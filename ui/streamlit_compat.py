"""
Helper Streamlit per compatibilita' con API recenti.

Streamlit 1.58 introduce ``st.iframe`` come sostituto piu' pulito di
``components.html`` per blocchi HTML inline. Questo modulo mantiene un unico
punto di accesso, cosi' popup e tabelle HTML possono essere rifiniti senza
spargere logica di compatibilita' nelle singole pagine.
"""
from __future__ import annotations

from typing import Any

import streamlit as st


def iframe_height_for_rows(
    n_rows: int,
    *,
    row_height: int = 39,
    header_height: int = 44,
    padding: int = 10,
    min_height: int = 160,
    max_height: int = 760,
    content_until_rows: int | None = None,
) -> int | str:
    """Calcola un'altezza iframe coerente per tabelle HTML.

    Per tabelle piccole restituisce opzionalmente ``"content"`` in modo da
    sfruttare l'altezza automatica di ``st.iframe``. Per tabelle grandi mantiene
    un limite massimo, evitando pagine ingestibili e preservando lo scroll
    interno gia' previsto dai blocchi HTML esistenti.
    """
    try:
        rows = max(0, int(n_rows))
    except Exception:
        rows = 0

    if content_until_rows is not None and rows <= content_until_rows:
        return "content"

    calculated = header_height + rows * row_height + padding
    return min(max_height, max(min_height, calculated))


def iframe_scroll_for_rows(n_rows: int, *, threshold: int = 17) -> bool:
    """Restituisce True quando una tabella merita lo scroll interno."""
    try:
        return int(n_rows) > threshold
    except Exception:
        return False


def render_html_iframe(
    html: str,
    *,
    height: int | str = "content",
    width: int | str = "stretch",
    scrolling: bool | None = None,
    tab_index: int | None = None,
) -> Any:
    """Renderizza HTML in iframe con l'API non deprecata di Streamlit 1.58.

    ``scrolling`` resta accettato per compatibilita' con il vecchio wrapper,
    anche se ``st.iframe`` non espone piu' questo parametro. La gestione dello
    scroll rimane quindi delegata al CSS/HTML interno e all'altezza passata.
    """
    _ = scrolling
    return st.iframe(html, height=height, width=width, tab_index=tab_index)
