@echo off
cd /d "%~dp0"
set "PORTFOLIO_PROFILE_PLOTLY_ON_START=1"
echo ============================================
echo   PORTAFOGLIO TITOLI - Installazione e Avvio
echo ============================================
echo.

REM Controlla se Python e' installato
python --version >nul 2>&1
if errorlevel 1 (
    echo ERRORE: Python non trovato.
    echo Scaricalo da https://www.python.org/downloads/
    echo IMPORTANTE: durante l'installazione spunta "Add Python to PATH"
    pause
    exit /b 1
)

echo Python trovato. Installazione librerie...
python -m pip install streamlit plotly yfinance pandas requests beautifulsoup4 --quiet

echo.
echo Avvio applicazione...
echo L'applicazione si aprira' nel browser.
echo Per chiuderla premi Ctrl+C in questa finestra.
echo.
python -m streamlit run "app.py"
pause
