@echo off
title Zar - Agente IA V10.3
cd /d "%~dp0"
python -m pip install -r requirements.txt
rem Worker de Instagram de este PC: arranca en segundo plano junto a ZAR si esta configurado.
rem Tiene su propio bloqueo, asi que no se duplica si la tarea programada ya lo arranco.
if exist ".local\instagram-runtime\Scripts\pythonw.exe" if exist ".local\instagram-worker\config.json" (
  echo Iniciando worker de Instagram de este PC...
  start "" ".local\instagram-runtime\Scripts\pythonw.exe" "scripts\zar-local-worker-service.py"
)
echo.
echo Iniciando Zar...
echo Abre http://127.0.0.1:8765
echo.
python app\main.py
pause
