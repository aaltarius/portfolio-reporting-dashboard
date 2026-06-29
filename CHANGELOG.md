# Changelog

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
