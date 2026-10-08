"""
Configurações centrais do projeto: caminhos, URLs da CVM e constantes.
"""

from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Diretórios base
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
CACHE_DIR = DATA_DIR / "cache"


def create_directories() -> None:
    """Cria todos os diretórios necessários caso não existam."""
    for directory in [RAW_DIR, PROCESSED_DIR, CACHE_DIR]:
        directory.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# URLs da CVM Dados Abertos
# ---------------------------------------------------------------------------

CVM_BASE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA"

CVM_CADASTRO_URL = f"{CVM_BASE_URL}/CAD/DADOS/cad_cia_aberta.csv"

CVM_ZIP_URL_TEMPLATES = {
    "ITR": f"{CVM_BASE_URL}/DOC/ITR/DADOS/itr_cia_aberta_{{ano}}.zip",
    "DFP": f"{CVM_BASE_URL}/DOC/DFP/DADOS/dfp_cia_aberta_{{ano}}.zip",
}

# ---------------------------------------------------------------------------
# Tipos de documentos e demonstrativos aceitos
# ---------------------------------------------------------------------------

TIPOS_DOC = ["ITR", "DFP"]

DEMONSTRATIVOS = ["DRE", "BPA", "BPP", "DFC_MI"]

# ---------------------------------------------------------------------------
# Colunas preservadas / de interesse dos arquivos CVM
# ---------------------------------------------------------------------------

COLUNAS_INTERESSE = [
    "CNPJ_CIA",
    "CD_CVM",
    "DENOM_CIA",
    "DT_REFER",
    "DT_INI_EXERC",
    "DT_FIM_EXERC",
    "CD_CONTA",
    "DS_CONTA",
    "VL_CONTA",
    "ESCALA_MOEDA",
    "ORDEM_EXERC",
    "VERSAO",
    "GRUPO_DFP",
    "MOEDA",
    "ST_CONTA_FIXA",
]

# Colunas que devem ser lidas como texto (evitar coerção numérica)
COLUNAS_TEXTO = ["CNPJ_CIA", "CD_CVM", "CD_CONTA"]

# ---------------------------------------------------------------------------
# Parâmetros de leitura dos CSVs da CVM
# ---------------------------------------------------------------------------

CSV_SEP = ";"
CSV_ENCODING = "latin1"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_zip_url(tipo_doc: str, ano: int) -> str:
    """Monta a URL do ZIP para o tipo de documento e ano informados."""
    tipo_doc = tipo_doc.upper()
    if tipo_doc not in CVM_ZIP_URL_TEMPLATES:
        raise ValueError(f"tipo_doc inválido: '{tipo_doc}'. Use um de {TIPOS_DOC}.")
    return CVM_ZIP_URL_TEMPLATES[tipo_doc].format(ano=ano)


def get_zip_filename(tipo_doc: str, ano: int) -> str:
    """Retorna o nome do arquivo ZIP local."""
    tipo_doc = tipo_doc.lower()
    return f"{tipo_doc}_cia_aberta_{ano}.zip"


def get_zip_path(tipo_doc: str, ano: int) -> Path:
    """Retorna o caminho completo do ZIP local."""
    return RAW_DIR / get_zip_filename(tipo_doc, ano)


def get_processed_path(statement: str, tipo_doc: str, ext: str = "parquet") -> Path:
    """Retorna o caminho do arquivo processado."""
    statement = statement.lower()
    tipo_doc = tipo_doc.lower()
    return PROCESSED_DIR / f"{statement}_{tipo_doc}.{ext}"
