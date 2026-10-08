"""Leitura dos demonstrativos da CVM já processados pelo pipeline existente.

Fonte: valuation_cvm/data/processed/*.parquet (DFP consolidado, plano de
contas padronizado da CVM). Este módulo transforma as linhas contábeis em
séries anuais por empresa — a base fundamentalista do painel, que funciona
mesmo sem internet.

Convenções:
  * Valores em R$ nominais (coluna VL_CONTA_AJUSTADO já vem convertida).
  * Códigos CD_CONTA têm prioridade sobre descrição textual: a CVM
    padroniza os níveis 1–3, então o código é muito mais confiável.
  * Nada é inventado: conta ausente vira None e o front-end mostra "—".
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Optional

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .settings import CVM_PROCESSED_DIR

STATEMENTS = ("dre", "bpa", "bpp", "dfc_mi")

# O que de fato é lido daqui. Tudo o mais que a CVM publica fica no parquet e
# não sobe para a memória — ver a nota em _frames.
COLUNAS_LIDAS = ("CD_CVM", "DENOM_CIA", "CNPJ_CIA", "CD_CONTA", "DS_CONTA",
                 "VL_CONTA_AJUSTADO", "ANO_REFER", "DT_FIM_EXERC",
                 "DT_INI_EXERC", "ORDEM_EXERC")
MAX_YEARS = 10

# As mesmas contas servem o anual e o trimestral de propósito: o 4T sai da
# diferença entre o exercício fechado (DFP) e o acumulado até o 3T (ITR), e
# subtrair linhas diferentes daria um número plausível e errado.
CONTA_RECEITA = (["3.01"], ["RECEITA DE VENDA", "RECEITA LIQUIDA",
                            "RECEITAS DA INTERMEDIACAO", "RECEITA OPERACIONAL"])
CONTA_LUCRO = (["3.11", "3.09"], ["LUCRO/PREJUIZO CONSOLIDADO DO PERIODO",
                                  "LUCRO/PREJUIZO DO PERIODO", "LUCRO LIQUIDO"])


# ---------------------------------------------------------------------------
# Carregamento
# ---------------------------------------------------------------------------

@lru_cache(maxsize=4)
def _frames(tipo: str = "dfp") -> dict[str, pd.DataFrame]:
    """Carrega os quatro demonstrativos uma única vez por processo.

    `tipo` é o sufixo do pipeline: "dfp" (anual) ou "itr" (trimestral). O
    sufixo era fixo em _dfp — o achado 00.3 do diagnóstico: o pipeline em
    valuation_cvm já baixa e processa o ITR, e o painel simplesmente não lia.
    """
    out: dict[str, pd.DataFrame] = {}
    for st in STATEMENTS:
        fp = CVM_PROCESSED_DIR / f"{st}_{tipo}.parquet"
        if not fp.exists():
            out[st] = pd.DataFrame()
            continue
        # Só as colunas que este módulo lê. O parquet do pipeline guarda tudo
        # que a CVM manda (versão, moeda, escala, ordem, grupo…), e o ITR de
        # uma década é grande o bastante para a diferença aparecer no tempo de
        # abrir a primeira empresa. Colunas ausentes são ignoradas: o formato
        # do parquet mudou entre versões do pipeline.
        try:
            disponiveis = set(pq.ParquetFile(fp).schema.names)
            df = pd.read_parquet(fp, columns=[c for c in COLUNAS_LIDAS if c in disponiveis])
        except Exception:
            df = pd.read_parquet(fp)
        # Exercício comparativo: a CVM repete o período anterior em toda
        # entrega. Descartar aqui corta linha à toa e evita que _collapse
        # escolha um valor reapresentado no lugar do corrente.
        if "ORDEM_EXERC" in df.columns:
            corrente = df["ORDEM_EXERC"].astype(str).map(_norm).str.startswith("ULTIMO")
            if corrente.any():
                df = df[corrente]
        df["CD_CVM"] = df["CD_CVM"].astype(str).str.strip()
        df["CD_CONTA"] = df["CD_CONTA"].astype(str).str.strip()
        # Normalizar por VALOR ÚNICO, não por linha. São milhões de linhas
        # para alguns milhares de descrições distintas, e _norm faz
        # normalização unicode + regex a cada chamada: por linha, isso
        # sozinho levava dezenas de segundos na primeira abertura do painel,
        # que era o "fica carregando e não abre".
        unicos = pd.Series(df["DS_CONTA"].astype(str).unique())
        df["DS_NORM"] = df["DS_CONTA"].astype(str).map(dict(zip(unicos, unicos.map(_norm))))
        # Nível hierárquico da conta (3.01.01 → 2). _collapse precisa dele em
        # toda consulta e o contava por regex a cada chamada; pré-calcular por
        # código único troca centenas de milhares de regex por uma busca em
        # dicionário. Mesmo raciocínio do DS_NORM acima.
        codigos = pd.Series(df["CD_CONTA"].unique())
        df["_LVL"] = df["CD_CONTA"].map(
            dict(zip(codigos, codigos.map(lambda c: c.count("."))))).astype("int16")
        out[st] = df
    return out


@lru_cache(maxsize=1)
def _shares_table() -> pd.DataFrame:
    """Quantidade de ações por CNPJ, a partir do capital social da CVM."""
    fp = CVM_PROCESSED_DIR / "capital_social.csv"
    if not fp.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(fp, sep=";", dtype=str, encoding="utf-8", on_bad_lines="skip")
    except UnicodeDecodeError:  # arquivos da CVM costumam vir em latin1
        df = pd.read_csv(fp, sep=";", dtype=str, encoding="latin1", on_bad_lines="skip")
    if "Tipo_Capital" not in df.columns:
        return pd.DataFrame()
    df = df[df["Tipo_Capital"].str.contains("Integralizado", na=False)].copy()
    for col in ("Quantidade_Acoes_Ordinarias", "Quantidade_Acoes_Preferenciais",
                "Quantidade_Total_Acoes"):
        df[col] = pd.to_numeric(df.get(col), errors="coerce")
    df["TOTAL"] = df["Quantidade_Total_Acoes"].fillna(
        df["Quantidade_Acoes_Ordinarias"].fillna(0) + df["Quantidade_Acoes_Preferenciais"].fillna(0)
    )
    df["CNPJ_DIG"] = df["CNPJ_Companhia"].str.replace(r"\D", "", regex=True)
    df = df[df["TOTAL"] > 0]
    return df.sort_values("Data_Referencia").groupby("CNPJ_DIG").agg(
        shares=("TOTAL", "last"), data=("Data_Referencia", "last")
    ).reset_index()


def _norm(s: object) -> str:
    txt = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", txt).strip().upper()


def limpar_cache() -> None:
    """Zera os quadros e o índice por empresa — os dois vivem juntos."""
    _frames.cache_clear()
    _por_empresa.cache_clear()


def available() -> bool:
    """Há demonstrações processadas? Olha os ARQUIVOS, sem carregá-los: o
    teste de saúde do contêiner chama isto a cada 30 s, e abrir os parquets
    aqui punha a CVM inteira na memória só para responder "sim"."""
    return any((CVM_PROCESSED_DIR / f"{st}_dfp.parquet").is_file()
               and (CVM_PROCESSED_DIR / f"{st}_dfp.parquet").stat().st_size > 0
               for st in STATEMENTS)



def latest_quarter(cd_cvm: str) -> Optional[dict]:
    """O trimestre mais recente publicado no ITR para a empresa.

    Devolve {"fim": "AAAA-MM-DD", "receita": float|None, "lucro": float|None},
    com os valores ACUMULADOS no exercício até aquela data — é assim que a
    CVM publica a DRE do ITR. Sem ITR processado, devolve None e o painel
    segue anual, como sempre foi.
    """
    dre = _company("dre", cd_cvm, "itr")
    if dre.empty or "DT_FIM_EXERC" not in dre.columns:
        return None
    dre = dre.dropna(subset=["DT_FIM_EXERC"])
    if dre.empty:
        return None
    # Quando o parquet distingue o período (DT_INI_EXERC), fica só o
    # acumulado-padrão do ano — descarta janelas trimestrais avulsas.
    if "DT_INI_EXERC" in dre.columns:
        ini = pd.to_datetime(dre["DT_INI_EXERC"], errors="coerce")
        comeco_de_ano = (ini.dt.month == 1) & (ini.dt.day == 1)
        if comeco_de_ano.any():
            dre = dre[comeco_de_ano]
    fim = dre["DT_FIM_EXERC"].max()
    tri = dre[dre["DT_FIM_EXERC"] == fim]

    def valor(codes, keywords):
        serie = _series(tri, codes=codes, keywords=keywords)
        vals = list(serie.values())
        return float(vals[0]) if vals else None

    return {
        "fim": str(pd.Timestamp(fim).date()),
        "receita": valor(*CONTA_RECEITA),
        "lucro": valor(*CONTA_LUCRO),
    }


# ---------------------------------------------------------------------------
# Série trimestral (ITR)
# ---------------------------------------------------------------------------
#
# A DRE do ITR vem ACUMULADA no exercício: o 2T chega como jan–jun, o 3T como
# jan–set. Plotar o acumulado como se fosse trimestre isolado desenha uma
# receita que só cresce ao longo do ano — número errado com cara de certo.
# Aqui o acumulado é desfeito por diferença, e o 4T (que o ITR não publica)
# sai do exercício fechado da DFP menos o acumulado até o 3T.

def _distancia_meses(a: pd.Timestamp, b: pd.Timestamp) -> int:
    """Meses entre duas datas."""
    return (b.year - a.year) * 12 + (b.month - a.month)


def _meses(ini: pd.Timestamp, fim: pd.Timestamp) -> int:
    """Meses cobertos por uma janela [ini, fim], contando as duas pontas."""
    return _distancia_meses(ini, fim) + 1


def _indice_do_trimestre(ini: pd.Timestamp, fim: pd.Timestamp) -> int:
    """1..4 a partir do início do exercício — vale para ano fiscal não-civil."""
    return max(1, min(4, round(_meses(ini, fim) / 3)))


def _acumulado_do_exercicio(dre: pd.DataFrame) -> pd.DataFrame:
    """Mantém só as linhas acumuladas desde a abertura do exercício.

    O CSV do ITR traz, para a mesma data-fim, tanto o acumulado quanto janelas
    avulsas (o trimestre isolado). A acumulada é a de início mais antigo — o
    que também funciona para empresas de exercício fiscal não-civil, ao
    contrário de procurar literalmente 1º de janeiro.
    """
    if "DT_INI_EXERC" not in dre.columns:
        return dre
    dre = dre.dropna(subset=["DT_FIM_EXERC", "DT_INI_EXERC"]).copy()
    if dre.empty:
        return dre
    # Exercícios comparativos ("PENÚLTIMO") repetem períodos antigos com valores
    # possivelmente reapresentados; o corrente basta.
    if "ORDEM_EXERC" in dre.columns:
        corrente = dre["ORDEM_EXERC"].map(_norm).str.startswith("ULTIMO")
        if corrente.any():
            dre = dre[corrente]
    abertura = dre.groupby("DT_FIM_EXERC")["DT_INI_EXERC"].transform("min")
    return dre[dre["DT_INI_EXERC"] == abertura]


def _desacumula(acc: dict, abertura: dict, anual: dict) -> dict:
    """{data-fim: acumulado} → {data-fim: trimestre isolado}.

    `abertura` diz em que data cada exercício começou (é o que agrupa os
    trimestres do mesmo ano fiscal). `anual` é a série da DFP, usada só para
    fechar o 4T.
    """
    por_exercicio: dict = {}
    for fim in sorted(acc):
        por_exercicio.setdefault(abertura.get(fim), []).append(fim)

    out: dict = {}
    for ini, datas in por_exercicio.items():
        if ini is None:
            continue
        anterior = 0.0
        for fim in datas:
            out[fim] = acc[fim] - anterior
            anterior = acc[fim]
        # 4T: o ITR não publica. Só dá para derivar quando o último acumulado
        # é mesmo o 3T — senão a diferença junta vários trimestres num só.
        ultimo = datas[-1]
        if _indice_do_trimestre(ini, ultimo) != 3:
            continue
        fecha = ini + pd.DateOffset(years=1) - pd.Timedelta(days=1)
        if fecha.year in anual and fecha not in out:
            out[fecha] = anual[fecha.year] - acc[ultimo]
    return out


def _ltm(isolado: dict) -> dict:
    """Soma móvel de 4 trimestres, só onde os quatro são consecutivos."""
    datas = sorted(isolado)
    out: dict = {}
    for i in range(3, len(datas)):
        janela = datas[i - 3:i + 1]
        # Quatro trimestres seguidos deixam ~9 meses entre a primeira e a
        # última data-fim; buraco na série não pode virar LTM silencioso.
        if not 8 <= _distancia_meses(janela[0], janela[-1]) <= 10:
            continue
        out[datas[i]] = sum(isolado[d] for d in janela)
    return out


def _ts(serie: dict) -> dict:
    """Chaves de data como Timestamp. A coluna do parquet pode vir como texto,
    e aí o `.get()` com Timestamp devolveria None para tudo — a falha
    silenciosa que esvazia uma tabela inteira sem erro nenhum."""
    return {pd.Timestamp(k): v for k, v in (serie or {}).items()}


# Contas trimestrais além das linhas da DRE de leitura.
CONTA_DESP_FIN = (["3.06.02"], ["DESPESAS FINANCEIRAS"])
CONTA_FCO = (["6.01"], ["CAIXA LIQUIDO ATIVIDADES OPERACIONAIS"])


def _trimestres(cd_cvm: str) -> dict:
    """Todos os trimestres isolados do ITR, conta a conta, com o 4T derivado.

    Devolve {"isolado": {chave: {Timestamp fim: valor}}, "abertura": {fim:
    início do exercício}, "fin": bool}. É a fonte única do trimestral: a DRE
    da página, os 12 meses dos múltiplos e o endividamento leem daqui, para
    os três nunca discordarem sobre o que foi o 2T.

    Fluxos vêm ACUMULADOS no exercício no ITR e são desfeitos por diferença;
    o 4T (que o ITR não publica) é a DFP do ano menos o acumulado até o 3T.
    D&A e EBITDA saem da DFC, como no anual.
    """
    vazio = {"isolado": {}, "abertura": {}, "fin": False}
    if not cd_cvm:
        return vazio
    dre = _company("dre", cd_cvm, "itr")
    if dre.empty or "DT_FIM_EXERC" not in dre.columns:
        return vazio
    dre = _acumulado_do_exercicio(dre)
    if dre.empty or "DT_INI_EXERC" not in dre.columns:
        return vazio
    abertura = {pd.Timestamp(f): pd.Timestamp(i) for f, i in
                (dre.drop_duplicates("DT_FIM_EXERC")
                    .set_index("DT_FIM_EXERC")["DT_INI_EXERC"].to_dict().items())}
    if not abertura:
        return vazio

    fin = is_financial_statement(cd_cvm)
    dre_anual = _company("dre", cd_cvm)
    contas = {chave: conta for chave, _r, _t, conta in _LINHAS_DRE if conta is not None}
    contas["despesas_financeiras"] = CONTA_DESP_FIN

    isolado: dict = {}
    for chave, conta in contas.items():
        acc = _ts(_series(dre, *conta, chave="DT_FIM_EXERC"))
        anual = _series(dre_anual, *conta) if not dre_anual.empty else {}
        isolado[chave] = _desacumula(acc, abertura, anual)

    dfc = _company("dfc_mi", cd_cvm, "itr")
    dfc = _acumulado_do_exercicio(dfc) if not dfc.empty else dfc
    dfc_anual = _company("dfc_mi", cd_cvm)
    deprec: dict = {}
    if not dfc.empty:
        def desacumula_dfc(acc: dict, anual: dict) -> dict:
            return _desacumula(_ts(acc), abertura, anual)
        deprec = desacumula_dfc(
            {d: abs(v) for d, v in _depreciation(dfc, chave="DT_FIM_EXERC").items()},
            {a: abs(v) for a, v in _depreciation(dfc_anual).items()} if not dfc_anual.empty else {})
        isolado["fco"] = desacumula_dfc(
            _series(dfc, *CONTA_FCO, chave="DT_FIM_EXERC"),
            _series(dfc_anual, *CONTA_FCO) if not dfc_anual.empty else {})
        isolado["capex"] = desacumula_dfc(
            _capex(dfc, "DT_FIM_EXERC"), _capex(dfc_anual) if not dfc_anual.empty else {})
    isolado["da"] = {d: -v for d, v in deprec.items()}
    ebit = isolado.get("ebit") or {}
    isolado["ebitda"] = ({d: ebit[d] + deprec[d] for d in ebit if d in deprec}
                        if not fin else {})
    return {"isolado": isolado, "abertura": abertura, "fin": fin}


def _exercicio_de(fim: pd.Timestamp, abertura: dict) -> int:
    """O exercício a que o trimestre pertence: o ano em que ele FECHA. Para o
    ano civil é o ano da data; num exercício jul–jun, o 1T (set) é do ano
    seguinte. O 4T derivado não tem abertura: a própria data é o fecho."""
    ini = abertura.get(fim)
    if ini is None:
        return pd.Timestamp(fim).year
    return (ini + pd.DateOffset(years=1) - pd.Timedelta(days=1)).year


def _numero_do_trimestre(fim: pd.Timestamp, abertura: dict) -> int:
    ini = abertura.get(fim)
    if ini is None:                       # 4T derivado: fecha o exercício
        return 4
    return _indice_do_trimestre(ini, pd.Timestamp(fim))


def _saldo_mais_recente(cd_cvm: str, st: str, codes, keywords) -> tuple:
    """(data, valor) do balanço mais recente, ITR ou DFP — o que for mais novo.

    Depois que a DFP do ano sai e antes do 1T seguinte, o último ITR (set)
    está três meses atrás do balanço anual (dez): pegar só o ITR seria
    defasar a dívida justamente quando o dado novo já existe.
    """
    candidatos: dict = {}
    for tipo in ("itr", "dfp"):
        frame = _company(st, cd_cvm, tipo)
        if frame.empty or "DT_FIM_EXERC" not in frame.columns:
            continue
        candidatos.update(_ts(_series(frame, codes, keywords, chave="DT_FIM_EXERC")))
    if not candidatos:
        return None, None
    data = max(candidatos)
    return data, candidatos[data]


def ltm_series(cd_cvm: str) -> dict:
    """Os últimos 12 meses até o trimestre mais recente publicado.

    Duas naturezas de conta, tratadas de formas diferentes de propósito:

      * **Fluxo** (receita, EBITDA, EBIT, lucro, despesa financeira, caixa
        das operações, capex): soma dos quatro trimestres isolados que
        terminam no ÚLTIMO trimestre. Todas as contas na mesma janela: uma
        conta sem o trimestre mais recente fica vazia, em vez de vir de uma
        janela mais velha com o rótulo da nova (o "LTM 2T26" que na verdade
        era 1T26 só para o EBITDA).
      * **Estoque** (dívida, caixa, patrimônio): o balanço mais recente, ITR
        ou DFP. Somar quatro saldos seria absurdo.

    Devolve {} quando o ITR não está processado ou não fecha 12 meses.
    """
    vazio: dict = {}
    if not cd_cvm:
        return vazio
    tri = _trimestres(cd_cvm)
    iso, abertura = tri["isolado"], tri["abertura"]
    datas = sorted({d for chave in ("receita", "lucro_liquido")
                    for d in (iso.get(chave) or {})})
    if not datas:
        return vazio
    ultimo = datas[-1]

    campos: dict = {}
    for chave in ("receita", "lucro_liquido", "ebit", "ebitda", "despesas_financeiras",
                  "fco", "capex"):
        janela = _ltm(iso.get(chave) or {})
        campos[chave] = janela.get(ultimo)
    deprec = _ltm({d: -v for d, v in (iso.get("da") or {}).items()}).get(ultimo)
    campos["depreciacao"] = abs(deprec) if deprec is not None else None
    if campos.get("capex") is not None:
        campos["capex"] = -abs(campos["capex"])
    campos["fcl"] = (campos["fco"] - abs(campos["capex"])
                     if campos.get("fco") is not None and campos.get("capex") is not None
                     else None)

    _, pl = _saldo_mais_recente(cd_cvm, "bpp", None,
                                ["PATRIMONIO LIQUIDO CONSOLIDADO", "PATRIMONIO LIQUIDO"])
    _, caixa = _saldo_mais_recente(cd_cvm, "bpa", ["1.01.01"], ["CAIXA E EQUIVALENTES"])
    _, aplic = _saldo_mais_recente(cd_cvm, "bpa", ["1.01.02"],
                                   ["APLICACOES FINANCEIRAS", "TITULOS E VALORES MOBILIARIOS"])
    data_div, div_cp = _saldo_mais_recente(cd_cvm, "bpp", ["2.01.04"], None)
    _, div_lp = _saldo_mais_recente(cd_cvm, "bpp", ["2.02.01"], None)
    campos["patrimonio_liquido"] = pl
    if div_cp is not None or div_lp is not None:
        bruta = (div_cp or 0.0) + (div_lp or 0.0)
        campos["divida_liquida"] = bruta - ((caixa or 0.0) + (aplic or 0.0))
        campos["divida_bruta"] = bruta
        campos["divida_cp"] = div_cp
        campos["divida_lp"] = div_lp
    if caixa is not None or aplic is not None:
        campos["caixa_total"] = (caixa or 0.0) + (aplic or 0.0)

    if not any(v is not None for v in campos.values()):
        return vazio

    n = _numero_do_trimestre(ultimo, abertura)
    ano = _exercicio_de(ultimo, abertura)
    return {
        "fim": str(pd.Timestamp(ultimo).date()),
        "rotulo": f"LTM {n}T{str(ano)[-2:]}",
        "trimestre": f"{n}T{str(ano)[-2:]}",
        "exercicio": ano,
        "saldo_em": str(pd.Timestamp(data_div).date()) if data_div is not None else None,
        "campos": campos,
        # Diz ao front quais colunas são saldo: elas não somam 12 meses, e
        # rotulá-las como se somassem seria mentir sobre o que o número é.
        "saldos": ["patrimonio_liquido", "divida_liquida", "divida_bruta",
                   "divida_cp", "divida_lp", "caixa_total"],
    }



# ---------------------------------------------------------------------------
# Extração de contas
# ---------------------------------------------------------------------------

@lru_cache(maxsize=8)
def _por_empresa(st: str, tipo: str) -> dict:
    """Índice CD_CVM → linhas, montado uma vez por demonstrativo.

    A varredura era `df[df["CD_CVM"] == cd]`: uma passada pelo quadro inteiro
    a cada consulta. A tela principal faz isso 90 vezes × 4 demonstrativos ×
    ~15 contas, e o custo aparecia inteiro na primeira abertura — 26 s só para
    montar a lista de ações. Agrupar uma vez troca a varredura por uma busca
    em dicionário.
    """
    df = _frames(tipo).get(st)
    if df is None or df.empty:
        return {}
    return {str(cd): grupo for cd, grupo in df.groupby("CD_CVM", sort=False)}


def _company(st: str, cd_cvm: str, tipo: str = "dfp") -> pd.DataFrame:
    grupo = _por_empresa(st, tipo).get(str(cd_cvm).strip())
    return pd.DataFrame() if grupo is None else grupo


def _series(
    sub: pd.DataFrame,
    codes: Optional[list[str]] = None,
    keywords: Optional[list[str]] = None,
    contains_all: bool = False,
    chave: str = "ANO_REFER",
) -> dict:
    """Série {período: valor} de uma conta.

    Tenta CD_CONTA exato na ordem informada; só cai para busca textual se
    nenhum código bater. Dentro de um período, prefere a conta de menor nível
    hierárquico (mais agregada).

    `chave` é a coluna que define o período: ANO_REFER no anual (um ponto por
    exercício) ou DT_FIM_EXERC no trimestral — lá o ano tem quatro pontos, e
    chavear por ano colapsaria os quatro em um.
    """
    if sub.empty:
        return {}

    # Recortar com `sub[mask]` copiava as nove colunas do quadro — inclusive as
    # de texto, que são Arrow — a cada uma das ~1.400 consultas da tela
    # principal. O recorte agora viaja como máscara e só os três vetores que
    # _collapse usa são materializados.
    for code in codes or []:
        onde = _mascara(sub["CD_CONTA"] == code)
        if onde.any():
            return _collapse(sub, chave, onde)

    if keywords:
        keys = [_norm(k) for k in keywords]
        ds = sub["DS_NORM"]
        onde = np.full(len(sub), contains_all, dtype=bool)
        for k in keys:
            achou = _mascara(ds.str.contains(k, regex=False, na=False))
            onde = (onde & achou) if contains_all else (onde | achou)
        if onde.any():
            return _collapse(sub, chave, onde)
    return {}


def _mascara(serie: pd.Series) -> np.ndarray:
    """Série booleana (possivelmente Arrow, possivelmente com nulos) → vetor."""
    return serie.to_numpy(dtype=bool, na_value=False)


def _periodo(valor, chave: str):
    """A chave de período tipada: ano inteiro no anual, Timestamp no trimestral."""
    return int(valor) if chave == "ANO_REFER" else pd.Timestamp(valor)


def _collapse(hit: pd.DataFrame, chave: str = "ANO_REFER",
              onde: Optional[np.ndarray] = None,
              criterio: Optional[np.ndarray] = None) -> dict:
    """Um valor por período: conta mais agregada; empate pelo maior |valor|.

    Em numpy, não em pandas. Esta função roda ~1.400 vezes só para montar a
    tela principal, e a versão anterior (assign + sort_values + itertuples)
    respondia sozinha por 11 s dos 19 s da primeira abertura: as colunas do
    parquet são de tipo Arrow, e percorrer linha a linha paga uma conversão
    por célula. Aqui o quadro vira três vetores e a escolha é um lexsort.

    `onde` recorta as linhas sem construir um sub-quadro. `criterio` troca o
    desempate padrão (nível hierárquico) por outro — o D&A desempata por
    "cita depreciação E amortização", não por nível.
    """
    val = hit["VL_CONTA_AJUSTADO"].to_numpy(dtype="float64", na_value=np.nan)
    valido = ~np.isnan(val)
    if onde is not None:
        valido &= onde
    if chave == "ANO_REFER":
        periodo = hit[chave].to_numpy(dtype="float64", na_value=np.nan)
        valido &= ~np.isnan(periodo)
    else:
        periodo = hit[chave].astype(str).to_numpy(dtype=object)
    if not valido.any():
        return {}

    val = val[valido]
    periodo = periodo[valido]
    if criterio is None:
        criterio = (hit["_LVL"].to_numpy(dtype="int64") if "_LVL" in hit.columns
                    else np.array([str(c).count(".") for c in hit["CD_CONTA"]], dtype="int64"))
    criterio = criterio[valido]

    # np.unique devolve os períodos já ordenados e o código de cada linha;
    # ordenar pelo código equivale a ordenar pelo período, tanto para o ano
    # inteiro do anual quanto para a data ISO do trimestral.
    periodos, codigo = np.unique(periodo, return_inverse=True)
    codigo = np.asarray(codigo).ravel()
    ordem = np.lexsort((-np.abs(val), criterio, codigo))
    codigo, val = codigo[ordem], val[ordem]

    primeiro = np.empty(len(codigo), dtype=bool)
    primeiro[0] = True
    np.not_equal(codigo[1:], codigo[:-1], out=primeiro[1:])
    escolhidos, valores = periodos[codigo[primeiro]], val[primeiro]

    if chave == "ANO_REFER":
        return {int(p): float(v) for p, v in zip(escolhidos, valores)}
    return {pd.Timestamp(p): float(v) for p, v in zip(escolhidos, valores)}


def _sum_series(*series: dict[int, float]) -> dict[int, float]:
    """Soma séries ano a ano; um ano existe no resultado se existir em alguma."""
    years: set[int] = set()
    for s in series:
        years |= set(s)
    return {y: sum(s.get(y, 0.0) for s in series) for y in sorted(years)}


# ---------------------------------------------------------------------------
# Perfil contábil
# ---------------------------------------------------------------------------

def is_financial_statement(cd_cvm: str) -> bool:
    """Detecta plano de contas de instituição financeira/seguradora.

    Bancos usam 2.08 para Patrimônio Líquido e não possuem 3.01 "Receita de
    Venda de Bens"; a descrição da 3.01 traz "Intermediação Financeira" ou
    "Receitas da Intermediação".
    """
    dre = _company("dre", cd_cvm)
    if dre.empty:
        return False
    top = dre[dre["CD_CONTA"] == "3.01"]["DS_NORM"]
    if top.str.contains("INTERMEDIACAO", na=False).any():
        return True
    if top.str.contains("PREMIOS|SEGUROS|RESSEGURO", regex=True, na=False).any():
        return True
    bpp = _company("bpp", cd_cvm)
    if not bpp.empty:
        pl_codes = set(bpp[bpp["DS_NORM"].str.contains("PATRIMONIO LIQUIDO", na=False)]["CD_CONTA"])
        if "2.08" in pl_codes and "2.03" not in pl_codes:
            return True
    return False


# ---------------------------------------------------------------------------
# Séries anuais consolidadas
# ---------------------------------------------------------------------------

def annual_series(cd_cvm: str, max_years: int = MAX_YEARS) -> dict:
    """Séries anuais por empresa, prontas para o painel.

    Devolve {"years": [...], "financial": bool, "series": {campo: [valores]}}
    com None onde a conta não existe.
    """
    if not cd_cvm:
        return {"years": [], "financial": False, "series": {}, "cnpj": None}

    dre = _company("dre", cd_cvm)
    bpa = _company("bpa", cd_cvm)
    bpp = _company("bpp", cd_cvm)
    dfc = _company("dfc_mi", cd_cvm)
    if dre.empty and bpa.empty:
        return {"years": [], "financial": False, "series": {}, "cnpj": None}

    fin = is_financial_statement(cd_cvm)

    # --- DRE -------------------------------------------------------------
    receita = _series(dre, *CONTA_RECEITA)
    lucro_bruto = _series(dre, ["3.03"], ["RESULTADO BRUTO", "LUCRO BRUTO"])
    ebit = _series(dre, ["3.05"], ["RESULTADO ANTES DO RESULTADO FINANCEIRO",
                                   "RESULTADO OPERACIONAL"])
    res_fin = _series(dre, ["3.06"], ["RESULTADO FINANCEIRO"])
    lucro_liq = _series(dre, *CONTA_LUCRO)
    # Operações descontinuadas: quando vem diferente de zero, a companhia
    # segregou uma operação que está saindo — o sinal mais verificável de
    # reestruturação de portfólio.
    #
    # Casada SÓ por descrição, de propósito. O código muda de plano de contas:
    # é 3.10 na indústria e 3.12 em seguradora, e confiar no número faz o
    # leitor pegar, na BB Seguridade, uma conta que vale bilhões e não tem
    # nada a ver com desinvestimento. A descrição é padronizada pela CVM nos
    # dois planos; o código, não.
    descont = _series(dre, None, ["OPERACOES DESCONTINUADAS"])

    # --- Balanço ---------------------------------------------------------
    ativo = _series(bpa, ["1"], ["ATIVO TOTAL"])
    imobilizado = _series(bpa, ["1.02.03"], ["IMOBILIZADO"])
    intangivel = _series(bpa, ["1.02.04"], ["INTANGIVEL"])
    caixa = _series(bpa, ["1.01.01"], ["CAIXA E EQUIVALENTES"])
    aplic = _series(bpa, ["1.01.02"], ["APLICACOES FINANCEIRAS", "TITULOS E VALORES MOBILIARIOS"])
    passivo = _series(bpp, ["2"], ["PASSIVO TOTAL"])
    # PL: bancos usam 2.08, não-financeiras 2.03 — casar por descrição cobre ambos.
    pl = _series(bpp, None, ["PATRIMONIO LIQUIDO CONSOLIDADO", "PATRIMONIO LIQUIDO"])
    div_cp = _series(bpp, ["2.01.04"], None)
    div_lp = _series(bpp, ["2.02.01"], None)
    divida_bruta = _sum_series(div_cp, div_lp) if (div_cp or div_lp) else {}
    desp_fin = _series(dre, ["3.06.02"], ["DESPESAS FINANCEIRAS"])

    # --- Fluxo de caixa --------------------------------------------------
    fco = _series(dfc, ["6.01"], ["CAIXA LIQUIDO ATIVIDADES OPERACIONAIS"])
    capex = _capex(dfc)
    deprec = _depreciation(dfc)

    # --- Derivadas -------------------------------------------------------
    caixa_total = _sum_series(caixa, aplic) if (caixa or aplic) else {}
    divida_liq = ({y: divida_bruta.get(y, 0.0) - caixa_total.get(y, 0.0)
                   for y in divida_bruta} if divida_bruta and not fin else {})
    ebitda = ({y: ebit[y] + abs(deprec.get(y, 0.0)) for y in ebit if y in deprec}
              if (ebit and deprec and not fin) else {})
    fcl = {y: fco[y] - abs(capex.get(y, 0.0)) for y in fco if y in capex} if (fco and capex) else {}

    fields = {
        "receita": receita,
        "lucro_bruto": lucro_bruto,
        "ebit": ebit,
        "ebitda": ebitda,
        "depreciacao": {y: abs(v) for y, v in deprec.items()},
        "resultado_financeiro": res_fin,
        "lucro_liquido": lucro_liq,
        "descontinuadas": descont,
        "ativo_total": ativo,
        "imobilizado": imobilizado,
        "intangivel": intangivel,
        "passivo_total": passivo,
        "patrimonio_liquido": pl,
        "caixa": caixa,
        "aplicacoes": aplic,
        "caixa_total": caixa_total,
        "divida_bruta": divida_bruta,
        "divida_liquida": divida_liq,
        "divida_cp": div_cp,
        "divida_lp": div_lp,
        "despesas_financeiras": desp_fin,
        "fco": fco,
        "capex": {y: -abs(v) for y, v in capex.items()},
        "fcl": fcl,
    }

    all_years = sorted({y for s in fields.values() for y in s})
    years = all_years[-max_years:]
    series = {k: [v.get(y) for y in years] for k, v in fields.items()}

    cnpj = None
    for frame in (dre, bpa, bpp):
        if not frame.empty:
            cnpj = str(frame["CNPJ_CIA"].iloc[-1])
            break

    return {
        "years": years,
        "financial": fin,
        "series": series,
        "cnpj": cnpj,
        "denom": str(dre["DENOM_CIA"].iloc[-1]) if not dre.empty else None,
        "last_year": years[-1] if years else None,
    }


_DA_RE = r"DEPRECIA|AMORTIZ|EXAUST"
_DA_EXCLUDE = r"DESPESAS ANTECIPADAS|AGIO|MAIS-VALIA|DIREITO DE USO CONTRAPRESTA"


def _depreciation(dfc: pd.DataFrame, chave: str = "ANO_REFER") -> dict:
    """Depreciação, amortização e exaustão a partir do DFC.

    A CVM não padroniza código para D&A: a linha vive em 6.01.01.xx com
    descrição livre. Estratégia, por ano:
      1. linha que cite depreciação E amortização (a consolidada típica);
      2. senão, a de maior valor absoluto que cite qualquer um dos termos.
    Descrições que claramente não são D&A do imobilizado são descartadas.
    """
    if dfc.empty:
        return {}
    cd = dfc["CD_CONTA"]
    base = _mascara(cd.str.startswith("6.01.01"))
    if not base.any():
        base = _mascara(cd.str.startswith("6.01"))
    ds = dfc["DS_NORM"]
    onde = (base
            & _mascara(ds.str.contains(_DA_RE, regex=True, na=False))
            & ~_mascara(ds.str.contains(_DA_EXCLUDE, regex=True, na=False)))
    if not onde.any():
        return {}
    # Preferir a linha que cita depreciação E amortização (a consolidada
    # típica): critério menor ordena primeiro, então o "ambos" vira -1.
    ambos = (_mascara(ds.str.contains("DEPRECIA", na=False))
             & _mascara(ds.str.contains("AMORTIZ", na=False)))
    return _collapse(dfc, chave, onde, criterio=-ambos.astype("int64"))


_CAPEX_RE = (r"IMOBILIZAD|INTANGIVE|ATIVO FIXO|ATIVOS FIXOS|PROPRIEDADE PARA INVESTIMENTO"
             r"|PROPRIEDADES PARA INVESTIMENTO|ATIVO NAO CIRCULANTE|ATIVO PERMANENTE")
_CAPEX_EXCLUDE = (r"VENDA|ALIENACAO|RECEBIMENTO|BAIXA|RESGATE|REDUCAO|RECURSOS PROVENIENTES"
                  r"|DESIMOBILIZ|CAIXA LIQUIDO")


def _capex(dfc: pd.DataFrame, chave: str = "ANO_REFER") -> dict:
    """CAPEX (investimento em imobilizado + intangível), como valor negativo.

    O código 6.02.01 NÃO é padronizado pela CVM — em várias empresas ele é
    "Aumento em Títulos e Valores Mobiliários" ou só parte do imobilizado.
    Por isso somamos todas as linhas de aquisição de imobilizado/intangível
    dentro das atividades de investimento (6.02.xx), excluindo alienações.
    """
    if dfc.empty:
        return {}
    ds = dfc["DS_NORM"]
    val = dfc["VL_CONTA_AJUSTADO"].to_numpy(dtype="float64", na_value=np.nan)
    onde = (_mascara(dfc["CD_CONTA"].str.startswith("6.02."))
            & _mascara(ds.str.contains(_CAPEX_RE, regex=True, na=False))
            & ~_mascara(ds.str.contains(_CAPEX_EXCLUDE, regex=True, na=False))
            & ~np.isnan(val)
            & _mascara(dfc[chave].notna()))
    if not onde.any():
        return {}

    val = val[onde]
    lvl = dfc["_LVL"].to_numpy(dtype="int64")[onde]
    bruto = dfc[chave].to_numpy(dtype=object)[onde]
    periodos, codigo = np.unique(bruto, return_inverse=True)
    codigo = np.asarray(codigo).ravel()

    out: dict = {}
    for i, periodo in enumerate(periodos):
        no_periodo = codigo == i
        # Evita dupla contagem quando a empresa detalha a conta em sub-níveis:
        # fica só com o nível hierárquico mais agregado presente no ano.
        agregado = no_periodo & (lvl == lvl[no_periodo].min())
        vals = val[agregado]
        neg = vals[vals < 0].sum()
        total = neg if neg < 0 else -np.abs(vals).sum()
        if total != 0:
            out[_periodo(periodo, chave)] = float(total)
    return out


# ---------------------------------------------------------------------------
# DRE estruturada — a tabela de leitura da página da empresa
# ---------------------------------------------------------------------------

# As contas na ordem em que a DRE se lê, de cima para baixo. `tipo` é o que a
# tela usa para formatar: `total` tem borda, `hero` é o lucro líquido, `margem`
# é a linha cinza sob um resultado, e `deducao` é o que aparece entre
# parênteses. Financeira usa um plano reduzido: em banco não existe CPV nem
# EBITDA, e mostrar as linhas vazias sugeriria que o dado faltou.
CONTA_CPV = (["3.02"], ["CUSTO DOS BENS", "CUSTO DOS PRODUTOS", "CUSTO DAS MERCADORIAS"])
CONTA_BRUTO = (["3.03"], ["RESULTADO BRUTO", "LUCRO BRUTO"])
CONTA_DESPESAS = (["3.04"], ["DESPESAS/RECEITAS OPERACIONAIS", "DESPESAS OPERACIONAIS"])
CONTA_EBIT = (["3.05"], ["RESULTADO ANTES DO RESULTADO FINANCEIRO", "RESULTADO OPERACIONAL"])
CONTA_RES_FIN = (["3.06"], ["RESULTADO FINANCEIRO"])
CONTA_IR = (["3.08"], ["IMPOSTO DE RENDA", "CONTRIBUICAO SOCIAL"])

_LINHAS_DRE = [
    ("receita", "Receita líquida", "valor", CONTA_RECEITA),
    ("cpv", "(−) CPV", "deducao", CONTA_CPV),
    ("lucro_bruto", "Lucro bruto", "total", CONTA_BRUTO),
    ("mg_bruta", "margem bruta", "margem", None),
    ("despesas", "(−) Despesas operacionais", "deducao", CONTA_DESPESAS),
    ("ebitda", "EBITDA", "total", None),
    ("mg_ebitda", "margem EBITDA", "margem", None),
    ("da", "(−) D&A", "deducao", None),
    ("ebit", "EBIT", "total", CONTA_EBIT),
    ("resultado_financeiro", "Resultado financeiro", "valor", CONTA_RES_FIN),
    ("ir", "(−) IR / CSLL", "deducao", CONTA_IR),
    ("lucro_liquido", "Lucro líquido", "hero", CONTA_LUCRO),
    ("mg_liquida", "margem líquida", "margem", None),
]

# Em instituição financeira, receita é intermediação e não há CPV/EBITDA.
_LINHAS_DRE_FINANCEIRA = ["receita", "resultado_financeiro", "ir",
                          "lucro_liquido", "mg_liquida"]

# De qual linha cada margem é calculada.
_BASE_DA_MARGEM = {"mg_bruta": "lucro_bruto", "mg_ebitda": "ebitda",
                   "mg_liquida": "lucro_liquido"}


def _monta_dre(series: dict, periodos: list, fin: bool) -> list[dict]:
    """As linhas da DRE a partir das séries {período: valor} já extraídas.

    EBITDA e D&A são derivados: a CVM não os publica como conta. D&A vem da
    DFC (onde é um ajuste do FCO) e o EBITDA é EBIT + |D&A| — a mesma conta
    que `annual_series` faz, para os dois lugares não divergirem.
    """
    linhas = []
    for chave, rotulo, tipo, _conta in _LINHAS_DRE:
        if fin and chave not in _LINHAS_DRE_FINANCEIRA:
            continue
        if tipo == "margem":
            base = series.get(_BASE_DA_MARGEM[chave]) or {}
            receita = series.get("receita") or {}
            # A chave pode existir valendo None (coluna acumulada incompleta):
            # testar presença não basta, tem de ser número dos dois lados.
            valores = []
            for p in periodos:
                b, r = base.get(p), receita.get(p)
                valores.append(b / r if isinstance(b, (int, float))
                               and isinstance(r, (int, float)) and r else None)
        else:
            serie = series.get(chave) or {}
            valores = [serie.get(p) for p in periodos]
        # Linha só de vazio ou só de zero não é informação: é o plano de
        # contas da companhia não usando aquela conta (o IR do banco, que
        # vem zerado na consolidada). Uma fileira de zeros numa tabela de
        # leitura sugere que a empresa não pagou imposto — ela não diz isso.
        if all(v is None or v == 0 for v in valores):
            continue
        linhas.append({"chave": chave, "rotulo": rotulo, "tipo": tipo,
                       "valores": valores})
    return linhas


def _cagr(valores: list, anos: int) -> Optional[float]:
    """CAGR entre o primeiro e o último valor da série, ambos positivos.

    Sinal trocado no meio (prejuízo virando lucro) não tem taxa composta que
    signifique alguma coisa — devolve None em vez de um número bonito.
    """
    validos = [(i, v) for i, v in enumerate(valores) if isinstance(v, (int, float))]
    if len(validos) < 2 or anos <= 0:
        return None
    (i0, v0), (i1, v1) = validos[0], validos[-1]
    span = i1 - i0
    if span <= 0 or v0 <= 0 or v1 <= 0:
        return None
    return (v1 / v0) ** (1.0 / span) - 1.0


def _series_dre_anual(dre: pd.DataFrame, dfc: pd.DataFrame, fin: bool) -> dict:
    saida = {}
    for chave, _rot, tipo, conta in _LINHAS_DRE:
        if conta is not None:
            saida[chave] = _series(dre, *conta)
    deprec = {a: abs(v) for a, v in _depreciation(dfc).items()} if not dfc.empty else {}
    saida["da"] = {a: -v for a, v in deprec.items()}
    ebit = saida.get("ebit") or {}
    saida["ebitda"] = ({a: ebit[a] + deprec[a] for a in ebit if a in deprec}
                       if not fin else {})
    return saida



# Linhas que somam no tempo (o resto são margens, calculadas por coluna).
_SOMAVEIS = {"receita", "cpv", "lucro_bruto", "despesas", "ebitda", "da", "ebit",
             "resultado_financeiro", "ir", "lucro_liquido"}


def dre_completa(cd_cvm: str, max_anos: int = 6) -> dict:
    """A DRE de leitura inteira: exercícios fechados, os trimestres de cada um,
    o ano em curso e os últimos 12 meses — numa grade só de colunas.

    Colunas, em ordem, cada uma com `tipo`:
      * ``tri``  — trimestre isolado (1T25…), ANTES do seu exercício; a tela
        os mostra quando o usuário abre o ano. `derivado` marca o 4T, que é
        DFP − 9M (o ITR não publica o 4T).
      * ``ano``  — exercício fechado (DFP).
      * ``ytd``  — o ano em curso, acumulado (1S26, 9M26), só quando há mais
        de um trimestre e todos eles; com um só, a coluna seria o próprio 1T.
      * ``ltm``  — soma dos 4 últimos trimestres, quando o último trimestre é
        posterior ao último exercício fechado (senão ela repetiria o ano).

    `grupo` liga cada trimestre ao exercício dele. Sem ITR, sai só o anual,
    como antes.
    """
    vazio = {"colunas": [], "linhas": [], "financial": False, "cagr_span": 0}
    if not cd_cvm:
        return vazio
    dre_a = _company("dre", cd_cvm)
    fin = is_financial_statement(cd_cvm)
    anual = (_series_dre_anual(dre_a, _company("dfc_mi", cd_cvm), fin)
             if not dre_a.empty else {})
    anos = sorted({a for serie in anual.values() for a in serie})[-max_anos:]

    tri = _trimestres(cd_cvm)
    iso, abertura = tri["isolado"], tri["abertura"]
    por_exercicio: dict = {}
    for d in sorted({d for serie in iso.values() for d in serie}):
        por_exercicio.setdefault(_exercicio_de(d, abertura), []).append(d)

    ultimo_ano = anos[-1] if anos else None
    parciais = [a for a in sorted(por_exercicio)
                if ultimo_ano is None or a > ultimo_ano]
    if not anos and not parciais:
        return vazio

    colunas: list = []
    valores: list = []            # um {chave: valor} por coluna

    def tri_cols(exercicio: int) -> list:
        idx = []
        for d in por_exercicio.get(exercicio, []):
            n = _numero_do_trimestre(d, abertura)
            colunas.append({"tipo": "tri", "rotulo": f"{n}T{str(exercicio)[-2:]}",
                            "grupo": exercicio, "fim": str(pd.Timestamp(d).date()),
                            "derivado": d not in abertura})
            valores.append({k: serie.get(d) for k, serie in iso.items()})
            idx.append(len(colunas) - 1)
        return idx

    for a in anos:
        tris = tri_cols(a)
        colunas.append({"tipo": "ano", "rotulo": str(a), "grupo": a, "n_tri": len(tris)})
        valores.append({k: serie.get(a) for k, serie in anual.items()})

    for a in parciais:
        tris = tri_cols(a)
        if len(tris) < 2:
            continue
        n = _numero_do_trimestre(pd.Timestamp(colunas[tris[-1]]["fim"]), abertura)
        # Acumulado só com o ano completo até ali: faltando um trimestre, a
        # soma seria menor que a real e passaria por número certo.
        if [_numero_do_trimestre(pd.Timestamp(colunas[i]["fim"]), abertura)
                for i in tris] != list(range(1, n + 1)):
            continue
        rot = {2: "1S", 3: "9M", 4: "12M"}.get(n, f"{n}T")
        colunas.append({"tipo": "ytd", "rotulo": f"{rot}{str(a)[-2:]}", "grupo": a,
                        "n_tri": len(tris)})
        valores.append({k: (sum(valores[i].get(k) for i in tris)
                            if all(valores[i].get(k) is not None for i in tris) else None)
                        for k in iso if k in _SOMAVEIS})

    # 12 meses: só quando há trimestre depois do último exercício fechado.
    datas = sorted(d for a in parciais for d in por_exercicio.get(a, []))
    if datas:
        ultimo = datas[-1]
        n = _numero_do_trimestre(ultimo, abertura)
        ex = _exercicio_de(ultimo, abertura)
        ltm = {k: _ltm(iso.get(k) or {}).get(ultimo) for k in iso if k in _SOMAVEIS}
        if any(v is not None for v in ltm.values()):
            colunas.append({"tipo": "ltm", "rotulo": f"12m · {n}T{str(ex)[-2:]}",
                            "grupo": None, "fim": str(pd.Timestamp(ultimo).date())})
            valores.append(ltm)

    periodos = list(range(len(colunas)))
    chaves = {k for v in valores for k in v}
    series_col = {k: {i: valores[i].get(k) for i in periodos} for k in chaves}
    linhas = _monta_dre(series_col, periodos, fin)
    i_anos = [i for i, c in enumerate(colunas) if c["tipo"] == "ano"]
    for linha in linhas:
        if linha["tipo"] in ("valor", "total", "hero") and len(i_anos) > 1:
            linha["cagr"] = _cagr([linha["valores"][i] for i in i_anos], len(i_anos) - 1)
        else:
            linha["cagr"] = None
    return {"colunas": colunas, "linhas": linhas, "financial": fin,
            "cagr_span": max(len(i_anos) - 1, 0)}


def shares_outstanding(cnpj: Optional[str]) -> Optional[float]:
    """Total de ações integralizadas (capital social da CVM)."""
    if not cnpj:
        return None
    tbl = _shares_table()
    if tbl.empty:
        return None
    digits = re.sub(r"\D", "", str(cnpj))
    hit = tbl[tbl["CNPJ_DIG"] == digits]
    if hit.empty:
        return None
    return float(hit.iloc[0]["shares"])


def shares_from_eps(cd_cvm: Optional[str]) -> Optional[float]:
    """Ações implícitas no lucro por ação publicado (conta 3.99 da DRE).

    Fallback para as empresas ausentes do arquivo de capital social:
    se a companhia informa LPA básico, o número de ações sai de
    lucro líquido ÷ LPA. É a média ponderada do exercício, o que basta
    para múltiplos de mercado.
    """
    if not cd_cvm:
        return None
    dre = _company("dre", cd_cvm)
    if dre.empty:
        return None

    lpa = _series(dre, ["3.99.01.01"], None)
    if not lpa:
        lpa = _series(dre, ["3.99.01.02"], None)
    lucro = _series(dre, ["3.11", "3.09"], ["LUCRO/PREJUIZO CONSOLIDADO DO PERIODO",
                                            "LUCRO/PREJUIZO DO PERIODO", "LUCRO LIQUIDO"])
    if not lpa or not lucro:
        return None

    for year in sorted(set(lpa) & set(lucro), reverse=True):
        eps, li = lpa[year], lucro[year]
        if not eps or not li or abs(eps) < 1e-9:
            continue
        shares = li / eps
        if shares <= 0:
            continue
        # A CVM publica o LPA já em R$/ação, mas o pipeline aplica a escala
        # do balanço (milhares) a todas as linhas — inflando a conta 3.99 em
        # 1.000×. Uma companhia aberta com menos de 5 milhões de ações é
        # implausível, então essa é a assinatura do erro de escala.
        if shares < 5e6:
            shares *= 1000.0
        if shares < 1e6:
            continue
        return float(shares)
    return None
