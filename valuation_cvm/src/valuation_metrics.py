"""
Módulo de cálculo de métricas fundamentalistas básicas.

IMPORTANTE:
- Não força cálculo quando falta dado.
- Quando informação é insuficiente, retorna NaN e registra flag de ausência.
- Métricas aproximadas têm sufixo _APROX no nome.
"""

from typing import Dict, Optional, Tuple
import math

from .logger import logger


# ---------------------------------------------------------------------------
# Helpers matemáticos
# ---------------------------------------------------------------------------

def safe_divide(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """
    Divide a por b de forma segura.
    Retorna None se qualquer operando for None/NaN ou se b == 0.
    """
    if a is None or b is None:
        return None
    if isinstance(a, float) and math.isnan(a):
        return None
    if isinstance(b, float) and math.isnan(b):
        return None
    if b == 0:
        return None
    return a / b


def _to_float(val: object) -> Optional[float]:
    """Converte para float, retorna None em caso de falha."""
    if val is None:
        return None
    try:
        v = float(val)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Dívida líquida
# ---------------------------------------------------------------------------

def calculate_net_debt(
    cash: Optional[float],
    gross_debt: Optional[float],
) -> Tuple[Optional[float], str]:
    """
    Calcula dívida líquida = dívida bruta - caixa.

    Retorna (valor, observação).
    """
    cash = _to_float(cash)
    gross_debt = _to_float(gross_debt)

    if gross_debt is None and cash is None:
        return None, "Dívida bruta e caixa ausentes"
    if gross_debt is None:
        return None, "Dívida bruta ausente"
    if cash is None:
        logger.warning("Caixa ausente — dívida líquida calculada sem deduzir caixa (pode ser superestimada).")
        return gross_debt, "Caixa ausente: dívida líquida = dívida bruta (sem dedução de caixa)"

    return gross_debt - cash, "OK"


# ---------------------------------------------------------------------------
# Margens
# ---------------------------------------------------------------------------

def calculate_margins(
    revenue: Optional[float],
    gross_profit: Optional[float],
    ebit: Optional[float],
    net_income: Optional[float],
) -> Dict[str, Optional[float]]:
    """
    Calcula margens brutas, operacional (EBIT) e líquida.
    Retorna NaN para as que não puderem ser calculadas.
    """
    rev = _to_float(revenue)

    margins: Dict[str, Optional[float]] = {
        "margem_bruta": safe_divide(_to_float(gross_profit), rev),
        "margem_ebit": safe_divide(_to_float(ebit), rev),
        "margem_liquida": safe_divide(_to_float(net_income), rev),
    }

    # Converter None → np.nan para consistência
    return {k: (v if v is not None else float("nan")) for k, v in margins.items()}


# ---------------------------------------------------------------------------
# Retornos
# ---------------------------------------------------------------------------

def calculate_returns(
    net_income: Optional[float],
    equity: Optional[float],
    ebit: Optional[float],
    invested_capital: Optional[float],
    total_assets: Optional[float] = None,
) -> Dict[str, Optional[float]]:
    """
    Calcula ROE, ROA e ROIC aproximado.

    ROE  = lucro líquido / patrimônio líquido
    ROA  = lucro líquido / ativo total
    ROIC_APROX = EBIT / capital investido (sem ajuste de imposto — aproximação)

    Quando a base do cálculo for negativa, retorna o valor mas adiciona flag de atenção.
    """
    ni = _to_float(net_income)
    eq = _to_float(equity)
    eb = _to_float(ebit)
    ic = _to_float(invested_capital)
    ta = _to_float(total_assets)

    roe = safe_divide(ni, eq)
    roa = safe_divide(ni, ta)
    roic_aprox = safe_divide(eb, ic)

    results = {
        "roe": roe if roe is not None else float("nan"),
        "roa": roa if roa is not None else float("nan"),
        "roic_aprox": roic_aprox if roic_aprox is not None else float("nan"),
    }

    # Flags de atenção
    if eq is not None and eq < 0:
        logger.warning("ROE: patrimônio líquido negativo (PL < 0) — resultado pode ser enganoso.")
    if ic is not None and ic <= 0:
        logger.warning("ROIC_APROX: capital investido <= 0 — resultado inválido.")

    return results


# ---------------------------------------------------------------------------
# Cálculo completo de métricas básicas a partir de snapshot
# ---------------------------------------------------------------------------

def calculate_basic_metrics(snapshot: Dict) -> Dict:
    """
    Recebe um snapshot financeiro (dict) e calcula métricas fundamentalistas básicas.

    Retorna dict com valores originais + métricas calculadas + flags.
    """
    receita = _to_float(snapshot.get("receita_liquida"))
    lucro_bruto = _to_float(snapshot.get("lucro_bruto"))
    ebit = _to_float(snapshot.get("ebit"))
    lucro_liq = _to_float(snapshot.get("lucro_liquido"))
    caixa = _to_float(snapshot.get("caixa_equivalentes"))
    aplic = _to_float(snapshot.get("aplicacoes_financeiras"))
    divida_bruta = _to_float(snapshot.get("divida_bruta"))
    pl = _to_float(snapshot.get("patrimonio_liquido"))
    ativo = _to_float(snapshot.get("ativo_total"))
    passivo = _to_float(snapshot.get("passivo_total"))
    fcop = _to_float(snapshot.get("fluxo_caixa_operacional"))
    capex = _to_float(snapshot.get("capex"))

    # Caixa total (caixa + aplicações)
    caixa_total: Optional[float] = None
    if caixa is not None or aplic is not None:
        caixa_total = (caixa or 0.0) + (aplic or 0.0)

    # Dívida líquida
    divida_liq, divida_obs = calculate_net_debt(caixa_total, divida_bruta)

    # Capital investido aproximado (PL + Dívida bruta)
    cap_inv: Optional[float] = None
    if pl is not None and divida_bruta is not None:
        cap_inv = pl + divida_bruta
    elif pl is not None:
        cap_inv = pl

    # Margens
    margins = calculate_margins(receita, lucro_bruto, ebit, lucro_liq)

    # Retornos
    returns = calculate_returns(
        net_income=lucro_liq,
        equity=pl,
        ebit=ebit,
        invested_capital=cap_inv,
        total_assets=ativo,
    )

    # FCL aproximado (FCOP - Capex)
    fcl_aprox: Optional[float] = None
    if fcop is not None and capex is not None:
        # Capex geralmente aparece negativo no DFC; se positivo, subtrai
        capex_abs = abs(capex)
        fcl_aprox = fcop - capex_abs

    metrics = {
        # Valores base
        "receita_liquida": receita,
        "lucro_bruto": lucro_bruto,
        "ebit": ebit,
        "lucro_liquido": lucro_liq,
        "caixa_equivalentes": caixa,
        "aplicacoes_financeiras": aplic,
        "caixa_total": caixa_total,
        "divida_bruta": divida_bruta,
        "divida_liquida": divida_liq,
        "divida_liquida_obs": divida_obs,
        "patrimonio_liquido": pl,
        "ativo_total": ativo,
        "passivo_total": passivo,
        "fluxo_caixa_operacional": fcop,
        "capex": capex,
        "fcl_aprox": fcl_aprox,
        "capital_investido_aprox": cap_inv,
        # Margens
        **margins,
        # Retornos
        **returns,
        # Flags
        "has_revenue": receita is not None,
        "has_gross_profit": lucro_bruto is not None,
        "has_ebit": ebit is not None,
        "has_net_income": lucro_liq is not None,
        "has_cash": caixa is not None,
        "has_debt": divida_bruta is not None,
        "has_equity": pl is not None,
        "has_operating_cash_flow": fcop is not None,
        "has_capex": capex is not None,
        "has_fcl": fcl_aprox is not None,
    }

    return metrics
