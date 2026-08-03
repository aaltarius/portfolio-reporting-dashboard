"""Refresh manuale dell'universo Mercati.

Il modulo resta fuori da Streamlit: scarica gli storici benchmark richiesti,
li fonde con la cache esistente e ritorna un report sintetico per la UI.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Iterable

from core.market_data import get_yahoo_live_quote, get_yahoo_price_history_full


DEFAULT_MARKET_REFRESH_PERIOD = "6mo"


def _finite_positive(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(parsed) or parsed <= 0:
        return None
    return parsed


def _clean_history(history: Any) -> dict[str, float]:
    if not isinstance(history, dict):
        return {}
    cleaned: dict[str, float] = {}
    for date_key, value in history.items():
        date_str = str(date_key or "")[:10]
        if len(date_str) != 10:
            continue
        parsed = _finite_positive(value)
        if parsed is not None:
            cleaned[date_str] = parsed
    return dict(sorted(cleaned.items()))


def _clean_live_quote(quote: Any) -> dict[str, Any]:
    if not isinstance(quote, dict):
        return {}
    price = _finite_positive(quote.get("price"))
    if price is None:
        return {}
    previous_close = _finite_positive(quote.get("previous_close"))
    pct = None
    try:
        pct_value = float(quote.get("pct"))
        if math.isfinite(pct_value):
            pct = pct_value
    except (TypeError, ValueError, OverflowError):
        pct = None
    points = None
    try:
        points_value = float(quote.get("points"))
        if math.isfinite(points_value):
            points = points_value
    except (TypeError, ValueError, OverflowError):
        points = None
    return {
        "ticker": str(quote.get("ticker") or "").strip(),
        "price": price,
        "previous_close": previous_close,
        "pct": pct,
        "points": points,
        "price_date": str(quote.get("price_date") or ""),
        "regular_market_time": quote.get("regular_market_time"),
        "exchange_timezone": str(quote.get("exchange_timezone") or ""),
        "currency": str(quote.get("currency") or ""),
        "source": str(quote.get("source") or "yahoo_chart_live"),
    }


def market_items_for_refresh(items: Iterable[dict[str, Any]], mode: str = "Core") -> list[dict[str, Any]]:
    """Restituisce gli item da aggiornare in base alla vista scelta."""
    source = [item for item in items if isinstance(item, dict)]
    if str(mode or "Core").lower().startswith("completo"):
        return source
    return [item for item in source if int(item.get("priority") or 9) <= 1]


def refresh_market_universe_benchmark_data(
    data: dict[str, Any],
    items: Iterable[dict[str, Any]],
    *,
    period: str = DEFAULT_MARKET_REFRESH_PERIOD,
) -> dict[str, Any]:
    """Aggiorna la cache benchmark per gli indici Mercati richiesti.

    Per ogni indice prova gli alias in ordine. Se Yahoo non restituisce dati sul
    ticker principale, viene usato il primo proxy disponibile e la pagina sceglie
    poi la serie piu' recente tra gli alias.
    """
    payload = data if isinstance(data, dict) else {}
    benchmark_data = payload.setdefault("benchmark_data", {})
    if not isinstance(benchmark_data, dict):
        benchmark_data = {}
        payload["benchmark_data"] = benchmark_data

    report: dict[str, Any] = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "period": str(period or DEFAULT_MARKET_REFRESH_PERIOD),
        "requested": 0,
        "updated": 0,
        "unchanged": 0,
        "failed": [],
        "attempts": [],
        "updated_items": [],
    }

    for item in items:
        label = str(item.get("label") or item.get("ticker") or "").strip()
        aliases = tuple(str(alias).strip() for alias in (item.get("aliases") or ()) if str(alias).strip())
        if not aliases:
            report["failed"].append({"label": label or "n/d", "aliases": []})
            continue

        report["requested"] += 1
        item_updated = False
        for alias in aliases:
            history = _clean_history(get_yahoo_price_history_full(alias, period=report["period"]))
            if not history:
                report["attempts"].append({
                    "label": label or alias,
                    "ticker": alias,
                    "status": "no_data",
                    "points": 0,
                    "last_date": "",
                })
                continue

            key = f"bench_{alias}"
            existing = benchmark_data.get(key, {})
            existing = existing if isinstance(existing, dict) else {}
            merged = dict(existing)
            before = dict(merged)
            merged.update(history)
            merged = dict(sorted((str(k), float(v)) for k, v in merged.items()))
            benchmark_data[key] = merged

            if merged != before:
                report["updated"] += 1
                item_updated = True
                status = "updated"
            else:
                report["unchanged"] += 1
                status = "unchanged"
            attempt = {
                "label": label or alias,
                "ticker": alias,
                "status": status,
                "points": len(merged),
                "last_date": max(merged.keys(), default=""),
            }
            report["attempts"].append(attempt)
            report["updated_items"].append({
                "label": label or alias,
                "ticker": alias,
                "points": len(merged),
                "last_date": max(merged.keys(), default=""),
                "changed": item_updated,
            })
            break
        else:
            report["failed"].append({"label": label or aliases[0], "aliases": list(aliases)})

    return report


def refresh_market_universe_live_data(
    data: dict[str, Any],
    items: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Aggiorna le quotazioni correnti dell'universo Mercati."""
    payload = data if isinstance(data, dict) else {}
    live_data = payload.setdefault("market_live_data", {})
    if not isinstance(live_data, dict):
        live_data = {}
        payload["market_live_data"] = live_data

    report: dict[str, Any] = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "requested": 0,
        "updated": 0,
        "failed": [],
        "attempts": [],
        "updated_items": [],
    }

    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for item in items:
        label = str(item.get("label") or item.get("ticker") or "").strip()
        aliases = tuple(str(alias).strip() for alias in (item.get("aliases") or ()) if str(alias).strip())
        if not aliases:
            report["failed"].append({"label": label or "n/d", "aliases": []})
            continue

        report["requested"] += 1
        for alias in aliases:
            quote = _clean_live_quote(get_yahoo_live_quote(alias))
            if not quote:
                report["attempts"].append({
                    "label": label or alias,
                    "ticker": alias,
                    "status": "no_live_data",
                    "price": None,
                    "pct": None,
                })
                continue

            key = f"live_{alias}"
            existing = live_data.get(key, {}) if isinstance(live_data.get(key, {}), dict) else {}
            comparable_existing = {k: existing.get(k) for k in ("price", "previous_close", "pct", "price_date")}
            comparable_new = {k: quote.get(k) for k in ("price", "previous_close", "pct", "price_date")}
            changed = comparable_existing != comparable_new
            live_data[key] = {
                **quote,
                "label": label or alias,
                "section": str(item.get("section") or ""),
                "fetched_at": fetched_at,
            }
            report["updated"] += 1
            report["attempts"].append({
                "label": label or alias,
                "ticker": alias,
                "status": "updated" if changed else "unchanged",
                "price": quote.get("price"),
                "pct": quote.get("pct"),
                "price_date": quote.get("price_date") or "",
            })
            report["updated_items"].append({
                "label": label or alias,
                "ticker": alias,
                "price": quote.get("price"),
                "pct": quote.get("pct"),
                "price_date": quote.get("price_date") or "",
                "changed": changed,
            })
            break
        else:
            report["failed"].append({"label": label or aliases[0], "aliases": list(aliases)})

    return report


def format_market_refresh_report(report: dict[str, Any]) -> str:
    requested = int(report.get("requested") or 0)
    updated = int(report.get("updated") or 0)
    unchanged = int(report.get("unchanged") or 0)
    recovered = updated + unchanged
    failed = len(report.get("failed") or [])
    return (
        f"Mercati aggiornati: {recovered} serie recuperate "
        f"({updated} modificate, {unchanged} gia' allineate), "
        f"{failed} non disponibili su {requested} richieste."
    )


def format_market_combined_refresh_report(report: dict[str, Any]) -> str:
    live = report.get("live") if isinstance(report.get("live"), dict) else {}
    storico = report.get("storico") if isinstance(report.get("storico"), dict) else {}
    live_requested = int(live.get("requested") or 0)
    live_updated = int(live.get("updated") or 0)
    live_failed = len(live.get("failed") or [])
    hist_requested = int(storico.get("requested") or 0)
    hist_updated = int(storico.get("updated") or 0)
    hist_unchanged = int(storico.get("unchanged") or 0)
    hist_failed = len(storico.get("failed") or [])
    return (
        f"Mercati aggiornati: live {live_updated}/{live_requested} "
        f"({live_failed} non disponibili), storico {hist_updated + hist_unchanged}/{hist_requested} "
        f"({hist_updated} modificati, {hist_failed} non disponibili)."
    )
