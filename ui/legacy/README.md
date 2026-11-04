# Legacy Review Notes

Questa cartella traccia il codice Streamlit lasciato in revisione dopo la scelta
definitiva di usare la sidebar come superficie operativa.

## 2026-07-26 - Accesso operativo solo sidebar

Percorsi vivi:

- `ui/sidebar.py` apre i form-server operativi.
- `ui/form_server/gestione.py` gestisce operazioni, strumenti e liquidita'.
- `ui/form_server/sator.py` gestisce SATOR.
- `ui/form_server/export_pp.py` gestisce l'export Portfolio Performance.

Blocchi legacy ancora nel codice sorgente, marcati con `LEGACY_REVIEW`: nessuno.

Nota 5.0-pre: i vecchi dialog Streamlit del Centro Operativo interno sono stati
rimossi da `ui/pages/operazioni.py`; il vecchio modulo SATOR interno e i relativi
helper sono stati rimossi da `ui/pages/pianificazione.py`. Le funzioni operative
vive restano nei moduli `ui/form_server/*`, aperti dalla sidebar.
