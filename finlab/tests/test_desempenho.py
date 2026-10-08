"""Cache servido na hora, limpeza só do mercado, histórico em memória,
fundamentos pré-calculados e compressão."""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from finlab.backend import cache, cvm, market, metrics, snapshot, universe  # noqa: E402


@pytest.fixture
def cache_isolado(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    cache._MEM.clear()
    yield tmp_path
    cache._MEM.clear()


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def test_cache_vencido_e_servido_na_hora_e_refeito_por_tras(cache_isolado):
    chamadas = []
    pronto = threading.Event()

    def lento():
        chamadas.append(1)
        if len(chamadas) > 1:
            time.sleep(0.3)
            pronto.set()
        return {"versao": len(chamadas)}

    assert cache.memoize_swr("overview:v8", 60, lento) == {"versao": 1}
    # vence o TTL: o arquivo e a memória ficam "velhos"
    cache._MEM["overview:v8"] = (time.time() - 120, {"versao": 1})
    fp = cache._path("overview:v8")
    import os
    os.utime(fp, (time.time() - 120, time.time() - 120))

    t = time.time()
    assert cache.memoize_swr("overview:v8", 60, lento) == {"versao": 1}   # o velho, na hora
    assert time.time() - t < 0.2
    assert pronto.wait(5)
    time.sleep(0.05)
    assert cache.memoize_swr("overview:v8", 60, lento) == {"versao": 2}   # o novo


def test_sem_nada_guardado_a_primeira_carga_espera(cache_isolado):
    assert cache.memoize_swr("etfs:rows:v1", 60, lambda: {"ok": True}) == {"ok": True}


def test_limpar_so_o_mercado_preserva_fundamentos(cache_isolado):
    cache.set("brapi:quote:PETR4", [1])
    cache.set("overview:v8", {"a": 1})
    cache.set("fund:v6:PETR4", {"b": 2})
    cache.set("ltm:v4:009512", {"c": 3})
    removidos = cache.clear(["brapi:quote", "overview"])
    assert removidos == 2
    assert cache.get("fund:v6:PETR4", 3600) == {"b": 2}
    assert cache.get("ltm:v4:009512", 3600) == {"c": 3}
    assert cache.get("brapi:quote:PETR4", 3600) is None
    assert cache.get("overview:v8", 3600) is None
    # sem prefixo: tudo
    assert cache.clear() == 2


def test_prefixo_nao_apaga_tipo_parecido(cache_isolado):
    cache.set("brapi:quote:X", 1)
    cache.set("brapi:quotex:Y", 2)
    cache.clear(["brapi:quote"])
    assert cache.get("brapi:quotex:Y", 3600) == 2


# ---------------------------------------------------------------------------
# Histórico local em memória
# ---------------------------------------------------------------------------

def test_historico_fica_em_memoria_e_respeita_o_filtro(tmp_path, monkeypatch):
    monkeypatch.setattr(market, "HISTORY_FILE", tmp_path / "history.csv")
    market._HIST.update(store=None, assinatura=None)
    out = market.merge_history({"AAA3": [("2026-01-02", 10.0)], "BBB3": [("2026-01-02", 20.0)]},
                               so=["AAA3"])
    assert out == {"AAA3": [("2026-01-02", 10.0)]}
    # gravado no disco, as duas
    assert "BBB3" in (tmp_path / "history.csv").read_text()
    # sem `so`, devolve tudo (compatível com quem já chamava assim)
    assert set(market.merge_history({})) == {"AAA3", "BBB3"}
    # outro processo grava o arquivo: é relido
    (tmp_path / "history.csv").write_text("CCC3,2026-01-02,5.0\n")
    assert set(market.merge_history({})) == {"CCC3"}


def test_consultas_em_paralelo_mantem_a_ordem():
    assert market._em_paralelo(lambda x: x * 2, range(30)) == [x * 2 for x in range(30)]


# ---------------------------------------------------------------------------
# Fundamentos pré-calculados
# ---------------------------------------------------------------------------

RE = ("3.01", "Receita de Venda de Bens e/ou Serviços")


def _linha(cd, fim, conta, valor):
    fim = pd.Timestamp(fim)
    return {"CD_CVM": cd, "DENOM_CIA": "X", "CNPJ_CIA": "x", "DT_FIM_EXERC": fim,
            "ORDEM_EXERC": "ÚLTIMO", "ANO_REFER": fim.year, "CD_CONTA": conta[0],
            "DS_CONTA": conta[1], "VL_CONTA_AJUSTADO": float(valor)}


@pytest.fixture
def cvm_minima(tmp_path, monkeypatch):
    pasta = tmp_path / "cvm"
    pasta.mkdir()
    cd = universe.get("WEGE3").cd_cvm
    pd.DataFrame([_linha(cd, "2024-12-31", RE, 100), _linha(cd, "2025-12-31", RE, 130)]
                 ).to_parquet(pasta / "dre_dfp.parquet", index=False)
    monkeypatch.setattr(cvm, "CVM_PROCESSED_DIR", pasta)
    monkeypatch.setattr(snapshot, "ARQUIVO", tmp_path / "fundamentos.json")
    snapshot._CARREGADO.update(dados=None, mtime=None, por_cd={})
    cvm.limpar_cache()
    cvm._shares_table.cache_clear()
    yield pasta
    cvm.limpar_cache()
    cvm._shares_table.cache_clear()     # a tabela de ações da pasta temporária não pode vazar
    snapshot._CARREGADO.update(dados=None, mtime=None, por_cd={})


def test_fundamentos_pre_calculados_iguais_ao_calculo_direto(cvm_minima):
    assert snapshot.precisa_gerar()
    snapshot.gerar()
    assert not snapshot.precisa_gerar()
    e = snapshot.empresa("WEGE3")
    direto = metrics.fundamentals("WEGE3")
    direto["acoes_cvm"] = {"capital": cvm.shares_outstanding(direto.get("cnpj")),
                           "lpa": cvm.shares_from_eps(direto.get("cd_cvm"))}
    assert e["fund"] == json.loads(json.dumps(direto))
    assert e["dre"] == json.loads(json.dumps(cvm.dre_completa(e["cd_cvm"])))
    assert snapshot.por_cd(e["cd_cvm"]) is not None


def test_cvm_nova_no_disco_invalida_o_arquivo(cvm_minima):
    snapshot.gerar()
    assert snapshot.atual() is not None
    # o pipeline grava demonstrações novas
    df = pd.read_parquet(cvm_minima / "dre_dfp.parquet")
    df.loc[len(df)] = df.iloc[-1]
    time.sleep(1.1)
    df.to_parquet(cvm_minima / "dre_dfp.parquet", index=False)
    assert snapshot.atual() is None          # não usa número velho
    assert snapshot.empresa("WEGE3") is None
    assert snapshot.precisa_gerar()


def test_versao_diferente_nao_e_usada(cvm_minima, monkeypatch):
    snapshot.gerar()
    monkeypatch.setattr(snapshot, "VERSAO", snapshot.VERSAO + 1)
    assert snapshot.atual() is None


def test_cvm_disponivel_nao_carrega_os_parquets(cvm_minima, monkeypatch):
    def proibido(*a, **k):
        raise AssertionError("available() não pode abrir os parquets")
    monkeypatch.setattr(cvm.pd, "read_parquet", proibido)
    cvm._frames.cache_clear()
    assert cvm.available() is True


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def test_botao_atualizar_limpa_so_o_mercado_e_a_resposta_vem_comprimida(cache_isolado):
    from fastapi.testclient import TestClient
    from finlab.backend.app import app

    cache.set("brapi:quote:PETR4", [1])
    cache.set("fund:v6:PETR4", {"b": 2})
    c = TestClient(app)
    r = c.post("/api/cache/clear")
    assert r.json()["escopo"] == "mercado"
    assert cache.get("fund:v6:PETR4", 3600) == {"b": 2}
    assert cache.get("brapi:quote:PETR4", 3600) is None

    r = c.get("/api/universe", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"


def test_so_as_empresas_do_painel_sobem_para_a_memoria(cvm_minima):
    """A CVM traz ~740 companhias e o painel lê 90: as outras não podem
    ocupar memória — carregá-las fazia a VPS matar o processo."""
    cd = universe.get("WEGE3").cd_cvm
    pd.DataFrame([_linha(cd, "2025-12-31", RE, 130), _linha("999999", "2025-12-31", RE, 7)]
                 ).to_parquet(cvm_minima / "dre_dfp.parquet", index=False)
    cvm.limpar_cache()
    carregadas = cvm._frames("dfp")["dre"]
    assert set(carregadas) == {cd}
    assert cvm._company("dre", cd)["VL_CONTA_AJUSTADO"].tolist() == [130.0]


def test_icones_nos_enderecos_padrao_do_iphone():
    """O iPhone tenta /apple-touch-icon.png por conta própria; os dois
    endereços e o /favicon.ico devolvem as imagens do FinLab."""
    from fastapi.testclient import TestClient
    from finlab.backend.app import app

    c = TestClient(app)
    for url in ("/apple-touch-icon.png", "/apple-touch-icon-precomposed.png", "/favicon.ico",
                "/assets/icones/apple-touch-icon.png", "/assets/manifest.webmanifest"):
        r = c.get(url)
        assert r.status_code == 200, url
    assert c.get("/apple-touch-icon.png").content[:8] == b"\x89PNG\r\n\x1a\n"
    assert c.get("/apple-touch-icon.png").content == c.get("/assets/icones/apple-touch-icon.png").content
