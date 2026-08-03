"""Striscia informativa mercati per la Home.

Non effettua chiamate rete: legge market_live_data/benchmark_data gia'
caricati in memoria e usa gli orari locali per indicare se il proxy e' aperto.
"""
from __future__ import annotations

import html
import math
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from core.config import COLORS
from core.data_models import ThemeConfig
from ui.formatting import fmt_pct_it
from ui.market_universe import MARKET_TAPE_ITEMS


def _finite_float(value) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _market_is_open(item: dict, now_utc: datetime | None = None) -> tuple[bool, datetime]:
    tz = ZoneInfo(str(item["tz"]))
    now = (now_utc or datetime.now(ZoneInfo("UTC"))).astimezone(tz)
    if now.weekday() >= 5:
        return False, now
    return bool(item["open"] <= now.time() <= item["close"]), now


def _latest_cached_return(benchmark_data: dict, aliases: tuple[str, ...]) -> dict[str, object] | None:
    if not isinstance(benchmark_data, dict):
        return None
    raw = None
    ticker_used = ""
    for ticker in aliases:
        maybe = benchmark_data.get(f"bench_{ticker}")
        if isinstance(maybe, dict) and maybe:
            raw = maybe
            ticker_used = ticker
            break
    if not isinstance(raw, dict):
        return None

    points: list[tuple[str, float]] = []
    for date_key, value in raw.items():
        numeric = _finite_float(value)
        if numeric is not None and numeric > 0:
            points.append((str(date_key), numeric))
    points.sort(key=lambda pair: pair[0])
    if len(points) < 2:
        return None
    prev_date, prev_value = points[-2]
    last_date, last_value = points[-1]
    if abs(prev_value) < 1e-12:
        return None
    return {
        "ticker": ticker_used,
        "last_date": last_date,
        "prev_date": prev_date,
        "last_value": last_value,
        "pct": (last_value / prev_value) - 1.0,
    }


def _latest_live_return(live_data: dict, aliases: tuple[str, ...]) -> dict[str, object] | None:
    if not isinstance(live_data, dict):
        return None
    candidates: list[tuple[int, int, dict[str, object]]] = []
    for order, ticker in enumerate(aliases):
        maybe = live_data.get(f"live_{ticker}")
        if not isinstance(maybe, dict):
            continue
        price = _finite_float(maybe.get("price"))
        if price is None or price <= 0:
            continue
        try:
            freshness = int(maybe.get("regular_market_time") or 0)
        except (TypeError, ValueError, OverflowError):
            freshness = 0
        pct = _finite_float(maybe.get("pct"))
        candidates.append((freshness, -order, {
            "ticker": ticker,
            "last_date": str(maybe.get("price_date") or ""),
            "last_value": price,
            "pct": pct,
        }))
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


def _tone_for_pct(value: float | None) -> tuple[str, str]:
    if value is None or abs(value) < 0.00005:
        return COLORS.get("muted", "#6B7280"), "flat"
    if value > 0:
        return COLORS["success"], "up"
    return COLORS["danger"], "down"


def build_market_tape_items(data: dict | None, now_utc: datetime | None = None) -> list[dict[str, object]]:
    benchmark_data = (data or {}).get("benchmark_data", {})
    live_data = (data or {}).get("market_live_data", {})
    rows = []
    for item in MARKET_TAPE_ITEMS:
        is_open, local_now = _market_is_open(item, now_utc=now_utc)
        live = _latest_live_return(live_data, tuple(item["aliases"]))
        cached = _latest_cached_return(benchmark_data, tuple(item["aliases"]))
        source = live or cached
        pct = source.get("pct") if source else None
        color, tone = _tone_for_pct(_finite_float(pct))
        rows.append({
            "flag": item["flag"],
            "label": item["label"],
            "ticker": str(source.get("ticker") if source else item["ticker"]),
            "open": is_open,
            "local_time": local_now.strftime("%H:%M"),
            "pct": _finite_float(pct),
            "tone": tone,
            "color": color,
            "last_date": str(source.get("last_date") if source else ""),
            "source": "Live" if live else "Storico",
        })
    return sorted(rows, key=lambda row: (not bool(row["open"]), str(row["label"])))


def render_market_ticker_tape(data: dict | None, theme: ThemeConfig | None = None) -> None:
    items = build_market_tape_items(data)
    if not items:
        return

    theme = theme or ThemeConfig()
    surface = getattr(theme, "bg_surface", "#FFFFFF")
    surface_alt = getattr(theme, "bg_surface_alt", "#F8FAFC")
    border = getattr(theme, "border_color", "rgba(15,23,42,.12)")
    text = getattr(theme, "font_color", "#262730")
    muted = getattr(theme, "muted_color", "rgba(15,23,42,.58)")
    primary = getattr(theme, "primary_color", COLORS.get("info", "#2563EB"))
    chips = []
    for item in items:
        pct = item.get("pct")
        pct_text = fmt_pct_it(pct, 2, signed=True) if pct is not None else "n/d"
        status = "Aperto" if item["open"] else "Chiuso"
        open_cls = " is-open" if item["open"] else " is-closed"
        title = (
            f"{item['label']} ({item['ticker']}) - {status} alle {item['local_time']} locali. "
            f"Ultimo dato cache: {item['last_date'] or 'n/d'}."
        )
        chips.append(
            '<span class="market-tape__chip{open_cls}" title="{title}">'
            '<span class="market-tape__flag">{flag}</span>'
            '<span class="market-tape__name">{label}</span>'
            '<span class="market-tape__status">{status}</span>'
            '<span class="market-tape__pct" style="color:{color};">{pct}</span>'
            '</span>'.format(
                open_cls=open_cls,
                title=html.escape(title, quote=True),
                flag=item["flag"],
                label=html.escape(str(item["label"])),
                status=status,
                color=item["color"],
                pct=pct_text,
            )
        )
    track = "".join(chips)
    marquee_track = track + track
    html_block = f"""
    <style>
    .market-tape {{
      margin:-2px 0 10px 0;
      padding:7px 8px;
      border:1px solid {border};
      border-radius:10px;
      background:linear-gradient(180deg,{surface}, {surface_alt});
      overflow:hidden;
    }}
    .market-tape__track {{
      display:flex;
      align-items:center;
      gap:7px;
      width:max-content;
      min-width:100%;
      animation:marketTapeScroll 42s linear infinite;
      scrollbar-width:thin;
      padding-bottom:1px;
    }}
    .market-tape:hover .market-tape__track {{
      animation-play-state:paused;
    }}
    .market-tape__chip {{
      flex:0 0 auto;
      display:inline-flex;
      align-items:center;
      gap:6px;
      min-height:27px;
      padding:4px 8px;
      border-radius:999px;
      border:1px solid rgba(15,23,42,.09);
      background:rgba(255,255,255,.74);
      color:{text};
      font-size:12.5px;
      line-height:1;
      white-space:nowrap;
    }}
    .market-tape__chip.is-open {{
      border-color:{primary};
      box-shadow:inset 0 0 0 1px color-mix(in srgb, {primary} 25%, transparent);
      background:color-mix(in srgb, {primary} 7%, #fff);
    }}
    .market-tape__chip.is-closed {{
      border-color:color-mix(in srgb, {COLORS["danger"]} 34%, transparent);
      background:color-mix(in srgb, {COLORS["danger"]} 7%, #fff);
    }}
    .market-tape__chip.is-closed .market-tape__status {{
      color:{COLORS["danger"]};
      font-weight:800;
    }}
    .market-tape__flag {{font-size:14px;line-height:1;}}
    .market-tape__name {{font-weight:800;}}
    .market-tape__status {{
      color:{muted};
      font-size:11.5px;
      font-weight:700;
    }}
    .market-tape__pct {{
      font-variant-numeric:tabular-nums;
      font-weight:900;
    }}
    @keyframes marketTapeScroll {{
      from {{transform:translateX(0);}}
      to {{transform:translateX(-50%);}}
    }}
    @media (prefers-reduced-motion: reduce) {{
      .market-tape__track {{animation:none;overflow-x:auto;width:100%;}}
    }}
    </style>
    <div class="market-tape" aria-label="Andamento principali mercati">
      <div class="market-tape__track">{marquee_track}</div>
    </div>
    """
    st.markdown(html_block, unsafe_allow_html=True)
