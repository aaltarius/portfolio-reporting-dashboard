"""
ui/pages/summary.py — Tab Summary (t5): Report generator
Pure form-based rendering with zero video visualizations.
Generates PDF/HTML reports for download (no KPI cards, no graphs on-screen).
"""
import html
import json
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any

import pandas as pd
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from core.cache import record_cache_decision
from core.finance import build_portfolio_summary_payload
from core.render_profiler import profile_step
from core.services.period_activity import build_period_activity
from core.services.report_builder import (
    apply_report_options,
    build_portfolio_report_html,
    build_report_filename,
    build_report_preview,
    default_report_options,
    report_payload_json,
    resolve_period,
)
from core.services.report_archive import (
    delete_summary_report,
    load_summary_report_manifest,
    read_summary_report_file,
    save_summary_report_archive,
)
from ui.charts.summary import build_summary_figures
from ui.charts.tables import color_pl
from ui.formatting import fmt_dt_it, fmt_eur_it, fmt_pct_it, fmt_num_it, fmt_qty_it
from ui.i18n import t
from ui.components import render_section_title, back_to_top, should_render_section, legend_block, vertical_gap, render_styled_table
from ui.page_chrome import render_page_intro as render_page_intro_shared, render_section_line as render_section_line_shared
from ui.theme import get_theme_context

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


def _section_line() -> None:
    return render_section_line_shared()


def _fmt_archive_datetime(value: Any) -> str:
    text = str(value or "")
    if not text:
        return "n/d"
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return text


def _fmt_archive_period(entry: dict[str, Any]) -> str:
    label = str(entry.get("period_label") or "ALL")
    start = str(entry.get("period_start") or "")
    end = str(entry.get("period_end") or "")
    if start or end:
        return f"{label} ({start or 'inizio'} - {end or 'oggi'})"
    return label


def _render_report_archive() -> None:
    reports = load_summary_report_manifest(limit=8)
    st.markdown(
        """
        <style>
        .report-archive-list { display:flex; flex-direction:column; gap:10px; margin-top:8px; }
        .report-archive-card { padding:12px 14px; border:1px solid #d8dee8; border-radius:10px; background:#ffffff; }
        .report-archive-title { font-weight:700; color:#111827; font-size:.93rem; }
        .report-archive-meta { margin-top:3px; color:#64748b; font-size:.80rem; line-height:1.45; }
        .report-archive-kpi { margin-top:6px; color:#334155; font-size:.82rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    if not reports:
        st.caption("Nessun report archiviato. Il prossimo report generato verra salvato automaticamente qui.")
        return

    st.caption("Ultimi report salvati localmente. Riprendi un report per riattivare i pulsanti di download HTML/JSON.")
    st.markdown("<div class='report-archive-list'>", unsafe_allow_html=True)
    for entry in reports:
        report_id = str(entry.get("id") or "")
        title = html.escape(str(entry.get("filename") or report_id or "Report"))
        saved_at = html.escape(_fmt_archive_datetime(entry.get("saved_at")))
        period = html.escape(_fmt_archive_period(entry))
        portfolio_name = html.escape(str(entry.get("portfolio_name") or "Portafoglio"))
        total_value = fmt_eur_it(entry.get("total_market_value"), 2)
        total_pl = fmt_eur_it(entry.get("total_pl"), 2, signed=True)
        st.markdown(
            f"""
            <div class="report-archive-card">
              <div class="report-archive-title">{title}</div>
              <div class="report-archive-meta">{saved_at} · {portfolio_name} · Periodo: {period}</div>
              <div class="report-archive-kpi">Valore strumenti: <strong>{total_value}</strong> · P/L: <strong>{total_pl}</strong></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        col_restore, col_delete, col_spacer = st.columns([1, 1, 4], gap="small")
        with col_restore:
            if st.button("Riprendi", key=f"summary_archive_restore_{report_id}", width="stretch"):
                html_bytes = read_summary_report_file(report_id, "html")
                json_bytes = read_summary_report_file(report_id, "json")
                if html_bytes:
                    st.session_state["summary_report_output"] = {
                        "html": html_bytes,
                        "json": json_bytes,
                        "filename": str(entry.get("filename") or entry.get("html_file") or f"{report_id}.html"),
                        "generated_at": _fmt_archive_datetime(entry.get("saved_at")),
                        "archive_id": report_id,
                    }
                    st.success("Report ripreso dall'archivio.")
                    st.rerun()
                else:
                    st.warning("File HTML non trovato per questo report archiviato.")
        with col_delete:
            if st.button("Elimina", key=f"summary_archive_delete_{report_id}", width="stretch"):
                delete_summary_report(report_id)
                current = st.session_state.get("summary_report_output") or {}
                if current.get("archive_id") == report_id:
                    st.session_state.pop("summary_report_output", None)
                st.rerun()
        with col_spacer:
            st.empty()
    st.markdown("</div>", unsafe_allow_html=True)


def render_summary(tab: DeltaGenerator, ctx: SimpleNamespace) -> None:
    """
    Report generator interface.
    The page collects options and generates HTML/PDF-print outputs on demand.
    """
    theme = get_theme_context()
    settings = ctx.settings
    data = ctx.data

    with tab:
        report_schema_version = "summary_report_v7_operations_optional"
        if st.session_state.get("summary_report_schema_version") != report_schema_version:
            st.session_state["summary_report_schema_version"] = report_schema_version
            st.session_state.pop("summary_report_output", None)

        _render_page_intro(
            t(settings, "tab.summary", "Summary"),
            t(settings, "page_intro.summary.comment", "Genera un report HTML completo del portafoglio, pronto da scaricare e da stampare in PDF dal browser. Qui scegli solo periodo e contenuti effettivi."),
            "summary",
            theme,
        )
        st.markdown("""
        <style>
        .report-gen-preview { padding: 14px 16px; background: white; border: 1px solid #d1d5db; border-radius: 12px; margin-top: 10px; font-size: 0.90rem; line-height: 1.58; color: #374151; }
        .report-preview-list { margin: 0; padding-left: 1.05rem; }
        .report-output-box { padding: 14px 16px; border: 1px solid #d1d5db; border-radius: 12px; background: #f8fafc; }
        .report-download-gap { height: 12px; }
        </style>
        """, unsafe_allow_html=True)

        defaults = default_report_options(settings)

        with st.container():
            render_section_title(
                "Identita del report",
                comment="Il report resta sempre completo. Qui imposti solo il periodo da usare per storico, benchmark e tabelle temporali.",
                gap_after="sm"
            )
            st.caption("Output unico: HTML completo. Per il PDF usa la stampa del browser sull'HTML generato.")
            report_period = st.selectbox(
                "Periodo",
                ["1M", "3M", "6M", "YTD", "1Y", "3Y", "ALL", "Personalizzato"],
                index=6,
                key="report_period",
            )

            if report_period == "Personalizzato":
                colp1, colp2 = st.columns(2, gap="medium")
                with colp1:
                    custom_start = st.date_input("Dal", value=date(date.today().year, 1, 1), format="DD/MM/YYYY", key="report_custom_start")
                with colp2:
                    custom_end = st.date_input("Al", value=date.today(), format="DD/MM/YYYY", key="report_custom_end")
            else:
                custom_start = None
                custom_end = None
            period_start, period_end = resolve_period(report_period, custom_start, custom_end)
            preview_activity = build_period_activity(data, period_start, period_end)

        _section_line()
        with st.container():
            render_section_title(
                "Contenuti",
                comment="Attiva solo le sezioni che ti servono. Se i dati non sono disponibili, la sezione viene saltata o indicata correttamente.",
                gap_after="sm"
            )
            col_chk1, col_chk2 = st.columns(2, gap="medium")
            with col_chk1:
                st.write("**Sezioni principali**")
                include_composition = st.checkbox("Composizione portafoglio", value=True, key="report_include_composition")
                include_performance = st.checkbox("Performance", value=True, key="report_include_performance")
                include_benchmark = st.checkbox("Benchmark", value=defaults["include_benchmark"], key="report_include_benchmark")
                include_liquidity = st.checkbox("Liquidita", value=True, key="report_include_liquidity")
                include_categories_detail = st.checkbox("Dettaglio categorie", value=True, key="report_include_categories_detail")
            with col_chk2:
                st.write("**Output e dettagli**")
                include_charts = st.checkbox("Grafici", value=True, key="report_include_charts")
                include_tables = st.checkbox("Tabelle di dettaglio", value=defaults["include_tables"], key="report_include_tables")
                include_holdings = st.checkbox("Dettaglio strumenti singoli", value=True, key="report_include_holdings")
                include_period_tables = st.checkbox("Tabelle rendimenti periodici", value=True, key="report_include_period_tables")
                include_risk_overview = st.checkbox("Metriche rischio e ratio", value=True, key="report_include_risk_overview")
                include_operations = st.checkbox("Operazioni e movimenti", value=defaults["include_operations"], key="report_include_operations")
                include_income = st.checkbox("Cedole/dividendi/proventi", value=True, key="report_include_income")

        report_options = {
            "include_charts": include_charts,
            "include_tables": include_tables,
            "include_benchmark": include_benchmark,
            "include_composition": include_composition,
            "include_performance": include_performance,
            "include_operations": include_operations,
            "include_income": include_income,
            "include_liquidity": include_liquidity,
            "include_holdings": include_holdings,
            "include_categories_detail": include_categories_detail,
            "include_risk_overview": include_risk_overview,
            "include_period_tables": include_period_tables,
            "period_label": report_period,
            "period_start": period_start,
            "period_end": period_end,
        }

        _section_line()
        with st.container():
            render_section_title(
                "Anteprima",
                comment="Prima di generare il file, controlla cosa entrera nel documento.",
                gap_after="sm"
            )
            preview_dfh = getattr(ctx, "dfh_top", pd.DataFrame())
            preview_da = getattr(ctx, "da", pd.DataFrame())
            preview_cat = getattr(ctx, "category_breakdown", pd.DataFrame())
            preview_payload = {
                "category_breakdown": preview_cat.to_dict("records") if preview_cat is not None and not preview_cat.empty else [],
                "summary_history": [{"data": "preview"}] if preview_dfh is not None and not preview_dfh.empty else [],
                "benchmark_history": [{"data": "preview"}] if include_benchmark and bool((data.get("benchmark_data", {}) or {})) else [],
                "full_holdings": preview_da.to_dict("records") if preview_da is not None and not preview_da.empty else [],
                "total_market_value": getattr(ctx, "tv", None),
                "total_cost": getattr(ctx, "tc", None),
                "total_pl": getattr(ctx, "pl_totale", None),
                "period_activity": preview_activity,
            }
            preview = build_report_preview(
                preview_payload,
                report_options,
                operations_df=ctx.ops_report,
                income_items=ctx.proventi,
                liquidity=ctx.liquidita_attuale,
            )
            included_html = "".join(f"<li>{item}</li>" for item in preview["included"])
            excluded_html = "".join(f"<li>{item}</li>" for item in preview["excluded"])
            warnings_html = "".join(f"<li>{item}</li>" for item in preview["warnings"])
            st.markdown(
                f"""
                <div class="report-gen-preview">
                  <strong>Incluso</strong>
                  <ul class="report-preview-list">{included_html or "<li>Nessuna sezione principale selezionata.</li>"}</ul>
                  <br><strong>Escluso o non disponibile</strong>
                  <ul class="report-preview-list">{excluded_html or "<li>Nessuna esclusione rilevante.</li>"}</ul>
                  {("<br><strong>Attenzione</strong><ul class='report-preview-list'>" + warnings_html + "</ul>") if warnings_html else ""}
                </div>
                """,
                unsafe_allow_html=True,
            )
        _section_line()
        with st.container():
            render_section_title(
                "Genera report",
                comment="La generazione avviene solo al click. Se includi grafici, vengono riusati i builder Plotly della Summary e la cache figure quando possibile.",
                gap_after="sm"
            )
            generate = st.button("Genera report", width="stretch", key="summary_generate_report")
            if generate:
                with profile_step("Summary", "generate_configurable_report"):
                    payload = build_portfolio_summary_payload(
                        data,
                        ctx.da,
                        settings,
                        ctx.last_quotes_update,
                        ctx.proventi,
                        dfh=ctx.dfh_top,
                        portfolio_df=ctx.df,
                        liquidita=ctx.liquidita_attuale,
                    )
                    payload = apply_report_options(payload, report_options)
                    payload["period_activity"] = build_period_activity(
                        data,
                        report_options.get("period_start"),
                        report_options.get("period_end"),
                    )
                    figures = {}
                    if include_charts:
                        figures = build_summary_figures(
                            payload,
                            settings,
                            include_advanced=include_risk_overview,
                            page_mode="Report",
                        )
                    html_doc = build_portfolio_report_html(
                        payload,
                        report_options,
                        figures=figures,
                        operations_df=ctx.ops_report,
                        income_items=ctx.proventi,
                        liquidity=ctx.liquidita_attuale,
                    )
                    json_payload = dict(payload)
                    period_activity = json_payload.get("period_activity", {})
                    if isinstance(period_activity, dict):
                        json_period_activity = {}
                        for key, value in period_activity.items():
                            if isinstance(value, pd.DataFrame):
                                json_period_activity[key] = value.to_dict("records")
                            else:
                                json_period_activity[key] = value
                        json_payload["period_activity"] = json_period_activity
                    html_bytes = html_doc.encode("utf-8")
                    json_bytes = report_payload_json(json_payload, report_options)
                    filename = build_report_filename(report_options, "html")
                    archive_entry = save_summary_report_archive(
                        html_bytes=html_bytes,
                        json_bytes=json_bytes,
                        filename=filename,
                        payload=json_payload,
                        options=report_options,
                    )
                    st.session_state["summary_report_output"] = {
                        "html": html_bytes,
                        "json": json_bytes,
                        "filename": filename,
                        "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "archive_id": archive_entry.get("id"),
                    }
                    record_cache_decision(
                        "genera report summary",
                        details={
                            "event_type": "summary_report_generate",
                            "report_id": archive_entry.get("id"),
                            "filename": filename,
                            "include_charts": bool(include_charts),
                            "include_risk_overview": bool(include_risk_overview),
                            "html_bytes": len(html_bytes),
                            "json_bytes": len(json_bytes),
                            "material_change": False,
                            "changed_count": 0,
                        },
                        invalidated=False,
                        token=0,
                        force_reload=False,
                        scenario="summary_report_isolated",
                        render_scope="full_tabs",
                        dirty_flags={},
                    )

            output = st.session_state.get("summary_report_output")
            if output:
                st.markdown(
                    f"<div class='report-output-box'>Report generato: <strong>{output['generated_at']}</strong>. "
                    f"Scarica l'HTML e, se ti serve il PDF, aprilo nel browser e usa la stampa.</div>",
                    unsafe_allow_html=True,
                )
                st.markdown("<div class='report-download-gap'></div>", unsafe_allow_html=True)
                col_down1, col_down2 = st.columns(2, gap="medium")
                with col_down1:
                    st.download_button(
                        "Scarica report HTML",
                        data=output["html"],
                        file_name=output["filename"],
                        mime="text/html",
                        width="stretch",
                        key="summary_download_html",
                    )
                with col_down2:
                    st.download_button(
                        "Scarica dati report JSON",
                        data=output["json"],
                        file_name=output["filename"].replace(".html", ".json"),
                        mime="application/json",
                        width="stretch",
                        key="summary_download_json",
                    )

        _section_line()
        with st.container():
            render_section_title(
                "Archivio report",
                comment="Ogni report generato viene salvato localmente e puo essere ripreso in seguito.",
                gap_after="sm",
            )
            _render_report_archive()

        back_to_top()
