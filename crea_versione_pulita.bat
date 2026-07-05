@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1

echo.
echo  ============================================================
echo   Portfolio Dashboard - Creazione versione pulita
echo  ============================================================
echo.
echo  Crea una COPIA del progetto nella cartella accanto,
echo  senza dati personali, pronta da consegnare.
echo  L'originale NON viene toccato.
echo.

:: Cartella sorgente = cartella di questo script
set "SRC=%~dp0"
set "SRC=%SRC:~0,-1%"

:: Cartella destinazione = sibling
for %%A in ("%SRC%\..") do set "PARENT=%%~fA"
set "DEST=%PARENT%\portfolio_pulito"

echo  Sorgente    : %SRC%
echo  Destinazione: %DEST%
echo.
set /p CONFIRM= Procedere? [S/N]:
if /i "!CONFIRM!" neq "S" (
    echo.
    echo  Annullato.
    pause
    exit /b 0
)

echo.
echo  [1/4] Pulizia destinazione precedente...
if exist "%DEST%" (
    rmdir /s /q "%DEST%"
    if errorlevel 1 (
        echo  ERRORE: impossibile eliminare %DEST%
        echo  Chiudi eventuali file aperti dalla cartella e riprova.
        pause
        exit /b 1
    )
)

echo  [2/4] Copia del codice sorgente (esclusi i dati personali)...
robocopy "%SRC%" "%DEST%" /E /NFL /NDL /NJH /NJS /nc /ns /np ^
  /XD "%SRC%\data\portfolio" ^
      "%SRC%\data\prices" ^
      "%SRC%\data\logs" ^
      "%SRC%\data\ai_reports" ^
      "%SRC%\data\cache" ^
      "%SRC%\backups" ^
      "%SRC%\.data" ^
      "%SRC%\__pycache__" ^
      "%SRC%\.streamlit" ^
      "%SRC%\.cache" ^
      "%SRC%\docs\superpowers" ^
  /XF "%SRC%\data\config\ai_config.json" ^
      "%SRC%\data\config\portafoglio_meta.json" ^
      "%SRC%\data\config\benchmark_last_refresh.json" ^
      "%SRC%\HANDOFF_LUNEDI.md" ^
      "%SRC%\portfolio_dashboard_brief_per_altra_ai_v2.md" ^
      "%SRC%\test_enrichment_results.json" ^
      "%SRC%\test_enrichment_report.html" ^
      "*.pyc" "*.pyo" "*.pyd" >nul

:: robocopy restituisce codici 0-7 per successo
if errorlevel 8 (
    echo  ERRORE durante la copia (codice %errorlevel%).
    pause
    exit /b 1
)

echo  [3/4] Creazione struttura cartelle dati vuote...
mkdir "%DEST%\data\portfolio"          2>nul
mkdir "%DEST%\data\prices"             2>nul
mkdir "%DEST%\data\logs"               2>nul
mkdir "%DEST%\data\ai_reports"         2>nul
mkdir "%DEST%\data\cache\analytics"    2>nul
mkdir "%DEST%\data\cache\figures"      2>nul
mkdir "%DEST%\data\cache\derived_runtime" 2>nul
mkdir "%DEST%\backups"                 2>nul

echo  [4/4] Verifica file sensibili non copiati...
set WARN=0
if exist "%DEST%\data\config\ai_config.json"             set WARN=1 & echo  [!] ATTENZIONE: ai_config.json presente (API key!)
if exist "%DEST%\data\portfolio\portafoglio_data.json"   set WARN=1 & echo  [!] ATTENZIONE: portafoglio_data.json presente
if exist "%DEST%\data\prices\portafoglio_storico_prezzi.json" set WARN=1 & echo  [!] ATTENZIONE: storico prezzi presente
if exist "%DEST%\test_enrichment_results.json"           set WARN=1 & echo  [!] ATTENZIONE: test_enrichment_results.json presente (ISIN reali)

echo.
if "!WARN!" == "1" (
    echo  *** VERIFICA MANUALE RICHIESTA - alcuni file sensibili potrebbero ***
    echo  *** essere stati copiati. Controlla la destinazione prima di       ***
    echo  *** consegnare la cartella.                                         ***
) else (
    echo  ============================================================
    echo   Tutto OK. Versione pulita creata in:
    echo   %DEST%
    echo  ============================================================
    echo.
    echo  L'amico dovra':
    echo   1. Installare Python 3.11+
    echo   2. pip install -r requirements.txt
    echo   3. Avviare con avvia_portafoglio.bat oppure:
    echo      streamlit run app.py
    echo.
    echo  Al primo avvio l'app si inizializza con un portafoglio vuoto.
)
echo.
pause
