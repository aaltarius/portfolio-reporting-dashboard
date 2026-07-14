"""Scheda Cruscotti > Benchmark.

Rende visibile il flusso di confronto con il benchmark senza modificare calcoli,
cache o impostazioni.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from types import SimpleNamespace
from typing import Any

import pandas as pd
import streamlit as st

from core.cache_signatures import build_portfolio_data_signature, resolve_analysis_render_sig
from core.render_profiler import profile_step
from core.analytics_payload_cache import load_entry as load_persistent_analytics_entry, store_entry as store_persistent_analytics_entry
from core.services.benchmark import build_benchmark_transparency_payload, benchmark_explanation
from ui.charts.benchmark import build_instrument_benchmark_scatter, build_portfolio_benchmark_comparison_chart, build_normalized_performance_chart, get_all_historical_tickers, resolve_period_start_date
from ui.components import kpi_card, legend_block, render_section_title, render_styled_table, vertical_gap
from ui.formatting import fmt_date_only_it, fmt_eur_it, fmt_num_it, fmt_pct_it
from ui.theme import P, macro_color


BENCHMARK_PAYLOAD_CACHE_KEY = "_cruscotti_benchmark_payload_cache_v1"
BENCHMARK_RENDER_CACHE_KEY = "_cruscotti_benchmark_render_cache_v2"


def _prune_cache_items(items: dict[str, Any], max_items: int = 16) -> None:
    """Mantiene contenuta la cache sessione delle figure benchmark."""
    if len(items) <= max_items:
        return
    for old_key in list(items.keys())[: max(0, len(items) - max_items)]:
        items.pop(old_key, None)


def _cached_render_value(key: str, builder, *, label: str, count: int | None = None):
    """Cache sessione per figure Benchmark già costruite da payload congelato."""
    cache = st.session_state.setdefault(BENCHMARK_RENDER_CACHE_KEY, {})
    if not isinstance(cache, dict):
        cache = {}
        st.session_state[BENCHMARK_RENDER_CACHE_KEY] = cache
    if key in cache:
        with profile_step("Cruscotti/Benchmark", f"cache hit figura {label}", count=count):
            return cache[key]
    with profile_step("Cruscotti/Benchmark", f"build figura {label}", count=count):
        value = builder()
    cache[key] = value
    _prune_cache_items(cache)
    return value


def _small_signature_part(value: Any) -> Any:
    """Riduce oggetti voluminosi a una firma leggera e serializzabile."""
    if isinstance(value, pd.DataFrame):
        if value.empty:
            return {"rows": 0, "cols": list(value.columns)}
        return {
            "rows": int(len(value)),
            "cols": list(value.columns),
            "first_index": str(value.index[0]),
            "last_index": str(value.index[-1]),
        }
    if isinstance(value, dict):
        return {str(k): _small_signature_part(v) for k, v in value.items() if k in {
            "benchmarking",
            "portfolio_benchmark_default",
            "settings_version",
        }}
    if isinstance(value, (list, tuple)):
        if not value:
            return {"len": 0}
        return {"len": len(value), "first": str(value[0])[:80], "last": str(value[-1])[:80]}
    return value

def _safe_count(value: Any) -> int:
    """Conta liste, tuple, dict, DataFrame e Series senza valutarli in booleano."""
    if value is None:
        return 0
    if isinstance(value, (pd.DataFrame, pd.Series)):
        return int(len(value))
    try:
        return int(len(value))
    except Exception:
        return 0


def _or_empty_sequence(value: Any) -> Any:
    """Ritorna [] solo per None, lasciando intatti DataFrame/Series/list già valorizzati."""
    return [] if value is None else value


def _benchmark_payload_signature(ctx: SimpleNamespace, settings: dict[str, Any], summary_payload: dict[str, Any] | None) -> str:
    """Firma logica del payload benchmark, usata solo per capire se la cache è fresca."""
    summary_payload = summary_payload if isinstance(summary_payload, dict) else {}
    history = _or_empty_sequence(summary_payload.get("summary_history"))
    bench_history = _or_empty_sequence(summary_payload.get("benchmark_history"))
    material = {
        "data_sig": build_portfolio_data_signature(
            getattr(ctx, "data", {}),
            app_version=str(getattr(ctx, "app_version", "n/d")),
            schema_version=str(getattr(ctx, "schema_version", "n/d")),
        ),
        "benchmark_settings": _small_signature_part(settings),
        "da": _small_signature_part(getattr(ctx, "da", pd.DataFrame())),
        "summary": {
            "twr": summary_payload.get("twr"),
            "cagr": summary_payload.get("cagr"),
            "benchmark_return": summary_payload.get("benchmark_return"),
            "tracking_error": summary_payload.get("tracking_error"),
            "information_ratio": summary_payload.get("information_ratio"),
            "summary_history": _small_signature_part(history),
            "benchmark_history": _small_signature_part(bench_history),
        },
    }
    raw = json.dumps(material, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _get_benchmark_payload_cache(signature: str) -> tuple[dict[str, Any] | None, bool]:
    """Restituisce (entry, stale) usando prima sessione e poi cache persistente."""
    cache = st.session_state.setdefault(BENCHMARK_PAYLOAD_CACHE_KEY, {"items": {}, "latest_key": ""})
    if not isinstance(cache, dict):
        cache = {"items": {}, "latest_key": ""}
        st.session_state[BENCHMARK_PAYLOAD_CACHE_KEY] = cache
    items = cache.setdefault("items", {})
    if not isinstance(items, dict):
        items = {}
        cache["items"] = items
    if signature in items and isinstance(items[signature], dict):
        items[signature].setdefault("cache_source", "session")
        return items[signature], False

    disk_entry, disk_stale, disk_source = load_persistent_analytics_entry("benchmark", signature)
    if isinstance(disk_entry, dict):
        disk_signature = str(disk_entry.get("signature") or signature)
        disk_entry.setdefault("cache_source", disk_source)
        items[disk_signature] = disk_entry
        cache["latest_key"] = disk_signature
        return disk_entry, disk_stale

    latest_key = str(cache.get("latest_key") or "")
    latest = items.get(latest_key)
    if isinstance(latest, dict):
        latest.setdefault("cache_source", "session_latest")
        return latest, True
    return None, False


def _store_benchmark_payload_cache(signature: str, payload: dict[str, Any]) -> dict[str, Any]:
    cache = st.session_state.setdefault(BENCHMARK_PAYLOAD_CACHE_KEY, {"items": {}, "latest_key": ""})
    items = cache.setdefault("items", {})
    entry = {
        "signature": signature,
        "created_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "payload": payload,
        "cache_source": "session+disk",
    }
    items[signature] = entry
    cache["latest_key"] = signature
    store_persistent_analytics_entry("benchmark", signature, entry, max_entries=6)
    # Mantiene solo poche analisi in memoria sessione per evitare crescita inutile.
    if len(items) > 4:
        for old_key in list(items.keys())[:-4]:
            items.pop(old_key, None)
    return entry


def _render_benchmark_status_text(slot, entry: dict[str, Any] | None, stale: bool) -> None:
    """Testo di stato (info/warning/caption) nel suo slot dedicato.

    Va richiamato di nuovo con l'entry aggiornata subito dopo un eventuale
    refresh, nello stesso rerun: altrimenti il messaggio mostra ancora la data
    di prima del click anche quando l'analisi è già stata rigenerata, dando
    l'impressione che il primo click non abbia fatto nulla.
    """
    with slot.container():
        if entry is None:
            st.info(
                "Nessuna analisi benchmark disponibile nella cache persistente. "
                "La prima analisi va generata una sola volta; poi verrà recuperata anche dopo il riavvio dell'app."
            )
            return
        created_at = str(entry.get("created_at") or "n/d")
        if stale:
            st.warning(
                f"Sto mostrando l'ultima analisi benchmark disponibile in cache, generata il {created_at}. "
                "I dati del portafoglio sono cambiati: rigenera solo se vuoi aggiornare questa lettura."
            )
            return
        source = str(entry.get("cache_source") or "cache")
        st.caption(f"Analisi benchmark in cache — generata il {created_at} — origine: {source}. Non viene rigenerata automaticamente nei rerun.")


def _render_benchmark_freeze_header(entry: dict[str, Any] | None, stale: bool, signature: str):
    """Header operativo: non rigenera il benchmark se l'utente non lo chiede.

    Ritorna (refresh_requested, status_slot). Il chiamante deve richiamare
    _render_benchmark_status_text(status_slot, ...) con l'entry aggiornata dopo
    un eventuale refresh, per evitare che il messaggio resti di un giro
    indietro rispetto ai dati che descrive.
    """
    render_section_title(
        "Benchmark",
        comment="Analisi congelata: i calcoli benchmark vengono rigenerati solo su richiesta, per non appesantire i rerun dei Cruscotti.",
        icon="analysis",
    )
    status_slot = st.empty()
    _render_benchmark_status_text(status_slot, entry, stale)

    if entry is None:
        return st.button("Analizza benchmark", type="primary", key=f"benchmark_analyze_{signature}"), status_slot
    if stale:
        return st.button("Aggiorna analisi benchmark", type="primary", key=f"benchmark_refresh_{signature}"), status_slot
    return st.button("Rigenera analisi benchmark", type="secondary", key=f"benchmark_regen_{signature}"), status_slot


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _fmt_pct(value: Any, signed: bool = True) -> str:
    v = _safe_float(value)
    return fmt_pct_it(v, 2, signed=signed) if v is not None else "n/d"


def _fmt_num(value: Any) -> str:
    v = _safe_float(value)
    return fmt_num_it(v, 2) if v is not None else "n/d"


def _excess_note(value: Any) -> str:
    v = _safe_float(value)
    if v is None:
        return "Confronto non disponibile"
    if v >= 0.03:
        return "Sopra benchmark in modo marcato"
    if v >= 0.0:
        return "Sopra benchmark"
    if v >= -0.03:
        return "Leggermente sotto benchmark"
    return "Sotto benchmark in modo marcato"


def _tracking_note(value: Any) -> str:
    v = _safe_float(value)
    if v is None:
        return "Non calcolabile"
    if v < 0.05:
        return "Molto vicino al benchmark"
    if v < 0.15:
        return "Scostamento intermedio"
    return "Scostamento elevato"


def _ir_note(value: Any) -> str:
    v = _safe_float(value)
    if v is None:
        return "Non calcolabile"
    if v >= 0.50:
        return "Extra-rendimento robusto"
    if v >= 0.0:
        return "Extra-rendimento positivo"
    return "Valore aggiunto negativo"


def _drawdown_note(port_dd: Any, bench_dd: Any) -> str:
    p = _safe_float(port_dd)
    b = _safe_float(bench_dd)
    if p is None or b is None:
        return "Confronto non disponibile"
    if p > b:
        return "Drawdown meno profondo del benchmark"
    if p < b:
        return "Drawdown più profondo del benchmark"
    return "Drawdown allineato"


def _render_component_table(components: list[dict[str, Any]]) -> None:
    with profile_step("Cruscotti/Benchmark", "component table: header/input", count=len(components or [])):
        st.markdown("#### Componenti effettive")
        if not components:
            st.info("Nessuna componente benchmark disponibile.")
            return
    with profile_step("Cruscotti/Benchmark", "component table: build dataframe", count=len(components or [])):
        df = pd.DataFrame(components)
        display = pd.DataFrame({
        "Componente": df.get("label", pd.Series(dtype=str)).astype(str),
        "Ticker": df.get("ticker", pd.Series(dtype=str)).astype(str),
        "Peso": pd.to_numeric(df.get("weight"), errors="coerce"),
        "Punti cache": pd.to_numeric(df.get("points"), errors="coerce").fillna(0).astype(int),
        "Prima data": df.get("first_date", pd.Series(dtype=str)).astype(str),
        "Ultima data": df.get("last_date", pd.Series(dtype=str)).astype(str),
        "Stato": df.get("source", pd.Series(dtype=str)).astype(str),
    })
    with profile_step("Cruscotti/Benchmark", "component table: build styler", count=len(display)):
        styled = (
            display.style
        .format({
            "Peso": lambda v: fmt_pct_it(v, 1, signed=False),
            "Punti cache": lambda v: fmt_num_it(v, 0),
        })
        .set_properties(subset=["Peso", "Punti cache"], **{"text-align": "right", "font-variant-numeric": "tabular-nums"})
        .set_properties(subset=["Stato"], **{"text-align": "center", "font-weight": "750"})
        .set_table_styles([
            {"selector": "th", "props": [("font-weight", "700"), ("white-space", "nowrap")]},
            {"selector": "td", "props": [("white-space", "nowrap")]},
        ], overwrite=False)
    )
    with profile_step("Cruscotti/Benchmark", "component table: render dataframe", count=len(display)):
        render_styled_table(
            styled,
        height=min(240, 72 + len(display) * 36),
        column_config={
            "Componente": st.column_config.TextColumn("Componente", width=190),
            "Ticker": st.column_config.TextColumn("Ticker", width=88),
            "Peso": st.column_config.NumberColumn("Peso", width=74),
            "Punti cache": st.column_config.NumberColumn("Punti", width=72),
            "Prima data": st.column_config.TextColumn("Da", width=92),
            "Ultima data": st.column_config.TextColumn("A", width=92),
            "Stato": st.column_config.TextColumn("Stato", width=78),
        },
    )


def _render_benchmark_kpis(metrics: dict[str, Any]) -> None:
    items = [
        ("Portafoglio", _fmt_pct(metrics.get("portfolio_return")), "Rendimento TWR/proxy", P["blue"], P["green"] if (_safe_float(metrics.get("portfolio_return"), 0.0) or 0.0) >= 0 else P["red"]),
        ("Benchmark", _fmt_pct(metrics.get("benchmark_return")), "Rendimento riferimento", P["orange"], P["green"] if (_safe_float(metrics.get("benchmark_return"), 0.0) or 0.0) >= 0 else P["red"]),
        ("Extra-rendimento", _fmt_pct(metrics.get("excess_return")), _excess_note(metrics.get("excess_return")), P["green"], P["green"] if (_safe_float(metrics.get("excess_return"), 0.0) or 0.0) >= 0 else P["red"]),
        ("CAGR portafoglio", _fmt_pct(metrics.get("portfolio_cagr")), "Rendimento annualizzato", P["blue"], None),
        ("CAGR benchmark", _fmt_pct(metrics.get("benchmark_cagr")), "Riferimento annualizzato", P["orange"], None),
        ("Tracking error", _fmt_pct(metrics.get("tracking_error"), signed=False), _tracking_note(metrics.get("tracking_error")), P["orange"], None),
        ("Information ratio", _fmt_num(metrics.get("information_ratio")), _ir_note(metrics.get("information_ratio")), P["blue"], P["green"] if (_safe_float(metrics.get("information_ratio"), 0.0) or 0.0) >= 0 else P["red"]),
        ("Max drawdown", _fmt_pct(metrics.get("portfolio_max_drawdown")), _drawdown_note(metrics.get("portfolio_max_drawdown"), metrics.get("benchmark_max_drawdown")), P["red"], None),
    ]
    for chunk in (items[:4], items[4:]):
        cols = st.columns(4)
        for col, (label, value, subtitle, accent, value_color) in zip(cols, chunk):
            with col:
                kpi_card(label, value, subtitle, accent=accent, value_color=value_color)
        vertical_gap("xs")




def _compat_color(label: str) -> str:
    value = str(label or "")
    if value == "Alta":
        return P["green"]
    if value == "Media":
        return P["blue"]
    if value == "Bassa":
        return P["orange"]
    if value in {"Senza benchmark", "Da verificare", "Dati insufficienti"}:
        return P["red"] if value != "Dati insufficienti" else P["muted"]
    return P["muted"]


def _status_color(label: str) -> str:
    value = str(label or "")
    if value == "Sovraperforma":
        return P["green"]
    if value == "Sottoperforma":
        return P["red"]
    if value == "Allineato":
        return P["blue"]
    if value in {"Da verificare", "Senza benchmark"}:
        return P["orange"]
    return P["muted"]


def _style_instrument_benchmark_table(row: pd.Series) -> list[str]:
    styles = ["" for _ in row.index]
    for idx, col in enumerate(row.index):
        if col in {"Rend. str.", "Rend. bench", "Extra", "Corr.", "Tracking", "Punti"}:
            styles[idx] += "text-align:right !important;font-variant-numeric:tabular-nums;"
        if col in {"Compat.", "Stato"}:
            styles[idx] += "text-align:center !important;font-weight:800;"
        if col == "Cat.":
            styles[idx] += f"color:{macro_color(str(row.get(col) or 'ALTRO'))};font-weight:850;"
        if col == "Extra":
            raw = row.get("Extra")
            if raw is not None and not pd.isna(raw):
                styles[idx] += f"color:{P['green'] if float(raw) >= 0 else P['red']};font-weight:800;"
        if col == "Compat.":
            styles[idx] += f"color:{_compat_color(str(row.get(col) or ''))};"
        if col == "Stato":
            styles[idx] += f"color:{_status_color(str(row.get(col) or ''))};"
    return styles


def _fmt_pct_optional(value: Any, decimals: int = 1, signed: bool = True) -> str:
    v = _safe_float(value)
    return fmt_pct_it(v, decimals, signed=signed) if v is not None else "n/d"


def _fmt_corr(value: Any) -> str:
    v = _safe_float(value)
    return fmt_num_it(v, 2) if v is not None else "n/d"


def _assignment_label(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return "Non assegnato"
    if "ticker" in raw or "manual" in raw or "mappa" in raw:
        return "Mappa diretta"
    if "macro" in raw:
        return "Macro-categoria"
    if "categoria" in raw:
        return "Categoria"
    if "fallback" in raw or "tipo" in raw:
        return "Fallback"
    return str(value or "n/d")


def _render_assignment_explanation() -> None:
    legend_block(
        "Il benchmark dello strumento viene risolto dal registro centrale dell'applicativo: prima regole specifiche per ticker/ISIN, "
        "poi tipo strumento, poi macro-categoria. Lo stesso registro viene usato anche da Quotazioni e dal refresh cache benchmark, "
        "così la label vista nei grafici e la matrice qui sotto parlano finalmente la stessa lingua.",
        variant="bottom",
    )


def _render_instrument_benchmark_matrix(matrix: pd.DataFrame) -> None:
    with profile_step("Cruscotti/Benchmark", "matrix: section title"):
        render_section_title(
        "Abbinamento strumenti / benchmark",
        comment="Matrice operativa per verificare quale benchmark viene associato a ogni strumento, con rendimento relativo e compatibilità sul periodo comune disponibile.",
        icon="quotes",
    )
    with profile_step("Cruscotti/Benchmark", "matrix: assignment explanation"):
        _render_assignment_explanation()
    if matrix is None or matrix.empty:
        st.info("Nessuna matrice strumento/benchmark disponibile.")
        return
    with profile_step("Cruscotti/Benchmark", "matrix: build dataframe", count=len(matrix)):
        df = matrix.copy()
        display = pd.DataFrame({
        "Strumento": df.get("ticker", pd.Series(dtype=str)).astype(str),
        "Cat.": df.get("categoria", pd.Series(dtype=str)).astype(str),
        "Benchmark": df.get("benchmark_label", pd.Series(dtype=str)).astype(str).replace({"": "n/d"}),
        "Ticker": df.get("benchmark_ticker", pd.Series(dtype=str)).astype(str).replace({"": "—"}),
        "Compat.": df.get("compatibility_label", pd.Series(dtype=str)).astype(str),
        "Rend. str.": pd.to_numeric(df.get("instrument_return"), errors="coerce"),
        "Rend. bench": pd.to_numeric(df.get("benchmark_return"), errors="coerce"),
        "Extra": pd.to_numeric(df.get("extra_return"), errors="coerce"),
        "Corr.": pd.to_numeric(df.get("correlation"), errors="coerce"),
        "Tracking": pd.to_numeric(df.get("tracking_error"), errors="coerce"),
        "Punti": pd.to_numeric(df.get("points"), errors="coerce"),
        "Stato": df.get("status", pd.Series(dtype=str)).astype(str),
    })
    display["Stato"] = display["Stato"].replace({
        "Dati insufficienti": "Dati insuff.",
        "Senza benchmark": "No benchmark",
        "Da verificare": "Verificare",
    })
    display["Compat."] = display["Compat."].replace({
        "Dati insufficienti": "Dati insuff.",
        "Senza benchmark": "No bench",
        "Da verificare": "Verificare",
    })

    with profile_step("Cruscotti/Benchmark", "matrix: build styler", count=len(display)):
        styled = (
            display.style
        .format({
            "Rend. str.": lambda v: _fmt_pct_optional(v, 1),
            "Rend. bench": lambda v: _fmt_pct_optional(v, 1),
            "Extra": lambda v: _fmt_pct_optional(v, 1),
            "Corr.": _fmt_corr,
            "Tracking": lambda v: _fmt_pct_optional(v, 1, signed=False),
            "Punti": lambda v: fmt_num_it(v, 0) if _safe_float(v) is not None else "n/d",
        })
        .apply(_style_instrument_benchmark_table, axis=1)
        .set_table_styles([
            {"selector": "table", "props": [("width", "100%"), ("table-layout", "fixed")]},
            {"selector": "th", "props": [("font-weight", "800"), ("white-space", "normal"), ("text-align", "center"), ("font-size", "0.68rem"), ("line-height", "1.05"), ("padding", "0.26rem 0.20rem")]},
            {"selector": "td", "props": [("white-space", "nowrap"), ("vertical-align", "middle"), ("padding", "0.26rem 0.20rem"), ("font-size", "0.70rem"), ("overflow", "hidden"), ("text-overflow", "ellipsis")]},
            {"selector": "td:nth-child(1), th:nth-child(1)", "props": [("width", "9.5%"), ("text-align", "left"), ("font-weight", "850")]},
            {"selector": "td:nth-child(2), th:nth-child(2)", "props": [("width", "5.0%"), ("text-align", "center")]},
            {"selector": "td:nth-child(3), th:nth-child(3)", "props": [("width", "16.0%"), ("text-align", "left")]},
            {"selector": "td:nth-child(4), th:nth-child(4)", "props": [("width", "7.0%"), ("text-align", "center")]},
            {"selector": "td:nth-child(5), th:nth-child(5)", "props": [("width", "8.0%"), ("text-align", "center"), ("font-weight", "800")]},
            {"selector": "td:nth-child(6), th:nth-child(6)", "props": [("width", "7.4%"), ("text-align", "right"), ("font-variant-numeric", "tabular-nums")]},
            {"selector": "td:nth-child(7), th:nth-child(7)", "props": [("width", "7.6%"), ("text-align", "right"), ("font-variant-numeric", "tabular-nums")]},
            {"selector": "td:nth-child(8), th:nth-child(8)", "props": [("width", "7.0%"), ("text-align", "right"), ("font-variant-numeric", "tabular-nums"), ("font-weight", "800")]},
            {"selector": "td:nth-child(9), th:nth-child(9)", "props": [("width", "5.8%"), ("text-align", "right"), ("font-variant-numeric", "tabular-nums")]},
            {"selector": "td:nth-child(10), th:nth-child(10)", "props": [("width", "7.0%"), ("text-align", "right"), ("font-variant-numeric", "tabular-nums")]},
            {"selector": "td:nth-child(11), th:nth-child(11)", "props": [("width", "5.4%"), ("text-align", "right"), ("font-variant-numeric", "tabular-nums")]},
            {"selector": "td:nth-child(12), th:nth-child(12)", "props": [("width", "14.3%"), ("text-align", "center"), ("font-weight", "800")]},
        ], overwrite=False)
    )
    table_height = "content"
    with profile_step("Cruscotti/Benchmark", "matrix: render dataframe", count=len(display)):
        render_styled_table(
            styled,
        height=table_height,
        static=False,
        column_config={
            "Strumento": st.column_config.TextColumn("Strumento", width="small"),
            "Cat.": st.column_config.TextColumn("Cat.", width="small"),
            "Benchmark": st.column_config.TextColumn("Benchmark", width="medium"),
            "Ticker": st.column_config.TextColumn("Ticker", width="small"),
            "Compat.": st.column_config.TextColumn("Compat.", width="small"),
            "Rend. str.": st.column_config.NumberColumn("Rend. str.", width="small"),
            "Rend. bench": st.column_config.NumberColumn("Rend. bench", width="small"),
            "Extra": st.column_config.NumberColumn("Extra", width="small"),
            "Corr.": st.column_config.NumberColumn("Corr.", width="small"),
            "Tracking": st.column_config.NumberColumn("Tracking", width="small"),
            "Punti": st.column_config.NumberColumn("Punti", width="small"),
            "Stato": st.column_config.TextColumn("Stato", width="small"),
        },
    )
    with profile_step("Cruscotti/Benchmark", "matrix: render legend"):
        legend_block(
            "Il confronto è prezzo strumento vs benchmark sul periodo comune disponibile; non simula ancora i tuoi flussi reali di acquisto. "
        "La logica di abbinamento resta governata dal registro centrale benchmark, condiviso con Quotazioni e refresh cache.",
        variant="bottom",
    )

def _format_period(period: dict[str, Any]) -> str:
    start = period.get("start")
    end = period.get("end")
    if not start or not end:
        return "Periodo confronto non disponibile"
    return f"Periodo confronto: {fmt_date_only_it(start)} → {fmt_date_only_it(end)}"


_NORM_PERF_SESSION_KEY = "_benchmark_norm_perf_fig_v2"


def _render_normalized_performance_section(ctx: SimpleNamespace) -> None:
    """Grafico performance normalizzata — sempre visibile, ricostruito solo su richiesta."""
    data = getattr(ctx, "data", {}) or {}
    storico = data.get("storico_prezzi") or {}
    if not storico:
        return

    vertical_gap("sm")
    render_section_title(
        "Performance normalizzata",
        comment="Sovrappone gli strumenti normalizzati a 0% da una data o un'origine comune. Non viene ricalcolato automaticamente nei rerun.",
        icon="analysis",
    )

    all_tickers = get_all_historical_tickers(data)
    if not all_tickers:
        st.info("Nessuno storico prezzi disponibile.")
        return

    options = [
        f"{t['ticker']} {'(In portafoglio)' if t['active'] else '(Fuori portafoglio)'}"
        for t in all_tickers
    ]
    ticker_by_label = {
        f"{t['ticker']} {'(In portafoglio)' if t['active'] else '(Fuori portafoglio)'}": t["ticker"]
        for t in all_tickers
    }
    default_labels = [
        lbl for lbl, tk in ticker_by_label.items()
        if next((t["active"] for t in all_tickers if t["ticker"] == tk), False)
    ]

    sorted_dates = sorted(storico.keys())
    first_date = sorted_dates[0][:10] if sorted_dates else ""
    last_date = sorted_dates[-1][:10] if sorted_dates else ""

    col_sel, col_mode = st.columns([2, 1])
    with col_sel:
        selected_labels = st.multiselect(
            "Strumenti da confrontare",
            options=options,
            default=default_labels,
            key="_norm_perf_ticker_select",
        )
    with col_mode:
        mode = st.radio(
            "Modalità",
            options=["Data comune", "Origini allineate"],
            index=0,
            key="_norm_perf_mode",
            help=(
                "Data comune: tutte le curve partono dalla stessa data di calendario.\n"
                "Origini allineate: ogni strumento parte da Giorno 0 indipendentemente "
                "da quando è entrato in storico — utile per confrontare traiettorie."
            ),
        )

    align_starts = mode == "Origini allineate"

    ctrl_left, ctrl_right = st.columns([3, 1])
    with ctrl_left:
        if not align_starts:
            PERIOD_OPTIONS = ["1M", "3M", "6M", "1A", "3A", "Tutto"]
            period = st.radio(
                "Periodo",
                options=PERIOD_OPTIONS,
                index=3,
                horizontal=True,
                key="_norm_perf_period",
            )
            start_date = resolve_period_start_date(sorted_dates, period)
        else:
            start_date = first_date
    with ctrl_right:
        build_clicked = st.button(
            "Costruisci grafico",
            type="primary",
            key="_norm_perf_build_btn",
            width="stretch",
        )

    cached_entry = st.session_state.get(_NORM_PERF_SESSION_KEY)

    if build_clicked:
        tickers_selected = [ticker_by_label[lbl] for lbl in selected_labels if lbl in ticker_by_label]
        held_set = frozenset(t["ticker"] for t in all_tickers if t["active"])
        fig = build_normalized_performance_chart(
            storico, tickers_selected, start_date, align_starts=align_starts, held_tickers=held_set,
        )
        cached_entry = {"fig": fig, "label": f"da {start_date} a {last_date}" if not align_starts else "origini allineate"}
        st.session_state[_NORM_PERF_SESSION_KEY] = cached_entry

    if cached_entry is not None:
        fig = cached_entry.get("fig") if isinstance(cached_entry, dict) else cached_entry
        label = cached_entry.get("label", "") if isinstance(cached_entry, dict) else ""
        if label:
            st.caption(f"Ultimo grafico costruito: {label}. Modifica i parametri e clicca di nuovo per aggiornare.")
        st.plotly_chart(fig, width="stretch")
    else:
        legend_block(
            "Seleziona gli strumenti, scegli modalità e periodo, poi clicca \"Costruisci grafico\". "
            "Il grafico resta visibile nei rerun successivi senza essere ricalcolato.",
            variant="bottom",
        )


def render_benchmark(ctx: SimpleNamespace, summary_bundle: Any | None = None) -> None:
    """Renderizza la scheda Benchmark senza rigenerare automaticamente i payload pesanti."""
    settings = getattr(ctx, "settings", None)
    if not isinstance(settings, dict):
        settings = getattr(ctx, "data", {}).get("settings", {}) if isinstance(getattr(ctx, "data", {}), dict) else {}
    summary_payload = getattr(summary_bundle, "payload", None) if summary_bundle is not None else None
    if summary_payload is None:
        summary_payload = getattr(ctx, "summary_payload", None)

    with profile_step("Cruscotti/Benchmark", "signature/cache/header"):
        signature = _benchmark_payload_signature(ctx, settings, summary_payload)
        entry, stale = _get_benchmark_payload_cache(signature)
        refresh_requested, status_slot = _render_benchmark_freeze_header(entry, stale, signature)

    if refresh_requested:
        with st.status("Analisi benchmark in corso…", expanded=True) as status:
            st.write("Costruzione confronto portafoglio/benchmark e matrice strumenti/benchmark.")
            with profile_step("Cruscotti/Benchmark", "build transparency payload"):
                payload = build_benchmark_transparency_payload(
                    data=getattr(ctx, "data", {}),
                    settings=settings,
                    da_frame=getattr(ctx, "da", pd.DataFrame()),
                    summary_payload=summary_payload,
                )
            entry = _store_benchmark_payload_cache(signature, payload)
            stale = False
            status.update(label="Analisi benchmark aggiornata", state="complete", expanded=False)
        _render_benchmark_status_text(status_slot, entry, stale)
    elif entry is None:
        legend_block(
            "Questa sezione è intenzionalmente congelata: Benchmark è una lettura pesante e non viene ricalcolata durante i normali rerun di Cruscotti. "
            "Premi “Analizza benchmark” quando vuoi aggiornare grafici, KPI e matrice strumenti/benchmark.",
            variant="bottom",
        )
        return
    else:
        payload = entry.get("payload", {}) if isinstance(entry, dict) else {}
        with profile_step("Cruscotti/Benchmark", "reuse cached transparency payload"):
            pass

    # Usa la firma memorizzata nell'entry (versione dell'analisi) anziché quella
    # corrente del portfolio: così un refresh prezzi non invalida le figure
    # di un'analisi benchmark che non è stata rigenerata.
    render_sig = resolve_analysis_render_sig(signature, entry)

    with profile_step("Cruscotti/Benchmark", "render header KPI e spiegazione"):
        cfg = payload.get("config", {})
        metrics = payload.get("metrics", {})
        availability = payload.get("availability", {})
        top_cols = st.columns([1.4, 1.0, 1.0])
        with top_cols[0]:
            kpi_card("Benchmark attivo", str(cfg.get("label") or "n/d"), str(cfg.get("mode") or ""), accent=P["orange"])
        with top_cols[1]:
            kpi_card("Componenti", fmt_num_it(len(cfg.get("components", [])), 0), "Pesi normalizzati", accent=P["blue"])
        with top_cols[2]:
            last_cache = payload.get("last_cache_date") or "n/d"
            kpi_card("Ultima cache", str(last_cache), f"Punti benchmark: {fmt_num_it(availability.get('benchmark_points'), 0)}", accent=P["green"] if availability.get("has_benchmark") else P["red"])

        legend_block(
            benchmark_explanation(payload) + " " + _format_period(payload.get("period", {})),
            variant="bottom",
        )
        vertical_gap("sm")

    with profile_step("Cruscotti/Benchmark", "layout confronto/componenti"):
        left, right = st.columns([1.65, 1.0], gap="large")
    with left:
        history_count = _safe_count(payload.get("history"))
        comparison_fig = _cached_render_value(
            f"{render_sig}:confronto_benchmark",
            lambda: build_portfolio_benchmark_comparison_chart(payload.get("history")),
            label="confronto benchmark",
            count=history_count,
        )
        with profile_step("Cruscotti/Benchmark", "render confronto benchmark", count=history_count):
            st.plotly_chart(comparison_fig, width="stretch")
    with right:
        with profile_step("Cruscotti/Benchmark", "render componenti benchmark", count=_safe_count(cfg.get("components"))):
            _render_component_table(cfg.get("components", []))

    with profile_step("Cruscotti/Benchmark", "render KPI confronto"):
        vertical_gap("sm")
        render_section_title("KPI confronto", comment="Le metriche qui sotto sono calcolate sullo stesso flusso già usato da Summary, report e analisi avanzate.", icon="metrics")
        _render_benchmark_kpis(metrics)

    with profile_step("Cruscotti/Benchmark", "render matrice strumenti"):
        vertical_gap("sm")
        matrix = payload.get("instrument_matrix")
        _render_instrument_benchmark_matrix(matrix)

    with profile_step("Cruscotti/Benchmark", "render sezione scatter coerenza", count=len(matrix) if isinstance(matrix, pd.DataFrame) else None):
        vertical_gap("sm")
        render_section_title(
            "Mappa coerenza / extra-rendimento",
            comment="Ogni punto è uno strumento: più è a destra più il benchmark è rappresentativo; sopra lo zero lo strumento batte il benchmark nel periodo comune.",
            icon="analysis",
        )
        matrix_count = len(matrix) if isinstance(matrix, pd.DataFrame) else None
        scatter_fig = _cached_render_value(
            f"{render_sig}:scatter_coerenza",
            lambda: build_instrument_benchmark_scatter(matrix),
            label="scatter coerenza",
            count=matrix_count,
        )
        with profile_step("Cruscotti/Benchmark", "render scatter coerenza", count=matrix_count):
            st.plotly_chart(scatter_fig, width="stretch")

    _render_normalized_performance_section(ctx)
