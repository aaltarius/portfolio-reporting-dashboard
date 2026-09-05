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
- **Fix 2026-09-03, segnalato dall'utente**: "Aggiorna Quotazioni" scriveva
  il prezzo sotto la data odierna (`ts = date.today()`) per qualunque
  strumento non-NAV in un giorno feriale, **ignorando `price_date`** (la
  data reale del prezzo restituita da Yahoo) — solo i fondi NAV usavano
  gia' correttamente la data effettiva. Un refresh subito dopo mezzanotte
  (osservato alle 00:34) trova ancora l'ultimo prezzo della sessione
  precedente (17:35 del giorno prima) ma lo etichettava come oggi,
  creando una sessione di mercato fittizia nello storico — mai capitato
  prima perche' l'utente non aveva mai aggiornato cosi' presto dopo
  mezzanotte. Fix in `ui/sidebar.py`: la scrittura sceglie sempre
  `price_date` quando disponibile (non piu' condizionata da `wd`, la
  variabile "e' un giorno feriale?"), "oggi" resta solo il fallback per
  l'unico caso senza `price_date` (fast_info senza timestamp). Rimossa
  anche la stessa condizione `wd`/`not wd` sul commit finale in
  `storico_prezzi`, che prima impediva la scrittura di
  `candidate_prices_by_date` nei giorni feriali. Test di regressione in
  `tests/test_weekend_storico_update.py` (ispezione del sorgente, stesso
  pattern gia' in uso per `ui/sidebar.py` in `test_streamlit_pages.py`).
  Suite completa verde. **Non toccato**: la riga "2026-09-03" gia'
  scritta nel file reale (`data/prices/portafoglio_storico_prezzi.json`,
  23 strumenti, valori diversi da quelli del 09-02, non una semplice
  duplicazione) — decisione lasciata all'utente, il backup automatico ha
  uno snapshot precedente alla scrittura se serve confrontare. La riga
  fittizia e' stata poi rimossa su richiesta esplicita dell'utente
  ("ripristina i valori così posso riaggiornare"), via `load_data()`/
  `save_data()` (backup automatico incluso), non con una modifica diretta
  del JSON — verificato che `strumenti[].prezzo/aggiornato` erano gia'
  corretti (mai stati toccati dal bug) e restano invariati dopo la pulizia.
- **Feature 2026-09-03, richiesta dall'utente ("Ripara buchi")**: nuova
  sezione nella pagina Gestione Dati (`ui/pages/gestione_dati.py`,
  `_render_ripara_buchi`), sotto la tabella qualita' dati esistente.
  **Prima versione (scarico completo dello storico) scartata su
  correzione esplicita dell'utente** ("preferirei... recupero
  automatico/manuale degli ultimi 30 giorni, con possibilita' di
  inserire i buchi mancanti manualmente... in caso di non recupero
  automatico e relativa accettazione") — ridisegnata: 1) recupero
  automatico limitato a `get_yahoo_price_history_full(ticker,
  period="1mo")` (~30 giorni, non piu' l'intero storico disponibile);
  2) i buchi che quella finestra non copre (piu' vecchi, o Yahoo non li
  ha) finiscono in una tabella di inserimento manuale (`st.data_editor`
  con colonna Prezzo editabile), con un passo di conferma separato dal
  recupero automatico. Nuove funzioni pure in `core/market_data.py`:
  `compute_missing_business_days` (stessa definizione della colonna
  "Buchi" di `instrument_quality.py`, ma ritorna le date non solo il
  conteggio), `preview_recent_gaps_fill` (divide auto-recuperabile da
  manuale, sola lettura), `apply_recent_gaps_fill` (scrive solo dopo
  conferma, mai sovrascrive un prezzo gia' presente). 16 test in
  `tests/test_market_data_backfill.py`, suite completa del repo verde.
  **Bug reale trovato dall'utente in uso live (2026-09-03)**:
  `KeyError: 'auto_fill'` a runtime — causa: `st.session_state` aveva
  ancora l'anteprima nel formato della prima versione scartata (Streamlit
  non svuota `session_state` quando il codice viene ricaricato a caldo,
  solo quando la sessione viene riavviata davvero). Confermava esattamente
  il rischio "non verificato visivamente" segnalato sopra. Fix in
  `ui/pages/gestione_dati.py` (`_render_ripara_buchi`): se il contenuto
  salvato in sessione non ha la forma attesa (`auto_fill`/`manual_dates`
  come chiavi), viene scartato e si richiede una nuova scansione invece
  di far esplodere il rendering. Verificato con la suite di test
  (`test_market_data_backfill.py` + repo completo verdi). Ancora da
  confermare de visu dall'utente dopo un refresh/riavvio della sessione
  Streamlit per svuotare lo stato obsoleto.
- **Altri due fix "Ripara buchi", stesso giorno, entrambi segnalati
  dall'utente in uso live**: (1) le date nelle due tabelle erano in
  formato ISO grezzo (`2026-08-24`) invece di gg/mm/aaaa come il resto
  dell'app — ora `st.column_config.DateColumn(format="DD/MM/YYYY")` su
  entrambe, coerente con `fmt_date_only_it` gia' usato nella tabella
  qualita' dati della stessa pagina. (2) **bug reale, non solo di
  formattazione**: `preview_recent_gaps_fill` calcolava i buchi su TUTTO
  lo storico dello strumento (prima->ultima data salvata, che per un BTP
  puo' risalire a mesi fa) e mandava nella tabella manuale qualunque
  buco che l'auto-recupero a 30 giorni non copriva — comparivano quindi
  buchi vecchi di mesi ("non ha assolutamente senso" — giustamente).
  Corretto: la funzione ora limita ENTRAMBE le liste (auto e manuale)
  agli ultimi 30 giorni con un cutoff esplicito
  (`date.today() - timedelta(days=30)`); un buco piu' vecchio non viene
  proposto affatto da questo flusso. Nuovo test di regressione
  (`test_preview_recent_gaps_fill_ignores_gaps_older_than_30_days`),
  17 test in `test_market_data_backfill.py`, suite completa verde.
  Inoltre la tabella "Recuperabili automaticamente" ora mostra riga per
  riga data+prezzo trovato (prima solo un conteggio, es. "3, 1, 3..." —
  l'utente doveva "scegliere a scatola chiusa").

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

### Punto della situazione al 2026-09-01 — progetto InstrumentAnalysis

**Nuovo progetto, mai registrato qui prima d'ora (bug di processo, corretto
ora)**: da questa sessione, "InstrumentAnalysis" — motore centrale
online-first per benchmark + C/D/S per strumento, sostituisce i mapping
statici di `core/benchmark_registry.py` e l'euristica ticker/parola-chiave
di `core/services/sator.py::infer_sator_metadata`. Origine: handoff
esterno `HANDOFF_PROGRAMMATORE_BENCHMARK_CDS/` (non trattato come vangelo,
base di partenza migliorabile). Chiude la "voce 11" (look-through
automatico) della revisione classificazione/allocazione gia' completata
(sotto-progetti 1-5, sezione 3 sopra).

**Piano dettagliato**: `docs/superpowers/plans/2026-09-01-instrument-analysis-cds-benchmark.md`
(gitignored come tutto `docs/`, quindi non arriva su GitHub — resta
locale). La sua sezione "Stato di avanzamento" in cima e' la fonte di
dettaglio task-by-task; questa sezione qui e' il riepilogo che deve
restare leggibile anche se quel file si perde o non viene letto.

**Fasi A-E del piano — stato reale, verificato sul codice e sulla git
history, non solo dichiarato**:
- **Fase A (motore centrale, `core/instrument_analysis/`) — FATTA.**
  Contratti, cache, adapter (Yahoo, OpenFIGI, Borsa Italiana, issuer
  factsheet, ECB tassi, provider indice MSCI), motore C/D/S, ladder
  benchmark base (EXACT/SORELLA + fallback), composite, orchestratore
  `InstrumentAnalysisService`. Mergiata in `main` (fast-forward, commit
  `4fe5203` + fix `a4bda6c`/`d59c143` scoperti in fase di merge).
- **Fase E (harness test/regressione, 111 fixture) — FATTA.** Replay
  ufficiale sui 111 eseguito per la prima volta in questa sessione (prima
  sempre rimandato per tempo): **C/D/S 93,92/100 (91/111 esatti)**.
- **Fase B (facade benchmark + propagazione) — MAI INIZIATA.** Solo elenco
  task ad alto livello nel piano, nessun dettaglio task-by-task scritto,
  zero codice.
- **Fase C (integrazione SATOR, ramo automatico) — MAI INIZIATA.**
- **Fase D (aggancio al refresh in background) — MAI INIZIATA.**

**Lavoro di questa sessione (dentro la Fase A, non una fase nuova)**:
collegata la classificazione testuale (`core/instrument_analysis/text_classification.py`,
gia' scritta in una sessione precedente ma non ancora collegata) a
`build_profile()` — prima gli adapter non popolavano
`structural_type`/`theme`/`sector`/`factor`/`size`, quindi il motore
C/D/S cadeva sempre nel fallback UNKNOWN (35/35/30). Due bug reali trovati
dal replay con dati veri e corretti: (1) `_benchmark_text()` in
`profile.py` sceglieva una sola fonte testuale invece di combinarle,
perdendo il segnale quando lo scraping Borsa Italiana tronca il campo
benchmark a meta' parola; (2) i token bond non coprivano abbreviazioni
reali viste in produzione ("Agg Bond", "AGGR BND"). Corretto anche un bug
in `InstrumentAnalysisService.discovered_benchmark_catalog()` (duplicava
la series come label invece di leggere il label reale). Punteggio C/D/S
sul replay ufficiale: da fallback totale (100% UNKNOWN, misurato a fine
Fase E) a 93,92/100.

**Gap aperti dentro la Fase A** (non sono le fasi B/C/D, sono cose lasciate
incomplete dentro il motore gia' costruito — numerati come nel piano):
1. Ladder intermedio (CUGINA/ZIA/NONNA/FAMIGLIA_AMPIA) — non collegato.
2. Provider indice Livello 3 (STOXX/FTSE/S&P DJI/Solactive/ICE) — solo
   MSCI attivo.
3. Curve sovrane duration-specific — stub, sempre `None`.
4. Composite multi-asset/holdings look-through — costruito ma non
   collegato a `service.py`.
5. Drift identity-resolution: 6/111 ticker "delisted" su Yahoo (404)
   risolvono a uno strumento reale diverso da quello inteso dalla
   fixture (es. `IQQ7.MI` atteso "iShares STOXX Europe 600 Technology",
   risolve a "iShares MSCI Turkey") — trovato analizzando i diff del
   replay ufficiale in questa sessione, non toccato.
6. Duration/bond sub-classification (ULTRA_SHORT/SHORT_GOV_BOND) e fondi
   proprietari Fineco AM privi di segnale testuale (serie "FAM-*") — 12
   dei 20 diff residui del replay, richiedono rispettivamente
   `duration_years` numerico (punto 3) e dati di composizione reale
   (punto 4): non un gap nuovo, solo quantificato oggi.

**Prossimo passo — DECISO il 2026-09-01**: l'utente ha confermato di
procedere con il **punto 1 sopra (ladder intermedio CUGINA/ZIA/NONNA/
FAMIGLIA_AMPIA)**, dopo che gli ho spiegato perche' non vede ancora
traccia di questo lavoro nell'applicativo — verificato con un grep che
zero file in `ui/` o nel resto di `core/` importano
`InstrumentAnalysisService`: il motore nuovo e' isolato, non collegato,
quello che gira davvero in produzione e' ancora `core/benchmark_registry.py`
e `core/services/sator.py::infer_sator_metadata` (entrambi fermi al
2026-08-21, mai toccati da questo progetto). Il ladder intermedio resta
un miglioramento "sotto il cofano" — misurabile solo via replay, non
visibile in app finche' la Fase B (propagazione) non collega il motore
nuovo al posto di quello vecchio. Questo va tenuto presente: chiudere il
punto 1 non produce nessun cambiamento visibile per l'utente nell'app.

**Dettaglio task scritto PRIMA di toccare codice** (richiesto
dall'utente, per non ripetere l'errore di oggi): 6 task (L1-L6) in
`docs/superpowers/plans/2026-09-01-instrument-analysis-cds-benchmark.md`,
sezione "Ladder intermedio — dettaglio task (gap 1, deciso 2026-09-01)",
subito prima della sezione "Fase A — Motore centrale". Riassunto: porta
`REFERENCE_FAMILIES` (catalogo statico di ~20 famiglie -> ticker Yahoo
reali) e `family_ladder()` da POC17.2, un punteggio di geometria/forma
tra serie storiche **senza pandas** (decisione presa: `series.py` di
questo progetto e' gia' esplicitamente senza pandas), una cache storici
separata (TTL giornaliero) per non rifare fetch per ogni strumento, e
collega tutto in `benchmark.py::resolve_benchmark` tra il ramo SISTER e
il fallback MERCATO_GENERALE esistente. Punteggio benchmark misurato oggi
prima di iniziare: **42,66/100 medio** — il numero da confrontare a fine
lavoro (Task L5), scritto qui subito dopo la misura, non a fine sessione.

**Task L1-L4 completati e testati (79 test nuovi/estesi, tutti verdi,
suite completa del repo verde). Task L5 (replay ufficiale) fatto:
risultato NEGATIVO, causa isolata, spiegato subito sotto — nessuna
modifica dichiarata risolta senza il confronto prima/dopo.**

**Score benchmark dopo L1-L4: 42,61/100 — invariato (era 42,66/100).
`relation_grade_counts` identico bit-per-bit a prima: zero istanze di
CUGINA/ZIA/NONNA su 111 strumenti reali.** Il ladder e' stato verificato
funzionante in isolamento (`fetch_family_series('TECH_GROWTH')` con rete
reale ritorna dati veri) — il problema non e' un bug nel codice scritto
oggi, sono due fatti che si sommano:
1. I 6 strumenti che oggi cadono in MERCATO_GENERALE sono **tutti bond
   governativi** (`GOV_BOND`) — il ladder e' scoped solo a equity/gold/
   commodity/digital_asset (per design, Task L1), quindi non li tocca mai.
   Nessuno strumento azionario del dataset raggiunge mai il fallback:
   risolvono tutti EXACT o SISTER prima, anche quando il testo scrapato e'
   troncato a meta' parola.
2. **La vera causa del punteggio basso e' un gap diverso, non nella lista
   originale**: i rami EXACT/SISTER di `benchmark.py` (100 strumenti su
   111) non calcolano mai `geometry_score`/`coverage_obs` — restano a 0,
   quindi la formula 55/35/10 dell'handoff (target 81,3/100) li tappa a
   ~46,75/100 indipendentemente da quanto buono sia il match. Causa a
   monte: EXACT/SISTER risolvono a **nomi leggibili** ("MSCI World
   Index"), non a **ticker interrogabili** — serve una risoluzione
   nome-benchmark -> ticker per poter calcolare geometry anche li', lavoro
   gia' segnalato come futuro nel commento di `series_is_fetchable` in
   `contracts.py`, ma non sapevamo fosse *il* collo di bottiglia dominante
   finche' questo replay non l'ha isolato.

Dettaglio completo: `docs/superpowers/plans/2026-09-01-instrument-analysis-cds-benchmark.md`,
sezione "Task L5", stesso file del dettaglio task.

**Prossimo passo — DECISO il 2026-09-02**: l'utente ha confermato di
procedere con la risoluzione nome-benchmark -> ticker interrogabile per i
rami EXACT/SISTER (per poter calcolare geometry_score/coverage_obs anche
li', causa reale del punteggio basso). Stessa disciplina di L1-L4: piano
task scritto prima di toccare codice.

**Verifica empirica PRIMA di scrivere codice (stessa disciplina appena
imparata da L5) — risultato negativo, pivot deciso senza ancora chiedere
conferma**: testata a mano la ricerca Yahoo per testo libero (stesso
endpoint di `find_ticker_candidates`) su 6 nomi reali di questa sessione
(nomi Borsa Italiana troncati, nomi issuer factsheet lunghi) — **5 su 6
zero risultati INDEX**, solo un nome corto/canonico ("MSCI Turkey") ha
trovato un match. I nomi ufficiali reali sono troppo lunghi/troncati per
funzionare con una ricerca testuale libera — stesso esito di L1-L4
(costruito bene, zero impatto), stavolta scoperto PRIMA di scrivere
codice.

**Pivot CONFERMATO dall'utente il 2026-09-02**: invece di una ricerca testuale
nuova, riusare `family_ladder()`/`geometry_score()` (gia' costruiti e
provati in L1-L4) anche per i rami EXACT/SISTER, come controllo di
qualita' supplementare basato su `profile.sector/theme/geography` (gia'
affidabili, indipendenti dal testo troncato) — senza mai cambiare
`operational_series`/`relation_grade`, solo per popolare
`geometry_score`/`coverage_obs` che oggi restano sempre a zero. Dettaglio
in `docs/superpowers/plans/...`, sezione "Task M3-bis"/"Task M4-bis".

**Task M3-bis/M4-bis implementati e testati (18 test in `test_benchmark.py`,
tutti verdi, suite completa del repo verde). Replay ufficiale rieseguito:
score benchmark 62,12/100 (era 42,61/100 dopo L1-L4, 42,66/100 all'inizio
della sessione) — +19,5 punti reali, misurati, non dichiarati.** C/D/S
invariato (93,92/100, fuori scope di questo lavoro). Resta sotto la
soglia di riferimento 81,3/100 dell'handoff (95/111 ancora sotto soglia):
miglioramento reale ma non risolutivo — molti match ora hanno una
geometria calcolata ma non abbastanza alta da superare 81,3 da sola.
Dettaglio completo (incluso un limite tecnico non risolutivo sul timing
misurato dal replay) in `docs/superpowers/plans/...`, sezione "Task
M4-bis".

**Continuazione autonoma post-checkpoint ("continua tu in maniera
progressiva")**: analizzati uno per uno (non a campione) i 75/111 ancora
sotto soglia dopo il +19,5 di cui sopra. Trovati e corretti 2 fix
aggiuntivi:
- **Fix 1**: bug gemello di quello del settore (vedi sopra), stavolta sul
  factor — "wide moat" (MOAT.MI reale) non faceva scattare il gate
  equity in `text_classification.py`. Stesso principio, stesso fix.
  Verificato con rete reale: MOAT.MI 46,8 -> 76,5/100.
- **Fix 2**: `service.py` scaricava lo storico dello strumento col ticker
  grezzo passato dal chiamante, non con quello RISOLTO da
  `resolve_yahoo_identity()` (che gia' trova un ticker funzionante via
  ISIN quando l'originale e' delisted — 4 casi reali verificati:
  IQQ6.MI→INFR.MI, E50.MI→MSE.MI, XWCO.MI→XDWM.MI, KOREA.MI→KRW.PA).
  **Nota**: alcuni ticker risolti sembrano un fondo diverso da quello
  inteso dalla fixture — quel problema (drift identity-resolution) resta
  aperto, questo fix allinea solo il fetch storico con l'identita' gia'
  usata altrove.

Suite completa verde dopo entrambi i fix. **Replay ufficiale completo
tentato due volte, interrotto dall'esterno entrambe le volte** (non un
errore nel codice). Verifica mirata sui 36 strumenti rimasti al
punteggio piatto (1 passaggio): **6/36 migliorati, media del sottoinsieme
46,75 -> 52,4/100** — salti fino a +42 punti su singoli strumenti
(E50.MI, EUQ.MI, XWCS.MI). Risultato misto su ~18 strumenti equity dove
il fix 2 non ha funzionato in questo run (probabile flakiness di rete,
non un bug deterministico — `KOREA.MI` aveva funzionato in una verifica
precedente nella stessa sessione). **Replay ufficiale completo ottenuto al terzo tentativo: score benchmark
64,19/100 (era 62,12/100 dopo M3-bis, 42,66/100 all'inizio sessione —
+21,5 punti totali, misurati, in questa sessione).** C/D/S 94,23/100.
72/111 ancora sotto soglia 81,3 (era 75).

**Terzo giro deciso ("spremiti le meningi") — N1-N3, verificati
empiricamente prima di scrivere codice**: N1 aggiunge famiglie
bond/money-market al ladder (oggi 12 strumenti completamente esclusi,
7/9 testati passerebbero subito con proxy reali AGG/IEF/SHY/TIP/LQD/
BIL); N2 fa provare l'intera scaletta di candidati invece di solo il
primo (FAMAMW.MI oggi fallisce per un soffio, 38,1 su 40, con una
seconda riga potrebbe passare); N3 aggiunge un retry leggero per
l'intermittenza di rete confermata (KOREA.MI: stesso codice, un
tentativo fallisce uno riesce). **N4 scartato** (abbassare la soglia del
gate) perche' comprometterebbe l'affidabilita' — verificato che il gate
rifiuta correttamente un match a bassa correlazione reale (ESPO.MI,
0,32). Dettaglio in `docs/superpowers/plans/...`, sezione "Task N".

**N1-N3 implementati e testati, replay ufficiale rieseguito: score
benchmark 68,69/100** (era 64,19/100, 42,66/100 all'inizio sessione —
**+26 punti totali in questa sessione**). 68/111 ancora sotto soglia
81,3 (era 72). Dettaglio N1 (famiglie bond/money-market, 7/9 verificate
passano subito), N2 (prova l'intera scaletta, non solo la prima riga),
N3 (retry leggero per intermittenza di rete confermata) in
`docs/superpowers/plans/...`, sezione "Task N".

**Task Q deciso il 2026-09-03**: curva benchmark composita pesata per C/D/S
(idea dell'utente, confermata nella documentazione originale
`_mixed_role_composite` di `poc17_4_engine_VALIDATED_REFERENCE.py`, riga
3558 — porta i due ruoli C/D/S piu' grandi, arrotonda il peso al 5% piu'
vicino, stesso principio gia' nel docstring di `composite.py` mai
collegato a nulla). Correzione di un errore mio precedente: avevo detto
che serviva composizione reale (asset_mix) — vero solo per i fondi
davvero multi-asset (meccanismo diverso, "existing economic two-leg
builder" nello stesso riferimento), non per il caso generale di
qualunque strumento con C/D/S misto, che usa solo i C/D/S gia' calcolati
oggi. Verificato empiricamente PRIMA di procedere: VJPA.MI (Giappone,
75C/25S) con blend 75%GLOBAL_EQUITY+25%JAPAN_EQUITY -> geometria 82,6
contro 58,4 del solo confronto puro (+24 punti); CNAA.MI modesto
(+1,7); EM13.MI (bond) **peggiore** del confronto puro — non un successo
universale, da verificare caso per caso in implementazione.

**Task P (miglior riga della scaletta + famiglie paese) implementato e
misurato: score benchmark 71,03/100** (era 68,57 dopo Task O, 42,66
all'inizio sessione). 59/111 ancora sotto soglia (era 68).

**Analisi del soffitto matematico** (fatta prima di continuare a
inseguire il 90% chiesto dall'utente, per essere onesti su cosa e'
davvero raggiungibile): la formula `0,55*semantic + 0,35*geometry +
0,10*coverage` ha un tetto che dipende dal grado semantico, non solo
dalla geometria — con geometria e copertura perfette (100), CUGINA
arriva a ~89-91, ZIA a ~82-84, **NONNA non supera mai 72,5, sotto la
soglia 81,3 a prescindere da quanto sia buona la geometria**. Una media
di 90/100 su 111 strumenti richiederebbe quasi tutti a grado CUGINA con
geometria quasi perfetta — non raggiungibile per costruzione quando uno
strumento non ha nessuna famiglia CUGINA disponibile (nessun settore/
tema/paese riconosciuto) e cade per forza su ZIA/NONNA. Dettaglio in
`docs/superpowers/plans/...`, sezione "Task P".

**Task Q implementato e verificato**: curva composita pesata C/D/S
(`_mixed_role_composite_candidate` in `benchmark.py`, porta il principio
di `_mixed_role_composite` dal riferimento validato, non il codice
letterale — quello userebbe lo stesso profilo per entrambe le gambe
sull'equity, collassando quasi sempre a una sola serie). Scope: solo
equity con satellite tra i due ruoli C/D/S piu' grandi (verificato che
danneggia i bond). Compete col confronto singolo su punteggio combinato
finale, mai forzato. Verificato dal vivo (rete reale): VJPA.MI
geometry_score 58,4 -> 82,6, senza toccare l'identita' ufficiale gia'
trovata (EXACT, "FTSE JAPAN INDEX"). `components` serializzato in cache
(prima escluso per design, mai popolato — ora lo e'). 26 test nuovi,
suite completa del repo verde.

**Task Q — replay ufficiale 2026-09-03: score benchmark 71,03 -> 71,09/100
(+0,06, sostanzialmente piatto)**. cds score invariato 94,23/100 (atteso,
Task Q non tocca la classificazione). `relation_grade_counts` del replay
(PROPRIA 93, SORELLA 7, MERCATO_GENERALE 6, NONNA_TECNICA 5) **non
contiene nessun FAMIGLIA_AMPIA**: la curva composita non e' mai stata
selezionata come serie operativa su questi 111 fixture — i 6 fallback
MERCATO_GENERALE restano tutti bond (fuori scope, come gia' documentato
per il ladder in Task L5), e nessuno strumento EXACT/SISTER equity aveva
un mix C/D/S tale da far vincere il confronto combinato al composito
sull'identita' singola. Il +0,06 misurato viene solo dal campo
`geometry_score` che per un piccolo numero di righe EXACT/SISTER equity
riflette ora il punteggio del composito quando risultava marginalmente
migliore nel confronto interno (mai un cambio di identita' — vedi design
sopra). **Onestamente: come per il ladder intermedio (Task L5), il
meccanismo e' corretto e verificato dal vivo (VJPA.MI), ma su questo
specifico dataset di replay ha impatto reale prossimo a zero.** Resta
comunque codice corretto e testato, pronto per strumenti reali con un
mix C/D/S piu' marcato di quelli presenti nei 111 fixture attuali.

**Stato del progetto InstrumentAnalysis a fine sessione 2026-09-02**:
Fase A + E fatte e validate; gap 1 (ladder intermedio) fatto, impatto
nullo sul dataset reale di per se' (tutti bond, fuori scope iniziale) ma
infrastruttura riusata con successo per tutto il resto della sessione;
geometry per EXACT/SISTER + 5 fix aggiuntivi (factor mancante, ticker
risolto per lo storico, famiglie bond/money-market, scaletta completa,
retry di rete) fatti, **score benchmark 42,66 -> 68,69/100 (+26 punti
reali, misurati col replay ufficiale)**. Fasi B/C/D ancora mai iniziate —
nessuna di queste modifiche e' visibile nell'app. **Prossimo passo: non
deciso**, da discutere alla prossima sessione — opzioni aperte: i residui
sotto soglia richiedono o accettare un segnale meno affidabile (scartato
oggi, vedi N4) o lavoro strutturale diverso (curve sovrane vere, gap 3;
policy di validazione ISIN vs ticker, gap 7); oppure passare alla Fase B
(propagazione all'app, l'unica cosa che l'utente vedrebbe cambiare
visivamente).

**Prossimo passo — DECISO il 2026-09-02**: l'utente ha confermato la
raccomandazione — smettere di inseguire il punteggio (rendimenti
decrescenti), e prima di collegare qualunque cosa all'app investigare il
presunto **drift di identity-resolution** (gap 7).

**Investigato e RISOLTO (2026-09-02): non e' un bug nostro.** Verificato
con una seconda fonte indipendente e autorevole (OpenFIGI, non solo la
ricerca testuale Yahoo) sui 3 casi piu' sospetti (IQQ7.MI, IQQ0.MI,
XWCO.MI): OpenFIGI conferma **esattamente** la stessa identita' che Yahoo
trova (Turchia, Property Yield, Materials) — due fonti dati indipendenti
e autorevoli concordano tra loro, e discordano entrambe dal `name_hint`
della fixture. Conclusione: e' la **fixture di test sintetica**
("RANDOM_MILAN_2026_D", generata casualmente, gia' documentato altrove
in questo file) ad avere abbinamenti ISIN/nome errati per queste 6 righe,
non il nostro codice di risoluzione — che sta facendo esattamente la
cosa giusta. **Nessun fix di codice necessario.** Il rischio teorico
resta (ISIN puo' essere riassegnato dopo la chiusura di un fondo, o le
fonti stesse possono sbagliare) ma non e' quello che si vede in questo
dataset — non e' un problema di correttezza urgente da risolvere prima
della Fase B.

Via libera confermata per procedere con la Fase B (propagazione
all'app) come prossimo passo.

**Deviazione dalla Fase B, decisa il 2026-09-03**: prima di generare la
tabella C/D/S+benchmark sui 30 strumenti reali "aperti" (richiesta
esplicita dell'utente), e' emerso che 4 fondi FAM (score 0,
EMERGENZA_TECNICA) e 4 BTP (score 16,5, solo fallback generico) restano
molto sotto soglia. L'utente ha contestato — verificato correttamente —
che l'handoff originale descriveva gia' una soluzione per entrambi
(sezione H multi-asset via `funds_data`, sezione I curva sovrana ECB),
mai implementata. Confermato empiricamente: i 4 ISIN FAM sono
risolvibili su Yahoo come fondi comuni con composizione REALE
disponibile (`funds_data.asset_classes`), scartati oggi solo perche'
`find_ticker_candidates` esclude i simboli Yahoo "0P..." (fondi comuni)
a prescindere. La curva ECB duration-matched per i BTP e' raggiungibile
e risponde con dati reali; lo spread Italia via Banca d'Italia e' piu'
fragile (sito cambiato) ma il riferimento ha gia' un fallback onesto per
quel caso. **Priorita' cambiata su richiesta dell'utente ("non avere
premura della fase B... approfondisci e risolvi"): Task R (fondi
multi-asset + curva sovrana BTP) prima della Fase B.** Dettaglio
completo in `docs/superpowers/plans/...`, sezione "Task R".

**Task R implementato e verificato sugli 8 strumenti reali (2026-09-03)**:

- **Fondi multi-asset** (`_multi_asset_composite_candidate` in
  `benchmark.py`, dato reale da `funds_data.asset_classes` via nuovo
  `resolve_mutual_fund_identity`/`fetch_fund_asset_mix` in
  `reference_data/yahoo.py`): **FAM-FLEX 0 -> geometria 86,4 (65%
  GLOBAL_EQUITY+35% AGG_BOND)**, **FAM-PU6 0 -> geometria 81,2** (35/65),
  **FAM-PU8 0 -> geometria 86,7** (85/15). **FAM-EMD resta a un fallback
  modesto** (score 16,5, come i BTP): e' 96% bond puro (nessuna gamba
  equity, il composito non si applica per costruzione — corretto), e i
  candidati bond disponibili (CORP_BOND/AGG_BOND, americani) tracciano
  un fondo di debito emergente troppo male per superare il gate di
  geometria (34-38, sotto soglia 40) — aggiunto solo un fallback minimo
  (asset_class OBB da composizione reale quando il testo non la
  riconosce) per evitare l'emergenza infrastrutturale totale. Una
  famiglia di riferimento EM-bond dedicata risolverebbe meglio, non
  fatta in questo giro.
- **Curva sovrana BTP** (`_sovereign_synthetic_candidate` in
  `benchmark.py`, curva ECB duration-matched + spread Italia best-effort
  in `reference_data/rates.py` + matematica pura in
  `sovereign_curve.py`): **score 16,5 -> 41,9/100 su 3 BTP su 4**
  (BTP-15MZ28, BTP-1DC28, BTP-1AG30), confidence 0,58 (spread Italia non
  trovato, sito Banca d'Italia probabilmente ristrutturato — degrada
  onestamente alla sola curva euro-area, mai un errore). **BTP-0826**
  (duration reale 0,09Y, quasi a scadenza) usa lo stesso meccanismo con
  un floor di 3 mesi sulla curva (piu' corto non pubblicato da ECB):
  score 16,5 -> 41,9 anche per questo, stesso risultato degli altri 3.
  **Richiede `duration_years` fornito dal chiamante**
  (`analyze(..., duration_years=...)`, nuovo parametro — nessuna fonte
  online di questo motore da' la duration di un singolo BTP): per i
  fixture ufficiali derivato da `maturity_date` (anni a scadenza come
  proxy, verificato vicino alla duration modificata reale — 3,91 vs 3,75
  per BTP-1AG30); per la Fase B andra' passato da
  `duration_modificata` (arricchimento PDF gia' esistente sullo
  strumento reale).
- 26 test nuovi (yahoo.py, profile.py, benchmark.py, service.py,
  sovereign_curve.py, rates.py, benchmark_scorer.py), suite completa del
  repo verde.

**Task R — replay ufficiale 2026-09-03: score benchmark 71,09 ->
74,68/100 (+3,59), score cds 94,23 -> 94,95/100.** A differenza di
Task Q (+0,06, sostanzialmente piatto), qui il salto e' reale e
strutturale: `relation_grade_counts` mostra il nuovo grado
`PROPRIA_STRUTTURALE` comparire **7 volte** (3 fondi FAM con composito
reale + 4 BTP con curva sovrana — esattamente il numero atteso),
`NONNA_TECNICA` (emergenza tecnica) crolla da 5 a 1 fixture,
`infrastructure_emergency_count` da 5 a 1. `MERCATO_GENERALE` scende da
6 a 4. `PROPRIA` scende di 1 (93->92, verosimilmente variazione di rete
tra due run live, non un effetto del codice — nessun ramo EXACT toccato
da Task R). **Non ancora tutto risolto onestamente**: 1 fixture resta in
emergenza tecnica (non identificato, fuori scope di questo giro), e i
BTP restano a confidence 0,58 (solo curva euro-area, spread Italia da
Banca d'Italia ancora non disponibile — sito probabilmente
ristrutturato).

**Task R — seguito, stesso giorno, due correzioni volute dall'utente**:

1. **"Dobbiamo trovare una soluzione per i BTP... idem per FAM-EMD... deve
   esserci un indice di riferimento facile"**: aggiunte due famiglie di
   riferimento mirate in `reference_families.py` — `EM_BOND` (`EMB`,
   `EMLC`) e `ITALY_GOV_BOND` (`EDMA.MU`, iShares Italy Govt Bond UCITS
   ETF — unico trovato con storico Yahoo reale, 254 osservazioni).
   Verificato empiricamente prima di collegare: EMB contro FAM-EMD
   geometria 64,1 (sopra soglia 40, molto meglio dei 34-38 dei proxy
   USA). Per FAM-EMD: riga aggiuntiva nel ladder BOND quando
   `geography=="emerging"`, compete e vince via il meccanismo esistente
   (best-across-all-rows, Task P) — **score 16,5 -> 73,2**. Per i BTP:
   nuova `_country_gov_bond_candidate` in `benchmark.py`, assegnazione
   diretta (come EXACT/SISTER, nessun gate di geometria obbligatorio —
   un BTP non ha storico proprio interrogabile via questo motore).
2. **"Non mi fa impazzire avere per indice un ETF... vorrei un indice
   puro se possibile"**: verificato che non esiste un indice BTP puro
   liberamente disponibile su Yahoo (ne' un "^" per un indice sovrano
   italiano, ne' per un rendimento IT10Y) — confermato con ricerche
   dirette. La curva ECB (Task R originale, sopra) **e' gia' la
   risposta**: e' una curva di rendimenti pubblicata, non un fondo.
   **Priorita' invertita**: la curva ECB ora vince SEMPRE quando
   disponibile (duration nota + risposta reale dalla fonte), l'ETF
   `EDMA.MU` resta solo rete di sicurezza se la curva fallisce (mai piu'
   "non trovo nulla"). Corretto anche un bug di efficienza emerso nel
   refactor: lo storico proprio veniva richiesto due volte per
   strumento (ora una sola, riusato tra i due tentativi).
   **Bonus aggiunto nello stesso giro**: nuovo `analyze(...,
   own_history=...)` — se il chiamante fornisce lo storico prezzi gia'
   posseduto (es. quello reale salvato in portafoglio per un BTP), la
   geometria contro la curva ECB diventa un vero controllo di qualita'
   invece di restare a sola confidence. Verificato con lo storico reale
   dei 4 BTP: **3 su 4 salgono a 65,0-71,9/100** (BTP-1AG30 resta a
   41,9 — solo 7 giorni di storico salvato, sotto la soglia minima di
   osservazioni, correttamente non gonfiato). Per FAM-EMD: nessun indice
   "puro" liberamente disponibile trovato (le curve di debito EM sono
   dati proprietari) — EMB (ETF) resta la scelta migliore realistica,
   comunicato onestamente all'utente.
   28 test nuovi/aggiornati, suite completa verde.

**Task R follow-up — replay ufficiale 2026-09-03: score benchmark 74,68
-> 75,38/100 (+0,70), cds invariato 94,95/100.** `relation_grade_counts`:
compare per la prima volta `CUGINA` (1, FAM-EMD via EM_BOND),
`PROPRIA_STRUTTURALE` sale a 9 (era 7 — oltre ai 4 BTP reali, anche 2
fixture BTP sintetiche del set di test beneficiano dello stesso
meccanismo, segno che generalizza), `MERCATO_GENERALE` scende da 4 a 1.
Resta 1 solo fixture in emergenza tecnica (non identificato, fuori
scope). **Il replay non misura il bonus di `own_history`** (i fixture
non hanno uno storico proprio reale da passare) — quello si vede solo
con dati reali, verificato sotto.

**Ri-controllo sui 30 strumenti reali "aperti" del portafoglio (con
`duration_years` e `own_history` reali per i 4 BTP): media punteggio
60,8 -> 77,8/100, strumenti sotto soglia 81,3 da 22/30 a 14/30.** Nessun
strumento resta a 0 o a un fallback debole. FAM-FLEX/PU6/PU8: 0 ->
82,9-86,0. FAM-EMD: 0 (poi 16,5 col fallback minimo) -> 73,2. I 4 BTP:
16,5 -> 41,9-71,9 (3 su 4 con bonus di geometria da storico reale,
BTP-1AG30 resta a 41,9 per storico troppo corto, 7 giorni, non gonfiato).
**Unico caso rimasto scoperto, invariato e fuori scope di oggi**:
XDEB.MI (46,8) — identita' trovata ma nessuna famiglia "minimum
volatility" nel ladder per la geometria.

---

**CHECKPOINT 2026-09-03 (fine sessione, l'utente deve riavviare)**:
Task R (fondi multi-asset + BTP) e il suo follow-up (indice puro +
EM_BOND) sono **chiusi e verificati**, sia sul replay ufficiale sia sui
30 strumenti reali. Suite completa del repo verde. Documentazione
(questo file, il piano in `docs/superpowers/plans/...`, `CHANGELOG.md`)
aggiornata fino a questo punto. **Nessuna modifica in sospeso, nulla da
riprendere a meta'.** Prossimo passo proposto (non ancora avviato):
**Fase B — collegare il motore InstrumentAnalysis all'app vera**
(`core/benchmark_registry.py`, SATOR, le pagine Quotazioni/Cruscotti/
Summary), l'unica cosa che l'utente vedrebbe cambiare visivamente. Non
ancora confermata esplicitamente dall'utente in questa sessione dopo il
lavoro di oggi — da chiedere/confermare alla ripresa.

---

**Sessione 2026-09-03 (continuazione) — Fase B avviata: Task S + B1 + B2 fatti**

Confermato dall'utente: commit del lavoro pendente (Task R + follow-up +
"Ripara buchi", mai committato nella sessione precedente pur essendo
completo — 3 commit separati, vedi git log) poi via alla Fase B.

**Analisi pre-implementazione (in plan mode) ha trovato un problema
architetturale reale**: per ~90% degli strumenti (rami PROPRIA/SORELLA)
`operational_series` e' un nome leggibile, non un ticker Yahoo interrogabile
(`series_is_fetchable=False`) — uno swap diretto della facade avrebbe fatto
sparire il grafico benchmark/correlazione per la maggioranza degli
strumenti (il vecchio registro statico dava sempre un ticker approssimato
ma reale). **Deciso con l'utente**: Task S prima di B1, per esporre un
ticker di riserva scaricabile gia' calcolato internamente dal motore (mai
scartato, mai un valore inventato) prima di collegare la facade.

**Task S — fatto e verificato**: nuovo campo `fallback_fetchable_series`/
`_label` su `BenchmarkResolution`, popolato nei rami EXACT/SISTER
(riusa il candidato di famiglia gia' calcolato per il confronto di
geometria, prima scartato), nei rami compositi (gamba di peso maggiore),
nel ramo curva sovrana BTP (ETF governativo nazionale, interrogato
opportunisticamente anche quando vince la curva ECB). Mai tocca
`operational_series`/`relation_grade`/`official_name`. 39 test in
`tests/core/instrument_analysis/test_benchmark.py`.

**Bug reale trovato dal replay ufficiale** (non un errore di S, di
processo — verificato PRIMA di dichiarare fatto): il nuovo campo
sopravviveva in memoria ma spariva al primo cache-hit — `_benchmark_to_cache`/
`_benchmark_from_cache` in `service.py` avevano una whitelist di campi
non aggiornata (stesso principio del bug gia' noto per C/D/S, vedi test
esistente `test_analyze_cache_hit_reconstructs_a_valid_analysis`).
Corretto, verificato dal vivo su SWDA.MI (fresh analyze -> fallback
popolato -> sopravvive al cache-hit), nuovo test di regressione diretto.

**Replay ufficiale sui 111 (prima del fix cache)**: `relation_grade_counts`
e score C/D/S **bit-per-bit identici** al replay di fine sessione
precedente (92 PROPRIA, 7 SORELLA, 9 PROPRIA_STRUTTURALE, 1 CUGINA, 1
MERCATO_GENERALE, 1 NONNA_TECNICA — cds 94,95/100 esatto). Score benchmark
75,39 contro 75,38 (variazione di rete tra due run live, non un effetto
del codice — nessun campo di identita' toccato da Task S). **Non ancora
rimisurata la percentuale di copertura del fallback sui 111 dopo il fix
cache**: un secondo replay a cache pulita e' stato avviato ma interrotto
dall'ambiente (processo in background terminato dal sistema prima del
completamento, non un errore del codice) — verificato pero' dal vivo su
un'istanza reale (SWDA.MI -> fallback `^GSPC`/GLOBAL_EQUITY) che il
meccanismo funziona end-to-end con dati reali.

**Fase B — Task B1 (facade) + B2 (pulizia import morti) fatti**:
`core/benchmark_registry.py` e' ora una facade sottile su
`InstrumentAnalysisService` — rimossi tutti i mapping statici
(`BENCHMARK_BY_TICKER/ISIN/TYPE/MACRO/INDEX_PATTERN`, ~90 righe).
`BenchmarkAssignment` esteso additivamente con i campi ricchi del motore;
`.ticker` = `operational_series` se interrogabile, altrimenti il fallback
di Task S, altrimenti vuoto; `.label` resta sempre l'identita' ufficiale.
Branch override manuale invariato bit-per-bit. `duration_years` (da
`duration_modificata`, gia' presente sullo strumento arricchito) passato
al motore per la curva sovrana sui BTP reali. `known_benchmark_catalog()`
delega a `discovered_benchmark_catalog()` (scoperto a runtime, non piu'
statico — **effetto collaterale onesto**: su un processo appena avviato,
con cache di risoluzione vuota, l'autocomplete benchmark in Quotazioni
interne/Strumenti sara' vuoto finche' il motore non ha risolto almeno uno
strumento; mai verificato visivamente in app, da fare alla ripresa).

`tools/audit_no_static_benchmarks.py` ora **passa** sul repo reale (prima
documentato come atteso fallire fino a questa fase — test aggiornato).
Suite completa del repo (430+ test) verde: riscritti i test che
testavano il *contenuto* dei mapping statici rimossi (quel contenuto non
esiste piu', il motore lo sostituisce e viene testato altrove — replay
ufficiale), preservati con un fake service locale
(`tests/_fake_instrument_analysis_service.py`) i test sul *meccanismo*
(precedenza override, propagazione ticker/label ai consumer, nessuna
chiamata di rete reale in un test unitario).

**B3-B8 (dashboard_datasets, finance, services/benchmark,
instrument_comparison, sator, form-server quote_interne/strumenti)**:
nessuna modifica di codice necessaria — la facade mantiene esattamente le
stesse firme. Verificato con la suite completa (ogni consumer ha test che
esercitano il path reale), non ancora con verifica visiva in app.

**Commit di questa sessione (4, separati per task)**: Task S
(`core/instrument_analysis/{contracts,benchmark}.py`), fix cache
(`service.py`), B1+B2 (`core/benchmark_registry.py` + pulizia import +
test), oltre ai 3 commit del lavoro pendente committato a inizio sessione
(Task R/follow-up InstrumentAnalysis, Ripara buchi + fix data fittizia,
docs).

**B9 completato (stessa sessione, dopo il checkpoint sopra)**:

1. **Copertura fallback sui 111 a cache pulita — misurata**: 98/109
   risoluzioni non-fetchable (89,9%) ora hanno un ticker di riserva reale
   per grafico/correlazione. Le 11 senza fallback restano onestamente
   senza grafico benchmark (nessun candidato di famiglia disponibile),
   comportamento neutro per costruzione (regola non negoziabile 9), non
   un ticker inventato.
2. **Replay ufficiale completo rieseguito**: cds invariato bit-per-bit
   (94,95/100), benchmark 75,38 -> 75,28/100 (-0,10, rumore). Nota
   d'onesta': `relation_grade_counts` ha mostrato uno spostamento piu'
   grande del solito (`PROPRIA_STRUTTURALE` 9->3, `SORELLA` 7->13) —
   **investigato prima di liquidarlo come rumore**: confrontati i punteggi
   dei singoli BTP/fondi FAM reali tra i due run, risultati **identici
   bit-per-bit** (es. BTP-15MZ28 41,9 in entrambi). Lo spostamento viene
   da fixture BTP *sintetiche* del set di test (non i 4 BTP reali)
   colpite da intermittenza di rete/rate-limit Yahoo osservata dal vivo in
   questa sessione (HTTP 429 diretto, retry su ticker "delisted" nei log
   dell'app reale avviata in parallelo) — non un effetto del codice.
3. **Verifica funzionale end-to-end con dati reali** (niente browser
   disponibile in questo ambiente — l'estensione Claude-in-Chrome non
   risultava connessa, verifica visiva pixel-per-pixel non fatta):
   - App reale avviata (`streamlit run app.py`) con il portafoglio vero:
     **tutte le 11 pagine renderizzano `status=OK`** (Cruscotti e
     Confronto incluse), zero errori/eccezioni nei log, sia al primo
     avvio sia al rerun caldo.
   - `resolve_instrument_benchmark` chiamato dal vivo sui 30 strumenti
     reali aperti: ENRG.MI (EXACT, label ufficiale "STOXX Europe 600
     Energy Screened+ Index", ticker fallback `^GSPE`), ETFMIB.MI (EXACT,
     ticker diretto `FTSEMIB.MI`), BTP-0826 (SISTER via ETF governativo
     `EDMA.MU`), FAM-EMD (COUSIN via `EMB`) — tutti risultati coerenti
     con quanto documentato nelle sessioni precedenti.
   - `ui/form_server/strumenti.py::_render_strumenti_page` renderizzato
     dal vivo per ETFMIB.MI: campo benchmark precompilato `FTSEMIB.MI`,
     badge "Automatico (confidenza: Alta)" — form funzionante con la
     facade.
   - **Non fatto**: conferma visiva vera e propria (screenshot/occhio
     umano) dei grafici Plotly in Cruscotti/Confronto. Consigliato che
     l'utente apra l'app e guardi di persona alla prima occasione,
     nessun segnale di problema trovato nella verifica funzionale.
4. Effetto collaterale del catalogo runtime (autocomplete benchmark parte
   vuoto su un processo fresco, si popola man mano che il motore risolve
   strumenti): **non ancora discusso con l'utente**, resta aperto se
   serve un prewarm esplicito.

**Fase B (Task S + B1-B9) chiusa.** Fasi C (SATOR, ramo automatico) e D
(refresh in background) del piano originale restano da iniziare — non
decise, da confermare alla ripresa.

---

**CHECKPOINT 2026-09-04 (sessione interrotta per riavvio dell'utente, nulla
implementato per la Fase C — solo pianificato)**

L'utente ha notato (uso reale dell'app dopo la Fase B) che l'Esposizione
Bucket in Quotazioni interne/Impostazioni mostra ancora valori vecchi anche
se il benchmark e' gia' aggiornato — **confermato corretto, non un bug**:
Fase C (SATOR) non era ancora stata toccata. L'utente ha chiesto di
procedere e confermato due volte ("si', procedi" e poi "continua con la
fase C").

**Fase C — solo pianificata, ZERO codice toccato in questa sessione.**
Piano completo scritto in `C:\Users\Giuseppe\.claude\plans\glittery-floating-marble.md`
(fuori dal repo, va riletto a mano se serve il dettaglio — non e' nel
worktree). Riassunto di quello che contiene, cosi' che questo file resti
la fonte di verita' anche se quel plan file si perde:

- **Vincolo critico trovato prima di scrivere qualunque dettaglio**:
  `infer_sator_metadata`/`resolve_instrument_bucket_exposure` sono oggi
  funzioni pure, istantanee, offline, chiamate in cicli stretti su TUTTO
  l'universo strumenti (motore di ranking SATOR, editor universo,
  reminder watchlist). `InstrumentAnalysisService.analyze()` fa vere
  chiamate di rete — chiamarlo li' dentro violerebbe la regola non
  negoziabile 1 (niente rerun/attese a sorpresa). **Serve un Task T
  prerequisito**: nuovo metodo `InstrumentAnalysisService.peek_cached(...)`
  che legge SOLO la cache gia' popolata (mai una fetch), fallback
  all'euristica vecchia quando la cache non ha ancora l'istrumento.
- **Task C1** (basso rischio): `resolve_instrument_bucket_exposure`, ramo
  automatico, usa `cds.core_pct/defensive_pct/satellite_pct` reali invece
  di `{_role_bucket(role): 1.0}`, quando `peek_cached()` ha successo.
  `_score_universe` gestisce gia' esposizioni frazionate da tempo (feature
  "Task 1/4 SATOR esposizione frazionata", 2026-08-21) — qui si tratta solo
  di alimentarlo con numeri migliori.
- **Task C2** (rischio maggiore): `infer_sator_metadata`, ramo automatico,
  deriva `nature`/`role`/`confidence` da `InstrumentProfile`
  (structural_type/sector/theme/factor/geography/geo_scope/asset_class)
  invece che da parole chiave nel nome. **Verificato sul codice reale**: i
  ruoli SATOR sono **10** (`SATOR_ROLE_VALUES`), non ~17 come stimato nel
  piano originale — contratto pubblico usato da 2 dropdown UI
  (`ui/form_server/quote_interne.py`, `ui/form_server/strumenti.py`) e
  validato da `apply_classification_override`, deve restare identico. Il
  vocabolario del motore (sector/theme/factor/geo_scope) copre gia' quasi
  1:1 le categorie semantiche dell'euristica attuale (es. sector=healthcare
  -> nature=healthcare/role=satellite_difensivo, gia' oggi). Per i fondi
  (asset_class FND, oggi hardcoded a core_difensivo sempre) si puo' usare
  `profile.asset_mix` reale (gia' presente da Task R) per un bucket vero
  invece di un default fisso — miglioramento reale, non solo migrazione.
- **Task C3** (solo segnalato, non in scope): trovata un'asimmetria
  preesistente (non causata da oggi) — `_score_universe` (sator.py:998)
  calcola la colonna `_bucket` mostrata in tabella SEMPRE da `role` singolo,
  mai dall'esposizione frazionata reale gia' usata per il punteggio. Task
  C1 la rendera' piu' visibile (piu' strumenti con vera esposizione
  frazionata). Da discutere se sistemarla subito dopo o in un giro
  successivo.
- **Task C4**: `core/services/cruscotti.py:213-232` ha una copia
  indipendente e manuale (`_NATURE_TO_BUCKET`/`_NATURE_TO_RADAR_AXIS`,
  commento esplicito nel file: duplicata per evitare un import circolare)
  della classificazione nature->bucket di sator.py, che alimenta il target
  del radar Cruscotti. Cambiare come viene assegnato `nature` (Task C2)
  senza toccare questo file la farebbe disallineare silenziosamente —
  viola la regola non negoziabile 4. Da risolvere con un import locale
  (pattern gia' usato altrove nello stesso file) invece di due dizionari.
- **Rischio test**: `tests/test_infer_sator_metadata_specificity.py` (11
  riferimenti) quasi certamente blocca gli esatti valori ticker/keyword che
  C2 sostituisce — da leggere per intero PRIMA di toccare `infer_sator_metadata`,
  stesso trattamento gia' dato ai test statici di `benchmark_registry.py`
  in Fase B (riscrivere gli assert sul *contenuto* rimosso, preservare
  quelli sul *meccanismo*).

**Prossimo passo alla ripresa**: il piano sopra non e' stato ancora
mostrato/confermato esplicitamente dall'utente (interrotto prima di
poterlo riassumere) — da presentare e fare approvare prima di scrivere
il dettaglio bite-sized e toccare codice, stessa disciplina di Task S/Fase B.

**Piano presentato e APPROVATO dall'utente 2026-09-04 (sessione
successiva)**: "Approvo il piano fase C". Si procede con dettaglio
bite-sized (Task T, C1, C2, C4 — C3 resta solo segnalata) e
implementazione un task alla volta, test + commit separato per task,
stesso ritmo di Task S/Fase B.

**Task T FATTO (2026-09-04, TDD)**: nuovo
`InstrumentAnalysisService.peek_cached(*, ticker, isin) -> InstrumentAnalysis | None`
(`core/instrument_analysis/service.py`) — legge solo `ia_cache`, zero fetch
di rete, `None` su cache assente/scaduta. 4 test nuovi (cache vuota, round
trip identico al cache-hit di `analyze()`, scadenza TTL, nessuna chiamata
agli adapter di rete). Refactor contestuale: `analyze()` ora chiama
`peek_cached()` internamente sul ramo cache-hit invece di duplicare la
ricostruzione (stesso comportamento, elapsed_ms impostato dopo). Suite
completa del repo verde (0 failures).

**Task C1 FATTO (2026-09-04, TDD)**: `resolve_instrument_bucket_exposure`
(`core/services/sator.py`), ramo automatico (dopo il controllo
dell'override manuale, invariato) — se
`_instrument_analysis_service().peek_cached(ticker=..., isin=...)` trova
una entry, usa `{"Core": cds.core_pct/100, "Difensivo": cds.defensive_pct/100,
"Satellite": cds.satellite_pct/100}` invece di `{_role_bucket(role): 1.0}`.
Nuovo singleton lazy `_instrument_analysis_service()` in sator.py, stesso
pattern di `core.benchmark_registry._service()`. 3 test nuovi (esposizione
reale da cache popolata, fallback a cache vuota, override manuale ha
sempre precedenza — mai consulta la cache). **Gap trovato e chiuso in
questa sessione, non pre-esistente**: nessun test del repo isolava la
cache disco `InstrumentAnalysisService` da `tests/conftest.py` (solo i
file dentro `tests/core/instrument_analysis/` lo facevano localmente) —
prima di C1 questo non contava perche' nessun percorso SATOR la
consultava mai; ora che `resolve_instrument_bucket_exposure` la legge,
qualunque test che esercita SATOR (`_score_universe`,
`compute_watchlist_reminders`, `build_sator_universe_editor_frame`, ecc.)
avrebbe silenziosamente potuto leggere `data/cache/instrument_analysis/resolution.json`
reale. Aggiunto fixture autouse globale
`_isolate_instrument_analysis_cache` in `tests/conftest.py` (stesso
principio di `portfolio_test_env` per `persistence.storage`) — chiude il
gap per tutto il repo, non solo per i test nuovi. Suite completa verde (0
failures) dopo l'aggiunta.

**Task C4 FATTO (2026-09-04, TDD)**: nuova costante pubblica
`NATURE_DEFAULT_ROLE` + funzione `nature_bucket(nature) -> str`
(`core/services/sator.py`, subito dopo `_role_bucket`) — stessa
associazione nature->ruolo fissa gia' presente in ogni ramo di
`infer_sator_metadata`, sorgente unica per il bucket di default di una
nature. `core/services/cruscotti.py::_derive_quantitative_radar_target`
non ha piu' la sua copia manuale indipendente `_NATURE_TO_BUCKET` (14
entry, verificate bit-per-bit identiche a `nature_bucket()` prima di
rimuoverla): ora chiama `nature_bucket()` via import locale dentro la
funzione (mai al top del modulo, per lo stesso timore di import circolare
gia' documentato in precedenza — non verificato risolvibile con certezza,
quindi non rischiato). 2 test nuovi in
`tests/test_sator_nature_bucket.py` (tutte le 19 nature vs bucket atteso,
fallback nature sconosciuta -> Satellite). Suite completa verde (0
failures).

**Task C2 FATTO (2026-09-04, TDD)**: `infer_sator_metadata` (`core/services/sator.py`)
ha un nuovo ramo, subito dopo il ramo GOV (invariato) e prima della catena
tk_in()/parole-chiave (invariata, resta il fallback): se
`_instrument_analysis_service().peek_cached(ticker=..., isin=...)` trova
un'analisi, `nature`/`role`/`confidence` vengono derivati da
`InstrumentProfile` via nuova funzione `_nature_role_from_profile()`
invece che dalla catena di keyword. Letto per intero
`tests/test_infer_sator_metadata_specificity.py` (9 test) PRIMA di
toccare la funzione, come da piano: **zero modifiche necessarie** — la
cache InstrumentAnalysis e' isolata/vuota in tutti quei test (fixture
globale gia' aggiunta in Task C1), quindi `peek_cached()` ritorna sempre
`None` li' e la catena keyword originale resta l'unico percorso eseguito,
bit-per-bit invariata.

Mappatura `_nature_role_from_profile()` (nuova, con `_confidence_label()`
per gradare `profile.confidence` in alta/media/bassa sulle stesse soglie
implicite dei 4 segnali di identita', 0.3+0.15/segnale): `structural_type`
GOLD/DIGITAL_ASSET/MONEY_MARKET/{GOV_BOND,AGGREGATE_BOND,
INFLATION_LINKED_BOND,BOND}/COMMODITY mappati 1:1 sui rami equivalenti
della vecchia catena; `sector` healthcare/technology+semiconductor/energy/
real_estate/metals_mining mappati sulle nature dedicate; `theme`
artificial_intelligence/robotics/cybersecurity/digitalisation ->
tecnologia_ai, clean_energy -> energia (estensione ragionata, nessun
branch equivalente esatto nella vecchia catena); `factor` quality ->
quality_factor; `SMALL_CAP_EQUITY`/`EX_MEGA_CAP_EQUITY` ->
azionario_paese_singolo; `EMERGING_BROAD_EQUITY` -> azionario_emergenti;
`SINGLE_COUNTRY_EQUITY`/`COUNTRY_BROAD_EQUITY` -> italia (se
geography=="italy") altrimenti azionario_paese_singolo;
`BROAD_EQUITY`+geo_scope=="global" -> azionario_globale_core. Categoria
FND: **migliorata, non solo migrata** — con `profile.asset_mix` reale
(dominante >=50%) deriva azionario_globale_core/core_globale o
bond_globale/bond dalla composizione vera del fondo, invece del vecchio
default fisso fondo_pac/core_difensivo (usato solo quando asset_mix e'
vuoto, il caso comune per fondi non-Fineco-AM). Ramo GOV resta
prioritario e non consulta mai la cache (un BTP e' sempre
bond_governativo/bond, verificato con test dedicato). Ogni combinazione
non riconosciuta ricade su altro/altro/bassa, stesso fallback totale di
prima — nessun valore inventato.

**Regressione nota e accettata** (non un bug, una scelta esplicita
documentata qui): la nature `difesa_sicurezza` non ha corrispondenza nel
nuovo motore (nessun `theme`/`sector` per "difesa/aerospace" in
`core/instrument_analysis/text_classification.py`) — uno strumento difesa
gia' risolto in cache ricade su "altro" invece che su
"difesa_sicurezza"/satellite_tematico come nella vecchia catena keyword.
Impatto reale: 0 strumenti nel portafoglio attuale (verificato con grep
sui dati reali), quindi non blocca la fase; da eventualmente chiudere con
una futura estensione di `text_classification.py` (fuori scope di questo
task).

18 test nuovi in `tests/test_infer_sator_metadata_from_instrument_analysis.py`
(ogni corrispondenza `structural_type`/`sector`/`factor` sopra, i due casi
FND con/senza asset_mix, GOV-vince-sempre, gradazione confidence, fallback
a cache vuota).

**Confronto onesto sui 30 strumenti reali aperti (26 in stato "aperto"),
come richiesto dal piano** — nature/ruolo vecchio (catena keyword, cache
forzata a `None`) vs nuovo (cache reale, gia' popolata per tutti e 26 dal
replay ufficiale) per ognuno, senza filtrare i casi che peggiorano:
**trovato un bug reale**, non una semplice differenza attesa — XDEB.MI
(`structural_type=FACTOR_MINIMUM_VOLATILITY`, `geo_scope=global`)
regrediva da `azionario_globale_core/core_globale` (vecchio, via keyword
"world"/"global" nel nome) ad `altro/altro` (nuovo): il fallback finale in
`_nature_role_from_profile()` controllava
`structural_type == "BROAD_EQUITY" and geo_scope == "global"` — troppo
stretto, perdeva qualunque altro tipo strutturale equity-like (fattoriale,
tematico non mappato, settoriale non tra i 5 gestiti) con scope globale.
**Corretto**: condizione allargata a `geo_scope == "global" and
structural_type` (qualunque tipo strutturale non vuoto, non solo
BROAD_EQUITY letterale) — un `structural_type` non vuoto significa che la
classificazione testuale ha comunque trovato un segnale equity, quindi
"globale" resta un fallback onesto, stesso comportamento della vecchia
catena keyword. Test di regressione aggiunto
(`test_non_quality_factor_equity_global_still_maps_to_azionario_globale_core`).
Dopo il fix: **4 strumenti cambiati su 26, zero regressioni** — FAM-FLEX
(fondo_pac/core_difensivo -> azionario_globale_core/core_globale, mix
59% equity), FAM-PU6 (-> bond_globale/bond, mix 59% bond), FAM-PU8 (->
azionario_globale_core/core_globale, mix 75% equity) tutti e tre
miglioramenti attesi del ramo FND (asset_mix reale), XGIN.MI (altro ->
bond_globale/bond, INFLATION_LINKED_BOND non riconosciuto dalla vecchia
catena keyword) un miglioramento imprevisto ma corretto. Verificata anche
l'esposizione bucket (Task C1) sugli stessi 26: tutti e 26 ora ricevono
esposizione frazionata reale da cache (prima del progetto: bucket singolo
100% per tutti).

**Verifica funzionale app reale** (stesso rigore di B9/Task S): avviata
`streamlit run app.py` in locale (porta 8765) con il portafoglio vero,
log di avvio puliti (zero errori/traceback), risposta HTTP 200. Verifica
via browser non disponibile in questa sessione (estensione Chrome non
connessa) — sostituita con una verifica diretta piu' rigorosa: chiamata
in-process, sui dati reali, di `resolve_instrument_bucket_exposure`/
`infer_sator_metadata` per tutti i 26 strumenti aperti (vedi confronto
sopra), che e' esattamente la logica dietro il form "Esposizione Bucket".
App chiusa correttamente a fine verifica.

Suite completa del repo verde (0 failures) — 6 run del tentativo, alcuni
interrotti a meta' da un problema d'ambiente/sandbox esterno non
riproducibile (mai una singola failure visibile prima dell'interruzione,
sempre risolto al tentativo successivo, ultima conferma pulita dopo il
fix XDEB.MI).

**Fase C COMPLETA (2026-09-04)**: Task T, C1, C4, C2 tutti fatti e
verificati. Il motore InstrumentAnalysis (Fase A) e' ora collegato
end-to-end a SATOR: esposizione bucket e nature/ruolo per strumento
derivano dal profilo online-first quando la cache e' popolata, con
fallback identico a prima quando non lo e' ancora.

**Task C3 FATTO (2026-09-04, TDD, stessa sessione — l'utente ha chiesto
di riprenderlo dopo aver visto il riepilogo)**: chiusa l'asimmetria
segnalata durante la Fase C originale — `_score_universe` (sator.py)
calcolava la colonna `_bucket` (mostrata in tabella, usata per
`bucket_weight`/`bucket_target`) SEMPRE da `_role_bucket(role)` (bucket
singolo), mai dall'esposizione frazionata reale `_bucket_exposure` (gia'
usata per il punteggio dal Task C1). Nuova funzione pura
`_primary_bucket_from_exposure(exposure, role)` (bucket dominante per
peso, fallback a `_role_bucket` se l'esposizione manca) — da non
confondere con l'omonima quasi-omonima `_dominant_bucket()` gia'
esistente nel file (scopo diverso, allocazione acquisti per deficit euro:
collisione di nome scoperta e risolta rinominando la nuova funzione).
Riprodotto il bug con un caso reale (BOND-SPLIT: role="bond" ->
`_role_bucket` "Difensivo", ma override 60% Core/40% Difensivo -> il
dominante e' Core) prima di correggere. 2 test nuovi in
`tests/test_sator_fractional_exposure_engine.py`. Suite completa verde
(0 failures).

**Fix grafico Overview FATTO (2026-09-04, TDD, stessa sessione — secondo
punto della domanda aperta sotto, primo punto lasciato perdere su
richiesta dell'utente)**: `ui/charts/overview.py::build_overview_time_chart`,
vista "P/L del portafoglio" — la serie "P/L storico" (verde) non somma
piu' `P/L Realizzato Netto` a `pl_attuale`: ora coincide esattamente con
"P/L pos. aperte" (blu tratteggiata), come da modello confermato
dall'utente ("sotto la blu resta in verde perche' sono somme ancora
impegnate"). "Total return" (arancione) resta invariato (colonna "P/L"
del dataframe storico, realizzato+proventi+aperto) — ora e' l'UNICA serie
a mostrare cio' che non e' piu' impegnato, riempiendo "tonexty" dal verde
fino al totale. Effetto collaterale corretto anche il colore di
riempimento del verde (`fillcolor` success/danger): ora segue il segno
del NUOVO valore (`current_open_pl`), non piu' il vecchio `pl_total`
passato dal chiamante (che rappresentava aperto+realizzato, semanticamente
sbagliato per colorare l'area del solo aperto). 3 test nuovi in
`tests/test_overview_pl_storico_matches_open_positions.py`. Nessuna
modifica al primo grafico (Composizione % P/L per Macro-Categoria):
l'utente ha confermato di lasciarlo com'e'.

**CORREZIONE del fix sopra (2026-09-05, sessione successiva)**: l'utente ha
visto il grafico reale e corretto il modello del 04/09 — "hai fatto
coincidere le curve posizioni aperte con p/l storico... non era questo
l'obiettivo, ma ampliare solo la parte in arancione in quanto somme non
investite". Il fix del 04/09 aveva reso "P/L storico" (verde) e "P/L pos.
aperte" (blu) matematicamente identiche punto per punto (`pl_storico =
pl_attuale`), quindi due linee sovrapposte esatte — non era quello che
voleva nonostante la risposta registrata sopra. **Richiesta finale
2026-09-05**: le tre curve tornano alla formula originale (pre-04/09) —
"P/L storico" (verde) = P/L posizioni aperte + P/L Realizzato Netto (torna
a salire sopra la blu ad ogni evento di realizzo), "Total return"
(arancione) = tutto come sempre. **Unico cambiamento reale**: la traccia
blu ("P/L pos. aperte") viene ora aggiunta PRIMA di quella arancione in
`fig.add_trace(...)` (non dopo) — dato che il fill "tonexty" riempie
sempre rispetto alla traccia immediatamente precedente, l'area arancione
ora parte dalla blu invece che dalla verde, quindi ingloba anche il
realizzato netto e non solo i proventi come nella versione originale
pre-04/09 (la verde resta visibile sopra come linea di confine, senza fill
proprio aggiuntivo tra blu e arancione). `fillcolor` del verde torna a
seguire il segno di `pl_total` (non piu' `current_open_pl`), coerente con
la formula ripristinata. Test in
`tests/test_overview_pl_storico_matches_open_positions.py` riscritti di
conseguenza (4 test: formula verde ripristinata, arancione invariato,
ordine tracce/fill blu->arancione, fillcolor coerente con `pl_total`).
Suite completa verde (0 failures) dopo il fix.

**Bug FATTO (2026-09-05): bottoni sidebar (form-server, porta 8502) non
aprivano piu' la scheda** — segnalato dall'utente ("i collegamenti del
sidebar su porta 8502 non funzionano normalmente"). Diagnosi: il
form-server backend rispondeva correttamente (HTTP 200 su tutte le
route), ma `/quote-interne` impiegava **3,3-4,7s** a rispondere, ben oltre
il timeout di 1,2s con cui `_open_form_server_page()` (`ui/sidebar.py`)
sonda la pagina prima di aprire la scheda — quindi il bottone "Quote &
impostazioni" restituiva sempre "non raggiungibile" e non chiamava mai
`webbrowser.open_new_tab()` (confermato nel log applicativo:
`Form server non raggiungibile ... timeout di connessione`, ripetuto ad
ogni avvio). Root cause trovata con `cProfile`:
`InstrumentAnalysisService.peek_cached()` (Fase C) chiama
`load_resolution_cache()` (`core/instrument_analysis/cache.py`) SENZA
alcuna memoizzazione — ogni chiamata rilegge e riparsa da zero l'intero
file JSON della cache di risoluzione da disco. `/quote-interne` itera i
30 strumenti attraverso piu' funzioni SATOR (`compute_instrument_buckets`,
`compute_instrument_quota_status`, `compute_instrument_reference_ranges`,
`compute_instrument_operational_status`, `infer_sator_metadata`,
`resolve_instrument_benchmark`), totalizzando **212 riletture** dello
stesso file in un solo render pagina (1,89s solo per questo). Probabile
causa anche del rallentamento gia' notato sulla tab "Pianificazione"
dell'app principale (~9s a ogni rerun, stessa catena di chiamate SATOR).
**Fix**: `load_resolution_cache()` ora memoizzata in-process per mtime del
file (+ path, per restare corretta con `DATA_DIR` monkeypatchato nei
test) — `save_resolution_cache()` aggiorna direttamente lo stato in
memoria invece di forzare una rilettura. Benchmark isolato: 200 letture
dirette da disco 1,227s -> 200 chiamate memoizzate 0,023s (**53,6x**).
4 test nuovi in `tests/core/instrument_analysis/test_cache.py`
(memoizzazione fra chiamate ripetute, nessuna rilettura dopo save,
rilevamento di una scrittura esterna via mtime). Suite completa verde (0
failures). **Nota**: il fix e' nel codice sorgente ma il processo
Streamlit dell'utente gia' in esecuzione ha ancora il modulo vecchio
caricato in memoria — serve un riavvio dell'app perche' il fix sia
visibile nella sessione live (non ho riavviato l'istanza dell'utente
senza chiederlo, essendo un processo che non ho avviato io in questa
sessione).

**Seguito FATTO (2026-09-05, stessa sessione)**: l'utente ha riavviato
l'app e riprovato — errore identico ("Quote & impostazioni non
disponibile ... timeout di connessione"). Verifica dal vivo sul processo
riavviato (PID nuovo, confermato partito DOPO il commit del fix sopra):
`/quote-interne` e' sceso da 3,3-4,7s a **1,4-1,5s** (il fix della cache
funziona), ma resta comunque sopra il timeout di probe di 1,2s usato da
`_open_form_server_page()` — la pagina fa comunque un calcolo SATOR su
tutti gli strumenti (piu' pesante delle altre 7 route del form-server,
quasi istantanee), quindi resta strutturalmente piu' lenta anche con la
cache InstrumentAnalysis a posto. **Fix aggiuntivo**: timeout di probe
alzato SOLO per la route `quote-interne` (1,2s -> 4,5s,
`_FORM_SERVER_PROBE_TIMEOUT_OVERRIDES` in `ui/sidebar.py`), le altre 7
route restano sul timeout veloce da 1,2s (fail-fast se il servizio e'
davvero giu'). 2 test aggiornati (assert sulla nuova firma
`_probe_form_server_page(url, timeout=probe_timeout)`) + 1 test nuovo in
`tests/test_form_server_startup.py` che verifica il timeout differenziato
per route con `_probe_form_server_page` mockato. Suite completa verde (0
failures). **Stesso avviso di prima**: serve un altro riavvio dell'app
perche' l'utente veda anche questo secondo fix.

**Bug FATTO (2026-09-05): hint "Automatico:" in Esposizione Bucket
mostrava la vecchia assegnazione a bucket singolo** — segnalato
dall'utente ("sotto il nome dello strumento in 'Automatico:' spuntano
altri valori sicuramente legati alla vecchia assegnazione"). Confermato:
`ui/form_server/quote_interne.py` calcolava le caselle editabili
(`current_exp`) con `resolve_instrument_bucket_exposure()` (Task C1,
frazionata reale da InstrumentAnalysis), ma l'hint "Automatico:" sotto il
ticker con un calcolo hand-rolled separato — SOLO `_role_bucket(ruolo)`,
sempre bucket singolo 100%, mai la cache — disallineato dai valori
frazionati mostrati nelle caselle accanto. Fix: estratta
`auto_instrument_bucket_exposure()` (nuova funzione pubblica in
`core/services/sator.py`) come nucleo condiviso — usata sia da
`resolve_instrument_bucket_exposure()` (fallback quando non c'e' override)
sia dall'hint in quote_interne.py, cosi' le due fonti non possono piu'
disallinearsi strutturalmente. **Bug satellite trovato in corsa**: la
prima versione del fix ha rotto 14 test esistenti (`auto_exp[b]` con
subscript diretto va in `KeyError` quando `_role_bucket` risolve un
singolo bucket diverso da quello indicizzato, es. "Satellite" mentre si
accede a "Core") — corretto con `.get(b, 0.0)`, stesso pattern difensivo
gia' usato per `current_exp`. Suite completa verde (0 failures) dopo il
fix. 3 test nuovi in `tests/test_resolve_instrument_bucket_exposure.py`
(auto_instrument_bucket_exposure ignora l'override attivo, fallback su
cache vuota). **Stesso avviso**: serve un riavvio dell'app.

**Investigazione FATTA (2026-09-05): qualita' benchmark in Quotazioni e
SATOR sui dati reali** — l'utente ha segnalato benchmark "che fanno
cagare" (dati mancanti, curve che spuntano dal nulla con pochi punti,
curve assenti per alcuni strumenti) e ha chiesto se C/D/S e benchmark in
SATOR sono gia' stati valutati sui suoi dati reali. Investigazione su 18
strumenti aperti reali (non fixture) - **due problemi distinti,
entrambi confermati**:
1. **Download storico benchmark incompleto** (non assegnazione): in
   `data/cache/portafoglio_benchmark_cache.json`, 63 ticker benchmark
   spaccati in due gruppi — 27 con ~500+ punti (storico da ago/set 2024,
   ~2 anni) e **36 con solo ~135 punti** (storico da fine feb 2026, ~6
   mesi). `_prefetch_benchmark_data()` (`core/dashboard_datasets.py:120`)
   chiede sempre `yf.Ticker(...).history(period="2y")`, ma per il secondo
   gruppo Yahoo/yfinance restituisce sistematicamente solo ~6 mesi (causa
   non ancora isolata, serve debug live — non introdotto in questa
   sessione). Effetto reale: per uno strumento posseduto da piu' di 6
   mesi con benchmark in questo gruppo, la curva "spunta dal nulla" a
   meta' grafico (es. FAM-FLEX 847gg storico proprio vs 136gg benchmark
   ^GSPC; GOLD.MI 827 vs 136; XDWT.MI 827 vs 136).
2. **Assegnazione benchmark sbagliata o assente** (bug reale, distinto):
   **SWDA.MI** (probabile ETF piu' "banale" del portafoglio, iShares Core
   MSCI World) non ha NESSUN benchmark — identita' risolta correttamente
   ma grado `MERCATO_GENERALE` con `operational_series` non scaricabile
   (`^990100-USD-STRD`), e il ticker-di-riserva (Task S) non trova nulla.
   **XMME.MI** (ETF Emergenti, identita' EXACT corretta) riceve **^GSPC**
   (S&P 500 USA) come ticker di riserva invece di un proxy Emergenti vero
   — mentre **EEM** (iShares MSCI Emerging Markets) e' gia' in cache con
   513gg di storico buono. Stesso pattern su FAM-FLEX. Il meccanismo di
   scelta del ticker-di-riserva collassa troppo spesso su ^GSPC come
   proxy generico invece di cercare un proxy piu' specifico gia'
   disponibile. Nessun fix applicato — solo diagnosi, in attesa di
   direzione dell'utente su priorita'.
   SATOR: la validazione Fase C (confronto 26 strumenti, sopra) copre
   SOLO la correttezza di nature/ruolo/bucket% (bucket assegnati sensati
   su un campione reale: XBAE.MI 35/65 Core/Difensivo, GOLD.MI 70/30
   Difensivo/Satellite, ETFMIB.MI 20/80 Core/Satellite) — MAI la UI SATOR
   vera (schermate/tabelle), e i benchmark mostrati in SATOR condividono
   lo stesso `resolve_instrument_benchmark()` quindi hanno gli stessi due
   problemi sopra.

**Bug FATTO (2026-09-05, scelto come priorita' dall'utente tra i due
sopra): download storico benchmark che restava corto per sempre**. Root
cause isolata: `_benchmark_refresh_state()` decideva se rifare il fetch
SOLO guardando quanto e' recente l'ultimo giorno in cache
(`last_valid`), mai quanto indietro arriva la copertura. Un fetch passato
troncato (causa esatta non isolata - probabile transiente lato Yahoo al
primo fetch di questi ticker, non riproducibile ora) restava quindi
"fresco" per sempre: il merge incrementale (`{**existing, **fresh}`)
aggiunge solo i giorni nuovi in avanti, mai quelli mancanti nel passato.
**Verificato dal vivo in sessione** che il download oggi funziona
benissimo per questi stessi ticker: `yf.Ticker("^GSPC").history(period="2y")`
(e altri 5 dal gruppo corto: TLT, URTH, EEM, QQQ, GC=F) hanno restituito
subito 502-504 punti pieni — la cache era stantia, non un limite reale
del download. **Fix**: nuovo controllo di copertura in
`_benchmark_refresh_state()` (`core/dashboard_datasets.py`) — se lo
storico piu' vecchio in cache copre meno di ~18 mesi
(`_BENCHMARK_EXPECTED_COVERAGE_DAYS = 550`, tutti i benchmark usati qui
sono indici/ETF/materie prime con decenni di storico reale, mai
autenticamente cosi' corti), ritenta un fetch pieno — ma solo se
`last_valid` non e' gia' oggi stesso, cosi' un ticker genuinamente
neo-quotato non viene ri-interrogato piu' volte nello stesso giorno. Si
autoripara e si ferma da solo (una volta colmata la copertura, il
controllo non scatta piu'). 7 test nuovi in
`tests/test_benchmark_refresh_coverage.py` (cache vuota, fresca con
copertura piena/corta, stale di 1 giorno con copertura corta/piena,
stale "vera", backfill end-to-end con `yf.Ticker` mockato). Suite
completa verde (0 failures). **Nota**: la cache reale
(`data/cache/portafoglio_benchmark_cache.json`) NON e' stata toccata in
questa sessione — avrebbe richiesto chiamate di rete reali sui dati veri
dell'utente senza chiederglielo prima. Si autoripara al prossimo refresh
quotazioni dopo il riavvio dell'app (i 36 ticker corti torneranno a
copertura piena entro un giorno di utilizzo normale).

**Bug FATTO (2026-09-05, richiesto dall'utente: "risolviamo anche il
secondo problema" — assegnazione sbagliata/assente SWDA.MI/XMME.MI)**:

1. **SWDA.MI senza benchmark**: root cause isolata in
   `core/instrument_analysis/service.py::analyze()` — il profilo risolve
   bene (BROAD_EQUITY/global, ETF), ma `resolve_benchmark()` cade su
   GENERAL_MARKET_FALLBACK con `geometry_score=0`/`coverage_obs=0`:
   l'intera scaletta CUGINA/ZIA/NONNA (`benchmark.py:591-633`) e' gated
   da `if instrument_series:` — se il fetch storico dello strumento
   (`_fetch_own_history_with_retry`, unico input che la abilita) torna
   vuoto per l'intermittenza di rete Yahoo gia' documentata nel codice
   stesso (`_HISTORY_RETRY_DELAY_SECONDS`, "un tentativo fallisce, uno
   riesce"), il ladder non viene nemmeno tentato. `_is_result_worth_caching`
   pero' considerava il risultato "meritevole di cache" solo perche'
   `asset_class` non era "ALTRO" — MAI controllando se il benchmark fosse
   degradato per una causa transitoria — congelando un fallback
   indistinguibile da un blackout di rete per l'intero TTL (14 giorni).
   **Fix**: nuovo parametro `own_history_fetch_failed` tracciato in
   `analyze()` (wrapper attorno al fetch di rete) e passato a
   `_is_result_worth_caching()` — un GENERAL_MARKET_FALLBACK causato da
   fetch fallito non viene piu' cachato (si ritenta al prossimo giro); un
   GENERAL_MARKET_FALLBACK genuino (fetch riuscito, nessun candidato del
   ladder supera la soglia) resta cacheato normalmente, comportamento
   invariato. 2 test nuovi + 5 test esistenti aggiornati (assumevano
   erroneamente che un GENERAL_MARKET_FALLBACK andasse sempre cachato,
   dato che la fixture autouse mockava lo storico proprio sempre vuoto).
2. **XMME.MI con proxy sbagliato (^GSPC invece di un indice Emergenti
   vero)**: root cause in `core/instrument_analysis/reference_families.py`
   — la famiglia `EMERGING_EQUITY` (riga ZIA/AUNT per `geography=
   "emerging"`) aveva solo indici di singolo paese (`^HSI`, `000001.SS`,
   `^BSESN` — Hong Kong/Cina/India), nessun ETF Emergenti diversificato
   reale: nessuno supera la soglia di geometria (40) per un fondo tipo
   XMME.MI, quindi vinceva la riga NONNA/GLOBAL_EQUITY (^GSPC) per
   mancanza di alternative migliori nella riga piu' specifica. Verificato
   con `geometry_score` reale sui dati del portafoglio (parquet storico +
   fetch live yfinance): **EEM 92,89** contro ^GSPC 57,65, ^HSI 18,00,
   000001.SS 41,55, ^BSESN 18,63 — EEM vince nettamente sia per semantica
   che per tracking. **Fix**: aggiunto `EEM` come primo candidato di
   `REFERENCE_FAMILIES["EMERGING_EQUITY"]`. 1 test nuovo (catalogo) +
   verificato che nessun test esistente assume il vecchio contenuto della
   tupla.

**Bug FATTO (2026-09-05, trovato durante l'investigazione sopra, NON
richiesto esplicitamente ma bloccante — perdita dati reale in corso)**:
mentre verificavo il bug SWDA.MI/XMME.MI ho notato che
`data/cache/portafoglio_benchmark_cache.json` era crollato da 63 serie
benchmark a **3** nella sessione live dell'utente. Grep sui log
applicativi (`Cache benchmark salvata: serie=N`) ha confermato il
pattern gia' successo 2 volte prima (17:22 e 19:02 del 2026-09-04,
entrambe autoriparate al giro successivo) e una terza volta questa
mattina (08:38:30) senza autoripararsi. Root cause in
`persistence/storage.py::save_data()`/`save_benchmark_data()`: entrambe
ripiegavano sul contenuto gia' su disco SOLO quando il `benchmark_data`
del chiamante era COMPLETAMENTE vuoto, mai quando era solo PARZIALE (non
vuoto ma con meno ticker di quelli gia' persistiti) — un chiamante con
una vista parziale della cache (probabile: un thread di prewarming/
render in background con un proprio snapshot di `data` non ancora
sincronizzato con gli altri 60 ticker scritti nel frattempo da altri
render) sovrascriveva l'INTERA cache con i pochi ticker che conosceva,
azzerando silenziosamente tutti gli altri. **Fix**: nuova
`_merged_benchmark_cache_payload()` condivisa da entrambe le funzioni —
unisce SEMPRE il `benchmark_data`/`market_live_data` del chiamante con
quanto gia' persistito su disco (il chiamante vince per i ticker che
conosce, tutti gli altri restano). 1 test esistente aggiornato (asseriva
il vecchio comportamento di sostituzione totale come atteso) + 1 test
nuovo con 60 ticker pre-esistenti + 2 nuovi da un chiamante parziale,
verifica che tutti e 62 sopravvivano. Suite completa verde (0 failures).
**Nota**: la causa esatta di QUALE thread/chiamante avesse la vista
parziale non e' stata isolata (probabile scheduler `benchmark_
scheduler_start`/prewarming con uno snapshot di `data` non aggiornato,
ma non confermato con un log dedicato) — il fix e' comunque corretto e
completo indipendentemente dalla causa esatta, perche' rende
`save_benchmark_data`/`save_data` sicure per costruzione sotto QUALUNQUE
scrittore con vista parziale, non solo quello osservato. La cache reale
(gia' ridotta a 3 serie da questo bug PRIMA del fix) si ripopolera'
gradualmente navigando l'app dopo il riavvio, non e' stata toccata
direttamente in questa sessione. **Stesso avviso**: serve un altro
riavvio dell'app per tutti e tre i fix di questo giro.

**Bug FATTO (2026-09-05, segnalato dall'utente come urgente: "SATOR non
disponibile ... SystemExit: 1 ... questa cosa va assolutamente
risolta!")**: root cause isolata nei log applicativi —
`start_form_server()` (`ui/form_server/__init__.py`) falliva a ripetizione
per 13+ minuti filati (08:53-09:06) con "porta 8502 non disponibile
(SystemExit: 1)", MENTRE una richiesta diretta alla stessa porta nello
stesso momento rispondeva regolarmente (200 su `/sator`, verificato dal
vivo). Causa: `start_form_server()` controllava SOLO la variabile locale
al modulo `_server_thread` per capire se il server fosse gia' attivo — un
hot-reload di Streamlit (reimport di questo modulo dopo una modifica a un
file .py nel repo, innescato dalle mie stesse modifiche al codice in
questa sessione mentre l'app dell'utente era in esecuzione con
file-watching attivo, il normale comportamento di `streamlit run` in
sviluppo) azzera quella variabile pur lasciando vivo il thread uvicorn
precedente, ancora in ascolto sulla porta. Il solo probe di rete di
backup (`_probe_existing_form_server`, timeout 0,35s) puo' fallire per un
semplice ritardo sotto carico, facendo scattare un secondo bind sulla
porta gia' occupata dal thread orfano -> `SystemExit(1)`. Lo scheduler
gemello `start_benchmark_scheduler`
(`core/infrastructure/schedule.py`) ha gia' questa stessa protezione
("funziona anche dopo hot-reload di Streamlit... i thread preesistenti
restano vivi con lo stesso nome") — `start_form_server` non ce l'aveva.
**Fix**: stesso pattern — cerca un thread vivo di nome
"PortafoglioFormServer" in `threading.enumerate()` PRIMA del probe di
rete, e si riaggancia direttamente se lo trova (nessun nuovo bind
tentato). 1 test nuovo in `tests/test_form_server_startup.py` (thread
orfano simulato, verifica che ne riaggancia lo stato senza tentare
`_probe_existing_form_server`/`_build_fastapi_app`). Suite completa
verde (0 failures). **Nota**: la causa scatenante specifica di QUESTA
sessione (i miei stessi edit al codice mentre l'app era in esecuzione)
non si ripetera' nell'uso normale dell'utente da solo, ma la
vulnerabilita' di fondo (nessuna protezione da hot-reload) era reale e
gia' presente prima di questa sessione — qualunque modifica futura al
codice con l'app attiva l'avrebbe potuta far scattare di nuovo. Stesso
avviso: serve un riavvio dell'app.

**Fase D — dettaglio bite-sized scritto e approvato 2026-09-04** (stessa
sessione), due decisioni di scope prese dall'utente via domanda diretta:
(1) scheduler background **disattivato di default**, come Mercati; (2) il
vecchio D3 (stato UI "in fase di risoluzione") **non serve** — verificato
che C1/C2 gia' ricadono sull'euristica vecchia quando la cache manca,
regola non negoziabile 9 gia' soddisfatta, nessuna nuova UI. Dettaglio
completo in `docs/superpowers/plans/2026-09-01-instrument-analysis-cds-benchmark.md`,
sezione "Fase D".

**Task D1 FATTO (2026-09-04, TDD)**: nuovo modulo
`core/infrastructure/instrument_analysis_auto_refresh.py`, stesso
scheletro di `core/infrastructure/market_auto_refresh.py` (thread daemon
singleton, file di stato JSON separato
`instrument_analysis_auto_refresh_state.json`). `_refresh_once()` itera
`data["strumenti"]`, per ognuno controlla
`InstrumentAnalysisService().peek_cached(...)` — se `None`, chiama
`resolve_instrument_benchmark(item, master_entry=...)` (riusa la
funzione gia' esistente invece di duplicare la chiamata ad `analyze()`:
gia' applica l'override manuale, calcola `duration_years` per i BTP, e
popola l'intera cache — profilo+CDS+benchmark insieme — come
side-effect). Cap `max_instruments_per_cycle` (default 20) per non
bloccare un ciclo su un universo grande (`analyze()` puo' costare fino a
8s/strumento). Riusa `should_refresh_market_auto` (logica pura, generica,
non vale la pena duplicarla per un solo altro chiamante). 8 test nuovi in
`tests/test_instrument_analysis_auto_refresh.py` (impostazioni
default/clamping, skip su cache-hit, resolve su cache-miss, cap
rispettato, fallimento per-ticker non blocca gli altri, "fresh" quando
non ancora dovuto, "disabled" non tocca mai dati/rete). Mai una vera
chiamata di rete nei test (service e `resolve_instrument_benchmark`
sempre mockati).

**Task D2 FATTO (2026-09-04)**: wiring in `app.py` (nuovo blocco
`INSTRUMENT ANALYSIS AUTO-REFRESH SCHEDULER`, copia 1:1 dello stile del
blocco Mercati, stessa guardia `PORTFOLIO_TESTING`) e in
`ui/pages/impostazioni.py` (nuova sezione "Profili strumenti
(InstrumentAnalysis)" nel form Impostazioni: checkbox "Aggiorna profili
strumenti in background" + intervallo minuti, salvati sotto
`settings["instrument_analysis_auto_refresh"]`, stesso stile del blocco
"Aggiornamento Mercati"). **Nessun pulsante manuale "Aggiorna"** in
questo giro (semplificazione concordata con l'utente: il primo giro del
thread fa gia' da prewarm iniziale). Verificato con
`test_all_standard_tabs_render_and_end_on_last_page` (rendering completo
di tutti i tab, incluso Impostazioni, verde) e con avvio reale
dell'app (`streamlit run app.py`, log puliti, HTTP 200, scheduler
correttamente inattivo di default — nessuna chiamata di rete spuria).

**Fase D COMPLETA (2026-09-04)**. Suite completa del repo verde (0
failures) dopo ogni commit. Con questo si chiude l'intero arco di lavoro
InstrumentAnalysis pianificato (Fasi A, E, B, C, D) — il motore online-first
e' ora completamente collegato: benchmark (Fase B), esposizione
bucket/nature/ruolo SATOR (Fase C), refresh automatico in background
opzionale (Fase D). Nessun prossimo passo pianificato al momento: eventuali
estensioni (Fase D con pulsante manuale, gap residui della Fase A come il
ladder CUGINA/ZIA/NONNA o `difesa_sicurezza` nel motore nuovo) restano
note aperte, da riprendere solo su richiesta esplicita dell'utente.

---

**Due domande aperte dello stesso utente, indipendenti dalla Fase C, NON
Fase C, NON InstrumentAnalysis — solo spiegazione, nessuna modifica fatta**:

1. **Grafico "Composizione % del Profit/Loss per Macro-Categoria"** (Home,
   `ui/charts/home.py::build_portfolio_pl_category_chart`): l'utente ha
   notato che GOV mostrava 10,6% con un P/L di -130,00€ e non gli tornava.
   Spiegato e verificato con dati reali (03/09/2026): la percentuale e'
   calcolata sul valore assoluto di ogni categoria diviso la somma dei
   valori assoluti (1.223,39€, non il P/L netto reale di 963,39€) — quindi
   il "100%" del grafico e' un totale lordo gonfiato (127% del netto), non
   il risultato netto vero. L'utente ha fatto notare correttamente che
   questo e' concettualmente sbagliato per un grafico "composizione del
   P/L": la scomposizione corretta (percentuale con segno sul P/L netto
   del giorno, es. GOV = -13,5% invece di +10,6%) e' stata proposta e
   verificata con numeri reali, ma **l'utente ha detto "lasciamo perdere
   per ora"** — nessuna modifica fatta, resta un miglioramento noto e
   proposto per quando vorra' riprenderlo.
2. **Grafico Overview (Home), serie "P/L pos. aperte" (blu tratteggiata)
   vs "P/L storico" (verde) vs "Total return" (arancione)**
   (`ui/charts/overview.py:130-179`): l'utente si aspetta che il verde
   stia SOTTO la linea blu tratteggiata e che l'arancione rappresenti la
   parte mancante (proventi gia' incassati, non impegnati). Verificato con
   dati reali (04/09/2026): oggi invece blu(963,39) < verde(2.527,76) <
   arancione(2.895,25) — verde = P/L posizioni aperte + P/L realizzato
   netto (854 righe di storico, un solo evento di realizzo reale, rimborso
   BTP-0826 il 01/08/2026, +1.564,37€ — non un bug di dati piatti,
   verificato), arancione = verde + proventi (367,49€). La parte
   sull'arancione ("soldi gia' incassati e non impegnati") gia' corrisponde
   a cosa fa il codice oggi. La parte sul verde/blu **non torna con la
   logica attuale** (verde somma un guadagno gia' incassato al P/L aperto,
   quindi sale sopra, non scende sotto) — chiesto all'utente di spiegare
   che modello si aspetta per la linea verde.
   **Risposta ricevuta 2026-09-04 (sessione successiva)**: il verde deve
   restare aderente alla blu (rappresenta capitale ancora impegnato in
   posizioni aperte, quindi verde = P/L posizioni aperte, coincide con blu
   invece di sommarci sopra il realizzato). Tutto cio' che non e' piu'
   impegnato — proventi incassati (367,49€) **+** P/L realizzato netto dal
   rimborso BTP (1.564,37€), totale 1.931,86€ — va in arancione, sopra la
   blu (arancione finale invariato: 2.895,25€, cambia solo quale segmento
   lo compone).
   **IMPLEMENTATO 2026-09-04** (stessa sessione, dopo la chiusura della
   Fase C): vedi sezione sopra "Fix grafico Overview FATTO".

---

(Nota di processo, valida per tutte le decisioni future su questo
progetto: **ogni decisione di priorita' va scritta qui**, nello stesso
momento in cui viene presa dall'utente, non solo nel piano gitignored o
nel ledger SDD effimero — vedi il punto sopra su come si e' persa
l'ultima volta.)

### Punto della situazione al 2026-08-21 — fronte SATOR/Purchase Optimizer
(indipendente dal punto sopra, ancora valido)

**Appena chiuso**: sotto-progetto 5/"10bis" (vedi sezione 3) — Purchase
Optimizer con esposizione frazionata reale (voce 10, ultima della sequenza
1-10) + 4 problemi UI/integrazione segnalati dall'utente rivedendo il
lavoro dei sotto-progetti 1-4. Eseguito con `subagent-driven-development`
in un worktree isolato (`.worktrees/sator-purchase-optimizer-frazionato`,
gia' ripulito), 9 task + un'ondata di fix dalla review finale, mersato in
`main` e **pushato su GitHub** (era da 121 commit che non succedeva:
policy del progetto e' "mai push senza richiesta esplicita", corretto ma
va sempre detto chiaramente quando un commit resta solo locale).

**Subito dopo, stesso giorno**: giro di feedback diretto dell'utente dopo
aver visto le schede nuove in uso (con screenshot allegati ogni volta),
tutto gia' corretto e pushato:
- tabella "Target & Stato" ricostruita come vera `<table>` (era rimasta a
  `<div>` flessibili disallineate, mai convertita quando il CSS e' stato
  unificato nel Task 6 del sotto-progetto 5);
- valore automatico (ruolo/benchmark/esposizione bucket) ora **sempre**
  visibile, non solo quando diverge — l'utente lo vuole come riferimento
  fisso anche dopo piu' modifiche manuali successive;
- benchmark ticker + etichetta accoppiati: quando il ticker scelto e' nel
  catalogo, l'etichetta si auto-compila via JS e diventa sola lettura
  (impossibile disallinearli);
- scheda "Impostazioni" separata da "Target & Stato" (ora scheda propria,
  la n.2), Ruolo & Benchmark ed Esposizione Bucket spostate a n.3/n.4;
- pulsanti "Salva" con margine sopra E sotto (un primo fix aveva messo
  solo sopra, corretto su segnalazione);
- tabella "Stato attuale" e sezione "Come funziona il calcolo interno"
  ristilizzate (classe CSS mancante nella prima, paragrafo unico
  trasformato in righe strutturate nella seconda).

Tutti questi fix sono in `ui/form_server/quote_interne.py`, commit
separati, suite completa verificata verde ad ogni passo, tutto pushato.

**Aperto, non deciso, non urgente**:
- decisione di design su NO_SELL (esclude oggi l'intero ranking SATOR, non
  solo i nuovi acquisti — vedi sezione 5, "Priorita 9", punto 2). Nessun
  dato reale lo usa oggi, dormiente.
- finestra di backfill automatico dello storico prezzi: e' emerso
  parlando del rientro da un'assenza di una settimana che il backfill
  automatico (via bottone "Aggiorna Quotazioni") copre solo ~7 giorni
  indietro (query Yahoo `range=7d`) — al limite per un'assenza di
  esattamente una settimana. Proposto di allargarla (es. 10-14 giorni),
  **utente non ha ancora deciso**, nessuna modifica fatta.

**Prossimo passo**: l'utente sara' fuori una settimana e vuole provare la
parte numerica con test funzionali propri al ritorno — nessuna azione
autonoma richiesta nel frattempo. Alla ripresa: aspettarsi feedback su
calcoli/comportamento funzionale (non piu' solo grafica), e ricordare la
decisione aperta sul backfill se l'utente la solleva di nuovo.

### Cronologia precedente (fase cache/render, superata)

Il lavoro precedente su questo punto era il tuning delle pagine pesanti
(Cruscotti, poi Quotazioni/Portafoglio) dentro la governance cache gia'
definita, senza selector/radio/render differiti — chiuso da tempo, non e'
piu' il fronte attivo. Lasciato qui solo come riferimento storico:
wrapper Plotly idempotente e key automatiche stabili per run era l'ultimo
tuning UI applicato in quella fase; nessuna modifica performance va mai
marcata come risolta senza confronto prima/dopo.
