"""Premissas iniciais de valuation, derivadas dos dados — não chutadas.

O cálculo do DCF/EPV roda no navegador (finlab/web/assets/js/engine.js) para
que os sliders respondam instantaneamente. Aqui montamos apenas o ponto de
partida: custo de capital, crescimento e fluxo-base coerentes com o
histórico da empresa e com o macro do dia.

Convenção de custo de capital (BRL nominal):
    Ke   = Rf + β × ERP + prêmio adicional
    Rf   = Selic corrente (já embute o risco soberano brasileiro, por isso
           não somamos prêmio-país de novo)
    Kd   = CDI + spread de crédito, depois de imposto
    WACC = We·Ke + Wd·Kd·(1 − t)
"""

from __future__ import annotations

from typing import Optional

from .metrics import TAX_RATE, div

# Beta setorial de referência, usado quando a BRAPI não fornece o beta.
SECTOR_BETA = {
    "BANCOS": 1.05, "SEGUROS": 0.85, "PETROLEO": 1.15, "MINERACAO": 1.20,
    "PAPEL_AGRO": 0.95, "UTILITIES": 0.70, "VAREJO": 1.25, "ALIMENTOS": 0.90,
    "SAUDE": 1.00, "IMOBILIARIO": 1.15, "INDUSTRIA_TECH": 1.05,
}

# Spread de crédito sobre o CDI por setor (a.a.), ponto de partida editável.
SECTOR_SPREAD = {
    "UTILITIES": 0.015, "BANCOS": 0.010, "SEGUROS": 0.010, "ALIMENTOS": 0.022,
    "PETROLEO": 0.020, "MINERACAO": 0.020, "PAPEL_AGRO": 0.022,
    "SAUDE": 0.028, "VAREJO": 0.030, "IMOBILIARIO": 0.032, "INDUSTRIA_TECH": 0.025,
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _mean(values: list[Optional[float]]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def base_fcf(fund: dict) -> dict:
    """Fluxo de caixa livre base: último exercício e média de 3 anos.

    A média suaviza capital de giro e capex lumpy — é o default do painel.
    """
    series = fund.get("series", {})
    fcl = [v for v in (series.get("fcl") or []) if v is not None]
    ultimo = fcl[-1] if fcl else None
    media3 = _mean(fcl[-3:]) if len(fcl) >= 2 else ultimo
    return {"ultimo": ultimo, "media3": media3, "historico": fcl[-5:]}


# Piso de conversão (FCL sobre EBITDA) para a base alternativa valer a troca.
# Abaixo disso o fluxo é ruído perto da dívida e do custo de capital, e o
# preço justo deixa de falar sobre a operação. Aferido nas empresas do
# universo em regime de ruptura: elas se distribuem de 18% para cima, com a
# MRV isolada em 7% — exatamente o caso em que a troca só serve para escapar
# da barreira de fluxo não positivo.
BASE_MATERIAL = 0.15


def base_por_regime(fund: dict, fcf: dict, reg: Optional[dict]) -> Optional[dict]:
    """O fluxo-base que o regime pede, quando ele difere do padrão do painel.

    O padrão é a média de 3 anos do FCL, que só é uma estimativa honesta do
    run-rate em operação normal (R0). Nos demais regimes ela descreve um
    passado que não se repete — e o parecer 05 é explícito: o ajuste tem de
    aparecer, senão o painel deixa de ser uma ferramenta de premissas abertas.

    Devolve None quando o regime não pede nada diferente. Nunca troca a base
    sozinha: quem escolhe continua sendo quem usa, e o padrão fica a um clique.
    """
    if not isinstance(reg, dict) or not reg.get("codigo") or reg["codigo"] == "R0":
        return None

    codigo = reg["codigo"]
    series = fund.get("series") or {}

    def media3(campo):
        vals = [v for v in (series.get(campo) or []) if v is not None]
        return _mean(vals[-3:]) if vals else None

    if codigo == "R1":
        # Fluxo do ativo maduro: o capex de expansão sai da base, o de
        # manutenção fica. A depreciação é o proxy padrão de manutenção — é o
        # que o ativo consome por ano para continuar sendo o que é.
        fco, dep = media3("fco"), media3("depreciacao")
        if fco is None or dep is None:
            return None
        valor = fco - abs(dep)
        return {
            "modo": "maduro",
            "rotulo": "Ativo maduro",
            "valor": round(valor, 2),
            "porque": "Em expansão, o FCL é negativo por escolha: o capex embute a "
                      "capacidade que ainda não gera receita. Esta base troca o capex "
                      "total pelo de manutenção (proxy: a depreciação), estimando o que "
                      "o ativo gera quando a expansão terminar. Cuidado: em negócio "
                      "intensivo em capital a depreciação subestima a manutenção de "
                      "verdade — o ativo foi comprado a custo histórico e se repõe a "
                      "custo de hoje. Quanto maior o salto contra a média, mais essa "
                      "base depende de a expansão de fato terminar.",
            "conta": "caixa das operações (média 3a) − depreciação (média 3a)",
        }

    if codigo in ("R2", "R3", "R4"):
        # Nos três, o passado descreve outra empresa: dívida sendo paga,
        # estratégia refeita, ou um pedaço saindo. O exercício mais recente é
        # o retrato menos contaminado que as demonstrações anuais oferecem.
        ultimo = fcf.get("ultimo")
        if ultimo is None:
            return None
        # Trocar uma base negativa por outra que é praticamente zero não
        # melhora nada: o DCF passa a existir, mas o preço justo vira função
        # só da dívida líquida. A MRV saía de −1,40 bi para +28 mi e o painel
        # cuspia −404% de upside, onde antes dizia honestamente que não dava
        # para valorar. Sem base material, o padrão fica e a barreira do
        # fluxo não positivo faz o seu trabalho.
        ebitda = media3("ebitda")
        if ebitda and ultimo < BASE_MATERIAL * abs(ebitda):
            return None
        porque = {
            "R2": "Em desalavancagem, a média de 3 anos mistura exercícios de "
                  "estruturas de capital diferentes. Atenção: o fluxo está indo para o "
                  "credor, então a ponte até o equity muda de ano para ano — e o painel "
                  "ainda usa uma dívida líquida fixa.",
            "R3": "Em turnaround, a média de 3 anos mistura o regime velho com o novo. "
                  "A margem histórica deixou de ser âncora, e o valor está numa "
                  "distribuição de cenários, não num ponto.",
            "R4": "Com uma operação saindo, a média de 3 anos soma fluxos de um pedaço "
                  "que não estará lá. O correto seria soma das partes — negócio "
                  "contínuo mais o valor de realização do que está à venda —, e esse "
                  "valor de realização o painel não tem.",
        }[codigo]
        return {
            "modo": "ultimo",
            "rotulo": "Último exercício",
            "valor": round(float(fcf["ultimo"]), 2),
            "porque": porque,
            "conta": "FCL do exercício mais recente",
        }

    # R5: a base não muda; o que perde sentido é a comparação com pares.
    return None


def assumptions(fund: dict, snap: dict, macro: dict, brapi: Optional[dict] = None,
                reg: Optional[dict] = None) -> dict:
    """Monta o conjunto de premissas iniciais para o motor de valuation."""
    sector = fund.get("sector") or ""
    base = fund.get("base", {})
    ind = fund.get("indicadores", {})

    def mv(chave):
        item = macro.get(chave) or {}
        v = item.get("value")
        return (v / 100.0) if isinstance(v, (int, float)) else None

    selic = mv("selic")
    ipca = mv("ipca")
    cdi = mv("cdi")
    pre10 = mv("prefixado_10a")
    ntnb10 = mv("ntnb_10a")
    implicita = mv("inflacao_implicita")

    inflacao = ipca if ipca is not None else 0.0450
    cdi_dec = cdi if cdi is not None else (selic or 0.1400)

    # Taxa livre de risco: para um modelo com perpetuidade, a âncora certa é
    # o juro nominal LONGO, não a Selic overnight — que é cíclica. Usamos o
    # prefixado ~10 anos quando disponível e deixamos as alternativas
    # explícitas para o usuário trocar com um clique.
    opcoes = {}
    if pre10 is not None:
        opcoes["pre10"] = {"valor": round(pre10, 4), "label": "Prefixado ~10a (NTN-F)",
                           "nota": "juro nominal longo — coerente com fluxo nominal e perpetuidade"}
    if ntnb10 is not None:
        # Compomos o juro real com o IPCA corrente, e não com a inflação
        # implícita: usar a implícita reproduziria exatamente o prefixado,
        # já que ela é definida por essa mesma identidade. Esta opção existe
        # justamente para quem projeta inflação diferente da do mercado.
        composta = (1 + ntnb10) * (1 + inflacao) - 1
        opcoes["ntnb"] = {
            "valor": round(composta, 4),
            "label": "NTN-B ~10a + IPCA 12m",
            "nota": (f"juro real de {ntnb10 * 100:.2f}% composto com IPCA de {inflacao * 100:.2f}%"
                     + (f"; a inflação implícita do mercado é {implicita * 100:.2f}%"
                        if implicita is not None else "")),
        }
    if selic is not None:
        opcoes["selic"] = {"valor": round(selic, 4), "label": "Selic à vista",
                           "nota": "taxa de curtíssimo prazo; sobe e desce com o ciclo"}

    if pre10 is not None:
        rf, rf_fonte, rf_modo = pre10, "ANBIMA · prefixado ~10 anos", "pre10"
    elif selic is not None:
        rf, rf_fonte, rf_modo = selic, "Selic à vista", "selic"
    else:
        rf, rf_fonte, rf_modo = 0.1400, "referência fixa", "selic"

    beta = None
    if brapi:
        raw = ((brapi.get("defaultKeyStatistics") or {}).get("beta")
               if isinstance(brapi.get("defaultKeyStatistics"), dict) else None)
        if raw:
            try:
                beta = _clamp(float(raw), 0.3, 2.5)
            except (TypeError, ValueError):
                beta = None
    beta_source = "BRAPI" if beta else "referência setorial"
    if beta is None:
        beta = SECTOR_BETA.get(sector, 1.0)

    erp = 0.050
    spread_credito = SECTOR_SPREAD.get(sector, 0.025)
    kd = cdi_dec + spread_credito

    # Estrutura de capital a valor de mercado; sem dado, cai para 25% dívida.
    cap = snap.get("market_cap")
    divida = base.get("divida_bruta")
    if cap and divida is not None and cap > 0:
        wd = _clamp(divida / (divida + cap), 0.0, 0.80)
        wd_source = "mercado (dívida bruta / (dívida + market cap))"
    else:
        wd = 0.25
        wd_source = "padrão (25%)"
    we = 1 - wd

    ke = rf + beta * erp
    wacc = we * ke + wd * kd * (1 - TAX_RATE)

    # Crescimento: ancorado no CAGR de receita, limitado e convergindo
    # para a inflação de longo prazo.
    cagr_rec = ind.get("cagr_receita_3a")
    g0 = _clamp(cagr_rec if cagr_rec is not None else inflacao, -0.05, 0.20)
    g_terminal = _clamp(inflacao, 0.0, max(0.0, wacc - 0.020))
    growth = [round(g0 + (g_terminal - g0) * (i / 4), 4) for i in range(5)]

    fcf = base_fcf(fund)
    fcf_base = fcf["media3"] if fcf["media3"] is not None else fcf["ultimo"]
    fcf_modo = "media3" if fcf["media3"] is not None else "ultimo"

    # O regime manda no padrão do painel — é o item 2.6 do plano. Não é ajuste
    # silencioso: o front mostra de quanto para quanto, a conta que produziu o
    # número e o porquê, com um clique para voltar à média de 3 anos.
    regime_base = base_por_regime(fund, fcf, reg)
    if regime_base and regime_base.get("valor") is not None:
        fcf_base = regime_base["valor"]
        fcf_modo = regime_base["modo"]

    ebit_hist = [v for v in (fund.get("series", {}).get("ebit") or []) if v is not None]
    ebit_norm = _mean(ebit_hist[-3:]) if ebit_hist else None

    # FCL sustentadamente acima do EBITDA é sinal de que o caixa do período
    # veio de capital de giro (tipicamente alongamento de fornecedores), não
    # da operação. Extrapolar isso num DCF projeta algo que não se repete.
    ebitda_hist = [v for v in (fund.get("series", {}).get("ebitda") or []) if v is not None]
    ebitda_norm = _mean(ebitda_hist[-3:]) if ebitda_hist else None
    fcl_sobre_ebitda = None
    if fcf_base is not None and ebitda_norm and ebitda_norm > 0:
        fcl_sobre_ebitda = round(fcf_base / ebitda_norm, 3)

    return {
        "rf": round(rf, 4),
        "rf_fonte": rf_fonte,
        "rf_modo": rf_modo,
        "rf_opcoes": opcoes,
        "erp": erp,
        "beta": round(beta, 3),
        "beta_source": beta_source,
        "premio_extra": 0.0,
        "ke": round(ke, 4),
        "cdi": round(cdi_dec, 4),
        "spread_credito": spread_credito,
        "kd": round(kd, 4),
        "tax": TAX_RATE,
        "wd": round(wd, 4),
        "we": round(we, 4),
        "wd_source": wd_source,
        "wacc": round(wacc, 4),
        "inflacao": round(inflacao, 4),
        "growth": growth,
        "g_terminal": round(g_terminal, 4),
        "anos": 5,
        "fcf_base": fcf_base,
        "fcf_ultimo": fcf["ultimo"],
        "fcf_media3": fcf["media3"],
        "fcf_historico": fcf["historico"],
        "fcf_regime": regime_base,
        "fcf_modo": fcf_modo,
        "ebit_normalizado": ebit_norm,
        "ebitda_normalizado": ebitda_norm,
        "fcl_sobre_ebitda": fcl_sobre_ebitda,
        "divida_liquida": base.get("divida_liquida"),
        "caixa": base.get("caixa"),
        "shares": snap.get("shares_quote"),
        "shares_emitidas": snap.get("shares"),
        "unit_ratio": snap.get("unit_ratio", 1),
        "preco": snap.get("price"),
        "aplicavel": not fund.get("financial") and fcf_base is not None,
        "motivo_nao_aplicavel": _motivo(fund, fcf_base, snap),
        "fcl_negativo": bool(fcf_base is not None and fcf_base <= 0),
    }


def bdr_assumptions(fund: dict, snap: dict, macro: dict,
                    quote: Optional[dict] = None,
                    yahoo_info: Optional[dict] = None) -> dict:
    """Premissas para o DCF de um BDR — inteiro na moeda de reporte (USD).

    O truque de conversão: `shares` aqui é sintético — market cap em USD
    dividido pelo preço do BDR em BRL. Assim, equity_value(USD) ÷ shares
    devolve diretamente o preço justo POR BDR em reais, sem precisar da
    razão BDR/ação do programa:

        equity/shares = preço_BDR × equity/mcap = preço_BDR × (1 + upside)
    """
    from . import b3data

    base = fund.get("base", {})
    ind = fund.get("indicadores", {})

    fx = b3data.usdbrl()
    preco_bdr = snap.get("price")

    # Market cap em USD: direto do Yahoo quando disponível (já vem em dólar);
    # senão, o marketCap em BRL da BRAPI convertido pela PTAX.
    mcap_usd = None
    mcap_fonte = None
    if yahoo_info and yahoo_info.get("marketCap"):
        try:
            mcap_usd = float(yahoo_info["marketCap"])
            mcap_fonte = "Yahoo Finance"
        except (TypeError, ValueError):
            mcap_usd = None
    if mcap_usd is None and quote and quote.get("marketCap"):
        try:
            mcap_brl = float(quote["marketCap"])
            if fx:
                mcap_usd = mcap_brl / fx
                mcap_fonte = "BRAPI ÷ PTAX"
        except (TypeError, ValueError):
            pass

    shares_eff = (mcap_usd / preco_bdr) if (mcap_usd and preco_bdr) else None

    # Custo de capital em dólar: âncoras dos EUA, não a curva brasileira.
    rf = 0.045       # UST ~10 anos, referência editável
    erp = 0.045
    inflacao = 0.025
    beta = 1.0
    beta_source = "padrão (1,0)"
    raw_beta = (yahoo_info or {}).get("beta")
    if raw_beta is None and quote:
        stats = quote.get("defaultKeyStatistics")
        raw_beta = stats.get("beta") if isinstance(stats, dict) else None
    try:
        if raw_beta:
            beta = _clamp(float(raw_beta), 0.3, 2.5)
            beta_source = "Yahoo Finance" if (yahoo_info or {}).get("beta") else "BRAPI"
    except (TypeError, ValueError):
        pass

    spread = 0.015
    kd = rf + spread

    divida = base.get("divida_bruta")
    if mcap_usd and divida is not None and mcap_usd > 0:
        wd = _clamp(divida / (divida + mcap_usd), 0.0, 0.80)
        wd_source = "mercado (dívida bruta / (dívida + market cap))"
    else:
        wd = 0.20
        wd_source = "padrão (20%)"
    we = 1 - wd

    ke = rf + beta * erp
    wacc = we * ke + wd * kd * (1 - TAX_RATE)

    cagr_rec = ind.get("cagr_receita_3a")
    g0 = _clamp(cagr_rec if cagr_rec is not None else 0.05, -0.05, 0.25)
    g_terminal = _clamp(inflacao, 0.0, max(0.0, wacc - 0.020))
    growth = [round(g0 + (g_terminal - g0) * (i / 4), 4) for i in range(5)]

    fcf = base_fcf(fund)
    fcf_base = fcf["media3"] if fcf["media3"] is not None else fcf["ultimo"]

    series = fund.get("series", {})
    ebit_hist = [v for v in (series.get("ebit") or []) if v is not None]
    ebit_norm = _mean(ebit_hist[-3:]) if ebit_hist else None
    ebitda_hist = [v for v in (series.get("ebitda") or []) if v is not None]
    ebitda_norm = _mean(ebitda_hist[-3:]) if ebitda_hist else None
    fcl_sobre_ebitda = (round(fcf_base / ebitda_norm, 3)
                        if fcf_base is not None and ebitda_norm and ebitda_norm > 0 else None)

    aplicavel = (not fund.get("financial") and fcf_base is not None
                 and shares_eff is not None)
    if fund.get("financial"):
        motivo = ("Balanço de instituição financeira: DCF de fluxo da firma não se "
                  "aplica. Use P/L, P/VP e ROE.")
    elif fund.get("years") in (None, []):
        motivo = ("Sem demonstrações disponíveis: o Yahoo Finance não respondeu para o "
                  "papel de origem (rede bloqueando finance.yahoo.com é a causa mais "
                  "comum) e a BRAPI não cobre fundamentos de BDR.")
    elif fcf_base is None:
        motivo = "Fluxo de caixa livre indisponível nos módulos da BRAPI."
    elif shares_eff is None:
        motivo = ("Market cap ou câmbio indisponível — impossível converter o "
                  "equity em preço por BDR.")
    else:
        motivo = None

    return {
        "rf": round(rf, 4),
        "rf_fonte": "UST ~10 anos (referência fixa, editável)",
        "rf_modo": "ust",
        "rf_opcoes": {},
        "erp": erp,
        "beta": round(beta, 3),
        "beta_source": beta_source,
        "premio_extra": 0.0,
        "ke": round(ke, 4),
        "cdi": round(rf, 4),
        "spread_credito": spread,
        "kd": round(kd, 4),
        "tax": TAX_RATE,
        "wd": round(wd, 4),
        "we": round(we, 4),
        "wd_source": wd_source,
        "wacc": round(wacc, 4),
        "inflacao": inflacao,
        "growth": growth,
        "g_terminal": round(g_terminal, 4),
        "anos": 5,
        "fcf_base": fcf_base,
        "fcf_ultimo": fcf["ultimo"],
        "fcf_media3": fcf["media3"],
        "fcf_historico": fcf["historico"],
        # BDR não passa por classificação de regime: as demonstrações vêm do
        # Yahoo, sem o plano de contas da CVM que os sinais leem.
        "fcf_regime": None,
        "fcf_modo": "media3" if fcf["media3"] is not None else "ultimo",
        "ebit_normalizado": ebit_norm,
        "ebitda_normalizado": ebitda_norm,
        "fcl_sobre_ebitda": fcl_sobre_ebitda,
        "divida_liquida": base.get("divida_liquida"),
        "caixa": base.get("caixa"),
        "shares": shares_eff,
        "shares_emitidas": None,
        "unit_ratio": 1,
        "preco": preco_bdr,
        "mcap_usd": mcap_usd,
        "mcap_fonte": mcap_fonte,
        "usdbrl": fx,
        "moeda": fund.get("currency") or "USD",
        "bdr": True,
        "aplicavel": aplicavel,
        "motivo_nao_aplicavel": motivo,
        "fcl_negativo": bool(fcf_base is not None and fcf_base <= 0),
    }


def _motivo(fund: dict, fcf_base: Optional[float], snap: dict) -> Optional[str]:
    if fund.get("financial"):
        return ("Instituição financeira: DCF por fluxo de caixa livre da firma não se "
                "aplica. Use múltiplos (P/L, P/VP) e o modelo de dividendos.")
    if fcf_base is None:
        return "Sem fluxo de caixa livre na base da CVM (FCO e/ou capex ausentes)."
    if not snap.get("shares_quote"):
        return "Quantidade de ações indisponível — o preço-alvo por ação não pode ser calculado."
    return None


# ---------------------------------------------------------------------------
# Poder de lucro (EPV) no servidor
# ---------------------------------------------------------------------------

def epv(prem: dict) -> dict:
    """Valor por poder de lucro, por ação — a porta em Python do `epv()` do
    engine.js, dígito por dígito.

    O motor de valuation vive no navegador porque lá ele recalcula a cada
    slider. Mas a TELA PRINCIPAL não tem sliders e tem 90 empresas: para a
    mesa poder responder "quais estão mais perto do próprio valor de poder de
    lucro" sem abrir empresa por empresa, o número precisa existir antes,
    aqui. É a mesma conta — EBIT normalizado depois de imposto capitalizado
    ao WACC, menos dívida líquida, dividido pelas ações —, então os dois
    lugares não podem divergir; há teste comparando os dois.

    Sem crescimento no numerador de propósito: EPV mede o que a empresa vale
    parada, com o lucro que já demonstra. É o piso contra o qual o preço de
    tela é lido.
    """
    vazio = {"valor": None, "equity": None, "por_acao": None, "upside": None}
    ebit = prem.get("ebit_normalizado")
    w = prem.get("wacc")
    if not isinstance(ebit, (int, float)) or not isinstance(w, (int, float)) or w <= 0:
        return vazio

    valor = (ebit * (1 - prem.get("tax", TAX_RATE))) / w
    dl = prem.get("divida_liquida")
    equity = valor - (dl if isinstance(dl, (int, float)) else 0.0)

    acoes = prem.get("shares")
    if not isinstance(acoes, (int, float)) or acoes <= 0:
        return {"valor": valor, "equity": equity, "por_acao": None, "upside": None}

    por_acao = equity / acoes
    preco = prem.get("preco")
    upside = (por_acao / preco - 1) if isinstance(preco, (int, float)) and preco > 0 else None
    return {"valor": valor, "equity": equity, "por_acao": por_acao, "upside": upside}
