"""Arquivo de deep researches por empresa — `data/deep empresas/`.

Toda vez que o usuário pede um deep research de uma companhia no chat, a
rodada inteira da mesa (pergunta + fala de cada agente) é gravada como um
.md nesta pasta — na VPS, dentro do volume de dados, sobrevivendo a
rebuilds. O painel não interpreta nada aqui: guarda o que a mesa disse,
com data e modelo, para o histórico de pesquisa ser consultável depois.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .settings import DATA_DIR

# O nome da pasta é o que o usuário pediu, com espaço mesmo — os scripts
# de deploy e o Docker sempre a citam entre aspas.
DIR_DEEP = DATA_DIR / "deep empresas"

MAX_CONTEUDO = 400_000


def _seguro(nome: str) -> str:
    """Só letras, números e hífen — nada de path traversal vindo da URL."""
    limpo = re.sub(r"[^A-Za-z0-9_-]", "", str(nome))
    return limpo[:80]


def salvar(ticker: str, conteudo: str, titulo: str = "") -> dict:
    """Grava `{TICKER}-AAAA-MM-DD.md` (sufixo -2, -3… se o dia já tem um)."""
    tk = _seguro(ticker).upper()
    if not tk:
        raise ValueError("Ticker inválido para arquivar.")
    corpo = str(conteudo or "").strip()
    if not corpo:
        raise ValueError("Deep research vazio — nada para arquivar.")
    corpo = corpo[:MAX_CONTEUDO]

    DIR_DEEP.mkdir(parents=True, exist_ok=True)
    hoje = date.today().isoformat()
    base = f"{tk}-{hoje}"
    caminho = DIR_DEEP / f"{base}.md"
    n = 2
    while caminho.exists():
        caminho = DIR_DEEP / f"{base}-{n}.md"
        n += 1

    cab = [f"# Deep research · {tk}",
           f"*{titulo.strip()}*" if titulo.strip() else "",
           f"Arquivado pelo FinLab em "
           f"{datetime.now().strftime('%d/%m/%Y %H:%M')} · "
           "conteúdo produzido pela mesa de IA sobre dados do painel — "
           "não é recomendação de investimento.",
           "", "---", ""]
    caminho.write_text("\n".join(l for l in cab if l is not None) + corpo + "\n",
                       encoding="utf-8")
    return {"arquivo": caminho.name, "ticker": tk, "data": hoje}


def listar() -> list[dict]:
    """Os researches arquivados, mais novo primeiro."""
    if not DIR_DEEP.exists():
        return []
    fora = []
    for arq in DIR_DEEP.glob("*.md"):
        m = re.match(r"([A-Z0-9]+)-(\d{4}-\d{2}-\d{2})", arq.stem)
        fora.append({"arquivo": arq.name,
                     "ticker": m.group(1) if m else arq.stem,
                     "data": m.group(2) if m else "",
                     "tamanho": arq.stat().st_size})
    fora.sort(key=lambda r: (r["data"], r["arquivo"]), reverse=True)
    return fora


def ler(arquivo: str) -> Optional[str]:
    nome = Path(arquivo).name          # nunca sai da pasta
    caminho = DIR_DEEP / nome
    if not caminho.exists() or caminho.suffix != ".md":
        return None
    return caminho.read_text(encoding="utf-8")
