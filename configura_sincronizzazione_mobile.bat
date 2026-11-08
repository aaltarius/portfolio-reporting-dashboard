@echo off
cd /d "%~dp0"
echo ============================================
echo   SESTANTE - Configurazione sincronizzazione Mobile
echo ============================================
echo.
python --version >nul 2>&1
if errorlevel 1 (
    echo ERRORE: Python non trovato.
    pause
    exit /b 1
)
python -m tools.sync_configura %*
echo.
pause
