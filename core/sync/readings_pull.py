"""Letture intraday del Mobile (TM-06): scarico nell'archivio locale e conferma al Worker.

Il Worker 1.5.9 aggiunge a `GET /api/v2/observations` il campo opzionale `readings` (tutte le letture della giornata, ordinate
per `seq`, al massimo 500 per risposta) e offre `POST /api/v2/observations/ack` con `{"upTo": seq}`, che cancella dal Mobile
solo le letture fino a quel progressivo.

Regole del Desktop:
- le letture si scrivono in `data/cache/letture_intraday.sqlite3` (chiave unica strumento + istante di mercato, mai doppioni);
  **la conferma parte solo se la scrittura è riuscita** (scrittura «stretta»: un errore blocca la conferma e le letture
  restano sul Mobile, che le riproporrà);
- stesse regole di validità dei prezzi importati: strumento noto, simbolo coerente, valuta euro, unità corretta, prezzo positivo,
  istante di mercato con l'ora; una lettura scartata è comunque «consumata» (la conferma la comprende), altrimenti resterebbe
  per sempre sul Mobile;
- `truncated: true` = il Mobile ha dovuto scartare letture vecchie: si registra una lacuna (visibile nel Termometro), senza
  inventare i prezzi mancanti;
- un Worker senza `readings` o senza endpoint di conferma lascia tutto com'era; una conferma persa o ripetuta non crea doppioni;
- non tocca il portafoglio, né i prezzi, né la contabilità: scrive solo l'archivio delle letture.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core import readings_store
from core.sync.snapshot import quote_symbol, to_iso
from core.sync.transport import TransportRefused

logger = logging.getLogger("portafoglio.sync")

ACK_ENDPOINT = "/api/v2/observations/ack"
MAX_PAGES = 50          # 50 × 500 = 25.000 letture per controllo: oltre il tetto di conservazione del Mobile (20.000)
PAGE_SIZE = 500


def _rome_ts(iso: str) -> str | None:
    """Istante di mercato (UTC ISO) -> `AAAA-MM-GG HH:MM` ora di Roma, come nell'archivio. None senza ora."""
    text = str(iso or "").strip()
    if len(text) <= 10:
        return None
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        when = when.astimezone(ZoneInfo("Europe/Rome"))
    except Exception:  # noqa: BLE001
        pass
    return when.strftime("%Y-%m-%d %H:%M")


def _expected_symbol(instrument: dict[str, Any]) -> str:
    if str(instrument.get("ticker") or "").startswith("BTP-"):
        return str(instrument.get("isin") or "").strip().upper()
    try:
        return str(quote_symbol(instrument) or "").strip().upper()
    except ValueError:
        return ""


def _accept(data: dict[str, Any], by_ticker: dict[str, dict[str, Any]], reading: dict[str, Any]) -> tuple[str, str, float, str] | None:
    """Riga (ticker, ts, prezzo, fonte) se la lettura è valida, altrimenti None."""
    ticker = str(reading.get("ticker") or "")
    instrument = by_ticker.get(ticker)
    if instrument is None:
        return None
    want_unit = "PCT_NOMINALE" if ticker.startswith("BTP-") else "EUR"
    if str(reading.get("unit") or "") != want_unit or str(reading.get("currency") or "").upper() != "EUR":
        return None
    symbol = _expected_symbol(instrument)
    if not symbol or str(reading.get("symbol") or "").strip().upper() != symbol:
        return None
    try:
        price = float(reading.get("price"))
    except (TypeError, ValueError):
        return None
    raw_time = str(reading.get("marketTime") or "").strip()
    ts = _rome_ts(to_iso(raw_time) or "") if len(raw_time) > 10 else None      # senza l'ora non è una lettura di giornata
    if ts is None or not price > 0 or price != price:
        return None
    return ticker, ts, price, "Mobile"


def _seq(reading: dict[str, Any]) -> int | None:
    value = reading.get("seq")
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def pull(transport, payload: dict[str, Any] | None, data: dict[str, Any], *, ack_path: str = ACK_ENDPOINT,
         observations_path: str = "/api/v2/observations", log_path: str | Path | None = None) -> dict[str, Any]:
    """Scarica le letture presenti in `payload` (la risposta già letta) e le pagine successive, poi conferma. Non solleva mai.

    Esito: `{supported, stored, rejected, acked, pages, truncated, error}`."""
    out: dict[str, Any] = {"supported": False, "stored": 0, "rejected": 0, "acked": None, "pages": 0, "truncated": False, "error": None}
    if not isinstance(payload, dict) or not isinstance(payload.get("readings"), list):
        return out                                  # Worker precedente: nessuna lettura, nessun cambiamento
    out["supported"] = True
    by_ticker = {str(i.get("ticker")): i for i in (data or {}).get("strumenti", []) if isinstance(i, dict) and i.get("ticker")}
    last_acked = -1
    try:
        for _ in range(MAX_PAGES):
            out["pages"] += 1
            if payload.get("truncated") and not out["truncated"]:
                out["truncated"] = True
                readings_store.add_gap("il Mobile ha scartato letture vecchie (limite di conservazione): possibili buchi nelle candele")
                logger.warning("Letture del Mobile: risposta troncata, registrata una lacuna")
            items = [r for r in payload.get("readings") or [] if isinstance(r, dict)]
            seqs = [s for s in (_seq(r) for r in items) if s is not None]
            if not seqs:
                break
            rows, rejected = [], 0
            for r in items:
                row = _accept(data, by_ticker, r) if _seq(r) is not None else None
                if row is None:
                    rejected += 1
                else:
                    rows.append(row)
            readings_store.add_readings(rows, strict=True)          # se fallisce: eccezione, nessuna conferma
            out["stored"] += len(rows)
            out["rejected"] += rejected
            upto = max(seqs)
            if upto <= last_acked:
                break                                               # nessun progresso: niente giri a vuoto
            # il Worker 1.5.9 non accetta il corpo compresso sulla conferma (400 «ACK JSON non valido», provato sul Worker di prova)
            transport.post(ack_path, json.dumps({"upTo": upto}).encode("utf-8"), gzip_body=False)
            last_acked = out["acked"] = upto
            if len(items) < PAGE_SIZE:
                break
            payload = transport.get_json(observations_path)
            if not isinstance(payload, dict) or not isinstance(payload.get("readings"), list):
                break
    except (RuntimeError, TransportRefused) as exc:
        out["error"] = f"comunicazione interrotta: {exc}"       # le letture non confermate restano sul Mobile e ritorneranno
        logger.warning("Letture del Mobile: %s", out["error"])
    except Exception as exc:  # noqa: BLE001 - un errore di scrittura impedisce la conferma
        out["error"] = f"{type(exc).__name__}: {exc}"
        logger.exception("Letture del Mobile non archiviate: nessuna conferma inviata")
    if log_path and (out["stored"] or out["rejected"] or out["error"] or out["truncated"]):
        try:
            path = Path(log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps({"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **out}, sort_keys=True) + "\n")
        except OSError:
            logger.exception("Registro delle letture del Mobile non scritto")
    return out
