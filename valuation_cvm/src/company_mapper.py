"""
Módulo para mapeamento e busca de empresas.

A CVM não fornece ticker diretamente no cadastro principal.
O projeto trabalha com CD_CVM, CNPJ_CIA e DENOM_CIA.
O arquivo ticker_mapper.csv deve ser preenchido manualmente ou via outra API.
"""

import re
from pathlib import Path
from typing import Optional, Union

import pandas as pd

from .config import PROCESSED_DIR, RAW_DIR
from .cvm_cleaner import clean_cadastro, normalize_text
from .logger import logger

CADASTRO_PARQUET = PROCESSED_DIR / "cadastro_cvm.parquet"
CADASTRO_CSV = RAW_DIR / "cad_cia_aberta.csv"
TICKER_MAPPER_PATH = PROCESSED_DIR / "ticker_mapper.csv"


def load_company_registry(only_active: bool = False) -> pd.DataFrame:
    """
    Carrega o cadastro de empresas abertas da CVM.

    Tenta primeiro o parquet processado; se não existir, lê o CSV bruto.
    """
    if CADASTRO_PARQUET.exists():
        logger.info("Carregando cadastro de: %s", CADASTRO_PARQUET)
        df = pd.read_parquet(CADASTRO_PARQUET)
    elif CADASTRO_CSV.exists():
        logger.info("Parquet não encontrado. Carregando CSV bruto: %s", CADASTRO_CSV)
        df = pd.read_csv(CADASTRO_CSV, sep=";", encoding="latin1", dtype=str)
        df = clean_cadastro(df, only_active=only_active)
    else:
        logger.error(
            "Cadastro não encontrado. Execute o pipeline primeiro: "
            "python -m src.main --start-year <ano>"
        )
        return pd.DataFrame()

    if only_active and "SIT" in df.columns:
        df = df[df["SIT"].str.upper().str.contains("ATIVO|ATIVA", na=False)].copy()

    return df.reset_index(drop=True)


def filter_company_by_name_or_cvm(
    query: Union[str, int],
    df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Busca empresas por nome (parcial), CD_CVM ou CNPJ.

    Exemplos:
        filter_company_by_name_or_cvm("PETROBRAS")
        filter_company_by_name_or_cvm("9512")
        filter_company_by_name_or_cvm("60.872.504/0001-23")
    """
    if df is None:
        df = load_company_registry()

    if df.empty:
        return pd.DataFrame()

    query_str = normalize_text(str(query)).upper()

    masks = []

    # Busca por CD_CVM
    if "CD_CVM" in df.columns:
        masks.append(df["CD_CVM"].astype(str).str.strip() == query_str)

    # Busca por CNPJ
    if "CNPJ_CIA" in df.columns:
        cnpj_clean = re.sub(r"[^\d]", "", query_str) if len(query_str) > 6 else ""
        if cnpj_clean:
            masks.append(df["CNPJ_CIA"].astype(str).str.replace(r"[^\d]", "", regex=True) == cnpj_clean)

    # Busca parcial por nome
    for col in ["DENOM_CIA", "DENOM_SOCIAL"]:
        if col in df.columns:
            masks.append(
                df[col].apply(normalize_text).str.upper().str.contains(query_str, na=False, regex=False)
            )

    if not masks:
        return pd.DataFrame()

    combined = masks[0]
    for m in masks[1:]:
        combined = combined | m

    result = df[combined].copy()
    logger.info("Busca '%s': %d empresa(s) encontrada(s).", query, len(result))
    return result.reset_index(drop=True)


def create_ticker_mapper_template(df_cadastro: Optional[pd.DataFrame] = None) -> Path:
    """
    Cria (ou atualiza) o arquivo ticker_mapper.csv com as colunas base.

    Se já existir, mantém os dados já preenchidos e adiciona novas empresas.
    Retorna o Path do arquivo criado.
    """
    if df_cadastro is None:
        df_cadastro = load_company_registry()

    cols_needed = ["CD_CVM", "CNPJ_CIA", "DENOM_CIA"]
    available = [c for c in cols_needed if c in df_cadastro.columns]

    if not available:
        logger.error("Cadastro sem colunas esperadas: %s", cols_needed)
        return TICKER_MAPPER_PATH

    template_df = df_cadastro[available].copy().drop_duplicates(subset=["CD_CVM"])

    # Adicionar colunas extras vazias
    for col in ["TICKER", "SETOR", "SUBSETOR", "FONTE_TICKER"]:
        if col not in template_df.columns:
            template_df[col] = ""

    # Se já existir, preservar dados preenchidos
    if TICKER_MAPPER_PATH.exists():
        existing = pd.read_csv(TICKER_MAPPER_PATH, dtype=str)
        filled = existing[existing["TICKER"].notna() & (existing["TICKER"] != "")]
        if not filled.empty:
            template_df = template_df.merge(
                filled[["CD_CVM", "TICKER", "SETOR", "SUBSETOR", "FONTE_TICKER"]],
                on="CD_CVM",
                how="left",
                suffixes=("", "_filled"),
            )
            for col in ["TICKER", "SETOR", "SUBSETOR", "FONTE_TICKER"]:
                filled_col = col + "_filled"
                if filled_col in template_df.columns:
                    template_df[col] = template_df[filled_col].where(
                        template_df[filled_col].notna(), template_df[col]
                    )
                    template_df.drop(columns=[filled_col], inplace=True)

    TICKER_MAPPER_PATH.parent.mkdir(parents=True, exist_ok=True)
    template_df.to_csv(TICKER_MAPPER_PATH, index=False)
    logger.info("ticker_mapper.csv criado/atualizado: %d empresas em %s", len(template_df), TICKER_MAPPER_PATH)
    return TICKER_MAPPER_PATH


def get_cd_cvm_by_query(query: str) -> Optional[str]:
    """
    Retorna o CD_CVM da primeira empresa encontrada pela query.
    Retorna None se não encontrar.
    """
    result = filter_company_by_name_or_cvm(query)
    if result.empty:
        return None
    if "CD_CVM" in result.columns:
        return str(result.iloc[0]["CD_CVM"])
    return None
