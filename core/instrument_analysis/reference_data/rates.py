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


def _maturity_token(years: float) -> str:
    """Porta `maturity_token` da
    `HANDOFF_PROGRAMMATORE_BENCHMARK_CDS/reference/poc17_4_engine_VALIDATED_REFERENCE.py`
    (riga 2017): converte anni in "5Y", "2Y6M", "18M" — il formato atteso
    dalla chiave di serie SDW YC (`PY_<token>`)."""
    months = max(1, round(years * 12))
    yy, mm = divmod(months, 12)
    if yy and mm:
        return f"{yy}Y{mm}M"
    if yy:
        return f"{yy}Y"
    return f"{mm}M"


def fetch_sovereign_curve(country_code: str, maturity_years: float, *, timeout: float = 5.0) -> RateSeries | None:
    """Curva euro-area par yield duration-matched (dataset SDW "YC", chiave
    "all bonds" `G_N_C`/`SV_C_YM` — porta `ecb_gov_curve` dal riferimento
    validato, riga 2021). Verificata in diretta il 2026-09-03: risponde con
    dati reali (5Y euro-area ~3,01%). `country_code` e' accettato per
    compatibilita' futura (spread paese-specifico, es. Italia via Banca
    d'Italia Rendistato — vedi `fetch_italy_sovereign_spread`) ma non
    seleziona ancora una curva diversa: la SDW YC pubblica solo la curva
    euro-area aggregata in modo affidabile, non curve sovrane per singolo
    paese."""
    token = _maturity_token(maturity_years)
    series_key = f"B.U2.EUR.4F.G_N_C.SV_C_YM.PY_{token}"
    url = f"{_SDW_BASE_URL}/YC/{series_key}?format=jsondata&lastNObservations=400"
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
    return _parse_sdw_jsondata(payload, series_id=series_key, label=f"EUR area government yield curve {token}")


def fetch_italy_sovereign_yield(maturity_years: float, *, timeout: float = 8.0) -> float | None:
    """Rendimento Italia (Rendistato, Banca d'Italia) per la banda di
    scadenza piu' vicina, in percentuale — porta il PRINCIPIO di
    `rendistato_latest` dal riferimento validato (righe 2038-2076: scarica
    il PDF ufficiale corrente e ne estrae il valore). Il chiamante calcola
    lo spread sottraendo la curva euro-area (`fetch_sovereign_curve`),
    stesso schema del riferimento (`spread = it - latest_euro`). Best-
    effort, mai bloccante: se la pagina/PDF non e' nel formato atteso
    (verificato il 2026-09-03: la pagina Banca d'Italia non espone piu' il
    link PDF nel formato che il riferimento si aspettava — probabile
    restyling del sito), ritorna None e il chiamante degrada onestamente
    alla sola curva euro-area (stesso comportamento del riferimento quando
    lo spread non e' disponibile, vedi `sovereign_curve.py`)."""
    try:
        page = requests.get(
            "https://www.bancaditalia.it/compiti/operazioni-mef/rendistato-rendiob/index.html",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout,
        ).text
    except Exception:
        return None
    import re
    from datetime import date as _date
    from io import BytesIO

    year = str(_date.today().year)
    href = ""
    for match in re.finditer(r'href=["\']([^"\']+)["\']', page, re.I):
        candidate = match.group(1)
        if year in candidate and "rendistato" in candidate.casefold() and candidate.casefold().endswith(".pdf"):
            href = candidate
            break
    if not href:
        return None
    url = href if href.startswith("http") else f"https://www.bancaditalia.it{href}"
    try:
        from pypdf import PdfReader
        pdf_bytes = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout).content
        text = "\n".join((page_obj.extract_text() or "") for page_obj in PdfReader(BytesIO(pdf_bytes)).pages)
    except Exception:
        return None

    bands = [
        (1.25, r"1\s+anno\s*[-–]\s*1\s+anno\s+6\s+mesi"),
        (2.04, r"1\s+anno\s+7\s+mesi\s*[-–]\s*2\s+anni\s+6\s+mesi"),
        (3.04, r"2\s+anni\s+7\s+mesi\s*[-–]\s*3\s+anni\s+6\s+mesi"),
        (4.04, r"3\s+anni\s+7\s+mesi\s*[-–]\s*4\s+anni\s+6\s+mesi"),
        (5.54, r"4\s+anni\s+7\s+mesi\s*[-–]\s*6\s+anni\s+6\s+mesi"),
        (7.54, r"6\s+anni\s+7\s+mesi\s*[-–]\s*8\s+anni\s+6\s+mesi"),
        (10.54, r"8\s+anni\s+7\s+mesi\s*[-–]\s*12\s+anni\s+6\s+mesi"),
        (16.54, r"12\s+anni\s+7\s+mesi\s*[-–]\s*20\s+anni\s+6\s+mesi"),
        (25.0, r"20\s+anni\s+7\s+mesi\s+e\s+oltre"),
    ]
    _band_years, pattern = min(bands, key=lambda item: abs(item[0] - maturity_years))
    matches = list(re.finditer(pattern, text, re.I))
    if not matches:
        return None
    window = text[matches[-1].end():matches[-1].end() + 1000]
    values = []
    for raw in re.findall(r"(?<!\d)(-?\d+[,.]\d{2,4})(?!\d)", window):
        try:
            value = float(raw.replace(",", "."))
        except ValueError:
            continue
        if -5.0 <= value <= 20.0:
            values.append(value)
    return values[-1] if values else None
