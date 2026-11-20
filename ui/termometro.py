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




def _geometry():
    """Dimensioni del grafico a candele: tutte da `ui/charts/settings.py` (voce `termometro_candele`), nessun numero qui."""
    from types import SimpleNamespace
    from ui.charts.settings import get_chart_setting as cfg

    def num(key, default):
        return float(cfg("termometro_candele", key, default))
    return SimpleNamespace(w=num("width", 680), h=num("height", 200), pad=num("pad", 14), left=num("axis_left", 54), bottom=num("axis_bottom", 22),
                           right=num("axis_right", 64), body_max=num("body_max_px", 20), body_ratio=num("body_slot_ratio", 0.56),
                           min_body=num("min_body_px", 4), halo_margin=num("halo_margin_px", 9), y_ticks=max(1.0, num("y_ticks_target", 4)),
                           x_labels=max(1, int(num("x_labels_max", 7))), font_axis=num("font_axis_px", 8.5), font_axis_x=num("font_axis_x_px", 7.5), font_pill=num("font_pill_px", 8.5))


def _chart_points(candles: list[dict[str, Any]], line: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Un punto per giorno: candela dove ci sono letture, P/L di fine giornata altrove."""
    by_day = {str(c["day"]): c for c in candles}
    values = {str(p["day"]): float(p["value"]) for p in line}
    for day, candle in by_day.items():
        values[day] = float(candle["close"])
    return [{"day": d, "value": values[d], "candle": by_day.get(d)} for d in sorted(values)]


def _nice_step(raw: float) -> float:
    """Passo «tondo» (1, 2, 5 × 10^n: 10, 20, 50, 100, 200 euro…) per le tacche dell'asse verticale."""
    import math
    if raw <= 0:
        return 1.0
    exp = math.floor(math.log10(raw))
    for mult in (1, 2, 5, 10):
        if raw <= mult * 10 ** exp:
            return mult * 10 ** exp
    return 10 ** (exp + 1)


def _axes_svg(points: list[dict[str, Any]], lo: float, hi: float, y, xc, g) -> str:
    """Assi leggeri, senza linee di base: guide orizzontali tratteggiate con l'importo (P/L in euro) e le date in basso."""
    import math
    step = _nice_step((hi - lo) / g.y_ticks)
    out = []
    value = math.ceil(lo / step) * step
    while value <= hi + 1e-9:
        yy = y(value)
        out.append(f"<line class='gr' x1='{g.left:.0f}' x2='{g.w - g.right:.0f}' y1='{yy:.1f}' y2='{yy:.1f}'/>"
                   f"<text class='ax' x='{g.left - 8:.0f}' y='{yy + 3.5:.1f}' text-anchor='end'>{html.escape(fmt_eur_it(value, 0, signed=True))}</text>")
        value += step
    base = g.h - g.bottom
    months = ("gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic")
    prev_month = None
    for i, p in enumerate(points):
        try:
            d = datetime.strptime(str(p["day"]), "%Y-%m-%d")
        except ValueError:
            continue
        out.append(f"<text class='ax axd' x='{xc(i):.1f}' y='{base + 13:.0f}' text-anchor='middle'>{d.day}</text>")
        if d.month != prev_month:   # il mese compare sotto il primo giorno disponibile di ogni mese (l'1 può mancare: festivo, nessuna lettura)
            out.append(f"<text class='ax axd axm' x='{xc(i):.1f}' y='{base + 24:.0f}' text-anchor='middle'>{months[d.month - 1]}</text>")
        prev_month = d.month
    return "".join(out)


def _smooth_path(coords: list[tuple[float, float]]) -> str:
    """Linea morbida fra i punti (tangenti orizzontali: nessun overshoot, i valori non superano mai quelli reali)."""
    if not coords:
        return ""
    d = [f"M{coords[0][0]:.1f},{coords[0][1]:.1f}"]
    for (x0, y0), (x1, y1) in zip(coords, coords[1:]):
        mid = (x0 + x1) / 2
        d.append(f"C{mid:.1f},{y0:.1f} {mid:.1f},{y1:.1f} {x1:.1f},{y1:.1f}")
    return " ".join(d)


def _candles_block(candles: list[dict[str, Any]] | None, line: list[dict[str, Any]] | None = None, gap: str | None = None) -> str:
    """Candele giornaliere del P/L delle posizioni aperte (letture archiviate, TM-05) collegate da una linea morbida; dove mancano le
    letture, il solo P/L di fine giornata. Un alone sfumato avvolge le candele. SVG inline, colori dai token del tema."""
    g = _geometry()
    ok = [c for c in (candles or []) if all(isinstance(c.get(k), (int, float)) for k in ("open", "high", "low", "close"))]
    points = _chart_points(ok, line or [])
    head = "<span class='ptf-insights-eyebrow'>P/L delle posizioni: candele delle letture</span>"
    if len(points) < 2 or not ok:
        return (
            f"<div class='ptf-pulse-candles'>{head}"
            "<div class='ptf-pulse-note'>Servono letture di almeno un giorno: il grafico si riempie a ogni aggiornamento delle quotazioni.</div></div>"
        )
    lows = [float(p["candle"]["low"]) if p["candle"] else p["value"] for p in points]
    highs = [float(p["candle"]["high"]) if p["candle"] else p["value"] for p in points]
    lo, hi = min(lows), max(highs)
    span = (hi - lo) or max(abs(hi) * 0.001, 1.0)
    lo, hi, span = lo - span * 0.10, hi + span * 0.10, span * 1.20
    plot_w, plot_h = g.w - g.left - g.right, g.h - g.bottom - 2 * g.pad
    y = lambda v: g.pad + (hi - float(v)) / span * plot_h  # noqa: E731
    slot = plot_w / len(points)
    xc = lambda i: g.left + slot * (i + 0.5)  # noqa: E731
    body = min(slot * g.body_ratio, g.body_max)
    right = g.w - g.right
    zero = (f"<line class='zero' x1='{g.left:.0f}' x2='{right:.0f}' y1='{y(0):.1f}' y2='{y(0):.1f}'/>" if lo < 0 < hi else "")
    axes = _axes_svg(points, lo, hi, y, xc, g)

    candle_idx = [i for i, p in enumerate(points) if p["candle"]]
    envelope = list(range(candle_idx[0], candle_idx[-1] + 1))      # un unico alone dalla prima all'ultima candela
    margin = g.halo_margin   # margine dell'alone attorno alle candele, ottenuto allargando la forma (niente bordo: un solo colore uniforme)
    top_edge = [(xc(i), y(points[i]["candle"]["high"] if points[i]["candle"] else points[i]["value"]) - margin) for i in envelope]
    bottom_edge = [(xc(i), y(points[i]["candle"]["low"] if points[i]["candle"] else points[i]["value"]) + margin) for i in reversed(envelope)]
    left_x, right_x = top_edge[0][0] - body / 2 - 4, top_edge[-1][0] + body / 2 + 4
    halo_d = (_smooth_path([(left_x, top_edge[0][1])] + top_edge + [(right_x, top_edge[-1][1])])
              + f" L{right_x:.1f},{bottom_edge[0][1]:.1f} "
              + _smooth_path([(right_x, bottom_edge[0][1])] + bottom_edge + [(left_x, bottom_edge[-1][1])]).replace("M", "L", 1) + " Z")
    halo = f"<path class='cd-halo' d='{halo_d}'/>"
    line_path = _smooth_path([(xc(i), y(p["value"])) for i, p in enumerate(points)])

    marks, hits = [], []
    for i, p in enumerate(points):
        x, c = xc(i), p["candle"]
        tip = (f"{_date_it(p['day'])}: fine giornata {fmt_eur_it(p['value'], 0, signed=True)}" if not c else
               f"{_date_it(c['day'])} · apertura {fmt_eur_it(c['open'], 0, signed=True)} · massimo {fmt_eur_it(c['high'], 0, signed=True)} · "
               f"minimo {fmt_eur_it(c['low'], 0, signed=True)} · chiusura {fmt_eur_it(c['close'], 0, signed=True)} · {int(c.get('n') or 0)} letture")
        hits.append(f"<i style='left:{(x - slot / 2) / g.w * 100:.3f}%;width:{slot / g.w * 100:.3f}%' title='{html.escape(tip)}'></i>")
        if not c:
            marks.append(f"<circle class='ln-dot' cx='{x:.1f}' cy='{y(p['value']):.1f}' r='3'><title>"
                         f"{html.escape(_date_it(p['day']))} · fine giornata {html.escape(fmt_eur_it(p['value'], 0, signed=True))}</title></circle>")
            continue
        tone = "up" if float(c["close"]) >= float(c["open"]) else "down"
        top, bottom = y(max(c["open"], c["close"])), y(min(c["open"], c["close"]))
        title = (f"{_date_it(c['day'])} · apertura {fmt_eur_it(c['open'], 0, signed=True)} · massimo {fmt_eur_it(c['high'], 0, signed=True)} · "
                 f"minimo {fmt_eur_it(c['low'], 0, signed=True)} · chiusura {fmt_eur_it(c['close'], 0, signed=True)} · {int(c.get('n') or 0)} letture")
        marks.append(
            f"<g class='cd-{tone}'><title>{html.escape(title)}</title>"
            f"<line x1='{x:.1f}' x2='{x:.1f}' y1='{y(c['high']):.1f}' y2='{y(c['low']):.1f}'/>"
            f"<rect x='{x - body / 2:.1f}' y='{top:.1f}' width='{body:.1f}' height='{max(bottom - top, g.min_body):.1f}'/></g>"
        )
    last = ok[-1]
    last_x, last_y = xc(len(points) - 1), y(last["close"])
    change = float(last["close"]) - float(last["open"])
    tone = "is-up" if change > 0.005 else "is-down" if change < -0.005 else "is-flat"
    pill = (f"<g class='lastpill {'up' if change >= 0 else 'down'}'><line class='lastguide' x1='{last_x + body / 2 + 2:.1f}' x2='{right + 4:.0f}' y1='{last_y:.1f}' y2='{last_y:.1f}'/>"
            f"<rect x='{right + 4:.0f}' y='{last_y - 8:.1f}' width='{g.right - 8:.0f}' height='16' rx='8'/>"
            f"<text x='{right + 4 + (g.right - 8) / 2:.1f}' y='{last_y + 3.8:.1f}' text-anchor='middle'>{html.escape(fmt_eur_it(last['close'], 0, signed=True))}</text></g>")
    summary = (
        f"{html.escape(_date_it(last['day']))}: apertura {html.escape(fmt_eur_it(last['open'], 0, signed=True))} · "
        f"massimo {html.escape(fmt_eur_it(last['high'], 0, signed=True))} · minimo {html.escape(fmt_eur_it(last['low'], 0, signed=True))} · "
        f"chiusura <b class='{tone}'>{html.escape(fmt_eur_it(last['close'], 0, signed=True))}</b> · {int(last.get('n') or 0)} letture"
    )
    gap_note = (f"<div class='ptf-pulse-note ptf-pulse-center'>Attenzione: il {html.escape(_date_it(gap))} il Mobile ha segnalato letture perse "
                "(troppi giorni senza collegamento al Desktop): le candele di quei giorni possono avere buchi, i prezzi mancanti non sono ricostruiti</div>") if gap else ""
    defs = ""
    return (
        f"<div class='ptf-pulse-candles'>{head}"
        "<div class='ptf-candle-panel'><div class='ptf-candle-stage'>"
        f"<svg viewBox='0 0 {g.w:.0f} {g.h:.0f}' style='--fs-ax:{g.font_axis:g}px;--fs-axd:{g.font_axis_x:g}px;--fs-pill:{g.font_pill:g}px' role='img' aria-label='P/L delle posizioni: linea di fine giornata e candele'>"
        f"{defs}{axes}{zero}{halo}<path class='ln' d='{line_path}'/>{''.join(marks)}{pill}</svg>"
        f"<div class='ptf-candle-hits'>{''.join(hits)}</div></div></div>"
        f"<div class='ptf-pulse-note ptf-pulse-center'>{summary}</div>"
        "<div class='ptf-pulse-note ptf-pulse-center'>P/L non realizzato delle posizioni aperte (valore − costo): gli acquisti non lo spostano; candela = giorno con letture, punto = solo fine giornata; "
        "l'alone avvolge le candele (escursione fra minimo e massimo); i fondi a valore giornaliero restano fermi</div>"
        f"{gap_note}</div>"
    )


def _balance_block(balance: dict[str, Any] | None) -> str:
    """Bilance guadagni/perdite per strumento, ieri sopra e oggi sotto, **sulla stessa scala** per un confronto diretto.

    Per ogni giorno: i guadagni a destra, le perdite a sinistra, il rombo del netto. HTML/CSS (non SVG) perché i suggerimenti al
    mouse (attributo `title`) funzionano ovunque e i testi hanno dimensione reale in pixel; il nome nel segmento si accorcia da
    solo con i puntini. Dimensioni e testi da `ui/charts/settings.py` (voce `termometro_bilancia`), colori dai token del tema."""
    days = [d for d in (balance or {}).get("days", []) if d.get("gains") or d.get("losses")]
    if not days:
        return ""
    from ui.charts.settings import get_chart_setting as cfg

    def num(key, default):
        return float(cfg("termometro_bilancia", key, default))
    bar_h, min_op = num("bar_height", 40), num("shade_min_opacity", 0.55)
    # scala unica fra i giorni mostrati: la stessa larghezza vale lo stesso importo, ieri e oggi si confrontano a occhio
    span = max(max(float(d.get("gain_total") or 0.0), -float(d.get("loss_total") or 0.0)) for d in days)
    span = max(span, 1.0)

    def segments(items: list[dict[str, Any]], cls: str) -> str:
        n, out = len(items), []
        for i, it in enumerate(items):
            eur = float(it["eur"])
            op = 1.0 - (1.0 - min_op) * (i / max(n - 1, 1))
            tip = f"{it['ticker']}: {fmt_eur_it(eur, 0, signed=True)}"
            out.append(f"<div class='bal-seg {cls}' style='flex:{abs(eur):.4f} 1 0;--op:{op:.2f}' title='{html.escape(tip)}'>"
                       f"<span>{html.escape(str(it['ticker']))}</span></div>")
        return "".join(out)

    def one_day(d: dict[str, Any]) -> str:
        gain_total, loss_total, net = float(d.get("gain_total") or 0.0), float(d.get("loss_total") or 0.0), float(d.get("net") or 0.0)
        left_w, right_w = -loss_total / span * 100.0, gain_total / span * 100.0       # % della metà (la metà = 50% della barra)
        net_pos = min(max(50.0 + net / span * 50.0, 4.0), 96.0)
        tone = "is-up" if net > 0.005 else "is-down" if net < -0.005 else "is-flat"
        label = ("Ieri" if d.get("key") == "yesterday" else "Oggi") + f" · {_date_it(d.get('date', ''))}"
        return (
            "<div class='bal-day'>"
            f"<div class='bal-heads'><b class='bal-hl'>Perdite {html.escape(fmt_eur_it(loss_total, 0, signed=True))}</b>"
            f"<span class='bal-day-t'>{html.escape(label)}</span>"
            f"<b class='bal-hg'>Guadagni {html.escape(fmt_eur_it(gain_total, 0, signed=True))}</b></div>"
            "<div class='bal-bar'>"
            f"<div class='bal-half bal-l'><div class='bal-stack' style='width:{left_w:.3f}%'>{segments(d.get('losses') or [], 'bal-loss')}</div></div>"
            f"<div class='bal-half bal-r'><div class='bal-stack' style='width:{right_w:.3f}%'>{segments(d.get('gains') or [], 'bal-gain')}</div></div>"
            f"<i class='bal-net' style='left:{net_pos:.2f}%' title='Totale netto: {html.escape(fmt_eur_it(net, 0, signed=True))}'></i></div>"
            f"<div class='bal-net-t {tone}' style='left:{net_pos:.2f}%'>Netto {html.escape(fmt_eur_it(net, 0, signed=True))}</div>"
            "</div>"
        )
    return (
        f"<div class='ptf-pulse-balance' style='--fs-head:{num('font_head_px', 13):g}px;--fs-seg:{num('font_seg_px', 10):g}px;--fs-net:{num('font_net_px', 13):g}px;"
        f"--bar-h:{bar_h:g}px;--day-gap:{num('day_gap_px', 10):g}px'>"
        "<span class='ptf-insights-eyebrow'>Guadagni contro perdite</span>"
        f"{''.join(one_day(d) for d in days)}"
        "<div class='ptf-pulse-note ptf-pulse-center'>P/L non realizzato delle posizioni aperte, strumento per strumento; ieri e oggi sulla stessa scala: "
        "più il segmento è largo più pesa, il rombo è il totale netto. Passa il mouse su un segmento per vedere lo strumento e l'importo</div></div>"
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
        f"{_candles_block(pulse.get('candles'), pulse.get('value_line'), pulse.get('readings_gap'))}"
        f"{_balance_block(pulse.get('balance'))}"
        "</div></div>"
    )


def render_portfolio_termometro(pulse: dict[str, Any] | None) -> None:
    html_block = build_portfolio_termometro_html(pulse)
    if html_block:
        st.markdown(html_block, unsafe_allow_html=True)
