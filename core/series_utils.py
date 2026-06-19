from __future__ import annotations

import pandas as pd

from core.asset_categories import ACTIVE_CATEGORY_CODES, get_selected_category_codes
from persistence.storage import _normalize_macro_label, get_registro_eventi


def slice_recent(df, days):
    if df is None or df.empty:
        return df
    cutoff = pd.to_datetime(df.index.max()) - pd.Timedelta(days=int(days))
    return df[df.index >= cutoff].copy()


def get_current_position_start_dates(data, positions=None) -> dict[str, pd.Timestamp]:
    """Return the latest opening date for each currently open position."""
    open_positions = positions if isinstance(positions, dict) else {}
    current_open = {
        str(tk): float((pos or {}).get("qty", 0.0) or 0.0)
        for tk, pos in open_positions.items()
        if float((pos or {}).get("qty", 0.0) or 0.0) > 0.0001
    }
    if not current_open:
        return {}

    qty_by_ticker: dict[str, float] = {}
    start_by_ticker: dict[str, pd.Timestamp] = {}
    try:
        events = get_registro_eventi(data)
    except Exception:
        events = data.get("registro_eventi", []) or []

    for event in sorted(events, key=lambda ev: str(ev.get("data", ""))):
        ticker = str(event.get("ticker") or "").strip()
        if ticker not in current_open:
            continue
        event_type = str(event.get("tipo_evento") or event.get("tipo") or "").strip().upper()
        event_date = pd.to_datetime(event.get("data"), errors="coerce")
        if pd.isna(event_date):
            continue
        qty = float(event.get("quantita", event.get("qty", 0.0)) or 0.0)
        before = float(qty_by_ticker.get(ticker, 0.0) or 0.0)
        if event_type == "ACQUISTO":
            after = before + qty
            if before <= 0.0001 and after > 0.0001:
                start_by_ticker[ticker] = pd.Timestamp(event_date).normalize()
            qty_by_ticker[ticker] = after
        elif event_type in {"VENDITA", "RIMBORSO A SCADENZA"}:
            after = max(0.0, before - qty)
            qty_by_ticker[ticker] = after
            if after <= 0.0001:
                start_by_ticker.pop(ticker, None)

    return {
        ticker: start
        for ticker, start in start_by_ticker.items()
        if ticker in current_open
    }


def build_category_return_index(dh, data, settings=None, positions=None):
    if dh is None or dh.empty:
        return pd.DataFrame()
    price_frame = dh.apply(pd.to_numeric, errors="coerce").sort_index().ffill()
    info_map = {s["ticker"]: s for s in data.get("strumenti", [])}
    open_positions = positions if isinstance(positions, dict) else {}
    position_starts = get_current_position_start_dates(data, open_positions)
    frames = {}
    visible_categories = list(get_selected_category_codes(settings)) if settings is not None else list(ACTIVE_CATEGORY_CODES)
    for cat in visible_categories:
        tickers = [
            tk
            for tk in price_frame.columns
            if tk in info_map
            and _normalize_macro_label(info_map[tk].get("tipo", "")) == cat
            and (price_frame[tk].notna().sum() > 0)
            and float((open_positions.get(tk, {}) or {}).get("qty", 0.0) or 0.0) > 0.0001
        ]
        if not tickers:
            continue
        norm_parts = []
        for tk in tickers:
            series = price_frame[tk].dropna()
            start_date = position_starts.get(tk)
            if start_date is not None:
                series = series.loc[series.index >= start_date]
            if series.empty:
                continue
            base = series.iloc[0]
            if pd.isna(base) or base == 0:
                continue
            norm_parts.append(series / base * 100)
        if not norm_parts:
            continue
        tmp = pd.concat(norm_parts, axis=1)
        frames[cat] = tmp.mean(axis=1, skipna=True)
    if not frames:
        return pd.DataFrame()
    return pd.DataFrame(frames).sort_index()
