"""BDRs de empresas estrangeiras listados na B3, separados por setor GICS.

Universo curado com os BDRs de maior liquidez (volume real do boletim da
B3), organizado pelos setores GICS em inglês — sem misturar com as ações
brasileiras da tela principal.

Fundamentos: as demonstrações dessas empresas não estão na CVM. Com token
BRAPI, os módulos de balanço/DRE/fluxo de caixa (dados Yahoo) alimentam o
mesmo pipeline de métricas, score e valuation das ações brasileiras — com
uma diferença estrutural: os números vêm na moeda de reporte (quase sempre
USD) e o preço do BDR é em BRL. Por isso o valuation trabalha inteiro na
moeda de reporte e converte só no fim:

    upside = equity_value(USD) / market_cap(USD) − 1
    preço justo por BDR = preço do BDR × (1 + upside)

Isso evita depender da razão BDR/ação de cada programa, que não é publicada
por API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import market
from .metrics import div

# ---------------------------------------------------------------------------
# Setores GICS (nomes em inglês, como pedido)
# ---------------------------------------------------------------------------

SECTORS: dict[str, dict] = {
    "TECHNOLOGY": {"label": "Information Technology", "icon": "💻"},
    "COMMUNICATION": {"label": "Communication Services", "icon": "📡"},
    "CONSUMER_DISCRETIONARY": {"label": "Consumer Discretionary", "icon": "🛍️"},
    "CONSUMER_STAPLES": {"label": "Consumer Staples", "icon": "🧺"},
    "FINANCIALS": {"label": "Financials", "icon": "🏛️"},
    "HEALTH_CARE": {"label": "Health Care", "icon": "⚕️"},
    "INDUSTRIALS": {"label": "Industrials", "icon": "🏭"},
    "ENERGY": {"label": "Energy", "icon": "🛢️"},
    "MATERIALS": {"label": "Materials", "icon": "⛏️"},
    "UTILITIES": {"label": "Utilities", "icon": "⚡"},
}


@dataclass(frozen=True)
class Bdr:
    ticker: str        # código na B3
    name: str
    us_ticker: str     # ticker na bolsa de origem
    sector: str
    bank: bool = False  # balanço de banco: score financeiro, sem DCF de FCFF


def B(ticker, name, us, sector, bank=False):
    return Bdr(ticker, name, us, sector, bank)


UNIVERSE: list[Bdr] = [
    # Information Technology
    B("AAPL34", "Apple", "AAPL", "TECHNOLOGY"),
    B("MSFT34", "Microsoft", "MSFT", "TECHNOLOGY"),
    B("NVDC34", "Nvidia", "NVDA", "TECHNOLOGY"),
    B("AVGO34", "Broadcom", "AVGO", "TECHNOLOGY"),
    B("ORCL34", "Oracle", "ORCL", "TECHNOLOGY"),
    B("TSMC34", "TSMC", "TSM", "TECHNOLOGY"),
    B("ASML34", "ASML", "ASML", "TECHNOLOGY"),
    B("ADBE34", "Adobe", "ADBE", "TECHNOLOGY"),
    B("SSFO34", "Salesforce", "CRM", "TECHNOLOGY"),
    B("N1OW34", "ServiceNow", "NOW", "TECHNOLOGY"),
    B("INTU34", "Intuit", "INTU", "TECHNOLOGY"),
    B("QCOM34", "Qualcomm", "QCOM", "TECHNOLOGY"),
    B("TXSA34", "Texas Instruments", "TXN", "TECHNOLOGY"),
    B("A1MD34", "AMD", "AMD", "TECHNOLOGY"),
    B("ITLC34", "Intel", "INTC", "TECHNOLOGY"),
    B("MUTC34", "Micron Technology", "MU", "TECHNOLOGY"),
    B("M2RV34", "Marvell Technology", "MRVL", "TECHNOLOGY"),
    B("K1LA34", "KLA", "KLAC", "TECHNOLOGY"),
    B("L1RC34", "Lam Research", "LRCX", "TECHNOLOGY"),
    B("D1EL34", "Dell Technologies", "DELL", "TECHNOLOGY"),
    B("W1DC34", "Western Digital", "WDC", "TECHNOLOGY"),
    B("S1TX34", "Seagate", "STX", "TECHNOLOGY"),
    B("IBMB34", "IBM", "IBM", "TECHNOLOGY"),
    B("CSCO34", "Cisco", "CSCO", "TECHNOLOGY"),
    B("S2NW34", "Snowflake", "SNOW", "TECHNOLOGY"),
    B("C2RW34", "CrowdStrike", "CRWD", "TECHNOLOGY"),
    B("P2LT34", "Palantir", "PLTR", "TECHNOLOGY"),
    B("M2ST34", "Strategy (MicroStrategy)", "MSTR", "TECHNOLOGY"),
    # Communication Services
    B("GOGL34", "Alphabet (Google)", "GOOGL", "COMMUNICATION"),
    B("M1TA34", "Meta Platforms", "META", "COMMUNICATION"),
    B("NFLX34", "Netflix", "NFLX", "COMMUNICATION"),
    B("DISB34", "Walt Disney", "DIS", "COMMUNICATION"),
    B("CMCS34", "Comcast", "CMCSA", "COMMUNICATION"),
    B("VERZ34", "Verizon", "VZ", "COMMUNICATION"),
    B("ATTB34", "AT&T", "T", "COMMUNICATION"),
    # Consumer Discretionary
    B("AMZO34", "Amazon", "AMZN", "CONSUMER_DISCRETIONARY"),
    B("TSLA34", "Tesla", "TSLA", "CONSUMER_DISCRETIONARY"),
    B("MELI34", "MercadoLibre", "MELI", "CONSUMER_DISCRETIONARY"),
    B("HOME34", "Home Depot", "HD", "CONSUMER_DISCRETIONARY"),
    B("NIKE34", "Nike", "NKE", "CONSUMER_DISCRETIONARY"),
    B("MCDC34", "McDonald's", "MCD", "CONSUMER_DISCRETIONARY"),
    B("SBUB34", "Starbucks", "SBUX", "CONSUMER_DISCRETIONARY"),
    B("BKNG34", "Booking Holdings", "BKNG", "CONSUMER_DISCRETIONARY"),
    B("U1BE34", "Uber", "UBER", "CONSUMER_DISCRETIONARY"),
    B("D1DG34", "DoorDash", "DASH", "CONSUMER_DISCRETIONARY"),
    B("BABA34", "Alibaba", "BABA", "CONSUMER_DISCRETIONARY"),
    B("P1DD34", "PDD Holdings", "PDD", "CONSUMER_DISCRETIONARY"),
    # Consumer Staples
    B("WALM34", "Walmart", "WMT", "CONSUMER_STAPLES"),
    B("COCA34", "Coca-Cola", "KO", "CONSUMER_STAPLES"),
    B("PEPB34", "PepsiCo", "PEP", "CONSUMER_STAPLES"),
    B("PGCO34", "Procter & Gamble", "PG", "CONSUMER_STAPLES"),
    B("COWC34", "Costco", "COST", "CONSUMER_STAPLES"),
    B("JBSS32", "JBS N.V.", "JBS", "CONSUMER_STAPLES"),
    # Financials
    B("BERK34", "Berkshire Hathaway", "BRK-B", "FINANCIALS", bank=True),
    B("JPMC34", "JPMorgan Chase", "JPM", "FINANCIALS", bank=True),
    B("BOAC34", "Bank of America", "BAC", "FINANCIALS", bank=True),
    B("WFCO34", "Wells Fargo", "WFC", "FINANCIALS", bank=True),
    B("CTGP34", "Citigroup", "C", "FINANCIALS", bank=True),
    B("GSGI34", "Goldman Sachs", "GS", "FINANCIALS", bank=True),
    B("MSBR34", "Morgan Stanley", "MS", "FINANCIALS", bank=True),
    B("AXPB34", "American Express", "AXP", "FINANCIALS", bank=True),
    B("BLAK34", "BlackRock", "BLK", "FINANCIALS", bank=True),
    B("VISA34", "Visa", "V", "FINANCIALS"),
    B("MSCD34", "Mastercard", "MA", "FINANCIALS"),
    B("PYPL34", "PayPal", "PYPL", "FINANCIALS"),
    B("C2OI34", "Coinbase", "COIN", "FINANCIALS"),
    B("ROXO34", "Nu Holdings (Nubank)", "NU", "FINANCIALS", bank=True),
    B("INBR32", "Inter & Co", "INTR", "FINANCIALS", bank=True),
    B("STOC34", "StoneCo", "STNE", "FINANCIALS"),
    B("PAGS34", "PagSeguro (PagBank)", "PAGS", "FINANCIALS"),
    # Health Care
    B("JNJB34", "Johnson & Johnson", "JNJ", "HEALTH_CARE"),
    B("LILY34", "Eli Lilly", "LLY", "HEALTH_CARE"),
    B("PFIZ34", "Pfizer", "PFE", "HEALTH_CARE"),
    B("MRCK34", "Merck & Co", "MRK", "HEALTH_CARE"),
    B("ABTT34", "Abbott Laboratories", "ABT", "HEALTH_CARE"),
    B("UNHH34", "UnitedHealth", "UNH", "HEALTH_CARE"),
    B("TMOS34", "Thermo Fisher", "TMO", "HEALTH_CARE"),
    B("M1RN34", "Moderna", "MRNA", "HEALTH_CARE"),
    # Industrials
    B("BOEI34", "Boeing", "BA", "INDUSTRIALS"),
    B("CATP34", "Caterpillar", "CAT", "INDUSTRIALS"),
    B("GEOO34", "GE Aerospace", "GE", "INDUSTRIALS"),
    B("HONB34", "Honeywell", "HON", "INDUSTRIALS"),
    B("DEEC34", "Deere & Co", "DE", "INDUSTRIALS"),
    B("U1AL34", "United Airlines", "UAL", "INDUSTRIALS"),
    B("FDXB34", "FedEx", "FDX", "INDUSTRIALS"),
    B("UPSS34", "UPS", "UPS", "INDUSTRIALS"),
    # Energy
    B("EXXO34", "ExxonMobil", "XOM", "ENERGY"),
    B("CHVX34", "Chevron", "CVX", "ENERGY"),
    # Materials
    B("FCXO34", "Freeport-McMoRan", "FCX", "MATERIALS"),
    B("N1EM34", "Newmont", "NEM", "MATERIALS"),
    B("AURA33", "Aura Minerals", "AUGO", "MATERIALS"),
    # Utilities
    B("NEXT34", "NextEra Energy", "NEE", "UTILITIES"),
]

BY_TICKER: dict[str, Bdr] = {b.ticker: b for b in UNIVERSE}
TICKERS: list[str] = [b.ticker for b in UNIVERSE]


def get(ticker: str) -> Optional[Bdr]:
    return BY_TICKER.get(ticker.upper().strip())


def peers(ticker: str) -> list[Bdr]:
    bdr = get(ticker)
    if not bdr:
        return []
    return [b for b in UNIVERSE if b.sector == bdr.sector and b.ticker != bdr.ticker]


# ---------------------------------------------------------------------------
# Fundamentos via Yahoo Finance (ticker de origem, gratuito)
# ---------------------------------------------------------------------------
# A BRAPI não expõe demonstrações para BDRs; o Yahoo tem tudo de graça para o
# papel na bolsa de origem (AAPL, MSFT, ...). O acesso fica isolado em
# _yahoo_download — uma função que devolve dicionários puros, fácil de cachear
# e de simular nos testes. Qualquer falha degrada para None, nunca quebra.

# Rótulos que o yfinance usa nas linhas dos demonstrativos, com sinônimos que
# aparecem conforme a versão/empresa.
_Y_INCOME = {
    "receita": ["Total Revenue", "Operating Revenue"],
    "lucro_bruto": ["Gross Profit"],
    "ebit": ["EBIT", "Operating Income"],
    "ebitda": ["EBITDA", "Normalized EBITDA"],
    "lucro_liquido": ["Net Income", "Net Income Common Stockholders"],
}
_Y_BALANCE = {
    "patrimonio_liquido": ["Stockholders Equity", "Common Stock Equity",
                           "Total Equity Gross Minority Interest"],
    "ativo_total": ["Total Assets"],
    "caixa": ["Cash And Cash Equivalents", "Cash Financial"],
    "aplicacoes": ["Other Short Term Investments"],
    "caixa_total": ["Cash Cash Equivalents And Short Term Investments"],
    "divida_bruta": ["Total Debt"],
}
_Y_CASHFLOW = {
    "fco": ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"],
    "capex": ["Capital Expenditure"],
    "depreciacao": ["Depreciation And Amortization", "Depreciation Amortization Depletion",
                    "Depreciation"],
}
_Y_INFO = ["marketCap", "beta", "dividendYield", "currentPrice", "regularMarketPrice",
           "targetMeanPrice", "targetHighPrice", "targetLowPrice",
           "numberOfAnalystOpinions", "recommendationKey", "financialCurrency"]


def _df_to_plain(df, wanted: dict) -> dict:
    """DataFrame do yfinance (linhas=contas, colunas=datas) → {campo: {ano: valor}}."""
    out: dict[str, dict[int, float]] = {}
    if df is None or getattr(df, "empty", True):
        return out
    index = {str(ix): ix for ix in df.index}
    for campo, rotulos in wanted.items():
        for rotulo in rotulos:
            if rotulo not in index:
                continue
            serie = df.loc[index[rotulo]]
            valores: dict[int, float] = {}
            for col, val in serie.items():
                try:
                    ano = int(getattr(col, "year", str(col)[:4]))
                    num = float(val)
                except (TypeError, ValueError):
                    continue
                if num == num:  # descarta NaN
                    valores[ano] = num
            if valores:
                out[campo] = valores
                break
    return out


def _yahoo_download(us_ticker: str) -> Optional[dict]:
    """Baixa demonstrações + info do Yahoo Finance. None em qualquer falha."""
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        tk = yf.Ticker(us_ticker)
        income = _df_to_plain(tk.income_stmt, _Y_INCOME)
        balance = _df_to_plain(tk.balance_sheet, _Y_BALANCE)
        cashflow = _df_to_plain(tk.cashflow, _Y_CASHFLOW)
        try:
            info_raw = tk.info or {}
        except Exception:
            info_raw = {}
        info = {}
        for chave in _Y_INFO:
            val = info_raw.get(chave)
            if val is not None:
                info[chave] = val
        if not income and not balance and not cashflow and not info:
            return None
        return {"income": income, "balance": balance, "cashflow": cashflow, "info": info}
    except Exception:
        return None


def yahoo_raw(bdr: Bdr) -> Optional[dict]:
    """Download com cache em disco (as demonstrações mudam 1x por trimestre)."""
    from . import cache
    from .settings import TTL_FUNDAMENTALS
    key = f"bdr:yahoo:v1:{bdr.us_ticker}"

    def fetch():
        return _yahoo_download(bdr.us_ticker)
    try:
        return cache.memoize(key, TTL_FUNDAMENTALS, fetch)
    except Exception:
        return None


def yahoo_dividend_yield(info: dict) -> Optional[float]:
    """DY do Yahoo em fração. O yfinance ora devolve fração (0.0044), ora
    pontos percentuais (0.44) conforme a versão — um DY acima de 25% é
    implausível para essas empresas, então usamos isso como assinatura."""
    raw = (info or {}).get("dividendYield")
    try:
        dy = float(raw)
    except (TypeError, ValueError):
        return None
    if dy <= 0:
        return None
    return dy / 100.0 if dy > 0.25 else dy


def fundamentals_from_yahoo(bdr: Bdr, raw: Optional[dict]) -> dict:
    """Demonstrações do Yahoo → mesma estrutura dos fundamentos CVM."""
    base_vazia = fundamentals_from_modules(bdr, None)
    if not raw:
        return base_vazia

    income = raw.get("income") or {}
    balance = raw.get("balance") or {}
    cashflow = raw.get("cashflow") or {}
    info = raw.get("info") or {}

    anos = sorted({ano for grupo in (income, balance, cashflow)
                   for serie in grupo.values() for ano in serie})
    if not anos:
        return base_vazia

    def montar(grupo: dict, campo: str) -> list:
        serie = grupo.get(campo) or {}
        return [serie.get(a) for a in anos]

    # caixa_total: linha consolidada quando existe; senão caixa + aplicações
    caixa_tot = balance.get("caixa_total")
    if not caixa_tot:
        cx = balance.get("caixa") or {}
        ap = balance.get("aplicacoes") or {}
        caixa_tot = {a: cx.get(a, 0.0) + ap.get(a, 0.0)
                     for a in set(cx) | set(ap)} or None

    db = balance.get("divida_bruta") or {}
    dl = ({a: db[a] - (caixa_tot or {}).get(a, 0.0) for a in db}
          if db and not bdr.bank else {})

    ebit = income.get("ebit") or {}
    ebitda = income.get("ebitda") or {}
    deprec = cashflow.get("depreciacao") or {}
    if not ebitda and ebit and deprec and not bdr.bank:
        ebitda = {a: ebit[a] + abs(deprec.get(a, 0.0)) for a in ebit if a in deprec}
    if bdr.bank:
        ebitda = {}

    fco = cashflow.get("fco") or {}
    capex = cashflow.get("capex") or {}
    fcl = {a: fco[a] - abs(capex.get(a, 0.0)) for a in fco if a in capex}

    series = {
        "receita": montar(income, "receita"),
        "lucro_bruto": montar(income, "lucro_bruto"),
        "ebit": montar(income, "ebit"),
        "ebitda": [ebitda.get(a) for a in anos],
        "depreciacao": [abs(deprec[a]) if a in deprec else None for a in anos],
        "resultado_financeiro": [None] * len(anos),
        "lucro_liquido": montar(income, "lucro_liquido"),
        "ativo_total": montar(balance, "ativo_total"),
        "passivo_total": [None] * len(anos),
        "patrimonio_liquido": montar(balance, "patrimonio_liquido"),
        "caixa": montar(balance, "caixa"),
        "aplicacoes": montar(balance, "aplicacoes"),
        "caixa_total": [(caixa_tot or {}).get(a) for a in anos],
        "divida_bruta": [db.get(a) for a in anos],
        "divida_liquida": [dl.get(a) for a in anos],
        "fco": [fco.get(a) for a in anos],
        "capex": [-abs(capex[a]) if a in capex else None for a in anos],
        "fcl": [fcl.get(a) for a in anos],
    }

    from . import metrics

    def lv(campo):
        return metrics.last_valid(series.get(campo, []), anos)

    receita_v, _ = lv("receita")
    ebit_v, _ = lv("ebit")
    ebitda_v, _ = lv("ebitda")
    lucro_v, _ = lv("lucro_liquido")
    lb_v, _ = lv("lucro_bruto")
    pl_v, _ = lv("patrimonio_liquido")
    ativo_v, _ = lv("ativo_total")
    db_v, _ = lv("divida_bruta")
    dl_v, _ = lv("divida_liquida")
    caixa_v, _ = lv("caixa_total")
    fco_v, _ = lv("fco")
    capex_v, _ = lv("capex")
    fcl_v, _ = lv("fcl")

    cap_inv = (pl_v + db_v) if (pl_v is not None and db_v is not None) else None

    indicadores = {
        "mg_bruta": div(lb_v, receita_v),
        "mg_ebitda": None if bdr.bank else div(ebitda_v, receita_v),
        "mg_ebit": div(ebit_v, receita_v),
        "mg_liquida": div(lucro_v, receita_v),
        "roe": div(lucro_v, pl_v),
        "roa": div(lucro_v, ativo_v),
        "roic": None if bdr.bank else div(
            (ebit_v * (1 - metrics.TAX_RATE)) if ebit_v is not None else None, cap_inv),
        "nd_ebitda": None if bdr.bank else div(dl_v, ebitda_v),
        "nd_equity": None if bdr.bank else div(dl_v, pl_v),
        "alavancagem": div(ativo_v, pl_v) if bdr.bank else None,
        "cash_conversion": None if bdr.bank else div(fco_v, ebitda_v),
        "fcf_margin": None if bdr.bank else div(fcl_v, receita_v),
        "cagr_receita_3a": metrics.cagr(series["receita"], anos, 3),
        "cagr_lucro_3a": metrics.cagr(series["lucro_liquido"], anos, 3),
        "cagr_ebitda_3a": None if bdr.bank else metrics.cagr(series["ebitda"], anos, 3),
        "consistencia_lucro": metrics.positive_years(series["lucro_liquido"], 5),
    }

    return {
        "ticker": bdr.ticker, "name": bdr.name, "sector": bdr.sector,
        "cd_cvm": None, "cnpj": None, "denom": bdr.name,
        "financial": bdr.bank, "years": anos, "series": series,
        "last_year": anos[-1],
        "base": {
            "receita": receita_v, "ebit": ebit_v, "ebitda": ebitda_v,
            "depreciacao": None, "lucro_liquido": lucro_v, "lucro_bruto": lb_v,
            "patrimonio_liquido": pl_v, "ativo_total": ativo_v,
            "divida_bruta": db_v, "divida_liquida": dl_v, "caixa": caixa_v,
            "fco": fco_v, "capex": capex_v, "fcl": fcl_v,
            "capital_investido": cap_inv,
        },
        "indicadores": indicadores,
        "currency": (info.get("financialCurrency") or "USD"),
        "bdr": True,
        "us_ticker": bdr.us_ticker,
        "fonte": "Yahoo Finance",
    }


def fetch_fundamentals(ticker: str) -> dict:
    """Orquestra as fontes: Yahoo (gratuito, completo) → módulos BRAPI.

    Devolve {"fund": ..., "info": dict do Yahoo ou {}, "fonte": str|None}.
    """
    bdr = get(ticker)
    if bdr is None:
        return {"fund": {}, "info": {}, "fonte": None}

    raw = yahoo_raw(bdr)
    fund = fundamentals_from_yahoo(bdr, raw)
    if fund.get("years"):
        return {"fund": fund, "info": (raw or {}).get("info") or {},
                "fonte": "Yahoo Finance"}

    mod = raw_modules(ticker)
    fund = fundamentals_from_modules(bdr, mod)
    if fund.get("years"):
        return {"fund": fund, "info": {}, "fonte": "BRAPI"}

    return {"fund": fund, "info": (raw or {}).get("info") or {}, "fonte": None}


# ---------------------------------------------------------------------------
# Fundamentos via módulos da BRAPI (dados no padrão Yahoo)
# ---------------------------------------------------------------------------

_MODULES = ("incomeStatementHistory,balanceSheetHistory,cashflowStatementHistory,"
            "defaultKeyStatistics,financialData,summaryProfile")


def _num(node) -> Optional[float]:
    """Campos Yahoo vêm como {'raw': x, 'fmt': '...'} ou escalares."""
    if node is None:
        return None
    if isinstance(node, dict):
        node = node.get("raw")
    try:
        value = float(node)
        return value if value == value else None
    except (TypeError, ValueError):
        return None


def _year(stmt: dict) -> Optional[int]:
    end = stmt.get("endDate")
    if isinstance(end, dict):
        end = end.get("fmt") or end.get("raw")
    text = str(end or "")
    if text[:4].isdigit():
        return int(text[:4])
    try:  # epoch
        from datetime import datetime, timezone
        return datetime.fromtimestamp(int(float(text)), tz=timezone.utc).year
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def raw_modules(ticker: str) -> Optional[dict]:
    if not market.BRAPI_TOKEN:
        return None
    key = f"bdr:mod:{ticker}"

    def fetch():
        r = market._SESSION.get(
            f"{market.BRAPI_BASE}/quote/{ticker}",
            params={"token": market.BRAPI_TOKEN, "modules": _MODULES},
            timeout=market.HTTP_TIMEOUT,
        )
        r.raise_for_status()
        res = r.json().get("results") or []
        return res[0] if res else None

    try:
        from . import cache
        from .settings import TTL_FUNDAMENTALS
        return cache.memoize(key, TTL_FUNDAMENTALS, fetch)
    except Exception:
        return None


def fundamentals_from_modules(bdr: Bdr, mod: Optional[dict]) -> dict:
    """Converte os módulos Yahoo/BRAPI na mesma estrutura dos fundamentos CVM.

    Devolve dict compatível com metrics/score, mais `currency` (moeda de
    reporte) — os valores NÃO são convertidos para BRL.
    """
    vazio = {"ticker": bdr.ticker, "name": bdr.name, "sector": bdr.sector,
             "cd_cvm": None, "cnpj": None, "denom": bdr.name,
             "financial": bdr.bank, "years": [], "series": {}, "last_year": None,
             "base": {}, "indicadores": {}, "currency": None, "bdr": True,
             "us_ticker": bdr.us_ticker}
    if not mod:
        return vazio

    income = ((mod.get("incomeStatementHistory") or {})
              .get("incomeStatementHistory") or [])
    balance = ((mod.get("balanceSheetHistory") or {})
               .get("balanceSheetStatements") or [])
    cashflow = ((mod.get("cashflowStatementHistory") or {})
                .get("cashflowStatements") or [])
    fin_data = mod.get("financialData") or {}
    currency = fin_data.get("financialCurrency") or "USD"

    def series_from(stmts: list, campo: str, sinal: int = 1) -> dict[int, float]:
        out = {}
        for stmt in stmts:
            year = _year(stmt)
            value = _num(stmt.get(campo))
            if year and value is not None:
                out[year] = sinal * value
        return out

    receita = series_from(income, "totalRevenue")
    lucro_bruto = series_from(income, "grossProfit")
    ebit = series_from(income, "ebit")
    lucro = series_from(income, "netIncome")
    pl = series_from(balance, "totalStockholderEquity")
    ativo = series_from(balance, "totalAssets")
    caixa = series_from(balance, "cash")
    aplic = series_from(balance, "shortTermInvestments")
    div_cp = series_from(balance, "shortLongTermDebt")
    div_lp = series_from(balance, "longTermDebt")
    fco = series_from(cashflow, "totalCashFromOperatingActivities")
    capex = series_from(cashflow, "capitalExpenditures")   # já vem negativo
    deprec = series_from(cashflow, "depreciation")

    anos = sorted(set(receita) | set(lucro) | set(pl) | set(fco))
    if not anos:
        return vazio

    def montar(dados: dict) -> list:
        return [dados.get(y) for y in anos]

    divida_bruta = {y: (div_cp.get(y, 0.0) + div_lp.get(y, 0.0))
                    for y in anos if y in div_cp or y in div_lp}
    caixa_total = {y: (caixa.get(y, 0.0) + aplic.get(y, 0.0))
                   for y in anos if y in caixa or y in aplic}
    divida_liq = ({y: divida_bruta[y] - caixa_total.get(y, 0.0) for y in divida_bruta}
                  if not bdr.bank else {})
    ebitda = ({y: ebit[y] + abs(deprec.get(y, 0.0)) for y in ebit if y in deprec}
              if not bdr.bank else {})
    fcl = {y: fco[y] - abs(capex.get(y, 0.0)) for y in fco if y in capex}

    series = {
        "receita": montar(receita), "lucro_bruto": montar(lucro_bruto),
        "ebit": montar(ebit), "ebitda": montar(ebitda),
        "depreciacao": montar({y: abs(v) for y, v in deprec.items()}),
        "resultado_financeiro": [None] * len(anos),
        "lucro_liquido": montar(lucro),
        "ativo_total": montar(ativo), "passivo_total": [None] * len(anos),
        "patrimonio_liquido": montar(pl),
        "caixa": montar(caixa), "aplicacoes": montar(aplic),
        "caixa_total": montar(caixa_total),
        "divida_bruta": montar(divida_bruta), "divida_liquida": montar(divida_liq),
        "fco": montar(fco),
        "capex": montar({y: -abs(v) for y, v in capex.items()}),
        "fcl": montar(fcl),
    }

    # Reaproveita o cálculo de indicadores das ações brasileiras.
    from . import metrics

    def lv(key):
        return metrics.last_valid(series.get(key, []), anos)

    receita_v, _ = lv("receita")
    ebit_v, _ = lv("ebit")
    ebitda_v, _ = lv("ebitda")
    lucro_v, _ = lv("lucro_liquido")
    lb_v, _ = lv("lucro_bruto")
    pl_v, _ = lv("patrimonio_liquido")
    ativo_v, _ = lv("ativo_total")
    db_v, _ = lv("divida_bruta")
    dl_v, _ = lv("divida_liquida")
    caixa_v, _ = lv("caixa_total")
    fco_v, _ = lv("fco")
    capex_v, _ = lv("capex")
    fcl_v, _ = lv("fcl")

    cap_inv = (pl_v + db_v) if (pl_v is not None and db_v is not None) else None

    indicadores = {
        "mg_bruta": div(lb_v, receita_v),
        "mg_ebitda": None if bdr.bank else div(ebitda_v, receita_v),
        "mg_ebit": div(ebit_v, receita_v),
        "mg_liquida": div(lucro_v, receita_v),
        "roe": div(lucro_v, pl_v),
        "roa": div(lucro_v, ativo_v),
        "roic": None if bdr.bank else div(
            (ebit_v * (1 - metrics.TAX_RATE)) if ebit_v is not None else None, cap_inv),
        "nd_ebitda": None if bdr.bank else div(dl_v, ebitda_v),
        "nd_equity": None if bdr.bank else div(dl_v, pl_v),
        "alavancagem": div(ativo_v, pl_v) if bdr.bank else None,
        "cash_conversion": None if bdr.bank else div(fco_v, ebitda_v),
        "fcf_margin": None if bdr.bank else div(fcl_v, receita_v),
        "cagr_receita_3a": metrics.cagr(series["receita"], anos, 3),
        "cagr_lucro_3a": metrics.cagr(series["lucro_liquido"], anos, 3),
        "cagr_ebitda_3a": None if bdr.bank else metrics.cagr(series["ebitda"], anos, 3),
        "consistencia_lucro": metrics.positive_years(series["lucro_liquido"], 5),
    }

    return {
        "ticker": bdr.ticker, "name": bdr.name, "sector": bdr.sector,
        "cd_cvm": None, "cnpj": None, "denom": bdr.name,
        "financial": bdr.bank, "years": anos, "series": series,
        "last_year": anos[-1],
        "base": {
            "receita": receita_v, "ebit": ebit_v, "ebitda": ebitda_v,
            "depreciacao": None, "lucro_liquido": lucro_v, "lucro_bruto": lb_v,
            "patrimonio_liquido": pl_v, "ativo_total": ativo_v,
            "divida_bruta": db_v, "divida_liquida": dl_v, "caixa": caixa_v,
            "fco": fco_v, "capex": capex_v, "fcl": fcl_v,
            "capital_investido": cap_inv,
        },
        "indicadores": indicadores,
        "currency": currency,
        "bdr": True,
        "us_ticker": bdr.us_ticker,
    }
