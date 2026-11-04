# ui/pages/ai_chat.py
"""Tab Chat AI: conversazione multi-turn con il portafoglio come contesto."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd
import streamlit as st

from core.ai_analysis import AI_CALL_COUNT_KEY, build_portfolio_ai_payload, call_gemini_chat, save_ai_report
from ui.components import legend_block, vertical_gap

_CHAT_HISTORY_KEY = "_ai_chat_history_v1"
_CHAT_CTX_SENT_KEY = "_ai_chat_ctx_sent_v1"


def render_ai_chat(ctx: SimpleNamespace, *, api_key: str, model: str) -> None:
    """Chat multi-turn con Gemini. Il portafoglio è iniettato nel primo messaggio."""
    legend_block(
        "Il portafoglio viene inviato a Gemini come contesto nel primo messaggio. "
        "Puoi poi fare domande libere senza ripetere i dati.",
        variant="bottom",
    )
    vertical_gap("xs")

    history: list[dict] = st.session_state.get(_CHAT_HISTORY_KEY, [])
    ctx_sent: bool = st.session_state.get(_CHAT_CTX_SENT_KEY, False)

    # Mostra i messaggi precedenti
    for msg in history:
        role_ui = "user" if msg["role"] == "user" else "assistant"
        text = msg["parts"][0]["text"]
        if msg.get("_display_text"):
            text = msg["_display_text"]
        with st.chat_message(role_ui):
            st.markdown(text)

    # Input in fondo alla discussione
    vertical_gap("xs")
    user_input = st.text_area("Scrivi un messaggio", placeholder="Chiedi qualcosa sul tuo portafoglio…", key="_ai_chat_input", height=90, label_visibility="collapsed")
    col_send, _ = st.columns([1, 4])
    with col_send:
        send = st.button("Invia", type="primary", key="_ai_chat_send_btn", width="stretch")

    vertical_gap("xs")
    col_save, col_reset, _ = st.columns([1, 1, 3])
    with col_save:
        if st.button("Salva chat", key="_ai_chat_save_btn", width="stretch", disabled=not history):
            lines = []
            for msg in history:
                role_label = "Utente" if msg["role"] == "user" else "Gemini"
                text = msg.get("_display_text") or msg["parts"][0]["text"]
                lines.append(f"**{role_label}:** {text}")
            transcript = "\n\n---\n\n".join(lines)
            try:
                save_ai_report({
                    "model": model,
                    "custom_prompt": "Chat multi-turn",
                    "payload": {},
                    "analysis_text": transcript,
                    "structured_data": {},
                })
                st.success("Chat salvata.")
            except Exception as exc:
                st.error(f"Errore salvataggio: {exc}")
    with col_reset:
        if st.button("Nuova chat", key="_ai_chat_reset_btn", width="stretch"):
            st.session_state.pop(_CHAT_HISTORY_KEY, None)
            st.session_state.pop(_CHAT_CTX_SENT_KEY, None)
            st.rerun()

    if send and user_input and user_input.strip():
        messages = list(history)
        display_text = user_input

        if not ctx_sent:
            da: pd.DataFrame = getattr(ctx, "da", pd.DataFrame())
            data: dict = getattr(ctx, "data", {}) or {}
            payload = build_portfolio_ai_payload(data, da)
            payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
            full_text = (
                f"Ecco il mio portafoglio (dati JSON) da usare come contesto per tutta la conversazione:\n"
                f"```json\n{payload_json}\n```\n\n"
                f"{user_input}"
            )
            msg_entry = {"role": "user", "parts": [{"text": full_text}], "_display_text": user_input}
        else:
            msg_entry = {"role": "user", "parts": [{"text": user_input}]}

        messages.append(msg_entry)

        with st.chat_message("user"):
            st.markdown(display_text)

        with st.chat_message("assistant"):
            with st.spinner("Gemini sta elaborando…"):
                try:
                    # Passa a Gemini solo role+parts (senza _display_text)
                    gemini_messages = [
                        {"role": m["role"], "parts": m["parts"]} for m in messages
                    ]
                    response = call_gemini_chat(gemini_messages, api_key, model=model)
                    st.markdown(response)
                    messages.append({"role": "model", "parts": [{"text": response}]})
                    st.session_state[_CHAT_HISTORY_KEY] = messages
                    st.session_state[_CHAT_CTX_SENT_KEY] = True
                    st.session_state[AI_CALL_COUNT_KEY] = st.session_state.get(AI_CALL_COUNT_KEY, 0) + 1
                    st.rerun()
                except RuntimeError as exc:
                    st.error(str(exc))
