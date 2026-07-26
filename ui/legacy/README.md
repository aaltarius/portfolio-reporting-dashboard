# Legacy Review Notes

Questa cartella traccia il codice Streamlit lasciato in revisione dopo la scelta
definitiva di usare la sidebar come superficie operativa.

## 2026-07-26 - Accesso operativo solo sidebar

Percorsi vivi:

- `ui/sidebar.py` apre i form-server operativi.
- `ui/form_server/gestione.py` gestisce operazioni, strumenti e liquidita'.
- `ui/form_server/sator.py` gestisce SATOR.
- `ui/form_server/export_pp.py` gestisce l'export Portfolio Performance.

Blocchi legacy ancora nel codice sorgente, marcati con `LEGACY_REVIEW`:

- `ui/pages/operazioni.py`: vecchi dialog Streamlit del Centro Operativo interno.
- `ui/pages/pianificazione.py`: vecchio modulo SATOR interno e helper collegati.

Motivo della scelta: i blocchi sono stati commentati invece che spostati
fisicamente per evitare un refactor grande nello stesso passaggio UI. La prossima
revisione puo' eliminarli oppure migrare eventuali funzioni ancora utili nei
moduli `ui/form_server/*` o `core/services/*`.
