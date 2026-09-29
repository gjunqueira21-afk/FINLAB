"""Universo coberto pelo painel: 90 ações da B3 em 11 setores.

Cada empresa carrega o CD_CVM já resolvido contra os parquets do pipeline
CVM (valuation_cvm/data/processed), o que permite calcular fundamentos e
score mesmo sem token BRAPI.

`SECTORS` define, por setor, quais múltiplos fazem sentido exibir na tela
principal — P/L e P/VP para bancos, EV/EBITDA para indústria, e assim por
diante. Dívida líquida/EBITDA é sempre a última coluna, exceto para
financeiras, onde a métrica não tem significado econômico.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Company:
    ticker: str
    name: str
    sector: str
    cd_cvm: Optional[str]
    cvm_name: str


def C(ticker: str, name: str, sector: str, cd_cvm: Optional[str], cvm_name: str) -> Company:
    return Company(ticker, name, sector, cd_cvm, cvm_name)


# ---------------------------------------------------------------------------
# Setores
# ---------------------------------------------------------------------------
# `metrics`: colunas de múltiplos exibidas na tela principal (máx. 4).
# `financial=True` marca setores em que dívida líquida/EBITDA não se aplica.

SECTORS: dict[str, dict] = {
    "BANCOS": {
        "label": "Bancos",
        "icon": "🏦",
        "metrics": ["pl", "pvp", "roe", "dy"],
        "financial": True,
    },
    "SEGUROS": {
        "label": "Seguros & Mercado de Capitais",
        "icon": "🛡️",
        "metrics": ["pl", "pvp", "roe", "dy"],
        "financial": True,
    },
    "PETROLEO": {
        "label": "Petróleo, Gás & Petroquímica",
        "icon": "🛢️",
        "metrics": ["ev_ebitda", "pl", "mg_ebitda", "dy"],
        "financial": False,
    },
    "MINERACAO": {
        "label": "Mineração & Siderurgia",
        "icon": "⛏️",
        "metrics": ["ev_ebitda", "pl", "mg_ebitda", "dy"],
        "financial": False,
    },
    "PAPEL_AGRO": {
        "label": "Papel, Celulose & Agro",
        "icon": "🌱",
        "metrics": ["ev_ebitda", "pl", "mg_ebitda", "roe"],
        "financial": False,
    },
    "UTILITIES": {
        "label": "Energia & Saneamento",
        "icon": "⚡",
        "metrics": ["ev_ebitda", "pl", "dy", "roe"],
        "financial": False,
    },
    "VAREJO": {
        "label": "Varejo & Consumo Discricionário",
        "icon": "🛒",
        "metrics": ["ev_ebitda", "pl", "pvp", "mg_ebitda"],
        "financial": False,
    },
    "ALIMENTOS": {
        "label": "Alimentos & Bebidas",
        "icon": "🍽️",
        "metrics": ["ev_ebitda", "pl", "mg_ebitda", "roe"],
        "financial": False,
    },
    "SAUDE": {
        "label": "Saúde",
        "icon": "🩺",
        "metrics": ["ev_ebitda", "pl", "pvp", "mg_ebitda"],
        "financial": False,
    },
    "IMOBILIARIO": {
        "label": "Imobiliário & Construção",
        "icon": "🏗️",
        "metrics": ["pvp", "pl", "roe", "dy"],
        "financial": False,
    },
    "INDUSTRIA_TECH": {
        "label": "Indústria, Tech & Logística",
        "icon": "⚙️",
        "metrics": ["ev_ebitda", "pl", "roe", "mg_ebitda"],
        "financial": False,
    },
}

METRIC_LABELS = {
    "pl": "P/L",
    "pvp": "P/VP",
    "ev_ebitda": "EV/EBITDA",
    "dy": "DY",
    "roe": "ROE",
    "mg_ebitda": "Mg. EBITDA",
    "nd_ebitda": "Dív.Líq/EBITDA",
}

# Formato de exibição de cada métrica no front-end.
METRIC_FORMAT = {
    "pl": "mult",
    "pvp": "mult",
    "ev_ebitda": "mult",
    "dy": "pct",
    "roe": "pct",
    "mg_ebitda": "pct",
    "nd_ebitda": "mult",
}


# ---------------------------------------------------------------------------
# Empresas
# ---------------------------------------------------------------------------

UNIVERSE: list[Company] = [
    C("ITUB4", "Itaú Unibanco", "BANCOS", "019348", "ITAU UNIBANCO HOLDING S.A."),
    C("BBDC4", "Bradesco", "BANCOS", "000906", "BCO BRADESCO S.A."),
    C("BBAS3", "Banco do Brasil", "BANCOS", "001023", "BCO BRASIL S.A."),
    C("SANB11", "Santander Brasil", "BANCOS", "020532", "BCO SANTANDER (BRASIL) S.A."),
    C("BPAC11", "BTG Pactual", "BANCOS", "022616", "BCO BTG PACTUAL S.A."),
    C("ABCB4", "Banco ABC Brasil", "BANCOS", "020958", "BCO ABC BRASIL S.A."),
    C("BRSR6", "Banrisul", "BANCOS", "001210", "BANCO DO ESTADO DO RIO GRANDE DO SUL SA"),
    C("ITSA4", "Itaúsa", "BANCOS", "007617", "ITAÚSA S.A."),
    C("BBSE3", "BB Seguridade", "SEGUROS", "023159", "BB SEGURIDADE PARTICIPAÇÕES S.A."),
    C("PSSA3", "Porto Seguro", "SEGUROS", "016659", "PORTO SEGURO S.A."),
    C("CXSE3", "Caixa Seguridade", "SEGUROS", "023795", "CAIXA SEGURIDADE PARTICIPAÇÕES S.A."),
    C("B3SA3", "B3", "SEGUROS", "021610", "B3 S.A. - BRASIL, BOLSA, BALCÃO"),
    C("IRBR3", "IRB Re", "SEGUROS", "024180", "IRB - BRASIL RESSEGUROS S.A."),
    C("PETR4", "Petrobras PN", "PETROLEO", "009512", "PETROLEO BRASILEIRO S.A. PETROBRAS"),
    C("PETR3", "Petrobras ON", "PETROLEO", "009512", "PETROLEO BRASILEIRO S.A. PETROBRAS"),
    C("PRIO3", "PRIO", "PETROLEO", "022187", "PRIO S.A."),
    C("RECV3", "PetroReconcavo", "PETROLEO", "025780", "PETRORECÔNCAVO S.A."),
    C("VBBR3", "Vibra Energia", "PETROLEO", "024295", "VIBRA ENERGIA S/A"),
    C("UGPA3", "Ultrapar", "PETROLEO", "018465", "ULTRAPAR PARTICIPACOES S.A."),
    C("BRKM5", "Braskem", "PETROLEO", "004820", "BRASKEM S.A."),
    C("CSAN3", "Cosan", "PETROLEO", "019836", "COSAN S.A."),
    C("VALE3", "Vale", "MINERACAO", "004170", "VALE S.A."),
    C("CSNA3", "CSN", "MINERACAO", "004030", "CIA SIDERURGICA NACIONAL"),
    C("GGBR4", "Gerdau", "MINERACAO", "003980", "GERDAU S.A."),
    C("GOAU4", "Metalúrgica Gerdau", "MINERACAO", "008656", "METALURGICA GERDAU S.A."),
    C("USIM5", "Usiminas", "MINERACAO", "014320", "USINAS SID DE MINAS GERAIS S.A.-USIMINAS"),
    C("CMIN3", "CSN Mineração", "MINERACAO", "025585", "CSN MINERAÇÃO S.A."),
    C("BRAP4", "Bradespar", "MINERACAO", "018724", "BRADESPAR S.A."),
    C("SUZB3", "Suzano", "PAPEL_AGRO", "013986", "SUZANO S.A."),
    C("KLBN11", "Klabin", "PAPEL_AGRO", "012653", "KLABIN S.A."),
    C("SLCE3", "SLC Agrícola", "PAPEL_AGRO", "020745", "SLC AGRICOLA S.A."),
    C("SMTO3", "São Martinho", "PAPEL_AGRO", "020516", "SAO MARTINHO S.A."),
    C("AGRO3", "BrasilAgro", "PAPEL_AGRO", "020036", "BRASILAGRO - CIA BRAS DE PROP AGRICOLAS"),
    C("JALL3", "Jalles Machado", "PAPEL_AGRO", "025496", "JALLES MACHADO S.A."),
    C("ELET3", "Eletrobras", "UTILITIES", "002437", "AXIA ENERGIA S.A."),
    C("EQTL3", "Equatorial", "UTILITIES", "020010", "EQUATORIAL S.A."),
    C("ENGI11", "Energisa", "UTILITIES", "015253", "ENERGISA S.A."),
    C("CPLE6", "Copel", "UTILITIES", "014311", "CIA PARANAENSE DE ENERGIA - COPEL"),
    C("CMIG4", "Cemig", "UTILITIES", "002453", "CIA ENERGETICA DE MINAS GERAIS - CEMIG"),
    C("TAEE11", "Taesa", "UTILITIES", "020257", "TRANSMISSORA ALIANÇA DE ENERGIA ELÉTRICA S.A."),
    C("EGIE3", "Engie Brasil", "UTILITIES", "017329", "ENGIE BRASIL ENERGIA S.A."),
    C("AURE3", "Auren Energia", "UTILITIES", "026620", "AUREN ENERGIA S.A."),
    C("SBSP3", "Sabesp", "UTILITIES", "014443", "CIA SANEAMENTO BASICO EST SAO PAULO"),
    C("NEOE3", "Neoenergia", "UTILITIES", "015539", "NEOENERGIA S.A."),
    C("CSMG3", "Copasa", "UTILITIES", "019445", "CIA SANEAMENTO DE MINAS GERAIS-COPASA MG"),
    C("MGLU3", "Magazine Luiza", "VAREJO", "022470", "MAGAZINE LUIZA S.A."),
    C("LREN3", "Lojas Renner", "VAREJO", "008133", "LOJAS RENNER S.A."),
    C("VIVA3", "Vivara", "VAREJO", "024805", "VIVARA PARTICIPAÇÕES S.A."),
    C("PETZ3", "Petz", "VAREJO", "025089", "PET CENTER COMÉRCIO E PARTICIPAÇÕES S.A."),
    C("SBFG3", "Grupo SBF", "VAREJO", "024694", "GRUPO SBF S.A."),
    C("ASAI3", "Assaí", "VAREJO", "025372", "SENDAS DISTRIBUIDORA S.A."),
    C("CRFB3", "Carrefour Brasil", "VAREJO", "024171", "ATACADÃO S.A."),
    C("PCAR3", "GPA", "VAREJO", "014826", "CIA BRASILEIRA DE DISTRIBUICAO"),
    C("GUAR3", "Guararapes", "VAREJO", "004669", "GUARARAPES CONFECCOES S.A."),
    C("ABEV3", "Ambev", "ALIMENTOS", "023264", "AMBEV S.A."),
    C("JBSS3", "JBS", "ALIMENTOS", "020575", "JBS S.A."),
    C("BRFS3", "BRF", "ALIMENTOS", "016292", "BRF S.A."),
    C("MRFG3", "Marfrig", "ALIMENTOS", "020788", "MARFRIG GLOBAL FOODS S.A."),
    C("BEEF3", "Minerva", "ALIMENTOS", "020931", "MINERVA S.A."),
    C("NTCO3", "Natura &Co", "ALIMENTOS", "024783", "NATURA &CO HOLDING S.A."),
    C("CAML3", "Camil", "ALIMENTOS", "024228", "CAMIL ALIMENTOS S.A."),
    C("RDOR3", "Rede D'Or", "SAUDE", "024821", "REDE D'OR SÃO LUIZ S.A."),
    C("HAPV3", "Hapvida", "SAUDE", "024392", "HAPVIDA PARTICIPAÇÕES E INVESTIMENTOS S.A."),
    C("FLRY3", "Fleury", "SAUDE", "021881", "FLEURY S.A."),
    C("RADL3", "Raia Drogasil", "SAUDE", "005258", "RAIA DROGASIL S.A."),
    C("HYPE3", "Hypera", "SAUDE", "021431", "HYPERA S.A."),
    C("QUAL3", "Qualicorp", "SAUDE", "022497", "QUALICORP CONSULTORIA E CORRETORA DE SEGUROS S.A."),
    C("DASA3", "Dasa", "SAUDE", "019623", "DIAGNOSTICOS DA AMERICA S.A."),
    C("ONCO3", "Oncoclínicas", "SAUDE", "026123", "ONCOCLÍNICAS DO BRASIL SERVIÇOS MÉDICOS S.A."),
    C("CYRE3", "Cyrela", "IMOBILIARIO", "014460", "CYRELA BRAZIL REALTY S.A.EMPREEND E PART"),
    C("MRVE3", "MRV", "IMOBILIARIO", "020915", "MRV ENGENHARIA E PARTICIPACOES S.A."),
    C("EZTC3", "EZTec", "IMOBILIARIO", "020770", "EZ TEC EMPREEND. E PARTICIPACOES S.A."),
    C("DIRR3", "Direcional", "IMOBILIARIO", "021350", "DIRECIONAL ENGENHARIA S.A."),
    C("TEND3", "Tenda", "IMOBILIARIO", "021148", "CONSTRUTORA TENDA S.A."),
    C("MULT3", "Multiplan", "IMOBILIARIO", "020982", "MULTIPLAN - EMPREEND IMOBILIARIOS S.A."),
    C("IGTI11", "Iguatemi", "IMOBILIARIO", "008672", "IGUATEMI S.A."),
    C("ALOS3", "Allos", "IMOBILIARIO", "022357", "ALLOS S.A."),
    C("LOGG3", "LOG CP", "IMOBILIARIO", "023272", "LOG COMMERCIAL PROPERTIES E PARTICIPAÇÕES"),
    C("WEGE3", "WEG", "INDUSTRIA_TECH", "005410", "WEG S.A."),
    C("EMBR3", "Embraer", "INDUSTRIA_TECH", "020087", "EMBRAER S.A."),
    C("POMO4", "Marcopolo", "INDUSTRIA_TECH", "008451", "MARCOPOLO S.A."),
    C("MYPK3", "Iochpe-Maxion", "INDUSTRIA_TECH", "011932", "IOCHPE MAXION S.A."),
    C("TOTS3", "Totvs", "INDUSTRIA_TECH", "019992", "TOTVS S.A."),
    C("VIVT3", "Vivo", "INDUSTRIA_TECH", "017671", "TELEFÔNICA BRASIL S.A"),
    C("TIMS3", "TIM Brasil", "INDUSTRIA_TECH", "024929", "TIM S.A."),
    C("LWSA3", "LWSA", "INDUSTRIA_TECH", "024910", "LWSA S/A"),
    C("INTB3", "Intelbras", "INDUSTRIA_TECH", "025453", "INTELBRAS S.A. IND. DE TELECOM. ELETRÔNICA BRASILEIRA"),
    C("RAIL3", "Rumo", "INDUSTRIA_TECH", "017450", "RUMO S.A."),
    C("RENT3", "Localiza", "INDUSTRIA_TECH", "019739", "LOCALIZA RENT A CAR S.A."),
    C("AZUL4", "Azul", "INDUSTRIA_TECH", "024112", "AZUL S.A."),
]

# ---------------------------------------------------------------------------
# Units (certificados de depósito de ações)
# ---------------------------------------------------------------------------
# Uma unit agrupa N ações. O preço negociado é o da unit, enquanto o capital
# social da CVM conta ações individuais — sem esta divisão, o valor de
# mercado (e todo múltiplo derivado dele) sai inflado pelo fator N.

UNIT_RATIO: dict[str, int] = {
    "SANB11": 2,    # 1 ON + 1 PN
    "BPAC11": 3,    # 1 ON + 2 PN
    "KLBN11": 5,    # 1 ON + 4 PN
    "TAEE11": 3,    # 1 ON + 2 PN
    "ENGI11": 5,    # 1 ON + 4 PN
    "IGTI11": 3,    # 1 ON + 2 PN
}


def unit_ratio(ticker: str) -> int:
    return UNIT_RATIO.get(ticker.upper().strip(), 1)


BY_TICKER: dict[str, Company] = {c.ticker: c for c in UNIVERSE}
TICKERS: list[str] = [c.ticker for c in UNIVERSE]


def get(ticker: str) -> Optional[Company]:
    return BY_TICKER.get(ticker.upper().strip())


def sector_of(ticker: str) -> Optional[str]:
    c = get(ticker)
    return c.sector if c else None


def is_financial(ticker: str) -> bool:
    sec = sector_of(ticker)
    return bool(sec and SECTORS[sec]["financial"])


def peers(ticker: str) -> list[str]:
    """Demais tickers do mesmo setor."""
    sec = sector_of(ticker)
    if not sec:
        return []
    return [c.ticker for c in UNIVERSE if c.sector == sec and c.ticker != ticker.upper()]


def as_payload() -> dict:
    """Estrutura enviada ao front-end."""
    return {
        "sectors": [
            {
                "key": key,
                **{k: v for k, v in meta.items()},
                "tickers": [c.ticker for c in UNIVERSE if c.sector == key],
            }
            for key, meta in SECTORS.items()
        ],
        "companies": [
            {"ticker": c.ticker, "name": c.name, "sector": c.sector, "cd_cvm": c.cd_cvm}
            for c in UNIVERSE
        ],
        "metric_labels": METRIC_LABELS,
        "metric_format": METRIC_FORMAT,
    }
