"""
core/services/report_builder.py - Pure helpers for configurable portfolio reports.

No Streamlit dependencies. The Summary page collects options and delegates here
for section resolution, period filtering and static HTML generation.
"""
from __future__ import annotations

import copy
import html
import json
from datetime import date, datetime
from typing import Any

import pandas as pd
import plotly.io as pio
import plotly.graph_objects as go
import numpy as np

from core.formatting import fmt_dt_it, fmt_eur_it, fmt_num_it, fmt_pct_it, fmt_qty_it


def default_report_options(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    reporting = (settings or {}).get("reporting_export", {}) if isinstance(settings, dict) else {}
    return {
        "include_charts": True,
        "include_tables": bool(reporting.get("include_holdings_table", True)),
        "include_benchmark": bool(reporting.get("include_benchmark", True)),
        "include_composition": True,
        "include_performance": True,
        "include_operations": True,
        "include_income": True,
        "include_liquidity": True,
        "include_holdings": True,
        "include_categories_detail": True,
        "include_risk_overview": True,
        "include_period_tables": True,
        "period_label": "Completo",
        "period_start": None,
        "period_end": None,
    }


def resolve_period(period_label: str, custom_start: Any = None, custom_end: Any = None, today: date | None = None) -> tuple[date | None, date | None]:
    today = today or date.today()
    label = str(period_label or "Completo")
    if label == "1M":
        return _shift_months(today, -1), today
    if label == "3M":
        return _shift_months(today, -3), today
    if label == "6M":
        return _shift_months(today, -6), today
    if label == "YTD":
        return date(today.year, 1, 1), today
    if label in {"1Y", "Ultimo anno"}:
        return _shift_months(today, -12), today
    if label in {"3Y", "Ultimi 3 anni"}:
        return _shift_months(today, -36), today
    if label == "Personalizzato":
        return _coerce_date(custom_start), _coerce_date(custom_end) or today
    return None, None


def apply_report_options(payload: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    """Return a report payload copy filtered by user-visible report options."""
    out = copy.deepcopy(payload or {})
    start = _coerce_date(options.get("period_start"))
    end = _coerce_date(options.get("period_end"))
    if start or end:
        for key in ("summary_history", "benchmark_history", "category_history"):
            out[key] = _filter_records_by_date(out.get(key, []), start, end)
        out["quarterly_returns"] = _filter_periodic_returns(out.get("quarterly_returns", []), start, end)
        out["monthly_returns"] = _filter_periodic_returns(out.get("monthly_returns", []), start, end)
        _recompute_period_metrics(out)
        _rebase_period_histories(out)
        out["period_is_filtered"] = True
    else:
        out["period_is_filtered"] = False

    if not bool(options.get("include_benchmark", True)):
        out["benchmark_history"] = []
        out["benchmark_return"] = None
        out["excess_vs_benchmark"] = None
        out["portfolio_benchmark"] = "Escluso dal report"
    return out


def build_report_preview(
    payload: dict[str, Any],
    options: dict[str, Any],
    *,
    operations_df: pd.DataFrame | None = None,
    income_items: list[dict[str, Any]] | None = None,
    liquidity: float | None = None,
) -> dict[str, list[str]]:
    included: list[str] = []
    excluded: list[str] = []
    warnings: list[str] = []

    included.append("Report completo con KPI, dettaglio portafoglio e sezioni selezionate.")
    included.append("Indicatori principali: valore, costo, patrimonio, P/L e numero strumenti.")

    if options.get("include_composition") and payload.get("category_breakdown"):
        included.append("Composizione del portafoglio per categoria e principali posizioni.")
    elif options.get("include_composition"):
        warnings.append("Composizione non disponibile: il report la saltera.")
    else:
        excluded.append("Composizione portafoglio.")

    if options.get("include_performance") and (payload.get("summary_history") or payload.get("twr") is not None):
        included.append("Performance: rendimento, drawdown e storico disponibile.")
    elif options.get("include_performance"):
        warnings.append("Performance limitata: storico insufficiente o metriche non calcolabili.")
    else:
        excluded.append("Performance.")

    if options.get("include_benchmark") and payload.get("benchmark_history"):
        included.append("Benchmark configurato e confronto disponibile.")
    elif options.get("include_benchmark"):
        warnings.append("Benchmark richiesto ma non disponibile: sara indicato come non disponibile.")
    else:
        excluded.append("Benchmark.")

    period_activity = payload.get("period_activity", {}) if isinstance(payload.get("period_activity", {}), dict) else {}
    activity_summary = period_activity.get("summary", {}) if isinstance(period_activity, dict) else {}
    has_activity = bool(activity_summary.get("event_count"))

    if options.get("include_operations") and (has_activity or (operations_df is not None and not operations_df.empty)):
        included.append("Operazioni, movimenti del periodo e spesa per strumento.")
    elif options.get("include_operations"):
        warnings.append("Operazioni richieste ma non disponibili nel dataset corrente.")

    if options.get("include_income") and income_items:
        included.append("Cedole/dividendi/proventi disponibili.")
    elif options.get("include_income"):
        excluded.append("Cedole/dividendi: nessun dato utile.")

    if options.get("include_liquidity") and liquidity is not None:
        included.append("Liquidita corrente e patrimonio complessivo.")

    if options.get("include_holdings"):
        included.append("Sezione strumenti singoli con dettaglio per ticker.")
    else:
        excluded.append("Dettaglio strumenti.")

    if options.get("include_categories_detail"):
        included.append("Sezione categorie con valore, peso e risultato.")
    else:
        excluded.append("Dettaglio categorie.")

    if options.get("include_period_tables"):
        included.append("Tabelle rendimenti periodici quando disponibili.")
    else:
        excluded.append("Tabelle periodiche.")

    if options.get("include_risk_overview"):
        included.append("Riepilogo rischio con volatilita, drawdown e ratio disponibili.")
    else:
        excluded.append("Riepilogo rischio.")

    if not options.get("include_charts"):
        excluded.append("Grafici.")
    if not options.get("include_tables"):
        excluded.append("Tabelle di dettaglio.")

    return {"included": included, "excluded": excluded, "warnings": warnings}


def build_report_filename(options: dict[str, Any], extension: str = "html") -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return f"portfolio_report_completo_{stamp}.{extension.lstrip('.')}"


def build_portfolio_report_html(
    payload: dict[str, Any],
    options: dict[str, Any],
    *,
    figures: dict[str, Any] | None = None,
    operations_df: pd.DataFrame | None = None,
    income_items: list[dict[str, Any]] | None = None,
    liquidity: float | None = None,
    generated_at: datetime | None = None,
) -> str:
    payload = payload or {}
    options = options or {}
    figures = figures or {}
    generated_at = generated_at or datetime.now()
    include_charts = bool(options.get("include_charts", True))
    include_tables = bool(options.get("include_tables", True))
    include_benchmark = bool(options.get("include_benchmark", True))
    include_composition = bool(options.get("include_composition", True))
    include_performance = bool(options.get("include_performance", True))
    include_operations = bool(options.get("include_operations", True))
    include_income = bool(options.get("include_income", True))
    include_liquidity = bool(options.get("include_liquidity", True))
    include_holdings = bool(options.get("include_holdings", True))
    include_categories_detail = bool(options.get("include_categories_detail", True))
    include_risk_overview = bool(options.get("include_risk_overview", True))
    include_period_tables = bool(options.get("include_period_tables", True))

    chart_html = _ChartEmbedder()
    sections: list[str] = []

    sections.append(_cover(payload, options, generated_at))
    sections.append(_kpi_section(payload, liquidity if include_liquidity else None))

    if include_performance:
        sections.append(
            _performance_section(
                payload,
                figures if include_charts else {},
                chart_html,
                include_benchmark,
                include_risk_overview=include_risk_overview,
                include_period_tables=include_period_tables,
            )
        )

    if include_operations:
        sections.append(_operations_section(operations_df, payload.get("period_activity"), include_tables=True))

    if include_composition:
        sections.append(
            _composition_section(
                payload,
                figures if include_charts else {},
                chart_html,
                include_tables,
                include_categories_detail=include_categories_detail,
            )
        )

    if include_tables and include_holdings:
        sections.append(_holdings_section(payload))

    if include_income:
        sections.append(_income_section(income_items or [], payload))

    sections.append(_highlights_section(payload))
    sections.append(_methodology_section(payload, include_benchmark))

    sections.append(_footer_note(payload))
    return _html_page("".join(sections), payload, options)


def report_payload_json(payload: dict[str, Any], options: dict[str, Any]) -> bytes:
    return json.dumps({"options": options, "payload": payload}, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def _coerce_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except Exception:
            continue
    return None


def _shift_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + int(months)
    year = month_index // 12
    month = month_index % 12 + 1
    days_in_month = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return date(year, month, min(value.day, days_in_month))


def _record_date(record: dict[str, Any]) -> date | None:
    return _coerce_date(record.get("data") or record.get("date") or record.get("Data"))


def _filter_records_by_date(records: list[dict[str, Any]], start: date | None, end: date | None) -> list[dict[str, Any]]:
    out = []
    for rec in records or []:
        d = _record_date(rec)
        if d is None:
            continue
        if start and d < start:
            continue
        if end and d > end:
            continue
        out.append(rec)
    return out


def _filter_periodic_returns(records: list[dict[str, Any]], start: date | None, end: date | None) -> list[dict[str, Any]]:
    if not (start or end):
        return list(records or [])
    out = []
    for rec in records or []:
        try:
            year = int(rec.get("year"))
            month = int(rec.get("month", 1))
            quarter = int(rec.get("quarter", 1))
            period_month = month if "month" in rec else max(1, min(12, quarter * 3))
            d = date(year, period_month, 1)
        except Exception:
            continue
        if start and d < date(start.year, start.month, 1):
            continue
        if end and d > date(end.year, end.month, 1):
            continue
        out.append(rec)
    return out


def _history_frame(records: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(records or [])
    if frame.empty:
        return frame
    frame["date_dt"] = pd.to_datetime(frame.get("data"), dayfirst=True, errors="coerce")
    frame["indice"] = pd.to_numeric(frame.get("indice"), errors="coerce")
    if "value" in frame.columns:
        frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    if "external_flow" in frame.columns:
        frame["external_flow"] = pd.to_numeric(frame["external_flow"], errors="coerce").fillna(0.0)
    return frame.dropna(subset=["date_dt", "indice"]).sort_values("date_dt").reset_index(drop=True)


def _recompute_period_metrics(payload: dict[str, Any]) -> None:
    hist = _history_frame(payload.get("summary_history", []))
    bench = _history_frame(payload.get("benchmark_history", []))
    if hist.empty or len(hist) < 2:
        for key in ("xirr", "twr", "cagr", "cagr_real", "volatility_ann", "max_drawdown", "benchmark_return", "excess_vs_benchmark", "sortino", "calmar", "information_ratio", "tracking_error"):
            payload[key] = None
        return

    idx = pd.to_numeric(hist["indice"], errors="coerce").dropna()
    rets = idx.pct_change().dropna()
    twr = float(idx.iloc[-1] / idx.iloc[0] - 1.0) if len(idx) >= 2 and abs(float(idx.iloc[0])) > 1e-12 else None
    elapsed_days = max(int((hist["date_dt"].iloc[-1] - hist["date_dt"].iloc[0]).days), 1)
    cagr = float((1.0 + twr) ** (365.25 / elapsed_days) - 1.0) if twr is not None and twr > -1.0 else None
    cagr_real = (
        float((1.0 + cagr) / (1.0 + payload.get("inflation_rate")) - 1.0)
        if cagr is not None and payload.get("inflation_rate")
        else None
    )
    vol = float(rets.std(ddof=1) * np.sqrt(252)) if len(rets) >= 3 else None
    running_max = idx.cummax()
    max_dd = float((idx / running_max - 1.0).min()) if len(idx) >= 2 else None

    bench_return = None
    excess = None
    tracking_error = None
    information_ratio = None
    if not bench.empty and len(bench) >= 2:
        bidx = pd.to_numeric(bench["indice"], errors="coerce").dropna()
        if len(bidx) >= 2 and abs(float(bidx.iloc[0])) > 1e-12:
            bench_return = float(bidx.iloc[-1] / bidx.iloc[0] - 1.0)
            excess = float(twr - bench_return) if twr is not None else None
        brets = bidx.pct_change().dropna()
        min_len = min(len(rets), len(brets))
        if min_len >= 4:
            ex_rets = rets.iloc[-min_len:].values - brets.iloc[-min_len:].values
            te = float(np.std(ex_rets, ddof=1) * np.sqrt(252))
            tracking_error = te if te > 1e-9 else None
            if tracking_error:
                information_ratio = float(np.mean(ex_rets) * 252 / tracking_error)

    sortino = None
    if len(rets) >= 4:
        neg = rets[rets < 0]
        if len(neg) >= 2 and cagr is not None:
            downside = float(np.sqrt((neg ** 2).mean()) * np.sqrt(252))
            sortino = float(cagr / downside) if downside > 1e-9 else None
    calmar = float(cagr / abs(max_dd)) if cagr is not None and max_dd is not None and abs(max_dd) > 1e-9 else None

    payload["xirr"] = _period_xirr_from_values_and_known_flows(hist)
    payload["twr"] = twr
    payload["cagr"] = cagr
    payload["cagr_real"] = cagr_real
    payload["volatility_ann"] = vol
    payload["max_drawdown"] = max_dd
    payload["benchmark_return"] = bench_return
    payload["excess_vs_benchmark"] = excess
    payload["sortino"] = sortino
    payload["calmar"] = calmar
    payload["information_ratio"] = information_ratio
    payload["tracking_error"] = tracking_error


def _period_xirr_from_values_and_known_flows(hist: pd.DataFrame) -> float | None:
    if "value" not in hist.columns or hist["value"].dropna().empty or len(hist) < 2:
        return None
    try:
        from core.domain.cashflows import compute_xirr

        start_value = float(hist["value"].iloc[0])
        end_value = float(hist["value"].iloc[-1])
        if start_value <= 0 or end_value <= 0:
            return None
        flows = [-start_value]
        dates = [hist["date_dt"].iloc[0].date()]
        if "external_flow" in hist.columns:
            for _, row in hist.iloc[1:-1].iterrows():
                flow = float(row.get("external_flow") or 0.0)
                if abs(flow) > 1e-9:
                    flows.append(-flow)
                    dates.append(row["date_dt"].date())
        flows.append(end_value)
        dates.append(hist["date_dt"].iloc[-1].date())
        return compute_xirr(flows, dates)
    except Exception:
        return None


def _rebase_period_histories(payload: dict[str, Any]) -> None:
    payload["summary_history"] = _rebase_history_records(payload.get("summary_history", []), ["indice"])
    payload["benchmark_history"] = _rebase_history_records(payload.get("benchmark_history", []), ["indice"])
    payload["category_history"] = _rebase_history_records(
        payload.get("category_history", []),
        _infer_category_history_columns(payload.get("category_history", [])),
    )


def _infer_category_history_columns(records: list[dict[str, Any]] | None) -> list[str]:
    if not records:
        return []
    first = next((record for record in records if isinstance(record, dict)), None)
    if not isinstance(first, dict):
        return []
    return [key for key in first.keys() if key not in {"data", "date", "Data"}]


def _rebase_history_records(records: list[dict[str, Any]], cols: list[str]) -> list[dict[str, Any]]:
    if not records:
        return []
    frame = pd.DataFrame(records).copy()
    for col in cols:
        if col not in frame.columns:
            continue
        series = pd.to_numeric(frame[col], errors="coerce")
        first = series.dropna().iloc[0] if not series.dropna().empty else None
        if first is not None and abs(float(first)) > 1e-12:
            frame[col] = (series / float(first) * 100.0).round(4)
    return frame.to_dict("records")


class _ChartEmbedder:
    def __init__(self) -> None:
        self._first = True

    def embed(self, fig: Any) -> str:
        if fig is None:
            return "<p class='note'>Grafico non disponibile per i dati selezionati.</p>"
        include_js = "cdn" if self._first else False
        self._first = False
        try:
            fig_for_report = go.Figure(fig)
            # In exported reports we always show the full filtered period, not the default UI button range.
            try:
                fig_for_report.update_xaxes(rangeselector=dict(visible=False, buttons=[]), rangeslider=dict(visible=False))
            except Exception:
                pass
            try:
                fig_for_report.update_layout(xaxis_rangeslider_visible=False)
            except Exception:
                pass
            try:
                fig_for_report.layout.updatemenus = ()
                fig_for_report.layout.sliders = ()
            except Exception:
                try:
                    fig_for_report.update_layout(updatemenus=[], sliders=[])
                except Exception:
                    pass
            for axis_name in [name for name in fig_for_report.layout if str(name).startswith("xaxis")]:
                axis = getattr(fig_for_report.layout, str(axis_name), None)
                if axis is None:
                    continue
                try:
                    axis.rangeselector = dict(visible=False, buttons=[])
                except Exception:
                    pass
                try:
                    axis.rangeslider = dict(visible=False)
                except Exception:
                    pass
            _force_figure_full_x_range(fig_for_report)
            return pio.to_html(fig_for_report, include_plotlyjs=include_js, full_html=False, config={"displayModeBar": False, "responsive": True})
        except Exception:
            return "<p class='note'>Grafico non incorporabile in questo report.</p>"


def _force_figure_full_x_range(fig: Any) -> None:
    try:
        dates = []
        for trace in getattr(fig, "data", []) or []:
            x_vals = getattr(trace, "x", None)
            if x_vals is None:
                continue
            parsed = pd.to_datetime(list(x_vals), errors="coerce")
            dates.extend([d for d in parsed if pd.notna(d)])
        if len(dates) < 2:
            return
        x_min = min(dates)
        x_max = max(dates)
        if x_min >= x_max:
            return
        fig.update_xaxes(range=[x_min, x_max], autorange=False, rangeselector=dict(visible=False, buttons=[]), rangeslider=dict(visible=False))
    except Exception:
        return


def _cover(payload: dict[str, Any], options: dict[str, Any], generated_at: datetime) -> str:
    period = html.escape(str(options.get("period_label") or "Completo"))
    return f"""
    <section class="hero">
      <div>
        <div class="eyebrow">Report portafoglio</div>
        <h1>{html.escape(str(payload.get('portfolio_name') or 'Portafoglio Principale'))}</h1>
        {f'<p>{html.escape(str(payload.get("portfolio_description")))}</p>' if str(payload.get('portfolio_description') or '').strip() else ''}
        <p>Documento completo costruito dai dati reali del portafoglio e filtrato sul periodo richiesto.</p>
      </div>
      <div class="hero-meta">
        <strong>Report completo</strong>
        <span>Periodo: {period}</span>
        <span>Generato: {fmt_dt_it(generated_at)}</span>
        <span>Valuta: {html.escape(str(payload.get('reporting_currency') or 'EUR'))}</span>
      </div>
    </section>
    """


def _kpi(label: str, value: str, note: str = "") -> str:
    return f"<div class='kpi'><span>{html.escape(label)}</span><strong>{value}</strong><small>{html.escape(note)}</small></div>"


def _kpi_section(payload: dict[str, Any], liquidity: float | None) -> str:
    total_market = float(payload.get("total_market_value") or 0.0)
    patrimonio = total_market + float(liquidity or 0.0) if liquidity is not None else total_market
    extra = _kpi("Liquidita", fmt_eur_it(liquidity, 2), "Disponibile") if liquidity is not None else ""
    return f"""
    <section>
      <h2>Indicatori principali</h2>
      <div class="grid">
        {_kpi("Valore strumenti", fmt_eur_it(payload.get('total_market_value'), 2), "Controvalore corrente")}
        {_kpi("Costo", fmt_eur_it(payload.get('total_cost'), 2), "Costo storico")}
        {_kpi("P/L", fmt_eur_it(payload.get('total_pl'), 2, signed=True), fmt_pct_it(payload.get('total_pl_pct'), 2, signed=True))}
        {_kpi("Patrimonio", fmt_eur_it(patrimonio, 2), "Strumenti + liquidita" if liquidity is not None else "Strumenti")}
        {extra}
        {_kpi("Strumenti", fmt_num_it(payload.get('holdings_count'), 0), "Posizioni attive")}
      </div>
    </section>
    """


def _performance_section(
    payload: dict[str, Any],
    figures: dict[str, Any],
    embedder: _ChartEmbedder,
    include_benchmark: bool,
    *,
    include_risk_overview: bool,
    include_period_tables: bool,
) -> str:
    benchmark = ""
    if include_benchmark:
        benchmark = _kpi("Benchmark", fmt_pct_it(payload.get("benchmark_return"), 2, signed=True), str(payload.get("portfolio_benchmark") or "n/d"))
    charts = ""
    if figures:
        charts = f"""
        <div class="two-col">
          <div>{embedder.embed(figures.get('history'))}</div>
          <div>{embedder.embed(figures.get('drawdown'))}</div>
        </div>
        <div class="two-col" style="margin-top:16px">
          <div>{embedder.embed(figures.get('annual')) if figures.get('annual') is not None else "<p class='note'>Rendimenti annuali non disponibili.</p>"}</div>
          <div>{embedder.embed(figures.get('pl_scatter')) if figures.get('pl_scatter') is not None else "<p class='note'>Valutazione strumenti per P/L non disponibile.</p>"}</div>
        </div>
        """
    risk_grid = ""
    if include_risk_overview:
        risk_grid = f"""
        <div class="grid" style="margin-top:12px">
          {_kpi("CAGR", fmt_pct_it(payload.get('cagr'), 2, signed=True), "Tasso composto annuo")}
          {_kpi("CAGR reale", fmt_pct_it(payload.get('cagr_real'), 2, signed=True), "Al netto inflazione") if payload.get('inflation_rate') else ""}
          {_kpi("Sortino", fmt_num_it(payload.get('sortino'), 2), "Rapporto rendimento / downside")}
          {_kpi("Calmar", fmt_num_it(payload.get('calmar'), 2), "CAGR / drawdown")}
          {_kpi("Tracking error", fmt_pct_it(payload.get('tracking_error'), 2), "vs benchmark")}
          {_kpi("Information ratio", fmt_num_it(payload.get('information_ratio'), 2), "Extra-rendimento / tracking error")}
        </div>
        """
    period_tables = ""
    if include_period_tables:
        period_tables = _period_tables_section(payload)
    explanations = _performance_explanations(payload, include_benchmark, include_risk_overview)
    return f"""
    <section>
      <h2>Performance</h2>
      <div class="grid">
        {_kpi("XIRR", fmt_pct_it(payload.get('xirr'), 2, signed=True), "Rendimento money-weighted")}
        {_kpi("TWR proxy", fmt_pct_it(payload.get('twr'), 2, signed=True), "Storico flow-adjusted")}
        {_kpi("Volatilita", fmt_pct_it(payload.get('volatility_ann'), 2), "Annua stimata")}
        {_kpi("Max drawdown", fmt_pct_it(payload.get('max_drawdown'), 2, signed=True), "Flessione massima")}
        {_kpi("Benchmark", fmt_pct_it(payload.get("benchmark_return"), 2, signed=True), str(payload.get("portfolio_benchmark") or "n/d")) if include_benchmark else ""}
        {_kpi("Extra-rendimento", fmt_pct_it(payload.get("excess_vs_benchmark"), 2, signed=True), "Portafoglio meno benchmark") if include_benchmark else ""}
        {_kpi("CAGR", fmt_pct_it(payload.get('cagr'), 2, signed=True), "Tasso composto annuo")}
        {_kpi("CAGR reale", fmt_pct_it(payload.get('cagr_real'), 2, signed=True), "Al netto inflazione") if payload.get('inflation_rate') else ""}
        {_kpi("Sortino", fmt_num_it(payload.get('sortino'), 2), "Rendimento / downside")}
        {_kpi("Calmar", fmt_num_it(payload.get('calmar'), 2), "CAGR / drawdown")}
        {_kpi("Tracking error", fmt_pct_it(payload.get('tracking_error'), 2), "Scarto dal benchmark")}
        {_kpi("Information ratio", fmt_num_it(payload.get('information_ratio'), 2), "Extra-rendimento / tracking error")}
        {_kpi("Proventi netti", fmt_eur_it(payload.get('net_proventi'), 2), "Cedole e dividendi disponibili")}
      </div>
      {_performance_explanations_block(explanations)}
      {charts}
      {period_tables}
    </section>
    """


def _composition_section(
    payload: dict[str, Any],
    figures: dict[str, Any],
    embedder: _ChartEmbedder,
    include_tables: bool,
    *,
    include_categories_detail: bool,
) -> str:
    chart = embedder.embed(figures.get("allocation")) if figures else ""
    table = _category_table(payload.get("category_breakdown", [])) if include_tables else ""
    detail = _category_detail_table(payload) if include_categories_detail and include_tables else "<p class='note'>Dettaglio categorie escluso.</p>"
    return f"""
    <section>
      <h2>Composizione</h2>
      <div class="two-col">
        <div>{chart or "<p class='note'>Grafici esclusi dal report.</p>"}</div>
        <div>{table or "<p class='note'>Tabelle di dettaglio escluse.</p>"}</div>
      </div>
      <div style="margin-top:16px">{embedder.embed(figures.get("category_history")) if figures and figures.get("category_history") is not None else "<p class='note'>Andamento categorie non disponibile.</p>"}</div>
      <div style="margin-top:16px">{detail}</div>
    </section>
    """


def _category_table(rows: list[dict[str, Any]]) -> str:
    body = "".join(
        f"<tr><td>{html.escape(str(r.get('categoria', '')))}</td><td class='num'>{fmt_pct_it(r.get('peso'), 2)}</td><td class='num'>{fmt_eur_it(r.get('controvalore'), 2)}</td></tr>"
        for r in rows or []
    )
    if not body:
        body = "<tr><td colspan='3'>Nessun dato disponibile.</td></tr>"
    return f"<table><thead><tr><th>Categoria</th><th>Peso</th><th>Controvalore</th></tr></thead><tbody>{body}</tbody></table>"


def _holdings_section(payload: dict[str, Any]) -> str:
    rows = payload.get("full_holdings", []) or []
    body = "".join(
        "<tr>"
        f"<td>{html.escape(str(h.get('ticker', '')))}</td>"
        f"<td>{html.escape(str(h.get('strumento', '')))}</td>"
        f"<td>{html.escape(str(h.get('categoria', '')))}</td>"
        f"<td class='num'>{fmt_qty_it(h.get('quote'), 4)}</td>"
        f"<td class='num'>{fmt_eur_it(h.get('prezzo'), 4)}</td>"
        f"<td class='num'>{fmt_eur_it(h.get('costo'), 2)}</td>"
        f"<td class='num'>{fmt_pct_it(h.get('peso'), 2)}</td>"
        f"<td class='num'>{fmt_eur_it(h.get('controvalore'), 2)}</td>"
        f"<td class='num'>{fmt_eur_it(h.get('pl_eur'), 2, signed=True)}</td>"
        f"<td class='num'>{fmt_pct_it(h.get('pl_pct'), 2, signed=True)}</td>"
        "</tr>"
        for h in rows
    )
    if not body:
        body = "<tr><td colspan='10'>Nessuna posizione disponibile.</td></tr>"
    return f"""
    <section>
      <h2>Dettaglio strumenti</h2>
      <table><thead><tr><th>Ticker</th><th>Strumento</th><th>Cat.</th><th>Quote</th><th>Prezzo</th><th>Costo</th><th>Peso</th><th>Controvalore</th><th>P/L</th><th>P/L %</th></tr></thead><tbody>{body}</tbody></table>
    </section>
    """


def _operations_section(
    operations_df: pd.DataFrame | None,
    period_activity: dict[str, Any] | None,
    *,
    include_tables: bool = True,
) -> str:
    period_activity = period_activity or {}
    summary = period_activity.get("summary", {}) if isinstance(period_activity, dict) else {}
    by_instrument = period_activity.get("by_instrument")
    event_log = period_activity.get("event_log")

    overview = ""
    if summary:
        overview = f"""
        <div class="grid">
          {_kpi("Acquisti", fmt_eur_it(summary.get('buy_net_outflow'), 2), f"{fmt_num_it(summary.get('buy_count'), 0)} operazioni")}
          {_kpi("Vendite/rimborsi", fmt_eur_it(summary.get('sell_net_inflow'), 2), f"{fmt_num_it(summary.get('sell_count'), 0)} operazioni")}
          {_kpi("Cedole/dividendi", fmt_eur_it(summary.get('income_net'), 2), f"{fmt_num_it(summary.get('income_count'), 0)} eventi")}
          {_kpi("Saldo netto periodo", fmt_eur_it(summary.get('net_cash_delta'), 2, signed=True), "Movimenti di cassa complessivi")}
          {_kpi("Versamenti", fmt_eur_it(summary.get('cash_in'), 2), f"{fmt_num_it(summary.get('cash_in_count'), 0)} movimenti")}
          {_kpi("Prelievi", fmt_eur_it(summary.get('cash_out'), 2), f"{fmt_num_it(summary.get('cash_out_count'), 0)} movimenti")}
          {_kpi("Commissioni", fmt_eur_it(summary.get('fees'), 2), "Costi del periodo")}
          {_kpi("Imposte", fmt_eur_it(summary.get('taxes'), 2), "Prelievi fiscali del periodo")}
        </div>
        """

    instrument_table = "<p class='note'>Nessun movimento per strumento nel periodo selezionato.</p>"
    if not include_tables:
        instrument_table = "<p class='note'>Tabella strumenti non inclusa nelle opzioni del report.</p>"
    elif isinstance(by_instrument, pd.DataFrame) and not by_instrument.empty:
        keep_cols = [
            "Ticker",
            "Strumento",
            "Operazioni",
            "Quote acquistate",
            "Quote vendute",
            "Delta quote",
            "Spesa acquisti",
            "Incasso vendite",
            "Cedole/dividendi netti",
            "Commissioni",
            "Imposte",
            "Saldo netto",
        ]
        instrument_df = by_instrument[[col for col in keep_cols if col in by_instrument.columns]].copy().head(40)
        for col in ("Operazioni",):
            if col in instrument_df.columns:
                instrument_df[col] = instrument_df[col].apply(lambda v: fmt_num_it(v, 0))
        for col in ("Quote acquistate", "Quote vendute", "Delta quote"):
            if col in instrument_df.columns:
                instrument_df[col] = instrument_df[col].apply(lambda v, signed=(col == "Delta quote"): fmt_num_it(v, 4, signed=signed))
        for col in ("Spesa acquisti", "Incasso vendite", "Cedole/dividendi netti", "Commissioni", "Imposte", "Saldo netto"):
            if col in instrument_df.columns:
                instrument_df[col] = instrument_df[col].apply(lambda v, signed=(col == "Saldo netto"): fmt_eur_it(v, 2, signed=signed))
        instrument_table = instrument_df.to_html(index=False, border=0, classes="report-table", escape=False)

    event_table = "<p class='note'>Nessuna operazione disponibile.</p>"
    if not include_tables:
        event_table = "<p class='note'>Registro eventi non incluso nelle opzioni del report.</p>"
    elif isinstance(event_log, pd.DataFrame) and not event_log.empty:
        event_df = event_log.tail(80).copy()
        if "Quote" in event_df.columns:
            event_df["Quote"] = event_df["Quote"].apply(lambda v: fmt_qty_it(v, 4))
        if "Prezzo" in event_df.columns:
            event_df["Prezzo"] = event_df["Prezzo"].apply(lambda v: fmt_eur_it(v, 4))
        for col in ("Lordo", "Commissioni", "Imposte", "Netto"):
            if col in event_df.columns:
                event_df[col] = event_df[col].apply(lambda v, signed=(col == "Netto"): fmt_eur_it(v, 2, signed=signed))
        event_table = event_df.to_html(index=False, border=0, classes="report-table", escape=False)
    elif operations_df is not None and not operations_df.empty:
        event_table = operations_df.tail(80).to_html(index=False, border=0, classes="report-table", escape=False)

    return f"""
    <section>
      <h2>Operazioni e movimenti del periodo</h2>
      <p class='note'>Qui trovi acquisti, vendite, variazione quote e flussi di cassa del periodo selezionato.</p>
      {overview or "<p class='note'>Nessun movimento disponibile nel periodo selezionato.</p>"}
      <div style="margin-top:16px">
        <h3>Acquisti, vendite e variazione quote per strumento</h3>
        {instrument_table}
      </div>
      <div style="margin-top:16px">
        <h3>Registro eventi del periodo</h3>
        {event_table}
      </div>
    </section>
    """


def _income_section(income_items: list[dict[str, Any]], payload: dict[str, Any]) -> str:
    rows = []
    for item in income_items[-80:]:
        rows.append(
            {
                "Data": item.get("data") or item.get("Data") or "",
                "Ticker": item.get("ticker") or item.get("Ticker") or "",
                "Tipo": item.get("tipo_evento") or item.get("tipo") or "Provento",
                "Netto": fmt_eur_it(item.get("importo_netto"), 2),
            }
        )
    table = pd.DataFrame(rows).to_html(index=False, border=0, classes="report-table", escape=False) if rows else "<p class='note'>Nessun provento disponibile.</p>"
    return f"""
    <section>
      <h2>Cedole, dividendi e proventi</h2>
      <div class="grid">
        {_kpi("Proventi netti", fmt_eur_it(payload.get('net_proventi'), 2), "Totale disponibile")}
        {_kpi("Proventi lordi", fmt_eur_it(payload.get('gross_proventi'), 2), "Totale disponibile")}
      </div>
      {table}
    </section>
    """


def _highlights_section(payload: dict[str, Any]) -> str:
    holdings = list(payload.get("full_holdings", []) or [])
    if not holdings:
        return "<section><h2>Punti notevoli</h2><p class='note'>Nessun dato holdings disponibile.</p></section>"
    by_value = sorted(holdings, key=lambda item: float(item.get("controvalore", 0) or 0), reverse=True)
    by_pl = sorted(holdings, key=lambda item: float(item.get("pl_eur", 0) or 0), reverse=True)
    top = by_value[:5]
    best = by_pl[:5]
    worst = list(reversed(by_pl[-5:]))
    return f"""
    <section>
      <h2>Punti notevoli</h2>
      <div class="three-col">
        <div>{_mini_holdings_table('Strumenti piu pesanti', top, 'controvalore')}</div>
        <div>{_mini_holdings_table('Migliori contributori', best, 'pl_eur')}</div>
        <div>{_mini_holdings_table('Peggiori contributori', worst, 'pl_eur')}</div>
      </div>
    </section>
    """


def _methodology_section(payload: dict[str, Any], include_benchmark: bool) -> str:
    methodology = payload.get("methodology", {}) if isinstance(payload.get("methodology", {}), dict) else {}
    rows = [
        ("Valorizzazione", methodology.get("valuation_rule", "")),
        ("XIRR", methodology.get("money_weighted_return", "")),
        ("TWR proxy", methodology.get("time_weighted_proxy", "")),
    ]
    if include_benchmark:
        rows.append(("Benchmark", methodology.get("benchmark_method", "")))
    body = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(str(v))}</td></tr>" for k, v in rows)
    return f"<section><h2>Metodo e limiti</h2><table>{body}</table></section>"


def _footer_note(payload: dict[str, Any]) -> str:
    return f"<section class='note'>{html.escape(str(payload.get('compliance_note') or 'Report interno. Non costituisce consulenza finanziaria.'))}</section>"


def _category_detail_table(payload: dict[str, Any]) -> str:
    rows = list(payload.get("category_breakdown", []) or [])
    if not rows:
        return "<p class='note'>Dettaglio categorie non disponibile.</p>"
    total_pl = float(payload.get("total_pl") or 0.0)
    holdings = list(payload.get("full_holdings", []) or [])
    grouped = {}
    for item in holdings:
        cat = str(item.get("categoria") or "")
        grouped.setdefault(cat, []).append(item)
    body = "".join(
        "<tr>"
        f"<td>{html.escape(str(r.get('categoria', '')))}</td>"
        f"<td class='num'>{fmt_eur_it(r.get('controvalore'), 2)}</td>"
        f"<td class='num'>{fmt_pct_it(r.get('peso'), 2)}</td>"
        f"<td class='num'>{fmt_num_it(len(grouped.get(str(r.get('categoria', '')), [])), 0)}</td>"
        f"<td>{html.escape(str(max(grouped.get(str(r.get('categoria', '')), []), key=lambda item: float(item.get('controvalore', 0) or 0)).get('ticker', 'n/d') if grouped.get(str(r.get('categoria', '')), []) else 'n/d'))}</td>"
        "</tr>"
        for r in rows
    )
    note = f"P/L complessivo disponibile nel report: {fmt_eur_it(total_pl, 2, signed=True)}."
    return f"<div><h3>Dettaglio per categoria</h3><table><thead><tr><th>Categoria</th><th>Valore</th><th>Peso</th><th>N. strumenti</th><th>Strumento principale</th></tr></thead><tbody>{body}</tbody></table><p class='note'>{note}</p></div>"


def _period_tables_section(payload: dict[str, Any]) -> str:
    quarterly_rows = list(payload.get("quarterly_returns", []) or [])
    monthly_rows = list(payload.get("monthly_returns", []) or [])
    quarterly = _simple_returns_table("Rendimenti trimestrali", quarterly_rows, kind="quarter")
    monthly = _simple_returns_table("Rendimenti mensili", monthly_rows[-12:], kind="month")
    return f"<div class='two-col' style='margin-top:16px'><div>{quarterly}</div><div>{monthly}</div></div>"


def _simple_returns_table(title: str, rows: list[dict[str, Any]], *, kind: str) -> str:
    if not rows:
        return f"<div><h3>{html.escape(title)}</h3><p class='note'>Dati non disponibili.</p></div>"
    body = ""
    for item in rows:
        label = f"{int(item.get('year'))} Q{int(item.get('quarter'))}" if kind == "quarter" else f"{int(item.get('month')):02d}/{int(item.get('year'))}"
        body += f"<tr><td>{label}</td><td class='num'>{fmt_pct_it(item.get('ptf'), 2, signed=True)}</td></tr>"
    return f"<div><h3>{html.escape(title)}</h3><table><thead><tr><th>Periodo</th><th>Portafoglio</th></tr></thead><tbody>{body}</tbody></table></div>"


def _mini_holdings_table(title: str, items: list[dict[str, Any]], value_key: str) -> str:
    if not items:
        return f"<div><h3>{html.escape(title)}</h3><p class='note'>Nessun dato disponibile.</p></div>"
    body = "".join(
        "<tr>"
        f"<td>{html.escape(str(item.get('ticker', '')))}</td>"
        f"<td class='num'>{fmt_eur_it(item.get(value_key), 2, signed=(value_key == 'pl_eur'))}</td>"
        "</tr>"
        for item in items
    )
    return f"<div><h3>{html.escape(title)}</h3><table><thead><tr><th>Ticker</th><th>Valore</th></tr></thead><tbody>{body}</tbody></table></div>"


def _performance_explanations(payload: dict[str, Any], include_benchmark: bool, include_risk_overview: bool) -> str:
    bits = [
        ("XIRR", f"{fmt_pct_it(payload.get('xirr'), 2, signed=True)}. Rendimento effettivo che considera quando hai investito o incassato."),
        ("TWR proxy", f"{fmt_pct_it(payload.get('twr'), 2, signed=True)}. Misura la performance del portafoglio separandola dai tuoi versamenti."),
        ("Volatilita", f"{fmt_pct_it(payload.get('volatility_ann'), 2)}. Più e alta, piu il valore del portafoglio tende a oscillare."),
        ("Max drawdown", f"{fmt_pct_it(payload.get('max_drawdown'), 2, signed=True)}. Indica il peggior calo temporaneo dal massimo del periodo."),
    ]
    if include_benchmark:
        bits.append(("Benchmark", f"{fmt_pct_it(payload.get('benchmark_return'), 2, signed=True)}. E il risultato del riferimento scelto nello stesso periodo. Serve come confronto, non come promessa."))
        bits.append(("Extra-rendimento", f"{fmt_pct_it(payload.get('excess_vs_benchmark'), 2, signed=True)}. Mostra se il portafoglio ha fatto meglio o peggio del benchmark."))
    if include_risk_overview:
        bits.append(("Tracking error", f"{fmt_pct_it(payload.get('tracking_error'), 2)}. Indica quanto il portafoglio si e mosso in modo diverso dal benchmark."))
        bits.append(("Information ratio", f"{fmt_num_it(payload.get('information_ratio'), 2)}. Riassume quanta resa extra e arrivata per ogni unita di scostamento dal benchmark."))
    return bits


def _performance_explanations_block(items: list[tuple[str, str]]) -> str:
    if not items:
        return "<p class='note'>Spiegazioni non disponibili.</p>"
    rows = "".join(
        f"<div class='metric-note-row'><strong>{html.escape(label)}</strong><span>{html.escape(text)}</span></div>"
        for label, text in items
    )
    return f"<div class='metric-notes'><h3>Come leggere queste metriche</h3>{rows}</div>"


def _html_page(body: str, payload: dict[str, Any], options: dict[str, Any]) -> str:
    title = html.escape(str(payload.get("portfolio_name") or "Portfolio Report"))
    css = """
    *{box-sizing:border-box} body{margin:0;background:#f3f6f9;color:#1f2937;font-family:system-ui,-apple-system,Segoe UI,Arial,sans-serif;font-size:14px;line-height:1.5}
    .page{max-width:1180px;margin:0 auto;padding:28px}
    .hero{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:24px;align-items:end;background:#16324f;color:white;border-radius:18px;padding:28px 32px;margin-bottom:20px}
    .hero h1{margin:4px 0 8px 0;font-size:1.9rem;line-height:1.1}.hero p{margin:0;color:rgba(255,255,255,.82)}
    .eyebrow{text-transform:uppercase;letter-spacing:.08em;font-size:.76rem;font-weight:800;color:rgba(255,255,255,.72)}
    .hero-meta{display:grid;gap:4px;text-align:right;font-size:.86rem}.hero-meta span{color:rgba(255,255,255,.78)}
    section{background:white;border:1px solid #dde5ee;border-radius:14px;padding:20px 22px;margin:0 0 16px 0;box-shadow:0 6px 18px rgba(15,23,42,.04)}
    h2{font-size:1.08rem;margin:0 0 14px 0;padding-bottom:7px;border-bottom:2px solid #e7edf4;color:#10243a}
    .grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.two-col{display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start}.three-col{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;align-items:start}
    .kpi{border:1px solid #e2e8f0;background:#f8fafc;border-radius:12px;padding:12px 14px;min-height:88px}.kpi span{display:block;font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;color:#64748b;font-weight:800}.kpi strong{display:block;margin-top:5px;font-size:1.28rem;color:#111827}.kpi small{display:block;margin-top:4px;color:#7b8794}
    .metric-notes{margin-top:14px;border:1px solid #dde5ee;background:#f8fafc;border-radius:14px;padding:14px 16px}.metric-notes h3{margin:0 0 10px 0;font-size:.86rem;color:#10243a;text-transform:uppercase;letter-spacing:.06em}.metric-note-row{display:grid;grid-template-columns:140px minmax(0,1fr);gap:10px;padding:8px 0;border-top:1px solid #e5edf5}.metric-note-row:first-of-type{border-top:none;padding-top:0}.metric-note-row strong{font-size:.82rem;color:#10243a}.metric-note-row span{font-size:.84rem;color:#526173;line-height:1.45}
    table{width:100%;border-collapse:collapse;font-size:.82rem}th,td{border:1px solid #e2e8f0;padding:7px 9px;vertical-align:top}th{background:#eef3f8;text-align:left;font-weight:800}.num{text-align:right;white-space:nowrap}
    .note{font-size:.84rem;color:#526173;background:#f8fafc}
    @media print{body{background:white}.page{padding:10px}section{box-shadow:none;break-inside:avoid}.hero{break-inside:avoid}.two-col{grid-template-columns:1fr 1fr}.three-col{grid-template-columns:repeat(3,1fr)}.grid{grid-template-columns:repeat(4,1fr)}}
    @media (max-width:840px){.page{padding:14px}.hero,.two-col,.three-col{grid-template-columns:1fr}.hero-meta{text-align:left}.grid{grid-template-columns:1fr 1fr}.metric-note-row{grid-template-columns:1fr}}
    """
    return f"<!doctype html><html lang='it'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{title}</title><style>{css}</style></head><body><main class='page'>{body}</main></body></html>"
