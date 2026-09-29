@echo off
title EPS VALUE TERMINAL — Dashboard
echo.
echo  ==========================================
echo   EPS VALUE TERMINAL — Iniciando Dashboard
echo  ==========================================
echo.

REM Verifica se streamlit está instalado
python -c "import streamlit" 2>nul
if errorlevel 1 (
    echo [AVISO] Streamlit nao encontrado. Instalando dependencias...
    pip install -r requirements.txt
    echo.
)

REM Verifica se plotly está instalado
python -c "import plotly" 2>nul
if errorlevel 1 (
    echo [AVISO] Plotly nao encontrado. Instalando...
    pip install plotly>=5.15.0
    echo.
)

echo [OK] Iniciando o dashboard em http://localhost:8501
echo [OK] Pressione Ctrl+C para parar o servidor
echo.
streamlit run dashboard.py --server.port 8501 --server.headless false

pause
