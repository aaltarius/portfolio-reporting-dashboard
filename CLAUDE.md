# CLAUDE.md

Guida rapida per un agente AI che riprende il lavoro su questo repo. Non
duplica la documentazione di progetto: la fonte primaria resta
`STATO_OPERATIVO_5.0_PRE.md`, da leggere per intero prima di modificare
rendering, navigazione, cache, calcoli finanziari, grafici, tema o
componenti Streamlit. Da li' si arriva a `docs/archivio_5_0/` (regole non
negoziabili, architettura, strategia cache) e a `TODO_5.0.md`.

## Prima di scrivere codice

1. Leggi `STATO_OPERATIVO_5.0_PRE.md` — stato reale, cosa e' stato fatto,
   cosa resta, cosa non fare.
2. Se tocchi layout/navigazione/cache/render, leggi anche
   `docs/archivio_5_0/01_REGOLE_NON_NEGOZIABILI.md`: la regola madre e' che
   Sestante prepara tutto prima dell'uso, mai render o rerun a sorpresa
   durante la navigazione.
3. Se tocchi formule finanziarie, cerca prima se esistono gia' in `core/`:
   non deve mai esistere una seconda definizione della stessa metrica in
   una pagina o in un grafico.

## Convenzioni operative di questo repo

- `tests/` e' interamente escluso da git (vedi `.gitignore`) per scelta
  esplicita del proprietario del repo, confermata il 2026-08-05: i test
  restano locali/effimeri, nessuna CI. Non proporre di versionarli senza
  che sia l'utente a chiederlo esplicitamente.
- Qualunque fixture di test che tocca dati deve isolare i path con
  `monkeypatch` (mai scrivere-poi-ripristinare sui file reali in
  `data/`): un incidente di perdita dati reale e' gia' avvenuto per questo
  motivo (vedi `STATO_OPERATIVO_5.0_PRE.md`, sezione "Strumenti chiusi,
  coerenza dati e KPI").
- Backup automatico gia' attivo: `save_data()` chiama `create_backup_bundle()`
  prima di ogni scrittura se `settings.backup.enabled` e
  `backup_before_save` sono `True` (lo sono di default, 20 backup
  conservati). Non serve reintrodurlo.
- Pattern di bug ricorrente da tenere a mente: qualunque codice che elenca
  "strumenti attivi" per un conteggio, un KPI o un'aggregazione deve
  escludere gli strumenti chiusi/terminali passando da
  `active_fetch_tickers(data)` (`core/domain/instrument_status.py`) o dal
  `chiusi_tickers` gia' calcolato in `ui/runtime_context.py`. E' stato
  trovato e corretto sei volte in punti diversi (KPI Quotazioni, toast
  sidebar, tabella diagnostica quotazioni, grafico P/L per categoria,
  tabella P/L settimanale, firma cache per categoria) prima di essere
  chiuso come classe di bug. Mai reinventare il filtro ad-hoc.
- Repo GitHub collegato (`aaltarius/portfolio-reporting-dashboard`) e'
  privato.
- Piani di lavoro strutturati (spec + task) per refactor grossi vivono in
  `docs/superpowers/specs/` e `docs/superpowers/plans/`; lo storico di
  esecuzione in `.superpowers/sdd/<piano>/`.

## Cosa non fare (ribadito da 01_REGOLE_NON_NEGOZIABILI.md)

- Niente radio/selectbox/selector per sostituire le tab principali gia'
  pronte.
- Niente caricamento lazy delle sezioni principali per accorciare l'avvio.
- Niente formula finanziaria duplicata fuori da `core/`.
- Niente colore/icona/stile inventato se esiste gia' un token nel tema
  centralizzato.
- Nessuna modifica performance dichiarata risolta senza log prima/dopo.
