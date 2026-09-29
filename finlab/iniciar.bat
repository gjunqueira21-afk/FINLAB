@echo off
REM FinLab - sobe o painel e abre no navegador.
setlocal

cd /d "%~dp0.."
set RAIZ=%cd%
set VENV=%RAIZ%\.venv
set PY=%VENV%\Scripts\python.exe

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo [ERRO] Python nao encontrado no PATH.
  echo Instale em https://www.python.org/downloads/ marcando
  echo "Add python.exe to PATH" durante a instalacao, e rode este script de novo.
  echo.
  pause
  exit /b 1
)

if not exist "%PY%" (
  echo -^> criando ambiente virtual em .venv
  python -m venv "%VENV%"
  if errorlevel 1 (
    echo [ERRO] Falha ao criar o ambiente virtual.
    pause
    exit /b 1
  )
)

echo -^> instalando dependencias
REM Atualiza o pip por "python -m pip": chamar pip.exe para atualizar a si
REM mesmo falha no Windows com "Access is denied", porque o executavel esta em uso.
"%PY%" -m pip install -q --upgrade pip
"%PY%" -m pip install -q -r "%RAIZ%\finlab\requirements.txt"
if errorlevel 1 (
  echo [ERRO] Falha ao instalar as dependencias.
  pause
  exit /b 1
)

if "%FINLAB_PORT%"=="" set FINLAB_PORT=8777
if "%FINLAB_HOST%"=="" set FINLAB_HOST=127.0.0.1

echo -^> FinLab em http://%FINLAB_HOST%:%FINLAB_PORT%
echo    (para encerrar, feche esta janela ou pressione Ctrl+C)
start "" "http://%FINLAB_HOST%:%FINLAB_PORT%"

"%PY%" -m uvicorn finlab.backend.app:app --host %FINLAB_HOST% --port %FINLAB_PORT%

endlocal
