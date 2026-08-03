from __future__ import annotations

import html

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

from core.domain.returns import simple_period_return, trailing_period_return
from core.domain.risk import build_drawdown_series, rolling_sharpe, rolling_volatility_annualized
from persistence.storage import APP_VERSION, default_settings
from ui.charts.settings import apply_settings
from ui.formatting import fmt_eur_it, fmt_num_it, fmt_pct_it, hex_to_rgba
from ui.theme import P, get_theme_context, macro_color

# Ownership reale:
# - pagina: ui/pages/summary.py
# - chart_id principali: summary_history, summary_annual, summary_drawdown,
#   summary_allocation, summary_allocation_bar, summary_rolling_vol,
#   summary_rolling_sharpe, summary_pl_scatter, summary_rolling_12m


def _returns_scale_legend_html(min_v, max_v, positive, negative, muted, font_family):
    """Legenda min/max a gradiente, come i rendimenti mensili di justETF."""
    if min_v is None or max_v is None:
        return ""
    grad = (
        f"linear-gradient(to right, {hex_to_rgba(negative, 0.85)}, {hex_to_rgba(negative, 0.15)}, "
        f"rgba(148,163,184,0.12), {hex_to_rgba(positive, 0.15)}, {hex_to_rgba(positive, 0.85)})"
    )
    return (
        f"<div style='display:flex;align-items:center;gap:10px;margin-top:10px;font-family:{font_family};'>"
        f"<span style='font-size:0.76rem;color:{negative};font-weight:700;white-space:nowrap;'>Min {fmt_pct_it(min_v, 1, signed=True)}</span>"
        f"<div style='flex:1;height:9px;border-radius:5px;background:{grad};'></div>"
        f"<span style='font-size:0.76rem;color:{positive};font-weight:700;white-space:nowrap;'>Max {fmt_pct_it(max_v, 1, signed=True)}</span>"
        f"</div>"
    )


def _contrast_text_color(intensity, dark_color, light_text="#ffffff", threshold=0.42):
    """Testo bianco sopra soglia (sfondo saturo/scuro), colore scuro sotto (sfondo tenue) —
    evita il verde-su-verde/rosso-su-rosso illeggibile a intensita' alta."""
    return light_text if intensity > threshold else dark_color


def quarterly_table_html(quarterly_returns, theme=None):
    if theme is None:
        try:
            theme = get_theme_context()
        except Exception:
            theme = None
    surface = getattr(theme, "bg_surface", "#ffffff") if theme is not None else "#ffffff"
    text = getattr(theme, "font_color", "#223144") if theme is not None else "#223144"
    muted = getattr(theme, "muted_color", "#6c7a89") if theme is not None else "#6c7a89"
    border = getattr(theme, "border_color", "rgba(26,58,92,0.14)") if theme is not None else "rgba(26,58,92,0.14)"
    primary = getattr(theme, "color_blue", "#1a3a5c") if theme is not None else "#1a3a5c"
    positive = getattr(theme, "color_green", "#1a7a4a") if theme is not None else "#1a7a4a"
    negative = getattr(theme, "color_red", "#c0392b") if theme is not None else "#c0392b"
    font_family = (getattr(theme, "colors", {}) or {}).get("font_family", "system-ui, -apple-system, sans-serif") if theme is not None else "system-ui, -apple-system, sans-serif"
    top_border = hex_to_rgba(primary, 0.10) if isinstance(primary, str) and primary.startswith("#") else "rgba(26,58,92,0.10)"
    if not quarterly_returns:
        return f"<p style='color:{muted};font-size:0.92rem;font-family:{font_family};'>Dati storici insufficienti per il calcolo trimestrale.</p>"
    by_year = {}
    all_vals = []
    for r in quarterly_returns:
        yr, q = (int(r["year"]), int(r["quarter"]))
        by_year.setdefault(yr, {})[q] = float(r["ptf"])
        all_vals.append(float(r["ptf"]))
    abs_vals = sorted((abs(v) for v in all_vals if pd.notna(v)))
    p90 = abs_vals[int(len(abs_vals) * 0.90)] if abs_vals else 0.01

    def _cell(v, is_total=False):
        left_border = f"border-left:2px solid {border};" if is_total else ""
        if v is None:
            return f"<td style='text-align:center;color:{muted};padding:8px 11px;border-top:1px solid {top_border};{left_border}'>—</td>"
        intensity = min(abs(float(v)) / max(p90, 1e-6), 1.0)
        col = positive if float(v) >= 0 else negative
        bg = hex_to_rgba(col, 0.10 + 0.45 * intensity)
        txt_color = _contrast_text_color(intensity, col)
        return f"<td style='text-align:center;color:{txt_color};font-weight:600;padding:8px 11px;background:{bg};border-top:1px solid {top_border};{left_border}'>{fmt_pct_it(v, 1, signed=True)}</td>"

    rows_html = ""
    for yr in sorted(by_year.keys()):
        qtrs = by_year[yr]
        q_vals = [qtrs.get(q) for q in [1, 2, 3, 4]]
        ann = None
        try:
            prod = 1.0
            for v in q_vals:
                if v is not None:
                    prod *= 1.0 + v
            if any((v is not None for v in q_vals)):
                ann = prod - 1.0
        except Exception:
            pass
        rows_html += f"<tr style='background:{surface};'><td style='font-weight:700;padding:8px 11px;font-size:0.82rem;color:{text};border-top:1px solid {top_border};'>{yr}</td>" + "".join((_cell(q_vals[i]) for i in range(4))) + _cell(ann, is_total=True) + "</tr>"
    hdr = ("Anno", "T1", "T2", "T3", "T4", "TOT")

    def _hdr_style(i):
        align = "left" if i == 0 else "center"
        border_left = f"border-left:2px solid {hex_to_rgba('#ffffff', 0.30)};" if i == len(hdr) - 1 else ""
        return f"padding:8px 11px;text-align:{align};font-weight:700;font-size:0.78rem;letter-spacing:.03em;text-transform:uppercase;{border_left}"

    hdr_html = "".join((f"<th style='{_hdr_style(i)}'>{h}</th>" for i, h in enumerate(hdr)))
    legend = _returns_scale_legend_html(min(all_vals) if all_vals else None, max(all_vals) if all_vals else None, positive, negative, muted, font_family)
    return (
        f"<div style='font-family:{font_family};'>"
        f"<div style='overflow-x:auto;'><table style='width:100%;border-collapse:collapse;font-size:0.82rem;border:1px solid {border};border-radius:12px;overflow:hidden;background:{surface};'>"
        f"<thead><tr style='background:{primary};color:white;'>{hdr_html}</tr></thead><tbody>{rows_html}</tbody></table></div>"
        f"{legend}</div>"
    )


def monthly_heatmap_html(monthly_returns, theme=None):
    if theme is None:
        try:
            theme = get_theme_context()
        except Exception:
            theme = None
    surface = getattr(theme, "bg_surface", "#ffffff") if theme is not None else "#ffffff"
    muted = getattr(theme, "muted_color", "#6c7a89") if theme is not None else "#6c7a89"
    border = getattr(theme, "border_color", "rgba(26,58,92,0.14)") if theme is not None else "rgba(26,58,92,0.14)"
    primary = getattr(theme, "color_blue", "#1a3a5c") if theme is not None else "#1a3a5c"
    positive = getattr(theme, "color_green", "#1a7a4a") if theme is not None else "#1a7a4a"
    negative = getattr(theme, "color_red", "#c0392b") if theme is not None else "#c0392b"
    font_family = (getattr(theme, "colors", {}) or {}).get("font_family", "system-ui, -apple-system, sans-serif") if theme is not None else "system-ui, -apple-system, sans-serif"
    mesi_labels = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]
    if not monthly_returns:
        return f"<p style='color:{muted};font-size:0.92rem;font-family:{font_family};'>Dati mensili insufficienti.</p>"
    by_year = {}
    all_vals = []
    for r in monthly_returns:
        yr, mo = (int(r["year"]), int(r["month"]))
        by_year.setdefault(yr, {})[mo] = float(r["ptf"])
        all_vals.append(float(r["ptf"]))
    abs_vals = sorted((abs(v) for v in all_vals if pd.notna(v)))
    p90 = abs_vals[int(len(abs_vals) * 0.90)] if abs_vals else 0.01

    def _cell_color(v):
        if v is None:
            return f"color:{muted};background:{surface};"
        intensity = min(abs(float(v)) / max(p90, 1e-6), 1.0)
        col = positive if v >= 0 else negative
        txt_color = _contrast_text_color(intensity, col)
        return f"background:{hex_to_rgba(col, 0.12 + 0.60 * intensity)};color:{txt_color};font-weight:{('700' if intensity > 0.5 else '600')};"

    rows_html = ""
    for yr in sorted(by_year.keys()):
        months = by_year[yr]
        cells = ""
        prod = 1.0
        has_any = False
        for mo in range(1, 13):
            v = months.get(mo)
            if v is not None:
                prod *= 1.0 + v
                has_any = True
            txt = fmt_pct_it(v, 1, signed=True) if v is not None else "—"
            cells += f"<td style='text-align:center;padding:7px 8px;font-size:0.74rem;{_cell_color(v)}'>{txt}</td>"
        ann = prod - 1.0 if has_any else None
        ann_style = _cell_color(ann)
        ann_txt = fmt_pct_it(ann, 1, signed=True) if ann is not None else "—"
        rows_html += f"<tr style='background:{surface};'><td style='font-weight:700;padding:7px 9px;font-size:0.80rem;'>{yr}</td>{cells}<td style='text-align:right;padding:7px 9px;font-size:0.76rem;font-weight:700;border-left:2px solid {border};{ann_style}'>{ann_txt}</td></tr>"
    hdr_html = "<th style='padding:7px 9px;text-align:left;font-size:0.78rem;text-transform:uppercase;letter-spacing:.03em;'>Anno</th>" + "".join((f"<th style='padding:7px 8px;text-align:center;font-size:0.76rem;text-transform:uppercase;letter-spacing:.02em;'>{m}</th>" for m in mesi_labels)) + f"<th style='padding:7px 9px;text-align:right;font-size:0.76rem;text-transform:uppercase;letter-spacing:.02em;border-left:2px solid {hex_to_rgba('#ffffff', 0.30)};'>Tot.</th>"
    legend = _returns_scale_legend_html(min(all_vals) if all_vals else None, max(all_vals) if all_vals else None, positive, negative, muted, font_family)
    return (
        f"<div style='font-family:{font_family};'>"
        f"<div style='overflow-x:auto;'><table style='width:100%;border-collapse:collapse;border:1px solid {border};border-radius:12px;overflow:hidden;background:{surface};'>"
        f"<thead><tr style='background:{primary};color:white;'>{hdr_html}</tr></thead><tbody>{rows_html}</tbody></table></div>"
        f"{legend}</div>"
    )


def _prepare_date_indice_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Converte 'data'->'date_dt' (formato italiano), pulisce 'indice',
    scarta le righe invalide, ordina cronologicamente. Estratta perche'
    era lo stesso identico blocco ripetuto per hist e bench in
    summary_series_df."""
    if df.empty:
        return df
    df["date_dt"] = pd.to_datetime(df["data"], dayfirst=True, errors="coerce")
    df["indice"] = pd.to_numeric(df["indice"], errors="coerce")
    return df.dropna(subset=["date_dt", "indice"]).sort_values("date_dt")


def summary_series_df(summary_payload):
    hist = _prepare_date_indice_frame(pd.DataFrame(summary_payload.get("summary_history", [])))
    bench = _prepare_date_indice_frame(pd.DataFrame(summary_payload.get("benchmark_history", [])))
    return hist, bench


def summary_category_series_df(summary_payload):
    cat = pd.DataFrame(summary_payload.get("category_history", []))
    if cat.empty:
        return pd.DataFrame()
    cat["date_dt"] = pd.to_datetime(cat["data"], dayfirst=True, errors="coerce")
    category_columns = [col for col in cat.columns if col not in {"data", "date_dt"}]
    for col in category_columns:
        if col in cat.columns:
            cat[col] = pd.to_numeric(cat[col], errors="coerce")
    return cat.dropna(subset=["date_dt"]).sort_values("date_dt")


def build_summary_figures(summary_payload, settings=None, include_advanced=True, data_sig=None, theme_sig=None, charts_settings_sig=None, page_mode="Rapida", cache_strategy=None):
    """Build all Summary figures and return them as a keyed bundle.

    chart_id gestiti internamente: summary_history, summary_annual, summary_drawdown,
    summary_allocation, summary_allocation_bar, summary_rolling_vol,
    summary_rolling_sharpe, summary_pl_scatter, summary_rolling_12m
    chiamato da: ui/pages/summary.py e dai flussi di export/reporting
    """
    settings = settings or default_settings()
    from core.settings_profiles import (
        CACHE_STRATEGY_DISABLED,
        CACHE_STRATEGY_DISK_ONLY,
        CACHE_STRATEGY_SESSION_ONLY,
        get_calculations_settings,
        get_effective_figure_cache_strategy,
    )

    calculations_settings = get_calculations_settings(settings)
    rolling_window_days = max(30, int(summary_payload.get("rolling_window_days", calculations_settings.get("rolling_window_days", 90))))

    fcache = None
    if data_sig and theme_sig and charts_settings_sig:
        from core.cache_orchestrator import get_registered_figure_cache
        from core.figure_cache import CachingStrategy

        fcache = get_registered_figure_cache()
        if cache_strategy is None:
            cache_name = get_effective_figure_cache_strategy(settings)
            cache_strategy = {
                CACHE_STRATEGY_DISABLED: CachingStrategy.DISABLED,
                CACHE_STRATEGY_SESSION_ONLY: CachingStrategy.SESSION_ONLY,
                CACHE_STRATEGY_DISK_ONLY: CachingStrategy.DISK_ONLY,
            }.get(cache_name, CachingStrategy.HYBRID)

    figures = {}
    hist, bench = summary_series_df(summary_payload)
    cat_hist = summary_category_series_df(summary_payload)
    report_mode = str(page_mode or "").lower() == "report"

    def _apply_summary_settings(fig, chart_id):
        fig = apply_settings(fig, chart_id)
        if report_mode:
            _strip_report_time_controls(fig)
        return fig

    def _build_or_cache(chart_id, builder):
        if fcache:
            return fcache.get_or_build(
                chart_id=chart_id,
                data_sig=data_sig,
                theme_sig=theme_sig,
                charts_settings_sig=charts_settings_sig,
                builder=builder,
                page_mode=page_mode,
                strategy=cache_strategy,
            )
        return builder()

    if not hist.empty:
        def _build_history():
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=hist["date_dt"], y=hist["indice"], mode="lines", name="Portafoglio TWR proxy", line=dict(width=3, color=P["blue"]), hovertemplate="%{x|%d/%m/%Y}<br>Indice TWR proxy: %{y:.2f}<extra></extra>"))
            if not bench.empty:
                fig.add_trace(go.Scatter(x=bench["date_dt"], y=bench["indice"], mode="lines", name=str(summary_payload.get("portfolio_benchmark") or "Benchmark"), line=dict(width=2.5, dash="dash", color=P["orange"]), hovertemplate="%{x|%d/%m/%Y}<br>Indice: %{y:.2f}<extra></extra>"))
            return _apply_summary_settings(fig, "summary_history")

        figures["history"] = _build_or_cache("summary_history", _build_history)

        def _build_annual():
            annual = hist.copy()
            annual["year"] = annual["date_dt"].dt.year
            ann_rets = annual.groupby("year")["indice"].agg(["first", "last"]).reset_index()
            ann_rets["port"] = ann_rets.apply(lambda r: simple_period_return(r["first"], r["last"]), axis=1)
            fig_ann = go.Figure()
            fig_ann.add_trace(go.Bar(x=ann_rets["year"].astype(str), y=ann_rets["port"], name="Portafoglio", text=[fmt_pct_it(v, 1, signed=True) for v in ann_rets["port"]], textposition="outside", marker_color=[P["green"] if float(v) >= 0 else P["red"] for v in ann_rets["port"]], cliponaxis=False))
            if not bench.empty:
                annual_b = bench.copy()
                annual_b["year"] = annual_b["date_dt"].dt.year
                ann_b = annual_b.groupby("year")["indice"].agg(["first", "last"]).reset_index()
                ann_b["bench"] = ann_b.apply(lambda r: simple_period_return(r["first"], r["last"]), axis=1)
                fig_ann.add_trace(go.Scatter(x=ann_b["year"].astype(str), y=ann_b["bench"], mode="lines+markers", name=str(summary_payload.get("portfolio_benchmark") or "Benchmark"), line=dict(color=P["orange"], width=2), hovertemplate="Anno %{x}<br>Benchmark: %{y:.2%}<extra></extra>"))
            return _apply_summary_settings(fig_ann, "summary_annual")

        figures["annual"] = _build_or_cache("summary_annual", _build_annual)

        def _build_drawdown():
            # build_drawdown_series calcola equity=1+v/100: alimentata con
            # v = indice-100 ottiene equity = indice/100, un puro riscalamento
            # moltiplicativo di "indice" che lascia invariato il rapporto
            # drawdown originale (indice/cummax(indice)-1), qualunque sia il
            # valore di partenza di "indice". Risultato in percentuale (*100),
            # riportato a frazione (/100) per restare compatibile con
            # l'hovertemplate ":.2%" gia' in uso.
            dd_series = [v / 100.0 for v in build_drawdown_series((hist["indice"] - 100.0).tolist())]
            fig_dd = go.Figure()
            fig_dd.add_trace(go.Scatter(x=hist["date_dt"], y=dd_series, mode="lines", fill="tozeroy", name="Drawdown portafoglio", line=dict(color=P["red"], width=1.8), fillcolor=hex_to_rgba(P["red"], 0.14), hovertemplate="%{x|%d/%m/%Y}<br>Drawdown: %{y:.2%}<extra></extra>"))
            if not bench.empty:
                dd_b_series = [v / 100.0 for v in build_drawdown_series((bench["indice"] - 100.0).tolist())]
                fig_dd.add_trace(go.Scatter(x=bench["date_dt"], y=dd_b_series, mode="lines", name=str(summary_payload.get("portfolio_benchmark") or "Benchmark"), line=dict(color=P["orange"], width=1.5, dash="dash"), hovertemplate="%{x|%d/%m/%Y}<br>Benchmark DD: %{y:.2%}<extra></extra>"))
            return _apply_summary_settings(fig_dd, "summary_drawdown")

        figures["drawdown"] = _build_or_cache("summary_drawdown", _build_drawdown)

    alloc_df = pd.DataFrame(summary_payload.get("category_breakdown", []))
    if not alloc_df.empty:
        def _build_allocation():
            fig_alloc = go.Figure(go.Pie(labels=alloc_df["categoria"], values=alloc_df["controvalore"], hole=0.52, marker=dict(colors=[macro_color(c) for c in alloc_df["categoria"]]), text=[fmt_pct_it(v, 1) for v in alloc_df["peso"]], textinfo="text", textposition="inside", sort=False, hovertemplate="%{label}<br>Controvalore: %{value:,.2f}<br>Peso: %{percent}<extra></extra>"))
            return _apply_summary_settings(fig_alloc, "summary_allocation")

        figures["allocation"] = _build_or_cache("summary_allocation", _build_allocation)

        def _build_allocation_bar():
            fig_alloc_bar = go.Figure(go.Bar(y=alloc_df["categoria"], x=alloc_df["peso"], orientation="h", marker_color=[macro_color(c) for c in alloc_df["categoria"]], text=[f"{fmt_pct_it(p, 1)}<br>{fmt_eur_it(v, 0)}" for p, v in zip(alloc_df["peso"], alloc_df["controvalore"])], textposition="outside", cliponaxis=False, showlegend=False, hovertemplate="%{y}<br>Peso: %{x:.2%}<extra></extra>"))
            return _apply_summary_settings(fig_alloc_bar, "summary_allocation_bar")

        figures["allocation_bar"] = _build_or_cache("summary_allocation_bar", _build_allocation_bar)

    if not cat_hist.empty:
        def _build_category_history():
            fig_cat = go.Figure()
            category_columns = [col for col in cat_hist.columns if col not in {"data", "date_dt"}]
            for cat in category_columns:
                if cat in cat_hist.columns and cat_hist[cat].notna().any():
                    fig_cat.add_trace(
                        go.Scatter(
                            x=cat_hist["date_dt"],
                            y=cat_hist[cat],
                            mode="lines",
                            name=cat,
                            line=dict(color=macro_color(cat), width=2.5),
                            hovertemplate="%{x|%d/%m/%Y}<br>Indice: %{y:.2f}<extra></extra>",
                        )
                    )
            return _apply_summary_settings(fig_cat, "summary_category_history")

        figures["category_history"] = _build_or_cache("summary_category_history", _build_category_history)

    if include_advanced and not hist.empty and len(hist) >= 8:
        half_window = max(21, rolling_window_days // 2)
        medium_window = max(42, int(round(rolling_window_days * 0.75)))
        full_window = max(63, rolling_window_days)
        windows = [
            (min(half_window, max(2, len(hist) - 1)), f"{half_window} giorni", P["blue"]),
            (min(medium_window, max(2, len(hist) - 1)), f"{medium_window} giorni", P["orange"]),
            (min(full_window, max(2, len(hist) - 1)), f"{rolling_window_days} giorni", P["red"]),
        ]

        def _build_rolling_vol():
            fig_rv = go.Figure()
            for window, label, color in windows:
                if window < 2:
                    continue
                rv = rolling_volatility_annualized(hist["indice"], window)
                fig_rv.add_trace(go.Scatter(x=hist["date_dt"], y=rv, mode="lines", name=label, line=dict(color=color, width=2), hovertemplate="%{x|%d/%m/%Y}<br>Vol annua: %{y:.1%}<extra></extra>"))
            return _apply_summary_settings(fig_rv, "summary_rolling_vol")

        figures["rolling_vol"] = _build_or_cache("summary_rolling_vol", _build_rolling_vol)

    if include_advanced and not hist.empty and len(hist) >= 30:
        w90 = min(max(30, rolling_window_days), max(2, len(hist) - 1))
        sharpe = rolling_sharpe(hist["indice"], w90)

        def _build_rolling_sharpe():
            fig_rs = go.Figure()
            fig_rs.add_trace(go.Scatter(x=hist["date_dt"], y=sharpe, mode="lines", name=f"Sharpe {rolling_window_days} giorni", line=dict(color=P["blue"], width=2.5), fill="tozeroy", fillcolor=hex_to_rgba(P["blue"], 0.08), hovertemplate="%{x|%d/%m/%Y}<br>Sharpe: %{y:.1f}<extra></extra>"))
            fig_rs.add_hline(y=0, line_dash="solid", line_color="rgba(0,0,0,0.25)", line_width=1)
            fig_rs.add_hline(y=1, line_dash="dot", line_color=P["green"], opacity=0.5, line_width=1, annotation_text="Sharpe = 1", annotation_position="bottom right", annotation_font_size=10)
            return _apply_summary_settings(fig_rs, "summary_rolling_sharpe")

        figures["rolling_sharpe"] = _build_or_cache("summary_rolling_sharpe", _build_rolling_sharpe)

    hold_df = pd.DataFrame(summary_payload.get("full_holdings", []))
    if include_advanced and not hold_df.empty and len(hold_df) >= 3:
        sc = hold_df.dropna(subset=["peso", "pl_pct", "controvalore"]).copy()
        sc = sc[sc["controvalore"] > 0]
        if len(sc) >= 3:
            def _build_pl_scatter():
                fig_sc = go.Figure()
                for cat in sc["categoria"].unique():
                    cdf = sc[sc["categoria"] == cat]
                    sizes = [max(10, min(50, float(v) / max(float(sc["controvalore"].max()), 1) * 50)) for v in cdf["controvalore"]]
                    fig_sc.add_trace(go.Scatter(x=cdf["peso"].values, y=cdf["pl_pct"].values, mode="markers+text", name=str(cat), text=cdf["ticker"].tolist(), textposition="top center", textfont=dict(size=9), marker=dict(size=sizes, color=macro_color(str(cat)), opacity=0.82, line=dict(width=1.2, color="white")), hovertemplate="<b>%{text}</b><br>Peso: %{x:.1%}<br>P/L: %{y:.1%}<br><extra></extra>"))
                fig_sc.add_hline(y=0, line_dash="dash", line_color="rgba(0,0,0,0.25)", line_width=1)
                return _apply_summary_settings(fig_sc, "summary_pl_scatter")

            figures["pl_scatter"] = _build_or_cache("summary_pl_scatter", _build_pl_scatter)

    if include_advanced and not hist.empty and len(hist) >= 26:
        rr_series = trailing_period_return(hist["indice"], 52)
        rr_colors = [P["green"] if v is not None and (not np.isnan(v)) and (v >= 0) else P["red"] for v in rr_series]

        def _build_rolling_12m():
            fig_rr = go.Figure()
            fig_rr.add_trace(go.Bar(x=hist["date_dt"], y=rr_series, name="Rendimento 12M", marker_color=rr_colors, hovertemplate="%{x|%d/%m/%Y}<br>Rendimento 12M: %{y:.2%}<extra></extra>"))
            fig_rr.add_hline(y=0, line_dash="solid", line_color="rgba(0,0,0,0.25)", line_width=1)
            return _apply_summary_settings(fig_rr, "summary_rolling_12m")

        figures["rolling_12m"] = _build_or_cache("summary_rolling_12m", _build_rolling_12m)

    return figures


def _strip_report_time_controls(fig):
    try:
        fig.layout.updatemenus = ()
        fig.layout.sliders = ()
    except Exception:
        try:
            fig.update_layout(updatemenus=[], sliders=[])
        except Exception:
            pass
    try:
        dates = []
        for trace in getattr(fig, "data", []) or []:
            x_vals = getattr(trace, "x", None)
            if x_vals is None:
                continue
            parsed = pd.to_datetime(list(x_vals), errors="coerce")
            dates.extend([d for d in parsed if pd.notna(d)])
        range_payload = {}
        if len(dates) >= 2:
            x_min = min(dates)
            x_max = max(dates)
            if x_min < x_max:
                range_payload = {"range": [x_min, x_max], "autorange": False}
        fig.update_xaxes(
            **range_payload,
            rangeselector=dict(visible=False, buttons=[]),
            rangeslider=dict(visible=False),
            fixedrange=False,
        )
    except Exception:
        pass

