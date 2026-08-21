# Changelog

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

## 4.9.40 - Consolidamento sidebar, Pianificazione fluida e cache Analitica coerente

**Accesso operativo definitivo dalla sidebar:**
- le azioni operative sono state consolidate sulla sidebar come unica superficie ufficiale: Inserisci operazione, Strumenti, Operazioni, Liquidità, Esporta PP e SATOR sono sempre disponibili dai pulsanti laterali
- rimossi da Setup i radio "Centro Operativo vs Sidebar", "SATOR" ed "Esporta PP": erano diventati un livello di scelta ridondante e rischiavano di mantenere due flussi paralleli per la stessa operazione
- i default di configurazione sono ora `operativo_mode="sidebar"`, `sator_mode="sidebar"` ed `export_pp_mode="sidebar"`; al salvataggio Setup normalizza comunque eventuali vecchi file impostazioni su questo assetto
- reso più robusto il bootstrap del form-server FastAPI su porta `8502`: se un rerun trova il vecchio thread morto, l'avvio viene ritentato; il log ora distingue l'avvio richiesto dal server realmente attivo
- aggiunte a `requirements.txt` le dipendenze effettive dei servizi sidebar (`fastapi`, `uvicorn[standard]`, `python-multipart`), prima usate dal codice ma non dichiarate dal progetto
- la pagina Operazioni diventa un registro consultivo degli eventi di portafoglio e dei movimenti di cassa: il vecchio Centro Operativo interno non viene più renderizzato
- in Pianificazione non viene più renderizzato il vecchio modulo SATOR Streamlit interno: restano Obiettivo di portafoglio, dashboard decisionale e fotografia di riferimento; SATOR operativo vive nella pagina standalone aperta dalla sidebar
- rimossa da Gestione Dati la sezione duplicata "Esporta per Portfolio Performance": l'export resta nel form-server dedicato `/export_pp`

**Tabella Portafoglio: prezzo e layout compatto:**
- aggiunta nella tabella "Controvalore del Portafoglio" la colonna dell'ultima quotazione disponibile, accanto a quote e controvalore
- spostato `PMC` prima del peso, così prezzo medio di carico, peso, quantità, ultima quotazione e controvalore seguono una lettura più naturale
- introdotte larghezze esplicite di colonna con font tabella a 13px: `Strumento` è più compatto, le colonne finali `P/L` e `Var gg` sono più larghe e la freccia finale non occupa spazio eccessivo

**Codice legacy tracciato per revisione:**
- aggiunta `ui/legacy/README.md` con la mappa dei percorsi vivi e dei blocchi legacy rimasti temporaneamente nel codice sorgente
- marcati con `LEGACY_REVIEW 2026-07-26` i vecchi dialog Streamlit del Centro Operativo in `ui/pages/operazioni.py` e il vecchio modulo SATOR interno in `ui/pages/pianificazione.py`
- scelta volutamente conservativa: i blocchi legacy sono commentati e isolati, non spostati fisicamente, perché contengono decorator Streamlit e helper intrecciati; la prossima revisione potrà eliminarli o migrare eventuali funzioni residue verso `ui/form_server/*` o `core/services/*`

**Pianificazione: preset obiettivo in un solo salvataggio:**
- eliminato il doppio click "Applica preset" + "Salva obiettivo di portafoglio": il preset rapido ora sta dentro lo stesso form dell'obiettivo e viene applicato direttamente dal pulsante "Salva obiettivo e aggiorna analisi"
- il salvataggio usa una callback Streamlit: l'impostazione viene scritta prima del rerun top-to-bottom, quindi Cruscotti/Analitica vede subito il nuovo target nello stesso ciclo di aggiornamento
- dopo il salvataggio i campi Core/Difensivo/Satellite vengono riallineati ai valori realmente salvati e il preset torna neutro (`-`), evitando che un preset rimanga selezionato e sovrascriva modifiche manuali successive

**Cruscotti / Analitica: fix cache "Scostamento da allocazione target":**
- il grafico "Scostamento da Allocazione Target" usava una firma cache che non includeva `portfolio_objective`: dopo aver cambiato target in Pianificazione poteva restare visibile una figura costruita con il vecchio obiettivo
- aggiunto `_objective_cache_token()` in `ui/dashboard_bundles.py` e incluso il token in `extra_params` della figure cache del grafico `analisi_target_gap`
- aggiunti test di regressione per verificare che due target diversi producano firme cache diverse e che il blocco Analitica includa esplicitamente l'obiettivo nella cache

**Navigazione e rerun:**
- aggiunto un bridge leggero per ricordare il tab principale selezionato nel browser (`sessionStorage`, chiave `sestante.activeTabIndex.v1`): dopo un rerun causato da un widget, l'app non deve tornare senza motivo alla prima scheda
- migliorata la navigazione programmata verso Quotazioni/Operazioni: il bridge aggiorna anche lo stato browser prima di cliccare il tab target, riducendo i ritorni inattesi dopo azioni da sidebar

**Setup / Avanzate: audit operativo:**
- verificato che `Profiling render` è ancora funzionante: misura i tempi reali della UI e, in modalità "Sweep completo", aggiunge il riepilogo pagina-per-pagina; resta in Avanzate come strumento diagnostico, spento di default
- verificato che il pre-render iniziale è ancora cablato e funzionante (`app.py`, `core/cache_prewarmer.py`, `ui/prewarm_bundle.py`, eventi persistiti in `core/render_profiler.py`): non rimosso perché continua a governare la costruzione preventiva delle figure principali
- la diagnostica del pre-render resta disponibile anche in Gestione Dati tramite stato prewarm, esecuzione manuale background e log render copiabile
- riscritte le etichette di Setup Avanzate per utenti non tecnici: `Profiling render` diventa "Misurazione tempi di caricamento", `Pre-render iniziale` diventa "Cache anticipata dei grafici", con note pratiche su quando lasciare tutto attivo, quando mostrare il report tempi e quando usare la diagnosi completa
- il box istruzioni di Avanzate è ora un pannello a righe colorate (Uso normale / Se sembra lento / Diagnosi tecnica), più leggibile del precedente blocco testuale

**Copertura test:**
- aggiunti/aggiornati test statici e unitari per bloccare regressioni su sidebar-only, preset Pianificazione, cache Analitica target, restore del tab selezionato e marcatura legacy
- verificati i blocchi collegati con `py_compile` e test mirati (`test_streamlit_pages`, `test_analitica_target_gap_objective_cache`, `test_portfolio_objective_settings`, `test_sator_*`, `test_page_intro_i18n`)

## 4.9.39 - Portafoglio più leggibile, Quotazioni coerenti e shell iniziale rifinita

**Tabella "Controvalore del Portafoglio":**
- riordinata la tabella per renderla più leggibile: peso e quote sono più vicini, il PMC precede il controvalore, le commissioni/costo iniziale non occupano più spazio nella vista principale
- aggiunta la colonna con mini-grafico 60 giorni per ogni strumento posseduto, basata sugli stessi dati dello sparkline nel popup di dettaglio
- il mini-grafico segue il colore del P/L della posizione, non l'ultimo movimento di prezzo: evita incoerenze come strumento in utile mostrato rosso nella tabella ma verde nel popup
- aggiunta linea orizzontale tratteggiata del PMC dentro il mini-grafico e nel popup, così si vede subito se il prezzo recente si muove sopra o sotto il carico
- riarticolate le colonne finali in ordine operativo: grafico, P/L €, P/L %, Var gg €, Var gg % e freccia direzionale
- riscritto il commento sotto la tabella: rimossa la legenda categorie ridondante, sostituita da una lettura più utile di peso, esposizione, andamento recente, P/L e variazione giornaliera

**Popup e grafici strumento:**
- il popup ticker e la tabella condividono dati, logica sparkline e riferimento PMC, riducendo discrepanze tra mini-grafico e dettaglio
- nella pagina Quotazioni, il grafico "Rendimento dello strumento" è stato riallineato matematicamente al valore massimo/minimo reale mostrato a video
- aggiunto confronto non invasivo con il rendimento del portafoglio nel grafico dello strumento, come riferimento visivo puntinato/trasparente

**Quotazioni: storico e freschezza dati:**
- aggiunto sotto i grafici in Quotazioni un indicatore sintetico dello stato dello storico prezzi, con ultima data disponibile e avviso quando la serie sembra più corta del previsto
- la firma cache ora include anche l'ultimo punto storico per ticker/categoria: un backfill o un aggiornamento dell'ultima data non resta nascosto dietro cache costruite con storico precedente
- aggiunti test su `latest_history_point_by_ticker` e sulla resa dell'indicatore `quote-history-status`

**Banner iniziale, progresso render e chiusura app:**
- rifinito il banner iniziale Sestante: titolo, sottotitolo "Portfolio Control Center", data/aggiornamento e KPI sono stati riorganizzati in modo più professionale
- la barra di avanzamento render ora misura il tempo UI dall'inizio del run alla fine e mostra messaggi più espliciti durante il rendering delle pagine
- ripristinata e ridisegnata la pagina finale dopo "Arresta Streamlit": schermata compatta e coerente col tema, senza layout rotto dopo la richiesta di shutdown

**Rerun e usabilità:**
- selezionare un preset rapido in Pianificazione non deve più generare un rerun immediato solo per la scelta del valore: il comportamento è stato spostato verso conferme esplicite nei form
- corretto il caso in cui un rerun da Pianificazione riportava l'utente in fondo alla pagina Quotazioni senza una causa comprensibile

## 4.9.38 - Pannello laterale del box iniziale più stretto

**Rifinitura del box iniziale (v4.9.37):**
- rimossa la riga "Piano" ("Dashboard premium"), poco informativa — restano solo Versione e Stato
- Versione e Stato ora su una riga sola ciascuna (etichetta a sinistra, valore allineato a destra) invece di etichetta sopra/valore sotto
- pannello laterale scuro ristretto da 230px a 168px, coerente con il contenuto ridotto
- rimossa la chiave di traduzione `app.badge`, rimasta orfana dopo la rimozione della riga "Piano"

## 4.9.37 - Nuovo box iniziale a pannello diviso

**Restyling del box in cima all'app:**
- stesso contenuto di prima (titolo, badge piano/versione/stato, data ultimo aggiornamento) ma riorganizzato in un pannello diviso: icona con gradiente + titolo + data a sinistra, pannello blu notte a destra con Piano/Versione/Stato separati da linee sottili
- il pannello laterale è intonato al colore primario della palette scelta in Setup (`color-mix` su `--ptf-primary`), quindi cambia tono automaticamente se l'utente cambia palette colori
- direzione scelta tra 3 alternative tramite mockup comparativi nella scheda di brainstorming visivo (icona in badge con gradiente, pannello diviso, minimale con chip separate), poi rifinita in 2 varianti di tono per il pannello laterale (nero neutro vs blu notte)

## 4.9.36 - L'app si chiama "Sestante"

**Rinominata l'app da "Portafoglio Titoli" a "Sestante":**
- il vecchio nome era descrittivo ma anonimo (indistinguibile da qualunque altra app dello stesso genere); "Sestante" richiama lo strumento di navigazione, coerente con l'icona 📊 già in uso, tono professionale/elegante
- aggiornato in tutti i punti live: titolo scheda browser (`st.set_page_config`), intestazione in cima all'app, footer della pagina Setup, metadati del pacchetto di reporting esportabile (`core/services/reporting.py`) e chiave di traduzione inglese (nome proprio, non tradotto)
- non toccato `legacy/ui/charts/reporting.py`: nessun chiamante nel repo, fuori scope

## 4.9.35 - Audit completo di Setup, refresh SATOR e doppia legenda donut

**Tasto "Aggiorna" per la fotografia SATOR (Pianificazione):**
- la fotografia SATOR può essere registrata dalla pagina standalone `/sator` (processo separato dall'app principale); tornando su Pianificazione senza interagire con nulla, la card "Fotografia di riferimento" restava con la versione precedente finché non partiva un rerun qualsiasi — nuovo tasto `🔄 Aggiorna` sopra la card che forza il rerun esplicito

**Doppia legenda con percentuale nel donut "Allocazione: bucket e strumenti":**
- solo l'anello esterno (natura/esposizione) aveva una legenda; l'anello interno (Core/Difensivo/Satellite) mostrava le etichette solo dentro le fette — aggiunta una seconda legenda (natura a sinistra, bucket a destra, via `legend`/`legend2` di Plotly) e le percentuali sul totale portafoglio accanto a ogni voce di entrambe

**Audit a 360° della pagina Setup: ogni impostazione ora ha un effetto reale, completo, o è dichiarata esplicitamente come non ancora implementata — nessuna via di mezzo silenziosa:**
- **Valuta base/reporting e Locale/Formato data/numerico** disabilitati con nota "funzionalità futura": non esiste alcuna conversione valuta né formattazione locale-aware nell'app (ogni importo resta sempre in EUR, ogni data/numero sempre in formato italiano) — i selettori restavano cliccabili senza fare nulla, ora è dichiarato onestamente
- **Rimossi `table_density`** (mai avuto un controllo UI, mai letto da nessuna parte) **e i 4 selettori di dimensione tipografica** Titoli/Sottotitoli/Body/Commenti (nessuna variabile CSS li applicava, a differenza di "Famiglia font" che invece funziona ed è stata mantenuta)
- **Descrizione portafoglio**: veniva salvata ma non era mai mostrata da nessuna parte — ora compare nell'intestazione dei report HTML esportati
- **Due nuovi controlli** per impostazioni già realmente attive ma prive di qualunque interfaccia: **colore accento** (`ui/theme.py`, 4 varianti) e **mostra spiegazioni** (box esplicativi in Cruscotti e Confronto)
- **CAGR reale al netto inflazione**: il campo "Inflazione annua %" veniva raccolto ma mai usato in alcun calcolo — ora un "CAGR reale" compare accanto al CAGR nominale nei report Executive/Extended, visibile solo quando l'inflazione configurata è maggiore di zero
- **Alert di rischio/peso, drawdown e volatilità collegati ai dati reali**: erano configurabili e validati in Setup, ma la funzione che li calcola (`core/services/alerts.py`) non riceveva mai i dati necessari dall'unico punto di chiamata — non potevano mai scattare qualunque soglia si impostasse; ora collegati al bundle di analisi già calcolato per i Cruscotti (cache condivisa), con calcolo limitato ai soli casi in cui almeno una delle tre soglie è davvero configurata, per non appesantire il primo caricamento della Home quando servono solo gli alert di perdita/concentrazione
- **Traduzione inglese** di titolo e commento introduttivo delle 10 pagine principali dell'app (prima tradotto solo un sottoinsieme parziale di stringhe) — perimetro limitato all'intestazione di pagina, le sezioni interne restano in italiano

## 4.9.34 - Aggiornamento a Streamlit 1.59.2

**Bump `streamlit` da 1.58.0 a 1.59.2:**
- nessuna delle funzionalità rimosse nel percorso 1.58→1.59 (`st.bokeh_chart`, connector Snowpark deprecato, `add_rows`, integrazione LangChain) è usata nel codice — verificato con ricerca su tutto il repo
- nessun uso di API `st.experimental_*`/`st.beta_*` da migrare
- avvio dell'app e rendering delle pagine (inclusi i grafici Plotly con legenda dinamica appena corretti e il fragment in Operazioni) verificati senza errori/traceback dopo l'aggiornamento

**Fix: le linguette del menu principale e il riquadro dei selectbox erano visivamente spariti (nessun bordo/sfondo/pillola) dopo il bump a 1.59.2:**
- la 1.59 ha sostituito il componente interno di `st.tabs` e `st.selectbox` (da BaseWeb a React Aria Components), che non emette più l'attributo `data-baseweb` su cui erano ancorate le regole CSS custom in `ui/styles.py` — le regole restavano nel foglio di stile ma non trovavano più nulla da selezionare, quindi tab e selectbox tornavano al rendering piatto di default
- selettori aggiornati per puntare agli attributi ancora presenti nel nuovo markup: `.stTabs [data-baseweb="tab-list"]`/`"tab"` → `[data-testid="stTabs"] [role="tablist"]`/`[data-testid="stTab"]`, `[data-baseweb="select"]` → `[data-testid="stSelectbox"] [role="group"]`

## 4.9.33 - Revisione delle metriche di Analisi Accumuli, fix messaggio di stato Accumuli/Benchmark

**Riscrittura delle metriche di "Analisi accumuli" (Cruscotti > Accumuli):**
- "Margine su PMC" e "Elasticità PMC" avevano nomi che inducevano a conclusioni sbagliate: il primo divideva per il prezzo corrente invece che per il PMC (non era un rendimento, ma la distanza dal pareggio), il secondo simulava sempre una rata fissa di €300 uguale per tutti gli strumenti invece della rata realmente tipica di ciascun PAC — corretti e rinominati: **Cuscinetto pareggio / Recupero necessario** (`distanza_pareggio_pct`, denominatore corretto) e **Impatto rata tipica sul PMC** (`impatto_pmc_rata_pct`, calcolato sulla mediana delle rate storiche realmente pagate)
- separati PMC all-in (comprensivo di commissioni) e prezzo medio di esecuzione (escluse commissioni), con percentile calcolato per entrambi rispetto ai prezzi storici — il calcolo escludeva erroneamente il punto sintetico "oggi" dalla serie prezzi solo in un secondo momento: ora il periodo statistico si ferma sempre all'ultima quotazione reale, non a un prezzo odierno duplicato
- nuova **Aderenza alle scadenze PAC**, dedotta dal calendario (cadenza mensile/trimestrale, primo acquisto trattato come versamento iniziale se anomalo) invece che dalla sola distanza grezza fra acquisti consecutivi, che resta disponibile come metrica secondaria
- Stato e Priorità riclassificati su due assi chiari (sopra/sotto il PMC × quanto una rata tipica lo sposterebbe ancora), eliminando il bucket residuale "Da monitorare" in cui finivano posizioni mature e in utile senza un motivo comprensibile; nuova legenda a tabella sotto la sintesi che spiega cosa significano i singoli Stati e la Priorità
- grafico a quadranti, box di lettura sotto le KPI (ora una tabella, non un paragrafo) e KPI di dettaglio (16 invece di 17, raggruppate per tema) aggiornati di conseguenza; aggiunta la linea del PMC attuale nel grafico "Prezzo vs PMC" per capire a colpo d'occhio la posizione del percentile
- riferimento: `specifica_revisione_analisi_accumuli_FAM-FLEX.md` (non versionato, analisi di supporto)

**Fix: il box di stato di Accumuli/Benchmark restava con la data vecchia dopo il primo click su "Rigenera/Aggiorna analisi":**
- `_render_accumuli_freeze_header`/`_render_benchmark_freeze_header` disegnavano il messaggio con data e provenienza dell'ultima analisi *prima* di sapere se in quello stesso click l'utente avesse chiesto un refresh — quindi anche quando il refresh veniva eseguito correttamente (la cache si aggiornava), il messaggio a schermo restava quello di prima, dando l'impressione che il primo click non avesse fatto nulla; serviva un secondo click per vedere il messaggio corretto (quello del refresh precedente)
- il messaggio ora vive in uno slot dedicato (`st.empty`) ridisegnato subito dopo un eventuale refresh nello stesso rerun, così riflette sempre lo stato reale

**Badge "non a zero commissioni" esteso da SATOR a Quotazioni e Portafoglio:**
- lo stesso badge "€" già usato in SATOR per gli ETF/ETC non a zero commissioni ora compare anche accanto al ticker nella tabella principale di Quotazioni e nelle tabelle Controvalore e "Andamento dell'ultima settimana" del Portafoglio — limitato a ETF/ETC, le uniche categorie per cui il campo "Zero commissioni" è impostabile in Strumenti
- la logica (lettura del campo `zero_commissioni` e badge HTML) era duplicata inline in SATOR: estratta in `ui/charts/instrument_badges.py`, ora riusata da tutti e 4 i punti invece di avere due implementazioni dello stesso indicatore

**Fix: la legenda dei grafici "Contributo al P/L (Area Stacked)" e "Rendimento dello strumento" si sovrapponeva ai numeri dell'asse X:**
- entrambi i grafici hanno una voce di legenda per strumento (dinamica, cresce con il numero di posizioni), ma il margine inferiore riservato era fisso e pensato per una legenda a riga singola — con molti strumenti la legenda andava a capo su più righe e quelle in eccesso finivano sotto il margine, sovrapponendosi ai tick dell'asse X (si "sistemava" solo ridimensionando la finestra, perché forzava Plotly a ricalcolare il layout alla larghezza reale)
- `computed_margin` (`ui/charts/layout.py`) ora stima il numero di righe dal conteggio reale delle voci di legenda e allarga il margine inferiore solo per le righe oltre la prima; la posizione della legenda scende in proporzione, così lo spazio riservato in più viene usato dalla legenda stessa invece di restare vuoto sotto di essa

## 4.9.32 - Unifica il grafico P/L per Categoria in Portafoglio, sfondo riga in "Andamento dell'ultima settimana"

**Rimozione del selettore doppio grafico in Overview:**
- il radio "Vista grafico" (P/L del portafoglio / P/L per Categoria) sopra le tab veniva quasi sempre lasciato su "P/L del portafoglio": la vista "P/L per Categoria" era generata solo su richiesta ma restava di fatto inutilizzata — rimosso il selettore, Overview mostra sempre e solo "P/L del portafoglio"
- il grafico "P/L per Categoria" (storico impilato per categoria) si è spostato in modo definitivo nella tab Portafoglio, subito dopo "Andamento dell'ultima settimana", come nuova sezione sempre visibile (gestibile on/off dalle impostazioni di visibilità come le altre sezioni della tab)

**Sfondo riga nella tabella "Andamento dell'ultima settimana":**
- le righe con tutti e 7 i giorni disponibili e concordi (tutti in guadagno o tutti in perdita) ricevono uno sfondo verde o rosso leggero e trasparente, come segnale visivo immediato dell'andamento della settimana per lo strumento — righe con giorni mancanti (strumenti acquistati di recente) o con un giorno a zero non vengono evidenziate

## 4.9.31 - Card "Fotografia di riferimento" in Pianificazione

**Traduzione "Quality factor" → "Fattore qualità":**
- ultima etichetta di natura/esposizione rimasta in inglese nella tabella Strumenti e nel sistema di classificazione automatica (`core/instrument_classification.py`, icona in `ui/charts/natura_icons.py`, placeholder in `ui/form_server/strumenti.py`) — tradotta

**Il box "Fotografia di riferimento" (sotto la mappa a bolle "Prossimo acquisto") diventa una card, come già fatto per "Allocazione: bucket e strumenti":**
- barra Importo ordine/Budget: si scala su `max(importo, budget)` invece di appiattirsi al 100% quando l'ordine supera il budget, con una tacca che segna dove sta il budget lungo la barra, colore rosso e scritta "+X% oltre budget" quando l'importo supera il budget
- tre mini-barre colorate per il mix Core/Difensivo/Satellite (stessi colori bucket usati altrove)
- tabella "Righe ordine": pallino colorato per bucket + icona natura + ticker e nome strumento sulla stessa riga (una sola riga per strumento, niente scroll verticale — tutte le righe restano visibili), righe ordinate Core → Difensivo → Satellite; due colonne aggiuntive, Prezzo (con nota a piè tabella che chiarisce che è il prezzo alla data della fotografia, non quello attuale) e Totale bucket (una sola cella per gruppo, unita con `rowspan` invece di ripetuta su ogni riga)
- nuove classi CSS `ref-snapshot-*` in `ui/styles.py`, stesso pattern delle `bucket-alloc-*` (agganciate alle variabili tema, chiaro/scuro)
- fix di un bug di rendering scoperto durante l'implementazione: negli f-string HTML multilinea, un placeholder che inizia con un proprio `\n` inserito subito dopo testo indentato produce una riga fatta di soli spazi, che Streamlit/markdown-it interpreta come fine del blocco HTML — il contenuto successivo veniva mostrato come blocco di codice indentato invece che renderizzato; le funzioni coinvolte ora costruiscono l'HTML per concatenazione di stringhe senza indentazione incidentale

**Rimozione sezione "Liquidità da investire" (Pianificazione):**
- ridondante con la nuova card "Fotografia di riferimento" (bucket, importo, scostamento da budget sono già lì) e con la card "Allocazione: bucket e strumenti" più sopra nella stessa pagina — rimossa insieme alla funzione ormai orfana `build_bucket_rebalancing_suggestions` (`core/finance.py`), rimasta senza altri chiamanti in tutto il repo

## 4.9.30 - Tabella "Andamento dell'ultima settimana" in Portafoglio

**Nuova tabella P/L settimanale per strumento:**
- tra la tabella Controvalore e "Proventi per strumento", nuova sezione che mostra il P/L giornaliero di ogni strumento posseduto negli ultimi giorni di quotazione reali (fino a 7), con colonna "P/L totale" (somma della settimana) e riga TOTALE in fondo — stessa veste grafica interattiva della tabella Controvalore (intestazioni ordinabili, colonne ridimensionabili), senza scroll orizzontale né verticale
- `core/services/analysis.py::build_weekly_pl_table` calcola i delta con lo stesso metodo già in uso per "Andamento dell'ultima giornata" (colonne `PL_<ticker>` cumulate per strumento, delta contato solo tra giorni in cui lo strumento era posseduto in entrambi)
- le intestazioni giorno mostrano l'iniziale del giorno della settimana prima della data (es. "V 10/07", convenzione L M M G V S D) e un separatore verticale (stesso spessore/colore del bordo tabella/riga TOTALE) segna il salto tra la colonna di venerdì e quella del lunedì successivo

**Esclusione del giorno "fantasma" nei weekend:**
- quando l'ultima riga dello storico portafoglio è un punto sintetico (prezzi ri-letti in un giorno di mercato chiuso, senza movimento reale — tipicamente un refresh di sabato che riconferma la chiusura di venerdì), la tabella lo mostrava come se fosse un giorno di trading vero, con delta a zero per tutti gli strumenti che "consumava" una delle colonne disponibili senza portare informazione; ora la funzione scarta quella riga confrontandola con le date reali di `storico_prezzi`, mostrando sempre gli ultimi giorni di borsa effettivamente aperta

**Popup di dettaglio ticker condiviso con la tabella Controvalore:**
- cliccare un ticker nella nuova tabella apre lo stesso identico popup (KPI grid, sparkline prezzo, fonte/aggiornamento) già presente in Controvalore, invece di non aprire nulla: il codice del modale (CSS/HTML/JS e il calcolo dei dati per strumento) è stato estratto in helper condivisi in `ui/charts/portfolio_popup.py`, usati da entrambe le tabelle — non due copie mantenute a mano

**Altre rifiniture:**
- colonna "Tipo" mostra la sigla di macro-categoria (GOV/FND/ETF/ETC/...) invece del testo esteso, e nuova colonna icona natura tra Tipo e Quote (stessa fonte e posizione della tabella Controvalore)
- valori giornalieri a due decimali; la colonna "P/L totale" resta a due decimali con il simbolo "€"
- per ogni colonna giorno, la cella con il valore più alto e quella con il valore più basso (pareggi inclusi) sono evidenziate in grassetto
- nuova colonna con freccia diagonale subito prima di "P/L totale": verde (↗) se il risultato della settimana per quello strumento è positivo, rossa (↘) se negativo

**Refactor tecnico — modularizzazione di `form_server.py`:**
- `form_server.py` (3540 righe, unico file `.py` sciolto in root insieme ad `app.py`) è stato smontato in `ui/form_server/`, un modulo per pagina/route (`inserisci.py`, `strumenti.py`, `gestione.py`, `sator.py`, `scheda_strumento.py`, `export_pp.py`, `privacy.py`) più `shell.py` per gli asset condivisi (CSS, snippet JS dei tab, helper numerico) — stesso pattern "un file per pagina" già in uso in `ui/pages/` per le pagine Streamlit
- l'entrypoint stesso è stato spostato da `form_server.py` (root) a `ui/form_server/__init__.py`; `app.py` ora importa `from ui.form_server import start_form_server` invece di `from form_server import start_form_server` — non resta più nessun secondo entrypoint sciolto in root
- nessun comportamento applicativo cambiato: stesse route, stessi form, stessa logica di dominio — verificato ricostruendo l'app FastAPI e interrogando ogni route (incluse le sotto-pagine di Strumenti e i rami di errore) con dati reali
- la duplicazione di alcune funzioni di gestione eventi tra `ui/form_server/gestione.py` e `ui/pages/operazioni.py` (Centro Operativo) resta intenzionale: riflette la scelta ancora aperta se tenere quelle funzionalità solo su sidebar, solo nell'app principale, o entrambe (Impostazioni → `operativo_mode`/`sator_mode`/`export_pp_mode`)

**Allineamento zero tra i 3 grafici a barre "Analisi per Macro-Categoria" (Portafoglio):**
- Controvalore, P/L per Categoria e Performance % per Categoria auto-scalavano l'asse Y in modo indipendente: quando una categoria (es. ETC) va in perdita, la linea dello zero finiva ad altezze diverse nei 3 grafici affiancati
- nuovo `ui/charts/axes.py::zero_aligned_ranges()`: calcola, tra i grafici passati, la frazione verticale in cui deve stare lo zero (quella richiesta dal grafico più sbilanciato in negativo) e applica lo stesso range proporzionale a tutti — anche al grafico Controvalore, che non ha mai valori negativi, riservandogli lo stesso spazio sotto lo zero solo per allineamento
- nessun cambiamento quando nessuna categoria è in perdita: i grafici restano ad autorange come prima

**Colore della categoria ETC:**
- l'arancio `#FFA726` era troppo simile al mostarda/oro di GOV (`#E8B960`) in molti grafici e badge; nuovo colore terracotta `#C2410C`, verificato per separazione cromatica (CVD/deuteranopia) rispetto alle altre categorie
- fix di un'incoerenza architetturale: a differenza di GOV/ETF/FND, il colore ETC era scritto due volte come hex letterale (`core/asset_categories.py` e `core/constants.py`) invece di passare dalla palette centrale `COLORS` in `core/config.py` — ora è indiretto come le altre, e reagirebbe correttamente a un eventuale tema scuro futuro
- fix di un bug distinto: la card KPI "Valore Attuale per Categoria" (overview) coloritava l'etichetta di categoria tramite una classe CSS dedicata in `ui/styles.py`, non tramite la palette centrale — mancava la regola per ETC (ricadeva sul grigio muted di default) e, per lo stesso motivo, anche per LIQ/DER/ALTRO; aggiunte tutte e quattro

**Modalità Privacy — corretti 6 modi in cui rivelava (o falsava) ciò che doveva nascondere:**
- la sidebar mostrava un banner "🔒 Privacy attiva" (o "🔒 Privacy: N titoli nascosti") — vanificava lo scopo di mostrare l'app a qualcuno senza far capire che qualcosa è nascosto; rimosso
- **liquidità e patrimonio totale erano sbagliati, non solo non filtrati**: nascondere uno strumento rimuoveva i suoi eventi ACQUISTO/VENDITA dal registro, e `compute_portfolio_state` (`core/finance.py`) somma i flussi di cassa di tutti gli eventi per calcolare la liquidità — il risultato mostrava lo strumento nascosto come se fosse stato disinvestito (nei casi di test, +30.000€ di liquidità fantasma). Ora gli eventi restano nel registro con il ticker mascherato (nuovo `PRIVACY_HIDDEN_TICKER_SENTINEL` in `core/config.py`) invece di essere rimossi: la liquidità torna esatta, l'identità dello strumento resta comunque nascosta ovunque venga elencata per ticker/nome
- tutte le pagine di `ui/form_server/` (Strumenti, SATOR, Operazioni/Liquidità gestione, Export PP, Scheda strumento — quelle aperte dai pulsanti della sidebar) non applicavano mai il filtro privacy, mostrando sempre la lista completa degli strumenti; corretto nei rami di sola lettura, mai in quelli che salvano su disco (un salvataggio con privacy attiva non deve mai cancellare per sempre lo strumento nascosto — verificato con un test dedicato)
- due punti in `ui/pages/gestione_dati.py` leggevano dati grezzi da disco bypassando il filtro; corretto quello di sola lettura (tabella Arricchimento), lasciato volutamente invariato quello che salva (Bonifica avanzata)
- il campo note di un versamento automatico ("Versamento automatico per acquisto XXX") citava il ticker nascosto in chiaro anche se l'evento in sé (un movimento di cassa senza ticker proprio) non veniva toccato dal mascheramento; ora il ticker nascosto viene sostituito anche all'interno delle note
- i report AI salvati (tab "🤖 AI") sono testo libero generato in precedenza da Gemini e possono citare per nome uno strumento oggi nascosto — non redigibile in modo affidabile a posteriori (l'AI può riferirsi a uno strumento senza scriverne il ticker); i report salvati restano nascosti finché la privacy è attiva, tornano visibili disattivandola
- `apply_privacy_filter` è stato centralizzato in `persistence/storage.py` (prima viveva solo dentro `app.py`, duplicato per ogni pagina che ne aveva bisogno) — fonte unica usata sia dall'app principale che da tutte le pagine form-server

**Fix: data del weekend mostrata come giorno di trading nei grafici temporali:**
- `build_portfolio_history_df` (`core/finance.py`) aggiungeva una riga sintetica "oggi" anche di sabato/domenica quando `last_quotes_update` risultava più recente dell'ultima data reale in `storico_prezzi` — condizione che si verifica anche per un semplice refresh benchmark, non solo per nuovi prezzi. Risultato: tutti i grafici temporali di Cruscotti/Overview mostravano sabato o domenica come se il mercato avesse aperto, con lo stesso identico valore di venerdì solo rietichettato
- la riga era ridondante fin dalla 4.9.17: un refresh nel weekend scrive già i prezzi nell'ultimo giorno di borsa reale (`_apply_price_date_entries_to_storico` in `ui/sidebar.py`), quindi l'ultima riga vera del grafico è già allineata ai KPI — verificato che il valore della riga fantasma coincideva esattamente con quello di venerdì
- ora la riga sintetica "oggi" si aggiunge solo nei giorni feriali (snapshot infragiornaliero legittimo prima che arrivi la chiusura reale); verificato che questo caso continua a funzionare
- stesso identico problema, implementazione indipendente, trovato anche in `core/services/accumuli.py::_build_ticker_series` (i grafici "Prezzo vs PMC" e "Capitale vs Valore" di Cruscotti → Accumuli): aggiungeva un punto "oggi" col prezzo corrente senza nessun controllo sul giorno della settimana, sabato e domenica compresi — stesso fix, punto sintetico solo nei giorni feriali

**Font dei numeri troppo grande nella heatmap "Correlazione per strumento" (Cruscotti → Analitica):**
- `build_correlation_heatmap` (`ui/charts/analisi.py`) usava un font fisso a 12px per i valori dentro le celle, mentre la matrice ha dimensione fissa 540×540px (`ui/charts/settings.py`); con molti strumenti la cella si restringe (nel portafoglio reale, 16 strumenti → celle da ~34px) e numeri come "-0.85" traboccavano dal riquadro
- il font ora si adatta al numero di etichette (lato cella stimato × 0.3, minimo 8px, massimo 12px) — 16 strumenti → 10px, matrici più dense scendono fino a 8px, poche etichette restano a 12px come prima

**Fix: MAX/MIN in € invece che in % sui grafici "Rendimento" a indice Base 100:**
- i marker MAX/MIN di "Rendimento dello strumento" (Quotazioni) e "Rendimento Omogeneizzato per Tipologia" (Cruscotti) formattavano il valore con `extrema_value_format` di default ("eur0", es. "€ 118") anche se l'asse è un indice Base 100 dal 1° investimento, non un controvalore in euro
- aggiunto un formato dedicato `pct1_base100` (`ui/charts/extrema.py`) che converte l'indice in percentuale di rendimento rispetto a 100 (es. 118,3 → "+18,3%", 82,7 → "-17,3%") e impostato sui 4 chart_id con quella semantica (`ui/charts/settings.py`)

**Nuova tabella "Allocazione: bucket e strumenti" in Pianificazione, al posto del box "Lettura dell'allocazione":**
- il vecchio box testuale (dettaglio per strumento) restava poco leggibile anche dopo l'allineamento a colonne della 4.9.30; sostituito con una tabella unica sotto il grafico ad anelli (`ui/pages/pianificazione.py::_render_bucket_allocation_table`), che assorbe sia il confronto obiettivo/attuale sia l'elenco strumenti — niente più due box separati
- riga per bucket (Core/Difensivo/Satellite): nome colorato come l'anello, controvalore, e una barra obiettivo-vs-attuale (riempimento = quota attuale, tacca = obiettivo) con lo scostamento in % colorato su tolleranza di ribilanciamento (entro ±3% verde, entro ±8% ambra, oltre rosso)
- righe sotto ciascun bucket aggregate per natura/esposizione (non più una riga per strumento): colonna Natura (icona + etichetta) prima, colonna Strumenti dopo con l'elenco ticker che condividono quella natura, importo sommato e mini-barra col peso % riferito al gruppo natura dentro il bucket; riga TOTALE in fondo
- nuove classi CSS `bucket-alloc-*` in `ui/styles.py`, agganciate alle variabili tema dell'app (si adattano automaticamente a chiaro/scuro)

**Traduzione "Commodities" → "Materie prime":**
- l'etichetta di natura/esposizione era l'unico valore ancora in inglese nel sistema di classificazione automatica (`core/instrument_classification.py`, icona in `ui/charts/natura_icons.py`) — tradotta, insieme al dato già salvato per lo strumento XDBC.MI
- tradotto anche il campo `categoria_etf` (dato di arricchimento justETF, mostrato come "Categoria" nella scheda strumento) per XDBC.MI e GOLD.MI, che riportava "Commodities - ..."; resta un campo esterno, quindi un futuro ri-arricchimento potrebbe rieportare il termine inglese

**Rimozione sezione "Copertura e sovrapposizione" + promemoria nature in watchlist (Pianificazione):**
- la sezione (heatmap di copertura per natura/area di mercato, sotto la tabella "Allocazione: bucket e strumenti") era diventata ridondante con quella tabella, introdotta nella stessa sessione: rimossa, insieme alle funzioni backend/chart ormai inutilizzate (`build_coverage_matrix_frame`, `sator_matrix_doppioni_scoperte` in `core/services/sator.py`; `build_coverage_matrix_chart`, `_format_matrix_cell` in `ui/charts/pianificazione.py`) e alla config chart orfana rimasta in `ui/charts/settings.py`
- l'unica informazione utile che portava — le nature in watchlist non ancora presidiate da un possesso — resta come riga promemoria attenuata ("In osservazione", nessun ticker/importo) dentro la tabella "Allocazione: bucket e strumenti" esistente, nel bucket corretto: nuova `compute_watchlist_reminders` in `core/services/sator.py` (`ui/pages/pianificazione.py::_build_bucket_allocation_table_html`, nuova classe CSS `bucket-alloc-watchlist-row`)
- fix di un bug scoperto per l'occasione nel rendering esistente della tabella: un bucket senza strumenti posseduti veniva saltato per intero (`if sub.empty: continue`), il che avrebbe fatto sparire silenziosamente anche il promemoria — corretto per mostrare comunque l'intestazione del bucket quando c'è almeno un promemoria da mostrare

**Unificazione stati SATOR a 3 (in portafoglio / in osservazione / escluso):**
- gli stati SATOR erano 5 (`in_portafoglio`, `watchlist`, `candidato`, `escluso`, `fuori_piano`): la distinzione `watchlist`/`candidato` era artificiosa (uno strumento osservato per mesi può diventare candidato d'acquisto in qualsiasi momento senza bisogno di un'etichetta manuale diversa) e `escluso`/`fuori_piano` erano già identici in ogni comportamento nel codice — ridotti a 3, `watchlist` rietichettato "In osservazione" nell'editor universo SATOR
- nessuna riscrittura dei dati salvati: nuovo `_resolve_sator_state` (`core/services/sator.py`) interpreta in lettura i vecchi valori `candidato`/`fuori_piano` come `watchlist`/`escluso`, senza toccare `portafoglio_data.json` — usato nei 4 punti dove lo stato viene letto (editor universo, salvataggio editor, motore di ranking, promemoria watchlist)
- motore di ranking SATOR semplificato di conseguenza: un solo toggle `include_watchlist` nelle impostazioni (rimosso `include_candidates`, mai esposto in UI, da `core/services/sator.py` e `persistence/storage.py`), rimossi il conteggio e il ramo ormai morti (`candidate_count`, ramo "Challenger" di `challenger_flag`)

## 4.9.29 - Rifiniture Dashboard decisionale

**Allocazione: bucket e strumenti:**
- il grafico passa da sunburst a due donut concentrici con un gap visibile tra anello interno (Core/Difensivo/Satellite) ed esterno (natura/esposizione, raggruppata per bucket cosí i confini dei due anelli coincidono esattamente — un portafoglio con un bucket molto dominante, es. quasi tutto BTP, non fa più sembrare che uno strumento "sconfini" in un altro bucket); legenda a destra sulle nature possedute; l'hover dell'anello esterno elenca i singoli strumenti che compongono ciascuna fetta
- contromisura a una stranezza di rendering di Plotly che, anche disattivando l'ordinamento automatico, disegna comunque la prima fetta al suo posto ma inverte l'ordine di tutte le altre (`_pie_clockwise_order` in `ui/charts/pianificazione.py`) — riguarda entrambi gli anelli; la legenda dell'anello esterno usa tracce fittizie dedicate per restare nell'ordine corretto, indipendente da questa stranezza

**Riquadri "Lettura di...":**
- le righe con più campi (ticker/natura/importo, colonna/elenco strumenti, ecc.) si allineano ora in colonne a larghezza fissa invece di un'unica riga di testo unita da punto e virgola — interessa "Lettura dell'allocazione", "Lettura della matrice", "Lettura ante-post" e "Dettaglio composizione ordine"

**Copertura e sovrapposizione:**
- il punteggio 4 di un'area si divide equamente tra gli strumenti posseduti che la condividono (es. 2 strumenti sulla stessa area → 2 e 2 invece di 4 e 4): ogni colonna posseduta somma sempre a 4, il valore per riga indica quanto di quell'area è "tua" rispetto agli altri strumenti che la coprono già; doppioni/aree scoperte si riconoscono ora dal numero di celle diverse da zero, non più da un confronto `== 4`
- etichette colonna verticali per una matrice più compatta

**Prossimo acquisto: mappa decisionale:**
- sotto la mappa a bolle, nuovo riquadro "Fotografia di riferimento" con data/nota, importo vs budget, mix bucket e righe ordine dell'ultima fotografia SATOR salvata (stessi dati già presenti nello Storico decisionale, resi visibili senza dover scorrere fino a lì) — visibile anche quando la fotografia più recente è precedente a questo aggiornamento e non ha ancora i punteggi per la mappa a bolle (prima restava nascosto proprio nel caso per cui era stato pensato)

**Pulizia:**
- rimossa l'intestazione "Dashboard decisionale" (ridondante con i titoli dei tre grafici sottostanti) e la riga orizzontale doppia che compariva prima di "Liquidità da investire" quando il modulo SATOR Streamlit è nascosto (Impostazioni → SATOR "Solo pagina sidebar")

## 4.9.28 - Dashboard decisionale in Pianificazione, costi SATOR live, badge € in tabella

**Nuova sezione "Dashboard decisionale" nella scheda Pianificazione:**
- aggiunta subito dopo "Obiettivo di portafoglio" e prima del modulo SATOR Streamlit (ormai congelato: il percorso attivo per SATOR è la pagina `/sator` raggiunta dalla sidebar) — indipendente dal suo stato di sessione, usa solo il portafoglio corrente e l'ultima fotografia SATOR salvata su disco
- **donut ad anelli concentrici**: anello interno Core/Difensivo/Satellite, anello esterno i singoli strumenti posseduti colorati per natura/esposizione (stessa palette dell'icona già in Portafoglio/Quotazioni), con lettura testuale di coerenza rispetto al target impostato
- **matrice di copertura e sovrapposizione**: righe = strumenti posseduti, colonne = aree di mercato (unione tra natura dei posseduti e dei candidati SATOR), punteggio 0/4 — evidenzia doppioni (due strumenti sulla stessa area) e aree scoperte
- **mappa a bolle dei prossimi acquisti**: dati dall'ultima fotografia SATOR salvata (non da un'analisi dal vivo), quattro quadranti decisionali su diversificazione (asse X, soglia 0,58) e rischio stimato (asse Y = 1 − risk_efficiency, soglia 0,42 — stesse soglie già usate altrove nella pagina), dimensione bolla = importo proposto
- avvisi gialli per strumenti posseduti con natura non chiaramente classificata ("Esposizione diversificata") o con contraddizione benchmark/tipo, e per ticker della fotografia salvata con dati insufficienti (fotografia precedente a questo aggiornamento)
- `build_sator_decision_record` ora salva anche `risk_efficiency`/`diversification_benefit` per ogni riga dell'ordine, in modo retrocompatibile (le fotografie salvate prima di questo aggiornamento restano leggibili, semplicemente non hanno questi due campi)

**Costi SATOR (zero commissioni/TER/spread) letti live dall'arricchimento:**
- il fattore Costo del punteggio SATOR leggeva sempre valori vuoti (`commission_mode` "non_definito", `zero_commission` False, `ter`/`spread` 0.0): i campi non erano mai stati collegati a una sorgente dati reale, quindi il fattore Costo non riusciva a distinguere i titoli tra loro
- zero commissioni/TER/spread si inseriscono ora nel tab Strumenti → Arricchimento (nuovo campo con checkbox per zero commissioni) e vengono letti live da `infer_sator_metadata`: un aggiornamento in Arricchimento si riflette subito nel punteggio Costo, senza passare dal vecchio editor universo dormiente

**Badge € nella tabella SATOR:**
- accanto al ticker, un badge € (stesso stile dei punteggi in tabella) segnala gli strumenti non a zero commissioni, con tooltip esplicativo

**Rifinitura interna — classificazione fondi NAV irregolare:**
- `is_nav_fund` (fondi gestiti/OICVM con pubblicazione NAV non giornaliera, es. i FAM-) era duplicata in `ui/sidebar.py`, mentre `ui/charts/quotes_popup.py` usava un'euristica diversa e meno precisa basata sulla natura/esposizione dello strumento; ora è un'unica funzione condivisa in `core/instrument_classification.py`

## 4.9.27 - Classificazione automatica della natura/esposizione degli strumenti

**Icona "natura" in Quotazioni e Portafoglio, ora calcolata da dati affidabili invece che dal nome abbreviato:**
- l'icona descrittiva accanto a ogni strumento (Quality factor, Commodities, Mercati emergenti, Bene rifugio, ecc.) veniva ricalcolata a ogni apertura della pagina Quotazioni cercando parole chiave nel solo nome commerciale, spesso abbreviato da Fineco — verifica manuale contro i 26 strumenti reali del portafoglio ha trovato 6 classificazioni sbagliate: `IWQU.MI` e `XDWT.MI` finivano in categorie generiche perché il nome abbreviava "Quality"/"Technology" in modo che le parole chiave non riconoscevano più; `FAMAMW.MI` (Metals and Mining) finiva su "Commodities" generico invece che su "Metalli e miniere"; i 4 fondi `FAM-*` venivano tutti etichettati "Fondo gestito / multi-asset" solo per il prefisso del ticker, ignorando il loro vero tipo (uno di questi, `FAM-PU8`, è un fondo azionario, non multi-asset); `FLXI.MI` (azionario India) e `IB1T.PA` (Bitcoin) cadevano nel fallback "Esposizione diversificata" — l'opposto della realtà per un'esposizione concentrata
- la classificazione (`core/instrument_classification.py`, nuovo modulo) ora usa anche `benchmark` e `focus_etf` catturati dall'arricchimento justETF, che riportano per esteso ciò che il nome Fineco abbrevia (es. benchmark "MSCI World Sector Neutral Quality" per `IWQU.MI`, che il nome visualizzato tronca in "Wl Qu Fac"); aggiunta una regola dedicata per singolo paese azionario (Italia, India, Cina, Brasile, Giappone) basata sul testo di benchmark/focus, non su calcoli percentuali — questi ultimi si sono rivelati inaffidabili durante lo sviluppo (il campo `paesi_top` di `FLXI.MI` conteneva dati di un'altra tabella, scambiati durante lo scraping justETF); rimossa la regola sul prefisso ticker "FAM-", troppo ampia
- l'etichetta è ora calcolata una volta e salvata sullo strumento (nuovo campo `natura`), non ricalcolata a ogni render: viene impostata alla creazione dello strumento, ricalcolata a ogni arricchimento successivo, e per i 26 strumenti già presenti è stata retroattivamente calcolata al primo caricamento dati dopo l'aggiornamento, usando solo dati già salvati su disco (nessuna nuova chiamata di rete); resta modificabile a mano dal tab Arricchimento in Strumenti, come ogni altro campo arricchito, e una modifica manuale non viene mai sovrascritta da un arricchimento automatico successivo
- l'icona compare ora anche nella tabella Portafoglio (Home), tra le colonne "Tipo" e "Quote" — prima esisteva solo in Quotazioni

**Correzione automatica del campo tipo quando l'arricchimento lo smentisce:**
- `XBAE.MI` aveva tipo salvato "ETF Az. Globale" (azionario) ma è in realtà un "Xtrackers II ESG Global Aggregate Bond UCITS ETF" (obbligazionario) — il tipo sbagliato non alterava l'icona (che legge anche benchmark/focus) ma falsava le viste che dipendono dal tipo altrove nell'app (categoria, allocazione, corrispondenza con il benchmark); ora, quando benchmark/focus_etf sono in aperta contraddizione con il tipo salvato, la correzione scatta in automatico a fine arricchimento (e anche nella migrazione una tantum sopra), con lo stesso meccanismo già esistente per cui "il focus di investimento rifinisce il tipo"

**Rifinitura post-verifica in app:**
- l'etichetta "Fondo gestito / multi-asset" si contraddiceva da sola per i fondi il cui stesso campo tipo dice "Passivo" (es. `FAM-PU6`, "Fondo Bilan. Passivo": "gestito" implica gestione attiva) — ora diventa "Fondo bilanciato" quando il testo contiene "passivo", senza toccare i fondi davvero a gestione attiva (es. `FAM-FLEX`)
- la colonna icona in Portafoglio era stata inserita come prima colonna della tabella; spostata tra "Tipo" e "Quote"

## 4.9.26 - Coerenza in/fuori portafoglio in Benchmark, arricchimento unificato, mappe di calore ripristinate

**Cruscotti > Benchmark — distinzione in/fuori portafoglio:**
- `get_all_historical_tickers` e `build_instrument_benchmark_matrix` consideravano "in portafoglio" qualunque ticker con un record in `strumenti`, indipendentemente dallo stato: uno strumento chiuso restava etichettato "(In portafoglio)", un ticker mai posseduto (es. un benchmark di riferimento) risultava "(Venduto)"
- primo tentativo di fix — criterio `stato == "aperto"` — rivelatosi insufficiente sui dati reali: il campo `stato` risultava "aperto" su tutti i 26 strumenti del portafoglio, inclusi i 10 venduti per intero (l'auto-tag a "osservato" introdotto in `operazioni.py` dopo una vendita totale non era mai stato applicato retroattivamente agli strumenti già venduti prima)
- fix definitivo: nuova funzione condivisa `core/domain/positions.py::held_tickers(data)`, che calcola le quote correnti dagli eventi reali (stesso motore di `compute_portfolio_state`) invece di fidarsi del campo stato — verificato sui dati reali del portafoglio: 16 strumenti posseduti / 10 fuori portafoglio
- la matrice "Abbinamento strumenti/benchmark" e il grafico "Mappa coerenza/extra-rendimento" ora escludono del tutto le posizioni non possedute (prima le mescolavano senza alcuna etichetta)
- nel grafico "Performance normalizzata" gli strumenti fuori portafoglio hanno ora linea tratteggiata e "(fuori portafoglio)" nel nome traccia, non solo un colore diverso — utile anche per chi non percepisce bene i colori

**Rendimenti mensili e trimestrali — mappe di calore ripristinate in Cruscotti:**
- il grafico esisteva già (`quarterly_table_html`/`monthly_heatmap_html` in `ui/charts/summary.py`, la prima ancora usata nel report PDF esportabile) ma la chiamata in `cruscotti.py` era ridotta a un commento placeholder da prima dell'inizio dello storico git di questo repository — ricollegata
- le celle a intensità alta (rendimento vicino al massimo/minimo osservato) avevano testo dello stesso colore verde/rosso dello sfondo, poco leggibile: ora il testo passa a bianco sopra una soglia di intensità
- le tabelle vivono in `<iframe>` (isolamento CSS totale dal resto della pagina) e non ereditavano il font dell'app: ora il font-family è dichiarato esplicitamente
- aggiunta una legenda min/max a gradiente sotto ogni tabella, come i rendimenti mensili di justETF
- titolo unico "Rendimenti mensili e trimestrali - mappe di calore", mappa mensile prima della tabella trimestrale; intestazioni trimestrali T1/T2/T3/T4/TOT al posto di Q1-Q4/Anno, valori centrati come nei mensili, riga verticale prima della colonna TOT in entrambe le tabelle

**Arricchimento strumenti unificato in Strumenti (sidebar), stesso pattern già usato per lo storico prezzi:**
- prima sparso su tre punti scollegati: pulsante "Arricchisci tutti" in Gestione Dati (Streamlit, rerun completo percepito come bloccante per l'intera app), link "Arricchisci ora" nel popup Quotazioni (un punto pensato per la sola lettura che in realtà scriveva dati), form di modifica manuale/import PDF nella Scheda completa (`form_server.py`)
- ora tutto in un unico tab "🔎 Arricchimento" nella pagina `/strumenti`: selezione strumento, arricchimento automatico, import da PDF Fineco, modifica manuale dei campi — stesso pattern già collaudato dal tab "Storico" (form POST classico, nessun rerun Streamlit)
- Gestione Dati torna un puro visualizzatore (tabella stato/completezza per strumento, nessun pulsante che scrive); il popup Quotazioni non ha più alcun link di scrittura

**Import da PDF esteso oltre la Scheda Fineco:**
- il parser (`core/instrument_enrichment.py`) era tarato solo sull'export "Scheda titolo" della piattaforma Fineco; testato con successo anche contro 3 factsheet ufficiali di altri emittenti (Franklin Templeton/iShares, Xtrackers/DWS, Amundi): nuove etichette riconosciute (TER, domicilio, valuta, metodo di replica, politica di distribuzione, AUM con valuta e scala inclusi), date sia in formato `GG/MM/AAAA` che `GG.MM.AAAA`, normalizzazione degli apostrofi tipografici, guardie contro falsi positivi da intestazioni di tabella o testo "sbordato" tra colonne nei PDF a più colonne
- limite noto, non risolto: i factsheet a 3 colonne molto dense (es. Amundi) restano parzialmente inaffidabili per i campi `benchmark`/`nav` — limite strutturale dell'estrazione testuale semplice su layout multi-colonna, non un'etichetta mancante

**Fix minore:** il ticker Yahoo per l'ISIN `XS2940466316` (iShares Bitcoin ETP) restava bloccato su `BTCN.AS` nella cache di risoluzione automatica (`cache_lookup_strumenti`), nonostante il ticker corretto `IB1T.PA` fosse impostato sullo strumento — modificare il ticker da `/strumenti` non sincronizzava questa cache, che ha sempre priorità sul ticker esplicito ad ogni refresh quotazioni. L'azione "modifica" ora aggiorna anche la cache.

## 4.9.25 - Conferma candidati e classificazione automatica alla creazione di uno strumento

**Flusso cerca/conferma per l'aggiunta di uno strumento (`/strumenti`):**
- l'aggiunta di uno strumento nuovo era un'operazione automatica a un solo passaggio: `find_ticker` sceglieva un solo candidato tra quelli restituiti dalla ricerca ISIN di Yahoo Finance (fino a 5) e lo salvava subito, senza mostrare le alternative. Se l'euristica sbagliava borsa/quotazione, il portafoglio finiva con uno storico prezzi sbagliato senza alcun segnale a monte
- ora l'azione `aggiungi` è divisa in due: `cerca` (nessun salvataggio, mostra tutti i candidati trovati con prezzo già risolto, quello proposto pre-selezionato) e `conferma_aggiungi` (salva il candidato scelto, o i valori inseriti manualmente); un fallimento in un singolo candidato durante il recupero prezzo non blocca gli altri
- **euristica `.MI` automatica**: la ricerca ISIN di Yahoo spesso non restituisce la quotazione di Borsa Italiana anche quando esiste ed è quotabile direttamente (verificato su 8 dei 9 strumenti reali del portafoglio): se nessun candidato trovato finisce per `.MI`, si tenta `{simbolo_base}.MI` per ogni simbolo base distinto tra i candidati, proponendolo se risponde con un prezzo reale
- **ticker suggerito dall'utente**: campo opzionale nel form di ricerca — se compilato, viene verificato (prezzo reale) e proposto al posto dell'euristica automatica, o promosso se coincide con un candidato già trovato; utile per i casi (es. `IWQU.MI`) dove il simbolo su altre borse non assomiglia a quello di Milano e nessuna euristica può indovinarlo

**Classificazione tipo e benchmark da arricchimento justETF (ETF/ETC):**
- il tipo di uno strumento nuovo veniva dedotto da `deduce_type` cercando parole chiave nel solo nome commerciale: se il nome non conteneva nulla di riconoscibile, il tipo restava vuoto — mappando sulla categoria "ALTRO", esclusa dalle categorie visibili di default (`GOV, ETF, FND, AZI, OBB`) — lo strumento risultava invisibile in Quotazioni e nei KPI pur essendo salvato correttamente
- lo stesso problema esisteva per il benchmark di confronto (`resolve_instrument_benchmark`): senza una regola esplicita per ticker/ISIN, il fallback finiva quasi sempre su "MSCI World", indipendentemente da cosa lo strumento seguisse davvero
- l'app ha già una funzione di arricchimento (`enrich_etf_etc`) che recupera da justETF il focus di investimento dichiarato e il benchmark reale del fondo, ma nessuna parte dell'applicativo la consumava per queste due decisioni — restavano solo etichette statiche nella scheda strumento
- ora, aggiungendo un ETF/ETC nuovo (non BTP, non scelta manuale), l'arricchimento justETF viene chiamato automaticamente prima del salvataggio: il focus di investimento rifinisce il tipo (`deduce_type` accetta un parametro opzionale `focus_etf`), e il benchmark reale sceglie un ticker proxy specifico tramite una nuova tabella di pattern per famiglie di indici note (MSCI, FTSE, S&P, Nasdaq, Bloomberg Commodity, oro/minerari, India, Bitcoin), con priorità subito dopo le regole esplicite per ticker/ISIN e prima del fallback generico per tipo
- se l'arricchimento fallisce, lo strumento non è ammissibile (BTP, scelta manuale) o il benchmark non corrisponde a nessun pattern noto, il comportamento resta identico a prima — nessuna regressione
- l'azione manuale "Arricchisci" da Gestione Dati non cambia: continua ad aggiornare solo i dettagli che aggiornava già (TER, benchmark, focus, ecc.), mai nome/tipo

**Fix:**
- i candidati aggiunti dall'euristica `.MI` o dal ticker suggerito avevano nome vuoto: senza nome, `deduce_type` non classificava il tipo, che restava vuoto — stessa causa del bug "ALTRO" sopra, ma introdotta dalla stessa euristica pensata per risolverlo. Ora entrambi i percorsi recuperano il nome via `find_name(isin)` prima di costruire il candidato
- il guard che doveva evitare l'arricchimento automatico per le scelte manuali non scattava mai nel flusso reale: la variabile passata al controllo veniva silenziosamente sovrascritta dal recupero prezzo di fallback prima di arrivare al controllo stesso (ogni inserimento manuale ha sempre prezzo assente, quindi il fallback scattava sempre). Isolata in `_fs_resolve_price_and_enrichment`, che cattura la scelta originale prima che venga sovrascritta
- due pattern della nuova tabella benchmark erano troppo ampi rispetto a quanto previsto: `"bloomberg"` avrebbe assegnato il proxy materie prime anche a indici obbligazionari targati Bloomberg (ristretto a `"bloomberg commodity"`); `"gold"` avrebbe assegnato oro fisico anche a ETF su società minerarie aurifere, bypassando la distinzione già esistente altrove nello stesso file (aggiunta una regola più specifica per i minerari, controllata prima di quella generica sull'oro)

## 4.9.24 - Recupero storico prezzi spostato in Strumenti (sidebar)

**Nuovo tab "Storico" nella pagina standalone `/strumenti`:**
- il recupero manuale dello storico prezzi (Yahoo Finance, merge non distruttivo) si faceva prima in Gestione Dati (Streamlit), dove il rerun completo dopo ogni azione lo rendeva percepito come bloccante per l'intera app; ora vive in `/strumenti`, un form POST classico che aggiorna solo se stesso
- tendina di selezione strumento con conteggio date già salvate e prima data disponibile in coda al nome (es. `TICKER — Nome (12 date, dal 03/01/2024)`) — nessuna tabella riepilogativa separata, la data compare semplicemente scegliendo lo strumento
- "Data di partenza" precompilata con la prima data che il sistema ha già per altri strumenti (`earliest_storico_date`), modificabile o azzerabile per importare tutto ciò che Yahoo ha disponibile
- nuova sezione "Elimina storico salvato": rimozione per strumento, per intero o solo in un intervallo di date, senza toccare gli altri strumenti sulle stesse date
- date in formato italiano GG/MM/AAAA ovunque nel tab (proposta, campi di eliminazione, messaggi di conferma), con parsing flessibile in ingresso (accetta anche YYYY-MM-DD)

**Fix:**
- `_fs_delete_instrument`, `_fs_delete_event`, `_fs_update_event` andavano in `NameError` su `save_data` da `/strumenti` e `/operazioni_gestione` standalone (import mancante nello scope della funzione): i dati venivano modificati in memoria ma mai salvati su disco
- i grafici di Quotazioni restavano quelli vecchi dopo un recupero storico, anche dopo aver riavviato l'applicativo. Due bug distinti, stessa causa di fondo:
  1. `core/cache_signatures.py` decideva se una firma dati era cambiata guardando solo `len(storico_prezzi)` e `max(storico_prezzi.keys())` (conteggio/data più recente su tutte le date, non per strumento). Un backfill che riempie date più vecchie **già presenti come chiave** (perché altri strumenti hanno già un prezzo su quel giorno) non tocca né l'uno né l'altro, quindi la firma restava identica e `core/figure_cache.py` continuava a servire la figura vecchia da disco.
  2. anche correggendo la firma, il grafico veniva "ricostruito" ma a partire dagli STESSI dati vecchi: `core/state.py` (`StateManager._derived_data_token` e `_build_hist_df_token_for`, usati da `get_hist_df_for`/`get_expanded_price_frame_for`/`get_portfolio_state_for`) ha una cache separata dei DataFrame storici, **persistita su disco** in `data/cache/derived_runtime/*.pkl` — sopravvive al riavvio dell'app — con lo stesso identico bug (solo `len(storico)`/`max(storico.keys())`). Era questa la cache che spiegava perché il problema persisteva anche dopo un riavvio completo.

  Entrambe ora includono `history_span_by_ticker`/`history_span` (quante date storiche include ciascun ticker e la più vecchia — funzione condivisa `core.cache_signatures.history_span_by_ticker`, riusata da `core/state.py`): catturano il backfill restando comunque stabili durante un refresh quotazioni intraday, che aggiorna solo il valore del prezzo odierno, non le chiavi. Il cambio di formato del token invalida automaticamente, una tantum, tutte le cache (figure e pickle) scritte dal codice precedente: non serve alcuna pulizia manuale, basta un riavvio con il fix applicato. Copertura di regressione in `tests/test_backfill_signature_invalidation.py` (firme + token StateManager) e `tests/test_state_hist_df_token.py`

## 4.9.23 - Parser PDF universale: label-proximity scanner

**Parser PDF completamente riscritto (`core/instrument_enrichment.py`):**
- eliminati i tre parser tipo-specifici (`_parse_pdf_btp`, `_parse_pdf_etf`, `_parse_pdf_fam`) che si rompevano ad ogni variazione di layout
- sostituiti da un unico scanner basato su dizionario di etichette italiane → campo + tipo valore (`_PDF_LABELS`, `_scan_labels`)
- `_scan_labels` cerca ogni etichetta su qualsiasi riga del testo estratto (non solo a inizio riga), con guard word-boundary; le etichette più lunghe hanno precedenza sulle più corte
- `_norm_line` normalizza per il match: rimuove accenti (NFD), collassa spazi, lowercase — le chiavi del dizionario non hanno mai accenti
- `_scan_rendimenti` estrae YTD / 1A / 2A / 3A / 5A / 10A con doppio layout (label-poi-valori e label/valore alternati); il `last_val_end` tracking evita che più etichette sulla stessa riga rivendichino lo stesso valore
- `_scan_morningstar` gestisce stelle Unicode ★ e font-icon privati
- `_scan_holdings` estrae la sezione "Primi N titoli" con terminatori flessibili (Avvertenze / Educational / Dati in tempo reale / fine testo)
- `_scan_distribuzione` imposta "Distribuzione" solo in presenza di un dividendo numerico (niente falsi positivi)

**Bug corretti:**
- `parse_fineco_pdf(pdf_bytes, tipo="etc")` restituiva `{}` perché il tipo "etc" non era gestito → ora il parametro `tipo` è ignorato nel parser PDF (rimane per compatibilità API); il parser estrae tutti i campi presenti indipendentemente dal tipo
- `categoria_etf` non veniva più popolata dopo l'import PDF → mappatura corretta da etichetta "Categoria" → campo `categoria_etf`

**Aggiungere un nuovo campo = una riga nel dizionario `_PDF_LABELS`.**

**Fix minori parser/enrichment:**
- `_scan_distribuzione` riconosce `(-)` come Accumulazione
- `morningstar` rileva qualsiasi codepoint PUA per le stelle rating; rimosso il rating dal core ETC
- `_rend_cls` non va più in crash su numeri italiani con separatore delle migliaia (es. `9.284,27`)

**Tabella arricchimento:**
- nuova colonna completezza % per strumento, altezza dinamica della tabella

**SATOR — gestione decisioni salvate:**
- helper `remove_sator_decision` e pulsante elimina per le fotografie decisionali salvate in `/sator`
- legenda colonne (riquadro + tooltip) nella tabella SATOR standalone

**Obiettivo di portafoglio unificato (Core/Difensivo/Satellite):**
- nuova sezione "Obiettivo di portafoglio" in Pianificazione: tre percentuali Core/Difensivo/Satellite (con preset rapidi che mostrano i numeri reali, non solo un nome), cap di concentrazione per asset class e pesi delle 5 dimensioni SATOR tutti editabili e trasparenti, con box informativo sulla matematica interna che resta fissa
- sostituisce ovunque il vecchio profilo GOV/ETF/FND (`target_profile_default`, con bug di naming come il fallback "Bilanciato" inesistente): "Liquidità da investire", il tetto satellite in Pianificazione, il grafico "Allineamento rispetto ad obiettivo" in Cruscotti e il radar Home/Cruscotti ora leggono tutti lo stesso obiettivo
- radar Home/Cruscotti derivato dall'obiettivo invece che da 4 preset nascosti (`RADAR_PROFILE_PRESETS`): assi quantitativi dai cap di concentrazione per natura, assi qualitativi per interpolazione sulla quota Satellite
- tabella SATOR standalone: colonna "Perché" sostituita da un badge Ruolo (Core/Difensivo/Satellite) per riga, e badge di avviso quando lo storico prezzi è troppo corto (<30gg) per un giudizio affidabile
- finestra rischio/rendimento SATOR estesa da 6 a 12 mesi per ridurre il rumore statistico
- migrazione automatica e non distruttiva: chi aveva un vecchio profilo salvato lo ritrova tradotto in Core/Difensivo/Satellite alla prima apertura
- rimossi (verificata l'assenza di chiamanti residui): `get_default_target_profile`, `build_target_gap_by_instrument`, `build_rebalancing_suggestions`, i campi settings `target_profile_default`/`rebalancing_target`, `RADAR_PROFILE_PRESETS`

**Rifiniture post-merge dell'obiettivo di portafoglio:**
- corretto un bug per cui la sezione "Obiettivo di portafoglio" spariva del tutto in Pianificazione se l'utente aveva impostato "Solo sidebar" per SATOR: ora si vede sempre, indipendentemente da quella modalità
- tabella SATOR standalone: colonne compattate (niente più scroll orizzontale), badge Ruolo ridotto a un quadratino colorato (blu/verde/arancio, senza etichetta testuale) per recuperare spazio su Ticker/Strumento/Funzione
- grafico "Obiettivo vs Attuale" corretto due volte: prima sommava le due serie invece di affiancarle (arrivava a leggere oltre il 100% su un bucket), poi è stato riportato allo stesso stile Plotly/tema già usato dagli altri grafici della pagina (st.bar_chart aveva uno zoom su hover non richiesto e non seguiva il tema)
- i tre grafici Core/Difensivo/Satellite di Pianificazione migrati dal layout scritto a mano al sistema centralizzato `ui/charts/settings.py` + `finalize_chart`, stesso meccanismo usato dagli altri grafici dell'app
- rimosso un intero modulo di codice morto (`ui/charts/pianificazione.py`, 8 funzioni residue di una versione precedente della pagina mai più chiamate) e la voce di configurazione orfana `overview_patrimonio`
- corretto un bug indipendente trovato nel frattempo: il grafico "Allineamento rispetto ad obiettivo" di Cruscotti applicava per errore le impostazioni di un altro grafico
- numeri sulle barre dei grafici di Pianificazione ingranditi (14px) e in formato italiano con un decimale (es. "55,2%")
- rimossa la sezione "Simulatore pre-operazione" (mai utilizzata)

---

## 4.9.22 - Sidebar avanzata: PP Export, SATOR, modalità accesso operativo

**Esporta PP dalla sidebar (`/export_pp`):**
- nuova pagina form_server con statistiche (strumenti / transazioni / date prezzi) e due link di download diretti
- GET `/export_pp/transazioni` → scarica `portfolio_performance.csv` (UTF-8 BOM, stesso formato del tasto in Dati)
- GET `/export_pp/prezzi` → scarica `prezzi_storici_pp.zip`
- pulsante **📊 Esporta PP** in sidebar

**SATOR dalla sidebar (`/sator`):**
- pagina form_server a due step: input (budget, severità concentrazione 1–4, linee massime, categorie) → analisi
- tabella ranking con semaforo 🟢/🟡/⚪, ticker, strumento, funzione, voto, Fit/Mom/Risk/Div/Cost, prezzo, quote possedute e quota suggerita
- pannello valutazione live aggiornato via JS: totale ordine, delta budget, headline (Entro budget / Fuori budget / Budget sottoutilizzato / Appena fuori budget)
- pulsanti "↺ Usa suggeriti" (pre-popola Qta con i valori SATOR), "✕ Deseleziona", campo note
- **📸 Salva fotografia** → `build_sator_decision_record` + `save_sator_decisions`; redirect con conferma
- pulsante **🧠 SATOR** in sidebar

**Impostazioni — Modalità accesso operativo:**
- nuovo campo `operativo_mode` in `default_settings()` (default `"entrambi"`)
- radio in Impostazioni → Aspetto: *Entrambi / Solo sidebar / Solo Centro Operativo*
- `"Solo sidebar"` → nasconde il Centro Operativo nella pagina Operazioni
- `"Solo Centro Operativo"` → nasconde i 6 pulsanti operativi in sidebar
- impostazione persistente in `settings.json`

**Fix eliminazione versamento (persistenza cache):**
- dopo la cancellazione di un VERSAMENTO il dato riappariva al riavvio perché `n_liquidita` non era incluso nella firma cache
- aggiunto `n_eventi` e `n_liquidita` alla firma in `core/cache_signatures.py`
- helper functions in `_delete_event_by_id` wrappate in try/except per garantire `save_data` anche in caso di errore secondario

**Schema invariato (3.3)**

---

## 4.9.21 - Quotazioni: frecce doppie, Δ Prezzo, popup link fonte, fix scroll e timeout

**Quotazioni — frecce doppie (▲▲ / ▼▼):**
- variazioni di prezzo superiori al 3% mostrano doppia freccia `▲▲` / `▼▼` in luogo della singola
- applicato sia nella tabella Quotazioni che nelle colonne analoghe in Portafoglio
- `build_price_direction_map` in `ui/components.py` ora restituisce `"up_big"` / `"down_big"` oltre a `"up"` / `"down"` / `"flat"`; `_trend_sym` in `portfolio_popup.py` e `_trend_symbol` in `tables.py` aggiornati di conseguenza

**Quotazioni — colonna Δ Prezzo:**
- nuova colonna dopo le colonne importo che mostra `prezzo − prezzo_prec` (variazione assoluta della quotazione, non del controvalore in portafoglio)
- 3 decimali, verde per positivo, rosso per negativo, "—" sotto soglia 0.0005
- ordinabile come le altre colonne numeriche

**Quotazioni — popup: link fonte:**
- nel popup di dettaglio strumento, sotto "Fonte / AGG.", compare la riga "Link fonte" con l'URL cliccabile che apre direttamente la pagina sorgente
- Borsa Italiana → pagina dati-completi BTP con ISIN specifico; Yahoo Finance → `finance.yahoo.com/quote/{ticker}`

**Fix scroll-to-bottom:**
- il `sendH()` dell'iframe salvava `window.parent.scrollY` prima del `postMessage` e lo ripristinava a 10/60/200 ms, impedendo lo scatto a fondo pagina dopo ogni elaborazione
- fix applicato a `quotes_popup.py`, `portfolio_popup.py`, `tables.py`

**Fix Gemini timeout:**
- `requests.exceptions.ReadTimeout` (e `RequestException`) non era catturato dall'handler UI `except RuntimeError`
- `call_gemini_flash` e `call_gemini_chat` in `core/ai_analysis.py` ora wrappano `requests.post` in `try/except Timeout/RequestException` e rilanciano come `RuntimeError` con messaggio leggibile

**Fix BTP zero-padding:**
- Borsa Italiana restituisce "9.38.17" per orari mattutini → `hh = "9"` → timestamp "2026-06-23 9:38" (15 char) → tutti i controlli `len >= 16` fallivano → cache non salvata, UI mostrava solo la data
- fix: `hh.zfill(2)` → "2026-06-23 09:38" (16 char)

**Fix prezzo stale a mercato aperto:**
- XDBC.MI / XDRE.MI mostravano verde anche se il prezzo era del giorno precedente con mercato già aperto
- nuova funzione `_is_stale_open_market()` in `ui/sidebar.py`: se `price_date < oggi` e siamo in un giorno lavorativo dopo le 09:30 e lo strumento non è un fondo NAV, imposta `status="warning"` ma usa comunque il prezzo
- il tooltip del warning mostra il messaggio esplicativo (fix al lookup `latest_log_item` in `quotes_popup.py`)

**Schema invariato (3.3)**

---

## 4.9.20 - Esporta portafoglio per Portfolio Performance

**Esportazione CSV per Portfolio Performance:**
- nuovo pulsante "Esporta per Portfolio Performance" nella tab Dati
- genera CSV delle transazioni con colonne in italiano (`Data`, `Tipo`, `Valore`, `Quote`, `Commissioni`, ecc.) compatibili con PP installato in lingua italiana
- tipi transazione italianizzati: `Acquisto`, `Vendita`, `Dividendo`, `Prelievo`, `Deposito`
- decimali europei (virgola come separatore) per compatibilità diretta con PP
- secondo pulsante per export prezzi storici ZIP: archivio multi-file per ticker, pronti per l'importazione storico prezzi in PP

**Schema invariato (3.3)**

---

## 4.9.19 - Strumenti chiusi, linea acquisto in Quotazioni, SATOR in cima, fix foto

**Operazioni — strumenti aperto/chiuso:**
- aggiunto campo `stato` (`"aperto"` / `"chiuso"`) al modello `Strumento` in `core/data_models.py`, con i campi opzionali `data_chiusura` e `motivo_chiusura`
- chiusura automatica su **VENDITA totale** (quantità residua ≤ 0) e su **RIMBORSO A SCADENZA**
- riapertura automatica su **ACQUISTO** successivo su uno strumento già chiuso
- il selettore strumenti nel form operazioni filtra i chiusi (mostrati solo nella tab dedicata)
- nuova tab "Chiusi" nel dialog strumenti: tabella con Ticker, Nome, Tipo, Chiuso il, Motivo

**Quotazioni — linea data di primo acquisto:**
- `build_quote_history_time_chart` accetta il parametro `purchase_date`: aggiunge una linea verticale tratteggiata con etichetta "Acquisto" nel grafico storico di ciascun strumento, allineata alla prima data operativa reale
- strumenti non più in portafoglio mostrano sfondo ambra distinto nel grafico

**Pianificazione — riordino sezioni:**
- modulo SATOR spostato in cima alla scheda Pianificazione; "Simulatore pre-operazione" rimane sotto, separato da divisore

**SATOR — fix storico decisionale (foto):**
- lo "Storico decisionale SATOR" è ora sempre visibile all'apertura della scheda, senza dover rilanciare l'analisi
- in precedenza era bloccato da due `return` anticipati (sessione senza `sator_result` o senza selezione manuale), rendendolo inaccessibile a ogni riavvio dell'app
- il pulsante "Salva fotografia" usa `session_state` (`sator_result` + `sator_manual_alloc`) invece di `combo_df`

**Schema invariato (3.3)**

## 4.9.17 - Performance normalizzata Benchmark, ottimizzazioni cache, fix weekend

**Benchmark — Performance normalizzata:**
- nuova sezione "Performance normalizzata" nella tab Benchmark di Cruscotti: sovrappone più strumenti (inclusi venduti) normalizzati a 0% da una data o un'origine comune
- modalità **Data comune** (calendario) o **Origini allineate** (ogni strumento parte da Giorno 0)
- filtri: multiselect ticker (con badge "In portafoglio" / "Venduto"), radio periodo (1M / 3M / 6M / 1A / 3A / Tutto), pulsante "Costruisci grafico" on-demand per evitare rebuild automatici
- implementato in `ui/charts/benchmark.py`: `build_normalized_performance_chart`, `get_all_historical_tickers`, `resolve_period_start_date`
- test dedicati in `tests/test_normalized_performance_chart.py`

**Ottimizzazioni performance — firme cache granulari (12 step):**
- `build_category_data_signature`: aggiornamento prezzi di una categoria non invalida figure delle altre (GOV, ETF, FND, ETC separati)
- `build_ticker_data_signature`: ogni grafico in Quotazioni ha firma per-ticker; un refresh parziale non ricostruisce i grafici invariati
- `build_historical_data_signature`: 5 chart storicamente stabili (correlazione, drawdown, performance per categoria, ...) ignorano i prezzi live e restano in cache su ogni refresh intraday
- `resolve_analysis_render_sig`: figure Benchmark e Accumuli usano firma stabile (senza prezzi live)
- `charts_settings_signature` usa solo content hash (no `mtime`/`size`): touch del file settings non scatena più rebuild completo
- storico precedente: `@st.cache_data(persist="disk")` su `orchestrate_data_cached` aveva ridotto gli avvii caldi, ma in 5.0-pre e' stato sostituito da `runtime.orchestration_payload`
- `build_hist_df_token_for` esclude le operazioni dalla firma: insert operazione non invalida più `hist_df` (~2-5s risparmiati per ogni inserimento)
- pre-worm `home_concentration` con parametri corretti: eliminati ~0.6s al primo accesso Home
- rimossi 5 chart morti dal pre-worm bundle; aggiunte 5 figure Analitica corrette: primo accesso Cruscotti/Analitica da ~22s a istantaneo
- `context_refresh.py` (`refresh_volatile_ctx_fields`): ripristina i campi non serializzabili (`fmtd`, `fmtds`, `header_date`) dopo la deserializzazione da disco

**Fix correttezza dati weekend:**
- `_apply_price_date_entries_to_storico` in `ui/sidebar.py`: su refresh di sabato/domenica scrive i prezzi nel giorno precedente lavorativo di `storico_prezzi` (prima veniva saltato)
- `build_portfolio_history_df` aggiunge il punto "oggi" anche nel weekend se `last_quotes_update > ultimo storico`
- cache interna `cache_storico_portafoglio` include `last_quotes_update` nella chiave (v3→v4): evita che il fix weekend venga ignorato per cache stale
- risultato: P/L nei KPI e P/L nel grafico storico ora sempre allineati, anche nei weekend

**Risultati misurati (13 giugno 2026, benchmark prima/dopo):**
- avvio caldo: ~35s → ~0.19s (disk cache hit)
- orchestrazione post-insert: ~35s → ~2.41s
- `get_hist_df_for` su insert: invariato (0.00s, cache hit grazie a firma separata)

**Schema invariato (3.3)**

## 4.9.18 - Pagina AI top-level, payload selector, chat, report library

**Navigazione:**
- nuova pagina top-level "🤖 AI" inserita dopo Pianificazione
- tab "Gestione Dati" rinominato "Dati"
- tab "Impostazioni" rinominato "Setup"
- tab AI rimosso da Cruscotti (ora pagina standalone)

**Pagina AI — 3 sub-tab:**
- **Analisi**: filtri payload per ticker, categoria e sezioni dati; modalità Testo o Avanzata (output JSON strutturato + grafici Plotly: radar score strumenti, proiezioni rendimento per categoria, scenari di stress); bottone "Salva report" → `data/ai_reports/`
- **Chat**: conversazione multi-turn con Gemini; portafoglio iniettato come contesto nel primo messaggio; "Nuova chat" per reset sessione
- **Report**: libreria report salvati (testo + dati strutturati + payload); eliminazione singolo report; diff tra due report via Gemini

**Configurazione AI in Setup:**
- API key salvata su disco in `data/config/ai_config.json` (priorità: secrets.toml > config.json > session)
- modello Gemini default configurabile; test connessione integrato

**Core (`core/ai_analysis.py`):**
- `build_portfolio_ai_payload` esteso con `filter_tickers`, `filter_categories`, `include_sections`; peso sempre relativo al portafoglio completo
- `call_gemini_structured`, `call_gemini_chat`, `call_gemini_diff`, `_parse_structured_response`
- `build_gemini_prompt` esteso con `structured=True/False`
- `load/save_ai_config`, `save/load/delete_ai_report`

**Test:** +65 nuovi test (311 totali); schema invariato (3.3)

## 4.9.15 - Streamlit 1.58 compatibility archive

- updated Streamlit requirement to `1.58.*`
- migrated deprecated Streamlit HTML iframe rendering from `components.html` to centralized `st.iframe` helper
- replaced residual deprecated `use_container_width=True` usages with `width="stretch"`
- preserved financial logic, schema version, chart settings, layout structure, and user-facing flows
- app version aligned to `4.9.15`; schema unchanged (`3.3`)

## 4.9.14x - Fase 3 avvio: pre-render iniziale centralizzato

- aggiunta configurazione centrale `ui_pre_render` per governare pre-render iniziale, fallback background, cooldown e scope
- collegato il bootstrap al pre-render completo iniziale quando la firma dati/tema cambia, mantenendo il prewarm background come fallback configurabile
- aggiunti controlli in Impostazioni > Avanzate e test dedicato sulla normalizzazione delle impostazioni

## 4.9.14 - Category perimeter alignment, data maintenance, debug split

- introduced configurable active categories up to 5, with propagation across key pages, shared datasets, snapshots, planning, and main category-driven charts
- aligned the active-category semantics so disabled categories are excluded from the operational portfolio perimeter instead of being only visually hidden
- improved data maintenance in Gestione Dati with category/ticker inventory and brutal cleanup support across portfolio data, history, ledger rebuild, and quotes log
- split rendering diagnostics into two independent controls: progress bar under the header and textual render log at page bottom
- improved quotes diagnostics table with portfolio-presence status and clearer handling of inactive instruments
- app version aligned to `4.9.14`; schema unchanged (`3.3`)

## 4.9.11 - UI Reorganization: Andamento/Analisi removal, Cruscotti hub, Summary as report generator [COMPLETED]

**Major structural changes:**
- ✅ removed Andamento and Analisi tabs from app.py
- ✅ consolidated all analytics content into Cruscotti with Analitica sub-tab (5 sub-tabs total: GOV/ETF/FND/Tutto/Analitica)
- ✅ removed "Patrimonio" view from Overview (now P/L del portafoglio + P/L per Categoria only)
- ✅ transformed Summary from visualization-based page to report generator (5 sections: Identity, Inclusions, Preview, Generate, Recent outputs) — zero on-screen visualizations
- ✅ operations page confirmed: "Spesa mensile per acquisto strumenti" section already present
- ✅ added Pianificazione tab (new tab 7 of 9) with placeholder for what-if simulator and liquidity planner

**Quotazioni page enhancements:**
- ✅ Drawdown per singolo strumento with radio toggle (Peggiori 6 / Tutti / Selezione manuale)
- ✅ Correlation matrices: strumenti (correlation heatmap) + macro-categorie (GOV/ETF/FND)
- ✅ Risk/Return table per ticker (dfstats) with metrics: Total Return, CAGR, Volatility, Sharpe, Max Drawdown, VaR, CVaR, Sortino, Calmar

**Schema unchanged (3.3)**. App structure: 9 tabs (Quotazioni, Portafoglio, Operazioni, Cruscotti, Summary, Confronto, Pianificazione, Gestione Dati, Impostazioni). All imports validated. Ready for 4.9.12+ incremental work.

## 4.9.10 - Cache optimization, benchmark scheduler, pre-warming

- synchronous pre-warming of essential dataframes (portfolio_state, history_df) with 2-second timeout in StateManager
- benchmark refresh moved outside critical path: manual refresh via Gestione Dati + automatic scheduler at 18:00 IT daily
- new Benchmark section in Gestione Dati with per-ticker refresh timestamps and freshness badges
- benchmark scheduler with exponential backoff retry and persistent state
- schema version unchanged (3.3)

## 4.9.9 - Cleanup e infrastructure improvements

- removed dead code: dark theme completely eliminated from codebase
- migrated figure cache from pickle.gz to JSON+gzip with automatic legacy conversion
- added render profiler always-on reporting in Data Management page (Performance section)
- added cache scenario badge in header (cold_start, post_data_change, warm_rerun)
- cleaned up unused placeholder variables
- schema version unchanged (3.3)

## 4.5 - Final roadmap release

- completed structural refactor and roadmap closure
- redesigned Summary as the main reporting hub
- integrated operational brief into Summary
- added Data Management page for backup, audit, observability, and quote maintenance
- improved reporting traceability and compliance exports
- added custom benchmark support and richer settings model
- introduced visible i18n groundwork for key UI sections
- completed final UI polish, spacing, naming, and reporting output cleanup

## Notes

- runtime folders such as `data/` and `backups/` are generated locally
- some secondary translations can still be extended over time
- current Pydantic deprecation warnings are known and non-blocking
