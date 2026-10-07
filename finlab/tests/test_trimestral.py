"""DRE completa (anos + trimestres + ano em curso + 12 meses), a janela dos
12 meses e a conferência do trimestral."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from finlab.backend import conferencia, cvm  # noqa: E402

CD = "009512"
RE = ("3.01", "Receita de Venda de Bens e/ou Serviços")
EB = ("3.05", "Resultado Antes do Resultado Financeiro e dos Tributos")
LU = ("3.11", "Lucro/Prejuízo Consolidado do Período")
DA = ("6.01.01.02", "Depreciação e Amortização")


def _l(fim, conta, valor, ini=None, ano_ref=None):
    fim = pd.Timestamp(fim)
    d = {"CD_CVM": CD, "DENOM_CIA": "X", "CNPJ_CIA": "x", "DT_FIM_EXERC": fim,
         "ORDEM_EXERC": "ÚLTIMO", "ANO_REFER": ano_ref or fim.year,
         "CD_CONTA": conta[0], "DS_CONTA": conta[1], "VL_CONTA_AJUSTADO": float(valor)}
    if ini:
        d["DT_INI_EXERC"] = pd.Timestamp(ini)
    return d


def _grava(tmp, nome, linhas):
    pd.DataFrame(linhas).to_parquet(tmp / f"{nome}.parquet", index=False)


@pytest.fixture
def empresa(tmp_path, monkeypatch):
    """2025 com 1T–3T no ITR e o ano na DFP; 2026 com 1T e 2T no ITR.

    Trimestres isolados — receita 100/110/120/(130 = 460 − 330)/140/150,
    EBIT 10/11/12/(13)/14/15, D&A 2 por trimestre (8 no ano), lucro 5/6/7/(8)/9/10.
    """
    monkeypatch.setattr(cvm, "CVM_PROCESSED_DIR", tmp_path)
    itr, dfc_itr = [], []
    for ano, tris in ((2025, ((100, 10, 5), (110, 11, 6), (120, 12, 7))),
                      (2026, ((140, 14, 9), (150, 15, 10)))):
        acc = [0, 0, 0]
        for i, (r, e, l) in enumerate(tris):
            fim = ("{}-03-31", "{}-06-30", "{}-09-30")[i].format(ano)
            acc = [acc[0] + r, acc[1] + e, acc[2] + l]
            ini = f"{ano}-01-01"
            itr += [_l(fim, RE, acc[0], ini), _l(fim, EB, acc[1], ini), _l(fim, LU, acc[2], ini)]
            dfc_itr.append(_l(fim, DA, 2 * (i + 1), ini))
    _grava(tmp_path, "dre_itr", itr)
    _grava(tmp_path, "dfc_mi_itr", dfc_itr)
    _grava(tmp_path, "dre_dfp", [_l("2025-12-31", RE, 460), _l("2025-12-31", EB, 46),
                                 _l("2025-12-31", LU, 26)])
    _grava(tmp_path, "dfc_mi_dfp", [_l("2025-12-31", DA, 8)])
    # balanço: dez/25 na DFP; jun/26 no ITR
    div = ("2.01.04", "Empréstimos e Financiamentos")
    _grava(tmp_path, "bpp_dfp", [_l("2025-12-31", div, 300)])
    _grava(tmp_path, "bpp_itr", [_l("2026-06-30", div, 280, "2026-01-01")])
    cvm.limpar_cache()
    yield tmp_path
    cvm.limpar_cache()


def _col(dre, rotulo):
    return [c["rotulo"] for c in dre["colunas"]].index(rotulo)


def _linha(dre, chave):
    return next(l for l in dre["linhas"] if l["chave"] == chave)["valores"]


def test_dre_completa_tem_trimestres_ano_em_curso_e_12_meses(empresa):
    dre = cvm.dre_completa(CD)
    rot = [c["rotulo"] for c in dre["colunas"]]
    # trimestres antes do exercício; o ano em curso com seus trimestres e o
    # acumulado; os 12 meses no fim
    assert rot == ["1T25", "2T25", "3T25", "4T25", "2025", "1T26", "2T26", "1S26", "12m · 2T26"]
    tipos = {c["rotulo"]: c["tipo"] for c in dre["colunas"]}
    assert tipos["2025"] == "ano" and tipos["1S26"] == "ytd" and tipos["12m · 2T26"] == "ltm"
    assert all(c["grupo"] == 2025 for c in dre["colunas"] if c["rotulo"].endswith("T25"))

    rec = _linha(dre, "receita")
    assert rec[_col(dre, "4T25")] == 130.0                  # DFP − 9M
    assert dre["colunas"][_col(dre, "4T25")]["derivado"] is True
    assert dre["colunas"][_col(dre, "1T25")]["derivado"] is False
    # os quatro trimestres somam o exercício
    assert sum(rec[_col(dre, f"{t}T25")] for t in (1, 2, 3, 4)) == rec[_col(dre, "2025")]
    assert rec[_col(dre, "1S26")] == 290.0                  # 140 + 150
    assert rec[_col(dre, "12m · 2T26")] == 120 + 130 + 140 + 150

    ebitda = _linha(dre, "ebitda")
    assert ebitda[_col(dre, "2T26")] == 15 + 2
    assert ebitda[_col(dre, "12m · 2T26")] == (12 + 13 + 14 + 15) + 4 * 2
    mg = _linha(dre, "mg_ebitda")
    assert mg[_col(dre, "12m · 2T26")] == pytest.approx(62 / 540)


def test_ltm_dos_multiplos_e_o_da_tabela_sao_o_mesmo(empresa):
    l = cvm.ltm_series(CD)
    dre = cvm.dre_completa(CD)
    assert l["rotulo"] == "LTM 2T26" and l["trimestre"] == "2T26" and l["exercicio"] == 2026
    assert l["campos"]["receita"] == _linha(dre, "receita")[-1]
    assert l["campos"]["ebitda"] == _linha(dre, "ebitda")[-1]
    # saldo: o balanço mais novo (jun/26, ITR), não o de dezembro
    assert l["campos"]["divida_bruta"] == 280.0
    assert l["saldo_em"] == "2026-06-30"


def test_ltm_nao_usa_janela_velha_para_conta_sem_o_ultimo_trimestre(empresa, tmp_path):
    """Sem a D&A do 2T26, o EBITDA 12m fica vazio — e não vira o EBITDA da
    janela até o 1T26 com o rótulo "LTM 2T26"."""
    dfc = pd.read_parquet(tmp_path / "dfc_mi_itr.parquet")
    dfc = dfc[dfc["DT_FIM_EXERC"] != pd.Timestamp("2026-06-30")]
    dfc.to_parquet(tmp_path / "dfc_mi_itr.parquet", index=False)
    cvm.limpar_cache()
    l = cvm.ltm_series(CD)
    assert l["rotulo"] == "LTM 2T26"
    assert l["campos"]["receita"] == 540.0
    assert l["campos"]["ebitda"] is None


def test_saldo_da_dfp_vence_itr_mais_velho(tmp_path, monkeypatch):
    """Depois da DFP e antes do 1T seguinte, o último ITR (set) está três
    meses atrás do balanço anual (dez): vale o de dezembro."""
    monkeypatch.setattr(cvm, "CVM_PROCESSED_DIR", tmp_path)
    div = ("2.01.04", "Empréstimos e Financiamentos")
    _grava(tmp_path, "bpp_itr", [_l("2025-09-30", div, 500, "2025-01-01")])
    _grava(tmp_path, "bpp_dfp", [_l("2025-12-31", div, 420)])
    cvm.limpar_cache()
    try:
        data, valor = cvm._saldo_mais_recente(CD, "bpp", ["2.01.04"], None)
        assert str(data.date()) == "2025-12-31" and valor == 420.0
    finally:
        cvm.limpar_cache()


def test_sem_itr_a_dre_segue_so_anual(tmp_path, monkeypatch):
    monkeypatch.setattr(cvm, "CVM_PROCESSED_DIR", tmp_path)
    _grava(tmp_path, "dre_dfp", [_l("2024-12-31", RE, 400), _l("2025-12-31", RE, 460)])
    cvm.limpar_cache()
    try:
        dre = cvm.dre_completa(CD)
        assert [c["rotulo"] for c in dre["colunas"]] == ["2024", "2025"]
        assert all(c["tipo"] == "ano" for c in dre["colunas"])
        assert cvm.ltm_series(CD) == {}
    finally:
        cvm.limpar_cache()


def test_ano_em_curso_com_um_trimestre_nao_ganha_acumulado(tmp_path, monkeypatch):
    """Com só o 1T26, o acumulado seria o próprio 1T: a coluna não aparece."""
    monkeypatch.setattr(cvm, "CVM_PROCESSED_DIR", tmp_path)
    itr = []
    for fim, acc in (("2025-03-31", 100), ("2025-06-30", 210), ("2025-09-30", 330)):
        itr.append(_l(fim, RE, acc, "2025-01-01"))
    itr.append(_l("2026-03-31", RE, 140, "2026-01-01"))
    _grava(tmp_path, "dre_itr", itr)
    _grava(tmp_path, "dre_dfp", [_l("2025-12-31", RE, 460)])
    cvm.limpar_cache()
    try:
        rot = [c["rotulo"] for c in cvm.dre_completa(CD)["colunas"]]
        assert rot == ["1T25", "2T25", "3T25", "4T25", "2025", "1T26", "12m · 1T26"]
    finally:
        cvm.limpar_cache()


# ---------------------------------------------------------------------------
# Conferência
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hoje, esperado", [
    (date(2026, 10, 7), date(2026, 6, 30)),
    (date(2026, 8, 18), date(2026, 3, 31)),     # 2T ainda dentro do prazo
    (date(2026, 8, 20), date(2026, 6, 30)),
    (date(2026, 4, 10), date(2025, 12, 31)),    # DFP já saiu, 1T ainda não
    (date(2026, 1, 15), date(2025, 9, 30)),
])
def test_trimestre_que_ja_deveria_estar_publicado(hoje, esperado):
    assert conferencia._trimestre_esperado(hoje) == esperado


def test_conferencia_avisa_itr_atrasado(empresa):
    class Comp:
        ticker, cd_cvm = "XPTO3", CD
    ok = conferencia.conferir_empresa(Comp, date(2026, 10, 7))
    assert ok["trimestre"] == "2T26" and ok["status"] == "ok", ok["avisos"]
    atrasado = conferencia.conferir_empresa(Comp, date(2026, 12, 1))   # 3T26 já deveria existir
    assert atrasado["status"] == "aviso"
    assert any("3T26" in a for a in atrasado["avisos"])
