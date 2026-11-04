"""Adapter OpenFIGI (mapping ID_ISIN -> identita' strumento). REST pubblico,
nessuna chiave richiesta per il volume di questo portafoglio."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import requests

from core.instrument_analysis.contracts import ProvenanceItem

_OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"


@dataclass(slots=True)
class OpenFigiIdentity:
    figi: str
    name: str
    ticker: str
    security_type: str
    security_type2: str
    market_sector: str
    exchange: str
    provenance: ProvenanceItem


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def map_isin(isin: str, *, timeout: float = 5.0) -> OpenFigiIdentity | None:
    isin_code = str(isin or "").strip().upper()
    if not isin_code:
        return None
    try:
        response = requests.post(
            _OPENFIGI_URL,
            json=[{"idType": "ID_ISIN", "idValue": isin_code}],
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
    except Exception:
        return None
    if response.status_code != 200:
        return None
    try:
        payload = response.json()
    except Exception:
        return None
    if not isinstance(payload, list) or not payload:
        return None
    rows = payload[0].get("data") if isinstance(payload[0], dict) else None
    if not rows:
        return None
    row = rows[0]
    return OpenFigiIdentity(
        figi=str(row.get("figi") or ""),
        name=str(row.get("name") or ""),
        ticker=str(row.get("ticker") or ""),
        security_type=str(row.get("securityType") or ""),
        security_type2=str(row.get("securityType2") or ""),
        market_sector=str(row.get("marketSector") or ""),
        exchange=str(row.get("exchCode") or ""),
        provenance=ProvenanceItem(
            source="openfigi", field="identity", value=row.get("figi"),
            confidence=0.9, fetched_at=_now_iso(),
        ),
    )
