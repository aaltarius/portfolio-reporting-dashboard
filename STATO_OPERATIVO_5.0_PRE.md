# Stato operativo 5.0-pre

Questo e' il documento unico da leggere per riprendere il lavoro sulla copia
`5.0-pre` senza perdere il filo.

Sequenza di lettura, in ordine (il numero nel nome del file e' l'ordine
consigliato, leggibile direttamente dalla cartella senza aprire nulla):

Root:

1. `README.md`: avvio rapido e orientamento repository.
2. `CLAUDE.md`: introduzione rapida per un agente AI, rimanda qui.
3. `STATO_OPERATIVO_5.0_PRE.md`: questo documento, fonte operativa
   principale — se un altro documento e' in contrasto, vince questo.
4. `CHANGELOG.md`: diario storico cronologico delle modifiche gia' fatte.
5. `TODO_5.0.md`: elenco attuale delle cose aperte, deve rispecchiare la
   sezione 5 di questo documento.

Governance vincolante, `docs/archivio_5_0/` (da leggere prima di ogni
modifica a rendering, navigazione, cache, grafici, formule o UI Streamlit):

- `01_REGOLE_NON_NEGOZIABILI.md`: vincoli da non violare.
- `02_ARCHITETTURA_5.0.md`: principi modulari e finanziari.
- `03_PROTOCOLLO_PERFORMANCE_5.0.md`: metodo per interventi su
  tempi/cache/render.

Cache, dettaglio tecnico in ordine cronologico/di dipendenza,
`docs/archivio_5_0/` (restano consultabili, ma non sono la fonte primaria se
in contrasto con questo file):

- `04_CACHE_STRATEGY_5.0.md`: policy e livelli L0-L4, definizione tecnica
  ancora valida.
- `05_PIANO_UNICO_CACHE_RENDER_5.0.md`: piano operativo originale a fasi; la
  sua tabella di stato interna e' superata dai due punti seguenti.
- `06_CACHE_INVENTORY_5.0.md`: fotografia iniziale delle cache censite,
  baseline storica.
- `07_CHIUSURA_FASE_CACHE_5.0.md`: chiusura del solo pilota
  registry/page-cache L3, non della cache unica applicativa.
- `08_CACHE_UNICA_5.0_MIGRAZIONE_DEFINITIVA.md`: piano corretto e vincolante
  per portare tutte le cache residue sotto un unico contratto.
- `09_RIPRESA_ORCHESTRAZIONE_CACHE_2026-08-03.md`: punto di ripresa
  operativo della fase cache sospesa, con stato reale, completato, residui e
  primo comando da eseguire alla ripartenza. Leggere questo per sapere
  esattamente da dove riprendere.
- `10_RENDER_BASELINE_2026-08-02.md`: baseline performance storica, log
  misure non un piano.
- `old/`: documenti di questo archivio interamente superati (proposta
  tentata e ritirata), non piu' citati da questa mappa; conservati solo per
  ricostruire perche' una strada e' stata scartata.

Refactor gia' eseguiti, con spec/piano tracciati, `docs/superpowers/`:

- `specs/2026-08-03-strumenti-chiusi-design.md` e
  `plans/2026-08-03-strumenti-chiusi.md`: spec e piano a 23 task del refactor
  "gestione unificata strumenti chiusi", gia' completato ed eseguito.

Fuori dal percorso ordinario, non prioritario:

- `docs/progetti/ROADMAP_AI_FINANZA_LIBRO.md`: progetto separato ispirato al
  libro, non prioritario nel percorso ordinario.
- `docs/fonti/PYTHON-per-l'AI-e-la-Finanza.pdf`: fonte PDF del progetto libro.

File dati vivi:

- `data/portfolio/portafoglio_data.json`
- `data/portfolio/portafoglio_snapshots.json`
- `data/portfolio/portafoglio_sator_decisions.json`

File dati conservativi o sospetti sono stati spostati in
`data/forensic/portfolio/` e non devono essere letti dall'app come sorgenti
operative.

---

## 1. Regole operative da ricordare sempre

Sestante deve preparare prima e navigare senza sorprese.

Regole non negoziabili:

- navigazione principale con tab native Streamlit gia' pronte;
- niente pagina singola con radio/selectbox/selector;
- niente modalita' visibili `Rapida/Completa` per saltare grafici attesi;
- niente render lazy per ridurre artificialmente l'avvio;
- niente rerun o caricamenti inattesi durante la consultazione;
- Mercati resta opzionale/on demand e non deve pesare sull'avvio ordinario;
- form-server e sidebar restano il canale operativo per evitare rerun continui;
- formule finanziarie, metriche e dati condivisi devono stare nel `core/`;
- tema, icone, colori e impostazioni grafici devono restare centralizzati;
- ogni modifica performance richiede log prima/dopo, ipotesi e test.

Errore gia' commesso e da non ripetere:

- non reintrodurre router a pagina singola;
- non reintrodurre radio o selettori per scegliere una pagina/render;
- non spostare il costo dall'avvio al click dell'utente.

---

## 2. Stato della copia

- Versione stabile di partenza: `4.9.40`.
- Copia di lavoro: `5.0-pre`.
- Schema dati: invariato.
- Obiettivo della copia: maturare stabilita', performance, coerenza finanziaria,
  modularita' e usabilita' senza perdere la versione funzionante.

La copia `4.9.40` resta il riferimento stabile. Tutte le attivita' qui sotto
riguardano solo `5.0-pre`.

---

## 3. Cosa e' stato fatto

### Governo e architettura

- Creati i documenti guida `01_REGOLE_NON_NEGOZIABILI.md` e
  `02_ARCHITETTURA_5.0.md`.
- Riordinata la documentazione: root ridotta ai documenti vivi, piani e analisi
  storiche spostati in `docs/archivio_5_0/`.
- Ripulita `data/portfolio`: lasciati solo i file operativi, backup manuali e
  snapshot storici spostati in `data/forensic/portfolio/`.
- Fissata la centralita' di modularita', tema unico, formule finanziarie nel
  core, impostazioni grafici centralizzate e dataset condivisi prima della UI.
- Creati `03_PROTOCOLLO_PERFORMANCE_5.0.md`,
  `05_PIANO_UNICO_CACHE_RENDER_5.0.md`, `04_CACHE_STRATEGY_5.0.md` e
  `06_CACHE_INVENTORY_5.0.md`.
- Aggiunto `tools/perf_render_log_analyzer.py` come base per leggere i render
  log in modo ripetibile.

### Strumenti chiusi, coerenza dati e KPI (2026-08-03/05)

- Unificata la gestione degli strumenti chiusi: stato aperto/chiuso/terminale
  sempre calcolato dal registro eventi (mai dal campo `stato`, morto). Nuovo
  `core/domain/instrument_status.py` con `active_fetch_tickers()` come unico
  filtro fetch quotazioni. Spec e piano completi in
  `docs/superpowers/specs/2026-08-03-strumenti-chiusi-design.md` e
  `docs/superpowers/plans/2026-08-03-strumenti-chiusi.md` (23 task, eseguiti
  con subagent-driven-development).
- `discharge_lot()` come unica definizione dello scarico PMC su
  vendita/rimborso, al posto di quattro implementazioni indipendenti; soglia
  posizione azzerata unificata su `QTY_ZERO_EPS`.
- Chiusa una classe di bug ricorrente (trovata e corretta sei volte in punti
  diversi): uno strumento chiuso/rimborsato che restava conteggiato o perdeva
  contributo storico perche' un punto di aggregazione non passava dal filtro
  canonico. Corretti: KPI "Letture OK/Warning/Errori" Quotazioni e toast
  sidebar (denominatore), tabella diagnostica quotazioni (riga stantia),
  grafico "P/L per Categoria" (perdeva tutto lo storico del chiuso, non solo
  post-chiusura), tabella "Andamento ultima settimana" (chiuso spariva dal
  totale), firma cache Cruscotti per categoria (mai invalidata su eventi),
  calendario BTP (stime sintetiche invece dei dati fiscali reali registrati).
- Aggiunta sezione "Posizioni Chiuse" in Portafoglio (capitale liberato, P/L
  realizzato lordo/netto, commissioni, imposte, rendimento %); rimossa la
  sezione duplicata in Operazioni.
- Aggiunte etichette esplicite sui grafici P/L di Portafoglio e
  Cruscotti/Analitica per chiarire il perimetro (storico completo incl.
  chiusi vs. sole posizioni aperte oggi).
- Corretto un incidente di perdita dati (storico prezzi ridotto da 830 a 14
  giorni) causato da `tests/conftest.py` che scriveva sui file reali con
  restore in `finally`; fixture riscritta con `monkeypatch` per isolare
  interamente i path (`DATA_DIR`, `PRICES_DIR`, ecc.) su `tmp_path`. Dati di
  scarto dell'incidente conservati in
  `data/forensic/portfolio/recovery_20260804_081005/`.
- Verificato: backup automatico prima di ogni `save_data()` gia' attivo e
  funzionante (`backup.enabled=True`, `backup_before_save=True`, 20 backup
  conservati) — non e' la causa dell'incidente sopra (il test scriveva fuori
  da `save_data()`).

### Cache e performance

- Introdotto `core/cache_policy.py` come registry centrale degli artefatti.
- Introdotto `core/page_cache.py` come primo store L3 con sessione, processo,
  disco, manifest e statistiche.
- Introdotto `core/cache_orchestrator.py` come ingresso canonico per gli
  artefatti registrati: il codice runtime deve chiedere cache tramite
  `artifact_id`, lasciando a registry/orchestratore la scelta di `page_id`,
  `layer`, log e provider.
- Esteso `core/cache_orchestrator.py` al provider Plotly: `FigureCache` resta lo
  store tecnico specializzato, ma pagine, prewarm, Summary, Cruscotti,
  Portafoglio, Quotazioni, Dati e analisi congelate usano l'adapter registrato
  `get_registered_figure_cache()`.
- Esteso `core/cache_orchestrator.py` allo store persistente delle analisi
  congelate: Benchmark/Accumuli leggono e salvano payload tramite
  `analytics.frozen_payload_store`, non piu' con import diretto del provider
  gzip/pickle.
- Esteso `core/cache_orchestrator.py` alle cache runtime in memoria:
  market lookup, indici cashflow e cache eventi strumento dello `StateManager`
  usano `get_registered_runtime_cache()`.
- Collegati al registry/page-cache questi piloti reali:
  `quotazioni.diagnostic_table`, `quotazioni.dataset_bundle`,
  `portafoglio.positions_table`, `cruscotti.category_dashboard_bundles`,
  `cruscotti.analitica_bundle`, `dati.quality_table`,
  `dati.cache_diagnostics`.
- Introdotto `core/runtime_cache.py` come adapter unico per le cache runtime in
  memoria: ogni cache di processo deve avere un `artifact_id` registrato, un
  `clear_group`, statistiche e invalidazione esplicita.
- Ricondotte al runtime cache registry le cache lookup prezzi/ISIN di
  `core.market_data`, gli indici cashflow intermedi di `core.cashflow_indices`
  e la cache eventi per strumento dello `StateManager`.
- Riclassificate le famiglie non-page-artifact da `legacy_provider` a
  `registered_provider`: FigureCache, StateManager derived runtime, cashflow
  intermedi, benchmark series, market lookup e frozen payload store sono ora
  provider ufficiali censiti, non cache estemporanee.
- Aggiunti test di guardia per impedire il ritorno di `legacy_provider` e per
  verificare che le cache runtime passino dall'adapter centrale.
- Chiusi gli ultimi artefatti rimasti `planned`: Summary report, Confronto
  report, Mercati live snapshot, Benchmark/Accumuli frozen analysis e prebuild
  registry sono ora `pilot` con trigger, storage, clear group e policy di rerun
  espliciti.
- Il prewarm legge il registry tramite `iter_prebuild_artifact_specs()` e
  distingue nei propri stats i target noti dai target realmente costruiti.
- Le azioni isolate da pulsante registrano una decisione cache propria:
  `Aggiorna mercati` resta su `market_refresh_isolated` senza cache bust del
  portafoglio; `Genera report` registra `summary_report_isolated` e non eredita
  piu' il piano diagnostico di azioni precedenti.
- Anche le analisi congelate Cruscotti registrano decisioni proprie:
  `benchmark_frozen_analysis_isolated` e `accumuli_frozen_analysis_isolated`.
  I log del 2026-08-03 mostrano che il benchmark puo' costare circa 16 secondi
  quando viene rigenerato, ma il rerun successivo riusa l'artefatto congelato.
- Il componente comune delle analisi congelate e' ora idempotente: Benchmark e
  Accumuli mostrano il pulsante solo se l'analisi manca o se la firma e' stale.
  Se l'artefatto e' gia' fresco, resta visibile lo stato cache e non viene piu'
  proposta una rigenerazione ordinaria a vuoto.
- Mercati ha ora due derivati registrati in page-cache: `mercati.overview_rows`
  e `mercati.base100_frame`. La pagina resta on demand, ma dopo una prima
  costruzione riusa righe e dataframe base100 se la firma Mercati non cambia.
- Gli artefatti Cruscotti pesanti (`category_dashboard_bundles` e
  `analitica_bundle`) usano ora codec disco raw-pickle con fallback dai vecchi
  `.pickle.gz`, per ridurre il costo CPU della lettura su primo avvio processo.
- Rimossa la scansione pesante della cache Dati dal render ordinario.
- Rimossa la manutenzione automatica della cache figure dal costruttore
  ordinario: manutenzione solo con azione esplicita.
- Aggiunti marker di continuita' nei render log: processo, sessione,
  progressivo run e stato runtime delle page cache.
- Lo storico render mostra anche `ultimo_run` e `delta_vs_mediana`, cosi' e'
  chiaro quando l'ultimo avvio e' molto piu' veloce della mediana storica
  costruita prima delle ultime ottimizzazioni.
- Corretta la classificazione scenario del render log: un primo avvio di
  sessione/processo con firma dati gia' nota non viene piu' confuso con un
  `warm_rerun`; il log separa `profiling_scenario` e
  `profiling_cache_condition`.
- Ripristinata la navigazione standard dopo il tentativo errato di pagina
  singola.
- Rimosso da Quotazioni il controllo visibile `Rapida/Completa`.
- Gli smoke test Streamlit usano ora una fixture dati temporanea con
  micro-portafoglio e storico prezzi controllati; i file locali vengono
  ripristinati a fine test, quindi il risultato non dipende piu' da una copia
  momentaneamente vuota o parziale.
- Chiusi due edge case emersi dagli AppTest: log quotazioni vuoto con strumenti
  presenti e report operazioni senza colonna opzionale `note`.
- Benchmark e Accumuli mantengono congelata l'analisi finanziaria, ma la firma
  delle figure include tema e impostazioni grafici: un cambio palette aggiorna
  la resa visiva senza forzare la rigenerazione dei payload finanziari.
- Avviato tuning render UI sul punto centrale Plotly: il wrapper globale
  `safe_plotly_chart` rende idempotente la preparazione runtime delle figure
  gia' in memoria, senza togliere grafici, senza lazy rendering e senza cambiare
  la navigazione a tab complete.
- Avviato tuning render UI anche sulle tabelle: `render_styled_table` mantiene
  `st.dataframe` per tabelle operative, ma usa HTML statico per le tabelle
  marcate `static=True`, evitando widget Streamlit quando non servono
  interazione, sort o stato.
- Stabilizzate le key automatiche Plotly: `app.py` azzera il contatore del
  wrapper a inizio run, quindi gli stessi grafici mantengono key prevedibili tra
  rerun e Streamlit puo' riusare meglio lo stato widget.
- Rafforzato il binding Plotly: il wrapper viene ricreato a ogni script-run per
  evitare che `st._portfolio_safe_plotly_chart` trattenga una vecchia funzione
  non resettata dopo reload del modulo.
- Rimosso dal runtime l'uso deprecato di `streamlit.components.v1.html`: il log
  copiabile dei tempi usa `ui.streamlit_compat.render_html_iframe()` e quindi
  `st.iframe`.
- Corretto il refresh quotazioni: un prezzo fetched uguale al valore economico
  gia' presente nello storico non viene piu' contato come variazione materiale
  solo per riallineare `strumento.prezzo`; in quel caso il log puo' tracciare il
  riallineamento tecnico, ma non deve invalidare Portafoglio/Cruscotti/Report.
- Reso idempotente il salvataggio impostazioni: se il payload normalizzato non
  cambia, `save_settings()` non riscrive il JSON e la pagina Setup non genera
  `cache_bust`, force reload o dirty flags su Cruscotti/Report; il render log
  espone `settings_noop` invece di lasciare appesa una vecchia invalidazione.

Stato sincero della cache al 2026-08-03:

- chiusa la fase di censimento: niente artifact `planned` o `legacy_provider`;
- avviata la fase di orchestrazione unica: page-cache registrata ora passa da
  `core/cache_orchestrator.py`;
- avanzata la fase FigureCache: i consumatori runtime passano dall'adapter
  registrato, ma restano da uniformare diagnostica/clear/stats nel contratto
  multi-provider;
- avanzata la fase frozen analysis: load/store persistente passa
  dall'orchestratore, ma resta da uniformare la diagnostica delle entry stale e
  la pulizia per clear group;
- avanzata la fase runtime-cache: i consumatori principali passano
  dall'orchestratore, ma restano da uniformare statistiche e pulizia nella
  console multi-provider;
- ancora da completare: report archive e prewarm devono essere diagnosticati e
  comandati come provider specializzati dello stesso contratto, non come logiche
  parallele;
- solo dopo questa chiusura ha senso tornare al tuning fine dei millisecondi su
  Cruscotti o sulle singole sezioni.

Aggiornamento 2026-08-17 — governance cache quasi chiusa:

- Decisa la domanda rimasta sospesa dal 2026-08-03: `core/page_cache.py`
  resta il magazzino L3 definitivo, nessuna riscrittura in
  `core/cache_store.py` (mai iniziata, nessun motivo concreto). Vedi
  `docs/archivio_5_0/08_CACHE_UNICA_5.0_MIGRAZIONE_DEFINITIVA.md`.
- Censiti artefatto per artefatto (non a campione) i 20 rimasti `pilot`:
  14 erano gia' collegati correttamente al magazzino, promossi subito a
  `registered_provider` (solo verifica + etichetta, nessun codice nuovo).
- 3 non avevano ancora nessuna cache reale (`confronto.comparison_report`,
  `summary.report_payload` ricostruiti ad ogni azione senza passare dal
  registry): collegati a `core/cache_orchestrator.py::get_or_build_registered_artifact`
  con firma sulle dipendenze gia' dichiarate nella scheda, test aggiunti,
  promossi.
- 2 avevano gia' cache reale ma tramite un meccanismo diverso da quello
  dichiarato (`cruscotti.benchmark_frozen_analysis`,
  `cruscotti.accumuli_frozen_analysis`: usano `core/frozen_analysis_cache.py`,
  gia' un consumatore dei provider registrati `analytics.frozen_payload_store`
  e `figures.plotly_cache_provider`, non `get_or_build_registered_artifact`
  come la scheda affermava): corretti storage/owner nel registry per
  riflettere la realta', poi promossi.
- `prebuild.registry_engine` verificato (deriva i target dal registry via
  `iter_prebuild_artifact_specs()`, percorso sincrono solo al primo avvio a
  freddo) e promosso.
- **Registry ora: 26 `registered_provider`, 1 solo `pilot`
  (`mercati.live_snapshot`), 1 `documented_exception`, 0 `legacy_provider`.**
  L'unico rimasto e' deliberatamente non toccato: e' un servizio in
  background (thread separato, architettura incompatibile con
  `get_or_build_registered_artifact`) e la sezione Mercati e' ancora
  esplicitamente "in osservazione per qualche giorno" (Priorita' 6) — non e'
  lavoro lasciato a meta', e' una decisione presa, dettagliata in
  `TODO_5.0.md`.
- Non ancora fatto: aggiornare Dati/render log per mostrare la copertura
  reale della cache unica (punto 4 di "Da fare adesso" in `TODO_5.0.md`), e
  la review complessiva `/code-review ultra` prima del tag 5.0 definitivo
  (Priorita' 8). Nessun push al remoto GitHub eseguito in questa sessione.

### L4 render snapshot

- Il pilot L4 su Cruscotti categorie e' stato provato e poi ritirato.
- Motivo: costruire snapshot Plotly/Kaleido nel render ordinario puo' bloccare
  l'avvio.
- Stato attuale:
  - nessun import L4 nel runtime Cruscotti;
  - nessun artefatto L4 nel registry operativo;
  - nessun flag L4 in Setup/config;
  - codice conservato solo in `experimental/l4_render_snapshot_pilot/`.

### Dati e qualita strumenti

- La vecchia sezione `Arricchimento strumenti` e' diventata
  `Qualita dati strumenti`.
- Il dataset viene da `core/services/instrument_quality.py`.
- La tabella mostra completezza, fonte, storico, buchi, prezzo fermo,
  copertura e prima azione operativa.
- Le metriche rischio/rendimento restano nel dataset centrale ma non
  appesantiscono la vista Dati.
- Migliorata la leggibilita' della tabella con progress column, intestazioni
  piu' chiare e colonne compatte.

### Portafoglio

- Corretta la coerenza tra `Var gg euro`, `Var gg %`, colori e fonte prezzi.
- Riallineata la definizione di ultima giornata tra tabella, sintesi, best/worst
  e grafici.
- Corretto il grafico P/L ultima giornata per evitare delta fittizi.
- Aggiunti test di invariante contabile sulle posizioni.
- Migliorata la tabella `Controvalore del Portafoglio` con ultimo prezzo,
  PMC, mini-grafico finale, colonna ticker/loghi, evidenze giornaliere e
  indicatori BTP poco invasivi.
- Aggiunto pannello sperimentale `Portfolio Insights`, coerente con icone,
  categorie e bucket strategici ufficiali.
- Corretto (2026-08-13) un bug reale in `core/finance.py`, trovato
  dall'utente dopo un import di storico per 3 strumenti solo osservati
  (MMS.MI, XBAG.MI, XDEQ.MI): l'indice date dello storico portafoglio
  (`_build_portfolio_history_core`) era costruito sull'unione di tutte le
  date di tutti gli strumenti tracciati, non solo di quelli posseduti —
  strumenti che pubblicano NAV di weekend facevano infiltrare date
  sabato/domenica nello storico portafoglio, visibili come spazi nel
  grafico P/L di Overview ogni settimana. Nessun dato perso (solo indice
  date, non integrità prezzi). Fix incondizionato (`_filter_weekend_dates`,
  non solo per strumenti osservati: uno osservato oggi può essere
  comprato domani), coerente con la logica "niente weekend" già presente
  altrove nell'app; `cache_storico_portafoglio` bump a v8.

### Quotazioni

- Corretto il grafico `Rendimento dello strumento`, inclusi massimo/minimo e
  riferimento portafoglio.
- Aggiunti mini-grafici coerenti con popup e linea PMC.
- Rimossa lettura dati impropria dal renderer popup.
- Migliorata la tabella `Ultime quotazioni aggiornate`: font minimo 13px,
  colonne proporzionate e niente scroll orizzontale.
- Collegato il bundle shared Quotazioni al registry/page-cache L3: ticker,
  gruppi categoria e indici cashflow passano ora da
  `quotazioni.dataset_bundle` e il render log mostra la sorgente
  `session/process/disk/build`.

### Mercati

- Pagina Mercati resa opzionale/on demand.
- Il tasto aggiorna alimenta l'intero universo Mercati, non solo la vista.
- Aggiunto semaforo freschezza.
- Aggiunto auto-refresh background configurabile da Setup, spento di default.
- Migliorata copertura live/storico e diagnostica `ctx/file`.
- Aggiunti indici/proxy internazionali e orizzonte 3 mesi.
- Migliorate mappe forza relativa e tabelle: font leggibile, niente scroll
  orizzontale, colori fonte/stato/performance, `Aperto` verde e `Chiuso` rosso.
- Striscia mercati nel Portafoglio mantenuta informativa e staccabile da Setup.

### Pianificazione e SATOR

- SATOR operativo resta nella pagina standalone/sidebar per evitare rerun
  Streamlit continui.
- Pianificazione mantiene obiettivo, dashboard decisionale e fotografia.
- Arricchita la fotografia di riferimento gia' esistente, senza duplicare la
  mappa decisionale.
- Aggiunti impatto target, cap natura, qualita dati, filtro commissioni non
  zero, filtri client-side, ordinamento client-side e valutazione live.
- Aggiunto storico fotografie con ordine effettivo, disciplina di esecuzione,
  confronto proposta/scelta reale e apprendimento per funzione.
- La parte piu' evoluta di SATOR e' interessante ma resta da validare con il
  prossimo piano acquisti reale.
- Priorita' 4 chiusa (2026-08-08): rischio/rendimento SATOR consolidato su
  `core/domain/risk.py` (funzioni canoniche gia' esistenti, riusate) e sulla
  finestra rolling configurabile invece della vecchia finestra fissa a 252
  giorni; `storico_sufficiente` ora segue la stessa finestra. Nessuna formula
  duplicata rimasta fuori da `core/`.
- Aggiunta Mappa strumenti (Progetto C del libro, `docs/progetti/ROADMAP_AI_FINANZA_LIBRO.md`)
  in Pianificazione: scatter rischio/rendimento su posseduti+candidati SATOR,
  rilevazione ridondanza per soglia di correlazione (0,85). Impatto misurato
  sul render Pianificazione: +250/320 ms circa su una base di ~0,5 s (vedi
  riga Pianificazione in "Ultima lettura performance", da aggiornare al
  prossimo log completo).
- Chiuso Progetto D (`docs/progetti/ROADMAP_AI_FINANZA_LIBRO.md`), 2026-08-09:
  sezione "Perche' questo voto" in Pianificazione, sotto la Mappa strumenti —
  per ogni strumento della classifica SATOR, contributo dei 5 fattori al voto
  (grafico a barre impilate `pianificazione_sator_explain` + tabella di
  sintesi), formule riusate da `core/services/sator.py`
  (`PESI_DIMENSIONI`/`NOME_FATTORE`) via il nuovo modulo
  `core/services/sator_explain.py`, nessun nuovo calcolo di punteggio.
  `build_instrument_map` ora accetta un `precomputed_result` opzionale cosi'
  Mappa strumenti e la nuova sezione condividono la stessa chiamata a
  `run_sator_analysis` invece di ricalcolarla due volte. Impatto misurato sul
  blocco SATOR di Pianificazione con dati reali (mediana di 5 run): da 157,7 ms
  (solo Mappa strumenti, comportamento pre-Task) a 204,5 ms (Mappa strumenti +
  Perche' questo voto), delta di mediana +46,9 ms — di cui ~23 ms per la
  costruzione del grafico e ~1 ms per `build_sator_explanations` (puro Python
  su una DataFrame gia' in memoria), il resto e' variabilita' di
  `run_sator_analysis` fra le due misurazioni.
  La review finale sul branch (che ha costruito ed ispezionato la figura
  renderizzata, non solo il codice) ha trovato e corretto tre problemi
  reali invisibili alla sola review per-task: l'asse X del grafico veniva
  tagliato a circa 1/3 della lunghezza vera (la protezione automatica sulle
  barre non e' stack-aware), l'asse Y mostrava il voto piu' alto in fondo
  invece che in cima (un passaggio della pipeline di rendering sovrascriveva
  l'ordine impostato dal builder), e i contributi usavano sempre i pesi di
  default invece di quelli che l'utente puo' personalizzare dall'expander
  "Pesi del punteggio SATOR" — ora `build_sator_explanations` riceve i pesi
  realmente usati da SATOR (`sator_result["sator_settings"]["score_weights"]`).
  Riformulata anche la frase di sintesi ("il fattore che porta meno punti al
  voto" invece di "il punto piu' debole", per non far sembrare un giudizio
  sullo strumento quello che e' solo un effetto dei pesi).
- Chiuso Progetto A (`docs/progetti/ROADMAP_AI_FINANZA_LIBRO.md`), 2026-08-09:
  sezione "Frontiera rischio/rendimento" in Pianificazione, sotto Mappa
  strumenti — confronto simulato tra portafoglio attuale, proposta SATOR
  (quote suggerite al budget corrente) e una modifica manuale via slider,
  con minimo-rischio e miglior Sharpe individuati su una nuvola di
  portafogli casuali long-only. Deliberatamente senza ottimizzatore (niente
  `scipy`, mai in uso nel repo) e senza alcuna stima di rendimento "atteso":
  solo rendimento storico annualizzato (orizzonte 6/12/24/36 mesi
  selezionabile) sullo stesso `returns_frame` gia' calcolato da
  `run_sator_analysis`, riusato senza ricalcolo — stesso principio "storico,
  non previsione" gia' applicato al resto di SATOR. Nuovo modulo
  `core/services/sator_frontier.py`.
  La review finale sull'intero branch ha trovato e corretto tre problemi
  reali, tutti nella stessa direzione (evitare la "falsa precisione" che la
  roadmap segnala come rischio esplicito di questo progetto): (1) uno
  strumento posseduto con storico troppo corto per l'orizzonte scelto
  spariva dal marker "Attuale" senza comparire nell'avviso "esclusi per
  storico insufficiente" — i due filtri (soglia larga per l'universo,
  soglia stretta per il calcolo storico/covarianza) non erano allineati;
  (2) con un vincolo di concentrazione stretto rispetto al numero di
  strumenti simulati, la nuvola casuale poteva degenerare in gran parte in
  punti duplicati (misurato: solo il 50% di punti distinti con 3 strumenti
  e il cap di default 0,35), disegnando comunque i marker "Min-rischio" e
  "Miglior Sharpe" come se la simulazione fosse informativa — ora un nuovo
  campo `cloud_degenerate` avvisa esplicitamente l'utente in questo caso;
  (3) mancava il test di guardia "mai parole previsive" gia' presente per
  la Mappa strumenti gemella, aggiunto per allineamento.
  Con questa chiusura, tutti e 4 i progetti pianificati del libro (A, B, C,
  D) sono completati; il quinto (storico decisionale ex-post) resta
  archiviato per scelta esplicita, non urgente — vedi Priorita' 7 in
  sezione 5.
- Allocazione budget SATOR per deficit di bucket (2026-08-16), opt-in.
  Piano a 11 task eseguito con subagent-driven-development, spec e piano
  completi in
  `docs/superpowers/specs/2026-08-15-sator-bucket-eligibility-design.md`
  e `docs/superpowers/plans/2026-08-15-sator-bucket-eligibility.md`.
  Bug reale trovato e misurato sul portafoglio dell'utente: con Core al
  18,98% (target 50%), Difensivo al 78,58% (target 40%, dominato da BTP
  pari al 76,1% del portafoglio) e Satellite al 2,44% (target 10%), a
  budget €1.500 l'allocazione greedy-globale gia' esistente di SATOR
  escludeva correttamente Difensivo (€0, oltre la banda massima) ma
  assegnava piu' soldi a Satellite (€923, deficit ~€5.031) che a Core
  (€570, deficit ~€20.765 — 4 volte maggiore): il motore sceglie il
  candidato con il punteggio migliore su tutto l'universo,
  indipendentemente da quale bucket abbia piu' bisogno di capitale.
  Nuovo master switch `bucket_first_allocation`
  (`core/services/sator.py:153`, spento di default — a flag spento il
  comportamento resta identico a prima, verificato per tracciamento del
  branch condizionale), con `band_tolerance_pp` (riga 151, bande min/max
  reali attorno al target di bucket, prima c'era solo il target puntuale)
  e `deficit_pac_only` (riga 152, esclude BTP/GOV dal calcolo dei pesi di
  bucket usato per lo split del deficit); UI in
  `ui/pages/pianificazione.py:335`, expander "Allocazione budget per
  bucket (avanzato)" dentro il form esistente "Obiettivo di portafoglio".
  Funzioni chiave: `_compute_bucket_bands` (riga 1038),
  `_compute_bucket_weights` esteso con `exclude_tickers` (riga 1057,
  retrocompatibile), `_non_pac_held_tickers` (riga 1090, riusa
  `infer_sator_metadata`/`pac_enabled`), `_compute_bucket_deficits`
  (riga 1108, formula Vpost/TargetValue/Deficit standard + blocco hard
  dei bucket oltre banda), `_suggested_quotes_by_bucket` (riga 1415,
  split del budget proporzionale al deficit, poi chiama per bucket la
  primitiva invariata `_suggested_quotes`). Decisione dell'utente a
  meta' implementazione: nessun cap predeterminato di righe per bucket
  (respinte sia la formula del piano, 1 riga/bucket, sia le 2 riga/bucket
  del design doc iniziale) — il conteggio resta governato solo da
  sotto-budget e punteggio di decisione (soglia >=0,50); wiring finale
  `max_lines_per_bucket=len(work)`. `build_sator_matrix_frame` (riga 823)
  riceve due parametri opzionali `data`/`settings` (default None,
  percorso invariato se assenti); collegata nei due call site reali
  `core/services/sator_frontier.py:328` e `ui/form_server/sator.py:1766`.
  Verifica end-to-end su dati reali, budget €1.500: flag spento -> Core
  €570/Satellite €923 (bug invariato); flag acceso -> Core
  €1.128/Satellite €292 (inversione corretta, vicino allo split teorico
  80/20 implicato dai deficit reali).
  Bug critico trovato dalla review finale whole-branch (dopo l'11° task,
  prima del merge) e corretto in un fix wave dedicato:
  `_compute_bucket_weights` rinormalizzava i pesi restanti quando
  `exclude_tickers` non era vuoto, dividendo per il totale ridotto. Con
  `deficit_pac_only` e `bucket_first_allocation` entrambi attivi,
  escludere i BTP gonfiava il peso di Core dal 18,98% reale a un 79,41%
  rinormalizzato — sopra banda massima, quindi bloccato — dirottando
  l'intero budget su Difensivo, gia' il bucket piu' sovrappesato: l'esatto
  opposto dello scopo del fix. Utente consultato direttamente, confermato
  verbatim: "voglio che se dico escludi dal calcolo i BTP questi non
  vengano considerati". Fix: rimossa ogni rinormalizzazione, somma pesi
  grezzi senza divisione in entrambi i casi (`exclude_tickers` vuoto o
  no). Aggiunti nello stesso fix wave: logging (`logger.info`/
  `logger.warning`, prima assente in questo file) per i casi "nessun
  deficit positivo" e "colonne mancanti col flag acceso", rimozione di un
  controllo morto (`"bucket_weight" in work.columns`, mai letto nel
  branch) e del cap residuo `max_lines_per_bucket=2` (ora `None` ->
  `len(ranking_df)`). Verificato con test end-to-end reale (entrambi i
  flag attivi, Core non piu' bloccato) e test sintetico (bucket
  interamente escluso -> peso 0.0, non rinormalizzato); scoped re-review
  dedicata su commit 0c28627..fb03288: tutti i finding ADDRESSED, nessuna
  nuova regressione.

### Cruscotti / Analitica

- Aggiunta Simulazione Monte Carlo del portafoglio posseduto (Progetto B del
  libro, `docs/progetti/ROADMAP_AI_FINANZA_LIBRO.md`), 2026-08-09: bootstrap
  storico dei rendimenti semplici pesati (non gaussiano), ventaglio
  5-95/25-75 percentile a 6/12/24 mesi, tabella con mediana/P5/P95/probabilita'
  di perdita/VaR/CVaR. Stesso pattern di cache a grana fine gia' in uso per
  gli altri grafici di `_build_analitica_bundle` (`ui/dashboard_bundles.py`),
  nessuna modifica al comportamento preesistente.
  - Estratta `combine_weighted_returns` (`core/domain/returns.py`) come
    formula canonica unica per la combinazione pesata rendimenti->portafoglio,
    riusata da SATOR (`_build_portfolio_return_series`, ora un wrapper) e dal
    Monte Carlo — evitava una duplicazione della stessa formula.
  - Scelta metodologica rilevante: il pool di rendimenti su cui si campiona
    e' ristretto alla finestra comune fra tutti gli strumenti posseduti
    pesati (`dropna` sui giorni in cui anche un solo strumento non ha ancora
    storico), non all'unione con giorni riempiti a zero — trovato in review
    finale come bug Critical (il riempimento a zero diluiva artificialmente
    la volatilita' simulata) e corretto prima del merge.
  - Impatto prestazionale misurato su `_build_analitica_bundle`: +129/166 ms
    (media ~145 ms) su piu' round puliti con metodologia a worktree isolato;
    un residuo di ~70-100 ms fra il costo isolato del solo blocco nuovo
    (~60 ms) e il delta end-to-end resta senza spiegazione certa (probabile
    overhead di hashing/serializzazione della cache), dichiarato qui come
    aperto invece di essere richiuso senza prova.
- Modificato (2026-08-13) il grafico "Rate di acquisto per strumento" in
  Cruscotti/Flussi e Acquisti: asse Y sul controvalore posseduto per
  strumento invece del numero di acquisti (che resta come etichetta sulle
  barre e nell'hover). Fatto affiancando la nuova versione a quella storica
  per un confronto diretto prima di decidere, come richiesto esplicitamente
  dall'utente; dopo valutazione la versione storica
  (`build_purchase_installments_chart`) e' stata rimossa.

### Report

- Creato archivio report Summary in `data/reports/summary/`.
- Salvati HTML/JSON e manifest locale.
- Aggiunto storico in Summary, ripristino nei download correnti ed eliminazione.

### Tema e UI

- Inserito logo Sestante finale nell'header.
- Rifinita barra iniziale.
- Uniformati diversi box, warning, log rendering e bottoni copia/scarica.
- Centralizzato il richiamo a icone/categorie/bucket dove erano state introdotte
  soluzioni visive incoerenti.

### Robustezza chart builder

- Chiuso (2026-08-11) l'audit difensivo dei chart builder, Priorita' 8.1
  ("Maturazione 5.0"): censite tutte le 51 funzioni `build_*_chart` sotto
  `ui/charts/` (12 file), corrette le 24 prive di guardia o con guardia
  rotta/incoerente su 9 file (`overview.py` 1, `home.py` 7, `analitica.py`
  6, `andamento.py` 2, `analisi.py` 2, `quotazioni.py` 3, `operazioni.py`
  1, `confronto.py` 1, `pianificazione.py` 1) — `cruscotti.py`,
  `accumuli.py` e `benchmark.py` gia' interamente a posto, nessuna
  modifica. Metodo puramente additivo: ogni fix e' un controllo `None`/vuoto
  aggiunto in testa alla funzione, mai una riscrittura; pattern canonico
  `empty_chart(chart_id)` (helper gia' esistente in `ui/charts/runtime.py`,
  prima usato in un solo file su dodici), con due eccezioni deliberate
  (`quotazioni.py` usa `apply_settings_base100` per lo stile base-100 anche
  a vuoto; `pianificazione.py::build_objective_mix_chart` usa `x or {}`
  invece di un early-return, perche' produce comunque un grafico valido a
  barre zero, piu' informativo di un placeholder vuoto).
  Due funzioni in `home.py` avevano un contratto di ritorno da preservare,
  verificato sui chiamanti reali prima di toccarle:
  `build_category_allocation_pie_chart` resta a `None` sul path vuoto (il
  suo unico chiamante lo gestisce gia' esplicitamente); `build_portfolio_pl_category_chart`
  e' passata da un `go.Figure()` nudo a `empty_chart(...)` (sicuro, il suo
  unico chiamante avvolge gia' il risultato in `apply_settings`).
  La review finale sull'intero branch ha cercato attivamente un rischio di
  crash residuo o nuovo nelle 24 funzioni corrette e non l'ha trovato;
  "pronto per il merge" senza riserve. Follow-up minori non urgenti (vedi
  `TODO_5.0.md`, sezione "Maturazione 5.0"): unificare la selezione
  duplicata del `chart_id` in due funzioni di `home.py`; quando si fara' la
  deduplicazione gia' nota di `build_risk_contribution_chart`
  (`analisi.py`/`analitica.py`, entrambe guardate separatamente in questo
  audit), la copia in `analisi.py` va rimossa (codice morto, nessun
  chiamante in produzione) non fusa; copertura test asimmetrica sul ramo
  "vuoto ma non `None`" di ~20 guardie.

### Consolidamento formule rendimento e Confronto strumenti (2026-08-14)

Piano a 14 task eseguito con subagent-driven-development, spec e piano
completi in
`docs/superpowers/specs/2026-08-14-pianificazione-confronto-strumenti-design.md`
e `docs/superpowers/plans/2026-08-14-pianificazione-confronto-strumenti.md`.

- Fase A (7 task) — consolidamento: un audit di `ui/charts/*.py` e
  `ui/pages/*.py` ha trovato 8 siti (non 6 come stimato all'avvio; l'ottavo,
  `core/services/sator.py::_rolling_return`, e' emerso a meta' lavoro) che
  reimplementavano "rendimento rispetto al primo valore"
  (`ultimo/primo - 1`) fuori da `core/`. Nuova
  `core.domain.returns.normalize_to_first(prices, *, as_pct=True)`
  (`core/domain/returns.py:411`) come primitiva condivisa, usata da
  `ui/charts/analisi.py:109`, `ui/pages/cruscotti.py:962` e
  `core/services/sator.py::_compute_all_metrics_batch` (riga 1501); gli
  altri siti (incl. l'ottavo) si sono accorpati sulla gia' esistente
  `core.domain.returns.simple_period_return` (`core/domain/returns.py:211`):
  `core/services/sator.py::_rolling_return` (riga 1454),
  `ui/pages/mercati.py::_period_return`/`_ytd_return`. Spostata anche la
  stima fiscale a scadenza BTP in
  `core/domain/calendar.py::estimate_maturity_tax` (`core/domain/calendar.py:287`),
  rimossa la duplicazione privata (`_stima_imposte_scadenza`/
  `_ALIQUOTA_BTP`) da `ui/charts/calendario_btp.py`.
  La review del task 5 ha trovato e corretto una rottura di parity: il
  codice originale di `_rolling_return` proteggeva anche i valori di
  partenza negativi (`inizio > 0`), la funzione condivisa proteggeva solo
  lo zero (`== 0`) — aggiunta una guardia esplicita `inizio <= 0` prima di
  delegare.
- Fase B (5 task) — nuova sezione "Confronto strumenti" in Pianificazione,
  subito dopo Mappa strumenti: sposta e ricostruisce la vecchia
  "Performance normalizzata" di Cruscotti/Benchmark (prima on-demand dietro
  un pulsante), ora sempre viva e aggiornata a ogni rerun — nessun pulsante
  "costruisci", scelta esplicita dell'utente ("confronto facile ed
  immediato"). Multiselect strumenti (default: posseduti), periodo,
  opzione "origini allineate" e overlay opzionale di un singolo benchmark
  (via `core.benchmark_registry` gia' esistente, mostrato/usabile solo con
  esattamente uno strumento selezionato) —
  `ui/pages/pianificazione.py::_render_instrument_comparison_section`
  (riga 674), grafico in
  `ui/charts/pianificazione.py::build_instrument_comparison_chart` (riga
  589, linee colorate piene per strumento, tratteggiata grigia per il
  benchmark), logica dati in nuovo `core/services/instrument_comparison.py`
  (`ComparisonSeries` riga 26, `resolve_period_start_date` riga 44,
  `get_all_historical_tickers` riga 60, `build_comparison_frame` riga 92).
  Rimossi da `ui/pages/cruscotti_benchmark.py`/`ui/charts/benchmark.py` la
  vecchia `_render_normalized_performance_section`,
  `build_normalized_performance_chart`, `get_all_historical_tickers` e
  `resolve_period_start_date` ora superate; il resto di Cruscotti/Benchmark
  (KPI, grafico portafoglio-vs-benchmark, matrice di correlazione,
  scatter di coerenza) resta invariato, deliberatamente fuori perimetro.
  Reso pubblico (rinominato, nessuna modifica di logica al momento del
  rename) `core/services/benchmark.py::instrument_price_history`/
  `benchmark_price_history` (righe 256/270, prima
  `_instrument_price_history`/`_benchmark_price_history`) per riuso dal
  nuovo modulo.
  Due bug di performance reali trovati e corretti dopo l'implementazione,
  misurati su dati reali (16 strumenti posseduti, 976 date di storico):
  (1) `instrument_price_history`/`benchmark_price_history` (funzioni
  preesistenti, non create da questo lavoro) avevano un anti-pattern
  `pd.to_datetime()`/`pd.to_numeric()` riga per riga, prima nascosto dietro
  la cache on-demand di Cruscotti e ora esposto dalla nuova sezione sempre
  viva — vettorizzato, ~121x piu' veloce (5,1 s -> 0,04 s per 16
  strumenti); (2) `build_instrument_comparison_chart` aveva lo stesso
  anti-pattern nel proprio codice nuovo (`[pd.to_datetime(d) for d in
  s.dates]` in loop) — sostituito con un'unica chiamata
  `pd.to_datetime(s.dates)`, ~118x piu' veloce (5,5 s -> 0,05 s). Risultato
  end-to-end: l'intera sezione (dati + grafico) costa ora circa 253 ms a
  rerun per la vista di default a 16 strumenti, contro un costo iniziale
  di circa 9,6 s — numeri reali prima/dopo come richiesto dalla regola di
  progetto sulle modifiche di performance.
- Fase C (1 task) — nuovo `tools/finance_formula_audit.py`, sul modello di
  `tools/cache_surface_audit.py`: scansione statica ripetibile di `ui/` per
  pattern di formule finanziarie (normalizzazione rendimento,
  statistiche/rischio, aliquote fiscali) non instradate da `core/`. Stessa
  limitazione nota del tool gemello: il filtro dei path esclude qualunque
  segmento con prefisso punto, quindi non trova file se eseguito da dentro
  un checkout annidato in `.worktrees/` (funziona correttamente da un
  checkout normale).
- Fuori piano, necessario per chiudere pulito: le fasi A e B avevano rotto
  4 file di test LOCALI preesistenti (`tests/` e' interamente gitignored,
  quindi invisibili in qualunque diff) che referenziavano ancora i nomi
  rimossi. Sistemati: eliminato
  `tests/test_normalized_performance_chart.py` (superato del tutto),
  aggiornati `tests/test_resto_volume_colori.py`,
  `tests/test_tax_rate_gov_consolidation.py`,
  `tests/test_cruscotti_uncached_tabs_perf_fix.py`. Suite locale completa
  verificata pulita dopo il fix (unico fallimento residuo: un artefatto
  path `.worktrees/` nel test proprio di `tools/cache_surface_audit.py`,
  preesistente, fuori perimetro, irrilevante fuori da questo worktree).
- Non fa parte di questo piano ma coincide temporalmente: durante
  l'inserimento manuale di IWQU.MI, XDEQ.MI, FAM-PU6 e' emerso e corretto
  un bug di firma cache separato — `core/cache_signatures.py::_normalized_instrument_signature_payload`
  non includeva il campo `natura`, quindi correggere l'etichetta natura di
  uno strumento non invalidava gli artefatti UI in cache. Gia' committato
  su `main` (`87f6ae9`), prima dell'apertura di questo branch.

### Revisione del modello di classificazione e allocazione — sotto-progetti 1-5 e correzioni sparse (2026-08-17/21)

Iniziativa separata dalla governance cache sopra, partita da un documento di
revisione esterno (`Revisione del modello di classificazione e allocazione –
Portfolio Intelligence.md`, root del repo — **eliminato su richiesta
dell'utente il 2026-08-21**, dopo che i sotto-progetti sotto erano stati
completati) con un ordine di priorita' a 11 voci in sezione 21. Dettaglio
completo di ogni commit in `CHANGELOG.md` (voci in cima al file); qui solo il
riepilogo di stato. Le spec/piani restano in `docs/superpowers/specs/` e
`docs/superpowers/plans/` (gitignored, locali).

- **Sotto-progetto 1 (voce 1, chiuso 2026-08-19)** — motore di
  classificazione e arricchimento unificato: primo editor UI per
  `manual_overrides.sator.{role,benchmark_code,benchmark_label,user_edited,
  benchmark_user_edited}`, `resolve_instrument_role`/`resolve_instrument_nature`
  come punti di accesso pubblici unici, `get_nature_visual` (icone keyed su
  nature SATOR invece di etichetta libera), 3 nuove nature (criptovalute,
  difesa/sicurezza, azionario paese singolo). Bug critico chiuso in review:
  l'editor scriveva un override ad ogni submit anche senza modifiche reali,
  rischiando di riattivare chiavi legacy dormienti — ora scrittura
  solo-se-cambiato.
- **Sotto-progetto 2 (voce 2, chiuso 2026-08-20)** — appartenenza percentuale
  multipla ai bucket: `resolve_instrument_bucket_exposure`/
  `compute_instrument_bucket_exposures`, editor "Esposizione tra bucket" in
  Classificazione. Il motore SATOR vero resta bucket-singolo per vincolo di
  scopo esplicito (flag `use_fractional_exposure`, default `False`, i 4
  chiamanti del motore restano invariati) — solo la vista "mix corrente" e i
  grafici a ciambella vedono la frazione.
- **Sotto-progetto 3 (voci 3+4, chiuso 2026-08-21)** — target strategico e
  posizione NO_SELL per strumento: `resolve_instrument_no_sell`,
  `compute_instrument_operational_status` (stato in_target/sottopeso/
  sovrappeso/sovrappeso_no_sell per strumento), pagina "Quote & impostazioni"
  ristrutturata a 3 sottoschede (Target & Stato, Ruolo & Benchmark,
  Esposizione Bucket). Eseguito con `subagent-driven-development`: 7 task,
  un bug critico di perdita dati trovato e corretto in corso d'opera (NO_SELL
  scritto su ticker non visibili in pagina), review finale sull'intero branch
  con un secondo bug della stessa classe trovato e corretto prima del merge
  (arrotondamento a intero della tabella Esposizione Bucket).
- **Sotto-progetto 4 (voci 6-9, chiuso 2026-08-21)** — esposizione
  frazionata reale nel motore SATOR: `SatorContext.instrument_bucket_exposures`,
  eleggibilita' generalizzata (uno strumento diviso resta candidabile se
  almeno un bucket a cui appartiene e' valido), `_score_fit` pesa la
  penalita' di sovrappeso-bucket sulla frazione di esposizione, deficit di
  bucket frazionato quando `bucket_first_allocation` e' attivo. Eseguito con
  `subagent-driven-development`: 4 task, un bug Critical trovato dalla
  review finale (la colonna `_bucket_exposure` veniva creata DOPO essere
  stata letta da `_score_fit`, rendendo l'intero task inerte in produzione
  — errore di ordinamento nella spec/piano stessi, non
  dell'implementatore, corretto con verifica empirica e test di
  integrazione dedicato) piu' 2 Important (un terzo punto di chiamata a
  `_compute_bucket_weights` mai reso frazionario, un docstring gemello
  rimasto falso). Voce 10 (Purchase Optimizer) esplicitamente rimandata a
  un sotto-progetto 5 futuro — vedi sotto.
- **Documento sorgente recuperato (2026-08-21)**: il file originale era
  stato eliminato dalla root del repo su richiesta esplicita dell'utente,
  ma il suo contenuto integrale (22 sezioni) era ancora presente nel
  transcript di sessione (era stato letto per intero all'inizio della
  conversazione) — recuperato e salvato in
  `docs/portfolio-intelligence/Revisione del modello di classificazione e
  allocazione – Portfolio Intelligence.md` (gitignored, come tutto
  `docs/`). Le voci 5 e 11, di cui si era temporaneamente perso il
  contenuto, sono quindi note di nuovo:
  - **Voce 5** — "Rendere configurabili i limiti di concentrazione" (sezioni
    11-12 del documento): i limiti di concentrazione per natura/tema
    (oggi `CAP_MORBIDO_NATURA`, hardcoded in `core/services/sator.py`)
    dovrebbero entrare nella Portfolio Policy configurabile, e il motore
    dovrebbe verificarli sulla **somma delle esposizioni effettive**
    (non sulla sola categoria nominale dello strumento) con una semantica
    esplicita per tipo di limite (`DIRECT_EXPOSURE_LIMIT` /
    `EFFECTIVE_EXPOSURE_LIMIT` / `THEMATIC_OVERWEIGHT_LIMIT`) — per
    distinguere es. la tecnologia strutturale gia' contenuta in un ETF
    core globale dalla tecnologia aggiuntiva presa con ETF settoriali
    dedicati.
  - **Voce 11** — "Aggiungere look-through automatico in una fase
    successiva" (sezione 6, "Livello 2"): il sotto-progetto 2
    (`bucket_exposure`) ha gia' costruito il "Livello 1" descritto dal
    documento originale (mapping manuale/configurabile dell'esposizione
    per strumento). Il "Livello 2" e' calcolare automaticamente, quando
    disponibili dati affidabili sulla composizione reale di fondi/ETF, la
    stessa scomposizione (azioni/obbligazioni/settori/paesi/valute/duration)
    senza inserimento manuale — con possibilita' di verifica/sovrascrittura
    manuale. Esplicitamente l'ultima voce della sequenza originale, non
    urgente.
- **Voci 6-10** (nomi confermati dal documento recuperato, sezione 21
  "Priorita' di sviluppo": "Calcolare l'esposizione effettiva", "Adeguare
  Strategic Analyzer", "Adeguare Eligibility Engine", "Adeguare
  Rebalancing Engine", "Adeguare Purchase Optimizer"): **tutte chiuse**
  (6-9 dal sotto-progetto 4, 10 dal sotto-progetto 5 — sotto). Resta solo
  la voce 11 (look-through automatico), esplicitamente rimandata dal
  documento sorgente stesso, non urgente.
- **Sotto-progetto 5 / "10bis" (voce 10 + 5 problemi UI/integrazione
  segnalati dall'utente, chiuso 2026-08-21)** — Purchase Optimizer con
  esposizione frazionata reale: `_dominant_bucket` fa competere uno
  strumento diviso tra bucket nel sotto-budget di quello con deficit
  maggiore (non solo il suo bucket primario), `_compute_marginal_purchase_metrics`
  pesa il miglioramento verso il target sulla somma pesata per bucket
  (mai una media, stesso principio del sotto-progetto 4), i nuovi
  parametri (`bucket_weights`/`bucket_targets`) sono filati fino alla
  colonna "Prio" mostrata in tabella — trovato in fase di piano che quel
  ricalcolo non era mai stato scoped al percorso pesato. Esteso su
  richiesta esplicita dell'utente ("un unico intervento 10bis completo")
  con 4 problemi reali trovati rivedendo il lavoro dei sotto-progetti
  1-4: coerenza grafica tra le 3 pagine del form-server (`sator.py`,
  `quote_interne.py`, `scheda_strumento.py` ricostruivano ciascuna il
  proprio CSS invece di riusare `shell.CSS` — un bug di colore reale
  incluso, `.alert-warn` rosso invece di ambra); NO_SELL collegato
  davvero al motore SATOR (`_score_universe` ora esclude dal ranking un
  nuovo acquisto, prima il flag influenzava solo un'etichetta UI); valore
  automatico mostrato accanto a ruolo/benchmark/esposizione bucket quando
  forzati manualmente; selettore benchmark da catalogo esistente
  (`<datalist>`, campo resta testo libero) + log su fetch storico vuoto.
  Eseguito con `subagent-driven-development`, 9 task + 1 ondata di fix
  dalla review finale (sul modello piu' capace, dispatchata dopo tutti i
  9 task): trovati e corretti un fallback asimmetrico su
  `_bucket_exposure` (il ramo pesato azzerava le metriche invece di
  degradare al bucket primario come gia' fa `_score_fit` — non
  raggiungibile in produzione oggi, ma incoerenza interna reale) e un
  `master_entry` mancante nel calcolo del valore benchmark "automatico"
  (poteva mostrare una forzatura inesistente). La review finale ha anche
  sollevato una tensione di design non risolta qui, lasciata a decisione
  esplicita dell'utente: NO_SELL esclude lo strumento dall'**intero**
  ranking SATOR (quindi anche dalla frontiera rischio/rendimento e dalla
  mappa strumenti), non solo dai nuovi acquisti — fedele al testo della
  spec originale, ma in tensione con l'uso tipico (una posizione storica
  che dovrebbe restare visibile nel portafoglio attuale). Nessun dato
  reale usa oggi NO_SELL, quindi il rischio e' dormiente.
- **Correzioni sparse non collegate alla revisione** (stessa finestra
  temporale, bug segnalati dall'uso reale): quantita' BTP dagli eventi reali
  invece del campo statico, Timeline BTP ordinata per scadenza, due bug
  reali di P/L fantasma da posizione non quotata e da Versamento
  automatico non sincronizzato con l'acquisto che finanzia (entrambi
  -18.312€ su casi reali), firma dati strumento estesa ai campi
  cedola/scadenza, Monte Carlo che non blocca piu' l'intera simulazione per
  un solo strumento con storico insufficiente, dimensione dinamica della
  matrice di correlazione, colore categoria e indicatore portafoglio nella
  tabella qualita' dati. Dettaglio in `CHANGELOG.md`.

---

## 4. Ultima lettura performance

Ultimo log analizzato il 2026-08-03 00:49:

| Pagina | Tempo circa | Stato |
|---|---:|---|
| Cruscotti | 4,9 s | principale collo residuo, render UI full-tabs |
| Quotazioni | 1,9 s | cache L3 funzionante, tuning pagina da fare dopo |
| Portafoglio | 1,3 s | accettabile, tuning pagina da fare dopo |
| Dati | 0,5 s | molto migliorata |
| Pianificazione | 0,5 s | accettabile |
| Mercati | 0,02 s | correttamente opzionale |
| Totale | 11,5 s | firma invariata, artefatti letti da cache, render completo ancora pesante |

Lettura:

- non risultano rete o yfinance nel render ordinario;
- non risultano dirty flag;
- `profiling_cache_condition=signature_unchanged` e `signature_diff: none`;
- `page_cache_runtime=process_entries=14; session_entries=14`;
- la separazione benchmark/mercati dalla firma semantica globale ha funzionato;
- `source=disk: 22`, `source=build: 0`;
- raw-pickle Cruscotti e' confermato nel log: `codec=pickle` su
  `category_dashboard_bundles` e `analitica_bundle`;
- Cruscotti resta il collo principale e pesa circa 5 s;
- il costo residuo e' soprattutto costruzione/render UI full-tabs, con
  Cruscotti come area piu' pesante;
- Mercati non e' il problema;
- il pilot L4 non deve essere riattivato nel runtime ordinario.

La firma semantica globale non include i benchmark/live market: quei dati hanno
cache e refresh dedicati. Il diff profiling puo' continuare a mostrarli come
informazione diagnostica separata.

---

## 5. Cosa resta da fare

### Priorita 1 - Chiusura governo cache

La cache unica applicativa e' chiusa come governance: registry centrale,
page-cache L3, provider runtime registrati, eccezioni Streamlit documentate e
test anti-regressione. Non significa che ogni pagina sia gia' al minimo teorico
di render: significa che non devono piu' esistere cache nuove fuori contratto.

Aggiornamento 2026-08-17: quasi tutti gli artefatti sono stati promossi da
`pilot` a `registered_provider` (26 su 27, vedi dettaglio in "Cache e
performance" sopra) — resta solo `mercati.live_snapshot`, bloccato
dall'osservazione ancora aperta di Priorita' 6.

Da mantenere:

1. eseguire `tools/cache_surface_audit.py` quando si introduce una nuova cache;
2. mantenere a zero i `legacy_provider` e gli artefatti `planned`;
3. usare `core.page_cache` per artefatti pagina e `core.runtime_cache` per
   cache runtime in memoria;
4. lasciare `@st.cache_resource` solo per singleton runtime documentati;
5. vietare nuove cache locali di pagina non registrate.

### Priorita 2 - Artefatti ad azione esplicita

Chiuso come cache governance. Questi lavori sono generati da pulsante ma restano
dentro il contratto unico e non devono causare rerun globali pesanti:

- Summary report payload;
- Confronto comparison report;
- Mercati live snapshot;
- Cruscotti Benchmark frozen analysis;
- Cruscotti Accumuli frozen analysis.

### Priorita 3 - Reportistica

- Completare archivio report step 2: rigenerare un report usando le opzioni
  salvate nella fotografia/manifest, senza reimpostare manualmente i checkbox.

### Priorita 4 - Dati e metriche quantitative comuni

Chiusa (2026-08-08) per la parte SATOR: vedi "Pianificazione e SATOR" in
sezione 3. Resta aperta la migrazione di Cruscotti/Quotazioni verso lo stesso
servizio comune, se emergera' un bisogno concreto (non forzarla adesso).

- ~~Consolidare il dataset rischio/rendimento strumenti in un servizio unico~~ (fatto per SATOR).
- Migrare gradualmente Cruscotti, Quotazioni verso quel servizio (non ancora fatto).
- Evitare formule duplicate nelle pagine.
- Verificare con test e confronto sui numeri reali.

### Priorita 5 - SATOR, da riprendere con il prossimo piano acquisti

Da non forzare adesso. Quando sara' il momento:

- validare se i giudizi SATOR aiutano davvero la decisione mensile;
- rendere piu' chiara la distanza tra proposta automatica e scelta manuale;
- migliorare explainability e confronto tra fotografie;
- valutare frontiera efficiente e Monte Carlo solo dopo aver consolidato le
  metriche comuni.

### Priorita 6 - Mercati, osservazione per qualche giorno

- Tenere la pagina Mercati in osservazione.
- Verificare se dati live/storico e semaforo freschezza sono affidabili.
- Non trasformarla in costo base dell'app.

### Priorita 7 - Progetti dal libro

Il progetto AI/finanza resta separato in
`docs/progetti/ROADMAP_AI_FINANZA_LIBRO.md`.

Ordine consigliato originale, non urgente (l'ordine effettivo seguito e'
stato C, poi B, poi D, poi A — scelto di volta in volta dall'utente in corso
d'opera, non una revisione della priorita'):

1. SATOR Frontier — fatto (2026-08-09), vedi "Pianificazione e SATOR" in
   sezione 3.
2. Monte Carlo Portafoglio — fatto (2026-08-09), vedi "Cruscotti / Analitica"
   in sezione 3.
3. Mappa AI strumenti / clustering — fatto, vedi "Pianificazione e SATOR" in
   sezione 3.
4. Explainability SATOR — fatto (2026-08-09), vedi "Pianificazione e SATOR"
   in sezione 3.
5. Storico decisionale con valutazione ex-post — archiviato (2026-08-11) per
   scelta esplicita dell'utente: non urgente, non prioritario adesso. La
   parte fotografie/confronto gia' in Pianificazione copre gia' un pezzo di
   questo bisogno, quindi non e' un vuoto totale.

Con questo, Priorita' 7 e' di fatto esaurita: tutti i progetti pianificati
sono chiusi o archiviati per scelta esplicita. Non riaprire il punto 5 senza
una richiesta esplicita.

### Priorita 9 - Revisione modello di classificazione e allocazione, voce residua

Vedi "Revisione del modello di classificazione e allocazione — sotto-progetti
1-5" in sezione 3 per cosa e' gia' chiuso (voci 1-4 e 6-10 dell'ordine di
priorita' originale — la voce 10, Purchase Optimizer, e' stata chiusa dal
sotto-progetto 5/"10bis" il 2026-08-21). Documento sorgente eliminato dalla
root il 2026-08-21 (richiesta esplicita dell'utente) ma **recuperato lo
stesso giorno** dal transcript di sessione (era stato letto per intero
all'inizio della conversazione) e salvato in
`docs/portfolio-intelligence/Revisione del modello di classificazione e
allocazione – Portfolio Intelligence.md` (gitignored) — tutte le 22
sezioni sono di nuovo consultabili per intero.

1. **Voce 11 — look-through automatico**, unica voce residua dell'intera
   sequenza 1-11, esplicitamente "fase successiva" nel documento originale
   (sezione 6, "Livello 2"): calcolo automatico della composizione reale
   di fondi/ETF (azioni/obbligazioni/settori/paesi/valute/duration) quando
   saranno disponibili dati affidabili, sopra il "Livello 1" manuale gia'
   costruito dal sotto-progetto 2 (`bucket_exposure`). Non urgente per
   esplicita indicazione del documento sorgente — dipende da una fonte
   dati esterna non ancora identificata.
2. **Decisione aperta segnalata dalla review finale del sotto-progetto 5**
   (non e' un bug, e' una scelta di design da fare esplicitamente): oggi
   NO_SELL esclude lo strumento dall'**intero** ranking SATOR
   (`_score_universe`), non solo dai nuovi acquisti — quindi sparisce
   anche dalla frontiera rischio/rendimento "Attuale"
   (`sator_frontier.py`) e dalla Mappa strumenti
   (`instrument_clustering.py`). Fedele al testo della spec (sezione 9 del
   documento sorgente: "escluso dal ranking"), ma in tensione con l'uso
   tipico di NO_SELL (una posizione storica sovrappesata che dovrebbe
   restare visibile nel portafoglio attuale, non solo bloccata per i
   nuovi acquisti). Nessun dato reale usa oggi NO_SELL (verificato), quindi
   dormiente — ma va deciso esplicitamente prima che qualcuno lo attivi:
   se la scelta e' "resta visibile ovunque tranne che come candidato
   d'acquisto", la correzione tocca `_score_universe` (non escludere dal
   ranking, solo forzare `Sug=0`/decision score nullo) e verosimilmente
   anche `build_sator_decision_record` (oggi esplicitamente escluso dal
   perimetro del sotto-progetto 5 dai vincoli globali del piano).

### Priorita 8 - Irrobustimento e maturazione 5.0

Traccia parallela alla chiusura cache/performance: qualita, difensivita e
documentazione prima di taggare una 5.0 definitiva.

1. Audit difensivo dei chart builder (`ui/charts/`): il crash
   `KeyError: 'Data'` gia' corretto era un gap isolato preesistente; verificare
   che tutti i builder abbiano guardie coerenti per dati vuoti, singolo
   giorno o strumento appena aperto (`empty_chart()` o equivalente), invece
   di scoprirli uno alla volta in produzione.
2. `CLAUDE.md` in root: introduzione rapida per un agente AI che riprende il
   lavoro, che rimanda a questo documento come fonte primaria invece di
   duplicarne il contenuto.
3. Review complessiva del branch (es. `/code-review ultra`) prima di taggare
   la 5.0 definitiva, per catturare quanto l'ispezione manuale punto-per-punto
   puo' aver perso.
4. Test/CI: decisione presa il 2026-08-05 di lasciare `tests/` locale ed
   effimero (mai versionato, per scelta esplicita gia' vigente), senza CI.
   Punto riaperto in futuro solo su richiesta esplicita: se riaperto, il repo
   GitHub e' privato, quindi versionare test con dati sintetici non
   esporrebbe dati reali.

---

## 6. Cose da non fare

- Non eliminare le tab principali gia' pronte.
- Non introdurre radio/selectbox per scegliere pagina o modalita' render.
- Non riattivare L4 snapshot dentro il render ordinario.
- Non aggiungere nuove cache locali nelle pagine.
- Non rendere Mercati un refresh automatico invasivo.
- Non duplicare formule finanziarie nella UI.
- Non inventare icone/colori fuori dai registri esistenti.
- Non presentare AI o simulazioni come previsioni certe.

---

## 7. Prossimo passo consigliato

Il prossimo lavoro concreto dovrebbe essere:

1. finire le ultime verifiche della fase cache con render log reale;
2. poi passare al tuning delle pagine pesanti, partendo da Cruscotti e solo
   dopo Quotazioni/Portafoglio;
3. ogni tuning deve usare la stessa governance cache gia' definita, senza
   introdurre selector, radio o render differiti.

Primo tuning UI applicato: wrapper Plotly idempotente e key automatiche stabili
per run. Prossima misura utile: nuovo render log a parita' di firma, idealmente
dopo un rerun nello stesso processo, per verificare se cala il remount dei
grafici.

Nessuna modifica performance deve essere marcata come risolta senza confronto
prima/dopo.
