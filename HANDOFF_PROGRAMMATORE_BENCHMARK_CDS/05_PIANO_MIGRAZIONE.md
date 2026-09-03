# PIANO DI MIGRAZIONE

## Step 0 — branch e baseline

Creare branch dedicato.
Eseguire test attuali e salvare output.

## Step 1 — inventario

```bash
python tools/inventory_legacy_usage.py /repo > legacy_inventory.txt
```

Classificare ogni hit:
- resolver
- UI
- persistence
- quotations
- cache
- summary
- tests

## Step 2 — contratti

Integrare `code/contracts_instrument_analysis.py`
nel package reale.

Nessuna UI deve dipendere dai dettagli degli adapter.

## Step 3 — service

Creare `InstrumentAnalysisService`.

Prima implementare:
- identity
- profile
- C/D/S
- benchmark identity
- cache

Poi operational series.

## Step 4 — facade

Sostituire `benchmark_registry.py` con una facade equivalente a
`code/benchmark_registry_TARGET.py`.

Conservare firme pubbliche necessarie per una migrazione graduale.

## Step 5 — propagation

Aggiornare uno per uno:
1. master/anagrafica
2. quotations
3. benchmark refresh
4. summary
5. dashboard
6. charts
7. persistence/export

Ogni modulo deve leggere lo stesso `InstrumentAnalysis`.

## Step 6 — rimozione legacy

Eliminare i cataloghi statici.
Rilanciare audit.

## Step 7 — replay 111

Produrre:
- JSON completo
- report scores
- timing report
- failure/provenance report

## Step 8 — gate

Non merge finché:
- C/D/S >= 99,4
- benchmark > 81,3
- invarianti tutti PASS
- no legacy static mappings
- p95 entro budget

## Step 9 — rollout

Persistenza con `algorithm_version`.
Le vecchie risoluzioni possono essere invalidate progressivamente.

## Step 10 — monitoraggio

Aggiungere telemetria locale/log:
- cache hit/miss
- source success
- relation selected
- fallback reason
- timing
- low confidence cases
