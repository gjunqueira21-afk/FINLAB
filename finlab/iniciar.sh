#!/usr/bin/env bash
# Gab's FinLab — sobe o painel e abre no navegador.
set -euo pipefail

cd "$(dirname "$0")/.."
RAIZ="$(pwd)"

PY="${PYTHON:-python3}"
VENV="$RAIZ/.venv"

if [ ! -d "$VENV" ]; then
  echo "→ criando ambiente virtual em .venv"
  "$PY" -m venv "$VENV"
fi

echo "→ instalando dependências"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$RAIZ/finlab/requirements.txt"

PORTA="${FINLAB_PORT:-8777}"
HOST="${FINLAB_HOST:-127.0.0.1}"

echo "→ Gab's FinLab em http://$HOST:$PORTA"
( sleep 2; (command -v xdg-open >/dev/null && xdg-open "http://$HOST:$PORTA") \
  || (command -v open >/dev/null && open "http://$HOST:$PORTA") || true ) &

exec "$VENV/bin/python" -m uvicorn finlab.backend.app:app --host "$HOST" --port "$PORTA"
