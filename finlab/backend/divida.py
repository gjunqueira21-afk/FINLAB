"""Análise de endividamento — o bloco central da página da empresa no V2.

Só aritmética sobre as séries anuais da CVM: nada aqui fala com a rede.
A regra da casa vale: conta que não existe sai None, nunca estimada.
Convenções:
  cobertura_juros   = EBITDA / |despesas financeiras|      (x)
  curto_prazo_pct   = dívida CP / dívida bruta             (fração)
  liquidez_imediata = caixa total / dívida CP              (x)
  custo_aparente    = |despesa financeira| / dívida bruta média do ano (fração)
"""
from __future__ import annotations

from typing import Optional

from .metrics import div

CHAVES_SAIDA = ("divida_bruta", "divida_liquida", "caixa_total", "divida_cp",
                "divida_lp", "nd_ebitda", "cobertura_juros", "curto_prazo_pct",
                "liquidez_imediata", "custo_aparente")


def _v(s: dict, chave: str, i: int) -> Optional[float]:
    serie = s.get(chave) or []
    return serie[i] if 0 <= i < len(serie) else None


def indicadores(anos: list[int], s: dict[str, list]) -> dict:
    """Séries derivadas de endividamento, alinhadas a `anos`."""
    out: dict[str, list] = {k: [] for k in CHAVES_SAIDA}
    for i, _ano in enumerate(anos):
        bruta = _v(s, "divida_bruta", i)
        liq = _v(s, "divida_liquida", i)
        caixa = _v(s, "caixa_total", i)
        cp = _v(s, "divida_cp", i)
        ebitda = _v(s, "ebitda", i)
        desp = _v(s, "despesas_financeiras", i)
        desp_abs = abs(desp) if desp is not None else None

        bruta_ant = _v(s, "divida_bruta", i - 1) if i > 0 else None
        media = ((bruta + bruta_ant) / 2
                 if bruta is not None and bruta_ant is not None else None)

        out["divida_bruta"].append(bruta)
        out["divida_liquida"].append(liq)
        out["caixa_total"].append(caixa)
        out["divida_cp"].append(cp)
        out["divida_lp"].append(_v(s, "divida_lp", i))
        out["nd_ebitda"].append(div(liq, ebitda))
        out["cobertura_juros"].append(div(ebitda, desp_abs))
        out["curto_prazo_pct"].append(div(cp, bruta))
        out["liquidez_imediata"].append(div(caixa, cp))
        out["custo_aparente"].append(div(desp_abs, media))
    return {"anos": anos, "series": out}
