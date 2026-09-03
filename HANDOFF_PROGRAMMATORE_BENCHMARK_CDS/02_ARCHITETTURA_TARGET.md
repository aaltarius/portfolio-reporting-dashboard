# ARCHITETTURA TARGET

```text
                         ┌───────────────────────┐
ticker / ISIN ──────────►│ InstrumentAnalysis   │
                         │ Service               │
                         └──────────┬────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
              ▼                     ▼                     ▼
      IdentityResolver       ProfileClassifier      MarketData
              │                     │                     │
    Borsa Italiana           C/D/S engine           historical
    OpenFIGI                 (independent           series / FX /
    Yahoo                    from benchmark)        rates
    issuer/factsheet               │
    index provider                 │
              │                    │
              └─────────────┬──────┘
                            ▼
                    BenchmarkResolver
                            │
            exact → sister → cousin → aunt
            → grandmother → broad family
            → general market → same-domain synthetic
                            │
                 ┌──────────┴───────────┐
                 ▼                      ▼
          single-series            multi-asset
          benchmark                composite
                                   max 2 legs
                            │
                            ▼
                    InstrumentAnalysis
                            │
              ┌─────────────┼──────────────┐
              ▼             ▼              ▼
 benchmark_registry     Quotazioni      Cruscotti
 compatibility facade  /refresh         /Summary/GUI
              │
              └──────────► persistence/cache
```

## Moduli consigliati

### `core/instrument_analysis/contracts.py`
Dataclass/enums del risultato canonico.

### `core/instrument_analysis/service.py`
Orchestratore.

### `core/instrument_analysis/reference_data/`
Adapter:
- borsa_italiana.py
- openfigi.py
- yahoo.py
- issuer.py
- index_provider.py

### `core/instrument_analysis/profile.py`
Normalizzazione semantica e profilo.

### `core/instrument_analysis/cds.py`
C/D/S validato.

### `core/instrument_analysis/benchmark.py`
Identity + operational series + ladder.

### `core/instrument_analysis/composite.py`
Multi-asset, max 2 gambe, step 5%.

### `core/instrument_analysis/series.py`
Storici, FX, rates, normalizzazione.

### `core/instrument_analysis/cache.py`
Cache runtime/last-known-good.

### `core/instrument_analysis/metrics.py`
Semantic, geometry, tracking, beta, TE, coverage.

### `benchmark_registry.py`
Solo facade backward-compatible.

## Dipendenza fondamentale

Il dependency graph deve essere unidirezionale:

UI / Summary / Quotazioni
→ facade/service
→ core

Mai:

UI → regole benchmark locali

o:

benchmark fallback → modifica C/D/S
