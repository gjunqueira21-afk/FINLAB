"""Fundamentos pré-calculados: a CVM processada uma vez, não a cada página.

Os números da CVM só mudam quando o pipeline baixa demonstrações novas
(`atualizar-dados.sh`) — quatro vezes por ano por empresa. Recalculá-los a
cada visita custava duas coisas: tempo, e a CVM inteira (anos de DFP e ITR de
todas as companhias abertas) carregada na memória do painel, mais de 1 GB.

Aqui tudo que vem da CVM para as ações do painel — séries anuais e
indicadores, 12 meses, DRE com trimestres, último ITR e quantidade de ações —
é calculado de uma vez e gravado em `data/fundamentos.json`. O painel só lê
esse arquivo. Ele é refeito quando os parquets da CVM mudam (a "assinatura"
abaixo) ou quando o formato muda (VERSAO), num PROCESSO SEPARADO: a memória
que o pandas usa para montar os números volta ao sistema quando ele termina.

As contas são exatamente as mesmas de antes (as mesmas funções), só que
feitas antes de você abrir a página — os testes comparam o arquivo com o
cálculo direto, empresa por empresa.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import cvm, metrics, universe
from .settings import DATA_DIR

_log = logging.getLogger("finlab.snapshot")

# Sobe sempre que o formato do arquivo ou alguma conta mudar: o painel
# então ignora o arquivo velho e manda refazer.
VERSAO = 1
ARQUIVO = DATA_DIR / "fundamentos.json"

_LOCK = threading.Lock()
_CARREGADO: dict = {"dados": None, "mtime": None, "por_cd": {}}
_GERANDO = threading.Event()


def assinatura() -> dict:
    """Tamanho e data de cada arquivo da CVM processado: muda quando o
    pipeline grava dados novos."""
    pasta = Path(cvm.CVM_PROCESSED_DIR)
    out = {"pasta": str(pasta.resolve()) if pasta.exists() else str(pasta)}
    for fp in sorted(list(pasta.glob("*.parquet")) + list(pasta.glob("capital_social.csv"))):
        try:
            st = fp.stat()
            out[fp.name] = [st.st_size, int(st.st_mtime)]
        except OSError:
            continue
    return out


def gerar(destino: Optional[Path] = None) -> dict:
    """Calcula tudo da CVM para as ações do painel e grava o arquivo."""
    destino = Path(destino or ARQUIVO)
    empresas: dict = {}
    for comp in universe.UNIVERSE:
        fund = metrics.fundamentals(comp.ticker)
        cd = comp.cd_cvm
        if fund:
            # As duas fontes de quantidade de ações da CVM, para o valor de
            # mercado quando a BRAPI não traz `sharesOutstanding`.
            fund["acoes_cvm"] = {"capital": cvm.shares_outstanding(fund.get("cnpj")),
                                 "lpa": cvm.shares_from_eps(cd)}
        empresas[comp.ticker] = {
            "cd_cvm": cd,
            "fund": fund,
            "ltm": cvm.ltm_series(cd) if cd else {},
            "dre": cvm.dre_completa(cd) if cd else {},
            "itr": cvm.latest_quarter(cd) if cd else None,
        }
    dados = {"versao": VERSAO, "gerado_em": datetime.now().isoformat(timespec="seconds"),
             "assinatura": assinatura(), "cvm_disponivel": cvm.available(),
             "empresas": empresas}
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(f".tmp{os.getpid()}")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(dados, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, destino)
    return dados


def _ler() -> Optional[dict]:
    """O arquivo, relido só quando muda no disco."""
    try:
        mtime = ARQUIVO.stat().st_mtime_ns
    except OSError:
        return None
    with _LOCK:
        if _CARREGADO["mtime"] != mtime:
            try:
                with ARQUIVO.open("r", encoding="utf-8") as fh:
                    dados = json.load(fh)
            except (OSError, ValueError):
                return None
            _CARREGADO.update(dados=dados, mtime=mtime, por_cd={
                e.get("cd_cvm"): e for e in (dados.get("empresas") or {}).values()
                if e.get("cd_cvm")})
        return _CARREGADO["dados"]


def atual() -> Optional[dict]:
    """O arquivo, se ele corresponde aos dados da CVM que estão no disco.

    Arquivo de outros dados (parquets atualizados, outra versão do código,
    outra pasta) não serve: o painel calcula direto — como sempre fez — até
    o arquivo novo ficar pronto. Número velho com cara de novo, nunca.
    """
    dados = _ler()
    if not dados or dados.get("versao") != VERSAO:
        return None
    if dados.get("assinatura") != assinatura():
        return None
    return dados


def empresa(ticker: str) -> Optional[dict]:
    dados = atual()
    return ((dados or {}).get("empresas") or {}).get(ticker) if dados else None


def por_cd(cd_cvm: Optional[str]) -> Optional[dict]:
    if not cd_cvm or not atual():
        return None
    return _CARREGADO["por_cd"].get(cd_cvm)


def precisa_gerar() -> bool:
    return atual() is None and cvm.available()


def gerar_em_segundo_plano() -> bool:
    """Refaz o arquivo num processo à parte, sem travar o painel.

    Processo e não thread: montar os números carrega a CVM no pandas, e essa
    memória só volta ao sistema quando o processo termina. O painel segue
    respondendo com o cálculo direto enquanto isso.
    """
    if _GERANDO.is_set():
        return False
    _GERANDO.set()

    def roda():
        try:
            subprocess.run([sys.executable, "-m", "finlab.backend.tarefas", "gerar-fundamentos"],
                           check=True, cwd=str(Path(__file__).resolve().parents[2]),
                           stdout=subprocess.DEVNULL)
            _log.info("fundamentos pré-calculados atualizados")
        except Exception:
            _log.exception("falha ao gerar os fundamentos pré-calculados")
        finally:
            _GERANDO.clear()

    threading.Thread(target=roda, name="gerar-fundamentos", daemon=True).start()
    return True
