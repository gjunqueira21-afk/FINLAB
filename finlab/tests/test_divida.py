"""Aritmética do bloco de endividamento — tudo síntese, sem rede nem parquet."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from finlab.backend import divida  # noqa: E402

ANOS = [2022, 2023, 2024]
S = {
    "divida_bruta":  [100.0, 120.0, 110.0],
    "divida_liquida": [80.0, 90.0, 70.0],
    "caixa_total":   [20.0, 30.0, 40.0],
    "divida_cp":     [30.0, 40.0, 20.0],
    "divida_lp":     [70.0, 80.0, 90.0],
    "ebitda":        [50.0, 45.0, 70.0],
    "despesas_financeiras": [-10.0, -12.0, -14.0],
}


def test_nd_ebitda_e_cobertura():
    out = divida.indicadores(ANOS, S)
    assert out["anos"] == ANOS
    assert abs(out["series"]["nd_ebitda"][0] - 80.0 / 50.0) < 1e-9
    # cobertura = EBITDA / |despesa financeira|
    assert abs(out["series"]["cobertura_juros"][2] - 70.0 / 14.0) < 1e-9


def test_composicao_e_liquidez():
    out = divida.indicadores(ANOS, S)
    assert abs(out["series"]["curto_prazo_pct"][1] - 40.0 / 120.0) < 1e-9
    assert abs(out["series"]["liquidez_imediata"][2] - 40.0 / 20.0) < 1e-9


def test_custo_aparente_usa_divida_media():
    out = divida.indicadores(ANOS, S)
    # 2023: 12 / ((100+120)/2)
    assert abs(out["series"]["custo_aparente"][1] - 12.0 / 110.0) < 1e-9
    # primeiro ano não tem média com o anterior
    assert out["series"]["custo_aparente"][0] is None


def test_dado_faltando_vira_none_sem_quebrar():
    s = {k: [None, None, None] for k in S}
    out = divida.indicadores(ANOS, s)
    for serie in out["series"].values():
        assert serie == [None, None, None]


def test_ebitda_zero_nao_divide():
    s = dict(S, ebitda=[0.0, 0.0, 0.0])
    out = divida.indicadores(ANOS, s)
    assert out["series"]["nd_ebitda"] == [None, None, None]


from fastapi.testclient import TestClient  # noqa: E402  (httpx via fastapi)


def _client():
    from finlab.backend import app as appmod
    return TestClient(appmod.app), appmod


def test_endpoint_sem_dado_cvm_devolve_200(monkeypatch):
    client, appmod = _client()
    monkeypatch.setattr(appmod, "_fundamentals",
                        lambda t: {"financial": False, "years": [], "series": {}})
    monkeypatch.setattr(appmod, "_ltm", lambda cd: {})
    monkeypatch.setattr(appmod, "_overview_rows",
                        lambda: {"rows": [], "sector_stats": {}})
    r = client.get("/api/company/PETR4/divida")
    assert r.status_code == 200
    body = r.json()
    assert body["anos"] == [] and body["avisos"]


def test_endpoint_financeira_devolve_flag(monkeypatch):
    client, appmod = _client()
    monkeypatch.setattr(appmod, "_fundamentals",
                        lambda t: {"financial": True, "years": [2024], "series": {}})
    r = client.get("/api/company/ITUB4/divida")
    assert r.status_code == 200
    assert r.json()["financial"] is True


def test_divida_de_bdr_declara_fonte_yahoo(monkeypatch):
    client, appmod = _client()
    monkeypatch.setattr(appmod, "_bdr_payload", lambda t: {"fundamentals": {
        "financial": False, "years": [2023, 2024],
        "series": {"divida_bruta": [10.0, 12.0], "divida_liquida": [8.0, 9.0],
                   "caixa_total": [2.0, 3.0], "ebitda": [5.0, 6.0]}}})
    r = client.get("/api/company/AAPL34/divida")
    assert r.status_code == 200
    body = r.json()
    assert body["atual"]["fonte"].startswith("Yahoo"), body["atual"]
    # BDR sem dado não pode mandar rodar o pipeline da CVM
    monkeypatch.setattr(appmod, "_bdr_payload", lambda t: {"fundamentals": {
        "financial": False, "years": [], "series": {}}})
    r2 = client.get("/api/company/AAPL34/divida")
    assert r2.status_code == 200
    assert all("valuation_cvm" not in a for a in r2.json()["avisos"])


def test_medianas_do_setor_cobrem_todos_os_indicadores(monkeypatch):
    import statistics
    client, appmod = _client()

    def fund_fake(t):
        base = {"PETR4": 2.0, "PETR3": 3.0, "PRIO3": 4.0}
        m = base.get(t, 5.0)
        return {"financial": False, "years": [2023, 2024], "series": {
            "divida_bruta": [9.0 * m, 10.0 * m], "divida_liquida": [7.0 * m, 8.0 * m],
            "caixa_total": [2.0 * m, 2.0 * m], "divida_cp": [4.0 * m, 4.0 * m],
            "divida_lp": [5.0 * m, 6.0 * m],
            "ebitda": [5.0, 5.0], "despesas_financeiras": [-1.0 * m, -1.0 * m]}}

    monkeypatch.setattr(appmod, "_fundamentals", fund_fake)
    monkeypatch.setattr(appmod, "_ltm", lambda cd: {})
    monkeypatch.setattr(appmod, "_overview_rows",
                        lambda: {"rows": [], "sector_stats": {"PETROLEO": {"nd_ebitda": 9.9, "n": 8}}})
    r = client.get("/api/company/PETR4/divida")
    st = r.json()["setor"]
    for chave in ("cobertura_juros", "curto_prazo_pct", "liquidez_imediata", "custo_aparente"):
        assert chave in st and st[chave] is not None, chave
    # mediana estatística (statistics.median), incluindo a própria empresa
    universo = appmod.universe
    ults = []
    for tk in [t for t in universo.TICKERS if universo.sector_of(t) == "PETROLEO"]:
        f = fund_fake(tk)
        from finlab.backend import divida as dv
        ults.append(dv.indicadores(f["years"], f["series"])["series"]["cobertura_juros"][-1])
    assert abs(st["cobertura_juros"] - statistics.median(ults)) < 1e-9
