"""
core/services/snapshots.py - Snapshot creation and comparison helpers.

Pure functions except for callers that explicitly persist via persistence.storage.
Designed to support both legacy snapshots and richer newly-created snapshots.
"""
from __future__ import annotations

import copy
import logging
import math
from datetime import datetime
from typing import Any

import pandas as pd

from core.asset_categories import ACTIVE_CATEGORY_CODES
from core.constants import QTY_ZERO_EPS
from core.finance import build_ptf_df, compute_portfolio_state
from persistence.storage import get_registro_eventi, macro_cat

logger = logging.getLogger("portafoglio.core.services.snapshots")


CATEGORIES = tuple(ACTIVE_CATEGORY_CODES)


def build_snapshot_from_portfolio_data(data: dict[str, Any], label: str = "Snapshot") -> dict[str, Any]:
    """Build a rich snapshot while preserving the legacy snapshot fields."""
    da = build_ptf_df(data)
    state = compute_portfolio_state(data, include_closed=True)
    liquidita = float(state.get("liquidita", 0.0) or 0.0)
    total_value = _sum_col(da, "Controvalore")
    total_cost = _sum_col(da, "Costo")
    total_pl = _sum_col(da, "P/L €") if "P/L €" in da.columns else total_value - total_cost
    holdings = []
    macro_values = {cat: 0.0 for cat in CATEGORIES}

    if da is not None and not da.empty:
        work = da.copy()
        work = work[pd.to_numeric(work.get("Quote", 0), errors="coerce").fillna(0) > QTY_ZERO_EPS].copy()
        if "Categoria" not in work.columns:
            work["Categoria"] = work["Tipo"].apply(macro_cat)
        for _, row in work.iterrows():
            category = macro_cat(row.get("Categoria") or row.get("Tipo", ""))
            market_value = _float(row.get("Controvalore"))
            cost = _float(row.get("Costo"))
            pl_eur = _holding_pl_fallback(row.get("P/L €"), market_value, cost)
            macro_values[category] = macro_values.get(category, 0.0) + market_value
            holdings.append(
                {
                    "ticker": str(row.get("Ticker") or ""),
                    "strumento": str(row.get("Strumento") or row.get("Ticker") or ""),
                    "categoria": category,
                    "tipo": str(row.get("Tipo") or ""),
                    "quantity": _float(row.get("Quote")),
                    "price": _float(row.get("Prezzo")),
                    "cost": cost,
                    "market_value": market_value,
                    "pl_eur": pl_eur,
                    "pl_pct": _safe_ratio(pl_eur, abs(cost)),
                    "weight": _safe_ratio(market_value, total_value),
                }
            )

    macro_weights = {cat: _safe_ratio(macro_values.get(cat, 0.0), total_value) for cat in CATEGORIES}
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    return {
        "snapshot_id": f"snap_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "portfolio_id": str(data.get("portfolio_id", "main") or "main"),
        "label": str(label or "Snapshot"),
        "created_at": ts,
        "total_value": total_value,
        "total_cost": total_cost,
        "total_pl": total_pl,
        "total_pl_pct": _safe_ratio(total_pl, abs(total_cost)),
        "cash_balance": liquidita,
        "total_assets": total_value + liquidita,
        "macro_weights": macro_weights,
        "macro_values": macro_values,
        "holdings": holdings,
    }


def build_snapshot_summary_df(snapshots: list[dict[str, Any]] | None) -> pd.DataFrame:
    rows = []
    for snap in snapshots or []:
        value = _float(snap.get("total_value"))
        cash = _float(snap.get("cash_balance"))
        cost = _float(snap.get("total_cost"))
        pl = _float(snap.get("total_pl"))
        rows.append(
            {
                "ID": snap.get("snapshot_id", ""),
                "Etichetta": snap.get("label", ""),
                "Data": _format_snapshot_date(snap.get("created_at")),
                "Valore strumenti": value,
                "Liquidita": cash,
                "Patrimonio": _float(snap.get("total_assets", value + cash)),
                "Costo": cost,
                "P/L": pl,
                "Rendimento": _safe_ratio(pl, abs(cost)),
            }
        )
    return pd.DataFrame(rows)


def build_snapshot_display_names(snapshots: list[dict[str, Any]] | None) -> list[str]:
    normalized = [snap for snap in (snapshots or []) if isinstance(snap, dict)]
    base_names = [str(snap.get("label") or snap.get("snapshot_id") or "Snapshot") for snap in normalized]
    counts: dict[str, int] = {}
    for base in base_names:
        counts[base] = counts.get(base, 0) + 1
    emitted: dict[str, int] = {}
    out: list[str] = []
    for snap, base in zip(normalized, base_names):
        emitted[base] = emitted.get(base, 0) + 1
        if counts.get(base, 0) <= 1:
            out.append(base)
            continue
        snap_dt = _snapshot_datetime(snap)
        suffix = snap_dt.strftime("%d/%m %H:%M") if snap_dt is not None else f"#{emitted[base]}"
        out.append(f"{base} - {suffix}")
    return out


def snapshot_datetime(snapshot: dict[str, Any] | None) -> pd.Timestamp | None:
    return _snapshot_datetime(snapshot or {})


def compare_snapshots(snap_a: dict[str, Any] | None, snap_b: dict[str, Any] | None) -> dict[str, Any]:
    snap_a = snap_a or {}
    snap_b = snap_b or {}
    holdings_a = snapshot_holdings_df(snap_a)
    holdings_b = snapshot_holdings_df(snap_b)
    category_df = build_category_comparison_df(snap_a, snap_b, holdings_a, holdings_b)
    holdings_df = build_holding_comparison_df(holdings_a, holdings_b)
    metrics_df = build_snapshot_metrics_df(snap_a, snap_b)
    contributors_df = holdings_df.sort_values("Delta valore", ascending=False).copy() if not holdings_df.empty else pd.DataFrame()
    return {
        "metrics": metrics_df,
        "categories": category_df,
        "holdings": holdings_df,
        "contributors": contributors_df,
        "summary": build_comparison_summary(metrics_df, category_df, contributors_df),
    }


def enrich_snapshots_with_portfolio_data(snapshots: list[dict[str, Any]] | None, data: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [enrich_snapshot_with_portfolio_data(snap, data) for snap in (snapshots or [])]


def enrich_snapshot_with_portfolio_data(snapshot: dict[str, Any] | None, data: dict[str, Any] | None) -> dict[str, Any]:
    """Add per-holding cost/P-L for legacy snapshots using portfolio events as-of snapshot date."""
    snap = copy.deepcopy(snapshot or {})
    if not data:
        return snap
    holdings = snap.get("holdings", []) or []
    if holdings and all(_has_holding_pl_fields(item) for item in holdings if isinstance(item, dict)):
        return snap

    snap_dt = _snapshot_datetime(snap)
    if snap_dt is None:
        return snap
    asof_data = _portfolio_data_asof(data, snap_dt)
    price_map = _price_map_asof(data, snap_dt)
    try:
        state = compute_portfolio_state(asof_data, price_map=price_map, include_closed=True)
        state_df = state.get("df", pd.DataFrame())
    except Exception:
        logger.warning("enrich_snapshot_with_portfolio_data: compute_portfolio_state fallito, snapshot mostrato senza posizioni arricchite", exc_info=True)
        state_df = pd.DataFrame()
    if state_df is None or state_df.empty:
        return snap

    state_by_ticker = {str(row.get("Ticker") or ""): row for _, row in state_df.iterrows()}
    total_value = _float(snap.get("total_value"))
    enriched = []
    source_holdings = holdings if holdings else _holdings_from_state_df(state_df)
    for item in source_holdings:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or item.get("Ticker") or "")
        state_row = state_by_ticker.get(ticker)
        market_value = _float(item.get("market_value", item.get("Controvalore", item.get("Valore"))))
        if market_value == 0.0 and state_row is not None:
            market_value = _float(state_row.get("Controvalore"))
        cost = _float(item.get("cost", item.get("Costo", item.get("Costo storico"))))
        if cost == 0.0 and state_row is not None:
            cost = _float(state_row.get("Costo"))
        quantity = _float(item.get("quantity", item.get("Quote")))
        if quantity == 0.0 and state_row is not None:
            quantity = _float(state_row.get("Quote"))
        price = _float(item.get("price", item.get("Prezzo")))
        if price == 0.0 and quantity > 1e-12 and market_value:
            price = market_value / quantity
        elif price == 0.0 and state_row is not None:
            price = _float(state_row.get("Prezzo"))
        pl_eur = _holding_pl_fallback(item.get("pl_eur", item.get("P/L €", item.get("P/L"))), market_value, cost)
        enriched.append(
            {
                **item,
                "ticker": ticker,
                "strumento": str(item.get("strumento") or item.get("Strumento") or (state_row.get("Strumento") if state_row is not None else ticker) or ticker),
                "categoria": macro_cat(item.get("categoria") or item.get("Categoria") or (state_row.get("Tipo") if state_row is not None else "")),
                "quantity": quantity,
                "price": price,
                "market_value": market_value,
                "cost": cost,
                "pl_eur": pl_eur,
                "pl_pct": _safe_ratio(pl_eur, abs(cost)),
                "weight": _float(item.get("weight", _safe_ratio(market_value, total_value))),
            }
        )
    snap["holdings"] = enriched
    if enriched:
        snap["total_cost"] = sum(_float(item.get("cost")) for item in enriched)
        snap["total_pl"] = sum(_float(item.get("pl_eur")) for item in enriched)
        snap["total_pl_pct"] = _safe_ratio(_float(snap.get("total_pl")), abs(_float(snap.get("total_cost"))))
    return snap


def build_multi_snapshot_metrics_df(snapshots: list[dict[str, Any]] | None, snapshot_names: list[str] | None = None) -> pd.DataFrame:
    rows = []
    normalized = [snap for snap in (snapshots or []) if isinstance(snap, dict)]
    names = snapshot_names or build_snapshot_display_names(normalized)
    for snap, snap_name in zip(normalized, names):
        if not isinstance(snap, dict):
            continue
        rows.append(
            {
                "Snapshot": snap_name,
                "Data": _format_snapshot_date(snap.get("created_at")),
                "Valore strumenti": _float(snap.get("total_value")),
                "Liquidita": _float(snap.get("cash_balance")),
                "Patrimonio totale": _float(snap.get("total_assets", _float(snap.get("total_value")) + _float(snap.get("cash_balance")))),
                "Costo": _float(snap.get("total_cost")),
                "P/L": _float(snap.get("total_pl")),
                "Rendimento": _float(snap.get("total_pl_pct", _safe_ratio(_float(snap.get("total_pl")), abs(_float(snap.get("total_cost")))))),
            }
        )
    return pd.DataFrame(rows)


def build_multi_snapshot_categories_df(snapshots: list[dict[str, Any]] | None, snapshot_names: list[str] | None = None) -> pd.DataFrame:
    rows = []
    normalized = [snap for snap in (snapshots or []) if isinstance(snap, dict)]
    names = snapshot_names or build_snapshot_display_names(normalized)
    for snap, snap_name in zip(normalized, names):
        if not isinstance(snap, dict):
            continue
        holdings = snapshot_holdings_df(snap)
        values = _category_values_from_snapshot(snap, holdings)
        total = sum(values.values())
        for cat in CATEGORIES:
            val = float(values.get(cat, 0.0))
            rows.append(
                {
                    "Snapshot": snap_name,
                    "Data": _format_snapshot_date(snap.get("created_at")),
                    "Categoria": cat,
                    "Valore": val,
                    "Peso": _safe_ratio(val, total),
                }
            )
    return pd.DataFrame(rows)


def build_multi_snapshot_metrics_wide_df(snapshots: list[dict[str, Any]] | None, snapshot_names: list[str] | None = None) -> pd.DataFrame:
    long_df = build_multi_snapshot_metrics_df(snapshots, snapshot_names=snapshot_names)
    if long_df.empty:
        return pd.DataFrame()
    metric_rows = []
    ordered = long_df["Snapshot"].tolist()
    for metric in ["Valore strumenti", "Liquidita", "Patrimonio totale", "Costo", "P/L", "Rendimento"]:
        row_df = long_df[["Snapshot", metric]].copy()
        pivot = dict(zip(row_df["Snapshot"], row_df[metric]))
        row = {"Voce": metric}
        for snap_name in ordered:
            row[snap_name] = pivot.get(snap_name)
        if len(ordered) >= 2:
            row["Delta complessivo"] = _float(pivot.get(ordered[-1])) - _float(pivot.get(ordered[0]))
        metric_rows.append(row)
    return pd.DataFrame(metric_rows)


def build_multi_snapshot_categories_wide_df(
    snapshots: list[dict[str, Any]] | None,
    value_col: str = "Valore",
    snapshot_names: list[str] | None = None,
) -> pd.DataFrame:
    long_df = build_multi_snapshot_categories_df(snapshots, snapshot_names=snapshot_names)
    if long_df.empty:
        return pd.DataFrame()
    ordered = snapshot_names or build_snapshot_display_names([snap for snap in (snapshots or []) if isinstance(snap, dict)])
    rows = []
    for cat in CATEGORIES:
        cat_df = long_df[long_df["Categoria"] == cat].copy()
        pivot = dict(zip(cat_df["Snapshot"], cat_df[value_col]))
        row = {"Categoria": cat}
        for snap_name in ordered:
            row[snap_name] = pivot.get(snap_name)
        if len(ordered) >= 2:
            row["Delta complessivo"] = _float(pivot.get(ordered[-1])) - _float(pivot.get(ordered[0]))
        rows.append(row)
    return pd.DataFrame(rows)


def build_multi_snapshot_holdings_wide_df(
    snapshots: list[dict[str, Any]] | None,
    snapshot_names: list[str] | None = None,
) -> pd.DataFrame:
    rows_by_ticker: dict[str, dict[str, Any]] = {}
    normalized = [snap for snap in (snapshots or []) if isinstance(snap, dict)]
    ordered = snapshot_names or build_snapshot_display_names(normalized)
    for snap, snap_name in zip(normalized, ordered):
        if not isinstance(snap, dict):
            continue
        holdings = snapshot_holdings_df(snap)
        if holdings.empty:
            continue
        for _, row in holdings.iterrows():
            ticker = str(row.get("ticker") or "")
            if not ticker:
                continue
            out_row = rows_by_ticker.setdefault(
                ticker,
                {
                    "Ticker": ticker,
                    "Strumento": str(row.get("strumento") or ticker),
                    "Categoria": str(row.get("categoria") or ""),
                },
            )
            out_row["Strumento"] = str(row.get("strumento") or out_row.get("Strumento") or ticker)
            out_row["Categoria"] = str(row.get("categoria") or out_row.get("Categoria") or "")
            out_row[f"Quote {snap_name}"] = _float(row.get("quantity"))
            out_row[f"Prezzo {snap_name}"] = _float(row.get("price"))
            out_row[f"Costo {snap_name}"] = _float(row.get("cost"))
            out_row[f"Valore {snap_name}"] = _float(row.get("market_value"))
            out_row[f"Peso {snap_name}"] = _float(row.get("weight"))
            out_row[f"P/L {snap_name}"] = _float(row.get("pl_eur"))
            out_row[f"Rendimento {snap_name}"] = _float(row.get("pl_pct"))
    if not rows_by_ticker:
        return pd.DataFrame()
    rows = list(rows_by_ticker.values())
    if len(ordered) >= 2:
        first = ordered[0]
        last = ordered[-1]
        for row in rows:
            row["Delta quote complessivo"] = _float(row.get(f"Quote {last}")) - _float(row.get(f"Quote {first}"))
            row["Delta costo complessivo"] = _float(row.get(f"Costo {last}")) - _float(row.get(f"Costo {first}"))
            row["Delta valore complessivo"] = _float(row.get(f"Valore {last}")) - _float(row.get(f"Valore {first}"))
            row["Delta P/L complessivo"] = _float(row.get(f"P/L {last}")) - _float(row.get(f"P/L {first}"))
            row["Delta peso complessivo"] = _float(row.get(f"Peso {last}")) - _float(row.get(f"Peso {first}"))
            row["Delta rendimento complessivo"] = _float(row.get(f"Rendimento {last}")) - _float(row.get(f"Rendimento {first}"))
            first_price = _float(row.get(f"Prezzo {first}"))
            last_price = _float(row.get(f"Prezzo {last}"))
            row["Delta prezzo % complessivo"] = _price_delta_pct(
                first_price,
                last_price,
                _float(row.get(f"Quote {first}")),
                _float(row.get(f"Quote {last}")),
            )
    out = pd.DataFrame(rows)
    sort_col = "Delta valore complessivo" if "Delta valore complessivo" in out.columns else f"Valore {ordered[-1]}"
    return out.sort_values(sort_col, ascending=False).reset_index(drop=True)


def build_snapshot_metrics_df(snap_a: dict[str, Any], snap_b: dict[str, Any]) -> pd.DataFrame:
    rows = []
    specs = [
        ("Valore strumenti", "total_value", "eur"),
        ("Liquidita", "cash_balance", "eur"),
        ("Patrimonio totale", "total_assets", "eur"),
        ("Costo", "total_cost", "eur"),
        ("P/L", "total_pl", "eur"),
        ("Rendimento", "total_pl_pct", "pct"),
    ]
    for label, key, kind in specs:
        a = _metric_value(snap_a, key)
        b = _metric_value(snap_b, key)
        if key == "total_assets":
            a = _float(snap_a.get("total_assets", _float(snap_a.get("total_value")) + _float(snap_a.get("cash_balance"))))
            b = _float(snap_b.get("total_assets", _float(snap_b.get("total_value")) + _float(snap_b.get("cash_balance"))))
        if key == "total_pl_pct":
            a = _float(snap_a.get("total_pl_pct", _safe_ratio(_float(snap_a.get("total_pl")), abs(_float(snap_a.get("total_cost"))))))
            b = _float(snap_b.get("total_pl_pct", _safe_ratio(_float(snap_b.get("total_pl")), abs(_float(snap_b.get("total_cost"))))))
        rows.append({"Voce": label, "A": a, "B": b, "Delta": b - a, "Tipo": kind})
    return pd.DataFrame(rows)


def build_category_comparison_df(
    snap_a: dict[str, Any],
    snap_b: dict[str, Any],
    holdings_a: pd.DataFrame | None = None,
    holdings_b: pd.DataFrame | None = None,
) -> pd.DataFrame:
    holdings_a = holdings_a if holdings_a is not None else snapshot_holdings_df(snap_a)
    holdings_b = holdings_b if holdings_b is not None else snapshot_holdings_df(snap_b)
    values_a = _category_values_from_snapshot(snap_a, holdings_a)
    values_b = _category_values_from_snapshot(snap_b, holdings_b)
    total_a = sum(values_a.values())
    total_b = sum(values_b.values())
    rows = []
    for cat in CATEGORIES:
        va = float(values_a.get(cat, 0.0))
        vb = float(values_b.get(cat, 0.0))
        rows.append(
            {
                "Categoria": cat,
                "Valore A": va,
                "Valore B": vb,
                "Delta valore": vb - va,
                "Peso A": _safe_ratio(va, total_a),
                "Peso B": _safe_ratio(vb, total_b),
                "Delta peso": _safe_ratio(vb, total_b) - _safe_ratio(va, total_a),
            }
        )
    return pd.DataFrame(rows)


def build_holding_comparison_df(holdings_a: pd.DataFrame, holdings_b: pd.DataFrame) -> pd.DataFrame:
    cols = ["ticker", "strumento", "categoria", "quantity", "price", "market_value", "cost", "pl_eur", "pl_pct", "weight"]
    left = _ensure_holding_cols(holdings_a, cols)
    right = _ensure_holding_cols(holdings_b, cols)
    merged = left.merge(right, on="ticker", how="outer", suffixes=(" A", " B"))
    if merged.empty:
        return pd.DataFrame(columns=["Ticker", "Strumento", "Categoria", "Quote A", "Quote B", "Delta quote", "Prezzo A", "Prezzo B", "Delta prezzo %", "Costo A", "Costo B", "Delta costo", "Valore A", "Valore B", "Delta valore", "Peso A", "Peso B", "Delta peso", "P/L A", "P/L B", "Delta P/L", "Rendimento A", "Rendimento B", "Delta rendimento"])
    merged["Strumento"] = merged["strumento B"].fillna(merged["strumento A"]).fillna(merged["ticker"])
    merged["Categoria"] = merged["categoria B"].fillna(merged["categoria A"]).fillna("")
    for col in ("quantity A", "quantity B", "price A", "price B", "market_value A", "market_value B", "cost A", "cost B", "pl_eur A", "pl_eur B", "pl_pct A", "pl_pct B", "weight A", "weight B"):
        merged[col] = pd.to_numeric(merged.get(col), errors="coerce").fillna(0.0)
    merged["pl_eur A"] = merged.apply(lambda row: _holding_pl_fallback(row.get("pl_eur A"), row.get("market_value A"), row.get("cost A")), axis=1)
    merged["pl_eur B"] = merged.apply(lambda row: _holding_pl_fallback(row.get("pl_eur B"), row.get("market_value B"), row.get("cost B")), axis=1)
    merged["pl_pct A"] = merged.apply(lambda row: _safe_ratio(row.get("pl_eur A"), abs(_float(row.get("cost A")))), axis=1)
    merged["pl_pct B"] = merged.apply(lambda row: _safe_ratio(row.get("pl_eur B"), abs(_float(row.get("cost B")))), axis=1)
    out = pd.DataFrame(
        {
            "Ticker": merged["ticker"],
            "Strumento": merged["Strumento"],
            "Categoria": merged["Categoria"],
            "Quote A": merged["quantity A"],
            "Quote B": merged["quantity B"],
            "Delta quote": merged["quantity B"] - merged["quantity A"],
            "Prezzo A": merged["price A"],
            "Prezzo B": merged["price B"],
            "Delta prezzo %": merged.apply(
                lambda row: _price_delta_pct(
                    _float(row.get("price A")),
                    _float(row.get("price B")),
                    _float(row.get("quantity A")),
                    _float(row.get("quantity B")),
                ),
                axis=1,
            ),
            "Costo A": merged["cost A"],
            "Costo B": merged["cost B"],
            "Delta costo": merged["cost B"] - merged["cost A"],
            "Valore A": merged["market_value A"],
            "Valore B": merged["market_value B"],
            "Delta valore": merged["market_value B"] - merged["market_value A"],
            "Peso A": merged["weight A"],
            "Peso B": merged["weight B"],
            "Delta peso": merged["weight B"] - merged["weight A"],
            "P/L A": merged["pl_eur A"],
            "P/L B": merged["pl_eur B"],
            "Delta P/L": merged["pl_eur B"] - merged["pl_eur A"],
            "Rendimento A": merged["pl_pct A"],
            "Rendimento B": merged["pl_pct B"],
            "Delta rendimento": merged["pl_pct B"] - merged["pl_pct A"],
        }
    )
    return out.sort_values("Delta valore", ascending=False).reset_index(drop=True)


def snapshot_holdings_df(snapshot: dict[str, Any] | None) -> pd.DataFrame:
    rows = []
    total = _float((snapshot or {}).get("total_value"))
    for item in (snapshot or {}).get("holdings", []) or []:
        if not isinstance(item, dict):
            continue
        quantity = _float(item.get("quantity", item.get("Quote")))
        market_value = _float(item.get("market_value", item.get("Controvalore", item.get("Valore"))))
        cost = _float(item.get("cost", item.get("Costo", item.get("Costo storico"))))
        pl_eur = _holding_pl_fallback(item.get("pl_eur", item.get("P/L €", item.get("P/L"))), market_value, cost)
        if abs(quantity) <= 1e-12 and abs(market_value) <= 1e-9 and abs(cost) <= 1e-9 and abs(pl_eur) <= 1e-9:
            continue
        rows.append(
            {
                "ticker": str(item.get("ticker") or item.get("Ticker") or ""),
                "strumento": str(item.get("strumento") or item.get("Strumento") or item.get("ticker") or item.get("Ticker") or ""),
                "categoria": macro_cat(item.get("categoria") or item.get("Categoria") or item.get("tipo") or item.get("Tipo") or ""),
                "quantity": quantity,
                "price": _float(item.get("price", item.get("Prezzo"))),
                "market_value": market_value,
                "cost": cost,
                "pl_eur": pl_eur,
                "pl_pct": _safe_ratio(pl_eur, abs(cost)),
                "weight": _float(item.get("weight", item.get("Peso", _safe_ratio(market_value, total)))),
            }
        )
    return pd.DataFrame(rows)


def delete_snapshot_by_id(snapshots_state: dict[str, Any], snapshot_id: str) -> tuple[dict[str, Any], bool]:
    state = dict(snapshots_state or {})
    snaps = list(state.get("snapshots", []) or [])
    before = len(snaps)
    state["snapshots"] = [snap for snap in snaps if str(snap.get("snapshot_id")) != str(snapshot_id)]
    return state, len(state["snapshots"]) != before


def build_comparison_summary(metrics_df: pd.DataFrame, category_df: pd.DataFrame, contributors_df: pd.DataFrame) -> list[str]:
    notes: list[str] = []
    if metrics_df is not None and not metrics_df.empty:
        patrimonio = metrics_df[metrics_df["Voce"] == "Patrimonio totale"]
        if not patrimonio.empty:
            delta = _float(patrimonio["Delta"].iloc[0])
            notes.append(f"Il patrimonio totale cambia di {delta:,.2f} EUR.")
        pl = metrics_df[metrics_df["Voce"] == "P/L"]
        if not pl.empty:
            delta_pl = _float(pl["Delta"].iloc[0])
            notes.append(f"Il P/L complessivo cambia di {delta_pl:,.2f} EUR.")
    if category_df is not None and not category_df.empty:
        row = category_df.iloc[category_df["Delta peso"].abs().argmax()]
        notes.append(f"La variazione di peso piu evidente riguarda {row['Categoria']} ({_float(row['Delta peso']):+.2%}).")
    if contributors_df is not None and not contributors_df.empty:
        best = contributors_df.iloc[0]
        worst = contributors_df.iloc[-1]
        notes.append(f"Maggior contributore positivo: {best['Ticker']} ({_float(best['Delta valore']):+,.2f} EUR).")
        if str(best["Ticker"]) != str(worst["Ticker"]):
            notes.append(f"Maggior contributore negativo: {worst['Ticker']} ({_float(worst['Delta valore']):+,.2f} EUR).")
    return notes


def _category_values_from_snapshot(snapshot: dict[str, Any], holdings: pd.DataFrame) -> dict[str, float]:
    values = {cat: 0.0 for cat in CATEGORIES}
    raw_values = snapshot.get("macro_values", {}) if isinstance(snapshot, dict) else {}
    if isinstance(raw_values, dict) and any(_float(v) for v in raw_values.values()):
        for cat in CATEGORIES:
            values[cat] = _float(raw_values.get(cat))
        return values
    if holdings is not None and not holdings.empty:
        grouped = holdings.groupby("categoria")["market_value"].sum()
        for cat in CATEGORIES:
            values[cat] = float(grouped.get(cat, 0.0) or 0.0)
        return values
    total = _float(snapshot.get("total_value")) if isinstance(snapshot, dict) else 0.0
    weights = snapshot.get("macro_weights", {}) if isinstance(snapshot, dict) else {}
    if isinstance(weights, dict):
        for cat in CATEGORIES:
            values[cat] = total * _float(weights.get(cat))
    return values


def _ensure_holding_cols(frame: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = frame.copy() if frame is not None else pd.DataFrame()
    for col in cols:
        if col not in out.columns:
            out[col] = 0.0 if col in {"quantity", "price", "market_value", "cost", "pl_eur", "pl_pct", "weight"} else ""
    return out[cols].copy()


def _metric_value(snapshot: dict[str, Any], key: str) -> float:
    return _float(snapshot.get(key))


def _sum_col(frame: pd.DataFrame | None, col: str) -> float:
    if frame is None or frame.empty or col not in frame.columns:
        return 0.0
    numeric = pd.to_numeric(frame[col], errors="coerce")
    numeric = numeric.map(_float)
    return float(numeric.sum())


def _safe_ratio(num: float, den: float) -> float:
    num = _float(num)
    den = _float(den)
    return num / den if abs(den) > 1e-12 else 0.0


def _price_delta_pct(price_a: float, price_b: float, qty_a: float = 0.0, qty_b: float = 0.0) -> float:
    price_a = _float(price_a)
    price_b = _float(price_b)
    qty_a = _float(qty_a)
    qty_b = _float(qty_b)
    if abs(qty_a) <= 1e-12 and abs(qty_b) <= 1e-12:
        return 0.0
    if abs(price_a) <= 1e-12 and abs(price_b) <= 1e-12:
        return 0.0
    return _safe_ratio(price_b - price_a, abs(price_a))


def _float(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, str):
        text = value.strip().replace("€", "").replace("%", "").replace(" ", "")
        if "," in text and "." in text:
            text = text.replace(".", "").replace(",", ".")
        elif "," in text:
            text = text.replace(",", ".")
        value = text
    try:
        number = float(value or 0.0)
    except Exception:
        return 0.0
    return number if math.isfinite(number) else 0.0


def _holding_pl_fallback(raw_pl: Any, market_value: Any, cost: Any) -> float:
    market_value_f = _float(market_value)
    cost_f = _float(cost)
    raw_pl_f = _float(raw_pl)
    if abs(raw_pl_f) > 1e-12:
        return raw_pl_f
    if abs(cost_f) <= 1e-12:
        return raw_pl_f
    derived_pl = market_value_f - cost_f
    if abs(derived_pl) > 1e-12:
        return derived_pl
    return raw_pl_f


def _has_holding_pl_fields(item: dict[str, Any]) -> bool:
    return any(key in item for key in ("pl_eur", "P/L €", "P/L")) and any(key in item for key in ("cost", "Costo", "Costo storico"))


def _snapshot_datetime(snapshot: dict[str, Any]) -> pd.Timestamp | None:
    for key in ("created_at", "data", "Data"):
        if snapshot.get(key):
            raw = str(snapshot.get(key))
            dayfirst = "/" in raw
            dt = pd.to_datetime(raw, errors="coerce", dayfirst=dayfirst)
            if pd.notna(dt):
                return pd.Timestamp(dt)
    return None


def _portfolio_data_asof(data: dict[str, Any], snap_dt: pd.Timestamp) -> dict[str, Any]:
    out = copy.deepcopy(data)
    cutoff = snap_dt.normalize()
    eventi = []
    for ev in get_registro_eventi(data):
        ev_dt = pd.to_datetime(ev.get("data"), errors="coerce")
        if pd.notna(ev_dt) and pd.Timestamp(ev_dt).normalize() <= cutoff:
            eventi.append(ev)
    out["registro_eventi"] = eventi
    out["cache_posizioni"] = {}
    return out


def _price_map_asof(data: dict[str, Any], snap_dt: pd.Timestamp) -> dict[str, float]:
    cutoff = snap_dt.normalize()
    storico = data.get("storico_prezzi", {}) if isinstance(data, dict) else {}
    out: dict[str, float] = {}
    if isinstance(storico, dict):
        for raw_date in sorted(storico.keys()):
            dt = pd.to_datetime(raw_date, errors="coerce")
            if pd.isna(dt) or pd.Timestamp(dt).normalize() > cutoff:
                continue
            prices = storico.get(raw_date, {})
            if isinstance(prices, dict):
                for ticker, price in prices.items():
                    val = _float(price)
                    if val > 0:
                        out[str(ticker)] = val
    if not out:
        for item in data.get("strumenti", []) or []:
            ticker = str(item.get("ticker") or "")
            price = _float(item.get("prezzo"))
            if ticker and price > 0:
                out[ticker] = price
    return out


def _holdings_from_state_df(state_df: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for _, row in state_df.iterrows():
        if _float(row.get("Quote")) <= 1e-12:
            continue
        rows.append(
            {
                "ticker": str(row.get("Ticker") or ""),
                "strumento": str(row.get("Strumento") or row.get("Ticker") or ""),
                "categoria": macro_cat(row.get("Tipo") or ""),
                "market_value": _float(row.get("Controvalore")),
                "weight": 0.0,
            }
        )
    return rows


def _format_snapshot_date(value: Any) -> str:
    if not value:
        return ""
    text = str(value)
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19], fmt).strftime("%d/%m/%Y %H:%M")
        except Exception:
            continue
    return text
