"""
ui/ux_helpers.py — micro-UX helpers per conferme e dettagli opzionali.

Contiene piccoli wrapper Streamlit a basso rischio: non modificano dati, calcoli o
navigazione, ma rendono piu' coerenti conferme distruttive e dettagli tecnici.
"""
from __future__ import annotations

import streamlit as st


def render_help_popover(label: str, body: str, *, key: str | None = None) -> None:
    """Mostra un piccolo contenuto informativo in st.popover, con fallback sicuro.

    Streamlit calcola comunque il contenuto del popover nel run corrente: questo
    helper va usato per testo/JSON leggero o diagnostica gia' disponibile, non per
    elaborazioni pesanti da rendere lazy.
    """
    text = str(body or "").strip()
    if not text:
        return
    try:
        with st.popover(label):
            st.markdown(text)
    except Exception:
        # Fallback per ambienti di test o versioni Streamlit senza popover.
        with st.expander(label, expanded=False):
            st.markdown(text)


def render_json_popover(label: str, payload: object) -> None:
    """Mostra JSON tecnico in un contenitore richiudibile, senza appesantire la UI."""
    try:
        with st.popover(label):
            st.json(payload)
    except Exception:
        with st.expander(label, expanded=False):
            st.json(payload)


def confirm_danger(label: str, *, key: str, help_text: str | None = None) -> bool:
    """Checkbox standardizzata per azioni distruttive."""
    return bool(st.checkbox(label, key=key, help=help_text))


def render_danger_hint(text: str) -> None:
    """Avviso compatto per azioni irreversibili o tecniche."""
    clean = str(text or "").strip()
    if clean:
        st.warning(clean)
