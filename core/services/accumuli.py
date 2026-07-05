"""Analisi PAC e acquisti progressivi.

Modulo puro, senza dipendenze Streamlit, usato dalla scheda Cruscotti > Accumuli.
Le funzioni non modificano i dati del portafoglio: ricostruiscono metriche e serie
operative a partire da operazioni, anagrafica strumenti e storico prezzi.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from persistence.storage import macro_cat


_ACCUMULATION_CATEGORIES = {"FND", "ETF", "ETC"}
_EXPLICIT_PAC_TOKENS = ("pac", "mensile", "mensili", "rata", "accumulo", "automatic")


@dataclass(frozen=True)
class AccumuliResult:
    summary: pd.DataFrame
    by_ticker: dict[str, dict[str, Any]]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = value.replace("€", "").replace("%", "").replace(" ", "").replace(".", "").replace(",", ".")
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except Exception:
        return default


def _safe_date(value: Any) -> pd.Timestamp | None:
    try:
        ts = pd.to_datetime(value, errors="coerce")
    except Exception:
        return None
    if pd.isna(ts):
        return None
    return pd.Timestamp(ts).normalize()


def _instrument_lookup(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for item in data.get("strumenti", []) or []:
        ticker = str(item.get("ticker") or "").strip()
        if ticker:
            lookup[ticker] = dict(item)
    master = data.get("instrument_master", {}) or {}
    if isinstance(master, dict):
        for ticker, item in master.items():
            tk = str(ticker or "").strip()
            if not tk:
                continue
            if isinstance(item, dict):
                merged = dict(item)
                merged.setdefault("ticker", tk)
                lookup.setdefault(tk, {}).update({k: v for k, v in merged.items() if v not in (None, "")})
    return lookup


def _normalise_operations(data: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    legacy_ops = data.get("operazioni", []) or []
    if legacy_ops:
        for op in legacy_ops:
            ticker = str(op.get("ticker") or "").strip()
            tipo = str(op.get("tipo") or op.get("tipo_evento") or "").strip().upper()
            dt = _safe_date(op.get("data"))
            if not ticker or dt is None or tipo not in {"ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA"}:
                continue
            qty = _safe_float(op.get("qty", op.get("quantita", 0.0)))
            price = _safe_float(op.get("price", op.get("prezzo_unitario", 0.0)))
            comm = _safe_float(op.get("comm", op.get("commissioni", 0.0)))
            imposte = _safe_float(op.get("imposte", op.get("imposta", 0.0)))
            lordo = _safe_float(op.get("importo_lordo", 0.0))
            if lordo <= 0 and qty > 0 and price > 0:
                lordo = qty * price
            rows.append(
                {
                    "data": dt,
                    "ticker": ticker,
                    "tipo": tipo,
                    "qty": qty,
                    "price": price,
                    "commissioni": max(comm, 0.0),
                    "imposte": max(imposte, 0.0),
                    "importo_lordo": max(lordo, 0.0),
                    "note": str(op.get("note") or op.get("descrizione") or ""),
                }
            )
    else:
        for ev in data.get("registro_eventi", []) or []:
            ticker = str(ev.get("ticker") or "").strip()
            tipo = str(ev.get("tipo_evento") or "").strip().upper()
            dt = _safe_date(ev.get("data"))
            if not ticker or dt is None or tipo not in {"ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA"}:
                continue
            qty = _safe_float(ev.get("quantita", 0.0))
            price = _safe_float(ev.get("prezzo_unitario", 0.0))
            lordo = _safe_float(ev.get("importo_lordo", 0.0))
            if lordo <= 0 and qty > 0 and price > 0:
                lordo = qty * price
            rows.append(
                {
                    "data": dt,
                    "ticker": ticker,
                    "tipo": tipo,
                    "qty": qty,
                    "price": price,
                    "commissioni": max(_safe_float(ev.get("commissioni", 0.0)), 0.0),
                    "imposte": max(_safe_float(ev.get("imposte", ev.get("imposta", 0.0))), 0.0),
                    "importo_lordo": max(lordo, 0.0),
                    "note": str(ev.get("note") or ev.get("descrizione") or ""),
                }
            )
    if not rows:
        return pd.DataFrame(columns=["data", "ticker", "tipo", "qty", "price", "commissioni", "imposte", "importo_lordo", "note"])
    df = pd.DataFrame(rows)
    return df.sort_values(["ticker", "data"]).reset_index(drop=True)


def _price_frame(data: dict[str, Any]) -> pd.DataFrame:
    storico = data.get("storico_prezzi", {}) or {}
    if isinstance(storico, pd.DataFrame):
        frame = storico.copy()
    elif isinstance(storico, dict):
        frame = pd.DataFrame.from_dict(storico, orient="index")
    else:
        return pd.DataFrame()
    if frame.empty:
        return pd.DataFrame()
    frame.index = pd.to_datetime(frame.index, errors="coerce")
    frame = frame[~frame.index.isna()].sort_index()
    for col in frame.columns:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame


def _ticker_type_and_name(ticker: str, lookup: dict[str, dict[str, Any]]) -> tuple[str, str, str]:
    item = lookup.get(ticker, {})
    tipo = str(item.get("tipo") or item.get("Tipologia") or "").strip()
    categoria = macro_cat(tipo)
    nome = str(item.get("nome") or item.get("name") or ticker).strip()
    return tipo, categoria, nome


def _explicit_pac_from_ops(ticker: str, ops: pd.DataFrame) -> bool:
    if ticker.upper().startswith("FAM-"):
        return True
    text = " ".join(str(v or "").lower() for v in ops.get("note", pd.Series(dtype=str)).tolist())
    return any(token in text for token in _EXPLICIT_PAC_TOKENS)


def _regularity_score(dates: pd.Series) -> float:
    ds = pd.to_datetime(dates, errors="coerce").dropna().sort_values()
    if len(ds) < 3:
        return 0.0
    deltas = ds.diff().dt.days.dropna()
    if deltas.empty:
        return 0.0
    monthly_like = deltas.between(20, 42).mean()
    quarterly_like = deltas.between(70, 105).mean()
    return float(max(monthly_like, quarterly_like))


def _state_and_priority(row: dict[str, Any]) -> tuple[str, str, str]:
    buys = int(row.get("n_acquisti", 0) or 0)
    margin = _safe_float(row.get("margine_pmc", 0.0))
    elasticity = _safe_float(row.get("elasticita_prossimo_acquisto", 0.0))
    efficiency = row.get("efficienza_accumulo")
    if buys < 3:
        return "Non significativo", "Bassa", "Meno di tre acquisti: il grafico PMC resta utile, ma non è ancora una vera analisi di accumulo."
    if margin < -0.03 and elasticity >= 0.08:
        return "Reattivo", "Alta", "Prezzo sotto PMC e posizione ancora molto manovrabile: nuovi acquisti possono incidere sul prezzo medio."
    if margin < -0.03:
        return "Sotto pressione", "Media", "Prezzo sotto PMC, ma l'effetto di un nuovo acquisto dipende dal capitale già investito."
    if elasticity < 0.05 and buys >= 12:
        return "Maturo", "Bassa", "Il PMC è ormai poco sensibile: nuovi acquisti aumentano soprattutto l'esposizione."
    if efficiency is not None and pd.notna(efficiency) and float(efficiency) >= 1.0 and margin >= 0:
        return "Efficiente", "Media", "PMC migliore o allineato alla media storica dei prezzi e margine positivo."
    if elasticity >= 0.08:
        return "Rafforzabile", "Alta", "Accumulo ancora elastico: un nuovo acquisto può modificare in modo percepibile il PMC."
    return "Da monitorare", "Media", "Accumulo leggibile, ma senza un segnale operativo netto."


def _current_price(ticker: str, lookup: dict[str, dict[str, Any]], prices: pd.DataFrame) -> float:
    item = lookup.get(ticker, {})
    price = _safe_float(item.get("prezzo", item.get("price", 0.0)))
    if price > 0:
        return price
    if ticker in prices.columns:
        series = pd.to_numeric(prices[ticker], errors="coerce").dropna()
        if not series.empty:
            return float(series.iloc[-1])
    return 0.0


def _build_ticker_series(ticker: str, ops: pd.DataFrame, prices: pd.DataFrame, current_price: float) -> pd.DataFrame:
    buys_and_sells = ops.sort_values("data").copy()
    if buys_and_sells.empty:
        return pd.DataFrame()
    start = pd.Timestamp(buys_and_sells["data"].min()).normalize()
    if ticker in prices.columns:
        price_series = pd.to_numeric(prices[ticker], errors="coerce").dropna().sort_index()
        price_series = price_series[price_series.index >= start]
    else:
        price_series = pd.Series(dtype=float)
    if price_series.empty:
        last_dt = pd.Timestamp(buys_and_sells["data"].max()).normalize()
        idx = pd.DatetimeIndex([start, last_dt]).unique().sort_values()
        price_series = pd.Series(current_price if current_price > 0 else np.nan, index=idx)
    for _, op in buys_and_sells.iterrows():
        dt = pd.Timestamp(op["data"]).normalize()
        if dt not in price_series.index:
            px = _safe_float(op.get("price"), np.nan)
            price_series.loc[dt] = px if px > 0 else np.nan
    price_series = price_series.sort_index().ffill()
    if current_price > 0:
        today = pd.Timestamp.today().normalize()
        if today not in price_series.index:
            price_series.loc[today] = current_price
    price_series = price_series.sort_index().ffill().dropna()
    if price_series.empty:
        return pd.DataFrame()

    events_by_date: dict[pd.Timestamp, list[dict[str, Any]]] = {}
    for _, op in buys_and_sells.iterrows():
        events_by_date.setdefault(pd.Timestamp(op["data"]).normalize(), []).append(op.to_dict())

    qty = 0.0
    invested = 0.0
    rows: list[dict[str, Any]] = []
    for dt, price in price_series.items():
        for op in events_by_date.get(pd.Timestamp(dt).normalize(), []):
            op_qty = _safe_float(op.get("qty"))
            op_price = _safe_float(op.get("price"))
            gross = _safe_float(op.get("importo_lordo"))
            if gross <= 0 and op_qty > 0 and op_price > 0:
                gross = op_qty * op_price
            total_cost = gross + _safe_float(op.get("commissioni")) + _safe_float(op.get("imposte"))
            if op.get("tipo") == "ACQUISTO":
                qty += op_qty
                invested += total_cost
            elif op.get("tipo") in {"VENDITA", "RIMBORSO A SCADENZA"} and op_qty > 0 and qty > 0:
                reduction = min(op_qty / qty, 1.0)
                invested *= max(0.0, 1.0 - reduction)
                qty = max(0.0, qty - op_qty)
        pmc = invested / qty if qty > 0 else np.nan
        value = qty * float(price) if qty > 0 else 0.0
        pl_abs = value - invested
        rows.append(
            {
                "Data": pd.Timestamp(dt),
                "Prezzo": float(price),
                "Quote": qty,
                "Capitale investito": invested,
                "PMC": pmc,
                "Controvalore": value,
                "P/L €": pl_abs,
                "P/L %": (pl_abs / invested) if invested > 0 else 0.0,
            }
        )
    return pd.DataFrame(rows)


def build_accumuli_analysis(
    data: dict[str, Any],
    *,
    min_purchases: int = 3,
    simulated_installment: float = 300.0,
) -> AccumuliResult:
    """Costruisce sintesi e dettaglio degli strumenti in logica PAC/accumulo.

    Sono inclusi solo FND/ETF/ETC con almeno ``min_purchases`` acquisti, salvo
    PAC espliciti riconosciuti da ticker/note. Gli strumenti non qualificabili
    non vengono cancellati dai dati: semplicemente non entrano nella scheda.
    """
    if not isinstance(data, dict):
        return AccumuliResult(pd.DataFrame(), {})
    ops = _normalise_operations(data)
    if ops.empty:
        return AccumuliResult(pd.DataFrame(), {})
    lookup = _instrument_lookup(data)
    prices = _price_frame(data)

    rows: list[dict[str, Any]] = []
    by_ticker: dict[str, dict[str, Any]] = {}
    for ticker, tk_ops_all in ops.groupby("ticker"):
        tk_ops = tk_ops_all.sort_values("data").reset_index(drop=True)
        buy_ops = tk_ops[tk_ops["tipo"] == "ACQUISTO"].copy()
        if buy_ops.empty:
            continue
        tipo, categoria, nome = _ticker_type_and_name(str(ticker), lookup)
        if categoria not in _ACCUMULATION_CATEGORIES:
            continue
        explicit = _explicit_pac_from_ops(str(ticker), buy_ops)
        regularity = _regularity_score(buy_ops["data"])
        buy_count = int(len(buy_ops))
        if buy_count < min_purchases and not explicit:
            continue

        current_px = _current_price(str(ticker), lookup, prices)
        series = _build_ticker_series(str(ticker), tk_ops, prices, current_px)
        if series.empty:
            continue
        latest = series.iloc[-1]
        qty = float(latest.get("Quote", 0.0) or 0.0)
        invested = float(latest.get("Capitale investito", 0.0) or 0.0)
        pmc = float(latest.get("PMC", np.nan)) if qty > 0 else np.nan
        value = float(latest.get("Controvalore", 0.0) or 0.0)
        pl_abs = value - invested
        pl_pct = pl_abs / invested if invested > 0 else 0.0
        current_px = current_px if current_px > 0 else float(latest.get("Prezzo", 0.0) or 0.0)
        margin_pmc = ((current_px - pmc) / current_px) if current_px > 0 and pd.notna(pmc) else np.nan
        price_values = pd.to_numeric(series["Prezzo"], errors="coerce").dropna() if "Prezzo" in series else pd.Series(dtype=float)
        price_mean = float(price_values.mean()) if not price_values.empty else np.nan
        price_max = float(price_values.max()) if not price_values.empty else np.nan
        pmc_percentile = (float((price_values <= pmc).mean()) if not price_values.empty and pd.notna(pmc) else np.nan)
        current_drawdown = ((current_px / price_max) - 1.0) if current_px > 0 and pd.notna(price_max) and price_max > 0 else np.nan
        efficiency = (price_mean / pmc) if pd.notna(price_mean) and pd.notna(pmc) and pmc > 0 else np.nan
        exec_prices = pd.to_numeric(buy_ops["price"], errors="coerce").dropna()
        cv_ops = float(exec_prices.std(ddof=0) / exec_prices.mean()) if len(exec_prices) >= 2 and exec_prices.mean() > 0 else np.nan
        avg_installment = float((buy_ops["importo_lordo"] + buy_ops["commissioni"] + buy_ops["imposte"]).replace(0, np.nan).dropna().median()) if buy_count else 0.0
        if not np.isfinite(avg_installment) or avg_installment <= 0:
            avg_installment = float(simulated_installment)
        # Elasticità residua del PMC: peso del prossimo acquisto simulato sul
        # capitale già investito. Non è un rendimento né una probabilità: misura
        # quanto il prezzo medio di carico è ancora manovrabile dai nuovi acquisti.
        # Può superare il 100% su posizioni embrionali o dati anomali.
        elasticita = float(simulated_installment / invested) if invested > 0 else np.nan
        tipo_accumulo = "PAC esplicito" if explicit else "Acquisti progressivi"
        row = {
            "ticker": str(ticker),
            "nome": nome,
            "tipo": tipo,
            "categoria": categoria,
            "tipo_accumulo": tipo_accumulo,
            "n_acquisti": buy_count,
            "regolarita": regularity,
            "capitale": invested,
            "controvalore": value,
            "pl_abs": pl_abs,
            "pl_pct": pl_pct,
            "quote": qty,
            "pmc": pmc,
            "prezzo_attuale": current_px,
            "margine_pmc": margin_pmc,
            "efficienza_accumulo": efficiency,
            "prezzo_medio_periodo": price_mean,
            "percentile_pmc": pmc_percentile,
            "drawdown_da_massimo": current_drawdown,
            "volatilita_acquisti": cv_ops,
            "importo_tipico_acquisto": avg_installment,
            "elasticita_prossimo_acquisto": elasticita,
            "prima_data": buy_ops["data"].min(),
            "ultima_data": buy_ops["data"].max(),
        }
        stato, priorita, diagnosis = _state_and_priority(row)
        row["stato"] = stato
        row["priorita"] = priorita
        row["diagnosi"] = diagnosis
        rows.append(row)
        by_ticker[str(ticker)] = {
            "summary": row,
            "series": series,
            "operations": buy_ops.sort_values("data", ascending=False).reset_index(drop=True),
        }

    if not rows:
        return AccumuliResult(pd.DataFrame(), by_ticker)
    summary = pd.DataFrame(rows)
    priority_rank = {"Alta": 0, "Media": 1, "Bassa": 2}
    summary["_priorita_rank"] = summary["priorita"].map(priority_rank).fillna(9)
    summary = summary.sort_values(["_priorita_rank", "categoria", "ticker"]).drop(columns=["_priorita_rank"]).reset_index(drop=True)
    return AccumuliResult(summary, by_ticker)


def simulate_next_installment(summary_row: dict[str, Any] | pd.Series, amount: float) -> dict[str, Any]:
    """Simula un nuovo acquisto al prezzo attuale senza modificare i dati reali."""
    if isinstance(summary_row, pd.Series):
        source = summary_row.to_dict()
    else:
        source = dict(summary_row or {})
    amount = max(_safe_float(amount), 0.0)
    price = _safe_float(source.get("prezzo_attuale"))
    qty = _safe_float(source.get("quote"))
    invested = _safe_float(source.get("capitale"))
    pmc_before = _safe_float(source.get("pmc"), np.nan)
    if amount <= 0 or price <= 0:
        return {"amount": amount, "new_qty": 0.0, "new_pmc": pmc_before, "pmc_delta": 0.0, "margin_after": source.get("margine_pmc"), "portfolio_weight_impact": None}
    new_qty = amount / price
    total_qty = qty + new_qty
    total_invested = invested + amount
    new_pmc = total_invested / total_qty if total_qty > 0 else np.nan
    pmc_delta = ((new_pmc / pmc_before) - 1.0) if pd.notna(pmc_before) and pmc_before > 0 else np.nan
    margin_after = ((price - new_pmc) / price) if price > 0 and pd.notna(new_pmc) else np.nan
    return {
        "amount": amount,
        "new_qty": new_qty,
        "new_pmc": new_pmc,
        "pmc_delta": pmc_delta,
        "margin_after": margin_after,
        "portfolio_weight_impact": None,
    }


__all__ = ["AccumuliResult", "build_accumuli_analysis", "simulate_next_installment"]
