"""
core/portfolio_metrics.py -- Definizioni canoniche dei KPI di portafoglio.
"""

from typing import Any

import pandas as pd

_EPS = 1e-9


def _sum_numeric(frame: pd.DataFrame | None, column: str) -> float:
    if frame is None or frame.empty or column not in frame.columns:
        return 0.0
    return float(pd.to_numeric(frame[column], errors="coerce").fillna(0).sum())


def _split_open_closed_positions(
    df_positions: pd.DataFrame | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df_positions is None or df_positions.empty:
        return pd.DataFrame(), pd.DataFrame()
    if "Quote" not in df_positions.columns:
        return df_positions.copy(), pd.DataFrame()
    open_positions = df_positions[df_positions["Quote"] > 0.0001].copy()
    closed_positions = df_positions[df_positions["Quote"] <= 0.0001].copy()
    return open_positions, closed_positions


def _realized_total(frame: pd.DataFrame | None) -> float:
    if frame is None or frame.empty:
        return 0.0
    if "P/L Realizzato Netto" in frame.columns:
        return _sum_numeric(frame, "P/L Realizzato Netto")
    return _sum_numeric(frame, "P/L €")


def calcola_kpi_principali(
    df_positions: pd.DataFrame,
    liquidita: float,
    *,
    capitale_investito: float | None = None,
) -> dict[str, float]:
    """
    Restituisce i KPI centrali del portafoglio con una sola definizione canonica.

    - `pl` e `pl_pct` descrivono l'unrealized sulle posizioni aperte.
    - `pl_totale` e `pl_totale_pct` includono il realizzato netto di aperte e chiuse.
    """
    if df_positions is None or df_positions.empty:
        return {
            "tv": 0.0,
            "tc": 0.0,
            "pl": 0.0,
            "pl_pct": 0.0,
            "pl_realizzato_aperte": 0.0,
            "pl_realizzato_chiuse": 0.0,
            "pl_realizzato_totale": 0.0,
            "pl_totale": 0.0,
            "pl_totale_pct": 0.0,
            "pp": 0.0,
            "patrimonio_totale": float(liquidita),
            "liquidita": float(liquidita),
            "capitale_investito": float(capitale_investito or 0.0),
        }

    open_positions, closed_positions = _split_open_closed_positions(df_positions)

    tv = _sum_numeric(open_positions, "Controvalore")
    tc = _sum_numeric(open_positions, "Costo")
    pl = tv - tc

    pl_realizzato_aperte = _realized_total(open_positions)
    pl_realizzato_chiuse = _realized_total(closed_positions)
    pl_realizzato_totale = pl_realizzato_aperte + pl_realizzato_chiuse
    pl_totale = pl + pl_realizzato_totale

    capital_base = float(capitale_investito or 0.0)
    if abs(capital_base) <= _EPS:
        capital_base = tc

    pl_pct = (pl / abs(tc)) if abs(tc) > _EPS else 0.0
    pl_totale_pct = (pl_totale / abs(capital_base)) if abs(capital_base) > _EPS else 0.0

    return {
        "tv": tv,
        "tc": tc,
        "pl": pl,
        "pl_pct": pl_pct,
        "pl_realizzato_aperte": pl_realizzato_aperte,
        "pl_realizzato_chiuse": pl_realizzato_chiuse,
        "pl_realizzato_totale": pl_realizzato_totale,
        "pl_totale": pl_totale,
        "pl_totale_pct": pl_totale_pct,
        "pp": pl_totale_pct,
        "patrimonio_totale": tv + float(liquidita),
        "liquidita": float(liquidita),
        "capitale_investito": float(capitale_investito or 0.0),
    }


def calcola_capitale_netto_versato(
    versamenti_netti: float,
    cap_investito: float,
) -> float:
    return versamenti_netti if abs(versamenti_netti) > _EPS else cap_investito


def calcola_capitale_rientrato(
    eventi_portafoglio: list[dict[str, Any]] | None,
) -> float:
    eventi_portafoglio = eventi_portafoglio or []
    posizioni_rientro: dict[str, dict[str, float]] = {}
    capitale_rientrato_totale = 0.0

    for evento in eventi_portafoglio:
        tipo_evento = evento.get("tipo_evento")
        ticker = str(evento.get("ticker", "") or "")

        try:
            quantita = float(evento.get("quantita", 0) or 0)
        except (ValueError, TypeError):
            quantita = 0.0

        try:
            prezzo = float(evento.get("prezzo_unitario", 0) or 0)
        except (ValueError, TypeError):
            prezzo = 0.0

        try:
            commissioni = float(evento.get("commissioni", 0) or 0)
        except (ValueError, TypeError):
            commissioni = 0.0

        try:
            imposte = float(evento.get("imposte", 0) or 0)
        except (ValueError, TypeError):
            imposte = 0.0

        if ticker and ticker not in posizioni_rientro:
            posizioni_rientro[ticker] = {"qty": 0.0, "cost": 0.0}

        if tipo_evento == "ACQUISTO" and ticker:
            posizioni_rientro[ticker]["qty"] += quantita
            posizioni_rientro[ticker]["cost"] += quantita * prezzo + commissioni + imposte
        elif tipo_evento in {"VENDITA", "RIMBORSO A SCADENZA"} and ticker:
            qty_before = posizioni_rientro[ticker]["qty"]
            cost_before = posizioni_rientro[ticker]["cost"]
            scarico_qty = min(quantita, qty_before) if qty_before > 0 else 0.0
            pmc = (cost_before / qty_before) if qty_before > _EPS else 0.0
            scarico_cost = scarico_qty * pmc

            capitale_rientrato_totale += scarico_cost

            posizioni_rientro[ticker]["qty"] = max(0.0, qty_before - scarico_qty)
            posizioni_rientro[ticker]["cost"] = max(0.0, cost_before - scarico_cost)

    return float(capitale_rientrato_totale)


def calcola_flussi_capitale(
    eventi_portafoglio: list[dict[str, Any]] | None,
) -> dict[str, float]:
    eventi_portafoglio = eventi_portafoglio or []
    cap_investito = sum(
        (
            float(evento.get("quantita", 0) or 0) * float(evento.get("prezzo_unitario", 0) or 0)
            + float(evento.get("commissioni", 0) or 0)
            + float(evento.get("imposte", 0) or 0)
        )
        for evento in eventi_portafoglio
        if evento.get("tipo_evento") == "ACQUISTO"
    )
    versamenti_netti = sum(
        abs(float(evento.get("importo_netto", 0) or evento.get("importo_lordo", 0) or 0))
        if evento.get("tipo_evento") == "VERSAMENTO"
        else -(
            abs(float(evento.get("importo_netto", 0) or evento.get("importo_lordo", 0) or 0))
            if evento.get("tipo_evento") == "PRELIEVO"
            else 0.0
        )
        for evento in eventi_portafoglio
    )
    cap_netto = calcola_capitale_netto_versato(versamenti_netti, cap_investito)
    cap_rientrato = calcola_capitale_rientrato(eventi_portafoglio)

    return {
        "cap_investito": float(cap_investito),
        "versamenti_netti": float(versamenti_netti),
        "cap_netto": float(cap_netto),
        "cap_rientrato": float(cap_rientrato),
    }


def calcola_total_return(
    pl_totale: float,
    proventi_netti: float,
    capitale_netto_versato: float,
) -> tuple[float, float]:
    total_return = float(pl_totale) + float(proventi_netti)
    total_return_pct = (
        total_return / float(capitale_netto_versato)
        if abs(float(capitale_netto_versato)) > _EPS
        else 0.0
    )
    return total_return, total_return_pct
