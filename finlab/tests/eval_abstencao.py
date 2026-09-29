#!/usr/bin/env python3
"""Teste de abstenção da mesa de IA — o parecer 03 §6 pede que seja bloqueante.

O modo de falha de um painel de IA não é errar a conta: é responder com
confiança sobre o que não sabe. Este script pergunta à mesa exatamente aquilo
que ela NÃO tem como saber e verifica se ela admite.

Precisa de chave real, então não entra na suíte offline (`pytest finlab/tests`).
Rode antes de confiar numa configuração nova de modelo:

    python finlab/tests/eval_abstencao.py --provider openrouter \\
        --model anthropic/claude-sonnet-5 --key sk-...

A chave pode vir de --key ou da variável FINLAB_EVAL_KEY. Ela não é gravada
em lugar nenhum: vai direto para o proxy local, como no painel.

Sai com código 1 se algum caso falhar — dá para pendurar num hook de release.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

GOLDEN = Path(__file__).resolve().parent / "golden" / "abstencao.json"


def _normaliza(txt: str) -> str:
    return " ".join((txt or "").lower().split())


def _perguntar(base: str, caso: dict, provider: str, model: str, key: str) -> str:
    corpo = json.dumps({
        "agent": caso["agente"],
        "ticker": caso["ticker"],
        "slot": {"provider": provider, "api_key": key, "model": model},
        "pergunta": caso["pergunta"],
    }).encode()
    req = urllib.request.Request(f"{base}/api/agents/run", data=corpo,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.load(resp).get("texto", "")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:8777",
                    help="painel em execução (padrão: 127.0.0.1:8777)")
    ap.add_argument("--provider", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--key", default=os.environ.get("FINLAB_EVAL_KEY", ""))
    ap.add_argument("--caso", help="roda só um caso, pelo id")
    args = ap.parse_args()

    if not args.key:
        print("Falta a chave: use --key ou FINLAB_EVAL_KEY.", file=sys.stderr)
        return 2

    dados = json.loads(GOLDEN.read_text(encoding="utf-8"))
    aceitas = [_normaliza(a) for a in dados["aceitas_como_abstencao"]]
    casos = [c for c in dados["casos"] if not args.caso or c["id"] == args.caso]

    falhas = []
    for caso in casos:
        print(f"\n[{caso['id']}] {caso['ticker']} · {caso['pergunta']}")
        try:
            texto = _perguntar(args.base, caso, args.provider, args.model, args.key)
        except (urllib.error.URLError, TimeoutError) as exc:
            falhas.append((caso["id"], f"não consegui perguntar: {exc}"))
            print(f"  ERRO  {exc}")
            continue

        n = _normaliza(texto)
        esperadas = aceitas + [_normaliza(x) for x in caso.get("deve_conter_extra", [])]
        admitiu = any(a in n for a in esperadas)
        inventou = [x for x in caso.get("nao_pode_conter", []) if _normaliza(x) in n]

        if inventou:
            falhas.append((caso["id"], f"inventou: {inventou}"))
            print(f"  FALHA  respondeu como se soubesse — {inventou}")
        elif not admitiu:
            falhas.append((caso["id"], "não admitiu a ausência do dado"))
            print("  FALHA  não disse que não tem o dado")
            print("         " + texto[:200].replace("\n", " "))
        else:
            print("  ok     admitiu que não tem o dado")

    print("\n" + "=" * 60)
    if falhas:
        print(f"{len(falhas)} de {len(casos)} casos FALHARAM:")
        for cid, motivo in falhas:
            print(f"  - {cid}: {motivo}")
        print("\nUm modelo que não abstém não deve ficar na mesa: ele produz "
              "narrativa plausível e não verificável, que é o problema que este "
              "painel existe para evitar.")
        return 1
    print(f"{len(casos)} casos · a mesa admitiu tudo que não sabe")
    return 0


if __name__ == "__main__":
    sys.exit(main())
