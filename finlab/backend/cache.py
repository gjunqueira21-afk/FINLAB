"""Cache simples em memória + disco com TTL.

Objetivo: não estourar a cota da BRAPI e manter o painel rápido mesmo
reiniciando o servidor. O cache em disco é JSON puro, fácil de inspecionar
e de apagar (basta remover finlab/data/cache).
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any, Callable, Optional

from .settings import CACHE_DIR

_LOCK = threading.Lock()
_MEM: dict[str, tuple[float, Any]] = {}


def _path(key: str):
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    return CACHE_DIR / f"{digest}.json"


def get(key: str, ttl: int) -> Optional[Any]:
    """Devolve o valor cacheado se ainda estiver dentro do TTL."""
    now = time.time()
    with _LOCK:
        hit = _MEM.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]

    fp = _path(key)
    try:
        if fp.exists() and now - fp.stat().st_mtime < ttl:
            with fp.open("r", encoding="utf-8") as fh:
                value = json.load(fh)
            with _LOCK:
                _MEM[key] = (fp.stat().st_mtime, value)
            return value
    except (OSError, ValueError):
        pass
    return None


def set(key: str, value: Any) -> None:  # noqa: A001 - nome espelha get()
    with _LOCK:
        _MEM[key] = (time.time(), value)
    try:
        with _path(key).open("w", encoding="utf-8") as fh:
            json.dump(value, fh, ensure_ascii=False)
    except (OSError, TypeError):
        pass


def memoize(key: str, ttl: int, producer: Callable[[], Any]) -> Any:
    """get-or-produce. Em caso de erro do producer, devolve cache expirado."""
    cached = get(key, ttl)
    if cached is not None:
        return cached
    try:
        value = producer()
    except Exception:
        stale = get(key, ttl=10 ** 9)  # melhor um dado velho do que nenhum
        if stale is not None:
            return stale
        raise
    if value is not None:
        set(key, value)
    return value


def clear() -> int:
    """Limpa memória e disco. Devolve quantos arquivos foram removidos."""
    with _LOCK:
        _MEM.clear()
    removed = 0
    for fp in CACHE_DIR.glob("*.json"):
        try:
            fp.unlink()
            removed += 1
        except OSError:
            pass
    return removed
