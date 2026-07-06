"""Servizi read-only per la trasparenza del benchmark di portafoglio.

Il modulo non modifica dati, cache o impostazioni: rende esplicita la logica
benchmark gia' usata dall'applicativo e produce payload pronti per Cruscotti e
Impostazioni.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from persistence.storage import macro_cat
from core.benchmark_registry import resolve_instrument_benchmark as _central_resolve_instrument_benchmark
from core.domain.positions import held_tickers

BENCHMARK_TICKER_FALLBACKS = {"BTI.MI": "EMB"}
CUSTOM_BENCHMARK_COMPONENT_OPTIONS = {
    "MSCI World / IWDA": "IWDA.AS",
    "Bond proxy / EMB": "EMB",
    "Commodity proxy / DJP": "DJP",
    "Oro proxy / SGLD": "SGLD.MI",
    "Nasdaq / QQQ": "QQQ",
}

# Fallback per macro-categoria usati quando l'anagrafica strumento non ha
# un benchmark puntuale ma altre aree dell'applicativo mostrano comunque un
# riferimento concettuale (es. GOV -> Bond Index in Quotazioni).
# Non rende il proxy perfetto: lo rende esplicito e calcolabile quando la
# relativa serie e' presente in cache.
INSTRUMENT_BENCHMARK_CATEGORY_FALLBACKS = {
    "GOV": {"ticker": "BND", "label": "Bond Index", "source": "macro categoria"},
    "BOND": {"ticker": "BND", "label": "Bond Index", "source": "macro categoria"},
    "OBB": {"ticker": "BND", "label": "Bond Index", "source": "macro categoria"},
}

INSTRUMENT_BENCHMARK_TYPE_FALLBACKS = {
    "gov": {"ticker": "BND", "label": "Bond Index", "source": "tipo sintetico"},
    "titolo governativo": {"ticker": "BND", "label": "Bond Index", "source": "tipo sintetico"},
    "titolo di stato": {"ticker": "BND", "label": "Bond Index", "source": "tipo sintetico"},
    "btp": {"ticker": "BND", "label": "Bond Index", "source": "tipo sintetico"},
}


def get_effective_portfolio_benchmark_label(settings: dict[str, Any] | None) -> str:
    if not isinstance(settings, dict):
        return "Blend automatico"
    benchmarking = settings.get("benchmarking", {}) if isinstance(settings.get("benchmarking", {}), dict) else {}
    raw_components = benchmarking.get("custom_components", [])
    valid_custom = bool(benchmarking.get("custom_enabled", False)) and isinstance(raw_components, list) and any(
        isinstance(item, dict) and str(item.get("ticker", "")).strip() and _safe_float(item.get("weight"), 0.0) > 0
        for item in raw_components
    )
    if valid_custom:
        return str(benchmarking.get("custom_name") or "Benchmark personalizzato")
    return str(settings.get("portfolio_benchmark_default") or benchmarking.get("default_portfolio_benchmark") or "Blend automatico")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _percent(value: Any) -> float:
    return _safe_float(value, 0.0)


def _normalize_components(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Accorpa ticker duplicati e normalizza i pesi a 1."""
    by_ticker: dict[str, dict[str, Any]] = {}
    for item in components:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "").strip()
        if not ticker:
            continue
        ticker = BENCHMARK_TICKER_FALLBACKS.get(ticker, ticker)
        label = str(item.get("label") or ticker).strip() or ticker
        w = _safe_float(item.get("weight"), 0.0)
        if w <= 0:
            continue
        if ticker not in by_ticker:
            by_ticker[ticker] = {"ticker": ticker, "label": label, "weight": 0.0}
        by_ticker[ticker]["weight"] += w
    total = sum(float(v.get("weight", 0.0)) for v in by_ticker.values())
    if total <= 0:
        return []
    out = []
    for item in sorted(by_ticker.values(), key=lambda x: str(x.get("label") or x.get("ticker"))):
        out.append({
            "ticker": str(item["ticker"]),
            "label": str(item.get("label") or item["ticker"]),
            "weight": float(item["weight"]) / total,
        })
    return out


def resolve_effective_benchmark_components(
    settings: dict[str, Any] | None,
    da_frame: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Restituisce label, componenti e descrizione del benchmark effettivo.

    Replica in forma dichiarativa la logica usata da build_portfolio_benchmark_series.
    """
    settings = settings if isinstance(settings, dict) else {}
    benchmarking = settings.get("benchmarking", {}) if isinstance(settings.get("benchmarking", {}), dict) else {}
    label = get_effective_portfolio_benchmark_label(settings)

    components: list[dict[str, Any]] = []
    custom_enabled = bool(benchmarking.get("custom_enabled", False))
    raw_custom = benchmarking.get("custom_components", [])
    if custom_enabled and isinstance(raw_custom, list):
        for item in raw_custom:
            if not isinstance(item, dict):
                continue
            ticker = str(item.get("ticker") or "").strip()
            weight = _safe_float(item.get("weight"), 0.0)
            if ticker and weight > 0:
                component_label = next(
                    (name for name, mapped_ticker in CUSTOM_BENCHMARK_COMPONENT_OPTIONS.items() if mapped_ticker == ticker),
                    ticker,
                )
                components.append({"ticker": ticker, "label": component_label, "weight": weight})
        components = _normalize_components(components)
        if components:
            return {
                "label": label,
                "mode": "personalizzato",
                "components": components,
                "method_note": "Benchmark personalizzato: componenti e pesi sono quelli definiti nelle impostazioni; i pesi vengono normalizzati automaticamente.",
            }

    if label == "60/40 MSCI World / Bond":
        components = [
            {"ticker": "IWDA.AS", "label": "MSCI World / IWDA", "weight": 0.60},
            {"ticker": "EMB", "label": "Bond proxy / EMB", "weight": 0.40},
        ]
        mode = "predefinito"
        note = "Benchmark predefinito 60/40: 60% azionario globale e 40% proxy obbligazionario."
    elif label == "100% MSCI World":
        components = [{"ticker": "IWDA.AS", "label": "MSCI World / IWDA", "weight": 1.0}]
        mode = "predefinito"
        note = "Benchmark predefinito 100% azionario globale."
    elif label == "100% GOV":
        ticker = BENCHMARK_TICKER_FALLBACKS.get("BTI.MI", "EMB")
        components = [{"ticker": ticker, "label": "Bond/GOV proxy", "weight": 1.0}]
        mode = "predefinito"
        note = "Benchmark predefinito obbligazionario/GOV basato sul proxy disponibile in cache."
    else:
        # Blend automatico: stessa semplificazione usata dal motore esistente.
        total = 0.0
        gov_value = 0.0
        if da_frame is not None and not da_frame.empty and "Controvalore" in da_frame.columns:
            total = float(pd.to_numeric(da_frame["Controvalore"], errors="coerce").fillna(0.0).sum())
            type_col = "Tipo" if "Tipo" in da_frame.columns else "Tipologia" if "Tipologia" in da_frame.columns else None
            if type_col:
                mask = da_frame[type_col].apply(macro_cat) == "GOV"
                gov_value = float(pd.to_numeric(da_frame.loc[mask, "Controvalore"], errors="coerce").fillna(0.0).sum())
        gov_w = gov_value / total if total > 0 else 0.0
        other_w = max(0.0, 1.0 - gov_w) if total > 0 else 1.0
        components = []
        if gov_w > 0.001:
            components.append({"ticker": "EMB", "label": "Bond/GOV proxy", "weight": gov_w})
        if other_w > 0.001:
            components.append({"ticker": "IWDA.AS", "label": "MSCI World / IWDA", "weight": other_w})
        components = _normalize_components(components)
        mode = "blend automatico"
        note = "Blend automatico: la quota GOV del portafoglio viene attribuita a un proxy obbligazionario; la restante parte viene attribuita a MSCI World. È un riferimento sintetico, non una replica puntuale di tutte le asset class."

    return {"label": label, "mode": mode, "components": components, "method_note": note}


def _history_frame(records: Any, value_col: str = "indice") -> pd.DataFrame:
    if not isinstance(records, list) or not records:
        return pd.DataFrame(columns=["date", value_col])
    df = pd.DataFrame(records)
    if "data" not in df.columns or value_col not in df.columns:
        return pd.DataFrame(columns=["date", value_col])
    df["date"] = pd.to_datetime(df["data"], dayfirst=True, errors="coerce")
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
    return df.dropna(subset=["date", value_col]).sort_values("date")[["date", value_col]].reset_index(drop=True)


def _series_return(df: pd.DataFrame, col: str = "indice") -> float | None:
    if df is None or df.empty or col not in df.columns or len(df) < 2:
        return None
    vals = pd.to_numeric(df[col], errors="coerce").dropna()
    if len(vals) < 2 or float(vals.iloc[0]) == 0:
        return None
    return float(vals.iloc[-1] / vals.iloc[0] - 1.0)


def _series_cagr(df: pd.DataFrame, col: str = "indice") -> float | None:
    ret = _series_return(df, col)
    if ret is None or ret <= -1 or df is None or df.empty or len(df) < 2:
        return None
    days = max(int((pd.to_datetime(df["date"].iloc[-1]) - pd.to_datetime(df["date"].iloc[0])).days), 1)
    return float((1.0 + ret) ** (365.25 / days) - 1.0)


def _series_max_drawdown(df: pd.DataFrame, col: str = "indice") -> float | None:
    if df is None or df.empty or col not in df.columns or len(df) < 2:
        return None
    vals = pd.to_numeric(df[col], errors="coerce").dropna()
    if len(vals) < 2:
        return None
    running = vals.cummax()
    dd = vals / running - 1.0
    return float(dd.min())


def _component_cache_state(data: dict[str, Any] | None, ticker: str) -> dict[str, Any]:
    benchmark_data = data.get("benchmark_data", {}) if isinstance(data, dict) else {}
    raw = benchmark_data.get(f"bench_{ticker}", {}) if isinstance(benchmark_data, dict) else {}
    points = len(raw) if isinstance(raw, dict) else 0
    last_date = max(raw.keys(), default="") if isinstance(raw, dict) else ""
    first_date = min(raw.keys(), default="") if isinstance(raw, dict) else ""
    return {"points": points, "first_date": first_date, "last_date": last_date, "source": "cache" if points else "assente"}




def _date_price_mapping_to_frame(mapping: Any, value_col: str = "price") -> pd.DataFrame:
    """Converte un mapping data->prezzo in serie ordinata e pulita."""
    if not isinstance(mapping, dict) or not mapping:
        return pd.DataFrame(columns=["date", value_col])
    rows = []
    for date_raw, value in mapping.items():
        dt = pd.to_datetime(date_raw, errors="coerce")
        val = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
        if pd.notna(dt) and pd.notna(val) and float(val) > 0:
            rows.append({"date": dt, value_col: float(val)})
    if not rows:
        return pd.DataFrame(columns=["date", value_col])
    return pd.DataFrame(rows).sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)


def _instrument_price_history(data: dict[str, Any] | None, ticker: str) -> pd.DataFrame:
    storico = data.get("storico_prezzi", {}) if isinstance(data, dict) else {}
    if not isinstance(storico, dict) or not ticker:
        return pd.DataFrame(columns=["date", "strumento"])
    rows = []
    for date_raw, by_ticker in storico.items():
        if not isinstance(by_ticker, dict) or ticker not in by_ticker:
            continue
        dt = pd.to_datetime(date_raw, errors="coerce")
        val = pd.to_numeric(pd.Series([by_ticker.get(ticker)]), errors="coerce").iloc[0]
        if pd.notna(dt) and pd.notna(val) and float(val) > 0:
            rows.append({"date": dt, "strumento": float(val)})
    if not rows:
        return pd.DataFrame(columns=["date", "strumento"])
    return pd.DataFrame(rows).sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)


def _benchmark_price_history(data: dict[str, Any] | None, bench_ticker: str) -> pd.DataFrame:
    benchmark_data = data.get("benchmark_data", {}) if isinstance(data, dict) else {}
    raw = benchmark_data.get(f"bench_{bench_ticker}", {}) if isinstance(benchmark_data, dict) else {}
    return _date_price_mapping_to_frame(raw, "benchmark")


def _align_instrument_benchmark(inst: pd.DataFrame, bench: pd.DataFrame) -> pd.DataFrame:
    if inst is None or inst.empty or bench is None or bench.empty:
        return pd.DataFrame(columns=["date", "strumento", "benchmark"])
    left = inst.copy()
    right = bench.copy()
    left["date"] = pd.to_datetime(left["date"], errors="coerce")
    right["date"] = pd.to_datetime(right["date"], errors="coerce")
    left = left.dropna(subset=["date", "strumento"]).set_index("date").sort_index()
    right = right.dropna(subset=["date", "benchmark"]).set_index("date").sort_index()
    if left.empty or right.empty:
        return pd.DataFrame(columns=["date", "strumento", "benchmark"])
    # Outer + ffill permette di confrontare serie con calendari leggermente diversi,
    # ma il perimetro viene poi ristretto ai giorni in cui entrambe le serie sono valorizzate.
    aligned = pd.concat([left, right], axis=1).sort_index().ffill().dropna(subset=["strumento", "benchmark"])
    if aligned.empty:
        return pd.DataFrame(columns=["date", "strumento", "benchmark"])
    return aligned.reset_index()


def _return_from_aligned(aligned: pd.DataFrame, col: str) -> float | None:
    if aligned is None or aligned.empty or col not in aligned.columns or len(aligned) < 2:
        return None
    vals = pd.to_numeric(aligned[col], errors="coerce").dropna()
    if len(vals) < 2 or float(vals.iloc[0]) == 0:
        return None
    return float(vals.iloc[-1] / vals.iloc[0] - 1.0)


def _aligned_return_metrics(aligned: pd.DataFrame) -> dict[str, Any]:
    if aligned is None or aligned.empty or len(aligned) < 2:
        return {
            "instrument_return": None,
            "benchmark_return": None,
            "extra_return": None,
            "correlation": None,
            "tracking_error": None,
            "points": int(len(aligned)) if aligned is not None else 0,
            "start": "",
            "end": "",
        }
    out = {
        "instrument_return": _return_from_aligned(aligned, "strumento"),
        "benchmark_return": _return_from_aligned(aligned, "benchmark"),
        "extra_return": None,
        "correlation": None,
        "tracking_error": None,
        "points": int(len(aligned)),
        "start": pd.to_datetime(aligned["date"].iloc[0]).date().isoformat(),
        "end": pd.to_datetime(aligned["date"].iloc[-1]).date().isoformat(),
    }
    if out["instrument_return"] is not None and out["benchmark_return"] is not None:
        out["extra_return"] = float(out["instrument_return"] - out["benchmark_return"])
    returns = aligned[["strumento", "benchmark"]].pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    if len(returns) >= 10:
        corr = returns["strumento"].corr(returns["benchmark"])
        if pd.notna(corr):
            out["correlation"] = float(corr)
        diff = returns["strumento"] - returns["benchmark"]
        te = diff.std(ddof=1)
        if pd.notna(te):
            out["tracking_error"] = float(te * np.sqrt(252.0))
    return out


def _resolve_instrument_benchmark(
    *,
    raw_type: str,
    category: str,
    master_entry: dict[str, Any] | None = None,
    instrument: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Wrapper locale sul registro centrale benchmark strumenti."""
    assignment = _central_resolve_instrument_benchmark(
        instrument if isinstance(instrument, dict) else {},
        raw_type=raw_type,
        category=category,
        master_entry=master_entry,
        prefer_master=True,
    )
    return assignment.as_dict()

def _benchmark_source(raw_type: str, bench_ticker: str | None, source_hint: str | None = None) -> str:
    if source_hint:
        return str(source_hint)
    if not bench_ticker:
        return "assente"
    return "registro centrale"

def _compatibility_score(raw_type: str, bench_ticker: str | None, correlation: Any, points: int) -> float | None:
    if not bench_ticker:
        return None
    mapping_confidence = 0.25 if bench_ticker else 0.0
    if correlation is None or pd.isna(correlation):
        data_confidence = 0.25 if int(points or 0) >= 20 else 0.10
    else:
        # correlation -1..1 -> 0..0.75, con taglio prudente entro il range.
        data_confidence = max(0.0, min(0.75, ((float(correlation) + 1.0) / 2.0) * 0.75))
    return float(max(0.0, min(1.0, mapping_confidence + data_confidence)))


def _compatibility_label(score: Any, points: int, bench_ticker: str | None) -> str:
    if not bench_ticker:
        return "Senza benchmark"
    if int(points or 0) < 20:
        return "Dati insufficienti"
    if score is None or pd.isna(score):
        return "Da verificare"
    score = float(score)
    if score >= 0.78:
        return "Alta"
    if score >= 0.58:
        return "Media"
    if score >= 0.40:
        return "Bassa"
    return "Da verificare"


def _benchmark_status(compatibility: str, extra_return: Any) -> str:
    if compatibility == "Senza benchmark":
        return "Senza benchmark"
    if compatibility in {"Dati insufficienti", "Da verificare"}:
        return compatibility
    v = _safe_float(extra_return, None)
    if v is None:
        return "Confronto parziale"
    if v >= 0.02:
        return "Sovraperforma"
    if v <= -0.02:
        return "Sottoperforma"
    return "Allineato"


def _position_values_by_ticker(da_frame: pd.DataFrame | None) -> dict[str, float]:
    if da_frame is None or da_frame.empty or "Ticker" not in da_frame.columns:
        return {}
    value_col = "Controvalore" if "Controvalore" in da_frame.columns else None
    if value_col is None:
        return {}
    tmp = da_frame.copy()
    tmp["Ticker"] = tmp["Ticker"].astype(str)
    tmp[value_col] = pd.to_numeric(tmp[value_col], errors="coerce").fillna(0.0)
    return tmp.groupby("Ticker")[value_col].sum().to_dict()


def build_instrument_benchmark_matrix(
    data: dict[str, Any] | None,
    da_frame: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Costruisce una matrice read-only strumento/benchmark.

    Il confronto e' prezzo strumento vs prezzo benchmark, normalizzato sul periodo
    comune disponibile. Non simula i flussi di acquisto reali dell'investitore.
    """
    data = data if isinstance(data, dict) else {}
    strumenti = data.get("strumenti", []) if isinstance(data.get("strumenti", []), list) else []
    master = data.get("instrument_master", {}) if isinstance(data.get("instrument_master", {}), dict) else {}
    values = _position_values_by_ticker(da_frame)
    held = held_tickers(data)
    rows: list[dict[str, Any]] = []
    for s in strumenti:
        if not isinstance(s, dict):
            continue
        ticker = str(s.get("ticker") or "").strip()
        if not ticker:
            continue
        # "In portafoglio" per questa matrice significa "possiedo quote ora":
        # il campo stato puo' restare "aperto" anche dopo una vendita totale
        # se nessuno lo ritagga a mano, quindi il criterio e' la quantita'
        # reale calcolata dagli eventi (held_tickers), non lo stato dichiarato
        # — stesso criterio di ui/charts/benchmark.py::get_all_historical_tickers.
        if ticker not in held:
            continue
        m = master.get(ticker, {}) if isinstance(master.get(ticker, {}), dict) else {}
        raw_type = str(m.get("type_raw") or s.get("tipo") or "")
        category = macro_cat(raw_type)
        resolved_benchmark = _resolve_instrument_benchmark(raw_type=raw_type, category=category, master_entry=m, instrument=s)
        bench_ticker = str(resolved_benchmark.get("ticker") or "").strip() or None
        bench_label = str(resolved_benchmark.get("label") or bench_ticker or "").strip()
        source = _benchmark_source(raw_type, bench_ticker, resolved_benchmark.get("source"))
        aligned = pd.DataFrame()
        metrics = _aligned_return_metrics(aligned)
        if bench_ticker:
            inst_hist = _instrument_price_history(data, ticker)
            bench_hist = _benchmark_price_history(data, bench_ticker)
            aligned = _align_instrument_benchmark(inst_hist, bench_hist)
            metrics = _aligned_return_metrics(aligned)
        score = _compatibility_score(raw_type, bench_ticker, metrics.get("correlation"), int(metrics.get("points") or 0))
        label = _compatibility_label(score, int(metrics.get("points") or 0), bench_ticker)
        rows.append({
            "ticker": ticker,
            "strumento": str(s.get("nome") or m.get("name") or ticker),
            "tipo": raw_type,
            "categoria": category,
            "benchmark_ticker": bench_ticker or "",
            "benchmark_label": bench_label or "—",
            "benchmark_source": source,
            "compatibility_score": score,
            "compatibility_label": label,
            "instrument_return": metrics.get("instrument_return"),
            "benchmark_return": metrics.get("benchmark_return"),
            "extra_return": metrics.get("extra_return"),
            "correlation": metrics.get("correlation"),
            "tracking_error": metrics.get("tracking_error"),
            "points": int(metrics.get("points") or 0),
            "period_start": metrics.get("start") or "",
            "period_end": metrics.get("end") or "",
            "status": _benchmark_status(label, metrics.get("extra_return")),
            "controvalore": float(values.get(ticker, 0.0) or 0.0),
        })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    order_cols = ["compatibility_score", "controvalore", "ticker"]
    return df.sort_values(order_cols, ascending=[False, False, True], na_position="last").reset_index(drop=True)


def build_benchmark_transparency_payload(
    *,
    data: dict[str, Any] | None,
    settings: dict[str, Any] | None,
    da_frame: pd.DataFrame | None,
    summary_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Costruisce il payload read-only della scheda Benchmark."""
    summary_payload = summary_payload if isinstance(summary_payload, dict) else {}
    cfg = resolve_effective_benchmark_components(settings, da_frame)
    components = []
    for item in cfg.get("components", []):
        cache = _component_cache_state(data, str(item.get("ticker") or ""))
        components.append({**item, **cache})

    port = _history_frame(summary_payload.get("summary_history", []), "indice")
    bench = _history_frame(summary_payload.get("benchmark_history", []), "indice")
    start_date = None
    end_date = None
    if not port.empty:
        start_date = pd.to_datetime(port["date"].iloc[0]).date().isoformat()
        end_date = pd.to_datetime(port["date"].iloc[-1]).date().isoformat()
    elif not bench.empty:
        start_date = pd.to_datetime(bench["date"].iloc[0]).date().isoformat()
        end_date = pd.to_datetime(bench["date"].iloc[-1]).date().isoformat()

    # Tenta un allineamento utile per chart/diagnosi anche se le serie hanno granularita' diversa.
    aligned = pd.DataFrame()
    if not port.empty:
        aligned = port.rename(columns={"indice": "portafoglio"}).copy()
        if not bench.empty:
            b = bench.rename(columns={"indice": "benchmark"}).set_index("date")
            aligned = aligned.set_index("date").join(b, how="left").sort_index().ffill().reset_index()
        else:
            aligned["benchmark"] = np.nan

    portfolio_return = summary_payload.get("twr")
    if portfolio_return is None:
        portfolio_return = _series_return(port)
    benchmark_return = summary_payload.get("benchmark_return")
    if benchmark_return is None:
        benchmark_return = _series_return(bench)
    excess = summary_payload.get("excess_vs_benchmark")
    if excess is None and portfolio_return is not None and benchmark_return is not None:
        excess = float(portfolio_return) - float(benchmark_return)

    metrics = {
        "portfolio_return": portfolio_return,
        "benchmark_return": benchmark_return,
        "excess_return": excess,
        "portfolio_cagr": summary_payload.get("cagr") or _series_cagr(port),
        "benchmark_cagr": _series_cagr(bench),
        "portfolio_max_drawdown": summary_payload.get("max_drawdown") or _series_max_drawdown(port),
        "benchmark_max_drawdown": _series_max_drawdown(bench),
        "tracking_error": summary_payload.get("tracking_error"),
        "information_ratio": summary_payload.get("information_ratio"),
    }

    last_cache_date = max((str(c.get("last_date") or "") for c in components), default="")
    instrument_matrix = build_instrument_benchmark_matrix(data, da_frame)

    return {
        "config": {**cfg, "components": components},
        "period": {"start": start_date, "end": end_date},
        "last_cache_date": last_cache_date,
        "history": aligned,
        "instrument_matrix": instrument_matrix,
        "metrics": metrics,
        "availability": {
            "portfolio_points": int(len(port)),
            "benchmark_points": int(len(bench)),
            "instrument_benchmark_rows": int(len(instrument_matrix)),
            "has_benchmark": bool(not bench.empty),
        },
        "method_note": cfg.get("method_note", ""),
    }


def benchmark_explanation(payload: dict[str, Any]) -> str:
    cfg = payload.get("config", {}) if isinstance(payload, dict) else {}
    metrics = payload.get("metrics", {}) if isinstance(payload, dict) else {}
    label = str(cfg.get("label") or "Benchmark")
    mode = str(cfg.get("mode") or "")
    ex = metrics.get("excess_return")
    te = metrics.get("tracking_error")
    ir = metrics.get("information_ratio")
    bits = [f"Benchmark attivo: {label} ({mode})."]
    note = str(payload.get("method_note") or "")
    if note:
        bits.append(note)
    if ex is not None:
        ex_v = _safe_float(ex)
        bits.append("Il portafoglio e' sopra il benchmark nel periodo selezionato." if ex_v >= 0 else "Il portafoglio e' sotto il benchmark nel periodo selezionato.")
    if te is not None:
        te_v = _safe_float(te)
        if te_v < 0.05:
            bits.append("Tracking error contenuto: il portafoglio si muove vicino al riferimento.")
        elif te_v < 0.15:
            bits.append("Tracking error intermedio: il portafoglio si discosta in modo apprezzabile dal riferimento.")
        else:
            bits.append("Tracking error elevato: il portafoglio e' molto diverso dal riferimento.")
    if ir is not None:
        ir_v = _safe_float(ir)
        if ir_v >= 0.5:
            bits.append("Information ratio positivo e robusto: l'extra-rendimento e' coerente con lo scostamento assunto.")
        elif ir_v >= 0:
            bits.append("Information ratio positivo ma prudente: l'extra-rendimento c'e', ma non e' ancora molto robusto.")
        else:
            bits.append("Information ratio negativo: lo scostamento dal benchmark non ha prodotto valore aggiunto nel periodo.")
    return " ".join(bits)
