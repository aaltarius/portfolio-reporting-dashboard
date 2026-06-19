# ui/pages/ai_page.py
"""Pagina AI: dispatcher con 3 tab — Analisi, Chat, Report."""
from __future__ import annotations

from types import SimpleNamespace

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from core.ai_analysis import AI_CALL_COUNT_KEY, GEMINI_MODELS, load_ai_config
from ui.components import back_to_top, render_section_title, vertical_gap
from ui.page_chrome import render_page_intro as render_page_intro_shared
from ui.pages.ai_analysis import render_ai_analysis
from ui.pages.ai_chat import render_ai_chat
from ui.pages.ai_reports import render_ai_reports

_AI_KEY_SESSION = "_cruscotti_ai_gemini_key"
_GEMINI_SECRETS_KEY = "GEMINI_API_KEY"


def _get_api_key() -> str:
    """Priorità: st.secrets > ai_config.json > session_state."""
    try:
        key = st.secrets.get(_GEMINI_SECRETS_KEY, "")
        if key:
            return str(key)
    except Exception:
        pass
    cfg = load_ai_config()
    if cfg.get("api_key"):
        return str(cfg["api_key"])
    return str(st.session_state.get(_AI_KEY_SESSION, ""))


def render_ai_page(tab: DeltaGenerator, ctx: SimpleNamespace) -> None:
    """Entry point della pagina AI."""
    with tab:
        render_page_intro_shared(
            title="Analisi AI portafoglio",
            comment="Analisi, chat e report via Google Gemini.",
            icon="analysis",
        )

        api_key = _get_api_key()
        if not api_key:
            st.info(
                "Nessuna chiave API configurata. "
                "Vai in **Setup → Configurazione AI** per inserire la tua chiave Gemini."
            )
            return

        cfg = load_ai_config()
        default_model = cfg.get("default_model", GEMINI_MODELS[0])
        default_idx = GEMINI_MODELS.index(default_model) if default_model in GEMINI_MODELS else 0

        selected_model = st.selectbox(
            "Modello Gemini",
            options=GEMINI_MODELS,
            index=default_idx,
            key="_ai_model_select",
            help="Il modello default si configura in Setup → Configurazione AI.",
        )

        call_count = st.session_state.get(AI_CALL_COUNT_KEY, 0)
        st.caption(
            f"Chiamate Gemini questa sessione: **{call_count}** — "
            "[Controlla quota e limiti →](https://console.cloud.google.com/apis/api/generativelanguage.googleapis.com/quotas)"
        )
        vertical_gap("xs")

        tab_analisi, tab_chat, tab_report = st.tabs(["Analisi", "Chat", "Report"])

        with tab_analisi:
            render_ai_analysis(ctx, api_key=api_key, model=selected_model)

        with tab_chat:
            render_ai_chat(ctx, api_key=api_key, model=selected_model)

        with tab_report:
            render_ai_reports(ctx, api_key=api_key, model=selected_model)

        back_to_top(show_prev=True, show_next=True, nav_key="ai")
