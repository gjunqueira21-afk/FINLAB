#!/usr/bin/env bash
# Inicia o dashboard EPS VALUE TERMINAL
set -e

echo ""
echo " =========================================="
echo "  EPS VALUE TERMINAL — Iniciando Dashboard"
echo " =========================================="
echo ""

# Instala dependências se necessário
python3 -c "import streamlit" 2>/dev/null || {
    echo "[AVISO] Instalando dependências..."
    pip install -r requirements.txt
}

echo "[OK] Acesse: http://localhost:8501"
echo "[OK] Pressione Ctrl+C para parar"
echo ""

streamlit run dashboard.py --server.port 8501
