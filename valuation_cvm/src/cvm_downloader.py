"""
Módulo responsável por baixar os arquivos da CVM Dados Abertos.

Fontes:
- Cadastro: https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv
- ITR/DFP:  https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{tipo}/DADOS/{tipo_lower}_cia_aberta_{ano}.zip
"""

import zipfile
from pathlib import Path
from typing import Optional

import requests
from tqdm import tqdm

from .config import (
    CVM_CADASTRO_URL,
    RAW_DIR,
    get_zip_url,
    get_zip_path,
    create_directories,
)
from .logger import logger

# Timeout padrão para requisições (segundos)
REQUEST_TIMEOUT = 120
# Tamanho do chunk de download (bytes)
CHUNK_SIZE = 1024 * 1024  # 1 MB


def _remote_is_newer(url: str, dest_path: Path) -> bool:
    """A origem mudou desde o arquivo local?

    A CVM REPUBLICA exercícios retroativamente, então "o arquivo existe" não
    significa "o arquivo está atual" — pular sempre servia dado velho em
    silêncio (achado 00.4 do diagnóstico). Um HEAD compara Last-Modified com
    o mtime local (fallback: Content-Length × tamanho). Na dúvida — servidor
    sem os cabeçalhos, rede fora — fica com o local, que é o comportamento
    antigo.
    """
    try:
        head = requests.head(url, timeout=30, allow_redirects=True)
    except requests.exceptions.RequestException:
        return False
    if head.status_code != 200:
        return False

    lm = head.headers.get("Last-Modified")
    if lm:
        try:
            from email.utils import parsedate_to_datetime
            remoto = parsedate_to_datetime(lm).timestamp()
            return remoto > dest_path.stat().st_mtime
        except (TypeError, ValueError):
            pass

    tamanho = head.headers.get("Content-Length")
    if tamanho and tamanho.isdigit():
        return int(tamanho) != dest_path.stat().st_size
    return False


def _download_file(url: str, dest_path: Path, force_download: bool = False) -> bool:
    """
    Baixa um arquivo da URL para dest_path.

    Retorna True se o download foi bem-sucedido, False caso contrário.
    Usa cache com revalidação: arquivo existente só é reaproveitado se a
    origem não estiver mais nova (Last-Modified/Content-Length).
    """
    if dest_path.exists() and not force_download:
        if not _remote_is_newer(url, dest_path):
            logger.info("Cache atual, pulando download: %s", dest_path.name)
            return True
        logger.info("Origem mais nova que o cache, rebaixando: %s", dest_path.name)

    logger.info("Iniciando download: %s -> %s", url, dest_path.name)

    try:
        response = requests.get(url, stream=True, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.ConnectionError as exc:
        logger.error("Erro de conexão ao baixar %s: %s", url, exc)
        return False
    except requests.exceptions.Timeout:
        logger.error("Timeout ao baixar %s", url)
        return False

    if response.status_code == 404:
        logger.warning("Arquivo não encontrado (404): %s", url)
        return False

    if response.status_code != 200:
        logger.error("HTTP %s ao baixar %s", response.status_code, url)
        return False

    total_size = int(response.headers.get("content-length", 0))
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    with open(dest_path, "wb") as f:
        with tqdm(
            total=total_size,
            unit="B",
            unit_scale=True,
            desc=dest_path.name,
            disable=total_size == 0,
            leave=False,
        ) as pbar:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    f.write(chunk)
                    pbar.update(len(chunk))

    logger.info("Download concluído: %s (%.1f KB)", dest_path.name, dest_path.stat().st_size / 1024)
    return True


def _is_valid_zip(path: Path) -> bool:
    """Valida se o arquivo em path é um ZIP válido."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            bad = zf.testzip()
            if bad is not None:
                logger.warning("ZIP corrompido em '%s': primeiro arquivo ruim = %s", path.name, bad)
                return False
        return True
    except zipfile.BadZipFile:
        logger.warning("Arquivo não é um ZIP válido: %s", path.name)
        return False
    except Exception as exc:
        logger.error("Erro ao validar ZIP %s: %s", path.name, exc)
        return False


def download_cvm_cadastro(force_download: bool = False) -> Optional[Path]:
    """
    Baixa o cadastro de companhias abertas da CVM.

    URL: https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv
    Salva em: data/raw/cad_cia_aberta.csv

    Retorna o Path do arquivo ou None em caso de falha.
    """
    create_directories()
    dest = RAW_DIR / "cad_cia_aberta.csv"

    success = _download_file(CVM_CADASTRO_URL, dest, force_download=force_download)
    if not success:
        return None

    return dest


def download_cvm_zip(
    tipo_doc: str,
    ano: int,
    force_download: bool = False,
) -> Optional[Path]:
    """
    Baixa o ZIP de ITR ou DFP para o ano informado.

    Parâmetros:
        tipo_doc:       "ITR" ou "DFP"
        ano:            Ano de referência (ex.: 2024)
        force_download: Se True, baixa mesmo que o arquivo já exista em cache

    Retorna o Path do ZIP ou None se não disponível / falha.
    """
    create_directories()
    tipo_doc = tipo_doc.upper()
    url = get_zip_url(tipo_doc, ano)
    dest = get_zip_path(tipo_doc, ano)

    success = _download_file(url, dest, force_download=force_download)
    if not success:
        return None

    if not _is_valid_zip(dest):
        logger.warning("ZIP inválido removido: %s", dest.name)
        dest.unlink(missing_ok=True)
        return None

    return dest


def download_all_cvm_data(
    start_year: int,
    end_year: int,
    force_download: bool = False,
) -> dict:
    """
    Baixa cadastro, ITR e DFP para todos os anos no intervalo [start_year, end_year].

    Retorna um dicionário com o resumo dos downloads:
    {
        "cadastro": Path | None,
        "ITR": {ano: Path | None, ...},
        "DFP": {ano: Path | None, ...},
    }
    """
    create_directories()
    results: dict = {"cadastro": None, "ITR": {}, "DFP": {}, "IPE": {}}

    logger.info("=== Iniciando download dos dados CVM (%d a %d) ===", start_year, end_year)

    # 1. Cadastro
    results["cadastro"] = download_cvm_cadastro(force_download=force_download)

    # 2. ITR, DFP e IPE por ano
    for ano in range(start_year, end_year + 1):
        for tipo_doc in ["ITR", "DFP", "IPE"]:
            path = download_cvm_zip(tipo_doc, ano, force_download=force_download)
            results[tipo_doc][ano] = path
            if path is None:
                logger.warning("[%s %d] Não disponível ou erro no download — será ignorado.", tipo_doc, ano)

    # Resumo
    anos = end_year - start_year + 1
    ok = {t: sum(1 for v in results[t].values() if v is not None) for t in ("ITR", "DFP", "IPE")}
    logger.info(
        "=== Download concluído | Cadastro: %s | ITR: %d/%d | DFP: %d/%d | IPE: %d/%d ===",
        "OK" if results["cadastro"] else "FALHOU",
        ok["ITR"], anos, ok["DFP"], anos, ok["IPE"], anos,
    )

    return results
