@echo off
REM ============================================
REM  XRV22 PRO V22 — Lanceur Windows
REM ============================================
cd /d "%~dp0"

REM Verifie que Python est installe
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [ERREUR] Python n'est pas installe ou pas dans le PATH.
    echo Telechargez Python 3.10+ depuis https://www.python.org/downloads/
    echo IMPORTANT : cochez "Add Python to PATH" lors de l'installation.
    echo.
    pause
    exit /b 1
)

REM Installe les dependances si necessaire
echo Installation des dependances...
pip install -r requirements.txt --quiet

REM Lance XRV22
echo.
echo Lancement de XRV22 PRO V22...
echo.
python -m xrv22.main %*

if %errorlevel% neq 0 (
    echo.
    echo [ERREUR] XRV22 s'est arrete avec une erreur.
    pause
)
