"""
core/portfolio_metrics.py -- Definizioni canoniche dei KPI di portafoglio.
"""

from typing import Any
import math

import pandas as pd

from core.constants import QTY_ZERO_EPS
from core.domain.positions import discharge_lot

_EPS = 1e-9


def _finite_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool) or value in (None, ""):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _sum_numeric(frame: pd.DataFrame | None, column: str) -> float:
    if frame is None or frame.empty or column not in frame.columns:
        return 0.0
    values = pd.to_numeric(frame[column], errors="coerce").replace([float("inf"), -float("inf")], pd.NA)
    return float(values.fillna(0).sum())


def _split_open_closed_positions(
    df_positions: pd.DataFrame | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df_positions is None or df_positions.empty:
        return pd.DataFrame(), pd.DataFrame()
    if "Quote" not in df_positions.columns:
        return df_positions.copy(), pd.DataFrame()
    quote_values = pd.to_numeric(df_positions["Quote"], errors="coerce").replace([float("inf"), -float("inf")], pd.NA).fillna(0.0)
    open_positions = df_positions[quote_values > QTY_ZERO_EPS].copy()
    closed_positions = df_positions[quote_values <= QTY_ZERO_EPS].copy()
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
        liquidita_value = _finite_float(liquidita)
        capitale_value = _finite_float(capitale_investito)
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
            "patrimonio_totale": liquidita_value,
            "liquidita": liquidita_value,
            "capitale_investito": capitale_value,
            "capitale_versato_residuo": 0.0,
        }

    open_positions, closed_positions = _split_open_closed_positions(df_positions)

    tv = _sum_numeric(open_positions, "Controvalore")
    tc = _sum_numeric(open_positions, "Costo")
    pl = tv - tc

    pl_realizzato_aperte = _realized_total(open_positions)
    pl_realizzato_chiuse = _realized_total(closed_positions)
    pl_realizzato_totale = pl_realizzato_aperte + pl_realizzato_chiuse
    pl_totale = pl + pl_realizzato_totale

    capital_base = _finite_float(capitale_investito)
    if abs(capital_base) <= _EPS:
        capital_base = tc

    pl_pct = (pl / abs(tc)) if abs(tc) > _EPS else 0.0
    pl_totale_pct = (pl_totale / abs(capital_base)) if abs(capital_base) > _EPS else 0.0

    liquidita_value = _finite_float(liquidita)
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
        "patrimonio_totale": tv + liquidita_value,
        "liquidita": liquidita_value,
        "capitale_investito": _finite_float(capitale_investito),
        "capitale_versato_residuo": tc,
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

        quantita = _finite_float(evento.get("quantita", 0))
        prezzo = _finite_float(evento.get("prezzo_unitario", 0))
        commissioni = _finite_float(evento.get("commissioni", 0))
        imposte = _finite_float(evento.get("imposte", 0))

        if ticker and ticker not in posizioni_rientro:
            posizioni_rientro[ticker] = {"qty": 0.0, "cost": 0.0}

        if tipo_evento == "ACQUISTO" and ticker:
            posizioni_rientro[ticker]["qty"] += quantita
            posizioni_rientro[ticker]["cost"] += quantita * prezzo + commissioni + imposte
        elif tipo_evento in {"VENDITA", "RIMBORSO A SCADENZA"} and ticker:
            result = discharge_lot(
                posizioni_rientro[ticker]["qty"], posizioni_rientro[ticker]["cost"],
                quantita, prezzo, commissioni, imposte,
            )
            capitale_rientrato_totale += result.capitale_liberato
            posizioni_rientro[ticker]["qty"] = result.qty_dopo
            posizioni_rientro[ticker]["cost"] = result.costo_dopo

    return float(capitale_rientrato_totale)


def calcola_flussi_capitale(
    eventi_portafoglio: list[dict[str, Any]] | None,
) -> dict[str, float]:
    eventi_portafoglio = eventi_portafoglio or []
    cap_investito = 0.0
    versamenti_netti = 0.0
    for evento in eventi_portafoglio:
        tipo_evento = evento.get("tipo_evento")
        if tipo_evento == "ACQUISTO":
            cap_investito += (
                _finite_float(evento.get("quantita", 0)) * _finite_float(evento.get("prezzo_unitario", 0))
                + _finite_float(evento.get("commissioni", 0))
                + _finite_float(evento.get("imposte", 0))
            )
        elif tipo_evento in {"VERSAMENTO", "PRELIEVO"}:
            amount = _finite_float(evento.get("importo_netto", None), default=0.0)
            if abs(amount) <= _EPS:
                amount = _finite_float(evento.get("importo_lordo", 0))
            versamenti_netti += abs(amount) if tipo_evento == "VERSAMENTO" else -abs(amount)
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
    capitale = _finite_float(capitale_netto_versato)
    total_return = _finite_float(pl_totale) + _finite_float(proventi_netti)
    total_return_pct = (
        total_return / capitale
        if abs(capitale) > _EPS
        else 0.0
    )
    return total_return, total_return_pct
