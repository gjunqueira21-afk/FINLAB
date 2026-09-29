"""Transcrição de teleconferência: segmentar o Q&A e indexar junto do resto.

O parecer 03 §3.4 pede a call segmentada "por par pergunta→resposta" — e é
isso que a torna útil: a unidade de recuperação de uma call não é o parágrafo,
é a troca inteira. Quando um analista pergunta sobre alavancagem, o que
importa é a pergunta MAIS a resposta; metade da troca engana.

A transcrição entra pelo painel, em texto. De onde ela veio — ASR local,
serviço pago, ou o site de RI da companhia — é escolha de quem usa: este
módulo não transcreve, ele **entende** o texto e o coloca no índice.

E o índice é o MESMO dos documentos da CVM (`docs.sqlite`). Isso não é
economia de código: é o que faz a call herdar de graça a recuperação por
BM25, o `doc ID` em toda citação, a validação de link em código e a regra de
fato × interpretação da mesa. Uma call indexada é, para a mesa, um documento
como os outros — com data, com ID, e citável.

Transcrições ficam locais e fora do repositório, como o parecer manda.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import datetime
from typing import Optional

from . import docs

# Marcadores do início da sessão de perguntas. A call brasileira típica tem um
# operador anunciando; a versão em inglês, o "question-and-answer session".
_INICIO_QA = re.compile(
    r"(sess[ãa]o\s+de\s+perguntas|perguntas\s+e\s+respostas|"
    r"question[- ]and[- ]answer|\bq\s*&\s*a\b|iniciar(?:emos)?\s+a\s+sess[ãa]o)",
    re.IGNORECASE)

# "Fulano de Tal, CEO:" / "Operador:" / "Analyst - Bank:" no começo da linha.
_FALANTE = re.compile(r"^[ \t]*([\wÀ-ÿ][\wÀ-ÿ .,'\-/&]{1,60}?)\s*:\s*(?=\S)")

# Quem conduz a call, não a responde: fecha o par corrente sem virar pergunta.
_OPERADOR = re.compile(r"^(operador|operator|moderador)\b", re.IGNORECASE)

# Legenda .vtt/.srt: numeração de cue e a linha de tempo.
_TEMPO = re.compile(r"^\s*(\d+\s*$|\d{1,2}:\d{2}(:\d{2})?[.,]?\d*\s*-->)")

MAX_TRECHO = 2000          # um par muito longo é cortado, não descartado
MAX_TRECHOS = 400          # teto por call, para não estourar o índice


# ---------------------------------------------------------------------------
# Limpeza e segmentação
# ---------------------------------------------------------------------------

def _limpar(texto: str) -> str:
    texto = unicodedata.normalize("NFKC", texto or "")
    linhas = [ln for ln in texto.splitlines()
              if not _TEMPO.match(ln) and ln.strip().upper() != "WEBVTT"]
    return "\n".join(linhas).strip()


def _turnos(texto: str) -> list[dict]:
    """Quebra o texto em turnos de fala.

    Transcrição sem rótulo de falante devolve um turno só, com quem=None —
    e a segmentação seguinte se vira com isso em vez de falhar.
    """
    turnos: list[dict] = []
    atual = {"quem": None, "texto": []}
    for linha in texto.splitlines():
        m = _FALANTE.match(linha)
        if m:
            if atual["texto"]:
                turnos.append(atual)
            atual = {"quem": m.group(1).strip(), "texto": [linha[m.end():].strip()]}
        elif linha.strip():
            atual["texto"].append(linha.strip())
    if atual["texto"]:
        turnos.append(atual)
    return [{"quem": t["quem"], "texto": " ".join(t["texto"]).strip()}
            for t in turnos if " ".join(t["texto"]).strip()]


def _corta_qa(turnos: list[dict]) -> int:
    """Índice do primeiro turno do Q&A. -1 quando a call não tem sessão."""
    for i, t in enumerate(turnos):
        if _INICIO_QA.search(t["texto"]):
            return i
    return -1


def _pares(turnos: list[dict]) -> list[dict]:
    """Agrupa os turnos do Q&A em pares pergunta→resposta.

    A heurística: um turno com "?" abre um par; turnos seguintes são a
    resposta; o próximo turno com "?" (ou o operador anunciando o próximo
    analista) fecha o par e abre outro. Pergunta em várias partes continua
    sendo uma só — enquanto ninguém respondeu, o "?" novo é do mesmo analista.
    """
    pares: list[dict] = []
    corrente: Optional[dict] = None

    def fechar():
        nonlocal corrente
        if corrente and corrente["pergunta"]:
            pares.append(corrente)
        corrente = None

    for t in turnos:
        if _OPERADOR.match(t["quem"] or ""):
            fechar()
            continue
        tem_pergunta = "?" in t["texto"]
        if tem_pergunta and (corrente is None or corrente["resposta"]):
            fechar()
            corrente = {"quem_pergunta": t["quem"], "pergunta": t["texto"],
                        "quem_resposta": None, "resposta": ""}
        elif corrente is None:
            # Resposta sem pergunta antes (transcrição truncada): vira
            # apresentação, não um par capenga.
            continue
        elif tem_pergunta and not corrente["resposta"]:
            corrente["pergunta"] += " " + t["texto"]       # pergunta em partes
        else:
            corrente["quem_resposta"] = corrente["quem_resposta"] or t["quem"]
            corrente["resposta"] = (corrente["resposta"] + " " + t["texto"]).strip()
    fechar()
    return [p for p in pares if p["resposta"]]


def _blocos_apresentacao(turnos: list[dict]) -> list[str]:
    """A parte expositiva, um bloco por falante — que é como ela se lê."""
    blocos = []
    for t in turnos:
        if _OPERADOR.match(t["quem"] or ""):
            continue
        corpo = t["texto"]
        while corpo:
            pedaco, corpo = corpo[:MAX_TRECHO], corpo[MAX_TRECHO:]
            blocos.append((f"{t['quem']}: " if t["quem"] else "") + pedaco)
    return blocos


def segmentar(texto: str) -> dict:
    """Transcrição → {apresentacao: [str], qa: [par], trechos: [str]}.

    `trechos` é o que vai para o índice: cada par vira UM trecho, com a
    pergunta e a resposta juntas — a unidade que faz sentido recuperar.
    """
    limpo = _limpar(texto)
    if not limpo:
        return {"apresentacao": [], "qa": [], "trechos": []}

    turnos = _turnos(limpo)
    corte = _corta_qa(turnos)
    if corte < 0:
        apresentacao, qa = _blocos_apresentacao(turnos), []
    else:
        apresentacao = _blocos_apresentacao(turnos[:corte])
        qa = _pares(turnos[corte:])
        # A marca pode aparecer fora do lugar — a apresentação mencionando a
        # sessão que vem depois, uma transcrição sem rótulo de falante onde
        # tudo é um turno só. Se o corte não produziu par nenhum, ele estava
        # errado: melhor a call inteira como apresentação do que texto perdido.
        if not qa:
            apresentacao, qa = _blocos_apresentacao(turnos), []

    trechos = [f"[APRESENTAÇÃO] {b}" for b in apresentacao]
    for p in qa:
        pergunta = f"P ({p['quem_pergunta'] or 'analista'}): {p['pergunta']}"
        resposta = f"R ({p['quem_resposta'] or 'companhia'}): {p['resposta']}"
        trechos.append(f"[Q&A] {pergunta}\n{resposta}"[:MAX_TRECHO * 2])
    return {"apresentacao": apresentacao, "qa": qa, "trechos": trechos[:MAX_TRECHOS]}


# ---------------------------------------------------------------------------
# Índice
# ---------------------------------------------------------------------------

def _protocolo(data: str) -> str:
    """ID da call no índice. O prefixo evita colisão com protocolo da CVM e
    deixa a origem legível na própria citação: (doc call-2026-08-05)."""
    return f"call-{data}"


def _conectar() -> sqlite3.Connection:
    docs.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(docs.DB_PATH)
    con.executescript(docs.ESQUEMA)
    return con


def indexar(cd_cvm: str, data: str, texto: str, titulo: str = "",
            link: str = "") -> dict:
    """Segmenta e grava a call no índice de documentos.

    Regravar a mesma data substitui a anterior: corrigir uma transcrição não
    pode deixar as duas versões disputando a recuperação.
    """
    if not cd_cvm:
        raise ValueError("Empresa sem código CVM.")
    try:
        data = str(datetime.fromisoformat(str(data)[:10]).date())
    except ValueError as exc:
        raise ValueError("Data da call inválida (use AAAA-MM-DD).") from exc

    seg = segmentar(texto)
    if not seg["trechos"]:
        raise ValueError("Não consegui ler nenhum trecho — o texto está vazio?")

    cd = str(cd_cvm).lstrip("0")
    protocolo = _protocolo(data)
    con = _conectar()
    try:
        con.execute(
            "INSERT OR REPLACE INTO documentos (protocolo, cd_cvm, categoria, tipo,"
            " assunto, data_entrega, data_referencia, link, estado, indexado_em)"
            " VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))",
            (protocolo, cd, "Teleconferência", "transcrição",
             (titulo or f"Call de {data}")[:300], data, data,
             link or "", "ok"))
        con.execute("DELETE FROM trechos WHERE protocolo = ?", (protocolo,))
        for i, trecho in enumerate(seg["trechos"]):
            con.execute(
                "INSERT INTO trechos (texto, protocolo, cd_cvm, data_entrega, ordem)"
                " VALUES (?,?,?,?,?)", (trecho, protocolo, cd, data, i))
        con.commit()
    finally:
        con.close()

    return {"protocolo": protocolo, "data": data,
            "apresentacao": len(seg["apresentacao"]), "qa": len(seg["qa"]),
            "trechos": len(seg["trechos"])}


def listar(cd_cvm: str) -> list[dict]:
    """As calls já indexadas desta empresa, da mais nova para a mais velha."""
    if not cd_cvm or not docs.available():
        return []
    try:
        con = sqlite3.connect(f"file:{docs.DB_PATH}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        linhas = con.execute(
            "SELECT d.protocolo, d.data_entrega, d.assunto,"
            " (SELECT COUNT(*) FROM trechos t WHERE t.protocolo = d.protocolo) AS trechos"
            " FROM documentos d WHERE d.cd_cvm = ? AND d.categoria = 'Teleconferência'"
            " ORDER BY d.data_entrega DESC", (str(cd_cvm).lstrip("0"),)).fetchall()
        con.close()
    except sqlite3.Error:
        return []
    return [{"protocolo": r["protocolo"], "data": r["data_entrega"],
             "titulo": r["assunto"], "trechos": r["trechos"]} for r in linhas]


def remover(cd_cvm: str, protocolo: str) -> bool:
    if not docs.available():
        return False
    con = _conectar()
    try:
        cur = con.execute(
            "DELETE FROM documentos WHERE protocolo = ? AND cd_cvm = ?"
            " AND categoria = 'Teleconferência'",
            (protocolo, str(cd_cvm).lstrip("0")))
        if not cur.rowcount:
            return False
        con.execute("DELETE FROM trechos WHERE protocolo = ?", (protocolo,))
        con.commit()
        return True
    finally:
        con.close()
