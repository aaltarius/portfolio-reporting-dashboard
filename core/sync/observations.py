"""Prezzi rilevati dal Mobile (osservazioni cloud): lettura, valutazione con la regola approvata e QUARANTENA.

Il Mobile può rilevare quotazioni per conto suo (pulsante «aggiorna»). Il Desktop le legge dal Worker
(`GET /api/v2/observations`, da realizzare lato Mobile: specifica 05, §17), le confronta con il proprio prezzo con
`core.sync.policy.choose_price` (vince la data di mercato più recente; scartati simbolo diverso, valuta diversa da euro,
data più vecchia, prezzo non valido, scostamento anomalo) e salva l'esito in `data/cache/sync_v2/observations.json`.

NON modifica il portafoglio né i prezzi del Desktop: l'applicazione dei prezzi accettati è la Fase 3 e richiede le
decisioni dell'utente sulle soglie (provvisorie: 10% e 3 punti per i titoli di Stato) e sull'unità dei BTP."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from core.sync import policy
from core.sync.transport import TransportRefused
from core.sync.snapshot import quote_symbol, to_iso

ENDPOINT = "/api/v2/observations"
SAME_QUOTE_MARGIN = timedelta(minutes=10)   # il Desktop salva l'ora al minuto: una rilevazione più recente di pochi minuti è la stessa quotazione


def fetch(transport, path: str = ENDPOINT) -> list[dict] | None:
    """Elenco delle osservazioni del Mobile, oppure None se il Worker non offre ancora l'endpoint."""
    try:
        payload = transport.get_json(path)
    except (RuntimeError, TransportRefused):          # endpoint assente, rifiutato (es. catalogo oltre il limite) o guasto: nessun prezzo
        return None
    items = payload.get("observations")
    return [o for o in items if isinstance(o, dict)] if isinstance(items, list) else None


def _desktop_observation(instrument: dict) -> tuple[policy.Observation, str] | None:
    """Prezzo del Desktop come osservazione. Simbolo atteso: il simbolo di quotazione per azioni/ETF/fondi, l'ISIN per i titoli
    di Stato (il Mobile li interroga per ISIN e dichiara l'ISIN reale in `symbol`)."""
    raw = str(instrument.get("aggiornato") or "").strip()
    # Il Desktop conosce la sola DATA di mercato: un prezzo del Mobile della stessa data non lo sostituisce (fine giornata).
    when = to_iso(raw + "T23:59:59" if len(raw) == 10 else raw)
    try:
        if str(instrument.get("ticker") or "").startswith("BTP-"):
            symbol = str(instrument.get("isin") or "").strip().upper()
        else:
            symbol = quote_symbol(instrument)
        price = float(instrument.get("prezzo"))
    except (TypeError, ValueError):
        return None
    if not symbol or not when:
        return None
    base = when
    if when:
        when = (datetime.fromisoformat(when.replace("Z", "+00:00")) + (timedelta() if len(raw) == 10 else SAME_QUOTE_MARGIN)).astimezone(
            timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return policy.Observation("desktop", symbol, price, "EUR", when, when), base


def _rome_day(iso: str) -> str:
    when = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    try:
        from zoneinfo import ZoneInfo
        when = when.astimezone(ZoneInfo("Europe/Rome"))
    except Exception:  # noqa: BLE001
        pass
    return when.strftime("%Y-%m-%d")


def evaluate(data: dict, observations: list[dict]) -> list[dict]:
    """Per ogni strumento con osservazioni del Mobile: decisione e motivo. Nessuna scrittura."""
    by_ticker = {str(i.get("ticker")): i for i in data.get("strumenti", []) if isinstance(i, dict) and i.get("ticker")}
    out = []
    for ticker in sorted({str(o.get("ticker")) for o in observations if o.get("ticker")}):
        instrument = by_ticker.get(ticker)
        if instrument is None:
            continue
        built = _desktop_observation(instrument)
        if built is None:
            if ticker.startswith("BTP-") and not str(instrument.get("isin") or "").strip():
                out.append({"ticker": ticker, "decision": "not_newer", "reasons": ["isin_missing"], "kind": "bond"})
            continue
        desk, desk_base = built
        cloud, bad_unit = [], 0
        want_unit = "PCT_NOMINALE" if ticker.startswith("BTP-") else "EUR"
        for o in (o for o in observations if str(o.get("ticker")) == ticker):
            if str(o.get("unit") or "") != want_unit:          # euro per quota / percentuale del nominale: mai confonderle
                bad_unit += 1
                continue
            try:
                cloud.append(policy.Observation("cloud", str(o.get("symbol") or "").strip().upper(), float(o.get("price")),
                                                str(o.get("currency") or ""), to_iso(o.get("marketTime")) or "",
                                                to_iso(o.get("fetchedAt")) or ""))
            except (TypeError, ValueError):
                continue
        kind = "bond" if ticker.startswith("BTP-") else "equity"
        choice = policy.choose_price(cloud + [desk], expected_symbol=desk.symbol, kind=kind)
        if (choice.applied is not None and choice.applied.source == "cloud"
                and abs(choice.applied.price - desk.price) < 1e-9 and _rome_day(choice.applied.market_time) == _rome_day(desk_base)):
            out.append({"ticker": ticker, "decision": "not_newer", "reasons": ["no_change"], "kind": kind})
        elif choice.applied is not None and choice.applied.source == "cloud":
            out.append({"ticker": ticker, "decision": "newer_on_mobile", "cloudPrice": choice.applied.price,
                        "cloudMarketTime": choice.applied.market_time, "desktopPrice": desk.price,
                        "desktopMarketTime": desk.market_time, "kind": kind})
        else:
            reasons = sorted({r.reason for r in choice.rejected_with_reason if r.observation.source == "cloud"} |
                             ({"unit_mismatch"} if bad_unit else set()))
            out.append({"ticker": ticker, "decision": "not_newer", "reasons": reasons, "kind": kind})
    return out


def quarantine(path, results: list[dict], *, now: datetime | None = None) -> None:
    from core.sync.v2_state import _write_atomic
    from pathlib import Path
    _write_atomic(Path(path), {"checkedAt": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                               "appliedToDesktop": False, "items": results})
