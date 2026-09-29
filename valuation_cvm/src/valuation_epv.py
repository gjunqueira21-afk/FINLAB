"""
Módulo de cálculo de EPV (Earnings Power Value).

Fórmula base:
    EPV = EBIT normalizado após impostos / WACC
    NOPAT = EBIT normalizado × (1 - alíquota efetiva)
    Equity EPV = EPV_enterprise - dívida líquida

Referência: metodologia de Bruce Greenwald.

IMPORTANTE:
- Não usa dados mockados.
- Se EBIT ou WACC não forem fornecidos, retorna None com flags explicativas.
- A normalização do EBIT requer série histórica.
"""

from typing import Dict, List, Literal, Optional

import numpy as np

from .logger import logger
from .valuation_metrics import safe_divide, _to_float


# ---------------------------------------------------------------------------
# Normalização do EBIT
# ---------------------------------------------------------------------------

NormMethod = Literal["median", "mean", "last", "mean_3y", "mean_5y"]


def normalize_ebit(
    ebit_series: List[Optional[float]],
    method: NormMethod = "median",
) -> Optional[float]:
    """
    Normaliza uma série histórica de EBIT.

    Métodos disponíveis:
        median   - mediana de todos os valores (padrão — mais conservador)
        mean     - média de todos os valores
        last     - último valor da série
        mean_3y  - média dos últimos 3 anos
        mean_5y  - média dos últimos 5 anos

    Retorna None se não houver dados válidos suficientes.
    """
    cleaned = [_to_float(v) for v in ebit_series if _to_float(v) is not None]

    if not cleaned:
        logger.warning("normalize_ebit: nenhum valor válido na série.")
        return None

    if method == "last":
        return cleaned[-1]

    if method == "mean_3y":
        window = cleaned[-3:]
    elif method == "mean_5y":
        window = cleaned[-5:]
    else:
        window = cleaned

    if not window:
        return None

    if method == "median":
        return float(np.median(window))

    return float(np.mean(window))


# ---------------------------------------------------------------------------
# Cálculo do EPV
# ---------------------------------------------------------------------------

def calculate_epv(
    ebit_normalized: Optional[float],
    tax_rate: float = 0.34,
    wacc: float = 0.10,
    net_debt: float = 0.0,
) -> Dict:
    """
    Calcula o EPV (Earnings Power Value) enterprise e de equity.

    Parâmetros:
        ebit_normalized: EBIT normalizado (em R$ ou na escala dos demonstrativos)
        tax_rate:        Alíquota efetiva de imposto (padrão: 34% — IRPJ + CSLL Brasil)
        wacc:            Taxa de desconto (WACC, em decimal; padrão: 10%)
        net_debt:        Dívida líquida (dívida bruta - caixa); pode ser negativa (caixa > dívida)

    Retorna dicionário com:
        ebit_normalized, nopat, epv_enterprise, net_debt, epv_equity,
        premissas (tax_rate, wacc), flags de qualidade.
    """
    result: Dict = {
        "ebit_normalized": None,
        "nopat": None,
        "epv_enterprise": None,
        "net_debt": net_debt,
        "epv_equity": None,
        "premissas": {
            "tax_rate": tax_rate,
            "wacc": wacc,
            "metodo_descricao": "EPV = NOPAT / WACC; NOPAT = EBIT × (1 - tax_rate)",
        },
        "flags": [],
    }

    # Validações
    if ebit_normalized is None:
        result["flags"].append("EBIT_NORMALIZADO_AUSENTE")
        logger.warning("calculate_epv: EBIT normalizado não fornecido.")
        return result

    ebit_val = _to_float(ebit_normalized)
    if ebit_val is None:
        result["flags"].append("EBIT_NORMALIZADO_INVALIDO")
        return result

    if wacc <= 0:
        result["flags"].append("WACC_INVALIDO")
        logger.error("calculate_epv: WACC deve ser > 0. Recebido: %s", wacc)
        return result

    if not (0 <= tax_rate < 1):
        result["flags"].append("TAX_RATE_INVALIDO")
        logger.warning("calculate_epv: tax_rate fora do intervalo [0, 1): %s", tax_rate)

    if ebit_val < 0:
        result["flags"].append("EBIT_NEGATIVO_EPV_NEGATIVO")
        logger.warning(
            "calculate_epv: EBIT normalizado é negativo (%.2f). "
            "EPV será negativo — empresa não tem poder de lucro positivo.", ebit_val
        )

    nopat = ebit_val * (1 - tax_rate)
    epv_enterprise = safe_divide(nopat, wacc)
    epv_equity = None
    if epv_enterprise is not None:
        epv_equity = epv_enterprise - net_debt

    result["ebit_normalized"] = ebit_val
    result["nopat"] = nopat
    result["epv_enterprise"] = epv_enterprise
    result["epv_equity"] = epv_equity

    if not result["flags"]:
        result["flags"].append("OK")

    logger.info(
        "EPV calculado | EBIT_norm=%.2f | NOPAT=%.2f | EPV_EV=%.2f | DívLíq=%.2f | EPV_Equity=%.2f",
        ebit_val, nopat,
        epv_enterprise or float("nan"),
        net_debt,
        epv_equity or float("nan"),
    )

    return result


# ---------------------------------------------------------------------------
# EPV por ação
# ---------------------------------------------------------------------------

def calculate_epv_per_share(
    equity_value: Optional[float],
    shares_outstanding: Optional[float],
) -> Optional[float]:
    """
    Calcula o EPV por ação.

    Parâmetros:
        equity_value:      Valor do equity pelo EPV
        shares_outstanding: Número de ações (deve ser obtido externamente — não disponível direto na CVM)

    A CVM pode não trazer número de ações de forma direta nos arquivos principais.
    Esta função aceita shares_outstanding como input externo.

    Retorna None se qualquer entrada for inválida.
    """
    ev = _to_float(equity_value)
    shares = _to_float(shares_outstanding)

    if ev is None:
        logger.warning("calculate_epv_per_share: equity_value ausente.")
        return None

    if shares is None or shares <= 0:
        logger.warning(
            "calculate_epv_per_share: número de ações ausente ou inválido (%s). "
            "Forneça shares_outstanding externamente (ex.: via brapi.dev ou B3).", shares_outstanding
        )
        return None

    return ev / shares


# ---------------------------------------------------------------------------
# EPV completo a partir de série histórica
# ---------------------------------------------------------------------------

def epv_from_ebit_series(
    ebit_series: List[Optional[float]],
    tax_rate: float = 0.34,
    wacc: float = 0.10,
    net_debt: float = 0.0,
    norm_method: NormMethod = "median",
    shares_outstanding: Optional[float] = None,
) -> Dict:
    """
    Fluxo completo: normaliza EBIT histórico e calcula EPV.

    Combina normalize_ebit + calculate_epv + calculate_epv_per_share.
    """
    ebit_norm = normalize_ebit(ebit_series, method=norm_method)
    result = calculate_epv(ebit_norm, tax_rate=tax_rate, wacc=wacc, net_debt=net_debt)
    result["premissas"]["norm_method"] = norm_method
    result["premissas"]["ebit_series_length"] = len([v for v in ebit_series if v is not None])

    if shares_outstanding:
        result["epv_per_share"] = calculate_epv_per_share(result["epv_equity"], shares_outstanding)
    else:
        result["epv_per_share"] = None
        result["flags"].append("SHARES_OUTSTANDING_NAO_FORNECIDO")

    return result
