"""Renderer HTML per insight decisionali compatti."""

from __future__ import annotations

import html
from typing import Any, Iterable

import streamlit as st

from core.services.portfolio_insights import PortfolioInsight
from ui.charts.natura_icons import get_natura_visual
from ui.components import _section_icon_svg
from ui.theme import bucket_color, macro_color


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
_RADAR_AREAS = {"Giornata", "Trend", "Cambio segno"}


def _severity_class(severity: str) -> str:
    normalized = str(severity or "info").strip().lower()
    if normalized in {"critical", "warning", "positive"}:
        return normalized
    return "info"


def _area_meta(area: str) -> tuple[str, str]:
    return _AREA_META.get(str(area or ""), _AREA_META["Stato"])


def _area_badge(area: str, *, compact: bool = False) -> str:
    color, icon_key = _area_meta(area)
    label_class = "ptf-insight-row-label" if compact else "ptf-insight-area"
    return (
        f'<div class="{label_class}" style="--area-tone:{html.escape(color)};">'
        f'<span class="ptf-insight-icon">{_section_icon_svg(icon_key)}</span>'
        f'<span>{html.escape(area or "Stato")}</span>'
        '</div>'
    )


def _tag_html(label: str, tone: str, kind: str, icon: str = "") -> str:
    if not label:
        return ""
    icon_html = f'<span class="ptf-insight-tag-icon">{icon}</span>' if icon else '<span class="ptf-insight-tag-dot"></span>'
    return (
        f'<span class="ptf-insight-tag is-{html.escape(kind)}" style="--tag-tone:{html.escape(tone)};">'
        f'{icon_html}'
        f'<span>{html.escape(label)}</span>'
        '</span>'
    )


def _instrument_block(item: PortfolioInsight, theme: Any) -> str:
    tags: list[str] = []
    category = str(getattr(item, "category", "") or "").strip().upper()
    bucket = str(getattr(item, "bucket", "") or "").strip()
    ticker = str(getattr(item, "ticker", "") or "").strip().upper()
    name = str(getattr(item, "name", "") or "").strip()
    natura = str(getattr(item, "natura", "") or "").strip()

    category_tone = macro_color(category) if category else "#64748b"
    identity = ""
    if ticker:
        natura_tone = category_tone
        natura_svg = ""
        if natura:
            natura_tone, natura_svg = get_natura_visual(natura)
        icon_html = (
            f'<span class="ptf-insight-identity-icon" title="{html.escape(natura or "Strumento")}">{natura_svg}</span>'
            if natura_svg
            else '<span class="ptf-insight-identity-icon"><span class="ptf-insight-tag-dot"></span></span>'
        )
        name_html = (
            f'<span class="ptf-insight-identity-name">{html.escape(name)}</span>'
            if name and name.upper() != ticker
            else ""
        )
        identity = (
            f'<div class="ptf-insight-identity" style="--instrument-tone:{html.escape(category_tone)};'
            f'--natura-tone:{html.escape(natura_tone)};">'
            f'{icon_html}'
            '<span class="ptf-insight-identity-text">'
            f'<span class="ptf-insight-identity-ticker">{html.escape(ticker)}</span>'
            f'{name_html}'
            '</span>'
            '</div>'
        )
    if category:
        tags.append(_tag_html(category, category_tone, "category"))
    if bucket:
        tags.append(_tag_html(bucket, bucket_color(bucket, theme), "bucket"))
    if not tags and not identity:
        return ""
    tags_html = f'<div class="ptf-insight-tags">{"".join(tags)}</div>' if tags else ""
    return f'<div class="ptf-insight-instrument-block">{tags_html}{identity}</div>'


def _insight_text_block(item: PortfolioInsight, theme: Any, *, lead: bool = False) -> str:
    title_class = "ptf-insight-main" if lead else "ptf-insight-row-title"
    text_class = "ptf-insight-message" if lead else "ptf-insight-row-text"
    action_class = "ptf-insight-action" if lead else "ptf-insight-row-action"
    return (
        f'<div class="{title_class}">{html.escape(item.title)}</div>'
        f'<div class="{text_class}">{html.escape(item.message)}</div>'
        f'<div class="{action_class}">{html.escape(item.action)}</div>'
        f'{_instrument_block(item, theme)}'
    )


def _radar_item_html(item: PortfolioInsight, theme: Any) -> str:
    severity_class = _severity_class(item.severity)
    return (
        f'<div class="ptf-insights-radar-item is-{severity_class}">'
        f'<div class="ptf-insights-radar-title">{html.escape(item.title)}</div>'
        f'<div class="ptf-insights-radar-text">{html.escape(item.message)}</div>'
        f'{_instrument_block(item, theme)}'
        '</div>'
    )


def _build_portfolio_insights_html(insights: Iterable[PortfolioInsight], theme: Any) -> str:
    items = list(insights or [])
    if not items:
        return ""

    radar_items = [item for item in items if item.area in _RADAR_AREAS][:4]
    decision_items = [item for item in items if item not in radar_items]
    lead = decision_items[0] if decision_items else items[0]
    radar_items = [item for item in radar_items if item != lead]
    others = [item for item in decision_items[1:] if item != lead]
    lead_class = _severity_class(lead.severity)
    radar_html = "".join(_radar_item_html(item, theme) for item in radar_items)
    if radar_html:
        radar_html = (
            '<div class="ptf-insights-radar">'
            '<div class="ptf-insights-radar-head">Radar operativo</div>'
            f'{radar_html}'
            '</div>'
        )
    rows: list[str] = []
    for item in others:
        severity_class = _severity_class(item.severity)
        rows.append(
            f"""
            <div class="ptf-insights-row is-{severity_class}">
              {_area_badge(item.area, compact=True)}
              <div>
                {_insight_text_block(item, theme)}
              </div>
            </div>
            """.strip()
        )
    rows_html = "".join(rows) if rows else (
        '<div class="ptf-insights-row is-info">'
        f'{_area_badge("Stato", compact=True)}'
        '<div><div class="ptf-insight-row-title">Nessun secondo segnale rilevante</div>'
        '<div class="ptf-insight-row-text">La priorita principale e sufficiente per questa lettura.</div></div>'
        '</div>'
    )

    return f"""
    <div class="ptf-insights-shell">
      <div class="ptf-insights-head">
        <div>
          <span class="ptf-insights-eyebrow">Lettura operativa</span>
          <div class="ptf-insights-title">Radar decisionale portafoglio</div>
        </div>
        <div class="ptf-insights-sync">tabella, trend e SATOR</div>
      </div>
      <div class="ptf-insights-body">
        <div class="ptf-insights-lead is-{lead_class}">
          {_area_badge(lead.area)}
          {_insight_text_block(lead, theme, lead=True)}
          {radar_html}
        </div>
        <div class="ptf-insights-list">
          {rows_html}
        </div>
      </div>
    </div>
    """.strip()


def render_portfolio_insights(insights: Iterable[PortfolioInsight], theme: Any) -> None:
    html_block = _build_portfolio_insights_html(insights, theme)
    if html_block:
        st.markdown(html_block, unsafe_allow_html=True)
