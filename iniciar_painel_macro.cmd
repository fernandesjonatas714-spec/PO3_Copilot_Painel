@echo off
setlocal
set "PAINEL_DIR=%~dp0"
set "PYTHON_EXE=%PAINEL_DIR%.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
  echo O ambiente do painel ainda nao foi instalado.
  pause
  exit /b 1
)
"%PYTHON_EXE%" -m po3.launcher
endlocal
