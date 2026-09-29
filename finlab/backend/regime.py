"""Classificação de regime da empresa (taxonomia R0–R5 do parecer 05).

O painel de valuation nasceu assumindo um único mundo: empresa em operação
normal, cuja média de 3 anos de FCO−capex é uma estimativa honesta do
run-rate. Esse mundo é o R0 — e é o único em que a premissa se sustenta. Numa
empresa vendendo ativos, o caixa da venda não é fluxo operacional e não se
perpetua; numa em expansão, o FCL é negativo por escolha, não por fraqueza.

Este módulo lê as demonstrações e diz em que mundo a empresa está, com a
evidência datada que sustenta a leitura. Três regras vindas do parecer, que
valem mais que a precisão da classificação:

  1. **Sem dado é "sem classificação"**, nunca R0 por omissão. Um painel que
     chuta "operação normal" quando não sabe é pior que um painel que cala.
  2. **Um exercício não muda regime.** Salvo o evento estrutural, que é
     estrutural justamente por não precisar de repetição, todo sinal exige
     dois exercícios consecutivos. Sem isso o rótulo oscila a cada release.
  3. **Toda inferência carrega confiança visível e a conta que a originou.**
     O número que virou evidência aparece junto, para o usuário conferir.

Limite conhecido desta fase: só sinais contábeis. Guidance, troca de gestão,
linguagem de call e fato relevante — metade da taxonomia do parecer — só
entram quando a ingestão do índice IPE existir. Por isso a confiança máxima
aqui é "média" para os regimes que dependem de intenção declarada.
"""

from __future__ import annotations

from typing import Optional

# ---------------------------------------------------------------------------
# Taxonomia
# ---------------------------------------------------------------------------
#
# `quebra` é o que deixa de valer no valuation; `fluxo` é o tratamento que o
# fluxo-base deveria receber. Por ora os dois são texto: o motor ainda não age
# sozinho sobre o regime — mostrar o diagnóstico vem antes de mudar o número.

REGIMES: dict[str, dict] = {
    "R0": {
        "rotulo": "Operação normal",
        "quebra": "Nada. É o único regime em que a média de 3 anos de FCO − capex "
                  "é uma estimativa honesta do run-rate.",
        "fluxo": "Média de 3 anos, como o painel já faz.",
    },
    "R1": {
        "rotulo": "Expansão / capex pesado",
        "quebra": "O FCL é negativo por escolha, não por fraqueza. A média de 3 anos "
                  "subestima o poder de geração maduro, e o EV/EBITDA engana porque o "
                  "EBITDA ainda não reflete a capacidade instalada.",
        "fluxo": "Fluxo do ativo maduro: EBITDA normalizado menos capex de manutenção "
                 "(não o capex total, que embute a expansão).",
    },
    "R2": {
        "rotulo": "Desalavancagem",
        "quebra": "O fluxo vai para o credor, não para o acionista. O DCF de fluxo da "
                  "firma continua válido, mas a ponte EV→equity muda de ano para ano.",
        "fluxo": "FCL de 12 meses móveis, com a ponte EV→equity recalculada por ano "
                 "de projeção.",
    },
    "R3": {
        "rotulo": "Turnaround",
        "quebra": "Todo o histórico vira irrelevante como base: a média de 3 anos "
                  "mistura o regime velho com o novo, e a margem histórica não é "
                  "âncora. O valor está numa distribuição de cenários, não num ponto.",
        "fluxo": "12 meses móveis do negócio core, ex-itens marcados — nunca a média "
                 "histórica.",
    },
    "R4": {
        "rotulo": "Reestruturação de portfólio",
        "quebra": "Caixa de venda de ativo não é fluxo operacional e não se perpetua. "
                  "Colocar isso no fluxo-base e crescer por 5 anos mais perpetuidade é "
                  "o erro de valuation mais caro que existe.",
        "fluxo": "Soma das partes: DCF do negócio contínuo mais o valor líquido de "
                 "realização dos ativos à venda, com deságio.",
    },
    "R5": {
        "rotulo": "Integração de M&A",
        "quebra": "O EBITDA reportado carrega custos não recorrentes de integração e "
                  "sinergias ainda não capturadas. A comparação com pares perde "
                  "sentido por 4 a 8 trimestres.",
        "fluxo": "Média de 3 anos, mas com os pares desqualificados como âncora "
                 "enquanto a integração corre.",
    },
}

# Ordem de precedência quando mais de um regime dispara. Não é arbitrária: é o
# quanto cada um destrói a base do modelo. R3 invalida o histórico inteiro; R4
# contamina o fluxo com caixa que não se repete; R1 distorce o nível; R2 e R5
# mexem na ponte e na comparação, sem quebrar o fluxo-base.
PRECEDENCIA = ["R3", "R4", "R1", "R2", "R5"]

MIN_EXERCICIOS = 3          # abaixo disso não há como exigir persistência

# Capex abaixo disso não sustenta "regime de capex pesado", por maior que seja
# a razão contra a depreciação. Aferido nas 90 ações do universo: é onde as
# empresas leves em ativo (incorporadora, distribuidora, bens de capital) se
# separam de saneamento, ferrovia, mineração, shoppings e energia.
CAPEX_MATERIAL = 0.08

# Toda companhia mexe no portfólio de vez em quando; regime é outra coisa. Os
# cortes separam a arrumação da reestruturação: com 1% da receita entravam a
# Totvs (item de 79 M sobre lucro de 921 M) e a Copel, que venderam pontas sem
# mudar de regime. Contra o lucro o teste é mais fiel ao que importa — quanto
# do poder de gerar resultado está saindo — e a receita fica como rede para
# quem está no prejuízo, onde o lucro não serve de denominador.
DESC_SOBRE_LUCRO = 0.20
DESC_SOBRE_RECEITA = 0.03


# ---------------------------------------------------------------------------
# Utilidades sobre as séries
# ---------------------------------------------------------------------------

def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and v == v else None


def _ultimos(series: dict, campo: str, anos: list, n: int) -> list[tuple]:
    """Os n exercícios mais recentes com valor, como [(ano, valor), ...]."""
    vals = series.get(campo) or []
    par = [(a, _num(v)) for a, v in zip(anos, vals)]
    return [(a, v) for a, v in par if v is not None][-n:]


def _pct(a: float, b: float) -> Optional[float]:
    return None if not b else a / b


# ---------------------------------------------------------------------------
# Sinais
# ---------------------------------------------------------------------------
#
# Cada sinal devolve (disparou, [evidências]). Evidência é sempre um fato com
# ano e número — nunca uma paráfrase.

def _ev(regime: str, ano: int, texto: str, valor=None, estrutural: bool = False) -> dict:
    """`estrutural` marca o fato que dispensa repetição: ele não é uma leitura
    de tendência, é um evento que ou aconteceu ou não."""
    return {"regime": regime, "exercicio": int(ano), "texto": texto, "valor": valor,
            "estrutural": estrutural}


def _sinal_desinvestimento(s: dict, anos: list) -> tuple[bool, list]:
    """R4 — resultado de operações descontinuadas materialmente diferente de zero.

    A linha só é preenchida quando a companhia segregou uma operação que está
    saindo. É evento estrutural: não exige repetição. O casamento é por
    descrição e não por código de conta — o código muda entre o plano da
    indústria e o de seguradora (ver a nota em `cvm.annual_series`).
    """
    evid = []
    desc = _ultimos(s, "descontinuadas", anos, 2)
    for ano, v in desc:
        if abs(v) < 1.0:
            continue
        rec = dict(_ultimos(s, "receita", anos, 10)).get(ano)
        lucro = dict(_ultimos(s, "lucro_liquido", anos, 10)).get(ano)
        # Material contra o resultado, ou contra a receita como rede para quem
        # está no prejuízo (ver os cortes e o porquê no topo do módulo).
        rel_rec = _pct(abs(v), abs(rec)) if rec else None
        rel_luc = _pct(abs(v), abs(lucro)) if lucro else None
        if (rel_rec or 0) >= DESC_SOBRE_RECEITA or (rel_luc or 0) >= DESC_SOBRE_LUCRO:
            evid.append(_ev("R4", ano,
                            "resultado de operações descontinuadas segregado no DRE",
                            v, estrutural=True))
    return bool(evid), evid


def _sinal_expansao(s: dict, anos: list) -> tuple[bool, list]:
    """R1 — capex muito acima da depreciação E material contra a receita.

    Capex ≈ depreciação é manutenção; 1,5× é onde a diferença deixa de ser
    ruído de ciclo de reposição. Exige dois exercícios: um ano de capex alto é
    troca de frota, não plano de expansão.

    A trava de materialidade não é decorativa. Numa incorporadora a depreciação
    é quase nada (terreno e estoque não depreciam), então a razão dispara sem
    que exista expansão alguma: a MRV aparecia com "capex de 7,2× a
    depreciação" investindo 4,7% da receita. Medindo o capex contra a receita,
    as empresas leves em ativo saem e sobram as que de fato imobilizam —
    saneamento, ferrovia, mineração, shoppings, energia.
    """
    capex = dict(_ultimos(s, "capex", anos, 3))
    deprec = dict(_ultimos(s, "depreciacao", anos, 3))
    receita = dict(_ultimos(s, "receita", anos, 3))
    comuns = sorted(set(capex) & set(deprec) & set(receita))[-2:]
    if len(comuns) < 2:
        return False, []

    evid = []
    for ano in comuns:
        razao = _pct(abs(capex[ano]), abs(deprec[ano]))
        intensidade = _pct(abs(capex[ano]), abs(receita[ano]))
        if razao is None or razao < 1.5:
            return False, []
        if intensidade is None or intensidade < CAPEX_MATERIAL:
            return False, []
        evid.append(_ev("R1", ano, f"capex de {razao:.1f}× a depreciação e "
                                   f"{intensidade:.0%} da receita", razao))

    imob = _ultimos(s, "imobilizado", anos, 3)
    if len(imob) >= 2 and imob[-1][1] > imob[-2][1]:
        evid.append(_ev("R1", imob[-1][0], "imobilizado maior que no exercício anterior",
                        imob[-1][1] - imob[-2][1]))
    return True, evid


def _sinal_desalavancagem(s: dict, anos: list) -> tuple[bool, list]:
    """R2 — dívida líquida caindo dois exercícios seguidos, com caixa operacional
    positivo (senão é venda de ativo pagando dívida, que é R4, não R2)."""
    dl = _ultimos(s, "divida_liquida", anos, 3)
    if len(dl) < 3:
        return False, []
    fco = dict(_ultimos(s, "fco", anos, 3))

    quedas = []
    for (ano_a, va), (ano_b, vb) in zip(dl, dl[1:]):
        if vb < va and fco.get(ano_b, 0) > 0:
            quedas.append(_ev("R2", ano_b, "dívida líquida menor que no exercício "
                                           "anterior, com caixa operacional positivo",
                              vb - va))
    if len(quedas) < 2:
        return False, []
    # Empresa com caixa líquido não está desalavancando: está aplicando.
    if dl[-1][1] <= 0:
        return False, []
    return True, quedas[-2:]


def _sinal_turnaround(s: dict, anos: list) -> tuple[bool, list]:
    """R3 — prejuízo no último exercício, confirmado por prejuízo anterior ou por
    colapso da margem operacional contra a própria história."""
    # Patrimônio líquido negativo é estrutural e dispensa confirmação: a
    # empresa consumiu o capital dos sócios. Entra antes do teste de prejuízo
    # porque um lucro simbólico esconde a situação — a Azul voltou ao azul em
    # 2025 por 0,12 bi carregando patrimônio de −29 bi, e sem este sinal saía
    # classificada como operação normal.
    pl = _ultimos(s, "patrimonio_liquido", anos, 1)
    if pl and pl[0][1] < 0:
        return True, [_ev("R3", pl[0][0],
                          "patrimônio líquido negativo — o capital dos sócios foi "
                          "consumido", pl[0][1], estrutural=True)]

    lucro = _ultimos(s, "lucro_liquido", anos, 3)
    if len(lucro) < 2 or lucro[-1][1] >= 0:
        return False, []

    evid = [_ev("R3", lucro[-1][0], "prejuízo no exercício", lucro[-1][1])]
    if lucro[-2][1] < 0:
        evid.append(_ev("R3", lucro[-2][0], "prejuízo também no exercício anterior",
                        lucro[-2][1]))
        return True, evid

    # Sem dois prejuízos, aceita colapso de margem: a operação piorou de forma
    # que a média histórica deixou de descrever.
    ebit = dict(_ultimos(s, "ebit", anos, 5))
    rec = dict(_ultimos(s, "receita", anos, 5))
    margens = {a: _pct(ebit[a], rec[a]) for a in sorted(set(ebit) & set(rec))
               if _pct(ebit[a], rec[a]) is not None}
    if len(margens) >= 3:
        ult = sorted(margens)[-1]
        antes = [margens[a] for a in sorted(margens)[:-1][-3:]]
        media = sum(antes) / len(antes)
        if media > 0 and margens[ult] < media * 0.5:
            evid.append(_ev("R3", ult, f"margem operacional de {margens[ult]:.1%} "
                                       f"contra média histórica de {media:.1%}",
                            margens[ult]))
            return True, evid
    return False, []


def _sinal_ma(s: dict, anos: list) -> tuple[bool, list]:
    """R5 — salto de intangível num exercício: o ágio de uma combinação de
    negócios entra aqui. Evento estrutural, não exige repetição."""
    intang = _ultimos(s, "intangivel", anos, 3)
    ativo = dict(_ultimos(s, "ativo_total", anos, 3))
    if len(intang) < 2:
        return False, []
    (ano_a, va), (ano_b, vb) = intang[-2], intang[-1]
    if va <= 0 or vb <= va:
        return False, []
    salto = (vb - va) / va
    peso = _pct(vb - va, ativo.get(ano_b)) or 0
    # 30% de alta E 5% do ativo: junto, isso é aquisição, não capitalização de
    # software. Qualquer um dos dois sozinho pega ruído demais.
    if salto >= 0.30 and peso >= 0.05:
        return True, [_ev("R5", ano_b,
                          f"intangível {salto:.0%} maior, equivalente a {peso:.0%} "
                          f"do ativo total", vb - va, estrutural=True)]
    return False, []


SINAIS = {
    "R4": _sinal_desinvestimento,
    "R1": _sinal_expansao,
    "R2": _sinal_desalavancagem,
    "R3": _sinal_turnaround,
    "R5": _sinal_ma,
}


# ---------------------------------------------------------------------------
# Classificação
# ---------------------------------------------------------------------------

def _sem_classificacao(motivo: str) -> dict:
    return {
        "codigo": None,
        "rotulo": "Sem classificação",
        "modificador": None,
        "confianca": None,
        "evidencias": [],
        "motivo": motivo,
        "quebra": None,
        "fluxo": None,
        "parcial": True,
    }


def classificar(fundamentals: dict) -> dict:
    """Devolve o regime da empresa a partir das séries anuais da CVM.

    Recebe o dicionário de `cvm.annual_series()` (ou o payload equivalente de
    um BDR) para não reler os parquets — o front já tem esses números na mão.
    """
    if not isinstance(fundamentals, dict):
        return _sem_classificacao("sem demonstrações carregadas")

    anos = fundamentals.get("years") or []
    series = fundamentals.get("series") or {}
    if len(anos) < MIN_EXERCICIOS:
        return _sem_classificacao(
            f"são precisos {MIN_EXERCICIOS} exercícios para exigir confirmação de um "
            f"regime; há {len(anos)}")

    # Sem resultado nem fluxo de caixa não há o que classificar. Chutar "operação
    # normal" aqui seria exatamente o erro que a regra 1 do parecer proíbe.
    if not _ultimos(series, "lucro_liquido", anos, 1) and not _ultimos(series, "fco", anos, 1):
        return _sem_classificacao("as demonstrações vieram sem resultado nem fluxo de caixa")

    disparados: dict[str, list] = {}
    for codigo, sinal in SINAIS.items():
        try:
            ok, evid = sinal(series, anos)
        except Exception:      # série malformada não pode derrubar o painel
            ok, evid = False, []
        if ok and evid:
            disparados[codigo] = evid

    ordem = [c for c in PRECEDENCIA if c in disparados]
    if not ordem:
        return {
            "codigo": "R0",
            "rotulo": REGIMES["R0"]["rotulo"],
            "modificador": None,
            "confianca": "media" if len(anos) >= 5 else "baixa",
            "evidencias": [_ev("R0", anos[-1],
                               "nenhum sinal de expansão, desalavancagem, turnaround, "
                               "desinvestimento ou integração nas demonstrações", None)],
            "motivo": None,
            "quebra": REGIMES["R0"]["quebra"],
            "fluxo": REGIMES["R0"]["fluxo"],
            "parcial": True,
        }

    principal = ordem[0]
    modificador = ordem[1] if len(ordem) > 1 else None
    evid = disparados[principal] + (disparados.get(modificador) or [])

    return {
        "codigo": principal,
        "rotulo": REGIMES[principal]["rotulo"],
        "modificador": ({"codigo": modificador, "rotulo": REGIMES[modificador]["rotulo"]}
                        if modificador else None),
        "confianca": _confianca(principal, disparados, anos),
        "evidencias": evid,
        "motivo": None,
        "quebra": REGIMES[principal]["quebra"],
        "fluxo": REGIMES[principal]["fluxo"],
        "parcial": True,
    }


def _confianca(principal: str, disparados: dict, anos: list) -> str:
    """Alta exige mais de uma evidência independente e histórico para confirmar.

    Nunca passa de "média" enquanto a leitura for só contábil: guidance, troca
    de gestão e fato relevante — que é metade da taxonomia — ainda não entram.
    """
    evid = disparados[principal]
    if len(anos) < 5:
        return "baixa"
    # Um fato estrutural sozinho pesa mais que duas leituras de tendência:
    # patrimônio negativo ou operação segregada no DRE ou aconteceu, ou não.
    if any(e.get("estrutural") for e in evid) or len(evid) >= 2:
        return "media"
    return "baixa"
