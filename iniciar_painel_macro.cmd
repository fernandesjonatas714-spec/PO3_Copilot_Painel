@echo off
setlocal
set "PAINEL_DIR=%~dp0"
set "PYTHON_EXE=%PAINEL_DIR%.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
  echo O ambiente do painel ainda nao foi instalado.
  pause
  exit /b 1
)
if exist "%PAINEL_DIR%.env" (
  for /f "usebackq tokens=1,* delims==" %%A in (`findstr /b "MT5_TERMINAL_PATH=" "%PAINEL_DIR%.env"`) do set "MT5_TERMINAL_PATH=%%B"
)
if not defined MT5_TERMINAL_PATH set "MT5_TERMINAL_PATH=C:\Program Files\Clear Investimentos MT5 Terminal\terminal64.exe"
set "AUTO_DATA_COLLECTION=true"
set "AUTO_DECISION_ENGINE=true"
set "SUPERVISOR_AI_ENABLED=true"
set "SHADOW_MODE_ENABLED=true"
"%PYTHON_EXE%" -m po3.launcher
endlocal
