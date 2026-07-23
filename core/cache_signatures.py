"""
core/cache_signatures.py — Deterministic signature generation for cache invalidation.

This module provides signature functions that generate consistent hashes based on
portfolio state, visual theme, and configuration. These signatures enable automatic
cache invalidation without manual busting: when any relevant data changes, the
signature changes, triggering regeneration of cached figures.

All functions are pure (no side effects) and deterministic: identical inputs
always produce identical signatures.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

logger = logging.getLogger("portafoglio.core.cache_signatures")


def _safe_hash(data: Any, max_depth: int = 3) -> str:
    """
    Create a deterministic SHA256 hash for any object.

    Attempts to JSON-serialize the data, falls back to repr() for non-JSON types.
    Returns the first 12 characters of the hex digest.

    Args:
        data: Object to hash
        max_depth: Maximum recursion depth for JSON serialization (default 3)

    Returns:
        12-character hex string
    """
    def _to_json_compatible(obj: Any, depth: int = 0) -> Any:
        """Convert object to JSON-compatible format."""
        if depth >= max_depth:
            return repr(obj)
        if isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        if isinstance(obj, (list, tuple)):
            return [_to_json_compatible(item, depth + 1) for item in obj]
        if isinstance(obj, dict):
            return {str(k): _to_json_compatible(v, depth + 1) for k, v in obj.items()}
        if isinstance(obj, SimpleNamespace):
            return _to_json_compatible(vars(obj), depth + 1)
        return repr(obj)

    try:
        json_compatible = _to_json_compatible(data)
        json_str = json.dumps(json_compatible, sort_keys=True, default=str)
        digest = hashlib.sha256(json_str.encode("utf-8")).hexdigest()
        return digest[:12]
    except Exception as e:
        logger.warning("Hash failure for data type %s: %s. Falling back to repr()", type(data).__name__, e)
        try:
            repr_str = repr(data)
            digest = hashlib.sha256(repr_str.encode("utf-8")).hexdigest()
            return digest[:12]
        except Exception as e2:
            logger.warning("Fallback hash also failed: %s. Using default signature", e2)
            return "000000000000"


def data_signature(
    n_instruments: int,
    n_operations: int,
    last_quotes_update: str,
    portfolio_data_hash: str,
    app_version: str,
    schema_version: str,
) -> str:
    """
    Hash portfolio state to detect when data has changed.

    Combines instrument count, operation count, portfolio content hash, and
    version strings. `last_quotes_update` is accepted for backward-compatible
    call sites but is intentionally excluded because it is operational metadata,
    not a financial state change by itself.

    Args:
        n_instruments: Number of instruments in portfolio
        n_operations: Number of transactions/operations
        last_quotes_update: ISO timestamp of last quotes update
        portfolio_data_hash: Content hash of portfolio data
        app_version: Application version string
        schema_version: Data schema version string

    Returns:
        12-character hex string
    """
    state = {
        "n_instruments": n_instruments,
        "n_operations": n_operations,
        "portfolio_data_hash": portfolio_data_hash,
        "app_version": app_version,
        "schema_version": schema_version,
    }
    return _safe_hash(state)


def _normalized_instrument_signature_payload(strumenti: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in strumenti:
        if not isinstance(item, dict):
            continue
        prezzo = item.get("prezzo", None)
        try:
            prezzo = None if prezzo in (None, "") else round(float(prezzo), 4)
        except Exception:
            prezzo = str(prezzo or "")
        stato_raw = item.get("stato")
        stato_norm = "chiuso" if stato_raw in {"chiuso", "osservato"} else "aperto"
        normalized.append({
            "isin": str(item.get("isin", "")).strip(),
            "ticker": str(item.get("ticker", "")).strip(),
            "tipo": str(item.get("tipo", "")).strip(),
            "prezzo": prezzo,
            "stato": stato_norm,
        })
    return sorted(normalized, key=lambda row: (row["ticker"], row["isin"], row["tipo"]))


def _normalized_operation_signature_payload(operazioni: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in operazioni:
        if not isinstance(item, dict):
            continue
        normalized.append({
            "event_id": str(item.get("event_id", "") or ""),
            "data": str(item.get("data", "") or ""),
            "ticker": str(item.get("ticker", "") or ""),
            "tipo_evento": str(item.get("tipo_evento", "") or item.get("tipo", "") or ""),
            "quantita": item.get("quantita", None),
            "prezzo_unitario": item.get("prezzo_unitario", None),
            "importo_netto": item.get("importo_netto", None),
            "commissioni": item.get("commissioni", None),
            "imposte": item.get("imposte", None),
        })
    return sorted(
        normalized,
        key=lambda row: (
            row["data"],
            row["ticker"],
            row["tipo_evento"],
            row["event_id"],
        ),
    )


def history_span_by_ticker(storico: dict[str, Any], tickers: list[str]) -> dict[str, dict[str, Any]]:
    """
    Per ogni ticker: quante date storiche lo includono e la piu' vecchia.

    n_history_dates/latest_history_date globali non bastano a rilevare un
    backfill (core.market_data.backfill_storico_prezzi) che riempie date piu'
    vecchie GIA' presenti come chiave nello storico (es. altri strumenti hanno
    gia' un prezzo su quel giorno): la chiave non e' nuova, quindi il conteggio
    e la data piu' recente restano identici anche se il ticker backfillato ha
    ora un perimetro storico piu' ampio. Guardare la presenza per-ticker cattura
    questo caso restando comunque stabile durante un refresh quotazioni
    intraday, che aggiorna solo il *valore* del prezzo odierno, non le chiavi.
    """
    ticker_set = {t for t in tickers if t}
    dates_by_ticker: dict[str, list[str]] = {t: [] for t in ticker_set}
    for day, prices in storico.items():
        if not isinstance(prices, dict):
            continue
        for tk in prices:
            if tk in ticker_set:
                dates_by_ticker[tk].append(day)
    return {
        tk: {"n_dates": len(dates), "earliest": min(dates) if dates else ""}
        for tk, dates in dates_by_ticker.items()
    }


def _base_market_signature_payload(
    data: dict[str, Any] | None,
    *,
    include_benchmark_data: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], str]:
    payload = data if isinstance(data, dict) else {}
    strumenti = payload.get("strumenti", []) if isinstance(payload.get("strumenti", []), list) else []
    operazioni = payload.get("operazioni", []) if isinstance(payload.get("operazioni", []), list) else []
    storico = payload.get("storico_prezzi", {}) if isinstance(payload.get("storico_prezzi", {}), dict) else {}
    latest_history_date = max(storico.keys()) if storico else ""
    last_quotes_update = str(
        payload.get("last_quotes_update")
        or payload.get("_last_quotes_update")
        or ""
    )

    registro_eventi = payload.get("registro_eventi", []) if isinstance(payload.get("registro_eventi", []), list) else []
    registro_liquidita = payload.get("registro_liquidita", []) if isinstance(payload.get("registro_liquidita", []), list) else []

    all_tickers = sorted({
        str(s.get("ticker", "")).strip()
        for s in strumenti
        if isinstance(s, dict) and str(s.get("ticker", "")).strip()
    })
    signature_payload: dict[str, Any] = {
        "instruments": _normalized_instrument_signature_payload(strumenti),
        "n_history_dates": len(storico),
        "latest_history_date": latest_history_date,
        "n_eventi": len(registro_eventi),
        "n_liquidita": len(registro_liquidita),
        "history_span_by_ticker": history_span_by_ticker(storico, all_tickers),
    }
    if include_benchmark_data:
        benchmark_data = payload.get("benchmark_data", {}) if isinstance(payload.get("benchmark_data", {}), dict) else {}
        signature_payload["benchmark_points"] = {
            str(key): len(value) if isinstance(value, dict) else 0
            for key, value in sorted(benchmark_data.items())
        }

    return signature_payload, strumenti, operazioni, storico, last_quotes_update


def build_market_data_signature(
    data: dict[str, Any] | None,
    *,
    app_version: str,
    schema_version: str,
    include_benchmark_data: bool = False,
) -> str:
    """Firma per dataset che dipendono da strumenti, storico prezzi e benchmark."""
    signature_payload, strumenti, _operazioni, _storico, last_quotes_update = _base_market_signature_payload(
        data,
        include_benchmark_data=include_benchmark_data,
    )
    market_data_hash = _safe_hash(signature_payload)
    return data_signature(
        n_instruments=len(strumenti),
        n_operations=0,
        last_quotes_update=last_quotes_update,
        portfolio_data_hash=market_data_hash,
        app_version=str(app_version),
        schema_version=str(schema_version),
    )


def build_cashflow_data_signature(
    data: dict[str, Any] | None,
    *,
    app_version: str,
    schema_version: str,
    include_benchmark_data: bool = False,
) -> str:
    """Firma per dataset che dipendono anche dal dettaglio delle operazioni."""
    signature_payload, strumenti, operazioni, _storico, last_quotes_update = _base_market_signature_payload(
        data,
        include_benchmark_data=include_benchmark_data,
    )
    signature_payload["operations"] = _normalized_operation_signature_payload(operazioni)
    cashflow_data_hash = _safe_hash(signature_payload)
    return data_signature(
        n_instruments=len(strumenti),
        n_operations=len(operazioni),
        last_quotes_update=last_quotes_update,
        portfolio_data_hash=cashflow_data_hash,
        app_version=str(app_version),
        schema_version=str(schema_version),
    )


def build_category_data_signature(
    data: dict[str, Any] | None,
    category: str,
    *,
    app_version: str,
    schema_version: str,
) -> str:
    """
    Firma per figure che dipendono solo dagli strumenti di una macro-categoria.

    Isola il subset di strumenti con tipo==category così che un aggiornamento
    quotazioni su ETF non invalidi le figure GOV/FND e viceversa.
    history_span_by_ticker (scoped ai soli ticker della categoria) e' l'unico
    meccanismo di rilevamento cambi storico: cattura sia il caso "nuovo
    giorno di quotazione per un ticker di questa categoria" sia il caso
    backfill (una data piu' vecchia gia' esistente riceve ora un valore per
    un ticker di questa categoria), senza dipendere da contatori globali che
    invaliderebbero la firma anche per categorie non toccate dal refresh.
    """
    payload = data if isinstance(data, dict) else {}
    strumenti = payload.get("strumenti", [])
    if not isinstance(strumenti, list):
        strumenti = []

    cat_strumenti = [
        s for s in strumenti
        if isinstance(s, dict) and str(s.get("tipo", "")).strip() == category
    ]

    storico = payload.get("storico_prezzi", {})
    if not isinstance(storico, dict):
        storico = {}
    last_quotes_update = str(
        payload.get("last_quotes_update")
        or payload.get("_last_quotes_update")
        or ""
    )

    cat_tickers = sorted({
        str(s.get("ticker", "")).strip()
        for s in cat_strumenti
        if isinstance(s, dict) and str(s.get("ticker", "")).strip()
    })
    signature_payload: dict[str, Any] = {
        "category": category,
        "instruments": _normalized_instrument_signature_payload(cat_strumenti),
        "history_span_by_ticker": history_span_by_ticker(storico, cat_tickers),
    }
    cat_hash = _safe_hash(signature_payload)
    return data_signature(
        n_instruments=len(cat_strumenti),
        n_operations=0,
        last_quotes_update=last_quotes_update,
        portfolio_data_hash=cat_hash,
        app_version=str(app_version),
        schema_version=str(schema_version),
    )


def build_ticker_data_signature(
    data: dict[str, Any] | None,
    ticker: str,
    *,
    app_version: str,
    schema_version: str,
) -> str:
    """
    Firma per figure che dipendono solo da un singolo strumento.

    Isola il subset di strumenti con ticker==ticker così che un aggiornamento
    quotazioni su SWDA non invalidi le figure BTP/VWCE e viceversa.
    history_span (scoped al solo ticker) e' l'unico meccanismo di rilevamento
    cambi storico: cattura sia il caso "nuovo giorno di quotazione per questo
    ticker" sia il caso backfill (una data piu' vecchia gia' esistente
    riceve ora un valore per questo ticker), senza dipendere da contatori
    globali che invaliderebbero la firma anche per ticker non toccati dal
    refresh.
    """
    payload = data if isinstance(data, dict) else {}
    strumenti = payload.get("strumenti", [])
    if not isinstance(strumenti, list):
        strumenti = []

    ticker_str = str(ticker).strip()
    ticker_strumenti = [
        s for s in strumenti
        if isinstance(s, dict) and str(s.get("ticker", "")).strip() == ticker_str
    ]

    storico = payload.get("storico_prezzi", {})
    if not isinstance(storico, dict):
        storico = {}
    last_quotes_update = str(
        payload.get("last_quotes_update")
        or payload.get("_last_quotes_update")
        or ""
    )

    signature_payload: dict[str, Any] = {
        "ticker": ticker_str,
        "instrument": _normalized_instrument_signature_payload(ticker_strumenti),
        "history_span": history_span_by_ticker(storico, [ticker_str]).get(ticker_str, {"n_dates": 0, "earliest": ""}),
    }
    ticker_hash = _safe_hash(signature_payload)
    return data_signature(
        n_instruments=len(ticker_strumenti),
        n_operations=0,
        last_quotes_update=last_quotes_update,
        portfolio_data_hash=ticker_hash,
        app_version=str(app_version),
        schema_version=str(schema_version),
    )


def build_historical_data_signature(
    data: dict[str, Any] | None,
    *,
    app_version: str,
    schema_version: str,
    include_operations: bool = False,
) -> str:
    """
    Firma per figure che dipendono solo dallo storico prezzi (end-of-day).

    Non include i prezzi live (strumenti.prezzo): stabile durante refresh
    intraday. Cambia solo quando arrivano nuovi dati storici, vengono
    aggiunti/rimossi strumenti, o (con include_operations=True) cambiano
    le operazioni.

    Usare per figure basate su dh_hist (build_hist_df) o dh_flow
    (build_expanded_price_frame) che non mostrano prezzi attuali.
    """
    payload = data if isinstance(data, dict) else {}
    strumenti = payload.get("strumenti", [])
    if not isinstance(strumenti, list):
        strumenti = []

    # Structural info only: ticker, tipo, isin — no current prices
    instruments_structural = sorted(
        [
            {
                "isin": str(s.get("isin", "")).strip(),
                "ticker": str(s.get("ticker", "")).strip(),
                "tipo": str(s.get("tipo", "")).strip(),
            }
            for s in strumenti
            if isinstance(s, dict)
        ],
        key=lambda r: (r["ticker"], r["isin"], r["tipo"]),
    )

    storico = payload.get("storico_prezzi", {})
    if not isinstance(storico, dict):
        storico = {}
    latest_history_date = max(storico.keys()) if storico else ""
    last_quotes_update = str(
        payload.get("last_quotes_update")
        or payload.get("_last_quotes_update")
        or ""
    )

    hist_tickers = sorted({row["ticker"] for row in instruments_structural if row["ticker"]})
    signature_payload: dict[str, Any] = {
        "instruments_structural": instruments_structural,
        "n_history_dates": len(storico),
        "latest_history_date": latest_history_date,
        "history_span_by_ticker": history_span_by_ticker(storico, hist_tickers),
    }
    if include_operations:
        operazioni = payload.get("operazioni", [])
        if not isinstance(operazioni, list):
            operazioni = []
        signature_payload["operations"] = _normalized_operation_signature_payload(operazioni)
        n_operations = len(operazioni)
    else:
        n_operations = 0

    hist_hash = _safe_hash(signature_payload)
    return data_signature(
        n_instruments=len(strumenti),
        n_operations=n_operations,
        last_quotes_update=last_quotes_update,
        portfolio_data_hash=hist_hash,
        app_version=str(app_version),
        schema_version=str(schema_version),
    )


def build_portfolio_data_signature(
    data: dict[str, Any] | None,
    *,
    app_version: str,
    schema_version: str,
    include_benchmark_data: bool = False,
) -> str:
    """
    Build a stable data signature from the portfolio payload.

    This helper avoids hashing the full in-memory state, which is expensive and
    can become unstable when runtime-only fields are added. It focuses on the
    pieces that materially change rendered figures.
    """
    return build_cashflow_data_signature(
        data,
        app_version=str(app_version),
        schema_version=str(schema_version),
        include_benchmark_data=include_benchmark_data,
    )


def build_portfolio_signature_components(
    data: dict[str, Any] | None,
    *,
    include_benchmark_data: bool = False,
) -> dict[str, Any]:
    """
    Restituisce le componenti diagnostiche della firma portfolio.

    Serve per capire *quale* blocco dati cambia tra due run, senza dover
    confrontare solo l'hash finale opaco.
    """
    signature_payload, strumenti, operazioni, storico, last_quotes_update = _base_market_signature_payload(
        data,
        include_benchmark_data=include_benchmark_data,
    )
    components: dict[str, Any] = {
        "instruments_hash": _safe_hash(signature_payload.get("instruments", [])),
        "operations_hash": _safe_hash(_normalized_operation_signature_payload(operazioni)),
        "history_dates_count": int(signature_payload.get("n_history_dates", 0) or 0),
        "latest_history_date": str(signature_payload.get("latest_history_date", "") or ""),
        "last_quotes_update": str(last_quotes_update or ""),
        "instrument_count": len(strumenti),
        "operation_count": len(operazioni),
    }
    if include_benchmark_data:
        components["benchmark_points_hash"] = _safe_hash(signature_payload.get("benchmark_points", {}))
    return components


def theme_signature(theme_context: dict[str, Any] | SimpleNamespace) -> str:
    """
    Hash visual theme to detect when colors, fonts, or dark mode changes.

    Extracts relevant theme properties and creates a deterministic signature.
    Handles both dictionary and SimpleNamespace theme contexts, plus any object
    with __dict__ attribute (like Streamlit's ThemeConfig).

    Args:
        theme_context: Theme configuration (dict, SimpleNamespace, or ThemeConfig)

    Returns:
        12-character hex string
    """
    if isinstance(theme_context, SimpleNamespace):
        theme_dict = vars(theme_context)
    elif isinstance(theme_context, dict):
        theme_dict = theme_context
    else:
        # Handle ThemeConfig and other objects with __dict__ (e.g., Streamlit's theme config)
        try:
            theme_dict = vars(theme_context)
        except TypeError:
            logger.warning("Cannot extract theme_context attributes for type: %s. Using repr()", type(theme_context).__name__)
            return _safe_hash(theme_context)

    # Extract theme properties relevant to rendering
    relevant_keys = {
        "primaryColor",
        "backgroundColor",
        "secondaryBackgroundColor",
        "textColor",
        "fontFamily",
        "base",
    }

    theme_subset = {k: v for k, v in theme_dict.items() if k in relevant_keys}

    return _safe_hash(theme_subset)


def charts_settings_signature(charts_settings_file_path: str | Path) -> str:
    """
    Hash ui/charts/settings.py content only (not mtime/size).

    Detects when chart configuration file has been modified. Returns consistent
    signature even if file doesn't exist (graceful fallback).

    Only content_hash is included: mtime and size caused false cache invalidations
    when the file was touched by git/IDE without actual content changes.

    Args:
        charts_settings_file_path: Path to ui/charts/settings.py

    Returns:
        12-character hex string
    """
    file_path = Path(charts_settings_file_path)

    if not file_path.exists():
        logger.warning("charts_settings file not found: %s. Using default signature", file_path)
        return _safe_hash({"file_exists": False, "path": str(file_path)})

    try:
        with open(file_path, "rb") as f:
            content_hash = hashlib.sha256(f.read()).hexdigest()

        file_info = {
            "content_hash": content_hash,
            "path": str(file_path),
        }
        return _safe_hash(file_info)
    except Exception as e:
        logger.warning("Failed to compute charts_settings signature: %s. Using fallback", e)
        return _safe_hash({"error": str(e), "path": str(file_path)})


def figure_signature(
    chart_id: str,
    data_sig: str,
    theme_sig: str,
    charts_settings_sig: str,
    page_mode: str = "Rapida",
    extra_params: dict[str, Any] | None = None,
) -> str:
    """
    Combine all signatures into a single cache key signature.

    Creates a deterministic signature from data, theme, and configuration
    signatures plus optional extra parameters. This is the primary signature
    used to determine if a figure needs regeneration.

    Args:
        chart_id: Identifier for the chart/figure
        data_sig: Signature from data_signature()
        theme_sig: Signature from theme_signature()
        charts_settings_sig: Signature from charts_settings_signature()
        page_mode: Page mode identifier (default "Rapida")
        extra_params: Additional parameters affecting rendering

    Returns:
        12-character hex string
    """
    def _normalize_page_mode(value: str) -> str:
        mode = str(value or "").strip().lower()
        if mode == "report":
            return "report"
        return "interactive"

    def _normalize_extra_params(params: dict[str, Any] | None) -> dict[str, Any] | None:
        if not params:
            return None

        normalized: dict[str, Any] = {}
        for key, value in sorted(params.items(), key=lambda item: str(item[0])):
            key_str = str(key)
            if value in (None, ""):
                continue

            # Operational bust tokens should not fragment the figure cache.
            if key_str == "cache_bust":
                continue

            # These counts are already represented by data_sig and only create
            # redundant figure variants on disk.
            if key_str in {"items", "count"}:
                continue

            # Order does not matter for these comparison charts.
            if key_str in {"tickers", "categories"}:
                if isinstance(value, str):
                    tokens = [part.strip() for part in value.split("|") if part.strip()]
                    normalized[key_str] = "|".join(sorted(tokens))
                    continue
                if isinstance(value, (list, tuple, set)):
                    normalized[key_str] = sorted(str(part).strip() for part in value if str(part).strip())
                    continue

            normalized[key_str] = value

        return normalized or None

    params = {
        "chart_id": chart_id,
        "data_sig": data_sig,
        "theme_sig": theme_sig,
        "charts_settings_sig": charts_settings_sig,
        "page_mode": _normalize_page_mode(page_mode),
    }

    normalized_extra = _normalize_extra_params(extra_params)
    if normalized_extra:
        params["extra_params"] = normalized_extra

    return _safe_hash(params)


def resolve_analysis_render_sig(current_sig: str, entry: Any) -> str:
    """
    Restituisce la firma stabile da usare come chiave per la cache di render
    delle figure derivate da un'analisi congelata (Benchmark, Accumuli).

    Usa la firma memorizzata nell'entry (da quando l'analisi fu costruita)
    invece della firma corrente del portfolio. Così un aggiornamento prezzi
    non invalida le figure di un'analisi che non è stata rigenerata.

    Restituisce current_sig come fallback quando entry è None, non è un dict,
    o non contiene una firma valida.
    """
    if isinstance(entry, dict):
        stored = entry.get("signature")
        if stored:
            return str(stored)
    return current_sig


def cache_key(chart_id: str, figure_sig: str) -> str:
    """
    Generate deterministic cache filename from chart ID and figure signature.

    Sanitizes chart_id to contain only alphanumeric characters, underscores,
    and hyphens. Returns filename in format: {chart_id}_{figure_sig}.json

    Args:
        chart_id: Identifier for the chart/figure
        figure_sig: Signature from figure_signature()

    Returns:
        Sanitized filename string
    """
    # Sanitize chart_id: keep only alphanumeric, underscore, hyphen
    sanitized_id = re.sub(r"[^a-zA-Z0-9_-]", "_", chart_id)

    return f"{sanitized_id}_{figure_sig}.json"
