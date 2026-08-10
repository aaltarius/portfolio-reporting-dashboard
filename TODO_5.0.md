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

1. Eseguire e mantenere `tools/cache_surface_audit.py` come censimento statico
   delle cache vive.
2. Registrare nel policy layer o giustificare formalmente tutte le cache
   residue: Streamlit cache, FigureCache, derived runtime, benchmark/Mercati,
   frozen analysis, prewarm, cache modulo.
3. Migrare una famiglia cache per volta sotto il contratto unico.
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

1. Audit difensivo dei chart builder in `ui/charts/`: 51 funzioni
   `build_*_chart` su 12 file, un solo file (`operazioni.py`) usa l'helper
   centralizzato `empty_chart()` gia' esistente in `ui/charts/runtime.py` —
   gli altri fanno guardie ad-hoc o rischiano di non averne. Verificare
   sistematicamente dati vuoti, singolo giorno, strumento appena aperto;
   convergere su `empty_chart()` dove manca o e' duplicato a mano.
2. Review complessiva del branch (`/code-review ultra`) prima di taggare la
   5.0 definitiva — cattura pattern trasversali che le review per singola
   feature (gia' fatte per B/C/D/A) non vedono per costruzione.

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
