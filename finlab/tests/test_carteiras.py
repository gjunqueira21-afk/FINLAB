"""Testes das carteiras acompanhadas e do arquivo de deep research.

Rodar: python -m pytest finlab/tests/test_carteiras.py -q

Preço aqui é sempre mockado (o sandbox não fala com fonte nenhuma): o que
se testa é a aritmética da cota, a derivação de pesos, os alertas de banda,
os avisos de qualidade e os dois bugs que a revisão financeira pegou na v1
(edição apagando movimento e benchmark morrendo em silêncio).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from finlab.backend import carteiras, deep, market  # noqa: E402


# ---------------------------------------------------------------------------
# Infra: tudo em tmp_path, preços de mentira com data controlada
# ---------------------------------------------------------------------------

@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(carteiras, "DIR_CARTEIRAS", tmp_path / "carteiras")
    monkeypatch.setattr(deep, "DIR_DEEP", tmp_path / "deep empresas")

    estado = {"precos": {}, "bench": None}

    def fake_price_series(tickers):
        return {tk: estado["precos"].get(tk, []) for tk in tickers}

    def fake_asset_series(tickers):
        return {carteiras.BENCHMARK: estado["bench"] or []}

    monkeypatch.setattr(market, "price_series", fake_price_series)
    monkeypatch.setattr(market, "asset_series", fake_asset_series)
    return estado


def _hoje():
    return carteiras._hoje()


def poe_precos(estado, precos: dict[str, float], data: str = None):
    d = data or _hoje()
    for tk, p in precos.items():
        estado["precos"].setdefault(tk, []).append((d, p))


def poe_bench(estado, preco: float, data: str = None):
    estado["bench"] = (estado["bench"] or []) + [(data or _hoje(), preco)]


PAYLOAD = {
    "nome": "Qualidade BR",
    "mandato": "Compounders com ROIC alto",
    "origem": "mesa",
    "posicoes": [
        {"ticker": "WEGE3", "peso": 0.5, "tese": "ROIC de 25% sustentado"},
        {"ticker": "PETR4", "peso": 0.3, "tese": "FCF yield de 15%"},
        {"ticker": "ITUB4", "peso": 0.2, "tese": "ROE 21% acima do custo"},
    ],
    "regras": {"banda": 5, "macro": "Selic acima de 12% favorece caixa"},
}


def carteira_padrao(estado, **override):
    poe_precos(estado, {"WEGE3": 40.0, "PETR4": 30.0, "ITUB4": 25.0})
    poe_bench(estado, 100.0)
    payload = {**PAYLOAD, **override}
    return carteiras.criar(payload)


# ---------------------------------------------------------------------------
# Criação e normalização
# ---------------------------------------------------------------------------

def test_criar_normaliza_e_abre_com_cota_100(sandbox):
    c = carteira_padrao(sandbox)
    assert c["atual"]["cota"] == 100.0
    assert c["atual"]["retorno"] == 0.0
    assert abs(sum(p["peso"] for p in c["posicoes"]) - 1.0) < 1e-6
    assert c["bench"]["preco0"] == 100.0
    assert c["origem"] == "mesa"
    # persistiu em disco, recarrega igual
    relido = carteiras.obter(c["id"])
    assert relido["nome"] == "Qualidade BR"


def test_pesos_em_percentual_viram_fracao(sandbox):
    poe_precos(sandbox, {"WEGE3": 40.0, "PETR4": 30.0})
    c = carteiras.criar({"nome": "Pct", "posicoes": [
        {"ticker": "WEGE3", "peso": 60}, {"ticker": "PETR4", "peso": 40}]})
    pesos = {p["ticker"]: p["peso"] for p in c["posicoes"]}
    assert abs(pesos["WEGE3"] - 0.6) < 1e-6
    assert abs(pesos["PETR4"] - 0.4) < 1e-6


@pytest.mark.parametrize("posicoes,erro", [
    ([], "pelo menos uma"),
    ([{"ticker": "WEGE3", "peso": 0.5}, {"ticker": "WEGE3", "peso": 0.5}], "duas vezes"),
    ([{"ticker": "XXXX9", "peso": 1.0}], "fora do universo"),
    ([{"ticker": "WEGE3", "peso": -1}], "peso positivo"),
    ([{"ticker": "WEGE3", "peso": 0.4}, {"ticker": "PETR4", "peso": 2.0}], "somam"),
])
def test_posicoes_invalidas_sao_recusadas_com_mensagem(sandbox, posicoes, erro):
    with pytest.raises(carteiras.CarteiraInvalida, match=erro):
        carteiras.criar({"nome": "X", "posicoes": posicoes})


def test_banda_invalida_e_erro_nao_default_silencioso(sandbox):
    poe_precos(sandbox, {"WEGE3": 40.0})
    with pytest.raises(carteiras.CarteiraInvalida, match="[Bb]anda"):
        carteiras.criar({"nome": "X", "regras": {"banda": 60},
                         "posicoes": [{"ticker": "WEGE3", "peso": 1.0}]})


def test_preco_velho_recusa_abertura(sandbox):
    poe_precos(sandbox, {"WEGE3": 40.0}, data="2024-01-05")
    with pytest.raises(carteiras.CarteiraInvalida, match="velho demais"):
        carteiras.criar({"nome": "X", "posicoes": [{"ticker": "WEGE3", "peso": 1.0}]})


# ---------------------------------------------------------------------------
# Snapshot: cota, pesos derivados, alertas, avisos
# ---------------------------------------------------------------------------

def test_atualizar_deriva_pesos_e_alerta_banda(sandbox):
    c = carteira_padrao(sandbox)
    # WEGE3 +50%, resto parado → peso passa de 50% para 60%: fora da banda de 5pp
    poe_precos(sandbox, {"WEGE3": 60.0, "PETR4": 30.0, "ITUB4": 25.0})
    poe_bench(sandbox, 110.0)
    c = carteiras.atualizar(c["id"])
    atual = c["atual"]
    assert atual["cota"] == pytest.approx(125.0)          # 0.5*1.5+0.3+0.2 = 1.25
    assert atual["retorno"] == pytest.approx(0.25)
    assert atual["pesos"]["WEGE3"] == pytest.approx(0.6)
    assert atual["retorno_bench"] == pytest.approx(0.10)
    # WEGE3 subiu para 60% (+10pp) e PETR4 caiu para 24% (−6pp): dois alertas
    assert len(atual["alertas"]) == 2
    assert any("WEGE3" in a for a in atual["alertas"])


def test_salto_de_30pct_gera_aviso_de_split(sandbox):
    c = carteira_padrao(sandbox)
    poe_precos(sandbox, {"WEGE3": 20.0, "PETR4": 30.0, "ITUB4": 25.0})
    c = carteiras.atualizar(c["id"])
    assert any("split" in a for a in c["atual"]["avisos"])


def test_papel_sem_preco_novo_congela_com_aviso(sandbox):
    c = carteira_padrao(sandbox)
    sandbox["precos"]["ITUB4"] = []           # sumiu da fonte (OPA?)
    poe_precos(sandbox, {"WEGE3": 44.0, "PETR4": 33.0})
    c = carteiras.atualizar(c["id"])
    assert c["atual"]["precos"]["ITUB4"] == 25.0
    assert any("congelada" in a for a in c["atual"]["avisos"])
    # 0.5*1.1 + 0.3*1.1 + 0.2*1.0 = 1.08
    assert c["atual"]["cota"] == pytest.approx(108.0)


def test_bench_indisponivel_nao_mata_a_serie(sandbox):
    c = carteira_padrao(sandbox)
    sandbox["bench"] = []
    poe_precos(sandbox, {"WEGE3": 44.0, "PETR4": 30.0, "ITUB4": 25.0})
    c = carteiras.atualizar(c["id"])
    assert c["atual"]["retorno_bench"] is None
    assert any(carteiras.BENCHMARK in a for a in c["atual"]["avisos"])
    assert c["bench"]["preco0"] == 100.0       # âncora intocada
    poe_bench(sandbox, 105.0)                  # fonte voltou
    c = carteiras.atualizar(c["id"])
    assert c["atual"]["retorno_bench"] == pytest.approx(0.05)


def test_mesmo_dia_substitui_snapshot_em_vez_de_duplicar(sandbox):
    c = carteira_padrao(sandbox)
    poe_precos(sandbox, {"WEGE3": 41.0, "PETR4": 30.0, "ITUB4": 25.0})
    c = carteiras.atualizar(c["id"])
    c = carteiras.atualizar(c["id"])
    assert len(c["snapshots"]) == 1


# ---------------------------------------------------------------------------
# Rebalancear e editar — os bugs da v1 não voltam
# ---------------------------------------------------------------------------

def test_rebalancear_mantem_cota_e_zera_desvios(sandbox):
    c = carteira_padrao(sandbox)
    poe_precos(sandbox, {"WEGE3": 60.0, "PETR4": 30.0, "ITUB4": 25.0})
    poe_bench(sandbox, 100.0)
    carteiras.atualizar(c["id"])
    c = carteiras.rebalancear(c["id"])
    assert c["atual"]["cota"] == pytest.approx(125.0)   # cota contínua
    assert c["base"]["cota_base"] == pytest.approx(125.0)
    assert c["atual"]["pesos"]["WEGE3"] == pytest.approx(0.5)  # de volta ao alvo
    assert c["atual"]["alertas"] == []
    assert any(e["tipo"] == "rebalanceamento" for e in c["eventos"])


def test_editar_pesos_anda_a_cota_com_a_composicao_antiga_antes_da_troca(sandbox):
    """O bug da v1: trocar posições congelava a cota no último snapshot e
    apagava o movimento desde então. A cota tem de subir 25% ANTES do rebase."""
    c = carteira_padrao(sandbox)
    poe_precos(sandbox, {"WEGE3": 60.0, "PETR4": 30.0, "ITUB4": 25.0, "VALE3": 70.0})
    c = carteiras.editar(c["id"], {"posicoes": [
        {"ticker": "WEGE3", "peso": 0.5}, {"ticker": "VALE3", "peso": 0.5}]})
    assert c["base"]["cota_base"] == pytest.approx(125.0)
    assert {p["ticker"] for p in c["posicoes"]} == {"WEGE3", "VALE3"}
    # e daqui em diante o movimento é da composição nova
    poe_precos(sandbox, {"WEGE3": 60.0, "VALE3": 77.0})
    c = carteiras.atualizar(c["id"])
    assert c["atual"]["cota"] == pytest.approx(125.0 * 1.05)


def test_editar_regras_sem_posicoes_nao_mexe_na_base(sandbox):
    c = carteira_padrao(sandbox)
    base_antes = json.dumps(c["base"], sort_keys=True)
    c = carteiras.editar(c["id"], {"regras": {"banda": 10, "micro": "ROIC < 15% acende luz"}})
    assert c["regras"]["banda"] == pytest.approx(0.10)
    assert c["regras"]["micro"].startswith("ROIC")
    assert json.dumps(c["base"], sort_keys=True) == base_antes


def test_atualizar_todas_isola_falhas(sandbox):
    a = carteira_padrao(sandbox)
    poe_precos(sandbox, {"VALE3": 70.0})
    b = carteiras.criar({"nome": "Só Vale",
                         "posicoes": [{"ticker": "VALE3", "peso": 1.0}]})
    # quebra só a segunda: sem preço nenhum, nem base (arquivo corrompido à mão)
    cb = carteiras.obter(b["id"])
    cb["posicoes"] = [{"ticker": "ZZZZ3", "peso": 1.0}]
    cb["base"]["precos"] = {}
    cb["atual"] = {}
    carteiras._gravar(cb)
    res = {r["id"]: r for r in carteiras.atualizar_todas()}
    assert res[a["id"]]["ok"] is True
    assert res[b["id"]]["ok"] is False and "ZZZZ3" in res[b["id"]]["erro"]


# ---------------------------------------------------------------------------
# Janelas, métricas e lâmina
# ---------------------------------------------------------------------------

def test_janelas_de_retorno_com_serie_longa():
    snaps = [
        {"data": "2025-06-30", "cota": 100.0, "retorno_bench": 0.00},
        {"data": "2025-08-29", "cota": 110.0, "retorno_bench": 0.05},
        {"data": "2025-12-31", "cota": 120.0, "retorno_bench": 0.10},
        {"data": "2026-08-31", "cota": 130.0, "retorno_bench": 0.15},
        {"data": "2026-09-15", "cota": 143.0, "retorno_bench": 0.20},
    ]
    jans = {j["nome"]: j for j in carteiras.janelas_de_retorno(snaps)}
    assert jans["No mês"]["carteira"] == pytest.approx(0.10)      # 130→143
    assert jans["No ano"]["carteira"] == pytest.approx(143 / 120 - 1, abs=1e-6)
    assert jans["12 meses"]["carteira"] == pytest.approx(0.30)    # 110→143
    assert jans["No mês"]["bench"] == pytest.approx(1.20 / 1.15 - 1, abs=1e-6)


def test_janelas_nao_finge_cobertura_em_serie_curta():
    snaps = [{"data": "2026-09-10", "cota": 100.0, "retorno_bench": 0.0},
             {"data": "2026-09-15", "cota": 101.0, "retorno_bench": 0.0}]
    jans = {j["nome"]: j for j in carteiras.janelas_de_retorno(snaps)}
    assert jans["12 meses"]["carteira"] is None
    assert jans["No ano"]["carteira"] is None


def test_metricas_drawdown_e_vol():
    snaps = [{"cota": c} for c in (100, 110, 99, 105)]
    met = carteiras.metricas_da_serie(snaps)
    assert met["drawdown_max"] == pytest.approx(99 / 110 - 1)
    assert met["vol_anualizada"] is None      # menos de 20 pontos = sem ruído


def test_lamina_traz_teses_regras_contribuicao_e_disclaimer(sandbox):
    c = carteira_padrao(sandbox)
    poe_precos(sandbox, {"WEGE3": 60.0, "PETR4": 30.0, "ITUB4": 25.0})
    poe_bench(sandbox, 110.0)
    c = carteiras.atualizar(c["id"])
    md = carteiras.lamina_md(c)
    assert "ROIC de 25%" in md                      # tese
    assert "Selic acima de 12%" in md               # regra macro
    assert "Contribuição" in md and "+25,00%" in md  # 0.5 × 50%
    assert "fora da banda" in md
    assert "embute" in md and "subestima" in md     # disclaimer honesto do ETF
    assert "não é recomendação" in md


# ---------------------------------------------------------------------------
# Remoção e segurança de path
# ---------------------------------------------------------------------------

def test_remover_e_id_torto_nao_sai_da_pasta(sandbox):
    c = carteira_padrao(sandbox)
    assert carteiras.obter("../../etc/passwd") is None
    assert carteiras.remover("nao-existe") is False
    assert carteiras.remover(c["id"]) is True
    assert carteiras.obter(c["id"]) is None
    assert carteiras.listar() == []


# ---------------------------------------------------------------------------
# Deep research arquivado
# ---------------------------------------------------------------------------

def test_deep_salva_lista_e_le(sandbox):
    r1 = deep.salvar("WEGE3", "# Análise\nROIC alto.", titulo="Deep da mesa")
    r2 = deep.salvar("wege3", "Segunda do dia.")
    assert r1["arquivo"].startswith("WEGE3-") and r1["arquivo"].endswith(".md")
    assert r2["arquivo"] != r1["arquivo"]           # sufixo -2 no mesmo dia
    nomes = [x["arquivo"] for x in deep.listar()]
    assert set(nomes) == {r1["arquivo"], r2["arquivo"]}
    corpo = deep.ler(r1["arquivo"])
    assert "ROIC alto" in corpo and "não é recomendação" in corpo


def test_deep_recusa_vazio_e_path_traversal(sandbox):
    with pytest.raises(ValueError):
        deep.salvar("WEGE3", "   ")
    with pytest.raises(ValueError):
        deep.salvar("../..", "x")
    assert deep.ler("../../../etc/passwd") is None
