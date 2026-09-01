"""Adapter ECB Statistical Data Warehouse (SDW) — API REST pubblica e
documentata, non scraping di pagina. Copre EUR short-term rate (spec
sezione J, MONEY MARKET) e, in un secondo passaggio, le curve sovrane
duration-specific (sezione I, BOND/BTP)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import requests

from core.instrument_analysis.contracts import ProvenanceItem

_SDW_BASE_URL = "https://data-api.ecb.europa.eu/service/data"

# Chiave serie EST (euro short-term rate) sul flusso ECB "EST". Verificare
# contro la documentazione SDW aggiornata al momento dell'implementazione
# (https://data.ecb.europa.eu/data/datasets/EST) — le chiavi di serie SDW
# possono cambiare struttura tra flussi, questa e' la chiave nota al
# momento della stesura di questo piano, non garantita immutabile.
_ESTR_SERIES_KEY = "B.EU000A2X2A25.WT"


@dataclass(slots=True)
class RateSeries:
    series_id: str
    label: str
    observations: dict[str, float]
    provenance: ProvenanceItem


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_sdw_jsondata(payload: dict, series_id: str, label: str) -> RateSeries | None:
    try:
        dataset = payload["dataSets"][0]
        series_map = dataset["series"]
        first_series = next(iter(series_map.values()))
        observation_values = first_series["observations"]
        date_labels = payload["structure"]["dimensions"]["observation"][0]["values"]
    except (KeyError, IndexError, StopIteration):
        return None

    observations: dict[str, float] = {}
    for index_str, value_list in observation_values.items():
        index = int(index_str)
        if index >= len(date_labels) or not value_list:
            continue
        date_label = date_labels[index]["id"]
        observations[date_label] = float(value_list[0])

    if not observations:
        return None

    return RateSeries(
        series_id=series_id, label=label, observations=observations,
        provenance=ProvenanceItem(source="ecb_sdw", field="rate", value=series_id,
                                   confidence=0.95, fetched_at=_now_iso()),
    )


def fetch_estr(*, timeout: float = 5.0) -> RateSeries | None:
    url = f"{_SDW_BASE_URL}/EST/{_ESTR_SERIES_KEY}?format=jsondata&lastNObservations=30"
    try:
        response = requests.get(url, headers={"Accept": "application/json"}, timeout=timeout)
    except Exception:
        return None
    if response.status_code != 200:
        return None
    try:
        payload = response.json()
    except Exception:
        return None
    return _parse_sdw_jsondata(payload, series_id="ESTR", label="Euro Short-Term Rate")


def fetch_sovereign_curve(country_code: str, maturity_years: float, *, timeout: float = 5.0) -> RateSeries | None:
    # Le curve sovrane duration-specific (BTP/Bund/OAT per scadenza) hanno
    # chiavi SDW diverse per paese/scadenza (dataset "YC" o "IRS" a seconda
    # della curva) — da verificare e completare in un secondo passaggio con
    # una risposta live reale per almeno il caso Italia (BTP), stesso
    # principio di completamento incrementale del Task A7 per STOXX. Finche'
    # non e' completata, ritorna sempre None: il ladder (Task A10) degrada
    # a mercato generale invece di inventare una curva.
    return None
