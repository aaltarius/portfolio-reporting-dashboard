"""Adapter provider indice — Livello 2 (MSCI, endpoint JSON pubblico).
Provider non ancora supportati ritornano None immediatamente, senza
tentare rete: mai un match inventato (spec sezione 4). STOXX/FTSE
Russell/S&P DJI/Solactive/ICE (Livello 3, best-effort) non sono ancora in
SUPPORTED_PROVIDERS in questa fase — vedi la "Nota per l'implementatore"
dopo questo blocco di codice per come attivarli in un secondo passaggio,
senza fingere un supporto che non esiste ancora."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

from core.instrument_analysis.contracts import ProvenanceItem

SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"MSCI"})

_MSCI_HISTORY_DAYS = 30


@dataclass(slots=True)
class IndexProviderMatch:
    provider: str
    code: str
    name: str
    provenance: ProvenanceItem


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def lookup_msci_index(index_code: str, *, variant: str = "NETR", currency: str = "USD",
                      timeout: float = 5.0) -> IndexProviderMatch | None:
    code = str(index_code or "").strip()
    if not code:
        return None
    url = "https://app2.msci.com/products/service/index/indexmaster/getLevelDataForGraph?" + urlencode({
        "currency_symbol": currency, "index_variant": variant,
        "start_date": (date.today() - timedelta(days=_MSCI_HISTORY_DAYS)).strftime("%Y%m%d"),
        "end_date": date.today().strftime("%Y%m%d"), "data_frequency": "DAILY", "index_codes": code,
    })
    try:
        response = requests.get(
            url, headers={"Accept": "application/json,text/plain,*/*", "Referer": "https://www.msci.com/"},
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
    levels = (payload.get("indexes") or {}).get("INDEX_LEVELS") or []
    if not levels:
        return None
    return IndexProviderMatch(
        provider="MSCI", code=code, name=f"MSCI {code}",
        provenance=ProvenanceItem(source="msci", field="benchmark", value=code,
                                   confidence=0.8, fetched_at=_now_iso()),
    )


def lookup_index_provider(provider: str, query: str) -> IndexProviderMatch | None:
    provider_code = str(provider or "").strip().upper()
    if provider_code not in SUPPORTED_PROVIDERS:
        return None
    if provider_code == "MSCI":
        return lookup_msci_index(query)
    return None
