"""Pagina Mercati: radar esterno dei principali indici internazionali.

La pagina non scarica dati in automatico durante il render: legge lo storico
benchmark gia' presente nel dataset, cosi' resta leggera nei rerun Streamlit.
"""
from __future__ import annotations

import math
import html
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from core.cache import record_cache_decision, set_last_mutation_details
from core.cache_policy import build_cache_artifact_signature, get_cache_artifact_spec
from core.cache_orchestrator import get_or_build_registered_artifact
from core.cache_signatures import build_market_data_signature
from core.config import COLORS
from core.render_profiler import profile_step
from core.services.market_universe_refresh import (
    DEFAULT_MARKET_REFRESH_PERIOD,
    format_market_combined_refresh_report,
    market_items_for_refresh,
    refresh_market_universe_benchmark_data,
    refresh_market_universe_live_data,
)
from persistence.storage import BENCHMARK_CACHE_FILE, default_benchmark_cache, save_benchmark_data, _read_json_file
from ui.components import back_to_top, legend_block, render_section_title, render_styled_table
from ui.formatting import fmt_num_it, fmt_pct_it
from ui.i18n import t
from ui.market_tape import _market_is_open, build_market_tape_items
from ui.market_universe import MARKET_SECTION_ORDER, MARKET_UNIVERSE_ITEMS
from ui.notifications import queue_success
from ui.page_chrome import render_page_intro as render_page_intro_shared
from ui.theme import P, get_theme_context


def _finite_float(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _market_cache_counts(payload: dict[str, Any] | None) -> tuple[int, int]:
    source = payload if isinstance(payload, dict) else {}
    benchmark_data = source.get("benchmark_data", {}) if isinstance(source.get("benchmark_data", {}), dict) else {}
    market_live_data = source.get("market_live_data", {}) if isinstance(source.get("market_live_data", {}), dict) else {}
    return len(benchmark_data), len(market_live_data)


def _merge_disk_market_cache(data: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, int]]:
    """Aggancia alla pagina Mercati la cache esterna benchmark/live.

    La cache Mercati vive in un file dedicato e non deve dipendere dalle cache
    derivate Streamlit del portafoglio: altrimenti un refresh puo' scaricare i
    dati ma la pagina continuare a renderizzare un payload vecchio.
    """
    payload = data if isinstance(data, dict) else {}
    disk_cache = _read_json_file(BENCHMARK_CACHE_FILE, default_benchmark_cache())
    disk_benchmark = disk_cache.get("benchmark_data", {}) if isinstance(disk_cache.get("benchmark_data", {}), dict) else {}
    disk_live = disk_cache.get("market_live_data", {}) if isinstance(disk_cache.get("market_live_data", {}), dict) else {}
    ctx_benchmark_count, ctx_live_count = _market_cache_counts(payload)
    if not disk_benchmark and not disk_live:
        return payload, {
            "ctx_benchmark": ctx_benchmark_count,
            "ctx_live": ctx_live_count,
            "disk_benchmark": 0,
            "disk_live": 0,
        }

    merged = dict(payload)
    if disk_benchmark:
        merged["benchmark_data"] = disk_benchmark
    if disk_live:
        merged["market_live_data"] = disk_live
    return merged, {
        "ctx_benchmark": ctx_benchmark_count,
        "ctx_live": ctx_live_count,
        "disk_benchmark": len(disk_benchmark),
        "disk_live": len(disk_live),
    }


def _series_from_benchmark_data(data: dict | None, aliases: tuple[str, ...]) -> tuple[str, pd.Series]:
    benchmark_data = (data or {}).get("benchmark_data", {}) or {}
    if not isinstance(benchmark_data, dict):
        return "", pd.Series(dtype=float)
    candidates: list[tuple[pd.Timestamp, int, int, str, pd.Series]] = []
    for order, ticker in enumerate(aliases):
        raw = benchmark_data.get(f"bench_{ticker}")
        if not isinstance(raw, dict) or not raw:
            continue
        points: list[tuple[pd.Timestamp, float]] = []
        for date_key, value in raw.items():
            numeric = _finite_float(value)
            ts = pd.to_datetime(date_key, errors="coerce")
            if numeric is not None and numeric > 0 and not pd.isna(ts):
                points.append((ts.normalize(), numeric))
        if points:
            frame = pd.DataFrame(points, columns=["Data", "Valore"]).drop_duplicates("Data", keep="last")
            frame = frame.sort_values("Data")
            series = pd.Series(frame["Valore"].to_numpy(), index=frame["Data"])
            candidates.append((pd.Timestamp(series.index[-1]), len(series), -order, ticker, series))
    if candidates:
        _last_date, _points, _priority, ticker, series = max(candidates, key=lambda item: (item[0], item[1], item[2]))
        return ticker, series
    return "", pd.Series(dtype=float)


def _live_quote_from_data(data: dict | None, aliases: tuple[str, ...]) -> tuple[str, dict[str, Any]]:
    live_data = (data or {}).get("market_live_data", {}) or {}
    if not isinstance(live_data, dict):
        return "", {}
    candidates: list[tuple[int, int, str, dict[str, Any]]] = []
    for order, ticker in enumerate(aliases):
        raw = live_data.get(f"live_{ticker}")
        if not isinstance(raw, dict):
            continue
        price = _finite_float(raw.get("price"))
        if price is None or price <= 0:
            continue
        market_time = raw.get("regular_market_time")
        try:
            freshness = int(market_time or 0)
        except (TypeError, ValueError, OverflowError):
            freshness = 0
        candidates.append((freshness, -order, ticker, raw))
    if candidates:
        _freshness, _priority, ticker, quote = max(candidates, key=lambda item: (item[0], item[1]))
        return ticker, quote
    return "", {}


def _period_return(series: pd.Series, observations_back: int) -> float | None:
    if series is None or len(series) <= observations_back:
        return None
    start = _finite_float(series.iloc[-1 - observations_back])
    end = _finite_float(series.iloc[-1])
    if start is None or end is None or abs(start) < 1e-12:
        return None
    return (end / start) - 1.0


def _ytd_return(series: pd.Series) -> float | None:
    if series is None or series.empty:
        return None
    last_date = pd.Timestamp(series.index[-1])
    current_year = int(last_date.year)
    year_slice = series[pd.to_datetime(series.index).year == current_year]
    if year_slice.empty:
        return None
    start = _finite_float(year_slice.iloc[0])
    end = _finite_float(series.iloc[-1])
    if start is None or end is None or abs(start) < 1e-12:
        return None
    return (end / start) - 1.0


def _tone(value: float | None) -> str:
    if value is None or abs(value) < 0.00005:
        return "flat"
    return "up" if value > 0 else "down"


def _section_rank(section: str) -> int:
    try:
        return MARKET_SECTION_ORDER.index(section)
    except ValueError:
        return len(MARKET_SECTION_ORDER) + 1


def _format_date_it(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = pd.to_datetime(raw[:10], errors="coerce")
    if pd.isna(parsed):
        return raw
    return parsed.strftime("%d/%m/%Y")


def _parse_market_datetime(value: Any) -> datetime | None:
    parsed = pd.to_datetime(str(value or "").strip(), errors="coerce")
    if pd.isna(parsed):
        return None
    try:
        return parsed.to_pydatetime().replace(tzinfo=None)
    except Exception:
        return None


def _age_minutes_from_now(value: Any) -> int | None:
    dt = _parse_market_datetime(value)
    if dt is None:
        return None
    delta = datetime.now() - dt
    try:
        return max(0, int(delta.total_seconds() // 60))
    except Exception:
        return None


def _format_age_label(minutes: int | None) -> str:
    if minutes is None:
        return "mai"
    if minutes < 60:
        return f"{minutes} min fa"
    hours = minutes // 60
    mins = minutes % 60
    if hours < 24:
        return f"{hours}h {mins:02d}m fa"
    days = hours // 24
    rem_hours = hours % 24
    return f"{days}g {rem_hours}h fa"


def _market_refresh_status(rows: list[dict[str, Any]], all_rows: list[dict[str, Any]]) -> dict[str, Any]:
    visible_total = len(rows)
    universe_total = len(all_rows)
    priced_count = sum(1 for row in rows if row.get("last_value") is not None)
    live_visible = sum(1 for row in rows if row.get("live"))
    open_count = sum(1 for row in rows if row.get("open"))
    live_ages = [
        _age_minutes_from_now(row.get("live_fetched_at"))
        for row in rows
        if row.get("live_fetched_at")
    ]
    live_ages = [age for age in live_ages if age is not None]
    latest_live_age = min(live_ages) if live_ages else None
    priced_ratio = priced_count / visible_total if visible_total else 0.0
    live_ratio = live_visible / visible_total if visible_total else 0.0

    tone = "green"
    title = "Dati freschi"
    action = "Aggiornamento non necessario."
    if visible_total == 0 or universe_total == 0 or priced_count == 0:
        tone = "red"
        title = "Aggiorna ora"
        action = "Nessun prezzo agganciato nella vista corrente."
    elif priced_ratio < 0.70:
        tone = "red"
        title = "Aggiorna ora"
        action = "Copertura prezzi troppo bassa."
    elif latest_live_age is None:
        tone = "yellow"
        title = "Aggiornamento consigliato"
        action = "Live non disponibile: premi Aggiorna mercati."
    elif (open_count > 0 and latest_live_age > 120) or latest_live_age > 24 * 60:
        tone = "red"
        title = "Aggiorna ora"
        action = "Dati live vecchi rispetto ai mercati aperti."
    elif priced_ratio < 0.95 or live_ratio < 0.60 or (open_count > 0 and latest_live_age > 45) or latest_live_age > 6 * 60:
        tone = "yellow"
        title = "Aggiornamento consigliato"
        action = "Dati leggibili, ma non completamente freschi."

    palette = {
        "green": (COLORS["success"], "#ecfdf5", "#bbf7d0"),
        "yellow": (COLORS["warning"], "#fffbeb", "#fde68a"),
        "red": (COLORS["danger"], "#fef2f2", "#fecaca"),
    }
    color, bg, border = palette[tone]
    return {
        "tone": tone,
        "color": color,
        "bg": bg,
        "border": border,
        "title": title,
        "action": action,
        "age_label": _format_age_label(latest_live_age),
        "priced_count": priced_count,
        "visible_total": visible_total,
        "live_visible": live_visible,
        "open_count": open_count,
    }


def _render_market_refresh_status(status: dict[str, Any]) -> None:
    _render_html_block(
        f"""
        <style>
        .market-refresh-status{{
            display:flex;
            align-items:center;
            gap:8px;
            margin:5px 0 2px 0;
            padding:7px 9px;
            border:1px solid {status["border"]};
            border-radius:8px;
            background:{status["bg"]};
            color:#334155;
            font-size:12.4px;
            line-height:1.25;
        }}
        .market-refresh-dot{{width:10px;height:10px;min-width:10px;border-radius:999px;background:{status["color"]};box-shadow:0 0 0 3px color-mix(in srgb,{status["color"]} 14%,transparent);}}
        .market-refresh-status b{{color:{status["color"]};font-weight:750;}}
        .market-refresh-status span{{font-weight:500;}}
        </style>
        <div class="market-refresh-status">
          <i class="market-refresh-dot"></i>
          <span><b>{html.escape(str(status["title"]))}</b> · ultimo live {html.escape(str(status["age_label"]))} · prezzi {int(status["priced_count"])}/{int(status["visible_total"])} · live {int(status["live_visible"])}/{int(status["visible_total"])} · {html.escape(str(status["action"]))}</span>
        </div>
        """
    )


def build_market_overview_rows(data: dict | None) -> list[dict[str, Any]]:
    status_items = build_market_tape_items(data)
    status_by_label = {str(item.get("label")): item for item in status_items}
    rows: list[dict[str, Any]] = []
    for item in MARKET_UNIVERSE_ITEMS:
        label = str(item["label"])
        aliases = tuple(item["aliases"])
        ticker_used, series = _series_from_benchmark_data(data, aliases)
        live_ticker, live_quote = _live_quote_from_data(data, aliases)
        status = status_by_label.get(label)
        if not status:
            is_open, local_now = _market_is_open(item)
            status = {"open": is_open, "local_time": local_now.strftime("%H:%M")}
        last_value = _finite_float(series.iloc[-1]) if not series.empty else None
        last_date = str(series.index[-1].date()) if not series.empty else ""
        day = _period_return(series, 1)
        live_price = _finite_float(live_quote.get("price")) if live_quote else None
        live_day = _finite_float(live_quote.get("pct")) if live_quote else None
        if live_price is not None:
            last_value = live_price
            last_date = str(live_quote.get("price_date") or last_date)
            ticker_used = live_ticker or ticker_used
        if live_day is not None:
            day = live_day
        ret_5d = _period_return(series, 5)
        ret_1m = _period_return(series, 21)
        ret_3m = _period_return(series, 63)
        ytd = _ytd_return(series)
        rows.append({
            "area": str(item.get("section") or "Altro"),
            "section": str(item.get("section") or "Altro"),
            "flag": item["flag"],
            "label": label,
            "ticker": ticker_used or item["ticker"],
            "priority": int(item.get("priority") or 9),
            "open": bool(status.get("open")),
            "local_time": str(status.get("local_time") or ""),
            "last_value": last_value,
            "last_date": last_date,
            "live": bool(live_quote),
            "live_price_date": str(live_quote.get("price_date") or "") if live_quote else "",
            "live_fetched_at": str(live_quote.get("fetched_at") or "") if live_quote else "",
            "day": day,
            "ret_5d": ret_5d,
            "ret_1m": ret_1m,
            "ret_3m": ret_3m,
            "ytd": ytd,
            "tone": _tone(day),
            "points": int(len(series)),
        })
    return sorted(rows, key=lambda row: (_section_rank(str(row.get("section") or "")), int(row.get("priority") or 9), str(row.get("label") or "")))


def _refresh_market_clock_fields(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggiorna solo stato aperto/chiuso e ora locale senza ricostruire i ritorni."""

    item_by_label = {str(item.get("label") or ""): item for item in MARKET_UNIVERSE_ITEMS}
    refreshed: list[dict[str, Any]] = []
    for row in rows or []:
        item = item_by_label.get(str(row.get("label") or ""))
        out = dict(row)
        if item:
            is_open, local_now = _market_is_open(item)
            out["open"] = bool(is_open)
            out["local_time"] = local_now.strftime("%H:%M")
        refreshed.append(out)
    return refreshed


def build_market_base100_frame(data: dict | None, *, observations: int = 90) -> pd.DataFrame:
    frames = []
    for item in MARKET_UNIVERSE_ITEMS:
        if int(item.get("priority") or 9) > 1:
            continue
        ticker_used, series = _series_from_benchmark_data(data, tuple(item["aliases"]))
        if series.empty:
            continue
        recent = series.tail(observations).copy()
        first = _finite_float(recent.iloc[0])
        if first is None or abs(first) < 1e-12:
            continue
        frame = pd.DataFrame({
            "Data": recent.index,
            "Indice": str(item["label"]),
            "Ticker": ticker_used or str(item["ticker"]),
            "Base 100": recent.astype(float) / first * 100.0,
        })
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["Data", "Indice", "Ticker", "Base 100"])
    return pd.concat(frames, ignore_index=True)


def _market_data_sig(data: dict[str, Any], ctx: SimpleNamespace) -> str:
    return build_market_data_signature(
        data,
        app_version=str(getattr(ctx, "app_version", "5.0-pre")),
        schema_version=str(getattr(ctx, "schema_version", "n/d")),
        include_benchmark_data=True,
    )


def _get_cached_market_overview_rows(data: dict[str, Any], ctx: SimpleNamespace) -> list[dict[str, Any]]:
    spec = get_cache_artifact_spec("mercati.overview_rows")
    market_sig = _market_data_sig(data, ctx)
    signature = build_cache_artifact_signature(
        spec.artifact_id,
        inputs={
            "market_data_signature": market_sig,
            "registry_items": len(MARKET_UNIVERSE_ITEMS),
        },
    )
    artifact = get_or_build_registered_artifact(
        artifact_id=spec.artifact_id,
        signature=signature,
        builder=lambda: build_market_overview_rows(data),
        clone_on_read=True,
        persist_disk=True,
        disk_codec="pickle",
    )
    return _refresh_market_clock_fields(artifact.value if isinstance(artifact.value, list) else [])


def _get_cached_market_base100_frame(data: dict[str, Any], ctx: SimpleNamespace, observations: int) -> pd.DataFrame:
    spec = get_cache_artifact_spec("mercati.base100_frame")
    market_sig = _market_data_sig(data, ctx)
    signature = build_cache_artifact_signature(
        spec.artifact_id,
        inputs={
            "market_data_signature": market_sig,
            "registry_items": len(MARKET_UNIVERSE_ITEMS),
            "observations": int(observations),
        },
    )
    artifact = get_or_build_registered_artifact(
        artifact_id=spec.artifact_id,
        signature=signature,
        builder=lambda: build_market_base100_frame(data, observations=observations),
        clone_on_read=True,
        persist_disk=True,
        disk_codec="pickle",
    )
    frame = artifact.value
    return frame if isinstance(frame, pd.DataFrame) else pd.DataFrame(columns=["Data", "Indice", "Ticker", "Base 100"])


def _avg_return(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [_finite_float(row.get(key)) for row in rows]
    values = [value for value in values if value is not None]
    if not values:
        return None
    return float(sum(values) / len(values))


def _positive_share(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [_finite_float(row.get(key)) for row in rows]
    values = [value for value in values if value is not None]
    if not values:
        return None
    return float(sum(1 for value in values if value > 0) / len(values))


def _core_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    core = [row for row in rows if int(row.get("priority") or 9) <= 1]
    return core or rows


def filter_market_rows(rows: list[dict[str, Any]], mode: str = "Core") -> list[dict[str, Any]]:
    """Filtra l'universo visibile senza cambiare il dataset sottostante."""
    if str(mode or "Core").lower().startswith("completo"):
        return rows
    return _core_rows(rows)


def build_market_area_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    area_rows: list[dict[str, Any]] = []
    for area in MARKET_SECTION_ORDER:
        group = [row for row in rows if row.get("section") == area]
        if not group:
            continue
        area_rows.append({
            "area": area,
            "count": len(group),
            "open_count": sum(1 for row in group if row.get("open")),
            "day": _avg_return(group, "day"),
            "ret_5d": _avg_return(group, "ret_5d"),
            "ret_1m": _avg_return(group, "ret_1m"),
            "ret_3m": _avg_return(group, "ret_3m"),
            "ytd": _avg_return(group, "ytd"),
            "breadth_1m": _positive_share(group, "ret_1m"),
        })
    return area_rows


def build_market_regime(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Sintesi decisionale del contesto mercato.

    Punteggio 0-100 basato soprattutto su breadth 1m/5g: non e' una previsione,
    ma una lettura rapida di quanto il movimento sia diffuso tra gli indici.
    """
    regime_rows = _core_rows(rows)
    day_breadth = _positive_share(regime_rows, "day")
    five_breadth = _positive_share(regime_rows, "ret_5d")
    month_breadth = _positive_share(regime_rows, "ret_1m")
    avg_day = _avg_return(regime_rows, "day")
    avg_5d = _avg_return(regime_rows, "ret_5d")
    avg_1m = _avg_return(regime_rows, "ret_1m")
    available_scores = [
        (day_breadth, 0.20),
        (five_breadth, 0.30),
        (month_breadth, 0.50),
    ]
    used = [(float(value), weight) for value, weight in available_scores if value is not None]
    score = sum(value * weight for value, weight in used) / sum(weight for _, weight in used) if used else 0.0
    area_rows = build_market_area_rows(regime_rows)
    leader = max((row for row in area_rows if row.get("ret_1m") is not None), key=lambda row: float(row["ret_1m"]), default=None)
    laggard = min((row for row in area_rows if row.get("ret_1m") is not None), key=lambda row: float(row["ret_1m"]), default=None)
    best = max((row for row in regime_rows if row.get("ret_1m") is not None), key=lambda row: float(row["ret_1m"]), default=None)
    worst = min((row for row in regime_rows if row.get("ret_1m") is not None), key=lambda row: float(row["ret_1m"]), default=None)
    if score >= 0.66 and (avg_1m is None or avg_1m >= 0):
        verdict = "Risk-on"
        action = "Contesto favorevole a incrementi graduali sugli asset rischiosi, privilegiando strumenti gia' coerenti con il target."
    elif score <= 0.34 and (avg_1m is None or avg_1m <= 0):
        verdict = "Risk-off"
        action = "Contesto fragile: meglio evitare rincorse aggressive e usare SATOR soprattutto per riequilibrio e disciplina."
    else:
        verdict = "Neutrale"
        action = "Segnale misto: conviene dare piu' peso a target, qualita' dati e prezzo relativo del singolo strumento."
    return {
        "verdict": verdict,
        "score": score,
        "day_breadth": day_breadth,
        "five_breadth": five_breadth,
        "month_breadth": month_breadth,
        "avg_day": avg_day,
        "avg_5d": avg_5d,
        "avg_1m": avg_1m,
        "leader_area": leader,
        "laggard_area": laggard,
        "best_index": best,
        "worst_index": worst,
        "action": action,
    }


def _build_base100_figure(frame: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if frame is None or frame.empty:
        fig.update_layout(height=360)
        return fig
    palette = [
        P.get("blue", "#2563EB"),
        P.get("green", "#059669"),
        P.get("orange", "#F97316"),
        P.get("purple", "#7C3AED"),
        P.get("red", "#DC2626"),
        "#0F766E",
        "#64748B",
        "#CA8A04",
        "#0284C7",
    ]
    for idx, (label, group) in enumerate(frame.groupby("Indice", sort=False)):
        fig.add_trace(go.Scatter(
            x=group["Data"],
            y=group["Base 100"],
            mode="lines",
            name=str(label),
            line=dict(width=2.2, color=palette[idx % len(palette)]),
            hovertemplate="%{fullData.name}<br>%{x|%d/%m/%Y}<br>Base 100: %{y:.2f}<extra></extra>",
        ))
    fig.add_hline(y=100, line_width=1, line_dash="dot", line_color="rgba(15,23,42,.35)")
    fig.update_layout(
        height=390,
        margin=dict(l=12, r=12, t=18, b=12),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis_title="",
        yaxis_title="Base 100",
        hovermode="x unified",
    )
    return fig


def _build_returns_heatmap_figure(rows: list[dict[str, Any]]) -> go.Figure:
    columns = [("day", "1g"), ("ret_5d", "5g"), ("ret_1m", "1m"), ("ret_3m", "3m"), ("ytd", "YTD")]
    labels = [_heatmap_label(row) for row in rows]
    z = []
    text = []
    for row in rows:
        z_row = []
        text_row = []
        for key, _label in columns:
            value = _finite_float(row.get(key))
            z_row.append(value * 100.0 if value is not None else None)
            text_row.append(_format_heatmap_pct_cell(value) if value is not None else "n/d")
        z.append(z_row)
        text.append(text_row)
    fig = go.Figure(data=go.Heatmap(
        z=z,
        x=[label for _key, label in columns],
        y=labels,
        text=text,
        texttemplate="%{text}",
        textfont=dict(size=13),
        customdata=[[str(row.get("label") or "")] * len(columns) for row in rows],
        hovertemplate="%{customdata}<br>%{x}: %{text}<extra></extra>",
        xgap=2,
        ygap=2,
        colorscale=[
            [0.0, "#dc2626"],
            [0.44, "#fee2e2"],
            [0.50, "#f8fafc"],
            [0.56, "#dcfce7"],
            [1.0, "#16a34a"],
        ],
        zmid=0,
        colorbar=dict(title=dict(text="%", font=dict(size=14)), thickness=13, tickfont=dict(size=14)),
    ))
    fig.update_layout(
        height=max(430, min(900, 42 * len(rows) + 110)),
        margin=dict(l=230, r=14, t=18, b=14),
        font=dict(size=17),
        xaxis_title="",
        yaxis_title="",
        yaxis=dict(
            autorange="reversed",
            showticklabels=True,
            tickfont=dict(size=19, color="#0f172a"),
            automargin=True,
        ),
        xaxis=dict(tickfont=dict(size=18), side="top"),
    )
    fig.update_traces(textfont=dict(size=13))
    return fig


def _build_area_strength_figure(area_rows: list[dict[str, Any]]) -> go.Figure:
    ordered = sorted(
        area_rows,
        key=lambda row: float(row["ret_1m"]) if row.get("ret_1m") is not None else -999.0,
        reverse=True,
    )
    fig = go.Figure()
    colors = [COLORS["success"] if (row.get("ret_1m") or 0.0) >= 0 else COLORS["danger"] for row in ordered]
    fig.add_trace(go.Bar(
        y=[row["area"] for row in ordered],
        x=[(row.get("ret_1m") or 0) * 100.0 for row in ordered],
        orientation="h",
        marker_color=colors,
        text=[_format_pct_cell(row.get("ret_1m")) for row in ordered],
        textfont=dict(size=12),
        textposition="auto",
        hovertemplate="%{y}<br>1m: %{text}<extra></extra>",
    ))
    fig.add_vline(x=0, line_width=1, line_color="rgba(15,23,42,.35)")
    fig.update_layout(
        height=max(300, 52 * len(ordered) + 84),
        margin=dict(l=170, r=14, t=14, b=14),
        xaxis_title="Rendimento medio 1m (%)",
        yaxis_title="",
        yaxis=dict(tickfont=dict(size=19), automargin=True),
        xaxis=dict(tickfont=dict(size=17), title=dict(font=dict(size=17))),
        showlegend=False,
    )
    return fig


def _heatmap_cell_colors(value: float | None) -> tuple[str, str, str]:
    if value is None:
        return "#f8fafc", "#64748b", "#e2e8f0"
    if abs(value) < 0.00005:
        return "#f8fafc", "#475569", "#e2e8f0"
    if value > 0:
        if value >= 0.02:
            return "#16a34a", "#ffffff", "#15803d"
        if value >= 0.005:
            return "#bbf7d0", "#166534", "#86efac"
        return "#dcfce7", "#166534", "#bbf7d0"
    if value <= -0.02:
        return "#dc2626", "#ffffff", "#b91c1c"
    if value <= -0.005:
        return "#fecaca", "#991b1b", "#fca5a5"
    return "#fee2e2", "#991b1b", "#fecaca"


def _relative_strength_cell(value: float | None) -> str:
    bg, color, border = _heatmap_cell_colors(value)
    text = _format_heatmap_pct_cell(value) if value is not None else "n/d"
    return (
        f'<div class="market-strength-cell" '
        f'style="background:{bg};color:{color};border-color:{border};">'
        f'{html.escape(text)}</div>'
    )


def _area_strength_bar_html(row: dict[str, Any], max_abs: float) -> str:
    value = _finite_float(row.get("ret_1m"))
    pct = 0.0 if value is None or max_abs <= 0 else min(abs(value) / max_abs, 1.0) * 50.0
    color = COLORS["success"] if (value or 0.0) >= 0 else COLORS["danger"]
    if value is None:
        fill_style = "left:50%;width:0%;background:#cbd5e1;"
    elif value >= 0:
        fill_style = f"left:50%;width:{pct:.1f}%;background:{color};"
    else:
        fill_style = f"left:{50.0 - pct:.1f}%;width:{pct:.1f}%;background:{color};"
    return (
        '<div class="market-area-row">'
        f'<div class="market-area-label">{html.escape(str(row.get("area") or ""))}</div>'
        '<div class="market-area-track"><span class="market-area-zero"></span>'
        f'<span class="market-area-fill" style="{fill_style}"></span></div>'
        f'<div class="market-area-value" style="color:{color};">{html.escape(_format_pct_cell(value))}</div>'
        '</div>'
    )


def _relative_strength_map_html(rows: list[dict[str, Any]], area_rows: list[dict[str, Any]]) -> str:
    columns = [("day", "1g"), ("ret_5d", "5g"), ("ret_1m", "1m"), ("ret_3m", "3m"), ("ytd", "YTD")]
    header_cells = "".join(f'<div class="market-strength-head">{html.escape(label)}</div>' for _key, label in columns)
    grid_rows: list[str] = [
        '<div class="market-strength-label market-strength-label-head">Indice</div>' + header_cells
    ]
    current_section = None
    for row in rows:
        section = str(row.get("section") or "")
        if section and section != current_section:
            current_section = section
            grid_rows.append(f'<div class="market-strength-section">{html.escape(section)}</div>')
        label = _heatmap_label(row)
        ticker = str(row.get("ticker") or "")
        grid_rows.append(
            '<div class="market-strength-label">'
            f'<span>{html.escape(label)}</span>'
            f'<small>{html.escape(ticker)}</small>'
            '</div>'
            + "".join(_relative_strength_cell(_finite_float(row.get(key))) for key, _label in columns)
        )

    area_values = [abs(v) for v in (_finite_float(row.get("ret_1m")) for row in area_rows) if v is not None]
    max_abs = max(area_values) if area_values else 0.01
    area_html = "".join(_area_strength_bar_html(row, max_abs) for row in area_rows)
    return f"""
    <style>
    .market-strength-shell{{display:flex;flex-direction:column;gap:10px;margin:2px 0 12px 0;}}
    .market-strength-grid{{
        display:grid;
        grid-template-columns:minmax(148px,1.38fr) repeat(5,minmax(48px,.44fr));
        gap:4px;
        align-items:stretch;
    }}
    .market-strength-head{{
        min-height:23px;
        display:flex;
        align-items:center;
        justify-content:center;
        border-radius:7px;
        background:#eef2f7;
        color:#334155;
        font-size:11.8px;
        font-weight:700;
        line-height:1;
    }}
    .market-strength-label-head{{justify-content:center;background:#eef2f7;color:#334155;font-size:11.8px;text-transform:uppercase;letter-spacing:.02em;}}
    .market-strength-section{{
        grid-column:1/-1;
        margin-top:4px;
        padding:4px 7px;
        border-radius:7px;
        background:#f8fafc;
        color:#0f172a;
        font-size:12.6px;
        line-height:1.1;
        font-weight:750;
        text-transform:uppercase;
        letter-spacing:.015em;
    }}
    .market-strength-label{{
        min-height:29px;
        display:flex;
        flex-direction:column;
        justify-content:center;
        gap:2px;
        padding:3px 7px;
        border:1px solid #e2e8f0;
        border-radius:7px;
        background:#fff;
        color:#0f172a;
        overflow:hidden;
    }}
    .market-strength-label span{{font-size:12.6px;font-weight:650;line-height:1.08;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
    .market-strength-label small{{font-size:9.5px;font-weight:500;color:#64748b;line-height:1;}}
    .market-strength-cell{{
        min-height:29px;
        display:flex;
        align-items:center;
        justify-content:center;
        border:1px solid;
        border-radius:7px;
        font-size:11.8px;
        line-height:1;
        font-weight:700;
        font-variant-numeric:tabular-nums;
    }}
    .market-area-strength{{
        display:flex;
        flex-direction:column;
        gap:5px;
        padding-top:2px;
    }}
    .market-area-title{{font-size:12.6px;font-weight:700;color:#0f172a;line-height:1.15;margin-bottom:1px;}}
    .market-area-row{{display:grid;grid-template-columns:minmax(142px,.92fr) minmax(150px,1.4fr) 54px;gap:7px;align-items:center;}}
    .market-area-label{{font-size:12.6px;font-weight:650;color:#0f172a;line-height:1.1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
    .market-area-track{{position:relative;height:11px;border-radius:999px;background:#eef2f7;overflow:hidden;border:1px solid #e2e8f0;}}
    .market-area-zero{{position:absolute;left:50%;top:0;bottom:0;width:1px;background:rgba(15,23,42,.35);}}
    .market-area-fill{{position:absolute;top:0;bottom:0;border-radius:999px;}}
    .market-area-value{{font-size:11.8px;font-weight:700;text-align:right;font-variant-numeric:tabular-nums;}}
    @media(max-width:760px){{
        .market-strength-grid{{grid-template-columns:minmax(132px,1.3fr) repeat(5,minmax(44px,.44fr));gap:3px;}}
        .market-strength-label span,.market-strength-section,.market-area-label,.market-area-title{{font-size:12.2px;}}
        .market-strength-cell,.market-strength-head,.market-area-value{{font-size:11.6px;}}
        .market-area-row{{grid-template-columns:minmax(118px,.9fr) minmax(102px,1fr) 54px;gap:6px;}}
    }}
    </style>
    <div class="market-strength-shell">
      <div class="market-strength-grid">{"".join(grid_rows)}</div>
      <div class="market-area-strength">
        <div class="market-area-title">Forza per area - rendimento medio 1m</div>
        {area_html or '<div class="market-area-label">Dati insufficienti</div>'}
      </div>
    </div>
    """


def _render_relative_strength_map(rows: list[dict[str, Any]], area_rows: list[dict[str, Any]]) -> None:
    _render_html_block(_relative_strength_map_html(rows, area_rows))


def _format_pct_cell(value: float | None) -> str:
    return fmt_pct_it(value, 2, signed=True) if value is not None else "n/d"


def _format_heatmap_pct_cell(value: float | None) -> str:
    return fmt_pct_it(value, 1, signed=True) if value is not None else "n/d"


def _heatmap_label(row: dict[str, Any]) -> str:
    label = str(row.get("label") or "")
    replacements = {
        "Emerging Markets": "EM",
        "Euro Stoxx 50": "EuroStoxx 50",
        "STOXX Europe 600": "STOXX 600",
        "Shanghai Composite": "Shanghai",
        "Treasury 20+ ETF": "Treasury 20+",
        "Euro Gov Bond": "Euro Gov",
        "Dollar Index": "DXY",
    }
    return f"{row.get('flag', '')} {replacements.get(label, label)}".strip()


def _market_row_source(row: dict[str, Any]) -> str:
    return "Live" if row.get("live") else "Storico"


def _pct_tone_from_text(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("+"):
        return "up"
    if text.startswith("-"):
        return "down"
    return "flat"


def _style_market_table(dataframe: pd.DataFrame) -> pd.DataFrame:
    styles = pd.DataFrame("", index=dataframe.index, columns=dataframe.columns)
    perf_cols = [col for col in ("1g", "Var gg", "5g", "1m", "YTD") if col in dataframe.columns]
    for idx, row in dataframe.iterrows():
        for col in perf_cols:
            tone = _pct_tone_from_text(row.get(col))
            if str(row.get(col) or "").lower() == "n/d":
                styles.loc[idx, col] = "color:#94a3b8;background:#f8fafc;font-weight:700;"
            elif tone == "up":
                styles.loc[idx, col] = "color:#047857;background:#ecfdf5;font-weight:800;"
            elif tone == "down":
                styles.loc[idx, col] = "color:#b91c1c;background:#fef2f2;font-weight:800;"
            else:
                styles.loc[idx, col] = "color:#64748b;background:#f8fafc;font-weight:700;"
        if "Fonte" in dataframe.columns:
            styles.loc[idx, "Fonte"] = (
                "color:#1d4ed8;background:#eff6ff;font-weight:800;"
                if str(row.get("Fonte") or "") == "Live"
                else "color:#475569;background:#f1f5f9;font-weight:800;"
            )
        if "Stato" in dataframe.columns:
            styles.loc[idx, "Stato"] = (
                "color:#047857;background:#ecfdf5;font-weight:800;"
                if str(row.get("Stato") or "") == "Aperto"
                else "color:#b91c1c;background:#fef2f2;font-weight:800;"
            )
        if "Prio" in dataframe.columns:
            styles.loc[idx, "Prio"] = (
                "color:#1d4ed8;background:#eff6ff;font-weight:800;"
                if str(row.get("Prio") or "") == "Core"
                else "color:#64748b;background:#f8fafc;font-weight:700;"
            )
    return styles


def _market_table_column_width_styles(display: pd.DataFrame) -> list[dict[str, Any]]:
    detailed_widths = {
        "Sez": "11%",
        "Indice": "22%",
        "Tk": "8%",
        "Prio": "6%",
        "Stato": "7%",
        "Ora": "5%",
        "Ultimo": "8%",
        "1g": "5%",
        "5g": "5%",
        "1m": "5%",
        "YTD": "6%",
        "Fonte": "6%",
        "Data": "6%",
    }
    section_widths = {
        "Indice": "28%",
        "Tk": "12%",
        "Stato": "10%",
        "Ultimo": "12%",
        "1g": "8%",
        "5g": "8%",
        "1m": "8%",
        "YTD": "8%",
        "Fonte": "6%",
    }
    widths = detailed_widths if "Sez" in display.columns else section_widths
    styles: list[dict[str, Any]] = []
    for idx, column in enumerate(display.columns):
        width = widths.get(str(column))
        if width:
            styles.append({
                "selector": f"th.col{idx}, td.col{idx}",
                "props": [("width", width), ("max-width", width)],
            })
    return styles


def _market_table_styler(display: pd.DataFrame):
    numeric_cols = [col for col in ("Ultimo", "1g", "5g", "1m", "YTD") if col in display.columns]
    meta_cols = [col for col in ("Tk", "Prio", "Stato", "Ora", "Fonte", "Data") if col in display.columns]
    styler = (
        display.style
        .apply(_style_market_table, axis=None)
        .set_properties(**{
            "font-size": "13px",
            "line-height": "1.18",
            "padding": "4px 5px",
            "white-space": "normal",
            "overflow-wrap": "anywhere",
        })
        .set_properties(subset=["Indice"], **{
            "text-align": "left",
            "white-space": "normal",
            "overflow-wrap": "break-word",
        })
        .set_properties(subset=numeric_cols, **{
            "text-align": "right",
            "white-space": "nowrap",
            "font-variant-numeric": "tabular-nums",
        })
        .set_properties(subset=meta_cols, **{
            "font-size": "12.8px",
            "white-space": "nowrap",
            "overflow": "hidden",
            "text-overflow": "ellipsis",
        })
        .set_table_styles([
            {"selector": "table", "props": [
                ("width", "100%"),
                ("max-width", "100%"),
                ("table-layout", "fixed"),
                ("border-collapse", "collapse"),
            ]},
            {"selector": "th", "props": [
                ("font-size", "12.5px"),
                ("font-weight", "750"),
                ("color", "#475569"),
                ("background", "#f8fafc"),
                ("padding", "5px 5px"),
                ("white-space", "nowrap"),
                ("overflow", "hidden"),
                ("text-overflow", "ellipsis"),
            ]},
            {"selector": "td", "props": [
                ("border-bottom", "1px solid #e2e8f0"),
                ("vertical-align", "middle"),
            ]},
            *_market_table_column_width_styles(display),
        ], overwrite=False)
    )
    try:
        return styler.hide(axis="index")
    except Exception:
        return styler


def _render_html_block(markup: str) -> None:
    """Render HTML puro senza passare dal parser Markdown quando possibile."""
    if hasattr(st, "html"):
        st.html(markup)
    else:
        st.markdown(markup, unsafe_allow_html=True)


def _render_market_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        st.info("Nessun dato mercato disponibile nello storico benchmark.")
        return
    display = pd.DataFrame([{
        "Sez": row["section"],
        "Indice": f"{row['flag']} {row['label']}",
        "Tk": row["ticker"],
        "Prio": "Core" if int(row.get("priority") or 9) <= 1 else "Esteso",
        "Stato": "Aperto" if row["open"] else "Chiuso",
        "Ora": row["local_time"] or "n/d",
        "Ultimo": fmt_num_it(row["last_value"], 2) if row["last_value"] is not None else "n/d",
        "1g": _format_pct_cell(row["day"]),
        "5g": _format_pct_cell(row["ret_5d"]),
        "1m": _format_pct_cell(row["ret_1m"]),
        "YTD": _format_pct_cell(row["ytd"]),
        "Fonte": _market_row_source(row),
        "Data": _format_date_it(row["last_date"]) or "n/d",
    } for row in rows])
    render_styled_table(
        _market_table_styler(display),
        height="content",
        static=True,
    )


def _section_table(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame([{
        "Indice": f"{row['flag']} {row['label']}",
        "Tk": row["ticker"],
        "Stato": "Aperto" if row["open"] else "Chiuso",
        "Ultimo": fmt_num_it(row["last_value"], 2) if row["last_value"] is not None else "n/d",
        "1g": _format_pct_cell(row["day"]),
        "5g": _format_pct_cell(row["ret_5d"]),
        "1m": _format_pct_cell(row["ret_1m"]),
        "YTD": _format_pct_cell(row["ytd"]),
        "Fonte": _market_row_source(row),
    } for row in rows])


def _render_section_overview(rows: list[dict[str, Any]]) -> None:
    area_rows = build_market_area_rows(rows)
    if not area_rows:
        return
    chips = []
    for row in area_rows:
        available = sum(1 for item in rows if item.get("section") == row["area"] and item.get("last_value") is not None)
        total = int(row.get("count") or 0)
        one_m = row.get("ret_1m")
        color = COLORS["success"] if (one_m or 0.0) >= 0 else COLORS["danger"]
        chips.append(
            f"""
            <div class="market-section-chip">
              <span>{html.escape(str(row["area"]))}</span>
              <b style="color:{color};">{_format_pct_cell(one_m)}</b>
              <small>{available}/{total} dati · {int(row.get("open_count") or 0)} aperti</small>
            </div>
            """
        )
    _render_html_block(
        """
        <style>
        .market-section-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:3px 0 12px 0;}
        .market-section-chip{border:1px solid rgba(15,23,42,.10);border-radius:8px;background:#fff;padding:8px 9px;min-height:62px;}
        .market-section-chip span{display:block;color:#475569;font-size:13px;font-weight:650;text-transform:uppercase;letter-spacing:.02em;line-height:1.14;}
        .market-section-chip b{display:block;margin-top:4px;font-size:.94rem;font-weight:700;font-variant-numeric:tabular-nums;}
        .market-section-chip small{display:block;margin-top:3px;color:#64748b;font-size:11.8px;font-weight:500;line-height:1.2;}
        @media(max-width:1100px){.market-section-grid{grid-template-columns:repeat(2,minmax(0,1fr));}}
        @media(max-width:720px){.market-section-grid{grid-template-columns:1fr;}}
        </style>
        <div class="market-section-grid">
        """ + "".join(chips) + "</div>"
    )


def _render_section_tables(rows: list[dict[str, Any]]) -> None:
    st.markdown(
        """
        <style>
        .market-section-label{margin:15px 0 7px 0;font-size:15px;font-weight:700;text-transform:uppercase;letter-spacing:.02em;color:#334155;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    for section in MARKET_SECTION_ORDER:
        group = [row for row in rows if row.get("section") == section]
        if not group:
            continue
        available = sum(1 for row in group if row.get("last_value") is not None)
        st.markdown(
            f"<div class='market-section-label'>{html.escape(section)} · {available}/{len(group)} con dati</div>",
            unsafe_allow_html=True,
        )
        section_df = _section_table(group)
        render_styled_table(
            _market_table_styler(section_df),
            height="content",
            static=True,
        )


def _render_market_refresh_controls(
    data: dict[str, Any],
    mode: str,
    rows: list[dict[str, Any]],
    all_rows: list[dict[str, Any]],
) -> None:
    selected_items = market_items_for_refresh(MARKET_UNIVERSE_ITEMS, mode)
    refresh_items = list(MARKET_UNIVERSE_ITEMS)
    left, right = st.columns([0.74, 0.26], vertical_alignment="center")
    with left:
        st.caption(
            f"Vista {mode}: {len(selected_items)} riferimenti mostrati. "
            f"Il tasto aggiorna tutto l'universo Mercati ({len(refresh_items)} riferimenti), non solo la vista corrente."
        )
        _render_market_refresh_status(_market_refresh_status(rows, all_rows))
    with right:
        if st.button(
            "Aggiorna mercati",
            key="mercati_refresh_button",
            width="stretch",
            help=(
                "Scarica manualmente quotazioni correnti e storici Yahoo per tutto l'universo Mercati. "
                "La vista Core/Completo cambia solo cosa viene mostrato a video."
            ),
        ):
            with st.spinner("Aggiornamento mercati in corso..."):
                live_report = refresh_market_universe_live_data(data, refresh_items)
                storico_report = refresh_market_universe_benchmark_data(
                    data,
                    refresh_items,
                    period=DEFAULT_MARKET_REFRESH_PERIOD,
                )
                report = {
                    "timestamp": live_report.get("timestamp") or storico_report.get("timestamp"),
                    "live": live_report,
                    "storico": storico_report,
                }
                save_benchmark_data(data)
                changed = [
                    item.get("ticker")
                    for item in (live_report.get("updated_items") or []) + (storico_report.get("updated_items") or [])
                    if item.get("changed")
                ]
                set_last_mutation_details({
                    "benchmarks_refreshed": True,
                    "market_live_refreshed": True,
                    "changed_tickers": changed,
                    "changed_count": len(changed),
                    "material_change": bool(changed),
                    "live_items": len(live_report.get("updated_items") or []),
                    "storico_items": len(storico_report.get("updated_items") or []),
                })
                record_cache_decision(
                    "rigenera mercati",
                    details={
                        "event_type": "market_refresh",
                        "benchmarks_refreshed": True,
                        "market_live_refreshed": True,
                        "changed_tickers": changed,
                        "changed_count": len(changed),
                        "material_change": bool(changed),
                        "live_items": len(live_report.get("updated_items") or []),
                        "storico_items": len(storico_report.get("updated_items") or []),
                    },
                    invalidated=False,
                    token=0,
                    force_reload=False,
                    scenario="market_refresh_isolated",
                    render_scope="full_tabs",
                    dirty_flags={},
                )
                st.session_state["_mercati_last_refresh_report"] = report
                st.session_state["_mercati_render_once"] = True
                queue_success(format_market_combined_refresh_report(report), icon="🔄")
                st.rerun()
    _render_last_market_refresh_report()


def _render_last_market_refresh_report() -> None:
    report = st.session_state.get("_mercati_last_refresh_report")
    if not isinstance(report, dict):
        return
    if isinstance(report.get("live"), dict) or isinstance(report.get("storico"), dict):
        live = report.get("live") if isinstance(report.get("live"), dict) else {}
        storico = report.get("storico") if isinstance(report.get("storico"), dict) else {}
        timestamp = str(report.get("timestamp") or live.get("timestamp") or storico.get("timestamp") or "")
        live_updated = int(live.get("updated") or 0)
        live_requested = int(live.get("requested") or 0)
        storico_recovered = int(storico.get("updated") or 0) + int(storico.get("unchanged") or 0)
        storico_requested = int(storico.get("requested") or 0)
        failed_live = live.get("failed") or []
        failed_storico = storico.get("failed") or []
        pieces = [
            f"ultimo refresh {timestamp}" if timestamp else "ultimo refresh",
            f"live {live_updated}/{live_requested}",
            f"storico {storico_recovered}/{storico_requested}",
        ]
        st.caption(" · ".join(pieces))
        failed = list(failed_live) + list(failed_storico)
        if failed:
            failed_labels = []
            for item in failed[:8]:
                label = str(item.get("label") or "n/d")
                aliases = ", ".join(str(alias) for alias in (item.get("aliases") or []) if str(alias).strip())
                failed_labels.append(f"{label} ({aliases})" if aliases else label)
            st.caption("Non disponibili: " + " · ".join(failed_labels))
        return
    timestamp = str(report.get("timestamp") or "")
    recovered = int(report.get("updated") or 0) + int(report.get("unchanged") or 0)
    requested = int(report.get("requested") or 0)
    failed = report.get("failed") or []
    pieces = [
        f"ultimo refresh {timestamp}" if timestamp else "ultimo refresh",
        f"{recovered}/{requested} serie recuperate",
        f"{int(report.get('updated') or 0)} aggiornate",
        f"{int(report.get('unchanged') or 0)} gia' allineate",
    ]
    st.caption(" · ".join(pieces))
    if failed:
        failed_labels = []
        for item in failed[:8]:
            label = str(item.get("label") or "n/d")
            aliases = ", ".join(str(alias) for alias in (item.get("aliases") or []) if str(alias).strip())
            failed_labels.append(f"{label} ({aliases})" if aliases else label)
        suffix = "" if len(failed) <= 8 else f" e altri {len(failed) - 8}"
        st.warning("Non recuperati: " + "; ".join(failed_labels) + suffix + ".")


def _bar_html(label: str, value: float | None, color: str) -> str:
    pct = max(0.0, min(float(value or 0.0) * 100.0, 100.0))
    return (
        f'<div class="mcc-bar-row"><span>{html.escape(label)}</span>'
        f'<b>{fmt_pct_it(value, 0) if value is not None else "n/d"}</b></div>'
        f'<div class="mcc-bar"><span style="width:{pct:.1f}%;background:{color};"></span></div>'
    )


def _idx_label(row: dict[str, Any] | None, key: str = "ret_1m") -> str:
    if not row:
        return "n/d"
    return f"{row.get('label') or row.get('area')} {_format_pct_cell(row.get(key))}"


def _render_market_pulse(rows: list[dict[str, Any]]) -> None:
    open_count = sum(1 for row in rows if row.get("open"))
    available_count = sum(1 for row in rows if row.get("last_value") is not None)
    regime = build_market_regime(rows)
    verdict = str(regime["verdict"])
    color = COLORS["success"] if verdict == "Risk-on" else (COLORS["danger"] if verdict == "Risk-off" else P.get("blue", "#2563EB"))
    leader_area = regime.get("leader_area") or {}
    laggard_area = regime.get("laggard_area") or {}
    best = regime.get("best_index")
    worst = regime.get("worst_index")
    score = float(regime.get("score") or 0.0)
    _render_html_block(
        f"""
        <style>
        .mcc-shell{{display:grid;grid-template-columns:1.08fr .92fr;gap:10px;margin:2px 0 12px 0;}}
        .mcc-panel{{border:1px solid rgba(15,23,42,.10);border-radius:8px;background:#fff;padding:11px 12px;box-shadow:0 1px 2px rgba(15,23,42,.035);}}
        .mcc-verdict{{display:flex;align-items:center;gap:9px;margin-bottom:7px;}}
        .mcc-dot{{width:10px;height:10px;border-radius:999px;background:{color};box-shadow:0 0 0 3px color-mix(in srgb,{color} 12%,transparent);}}
        .mcc-kicker{{font-size:10.5px;text-transform:uppercase;letter-spacing:.045em;color:#64748b;font-weight:850;}}
        .mcc-title{{font-size:1.16rem;line-height:1.05;font-weight:900;color:{color};}}
        .mcc-action{{color:#334155;font-size:13px;line-height:1.35;margin-top:4px;}}
        .mcc-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-top:9px;}}
        .mcc-mini{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:7px;padding:7px 8px;min-height:54px;}}
        .mcc-mini span{{display:block;color:#64748b;font-size:10.5px;font-weight:850;text-transform:uppercase;letter-spacing:.035em;}}
        .mcc-mini b{{display:block;margin-top:4px;color:#0f172a;font-size:13px;line-height:1.2;}}
        .mcc-side{{display:flex;flex-direction:column;gap:7px;}}
        .mcc-bar-row{{display:flex;align-items:center;justify-content:space-between;color:#475569;font-size:12px;font-weight:800;margin-top:4px;}}
        .mcc-bar{{height:7px;background:#e5e7eb;border-radius:999px;overflow:hidden;margin:3px 0 6px;}}
        .mcc-bar span{{display:block;height:100%;border-radius:999px;}}
        @media(max-width:900px){{.mcc-shell{{grid-template-columns:1fr;}}.mcc-grid{{grid-template-columns:1fr;}}}}
        </style>
        <div class="mcc-shell">
          <div class="mcc-panel">
            <div class="mcc-verdict">
              <span class="mcc-dot"></span>
              <div>
                <div class="mcc-kicker">Regime di mercato</div>
                <div class="mcc-title">{html.escape(verdict)} · {fmt_pct_it(score, 0)}</div>
              </div>
            </div>
            <div class="mcc-action">{html.escape(str(regime.get("action") or ""))}</div>
            <div class="mcc-grid">
              <div class="mcc-mini"><span>Leadership area</span><b>{html.escape(str(leader_area.get("area") or "n/d"))} {_format_pct_cell(leader_area.get("ret_1m"))}</b></div>
              <div class="mcc-mini"><span>Migliore indice 1m</span><b>{html.escape(_idx_label(best, "ret_1m"))}</b></div>
              <div class="mcc-mini"><span>Fragilita' 1m</span><b>{html.escape(_idx_label(worst, "ret_1m"))}</b></div>
            </div>
          </div>
          <div class="mcc-panel mcc-side">
            <div class="mcc-kicker">Ampiezza del movimento</div>
            {_bar_html("Oggi", regime.get("day_breadth"), P.get("blue", "#2563EB"))}
            {_bar_html("5 giorni", regime.get("five_breadth"), P.get("orange", "#F97316"))}
            {_bar_html("1 mese", regime.get("month_breadth"), color)}
            <div class="mcc-mini"><span>Copertura dati</span><b>{available_count}/{len(rows)} indici · {open_count} aperti ora</b></div>
          </div>
        </div>
        """
    )


def _render_mercati_lazy_placeholder(data: dict[str, Any], cache_diag: dict[str, int]) -> bool:
    """Schermata leggera: la pagina Mercati viene costruita solo su richiesta.

    Streamlit renderizza tutte le tab native a ogni rerun. Mercati e' una pagina
    opzionale e ricca di grafici: tenerla dietro un pulsante evita che pesi su
    avvio, refresh quotazioni e salvataggi non collegati ai mercati.
    """
    benchmark_count, live_count = _market_cache_counts(data)
    last_generated = st.session_state.get("_mercati_last_generated_at")
    generated_label = str(last_generated or "mai in questa sessione")
    _render_html_block(
        f"""
        <style>
        .market-lazy-shell{{
            border:1px solid rgba(15,23,42,.10);
            border-radius:10px;
            background:linear-gradient(135deg,#ffffff 0%,#f8fafc 100%);
            padding:14px 15px;
            margin:4px 0 12px 0;
            box-shadow:0 1px 2px rgba(15,23,42,.035);
        }}
        .market-lazy-title{{
            display:flex;
            align-items:center;
            gap:9px;
            color:#0f172a;
            font-size:1.02rem;
            font-weight:780;
            line-height:1.18;
            margin-bottom:7px;
        }}
        .market-lazy-dot{{
            width:10px;
            height:10px;
            border-radius:999px;
            background:{P.get("blue", "#2563EB")};
            box-shadow:0 0 0 3px color-mix(in srgb,{P.get("blue", "#2563EB")} 13%,transparent);
        }}
        .market-lazy-text{{
            color:#475569;
            font-size:13.2px;
            line-height:1.42;
            margin-bottom:10px;
        }}
        .market-lazy-grid{{
            display:grid;
            grid-template-columns:repeat(4,minmax(0,1fr));
            gap:8px;
        }}
        .market-lazy-kpi{{
            border:1px solid #e2e8f0;
            border-radius:8px;
            background:#fff;
            padding:8px 9px;
            min-height:54px;
        }}
        .market-lazy-kpi span{{
            display:block;
            color:#64748b;
            font-size:10.8px;
            font-weight:750;
            text-transform:uppercase;
            letter-spacing:.025em;
        }}
        .market-lazy-kpi b{{
            display:block;
            margin-top:4px;
            color:#0f172a;
            font-size:13.4px;
            font-weight:760;
            line-height:1.2;
        }}
        @media(max-width:900px){{.market-lazy-grid{{grid-template-columns:repeat(2,minmax(0,1fr));}}}}
        @media(max-width:620px){{.market-lazy-grid{{grid-template-columns:1fr;}}}}
        </style>
        <div class="market-lazy-shell">
          <div class="market-lazy-title"><span class="market-lazy-dot"></span><span>Mercati in modalita' on demand</span></div>
          <div class="market-lazy-text">
            Questa sezione e' opzionale e non viene ricostruita automaticamente durante avvio, refresh prezzi o salvataggi.
            Premi <b>Rigenera Mercati</b> solo quando vuoi consultare radar, mappe, tabelle e confronto base 100.
          </div>
          <div class="market-lazy-grid">
            <div class="market-lazy-kpi"><span>Registry</span><b>{len(MARKET_UNIVERSE_ITEMS)} riferimenti</b></div>
            <div class="market-lazy-kpi"><span>Storico cache</span><b>{benchmark_count} serie</b></div>
            <div class="market-lazy-kpi"><span>Live cache</span><b>{live_count} quote</b></div>
            <div class="market-lazy-kpi"><span>Ultima rigenerazione</span><b>{html.escape(generated_label)}</b></div>
          </div>
        </div>
        """
    )
    st.caption(
        f"Cache letta: ctx {cache_diag['ctx_benchmark']}/{cache_diag['ctx_live']} · "
        f"file {cache_diag['disk_benchmark']}/{cache_diag['disk_live']}. "
        "La striscia mercati del Portafoglio continua a usare la cache gia' disponibile."
    )
    regenerate = bool(st.button(
        "Rigenera Mercati",
        key="mercati_regenerate_page",
        width="stretch",
        help="Costruisce ora la pagina completa Mercati. Il blocco resta occasionale e non pesa sui prossimi rerun.",
    ))
    back_to_top(show_prev=True, show_next=True, nav_key="mercati")
    return regenerate


def render_mercati(tab: DeltaGenerator, ctx: SimpleNamespace) -> None:
    with tab:
        settings = getattr(ctx, "settings", {}) or {}
        theme = get_theme_context()
        render_page_intro_shared(
            t(settings, "tab.markets", "Mercati"),
            t(
                settings,
                "page_intro.mercati.comment",
                "Radar dei principali indici internazionali: andamento, stato dei mercati e confronto base 100 sui dati benchmark disponibili.",
            ),
            "analysis",
            theme,
        )

        data, cache_diag = _merge_disk_market_cache(getattr(ctx, "data", {}) or {})
        render_requested = bool(st.session_state.pop("_mercati_render_once", False))
        if not render_requested:
            render_requested = _render_mercati_lazy_placeholder(data, cache_diag)
        if not render_requested:
            return

        st.session_state["_mercati_last_generated_at"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        with profile_step("Mercati", "load/build overview rows"):
            all_rows = _get_cached_market_overview_rows(data, ctx)
        market_mode = st.segmented_control(
            "Universo",
            options=["Core", "Completo"],
            default="Core",
            key="mercati_universo_mode",
            help="Core mostra solo i riferimenti decisionali principali. Completo include anche proxy e indici di secondo livello.",
        )
        rows = filter_market_rows(all_rows, str(market_mode or "Core"))
        _render_market_refresh_controls(data, str(market_mode or "Core"), rows, all_rows)
        benchmark_count, live_count = _market_cache_counts(data)
        priced_count = sum(1 for row in rows if row.get("last_value") is not None)
        st.caption(
            f"{len(rows)} strumenti mostrati su {len(all_rows)} disponibili nella registry · "
            f"dati letti: {priced_count}/{len(rows)} prezzi, {benchmark_count} serie storiche, {live_count} live · "
            f"ctx {cache_diag['ctx_benchmark']}/{cache_diag['ctx_live']} · file {cache_diag['disk_benchmark']}/{cache_diag['disk_live']}."
        )
        if rows and priced_count == 0 and (benchmark_count or live_count):
            st.warning(
                "La cache Mercati contiene dati, ma nessun alias della vista corrente e' stato agganciato. "
                "Controlla il report di aggiornamento: potrebbe esserci un disallineamento tra ticker salvati e registry Mercati.",
                icon="⚠️",
            )
        with profile_step("Mercati", "render market pulse", count=len(rows)):
            _render_market_pulse(rows)
        with profile_step("Mercati", "render section overview", count=len(rows)):
            _render_section_overview(rows)

        render_section_title(
            "Mappa forza relativa",
            comment="Heatmap dei principali orizzonti: aiuta a distinguere un rimbalzo giornaliero isolato da una forza piu' persistente su 5 giorni, 1 mese, 3 mesi e da inizio anno.",
            icon="risk",
        )
        area_rows = build_market_area_rows(rows)
        if rows:
            _render_relative_strength_map(rows, area_rows)
        else:
            st.info("Dati insufficienti per costruire la forza relativa per area.")

        render_section_title(
            "Sezioni mercato",
            comment="Le sezioni sono divise per funzione: azionario, tassi, materie prime, valute e rischio. La vista Core evita rumore; Completo serve per approfondire.",
            icon="data",
        )
        _render_section_tables(rows)

        render_section_title(
            "Andamento comparato",
            comment="Base 100 sugli ultimi dati disponibili: serve per confrontare direzione e forza relativa degli indici, non per leggere valori assoluti.",
            icon="analysis",
        )
        period = st.segmented_control(
            "Periodo",
            options=["1m", "3m", "6m"],
            default="3m",
            key="mercati_periodo_base100",
        )
        observations = {"1m": 23, "3m": 66, "6m": 132}.get(str(period), 66)
        with profile_step("Mercati", "load/build base100 frame", count=observations):
            frame = _get_cached_market_base100_frame(data, ctx, observations)
        if frame.empty:
            st.info("Storico benchmark insufficiente per costruire il confronto base 100.")
        else:
            st.plotly_chart(_build_base100_figure(frame), width="stretch")

        render_section_title(
            "Tabella mercato",
            comment="La tabella usa la cache benchmark gia' caricata dall'app: gli strumenti senza storico restano n/d finche' non vengono alimentati dai dati mercato.",
            icon="quotes",
        )
        _render_market_table(rows)
        legend_block(
            "Lettura operativa: questa pagina non deve decidere al posto di SATOR, ma deve dargli contesto. Il prossimo passo sensato e' usare regime, leadership e breadth come fattori di timing nelle proposte di acquisto.",
            variant="bottom",
        )
        back_to_top(show_prev=True, show_next=True, nav_key="mercati")
