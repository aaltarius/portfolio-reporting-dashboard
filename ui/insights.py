"""Renderer HTML per insight decisionali compatti."""

from __future__ import annotations

import html
from typing import Any, Iterable

import streamlit as st

from core.services.portfolio_insights import PortfolioInsight
from ui.components import _section_icon_svg
from ui.theme import macro_color


_AREA_META: dict[str, tuple[str, str]] = {
    "Allocazione": ("var(--ptf-primary)", "portfolio"),
    "Concentrazione": ("#7c3aed", "analysis"),
    "Giornata": ("#ea580c", "quotes"),
    "Trend": ("#16a34a", "quotes"),
    "Cambio segno": ("var(--ptf-danger)", "risk"),
    "Qualita' dati": ("#0f766e", "data"),
    "SATOR": ("#0284c7", "analysis"),
    "Stato": ("var(--ptf-primary)", "default"),
}
_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2, "positive": 3}


def _severity_class(severity: str) -> str:
    normalized = str(severity or "info").strip().lower()
    if normalized in {"critical", "warning", "positive"}:
        return normalized
    return "info"


def _area_meta(area: str) -> tuple[str, str]:
    return _AREA_META.get(str(area or ""), _AREA_META["Stato"])


def _area_badge(area: str) -> str:
    color, icon_key = _area_meta(area)
    return (
        f'<div class="ptf-insight-cell-label" style="--area-tone:{html.escape(color)};">'
        f'<span class="ptf-insight-icon">{_section_icon_svg(icon_key)}</span>'
        f'<span>{html.escape(area or "Stato")}</span>'
        "</div>"
    )


def _ticker_chip_html(item: PortfolioInsight) -> str:
    ticker = str(getattr(item, "ticker", "") or "").strip().upper()
    if not ticker:
        return ""
    category = str(getattr(item, "category", "") or "").strip().upper()
    tone = macro_color(category) if category else "#64748b"
    return (
        f'<span class="ptf-insight-tag is-ticker" style="--tag-tone:{html.escape(tone)};">'
        '<span class="ptf-insight-tag-dot"></span>'
        f"<span>{html.escape(ticker)}</span>"
        "</span>"
    )


def _cell_tooltip(item: PortfolioInsight) -> str:
    message = str(item.message or "").strip()
    action = str(item.action or "").strip()
    if message and action:
        tooltip = f"{message} — {action}"
    else:
        tooltip = message or action
    return html.escape(tooltip)


def _insight_cell_html(item: PortfolioInsight) -> str:
    severity_class = _severity_class(item.severity)
    tooltip = _cell_tooltip(item)
    message = html.escape(str(item.message or "").strip())
    action = html.escape(str(item.action or "").strip())
    message_html = f'<div class="ptf-insight-cell-message">{message}</div>' if message else ""
    action_html = f'<div class="ptf-insight-cell-action">{action}</div>' if action else ""
    return (
        f'<div class="ptf-insight-cell is-{severity_class}" title="{tooltip}">'
        f"{_area_badge(item.area)}"
        f'<div class="ptf-insight-cell-title">{html.escape(item.title)}</div>'
        f"{message_html}"
        f"{action_html}"
        f"{_ticker_chip_html(item)}"
        "</div>"
    )


def _sort_key(item: PortfolioInsight) -> tuple[int, int]:
    severity = str(getattr(item, "severity", "") or "").strip().lower()
    return (_SEVERITY_ORDER.get(severity, 9), -int(getattr(item, "rank", 0) or 0))


def _build_portfolio_insights_html(insights: Iterable[PortfolioInsight], theme: Any) -> str:
    _ = theme
    items = sorted(list(insights or []), key=_sort_key)
    if not items:
        return ""

    cells_html = "".join(_insight_cell_html(item) for item in items)

    return f"""
    <div class="ptf-insights-shell">
      <div class="ptf-insights-head">
        <div>
          <span class="ptf-insights-eyebrow">Lettura operativa</span>
          <div class="ptf-insights-title">Radar decisionale portafoglio</div>
        </div>
        <div class="ptf-insights-sync">tabella, trend e SATOR</div>
      </div>
      <div class="ptf-insights-grid">
        {cells_html}
      </div>
    </div>
    """.strip()


def render_portfolio_insights(insights: Iterable[PortfolioInsight], theme: Any) -> None:
    html_block = _build_portfolio_insights_html(insights, theme)
    if html_block:
        st.markdown(html_block, unsafe_allow_html=True)
