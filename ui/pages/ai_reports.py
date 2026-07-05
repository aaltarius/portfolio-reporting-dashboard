# ui/pages/ai_reports.py
"""Tab Report AI: libreria report salvati + diff tra due analisi."""
from __future__ import annotations

from types import SimpleNamespace

import streamlit as st

from core.ai_analysis import AI_CALL_COUNT_KEY, call_gemini_diff, delete_ai_report, load_ai_reports
from core.formatting import fmt_dt_it
from ui.components import legend_block, render_section_title, vertical_gap


def render_ai_reports(ctx: SimpleNamespace, *, api_key: str, model: str) -> None:
    """Libreria report AI salvati e confronto diff tra due analisi."""
    reports = load_ai_reports()

    if not reports:
        legend_block(
            "Nessun report salvato. Vai alla tab Analisi, esegui un'analisi e clicca «Salva report».",
            variant="bottom",
        )
        return

    render_section_title("Report salvati", icon="analysis")
    vertical_gap("xs")

    for report in reports:
        filename = report.get("_filename", "")
        saved_at = report.get("saved_at", filename.replace(".json", "").replace("_", " "))
        mdl = report.get("model", "—")
        n = len(report.get("payload", {}).get("instruments", []))
        cv = report.get("payload", {}).get("totale_controvalore_eur", 0)

        with st.expander(f"📄 {fmt_dt_it(saved_at)} · {mdl} · {n} strumenti · € {cv:,.0f}", expanded=False):
            st.markdown(report.get("analysis_text", "_Testo non disponibile._"))

            sd = report.get("structured_data", {})
            if sd:
                with st.expander("Dati strutturati (JSON)", expanded=False):
                    st.json(sd)

            col_del, col_space = st.columns([1, 4])
            with col_del:
                if st.button("Elimina", key=f"_ai_del_{filename}", type="secondary"):
                    delete_ai_report(filename)
                    st.success("Report eliminato.")
                    st.rerun()

    vertical_gap("sm")
    render_section_title("Confronta due report (Diff AI)", icon="analysis")
    legend_block(
        "Seleziona due report per chiedere a Gemini di confrontarli e identificare "
        "i cambiamenti nel portafoglio e nel giudizio dell'AI.",
        variant="bottom",
    )
    vertical_gap("xs")

    report_options = {
        r.get("saved_at", r.get("_filename", "")): r for r in reports
    }
    option_keys = list(report_options.keys())

    if len(option_keys) < 2:
        st.info("Servono almeno 2 report salvati per il confronto.")
        return

    col_a, col_b = st.columns(2)
    with col_a:
        sel_a = st.selectbox("Report A (più vecchio)", options=option_keys, index=len(option_keys) - 1, format_func=fmt_dt_it, key="_ai_diff_a")
    with col_b:
        sel_b = st.selectbox("Report B (più recente)", options=option_keys, index=0, format_func=fmt_dt_it, key="_ai_diff_b")

    if st.button("Confronta con AI", type="primary", key="_ai_diff_btn", width="stretch"):
        if sel_a == sel_b:
            st.warning("Seleziona due report diversi.")
            return
        text_a = report_options[sel_a].get("analysis_text", "")
        text_b = report_options[sel_b].get("analysis_text", "")
        with st.spinner("Gemini sta confrontando le analisi…"):
            try:
                diff_result = call_gemini_diff(text_a, text_b, api_key, model=model)
                st.session_state["_ai_diff_result"] = diff_result
                st.session_state[AI_CALL_COUNT_KEY] = st.session_state.get(AI_CALL_COUNT_KEY, 0) + 1
            except RuntimeError as exc:
                st.error(str(exc))

    diff_result = st.session_state.get("_ai_diff_result")
    if diff_result:
        vertical_gap("xs")
        render_section_title("Risultato confronto", icon="analysis")
        st.markdown(diff_result)
