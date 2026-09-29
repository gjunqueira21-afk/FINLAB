"""
Módulo de limpeza e padronização dos dados da CVM.
"""

import re
import unicodedata

import numpy as np
import pandas as pd

from .logger import logger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_text(text: object) -> str:
    """Normaliza texto: remove espaços duplicados e strip."""
    if pd.isna(text):
        return ""
    s = str(text).strip()
    s = re.sub(r"\s+", " ", s)
    return s


def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza nomes de colunas: upper + strip + sem espaços."""
    df.columns = [normalize_text(c).upper().replace(" ", "_") for c in df.columns]
    return df


def _safe_to_datetime(series: pd.Series) -> pd.Series:
    """Converte série para datetime, tolerando erros."""
    return pd.to_datetime(series, errors="coerce", dayfirst=False)


def _safe_to_numeric(series: pd.Series) -> pd.Series:
    """Converte série para numérico, tolerando erros."""
    return pd.to_numeric(series, errors="coerce")


# ---------------------------------------------------------------------------
# Limpeza do cadastro
# ---------------------------------------------------------------------------

def clean_cadastro(df: pd.DataFrame, only_active: bool = False) -> pd.DataFrame:
    """
    Limpa e padroniza o cadastro de companhias abertas da CVM.

    Parâmetros:
        df:          DataFrame bruto do cadastro
        only_active: Se True, filtra apenas empresas com situação ativa
    """
    if df is None or df.empty:
        logger.warning("clean_cadastro: DataFrame vazio ou None recebido.")
        return pd.DataFrame()

    df = df.copy()
    df = normalize_column_names(df)

    # Preservar CD_CVM e CNPJ como string
    for col in ["CD_CVM", "CNPJ_CIA", "CNPJ_CVM"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().str.zfill(
                14 if "CNPJ" in col else 0
            ).str.lstrip("0") if "CNPJ" not in col else df[col].astype(str).str.strip()
            # Garantir que CD_CVM seja string sem padding desnecessário
            if col == "CD_CVM":
                df[col] = df[col].astype(str).str.strip()

    # Datas
    date_cols = [c for c in df.columns if c.startswith("DT_")]
    for col in date_cols:
        df[col] = _safe_to_datetime(df[col])

    # Normalizar strings de nome
    for col in ["DENOM_CIA", "DENOM_SOCIAL", "SIT", "SETOR_ATIV"]:
        if col in df.columns:
            df[col] = df[col].apply(normalize_text)

    if only_active and "SIT" in df.columns:
        antes = len(df)
        df = df[df["SIT"].str.upper().str.contains("ATIVO|ATIVA", na=False)].copy()
        logger.info("Filtro only_active: %d -> %d empresas.", antes, len(df))

    logger.info("Cadastro limpo: %d empresas, %d colunas.", len(df), df.shape[1])
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Limpeza de demonstrativos
# ---------------------------------------------------------------------------

# Mapeamento de ESCALA_MOEDA para multiplicador
_ESCALA_MAP = {
    "UNIDADE": 1,
    "MIL": 1_000,
    "MILHAR": 1_000,
    "MILHAO": 1_000_000,
    "MILHÃO": 1_000_000,
    "BILHAO": 1_000_000_000,
    "BILHÃO": 1_000_000_000,
}


def _resolve_scale(escala: object) -> float:
    """Retorna o multiplicador para a escala monetária fornecida."""
    if pd.isna(escala):
        return np.nan
    key = normalize_text(str(escala)).upper()
    # Remove acentos para comparação
    key_norm = "".join(
        c for c in unicodedata.normalize("NFD", key)
        if unicodedata.category(c) != "Mn"
    )
    return float(_ESCALA_MAP.get(key_norm, np.nan))


def clean_statement(df: pd.DataFrame) -> pd.DataFrame:
    """
    Limpa e padroniza um demonstrativo financeiro da CVM.

    Ações:
    - Normaliza nomes de colunas
    - Converte datas
    - Converte VL_CONTA para numérico
    - Preserva CD_CONTA como string
    - Cria VL_CONTA_AJUSTADO (VL_CONTA * multiplicador de escala)
    - Cria ANO_REFER e TRIMESTRE_REFER
    - Normaliza DS_CONTA
    """
    if df is None or df.empty:
        logger.warning("clean_statement: DataFrame vazio ou None recebido.")
        return pd.DataFrame()

    df = df.copy()
    df = normalize_column_names(df)

    # Colunas como texto
    for col in ["CNPJ_CIA", "CD_CVM", "CD_CONTA"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    # Datas
    for col in ["DT_REFER", "DT_INI_EXERC", "DT_FIM_EXERC"]:
        if col in df.columns:
            df[col] = _safe_to_datetime(df[col])

    # VL_CONTA numérico
    if "VL_CONTA" in df.columns:
        df["VL_CONTA"] = _safe_to_numeric(df["VL_CONTA"])

    # Escala monetária → VL_CONTA_AJUSTADO
    if "ESCALA_MOEDA" in df.columns:
        df["_ESCALA_MULT"] = df["ESCALA_MOEDA"].apply(_resolve_scale)
        if "VL_CONTA" in df.columns:
            df["VL_CONTA_AJUSTADO"] = df["VL_CONTA"] * df["_ESCALA_MULT"]
        df.drop(columns=["_ESCALA_MULT"], inplace=True)
    else:
        if "VL_CONTA" in df.columns:
            df["VL_CONTA_AJUSTADO"] = df["VL_CONTA"]
            logger.debug("ESCALA_MOEDA ausente: VL_CONTA_AJUSTADO = VL_CONTA sem multiplicador.")

    # ANO_REFER
    ref_col = "DT_REFER" if "DT_REFER" in df.columns else (
        "DT_FIM_EXERC" if "DT_FIM_EXERC" in df.columns else None
    )
    if ref_col:
        df["ANO_REFER"] = df[ref_col].dt.year

    # TRIMESTRE_REFER
    if "DT_REFER" in df.columns:
        df["TRIMESTRE_REFER"] = df["DT_REFER"].dt.quarter

    # Normalizar DS_CONTA
    if "DS_CONTA" in df.columns:
        df["DS_CONTA"] = df["DS_CONTA"].apply(normalize_text)

    # VERSAO e ORDEM_EXERC como texto
    for col in ["VERSAO", "ORDEM_EXERC"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    logger.debug("clean_statement: %d linhas, %d colunas.", len(df), df.shape[1])
    return df.reset_index(drop=True)
