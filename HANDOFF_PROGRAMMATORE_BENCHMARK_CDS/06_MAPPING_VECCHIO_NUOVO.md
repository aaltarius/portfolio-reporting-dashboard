# DAL VECCHIO `benchmark_registry.py` AL NUOVO SISTEMA

| Vecchio elemento | Destino |
|---|---|
| `BENCHMARK_BY_TICKER` | ELIMINARE |
| `BENCHMARK_BY_ISIN` | ELIMINARE |
| `BENCHMARK_BY_TYPE` | ELIMINARE come sorgente benchmark |
| `BENCHMARK_BY_MACRO` | ELIMINARE come sorgente benchmark |
| `BENCHMARK_BY_INDEX_PATTERN` | SOSTITUIRE con parsing + runtime provider/index search |
| `LEGACY_BENCH` | ELIMINARE dopo migration |
| `_macro_from_type()` | può restare solo come classificazione generica, non benchmark |
| `resolve_instrument_benchmark()` | MANTENERE come facade |
| `known_benchmark_catalog()` | trasformare in cache/discovered autocomplete |
| manual override | MANTENERE e separare |
| `BenchmarkAssignment` | MANTENERE temporaneamente, ampliare |

## Esempio

Vecchio:

```python
if tk in BENCHMARK_BY_TICKER:
    return BENCHMARK_BY_TICKER[tk]
```

Nuovo:

```python
analysis = instrument_analysis_service.analyze(ticker=tk, isin=isincode)
return compatibility_assignment(analysis.benchmark)
```

Il resolver centrale è l'unica parte autorizzata a:
- interrogare fonti;
- costruire profilo;
- assegnare C/D/S;
- trovare benchmark;
- scegliere fallback;
- calcolare confidence/metrics.
