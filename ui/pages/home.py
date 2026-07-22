"""
ui/pages/home.py — Tab Portafoglio (t1): tabella posizioni, KPI, grafici
Pure rendering with service functions and centralized theme.
"""
import html
from types import SimpleNamespace
from typing import Any

import pandas as pd
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from core.asset_categories import get_selected_category_codes
from core.cache_signatures import build_portfolio_data_signature, charts_settings_signature, theme_signature
from core.data_models import ThemeConfig
from core.figure_cache import CachingStrategy, get_figure_cache
from persistence.storage import get_proventi_normalizzati
from core.render_profiler import profile_step
from core.settings_profiles import resolve_figure_cache_strategy

from core.services import (
    build_pl_delta_series,
    build_weekly_pl_table,
)
from persistence.storage import macro_cat
from core.finance import build_proventi_summary
from ui.formatting import fmt_eur_it, fmt_pct_it, fmt_num_it, fmtds
from ui.i18n import t
from ui.theme import CATEGORY_COLORS, get_theme_context, instrument_color, macro_color
from ui.components import (
    macro_legend_html,
    legend_block, kpi_card, build_price_direction_map,
    render_styled_table, back_to_top, vertical_gap, should_render_section, render_section_title,
)
from ui.charts.axes import zero_aligned_ranges
from ui.charts.overview import build_overview_time_chart
from ui.charts.home import (
    build_category_allocation_pie_chart,
    build_category_bar_chart,
    build_concentration_chart,
    build_instrument_allocation_pie_chart,
    build_instrument_bar_chart,
    build_portfolio_pl_chart,
    build_portfolio_pl_category_chart,
)
from ui.charts.portfolio_popup import render_portfolio_table_with_popup, render_weekly_pl_table
from ui.charts.tables import color_pl, style_macro_cols
from ui.page_chrome import render_page_intro as render_page_intro_shared
from ui.charts.settings import apply_settings


def _normalize_best_worst_name_block(name: str, companion_name: str, threshold: int = 26) -> str:
    """Aggiunge una riga invisibile al nome più corto quando il compagno va a capo."""
    this_wraps = len(str(name or "")) > threshold
    other_wraps = len(str(companion_name or "")) > threshold
    if not this_wraps and other_wraps:
        return f"{name}<br><span style='visibility:hidden;'>.</span>"
    return name


def _as_date_key(value: Any) -> str:
    try:
        ts = pd.to_datetime(value, errors="coerce")
        if pd.isna(ts):
            return ""
        return str(ts.date())
    except Exception:
        return ""


def _build_last_day_income_context(dfh: pd.DataFrame, data: dict[str, Any] | None = None) -> dict[str, Any]:
    if dfh is None or dfh.empty:
        return {"date": "", "total_net": 0.0, "by_ticker": {}}
    last_date_key = _as_date_key(dfh.iloc[-1].get("Data"))
    by_ticker: dict[str, float] = {}
    total_net = 0.0
    for item in get_proventi_normalizzati(data or {}):
        if _as_date_key(item.get("data")) != last_date_key:
            continue
        ticker = str(item.get("ticker") or "")
        netto = float(item.get("importo_netto", 0.0) or 0.0)
        if not ticker or abs(netto) <= 1e-12:
            continue
        by_ticker[ticker] = by_ticker.get(ticker, 0.0) + netto
        total_net += netto
    return {"date": last_date_key, "total_net": total_net, "by_ticker": by_ticker}


def _build_last_day_market_only_history(
    dfh: pd.DataFrame,
    data: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Restituisce una vista storica depurata dai proventi cumulati incassati."""
    if dfh is None or dfh.empty:
        return dfh

    income_by_date: dict[str, float] = {}
    for item in get_proventi_normalizzati(data or {}):
        date_key = _as_date_key(item.get("data"))
        if not date_key:
            continue
        netto = float(item.get("importo_netto", 0.0) or 0.0)
        if abs(netto) <= 1e-12:
            continue
        income_by_date[date_key] = income_by_date.get(date_key, 0.0) + netto

    if not income_by_date:
        return dfh

    adjusted = dfh.copy()
    adjusted_dates = adjusted["Data"].apply(_as_date_key)
    cumulative_income = 0.0
    cumulative_series: list[float] = []
    for date_key in adjusted_dates:
        cumulative_income += float(income_by_date.get(date_key, 0.0) or 0.0)
        cumulative_series.append(cumulative_income)

    cumulative_income_series = pd.Series(cumulative_series, index=adjusted.index, dtype="float64")
    for column in ("P/L", "Valore", "Liquidita", "Liquidità"):
        if column in adjusted.columns:
            adjusted[column] = pd.to_numeric(adjusted[column], errors="coerce").sub(cumulative_income_series, fill_value=0.0)
    return adjusted


def _build_last_day_contributors_report(
    dfh: pd.DataFrame,
    info_map: dict[str, dict[str, Any]] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Helper della Home: contributori migliori/peggiori dell'ultima giornata."""
    if dfh is None or len(dfh) < 2:
        return None

    info_map = info_map or {}
    price_history = (data or {}).get("storico_prezzi", {})
    last = dfh.iloc[-1]
    prev = dfh.iloc[-2]
    pl_cols = [c for c in dfh.columns if c.startswith("PL_")]
    if not pl_cols:
        return None

    contributors: list[dict[str, Any]] = []
    for col in pl_cols:
        tk = col[3:]
        try:
            v_last = float(last[col]) if pd.notna(last[col]) else None
            v_prev = float(prev[col]) if pd.notna(prev[col]) else None
            if v_last is None or v_prev is None:
                continue
            delta = v_last - v_prev
            info = info_map.get(tk, {})
            ticker_history: list[tuple[str, Any]] = []
            for raw_date, values in price_history.items():
                if not isinstance(values, dict) or tk not in values:
                    continue
                ticker_history.append((raw_date, values.get(tk)))
            ticker_history.sort(key=lambda item: item[0])
            pct_change = None
            current_value = None
            if info.get("prezzo") is not None and info.get("qt") is not None:
                try:
                    current_value = float(info.get("prezzo")) * float(info.get("qt"))
                except (TypeError, ValueError):
                    current_value = None
            if current_value is not None:
                previous_value = current_value - delta
                if previous_value not in (None, 0):
                    pct_change = delta / previous_value
            elif len(ticker_history) >= 2:
                try:
                    prev_price = float(ticker_history[-2][1])
                    last_price = float(ticker_history[-1][1])
                    if prev_price != 0:
                        pct_change = (last_price - prev_price) / prev_price
                except (TypeError, ValueError):
                    pct_change = None
            contributors.append(
                {
                    "ticker": tk,
                    "name": info.get("nome") or tk,
                    "delta": delta,
                    "pct_change": pct_change,
                    "category": macro_cat(info.get("tipo", "")),
                }
            )
        except Exception:
            continue

    positives = [item for item in contributors if item["delta"] > 0]
    negatives = [item for item in contributors if item["delta"] < 0]
    positives.sort(key=lambda item: item["delta"], reverse=True)
    negatives.sort(key=lambda item: item["delta"])

    return {
        "up_count": len(positives),
        "down_count": len(negatives),
        "best": positives,
        "worst": negatives,
    }


def _compute_home_category_deltas(
    dfh: pd.DataFrame,
    data: dict[str, Any],
    prev_idx: int | None = None,
) -> dict[str, dict[str, float]]:
    """Helper della Home: delta P/L per categoria nell'ultima giornata."""
    if prev_idx is None:
        prev_idx = len(dfh) - 2
    if len(dfh) < 2 or prev_idx < 0:
        return {}

    last = dfh.iloc[-1]
    prev = dfh.iloc[prev_idx]
    pl_cols = [c for c in dfh.columns if c.startswith("PL_")]
    if not pl_cols:
        return {}

    ticker_to_cat = {
        s.get("ticker", ""): macro_cat(s.get("tipo", ""))
        for s in data.get("strumenti", [])
    }
    category_deltas: dict[str, dict[str, float]] = {}
    for col in pl_cols:
        ticker = col[3:]
        cat = ticker_to_cat.get(ticker, "Altro")

        # Skip instruments where either last or prev row is NaN (avoids closing-event spikes)
        if not (pd.notna(last[col]) and pd.notna(prev[col])):
            continue

        v_last = float(last[col])
        v_prev = float(prev[col])
        delta = v_last - v_prev

        if cat not in category_deltas:
            category_deltas[cat] = {"delta_pl": 0, "max_pl": 0}
        category_deltas[cat]["delta_pl"] += delta
        category_deltas[cat]["max_pl"] = max(category_deltas[cat]["max_pl"], v_last)

    return category_deltas


def _build_last_day_summary(
    dfh: pd.DataFrame,
    info_map: dict[str, dict[str, Any]] | None = None,
    data: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> str | None:
    """Helper della Home: HTML della sintesi dell'ultima giornata disponibile."""
    if dfh is None or len(dfh) < 2:
        return None

    last = dfh.iloc[-1]
    prev = dfh.iloc[-2]
    delta_valore = float(last["Valore"]) - float(prev["Valore"])
    theme = get_theme_context()
    # Compute delta only from instruments open in BOTH rows (avoids closing-event spikes)
    raw_delta_pl = float(build_pl_delta_series(dfh, theme)["deltas"][-1])
    delta_capitale = float(last.get("Capitale", 0.0)) - float(prev.get("Capitale", 0.0))
    last_date = fmtds(last["Data"])
    prev_date = fmtds(prev["Data"])
    income_context = _build_last_day_income_context(dfh, data)
    day_income = float(income_context.get("total_net", 0.0) or 0.0)
    delta_pl = raw_delta_pl - day_income

    prev_pl_value = float(prev["P/L"]) if float(prev["P/L"]) != 0 else 0.0
    pct_var = (delta_pl / prev_pl_value) if abs(prev_pl_value) > 1e-9 else 0

    col_green = theme.colors["success"]
    col_red = theme.colors["danger"]
    sign_color_v = col_green if delta_pl >= 0 else col_red
    sign_color_pl = col_green if delta_pl >= 0 else col_red

    pl_cols = [c for c in dfh.columns if c.startswith("PL_")]
    up_count = sum(
        1
        for col in pl_cols
        if pd.notna(last[col]) and pd.notna(prev[col]) and (float(last[col]) - float(prev[col])) > 0
    )
    down_count = sum(
        1
        for col in pl_cols
        if pd.notna(last[col]) and pd.notna(prev[col]) and (float(last[col]) - float(prev[col])) < 0
    )

    category_deltas = _compute_home_category_deltas(dfh, data or {}, len(dfh) - 2)
    report = _build_last_day_contributors_report(dfh, info_map, data) or {}
    best_items = list(report.get("best", []) or [])
    worst_items = list(report.get("worst", []) or [])
    visible_categories = list(get_selected_category_codes(settings))

    html_lines = []
    html_lines.append('<div style="display: grid; grid-template-columns: 0.8fr 1fr 0.8fr; gap: 12px; padding: 12px; background: var(--ptf-surface); border: 1px solid var(--ptf-border); border-radius: 8px;">')
    html_lines.append('<div style="display: flex; flex-direction: column; gap: 4px;">')
    html_lines.append(f'<div style="display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap;"><span style="font-size: 1.8rem; font-weight: 700; color: {sign_color_v};">{fmt_pct_it(pct_var, 2, signed=True)}</span><span title="Variazione percentuale del P/L dell&apos;ultima giornata rispetto al P/L del giorno precedente." style="font-size: 0.85rem; color: var(--ptf-muted); cursor:help;">Rendimento giorno ⓘ</span><span style="font-size: 1rem; font-weight: 600; color: {sign_color_v};">{fmt_eur_it(delta_pl, 2, signed=True)}</span><span title="Variazione in euro del risultato di mercato dell&apos;ultima giornata." style="font-size: 0.8rem; color: {sign_color_pl}; font-weight: 600; cursor:help;">P/L giorno ⓘ</span></div>')
    if abs(day_income) > 1e-9:
        income_color = col_green if day_income >= 0 else col_red
        html_lines.append(f'<div style="font-size: 0.76rem; color: var(--ptf-muted);">Proventi della giornata: <span style="color:{income_color}; font-weight:600;">{fmt_eur_it(day_income, 2, signed=True)}</span></div>')
    if abs(delta_capitale) > 1e-9:
        flow_color = col_green if delta_capitale >= 0 else col_red
        html_lines.append(f'<div style="font-size: 0.76rem; color: var(--ptf-muted);">Flussi della giornata: <span style="color:{flow_color}; font-weight:600;">{fmt_eur_it(delta_capitale, 2, signed=True)}</span></div>')
    if abs(delta_valore - raw_delta_pl) > 1e-9:
        html_lines.append(f'<div style="font-size: 0.76rem; color: var(--ptf-muted);">Variazione lorda valore: {fmt_eur_it(delta_valore, 2, signed=True)}</div>')
    html_lines.append(f'<div style="font-size: 0.8rem; color: var(--ptf-muted);"><span style="color: {col_green}; font-weight: 600;">{up_count}▲</span> <span style="color: var(--ptf-muted);">/</span> <span style="color: {col_red}; font-weight: 600;">{down_count}▼</span></div>')
    html_lines.append(f'<div style="font-size: 0.75rem; color: var(--ptf-muted);">{last_date} vs {prev_date}</div>')
    html_lines.append('</div>')

    html_lines.append('<div style="display: flex; flex-direction: column; justify-content: center; gap: 8px; padding-left: 10px;">')
    max_delta = max((abs(category_deltas.get(c, {}).get("delta_pl", 0)) for c in visible_categories), default=1)
    for cat in visible_categories:
        color = CATEGORY_COLORS.get(cat, macro_color(cat))
        delta = category_deltas.get(cat, {}).get("delta_pl", 0)
        sign_color = col_green if delta >= 0 else col_red
        bar_width = int((abs(delta) / max_delta * 80)) if max_delta > 0 else 15
        justify = "flex-end" if delta < 0 else "flex-start"
        html_lines.append(
            f'<div>'
            f'<div style="display:flex; align-items:center; gap:8px;">'
            f'<div style="min-width:32px; font-size:0.75rem; font-weight:700; color:{color}; text-transform:uppercase;">{cat}</div>'
            f'<div style="position:relative; width:170px; height:14px;">'
            f'<div style="position:absolute; left:50%; top:0; bottom:0; width:1px; background:rgba(148,163,184,0.45);"></div>'
            f'<div style="position:absolute; top:4px; {"left:calc(50% - " + str(bar_width) + "px);" if delta < 0 else "left:50%;"} display:flex; justify-content:{justify};">'
            f'<div style="background:{sign_color}; height:6px; border-radius:3px; width:{bar_width}px;"></div>'
            f'</div></div>'
            f'<div style="font-size:0.8rem; color:{sign_color}; font-weight:600;">{fmt_eur_it(delta, 2, signed=True)}</div>'
            f'</div></div>'
        )
    html_lines.append('</div>')

    html_lines.append('<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; align-items: center;">')
    best_item = best_items[0] if best_items else None
    worst_item = worst_items[0] if worst_items else None
    if best_item or worst_item:
        nome_best = (
            info_map.get(best_item["ticker"], {}).get("nome", best_item["ticker"])
            if best_item and info_map else (best_item["ticker"] if best_item else "")
        )
        nome_worst = (
            info_map.get(worst_item["ticker"], {}).get("nome", worst_item["ticker"])
            if worst_item and info_map else (worst_item["ticker"] if worst_item else "")
        )
        nome_best_html = _normalize_best_worst_name_block(str(nome_best), str(nome_worst))
        nome_worst_html = _normalize_best_worst_name_block(str(nome_worst), str(nome_best))
        if best_item and abs(float(best_item.get("delta", 0.0) or 0.0)) > 0:
            html_lines.append(
                f'<div style="min-width:0;"><div style="font-size: 0.75rem; color: {col_green}; text-transform: uppercase; font-weight: 600;">▲ Best</div>'
                f'<div style="font-size: 0.75rem; color: var(--ptf-text); font-weight: 500; line-height: 1.1; word-break: break-word;">{nome_best_html}</div>'
                f'<div style="font-size: 0.8rem; color: {col_green}; font-weight: 600; margin-top: 2px;">{fmt_eur_it(float(best_item.get("delta", 0.0) or 0.0), 2, signed=True)}</div></div>'
            )
        else:
            html_lines.append('<div></div>')
        if worst_item and abs(float(worst_item.get("delta", 0.0) or 0.0)) > 0:
            html_lines.append(
                f'<div style="min-width:0;"><div style="font-size: 0.75rem; color: {col_red}; text-transform: uppercase; font-weight: 600;">▼ Worst</div>'
                f'<div style="font-size: 0.75rem; color: var(--ptf-text); font-weight: 500; line-height: 1.1; word-break: break-word;">{nome_worst_html}</div>'
                f'<div style="font-size: 0.8rem; color: {col_red}; font-weight: 600; margin-top: 2px;">{fmt_eur_it(float(worst_item.get("delta", 0.0) or 0.0), 2, signed=True)}</div></div>'
            )
        else:
            html_lines.append('<div></div>')
    html_lines.append('</div>')
    html_lines.append('</div>')

    return '\n'.join(html_lines)


def _render_last_day_contributors_tables(dfh_top: pd.DataFrame, data: dict[str, Any], theme: ThemeConfig) -> None:
    """Mostra titoli migliori e peggiori dell'ultima giornata in due box affiancati di pari altezza."""
    info_map = {s["ticker"]: s for s in data.get("strumenti", [])}
    report = _build_last_day_contributors_report(dfh_top, info_map, data)
    if not report:
        return

    best_items = report.get("best", [])
    worst_items = report.get("worst", [])
    if not best_items and not worst_items:
        return

    row_count = max(len(best_items), len(worst_items), 1)
    table_height = max(220, 74 + row_count * 35)

    def _build_table(items: list[dict[str, Any]], empty_label: str) -> pd.DataFrame:
        if not items:
            return pd.DataFrame(
                [{"Ticker": "—", "Strumento": empty_label, "Var. su Ctv %": None, "Delta €": None, "_category": ""}]
            )
        rows = []
        for item in items:
            ticker = str(item.get("ticker", "") or "")
            rows.append(
                {
                    "Ticker": ticker,
                    "Strumento": str(item.get("name", "") or ticker),
                    "Var. su Ctv %": item.get("pct_change"),
                    "Delta €": item.get("delta"),
                    "_category": str(item.get("category", "") or ""),
                }
            )
        return pd.DataFrame(rows)

    def _render_table(title: str, accent: str, items: list[dict[str, Any]], empty_label: str) -> None:
        table_df = _build_table(items, empty_label)
        display_df = table_df[["Ticker", "Strumento", "Var. su Ctv %", "Delta €"]]

        def _ticker_style(value: Any) -> str:
            match = table_df.loc[table_df["Ticker"] == value, "_category"]
            category = match.iloc[0] if not match.empty else ""
            color = macro_color(str(category or ""))
            return f"color: {color}; font-weight: 700;"

        def _signed_text_style(value: Any) -> str:
            if value is None or pd.isna(value):
                return ""
            numeric_value = float(value)
            if numeric_value < 0:
                return f"color: {theme.color_red}; font-weight: 600;"
            if numeric_value > 0:
                return f"color: {theme.color_green}; font-weight: 600;"
            return ""

        styler = (
            display_df.style
            .map(_ticker_style, subset=["Ticker"])
            .map(_signed_text_style, subset=["Var. su Ctv %", "Delta €"])
            .format({
                "Var. su Ctv %": lambda v: "—" if v is None or pd.isna(v) else fmt_pct_it(v, 2, signed=True),
                "Delta €": lambda v: "—" if v is None or pd.isna(v) else fmt_eur_it(v, 2, signed=True),
            })
        )

        st.markdown(
            f"<div style='font-size:0.76rem; font-weight:700; color:{accent}; text-transform:uppercase; letter-spacing:0.02em; margin:0 0 6px 0;'>{title} ({len(items)})</div>",
            unsafe_allow_html=True,
        )
        render_styled_table(
            styler,
            height=table_height,
            column_config={
                "Ticker": st.column_config.TextColumn(width="small"),
                "Strumento": st.column_config.TextColumn(width="medium"),
                "Var. su Ctv %": st.column_config.NumberColumn(width="small"),
                "Delta €": st.column_config.NumberColumn(width="small"),
            },
        )

    c_best, c_worst = st.columns(2)
    with c_best:
        _render_table("▲ BEST - TITOLI MIGLIORI", theme.color_green, best_items, "Nessun titolo in rialzo")
    with c_worst:
        _render_table("▼ WORST - TITOLI PEGGIORI", theme.color_red, worst_items, "Nessun titolo in calo")


def _render_home_andamento_clone(
    dfh_top: pd.DataFrame,
    data: dict[str, Any],
    theme: ThemeConfig,
    settings: dict[str, Any] | None = None,
    chart_loader=None,
) -> None:
    """Replica nella scheda Portafoglio il solo grafico Profit / Loss Complessivo."""
    dfh_market_only = _build_last_day_market_only_history(dfh_top, data)
    income_context = _build_last_day_income_context(dfh_top, data)
    home_pl_extra_params = {
        "rows": len(dfh_market_only),
        "market_view": "last_day_net_proventi_cumulative_v2",
        "last_day": str(income_context.get("date") or ""),
        "last_day_income": round(float(income_context.get("total_net", 0.0) or 0.0), 6),
    }
    with profile_step("Portafoglio/UltimaGiornata", "build delta series", count=len(dfh_market_only)):
        delta_data = build_pl_delta_series(dfh_market_only, theme)
    with profile_step("Portafoglio/UltimaGiornata", "load fig portfolio pl", count=len(dfh_top)):
        if chart_loader is None:
            fig = build_portfolio_pl_chart(
                dfh_market_only,
                delta_data["colors"],
                delta_data["delta_text"],
                "%d/%m/%Y",
                theme,
            )
            apply_settings(fig, 'home_portfolio_pl')
        else:
            fig = chart_loader(
                "home_portfolio_pl",
                lambda: apply_settings(
                    build_portfolio_pl_chart(
                        dfh_market_only,
                        delta_data["colors"],
                        delta_data["delta_text"],
                        "%d/%m/%Y",
                        theme,
                    ),
                    "home_portfolio_pl",
                ),
                extra_params=home_pl_extra_params,
            )
    with profile_step("Portafoglio/UltimaGiornata", "render fig portfolio pl"):
        st.plotly_chart(fig, width="stretch")
    with profile_step("Portafoglio/UltimaGiornata", "load fig portfolio pl category", count=len(dfh_top)):
        fig_cat = (
            apply_settings(build_portfolio_pl_category_chart(dfh_top, data, theme, settings=settings), 'home_portfolio_pl_category')
            if chart_loader is None
            else chart_loader(
                "home_portfolio_pl_category",
                lambda: apply_settings(
                    build_portfolio_pl_category_chart(dfh_top, data, theme, settings=settings),
                    'home_portfolio_pl_category',
                ),
                extra_params={"rows": len(dfh_top), "cats": "|".join(get_selected_category_codes(settings))},
            )
        )
    if len(fig_cat.data) > 0:
        with profile_step("Portafoglio/UltimaGiornata", "render fig portfolio pl category"):
            st.plotly_chart(fig_cat, width="stretch")


def _render_portfolio_table_section(
    da: pd.DataFrame,
    dfh_top: pd.DataFrame,
    data: dict[str, Any],
    proventi: list[dict[str, Any]] | None,
    tv: float,
    theme: ThemeConfig,
    settings: dict[str, Any] | None = None,
    macro_summary: pd.DataFrame | None = None,
    chart_loader=None,
) -> None:
    """Mostra tabella posizioni, ultimo giorno, allocazione e concentrazione."""
    settings = settings or {}
    if not da.empty:
        with profile_step("Portafoglio", "render tabella posizioni", count=len(da)):
            _price_direction_map = build_price_direction_map(data)
            render_portfolio_table_with_popup(da, data, direction_map=_price_direction_map)
            legend_block(
                "Posizioni attualmente in portafoglio con quantità, prezzo corrente, costo medio di carico, controvalore e risultato. "
                + macro_legend_html(settings) +
                " Prima del ticker la freccia indica il movimento rispetto alla giornata precedente: verde verso l'alto in caso di aumento, rossa verso il basso in caso di calo, linea orizzontale in caso di stabilità."
            )

        if should_render_section("Portafoglio", "Andamento ultima giornata", settings):
            if not dfh_top.empty and len(dfh_top) > 1:
                with profile_step("Portafoglio", "render andamento ultima giornata", count=len(dfh_top)):
                    _home_info_map = {s["ticker"]: s for s in data.get("strumenti", [])}
                    with profile_step("Portafoglio/UltimaGiornata", "build sintesi html", count=len(dfh_top)):
                        _home_last_day_html = _build_last_day_summary(dfh_top, _home_info_map, data, settings)
                    if _home_last_day_html:
                        with profile_step("Portafoglio/UltimaGiornata", "render header e html"):
                            render_section_title(
                                "Andamento dell'ultima giornata",
                                icon="quotes",
                                gap_after="xs",
                            )
                            st.markdown(_home_last_day_html, unsafe_allow_html=True)
                            st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)
                        with profile_step("Portafoglio/UltimaGiornata", "render tabelle best worst"):
                            _render_last_day_contributors_tables(dfh_top, data, theme)
                        with profile_step("Portafoglio/UltimaGiornata", "render grafico andamento clone", count=len(dfh_top)):
                            st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)
                            _render_home_andamento_clone(dfh_top, data, theme, settings, chart_loader=chart_loader)

        if should_render_section("Portafoglio", "Andamento dell'ultima settimana", settings):
            with profile_step("Portafoglio", "render andamento ultima settimana", count=len(da)):
                weekly = build_weekly_pl_table(da, dfh_top, data)
                if weekly:
                    render_section_title(
                        "Andamento dell'ultima settimana",
                        icon="quotes",
                        gap_after="xs",
                    )
                    render_weekly_pl_table(weekly, da, data)
                    legend_block(
                        "P/L giornaliero per strumento negli ultimi giorni di quotazione disponibili, calcolato come "
                        "variazione del risultato non realizzato (quantità × prezzo − costo) rispetto al giorno "
                        "precedente. La colonna P/L totale è la somma dei giorni mostrati in tabella, non il P/L "
                        "complessivo dello strumento. Celle vuote: strumento non ancora in portafoglio in quella data."
                    )

        if should_render_section("Portafoglio", "P/L per Categoria", settings):
            if not dfh_top.empty and len(dfh_top) > 1:
                with profile_step("Portafoglio", "render P/L per categoria", count=len(dfh_top)):
                    render_section_title(
                        "P/L per Categoria",
                        icon="chart",
                        gap_after="xs",
                    )
                    if chart_loader is None:
                        fig_cat_history = build_overview_time_chart(
                            dfh_top, da, "P/L per Categoria", None, 0.0, None, None, theme, settings=settings, total_return=None
                        )
                    else:
                        fig_cat_history = chart_loader(
                            "overview_pl_categoria",
                            lambda: build_overview_time_chart(
                                dfh_top, da, "P/L per Categoria", None, 0.0, None, None, theme, settings=settings, total_return=None
                            ),
                            extra_params={"rows": len(dfh_top), "cats": "|".join(get_selected_category_codes(settings))},
                        )
                    st.plotly_chart(fig_cat_history, width="stretch")
                    legend_block(
                        "Andamento storico del P/L delle categorie visibili, sovrapposte (area impilata)."
                    )

        if should_render_section("Portafoglio", "Proventi per strumento", settings):
            _render_proventi_section(proventi, data)

        if should_render_section("Portafoglio", "Sintesi allocazione", settings):
            render_section_title(
                "Sintesi allocazione",
                icon="portfolio",
                gap_after="xs",
            )
        with profile_step("Portafoglio", "render sintesi allocazione", count=len(macro_summary) if isinstance(macro_summary, pd.DataFrame) else 0):
            legend_block(
                "Riepilogo rapido di peso, risultato e concentrazione. Il peso percentuale aiuta a capire quanto ogni area influenzi il portafoglio complessivo, mentre la concentrazione evidenzia se pochi strumenti incidono in modo dominante."
            )

            # Use service to build macro summary
            macro_summary = macro_summary.copy() if isinstance(macro_summary, pd.DataFrame) else pd.DataFrame()
            if not macro_summary.empty:
                display_summary = macro_summary.copy()
                for col in ["Costo", "Controvalore", "P/L €"]:
                    display_summary[col] = display_summary[col].apply(lambda v: fmt_eur_it(v, 2))
                for col in ["Peso %", "P/L %"]:
                    display_summary[col] = display_summary[col].apply(lambda v: fmt_pct_it(v, 2))

                styled = (
                    display_summary[["Tipologia", "Costo", "Controvalore", "Peso %", "P/L €", "P/L %"]].style
                    .apply(style_macro_cols, axis=1)
                    .map(color_pl, subset=["P/L €", "P/L %"])
                )
                render_styled_table(styled, height="content")

        if len(da) >= 2:
            with profile_step("Portafoglio", "render grafico concentrazione", count=len(da)):
                if chart_loader is None:
                    fig_conc = build_concentration_chart(da, tv, theme, settings=settings)
                    apply_settings(fig_conc, 'home_concentration')
                else:
                    fig_conc = chart_loader(
                        "home_concentration",
                        lambda: apply_settings(build_concentration_chart(da, tv, theme, settings=settings), 'home_concentration'),
                        extra_params={"items": len(da), "tv": round(float(tv or 0.0), 2)},
                    )
                st.plotly_chart(fig_conc, width="stretch")


def _render_performance_charts(
    da: pd.DataFrame,
    tv: float,
    theme: ThemeConfig,
    settings: dict[str, Any] | None = None,
    chart_loader=None,
) -> None:
    """Mostra pie chart allocazione e chart performance %."""
    with profile_step("Portafoglio", "render grafici allocazione e performance", count=len(da)):
        visible_categories = list(get_selected_category_codes(settings))
        categories_text = ", ".join(visible_categories)
        g1, g2 = st.columns(2)
        with g1:
            if not da.empty and tv > 0:
                legend_block(
                    "Come è ripartito il portafoglio tra i singoli strumenti in termini di valore. "
                    "Le fette molto piccole non riportano l'etichetta per non affollare il grafico, ma sono sempre visibili nella legenda.",
                    min_height=118
                )
                if chart_loader is None:
                    fig = build_instrument_allocation_pie_chart(da)
                    apply_settings(fig, 'home_instrument_pie')
                else:
                    fig = chart_loader(
                        "home_instrument_pie",
                        lambda: apply_settings(build_instrument_allocation_pie_chart(da), 'home_instrument_pie'),
                        extra_params={"items": len(da)},
                    )
                st.plotly_chart(fig, width="stretch")

        with g2:
            if not da.empty:
                fig = (
                    build_category_allocation_pie_chart(da, settings=settings)
                    if chart_loader is None
                    else chart_loader(
                        "home_category_allocation_pie",
                        lambda: build_category_allocation_pie_chart(da, settings=settings),
                        extra_params={"items": len(da), "cats": categories_text},
                    )
                )
                if fig is not None:
                    legend_block(
                        f"Distribuzione del portafoglio nelle macro-categorie visibili: {categories_text}. "
                        + macro_legend_html(settings),
                        min_height=118
                    )
                    st.plotly_chart(fig, width="stretch")

        _gp3, _gp4 = st.columns(2)
        with _gp3:
            ds = da.sort_values("P/L %")
            legend_block(
                "Rendimento percentuale di ciascuna posizione rispetto al costo di acquisto. Ogni strumento mantiene lo stesso colore usato nei grafici a torta per un riconoscimento immediato.",
                min_height=118
            )
            if chart_loader is None:
                fig = build_instrument_bar_chart(ds, "P/L %", "Performance %", fmt_pct_it, ".0%", 1)
                apply_settings(fig, 'home_instrument_bar_perf')
            else:
                fig = chart_loader(
                    "home_instrument_bar_perf",
                    lambda: apply_settings(build_instrument_bar_chart(ds, "P/L %", "Performance %", fmt_pct_it, ".0%", 1), 'home_instrument_bar_perf'),
                    extra_params={"items": len(ds)},
                )
            st.plotly_chart(fig, width="stretch")

        with _gp4:
            ds2 = da.sort_values("P/L €")
            legend_block(
                "Guadagno o perdita in euro di ciascuna posizione. Le barre più lunghe identificano i titoli che pesano di più sul risultato complessivo, positivo o negativo.",
                min_height=118
            )
            if chart_loader is None:
                fig = build_instrument_bar_chart(ds2, "P/L €", "P/L in Euro", fmt_eur_it, ",", 0)
                apply_settings(fig, 'home_instrument_bar_pl')
            else:
                fig = chart_loader(
                    "home_instrument_bar_pl",
                    lambda: apply_settings(build_instrument_bar_chart(ds2, "P/L €", "P/L in Euro", fmt_eur_it, ",", 0), 'home_instrument_bar_pl'),
                    extra_params={"items": len(ds2)},
                )
            st.plotly_chart(fig, width="stretch")


def _render_category_analysis(
    da: pd.DataFrame,
    cat_agg: pd.DataFrame | None = None,
    settings: dict[str, Any] | None = None,
    chart_loader=None,
) -> None:
    """Mostra grafici per controvalore, P/L €, e P/L % per categoria."""
    if not da.empty:
        with profile_step("Portafoglio", "render analisi macro-categoria", count=len(da)):
            visible_categories = list(get_selected_category_codes(settings))
            categories_text = ", ".join(visible_categories)
            render_section_title(
                "Analisi per Macro-Categoria",
                comment=(
                    f"Vista di insieme per {categories_text}: controvalore attuale, risultato in euro e rendimento percentuale. "
                    "I grafici usano la stessa codifica a colori delle sezioni precedenti. "
                    + macro_legend_html(settings)
                ),
                icon="analysis",
            )
            if cat_agg is None:
                from core.services import get_category_allocation_breakdown
                cat_agg = get_category_allocation_breakdown(da, settings)
            cat_agg = cat_agg[cat_agg["Categoria"].isin(visible_categories)].copy()

            # Allinea la linea dello zero tra i 3 grafici affiancati: se una
            # categoria ha P/L €/% negativo, senza questo i 3 assi Y (unità
            # diverse, autorange indipendente) mostrerebbero lo zero ad altezze
            # diverse. Restituisce None per ciascuno se non ci sono negativi
            # (nessuna modifica al comportamento nel caso comune).
            value_range, pl_range, perf_range = zero_aligned_ranges([
                cat_agg["Controvalore"].tolist(),
                cat_agg["P/L €"].tolist(),
                cat_agg["P/L %"].tolist(),
            ])

            gc1, gc2, gc3 = st.columns(3)
            with gc1:
                if chart_loader is None:
                    fig = build_category_bar_chart(cat_agg, "Controvalore", "Controvalore", fmt_eur_it, ",", settings, y_range=value_range)
                else:
                    fig = chart_loader(
                        "home_category_bar_value",
                        lambda: build_category_bar_chart(cat_agg, "Controvalore", "Controvalore", fmt_eur_it, ",", settings, y_range=value_range),
                        extra_params={"items": len(cat_agg), "y_range": value_range},
                    )
                st.plotly_chart(fig, width="stretch")
            with gc2:
                if chart_loader is None:
                    fig = build_category_bar_chart(cat_agg, "P/L €", "P/L per Categoria", fmt_eur_it, ",", settings, y_range=pl_range)
                else:
                    fig = chart_loader(
                        "home_category_bar_pl",
                        lambda: build_category_bar_chart(cat_agg, "P/L €", "P/L per Categoria", fmt_eur_it, ",", settings, y_range=pl_range),
                        extra_params={"items": len(cat_agg), "y_range": pl_range},
                    )
                st.plotly_chart(fig, width="stretch")
            with gc3:
                if chart_loader is None:
                    fig = build_category_bar_chart(cat_agg, "P/L %", "Performance % per Categoria", fmt_pct_it, ".1%", settings, y_range=perf_range)
                else:
                    fig = chart_loader(
                        "home_category_bar_perf",
                        lambda: build_category_bar_chart(cat_agg, "P/L %", "Performance % per Categoria", fmt_pct_it, ".1%", settings, y_range=perf_range),
                        extra_params={"items": len(cat_agg), "y_range": perf_range},
                    )
                st.plotly_chart(fig, width="stretch")


def _flow_card(title: str, rows: list[tuple[str, str]], total_label: str, total_val: str, total_ok: bool) -> str:
    """HTML card per il flowchart finanziario. rows = [(label, valore_formattato), ...]"""
    tot_color = "#16a34a" if total_ok else "#dc2626"
    rows_html = "".join(
        f'<tr><td style="padding:2px 6px;font-size:12px;color:#888;">{lbl}</td>'
        f'<td style="padding:2px 6px;font-size:12px;font-weight:600;text-align:right;">{val}</td></tr>'
        for lbl, val in rows
    )
    return (
        f'<div style="border:1px solid #ccc;border-radius:8px;padding:10px 12px;'
        f'background:var(--background-color,#fff);min-height:120px;">'
        f'<div style="font-size:12px;font-weight:700;letter-spacing:.04em;'
        f'text-transform:uppercase;margin-bottom:6px;color:#666;">{title}</div>'
        f'<table style="width:100%;border-collapse:collapse;">{rows_html}'
        f'<tr style="border-top:1px solid #ddd;">'
        f'<td style="padding:4px 6px;font-size:13px;font-weight:700;">{total_label}</td>'
        f'<td style="padding:4px 6px;font-size:14px;font-weight:800;text-align:right;color:{tot_color};">'
        f'{total_val}</td></tr></table></div>'
    )


_ARROW_H = '<div style="display:flex;align-items:center;justify-content:center;height:100%;font-size:28px;color:#aaa;padding-top:30px;">&#8594;</div>'
_ARROW_V = '<div style="text-align:center;font-size:24px;color:#aaa;padding:4px 0;">&#8595;</div>'




def _render_proventi_section(proventi: list[dict[str, Any]], data: dict[str, Any]) -> None:
    """Mostra riepilogo proventi (cedole e dividendi)."""
    if proventi:
        with profile_step("Portafoglio", "render sezione proventi", count=len(proventi)):
            render_section_title(
                "Proventi per strumento",
                comment=(
                    "Riepilogo delle cedole e dei dividendi incassati per ogni strumento. "
                    "L'importo netto è al netto della ritenuta fiscale applicata."
                ),
                icon="income",
            )
            _info_map_prov = {s["ticker"]: s for s in data["strumenti"]}
            prov_summary = build_proventi_summary(proventi, _info_map_prov)
            if not prov_summary.empty:
                styled_prov = (
                    prov_summary.style
                    .format({
                        "Lordo totale": lambda v: fmt_eur_it(v, 2),
                        "Ritenute": lambda v: fmt_eur_it(v, 2),
                        "Netto totale": lambda v: fmt_eur_it(v, 2),
                        "N": lambda v: fmt_num_it(v, 0),
                    })
                )
                render_styled_table(styled_prov)


def render_home(tab: DeltaGenerator, ctx: SimpleNamespace) -> None:
    """Pure rendering for home page dashboard."""
    theme = get_theme_context()

    data = ctx.data
    da = ctx.da
    dfh_top = ctx.dfh_top
    tv = ctx.tv
    tc = ctx.tc
    pl = ctx.pl
    pl_color = ctx.pl_color
    patrimonio_totale = ctx.patrimonio_totale
    liquidita = ctx.liquidita_attuale
    proventi = ctx.proventi
    settings = ctx.settings if hasattr(ctx, 'settings') else {}
    macro_summary = getattr(ctx, "macro_summary_report", pd.DataFrame())
    data_sig = build_portfolio_data_signature(
        data,
        app_version=str(getattr(ctx, "app_version", "n/d")),
        schema_version=str(getattr(ctx, "schema_version", "n/d")),
    )
    theme_sig = theme_signature(theme)
    charts_sig = charts_settings_signature("ui/charts/settings.py")
    strategy_name = resolve_figure_cache_strategy(settings, st.session_state)
    if strategy_name == "disabled":
        cache_strategy = CachingStrategy.DISABLED
    elif strategy_name == "session_only":
        cache_strategy = CachingStrategy.SESSION_ONLY
    elif strategy_name == "disk_only":
        cache_strategy = CachingStrategy.DISK_ONLY
    else:
        cache_strategy = CachingStrategy.HYBRID
    fcache = get_figure_cache()

    def _chart_loader(chart_id: str, builder, *, extra_params: dict[str, Any] | None = None):
        return fcache.get_or_build(
            chart_id=chart_id,
            data_sig=data_sig,
            theme_sig=theme_sig,
            charts_settings_sig=charts_sig,
            builder=builder,
            page_mode="Completa",
            extra_params=extra_params or {},
            strategy=cache_strategy,
        )

    with tab:
        render_page_intro_shared(
            t(settings, "page_intro.portafoglio.title", "Home"),
            t(settings, "page_intro.portafoglio.comment", "Vista rapida del portafoglio: posizioni attive, andamento recente, allocazione per macro-categoria e proventi gia' incassati."),
            "portfolio",
            theme,
        )
        active_count = len(da.index) if not da.empty else 0
        _chiusi_tk = getattr(ctx, "chiusi_tickers", frozenset())
        total_count = sum(1 for s in data.get("strumenti", []) if str(s.get("ticker") or "") not in _chiusi_tk)
        suffix = f"{active_count} strumenti attivi su {total_count} censiti"
        if should_render_section("Portafoglio", "Controvalore del Portafoglio", settings):
            render_section_title(
                "Controvalore del Portafoglio",
                subtitle=suffix,
                icon="portfolio",
                gap_after="xs",
            )
            _render_portfolio_table_section(da, dfh_top, data, proventi, tv, theme, settings, macro_summary=macro_summary, chart_loader=_chart_loader)
            _render_performance_charts(da, tv, theme, settings, chart_loader=_chart_loader)

        vertical_gap("md")
        if should_render_section("Portafoglio", "Analisi per Macro-Categoria", settings):
            _render_category_analysis(da, getattr(ctx, "category_breakdown", None), settings, chart_loader=_chart_loader)
            vertical_gap("md")
        back_to_top(show_prev=True, show_next=True, nav_key="portafoglio")

