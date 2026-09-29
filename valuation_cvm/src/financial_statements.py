"""
Módulo para carregar, filtrar e construir snapshots financeiros de empresas.
"""

from typing import Dict, List, Optional

import pandas as pd

from .config import get_processed_path
from .logger import logger


# ---------------------------------------------------------------------------
# Carregamento de demonstrativos processados
# ---------------------------------------------------------------------------

def load_processed_statement(statement: str, tipo_doc: str) -> pd.DataFrame:
    """
    Carrega o parquet processado de um demonstrativo.

    Exemplo:
        load_processed_statement("DRE", "DFP")
        load_processed_statement("BPA", "ITR")
    """
    parquet_path = get_processed_path(statement.lower(), tipo_doc.lower(), "parquet")

    if not parquet_path.exists():
        logger.warning(
            "Arquivo processado não encontrado: %s. "
            "Execute o pipeline primeiro: python -m src.main",
            parquet_path,
        )
        return pd.DataFrame()

    df = pd.read_parquet(parquet_path)
    logger.info("Carregado %s: %d registros.", parquet_path.name, len(df))
    return df


# ---------------------------------------------------------------------------
# Extração de contas contábeis
# ---------------------------------------------------------------------------

def extract_account(
    df: pd.DataFrame,
    cd_cvm: Optional[str] = None,
    account_keywords: Optional[List[str]] = None,
    cd_conta: Optional[str] = None,
    exact_match: bool = False,
) -> pd.DataFrame:
    """
    Busca contas em um demonstrativo filtradas por empresa, palavras-chave ou código.

    Parâmetros:
        df:               DataFrame do demonstrativo
        cd_cvm:           CD_CVM da empresa (string)
        account_keywords: Lista de palavras-chave para buscar em DS_CONTA
        cd_conta:         Código exato da conta (ex.: "3.01")
        exact_match:      Se True, exige que TODAS as keywords estejam presentes

    Exemplos:
        extract_account(dre, cd_cvm="9512", account_keywords=["receita", "venda"])
        extract_account(dre, cd_cvm="9512", account_keywords=["lucro líquido"])
        extract_account(bpp, cd_cvm="9512", account_keywords=["empréstimos"])
    """
    if df.empty:
        return pd.DataFrame()

    mask = pd.Series([True] * len(df), index=df.index)

    # Filtro por empresa
    if cd_cvm is not None and "CD_CVM" in df.columns:
        mask &= df["CD_CVM"].astype(str).str.strip() == str(cd_cvm).strip()

    # Filtro por código de conta
    if cd_conta is not None and "CD_CONTA" in df.columns:
        mask &= df["CD_CONTA"].astype(str).str.strip() == str(cd_conta).strip()

    # Filtro por palavras-chave em DS_CONTA
    if account_keywords and "DS_CONTA" in df.columns:
        ds_upper = df["DS_CONTA"].fillna("").str.upper()
        if exact_match:
            kw_mask = pd.Series([True] * len(df), index=df.index)
            for kw in account_keywords:
                kw_mask &= ds_upper.str.contains(kw.upper(), regex=False, na=False)
        else:
            kw_mask = pd.Series([False] * len(df), index=df.index)
            for kw in account_keywords:
                kw_mask |= ds_upper.str.contains(kw.upper(), regex=False, na=False)
        mask &= kw_mask

    result = df[mask].copy()
    return result.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Demonstrativo mais recente de uma empresa
# ---------------------------------------------------------------------------

def get_latest_company_statement(
    cd_cvm: str,
    statement: str,
    tipo_doc: str = "DFP",
) -> pd.DataFrame:
    """
    Retorna o demonstrativo mais recente da empresa.

    Filtra por CD_CVM e retorna apenas a última data de referência disponível.
    """
    df = load_processed_statement(statement, tipo_doc)
    if df.empty:
        return pd.DataFrame()

    company_df = df[df["CD_CVM"].astype(str).str.strip() == str(cd_cvm).strip()].copy()
    if company_df.empty:
        logger.warning("Empresa CD_CVM='%s' não encontrada em %s %s.", cd_cvm, tipo_doc, statement)
        return pd.DataFrame()

    # Usar VERSAO mais recente para o último período
    date_col = "DT_REFER" if "DT_REFER" in company_df.columns else "DT_FIM_EXERC"
    if date_col in company_df.columns:
        last_date = company_df[date_col].max()
        company_df = company_df[company_df[date_col] == last_date].copy()

    return company_df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Helpers internos de extração de valor
# ---------------------------------------------------------------------------

def _latest_year_mask(df: pd.DataFrame) -> pd.DataFrame:
    """Filtra o DataFrame para o exercício mais recente disponível.

    Os arquivos processados expõem ANO_REFER e/ou DT_FIM_EXERC (não DT_REFER).
    """
    if df.empty:
        return df
    if "ANO_REFER" in df.columns and df["ANO_REFER"].notna().any():
        last = df["ANO_REFER"].max()
        return df[df["ANO_REFER"] == last]
    for dc in ("DT_FIM_EXERC", "DT_REFER"):
        if dc in df.columns and df[dc].notna().any():
            last = df[dc].max()
            return df[df[dc] == last]
    return df


def _pick_value(
    df: pd.DataFrame,
    cd_cvm: str,
    cd_contas: Optional[List[str]] = None,
    keywords: Optional[List[str]] = None,
    year: Optional[int] = None,
    value_col: str = "VL_CONTA_AJUSTADO",
) -> Optional[float]:
    """Extrai o valor de uma conta no exercício mais recente (ou `year`).

    Estratégia robusta:
        1. Filtra a empresa (CD_CVM)
        2. Filtra o ano (o mais recente por padrão)
        3. Tenta casar por CD_CONTA exato (Plano de Contas Padronizado CVM) — preferencial
        4. Se não houver código, casa por palavra-chave em DS_CONTA (conta de
           menor nível hierárquico, mais agregada)

    Códigos CD_CONTA são muito mais confiáveis que texto: a CVM padroniza os
    níveis 1–3 do plano de contas para empresas não-financeiras.
    """
    if df.empty or "CD_CVM" not in df.columns:
        return None

    sub = df[df["CD_CVM"].astype(str).str.strip() == str(cd_cvm).strip()].copy()
    if sub.empty or value_col not in sub.columns:
        return None

    if year is not None and "ANO_REFER" in sub.columns:
        sub = sub[sub["ANO_REFER"] == year]
    else:
        sub = _latest_year_mask(sub)
    if sub.empty:
        return None

    # 1) Match exato por CD_CONTA (preferencial)
    if cd_contas and "CD_CONTA" in sub.columns:
        codes = sub["CD_CONTA"].astype(str).str.strip()
        for code in cd_contas:
            hit = sub[codes == code]
            v = hit[value_col].dropna()
            if not v.empty:
                return float(v.iloc[0])

    # 2) Fallback por palavra-chave em DS_CONTA
    if keywords and "DS_CONTA" in sub.columns:
        ds = sub["DS_CONTA"].fillna("").str.upper()
        for kw in keywords:
            m = ds.str.contains(kw.upper(), regex=False, na=False)
            if m.any():
                hit = sub[m]
                if "CD_CONTA" in hit.columns:
                    hit = hit.assign(
                        _lvl=hit["CD_CONTA"].astype(str).str.count(r"\.")
                    ).sort_values("_lvl")
                v = hit[value_col].dropna()
                if not v.empty:
                    return float(v.iloc[0])

    return None


def _get_value(
    df: pd.DataFrame,
    cd_cvm: str,
    keywords: List[str],
    date_col: str = "DT_REFER",
    value_col: str = "VL_CONTA_AJUSTADO",
) -> Optional[float]:
    """Compatibilidade: extrai valor por palavra-chave no exercício mais recente."""
    return _pick_value(df, cd_cvm, cd_contas=None, keywords=keywords, value_col=value_col)


# ---------------------------------------------------------------------------
# Snapshot financeiro
# ---------------------------------------------------------------------------

def build_company_snapshot(cd_cvm: str, tipo_doc: str = "DFP") -> Dict:
    """
    Constrói um resumo financeiro consolidado da empresa.

    Tenta extrair as principais linhas das demonstrações:
    DRE, BPA, BPP e DFC_MI.

    Retorna dicionário com valores e flags de qualidade.
    """
    cd_cvm = str(cd_cvm).strip()

    dre = load_processed_statement("DRE", tipo_doc)
    bpa = load_processed_statement("BPA", tipo_doc)
    bpp = load_processed_statement("BPP", tipo_doc)
    dfc = load_processed_statement("DFC_MI", tipo_doc)

    def get(df: pd.DataFrame, codes: List[str], keys: List[str]) -> Optional[float]:
        if df.empty:
            return None
        return _pick_value(df, cd_cvm, cd_contas=codes, keywords=keys)

    # DRE — CD_CONTA padrão CVM + fallback por texto
    receita = get(dre, ["3.01"], [
        "receita de venda de bens", "receita líquida", "receita de venda",
        "receita operacional líquida",
    ])
    lucro_bruto = get(dre, ["3.03"], ["resultado bruto", "lucro bruto"])
    ebit = get(dre, ["3.05"], [
        "resultado antes do resultado financeiro",
        "resultado operacional", "lucro operacional",
    ])
    lucro_liq = get(dre, ["3.11", "3.09"], [
        "lucro/prejuízo consolidado do período",
        "lucro/prejuízo do período", "lucro líquido",
    ])

    # BPA — Ativo
    caixa = get(bpa, ["1.01.01"], [
        "caixa e equivalentes de caixa", "caixa e equivalentes", "disponibilidades",
    ])
    aplicacoes = get(bpa, ["1.01.02"], [
        "aplicações financeiras", "títulos e valores mobiliários",
    ])
    ativo_total = get(bpa, ["1"], ["ativo total"])

    # BPP — Passivo
    passivo_total = get(bpp, ["2"], ["passivo total"])
    # PL por palavra-chave (não por código): bancos usam 2.08, não-financeiras 2.03.
    # "Patrimônio Líquido Consolidado" é descrição padrão em ambos os planos.
    pl = get(bpp, None, [
        "patrimônio líquido consolidado", "patrimônio líquido",
    ])
    # Dívida = Empréstimos e Financiamentos circulante (2.01.04) + não circulante (2.02.01)
    # Inclui debêntures e arrendamentos (sub-contas já somadas nos códigos pais)
    divida_cp = get(bpp, ["2.01.04"], None)
    divida_lp = get(bpp, ["2.02.01"], None)

    divida_bruta = None
    if divida_cp is not None or divida_lp is not None:
        divida_bruta = (divida_cp or 0.0) + (divida_lp or 0.0)

    # DFC — Fluxo de caixa operacional (6.01) e CAPEX (6.02.01)
    fcop = get(dfc, ["6.01"], [
        "caixa líquido atividades operacionais",
        "caixa líquido nas atividades operacionais",
        "caixa gerado nas operações",
    ])
    capex = get(dfc, ["6.02.01"], [
        "aquisições de ativos imobilizados e intangíveis",
        "aquisição de imobilizado",
        "adições ao ativo imobilizado",
    ])

    # Dívida líquida
    caixa_total = (caixa or 0.0) + (aplicacoes or 0.0)
    divida_liq: Optional[float] = None
    if divida_bruta is not None:
        divida_liq = divida_bruta - caixa_total

    snapshot = {
        # Demonstração de resultado
        "receita_liquida": receita,
        "lucro_bruto": lucro_bruto,
        "ebit": ebit,
        "lucro_liquido": lucro_liq,
        # Balanço
        "caixa_equivalentes": caixa,
        "aplicacoes_financeiras": aplicacoes,
        "ativo_total": ativo_total,
        "passivo_total": passivo_total,
        "patrimonio_liquido": pl,
        "divida_bruta": divida_bruta,
        "divida_liquida": divida_liq,
        # Fluxo de caixa
        "fluxo_caixa_operacional": fcop,
        "capex": capex,
        # Flags de qualidade
        "has_revenue": receita is not None,
        "has_gross_profit": lucro_bruto is not None,
        "has_ebit": ebit is not None,
        "has_net_income": lucro_liq is not None,
        "has_cash": caixa is not None,
        "has_debt": divida_bruta is not None,
        "has_equity": pl is not None,
        "has_operating_cash_flow": fcop is not None,
        "has_capex": capex is not None,
        # Meta
        "cd_cvm": cd_cvm,
        "tipo_doc": tipo_doc,
    }

    # Log de flags
    missing = [k.replace("has_", "") for k, v in snapshot.items() if k.startswith("has_") and not v]
    if missing:
        logger.warning("Snapshot CD_CVM=%s: dados ausentes para: %s", cd_cvm, ", ".join(missing))
    else:
        logger.info("Snapshot CD_CVM=%s: todos os dados principais encontrados.", cd_cvm)

    return snapshot
