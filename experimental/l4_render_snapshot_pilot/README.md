# Pilot L4 render snapshot - sperimentale

Questo codice e' stato spostato fuori dal runtime ordinario il 2026-08-02.

Motivo:

- il primo pilot collegato a Cruscotti categorie ha bloccato l'avvio al passo
  4/11 perche' tentava conversioni Plotly/Kaleido durante il render Streamlit;
- questa modalita' viola il principio operativo di Sestante: preparare prima,
  navigare senza sorprese;
- il registry cache operativo deve governare L1-L3 e azioni esplicite, non
  attivare snapshot L4 dentro la navigazione.

Regola per riaprire il tema:

- nessun builder L4 puo' essere richiamato da una pagina Streamlit ordinaria;
- gli snapshot devono essere pre-costruiti fuori render, con timeout, stato
  `ready/stale/building/failed` e fallback nativo;
- Setup non deve esporre flag ordinari finche' la pipeline non e' completa e
  verificata con baseline prima/dopo.

File sperimentali:

- `core/render_snapshot_cache.py`
- `core/render_snapshot_policy.py`
- `ui_render_snapshots/cruscotti_category.py`
