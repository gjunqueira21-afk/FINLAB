"""Etapa de documentos: baixa os PDFs do índice IPE e monta o índice de busca.

O 2.1 entregou o ÍNDICE (ipe.parquet): uma linha por documento, com data e
Link_Download. Esta etapa entrega o CONTEÚDO: baixa cada PDF respeitando o
Crawl-Delay de 10 s do robots.txt da CVM, extrai o texto, corta em trechos
com metadado temporal obrigatório e grava tudo num SQLite com FTS5 — busca
BM25 sem banco vetorial, como o parecer 03 §3–4 pede.

É um processo de fundo por natureza: a primeira carga leva horas por causa
do Crawl-Delay. Por isso ela é INCREMENTAL — protocolo já indexado nunca é
baixado de novo — e opt-in no pipeline (--docs), com teto por companhia.

Uso:
    python -m src.ipe_docs                     # incremental, padrão
    python -m src.ipe_docs --meses 12 --por-empresa 10
    python -m src.main ... --docs              # acoplado ao pipeline
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import requests

from .config import PROCESSED_DIR, RAW_DIR
from .logger import logger

# Mesmas categorias do leitor do painel (finlab/backend/ipe.py): o que muda a
# leitura de momento de uma empresa. Press-release entra porque é onde vive a
# prévia operacional.
CATEGORIAS_RELEVANTES = (
    "Fato Relevante",
    "Comunicado ao Mercado",
    "Dados Econômico-Financeiros",
    "Calendário de Eventos Corporativos",
    "Reunião da Administração",
    "Press-release",
)

CRAWL_DELAY_S = 10          # robots.txt da CVM — parecer 03 §2, inegociável
TIMEOUT_S = 60
CHUNK_ALVO = 1100           # ~caracteres por trecho; corta em parágrafo
CHUNK_MINIMO = 200          # trecho menor que isso se junta ao vizinho
MAX_PAGINAS = 60            # apresentação de 300 páginas não vale o custo

DOCS_DIR = RAW_DIR / "docs"
DB_PATH = PROCESSED_DIR / "docs.sqlite"


# ---------------------------------------------------------------------------
# Universo: os CD_CVM cobertos pelo painel
# ---------------------------------------------------------------------------

def _codigos_do_universo() -> set[str]:
    """CD_CVM das 90 empresas do painel, sem zeros à esquerda.

    O universo mora em finlab/backend/universe.py (só stdlib). Importá-lo
    evita manter duas listas; se o finlab não estiver ao lado (pipeline usado
    solto), a etapa indexa todas as companhias do índice — só que aí o teto
    por empresa importa ainda mais.
    """
    raiz = Path(__file__).resolve().parent.parent.parent / "finlab"
    if not (raiz / "backend" / "universe.py").exists():
        return set()
    sys.path.insert(0, str(raiz))
    try:
        from backend import universe  # type: ignore
        return {c.cd_cvm.lstrip("0") for c in universe.UNIVERSE if c.cd_cvm}
    except Exception as exc:
        logger.warning("Universo do painel indisponível (%s) — indexando todos.", exc)
        return set()
    finally:
        sys.path.pop(0)


# ---------------------------------------------------------------------------
# Extração de texto
# ---------------------------------------------------------------------------

def _extrair_texto(caminho: Path) -> str:
    """Texto do PDF, página a página.

    Docling entrega Markdown melhor (tabelas, layout), mas pesa gigabytes de
    modelo; pypdf resolve o caso comum — os PDFs do ENET são digitais, não
    escaneados. A escolha é por disponibilidade: quem instalar docling ganha
    a extração melhor sem mexer aqui.
    """
    try:
        from docling.document_converter import DocumentConverter  # type: ignore
        return DocumentConverter().convert(str(caminho)).document.export_to_markdown()
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("Docling falhou em %s (%s) — caindo para pypdf.", caminho.name, exc)

    from pypdf import PdfReader
    paginas = []
    reader = PdfReader(str(caminho))
    for pagina in reader.pages[:MAX_PAGINAS]:
        try:
            paginas.append(pagina.extract_text() or "")
        except Exception:
            paginas.append("")
    return "\n\n".join(paginas)


def _limpar(texto: str) -> str:
    texto = unicodedata.normalize("NFKC", texto)
    texto = re.sub(r"[ \t]+", " ", texto)
    return re.sub(r"\n{3,}", "\n\n", texto).strip()


def _cortar(texto: str) -> list[str]:
    """Trechos de ~CHUNK_ALVO caracteres, sempre fechando em parágrafo."""
    if not texto:
        return []
    paragrafos = [p.strip() for p in texto.split("\n\n") if p.strip()]
    trechos, atual = [], ""
    for p in paragrafos:
        if atual and len(atual) + len(p) > CHUNK_ALVO:
            trechos.append(atual)
            atual = p
        else:
            atual = f"{atual}\n\n{p}" if atual else p
    if atual:
        # Rabicho curto se junta ao trecho anterior em vez de virar ruído.
        if trechos and len(atual) < CHUNK_MINIMO:
            trechos[-1] += "\n\n" + atual
        else:
            trechos.append(atual)
    return trechos


# ---------------------------------------------------------------------------
# Índice SQLite + FTS5
# ---------------------------------------------------------------------------

ESQUEMA = """
CREATE TABLE IF NOT EXISTS documentos (
    protocolo   TEXT PRIMARY KEY,
    cd_cvm      TEXT NOT NULL,
    categoria   TEXT,
    tipo        TEXT,
    assunto     TEXT,
    data_entrega TEXT NOT NULL,   -- metadado temporal obrigatório (03 §4)
    data_referencia TEXT,
    link        TEXT NOT NULL,
    estado      TEXT NOT NULL DEFAULT 'ok',  -- ok | sem_texto | falha_download
    indexado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_docs_empresa ON documentos (cd_cvm, data_entrega DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS trechos USING fts5(
    texto,
    protocolo UNINDEXED,
    cd_cvm UNINDEXED,
    data_entrega UNINDEXED,
    ordem UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


def _abrir_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript(ESQUEMA)
    return con


def _ja_indexados(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT protocolo FROM documentos")}


def _gravar_documento(con: sqlite3.Connection, meta: dict, trechos: list[str],
                      estado: str) -> None:
    con.execute(
        "INSERT OR REPLACE INTO documentos (protocolo, cd_cvm, categoria, tipo, assunto,"
        " data_entrega, data_referencia, link, estado, indexado_em)"
        " VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))",
        (meta["protocolo"], meta["cd_cvm"], meta["categoria"], meta["tipo"],
         meta["assunto"], meta["data_entrega"], meta["data_referencia"],
         meta["link"], estado))
    con.execute("DELETE FROM trechos WHERE protocolo = ?", (meta["protocolo"],))
    for i, t in enumerate(trechos):
        con.execute(
            "INSERT INTO trechos (texto, protocolo, cd_cvm, data_entrega, ordem)"
            " VALUES (?,?,?,?,?)",
            (t, meta["protocolo"], meta["cd_cvm"], meta["data_entrega"], i))
    con.commit()


# ---------------------------------------------------------------------------
# Seleção e download
# ---------------------------------------------------------------------------

def _selecionar(ipe: pd.DataFrame, meses: int, por_empresa: int,
                universo: set[str]) -> pd.DataFrame:
    df = ipe.copy()
    df["CD"] = df["Codigo_CVM"].astype(str).str.strip().str.lstrip("0")
    if universo:
        df = df[df["CD"].isin(universo)]
    if "Categoria" in df.columns:
        df = df[df["Categoria"].isin(CATEGORIAS_RELEVANTES)]
    df["Data_Entrega"] = pd.to_datetime(df["Data_Entrega"], errors="coerce")
    df = df.dropna(subset=["Data_Entrega", "Link_Download", "Protocolo_Entrega"])
    corte = pd.Timestamp.today() - pd.DateOffset(months=meses)
    df = df[df["Data_Entrega"] >= corte]
    # Mais novo primeiro, teto por companhia: o que aconteceu DESDE o balanço
    # importa mais que o histórico profundo, e o Crawl-Delay cobra por página.
    df = df.sort_values("Data_Entrega", ascending=False)
    return df.groupby("CD", sort=False).head(por_empresa)


def _data_iso(valor) -> Optional[str]:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    ts = pd.to_datetime(valor, errors="coerce")
    return ts.date().isoformat() if pd.notna(ts) else None


def _baixar(sessao: requests.Session, url: str, destino: Path) -> bool:
    destino.parent.mkdir(parents=True, exist_ok=True)
    r = sessao.get(url, timeout=TIMEOUT_S)
    r.raise_for_status()
    destino.write_bytes(r.content)
    return True


def indexar(meses: int = 24, por_empresa: int = 15,
            limite_total: Optional[int] = None) -> dict:
    """Roda a etapa inteira. Devolve o placar (para log e teste)."""
    fp = PROCESSED_DIR / "ipe.parquet"
    if not fp.exists():
        logger.warning("ipe.parquet não existe — rode o pipeline antes (etapa 2.1).")
        return {"baixados": 0, "pulados": 0, "falhas": 0}

    ipe = pd.read_parquet(fp)
    alvo = _selecionar(ipe, meses, por_empresa, _codigos_do_universo())
    con = _abrir_db()
    prontos = _ja_indexados(con)

    placar = {"baixados": 0, "pulados": 0, "falhas": 0}
    sessao = requests.Session()
    sessao.headers["User-Agent"] = "FinLab/1.0 (uso pessoal; contato via GitHub)"

    pendentes = [r for r in alvo.itertuples()
                 if str(r.Protocolo_Entrega) not in prontos]
    logger.info("Documentos: %d no alvo, %d já indexados, %d a baixar "
                "(~%d min com Crawl-Delay).", len(alvo), len(alvo) - len(pendentes),
                len(pendentes), len(pendentes) * CRAWL_DELAY_S // 60)

    for n, r in enumerate(pendentes):
        if limite_total is not None and n >= limite_total:
            logger.info("Teto de %d documentos da rodada atingido — o resto fica "
                        "para a próxima (a etapa é incremental).", limite_total)
            break
        protocolo = str(r.Protocolo_Entrega)
        meta = {
            "protocolo": protocolo,
            "cd_cvm": str(r.CD),
            "categoria": getattr(r, "Categoria", None),
            "tipo": getattr(r, "Tipo", None),
            "assunto": (getattr(r, "Assunto", None) or "")[:300],
            "data_entrega": r.Data_Entrega.date().isoformat(),
            # Data_Referencia vem string no parquet (só a de entrega é
            # convertida na seleção): normaliza aqui, tolerando ausência.
            "data_referencia": _data_iso(getattr(r, "Data_Referencia", None)),
            "link": str(r.Link_Download),
        }
        destino = DOCS_DIR / meta["cd_cvm"] / f"{protocolo}.pdf"
        try:
            if not destino.exists():
                _baixar(sessao, meta["link"], destino)
                time.sleep(CRAWL_DELAY_S)   # só o download paga o pedágio
            texto = _limpar(_extrair_texto(destino))
            trechos = _cortar(texto)
            _gravar_documento(con, meta, trechos, "ok" if trechos else "sem_texto")
            placar["baixados"] += 1
            logger.info("[%d/%d] %s %s · %s (%d trechos)", n + 1, len(pendentes),
                        meta["cd_cvm"], meta["data_entrega"],
                        (meta["categoria"] or "?"), len(trechos))
        except KeyboardInterrupt:
            logger.info("Interrompido — o que já foi indexado está salvo.")
            break
        except Exception as exc:
            # Falha de UM documento não derruba a rodada; fica marcada para o
            # placar e o documento tenta de novo na próxima (não entra no DB).
            placar["falhas"] += 1
            logger.warning("Falha em %s (%s): %s", protocolo, meta["link"], exc)
            time.sleep(CRAWL_DELAY_S)

    placar["pulados"] = len(alvo) - len(pendentes)
    con.close()
    logger.info("Documentos: %(baixados)d indexados, %(pulados)d já estavam, "
                "%(falhas)d falharam.", placar)
    return placar


def main() -> None:
    ap = argparse.ArgumentParser(description="Baixa e indexa os PDFs do índice IPE.")
    ap.add_argument("--meses", type=int, default=24,
                    help="Janela de documentos a trás (padrão: 24 meses)")
    ap.add_argument("--por-empresa", type=int, default=15,
                    help="Teto de documentos por companhia (padrão: 15)")
    ap.add_argument("--limite", type=int, default=None,
                    help="Teto total da rodada (a etapa é incremental)")
    args = ap.parse_args()
    indexar(meses=args.meses, por_empresa=args.por_empresa, limite_total=args.limite)


if __name__ == "__main__":
    main()
