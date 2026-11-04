from __future__ import annotations

import math
import pandas as pd
import streamlit as st

from persistence.storage import _normalize_macro_label, macro_cat as _macro_cat
from ui.components import render_styled_table
from ui.formatting import fmt_eur_it, fmt_pct_it, fmt_qty_it
from ui.streamlit_compat import iframe_height_for_rows, iframe_scroll_for_rows, render_html_iframe
from ui.theme import CATEGORY_COLORS, P, macro_color

def color_pl(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    if v > 0:
        return f"color:{P['green']};font-weight:600;"
    if v < 0:
        return f"color:{P['red']};font-weight:600;"
    return f"color:{P['muted']};"



def style_macro_cols(row):
    cat = _normalize_macro_label(row.get("Tipo", row.get("Tipologia", "")))
    color = macro_color(cat)
    styles = []
    for col in row.index:
        if col in {"Ticker", "Tipo", "Tipologia", "Descrizione"}:
            styles.append(f"color:{color};font-weight:700;")
        else:
            styles.append("")
    return styles


def small_pie_texts(values, threshold=0.06):
    vals = [float(v) if pd.notna(v) else 0.0 for v in values]
    total = sum(vals)
    if total <= 0:
        return ["" for _ in vals]
    out = []
    for v in vals:
        share = v / total
        out.append(fmt_pct_it(share, 1) if share >= threshold else "")
    return out



