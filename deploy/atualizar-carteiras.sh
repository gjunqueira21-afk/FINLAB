#!/bin/bash
# Atualiza cota, pesos, alertas de banda e a lâmina de TODAS as carteiras
# acompanhadas — o "cron dos agents". Roda 100% sem chave de IA: as chaves
# dos provedores vivem no navegador do usuário e nunca ficam na VPS, então
# o agendado é o quantitativo (preço, cota, desvio, lâmina); julgamento
# (research, análise) continua sendo pedido pela interface.
#
# Agende toda segunda às 6h (depois do atualizar-dados.sh, se ambos):
#   crontab -e
#   30 6 * * 1  cd /root/FINLAB/deploy && bash atualizar-carteiras.sh >> /var/log/finlab-carteiras.log 2>&1
set -euo pipefail
cd "$(dirname "$0")"

echo "-> $(date '+%F %T') atualizando as carteiras acompanhadas"
docker compose exec -T finlab python -m finlab.backend.tarefas atualizar-carteiras --lamina
echo "-> pronto."
