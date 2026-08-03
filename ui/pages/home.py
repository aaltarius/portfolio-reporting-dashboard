"""
ui/pages/home.py — Tab Portafoglio (t1): tabella posizioni, KPI, grafici
Pure rendering with service functions and centralized theme.
"""
import html
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from core.asset_categories import get_selected_category_codes
from core.cache_policy import build_cache_artifact_signature, get_cache_artifact_spec
from core.cache_orchestrator import get_or_build_registered_artifact, get_registered_figure_cache
from core.cache_signatures import build_portfolio_data_signature, charts_settings_signature, theme_signature
from core.config import COLORS
from core.data_models import ThemeConfig
from core.figure_cache import CachingStrategy
from persistence.storage import _safe_float, get_proventi_normalizzati
from core.render_profiler import profile_step
from core.settings_profiles import (
    get_effective_market_ticker_tape_enabled,
    get_effective_portfolio_insights_enabled,
    resolve_figure_cache_strategy,
)

from core.services import (
    build_pl_delta_series,
    build_weekly_pl_table,
)
from core.services.portfolio_insights import build_portfolio_insights
from persistence.storage import SATOR_DECISIONS_FILE, macro_cat
from core.finance import build_proventi_summary
from ui.formatting import fmt_eur_it, fmt_pct_it, fmt_num_it, fmtds
from ui.i18n import t
from ui.theme import CATEGORY_COLORS, get_theme_context, instrument_color, macro_color
from ui.components import (
    macro_legend_html,
    legend_block, kpi_card, build_price_direction_map,
    render_styled_table, back_to_top, vertical_gap, should_render_section, render_section_title,
)
from ui.charts.axes import zero_aligned_ranges
from ui.charts.overview import build_overview_time_chart
from ui.charts.home import (
    build_category_allocation_pie_chart,
    build_category_bar_chart,
    build_concentration_chart,
    build_instrument_allocation_pie_chart,
    build_instrument_bar_chart,
    build_portfolio_pl_chart,
    build_portfolio_pl_category_chart,
)
from ui.charts.portfolio_popup import render_portfolio_table_with_popup, render_weekly_pl_table
from ui.charts.tables import color_pl, style_macro_cols
from ui.insights import render_portfolio_insights
from ui.market_tape import render_market_ticker_tape
from ui.page_chrome import render_page_intro as render_page_intro_shared
from ui.charts.settings import apply_settings

_DAILY_EUR_DISPLAY_EPS = 0.005


def _normalize_best_worst_name_block(name: str, companion_name: str, threshold: int = 26) -> str:
    """Aggiunge una riga invisibile al nome più corto quando il compagno va a capo."""
    this_wraps = len(str(name or "")) > threshold
    other_wraps = len(str(companion_name or "")) > threshold
    if not this_wraps and other_wraps:
        return f"{name}<br><span style='visibility:hidden;'>.</span>"
    return name


def _as_date_key(value: Any) -> str:
    try:
        ts = pd.to_datetime(value, errors="coerce")
        if pd.isna(ts):
            return ""
        return str(ts.date())
    except Exception:
        return ""


def _build_last_day_income_context(dfh: pd.DataFrame, data: dict[str, Any] | None = None) -> dict[str, Any]:
    if dfh is None or dfh.empty:
        return {"date": "", "total_net": 0.0, "by_ticker": {}}
    last_date_key = _as_date_key(dfh.iloc[-1].get("Data"))
    by_ticker: dict[str, float] = {}
    total_net = 0.0
    for item in get_proventi_normalizzati(data or {}):
        if _as_date_key(item.get("data")) != last_date_key:
            continue
        ticker = str(item.get("ticker") or "")
        netto = _safe_float(item.get("importo_netto", 0.0))
        if not ticker or abs(netto) <= 1e-12:
            continue
        by_ticker[ticker] = by_ticker.get(ticker, 0.0) + netto
        total_net += netto
    return {"date": last_date_key, "total_net": total_net, "by_ticker": by_ticker}


def _build_last_day_market_only_history(
    dfh: pd.DataFrame,
    data: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Restituisce una vista storica depurata dai proventi cumulati incassati."""
    if dfh is None or dfh.empty:
        return dfh

    income_by_date: dict[str, float] = {}
    for item in get_proventi_normalizzati(data or {}):
        date_key = _as_date_key(item.get("data"))
        if not date_key:
            continue
        netto = _safe_float(item.get("importo_netto", 0.0))
        if abs(netto) <= 1e-12:
            continue
        income_by_date[date_key] = income_by_date.get(date_key, 0.0) + netto

    if not income_by_date:
        return dfh

    adjusted = dfh.copy()
    adjusted_dates = adjusted["Data"].apply(_as_date_key)
    cumulative_income = 0.0
    cumulative_series: list[float] = []
    for date_key in adjusted_dates:
        cumulative_income += float(income_by_date.get(date_key, 0.0) or 0.0)
        cumulative_series.append(cumulative_income)

    cumulative_income_series = pd.Series(cumulative_series, index=adjusted.index, dtype="float64")
    for column in ("P/L", "Valore", "Liquidita", "Liquidità"):
        if column in adjusted.columns:
            adjusted[column] = pd.to_numeric(adjusted[column], errors="coerce").sub(cumulative_income_series, fill_value=0.0)
    return adjusted


def _trim_history_to_latest_market_date(dfh: pd.DataFrame, data: dict[str, Any] | None = None) -> pd.DataFrame:
    """Rimuove eventuali righe sintetiche successive all'ultima data prezzi reale."""
    if dfh is None or dfh.empty or "Data" not in dfh.columns:
        return dfh
    _, latest_market_date = _latest_two_market_dates((data or {}).get("storico_prezzi", {}) or {})
    if not latest_market_date:
        return dfh
    latest_ts = pd.Timestamp(latest_market_date).normalize()
    dates = pd.to_datetime(dfh["Data"], errors="coerce").dt.normalize()
    trimmed = dfh.loc[dates <= latest_ts].copy()
    return trimmed if len(trimmed) >= 2 else dfh


def _build_last_day_contributors_report(
    dfh: pd.DataFrame,
    info_map: dict[str, dict[str, Any]] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Helper della Home: contributori migliori/peggiori dell'ultima giornata."""
    if dfh is None or len(dfh) < 2:
        return None

    info_map = info_map or {}
    last = dfh.iloc[-1]
    prev = dfh.iloc[-2]
    pl_cols = [c for c in dfh.columns if c.startswith("PL_")]
    if not pl_cols:
        return None

    contributors: list[dict[str, Any]] = []
    for col in pl_cols:
        tk = col[3:]
        try:
            v_last = float(last[col]) if pd.notna(last[col]) else None
            v_prev = float(prev[col]) if pd.notna(prev[col]) else None
            if v_last is None or v_prev is None:
                continue
            delta = v_last - v_prev
            info = info_map.get(tk, {})
            pct_change = None
            current_value = None
            if info.get("prezzo") is not None and info.get("qt") is not None:
                try:
                    current_value = float(info.get("prezzo")) * float(info.get("qt"))
                except (TypeError, ValueError):
                    current_value = None
            if current_value is not None:
                previous_value = current_value - delta
                if previous_value not in (None, 0):
                    pct_change = delta / previous_value
            contributors.append(
                {
                    "ticker": tk,
                    "name": info.get("nome") or tk,
                    "delta": delta,
                    "pct_change": pct_change,
                    "category": macro_cat(info.get("tipo", "")),
                }
            )
        except Exception:
            continue

    positives = [item for item in contributors if item["delta"] > 0]
    negatives = [item for item in contributors if item["delta"] < 0]
    positives.sort(key=lambda item: item["delta"], reverse=True)
    negatives.sort(key=lambda item: item["delta"])

    return {
        "up_count": len(positives),
        "down_count": len(negatives),
        "best": positives,
        "worst": negatives,
        "all": contributors,
    }


def _finite_float_or_none(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _positive_float_or_none(value: Any) -> float | None:
    result = _finite_float_or_none(value)
    return result if result is not None and result > 0 else None


def _price_state_from_pct(pct: float | None) -> str:
    if pct is None:
        return "flat"
    if pct > 0.03:
        return "up_big"
    if pct > 0:
        return "up"
    if pct < -0.03:
        return "down_big"
    if pct < 0:
        return "down"
    return "flat"


def _last_two_valid_prices_for_ticker(
    storico: dict[str, Any],
    ticker: str,
    *,
    prev_date: str | None = None,
    last_date: str | None = None,
) -> tuple[tuple[str, float], tuple[str, float]] | None:
    if prev_date and last_date:
        prev_values = storico.get(prev_date) if isinstance(storico, dict) else None
        last_values = storico.get(last_date) if isinstance(storico, dict) else None
        if not isinstance(prev_values, dict) or not isinstance(last_values, dict):
            return None
        prev_price = _positive_float_or_none(prev_values.get(ticker))
        last_price = _positive_float_or_none(last_values.get(ticker))
        if prev_price is None or last_price is None:
            return None
        return (str(prev_date), prev_price), (str(last_date), last_price)

    points: list[tuple[str, float]] = []
    for raw_date in sorted((storico or {}).keys()):
        day_values = storico.get(raw_date)
        if not isinstance(day_values, dict) or ticker not in day_values:
            continue
        price = _positive_float_or_none(day_values.get(ticker))
        if price is not None:
            points.append((str(raw_date), price))
    if len(points) < 2:
        return None
    return points[-2], points[-1]


def _latest_two_market_dates(storico: dict[str, Any] | None) -> tuple[str | None, str | None]:
    if not isinstance(storico, dict) or len(storico) < 2:
        return None, None
    valid_dates = [
        str(day)
        for day, values in storico.items()
        if isinstance(values, dict) and any(_positive_float_or_none(value) is not None for value in values.values())
    ]
    if len(valid_dates) < 2:
        return None, None
    valid_dates = sorted(valid_dates)
    return valid_dates[-2], valid_dates[-1]


def _build_price_based_daily_variation(
    row: pd.Series,
    data: dict[str, Any],
    *,
    prev_date: str | None = None,
    last_date: str | None = None,
) -> dict[str, float | str] | None:
    """Restituisce delta giornaliero coerente: stessa fonte prezzo per % ed euro."""
    ticker = str(row.get("Ticker", "") or "")
    if not ticker:
        return None

    pair = _last_two_valid_prices_for_ticker(
        data.get("storico_prezzi", {}) or {},
        ticker,
        prev_date=prev_date,
        last_date=last_date,
    )
    if pair is None:
        return None
    (pair_prev_date, prev_price), (pair_last_date, last_price) = pair
    if prev_price <= 0:
        return None

    pct = (last_price - prev_price) / prev_price
    if not math.isfinite(pct) or abs(1.0 + pct) <= 1e-12:
        return None

    current_value = _finite_float_or_none(row.get("Controvalore"))
    if current_value is None:
        qty = _finite_float_or_none(row.get("Quote"))
        current_value = qty * last_price if qty is not None else None
    if current_value is None:
        return None

    previous_value = current_value / (1.0 + pct)
    delta_eur = current_value - previous_value
    if not math.isfinite(delta_eur):
        return None

    return {
        "state": _price_state_from_pct(pct),
        "delta_eur": delta_eur,
        "delta_pct": pct,
        "source": "price_value",
        "prev_date": pair_prev_date,
        "last_date": pair_last_date,
    }


def _build_direction_map_contributors_report(
    da: pd.DataFrame,
    data: dict[str, Any],
    direction_map: dict[str, Any],
) -> dict[str, Any]:
    info_map = {str(s.get("ticker", "")): s for s in data.get("strumenti", [])}
    contributors: list[dict[str, Any]] = []
    prev_date = None
    last_date = None
    if da is None or da.empty:
        return {"up_count": 0, "down_count": 0, "best": [], "worst": [], "all": [], "prev_date": None, "last_date": None}

    for _, row in da.iterrows():
        tk = str(row.get("Ticker", "") or "")
        raw = direction_map.get(tk)
        if not isinstance(raw, dict):
            continue
        delta = _finite_float_or_none(raw.get("delta_eur"))
        pct_change = _finite_float_or_none(raw.get("delta_pct"))
        if delta is None:
            continue
        if raw.get("prev_date"):
            prev_date = str(raw.get("prev_date"))
        if raw.get("last_date"):
            last_date = str(raw.get("last_date"))
        info = info_map.get(tk, {})
        contributors.append(
            {
                "ticker": tk,
                "name": info.get("nome") or row.get("Strumento") or tk,
                "delta": delta,
                "pct_change": pct_change,
                "category": macro_cat(info.get("tipo", row.get("Tipo", ""))),
                "source": raw.get("source"),
            }
        )

    positives = [item for item in contributors if float(item.get("delta", 0.0) or 0.0) > _DAILY_EUR_DISPLAY_EPS]
    negatives = [item for item in contributors if float(item.get("delta", 0.0) or 0.0) < -_DAILY_EUR_DISPLAY_EPS]
    positives.sort(key=lambda item: float(item.get("delta", 0.0) or 0.0), reverse=True)
    negatives.sort(key=lambda item: float(item.get("delta", 0.0) or 0.0))
    return {
        "up_count": len(positives),
        "down_count": len(negatives),
        "best": positives,
        "worst": negatives,
        "all": contributors,
        "prev_date": prev_date,
        "last_date": last_date,
    }


def _build_portfolio_table_direction_map(
    da: pd.DataFrame,
    dfh: pd.DataFrame,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Costruisce variazione giornaliera coerente per riga della tabella Home."""
    base_map: dict[str, Any] = dict(build_price_direction_map(data))
    if da is None or da.empty:
        return base_map

    visible_tickers = {str(tk) for tk in da.get("Ticker", pd.Series(dtype=str)).dropna()}
    prev_market_date, last_market_date = _latest_two_market_dates(data.get("storico_prezzi", {}) or {})
    price_based_tickers: set[str] = set()
    for _, row in da.iterrows():
        tk = str(row.get("Ticker", "") or "")
        if not tk:
            continue
        price_variation = _build_price_based_daily_variation(
            row,
            data,
            prev_date=prev_market_date,
            last_date=last_market_date,
        )
        if price_variation is None:
            continue
        base_map[tk] = price_variation
        price_based_tickers.add(tk)

    if dfh is None or len(dfh) < 2:
        return base_map

    info_map = {str(s.get("ticker", "")): s for s in data.get("strumenti", [])}
    report = _build_last_day_contributors_report(dfh, info_map, data) or {}
    for item in report.get("all", []):
        tk = str(item.get("ticker") or "")
        if not tk or tk not in visible_tickers or tk in price_based_tickers:
            continue
        existing = base_map.get(tk, "flat")
        state = existing.get("state", "flat") if isinstance(existing, dict) else existing
        base_map[tk] = {
            "state": state or "flat",
            "delta_eur": item.get("delta"),
            "delta_pct": item.get("pct_change"),
            "source": "pl_history",
        }
    return base_map


def _compute_home_category_deltas(
    dfh: pd.DataFrame,
    data: dict[str, Any],
    prev_idx: int | None = None,
) -> dict[str, dict[str, float]]:
    """Helper della Home: delta P/L per categoria nell'ultima giornata."""
    if prev_idx is None:
        prev_idx = len(dfh) - 2
    if len(dfh) < 2 or prev_idx < 0:
        return {}

    last = dfh.iloc[-1]
    prev = dfh.iloc[prev_idx]
    pl_cols = [c for c in dfh.columns if c.startswith("PL_")]
    if not pl_cols:
        return {}

    ticker_to_cat = {
        s.get("ticker", ""): macro_cat(s.get("tipo", ""))
        for s in data.get("strumenti", [])
    }
    category_deltas: dict[str, dict[str, float]] = {}
    for col in pl_cols:
        ticker = col[3:]
        cat = ticker_to_cat.get(ticker, "Altro")

        # Skip instruments where either last or prev row is NaN (avoids closing-event spikes)
        if not (pd.notna(last[col]) and pd.notna(prev[col])):
            continue

        v_last = float(last[col])
        v_prev = float(prev[col])
        delta = v_last - v_prev

        if cat not in category_deltas:
            category_deltas[cat] = {"delta_pl": 0, "max_pl": 0}
        category_deltas[cat]["delta_pl"] += delta
        category_deltas[cat]["max_pl"] = max(category_deltas[cat]["max_pl"], v_last)

    return category_deltas


def _build_last_day_summary(
    dfh: pd.DataFrame,
    info_map: dict[str, dict[str, Any]] | None = None,
    data: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
    daily_report: dict[str, Any] | None = None,
) -> str | None:
    """Helper della Home: HTML della sintesi dell'ultima giornata disponibile."""
    if dfh is None or len(dfh) < 2:
        return None

    last = dfh.iloc[-1]
    prev = dfh.iloc[-2]
    delta_valore = float(last["Valore"]) - float(prev["Valore"])
    theme = get_theme_context()
    # Compute delta only from instruments open in BOTH rows (avoids closing-event spikes)
    raw_delta_pl = (
        sum(float(item.get("delta", 0.0) or 0.0) for item in daily_report.get("all", []))
        if daily_report is not None
        else float(build_pl_delta_series(dfh, theme)["deltas"][-1])
    )
    delta_capitale = float(last.get("Capitale", 0.0)) - float(prev.get("Capitale", 0.0))
    last_date = fmtds(last["Data"])
    prev_date = fmtds(prev["Data"])
    income_context = _build_last_day_income_context(dfh, data)
    day_income = float(income_context.get("total_net", 0.0) or 0.0)
    delta_pl = raw_delta_pl if daily_report is not None else raw_delta_pl - day_income

    prev_pl_value = float(prev["P/L"]) if float(prev["P/L"]) != 0 else 0.0
    pct_var = (delta_pl / prev_pl_value) if abs(prev_pl_value) > 1e-9 else 0

    col_green = theme.colors["success"]
    col_red = theme.colors["danger"]
    sign_color_v = col_green if delta_pl >= 0 else col_red
    sign_color_pl = col_green if delta_pl >= 0 else col_red

    if daily_report is not None:
        up_count = int(daily_report.get("up_count", 0) or 0)
        down_count = int(daily_report.get("down_count", 0) or 0)
        category_deltas: dict[str, dict[str, float]] = {}
        for item in daily_report.get("all", []) or []:
            cat = str(item.get("category") or "Altro")
            delta = float(item.get("delta", 0.0) or 0.0)
            if cat not in category_deltas:
                category_deltas[cat] = {"delta_pl": 0.0, "max_pl": 0.0}
            category_deltas[cat]["delta_pl"] += delta
            category_deltas[cat]["max_pl"] = max(category_deltas[cat]["max_pl"], abs(delta))
        report = daily_report
        if daily_report.get("last_date"):
            last_date = fmtds(daily_report.get("last_date"))
        if daily_report.get("prev_date"):
            prev_date = fmtds(daily_report.get("prev_date"))
    else:
        pl_cols = [c for c in dfh.columns if c.startswith("PL_")]
        up_count = sum(
            1
            for col in pl_cols
            if pd.notna(last[col]) and pd.notna(prev[col]) and (float(last[col]) - float(prev[col])) > 0
        )
        down_count = sum(
            1
            for col in pl_cols
            if pd.notna(last[col]) and pd.notna(prev[col]) and (float(last[col]) - float(prev[col])) < 0
        )
        category_deltas = _compute_home_category_deltas(dfh, data or {}, len(dfh) - 2)
        report = _build_last_day_contributors_report(dfh, info_map, data) or {}
    best_items = list(report.get("best", []) or [])
    worst_items = list(report.get("worst", []) or [])
    visible_categories = list(get_selected_category_codes(settings))

    html_lines = []
    html_lines.append('<div style="display: grid; grid-template-columns: 0.8fr 1fr 0.8fr; gap: 12px; padding: 12px; background: var(--ptf-surface); border: 1px solid var(--ptf-border); border-radius: 8px;">')
    html_lines.append('<div style="display: flex; flex-direction: column; gap: 4px;">')
    html_lines.append(f'<div style="display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap;"><span style="font-size: 1.8rem; font-weight: 700; color: {sign_color_v};">{fmt_pct_it(pct_var, 2, signed=True)}</span><span title="Variazione percentuale del P/L dell&apos;ultima giornata rispetto al P/L del giorno precedente." style="font-size: 0.85rem; color: var(--ptf-muted); cursor:help;">Rendimento giorno ⓘ</span><span style="font-size: 1rem; font-weight: 600; color: {sign_color_v};">{fmt_eur_it(delta_pl, 2, signed=True)}</span><span title="Variazione in euro del risultato di mercato dell&apos;ultima giornata." style="font-size: 0.8rem; color: {sign_color_pl}; font-weight: 600; cursor:help;">P/L giorno ⓘ</span></div>')
    if abs(day_income) > 1e-9:
        income_color = col_green if day_income >= 0 else col_red
        html_lines.append(f'<div style="font-size: 0.76rem; color: var(--ptf-muted);">Proventi della giornata: <span style="color:{income_color}; font-weight:600;">{fmt_eur_it(day_income, 2, signed=True)}</span></div>')
    if abs(delta_capitale) > 1e-9:
        flow_color = col_green if delta_capitale >= 0 else col_red
        html_lines.append(f'<div style="font-size: 0.76rem; color: var(--ptf-muted);">Flussi della giornata: <span style="color:{flow_color}; font-weight:600;">{fmt_eur_it(delta_capitale, 2, signed=True)}</span></div>')
    if abs(delta_valore - raw_delta_pl) > 1e-9:
        html_lines.append(f'<div style="font-size: 0.76rem; color: var(--ptf-muted);">Variazione lorda valore: {fmt_eur_it(delta_valore, 2, signed=True)}</div>')
    html_lines.append(f'<div style="font-size: 0.8rem; color: var(--ptf-muted);"><span style="color: {col_green}; font-weight: 600;">{up_count}▲</span> <span style="color: var(--ptf-muted);">/</span> <span style="color: {col_red}; font-weight: 600;">{down_count}▼</span></div>')
    html_lines.append(f'<div style="font-size: 0.75rem; color: var(--ptf-muted);">{last_date} vs {prev_date}</div>')
    html_lines.append('</div>')

    html_lines.append('<div style="display: flex; flex-direction: column; justify-content: center; gap: 8px; padding-left: 10px;">')
    max_delta = max((abs(category_deltas.get(c, {}).get("delta_pl", 0)) for c in visible_categories), default=1)
    for cat in visible_categories:
        color = CATEGORY_COLORS.get(cat, macro_color(cat))
        delta = category_deltas.get(cat, {}).get("delta_pl", 0)
        sign_color = col_green if delta >= 0 else col_red
        bar_width = int((abs(delta) / max_delta * 80)) if max_delta > 0 else 15
        justify = "flex-end" if delta < 0 else "flex-start"
        html_lines.append(
            f'<div>'
            f'<div style="display:flex; align-items:center; gap:8px;">'
            f'<div style="min-width:32px; font-size:0.75rem; font-weight:700; color:{color}; text-transform:uppercase;">{cat}</div>'
            f'<div style="position:relative; width:170px; height:14px;">'
            f'<div style="position:absolute; left:50%; top:0; bottom:0; width:1px; background:rgba(148,163,184,0.45);"></div>'
            f'<div style="position:absolute; top:4px; {"left:calc(50% - " + str(bar_width) + "px);" if delta < 0 else "left:50%;"} display:flex; justify-content:{justify};">'
            f'<div style="background:{sign_color}; height:6px; border-radius:3px; width:{bar_width}px;"></div>'
            f'</div></div>'
            f'<div style="font-size:0.8rem; color:{sign_color}; font-weight:600;">{fmt_eur_it(delta, 2, signed=True)}</div>'
            f'</div></div>'
        )
    html_lines.append('</div>')

    html_lines.append('<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; align-items: center;">')
    best_item = best_items[0] if best_items else None
    worst_item = worst_items[0] if worst_items else None
    if best_item or worst_item:
        nome_best = (
            info_map.get(best_item["ticker"], {}).get("nome", best_item["ticker"])
            if best_item and info_map else (best_item["ticker"] if best_item else "")
        )
        nome_worst = (
            info_map.get(worst_item["ticker"], {}).get("nome", worst_item["ticker"])
            if worst_item and info_map else (worst_item["ticker"] if worst_item else "")
        )
        nome_best_html = _normalize_best_worst_name_block(str(nome_best), str(nome_worst))
        nome_worst_html = _normalize_best_worst_name_block(str(nome_worst), str(nome_best))
        if best_item and abs(float(best_item.get("delta", 0.0) or 0.0)) > 0:
            html_lines.append(
                f'<div style="min-width:0;"><div style="font-size: 0.75rem; color: {col_green}; text-transform: uppercase; font-weight: 600;">▲ Best</div>'
                f'<div style="font-size: 0.75rem; color: var(--ptf-text); font-weight: 500; line-height: 1.1; word-break: break-word;">{nome_best_html}</div>'
                f'<div style="font-size: 0.8rem; color: {col_green}; font-weight: 600; margin-top: 2px;">{fmt_eur_it(float(best_item.get("delta", 0.0) or 0.0), 2, signed=True)}</div></div>'
            )
        else:
            html_lines.append('<div></div>')
        if worst_item and abs(float(worst_item.get("delta", 0.0) or 0.0)) > 0:
            html_lines.append(
                f'<div style="min-width:0;"><div style="font-size: 0.75rem; color: {col_red}; text-transform: uppercase; font-weight: 600;">▼ Worst</div>'
                f'<div style="font-size: 0.75rem; color: var(--ptf-text); font-weight: 500; line-height: 1.1; word-break: break-word;">{nome_worst_html}</div>'
                f'<div style="font-size: 0.8rem; color: {col_red}; font-weight: 600; margin-top: 2px;">{fmt_eur_it(float(worst_item.get("delta", 0.0) or 0.0), 2, signed=True)}</div></div>'
            )
        else:
            html_lines.append('<div></div>')
    html_lines.append('</div>')
    html_lines.append('</div>')

    return '\n'.join(html_lines)


def _render_last_day_contributors_tables(
    dfh_top: pd.DataFrame,
    data: dict[str, Any],
    theme: ThemeConfig,
    daily_report: dict[str, Any] | None = None,
) -> None:
    """Mostra titoli migliori e peggiori dell'ultima giornata in due box affiancati di pari altezza."""
    info_map = {s["ticker"]: s for s in data.get("strumenti", [])}
    report = daily_report if daily_report is not None else _build_last_day_contributors_report(dfh_top, info_map, data)
    if not report:
        return

    best_items = report.get("best", [])
    worst_items = report.get("worst", [])
    if not best_items and not worst_items:
        return

    row_count = max(len(best_items), len(worst_items), 1)
    table_height = max(220, 74 + row_count * 35)

    def _build_table(items: list[dict[str, Any]], empty_label: str) -> pd.DataFrame:
        if not items:
            return pd.DataFrame(
                [{"Ticker": "—", "Strumento": empty_label, "Var. su Ctv %": None, "Delta €": None, "_category": ""}]
            )
        rows = []
        for item in items:
            ticker = str(item.get("ticker", "") or "")
            rows.append(
                {
                    "Ticker": ticker,
                    "Strumento": str(item.get("name", "") or ticker),
                    "Var. su Ctv %": item.get("pct_change"),
                    "Delta €": item.get("delta"),
                    "_category": str(item.get("category", "") or ""),
                }
            )
        return pd.DataFrame(rows)

    def _render_table(title: str, accent: str, items: list[dict[str, Any]], empty_label: str) -> None:
        table_df = _build_table(items, empty_label)
        display_df = table_df[["Ticker", "Strumento", "Var. su Ctv %", "Delta €"]]

        def _ticker_style(value: Any) -> str:
            match = table_df.loc[table_df["Ticker"] == value, "_category"]
            category = match.iloc[0] if not match.empty else ""
            color = macro_color(str(category or ""))
            return f"color: {color}; font-weight: 700;"

        def _signed_text_style(value: Any) -> str:
            if value is None or pd.isna(value):
                return ""
            numeric_value = float(value)
            if numeric_value < 0:
                return f"color: {theme.color_red}; font-weight: 600;"
            if numeric_value > 0:
                return f"color: {theme.color_green}; font-weight: 600;"
            return ""

        styler = (
            display_df.style
            .map(_ticker_style, subset=["Ticker"])
            .map(_signed_text_style, subset=["Var. su Ctv %", "Delta €"])
            .format({
                "Var. su Ctv %": lambda v: "—" if v is None or pd.isna(v) else fmt_pct_it(v, 2, signed=True),
                "Delta €": lambda v: "—" if v is None or pd.isna(v) else fmt_eur_it(v, 2, signed=True),
            })
        )

        st.markdown(
            f"<div style='font-size:0.76rem; font-weight:700; color:{accent}; text-transform:uppercase; letter-spacing:0.02em; margin:0 0 6px 0;'>{title} ({len(items)})</div>",
            unsafe_allow_html=True,
        )
        render_styled_table(
            styler,
            height=table_height,
            column_config={
                "Ticker": st.column_config.TextColumn(width="small"),
                "Strumento": st.column_config.TextColumn(width="medium"),
                "Var. su Ctv %": st.column_config.NumberColumn(width="small"),
                "Delta €": st.column_config.NumberColumn(width="small"),
            },
        )

    c_best, c_worst = st.columns(2)
    with c_best:
        _render_table("▲ BEST - TITOLI MIGLIORI", theme.color_green, best_items, "Nessun titolo in rialzo")
    with c_worst:
        _render_table("▼ WORST - TITOLI PEGGIORI", theme.color_red, worst_items, "Nessun titolo in calo")


def _render_home_andamento_clone(
    dfh_top: pd.DataFrame,
    data: dict[str, Any],
    theme: ThemeConfig,
    settings: dict[str, Any] | None = None,
    chart_loader=None,
) -> None:
    """Replica nella scheda Portafoglio il solo grafico Profit / Loss Complessivo."""
    dfh_real_market = _trim_history_to_latest_market_date(dfh_top, data)
    dfh_market_only = _build_last_day_market_only_history(dfh_real_market, data)
    income_context = _build_last_day_income_context(dfh_real_market, data)
    home_pl_extra_params = {
        "rows": len(dfh_market_only),
        "market_view": "last_day_net_proventi_cumulative_v2",
        "last_day": str(income_context.get("date") or ""),
        "last_day_income": round(float(income_context.get("total_net", 0.0) or 0.0), 6),
    }
    with profile_step("Portafoglio/UltimaGiornata", "build delta series", count=len(dfh_market_only)):
        delta_data = build_pl_delta_series(dfh_market_only, theme)
    with profile_step("Portafoglio/UltimaGiornata", "load fig portfolio pl", count=len(dfh_top)):
        if chart_loader is None:
            fig = build_portfolio_pl_chart(
                dfh_market_only,
                delta_data["colors"],
                delta_data["delta_text"],
                "%d/%m/%Y",
                theme,
            )
            apply_settings(fig, 'home_portfolio_pl')
        else:
            fig = chart_loader(
                "home_portfolio_pl",
                lambda: apply_settings(
                    build_portfolio_pl_chart(
                        dfh_market_only,
                        delta_data["colors"],
                        delta_data["delta_text"],
                        "%d/%m/%Y",
                        theme,
                    ),
                    "home_portfolio_pl",
                ),
                extra_params=home_pl_extra_params,
            )
    with profile_step("Portafoglio/UltimaGiornata", "render fig portfolio pl"):
        st.plotly_chart(fig, width="stretch")
    with profile_step("Portafoglio/UltimaGiornata", "load fig portfolio pl category", count=len(dfh_real_market)):
        fig_cat = (
            apply_settings(build_portfolio_pl_category_chart(dfh_real_market, data, theme, settings=settings), 'home_portfolio_pl_category')
            if chart_loader is None
            else chart_loader(
                "home_portfolio_pl_category",
                lambda: apply_settings(
                    build_portfolio_pl_category_chart(dfh_real_market, data, theme, settings=settings),
                    'home_portfolio_pl_category',
                ),
                extra_params={"rows": len(dfh_real_market), "cats": "|".join(get_selected_category_codes(settings))},
            )
        )
    if len(fig_cat.data) > 0:
        with profile_step("Portafoglio/UltimaGiornata", "render fig portfolio pl category"):
            st.plotly_chart(fig_cat, width="stretch")


def _file_fingerprint(path_value: str) -> dict[str, Any]:
    path = Path(str(path_value or ""))
    try:
        stat = path.stat()
        return {
            "exists": True,
            "mtime": round(float(stat.st_mtime), 3),
            "size": int(stat.st_size),
        }
    except Exception:
        return {"exists": False, "mtime": 0.0, "size": 0}


def _portfolio_table_settings_payload(settings: dict[str, Any] | None) -> dict[str, Any]:
    settings = settings or {}
    alerts = settings.get("alerts", {}) if isinstance(settings.get("alerts", {}), dict) else {}
    return {
        "selected_categories": list(get_selected_category_codes(settings)),
        "portfolio_insights_enabled": get_effective_portfolio_insights_enabled(settings),
        "portfolio_objective": settings.get("portfolio_objective", {}),
        "sator": settings.get("sator", {}),
        "concentration_threshold_pct": alerts.get("concentration_threshold_pct"),
    }


def _build_positions_table_payload(
    da: pd.DataFrame,
    dfh_top: pd.DataFrame,
    data: dict[str, Any],
    settings: dict[str, Any] | None,
    *,
    include_insights: bool,
) -> dict[str, Any]:
    """Payload cacheabile della sezione Controvalore del Portafoglio."""

    table_df = da.copy() if isinstance(da, pd.DataFrame) else pd.DataFrame()
    direction_map: dict[str, Any] = {}
    daily_report: dict[str, Any] | None = None
    insights = []
    if not table_df.empty:
        with profile_step("Portafoglio", "build positions table direction map", count=len(table_df)):
            direction_map = _build_portfolio_table_direction_map(table_df, dfh_top, data)
            daily_report = _build_direction_map_contributors_report(table_df, data, direction_map)
        if include_insights:
            with profile_step("Portafoglio", "build portfolio insights", count=len(table_df)):
                insights = build_portfolio_insights(
                    table_df,
                    dfh_top,
                    data,
                    settings or {},
                    direction_map=direction_map,
                    daily_report=daily_report,
                )
    return {
        "da": table_df,
        "direction_map": direction_map,
        "daily_report": daily_report,
        "insights": insights,
    }


def _render_portfolio_table_section(
    da: pd.DataFrame,
    dfh_top: pd.DataFrame,
    data: dict[str, Any],
    proventi: list[dict[str, Any]] | None,
    tv: float,
    theme: ThemeConfig,
    settings: dict[str, Any] | None = None,
    macro_summary: pd.DataFrame | None = None,
    chart_loader=None,
    direction_map: dict[str, Any] | None = None,
    daily_report: dict[str, Any] | None = None,
) -> None:
    """Mostra tabella posizioni, ultimo giorno, allocazione e concentrazione."""
    settings = settings or {}
    _price_direction_map = direction_map or {}
    _daily_report = daily_report
    if not da.empty:
        if not _price_direction_map:
            _price_direction_map = _build_portfolio_table_direction_map(da, dfh_top, data)
        if _daily_report is None:
            _daily_report = _build_direction_map_contributors_report(da, data, _price_direction_map)
        with profile_step("Portafoglio", "render tabella posizioni", count=len(da)):
            render_portfolio_table_with_popup(da, data, direction_map=_price_direction_map)
            legend_block(
                """
                <div style="width:100%;">
                  <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:14px;flex-wrap:wrap;margin-bottom:10px;">
                    <div>
                      <div style="font-size:0.72rem;text-transform:uppercase;letter-spacing:.08em;font-weight:800;opacity:.68;margin-bottom:2px;">Lettura rapida</div>
                      <div style="font-size:0.95rem;font-weight:800;line-height:1.25;">Da sinistra a destra: esposizione, valore, andamento, risultato e giornata.</div>
                    </div>
                    <div style="font-size:0.78rem;font-weight:800;padding:4px 9px;border-radius:999px;border:1px solid color-mix(in srgb,var(--ptf-primary) 22%,transparent);background:color-mix(in srgb,var(--ptf-primary) 7%,transparent);white-space:nowrap;">Clic sul ticker = dettaglio completo</div>
                  </div>
                  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:0;border-top:1px solid color-mix(in srgb,var(--ptf-text) 10%,transparent);">
                    <div style="padding:9px 12px 3px 0;"><b>Esposizione</b><br><span style="opacity:.78;">Peso %, quote e PMC.</span></div>
                    <div style="padding:9px 12px 3px 0;"><b>Valore</b><br><span style="opacity:.78;">Controvalore della posizione.</span></div>
                    <div style="padding:9px 12px 3px 0;"><b>60g</b><br><span style="opacity:.78;">Prezzo recente; tratteggio = PMC.</span></div>
                    <div style="padding:9px 12px 3px 0;"><b>Risultato</b><br><span style="opacity:.78;">P/L € e P/L %.</span></div>
                    <div style="padding:9px 0 3px 0;"><b>Giornata</b><br><span style="opacity:.78;">Var. gg e freccia prezzo.</span></div>
                  </div>
                </div>
                """
            )

        if should_render_section("Portafoglio", "Andamento ultima giornata", settings):
            if not dfh_top.empty and len(dfh_top) > 1:
                with profile_step("Portafoglio", "render andamento ultima giornata", count=len(dfh_top)):
                    _home_info_map = {s["ticker"]: s for s in data.get("strumenti", [])}
                    with profile_step("Portafoglio/UltimaGiornata", "build sintesi html", count=len(dfh_top)):
                        _home_last_day_html = _build_last_day_summary(dfh_top, _home_info_map, data, settings, daily_report=_daily_report)
                    if _home_last_day_html:
                        with profile_step("Portafoglio/UltimaGiornata", "render header e html"):
                            render_section_title(
                                "Andamento dell'ultima giornata",
                                icon="quotes",
                                gap_after="xs",
                            )
                            st.markdown(_home_last_day_html, unsafe_allow_html=True)
                            st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)
                        with profile_step("Portafoglio/UltimaGiornata", "render tabelle best worst"):
                            _render_last_day_contributors_tables(dfh_top, data, theme, daily_report=_daily_report)
                        with profile_step("Portafoglio/UltimaGiornata", "render grafico andamento clone", count=len(dfh_top)):
                            st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)
                            _render_home_andamento_clone(dfh_top, data, theme, settings, chart_loader=chart_loader)

        if should_render_section("Portafoglio", "Andamento dell'ultima settimana", settings):
            with profile_step("Portafoglio", "render andamento ultima settimana", count=len(da)):
                weekly = build_weekly_pl_table(da, dfh_top, data)
                if weekly:
                    render_section_title(
                        "Andamento dell'ultima settimana",
                        icon="quotes",
                        gap_after="xs",
                    )
                    render_weekly_pl_table(weekly, da, data)
                    legend_block(
                        "P/L giornaliero per strumento negli ultimi giorni di quotazione disponibili, calcolato come "
                        "variazione del risultato non realizzato (quantità × prezzo − costo) rispetto al giorno "
                        "precedente. La colonna P/L totale è la somma dei giorni mostrati in tabella, non il P/L "
                        "complessivo dello strumento. Celle vuote: strumento non ancora in portafoglio in quella data."
                    )

        if should_render_section("Portafoglio", "P/L per Categoria", settings):
            if not dfh_top.empty and len(dfh_top) > 1:
                with profile_step("Portafoglio", "render P/L per categoria", count=len(dfh_top)):
                    render_section_title(
                        "P/L per Categoria",
                        icon="chart",
                        gap_after="xs",
                    )
                    if chart_loader is None:
                        fig_cat_history = build_overview_time_chart(
                            dfh_top, da, "P/L per Categoria", None, 0.0, None, None, theme, settings=settings, total_return=None
                        )
                    else:
                        fig_cat_history = chart_loader(
                            "overview_pl_categoria",
                            lambda: build_overview_time_chart(
                                dfh_top, da, "P/L per Categoria", None, 0.0, None, None, theme, settings=settings, total_return=None
                            ),
                            extra_params={"rows": len(dfh_top), "cats": "|".join(get_selected_category_codes(settings))},
                        )
                    st.plotly_chart(fig_cat_history, width="stretch")
                    legend_block(
                        "Andamento storico del P/L delle categorie visibili, sovrapposte (area impilata)."
                    )

        if should_render_section("Portafoglio", "Proventi per strumento", settings):
            _render_proventi_section(proventi, data)

        if should_render_section("Portafoglio", "Sintesi allocazione", settings):
            render_section_title(
                "Sintesi allocazione",
                icon="portfolio",
                gap_after="xs",
            )
        with profile_step("Portafoglio", "render sintesi allocazione", count=len(macro_summary) if isinstance(macro_summary, pd.DataFrame) else 0):
            legend_block(
                "Riepilogo rapido di peso, risultato e concentrazione. Il peso percentuale aiuta a capire quanto ogni area influenzi il portafoglio complessivo, mentre la concentrazione evidenzia se pochi strumenti incidono in modo dominante."
            )

            # Use service to build macro summary
            macro_summary = macro_summary.copy() if isinstance(macro_summary, pd.DataFrame) else pd.DataFrame()
            if not macro_summary.empty:
                display_summary = macro_summary.copy()
                for col in ["Costo", "Controvalore", "P/L €"]:
                    display_summary[col] = display_summary[col].apply(lambda v: fmt_eur_it(v, 2))
                for col in ["Peso %", "P/L %"]:
                    display_summary[col] = display_summary[col].apply(lambda v: fmt_pct_it(v, 2))

                styled = (
                    display_summary[["Tipologia", "Costo", "Controvalore", "Peso %", "P/L €", "P/L %"]].style
                    .apply(style_macro_cols, axis=1)
                    .map(color_pl, subset=["P/L €", "P/L %"])
                )
                render_styled_table(styled, height="content")

        if len(da) >= 2:
            with profile_step("Portafoglio", "render grafico concentrazione", count=len(da)):
                if chart_loader is None:
                    fig_conc = build_concentration_chart(da, tv, theme, settings=settings)
                    apply_settings(fig_conc, 'home_concentration')
                else:
                    fig_conc = chart_loader(
                        "home_concentration",
                        lambda: apply_settings(build_concentration_chart(da, tv, theme, settings=settings), 'home_concentration'),
                        extra_params={"items": len(da), "tv": round(float(tv or 0.0), 2)},
                    )
                st.plotly_chart(fig_conc, width="stretch")


def _render_performance_charts(
    da: pd.DataFrame,
    tv: float,
    theme: ThemeConfig,
    settings: dict[str, Any] | None = None,
    chart_loader=None,
) -> None:
    """Mostra pie chart allocazione e chart performance %."""
    with profile_step("Portafoglio", "render grafici allocazione e performance", count=len(da)):
        visible_categories = list(get_selected_category_codes(settings))
        categories_text = ", ".join(visible_categories)
        g1, g2 = st.columns(2)
        with g1:
            if not da.empty and tv > 0:
                legend_block(
                    "Come è ripartito il portafoglio tra i singoli strumenti in termini di valore. "
                    "Le fette molto piccole non riportano l'etichetta per non affollare il grafico, ma sono sempre visibili nella legenda.",
                    min_height=118
                )
                if chart_loader is None:
                    fig = build_instrument_allocation_pie_chart(da)
                    apply_settings(fig, 'home_instrument_pie')
                else:
                    fig = chart_loader(
                        "home_instrument_pie",
                        lambda: apply_settings(build_instrument_allocation_pie_chart(da), 'home_instrument_pie'),
                        extra_params={"items": len(da)},
                    )
                st.plotly_chart(fig, width="stretch")

        with g2:
            if not da.empty:
                fig = (
                    build_category_allocation_pie_chart(da, settings=settings)
                    if chart_loader is None
                    else chart_loader(
                        "home_category_allocation_pie",
                        lambda: build_category_allocation_pie_chart(da, settings=settings),
                        extra_params={"items": len(da), "cats": categories_text},
                    )
                )
                if fig is not None:
                    legend_block(
                        f"Distribuzione del portafoglio nelle macro-categorie visibili: {categories_text}. "
                        + macro_legend_html(settings),
                        min_height=118
                    )
                    st.plotly_chart(fig, width="stretch")

        _gp3, _gp4 = st.columns(2)
        with _gp3:
            ds = da.sort_values("P/L %")
            legend_block(
                "Rendimento percentuale di ciascuna posizione rispetto al costo di acquisto. Ogni strumento mantiene lo stesso colore usato nei grafici a torta per un riconoscimento immediato.",
                min_height=118
            )
            if chart_loader is None:
                fig = build_instrument_bar_chart(ds, "P/L %", "Performance %", fmt_pct_it, ".0%", 1)
                apply_settings(fig, 'home_instrument_bar_perf')
            else:
                fig = chart_loader(
                    "home_instrument_bar_perf",
                    lambda: apply_settings(build_instrument_bar_chart(ds, "P/L %", "Performance %", fmt_pct_it, ".0%", 1), 'home_instrument_bar_perf'),
                    extra_params={"items": len(ds)},
                )
            st.plotly_chart(fig, width="stretch")

        with _gp4:
            ds2 = da.sort_values("P/L €")
            legend_block(
                "Guadagno o perdita in euro di ciascuna posizione. Le barre più lunghe identificano i titoli che pesano di più sul risultato complessivo, positivo o negativo.",
                min_height=118
            )
            if chart_loader is None:
                fig = build_instrument_bar_chart(ds2, "P/L €", "P/L in Euro", fmt_eur_it, ",", 0)
                apply_settings(fig, 'home_instrument_bar_pl')
            else:
                fig = chart_loader(
                    "home_instrument_bar_pl",
                    lambda: apply_settings(build_instrument_bar_chart(ds2, "P/L €", "P/L in Euro", fmt_eur_it, ",", 0), 'home_instrument_bar_pl'),
                    extra_params={"items": len(ds2)},
                )
            st.plotly_chart(fig, width="stretch")


def _render_category_analysis(
    da: pd.DataFrame,
    cat_agg: pd.DataFrame | None = None,
    settings: dict[str, Any] | None = None,
    chart_loader=None,
) -> None:
    """Mostra grafici per controvalore, P/L €, e P/L % per categoria."""
    if not da.empty:
        with profile_step("Portafoglio", "render analisi macro-categoria", count=len(da)):
            visible_categories = list(get_selected_category_codes(settings))
            categories_text = ", ".join(visible_categories)
            render_section_title(
                "Analisi per Macro-Categoria",
                comment=(
                    f"Vista di insieme per {categories_text}: controvalore attuale, risultato in euro e rendimento percentuale. "
                    "I grafici usano la stessa codifica a colori delle sezioni precedenti. "
                    + macro_legend_html(settings)
                ),
                icon="analysis",
            )
            if cat_agg is None:
                from core.services import get_category_allocation_breakdown
                cat_agg = get_category_allocation_breakdown(da, settings)
            cat_agg = cat_agg[cat_agg["Categoria"].isin(visible_categories)].copy()

            # Allinea la linea dello zero tra i 3 grafici affiancati: se una
            # categoria ha P/L €/% negativo, senza questo i 3 assi Y (unità
            # diverse, autorange indipendente) mostrerebbero lo zero ad altezze
            # diverse. Restituisce None per ciascuno se non ci sono negativi
            # (nessuna modifica al comportamento nel caso comune).
            value_range, pl_range, perf_range = zero_aligned_ranges([
                cat_agg["Controvalore"].tolist(),
                cat_agg["P/L €"].tolist(),
                cat_agg["P/L %"].tolist(),
            ])

            gc1, gc2, gc3 = st.columns(3)
            with gc1:
                if chart_loader is None:
                    fig = build_category_bar_chart(cat_agg, "Controvalore", "Controvalore", fmt_eur_it, ",", settings, y_range=value_range)
                else:
                    fig = chart_loader(
                        "home_category_bar_value",
                        lambda: build_category_bar_chart(cat_agg, "Controvalore", "Controvalore", fmt_eur_it, ",", settings, y_range=value_range),
                        extra_params={"items": len(cat_agg), "y_range": value_range},
                    )
                st.plotly_chart(fig, width="stretch")
            with gc2:
                if chart_loader is None:
                    fig = build_category_bar_chart(cat_agg, "P/L €", "P/L per Categoria", fmt_eur_it, ",", settings, y_range=pl_range)
                else:
                    fig = chart_loader(
                        "home_category_bar_pl",
                        lambda: build_category_bar_chart(cat_agg, "P/L €", "P/L per Categoria", fmt_eur_it, ",", settings, y_range=pl_range),
                        extra_params={"items": len(cat_agg), "y_range": pl_range},
                    )
                st.plotly_chart(fig, width="stretch")
            with gc3:
                if chart_loader is None:
                    fig = build_category_bar_chart(cat_agg, "P/L %", "Performance % per Categoria", fmt_pct_it, ".1%", settings, y_range=perf_range)
                else:
                    fig = chart_loader(
                        "home_category_bar_perf",
                        lambda: build_category_bar_chart(cat_agg, "P/L %", "Performance % per Categoria", fmt_pct_it, ".1%", settings, y_range=perf_range),
                        extra_params={"items": len(cat_agg), "y_range": perf_range},
                    )
                st.plotly_chart(fig, width="stretch")


def _flow_card(title: str, rows: list[tuple[str, str]], total_label: str, total_val: str, total_ok: bool) -> str:
    """HTML card per il flowchart finanziario. rows = [(label, valore_formattato), ...]"""
    tot_color = COLORS["success"] if total_ok else COLORS["danger"]
    rows_html = "".join(
        f'<tr><td style="padding:2px 6px;font-size:12px;color:#888;">{lbl}</td>'
        f'<td style="padding:2px 6px;font-size:12px;font-weight:600;text-align:right;">{val}</td></tr>'
        for lbl, val in rows
    )
    return (
        f'<div style="border:1px solid #ccc;border-radius:8px;padding:10px 12px;'
        f'background:var(--background-color,#fff);min-height:120px;">'
        f'<div style="font-size:12px;font-weight:700;letter-spacing:.04em;'
        f'text-transform:uppercase;margin-bottom:6px;color:#666;">{title}</div>'
        f'<table style="width:100%;border-collapse:collapse;">{rows_html}'
        f'<tr style="border-top:1px solid #ddd;">'
        f'<td style="padding:4px 6px;font-size:13px;font-weight:700;">{total_label}</td>'
        f'<td style="padding:4px 6px;font-size:14px;font-weight:800;text-align:right;color:{tot_color};">'
        f'{total_val}</td></tr></table></div>'
    )


_ARROW_H = '<div style="display:flex;align-items:center;justify-content:center;height:100%;font-size:28px;color:#aaa;padding-top:30px;">&#8594;</div>'
_ARROW_V = '<div style="text-align:center;font-size:24px;color:#aaa;padding:4px 0;">&#8595;</div>'




def _render_proventi_section(proventi: list[dict[str, Any]], data: dict[str, Any]) -> None:
    """Mostra riepilogo proventi (cedole e dividendi)."""
    if proventi:
        with profile_step("Portafoglio", "render sezione proventi", count=len(proventi)):
            render_section_title(
                "Proventi per strumento",
                comment=(
                    "Riepilogo delle cedole e dei dividendi incassati per ogni strumento. "
                    "L'importo netto è al netto della ritenuta fiscale applicata."
                ),
                icon="income",
            )
            _info_map_prov = {s["ticker"]: s for s in data["strumenti"]}
            prov_summary = build_proventi_summary(proventi, _info_map_prov)
            if not prov_summary.empty:
                styled_prov = (
                    prov_summary.style
                    .format({
                        "Lordo totale": lambda v: fmt_eur_it(v, 2),
                        "Ritenute": lambda v: fmt_eur_it(v, 2),
                        "Netto totale": lambda v: fmt_eur_it(v, 2),
                        "N": lambda v: fmt_num_it(v, 0),
                    })
                )
                render_styled_table(styled_prov)


def render_home(tab: DeltaGenerator, ctx: SimpleNamespace) -> None:
    """Pure rendering for home page dashboard."""
    theme = get_theme_context()

    data = ctx.data
    da = ctx.da
    dfh_top = ctx.dfh_top
    tv = ctx.tv
    tc = ctx.tc
    pl = ctx.pl
    pl_color = ctx.pl_color
    patrimonio_totale = ctx.patrimonio_totale
    liquidita = ctx.liquidita_attuale
    proventi = ctx.proventi
    settings = ctx.settings if hasattr(ctx, 'settings') else {}
    macro_summary = getattr(ctx, "macro_summary_report", pd.DataFrame())
    data_sig = build_portfolio_data_signature(
        data,
        app_version=str(getattr(ctx, "app_version", "n/d")),
        schema_version=str(getattr(ctx, "schema_version", "n/d")),
    )
    theme_sig = theme_signature(theme)
    charts_sig = charts_settings_signature("ui/charts/settings.py")
    strategy_name = resolve_figure_cache_strategy(settings, st.session_state)
    if strategy_name == "disabled":
        cache_strategy = CachingStrategy.DISABLED
    elif strategy_name == "session_only":
        cache_strategy = CachingStrategy.SESSION_ONLY
    elif strategy_name == "disk_only":
        cache_strategy = CachingStrategy.DISK_ONLY
    else:
        cache_strategy = CachingStrategy.HYBRID
    fcache = get_registered_figure_cache()

    def _chart_loader(chart_id: str, builder, *, extra_params: dict[str, Any] | None = None):
        return fcache.get_or_build(
            chart_id=chart_id,
            data_sig=data_sig,
            theme_sig=theme_sig,
            charts_settings_sig=charts_sig,
            builder=builder,
            page_mode="Completa",
            extra_params=extra_params or {},
            strategy=cache_strategy,
        )

    with tab:
        render_page_intro_shared(
            t(settings, "page_intro.portafoglio.title", "Home"),
            t(settings, "page_intro.portafoglio.comment", "Vista rapida del portafoglio: posizioni attive, andamento recente, allocazione per macro-categoria e proventi gia' incassati."),
            "portfolio",
            theme,
        )
        active_count = len(da.index) if not da.empty else 0
        _chiusi_tk = getattr(ctx, "chiusi_tickers", frozenset())
        total_count = sum(1 for s in data.get("strumenti", []) if str(s.get("ticker") or "") not in _chiusi_tk)
        suffix = f"{active_count} strumenti attivi su {total_count} osservati"
        if should_render_section("Portafoglio", "Controvalore del Portafoglio", settings):
            _portfolio_da = da
            _portfolio_direction_map: dict[str, Any] = {}
            _portfolio_daily_report: dict[str, Any] | None = None
            _portfolio_insights = []
            if not da.empty:
                _positions_spec = get_cache_artifact_spec("portafoglio.positions_table")
                _positions_sig = build_cache_artifact_signature(
                    "portafoglio.positions_table",
                    inputs={
                        "data_sig": data_sig,
                        "rows": len(da),
                        "history_rows": len(dfh_top) if isinstance(dfh_top, pd.DataFrame) else 0,
                        "settings": _portfolio_table_settings_payload(settings),
                        "sator_decisions": _file_fingerprint(SATOR_DECISIONS_FILE),
                    },
                )
                with profile_step("Portafoglio", "load/build positions table artifact", count=len(da)):
                    _positions_artifact = get_or_build_registered_artifact(
                        artifact_id=_positions_spec.artifact_id,
                        signature=_positions_sig,
                        builder=lambda: _build_positions_table_payload(
                            da,
                            dfh_top,
                            data,
                            settings,
                            include_insights=get_effective_portfolio_insights_enabled(settings),
                        ),
                        clone_on_read=True,
                    )
                _positions_payload = _positions_artifact.value if isinstance(_positions_artifact.value, dict) else {}
                if isinstance(_positions_payload.get("da"), pd.DataFrame):
                    _portfolio_da = _positions_payload.get("da")
                _portfolio_direction_map = _positions_payload.get("direction_map") or {}
                _portfolio_daily_report = _positions_payload.get("daily_report")
                _portfolio_insights = list(_positions_payload.get("insights") or [])
                if get_effective_portfolio_insights_enabled(settings) and _portfolio_insights:
                    with profile_step("Portafoglio", "render portfolio insights", count=len(_portfolio_insights)):
                        render_portfolio_insights(_portfolio_insights, theme)
            render_section_title(
                "Controvalore del Portafoglio",
                subtitle=suffix,
                icon="portfolio",
                gap_after="xs",
            )
            if get_effective_market_ticker_tape_enabled(settings):
                with profile_step("Portafoglio", "render striscia mercati"):
                    render_market_ticker_tape(data, theme)
            _render_portfolio_table_section(
                _portfolio_da,
                dfh_top,
                data,
                proventi,
                tv,
                theme,
                settings,
                macro_summary=macro_summary,
                chart_loader=_chart_loader,
                direction_map=_portfolio_direction_map,
                daily_report=_portfolio_daily_report,
            )
            _render_performance_charts(da, tv, theme, settings, chart_loader=_chart_loader)

        vertical_gap("md")
        if should_render_section("Portafoglio", "Analisi per Macro-Categoria", settings):
            _render_category_analysis(da, getattr(ctx, "category_breakdown", None), settings, chart_loader=_chart_loader)
            vertical_gap("md")
        back_to_top(show_prev=True, show_next=True, nav_key="portafoglio")
