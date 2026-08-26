"""Dados de negociação e cadastro da B3, via arquivos públicos do PulseFlat.

Três conjuntos:

  * BDI (boletim diário) — preço de fechamento e volume financeiro de TODOS
    os ativos à vista da B3, dia a dia (~50 pregões no arquivo). É o que
    permite cotação, performance e liquidez de ETFs e BDRs sem token algum.
  * Lista oficial de ETFs listados (renda variável e renda fixa).
  * Registro de fundos da CVM — patrimônio líquido e situação de cada classe.

O BDI tem ~1,2 milhão de linhas; o resultado agregado por ativo é cacheado
em disco (TTL longo), então o custo de parse acontece no máximo uma vez por
período de cache.
"""

from __future__ import annotations

import csv
import gzip
import io
import re
import unicodedata
from typing import Optional

import requests

from . import cache
from .settings import HTTP_TIMEOUT, TTL_MACRO

PULSE_BASE = "https://raw.githubusercontent.com/PulseDataLabs/PulseFlat/main/data"
TTL_BDI = 6 * 3600          # o boletim é D-1: 6h de cache bastam
TTL_CADASTRO = 24 * 3600

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "FinLab/1.0"})


def _norm(s: object) -> str:
    txt = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", txt).strip().upper()


# ---------------------------------------------------------------------------
# BDI — preços e volume do mercado à vista
# ---------------------------------------------------------------------------

def bdi() -> dict[str, dict]:
    """Agregado por ativo do boletim diário.

    Devolve {codigo: {"series": [(data, fechamento), ...],
                      "avg_vol": volume financeiro médio diário (R$),
                      "days": pregões com negócio no arquivo}}
    Cobre ações, ETFs, BDRs e units — tudo que negocia à vista.
    """
    def build():
        r = _SESSION.get(f"{PULSE_BASE}/b3_bdi_trades_acoes.csv.gz",
                         timeout=max(HTTP_TIMEOUT, 180))
        r.raise_for_status()
        out: dict[str, dict] = {}
        with gzip.open(io.BytesIO(r.content), "rt", encoding="utf-8", errors="replace") as fh:
            for row in csv.DictReader(fh):
                code = (row.get("codigo_ativo") or "").strip().upper()
                mkt = row.get("mkt")
                sgmt = row.get("sgmt_nm")
                vista = mkt == "EQUITY-CASH" and sgmt == "CASH"
                # ETFs de renda fixa (IMAB11, LFTS11, ...) saem no boletim sob
                # "FIXED INCOME"/"FORWARD"; o padrão XXXX11 separa-os das
                # debêntures e termos verdadeiros desse segmento.
                etf_rf = (mkt == "FIXED INCOME" and sgmt == "FORWARD"
                          and re.fullmatch(r"[A-Z0-9]{4}11", code or ""))
                if not vista and not etf_rf:
                    continue
                date = (row.get("data_referencia") or "")[:10]
                if not code or not date:
                    continue
                try:
                    price = float(row.get("preco_ultimo") or 0)
                    vol = float(row.get("ntl_fin_vol") or 0)
                except (TypeError, ValueError):
                    continue
                if price <= 0:
                    continue
                slot = out.setdefault(code, {"px": {}, "vol": 0.0, "days": 0})
                slot["px"][date] = price
                slot["vol"] += vol
                slot["days"] += 1
        return {
            code: {
                "series": sorted(slot["px"].items()),
                "avg_vol": slot["vol"] / slot["days"] if slot["days"] else 0.0,
                "days": slot["days"],
            }
            for code, slot in out.items()
        }

    try:
        return cache.memoize("b3:bdi:v1", TTL_BDI, build) or {}
    except Exception:
        return {}


def bdi_asset(code: str) -> Optional[dict]:
    return bdi().get(code.upper().strip())


# ---------------------------------------------------------------------------
# ETFs listados
# ---------------------------------------------------------------------------

def etf_listing() -> list[dict]:
    """Lista oficial de ETFs da B3: código, nome e categoria (RV/RF)."""
    def build():
        r = _SESSION.get(f"{PULSE_BASE}/b3_etfs.csv", timeout=max(HTTP_TIMEOUT, 60))
        r.raise_for_status()
        r.encoding = r.encoding or "utf-8"
        out = []
        for row in csv.DictReader(io.StringIO(r.text)):
            code = (row.get("codigo_fundo") or "").strip().upper()
            if not code:
                continue
            out.append({
                "ticker": code,
                "nome": (row.get("nome_fundo") or "").strip(),
                "categoria_b3": (row.get("categoria_etf") or "").strip(),
            })
        return out

    try:
        return cache.memoize("b3:etfs:v1", TTL_CADASTRO, build) or []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Registro de fundos da CVM (patrimônio líquido)
# ---------------------------------------------------------------------------

def fund_registry_index() -> dict[str, dict]:
    """Classes de fundo de índice do registro CVM, indexadas por nome normalizado."""
    def build():
        r = _SESSION.get(f"{PULSE_BASE}/registro_fundo_classe.csv.gz",
                         timeout=max(HTTP_TIMEOUT, 180))
        r.raise_for_status()
        out: dict[str, dict] = {}
        with gzip.open(io.BytesIO(r.content), "rt", encoding="utf-8", errors="replace") as fh:
            for row in csv.DictReader(fh):
                name = _norm(row.get("denominacao_social"))
                if "INDICE" not in name:
                    continue
                try:
                    pl = float(row.get("patrimonio_liquido") or 0) or None
                except (TypeError, ValueError):
                    pl = None
                out[name] = {
                    "pl": pl,
                    "pl_data": (row.get("data_patrimonio_liquido") or "")[:10] or None,
                    "situacao": (row.get("situacao") or "").strip(),
                    "gestor": (row.get("gestor") or "").strip() or None,
                    "administrador": (row.get("administrador") or "").strip() or None,
                    "inicio": (row.get("data_inicio") or "")[:10] or None,
                }
        return out

    try:
        return cache.memoize("b3:registro:v1", TTL_CADASTRO, build) or {}
    except Exception:
        return {}


def registry_for(nome_fundo: str) -> Optional[dict]:
    """Casa o nome (truncado) da lista B3 com o registro CVM."""
    alvo = _norm(nome_fundo)
    if not alvo:
        return None
    idx = fund_registry_index()
    hit = idx.get(alvo)
    if hit:
        return hit
    prefixo = alvo[:35]
    for name, data in idx.items():
        if name.startswith(prefixo):
            return data
    return None


# ---------------------------------------------------------------------------
# Câmbio (para converter valores de BDR)
# ---------------------------------------------------------------------------

def usdbrl() -> Optional[float]:
    from . import market
    item = (market.macro() or {}).get("usdbrl") or {}
    value = item.get("value")
    return float(value) if isinstance(value, (int, float)) else None
