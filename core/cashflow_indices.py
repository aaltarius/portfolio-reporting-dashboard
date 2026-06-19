from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd

from core.cache_signatures import build_portfolio_data_signature
from persistence.storage import APP_VERSION

_INTERMEDIATE_DATA_CACHE: dict[str, tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]] = {}
_INTERMEDIATE_DATA_CACHE_MAX = 24
_TICKER_VALUE_FLOW_CACHE: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
_TICKER_VALUE_FLOW_CACHE_MAX = 8


def _cache_put(key: str, value) -> None:
    _INTERMEDIATE_DATA_CACHE[key] = value
    while len(_INTERMEDIATE_DATA_CACHE) > _INTERMEDIATE_DATA_CACHE_MAX:
        oldest_key = next(iter(_INTERMEDIATE_DATA_CACHE))
        _INTERMEDIATE_DATA_CACHE.pop(oldest_key, None)


def _ticker_cache_put(key: str, value) -> None:
    _TICKER_VALUE_FLOW_CACHE[key] = value
    while len(_TICKER_VALUE_FLOW_CACHE) > _TICKER_VALUE_FLOW_CACHE_MAX:
        oldest_key = next(iter(_TICKER_VALUE_FLOW_CACHE))
        _TICKER_VALUE_FLOW_CACHE.pop(oldest_key, None)


def _group_map_signature(group_map) -> str:
    normalized = {
        str(group): sorted(str(item) for item in members)
        for group, members in sorted((group_map or {}).items(), key=lambda item: str(item[0]))
    }
    raw = json.dumps(normalized, sort_keys=True, ensure_ascii=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


def _frame_runtime_signature(frame: pd.DataFrame) -> str:
    if frame is None or frame.empty:
        return "empty"
    tail = frame.tail(5)
    payload = {
        "shape": list(frame.shape),
        "columns": [str(col) for col in frame.columns],
        "index_min": str(frame.index.min()),
        "index_max": str(frame.index.max()),
        "tail": tail.to_json(date_format="iso", default_handler=str),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


def _operation_cashflow(op) -> float:
    qty = float(op.get("qty", 0) or 0)
    price = float(op.get("price", 0) or 0)
    comm = float(op.get("comm", 0) or 0)
    if op.get("tipo") == "ACQUISTO":
        return qty * price + comm
    return -(qty * price - comm)


def _base_value_flow_cache_key(data, price_frame) -> str:
    payload = {
        "kind": "ticker_value_flow_tables",
        "data_sig": build_portfolio_data_signature(
            data if isinstance(data, dict) else {},
            app_version=str(APP_VERSION),
            schema_version=str((data or {}).get("schema_version", "n/d")) if isinstance(data, dict) else "n/d",
            include_benchmark_data=False,
        ),
        "price_frame_sig": _frame_runtime_signature(price_frame),
    }
    return hashlib.md5(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()


def _group_cashflow_indices_cache_key(data, price_frame, group_map) -> str:
    cache_key_payload = {
        "kind": "group_cashflow_indices",
        "data_sig": build_portfolio_data_signature(
            data if isinstance(data, dict) else {},
            app_version=str(APP_VERSION),
            schema_version=str((data or {}).get("schema_version", "n/d")) if isinstance(data, dict) else "n/d",
            include_benchmark_data=False,
        ),
        "price_frame_sig": _frame_runtime_signature(price_frame),
        "group_map_sig": _group_map_signature(group_map),
    }
    return hashlib.md5(json.dumps(cache_key_payload, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()


def seed_group_cashflow_indices_cache(data, price_frame, group_map, result) -> None:
    """Seed a derived group-cashflow result when it was sliced from a superset build."""
    if not group_map or result is None:
        return
    try:
        index_df, returns_df, values_df, flows_df = result
        _cache_put(
            _group_cashflow_indices_cache_key(data, price_frame, group_map),
            (
                index_df.copy() if hasattr(index_df, "copy") else index_df,
                returns_df.copy() if hasattr(returns_df, "copy") else returns_df,
                values_df.copy() if hasattr(values_df, "copy") else values_df,
                flows_df.copy() if hasattr(flows_df, "copy") else flows_df,
            ),
        )
    except Exception:
        return


def build_ticker_value_flow_tables(data, price_frame):
    if price_frame is None or price_frame.empty:
        return (pd.DataFrame(), pd.DataFrame())

    cache_key = _base_value_flow_cache_key(data, price_frame)
    cached = _TICKER_VALUE_FLOW_CACHE.get(cache_key)
    if cached is not None:
        return tuple(item.copy() if hasattr(item, "copy") else item for item in cached)

    idx = pd.DatetimeIndex(price_frame.index).sort_values()
    tickers = [str(col) for col in price_frame.columns]
    if not tickers:
        return (pd.DataFrame(), pd.DataFrame())

    price_matrix = (
        price_frame.reindex(index=idx, columns=tickers)
        .apply(pd.to_numeric, errors="coerce")
        .ffill()
    )

    qty_rows: list[dict[str, Any]] = []
    flow_rows: list[dict[str, Any]] = []
    valid_tickers = set(tickers)
    for op in sorted(data.get("operazioni", []), key=lambda x: str(x.get("data", ""))):
        ticker = str(op.get("ticker", "") or "")
        if ticker not in valid_tickers:
            continue
        try:
            op_date = pd.Timestamp(pd.to_datetime(op.get("data"))).normalize()
            qty = float(op.get("qty", 0) or 0.0)
        except Exception:
            continue
        effective_pos = idx.searchsorted(op_date, side="left")
        if effective_pos >= len(idx):
            continue
        effective_date = idx[effective_pos]
        signed_qty = qty if op.get("tipo") == "ACQUISTO" else -qty
        qty_rows.append({"Data": effective_date, "Ticker": ticker, "QtyDelta": signed_qty})
        flow_rows.append({"Data": effective_date, "Ticker": ticker, "Cashflow": _operation_cashflow(op)})

    if qty_rows:
        qty_delta = (
            pd.DataFrame(qty_rows)
            .pivot_table(index="Data", columns="Ticker", values="QtyDelta", aggfunc="sum")
            .reindex(index=idx, columns=tickers, fill_value=0.0)
            .sort_index()
            .fillna(0.0)
        )
        positions_frame = qty_delta.cumsum()
    else:
        positions_frame = pd.DataFrame(0.0, index=idx, columns=tickers, dtype=float)

    if flow_rows:
        flows_by_ticker = (
            pd.DataFrame(flow_rows)
            .pivot_table(index="Data", columns="Ticker", values="Cashflow", aggfunc="sum")
            .reindex(index=idx, columns=tickers, fill_value=0.0)
            .sort_index()
            .fillna(0.0)
            .astype(float)
        )
    else:
        flows_by_ticker = pd.DataFrame(0.0, index=idx, columns=tickers, dtype=float)

    value_by_ticker = positions_frame.multiply(price_matrix, fill_value=0.0).astype(float)
    result = (value_by_ticker, flows_by_ticker)
    _ticker_cache_put(cache_key, tuple(item.copy() if hasattr(item, "copy") else item for item in result))
    return result


def build_group_value_flow_tables(data, price_frame, group_map):
    if price_frame is None or price_frame.empty or (not group_map):
        return (pd.DataFrame(), pd.DataFrame())
    idx = pd.DatetimeIndex(price_frame.index).sort_values()
    cols = list(group_map.keys())
    value_by_ticker, flows_by_ticker = build_ticker_value_flow_tables(data, price_frame)
    available_tickers = set(str(col) for col in value_by_ticker.columns)
    relevant_tickers = sorted(
        {
            str(ticker)
            for members in group_map.values()
            for ticker in members
            if str(ticker) in available_tickers
        }
    )

    if not relevant_tickers:
        empty = pd.DataFrame(0.0, index=idx, columns=cols, dtype=float)
        return (empty.copy(), empty)
    values = pd.DataFrame(
        {
            group_name: value_by_ticker.reindex(columns=[str(tk) for tk in members if str(tk) in value_by_ticker.columns], fill_value=0.0).sum(axis=1)
            for group_name, members in group_map.items()
        },
        index=idx,
    ).astype(float)
    flows = pd.DataFrame(
        {
            group_name: flows_by_ticker.reindex(columns=[str(tk) for tk in members if str(tk) in flows_by_ticker.columns], fill_value=0.0).sum(axis=1)
            for group_name, members in group_map.items()
        },
        index=idx,
    ).astype(float)

    return (values, flows)


def build_twr_index_from_value_flow(value_series, flow_series):
    values = pd.Series(value_series, dtype=float)
    flows = pd.Series(flow_series, index=values.index, dtype=float).fillna(0.0)
    out = []
    started = False
    prev_val = np.nan
    last_index = np.nan
    for date in values.index:
        val = values.loc[date]
        cashflow = flows.loc[date]
        if not started:
            if pd.notna(val) and val > 0:
                started = True
                last_index = 100.0
                prev_val = float(val)
                out.append(last_index)
            else:
                out.append(np.nan)
            continue
        if pd.notna(prev_val) and prev_val > 0 and pd.notna(val):
            period_ret = (float(val) - float(cashflow)) / float(prev_val) - 1
            if not np.isfinite(period_ret):
                period_ret = 0.0
            last_index = float(last_index) * (1.0 + period_ret)
            out.append(last_index)
        else:
            out.append(np.nan)
        if pd.notna(val) and val > 0:
            prev_val = float(val)
    return pd.Series(out, index=values.index, dtype=float)


def build_group_cashflow_indices(data, price_frame, group_map):
    cache_key = _group_cashflow_indices_cache_key(data, price_frame, group_map)
    cached = _INTERMEDIATE_DATA_CACHE.get(cache_key)
    if cached is not None:
        return tuple(item.copy() if hasattr(item, "copy") else item for item in cached)

    values, flows = build_group_value_flow_tables(data, price_frame, group_map)
    if values.empty:
        return (pd.DataFrame(), pd.DataFrame(), values, flows)
    frames = {}
    for col in values.columns:
        idx_series = build_twr_index_from_value_flow(values[col], flows[col])
        if idx_series.notna().sum() >= 2:
            frames[col] = idx_series
    if not frames:
        return (pd.DataFrame(), pd.DataFrame(), values, flows)
    index_df = pd.DataFrame(frames).sort_index()
    returns_df = index_df.pct_change().replace([np.inf, -np.inf], np.nan)
    result = (index_df, returns_df, values, flows)
    _cache_put(cache_key, tuple(item.copy() if hasattr(item, "copy") else item for item in result))
    return result
