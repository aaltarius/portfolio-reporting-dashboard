"""Tipo che descrive una serie registrata in archivio. Nessun elenco di indici o ETF: il registro e' l'archivio (ADR-0021)."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class IndexSpec:
    code: str
    label: str
    family: str
    provider: str
    currency: str
    return_type: str  # PRICE, TOTAL_RETURN, NET_TR, COMPOUNDED, ETF_ADJ_CLOSE, BLEND
    scope: str
    url: str = ""
    asset_kind: str = "index"  # index | etf_proxy | composite
