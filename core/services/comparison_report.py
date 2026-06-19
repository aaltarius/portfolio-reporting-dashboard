"""
core/services/comparison_report.py - Static HTML export for snapshot comparisons.
"""
from __future__ import annotations

import html
from datetime import datetime
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

from core.formatting import fmt_dt_it, fmt_eur_it, fmt_num_it, fmt_pct_it, fmt_qty_it


def build_comparison_report_html(
    *,
    title: str,
    generated_at: datetime | None,
    snapshot_names: list[str],
    metric_map: dict[str, Any],
    summary_notes: list[str],
    metrics_wide_df: pd.DataFrame,
    categories_value_wide_df: pd.DataFrame,
    categories_weight_wide_df: pd.DataFrame,
    holdings_wide_df: pd.DataFrame,
    interval_activities: list[dict[str, Any]],
    figures: dict[str, Any] | None = None,
) -> str:
    generated_at = generated_at or datetime.now()
    figures = figures or {}
    body = []
    body.append(_hero(title, snapshot_names, generated_at))
    body.append(_kpi_section(metric_map))
    body.append(_notes_section(summary_notes))
    body.append(_charts_section(figures))
    body.append(_table_section("Metriche confronto", _format_metrics_table(metrics_wide_df)))
    body.append(_table_section("Categorie: controvalore", _format_currency_table(categories_value_wide_df, key_col="Categoria")))
    body.append(_table_section("Categorie: peso", _format_percent_table(categories_weight_wide_df, key_col="Categoria")))
    body.append(_table_section("Strumenti: quote e prezzi", _format_quote_price_table(holdings_wide_df)))
    body.append(_table_section("Strumenti: capitale e controvalore", _format_capital_table(holdings_wide_df)))
    body.append(_table_section("Strumenti: P/L e rendimento", _format_performance_table(holdings_wide_df)))
    body.append(_interval_activities_section(interval_activities))
    return _html_page("".join(body), title)


def build_comparison_report_filename(extension: str = "html") -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return f"confronto_portafoglio_{stamp}.{extension.lstrip('.')}"


def _hero(title: str, snapshot_names: list[str], generated_at: datetime) -> str:
    snaps = " -> ".join(html.escape(str(name or "")) for name in snapshot_names)
    return f"""
    <section class="hero">
      <div>
        <div class="eyebrow">Confronto portafoglio</div>
        <h1>{html.escape(title)}</h1>
        <p>Documento di confronto tra snapshot del portafoglio con focus su valore, quote, rendimento e movimenti.</p>
      </div>
      <div class="hero-meta">
        <strong>Confronto completo</strong>
        <span>Snapshot: {snaps}</span>
        <span>Generato: {fmt_dt_it(generated_at)}</span>
      </div>
    </section>
    """


def _kpi_section(metric_map: dict[str, Any]) -> str:
    patrimonio = metric_map.get("Patrimonio totale", {})
    pl = metric_map.get("P/L", {})
    rendimento = metric_map.get("Rendimento", {})
    cash = metric_map.get("Liquidita", {})
    return f"""
    <section>
      <h2>Riepilogo differenze</h2>
      <div class="grid">
        {_kpi("Patrimonio finale", fmt_eur_it(patrimonio.get('B'), 2), fmt_eur_it(patrimonio.get('Delta'), 2, signed=True))}
        {_kpi("P/L finale", fmt_eur_it(pl.get('B'), 2, signed=True), fmt_eur_it(pl.get('Delta'), 2, signed=True))}
        {_kpi("Rendimento finale", fmt_pct_it(rendimento.get('B'), 2, signed=True), fmt_pct_it(rendimento.get('Delta'), 2, signed=True))}
        {_kpi("Liquidita finale", fmt_eur_it(cash.get('B'), 2), fmt_eur_it(cash.get('Delta'), 2, signed=True))}
      </div>
    </section>
    """


def _notes_section(summary_notes: list[str]) -> str:
    if not summary_notes:
        return ""
    body = "".join(f"<li>{html.escape(str(note))}</li>" for note in summary_notes)
    return f"<section><h2>Lettura sintetica</h2><ul>{body}</ul></section>"


def _charts_section(figures: dict[str, Any]) -> str:
    if not figures:
        return ""
    top = f"""
    <div class="two-col">
      <div>{_embed_figure(figures.get('assets_timeline'))}</div>
      <div>{_embed_figure(figures.get('pl_timeline'))}</div>
    </div>
    """
    mid = f"""
    <div class="two-col" style="margin-top:16px">
      <div>{_embed_figure(figures.get('left_main'))}</div>
      <div>{_embed_figure(figures.get('right_main'))}</div>
    </div>
    """
    bottom = f"""
    <div class="two-col" style="margin-top:16px">
      <div>{_embed_figure(figures.get('value_detail'))}</div>
      <div>{_embed_figure(figures.get('perf_detail'))}</div>
    </div>
    """
    return f"<section><h2>Grafici</h2>{top}{mid}{bottom}</section>"


def _table_section(title: str, table_html: str) -> str:
    if not table_html:
        return ""
    return f"<section><h2>{html.escape(title)}</h2>{table_html}</section>"


def _interval_activities_section(interval_activities: list[dict[str, Any]]) -> str:
    if not interval_activities:
        return ""
    blocks = []
    for item in interval_activities:
        summary = item.get("summary", {}) or {}
        by_instrument = item.get("by_instrument")
        if isinstance(by_instrument, pd.DataFrame):
            df = by_instrument.head(18).copy()
        elif by_instrument:
            df = pd.DataFrame(by_instrument).head(18)
        else:
            df = pd.DataFrame()
        if not df.empty:
            for col in ("Operazioni",):
                if col in df.columns:
                    df[col] = df[col].apply(lambda v: fmt_num_it(v, 0))
            for col in ("Quote acquistate", "Quote vendute"):
                if col in df.columns:
                    df[col] = df[col].apply(lambda v: fmt_qty_it(v, 4))
            if "Delta quote" in df.columns:
                df["Delta quote"] = df["Delta quote"].apply(lambda v: fmt_num_it(v, 4, signed=True))
            for col in ("Spesa acquisti", "Incasso vendite", "Cedole/dividendi netti", "Commissioni", "Imposte"):
                if col in df.columns:
                    df[col] = df[col].apply(lambda v: fmt_eur_it(v, 2))
            if "Saldo netto" in df.columns:
                df["Saldo netto"] = df["Saldo netto"].apply(lambda v: fmt_eur_it(v, 2, signed=True))
            table = df.to_html(index=False, border=0, classes="report-table", escape=False)
        else:
            table = "<p class='note'>Nessun movimento per strumento in questo intervallo.</p>"
        blocks.append(
            f"""
            <div class="interval-block">
              <h3>{html.escape(str(item.get('label') or 'Intervallo'))}</h3>
              <div class="grid interval-grid">
                {_kpi("Acquisti", fmt_eur_it(summary.get('buy_net_outflow'), 2), f"{fmt_num_it(summary.get('buy_count'), 0)} operazioni")}
                {_kpi("Vendite/rimborsi", fmt_eur_it(summary.get('sell_net_inflow'), 2), f"{fmt_num_it(summary.get('sell_count'), 0)} operazioni")}
                {_kpi("Cedole/dividendi", fmt_eur_it(summary.get('income_net'), 2), f"{fmt_num_it(summary.get('income_count'), 0)} eventi")}
                {_kpi("Saldo netto", fmt_eur_it(summary.get('net_cash_delta'), 2, signed=True), "Cassa del periodo")}
              </div>
              <div style="margin-top:14px">{table}</div>
            </div>
            """
        )
    return f"<section><h2>Movimenti tra snapshot</h2>{''.join(blocks)}</section>"


def _format_metrics_table(frame: pd.DataFrame) -> str:
    if frame is None or frame.empty:
        return "<p class='note'>Nessuna metrica disponibile.</p>"
    df = frame.copy().astype(object)
    for idx, row in df.iterrows():
        is_pct = str(row.get("Voce")) == "Rendimento"
        for col in df.columns:
            if col == "Voce":
                continue
            value = row.get(col)
            df.at[idx, col] = fmt_pct_it(value, 2, signed=("Delta" in col)) if is_pct else fmt_eur_it(value, 2, signed=("Delta" in col))
    return df.to_html(index=False, border=0, classes="report-table", escape=False)


def _format_currency_table(frame: pd.DataFrame, *, key_col: str) -> str:
    if frame is None or frame.empty:
        return "<p class='note'>Dati non disponibili.</p>"
    df = frame.copy()
    for col in df.columns:
        if col == key_col:
            continue
        df[col] = df[col].apply(lambda v, col_name=col: fmt_eur_it(v, 2, signed=("Delta" in col_name)))
    return df.to_html(index=False, border=0, classes="report-table", escape=False)


def _format_percent_table(frame: pd.DataFrame, *, key_col: str) -> str:
    if frame is None or frame.empty:
        return "<p class='note'>Dati non disponibili.</p>"
    df = frame.copy()
    for col in df.columns:
        if col == key_col:
            continue
        df[col] = df[col].apply(lambda v, col_name=col: fmt_pct_it(v, 2, signed=("Delta" in col_name)))
    return df.to_html(index=False, border=0, classes="report-table", escape=False)


def _format_quote_price_table(frame: pd.DataFrame) -> str:
    if frame is None or frame.empty:
        return "<p class='note'>Dettaglio strumenti non disponibile.</p>"
    keep = [col for col in frame.columns if col in {"Ticker", "Strumento"} or col.startswith("Quote ") or col in {"Delta quote complessivo", "Delta prezzo % complessivo"} or col.startswith("Prezzo ")]
    df = frame[keep].copy()
    for col in df.columns:
        if col in {"Ticker", "Strumento"}:
            continue
        if "Prezzo" in col and "%" not in col:
            df[col] = df[col].apply(lambda v: fmt_eur_it(v, 4))
        elif "%" in col:
            df[col] = df[col].apply(lambda v: fmt_pct_it(v, 2, signed=True))
        elif "Delta" in col:
            df[col] = df[col].apply(lambda v: fmt_num_it(v, 4, signed=True))
        else:
            df[col] = df[col].apply(lambda v: fmt_qty_it(v, 4))
    return df.to_html(index=False, border=0, classes="report-table", escape=False)


def _format_capital_table(frame: pd.DataFrame) -> str:
    if frame is None or frame.empty:
        return "<p class='note'>Dettaglio strumenti non disponibile.</p>"
    keep = [col for col in frame.columns if col in {"Ticker", "Strumento", "Categoria"} or col.startswith("Costo ") or col.startswith("Valore ") or col in {"Delta costo complessivo", "Delta valore complessivo"}]
    df = frame[keep].copy()
    for col in df.columns:
        if col in {"Ticker", "Strumento", "Categoria"}:
            continue
        df[col] = df[col].apply(lambda v, col_name=col: fmt_eur_it(v, 2, signed=("Delta" in col_name)))
    return df.to_html(index=False, border=0, classes="report-table", escape=False)


def _format_performance_table(frame: pd.DataFrame) -> str:
    if frame is None or frame.empty:
        return "<p class='note'>Dettaglio strumenti non disponibile.</p>"
    keep = [col for col in frame.columns if col in {"Ticker", "Strumento"} or col.startswith("P/L ") or col.startswith("Rendimento ") or col in {"Delta P/L complessivo", "Delta rendimento complessivo"}]
    df = frame[keep].copy()
    for col in df.columns:
        if col in {"Ticker", "Strumento"}:
            continue
        if "Rendimento" in col:
            df[col] = df[col].apply(lambda v, col_name=col: fmt_pct_it(v, 2, signed=("Delta" in col_name)))
        else:
            df[col] = df[col].apply(lambda v: fmt_eur_it(v, 2, signed=True))
    return df.to_html(index=False, border=0, classes="report-table", escape=False)


def _embed_figure(fig: Any) -> str:
    if fig is None:
        return "<p class='note'>Grafico non disponibile.</p>"
    try:
        clone = go.Figure(fig)
        return pio.to_html(clone, include_plotlyjs=False, full_html=False, config={"displayModeBar": False, "responsive": True})
    except Exception:
        return "<p class='note'>Grafico non esportabile.</p>"


def _kpi(label: str, value: str, note: str = "") -> str:
    return f"<div class='kpi'><span>{html.escape(label)}</span><strong>{value}</strong><small>{html.escape(note)}</small></div>"


def _html_page(body: str, title: str) -> str:
    css = """
    *{box-sizing:border-box} body{margin:0;background:#f3f6f9;color:#1f2937;font-family:system-ui,-apple-system,Segoe UI,Arial,sans-serif;font-size:14px;line-height:1.5}
    .page{max-width:1200px;margin:0 auto;padding:28px}
    .hero{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:24px;align-items:end;background:#16324f;color:white;border-radius:18px;padding:28px 32px;margin-bottom:20px}
    .hero h1{margin:4px 0 8px 0;font-size:1.9rem;line-height:1.1}.hero p{margin:0;color:rgba(255,255,255,.82)}
    .eyebrow{text-transform:uppercase;letter-spacing:.08em;font-size:.76rem;font-weight:800;color:rgba(255,255,255,.72)}
    .hero-meta{display:grid;gap:4px;text-align:right;font-size:.86rem}.hero-meta span{color:rgba(255,255,255,.78)}
    section{background:white;border:1px solid #dde5ee;border-radius:14px;padding:20px 22px;margin:0 0 16px 0;box-shadow:0 6px 18px rgba(15,23,42,.04)}
    h2{font-size:1.08rem;margin:0 0 14px 0;padding-bottom:7px;border-bottom:2px solid #e7edf4;color:#10243a}
    h3{margin:0 0 12px 0;font-size:.94rem;color:#10243a}
    .grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.two-col{display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start}
    .kpi{border:1px solid #e2e8f0;background:#f8fafc;border-radius:12px;padding:12px 14px;min-height:88px}.kpi span{display:block;font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;color:#64748b;font-weight:800}.kpi strong{display:block;margin-top:5px;font-size:1.28rem;color:#111827}.kpi small{display:block;margin-top:4px;color:#7b8794}
    table{width:100%;border-collapse:collapse;font-size:.82rem}th,td{border:1px solid #e2e8f0;padding:7px 9px;vertical-align:top}th{background:#eef3f8;text-align:left;font-weight:800}
    .note{font-size:.84rem;color:#526173;background:#f8fafc}.interval-block{margin-top:14px}
    ul{margin:0;padding-left:20px}
    @media print{body{background:white}.page{padding:10px}section{box-shadow:none;break-inside:avoid}.two-col{grid-template-columns:1fr 1fr}.grid{grid-template-columns:repeat(4,1fr)}}
    @media (max-width:840px){.page{padding:14px}.hero,.two-col{grid-template-columns:1fr}.hero-meta{text-align:left}.grid{grid-template-columns:1fr 1fr}}
    """
    escaped_title = html.escape(title)
    return f"<!doctype html><html lang='it'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{escaped_title}</title><script src='https://cdn.plot.ly/plotly-2.35.2.min.js'></script><style>{css}</style></head><body><main class='page'>{body}</main></body></html>"
