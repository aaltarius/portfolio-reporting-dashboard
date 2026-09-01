"""Adapter Borsa Italiana. Estende la stessa pagina gia' raggiunta da
core/market_data.py::get_borsa_italiana_etf_name con il benchmark ufficiale,
quando presente nella tabella dati della scheda ETF."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from core.instrument_analysis.contracts import ProvenanceItem

_HEADERS = {"User-Agent": "Mozilla/5.0"}


@dataclass(slots=True)
class BorsaItalianaEtfInfo:
    name: str
    benchmark_name: str
    provenance: ProvenanceItem


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_title(raw_title: str, isin: str) -> str:
    name = raw_title.strip()
    for suffix in (" - Borsa Italiana", " quotazioni", f" | {isin}"):
        name = name.split(suffix)[0]
    return name.strip()


def _find_benchmark_row(soup: BeautifulSoup) -> str:
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        label = cells[0].get_text(strip=True).lower()
        if "benchmark" in label or "indice" in label:
            return cells[1].get_text(strip=True)
    return ""


def fetch_etf_info(isin: str, *, timeout: float = 10.0) -> BorsaItalianaEtfInfo | None:
    isin_code = str(isin or "").strip().upper()
    if not isin_code:
        return None
    try:
        response = requests.get(
            f"https://www.borsaitaliana.it/borsa/etf/scheda/{isin_code}-ETFP.html?lang=it",
            headers=_HEADERS, timeout=timeout,
        )
    except Exception:
        return None
    if response.status_code != 200:
        return None
    soup = BeautifulSoup(response.text, "html.parser")
    title_tag = soup.find("title")
    if title_tag is None:
        return None
    name = _clean_title(title_tag.text, isin_code)
    if len(name) <= 5 or "borsa italiana" in name.lower() or "error" in name.lower():
        return None
    benchmark_name = _find_benchmark_row(soup)
    return BorsaItalianaEtfInfo(
        name=name,
        benchmark_name=benchmark_name,
        provenance=ProvenanceItem(
            source="borsa_italiana", field="identity", value=name,
            confidence=0.85 if benchmark_name else 0.6, fetched_at=_now_iso(),
        ),
    )
