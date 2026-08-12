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
