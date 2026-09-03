# -*- coding: utf-8 -*-
"""Deterministic, network-free blocking tests for POC17.4."""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pandas as pd

from poc17_4_engine import Benchmark, Evidence, Profile, apply_17_4_semantic_guard

ROOT=Path(__file__).resolve().parent
BASE_ENGINE=ROOT / "poc17_2_engine.py"
NEW_ENGINE=ROOT / "poc17_4_engine.py"


def _function_hash(path,names):
    tree=ast.parse(path.read_text(encoding="utf-8"))
    rows=[]
    for node in tree.body:
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in names:
            rows.append((node.name,ast.dump(node,include_attributes=False)))
    assert {x[0] for x in rows}==set(names), "C/D/S function set incomplete"
    payload="\n".join(v for _,v in sorted(rows)).encode()
    return hashlib.sha256(payload).hexdigest()


def _curve():
    return pd.Series([100.0,101.0,102.0],index=pd.date_range("2026-01-01",periods=3))


def _benchmark(symbol,name="Broad index",level="INDEX_CLASS_REFERENCE",variant="GLOBAL_PARENT"):
    return Benchmark(level=level,provider="YFINANCE",official_name=name,
                     operational_symbol=symbol,provider_id=symbol,variant=variant,
                     confidence=.80,semantic_confidence=.75,series=_curve())


def test_cds_source_is_frozen():
    # These are the complete structural/C-D-S entry points changed between
    # releases 15-17 and deliberately frozen in 17.2.
    names={"profile","exposure_fingerprint","role","structural_type","_quantize_effective"}
    assert _function_hash(BASE_ENGINE,names)==_function_hash(NEW_ENGINE,names)


def test_exact_is_locked():
    e=Evidence(benchmark_name="MSCI World")
    p=Profile(asset="equity",geography="world",geo_scope="global",breadth="broad")
    b=_benchmark("^990100-USD-STRD","MSCI World","EXACT_ALTERNATIVE_INDEX","")
    out=apply_17_4_semantic_guard(e,p,b)
    assert out.level=="EXACT_ALTERNATIVE_INDEX"
    assert out.semantic_guard_status=="LOCKED_EXACT"


def test_emerging_single_country_is_proxy_only():
    e=Evidence(benchmark_name="MSCI Emerging Markets")
    p=Profile(asset="equity",geography="emerging",geo_scope="regional",breadth="broad")
    out=apply_17_4_semantic_guard(e,p,_benchmark("000001.SS","Reference: Emerging Equity","INDEX_CLASS_REFERENCE","EM_PARENT"))
    assert out.level=="OFFICIAL_IDENTITY_WITH_ANALYTICAL_PROXY"
    assert out.official_name=="MSCI Emerging Markets"
    assert out.analytical_series_name=="Reference: Emerging Equity"
    assert out.series_relation=="ANALYTICAL_PROXY_ONLY"


def test_europe_cannot_become_us_benchmark():
    e=Evidence(benchmark_name="STOXX Europe 600")
    p=Profile(asset="equity",geography="europe",geo_scope="regional",breadth="broad")
    out=apply_17_4_semantic_guard(e,p,_benchmark("^GSPC","S&P 500"))
    assert out.semantic_guard_status=="PROXY_ONLY"
    assert out.official_name=="STOXX Europe 600"


def test_theme_cannot_be_erased_by_nasdaq_or_sp500():
    e=Evidence(name="Global Water UCITS ETF",benchmark_name="S&P Global Water Index")
    p=Profile(asset="equity",geography="world",geo_scope="global",theme="water")
    for symbol,name in (("^GSPC","S&P 500"),("^IXIC","Nasdaq Composite")):
        out=apply_17_4_semantic_guard(e,p,_benchmark(symbol,name))
        assert out.semantic_guard_status=="PROXY_ONLY"
        assert out.official_name=="S&P Global Water Index"


def test_compatible_theme_survives():
    e=Evidence(name="Artificial Intelligence UCITS ETF",benchmark_name="Nasdaq Global AI")
    p=Profile(asset="equity",geography="world",geo_scope="global",theme="artificial_intelligence")
    out=apply_17_4_semantic_guard(e,p,_benchmark("DE000SLA98X0.SG","Solactive Global Artificial Intelligence Index NTR","TIERED_INDEX_REFERENCE","THEME"))
    assert out.semantic_guard_status=="PASS"
    assert out.official_name=="Solactive Global Artificial Intelligence Index NTR"


if __name__=="__main__":
    tests=[v for k,v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print("PASS",test.__name__)
    print("ALL POC17.4 FROM-17.2 BLOCKING INVARIANTS PASSED")
