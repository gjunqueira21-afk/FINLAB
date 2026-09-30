#!/bin/bash
# Atualiza cota, pesos, alertas de banda, target price e a lâmina de TODAS
# as carteiras acompanhadas. Só preço e conta: nada de chave de API na VPS.
#
# Agende toda segunda às 6h (depois do atualizar-dados.sh, se ambos):
#   crontab -e
#   30 6 * * 1  cd /root/FINLAB/deploy && bash atualizar-carteiras.sh >> /var/log/finlab-carteiras.log 2>&1
set -euo pipefail
cd "$(dirname "$0")"

echo "-> $(date '+%F %T') atualizando as carteiras acompanhadas"
docker compose exec -T finlab python -m finlab.backend.tarefas atualizar-carteiras --lamina
echo "-> pronto."
