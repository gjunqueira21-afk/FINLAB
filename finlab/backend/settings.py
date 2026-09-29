"""Configuração central do FinLab.

Tudo que muda de máquina para máquina (token, caminhos, TTLs) fica aqui.
Nenhum segredo é gravado no repositório: as chaves vêm de variáveis de
ambiente / `.env` local ou do navegador do usuário.
"""

from __future__ import annotations

import os
from pathlib import Path

try:  # python-dotenv é opcional
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*_a, **_k):
        return False

BASE_DIR = Path(__file__).resolve().parent.parent      # finlab/
REPO_DIR = BASE_DIR.parent                             # raiz do repositório
WEB_DIR = BASE_DIR / "web"
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"

# O pipeline CVM já existente continua sendo a fonte de dados fundamentalistas.
CVM_PROCESSED_DIR = Path(
    os.getenv("FINLAB_CVM_DIR", REPO_DIR / "valuation_cvm" / "data" / "processed")
)

ENV_FILE = BASE_DIR / ".env"
# Guardado antes de carregar: o painel mostra este caminho quando o token não
# aparece, para não sobrar dúvida sobre onde o arquivo tem de estar.
ENV_FILE_FOUND = ENV_FILE.is_file()

load_dotenv(ENV_FILE)
load_dotenv(REPO_DIR / "valuation_cvm" / ".env")

BRAPI_TOKEN = os.getenv("BRAPI_TOKEN", "").strip()
BRAPI_BASE = "https://brapi.dev/api"
HTTP_TIMEOUT = float(os.getenv("FINLAB_HTTP_TIMEOUT", "15"))

# Modo demonstração: gera séries de mercado sintéticas e DETERMINÍSTICAS para
# quem ainda não tem token BRAPI. A interface sinaliza isso em todas as telas.
DEMO_MODE = os.getenv("FINLAB_DEMO", "").strip().lower() in {"1", "true", "yes", "on"}

# TTLs de cache em segundos
TTL_QUOTE = int(os.getenv("FINLAB_TTL_QUOTE", "300"))          # cotação: 5 min
TTL_HISTORY = int(os.getenv("FINLAB_TTL_HISTORY", "3600"))     # histórico: 1 h
TTL_FUNDAMENTALS = int(os.getenv("FINLAB_TTL_FUND", "43200"))  # fundamentos: 12 h
TTL_MACRO = int(os.getenv("FINLAB_TTL_MACRO", "3600"))         # macro: 1 h
TTL_CVM = int(os.getenv("FINLAB_TTL_CVM", "86400"))            # parquet CVM: 24 h

HOST = os.getenv("FINLAB_HOST", "127.0.0.1")
PORT = int(os.getenv("FINLAB_PORT", "8777"))

# Premissas macro de fallback (usadas quando BCB/BRAPI estão indisponíveis).
# Servem apenas como ponto de partida editável — a interface deixa explícito
# quando o valor é fallback e não dado de mercado.
FALLBACK_MACRO = {
    "selic": 15.00,      # % a.a.
    "ipca": 4.50,        # % a.a. (12 meses)
    "cdi": 14.90,        # % a.a.
    "usdbrl": 5.40,
    "erp": 5.00,         # prêmio de risco de mercado (%)
    "crp": 2.00,         # prêmio de risco Brasil / EMBI+ (%)
}

CACHE_DIR.mkdir(parents=True, exist_ok=True)
