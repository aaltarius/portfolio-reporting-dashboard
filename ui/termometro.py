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


def _streak_cell(streak: dict[str, Any] | None) -> str:
    if not streak or not streak.get("days"):
        return ""
    direction, days = streak.get("direction"), int(streak["days"])
    if direction == "flat":
        main, tone = f"{days} giorni invariato", "is-flat"
    else:
        up = direction == "up"
        main = f"{days} {'giorno' if days == 1 else 'giorni'} {'in rialzo' if up else 'in calo'}"
        tone = "is-up" if up else "is-down"
    extras = []
    worst, best = streak.get("worst_day"), streak.get("best_day")
    if worst and worst.get("pct") is not None and worst["pct"] < -_FLAT_PCT:
        extras.append(f"peggior giorno del mese <b class='is-down'>{html.escape(fmt_pct_it(worst['pct'], 2, signed=True))}</b> ({html.escape(_date_it(worst['date']))})")
    if best and best.get("pct") is not None and best["pct"] > _FLAT_PCT:
        extras.append(f"migliore <b class='is-up'>{html.escape(fmt_pct_it(best['pct'], 2, signed=True))}</b> ({html.escape(_date_it(best['date']))})")
    note = f"<div class='ptf-pulse-note'>{' · '.join(extras)}</div>" if extras else ""
    return (
        f"<div class='ptf-pulse-stat {tone}'><div class='ptf-pulse-h'>Serie</div>"
        f"<div class='ptf-pulse-statv'>{html.escape(main)}</div>{note}</div>"
    )


def _year_range_cell(rng: dict[str, Any] | None) -> str:
    if not rng or rng.get("position") is None:
        return ""
    pos = min(1.0, max(0.0, float(rng["position"])))
    partial = "<div class='ptf-pulse-note'>storia inferiore a 12 mesi</div>" if rng.get("partial") else ""
    return (
        "<div class='ptf-pulse-stat is-flat'><div class='ptf-pulse-h'>Ultimi 12 mesi</div>"
        f"<div class='ptf-pulse-range'><i style='left:{pos * 100:.0f}%'></i></div>"
        "<div class='ptf-pulse-note ptf-pulse-rangelab'>"
        f"<span>dal minimo <b class='is-up'>{html.escape(fmt_pct_it(rng['from_low'], 1, signed=True))}</b></span>"
        f"<span>dal massimo <b class='is-down'>{html.escape(fmt_pct_it(rng['from_high'], 1, signed=True))}</b></span></div>"
        f"{partial}</div>"
    )


def _volatility_cell(vol: dict[str, Any] | None) -> str:
    if not vol or vol.get("recent") is None:
        return ""
    label = str(vol.get("label") or "")
    tone = {"calma": "is-up", "agitata": "is-down"}.get(label, "is-flat")
    return (
        f"<div class='ptf-pulse-stat {tone}'><div class='ptf-pulse-h'>Volatilita' recente</div>"
        f"<div class='ptf-pulse-statv'>{html.escape(label.capitalize())}</div>"
        f"<div class='ptf-pulse-note'>{html.escape(fmt_pct_it(vol['recent'], 1, signed=False))} annua ultimo mese · "
        f"normale {html.escape(fmt_pct_it(vol['baseline'], 1, signed=False))}</div></div>"
    )


def _stats_row(pulse: dict[str, Any]) -> str:
    cells = "".join((
        _streak_cell(pulse.get("streak")),
        _year_range_cell(pulse.get("year_range")),
        _volatility_cell(pulse.get("volatility")),
    ))
    return f"<div class='ptf-pulse-stats'>{cells}</div>" if cells else ""


def _contributors_row(contrib: dict[str, Any] | None) -> str:
    if not contrib:
        return ""

    def _side(items: list[dict[str, Any]], tone: str) -> str:
        return " ".join(
            f"<b class='{tone}'>{html.escape(str(i['ticker']))} {html.escape(fmt_eur_it(i['eur'], 0, signed=True))}</b>"
            for i in items
        )

    parts = []
    if contrib.get("top"):
        parts.append(f"hanno spinto: {_side(contrib['top'], 'is-up')}")
    if contrib.get("bottom"):
        parts.append(f"hanno frenato: {_side(contrib['bottom'], 'is-down')}")
    if not parts:
        return ""
    return (
        "<div class='ptf-pulse-breadth'>"
        "<span class='ptf-insights-eyebrow'>Nel mese</span>"
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
        f"{_stats_row(pulse)}"
        f"{_category_tiles(pulse.get('categories') or [])}"
        f"{_breadth_row(pulse.get('breadth'))}"
        f"{_contributors_row(pulse.get('contributors'))}"
        "</div></div>"
    )


def render_portfolio_termometro(pulse: dict[str, Any] | None) -> None:
    html_block = build_portfolio_termometro_html(pulse)
    if html_block:
        st.markdown(html_block, unsafe_allow_html=True)
