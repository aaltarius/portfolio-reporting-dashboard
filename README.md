# Portfolio Reporting Dashboard

`Portfolio Reporting Dashboard` is a Streamlit application for portfolio monitoring, analytics, reporting, and operational controls.

## Read before changing the app

Before modifying rendering, navigation, cache, financial formulas, charts, theme
or Streamlit layout, read:

- `STATO_OPERATIVO_5.0_PRE.md`

This is the single operational document for the 5.0-pre workstream. Historical
planning notes, cache audits, architecture notes and render baselines are kept in
`docs/archivio_5_0/` only as reference material. Separate research projects and
source documents live under `docs/progetti/` and `docs/fonti/`.

The most important rule is: Sestante prepares the experience before use. Do not
introduce intermediate reruns, page selectors or lazy rendering during navigation
unless the user explicitly asks for that tradeoff.

The project includes:

- portfolio overview and market value monitoring
- quote diagnostics and historical price views
- operations and cash movement registry
- advanced analytics (risk, drawdown, correlations, contribution analysis)
- portfolio summary and reporting exports
- comparison between portfolio snapshots
- data management, audit, and observability tools

## Main features

- multi-page Streamlit interface
- professional summary/reporting hub
- operational brief generated from the same Summary data
- reporting traceability and audit trail exports
- custom benchmark support
- settings for analytics, alerts, reporting, and i18n
- data import and quote maintenance tools

## Project structure

```text
app.py
avvia_portafoglio.bat
aggiorna_remoto.php
core/
persistence/
ui/
```

Runtime folders such as `data/` and `backups/` are generated locally and are intentionally excluded from version control.

## Requirements

- Python 3.11+ recommended
- Windows batch launcher included, but the app itself is standard Python/Streamlit

Install dependencies with:

```powershell
python -m pip install -r requirements.txt
```

## Run locally

### Option 1: batch launcher

```powershell
.\avvia_portafoglio.bat
```

### Option 2: direct Streamlit command

```powershell
python -m streamlit run app.py
```

At first run, the application recreates its local `data/` folder automatically.

## Notes for GitHub

This repository is prepared to track only source code and project configuration.

Excluded on purpose:

- runtime data
- backups
- caches
- local archives

If you want to publish the repository publicly, review `aggiorna_remoto.php` and any project text for personal, server, or deployment-specific information before pushing.

## Suggested repository name

`portfolio-reporting-dashboard`
