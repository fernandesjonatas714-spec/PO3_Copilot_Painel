@echo off
setlocal
set "PAINEL_DIR=%~dp0"
set "BASE_PYTHON=C:\Users\JONATAS\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%BASE_PYTHON%" (
  echo Python base nao encontrado: %BASE_PYTHON%
  pause
  exit /b 1
)
"%BASE_PYTHON%" -m venv "%PAINEL_DIR%.venv"
if errorlevel 1 goto :error
"%PAINEL_DIR%.venv\Scripts\python.exe" -m pip install -r "%PAINEL_DIR%requirements.txt"
if errorlevel 1 goto :error
echo Painel instalado com sucesso.
echo Use iniciar_painel.cmd para abrir.
pause
exit /b 0
:error
echo Falha ao instalar o painel.
pause
exit /b 1
