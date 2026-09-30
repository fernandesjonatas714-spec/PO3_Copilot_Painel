@echo off
setlocal
set "PAINEL_DIR=%~dp0"
set "PYTHON_EXE=%PAINEL_DIR%.venv\Scripts\python.exe"
set "PAINEL_URL=http://127.0.0.1:8501/"
if not exist "%PYTHON_EXE%" (
  echo O ambiente do painel ainda nao foi instalado.
  echo Execute primeiro instalar_painel.cmd.
  pause
  exit /b 1
)

rem Se o painel ja estiver ativo, apenas abre a pagina existente.
powershell -NoProfile -Command "try { $resposta = Invoke-WebRequest -Uri '%PAINEL_URL%' -UseBasicParsing -TimeoutSec 2; if ($resposta.StatusCode -eq 200) { exit 0 } } catch {}; exit 1"
if not errorlevel 1 (
  start "" "%PAINEL_URL%"
  exit /b 0
)

rem Porta fixa e modo nao-headless fazem o Streamlit abrir o navegador.
"%PYTHON_EXE%" -m streamlit run "%PAINEL_DIR%app.py" --server.address 127.0.0.1 --server.port 8501 --server.headless false --server.showEmailPrompt false --browser.gatherUsageStats false
endlocal
