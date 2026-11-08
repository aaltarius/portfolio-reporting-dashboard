"""Fotografia del portafoglio nel formato `sestante.mobile.snapshot.v1`, calcolata in memoria.

Usa il motore canonico (`compute_portfolio_state`) invece di replicarne le formule; il formato e la
revisione (SHA-256 del JSON canonico) coincidono con quelli dell'esportatore attuale del Mobile, così
la parità si può verificare. Non scrive nulla e non modifica i dati ricevuti."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import math
import re

from core.domain.positions import compute_portfolio_state
from persistence.storage import get_registro_eventi

SCHEMA = "sestante.mobile.snapshot.v1"
_YAHOO = re.compile(r"Yahoo\s*\[([A-Za-z0-9.^_=-]{1,30})\]", re.I)
_SYMBOL = re.compile(r"[A-Z0-9^][A-Z0-9.^_=-]{0,29}")


def _local_tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Rome")
    except Exception:
        return dt.datetime.now().astimezone().tzinfo


def to_iso(text) -> str | None:
    if not text:
        return None
    try:
        d = dt.datetime.fromisoformat(str(text).strip())
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_local_tz())
    return d.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def quote_symbol(instrument: dict) -> str | None:
    ticker = str(instrument.get("ticker") or "").strip()
    if ticker.startswith("BTP-"):
        return None
    match = _YAHOO.search(str(instrument.get("fonte") or ""))
    symbol = (match.group(1) if match else ticker).upper()
    if not _SYMBOL.fullmatch(symbol):
        raise ValueError(f"Simbolo di quotazione non valido per {ticker}.")
    return symbol


def canonical_sha256(payload: dict) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_snapshot(data: dict, *, source_bytes: bytes | None = None) -> dict:
    """Costruisce la fotografia. Solleva ValueError se i dati non permettono un export affidabile."""
    work = copy.deepcopy(data)  # il motore aggiorna cache_posizioni: mai sui dati del chiamante
    work["cache_posizioni"] = {}
    events = get_registro_eventi(work)
    if not events:
        raise ValueError("Registro eventi vuoto: nessuna fotografia.")
    ids = [e["event_id"] for e in events]
    if len(ids) != len(set(ids)):
        raise ValueError("Registro eventi con identificativi duplicati.")
    tickers = [s.get("ticker") for s in work.get("strumenti", []) if isinstance(s, dict) and s.get("ticker")]
    if len(tickers) != len(set(tickers)):
        raise ValueError("Ticker duplicati negli strumenti.")
    source_at = to_iso(work.get("last_quotes_update"))
    if not source_at:
        raise ValueError("Data dell'ultimo aggiornamento quotazioni assente o non valida.")

    state = compute_portfolio_state(work, include_closed=False)
    by_ticker = {s["ticker"]: s for s in work["strumenti"] if isinstance(s, dict) and s.get("ticker")}
    positions = []
    for _, row in state["df"].iterrows():
        tk = row["Ticker"]
        qty, cost, price, value = (float(row[k]) for k in ("Quote", "Costo", "Prezzo", "Controvalore"))
        if not all(math.isfinite(v) for v in (qty, cost, price, value)) or price <= 0 or cost < 0 or value < 0:
            raise ValueError(f"Prezzo o posizione non valida per {tk}.")
        info = by_ticker[tk]
        pos = {
            "ticker": tk, "name": str(info.get("nome") or tk)[:180], "category": str(info.get("tipo") or "")[:80],
            "isin": str(info.get("isin") or "")[:20], "qty": qty, "cost": cost, "price": price, "value": value,
            "priceObservedAt": to_iso(info.get("aggiornato")),
        }
        symbol = quote_symbol(info)
        if symbol:
            pos["quoteSymbol"] = symbol
        positions.append(pos)
    if not positions:
        raise ValueError("Nessuna posizione attiva da esportare.")

    raw = source_bytes if source_bytes is not None else json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    snap = {
        "schema": SCHEMA,
        "portfolioId": str(work.get("portfolio_id") or "main"),
        "sourceUpdatedAt": source_at,
        "sourceFileSha256": hashlib.sha256(raw).hexdigest(),
        "sourceEventCount": len(events),
        "sourceOperationCount": len(work.get("operazioni") or []),
        "sourceLastEventDate": max(str(e.get("data") or "") for e in events),
        "masterCount": len(by_ticker),
        "cash": float(state["liquidita"]),
        "positions": positions,
    }
    snap["revision"] = canonical_sha256(snap)
    return snap
