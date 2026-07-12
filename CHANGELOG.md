# Changelog

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
- `@st.cache_data(persist="disk")` su `orchestrate_data_cached`: dati persistono su disco tra restart; avvio caldo da ~35s+ a ~2-5s
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
