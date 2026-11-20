"""Archivio incrementale delle letture di prezzo (TM-05): una riga per strumento e istante di mercato.

SQLite locale in `data/cache/` (dato personale: mai in git, mai online). Si aggiunge solo con
«inserisci se non esiste» sulla chiave (strumento, istante di mercato): la stessa lettura vista dal Desktop e
dal Mobile, o riletta dopo, non crea doppioni e nulla si rigenera. Alimenta le candele del Termometro
(`core/services/portfolio_candles.py`). Tutte le funzioni di scrittura non sollevano mai: l'archivio è un di più
e non deve rompere un aggiornamento delle quotazioni.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from typing import Any, Iterable

from core.volume_policy import READINGS_RETENTION_DAYS

logger = logging.getLogger("portafoglio.readings")

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: Percorso dell'archivio. I test lo sostituiscono con `monkeypatch` (fixture autouse in tests/conftest.py).
READINGS_DB_PATH: str = os.path.join(_BASE_DIR, "data", "cache", "letture_intraday.sqlite3")

_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}")


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(READINGS_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(READINGS_DB_PATH, timeout=10)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS letture ("
        "ticker TEXT NOT NULL, ts TEXT NOT NULL, prezzo REAL NOT NULL, fonte TEXT NOT NULL DEFAULT '', "
        "registrato_il TEXT NOT NULL, PRIMARY KEY (ticker, ts))"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_letture_ts ON letture (ts)")
    conn.execute("CREATE TABLE IF NOT EXISTS lacune (registrato_il TEXT NOT NULL, nota TEXT NOT NULL DEFAULT '')")
    return conn


def _source_family(source: Any) -> str:
    """«Yahoo [XYZ.MI]» → «Yahoo»: del fornitore interessa la famiglia, non il simbolo."""
    return str(source or "").split("[")[0].strip()


def normalize_ts(value: Any) -> str | None:
    """Istante di mercato nel formato `AAAA-MM-GG HH:MM`; None se non ha l'ora (una lettura senza ora non è una lettura di giornata)."""
    text = str(value or "").strip()
    if not _TS_RE.match(text):
        return None
    return text[:10] + " " + text[11:16]


def rows_from_quotes_log_items(items: Iterable[dict[str, Any]]) -> list[tuple[str, str, float, str]]:
    """Dalle voci del registro quotazioni (`price_date` = istante di mercato) alle righe (ticker, ts, prezzo, fonte)."""
    rows: list[tuple[str, str, float, str]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "").strip()
        ts = normalize_ts(item.get("price_date"))
        try:
            price = float(item.get("price"))
        except (TypeError, ValueError):
            continue
        if not ticker or ts is None or not price > 0 or str(item.get("status") or "") == "error":
            continue
        rows.append((ticker, ts, price, _source_family(item.get("source"))))
    return rows


def add_readings(rows: Iterable[tuple[str, str, float, str]], *, now: datetime | None = None, strict: bool = False) -> int:
    """Aggiunge le letture mancanti e ne restituisce il numero effettivamente inserito. Non solleva mai,
    salvo con `strict=True` (usato prima di confermare al Mobile: un errore di scrittura deve impedire la conferma)."""
    rows = list(rows)
    if not rows:
        return 0
    stamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    try:
        with closing(_connect()) as conn, conn:
            before = conn.total_changes
            conn.executemany(
                "INSERT OR IGNORE INTO letture (ticker, ts, prezzo, fonte, registrato_il) VALUES (?, ?, ?, ?, ?)",
                [(t, ts, float(p), src, stamp) for t, ts, p, src in rows],
            )
            return conn.total_changes - before
    except Exception:  # noqa: BLE001 - l'archivio è un di più
        if strict:
            raise
        logger.exception("Archivio letture non aggiornato")
        return 0


def add_gap(note: str, *, now: datetime | None = None) -> None:
    """Registra una lacuna dichiarata dalla fonte (es. letture del Mobile scartate per il tetto di conservazione). Non solleva mai."""
    try:
        with closing(_connect()) as conn, conn:
            conn.execute("INSERT INTO lacune (registrato_il, nota) VALUES (?, ?)",
                         ((now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"), str(note)[:300]))
    except Exception:  # noqa: BLE001
        logger.exception("Lacuna delle letture non registrata")


def last_gap_day(since_day: str | None = None) -> str | None:
    """Giorno (AAAA-MM-GG) dell'ultima lacuna registrata, dal giorno indicato in poi; None se non ce ne sono."""
    if not os.path.exists(READINGS_DB_PATH):
        return None
    try:
        with closing(_connect()) as conn:
            row = conn.execute("SELECT MAX(registrato_il) FROM lacune WHERE registrato_il >= ?", (str(since_day or "")[:10],)).fetchone()
        return str(row[0])[:10] if row and row[0] else None
    except Exception:  # noqa: BLE001
        return None


def add_from_quotes_log_items(items: Iterable[dict[str, Any]]) -> int:
    return add_readings(rows_from_quotes_log_items(items))


def read_since(first_day: str) -> list[tuple[str, str, float]]:
    """Letture (ticker, ts, prezzo) dal giorno indicato (incluso) in poi, in ordine di tempo. [] se l'archivio non c'è o non si legge."""
    if not os.path.exists(READINGS_DB_PATH):
        return []
    try:
        with closing(_connect()) as conn:
            return [(t, ts, float(p)) for t, ts, p in conn.execute(
                "SELECT ticker, ts, prezzo FROM letture WHERE ts >= ? ORDER BY ts, ticker", (str(first_day)[:10],))]
    except Exception:  # noqa: BLE001
        logger.exception("Archivio letture non leggibile")
        return []


def revision() -> str:
    """Impronta leggera dell'archivio per le firme delle cache: numero di righe e ultimo istante."""
    if not os.path.exists(READINGS_DB_PATH):
        return "0|"
    try:
        with closing(_connect()) as conn:
            count, last = conn.execute("SELECT COUNT(*), COALESCE(MAX(ts), '') FROM letture").fetchone()
            gaps = conn.execute("SELECT COUNT(*) FROM lacune").fetchone()[0]
        return f"{count}|{last}" + (f"|g{gaps}" if gaps else "")
    except Exception:  # noqa: BLE001
        return "err|"


def prune(*, today: datetime | None = None, days: int = READINGS_RETENTION_DAYS) -> int:
    """Toglie le letture più vecchie del tetto di retention (solo per data). Non solleva mai."""
    limit = ((today or datetime.now()) - timedelta(days=int(days))).strftime("%Y-%m-%d")
    if not os.path.exists(READINGS_DB_PATH):
        return 0
    try:
        with closing(_connect()) as conn, conn:
            before = conn.total_changes
            conn.execute("DELETE FROM letture WHERE ts < ?", (limit,))
            return conn.total_changes - before
    except Exception:  # noqa: BLE001
        logger.exception("Potatura dell'archivio letture non riuscita")
        return 0


def ensure_initial_backfill(quotes_log: dict[str, Any] | None) -> int:
    """Alla prima volta (archivio ancora inesistente) porta dentro le letture già nel registro quotazioni. Poi non fa più nulla."""
    if os.path.exists(READINGS_DB_PATH):
        return 0
    return backfill_from_quotes_log(quotes_log)


def backfill_from_quotes_log(quotes_log: dict[str, Any] | None) -> int:
    """Riempimento iniziale: porta nell'archivio le letture ancora presenti nel registro quotazioni (idempotente)."""
    return add_from_quotes_log_items((quotes_log or {}).get("items", []))
