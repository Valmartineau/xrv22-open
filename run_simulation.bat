@echo off
REM ============================================
REM  XRV22 PRO V22 — Mode Simulation (Windows)
REM ============================================
cd /d "%~dp0"

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERREUR] Python n'est pas installe ou pas dans le PATH.
    echo Telechargez Python 3.10+ depuis https://www.python.org/downloads/
    pause
    exit /b 1
)

pip install -r requirements.txt --quiet
echo Lancement de XRV22 PRO V22 en mode SIMULATION...
echo.
python -m xrv22.main --sim

if %errorlevel% neq 0 pause
