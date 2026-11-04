@echo off
cd /d "%~dp0"
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

echo Python trovato. Verifica librerie...
python -c "import streamlit, plotly, yfinance, pandas, requests, bs4" >nul 2>&1
if errorlevel 1 (
    echo Librerie mancanti. Installazione da requirements.txt...
    python -m pip install -r requirements.txt --quiet
) else (
    echo Librerie gia' presenti. Installazione saltata.
)

echo.
echo Avvio applicazione...
echo L'applicazione si aprira' nel browser.
echo Per chiuderla premi Ctrl+C in questa finestra.
echo.
python -m streamlit run "app.py"
pause
