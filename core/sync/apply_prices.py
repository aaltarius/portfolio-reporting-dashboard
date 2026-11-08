"""Importa nel Desktop i prezzi più recenti trovati dal Mobile (regola approvata: vince la data di mercato più recente).

Si applica SOLO ciò che `observations.evaluate` accetta: valuta in euro, simbolo coerente, unità corretta (euro per le
azioni/ETF, percentuale del nominale per i BTP), data di mercato successiva a quella del Desktop, scostamento entro le soglie
(10% oppure 3 punti per i titoli di Stato). Dell'istante cambiano solo `prezzo` e `aggiornato` (data di mercato); `fonte`, storico e
operazioni non si toccano. I dati si rileggono dal disco al momento dell'applicazione e si salvano con il percorso normale
(`load_data` → modifica → `save_data`, che unisce eventuali scritture concorrenti della sessione aperta).
Ogni decisione (applicata o scartata, con il motivo) finisce nel registro locale `observations_log.jsonl`."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from core.sync import observations as obs

logger = logging.getLogger("portafoglio.sync")


def _market_day(iso: str) -> str:
    when = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    try:
        from zoneinfo import ZoneInfo
        when = when.astimezone(ZoneInfo("Europe/Rome"))
    except Exception:  # noqa: BLE001
        pass
    return when.strftime("%Y-%m-%d")


def apply(observations: list[dict], *, load=None, save=None, log_path=None, now: datetime | None = None) -> dict:
    """Applica i prezzi accettati. Restituisce {applied, items, error}; non solleva mai."""
    now = now or datetime.now(timezone.utc)
    try:
        if load is None or save is None:
            from persistence.storage import load_data, save_data
            load = load or load_data
            save = save or (lambda d: save_data(d, include_storico=False, automatic=True))
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
            if item["decision"] == "newer_on_mobile":
                inst = by_ticker[item["ticker"]]
                new_day = _market_day(item["cloudMarketTime"])
                old_price, old_day = inst.get("prezzo"), inst.get("aggiornato")
                inst["prezzo"], inst["aggiornato"] = item["cloudPrice"], new_day
                applied.append({"ticker": item["ticker"], "old": old_price, "new": item["cloudPrice"], "date": new_day})
                record.update(decision="applied", oldPrice=old_price, oldDate=old_day, newPrice=item["cloudPrice"], newDate=new_day,
                              marketTime=item["cloudMarketTime"])
            else:
                record.update(decision="rejected", reasons=item.get("reasons", []))
            records.append(record)
        if applied:
            save(data)
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
