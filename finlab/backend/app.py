"""API do Gab's FinLab.

FastAPI fino: serve o front estático e devolve JSON. Todo o cálculo de
valuation interativo acontece no navegador; aqui ficam coleta, normalização
contábil, score e o proxy dos agentes de IA.
"""

from __future__ import annotations

import json
import statistics
from typing import Optional

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import calls, promessas  # noqa: F401  (rotas abaixo)
from . import (agents, b3data, bdrs, cache, cvm, docs, etfs, ipe, market, metrics,
               regime, scoring, universe, valuation, xlsx_dcf)
from .settings import DEMO_MODE, TTL_CVM, TTL_QUOTE, WEB_DIR

app = FastAPI(title="Gab's FinLab", version="2.0", docs_url="/api/docs")


@app.middleware("http")
async def _sem_cache_heuristico(request, call_next):
    """Força o navegador a revalidar HTML e assets a cada visita.

    Sem Cache-Control, os navegadores aplicam "frescor heurístico" e reutilizam
    JS/CSS antigos do cache sem perguntar ao servidor — depois de um git pull,
    a página carrega com metade dos scripts desatualizados e quebra de formas
    silenciosas. `no-cache` não desliga o cache: só exige a revalidação
    (respostas 304 continuam baratas).
    """
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/assets") or not path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# ---------------------------------------------------------------------------
# Camada de dados
# ---------------------------------------------------------------------------

def _fundamentals(ticker: str) -> dict:
    # A versão na chave sobe SEMPRE que o formato do payload muda. O cache vive
    # em disco com TTL de 24 h: sem o bump, quem der git pull passa um dia
    # inteiro vendo o painel novo alimentado pelo blob antigo — que aqui
    # significaria classificar o regime sem os campos que o classificador lê.
    return cache.memoize(f"fund:v4:{ticker}", TTL_CVM, lambda: metrics.fundamentals(ticker)) or {}


def _overview_rows() -> dict:
    """Monta a tabela da tela principal: mercado + fundamentos + score."""
    def build():
        tickers = universe.TICKERS
        series = market.price_series(tickers)
        quotes = market.brapi_quotes(tickers)
        # Uma leitura de macro para as 90: o EPV precisa do WACC, e o WACC
        # precisa de Rf/CDI, que são os mesmos para o painel inteiro.
        macro_data = market.macro()

        rows = []
        for comp in universe.UNIVERSE:
            fund = _fundamentals(comp.ticker)
            if not fund:
                continue
            brapi = quotes.get(comp.ticker)
            snap = metrics.market_snapshot(comp.ticker, series.get(comp.ticker, []), brapi, fund)
            mult = metrics.multiples(fund, snap, brapi)
            sc = scoring.score(fund.get("indicadores", {}), fund.get("financial", False))
            base = fund.get("base") or {}
            ind = fund.get("indicadores") or {}
            rows.append({
                "ticker": comp.ticker,
                "name": comp.name,
                "sector": comp.sector,
                "financial": fund.get("financial", False),
                "last_year": fund.get("last_year"),
                "price": snap.get("price"),
                "price_date": snap.get("price_date"),
                "price_source": snap.get("price_source"),
                "market_cap": snap.get("market_cap"),
                "perf": snap.get("perf"),
                "multiples": mult,
                "score": sc.get("total"),
                "score_band": scoring.band(sc.get("total")),
                "grade": scoring.grade(sc.get("total")),
                "cobertura": sc.get("cobertura"),
                "parcial": sc.get("parcial"),
                # A tela principal carregava só múltiplos e nota. A mesa,
                # perguntada sobre o conjunto ("quais estão mais perto do
                # próprio valor de poder de lucro?"), não tinha como
                # responder sem abrir empresa por empresa. Agora o essencial
                # do dossiê de cada uma viaja junto da linha.
                "valor": _epv_da_linha(fund, snap, macro_data, brapi),
                "porte": {
                    "receita": base.get("receita"),
                    "lucro_liquido": base.get("lucro_liquido"),
                    "ebitda": base.get("ebitda"),
                    "fcl": base.get("fcl"),
                    "divida_liquida": base.get("divida_liquida"),
                    "patrimonio_liquido": base.get("patrimonio_liquido"),
                },
                "qualidade": {
                    "mg_ebitda": ind.get("mg_ebitda"),
                    "mg_liquida": ind.get("mg_liquida"),
                    "roic": ind.get("roic"),
                    "cagr_receita_3a": ind.get("cagr_receita_3a"),
                    "cagr_lucro_3a": ind.get("cagr_lucro_3a"),
                    "consistencia_lucro": ind.get("consistencia_lucro"),
                },
                "pilares": [{"key": p["key"], "label": p["label"], "score": p["score"]}
                            for p in sc.get("pilares", [])],
            })

        rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0), r["ticker"]))
        for i, row in enumerate(rows, start=1):
            row["rank"] = i

        return {
            "rows": rows,
            "sector_stats": _sector_stats(rows),
            "demo": DEMO_MODE,
            "cvm_disponivel": cvm.available(),
        }

    # v5: a linha ganhou valor (EPV), porte e qualidade. Sem o bump, quem já
    # tem o blob antigo veria a mesa dizer que não tem o dado que existe.
    return _com_diagnostico(cache.memoize("overview:v5", TTL_QUOTE, build) or {"rows": []})


def _epv_da_linha(fund: dict, snap: dict, macro_data: dict,
                  brapi: Optional[dict]) -> dict:
    """EPV por ação e a distância dele para o preço de tela.

    Só para quem o método comporta: em banco e seguradora o EPV pela firma
    não significa nada, e o campo sai vazio em vez de sair errado.
    """
    # O LPA vale para todo mundo — inclusive banco, onde é a métrica central.
    # Só o EPV é que não se aplica a instituição financeira.
    lucro = (fund.get("base") or {}).get("lucro_liquido")
    acoes = snap.get("shares_quote")
    out = {"epv_por_acao": None, "epv_upside": None, "wacc": None,
           "lpa": round(lucro / acoes, 4) if lucro is not None and acoes else None}
    if fund.get("financial"):
        return out
    try:
        prem = valuation.assumptions(fund, snap, macro_data or {}, brapi)
        v = valuation.epv(prem)
    except Exception:
        # A tela principal não pode cair por causa de uma empresa com dado
        # torto: sem valor, a linha continua com múltiplos e nota.
        return out
    out["epv_por_acao"] = round(v["por_acao"], 4) if v.get("por_acao") is not None else None
    out["epv_upside"] = round(v["upside"], 4) if v.get("upside") is not None else None
    out["wacc"] = prem.get("wacc")
    return out


def _com_diagnostico(payload: dict) -> dict:
    """Acrescenta o estado das fontes a um payload vindo do cache.

    Isto NÃO pode entrar no blob memoizado: o cache vive em disco e sobrevive
    ao restart, então quem acabou de preencher o BRAPI_TOKEN e reiniciou
    continuaria vendo "rodando sem token" pelo resto do TTL — exatamente o
    contrário do que o painel deveria dizer.
    """
    out = dict(payload)
    out["providers"] = market.provider_status()
    out["source"] = market.source_label()
    return out


def _sector_stats(rows: list[dict]) -> dict:
    """Mediana dos múltiplos e do score por setor, para comparação de pares."""
    out: dict[str, dict] = {}
    keys = ["pl", "pvp", "ev_ebitda", "dy", "roe", "mg_ebitda", "nd_ebitda"]
    for sector in universe.SECTORS:
        grupo = [r for r in rows if r["sector"] == sector]
        if not grupo:
            continue
        stats: dict[str, Optional[float]] = {}
        for key in keys:
            vals = [r["multiples"].get(key) for r in grupo]
            vals = [v for v in vals if v is not None and -1e6 < v < 1e6]
            # P/L e EV/EBITDA negativos não entram na mediana do setor:
            # empresa com prejuízo distorce a referência de "caro/barato".
            if key in ("pl", "ev_ebitda", "pvp"):
                vals = [v for v in vals if v > 0]
            stats[key] = round(statistics.median(vals), 3) if vals else None
        notas = [r["score"] for r in grupo if r["score"] is not None]
        stats["score"] = round(statistics.median(notas), 1) if notas else None
        stats["n"] = len(grupo)
        out[sector] = stats
    return out


# ---------------------------------------------------------------------------
# Rotas de dados
# ---------------------------------------------------------------------------

@app.get("/api/universe")
def api_universe():
    payload = universe.as_payload()
    payload["bdrs"] = [{"ticker": b.ticker, "name": b.name, "sector": b.sector}
                       for b in bdrs.UNIVERSE]
    payload["bdr_sectors"] = bdrs.SECTORS
    return payload


@app.get("/api/overview")
def api_overview():
    return _overview_rows()


@app.get("/api/macro")
def api_macro():
    return market.macro()


@app.get("/api/config")
def api_config():
    return {
        "providers": agents.provider_list(),
        "agents": agents.agent_list(),
        "market_providers": market.provider_status(),
        "demo": DEMO_MODE,
        "source": market.source_label(),
    }


@app.get("/api/company/{ticker}/promessas")
def api_promessas(ticker: str):
    """Placar de promessas da gestão para este ticker."""
    return promessas.placar(_ticker_valido(ticker))


@app.post("/api/company/{ticker}/promessas")
def api_promessa_nova(ticker: str, body: dict = Body(...)):
    try:
        return promessas.registrar(_ticker_valido(ticker), body or {})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/company/{ticker}/promessas/{promessa_id}")
def api_promessa_versao(ticker: str, promessa_id: str, body: dict = Body(...)):
    """Nova versão: dar baixa, corrigir prazo, anotar. Nunca sobrescreve."""
    try:
        return promessas.atualizar(_ticker_valido(ticker), promessa_id, body or {})
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Promessa não encontrada.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/company/{ticker}/promessas/{promessa_id}")
def api_promessa_remover(ticker: str, promessa_id: str):
    if not promessas.remover(_ticker_valido(ticker), promessa_id):
        raise HTTPException(status_code=404, detail="Promessa não encontrada.")
    return {"ok": True}


@app.get("/api/company/{ticker}/calls")
def api_calls(ticker: str):
    """Transcrições de teleconferência já indexadas para este ticker."""
    comp = universe.get(_ticker_valido(ticker))
    return {"calls": calls.listar(comp.cd_cvm) if comp else []}


@app.post("/api/company/{ticker}/calls")
def api_call_nova(ticker: str, body: dict = Body(...)):
    """Indexa uma transcrição colada pelo usuário.

    O painel não transcreve: de onde veio o texto — ASR local, serviço pago
    ou o site de RI — é escolha de quem usa. Aqui ele é segmentado em pares
    pergunta→resposta e entra no MESMO índice dos documentos da CVM, então a
    mesa passa a citá-lo com data e `doc ID` como qualquer outro.
    """
    comp = universe.get(_ticker_valido(ticker))
    if comp is None or not comp.cd_cvm:
        raise HTTPException(status_code=400,
                            detail="Empresa sem código CVM — não dá para indexar.")
    try:
        return calls.indexar(comp.cd_cvm, (body or {}).get("data") or "",
                             (body or {}).get("texto") or "",
                             (body or {}).get("titulo") or "",
                             (body or {}).get("link") or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/company/{ticker}/calls/{protocolo}")
def api_call_remover(ticker: str, protocolo: str):
    comp = universe.get(_ticker_valido(ticker))
    if comp is None or not calls.remover(comp.cd_cvm, protocolo):
        raise HTTPException(status_code=404, detail="Transcrição não encontrada.")
    return {"ok": True}


def _ticker_valido(ticker: str) -> str:
    tk = (ticker or "").upper().strip()
    if not universe.get(tk) and not bdrs.get(tk):
        raise HTTPException(status_code=404, detail=f"Ticker fora do universo: {tk}")
    return tk


@app.get("/api/company/{ticker}/docs")
def api_company_docs(ticker: str, q: str = ""):
    """Busca no conteúdo dos documentos indexados da empresa (BM25/FTS5).

    Sem `q`, devolve os documentos mais recentes com o primeiro trecho — a
    resposta de "o que a empresa comunicou por último". Sem índice (o pipeline
    ainda não rodou com --docs), lista vazia e o painel segue só com o IPE.
    """
    ticker = ticker.upper().strip()
    comp = universe.get(ticker)
    if comp is None:
        raise HTTPException(status_code=404, detail=f"Ticker fora do universo: {ticker}")
    q = q.strip()
    trechos = docs.search(comp.cd_cvm, q) if q else docs.recentes(comp.cd_cvm)
    return {"ticker": ticker, "q": q or None, "disponivel": docs.available(),
            "trechos": trechos}


@app.get("/api/company/{ticker}")
def api_company(ticker: str):
    ticker = ticker.upper().strip()
    comp = universe.get(ticker)
    if comp is None:
        if bdrs.get(ticker):
            return _bdr_payload(ticker)
        raise HTTPException(status_code=404, detail=f"Ticker fora do universo coberto: {ticker}")

    fund = _fundamentals(ticker)
    if not fund:
        raise HTTPException(status_code=404, detail=f"Sem dados para {ticker}")

    series = market.price_series([ticker]).get(ticker, [])
    brapi = market.brapi_fundamentals(ticker) or market.brapi_quotes([ticker]).get(ticker)
    snap = metrics.market_snapshot(ticker, series, brapi, fund)
    mult = metrics.multiples(fund, snap, brapi)
    sc = scoring.score(fund.get("indicadores", {}), fund.get("financial", False))
    macro_data = market.macro()
    # O regime vem antes das premissas: é ele que diz se a média de 3 anos
    # descreve o run-rate desta empresa ou o de outra que ela já foi.
    reg = regime.classificar(fund)
    prem = valuation.assumptions(fund, snap, macro_data, brapi, reg=reg)

    overview = _overview_rows()
    stats = (overview.get("sector_stats") or {}).get(comp.sector, {})
    pares = [r for r in overview.get("rows", []) if r["sector"] == comp.sector]

    return {
        "fundamentals": fund,
        "market": snap,
        "multiples": mult,
        "score": sc,
        "assumptions": prem,
        "macro": macro_data,
        "sector_stats": stats,
        "sector_label": universe.SECTORS[comp.sector]["label"],
        "peers": [{"ticker": p["ticker"], "name": p["name"], "score": p["score"],
                   "multiples": p["multiples"], "price": p["price"], "perf": p["perf"]}
                  for p in pares],
        "price_series": [{"d": d, "p": p} for d, p in series[-500:]],
        "consenso": _consenso(brapi),
        "itr": cvm.latest_quarter(comp.cd_cvm),
        "trimestral": cvm.quarterly_series(comp.cd_cvm),
        "ltm": cvm.ltm_series(comp.cd_cvm),
        # DRE de leitura: as tabelas da página nova (spec 4.3). Vem montada do
        # backend porque a montagem é contábil — códigos de conta, D&A da DFC,
        # desacumulação do ITR —, não formatação.
        "dre": {"anual": cvm.dre_anual(comp.cd_cvm),
                "trimestral": cvm.dre_trimestral(comp.cd_cvm)},
        "ipe": ipe.documentos(comp.cd_cvm),
        "docs": docs.stats(comp.cd_cvm),
        "calls": calls.listar(comp.cd_cvm),
        "promessas": promessas.placar(ticker),
        "regime": reg,
        "source": snap.get("price_source"),
    }


@app.get("/api/company/{ticker}/dcf.xlsx")
def api_company_dcf_xlsx(ticker: str):
    """A planilha DCF do redesenho (spec 4.1): dados do painel preenchidos,
    premissas em 3 cenários e só fórmulas nos resultados. A página não calcula
    mais preço justo — quem simula é o usuário, no Excel."""
    ticker = ticker.upper().strip()
    comp = universe.get(ticker)
    if comp is None:
        raise HTTPException(status_code=404,
                            detail=f"Planilha disponível só para as ações da B3 do universo: {ticker}")
    fund = _fundamentals(ticker)
    if not fund:
        raise HTTPException(status_code=404, detail=f"Sem dados para {ticker}")

    series = market.price_series([ticker]).get(ticker, [])
    brapi = market.brapi_fundamentals(ticker) or market.brapi_quotes([ticker]).get(ticker)
    snap = metrics.market_snapshot(ticker, series, brapi, fund)
    reg = regime.classificar(fund)
    prem = valuation.assumptions(fund, snap, market.macro(), brapi, reg=reg)

    try:
        blob = xlsx_dcf.planilha(ticker, prem, fund)
    except xlsx_dcf.SemDados as e:
        raise HTTPException(status_code=400, detail=str(e))

    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{ticker}-DCF.xlsx"'})


def _consenso(brapi: Optional[dict]) -> dict:
    """Preço-alvo e recomendação de analistas, quando a BRAPI fornece."""
    if not brapi:
        return {}
    fd = brapi.get("financialData")
    if not isinstance(fd, dict):
        return {}
    return {
        "alvo_medio": fd.get("targetMeanPrice"),
        "alvo_alto": fd.get("targetHighPrice"),
        "alvo_baixo": fd.get("targetLowPrice"),
        "recomendacao": fd.get("recommendationKey"),
        "analistas": fd.get("numberOfAnalystOpinions"),
    }


# ---------------------------------------------------------------------------
# ETFs
# ---------------------------------------------------------------------------

def _etf_rows() -> dict:
    def build():
        uni = etfs.universe()
        tickers = [e["ticker"] for e in uni]
        series = market.asset_series(tickers)
        boletim = b3data.bdi()

        rows = []
        for etf in uni:
            tk = etf["ticker"]
            perf = market.performance(series.get(tk, []))
            liq = (boletim.get(tk) or {}).get("avg_vol")
            rows.append({
                **etf,
                "price": perf.get("price"),
                "price_date": perf.get("date"),
                "perf": {k: perf.get(k) for k in ("day", "week", "m3", "m12", "ytd")},
                "liquidez": liq,
                "liquidez_faixa": etfs.liquidity_band(liq),
                "pregoes": (boletim.get(tk) or {}).get("days", 0),
            })
        # Mais líquidos primeiro dentro de cada categoria.
        rows.sort(key=lambda r: -(r["liquidez"] or 0))
        return {"rows": rows, "categories": etfs.CATEGORIES}
    return _com_diagnostico(cache.memoize("etfs:rows:v1", TTL_QUOTE, build) or {"rows": []})


@app.get("/api/etfs")
def api_etfs():
    return _etf_rows()


@app.get("/api/etf/{ticker}")
def api_etf(ticker: str):
    ticker = ticker.upper().strip()
    etf = etfs.get(ticker)
    if etf is None:
        raise HTTPException(status_code=404, detail=f"ETF fora da lista B3: {ticker}")

    series = market.asset_series([ticker]).get(ticker, [])
    perf = market.performance(series)
    boletim = b3data.bdi()
    liq = (boletim.get(ticker) or {}).get("avg_vol")

    todos = _etf_rows().get("rows", [])
    pares = [r for r in todos if r["categoria"] == etf["categoria"] and r["ticker"] != ticker]

    return {
        **etf,
        "price": perf.get("price"),
        "price_date": perf.get("date"),
        "perf": {k: perf.get(k) for k in ("day", "week", "m3", "m12", "ytd")},
        "liquidez": liq,
        "liquidez_faixa": etfs.liquidity_band(liq),
        "pregoes": (boletim.get(ticker) or {}).get("days", 0),
        "price_series": [{"d": d, "p": p} for d, p in series[-500:]],
        "peers": [{k: p[k] for k in ("ticker", "nome", "taxa_adm", "liquidez",
                                     "price", "perf", "pl", "curado")}
                  for p in pares[:15]],
        "categoria_meta": etfs.CATEGORIES.get(etf["categoria"], {}),
        "source": market.source_label(),
    }


# ---------------------------------------------------------------------------
# BDRs
# ---------------------------------------------------------------------------

def _bdr_rows() -> dict:
    def build():
        tickers = bdrs.TICKERS
        series = market.asset_series(tickers)
        quotes = market.brapi_quotes(tickers)
        boletim = b3data.bdi()

        rows = []
        for bdr in bdrs.UNIVERSE:
            tk = bdr.ticker
            perf = market.performance(series.get(tk, []))
            price = perf.get("price")
            quote = quotes.get(tk)
            if quote and quote.get("regularMarketPrice"):
                price = float(quote["regularMarketPrice"])
                chg = quote.get("regularMarketChangePercent")
                if chg is not None:
                    perf["day"] = float(chg) / 100.0
            liq = (boletim.get(tk) or {}).get("avg_vol")
            dy = quote.get("dividendYield") if quote else None
            rows.append({
                "ticker": tk, "name": bdr.name, "us_ticker": bdr.us_ticker,
                "sector": bdr.sector, "bank": bdr.bank,
                "price": price,
                "price_date": perf.get("date"),
                "perf": {k: perf.get(k) for k in ("day", "week", "m3", "m12", "ytd")},
                "liquidez": liq,
                "liquidez_faixa": etfs.liquidity_band(liq),
                "dy": (float(dy) / 100.0) if dy is not None else None,
            })
        rows.sort(key=lambda r: -(r["liquidez"] or 0))
        return {"rows": rows, "sectors": {k: v for k, v in bdrs.SECTORS.items()}}
    saida = _com_diagnostico(cache.memoize("bdrs:rows:v1", TTL_QUOTE, build) or {"rows": []})
    saida["brapi"] = bool(market.BRAPI_TOKEN)
    return saida


@app.get("/api/bdrs")
def api_bdrs():
    return _bdr_rows()


def _bdr_payload(ticker: str) -> dict:
    """Payload no formato de /api/company, para o painel reusar a tela."""
    bdr = bdrs.get(ticker)
    if bdr is None:
        raise HTTPException(status_code=404, detail=f"BDR fora do universo: {ticker}")

    # Só resultados COM dados entram no cache de 24h: uma falha transitória do
    # Yahoo não pode condenar o BDR a um dia inteiro sem fundamentos.
    chave_bundle = f"bdr:bundle:v2:{ticker}"
    bundle = cache.get(chave_bundle, TTL_CVM)
    if not bundle or not bundle.get("fonte"):
        bundle = bdrs.fetch_fundamentals(ticker) or {}
        if bundle.get("fonte"):
            cache.set(chave_bundle, bundle)
    fund = bundle.get("fund") or bdrs.fundamentals_from_modules(bdr, None)
    yahoo_info = bundle.get("info") or {}

    series = market.asset_series([ticker]).get(ticker, [])
    quote = market.brapi_quotes([ticker]).get(ticker)
    perf = market.performance(series)
    price = perf.get("price")
    source = market.source_label()
    if quote and quote.get("regularMarketPrice"):
        price = float(quote["regularMarketPrice"])
        source = "BRAPI"
        chg = quote.get("regularMarketChangePercent")
        if chg is not None:
            perf["day"] = float(chg) / 100.0

    macro_data = market.macro()
    prem = valuation.bdr_assumptions(fund, {"price": price}, macro_data, quote, yahoo_info)

    snap = {
        "price": price,
        "price_date": perf.get("date"),
        "price_source": source,
        "perf": {k: perf.get(k) for k in ("day", "week", "m3", "m12", "ytd")},
        "shares": prem.get("shares"),
        "shares_quote": prem.get("shares"),
        "unit_ratio": 1,
        "shares_source": "sintético: mcap USD ÷ preço do BDR",
        "market_cap": prem.get("mcap_usd"),
        "market_cap_source": "BRAPI (convertido a USD pela PTAX)" if prem.get("mcap_usd") else None,
        "points": len(series or []),
    }

    base = fund.get("base", {})
    mcap_usd = prem.get("mcap_usd")
    dl = base.get("divida_liquida")
    ev = (mcap_usd + dl) if (mcap_usd is not None and dl is not None
                             and not fund.get("financial")) else None
    dy = bdrs.yahoo_dividend_yield(yahoo_info)
    if dy is None and quote and quote.get("dividendYield") is not None:
        try:
            dy = float(quote["dividendYield"]) / 100.0
        except (TypeError, ValueError):
            dy = None
    mult = {
        "pl": metrics.div(mcap_usd, base.get("lucro_liquido")),
        "pvp": metrics.div(mcap_usd, base.get("patrimonio_liquido")),
        "ev_ebitda": metrics.div(ev, base.get("ebitda")),
        "ev_ebit": metrics.div(ev, base.get("ebit")),
        "psr": metrics.div(mcap_usd, base.get("receita")),
        "dy": dy,
        "roe": fund.get("indicadores", {}).get("roe"),
        "mg_ebitda": fund.get("indicadores", {}).get("mg_ebitda"),
        "nd_ebitda": fund.get("indicadores", {}).get("nd_ebitda"),
        "ev": ev, "lpa": None, "vpa": None,
        "fcf_yield": metrics.div(base.get("fcl"), mcap_usd),
    }

    sc = scoring.score(fund.get("indicadores", {}), fund.get("financial", False))

    todos = _bdr_rows().get("rows", [])
    pares = [r for r in todos if r["sector"] == bdr.sector]

    return {
        "fundamentals": fund,
        "market": snap,
        "multiples": mult,
        "score": sc,
        "assumptions": prem,
        "macro": macro_data,
        "sector_stats": {},
        "sector_label": bdrs.SECTORS[bdr.sector]["label"],
        "peers": [{"ticker": p["ticker"], "name": p["name"], "score": None,
                   "multiples": {"dy": p.get("dy")}, "price": p["price"],
                   "perf": p["perf"], "liquidez": p.get("liquidez")}
                  for p in pares if p["ticker"] != ticker],
        "price_series": [{"d": d, "p": p} for d, p in series[-500:]],
        "consenso": _consenso_bdr(yahoo_info, price) or _consenso(quote),
        "source": source,
        "fonte_fundamentos": bundle.get("fonte"),
        "bdr": True,
    }


def _consenso_bdr(info: dict, preco_bdr) -> dict:
    """Preço-alvo de analistas do Yahoo, convertido para 'por BDR'.

    O alvo vem em USD por ação de origem; convertê-lo pela mesma identidade do
    valuation (alvo/preço de origem × preço do BDR) devolve um número na moeda
    e na escala que o usuário vê na tela.
    """
    if not info or not preco_bdr:
        return {}
    atual = info.get("currentPrice") or info.get("regularMarketPrice")
    alvo = info.get("targetMeanPrice")
    try:
        atual = float(atual)
        alvo_m = float(alvo)
    except (TypeError, ValueError):
        return {}
    if atual <= 0:
        return {}

    def conv(chave):
        try:
            return round(float(info[chave]) / atual * preco_bdr, 2)
        except (TypeError, ValueError, KeyError):
            return None

    return {
        "alvo_medio": round(alvo_m / atual * preco_bdr, 2),
        "alvo_alto": conv("targetHighPrice"),
        "alvo_baixo": conv("targetLowPrice"),
        "recomendacao": info.get("recommendationKey"),
        "analistas": info.get("numberOfAnalystOpinions"),
        "fonte": "Yahoo Finance · convertido para R$ por BDR",
    }


# ---------------------------------------------------------------------------
# Agentes
# ---------------------------------------------------------------------------

@app.post("/api/llm/models")
def api_llm_models(body: dict = Body(...)):
    """Modelos que a chave informada pode usar naquele provedor."""
    provider = (body.get("provider") or "").strip()
    api_key = (body.get("api_key") or "").strip()
    try:
        return agents.list_models(provider, api_key)
    except agents.LLMError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/docs/extrair")
async def api_docs_extrair(request: Request):
    """Extrai o texto de um PDF enviado pelo chat (corpo binário, sem gravação).

    O corpo é o PDF cru — sem multipart, sem dependência nova. O texto volta
    para o navegador e é ELE quem decide mandar junto da próxima pergunta;
    o servidor não guarda nada, mesma regra das chaves de API.
    """
    conteudo = await request.body()
    if not conteudo:
        raise HTTPException(status_code=400, detail="Envie o PDF no corpo da requisição.")
    try:
        return docs.extrair_pdf(conteudo)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/agents/chat")
def api_agent_chat(body: dict = Body(...)):
    """Conversa livre com a mesa, no contexto do ativo aberto na tela."""
    slot = body.get("slot") or {}
    api_key = (slot.get("api_key") or "").strip()
    model = (slot.get("model") or "").strip()
    if not api_key or not model:
        raise HTTPException(status_code=400,
                            detail="Configure um slot com chave e modelo em ⚙ Modelos de IA.")

    pergunta = (body.get("pergunta") or "").strip()
    if not pergunta:
        raise HTTPException(status_code=400, detail="Escreva uma pergunta.")

    # Quem fala: um especialista, a mesa junta (None) ou a conclusão da rodada.
    agente = (body.get("agente") or "").strip() or None
    if agente and agente != "sintese" and agente not in agents.AGENTS:
        raise HTTPException(status_code=400, detail=f"Agente desconhecido: {agente}")

    # Quem lê a rodada recebe as falas dos outros dentro da própria pergunta:
    # a "sintese" para concluir, o Cético para contestar, o Moderador para
    # mapear. O fechamento diz a cada um o que fazer com o que leu.
    respostas = body.get("respostas") or []
    if agente == "sintese":
        pergunta = agents.monta_pergunta_sintese(pergunta, respostas)
    elif agente and respostas and (agente in agents.FECHAMENTO_DA_RODADA
                                   or agents.AGENTS.get(agente, {}).get("le_a_mesa")):
        pergunta = agents.monta_pergunta_sintese(
            pergunta, respostas,
            agents.FECHAMENTO_DA_RODADA.get(agente, "Comente agora o que a mesa disse."))

    ticker = (body.get("ticker") or "").upper().strip()
    tela = (body.get("tela") or "").strip().lower()
    trechos_docs: list = []
    if ticker and (universe.get(ticker) or bdrs.get(ticker)):
        payload = api_company(ticker)
        contexto = agents.build_context(
            payload,
            body.get("assumptions") or payload["assumptions"],
            body.get("resultado") or {},
            payload.get("macro") or {},
        )
        # Recuperação sobre o CONTEÚDO dos documentos (2.3): a pergunta do
        # usuário é a consulta. O bloco carrega data e link em cada trecho, e
        # a abstenção vem pronta quando nada é recuperado — desde que o índice
        # exista; sem ele, nada é dito para o modelo não negar documento que
        # simplesmente não foi ingerido.
        comp = universe.get(ticker)
        if comp is not None and docs.available():
            trechos_docs = docs.search(comp.cd_cvm, pergunta)
            if not trechos_docs:
                trechos_docs = docs.recentes(comp.cd_cvm)
            contexto += "\n\n" + docs.bloco_contexto(trechos_docs)

    elif tela in ("acoes", "etfs", "bdrs"):
        # Telas de lista: a mesa enxerga a tabela inteira que está na tela —
        # é o que permite perguntar sobre o conjunto ("quais para uma carteira?").
        macro_data = market.macro()
        if tela == "acoes":
            contexto = agents.contexto_lista_acoes(_overview_rows(), macro_data,
                                                   universe.SECTORS)
        elif tela == "etfs":
            contexto = agents.contexto_lista_etfs(_etf_rows(), macro_data,
                                                  etfs.CATEGORIES)
        else:
            contexto = agents.contexto_lista_bdrs(_bdr_rows(), macro_data,
                                                  bdrs.SECTORS)
        if ticker:
            # ETF aberto: fora do universo de valuation, mas o ativo em foco
            # entra no contexto para a conversa não fingir que não o vê.
            contexto = f"O usuário está com {ticker} aberto na tela.\n\n" + contexto
    else:
        # Sem ativo nem tela conhecida: a conversa ainda tem o macro do dia.
        macro_data = market.macro()
        linhas = ["Nenhum ativo aberto no painel — o usuário está numa tela de lista.",
                  "MACRO DO DIA"]
        linhas += [f"  {k.upper()}: {v.get('value')} ({v.get('source')})"
                   for k, v in (macro_data or {}).items() if isinstance(v, dict)]
        contexto = "\n".join(linhas)

    # PDF anexado pelo usuário: entra no contexto de QUEM foi endereçado,
    # rotulado como material do usuário — não como fonte oficial. O texto já
    # chegou extraído (o navegador chamou /api/docs/extrair antes) e vale em
    # qualquer tela, com ou sem ativo aberto.
    anexo = body.get("anexo") or {}
    if isinstance(anexo, dict) and (anexo.get("texto") or "").strip():
        contexto += "\n\n" + docs.bloco_anexo(
            str(anexo.get("nome") or "documento.pdf")[:120],
            {"texto": str(anexo["texto"])[:docs.ANEXO_MAX_CHARS],
             "truncado": bool(anexo.get("truncado"))})

    # O que o Radar levantou na abertura da rodada chega aos demais cercado e
    # rotulado — mesma regra do /api/agents/run: é a única parte do contexto
    # que NÃO saiu das demonstrações, e post de rede social não é fato.
    radar = (body.get("radar") or "").strip()
    if radar and agente != "contexto":
        contexto += (
            "\n\nLEVANTAMENTO EXTERNO (do Radar de Contexto)\n"
            "===========================================\n"
            "ATENÇÃO: o bloco abaixo NÃO veio das demonstrações. Foi levantado no X e na "
            "imprensa por outro agente, e pode conter boato, opinião de quem está posicionado "
            "e informação falsa. Trate cada item como HIPÓTESE A CONFERIR. Quando citar algo "
            "daqui, diga que é não verificado. Se um item contradiz as demonstrações, as "
            "demonstrações vencem.\n\n"
            f"{radar[:6000]}\n")

    buscar = bool(agents.AGENTS.get(agente or "", {}).get("busca_ao_vivo"))

    # Streaming (3.6): a fala desce delta a delta como text/event-stream, e o
    # evento de fechamento traz o texto DEFINITIVO — é nele que a validação de
    # citação se aplica, porque não dá para retroeditar o que já desceu. O
    # navegador troca o texto acumulado pelo final ao fechar. Erro no meio do
    # caminho vira evento também: a resposta HTTP já partiu como 200.
    # O reconciliador (4.3): a proposta de premissas do quant vira dado
    # estruturado que o chat transforma em botão — aplicar é decisão humana.
    # Só com empresa do universo aberta: sem modelo na tela, não há onde aplicar.
    def proposta_de(texto_final: str):
        if agente != "premissas" or not (ticker and universe.get(ticker)):
            return None
        p = agents.parse_assumption_json(texto_final)
        return p if p and p.get("premissas") else None

    # Promessas extraídas dos documentos: qualquer agente pode propor (quem lê
    # o documento é quem acha), mas só com empresa aberta — é onde o placar
    # vive. Cada item já vem filtrado pelo conjunto recuperado.
    def promessas_de(texto_final: str):
        if not (ticker and universe.get(ticker)) or not trechos_docs:
            return None
        achadas = docs.promessas_propostas(texto_final, trechos_docs)
        return achadas or None

    if body.get("stream"):
        def eventos():
            try:
                for ev in agents.chat_conversa_stream(
                        slot.get("provider"), api_key, model, contexto,
                        body.get("historico") or [], pergunta, agente, buscar):
                    if ev.get("fim"):
                        texto_final = docs.validar_citacoes(ev.get("texto") or "",
                                                            trechos_docs)
                        ev = {"fim": True, "texto": texto_final,
                              "uso": ev.get("uso"), "modelo": model,
                              "provedor": slot.get("provider"), "agente": agente,
                              "proposta": proposta_de(texto_final),
                              "promessas": promessas_de(texto_final)}
                    yield "data: " + json.dumps(ev, ensure_ascii=False) + "\n\n"
            except agents.LLMError as exc:
                yield "data: " + json.dumps({"erro": str(exc)},
                                            ensure_ascii=False) + "\n\n"
        return StreamingResponse(eventos(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store",
                                          "X-Accel-Buffering": "no"})

    try:
        texto = agents.chat_conversa(
            slot.get("provider"), api_key, model, contexto,
            body.get("historico") or [], pergunta, agente, buscar=buscar)
    except agents.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Validação de citação em código (03 §5): link do RAD que o modelo citou
    # sem ter recebido é invenção — sai marcado, não passa como fonte.
    texto = docs.validar_citacoes(texto, trechos_docs)

    return {"texto": texto, "modelo": model, "provedor": slot.get("provider"),
            "ticker": ticker or None, "agente": agente,
            "proposta": proposta_de(texto), "promessas": promessas_de(texto)}


@app.post("/api/agents/run")
def api_agent_run(body: dict = Body(...)):
    agent_key = body.get("agent")
    slot = body.get("slot") or {}
    if agent_key not in agents.AGENTS:
        raise HTTPException(status_code=400, detail=f"Agente desconhecido: {agent_key}")

    provider = slot.get("provider")
    api_key = (slot.get("api_key") or "").strip()
    model = (slot.get("model") or "").strip()
    if not api_key:
        raise HTTPException(status_code=400,
                            detail="Slot sem chave de API. Configure em ⚙ Modelos de IA.")
    if not model:
        raise HTTPException(status_code=400, detail="Slot sem modelo definido.")

    ticker = (body.get("ticker") or "").upper().strip()
    if not universe.get(ticker) and not bdrs.get(ticker):
        raise HTTPException(status_code=400, detail=f"Ticker inválido: {ticker}")

    payload = api_company(ticker)
    contexto = agents.build_context(
        payload,
        body.get("assumptions") or payload["assumptions"],
        body.get("resultado") or {},
        payload.get("macro") or {},
    )
    pergunta = (body.get("pergunta") or "").strip()

    # O conteúdo dos documentos entra na rodada (2.3): com pergunta, ela é a
    # consulta; sem, os documentos mais recentes — "o que a companhia
    # comunicou por último". Cada trecho com data e link.
    comp = universe.get(ticker)
    trechos_docs: list = []
    if comp is not None and docs.available():
        trechos_docs = docs.search(comp.cd_cvm, pergunta) if pergunta else []
        if not trechos_docs:
            trechos_docs = docs.recentes(comp.cd_cvm)
        contexto += "\n\n" + docs.bloco_contexto(trechos_docs)

    user = f"CONTEXTO\n========\n{contexto}\n"

    # O Radar de Contexto abre a rodada e o que ele levantou entra aqui. Vem
    # cercado e rotulado: é a única parte do contexto que NÃO saiu das
    # demonstrações, e os outros agentes precisam saber disso para não tratar
    # post de rede social como se fosse fato relevante.
    radar = (body.get("radar") or "").strip()
    if radar and agent_key != "contexto":
        user += (
            "\nLEVANTAMENTO EXTERNO (do Radar de Contexto)\n"
            "===========================================\n"
            "ATENÇÃO: o bloco abaixo NÃO veio das demonstrações. Ele foi levantado no X e na "
            "imprensa por outro agente, e pode conter boato, opinião de quem está posicionado "
            "e informação falsa. Trate cada item como HIPÓTESE A CONFERIR, nunca como fato "
            "estabelecido. Quando citar algo daqui, diga que é não verificado. Se um item "
            "contradiz as demonstrações acima, as demonstrações vencem.\n\n"
            f"{radar[:6000]}\n")

    # Cético e Moderador leem a rodada: sem as falas, não há o que contestar
    # nem o que mapear. Vem depois do contexto de propósito — o que os agentes
    # disseram é matéria de discussão, não fonte.
    falas = body.get("falas") or {}
    if falas and agents.AGENTS[agent_key].get("le_a_mesa"):
        blocos = []
        for chave, texto in falas.items():
            nome = (agents.AGENTS.get(chave) or {}).get("label", chave)
            if texto and chave != agent_key:
                blocos.append(f"--- {nome} ---\n{str(texto)[:4000]}")
        if blocos:
            user += ("\nFALAS DA MESA\n=============\n"
                     "O que os outros agentes escreveram nesta rodada. Isto é OPINIÃO deles, "
                     "não dado: o CONTEXTO acima é que manda.\n\n" + "\n\n".join(blocos) + "\n")

    if pergunta:
        user += f"\nPERGUNTA ADICIONAL DO USUÁRIO\n============================\n{pergunta}\n"

    try:
        texto = agents.chat(provider, api_key, model,
                            agents.AGENTS[agent_key]["system"], user,
                            buscar=bool(agents.AGENTS[agent_key].get("busca_ao_vivo")))
    except agents.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Link do RAD citado sem estar no conjunto recuperado é invenção — marcado
    # em código, não em prompt (03 §5).
    texto = docs.validar_citacoes(texto, trechos_docs)

    resposta = {"agent": agent_key, "ticker": ticker, "texto": texto,
                "modelo": model, "provedor": provider}
    if agent_key == "premissas":
        proposta = agents.parse_assumption_json(texto)
        if proposta:
            resposta["proposta"] = proposta
    return resposta


# ---------------------------------------------------------------------------
# Manutenção
# ---------------------------------------------------------------------------

@app.post("/api/cache/clear")
def api_cache_clear():
    removed = cache.clear()
    cvm.limpar_cache()
    cvm._shares_table.cache_clear()
    return {"ok": True, "arquivos_removidos": removed}


@app.get("/api/health")
def api_health():
    return {"ok": True, "cvm": cvm.available(), "demo": DEMO_MODE,
            "fonte_mercado": market.source_label(), "tickers": len(universe.TICKERS)}


# ---------------------------------------------------------------------------
# Front-end
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/empresa")
def empresa():
    return FileResponse(WEB_DIR / "empresa.html")


@app.get("/etfs")
def etfs_page():
    return FileResponse(WEB_DIR / "etfs.html")


@app.get("/etf")
def etf_page():
    return FileResponse(WEB_DIR / "etf.html")


@app.get("/bdrs")
def bdrs_page():
    return FileResponse(WEB_DIR / "bdrs.html")


@app.exception_handler(404)
def not_found(_request, exc):
    return JSONResponse(status_code=404, content={"detail": getattr(exc, "detail", "não encontrado")})


app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")
