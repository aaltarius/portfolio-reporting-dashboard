"""
core/asset_categories.py — Registry centralizzato delle categorie strumenti.

Fonte unica di verita' per:
- codice categoria
- nome breve
- descrizione
- colore
- alias legacy
"""
from __future__ import annotations

import copy
from typing import Any

from core.config import COLORS


ASSET_CATEGORY_REGISTRY: dict[str, dict[str, str]] = {
    "LIQ": {
        "label": "LIQ",
        "name": "Liquidità",
        "description": "Conti correnti, conti deposito, pronti contro termine.",
        "color": "#26A69A",
    },
    "GOV": {
        "label": "GOV",
        "name": "Titoli di Stato",
        "description": "BTP, BOT, CCT, BTP Italia, BTP€i e sovrani esteri.",
        "color": COLORS["category_gov"],
    },
    "OBB": {
        "label": "OBB",
        "name": "Obbligazioni",
        "description": "Corporate, bancarie e sovranazionali.",
        "color": "#7E57C2",
    },
    "AZI": {
        "label": "AZI",
        "name": "Azioni",
        "description": "Azioni singole.",
        "color": "#EF6C9A",
    },
    "ETF": {
        "label": "ETF",
        "name": "Exchange Traded Fund",
        "description": "ETF quotati.",
        "color": COLORS["category_etf"],
    },
    "ETC": {
        "label": "ETC",
        "name": "Exchange Traded Commodity",
        "description": "ETC ed eventuali ETN.",
        "color": COLORS["category_etc"],
    },
    "FND": {
        "label": "FND",
        "name": "Fondi comuni e SICAV",
        "description": "Fondi comuni, SICAV e FAM.",
        "color": COLORS["category_fnd"],
    },
    "DER": {
        "label": "DER",
        "name": "Derivati e certificates",
        "description": "Futures, opzioni e investment certificates.",
        "color": "#8E44AD",
    },
    "ALTRO": {
        "label": "ALTRO",
        "name": "Altro",
        "description": "Categoria non classificata.",
        "color": COLORS["category_default"],
    },
}

MAX_VISIBLE_CATEGORY_CODES = 5
DEFAULT_VISIBLE_CATEGORY_CODES = ["GOV", "ETF", "FND", "AZI", "OBB"]
ACTIVE_CATEGORY_CODES = ["GOV", "ETF", "FND"]

LEGACY_CATEGORY_ALIASES = {
    "BTP": "GOV",
    "PAC": "FND",
    "FONDO": "FND",
    "FONDI": "FND",
    "LIQUIDITA": "LIQ",
    "AZIONI": "AZI",
    "OBBLIGAZIONI": "OBB",
    "DERIVATI": "DER",
}


def normalize_category_code(value: Any, default: str = "ALTRO") -> str:
    text = str(value or "").strip().upper()
    if not text:
        return default
    if text in ASSET_CATEGORY_REGISTRY:
        return text
    if text in LEGACY_CATEGORY_ALIASES:
        return LEGACY_CATEGORY_ALIASES[text]
    return default


def infer_category_code(value: Any, default: str = "ALTRO") -> str:
    raw = str(value or "").strip()
    code = normalize_category_code(raw, default="")
    if code:
        return code
    txt = raw.lower()

    if any(token in txt for token in ("conto corrente", "conti correnti", "conto deposito", "deposito", "pronti contro termine", "pct", "liquid")):
        return "LIQ"
    if any(token in txt for token in ("titolo di stato", "titoli di stato", "btp", "bot", "cct", "btp italia", "btp€i", "btei", "gov", "sovrano")):
        return "GOV"
    if any(token in txt for token in ("obblig", "bond", "corporate", "sovranazional", "supranational")):
        return "OBB"
    if any(token in txt for token in ("azione", "azioni", "stock", "equity")):
        return "AZI"
    if "etf" in txt:
        return "ETF"
    if any(token in txt for token in ("etc", "etn", "commodity")):
        return "ETC"
    if any(token in txt for token in ("fondo", "fondi", "sicav", "fam", "pac")):
        return "FND"
    if any(token in txt for token in ("deriv", "future", "futures", "opzion", "certificate", "certificates")):
        return "DER"
    return default


def category_label(code: Any) -> str:
    normalized = normalize_category_code(code)
    return ASSET_CATEGORY_REGISTRY.get(normalized, ASSET_CATEGORY_REGISTRY["ALTRO"])["label"]


def category_name(code: Any) -> str:
    normalized = normalize_category_code(code)
    return ASSET_CATEGORY_REGISTRY.get(normalized, ASSET_CATEGORY_REGISTRY["ALTRO"])["name"]


def category_description(code: Any) -> str:
    normalized = normalize_category_code(code)
    return ASSET_CATEGORY_REGISTRY.get(normalized, ASSET_CATEGORY_REGISTRY["ALTRO"])["description"]


def category_color(code: Any) -> str:
    normalized = normalize_category_code(code)
    return ASSET_CATEGORY_REGISTRY.get(normalized, ASSET_CATEGORY_REGISTRY["ALTRO"])["color"]


def normalize_category_selection(
    values: Any,
    *,
    max_items: int = MAX_VISIBLE_CATEGORY_CODES,
    fallback: list[str] | None = None,
) -> list[str]:
    """Normalizza una selezione categorie mantenendo ordine, unicita' e limite massimo."""
    fallback = list(fallback or DEFAULT_VISIBLE_CATEGORY_CODES)
    raw_values = values if isinstance(values, (list, tuple, set)) else fallback

    selected: list[str] = []
    for value in raw_values:
        normalized = normalize_category_code(value, default="")
        if normalized and normalized in ASSET_CATEGORY_REGISTRY and normalized not in selected:
            selected.append(normalized)
        if len(selected) >= max_items:
            break

    if not selected:
        return fallback[:max_items]
    return selected[:max_items]


def get_selected_category_codes(settings: dict[str, Any] | None = None) -> list[str]:
    """Restituisce le categorie selezionate dalle impostazioni, con fallback sicuro."""
    payload = settings if isinstance(settings, dict) else {}
    category_view = payload.get("category_view", {})
    if not isinstance(category_view, dict):
        category_view = {}
    return normalize_category_selection(category_view.get("selected_categories"))


def filter_data_by_selected_categories(
    data: dict[str, Any] | None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Restituisce una copia del dataset limitata alle categorie attive.

    Le categorie non selezionate vengono escluse dal perimetro attivo:
    strumenti, operazioni, proventi, eventi, ledger e storico prezzi.
    """
    payload = copy.deepcopy(data or {})
    selected_categories = set(get_selected_category_codes(settings))
    strumenti = list(payload.get("strumenti", []) or [])
    selected_tickers = {
        str(item.get("ticker") or "")
        for item in strumenti
        if normalize_category_code(infer_category_code(item.get("tipo", ""))) in selected_categories
    }
    excluded_tickers = {
        str(item.get("ticker") or "")
        for item in strumenti
        if str(item.get("ticker") or "") and str(item.get("ticker") or "") not in selected_tickers
    }

    def _text_blob(record: Any) -> str:
        if not isinstance(record, dict):
            return str(record or "").upper()
        parts = []
        for key in ("ticker", "note", "descrizione", "strumento", "nome"):
            value = record.get(key)
            if value:
                parts.append(str(value))
        return " | ".join(parts).upper()

    def _keep_record(record: Any) -> bool:
        if not isinstance(record, dict):
            return True
        ticker = str(record.get("ticker") or "").strip()
        if ticker:
            return ticker in selected_tickers
        blob = _text_blob(record)
        if not blob:
            return True
        for excluded in excluded_tickers:
            if excluded and excluded.upper() in blob:
                return False
        return True

    payload["strumenti"] = [item for item in strumenti if str(item.get("ticker") or "") in selected_tickers]
    for key in ("operazioni", "registro_eventi", "proventi", "registro_liquidita"):
        payload[key] = [item for item in list(payload.get(key, []) or []) if _keep_record(item)]

    storico = {}
    for raw_date, prices in (payload.get("storico_prezzi", {}) or {}).items():
        if isinstance(prices, dict):
            filtered_prices = {tk: value for tk, value in prices.items() if str(tk or "") in selected_tickers}
            if filtered_prices:
                storico[raw_date] = filtered_prices
    payload["storico_prezzi"] = storico

    instrument_master = payload.get("instrument_master", {})
    if isinstance(instrument_master, dict):
        payload["instrument_master"] = {
            tk: value for tk, value in instrument_master.items()
            if str(tk or "") in selected_tickers
        }

    payload["cache_posizioni"] = {}
    payload["cache_storico_portafoglio"] = {}
    return payload
