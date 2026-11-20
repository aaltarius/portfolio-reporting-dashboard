"""Pagina di PROVE per rappresentare il P/L (TM-03): non tocca nessun grafico dell'app né i dati.

Legge in sola lettura il portafoglio e produce un file HTML autonomo con quattro rappresentazioni complementari alle aree
impilate con segno. Il file contiene dati personali: viene scritto in `data/cache/prove_grafici/` (ignorata da git) e non va
condiviso né pubblicato. Uso:  python -m tools.prova_grafici_pl [--giorni 30] [--apri]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "data" / "cache" / "prove_grafici"


def _load():
    import persistence.storage as st
    from persistence.parquet_utils import load_storico_prezzi_hybrid
    from core.finance import build_portfolio_history_df
    data = json.load(open(st.DATA_FILE, encoding="utf-8-sig"))
    data["storico_prezzi"] = load_storico_prezzi_hybrid(st.STORICO_PREZZI_FILE)
    return data, build_portfolio_history_df(data)


def _layout(fig: go.Figure, theme, title: str, height: int) -> go.Figure:
    fig.update_layout(
        title=dict(text=f"<b>{title}</b>", x=0.5), height=height, paper_bgcolor=theme.bg_chart, plot_bgcolor=theme.bg_chart,
        font=dict(color=theme.font_color), margin=dict(l=110, r=40, t=60, b=50), hovermode="closest",
    )
    fig.update_xaxes(gridcolor=theme.grid_color)
    fig.update_yaxes(gridcolor=theme.grid_color)
    return fig


from core.services.pl_calendar import daily_market_change as _daily_series  # noqa: E402


def _daily_market_change(pl: pd.DataFrame) -> pd.Series:
    """Variazione giornaliera dovuta al mercato (stessa funzione dell'app, `core/services/pl_calendar.py`)."""
    return _daily_series(pl.reset_index().rename(columns={pl.index.name or 'index': 'Data'}).rename(columns=lambda c: c if c == 'Data' else f'PL_{c}'))


def _eur(v: float) -> str:
    return f"{v:+,.0f} €".replace(",", ".")


def build_figures(dfh: pd.DataFrame, data: dict, theme, days: int) -> list[tuple[str, str, go.Figure]]:
    from persistence.storage import macro_cat
    up, down = theme.colors["success"], theme.colors["danger"]
    cols = [c for c in dfh.columns if c.startswith("PL_")]
    pl = dfh.set_index(pd.to_datetime(dfh["Data"]))[cols].apply(pd.to_numeric, errors="coerce")
    pl.columns = [c[3:] for c in cols]
    last = pl.iloc[-1].dropna()
    cat = {str(s.get("ticker") or ""): macro_cat(str(s.get("tipo") or "")) for s in data.get("strumenti", [])}
    out: list[tuple[str, str, go.Figure]] = []

    # 1) Classifica dei contributi
    rank = last.sort_values()
    fig = go.Figure(go.Bar(x=rank.values, y=rank.index, orientation="h", marker_color=[up if v >= 0 else down for v in rank.values],
                           text=[_eur(v) for v in rank.values], textposition="outside", cliponaxis=False,
                           hovertemplate="%{y}: %{x:+,.2f} €<extra></extra>"))
    fig.add_vline(x=0, line_width=1.5, line_color=theme.font_color)
    fig.add_annotation(x=0.99, y=1.0, xref="paper", yref="paper", showarrow=False, xanchor="right", yanchor="bottom",
                       text=f"Totale netto <b>{_eur(float(last.sum()))}</b>", font=dict(size=13))
    out.append(("1. Classifica dei contributi",
                "P/L di oggi per strumento, ordinato: a sinistra chi frena, a destra chi trascina. Risponde a «chi sta pesando di più?».",
                _layout(fig, theme, "Chi trascina e chi frena (P/L di oggi)", max(360, 26 * len(rank) + 120))))

    # 2) Cascata per categoria e per strumento
    def waterfall(values: pd.Series, title: str) -> go.Figure:
        order = values.sort_values(ascending=False)
        fig = go.Figure(go.Waterfall(
            x=list(order.index) + ["Totale netto"], y=list(order.values) + [0], measure=["relative"] * len(order) + ["total"],
            text=[_eur(v) for v in order.values] + [_eur(float(order.sum()))], textposition="outside",
            increasing=dict(marker=dict(color=up)), decreasing=dict(marker=dict(color=down)),
            totals=dict(marker=dict(color=theme.color_blue)), connector=dict(line=dict(color=theme.muted_color, width=1)),
            hovertemplate="%{x}: %{y:+,.2f} €<extra></extra>"))
        fig.add_hline(y=0, line_width=1.2, line_color=theme.font_color)
        return _layout(fig, theme, title, 420)
    by_cat = last.groupby(lambda tk: cat.get(tk, "Altro")).sum()
    by_cat = by_cat[by_cat.abs() > 0.005]
    out.append(("2a. Cascata per categoria",
                "Parte da zero, ogni categoria è un gradino verso l'alto (guadagno) o il basso (perdita) fino al totale netto in blu. Risponde a «come si arriva a questo totale?».",
                waterfall(by_cat, "Come si arriva al totale: per categoria")))
    out.append(("2b. Cascata per strumento", "Come sopra, ma strumento per strumento: dal maggior guadagno alla maggior perdita.",
                waterfall(last, "Come si arriva al totale: per strumento")))

    # 3) Mappa di calore delle variazioni giornaliere
    delta = pl.diff().iloc[-days:].dropna(how="all", axis=1).fillna(0.0)
    delta = delta.loc[:, delta.abs().sum().sort_values(ascending=False).index]
    lim = float(max(abs(delta.values).max(), 1.0))
    fig = go.Figure(go.Heatmap(
        z=delta.T.values, x=[d.strftime("%d/%m") for d in delta.index], y=list(delta.columns), zmid=0, zmin=-lim, zmax=lim,
        colorscale=[[0, down], [0.5, theme.bg_chart], [1, up]], colorbar=dict(title="€ nel giorno"),
        hovertemplate="%{y} · %{x}: %{z:+,.2f} €<extra></extra>", xgap=1, ygap=1))
    fig.update_yaxes(autorange="reversed")
    out.append(("3. Mappa di calore dei giorni",
                "Ogni cella è la variazione di P/L di uno strumento in un giorno (verde guadagno, rosso perdita, più intenso = più grande). Mostra i giorni e gli strumenti problematici; gli strumenti più mossi stanno in alto.",
                _layout(fig, theme, f"Variazione giornaliera per strumento (ultimi {len(delta)} giorni)", max(380, 24 * len(delta.columns) + 140))))

    # 4) Variazione netta giornaliera (sopra) e P/L complessivo (sotto), stesso asse dei giorni
    from plotly.subplots import make_subplots
    net = pl.sum(axis=1)
    daily = _daily_market_change(pl).iloc[-days:]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.55, 0.45], vertical_spacing=0.08,
                        subplot_titles=("Variazione del giorno (€)", "P/L complessivo (€)"))
    fig.add_trace(go.Bar(x=daily.index, y=daily.values, marker_color=[up if v >= 0 else down for v in daily.values], name="Variazione del giorno",
                         hovertemplate="%{x|%d/%m}: %{y:+,.2f} €<extra></extra>", showlegend=False), row=1, col=1)
    tail = net.iloc[-days:]
    fig.add_trace(go.Scatter(x=tail.index, y=tail.values, name="P/L complessivo", mode="lines", fill="tozeroy",
                             line=dict(color=theme.muted_color, width=2.2), fillcolor="rgba(120,130,150,0.18)",
                             hovertemplate="%{x|%d/%m}: %{y:+,.2f} €<extra></extra>", showlegend=False), row=2, col=1)
    fig.add_hline(y=0, line_width=1.2, line_color=theme.font_color, row=1, col=1)
    fig.add_hline(y=0, line_width=1.2, line_color=theme.font_color, row=2, col=1)
    out.append(("4. Variazione giornaliera e cumulato",
                "In alto quanto è cambiato il P/L netto in ciascun giorno; in basso il P/L complessivo, sugli stessi giorni. Risponde a «quanto ho guadagnato o perso al giorno, e dove sono arrivato?».",
                _layout(fig, theme, "P/L netto: giorno per giorno e cumulato", 560)))
    return out


def build_figures_v2(dfh: pd.DataFrame, data: dict, theme, days: int) -> list[tuple[str, str, go.Figure]]:
    """Seconda pagina di prove: rappresentazioni nuove e di impatto (non dei grafici già presenti nell'app)."""
    from core.finance import build_ptf_df
    from persistence.storage import macro_cat
    up, down = theme.colors["success"], theme.colors["danger"]
    da = build_ptf_df(data)
    pl_col = next(c for c in da.columns if c.startswith("P/L") and "%" not in c and "Realizz" not in c)
    da = da[pd.to_numeric(da["Controvalore"], errors="coerce").fillna(0) > 0].copy()
    da["pl"] = pd.to_numeric(da[pl_col], errors="coerce").fillna(0.0)
    da["val"] = pd.to_numeric(da["Controvalore"], errors="coerce").fillna(0.0)
    da["pct"] = pd.to_numeric(da["P/L %"], errors="coerce").fillna(0.0) * 100.0      # la colonna è una frazione: qui in %
    da["cat"] = da["Tipo"].apply(macro_cat)
    gains, losses = da[da.pl > 0].sort_values("pl", ascending=False), da[da.pl < 0].sort_values("pl")
    net = float(da.pl.sum())
    out: list[tuple[str, str, go.Figure]] = []

    # A) La bilancia: guadagni a destra, perdite a sinistra, nel mezzo il netto
    fig = go.Figure()
    big = 0.085 * max(float(gains.pl.sum()), float(-losses.pl.sum()), 1.0)

    def shade(base: str, i: int, n: int) -> str:
        return base if n <= 1 else f"rgba({int(base[1:3], 16)},{int(base[3:5], 16)},{int(base[5:7], 16)},{1.0 - 0.45 * i / max(n - 1, 1):.2f})"
    for side, color in ((gains, up), (losses, down)):
        for i, (_, r) in enumerate(side.iterrows()):
            fig.add_trace(go.Bar(y=["P/L"], x=[r.pl], orientation="h", name=r.Ticker, marker=dict(color=shade(color, i, len(side)), line=dict(color=theme.bg_chart, width=1.5)),
                                 text=[r.Ticker if abs(r.pl) >= big else ""], textposition="inside", insidetextanchor="middle", textangle=0, textfont=dict(color="#ffffff", size=13),
                                 hovertemplate=f"{r.Ticker}: %{{x:+,.0f}} €<extra></extra>", showlegend=False))
    span = max(float(gains.pl.sum()), float(-losses.pl.sum()), 1.0)
    fig.update_layout(barmode="relative", bargap=0.15)
    fig.add_vline(x=0, line_width=2, line_color=theme.font_color)
    fig.add_trace(go.Scatter(x=[net], y=["P/L"], mode="markers", marker=dict(symbol="diamond", size=22, color=theme.bg_chart, line=dict(color=theme.font_color, width=3)),
                             hovertemplate=f"Totale netto: {net:+,.0f} €<extra></extra>", showlegend=False))
    fig.add_annotation(x=-span / 2, y=1.22, yref="paper", showarrow=False, text=f"<b>PERDITE  {_eur(float(losses.pl.sum()))}</b>", font=dict(size=20, color=down))
    fig.add_annotation(x=span / 2, y=1.22, yref="paper", showarrow=False, text=f"<b>GUADAGNI  {_eur(float(gains.pl.sum()))}</b>", font=dict(size=20, color=up))
    fig.add_annotation(x=net, y=-0.42, yref="paper", showarrow=True, ay=34, ax=0, arrowcolor=theme.font_color, xanchor="center",
                       text=f"<b>NETTO {_eur(net)}</b>", font=dict(size=20, color=theme.font_color))
    fig.update_xaxes(range=[-span * 1.08, span * 1.08], zeroline=False, tickformat="+,.0f", ticksuffix=" €")
    fig.update_yaxes(visible=False)
    out.append(("A. La bilancia", "Tutti i guadagni a destra, tutte le perdite a sinistra, ognuno col suo strumento; il rombo è il totale netto. Si capisce al volo se pesa di più il verde o il rosso e chi sono i protagonisti.",
                _layout(fig, theme, "Guadagni contro perdite", 330).update_layout(margin=dict(l=40, r=40, t=110, b=110), showlegend=False)))

    # B) Mappa del portafoglio (treemap): dimensione = controvalore, colore = P/L %
    labels, parents, values, colors, custom, ids = [], [], [], [], [], []
    lim = float(max(da.pct.abs().max(), 0.5))
    for cat, g in da.groupby("cat"):
        ids.append(f"c_{cat}"); labels.append(cat); parents.append(""); values.append(float(g.val.sum()))
        gpct = float(g.pl.sum() / max(g.val.sum() - g.pl.sum(), 1.0) * 100)
        colors.append(gpct); custom.append(f"{_eur(float(g.pl.sum()))} · {gpct:+.1f}%")
        for _, r in g.sort_values("val", ascending=False).iterrows():
            ids.append(f"t_{r.Ticker}"); labels.append(r.Ticker); parents.append(f"c_{cat}"); values.append(float(r.val))
            colors.append(float(r.pct)); custom.append(f"{_eur(float(r.pl))} · {float(r.pct):+.1f}%")
    fig = go.Figure(go.Treemap(ids=ids, labels=labels, parents=parents, values=values, branchvalues="total", customdata=custom,
                               marker=dict(colors=colors, colorscale=[[0, down], [0.5, theme.bg_chart], [1, up]], cmid=0, cmin=-lim, cmax=lim,
                                           line=dict(width=2, color=theme.bg_chart), colorbar=dict(title="P/L %", ticksuffix="%")),
                               texttemplate="<b>%{label}</b><br>%{customdata}", hovertemplate="%{label}<br>Controvalore: %{value:,.0f} €<br>P/L: %{customdata}<extra></extra>",
                               textfont=dict(size=15), pathbar=dict(visible=False), tiling=dict(pad=3)))
    out.append(("B. Mappa del portafoglio", "Ogni rettangolo è uno strumento: più è grande più soldi ci sono dentro, più è verde/rosso più sta guadagnando/perdendo in percentuale. Raggruppati per categoria. Si vede dove sono i soldi e dove fa male.",
                _layout(fig, theme, "Dove sono i soldi e come stanno andando", 560).update_layout(margin=dict(l=20, r=20, t=60, b=20))))

    # C) Quadranti: P/L % contro P/L €, dimensione = controvalore
    fig = go.Figure()
    fig.add_shape(type="rect", x0=0, x1=1, y0=0, y1=1, xref="x domain", yref="y domain", fillcolor="rgba(0,0,0,0)", line_width=0)
    fig.add_trace(go.Scatter(x=da.pct, y=da.pl, mode="markers+text", text=da.Ticker, textposition="top center", textfont=dict(size=12),
                             marker=dict(size=da.val, sizemode="area", sizeref=2.0 * float(da.val.max()) / (70.0 ** 2), sizemin=8,
                                         color=[up if v >= 0 else down for v in da.pl], opacity=0.78, line=dict(color=theme.bg_chart, width=1.5)),
                             customdata=da.val, hovertemplate="%{text}<br>P/L: %{y:+,.0f} € (%{x:+.2f}%)<br>Controvalore: %{customdata:,.0f} €<extra></extra>", showlegend=False))
    fig.add_vline(x=0, line_width=1.5, line_color=theme.font_color)
    fig.add_hline(y=0, line_width=1.5, line_color=theme.font_color)
    fig.update_xaxes(title="P/L in % sul costo", ticksuffix="%", zeroline=False)
    fig.update_yaxes(title="P/L in €", ticksuffix=" €", zeroline=False)
    for x, y, t, c in ((0.98, 0.97, "rende bene e pesa", up), (0.02, 0.03, "rende male e pesa", down)):
        fig.add_annotation(xref="paper", yref="paper", x=x, y=y, xanchor="right" if x > 0.5 else "left", yanchor="top" if y > 0.5 else "bottom",
                           text=f"<b>{t}</b>", showarrow=False, font=dict(size=13, color=c), opacity=0.8)
    out.append(("C. I quadranti", "Ogni bolla è uno strumento: a destra rende, a sinistra perde (in %); in alto guadagna, in basso perde (in €); la grandezza è quanti soldi ci sono dentro. Le bolle grandi in basso a sinistra sono i problemi veri.",
                _layout(fig, theme, "Quanto rende e quanto pesa", 520)))

    # D) Calendario del P/L netto giornaliero
    cols = [c for c in dfh.columns if c.startswith("PL_")]
    plx = dfh.set_index(pd.to_datetime(dfh["Data"]))[cols].apply(pd.to_numeric, errors="coerce")
    daily = _daily_market_change(plx).dropna().iloc[-91:]
    weeks = sorted({d - pd.Timedelta(days=d.weekday()) for d in daily.index})
    z = [[None] * len(weeks) for _ in range(5)]
    txt = [[""] * len(weeks) for _ in range(5)]
    for d, v in daily.items():
        if d.weekday() < 5:
            wi = weeks.index(d - pd.Timedelta(days=d.weekday()))
            z[d.weekday()][wi] = float(v)
            txt[d.weekday()][wi] = f"{d.day}<br><b>{v:+,.0f}</b>".replace(",", ".")
    lim = float(max(abs(daily).max(), 1.0))
    fig = go.Figure(go.Heatmap(z=z, x=[w.strftime("sett. %d/%m") for w in weeks], y=["Lun", "Mar", "Mer", "Gio", "Ven"], text=txt, texttemplate="%{text}", zmid=0, zmin=-lim, zmax=lim,
                               colorscale=[[0, down], [0.5, theme.bg_chart], [1, up]], xgap=4, ygap=4, hoverongaps=False, colorbar=dict(title="€ nel giorno"),
                               hovertemplate="%{x} · %{y}: %{z:+,.0f} €<extra></extra>", textfont=dict(size=12)))
    fig.update_yaxes(autorange="reversed")
    out.append(("D. Il calendario", "Un riquadro per ogni giorno di Borsa degli ultimi tre mesi: verde se il P/L è salito, rosso se è sceso (col numero in euro). Le settimane buone e quelle storte si vedono a colpo d'occhio.",
                _layout(fig, theme, "Giorno per giorno: com'è andata", 380)))
    return out


def render_html(sections: list[tuple[str, str, go.Figure]], theme) -> str:
    parts = []
    for i, (title, note, fig) in enumerate(sections):
        parts.append(f"<section><h2>{title}</h2><p>{note}</p>"
                     f"{fig.to_html(include_plotlyjs=True if i == 0 else False, full_html=False, config={'displaylogo': False})}</section>")
    return (f"<!doctype html><html lang='it'><meta charset='utf-8'><title>Prove grafici P/L</title>"
            f"<body style='margin:0;padding:24px 32px;background:{theme.bg_app};color:{theme.font_color};font-family:Segoe UI,system-ui,sans-serif'>"
            "<h1 style='margin:0 0 4px'>Prove di rappresentazione del P/L</h1>"
            "<p style='opacity:.75;margin:0 0 20px'>Pagina di prova generata in sola lettura dai tuoi dati reali. Non modifica nessun grafico dell'app. "
            "<b>Contiene dati personali: non condividerla né pubblicarla.</b></p>"
            "<style>section{margin:0 0 28px;padding:14px 16px;border-radius:14px;background:" + theme.bg_chart + ";border:1px solid " + theme.border_color
            + "}h2{margin:0 0 4px;font-size:1.05rem}section>p{margin:0 0 8px;opacity:.8;font-size:.92rem}</style>"
            + "".join(parts) + "</body></html>")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--giorni", type=int, default=30)
    ap.add_argument("--pagina", choices=["1", "2", "tutte"], default="tutte", help="1 = rappresentazioni classiche, 2 = rappresentazioni nuove")
    ap.add_argument("--apri", action="store_true", help="apre il file nel browser")
    args = ap.parse_args(argv)
    from ui.theme import get_theme_context
    theme = get_theme_context()
    data, dfh = _load()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pages = {"prova_grafici_pl.html": build_figures, "prova_grafici_pl_2.html": build_figures_v2}
    wanted = {"1": ["prova_grafici_pl.html"], "2": ["prova_grafici_pl_2.html"], "tutte": list(pages)}[args.pagina]
    for name in wanted:
        path = OUT_DIR / name
        path.write_text(render_html(pages[name](dfh, data, theme, max(5, args.giorni)), theme), encoding="utf-8")
        print(f"Scritto: {path}")
        if args.apri:
            os.startfile(str(path))  # noqa: S606 - apertura locale del file appena scritto
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
