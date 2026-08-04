"""BTP calendar and timeline dataset builders."""

from __future__ import annotations

import math

import pandas as pd


CEDOLA_FREQ_MONTHS = {
    "trimestrale": 3,
    "semestrale": 6,
    "annuale": 12,
}

CEDOLA_FREQ_PAYMENTS = {
    "trimestrale": 4,
    "semestrale": 2,
    "annuale": 1,
}

# Aliquote fiscali italiane su cedole/plusvalenze, convenzione percento
# (12.5, non 0.125). GOV = titoli di Stato italiani (BTP, CCT, ...); OTHER =
# tutti gli altri strumenti (azioni, ETF, fondi, obbligazioni corporate...).
# Costante unica: prima duplicata in modo indipendente in più punti del
# codice (ui/charts/calendario_btp.py in convenzione frazione, ui/pages/
# operazioni.py, ui/form_server/*.py). Chi ha bisogno della frazione (es.
# 0.125) deve dividere per 100.0 qui, non ridefinire il letterale altrove.
TAX_RATE_GOV_PCT = 12.5
TAX_RATE_OTHER_PCT = 26.0


_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%y", "%d/%m/%Y")


def _to_ts(value) -> pd.Timestamp | None:
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp,)):
        return value if not pd.isna(value) else None
    raw = str(value).strip()
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return pd.Timestamp(pd.to_datetime(raw, format=fmt))
        except (ValueError, TypeError):
            continue
    return None


def _is_btp(tipo: str) -> bool:
    tipo_norm = str(tipo or "").strip().lower()
    return tipo_norm in {"btp", "titolo di stato"}


def _finite_float(value, default: float = 0.0, *, zero_as_default: bool = False) -> float:
    if isinstance(value, bool) or value in (None, ""):
        return float(default)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    if zero_as_default and abs(number) <= 1e-12:
        return float(default)
    return number if math.isfinite(number) else float(default)


def _first_purchase_date(registro_eventi: list[dict], ticker: str) -> pd.Timestamp | None:
    purchase_dates: list[pd.Timestamp] = []
    for ev in registro_eventi or []:
        if str(ev.get("ticker") or "").strip() != ticker:
            continue
        if str(ev.get("tipo_evento") or "").strip().upper() != "ACQUISTO":
            continue
        ts = _to_ts(ev.get("data"))
        if ts is not None:
            purchase_dates.append(ts.normalize())
    if not purchase_dates:
        return None
    return min(purchase_dates)


def _real_events_by_type(registro_eventi: list[dict], ticker: str, tipo_evento: str) -> list[dict]:
    """Eventi realmente registrati (non stimati) per ticker+tipo, ordinati per data.

    Usati per sostituire, riga per riga, la proiezione sintetica del
    calendario (basata su cedola_perc/aliquota fissa) con gli importi
    davvero incassati — incluse le imposte effettivamente pagate, che il
    modello sintetico non conosce."""
    matches = [
        ev for ev in (registro_eventi or [])
        if str(ev.get("ticker") or "").strip() == ticker
        and str(ev.get("tipo_evento") or "").strip().upper() == tipo_evento
    ]
    matches.sort(key=lambda ev: str(ev.get("data") or ""))
    return matches


def _match_real_event(real_events: list[dict], target_date: pd.Timestamp, used: set[int], tolerance_days: int = 45) -> dict | None:
    """Trova, tra gli eventi reali non ancora usati, quello con data piu'
    vicina a target_date entro tolerance_days (le date di pagamento reali
    possono scostarsi di qualche giorno dal calendario teorico per motivi di
    valuta/settlement)."""
    best_idx = None
    best_delta = None
    for idx, ev in enumerate(real_events):
        if idx in used:
            continue
        ev_date = _to_ts(ev.get("data"))
        if ev_date is None:
            continue
        delta = abs((ev_date.normalize() - target_date).days)
        if delta > tolerance_days:
            continue
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best_idx = idx
    if best_idx is None:
        return None
    used.add(best_idx)
    return real_events[best_idx]


def build_btp_calendar(data: dict) -> pd.DataFrame:
    """Build timeline rows for BTP purchase span, coupons and maturity."""
    rows: list[dict] = []
    strumenti = data.get("strumenti", []) or []
    registro_eventi = data.get("registro_eventi", []) or []
    today = pd.Timestamp.today().normalize()

    for strumento in strumenti:
        if not _is_btp(strumento.get("tipo", "")):
            continue

        ticker = str(strumento.get("ticker") or "").strip()
        if not ticker:
            continue

        scadenza = _to_ts(strumento.get("scadenza"))
        if scadenza is None:
            continue
        scadenza = scadenza.normalize()

        purchase_date = (
            _to_ts(strumento.get("data_acquisto"))
            or _to_ts(strumento.get("data_origine"))
            or _first_purchase_date(registro_eventi, ticker)
            or today
        )
        purchase_date = purchase_date.normalize()

        cedola_perc = _finite_float(strumento.get("cedola_perc"), 0.0)
        nominale = _finite_float(strumento.get("nominale"), 100.0, zero_as_default=True)
        quantita = _finite_float(strumento.get("quantita"), 1.0, zero_as_default=True)

        cedola_freq = str(strumento.get("cedola_frequenza", "annuale") or "annuale").strip().lower()
        prima_cedola = (
            _to_ts(strumento.get("prima_cedola"))
            or _to_ts(strumento.get("data_origine"))
            or purchase_date
        )
        prima_cedola = prima_cedola.normalize()
        aliquota_cedola = _finite_float(strumento.get("aliquota_cedola"), TAX_RATE_GOV_PCT, zero_as_default=True)

        rows.append(
            {
                "ticker": ticker,
                "nome": str(strumento.get("nome") or ticker),
                "importo_label": "Acquisto",
                "tipo_riga": "span",
                "data_inizio": purchase_date,
                "data_fine": scadenza,
                "data": purchase_date,
                "importo": 0.0,
                "importo_lordo": 0.0,
                "tipo_evento": "possesso",
                "stato_evento": "in_corso",
            }
        )

        # Un rimborso realmente registrato porta con se' le imposte davvero
        # pagate (persistite da discharge_lot al momento dell'evento) — la
        # proiezione sintetica sotto non le conosce affatto, quindi va usata
        # solo finche' l'operatore non registra l'evento vero.
        real_rimborsi = _real_events_by_type(registro_eventi, ticker, "RIMBORSO A SCADENZA")
        real_rimborso = real_rimborsi[0] if real_rimborsi else None

        importo_rimborso = nominale * quantita
        scadenza_row: dict = {
            "ticker": ticker,
            "nome": str(strumento.get("nome") or ticker),
            "importo_label": fmt_eur_label(importo_rimborso),
            "tipo_riga": "evento",
            "data_inizio": purchase_date,
            "data_fine": scadenza,
            "data": scadenza,
            "importo": importo_rimborso,
            "importo_lordo": importo_rimborso,
            "imposte": None,
            "tipo_evento": "scadenza",
            "stato_evento": "incassata" if scadenza <= today else "futura",
        }
        if real_rimborso is not None:
            real_lordo = _finite_float(real_rimborso.get("importo_lordo"), importo_rimborso)
            real_imposte = _finite_float(real_rimborso.get("imposte"), 0.0)
            real_netto = _finite_float(real_rimborso.get("importo_netto"), real_lordo - real_imposte)
            scadenza_row.update({
                "importo_label": fmt_eur_label(real_netto),
                "importo": real_netto,
                "importo_lordo": real_lordo,
                "imposte": real_imposte,
                "stato_evento": "incassata",
            })
        rows.append(scadenza_row)

        if cedola_perc <= 0:
            continue

        payments_per_year = CEDOLA_FREQ_PAYMENTS.get(cedola_freq, 1)
        cedola_per_quota = (cedola_perc / 100.0) * nominale / payments_per_year
        cedola_amount_lordo = cedola_per_quota * quantita
        cedola_amount_netto = cedola_amount_lordo * (1.0 - aliquota_cedola / 100.0)

        real_cedole = _real_events_by_type(registro_eventi, ticker, "CEDOLA")
        used_real_cedole: set[int] = set()

        current = prima_cedola
        while current <= scadenza:
            current_day = pd.Timestamp(current).normalize()
            cedola_row: dict = {
                "ticker": ticker,
                "nome": str(strumento.get("nome") or ticker),
                "importo_label": fmt_eur_label(cedola_amount_netto),
                "tipo_riga": "evento",
                "data_inizio": purchase_date,
                "data_fine": scadenza,
                "data": current_day,
                "importo": cedola_amount_netto,
                "importo_lordo": cedola_amount_lordo,
                "imposte": None,
                "tipo_evento": "cedola",
                "stato_evento": "incassata" if current_day <= today else "futura",
            }
            real_cedola = None
            if current_day <= today:
                real_cedola = _match_real_event(real_cedole, current_day, used_real_cedole)
            if real_cedola is not None:
                real_lordo = _finite_float(real_cedola.get("importo_lordo"), cedola_amount_lordo)
                real_imposte = _finite_float(real_cedola.get("imposte"), 0.0)
                real_netto = _finite_float(real_cedola.get("importo_netto"), real_lordo - real_imposte)
                cedola_row.update({
                    "importo_label": fmt_eur_label(real_netto),
                    "importo": real_netto,
                    "importo_lordo": real_lordo,
                    "imposte": real_imposte,
                })
            rows.append(cedola_row)
            current = current + pd.DateOffset(months=CEDOLA_FREQ_MONTHS.get(cedola_freq, 12))

    df = pd.DataFrame(
        rows,
        columns=[
            "ticker",
            "nome",
            "tipo_riga",
            "data_inizio",
            "data_fine",
            "data",
            "importo",
            "importo_lordo",
            "imposte",
            "importo_label",
            "tipo_evento",
            "stato_evento",
        ],
    )
    if not df.empty:
        df = df.sort_values(["ticker", "data", "tipo_riga"]).reset_index(drop=True)
    return df


def fmt_eur_label(value: float) -> str:
    return f"€ {_finite_float(value, 0.0):,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
