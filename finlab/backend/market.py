"""Dados de mercado: cotações, histórico e macro.

Três provedores encadeados, do mais rico para o mais disponível:

  1. BRAPI.dev      — intradiário + fundamentos + consenso. Exige token.
  2. Yahoo Finance  — histórico longo (anos), sem token.
  3. PulseFlat      — CSVs diários no GitHub (raw.githubusercontent.com).
                      Sem token e sobrevive a redes restritas; histórico curto.

O painel usa o primeiro provedor que responder para cada campo e sempre
informa a origem do dado na interface. Além disso, todo fechamento visto é
gravado em finlab/data/history.csv, de modo que o histórico local se
aprofunda com o uso, independentemente do provedor.
"""

from __future__ import annotations

import csv
import io
import json
import os
from bisect import bisect_right
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

import requests

from . import cache
from .settings import (BRAPI_BASE, BRAPI_TOKEN, DATA_DIR, ENV_FILE,
                       ENV_FILE_FOUND, FALLBACK_MACRO, HTTP_TIMEOUT,
                       TTL_FUNDAMENTALS, TTL_HISTORY, TTL_MACRO, TTL_QUOTE)

PULSE_BASE = "https://raw.githubusercontent.com/PulseDataLabs/PulseFlat/main/data"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart"
HISTORY_FILE = DATA_DIR / "history.csv"

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "FinLab/1.0"})


# ---------------------------------------------------------------------------
# Diagnóstico de provedores
# ---------------------------------------------------------------------------

def provider_status() -> dict:
    """Quais fontes estão configuradas/disponíveis, para exibir no painel.

    A BRAPI é a única que depende de token, então ela leva junto o diagnóstico
    do `.env`: onde o painel procurou o arquivo, se achou, e como o token foi
    lido. Sem isso, "rodando sem token" com o token salvo vira adivinhação.
    """
    em_uso = source_label()
    return {
        "brapi": {
            "label": "BRAPI",
            "configured": bool(BRAPI_TOKEN),
            "ok": _probe("brapi"),
            "em_uso": em_uso == "BRAPI",
            "precisa_token": True,
            "token_mascarado": _mascara(BRAPI_TOKEN),
            "env_path": str(ENV_FILE),
            "env_encontrado": ENV_FILE_FOUND,
        },
        "yahoo": {"label": "Yahoo Finance", "configured": True, "ok": _probe("yahoo"),
                  "em_uso": em_uso == "Yahoo Finance", "precisa_token": False},
        "pulseflat": {"label": "PulseFlat", "configured": True, "ok": _probe("pulseflat"),
                      "em_uso": em_uso.startswith("PulseFlat"), "precisa_token": False},
    }


def _mascara(token: str) -> str:
    """Só o suficiente para reconhecer o token — nunca o token inteiro."""
    if not token:
        return ""
    if len(token) <= 8:
        return "•" * len(token)
    return f"{token[:4]}…{token[-2:]} ({len(token)} caracteres)"


def _probe(kind: str) -> Optional[bool]:
    key = f"probe:{kind}"
    hit = cache.get(key, ttl=600)
    if hit is not None:
        return hit.get("ok")
    ok = False
    try:
        if kind == "brapi":
            if not BRAPI_TOKEN:
                ok = False
            else:
                r = _SESSION.get(f"{BRAPI_BASE}/quote/PETR4",
                                 params={"token": BRAPI_TOKEN}, timeout=HTTP_TIMEOUT)
                ok = r.status_code == 200
        elif kind == "yahoo":
            r = _SESSION.get(f"{YAHOO_CHART}/PETR4.SA", params={"range": "5d", "interval": "1d"},
                             timeout=HTTP_TIMEOUT)
            ok = r.status_code == 200
        else:
            r = _SESSION.get(f"{PULSE_BASE}/market_latest.json", timeout=HTTP_TIMEOUT)
            ok = r.status_code == 200
    except Exception:
        ok = False
    cache.set(key, {"ok": ok})
    return ok


# ---------------------------------------------------------------------------
# Provedor 3 — PulseFlat (sem token)
# ---------------------------------------------------------------------------

def _pulse_csv(name: str, ttl: int, memo: bool = True) -> list[dict]:
    """Lê um CSV do PulseFlat. `memo=False` para arquivos grandes.

    Guardar as linhas cruas em disco só compensa em arquivo pequeno: o CSV de
    cotações tem 462 mil linhas e virava um blob JSON de 70 MB no cache — que
    o painel reescrevia na primeira abertura e relia em toda partida. Quem
    passa memo=False já memoiza o resultado *processado*, que é o que importa.
    """
    def fetch():
        r = _SESSION.get(f"{PULSE_BASE}/{name}", timeout=max(HTTP_TIMEOUT, 60))
        r.raise_for_status()
        r.encoding = r.encoding or "utf-8"
        return list(csv.DictReader(io.StringIO(r.text)))
    try:
        if not memo:
            return fetch()
        return cache.memoize(f"pulse:{name}", ttl, fetch) or []
    except Exception:
        return []


# O painel consome no máximo os últimos 500 fechamentos (~2 anos) e a janela
# mais longa da performance é 12 meses. O arquivo do PulseFlat traz desde 2020;
# guardar tudo era um blob de 16 MB relido a cada partida sem que nada na tela
# usasse a cauda. O histórico local (history.csv) segue acumulando o que já viu.
ANOS_DE_HISTORICO = 4


def pulse_prices() -> dict[str, list[tuple[str, float]]]:
    """{ticker: [(data, fechamento), ...]} ordenado por data."""
    def build():
        rows = _pulse_csv("yahoo_acoes_brasileiras.csv", TTL_HISTORY, memo=False)
        corte = (date.today() - timedelta(days=365 * ANOS_DE_HISTORICO)).isoformat()
        out: dict[str, list[tuple[str, float]]] = {}
        for row in rows:
            tk = (row.get("label") or "").strip().upper()
            dt = (row.get("data_referencia") or "").strip()
            try:
                px = float(row.get("preco_fechamento") or "")
            except ValueError:
                continue
            if not tk or not dt or px <= 0 or dt < corte:
                continue
            out.setdefault(tk, []).append((dt, px))
        for tk in out:
            seen: dict[str, float] = dict(sorted(out[tk]))
            out[tk] = sorted(seen.items())
        return out
    # v3: a série passou a ser recortada em ANOS_DE_HISTORICO. Sem o bump, quem
    # já tem o blob antigo continuaria carregando os 16 MB pelo resto do TTL.
    return cache.memoize("pulse:prices:v3", TTL_HISTORY, build) or {}


def pulse_macro() -> dict:
    """Indicadores macro do market_latest.json (CDI, SELIC, IPCA, PTAX, IBOV)."""
    def fetch():
        r = _SESSION.get(f"{PULSE_BASE}/market_latest.json", timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return r.json()
    try:
        return {"items": cache.memoize("pulse:macro", TTL_MACRO, fetch)}
    except Exception:
        return {"items": []}


def _pt_number(txt: str) -> Optional[float]:
    """Converte número em formato pt-BR.

    '14,15%' -> 14.15 · '5.1177' -> 5.1177 · '175.335' -> 175335.0
    Sem vírgula, um ponto só é separador de milhar quando divide grupos de
    exatamente três dígitos ('175.335'); caso contrário é decimal ('5.1177').
    """
    if txt is None:
        return None
    s = str(txt).replace("%", "").replace(" ", "").strip()
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") >= 1:
        inteiro, _, resto = s.partition(".")
        grupos = resto.split(".")
        if all(len(g) == 3 and g.isdigit() for g in grupos) and inteiro.lstrip("-").isdigit():
            s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def yield_curve() -> dict:
    """Curva de juros do Tesouro (ANBIMA), base do custo de capital.

    Para um DCF com perpetuidade, a taxa livre de risco relevante é a de
    prazo longo, não a Selic overnight. Devolvemos as duas, mais a NTN-B
    real e a inflação implícita, para que a escolha fique explícita na tela.
    Taxas em % a.a.
    """
    def build():
        rows = _pulse_csv("anbima_titulos_publicos.csv", TTL_MACRO)
        if not rows:
            return {}
        ref = max(r.get("data_referencia") or "" for r in rows)
        out: dict[str, Optional[float]] = {"data": ref}

        def escolhe(titulo: str, anos_alvo: int) -> Optional[tuple[str, float]]:
            alvo = date.today().year + anos_alvo
            cand = []
            for r in rows:
                if r.get("titulo") != titulo or r.get("data_referencia") != ref:
                    continue
                venc = (r.get("data_vencimento") or "")[:4]
                try:
                    taxa = float(r.get("tx_indicativa"))
                    ano = int(venc)
                except (TypeError, ValueError):
                    continue
                cand.append((abs(ano - alvo), ano, taxa))
            if not cand:
                return None
            cand.sort()
            return (str(cand[0][1]), cand[0][2])

        pre = escolhe("NTN-F", 10)
        real = escolhe("NTN-B", 10)
        real_longa = escolhe("NTN-B", 25)

        if pre:
            out["prefixado_10a"] = round(pre[1], 4)
            out["prefixado_venc"] = pre[0]
        if real:
            out["ntnb_10a"] = round(real[1], 4)
            out["ntnb_venc"] = real[0]
        if real_longa:
            out["ntnb_longa"] = round(real_longa[1], 4)
        if pre and real:
            implicita = ((1 + pre[1] / 100) / (1 + real[1] / 100) - 1) * 100
            out["inflacao_implicita"] = round(implicita, 4)
        return out

    try:
        return cache.memoize("curva:v1", TTL_MACRO, build) or {}
    except Exception:
        return {}


def pulse_ipca_12m() -> Optional[float]:
    """IPCA acumulado em 12 meses, composto a partir da série mensal do BCB.

    O feed traz a variação mensal (SGS 433); o rótulo "12 meses" que vem
    junto está trocado na origem, então compomos aqui em vez de confiar nele.
    """
    def build():
        rows = _pulse_csv("bcb_sgs.csv", TTL_MACRO)
        mensal = []
        for row in rows:
            if str(row.get("codigo_serie")).strip() != "433":
                continue
            try:
                mensal.append((row.get("data_referencia"), float(row.get("valor"))))
            except (TypeError, ValueError):
                continue
        if len(mensal) < 12:
            return None
        mensal.sort()
        acumulado = 1.0
        for _, v in mensal[-12:]:
            acumulado *= 1 + v / 100.0
        return round((acumulado - 1) * 100, 2)
    try:
        return cache.memoize("pulse:ipca12", TTL_MACRO, build)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Provedor 2 — Yahoo Finance (sem token, histórico longo)
# ---------------------------------------------------------------------------

def yahoo_history(ticker: str, rng: str = "2y") -> list[tuple[str, float]]:
    key = f"yahoo:{ticker}:{rng}"

    def fetch():
        r = _SESSION.get(f"{YAHOO_CHART}/{ticker}.SA",
                         params={"range": rng, "interval": "1d"}, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        res = (r.json().get("chart") or {}).get("result") or []
        if not res:
            return []
        stamps = res[0].get("timestamp") or []
        closes = ((res[0].get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        out = []
        for ts, px in zip(stamps, closes):
            if px is None:
                continue
            out.append((datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d"), float(px)))
        return out
    try:
        return cache.memoize(key, TTL_HISTORY, fetch) or []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Provedor 1 — BRAPI (token)
# ---------------------------------------------------------------------------

def brapi_quotes(tickers: Iterable[str]) -> dict[str, dict]:
    """Cotação + fundamentos rápidos em lote (a BRAPI aceita lista separada por vírgula)."""
    tickers = [t.upper() for t in tickers]
    if not BRAPI_TOKEN or not tickers:
        return {}
    out: dict[str, dict] = {}
    for i in range(0, len(tickers), 10):
        chunk = tickers[i:i + 10]
        key = "brapi:quote:" + ",".join(chunk)

        def fetch(chunk=chunk):
            r = _SESSION.get(f"{BRAPI_BASE}/quote/{','.join(chunk)}",
                             params={"token": BRAPI_TOKEN, "fundamental": "true"},
                             timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            return r.json().get("results", [])
        try:
            for item in cache.memoize(key, TTL_QUOTE, fetch) or []:
                sym = str(item.get("symbol", "")).upper()
                if sym:
                    out[sym] = item
        except Exception:
            continue
    return out


def brapi_history(ticker: str, rng: str = "1y") -> list[tuple[str, float]]:
    if not BRAPI_TOKEN:
        return []
    key = f"brapi:hist:{ticker}:{rng}"

    def fetch():
        r = _SESSION.get(f"{BRAPI_BASE}/quote/{ticker}",
                         params={"token": BRAPI_TOKEN, "range": rng, "interval": "1d"},
                         timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        res = r.json().get("results") or []
        if not res:
            return []
        out = []
        for row in res[0].get("historicalDataPrice") or []:
            px, ts = row.get("close"), row.get("date")
            if px is None or ts is None:
                continue
            out.append((datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d"), float(px)))
        return out
    try:
        return cache.memoize(key, TTL_HISTORY, fetch) or []
    except Exception:
        return []


def brapi_fundamentals(ticker: str) -> Optional[dict]:
    if not BRAPI_TOKEN:
        return None
    key = f"brapi:fund:{ticker}"

    def fetch():
        mods = "summaryProfile,defaultKeyStatistics,financialData"
        r = _SESSION.get(f"{BRAPI_BASE}/quote/{ticker}",
                         params={"token": BRAPI_TOKEN, "modules": mods, "dividends": "true"},
                         timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        res = r.json().get("results") or []
        return res[0] if res else None
    try:
        return cache.memoize(key, TTL_FUNDAMENTALS, fetch)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Histórico local acumulado
# ---------------------------------------------------------------------------

def _load_local_history() -> dict[str, dict[str, float]]:
    """Lê o histórico acumulado, ignorando o que não der para aproveitar.

    Este arquivo é escrito a cada carga e pode ficar corrompido — duas
    instâncias do painel no ar ao mesmo tempo, disco cheio, desligamento no
    meio da gravação. Uma linha ruim NÃO pode derrubar o painel inteiro: aqui
    se pula o que estiver quebrado e se aproveita o resto.
    """
    out: dict[str, dict[str, float]] = {}
    if not HISTORY_FILE.exists():
        return out
    try:
        with HISTORY_FILE.open("r", encoding="utf-8", newline="",
                               errors="replace") as fh:
            leitor = csv.reader(fh)
            while True:
                try:
                    row = next(leitor)
                except StopIteration:
                    break
                except csv.Error:
                    # Campo gigante ou NUL no meio: o leitor levanta e segue.
                    continue
                if len(row) != 3:
                    continue
                tk, dt, px = (c.strip() for c in row)
                if not tk or not dt:
                    continue
                try:
                    out.setdefault(tk, {})[dt] = float(px)
                except ValueError:
                    continue
    except (OSError, csv.Error):
        pass
    return out


def _save_local_history(store: dict[str, dict[str, float]]) -> None:
    """Grava num temporário e troca no fim.

    Escrever direto no arquivo final deixa uma janela em que ele está pela
    metade; se o processo morrer aí (ou outro painel estiver gravando junto),
    o histórico fica corrompido. `os.replace` é atômico no mesmo volume.
    """
    tmp = HISTORY_FILE.with_suffix(f".tmp{os.getpid()}")
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            for tk in sorted(store):
                for dt in sorted(store[tk]):
                    w.writerow([tk, dt, f"{store[tk][dt]:.6f}"])
        os.replace(tmp, HISTORY_FILE)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def merge_history(series_by_ticker: dict[str, list[tuple[str, float]]]) -> dict[str, list[tuple[str, float]]]:
    """Funde o que veio do provedor com o histórico local e persiste a união."""
    store = _load_local_history()
    changed = False
    for tk, series in series_by_ticker.items():
        bucket = store.setdefault(tk, {})
        for dt, px in series:
            if bucket.get(dt) != px:
                bucket[dt] = px
                changed = True
    if changed:
        _save_local_history(store)
    return {tk: sorted(vals.items()) for tk, vals in store.items()}


# ---------------------------------------------------------------------------
# Janelas de performance
# ---------------------------------------------------------------------------

_WINDOWS = {"week": 7, "m3": 91, "m12": 365}


def performance(series: list[tuple[str, float]], today: Optional[date] = None) -> dict:
    """Retornos por janela a partir de uma série de fechamentos.

    Cada janela usa o último fechamento disponível em ou antes da data-alvo,
    e só é calculada se houver observação suficientemente próxima do alvo
    (tolerância de 12 dias corridos) — evita comparar 3 meses contra uma
    série que só tem 3 semanas.
    """
    out = {"price": None, "date": None, "day": None, "week": None,
           "m3": None, "m12": None, "ytd": None}
    if not series:
        return out
    series = sorted(series)
    last_date, last_px = series[-1]
    out["price"], out["date"] = last_px, last_date
    ref = today or date.fromisoformat(last_date)

    if len(series) >= 2 and series[-2][1]:
        out["day"] = last_px / series[-2][1] - 1

    # As datas são ISO ("2026-08-05"): comparar como texto já é comparar
    # cronologicamente. A versão anterior varria a série inteira convertendo
    # cada data com strptime, uma vez por janela e por empresa — 462 mil
    # conversões só para montar a tela principal, ~6 s da primeira abertura.
    datas = [d for d, _ in series]

    def close_at(target: date, tol_days: int) -> Optional[float]:
        i = bisect_right(datas, target.isoformat())
        if i == 0:
            return None
        if (target - date.fromisoformat(datas[i - 1])).days > tol_days:
            return None
        return series[i - 1][1]

    for key, days in _WINDOWS.items():
        base = close_at(ref - timedelta(days=days), tol_days=12 if days <= 91 else 20)
        if base:
            out[key] = last_px / base - 1

    jan1 = date(ref.year, 1, 1)
    first_date = date.fromisoformat(series[0][0])
    if first_date <= jan1 + timedelta(days=12):
        base = close_at(jan1, tol_days=12)
        if base:
            out["ytd"] = last_px / base - 1
    return out


# ---------------------------------------------------------------------------
# Macro consolidado
# ---------------------------------------------------------------------------

def macro() -> dict:
    """Selic, CDI, IPCA, dólar e Ibovespa, com origem declarada."""
    def build():
        data = {k: {"value": v, "source": "fallback"} for k, v in FALLBACK_MACRO.items()}
        items = pulse_macro().get("items") or []
        mapping = {
            "CDI": "cdi", "SELIC": "selic",
            "PTAX USD VENDA": "usdbrl", "IBOVESPA": "ibov",
        }
        for item in items:
            label = str(item.get("label", "")).upper()
            key = mapping.get(label)
            if not key:
                continue
            value = _pt_number(item.get("value"))
            if value is None:
                continue
            data[key] = {"value": value, "source": "PulseFlat/BCB",
                         "date": item.get("reference_date"),
                         "change": item.get("change")}

        ipca12 = pulse_ipca_12m()
        if ipca12 is not None:
            data["ipca"] = {"value": ipca12, "source": "BCB · acumulado 12m"}

        curva = yield_curve()
        for chave, rotulo in (("prefixado_10a", "NTN-F ~10 anos"),
                              ("ntnb_10a", "NTN-B ~10 anos (real)"),
                              ("ntnb_longa", "NTN-B longa (real)"),
                              ("inflacao_implicita", "inflação implícita")):
            if curva.get(chave) is not None:
                data[chave] = {"value": curva[chave], "source": "ANBIMA · " + rotulo,
                               "date": curva.get("data")}

        if BRAPI_TOKEN:
            for key, path in (("selic", "prime-rate"), ("ipca", "inflation")):
                value = _brapi_macro(path)
                if value is not None:
                    data[key] = {"value": value, "source": "BRAPI"}
        return data
    try:
        return cache.memoize("macro:v2", TTL_MACRO, build)
    except Exception:
        return {k: {"value": v, "source": "fallback"} for k, v in FALLBACK_MACRO.items()}


def _brapi_macro(path: str) -> Optional[float]:
    try:
        r = _SESSION.get(f"{BRAPI_BASE}/v2/{path}",
                         params={"token": BRAPI_TOKEN, "country": "brazil", "historical": "false"},
                         timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json().get(path) or []
        return float(data[0]["value"]) if data else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Fachada usada pelo restante do backend
# ---------------------------------------------------------------------------

def price_series(tickers: list[str]) -> dict[str, list[tuple[str, float]]]:
    """Séries de fechamento por ticker, do melhor provedor disponível."""
    result: dict[str, list[tuple[str, float]]] = {}

    if BRAPI_TOKEN:
        for tk in tickers:
            hist = brapi_history(tk, "1y")
            if len(hist) > 20:
                result[tk] = hist

    faltando = [t for t in tickers if t not in result]
    if faltando and _probe("yahoo"):
        for tk in faltando:
            hist = yahoo_history(tk, "2y")
            if len(hist) > 20:
                result[tk] = hist

    pulse = pulse_prices()
    for tk in tickers:
        extra = pulse.get(tk) or []
        if not extra:
            continue
        if tk in result:
            merged = dict(result[tk])
            merged.update(dict(extra))
            result[tk] = sorted(merged.items())
        else:
            result[tk] = extra

    return merge_history(result)


def asset_series(tickers: list[str]) -> dict[str, list[tuple[str, float]]]:
    """Séries de fechamento para QUALQUER ativo à vista da B3 (ETF, BDR, ação).

    Ordem: BRAPI (token) → Yahoo → boletim diário da B3 (BDI, sem token).
    Tudo é fundido com o histórico local, que se aprofunda com o uso.
    """
    from . import b3data

    result: dict[str, list[tuple[str, float]]] = {}

    if BRAPI_TOKEN:
        for tk in tickers:
            hist = brapi_history(tk, "1y")
            if len(hist) > 20:
                result[tk] = hist

    faltando = [t for t in tickers if t not in result]
    if faltando and _probe("yahoo"):
        for tk in faltando:
            hist = yahoo_history(tk, "2y")
            if len(hist) > 20:
                result[tk] = hist

    boletim = b3data.bdi()
    for tk in tickers:
        extra = (boletim.get(tk) or {}).get("series") or []
        if not extra:
            continue
        if tk in result:
            merged = dict(result[tk])
            merged.update(dict(extra))
            result[tk] = sorted(merged.items())
        else:
            result[tk] = extra

    return merge_history(result)


def source_label() -> str:
    if BRAPI_TOKEN and _probe("brapi"):
        return "BRAPI"
    if _probe("yahoo"):
        return "Yahoo Finance"
    if _probe("pulseflat"):
        return "PulseFlat (B3/Yahoo D-1)"
    return "histórico local"
