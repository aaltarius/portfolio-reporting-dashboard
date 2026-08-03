"""
core/services/planning.py - Pure what-if planning calculations.

The simulator never writes portfolio data. It estimates static impact on
allocation, concentration and liquidity before a real operation is recorded.
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd

from core.asset_categories import ACTIVE_CATEGORY_CODES, get_selected_category_codes
from persistence.storage import macro_cat


PLANNING_CATEGORIES = tuple(ACTIVE_CATEGORY_CODES)


def _resolve_planning_categories(settings: dict[str, Any] | None = None) -> tuple[str, ...]:
    if settings is None:
        return PLANNING_CATEGORIES
    return tuple(get_selected_category_codes(settings))


def build_allocation_table(
    positions_df: pd.DataFrame,
    cash_balance: float = 0.0,
    settings: dict[str, Any] | None = None,
) -> pd.DataFrame:
    work = _prepare_positions(positions_df)
    grouped = work.groupby("Categoria")["Controvalore"].sum() if not work.empty else pd.Series(dtype=float)
    rows = []
    cash_value = max(0.0, _float(cash_balance))
    total = _float(grouped.sum()) + cash_value
    for cat in _resolve_planning_categories(settings):
        value = _float(grouped.get(cat, 0.0))
        rows.append({"Categoria": cat, "Valore": value, "Peso": _safe_ratio(value, total)})
    rows.append({"Categoria": "Liquidita", "Valore": cash_value, "Peso": _safe_ratio(cash_value, total)})
    return pd.DataFrame(rows)


def build_concentration_table(positions_df: pd.DataFrame, cash_balance: float = 0.0) -> pd.DataFrame:
    work = _prepare_positions(positions_df)
    total = _sum(work, "Controvalore") + max(0.0, _float(cash_balance))
    if work.empty or total <= 0:
        return pd.DataFrame(columns=["Ticker", "Strumento", "Categoria", "Controvalore", "Peso"])
    work["Peso"] = _numeric_series(work["Controvalore"]) / total
    return work[["Ticker", "Strumento", "Categoria", "Controvalore", "Peso"]].sort_values("Peso", ascending=False).reset_index(drop=True)


def build_simulation_metrics(
    before_df: pd.DataFrame,
    after_df: pd.DataFrame,
    cash_before: float,
    cash_after: float,
) -> pd.DataFrame:
    before_value = _sum(before_df, "Controvalore")
    after_value = _sum(after_df, "Controvalore")
    cash_before = _float(cash_before)
    cash_after = _float(cash_after)
    before_assets = before_value + cash_before
    after_assets = after_value + cash_after
    rows = [
        ("Valore strumenti", before_value, after_value, "eur"),
        ("Liquidita", float(cash_before or 0.0), float(cash_after or 0.0), "eur"),
        ("Patrimonio simulato", before_assets, after_assets, "eur"),
        ("Peso liquidita", _safe_ratio(max(0.0, cash_before), before_assets), _safe_ratio(max(0.0, cash_after), after_assets), "pct"),
    ]
    return pd.DataFrame([{"Voce": label, "Prima": a, "Dopo": b, "Delta": b - a, "Tipo": kind} for label, a, b, kind in rows])


def build_simulation_notes(
    metrics: pd.DataFrame,
    allocation_before: pd.DataFrame,
    allocation_after: pd.DataFrame,
    concentration_before: pd.DataFrame,
    concentration_after: pd.DataFrame,
    warnings: list[str] | None = None,
) -> list[str]:
    notes = []
    warnings = warnings or []
    cash_row = metrics[metrics["Voce"] == "Liquidita"] if metrics is not None and not metrics.empty else pd.DataFrame()
    if not cash_row.empty:
        cash_after = float(cash_row["Dopo"].iloc[0])
        if cash_after < 0:
            notes.append("La simulazione porta la liquidita sotto zero: serve ridurre importo o prevedere un versamento.")
        else:
            notes.append("La liquidita resta positiva dopo la simulazione.")

    merged_alloc = allocation_before.merge(allocation_after, on="Categoria", suffixes=(" prima", " dopo"))
    if not merged_alloc.empty:
        merged_alloc["Delta peso"] = merged_alloc["Peso dopo"] - merged_alloc["Peso prima"]
        row = merged_alloc.iloc[merged_alloc["Delta peso"].abs().argmax()]
        notes.append(f"La categoria che cambia di piu e {row['Categoria']} ({float(row['Delta peso']):+.2%}).")

    before_top = float(concentration_before["Peso"].iloc[0]) if concentration_before is not None and not concentration_before.empty else 0.0
    after_top = float(concentration_after["Peso"].iloc[0]) if concentration_after is not None and not concentration_after.empty else 0.0
    if after_top > before_top:
        notes.append(f"La concentrazione massima sale da {before_top:.2%} a {after_top:.2%}.")
    elif after_top < before_top:
        notes.append(f"La concentrazione massima scende da {before_top:.2%} a {after_top:.2%}.")

    notes.extend(warnings)
    return notes


def _prepare_positions(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        out = pd.DataFrame(columns=["Ticker", "Strumento", "Tipo", "Categoria", "Quote", "Prezzo", "PMC", "Controvalore", "Costo", "P/L €"])
    else:
        out = frame.copy()
    for col in ("Ticker", "Strumento", "Tipo"):
        if col not in out.columns:
            out[col] = ""
    for col in ("Quote", "Prezzo", "PMC", "Controvalore", "Costo", "P/L €"):
        if col not in out.columns:
            out[col] = 0.0
        out[col] = _numeric_series(out[col])
    if "Categoria" not in out.columns:
        out["Categoria"] = out["Tipo"].apply(macro_cat)
    else:
        out["Categoria"] = out["Categoria"].apply(macro_cat)
    return out[out["Quote"].fillna(0.0) > 0.0001].copy()


def _sum(frame: pd.DataFrame, col: str) -> float:
    if frame is None or frame.empty or col not in frame.columns:
        return 0.0
    return float(_numeric_series(frame[col]).sum())


def _float(value: Any) -> float:
    try:
        raw = 0.0 if value is None or (isinstance(value, str) and value.strip() == "") else value
        result = float(raw)
    except Exception:
        return 0.0
    return result if math.isfinite(result) else 0.0


def _numeric_series(values: Any) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if not isinstance(numeric, pd.Series):
        numeric = pd.Series(numeric)
    return numeric.map(_float)


def _safe_ratio(num: float, den: float) -> float:
    den = _float(den)
    num = _float(num)
    return num / den if abs(den) > 1e-12 else 0.0
