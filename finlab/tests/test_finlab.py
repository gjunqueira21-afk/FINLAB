"""Testes do FinLab.

Rodar: python -m pytest finlab/tests -q

Cobrem o que quebra silenciosamente: extração contábil da CVM, escalas
(units, LPA em milhares), consistência dos múltiplos, curvas do score e o
proxy de LLM nos três formatos de API. O motor de valuation em JavaScript
tem teste próprio em finlab/tests/test_engine.py (roda no navegador).
"""

from __future__ import annotations

import json
import sys
import threading
import http.server
import socketserver
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from finlab.backend import bdrs, cvm, metrics, scoring, universe  # noqa: E402
from finlab.backend import market  # noqa: E402


# ---------------------------------------------------------------------------
# Universo
# ---------------------------------------------------------------------------

def test_universo_tem_90_acoes_sem_duplicatas():
    assert len(universe.UNIVERSE) == 90
    tickers = [c.ticker for c in universe.UNIVERSE]
    assert len(set(tickers)) == 90


def test_todo_setor_declarado_tem_empresa():
    usados = {c.sector for c in universe.UNIVERSE}
    assert usados == set(universe.SECTORS)


def test_metricas_do_setor_sao_conhecidas():
    for key, meta in universe.SECTORS.items():
        assert 1 <= len(meta["metrics"]) <= 4, key
        for m in meta["metrics"]:
            assert m in universe.METRIC_LABELS, (key, m)
            assert m in universe.METRIC_FORMAT, (key, m)


def test_units_tem_razao_maior_que_um():
    for ticker, ratio in universe.UNIT_RATIO.items():
        assert universe.get(ticker) is not None, ticker
        assert ratio >= 2
        assert ticker.endswith("11"), "só units terminam em 11"


# ---------------------------------------------------------------------------
# Extração da CVM
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not cvm.available(), reason="parquets da CVM ausentes")
def test_series_anuais_da_petrobras():
    dados = cvm.annual_series("009512")
    assert dados["years"], "sem exercícios"
    assert not dados["financial"]
    serie = dados["series"]
    receita = [v for v in serie["receita"] if v is not None]
    assert receita and min(receita) > 1e11, "receita da Petrobras acima de R$ 100 bi"
    # EBITDA precisa ser coerente com EBIT + D&A no mesmo ano
    for i, ano in enumerate(dados["years"]):
        ebit, da, ebitda = serie["ebit"][i], serie["depreciacao"][i], serie["ebitda"][i]
        if None in (ebit, da, ebitda):
            continue
        assert abs(ebitda - (ebit + abs(da))) < 1.0, ano


@pytest.mark.skipif(not cvm.available(), reason="parquets da CVM ausentes")
def test_capex_sempre_negativo_e_fcl_bate_com_fco_menos_capex():
    for ticker in ("VALE3", "WEGE3", "EQTL3", "SUZB3", "MGLU3"):
        comp = universe.get(ticker)
        dados = cvm.annual_series(comp.cd_cvm)
        serie = dados["series"]
        for i in range(len(dados["years"])):
            capex, fco, fcl = serie["capex"][i], serie["fco"][i], serie["fcl"][i]
            if capex is not None:
                assert capex <= 0, (ticker, dados["years"][i])
            if None not in (capex, fco, fcl):
                assert abs(fcl - (fco - abs(capex))) < 1.0, (ticker, dados["years"][i])


@pytest.mark.skipif(not cvm.available(), reason="parquets da CVM ausentes")
def test_bancos_sao_detectados_e_nao_ganham_ebitda():
    for ticker in ("ITUB4", "BBAS3", "BBDC4"):
        comp = universe.get(ticker)
        dados = cvm.annual_series(comp.cd_cvm)
        assert dados["financial"], ticker
        assert all(v is None for v in dados["series"]["ebitda"]), ticker
        assert all(v is None for v in dados["series"]["divida_liquida"]), ticker


@pytest.mark.skipif(not cvm.available(), reason="parquets da CVM ausentes")
def test_acoes_implicitas_no_lpa_corrigem_a_escala():
    """A conta 3.99 vem inflada em 1.000× pelo pipeline; o fallback corrige."""
    # Raia Drogasil: ~1,65 bilhão de ações.
    acoes = cvm.shares_from_eps("005258")
    assert acoes is not None
    assert 1e9 < acoes < 3e9, acoes


@pytest.mark.skipif(not cvm.available(), reason="parquets da CVM ausentes")
def test_capital_social_bate_com_ordem_de_grandeza_conhecida():
    casos = {"33.000.167/0001-01": (10e9, 15e9),   # Petrobras
             "33.592.510/0001-54": (4e9, 5e9),     # Vale
             "60.872.504/0001-23": (9e9, 13e9)}    # Itaú Unibanco
    for cnpj, (lo, hi) in casos.items():
        acoes = cvm.shares_outstanding(cnpj)
        assert acoes is not None and lo < acoes < hi, (cnpj, acoes)


# ---------------------------------------------------------------------------
# Métricas e múltiplos
# ---------------------------------------------------------------------------

def test_last_valid_pega_o_ultimo_nao_nulo():
    assert metrics.last_valid([1, None, 3, None], [2020, 2021, 2022, 2023]) == (3.0, 2022)
    assert metrics.last_valid([None, None], [2020, 2021]) == (None, None)
    assert metrics.last_valid([], []) == (None, None)


def test_cagr_exige_pontas_positivas():
    anos = [2020, 2021, 2022, 2023]
    assert metrics.cagr([100, 110, 121, 133.1], anos, 3) == pytest.approx(0.1, abs=1e-4)
    assert metrics.cagr([-10, 5, 8, 12], anos, 3) is None       # base negativa
    assert metrics.cagr([100, 110], [2022, 2023], 3) is None    # série curta


def test_div_protege_denominador():
    assert metrics.div(10, 2) == 5
    assert metrics.div(10, 0) is None
    assert metrics.div(None, 2) is None


def test_positive_years():
    assert metrics.positive_years([1, 2, -1, 4, 5]) == pytest.approx(0.8)
    assert metrics.positive_years([1, 2]) is None  # amostra insuficiente


def test_unit_divide_o_valor_de_mercado():
    fund = {"base": {"lucro_liquido": 1e9, "patrimonio_liquido": 5e9, "divida_liquida": None,
                     "ebitda": None, "ebit": None, "receita": None, "fcl": None},
            "indicadores": {}, "financial": True, "cnpj": None, "cd_cvm": None}
    serie = [("2026-01-02", 30.0), ("2026-01-03", 30.0)]

    snap_unit = metrics.market_snapshot("SANB11", serie, None, fund)
    snap_normal = metrics.market_snapshot("BBDC4", serie, None, fund)
    assert snap_unit["unit_ratio"] == 2
    assert snap_normal["unit_ratio"] == 1
    if snap_unit["shares"] and snap_normal["shares"]:
        assert snap_unit["shares_quote"] == snap_unit["shares"] / 2


def _auto(fund, snap, brapi, ltm=None):
    """Os múltiplos da fonte automática, a que a tela abre por padrão."""
    return metrics.multiplos_por_fonte(fund, snap, brapi, ltm)["auto"]


def test_multiplos_sao_consistentes_com_os_insumos():
    fund = {"base": {"lucro_liquido": 200.0, "patrimonio_liquido": 1000.0,
                     "divida_liquida": 300.0, "ebitda": 400.0, "ebit": 350.0,
                     "receita": 2000.0, "fcl": 150.0},
            "indicadores": {"roe": 0.2, "mg_ebitda": 0.2, "nd_ebitda": 0.75},
            "financial": False}
    snap = {"market_cap": 2000.0, "shares_quote": 100.0, "shares": 100.0}
    mult = _auto(fund, snap, None)
    assert mult["pl"] == pytest.approx(10.0)
    assert mult["pvp"] == pytest.approx(2.0)
    assert mult["ev"] == pytest.approx(2300.0)
    assert mult["ev_ebitda"] == pytest.approx(5.75)
    assert mult["lpa"] == pytest.approx(2.0)
    assert mult["vpa"] == pytest.approx(10.0)


def test_financeira_nao_recebe_enterprise_value():
    fund = {"base": {"lucro_liquido": 100.0, "patrimonio_liquido": 500.0,
                     "divida_liquida": None, "ebitda": None, "ebit": None,
                     "receita": 900.0, "fcl": None},
            "indicadores": {}, "financial": True}
    mult = _auto(fund, {"market_cap": 1000.0, "shares_quote": 10.0}, None)
    assert mult["ev"] is None
    assert mult["ev_ebitda"] is None


def _fund_itub():
    # ITUB4, exercício 2025 na CVM: lucro 45,85 bi / PL 215,08 bi = ROE 21,3%.
    return {"base": {"lucro_liquido": 45.85e9, "patrimonio_liquido": 215.08e9,
                     "divida_liquida": None, "ebitda": None, "ebit": None,
                     "receita": 300e9, "fcl": None},
            "indicadores": {"roe": 45.85 / 215.08}, "financial": True, "last_year": 2025}


def test_multiplos_vem_da_brapi_quando_ela_tem():
    brapi = {"priceEarnings": 9.5, "dividendYield": 7.0,
             "defaultKeyStatistics": {"priceToBook": 2.2, "bookValue": 20.0,
                                      "trailingEps": 4.6},
             "financialData": {"returnOnEquity": 0.228}}
    snap = {"market_cap": 400e9, "shares_quote": 10e9, "price": 44.0}
    mult = _auto(_fund_itub(), snap, brapi)
    assert mult["pl"] == pytest.approx(9.5)
    assert mult["pvp"] == pytest.approx(2.2)
    assert mult["roe"] == pytest.approx(0.228)
    assert mult["dy"] == pytest.approx(0.07)
    # LPA/VPA na mesma janela do P/L e do P/VP da tela: preço ÷ múltiplo.
    assert mult["lpa"] == pytest.approx(44.0 / 9.5)
    assert mult["vpa"] == pytest.approx(20.0)
    assert mult["fontes"]["pl"] == mult["fontes"]["roe"] == "BRAPI"
    # Banco: nada de EV/EBITDA, nem que a BRAPI mande um.
    assert mult["ev_ebitda"] is None and mult["ev"] is None


def test_roe_da_brapi_em_pontos_percentuais_vira_fracao():
    # Mesmo número em pontos (22,8): a escala é a que bate com LPA ÷ VPA.
    brapi = {"defaultKeyStatistics": {"bookValue": 20.0, "trailingEps": 4.6},
             "financialData": {"returnOnEquity": 22.8}}
    snap = {"market_cap": 400e9, "shares_quote": 10e9, "price": 44.0}
    assert _auto(_fund_itub(), snap, brapi)["roe"] == pytest.approx(0.228)
    # Sem LPA/VPA da BRAPI, a referência é a conta da CVM.
    brapi = {"financialData": {"returnOnEquity": 22.8}}
    assert _auto(_fund_itub(), snap, brapi)["roe"] == pytest.approx(0.228)
    # ROE baixo em pontos (1,2%) não pode virar 120%: com LPA ÷ VPA da própria
    # BRAPI (mesma janela) a escala sai certa mesmo com o anual da CVM em 21%.
    brapi = {"defaultKeyStatistics": {"bookValue": 20.0, "trailingEps": 0.24},
             "financialData": {"returnOnEquity": 1.2}}
    assert _auto(_fund_itub(), snap, brapi)["roe"] == pytest.approx(0.012)
    # Sem LPA/VPA, a referência seguinte é a CVM de 12 meses (mesma janela).
    ltm = {"fim": "2026-06-30", "rotulo": "LTM 2T26",
           "campos": {"lucro_liquido": 2.6e9, "patrimonio_liquido": 215e9}}
    brapi = {"financialData": {"returnOnEquity": 1.2}}
    assert _auto(_fund_itub(), snap, brapi, ltm)["roe"] == pytest.approx(0.012)


def test_multiplos_caem_para_a_cvm_campo_a_campo():
    # BRAPI só com P/L: o resto vem do exercício da CVM, e a fonte diz isso.
    snap = {"market_cap": 430e9, "shares_quote": 10e9, "price": 43.0}
    mult = _auto(_fund_itub(), snap, {"priceEarnings": 9.0,
                                                  "financialData": {"returnOnEquity": None}})
    assert mult["fontes"]["pl"] == "BRAPI"
    assert mult["pvp"] == pytest.approx(430 / 215.08)
    assert mult["roe"] == pytest.approx(0.2132, abs=1e-4)
    assert mult["fontes"]["pvp"] == mult["fontes"]["roe"] == "CVM"
    assert mult["ano_cvm"] == 2025
    # Sem BRAPI nenhuma, tudo CVM — o comportamento de antes.
    mult = _auto(_fund_itub(), snap, None)
    assert mult["pl"] == pytest.approx(430 / 45.85)
    assert set(v for v in mult["fontes"].values() if v) == {"CVM"}


def test_multiplos_ignoram_lixo_da_brapi():
    snap = {"market_cap": 430e9, "shares_quote": 10e9, "price": 43.0}
    brapi = {"priceEarnings": "NaN", "dividendYield": "abc",
             "defaultKeyStatistics": {"priceToBook": 0},
             "financialData": {"returnOnEquity": float("inf")}}
    mult = _auto(_fund_itub(), snap, brapi)
    assert mult["pl"] == pytest.approx(430 / 45.85)
    assert mult["pvp"] == pytest.approx(430 / 215.08)
    assert mult["dy"] is None
    assert mult["fontes"]["pl"] == mult["fontes"]["pvp"] == mult["fontes"]["roe"] == "CVM"


def test_nao_financeira_usa_ev_ebitda_e_margem_da_brapi():
    fund = {"base": {"lucro_liquido": 200.0, "patrimonio_liquido": 1000.0,
                     "divida_liquida": 300.0, "ebitda": 400.0, "ebit": 350.0,
                     "receita": 2000.0, "fcl": 150.0},
            "indicadores": {"roe": 0.2, "mg_ebitda": 0.2, "nd_ebitda": 0.75},
            "financial": False, "last_year": 2025}
    snap = {"market_cap": 2000.0, "shares_quote": 100.0, "price": 20.0}
    brapi = {"financialData": {"enterpriseToEbitda": 6.1, "ebitdaMargins": 0.22,
                               "enterpriseValue": 2500.0}}
    mult = _auto(fund, snap, brapi)
    assert mult["ev_ebitda"] == pytest.approx(6.1)
    assert mult["mg_ebitda"] == pytest.approx(0.22)
    assert mult["ev"] == pytest.approx(2500.0)
    # Alavancagem continua da CVM.
    assert mult["nd_ebitda"] == pytest.approx(0.75)
    assert mult["fontes"]["nd_ebitda"] == "CVM"


def _ltm_itub():
    # 12 meses até o 2T26 pelos ITRs: lucro 50 bi sobre PL de 220 bi = 22,7%.
    return {"fim": "2026-06-30", "rotulo": "LTM 2T26",
            "campos": {"lucro_liquido": 50e9, "patrimonio_liquido": 220e9,
                       "receita": 310e9}}


def test_cada_fonte_escolhida_e_respeitada():
    snap = {"market_cap": 440e9, "shares_quote": 10e9, "price": 44.0}
    brapi = {"priceEarnings": 9.5, "financialData": {"returnOnEquity": 0.215}}
    por = metrics.multiplos_por_fonte(_fund_itub(), snap, brapi, _ltm_itub())
    assert set(por) == set(metrics.FONTES)

    ex = por["cvm_exercicio"]
    assert ex["roe"] == pytest.approx(45.85 / 215.08)
    assert ex["pl"] == pytest.approx(440 / 45.85)
    assert ex["lpa"] == pytest.approx(4.585)
    assert set(v for v in ex["fontes"].values() if v) <= {"CVM", "BRAPI"}
    assert ex["fontes"]["roe"] == "CVM"

    m12 = por["cvm_12m"]
    assert m12["roe"] == pytest.approx(50 / 220)
    assert m12["pl"] == pytest.approx(440 / 50)
    assert m12["pvp"] == pytest.approx(2.0)
    assert m12["lpa"] == pytest.approx(5.0)
    assert m12["fontes"]["roe"] == "CVM12" and m12["ltm_rotulo"] == "LTM 2T26"

    b = por["brapi"]
    assert b["pl"] == pytest.approx(9.5) and b["roe"] == pytest.approx(0.215)
    # BRAPI escolhida e sem P/VP: fica vazio, não pega o da CVM escondido.
    assert b["pvp"] is None and b["fontes"]["pvp"] is None

    # Automático: BRAPI, depois CVM 12 meses, depois exercício — campo a campo.
    a = por["auto"]
    assert a["pl"] == pytest.approx(9.5) and a["fontes"]["pl"] == "BRAPI"
    assert a["pvp"] == pytest.approx(2.0) and a["fontes"]["pvp"] == "CVM12"
    # LPA e VPA na janela do P/L e do P/VP que estão na tela.
    assert a["lpa"] == pytest.approx(44.0 / 9.5) and a["fontes"]["lpa"] == "BRAPI"
    assert a["vpa"] == pytest.approx(22.0) and a["fontes"]["vpa"] == "CVM12"


def test_sem_itr_a_fonte_cvm_12m_fica_vazia_e_o_auto_cai_para_o_exercicio():
    snap = {"market_cap": 440e9, "shares_quote": 10e9, "price": 44.0}
    por = metrics.multiplos_por_fonte(_fund_itub(), snap, None, None)
    assert all(por["cvm_12m"][k] is None for k in ("pl", "pvp", "roe", "lpa"))
    assert por["auto"]["roe"] == pytest.approx(45.85 / 215.08)
    assert por["auto"]["fontes"]["roe"] == "CVM"


def test_divida_sobre_ebitda_vem_da_cvm_mesmo_com_brapi_escolhida():
    fund = {"base": {"lucro_liquido": 200.0, "patrimonio_liquido": 1000.0,
                     "divida_liquida": 300.0, "ebitda": 400.0, "ebit": 350.0,
                     "receita": 2000.0, "fcl": 150.0},
            "indicadores": {}, "financial": False, "last_year": 2025}
    ltm = {"fim": "2026-06-30", "rotulo": "LTM 2T26",
           "campos": {"lucro_liquido": 220.0, "patrimonio_liquido": 1100.0,
                      "divida_liquida": 250.0, "ebitda": 500.0, "receita": 2200.0}}
    snap = {"market_cap": 2000.0, "shares_quote": 100.0, "price": 20.0}
    por = metrics.multiplos_por_fonte(fund, snap, {"priceEarnings": 9.0}, ltm)
    assert por["brapi"]["nd_ebitda"] == pytest.approx(0.5)
    assert por["brapi"]["fontes"]["nd_ebitda"] == "CVM12"
    assert por["cvm_exercicio"]["nd_ebitda"] == pytest.approx(0.75)
    assert por["cvm_12m"]["ev_ebitda"] == pytest.approx(2250 / 500)
    assert por["cvm_12m"]["mg_ebitda"] == pytest.approx(500 / 2200)


def test_brapi_multiplos_cai_para_papel_a_papel_quando_o_plano_recusa_lote(monkeypatch):
    import requests
    from finlab.backend import cache as cache_mod
    monkeypatch.setattr(market, "BRAPI_TOKEN", "t")
    monkeypatch.setattr(cache_mod, "get", lambda *a, **k: None)
    monkeypatch.setattr(cache_mod, "set", lambda *a, **k: None)

    class Resp:
        status_code = 403

    def recusa(*a, **k):
        raise requests.HTTPError(response=Resp())
    monkeypatch.setattr(market._SESSION, "get", recusa)
    monkeypatch.setattr(market, "brapi_fundamentals",
                        lambda tk: {"symbol": tk, "priceEarnings": 8.0})
    out = market.brapi_multiplos(["itub4", "bbdc4"])
    assert set(out) == {"ITUB4", "BBDC4"}

    # Rede fora do ar: não sai disparando uma consulta por papel.
    chamadas = []
    monkeypatch.setattr(market._SESSION, "get",
                        lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError()))
    monkeypatch.setattr(market, "brapi_fundamentals", lambda tk: chamadas.append(tk))
    assert market.brapi_multiplos(["ITUB4"]) == {}
    assert chamadas == []


# ---------------------------------------------------------------------------
# Score
# ---------------------------------------------------------------------------

def test_curva_interpola_e_satura():
    ancoras = [(0.0, 0.0), (0.10, 50.0), (0.20, 100.0)]
    assert scoring.curve(0.05, ancoras) == pytest.approx(25.0)
    assert scoring.curve(0.15, ancoras) == pytest.approx(75.0)
    assert scoring.curve(-1.0, ancoras) == 0.0      # abaixo do piso
    assert scoring.curve(9.0, ancoras) == 100.0     # acima do teto
    assert scoring.curve(None, ancoras) is None


def test_curva_de_alavancagem_premia_menos_divida():
    assert scoring.curve(0.5, scoring.ND_EBITDA) > scoring.curve(3.5, scoring.ND_EBITDA)
    assert scoring.curve(-0.5, scoring.ND_EBITDA) > 95.0     # caixa líquido
    assert scoring.curve(-2.0, scoring.ND_EBITDA) == 100.0   # caixa líquido alto satura


def test_score_fica_entre_0_e_100_e_reporta_cobertura():
    otima = {"roe": 0.30, "roic": 0.25, "mg_liquida": 0.25, "nd_ebitda": -0.5,
             "nd_equity": -0.2, "mg_ebitda": 0.45, "cagr_receita_3a": 0.25,
             "cagr_ebitda_3a": 0.25, "cash_conversion": 1.0, "fcf_margin": 0.18,
             "consistencia_lucro": 1.0}
    pessima = {k: (-0.2 if "cagr" in k or "margin" in k or k.startswith("mg") or k in
                   ("roe", "roic", "cash_conversion") else 6.0) for k in otima}
    pessima["consistencia_lucro"] = 0.0

    boa = scoring.score(otima)
    ruim = scoring.score(pessima)
    assert 90 <= boa["total"] <= 100
    assert 0 <= ruim["total"] <= 20
    assert boa["cobertura"] == pytest.approx(1.0)
    assert not boa["parcial"]


def test_score_com_dado_faltando_nao_e_punido_mas_marca_cobertura():
    parcial = scoring.score({"roe": 0.20})
    assert parcial["total"] is not None
    assert parcial["cobertura"] < 0.3
    assert parcial["parcial"] is True


def test_score_sem_indicador_algum_nao_inventa_nota():
    assert scoring.score({})["total"] is None
    assert scoring.grade(None) == "—"
    assert scoring.band(None) == "none"


def test_perfil_financeiro_usa_outros_pilares():
    pilares = {p["key"] for p in scoring.score({"roe": 0.2}, financial=True)["pilares"]}
    assert "caixa" not in pilares          # conversão de caixa não se aplica a banco
    assert "rentabilidade" in pilares


# ---------------------------------------------------------------------------
# Premissas de valuation
# ---------------------------------------------------------------------------

def _fund_teste():
    return {
        "sector": "INDUSTRIA_TECH", "financial": False,
        "base": {"divida_bruta": 1000.0, "divida_liquida": 500.0, "caixa": 500.0},
        "indicadores": {"cagr_receita_3a": 0.08},
        "series": {"fcl": [100.0, 120.0, 140.0], "ebit": [200.0, 220.0, 240.0]},
    }


def test_numero_pt_br():
    assert market._pt_number("14,15%") == pytest.approx(14.15)
    assert market._pt_number("5.1177") == pytest.approx(5.1177)
    assert market._pt_number("175.335") == pytest.approx(175335.0)
    assert market._pt_number("1.234.567") == pytest.approx(1234567.0)
    assert market._pt_number("") is None
    assert market._pt_number(None) is None


def test_performance_calcula_janelas_e_respeita_tolerancia():
    from datetime import date, timedelta
    hoje = date(2026, 7, 27)
    serie = []
    for i in range(400, -1, -1):
        d = hoje - timedelta(days=i)
        serie.append((d.isoformat(), 100.0 * (1.0005 ** (400 - i))))
    perf = market.performance(serie, hoje)
    assert perf["price"] == pytest.approx(serie[-1][1])
    for janela in ("day", "week", "m3", "m12", "ytd"):
        assert perf[janela] is not None, janela
        assert perf[janela] > 0

    # Série curta: janelas longas não podem ser inventadas.
    curta = serie[-20:]
    perf_curta = market.performance(curta, hoje)
    assert perf_curta["week"] is not None
    assert perf_curta["m3"] is None
    assert perf_curta["m12"] is None
    assert perf_curta["ytd"] is None


def test_performance_sem_serie():
    assert market.performance([])["price"] is None


def test_performance_com_buracos_e_fim_de_semana():
    """A busca por data virou bisect sobre texto ISO; precisa achar o mesmo ponto.

    O caso que importa é a data-alvo que NÃO existe na série (fim de semana,
    feriado, pregão sem negócio): a janela tem de cair no último fechamento
    anterior ao alvo, nunca no seguinte.
    """
    from datetime import date

    serie = [("2026-01-02", 100.0), ("2026-01-05", 110.0), ("2026-01-06", 120.0),
             ("2026-04-06", 130.0), ("2026-07-06", 140.0)]
    # 2026-01-03 e 04 são fim de semana: a janela de 3 meses a partir de 06/04
    # tem de usar como base o fechamento de 05/01, não o de 06/01. O numerador
    # é sempre o último fechamento da série.
    perf = market.performance(serie, date(2026, 4, 6))
    assert perf["m3"] == pytest.approx(140.0 / 110.0 - 1)
    # Alvo anterior ao primeiro ponto: sem base, sem retorno inventado.
    assert market.performance(serie[-2:], date(2026, 7, 6))["m12"] is None


def test_pulse_recorta_o_historico_sem_perder_a_janela_do_painel(monkeypatch):
    """O blob de cotações era de 16 MB e o painel só consome ~2 anos.

    O corte tem de deixar de fora o que está além de ANOS_DE_HISTORICO e
    preservar tudo o que as telas leem (500 fechamentos e a janela de 12 meses).
    """
    from datetime import date, timedelta

    hoje = date.today()
    velha = (hoje - timedelta(days=365 * (market.ANOS_DE_HISTORICO + 2))).isoformat()
    recente = (hoje - timedelta(days=30)).isoformat()
    linhas = [
        {"label": "TESTE3", "data_referencia": velha, "preco_fechamento": "10"},
        {"label": "TESTE3", "data_referencia": recente, "preco_fechamento": "20"},
    ]
    monkeypatch.setattr(market, "_pulse_csv", lambda *a, **kw: linhas)
    monkeypatch.setattr(market.cache, "memoize", lambda key, ttl, producer: producer())

    serie = market.pulse_prices()["TESTE3"]
    assert [d for d, _ in serie] == [recente]


def test_leitor_da_cvm_aceita_itr_e_degrada_sem_ele(tmp_path, monkeypatch):
    """O sufixo _dfp era fixo (achado 00.3): o pipeline gera *_itr.parquet e o
    painel não lia. Com um ITR sintético, latest_quarter devolve o trimestre
    mais recente; sem arquivo, devolve None sem quebrar nada."""
    import pandas as pd

    monkeypatch.setattr(cvm, "CVM_PROCESSED_DIR", tmp_path)
    cvm.limpar_cache()
    try:
        # sem arquivos: nada de ITR, nada de exceção
        assert cvm.latest_quarter("009512") is None

        linhas = []
        for fim, receita, lucro in (("2026-03-31", 100.0, 10.0),
                                    ("2026-06-30", 220.0, 25.0)):
            linhas += [
                {"CD_CVM": "009512", "DENOM_CIA": "PETRO", "CNPJ_CIA": "x",
                 "DT_FIM_EXERC": pd.Timestamp(fim), "DT_INI_EXERC": pd.Timestamp("2026-01-01"),
                 "ANO_REFER": 2026, "CD_CONTA": "3.01",
                 "DS_CONTA": "Receita de Venda de Bens e/ou Serviços",
                 "VL_CONTA_AJUSTADO": receita},
                {"CD_CVM": "009512", "DENOM_CIA": "PETRO", "CNPJ_CIA": "x",
                 "DT_FIM_EXERC": pd.Timestamp(fim), "DT_INI_EXERC": pd.Timestamp("2026-01-01"),
                 "ANO_REFER": 2026, "CD_CONTA": "3.11",
                 "DS_CONTA": "Lucro/Prejuízo Consolidado do Período",
                 "VL_CONTA_AJUSTADO": lucro},
            ]
        # janela avulsa (2T isolado) NÃO pode ser confundida com o acumulado
        linhas.append({"CD_CVM": "009512", "DENOM_CIA": "PETRO", "CNPJ_CIA": "x",
                       "DT_FIM_EXERC": pd.Timestamp("2026-06-30"),
                       "DT_INI_EXERC": pd.Timestamp("2026-04-01"),
                       "ANO_REFER": 2026, "CD_CONTA": "3.01",
                       "DS_CONTA": "Receita de Venda de Bens e/ou Serviços",
                       "VL_CONTA_AJUSTADO": 120.0})
        pd.DataFrame(linhas).to_parquet(tmp_path / "dre_itr.parquet", index=False)
        cvm.limpar_cache()

        q = cvm.latest_quarter("009512")
        assert q == {"fim": "2026-06-30", "receita": 220.0, "lucro": 25.0}
        # outra empresa segue sem dado, sem exceção
        assert cvm.latest_quarter("999999") is None
    finally:
        cvm.limpar_cache()


def test_downloader_revalida_quando_a_origem_muda(tmp_path, monkeypatch):
    """A CVM republica exercícios retroativamente; pular só porque o arquivo
    existe servia dado velho em silêncio (achado 00.4)."""
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "valuation_cvm"))
    dl = pytest.importorskip("src.cvm_downloader",
                             reason="dependências do pipeline (tqdm) ausentes")

    arq = tmp_path / "dfp.zip"
    arq.write_bytes(b"conteudo-antigo")

    class _Resp:
        def __init__(self, headers, status=200):
            self.headers = headers
            self.status_code = status

    # origem mais nova (Last-Modified no futuro) -> rebaixa
    monkeypatch.setattr(dl.requests, "head",
                        lambda *a, **k: _Resp({"Last-Modified": "Wed, 01 Jan 2225 00:00:00 GMT"}))
    assert dl._remote_is_newer("http://x/dfp.zip", arq) is True

    # origem antiga -> mantém o cache
    monkeypatch.setattr(dl.requests, "head",
                        lambda *a, **k: _Resp({"Last-Modified": "Wed, 01 Jan 2020 00:00:00 GMT"}))
    assert dl._remote_is_newer("http://x/dfp.zip", arq) is False

    # sem Last-Modified: decide pelo tamanho
    monkeypatch.setattr(dl.requests, "head",
                        lambda *a, **k: _Resp({"Content-Length": "999"}))
    assert dl._remote_is_newer("http://x/dfp.zip", arq) is True
    monkeypatch.setattr(dl.requests, "head",
                        lambda *a, **k: _Resp({"Content-Length": str(arq.stat().st_size)}))
    assert dl._remote_is_newer("http://x/dfp.zip", arq) is False

    # rede fora ou sem cabeçalho: fica com o local (comportamento antigo)
    def _boom(*a, **k):
        raise dl.requests.exceptions.ConnectionError("offline")
    monkeypatch.setattr(dl.requests, "head", _boom)
    assert dl._remote_is_newer("http://x/dfp.zip", arq) is False


def test_historico_corrompido_nao_derruba_o_painel(tmp_path, monkeypatch):
    """Duas instâncias do painel gravando junto corromperam o history.csv e
    TODA página de empresa passou a devolver 500. Uma linha ruim tem de ser
    pulada, não virar exceção."""
    arq = tmp_path / "history.csv"
    arq.write_text(
        "PETR4,2024-01-02,30.5\n"
        + "LIXO," + ("x" * 200000) + ",1\n"          # campo gigante
        + "VALE3,2024-01-02,nao-e-numero\n"          # preço inválido
        + "SO,DUAS,COLUNAS,DEMAIS\n"                 # colunas a mais
        + ",,\n"                                     # linha vazia
        + "VALE3,2024-01-03,61.25\n",
        encoding="utf-8")
    monkeypatch.setattr(market, "HISTORY_FILE", arq)

    hist = market._load_local_history()
    assert hist["PETR4"] == {"2024-01-02": 30.5}
    assert hist["VALE3"] == {"2024-01-03": 61.25}   # a linha ruim sumiu, a boa ficou
    assert "SO" not in hist and "" not in hist


def test_historico_e_gravado_de_forma_atomica(tmp_path, monkeypatch):
    arq = tmp_path / "history.csv"
    monkeypatch.setattr(market, "HISTORY_FILE", arq)
    market._save_local_history({"PETR4": {"2024-01-02": 30.5}})

    assert arq.read_text(encoding="utf-8").strip() == "PETR4,2024-01-02,30.500000"
    # nenhum temporário deixado para trás
    assert [p.name for p in tmp_path.iterdir()] == ["history.csv"]
    assert market._load_local_history() == {"PETR4": {"2024-01-02": 30.5}}


def test_status_das_fontes_diagnostica_o_token(monkeypatch):
    monkeypatch.setattr(market, "_probe", lambda k: {"brapi": True, "yahoo": True,
                                                     "pulseflat": False}[k])
    monkeypatch.setattr(market, "BRAPI_TOKEN", "abcd1234567890xyz")
    monkeypatch.setattr(market, "source_label", lambda: "BRAPI")

    st = market.provider_status()
    assert set(st) == {"brapi", "yahoo", "pulseflat"}
    assert st["brapi"]["configured"] and st["brapi"]["ok"] and st["brapi"]["em_uso"]
    assert st["yahoo"]["ok"] and not st["yahoo"]["precisa_token"]
    assert st["pulseflat"]["ok"] is False

    # o token é identificável mas nunca aparece inteiro
    mascara = st["brapi"]["token_mascarado"]
    assert "abcd1234567890xyz" not in mascara
    assert mascara.startswith("abcd") and "17 caracteres" in mascara

    # e o painel diz onde procurou o arquivo
    assert st["brapi"]["env_path"].endswith(".env")


def test_status_sem_token_nao_vaza_mascara(monkeypatch):
    monkeypatch.setattr(market, "_probe", lambda k: k != "brapi")
    monkeypatch.setattr(market, "BRAPI_TOKEN", "")
    monkeypatch.setattr(market, "source_label", lambda: "PulseFlat (B3/Yahoo D-1)")

    st = market.provider_status()
    assert st["brapi"]["configured"] is False
    assert st["brapi"]["token_mascarado"] == ""
    assert st["pulseflat"]["em_uso"] is True

    # token curto vira só bolinhas, sem revelar o tamanho útil
    monkeypatch.setattr(market, "BRAPI_TOKEN", "abc")
    assert market.provider_status()["brapi"]["token_mascarado"] == "•••"


def test_diagnostico_das_fontes_nao_entra_no_cache(monkeypatch):
    """O cache vive em disco e sobrevive ao restart. Se o estado do token
    fosse memoizado junto, quem acabasse de configurar o BRAPI_TOKEN veria
    'rodando sem token' pelo resto do TTL."""
    from finlab.backend import app as app_mod

    chamadas = {"n": 0}

    def status_falso():
        chamadas["n"] += 1
        return {"brapi": {"configured": chamadas["n"] > 1, "ok": True}}

    monkeypatch.setattr(app_mod.market, "provider_status", status_falso)
    monkeypatch.setattr(app_mod.market, "source_label", lambda: f"fonte-{chamadas['n']}")

    payload = {"rows": [1, 2, 3]}
    primeiro = app_mod._com_diagnostico(payload)
    segundo = app_mod._com_diagnostico(payload)

    assert primeiro["rows"] == [1, 2, 3] and segundo["rows"] == [1, 2, 3]
    # a segunda leitura enxerga o token que acabou de ser configurado
    assert primeiro["providers"]["brapi"]["configured"] is False
    assert segundo["providers"]["brapi"]["configured"] is True
    assert primeiro["source"] != segundo["source"]
    # e o payload original (o que fica no cache) segue limpo
    assert "providers" not in payload and "source" not in payload


def test_universo_bdr_sem_duplicatas_e_setores_validos():
    from finlab.backend import bdrs
    tickers = [b.ticker for b in bdrs.UNIVERSE]
    assert len(tickers) == len(set(tickers))
    for b in bdrs.UNIVERSE:
        assert b.sector in bdrs.SECTORS, b.ticker
        assert b.us_ticker, b.ticker


def test_bancos_de_bdr_marcados():
    from finlab.backend import bdrs
    assert bdrs.get("JPMC34").bank
    assert not bdrs.get("VISA34").bank      # rede de pagamento, balanço corporativo
    assert not bdrs.get("AAPL34").bank


def test_fundamentos_de_bdr_a_partir_de_modulos_mockados():
    """Payload no formato Yahoo/BRAPI vira a mesma estrutura dos fundamentos CVM."""
    from finlab.backend import bdrs

    def stmt(ano, campos):
        base = {"endDate": {"fmt": f"{ano}-09-30"}}
        base.update({k: {"raw": v} for k, v in campos.items()})
        return base

    mod = {
        "incomeStatementHistory": {"incomeStatementHistory": [
            stmt(2025, {"totalRevenue": 400e9, "grossProfit": 180e9,
                        "ebit": 120e9, "netIncome": 100e9}),
            stmt(2024, {"totalRevenue": 380e9, "grossProfit": 170e9,
                        "ebit": 114e9, "netIncome": 95e9}),
            stmt(2023, {"totalRevenue": 360e9, "grossProfit": 160e9,
                        "ebit": 108e9, "netIncome": 90e9}),
            stmt(2022, {"totalRevenue": 340e9, "grossProfit": 150e9,
                        "ebit": 102e9, "netIncome": 85e9}),
        ]},
        "balanceSheetHistory": {"balanceSheetStatements": [
            stmt(2025, {"totalStockholderEquity": 70e9, "totalAssets": 350e9,
                        "cash": 30e9, "shortTermInvestments": 30e9,
                        "shortLongTermDebt": 10e9, "longTermDebt": 90e9}),
            stmt(2024, {"totalStockholderEquity": 65e9, "totalAssets": 340e9,
                        "cash": 28e9, "shortTermInvestments": 30e9,
                        "shortLongTermDebt": 11e9, "longTermDebt": 95e9}),
        ]},
        "cashflowStatementHistory": {"cashflowStatements": [
            stmt(2025, {"totalCashFromOperatingActivities": 110e9,
                        "capitalExpenditures": -12e9, "depreciation": 11e9}),
            stmt(2024, {"totalCashFromOperatingActivities": 105e9,
                        "capitalExpenditures": -11e9, "depreciation": 10e9}),
        ]},
        "financialData": {"financialCurrency": "USD"},
    }

    bdr = bdrs.get("AAPL34")
    fund = bdrs.fundamentals_from_modules(bdr, mod)

    assert fund["currency"] == "USD"
    assert fund["years"] == [2022, 2023, 2024, 2025]
    assert fund["last_year"] == 2025
    base = fund["base"]
    assert base["receita"] == pytest.approx(400e9)
    assert base["ebitda"] == pytest.approx(120e9 + 11e9)
    assert base["divida_bruta"] == pytest.approx(100e9)
    assert base["divida_liquida"] == pytest.approx(100e9 - 60e9)
    assert base["fcl"] == pytest.approx(110e9 - 12e9)
    ind = fund["indicadores"]
    assert ind["roe"] == pytest.approx(100e9 / 70e9)
    assert ind["cagr_receita_3a"] == pytest.approx((400 / 340) ** (1 / 3) - 1, rel=1e-6)
    # dá para pontuar com esses indicadores
    sc = scoring.score(ind, fund["financial"])
    assert sc["total"] is not None and 0 <= sc["total"] <= 100


def test_universo_etf_completo_e_categorizado(monkeypatch):
    from finlab.backend import b3data, etfs as met

    monkeypatch.setattr(b3data, "etf_listing", lambda: [
        {"ticker": "BOVA11", "nome": "ISHARES IBOVESPA FUNDO DE ÍNDICE",
         "categoria_b3": "ETF Renda Variável"},
        {"ticker": "XPTO11", "nome": "GESTORA MSCI GLOBAL FUNDO DE ÍNDICE",
         "categoria_b3": "ETF Renda Variável"},
        {"ticker": "BOL5", "nome": "PRODUTO ESTRANHO", "categoria_b3": ""},
    ])
    monkeypatch.setattr(b3data, "registry_for", lambda nome: {"pl": 1e9, "pl_data": "2026-07-01",
                                                              "situacao": "Em Funcionamento Normal",
                                                              "gestor": None, "administrador": None,
                                                              "inicio": None})
    uni = met.universe()
    tickers = {e["ticker"] for e in uni}
    assert "BOVA11" in tickers
    assert "XPTO11" in tickers
    assert "BOL5" not in tickers            # código fora do padrão XXXX11 sai
    assert "HASH11" in tickers              # cripto entra pela lista extra

    bova = next(e for e in uni if e["ticker"] == "BOVA11")
    assert bova["categoria"] == "INDICES_BR"
    assert bova["curado"] and bova["taxa_adm"] == 0.10
    xpto = next(e for e in uni if e["ticker"] == "XPTO11")
    assert xpto["categoria"] == "INTERNACIONAL"   # heurística de nome
    assert not xpto["curado"]
    hash11 = next(e for e in uni if e["ticker"] == "HASH11")
    assert hash11["categoria"] == "CRIPTO"


def test_faixas_de_liquidez():
    from finlab.backend import etfs as met
    assert met.liquidity_band(None) == "sem negócios"
    assert met.liquidity_band(200e6) == "muito alta"
    assert met.liquidity_band(20e6) == "alta"
    assert met.liquidity_band(2e6) == "média"
    assert met.liquidity_band(200e3) == "baixa"
    assert met.liquidity_band(5e3) == "muito baixa"


def test_toda_meta_curada_de_etf_aponta_categoria_valida():
    from finlab.backend import etfs as met
    for ticker, meta in met.ETF_META.items():
        assert meta["cat"] in met.CATEGORIES, ticker
        assert meta["tese"], ticker
        if meta["taxa_adm"] is not None:
            assert 0 < meta["taxa_adm"] < 3, ticker


# ---------------------------------------------------------------------------
# Fundamentos de BDR via Yahoo Finance
# ---------------------------------------------------------------------------

def _yahoo_raw_exemplo():
    def anos(vals):
        return {2022 + i: v for i, v in enumerate(vals)}
    return {
        "income": {
            "receita": anos([340e9, 360e9, 380e9, 400e9]),
            "lucro_bruto": anos([150e9, 160e9, 170e9, 180e9]),
            "ebit": anos([102e9, 108e9, 114e9, 120e9]),
            "ebitda": anos([113e9, 119e9, 125e9, 131e9]),
            "lucro_liquido": anos([85e9, 90e9, 95e9, 100e9]),
        },
        "balance": {
            "patrimonio_liquido": anos([60e9, 62e9, 65e9, 70e9]),
            "ativo_total": anos([330e9, 335e9, 340e9, 350e9]),
            "caixa_total": anos([55e9, 58e9, 58e9, 60e9]),
            "divida_bruta": anos([105e9, 104e9, 106e9, 100e9]),
        },
        "cashflow": {
            "fco": anos([95e9, 100e9, 105e9, 110e9]),
            "capex": anos([-10e9, -10e9, -11e9, -12e9]),
            "depreciacao": anos([10e9, 10e9, 10e9, 11e9]),
        },
        "info": {"marketCap": 3.0e12, "beta": 1.2, "dividendYield": 0.44,
                 "currentPrice": 210.0, "targetMeanPrice": 250.0,
                 "targetHighPrice": 300.0, "targetLowPrice": 180.0,
                 "numberOfAnalystOpinions": 40, "recommendationKey": "buy",
                 "financialCurrency": "USD"},
    }


def test_fundamentos_de_bdr_via_yahoo():
    from finlab.backend import bdrs
    fund = bdrs.fundamentals_from_yahoo(bdrs.get("AAPL34"), _yahoo_raw_exemplo())
    assert fund["fonte"] == "Yahoo Finance"
    assert fund["years"] == [2022, 2023, 2024, 2025]
    base = fund["base"]
    assert base["receita"] == pytest.approx(400e9)
    assert base["ebitda"] == pytest.approx(131e9)          # linha EBITDA direto
    assert base["divida_liquida"] == pytest.approx(40e9)   # 100 − 60 (caixa consolidado)
    assert base["fcl"] == pytest.approx(98e9)
    sc = scoring.score(fund["indicadores"], fund["financial"])
    assert sc["total"] is not None


def test_yahoo_ebitda_derivado_quando_linha_falta():
    from finlab.backend import bdrs
    raw = _yahoo_raw_exemplo()
    del raw["income"]["ebitda"]
    fund = bdrs.fundamentals_from_yahoo(bdrs.get("AAPL34"), raw)
    # EBIT 120 + D&A 11
    assert fund["base"]["ebitda"] == pytest.approx(131e9)


def test_yahoo_banco_nao_ganha_ebitda_nem_divida_liquida():
    from finlab.backend import bdrs
    fund = bdrs.fundamentals_from_yahoo(bdrs.get("JPMC34"), _yahoo_raw_exemplo())
    assert fund["financial"] is True
    assert all(v is None for v in fund["series"]["ebitda"])
    assert fund["indicadores"]["nd_ebitda"] is None


def test_yahoo_dy_heuristica_de_escala():
    from finlab.backend import bdrs
    assert bdrs.yahoo_dividend_yield({"dividendYield": 0.0044}) == pytest.approx(0.0044)
    assert bdrs.yahoo_dividend_yield({"dividendYield": 0.44}) == pytest.approx(0.0044)
    assert bdrs.yahoo_dividend_yield({"dividendYield": None}) is None
    assert bdrs.yahoo_dividend_yield({}) is None


def test_orquestrador_prefere_yahoo_e_cai_para_brapi(monkeypatch):
    from finlab.backend import bdrs
    monkeypatch.setattr(bdrs, "yahoo_raw", lambda b: _yahoo_raw_exemplo())
    bundle = bdrs.fetch_fundamentals("AAPL34")
    assert bundle["fonte"] == "Yahoo Finance"
    assert bundle["info"]["marketCap"] == pytest.approx(3.0e12)

    monkeypatch.setattr(bdrs, "yahoo_raw", lambda b: None)
    monkeypatch.setattr(bdrs, "raw_modules", lambda t: None)
    bundle = bdrs.fetch_fundamentals("AAPL34")
    assert bundle["fonte"] is None
    assert bundle["fund"]["years"] == []


def test_consenso_de_bdr_convertido_para_reais_por_bdr():
    from finlab.backend.app import _consenso_bdr
    cons = _consenso_bdr(_yahoo_raw_exemplo()["info"], 87.15)
    # alvo médio 250 sobre preço atual 210 → mesmo upside aplicado ao BDR
    assert cons["alvo_medio"] == pytest.approx(round(250 / 210 * 87.15, 2))
    assert cons["alvo_alto"] == pytest.approx(round(300 / 210 * 87.15, 2))
    assert cons["analistas"] == 40
    assert "Yahoo" in cons["fonte"]
    assert _consenso_bdr({}, 87.15) == {}
    assert _consenso_bdr(_yahoo_raw_exemplo()["info"], None) == {}


def test_df_to_plain_converte_dataframe_do_yfinance():
    import pandas as pd
    from finlab.backend import bdrs
    df = pd.DataFrame(
        {pd.Timestamp("2025-09-30"): [400e9, 100e9],
         pd.Timestamp("2024-09-30"): [380e9, float("nan")]},
        index=["Total Revenue", "Net Income"],
    )
    out = bdrs._df_to_plain(df, bdrs._Y_INCOME)
    assert out["receita"] == {2025: 400e9, 2024: 380e9}
    assert out["lucro_liquido"] == {2025: 100e9}   # NaN descartado
    assert bdrs._df_to_plain(None, bdrs._Y_INCOME) == {}


# ---------------------------------------------------------------------------
# Contexto dos agentes por tipo de ativo
# ---------------------------------------------------------------------------

def _payload_min(**over):
    fund = {"name": "X", "ticker": "XPTO3", "sector": "VAREJO", "financial": False,
            "last_year": 2025, "base": {"receita": 400e9}, "indicadores": {},
            "series": {}, "years": []}
    fund.update(over)
    return {"fundamentals": fund, "market": {"perf": {}}, "multiples": {}, "score": {}}


# ---------------------------------------------------------------------------
# Série trimestral (ITR)
# ---------------------------------------------------------------------------

RE_DS = "Receita de Venda de Bens e/ou Serviços"
LU_DS = "Lucro/Prejuízo Consolidado do Período"


def _linha_itr(fim, ini, conta, ds, valor, ordem="ÚLTIMO"):
    import pandas as pd

    return {"CD_CVM": "009512", "DENOM_CIA": "X", "CNPJ_CIA": "x",
            "DT_FIM_EXERC": pd.Timestamp(fim), "DT_INI_EXERC": pd.Timestamp(ini),
            "ORDEM_EXERC": ordem, "ANO_REFER": pd.Timestamp(fim).year,
            "CD_CONTA": conta, "DS_CONTA": ds, "VL_CONTA_AJUSTADO": valor}


def _monta_itr(tmp_path, linhas, anual=None):
    """Grava um ITR (e opcionalmente a DFP) sintéticos e devolve os pontos."""
    import pandas as pd

    pd.DataFrame(linhas).to_parquet(tmp_path / "dre_itr.parquet", index=False)
    if anual:
        pd.DataFrame([
            {"CD_CVM": "009512", "DENOM_CIA": "X", "CNPJ_CIA": "x",
             "DT_FIM_EXERC": pd.Timestamp(f"{ano}-12-31"), "ANO_REFER": ano,
             "CD_CONTA": conta, "DS_CONTA": ds, "VL_CONTA_AJUSTADO": v}
            for ano, conta, ds, v in anual
        ]).to_parquet(tmp_path / "dre_dfp.parquet", index=False)
    cvm.limpar_cache()
    return _trimestres_da_dre("009512")


def _trimestres_da_dre(cd):
    """{rótulo: {"receita", "lucro_liquido", "derivado"}} das colunas de
    trimestre da DRE completa — a mesma que a página mostra."""
    dre = cvm.dre_completa(cd)
    linhas = {l["chave"]: l["valores"] for l in dre.get("linhas", [])}
    return {c["rotulo"]: {"receita": linhas.get("receita", [None] * (i + 1))[i],
                          "lucro_liquido": linhas.get("lucro_liquido", [None] * (i + 1))[i],
                          "derivado": c.get("derivado")}
            for i, c in enumerate(dre.get("colunas", [])) if c["tipo"] == "tri"}


def test_serie_trimestral_desacumula_o_itr(tmp_path, monkeypatch):
    """A DRE do ITR vem acumulada no exercício. Plotar o acumulado como se
    fosse trimestre isolado desenha uma receita que só sobe — errado com cara
    de certo. Aqui: acumulado 100/220/360 vira 100/120/140."""
    monkeypatch.setattr(cvm, "CVM_PROCESSED_DIR", tmp_path)
    cvm.limpar_cache()
    try:
        linhas = []
        for fim, acc in (("2025-03-31", 100.0), ("2025-06-30", 220.0), ("2025-09-30", 360.0)):
            linhas += [_linha_itr(fim, "2025-01-01", "3.01", RE_DS, acc),
                       _linha_itr(fim, "2025-01-01", "3.11", LU_DS, acc / 10)]
        pontos = _monta_itr(tmp_path, linhas,
                            anual=[(2025, "3.01", RE_DS, 500.0), (2025, "3.11", LU_DS, 50.0)])

        assert pontos["1T25"]["receita"] == 100.0
        assert pontos["2T25"]["receita"] == 120.0
        assert pontos["3T25"]["receita"] == 140.0
        # o 4T não existe no ITR: sai do exercício fechado menos o acumulado
        assert pontos["4T25"]["receita"] == 140.0
        assert pontos["4T25"]["derivado"] is True
        assert pontos["1T25"]["derivado"] is False
        # validação forte: os 12 meses que fecham o exercício batem com o anual
        ltm = cvm.ltm_series("009512")
        assert ltm["trimestre"] == "4T25"
        assert ltm["campos"]["receita"] == 500.0
        assert ltm["campos"]["lucro_liquido"] == 50.0
    finally:
        cvm.limpar_cache()


def test_serie_trimestral_descarta_janela_avulsa_e_comparativo(tmp_path, monkeypatch):
    """O CSV do ITR traz, para a mesma data-fim, o acumulado e o trimestre
    avulso; e repete períodos antigos como exercício comparativo. Confundir
    qualquer um dos dois com o acumulado corrompe a diferença."""
    monkeypatch.setattr(cvm, "CVM_PROCESSED_DIR", tmp_path)
    cvm.limpar_cache()
    try:
        linhas = [
            _linha_itr("2025-03-31", "2025-01-01", "3.01", RE_DS, 100.0),
            _linha_itr("2025-06-30", "2025-01-01", "3.01", RE_DS, 220.0),
            # janela avulsa do 2T (abril–junho): valor diferente do acumulado
            _linha_itr("2025-06-30", "2025-04-01", "3.01", RE_DS, 777.0),
            # comparativo do ano anterior, possivelmente reapresentado
            _linha_itr("2024-03-31", "2024-01-01", "3.01", RE_DS, 999.0, ordem="PENÚLTIMO"),
        ]
        pontos = _monta_itr(tmp_path, linhas)

        assert pontos["2T25"]["receita"] == 120.0     # 220 − 100, não 777
        assert "1T24" not in pontos                   # o comparativo não vira ponto
    finally:
        cvm.limpar_cache()


def test_quarto_trimestre_so_sai_quando_o_terceiro_fechou(tmp_path, monkeypatch):
    """Se a empresa só publicou o 1T, anual − acumulado seriam nove meses
    empilhados num "4T". Melhor não desenhar do que desenhar errado."""
    monkeypatch.setattr(cvm, "CVM_PROCESSED_DIR", tmp_path)
    cvm.limpar_cache()
    try:
        pontos = _monta_itr(
            tmp_path,
            [_linha_itr("2025-03-31", "2025-01-01", "3.01", RE_DS, 100.0)],
            anual=[(2025, "3.01", RE_DS, 500.0)])

        assert list(pontos) == ["1T25"]
        assert pontos["1T25"]["receita"] == 100.0
    finally:
        cvm.limpar_cache()


def test_ltm_nao_soma_trimestres_com_buraco(tmp_path, monkeypatch):
    """Quatro pontos na série não são necessariamente quatro trimestres
    seguidos. Com um ano faltando, o LTM tem de ficar vazio em vez de somar
    períodos distantes e chamar isso de "últimos 12 meses"."""
    monkeypatch.setattr(cvm, "CVM_PROCESSED_DIR", tmp_path)
    cvm.limpar_cache()
    try:
        linhas = []
        for ano, acc in ((2022, (100.0, 220.0)), (2025, (130.0, 260.0))):
            for k, (fim_m, v) in enumerate(zip(("03-31", "06-30"), acc)):
                linhas.append(_linha_itr(f"{ano}-{fim_m}", f"{ano}-01-01", "3.01", RE_DS, v))
        pontos = _monta_itr(tmp_path, linhas)

        assert len(pontos) == 4
        assert cvm.ltm_series("009512") == {}
    finally:
        cvm.limpar_cache()


def test_painel_segue_anual_sem_itr(tmp_path, monkeypatch):
    """Sem os parquets do ITR o painel não pode quebrar — só não mostra o
    trimestral."""
    monkeypatch.setattr(cvm, "CVM_PROCESSED_DIR", tmp_path)
    cvm.limpar_cache()
    try:
        assert _trimestres_da_dre("009512") == {}
        assert cvm.ltm_series("009512") == {}
        assert cvm.ltm_series("") == {}
    finally:
        cvm.limpar_cache()


# ---------------------------------------------------------------------------
# Classificação de regime
# ---------------------------------------------------------------------------

def _fund(anos, **series):
    """Fundamentals mínimo no formato de cvm.annual_series."""
    return {"years": list(anos), "series": {k: list(v) for k, v in series.items()}}


def _fcf(ultimo, media3):
    return {"ultimo": ultimo, "media3": media3, "historico": []}


def test_ltm_soma_fluxo_e_nao_soma_saldo(tmp_path, monkeypatch):
    """As duas naturezas de conta: fluxo soma 12 meses, saldo é o do balanço
    mais recente. Somar quatro trimestres de patrimônio líquido seria absurdo,
    e é o tipo de erro que passa despercebido numa tabela bonita."""
    import pandas as pd

    monkeypatch.setattr(cvm, "CVM_PROCESSED_DIR", tmp_path)
    cvm.limpar_cache()
    try:
        # DRE trimestral acumulada: 4 trimestres isolados de 100 cada
        dre = []
        for ano, accs in ((2024, (100.0, 200.0, 300.0)), (2025, (100.0, 200.0, 300.0))):
            for fim, acc in zip((f"{ano}-03-31", f"{ano}-06-30", f"{ano}-09-30"), accs):
                dre.append(_linha_itr(fim, f"{ano}-01-01", "3.01", RE_DS, acc))
        pd.DataFrame(dre).to_parquet(tmp_path / "dre_itr.parquet", index=False)
        # anual fecha 2024 em 400 -> 4T24 isolado = 100
        pd.DataFrame([{
            "CD_CVM": "009512", "DENOM_CIA": "X", "CNPJ_CIA": "x",
            "DT_FIM_EXERC": pd.Timestamp("2024-12-31"), "ANO_REFER": 2024,
            "CD_CONTA": "3.01", "DS_CONTA": RE_DS, "VL_CONTA_AJUSTADO": 400.0,
        }]).to_parquet(tmp_path / "dre_dfp.parquet", index=False)
        # balanço: saldo cresce a cada trimestre; o LTM tem de pegar o último
        bpp = [{"CD_CVM": "009512", "DENOM_CIA": "X", "CNPJ_CIA": "x",
                "DT_INI_EXERC": pd.Timestamp("2025-01-01"),
                "DT_FIM_EXERC": pd.Timestamp(f), "ORDEM_EXERC": "ÚLTIMO",
                "ANO_REFER": 2025, "CD_CONTA": "2.03",
                "DS_CONTA": "Patrimônio Líquido Consolidado", "VL_CONTA_AJUSTADO": v}
               for f, v in (("2025-03-31", 900.0), ("2025-06-30", 950.0))]
        pd.DataFrame(bpp).to_parquet(tmp_path / "bpp_itr.parquet", index=False)
        cvm.limpar_cache()

        l = cvm.ltm_series("009512")
        assert l["fim"] == "2025-09-30"
        # fluxo: 4T24 (100) + 1T25 + 2T25 + 3T25 (100 cada) = 400
        assert l["campos"]["receita"] == 400.0
        # saldo: o do balanço mais recente, jamais a soma dos trimestres
        assert l["campos"]["patrimonio_liquido"] == 950.0
        assert "patrimonio_liquido" in l["saldos"]
    finally:
        cvm.limpar_cache()


def test_ltm_vazio_sem_itr(tmp_path, monkeypatch):
    """Sem ITR a coluna do ano em curso não aparece — e a tabela anual segue."""
    monkeypatch.setattr(cvm, "CVM_PROCESSED_DIR", tmp_path)
    cvm.limpar_cache()
    try:
        assert cvm.ltm_series("009512") == {}
        assert cvm.ltm_series("") == {}
    finally:
        cvm.limpar_cache()


# ---------------------------------------------------------------------------
# Radar de Contexto (busca ao vivo) e camada de momento
# ---------------------------------------------------------------------------

def _pdf_minimo(texto: str) -> bytes:
    """Um PDF de verdade, com uma página e o texto pedido, sem dependência.

    Os offsets do xref são calculados, não chutados — pypdf valida a
    estrutura, e é justamente a extração real que o teste quer exercitar.
    """
    conteudo = f"BT /F1 11 Tf 40 700 Td ({texto}) Tj ET".encode("latin-1", "replace")
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
         b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"),
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(conteudo), conteudo),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    saida = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, corpo in enumerate(objetos, start=1):
        offsets.append(len(saida))
        saida += b"%d 0 obj\n%s\nendobj\n" % (i, corpo)
    inicio_xref = len(saida)
    saida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1)
    for off in offsets:
        saida += b"%010d 00000 n \n" % off
    saida += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF"
              % (len(objetos) + 1, inicio_xref))
    return bytes(saida)


def _importar_ipe_docs():
    raiz = Path(__file__).resolve().parents[2] / "valuation_cvm"
    sys.path.insert(0, str(raiz))
    try:
        from src import ipe_docs  # noqa: E402
        return ipe_docs
    finally:
        sys.path.pop(0)


def test_selecao_respeita_categoria_universo_janela_e_teto():
    import pandas as pd
    ipe_docs = _importar_ipe_docs()

    hoje = pd.Timestamp.today()
    linhas = []
    for i in range(10):
        linhas.append({"Codigo_CVM": "9512", "Categoria": "Fato Relevante",
                       "Data_Entrega": hoje - pd.Timedelta(days=i * 30),
                       "Protocolo_Entrega": f"A{i}", "Link_Download": "https://x/a.pdf"})
    linhas.append({"Codigo_CVM": "9512", "Categoria": "Assembleia",
                   "Data_Entrega": hoje, "Protocolo_Entrega": "IRRELEV",
                   "Link_Download": "https://x/b.pdf"})
    linhas.append({"Codigo_CVM": "777777", "Categoria": "Fato Relevante",
                   "Data_Entrega": hoje, "Protocolo_Entrega": "FORA",
                   "Link_Download": "https://x/c.pdf"})
    linhas.append({"Codigo_CVM": "9512", "Categoria": "Fato Relevante",
                   "Data_Entrega": hoje - pd.Timedelta(days=900),
                   "Protocolo_Entrega": "VELHO", "Link_Download": "https://x/d.pdf"})

    sel = ipe_docs._selecionar(pd.DataFrame(linhas), meses=24, por_empresa=4,
                               universo={"9512"})
    protocolos = list(sel["Protocolo_Entrega"])
    assert len(protocolos) == 4                      # teto por empresa
    assert "IRRELEV" not in protocolos               # categoria fora da lista
    assert "FORA" not in protocolos                  # empresa fora do universo
    assert "VELHO" not in protocolos                 # fora da janela
    assert protocolos == sorted(protocolos, key=lambda p: int(p[1:]))  # mais novos


def test_corte_em_paragrafos_com_rabicho_juntado():
    ipe_docs = _importar_ipe_docs()
    paragrafo = "x" * 500
    texto = "\n\n".join([paragrafo, paragrafo, paragrafo, "fim curto"])
    trechos = ipe_docs._cortar(texto)
    assert all(len(t) <= ipe_docs.CHUNK_ALVO + 600 for t in trechos)
    # o rabicho curto não vira trecho próprio
    assert trechos[-1].endswith("fim curto") and len(trechos[-1]) > len("fim curto")
    assert ipe_docs._cortar("") == []


def test_dre_anual_monta_as_linhas_com_margens_e_cagr(tmp_path, monkeypatch):
    """A DRE de leitura: ordem contábil, margens derivadas da receita, CAGR só
    onde ele significa alguma coisa, e EBITDA = EBIT + |D&A| (a CVM não
    publica EBITDA como conta)."""
    import pandas as pd

    monkeypatch.setattr(cvm, "CVM_PROCESSED_DIR", tmp_path)
    cvm.limpar_cache()
    try:
        linhas = []
        for ano, receita, cpv, bruto, desp, ebit, resfin, ir, lucro in [
            (2024, 1000.0, -600.0, 400.0, -150.0, 250.0, -20.0, -60.0, 170.0),
            (2025, 1200.0, -700.0, 500.0, -180.0, 320.0, -25.0, -80.0, 215.0),
        ]:
            for conta, ds, v in [("3.01", "Receita de Venda de Bens", receita),
                                 ("3.02", "Custo dos Bens Vendidos", cpv),
                                 ("3.03", "Resultado Bruto", bruto),
                                 ("3.04", "Despesas/Receitas Operacionais", desp),
                                 ("3.05", "Resultado Antes do Resultado Financeiro", ebit),
                                 ("3.06", "Resultado Financeiro", resfin),
                                 ("3.08", "Imposto de Renda e Contribuição Social", ir),
                                 ("3.11", "Lucro/Prejuizo Consolidado do Periodo", lucro)]:
                linhas.append({"CD_CVM": "009512", "DENOM_CIA": "T", "CNPJ_CIA": "1",
                               "ANO_REFER": ano, "ORDEM_EXERC": "ÚLTIMO",
                               "DT_FIM_EXERC": f"{ano}-12-31",
                               "CD_CONTA": conta, "DS_CONTA": ds, "VL_CONTA_AJUSTADO": v})
        pd.DataFrame(linhas).to_parquet(tmp_path / "dre_dfp.parquet", index=False)
        # D&A vive na DFC, como ajuste do FCO
        pd.DataFrame([
            {"CD_CVM": "009512", "DENOM_CIA": "T", "CNPJ_CIA": "1", "ANO_REFER": ano,
             "ORDEM_EXERC": "ÚLTIMO", "DT_FIM_EXERC": f"{ano}-12-31",
             "CD_CONTA": "6.01.01.02", "DS_CONTA": "Depreciacao e Amortizacao",
             "VL_CONTA_AJUSTADO": v}
            for ano, v in [(2024, 50.0), (2025, 60.0)]
        ]).to_parquet(tmp_path / "dfc_mi_dfp.parquet", index=False)
        cvm.limpar_cache()

        d = cvm.dre_completa("009512")
        assert [c["rotulo"] for c in d["colunas"]] == ["2024", "2025"]
        assert d["financial"] is False
        por = {l["chave"]: l for l in d["linhas"]}

        # ordem contábil preservada
        assert [l["chave"] for l in d["linhas"]][:4] == [
            "receita", "cpv", "lucro_bruto", "mg_bruta"]
        assert por["receita"]["valores"] == [1000.0, 1200.0]
        assert por["cpv"]["tipo"] == "deducao"
        assert por["lucro_liquido"]["tipo"] == "hero"

        # EBITDA derivado: EBIT + |D&A|
        assert por["ebitda"]["valores"] == [300.0, 380.0]
        assert por["da"]["valores"] == [-50.0, -60.0], "D&A entra negativa"

        # margens sobre a receita, na linha própria
        assert por["mg_bruta"]["valores"] == [pytest.approx(0.4), pytest.approx(0.4167, abs=1e-3)]
        assert por["mg_ebitda"]["valores"][1] == pytest.approx(380.0 / 1200.0)
        assert por["mg_liquida"]["tipo"] == "margem"

        # CAGR só nas linhas de resultado; margem e dedução não têm
        assert por["receita"]["cagr"] == pytest.approx(0.2)
        assert por["mg_bruta"]["cagr"] is None
        assert por["cpv"]["cagr"] is None
    finally:
        cvm.limpar_cache()


def test_dre_anual_de_financeira_cai_no_plano_reduzido(tmp_path, monkeypatch):
    """Banco não tem CPV nem EBITDA: mostrar as linhas vazias sugeriria que o
    dado faltou. E linha só de zeros (o IR da consolidada) não entra."""
    import pandas as pd

    monkeypatch.setattr(cvm, "CVM_PROCESSED_DIR", tmp_path)
    cvm.limpar_cache()
    try:
        pd.DataFrame([
            {"CD_CVM": "009512", "DENOM_CIA": "B", "CNPJ_CIA": "1", "ANO_REFER": 2025,
             "ORDEM_EXERC": "ÚLTIMO", "DT_FIM_EXERC": "2025-12-31",
             "CD_CONTA": c, "DS_CONTA": ds, "VL_CONTA_AJUSTADO": v}
            for c, ds, v in [
                ("3.01", "Receitas da Intermediação Financeira", 500.0),
                ("3.06", "Resultado Financeiro", -10.0),
                ("3.08", "Imposto de Renda e Contribuição Social", 0.0),
                ("3.11", "Lucro/Prejuizo Consolidado do Periodo", 90.0)]
        ]).to_parquet(tmp_path / "dre_dfp.parquet", index=False)
        cvm.limpar_cache()

        d = cvm.dre_completa("009512")
        chaves = [l["chave"] for l in d["linhas"]]
        assert d["financial"] is True
        assert "cpv" not in chaves and "ebitda" not in chaves and "da" not in chaves
        assert "receita" in chaves and "lucro_liquido" in chaves and "mg_liquida" in chaves
        assert "ir" not in chaves, "linha só de zeros não é informação"
    finally:
        cvm.limpar_cache()


def test_dre_trimestral_desacumula_e_soma_o_acumulado(tmp_path, monkeypatch):
    """Dois invariantes: o ITR vem acumulado e sai isolado; e a coluna do
    semestre é a soma dos trimestres. Sem 3T e 4T de 2024 não há 12 meses
    seguidos: a coluna de 12 meses não aparece."""
    import pandas as pd

    monkeypatch.setattr(cvm, "CVM_PROCESSED_DIR", tmp_path)
    cvm.limpar_cache()
    try:
        def linha(ano, mes_fim, acumulado, valor, conta="3.01",
                  ds="Receita de Venda de Bens"):
            return {"CD_CVM": "009512", "DENOM_CIA": "T", "CNPJ_CIA": "1",
                    "ANO_REFER": ano, "ORDEM_EXERC": "ÚLTIMO",
                    "DT_INI_EXERC": f"{ano}-01-01",
                    "DT_FIM_EXERC": f"{ano}-{mes_fim}", "CD_CONTA": conta,
                    "DS_CONTA": ds, "VL_CONTA_AJUSTADO": acumulado if acumulado else valor}

        itr = []
        for ano, (a1, a2) in [(2024, (100.0, 220.0)), (2025, (120.0, 260.0))]:
            for conta, ds, fator in [("3.01", "Receita de Venda de Bens", 1.0),
                                     ("3.11", "Lucro/Prejuizo Consolidado do Periodo", 0.2)]:
                itr.append(linha(ano, "03-31", a1 * fator, None, conta, ds))
                itr.append(linha(ano, "06-30", a2 * fator, None, conta, ds))
        pd.DataFrame(itr).to_parquet(tmp_path / "dre_itr.parquet", index=False)
        cvm.limpar_cache()

        d = cvm.dre_completa("009512")
        assert [c["rotulo"] for c in d["colunas"]] == [
            "1T24", "2T24", "1S24", "1T25", "2T25", "1S25"]
        assert d["colunas"][-1]["tipo"] == "ytd"

        receita = next(l for l in d["linhas"] if l["chave"] == "receita")
        # acumulado 120 e 260 → trimestres isolados 120 e 140
        assert receita["valores"][3:] == [120.0, 140.0, 260.0]
        assert receita["valores"][5] == receita["valores"][3] + receita["valores"][4]
        assert receita["valores"][:3] == [100.0, 120.0, 220.0]
    finally:
        cvm.limpar_cache()


def test_dre_degrada_sem_dado(tmp_path, monkeypatch):
    monkeypatch.setattr(cvm, "CVM_PROCESSED_DIR", tmp_path)
    cvm.limpar_cache()
    try:
        assert cvm.dre_completa("009512")["linhas"] == []
        assert cvm.dre_completa("009512")["colunas"] == []
        assert cvm.dre_completa("")["colunas"] == []
    finally:
        cvm.limpar_cache()


def test_cagr_recusa_sinal_trocado():
    """Prejuízo virando lucro não tem taxa composta que signifique nada."""
    # a janela é a distância entre o primeiro e o último valor VÁLIDO —
    # série que só começa no meio não vira CAGR de 5 anos
    assert cvm._cagr([100.0, 121.0], 5) == pytest.approx(0.21)
    assert cvm._cagr([None, None, 100.0, 121.0], 3) == pytest.approx(0.21)
    assert cvm._cagr([100.0, 110.0, 121.0], 2) == pytest.approx(0.1)
    assert cvm._cagr([-50.0, 121.0], 1) is None
    assert cvm._cagr([100.0, -20.0], 1) is None
    assert cvm._cagr([None, 100.0], 1) is None
    assert cvm._cagr([], 5) is None


# ---------------------------------------------------------------------------
# Planilha DCF exportada (spec 4.1 do redesenho)
# ---------------------------------------------------------------------------

def _abrir_planilha(blob):
    import io
    from openpyxl import load_workbook
    return load_workbook(io.BytesIO(blob))


def test_resposta_troca_nan_e_inf_por_null(caplog):
    from finlab.backend.app import JSONSeguro, app
    corpo = JSONSeguro({"a": float("nan"), "b": [1.5, float("inf")],
                        "c": {"d": float("-inf"), "e": "ok"}}).body
    assert json.loads(corpo) == {"a": None, "b": [1.5, None], "c": {"d": None, "e": "ok"}}
    assert "c.d" in caplog.text and "b[1]" in caplog.text
    assert app.router.default_response_class is JSONSeguro


# ---------------------------------------------------------------------------
# BDR: mercado sintético (substitui o antigo bdr_assumptions)
# ---------------------------------------------------------------------------

def test_bdr_market_usa_mcap_do_yahoo_direto():
    out = bdrs.bdr_market(50.0, None, {"marketCap": 1_000_000_000.0})
    assert out["mcap_usd"] == 1_000_000_000.0
    assert out["mcap_fonte"] == "Yahoo Finance"
    assert abs(out["shares"] - 20_000_000.0) < 1e-6


def test_bdr_market_converte_brapi_pela_ptax(monkeypatch):
    from finlab.backend import b3data
    monkeypatch.setattr(b3data, "usdbrl", lambda: 5.0)
    out = bdrs.bdr_market(50.0, {"marketCap": 500_000_000.0}, {})
    assert out["mcap_usd"] == 100_000_000.0
    assert out["mcap_fonte"] == "BRAPI ÷ PTAX"


def test_bdr_market_sem_dado_fica_vazio():
    out = bdrs.bdr_market(None, None, {})
    assert out == {"mcap_usd": None, "mcap_fonte": None, "shares": None}


def test_series_de_divida_da_petrobras():
    if not cvm.available():
        pytest.skip("parquets da CVM ausentes")
    data = cvm.annual_series("009512")
    s = data["series"]
    for chave in ("divida_cp", "divida_lp", "despesas_financeiras"):
        assert chave in s, chave
    # CP + LP == bruta onde ambos existem
    for cp, lp, bruta in zip(s["divida_cp"], s["divida_lp"], s["divida_bruta"]):
        if cp is not None and lp is not None and bruta is not None:
            assert abs((cp + lp) - bruta) < 1e-3
    # despesa financeira da Petrobras é negativa (conta de despesa) e grande
    desp = [v for v in s["despesas_financeiras"] if v is not None]
    assert desp and all(v < 0 for v in desp)


def test_recorta_janela_do_etf():
    from finlab.backend import etfs as etfs_mod
    from datetime import date
    serie = [(f"2025-{m:02d}-15", 100.0 + m) for m in range(1, 13)]
    hoje = date(2025, 12, 20)
    out = etfs_mod.recorta_janela(serie, "3m", hoje=hoje)
    assert out["serie"][0][0] >= "2025-09-20"
    assert abs(out["retorno"] - (112.0 / out["serie"][0][1] - 1)) < 1e-9
    ytd = etfs_mod.recorta_janela(serie, "ytd", hoje=hoje)
    assert ytd["serie"][0][0] == "2025-01-15"
    tudo = etfs_mod.recorta_janela(serie, "max", hoje=hoje)
    assert len(tudo["serie"]) == 12


def test_recorta_janela_sem_cobertura_devolve_o_que_ha():
    from finlab.backend import etfs as etfs_mod
    from datetime import date
    serie = [("2025-11-01", 10.0), ("2025-12-01", 11.0)]
    out = etfs_mod.recorta_janela(serie, "12m", hoje=date(2025, 12, 20))
    # série curta: devolve os pontos existentes e retorno None (janela não coberta)
    assert len(out["serie"]) == 2
    assert out["retorno"] is None


def test_requirements_acompanham_o_codigo():
    """O launcher instala finlab/requirements.txt: ele tem de cobrir a suíte
    (httpx do TestClient) e não pode arrastar dependência de módulo removido."""
    req = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text(encoding="utf-8")
    assert "httpx" in req
    assert "pypdf" not in req      # docs.py saiu no V2
    assert "openpyxl" not in req   # xlsx_dcf.py saiu no V2
    assert "yfinance" in req       # fundamentos de BDR
