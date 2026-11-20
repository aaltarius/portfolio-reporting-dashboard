"""Calendario del P/L giornaliero del Portafoglio (TM-07): griglia di riquadri, uno per giorno di Borsa.

HTML/CSS puro, nessun Plotly. Parametri in `ui/charts/settings.py` (voce `portafoglio_calendario_pl`), colori dai token del tema
(classi .ptf-plcal-* in `ui/styles.py`). I dati arrivano da `core.services.pl_calendar.build_pl_calendar`."""
from __future__ import annotations

import html
from datetime import datetime
from typing import Any

import streamlit as st

from ui.formatting import fmt_eur_it

_WEEKDAYS = ("Lun", "Mar", "Mer", "Gio", "Ven")


def _dm(value: str) -> str:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").strftime("%d/%m")
    except ValueError:
        return str(value)


def _tone(v: float) -> str:
    return "up" if v > 0.005 else "down" if v < -0.005 else "flat"


def _mini_row(cal: dict[str, Any], n: int, cfg) -> str:
    """Per ogni settimana una barra dal giorno peggiore al giorno migliore, su scala unica; lo zero è sempre dentro la scala."""
    lo_s, hi_s = float(cal["scale_min"]), float(cal["scale_max"])
    span = (hi_s - lo_s) or 1.0
    h = float(cfg("portafoglio_calendario_pl", "mini_height_px", 84))
    gap = float(cfg("portafoglio_calendario_pl", "total_gap_px", 10))
    zero_pct = (hi_s / span) * 100
    st = f"style='height:{h:.0f}px;margin-top:{gap:.0f}px'"
    cells = []
    for w in cal["week_stats"]:
        if not w["n_days"]:
            cells.append(f"<div class='ptf-plcal-mini is-empty' {st}></div>")
            continue
        top, bot = max(w["best"], 0.0), min(w["worst"], 0.0)            # con giorni tutti dello stesso segno la barra parte dallo zero
        top_pct, h_pct = (hi_s - top) / span * 100, max((top - bot) / span * 100, 1.5)
        cells.append(
            f"<div class='ptf-plcal-mini' {st}>"
            f"<span class='hi is-{_tone(w['best'])}'>{html.escape(fmt_eur_it(w['best'], 0, signed=True))}</span>"
            f"<div class='plot'><i class='zero' style='top:{zero_pct:.1f}%'></i><i class='bar' style='top:{top_pct:.1f}%;height:{h_pct:.1f}%'></i></div>"
            f"<span class='lo is-{_tone(w['worst'])}'>{html.escape(fmt_eur_it(w['worst'], 0, signed=True))}</span></div>")
    return f"<div class='ptf-plcal-lbl'>Max/min</div>{''.join(cells)}"


def _total_row(cal: dict[str, Any], n: int, i_min: float, i_max: float, strong_from: float) -> str:
    """Totale di ogni settimana, sotto il mini grafico: colore sul totale settimanale, ▲ migliore e ▼ peggiore."""
    max_t = float(cal.get("max_total_abs") or 1.0)
    cells = []
    for wi, w in enumerate(cal["week_stats"]):
        t = float(w["total"])
        inten = i_min + (i_max - i_min) * min(abs(t) / max_t, 1.0)
        mark = " is-best" if wi == cal.get("best_week") else " is-worst" if wi == cal.get("worst_week") else ""
        arrow = "▲ " if mark == " is-best" else "▼ " if mark == " is-worst" else ""
        strong = " is-strong" if inten >= strong_from else ""
        cells.append(f"<div class='ptf-plcal-tot is-{_tone(t)}{strong}{mark}' style='--i:{inten:.2f}' title='Totale settimana'>"
                     f"<b>{arrow}{html.escape(fmt_eur_it(t, 0, signed=True))}</b></div>")
    return f"<div class='ptf-plcal-lbl'><b>Sett.</b></div>{''.join(cells)}"


def build_pl_calendar_html(cal: dict[str, Any] | None) -> str:
    if not cal or not cal.get("cells"):
        return ""
    from ui.charts.settings import get_chart_setting as cfg
    gap = float(cfg("portafoglio_calendario_pl", "cell_gap_px", 4))
    outline = float(cfg("portafoglio_calendario_pl", "mark_outline_px", 3))
    min_w = float(cfg("portafoglio_calendario_pl", "cell_min_width_px", 54))
    i_min = float(cfg("portafoglio_calendario_pl", "intensity_min", 0.10))
    i_max = float(cfg("portafoglio_calendario_pl", "intensity_max", 0.85))
    strong_from = float(cfg("portafoglio_calendario_pl", "strong_from", 0.6))    # da qui in su il testo diventa bianco
    weeks = cal["weeks"]
    max_abs = float(cal.get("max_abs") or 1.0)
    by_pos = {(c["weekday"], c["week"]): c for c in cal["cells"]}
    head = "".join(f"<div class='ptf-plcal-wk'>{html.escape(_dm(w))}</div>" if i % 2 == 0 else "<div class='ptf-plcal-wk'></div>" for i, w in enumerate(weeks))
    rows = []
    for wd, label in enumerate(_WEEKDAYS):
        cells = []
        for wi in range(len(weeks)):
            c = by_pos.get((wd, wi))
            if c is None:
                cells.append("<div class='ptf-plcal-cell is-empty'></div>")
                continue
            eur = float(c["eur"])
            tone = "up" if eur > 0.005 else "down" if eur < -0.005 else "flat"
            inten = i_min + (i_max - i_min) * min(abs(eur) / max_abs, 1.0)
            day = c["day"][8:10]
            strong = " is-strong" if inten >= strong_from else ""
            cells.append(
                f"<div class='ptf-plcal-cell is-{tone}{strong}' style='--i:{inten:.2f}' title='{html.escape(_dm(c['day']))}: {html.escape(fmt_eur_it(eur, 0, signed=True))}'>"
                f"<span class='d'>{html.escape(day)}</span><b>{html.escape(fmt_eur_it(eur, 0, signed=True))}</b></div>")
        rows.append(f"<div class='ptf-plcal-lbl'>{label}</div>{''.join(cells)}")
    rows.append(_mini_row(cal, len(weeks), cfg))
    rows.append(_total_row(cal, len(weeks), i_min, i_max, strong_from))
    total = float(cal.get("total") or 0.0)
    tone_t = "is-up" if total > 0.005 else "is-down" if total < -0.005 else "is-flat"
    summary = (f"Negli ultimi {len(weeks)} periodi settimanali: <b class='{tone_t}'>{html.escape(fmt_eur_it(total, 0, signed=True))}</b> "
               f"· {int(cal.get('up_days') or 0)} giorni in rialzo · {int(cal.get('down_days') or 0)} in calo")
    return (
        f"<div class='ptf-plcal' style='--cols:{len(weeks)};--gap:{gap:.0f}px;--minw:{min_w:.0f}px;--mark:{outline:.0f}px'>"
        "<div class='ptf-plcal-grid'>"
        f"<div></div>{head}{''.join(rows)}"
        "</div>"
        f"<div class='ptf-pulse-note ptf-pulse-center'>{summary}</div></div>"
    )


def render_pl_calendar(cal: dict[str, Any] | None) -> bool:
    block = build_pl_calendar_html(cal)
    if block:
        st.markdown(block, unsafe_allow_html=True)
    return bool(block)
