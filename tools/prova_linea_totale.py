"""Anteprima di prova dello stile della linea «Totale netto» nei due grafici a aree con segno (TM-03).

Non tocca nessuna pagina né impostazione dell'app: legge in sola lettura il portafoglio e scrive un file HTML autonomo in
`data/cache/prove_grafici/` (ignorata da git: contiene dati personali, non va condiviso né pubblicato). Per ogni variante mostra
«P/L per Categoria» e «Contributo al P/L (Area Stacked)». Uso:  python -m tools.prova_linea_totale [--apri]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "cache" / "prove_grafici" / "prova_linea_totale.html"

# (nome, descrizione, colore linea, spessore, tratto, spessore alone, colore alone, punti)
VARIANTI = [   # tutte: linea piena larga 2 su fascia grigio chiaro larga 4 (richiesta dell'utente); cambia solo il colore acceso
    ("1. Lime acceso", "Verde-giallo molto saturo: nessuno strumento ha questa tinta (i verdi della palette sono verde-acqua).", "#76d900", 2, "solid", 4, "#bcc2cb", False),
    ("2. Verde neon", "Verde brillante: stacca bene, ma richiama il verde dei guadagni.", "#00e676", 2, "solid", 4, "#bcc2cb", False),
    ("3. Giallo elettrico", "Giallo puro molto acceso: più freddo dell'ambra di GOV e degli strumenti arancio.", "#ffea00", 2, "solid", 4, "#bcc2cb", False),
    ("4. Ciano elettrico", "Azzurro brillante: vicino ai turchesi di alcuni strumenti.", "#00e5ff", 2, "solid", 4, "#bcc2cb", False),
    ("5. Blu elettrico", "Blu molto saturo: vicino all'azzurro di ETF, ma più profondo.", "#2962ff", 2, "solid", 4, "#bcc2cb", False),
    ("6. Bianco puro", "Linea bianca sulla fascia grigia: massimo contrasto su qualunque colore.", "#ffffff", 2, "solid", 4, "#9aa1ab", False),
]


def _style(fig, col, width, dash, halo_w, halo_c, dots, title):
    for t in fig.data:
        if t.name == "Totale netto (alone)":
            if halo_w:
                t.line.width, t.line.color, t.opacity = halo_w, halo_c, 1
            else:
                t.visible = False
        elif t.name == "Totale netto":
            t.line.color, t.line.width, t.line.dash = col, width, dash
            if dots:
                t.mode, t.marker = "lines+markers", dict(size=5, color=col)
    fig.update_layout(width=None, autosize=True, height=460, title=dict(text=f"<b>{title}</b>"))
    return fig


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apri", action="store_true", help="apre il file nel browser")
    args = ap.parse_args(argv)
    import persistence.storage as st
    from persistence.parquet_utils import load_storico_prezzi_hybrid
    from core.finance import build_portfolio_history_df, build_ptf_df
    from persistence.storage import macro_cat
    from ui.charts.analitica import build_pl_decomposition_time_chart
    from ui.charts.overview import build_overview_time_chart
    from ui.theme import get_theme_context
    data = json.load(open(st.DATA_FILE, encoding="utf-8-sig"))
    data["storico_prezzi"] = load_storico_prezzi_hybrid(st.STORICO_PREZZI_FILE)
    dfh = build_portfolio_history_df(data)
    dfh = dfh[pd.to_datetime(dfh["Data"]) >= pd.to_datetime(dfh["Data"]).max() - pd.Timedelta(days=50)].reset_index(drop=True)
    da = build_ptf_df(data)
    da["Categoria"] = da["Tipo"].apply(macro_cat)
    theme = get_theme_context()
    pl_cols = [c for c in dfh.columns if c.startswith("PL_")]
    cats = ["GOV", "FND", "ETF", "ETC", "OBB", "AZI"]
    sections, first = [], True
    for name, desc, col, width, dash, halo_w, halo_c, dots in VARIANTI:
        figs = []
        for build, title in ((lambda: build_overview_time_chart(dfh, da, "P/L per Categoria", None, 0.0, None, None, theme, settings={"asset_categories": cats}, data=data), "P/L per Categoria"),
                             (lambda: build_pl_decomposition_time_chart(dfh, pl_cols, "Stacked", None, theme), "Contributo al P/L (Area Stacked)")):
            f = _style(build(), col, width, dash, halo_w, halo_c, dots, title)
            figs.append(f.to_html(include_plotlyjs=True if first else False, full_html=False, default_width="100%", default_height="460px", config={"displaylogo": False, "responsive": True}))
            first = False
        sections.append(f"<section><h2>{name}</h2><p>{desc}</p><div class='row'>{''.join(f'<div class=c>{x}</div>' for x in figs)}</div></section>")
    page = ("<!doctype html><html lang='it'><meta charset='utf-8'><title>Prova linea Totale netto</title>"
            f"<body style='margin:0;padding:24px 32px;background:{theme.bg_app};color:{theme.font_color};font-family:Segoe UI,system-ui,sans-serif'>"
            "<h1 style='margin:0 0 4px'>Prova dello stile della linea «Totale netto»</h1>"
            "<p style='opacity:.75;margin:0 0 20px'>Anteprima generata in sola lettura dai tuoi dati reali. Non modifica nessuna pagina dell'app. "
            "<b>Contiene dati personali: non condividerla né pubblicarla.</b></p>"
            f"<style>section{{margin:0 0 26px;padding:12px 14px;border-radius:14px;background:{theme.bg_chart};border:1px solid {theme.border_color}}}"
            "h2{margin:0 0 2px;font-size:1.05rem}section>p{margin:0 0 6px;opacity:.8;font-size:.92rem}.row{display:block}.c{width:100%;margin-bottom:8px}</style>"
            + "".join(sections) + "</body></html>")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"Scritto: {OUT}")
    if args.apri:
        os.startfile(str(OUT))  # noqa: S606 - apertura locale del file appena scritto
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
