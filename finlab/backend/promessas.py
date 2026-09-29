"""Placar de promessas: o que a gestão prometeu, e o que ela entregou.

Uma promessa da administração — "capex de R$ 2 bi em 2026", "desalavancar
para 2× até o 4T", "vender a operação nos EUA no 1S" — vale exatamente o
tanto que ela é cobrada depois. O painel já sabia o que a empresa
contabilizou e o que ela comunicou; faltava a memória de terceiro tipo: o
que ela DISSE QUE IA FAZER, com prazo, e no que aquilo deu.

Três decisões de desenho:

  * **Versionado, nunca sobrescrito.** Toda mudança vira uma versão nova com
    data. Uma promessa que muda de prazo duas vezes é o dado mais valioso
    aqui — e um `UPDATE` a apagaria. O estado corrente é a última versão; o
    histórico fica inteiro.
  * **Local, fora do repositório.** Vive em `finlab/data/promessas.json`,
    ignorado pelo git: é a memória de análise do usuário, com a leitura dele
    sobre a gestão. Mesma regra das transcrições no parecer 03.
  * **Origem declarada.** Promessa registrada a partir de um documento
    carrega o `doc` (protocolo da CVM) e o link. Promessa digitada à mão
    fica marcada como manual — sem fingir procedência que não tem.

Nada aqui é calculado por modelo: o placar é aritmética sobre o que o
usuário registrou e deu baixa.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import date, datetime
from typing import Optional

from .settings import DATA_DIR

ARQUIVO = DATA_DIR / "promessas.json"

# `aberta` é o único estado que o tempo pode mudar de significado: passado o
# prazo sem baixa, ela vira "vencida" no placar — sem que ninguém a edite.
ESTADOS = ("aberta", "cumprida", "quebrada", "parcial")

_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Persistência
# ---------------------------------------------------------------------------

def _ler() -> dict:
    if not ARQUIVO.exists():
        return {}
    try:
        with ARQUIVO.open("r", encoding="utf-8") as fh:
            dados = json.load(fh)
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        # Arquivo corrompido não pode derrubar o painel: o placar some, o
        # resto da tela continua. O arquivo fica onde está, para o usuário
        # poder recuperar à mão.
        return {}


def _gravar(dados: dict) -> None:
    ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
    tmp = ARQUIVO.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(dados, fh, ensure_ascii=False, indent=1)
    tmp.replace(ARQUIVO)   # troca atômica: nunca deixa o arquivo pela metade


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------

def _corrente(promessa: dict) -> dict:
    """O estado de hoje de uma promessa: a última versão registrada."""
    versoes = promessa.get("versoes") or []
    return versoes[-1] if versoes else {}


def _vencida(atual: dict, hoje: Optional[date] = None) -> bool:
    prazo = atual.get("prazo")
    if atual.get("estado") != "aberta" or not prazo:
        return False
    try:
        return date.fromisoformat(str(prazo)[:10]) < (hoje or date.today())
    except ValueError:
        return False


def _achatar(promessa: dict, hoje: Optional[date] = None) -> dict:
    """A promessa como o painel a consome: estado corrente + histórico."""
    atual = _corrente(promessa)
    return {
        "id": promessa.get("id"),
        "criada_em": promessa.get("criada_em"),
        "texto": atual.get("texto"),
        "prazo": atual.get("prazo"),
        "metrica": atual.get("metrica"),
        "estado": atual.get("estado", "aberta"),
        "nota": atual.get("nota"),
        "doc": atual.get("doc"),
        "link": atual.get("link"),
        "data_origem": atual.get("data_origem"),
        "origem": atual.get("origem", "manual"),
        "vencida": _vencida(atual, hoje),
        "revisoes": len(promessa.get("versoes") or []) - 1,
        "versoes": promessa.get("versoes") or [],
    }


def listar(ticker: str, hoje: Optional[date] = None) -> list[dict]:
    """Promessas de um ticker: vencidas primeiro, depois por prazo."""
    with _LOCK:
        cru = _ler().get(str(ticker).upper(), [])
    itens = [_achatar(p, hoje) for p in cru]
    # Quem está vencido é o que exige ação; entre iguais, prazo mais próximo.
    itens.sort(key=lambda p: (not p["vencida"], p["estado"] != "aberta",
                              p["prazo"] or "9999"))
    return itens


def placar(ticker: str, hoje: Optional[date] = None) -> dict:
    """Contagem por estado — o resumo que o painel e a mesa leem.

    `taxa` só existe quando alguma promessa já foi resolvida: dizer "0% de
    cumprimento" para uma empresa sem nenhuma promessa vencida seria mentira
    aritmética.
    """
    itens = listar(ticker, hoje)
    conta = {e: 0 for e in ESTADOS}
    for p in itens:
        conta[p["estado"]] = conta.get(p["estado"], 0) + 1
    resolvidas = conta["cumprida"] + conta["quebrada"] + conta["parcial"]
    return {
        "total": len(itens),
        "aberta": conta["aberta"],
        "cumprida": conta["cumprida"],
        "quebrada": conta["quebrada"],
        "parcial": conta["parcial"],
        "vencidas": sum(1 for p in itens if p["vencida"]),
        "taxa": (round(conta["cumprida"] / resolvidas, 3) if resolvidas else None),
        "itens": itens,
    }


# ---------------------------------------------------------------------------
# Escrita
# ---------------------------------------------------------------------------

def _versao(campos: dict, estado: str) -> dict:
    return {
        "quando": _agora(),
        "texto": (campos.get("texto") or "").strip(),
        "prazo": (campos.get("prazo") or None),
        "metrica": (campos.get("metrica") or None),
        "estado": estado,
        "nota": (campos.get("nota") or None),
        "doc": (campos.get("doc") or None),
        "link": (campos.get("link") or None),
        "data_origem": (campos.get("data_origem") or None),
        "origem": campos.get("origem") or ("documento" if campos.get("doc") else "manual"),
    }


def registrar(ticker: str, campos: dict) -> dict:
    """Cria uma promessa. Texto é obrigatório — o resto é opcional."""
    texto = (campos.get("texto") or "").strip()
    if not texto:
        raise ValueError("A promessa precisa de um texto.")
    estado = campos.get("estado") or "aberta"
    if estado not in ESTADOS:
        raise ValueError(f"Estado inválido: {estado}")

    tk = str(ticker).upper()
    nova = {"id": uuid.uuid4().hex[:12], "criada_em": _agora(),
            "versoes": [_versao(campos, estado)]}
    with _LOCK:
        dados = _ler()
        dados.setdefault(tk, []).append(nova)
        _gravar(dados)
    return _achatar(nova)


def atualizar(ticker: str, promessa_id: str, campos: dict) -> dict:
    """Nova VERSÃO de uma promessa — dar baixa, corrigir prazo, anotar.

    Os campos ausentes herdam da versão anterior: dar baixa não deve exigir
    reenviar o texto inteiro, e reenviá-lo seria uma chance de perdê-lo.
    """
    tk = str(ticker).upper()
    estado = campos.get("estado")
    if estado is not None and estado not in ESTADOS:
        raise ValueError(f"Estado inválido: {estado}")

    with _LOCK:
        dados = _ler()
        lista = dados.get(tk) or []
        alvo = next((p for p in lista if p.get("id") == promessa_id), None)
        if alvo is None:
            raise KeyError(promessa_id)
        anterior = _corrente(alvo)
        herdado = {k: campos.get(k, anterior.get(k))
                   for k in ("texto", "prazo", "metrica", "nota", "doc", "link",
                             "data_origem", "origem")}
        alvo["versoes"].append(_versao(herdado, estado or anterior.get("estado", "aberta")))
        _gravar(dados)
    return _achatar(alvo)


def remover(ticker: str, promessa_id: str) -> bool:
    """Apaga uma promessa inteira — o único caminho destrutivo, para quando
    ela foi registrada por engano."""
    tk = str(ticker).upper()
    with _LOCK:
        dados = _ler()
        lista = dados.get(tk) or []
        restante = [p for p in lista if p.get("id") != promessa_id]
        if len(restante) == len(lista):
            return False
        if restante:
            dados[tk] = restante
        else:
            dados.pop(tk, None)
        _gravar(dados)
    return True


# ---------------------------------------------------------------------------
# Contexto da mesa
# ---------------------------------------------------------------------------

def bloco_contexto(ticker: str, hoje: Optional[date] = None) -> str:
    """O placar como a mesa o lê.

    Vazio devolve o convite explícito a não inventar: a ausência de promessa
    registrada não é ausência de promessa feita, e o agente precisa saber a
    diferença.
    """
    p = placar(ticker, hoje)
    if not p["total"]:
        return ("PLACAR DE PROMESSAS: nenhuma promessa registrada para esta empresa. "
                "Isso significa que o usuário ainda não cadastrou nenhuma — NÃO "
                "significa que a gestão não prometeu nada. Não afirme cumprimento "
                "nem descumprimento de promessa a partir daqui.")

    linhas = [
        "PLACAR DE PROMESSAS (registrado pelo usuário; a fonte de cada item está "
        "no próprio item)",
        f"  Resumo: {p['total']} promessa(s) · {p['aberta']} aberta(s) "
        f"({p['vencidas']} com prazo vencido) · {p['cumprida']} cumprida(s) · "
        f"{p['quebrada']} quebrada(s) · {p['parcial']} parcial(is)"
        + (f" · taxa de cumprimento {p['taxa']:.0%}" if p["taxa"] is not None else ""),
    ]
    for item in p["itens"]:
        marca = "VENCIDA" if item["vencida"] else item["estado"].upper()
        cab = f"  [{marca}]"
        if item["prazo"]:
            cab += f" prazo {item['prazo']}"
        if item["doc"]:
            cab += f" (doc {item['doc']})"
        if item["revisoes"] > 0:
            # Promessa que mudou de prazo é sinal, não ruído.
            cab += f" · replanejada {item['revisoes']}x"
        linhas.append(f"{cab}: {item['texto']}")
        if item.get("nota"):
            linhas.append(f"      nota do usuário: {item['nota']}")
    linhas.append("  Promessa VENCIDA é a que passou do prazo sem baixa — cobre-a "
                  "explicitamente. Não invente promessa que não esteja nesta lista.")
    return "\n".join(linhas)
