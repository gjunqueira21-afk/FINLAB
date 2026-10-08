"""API do FinLab V2.

FastAPI fino: serve o front estático e devolve JSON. Aqui ficam coleta,
normalização contábil, score, endividamento e carteiras — sem valuation
interativo e sem mesa de IA.
"""

from __future__ import annotations

import json
import logging
import math
import statistics
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import carteiras  # noqa: F401  (rotas abaixo)
from . import (b3data, bdrs, cache, cvm, divida, etfs, market, metrics, scoring,
               snapshot, universe)
from .settings import DEMO_MODE, TTL_CVM, TTL_QUOTE, WEB_DIR

_log = logging.getLogger("finlab")


def _sem_nao_finitos(obj: Any, caminho: str = "", achados: Optional[list] = None) -> Any:
    """NaN e ±inf viram None, recursivamente.

    Conta com dado faltando (banco não tem EBITDA, trimestre sem linha na
    CVM) sai do pandas como NaN, e JSON não tem NaN: a resposta inteira
    virava erro 500. None chega à tela como "—", que é o que o painel já
    mostra para dado ausente. Os caminhos encontrados vão para o log, para a
    origem do NaN poder ser corrigida na fonte.
    """
    if isinstance(obj, float):
        if math.isfinite(obj):
            return obj
        if achados is not None and len(achados) < 5:
            achados.append(caminho or "(raiz)")
        return None
    if isinstance(obj, dict):
        return {k: _sem_nao_finitos(v, f"{caminho}.{k}" if caminho else str(k), achados)
                for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sem_nao_finitos(v, f"{caminho}[{i}]", achados) for i, v in enumerate(obj)]
    return obj


class JSONSeguro(JSONResponse):
    """JSONResponse que não quebra com NaN/inf — vira null, com aviso no log."""

    def render(self, content: Any) -> bytes:
        achados: list = []
        limpo = _sem_nao_finitos(content, achados=achados)
        if achados:
            _log.warning("valores não finitos trocados por null em: %s", ", ".join(achados))
        return json.dumps(limpo, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":")).encode("utf-8")


@asynccontextmanager
async def _ciclo_de_vida(_app):
    """Ao subir, confere se os fundamentos pré-calculados batem com a CVM no
    disco; se não, manda refazer num processo à parte (o painel responde
    calculando direto enquanto isso)."""
    try:
        if snapshot.precisa_gerar():
            snapshot.gerar_em_segundo_plano()
    except Exception:  # nunca impede o painel de subir
        _log.exception("checagem dos fundamentos pré-calculados falhou")
    yield


app = FastAPI(title="FinLab", version="2.0", docs_url="/api/docs",
              default_response_class=JSONSeguro, lifespan=_ciclo_de_vida)
# Compressão: a tela principal manda ~300 KB de JSON (90 ações × 3 fontes de
# múltiplos); comprimido, isso vira uma fração — o que mais pesa no celular.
app.add_middleware(GZipMiddleware, minimum_size=1024)


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
    # Do arquivo pré-calculado quando ele bate com a CVM no disco (o normal);
    # o cálculo direto abaixo é o caminho de quando ele ainda não existe.
    pronto = snapshot.empresa(ticker)
    if pronto is not None and pronto.get("fund"):
        return pronto["fund"]
    # A versão na chave sobe SEMPRE que o formato do payload muda. O cache vive
    # em disco com TTL de 24 h: sem o bump, quem der git pull passa um dia
    # inteiro vendo o painel novo alimentado pelo blob antigo.
    # v6: séries de dívida CP/LP e despesas financeiras (V2) — o v5 chegou a
    # ser gravado ANTES dessas séries existirem, então o bump é duplo.
    return cache.memoize(f"fund:v6:{ticker}", TTL_CVM, lambda: metrics.fundamentals(ticker)) or {}


def _ltm(cd_cvm: Optional[str]) -> dict:
    """12 meses móveis dos ITRs da CVM, com o mesmo cache das demonstrações:
    a tela principal pede os 90 de uma vez, e o ITR só muda com o pipeline."""
    if not cd_cvm:
        return {}
    pronto = snapshot.por_cd(cd_cvm)
    if pronto is not None:
        return pronto.get("ltm") or {}
    # v4: todas as contas na janela do último trimestre, saldo mais novo entre
    # ITR e DFP e a despesa financeira (cobertura de juros em 12 meses).
    # Vazio (ITR ainda não processado) não vai para o cache: senão o painel
    # passaria 24 h sem os 12 meses mesmo depois do atualizar-dados.sh.
    return cache.memoize(f"ltm:v4:{cd_cvm}", TTL_CVM,
                         lambda: cvm.ltm_series(cd_cvm) or None) or {}


def _overview_rows() -> dict:
    """Monta a tabela da tela principal: mercado + fundamentos + score."""
    def build():
        tickers = universe.TICKERS
        series = market.price_series(tickers)
        quotes = market.brapi_quotes(tickers)
        # Módulos de múltiplos (12 h de cache) somados à cotação (5 min): o
        # preço e o valor de mercado continuam vindo da cotação mais fresca.
        mods = market.brapi_multiplos(tickers)

        rows = []
        for comp in universe.UNIVERSE:
            fund = _fundamentals(comp.ticker)
            if not fund:
                continue
            brapi = quotes.get(comp.ticker)
            if mods.get(comp.ticker):
                brapi = {**mods[comp.ticker], **(brapi or {})}
            snap = metrics.market_snapshot(comp.ticker, series.get(comp.ticker, []), brapi, fund)
            por_fonte = metrics.multiplos_por_fonte(fund, snap, brapi, _ltm(comp.cd_cvm))
            mult = por_fonte["auto"]
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
                # As outras fontes, para o seletor da tela (o "auto" é `multiples`).
                "multiplos": {f: m for f, m in por_fonte.items() if f != "auto"},
                "score": sc.get("total"),
                "score_band": scoring.band(sc.get("total")),
                "grade": scoring.grade(sc.get("total")),
                "cobertura": sc.get("cobertura"),
                "parcial": sc.get("parcial"),
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
            "sector_stats_fontes": {f: _sector_stats(rows, f) for f in metrics.FONTES
                                    if f != "auto"},
            "demo": DEMO_MODE,
            "cvm_disponivel": cvm.available(),
        }

    # v8: sai o EPV ("valor") da linha — o V2 não faz valuation.
    # swr: com o cache vencido, entrega o anterior na hora e refaz por trás.
    return _com_diagnostico(cache.memoize_swr("overview:v8", TTL_QUOTE, build) or {"rows": []})


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


def _sector_stats(rows: list[dict], fonte: str = "auto") -> dict:
    """Mediana dos múltiplos e do score por setor, para comparação de pares.

    `fonte` escolhe o pacote de múltiplos da linha: a mediana tem de sair da
    mesma fonte que a tabela está mostrando.
    """
    out: dict[str, dict] = {}
    keys = ["pl", "pvp", "ev_ebitda", "dy", "roe", "mg_ebitda", "nd_ebitda"]
    for sector in universe.SECTORS:
        grupo = [r for r in rows if r["sector"] == sector]
        if not grupo:
            continue
        stats: dict[str, Optional[float]] = {}
        for key in keys:
            vals = [(r["multiples"] if fonte == "auto"
                     else (r.get("multiplos") or {}).get(fonte) or {}).get(key)
                    for r in grupo]
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
        "market_providers": market.provider_status(),
        "demo": DEMO_MODE,
        "source": market.source_label(),
    }


# ---------------------------------------------------------------------------
# Carteiras acompanhadas — montagem manual, acompanhamento quantitativo.
# É o que o cron chama; nada aqui usa LLM.
# ---------------------------------------------------------------------------

@app.get("/api/carteiras")
def api_carteiras():
    return {"carteiras": carteiras.listar()}


@app.post("/api/carteiras")
def api_carteira_criar(body: dict = Body(...)):
    try:
        c = carteiras.criar(body or {})
    except carteiras.CarteiraInvalida as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return carteiras.detalhe(c)


@app.post("/api/carteiras/atualizar-todas")
def api_carteiras_atualizar_todas():
    """O que o cron chama por HTTP; a CLI (`python -m finlab.backend.tarefas`)
    faz o mesmo sem passar pelo servidor."""
    return {"resultados": carteiras.atualizar_todas()}


def _carteira_ou_404(carteira_id: str) -> dict:
    c = carteiras.obter(carteira_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Carteira não encontrada.")
    return c


@app.get("/api/carteiras/{carteira_id}")
def api_carteira(carteira_id: str):
    return carteiras.detalhe(_carteira_ou_404(carteira_id))


@app.patch("/api/carteiras/{carteira_id}")
def api_carteira_editar(carteira_id: str, body: dict = Body(...)):
    try:
        return carteiras.detalhe(carteiras.editar(carteira_id, body or {}))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Carteira não encontrada.") from exc
    except carteiras.CarteiraInvalida as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/carteiras/{carteira_id}")
def api_carteira_remover(carteira_id: str):
    if not carteiras.remover(carteira_id):
        raise HTTPException(status_code=404, detail="Carteira não encontrada.")
    return {"ok": True}


@app.post("/api/carteiras/{carteira_id}/atualizar")
def api_carteira_atualizar(carteira_id: str):
    try:
        return carteiras.detalhe(carteiras.atualizar(carteira_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Carteira não encontrada.") from exc
    except carteiras.CarteiraInvalida as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/carteiras/{carteira_id}/rebalancear")
def api_carteira_rebalancear(carteira_id: str):
    try:
        return carteiras.detalhe(carteiras.rebalancear(carteira_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Carteira não encontrada.") from exc
    except carteiras.CarteiraInvalida as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/carteiras/{carteira_id}/lamina.md")
def api_carteira_lamina(carteira_id: str):
    """A lâmina quantitativa — gerada na hora."""
    return Response(content=carteiras.lamina_md(_carteira_ou_404(carteira_id)),
                    media_type="text/markdown; charset=utf-8")


# ---------------------------------------------------------------------------
# Empresa
# ---------------------------------------------------------------------------

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

    pronto = snapshot.empresa(ticker)
    series = market.price_series([ticker]).get(ticker, [])
    brapi = market.brapi_fundamentals(ticker) or market.brapi_quotes([ticker]).get(ticker)
    snap = metrics.market_snapshot(ticker, series, brapi, fund)
    ltm = _ltm(comp.cd_cvm)
    por_fonte = metrics.multiplos_por_fonte(fund, snap, brapi, ltm)
    sc = scoring.score(fund.get("indicadores", {}), fund.get("financial", False))

    overview = _overview_rows()
    stats = (overview.get("sector_stats") or {}).get(comp.sector, {})

    return {
        "fundamentals": fund,
        "market": snap,
        "multiples": por_fonte["auto"],
        "multiplos": {f: m for f, m in por_fonte.items() if f != "auto"},
        "score": sc,
        "sector_stats": stats,
        "sector_label": universe.SECTORS[comp.sector]["label"],
        "price_series": [{"d": d, "p": p} for d, p in series[-500:]],
        "consenso": _consenso(brapi),
        "itr": pronto["itr"] if pronto else cvm.latest_quarter(comp.cd_cvm),
        "ltm": ltm,
        # A DRE inteira numa grade: exercícios, trimestres de cada um (a tela
        # abre o ano clicado), o ano em curso e os últimos 12 meses.
        "dre": {"completa": pronto["dre"] if pronto else cvm.dre_completa(comp.cd_cvm)},
        "source": snap.get("price_source"),
    }


@app.get("/api/company/{ticker}/divida")
def api_company_divida(ticker: str):
    """Análise de endividamento: histórico CVM + retrato mais recente."""
    ticker = ticker.upper().strip()
    comp = universe.get(ticker)
    bdr = bdrs.get(ticker) if comp is None else None
    if comp is None and bdr is None:
        raise HTTPException(status_code=404, detail=f"Ticker fora do universo: {ticker}")

    if comp is not None:
        fund = _fundamentals(ticker)
        financial = bool(fund.get("financial"))
    else:
        payload = _bdr_payload(ticker)
        fund = payload["fundamentals"]
        financial = bool(fund.get("financial"))

    if financial:
        return {"ticker": ticker, "financial": True, "anos": [], "series": {},
                "atual": {}, "setor": {}, "avisos": [
                    "Instituição financeira: alavancagem se lê por Ativo/PL e "
                    "capital regulatório, não por dívida líquida/EBITDA."]}

    eh_bdr = comp is None
    anos = list(fund.get("years") or [])
    series = {k: list(v) for k, v in (fund.get("series") or {}).items()}
    ltm = _ltm(comp.cd_cvm) if comp is not None else {}
    campos = (ltm or {}).get("campos") or {}
    # O balanço do último trimestre entra como mais um ponto da série, depois
    # dos exercícios: sem ele, o gráfico e os indicadores param no ano
    # fechado e a alavancagem de hoje fica escondida atrás da de dezembro.
    # Fluxos (EBITDA, despesa financeira) desse ponto são os 12 meses.
    if (campos.get("divida_liquida") is not None and anos and ltm.get("exercicio")
            and ltm["exercicio"] > int(anos[-1])):
        anos.append(ltm.get("trimestre") or ltm.get("rotulo"))
        for k in set(series) | {"divida_bruta", "divida_liquida", "caixa_total",
                                "divida_cp", "divida_lp", "ebitda", "despesas_financeiras"}:
            series.setdefault(k, [None] * (len(anos) - 1)).append(campos.get(k))
    calc = divida.indicadores(anos, series)

    avisos = []
    if not anos:
        avisos.append("Sem demonstrações do Yahoo para este BDR agora — "
                      "recarregue mais tarde." if eh_bdr else
                      "Sem demonstrações processadas da CVM para este ticker — "
                      "rode o pipeline em valuation_cvm.")

    # Retrato mais recente: saldo do último ITR (ou da DFP, se for mais nova)
    # sobre o EBITDA dos últimos 12 meses.
    atual = {}
    if campos.get("divida_liquida") is not None:
        nd = None
        if campos.get("ebitda"):
            nd = campos["divida_liquida"] / campos["ebitda"]
        atual = {"divida_liquida": campos.get("divida_liquida"),
                 "divida_bruta": campos.get("divida_bruta"),
                 "caixa_total": campos.get("caixa_total"),
                 "nd_ebitda": nd,
                 "fonte": "CVM · ITR", "rotulo": (ltm or {}).get("rotulo"),
                 "saldo_em": ltm.get("saldo_em")}
    elif anos:
        i = len(anos) - 1
        atual = {"divida_liquida": calc["series"]["divida_liquida"][i],
                 "divida_bruta": calc["series"]["divida_bruta"][i],
                 "caixa_total": calc["series"]["caixa_total"][i],
                 "nd_ebitda": calc["series"]["nd_ebitda"][i],
                 # BDR não passa pela CVM: as demonstrações vêm do Yahoo, em
                 # USD — a etiqueta de origem tem de dizer isso.
                 "fonte": "Yahoo Finance · USD" if eh_bdr else "CVM · DFP",
                 "rotulo": f"exercício {anos[i]}"}

    # Medianas do setor (só para ações B3): ND/EBITDA do overview + as demais
    # calculadas dos fundamentos do setor inteiro, empresa incluída — a mesma
    # base da mediana de ND/EBITDA (cache de 24h já absorve o custo).
    setor = {}
    if comp is not None:
        stats = (_overview_rows().get("sector_stats") or {}).get(comp.sector) or {}
        chaves = ("cobertura_juros", "curto_prazo_pct", "liquidez_imediata",
                  "custo_aparente")
        valores: dict[str, list] = {k: [] for k in chaves}
        for tk in [ticker] + universe.peers(ticker):
            f = _fundamentals(tk)
            if not f or f.get("financial"):
                continue
            an = f.get("years") or []
            if not an:
                continue
            c = divida.indicadores(an, f.get("series") or {})
            for k in chaves:
                v = c["series"][k][-1]
                if v is not None:
                    valores[k].append(v)
        setor = {"nd_ebitda": stats.get("nd_ebitda"), "n": stats.get("n")}
        for k in chaves:
            setor[k] = round(statistics.median(valores[k]), 4) if valores[k] else None

    return {"ticker": ticker, "financial": False, "anos": anos,
            "series": calc["series"], "atual": atual, "setor": setor,
            "avisos": avisos}


@app.get("/api/company/{ticker}/pares")
def api_company_pares(ticker: str):
    """Pares do setor com as linhas completas do overview — a empresa junto."""
    ticker = ticker.upper().strip()
    comp = universe.get(ticker)
    if comp is None:
        raise HTTPException(status_code=404,
                            detail=f"Pares por setor só para as ações B3: {ticker}")
    ov = _overview_rows()
    rows = [dict(r, eu=(r["ticker"] == ticker))
            for r in ov.get("rows", []) if r["sector"] == comp.sector]
    return {"setor": comp.sector,
            "sector_label": universe.SECTORS[comp.sector]["label"],
            "stats": (ov.get("sector_stats") or {}).get(comp.sector, {}),
            "rows": rows}


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
    return _com_diagnostico(cache.memoize_swr("etfs:rows:v1", TTL_QUOTE, build) or {"rows": []})


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


@app.get("/api/etf/{ticker}/historico")
def api_etf_historico(ticker: str, janela: str = "12m"):
    ticker = ticker.upper().strip()
    if etfs.get(ticker) is None:
        raise HTTPException(status_code=404, detail=f"ETF fora da lista B3: {ticker}")
    if janela not in ("1m", "3m", "6m", "12m", "ytd", "max"):
        raise HTTPException(status_code=400, detail=f"Janela desconhecida: {janela}")
    serie = market.asset_series([ticker]).get(ticker, [])
    if janela == "max" and len(serie) < 1000:
        # histórico longo: o Yahoo cobre anos; funde com o local acumulado
        longo = market.yahoo_history(ticker, "10y")
        if longo:
            serie = market.merge_history({ticker: longo}).get(ticker, serie)
    rec = etfs.recorta_janela(serie, janela)
    return {"ticker": ticker, "janela": janela,
            "serie": [{"d": d, "p": p} for d, p in rec["serie"]],
            "retorno": rec["retorno"], "pontos": len(rec["serie"])}


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
    saida = _com_diagnostico(cache.memoize_swr("bdrs:rows:v1", TTL_QUOTE, build) or {"rows": []})
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

    mercado = bdrs.bdr_market(price, quote, yahoo_info)
    mcap_usd = mercado.get("mcap_usd")

    snap = {
        "price": price,
        "price_date": perf.get("date"),
        "price_source": source,
        "perf": {k: perf.get(k) for k in ("day", "week", "m3", "m12", "ytd")},
        "shares": mercado.get("shares"),
        "shares_quote": mercado.get("shares"),
        "unit_ratio": 1,
        "shares_source": "sintético: mcap USD ÷ preço do BDR",
        "market_cap": mcap_usd,
        "market_cap_source": mercado.get("mcap_fonte"),
        "points": len(series or []),
    }

    base = fund.get("base", {})
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

    O alvo vem em USD por ação de origem; convertê-lo pela mesma identidade
    (alvo/preço de origem × preço do BDR) devolve um número na moeda e na
    escala que o usuário vê na tela.
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
# Manutenção
# ---------------------------------------------------------------------------

# O que o botão ↻ Atualizar refaz: cotações e o que é montado com elas.
# Fundamentos (CVM, Yahoo dos BDRs) ficam: só mudam com resultado novo, e
# refazê-los a cada clique era o que deixava o botão lento.
_CACHE_DE_MERCADO = ("brapi:quote", "brapi:fund", "brapi:mult", "overview", "etfs:rows",
                     "bdrs:rows", "macro", "pulse", "probe", "b3:bdi")


@app.post("/api/cache/clear")
def api_cache_clear(tudo: bool = False):
    """Sem parâmetro: só o que vem do mercado. `?tudo=1`: tudo, inclusive o
    cálculo direto da CVM em memória (manutenção)."""
    if not tudo:
        return {"ok": True, "escopo": "mercado",
                "arquivos_removidos": cache.clear(_CACHE_DE_MERCADO)}
    removed = cache.clear()
    cvm.limpar_cache()
    cvm._shares_table.cache_clear()
    return {"ok": True, "escopo": "tudo", "arquivos_removidos": removed}


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


@app.get("/carteiras")
def carteiras_page():
    return FileResponse(WEB_DIR / "carteiras.html")


# Os endereços-padrão que o iPhone e os navegadores tentam por conta própria,
# além dos <link> das páginas. Ficam fora da senha no proxy (só imagens).
@app.get("/apple-touch-icon.png", include_in_schema=False)
@app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
def apple_touch_icon():
    return FileResponse(WEB_DIR / "assets" / "icones" / "apple-touch-icon.png", media_type="image/png")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(WEB_DIR / "assets" / "icones" / "favicon-32.png", media_type="image/png")


@app.exception_handler(404)
def not_found(_request, exc):
    return JSONResponse(status_code=404, content={"detail": getattr(exc, "detail", "não encontrado")})


app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")
