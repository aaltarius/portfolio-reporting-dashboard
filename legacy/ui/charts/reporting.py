# LEGACY (2026-07-07): nessun importer nell'app viva (verificato con grep sull'intero
# repo). report_table_html/build_report_html restano qui solo come riferimento,
# non caricati da nessuna pagina.
from __future__ import annotations

import pandas as pd

from ui.formatting import fmt_dt_it, fmt_eur_it, fmt_pct_it, fmt_qty_it

# Modulo shared reporting/export.
# Ruolo:
# - genera HTML tabellare per report statici
# - usato da runtime/reporting, non dal render Plotly interattivo delle pagine


def report_table_html(df):
    """Return a simple HTML table for reporting/export flows."""
    if df is None or df.empty:
        return "<p>Nessun dato disponibile.</p>"
    return df.to_html(index=False, border=0, classes="report-table", escape=False)


def build_report_html(
    report_kind,
    header_date,
    da_frame,
    macro_summary_df,
    ops_df,
    dfh,
    analysis_text,
    last_quotes_update,
    capital_value=0.0,
):
    """Build the full reporting HTML document.

    Chiamato da: flussi shared di reporting/export tramite ui/runtime_context.py.
    Nota: non e' legato a un chart_id singolo; compone tabelle e sezioni statiche.
    """
    detailed = report_kind == "analitico"
    css = """
    <style>
    body{font-family:Arial,Helvetica,sans-serif;color:#1f2937;margin:24px}
    h1,h2,h3{margin:0 0 10px 0;color:#111827}
    .meta{color:#6b7280;font-size:12px;margin-bottom:16px}
    .grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:16px 0}
    .card{border:1px solid #d1d5db;border-radius:10px;padding:12px}
    .card-title{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:#6b7280;margin-bottom:6px}
    .card-value{font-size:22px;font-weight:700}
    .section{margin-top:22px}
    .report-table{width:100%;border-collapse:collapse;font-size:12px}
    .report-table th,.report-table td{border:1px solid #d1d5db;padding:6px 8px;text-align:left}
    .report-table th{background:#f3f4f6}
    .small{font-size:12px;color:#4b5563}
    </style>
    """
    tv = da_frame["Controvalore"].sum() if da_frame is not None and (not da_frame.empty) else 0.0
    tc = da_frame["Costo"].sum() if da_frame is not None and (not da_frame.empty) else 0.0
    pl = tv - tc
    pp = pl / abs(tc) if abs(tc) > 1e-09 else 0.0
    cap = float(capital_value or 0.0)
    cards = (
        f"""
    <div class="grid">
      <div class="card"><div class="card-title">Capitale versato</div><div class="card-value">{fmt_eur_it(cap, 2)}</div></div>
      <div class="card"><div class="card-title">Valore di mercato</div><div class="card-value">{fmt_eur_it(tv, 2)}</div></div>
      <div class="card"><div class="card-title">P/L complessivo</div><div class="card-value">{fmt_eur_it(pl, 2, signed=True)} ({fmt_pct_it(pp, 2, signed=True)})</div></div>
      <div class="card"><div class="card-title">Ultimo aggiornamento quotazioni</div><div class="card-value" style="font-size:18px">{fmt_dt_it(last_quotes_update)}</div></div>
    </div>
    """
    )
    sections = [
        f"<h1>Portafoglio Titoli — Report {report_kind.title()}</h1>",
        f'<div class="meta">Generato il {header_date}</div>',
        cards,
        '<div class="section"><h2>Sintesi interpretativa</h2><p class="small">' + analysis_text + "</p></div>",
        '<div class="section"><h2>Sintesi allocazione</h2>' + report_table_html(macro_summary_df) + "</div>",
    ]
    if detailed:
        port = da_frame.copy() if da_frame is not None else pd.DataFrame()
        if not port.empty:
            port = port[
                ["Ticker", "Strumento", "Tipo", "Quote", "Prezzo", "PMC", "Controvalore", "Costo", "P/L €", "P/L %"]
            ].copy()
            for col in ["Prezzo", "PMC"]:
                port[col] = port[col].map(lambda v: fmt_eur_it(v, 3))
            port["Controvalore"] = port["Controvalore"].map(lambda v: fmt_eur_it(v, 2))
            port["Costo"] = port["Costo"].map(lambda v: fmt_eur_it(v, 2))
            port["P/L €"] = port["P/L €"].map(lambda v: fmt_eur_it(v, 2, signed=True))
            port["Quote"] = port["Quote"].map(lambda v: fmt_qty_it(v, 4))
            port["P/L %"] = port["P/L %"].map(lambda v: fmt_pct_it(v, 2, signed=True))
        sections.append(
            '<div class="section"><h2>Controvalore del portafoglio</h2>'
            + report_table_html(port)
            + "</div>"
        )
        if ops_df is not None and (not ops_df.empty):
            sections.append('<div class="section"><h2>Operazioni</h2>' + report_table_html(ops_df) + "</div>")
        if dfh is not None and (not dfh.empty):
            hist = dfh[["Data", "Valore", "Costo", "Capitale", "P/L"]].copy().tail(20)
            hist["Data"] = hist["Data"].dt.strftime("%d/%m/%Y")
            hist["Valore"] = hist["Valore"].map(lambda v: fmt_eur_it(v, 2))
            hist["Costo"] = hist["Costo"].map(lambda v: fmt_eur_it(v, 2))
            hist["Capitale"] = hist["Capitale"].map(lambda v: fmt_eur_it(v, 2))
            hist["P/L"] = hist["P/L"].map(lambda v: fmt_eur_it(v, 2, signed=True))
            sections.append('<div class="section"><h2>Storico recente</h2>' + report_table_html(hist) + "</div>")
    return "<html><head><meta charset='utf-8'>" + css + "</head><body>" + "".join(sections) + "</body></html>"
