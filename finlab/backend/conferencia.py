"""Conferência dos dados trimestrais (ITR) das ações do painel.

    python -m finlab.backend.tarefas conferir-trimestres

Roda nas 90 ações com os parquets da CVM que estão no disco (sem rede) e
diz, empresa a empresa, se o ano em curso e os 12 meses estão de pé:

  * qual o último exercício (DFP) e o último trimestre (ITR) processados;
  * se o último trimestre é o que já deveria estar publicado hoje (o ITR
    sai até 45 dias depois do fim do trimestre; a DFP, até 31/mar);
  * se receita, lucro e EBITDA dos 12 meses existem — sem o EBITDA 12m, o
    Dív.Líq/EBITDA cai para o exercício fechado e fica defasado;
  * Dív.Líq/EBITDA do exercício contra o dos 12 meses, lado a lado;
  * trimestre com receita negativa (sinal de acumulado mal desfeito).
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd

from . import cvm, universe


def _trimestre_esperado(hoje: date) -> date:
    """O fim do trimestre mais recente que já deveria estar publicado hoje.

    Prazos da CVM: ITR em até 45 dias do fim do 1T, 2T e 3T; o 4T vem na DFP,
    até 31 de março. Usa uma folga de 5 dias para a CVM disponibilizar o
    arquivo e o pipeline baixar.
    """
    candidatos = []
    for ano in (hoje.year - 1, hoje.year):
        candidatos += [(date(ano, 3, 31), date(ano, 5, 20)),
                       (date(ano, 6, 30), date(ano, 8, 19)),
                       (date(ano, 9, 30), date(ano, 11, 19)),
                       (date(ano, 12, 31), date(ano + 1, 4, 5))]
    publicados = [fim for fim, prazo in candidatos if prazo <= hoje]
    return max(publicados)


def _rot(fim: date) -> str:
    return f"{(fim.month - 1) // 3 + 1}T{str(fim.year)[-2:]}"


def _nd(divida: Optional[float], ebitda: Optional[float]) -> Optional[float]:
    if divida is None or not ebitda:
        return None
    return divida / ebitda


def conferir_empresa(comp, hoje: date) -> dict:
    cd = comp.cd_cvm
    fin = universe.is_financial(comp.ticker) or (cvm.is_financial_statement(cd) if cd else False)
    linha = {"ticker": comp.ticker, "financeira": fin, "exercicio": None,
             "trimestre": None, "nd_ano": None, "nd_12m": None,
             "avisos": [], "status": "ok"}
    if not cd:
        linha["avisos"].append("sem código CVM no universo")
        linha["status"] = "erro"
        return linha

    anual = cvm.annual_series(cd)
    anos = anual.get("years") or []
    if not anos:
        linha["avisos"].append("sem DFP processada")
        linha["status"] = "erro"
        return linha
    linha["exercicio"] = anos[-1]
    # A DFP do ano anterior sai até 31/mar: depois disso, faltar é sinal de
    # pipeline parado ou de empresa que deixou de reportar (saiu da bolsa).
    esperado_dfp = hoje.year - 1 if hoje >= date(hoje.year, 4, 5) else hoje.year - 2
    if int(anos[-1]) < esperado_dfp:
        linha["avisos"].append(f"último exercício é {anos[-1]}, mas a DFP de {esperado_dfp} "
                               "já deveria existir — empresa parou de reportar?")
    s = anual.get("series") or {}
    if not fin:
        linha["nd_ano"] = _nd((s.get("divida_liquida") or [None])[-1],
                              (s.get("ebitda") or [None])[-1])

    ltm = cvm.ltm_series(cd)
    if not ltm:
        linha["avisos"].append("sem ITR processado — o painel fica só no anual "
                               "(rode atualizar-dados.sh)")
        linha["status"] = "aviso"
        return linha
    linha["trimestre"] = ltm.get("trimestre")
    campos = ltm.get("campos") or {}
    fim = pd.Timestamp(ltm["fim"]).date()

    esperado = _trimestre_esperado(hoje)
    if fim < esperado:
        linha["avisos"].append(f"último dado é {ltm.get('trimestre')}, mas {_rot(esperado)} "
                               "já deveria estar publicado — rode atualizar-dados.sh")
    for chave, nome in (("receita", "receita"), ("lucro_liquido", "lucro")):
        if campos.get(chave) is None:
            linha["avisos"].append(f"sem {nome} dos 12 meses")
    if not fin:
        linha["nd_12m"] = _nd(campos.get("divida_liquida"), campos.get("ebitda"))
        if campos.get("ebitda") is None:
            linha["avisos"].append("sem EBITDA dos 12 meses (D&A ausente no ITR) — "
                                   "Dív.Líq/EBITDA cai para o exercício")
        if campos.get("divida_liquida") is None:
            linha["avisos"].append("sem dívida líquida no balanço do ITR")

    if not fin:
        dre = cvm.dre_completa(cd)
        receita = next((l for l in dre.get("linhas") or [] if l["chave"] == "receita"), None)
        if receita:
            neg = [c["rotulo"] for c, v in zip(dre["colunas"], receita["valores"])
                   if c["tipo"] == "tri" and isinstance(v, (int, float)) and v < 0]
            if neg:
                linha["avisos"].append("receita trimestral negativa em " + ", ".join(neg))

    if linha["avisos"]:
        linha["status"] = "aviso"
    return linha


def conferir(hoje: Optional[date] = None, tickers: Optional[list] = None) -> list[dict]:
    hoje = hoje or date.today()
    alvo = [c for c in universe.UNIVERSE if not tickers or c.ticker in tickers]
    out = []
    for comp in alvo:
        try:
            out.append(conferir_empresa(comp, hoje))
        except Exception as exc:  # uma empresa quebrada não derruba a conferência
            out.append({"ticker": comp.ticker, "status": "erro", "exercicio": None,
                        "trimestre": None, "nd_ano": None, "nd_12m": None,
                        "financeira": False, "avisos": [f"falhou: {exc!r}"]})
    return out


def relatorio(linhas: list[dict], hoje: Optional[date] = None) -> str:
    hoje = hoje or date.today()
    fx = lambda v: "—" if v is None else f"{v:,.1f}x".replace(",", "X").replace(".", ",").replace("X", ".")
    txt = [f"Conferência do trimestral · {hoje:%d/%m/%Y} · último trimestre que já "
           f"deveria estar publicado: {_rot(_trimestre_esperado(hoje))}", "",
           f"{'ticker':8} {'DFP':>5} {'ITR':>5} {'DL/EBITDA ano':>14} {'DL/EBITDA 12m':>14}  situação"]
    for l in linhas:
        situacao = "ok" if l["status"] == "ok" else "; ".join(l["avisos"])
        txt.append(f"{l['ticker']:8} {str(l['exercicio'] or '—'):>5} {str(l['trimestre'] or '—'):>5} "
                   f"{('n/a' if l['financeira'] else fx(l['nd_ano'])):>14} "
                   f"{('n/a' if l['financeira'] else fx(l['nd_12m'])):>14}  {situacao}")
    n = {k: sum(1 for l in linhas if l["status"] == k) for k in ("ok", "aviso", "erro")}
    txt += ["", f"{len(linhas)} ações · {n['ok']} ok · {n['aviso']} com aviso · {n['erro']} com erro"]
    return "\n".join(txt)
