# HANDOFF AL PROGRAMMATORE — Benchmark + C/D/S

## Obiettivo

Integrare nel software reale una sola pipeline centrale che, partendo da **ticker/ISIN**, produca:

- identità dello strumento;
- profilo finanziario;
- C/D/S;
- benchmark ufficiale;
- serie operativa di confronto;
- grado di parentela/fallback;
- composizione per i multi-asset;
- metriche quantitative;
- confidence/provenance;
- cache e timestamp/versione.

Il vecchio `benchmark_registry.py` **non va ampliato con altri casi**: va trasformato da catalogo statico a **compatibility facade** verso il nuovo servizio centrale.

## Ordine di lettura

1. `01_PROMPT_IMPLEMENTAZIONE.md`
2. `02_ARCHITETTURA_TARGET.md`
3. `03_PROPAGAZIONE_SOFTWARE.md`
4. `04_TEST_E_CRITERI_ACCETTAZIONE.md`
5. `05_PIANO_MIGRAZIONE.md`
6. `code/contracts_instrument_analysis.py`
7. `code/benchmark_registry_TARGET.py`
8. `tools/inventory_legacy_usage.py`
9. `tools/audit_no_static_benchmarks.py`

## File di riferimento

`fixtures/known_instruments.json`
- universo di regressione: 111 strumenti;
- deve essere usato **solo nei test**;
- non deve mai essere importato dal resolver di produzione.

`fixtures/cds_regression_baseline_111.json`
- baseline C/D/S validata;
- deve essere usata **solo nei test**.

`reference/poc17_2_engine_CDS_BASELINE_REFERENCE.py`
- riferimento per la logica C/D/S che aveva raggiunto ~99,4/100.

`reference/poc17_4_engine_VALIDATED_REFERENCE.py`
- riferimento architetturale/metriche/semantic guard/curve;
- non deve diventare una fonte di mapping per singolo strumento.

`reference/poc17_online_first_REFERENCE_ONLY.py`
- prototipo utile per adapter online, budget temporale, Borsa/OpenFIGI/yfinance;
- **NON è production-ready**: il replay ha mostrato ancora troppi `BASE100-EMERGENCY` e fallback sintetici prematuri.
- usarlo come sorgente di idee/adapters, NON copiarne ciecamente il resolver finale.

## Vincoli non negoziabili

- nessun mapping ticker → benchmark;
- nessun mapping ISIN → benchmark;
- nessuna lista benchmark/preloaded family nel resolver;
- benchmark mai ETF/fondo;
- C/D/S indipendente dal fallback benchmark;
- cross-asset vietato;
- multi-asset → benchmark composito;
- sempre una curva;
- `BASE100` solo errore infrastrutturale estremo;
- ricerca online con budget massimo, cache, early-stop;
- unico risultato centrale propagato a tutto il software.

## Primo comando da eseguire nel repository reale

```bash
python tools/inventory_legacy_usage.py /percorso/del/repository
```

Poi, dopo la migrazione:

```bash
python tools/audit_no_static_benchmarks.py /percorso/del/repository
```
