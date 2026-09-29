"""
Configuração de logging centralizada para o projeto valuation_cvm.
"""

import logging
import sys


def setup_logger(name: str = "valuation_cvm", level: int = logging.INFO) -> logging.Logger:
    """
    Cria e configura um logger com saída formatada para stdout.
    Retorna o logger configurado.
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


# Logger padrão do projeto
logger = setup_logger()
