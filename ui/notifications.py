"""
ui/notifications.py — Toast e status centralizzati per Streamlit.

Obiettivo: mostrare messaggi persistenti anche quando un'azione termina con st.rerun().
Le notifiche vengono accodate in session_state e visualizzate al run successivo.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import streamlit as st

_TOAST_QUEUE_KEY = "_portfolio_pending_toasts"


def queue_toast(message: str, *, icon: str | None = None) -> None:
    """Accoda una notifica da mostrare al prossimo rerun.

    Usare questa funzione prima di st.rerun() al posto di st.success()/st.info(),
    perché gli elementi renderizzati prima del rerun possono non essere percepiti.
    """
    text = str(message or "").strip()
    if not text:
        return
    queue = list(st.session_state.get(_TOAST_QUEUE_KEY, []) or [])
    queue.append({"message": text, "icon": icon})
    st.session_state[_TOAST_QUEUE_KEY] = queue


def flush_toasts() -> None:
    """Mostra e svuota le notifiche accodate nel run precedente."""
    pending = st.session_state.pop(_TOAST_QUEUE_KEY, []) or []
    if not isinstance(pending, Iterable):
        return
    for item in pending:
        if isinstance(item, dict):
            message = str(item.get("message") or "").strip()
            icon = item.get("icon")
        else:
            message = str(item or "").strip()
            icon = None
        if not message:
            continue
        try:
            st.toast(message, icon=icon)
        except Exception:
            # Fallback per ambienti/test o versioni Streamlit senza toast pienamente disponibile.
            st.success(f"{icon + ' ' if icon else ''}{message}")


def queue_success(message: str, *, icon: str = "✅") -> None:
    """Shortcut semantico per conferme positive."""
    queue_toast(message, icon=icon)


def queue_info(message: str, *, icon: str = "ℹ️") -> None:
    """Shortcut semantico per messaggi informativi."""
    queue_toast(message, icon=icon)


def update_status(status_box: Any, *, label: str, state: str = "complete", expanded: bool = False) -> None:
    """Aggiorna uno status Streamlit senza far fallire l'app nei test o in fallback."""
    try:
        status_box.update(label=label, state=state, expanded=expanded)
    except Exception:
        pass
