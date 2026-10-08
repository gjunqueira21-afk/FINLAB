"""Testes das carteiras acompanhadas.

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

from finlab.backend import carteiras, market  # noqa: E402


# ---------------------------------------------------------------------------
# Infra: tudo em tmp_path, preços de mentira com data controlada
# ---------------------------------------------------------------------------

@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(carteiras, "DIR_CARTEIRAS", tmp_path / "carteiras")

    estado = {"precos": {}, "bench": None}

    def fake_price_series(tickers):
        return {tk: estado["precos"].get(tk, []) for tk in tickers}

    def fake_asset_series(tickers):
        out = {tk: estado["precos"].get(tk, []) for tk in tickers}
        out[carteiras.BENCHMARK] = estado["bench"] or []
        return out

    # etfs.universe() fala com a rede; nos testes o cadastro é sintético.
    monkeypatch.setattr(carteiras, "etfs", type("E", (), {
        "get": staticmethod(lambda tk: {"ticker": tk} if tk == "BOVA11" else None)})(),
        raising=False)

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

def test_lock_funciona_sem_fcntl_como_no_windows(sandbox, monkeypatch):
    chamadas = []

    class FakeMsvcrt:
        LK_LOCK, LK_UNLCK = 1, 0

        @staticmethod
        def locking(fd, modo, n):
            chamadas.append(modo)

    monkeypatch.setattr(carteiras, "_fcntl", None)
    monkeypatch.setattr(carteiras, "_msvcrt", FakeMsvcrt)
    c = carteira_padrao(sandbox)
    assert carteiras.obter(c["id"])["nome"] == "Qualidade BR"
    assert chamadas and chamadas[0] == FakeMsvcrt.LK_LOCK
    assert chamadas.count(FakeMsvcrt.LK_LOCK) == chamadas.count(FakeMsvcrt.LK_UNLCK)


# ---------------------------------------------------------------------------
# V2: target price, universo ampliado, limite de carteiras
# ---------------------------------------------------------------------------

def test_target_price_marca_atingido(sandbox):
    payload = dict(PAYLOAD, posicoes=[
        {"ticker": "WEGE3", "peso": 0.6, "alvo": 50.0},
        {"ticker": "PETR4", "peso": 0.4},          # sem alvo — não pode quebrar
    ])
    poe_precos(sandbox, {"WEGE3": 40.0, "PETR4": 30.0})
    poe_bench(sandbox, 100.0)
    c = carteiras.criar(payload)
    assert c["atual"]["alvos"]["WEGE3"]["atingido"] is False
    assert "PETR4" not in c["atual"]["alvos"]

    poe_precos(sandbox, {"WEGE3": 52.0, "PETR4": 31.0})
    c = carteiras.atualizar(c["id"])
    assert c["atual"]["alvos"]["WEGE3"]["atingido"] is True
    r = carteiras.listar()[0]
    assert r["n_alvos"] == 1


def test_alvo_invalido_e_recusado(sandbox):
    poe_precos(sandbox, {"WEGE3": 40.0})
    for ruim in ("abc", 0, -5):
        with pytest.raises(carteiras.CarteiraInvalida):
            carteiras.criar({"nome": "X", "posicoes": [
                {"ticker": "WEGE3", "peso": 1.0, "alvo": ruim}]})


def test_limite_de_dez_carteiras(sandbox):
    poe_precos(sandbox, {"WEGE3": 40.0})
    poe_bench(sandbox, 100.0)
    for i in range(10):
        carteiras.criar({"nome": f"C{i}", "posicoes": [{"ticker": "WEGE3", "peso": 1.0}]})
    with pytest.raises(carteiras.CarteiraInvalida):
        carteiras.criar({"nome": "C10", "posicoes": [{"ticker": "WEGE3", "peso": 1.0}]})


def test_bdr_e_etf_entram_na_carteira(sandbox):
    poe_precos(sandbox, {"WEGE3": 40.0, "AAPL34": 60.0, "BOVA11": 120.0})
    poe_bench(sandbox, 100.0)
    c = carteiras.criar({"nome": "Mista", "posicoes": [
        {"ticker": "WEGE3", "peso": 0.4},
        {"ticker": "AAPL34", "peso": 0.3},
        {"ticker": "BOVA11", "peso": 0.3}]})
    assert {p["ticker"] for p in c["posicoes"]} == {"WEGE3", "AAPL34", "BOVA11"}


def test_detalhe_traz_janelas_e_sparkline(sandbox):
    c = carteira_padrao(sandbox)
    det = carteiras.detalhe(carteiras.obter(c["id"]))
    assert "janelas" in det and "metricas" in det
    r = carteiras.listar()[0]
    assert isinstance(r["serie_curta"], list)


# ---------------------------------------------------------------------------
# Lâmina em PDF
# ---------------------------------------------------------------------------

@pytest.fixture()
def pdf_ok(monkeypatch):
    pytest.importorskip("weasyprint", reason="WeasyPrint (e o Pango) ausentes")
    from finlab.backend import lamina_pdf
    monkeypatch.setattr(lamina_pdf, "etfs", type("E", (), {"get": staticmethod(lambda tk: None)})())
    return lamina_pdf


def test_lamina_pdf_baixa_como_arquivo(sandbox, pdf_ok):
    from fastapi.testclient import TestClient
    from finlab.backend.app import app

    c = carteira_padrao(sandbox, nome="Comitê Jarvis Equity Mundo/Brasil")
    poe_precos(sandbox, {"WEGE3": 60.0, "PETR4": 30.0, "ITUB4": 25.0})
    poe_bench(sandbox, 110.0)
    carteiras.atualizar(c["id"])
    r = TestClient(app).get(f"/api/carteiras/{c['id']}/lamina.pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    disp = r.headers["content-disposition"]
    assert disp.startswith("attachment;") and ".pdf" in disp
    assert "Comite Jarvis Equity MundoBrasil" in disp            # nome sem acento nem barra
    assert "filename*=UTF-8''" in disp
    assert r.content.startswith(b"%PDF") and r.content.rstrip().endswith(b"%%EOF")
    assert TestClient(app).get("/api/carteiras/nao-existe/lamina.pdf").status_code == 404


def test_lamina_pdf_traz_os_numeros_da_carteira(sandbox, pdf_ok):
    c = carteira_padrao(sandbox)
    poe_precos(sandbox, {"WEGE3": 60.0, "PETR4": 30.0, "ITUB4": 25.0})
    poe_bench(sandbox, 110.0)
    c = carteiras.atualizar(c["id"])
    # mesmo dia substitui o ponto: um dia anterior para a série ter dois
    c["snapshots"].insert(0, {"data": "2020-01-02", "cota": 100.0, "retorno_bench": 0.0})
    html = pdf_ok.html(c)
    assert "ROIC de 25%" in html and "Selic acima de 12%" in html
    assert "+25,00 p.p." in html                    # contribuição 0,5 × 50%
    assert "fora da banda" in html
    assert "<polyline" in html                      # gráfico com 2 pontos
    assert "subestima" in html and "não é recomendação" in html
    assert pdf_ok.gerar(c).startswith(b"%PDF")


def test_lamina_pdf_de_carteira_recem_criada_nao_quebra(sandbox, pdf_ok):
    c = carteira_padrao(sandbox, nome="<script>alert(1)</script>", posicoes=[
        {"ticker": "WEGE3", "peso": 1.0}])
    html = pdf_ok.html(c)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "segundo ponto" in html                  # sem gráfico com 1 ponto só
    assert pdf_ok.gerar(c).startswith(b"%PDF")


def test_formatacao_pt_br_da_lamina():
    from finlab.backend import lamina_pdf as L
    assert L._pct(0.074) == "+7,4%"
    assert L._pct(-0.131) == "−13,1%"
    assert L._pct(-0.00001) == "+0,0%"              # sem "−0,0%"
    assert L._pct(0.172, sinal=False) == "17,2%"
    assert L._num(1234.5) == "1.234,50"
    assert L._pp(-0.037) == "−3,7 p.p."
    assert L._escala(99.6, 111.2) == [95, 100, 105, 110, 115]
