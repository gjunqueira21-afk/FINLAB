"""Índice IPE da CVM: o que a companhia comunicou ao mercado.

O painel sabia ler o que a empresa *contabilizou* e não sabia nada do que ela
*comunicou*. O IPE (Informações Periódicas e Eventuais) fecha esse buraco: uma
linha por documento entregue à CVM — fato relevante, comunicado ao mercado,
press-release, apresentação a analistas, calendário de eventos —, cada uma com
data e com `Link_Download` apontando para o PDF no RAD/ENET.

Aqui está só o **índice**, e isso é uma escolha, não uma limitação temporária:

  * O índice sozinho já responde "o que aconteceu nesta empresa desde o
    balanço", com data e link para o usuário conferir na fonte.
  * Ele é **verificável**: cada item aponta para um documento oficial. Nada
    aqui é interpretação de modelo.
  * Baixar e parsear os PDFs é outra ordem de grandeza — e o parecer 03 pede
    respeito ao Crawl-Delay de 10 s, o que torna a ingestão um processo de
    fundo, não algo que se faz ao abrir uma tela.

Nada do que este módulo devolve é opinião: é o que a companhia publicou, na
data em que publicou.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

import pandas as pd

from .settings import CVM_PROCESSED_DIR

# As categorias que mudam uma tese, na ordem em que importam para o analista.
# O IPE tem dezenas — assembleia, aviso aos acionistas, política de negociação
# — e mostrar tudo afogaria o que interessa.
CATEGORIAS_RELEVANTES = (
    "Fato Relevante",
    "Comunicado ao Mercado",
    "Dados Econômico-Financeiros",
    "Calendário de Eventos Corporativos",
    "Reunião da Administração",
)

MAX_DOCS = 12


@lru_cache(maxsize=1)
def _indice() -> pd.DataFrame:
    fp = CVM_PROCESSED_DIR / "ipe.parquet"
    if not fp.exists():
        return pd.DataFrame()
    try:
        df = pd.read_parquet(fp)
    except Exception:      # parquet truncado não pode derrubar o painel
        return pd.DataFrame()
    if "Codigo_CVM" not in df.columns:
        return pd.DataFrame()
    # O CD_CVM do universo vem zero-preenchido ("009512"); o do IPE, nem sempre.
    df["_CD"] = df["Codigo_CVM"].astype(str).str.strip().str.lstrip("0")
    return df


def disponivel() -> bool:
    return not _indice().empty


def cobertura() -> Optional[str]:
    """A entrega mais recente no índice inteiro — o "até quando o painel vê"."""
    df = _indice()
    if df.empty or "Data_Entrega" not in df.columns:
        return None
    fim = pd.to_datetime(df["Data_Entrega"], errors="coerce").max()
    return None if pd.isna(fim) else str(fim.date())


def documentos(cd_cvm: str, limite: int = MAX_DOCS) -> dict:
    """Os documentos recentes de uma companhia, do mais novo para o mais velho.

    Devolve {"docs": [...], "cobertura": "AAAA-MM-DD", "total": n}. Sem o
    parquet do IPE, devolve a estrutura vazia e o painel segue sem a seção —
    do mesmo jeito que segue sem o ITR.
    """
    vazio = {"docs": [], "cobertura": None, "total": 0}
    if not cd_cvm:
        return vazio
    df = _indice()
    if df.empty:
        return vazio

    sub = df[df["_CD"] == str(cd_cvm).strip().lstrip("0")]
    if sub.empty:
        return vazio

    if "Categoria" in sub.columns:
        relevantes = sub[sub["Categoria"].isin(CATEGORIAS_RELEVANTES)]
        # Se o filtro zerar, mostra o que existe: melhor um documento de
        # categoria incomum que uma tela vazia dizendo que não houve nada.
        sub = relevantes if not relevantes.empty else sub

    if "Data_Entrega" in sub.columns:
        sub = sub.sort_values("Data_Entrega", ascending=False)

    docs = []
    for r in sub.head(limite).itertuples():
        data = getattr(r, "Data_Entrega", None)
        docs.append({
            "data": str(pd.Timestamp(data).date()) if data is not None and not pd.isna(data) else None,
            "categoria": getattr(r, "Categoria", None),
            "tipo": getattr(r, "Tipo", None),
            "assunto": _resumo(getattr(r, "Assunto", None)),
            "link": getattr(r, "Link_Download", None),
        })
    return {"docs": docs, "cobertura": cobertura(), "total": int(len(sub))}


def _resumo(assunto: object, limite: int = 180) -> Optional[str]:
    """O campo Assunto é livre e às vezes traz um parágrafo inteiro."""
    if assunto is None or (isinstance(assunto, float) and assunto != assunto):
        return None
    texto = " ".join(str(assunto).split())
    if not texto:
        return None
    return texto if len(texto) <= limite else texto[:limite - 1] + "…"
