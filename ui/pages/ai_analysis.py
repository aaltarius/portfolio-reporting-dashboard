# ui/pages/ai_analysis.py
"""Tab Analisi AI: payload selector, analisi testo/avanzata, grafici strutturati, salva report."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.ai_analysis import AI_CALL_COUNT_KEY
from core.config import COLORS
from core.ai_analysis import (
    GEMINI_MODELS,
    build_gemini_prompt,
    build_portfolio_ai_payload,
    call_gemini_flash,
    call_gemini_structured,
    save_ai_report,
)
from ui.components import legend_block, render_section_title, vertical_gap

_AI_RESULT_KEY = "_ai_analysis_result_v2"

# ── Grafici strutturati ────────────────────────────────────────────────────────

def _render_instrument_scores(scores: list[dict]) -> None:
    if not scores:
        return
    render_section_title("Score strumenti (AI)", icon="analysis")
    categories = ["Rischio", "Qualità", "Diversificazione"]
    fig = go.Figure()
    for item in scores:
        fig.add_trace(go.Scatterpolar(
            r=[item.get("risk", 0), item.get("quality", 0), item.get("diversification", 0)],
            theta=categories,
            fill="toself",
            name=str(item.get("ticker", "")),
        ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 10])),
        showlegend=True,
        height=400,
        margin=dict(l=40, r=40, t=40, b=40),
    )
    st.plotly_chart(fig, width="stretch")
    legend_block("Valori 1-10 stimati dal modello AI sulla base della composizione del portafoglio. Non costituiscono valutazioni finanziarie ufficiali.", variant="bottom")


def _render_category_projections(projections: list[dict]) -> None:
    if not projections:
        return
    render_section_title("Proiezioni rendimento per categoria (AI)", icon="analysis")
    cats = [p.get("category", "") for p in projections]
    mins = [p.get("expected_return_min_pct", 0) for p in projections]
    maxs = [p.get("expected_return_max_pct", 0) for p in projections]
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Min %", x=cats, y=mins, marker_color="#5B8DEF"))
    fig.add_trace(go.Bar(name="Max %", x=cats, y=maxs, marker_color="#00D4AA"))
    fig.update_layout(
        barmode="group",
        yaxis_title="Rendimento atteso %",
        height=350,
        margin=dict(l=40, r=40, t=40, b=40),
    )
    st.plotly_chart(fig, width="stretch")
    legend_block("Stime qualitative AI basate sulla composizione storica delle categorie. Non sono previsioni finanziarie.", variant="bottom")


def _render_stress_scenarios(scenarios: list[dict]) -> None:
    if not scenarios:
        return
    render_section_title("Scenari di stress (AI)", icon="analysis")
    names = [s.get("name", "") for s in scenarios]
    impacts = [s.get("portfolio_impact_pct", 0) for s in scenarios]
    colors = [COLORS["danger"] if v < 0 else COLORS["success"] for v in impacts]
    fig = go.Figure(go.Bar(x=names, y=impacts, marker_color=colors))
    fig.update_layout(
        yaxis_title="Impatto stimato %",
        height=300,
        margin=dict(l=40, r=40, t=40, b=40),
    )
    st.plotly_chart(fig, width="stretch")
    legend_block("Scenari ipotetici stimati dal modello AI. Non sono simulazioni quantitative reali.", variant="bottom")


# ── Payload selector UI ────────────────────────────────────────────────────────

def _render_payload_selector(da: pd.DataFrame) -> tuple[list[str] | None, list[str] | None, set[str] | None]:
    """Mostra l'expander di filtro payload. Ritorna (filter_tickers, filter_categories, include_sections)."""
    all_tickers = list(da["Ticker"].dropna().unique()) if "Ticker" in da.columns else []
    all_categories = list(da["Tipo"].dropna().unique()) if "Tipo" in da.columns else []
    all_sections = ["allocation", "rebalancing", "totals"]

    with st.expander("Filtri payload (cosa inviare a Gemini)", expanded=False):
        sel_tickers = st.multiselect(
            "Filtra strumenti specifici",
            options=all_tickers,
            default=[],
            placeholder="Lascia vuoto per includere tutti",
            key="_ai_filter_tickers",
        )
        sel_cats = st.multiselect(
            "Filtra categorie",
            options=all_categories,
            default=[],
            placeholder="Lascia vuoto per includere tutte",
            key="_ai_filter_categories",
        )
        sel_sections = st.multiselect(
            "Sezioni dati incluse",
            options=all_sections,
            default=all_sections,
            key="_ai_filter_sections",
        )
        st.caption(
            "Il peso di ogni strumento è sempre relativo al portafoglio completo, anche con filtri attivi."
        )

    filter_tickers = sel_tickers if sel_tickers else None
    filter_categories = sel_cats if sel_cats else None
    include_sections = set(sel_sections) if sel_sections else None
    return filter_tickers, filter_categories, include_sections


# ── Entry point ────────────────────────────────────────────────────────────────

def render_ai_analysis(ctx: SimpleNamespace, *, api_key: str, model: str) -> None:
    """Tab Analisi: analisi one-shot con payload selector, modalità testo/avanzata, salva report."""
    da: pd.DataFrame = getattr(ctx, "da", pd.DataFrame())
    data: dict = getattr(ctx, "data", {}) or {}

    filter_tickers, filter_categories, include_sections = _render_payload_selector(da)

    analysis_mode = st.radio(
        "Modalità analisi",
        ["Testo libero", "Avanzata (JSON + grafici)"],
        horizontal=True,
        key="_ai_analysis_mode",
    )
    structured = analysis_mode == "Avanzata (JSON + grafici)"

    custom_prompt = st.text_area(
        "Prompt personalizzato (opzionale)",
        value="",
        placeholder="Lascia vuoto per usare il prompt standard.",
        height=72,
        key="_ai_custom_prompt",
    )

    if st.button("Analizza portafoglio", type="primary", key="_ai_analyze_btn", width="stretch"):
        with st.status("Analisi in corso…", expanded=True) as status:
            try:
                st.write("Costruzione payload…")
                payload = build_portfolio_ai_payload(
                    data, da,
                    filter_tickers=filter_tickers,
                    filter_categories=filter_categories,
                    include_sections=include_sections,
                )
                n = len(payload["instruments"])
                cv = payload.get("totale_controvalore_eur", 0)
                st.write(f"{n} strumenti · € {cv:,.0f}")
                st.write("Invio a Gemini…")
                prompt = build_gemini_prompt(payload, custom_prompt=custom_prompt or None, structured=structured)

                structured_data: dict = {}
                if structured:
                    structured_data = call_gemini_structured(prompt, api_key, model=model)
                    response_text = structured_data.pop("analysis_text", "")
                else:
                    response_text = call_gemini_flash(prompt, api_key, model=model)

                st.session_state[_AI_RESULT_KEY] = {
                    "text": response_text,
                    "structured_data": structured_data,
                    "n_instruments": n,
                    "totale_cv": cv,
                    "model": model,
                    "custom_prompt": custom_prompt,
                    "payload": payload,
                    "structured": structured,
                }
                st.session_state[AI_CALL_COUNT_KEY] = st.session_state.get(AI_CALL_COUNT_KEY, 0) + 1
                status.update(label="Analisi completata", state="complete", expanded=False)
            except RuntimeError as exc:
                status.update(label="Errore API", state="error", expanded=True)
                st.error(str(exc))
                return
            except Exception as exc:
                status.update(label="Errore imprevisto", state="error", expanded=True)
                st.error(f"Errore imprevisto: {exc}")
                return

    cached = st.session_state.get(_AI_RESULT_KEY)
    if not cached:
        legend_block("Clicca «Analizza portafoglio» per inviare i dati a Gemini.", variant="bottom")
        return

    st.caption(
        f"Ultima analisi: {cached['n_instruments']} strumenti · "
        f"€ {cached['totale_cv']:,.0f} · modello: {cached['model']}"
    )
    vertical_gap("xs")
    st.markdown(cached["text"])

    sd = cached.get("structured_data", {})
    if sd:
        _render_instrument_scores(sd.get("instrument_scores", []))
        _render_category_projections(sd.get("category_projections", []))
        _render_stress_scenarios(sd.get("stress_scenarios", []))

    vertical_gap("xs")
    if st.button("Salva report", key="_ai_save_report_btn"):
        try:
            save_ai_report({
                "analysis_text": cached["text"],
                "structured_data": cached.get("structured_data", {}),
                "model": cached["model"],
                "custom_prompt": cached.get("custom_prompt", ""),
                "payload": cached.get("payload", {}),
            })
            st.success("Report salvato in data/ai_reports/")
        except Exception as exc:
            st.error(f"Errore salvataggio: {exc}")
