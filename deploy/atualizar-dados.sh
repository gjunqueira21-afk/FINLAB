#!/bin/bash
# Reprocessa as demonstrações da CVM (DFP/ITR) dentro do contêiner.
# Rode depois de cada temporada de resultados — ou agende semanalmente com:
#   crontab -e
#   0 6 * * 1  cd /root/FINLAB/deploy && bash atualizar-dados.sh >> /var/log/finlab-dados.log 2>&1
set -euo pipefail
cd "$(dirname "$0")"

echo "-> atualizando as demonstrações da CVM (pode levar alguns minutos)"
docker compose exec -T finlab sh -c \
    'cd /app/valuation_cvm && python -m src.main --start-year 2016 --end-year $(date +%Y)'

echo "-> limpando o cache do painel para os números novos aparecerem"
docker compose restart finlab

echo "-> pronto."
