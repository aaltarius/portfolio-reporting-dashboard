"""
core/validation.py — Validazione eventi portafoglio.
Nessuna dipendenza da streamlit.

validate_evento_portafoglio dipende da compute_portfolio_state (core/finance.py)
e viene completata nel Task 5 dopo l'estrazione di core/finance.py.
"""
from persistence.storage import (
    _safe_float,
    TIPI_EVENTO_PORTAFOGLIO,
    EVENTI_CON_STRUMENTO,
    EVENTI_CON_QUANTITA,
    EVENTI_CON_PREZZO,
    EVENTI_CON_IMPORTO,
    macro_cat,
    _normalize_event_record,
)
import pandas as pd


_EVENTI_CON_GIACENZA = {"VENDITA", "RIMBORSO A SCADENZA"}
_EVENTI_PROVENTO = {"CEDOLA", "DIVIDENDO"}


def _instrument_lookup(data, ticker):
    return next((s for s in data.get("strumenti", []) if s.get("ticker") == ticker), {})


def _instrument_type_info(data, ticker):
    s = _instrument_lookup(data, ticker)
    nome = str(s.get("nome", "") or "")
    tipo = str(s.get("tipo", "") or "")
    txt = f"{nome} {tipo}".lower()
    return s, nome, tipo, txt


def _supports_coupon(data, ticker):
    _, _, tipo, txt = _instrument_type_info(data, ticker)
    category = macro_cat(tipo)
    if category == "GOV":
        return True
    if category in {"ETF", "FND", "ETC"}:
        return False
    return any(k in txt for k in ["titolo di stato", "btp", "bond", "obbl", "cedola"])


def _supports_dividend(data, ticker):
    _, nome, tipo, txt = _instrument_type_info(data, ticker)
    if _supports_coupon(data, ticker):
        return False
    if any(k in txt for k in ["acc", "accum", "accumul"]):
        return False
    return any(k in txt for k in ["dist", "distrib", "dividend"])


def _supports_redemption(data, ticker):
    _, _, tipo, txt = _instrument_type_info(data, ticker)
    category = macro_cat(tipo)
    if category == "GOV":
        return True
    if category in {"ETF", "FND", "ETC"}:
        return False
    return any(k in txt for k in ["titolo di stato", "btp", "bond", "obbl", "scadenza", "maturity"])


def validate_evento_portafoglio(data, evento):
    """Validazione completa di un evento portafoglio.
    Dipende da compute_portfolio_state e get_cash_balance (core/finance.py)
    e da fmt_eur_it, fmt_qty_it (core/formatting.py).
    Importati qui in modo lazy per evitare import circolari durante la transizione."""
    from core.finance import compute_portfolio_state, get_cash_balance
    from core.formatting import fmt_eur_it, fmt_qty_it

    ev = _normalize_event_record(evento)
    tipo = ev.get("tipo_evento")
    qty = _safe_float(ev.get("quantita", 0))
    prezzo = _safe_float(ev.get("prezzo_unitario", 0))
    lordo = _safe_float(ev.get("importo_lordo", 0))
    netto = _safe_float(ev.get("importo_netto", 0))
    tk = ev.get("ticker", "")
    ignore_cash_check = bool(evento.get("ignore_cash_check")) if isinstance(evento, dict) else False

    if tipo not in set(TIPI_EVENTO_PORTAFOGLIO):
        return False, "Tipo evento non valido."

    if tipo in EVENTI_CON_STRUMENTO and not tk:
        return False, "Seleziona uno strumento."

    if tipo in EVENTI_CON_QUANTITA:
        if qty <= 0:
            return False, "La quantità deve essere maggiore di zero."
    if tipo in EVENTI_CON_PREZZO:
        if prezzo <= 0:
            return False, "Il prezzo deve essere maggiore di zero."

    if tipo in EVENTI_CON_IMPORTO and abs(lordo) <= 1e-12 and abs(netto) <= 1e-12:
        return False, "L'importo deve essere maggiore di zero."

    stato = compute_portfolio_state(data, include_closed=True)
    df = stato.get("df", pd.DataFrame())
    qty_disp = 0.0
    row = None
    if tk and df is not None and not df.empty and tk in set(df.get("Ticker", [])):
        row = df[df["Ticker"] == tk].iloc[0]
        qty_disp = _safe_float(row.get("Quote", 0))

    if tipo == "ACQUISTO" and not ignore_cash_check:
        saldo = get_cash_balance(data)
        fabbisogno = abs(netto) if abs(netto) > 1e-12 else abs(qty * prezzo + _safe_float(ev.get("commissioni", 0)) + _safe_float(ev.get("imposte", 0)))
        if fabbisogno - saldo > 1e-9:
            return False, f"Liquidità insufficiente per l'acquisto: disponibili {fmt_eur_it(saldo,2)}. Attiva il versamento automatico o registra prima un versamento."

    if tipo in _EVENTI_CON_GIACENZA:
        if row is None or qty_disp <= 1e-12:
            return False, "Lo strumento non risulta presente in portafoglio."
        if qty - qty_disp > 1e-9:
            return False, f"Quantità insufficiente: disponibili {fmt_qty_it(qty_disp,4)} quote."
        if tipo == "RIMBORSO A SCADENZA" and not _supports_redemption(data, tk):
            return False, "Il rimborso a scadenza è consentito solo per strumenti compatibili con la scadenza/rimborso."

    if tipo in _EVENTI_PROVENTO:
        if row is None or qty_disp <= 1e-12:
            return False, "Per registrare il provento devi avere una posizione aperta sullo strumento."
        if tipo == "CEDOLA" and not _supports_coupon(data, tk):
            return False, "La cedola è consentita solo per strumenti compatibili (es. obbligazioni o titoli di Stato)."
        if tipo == "DIVIDENDO" and not _supports_dividend(data, tk):
            return False, "Il dividendo è consentito solo per strumenti compatibili con distribuzione."

    if tipo == "PRELIEVO":
        saldo = get_cash_balance(data)
        richiesta = abs(netto) if abs(netto) > 1e-12 else abs(lordo)
        if richiesta - saldo > 1e-9:
            return False, f"Liquidità insufficiente: disponibili {fmt_eur_it(saldo,2)}."

    return True, ""
