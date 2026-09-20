@echo off
title Zar - Agente IA V10.3
cd /d "%~dp0"
python -m pip install -r requirements.txt
echo.
echo Iniciando Zar...
echo Abre http://127.0.0.1:8765
echo.
python app\main.py
pause
