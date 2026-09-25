"""Carteiras montadas pela mesa (ou à mão) e seguidas pelo painel.

O desenho segue a regra da casa: número calculado em código, opinião nos
agentes, decisão no usuário. A carteira nasce de uma proposta (da mesa, com
gate humano, ou do formulário), vira um JSON versionável em
`data/carteiras/`, e o acompanhamento é puramente quantitativo — cota base
100 na criação, buy-and-hold entre rebalanceamentos, pesos derivando com o
preço. Quando um peso estoura a banda configurada, o painel ALERTA; quem
rebalanceia é o usuário, com um clique que fica registrado no histórico.

As regras macro/micro que o usuário escreve não disparam ordem nenhuma:
elas são guardadas, aparecem na lâmina e entram no contexto da mesa quando
o research é pedido — condição de mercado é julgamento, e julgamento aqui
sempre passa por gente.

Decisões de robustez (da revisão de arquitetura):
• Escrita protegida por lock de ARQUIVO (flock/msvcrt): o cron roda em outro
  processo que a UI, e read-modify-write sem lock perderia eventos.
• Snapshot histórico é magro (data, cota, retornos, nº de alertas); o
  retrato completo (pesos, preços, alertas) vive só em `atual` — o arquivo
  não incha nem o payload de detalhe carrega megabytes.
• Preço carrega a própria DATA: criar/rebalancear recusam preço velho, e o
  snapshot é rotulado pela data do preço, não pelo dia do relógio — cron de
  sábado não fabrica pregão.
• Benchmark (BOVA11) é buy-and-hold desde a criação, independente de
  rebalanceamentos; se a fonte falhar num dia, a série não morre.
• Datas no fuso de São Paulo, explícito — o container pode estar em UTC.

Tudo fica em `finlab/data/carteiras/` (fora do repositório; na VPS, dentro
do volume `dados_app`, sobrevivendo a rebuild).
"""

from __future__ import annotations

import json
import re
import secrets
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:                                  # Unix: lock de arquivo nativo
    import fcntl as _fcntl
    _msvcrt = None
except ImportError:                   # Windows: o painel também roda local
    _fcntl = None
    import msvcrt as _msvcrt

from . import market, universe
from .settings import DATA_DIR

DIR_CARTEIRAS = DATA_DIR / "carteiras"
BENCHMARK = "BOVA11"
COTA_INICIAL = 100.0
BANDA_PADRAO = 0.05          # 5 p.p. de desvio antes do alerta
MAX_POSICOES = 25
MAX_SNAPSHOTS = 1500         # ~6 anos de pregões; além disso, apara do início
MAX_EVENTOS = 200
MAX_ATRASO_DIAS = 7          # preço mais velho que isso não abre carteira

try:
    _TZ = ZoneInfo("America/Sao_Paulo")
except ZoneInfoNotFoundError:
    # Windows sem o pacote tzdata não tem base de fusos; São Paulo não tem
    # horário de verão desde 2019, então UTC-3 fixo dá a mesma data.
    _TZ = timezone(timedelta(hours=-3))


def _hoje() -> str:
    return datetime.now(_TZ).date().isoformat()


def _agora() -> str:
    return datetime.now(_TZ).isoformat(timespec="seconds")


class CarteiraInvalida(ValueError):
    """Payload que não vira carteira — a mensagem já vem pronta para a tela."""


# ---------------------------------------------------------------------------
# Disco — com lock entre processos (a UI e o cron escrevem no mesmo arquivo)
# ---------------------------------------------------------------------------

def _caminho(carteira_id: str) -> Path:
    # basename barra path traversal vindo de um id torto na URL
    return DIR_CARTEIRAS / (Path(carteira_id).name + ".json")


@contextmanager
def _travado(carteira_id: str):
    """Lock exclusivo por carteira, entre PROCESSOS.

    O uvicorn e o cron (`docker compose exec … tarefas`) são processos
    diferentes: um `threading.Lock` não bastaria. O lock envolve o ciclo
    inteiro ler → mudar → gravar de quem escreve. `flock` no Linux (a VPS),
    `msvcrt.locking` no Windows (o painel rodando no PC).
    """
    DIR_CARTEIRAS.mkdir(parents=True, exist_ok=True)
    trava = DIR_CARTEIRAS / (Path(carteira_id).name + ".lock")
    with trava.open("w") as fh:
        _trava(fh)
        try:
            yield
        finally:
            _destrava(fh)


def _trava(fh) -> None:
    if _fcntl is not None:
        _fcntl.flock(fh, _fcntl.LOCK_EX)
        return
    # LK_LOCK desiste depois de ~10 s; o outro processo segura o lock por
    # milissegundos, então insistir é o certo.
    while True:
        try:
            fh.seek(0)
            _msvcrt.locking(fh.fileno(), _msvcrt.LK_LOCK, 1)
            return
        except OSError:
            continue


def _destrava(fh) -> None:
    if _fcntl is not None:
        _fcntl.flock(fh, _fcntl.LOCK_UN)
        return
    fh.seek(0)
    _msvcrt.locking(fh.fileno(), _msvcrt.LK_UNLCK, 1)


def _gravar(c: dict) -> None:
    caminho = _caminho(c["id"])
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(caminho)   # troca atômica: nunca meia-carteira em disco


def obter(carteira_id: str) -> Optional[dict]:
    caminho = _caminho(carteira_id)
    if not caminho.exists():
        return None
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def listar() -> list[dict]:
    """Resumo de todas as carteiras, mais nova primeiro."""
    if not DIR_CARTEIRAS.exists():
        return []
    fora = []
    for arq in sorted(DIR_CARTEIRAS.glob("*.json")):
        try:
            c = json.loads(arq.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if isinstance(c, dict) and c.get("id"):
            fora.append(_resumo(c))
    fora.sort(key=lambda r: r["criada_em"], reverse=True)
    return fora


def remover(carteira_id: str) -> bool:
    with _travado(carteira_id):
        caminho = _caminho(carteira_id)
        if not caminho.exists():
            return False
        caminho.unlink()
    try:
        (DIR_CARTEIRAS / (Path(carteira_id).name + ".lock")).unlink(missing_ok=True)
    except OSError:
        pass
    return True


def _resumo(c: dict) -> dict:
    atual = c.get("atual") or {}
    return {
        "id": c["id"], "nome": c["nome"], "criada_em": c["criada_em"],
        "mandato": c.get("mandato") or "",
        "origem": c.get("origem") or "manual",
        "n_posicoes": len(c.get("posicoes") or []),
        "cota": atual.get("cota"),
        "retorno": atual.get("retorno"),
        "retorno_bench": atual.get("retorno_bench"),
        "atualizada_em": atual.get("data"),
        "n_alertas": len(atual.get("alertas") or []),
    }


def detalhe(c: dict) -> dict:
    """O payload da página: tudo do estado corrente, série COMPACTA do
    histórico (o arquivo completo fica no disco, não na resposta)."""
    return {
        "id": c["id"], "nome": c["nome"], "criada_em": c["criada_em"],
        "mandato": c.get("mandato") or "",
        "origem": c.get("origem") or "manual",
        "posicoes": c.get("posicoes") or [],
        "regras": c.get("regras") or {},
        "base": {"data": (c.get("base") or {}).get("data")},
        "bench": {"data0": (c.get("bench") or {}).get("data0"),
                  "disponivel": bool((c.get("bench") or {}).get("preco0"))},
        "atual": c.get("atual") or {},
        "serie": [{"data": s["data"], "cota": s["cota"],
                   "retorno_bench": s.get("retorno_bench")}
                  for s in (c.get("snapshots") or [])],
        "eventos": (c.get("eventos") or [])[-50:],
    }


# ---------------------------------------------------------------------------
# Preços com data — a matéria-prima de tudo
# ---------------------------------------------------------------------------

def _ultimo_ponto(pontos: list) -> Optional[dict]:
    if not pontos:
        return None
    d, p = pontos[-1]
    return {"p": float(p), "d": str(d)[:10]}


def _precos_atuais(tickers: list[str], exigir_frescor: bool = False) -> dict[str, dict]:
    """Último preço de cada ticker, COM a data dele.

    As fontes podem devolver defasagens diferentes por papel; guardar a data
    junto é o que impede a cota de misturar hoje com anteontem sem ninguém
    saber. Com `exigir_frescor`, preço mais velho que MAX_ATRASO_DIAS recusa
    a operação — abrir carteira sobre preço de semana passada é abrir outra
    carteira.
    """
    series = market.price_series(tickers)
    precos: dict[str, dict] = {}
    limite = MAX_ATRASO_DIAS
    hoje = datetime.now(_TZ).date()
    for tk in tickers:
        ponto = _ultimo_ponto(series.get(tk) or [])
        if ponto is None:
            raise CarteiraInvalida(
                f"Sem preço disponível para {tk} agora — sem preço de partida "
                "não existe cota para acompanhar. Tente de novo em instantes.")
        if exigir_frescor:
            try:
                idade = (hoje - date.fromisoformat(ponto["d"])).days
            except ValueError:
                idade = None
            if idade is not None and idade > limite:
                raise CarteiraInvalida(
                    f"O preço de {tk} está com {idade} dias ({ponto['d']}) — "
                    "velho demais para abrir posição. Atualize as fontes de "
                    "preço e tente de novo.")
        precos[tk] = ponto
    return precos


def _ponto_benchmark() -> Optional[dict]:
    try:
        return _ultimo_ponto((market.asset_series([BENCHMARK]) or {}).get(BENCHMARK) or [])
    except Exception:
        return None   # sem benchmark a carteira continua funcionando


# ---------------------------------------------------------------------------
# Criação
# ---------------------------------------------------------------------------

def _slug(nome: str) -> str:
    s = unicodedata.normalize("NFD", nome)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "carteira"
    return f"cart-{s}-{secrets.token_hex(2)}"


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) else None


def _normaliza_posicoes(posicoes: list) -> list[dict]:
    """Valida tickers contra o universo e normaliza os pesos para somar 1.

    Peso pode chegar como fração (0.25) ou percentual (25): se a soma passa
    de 3, o payload está em percentual e é dividido por 100 — a mesa escreve
    dos dois jeitos e nenhum deles pode virar uma carteira 100x alavancada.
    """
    if not isinstance(posicoes, list) or not posicoes:
        raise CarteiraInvalida("A carteira precisa de pelo menos uma posição.")
    if len(posicoes) > MAX_POSICOES:
        raise CarteiraInvalida(f"Máximo de {MAX_POSICOES} posições por carteira.")

    limpas, vistos = [], set()
    for p in posicoes:
        tk = str((p or {}).get("ticker") or "").upper().strip()
        peso = _num((p or {}).get("peso"))
        if not tk or peso is None or peso <= 0:
            raise CarteiraInvalida(f"Posição inválida: {p!r} — precisa de ticker "
                                   "e peso positivo.")
        if universe.get(tk) is None:
            raise CarteiraInvalida(
                f"{tk} está fora do universo coberto pelo painel — a carteira "
                "só acompanha o que o painel consegue precificar e fundamentar.")
        if tk in vistos:
            raise CarteiraInvalida(f"{tk} aparece duas vezes na carteira.")
        vistos.add(tk)
        limpas.append({"ticker": tk, "peso": peso,
                       "tese": str((p or {}).get("tese") or "").strip()[:600]})

    soma = sum(p["peso"] for p in limpas)
    if soma > 3:
        for p in limpas:
            p["peso"] /= 100.0
        soma = sum(p["peso"] for p in limpas)
    if not 0.2 <= soma <= 1.8:
        raise CarteiraInvalida(
            f"Os pesos somam {soma:.2f} — muito longe de 100% para ser um "
            "arredondamento. Confira os valores.")
    for p in limpas:
        p["peso"] = round(p["peso"] / soma, 6)
    return limpas


def _normaliza_banda(valor, obrigatoria: bool = False) -> Optional[float]:
    """Banda em fração; aceita p.p. (5 → 0.05). Valor inválido é ERRO, não
    default silencioso — quem digitou 60 precisa saber que 60 não vale."""
    banda = _num(valor)
    if banda is None:
        if obrigatoria:
            raise CarteiraInvalida("Banda de rebalanceamento inválida.")
        return None
    if banda > 1:
        banda = banda / 100.0
    if not 0 < banda <= 0.5:
        raise CarteiraInvalida(
            "Banda de rebalanceamento fora do intervalo: use entre 1 e 50 p.p.")
    return round(banda, 4)


def criar(payload: dict) -> dict:
    """Cria a carteira: valida, captura os preços de partida e o 1º snapshot."""
    payload = payload or {}
    nome = str(payload.get("nome") or "").strip()[:80]
    if not nome:
        raise CarteiraInvalida("Dê um nome à carteira.")

    posicoes = _normaliza_posicoes(payload.get("posicoes"))
    regras_in = payload.get("regras") or {}
    banda = _normaliza_banda(regras_in.get("banda")) if "banda" in regras_in else None
    regras = {
        "banda": banda or BANDA_PADRAO,
        "macro": str(regras_in.get("macro") or "").strip()[:1500],
        "micro": str(regras_in.get("micro") or "").strip()[:1500],
    }

    tickers = [p["ticker"] for p in posicoes]
    precos = _precos_atuais(tickers, exigir_frescor=True)
    bench = _ponto_benchmark()
    hoje = _hoje()

    c = {
        "id": _slug(nome),
        "nome": nome,
        "mandato": str(payload.get("mandato") or "").strip()[:800],
        "origem": "mesa" if payload.get("origem") == "mesa" else "manual",
        "criada_em": hoje,
        "posicoes": posicoes,
        "regras": regras,
        "base": {"data": hoje, "precos": precos, "cota_base": COTA_INICIAL},
        # Benchmark buy-and-hold desde a criação, independente de
        # rebalanceamentos — é a comparação honesta com "ter comprado o
        # índice no mesmo dia". Sem fonte agora, fica sem benchmark e o
        # primeiro update que o encontrar abre a série DECLARANDO a data.
        "bench": {"preco0": bench["p"], "data0": bench["d"]} if bench else {},
        "snapshots": [],
        "eventos": [{"data": _agora(), "tipo": "criacao",
                     "texto": f"Carteira criada com {len(posicoes)} posições "
                              f"({'proposta da mesa, aprovada pelo usuário' if payload.get('origem') == 'mesa' else 'montagem manual'})."}],
    }
    _snapshot(c, precos, bench)
    with _travado(c["id"]):
        _gravar(c)
    return c


# ---------------------------------------------------------------------------
# Acompanhamento — a parte que o cron roda
# ---------------------------------------------------------------------------

def _snapshot(c: dict, precos: dict[str, dict], bench: Optional[dict],
              avisos_extras: Optional[list[str]] = None) -> dict:
    """Recalcula o estado corrente e anexa o ponto do dia à série.

    Buy-and-hold desde o último rebalanceamento: o valor de cada posição
    cresce com o preço, os PESOS derivam, e a cota é a soma — exatamente o
    que aconteceria com uma carteira real sem novos aportes.

    O retrato completo (pesos, preços, retornos, alertas) fica em `atual`;
    a série histórica guarda só o essencial, para o arquivo não incrementar
    megabytes por semana de uso.
    """
    base = c["base"]
    valor = 0.0
    valores_pos = {}
    for p in c["posicoes"]:
        tk = p["ticker"]
        p0 = (base["precos"].get(tk) or {}).get("p")
        p1 = (precos.get(tk) or {}).get("p")
        v = p["peso"] * (p1 / p0) if p0 and p1 else p["peso"]
        valores_pos[tk] = v
        valor += v

    cota = round(base["cota_base"] * valor, 4)
    pesos_atuais = {tk: round(v / valor, 6) for tk, v in valores_pos.items()}
    retornos_pos = {}
    for p in c["posicoes"]:
        tk = p["ticker"]
        p0 = (base["precos"].get(tk) or {}).get("p")
        p1 = (precos.get(tk) or {}).get("p")
        if p0 and p1:
            retornos_pos[tk] = round(p1 / p0 - 1, 6)

    banda = c["regras"].get("banda") or BANDA_PADRAO
    alertas = []
    for p in c["posicoes"]:
        drift = pesos_atuais.get(p["ticker"], p["peso"]) - p["peso"]
        if abs(drift) > banda:
            alertas.append(f"{p['ticker']}: peso {pesos_atuais[p['ticker']]:.1%} "
                           f"vs alvo {p['peso']:.1%} — fora da banda de "
                           f"{banda * 100:.0f} p.p.")

    # Benchmark: série própria, ancorada na criação. Fonte falhou hoje →
    # ponto sem benchmark; a âncora nunca é tocada, então amanhã volta.
    if bench and not (c.get("bench") or {}).get("preco0"):
        c["bench"] = {"preco0": bench["p"], "data0": bench["d"]}
        _evento(c, "benchmark", f"Série do {BENCHMARK} iniciada em {bench['d']} "
                                "(indisponível na criação).")
    retorno_bench = None
    ancora = (c.get("bench") or {}).get("preco0")
    if bench and ancora:
        retorno_bench = round(bench["p"] / ancora - 1, 6)

    # A data do snapshot é a do PREÇO mais novo, não a do relógio: rodar o
    # cron no sábado substitui o ponto de sexta em vez de inventar pregão.
    datas = sorted(v["d"] for v in precos.values())
    data_snap = datas[-1] if datas else _hoje()

    # Avisos de qualidade de dado — não são alertas de banda, são o painel
    # dizendo em que o número desta rodada é menos confiável.
    avisos = list(avisos_extras or [])
    if datas and datas[0] != datas[-1]:
        avisos.append(f"Preços com datas misturadas ({datas[0]} a {datas[-1]}) "
                      "— fontes defasadas entre papéis.")
    precos_prev = (c.get("atual") or {}).get("precos") or {}
    for tk, v in precos.items():
        anterior = precos_prev.get(tk)
        if anterior and abs(v["p"] / anterior - 1) > 0.30:
            avisos.append(f"{tk} variou {v['p'] / anterior - 1:+.0%} num dia — "
                          "possível split/evento societário: confira e, se for "
                          "o caso, rebalanceie para reancorar a base.")
    if (c.get("bench") or {}).get("preco0") and not bench:
        avisos.append(f"{BENCHMARK} indisponível nesta rodada — comparação "
                      "congelada no último ponto.")

    c["atual"] = {
        "data": data_snap,
        "cota": cota,
        "retorno": round(cota / COTA_INICIAL - 1, 6),
        "retorno_bench": retorno_bench,
        "pesos": pesos_atuais,
        "retornos": retornos_pos,
        "precos": {tk: v["p"] for tk, v in precos.items()},
        "datas_precos": {tk: v["d"] for tk, v in precos.items()},
        "alertas": alertas,
        "avisos": avisos,
    }

    ponto = {"data": data_snap, "cota": cota,
             "retorno": c["atual"]["retorno"],
             "retorno_bench": retorno_bench,
             "n_alertas": len(alertas)}
    snaps = c.setdefault("snapshots", [])
    if snaps and snaps[-1]["data"] == ponto["data"]:
        snaps[-1] = ponto
    else:
        snaps.append(ponto)
    if len(snaps) > MAX_SNAPSHOTS:
        del snaps[: len(snaps) - MAX_SNAPSHOTS]
    return c["atual"]


def _precos_para_update(c: dict, fonte: dict[str, Optional[dict]]) -> tuple[dict, list[str]]:
    """Preços para uma atualização: papel sem preço novo fica CONGELADO no
    último conhecido, com aviso — uma OPA ou deslistamento não pode fazer a
    carteira inteira falhar todo dia para sempre."""
    precos, avisos = {}, []
    ultimo = (c.get("atual") or {}).get("precos") or {}
    datas_ultimo = (c.get("atual") or {}).get("datas_precos") or {}
    for p in c["posicoes"]:
        tk = p["ticker"]
        ponto = fonte.get(tk)
        if ponto is None:
            if ultimo.get(tk) is not None:
                congelado = {"p": ultimo[tk],
                             "d": datas_ultimo.get(tk, c["base"]["data"])}
            else:
                congelado = c["base"]["precos"].get(tk)
            if not congelado:
                raise CarteiraInvalida(f"Sem preço algum para {tk}.")
            precos[tk] = congelado
            avisos.append(f"Sem preço novo para {tk} — posição congelada no "
                          f"último preço ({congelado['d']}). Se o papel saiu "
                          "de negociação, edite a carteira.")
        else:
            precos[tk] = ponto
    return precos, avisos


def atualizar(carteira_id: str) -> dict:
    """Busca preços frescos e grava o snapshot — o que o cron chama."""
    with _travado(carteira_id):
        c = obter(carteira_id)
        if c is None:
            raise KeyError(carteira_id)
        tickers = [p["ticker"] for p in c["posicoes"]]
        series = market.price_series(tickers)
        fonte = {tk: _ultimo_ponto(series.get(tk) or []) for tk in tickers}
        precos, avisos = _precos_para_update(c, fonte)
        _snapshot(c, precos, _ponto_benchmark(), avisos)
        _gravar(c)
    return c


def atualizar_todas() -> list[dict]:
    """Atualiza cada carteira isoladamente — uma falhar não derruba as outras.

    Os preços são buscados UMA vez para a união dos tickers de todas as
    carteiras (dez carteiras com WEGE3 não são dez chamadas de rede).
    """
    resumos = listar()
    if not resumos:
        return []

    todos: set[str] = set()
    for r in resumos:
        c = obter(r["id"])
        if c:
            todos.update(p["ticker"] for p in c.get("posicoes") or [])
    series = market.price_series(sorted(todos)) if todos else {}
    precos_globais = {tk: _ultimo_ponto(series.get(tk) or []) for tk in todos}
    bench = _ponto_benchmark()

    saida = []
    for r in resumos:
        try:
            with _travado(r["id"]):
                c = obter(r["id"])
                if c is None:
                    continue   # removida entre o listar e agora
                precos, avisos = _precos_para_update(c, precos_globais)
                _snapshot(c, precos, bench, avisos)
                _gravar(c)
            saida.append({"id": c["id"], "nome": c["nome"], "ok": True,
                          "cota": c["atual"]["cota"],
                          "alertas": c["atual"]["alertas"]})
        except Exception as exc:   # noqa: BLE001 — o relato é o produto
            saida.append({"id": r["id"], "nome": r["nome"],
                          "ok": False, "erro": str(exc)})
    return saida


# ---------------------------------------------------------------------------
# Mudanças com histórico
# ---------------------------------------------------------------------------

def _evento(c: dict, tipo: str, texto: str) -> None:
    eventos = c.setdefault("eventos", [])
    eventos.append({"data": _agora(), "tipo": tipo, "texto": texto})
    if len(eventos) > MAX_EVENTOS:
        del eventos[: len(eventos) - MAX_EVENTOS]


def _rebase(c: dict, precos: dict[str, dict]) -> None:
    """Base nova nos preços de agora com a COTA contínua — a mecânica de um
    rebalanceamento real: vende o que passou do alvo, compra o que faltou."""
    cota_atual = (c.get("atual") or {}).get("cota") or COTA_INICIAL
    c["base"] = {"data": _hoje(), "precos": precos, "cota_base": cota_atual}


def rebalancear(carteira_id: str) -> dict:
    """Volta os pesos aos alvos, com a cota contínua e o evento registrado."""
    with _travado(carteira_id):
        c = obter(carteira_id)
        if c is None:
            raise KeyError(carteira_id)
        precos = _precos_atuais([p["ticker"] for p in c["posicoes"]],
                                exigir_frescor=True)
        bench = _ponto_benchmark()
        _snapshot(c, precos, bench)          # marca o estado pré-rebalance
        _rebase(c, precos)
        _evento(c, "rebalanceamento",
                f"Pesos devolvidos aos alvos com a cota em "
                f"{c['atual']['cota']:.2f}.")
        _snapshot(c, precos, bench)          # estado pós: pesos = alvos
        _gravar(c)
    return c


def editar(carteira_id: str, payload: dict) -> dict:
    """Nome, mandato, regras e pesos-alvo. Mudar pesos rebalanceia na hora:
    alvo novo com base velha seria uma carteira que nunca existiu."""
    payload = payload or {}
    with _travado(carteira_id):
        c = obter(carteira_id)
        if c is None:
            raise KeyError(carteira_id)

        if payload.get("nome"):
            c["nome"] = str(payload["nome"]).strip()[:80]
        if "mandato" in payload:
            c["mandato"] = str(payload.get("mandato") or "").strip()[:800]
        if isinstance(payload.get("regras"), dict):
            r = payload["regras"]
            if "banda" in r:
                c["regras"]["banda"] = _normaliza_banda(r.get("banda"),
                                                        obrigatoria=True)
            for chave in ("macro", "micro"):
                if chave in r:
                    c["regras"][chave] = str(r.get(chave) or "").strip()[:1500]
            _evento(c, "regras", "Regras da carteira atualizadas.")

        if "posicoes" in payload:
            # Presente e vazio é erro declarado, não um "nada a fazer": quem
            # mandou uma lista vazia acha que esvaziou a carteira.
            novas = _normaliza_posicoes(payload["posicoes"])
            antigos = [p["ticker"] for p in c["posicoes"]]
            uniao = sorted({*antigos, *(p["ticker"] for p in novas)})
            precos = _precos_atuais(uniao, exigir_frescor=True)
            bench = _ponto_benchmark()
            # A cota anda até AGORA com a composição antiga antes da troca —
            # congelar no último snapshot apagaria o movimento desde então.
            _snapshot(c, {tk: precos[tk] for tk in antigos}, bench)
            c["posicoes"] = novas
            _rebase(c, {p["ticker"]: precos[p["ticker"]] for p in novas})
            _evento(c, "pesos", f"Composição alterada para {len(novas)} "
                                "posições; base rebalanceada nos preços de agora.")
            _snapshot(c, {p["ticker"]: precos[p["ticker"]] for p in novas}, bench)

        _gravar(c)
    return c


# ---------------------------------------------------------------------------
# Lâmina — o relatório quantitativo, sem LLM
# ---------------------------------------------------------------------------

def _pct(v, casas: int = 1) -> str:
    return f"{v * 100:+.{casas}f}%".replace(".", ",") if isinstance(v, (int, float)) else "—"


def _dmy(iso: str) -> str:
    try:
        return date.fromisoformat(str(iso)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return str(iso)


def metricas_da_serie(snaps: list[dict]) -> dict:
    """Volatilidade anualizada e drawdown máximo da série de cotas.

    Só com o que a série diária dá honestamente: menos de ~20 pontos não
    sustenta volatilidade, e o campo sai None em vez de sair ruído.
    """
    cotas = [s["cota"] for s in snaps if isinstance(s.get("cota"), (int, float))]
    out = {"vol_anualizada": None, "drawdown_max": None}
    if len(cotas) >= 2:
        pico, dd = cotas[0], 0.0
        for cq in cotas:
            pico = max(pico, cq)
            dd = min(dd, cq / pico - 1)
        out["drawdown_max"] = round(dd, 6)
    if len(cotas) >= 20:
        rets = [cotas[i] / cotas[i - 1] - 1 for i in range(1, len(cotas))]
        media = sum(rets) / len(rets)
        var = sum((r - media) ** 2 for r in rets) / (len(rets) - 1)
        out["vol_anualizada"] = round((var ** 0.5) * (252 ** 0.5), 6)
    return out


def janelas_de_retorno(snaps: list[dict]) -> list[dict]:
    """Retorno em janelas padronizadas (mês, ano, 12 meses), carteira × bench.

    Cada janela parte do último snapshot ANTERIOR ao corte; se a série ainda
    não cobre a janela, o valor sai None em vez de fingir uma janela cheia
    com menos dias — retorno "no ano" de uma carteira de duas semanas seria
    só o retorno desde o início com outro rótulo.
    """
    if not snaps:
        return []
    ultimo = snaps[-1]
    try:
        fim = date.fromisoformat(str(ultimo["data"])[:10])
    except ValueError:
        return []

    def ponto_ate(corte: date) -> Optional[dict]:
        achado = None
        for s in snaps:
            try:
                d = date.fromisoformat(str(s["data"])[:10])
            except ValueError:
                continue
            if d <= corte:
                achado = s
            else:
                break
        return achado

    cortes = [("No mês", fim.replace(day=1) - timedelta(days=1)),
              ("No ano", date(fim.year - 1, 12, 31)),
              ("12 meses", fim - timedelta(days=365))]
    saida = []
    for nome, corte in cortes:
        ini = ponto_ate(corte)
        cart = bench = None
        if ini is not None and ini is not ultimo:
            c0, c1 = ini.get("cota"), ultimo.get("cota")
            if isinstance(c0, (int, float)) and isinstance(c1, (int, float)) and c0:
                cart = round(c1 / c0 - 1, 6)
            b0, b1 = ini.get("retorno_bench"), ultimo.get("retorno_bench")
            if isinstance(b0, (int, float)) and isinstance(b1, (int, float)):
                bench = round((1 + b1) / (1 + b0) - 1, 6)
        saida.append({"nome": nome, "carteira": cart, "bench": bench})
    return saida


def lamina_md(c: dict) -> str:
    """A lâmina da carteira: número calculado aqui, tese guardada na criação.

    Nenhum modelo de linguagem participa — é o relatório que o cron pode
    gerar sozinho, sem chave de API nenhuma.
    """
    atual = c.get("atual") or {}
    snaps = c.get("snapshots") or []
    pesos = atual.get("pesos") or {}
    rets = atual.get("retornos") or {}
    banda = c["regras"].get("banda") or BANDA_PADRAO
    met = metricas_da_serie(snaps)

    L = [f"# {c['nome']} · lâmina da carteira", ""]
    L.append(f"Gerada pelo FinLab em {datetime.now(_TZ).strftime('%d/%m/%Y')} · "
             f"carteira criada em {_dmy(c['criada_em'])} · origem: "
             f"{'mesa de IA (aprovada pelo usuário)' if c.get('origem') == 'mesa' else 'montagem manual'}")
    L.append("")
    if c.get("mandato"):
        L.append(f"**Mandato:** {c['mandato']}")
        L.append("")

    L.append("## Desempenho")
    L.append("")
    L.append(f"- Cota: **{atual.get('cota', COTA_INICIAL):.2f}** (base 100 em "
             f"{_dmy(c['criada_em'])})")
    L.append(f"- Retorno desde o início: **{_pct(atual.get('retorno'))}**")
    if atual.get("retorno_bench") is not None:
        dif = (atual.get("retorno") or 0) - atual["retorno_bench"]
        d0 = (c.get("bench") or {}).get("data0") or c["criada_em"]
        L.append(f"- {BENCHMARK} desde {_dmy(d0)}: {_pct(atual['retorno_bench'])} "
                 f"→ diferença de **{_pct(dif)}**")
    jans = janelas_de_retorno(snaps)
    if any(j["carteira"] is not None for j in jans):
        partes = []
        for j in jans:
            if j["carteira"] is None:
                continue
            trecho = f"{j['nome'].lower()}: {_pct(j['carteira'])}"
            if j["bench"] is not None:
                trecho += f" (vs {_pct(j['bench'])} do {BENCHMARK})"
            partes.append(trecho)
        L.append(f"- Janelas — {' · '.join(partes)}")
    if met["drawdown_max"] is not None:
        L.append(f"- Drawdown máximo: {_pct(met['drawdown_max'])}")
    if met["vol_anualizada"] is not None:
        L.append(f"- Volatilidade anualizada (diária, últimos {len(snaps)} "
                 f"pontos): {met['vol_anualizada'] * 100:.1f}%".replace(".", ","))
    L.append(f"- Última atualização: {_dmy(atual.get('data', ''))} · "
             f"{len(snaps)} ponto(s) na série")
    L.append("")

    L.append("## Posições")
    L.append("")
    L.append("| Ticker | Peso alvo | Peso atual | Desvio | Retorno* | Contribuição* |")
    L.append("|---|---|---|---|---|---|")
    for p in sorted(c["posicoes"], key=lambda x: -x["peso"]):
        tk = p["ticker"]
        pa = pesos.get(tk)
        drift = (pa - p["peso"]) if isinstance(pa, (int, float)) else None
        marca = " ⚠" if isinstance(drift, (int, float)) and abs(drift) > banda else ""
        ret = rets.get(tk)
        contrib = p["peso"] * ret if isinstance(ret, (int, float)) else None
        L.append(f"| {tk} | {p['peso'] * 100:.1f}% | "
                 + (f"{pa * 100:.1f}%" if isinstance(pa, (int, float)) else "—")
                 + f" | {_pct(drift) if drift is not None else '—'}{marca} | "
                 + f"{_pct(ret)} | {_pct(contrib, 2)} |")
    L.append("")
    L.append(f"*\\* retorno e contribuição (peso alvo × retorno, em p.p. da "
             f"cota) desde o último rebalanceamento ({_dmy(c['base']['data'])}).*")
    L.append("")

    alertas = atual.get("alertas") or []
    L.append("## Regras e estado")
    L.append("")
    L.append(f"- Banda de rebalanceamento: {banda * 100:.0f} p.p. — "
             + (f"**{len(alertas)} posição(ões) fora da banda**" if alertas
                else "todas as posições dentro da banda"))
    for a in alertas:
        L.append(f"  - ⚠ {a}")
    if c["regras"].get("macro"):
        L.append(f"- Condições macro a observar: {c['regras']['macro']}")
    if c["regras"].get("micro"):
        L.append(f"- Condições micro a observar: {c['regras']['micro']}")
    L.append("")

    teses = [p for p in c["posicoes"] if p.get("tese")]
    if teses:
        L.append("## Resumo das teses")
        L.append("")
        for p in sorted(teses, key=lambda x: -x["peso"]):
            L.append(f"- **{p['ticker']}** ({p['peso'] * 100:.1f}%): {p['tese']}")
        L.append("")

    eventos = (c.get("eventos") or [])[-8:]
    if eventos:
        L.append("## Últimos eventos")
        L.append("")
        for e in reversed(eventos):
            L.append(f"- {_dmy(e['data'])} · {e['tipo']}: {e['texto']}")
        L.append("")

    L.append("---")
    L.append("*Cota simulada buy-and-hold entre rebalanceamentos, sem custos "
             "nem impostos, e SEM proventos — dividendos pagos não entram na "
             f"cota, enquanto o {BENCHMARK} os embute (o ETF reinveste "
             "internamente): a comparação com o benchmark subestima a "
             "carteira, e mais ainda se ela for de dividendos. "
             "Rebalanceamentos são executados sem custo nos preços "
             "observados. As regras macro/micro são anotações de "
             "acompanhamento — nada dispara ordem. Isto não é recomendação "
             "de investimento.*")
    return "\n".join(L)
