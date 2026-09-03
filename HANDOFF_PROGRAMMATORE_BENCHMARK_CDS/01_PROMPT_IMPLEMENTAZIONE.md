# PROMPT OPERATIVO DA ESEGUIRE SUL REPOSITORY REALE

Agisci come senior Python/software engineer e modifica il progetto esistente senza creare un sottosistema parallelo.

## CONTESTO VINCOLANTE

Nel progetto esiste `benchmark_registry.py`, attualmente usato come fonte centrale per benchmark e richiamato da Quotazioni, Cruscotti, Summary, refresh cache e altri moduli.

La vecchia logica contiene cataloghi statici (`BENCHMARK_BY_TICKER`, `BENCHMARK_BY_ISIN`, `BENCHMARK_BY_TYPE`, `BENCHMARK_BY_MACRO`, `BENCHMARK_BY_INDEX_PATTERN`, `LEGACY_BENCH`) e proxy fissi. Questa architettura deve essere eliminata dal percorso automatico.

**Non aggiungere ulteriori eccezioni. Non creare nuovi dizionari equivalenti con nomi diversi.**

## RISULTATO RICHIESTO

Partendo esclusivamente da ticker/ISIN, produrre un `InstrumentAnalysis` unico con:

1. identità runtime;
2. profilo strutturale;
3. C/D/S;
4. benchmark ufficiale;
5. curva operativa;
6. relazione: PROPRIA/SORELLA/CUGINA/ZIA/NONNA/FAMIGLIA AMPIA/MERCATO GENERALE;
7. componenti e pesi se multi-asset;
8. metriche;
9. confidence;
10. provenance;
11. cache/versione/timestamp.

Tale risultato deve essere la sola fonte usata da tutto il software.

---

## A. ZERO-KNOWLEDGE CORRETTO

"Zero aiutini" significa:

VIETATO in produzione:
- mapping ticker→benchmark;
- mapping ISIN→benchmark;
- mapping tipo→ticker benchmark;
- mapping macro→ticker benchmark;
- famiglie di simboli precaricate;
- eccezioni per singolo strumento;
- cache di risoluzioni precompilata nel codice o distribuita come knowledge base.

CONSENTITO e richiesto:
- tassonomie finanziarie generiche;
- parsing generico di testi;
- interrogazione runtime di fonti online;
- cache generata autonomamente dal programma;
- manual override esplicito dell'utente, separato dall'automazione.

---

## B. PIPELINE ONLINE-FIRST / INFERENCE-LAST

### B1 — Identity discovery, in parallelo

Input: `ticker`, `isin`.

Fonti:

1. **Borsa Italiana**
   - per ETF: denominazione, tipo, benchmark ufficiale, benchmark code, area/stile, Bloomberg ticker, RIC, valuta;
   - per BTP/bond: denominazione, emittente, tipologia, scadenza, duration, cedola, valuta.

2. **OpenFIGI**
   - mapping per `ID_ISIN`;
   - name, ticker, securityType/securityType2, marketSector, exchange, FIGI.

3. **Yahoo/yfinance**
   - Search / Lookup / Ticker;
   - per indici usare `Lookup(query).get_index()`;
   - storico serie con `history`/download;
   - non scegliere ETF come benchmark.

4. **Emittente / factsheet / KID**
   - soprattutto fondi e multi-asset;
   - discovery generica per ISIN/nome runtime, senza URL hard-coded per strumento.

5. **Provider indice**
   - MSCI, STOXX, FTSE Russell, S&P DJI, Nasdaq, Solactive, Bloomberg, ICE, ecc.;
   - provider dedotto dal benchmark trovato online;
   - canonicalizzare nome/codice/variante/valuta/universo.

Le fonti concordanti aumentano confidence.
Le fonti discordanti producono warning e provenance.

---

## C. PROFILO FINANZIARIO CENTRALE

Creare un `InstrumentProfile` con almeno:

- asset_class
- structural_type
- geography
- geo_scope
- sector
- theme
- factor
- size
- market_breadth
- issuer_type
- currency
- hedged
- duration_years
- maturity_date
- commodity_type
- asset_mix
- confidence
- completeness
- provenance

Non derivare il profilo dal benchmark di fallback.

---

## D. C/D/S

Recuperare/mantenere la logica validata POC17.2/17.4.

Target di regressione: **>= 99,4/100** sul fixture dei 111 strumenti.

Vincoli:
- C+D+S = 100%;
- benchmark/fallback non può modificare C/D/S;
- conservare raw percentages, active roles, confidence, flags, reliability e reasons.

I file di riferimento sono in `reference/`.

---

## E. BENCHMARK: IDENTITÀ UFFICIALE ≠ CURVA OPERATIVA

Conservare separatamente:

### Identità ufficiale
- official_benchmark_name
- official_benchmark_code
- official_benchmark_provider
- official_benchmark_source

### Curva operativa
- operational_series
- operational_provider
- operational_kind
- resolution_level
- relation_grade

Un proxy analitico non deve mai essere presentato come benchmark ufficiale.

---

## F. LADDER OBBLIGATORIO

Ordine:

0. PROPRIA / EXACT
1. SORELLA
2. CUGINA
3. ZIA
4. NONNA
5. FAMIGLIA AMPIA
6. MERCATO GENERALE

### EXACT

Usare prima:
- official code;
- Bloomberg ticker;
- RIC;
- canonical official name;
- provider code;
- Yahoo `Lookup.get_index()`.

Se exact/near-exact valido: early-stop.

### SORELLA

Stesso universo/asset/geografia/settore/tema/factor/size/duration, rimuovendo solo customizzazioni secondarie:
- ESG screen;
- capped;
- 20/35;
- custom;
- variant net/gross/price;
- eventuale hedging, quando necessario per trovare una serie confrontabile.

### CUGINA

Stessa caratteristica dominante, universo leggermente più ampio.

### ZIA

Mantiene asset e geografia principale, rilassa settore/factor/size.

### NONNA

Broad market della stessa famiglia.

### FAMIGLIA AMPIA / MERCATO GENERALE

Allargare progressivamente senza mai cambiare asset class.

---

## G. DOMAIN LOCK NON COMPENSABILE

Prima della geometry.

Vietato:
- equity → bond;
- commodity → bond;
- gold → bond;
- digital asset → bond;
- cash → equity;
- ecc.

Una buona correlazione non può superare il veto semantico.

---

## H. MULTI-ASSET / FONDI FLESSIBILI

Regola generica, mai FAM-specifica.

1. recuperare asset allocation runtime;
2. yfinance `FundsData` quando disponibile:
   - asset_classes
   - equity_holdings
   - bond_holdings
   - bond_ratings
   - sector_weightings
   - top_holdings
3. integrare con factsheet/emittente;
4. comprimere a massimo 2 gambe;
5. pesi a step 5%;
6. geometry può modificare i pesi solo ±5%;
7. risolvere ogni gamba con lo stesso resolver;
8. costruire curva composita.

Invariante:
`asset_class == MULTI_ASSET => operational_kind == COMPOSITE`

salvo errore infrastrutturale esplicitamente marcato.

FAM-FLEX, FAM-PU6, FAM-PU8 sono solo fixture di regressione.
Mai inserirli in `if`, dizionari o pattern speciali.

FAM-EMD deve testare genericamente il riconoscimento Emerging Markets Debt.

---

## I. BOND/BTP

Mai usare ETF proxy.

Per singole obbligazioni:
- country/issuer;
- sovereign/corporate;
- currency;
- maturity;
- duration;
- inflation link;
- rating/spread se reperibili.

Costruire curve duration-specific con fonti ufficiali (ECB/Banca d'Italia/altre curve pubbliche).

---

## J. MONEY MARKET

Usare il rate coerente con la valuta.
Per EUR: €STR/ECB.
Non usare Treasury ETF USA come proxy.

---

## K. HOLDINGS SYNTHETIC

Solo se:
- asset equity;
- identity conosciuta;
- non è disponibile in tempo un indice coerente;
- il ladder pubblico è stato realmente esaurito.

Costruire una curva dalle holdings runtime.

Deve essere etichettata come sintetica e non precedere un broad index ovvio.

---

## L. BASE100

`BASE100-EMERGENCY` non è un benchmark.

È ammesso solo se:
- fonti indisponibili;
- nessun last-known-good;
- nessun same-domain synthetic possibile.

Etichetta:
`INFRASTRUCTURE_EMERGENCY`

Non includerlo nel normale benchmark score.

---

## M. VELOCITÀ

Target:
- cache hit < 250 ms;
- casi semplici ~1–2 s;
- p95 <= 5 s;
- hard budget <= 8 s/strumento.

Usare:
- parallel I/O;
- OpenFIGI batch;
- connection pooling;
- timeout brevi;
- query dedup;
- early-stop;
- deep metadata solo per casi ambigui/fondi;
- cache.

Alla scadenza del budget:
1. migliore same-domain già trovata;
2. last-known-good;
3. same-domain synthetic;
4. infrastructure emergency.

Mai cross-asset per rispettare il timeout.

---

## N. CACHE

Persistente e generata runtime.

Salvare:
- identity;
- profile;
- C/D/S;
- official benchmark;
- operational series;
- relation;
- components;
- confidence;
- provenance;
- timestamp;
- algorithm_version.

TTL differenziati:
- identity/benchmark: 7–30 giorni;
- market history: giornaliero;
- failure cache: breve.

La cache non deve essere distribuita come knowledge base precaricata.

---

## O. COMPATIBILITÀ CON IL SOFTWARE ESISTENTE

`benchmark_registry.py` resta la facciata centrale.

`resolve_instrument_benchmark()` deve delegare al nuovo servizio.

Mantenere temporaneamente `BenchmarkAssignment`, estendendolo senza rompere i chiamanti.

Il vecchio campo `ticker` deve diventare un alias compatibile verso `operational_series`, che può essere:
- index symbol;
- provider series;
- synthetic ID;
- composite ID;
- rate ID;
- direct underlying.

Non assumere più Yahoo ticker.

---

## P. PROPAGAZIONE OBBLIGATORIA

Individuare e modificare ogni uso di:
- resolve_instrument_benchmark
- BenchmarkAssignment
- BENCHMARK_BY_*
- LEGACY_BENCH
- known_benchmark_catalog
- benchmark_ticker
- benchmark_label
- benchmark_source
- core_pct
- defensive_pct
- satellite_pct

Nessun modulo periferico deve calcolare benchmark o C/D/S autonomamente.

Aggiornare:
- anagrafica/master;
- Quotazioni;
- Cruscotti;
- Summary;
- grafici;
- cache benchmark;
- refresh;
- export/import;
- persistence/database;
- eventuali API interne.

---

## Q. MANUAL OVERRIDE

Gli override utente restano possibili ma separati:

- manual_override
- manual_benchmark_series
- manual_benchmark_label
- manual_reason
- manual_updated_at

Conservare anche la scelta automatica per confronto/audit.

---

## R. TEST E CRITERI DI ACCETTAZIONE

Fixture 111 solo nei test.

Target:
- C/D/S >= 99,4/100;
- benchmark score > 81,3/100 con formula:
  `55% semantic + 35% geometry + 10% coverage`;
- 0 mapping ticker→benchmark;
- 0 mapping ISIN→benchmark;
- 0 static benchmark families;
- 0 benchmark ETF;
- 0 cross-asset fallback;
- 0 NON RISOLTO;
- 0 normale BASE100;
- 100% multi-asset → composito;
- 100% C+D+S=100;
- official identity separata dalla analytical series;
- hard timeout rispettato;
- GUI/summary/cache aggiornati;
- un'unica fonte centrale di verità.

Non considerare completato il lavoro perché ogni strumento ha "qualcosa".
La qualità semantica e quantitativa è parte dei criteri di accettazione.

---

## S. CONSEGNA RICHIESTA DAL PROGRAMMATORE

Alla fine produrre:

1. elenco file modificati/creati;
2. schema architetturale finale;
3. migration note;
4. risultato scanner dipendenze legacy;
5. risultato audit no-static;
6. replay dei 111;
7. score C/D/S;
8. score benchmark;
9. conteggio per relation_grade;
10. conteggio infrastructure emergencies;
11. tempi mean/p50/p95/max;
12. elenco eventuali casi ancora sotto soglia con motivo;
13. prova che Quotazioni/Cruscotti/Summary leggano tutti `InstrumentAnalysis`;
14. test di backward compatibility del `benchmark_registry.py`.

Non introdurre altre eccezioni per correggere i casi falliti.
