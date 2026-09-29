"""
Módulo responsável por abrir ZIPs da CVM e ler os CSVs internos.

Convenção de nomes de arquivos dentro dos ZIPs:
  ITR: itr_cia_aberta_{STATEMENT}_{con|ind}_{ano}.csv
  DFP: dfp_cia_aberta_{STATEMENT}_{con|ind}_{ano}.csv
"""

import zipfile
import io
from pathlib import Path
from typing import List, Optional

import pandas as pd

from .config import (
    CSV_SEP,
    CSV_ENCODING,
    COLUNAS_TEXTO,
    get_zip_path,
)
from .logger import logger


def list_files_in_zip(zip_path: Path) -> List[str]:
    """
    Retorna a lista de nomes de arquivos dentro do ZIP.
    Retorna lista vazia se o arquivo não existir ou não for válido.
    """
    if not zip_path.exists():
        logger.warning("ZIP não encontrado: %s", zip_path)
        return []
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            return zf.namelist()
    except zipfile.BadZipFile:
        logger.error("ZIP inválido: %s", zip_path)
        return []


def read_cvm_file_from_zip(zip_path: Path, filename: str) -> Optional[pd.DataFrame]:
    """
    Lê um CSV específico de dentro do ZIP da CVM.

    Usa separador ";", encoding latin1.
    Preserva CNPJ_CIA, CD_CVM e CD_CONTA como string.

    Retorna DataFrame ou None em caso de falha.
    """
    if not zip_path.exists():
        logger.warning("ZIP não encontrado: %s", zip_path)
        return None

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            files_in_zip = zf.namelist()
            if filename not in files_in_zip:
                logger.debug("Arquivo '%s' não encontrado em %s", filename, zip_path.name)
                return None

            with zf.open(filename) as f:
                raw_bytes = f.read()

        df = pd.read_csv(
            io.BytesIO(raw_bytes),
            sep=CSV_SEP,
            encoding=CSV_ENCODING,
            dtype={col: str for col in COLUNAS_TEXTO},
            low_memory=False,
        )
        logger.debug("Lido '%s': %d linhas, %d colunas", filename, len(df), df.shape[1])
        return df

    except Exception as exc:
        logger.error("Erro ao ler '%s' de %s: %s", filename, zip_path.name, exc)
        return None


def get_statement_filename(
    tipo_doc: str,
    statement: str,
    ano: int,
    consolidated: bool = True,
) -> str:
    """
    Retorna o nome esperado do arquivo CSV dentro do ZIP.

    Exemplos:
        get_statement_filename("ITR", "DRE", 2025, True)  -> "itr_cia_aberta_DRE_con_2025.csv"
        get_statement_filename("DFP", "BPA", 2025, False) -> "dfp_cia_aberta_BPA_ind_2025.csv"
    """
    tipo_doc = tipo_doc.lower()
    suffix = "con" if consolidated else "ind"
    return f"{tipo_doc}_cia_aberta_{statement}_{suffix}_{ano}.csv"


def _load_single_year(
    tipo_doc: str,
    statement: str,
    ano: int,
    consolidated: bool,
) -> Optional[pd.DataFrame]:
    """
    Carrega um demonstrativo de um único ano.
    Tenta consolidado primeiro; se não encontrar, tenta individual (fallback).
    """
    zip_path = get_zip_path(tipo_doc, ano)
    if not zip_path.exists():
        logger.debug("[%s %d] ZIP não encontrado, pulando.", tipo_doc, ano)
        return None

    # Tenta arquivo preferido (consolidado ou individual)
    filename = get_statement_filename(tipo_doc, statement, ano, consolidated)
    df = read_cvm_file_from_zip(zip_path, filename)

    if df is None and consolidated:
        # Fallback para individual
        filename_ind = get_statement_filename(tipo_doc, statement, ano, consolidated=False)
        logger.debug("[%s %d] '%s' não encontrado, tentando fallback individual: %s",
                     tipo_doc, ano, filename, filename_ind)
        df = read_cvm_file_from_zip(zip_path, filename_ind)
        if df is not None:
            df["_FALLBACK_IND"] = True

    if df is not None:
        df["_FALLBACK_IND"] = df.get("_FALLBACK_IND", False)

    return df


def load_statement(
    tipo_doc: str,
    statement: str,
    years: List[int],
    consolidated: bool = True,
) -> pd.DataFrame:
    """
    Carrega uma demonstração financeira para múltiplos anos e consolida em um único DataFrame.

    Parâmetros:
        tipo_doc:    "ITR" ou "DFP"
        statement:   "DRE", "BPA", "BPP" ou "DFC_MI"
        years:       Lista de anos (ex.: [2019, 2020, 2021])
        consolidated: True para arquivo consolidado (_con_), False para individual (_ind_)

    Adiciona colunas auxiliares:
        TIPO_DOC, STATEMENT, ANO_ARQUIVO, CONSOLIDADO
    """
    tipo_doc = tipo_doc.upper()
    statement = statement.upper()
    frames: List[pd.DataFrame] = []

    for ano in years:
        df = _load_single_year(tipo_doc, statement, ano, consolidated)
        if df is None:
            logger.warning("[%s %s %d] Nenhum dado carregado.", tipo_doc, statement, ano)
            continue

        df["TIPO_DOC"] = tipo_doc
        df["STATEMENT"] = statement
        df["ANO_ARQUIVO"] = ano
        df["CONSOLIDADO"] = not df.get("_FALLBACK_IND", pd.Series(False)).any()
        frames.append(df)

    if not frames:
        logger.warning("Nenhum dado encontrado para %s %s nos anos: %s", tipo_doc, statement, years)
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)
    result.drop(columns=["_FALLBACK_IND"], errors="ignore", inplace=True)

    logger.info(
        "[%s %s] Carregados %d registros de %d ano(s).",
        tipo_doc, statement, len(result), len(frames),
    )
    return result
