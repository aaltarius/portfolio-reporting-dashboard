"""Costruzione dei quattro invii accessori per il Mobile (storico, mercato breve, sezioni Desktop, storico BTP).

Sono la riproduzione, dentro il Desktop, degli esportatori del pacchetto Mobile (`esporta_*`): stessi schemi
(`sestante.mobile.history.v1`, `market_brief.v1`, `desktop_features.v2`, `btp_history.v1`), stessi limiti del
Worker, stessi calcoli (si riusano i motori del Desktop, nessuna formula nuova). Solo costruzione in memoria:
nessuna rete, nessuna scrittura, i dati ricevuti non vengono modificati.

Ogni funzione riceve la fotografia già costruita (`snapshot`): `sourceFileSha256`, `portfolioRevision` e
`sourceUpdatedAt` devono essere identici in tutti i pacchetti, altrimenti il Worker risponde 409."""
from __future__ import annotations

import copy
import datetime as dt
import json
import math

HISTORY_SCHEMA = "sestante.mobile.history.v1"
BRIEF_SCHEMA = "sestante.mobile.market_brief.v1"
FEATURES_SCHEMA = "sestante.mobile.desktop_features.v2"
BTP_SCHEMA = "sestante.mobile.btp_history.v1"

LIMITS = {"history": 450_000, "brief": 120_000, "features": 150_000, "btp": 160_000}
_HISTORY_FIELDS = {"Valore": "total", "ValoreAperto": "positionsValue", "Capitale": "capital",
                   "Liquidità": "cash", "P/L": "pnl"}


def encode(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _num(value, digits=8):
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return round(n, digits) if math.isfinite(n) and abs(n) < 1e12 else None


def _text(value, n=180):
    return str(value or "").strip()[:n]


def _date(value):
    if value is None or value == "":
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    try:
        return dt.date.fromisoformat(str(value).strip()[:10]).isoformat()
    except ValueError:
        return None


def _common(snapshot: dict) -> dict:
    return {"portfolioId": snapshot["portfolioId"], "sourceFileSha256": snapshot["sourceFileSha256"],
            "portfolioRevision": snapshot["revision"], "sourceUpdatedAt": snapshot["sourceUpdatedAt"]}


def _checked(row, key):
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or abs(float(value)) > 1e12:
        raise ValueError(f"Campo storico {key} non valido ({row.get('Data')}).")
    return round(float(value), 6)


def _check_size(body: bytes, key: str, label: str) -> bytes:
    if len(body) > LIMITS[key]:
        raise ValueError(f"{label}: {len(body)} byte oltre il limite del Worker ({LIMITS[key]}).")
    return body


def build_history(data: dict, snapshot: dict):
    """Storico aggregato (grafici patrimonio e P/L). Usa la cache dello Storico già calcolata dal Desktop."""
    cache = data.get("cache_storico_portafoglio")
    if not isinstance(cache, dict) or not isinstance(cache.get("rows"), list):
        raise ValueError("Cache dello Storico assente: aprire la pagina Storico sul Desktop.")
    rows = cache["rows"]
    if not any(any(str(k).startswith("PL_") for k in r) for r in rows if isinstance(r, dict)):
        raise ValueError("Cache dello Storico priva delle colonne PL_<ticker>.")
    if not 2 <= len(rows) <= 2000:
        raise ValueError("Numero di righe dello Storico non valido (2..2000).")
    families = {}
    for ins in data.get("strumenti", []):
        if not isinstance(ins, dict) or not ins.get("ticker"):
            continue
        tk, kind = str(ins["ticker"]).strip(), str(ins.get("tipo") or "").lower()
        families[tk] = "BTP" if tk.startswith("BTP-") or "titolo di stato" in kind else (
            "FAM" if tk.startswith("FAM-") or kind.startswith("fondo") else "ETF")
    points, latest = [], ""
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Riga dello Storico non valida.")
        day = row.get("Data")
        if not isinstance(day, str) or len(day) != 10 or dt.date.fromisoformat(day).isoformat() != day:
            raise ValueError("Data dello Storico non valida.")
        if day <= latest:
            raise ValueError("Date dello Storico duplicate o non ordinate: " + day)
        latest = day
        vals = {dst: _checked(row, src) for src, dst in _HISTORY_FIELDS.items()}
        if abs(vals["total"] - (vals["positionsValue"] + vals["cash"])) > max(2, abs(vals["total"]) * 0.00002):
            raise ValueError("Valore dello Storico diverso da posizioni + liquidità alla data " + day)
        fam = {"ETF": 0.0, "FAM": 0.0, "BTP": 0.0}
        for key in row:
            if str(key).startswith("PL_"):
                tk = key[3:]
                if tk not in families:
                    raise ValueError("Strumento nello Storico privo di classificazione: " + tk)
                fam[families[tk]] += _checked(row, key)
        points.append({"date": day, **vals, "categoryPnl": {k: round(v, 6) for k, v in fam.items()}})
    payload = {"schema": HISTORY_SCHEMA, **_common(snapshot), "cacheSignature": str(cache.get("signature") or "")[:180],
              "points": points}
    return payload, _check_size(encode(payload), "history", "Storico")


def _price_history(data: dict, price_history: dict | None):
    hist = price_history if price_history is not None else data.get("storico_prezzi")
    if not isinstance(hist, dict) or sum(isinstance(v, dict) and bool(v) for v in hist.values()) < 6:
        raise ValueError("Storico prezzi non disponibile (servono almeno 6 date).")
    return hist


def build_market_brief(data: dict, snapshot: dict, price_history: dict | None = None):
    """Ultima seduta e ultime sedute: solo prezzi giornalieri delle posizioni aperte (fino a 50 date reali)."""
    tickers = {p["ticker"] for p in snapshot["positions"]}
    sessions = []
    for day, prices in sorted(_price_history(data, price_history).items()):
        try:
            if not isinstance(day, str) or len(day) != 10 or dt.date.fromisoformat(day).isoformat() != day:
                continue
        except ValueError:
            continue
        if not isinstance(prices, dict):
            continue
        items = {}
        for tk in tickers:
            v = prices.get(tk)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            v = float(v)
            if math.isfinite(v) and 0 < v < 1e9:
                items[tk] = round(v, 8)
        if items:
            sessions.append({"date": day, "prices": items})
    sessions = sessions[-50:]
    if len(sessions) < 6:
        raise ValueError(f"Solo {len(sessions)} sedute con prezzi validi: ne servono almeno 6.")
    payload = {"schema": BRIEF_SCHEMA, **{k: v for k, v in _common(snapshot).items()}, "sessions": sessions}
    return payload, _check_size(encode(payload), "brief", "Mercato breve")


def build_features(data: dict, snapshot: dict, today: dt.date | None = None):
    """Anagrafica, Accumuli (DCA), calendario titoli di Stato e riepilogo posizioni chiuse: motori del Desktop."""
    from core.domain.calendar import build_btp_calendar
    from core.domain.instrument_status import compute_instrument_statuses
    from core.domain.positions import held_tickers
    from core.services.accumuli import build_accumuli_analysis
    from core.services.closed_positions import build_closed_positions_table, summarize_closed_positions
    from persistence.storage import macro_cat

    work = copy.deepcopy(data)
    today = today or dt.date.today()
    held = held_tickers(work)
    statuses = compute_instrument_statuses(work)
    items, seen = [], set()
    for raw in work.get("strumenti", []):
        if not isinstance(raw, dict):
            continue
        tk = _text(raw.get("ticker"), 60)
        if not tk or tk in seen:
            raise ValueError("Ticker duplicato o non valido in strumenti: " + tk)
        seen.add(tk)
        maturity = _date(raw.get("scadenza"))
        st = statuses.get(tk)
        closed = bool(st and not st.is_open and st.has_any_event)
        gov = "Titolo di Stato" in str(raw.get("tipo", ""))
        items.append({
            "ticker": tk, "name": _text(raw.get("nome") or tk, 200), "isin": _text(raw.get("isin"), 32),
            "type": _text(raw.get("tipo"), 100), "category": _text(macro_cat(raw.get("tipo") or ""), 30),
            "nature": _text(raw.get("natura"), 110), "status": _text(raw.get("stato"), 30),
            "price": _num(raw.get("prezzo")), "updatedAt": _text(raw.get("aggiornato"), 40),
            "source": _text(raw.get("fonte"), 130), "maturity": maturity,
            "archived": bool(closed or (gov and maturity and maturity < today.isoformat() and tk not in held)),
            "priceUnit": "PCT_NOMINALE" if gov else "EUR",
        })
    fields = {"regolarita_intervalli": "regularity", "aderenza_pac_pct": "scheduleAdherence",
              "distanza_pareggio_pct": "breakEvenDistance", "percentile_pmc_allin": "pmcPercentile",
              "drawdown_da_massimo": "drawdown", "impatto_pmc_rata_pct": "pmcImpact", "capitale": "capital",
              "controvalore": "value", "pl_abs": "pnl", "pl_pct": "pnlPct", "quote": "quantity",
              "pmc_allin": "pmc", "prezzo_attuale": "price", "importo_tipico_acquisto": "typicalInstallment"}
    acc = build_accumuli_analysis(work)
    accumuli = []
    for row in (acc.summary.to_dict("records") if not acc.summary.empty else []):
        rec = {"ticker": _text(row.get("ticker"), 60), "name": _text(row.get("nome"), 200),
               "category": _text(row.get("categoria"), 30), "method": _text(row.get("tipo_accumulo"), 60),
               "buys": int(row.get("n_acquisti") or 0), "state": _text(row.get("stato"), 60),
               "priority": _text(row.get("priorita"), 30), "diagnosis": _text(row.get("diagnosi"), 380),
               "lastQuoteDate": _date(row.get("data_ultima_quotazione"))}
        rec.update({out: _num(row.get(src)) for src, out in fields.items()})
        accumuli.append(rec)
    cal = build_btp_calendar(work)
    future = []
    if not cal.empty:
        for row in cal.to_dict("records"):
            tk, ev, day = _text(row.get("ticker"), 60), _text(row.get("tipo_evento"), 30), _date(row.get("data"))
            if (tk not in held or ev not in ("cedola", "scadenza") or _text(row.get("stato_evento"), 20) != "futura"
                    or not day or day < today.isoformat()):
                continue
            future.append({"ticker": tk, "name": _text(row.get("nome"), 200), "date": day, "event": ev,
                           "netAmount": _num(row.get("importo")), "grossAmount": _num(row.get("importo_lordo"))})
    future.sort(key=lambda x: (x["date"], x["ticker"], x["event"]))
    if len(future) > 1000:
        raise ValueError("Troppi eventi nel calendario dei titoli di Stato.")
    c = summarize_closed_positions(build_closed_positions_table(work))
    payload = {"schema": FEATURES_SCHEMA, **_common(snapshot), "catalog": items, "accumuli": accumuli,
              "closedSummary": {"count": int(c["n_posizioni"]), "freedCapital": _num(c["capitale_liberato_totale"]),
                                "grossPnl": _num(c["pl_lordo_totale"]), "fees": _num(c["commissioni_totali"]),
                                "taxes": _num(c["imposte_totali"]), "realizedPnl": _num(c["pl_realizzato_totale"]),
                                "incomeNet": _num(c["cedole_dividendi_totali"]), "totalReturn": _num(c["return_totale"]),
                                "realizedRatio": _num(c["rendimento_pct_medio"])},
              "futureGov": future, "calendarAsOf": today.isoformat()}
    return payload, _check_size(encode(payload), "features", "Sezioni Desktop")


def build_btp_history(data: dict, snapshot: dict, price_history: dict | None = None, *, last_days: int | None = None):
    """Serie prezzi dei BTP detenuti. Il Worker UNISCE le serie ricevute a quelle già presenti: con `last_days`
    si inviano solo le osservazioni recenti (almeno 2 per titolo), che è il modo di ridurre il traffico."""
    active = sorted(p["ticker"] for p in snapshot["positions"] if str(p["ticker"]).startswith("BTP-"))
    if not active:
        raise ValueError("Nessun BTP detenuto.")
    series = {t: [] for t in active}
    for day, prices in sorted(_price_history(data, price_history).items()):
        try:
            if not isinstance(day, str) or dt.date.fromisoformat(day).isoformat() != day:
                continue
        except ValueError:
            continue
        if not isinstance(prices, dict):
            continue
        for tk in series:
            v = prices.get(tk)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            v = float(v)
            if math.isfinite(v) and 0 < v <= 1000:
                series[tk].append({"date": day, "price": round(v, 8)})
    for tk, pts in series.items():
        if len(pts) < 2:
            raise ValueError(f"Storico {tk} insufficiente ({len(pts)} osservazioni).")
        if last_days is not None:
            series[tk] = pts[-max(2, int(last_days)):]
        elif len(pts) > 1200:
            raise ValueError(f"Storico {tk} troppo esteso per il contratto cloud.")
    payload = {"schema": BTP_SCHEMA, "portfolioId": snapshot["portfolioId"], "sourceFileSha256": snapshot["sourceFileSha256"],
              "sourceUpdatedAt": snapshot["sourceUpdatedAt"], "series": series}
    return payload, _check_size(encode(payload), "btp", "Storico BTP")
