"""Métricas fundamentalistas derivadas das séries da CVM + dados de mercado.

Regra geral do módulo: nada é estimado silenciosamente. Se a conta não
existe, o campo vem `None` e o painel mostra "—". Cada indicador carrega o
ano-base de onde saiu, porque nem toda empresa tem o mesmo último exercício
publicado.
"""

from __future__ import annotations

import math
from typing import Optional

from . import cvm, market, universe
from .settings import DEMO_MODE

# Alíquota efetiva usada no NOPAT do ROIC (IRPJ 25% + CSLL 9%).
TAX_RATE = 0.34


# ---------------------------------------------------------------------------
# Helpers de série
# ---------------------------------------------------------------------------

def last_valid(values: list, years: list[int]) -> tuple[Optional[float], Optional[int]]:
    """Último valor não-nulo de uma série anual, com o ano correspondente."""
    for value, year in zip(reversed(values or []), reversed(years or [])):
        if value is not None:
            return float(value), int(year)
    return None, None


def div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return a / b


def cagr(values: list, years: list[int], span: int = 3) -> Optional[float]:
    """CAGR entre o último ano válido e o ano `span` exercícios antes.

    Só é calculado quando ambas as pontas são positivas — CAGR com base
    negativa não tem interpretação econômica.
    """
    pairs = [(y, v) for y, v in zip(years or [], values or []) if v is not None]
    if len(pairs) < span + 1:
        return None
    end_year, end = pairs[-1]
    start_candidates = [(y, v) for y, v in pairs if y <= end_year - span]
    if not start_candidates:
        return None
    start_year, start = start_candidates[-1]
    n = end_year - start_year
    if n <= 0 or start <= 0 or end <= 0:
        return None
    return (end / start) ** (1 / n) - 1


def positive_years(values: list, window: int = 5) -> Optional[float]:
    """Fração dos últimos `window` exercícios com valor positivo."""
    vals = [v for v in (values or []) if v is not None][-window:]
    if len(vals) < 3:
        return None
    return sum(1 for v in vals if v > 0) / len(vals)


# ---------------------------------------------------------------------------
# Fundamentos por empresa
# ---------------------------------------------------------------------------

def fundamentals(ticker: str) -> dict:
    """Séries + indicadores contábeis de uma empresa (sem dados de mercado)."""
    comp = universe.get(ticker)
    if comp is None:
        return {}
    data = cvm.annual_series(comp.cd_cvm) if comp.cd_cvm else {
        "years": [], "financial": False, "series": {}, "cnpj": None}

    years = data.get("years") or []
    series = data.get("series") or {}
    fin = bool(data.get("financial")) or universe.is_financial(ticker)

    def lv(key):
        return last_valid(series.get(key, []), years)

    receita, ano_receita = lv("receita")
    ebit, _ = lv("ebit")
    ebitda, _ = lv("ebitda")
    da, _ = lv("depreciacao")
    lucro, ano_lucro = lv("lucro_liquido")
    lucro_bruto, _ = lv("lucro_bruto")
    pl, _ = lv("patrimonio_liquido")
    ativo, _ = lv("ativo_total")
    div_bruta, _ = lv("divida_bruta")
    div_liq, _ = lv("divida_liquida")
    caixa, _ = lv("caixa_total")
    fco, _ = lv("fco")
    capex, _ = lv("capex")
    fcl, _ = lv("fcl")

    capital_investido = None
    if pl is not None and div_bruta is not None:
        capital_investido = pl + div_bruta

    ind = {
        "mg_bruta": div(lucro_bruto, receita),
        "mg_ebitda": None if fin else div(ebitda, receita),
        "mg_ebit": div(ebit, receita),
        "mg_liquida": div(lucro, receita),
        "roe": div(lucro, pl),
        "roa": div(lucro, ativo),
        "roic": None if fin else div((ebit * (1 - TAX_RATE)) if ebit is not None else None,
                                     capital_investido),
        "nd_ebitda": None if fin else div(div_liq, ebitda),
        "nd_equity": None if fin else div(div_liq, pl),
        "alavancagem": div(ativo, pl) if fin else None,
        "cash_conversion": None if fin else div(fco, ebitda),
        "fcf_margin": None if fin else div(fcl, receita),
        "cagr_receita_3a": cagr(series.get("receita", []), years, 3),
        "cagr_lucro_3a": cagr(series.get("lucro_liquido", []), years, 3),
        "cagr_ebitda_3a": None if fin else cagr(series.get("ebitda", []), years, 3),
        "consistencia_lucro": positive_years(series.get("lucro_liquido", []), 5),
    }

    return {
        "ticker": comp.ticker,
        "name": comp.name,
        "sector": comp.sector,
        "cd_cvm": comp.cd_cvm,
        "cnpj": data.get("cnpj"),
        "denom": data.get("denom") or comp.cvm_name,
        "financial": fin,
        "years": years,
        "series": series,
        "last_year": data.get("last_year"),
        "base": {
            "receita": receita, "ano_receita": ano_receita,
            "ebit": ebit, "ebitda": ebitda, "depreciacao": da,
            "lucro_liquido": lucro, "ano_lucro": ano_lucro,
            "lucro_bruto": lucro_bruto,
            "patrimonio_liquido": pl, "ativo_total": ativo,
            "divida_bruta": div_bruta, "divida_liquida": div_liq, "caixa": caixa,
            "fco": fco, "capex": capex, "fcl": fcl,
            "capital_investido": capital_investido,
        },
        "indicadores": ind,
    }


# ---------------------------------------------------------------------------
# Mercado + múltiplos
# ---------------------------------------------------------------------------

def _demo_price(ticker: str, base_equity: Optional[float]) -> float:
    """Preço sintético determinístico para o modo demonstração."""
    seed = sum((i + 1) * ord(ch) for i, ch in enumerate(ticker))
    return round(8 + (seed % 730) / 10.0, 2)


def market_snapshot(ticker: str, series: list[tuple[str, float]],
                    brapi: Optional[dict], fund: dict) -> dict:
    """Preço, performance, ações em circulação e valor de mercado."""
    perf = market.performance(series)
    price = perf.get("price")
    source = "histórico"

    if brapi:
        live = brapi.get("regularMarketPrice")
        if live:
            price = float(live)
            source = "BRAPI"
            chg = brapi.get("regularMarketChangePercent")
            if chg is not None:
                perf["day"] = float(chg) / 100.0
            perf["price"] = price
    elif price is not None:
        source = market.source_label()

    if price is None and DEMO_MODE:
        price = _demo_price(ticker, fund.get("base", {}).get("patrimonio_liquido"))
        source = "demo"

    # `shares` = ações emitidas pela companhia (base contábil).
    # `shares_quote` = papéis equivalentes ao que é negociado: em units,
    # divide-se pelo número de ações que compõem cada unit.
    shares = None
    shares_source = None
    if brapi and brapi.get("sharesOutstanding"):
        shares, shares_source = float(brapi["sharesOutstanding"]), "BRAPI"
    if not shares:
        shares = cvm.shares_outstanding(fund.get("cnpj"))
        shares_source = "capital social CVM" if shares else None
    if not shares:
        shares = cvm.shares_from_eps(fund.get("cd_cvm"))
        shares_source = "implícito no LPA (CVM)" if shares else None

    ratio = universe.unit_ratio(ticker)
    shares_quote = (shares / ratio) if shares else None

    market_cap = None
    cap_source = None
    if brapi and brapi.get("marketCap"):
        market_cap, cap_source = float(brapi["marketCap"]), "BRAPI"
    elif price is not None and shares_quote:
        sufixo = f" ÷ {ratio} (unit)" if ratio > 1 else ""
        market_cap = price * shares_quote
        cap_source = f"preço × ações{sufixo} · {shares_source}"

    return {
        "price": price,
        "price_date": perf.get("date"),
        "price_source": source,
        "perf": {k: perf.get(k) for k in ("day", "week", "m3", "m12", "ytd")},
        "shares": shares,
        "shares_quote": shares_quote,
        "unit_ratio": ratio,
        "shares_source": shares_source,
        "market_cap": market_cap,
        "market_cap_source": cap_source,
        "points": len(series or []),
    }


def _num(v) -> Optional[float]:
    """Número finito ou None — a BRAPI às vezes manda string, 0 ou NaN."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _campo_brapi(brapi: Optional[dict], *nomes: str) -> Optional[float]:
    """Primeiro campo presente, no topo da cotação ou nos módulos.

    Os nomes variam entre versões da API (`ebitdaMargins` × `ebitdaMargin`),
    e o mesmo número às vezes vem em `defaultKeyStatistics`, às vezes em
    `financialData`: procura em todos antes de desistir.
    """
    if not brapi:
        return None
    lugares = [brapi] + [brapi.get(m) for m in ("defaultKeyStatistics", "financialData")]
    for nome in nomes:
        for lugar in lugares:
            if isinstance(lugar, dict):
                v = _num(lugar.get(nome))
                if v is not None:
                    return v
    return None


def _taxa(v: Optional[float], *refs: Optional[float]) -> Optional[float]:
    """Taxa da BRAPI (ROE, margem) sempre como fração: 0,213 = 21,3%.

    A API entrega umas taxas em fração e outras em pontos percentuais (o DY
    vem em pontos), e o dicionário dela não diz qual é qual. Em vez de
    adivinhar, a escala é a que fica mais perto de uma referência da mesma
    grandeza: LPA ÷ VPA da própria BRAPI, ou a conta anual da CVM. Janela
    diferente muda o número em alguns pontos, nunca em 100 vezes.
    """
    if v is None:
        return None
    if v == 0:
        return 0.0
    for ref in refs:
        if ref is not None and ref != 0:
            return min((v, v / 100.0), key=lambda c: abs(math.log(abs(c) / abs(ref))))
    # Sem referência nenhuma: acima de 150% só em pontos percentuais.
    return v / 100.0 if abs(v) > 1.5 else v


# As fontes que o usuário escolhe na tela. "auto" é a mistura: cada múltiplo
# da primeira fonte que o tiver, na ordem de FONTES_AUTO.
FONTES = ("auto", "brapi", "cvm_12m", "cvm_exercicio")
FONTES_AUTO = ("brapi", "cvm_12m", "cvm_exercicio")
_TAG = {"brapi": "BRAPI", "cvm_12m": "CVM12", "cvm_exercicio": "CVM"}
_CHAVES = ("pl", "pvp", "ev_ebitda", "ev_ebit", "psr", "roe", "mg_ebitda",
           "nd_ebitda", "ev", "lpa", "vpa", "fcf_yield")
# Estes a BRAPI não publica: em qualquer fonte escolhida, saem da CVM.
_SO_CVM = ("nd_ebitda", "ev_ebit", "psr", "fcf_yield")


def _pacote_cvm(v: dict, snap: dict, fin: bool) -> dict:
    """Múltiplos sobre um conjunto de contas da CVM (exercício ou 12 meses).

    `v` traz fluxos (lucro, receita, EBITDA, EBIT, FCL) e saldos (PL, dívida
    líquida) da mesma janela; o preço é sempre o de agora.
    """
    cap = snap.get("market_cap")
    lucro, pl = v.get("lucro_liquido"), v.get("patrimonio_liquido")
    ebitda, nd = v.get("ebitda"), v.get("divida_liquida")
    ev = (cap + nd) if (cap is not None and nd is not None and not fin) else None
    return {
        "pl": div(cap, lucro),
        "pvp": div(cap, pl),
        "ev_ebitda": div(ev, ebitda),
        "ev_ebit": div(ev, v.get("ebit")),
        "psr": div(cap, v.get("receita")),
        "roe": div(lucro, pl),
        "mg_ebitda": None if fin else div(ebitda, v.get("receita")),
        "nd_ebitda": None if fin else div(nd, ebitda),
        "ev": ev,
        # Por papel negociado (unit, quando for o caso), para comparar com o preço.
        "lpa": div(lucro, snap.get("shares_quote")),
        "vpa": div(pl, snap.get("shares_quote")),
        "fcf_yield": div(v.get("fcl"), cap),
    }


def _pacote_brapi(brapi: Optional[dict], snap: dict, fin: bool,
                  refs: dict) -> dict:
    """Múltiplos de 12 meses como a BRAPI publica. Zero em múltiplo de preço
    é campo vazio, não empresa de graça."""
    price = snap.get("price")
    lpa_b = _campo_brapi(brapi, "earningsPerShare", "trailingEps")
    vpa_b = _campo_brapi(brapi, "bookValue")
    pl_b = _campo_brapi(brapi, "priceEarnings", "trailingPE")
    if pl_b is None and price and lpa_b:
        pl_b = price / lpa_b
    pvp_b = _campo_brapi(brapi, "priceToBook")
    if pvp_b is None and price and vpa_b and vpa_b > 0:
        pvp_b = price / vpa_b
    out = dict.fromkeys(_CHAVES)
    out.update({
        "pl": pl_b or None,
        "pvp": pvp_b or None,
        "ev_ebitda": None if fin else (_campo_brapi(brapi, "enterpriseToEbitda") or None),
        "roe": _taxa(_campo_brapi(brapi, "returnOnEquity"),
                     div(lpa_b, vpa_b) if vpa_b and vpa_b > 0 else None,
                     refs.get("roe")),
        "mg_ebitda": None if fin else _taxa(_campo_brapi(brapi, "ebitdaMargins", "ebitdaMargin"),
                                             refs.get("mg_ebitda")),
        "ev": None if fin else (_campo_brapi(brapi, "enterpriseValue") or None),
    })
    # LPA e VPA acompanham o P/L e o P/VP que estão na tela: o football field
    # multiplica o P/L dos pares pelo LPA, e as duas pontas precisam da mesma
    # janela. Preço ÷ múltiplo é, por construção, o LPA do papel negociado.
    out["lpa"] = (price / out["pl"]) if price and out["pl"] else None
    out["vpa"] = (price / out["pvp"]) if price and out["pvp"] else None
    return out


def multiplos_por_fonte(fund: dict, snap: dict, brapi: Optional[dict],
                        ltm: Optional[dict] = None) -> dict[str, dict]:
    """Os múltiplos em cada fonte que o usuário pode escolher na tela.

      * ``brapi``         — últimos 12 meses como a BRAPI publica;
      * ``cvm_12m``       — últimos 12 meses dos ITRs da CVM (oficial);
      * ``cvm_exercicio`` — último exercício fechado, DFP da CVM (oficial);
      * ``auto``          — cada múltiplo da primeira fonte que o tiver, nessa
        ordem (a BRAPI cobre mais papéis; a CVM é o fallback oficial).

    Cada pacote diz em ``fontes`` de onde saiu cada número, porque as janelas
    dão números diferentes para o mesmo ROE — o que fazia o painel "discordar"
    do release. Dív.Líq/EBITDA, EV/EBIT, P/Receita e FCF yield a BRAPI não
    publica: saem da CVM mesmo com a BRAPI escolhida. DY só a BRAPI tem.
    """
    fin = bool(fund.get("financial"))
    base = fund.get("base", {}) or {}
    campos_ltm = (ltm or {}).get("campos") or {}

    brutos = {
        "cvm_exercicio": _pacote_cvm(base, snap, fin),
        "cvm_12m": _pacote_cvm(campos_ltm, snap, fin) if campos_ltm else dict.fromkeys(_CHAVES),
    }
    # A referência de escala das taxas da BRAPI: a conta mais recente da CVM.
    refs = {k: (brutos["cvm_12m"].get(k) if brutos["cvm_12m"].get(k) is not None
                else brutos["cvm_exercicio"].get(k)) for k in ("roe", "mg_ebitda")}
    brutos["brapi"] = _pacote_brapi(brapi, snap, fin, refs)

    dy = None
    if brapi:
        raw = _num(brapi.get("dividendYield"))
        if raw is not None:
            # A BRAPI devolve o DY em pontos percentuais (ex.: 8.4 = 8,4%).
            dy = raw / 100.0

    comum = {"dy": dy, "ano_cvm": fund.get("last_year"),
             "ltm_fim": (ltm or {}).get("fim"), "ltm_rotulo": (ltm or {}).get("rotulo")}

    def escolhe(ordem: tuple[str, ...]) -> dict:
        out: dict = {}
        fontes: dict[str, Optional[str]] = {}
        for k in _CHAVES:
            origem = next((f for f in ordem if brutos[f].get(k) is not None), None)
            out[k] = brutos[origem][k] if origem else None
            fontes[k] = _TAG[origem] if origem else None
        # LPA/VPA seguem a fonte do P/L/P/VP, para as duas pontas do football
        # field ficarem na mesma janela mesmo quando a mistura é campo a campo.
        for par, mult in (("lpa", "pl"), ("vpa", "pvp")):
            origem = next((f for f, t in _TAG.items() if t == fontes[mult]), None)
            out[par] = brutos[origem][par] if origem else out[par]
            fontes[par] = fontes[mult] if origem and out[par] is not None else fontes[par]
        fontes["dy"] = "BRAPI" if dy is not None else None
        return {**out, **comum, "fontes": fontes}

    # Fonte escolhida é fonte respeitada: sem o dado nela, fica vazio —
    # exceto o que só a CVM publica, que na BRAPI vem da CVM mais recente.
    so_brapi = escolhe(("brapi",))
    cvm_recente = escolhe(("cvm_12m", "cvm_exercicio"))
    for k in _SO_CVM:
        so_brapi[k] = cvm_recente[k]
        so_brapi["fontes"][k] = cvm_recente["fontes"][k]
    return {
        "auto": escolhe(FONTES_AUTO),
        "brapi": so_brapi,
        "cvm_12m": escolhe(("cvm_12m",)),
        "cvm_exercicio": escolhe(("cvm_exercicio",)),
    }


def multiples(fund: dict, snap: dict, brapi: Optional[dict],
              ltm: Optional[dict] = None) -> dict:
    """Os múltiplos da fonte automática (ver `multiplos_por_fonte`)."""
    return multiplos_por_fonte(fund, snap, brapi, ltm)["auto"]
