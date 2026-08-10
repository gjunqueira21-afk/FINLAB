"""Análise de call pelo agente de contexto — cache em disco e arquivo .md.

O fluxo do redesenho (spec 4.2/4.4): o usuário sobe a transcrição, o painel
segmenta e indexa (calls.py), e UMA chamada ao provedor configurado devolve
um JSON estrito — nota, o que foi entregue, o que ficou devendo, a principal
preocupação do Q&A e as âncoras dos trechos. O resultado é validado AQUI, em
código, e cacheado em `data/calls/{ticker}/{protocolo}.json`: navegar entre
calls nunca chama o modelo de novo.

O arquivo `{ticker}-calls.md` é a projeção canônica desse cache para leitura
— regenerado por completo a cada mudança, com TODAS as calls, da mais nova
para a mais antiga. Nada é apagado, nunca: a tela mostra 3, o arquivo guarda
todas, e ele entra no índice de documentos para a mesa citar `[call:XTXX]`.

Como tudo que nasce de transcrição, o cache e o .md ficam locais
(`finlab/data/calls/`, fora do repositório).
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from . import agents, docs
from .settings import DATA_DIR

DIR_CALLS = DATA_DIR / "calls"

NOTAS = ("positiva", "neutra", "pessimista")
_ROTULO_TRI = re.compile(r"\b([1-4]T\d{2})\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Rótulo da call
# ---------------------------------------------------------------------------

def rotulo_da_call(data_iso: str, titulo: str = "") -> str:
    """O rótulo `XTXX` que identifica a call no arquivo e nas citações.

    Prioridade para o título ("Call do 2T26" → 2T26). Sem título, a
    heurística do calendário de resultados: uma call divulga o trimestre
    ANTERIOR à sua data — call de agosto/26 fala do 2T26, a de fevereiro/26
    fecha o 4T25. Confere com todas as calls do arquivo de referência.
    """
    m = _ROTULO_TRI.search(titulo or "")
    if m:
        return m.group(1).upper()
    try:
        d = date.fromisoformat(str(data_iso)[:10])
    except ValueError:
        return str(data_iso)[:10]
    tri = (d.month - 1) // 3
    if tri == 0:
        return f"4T{(d.year - 1) % 100:02d}"
    return f"{tri}T{d.year % 100:02d}"


def ancoras_validas(rotulo: str, seg: dict) -> list[str]:
    """As âncoras que EXISTEM nesta transcrição — o conjunto contra o qual as
    citações do modelo são validadas (em código, nunca só no prompt)."""
    ancoras = [f"{rotulo}#apresentacao-{i + 1:02d}"
               for i in range(len(seg.get("apresentacao") or []))]
    ancoras += [f"{rotulo}#qa-{i + 1:02d}"
                for i in range(len(seg.get("qa") or []))]
    return ancoras


# ---------------------------------------------------------------------------
# O prompt — critério fixo da nota, para consistência entre calls
# ---------------------------------------------------------------------------

_SISTEMA = (
    "Você é o agente de contexto de um painel de análise fundamentalista. "
    "Sua tarefa: ler a transcrição de UMA teleconferência de resultados e "
    "devolver um resumo estruturado. Responda APENAS com um objeto JSON "
    "válido, sem texto antes ou depois, neste formato:\n"
    "{\n"
    '  "nota": "positiva" | "neutra" | "pessimista" | null,\n'
    '  "entregue": "texto" | null,\n'
    '  "devendo": "texto" | null,\n'
    '  "preocupacao": "texto" | null,\n'
    '  "motivo": "por que algum campo ficou null" | null,\n'
    '  "trechos": ["âncora", ...]\n'
    "}\n\n"
    "CRITÉRIO FIXO DA NOTA — aplique exatamente este, para que calls "
    "diferentes sejam comparáveis:\n"
    "- positiva: a gestão ENTREGOU o que havia prometido E respondeu a "
    "principal preocupação dos analistas com números;\n"
    "- pessimista: falhou uma entrega relevante OU se esquivou do tema "
    "principal do Q&A;\n"
    "- neutra: todo o resto.\n\n"
    "Campos:\n"
    "- entregue: o que a gestão cumpriu contra o que havia guiado/prometido, "
    "com os números ditos na call;\n"
    "- devendo: o que ficou aquém do guiado ou foi adiado;\n"
    "- preocupacao: o tema mais insistente do Q&A e COMO a gestão respondeu "
    "(com números ou se esquivando);\n"
    "- trechos: 1 a 4 âncoras da lista de âncoras válidas fornecida — "
    "somente da lista, nunca inventadas.\n\n"
    "HONESTIDADE: você só sabe o que está na transcrição. Se ela não "
    "sustentar um campo (call sem Q&A, texto truncado, sem menção a "
    "promessa anterior), devolva null nesse campo e explique em `motivo` — "
    "abster-se é resposta certa, chutar não é."
)

# Teto de transcrição enviada ao modelo. Um contexto estourado falha a
# chamada inteira; cortar o MEIO da apresentação preserva o que mais
# importa — o começo (guidance) e o Q&A completo.
_MAX_CHARS = 60_000


def _corpo_para_analise(rotulo: str, seg: dict) -> str:
    partes = [f"CALL {rotulo} — transcrição segmentada pelo painel.", ""]
    apresentacao = seg.get("apresentacao") or []
    qa = seg.get("qa") or []

    partes.append("== APRESENTAÇÃO ==")
    for i, bloco in enumerate(apresentacao):
        partes.append(f"[{rotulo}#apresentacao-{i + 1:02d}] {bloco}")
    partes.append("")
    partes.append("== SESSÃO DE PERGUNTAS (Q&A) ==")
    if not qa:
        partes.append("(esta transcrição não tem sessão de perguntas)")
    for i, par in enumerate(qa):
        partes.append(
            f"[{rotulo}#qa-{i + 1:02d}] "
            f"P ({par.get('quem_pergunta') or 'analista'}): {par.get('pergunta')}\n"
            f"R ({par.get('quem_resposta') or 'companhia'}): {par.get('resposta')}")

    texto = "\n".join(partes)
    if len(texto) > _MAX_CHARS:
        corte = _MAX_CHARS // 2
        texto = (texto[:corte] + "\n\n[... transcrição cortada pelo painel "
                 "para caber no contexto ...]\n\n" + texto[-corte:])
    return texto


# ---------------------------------------------------------------------------
# Chamada + validação
# ---------------------------------------------------------------------------

def _json_da_resposta(texto: str) -> dict:
    """O JSON da resposta, com ou sem cerca de código em volta."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", texto, re.DOTALL)
    bruto = m.group(1) if m else texto
    ini, fim = bruto.find("{"), bruto.rfind("}")
    if ini < 0 or fim <= ini:
        raise ValueError("A resposta do modelo não trouxe um objeto JSON.")
    return json.loads(bruto[ini:fim + 1])


def _valida(parsed: dict, validas: list[str]) -> dict:
    """Só o schema 4.2 passa; âncora fora da transcrição cai AQUI, em código."""
    def txt(chave):
        v = parsed.get(chave)
        return str(v).strip()[:900] if isinstance(v, str) and str(v).strip() else None

    nota = parsed.get("nota")
    nota = nota.strip().lower() if isinstance(nota, str) else None
    if nota not in NOTAS:
        nota = None

    conjunto = set(validas)
    trechos = [str(t).strip() for t in (parsed.get("trechos") or [])
               if isinstance(t, str)]
    trechos = [t for t in trechos if t in conjunto][:4]

    return {"nota": nota, "entregue": txt("entregue"), "devendo": txt("devendo"),
            "preocupacao": txt("preocupacao"), "motivo": txt("motivo"),
            "trechos": trechos}


def analisar(slot: dict, rotulo: str, seg: dict) -> dict:
    """Uma chamada ao provedor do slot; devolve a análise validada.

    Levanta `agents.LLMError` (provedor fora do ar, chave ruim) ou
    `ValueError` (resposta que não é o JSON pedido) — quem chama decide
    guardar a call sem análise com a mensagem do erro.
    """
    validas = ancoras_validas(rotulo, seg)
    user = (_corpo_para_analise(rotulo, seg)
            + "\n\nÂNCORAS VÁLIDAS (use apenas estas em `trechos`): "
            + (", ".join(validas) if validas else "(nenhuma)")
            + "\n\nDevolva o JSON.")
    resposta = agents.chat(slot["provider"], slot["api_key"], slot["model"],
                           _SISTEMA, user, temperature=0.2, max_tokens=1200)
    return _valida(_json_da_resposta(resposta), validas)


SEM_PROVEDOR = ("Configure um provedor na mesa de IA (⚙) para gerar o resumo "
                "desta call.")


# ---------------------------------------------------------------------------
# Cache em disco — data/calls/{ticker}/{protocolo}.json
# ---------------------------------------------------------------------------

def _dir_ticker(ticker: str) -> Path:
    return DIR_CALLS / ticker.upper()


def _caminho(ticker: str, protocolo: str) -> Path:
    # O protocolo vem do próprio painel (call-AAAA-MM-DD); o basename barra
    # qualquer tentativa de path traversal vinda de um protocolo torto.
    return _dir_ticker(ticker) / (Path(protocolo).name + ".json")


def gravar(ticker: str, registro: dict) -> None:
    caminho = _caminho(ticker, registro["protocolo"])
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(registro, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(caminho)


def carregar(ticker: str, protocolo: str) -> Optional[dict]:
    caminho = _caminho(ticker, protocolo)
    if not caminho.exists():
        return None
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def apagar(ticker: str, protocolo: str) -> None:
    try:
        _caminho(ticker, protocolo).unlink(missing_ok=True)
    except OSError:
        pass


def registro_novo(protocolo: str, data_iso: str, titulo: str,
                  analise: Optional[dict], mensagem: Optional[str] = None,
                  modelo: str = "") -> dict:
    return {
        "protocolo": protocolo,
        "data": data_iso,
        "titulo": titulo or f"Call de {data_iso}",
        "rotulo": rotulo_da_call(data_iso, titulo),
        "analise": analise,
        "mensagem": mensagem,
        "modelo": modelo,
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# A lista que a página consome
# ---------------------------------------------------------------------------

def com_analise(ticker: str, lista: list[dict]) -> list[dict]:
    """Enriquece a lista do índice (calls.listar) com o cache de análise e a
    posição na tela: 3 mais recentes ficam; da 4ª em diante, `arquivada_em` é
    a data da call que a empurrou para fora."""
    fora = []
    for i, item in enumerate(sorted(lista, key=lambda c: c["data"], reverse=True)):
        reg = carregar(ticker, item["protocolo"]) or {}
        item = dict(item)
        item["rotulo"] = reg.get("rotulo") or rotulo_da_call(item["data"],
                                                            item.get("titulo") or "")
        item["analise"] = reg.get("analise")
        item["mensagem"] = reg.get("mensagem")
        item["nota"] = (reg.get("analise") or {}).get("nota")
        item["na_tela"] = i < 3
        fora.append(item)
    for i, item in enumerate(fora):
        item["arquivada_em"] = fora[i - 3]["data"] if i >= 3 else None
    return fora


# ---------------------------------------------------------------------------
# O arquivo {ticker}-calls.md — regenerado por completo, nunca editado
# ---------------------------------------------------------------------------

def caminho_md(ticker: str) -> Path:
    return DIR_CALLS / f"{ticker.upper()}-calls.md"


def _dmy(data_iso: str) -> str:
    try:
        return date.fromisoformat(str(data_iso)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return str(data_iso)


def _secao_md(item: dict) -> str:
    a = item.get("analise") or {}
    nota = (a.get("nota") or "sem análise").upper()
    estado = ("na tela" if item.get("na_tela")
              else f"arquivada da tela em {_dmy(item.get('arquivada_em') or '')}")
    linhas = [f"## [call:{item['rotulo']}] — {_dmy(item['data'])} · "
              f"nota: **{nota}** · {estado}", ""]

    if not item.get("analise"):
        motivo = (item.get("mensagem")
                  or "provedor não configurado quando a call entrou")
        linhas.append(f"- *(sem análise: {motivo})*")
    else:
        campos = [("Entregue", a.get("entregue")),
                  ("Ficou devendo", a.get("devendo")),
                  ("Preocupação principal (Q&A)", a.get("preocupacao"))]
        for rotulo, valor in campos:
            linhas.append(f"- **{rotulo}:** "
                          + (valor or f"*sem base na transcrição"
                             + (f" — {a['motivo']}" if a.get("motivo") else "")
                             + "*"))
        if a.get("trechos"):
            linhas.append("- **Âncoras:** "
                          + " · ".join(f"`{t}`" for t in a["trechos"]))
    return "\n".join(linhas)


def regenerar_md(ticker: str, cd_cvm: str, lista_com_analise: list[dict]) -> Optional[Path]:
    """Reescreve `{ticker}-calls.md` do zero a partir do cache e o indexa.

    Fonte de dados = os JSONs; o .md é a projeção canônica para leitura —
    regenerado inteiro, nunca dessincroniza. E como ele entra no índice de
    documentos, a mesa cita `[call:XTXX]` como qualquer documento.
    """
    ticker = ticker.upper()
    if not lista_com_analise:
        return None

    corpo = [
        f"# {ticker} · Arquivo de calls", "",
        "> Gerado pelo agente de contexto do Gab's FinLab. **Este arquivo é a "
        "fonte canônica**: guarda", "> todas as calls já enviadas, da mais "
        "nova para a mais antiga — nada se apaga. O painel mostra",
        "> apenas as 3 do topo; a mesa de IA lê o arquivo inteiro e cita cada "
        "call por `[call:XTXX]`,", "> com data e doc ID, como qualquer "
        "documento do índice.", "", "---", "",
    ]
    for item in lista_com_analise:
        corpo.append(_secao_md(item))
        corpo.append("")
    corpo += [
        "---", "",
        "*Formato por call: `nota` (positiva · neutra · pessimista, critério "
        "fixo do agente), três campos de texto (entregue · ficou devendo · "
        "preocupação principal) e âncoras para os trechos da transcrição no "
        "índice. Uma call nova entra no topo; as antigas nunca saem daqui.*", "",
    ]

    caminho = caminho_md(ticker)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text("\n".join(corpo), encoding="utf-8")
    _indexar_md(ticker, cd_cvm, lista_com_analise)
    return caminho


def _indexar_md(ticker: str, cd_cvm: str, lista: list[dict]) -> None:
    """Uma seção do arquivo por trecho, sob um documento só. É o que faz a
    ANÁLISE (não só a transcrição crua) ser recuperável pela mesa."""
    if not cd_cvm:
        return
    cd = str(cd_cvm).lstrip("0")
    protocolo = f"callsmd-{ticker.upper()}"
    mais_nova = lista[0]["data"] if lista else ""
    docs.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(docs.DB_PATH)
    try:
        con.executescript(docs.ESQUEMA)
        con.execute(
            "INSERT OR REPLACE INTO documentos (protocolo, cd_cvm, categoria,"
            " tipo, assunto, data_entrega, data_referencia, link, estado,"
            " indexado_em) VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))",
            (protocolo, cd, "Arquivo de calls", "resumo",
             f"{ticker.upper()}-calls.md — análises do agente de contexto",
             mais_nova, mais_nova, "", "ok"))
        con.execute("DELETE FROM trechos WHERE protocolo = ?", (protocolo,))
        for i, item in enumerate(lista):
            con.execute(
                "INSERT INTO trechos (texto, protocolo, cd_cvm, data_entrega,"
                " ordem) VALUES (?,?,?,?,?)",
                (_secao_md(item), protocolo, cd, item["data"], i))
        con.commit()
    finally:
        con.close()
