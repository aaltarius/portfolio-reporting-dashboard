# PROPAGAZIONE A TUTTO IL SOFTWARE

## Regola

Ogni componente che oggi legge o calcola benchmark/C-D-S deve passare al risultato canonico `InstrumentAnalysis`.

## Mappa di migrazione

### Anagrafica / master strumenti

Persistenza nuova:
- analysis_algorithm_version
- analysis_resolved_at
- structural_type
- asset_class
- geography / geo_scope
- sector / theme / factor / size
- duration / maturity
- asset_mix
- core_pct / defensive_pct / satellite_pct
- cds_confidence / cds_reliability
- official_benchmark_name/code/provider/source
- operational_series/provider/kind
- resolution_level / relation_grade
- benchmark_confidence
- semantic / geometry / selection scores
- components
- warnings / errors / provenance

Non sovrascrivere manual override.

### Quotazioni

Il refresh non deve più assumere che `benchmark_ticker` sia sempre scaricabile da Yahoo.

Implementare dispatcher per:
- YAHOO_INDEX
- PROVIDER_INDEX
- SYNTHETIC_BOND
- SOVEREIGN_CURVE
- RATE
- COMPOSITE
- HOLDINGS_SYNTHETIC
- DIRECT_UNDERLYING
- INFRASTRUCTURE_EMERGENCY

### Cache benchmark

Separare:
- resolution cache;
- historical series cache.

Il refresh giornaliero storico non deve rifare la discovery se il resolver è ancora valido.

### Cruscotti

Mostrare distintamente:
- Benchmark ufficiale
- Curva di confronto
- Parentela
- Confidence
- Reliability
- Metriche

### Grafici

Conservare base 100.
Per COMPOSITE mostrare:
- componenti
- pesi

### Summary

Niente inferenze locali.
Leggere:
- C/D/S
- benchmark identity
- operational series
- metrics
direttamente da `InstrumentAnalysis`.

### Export/import

Versionare schema.
Non perdere componenti/provenance/relation.

### UI di modifica benchmark

L'autocomplete può leggere solo:
- cache runtime dei benchmark scoperti;
- manual values già usati.

Non usare un catalogo statico come sorgente automatica.

## Query di inventario

Eseguire:

```bash
rg -n "resolve_instrument_benchmark|BenchmarkAssignment|BENCHMARK_BY_|LEGACY_BENCH|known_benchmark_catalog|benchmark_ticker|benchmark_label|benchmark_source|core_pct|defensive_pct|satellite_pct" .
```

Oppure usare `tools/inventory_legacy_usage.py`.
