"""BTP calendar and timeline dataset builders."""

from __future__ import annotations

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


def _to_ts(value) -> pd.Timestamp | None:
    try:
        ts = pd.to_datetime(value)
    except (ValueError, TypeError, pd.errors.ParserError):
        return None
    if pd.isna(ts):
        return None
    return pd.Timestamp(ts)


def _is_btp(tipo: str) -> bool:
    tipo_norm = str(tipo or "").strip().lower()
    return tipo_norm in {"btp", "titolo di stato"}


def _first_purchase_date(registro_eventi: list[dict], ticker: str) -> pd.Timestamp | None:
    purchase_dates: list[pd.Timestamp] = []
    for ev in registro_eventi or []:
        if str(ev.get("ticker") or "").strip() != ticker:
            continue
        if str(ev.get("tipo") or "").strip().upper() != "ACQUISTO":
            continue
        ts = _to_ts(ev.get("data"))
        if ts is not None:
            purchase_dates.append(ts.normalize())
    if not purchase_dates:
        return None
    return min(purchase_dates)


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

        try:
            cedola_perc = float(strumento.get("cedola_perc", 0) or 0)
        except Exception:
            cedola_perc = 0.0
        try:
            nominale = float(strumento.get("nominale", 100) or 100)
        except Exception:
            nominale = 100.0
        try:
            quantita = float(strumento.get("quantita", 1) or 1)
        except Exception:
            quantita = 1.0

        cedola_freq = str(strumento.get("cedola_frequenza", "annuale") or "annuale").strip().lower()
        prima_cedola = (
            _to_ts(strumento.get("prima_cedola"))
            or _to_ts(strumento.get("data_origine"))
            or purchase_date
        )
        prima_cedola = prima_cedola.normalize()
        try:
            aliquota_cedola = float(strumento.get("aliquota_cedola", 12.5) or 12.5)
        except Exception:
            aliquota_cedola = 12.5

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
                "tipo_evento": "possesso",
                "stato_evento": "in_corso",
            }
        )

        importo_rimborso = nominale * quantita
        rows.append(
            {
                "ticker": ticker,
                "nome": str(strumento.get("nome") or ticker),
                "importo_label": fmt_eur_label(importo_rimborso),
                "tipo_riga": "evento",
                "data_inizio": purchase_date,
                "data_fine": scadenza,
                "data": scadenza,
                "importo": importo_rimborso,
                "importo_lordo": importo_rimborso,
                "tipo_evento": "scadenza",
                "stato_evento": "incassata" if scadenza <= today else "futura",
            }
        )

        if cedola_perc <= 0:
            continue

        payments_per_year = CEDOLA_FREQ_PAYMENTS.get(cedola_freq, 1)
        cedola_per_quota = (cedola_perc / 100.0) * nominale / payments_per_year
        cedola_amount_lordo = cedola_per_quota * quantita
        cedola_amount_netto = cedola_amount_lordo * (1.0 - aliquota_cedola / 100.0)

        current = prima_cedola
        while current <= scadenza:
            current_day = pd.Timestamp(current).normalize()
            rows.append(
                {
                    "ticker": ticker,
                    "nome": str(strumento.get("nome") or ticker),
                    "importo_label": fmt_eur_label(cedola_amount_netto),
                    "tipo_riga": "evento",
                    "data_inizio": purchase_date,
                    "data_fine": scadenza,
                    "data": current_day,
                    "importo": cedola_amount_netto,
                    "importo_lordo": cedola_amount_lordo,
                    "tipo_evento": "cedola",
                    "stato_evento": "incassata" if current_day <= today else "futura",
                }
            )
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
            "importo_label",
            "tipo_evento",
            "stato_evento",
        ],
    )
    if not df.empty:
        df = df.sort_values(["ticker", "data", "tipo_riga"]).reset_index(drop=True)
    return df


def fmt_eur_label(value: float) -> str:
    try:
        return f"€ {float(value):,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "€ 0"
