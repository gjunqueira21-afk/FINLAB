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
