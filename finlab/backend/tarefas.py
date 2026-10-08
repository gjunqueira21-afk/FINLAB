"""Tarefas agendáveis do FinLab — o que o cron da VPS chama.

    python -m finlab.backend.tarefas atualizar-carteiras
    python -m finlab.backend.tarefas atualizar-carteiras --lamina
    python -m finlab.backend.tarefas conferir-trimestres [TICKER ...]
    python -m finlab.backend.tarefas gerar-fundamentos [--se-preciso]

Só o que roda SEM chave de API entra aqui: as chaves dos provedores de LLM
vivem no navegador do usuário e nunca ficam no servidor, então o cron
atualiza preços, cotas, desvios e lâminas — julgamento (research, análise)
continua sendo pedido pela interface, com a chave viajando na requisição.

Linha de cron sugerida (segunda-feira, 6h, com o painel em Docker):
    0 6 * * 1  cd /root/FINLAB/deploy && bash atualizar-carteiras.sh
"""

from __future__ import annotations

import argparse
import sys

from . import carteiras


def _atualizar_carteiras(gerar_lamina: bool) -> int:
    resultados = carteiras.atualizar_todas()
    if not resultados:
        print("Nenhuma carteira para atualizar.")
        return 0

    falhas = 0
    for r in resultados:
        if r.get("ok"):
            alertas = r.get("alertas") or []
            print(f"[ok] {r['nome']}: cota {r['cota']:.2f}"
                  + (f" · {len(alertas)} alerta(s) de banda" if alertas else ""))
            for a in alertas:
                print(f"     ! {a}")
        else:
            falhas += 1
            print(f"[ERRO] {r['nome']}: {r.get('erro')}")

    if gerar_lamina:
        for r in resultados:
            if not r.get("ok"):
                continue
            c = carteiras.obter(r["id"])
            destino = carteiras.DIR_CARTEIRAS / "laminas"
            destino.mkdir(parents=True, exist_ok=True)
            arq = destino / f"{r['id']}.md"
            arq.write_text(carteiras.lamina_md(c), encoding="utf-8")
            print(f"[lamina] {arq}")

    print(f"{len(resultados) - falhas} de {len(resultados)} carteira(s) atualizadas.")
    return 1 if falhas else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m finlab.backend.tarefas",
        description="Tarefas agendáveis do FinLab (cron-friendly).")
    sub = parser.add_subparsers(dest="tarefa", required=True)

    p = sub.add_parser("atualizar-carteiras",
                       help="Recalcula cota, pesos e alertas de todas as carteiras.")
    p.add_argument("--lamina", action="store_true",
                   help="Também regrava a lâmina .md de cada carteira em "
                        "data/carteiras/laminas/.")

    c = sub.add_parser("conferir-trimestres",
                       help="Confere ITR, 12 meses e Dív.Líq/EBITDA de todas as ações.")
    c.add_argument("tickers", nargs="*", help="Só estes tickers (padrão: todos).")

    g = sub.add_parser("gerar-fundamentos",
                       help="Pré-calcula os fundamentos da CVM em data/fundamentos.json.")
    g.add_argument("--se-preciso", action="store_true",
                   help="Só gera se o arquivo não existir ou não bater com os dados da CVM.")

    args = parser.parse_args()
    if args.tarefa == "gerar-fundamentos":
        from . import cvm, snapshot
        if args.se_preciso and not snapshot.precisa_gerar():
            print("fundamentos pré-calculados já estão em dia.")
            sys.exit(0)
        if not cvm.available():
            print("sem demonstrações da CVM processadas — rode o pipeline antes.")
            sys.exit(1)
        import time
        t = time.time()
        dados = snapshot.gerar()
        print(f"fundamentos de {len(dados['empresas'])} ações gravados em "
              f"{snapshot.ARQUIVO} ({time.time() - t:.0f} s).")
        sys.exit(0)
    if args.tarefa == "atualizar-carteiras":
        sys.exit(_atualizar_carteiras(args.lamina))
    if args.tarefa == "conferir-trimestres":
        from . import conferencia
        linhas = conferencia.conferir(tickers=[t.upper() for t in args.tickers] or None)
        print(conferencia.relatorio(linhas))
        sys.exit(0)


if __name__ == "__main__":
    main()
