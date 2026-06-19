"""ui/pages/cruscotti_ai.py — Tab AI: analisi portafoglio via Gemini Flash."""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import streamlit as st

from core.ai_analysis import GEMINI_MODELS, build_gemini_prompt, build_portfolio_ai_payload, call_gemini_flash, list_gemini_models, test_gemini_connection
from ui.components import legend_block, render_section_title, vertical_gap

_AI_RESULT_KEY = "_cruscotti_ai_result_v1"
_AI_KEY_SESSION = "_cruscotti_ai_gemini_key"
_GEMINI_SECRETS_KEY = "GEMINI_API_KEY"


def _get_api_key() -> str:
    """Legge la chiave API da st.secrets se disponibile, altrimenti da session_state."""
    try:
        key = st.secrets.get(_GEMINI_SECRETS_KEY, "")
        if key:
            return str(key)
    except Exception:
        pass
    return str(st.session_state.get(_AI_KEY_SESSION, ""))


def render_ai_analysis(ctx: SimpleNamespace) -> None:
    """Analisi portafoglio via Gemini Flash — on-demand, non ricalcolata sui rerun."""
    render_section_title(
        "Analisi AI portafoglio",
        comment="Invia i dati del portafoglio a Gemini Flash (Google) per un'analisi indipendente. Non viene rieseguita automaticamente nei rerun.",
        icon="analysis",
    )
    legend_block(
        "I dati del portafoglio vengono inviati a Google Gemini. "
        "Non includere informazioni sensibili extra nel prompt personalizzato. "
        "La chiave API rimane solo in memoria di sessione e non viene salvata su disco.",
        variant="bottom",
    )
    vertical_gap("xs")

    # ── Chiave API ──────────────────────────────────────────────────────────
    stored_key = _get_api_key()
    key_display = "●●●●●●●●" if stored_key else ""

    with st.expander("Configurazione chiave API Gemini", expanded=not bool(stored_key)):
        st.markdown(
            "Ottieni una chiave gratuita su [Google AI Studio](https://aistudio.google.com/apikey). "
            "In alternativa crea `.streamlit/secrets.toml` con `GEMINI_API_KEY = \"la-tua-chiave\"`."
        )
        new_key = st.text_input(
            "Chiave API Gemini",
            value="",
            type="password",
            placeholder="AIza...",
            key="_ai_key_input",
        )
        if st.button("Salva chiave", key="_ai_key_save_btn"):
            if new_key.strip():
                st.session_state[_AI_KEY_SESSION] = new_key.strip()
                st.success("Chiave salvata per questa sessione.")
                st.rerun()
            else:
                st.warning("Inserisci una chiave valida.")
        if stored_key:
            st.caption(f"Chiave attiva: {key_display} (valida per questa sessione)")

    vertical_gap("xs")

    api_key = _get_api_key()
    if not api_key:
        st.info("Inserisci la chiave API Gemini per abilitare l'analisi.")
        return

    col_diag1, col_diag2 = st.columns(2)
    with col_diag1:
        if st.button("Mostra modelli disponibili", key="_ai_list_models_btn", use_container_width=True):
            try:
                available = list_gemini_models(api_key)
                if available:
                    st.success("Modelli disponibili (supportano generateContent):")
                    st.code("\n".join(available))
                else:
                    st.warning("Nessun modello trovato per questa chiave.")
            except RuntimeError as exc:
                st.error(str(exc))
            return
    with col_diag2:
        if st.button("Testa connessione (prompt minimale)", key="_ai_test_conn_btn", use_container_width=True):
            selected_model_test = st.session_state.get("_ai_model_select", GEMINI_MODELS[0])
            try:
                result = test_gemini_connection(api_key, model=selected_model_test)
                st.success(f"Connessione OK. Risposta modello: {result!r}")
            except RuntimeError as exc:
                st.error(str(exc))
            return

    # ── Controlli analisi ────────────────────────────────────────────────────
    da: pd.DataFrame = getattr(ctx, "da", pd.DataFrame())
    data: dict = getattr(ctx, "data", {}) or {}

    col_model, col_btn = st.columns([3, 1])
    with col_model:
        selected_model = st.selectbox(
            "Modello",
            options=GEMINI_MODELS,
            index=0,
            key="_ai_model_select",
            help="gemini-2.0-flash è il modello gratuito disponibile. "
                 "gemini-2.0-flash-lite è più veloce ma meno accurato. "
                 "I modelli 2.5 sono a pagamento.",
        )
    with col_btn:
        vertical_gap("sm")
        analyze_clicked = st.button(
            "Analizza portafoglio",
            type="primary",
            key="_ai_analyze_btn",
            use_container_width=True,
        )

    custom_prompt = st.text_area(
        "Prompt personalizzato (opzionale)",
        value="",
        placeholder="Lascia vuoto per usare il prompt standard. "
                    "Esempio: «Concentrati sul rischio di duration dei titoli GOV.»",
        height=72,
        key="_ai_custom_prompt",
    )

    # ── Esecuzione ────────────────────────────────────────────────────────────
    if analyze_clicked:
        with st.status("Analisi in corso con Gemini Flash…", expanded=True) as status:
            try:
                st.write("Costruzione payload portafoglio…")
                payload = build_portfolio_ai_payload(data, da)
                st.write(f"Portafoglio: {len(payload['instruments'])} strumenti, "
                         f"€ {payload['totale_controvalore_eur']:,.0f} controvalore totale.")
                st.write("Invio a Gemini Flash…")
                prompt = build_gemini_prompt(payload, custom_prompt=custom_prompt or None)
                response_text = call_gemini_flash(prompt, api_key, model=selected_model)
                st.session_state[_AI_RESULT_KEY] = {
                    "text": response_text,
                    "n_instruments": len(payload["instruments"]),
                    "totale_cv": payload["totale_controvalore_eur"],
                }
                status.update(label="Analisi completata", state="complete", expanded=False)
            except RuntimeError as exc:
                status.update(label="Errore API", state="error", expanded=True)
                st.error(str(exc))
                return
            except Exception as exc:
                status.update(label="Errore imprevisto", state="error", expanded=True)
                st.error(f"Errore imprevisto: {exc}")
                return

    # ── Risultato ────────────────────────────────────────────────────────────
    cached = st.session_state.get(_AI_RESULT_KEY)
    if cached:
        st.caption(
            f"Ultima analisi: {cached['n_instruments']} strumenti · "
            f"€ {cached['totale_cv']:,.0f} controvalore. "
            "Clicca di nuovo per aggiornare."
        )
        vertical_gap("xs")
        st.markdown(cached["text"])
    elif not analyze_clicked:
        legend_block(
            "Clicca «Analizza portafoglio» per inviare i dati a Gemini Flash e ricevere "
            "un'analisi con suggerimenti di ribilanciamento.",
            variant="bottom",
        )
