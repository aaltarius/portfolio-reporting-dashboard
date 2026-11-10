"""Importa nel Desktop i prezzi più recenti trovati dal Mobile (regola approvata: vince la data di mercato più recente).

Si applica SOLO ciò che `observations.evaluate` accetta: valuta in euro, simbolo coerente, unità corretta (euro per le
azioni/ETF, percentuale del nominale per i BTP), data di mercato successiva a quella del Desktop, scostamento entro le soglie
(10% oppure 3 punti per i titoli di Stato). Dell'istante cambiano `prezzo` e `aggiornato` (data di mercato); `fonte` e operazioni non si toccano. Come nel refresh
manuale, il prezzo entra anche nello storico alla data di mercato e si aggiornano `last_quotes_update` e il registro quotazioni. I dati si rileggono dal disco al momento dell'applicazione e si salvano con il percorso normale
(`load_data` → modifica → `save_data`, che unisce eventuali scritture concorrenti della sessione aperta).
Ogni decisione (applicata o scartata, con il motivo) finisce nel registro locale `observations_log.jsonl`."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from core.sync import observations as obs

logger = logging.getLogger("portafoglio.sync")


def _market_stamp(iso: str, like: object) -> str:
    """Data (e ora, ora di Roma) di mercato nello stesso formato che il Desktop usa già in `aggiornato`."""
    when = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    try:
        from zoneinfo import ZoneInfo
        when = when.astimezone(ZoneInfo("Europe/Rome"))
    except Exception:  # noqa: BLE001
        pass
    return when.strftime("%Y-%m-%d %H:%M") if len(str(like or "").strip()) > 10 else when.strftime("%Y-%m-%d")


def _log_import_in_quotes_log(applied: list[dict], stamp: str) -> None:
    """Riflette l'importazione nel registro quotazioni (tabella e box «Ultimo refresh»), con fonte «Mobile». Non solleva mai."""
    try:
        from persistence.storage import load_quotes_log, save_quotes_log
        log = load_quotes_log()
        items = []
        for a in applied:
            prev = a.get("prev")
            try:
                delta = float(a["new"]) / float(prev) - 1.0 if prev not in (None, "") and float(prev) != 0 else None
            except (TypeError, ValueError):
                delta = None
            items.append({"timestamp": stamp, "ticker": a["ticker"], "instrument_name": a.get("name") or a["ticker"], "source": "Mobile",
                          "status": "ok", "price": float(a["new"]), "previous_price": None if prev in (None, "") else float(prev),
                          "delta_pct": delta, "warning": "", "fallback_used": False, "price_date": a.get("stamp") or a["date"],
                          "latest_history_date": str(a["date"])[:10]})
        log["last_refresh"] = stamp
        log["last_refresh_source"] = f"Mobile · {len(applied)} {'prezzo' if len(applied) == 1 else 'prezzi'}"
        log["items"] = items + list(log.get("items", []))[:200]
        save_quotes_log(log)
    except Exception:  # noqa: BLE001 - il registro è un di più
        logger.exception("Registro quotazioni non aggiornato dopo l'importazione dal Mobile")


def _previous_close(storico: dict, ticker: str, market_day: str, fallback):
    """Ultima chiusura nello storico strettamente precedente al giorno di mercato (come il «prezzo precedente» del refresh manuale)."""
    for day in sorted((d for d in storico if str(d) < market_day), reverse=True):
        value = (storico.get(day) or {}).get(ticker)
        if value not in (None, ""):
            return value
    return fallback


def fill_missing_history(data: dict) -> list[str]:
    """Scrive nello storico il prezzo corrente degli strumenti il cui `aggiornato` cade nell'ultimo giorno dello storico (o dopo)
    ma che in quel giorno non hanno una riga. Senza, Desktop e Mobile calcolano l'«ultima seduta» con insiemi di prezzi diversi
    (il Mobile usa il prezzo corrente, il Desktop lo storico). Non tocca i giorni passati né i valori già presenti."""
    storico = data.setdefault("storico_prezzi", {})
    days = [d for d in storico if isinstance(d, str) and len(d) == 10]
    if not days:
        return []
    last_day = max(days)
    filled = []
    for inst in data.get("strumenti", []):
        if not isinstance(inst, dict):
            continue
        day = str(inst.get("aggiornato") or "")[:10]
        try:
            price = float(inst.get("prezzo"))
        except (TypeError, ValueError):
            continue
        ticker = str(inst.get("ticker") or "")
        if ticker and len(day) == 10 and day >= last_day and price > 0 and (storico.get(day) or {}).get(ticker) in (None, ""):
            storico.setdefault(day, {})[ticker] = price
            filled.append(ticker)
    return filled


def reconcile_now(*, load=None, save=None) -> list[str]:
    """Allinea lo storico ai prezzi correnti (vedi `fill_missing_history`) e salva solo se serve. Non solleva mai."""
    try:
        if load is None or save is None:
            from persistence.storage import load_data, save_data
            load = load or load_data
            save = save or (lambda d: save_data(d, include_storico=True, automatic=True))
        data = load()
        filled = fill_missing_history(data)
        if filled:
            save(data)
            logger.info("Storico prezzi allineato ai prezzi correnti: %d strumenti (%s)", len(filled), ", ".join(filled))
        return filled
    except Exception:  # noqa: BLE001
        logger.exception("Allineamento dello storico non riuscito")
        return []


def apply(observations: list[dict], *, load=None, save=None, log_path=None, now: datetime | None = None,
          now_local: datetime | None = None) -> dict:
    """Applica i prezzi accettati. Restituisce {applied, items, error}; non solleva mai."""
    now = now or datetime.now(timezone.utc)
    update_quotes_log = load is None and save is None     # con load/save iniettati (test) non si scrive in nessun file reale
    try:
        if load is None or save is None:
            from persistence.storage import load_data, save_data
            load = load or load_data
            save = save or (lambda d: save_data(d, include_storico=True, automatic=True))
        data = load()
        items = obs.evaluate(data, observations)
        by_ticker = {str(s.get("ticker")): s for s in data.get("strumenti", []) if isinstance(s, dict)}
        by_obs = {}
        for o in observations:
            by_obs.setdefault(str(o.get("ticker")), o)
        applied, records = [], []
        for item in items:
            record = {"at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "ticker": item["ticker"], "kind": item.get("kind")}
            src = by_obs.get(item["ticker"], {})
            record["provider"] = src.get("provider")
            record["observed"] = {k: src.get(k) for k in ("symbol", "price", "currency", "unit", "marketTime", "fetchedAt")}
            if item["decision"] == "newer_on_mobile":
                inst = by_ticker[item["ticker"]]
                old_price, old_day = inst.get("prezzo"), inst.get("aggiornato")
                new_day = _market_stamp(item["cloudMarketTime"], old_day)
                inst["prezzo"], inst["aggiornato"] = item["cloudPrice"], new_day
                full_day = _market_stamp(item["cloudMarketTime"], "0000-00-00 00:00")      # con l'ora, per la tabella Quotazioni
                applied.append({"ticker": item["ticker"], "old": old_price, "new": item["cloudPrice"], "date": new_day, "stamp": full_day,
                                "name": inst.get("nome"), "prev": _previous_close(data.get("storico_prezzi") or {}, item["ticker"],
                                                                                  full_day[:10], old_price)})
                record.update(decision="applied", oldPrice=old_price, oldDate=old_day, newPrice=item["cloudPrice"], newDate=new_day,
                              marketTime=item["cloudMarketTime"])
            else:
                record.update(decision="rejected", reasons=item.get("reasons", []))
            records.append(record)
        if applied:
            # Come il refresh manuale: il prezzo entra nello storico alla data di mercato (da lì Portafoglio e Quotazioni
            # ricavano l'ultimo giorno operativo) e l'orario dell'ultimo aggiornamento quotazioni viene aggiornato.
            storico = data.setdefault("storico_prezzi", {})
            for a in applied:
                try:
                    price = float(a["new"])
                except (TypeError, ValueError):
                    continue
                if price > 0:
                    storico.setdefault(str(a["date"])[:10], {})[a["ticker"]] = price
            fill_missing_history(data)
            local_now = datetime.now() if now_local is None else now_local
            data["last_quotes_update"] = local_now.strftime("%Y-%m-%d %H:%M:%S")
            save(data)
            if update_quotes_log:
                _log_import_in_quotes_log(applied, data["last_quotes_update"])
            logger.info("Prezzi importati dal Mobile: %d (%s)", len(applied), ", ".join(a["ticker"] for a in applied))
        if log_path and records:
            path = Path(log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as handle:
                for record in records:
                    handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return {"applied": applied, "items": items, "error": None}
    except Exception as exc:  # noqa: BLE001 - l'importazione non deve mai rompere l'avvio
        logger.exception("Importazione dei prezzi del Mobile non riuscita")
        return {"applied": [], "items": [], "error": f"{type(exc).__name__}: {exc}"}
