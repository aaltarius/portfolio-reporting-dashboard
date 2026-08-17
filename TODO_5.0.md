# TODO 5.0

Fonte operativa principale: `STATO_OPERATIVO_5.0_PRE.md`.
Inventario tecnico cache: `docs/archivio_5_0/06_CACHE_INVENTORY_5.0.md`.
Chiusura pilota cache: `docs/archivio_5_0/07_CHIUSURA_FASE_CACHE_5.0.md`.
Migrazione definitiva cache unica: `docs/archivio_5_0/08_CACHE_UNICA_5.0_MIGRAZIONE_DEFINITIVA.md`.

Questo file contiene solo le cose aperte. Lo storico delle modifiche resta in
`CHANGELOG.md`.

---

## Da fare adesso

Fase pilota L3 chiusa. Cache unica applicativa ancora aperta.

Deciso 2026-08-17: `core/page_cache.py` resta il magazzino L3 definitivo
(nessuna riscrittura in `core/cache_store.py`, mai iniziata e senza motivo
concreto) — vedi `docs/archivio_5_0/08_CACHE_UNICA_5.0_MIGRAZIONE_DEFINITIVA.md`.
Questo ha sbloccato la promozione di tutti gli artefatti `storage="page_artifact"`
gia' verificati contro il contratto unico (owner, firma, dipendenze,
invalidazione, passaggio reale da `core/cache_orchestrator.py`), senza
aspettare una decisione di architettura mai presa.

Censimento completo dei 20 artefatti ancora `pilot` fatto artefatto per
artefatto (non a campione): 14 erano gia' collegati correttamente al
magazzino e sono stati promossi subito a `registered_provider` in un'unica
sessione (nessun codice nuovo, solo verifica + etichetta ciascuno):
`quotazioni.diagnostic_table`, `quotazioni.dataset_bundle`,
`quotazioni.category_ticker_bundles`, `dati.quality_table`,
`dati.cache_diagnostics`, `dati.remote_php_export`,
`cruscotti.category_dashboard_bundles`, `cruscotti.analitica_bundle`,
`cruscotti.advanced_analysis_data`, `cruscotti.category_metrics`,
`mercati.overview_rows`, `mercati.base100_frame`,
`summary.dashboard_payload`, `runtime.orchestration_payload`.

Stato registry dopo il censimento (14 etichette): 21 `registered_provider`,
6 `pilot`, 1 `documented_exception`, 0 `legacy_provider`.

Primo dei 3 "senza cache reale" completato 2026-08-17:
`confronto.comparison_report` era ricostruito ad ogni rerun in
`ui/pages/confronto.py:901` (nessuna cache, solo etichetta nel registro).
Collegato a `core/cache_orchestrator.py::get_or_build_registered_artifact`
con firma su `snapshot_ids` (ID snapshot selezionati),
`portfolio_data_signature` (`ctx.data_sig`), `comparison_options`
(multi-snapshot, benchmark) e `reporting_settings` (decimali export) —
cambia solo quando cambia davvero la selezione, non ad ogni rerun della
pagina. Test aggiunto in `tests/test_cache_policy_5.py`
(`test_confronto_page_uses_registered_page_artifact_for_comparison_report`).
Promosso a `registered_provider`. Stato registry ora: **22
`registered_provider`**, **5 `pilot`**, 1 `documented_exception`,
0 `legacy_provider`.

Secondo dei 3 "senza cache reale" completato 2026-08-17:
`summary.report_payload` (`ui/pages/summary.py:370`, generato dal pulsante
"Genera report") era gia' dietro un click esplicito (non ricostruito ad
ogni rerun come Confronto), ma senza passare dal magazzino registrato: solo
loggato per diagnostica. Collegato allo stesso modo, firma su
`portfolio_data_signature` (`ctx.data_sig`), `report_options` (le checkbox
di cosa includere), `theme_signature`, `operations_report` (conteggio righe
movimenti) e `reporting_settings`. Test aggiunto in
`tests/test_cache_policy_5.py`
(`test_summary_page_uses_registered_page_artifact_for_report_payload`).
Promosso a `registered_provider`. Stato registry ora: **23
`registered_provider`**, **4 `pilot`**, 1 `documented_exception`,
0 `legacy_provider`.

I 4 rimasti in `pilot` sono classificati per tipo di lavoro residuo, non
tutti uguali:

- **Nessuna cache reale ancora scritta** (serve codice vero, stesso schema
  gia' applicato due volte): `mercati.live_snapshot` (scrive/legge un file
  JSON direttamente in `core/infrastructure/market_auto_refresh.py`, mai
  passato dal registry — architettura diversa dagli altri due perche' e' un
  servizio in background, non generato dentro il render di una pagina).
- **Cache reale gia' funzionante, ma tramite un meccanismo diverso e gia'
  definitivo** (`analytics.frozen_payload_store`/`store_frozen_analysis_cache`,
  non `get_or_build_registered_artifact`): `cruscotti.benchmark_frozen_analysis`,
  `cruscotti.accumuli_frozen_analysis` — qui serve solo decidere come
  rappresentare correttamente nel registry una cache che passa da un altro
  provider gia' promosso, non scrivere cache nuova.
- **Caso a parte**: `prebuild.registry_engine` e' il motore che decide cosa
  preparare in anticipo (gia' collegato al registry via
  `iter_prebuild_artifact_specs()` in `ui/prewarm_bundle.py`), non un
  payload da mettere lui stesso in cache — la sua "definizione di finito"
  va valutata separatamente dagli altri.

1. Eseguire e mantenere `tools/cache_surface_audit.py` come censimento statico
   delle cache vive.
2. Registrare nel policy layer o giustificare formalmente tutte le cache
   residue: Streamlit cache, FigureCache, derived runtime, benchmark/Mercati,
   frozen analysis, prewarm, cache modulo.
3. Migrare una famiglia cache per volta sotto il contratto unico (i 3
   artefatti senza cache reale sono il prossimo lavoro vero: scrivere il
   collegamento a `core/cache_orchestrator.py` con test, uno alla volta).
4. Aggiornare Dati e render log per mostrare la copertura reale della cache
   unica.
5. Solo dopo ottimizzare Cruscotti come render UI full-tabs.

---

## Da fare dopo

1. Collegare gli artefatti ad azione esplicita al registry cache:
   Summary report, Confronto report, Mercati live snapshot, Benchmark frozen e
   Accumuli frozen.
2. Completare archivio report step 2: rigenerazione con le stesse opzioni
   salvate.
3. Consolidare dataset rischio/rendimento strumenti e migrare gradualmente
   Cruscotti, Quotazioni e SATOR verso il servizio centrale.
4. Valutare `core/page_cache.py` come store L3 definitivo o evolverlo in
   `core/cache_store.py`.
5. Costruire prebuild guidato dal registry, fuori dal render ordinario.
6. Tenere Mercati in osservazione per qualche giorno: dati, semaforo,
   auto-refresh background e striscia informativa.
7. Validare Portfolio Insights sul portafoglio reale prima di renderlo
   definitivo.

---

## Maturazione 5.0 (prima del tag definitivo)

Priorita' 8 di `STATO_OPERATIVO_5.0_PRE.md`, sezione 5 — non cache, qualita'
e robustezza. Con i progetti del libro chiusi (vedi sotto), questa e' la
traccia concreta rimasta per dichiarare la 5.0 matura:

1. ~~Audit difensivo dei chart builder in `ui/charts/`~~ fatto (2026-08-11):
   24 funzioni corrette su 9 file, tutte quelle senza guardia o con guardia
   rotta/incoerente sulle 51 censite. Vedi `STATO_OPERATIVO_5.0_PRE.md`
   sezione 3. Follow-up minori emersi dalla review finale, non urgenti:
   - unificare la selezione duplicata del `chart_id` (stesso ternario/if-elif
     ripetuto due volte) in `build_instrument_bar_chart` e
     `build_category_bar_chart` (`ui/charts/home.py`);
   - quando si fara' la deduplicazione gia' nota di `build_risk_contribution_chart`
     (copia identica in `ui/charts/analisi.py` e `ui/charts/analitica.py`,
     entrambe gia' guardate separatamente in questo audit): la copia in
     `analisi.py` e' codice morto (nessun chiamante in produzione, la pagina
     `ui/pages/analisi.py` citata nella sua docstring non esiste piu') — va
     **rimossa**, non fusa con l'altra;
   - copertura test asimmetrica: la meta' "vuoto ma non None" di ~20 guardie
     non ha un test dedicato (solo il caso `None` e' testato sistematicamente).
2. Review complessiva del branch (`/code-review ultra`) prima di taggare la
   5.0 definitiva — cattura pattern trasversali che le review per singola
   feature (gia' fatte per B/C/D/A e per l'audit chart builder) non vedono
   per costruzione.

---

## Rimandato intenzionalmente

1. Miglioramento profondo SATOR con il prossimo piano acquisti reale.
2. Progetti dal libro in `ROADMAP_AI_FINANZA_LIBRO.md`: chiusi (2026-08-09)
   SATOR Frontier, Monte Carlo, clustering strumenti (Mappa strumenti) ed
   explainability ("Perché questo voto") — vedi `STATO_OPERATIVO_5.0_PRE.md`
   sezione 3. Storico decisionale ex-post archiviato (2026-08-11) per scelta
   esplicita, non urgente: non riaprire senza richiesta esplicita.
3. L4 render snapshot: resta solo in `experimental/l4_render_snapshot_pilot/`.
   Non rientra nel runtime finche' non esiste una pipeline di prebuild esterna
   al render Streamlit.

---

## Vincoli da non violare

- Tab principali sempre pronte all'avvio.
- Nessun radio/selectbox/selector per sostituire la navigazione.
- Nessuna modalita' visibile `Rapida/Completa` per nascondere grafici.
- Nessuna cache privata nelle pagine.
- Nessuna formula finanziaria duplicata nella UI.
- Tema, icone, colori e grafici sempre centralizzati.
