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
MAX_TRIMESTRES = 12

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
    return any(not df.empty for df in _frames().values())


def quarterly_available() -> bool:
    """True quando o pipeline já gerou os parquets do ITR."""
    return any(not df.empty for df in _frames("itr").values())


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


def ltm_series(cd_cvm: str) -> dict:
    """O ano corrente parcial: 12 meses móveis até o último ITR publicado.

    A tabela de demonstrações mostrava só exercícios fechados, então o ano em
    curso simplesmente não existia nela — e é justamente o período que o
    usuário está tentando entender.

    Duas naturezas de conta, tratadas de formas diferentes de propósito:

      * **Fluxo** (receita, EBITDA, EBIT, lucro, caixa das operações, capex):
        soma dos quatro trimestres isolados. Somar acumulados daria o dobro.
      * **Estoque** (dívida líquida, patrimônio líquido): é saldo, não fluxo.
        Vale o do balanço mais recente — somar quatro seria absurdo.

    Devolve {} quando o ITR não está processado ou não fecha 12 meses.
    """
    vazio: dict = {}
    if not cd_cvm:
        return vazio

    dre = _acumulado_do_exercicio(_company("dre", cd_cvm, "itr"))
    if dre.empty or "DT_INI_EXERC" not in dre.columns:
        return vazio
    abertura = (dre.drop_duplicates("DT_FIM_EXERC")
                   .set_index("DT_FIM_EXERC")["DT_INI_EXERC"].to_dict())
    if not abertura:
        return vazio

    dfc = _acumulado_do_exercicio(_company("dfc_mi", cd_cvm, "itr"))
    dre_anual = _company("dre", cd_cvm)
    dfc_anual = _company("dfc_mi", cd_cvm)

    def ltm_de(acumulado: dict, anual: dict) -> Optional[float]:
        if not acumulado:
            return None
        isolado = _desacumula(acumulado, abertura, anual or {})
        janela = _ltm(isolado)
        return janela.get(max(janela)) if janela else None

    # --- fluxos da DRE ----------------------------------------------------
    campos: dict = {}
    for nome, conta in (("receita", CONTA_RECEITA), ("lucro_liquido", CONTA_LUCRO),
                        ("ebit", (["3.05"], ["RESULTADO ANTES DO RESULTADO FINANCEIRO",
                                             "RESULTADO OPERACIONAL"]))):
        campos[nome] = ltm_de(_series(dre, *conta, chave="DT_FIM_EXERC"),
                              _series(dre_anual, *conta) if not dre_anual.empty else {})

    # --- fluxos do DFC ----------------------------------------------------
    if not dfc.empty:
        fco = ltm_de(_series(dfc, ["6.01"], ["CAIXA LIQUIDO ATIVIDADES OPERACIONAIS"],
                             chave="DT_FIM_EXERC"),
                     _series(dfc_anual, ["6.01"], ["CAIXA LIQUIDO ATIVIDADES OPERACIONAIS"])
                     if not dfc_anual.empty else {})
        capex = ltm_de(_capex(dfc, "DT_FIM_EXERC"),
                       _capex(dfc_anual) if not dfc_anual.empty else {})
        deprec = ltm_de(_depreciation(dfc, "DT_FIM_EXERC"),
                        _depreciation(dfc_anual) if not dfc_anual.empty else {})
        campos["fco"] = fco
        campos["capex"] = -abs(capex) if capex is not None else None
        campos["depreciacao"] = abs(deprec) if deprec is not None else None
        campos["fcl"] = (fco - abs(capex)) if (fco is not None and capex is not None) else None
        if campos.get("ebit") is not None and deprec is not None:
            campos["ebitda"] = campos["ebit"] + abs(deprec)

    # --- estoques do balanço ---------------------------------------------
    bpa = _company("bpa", cd_cvm, "itr")
    bpp = _company("bpp", cd_cvm, "itr")

    def saldo(frame, codes, keywords) -> Optional[float]:
        if frame.empty:
            return None
        serie = _series(frame, codes, keywords, chave="DT_FIM_EXERC")
        return serie.get(max(serie)) if serie else None

    pl = saldo(bpp, None, ["PATRIMONIO LIQUIDO CONSOLIDADO", "PATRIMONIO LIQUIDO"])
    caixa = saldo(bpa, ["1.01.01"], ["CAIXA E EQUIVALENTES"])
    aplic = saldo(bpa, ["1.01.02"], ["APLICACOES FINANCEIRAS", "TITULOS E VALORES MOBILIARIOS"])
    div_cp = saldo(bpp, ["2.01.04"], None)
    div_lp = saldo(bpp, ["2.02.01"], None)
    campos["patrimonio_liquido"] = pl
    if div_cp is not None or div_lp is not None:
        bruta = (div_cp or 0.0) + (div_lp or 0.0)
        campos["divida_liquida"] = bruta - ((caixa or 0.0) + (aplic or 0.0))

    if not any(v is not None for v in campos.values()):
        return vazio

    fim = max(abertura)
    return {
        "fim": str(pd.Timestamp(fim).date()),
        "rotulo": f"LTM {_indice_do_trimestre(pd.Timestamp(abertura[fim]), pd.Timestamp(fim))}"
                  f"T{str(pd.Timestamp(fim).year)[-2:]}",
        "campos": campos,
        # Diz ao front quais colunas são saldo: elas não somam 12 meses, e
        # rotulá-las como se somassem seria mentir sobre o que o número é.
        "saldos": ["patrimonio_liquido", "divida_liquida"],
    }


def quarterly_series(cd_cvm: str, max_tri: int = MAX_TRIMESTRES) -> dict:
    """Trimestres isolados e LTM por empresa, prontos para o painel.

    Devolve {"pontos": [...], "campos": [...]}; lista vazia quando o pipeline
    ainda não gerou os parquets do ITR — e aí o painel segue anual.
    """
    vazio: dict = {"pontos": [], "campos": []}
    if not cd_cvm:
        return vazio

    dre = _company("dre", cd_cvm, "itr")
    if dre.empty or "DT_FIM_EXERC" not in dre.columns:
        return vazio
    dre = _acumulado_do_exercicio(dre)
    if dre.empty:
        return vazio

    abertura = (dre.drop_duplicates("DT_FIM_EXERC")
                   .set_index("DT_FIM_EXERC")["DT_INI_EXERC"].to_dict()
                if "DT_INI_EXERC" in dre.columns else {})
    if not abertura:
        return vazio

    campos = {"receita": CONTA_RECEITA, "lucro_liquido": CONTA_LUCRO}
    acumulado = {nome: _series(dre, cod, kw, chave="DT_FIM_EXERC")
                 for nome, (cod, kw) in campos.items()}
    if not any(acumulado.values()):
        return vazio

    dre_anual = _company("dre", cd_cvm)
    anual = ({nome: _series(dre_anual, cod, kw) for nome, (cod, kw) in campos.items()}
             if not dre_anual.empty else {})

    isolado = {nome: _desacumula(serie, abertura, anual.get(nome, {}))
               for nome, serie in acumulado.items()}
    ltm = {nome: _ltm(serie) for nome, serie in isolado.items()}

    datas = sorted(set().union(*[set(s) for s in isolado.values()]))[-max_tri:]
    pontos = []
    for fim in datas:
        ini = abertura.get(fim)
        # O 4T é derivado: não tem linha própria no ITR, logo não tem abertura.
        derivado = ini is None
        if derivado:
            ini = pd.Timestamp(fim) - pd.DateOffset(years=1) + pd.Timedelta(days=1)
        tri = _indice_do_trimestre(pd.Timestamp(ini), pd.Timestamp(fim))
        ponto = {
            "fim": str(pd.Timestamp(fim).date()),
            "rotulo": f"{tri}T{str(pd.Timestamp(fim).year)[-2:]}",
            "derivado": derivado,
        }
        for nome in campos:
            ponto[nome] = isolado[nome].get(fim)
            ponto[nome + "_ltm"] = ltm[nome].get(fim)
        pontos.append(ponto)

    return {"pontos": pontos, "campos": list(campos)}


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


def dre_anual(cd_cvm: str, max_anos: int = 6) -> dict:
    """DRE dos últimos exercícios, com CAGR da janela inteira."""
    vazio = {"anos": [], "linhas": [], "financial": False, "cagr_span": 0}
    if not cd_cvm:
        return vazio
    dre = _company("dre", cd_cvm)
    if dre.empty:
        return vazio
    fin = is_financial_statement(cd_cvm)
    series = _series_dre_anual(dre, _company("dfc_mi", cd_cvm), fin)

    anos = sorted({a for s in series.values() for a in s})[-max_anos:]
    if not anos:
        return vazio
    linhas = _monta_dre(series, anos, fin)
    for linha in linhas:
        # Margem não tem CAGR: taxa composta de um percentual não quer dizer
        # nada. Dedução tampouco — o CAGR do CPV interessa em módulo, e ele
        # já é lido junto da receita.
        linha["cagr"] = (_cagr(linha["valores"], len(anos) - 1)
                         if linha["tipo"] in ("valor", "total", "hero") else None)
    return {"anos": anos, "linhas": linhas, "financial": fin,
            "cagr_span": len(anos) - 1}


def dre_trimestral(cd_cvm: str) -> dict:
    """Trimestres do ano corrente, desacumulados, com Δ contra o ano anterior.

    O ITR vem acumulado no exercício; a desacumulação é a mesma de
    `quarterly_series`. O Δ a/a compara cada trimestre com o mesmo trimestre
    do ano anterior — que é a comparação que a sazonalidade não distorce.
    """
    vazio = {"colunas": [], "linhas": [], "financial": False, "ano": None}
    if not cd_cvm:
        return vazio
    dre = _company("dre", cd_cvm, "itr")
    if dre.empty or "DT_FIM_EXERC" not in dre.columns:
        return vazio
    dre = _acumulado_do_exercicio(dre)
    if dre.empty:
        return vazio
    # Chaves normalizadas para Timestamp: as séries vêm de _collapse com
    # Timestamp, e se a coluna do parquet estiver como texto o `.get()` daria
    # None para tudo — a tabela sumiria inteira, sem erro nenhum. Falha
    # silenciosa é a pior; normalizar aqui custa nada.
    abertura = {}
    if "DT_INI_EXERC" in dre.columns:
        for fim, ini in (dre.drop_duplicates("DT_FIM_EXERC")
                            .set_index("DT_FIM_EXERC")["DT_INI_EXERC"].to_dict().items()):
            abertura[pd.Timestamp(fim)] = pd.Timestamp(ini)
    if not abertura:
        return vazio

    fin = is_financial_statement(cd_cvm)
    dre_anual_df = _company("dre", cd_cvm)
    dfc_itr = _company("dfc_mi", cd_cvm, "itr")

    acumulado, anual = {}, {}
    for chave, _rot, tipo, conta in _LINHAS_DRE:
        if conta is None:
            continue
        acumulado[chave] = _series(dre, *conta, chave="DT_FIM_EXERC")
        anual[chave] = _series(dre_anual_df, *conta) if not dre_anual_df.empty else {}
    if not any(acumulado.values()):
        return vazio

    series = {c: _desacumula(s, abertura, anual.get(c, {})) for c, s in acumulado.items()}

    # D&A trimestral vem da DFC do ITR, também acumulada no exercício.
    if not dfc_itr.empty:
        da_acc = {d: abs(v) for d, v in _depreciation(dfc_itr, chave="DT_FIM_EXERC").items()}
        da_anual = ({a: abs(v) for a, v in _depreciation(_company("dfc_mi", cd_cvm)).items()}
                    if not _company("dfc_mi", cd_cvm).empty else {})
        deprec = _desacumula(da_acc, abertura, da_anual)
    else:
        deprec = {}
    series["da"] = {d: -v for d, v in deprec.items()}
    ebit = series.get("ebit") or {}
    series["ebitda"] = ({d: ebit[d] + deprec[d] for d in ebit if d in deprec}
                        if not fin else {})

    datas = sorted({d for s in series.values() for d in s})
    if not datas:
        return vazio
    ano = pd.Timestamp(datas[-1]).year
    do_ano = [d for d in datas if pd.Timestamp(d).year == ano]
    if not do_ano:
        return vazio

    colunas = []
    for fim in do_ano:
        ini = abertura.get(fim)
        derivado = ini is None                       # o 4T não tem linha própria
        if derivado:
            ini = pd.Timestamp(fim) - pd.DateOffset(years=1) + pd.Timedelta(days=1)
        tri = _indice_do_trimestre(pd.Timestamp(ini), pd.Timestamp(fim))
        colunas.append({"fim": str(pd.Timestamp(fim).date()),
                        "rotulo": f"{tri}T{str(ano)[-2:]}", "tri": tri,
                        "derivado": derivado, "acumulado": False})

    # A coluna acumulada: 1S, 9M ou o ano, conforme quantos trimestres saíram.
    n = len(colunas)
    rotulo_acc = {1: None, 2: "1S", 3: "9M", 4: "Ano"}.get(n)
    if rotulo_acc:
        colunas.append({"fim": colunas[-1]["fim"],
                        "rotulo": f"{rotulo_acc}{str(ano)[-2:]}",
                        "tri": None, "derivado": False, "acumulado": True})

    # A chave de período é o ÍNDICE da coluna, não a data-fim: a coluna
    # acumulada termina no mesmo dia do último trimestre, e chavear por data
    # faria uma sobrescrever a outra — o 2T apareceria com o valor do 1S.
    periodos = list(range(len(colunas)))
    somaveis = {"receita", "cpv", "lucro_bruto", "despesas", "ebitda", "da",
                "ebit", "resultado_financeiro", "ir", "lucro_liquido"}
    series_col = {}
    for chave, serie in series.items():
        por_periodo = {}
        for i, col in enumerate(colunas):
            if not col["acumulado"]:
                por_periodo[i] = serie.get(pd.Timestamp(col["fim"]))
            elif chave in somaveis:
                vals = [serie.get(pd.Timestamp(c["fim"])) for c in colunas[:i]]
                vals = [v for v in vals if v is not None]
                # Acumulado incompleto seria menor que a soma real e passaria
                # despercebido: sem todos os trimestres, a coluna fica vazia.
                por_periodo[i] = (sum(vals) if len(vals) == i else None)
        series_col[chave] = por_periodo

    linhas = _monta_dre(series_col, periodos, fin)

    # Δ a/a: mesmo trimestre do ano anterior, por índice de trimestre.
    anterior = {}
    for chave, serie in series.items():
        por_tri = {}
        for d, v in serie.items():
            if pd.Timestamp(d).year != ano - 1:
                continue
            ini_ant = abertura.get(d)
            if ini_ant is None:
                ini_ant = pd.Timestamp(d) - pd.DateOffset(years=1) + pd.Timedelta(days=1)
            por_tri[_indice_do_trimestre(pd.Timestamp(ini_ant), pd.Timestamp(d))] = v
        anterior[chave] = por_tri

    for linha in linhas:
        if linha["tipo"] == "margem":
            linha["yoy"] = [None] * len(colunas)
            continue
        yoy = []
        for i, col in enumerate(colunas):
            atual = linha["valores"][i]
            if col["acumulado"]:
                base = [anterior.get(linha["chave"], {}).get(c["tri"]) for c in colunas[:i]]
                base = [b for b in base if b is not None]
                antes = sum(base) if len(base) == i else None
            else:
                antes = anterior.get(linha["chave"], {}).get(col["tri"])
            # Base negativa ou zero não produz variação percentual legível.
            yoy.append((atual / antes - 1) if (isinstance(atual, (int, float))
                                               and isinstance(antes, (int, float))
                                               and antes > 0) else None)
        linha["yoy"] = yoy

    return {"colunas": colunas, "linhas": linhas, "financial": fin, "ano": ano}


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
