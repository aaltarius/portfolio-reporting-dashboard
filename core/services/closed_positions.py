"""core/services/closed_positions.py — Fonte canonica unica per il riepilogo
delle posizioni chiuse (vendute o rimborsate a scadenza).

Consumato sia da ui/pages/operazioni.py (registro consultivo) sia da
ui/pages/home.py ("Portafoglio", riepilogo per l'operatore): nessuna delle
due pagine ricalcola questa logica in proprio.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from persistence.storage import macro_cat, get_registro_eventi, _safe_float
from core.constants import QTY_ZERO_EPS
from core.domain.positions import compute_portfolio_state
from core.domain.instrument_status import compute_instrument_statuses
from core.formatting import fmtds


CLOSED_POSITIONS_COLUMNS = [
    "Ticker", "Nome", "Tipo", "Aperto il", "Chiuso il", "Motivo",
    "Capitale Liberato €", "P/L Lordo €", "Commissioni €", "Imposte €",
    "P/L Realizzato €", "Cedole/Div. netti €", "Return Totale €", "Rendimento %",
    "Osserva prezzo",
]


def build_closed_positions_table(data: dict[str, Any]) -> pd.DataFrame:
    """Righe per ogni strumento chiuso (venduto o rimborsato), con la
    scomposizione completa e verificabile del risultato: capitale liberato,
    P/L lordo, commissioni pagate in chiusura, imposte, P/L netto
    (realizzato), cedole/dividendi netti incassati, return totale e
    rendimento percentuale sul capitale liberato. Vale sempre
    "P/L Lordo - Commissioni - Imposte == P/L Realizzato" (± arrotondamento),
    cosi' il numero finale e' tracciabile riga per riga, non una scatola
    nera. DataFrame vuoto se non c'e' nulla da mostrare (nessun errore,
    nessuna eccezione)."""
    df_positions = compute_portfolio_state(data, include_closed=True).get("df", pd.DataFrame())
    if df_positions.empty:
        return pd.DataFrame(columns=CLOSED_POSITIONS_COLUMNS)
    df_chiusi_pos = df_positions[df_positions["Quote"] <= QTY_ZERO_EPS]
    if df_chiusi_pos.empty:
        return pd.DataFrame(columns=CLOSED_POSITIONS_COLUMNS)

    statuses = compute_instrument_statuses(data)
    chiusi_tickers = {tk for tk, status in statuses.items() if not status.is_open and status.has_any_event}
    chiusi = [s for s in data.get("strumenti", []) if s.get("ticker") in chiusi_tickers]
    if not chiusi:
        return pd.DataFrame(columns=CLOSED_POSITIONS_COLUMNS)

    first_buy: dict[str, str] = {}
    last_close: dict[str, str] = {}
    close_motivo: dict[str, str] = {}
    # Capitale liberato e commissioni di CHIUSURA (non quelle di acquisto,
    # gia' assorbite nel costo base e quindi gia' dedotte dentro P/L Lordo)
    # sommati per ticker sugli eventi VENDITA/RIMBORSO — una posizione puo'
    # essere stata chiusa in piu' tranche, non solo con un evento unico.
    capitale_liberato_by_tk: dict[str, float] = {}
    commissioni_uscita_by_tk: dict[str, float] = {}
    for ev in get_registro_eventi(data):
        tk = str(ev.get("ticker", "") or "")
        tipo_ev = str(ev.get("tipo_evento", "") or "")
        if tipo_ev == "ACQUISTO" and tk and tk not in first_buy:
            first_buy[tk] = str(ev.get("data", "") or "")
        elif tipo_ev in ("VENDITA", "RIMBORSO A SCADENZA") and tk:
            last_close[tk] = str(ev.get("data", "") or "")
            close_motivo[tk] = tipo_ev
            capitale_liberato_by_tk[tk] = capitale_liberato_by_tk.get(tk, 0.0) + _safe_float(ev.get("capitale_liberato", 0.0))
            commissioni_uscita_by_tk[tk] = commissioni_uscita_by_tk.get(tk, 0.0) + _safe_float(ev.get("commissioni", 0.0))

    rows = []
    for s in chiusi:
        ticker = str(s.get("ticker", "") or "")
        status = statuses.get(ticker)
        nome = str(s.get("nome", ticker) or ticker)
        tipo = macro_cat(str(s.get("tipo", "") or ""))
        data_apertura = fmtds(first_buy.get(ticker, "")) if first_buy.get(ticker) else "—"
        _close_date = last_close.get(ticker) or str(s.get("data_chiusura", "") or "")
        data_chius = fmtds(_close_date) if _close_date else "—"
        motivo = close_motivo.get(ticker) or str(s.get("motivo_chiusura", "") or "—")

        pos_row = df_positions[df_positions["Ticker"] == ticker] if not df_positions.empty else pd.DataFrame()
        if pos_row.empty:
            pl_lordo = pl_netto = cedole = dividendi = imposte = 0.0
        else:
            r = pos_row.iloc[0]
            pl_lordo = _safe_float(r.get("P/L Realizzato Lordo", 0.0))
            pl_netto = _safe_float(r.get("P/L Realizzato Netto", 0.0))
            cedole = _safe_float(r.get("Cedole nette", 0.0))
            dividendi = _safe_float(r.get("Dividendi netti", 0.0))
            imposte = _safe_float(r.get("Imposte €", 0.0))

        capitale_liberato = capitale_liberato_by_tk.get(ticker, 0.0)
        commissioni_uscita = commissioni_uscita_by_tk.get(ticker, 0.0)
        return_totale = pl_netto + cedole + dividendi
        # Frazione (0.0323), non gia' moltiplicata per 100: fmt_pct_it (ui/formatting.py)
        # si aspetta l'input in questa forma e fa lei la conversione per la UI,
        # stessa convenzione usata dalle altre colonne "%" in tutto l'applicativo.
        rendimento_pct = (pl_netto / capitale_liberato) if abs(capitale_liberato) > 1e-9 else None
        rows.append({
            "Ticker": ticker,
            "Nome": nome,
            "Tipo": tipo,
            "Aperto il": data_apertura,
            "Chiuso il": data_chius,
            "Motivo": motivo,
            "Capitale Liberato €": capitale_liberato,
            "P/L Lordo €": pl_lordo,
            "Commissioni €": commissioni_uscita,
            "Imposte €": imposte,
            "P/L Realizzato €": pl_netto,
            "Cedole/Div. netti €": cedole + dividendi,
            "Return Totale €": return_totale,
            "Rendimento %": rendimento_pct,
            "Osserva prezzo": "—" if (status and status.is_terminal) else ("Sì" if (status and status.osserva_prezzo) else "No"),
        })

    if not rows:
        return pd.DataFrame(columns=CLOSED_POSITIONS_COLUMNS)
    return pd.DataFrame(rows, columns=CLOSED_POSITIONS_COLUMNS)


def summarize_closed_positions(df_chiusi: pd.DataFrame) -> dict[str, float | int]:
    """Totali aggregati sulle posizioni chiuse: quante sono, capitale
    liberato complessivo, P/L lordo/netto complessivo, commissioni e
    imposte pagate complessive, return totale complessivo, rendimento %
    medio ponderato sul capitale liberato."""
    if df_chiusi is None or df_chiusi.empty:
        return {
            "n_posizioni": 0,
            "capitale_liberato_totale": 0.0,
            "pl_lordo_totale": 0.0,
            "commissioni_totali": 0.0,
            "imposte_totali": 0.0,
            "pl_realizzato_totale": 0.0,
            "cedole_dividendi_totali": 0.0,
            "return_totale": 0.0,
            "rendimento_pct_medio": None,
        }
    capitale_liberato_totale = float(pd.to_numeric(df_chiusi["Capitale Liberato €"], errors="coerce").fillna(0.0).sum())
    pl_realizzato_totale = float(pd.to_numeric(df_chiusi["P/L Realizzato €"], errors="coerce").fillna(0.0).sum())
    return {
        "n_posizioni": int(len(df_chiusi)),
        "capitale_liberato_totale": capitale_liberato_totale,
        "pl_lordo_totale": float(pd.to_numeric(df_chiusi["P/L Lordo €"], errors="coerce").fillna(0.0).sum()),
        "commissioni_totali": float(pd.to_numeric(df_chiusi["Commissioni €"], errors="coerce").fillna(0.0).sum()),
        "imposte_totali": float(pd.to_numeric(df_chiusi["Imposte €"], errors="coerce").fillna(0.0).sum()),
        "pl_realizzato_totale": pl_realizzato_totale,
        "cedole_dividendi_totali": float(pd.to_numeric(df_chiusi["Cedole/Div. netti €"], errors="coerce").fillna(0.0).sum()),
        "return_totale": float(pd.to_numeric(df_chiusi["Return Totale €"], errors="coerce").fillna(0.0).sum()),
        # Frazione (0.0323), stessa convenzione di fmt_pct_it — vedi nota in build_closed_positions_table.
        "rendimento_pct_medio": (pl_realizzato_totale / capitale_liberato_totale) if abs(capitale_liberato_totale) > 1e-9 else None,
    }
