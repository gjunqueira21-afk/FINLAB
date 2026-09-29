"""ETFs listados na B3: universo dinâmico + metadados curados.

O universo vem da lista oficial da B3 (via PulseFlat), então ETFs novos
aparecem sozinhos. O que nenhuma fonte pública entrega por API — tese,
índice de referência e taxa de administração — vive na tabela curada
`ETF_META` abaixo: fácil de completar e de corrigir.

Um ETF não tem valuation: o painel dele mostra o que o fundo faz, quanto
custa (taxa de administração) e quão líquido é, com performance contra os
pares da mesma categoria.
"""

from __future__ import annotations

import re
from typing import Optional

from . import b3data

# ---------------------------------------------------------------------------
# Categorias
# ---------------------------------------------------------------------------

CATEGORIES: dict[str, dict] = {
    "INDICES_BR": {"label": "Índices Brasil", "icon": "🇧🇷",
                   "desc": "Ibovespa e índices amplos de ações brasileiras"},
    "FATORES_DIV": {"label": "Fatores, Dividendos & ESG", "icon": "🎯",
                    "desc": "Small caps, dividendos, low vol, momentum e sustentabilidade"},
    "INTERNACIONAL": {"label": "Internacional", "icon": "🌍",
                      "desc": "S&P 500, mundo, países e temas globais"},
    "RENDA_FIXA": {"label": "Renda Fixa", "icon": "📜",
                   "desc": "Tesouro (IMA-B, IRF-M), CDI e crédito"},
    "CRIPTO": {"label": "Cripto", "icon": "₿",
               "desc": "Bitcoin, Ethereum e cestas de criptoativos"},
    "SETORIAL": {"label": "Setoriais & Temáticos", "icon": "🧩",
                 "desc": "Setores da B3, ouro, commodities e temas específicos"},
}

# ---------------------------------------------------------------------------
# Metadados curados
# ---------------------------------------------------------------------------
# taxa_adm em % a.a. — mantida localmente porque não existe fonte pública por
# API; confira na página da gestora antes de decidir. `None` = não preenchida.

def M(cat: str, tese: str, indice: Optional[str] = None,
      taxa_adm: Optional[float] = None) -> dict:
    return {"cat": cat, "tese": tese, "indice": indice, "taxa_adm": taxa_adm}


ETF_META: dict[str, dict] = {
    # --- Índices Brasil ---------------------------------------------------
    "BOVA11": M("INDICES_BR", "Replica o Ibovespa — a porta de entrada mais líquida "
                "para a bolsa brasileira em um único papel.", "Ibovespa", 0.10),
    "BOVV11": M("INDICES_BR", "Ibovespa pela gestora do Itaú; alternativa ao BOVA11 "
                "com estrutura própria de replicação.", "Ibovespa", 0.20),
    "BBOV11": M("INDICES_BR", "Ibovespa pela BB Asset, com selo de responsabilidade "
                "socioambiental do banco.", "Ibovespa"),
    "BOVB11": M("INDICES_BR", "Ibovespa pela Bradesco Asset.", "Ibovespa"),
    "BOVX11": M("INDICES_BR", "Ibovespa com custo agressivo, da XP Asset.", "Ibovespa"),
    "PIBB11": M("INDICES_BR", "O ETF mais antigo da B3: replica o IBrX-50, as 50 ações "
                "mais negociadas, com uma das menores taxas do mercado.", "IBrX-50", 0.059),
    "BRAX11": M("INDICES_BR", "IBrX-100 — carteira mais ampla que o Ibovespa, ponderada "
                "por valor de mercado.", "IBrX-100"),
    "XBOV11": M("INDICES_BR", "Ibovespa pela Caixa Asset.", "Ibovespa"),

    # --- Fatores, dividendos & ESG ----------------------------------------
    "SMAL11": M("FATORES_DIV", "Small caps brasileiras (índice SMLL): mais risco e mais "
                "beta que o Ibovespa, historicamente amplifica os ciclos.", "SMLL", 0.50),
    "DIVO11": M("FATORES_DIV", "Ações do IDIV — pagadoras de dividendos consistentes; "
                "tende a carregar utilities, bancos e seguradoras.", "IDIV", 0.50),
    "FIND11": M("FATORES_DIV", "Setor financeiro da B3 (IFNC): bancos, seguradoras e B3.",
                "IFNC", 0.50),
    "GOVE11": M("FATORES_DIV", "Empresas com melhores práticas de governança (IGC-NM).",
                "IGCT"),
    "ISUS11": M("FATORES_DIV", "Carteira do ISE — o índice de sustentabilidade da B3.",
                "ISE", 0.38),
    "ECOO11": M("FATORES_DIV", "Índice de carbono eficiente ICO2.", "ICO2", 0.38),
    "TRIG11": M("FATORES_DIV", "Estratégia sistemática de momentum em ações brasileiras."),
    "BMMT11": M("FATORES_DIV", "Fator momentum Brasil, índice Morningstar.", "Morningstar BR Momento"),
    "VLID11": M("FATORES_DIV", "Fator valor em ações brasileiras."),

    # --- Internacional ------------------------------------------------------
    "IVVB11": M("INTERNACIONAL", "S&P 500 em reais, sem hedge: você leva o índice "
                "americano e a variação do dólar juntos.", "S&P 500 (BRL)", 0.23),
    "SPXI11": M("INTERNACIONAL", "S&P 500 em reais pela XP Asset, concorrente direto "
                "do IVVB11.", "S&P 500 (BRL)"),
    "NASD11": M("INTERNACIONAL", "Nasdaq-100 em reais: big techs americanas com "
                "exposição cambial.", "Nasdaq-100 (BRL)"),
    "WRLD11": M("INTERNACIONAL", "Ações globais desenvolvidas (MSCI World) em reais.",
                "MSCI World (BRL)"),
    "ACWI11": M("INTERNACIONAL", "Mundo todo em um papel: MSCI ACWI, desenvolvidos + "
                "emergentes.", "MSCI ACWI (BRL)"),
    "EURP11": M("INTERNACIONAL", "Ações europeias desenvolvidas em reais.", "Europa (BRL)"),
    "ASIA11": M("INTERNACIONAL", "Ásia desenvolvida e emergente em reais."),
    "XINA11": M("INTERNACIONAL", "Ações chinesas (índice MSCI China) em reais.", "MSCI China (BRL)"),
    "EMEG11": M("INTERNACIONAL", "Mercados emergentes em reais."),
    "USTK11": M("INTERNACIONAL", "Tecnologia americana em reais."),
    "JOGO11": M("INTERNACIONAL", "Tema global de games e e-sports."),
    "TECB11": M("INTERNACIONAL", "Tecnologia global em reais, da BB Asset."),

    # --- Renda fixa ---------------------------------------------------------
    "IMAB11": M("RENDA_FIXA", "Títulos públicos atrelados ao IPCA (IMA-B completo): "
                "juro real com duration longa — sobe forte quando o juro cai.",
                "IMA-B", 0.25),
    "B5P211": M("RENDA_FIXA", "NTN-Bs de até 5 anos (IMA-B5 P2): juro real com menos "
                "sensibilidade a juros que o IMAB11.", "IMA-B5 P2", 0.20),
    "IB5M11": M("RENDA_FIXA", "NTN-Bs longas, vencimento acima de 5 anos (IMA-B5+): "
                "duration alta, aposta direta em fechamento de curva.", "IMA-B5+"),
    "IRFM11": M("RENDA_FIXA", "Prefixados (IRF-M): ganha com queda da curva nominal.",
                "IRF-M", 0.20),
    "FIXA11": M("RENDA_FIXA", "Juro prefixado sintético via futuros de DI.", "Pré DI", 0.30),
    "LFTS11": M("RENDA_FIXA", "Pós-fixado colado na Selic (LFTs) — o 'caixa' listado em bolsa.",
                "IMA-S"),
    "CDII11": M("RENDA_FIXA", "CDI via debêntures e títulos privados de alta qualidade."),
    "DEBB11": M("RENDA_FIXA", "Debêntures incentivadas — crédito privado isento na pessoa física."),

    # --- Cripto -------------------------------------------------------------
    "HASH11": M("CRIPTO", "Cesta dos maiores criptoativos (Nasdaq Crypto Index): "
                "bitcoin e ethereum dominam o peso.", "Nasdaq Crypto Index", 1.30),
    "BITH11": M("CRIPTO", "100% bitcoin, da Hashdex.", "Bitcoin", 0.70),
    "QBTC11": M("CRIPTO", "100% bitcoin, da QR Asset.", "Bitcoin", 0.75),
    "ETHE11": M("CRIPTO", "100% ethereum, da QR Asset.", "Ethereum", 0.75),
    "QETH11": M("CRIPTO", "Ethereum, da QR Asset.", "Ethereum", 0.75),
    "WEB311": M("CRIPTO", "Tema Web3 e infraestrutura de blockchain.", None, 1.30),
    "DEFI11": M("CRIPTO", "Cesta de protocolos de finanças descentralizadas (DeFi).", None, 1.30),
    "CRPT11": M("CRIPTO", "Cesta ampla de criptoativos."),

    # --- Setoriais & temáticos ---------------------------------------------
    "GOLD11": M("SETORIAL", "Ouro em reais, com lastro no exterior: proteção clássica "
                "contra crise e desvalorização cambial.", "Ouro (BRL)", 0.30),
    "MATB11": M("SETORIAL", "Setor de materiais básicos da B3 (IMAT): mineração, "
                "siderurgia, papel e celulose.", "IMAT", 0.38),
    "UTIP11": M("SETORIAL", "Utilities da B3 (UTIL): energia elétrica e saneamento.", "UTIL"),
    "AGRI11": M("SETORIAL", "Agronegócio brasileiro (IAGRO-FFS), da BB Asset.", "IAGRO"),
    "ESGB11": M("SETORIAL", "Tema ESG Brasil, da BTG Asset."),
    "REIT11": M("SETORIAL", "Fundos imobiliários listados — 'FII de FIIs' em formato ETF."),
    "TECK11": M("SETORIAL", "Tecnologia listada na B3."),
}

# Palavras-chave para categorizar quem não está na tabela curada.
_RULES: list[tuple[str, str]] = [
    (r"BITCOIN|ETHEREUM|CRYPTO|CRIPTO|DEFI|WEB3|BLOCKCHAIN|SOLANA|XRP", "CRIPTO"),
    (r"S&P|SP500|NASDAQ|MSCI|GLOBAL|MUNDO|WORLD|CHINA|EUA|ASIA|EUROPA|EMERGENTES|INTERNACIONAL|TREASURY|DOLAR", "INTERNACIONAL"),
    (r"IMA-?B|IMA-?S|IRF-?M|IDKA|TESOURO|DEBENTURE|CDI|SELIC|PREFIXADO|INFLACAO|IPCA|RENDA FIXA|CREDITO", "RENDA_FIXA"),
    (r"IBOVESPA|IBRX|IBRA|IBOV", "INDICES_BR"),
    (r"SMALL|DIVIDENDO|IDIV|MOMENTO|MOMENTUM|VALOR|QUALITY|LOW VOL|GOVERNANCA|ESG|SUSTENTAB|CARBONO", "FATORES_DIV"),
    (r"OURO|GOLD|AGRO|IMOBILIARIO|FII|UTILITIES|ENERGIA|FINANCEIRO|MATERIAIS|CONSUMO|SAUDE|TECNOLOGIA|GAMES", "SETORIAL"),
]


def _categorize(ticker: str, nome: str, categoria_b3: str) -> str:
    meta = ETF_META.get(ticker)
    if meta:
        return meta["cat"]
    alvo = f"{nome} {ticker}".upper()
    for pattern, cat in _RULES:
        if re.search(pattern, alvo):
            return cat
    if "RENDA FIXA" in (categoria_b3 or "").upper():
        return "RENDA_FIXA"
    return "SETORIAL"


def _generic_tese(nome: str, categoria_b3: str) -> str:
    tipo = "renda fixa" if "RENDA FIXA" in (categoria_b3 or "").upper() else "renda variável"
    return (f"Fundo de índice de {tipo} listado na B3 ({nome.title()}). "
            "Tese e taxa ainda não catalogadas — confira o regulamento na gestora.")


# ---------------------------------------------------------------------------
# Universo consolidado
# ---------------------------------------------------------------------------

_TICKER_RE = re.compile(r"^[A-Z0-9]{4}11$")

# ETFs que a lista da B3 não traz (cripto, sobretudo) mas negociam na bolsa —
# entram pelo cadastro curado, com preço e liquidez vindos do boletim diário.
_EXTRA_LISTING = {
    "HASH11": "HASHDEX NASDAQ CRYPTO INDEX FUNDO DE ÍNDICE",
    "BITH11": "HASHDEX NASDAQ BITCOIN FUNDO DE ÍNDICE",
    "QBTC11": "QR BITCOIN FUNDO DE ÍNDICE",
    "ETHE11": "QR ETHER FUNDO DE ÍNDICE",
    "QETH11": "QR ETHEREUM FUNDO DE ÍNDICE",
    "WEB311": "HASHDEX WEB3 FUNDO DE ÍNDICE",
    "DEFI11": "HASHDEX DEFI FUNDO DE ÍNDICE",
    "B5P211": "IT NOW ID ETF IMA-B5 P2 FUNDO DE ÍNDICE",
    "IB5M11": "IT NOW ID ETF IMA-B5+ FUNDO DE ÍNDICE",
}


def universe() -> list[dict]:
    """Todos os ETFs listados, com categoria, metadados e cadastro CVM."""
    listing = [item for item in b3data.etf_listing()
               if _TICKER_RE.match(item["ticker"])]
    presentes = {item["ticker"] for item in listing}
    for ticker, nome in _EXTRA_LISTING.items():
        if ticker not in presentes:
            categoria = "ETF Renda Fixa" if ticker in ("B5P211", "IB5M11") else "ETF Renda Variável"
            listing.append({"ticker": ticker, "nome": nome, "categoria_b3": categoria})

    out = []
    for item in listing:
        ticker = item["ticker"]
        meta = ETF_META.get(ticker) or {}
        cat = _categorize(ticker, item["nome"], item["categoria_b3"])
        registro = b3data.registry_for(item["nome"]) or {}
        out.append({
            "ticker": ticker,
            "nome": item["nome"],
            "categoria": cat,
            "categoria_b3": item["categoria_b3"],
            "tese": meta.get("tese") or _generic_tese(item["nome"], item["categoria_b3"]),
            "curado": ticker in ETF_META,
            "indice": meta.get("indice"),
            "taxa_adm": meta.get("taxa_adm"),
            "pl": registro.get("pl"),
            "pl_data": registro.get("pl_data"),
            "situacao": registro.get("situacao"),
            "gestor": registro.get("gestor"),
            "inicio": registro.get("inicio"),
        })
    return out


def get(ticker: str) -> Optional[dict]:
    ticker = ticker.upper().strip()
    for etf in universe():
        if etf["ticker"] == ticker:
            return etf
    return None


def liquidity_band(avg_vol: Optional[float]) -> str:
    """Classificação qualitativa da liquidez pelo volume médio diário."""
    if avg_vol is None or avg_vol <= 0:
        return "sem negócios"
    if avg_vol >= 50e6:
        return "muito alta"
    if avg_vol >= 10e6:
        return "alta"
    if avg_vol >= 1e6:
        return "média"
    if avg_vol >= 100e3:
        return "baixa"
    return "muito baixa"
