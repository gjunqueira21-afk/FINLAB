"""Busca no conteúdo dos documentos da empresa (docs.sqlite do pipeline).

O ipe.py responde "o que a companhia ENTREGOU" (o índice, com data e link).
Este módulo responde "o que está ESCRITO dentro" — busca BM25 via SQLite FTS5
sobre os trechos que a etapa --docs do pipeline extraiu dos PDFs.

Três regras do parecer 03 §5, aplicadas aqui e não em prompt:

  * Todo trecho devolvido carrega a DATA do documento — chunk sem data não
    existe neste índice (a coluna é NOT NULL na origem).
  * A citação é rastreável: cada trecho aponta o link oficial no RAD/ENET.
  * Recuperação vazia devolve vazio — quem monta o contexto decide como
    declarar a abstenção, mas este módulo nunca inventa resultado.

Sem o docs.sqlite (pipeline ainda não rodou com --docs), tudo degrada para
vazio e o painel segue funcionando só com o índice.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import date
from typing import Optional

from .settings import CVM_PROCESSED_DIR

DB_PATH = CVM_PROCESSED_DIR / "docs.sqlite"

# O mesmo esquema que a etapa --docs do pipeline cria (valuation_cvm/src/
# ipe_docs.py). Está declarado aqui também porque a ingestão de calls escreve
# no índice sem passar pelo pipeline — e um teste garante que as duas cópias
# não divirjam. `CREATE ... IF NOT EXISTS` faz as duas conviverem.
ESQUEMA = """
CREATE TABLE IF NOT EXISTS documentos (
    protocolo   TEXT PRIMARY KEY,
    cd_cvm      TEXT NOT NULL,
    categoria   TEXT,
    tipo        TEXT,
    assunto     TEXT,
    data_entrega TEXT NOT NULL,
    data_referencia TEXT,
    link        TEXT NOT NULL,
    estado      TEXT NOT NULL DEFAULT 'ok',
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

# Trechos por consulta: o suficiente para dar corpo sem afogar o contexto.
MAX_TRECHOS = 6
TAM_TRECHO_CONTEXTO = 700


def available() -> bool:
    return DB_PATH.exists()


def _conectar() -> Optional[sqlite3.Connection]:
    if not available():
        return None
    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con
    except sqlite3.Error:
        return None


def _norm(texto: str) -> str:
    s = unicodedata.normalize("NFD", texto)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _consulta_fts(pergunta: str) -> str:
    """Pergunta livre → consulta FTS5 tolerante.

    Cada termo vira um prefixo entre aspas unidos por OR: a pergunta "o que
    aconteceu com a Resia?" precisa achar 'Resia' mesmo sem os outros termos
    baterem — BM25 rankeia quem casa mais. Aspas evitam que operador (AND,
    NEAR, *) vindo do usuário quebre a sintaxe.
    """
    termos = re.findall(r"\w{3,}", _norm(pergunta), flags=re.UNICODE)
    if not termos:
        return ""
    return " OR ".join(f'"{t}"*' for t in termos[:12])


def search(cd_cvm: Optional[str], pergunta: str, n: int = MAX_TRECHOS) -> list[dict]:
    """Trechos mais relevantes para a pergunta, com data e link sempre juntos."""
    if not cd_cvm or not pergunta:
        return []
    con = _conectar()
    if con is None:
        return []
    consulta = _consulta_fts(pergunta)
    if not consulta:
        con.close()
        return []
    try:
        linhas = con.execute(
            """
            SELECT t.texto, t.data_entrega, t.protocolo,
                   d.categoria, d.assunto, d.link
              FROM trechos t
              JOIN documentos d ON d.protocolo = t.protocolo
             WHERE t.cd_cvm = ? AND trechos MATCH ?
             ORDER BY bm25(trechos)
             LIMIT ?
            """,
            (str(cd_cvm).lstrip("0"), consulta, int(n)),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()

    return [{
        "data": r["data_entrega"],
        "categoria": r["categoria"],
        "assunto": r["assunto"],
        "link": r["link"],
        "protocolo": r["protocolo"],
        "trecho": r["texto"][:TAM_TRECHO_CONTEXTO],
    } for r in linhas]


def recentes(cd_cvm: Optional[str], n: int = 4) -> list[dict]:
    """O primeiro trecho dos documentos mais novos — a rodada da mesa abre com
    isto quando não há pergunta que sirva de consulta."""
    if not cd_cvm:
        return []
    con = _conectar()
    if con is None:
        return []
    try:
        linhas = con.execute(
            """
            SELECT t.texto, t.data_entrega, t.protocolo,
                   d.categoria, d.assunto, d.link
              FROM documentos d
              JOIN trechos t ON t.protocolo = d.protocolo AND t.ordem = 0
             WHERE d.cd_cvm = ? AND d.estado = 'ok'
             ORDER BY d.data_entrega DESC
             LIMIT ?
            """,
            (str(cd_cvm).lstrip("0"), int(n)),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()

    return [{
        "data": r["data_entrega"],
        "categoria": r["categoria"],
        "assunto": r["assunto"],
        "link": r["link"],
        "protocolo": r["protocolo"],
        "trecho": r["texto"][:TAM_TRECHO_CONTEXTO],
    } for r in linhas]


def stats(cd_cvm: Optional[str] = None) -> dict:
    """Cobertura do índice — o painel diz até onde a mesa enxerga."""
    con = _conectar()
    if con is None:
        return {"disponivel": False, "documentos": 0}
    try:
        if cd_cvm:
            row = con.execute(
                "SELECT COUNT(*) AS n, MAX(data_entrega) AS ultimo FROM documentos"
                " WHERE cd_cvm = ? AND estado = 'ok'",
                (str(cd_cvm).lstrip("0"),)).fetchone()
        else:
            row = con.execute(
                "SELECT COUNT(*) AS n, MAX(data_entrega) AS ultimo"
                " FROM documentos WHERE estado = 'ok'").fetchone()
        return {"disponivel": True, "documentos": int(row["n"] or 0),
                "ultimo": row["ultimo"]}
    except sqlite3.Error:
        return {"disponivel": False, "documentos": 0}
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Contexto para a mesa + validação de citação
# ---------------------------------------------------------------------------

def bloco_contexto(trechos: list[dict]) -> str:
    """O bloco que entra no contexto dos agentes.

    A data vem ANTES do trecho, sempre — parecer 03 §5: data visível em todo
    chunk injetado. Cada trecho carrega o ID do documento (o protocolo da
    CVM): é o que permite à mesa separar FATO (afirmação que termina com
    `(doc ID)`) de INTERPRETAÇÃO (que não leva doc) — e ao Cético contestar
    por ID, não por impressão. Vazio devolve a abstenção pronta, para o
    agente não fingir que leu documento que não existe.
    """
    if not trechos:
        return ("DOCUMENTOS DA EMPRESA: nenhum trecho recuperado para esta "
                "consulta. Não cite fato relevante, comunicado ou guidance — "
                "diga que não há documento recuperado sobre o assunto.")
    linhas = ["DOCUMENTOS DA EMPRESA (trechos oficiais recuperados)",
              "Regra de citação, obrigatória para a mesa inteira:",
              "• FATO tirado de um trecho: a frase termina com (doc ID), usando o "
              "ID entre colchetes abaixo. Fato sem (doc ID) será tratado como "
              "não fundamentado.",
              "• INTERPRETAÇÃO sua não leva (doc ID) — é assim que o leitor "
              "separa o que o documento diz do que você conclui.",
              "• Nunca invente um ID: só os listados abaixo existem."]
    for t in trechos:
        cab = f"[doc {t['protocolo']} · {t['data']}] {t['categoria'] or 'Documento'}"
        if t.get("assunto"):
            cab += f" — {t['assunto']}"
        linhas.append(f"\n{cab}\nLink: {t['link']}\n{t['trecho']}")
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# PDF enviado pelo usuário no chat
# ---------------------------------------------------------------------------

# Um fato relevante tem 2–6 páginas; uma apresentação, dezenas. O teto de
# caracteres protege o prompt — o que passar dele fica de fora e o bloco avisa.
ANEXO_MAX_BYTES = 15 * 1024 * 1024
ANEXO_MAX_PAGINAS = 80
ANEXO_MAX_CHARS = 30_000


def extrair_pdf(conteudo: bytes) -> dict:
    """Texto de um PDF enviado pelo usuário. Nada é gravado em disco.

    Devolve {"texto", "paginas", "truncado"} ou levanta ValueError com a
    mensagem que o chat mostra.
    """
    import io

    if len(conteudo) > ANEXO_MAX_BYTES:
        raise ValueError("PDF acima de 15 MB — envie um documento menor.")
    if not conteudo.startswith(b"%PDF"):
        raise ValueError("O arquivo não parece ser um PDF.")
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(conteudo))
        paginas = []
        for pagina in reader.pages[:ANEXO_MAX_PAGINAS]:
            try:
                paginas.append(pagina.extract_text() or "")
            except Exception:
                paginas.append("")
        texto = "\n\n".join(paginas).strip()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Não consegui ler o PDF: {type(exc).__name__}") from exc

    if not texto:
        raise ValueError("O PDF não tem texto extraível — se for escaneado, "
                         "o painel não faz OCR.")
    truncado = len(texto) > ANEXO_MAX_CHARS or len(reader.pages) > ANEXO_MAX_PAGINAS
    return {"texto": texto[:ANEXO_MAX_CHARS], "paginas": len(reader.pages),
            "truncado": truncado}


def bloco_anexo(nome: str, anexo: dict) -> str:
    """O documento enviado entra no contexto rotulado como material do usuário:
    é leitura sob demanda, não fonte oficial recuperada do índice."""
    aviso = (" (documento truncado — só o começo está aqui)"
             if anexo.get("truncado") else "")
    return (f"DOCUMENTO ENVIADO PELO USUÁRIO — {nome}{aviso}\n"
            "==========================================\n"
            "O usuário anexou este documento e pediu que você o leia. Ele NÃO "
            "veio do índice oficial: trate como material de trabalho, cite "
            "trechos dele quando afirmar algo baseado nele, e não o confunda "
            "com as demonstrações da CVM.\n\n"
            f"{anexo.get('texto', '')}")


def promessas_propostas(texto: str, trechos: list[dict]) -> list[dict]:
    """Promessas que o agente extraiu dos documentos, filtradas pelo recuperado.

    O modelo devolve um bloco ```json com uma lista. Aqui ele vira dado
    utilizável, e cada item precisa passar por duas peneiras em CÓDIGO:

      * o `doc` tem de ser um dos trechos realmente recuperados — proposta
        ancorada em documento inventado não chega à tela;
      * o prazo, quando vier, tem de ser data ISO válida.

    O link e a data do documento vêm do índice, não do modelo: assim a
    promessa registrada aponta para a fonte certa mesmo que o agente tenha
    escrito a URL errada.
    """
    import json as _json

    if not texto or "promessas" not in texto:
        return []
    bruto = None
    for parte in texto.split("```"):
        limpo = parte.strip()
        if limpo.startswith("json"):
            limpo = limpo[4:].strip()
        if limpo.startswith("{") and '"promessas"' in limpo:
            bruto = limpo
            break
    if bruto is None:
        return []
    try:
        dados = _json.loads(bruto)
    except ValueError:
        return []

    porta = {str(t.get("protocolo")): t for t in trechos if t.get("protocolo")}
    saida = []
    for item in (dados.get("promessas") or [])[:20]:
        if not isinstance(item, dict):
            continue
        corpo = str(item.get("texto") or "").strip()
        doc = str(item.get("doc") or "").strip()
        if not corpo or doc not in porta:
            continue
        prazo = str(item.get("prazo") or "").strip()[:10]
        if prazo:
            try:
                date.fromisoformat(prazo)
            except ValueError:
                prazo = ""
        origem = porta[doc]
        saida.append({
            "texto": corpo[:400],
            "prazo": prazo or None,
            "metrica": (str(item.get("metrica") or "").strip() or None),
            "doc": doc,
            "link": origem.get("link"),
            "data_origem": origem.get("data"),
            "origem": "documento",
        })
    return saida


def validar_citacoes(texto: str, trechos: list[dict]) -> str:
    """Validação de citação em código, não em prompt (03 §5).

    Duas verificações, mesma lógica: referência que NÃO está no conjunto
    recuperado é invenção e sai marcada, em vez de seguir adiante com cara
    de fonte oficial.

      * URL de RAD/ENET fora do conjunto → marcada.
      * `(doc ID)` com ID fora do conjunto → marcado. É a metade em código do
        esquema fato × interpretação (04 F2): o prompt pede a etiqueta, mas
        quem garante que ela aponta para documento real é este filtro.
    """
    permitidos = {t["link"] for t in trechos}
    ids = {str(t.get("protocolo")) for t in trechos if t.get("protocolo")}

    def marca_link(m: re.Match) -> str:
        url = m.group(0).rstrip('.,;)»"')
        if url in permitidos:
            return m.group(0)
        return f"{m.group(0)} ⚠[link não recuperado nesta consulta]"

    def marca_doc(m: re.Match) -> str:
        if m.group(1) in ids:
            return m.group(0)
        return f"{m.group(0)} ⚠[doc inexistente no recuperado]"

    texto = re.sub(r"https?://(?:www\.)?rad\.cvm\.gov\.br\S+", marca_link, texto)
    return re.sub(r"\(doc\s+([A-Za-z0-9_.-]+)\)", marca_doc, texto)
