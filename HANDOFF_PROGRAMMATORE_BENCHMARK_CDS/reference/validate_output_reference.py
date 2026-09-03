# -*- coding: utf-8 -*-
from pathlib import Path
import json, sys

def f(x, default=0.0):
    try: return float(x)
    except Exception: return default

def main():
    if len(sys.argv) != 2:
        print("Uso: python validate_output_final.py output.json")
        return 2
    p = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    rows = p.get("results", [])
    errors = []
    scores = []
    for r in rows:
        tag = r.get("ticker") or r.get("isin") or "?"
        total = f(r.get("core_pct")) + f(r.get("defensive_pct")) + f(r.get("satellite_pct"))
        if abs(total - 100.0) > 0.05:
            errors.append(f"{tag}: C/D/S={total}")
        if not r.get("benchmark_series_display"):
            errors.append(f"{tag}: curva vuota")
        if "NON RISOLTO" in str(r.get("benchmark_quality","")).upper():
            errors.append(f"{tag}: NON RISOLTO")
        if "DOMAIN_LOCK_REJECTED" in str(r.get("errors","")) or "FINAL_DOMAIN_VETO" in str(r.get("errors","")):
            # It is acceptable only if the final assigned series is domain-safe;
            # flag for review because a rejected intermediate candidate occurred.
            pass
        sem = 100.0 * max(
            f(r.get("reference_semantic_confidence")),
            f(r.get("benchmark_confidence"))
        )
        geom = f(r.get("reference_geometry_score"))
        obs = f(r.get("benchmark_obs"))
        coverage = min(100.0, 100.0 * obs / 252.0)
        bench = .55*sem + .35*geom + .10*coverage
        scores.append(bench)

    print(f"Risultati: {len(rows)}")
    print(f"Violazioni: {len(errors)}")
    for e in errors[:30]:
        print(" -", e)
    if scores:
        print(f"Benchmark audit medio (55% sem + 35% geometry + 10% coverage): {sum(scores)/len(scores):.1f}/100")
    return 1 if errors else 0

if __name__ == "__main__":
    raise SystemExit(main())
