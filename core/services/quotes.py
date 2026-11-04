"""
core/services/quotes.py — Quotazioni (quotes) services.

Functions for managing quote statistics and ticker validation.
Pure functions - no Streamlit dependencies, no side effects.
"""
from typing import Any
import pandas as pd
from core.asset_categories import ASSET_CATEGORY_REGISTRY, ACTIVE_CATEGORY_CODES


def get_quotazioni_stats(qdf: pd.DataFrame) -> dict[str, int]:
    """Conta esiti OK, WARNING ed ERRORE nella diagnostica quotazioni."""
    if qdf is None or qdf.empty or "Esito" not in qdf.columns:
        return {"ok": 0, "warning": 0, "error": 0}
    return {
        "ok": int((qdf["Esito"] == "OK").sum()),
        "warning": int((qdf["Esito"] == "WARNING").sum()),
        "error": int((qdf["Esito"] == "ERRORE").sum()),
    }


def get_valid_quote_tickers_by_category(
    data: dict[str, Any],
    dh: pd.DataFrame,
    closed_tickers: frozenset[str] | None = None,
) -> list[str]:
    """Restituisce ticker con storico quotazioni valido, ordinati per macro-categoria."""
    from persistence.storage import macro_cat

    if dh is None or dh.empty:
        return []
    strumenti = data.get("strumenti", [])
    tickers = [
        s["ticker"] for s in strumenti
        if s.get("ticker") in dh.columns
        and dh[s["ticker"]].notna().sum() > 0
        and (closed_tickers is None or s.get("ticker") not in closed_tickers)
    ]
    ordered_categories = [code for code in ASSET_CATEGORY_REGISTRY.keys() if code != "ALTRO"]
    categorized = {cat: [] for cat in ordered_categories}
    categorized["ALTRO"] = []
    for tk in tickers:
        strumento = next((s for s in strumenti if s.get("ticker") == tk), {})
        cat = macro_cat(strumento.get("tipo", ""))
        if cat in categorized:
            categorized[cat].append(tk)
        else:
            categorized["ALTRO"].append(tk)
    for cat in categorized:
        categorized[cat].sort()
    result = []
    for cat in [*ordered_categories, "ALTRO"]:
        result.extend(categorized.get(cat, []))
    return result
