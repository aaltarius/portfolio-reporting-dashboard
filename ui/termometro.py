"""Renderer HTML del Termometro del portafoglio (vedi core/services/portfolio_pulse.py)."""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any

import streamlit as st

from ui.formatting import fmt_eur_it, fmt_pct_it

#: Colori dei tag categoria: gli stessi gia' usati dalle card KPI (`.kpi-triplet-tag-*`).
_CATEGORY_TAG_CLASS = {"GOV": "gov", "FND": "fnd", "ETF": "etf", "ETC": "etc", "OBB": "obb", "AZI": "azi"}
_FLAT_PCT = 0.00005  # sotto 0,005% e' "invariato" (colore neutro)


def _tone(value: float | None) -> str:
    if value is None:
        return "is-na"
    if abs(value) < _FLAT_PCT:
        return "is-flat"
    return "is-up" if value > 0 else "is-down"


def _date_it(value: str) -> str:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").strftime("%d/%m")
    except ValueError:
        return str(value)


def _horizon_cell(item: dict[str, Any]) -> str:
    eur, pct = item.get("eur"), item.get("pct")
    tone = _tone(pct if pct is not None else eur)
    eur_txt = fmt_eur_it(eur, 0, signed=True) if eur is not None else "n/d"
    pct_txt = fmt_pct_it(pct, 2, signed=True) if pct is not None else "n/d"
    note = "<div class='ptf-pulse-note'>storia parziale</div>" if item.get("partial") else ""
    return (
        f"<div class='ptf-pulse-cell {tone}'>"
        f"<div class='ptf-pulse-h'>{html.escape(str(item.get('label', '')))}</div>"
        f"<div class='ptf-pulse-eur'>{html.escape(eur_txt)}</div>"
        f"<div class='ptf-pulse-pct'>{html.escape(pct_txt)}</div>{note}</div>"
    )


def _drawdown_row(dd: dict[str, Any] | None) -> str:
    if not dd or dd.get("pct") is None:
        return ""
    pct = float(dd["pct"])
    if abs(pct) < _FLAT_PCT:
        text = "Il portafoglio e' ai massimi"
        fill = 0.0
    else:
        days = int(dd.get("days_since_peak") or 0)
        text = (
            f"<b class='is-down'>{html.escape(fmt_pct_it(pct, 1, signed=True))}</b> "
            f"dal picco del {html.escape(_date_it(dd.get('peak_date', '')))} "
            f"({days} giorni fa)"
        )
        fill = min(1.0, abs(pct) / 0.15)  # barra piena a -15%
    return (
        "<div class='ptf-pulse-dd'>"
        "<span class='ptf-insights-eyebrow'>Dal picco</span>"
        f"<div class='ptf-pulse-bar'><i style='width:{fill * 100:.0f}%'></i></div>"
        f"<span class='ptf-pulse-ddtext'>{text}</span></div>"
    )


def _category_tiles(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    tiles = []
    for row in rows:
        code = str(row.get("code") or "")
        pct, eur = row.get("pct"), row.get("eur")
        tone = _tone(pct if pct is not None else eur)
        pct_txt = fmt_pct_it(pct, 2, signed=True) if pct is not None else "n/d"
        eur_txt = f"{fmt_eur_it(eur, 0, signed=True)} sul totale" if eur is not None else "nessuna posizione"
        tag = _CATEGORY_TAG_CLASS.get(code.upper(), "")
        tiles.append(
            f"<div class='ptf-pulse-cat {tone}'>"
            f"<div class='kpi-triplet-tag kpi-triplet-tag-{tag}'>{html.escape(code)}</div>"
            f"<div class='ptf-pulse-catpct'>{html.escape(pct_txt)}</div>"
            f"<div class='ptf-pulse-note'>{html.escape(eur_txt)}</div></div>"
        )
    return (
        f"<div class='ptf-pulse-cats' style='--cols:{len(rows)}'>{''.join(tiles)}</div>"
        "<div class='ptf-pulse-note ptf-pulse-center'>variazione % a 5 giorni · peso in € nello stesso periodo (solo mercato)</div>"
    )


def _breadth_row(breadth: dict[str, Any] | None) -> str:
    if not breadth or not breadth.get("total"):
        return ""
    total, down, up = int(breadth["total"]), int(breadth["down"]), int(breadth["up"])
    flat = int(breadth.get("flat", total - down - up))
    dots = (
        "<b class='d'></b>" * down + "<b class='f'></b>" * flat + "<b class='u'></b>" * up
    )
    parts = [f"<b>{down}</b> su {total} in calo oggi"]
    worst, best = breadth.get("worst"), breadth.get("best")
    if worst:
        parts.append(
            f"peggiore <b class='is-down'>{html.escape(str(worst['ticker']))} "
            f"{html.escape(fmt_eur_it(worst['eur'], 0, signed=True))}</b>"
        )
    if best:
        parts.append(
            f"migliore <b class='is-up'>{html.escape(str(best['ticker']))} "
            f"{html.escape(fmt_eur_it(best['eur'], 0, signed=True))}</b>"
        )
    return (
        "<div class='ptf-pulse-breadth'>"
        "<span class='ptf-insights-eyebrow'>Oggi</span>"
        f"<span class='ptf-pulse-dots'>{dots}</span>"
        f"<span>{' · '.join(parts)}</span></div>"
    )


def build_portfolio_termometro_html(pulse: dict[str, Any] | None) -> str:
    if not pulse:
        return ""
    cells = "".join(_horizon_cell(h) for h in pulse.get("horizons", []))
    return (
        "<div class='ptf-insights-shell ptf-pulse'>"
        "<div class='ptf-insights-head'><div>"
        "<span class='ptf-insights-eyebrow'>Colpo d'occhio</span>"
        "<div class='ptf-insights-title'>Termometro del portafoglio</div></div>"
        f"<div class='ptf-insights-sync'>aggiornato al {html.escape(_date_it(pulse.get('as_of', '')))}"
        " · al netto di versamenti e prelievi</div></div>"
        "<div class='ptf-pulse-body'>"
        f"<div class='ptf-pulse-hz'>{cells}</div>"
        f"{_drawdown_row(pulse.get('drawdown'))}"
        f"{_category_tiles(pulse.get('categories') or [])}"
        f"{_breadth_row(pulse.get('breadth'))}"
        "</div></div>"
    )


def render_portfolio_termometro(pulse: dict[str, Any] | None) -> None:
    html_block = build_portfolio_termometro_html(pulse)
    if html_block:
        st.markdown(html_block, unsafe_allow_html=True)
