"""Scheda Cruscotti > Accumuli.

UI modulare per PAC espliciti e acquisti progressivi su FND/ETF/ETC.
Consuma il tema centralizzato e delega i calcoli a core.services.accumuli.
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
from core.services.accumuli import AccumuliResult, build_accumuli_analysis
from ui.charts.accumuli import (
    build_accumuli_overview_chart,
    build_accumulo_price_pmc_chart,
    build_accumulo_value_chart,
)
from ui.components import kpi_card, legend_block, render_section_title, render_styled_table, vertical_gap
from ui.formatting import fmt_eur_it, fmt_num_it, fmt_pct_it, fmt_qty_it
from ui.theme import P, macro_color


ACCUMULI_ANALYSIS_CACHE_KEY = "_cruscotti_accumuli_analysis_cache_v1"
ACCUMULI_RENDER_CACHE_KEY = "_cruscotti_accumuli_render_cache_v2"


def _prune_cache_items(items: dict[str, Any], max_items: int = 24) -> None:
    """Mantiene contenuta la cache sessione degli oggetti UI già costruiti."""
    if len(items) <= max_items:
        return
    for old_key in list(items.keys())[: max(0, len(items) - max_items)]:
        items.pop(old_key, None)


def _frame_token(df: Any, cols: list[str] | None = None) -> str:
    """Token compatto per invalidare la cache figure senza serializzare oggetti pesanti."""
    if df is None:
        return "none"
    if not isinstance(df, pd.DataFrame):
        try:
            return f"obj:{len(df)}:{type(df).__name__}"
        except Exception:
            return f"obj:{type(df).__name__}"
    if df.empty:
        return f"df:0:{','.join(map(str, df.columns))}"
    try:
        use = df[cols].copy() if cols else df.copy()
        digest = int(pd.util.hash_pandas_object(use, index=True).sum())
        return f"df:{len(use)}:{digest}"
    except Exception:
        first_idx = str(df.index[0]) if len(df.index) else ""
        last_idx = str(df.index[-1]) if len(df.index) else ""
        return f"df:{len(df)}:{first_idx}:{last_idx}:{','.join(map(str, df.columns))}"


def _cached_render_value(key: str, builder, *, label: str, count: int | None = None):
    """Cache sessione per figure UI Accumuli già costruite.

    L'analisi PAC è già congelata; il log v12 ha mostrato che il costo residuo
    era la ricostruzione ripetuta delle figure dal payload già disponibile.
    Questa cache non modifica dati o navigazione: evita solo rebuild UI identici
    nel rerun caldo.
    """
    cache = st.session_state.setdefault(ACCUMULI_RENDER_CACHE_KEY, {})
    if not isinstance(cache, dict):
        cache = {}
        st.session_state[ACCUMULI_RENDER_CACHE_KEY] = cache
    if key in cache:
        with profile_step("Cruscotti/Accumuli", f"cache hit figura {label}", count=count):
            return cache[key]
    with profile_step("Cruscotti/Accumuli", f"build figura {label}", count=count):
        value = builder()
    cache[key] = value
    _prune_cache_items(cache)
    return value


def _small_signature_part(value: Any) -> Any:
    """Riduce oggetti voluminosi a una firma leggera per la cache UI Accumuli."""
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
            "strumenti",
            "operazioni",
            "settings",
            "schema_version",
        }}
    if isinstance(value, (list, tuple)):
        if not value:
            return {"len": 0}
        return {"len": len(value), "first": str(value[0])[:80], "last": str(value[-1])[:80]}
    return value


def _accumuli_analysis_signature(ctx: SimpleNamespace) -> str:
    """Firma logica dell'analisi accumuli, usata solo per freschezza cache sessione."""
    material = {
        "data_sig": build_portfolio_data_signature(
            getattr(ctx, "data", {}),
            app_version=str(getattr(ctx, "app_version", "n/d")),
            schema_version=str(getattr(ctx, "schema_version", "n/d")),
        ),
        "da": _small_signature_part(getattr(ctx, "da", pd.DataFrame())),
    }
    raw = json.dumps(material, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _get_accumuli_analysis_cache(signature: str) -> tuple[dict[str, Any] | None, bool]:
    """Restituisce (entry, stale) usando prima sessione e poi cache persistente."""
    cache = st.session_state.setdefault(ACCUMULI_ANALYSIS_CACHE_KEY, {"items": {}, "latest_key": ""})
    if not isinstance(cache, dict):
        cache = {"items": {}, "latest_key": ""}
        st.session_state[ACCUMULI_ANALYSIS_CACHE_KEY] = cache
    items = cache.setdefault("items", {})
    if not isinstance(items, dict):
        items = {}
        cache["items"] = items
    if signature in items and isinstance(items[signature], dict):
        items[signature].setdefault("cache_source", "session")
        return items[signature], False

    disk_entry, disk_stale, disk_source = load_persistent_analytics_entry("accumuli", signature)
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


def _store_accumuli_analysis_cache(signature: str, result: Any) -> dict[str, Any]:
    cache = st.session_state.setdefault(ACCUMULI_ANALYSIS_CACHE_KEY, {"items": {}, "latest_key": ""})
    items = cache.setdefault("items", {})
    entry = {
        "signature": signature,
        "created_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "result": result,
        "cache_source": "session+disk",
    }
    items[signature] = entry
    cache["latest_key"] = signature
    store_persistent_analytics_entry("accumuli", signature, entry, max_entries=6)
    if len(items) > 4:
        for old_key in list(items.keys())[:-4]:
            items.pop(old_key, None)
    return entry


def _render_accumuli_freeze_header(entry: dict[str, Any] | None, stale: bool, signature: str, show_explanations: bool = True) -> bool:
    """Header operativo: non rigenera Accumuli se l'utente non lo chiede."""
    render_section_title(
        "Accumuli e PAC",
        comment=(
            "Analisi congelata: metriche, grafici PAC e dettaglio accumuli vengono rigenerati solo su richiesta, "
            "così i Cruscotti restano leggeri nei rerun ordinari."
            if show_explanations
            else None
        ),
        icon="analysis",
    )
    if entry is None:
        st.info(
            "Nessuna analisi accumuli disponibile nella cache persistente. "
            "La prima analisi va generata una sola volta; poi verrà recuperata anche dopo il riavvio dell'app."
        )
        return st.button("Analizza accumuli", type="primary", key=f"accumuli_analyze_{signature}")

    created_at = str(entry.get("created_at") or "n/d")
    if stale:
        st.warning(
            f"Sto mostrando l'ultima analisi accumuli disponibile in cache, generata il {created_at}. "
            "I dati del portafoglio sono cambiati: rigenera solo se vuoi aggiornare questa lettura."
        )
        return st.button("Aggiorna analisi accumuli", type="primary", key=f"accumuli_refresh_{signature}")

    source = str(entry.get("cache_source") or "cache")
    st.caption(f"Analisi accumuli in cache — generata il {created_at} — origine: {source}. Non viene rigenerata automaticamente nei rerun.")
    return st.button("Rigenera analisi accumuli", type="secondary", key=f"accumuli_regen_{signature}")


_FIELD_RENAMES = {
    "elasticita_prossima_rata": "elasticita_prossimo_acquisto",
    "rata_tipica": "importo_tipico_acquisto",
}


def _migrate_result(result: Any) -> Any:
    """Rinomina i vecchi nomi di campo nei risultati cached per compatibilità con il codice corrente."""
    if result is None or not hasattr(result, "summary"):
        return result
    summary = result.summary
    if isinstance(summary, pd.DataFrame) and not summary.empty:
        old_cols = {old: new for old, new in _FIELD_RENAMES.items() if old in summary.columns and new not in summary.columns}
        if old_cols:
            summary = summary.rename(columns=old_cols)
    by_ticker: dict[str, Any] = {}
    for tk, v in (result.by_ticker or {}).items():
        row = v.get("summary", {})
        if isinstance(row, dict):
            updated = False
            for old, new in _FIELD_RENAMES.items():
                if old in row and new not in row:
                    row = dict(row)
                    row[new] = row.pop(old)
                    updated = True
            if updated:
                v = dict(v)
                v["summary"] = row
        by_ticker[tk] = v
    return AccumuliResult(summary, by_ticker)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _priority_color(value: str) -> str:
    return {"Alta": P["red"], "Media": P["orange"], "Bassa": P["green"]}.get(str(value), P["muted"])


def _state_color(value: str) -> str:
    return {
        "Maturo": P["green"],
        "Efficiente": P["green"],
        "Rafforzabile": P["blue"],
        "Reattivo": P["red"],
        "Sotto pressione": P["red"],
        "Da monitorare": P["muted"],
        "Non significativo": P["muted"],
    }.get(str(value), P["blue"])


def _style_summary_table(row: pd.Series) -> list[str]:
    styles: list[str] = []
    cat = str(row.get("Categoria") or "")
    state = str(row.get("Stato") or "")
    priority = str(row.get("Priorità") or "")
    raw_pl = _safe_float(row.get("P/L"))
    for col in row.index:
        style = ""
        if col == "Strumento":
            style = f"color:{macro_color(cat)};font-weight:850;"
        elif col == "Categoria":
            style = f"color:{macro_color(cat)};font-weight:650;"
        elif col == "Quote":
            style = f"color:{P['blue']};font-weight:800;"
        elif col == "P/L":
            style = f"color:{P['green'] if raw_pl >= 0 else P['red']};font-weight:800;"
        elif col == "Stato":
            color = _state_color(state)
            style = f"color:{color};font-weight:850;text-align:center;"
        elif col == "Priorità":
            color = _priority_color(priority)
            style = f"color:{color};font-weight:850;text-align:center;"
        styles.append(style)
    return styles


def _format_summary(summary: pd.DataFrame) -> pd.DataFrame:
    """Dataset tabellare grezzo, formattato poi tramite Styler.

    Mantenerlo numerico consente a Streamlit/Pandas di applicare allineamenti,
    formati e sort in modo coerente con la tabella Portafoglio.
    """
    if summary is None or summary.empty:
        return pd.DataFrame()
    display = pd.DataFrame(
        {
            "Strumento": summary["ticker"].astype(str),
            "Categoria": summary["categoria"].astype(str),
            "N. acquisti": pd.to_numeric(summary["n_acquisti"], errors="coerce").fillna(0).astype(int),
            "Quote": pd.to_numeric(summary["quote"], errors="coerce"),
            "Capitale": pd.to_numeric(summary["capitale"], errors="coerce"),
            "Valore": pd.to_numeric(summary["controvalore"], errors="coerce"),
            "P/L": pd.to_numeric(summary["pl_pct"], errors="coerce"),
            "PMC": pd.to_numeric(summary["pmc"], errors="coerce"),
            "Prezzo": pd.to_numeric(summary["prezzo_attuale"], errors="coerce"),
            "Elast. PMC": pd.to_numeric(summary["elasticita_prossimo_acquisto"], errors="coerce"),
            "Stato": summary["stato"].astype(str),
            "Priorità": summary["priorita"].astype(str),
        }
    )
    return display


def _render_overview_kpis(summary: pd.DataFrame) -> None:
    total_invested = float(pd.to_numeric(summary.get("capitale"), errors="coerce").fillna(0.0).sum())
    total_value = float(pd.to_numeric(summary.get("controvalore"), errors="coerce").fillna(0.0).sum())
    total_pl = total_value - total_invested
    total_pl_pct = total_pl / total_invested if total_invested > 0 else 0.0
    below_pmc = int((pd.to_numeric(summary.get("margine_pmc"), errors="coerce") < 0).sum())
    high_elasticity = int((pd.to_numeric(summary.get("elasticita_prossimo_acquisto"), errors="coerce") >= 0.08).sum())
    cols = st.columns(6)
    with cols[0]:
        kpi_card("Strumenti in accumulo", fmt_num_it(len(summary), 0), "PAC espliciti e progressivi", accent=P["blue"])
    with cols[1]:
        kpi_card("Capitale investito", fmt_eur_it(total_invested, 0), "Costo aperto aggregato", accent=P["green"])
    with cols[2]:
        kpi_card("Controvalore", fmt_eur_it(total_value, 0), "Valore corrente", accent=P["blue"])
    with cols[3]:
        kpi_card("P/L accumuli", fmt_pct_it(total_pl_pct, 1, signed=True), fmt_eur_it(total_pl, 0, signed=True), accent=P["green"], value_color=P["green"] if total_pl >= 0 else P["red"])
    with cols[4]:
        kpi_card("Sotto PMC", fmt_num_it(below_pmc, 0), "Prezzo sotto carico", accent=P["orange"], value_color=P["orange"] if below_pmc else P["green"])
    with cols[5]:
        kpi_card("Alta elasticità", fmt_num_it(high_elasticity, 0), "Prossimo acquisto ≥ 8%", accent=P["red" if high_elasticity else "green"], value_color=P["red"] if high_elasticity else P["green"])


def _filter_summary(summary: pd.DataFrame) -> pd.DataFrame:
    """Filtro leggero: solo ricerca testuale.

    I filtri per categoria/PAC/sotto PMC sono stati rimossi perché la scheda
    deve funzionare come cruscotto operativo, non come pannello di interrogazione.
    """
    query = st.text_input(
        "Ricerca strumento",
        value="",
        placeholder="Cerca per ticker o nome...",
        key="accumuli_search",
    )
    filtered = summary.copy()
    query = str(query or "").strip().lower()
    if query:
        filtered = filtered[
            filtered["ticker"].astype(str).str.lower().str.contains(query, regex=False)
            | filtered["nome"].astype(str).str.lower().str.contains(query, regex=False)
        ]
    return filtered.reset_index(drop=True)


def _fmt_elasticity_table(value: Any) -> str:
    """Formato leggibile dell'elasticità PMC in tabella.

    La metrica resta quella originaria, quindi può superare il 100% su
    posizioni embrionali; in sintesi evitiamo numeri estremi tipo 412,1%.
    """
    v = _safe_float(value, default=float("nan"))
    if pd.isna(v):
        return "—"
    if v >= 1.0:
        return ">100%"
    return fmt_pct_it(v, 1)


def _elasticity_judgment(value: Any) -> str:
    v = _safe_float(value, default=float("nan"))
    if pd.isna(v):
        return "Non calcolabile"
    if v < 0.02:
        return "Bassa: PMC quasi blindato"
    if v < 0.08:
        return "Media: PMC ancora sensibile"
    if v < 0.25:
        return "Alta: acquisto incisivo"
    if v < 1.0:
        return "Molto alta: posizione giovane"
    return "Anomala: acquisto oltre il capitale"


def _render_summary_table(summary: pd.DataFrame) -> None:
    with profile_step("Cruscotti/Accumuli", "summary table: format dataframe", count=len(summary) if isinstance(summary, pd.DataFrame) else None):
        display = _format_summary(summary)
    if display.empty:
        st.info("Nessuno strumento soddisfa i filtri selezionati.")
        return
    numeric_cols = ["N. acquisti", "Quote", "Capitale", "Valore", "P/L", "PMC", "Prezzo", "Elast. PMC"]
    center_cols = ["Stato", "Priorità"]
    with profile_step("Cruscotti/Accumuli", "summary table: build styler", count=len(display)):
        styled = (
            display.style
        .format(
            {
                "N. acquisti": lambda v: fmt_num_it(v, 0),
                "Quote": lambda v: fmt_qty_it(v, 4),
                "Capitale": lambda v: fmt_eur_it(v, 0),
                "Valore": lambda v: fmt_eur_it(v, 0),
                "P/L": lambda v: fmt_pct_it(v, 1, signed=True),
                "PMC": lambda v: fmt_eur_it(v, 2),
                "Prezzo": lambda v: fmt_eur_it(v, 2),
                "Elast. PMC": _fmt_elasticity_table,
            }
        )
        .apply(_style_summary_table, axis=1)
        .set_properties(**{"font-variant-numeric": "tabular-nums"})
        .set_properties(subset=numeric_cols, **{"text-align": "right"})
        .set_properties(subset=center_cols, **{"text-align": "center"})
        .set_table_styles(
            [
                {"selector": "th", "props": [("font-weight", "700"), ("white-space", "nowrap")]},
                {"selector": "td", "props": [("white-space", "nowrap"), ("overflow", "hidden"), ("text-overflow", "ellipsis")]},
                {"selector": "th.col0,td.col0", "props": [("min-width", "110px"), ("max-width", "130px")]},
                {"selector": "th.col1,td.col1", "props": [("min-width", "48px"), ("max-width", "62px"), ("text-align", "center")]},
                {"selector": "th.col2,td.col2", "props": [("min-width", "42px"), ("max-width", "52px")]},
                {"selector": "th.col3,td.col3", "props": [("min-width", "66px"), ("max-width", "82px"), ("color", "#3B82F6"), ("font-weight", "800")]},
                {"selector": "th.col4,td.col4,th.col5,td.col5", "props": [("min-width", "72px"), ("max-width", "88px")]},
                {"selector": "th.col6,td.col6,th.col7,td.col7,th.col8,td.col8,th.col9,td.col9", "props": [("min-width", "62px"), ("max-width", "82px")]},
                {"selector": "th.col10,td.col10", "props": [("min-width", "82px"), ("max-width", "98px"), ("text-align", "center")]},
                {"selector": "th.col11,td.col11", "props": [("min-width", "66px"), ("max-width", "82px"), ("text-align", "center")]},
                {
                    "selector": "th.col3,th.col4,th.col5,th.col6,th.col7,th.col8,th.col9,td.col3,td.col4,td.col5,td.col6,td.col7,td.col8,td.col9",
                    "props": [("text-align", "right")],
                },
                {
                    "selector": "th.col10,th.col11,td.col10,td.col11",
                    "props": [("text-align", "center")],
                },
            ],
            overwrite=False,
        )
    )
    with profile_step("Cruscotti/Accumuli", "summary table: render dataframe", count=len(display)):
        render_styled_table(
            styled,
        height=min(420, 72 + len(display) * 36),
        column_config={
            "Strumento": st.column_config.TextColumn("Strumento", width=118),
            "Categoria": st.column_config.TextColumn("Categoria", width=56),
            "N. acquisti": st.column_config.NumberColumn("N.", width=48),
            "Quote": st.column_config.NumberColumn("Quote", width=72),
            "Capitale": st.column_config.NumberColumn("Capitale", width=82),
            "Valore": st.column_config.NumberColumn("Valore", width=82),
            "P/L": st.column_config.NumberColumn("P/L", width=64),
            "PMC": st.column_config.NumberColumn("PMC", width=72),
            "Prezzo": st.column_config.NumberColumn("Prezzo", width=72),
            "Elast. PMC": st.column_config.NumberColumn("Elast. PMC", width=78),
            "Stato": st.column_config.TextColumn("Stato", width=92),
            "Priorità": st.column_config.TextColumn("Priorità", width=76),
        },
    )


def _render_diagnosis(row: pd.Series) -> None:
    state = str(row.get("stato") or "Da monitorare")
    priority = str(row.get("priorita") or "Media")
    diagnosis = str(row.get("diagnosi") or "Analisi disponibile ma senza un segnale operativo netto.")
    color = _state_color(state)
    st.markdown(
        f"""
        <div class="kpi-card" style="--accent:{color};border-left:4px solid {color};">
            <div class="kpi-label">Diagnosi automatica</div>
            <div style="font-weight:850;color:{color};margin:2px 0 6px 0;">{state} · Priorità {priority}</div>
            <div class="kpi-sub" style="font-size:0.92rem;line-height:1.45;">{diagnosis}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )



def _render_metric_comment(row: pd.Series) -> None:
    state = str(row.get("stato") or "Da monitorare")
    margin = _safe_float(row.get("margine_pmc"))
    elasticity = _safe_float(row.get("elasticita_prossimo_acquisto"))
    efficiency = row.get("efficienza_accumulo")
    percentile = row.get("percentile_pmc")
    regularity = row.get("regolarita")
    drawdown = row.get("drawdown_da_massimo")
    parts = [
        f"<b>{state}</b>: il grafico legge l'accumulo sull'intera vita operativa dello strumento, anche quando usi i bottoni temporali del grafico.",
        f"Margine su PMC {fmt_pct_it(margin, 1, signed=True)}: indica la distanza tra prezzo attuale e prezzo medio di carico.",
        f"Elasticità PMC {_fmt_elasticity_table(elasticity)}: {_elasticity_judgment(elasticity)}.",
        f"Percentile PMC {fmt_pct_it(percentile, 0)}: {_percentile_judgment(percentile)} rispetto ai prezzi osservati nel periodo PAC.",
        f"Regolarità acquisti {fmt_pct_it(regularity, 0)}: {_regularity_judgment(regularity)}.",
        f"Drawdown dal massimo {fmt_pct_it(drawdown, 1, signed=True)}: {_drawdown_judgment(drawdown)}.",
    ]
    if efficiency is not None and pd.notna(efficiency):
        parts.append(f"Efficienza accumulo {fmt_num_it(efficiency, 2)}: confronto descrittivo tra media prezzi e PMC effettivo.")
    legend_block("<br>".join(parts), variant="bottom")


def _render_recent_operations(ops: pd.DataFrame) -> None:
    st.markdown("#### Ultimi acquisti")
    if ops is None or ops.empty:
        st.caption("Nessun acquisto disponibile.")
        return
    with profile_step("Cruscotti/Accumuli", "recent operations: build table", count=len(ops)):
        table = ops.head(6).copy()
        table["Data"] = pd.to_datetime(table["data"], errors="coerce").dt.strftime("%d/%m/%Y")
        table["Importo"] = [fmt_eur_it(v, 2) for v in pd.to_numeric(table["importo_lordo"], errors="coerce").fillna(0.0)]
        table["Quote"] = [fmt_qty_it(v, 4) for v in pd.to_numeric(table["qty"], errors="coerce").fillna(0.0)]
        table["Prezzo"] = [fmt_eur_it(v, 4) for v in pd.to_numeric(table["price"], errors="coerce").fillna(0.0)]
    with profile_step("Cruscotti/Accumuli", "recent operations: st.dataframe", count=len(table)):
        st.dataframe(table[["Data", "Importo", "Quote", "Prezzo"]], width="stretch", hide_index=True, height="content")



def _efficiency_judgment(value: Any) -> str:
    v = _safe_float(value, default=float("nan"))
    if pd.isna(v):
        return "Non calcolabile"
    if v >= 1.00:
        return "Ottima: PMC migliore della media"
    if v >= 0.98:
        return "Neutra: vicino alla media"
    return "Debole: PMC sopra la media"


def _volatility_judgment(value: Any) -> str:
    v = _safe_float(value, default=float("nan"))
    if pd.isna(v):
        return "Non calcolabile"
    if v < 0.05:
        return "Bassa: prezzi omogenei"
    if v < 0.10:
        return "Media: oscillazioni assorbite"
    return "Alta: acquisti su forte volatilità"


def _margin_judgment(value: Any) -> str:
    v = _safe_float(value, default=float("nan"))
    if pd.isna(v):
        return "Non calcolabile"
    if v >= 0.08:
        return "Cuscinetto ampio"
    if v >= 0.00:
        return "Margine positivo"
    return "Sotto PMC"


def _pl_judgment(value: Any) -> str:
    v = _safe_float(value, default=float("nan"))
    if pd.isna(v):
        return "Non calcolabile"
    if v > 0:
        return "In utile"
    if v < 0:
        return "In perdita"
    return "In pareggio"



def _market_mean_judgment(row: pd.Series) -> str:
    mean_px = _safe_float(row.get("prezzo_medio_periodo"), default=float("nan"))
    pmc = _safe_float(row.get("pmc"), default=float("nan"))
    if pd.isna(mean_px) or pd.isna(pmc) or mean_px <= 0 or pmc <= 0:
        return "Non calcolabile"
    diff = (pmc / mean_px) - 1.0
    if diff <= -0.02:
        return "PMC migliore della media"
    if diff <= 0.02:
        return "PMC allineato alla media"
    return "PMC sopra la media"


def _percentile_judgment(value: Any) -> str:
    v = _safe_float(value, default=float("nan"))
    if pd.isna(v):
        return "Non calcolabile"
    if v <= 0.33:
        return "Molto favorevole"
    if v <= 0.66:
        return "Intermedio"
    return "Poco favorevole"


def _regularity_judgment(value: Any) -> str:
    v = _safe_float(value, default=float("nan"))
    if pd.isna(v):
        return "Non calcolabile"
    if v >= 0.70:
        return "Alta: cadenza regolare"
    if v >= 0.40:
        return "Media: cadenza parziale"
    return "Bassa: acquisti irregolari"


def _drawdown_judgment(value: Any) -> str:
    v = _safe_float(value, default=float("nan"))
    if pd.isna(v):
        return "Non calcolabile"
    if v >= -0.02:
        return "Vicino ai massimi"
    if v >= -0.10:
        return "Correzione moderata"
    if v >= -0.20:
        return "Correzione rilevante"
    return "Forte drawdown"

def _render_detail(row: pd.Series, detail: dict[str, Any], cache_signature: str) -> None:
    ticker = str(row.get("ticker") or "")
    with profile_step("Cruscotti/Accumuli", f"detail {ticker}: title"):
        render_section_title(f"Dettaglio accumulo – {ticker}", icon="analysis")
    items = [
        ("Quote totali", fmt_qty_it(row.get("quote"), 4), "quote detenute attualmente", P["blue"], P["blue"]),
        ("Capitale", fmt_eur_it(row.get("capitale"), 0), "Costo aperto", P["muted"], None),
        ("Controvalore", fmt_eur_it(row.get("controvalore"), 0), "Valore corrente", P["green"], P["green"] if _safe_float(row.get("pl_abs")) >= 0 else P["red"]),
        ("P/L", fmt_pct_it(row.get("pl_pct"), 1, signed=True), _pl_judgment(row.get("pl_pct")), P["green"], P["green"] if _safe_float(row.get("pl_pct")) >= 0 else P["red"]),
        ("PMC", fmt_eur_it(row.get("pmc"), 2), "Prezzo medio di carico", P["orange"], None),
        ("Prezzo", fmt_eur_it(row.get("prezzo_attuale"), 2), "Ultimo prezzo disponibile", P["blue"], None),
        ("Margine PMC", fmt_pct_it(row.get("margine_pmc"), 1, signed=True), _margin_judgment(row.get("margine_pmc")), P["green"], P["green"] if _safe_float(row.get("margine_pmc")) >= 0 else P["red"]),
        ("Volatilità", fmt_pct_it(row.get("volatilita_acquisti"), 1), _volatility_judgment(row.get("volatilita_acquisti")), P["red"], None),
        ("Media mercato", fmt_eur_it(row.get("prezzo_medio_periodo"), 2), _market_mean_judgment(row), P["blue"], None),
        ("Percentile PMC", fmt_pct_it(row.get("percentile_pmc"), 0), _percentile_judgment(row.get("percentile_pmc")), P["orange"], None),
        ("Regolarità", fmt_pct_it(row.get("regolarita"), 0), _regularity_judgment(row.get("regolarita")), P["green"], None),
        ("Drawdown max", fmt_pct_it(row.get("drawdown_da_massimo"), 1, signed=True), _drawdown_judgment(row.get("drawdown_da_massimo")), P["red"], P["green"] if _safe_float(row.get("drawdown_da_massimo"), 0.0) >= -0.02 else P["red"]),
    ]
    with profile_step("Cruscotti/Accumuli", f"detail {ticker}: render KPI cards"):
        for chunk in [items[i:i+4] for i in range(0, len(items), 4)]:
            if not chunk:
                continue
            cols = st.columns(4)
            for col, (label, value, subtitle, accent, value_color) in zip(cols, chunk):
                with col:
                    kpi_card(label, value, subtitle, accent=accent, value_color=value_color)
            vertical_gap("xs")

    with profile_step("Cruscotti/Accumuli", f"detail {ticker}: render comment"):
        _render_metric_comment(row)
        vertical_gap("xs")

    series = detail.get("series", pd.DataFrame())
    operations = detail.get("operations", pd.DataFrame())
    series_count = len(series) if isinstance(series, pd.DataFrame) else None
    with profile_step("Cruscotti/Accumuli", f"detail {ticker}: layout columns", count=series_count):
        chart_col, side_col = st.columns([2.35, 1.0], gap="large")
    with chart_col:
        series_token = _frame_token(series)
        ops_token = _frame_token(operations)
        price_fig = _cached_render_value(
            f"{cache_signature}:{ticker}:price_pmc:{series_token}:{ops_token}",
            lambda: build_accumulo_price_pmc_chart(series, operations),
            label=f"{ticker} prezzo vs PMC",
            count=series_count,
        )
        with profile_step("Cruscotti/Accumuli", f"detail {ticker}: render prezzo vs PMC", count=series_count):
            st.plotly_chart(price_fig, width="stretch")
        value_fig = _cached_render_value(
            f"{cache_signature}:{ticker}:capitale_vs_valore:{series_token}",
            lambda: build_accumulo_value_chart(series),
            label=f"{ticker} capitale vs valore",
            count=series_count,
        )
        with profile_step("Cruscotti/Accumuli", f"detail {ticker}: render capitale vs valore", count=series_count):
            st.plotly_chart(value_fig, width="stretch")
    with side_col:
        with profile_step("Cruscotti/Accumuli", f"detail {ticker}: diagnosis/recent ops"):
            _render_diagnosis(row)
            vertical_gap("sm")
            _render_recent_operations(detail.get("operations", pd.DataFrame()))


def render_accumuli(ctx: SimpleNamespace, show_explanations: bool = True) -> None:
    """Renderizza la scheda Accumuli senza rigenerare automaticamente l'analisi pesante."""
    with profile_step("Cruscotti/Accumuli", "signature/cache/header"):
        signature = _accumuli_analysis_signature(ctx)
        entry, stale = _get_accumuli_analysis_cache(signature)
        refresh_requested = _render_accumuli_freeze_header(entry, stale, signature, show_explanations=show_explanations)

    if refresh_requested:
        with st.status("Analisi accumuli in corso…", expanded=True) as status:
            st.write("Costruzione metriche DCA, grafici PAC e dettaglio per strumento.")
            with profile_step("Cruscotti/Accumuli", "build analysis"):
                result = build_accumuli_analysis(getattr(ctx, "data", {}) or {})
            entry = _store_accumuli_analysis_cache(signature, result)
            stale = False
            status.update(label="Analisi accumuli aggiornata", state="complete", expanded=False)
    elif entry is None:
        legend_block(
            "Questa sezione è intenzionalmente congelata: Accumuli è una lettura operativa non quotidiana e non viene "
            "ricalcolata durante i normali rerun di Cruscotti. Premi “Analizza accumuli” quando vuoi aggiornare metriche, grafici e dettaglio PAC.",
            variant="bottom",
        )
        return
    else:
        result = entry.get("result") if isinstance(entry, dict) else None
        with profile_step("Cruscotti/Accumuli", "reuse cached analysis"):
            pass

    result = _migrate_result(result)

    # Usa la firma memorizzata nell'entry (versione dell'analisi) anziché quella
    # corrente del portfolio: così un refresh prezzi non invalida le figure
    # di un'analisi accumuli che non è stata rigenerata.
    render_sig = resolve_analysis_render_sig(signature, entry)

    if result is None:
        st.info("Analisi accumuli non disponibile. Premi “Analizza accumuli” per ricostruirla.")
        return

    summary = result.summary
    if summary is None or summary.empty:
        st.info("Non risultano strumenti FND/ETF/ETC con almeno tre acquisti o con logica PAC riconoscibile.")
        return

    with profile_step("Cruscotti/Accumuli", "render overview KPI", count=len(summary)):
        _render_overview_kpis(summary)
        vertical_gap("sm")
    with profile_step("Cruscotti/Accumuli", "filter summary", count=len(summary)):
        filtered = _filter_summary(summary)
        vertical_gap("xs")

    if not filtered.empty:
        overview_key = f"{render_sig}:overview:{_frame_token(filtered, ['ticker', 'categoria', 'capitale', 'controvalore', 'pl_pct', 'priorita'])}"
        overview_fig = _cached_render_value(
            overview_key,
            lambda: build_accumuli_overview_chart(filtered),
            label="overview accumuli",
            count=len(filtered),
        )
        with profile_step("Cruscotti/Accumuli", "render overview chart", count=len(filtered)):
            st.plotly_chart(overview_fig, width="stretch")
    with profile_step("Cruscotti/Accumuli", "render summary section/table", count=len(filtered)):
        render_section_title("Sintesi accumuli", icon="portfolio", gap_after="xs")
        _render_summary_table(filtered)
    if filtered.empty:
        return

    with profile_step("Cruscotti/Accumuli", "select ticker", count=len(filtered)):
        ticker_options = filtered["ticker"].astype(str).tolist()
        selected = st.selectbox("Strumento da analizzare", ticker_options, index=0, key="accumuli_selected_ticker")
        row = filtered[filtered["ticker"].astype(str) == selected].iloc[0]
        detail = result.by_ticker.get(str(selected), {})
        vertical_gap("sm")
    with profile_step("Cruscotti/Accumuli", f"render detail {selected}"):
        _render_detail(row, detail, render_sig)

