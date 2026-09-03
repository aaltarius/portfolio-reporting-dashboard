# -*- coding: utf-8 -*-
"""
Compares FINAL replay C/D/S with the frozen POC17.2 baseline.
TEST ONLY: the resolver never imports or reads this baseline.
"""
from pathlib import Path
import json, sys

ROOT = Path(__file__).resolve().parent

def key(r):
    return (r.get("ticker") or "").upper() or (r.get("isin") or "").upper()

def main():
    if len(sys.argv) != 2:
        print("Uso: python audit_cds_vs_17_2.py output_final.json")
        return 2
    base = json.loads((ROOT/"cds_regression_baseline_111.json").read_text(encoding="utf-8"))
    out = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    brow = base.get("results", base if isinstance(base,list) else [])
    orow = out.get("results", [])
    bm = {key(r):r for r in brow}
    om = {key(r):r for r in orow}
    exact = 0
    abs_err = 0.0
    n = 0
    diffs = []
    for k,b in bm.items():
        o = om.get(k)
        if not o: continue
        bv = [float(b.get(x,0)) for x in ("core_pct","defensive_pct","satellite_pct")]
        ov = [float(o.get(x,0)) for x in ("core_pct","defensive_pct","satellite_pct")]
        err = sum(abs(a-c) for a,c in zip(bv,ov))/2.0
        abs_err += err
        n += 1
        if err < .01: exact += 1
        else: diffs.append((err,k,bv,ov))
    score = max(0.0, 100.0 - abs_err/max(1,n))
    print(f"Confrontati: {n}")
    print(f"Identici: {exact}/{n}")
    print(f"C/D/S score vs frozen 17.2: {score:.2f}/100")
    for err,k,bv,ov in sorted(diffs, reverse=True)[:20]:
        print(f"- {k}: baseline={bv}, final={ov}, distanza={err:.1f}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
