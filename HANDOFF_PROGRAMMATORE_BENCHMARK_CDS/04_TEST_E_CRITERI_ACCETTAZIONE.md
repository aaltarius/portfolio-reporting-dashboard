# TEST E CRITERI DI ACCETTAZIONE

## 1. Static audit

Deve fallire se nel codice di produzione ricompaiono:
- `BENCHMARK_BY_TICKER`
- `BENCHMARK_BY_ISIN`
- `BENCHMARK_BY_TYPE`
- `BENCHMARK_BY_MACRO`
- `BENCHMARK_BY_INDEX_PATTERN`
- `LEGACY_BENCH`
- equivalente catalogo statico.

Comando:

```bash
python tools/audit_no_static_benchmarks.py /repo
```

## 2. Regression fixture

Usare:
- `fixtures/known_instruments.json`
- `fixtures/cds_regression_baseline_111.json`

Questi file NON devono essere importabili dal codice di produzione.

## 3. C/D/S

Formula consigliata di distanza per strumento:

```text
distance = (|C-C0| + |D-D0| + |S-S0|) / 2
score = 100 - mean(distance)
```

Target:
`>= 99,4/100`.

## 4. Benchmark

Score omogeneo:

```text
benchmark_score =
    0.55 * semantic_score
  + 0.35 * geometry_score
  + 0.10 * coverage_score
```

Target:
`> 81,3/100`.

## 5. Invarianti bloccanti

- C+D+S = 100
- fallback benchmark non cambia C/D/S
- ETF/fund mai benchmark
- domain lock prima della geometry
- known multi-asset → composite
- official != analytical proxy quando non exact
- sempre una curva
- no `NON RISOLTO`
- Base100 non è un normale benchmark
- hard timeout rispettato
- no production dependency verso `tests/fixtures`

## 6. Casi di regressione importanti

Non creare regole speciali per questi nomi; sono solo test:
- SWDA: broad world equity
- XDWT: world technology
- XMME: emerging broad equity
- XDBC: commodity
- XAIX: thematic AI
- XEON: EUR money market
- EM13: short gov bond
- BTP con solo ISIN: sovereign duration-specific
- FAM-EMD: emerging debt
- FAM-FLEX: multi-asset
- FAM-PU6: multi-asset
- FAM-PU8: multi-asset

## 7. Performance

Registrare:
- mean
- p50
- p95
- max
- cache hit ratio
- source hit ratio

Target:
- cache hit < 250 ms
- p95 <= 5 s
- hard cap <= 8 s

## 8. Report finale obbligatorio

Tabella:
ticker/isin | structural_type | C/D/S | official benchmark | operational series | relation | semantic | geometry | score | ms

Aggregati:
- C/D/S score
- benchmark score
- relation distribution
- exact count
- composite count
- same-domain synthetic count
- infrastructure emergency count
- time p50/p95/max
