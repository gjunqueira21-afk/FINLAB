"""Score de saúde financeira (0–100) usado para ordenar a tela principal.

Filosofia: nota explicável, não caixa-preta. Cada indicador vira uma nota
0–100 por interpolação linear entre âncoras conhecidas do mercado
brasileiro; os indicadores se agrupam em pilares com peso fixo. Quando um
indicador falta, o peso é redistribuído entre os disponíveis dentro do
pilar e a cobertura de dados é reportada — uma empresa não ganha nem perde
nota por ausência de informação, mas o painel avisa que a nota é parcial.

Bancos e seguradoras usam outro conjunto de pilares: dívida líquida/EBITDA
e conversão de caixa não têm significado num balanço de instituição
financeira.
"""

from __future__ import annotations

from typing import Optional

# ---------------------------------------------------------------------------
# Curvas de pontuação
# ---------------------------------------------------------------------------

Anchors = list[tuple[float, float]]


def curve(value: Optional[float], anchors: Anchors) -> Optional[float]:
    """Interpola `value` na curva de âncoras [(x, nota)] com x crescente."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    if v <= anchors[0][0]:
        return anchors[0][1]
    if v >= anchors[-1][0]:
        return anchors[-1][1]
    for (x0, s0), (x1, s1) in zip(anchors, anchors[1:]):
        if x0 <= v <= x1:
            if x1 == x0:
                return s1
            return s0 + (s1 - s0) * (v - x0) / (x1 - x0)
    return anchors[-1][1]


ROE = [(-0.10, 0), (0.0, 8), (0.05, 25), (0.10, 45), (0.15, 65), (0.20, 80), (0.30, 95), (0.45, 100)]
ROA = [(-0.02, 0), (0.0, 8), (0.005, 22), (0.01, 42), (0.015, 62), (0.02, 80), (0.03, 100)]
ROIC = [(-0.05, 0), (0.0, 8), (0.04, 22), (0.08, 42), (0.12, 62), (0.18, 80), (0.25, 95), (0.35, 100)]
MG_EBITDA = [(-0.05, 0), (0.0, 10), (0.05, 22), (0.10, 35), (0.18, 55), (0.28, 75), (0.40, 90), (0.55, 100)]
MG_LIQUIDA = [(-0.10, 0), (0.0, 12), (0.03, 28), (0.07, 45), (0.12, 62), (0.20, 82), (0.30, 100)]
# Menor é melhor: âncoras decrescentes em nota.
ND_EBITDA = [(-1.0, 100), (0.0, 95), (1.0, 85), (2.0, 70), (2.5, 60), (3.0, 45), (3.5, 32), (4.0, 20), (5.0, 8), (6.0, 0)]
ND_EQUITY = [(-0.5, 100), (0.0, 92), (0.3, 80), (0.6, 65), (1.0, 45), (1.5, 25), (2.5, 5), (4.0, 0)]
ALAVANCAGEM_BANCO = [(3.0, 100), (6.0, 88), (8.0, 75), (10.0, 60), (12.0, 45), (15.0, 25), (20.0, 5), (30.0, 0)]
CAGR = [(-0.20, 0), (-0.10, 12), (-0.03, 28), (0.0, 38), (0.05, 52), (0.10, 66), (0.18, 85), (0.30, 100)]
CASH_CONV = [(-0.2, 0), (0.0, 10), (0.30, 30), (0.50, 50), (0.70, 70), (0.90, 88), (1.10, 100)]
FCF_MARGIN = [(-0.15, 0), (-0.05, 15), (0.0, 32), (0.03, 48), (0.07, 65), (0.12, 82), (0.20, 100)]
CONSISTENCIA = [(0.0, 0), (0.4, 25), (0.6, 50), (0.8, 75), (1.0, 100)]


# ---------------------------------------------------------------------------
# Pilares
# ---------------------------------------------------------------------------
# (chave do indicador, rótulo, curva, peso dentro do pilar)

PILLARS_CORP = [
    ("rentabilidade", "Rentabilidade", 0.26, [
        ("roe", "ROE", ROE, 0.40),
        ("roic", "ROIC", ROIC, 0.35),
        ("mg_liquida", "Margem líquida", MG_LIQUIDA, 0.25),
    ]),
    ("alavancagem", "Alavancagem", 0.24, [
        ("nd_ebitda", "Dív. líq./EBITDA", ND_EBITDA, 0.60),
        ("nd_equity", "Dív. líq./PL", ND_EQUITY, 0.40),
    ]),
    ("margem", "Margem operacional", 0.14, [
        ("mg_ebitda", "Margem EBITDA", MG_EBITDA, 1.0),
    ]),
    ("crescimento", "Crescimento", 0.16, [
        ("cagr_receita_3a", "CAGR receita 3a", CAGR, 0.50),
        ("cagr_ebitda_3a", "CAGR EBITDA 3a", CAGR, 0.50),
    ]),
    ("caixa", "Geração de caixa", 0.14, [
        ("cash_conversion", "FCO/EBITDA", CASH_CONV, 0.55),
        ("fcf_margin", "Margem de FCL", FCF_MARGIN, 0.45),
    ]),
    ("consistencia", "Consistência", 0.06, [
        ("consistencia_lucro", "Anos com lucro (5a)", CONSISTENCIA, 1.0),
    ]),
]

PILLARS_FIN = [
    ("rentabilidade", "Rentabilidade", 0.38, [
        ("roe", "ROE", ROE, 0.60),
        ("roa", "ROA", ROA, 0.40),
    ]),
    ("margem", "Margem", 0.18, [
        ("mg_liquida", "Margem líquida", MG_LIQUIDA, 1.0),
    ]),
    ("crescimento", "Crescimento", 0.20, [
        ("cagr_lucro_3a", "CAGR lucro 3a", CAGR, 0.60),
        ("cagr_receita_3a", "CAGR receita 3a", CAGR, 0.40),
    ]),
    ("alavancagem", "Solidez", 0.16, [
        ("alavancagem", "Ativo/PL", ALAVANCAGEM_BANCO, 1.0),
    ]),
    ("consistencia", "Consistência", 0.08, [
        ("consistencia_lucro", "Anos com lucro (5a)", CONSISTENCIA, 1.0),
    ]),
]


def score(indicadores: dict, financial: bool = False) -> dict:
    """Calcula a nota final e o detalhamento por pilar.

    Devolve:
        total       nota 0–100 (None se não houver dado suficiente)
        cobertura   fração do peso total com dado disponível
        pilares     lista com nota, peso e componentes de cada pilar
        parcial     True quando a cobertura fica abaixo de 60%
    """
    pillars = PILLARS_FIN if financial else PILLARS_CORP
    detail = []
    soma, peso_usado = 0.0, 0.0
    cobertura_num, cobertura_den = 0.0, 0.0

    for key, label, peso, itens in pillars:
        comps, sub_soma, sub_peso = [], 0.0, 0.0
        for ind_key, ind_label, anchors, ind_peso in itens:
            valor = indicadores.get(ind_key)
            nota = curve(valor, anchors)
            comps.append({
                "key": ind_key, "label": ind_label,
                "value": valor, "score": None if nota is None else round(nota, 1),
                "weight": ind_peso,
            })
            cobertura_den += peso * ind_peso
            if nota is not None:
                sub_soma += nota * ind_peso
                sub_peso += ind_peso
                cobertura_num += peso * ind_peso

        pilar_nota = (sub_soma / sub_peso) if sub_peso > 0 else None
        detail.append({
            "key": key, "label": label, "weight": peso,
            "score": None if pilar_nota is None else round(pilar_nota, 1),
            "components": comps,
        })
        if pilar_nota is not None:
            soma += pilar_nota * peso
            peso_usado += peso

    total = (soma / peso_usado) if peso_usado > 0 else None
    cobertura = (cobertura_num / cobertura_den) if cobertura_den else 0.0
    return {
        "total": None if total is None else round(total, 1),
        "cobertura": round(cobertura, 3),
        "parcial": cobertura < 0.60,
        "pilares": detail,
        "perfil": "financeiro" if financial else "corporativo",
    }


def grade(total: Optional[float]) -> str:
    """Faixa qualitativa mostrada no painel."""
    if total is None:
        return "—"
    if total >= 80:
        return "A+"
    if total >= 70:
        return "A"
    if total >= 60:
        return "B"
    if total >= 50:
        return "C"
    if total >= 40:
        return "D"
    return "E"


def band(total: Optional[float]) -> str:
    """Classe de cor usada pelo front-end."""
    if total is None:
        return "none"
    if total >= 70:
        return "good"
    if total >= 55:
        return "ok"
    if total >= 40:
        return "warn"
    return "bad"
