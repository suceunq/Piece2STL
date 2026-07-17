@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo L'environnement Python est introuvable.
    echo Lancez d'abord l'installation indiquee dans README.md.
    pause
    exit /b 1
)

start "Piece2STL" ".venv\Scripts\pythonw.exe" "scripts\piece2stl_app.py"
