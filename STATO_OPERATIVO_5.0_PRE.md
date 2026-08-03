# Stato operativo 5.0-pre

Questo e' il documento unico da leggere per riprendere il lavoro sulla copia
`5.0-pre` senza perdere il filo.

Documenti visibili in root:

- `README.md`: avvio rapido e orientamento repository.
- `CHANGELOG.md`: diario storico delle modifiche.
- `STATO_OPERATIVO_5.0_PRE.md`: questo documento, fonte operativa principale.

Documenti separati dal percorso ordinario:

- `docs/progetti/ROADMAP_AI_FINANZA_LIBRO.md`: progetto separato ispirato al
  libro, non prioritario nel percorso ordinario.
- `docs/fonti/PYTHON-per-l'AI-e-la-Finanza.pdf`: fonte PDF del progetto libro.

Gli altri documenti di piano/analisi sono stati archiviati in
`docs/archivio_5_0/`. Restano consultabili, ma non sono la fonte primaria se in
contrasto con questo file:

- `docs/archivio_5_0/REGOLE_NON_NEGOZIABILI.md`: vincoli da non violare.
- `docs/archivio_5_0/ARCHITETTURA_5.0.md`: principi modulari e finanziari.
- `docs/archivio_5_0/PROTOCOLLO_PERFORMANCE_5.0.md`: metodo per interventi su
  tempi/cache/render.
- `docs/archivio_5_0/CACHE_STRATEGY_5.0.md`,
  `docs/archivio_5_0/PIANO_UNICO_CACHE_RENDER_5.0.md`,
  `docs/archivio_5_0/CACHE_INVENTORY_5.0.md`: dettagli tecnici cache.
- `docs/archivio_5_0/CHIUSURA_FASE_CACHE_5.0.md`: chiusura del solo pilota
  registry/page-cache L3, non della cache unica applicativa.
- `docs/archivio_5_0/CACHE_UNICA_5.0_MIGRAZIONE_DEFINITIVA.md`: piano corretto
  e vincolante per portare tutte le cache residue sotto un unico contratto.
- `docs/archivio_5_0/RIPRESA_ORCHESTRAZIONE_CACHE_2026-08-03.md`: punto di
  ripresa operativo della fase cache sospesa, con stato reale, completato,
  residui e primo comando da eseguire alla ripartenza.
- `docs/archivio_5_0/RENDER_BASELINE_2026-08-02.md`: baseline performance
  storica.

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

- Creati i documenti guida `REGOLE_NON_NEGOZIABILI.md` e
  `ARCHITETTURA_5.0.md`.
- Riordinata la documentazione: root ridotta ai documenti vivi, piani e analisi
  storiche spostati in `docs/archivio_5_0/`.
- Ripulita `data/portfolio`: lasciati solo i file operativi, backup manuali e
  snapshot storici spostati in `data/forensic/portfolio/`.
- Fissata la centralita' di modularita', tema unico, formule finanziarie nel
  core, impostazioni grafici centralizzate e dataset condivisi prima della UI.
- Creati `PROTOCOLLO_PERFORMANCE_5.0.md`,
  `PIANO_UNICO_CACHE_RENDER_5.0.md`, `CACHE_STRATEGY_5.0.md` e
  `CACHE_INVENTORY_5.0.md`.
- Aggiunto `tools/perf_render_log_analyzer.py` come base per leggere i render
  log in modo ripetibile.

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

- Consolidare il dataset rischio/rendimento strumenti in un servizio unico.
- Migrare gradualmente Cruscotti, Quotazioni e poi SATOR verso quel servizio.
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

Ordine consigliato, non urgente:

1. SATOR Frontier.
2. Monte Carlo Portafoglio.
3. Mappa AI strumenti / clustering.
4. Explainability SATOR.
5. Storico decisionale con valutazione ex-post.

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
