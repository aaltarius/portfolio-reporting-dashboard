"""
ui/pages/confronto.py — Tab Confronto (t7): snapshot comparison
Pure rendering with pre-computed snapshot data.
"""
import html
import logging
import json
from types import SimpleNamespace
from datetime import date, datetime

import pandas as pd
import streamlit as st

from core.cache import invalidate_portfolio_cache
from streamlit.delta_generator import DeltaGenerator

from persistence.storage import (
    load_snapshots,
    save_snapshots,
)
from core.finance import (
    get_effective_portfolio_benchmark_config,
)
from core.services.snapshots import (
    build_snapshot_display_names,
    build_multi_snapshot_categories_wide_df,
    build_multi_snapshot_categories_df,
    build_multi_snapshot_holdings_wide_df,
    build_multi_snapshot_metrics_wide_df,
    build_multi_snapshot_metrics_df,
    build_snapshot_from_portfolio_data,
    build_snapshot_summary_df,
    compare_snapshots,
    delete_snapshot_by_id,
    enrich_snapshot_with_portfolio_data,
    enrich_snapshots_with_portfolio_data,
    snapshot_datetime,
    snapshot_holdings_df,
)
from core.services.period_activity import build_period_activity
from core.services.comparison_report import (
    build_comparison_report_filename,
    build_comparison_report_html,
)
from core.settings_profiles import get_effective_show_explanations
from ui.formatting import (
    fmt_dt_it, fmt_num_it, fmt_eur_it, fmt_pct_it, fmt_qty_it,
)
from ui.i18n import t
from ui.theme import get_theme_context
from ui.notifications import queue_info, queue_success
from ui.ux_helpers import confirm_danger, render_danger_hint, render_json_popover
from ui.components import (
    kpi_card, legend_block, back_to_top,
    render_section_title,
    render_styled_table,
    vertical_gap, should_render_section,
)
from ui.charts.confronto import (
    build_multi_snapshot_delta_bar_chart,
    build_multi_snapshot_category_grouped_chart,
    build_multi_snapshot_holdings_grouped_chart,
    build_snapshot_category_timeline_chart,
    build_snapshot_category_delta_chart,
    build_snapshot_comparison_time_chart,
    build_snapshot_contributors_chart,
    build_snapshot_metric_timeline_chart,
    build_snapshot_pl_delta_chart,
    build_snapshot_return_delta_chart,
    build_snapshot_value_decomposition_chart,
)
from ui.charts.tables import color_pl, style_macro_cols
from ui.charts.settings import apply_settings
from ui.page_chrome import render_page_intro as render_page_intro_shared, render_section_line as render_section_line_shared

logger = logging.getLogger("portafoglio.ui.confronto")


def _snapshot_letter_map(snapshot_names: list[str]) -> dict[str, str]:
    letters = ["A", "B", "C", "D"]
    return {name: letters[idx] if idx < len(letters) else f"S{idx + 1}" for idx, name in enumerate(snapshot_names)}


def _rename_snapshot_table_cols(frame: pd.DataFrame, label_map: dict[str, str]) -> pd.DataFrame:
    if frame is None:
        return pd.DataFrame()
    renamed = frame.copy()
    if renamed.empty or not label_map:
        return renamed
    direct_map = {name: alias for name, alias in label_map.items() if name in renamed.columns}
    if direct_map:
        renamed = renamed.rename(columns=direct_map)
    prefixes = ("Quote ", "Prezzo ", "Costo ", "Valore ", "Peso ", "P/L ", "Rendimento ")
    cols_map: dict[str, str] = {}
    for col in renamed.columns:
        for prefix in prefixes:
            if col.startswith(prefix):
                suffix = col[len(prefix):]
                alias = label_map.get(suffix)
                if alias:
                    cols_map[col] = f"{prefix}{alias}"
                break
    if cols_map:
        renamed = renamed.rename(columns=cols_map)
    return renamed


def _compact_table_styler(styler):
    return styler.set_table_styles(
        [
            {"selector": "th", "props": [("font-size", "0.76rem"), ("padding", "6px 8px")]},
            {"selector": "td", "props": [("font-size", "0.76rem"), ("padding", "6px 8px")]},
        ],
        overwrite=False,
    )


def _compact_instrument_label(value: object, max_len: int = 34) -> str:
    text = str(value or "").strip()
    if len(text) <= max_len:
        return html.escape(text)
    short = text[: max_len - 1].rstrip() + "…"
    return f"<span title='{html.escape(text)}'>{html.escape(short)}</span>"


def _header_break(label: str) -> str:
    mapping = {
        "Delta complessivo": "Delta<br>compl.",
        "Delta quote complessivo": "Delta quote<br>compl.",
        "Delta prezzo % complessivo": "Delta prezzo %<br>compl.",
        "Delta costo complessivo": "Delta costo<br>compl.",
        "Delta valore complessivo": "Delta valore<br>compl.",
        "Delta P/L complessivo": "Delta P/L<br>compl.",
        "Delta rendimento complessivo": "Delta rendimento<br>compl.",
        "Valore strumenti": "Valore<br>strumenti",
        "Patrimonio totale": "Patrimonio<br>totale",
    }
    if label in mapping:
        return mapping[label]
    for prefix in ("Quote ", "Prezzo ", "Costo ", "Valore ", "Peso ", "P/L ", "Rendimento "):
        if label.startswith(prefix):
            return f"{html.escape(prefix.strip())}<br>{html.escape(label[len(prefix):])}"
    return html.escape(label)


def _render_compact_html_table(
    frame: pd.DataFrame,
    *,
    theme,
    formatters: dict[str, callable] | None = None,
    signed_cols: set[str] | None = None,
) -> None:
    if frame is None or frame.empty:
        st.info("Nessun dato disponibile.")
        return
    formatters = formatters or {}
    signed_cols = signed_cols or set()
    cols = list(frame.columns)
    head = "".join(f"<th>{_header_break(str(col))}</th>" for col in cols)
    body_rows: list[str] = []
    for _, row in frame.iterrows():
        cells: list[str] = []
        for col in cols:
            raw = row.get(col)
            if col == "Strumento":
                rendered = _compact_instrument_label(raw)
            else:
                fmt = formatters.get(col)
                rendered = fmt(raw) if fmt else html.escape("" if raw is None else str(raw))
            klass = "num" if col not in {"Ticker", "Strumento", "Categoria", "Voce"} else ""
            style = ""
            if col in signed_cols:
                try:
                    val = float(raw or 0.0)
                except Exception:
                    val = 0.0
                if val > 0:
                    style = f" style='color:{theme.color_green};font-weight:600'"
                elif val < 0:
                    style = f" style='color:{theme.color_red};font-weight:600'"
            cells.append(f"<td class='{klass}'{style}>{rendered}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    st.markdown(
        f"""
        <style>
        .cmp-table-wrap {{ margin: 0 0 10px 0; }}
        .cmp-table {{
            width:100%;
            border-collapse:collapse;
            table-layout:fixed;
            font-size:0.76rem;
            line-height:1.25;
            border:1px solid {theme.border_color};
            background:{theme.bg_surface};
        }}
        .cmp-table th, .cmp-table td {{
            border:1px solid {theme.border_color};
            padding:6px 8px;
            vertical-align:top;
            white-space:normal;
            word-break:break-word;
        }}
        .cmp-table th {{
            background:{theme.bg_surface_alt};
            font-size:0.75rem;
            font-weight:700;
        }}
        .cmp-table td.num {{
            text-align:right;
        }}
        </style>
        <div class="cmp-table-wrap">
          <table class="cmp-table">
            <thead><tr>{head}</tr></thead>
            <tbody>{''.join(body_rows)}</tbody>
          </table>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _page_icon_svg(kind: str = "default") -> str:
    icons = {
        "summary": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-summary" x1="3" y1="3" x2="21" y2="21"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="3.5" y="3" width="17" height="18" rx="4" fill="url(#g-summary)" opacity=".16"/>
          <path d="M8 8.2h8M8 12h8M8 15.8h5" fill="none" stroke="url(#g-summary)" stroke-width="1.9" stroke-linecap="round"/>
          <circle cx="17" cy="16" r="2.2" fill="url(#g-summary)"/>
        </svg>
        """,
        "confronto": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-confronto" x1="4" y1="20" x2="20" y2="4"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="3" y="4" width="18" height="16" rx="4" fill="url(#g-confronto)" opacity=".14"/>
          <path d="M7 16.5V11M12 16.5V7.5M17 16.5v-4" fill="none" stroke="url(#g-confronto)" stroke-width="2.1" stroke-linecap="round"/>
          <path d="M6.5 17.5h11" stroke="url(#g-confronto)" stroke-width="1.8" stroke-linecap="round"/>
        </svg>
        """,
        "pianificazione": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-plan" x1="4" y1="4" x2="20" y2="20"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="3.5" y="5" width="17" height="15.5" rx="4" fill="url(#g-plan)" opacity=".15"/>
          <path d="M8 3.5v3M16 3.5v3M6.5 9h11" stroke="url(#g-plan)" stroke-width="1.8" stroke-linecap="round"/>
          <path d="M8 13h3l1.5 2.2L16.5 11" fill="none" stroke="url(#g-plan)" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        """,
        "gestione": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-data" x1="4" y1="4" x2="20" y2="20"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="4" y="3.5" width="16" height="17" rx="4" fill="url(#g-data)" opacity=".15"/>
          <path d="M8 8h8M8 12h8M8 16h5" stroke="url(#g-data)" stroke-width="1.8" stroke-linecap="round"/>
          <circle cx="17" cy="16" r="2.2" fill="url(#g-data)"/>
        </svg>
        """,
        "impostazioni": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-settings" x1="4" y1="4" x2="20" y2="20"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <circle cx="12" cy="12" r="8.5" fill="url(#g-settings)" opacity=".15"/>
          <path d="M12 8.1v-2M12 18v-2M8.1 12h-2M18 12h-2M9.25 9.25 7.8 7.8M16.2 16.2l-1.45-1.45M14.75 9.25 16.2 7.8M7.8 16.2l1.45-1.45" stroke="url(#g-settings)" stroke-width="1.7" stroke-linecap="round"/>
          <circle cx="12" cy="12" r="3.1" fill="none" stroke="url(#g-settings)" stroke-width="2"/>
        </svg>
        """,
        "default": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-default" x1="4" y1="4" x2="20" y2="20"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="4" y="4" width="16" height="16" rx="4" fill="url(#g-default)" opacity=".15"/>
          <path d="M8 9h8M8 13h8M8 17h5" stroke="url(#g-default)" stroke-width="1.8" stroke-linecap="round"/>
        </svg>
        """,
    }
    return icons.get(kind, icons["default"])


def _render_page_intro(title: str, comment: str, icon: str = "default", theme=None) -> None:
    return render_page_intro_shared(title, comment, icon, theme)
    theme = theme or get_theme_context()
    accent = getattr(theme, "color_blue", "#3b82f6")
    accent_2 = getattr(theme, "color_green", "#22c55e")
    font = getattr(theme, "font_color", "#111827")
    panel_bg = getattr(theme, "panel_bg", "#f8fafc")
    border = getattr(theme, "border_color", "rgba(148,163,184,.32)")
    muted = getattr(theme, "muted_color", "#64748b")
    st.markdown(
        f"""
        <style>
        .page-intro {{
            --page-accent:{accent};
            --page-accent-2:{accent_2};
            margin:0;
            padding:0;
        }}
        .page-intro-title {{
            display:flex;
            align-items:center;
            gap:10px;
            margin:0 0 8px 0;
            color:{font};
            font-size:1.28rem;
            font-weight:850;
            line-height:1.18;
            letter-spacing:-0.01em;
        }}
        .page-intro-icon {{
            width:27px;
            height:27px;
            display:inline-flex;
            align-items:center;
            justify-content:center;
            flex:0 0 27px;
        }}
        .page-intro-icon svg {{
            width:27px;
            height:27px;
            display:block;
        }}
        .page-intro-comment {{
            margin:0;
            padding:10px 14px;
            color:{font};
            background:{panel_bg};
            border:1px solid {border};
            border-left:4px solid {accent};
            border-radius:14px;
            font-size:0.92rem;
            line-height:1.42;
            font-weight:500;
            box-shadow:0 8px 18px rgba(15,23,42,.04);
        }}
        .section-line {{
            margin:14px 0 14px 0;
            border:0;
            border-top:1px solid rgba(148,163,184,.30);
        }}
        .page-intro + .section-line {{
            margin-top:14px !important;
        }}
        </style>
        <div class="page-intro">
          <div class="page-intro-title">
            <span class="page-intro-icon">{_page_icon_svg(icon)}</span>
            <span>{title}</span>
          </div>
          <div class="page-intro-comment">{comment}</div>
        </div>
        <hr class="section-line" />
        """,
        unsafe_allow_html=True,
    )


def _section_line() -> None:
    return render_section_line_shared()


def render_confronto(tab: DeltaGenerator, ctx: SimpleNamespace) -> None:
    """Pure rendering for confronto page."""
    # Get theme at function entry
    theme = get_theme_context()

    # Extract needed data from context
    data = ctx.data
    snapshots_state = load_snapshots()
    fmtd = ctx.fmtd
    settings = ctx.settings

    with tab:

        _render_page_intro("Confronto", t(settings, "comparison.note", "Scheda dedicata al confronto tra snapshot del portafoglio. Consente di leggere differenze di valore, P/L e allocazione e di esportare i dati in CSV o JSON."), "confronto", theme)
        st.markdown(
            f"""<style>
            .confronto-caption-chip {{
              display:inline-block;
              margin-top:4px;
              padding:7px 10px;
              border-radius:999px;
              border:1px solid {theme.border_color};
              background:{theme.colors.get('bg_surface_alt', theme.bg_surface)};
              color:{theme.font_color};
              font-size:0.84rem;
              line-height:1.4;
            }}
            </style>""",
            unsafe_allow_html=True,
        )
        show_explanations = get_effective_show_explanations(settings) if isinstance(settings, dict) else True
        benchmark_cfg = get_effective_portfolio_benchmark_config(settings)
        benchmark_label = str(benchmark_cfg.get("label") or "Blend automatico")
        reporting_settings = settings.get("reporting_export", {})
        export_decimals = int(reporting_settings.get("decimal_places", 2))
        preferred_export = str(reporting_settings.get("default_format", settings.get("comparison_export_format_default", "csv"))).lower()
        snaps_df = build_snapshot_summary_df(snapshots_state.get("snapshots", []))

        render_section_title(
            "Snapshot del portafoglio",
            comment="Crea una foto dello stato corrente e scegli due momenti da confrontare. Nessun grafico viene generato finche non avvii il confronto.",
            gap_after="sm",
        )
        col_create_1, col_create_2 = st.columns([2, 1], gap="medium")
        with col_create_1:
            snap_label = st.text_input(
                "Etichetta nuovo snapshot",
                value=f"Snapshot {fmtd(date.today())}",
                key="snap_new_label",
                help="Usa un nome leggibile, per esempio 'Prima ribilanciamento' o 'Fine mese'.",
            )
        with col_create_2:
            vertical_gap("lg")
            if st.button(t(settings, "comparison.create_snapshot", "Crea snapshot corrente"), width="stretch", key="snap_create"):
                snapshots_state = load_snapshots()
                snapshots_state.setdefault("snapshots", []).append(build_snapshot_from_portfolio_data(data, label=snap_label))
                save_snapshots(snapshots_state)
                logger.info("Snapshot creato dalla pagina confronto")
                queue_success(t(settings, "comparison.created", "Snapshot creato."))
                invalidate_portfolio_cache("snapshot creato")
                st.rerun()

        if not snaps_df.empty:
            styled_snaps = snaps_df.style.format({
                "Valore strumenti": lambda v: fmt_eur_it(v, 2),
                "Liquidita": lambda v: fmt_eur_it(v, 2),
                "Patrimonio": lambda v: fmt_eur_it(v, 2),
                "Costo": lambda v: fmt_eur_it(v, 2),
                "P/L": lambda v: fmt_eur_it(v, 2, signed=True),
                "Rendimento": lambda v: fmt_pct_it(v, 2, signed=True),
            }).map(color_pl, subset=["P/L", "Rendimento"])
            render_styled_table(styled_snaps, height="content")

            with st.expander("Gestione snapshot", expanded=False):
                delete_labels = (snaps_df["Etichetta"].astype(str) + " - " + snaps_df["Data"].astype(str)).tolist()
                inspect_idx = st.selectbox(
                    "Apri snapshot",
                    range(len(delete_labels)),
                    format_func=lambda i: delete_labels[i],
                    key="snap_inspect_idx",
                )
                inspect_snap = snapshots_state.get("snapshots", [])[inspect_idx]
                enriched_inspect = enrich_snapshot_with_portfolio_data(inspect_snap, data)
                holdings_inspect = snapshot_holdings_df(enriched_inspect)
                cmeta1, cmeta2, cmeta3 = st.columns(3, gap="small")
                cmeta1.metric("Valore strumenti", fmt_eur_it(enriched_inspect.get("total_value"), 2))
                cmeta2.metric("Costo", fmt_eur_it(enriched_inspect.get("total_cost"), 2))
                cmeta3.metric("P/L", fmt_eur_it(enriched_inspect.get("total_pl"), 2, signed=True))
                if not holdings_inspect.empty:
                    inspect_table = holdings_inspect.rename(
                        columns={
                            "ticker": "Ticker",
                            "strumento": "Strumento",
                            "categoria": "Categoria",
                            "market_value": "Controvalore",
                            "cost": "Costo",
                            "pl_eur": "P/L",
                            "weight": "Peso",
                        }
                    )
                    inspect_cols = [col for col in ["Ticker", "Strumento", "Categoria", "Controvalore", "Costo", "P/L", "Peso"] if col in inspect_table.columns]
                    styled_inspect = inspect_table[inspect_cols].style.format({
                        "Controvalore": lambda v: fmt_eur_it(v, 2),
                        "Costo": lambda v: fmt_eur_it(v, 2),
                        "P/L": lambda v: fmt_eur_it(v, 2, signed=True),
                        "Peso": lambda v: fmt_pct_it(v, 2),
                    }).map(color_pl, subset=["P/L"])
                    render_styled_table(styled_inspect, height="content", static=True)
                render_json_popover("Mostra JSON tecnico dello snapshot", enriched_inspect)

                _section_line()
                selected_delete = st.multiselect(
                    "Snapshot da eliminare",
                    options=list(range(len(delete_labels))),
                    format_func=lambda i: delete_labels[i],
                    key="snap_delete_multi",
                )
                if selected_delete:
                    render_danger_hint("Gli snapshot selezionati verranno rimossi dal file snapshots.json. L'operazione non modifica il portafoglio corrente.")
                confirm_delete = confirm_danger(
                    "Confermo l'eliminazione degli snapshot selezionati",
                    key="snap_delete_confirm",
                    help_text="La conferma serve a evitare cancellazioni accidentali nella gestione storica del confronto.",
                )
                if st.button("Elimina snapshot selezionati", width="stretch", key="snap_delete_btn", disabled=(not confirm_delete or not selected_delete)):
                    updated_state = load_snapshots()
                    deleted_count = 0
                    selected_ids = {
                        str(snapshots_state.get("snapshots", [])[idx].get("snapshot_id"))
                        for idx in selected_delete
                        if idx < len(snapshots_state.get("snapshots", []))
                    }
                    for selected_id in selected_ids:
                        updated_state, deleted = delete_snapshot_by_id(updated_state, selected_id)
                        deleted_count += int(bool(deleted))
                    if deleted_count:
                        save_snapshots(updated_state)
                        queue_success(f"Eliminati {deleted_count} snapshot.")
                        st.session_state.pop("confronto_selection", None)
                        invalidate_portfolio_cache("snapshot eliminati")
                        st.rerun()
                    else:
                        st.error("Nessuno snapshot eliminato.")

            _section_line()
            render_section_title(
                "Selezione confronto",
                comment="Scegli due snapshot obbligatori e, se vuoi, un terzo momento intermedio o finale. Le sezioni sotto si aggiornano solo dopo il click.",
                gap_after="sm",
            )
            snap_labels = (snaps_df['Etichetta'].astype(str) + " - " + snaps_df['Data'].astype(str)).tolist()
            idx_a = st.selectbox(t(settings, "comparison.snapshot_a", "Snapshot A"), range(len(snap_labels)), format_func=lambda i: snap_labels[i], key="cmp_a")
            idx_b = st.selectbox(t(settings, "comparison.snapshot_b", "Snapshot B"), range(len(snap_labels)), index=min(1, len(snap_labels)-1), format_func=lambda i: snap_labels[i], key="cmp_b")
            use_third = st.checkbox("Snapshot C", value=False, key="cmp_enable_c")
            idx_c = None
            if use_third:
                idx_c = st.selectbox("Snapshot C", range(len(snap_labels)), index=min(2, len(snap_labels)-1), format_func=lambda i: snap_labels[i], key="cmp_c")
            invalid_selection = idx_a == idx_b or (use_third and idx_c in {idx_a, idx_b})
            compare_btn = st.button("Confronta snapshot", width="stretch", key="cmp_run", disabled=(invalid_selection or len(snap_labels) < 2))
            if compare_btn:
                payload = {"idx_a": int(idx_a), "idx_b": int(idx_b), "use_third": bool(use_third)}
                if use_third and idx_c is not None:
                    payload["idx_c"] = int(idx_c)
                st.session_state["confronto_selection"] = payload

            selection = st.session_state.get("confronto_selection")
            if selection and selection.get("idx_a") < len(snap_labels) and selection.get("idx_b") < len(snap_labels):
                idx_a = int(selection["idx_a"])
                idx_b = int(selection["idx_b"])
                idx_c = selection.get("idx_c") if selection.get("use_third") else None
                if idx_a == idx_b or (idx_c in {idx_a, idx_b}):
                    st.info(t(settings, "comparison.select_two", "Seleziona due snapshot diversi per confrontarli."))
                    back_to_top(show_prev=True, show_next=True, nav_key="confronto")
                    return

                snap_a = snapshots_state.get("snapshots", [])[idx_a]
                snap_b = snapshots_state.get("snapshots", [])[idx_b]
                selected_snapshots = [snap_a, snap_b]
                if idx_c is not None and int(idx_c) < len(snap_labels):
                    selected_snapshots.append(snapshots_state.get("snapshots", [])[int(idx_c)])
                    selected_snapshots = sorted(selected_snapshots, key=lambda item: str(item.get("created_at", "")))
                selected_snapshots = enrich_snapshots_with_portfolio_data(selected_snapshots, data)
                snapshot_names = build_snapshot_display_names(selected_snapshots)
                snap_a = selected_snapshots[0]
                snap_b = selected_snapshots[-1]
                comparison = compare_snapshots(snap_a, snap_b)
                metrics_df = comparison["metrics"]
                category_df = comparison["categories"]
                holdings_df = comparison["holdings"]
                contributors_df = comparison["contributors"]
                metrics_timeline_df = build_multi_snapshot_metrics_df(selected_snapshots, snapshot_names=snapshot_names)
                categories_timeline_df = build_multi_snapshot_categories_df(selected_snapshots, snapshot_names=snapshot_names)
                metrics_wide_df = build_multi_snapshot_metrics_wide_df(selected_snapshots, snapshot_names=snapshot_names)
                categories_value_wide_df = build_multi_snapshot_categories_wide_df(selected_snapshots, value_col="Valore", snapshot_names=snapshot_names)
                categories_weight_wide_df = build_multi_snapshot_categories_wide_df(selected_snapshots, value_col="Peso", snapshot_names=snapshot_names)
                holdings_wide_df = build_multi_snapshot_holdings_wide_df(selected_snapshots, snapshot_names=snapshot_names)
                is_multi = len(selected_snapshots) == 3
                interval_activities = []
                for left_idx in range(len(selected_snapshots) - 1):
                    left_snap = selected_snapshots[left_idx]
                    right_snap = selected_snapshots[left_idx + 1]
                    left_dt = snapshot_datetime(left_snap)
                    right_dt = snapshot_datetime(right_snap)
                    activity = build_period_activity(
                        data,
                        left_dt.date() if left_dt is not None else None,
                        right_dt.date() if right_dt is not None else None,
                        include_start=False,
                    )
                    interval_activities.append(
                        {
                            "label": f"{snapshot_names[left_idx]} -> {snapshot_names[left_idx + 1]}",
                            "summary": activity.get("summary", {}),
                            "by_instrument": activity.get("by_instrument", pd.DataFrame()),
                            "event_log": activity.get("event_log", pd.DataFrame()),
                        }
                    )

                _section_line()
                render_section_title(
                    "Riepilogo differenze",
                    comment="Questi KPI leggono il cambiamento complessivo tra il primo e l'ultimo snapshot selezionato.",
                    gap_after="sm",
                )
                metric_map = {row["Voce"]: row for _, row in metrics_df.iterrows()}
                delta_assets = float(metric_map.get("Patrimonio totale", {}).get("Delta", 0.0))
                delta_pl_cmp = float(metric_map.get("P/L", {}).get("Delta", 0.0))
                delta_return = float(metric_map.get("Rendimento", {}).get("Delta", 0.0))
                delta_cash = float(metric_map.get("Liquidita", {}).get("Delta", 0.0))
                m1, m2, m3, m4 = st.columns(4, gap="small")
                with m1:
                    kpi_card("Patrimonio", fmt_eur_it(metric_map.get("Patrimonio totale", {}).get("B", 0), 2), fmt_eur_it(delta_assets, 2, signed=True), accent=theme.color_blue, value_color=theme.color_green if delta_assets >= 0 else theme.color_red)
                with m2:
                    kpi_card(t(settings, "comparison.delta_pl", "Delta P/L"), fmt_eur_it(delta_pl_cmp, 2, signed=True), t(settings, "comparison.delta_note", "Differenza tra snapshot"), accent=theme.color_green if delta_pl_cmp >= 0 else theme.color_red, value_color=theme.color_green if delta_pl_cmp >= 0 else theme.color_red)
                with m3:
                    kpi_card("Delta rendimento", fmt_pct_it(delta_return, 2, signed=True), "Variazione P/L percentuale", accent=theme.color_orange, value_color=theme.color_green if delta_return >= 0 else theme.color_red)
                with m4:
                    kpi_card("Liquidita", fmt_eur_it(metric_map.get("Liquidita", {}).get("B", 0), 2), fmt_eur_it(delta_cash, 2, signed=True), accent=theme.color_blue)

                if comparison["summary"]:
                    summary_notes_html = "".join(f"<li>{note}</li>" for note in comparison["summary"])
                    vertical_gap("sm")
                    legend_block(
                        "<div style='font-size:0.86rem !important; line-height:1.60 !important;'>"
                        "<span style='font-size:0.86rem !important; font-weight:700;'>Lettura sintetica</span>"
                        f"<ul style='margin:6px 0 0 18px; padding:0; font-size:0.86rem !important; line-height:1.60 !important;'>{summary_notes_html}</ul>"
                        "</div>"
                    )

                _section_line()
                render_section_title(
                    "Evoluzione tra i momenti",
                    comment=f"Benchmark attivo: {benchmark_label}. Qui leggi come si muovono patrimonio, P/L e categorie lungo i momenti selezionati.",
                    gap_after="sm",
                )
                snap_a_label = snapshot_names[0]
                snap_b_label = snapshot_names[-1]
                fig_cmp = build_snapshot_comparison_time_chart(category_df.rename(columns={"Delta peso": "Delta"}), snap_a_label, snap_b_label, theme)
                fig_delta = build_snapshot_category_delta_chart(category_df, theme)
                fig_contrib = build_snapshot_contributors_chart(contributors_df, theme)
                fig_assets_timeline = build_snapshot_metric_timeline_chart(metrics_timeline_df, "Patrimonio totale", "confronto_assets_timeline", theme)
                fig_pl_timeline = build_snapshot_metric_timeline_chart(metrics_timeline_df, "P/L", "confronto_pl_timeline", theme)
                fig_cat_value_timeline = build_snapshot_category_timeline_chart(categories_timeline_df, "Valore", "confronto_category_value_timeline", theme)
                fig_cat_weight_timeline = build_snapshot_category_timeline_chart(categories_timeline_df, "Peso", "confronto_category_weight_timeline", theme)
                fig_cat_value_grouped = build_multi_snapshot_category_grouped_chart(categories_timeline_df, "Valore", "confronto_category_value_grouped", theme)
                fig_cat_weight_grouped = build_multi_snapshot_category_grouped_chart(categories_timeline_df, "Peso", "confronto_category_weight_grouped", theme)
                fig_pl_delta = build_snapshot_pl_delta_chart(holdings_df, theme)
                fig_holdings_value_grouped = build_multi_snapshot_holdings_grouped_chart(holdings_wide_df, "Valore", "confronto_holding_value_grouped", theme)
                fig_holdings_pl_grouped = build_multi_snapshot_holdings_grouped_chart(holdings_wide_df, "P/L", "confronto_holding_pl_grouped", theme)
                fig_value_decomposition = build_snapshot_value_decomposition_chart(holdings_df, theme)
                fig_return_delta = build_snapshot_return_delta_chart(holdings_df, theme)
                fig_multi_pl_delta = None
                fig_multi_return_delta = None
                if is_multi:
                    first_label = snapshot_names[0]
                    last_label = snapshot_names[-1]
                    fig_multi_pl_delta = build_multi_snapshot_delta_bar_chart(
                        holdings_wide_df,
                        "Delta P/L complessivo",
                        "confronto_multi_delta_pl",
                        theme,
                        title=f"<b>Delta P/L complessivo ({first_label} -> {last_label})</b>",
                        percent=False,
                    )
                    fig_multi_return_delta = build_multi_snapshot_delta_bar_chart(
                        holdings_wide_df,
                        "Delta rendimento complessivo",
                        "confronto_multi_delta_return",
                        theme,
                        title=f"<b>Delta rendimento complessivo ({first_label} -> {last_label})</b>",
                        percent=True,
                    )
                for fig in (fig_value_decomposition, fig_holdings_value_grouped):
                    try:
                        fig.update_layout(height=440)
                    except Exception:
                        pass
                try:
                    fig_holdings_value_grouped.update_layout(title={"text": "<b>Controvalore strumenti tra snapshot</b>"})
                except Exception:
                    pass
                has_value_decomposition = False
                if not holdings_df.empty and {"Delta costo", "Delta P/L"}.issubset(set(holdings_df.columns)):
                    has_value_decomposition = bool(
                        (
                            pd.to_numeric(holdings_df["Delta costo"], errors="coerce").fillna(0.0).abs()
                            + pd.to_numeric(holdings_df["Delta P/L"], errors="coerce").fillna(0.0).abs()
                        ).gt(1e-9).any()
                    )
                if has_value_decomposition:
                    try:
                        has_value_decomposition = len(getattr(fig_value_decomposition, "data", []) or []) > 0
                    except Exception:
                        has_value_decomposition = False

                cfig0a, cfig0b = st.columns(2, gap="medium")
                with cfig0a:
                    st.plotly_chart(fig_assets_timeline, width="stretch", config={"displayModeBar": False})
                with cfig0b:
                    st.plotly_chart(fig_pl_timeline, width="stretch", config={"displayModeBar": False})

                cfig1, cfig2 = st.columns(2, gap="medium")
                with cfig1:
                    st.plotly_chart(fig_cat_weight_grouped if is_multi else fig_cmp, width="stretch", config={"displayModeBar": False})
                with cfig2:
                    st.plotly_chart(fig_cat_value_grouped if is_multi else fig_delta, width="stretch", config={"displayModeBar": False})

                cfig3, cfig4 = st.columns(2, gap="medium")
                with cfig3:
                    st.plotly_chart(fig_cat_value_timeline, width="stretch", config={"displayModeBar": False})
                with cfig4:
                    st.plotly_chart(fig_cat_weight_timeline, width="stretch", config={"displayModeBar": False})

                _section_line()
                render_section_title(
                    "Strumenti: controvalore",
                    comment="Qui separiamo il puro valore economico dal risultato: quanto hai investito in piu e quanto invece e cambiato per effetto del P/L.",
                    gap_after="sm",
                )
                cfig5, cfig6 = st.columns(2, gap="medium")
                with cfig5:
                    st.plotly_chart(fig_holdings_value_grouped if not is_multi else fig_contrib, width="stretch", config={"displayModeBar": False})
                with cfig6:
                    st.plotly_chart((fig_value_decomposition if has_value_decomposition else fig_contrib) if not is_multi else fig_cat_value_grouped, width="stretch", config={"displayModeBar": False})

                _section_line()
                render_section_title(
                    "Strumenti: P/L",
                    comment=(
                        "Con tre snapshot il primo grafico confronta il P/L di A, B e C; il secondo riassume il delta complessivo tra il primo e l'ultimo momento."
                        if is_multi
                        else "Qui guardi il risultato economico e la variazione di rendimento per capire se uno strumento e migliorato o peggiorato oltre ai semplici versamenti."
                    ),
                    gap_after="sm",
                )
                cfig7, cfig8 = st.columns(2, gap="medium")
                with cfig7:
                    st.plotly_chart(fig_holdings_pl_grouped, width="stretch", config={"displayModeBar": False})
                with cfig8:
                    st.plotly_chart(fig_pl_delta if not is_multi else fig_multi_return_delta, width="stretch", config={"displayModeBar": False})

                snapshot_label_map = _snapshot_letter_map(snapshot_names)
                metrics_display_df = _rename_snapshot_table_cols(metrics_wide_df, snapshot_label_map).copy().astype(object)
                for idx_row, row in metrics_display_df.iterrows():
                    is_pct_row = str(row.get("Voce")) == "Rendimento"
                    for col in metrics_display_df.columns:
                        if col == "Voce":
                            continue
                        val = row.get(col)
                        metrics_display_df.at[idx_row, col] = fmt_pct_it(val, 2, signed=("Delta" in col)) if is_pct_row else fmt_eur_it(val, 2, signed=("Delta" in col))
                _render_compact_html_table(metrics_display_df, theme=theme)

                if is_multi:
                    categories_value_display_df = _rename_snapshot_table_cols(categories_value_wide_df, snapshot_label_map)
                    categories_weight_display_df = _rename_snapshot_table_cols(categories_weight_wide_df, snapshot_label_map)
                    styled_cat = categories_value_display_df.style.format({
                        col: (lambda v, col_name=col: fmt_eur_it(v, 2, signed=("Delta" in col_name)))
                        for col in categories_value_display_df.columns if col != "Categoria"
                    })
                    styled_cat = _compact_table_styler(styled_cat)
                    if "Delta complessivo" in categories_value_display_df.columns:
                        styled_cat = styled_cat.map(color_pl, subset=["Delta complessivo"])
                    styled_cat_weights = categories_weight_display_df.style.format({
                        col: (lambda v, col_name=col: fmt_pct_it(v, 2, signed=("Delta" in col_name)))
                        for col in categories_weight_display_df.columns if col != "Categoria"
                    })
                    styled_cat_weights = _compact_table_styler(styled_cat_weights)
                    if "Delta complessivo" in categories_weight_display_df.columns:
                        styled_cat_weights = styled_cat_weights.map(color_pl, subset=["Delta complessivo"])
                else:
                    styled_cat = category_df.style.format({
                        "Valore A": lambda v: fmt_eur_it(v, 2),
                        "Valore B": lambda v: fmt_eur_it(v, 2),
                        "Delta valore": lambda v: fmt_eur_it(v, 2, signed=True),
                        "Peso A": lambda v: fmt_pct_it(v, 2),
                        "Peso B": lambda v: fmt_pct_it(v, 2),
                        "Delta peso": lambda v: fmt_pct_it(v, 2, signed=True),
                    }).apply(style_macro_cols, axis=1).map(color_pl, subset=["Delta valore", "Delta peso"])
                    styled_cat = _compact_table_styler(styled_cat)
                if is_multi:
                    _render_compact_html_table(
                        categories_value_display_df,
                        theme=theme,
                        formatters={
                            col: (lambda v, col_name=col: fmt_eur_it(v, 2, signed=("Delta" in col_name)))
                            for col in categories_value_display_df.columns if col != "Categoria"
                        },
                        signed_cols={"Delta complessivo"},
                    )
                else:
                    category_display_df = category_df.copy().astype(object)
                    for col in ("Valore A", "Valore B", "Delta valore"):
                        if col in category_display_df.columns:
                            category_display_df[col] = category_display_df[col].apply(lambda v, col_name=col: fmt_eur_it(v, 2, signed=("Delta" in col_name)))
                    for col in ("Peso A", "Peso B", "Delta peso"):
                        if col in category_display_df.columns:
                            category_display_df[col] = category_display_df[col].apply(lambda v, col_name=col: fmt_pct_it(v, 2, signed=("Delta" in col_name)))
                    _render_compact_html_table(
                        category_display_df,
                        theme=theme,
                        signed_cols={"Delta valore", "Delta peso"},
                    )
                if is_multi:
                    _render_compact_html_table(
                        categories_weight_display_df,
                        theme=theme,
                        formatters={
                            col: (lambda v, col_name=col: fmt_pct_it(v, 2, signed=("Delta" in col_name)))
                            for col in categories_weight_display_df.columns if col != "Categoria"
                        },
                        signed_cols={"Delta complessivo"},
                    )

                _section_line()
                render_section_title(
                    "Dettaglio strumenti",
                    comment="Qui separiamo quote, capitale investito e rendimento per evitare di mischiare movimenti di PAC e performance di mercato.",
                    gap_after="sm",
                )
                quote_cols = ["Ticker", "Strumento"] + [f"Quote {name}" for name in snapshot_names] + ["Delta quote complessivo", "Delta prezzo % complessivo"]
                capital_cols = ["Ticker", "Strumento", "Categoria"] + [f"Costo {name}" for name in snapshot_names] + [f"Valore {name}" for name in snapshot_names] + ["Delta costo complessivo", "Delta valore complessivo"]
                perf_cols = ["Ticker", "Strumento"] + [f"P/L {name}" for name in snapshot_names] + [f"Rendimento {name}" for name in snapshot_names] + ["Delta P/L complessivo", "Delta rendimento complessivo"]
                quote_table_df = _rename_snapshot_table_cols(holdings_wide_df[[col for col in quote_cols if col in holdings_wide_df.columns]].copy(), snapshot_label_map)
                capital_table_df = _rename_snapshot_table_cols(holdings_wide_df[[col for col in capital_cols if col in holdings_wide_df.columns]].copy(), snapshot_label_map)
                perf_table_df = _rename_snapshot_table_cols(holdings_wide_df[[col for col in perf_cols if col in holdings_wide_df.columns]].copy(), snapshot_label_map)

                styled_quotes = quote_table_df.style.format({
                    col: (lambda v, col_name=col: fmt_pct_it(v, 2, signed=True) if "%" in col_name else (fmt_num_it(v, 4, signed=True) if "Delta" in col_name else fmt_qty_it(v, 4)))
                    for col in quote_table_df.columns if col not in {"Ticker", "Strumento"}
                })
                styled_quotes = _compact_table_styler(styled_quotes)
                if "Delta quote complessivo" in quote_table_df.columns:
                    styled_quotes = styled_quotes.map(color_pl, subset=["Delta quote complessivo"])
                if "Delta prezzo % complessivo" in quote_table_df.columns:
                    styled_quotes = styled_quotes.map(color_pl, subset=["Delta prezzo % complessivo"])

                styled_capital = capital_table_df.style.format({
                    col: (lambda v, col_name=col: fmt_eur_it(v, 2, signed=("Delta" in col_name)))
                    for col in capital_table_df.columns if col not in {"Ticker", "Strumento", "Categoria"}
                })
                styled_capital = _compact_table_styler(styled_capital)
                for subset_col in ("Delta costo complessivo", "Delta valore complessivo"):
                    if subset_col in capital_table_df.columns:
                        styled_capital = styled_capital.map(color_pl, subset=[subset_col])

                styled_perf = perf_table_df.style.format({
                    col: (lambda v, col_name=col: fmt_pct_it(v, 2, signed=("Delta" in col_name)) if "Rendimento" in col_name else fmt_eur_it(v, 2, signed=True))
                    for col in perf_table_df.columns if col not in {"Ticker", "Strumento"}
                })
                styled_perf = _compact_table_styler(styled_perf)
                for subset_col in ("Delta P/L complessivo", "Delta rendimento complessivo"):
                    if subset_col in perf_table_df.columns:
                        styled_perf = styled_perf.map(color_pl, subset=[subset_col])

                render_section_title(
                    "Quote e prezzi",
                    comment="Serve a capire se e cambiata la posizione: piu quote, meno quote, nuovi ingressi o vendite parziali.",
                    gap_after="sm",
                )
                _render_compact_html_table(
                    quote_table_df,
                    theme=theme,
                    formatters={
                        col: (lambda v, col_name=col: fmt_pct_it(v, 2, signed=True) if "%" in col_name else (fmt_num_it(v, 4, signed=True) if "Delta" in col_name else fmt_qty_it(v, 4)))
                        for col in quote_table_df.columns if col not in {"Ticker", "Strumento"}
                    },
                    signed_cols={"Delta quote complessivo", "Delta prezzo % complessivo"},
                )
                render_section_title(
                    "Capitale e controvalore",
                    comment="Qui distingui il capitale investito dal valore di mercato finale.",
                    gap_after="sm",
                )
                _render_compact_html_table(
                    capital_table_df,
                    theme=theme,
                    formatters={
                        col: (lambda v, col_name=col: fmt_eur_it(v, 2, signed=("Delta" in col_name)))
                        for col in capital_table_df.columns if col not in {"Ticker", "Strumento", "Categoria"}
                    },
                    signed_cols={"Delta costo complessivo", "Delta valore complessivo"},
                )
                render_section_title(
                    "P/L e rendimento",
                    comment="Qui guardi il risultato economico e la resa percentuale per strumento.",
                    gap_after="sm",
                )
                _render_compact_html_table(
                    perf_table_df,
                    theme=theme,
                    formatters={
                        col: (lambda v, col_name=col: fmt_pct_it(v, 2, signed=("Delta" in col_name)) if "Rendimento" in col_name else fmt_eur_it(v, 2, signed=True))
                        for col in perf_table_df.columns if col not in {"Ticker", "Strumento"}
                    },
                    signed_cols={"Delta P/L complessivo", "Delta rendimento complessivo"},
                )

                if not holdings_df.empty and not is_multi:
                    detail_cols = [
                        "Ticker", "Strumento", "Categoria",
                        "Quote A", "Quote B", "Delta quote",
                        "Prezzo A", "Prezzo B", "Delta prezzo %",
                        "Delta peso",
                    ]
                    detail_df = holdings_df[[col for col in detail_cols if col in holdings_df.columns]].copy()
                    styled_detail = detail_df.style.format({
                        "Quote A": lambda v: fmt_qty_it(v, 4),
                        "Quote B": lambda v: fmt_qty_it(v, 4),
                        "Delta quote": lambda v: fmt_num_it(v, 4, signed=True),
                        "Prezzo A": lambda v: fmt_eur_it(v, 4),
                        "Prezzo B": lambda v: fmt_eur_it(v, 4),
                        "Delta prezzo %": lambda v: fmt_pct_it(v, 2, signed=True),
                        "Delta peso": lambda v: fmt_pct_it(v, 2, signed=True),
                    })
                    styled_detail = _compact_table_styler(styled_detail)
                    styled_detail = styled_detail.map(color_pl, subset=[col for col in ["Delta quote", "Delta prezzo %", "Delta peso"] if col in detail_df.columns])
                    render_section_title(
                        "Variazioni dirette A -> B",
                        comment="Vista compatta del confronto puro tra i due estremi selezionati.",
                        gap_after="sm",
                    )
                    _render_compact_html_table(
                        detail_df,
                        theme=theme,
                        formatters={
                            "Quote A": lambda v: fmt_qty_it(v, 4),
                            "Quote B": lambda v: fmt_qty_it(v, 4),
                            "Delta quote": lambda v: fmt_num_it(v, 4, signed=True),
                            "Prezzo A": lambda v: fmt_eur_it(v, 4),
                            "Prezzo B": lambda v: fmt_eur_it(v, 4),
                            "Delta prezzo %": lambda v: fmt_pct_it(v, 2, signed=True),
                            "Delta peso": lambda v: fmt_pct_it(v, 2, signed=True),
                        },
                        signed_cols={"Delta quote", "Delta prezzo %", "Delta peso"},
                    )

                if interval_activities:
                    _section_line()
                    render_section_title(
                        "Movimenti tra snapshot",
                        comment="Questa parte spiega cosa hai fatto davvero tra un momento e l'altro: acquisti, vendite, cedole, PAC e variazioni di cassa.",
                        gap_after="sm",
                    )
                    for interval in interval_activities:
                        summary = interval.get("summary", {})
                        st.markdown(f"**{interval.get('label', '')}**")
                        ia1, ia2, ia3, ia4 = st.columns(4, gap="small")
                        ia1.metric("Acquisti", fmt_eur_it(summary.get("buy_net_outflow"), 2))
                        ia2.metric("Vendite/rimborsi", fmt_eur_it(summary.get("sell_net_inflow"), 2))
                        ia3.metric("Cedole/dividendi", fmt_eur_it(summary.get("income_net"), 2))
                        ia4.metric("Saldo netto", fmt_eur_it(summary.get("net_cash_delta"), 2, signed=True))
                        interval_df = interval.get("by_instrument", pd.DataFrame())
                        if isinstance(interval_df, pd.DataFrame) and not interval_df.empty:
                            interval_table = interval_df.head(16).style.format({
                                "Operazioni": lambda v: fmt_num_it(v, 0),
                                "Quote acquistate": lambda v: fmt_qty_it(v, 4),
                                "Quote vendute": lambda v: fmt_qty_it(v, 4),
                                "Delta quote": lambda v: fmt_num_it(v, 4, signed=True),
                                "Spesa acquisti": lambda v: fmt_eur_it(v, 2),
                                "Incasso vendite": lambda v: fmt_eur_it(v, 2),
                                "Cedole/dividendi netti": lambda v: fmt_eur_it(v, 2),
                                "Commissioni": lambda v: fmt_eur_it(v, 2),
                                "Imposte": lambda v: fmt_eur_it(v, 2),
                                "Saldo netto": lambda v: fmt_eur_it(v, 2, signed=True),
                            })
                            interval_table = interval_table.map(color_pl, subset=[col for col in ["Delta quote", "Saldo netto"] if col in interval_df.columns])
                            _render_compact_html_table(
                                interval_df,
                                theme=theme,
                                formatters={
                                    "Operazioni": lambda v: fmt_num_it(v, 0),
                                    "Quote acquistate": lambda v: fmt_qty_it(v, 4),
                                    "Quote vendute": lambda v: fmt_qty_it(v, 4),
                                    "Delta quote": lambda v: fmt_num_it(v, 4, signed=True),
                                    "Spesa acquisti": lambda v: fmt_eur_it(v, 2),
                                    "Incasso vendite": lambda v: fmt_eur_it(v, 2),
                                    "Cedole/dividendi netti": lambda v: fmt_eur_it(v, 2),
                                    "Commissioni": lambda v: fmt_eur_it(v, 2),
                                    "Imposte": lambda v: fmt_eur_it(v, 2),
                                    "Saldo netto": lambda v: fmt_eur_it(v, 2, signed=True),
                                },
                                signed_cols={"Delta quote", "Saldo netto"},
                            )

                export_df = holdings_wide_df.copy() if is_multi else holdings_df.copy()
                numeric_cols = export_df.select_dtypes(include=["number"]).columns
                if len(numeric_cols) > 0:
                    export_df.loc[:, numeric_cols] = export_df.loc[:, numeric_cols].round(export_decimals)
                csv_bytes = export_df.to_csv(index=False).encode("utf-8-sig")
                comparison_figures = {
                    "assets_timeline": fig_assets_timeline,
                    "pl_timeline": fig_pl_timeline,
                    "left_main": fig_cat_weight_grouped if is_multi else fig_cmp,
                    "right_main": fig_cat_value_grouped if is_multi else fig_delta,
                    "value_detail": fig_contrib if is_multi else (fig_value_decomposition if has_value_decomposition else fig_holdings_value_grouped),
                    "perf_detail": fig_return_delta if is_multi else fig_pl_delta,
                }
                comparison_html = build_comparison_report_html(
                    title="Confronto snapshot portafoglio",
                    generated_at=datetime.now(),
                    snapshot_names=snapshot_names,
                    metric_map=metric_map,
                    summary_notes=comparison["summary"],
                    metrics_wide_df=metrics_wide_df,
                    categories_value_wide_df=categories_value_wide_df,
                    categories_weight_wide_df=categories_weight_wide_df,
                    holdings_wide_df=holdings_wide_df,
                    interval_activities=interval_activities,
                    figures=comparison_figures,
                ).encode("utf-8")
                json_bytes = json.dumps(
                    {
                        "snapshot_a": snap_a,
                        "snapshot_b": snap_b,
                        "selected_snapshots": selected_snapshots,
                        "metrics_timeline": metrics_timeline_df.to_dict("records"),
                        "metrics": metrics_df.to_dict("records"),
                        "categories": category_df.to_dict("records"),
                        "categories_timeline": categories_timeline_df.to_dict("records"),
                        "holdings": holdings_df.to_dict("records"),
                        "holdings_wide": holdings_wide_df.to_dict("records"),
                        "interval_activities": [
                            {
                                "label": item.get("label"),
                                "summary": item.get("summary", {}),
                                "by_instrument": item.get("by_instrument", pd.DataFrame()).to_dict("records") if isinstance(item.get("by_instrument"), pd.DataFrame) else [],
                            }
                            for item in interval_activities
                        ],
                        "benchmark": benchmark_cfg,
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ).encode("utf-8")
                c61, c62, c63 = st.columns(3)
                if preferred_export == "json":
                    c61.download_button("Esporta confronto HTML", data=comparison_html, file_name=build_comparison_report_filename("html"), mime="text/html", width="stretch")
                    c62.download_button(t(settings, "comparison.export_json", "Esporta confronto JSON"), data=json_bytes, file_name="confronto_portafogli.json", mime="application/json", width="stretch")
                    c63.download_button(t(settings, "comparison.export_csv", "Esporta confronto CSV"), data=csv_bytes, file_name="confronto_portafogli.csv", mime="text/csv", width="stretch")
                else:
                    c61.download_button("Esporta confronto HTML", data=comparison_html, file_name=build_comparison_report_filename("html"), mime="text/html", width="stretch")
                    c62.download_button(t(settings, "comparison.export_csv", "Esporta confronto CSV"), data=csv_bytes, file_name="confronto_portafogli.csv", mime="text/csv", width="stretch")
                    c63.download_button(t(settings, "comparison.export_json", "Esporta confronto JSON"), data=json_bytes, file_name="confronto_portafogli.json", mime="application/json", width="stretch")
            else:
                st.info("Seleziona due snapshot diversi, aggiungi facoltativamente un terzo momento e premi Confronta snapshot.")
        else:
            st.info(t(settings, "comparison.none", "Nessuno snapshot disponibile. Crea il primo snapshot corrente."))
        back_to_top(show_prev=True, show_next=True, nav_key="confronto")
