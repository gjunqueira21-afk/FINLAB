#!/bin/bash
# Atualiza o FinLab na VPS: git pull + rebuild + sobe de novo.
# Os dados da CVM e os caches vivem em volumes — nada é perdido.
set -euo pipefail
cd "$(dirname "$0")"

echo "-> git pull"
git -C .. pull

echo "-> rebuild e restart"
docker compose up -d --build

echo "-> pronto. Logs: docker compose logs -f finlab"
