"""Lâmina da carteira em PDF.

Os mesmos números da lâmina em markdown (`carteiras.lamina_md`), diagramados
como um material de apresentação: cabeçalho com a marca, indicadores, gráfico
da cota contra o BOVA11, posições com barras de peso, teses, regras e
histórico. HTML + CSS convertidos em PDF pelo WeasyPrint, no próprio painel —
sem navegador, sem serviço externo, e nenhum modelo de linguagem participa.
"""

from __future__ import annotations

import base64
from datetime import date, datetime
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Optional

from . import bdrs, carteiras, etfs

DIR = Path(__file__).resolve().parent / "lamina"

# Paleta: a do painel, em versão para papel (fundo claro, tinta escura).
TINTA = "#0B1222"
CIANO = "#0891B2"        # ciano do painel escurecido: legível no branco
VIOLETA = "#7C3AED"
VERDE = "#059669"
VERMELHO = "#DC2626"
AMBAR = "#B45309"
CINZA = "#64748B"


# ---------------------------------------------------------------------------
# Formatação pt-BR
# ---------------------------------------------------------------------------

def _num(v: Optional[float], casas: int = 2) -> str:
    if not isinstance(v, (int, float)):
        return "—"
    txt = f"{v:,.{casas}f}"
    return txt.replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(v: Optional[float], casas: int = 1, sinal: bool = True) -> str:
    if not isinstance(v, (int, float)):
        return "—"
    if abs(v) < 0.5 * 10 ** -(casas + 2):
        v = 0.0                      # "-0,0%" não existe
    txt = _num(abs(v) * 100, casas) + "%"
    if not sinal:
        return ("-" if v < 0 else "") + txt
    return ("+" if v >= 0 else "−") + txt


def _pp(v: Optional[float], casas: int = 1) -> str:
    """Diferença em pontos percentuais."""
    if not isinstance(v, (int, float)):
        return "—"
    return _pct(v, casas).replace("%", " p.p.")


def _cor(v: Optional[float]) -> str:
    if not isinstance(v, (int, float)) or abs(v) < 5e-5:
        return CINZA
    return VERDE if v > 0 else VERMELHO


def _data(iso: str) -> str:
    try:
        return date.fromisoformat(str(iso)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return str(iso)


def _e(txt) -> str:
    return escape(str(txt or ""))


def _tipo(ticker: str) -> str:
    if bdrs.get(ticker):
        return "BDR"
    try:
        if etfs.get(ticker):
            return "ETF"
    except Exception:
        pass
    return "AÇÃO"


TIPOS_DE_EVENTO = {"criacao": "criação", "pesos": "composição", "regras": "regras",
                   "rebalanceamento": "rebalanceamento", "benchmark": "benchmark"}


# ---------------------------------------------------------------------------
# Recursos embutidos (fonte, marca)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _fontes_css() -> str:
    regras = []
    for peso in (400, 600, 700, 800):
        b64 = base64.b64encode((DIR / f"Inter-{peso}.ttf").read_bytes()).decode()
        regras.append(f"@font-face{{font-family:'Inter';font-weight:{peso};"
                      f"src:url(data:font/ttf;base64,{b64}) format('truetype')}}")
    return "\n".join(regras)


@lru_cache(maxsize=1)
def _marca() -> str:
    return "data:image/png;base64," + base64.b64encode((DIR / "marca.png").read_bytes()).decode()


@lru_cache(maxsize=1)
def _wordmark(cor_a: str = "#67E8F9", cor_b: str = "#A78BFA") -> str:
    svg = (DIR / "wordmark.svg").read_text(encoding="utf-8")
    vb = svg.split('viewBox="')[1].split('"')[0]
    d = svg.split(' d="')[1].split('"')[0]
    x, _y, w, _h = (float(n) for n in vb.split())
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" class="wordmark">'
            f'<defs><linearGradient id="wm" gradientUnits="userSpaceOnUse" x1="{x}" y1="0" '
            f'x2="{x + w}" y2="0"><stop offset="0" stop-color="{cor_a}"/>'
            f'<stop offset="0.55" stop-color="#C4B5FD"/><stop offset="1" stop-color="{cor_b}"/>'
            f'</linearGradient></defs><path d="{d}" fill="url(#wm)"/></svg>')


# ---------------------------------------------------------------------------
# Gráfico da cota × benchmark (SVG desenhado aqui, sem biblioteca)
# ---------------------------------------------------------------------------

def _escala(lo: float, hi: float, n: int = 4) -> list[float]:
    """Marcas "redondas" do eixo (passo 1, 2, 2,5 ou 5 × potência de 10)."""
    import math
    if hi - lo < 1e-9:
        lo, hi = lo - 1, hi + 1
    bruto = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(bruto))
    passo = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= bruto - 1e-12)
    ini = math.floor(lo / passo) * passo
    marcas = [round(ini + k * passo, 6) for k in range(int(math.ceil((hi - ini) / passo - 1e-9)) + 1)]
    return marcas


def _grafico(snaps: list[dict], larg: float = 470, alt: float = 190) -> str:
    pontos = [(s["data"], s["cota"], s.get("retorno_bench")) for s in snaps
              if isinstance(s.get("cota"), (int, float))]
    if len(pontos) < 2:
        return ('<div class="sem-grafico">A série começa com a próxima atualização '
                'diária — o gráfico aparece a partir do segundo ponto.</div>')
    cotas = [p[1] for p in pontos]
    bench = [100 * (1 + p[2]) if isinstance(p[2], (int, float)) else None for p in pontos]
    valores = cotas + [b for b in bench if b is not None] + [100.0]
    marcas = _escala(min(valores), max(valores))
    lo, hi = marcas[0], marcas[-1]
    esq, dir_, topo, base = 40, 8, 8, 26
    w, h = larg - esq - dir_, alt - topo - base
    n = len(pontos)
    X = lambda i: esq + (w * i / (n - 1))
    Y = lambda v: topo + h * (1 - (v - lo) / (hi - lo))

    partes = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {larg} {alt}" class="grafico">',
              '<defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1">'
              f'<stop offset="0" stop-color="{CIANO}" stop-opacity="0.22"/>'
              f'<stop offset="1" stop-color="{CIANO}" stop-opacity="0"/></linearGradient>'
              f'<linearGradient id="linha" gradientUnits="userSpaceOnUse" x1="{esq}" y1="0" x2="{esq + w}" y2="0">'
              f'<stop offset="0" stop-color="{CIANO}"/><stop offset="1" stop-color="{VIOLETA}"/>'
              '</linearGradient></defs>']
    for m in marcas:
        y = Y(m)
        forte = abs(m - 100) < 1e-9
        tracejado = ' stroke-dasharray="3 3"' if forte else ""
        partes.append(f'<line x1="{esq}" x2="{esq + w}" y1="{y:.1f}" y2="{y:.1f}" '
                      f'stroke="{"#94A3B8" if forte else "#E2E8F0"}" stroke-width="{0.8 if forte else 0.6}"'
                      f'{tracejado}/>')
        partes.append(f'<text x="{esq - 6}" y="{y + 3:.1f}" text-anchor="end" font-family="Inter" font-size="10" fill="#94A3B8">{_num(m, 0 if m == int(m) else 1)}</text>')
    # datas: primeira, meio e última
    for i in sorted({0, (n - 1) // 2, n - 1}):
        ancora = "start" if i == 0 else "end" if i == n - 1 else "middle"
        partes.append(f'<text x="{X(i):.1f}" y="{alt - 6}" text-anchor="{ancora}" font-family="Inter" font-size="10" fill="#94A3B8">'
                      f'{_data(pontos[i][0])[:5]}</text>')
    linha = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(cotas))
    partes.append(f'<polygon points="{X(0):.1f},{topo + h:.1f} {linha} {X(n - 1):.1f},{topo + h:.1f}" fill="url(#area)"/>')
    segs, atual = [], []
    for i, v in enumerate(bench):
        if v is None:
            if len(atual) > 1:
                segs.append(atual)
            atual = []
        else:
            atual.append(f"{X(i):.1f},{Y(v):.1f}")
    if len(atual) > 1:
        segs.append(atual)
    for s in segs:
        partes.append(f'<polyline points="{" ".join(s)}" fill="none" stroke="#94A3B8" '
                      'stroke-width="1.4" stroke-dasharray="4 3" stroke-linejoin="round"/>')
    partes.append(f'<polyline points="{linha}" fill="none" stroke="url(#linha)" stroke-width="2.2" '
                  'stroke-linejoin="round" stroke-linecap="round"/>')
    partes.append(f'<circle cx="{X(n - 1):.1f}" cy="{Y(cotas[-1]):.1f}" r="3.2" fill="{VIOLETA}" '
                  'stroke="#fff" stroke-width="1.4"/>')
    partes.append("</svg>")
    return "".join(partes)


# ---------------------------------------------------------------------------
# Documento
# ---------------------------------------------------------------------------

CSS = f"""
@page {{
  size: A4; margin: 14mm 13mm 16mm 13mm;
  @bottom-left {{ content: "FinLab · lâmina da carteira · não é recomendação de investimento";
                 font: 400 6.6pt 'Inter'; color: #94A3B8; }}
  @bottom-right {{ content: "página " counter(page) " de " counter(pages);
                  font: 400 6.6pt 'Inter'; color: #94A3B8; }}
}}
* {{ box-sizing: border-box; }}
html {{ font-family: 'Inter'; font-size: 8.6pt; color: {TINTA}; line-height: 1.45;
        font-feature-settings: 'tnum' 1, 'kern' 1; }}
body {{ margin: 0; }}
h2 {{ font: 800 7pt 'Inter'; letter-spacing: .16em; text-transform: uppercase; color: {CIANO};
      margin: 0 0 6pt; display: flex; align-items: center; }}
h2::after {{ content: ""; flex: 1; height: 0.6pt; background: #E2E8F0; margin-left: 8pt; }}
section {{ margin-top: 13pt; }}

/* ---------- cabeçalho ---------- */
.capa {{ margin: -14mm -13mm 0; padding: 11mm 13mm 9mm; color: #E6ECF5;
         background: linear-gradient(135deg, #070B14 0%, #0E1A33 58%, #1B1640 100%);
         position: relative; }}
.capa .topo {{ display: flex; align-items: center; justify-content: space-between; }}
.marca {{ display: flex; align-items: center; gap: 7pt; }}
.marca img {{ width: 34pt; height: 34pt; }}
.wordmark {{ height: 15pt; width: auto; }}
.selo {{ font: 700 6.4pt 'Inter'; letter-spacing: .22em; text-transform: uppercase; color: #8FD8FB;
         border: 0.6pt solid rgba(143,216,251,.45); border-radius: 20pt; padding: 3pt 9pt; }}
.capa h1 {{ font: 800 21pt/1.12 'Inter'; letter-spacing: -.015em; margin: 13pt 0 4pt; color: #fff; }}
.capa .meta {{ font-size: 7.6pt; color: #9FB0CC; }}
.capa .meta b {{ color: #DDE6F3; font-weight: 600; }}
.mandato {{ margin-top: 9pt; padding: 7pt 10pt; border-left: 2pt solid #67E8F9;
            background: rgba(103,232,249,.07); color: #C9D5E6; font-size: 7.6pt; line-height: 1.5;
            border-radius: 0 4pt 4pt 0; }}
.mandato b {{ color: #67E8F9; font-weight: 700; letter-spacing: .08em; font-size: 6.4pt;
              text-transform: uppercase; margin-right: 4pt; }}

/* ---------- indicadores ---------- */
.kpis {{ display: flex; gap: 6pt; margin-top: 12pt; }}
.kpi {{ flex: 1; border: 0.6pt solid #E2E8F0; border-radius: 6pt; padding: 7pt 9pt 8pt;
        background: #F8FAFC; }}
.kpi .r {{ font: 700 6.2pt 'Inter'; letter-spacing: .12em; text-transform: uppercase; color: {CINZA}; }}
.kpi .v {{ font: 800 15pt/1.15 'Inter'; letter-spacing: -.01em; margin-top: 3pt; }}
.kpi .s {{ font-size: 6.8pt; color: {CINZA}; margin-top: 2pt; }}
.kpi.destaque {{ background: linear-gradient(160deg, #ECFEFF 0%, #F5F3FF 100%); border-color: #C7D2FE; }}

/* ---------- gráfico + janelas ---------- */
.linha2 {{ display: flex; gap: 12pt; align-items: stretch; }}
.linha2 .graf {{ flex: 1.75; }}
.linha2 .lado {{ flex: 1; }}
.grafico {{ width: 100%; height: auto; }}
.legenda {{ display: flex; gap: 12pt; font-size: 6.8pt; color: {CINZA}; margin-top: 2pt; }}
.legenda i {{ display: inline-block; width: 12pt; height: 2pt; vertical-align: middle; margin-right: 4pt;
              border-radius: 2pt; }}
.sem-grafico {{ border: 0.6pt dashed #CBD5E1; border-radius: 6pt; padding: 22pt 14pt; color: {CINZA};
                text-align: center; font-size: 7.6pt; }}
table {{ width: 100%; border-collapse: collapse; }}
.janelas td, .janelas th {{ padding: 4.5pt 0; border-bottom: 0.6pt solid #EEF2F7; }}
.janelas th {{ font: 700 6.2pt 'Inter'; letter-spacing: .1em; text-transform: uppercase; color: {CINZA};
               text-align: right; }}
.janelas th:first-child, .janelas td:first-child {{ text-align: left; }}
.janelas td {{ text-align: right; font-weight: 600; }}
.estat {{ margin-top: 8pt; font-size: 7pt; color: {CINZA}; line-height: 1.7; }}
.estat b {{ color: {TINTA}; font-weight: 700; }}

/* ---------- posições ---------- */
.pos th {{ font: 700 6.1pt 'Inter'; letter-spacing: .1em; text-transform: uppercase; color: {CINZA};
           text-align: right; padding: 0 0 5pt 6pt; border-bottom: 0.9pt solid {TINTA}; }}
.pos td {{ text-align: right; padding: 5.2pt 0 5.2pt 6pt; border-bottom: 0.6pt solid #EEF2F7;
           vertical-align: middle; white-space: nowrap; }}
.pos th:first-child, .pos td:first-child {{ text-align: left; padding-left: 0; }}
.pos tr:nth-child(even) td {{ background: #FAFBFD; }}
.tk {{ font-weight: 800; font-size: 8.8pt; letter-spacing: .01em; }}
.tipo {{ font: 700 5.4pt 'Inter'; letter-spacing: .08em; color: {CINZA}; background: #EEF2F7;
         border-radius: 3pt; padding: 1pt 3.5pt; margin-left: 4pt; vertical-align: 1pt; }}
.peso {{ display: flex; align-items: center; justify-content: flex-end; gap: 5pt; }}
.barra {{ width: 46pt; height: 4.4pt; background: #EEF2F7; border-radius: 3pt; overflow: hidden; }}
.barra i {{ display: block; height: 100%; border-radius: 3pt;
            background: linear-gradient(90deg, {CIANO}, {VIOLETA}); }}
.forte {{ font-weight: 700; }}
.num {{ display: inline-block; min-width: 31pt; text-align: right; }}
.alvo-ok {{ font: 700 5.6pt 'Inter'; letter-spacing: .06em; text-transform: uppercase; color: {AMBAR};
            background: #FEF3C7; border-radius: 3pt; padding: 1pt 3.5pt; margin-left: 4pt; }}
.nota {{ font-size: 6.6pt; color: {CINZA}; margin-top: 5pt; }}
.fora {{ color: {AMBAR}; font-weight: 700; }}

/* ---------- teses ---------- */
.teses {{ display: flex; flex-wrap: wrap; gap: 6pt; }}
.tese {{ width: calc(50% - 3pt); border: 0.6pt solid #E2E8F0; border-radius: 6pt; padding: 7pt 9pt;
         break-inside: avoid; }}
.tese .cab {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 3pt; }}
.tese .cab .w {{ font: 700 6.6pt 'Inter'; color: {VIOLETA}; }}
.tese p {{ margin: 0; font-size: 7.5pt; color: #334155; line-height: 1.5; }}

/* ---------- regras e eventos ---------- */
.duas {{ display: flex; gap: 14pt; }}
.duas > div {{ flex: 1; }}
.regra {{ margin-bottom: 6pt; }}
.regra .r {{ font: 700 6.2pt 'Inter'; letter-spacing: .1em; text-transform: uppercase; color: {CINZA};
             margin-bottom: 1.5pt; }}
.regra p {{ margin: 0; font-size: 7.5pt; color: #334155; }}
.ok {{ color: {VERDE}; font-weight: 700; }}
.evento {{ display: flex; gap: 8pt; padding: 4pt 0; border-bottom: 0.6pt solid #EEF2F7; font-size: 7.3pt; }}
.evento .d {{ color: {CINZA}; width: 46pt; flex: none; }}
.evento .t {{ font: 700 5.8pt 'Inter'; letter-spacing: .06em; text-transform: uppercase; color: {CIANO};
              width: 74pt; flex: none; padding-top: 1pt; }}
.evento .x {{ color: #334155; }}
.aviso {{ margin-top: 14pt; padding-top: 8pt; border-top: 0.6pt solid #E2E8F0; font-size: 6.5pt;
          color: #94A3B8; line-height: 1.55; }}
.pagina {{ break-before: page; margin-top: 0; }}
.junto {{ break-inside: avoid; }}
"""


def _kpis(c: dict, atual: dict, met: dict) -> str:
    ret = atual.get("retorno")
    rb = atual.get("retorno_bench")
    dif = (ret or 0) - rb if isinstance(rb, (int, float)) and isinstance(ret, (int, float)) else None
    alertas = atual.get("alertas") or []
    banda = c["regras"].get("banda") or carteiras.BANDA_PADRAO
    d0 = (c.get("bench") or {}).get("data0") or c["criada_em"]
    cards = [
        ("destaque", "Cota", _num(atual.get("cota", carteiras.COTA_INICIAL)), TINTA,
         f"base 100 em {_data(c['criada_em'])}"),
        ("", "Retorno", _pct(ret), _cor(ret), "desde o início"),
        ("", f"vs {carteiras.BENCHMARK}", _pp(dif), _cor(dif),
         f"{carteiras.BENCHMARK} {_pct(rb)} desde {_data(d0)}" if rb is not None else "sem benchmark ainda"),
        ("", "Drawdown máx.", _pct(met.get("drawdown_max"), sinal=False) if met.get("drawdown_max") else "0,0%",
         VERMELHO if (met.get("drawdown_max") or 0) < -5e-5 else CINZA, "maior queda da cota"),
        ("", "Posições", str(len(c["posicoes"])), TINTA,
         (f'<span class="fora">{len(alertas)} fora da banda</span>' if alertas
          else f'<span class="ok">todas na banda</span> de {_num(banda * 100, 0)} p.p.')),
    ]
    return '<div class="kpis">' + "".join(
        f'<div class="kpi {cls}"><div class="r">{_e(r)}</div>'
        f'<div class="v" style="color:{cor}">{v}</div><div class="s">{s}</div></div>'
        for cls, r, v, cor, s in cards) + "</div>"


def _janelas(snaps: list[dict], atual: dict, met: dict) -> str:
    linhas = []
    for j in carteiras.janelas_de_retorno(snaps):
        linhas.append(f'<tr><td>{_e(j["nome"])}</td>'
                      f'<td style="color:{_cor(j["carteira"])}">{_pct(j["carteira"])}</td>'
                      f'<td style="color:{CINZA}">{_pct(j["bench"])}</td></tr>')
    vol = met.get("vol_anualizada")
    estat = [f"Última atualização: <b>{_data(atual.get('data', ''))}</b>",
             f"Pontos na série: <b>{len(snaps)}</b>"]
    estat.append(f"Volatilidade anualizada: <b>{_pct(vol, sinal=False)}</b>" if vol is not None
                 else "Volatilidade: <b>a partir de 20 pregões</b>")
    return (f'<table class="janelas"><tr><th>Janela</th><th>Carteira</th><th>{carteiras.BENCHMARK}</th></tr>'
            + "".join(linhas) + f'</table><div class="estat">{"<br>".join(estat)}</div>')


def _posicoes(c: dict, atual: dict) -> str:
    pesos = atual.get("pesos") or {}
    rets = atual.get("retornos") or {}
    alvos = atual.get("alvos") or {}
    banda = c["regras"].get("banda") or carteiras.BANDA_PADRAO
    maior = max((p["peso"] for p in c["posicoes"]), default=1) or 1
    linhas = []
    for p in sorted(c["posicoes"], key=lambda x: -x["peso"]):
        tk = p["ticker"]
        pa = pesos.get(tk)
        drift = (pa - p["peso"]) if isinstance(pa, (int, float)) else None
        fora = isinstance(drift, (int, float)) and abs(drift) > banda
        ret = rets.get(tk)
        contrib = p["peso"] * ret if isinstance(ret, (int, float)) else None
        a = alvos.get(tk) or {}
        alvo_txt = ("R$ " + _num(a["alvo"]) + ('<span class="alvo-ok">atingido</span>' if a.get("atingido") else "")
                    if a else "—")
        linhas.append(
            f'<tr><td><span class="tk">{_e(tk)}</span><span class="tipo">{_tipo(tk)}</span></td>'
            f'<td><div class="peso"><div class="barra"><i style="width:{p["peso"] / maior * 100:.1f}%"></i></div>'
            f'<span class="forte num">{_pct(p["peso"], sinal=False)}</span></div></td>'
            f'<td>{_pct(pa, sinal=False)}</td>'
            f'<td class="{"fora" if fora else ""}" style="{"" if fora else f"color:{CINZA}"}">{_pp(drift)}</td>'
            f'<td style="color:{_cor(ret)}">{_pct(ret)}</td>'
            f'<td>{alvo_txt}</td>'
            f'<td class="forte" style="color:{_cor(a.get("distancia"))}">{_pct(a.get("distancia")) if a else "—"}</td>'
            f'<td style="color:{_cor(contrib)}">{_pp(contrib, 2)}</td></tr>')
    return ('<table class="pos"><tr><th>Ativo</th><th>Peso alvo</th><th>Peso atual</th><th>Desvio</th>'
            '<th>Retorno*</th><th>Target</th><th>Upside</th><th>Contrib.*</th></tr>'
            + "".join(linhas) + "</table>"
            + f'<div class="nota">* Retorno e contribuição (peso alvo × retorno, em p.p. da cota) desde o '
              f'último rebalanceamento ({_data(c["base"]["data"])}). Desvio = peso atual − peso alvo; '
              f'banda de {_num(banda * 100, 0)} p.p. Upside = distância do preço atual até o target; '
              '"atingido" marca o papel que já passou do target.</div>')


def html(c: dict) -> str:
    atual = c.get("atual") or {}
    snaps = c.get("snapshots") or []
    met = carteiras.metricas_da_serie(snaps)
    origem = "mesa de IA (aprovada pelo usuário)" if c.get("origem") == "mesa" else "montagem manual"
    hoje = datetime.now(carteiras._TZ).strftime("%d/%m/%Y")

    mandato = (f'<div class="mandato"><b>Mandato</b>{_e(c["mandato"])}</div>'
               if c.get("mandato") else "")
    capa = (f'<div class="capa"><div class="topo"><div class="marca"><img src="{_marca()}">'
            f'{_wordmark()}</div><div class="selo">Lâmina da carteira</div></div>'
            f'<h1>{_e(c["nome"])}</h1>'
            f'<div class="meta">Gerada em <b>{hoje}</b> · criada em <b>{_data(c["criada_em"])}</b> · '
            f'origem: <b>{origem}</b></div>{mandato}</div>')

    tem_grafico = sum(1 for s in snaps if isinstance(s.get("cota"), (int, float))) >= 2
    legenda = (f'<div class="legenda"><span><i style="background:linear-gradient(90deg,{CIANO},{VIOLETA})"></i>'
               f'Cota da carteira</span><span><i style="background:#94A3B8"></i>{carteiras.BENCHMARK} '
               f'(base 100)</span></div>') if tem_grafico else ""
    grafico = (f'<div class="linha2 junto"><div class="graf">{_grafico(snaps)}{legenda}</div>'
               f'<div class="lado">{_janelas(snaps, atual, met)}</div></div>')

    teses = [p for p in c["posicoes"] if p.get("tese")]
    bloco_teses = ""
    if teses:
        bloco_teses = ('<section class="pagina"><h2>Teses</h2><div class="teses">' + "".join(
            f'<div class="tese"><div class="cab"><span class="tk">{_e(p["ticker"])}</span>'
            f'<span class="w">{_pct(p["peso"], sinal=False)} da carteira</span></div><p>{_e(p["tese"])}</p></div>'
            for p in sorted(teses, key=lambda x: -x["peso"])) + "</div></section>")

    alertas = atual.get("alertas") or []
    banda = c["regras"].get("banda") or carteiras.BANDA_PADRAO
    regras = [f'<div class="regra"><div class="r">Banda de rebalanceamento</div><p>{_num(banda * 100, 0)} p.p. — '
              + (f'<span class="fora">{len(alertas)} posição(ões) fora da banda</span>: '
                 + "; ".join(_e(a) for a in alertas) if alertas
                 else '<span class="ok">todas as posições dentro da banda</span>') + "</p></div>"]
    for chave, rotulo in (("macro", "Condições macro a observar"), ("micro", "Condições micro a observar")):
        if c["regras"].get(chave):
            regras.append(f'<div class="regra"><div class="r">{rotulo}</div><p>{_e(c["regras"][chave])}</p></div>')
    eventos = (c.get("eventos") or [])[-8:]
    lista_ev = "".join(
        f'<div class="evento"><span class="d">{_data(e["data"])}</span>'
        f'<span class="t">{_e(TIPOS_DE_EVENTO.get(e["tipo"], e["tipo"]))}</span><span class="x">{_e(e["texto"])}</span></div>'
        for e in reversed(eventos))

    aviso = ("Cota simulada buy-and-hold entre rebalanceamentos, sem custos nem impostos, e sem proventos — "
             f"dividendos pagos não entram na cota, enquanto o {carteiras.BENCHMARK} os embute (o ETF reinveste "
             "internamente): a comparação com o benchmark subestima a carteira, e mais ainda se ela for de "
             "dividendos. Rebalanceamentos são executados sem custo nos preços observados. As regras macro/micro "
             "são anotações de acompanhamento — nada dispara ordem. Isto não é recomendação de investimento.")

    corpo = (capa + _kpis(c, atual, met)
             + f'<section class="junto"><h2>Cota × {carteiras.BENCHMARK}</h2>{grafico}</section>'
             + f'<section><h2>Posições</h2>{_posicoes(c, atual)}</section>'
             + bloco_teses
             + '<section class="junto"><div class="duas">'
             + f'<div><h2>Regras e estado</h2>{"".join(regras)}</div>'
             + (f'<div><h2>Últimos eventos</h2>{lista_ev}</div>' if eventos else "")
             + '</div></section>'
             + f'<div class="aviso">{aviso}</div>')
    return (f'<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">'
            f'<title>{_e(c["nome"])} · lâmina</title><style>{_fontes_css()}{CSS}</style></head>'
            f'<body>{corpo}</body></html>')


def gerar(c: dict) -> bytes:
    """O PDF da lâmina."""
    from weasyprint import HTML    # importado aqui: só quem baixa a lâmina paga o custo
    return HTML(string=html(c)).write_pdf()


def nome_do_arquivo(c: dict) -> str:
    """'Lamina - <nome> - AAAA-MM-DD.pdf', só com caracteres seguros."""
    import re
    import unicodedata
    base = unicodedata.normalize("NFKD", c.get("nome") or "carteira").encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Za-z0-9 ._-]+", "", base).strip() or "carteira"
    return f"Lamina - {base} - {datetime.now(carteiras._TZ).strftime('%Y-%m-%d')}.pdf"
