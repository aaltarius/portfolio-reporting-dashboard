"""Matrice Benchmark con lo stesso renderer nativo di Quotazioni e Portafoglio.

Nessun iframe/HTML statico, CSS locale, scrollbar verticale prefissata o
paginazione: il tema, le righe e la tabella sono quelli di ui.components.
"""
from __future__ import annotations
from typing import Any
import pandas as pd
import streamlit as st

from ui.components import render_styled_table
from ui.theme import get_theme_context, macro_color


def render_benchmark_table(
    records: list[dict[str, Any]] | pd.DataFrame,
    *,
    columns: list[tuple[str, str]],
    key: str,
    category_key: str | None = None,
    instrument_key: str | None = None,
    tone_key: str | None = None,
    page_size: int | None = None,
    widths: list[int] | None = None,
) -> None:
    """Vista completa con st.dataframe/Stylers condivisi (height='content').

    key, page_size e widths sono conservati per compatibilita' con i chiamanti
    esistenti; non viene creato stato widget o un secondo scroll interno.
    """
    frame = records.copy() if isinstance(records, pd.DataFrame) else pd.DataFrame(records)
    if frame.empty:
        st.caption('Nessun elemento da visualizzare.')
        return
    fields = [field for field, _ in columns]
    labels = {field: label for field, label in columns}
    frame = frame.reindex(columns=fields).fillna('').rename(columns=labels)
    instrument = labels.get(instrument_key, '') if instrument_key else ''
    category = labels.get(category_key, '') if category_key else ''
    extra = labels.get(tone_key, '') if tone_key else ''
    ctx = get_theme_context()
    category_color = {
        str(v): macro_color(str(v)) for v in frame[category].unique()
    } if category and category in frame.columns else {}

    def _style_row(row: pd.Series) -> list[str]:
        cat_color = category_color.get(str(row.get(category)), ctx.font_color)
        result = []
        for col in row.index:
            css = ''
            if col in (instrument, category):
                css = f'color:{cat_color};font-weight:700;'
            elif col == extra:
                value = str(row[col]).strip()
                if value.startswith('+'):
                    css = f'color:{ctx.color_green};font-weight:700;'
                elif value.startswith('-') and value not in ('-', '—'):
                    css = f'color:{ctx.color_red};font-weight:700;'
            elif col == 'Stato':
                state = str(row[col])
                if state in ('Da aggiornare', 'Storico incerto', 'Dati mancanti'):
                    css = f'color:{ctx.color_red};font-weight:600;'
            result.append(css)
        return result

    styled = frame.style.format(na_rep='—', escape='html').apply(_style_row, axis=1)
    # Identico punto di rendering usato in Quotazioni, Portafoglio e Cruscotti.
    # height='content' mostra l'intero numero di righe senza paginazione.
    render_styled_table(styled, height='content')
