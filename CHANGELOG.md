# Changelog

Tutte le modifiche rilevanti di Sestante, per versione. Il formato segue [Keep a Changelog](https://keepachangelog.com/it/1.1.0/), con le sezioni Aggiunto, Modificato, Corretto, Rimosso. Ogni voce occupa una riga e descrive l'effetto per l'utente; diagnosi, cause e file toccati sono nel diario (`docs/diario/`).

Questo file è stato riscritto in forma sintetica il 02/11/2026. Il testo integrale precedente è in [`docs/changelog/5.x-dettaglio.md`](docs/changelog/5.x-dettaglio.md); le versioni 4.x sono in [`docs/changelog/4.x.md`](docs/changelog/4.x.md). Le date sono quelle registrate nello stato operativo; dove mancano, lo si indica.

## [Non rilasciato]

### Modificato
- Portafoglio, grafico «P/L per Categoria»: linea dello zero marcata (2,5 px, scura, sopra le aree impilate).
- Dipendenze: yfinance 1.7.0 → 1.8.0, che non usa più `inplace=True` e non emette più i `Pandas4Warning` con pandas 3.1.

### Aggiunto
- Benchmark, tabelle «Benchmark scelto dal web» e «Strumenti e benchmark»: colonna «Modifica» con la data (gg/mm) per gli strumenti il cui benchmark è stato sostituito negli ultimi 3 giorni, letta dalla storia delle assegnazioni; il benchmark precedente è nel dettaglio dello strumento.
- Strumento `tools/realign_weekly_benchmarks.py` (dry-run di default, backup prima di scrivere, idempotente): porta al venerdì le barre settimanali salvate con la data del lunedì e ripristina i prezzi sovrascritti dai backup.

### Corretto
- Dati, avvio: se il file del portafoglio è illeggibile (o manca ma i backup contengono dati) l'app si ferma con un messaggio e non crea più un portafoglio vuoto al suo posto; i backup con dati non vengono più eliminati dalla rotazione; un salvataggio senza alcun evento sopra un portafoglio con molti eventi viene rifiutato.
- Benchmark, tabelle «Strumenti e benchmark» e «Benchmark scelto dal web»: larghezze delle colonne applicate senza scroll orizzontale (prima erano tutte uguali e il testo lungo veniva troncato), righe ordinate per categoria nell'ordine delle impostazioni, «Benchmark scelto dal web» con ticker e categoria colorati come l'altra tabella e colonna «Ptf» (- in portafoglio, ★ candidato, ☆ osservato) come in Quotazioni, colonna «Stato» sostituita da una riga sotto la tabella quando ci sono serie ferme, intestazioni «Correl.» e «Scost.annuo%», date come gg/mm, nomi con «&» mostrati correttamente (comparivano come «&amp;»).
- Benchmark, correlazione e tracking error nella matrice «Strumenti e benchmark»: erano molto bassi (0,1–0,3) perché le barre settimanali di Yahoo portavano la data del lunedì con la chiusura del venerdì (sfalsamento di quattro giorni) e i rendimenti erano confrontati giorno per giorno con una serie che si muove una volta a settimana. Ora si misurano sui rendimenti settimanali, gli stessi con cui il benchmark è stato scelto.
- Benchmark, scaricamento prezzi: barre giornaliere al posto di quelle settimanali, che sovrascrivevano i prezzi del lunedì nelle serie già giornaliere.
- Benchmark, serie ferme da più di 10 giorni: non spariscono più dai grafici, dal benchmark di portafoglio e dalla matrice; restano disegnate con la data dell'ultimo dato in legenda («· dati al gg/mm») e un avviso nella pagina. Il messaggio «Componenti non disponibili» ora compare solo se manca davvero lo storico.
- Benchmark, pulsanti «Ricalcola la scelta di tutti» e «Aggiorna i prezzi dei benchmark scelti»: il risultato indica i riferimenti di portafoglio e il motivo di ogni richiesta non riuscita; una scelta non salvata (serie non scaricata) non è più contata come riuscita; ogni passo scrive nel log.
- Benchmark, «Aggiorna i prezzi dei benchmark scelti»: aggiorna anche i riferimenti del benchmark di portafoglio, che prima restavano fermi e facevano comparire «Componenti non disponibili in SQLite» dopo 10 giorni.
- Benchmark, pannello «Benchmark scelto dal web»: lo stato «Dati non aggiornati» e la colonna «aggiornato al» leggono l'ultimo prezzo in archivio e non la data fotografata alla scelta.
- Quotazioni, grafici per strumento: la linea del benchmark torna dopo un aggiornamento dei dati; la firma della figura ignorava il benchmark quando le componenti erano un elenco di dizionari e la cache serviva la figura vecchia senza la linea.

## [5.7] — 2026-11-05

### Aggiunto
- Operazioni: riga di sintesi (operazioni, acquistato, vendite e rimborsi, cedole e dividendi, costi e imposte, liquidità; anno in corso e da sempre) e cronologia unica al posto delle due tabelle, per mese, con filtri per tipo e periodo, ricerca, totali che seguono i filtri, dettaglio per riga ed esportazione CSV, tutto nel browser senza ricaricare la pagina; il versamento che copre un acquisto è mostrato nella riga dell'acquisto.
- Summary, archivio report: griglia con un report per riga (data, periodo in italiano, contenuti, valore e P/L, dimensione), anteprima in popup con apertura in una nuova scheda, pulsante di download accanto all'anteprima e «Riprendi», eliminazione con conferma; i report oltre l'ottavo in un pannello a parte.
- Backup: ogni copia include ora storico prezzi e decisioni SATOR, ha un manifest con controllo di integrità (dimensioni sempre, hash su richiesta) e il ripristino li riporta entrambi. La chiave API dell'AI resta esclusa dai backup.
- Dati: riquadro «Salute dei dati» in cima con le poche azioni da fare (cosa, dove) e KPI «Ultimo backup»; la tabella qualità ha la colonna «Posizione» (In portafoglio, Chiuso/Rimborsato con data, Candidato, Osservato).
- Setup: riga di sintesi con benchmark di portafoglio, uso della rete, categorie attive e preset di visibilità.
- Popup della tabella Portafoglio: grafico del valore della posizione sotto quello del prezzo (costo tratteggiato, area verde/rossa, frecce verso l'alto sugli acquisti); grafici e mini-sparkline («90g») su 90 giorni (erano 60); cascata del risultato (P/L aperto, realizzato, cedole, totale) e peso sul portafoglio ad anello con contributo a 90 giorni.
- Popup della tabella Quotazioni: grafico a 30 giorni (erano 12) con la tabella letture sugli ultimi 10; riepilogo del periodo (variazione, massimo, minimo, distanza dal picco, posizione nel range) e cerchi vuoti per i giorni senza lettura.
- Benchmark scelto dal web per ogni strumento (ETF proxy etichettati, scelta manuale prioritaria, pannello «perché questo benchmark»), ricalcolo solo su comando; benchmark di portafoglio con riferimenti cercati dallo stesso algoritmo.
- Controllo automatico esteso: blocca ogni elenco di simboli di mercato e le vecchie scale.

### Modificato
- Sidebar: al posto del titolo «⚙️ Gestione» c'è il logo Sestante (versione compatta in `static/sestante_logo_sidebar.png`) con la versione piccola accanto.
- Margini superiori ridotti: il logo ora parte subito sotto la barra di Streamlit (circa 80 px in meno; la causa erano cinque elementi vuoti di CSS e script iniettati prima dell'intestazione, ciascuno con 16 px di spazio); barra e intestazione della sidebar più basse (la barra resta visibile).
- Dati: ordine nuovo (stato e integrità, backup, qualità strumenti, import quotazioni, poi, in fondo, cache, log, diagnostica e bonifica); inventario file dai percorsi reali con data di modifica; la bonifica avanzata crea un backup automatico, mostra l'anteprima dei record e si sblocca scrivendo la categoria.
- Setup: «Aggiornamenti automatici in rete» raccoglie benchmark, Mercati e profili strumenti in un solo riquadro; le opzioni avanzate sono in un pannello chiuso; tolti i selettori disabilitati di valuta, locale e formati; soglie degli avvisi con «0 = spenta» nell'etichetta; test connessione AI senza risposta grezza.
- Pianificazione: pulsante «🔄 Ricalcola SATOR con i prezzi attuali» sopra il piano di ribilanciamento; ricalcolo sincrono, senza «dati precedenti».
- SATOR (ranking, ribilanciamento, mappa, frontiera) non si ricalcola più a ogni «Aggiorna quotazioni»: la firma ignora prezzi live e ultimo giorno di storico; si ricalcola con nuove operazioni, un nuovo giorno di storico o impostazioni SATOR.
- Modello Gemini predefinito `gemini-3.6-flash` (il 3.5 è deprecato e instradato al 3.6); testo di aiuto del modello aggiornato.
- Pagina AI: nuova scheda «Test benchmark», prova su richiesta che chiede a Gemini in una sola chiamata il benchmark ufficiale degli strumenti in portafoglio (solo ticker, ISIN, nome, tipo; risultato non salvato).
- Attivare il log dei tempi, l'avanzamento tecnico o il livello log nelle Impostazioni non ricostruisce più Summary, Cruscotti e figure: queste opzioni non entrano più nelle firme delle cache.
- Pianificazione: i candidati al rinforzo di un bucket (quote reali SATOR) non si ricalcolano più a ogni rerun; rerun a caldo da ~6–9 s a ~3,5–4,5 s (AppTest).
- Avvio a freddo da ~20–23 s a ~11–12 s e rerun a caldo da ~13–15 s a ~6–9 s (misure su AppTest): archivio SQLite dei benchmark senza riaperture di connessione, firma dei dati stabile tra processi (le figure per strumento non si ricostruiscono più a ogni avvio), cache di risoluzione degli strumenti letta una volta per run.
- SATOR in Pianificazione dopo un cambio di prezzi: piano di ribilanciamento, mappa strumenti e frontiera mostrano l'ultimo risultato con l'avviso «dati precedenti, calcolati alle HH:MM» mentre si ricalcolano (ADR-0023).
- Aggiornamento automatico dei profili strumenti spento di default; backup automatici dell'aggiornamento quotazioni al massimo ogni 30 minuti; storico prezzi riscritto solo se cambia.
- Cache figure: al massimo 3 varianti per figura; «Spesa mensile per acquisto strumenti» non si ricostruisce più all'aggiornamento prezzi.
- L'aggiornamento giornaliero dei prezzi benchmark (18:00) è spento di default e si attiva da Impostazioni → Benchmark.
- L'archivio SQLite è il registro dei benchmark: una serie va registrata prima di essere usata ([ADR-0022](docs/adr/0022-archivio-registro-dei-benchmark-e-isolamento-test.md)).
- Analisi strumento: il benchmark è scelto con lo stesso algoritmo di scoperta.
- Opzioni del benchmark personalizzato dalle serie in archivio.
- Documentazione riorganizzata: stato corrente, backlog, ADR, diario mensile, architettura, sviluppo e archivio separati (vedi `docs/README.md`).

### Corretto
- Dati: gli strumenti chiusi o rimborsati non generano più avvisi (prezzo mancante, storico corto, cedola) né «azioni da fare» nella tabella qualità; gli strumenti solo osservati (mai movimentati) sono un'informazione, non un avviso.

### Rimosso
- Dati: «Reset pagina» della cache grafici (elenco pagine superato, spesso senza effetto).
- Scale per famiglia, tabelle per strumento, catalogo fisso di indici e ETF, curva sovrana BCE e vecchio pannello «Dove intervenire».
- Script di diagnostica monouso `tools/diagnose_home_delta.py` e `tools/diagnose_xirr_change.py` e il logo inutilizzato `assets/sestante_logo_header.png`.

## [Benchmark 5.6] — 2026-11-02

Pacchetto di aggiornamento del solo modulo Benchmark, installabile direttamente dalla base 5.4. Non modifica `APP_VERSION` (vedi ADR-0015).

### Aggiunto
- Gestione manuale degli storici per tutti gli strumenti: CSV, XLSX, tabella incollata e singola osservazione, con anteprima di duplicati e conflitti, conferma delle correzioni, esportazione, audit e annullamento.
- Storici di indici censiti e dei cambi EUR/USD, EUR/GBP, EUR/JPY, EUR/CHF archiviati in `data/indices/benchmarks.sqlite3`.
- Installer con `-DryRun`, verifica degli hash della base, backup e script di ripristino.

### Modificato
- Pagina Cruscotti → Benchmark riordinata: KPI, grafici, matrice «Strumenti e benchmark», approfondimento, «Dove intervenire» compatto e gestione degli storici.
- Diagnosi che distingue parentela economica, storico assente, dato obsoleto, origine non verificata e confronto sospeso, indicando conseguenza e azione disponibile.
- <strumento>: indice ufficiale identificato in `BU3XALCT`; storico acquisibile solo manualmente da fonte legittima.

### Limiti noti
- Verificati solo 13 test mirati e la prova di installazione e ripristino. Suite completa, collaudo su Windows, prestazioni e coerenza economica dei benchmark sono ancora da verificare (BM-01…BM-08).

## [5.5] — 2026-10-31

### Aggiunto
- Termometro del portafoglio con gli indicatori Serie, Ultimi 12 mesi, Volatilità recente e Nel mese.
- Pulsante sidebar «Versioni librerie».

### Modificato
- Dipendenze aggiornate: streamlit 1.66.1, pandas 3.1.0, pydantic 2.14.2, numpy 2.5.4.
- `.streamlit/config.toml` versionato; resta escluso solo `secrets.toml`.
- Etichette inclinate o verticali nel Waterfall con più di 8 o 14 barre; intestazione con righe di pari larghezza.

### Corretto
- I test non creano più backup fittizi che, per effetto della retention, eliminavano backup reali.

## [5.4] — 2026-10-14

### Aggiunto
- Pulsante «Lista della spesa» (CSV) su ogni fotografia dello storico SATOR.
- Tetti di retention centralizzati in `core/volume_policy.py`; pulizia degli artefatti di pagina e dei file di cache orfani.

### Corretto
- Con la Modalità Privacy attiva, capitale versato, capitale rientrato e curva storica escludono gli strumenti nascosti.

## [5.3] — 2026-10-07

### Aggiunto
- Valore del PMC sull'asse Y dei popup strumento in Portafoglio e Quotazioni.

## [5.2] — 2026-10-07

### Aggiunto
- Asse Y con minimo e massimo in euro e collegamento alla fonte nei popup strumento di Portafoglio.

### Corretto
- La firma della cache considera il contenuto del registro eventi: le modifiche a rimborsi, imposte e cedole aggiornano Posizioni chiuse e KPI.

## [5.1] — data di rilascio non registrata (interventi tra il 2026-09-21 e il 2026-10-07)

### Modificato
- Cache condivisa per il motore SATOR: Pianificazione da circa 10,8 s a pochi millisecondi quando SATOR non cambia.
- Dipendenze aggiornate: streamlit 1.64, plotly 7.1, yfinance 1.7.

### Corretto
- Il grafico «P/L per Categoria» ad aree impilate non taglia più la cima della pila.
- «Ripara buchi nello storico» non interroga più Yahoo per BTP e fondi non risolvibili.

## [5.0] — 2026-09-08 (tag `v5.0`)

Prima versione stabile della serie 5, al termine della maturazione 5.0-pre e della revisione `/code-review ultra`. Le voci del CHANGELOG precedente registrate sotto «5.0» dopo il tag (9-21 settembre) sono riportate qui come interventi successivi.

### Aggiunto (dopo il tag)
- Ribilanciamento in Pianificazione, riscritto in v2: ogni strumento visibile, badge grafici, alternativa per asset class, simulatore di capitale.
- «Candidato all'acquisto» per gli strumenti osservati in Quotazioni.
- Conferma delle cedole maturate; badge NEW e badge SATOR in Portafoglio.

### Corretto (dopo il tag)
- Timeout della porta 8502 causato da salvataggi completi su operazioni leggere.
- BTP bloccati al 62% di completezza dell'arricchimento anagrafico.
- Storico prezzi Yahoo troncato, dati benchmark contaminati da test, 4 grafici del report non funzionanti, unità errata in Monte Carlo.
- Grafico «Composizione % del P/L per Macro-Categoria» con andamento fuorviante.
- Strumenti con esposizione su più bucket proposti due volte nel ribilanciamento (2026-09-21).

## [5.0-pre] — agosto – 2026-09-08

Ciclo di maturazione dalla base stabile 4.9.40. Sintesi per area; il dettaglio di ogni voce è in `docs/changelog/5.x-dettaglio.md`.

### Aggiunto
- Governo unico della cache: registro, orchestratore, page-cache L3 e 26 provider registrati su 27.
- Revisione del modello di classificazione e allocazione (sotto-progetti 1-5): arricchimento unificato, esposizione frazionata ai bucket, target strategico e NO_SELL, motore SATOR e Purchase Optimizer frazionati.
- Motore centrale InstrumentAnalysis (classificazione, C/D/S, benchmark) collegato a benchmark registry e SATOR, con refresh in background.
- SATOR Frontier, Monte Carlo del portafoglio, Mappa strumenti, explainability del voto SATOR.
- Editor delle quote target per strumento; allocazione del budget SATOR per deficit di bucket.
- Confronto strumenti in Pianificazione.
- Grafico allocazione a barre, lista della spesa CSV, benchmark auto-correttivo in Quotazioni.

### Modificato
- Gestione unificata degli strumenti chiusi e coerenza dei KPI.
- Consolidamento delle formule di rendimento e del dataset rischio/rendimento usato da SATOR.

### Corretto
- 13 criticità emerse dalla revisione critica dell'intero applicativo (dati, SATOR, Analitica, obbligazioni).
- Due bug critici di perdita dati introdotti dal merge concorrente, individuati con `/code-review ultra`.
- Date dei fine settimana nello storico del portafoglio, P/L fantasma, matrici di correlazione, BTP.
- Audit difensivo dei chart builder: 24 funzioni corrette su 9 file.

## Versioni 4.x

Da 4.5 a 4.9.40: vedi [`docs/changelog/4.x.md`](docs/changelog/4.x.md).
