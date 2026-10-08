"""Cache simples em memória + disco com TTL.

Objetivo: não estourar a cota da BRAPI e manter o painel rápido mesmo
reiniciando o servidor. O cache em disco é JSON puro, fácil de inspecionar
e de apagar (basta remover finlab/data/cache).

O nome de cada arquivo começa pelo "tipo" da chave (`brapi_quote__…`,
`overview_v8__…`): é isso que deixa o botão Atualizar apagar só cotações,
sem jogar fora fundamentos que levaram minutos para calcular.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from typing import Any, Callable, Iterable, Optional

from .settings import CACHE_DIR

_log = logging.getLogger("finlab.cache")
_LOCK = threading.Lock()
_MEM: dict[str, tuple[float, Any]] = {}
_ATUALIZANDO: set[str] = set()


def _tipo(texto: str) -> str:
    """Os dois primeiros segmentos da chave, em forma de nome de arquivo."""
    return re.sub(r"[^a-z0-9]+", "_", ":".join(texto.split(":")[:2]).lower()).strip("_")[:40]


def _path(key: str):
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    return CACHE_DIR / f"{_tipo(key)}__{digest}.json"


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


def memoize_swr(key: str, ttl: int, producer: Callable[[], Any]) -> Any:
    """Como `memoize`, mas quem chega com o cache vencido não espera.

    Vencido e existente → devolve o velho NA HORA e refaz por trás, numa
    thread (uma só por chave). Só a primeira carga de todas, sem nada
    guardado, espera o producer. É o que tira os segundos de espera da tela
    principal a cada 5 minutos: o preço tem no máximo um ciclo de atraso, e
    o botão Atualizar continua forçando a carga nova.
    """
    cached = get(key, ttl)
    if cached is not None:
        return cached
    stale = get(key, ttl=10 ** 9)
    if stale is None:
        return memoize(key, ttl, producer)

    with _LOCK:
        if key in _ATUALIZANDO:
            return stale
        _ATUALIZANDO.add(key)

    def refaz():
        try:
            value = producer()
            if value is not None:
                set(key, value)
        except Exception:  # o velho continua servindo; o erro fica no log
            _log.exception("atualização em segundo plano falhou: %s", key)
        finally:
            with _LOCK:
                _ATUALIZANDO.discard(key)

    threading.Thread(target=refaz, name=f"swr:{key}", daemon=True).start()
    return stale


def clear(prefixos: Optional[Iterable[str]] = None) -> int:
    """Limpa memória e disco. Devolve quantos arquivos foram removidos.

    `prefixos` (no formato da chave, ex. "brapi:quote", "overview") limita a
    limpeza a esses tipos; sem eles, apaga tudo.
    """
    tipos = [_tipo(p) for p in prefixos] if prefixos is not None else None

    def bate(tipo: str) -> bool:
        return tipos is None or any(tipo == t or tipo.startswith(t + "_") for t in tipos)

    with _LOCK:
        for k in [k for k in _MEM if bate(_tipo(k))]:
            del _MEM[k]
    removed = 0
    for fp in CACHE_DIR.glob("*.json"):
        tipo = fp.name.split("__", 1)[0] if "__" in fp.name else ""
        # Arquivo do formato antigo (sem tipo no nome) só sai na limpeza total.
        if tipos is not None and (not tipo or not bate(tipo)):
            continue
        try:
            fp.unlink()
            removed += 1
        except OSError:
            pass
    return removed
