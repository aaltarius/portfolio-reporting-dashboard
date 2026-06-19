"""
core/services/planning.py - Pure what-if planning calculations.

The simulator never writes portfolio data. It estimates static impact on
allocation, concentration and liquidity before a real operation is recorded.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from core.asset_categories import ACTIVE_CATEGORY_CODES, get_selected_category_codes
from persistence.storage import macro_cat


PLANNING_CATEGORIES = tuple(ACTIVE_CATEGORY_CODES)


def _resolve_planning_categories(settings: dict[str, Any] | None = None) -> tuple[str, ...]:
    if settings is None:
        return PLANNING_CATEGORIES
    return tuple(get_selected_category_codes(settings))


def simulate_trade_impact(
    positions_df: pd.DataFrame,
    *,
    cash_balance: float,
    operation: str,
    ticker: str,
    name: str,
    category: str,
    quantity: float,
    price: float,
    commissions: float = 0.0,
) -> dict[str, Any]:
    operation = str(operation or "Acquisto")
    ticker = str(ticker or "").strip().upper()
    name = str(name or ticker or "Strumento ipotetico")
    category = macro_cat(category)
    quantity = max(0.0, _float(quantity))
    price = max(0.0, _float(price))
    commissions = max(0.0, _float(commissions))
    amount = quantity * price

    before = _prepare_positions(positions_df)
    after = before.copy()
    warnings: list[str] = []

    if not ticker:
        warnings.append("Ticker mancante: la simulazione usa una riga descrittiva generica.")
        ticker = "IPOTETICO"
    if amount <= 0:
        warnings.append("Importo nullo: inserisci quantita e prezzo maggiori di zero.")

    existing_mask = after["Ticker"].astype(str).str.upper() == ticker
    cash_after = float(cash_balance or 0.0)

    if operation == "Vendita":
        if not existing_mask.any():
            warnings.append("Vendita non simulabile su uno strumento non presente: nessuna posizione ridotta.")
        else:
            idx = after[existing_mask].index[0]
            current_qty = _float(after.at[idx, "Quote"])
            if quantity > current_qty:
                warnings.append("Quantita in vendita superiore alla posizione: viene limitata alla quantita disponibile.")
                quantity = current_qty
                amount = quantity * price
            ratio = quantity / current_qty if current_qty > 1e-12 else 0.0
            for col in ("Quote", "Controvalore", "Costo", "P/L €"):
                after.at[idx, col] = _float(after.at[idx, col]) * max(0.0, 1.0 - ratio)
            cash_after += max(0.0, amount - commissions)
            warnings.append("La vendita e simulata in modo statico: non registra fiscalita o P/L realizzato.")
    else:
        cash_after -= amount + commissions
        if existing_mask.any():
            idx = after[existing_mask].index[0]
            after.at[idx, "Quote"] = _float(after.at[idx, "Quote"]) + quantity
            after.at[idx, "Controvalore"] = _float(after.at[idx, "Controvalore"]) + amount
            after.at[idx, "Costo"] = _float(after.at[idx, "Costo"]) + amount + commissions
            after.at[idx, "P/L €"] = _float(after.at[idx, "Controvalore"]) - _float(after.at[idx, "Costo"])
        else:
            after = pd.concat(
                [
                    after,
                    pd.DataFrame(
                        [
                            {
                                "Ticker": ticker,
                                "Strumento": name,
                                "Tipo": category,
                                "Categoria": category,
                                "Quote": quantity,
                                "Prezzo": price,
                                "PMC": price,
                                "Controvalore": amount,
                                "Costo": amount + commissions,
                                "P/L €": -commissions,
                            }
                        ]
                    ),
                ],
                ignore_index=True,
            )
    after = after[pd.to_numeric(after["Controvalore"], errors="coerce").fillna(0) > 0.0001].copy()
    before_alloc = build_allocation_table(before, cash_balance)
    after_alloc = build_allocation_table(after, cash_after)
    before_conc = build_concentration_table(before, cash_balance)
    after_conc = build_concentration_table(after, cash_after)
    metrics = build_simulation_metrics(before, after, cash_balance, cash_after)
    suggestions = build_simulation_notes(metrics, before_alloc, after_alloc, before_conc, after_conc, warnings)
    return {
        "operation": operation,
        "ticker": ticker,
        "amount": amount,
        "commissions": commissions,
        "cash_before": float(cash_balance or 0.0),
        "cash_after": cash_after,
        "positions_before": before,
        "positions_after": after,
        "allocation_before": before_alloc,
        "allocation_after": after_alloc,
        "concentration_before": before_conc,
        "concentration_after": after_conc,
        "metrics": metrics,
        "notes": suggestions,
        "warnings": warnings,
    }


def build_allocation_table(
    positions_df: pd.DataFrame,
    cash_balance: float = 0.0,
    settings: dict[str, Any] | None = None,
) -> pd.DataFrame:
    work = _prepare_positions(positions_df)
    grouped = work.groupby("Categoria")["Controvalore"].sum() if not work.empty else pd.Series(dtype=float)
    rows = []
    total = float(grouped.sum()) + max(0.0, float(cash_balance or 0.0))
    for cat in _resolve_planning_categories(settings):
        value = float(grouped.get(cat, 0.0) or 0.0)
        rows.append({"Categoria": cat, "Valore": value, "Peso": _safe_ratio(value, total)})
    cash_value = max(0.0, float(cash_balance or 0.0))
    rows.append({"Categoria": "Liquidita", "Valore": cash_value, "Peso": _safe_ratio(cash_value, total)})
    return pd.DataFrame(rows)


def build_concentration_table(positions_df: pd.DataFrame, cash_balance: float = 0.0) -> pd.DataFrame:
    work = _prepare_positions(positions_df)
    total = _sum(work, "Controvalore") + max(0.0, float(cash_balance or 0.0))
    if work.empty or total <= 0:
        return pd.DataFrame(columns=["Ticker", "Strumento", "Categoria", "Controvalore", "Peso"])
    work["Peso"] = pd.to_numeric(work["Controvalore"], errors="coerce").fillna(0.0) / total
    return work[["Ticker", "Strumento", "Categoria", "Controvalore", "Peso"]].sort_values("Peso", ascending=False).reset_index(drop=True)


def build_simulation_metrics(
    before_df: pd.DataFrame,
    after_df: pd.DataFrame,
    cash_before: float,
    cash_after: float,
) -> pd.DataFrame:
    before_value = _sum(before_df, "Controvalore")
    after_value = _sum(after_df, "Controvalore")
    before_assets = before_value + float(cash_before or 0.0)
    after_assets = after_value + float(cash_after or 0.0)
    rows = [
        ("Valore strumenti", before_value, after_value, "eur"),
        ("Liquidita", float(cash_before or 0.0), float(cash_after or 0.0), "eur"),
        ("Patrimonio simulato", before_assets, after_assets, "eur"),
        ("Peso liquidita", _safe_ratio(max(0.0, cash_before), before_assets), _safe_ratio(max(0.0, cash_after), after_assets), "pct"),
    ]
    return pd.DataFrame([{"Voce": label, "Prima": a, "Dopo": b, "Delta": b - a, "Tipo": kind} for label, a, b, kind in rows])


def build_static_return_scenarios(total_after: float, annual_returns: dict[str, float]) -> pd.DataFrame:
    horizons = [("3 mesi", 0.25), ("6 mesi", 0.50), ("1 anno", 1.0)]
    rows = []
    for scenario, annual_return in (annual_returns or {}).items():
        annual_return = _float(annual_return)
        for label, years in horizons:
            projected = float(total_after or 0.0) * ((1.0 + annual_return) ** years)
            rows.append(
                {
                    "Scenario": str(scenario),
                    "Orizzonte": label,
                    "Rendimento annuo ipotetico": annual_return,
                    "Valore simulato": projected,
                    "Delta": projected - float(total_after or 0.0),
                }
            )
    return pd.DataFrame(rows)


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
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    if "Categoria" not in out.columns:
        out["Categoria"] = out["Tipo"].apply(macro_cat)
    else:
        out["Categoria"] = out["Categoria"].apply(macro_cat)
    return out[out["Quote"].fillna(0.0) > 0.0001].copy()


def _sum(frame: pd.DataFrame, col: str) -> float:
    if frame is None or frame.empty or col not in frame.columns:
        return 0.0
    return float(pd.to_numeric(frame[col], errors="coerce").fillna(0.0).sum())


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _safe_ratio(num: float, den: float) -> float:
    den = float(den or 0.0)
    return float(num or 0.0) / den if abs(den) > 1e-12 else 0.0
