"""
core/diagnostics.py — diagnostica leggera per cache, runtime e prestazioni.

Il modulo e' intenzionalmente read-only: raccoglie stati, dimensioni e segnali
operativi senza modificare dati, cache o session_state.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except Exception:
        return default


def _mb(num_bytes: Any) -> float:
    return round(_safe_float(num_bytes) / (1024 * 1024), 2)


def _fmt_dt(value: Any) -> str:
    if not value:
        return "n/d"
    text = str(value)
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(text[:19], fmt).strftime("%d/%m/%Y %H:%M")
        except Exception:
            continue
    return text




def make_arrow_safe_dataframe(rows: Any) -> pd.DataFrame:
    """Normalizza una tabella diagnostica per il rendering Streamlit/Arrow.

    Le diagnostiche usano spesso colonne generiche come ``Valore`` o
    ``Indicatore`` che possono mescolare interi, stringhe, date e valori nulli.
    PyArrow, usato internamente da ``st.dataframe``, puo' provare a inferire un
    tipo numerico unico e fallire quando trova una stringa. Questa funzione
    lavora solo sulla copia destinata alla vista e non modifica i dati reali.
    """
    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if df.empty:
        return df.copy()

    safe = df.copy()
    for col in safe.columns:
        series = safe[col]
        # Le colonne object sono quelle piu' esposte a inferenze miste Arrow.
        # Convertiamo anche le colonne category per evitare categorie non stringa.
        if str(series.dtype) in {"object", "category"}:
            safe[col] = series.map(lambda value: "—" if pd.isna(value) else str(value))
    return safe

def safe_file_info(path: str | Path) -> dict[str, Any]:
    """Restituisce presenza, dimensione e timestamp di un file senza sollevare eccezioni."""
    p = Path(path)
    try:
        if not p.exists() or not p.is_file():
            return {"path": str(p), "exists": False, "size_bytes": 0, "size_mb": 0.0, "modified": "n/d"}
        stat = p.stat()
        return {
            "path": str(p),
            "exists": True,
            "size_bytes": int(stat.st_size),
            "size_mb": _mb(stat.st_size),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M"),
        }
    except Exception:
        return {"path": str(p), "exists": False, "size_bytes": 0, "size_mb": 0.0, "modified": "n/d"}


def build_cache_health_rows(
    *,
    cache_settings: dict[str, Any] | None,
    figure_stats: dict[str, Any] | None,
    cache_tree: dict[str, Any] | None,
    prewarm_status: dict[str, Any] | None,
    action_log: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Sintesi operativa della cache figure e del pre-render."""
    cache_settings = cache_settings or {}
    figure_stats = figure_stats or {}
    cache_tree = cache_tree or {}
    prewarm_status = prewarm_status or {}
    action_log = action_log or {}

    enabled = bool(cache_settings.get("enabled", True))
    strategy = str(cache_settings.get("strategy", "hybrid"))
    total_size_mb = _safe_float(figure_stats.get("total_size_mb"))
    limit_mb = _safe_float(cache_settings.get("max_cache_size_mb"), 500.0)
    usage = (total_size_mb / limit_mb * 100.0) if limit_mb > 0 else 0.0
    num_files = _safe_int(figure_stats.get("num_files"))
    legacy_files = _safe_int(figure_stats.get("legacy_double_json_files")) + _safe_int(figure_stats.get("pickle_files"))
    tree_size_mb = _mb(cache_tree.get("total_size_bytes", 0))

    rows = [
        {
            "Area": "Cache figure",
            "Stato": "Attiva" if enabled else "Disattiva",
            "Indicatore": strategy,
            "Lettura": "Strategia in uso per il riuso dei grafici.",
        },
        {
            "Area": "Spazio cache",
            "Stato": f"{total_size_mb:.2f} MB",
            "Indicatore": f"{usage:.0f}% del limite",
            "Lettura": "Valore sotto controllo" if usage < 80 else "Valutare ottimizzazione o aumento limite.",
        },
        {
            "Area": "File cache",
            "Stato": str(num_files),
            "Indicatore": f"legacy={legacy_files}",
            "Lettura": "Ottimizzazione consigliata" if legacy_files else "Nessun residuo legacy rilevato.",
        },
        {
            "Area": "Data/cache complessiva",
            "Stato": f"{tree_size_mb:.2f} MB",
            "Indicatore": f"{_safe_int(cache_tree.get('total_files'))} file",
            "Lettura": "Inventario fisico della cartella data/cache.",
        },
        {
            "Area": "Pre-warming",
            "Stato": "In esecuzione" if bool(prewarm_status.get("running")) else "Fermo",
            "Indicatore": f"ultimo={prewarm_status.get('last_run', 'Mai')}",
            "Lettura": f"Prossima run stimata tra {prewarm_status.get('next_run_in_minutes', 0)} minuti.",
        },
        {
            "Area": "Ultime azioni",
            "Stato": str(action_log.get("optimized", "mai")),
            "Indicatore": f"clear={action_log.get('cleared', 'mai')}",
            "Lettura": f"prewarm={action_log.get('prewarm_started', 'mai')}",
        },
    ]
    return rows


def build_cache_chart_rows(figure_stats: dict[str, Any] | None, *, limit: int = 12) -> list[dict[str, Any]]:
    """Elenco dei chart_id piu' presenti nel manifest cache."""
    chart_counts = dict((figure_stats or {}).get("chart_counts", {}) or {})
    rows: list[dict[str, Any]] = []
    for chart_id, count in sorted(chart_counts.items(), key=lambda item: int(item[1] or 0), reverse=True)[: max(1, int(limit))]:
        rows.append({"Chart ID": str(chart_id), "File": int(count or 0)})
    return rows


def build_render_event_rows(events: list[dict[str, Any]] | None, *, limit: int = 12, min_seconds: float = 0.0) -> list[dict[str, Any]]:
    """Sintesi delle sotto-fasi di render piu' lente, gia' registrate dal profiler."""
    rows: list[dict[str, Any]] = []
    for event in events or []:
        elapsed = _safe_float(event.get("elapsed"))
        if elapsed < float(min_seconds or 0.0):
            continue
        rows.append(
            {
                "Pagina": str(event.get("page") or "n/d"),
                "Fase": str(event.get("step") or "n/d"),
                "Tempo s": round(elapsed, 3),
                "Stato": str(event.get("status") or "OK"),
                "Dettaglio": str(event.get("detail") or ""),
            }
        )
    return sorted(rows, key=lambda item: float(item.get("Tempo s", 0.0) or 0.0), reverse=True)[: max(1, int(limit))]


def build_session_state_rows(session_state: Any) -> list[dict[str, Any]]:
    """Sintesi non invasiva dello stato Streamlit corrente."""
    try:
        keys = list(session_state.keys())
    except Exception:
        keys = []
    fig_keys = [key for key in keys if str(key).startswith("_fig_cache_")]
    internal_keys = [key for key in keys if str(key).startswith("_")]
    return [
        {"Voce": "Chiavi session_state", "Valore": len(keys), "Dettaglio": "Totale chiavi attive nella sessione."},
        {"Voce": "Cache figure in sessione", "Valore": len(fig_keys), "Dettaglio": "Figure mantenute nella sola sessione browser."},
        {"Voce": "Chiavi tecniche", "Valore": len(internal_keys), "Dettaglio": "Chiavi interne usate da runtime/cache/test."},
        {"Voce": "Cache bust", "Valore": str(session_state.get("_portfolio_cache_bust", 0) if hasattr(session_state, "get") else 0), "Dettaglio": str(session_state.get("_portfolio_cache_reason", "") if hasattr(session_state, "get") else "")},
    ]


def build_runtime_diagnostic_rows(
    *,
    data: dict[str, Any] | None,
    settings: dict[str, Any] | None,
    log_stats: dict[str, Any] | None,
    snapshots_state: Any = None,
) -> list[dict[str, Any]]:
    """Controlli sintetici per capire se l'ambiente applicativo e' coerente."""
    data = data or {}
    settings = settings or {}
    log_stats = log_stats or {}
    strumenti = data.get("strumenti", []) or []
    storico = data.get("storico_prezzi", {}) or {}
    snapshots = []
    try:
        snapshots = list(getattr(snapshots_state, "snapshots", []) or [])
    except Exception:
        snapshots = []

    return [
        {
            "Ambito": "Dati",
            "Stato": "OK" if strumenti else "Warning",
            "Indicatore": f"strumenti={len(strumenti)}",
            "Lettura": "Anagrafica disponibile." if strumenti else "Anagrafica vuota o non caricata.",
        },
        {
            "Ambito": "Prezzi",
            "Stato": "OK" if storico else "Warning",
            "Indicatore": f"date={len(storico)}",
            "Lettura": "Storico prezzi disponibile." if storico else "Storico prezzi assente o non caricato.",
        },
        {
            "Ambito": "Snapshot",
            "Stato": "OK" if snapshots else "Info",
            "Indicatore": f"snapshot={len(snapshots)}",
            "Lettura": "Snapshot disponibili per confronto." if snapshots else "Nessuno snapshot disponibile.",
        },
        {
            "Ambito": "Settings",
            "Stato": "OK" if settings else "Warning",
            "Indicatore": f"chiavi={len(settings)}",
            "Lettura": "Configurazione caricata." if settings else "Configurazione non disponibile.",
        },
        {
            "Ambito": "Log",
            "Stato": "OK" if bool(log_stats.get("exists")) else "Info",
            "Indicatore": f"{_mb(log_stats.get('size_bytes', 0)):.2f} MB",
            "Lettura": "Log applicativo presente." if bool(log_stats.get("exists")) else "Log non ancora generato.",
        },
    ]


def build_diagnostic_recommendations(
    *,
    cache_settings: dict[str, Any] | None,
    figure_stats: dict[str, Any] | None,
    cache_tree: dict[str, Any] | None,
    render_rows: list[dict[str, Any]] | None,
) -> list[str]:
    """Produce suggerimenti brevi e non vincolanti sulla base dei segnali tecnici."""
    cache_settings = cache_settings or {}
    figure_stats = figure_stats or {}
    cache_tree = cache_tree or {}
    render_rows = render_rows or []
    suggestions: list[str] = []

    total_size_mb = _safe_float(figure_stats.get("total_size_mb"))
    limit_mb = _safe_float(cache_settings.get("max_cache_size_mb"), 500.0)
    if limit_mb > 0 and total_size_mb / limit_mb >= 0.8:
        suggestions.append("La cache figure e' vicina al limite configurato: valuta Ottimizza cache o aumenta il limite MB.")

    legacy_files = _safe_int(figure_stats.get("legacy_double_json_files")) + _safe_int(figure_stats.get("pickle_files"))
    if legacy_files:
        suggestions.append("Sono presenti file cache legacy: usa Ottimizza cache per migrare/ripulire i residui.")

    if _safe_int(cache_tree.get("total_files")) > 2000:
        suggestions.append("La cartella data/cache contiene molti file: una manutenzione periodica puo' ridurre i tempi di scansione.")

    slow = [row for row in render_rows if _safe_float(row.get("Tempo s")) >= 1.0]
    if slow:
        suggestions.append("Sono state rilevate sotto-fasi di render superiori a 1 secondo: controlla il riepilogo performance prima di nuovi refactor.")

    if not suggestions:
        suggestions.append("Nessuna criticita' tecnica evidente dai segnali disponibili in questa sessione.")
    return suggestions
