# Changelog

## 5.0 - Conferma cedole maturate, badge NEW e badge SATOR in Portafoglio

Tre richieste dell'utente via brainstorming, sulla stessa colonna icone
già usata per i badge BTP in tabella Controvalore.

- **[Cruscotti/Portafoglio] Conferma cedola incassata in un click**: nuova
  `cedole_maturate_da_registrare()` (simmetrica a `matured_unredeemed_gov`)
  segnala in Home le cedole BTP con stato "incassata" nel calendario senza
  un evento CEDOLA reale registrato. Un bottone apre `/operazioni` già
  precompilato (ticker/data/importo lordo); la scrittura resta un click
  esplicito dell'utente sul form esistente, nessuna scrittura automatica.
- **[Portafoglio] Badge "N" per acquisti recenti**: visibile 5 giorni
  dall'ultimo evento ACQUISTO registrato per il ticker, rinforzi di
  posizioni già aperte inclusi. Bug reale trovato e corretto in giornata:
  la prima versione guardava il *primo* acquisto in assoluto
  (`first_purchase_date`), quindi un rinforzo su una posizione aperta da
  mesi non faceva mai comparire il badge — corretto con la nuova
  `most_recent_purchase_date()`.
- **[Portafoglio] Badge "S" per candidati SATOR**: segnala gli strumenti
  presenti nell'ultima fotografia SATOR salvata (stessa fonte già usata
  da Pianificazione). Si azzera per l'intera foto al primo acquisto
  successivo registrato, non per singolo ticker.

## 5.0 - Timeout porta 8502 e BTP bloccati al 62% di arricchimento

Due problemi reali segnalati dall'utente in uso normale.

- **[Critico] Timeout "Porta 8502" nel form-server (Strumenti, SATOR,
  Privacy, ecc.)**: `save_data()` riscrive sempre anche l'intero storico
  prezzi (JSON+gzip+Parquet) — misurato 5,35s su dati reali (31
  strumenti, 871 giorni), anche per un salvataggio che non tocca lo
  storico per niente. Il form-server e' un unico processo async condiviso
  da tutte le route: un salvataggio da 5s+ stallava anche le altre pagine
  contro un timeout di probe di 1,2s. Aggiunto `include_storico=False`
  a tutte le 9 azioni di `ui/form_server/strumenti.py` che non toccano
  `storico_prezzi` (arricchimento, import PDF, modifica manuale,
  classificazione SATOR, bucket exposure, toggle candidato/osservazione
  prezzo, aggiunta strumento) — scese a 0,36s. Le 4 azioni che toccano
  davvero lo storico (recupera/elimina storico, elimina strumento,
  rinomina ticker) restano invariate.
- **[Strumenti] BTP bloccati al 62% di arricchimento, senza modo di
  capire perché**: il calcolo di completezza controllava un campo
  (`cedola_annuale`) mai scritto da nessuna parte dell'app — il motore di
  calcolo cedole (`core/domain/bonds.py`) usa solo `cedola_perc`.
  Verificato sulla pagina reale di Borsa Italiana: "rating emittente" non
  è dato per singolo BTP (rimosso dai campi richiesti); "Struttura Bond"
  e "Tasso Cedola su base Annua" sono presenti ma non venivano scraped
  nei campi giusti. Un BTP arricchito automaticamente ora arriva al 100%
  reale. Aggiunta anche una lista campo-per-campo (✓/✗ + come ottenere
  ciò che manca) nella scheda Arricchimento di Strumenti, per tutti i
  tipi di strumento.

## 5.0 - Nuovo: "Candidato all'acquisto" per gli strumenti osservati in Quotazioni

Richiesta dell'utente: tra gli strumenti osservati (mai acquistati) in
Quotazioni, poter evidenziare quelli passati da semplice osservazione a
priorità d'acquisto.

- **[Strumenti]** Nuovo flag `candidato_acquisto` per strumento, attivabile
  dal tab "✏️ Modifica" (nuova mini tabella "Candidati all'acquisto" in
  cima, un bottone ☆/★ per riga) — stesso meccanismo già usato per
  "Osservazione prezzo" sugli strumenti chiusi.
- **[Quotazioni]** La colonna "Ptf" della tabella "Ultime quotazioni
  aggiornate" è diventata la colonna Candidato: intestazione ★☆, celle
  "-" (già in portafoglio) / ★ (candidato) / ☆ (osservato semplice),
  sfondo riga azzurro tenue per i candidati. Ordinamento di apertura:
  in portafoglio, poi candidati, poi osservati semplici. Stessa icona
  ★/☆ anche nel titolo dei grafici storico quotazioni per singolo
  strumento.
- **[Cache]** Aggiunto `candidato_acquisto` alla firma dati condivisa
  (`core/cache_signatures.py::_normalized_instrument_signature_payload`,
  la stessa già estesa in passato per "natura" e i campi cedola BTP):
  senza, attivare/disattivare un candidato non avrebbe invalidato la
  cache del grafico per-ticker.

## 5.0 - Grafico "Composizione % del P/L per Macro-Categoria" raccontava una storia falsa

Segnalato dall'utente in uso normale: il grafico mostrava GOV al 31,9% di
"composizione" nello stesso giorno in cui GOV era in perdita di circa 500€.

- **[Portafoglio] Segno del P/L perso nel grafico di composizione**: la
  percentuale di ogni categoria era calcolata sul valore assoluto sia al
  numeratore che al denominatore, quindi una categoria in perdita veniva
  impilata verso l'alto esattamente come una in guadagno — il "100%" del
  grafico era un totale lordo che nascondeva completamente il segno. La
  percentuale resta normalizzata sul totale assoluto del giorno (somma
  sempre 100% in valore assoluto, nessuna instabilità), ma ora il segno
  decide la posizione nello stack: perdita sotto la linea dello zero,
  guadagno sopra. Range Y reso dinamico invece di fisso a ±100% (tracce
  invisibili comunicano al motore di scala condiviso l'estensione reale
  dello stack positivo/negativo di ogni giorno, non solo il valore di ogni
  singola categoria) ed etichette di fine linea distanziate quando si
  sovrappongono, calibrate sul range dell'asse realmente visualizzato
  (non sul solo ultimo giorno, che poteva sottostimare lo spazio
  necessario e far sovrapporre due etichette adiacenti). Linea dello zero
  resa piu' marcata, visto che ora e' lo spartiacque guadagno/perdita e
  non piu' decorativa.

## 5.0 - Storico prezzi Yahoo troncato, dati benchmark contaminati da test, 4 grafici rotti nel report, unità sbagliata in Monte Carlo, confronto strumenti in Pianificazione

Round di bug reali segnalati dall'utente in uso normale (non una review sistematica).

- **[Critico] Arricchimento storico prezzi Yahoo troncato a poche decine di
  punti**: la Chart API di Yahoo, per `range=max`, restituisce lato server
  una serie sotto-campionata invece dello storico giornaliero pieno (66
  punti invece di 2400+ su alcuni ETC). Corretto usando timestamp Unix
  (`period1`/`period2`) come fa `yfinance` internamente, invece della
  stringa `range=`. Storico esteso sui 4 strumenti coinvolti.
- **[Critico] Dati di benchmark contaminati da fixture di test**
  (`bench_IWDA.AS`, `bench_^GSPE`, `bench_SUB.OK`): due test senza
  isolamento dei path scrivevano dati sintetici direttamente nella cache
  benchmark reale ad ogni esecuzione della suite. Isolati con monkeypatch,
  cache reale ripulita.
- **[Report Summary] 4 grafici rotti**: il benchmark contaminato faceva
  esplodere l'asse Y di "Andamento TWR proxy"; l'asse X forzato al periodo
  intero rompeva "Rendimento annuale" (grafico a barre, coercizione
  silenziosa di anni in date) e non ricalcolava l'asse Y di "Drawdown";
  etichette sovrapposte in "Distribuzione P/L". Bump di versione della
  cache del report, perché la firma non includeva mai il codice del
  generatore e continuava a servire l'HTML vecchio.
- **[Analitica] Monte Carlo**: l'asse mostrava i giorni di trading grezzi
  della simulazione (126/252/378 per 6/12/18 mesi) invece dei giorni di
  calendario attesi (180/360/540); rietichettato nell'equivalente di
  calendario senza toccare la metodologia di simulazione. Corretta anche
  una sovrapposizione titolo/etichette.
- **[Pianificazione] Confronto strumenti poco utile con "Origini
  allineate"**: il periodo scelto (1M/3M/6M...) veniva ignorato in quella
  modalità, mostrando sempre tutto lo storico. Ora il periodo tronca ogni
  strumento alle sue ultime N; con un periodo definito le date restano di
  calendario reale (uno strumento con meno storico appare sfalsato sulla
  porzione recente condivisa, non forzato a sovrapporsi dall'inizio); con
  "Tutto" resta l'indice sintetico Giorno 0.

## 5.0 - Prima versione stabile

Chiude il ciclo di sviluppo 5.0-pre. Le voci sotto (dalla ristrutturazione
SATOR post stress-test in poi) documentano il lavoro dell'ultimo giorno di
questo ciclo: review "avvocato del diavolo" estesa a tutto l'applicativo,
audit del motore finanziario con esecuzione reale, prima navigazione
dal vivo per un audit di usabilità, e infine `/code-review ultra` - che
ha trovato e permesso di correggere due bug critici di perdita dati
introdotti dalla correzione di persistenza della stessa giornata, prima
che potessero mai toccare dati reali. Changelog completo delle versioni
precedenti (4.9.40 e a scendere) in `CHANGELOG_ARCHIVE.md`.

## 5.0-pre - /code-review ultra: corretti due bug critici di perdita dati introdotti dal fix di persistenza di oggi, più 4 rifiniture SATOR

Prima esecuzione di `/code-review ultra` sul lavoro di oggi. Ha trovato,
tra gli altri, due bug seri **causati proprio dal merge a 3 vie introdotto
poche ore prima nella stessa sessione** per proteggere da perdite di dati
- la correzione più delicata della giornata aveva un suo proprio bug.

- **[Critico] Modalità Privacy + il nuovo merge potevano cancellare per
  sempre gli strumenti nascosti da disco** e sovrascrivere il ticker reale
  dei loro eventi collegati con il segnaposto privacy. La vista filtrata
  per la Modalità Privacy non deve mai raggiungere una scrittura reale (il
  suo stesso contratto lo dichiarava da tempo, ma nessun controllo lo
  faceva rispettare): ora `save_data()` rifiuta esplicitamente qualunque
  dato marcato come filtrato per privacy, invece di limitarsi a
  documentare la regola.
- **[Critico] Un file dati corrotto o illeggibile per un errore di I/O
  transitorio veniva trattato come "tutto cancellato da un altro
  processo"**, azzerando quasi per intero strumenti/eventi/anagrafica ad
  ogni salvataggio successivo - l'esatto opposto della rete di sicurezza
  che il merge doveva introdurre. Ora un file esistente ma non leggibile
  in modo affidabile blocca il merge e scrive comunque i dati del
  chiamante, senza mai presumere una cancellazione.
- **SATOR**: l'indicatore "quanto target manca ancora" sovrastimava il
  progresso lasciato indietro quando solo una parte delle righe proposte
  per lo stesso bucket veniva saltata (mostrava l'intero miglioramento del
  bucket anche per una sola riga su tre); corretto uno scambio di bucket
  nel calcolo del miglioramento cumulativo che poteva usare per errore i
  numeri di un bucket diverso da quello giusto; rimossa una chiamata
  duplicata nel motore di acquisto a blocchi per budget grandi.

Tutti i fix verificati con nuovi test di regressione mirati e con la
suite di test locale completa: nessuna regressione.

## 5.0-pre - Chiusura dei punti aperti verso la 5.0 definitiva: decisione SATOR, badge freschezza, audit difensivo grafici

- **Decisione definitiva su SATOR**: il routing per esposizione maggioritaria
  tra bucket (`_dominant_bucket`) resta il comportamento voluto - non più un
  limite aperto in attesa di conferma. Un tentativo di correzione precedente
  reintroduceva un bug più grave e frequente già risolto (Task V-ter);
  semplicità e prevedibilità già validate sui dati reali battono un fix
  rischioso per un caso limite mai osservato.
- **Corretta un'incoerenza cromatica in Quotazioni**: il badge "Ultimo
  refresh" diventava rosso dopo 60 minuti, lo stesso colore usato per
  "Errori" nella stessa schermata - risultato: 29/29 letture OK ma badge
  comunque rosso, leggibile come un problema. Ora arancione, coerente con
  "Warning" nella stessa schermata; il rosso resta riservato a errori reali.
- Aggiunta una nota esplicativa alle card XIRR/TWR proxy in Cruscotti: può
  divergere dal P/L semplice su periodi brevi, prima non spiegato.
- **Audit difensivo sistematico dei chart builder** (`ui/charts/`): 10
  moduli senza copertura dedicata verificati uno per uno con esecuzione
  reale su input degeneri (None, DataFrame vuoto, colonne mancanti).
  Trovato e corretto un vero gap: `build_btp_calendar_figure` sollevava
  `KeyError` su un DataFrame non vuoto ma privo delle colonne richieste
  (stessa classe del `KeyError: 'Data'` già risolto in passato altrove) -
  ora restituisce una figura vuota come tutti gli altri builder. Gli altri
  9 moduli erano già correttamente guardati. Aggiunti 5 nuovi file di test
  di regressione seguendo la convenzione esistente del progetto.

Verificato con la suite di test locale completa (258+ file): nessuna
regressione.

## 5.0-pre - Review avvocato-del-diavolo su tutto l'applicativo: corretti 13 problemi reali (dati, SATOR, Analitica, obbligazioni)

Round di correzioni su 13 criticità trovate con una review "avvocato del
diavolo" estesa a tutto l'applicativo (non solo SATOR): motore
finanziario, cache/persistenza, benchmark/classificazione strumenti,
servizi Cruscotti/Analitica, form-server/mutazione dati, pagine UI.

- **Corretta una possibile perdita silenziosa di operazioni/strumenti**:
  `save_data()` scriveva `strumenti`/`registro_eventi`/`instrument_master`
  senza mai confrontarli con quanto già su disco - se aggiornavi le
  quotazioni dalla sidebar (richiede alcuni secondi) mentre inserivi
  un'operazione dal form-server, l'operazione appena salvata poteva
  sparire al salvataggio successivo della sessione principale. Aggiunto
  un merge a 3 vie (stesso principio già in uso per i dati benchmark):
  un elemento aggiunto da un altro processo non va più perso, una
  cancellazione esplicita resta comunque rispettata.
- **I backup automatici prima di ogni salvataggio sono ora davvero attivi
  di default**: il default reale era disattivato, in contraddizione con
  la documentazione interna del progetto.
- **Cancellare un acquisto auto-liquidato ora cancella anche il
  versamento di cassa collegato** (e viceversa), invece di lasciarlo
  orfano nel registro a gonfiare la liquidità disponibile. Corretta anche
  la sincronizzazione: modificare il versamento direttamente non lascia
  più il trade collegato disallineato. Sistemato anche l'ordine
  cronologico acquisto/versamento nel registro eventi (il versamento che
  finanzia un acquisto ora precede sempre l'acquisto stesso).
- **SATOR**: corretto il meccanismo di recupero del budget per i bucket
  "a secco" (nessun candidato comprabile con la propria fetta), che con
  l'allocazione bucket-first non scattava quasi mai; un ruolo impostato
  manualmente su uno strumento non classificato ora incide davvero sul
  gruppo di confronto invece di essere ignorato; l'indicatore "quanto
  target manca ancora" ora riflette l'effetto combinato di più righe
  d'acquisto nello stesso bucket, non la somma di effetti isolati che
  sottostimava il progresso reale.
- **Monte Carlo (Analitica)**: quando la simulazione esclude strumenti
  nuovi o con quotazioni frammentate, il punto "Oggi" del grafico ora lo
  dichiara esplicitamente invece di mostrare un controvalore ridotto
  senza spiegazione, leggibile come un errore di dati.
- **L'avviso "Peso dominante" ora rispetta una soglia di concentrazione
  più bassa impostata da te** in Impostazioni, invece di restare sempre
  ancorato a un pavimento fisso del 18% quando gli "Alert attivi" sono
  spenti.
- **Overview**: corretto un caso in cui il riquadro "Andamento
  dell'ultima giornata" mostrava una percentuale di segno opposto al
  colore (un miglioramento del P/L visualizzato come percentuale
  negativa in verde) quando il P/L del giorno precedente era negativo.
- **Obbligazioni**: la scadenza di un BTP non viene più letta male quando
  il nome combina un tasso a due decimali con un formato data senza
  giorno esplicito (es. "3,45% AG2029" non è più interpretato come
  2045); il calendario cedole, quando mancano tutti i riferimenti
  temporali dello strumento, si ancora ora alla scadenza reale invece
  che alla data odierna.
- Rimane un limite noto e non ancora risolto in SATOR: uno strumento con
  esposizione divisa tra bucket viene sempre instradato al bucket della
  propria maggioranza, anche quando un bucket minoritario a cui
  appartiene ha un deficit molto più grave - correggerlo richiederebbe
  ribaltare una scelta di design già presa e testata in precedenza (Task
  V-ter), quindi non è stato toccato senza una decisione esplicita.
- **Corretta una didascalia disallineata in Pianificazione**: il testo
  sopra il grafico "Allocazione: bucket e strumenti" descriveva ancora il
  vecchio doppio anello ("Anello interno/esterno"), mai aggiornato quando
  il grafico è stato sostituito da barre orizzontali in una sessione
  precedente - trovato navigando l'app dal vivo, non solo leggendo il
  codice.
- **Motore finanziario verificato con esecuzione reale, non solo lettura
  del codice**: XIRR, TWR, CAGR, volatilità/Sharpe, drawdown massimo, PMC
  e P&L realizzato, aliquote fiscali - ogni formula testata su scenari
  con valore atteso calcolato indipendentemente (mai copiando la logica
  del codice stesso). Nessun errore trovato.

Verificato con l'intera suite di test locale (258 file) dopo ogni
correzione e di nuovo con tutte le modifiche insieme: nessuna
regressione.

## 5.0-pre - Pulsante "Riavvia sessione app" spostato in sidebar, colori del grafico P/L Overview scambiati

- **"Riavvia sessione app" spostato dalla scheda Dati (era sotto un
  expander) direttamente in sidebar**, sempre visibile accanto ad "Arresta
  Streamlit": ricarica dati, benchmark, artefatti pagina e cache interna
  con un solo click, senza chiudere il terminale.
- Nel grafico "P/L del portafoglio" di Overview, gli stili delle linee
  "P/L storico" e "P/L pos. aperte" sono stati scambiati (la prima è ora
  la tratteggiata blu, la seconda la piena verde) su richiesta esplicita
  dell'utente - i dati rappresentati restano invariati.

## 5.0-pre - Ristrutturazione motore SATOR, grafico Allocazione a barre, lista della spesa CSV, benchmark auto-correttivo su Quotazioni

- **La cache dei grafici di Quotazioni non si aggiornava mai quando cambiava
  solo il benchmark**: una riparazione dei dati benchmark restava invisibile
  a schermo perche' la firma della cache dipendeva solo dai prezzi dello
  strumento, mai dal benchmark disegnato nello stesso grafico. Corretto -
  ora la figura si ricostruisce ogni volta che il benchmark del ticker
  cambia davvero.
- Aggiunta una guardia contro le curve "fantasma": una serie benchmark
  momentaneamente piatta non viene piu' normalizzata e salvata per sempre
  nella figura (prima produceva una linea invisibile, sovrapposta al
  riferimento a 100, ma con voce in legenda).
- **Passaggio automatico e visibile a un benchmark alternativo quando la
  fonte originale smette di pubblicare dati** (verificato dal vivo su due
  casi reali: ENRG.MI passa a `^GSPC` quando `^GSPE` risulta fermo da
  settimane, XDBC.MI passa a `^SPGSCI` quando `^BCOM` risulta "possibly
  delisted" su Yahoo Finance) - mai un ETF proxy, solo alternative gia'
  presenti nel catalogo ufficiale del motore di risoluzione, e solo se
  quell'alternativa e' a sua volta viva.
- Il benchmark di uno strumento con una posizione riaperta di recente ora
  copre sempre l'intero storico visibile (prima si vedeva solo dalla data
  di riapertura, invisibile su un grafico di anni) e resta ancorato a 100
  proprio sulla data di acquisto, come la curva dello strumento.
- **Rimosso il selettore "Severita' concentrazione" da SATOR**: verificato
  con uno sweep su 8 budget molto diversi (300-80.000 EUR) che le 4 opzioni
  producevano decisioni di acquisto identiche o quasi sempre nella pratica.
- **I budget grandi non restavano piu' inutilizzati**: un budget di
  500.000 EUR spendeva solo il 57% anche col tetto per riga al massimo
  (il vero limite era il numero di righe, non il tetto) - ora arriva al
  100% quando esistono abbastanza candidati validi, senza mai comprare
  qualcosa che peggiori l'obiettivo di portafoglio dichiarato.
- Aggiunta una batteria di stress-test SATOR qualitativi (non solo "il
  motore non si rompe mai", ma "le proposte hanno senso finanziario"):
  la distanza dall'obiettivo Core/Difensivo/Satellite deve sempre
  diminuire dopo un acquisto suggerito, nessuna riga finanziata con un
  punteggio scandalosamente basso, un rendimento recente estremo non deve
  far vincere uno strumento sul suo punteggio di momentum.
- **Riparato un dato benchmark corrotto** (`IWDA.AS`, usato dal benchmark
  "Blend automatico" di Cruscotti): 5 soli punti in cache con un valore di
  999 al posto di un prezzo reale (~127) - causava rendimenti aggregati
  fuori scala (centinaia di punti percentuali). Aggiunta anche una
  scansione di integrita' su tutte le altre serie benchmark in cache,
  nessun'altra anomalia trovata.
- **SATOR: uno strumento posseduto solo in parte da un bucket non vinceva
  piu' l'intera fetta di quel bucket a torto**: uno strumento con anche
  solo il 20-30% di esposizione sul bucket piu' carente veniva instradato
  per intero nella sua fetta di budget, anche se per il resto apparteneva
  a un altro bucket - vince ora sempre il bucket della propria esposizione
  maggioritaria, non piu' il bucket col deficit assoluto piu' grande.
- **SATOR: "obbligazionario globale" si divide ora in tre gruppi di
  confronto distinti** (governativo a breve duration, aggregato globale,
  inflation-linked): un governativo breve come EM13.MI non spariva dalla
  classifica per voto basso, ma perche' competeva sempre - e perdeva -
  contro un Global Aggregate Bond, una funzione di portafoglio diversa.
- Corretto un congelamento permanente di gruppo/etichetta trovato su 13
  strumenti reali del portafoglio: un valore salvato in passato
  dall'editor universo SATOR restava bloccato per sempre anche dopo un
  miglioramento della logica di classificazione sottostante - ora
  ricalcolato sempre da ruolo e natura correnti.
- Un ETF a fattore minimum-volatility/low-beta (es. XDEB.MI) non viene piu'
  etichettato genericamente "core azionario globale", evitando che
  competa impropriamente con un vero core market-cap-weighted.
- **SATOR: il tetto "Max linee ordine" e' ora rispettato davvero anche con
  l'allocazione bucket-first attiva** (prima veniva ignorato in quel
  percorso: 1.500 EUR/severita' alta/3 linee restituiva 13 righe) - la
  ripartizione delle righe tra bucket viene scelta congiuntamente per
  massimizzare la spesa complessiva entro il tetto, invece che bucket per
  bucket in sequenza.
- Con budget grandi, un secondo giro di acquisto versa ora il residuo
  anche sulle righe gia' aperte quando restano comunque utili rispetto
  all'obiettivo, invece di fermarsi non appena la quota marginale singola
  scende sotto la soglia minima.
- **Il pallino di ruolo in tabella SATOR mostra ora la ripartizione reale**:
  uno strumento con esposizione divisa tra bucket (es. 40% Core/60%
  Satellite) e' rappresentato da una mini-barra segmentata proporzionale,
  non piu' da un pallino pieno sul solo bucket dominante.
- **Grafico "Allocazione" di Pianificazione ricostruito da zero**:
  sostituito il doppio anello (giudicato "confuso", poi "totalmente
  inesatto") con barre orizzontali impilate, una per bucket, segmentate
  per strumento - rappresenta correttamente uno strumento con esposizione
  frazionata su piu' bucket, prima sparso su fette scollegate dello stesso
  anello esterno. Nella tabella di dettaglio sotto il grafico, uno
  strumento diviso mostra ora tra parentesi la propria ripartizione
  percentuale Core/Difensivo/Satellite.
- **Aggiunta la colonna ISIN e un pulsante "Scarica lista della spesa
  (CSV)"** alla fotografia SATOR salvata in Pianificazione: ticker, ISIN,
  nome, bucket, quote, prezzo presunto e importo, pronti per la ricerca e
  l'inserimento ordine sul sito della banca.
- **La simulazione Monte Carlo di Analitica non si blocca piu' per colpa
  di pochi strumenti con quotazioni frammentate**: vengono esclusi in modo
  automatico e minimale (uno alla volta, solo quanto basta), con una nota
  esplicita sotto il grafico su quali e perche'.
- **Gestione Dati**: il pulsante "Svuota cache" ripulisce ora anche gli
  artefatti di pagina (i bundle di Quotazioni con benchmark), non solo i
  file grafici. Aggiunto un nuovo pulsante "Riavvia sessione app" che
  ricarica dati, benchmark e cache interna con un solo click, senza
  chiudere il terminale - causa individuata: un componente interno dell'app
  sopravvive all'aggiornamento a caldo del codice in sviluppo e restava
  agganciato alla versione del codice con cui era partito.

## 5.0-pre - Benchmark sempre garantiti, stop perdita dati cache, fix accesso sidebar

- **Ogni strumento posseduto ha ora un benchmark di riferimento** anche
  quando non si trova una corrispondenza diretta verificata: quando la
  qualita' del confronto non e' valutabile (storico dello strumento
  indisponibile, o nessun candidato supera la soglia di somiglianza), il
  motore offre comunque il ticker scaricabile piu' specifico del catalogo
  di famiglie (es. EEM per un fondo Emergenti, non il generico S&P 500),
  senza bisogno di rete. Le voci gia' in cache senza alcun riferimento si
  autoriparano alla prima lettura, non serve aspettare la scadenza
  naturale (14 giorni). Verificato sui dati reali: da 3 strumenti
  posseduti su 30 senza alcun grafico di riferimento a 0/30.
- Corretti due casi reali di assegnazione benchmark scadente: uno
  strumento azionario globale che non trovava piu' nulla dopo
  un'intermittenza di rete transitoria (ora torna a risolvere il nome
  ufficiale con un confronto verificato), un fondo Mercati Emergenti che
  riceveva l'indice USA come proxy invece di un indice Emergenti vero.
- L'esposizione automatica per bucket (Core/Difensivo/Satellite) mostrata
  come riferimento accanto ai valori modificabili ora usa la stessa fonte
  frazionata reale delle caselle sopra, invece di un'euristica separata
  che mostrava sempre un bucket unico al 100% anche quando lo strumento
  aveva gia' un'esposizione mista nota.
- Le curve storiche dei benchmark che restavano bloccate a ~6 mesi invece
  dei ~2 anni attesi (causa: un fetch passato incompleto restava
  "fresco" per sempre) ora si autoriparano al primo refresh utile.
- **Corretta una perdita di dati reale**: la cache dei benchmark poteva
  essere azzerata da 60+ serie a poche unita' quando un processo in
  background aveva solo una vista parziale della cache al momento del
  salvataggio. Ora ogni scrittura unisce sempre col contenuto gia' su
  disco invece di sostituirlo.
- Sistemato l'avvio del servizio locale che alimenta i bottoni della
  sidebar (Strumenti, Operazioni, SATOR, Quote & impostazioni...): dopo
  una modifica al codice con l'app in esecuzione poteva restare "smarrito"
  pur essendo ancora raggiungibile, mostrando un errore fuorviante.
  Timeout di controllo alzato per le pagine piu' pesanti da calcolare.
- La cache di risoluzione InstrumentAnalysis (profili/benchmark per
  strumento) e' ora tenuta in memoria tra chiamate ripetute invece di
  essere riletta da disco ogni volta (fino a 50x piu' veloce sulle pagine
  che la consultano per ogni strumento del portafoglio).

## 5.0-pre - Fase C+D: SATOR collegato a InstrumentAnalysisService, refresh automatico in background

- SATOR (esposizione bucket, nature/ruolo per strumento) non usa piu' solo
  la vecchia euristica per keyword sul ticker: quando la cache
  InstrumentAnalysis e' popolata per uno strumento, esposizione bucket
  frazionata, nature e ruolo derivano dal profilo online-first (Fase A);
  fallback identico a prima quando la cache non c'e' ancora. Nuovo
  `peek_cached()` sul service per leggere la cache senza mai fare rete
  (Task T), cosi' SATOR non paga mai il costo di un'analisi live.
- Fix reale trovato nel confronto vecchio/nuovo sui 26 strumenti aperti
  del portafoglio: uno strumento a fattore/tematico con `geo_scope=global`
  (es. XDEB.MI, `FACTOR_MINIMUM_VOLATILITY`) regrediva ad "altro/altro"
  perche' il fallback finale controllava solo
  `structural_type == "BROAD_EQUITY"`. Allargato a qualunque
  `structural_type` non vuoto con scope globale. Dopo il fix: 4 strumenti
  su 26 cambiati, zero regressioni.
- Fix asimmetria: la colonna "bucket" mostrata in tabella (usata per
  `bucket_weight`/`bucket_target`) veniva ancora calcolata dal ruolo
  singolo anche per strumenti con esposizione frazionata reale (es. 60%
  Core/40% Difensivo classificato comunque come "Difensivo" dal ruolo).
  Ora usa il bucket dominante per peso dell'esposizione frazionata, con
  fallback al vecchio comportamento se l'esposizione manca.
- Fix collaterale (segnalato dall'utente sul grafico "P/L del
  portafoglio", vista Overview): la serie "P/L storico" sommava
  erroneamente il P/L realizzato netto a quello delle posizioni aperte.
  Ora coincide esattamente con "P/L pos. aperte"; "Total return" resta
  l'unica serie a includere il realizzato, con l'area di riempimento
  colorata in base al segno corretto.
- Refresh automatico in background per i profili InstrumentAnalysis
  (Fase D): stesso schema del refresh Mercati (thread daemon, stato
  proprio su file), **disattivato di default**. Popola la cache
  strumento per strumento (fino a 20 per ciclo) solo per chi non e' gia'
  in cache, senza mai bloccare un ciclo su un universo grande. Attivabile
  da Impostazioni; nessun pulsante di refresh manuale in questo giro
  (il primo ciclo del thread fa gia' da prewarm).
- Con questo si chiude l'intero arco InstrumentAnalysis pianificato
  (Fasi A, E, B, C, D): motore online-first collegato end-to-end a
  benchmark, esposizione bucket/nature/ruolo SATOR e refresh in
  background. Dettaglio completo in `STATO_OPERATIVO_5.0_PRE.md`
  sezione 7.

## 5.0-pre - Fase B: core/benchmark_registry.py collegato a InstrumentAnalysisService

- `core/benchmark_registry.py` non e' piu' un mapping statico ticker/ISIN/
  tipo: e' una facade sottile su `InstrumentAnalysisService` — la
  risoluzione automatica del benchmark per singolo strumento (Cruscotti,
  Quotazioni, Confronto, form "Ruolo & Benchmark") ora viene dal motore
  online-first invece che da ~90 righe di regole codificate a mano.
  L'override manuale dell'utente resta identico e ha sempre la priorita'.
  `tools/audit_no_static_benchmarks.py` conferma zero mapping statici
  residui nel repo.
- Nuovo ticker "di riserva" scaricabile per strumenti la cui identita'
  ufficiale e' un nome leggibile invece di un simbolo Yahoo (~90% dei
  casi): il grafico benchmark e la correlazione continuano a funzionare
  senza mai sostituire l'identita' ufficiale mostrata.
- Effetto collaterale onesto: l'autocomplete del benchmark in Quotazioni
  interne/Strumenti ora si popola con quello che il motore scopre a
  runtime, non piu' con un elenco fisso — su un processo appena avviato
  puo' apparire vuoto finche' non e' stato risolto almeno uno strumento.
- Verifica end-to-end: app reale avviata con il portafoglio vero, tutte
  le 11 pagine (Cruscotti/Confronto incluse) renderizzano senza errori;
  89,9% delle identita' non direttamente scaricabili ora hanno comunque
  un ticker di riserva per grafico/correlazione (era 0%).
  Dettaglio completo in `STATO_OPERATIVO_5.0_PRE.md` sezione 7.

## 5.0-pre - InstrumentAnalysis: classificazione, geometry, ladder e composite C/D/S; fix data fittizia quotazioni; "Ripara buchi"

- InstrumentAnalysis (proseguimento): score C/D/S 42,66 -> 94,95/100,
  score benchmark 42,66 -> 75,38/100 sul replay ufficiale dei 111 (sui 30
  strumenti reali del portafoglio: media 60,8 -> 77,8/100).
  Dettaglio in `STATO_OPERATIVO_5.0_PRE.md` sezione 7.
- Fondi multi-asset (es. fondi Fineco AM proprietari) e titoli di stato
  singoli ora hanno un benchmark reale invece di un fallback generico o
  di nessuna risoluzione: composizione azioni/obbligazioni reale per i
  fondi (yfinance), curva di rendimento sovrana ECB duration-matched per
  i BTP (mai un ETF come proxy — solo rete di sicurezza se la curva non
  risponde), indice di riferimento dedicato per il debito dei mercati
  emergenti (EMB). Idea confermata nella documentazione originale
  dell'handoff, non ancora collegata; priorita' e scelte perfezionate su
  feedback diretto dell'utente (indice puro preferito a un ETF quando
  disponibile).
- Classificazione testuale collegata al motore + 3 bug di riconoscimento
  corretti (fonte benchmark troncata, abbreviazioni bond, token factor
  mancante nel gate equity).
- I rami EXACT/SISTER ora calcolano un punteggio di geometria come
  controllo qualita' (prima restavano sempre a un valore fisso basso).
- Ladder intermedio collegato (~40 famiglie di riferimento, 15 paesi),
  con selezione del miglior candidato invece del primo disponibile.
- Curva composita pesata per C/D/S per strumenti equity con ruolo misto
  (idea dell'utente, confermata nell'handoff originale).
- Fix "Aggiorna Quotazioni": scriveva il prezzo sotto la data odierna
  invece della data reale, creando una sessione fittizia se aggiornato
  subito dopo mezzanotte (segnalato dall'utente).
- Nuova sezione "Ripara buchi" in Gestione Dati: recupero automatico
  limitato agli ultimi 30 giorni, inserimento manuale con conferma per
  i buchi piu' vecchi. Tre fix segnalati dall'utente in uso live: crash
  (`KeyError: 'auto_fill'`) da anteprima obsoleta in sessione; date in
  formato ISO invece di gg/mm/aaaa; buchi vecchi di mesi proposti nella
  tabella manuale invece di restare entro gli ultimi 30 giorni come da
  richiesta originale. Tabella auto-recupero ora mostra data+prezzo per
  riga invece di un solo conteggio.

## 5.0-pre - Purchase Optimizer con esposizione frazionata reale, coerenza grafica form-server, NO_SELL nel motore SATOR (sotto-progetto 5/"10bis", 11 revisione classificazione)

- chiude la voce 10 dell'ordine di priorità della revisione (Purchase
  Optimizer), l'ultima ancora aperta della sequenza obbligatoria 1-10 dopo
  il sotto-progetto 4. Un strumento con esposizione frazionata ai bucket
  (es. 65% Core / 35% Difensivo) poteva prima competere per un nuovo
  acquisto SOLO nel sotto-budget del suo bucket primario: se quel bucket
  era saturo/bloccato, lo strumento non poteva mai essere comprato per
  aiutare l'altro bucket a cui pure apparteneva, anche con un deficit
  enorme lì.
- `_dominant_bucket(exposure, eligible_buckets, bucket_deficits)`: per ogni
  riga, assegna lo strumento al bucket — tra quelli a cui appartiene ed è
  eleggibile — con il deficit euro maggiore. Per uno strumento non diviso
  collassa esattamente al comportamento di sempre.
- `_compute_marginal_purchase_metrics` guadagna `bucket_weights`/
  `bucket_targets` opzionali (default `None`, percorso di default
  invariato): quando presenti, il miglioramento verso il target è la
  somma pesata sui bucket toccati — mai una media dei pesi/target prima
  di calcolare lo scostamento, stesso principio già validato dal
  sotto-progetto 4 per `_score_fit`. I due parametri sono filati fino
  alla colonna "Prio" mostrata in tabella e alla motivazione testuale —
  trovato in fase di piano che quel ricalcolo (un terzo punto di chiamata
  mai scoped al percorso pesato) avrebbe altrimenti mostrato una priorità
  incoerente con la decisione reale per uno strumento diviso.
- esteso su richiesta esplicita dell'utente ("un unico intervento 10bis
  completo") con 4 problemi reali segnalati rivedendo il lavoro dei
  sotto-progetti 1-4:
  - **coerenza grafica tra le pagine del form-server**: `sator.py`,
    `quote_interne.py` e `scheda_strumento.py` ricostruivano ciascuna il
    proprio foglio di stile invece di riusare `shell.CSS` — un bug di
    colore reale incluso (`.alert-warn` in rosso invece che in ambra, non
    distinguibile visivamente da un errore).
  - **NO_SELL collegato davvero al motore SATOR**: `_score_universe` ora
    esclude dal ranking un nuovo acquisto per uno strumento NO_SELL —
    prima il flag influenzava solo un'etichetta nella UI, mai
    l'eleggibilità reale. Aggiunta anche una nota esplicativa accanto
    alla spunta, prima priva di qualunque testo.
  - **valore automatico accanto al valore in vigore** per le tabelle
    "Ruolo & Benchmark" ed "Esposizione Bucket" — mostrato solo quando
    diverge dal valore effettivo, per non affollare la tabella quando non
    c'è alcuna forzatura manuale.
  - **selettore benchmark da catalogo esistente** (`<datalist>`, il campo
    resta testo libero — nessuna perdita della possibilità di inserirne
    uno nuovo) + log di avviso quando il fetch dello storico prezzi di un
    benchmark torna vuoto (prima silenziosamente saltato).
- eseguito con `subagent-driven-development`: 9 task + un'ondata di fix
  dalla review finale sull'intero branch (sul modello più capace,
  dispatchata dopo tutti i 9 task). Bug trovati e corretti prima del
  merge: `post_bucket_weight` nel ramo pesato restituiva il valore
  pre-acquisto invece che post-acquisto (Task 2); il test end-to-end
  "flagship" passava per un motivo estraneo al fix reale, senza che il
  suo bucket primario fosse davvero bloccato (Task 4); un fallback
  asimmetrico su `_bucket_exposure` che azzerava silenziosamente le
  metriche nel ramo pesato invece di degradare al bucket primario come
  già fa `_score_fit` (non raggiungibile in produzione oggi, ma
  incoerenza interna reale); un valore benchmark "automatico" calcolato
  senza `master_entry`, che poteva mostrare una forzatura manuale
  inesistente.
- **decisione di design lasciata aperta dalla review finale** (non un
  bug): NO_SELL esclude oggi lo strumento dall'intero ranking SATOR, non
  solo dai nuovi acquisti — quindi sparisce anche dalla frontiera
  rischio/rendimento "Attuale" e dalla Mappa strumenti. Fedele al testo
  della spec, ma in tensione con l'uso tipico (una posizione storica che
  dovrebbe restare visibile nel portafoglio attuale). Nessun dato reale
  usa oggi NO_SELL — vedi sezione "Priorità 9" in `STATO_OPERATIVO_5.0_PRE.md`
  per i dettagli e le opzioni di correzione.

## 5.0-pre - Esposizione frazionata reale nel motore SATOR (sotto-progetto 4/11 revisione classificazione)

- copre le voci 6-9 dell'ordine di priorità della revisione (segue il
  sotto-progetto 3, target strategico e NO_SELL). Il sotto-progetto 2
  aveva introdotto l'esposizione frazionata ai bucket (uno strumento può
  appartenere per frazione a più bucket Core/Difensivo/Satellite) ma solo
  per gli aggregatori di visualizzazione — il motore SATOR vero
  continuava a vedere ogni strumento come 100% nel suo bucket primario.
  Questo sotto-progetto chiude il divario per 4 pezzi del motore, uno per
  voce, senza formule nuove: ogni funzione generalizzata degenera
  esattamente al comportamento di oggi per uno strumento senza divisione
  configurata.
- `SatorContext` guadagna `instrument_bucket_exposures` (mappa
  ticker→bucket→frazione per l'intero universo, non solo i posseduti);
  `run_sator_analysis` calcola ora i propri `bucket_weights` con
  l'esposizione frazionata (riuso del flag `use_fractional_exposure` già
  esistente dal sotto-progetto 2, prima sempre `False` per il motore).
- eleggibilità (voce 8, Eligibility Engine): uno strumento diviso resta
  candidabile finché almeno uno dei bucket a cui appartiene ha quote
  interne valide, non solo il suo bucket primario.
- punteggio Fit (voce 7, Strategic Analyzer): la penalità di sovrappeso-bucket
  è ora la media pesata sulla frazione di esposizione di ciascun bucket
  toccato, invece del solo bucket primario — uno strumento diviso 65%
  Core/35% Difensivo con Core sovrappesato e Difensivo no viene penalizzato
  solo per la sua vera quota in Core.
- deficit di bucket (voce 9, Rebalancing Engine): quando l'impostazione
  opt-in `bucket_first_allocation` è attiva, il calcolo del deficit euro
  per bucket riflette anch'esso la composizione frazionata reale.
- voce 10 (Purchase Optimizer) esplicitamente rimandata a un sotto-progetto
  5 futuro: l'allocazione degli acquisti resta a bucket singolo, è il
  pezzo più delicato (un acquisto di uno strumento diviso dovrebbe
  "pagare" da più sotto-budget di bucket senza doppio conteggio — problema
  algoritmico distinto, non risolvibile con lo stesso pattern delle altre
  3 voci).
- bug critico trovato dalla review finale sull'intero branch e corretto
  prima del merge: la colonna `_bucket_exposure` veniva creata DOPO essere
  già stata letta dal calcolo del punteggio Fit, rendendo l'intera
  generalizzazione della voce 7 inerte in produzione (ogni strumento,
  diviso o no, veniva sempre valutato come 100% nel suo bucket primario) —
  errore di ordinamento nella spec/piano stessi, non dell'implementazione;
  trovato con verifica empirica sul motore reale, corretto spostando il
  popolamento della colonna dentro il ciclo di costruzione delle righe
  (prima del calcolo dei punteggi) con un test di integrazione dedicato
  che passa per `run_sator_analysis` reale, non per una riga costruita a
  mano. Corretto in stesso giro anche un terzo punto di chiamata mai
  aggiornato (alimentava un alert di sovrappeso-bucket con un gate non
  frazionato, rischiando di sopprimere un alert reale per uno strumento
  diviso) e un docstring gemello rimasto falso.

## 5.0-pre - Target strategico e posizione NO_SELL per strumento (sotto-progetto 3/11 revisione classificazione)

- copre le voci 3+4 dell'ordine di priorità della "Revisione del modello di
  classificazione e allocazione" (segue il sotto-progetto 2, appartenenza
  frazionata ai bucket). Obiettivo: vedere affiancati peso attuale e target
  strategico per ogni strumento, e poter segnalare una posizione
  sovrappesata "per scelta" (legacy) senza generare l'impulso a venderla.
- `resolve_instrument_no_sell(data, ticker)` (nuovo, `core/services/sator.py`):
  legge il flag NO_SELL da `manual_overrides.sator`, sola lettura, nessun
  campo dati nuovo oltre `no_sell`/`no_sell_user_edited`.
- `compute_instrument_operational_status(data, settings)` (nuovo): calcola
  peso attuale, target assoluto di portafoglio (`instrument_quotas[bucket][ticker]
  * objective[bucket]` — mai confrontare direttamente la quota-di-bucket col
  peso-di-portafoglio, denominatori diversi) e stato
  (`in_target`/`sottopeso`/`sovrappeso`/`sovrappeso_no_sell`) per ogni
  strumento posseduto. Nessun impatto sul motore SATOR (`run_sator_analysis`
  e affini restano invariati).
- `apply_classification_override` e `apply_bucket_exposure_override` estratte
  dai rami POST di `ui/form_server/strumenti.py` (Classificazione →
  Arricchimento) in `core/services/sator.py`: stessa identica logica di
  scrittura, ora condivisa anche dalla nuova pagina — verificata
  comportamentalmente invariata sull'editor originale con la suite di
  non-regressione esistente.
- Pagina "Quote & impostazioni" (`ui/form_server/quote_interne.py`)
  ristrutturata da pannello singolo a 3 sottoschede: "Target & Stato" (peso
  attuale, target strategico, checkbox NO_SELL, badge di stato per
  strumento), "Ruolo & Benchmark" e "Esposizione Bucket" (tabelle
  multi-riga, editing rapido per tutti gli strumenti in una sola vista,
  invece dell'editor singolo-strumento di Strumenti → Arricchimento).
- bug critico trovato in review e corretto prima del merge: la prima
  versione di `apply_no_sell_from_form` scansionava l'intero catalogo
  strumenti invece dei soli ticker con una checkbox NO_SELL renderizzata in
  quella pagina — salvare una modifica qualsiasi alle quote poteva
  cancellare silenziosamente il flag NO_SELL di uno strumento chiuso, mai
  posseduto, o escluso in quel momento dal toggle BTP/GOV. Corretto
  scopando la scrittura ai soli ticker effettivamente presenti nel submit,
  con test di regressione dedicato.
- review finale sull'intero branch: un secondo bug della stessa classe
  (la tabella "Esposizione Bucket" arrotondava le percentuali a interi,
  corrompendo silenziosamente split come 12,5%/87,5% in 12%/88% al primo
  salvataggio di una riga qualsiasi) più 3 problemi di coerenza (il target
  calcolato non veniva mai mostrato in UI; le tre sottoschede iteravano
  popolazioni di strumenti diverse; il menu Ruolo usava chiavi tecniche
  invece delle etichette italiane già in uso in `/strumenti`) — tutti
  corretti in un'unica passata e ri-verificati prima del merge.

## 5.0-pre - Correzioni sparse su BTP, P/L fantasma, Monte Carlo, matrici di correlazione e qualità dati

- BTP: la quantità per il calcolo del rimborso a scadenza veniva letta dal
  campo facoltativo `strumento["quantita"]` (popolato solo dai vecchi
  flussi manuali, assente per uno strumento nuovo → default 1 quota). Ora
  usa `core.domain.positions.calc_positions` come tutto il resto dell'app.
  Timeline BTP ora ordinata per scadenza cronologica (non più alfabetico
  per ticker), e il totale sotto la tabella eventi è scomposto in tre
  righe (Totale / di cui incassato / di cui residuo) invece di un unico
  numero che mischiava cedole già incassate e future.
- bug reale con impatto finanziario diretto: una posizione senza alcuna
  quotazione nota (es. BTP acquistato lo stesso giorno, prima ancora di
  avere uno storico prezzi) veniva valorizzata a zero invece che al costo
  di carico, generando una perdita fantasma in curva P/L (-18.312 € su un
  caso reale). Nuovo comportamento neutro: in assenza di prezzo di mercato
  il valore è il costo di carico (P/L zero finché non arriva una
  quotazione reale). Bump firma cache dedicato perché una riga già
  cacheata sotto lo schema precedente non si autocorregge da sola.
- secondo bug reale con lo stesso impatto (-18.312 € di P/L fantasma): un
  Acquisto auto-liquidato e il suo Versamento automatico non avevano alcun
  collegamento strutturale — correggere prezzo/commissioni/data
  dell'acquisto lasciava il versamento sul valore vecchio, sbilanciando la
  partita di giro. Ora ogni Versamento automatico è collegato al trade che
  finanzia (`linked_trade_event_id`) e viene risincronizzato automaticamente
  quando il trade collegato viene modificato.
- la firma dati strumento non includeva i campi cedola/scadenza: correggere
  dati di una cedola sbagliata su un BTP già presente non invalidava la
  cache, lasciando Timeline BTP e il KPI "Cedole attese 12 mesi" bloccati
  sul valore vecchio a tempo indeterminato (stessa classe di bug già chiusa
  una volta per il campo "natura"). Aggiunti scadenza, cedola_perc,
  cedola_frequenza, prima_cedola, aliquota_cedola, nominale alla firma.
  Anche la tabella yield prospettico GOV ora ordina per scadenza cronologica
  invece che per cedole 12 mesi decrescenti.
- Monte Carlo: il bootstrap richiedeva che TUTTI gli strumenti pesati
  avessero un rendimento valido nello stesso giorno, quindi un solo
  strumento appena aperto con poche quotazioni bloccava l'intera
  simulazione anche con un portafoglio ricco di storico. Ora gli strumenti
  con meno di 60 osservazioni proprie vengono esclusi dal paniere (pesi
  riproporzionati sui restanti) invece di bloccare tutto, e la UI segnala
  quali strumenti sono esclusi e che quota rappresentano. Stessa logica di
  trasparenza estesa a metriche avanzate e contributo al rischio (uno
  strumento con meno di 3 quotazioni proprie spariva senza spiegazione).
- matrice di correlazione per strumento: l'altezza dinamica calcolata dal
  builder veniva scartata e sovrascritta dall'altezza fissa pensata per la
  matrice per categoria, rendendo illeggibile la matrice con 20+ strumenti;
  corretto anche lo spazio bianco in eccesso sopra la matrice. Aggiunta
  anche una legenda condivisa sotto entrambe le matrici che spiega il
  significato di +1/-1/0 (prima nessun riferimento, colorbar disattivata).
- eliminato un `RuntimeWarning` numpy nel calcolo correlazioni SATOR (un
  titolo con pochissime quotazioni proprie faceva sollevare "Degrees of
  freedom <= 0", scartato solo a valle — risultato finale già corretto, ma
  il warning intasava i log).
- tabella qualità dati strumenti: ora mostra il colore di categoria
  (`ui.theme.macro_color`, come tutte le altre tabelle) e distingue gli
  strumenti realmente in portafoglio da quelli solo osservati (colonna
  "Ptf"), invece del rendering grezzo precedente. Le tabelle "Ultime
  quotazioni aggiornate", "Controvalore del Portafoglio" e "Andamento
  ultima settimana" ora si aprono ordinate per categoria alfabetica.

## 5.0-pre - Appartenenza percentuale multipla ai bucket (sotto-progetto 2/11 revisione classificazione)

- copre la voce 2 dell'ordine di priorità della revisione (segue il
  sotto-progetto 1). Permette a uno strumento di appartenere per frazione a
  più bucket Core/Difensivo/Satellite (es. un fondo bilanciato 60/40) invece
  che a un solo bucket "primario" derivato dal ruolo.
- `resolve_instrument_bucket_exposure`/`compute_instrument_bucket_exposures`
  (nuove): esposizione frazionata per strumento e mappa aggregata
  ticker→bucket pesata, con validazione somma=1.0 (tolleranza 1e-6) e
  fallback sul bucket primario quando l'override è assente o malformato.
- `_compute_bucket_weights` somma ora proporzionalmente per gli strumenti
  con esposizione divisa, ma solo dietro un flag esplicito
  `use_fractional_exposure` (default `False`): il motore SATOR vero
  (`run_sator_analysis`, `blocked_buckets_quota`, `compute_instrument_quota_status`)
  resta bucket-singolo e comportamentalmente invariato per vincolo di
  scopo — solo la vista "mix corrente" per l'utente vede la frazione.
  `build_portfolio_rings_frame` esplode una riga per (strumento, bucket) per
  gli strumenti divisi, ereditata automaticamente dal grafico a ciambella e
  dalla tabella di allocazione.
- validazione delle quote interne: uno strumento con appartenenza divisa
  viene escluso dal calcolo di validità di ogni bucket (non richiede una
  quota in nessun bucket), e la sua vecchia quota — se ne aveva una prima
  di dividersi — viene riservata nel calcolo della somma-100% degli altri
  strumenti dello stesso bucket, invece di far scendere permanentemente
  sotto 100% un bucket già corretto.
- nuovo editor "Esposizione tra bucket" in Classificazione → Arricchimento:
  scrittura solo-se-cambiato (stesso principio già applicato a
  ruolo/benchmark), validazione somma≈100% con messaggio di rifiuto
  distinto dal messaggio di successo (bug corretto: prima il redirect
  mostrava sempre "aggiornata" anche quando la scrittura veniva scartata).

## 5.0-pre - Motore di classificazione e arricchimento unificato (sotto-progetto 1/11 revisione classificazione)

- copre la voce 1 dell'ordine di priorità della revisione. Introduce il
  primo editor UI per `manual_overrides.sator.{role,benchmark_code,
  benchmark_label,user_edited,benchmark_user_edited}` — meccanismo già letto
  dal motore SATOR ma finora mai alimentato da nessuna interfaccia.
- 3 nuove nature SATOR (criptovalute, difesa_sicurezza,
  azionario_paese_singolo) per colmare i buchi della tassonomia visiva
  legacy; corretta la specificità bond-vs-emerging in `infer_sator_metadata`
  (un fondo "Emerging Markets Bond" finiva classificato come azionario) e
  aggiunto un campo "confidence" (alta/media/bassa, alta solo per match
  esatto su ticker/ISIN, non su semplice keyword); riconosciuta la keyword
  "Information Technology" mancante nel ramo tecnologia/AI.
- `get_nature_visual` sostituisce la vecchia icona keyed su etichetta
  libera con una keyed sulla nature SATOR risolta; migrati i 7 chiamanti
  reali (tabelle quotazioni/portafoglio, promemoria watchlist, donut di
  Pianificazione). Nuovi `resolve_instrument_nature`/`resolve_instrument_role`
  come punti di accesso pubblici unici, sostituendo duplicazioni manuali
  della logica privata in più file.
- editor manuale ruolo/benchmark nella tab Arricchimento: bug critico
  trovato e corretto in review — il salvataggio scriveva un override ad
  ogni submit anche senza modifiche reali (il form è sempre precompilato),
  e poteva riattivare chiavi legacy dormienti condividendo lo stesso flag
  `user_edited` di campi indipendenti. Corretto a scrittura solo-se-cambiato,
  indipendente per ruolo e benchmark. Corretto anche un secondo bug: un
  benchmark manuale impostato una volta restava "congelato" in
  `instrument_master` e non veniva più aggiornato da correzioni successive
  alle regole automatiche.
- review finale: chiusi 8 finding aggiuntivi (4 punti reali dove un
  benchmark override non veniva mai letto per mancanza di `master_entry`,
  due nature con etichetta identica indistinguibili nel donut, validazione
  del ruolo inviato contro i valori ammessi, etichette italiane leggibili
  nel `<select>` ruolo invece del codice tecnico).

## 5.0-pre - Editor quote target per strumento e pagina /quote-interne

- primo modello dati e prima UI per le quote target SATOR per strumento
  dentro ogni bucket: schema `instrument_quotas`/`instrument_quota_tolerance_pp`,
  calcolo di validità per bucket (copertura totale + somma≈100%, opt-in:
  un bucket mai configurato resta sempre valido), blocco dei candidati
  SATOR nei bucket con quote non valide.
- nuova pagina form-server `/quote-interne` (registrata in sidebar come
  "Quote & impostazioni"): editor delle quote con validazione somma=100 lato
  server, tabella di stato in sola lettura, forbice di riferimento
  indicativa per strumento (dai limiti di concentrazione per natura già
  esistenti), banner bloccante e avviso informativo per bucket con quote
  mancanti o mai configurate. Le 4 sezioni di impostazioni SATOR avanzate
  (limiti di concentrazione, allocazione budget, pesi punteggio, tolleranze)
  spostate dagli expander di Pianificazione a questa pagina.
- toggle unico "Escludi BTP/GOV" in cima a Pianificazione, propagato a ogni
  grafico/tabella della pagina (sostituisce il vecchio checkbox limitato al
  solo calcolo deficit di bucket). Tabella di allocazione bucket
  ristrutturata a riga-per-ticker con barra attuale/tacca target.
- review finale + due giri di correzioni segnalate dall'uso reale: quote di
  concentrazione mai salvate, opt-in per bucket irraggiungibile, tolleranza
  di validazione disallineata dal vincolo core, colori hardcoded al posto
  dei token tema, toggle BTP non propagato a `/quote-interne`, testo HTML
  che si rompeva su una riga vuota dentro `st.markdown`, percentuali del
  grafico obiettivo-vs-mix non rinormalizzate quando si esclude un bucket.

## 5.0-pre - Chiusura quasi totale della governance cache unica

- deciso (richiesto dall'utente, 2026-08-17): `core/page_cache.py` resta il
  magazzino L3 definitivo, nessuna riscrittura in `core/cache_store.py` —
  decisione rimasta sospesa dal 2026-08-03 che bloccava implicitamente la
  promozione di 21 artefatti ancora `pilot`.
- censimento completo (non a campione) di tutti gli artefatti ancora
  `pilot`: 14 già collegati correttamente al magazzino promossi subito
  (solo verifica, nessun codice nuovo); `confronto.comparison_report` e
  `summary.report_payload` collegati per la prima volta a
  `get_or_build_registered_artifact` (prima ricostruiti ad ogni rerun o
  dietro click senza passare dal magazzino); le schede di
  `cruscotti.benchmark_frozen_analysis`/`accumuli_frozen_analysis`
  corrette per riflettere il meccanismo di cache reale già in uso (la
  cache c'era ed era corretta, solo la scheda del registro descriveva un
  meccanismo sbagliato); `prebuild.registry_engine` verificato e promosso.
- registro finale: 26 `registered_provider` (era 6 a inizio intervento),
  1 solo `pilot` rimasto (`mercati.live_snapshot`, deliberatamente non
  toccato: è un servizio in background incompatibile con l'architettura di
  `get_or_build_registered_artifact`, e la sezione Mercati resta in
  osservazione).
- riordinata la pagina Pianificazione: "Confronto strumenti" (tool manuale)
  spostato in fondo, dopo tutta la parte automatica di SATOR, per non
  interrompere bruscamente il flusso di analisi.

## 5.0-pre - Alert di concentrazione BTP silenziati quando deficit_pac_only e' attivo

- richiesta esplicita dell'utente (2026-08-16, confermata con domanda
  multi-scelta): quando `deficit_pac_only` e' acceso l'utente ha gia' detto
  a SATOR di ignorare i BTP nel calcolo del deficit di bucket; gli alert
  "Concentrazione elevata: bond governativo 76%" e "Bucket sovrappesato:
  Difensivo 79%" - dovuti solo ai BTP - risultavano comunque sempre
  visibili, percepiti come rumore contraddittorio rispetto al flag appena
  attivato. Scartate le opzioni "rimuovi sempre" (nasconderebbe
  un'informazione di rischio reale col flag spento) e "alza la soglia"
  (non risolve, l'utente vuole silenzio solo quando ha gia' escluso i BTP).
- `_compute_nature_weights` (`core/services/sator.py:1807`) accetta ora
  `exclude_tickers`, stesso pattern di `_compute_bucket_weights`: nessuna
  rinormalizzazione, i ticker esclusi sono rimossi dalla somma e basta.
  `run_sator_analysis`, quando `deficit_pac_only=True`, ricalcola
  nature_weights e bucket_weights escludendo i ticker non-PAC (stesso
  `_non_pac_held_tickers` gia' usato per lo split budget) e li passa a
  `_build_alerts` come filtro: un alert di concentrazione compare solo se
  la soglia resta superata ANCHE dopo l'esclusione. Un alert non causato
  dai BTP (es. "fondo pac 15%", verificato) continua a comparire come
  sempre. Flag spento: comportamento identico a prima, nessun filtro.

## 5.0-pre - Redistribuzione del residuo di budget tra bucket SATOR

- bug segnalato dall'utente in uso reale (2026-08-16), dopo il merge del
  meccanismo di allocazione per bucket sopra: con budget 1.600EUR e
  `bucket_first_allocation` attivo, ogni bucket riceveva un sotto-budget
  proporzionale al proprio deficit ma poteva fermarsi prima di spenderlo
  (candidati sotto soglia 0,50 di punteggio decisionale, o cap del 35% per
  riga); il residuo restava liquido a prescindere, senza mai andare a un
  bucket che aveva invece saturato la propria quota. Misurato: 126EUR di
  residuo su 1.600EUR richiesti; l'utente notava inoltre che il pannello di
  confronto SATOR/utente (`ui/form_server/sator.py`) lo accusava di
  "impegnare piu' budget di SATOR" quando in realta' stava solo usando il
  proprio budget dichiarato, non la proposta (parziale) di SATOR.
- fix in `_suggested_quotes_by_bucket` (`core/services/sator.py:1425`):
  aggiunto un secondo giro, singolo e deterministico (nessun loop): il
  residuo dei bucket sottospesi va ai bucket che hanno saturato la propria
  fetta nel primo giro (entro il 5% o 1EUR di tolleranza), in proporzione
  al loro deficit. Un bucket che non ha saturato la propria quota nel primo
  giro non riceve mai altro nel secondo — se aveva gia' esaurito i
  candidati validi, dargli piu' budget non lo aiuterebbe. Verificato sui
  dati reali: residuo sceso da 126EUR a 10EUR (quota fisiologica di
  granularita' quote intere, non risolvibile senza spezzare l'invariante
  "quote intere" del motore).
- ripristinati in questa occasione anche i test del piano precedente
  (`tests/test_sator_bucket_objective.py`), persi durante la pulizia del
  worktree: `tests/` e' interamente gitignored in questo repo (scelta
  esplicita, 2026-08-05) e `git worktree remove` non ne preserva il
  contenuto - i test scritti durante l'11 task del piano bucket-eligibility
  esistevano solo nella working copy del worktree e sono spariti con esso.
  Nota per il futuro: prima di rimuovere un worktree che ha esteso test in
  `tests/`, copiarli nella working copy principale se si vuole conservarne
  la copertura.

## 5.0-pre - Allocazione budget SATOR per deficit di bucket (opt-in)

- bug reale trovato e misurato sul portafoglio dell'utente, non
  ipotetico: con Core al 18,98% (target 50%), Difensivo al 78,58%
  (target 40%, dominato da BTP pari al 76,1% dell'intero portafoglio) e
  Satellite al 2,44% (target 10%), a budget di €1.500 l'allocazione
  greedy-globale gia' esistente di SATOR escludeva correttamente
  Difensivo (€0, bucket oltre la banda massima) ma assegnava piu' soldi a
  Satellite (€923, deficit euro ~€5.031) che a Core (€570, deficit
  ~€20.765 — 4 volte maggiore): SATOR sceglie il candidato con il
  punteggio migliore su tutto l'universo, indipendentemente da quale
  bucket abbia piu' bisogno di capitale.
- nuovo meccanismo opt-in, spento di default, in `core/services/sator.py`:
  master switch `bucket_first_allocation` (riga 153, False di default —
  a flag spento il comportamento resta identico a prima, verificato per
  tracciamento del branch condizionale e non solo per output di test),
  `band_tolerance_pp` (riga 151, 0,03 di default: bande min/max reali
  attorno al target di ciascun bucket, prima esisteva solo il target
  puntuale) e `deficit_pac_only` (riga 152, False di default: esclude gli
  strumenti non da accumulo come BTP/GOV dal calcolo dei pesi di bucket
  usato per lo split del deficit), tutti normalizzati in
  `ensure_sator_settings` (riga 180).
- 5 funzioni nuove/estese in `core/services/sator.py`:
  `_compute_bucket_bands` (riga 1038, target puntuale -> {target, min,
  max}); `_compute_bucket_weights` esteso con `exclude_tickers` (riga
  1057, retrocompatibile — verificato su dati reali di produzione, non
  solo su fixture sintetica, che ometterlo riproduce l'output odierno
  entro il rumore float); `_non_pac_held_tickers` (riga 1090, riusa
  `infer_sator_metadata`/`pac_enabled` gia' esistenti invece di
  reimplementare il check di categoria); `_compute_bucket_deficits`
  (riga 1108, formula standard Vpost = value+budget,
  TargetValue = Vpost*target, Deficit = max(TargetValue-CurrentValue, 0),
  piu' blocco hard dei bucket oltre la banda massima — il test di
  regressione sul caso reale riproduce i numeri misurati sopra);
  `_suggested_quotes_by_bucket` (riga 1415, divide il budget fra i
  bucket idonei in proporzione al deficit, poi chiama una volta per
  bucket, sul sotto-budget, la primitiva esistente e non modificata
  `_suggested_quotes`).
- decisione di design dell'utente a meta' implementazione: nessun cap
  predeterminato di righe suggerite per bucket. La review del task 7 ha
  trovato che la formula del piano (`max(1, max_lines // 3 or 1)`, 1 riga
  per bucket) contraddiceva il design doc scritto in precedenza (2 righe
  per bucket) — interpellato direttamente, l'utente ha respinto entrambi
  i numeri: il conteggio di acquisti suggeriti resta governato solo dal
  sotto-budget e dal punteggio di decisione di ogni candidato (soglia
  >=0,50), non da un limite fisso. Wiring finale:
  `max_lines_per_bucket=len(work)`, nessun cap artificiale — i limiti
  reali restano soglia di punteggio, budget disponibile e il cap
  preesistente del 35% per riga.
- `build_sator_matrix_frame` (riga 823) riceve due nuovi parametri
  opzionali `data`/`settings` (default None): se assenti il percorso di
  codice resta strutturalmente identico a prima (la condizione di branch
  fa short-circuit prima di toccare `ensure_sator_settings` o le nuove
  funzioni); se presenti e col flag acceso, delega alla nuova allocazione
  per bucket. Collegati i due call site reali:
  `core/services/sator_frontier.py:328` (simulazione pre-trade di SATOR
  Frontier) e `ui/form_server/sator.py:1766` (azione "Analizza"
  principale di SATOR) — entrambi verificati live su dati reali, output
  invariato a flag spento.
- UI in `ui/pages/pianificazione.py:335`, dentro il form esistente
  "Obiettivo di portafoglio": nuovo expander "Allocazione budget per
  bucket (avanzato)" con 3 controlli (checkbox `bucket_first_allocation`,
  number_input `band_tolerance_pp` in punti percentuali con conversione
  andata/ritorno verso la frazione memorizzata, verificata anche in
  round-trip, checkbox `deficit_pac_only`), salvati con il pattern
  esistente `_save_portfolio_objective_settings_from_state`.
- verifica end-to-end finale (test interattivo via browser non
  disponibile in questa sessione: simulato cio' che i nuovi controlli UI
  scriverebbero nelle settings, poi eseguito `run_sator_analysis` +
  `build_sator_matrix_frame` sul portafoglio reale con budget €1.500):
  flag spento -> Core €570 / Satellite €923 (bug di oggi, invariato);
  flag acceso -> **Core €1.128 / Satellite €292** — inversione corretta,
  vicino allo split teorico 80/20 implicato dai deficit euro reali.
- bug critico trovato dalla review finale whole-branch (dopo l'11° e
  ultimo task del piano, prima del merge) e corretto in un fix wave
  dedicato: `_compute_bucket_weights` (riga 1057) rinormalizzava i pesi
  restanti quando `exclude_tickers` non era vuoto, dividendo per il
  totale ridotto. Su dati reali, attivando insieme `deficit_pac_only` e
  `bucket_first_allocation`, escludere i BTP gonfiava il peso di Core dal
  18,98% reale a un 79,41% rinormalizzato — sopra la banda massima,
  quindi bloccato — dirottando l'intero budget su Difensivo, gia' il
  bucket piu' sovrappesato: l'esatto opposto dello scopo del fix.
  Interpellato direttamente, l'utente ha confermato: "voglio che se dico
  escludi dal calcolo i BTP questi non vengano considerati" — gli
  strumenti esclusi non devono avere alcun effetto sui pesi degli altri
  bucket. Fix: rimossa ogni rinormalizzazione, somma di pesi grezzi senza
  divisione, per entrambi i casi (`exclude_tickers` vuoto o no). Aggiunti
  anche in questo fix wave: logging (`logger.info`/`logger.warning`) su
  `build_sator_matrix_frame` per i casi "nessun deficit positivo" e
  "colonne mancanti col flag acceso" (prima silenziosi), rimozione di un
  controllo morto (`"bucket_weight" in work.columns`, mai letto nel
  branch) dalla guardia del branch, e rimozione del cap
  `max_lines_per_bucket=2` residuo di un design gia' scartato dall'utente
  (ora `None`, risolto a `len(ranking_df)`). Verificato con un test
  end-to-end su dati reali (entrambi i flag attivi: Core non piu'
  bloccato) e uno sintetico (bucket interamente escluso -> peso 0.0, non
  rinormalizzato); scoped re-review dedicata: tutti i finding ADDRESSED,
  nessuna nuova regressione.
- deliberatamente non toccato: il resto del motore di punteggio SATOR
  (`_score_fit`, `_score_momentum`, `_purchase_decision_score` e simili)
  e la primitiva `_suggested_quotes()` restano invariati, ancora
  chiamati dal nuovo codice per bucket. Origine del lavoro: un documento
  esterno "Portfolio Intelligence" proponeva un modulo generico parallelo
  (Policy, Eligibility Engine, Rebalancing, Opportunity Engine); l'analisi
  preliminare ha concluso di innestare i miglioramenti reali dentro SATOR
  invece di duplicarlo (correlazione reale gia' esistente contro tag
  manuali proposti, explainability deterministica gia' esistente, due
  punteggi gia' distinti) — le altre proposte del documento (Scenario
  Engine per versamenti ricorrenti, Risk Tags/Cluster con limiti hard,
  stati RESEARCH/EXCLUDED con motivazioni salvate, audit log delle
  raccomandazioni, versioning della Policy) restano deliberatamente fuori
  perimetro, candidate per un futuro potenziamento SATOR. Spec e piano
  completi:
  `docs/superpowers/specs/2026-08-15-sator-bucket-eligibility-design.md`,
  `docs/superpowers/plans/2026-08-15-sator-bucket-eligibility.md`.

## 5.0-pre - Confronto strumenti in Pianificazione e consolidamento formule rendimento

- consolidati 8 siti (non 6 come stimato all'inizio: l'ottavo,
  `core/services/sator.py::_rolling_return`, e' emerso a meta' lavoro)
  che reimplementavano la formula "rendimento rispetto al primo valore"
  (`ultimo/primo - 1`) invece di chiamare `core/`; nuova
  `core.domain.returns.normalize_to_first(prices, *, as_pct=True)` come
  primitiva condivisa, usata da `ui/charts/analisi.py:109`,
  `ui/pages/cruscotti.py:962` e
  `core/services/sator.py::_compute_all_metrics_batch` (riga ~1501); gli
  altri siti (incl. l'ottavo) si sono accorpati sulla gia' esistente
  `core.domain.returns.simple_period_return`
  (`core/services/sator.py::_rolling_return`,
  `ui/pages/mercati.py::_period_return`/`_ytd_return`). Spostata in
  `core/domain/calendar.py::estimate_maturity_tax(lordo, pmc)` anche la
  stima fiscale a scadenza BTP, rimossa la duplicazione privata
  (`_stima_imposte_scadenza`/`_ALIQUOTA_BTP`) da
  `ui/charts/calendario_btp.py`.
- la review del task ha trovato e corretto una rottura di parity durante il
  consolidamento di `_rolling_return`: il codice originale proteggeva anche
  i valori di partenza negativi (`inizio > 0`), la nuova funzione condivisa
  proteggeva solo lo zero (`== 0`) — aggiunta una guardia esplicita
  `inizio <= 0` prima di delegare, per non introdurre un rendimento
  calcolato su un valore di partenza negativo.
- nuova sezione "Confronto strumenti" in Pianificazione, subito dopo Mappa
  strumenti: sposta e ricostruisce la vecchia "Performance normalizzata" di
  Cruscotti/Benchmark, prima on-demand dietro un pulsante, ora sempre viva
  e aggiornata a ogni rerun — nessun pulsante "costruisci", scelta esplicita
  dell'utente per un confronto "facile ed immediato". Multiselect strumenti
  (default: posseduti), periodo, opzione "origini allineate" e overlay
  opzionale di un singolo benchmark (tramite `core.benchmark_registry`
  gia' esistente) — `ui/pages/pianificazione.py::_render_instrument_comparison_section`,
  grafico in `ui/charts/pianificazione.py::build_instrument_comparison_chart`
  (linee colorate piene per strumento, tratteggiata grigia per il
  benchmark), logica dati in nuovo
  `core/services/instrument_comparison.py` (`ComparisonSeries`,
  `build_comparison_frame`, `get_all_historical_tickers`,
  `resolve_period_start_date`). Rimossi da
  `ui/pages/cruscotti_benchmark.py`/`ui/charts/benchmark.py` la vecchia
  `_render_normalized_performance_section`,
  `build_normalized_performance_chart` e le due funzioni di supporto ora
  superate; il resto di Cruscotti/Benchmark (KPI, grafico
  portafoglio-vs-benchmark, matrice di correlazione, scatter di coerenza)
  resta invariato, deliberatamente fuori perimetro.
- due bug di performance reali trovati e corretti dopo l'implementazione,
  con misura diretta su dati reali (16 strumenti posseduti, 976 date di
  storico), non per assunzione: (1)
  `core/services/benchmark.py::instrument_price_history`/`benchmark_price_history`
  (funzioni preesistenti, non create da questo lavoro) avevano un
  anti-pattern `pd.to_datetime()`/`pd.to_numeric()` riga per riga, prima
  nascosto dietro la cache on-demand di Cruscotti e ora esposto dalla nuova
  sezione sempre viva — vettorizzato, ~121x piu' veloce (5,1 s -> 0,04 s
  per 16 strumenti); (2) `ui/charts/pianificazione.py::build_instrument_comparison_chart`
  aveva lo stesso anti-pattern nel proprio codice nuovo
  (`[pd.to_datetime(d) for d in s.dates]` in loop) — sostituito con
  un'unica chiamata `pd.to_datetime(s.dates)`, ~118x piu' veloce
  (5,5 s -> 0,05 s). Risultato end-to-end: l'intera sezione (dati +
  grafico) costa ora circa 253 ms a rerun per la vista di default a 16
  strumenti, contro un costo iniziale di circa 9,6 s — solo cosi' il
  requisito "live, senza pulsante" e' davvero rispettato, verificato con
  numeri reali prima/dopo come richiesto dalla regola di progetto sulle
  modifiche di performance.
- reso pubblico (rinominato, nessuna modifica di logica al momento del
  rename) `core/services/benchmark.py::_instrument_price_history`/
  `_benchmark_price_history` in `instrument_price_history`/
  `benchmark_price_history`, per riuso dal nuovo modulo
  `core/services/instrument_comparison.py`.
- nuovo `tools/finance_formula_audit.py`, sul modello di
  `tools/cache_surface_audit.py`: scansione statica ripetibile di `ui/`
  per pattern di formule finanziarie (normalizzazione rendimento,
  statistiche/rischio, aliquote fiscali) non instradate da `core/`.
  Stessa limitazione nota del tool gemello: il filtro dei path esclude
  qualunque segmento con prefisso punto, quindi non trova file se
  eseguito da dentro un checkout annidato in `.worktrees/` (funziona
  correttamente da un checkout normale).

## 5.0-pre - Corretta l'infiltrazione di date weekend nello storico portafoglio

- bump obbligatorio anche dei due livelli di cache esterni al fix
  (`history_df_v5` -> `v6` in `core/state.py`, `_STATE_MANAGER_SCHEMA` in
  `app.py`): senza bump, un pkl già su disco con la firma dati invariata
  avrebbe continuato a servire il vecchio dataframe con le righe weekend
  anche dopo il fix — stesso sintomo già documentato nel bump del
  2026-08-09 (colonna `ValoreAperto`)
- `core/finance.py::_build_portfolio_history_core` costruiva l'indice date
  dello storico portafoglio dall'unione di **tutte** le date di **tutti**
  gli strumenti in `storico_prezzi`, non solo di quelli posseduti: un
  import di storico per uno strumento solo osservato che pubblica NAV di
  sabato/domenica (es. alcuni fondi) faceva entrare quelle date weekend
  nello storico portafoglio, riportando avanti l'ultimo prezzo noto dei
  posseduti sotto una data di mercato chiuso — visibile come uno spazio
  tra venerdì e lunedì nel grafico P/L di Overview (che nasconde
  sabato-lunedì dall'asse) ogni settimana in cui lo strumento osservato
  aveva un prezzo
- trovato dopo un import reale di storico per 3 strumenti osservati
  (MMS.MI, XBAG.MI, XDEQ.MI): 137 nuove date weekend infiltrate
  nell'indice; nessun dato esistente perso, il bug era solo di indice date
  non di integrità dei prezzi già presenti
- nuovo `_filter_weekend_dates()`, applicato incondizionatamente
  (indipendente da chi possiede cosa: uno strumento osservato oggi può
  diventare posseduto domani e continuerebbe a pubblicare NAV di weekend)
  — stessa filosofia "niente weekend" già in uso da
  `_build_synthetic_today_row` e `_with_current_point`
  (`ui/charts/overview.py`); `cache_storico_portafoglio` bump a v8

## 5.0-pre - Grafico "Rate di acquisto per strumento" su controvalore posseduto

- sostituito in Cruscotti/Flussi e Acquisti l'asse Y del grafico "Rate di
  acquisto per strumento" dal numero di acquisti al controvalore posseduto
  per strumento (da `ctx.da["Controvalore"]`); il numero di acquisti resta
  visibile come etichetta sopra ogni barra e nell'hover, asse secondario
  (range prezzi/PMC) invariato — `build_purchase_installments_by_value_chart`
  in `ui/charts/operazioni.py`, rimossa la funzione precedente
  (`build_purchase_installments_chart`) dopo valutazione affiancata

## 5.0-pre - Audit difensivo dei chart builder

- corrette 24 funzioni `build_*_chart` su 9 file (`ui/charts/overview.py`,
  `home.py`, `analitica.py`, `andamento.py`, `analisi.py`, `quotazioni.py`,
  `operazioni.py`, `confronto.py`, `pianificazione.py`) prive di guardia
  contro input `None`/vuoto o con una guardia rotta/incoerente, su un
  censimento completo delle 51 funzioni chart builder del repo; nessuna
  modifica al comportamento su dati validi, solo prevenzione crash su
  input mancante o malformato

## 5.0-pre - Progetti libro AI/Finanza: Mappa strumenti, Monte Carlo, Explainability SATOR, SATOR Frontier

- aggiunta Mappa strumenti in Pianificazione (Progetto C,
  `docs/progetti/ROADMAP_AI_FINANZA_LIBRO.md`,
  `core/services/instrument_clustering.py`): scatter rischio/rendimento
  storico su strumenti posseduti e in osservazione, rilevazione coppie
  potenzialmente ridondanti per correlazione (soglia 0,85)
- aggiunta simulazione Monte Carlo del portafoglio posseduto in
  Cruscotti/Analitica (Progetto B, `core/services/portfolio_simulation.py`):
  bootstrap storico dei rendimenti giornalieri pesati (non un modello
  gaussiano), fan chart a percentili annidati su 6/12/24 mesi, tabella
  mediana/P5/P95/probabilita' di perdita/VaR/CVaR; estratta
  `combine_weighted_returns` (`core/domain/returns.py`) come formula
  canonica unica di combinazione pesata rendimenti->portafoglio, riusata
  anche da SATOR
- aggiunta sezione "Perché questo voto" in Pianificazione (Progetto D,
  Explainability SATOR, `core/services/sator_explain.py`): per ogni
  strumento della classifica, contributo dei 5 fattori SATOR al voto finale
  su una scala 1-10 diretta, con distinzione visiva posseduto/osservato
- aggiunta sezione "Frontiera rischio/rendimento" in Pianificazione
  (Progetto A, SATOR Frontier, `core/services/sator_frontier.py`): confronto
  simulato (nessun ottimizzatore, nessuna stima di rendimento "atteso") tra
  portafoglio attuale, proposta SATOR e una modifica manuale via slider, con
  minimo-rischio e miglior Sharpe individuati su una nuvola di portafogli
  casuali; orizzonte storico selezionabile (6/12/24/36 mesi) e avvisi
  espliciti su strumenti esclusi per storico corto e su simulazioni poco
  informative quando il vincolo di concentrazione e' molto stretto rispetto
  al numero di strumenti
- archiviato (non urgente, per scelta esplicita) il quinto progetto del
  libro, storico decisionale con valutazione ex-post: la parte
  fotografie/confronto gia' esistente in Pianificazione copre in parte
  questo bisogno

## 5.0-pre - Coerenza dati posizioni chiuse, KPI Quotazioni e sezione Posizioni Chiuse

- corretto il conteggio KPI "Letture OK/Warning/Errori" in Quotazioni: una
  lettura stantia di uno strumento chiuso/rimborsato (fetch avvenuto prima
  della registrazione dell'evento di chiusura) veniva ricontata ad ogni
  refresh perche' `_refresh_volatile_quotes_runtime()` in `app.py` costruiva
  l'elenco strumenti da tutti quelli in portafoglio invece che dal solo
  sottoinsieme attivo (`ctx.chiusi_tickers`); stesso bug corretto nel toast
  "N/M aggiornati" della sidebar (`ui/sidebar.py`), che usava
  `len(data["strumenti"])` come denominatore invece del numero di strumenti
  effettivamente idonei al fetch
- rafforzato `build_quotes_diagnostic_table` (`core/quotes_runtime.py`):
  quando riceve un `quotes_refresh_df` gia' costruito (come fa sempre la
  pagina Quotazioni), `closed_tickers` ora filtra anche le righe gia'
  presenti, non solo il calcolo delle righe mancanti — uno strumento
  chiuso/terminale con una lettura ancora nel log non resta piu' visibile
  indefinitamente
- corretto il grafico "P/L per Categoria" (`ui/charts/overview.py`,
  `build_overview_time_chart`): la mappa categoria/ticker veniva costruita
  solo da `da` (posizioni aperte), quindi uno strumento chiuso perdeva
  l'intero contributo storico dal grafico impilato per categoria, per tutta
  la serie storica e non solo dopo la chiusura; aggiunto parametro `data`
  opzionale con fallback su `macro_cat()` per i ticker assenti da `da`
- corretta la tabella "Andamento dell'ultima settimana"
  (`core/services/analysis.py::build_weekly_pl_table`): gli strumenti chiusi
  durante la finestra di calcolo non comparivano piu' e il loro contributo
  spariva dal totale settimanale; aggiunta una seconda passata che recupera
  dalle colonne `PL_<ticker>` gli strumenti chiusi con storico valido,
  marcati con badge "chiuso" nel renderer (`ui/charts/portfolio_popup.py`)
- collegato il calendario scadenze BTP (`core/domain/calendar.py`,
  `ui/charts/calendario_btp.py`) ai dati fiscali reali del registro eventi:
  le righe "scadenza"/"cedola" ora usano `importo_lordo`/`imposte`/
  `importo_netto` degli eventi RIMBORSO A SCADENZA/CEDOLA effettivamente
  registrati (match per data entro 45 giorni) invece di una stima sintetica
  per aliquota, quando l'evento reale esiste
- corretta la firma di cache per-categoria (`core/cache_signatures.py`,
  `build_category_data_signature`): il conteggio operazioni era
  hardcodato a zero, quindi la cache dei Cruscotti per categoria non si
  invalidava mai all'aggiunta/rimozione di un evento (es. RIMBORSO); corretta
  anche la pseudo-categoria "Tutto", che non intercettava mai nessuno
  strumento
- aggiunta la sezione "Posizioni Chiuse" in Portafoglio
  (`ui/pages/home.py`, `ui/components.py`,
  nuovo `core/services/closed_positions.py`): tabella con capitale liberato,
  P/L realizzato lordo/netto, commissioni, imposte, rendimento % e
  cedole/dividendi netti per ogni posizione chiusa, sommando gli eventi di
  chiusura anche in caso di vendite parziali; rimossa la sezione duplicata
  precedentemente presente in Operazioni
- riordinato il KPI "Capitale Versato Residuo" in Overview (spostato da
  ultima a seconda posizione nella riga KPI)
- aggiunte etichette esplicite ai grafici P/L di Portafoglio e
  Cruscotti/Analitica per chiarire l'ambito temporale/perimetro (storico
  completo incluse posizioni chiuse, vs. sole posizioni aperte oggi)

## 5.0-pre - Governo cache applicativo centralizzato

- unificata la gestione degli strumenti chiusi (rimborsati a scadenza o
  venduti): stato aperto/chiuso/terminale sempre calcolato dal registro
  eventi (mai piu' dal campo `stato`, che non veniva aggiornato da nessun
  codice di produzione); nuovo `core/domain/instrument_status.py` con
  `active_fetch_tickers()` come unico filtro fetch quotazioni, usato da
  sidebar, runtime context, pagina Quotazioni e `tools/importa_quotazioni.py`
- introdotto `discharge_lot()` come unica definizione dello scarico PMC su
  vendita/rimborso, riusata da `compute_portfolio_state`, `_apply_event_to_pos`
  e `calcola_capitale_rientrato` al posto di quattro implementazioni
  indipendenti; soglia "posizione azzerata" unificata su `QTY_ZERO_EPS`
- ogni evento VENDITA/RIMBORSO A SCADENZA persiste ora `capitale_liberato`
  (quota di costo storico restituita, non reddito) e `plusvalenza_netta`
  (P/L realizzato al netto di commissioni/imposte), riallineati
  automaticamente dopo ogni inserimento/modifica/cancellazione evento e al
  caricamento dati (backfill retroattivo sugli eventi storici)
- nuovo KPI "Capitale Versato Residuo" in Overview: costo storico delle sole
  posizioni aperte, con invariante testato `capitale investito lordo ==
  capitale versato residuo + capitale rientrato`
- nuovo alert "titoli scaduti non ancora rimborsati" (GOV con scadenza
  passata e nessun evento RIMBORSO registrato), sempre visibile in Overview
- nuovo flag `osserva_prezzo` per strumento: uno strumento non-GOV venduto
  puo' restare nel fetch quotazioni su scelta esplicita dell'operatore
  (toggle nel form-server, tab Strumenti → Chiusi); i titoli di Stato
  rimborsati a scadenza restano sempre esclusi, senza eccezioni
- ricostruita la sezione "Posizioni Chiuse" di Operazioni sullo stato
  calcolato (prima non mostrava mai nulla per via del campo `stato` morto)
- bump della versione cache orchestrazione per forzare un refresh pulito
  dopo il refactor (evita AttributeError su cache preesistenti)
- introdotto `core/cache_orchestrator.py` come ingresso canonico per gli
  artefatti cache registrati: i moduli runtime ora chiedono un artefatto tramite
  `artifact_id`, mentre `page_id`, `layer`, `log_page` e provider arrivano dal
  registry centrale
- migrate le chiamate page-cache registrate di `app.py`, Quotazioni,
  Portafoglio, Dati, Mercati, Summary e Cruscotti su
  `get_or_build_registered_artifact`, lasciando `core.page_cache` come provider
  tecnico interno e non piu' come API architetturale di pagina
- aggiunto l'adapter `RegisteredFigureCacheAdapter`: le figure Plotly usano ora
  `get_registered_figure_cache()`/`get_or_build_registered_figure()` come
  ingresso registry-aware, mentre `core.figure_cache.FigureCache` resta lo store
  specializzato interno
- migrate su adapter registrato le chiamate FigureCache di prewarm, Summary,
  Cruscotti, Portafoglio, Quotazioni, Dati e analisi congelate
- portato sotto orchestratore anche lo store persistente delle analisi
  congelate: `core.frozen_analysis_cache` usa ora
  `load_registered_analytics_entry()` e `store_registered_analytics_entry()`
  invece di importare direttamente `core.analytics_payload_cache`
- portate sotto orchestratore anche le cache runtime in memoria:
  `market_data`, `cashflow_indices` e `StateManager` usano ora
  `get_registered_runtime_cache()`, lasciando `core.runtime_cache` come provider
  tecnico interno
- rimosso l'ultimo uso runtime di `streamlit.components.v1.html` dal log
  copiabile dei tempi: `ui.runtime_pages` usa ora il wrapper centrale
  `render_html_iframe()` basato su `st.iframe`, eliminando il warning di
  deprecazione Streamlit
- aggiornati i test di guardia per impedire il ritorno di accessi diretti a
  `get_or_build_page_artifact` e `get_figure_cache` nei moduli runtime gia'
  migrati
- rettificata la documentazione cache: la governance non viene piu' descritta
  come cache unica pienamente completata; la fase aperta e' ora
  l'orchestrazione concettuale unica dei provider specializzati
- reso idempotente il componente comune delle analisi congelate:
  Benchmark/Accumuli mostrano il pulsante solo quando manca l'analisi o quando
  la firma e' stale; se l'artefatto e' gia' fresco, non compare piu' il vecchio
  `Rigenera analisi ...`, evitando rebuild locali inutili a firma invariata
- ottimizzato il wrapper centrale `render_styled_table`: le tabelle dichiarate
  `static=True` vengono renderizzate come HTML statico dallo Styler, con fallback
  a `st.table`, evitando widget Streamlit inutili per tabelle descrittive
- migliorato il riepilogo storico del render log: oltre a mediana/min/max/p95
  mostra ora anche `ultimo_run` e `delta_vs_mediana`, cosi' i run recenti piu'
  veloci non vengono nascosti da mediane contaminate dai tempi pre-ottimizzazione
- corretto il riepilogo storico del render log: la sezione dei colli di
  bottiglia mostra ora solo le sotto-fasi ancora presenti nell'ultimo run,
  evitando che step rimossi o rinominati dopo la migrazione cache, come i vecchi
  build Mercati, restino indicati come problemi attuali
- corretto il refresh quotazioni quando i prezzi scaricati coincidono con il
  valore economico gia' presente nello storico: il riallineamento tecnico del
  campo `strumento.prezzo` non viene piu' classificato come variazione materiale
  e quindi non genera `cache_bust` globale, rebuild Cruscotti/Report o nuovo
  `instruments_hash` senza reale delta prezzo
- corretto il binding del wrapper Plotly: `st._portfolio_safe_plotly_chart`
  viene ricreato a ogni script-run usando l'originale Streamlit, cosi' il reset
  del contatore key colpisce la funzione effettivamente usata e i rerun non
  avanzano da `plotly_97` a `plotly_193`
- reso idempotente il salvataggio impostazioni: `save_settings()` non riscrive
  piu' `portafoglio_settings.json` se il payload normalizzato e' identico e
  ritorna `False`; la pagina Setup non genera piu' `cache_bust`, force reload e
  dirty flags `cruscotti/reports/settings` quando l'utente preme Salva senza
  cambiare davvero nulla; il render log registra invece uno scenario
  `settings_noop` senza invalidazione
- avviata la fase di tuning render UI senza cambiare navigazione: il wrapper
  centrale `ui.charts.streamlit_runtime.safe_plotly_chart` prepara tema e
  annotazioni Plotly una sola volta per oggetto figura nel processo, invece di
  ripetere la pulizia a ogni rerun sugli stessi oggetti gia' serviti dalla cache
- stabilizzate le key automatiche dei grafici Plotly: il contatore `plotly_N`
  viene azzerato a inizio script-run, evitando che rerun successivi producano
  chiavi sempre nuove (`plotly_135`, `plotly_136`, ...) e costringano Streamlit
  a trattare gli stessi grafici come widget nuovi
- il wrapper Plotly imposta ora una configurazione base uniforme
  `responsive=True` e `displaylogo=False`, rispettando eventuali config locali
  gia' passate dai singoli renderer
- isolata la diagnostica profiling dagli smoke test Streamlit: con
  `PORTFOLIO_TESTING=1` l'app non legge e non scrive piu' i file reali
  `.data/.profiling_state` e `.data/.profiling_signature_parts.json`, evitando
  falsi `signature_changed` dal micro-portafoglio di test al portafoglio reale
- confermato dal render log 2026-08-03 00:49 che la firma reale resta stabile:
  `profiling_cache_condition=signature_unchanged`, `signature_diff: none`,
  `page_cache_runtime=process_entries=14; session_entries=14`; il tempo residuo
  e' render UI completo, soprattutto Cruscotti, non rebuild cache/dati
- aggiunto `core/runtime_cache.py`, adapter unico per cache runtime in memoria:
  ogni cache deve essere legata a un artifact del registry, con `clear_group`,
  statistiche, limite LRU e invalidazione controllata
- migrate su `core.runtime_cache` le cache lookup prezzi/ISIN di
  `core.market_data`, eliminando i dizionari globali opachi per prezzi runtime
  e mapping ISIN->ticker
- migrate su `core.runtime_cache` le cache degli indici cashflow intermedi in
  `core.cashflow_indices`, mantenendo invariati calcoli e copie difensive dei
  DataFrame
- collegata al provider runtime registrato la cache eventi per strumento dello
  `StateManager`, mantenendo compatibilita' con i test che la sostituiscono con
  un dict isolato
- riclassificate in `core/cache_policy.py` le famiglie non-page-artifact da
  `legacy_provider` a `registered_provider`: FigureCache, derived runtime,
  cashflow intermedi, benchmark series, market lookup e frozen payload store
- aggiunti test di guardia per impedire il ritorno di provider legacy e per
  verificare che le cache runtime usino l'adapter centrale
- aggiornato `STATO_OPERATIVO_5.0_PRE.md`: la governance registry/page-cache e'
  avanzata, ma l'orchestrazione unica resta una fase architetturale da chiudere
  prima del tuning fine delle singole pagine
- aggiunto
  `docs/archivio_5_0/RIPRESA_ORCHESTRAZIONE_CACHE_2026-08-03.md` come documento
  di continuita' per sospendere la fase cache e ripartire senza ricostruire il
  contesto: include stato reale, provider gia' migrati, residui, divieti e
  primo comando di indagine

## 5.0-pre - Pulizia documentazione e dati non operativi

- ripulita la root documentale: lasciati in evidenza solo `README.md`,
  `CHANGELOG.md` e `STATO_OPERATIVO_5.0_PRE.md`
- spostati i documenti storici di piano/cache/render in
  `docs/archivio_5_0/`, con README di orientamento e regola di prevalenza dello
  stato operativo principale
- spostata la roadmap del progetto libro in `docs/progetti/` e il PDF sorgente
  in `docs/fonti/`
- ripulita `data/portfolio`: lasciati solo i file operativi
  `portafoglio_data.json`, `portafoglio_snapshots.json` e
  `portafoglio_sator_decisions.json`
- spostati i backup/manuali e gli snapshot storici in
  `data/forensic/portfolio/`, senza cancellare nulla e con README esplicativo
- aggiornati `README.md` e `STATO_OPERATIVO_5.0_PRE.md` per riflettere la nuova
  struttura e ridurre il rischio di usare documenti o dati non vivi

## 5.0-pre - Chiusura operativa fase cache L1-L3

- chiusi gli ultimi artefatti cache rimasti `planned` nel registry:
  `mercati.live_snapshot`, `summary.report_payload`,
  `confronto.comparison_report`, `cruscotti.benchmark_frozen_analysis`,
  `cruscotti.accumuli_frozen_analysis` e `prebuild.registry_engine` passano a
  contratto `pilot`
- aggiunto `iter_prebuild_artifact_specs()` in `core/cache_policy.py` e collegato
  `ui/prewarm_bundle.py` al registry, con distinzione fra target prebuild noti e
  target realmente costruiti
- aggiunti test di guardia: il registry non deve piu' contenere artefatti
  `planned` e il prewarm deve esporre la propria copertura rispetto al registry
- corretto il tracciamento delle azioni isolate: `Aggiorna mercati` non chiama
  piu' `invalidate_portfolio_cache` e registra `market_refresh_isolated`;
  `Genera report` registra `summary_report_isolated`, evitando che il render log
  mostri una vecchia decisione cache non pertinente
- aggiunto lo stesso tracciamento isolato alle analisi congelate Cruscotti:
  `Analizza benchmark` registra `benchmark_frozen_analysis_isolated` e
  `Analizza accumuli` registra `accumuli_frozen_analysis_isolated`, senza cache
  bust globale
- aggiunti due artefatti cache Mercati ufficiali: `mercati.overview_rows` e
  `mercati.base100_frame`; i derivati pesanti della pagina vengono ora letti da
  `core.page_cache` con firma Mercati e codec raw-pickle, mentre aperto/chiuso e
  ora locale restano aggiornati live senza ricostruire i ritorni
- rettificata la chiusura: `CHIUSURA_FASE_CACHE_5.0.md` chiude solo il pilota
  registry/page-cache L3, non la cache unica applicativa
- aggiunto `CACHE_UNICA_5.0_MIGRAZIONE_DEFINITIVA.md` come piano vincolante per
  completare davvero la cache unica 5.0: censimento, registry, FigureCache,
  derived runtime, benchmark/Mercati, frozen analysis, prewarm, diagnostica e
  Definition of Done
- aggiunto `tools/cache_surface_audit.py`, audit statico ripetibile che censisce
  Streamlit cache, page artifacts, FigureCache, session cache, module cache,
  cache persistenti, prewarm e frozen analysis
- registrate in `core/cache_policy.py` anche le famiglie cache residue
  (`runtime.orchestration_payload`, risorse Streamlit, FigureCache,
  derived runtime, cashflow intermedi, benchmark series, market lookup, frozen
  payload store e prebuild registry), portandole dentro un contratto esplicito
  senza cambiare ancora il runtime
- rimossa la cache privata processo/sessione dei bundle categoria Cruscotti in
  `ui/dashboard_bundles.py`: `cruscotti.category_dashboard_bundles` usa ora solo
  lo store ufficiale `core.page_cache` per sessione, processo, disco e build,
  eliminando un doppio layer opaco
- migrata la cache delle metriche categoria Cruscotti da `@st.cache_data`
  locale a nuovo artefatto registrato `cruscotti.category_metrics`, mantenendo
  invariata la funzione finanziaria `build_category_dashboard_metrics`
- migrata la cache dei dataset finanziari avanzati di Analitica da
  `@st.cache_data` locale a nuovo artefatto registrato
  `cruscotti.advanced_analysis_data`, con lettura sessione/processo/disco/build
  dallo store ufficiale e senza cambiare la navigazione a tab gia' pronte
- rimossi i builder `st.cache_data` interni del bundle Quotazioni: il bundle
  generale usa `quotazioni.dataset_bundle` e i dettagli ticker per categoria
  usano `quotazioni.category_ticker_bundles`, entrambi via registry/page-cache
- rimossa la cache `st.cache_data` dei dataset categoria Cruscotti in
  `core/dashboard_datasets.py`: la cache resta governata dal bundle registrato
  `cruscotti.category_dashboard_bundles`
- migrato il payload condiviso Summary a `summary.dashboard_payload`, rimuovendo
  il builder `st.cache_data` e la cache manuale `session_state` del payload
- migrato l'export PHP remoto della pagina Dati a `dati.remote_php_export`,
  eliminando l'ultimo `st.cache_data` locale dalla pagina Dati
- migrata l'orchestrazione iniziale da `orchestrate_data_cached` con
  `st.cache_data(persist="disk")` a `runtime.orchestration_payload` su
  registry/page-cache raw-pickle, mantenendo `refresh_volatile_ctx_fields` dopo
  il caricamento del payload
- irrobustiti gli smoke test Streamlit: la fixture ora monta un micro-portafoglio
  temporaneo e ripristina i file dati al termine, evitando che i test dipendano
  dal contenuto locale corrente della copia `5.0-pre`
- corretto `core.quotes_runtime.build_quotes_refresh_df`: anche con log
  quotazioni vuoto o interamente filtrato restituisce uno schema colonne stabile,
  senza far saltare l'orchestrazione iniziale
- corretto `core.services.cruscotti.build_operations_report`: le colonne
  opzionali delle operazioni, inclusa `note`, vengono normalizzate prima del
  report, cosi' import storici o incompleti non generano `KeyError`
- riallineati gli smoke test alla navigazione attuale a 11 tab native,
  includendo la pagina `Mercati`
- corrette le firme render delle analisi congelate Benchmark e Accumuli:
  l'analisi finanziaria resta congelata, ma le figure vengono invalidate quando
  cambiano tema o impostazioni grafici, evitando grafici con stile vecchio dopo
  un cambio palette
- aggiornati stato operativo, TODO, strategia e inventario per distinguere in
  modo netto il pilota completato dalla migrazione cache unica ancora aperta
- registrata in `RENDER_BASELINE_2026-08-02.md` la misura finale di chiusura
  del log 19:43: firma invariata, 7 artefatti page-cache in sessione/processo,
  Cruscotti raw-pickle da disco e artefatti gzip residui misurati solo in pochi
  millisecondi
- aggiunto test documentale per impedire che piano, strategia, TODO e chiusura
  cache tornino a divergere

## 5.0-pre - Copia di lavoro per maturazione 5.0

**Baseline:**
- copia fisica della versione funzionante `4.9.40`, creata prima degli interventi strutturali verso la 5.0
- versione applicativa aggiornata a `5.0-pre`; schema dati invariato
- obiettivo della copia: consolidare legacy, form-server, schema dati, cache diagnostica, setup e hardening dei calcoli senza perdere il punto stabile 4.9.40
- aggiunto `STATO_OPERATIVO_5.0_PRE.md` come documento unico di governo: raccoglie principi, cosa e' stato fatto, stato performance, backlog ordinato e cose da non fare; `TODO_5.0.md` e' stato ripulito e ridotto alle sole attivita' aperte
- aggiunto `ARCHITETTURA_5.0.md` come documento guida: modularita' al centro, tema unico centralizzato, formule finanziarie canoniche nel core, impostazioni grafici centralizzate e dataset condivisi prima della UI
- aggiunto `REGOLE_NON_NEGOZIABILI.md` come documento operativo da leggere prima di modificare rendering, navigazione, cache, formule, tema o layout: sancisce il principio "preparare prima, navigare senza sorprese" e vieta render/rerun intermedi non richiesti
- aggiunto `PIANO_UNICO_CACHE_RENDER_5.0.md`: piano operativo unico per rifondare cache, pre-render, invalidazioni e diagnostica tempi con registry centrale, store unico, prebuild coerente e migrazione graduale delle pagine senza render intermedi durante l'uso
- avviata la Fase 1/2 del piano cache 5.0: aggiunto `CACHE_INVENTORY_5.0.md`, introdotto `core/cache_policy.py` come registry centrale degli artefatti e collegata la diagnostica Quotazioni `quotazioni.diagnostic_table` al nuovo contratto senza cambiare la resa della pagina
- avviata la Fase 3 della cache 5.0: `core/page_cache.py` mantiene ora un manifest JSON degli artefatti pagina, espone statistiche/righe diagnostiche e clear selettivo; Dati mostra anche gli artefatti pagina accanto alla cache figure, evitando che il nuovo layer L3 resti invisibile nei render log
- aggiunta riconciliazione automatica del manifest artefatti pagina: se Dati trova il manifest vuoto ma esistono gia' file `.pickle.gz` su disco, ricostruisce l'indice senza rigenerare gli artefatti, cosi' il KPI `Artefatti pagina` non resta falsamente a zero dopo l'introduzione del nuovo store L3
- portato `portafoglio.positions_table` da artefatto pianificato a pilota reale: la sezione "Controvalore del Portafoglio" recupera ora da `core/page_cache.py` il payload registrato nel registry, con DataFrame posizioni, frecce giornaliere, report giornata e insight gia' pronti; la resa UI resta invariata ma il render log mostra `L3 page artifact positions_table` con sorgente `session/process/disk/build`
- irrobustito il clone degli artefatti pagina: i payload annidati (`dict`/`list` con DataFrame o oggetti interni) vengono copiati in profondita' quando richiesto, evitando mutazioni accidentali della cache condivisa tra sessione, processo e disco
- aggiunto il terzo pilota cache 5.0 `cruscotti.category_dashboard_bundles`: il bundle categorie dei Cruscotti passa ora dal registry e da `core/page_cache.py`, mantenendo il builder esistente e le tab Streamlit native; il render log deve mostrare `L3 page artifact category_dashboard_bundles` con sorgente `session/process/disk/build`
- aggiunto il quarto pilota cache 5.0 `cruscotti.analitica_bundle`: il bundle Analitica dei Cruscotti passa ora dallo stesso registry/page-cache L3 dei piloti gia' attivi, riusando le figure Plotly cacheate e tracciando nel render log `L3 page artifact analitica_bundle` senza cambiare `st.tabs` o introdurre render on-demand
- aggiunto il quinto pilota cache 5.0 `dati.quality_table`: la tabella "Qualita dati strumenti" non usa piu' una cache locale separata in Dati, ma passa dal registry e da `core/page_cache.py` con firma esplicita, clone sicuro del DataFrame e log `L3 page artifact quality_table`
- aggiunto il sesto pilota cache 5.0 `dati.cache_diagnostics`: le statistiche cache della pagina Dati passano ora dal registry/page-cache senza finestra TTL, con invalidazione su azioni cache esplicite e lettura basata su manifest, eliminando il vecchio dizionario process locale e rendendo tracciabile `L3 page artifact cache_diagnostics`; il log pagina usa ora l'etichetta `cache diagnostics`, non piu' `build cache stats`
- corretto il collo di bottiglia della diagnostica cache Dati emerso nel primo avvio del 02/08/2026: il payload non viene piu' invalidato solo per passaggio del tempo e non cammina piu' ricorsivamente su `data/cache` durante il render ordinario; `FigureCache.get_stats()` usa il manifest quando disponibile
- rimossa la manutenzione automatica della cache figure dal costruttore di `FigureCache`: migrazione legacy, rimozione orfani e applicazione limiti restano disponibili tramite l'azione esplicita "Ottimizza cache", ma non vengono piu' eseguite nel percorso di avvio ordinario
- introdotto `PROTOCOLLO_PERFORMANCE_5.0.md` e collegato ai documenti guida: ogni intervento su cache/render/prewarm/diagnostica deve ora partire da scenario misurato, ipotesi falsificabile, classificazione L0-L4, test di regressione e confronto prima/dopo
- aggiunto `tools/perf_render_log_analyzer.py`: analizzatore offline dei render log che estrae totale, tempi pagina, gap profiling, eventi esclusivi, hit/miss cache e rebuild L3; serve come base ripetibile per valutare i prossimi interventi performance senza procedere a sensazione
- vettorializzato `core.services.analysis.build_pl_delta_series`: la serie delta P/L giornaliera non scorre piu' riga per riga con `iloc`, ma usa `diff()`/maschera Pandas mantenendo la regola finanziaria degli strumenti validi in entrambe le date; riduce il collo `Portafoglio/UltimaGiornata / build delta series` senza cambiare numeri
- aggiunta profilazione interna alla tabella popup Quotazioni: il prossimo render log distingue lettura strumenti freschi, build mappa holdings, raggruppamento log e render iframe dentro `render tabella diagnostica quotazioni`, cosi' si capisce dove vanno i 0,6-0,7 s residui
- rimosso I/O improprio dal renderer popup Quotazioni: `render_quotes_table_with_popup` non richiama piu' `load_data()` durante il render ordinario, ma usa l'anagrafica gia' presente nel payload pagina; il log aveva misurato `Quotazioni/TablePopup / load fresh instruments for popup` a 0,701 s e la verifica successiva porta `render tabella diagnostica quotazioni` a 0,056 s
- corretta la pulizia legacy del grafico Quotazioni `quotazioni_instrument_performance_time_v2`: la compatibilita' MAX/MIN resta governata dalla firma figura (`extrema_logic_version` e `portfolio_reference`), ma non viene piu' cancellata la cache disco per pattern a ogni nuova sessione, evitando il `cache_miss` ricorrente all'avvio
- aggiunta profilazione granulare del render Cruscotti/Analitica: il prossimo report tempi separa intro, grafici principali, metriche avanzate, tabella rischio/rendimento, heatmap, target, contributo rischio e radar senza cambiare tab, cache, calcoli o navigazione
- alleggerito il render L4 delle tabelle P/L per orizzonte in Cruscotti: le cinque tabelle categoria/Tutto non passano piu' da Pandas Styler + `st.table`, ma da un renderer HTML statico dedicato che preserva colori, frecce trend, parziali e riga totale; nessun lazy render e nessun cambio di calcolo/cache
- stabilizzato il render delle figure congelate Benchmark/Accumuli: le analisi restano rigenerabili solo da pulsante, ma le figure derivate passano ora dalla `FigureCache` HYBRID persistente invece che da cache solo di sessione; dopo reload/process reset il sistema deve poter leggere da disco i grafici gia' costruiti e non ricostruire automaticamente prezzo vs PMC, capitale vs valore, overview accumuli, confronto benchmark e scatter coerenza
- aggiunta diagnostica di continuita' runtime nel report rendering: ogni log mostra ora `process_pid`, `process_token`, eta' modulo runtime, `session_token`, progressivo sessione e snapshot memoria/sessione di `core.page_cache`, cosi' si distingue un vero warm rerun da un riavvio processo/sessione prima di intervenire sulle prestazioni
- corretta la classificazione scenario del render log: il progressivo sessione viene registrato in `app.py` a inizio run e non incrementato dal log; un primo avvio di sessione/processo con firma dati gia' nota viene classificato come `first_session_run` e non come `warm_rerun`, mentre `profiling_cache_condition` separa firma assente, cambiata o invariata
- collegato il bundle shared Quotazioni al contratto cache 5.0: nuovo artefatto `quotazioni.dataset_bundle` in `core/cache_policy.py`, wrapper `core.page_cache` dentro `core.dashboard_datasets.get_quotazioni_dataset_bundle` e log esplicito `cached bundle shared source` con sorgente `session/process/disk/build`; la UI resta completa e pre-renderizzata
- separata la firma semantica del portafoglio dai dati benchmark/mercati: `app.py` non include piu' `include_benchmark_data=True` nella firma globale usata per classificare `signature_changed`, evitando falsi avvii freddi quando cambia solo `benchmark_points_hash`; il diff profiling continua invece a mostrare i benchmark come diagnostica separata
- confermata dal render log 2026-08-02 17:50 la stabilizzazione della firma (`profiling_cache_condition=signature_unchanged`, `signature_diff:none`) e il recupero L3 di Quotazioni: `quotazioni.dataset_bundle source=disk` in circa 0,005 s e `load/build cached bundle shared` in circa 0,008 s; la prossima priorita' performance passa quindi a Cruscotti
- ottimizzata la lettura disco degli artefatti Cruscotti pesanti: `core/page_cache.py` supporta ora anche codec raw-pickle opzionale, con fallback automatico dai vecchi `.pickle.gz`; `cruscotti.category_dashboard_bundles` e `cruscotti.analitica_bundle` lo usano per ridurre CPU/latenza di deserializzazione senza cambiare tab, render completo o UX
- esteso il log degli artefatti L3 con il dettaglio codec (`codec=pickle`, `codec=gzip` o migrazione `codec=gzip->pickle`), cosi' i prossimi render log distinguono una vera lettura raw-pickle da un run di fallback/migrazione legacy
- confermato dal render log 2026-08-02 18:43 che gli artefatti Cruscotti pesanti leggono davvero da raw-pickle (`codec=pickle`): Cruscotti scende a circa 4,882 s e il totale a circa 11,420 s; il collo residuo e' quindi render UI full-tabs, non piu' fallback/migrazione del page artifact
- aggiunta `ANALISI_DEFINITIVA_RENDER_CACHE_5.0.md`: formalizzata la diagnosi sul limite strutturale della sola cache L1-L3 in Streamlit e definito il prossimo salto architetturale corretto, cioe' snapshot render L4 per sezioni read-only pesanti, partendo da Cruscotti
- spostato in sperimentale il pilota L4 Render Snapshot su Cruscotti categorie dopo blocco in avvio al passo 4/11: i file sono conservati in `experimental/l4_render_snapshot_pilot/`, ma rimossi da `core/`, `ui/`, registry operativo, Setup e configurazione persistente; Cruscotti usa solo il renderer nativo finche' non esiste una pipeline di prebuild fuori-render
- ripristinata la regola architetturale non negoziabile dopo il tentativo errato di pagina singola: la navigazione principale resta a linguette Streamlit native e pre-renderizzate, senza radio/selettori che sostituiscano le tab; Quotazioni non mostra piu' il radio Rapida/Completa e viene preparata in vista completa
- esteso il registry cache 5.0 con il contratto per artefatti ad azione esplicita (`trigger`, `rerun_policy`, `action_scope`) e registrati come pianificati Summary report, Confronto report, Mercati live snapshot, Cruscotti Benchmark congelato e Cruscotti Accumuli congelato; questi lavori devono essere isolati dal rerun globale e riusabili dopo il click
- aggiunto test di regressione su `core.page_cache`: un artefatto letto da disco deve essere promosso in sessione/processo e non ricaricato da disco nei recuperi successivi con la stessa firma
- salvata la prima baseline render reale in `RENDER_BASELINE_2026-08-02.md`: warm rerun completo da 12,371s con colli di bottiglia principali Cruscotti, Dati e Quotazioni; confermato che Mercati non pesa sul flusso base e che il costo Plotly puro non e' il problema principale
- rinominata in Dati la sezione "Arricchimento strumenti" in "Qualita dati strumenti": la tabella ora consuma il dataset centrale `core/services/instrument_quality.py`, combinando anagrafica arricchita, completezza, fonte, storico prezzi, buchi, prezzo fermo, copertura e prima azione operativa senza duplicare formule nella UI
- resa piu' leggibile la tabella "Qualita dati strumenti": ripristinata la `ProgressColumn` Streamlit originale per la completezza di arricchimento, rimosso lo score tecnico dalla vista utente, tolte le metriche rischio/rendimento dalla tabella principale e aggiunto un commento operativo sui controlli da leggere
- ampliato il dataset e la tabella "Qualita dati strumenti" con letture operative non finanziarie: Fonte abbreviata (`Aut`, `Pdf`, `Man`), Copertura dello storico e prima azione "Da sistemare", calcolate nel core e non nella UI
- compattate le colonne di "Qualita dati strumenti" con larghezze numeriche in pixel invece delle classi Streamlit `small/medium`, mantenendo tutte le colonne e usando intestazioni finali piu' leggibili (`Qualita`, `Arricchito`, `Arricc. il`, `Storico`, `Azione`)
- ottimizzato avvio e refresh quotazioni: il launcher salta `pip install` quando le librerie sono gia' presenti, i BTP non cadono piu' su Yahoo dopo un miss di Borsa Italiana e il bottone "Aggiorna Quotazioni" scarica i prezzi in parallelo mantenendo invariata la logica di commit finanziario
- aggiunta strumentazione preliminare per il debug dei tempi: log strutturati `APP_PHASE`, `PAGE_RENDER`, `DASHBOARD_RENDER`, `QUOTE_FETCH` e `QUOTE_REFRESH`, storico render salvato anche nei run standard e sottofasi Pianificazione/SATOR profilate senza modificare calcoli o layout
- consolidata la barra azioni del log rendering in un unico micro-componente: `Scarica log rendering .txt` e `Copia negli appunti` sono due bottoni HTML identici; lo scarico usa un `Blob` JavaScript invece di `data:` URI o widget Streamlit separati
- corretto il funzionamento reale di `Copia negli appunti`: il micro-componente del report rendering ora usa `streamlit.components.v1.html`, che esegue JavaScript, e tenta automaticamente il fallback `execCommand` se la Clipboard API del browser viene negata
- estesa la strumentazione tempi della pagina Dati: il report render ora distingue qualita' dati strumenti, statistiche cache, lettura log, diagnostica runtime e controlli integrita', evitando che la pagina resti una scatola nera quando pesa diversi secondi nel render complessivo
- corretto lo storico render in modalita' debug completa: la run corrente viene salvata prima di calcolare `Storico render comparabili`, cosi' il riepilogo non resta ancorato a vecchi run piu' lenti e non contraddice il totale appena misurato
- portato il report rendering debug a `render-log-v1+deep-v4` con riga `diagnostic_features`, cosi' e' immediato riconoscere se il log copiato arriva dal codice aggiornato o da una sessione Streamlit ancora vecchia
- corretto l'abbinamento tra tempi pagina e sottofasi nel report rendering: tab con emoji o nomi compatti (`Dati`, `Mercati`, `Setup`, `AI`) vengono ricondotte allo stesso nome canonico usato dai `profile_step`
- alleggerita la sezione "Qualita dati strumenti": la pagina Dati usa il dataset gia' caricato nel run e richiede al servizio centrale solo la modalita' leggera, evitando calcoli di rendimenti/volatilita'/Sharpe non mostrati in quella tabella
- alleggerito il flusso `Aggiorna Quotazioni`: il launcher non forza piu' il profiling Plotly a ogni avvio e il click prezzi non scarica piu' anche i benchmark; benchmark e pagina Mercati restano aggiornati tramite scheduler/refresh dedicato, evitando circa 10 secondi di lavoro extra nel caso misurato del 2026-08-01
- reso non bloccante il pre-render grafici: la configurazione corrente e il default non usano piu' `initial_complete=true`, quindi la preparazione cache parte in background quando serve invece di aggiungere tempo sincrono al caricamento; Setup ora descrive chiaramente la differenza tra background consigliato e blocco avvio tecnico
- blindato il pre-render contro i blocchi nei rerun caldi: anche se l'opzione tecnica `initial_complete` resta attiva in una vecchia sessione, `app.py` puo' eseguire il pre-render sincrono solo su vero `cold_start`; su `warm_rerun` ora rinvia anche il background automatico e il log lo dichiara nel dettaglio
- alleggerite le diagnostiche della pagina Dati: le statistiche cache e la scansione cartella cache sono riusate per 30 minuti in sessione, evitando I/O ripetuto nei rerun ravvicinati del report tempi
- aggiunta diagnostica esplicita per la cache bundle di Cruscotti: il report distingue `cache hit dashboard categoria completo` e `cache miss dashboard categoria completo`, rendendo verificabile se i 2+ secondi del bundle sono build reale o perdita cache
- irrobustita la cache del bundle categoria Cruscotti: oltre a `st.session_state` viene mantenuto un fallback leggero nel processo Streamlit, con log `source=session/process`, per evitare rebuild completi nei rerun caldi con firma dati invariata
- preservato il comportamento pre-renderizzato di Cruscotti: le sottoschede restano `st.tabs` native e vengono preparate prima dell'uso, evitando render intermedi/rerun durante la navigazione interna; le ottimizzazioni devono agire su cache e calcolo anticipato
- aggiunta cache persistente e profiling per le metriche KPI dei cruscotti categoria: `build_category_dashboard_metrics` resta nel core finanziario, ma la UI riusa il payload per firma dati/categoria e il render log mostra `load/build metrics`
- alleggerita ulteriormente la pagina Dati: il dataset "Qualita dati strumenti" resta calcolato dal servizio core, ma viene riusato con `st.cache_data(persist="disk")` su firma dati/giornata; la diagnostica cache passa da 30 secondi a 30 minuti e viene invalidata solo dopo azioni cache esplicite, riducendo rebuild e scansioni disco nei rerun ravvicinati
- reso spiegabile il tempo della sezione Qualita dati strumenti: il dataset ora usa anche cache esplicita sessione/processo e il render log indica la sorgente (`session`, `process`, `streamlit_cache`) invece di mostrare solo una firma troncata poco utile
- raffinata la diagnostica della pagina Dati dopo il nuovo render log: sorgente qualita rinominata in `streamlit_cache`, aggiunti marker per inventario file, bonifica e generazione PHP remoto, evitato il `load_data()` ordinario nella bonifica chiusa ricaricando il JSON fresco solo quando si preme l'azione distruttiva
- impedito l'avvio automatico del prewarm background nei `warm_rerun`: se il cooldown scade mentre l'utente sta usando l'app, il pre-render viene registrato come `deferred_warm_rerun` invece di costruire grafici in background e contendere CPU durante la navigazione
- superato il vecchio fallback temporale per le statistiche cache della pagina Dati: la scansione `data/cache` non fa piu' parte del render ordinario e la diagnostica deve leggere manifest/cache persistente invece di dipendere da finestre da 30 minuti
- resa la pagina Mercati on demand: nei rerun standard mostra solo un pannello leggero con stato cache e pulsante `Rigenera Mercati`; radar, mappe, tabelle e base 100 vengono costruiti solo su richiesta o subito dopo il refresh manuale Mercati, togliendo il costo della tab opzionale da avvio e aggiornamento prezzi
- ripristinata la navigazione standard in fondo a Mercati, anche nel pannello on-demand: icone/pulsanti Precedente, Torna in cima e Successiva usano il componente condiviso `back_to_top`, coerente con il resto dell'app
- creato rollback fisico prima della sperimentazione Pianificazione/SATOR v2: `portfolio_beta_5.0-pre_backup_before_planning_sator_v2_20260727`
- aggiunto auto-refresh silenzioso della pagina Mercati configurabile da Setup: un worker idempotente aggiorna in background cache live e storico 6 mesi senza forzare rerun Streamlit; impostazione spenta di default, intervalli configurabili e stato interno tracciato in `data/cache/market_auto_refresh_state.json`
- rimossa la scrollabilita' orizzontale dalle tabelle Mercati: resa statica compatta con layout fisso al 100%, indice nascosto, colonne percentuali e testi lunghi gestiti senza trascinamento laterale
- uniformato il colore stato Mercati: `Aperto` resta verde, `Chiuso` ora viene evidenziato in rosso nella tabella Mercati e nella striscia informativa
- aggiunto semaforo di aggiornamento nella pagina Mercati: valuta copertura prezzi, copertura live e anzianita' dell'ultimo refresh per indicare Dati freschi, Aggiornamento consigliato o Aggiorna ora accanto al pulsante
- aggiunto l'orizzonte 3 mesi alla Mappa forza relativa Mercati: il builder calcola `ret_3m` su circa 63 sedute e la griglia mostra ora 1g, 5g, 1m, 3m e YTD senza allargare le tabelle dati
- alleggerito il peso tipografico della pagina Mercati: mappa forza relativa, barre area, chip e label sezione non usano piu' grassetti 900/950 ovunque, mantenendo enfasi solo sui valori principali
- compattata la Mappa forza relativa HTML in Mercati dopo verifica visiva: etichette e celle riportate a proporzioni da tabella decisionale, mantenendo leggibilita' senza ingombro eccessivo
- sostituita la resa Plotly della Mappa forza relativa in Mercati con una griglia HTML/CSS controllata: etichette di sezioni/indici a dimensione reale, numeri delle celle a 13.5px e barre di forza per area allineate sotto, evitando autoscale e compressioni del wrapper Streamlit/Plotly
- riequilibrata la tipografia della Mappa forza relativa in Mercati: numeri nelle celle ridotti, label indici/aree rese molto piu' leggibili tramite tick label Plotly reali, chip/sezioni HTML ampliati e test aggiornati per bloccare la gerarchia corretta
- arricchita la card gia' esistente "Fotografia di riferimento" in Pianificazione con giudizio SATOR, uso budget e alert principali; rimossa la card pilota separata per non duplicare la mappa decisionale gia' presente
- rivista la tabella "Ultime quotazioni aggiornate": font minimo 13px, proporzioni colonne esplicite tramite `colgroup`, layout fisso e nessuno scroll orizzontale
- corretta la logica di `Var gg €`/`Var gg %` nella tabella "Controvalore del Portafoglio": la variazione giornaliera viene calcolata in modo coerente dalla stessa fonte prezzo e dal controvalore della riga; il renderer ricostruisce il delta economico se riceve una percentuale materiale con euro nullo, evitando combinazioni fuorvianti come percentuale negativa e importo zero
- resa coerente la colorazione di `Var gg €` e `Var gg %` nella tabella "Controvalore del Portafoglio": quando la percentuale arrotonda a `0,00%` ma il delta economico ha segno materiale, eredita lo stesso colore; le righe in cui la variazione giornaliera fa attraversare lo zero del P/L vengono evidenziate sulle celle P/L con tooltip dedicato
- riallineata la definizione di "ultima giornata" in Home: tabella portafoglio, sintesi, conteggio su/giu' e best/worst ora usano la stessa mappa giornaliera basata sulle due ultime date globali di mercato; i ticker con prezzo fermo a una data precedente non trascinano piu' movimenti vecchi nella giornata corrente
- il grafico Profit/Loss dell'ultima giornata ignora eventuali righe sintetiche successive all'ultima data reale dello storico prezzi, evitando delta fittizi o confronti su giornate non quotate
- aggiunti test di invariante contabile sulle posizioni base: `Controvalore = Quote x Prezzo`, `P/L € = Controvalore - Costo` e `P/L % = P/L € / Costo`, cosi' la suite verifica non solo la presenza delle colonne ma anche la coerenza numerica tra i campi mostrati
- arricchito SATOR v2 con metriche post-acquisto: la classifica standalone mostra ora impatto sul target (`Imp`), stato cap di concentrazione (`Cap`) e qualita' dati (`Dato`); le stesse metriche vengono ricalcolate al salvataggio della fotografia anche se l'utente modifica manualmente le quantita'
- aggiunta in SATOR standalone la spunta `Includi commissioni non zero`: attiva di default per preservare il comportamento precedente, ma se disattivata esclude dall'universo gli strumenti non marcati a zero commissioni invece di limitarli a una penalita' nel fattore costo
- trasformata la classifica SATOR in una prima decision table operativa: filtri rapidi client-side per suggeriti, target migliorato, cap rispettato, dati solidi e zero commissioni; nessun rerun Streamlit per filtrare la tabella
- aggiunto ordinamento client-side della decision table SATOR per voto, impatto target, margine cap, qualita' dati e prezzo, mantenendo il filtro attivo e le quantita' gia' inserite
- potenziata la `Valutazione live` SATOR: oltre a budget, ripartizione e voto medio mostra ora impatto target, stato dei cap natura e qualita' media dei dati sull'ordine selezionato, ricalcolando questi valori sulle quantita' inserite manualmente
- arricchito lo storico fotografie SATOR con confronto target/cap/dati per ogni decisione salvata e con dettaglio riga ordine che mostra impatto, margine cap e qualita' dati dello strumento
- reso piu' leggibile lo storico decisionale SATOR: le fotografie sono raggruppate per mese con riepilogo importi/foto e, quando presente `actual_order`, viene mostrato il confronto immediato tra proposta salvata e ordine effettivo
- aggiunta nello storico SATOR la registrazione dell'ordine effettivo: dal dettaglio di una fotografia si possono salvare quantita'/prezzi eseguiti, aggiornando solo il registro decisionale via POST nella pagina standalone, senza modificare il portafoglio e senza rerun Streamlit
- aggiunta una sintesi di aderenza esecuzione nello storico SATOR: sulle fotografie con eseguito registrato mostra numero di foto concluse, aderenza media all'importo proposto, delta totale e strumenti saltati/aggiunti
- aggiunta nello storico SATOR una lettura operativa di apprendimento decisionale: classifica la disciplina di esecuzione, evidenzia i ticker saltati piu' spesso e quelli aggiunti extra rispetto alla proposta, usando solo dati gia' registrati nella pagina standalone
- aggiunta nello storico SATOR la tabella "Apprendimento per funzione": aggrega le fotografie eseguite per bucket/funzione, mostra quante proposte vengono saltate o eseguite, il target medio lasciato sul tavolo quando una riga viene saltata e segnala eventuali esecuzioni oltre cap o con dati deboli
- portata in Pianificazione una sintesi compatta dell'apprendimento SATOR: la card "Fotografia di riferimento" mostra disciplina di esecuzione, aderenza importo, delta, scostamenti, target lasciato e ticker saltato piu' spesso quando nello storico esistono ordini effettivi registrati
- aggiunto in Portafoglio un pannello sperimentale e reversibile "Portfolio Insights": sopra la tabella evidenzia scostamenti Core/Difensivo/Satellite, concentrazione, impatti della giornata, cambi segno P/L, qualita' dati e ultimo suggerimento SATOR, riusando la stessa mappa giornaliera della tabella per evitare discrepanze
- rifinito il rendering del pannello Portfolio Insights: stile spostato nel CSS globale dell'app, HTML renderizzato con `st.html` quando disponibile e layout riallineato al linguaggio visuale Sestante con una priorita' principale e segnali secondari compatti
- migliorata la leggibilita' del pannello Portfolio Insights con icone e colori per tipologia di segnale (allocazione, concentrazione, giornata, cambio segno, qualita' dati, SATOR) e sostituita la dicitura tecnica "stessi dati della tabella" con "coerente con Var gg e P/L"
- arricchiti gli insight di Portafoglio con metadati strumento: quando il segnale riguarda un ticker, il pannello mostra badge ticker, categoria macro colorata (GOV/FND/ETF/...) e bucket strategico colorato (Core/Difensivo/Satellite)
- riallineate le icone del pannello Portfolio Insights al sistema visuale ufficiale: rimosse le SVG locali inventate, riusate le icone di sezione esistenti e le icone natura gia' presenti in `ui/charts/natura_icons.py`, con colori categoria/bucket dalle palette centralizzate
- corretto il resolver icone strumento del pannello Portfolio Insights: se `natura` non e' gia' salvata, viene calcolata a runtime con `core.instrument_classification.classify_natura`, la stessa logica usata per riconoscere icone in Quotazioni e Portafoglio (es. ENRG.MI -> Energia, XMME.MI -> Mercati emergenti)
- reso coerente il pannello Portfolio Insights con lo standard visuale dell'app: rendering HTML tramite `st.markdown` per preservare le icone SVG ufficiali, blocco identita' strumento con ticker/nome colorati dalla macrocategoria, date in formato italiano e suggerimenti di allocazione collegati al ticker concreto proposto dall'ultima fotografia SATOR quando disponibile
- riorganizzato il pannello Portfolio Insights in chiave piu' decisionale: lo strumento viene mostrato dentro il segnale che lo cita, non prima del testo; aggiunto un radar operativo nella prima colonna con peggior/miglior contributo di giornata, migliore/peggiore andamento sulle ultime sedute disponibili e segnali di cambio colore P/L, mantenendo una selezione bilanciata fra SATOR, allocazione, giornata, trend, concentrazione e qualita' dati
- rifinito l'ordine interno dei segnali Portfolio Insights: titolo, dato numerico, azione concreta, badge categoria/bucket e solo infine riga ticker/nome strumento, cosi' l'identita' dello strumento resta agganciata al punto in cui viene citata
- estesa la mappa "Prossimo acquisto" in Pianificazione: il tooltip delle bolle riporta impatto target, concentrazione natura post-acquisto e qualita' dello storico, leggendo i dati salvati nell'ultima fotografia SATOR
- ottimizzata la mappa "Prossimo acquisto": assi con padding dinamico, marker non clippati, label adattive ai bordi e margini finali piu' ampi evitano che le bolle vengano tagliate o schiacciate quando i candidati sono vicini agli estremi 0/1
- rimosso da `ui/pages/operazioni.py` il vecchio Centro Operativo Streamlit interno e il carrello/dialog legacy: la pagina Operazioni resta consultiva, mentre Inserisci/Strumenti/Operazioni/Liquidita' vivono solo nei form-server aperti dalla sidebar
- rimosso da `ui/pages/pianificazione.py` il vecchio modulo SATOR Streamlit in-page e i suoi helper di editor/matrice/ordine manuale: Pianificazione mantiene obiettivo portafoglio, dashboard decisionale e fotografia di riferimento; SATOR operativo resta nella pagina standalone aperta dalla sidebar
- irrobustiti i pulsanti operativi della sidebar: ogni apertura del form-server ora ritenta l'avvio, controlla thread/stato `ready`, mostra uno stato compatto su porta 8502 e segnala errori leggibili invece di aprire alla cieca una pagina non disponibile
- sostituiti gli avvisi nativi `st.warning`/`st.error` dei servizi operativi con un badge sidebar compatto e coerente col tema, meno invasivo durante l'uso normale
- rimosso il badge preventivo dei servizi operativi dalla sidebar: lo stato della porta 8502 viene verificato solo dopo il click su una pagina operativa; se la pagina locale non risponde, l'app mostra un avviso contestuale con il suggerimento di riprovare o riavviare l'applicativo
- inserito il logo Sestante finale nell'header iniziale tramite nuovo asset statico (`static/sestante_logo_header_final.png`), evitando la cache dei file precedenti e mantenendo a destra KPI tecnici, data e ultimo aggiornamento
- rifinita la barra iniziale: contenitore arrotondato con fondo chiaro discreto, nessun box separato attorno al logo e nessuna linea blu superiore
- irrobustito il refresh manuale della pagina Mercati: lo storico benchmark usa prima la Chart API Yahoo con ticker codificati correttamente (es. `^GDAXI`, `^FTSE`) e solo dopo il fallback `yfinance`, aggiungendo proxy ETF per DAX/FTSE 100 e un report post-refresh con serie recuperate, gia' allineate e non disponibili
- separato il refresh live della pagina Mercati dallo storico benchmark: `Aggiorna mercati` ora recupera anche quotazioni correnti Yahoo (`market_live_data`) e le usa per `Ultimo`/`Var gg`, mentre 5g/1m/YTD e grafici restano basati sulle serie daily; aggiunta persistenza del live nella cache benchmark e colonna `Fonte` per distinguere Live/Storico
- reso il refresh Mercati indipendente dalla vista Core/Completo: il tasto alimenta sempre tutto l'universo Mercati, mentre la vista decide solo cosa mostrare; la striscia mercati ora usa prima `market_live_data` e solo in fallback `benchmark_data`
- corretto il reload dati Mercati: `_data_mtime()` include ora `portafoglio_benchmark_cache.json` e la firma cache considera anche ultimi valori benchmark e `market_live_data`, evitando contesti Streamlit obsoleti con tabella Mercati ancora `n/d` dopo il refresh; aggiunta diagnostica di copertura dati letti nella pagina Mercati
- corretto il caricamento effettivo della cache Mercati: `load_data()` ora considera `portafoglio_benchmark_cache.json` fonte autorevole per `benchmark_data` e `market_live_data`, ignorando eventuali campi residui/stale in `portafoglio_data.json`; `save_benchmark_data()` preserva la parte live/storica esistente quando riceve payload incompleti
- resa la pagina Mercati indipendente dal payload orchestrato quando legge dati benchmark/live: a inizio render fonde direttamente `portafoglio_benchmark_cache.json` nel payload della pagina e mostra diagnostica `ctx/file` per distinguere cache Streamlit vecchia da cache disco aggiornata
- rivista la leggibilita' della pagina Mercati: tabelle con `height="content"`, colonne compatte, font 13px, evidenziazione cromatica di performance/Stato/Fonte, label piu' brevi e riduzione dell'ingombro dei box regime/aree e delle mappe forza relativa
- ampliato in modo selettivo l'universo Core Mercati: promossi Dow Jones, US 2Y, Brent ed EUR/GBP; aggiunto GBP/USD in Esteso; aumentata la leggibilita' della mappa forza relativa con font piu' grandi su celle, assi e colorbar
- corretto errore Plotly nella mappa forza relativa: sostituito `colorbar.titlefont` non supportato con `colorbar.title.font` e aggiunto test che costruisce effettivamente la heatmap con la versione Plotly installata
- aumentata ulteriormente la leggibilita' della mappa forza relativa: valori compattati a 1 decimale, label indici abbreviate, gap tra celle, font celle/assi a 14px e test dedicato sui parametri tipografici minimi
- resi leggibili i nomi strumenti della mappa forza relativa: le label Y non sono piu' tick label compresse da Plotly, ma annotazioni dedicate a 15px con margine sinistro ampliato e test specifico
- aumentate in modo netto le etichette della sezione Mappa forza relativa: aree/assi del grafico forza area a 17px/15px, label heatmap a 18px, chip/sezioni HTML a 14-15px; sostituita anche `xaxis.titlefont` con `xaxis.title.font` per compatibilita' Plotly
- aumentate in modo netto le etichette della sezione Mappa forza relativa: aree/assi del grafico forza area a 17px/15px, label heatmap a 18px, chip/sezioni HTML a 14-15px; sostituita anche `xaxis.titlefont` con `xaxis.title.font` per compatibilita' Plotly
- resi leggibili i nomi strumenti della mappa forza relativa: le label Y non sono piu' tick label compresse da Plotly, ma annotazioni dedicate a 15px con margine sinistro ampliato e test specifico
- aumentata ulteriormente la leggibilita' della mappa forza relativa: valori compattati a 1 decimale, label indici abbreviate, gap tra celle, font celle/assi a 14px e test dedicato sui parametri tipografici minimi
- corretto errore Plotly nella mappa forza relativa: sostituito `colorbar.titlefont` non supportato con `colorbar.title.font` e aggiunto test che costruisce effettivamente la heatmap con la versione Plotly installata
- ampliato in modo selettivo l'universo Core Mercati: promossi Dow Jones, US 2Y, Brent ed EUR/GBP; aggiunto GBP/USD in Esteso; aumentata la leggibilita' della mappa forza relativa con font piu' grandi su celle, assi e colorbar
- rivista la leggibilita' della pagina Mercati: tabelle con `height="content"`, colonne compatte, font 13px, evidenziazione cromatica di performance/Stato/Fonte, label piu' brevi e riduzione dell'ingombro dei box regime/aree e delle mappe forza relativa
- resa la pagina Mercati indipendente dal payload orchestrato quando legge dati benchmark/live: a inizio render fonde direttamente `portafoglio_benchmark_cache.json` nel payload della pagina e mostra diagnostica `ctx/file` per distinguere cache Streamlit vecchia da cache disco aggiornata
- corretto il caricamento effettivo della cache Mercati: `load_data()` ora considera `portafoglio_benchmark_cache.json` fonte autorevole per `benchmark_data` e `market_live_data`, ignorando eventuali campi residui/stale in `portafoglio_data.json`; `save_benchmark_data()` preserva la parte live/storica esistente quando riceve payload incompleti
- corretto il reload dati Mercati: `_data_mtime()` include ora `portafoglio_benchmark_cache.json` e la firma cache considera anche ultimi valori benchmark e `market_live_data`, evitando contesti Streamlit obsoleti con tabella Mercati ancora `n/d` dopo il refresh; aggiunta diagnostica di copertura dati letti nella pagina Mercati
- reso il refresh Mercati indipendente dalla vista Core/Completo: il tasto alimenta sempre tutto l'universo Mercati, mentre la vista decide solo cosa mostrare; la striscia mercati ora usa prima `market_live_data` e solo in fallback `benchmark_data`
- separato il refresh live della pagina Mercati dallo storico benchmark: `Aggiorna mercati` ora recupera anche quotazioni correnti Yahoo (`market_live_data`) e le usa per `Ultimo`/`Var gg`, mentre 5g/1m/YTD e grafici restano basati sulle serie daily; aggiunta persistenza del live nella cache benchmark e colonna `Fonte` per distinguere Live/Storico
- consolidata la normalizzazione schema/storage: settings, dati portafoglio, snapshot, quotes log e meta vengono riallineati alla schema corrente e recuperano payload malformati senza lasciare versioni vecchie in memoria
- reso piu' silenzioso l'avvio del form-server: se la porta 8502 espone gia' una pagina Sestante valida, l'app la riusa invece di tentare un secondo bind Uvicorn
- esteso il reload automatico dello StateManager a tutti i file runtime principali (`data`, `settings`, `quotes_log`, `snapshots`, `meta`): i salvataggi fatti dai form-server fuori dal rerun Streamlit non lasciano piu' impostazioni o metadati cacheati
- centralizzato il calcolo delle metriche da curva rendimento (`TWR`, `CAGR`, `CAGR reale`, volatilita', max drawdown, Sortino, Calmar, tracking error e information ratio) in `core/domain/returns.py`, cosi' dashboard Summary e report filtrati usano la stessa formula
- chiarito e corretto il Money Weighted Return di portafoglio: lo `XIRR` principale usa ora, quando disponibili, i flussi esterni reali (`VERSAMENTO`/`PRELIEVO`) e il patrimonio finale comprensivo di liquidita'; il precedente XIRR sugli strumenti resta salvato come `xirr_assets`
- reso esplicito nei report il significato dello `XIRR`: le card Performance distinguono `XIRR portafoglio` da `XIRR strumenti`, mostrano l'origine del calcolo e riportano il confronto strumenti quando i due valori non coincidono
- irrobustiti i controlli integrita' BTP: un calendario cedole malformato o privo di date valide ora produce un warning in Gestione Dati invece di poter interrompere la pagina con un errore tecnico
- migliorate le validazioni di input: una data passata con tipo errato mostra ora un messaggio specifico invece di essere confusa con una data mancante
- rafforzati i controlli numerici dei form: quantita', prezzi e soglie non accettano piu' valori booleani (`True`/`False`) come se fossero numeri validi
- bloccati valori numerici non finiti (`NaN`, `inf`, `-inf`) in quantita', prezzi, soglie e import quotazioni, evitando che dati corrotti possano entrare nello storico prezzi o nei calcoli di portafoglio
- estesa la stessa protezione allo storage centrale: `_safe_float` converte ora valori non finiti al default con warning, proteggendo anche dati gia' salvati o file legacy caricati prima delle nuove validazioni UI
- filtrato lo storico prezzi in `build_hist_df`: prezzi non finiti, nulli o non positivi restano buchi espliciti (`NaN`) invece di alimentare grafici e calcoli con valori corrotti
- irrobustite le fonti mercato: prezzi Yahoo/recent history/backfill non finiti o non positivi vengono scartati prima di entrare in cache runtime o nello storico prezzi
- protetta anche la scrittura sidebar dello storico per data effettiva di mercato: un prezzo non finito/non positivo viene ignorato e non puo' sovrascrivere una quotazione valida gia' salvata
- ampliati i controlli di integrita' in Gestione Dati: prezzi correnti non finiti/non positivi e prezzi storici inutilizzabili vengono ora evidenziati come anomalie diagnostiche
- rese coerenti le firme cache dei grafici con la pulizia prezzi: punti storici non numerici, non finiti o non positivi non vengono piu' contati come quotazioni valide per ticker/categoria
- estesi i controlli di integrita' sugli eventi: quantita', prezzi unitari e importi non numerici/non finiti vengono segnalati in Gestione Dati invece di rischiare errori tecnici o calcoli sporchi
- irrobustiti i KPI di capitale e total return: valori legacy non numerici/non finiti in liquidita', capitale investito, acquisti, versamenti e prelievi vengono neutralizzati invece di propagare `NaN`/`inf`
- irrobustita la costruzione XIRR legacy: operazioni/proventi con importi non finiti vengono scartati e loggati, e il valore terminale usa solo controvalori finiti
- resi robusti i riepiloghi proventi e i totali Summary: cedole/dividendi legacy con importi malformati o non finiti non propagano piu' valori `NaN`/`inf` nei report
- irrobustito l'export Portfolio Performance: importi non finiti vengono neutralizzati, gli acquisti possono ricostruire il valore da quantita' x prezzo, e lo ZIP prezzi salta quotazioni non numeriche/non finite/non positive
- rese robuste le viste market-only di Home e Analitica: proventi legacy non numerici/non finiti non alterano piu' i grafici P/L depurati da cedole/dividendi
- estesa la pulizia numerica ai proventi netti dei Cruscotti: valori legacy `NaN`/`inf` non possono piu' contaminare il totale cedole/dividendi mostrato nelle viste aggregate
- resi piu' difensivi calendario BTP e YTM/duration: metadati non finiti su cedola, nominale, quantita', aliquota o prezzo vengono gestiti senza produrre timeline o rendimenti impossibili
- irrobustiti snapshot e confronti snapshot: totali, pesi, P/L, prezzi e note automatiche usano solo valori finiti, evitando che uno snapshot legacy sporco deformi confronto storico e commenti
- protetto il payload radar dei Cruscotti: obiettivi, cap di concentrazione, TER/duration arricchiti, controvalori e liquidita' non finiti vengono neutralizzati prima di costruire assi, pesi e confronto con target
- rese piu' robuste le metriche categoria dei Cruscotti: investimento, controvalore, P/L, giacenza media, TWR proxy e volatilita' ignorano punti `NaN`/`inf` invece di propagare valori impossibili nelle card
- protetti anche riepilogo macro, breakdown allocazione e card valore/P-L per categoria: somme e percentuali usano colonne numeriche sanificate prima di aggregare
- irrobustiti i riepiloghi di attivita' periodo usati nei report: importi, quantita', commissioni e imposte non finiti vengono neutralizzati in summary, dettaglio per strumento e registro eventi
- irrobustito il report HTML esportabile: KPI, liquidita', proventi, holdings, dettagli categoria, highlights, serie storiche ribasate e XIRR di periodo filtrano `NaN`/`inf` prima di formattare o ordinare i dati
- irrobustito anche il payload Summary a monte del report: impostazioni metriche, liquidita', KPI, holdings, storico e breakdown categoria neutralizzano valori non finiti prima di costruire JSON/HTML
- irrobustiti i dataset dashboard GOV/categoria/Tutto: quote, prezzi, PMC, controvalori, P/L e pesi di comparto vengono sanificati prima di somme e medie ponderate, evitando che un dato legacy `NaN`/`inf` deformi card o grafici dei Cruscotti
- irrobustiti i calcoli what-if di Pianificazione: posizioni e liquidita' non finite vengono neutralizzate prima di allocazione, concentrazione e metriche prima/dopo, cosi' la simulazione resta leggibile anche con dati legacy sporchi
- irrobustiti gli alert di portafoglio: soglie, risk ratio, drawdown, volatilita' e P/L non finiti non generano alert fantasma; se `P/L %` e' parziale, l'alert perdita ricostruisce il dato da `P/L € / Costo`
- irrobustita la vista Cedole & Scadenze: importi calendario, rimborsi, valori GOV, YTM e duration non finiti vengono ignorati nei KPI e nella duration media ponderata senza cambiare la forma della tabella dettagli
- ridotto il rumore dei log numerici: `_safe_float` tratta `NaN` come valore mancante atteso e non emette piu' warning ripetuti, mentre mantiene il warning per `inf`/`-inf` e valori non convertibili
- aggiunto `TODO_5.0.md` con backlog esplicito per l'archivio dei report generati: salvataggio automatico HTML/JSON, manifest locale, storico in Summary, download/eliminazione e rigenerazione con stesse opzioni
- aggiunto il primo step dell'archivio report Summary: ogni report generato viene salvato automaticamente in `data/reports/summary/` con HTML, JSON e manifest; la pagina Summary mostra gli ultimi report, consente di riprenderli nei download correnti o eliminarli
- resa piu' stabile l'osservabilita' in test: la configurazione logging mantiene la propagazione quando l'app gira sotto pytest/modalita' test, evitando che `caplog` perda i record dopo l'import Streamlit
- corrette le regole evento per ETF/FND/ETC obbligazionari: la presenza di parole come `obbligazionario` o `bond` nel nome non li rende piu' strumenti da cedola/rimborso a scadenza; se sono a distribuzione restano compatibili con `DIVIDENDO`
- la validazione eventi respinge ora esplicitamente tipi evento mancanti o non supportati, invece di lasciarli passare fino al salvataggio o ai calcoli successivi

