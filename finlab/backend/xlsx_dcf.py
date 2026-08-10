"""Exportação da planilha DCF — a página não calcula mais preço justo.

O redesenho tirou o motor de valuation da página da empresa: quem quer
simular exporta esta planilha, com os dados da CVM já preenchidos, mexe nas
premissas no Excel/LibreOffice e traz os três preços justos de volta para o
campo "Seu DCF". A estrutura reproduz o `WEGE3-DCF.xlsx` de referência
(finlab/docs/redesign/): dados do painel em cinza, premissas editáveis em
três cenários (fundo amarelo, fonte azul), e TODOS os resultados como
fórmula viva — nunca um número calculado aqui em Python. Se a planilha
recalcula diferente do que o painel diria, o bug fica visível; se os
resultados viessem prontos, ficaria escondido.
"""

from __future__ import annotations

import io
from datetime import date
from typing import Optional

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter


class SemDados(ValueError):
    """A planilha não pode ser montada com o que o painel tem."""


# ---------------------------------------------------------------------------
# Estilo — as cores exatas do arquivo de referência
# ---------------------------------------------------------------------------

_AZUL_ESCURO = "FF1F3864"   # cabeçalho de seção
_AZUL_MEDIO = "FF2E5395"    # cabeçalho dos cenários
_CINZA_FUNDO = "FFF2F2F2"   # dado do painel (não editar)
_AMARELO = "FFFFFF00"       # célula editável
_AZUL_FONTE = "FF0000FF"    # fonte da célula editável
_DESTAQUE = "FFD9E8FB"      # linha do preço justo
_CINZA_TXT = "FF666666"     # notas de fonte
_CINZA_HINT = "FF808080"    # dicas da coluna F

_FMT_MI = "#,##0;\\(#,##0\\);\\-"
_FMT_MOEDA = "#,##0.00;\\(#,##0.00\\);\\-"
_FMT_PCT1 = "0.0%;\\(0.0%\\);\\-"
_FMT_PCT2 = "0.00%;\\(0.00%\\);\\-"
_FMT_NUM2 = "0.00"

_ARIAL = "Arial"


def _fill(cor: str) -> PatternFill:
    return PatternFill(fill_type="solid", start_color=cor, end_color=cor)


class _Folha:
    """Açúcar de escrita: cada célula sai com Arial e o formato certo."""

    def __init__(self, ws):
        self.ws = ws

    def cel(self, ref: str, valor, *, fmt: str = "General", bold: bool = False,
            size: float = 10.0, cor: Optional[str] = None,
            fundo: Optional[str] = None):
        c = self.ws[ref]
        c.value = valor
        c.number_format = fmt
        c.font = Font(name=_ARIAL, size=size, bold=bold,
                      color=cor if cor else None)
        if fundo:
            c.fill = _fill(fundo)
        return c

    def secao(self, ref: str, titulo: str):
        self.cel(ref, titulo, bold=True, cor="FFFFFFFF", fundo=_AZUL_ESCURO)

    def hint(self, ref: str, texto: str):
        self.cel(ref, texto, size=8.0, cor=_CINZA_HINT)

    def fonte(self, ref: str, texto: str):
        self.cel(ref, texto, size=8.5, cor=_CINZA_TXT, fundo=_CINZA_FUNDO)


# ---------------------------------------------------------------------------
# Cenários — mediana do painel ± deltas fixos, como no arquivo de referência
# ---------------------------------------------------------------------------

def _cenarios_growth(growth: list) -> tuple[list, list, list]:
    """Pessimista/otimista a partir da rampa mediana: metade e uma vez e meia
    a taxa de cada ano (±|g|/2), arredondado a 0,05 p.p. — a proporção do
    arquivo de referência. Funciona igual com taxa negativa."""
    med = [round(float(g), 4) for g in (growth or [])][:5]
    while len(med) < 5:
        med.append(med[-1] if med else 0.05)
    delta = [abs(g) / 2 for g in med]
    bear = [round(g - d, 4) for g, d in zip(med, delta)]
    bull = [round(g + d, 4) for g, d in zip(med, delta)]
    return bear, med, bull


def _cenarios_beta(beta: float) -> tuple[float, float, float]:
    """±10% arredondado a 0,05: mais beta é mais desconto, então o beta alto
    fica no cenário pessimista."""
    passo = 0.05
    bear = round(round(beta * 1.1 / passo) * passo, 2)
    bull = round(round(beta * 0.9 / passo) * passo, 2)
    return bear, round(beta, 2), bull


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) else None


# ---------------------------------------------------------------------------
# A planilha
# ---------------------------------------------------------------------------

def planilha(ticker: str, prem: dict, fund: dict,
             hoje: Optional[date] = None) -> bytes:
    """Monta o .xlsx do DCF com os dados reais do ticker.

    `prem` é a saída de `valuation.assumptions` — a mesma que alimentava o
    motor da página, então planilha e painel partem das MESMAS premissas.
    Levanta `SemDados` quando o essencial não existe (financeira, FCL ou
    cotação ausentes) com o motivo em português, pronto para a tela.
    """
    if fund.get("financial"):
        raise SemDados("Instituição financeira: DCF de fluxo de caixa livre "
                       "da firma não se aplica — use P/L, P/VP e ROE.")

    fcl_media3 = _num(prem.get("fcf_media3"))
    fcl_ultimo = _num(prem.get("fcf_ultimo"))
    if fcl_media3 is None and fcl_ultimo is None:
        raise SemDados("Sem fluxo de caixa livre na base da CVM (FCO e/ou "
                       "capex ausentes) — não há o que projetar.")
    if fcl_media3 is None:
        fcl_media3 = fcl_ultimo
    if fcl_ultimo is None:
        fcl_ultimo = fcl_media3

    acoes = _num(prem.get("shares")) or _num(prem.get("shares_emitidas"))
    if not acoes or acoes <= 0:
        raise SemDados("Quantidade de ações indisponível — o preço justo por "
                       "ação não teria denominador.")
    preco = _num(prem.get("preco"))
    if not preco or preco <= 0:
        raise SemDados("Sem cotação para o papel — o upside não teria "
                       "referência.")

    dl = _num(prem.get("divida_liquida")) or 0.0
    ultimo_ex = fund.get("last_year") or ""
    hoje = hoje or date.today()
    data_str = hoje.strftime("%d/%m/%Y")

    # Premissas (fração decimal, como o Excel espera com formato de %)
    bear_g, med_g, bull_g = _cenarios_growth(prem.get("growth") or [0.05] * 5)
    g_med = round(_num(prem.get("g_terminal")) or 0.04, 4)
    g_bear, g_bull = max(0.0, round(g_med - 0.015, 4)), round(g_med + 0.015, 4)
    rf = round(_num(prem.get("rf")) or 0.13, 4)
    beta_bear, beta_med, beta_bull = _cenarios_beta(_num(prem.get("beta")) or 1.0)
    erp = round(_num(prem.get("erp")) or 0.05, 4)
    premio = round(_num(prem.get("premio_extra")) or 0.0, 4)
    spread = round(_num(prem.get("spread_credito")) or 0.02, 4)
    wd = round(_num(prem.get("wd")) or 0.25, 4)
    tax = round(_num(prem.get("tax")) or 0.34, 4)

    mi = lambda v: round(v / 1e6)   # noqa: E731 — R$ → R$ milhões

    wb = Workbook()
    ws = wb.active
    ws.title = "DCF"
    f = _Folha(ws)

    # Cabeçalho -----------------------------------------------------------
    f.cel("A1", f"{ticker} · Modelo DCF", bold=True, size=14.0)
    f.cel("A2", f"Exportado do Gab's FinLab em {data_str} · dados: DFP/ITR da "
                "CVM e mercado (BRAPI) · não é recomendação de investimento",
          size=9.0, cor=_CINZA_TXT)
    f.cel("A3", "Legenda: fundo amarelo + fonte azul = edite aqui · fonte "
                "preta = fórmula, não mexa · fundo cinza = dado do painel",
          size=9.0, cor=_CINZA_TXT)

    # DADOS DO PAINEL -----------------------------------------------------
    f.secao("A5", "DADOS DO PAINEL")
    f.cel("C5", "Fonte", bold=True, cor="FFFFFFFF", fundo=_AZUL_ESCURO)

    dados = [
        ("A6", "FCL médio 3 anos (R$ mi)", mi(fcl_media3), _FMT_MI,
         f"DFC da CVM {ultimo_ex - 2}–{ultimo_ex}" if isinstance(ultimo_ex, int)
         else "DFC da CVM"),
        ("A7", "FCL último exercício (R$ mi)", mi(fcl_ultimo), _FMT_MI,
         f"DFC da CVM {ultimo_ex}" if ultimo_ex else "DFC da CVM"),
        ("A8", "Dívida líquida (R$ mi)", mi(dl), _FMT_MI,
         (f"DFP {ultimo_ex}" if ultimo_ex else "DFP")
         + (" (caixa líquido)" if dl < 0 else "")),
        ("A9", "Ações emitidas (mi)", mi(acoes), _FMT_MI, "capital social CVM"),
        ("A10", "Preço de tela (R$)", round(preco, 2), _FMT_MOEDA,
         f"{prem.get('preco_fonte') or 'BRAPI'} · {data_str}"),
    ]
    for ref, rotulo, valor, fmt, origem in dados:
        linha = ref[1:]
        f.cel(ref, rotulo, fundo=_CINZA_FUNDO)
        f.cel("B" + linha, valor, fmt=fmt, fundo=_CINZA_FUNDO)
        f.fonte("C" + linha, origem)

    # PREMISSAS POR CENÁRIO ----------------------------------------------
    f.secao("A12", "PREMISSAS POR CENÁRIO")
    for col, nome in (("B", "Pessimista"), ("C", "Mediana"), ("D", "Otimista")):
        f.cel(col + "12", nome, bold=True, cor="FFFFFFFF", fundo=_AZUL_MEDIO)

    def editavel(linha: int, rotulo: str, valores: tuple, fmt: str,
                 dica: Optional[str] = None):
        f.cel(f"A{linha}", rotulo)
        for col, v in zip(("B", "C", "D"), valores):
            f.cel(f"{col}{linha}", v, fmt=fmt, cor=_AZUL_FONTE, fundo=_AMARELO)
        if dica:
            f.hint(f"F{linha}", dica)

    fcl_mi = mi(fcl_media3)
    editavel(13, "FCL base (R$ mi)", (fcl_mi, fcl_mi, fcl_mi), _FMT_MI,
             "padrão: média de 3 anos (B6); troque por B7 se preferir o "
             "último exercício")
    rotulos_g = ["Crescimento do FCL · ano 1", "Crescimento · ano 2",
                 "Crescimento · ano 3", "Crescimento · ano 4",
                 "Crescimento · ano 5"]
    for i, rotulo in enumerate(rotulos_g):
        editavel(14 + i, rotulo, (bear_g[i], med_g[i], bull_g[i]), _FMT_PCT1)
    editavel(19, "Perpetuidade (g)", (g_bear, g_med, g_bull), _FMT_PCT2,
             "dificilmente acima de inflação + PIB")
    editavel(20, "Taxa livre de risco (Rf)", (rf, rf, rf), _FMT_PCT2,
             prem.get("rf_fonte") or "prefixado ~10 anos (ANBIMA)")
    editavel(21, "Beta", (beta_bear, beta_med, beta_bull), _FMT_NUM2)
    editavel(22, "Prêmio de risco (ERP)", (erp, erp, erp), _FMT_PCT2)
    editavel(23, "Prêmio adicional", (round(premio + 0.01, 4), premio, premio),
             _FMT_PCT2, "tamanho, governança, execução")
    editavel(24, "Spread de crédito", (spread, spread, spread), _FMT_PCT2)
    editavel(25, "Dívida / (dívida + equity)", (wd, wd, wd), _FMT_PCT1)
    editavel(26, "Alíquota efetiva", (tax, tax, tax), _FMT_PCT1)

    # CUSTO DE CAPITAL — só fórmula --------------------------------------
    f.secao("A28", "CUSTO DE CAPITAL")

    def formula(linha: int, rotulo: str, corpo: str, fmt: str,
                bold: bool = False, size: float = 10.0,
                fundo: Optional[str] = None):
        f.cel(f"A{linha}", rotulo, bold=bold, size=size, fundo=fundo)
        for col in ("B", "C", "D"):
            f.cel(f"{col}{linha}", "=" + corpo.replace("_", col), fmt=fmt,
                  bold=bold, size=size, fundo=fundo)

    formula(29, "Ke — custo do equity", "_20+_21*_22+_23", _FMT_PCT2)
    formula(30, "Kd líquido de impostos", "(_20+_24)*(1-_26)", _FMT_PCT2)
    formula(31, "WACC", "_29*(1-_25)+_30*_25", _FMT_PCT2, bold=True)

    # PROJEÇÃO DO FCL -----------------------------------------------------
    f.secao("A33", "PROJEÇÃO DO FCL (R$ mi)")
    base_ano = ultimo_ex if isinstance(ultimo_ex, int) else "base"
    formula(34, f"FCL ano 1 ({base_ano}+1)", "_13*(1+_14)", _FMT_MI)
    for i in range(2, 6):
        formula(33 + i, f"FCL ano {i} ({base_ano}+{i})",
                f"_{32 + i}*(1+_{13 + i})", _FMT_MI)

    # DO FLUXO AO PREÇO JUSTO --------------------------------------------
    f.secao("A40", "DO FLUXO AO PREÇO JUSTO")
    for i in range(1, 6):
        formula(40 + i, f"VP do ano {i}", f"_{33 + i}/(1+_$31)^{i}", _FMT_MI)
    formula(46, "Soma dos VP explícitos", "SUM(_41:_45)", _FMT_MI)
    # A guarda de Gordon: WACC ≤ g não é um número, é um aviso.
    formula(47, "Valor terminal (Gordon)",
            'IF(_31<=_19,"n/a",_38*(1+_19)/(_31-_19))', _FMT_MI)
    formula(48, "VP do valor terminal",
            'IF(ISNUMBER(_47),_47/(1+_31)^5,"n/a")', _FMT_MI)
    formula(49, "Enterprise value",
            'IF(ISNUMBER(_48),_46+_48,"n/a")', _FMT_MI, bold=True)
    formula(50, "(−) Dívida líquida", "$B$8", _FMT_MI)
    formula(51, "Equity value",
            'IF(ISNUMBER(_49),_49-_50,"n/a")', _FMT_MI, bold=True)
    formula(52, "Peso da perpetuidade no EV",
            'IF(ISNUMBER(_49),_48/_49,"n/a")', _FMT_PCT1)
    formula(53, "PREÇO JUSTO POR AÇÃO (R$)",
            'IF(ISNUMBER(_51),_51/$B$9,"n/a")', _FMT_MOEDA,
            bold=True, size=12.0, fundo=_DESTAQUE)
    formula(54, "Upside vs preço de tela",
            'IF(ISNUMBER(_53),_53/$B$10-1,"n/a")', _FMT_PCT1)

    f.cel("A56", '→ Leve os três preços justos (linha 53) para o campo '
                 '"Seu DCF · faixa da planilha" no painel da empresa.',
          bold=True, cor=_AZUL_ESCURO)

    ws.column_dimensions["A"].width = 34.0
    for col in ("B", "C", "D"):
        ws.column_dimensions[col].width = 14.0
    ws.column_dimensions["F"].width = 2.0

    _sensibilidade(wb, wacc=_num(prem.get("wacc")) or 0.15, g=g_med)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _sensibilidade(wb: Workbook, wacc: float, g: float) -> None:
    """Aba de sensibilidade: WACC × g, centrada no cenário mediana do painel,
    com cada célula refazendo o DCF inteiro por fórmula sobre os fluxos da
    coluna C da aba DCF."""
    ws = wb.create_sheet("Sensibilidade")
    f = _Folha(ws)

    f.cel("A1", "Sensibilidade do preço justo (R$/ação)", bold=True, size=12.0)
    f.cel("A2", "Fluxos do cenário Mediana (aba DCF, coluna C) · linhas: WACC "
                "· colunas: crescimento na perpetuidade",
          size=9.0, cor=_CINZA_TXT)

    # Grade centrada no painel: WACC ±3 p.p., g ±2 p.p., passo de 1 p.p.
    centro_w = round(wacc, 2)
    centro_g = round(g, 2)
    waccs = [round(centro_w + d / 100, 2) for d in range(-3, 4)]
    waccs = [w for w in waccs if w > 0.01]
    gs = [round(centro_g + d / 100, 2) for d in range(-2, 3)]
    gs = [x for x in gs if x >= 0.0]

    f.cel("A4", "WACC \\ g", bold=True, cor="FFFFFFFF", fundo=_AZUL_ESCURO)
    for j, x in enumerate(gs):
        col = get_column_letter(2 + j)
        f.cel(f"{col}4", x, fmt=_FMT_PCT1, bold=True, cor="FFFFFFFF",
              fundo=_AZUL_ESCURO)

    for i, w in enumerate(waccs):
        linha = 5 + i
        f.cel(f"A{linha}", w, fmt=_FMT_PCT1, bold=True)
        for j in range(len(gs)):
            col = get_column_letter(2 + j)
            vps = "+".join(
                f"DCF!$C${33 + k}/(1+$A{linha})^{k}" for k in range(1, 6))
            term = (f"DCF!$C$38*(1+{col}$4)/($A{linha}-{col}$4)"
                    f"/(1+$A{linha})^5")
            f.cel(f"{col}{linha}",
                  f'=IF($A{linha}<={col}$4,"n/a",'
                  f"({vps}+{term}-DCF!$B$8)/DCF!$B$9)",
                  fmt=_FMT_MOEDA)

    f.cel(f"A{5 + len(waccs) + 1}",
          "A célula mais próxima do seu WACC e do seu g na aba DCF é o seu "
          "caso-base.", size=9.0, cor=_CINZA_TXT)

    ws.column_dimensions["A"].width = 12.0
