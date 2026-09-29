"""
Módulo de cálculo de DCF (Discounted Cash Flow).

Estrutura simples e transparente:
1. Projetar FCL (Fluxo de Caixa Livre) com taxas de crescimento
2. Calcular Valor Terminal (Gordon Growth Model)
3. Descontar todos os fluxos a valor presente
4. Calcular Enterprise Value e Equity Value

IMPORTANTE:
- WACC deve ser > g (taxa terminal), caso contrário a fórmula de Gordon não é válida.
- FCL negativo é aceito, mas gera flag de atenção.
- Não inventa premissas: todas as taxas devem ser fornecidas explicitamente.
"""

from typing import Dict, List, Optional

from .logger import logger
from .valuation_metrics import safe_divide


# ---------------------------------------------------------------------------
# Projeção de FCL
# ---------------------------------------------------------------------------

def project_fcf(
    base_fcf: float,
    growth_rates: List[float],
    years: Optional[int] = None,
) -> List[float]:
    """
    Projeta o FCL (Fluxo de Caixa Livre) ao longo dos anos.

    Parâmetros:
        base_fcf:     FCL do período base (R$ ou escala dos demonstrativos)
        growth_rates: Lista de taxas de crescimento por período (decimal).
                      Se len(growth_rates) < years, repete a última taxa.
        years:        Número de anos de projeção.
                      Se None, usa len(growth_rates).

    Exemplo:
        project_fcf(1000, [0.10, 0.10, 0.08, 0.08, 0.06], years=5)
        -> FCL projetado para cada um dos 5 anos
    """
    if years is None:
        years = len(growth_rates)

    if years <= 0:
        logger.warning("project_fcf: years deve ser > 0.")
        return []

    if not growth_rates:
        logger.warning("project_fcf: growth_rates vazio — assumindo crescimento zero.")
        growth_rates = [0.0]

    # Completa com a última taxa se necessário
    rates = list(growth_rates)
    while len(rates) < years:
        rates.append(rates[-1])

    fcfs: List[float] = []
    current = float(base_fcf)
    for i in range(years):
        current = current * (1 + rates[i])
        fcfs.append(current)

    return fcfs


# ---------------------------------------------------------------------------
# Valor Terminal
# ---------------------------------------------------------------------------

def calculate_terminal_value(
    final_fcf: float,
    terminal_growth: float,
    wacc: float,
) -> Optional[float]:
    """
    Calcula o Valor Terminal usando o modelo de Gordon (perpetuidade com crescimento).

    TV = FCF_final × (1 + g) / (WACC - g)

    Parâmetros:
        final_fcf:      FCL do último ano projetado
        terminal_growth: Taxa de crescimento na perpetuidade (g), decimal
        wacc:           Taxa de desconto (WACC), decimal

    Retorna None se WACC <= g (fórmula inválida).
    """
    if wacc <= terminal_growth:
        logger.error(
            "calculate_terminal_value: WACC (%.4f) deve ser maior que g (%.4f). "
            "A fórmula de Gordon não é válida neste caso.",
            wacc, terminal_growth,
        )
        return None

    tv = final_fcf * (1 + terminal_growth) / (wacc - terminal_growth)
    return tv


# ---------------------------------------------------------------------------
# Desconto de fluxos
# ---------------------------------------------------------------------------

def discount_cash_flows(
    fcfs: List[float],
    wacc: float,
) -> List[float]:
    """
    Desconta uma lista de fluxos de caixa ao valor presente.

    Retorna lista com o VP de cada fluxo.
    """
    if wacc <= 0:
        logger.error("discount_cash_flows: WACC deve ser > 0. Recebido: %s", wacc)
        return [float("nan")] * len(fcfs)

    return [fcf / ((1 + wacc) ** (i + 1)) for i, fcf in enumerate(fcfs)]


# ---------------------------------------------------------------------------
# DCF completo
# ---------------------------------------------------------------------------

def calculate_dcf(
    base_fcf: float,
    growth_rates: List[float],
    terminal_growth: float,
    wacc: float,
    net_debt: float = 0.0,
    years: Optional[int] = None,
) -> Dict:
    """
    Calcula o DCF completo.

    Parâmetros:
        base_fcf:        FCL base (período atual, antes das projeções)
        growth_rates:    Taxas de crescimento por ano (decimal). Ex.: [0.10, 0.10, 0.08]
        terminal_growth: Taxa de crescimento na perpetuidade (g), decimal
        wacc:            Taxa de desconto (WACC), decimal
        net_debt:        Dívida líquida (para chegar ao equity value)
        years:           Número de anos de projeção (padrão: len(growth_rates))

    Retorna dicionário com:
        fcfs_projetados, vp_fcfs, valor_terminal, vp_valor_terminal,
        enterprise_value, dívida_líquida, equity_value, premissas, flags
    """
    result: Dict = {
        "fcfs_projetados": [],
        "vp_fcfs": [],
        "valor_terminal": None,
        "vp_valor_terminal": None,
        "enterprise_value": None,
        "net_debt": net_debt,
        "equity_value": None,
        "premissas": {
            "base_fcf": base_fcf,
            "growth_rates": growth_rates,
            "terminal_growth": terminal_growth,
            "wacc": wacc,
            "years": years or len(growth_rates),
        },
        "flags": [],
    }

    # Validações
    if wacc <= 0:
        result["flags"].append("WACC_INVALIDO")
        logger.error("calculate_dcf: WACC deve ser > 0.")
        return result

    if wacc <= terminal_growth:
        result["flags"].append("WACC_MENOR_OU_IGUAL_A_G")
        logger.error("calculate_dcf: WACC (%.4f) <= g (%.4f) — Valor Terminal inválido.", wacc, terminal_growth)
        return result

    if base_fcf < 0:
        result["flags"].append("FCL_BASE_NEGATIVO")
        logger.warning("calculate_dcf: FCL base negativo (%.2f). DCF pode resultar em valor negativo.", base_fcf)

    # 1. Projetar FCL
    fcfs = project_fcf(base_fcf, growth_rates, years=years)
    result["fcfs_projetados"] = fcfs
    result["premissas"]["years"] = len(fcfs)

    if not fcfs:
        result["flags"].append("PROJECAO_VAZIA")
        return result

    # 2. Descontar FCLs
    vp_fcfs = discount_cash_flows(fcfs, wacc)
    result["vp_fcfs"] = vp_fcfs
    soma_vp_fcfs = sum(vp_fcfs)

    # 3. Valor Terminal
    final_fcf = fcfs[-1]
    tv = calculate_terminal_value(final_fcf, terminal_growth, wacc)
    result["valor_terminal"] = tv

    if tv is None:
        result["flags"].append("VALOR_TERMINAL_INVALIDO")
        return result

    # 4. VP do Valor Terminal
    n_anos = len(fcfs)
    vp_tv = tv / ((1 + wacc) ** n_anos)
    result["vp_valor_terminal"] = vp_tv

    # 5. Enterprise Value
    ev = soma_vp_fcfs + vp_tv
    result["enterprise_value"] = ev

    # 6. Equity Value
    result["equity_value"] = ev - net_debt

    if not result["flags"]:
        result["flags"].append("OK")

    # % do valor que vem do Valor Terminal (indicador de sensibilidade)
    tv_pct = safe_divide(vp_tv, ev)
    if tv_pct is not None:
        result["premissas"]["pct_ev_de_valor_terminal"] = round(tv_pct * 100, 1)
        if tv_pct > 0.75:
            result["flags"].append("ALTO_PESO_VALOR_TERMINAL_ACIMA_75PCT")
            logger.warning(
                "DCF: %.1f%% do Enterprise Value vem do Valor Terminal — "
                "resultado é muito sensível às premissas de longo prazo.",
                tv_pct * 100,
            )

    logger.info(
        "DCF calculado | EV=%.2f | TV=%.2f (%.1f%% do EV) | Equity=%.2f",
        ev, vp_tv,
        (tv_pct or 0) * 100,
        result["equity_value"],
    )

    return result
