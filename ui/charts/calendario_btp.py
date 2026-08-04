"""BTP timeline visualization."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.config import COLORS
from core.domain.calendar import TAX_RATE_GOV_PCT
from ui.charts.runtime import finalize_chart
from ui.charts.settings import apply_settings, get_chart_setting
from ui.components import render_styled_table
from ui.formatting import fmt_eur_it
from ui.theme import ThemeConfig
from ui.theme import macro_color


_ALIQUOTA_BTP = TAX_RATE_GOV_PCT / 100.0


def _stima_imposte_scadenza(lordo: float, pmc: float | None) -> float | None:
    """Stima l'imposta sulla plusvalenza a rimborso per un BTP.

    Restituisce None se PMC non disponibile (la cella mostrerà '—').
    """
    # Formula valida per BTP con nominale=100: gain_frac = (100-PMC)/100, lordo = nominale*quantita
    if pmc is None:
        return None
    gain_frac = max(0.0, (100.0 - pmc) / 100.0)
    return lordo * gain_frac * _ALIQUOTA_BTP


def build_btp_calendar_figure(
    calendar_df: pd.DataFrame,
    theme: ThemeConfig | None = None,
    pmc_map: dict[str, float] | None = None,
) -> go.Figure:
    """Build the BTP timeline figure (possession span, coupons, maturity).

    Parte cacheabile di render_btp_calendar: nessuna chiamata st.*, solo
    costruzione della figura Plotly. Se calendar_df è vuoto dopo la pulizia,
    ritorna una go.Figure() vuota (mai None: il chiamante passa sempre il
    risultato a st.plotly_chart).
    """
    df = calendar_df.copy()
    midday = pd.Timedelta(hours=12)
    df["data"] = pd.to_datetime(df["data"], errors="coerce").dt.normalize() + midday
    df["data_inizio"] = pd.to_datetime(df.get("data_inizio"), errors="coerce").dt.normalize() + midday
    df["data_fine"] = pd.to_datetime(df.get("data_fine"), errors="coerce").dt.normalize() + midday
    df = df.dropna(subset=["data"]).sort_values(["ticker", "data"])
    if df.empty:
        return go.Figure()

    tickers = list(df["ticker"].dropna().astype(str).drop_duplicates())
    min_data = df["data"].min()
    max_data = df["data"].max()
    ticker_label_x = min_data - pd.Timedelta(days=40)
    past_line_color = "#0F8A38"
    future_line_color = "#F59E0B"
    elapsed_text_color = "#0F8A38"
    gov_color = macro_color("GOV")
    colors = {
        ("cedola", "incassata"): COLORS["success"],
        ("cedola", "futura"): COLORS["danger"],
        ("scadenza", "incassata"): COLORS["success"],
        ("scadenza", "futura"): "#F59E0B",
    }

    def _duration_label(start: pd.Timestamp, end: pd.Timestamp) -> str:
        start_n = pd.to_datetime(start, errors="coerce")
        end_n = pd.to_datetime(end, errors="coerce")
        if pd.isna(start_n) or pd.isna(end_n):
            return ""
        days = max(int((end_n.normalize() - start_n.normalize()).days), 0)
        years = days // 365
        rem_days = days % 365
        return f"{years}a {rem_days}g"

    fig = go.Figure()
    today = pd.Timestamp.today().normalize() + midday
    spans = df[df["tipo_riga"] == "span"].drop_duplicates(subset=["ticker"])
    for _, row in spans.iterrows():
        start = row.get("data_inizio")
        end = row.get("data_fine")
        if pd.isna(start) or pd.isna(end):
            continue
        past_end = min(end, today)
        future_start = max(start, today)
        if start <= past_end:
            fig.add_trace(
                go.Scatter(
                    x=[start, past_end],
                    y=[row["ticker"], row["ticker"]],
                    mode="lines",
                    line=dict(color=past_line_color, width=4),
                    hovertemplate=(
                        f"<b>{row['ticker']}</b><br>"
                        f"Tempo trascorso: {_duration_label(start, past_end)}<br>"
                        f"Possesso: {start:%d/%m/%Y} → {past_end:%d/%m/%Y}<extra></extra>"
                    ),
                    showlegend=False,
                )
            )
            if start < past_end:
                fig.add_annotation(
                    x=start + (past_end - start) / 2,
                    y=row["ticker"],
                    xref="x",
                    yref="y",
                    text=f"<span style='color:{elapsed_text_color}'>{_duration_label(start, past_end)}</span>",
                    showarrow=False,
                    yshift=-14,
                    yanchor="middle",
                    font=dict(size=11, color=elapsed_text_color),
                    bgcolor="rgba(255,255,255,0.88)",
                )
        if future_start <= end:
            fig.add_trace(
                go.Scatter(
                    x=[future_start, end],
                    y=[row["ticker"], row["ticker"]],
                    mode="lines",
                    line=dict(color=future_line_color, width=4),
                    hovertemplate=(
                        f"<b>{row['ticker']}</b><br>"
                        f"Tempo residuo: {_duration_label(future_start, end)}<br>"
                        f"Residuo: {future_start:%d/%m/%Y} → {end:%d/%m/%Y}<extra></extra>"
                    ),
                    showlegend=False,
                )
            )
            if future_start < end:
                fig.add_annotation(
                    x=future_start + (end - future_start) / 2,
                    y=row["ticker"],
                    xref="x",
                    yref="y",
                    text=_duration_label(future_start, end),
                    showarrow=False,
                    yshift=-14,
                    yanchor="middle",
                    font=dict(size=10, color=future_line_color),
                    bgcolor="rgba(255,255,255,0.88)",
                )
        fig.add_trace(
            go.Scatter(
                x=[start],
                y=[row["ticker"]],
                mode="markers+text",
                marker=dict(
                    size=9,
                    color="#64748B",
                    symbol="circle",
                    line=dict(color="#ffffff", width=1.1),
                ),
                text=None,
                hovertemplate=(
                    f"<b>{row['ticker']}</b><br>"
                    f"Inizio possesso<br>Data: {start:%d/%m/%Y}<extra></extra>"
                ),
                showlegend=False,
            )
        )
        fig.add_annotation(
            x=start,
            y=row["ticker"],
            xref="x",
            yref="y",
            text=f"{start:%d/%m/%Y}",
            showarrow=False,
            xshift=-8,
            yshift=12,
            xanchor="right",
            yanchor="bottom",
            font=dict(size=10, color="#64748B"),
            bgcolor="rgba(255,255,255,0.88)",
        )

    events = df[df["tipo_riga"] == "evento"].copy()
    for (tipo_evento, stato_evento), part in events.groupby(["tipo_evento", "stato_evento"], dropna=False):
        if part.empty:
            continue
        is_coupon = str(tipo_evento) == "cedola"
        marker_symbol = "circle" if is_coupon else "diamond"
        marker_size = 11 if is_coupon else 14
        color = colors.get((str(tipo_evento), str(stato_evento)), "#94A3B8")
        label = "Cedola" if is_coupon else "Rimborso/scadenza"
        fig.add_trace(
            go.Scatter(
                x=part["data"],
                y=part["ticker"],
                mode="markers+text",
                marker=dict(
                    size=marker_size,
                    color=color,
                    symbol=marker_symbol,
                    line=dict(color="#ffffff", width=1.2),
                ),
                text=part["importo"].map(lambda v: fmt_eur_it(v, 2)) if is_coupon and "importo" in part.columns else None,
                textposition="top center",
                textfont=dict(size=10, color=color),
                customdata=part[[c for c in ["nome", "importo", "importo_lordo", "stato_evento"] if c in part.columns]].values,
                hovertemplate=(
                    "<b>%{y}</b><br>%{customdata[0]}<br>"
                    + label
                    + "<br>Importo netto: %{customdata[1]:,.2f} €<br>"
                    + ("Importo lordo: %{customdata[2]:,.2f} €<br>" if "importo_lordo" in part.columns else "")
                    + "Stato: %{customdata[" + ("3" if "importo_lordo" in part.columns else "2") + "]}<br>"
                    + "Data: %{x|%d/%m/%Y}<extra></extra>"
                ),
                name=f"{label} {'incassata' if str(stato_evento) == 'incassata' else 'futura'}",
                showlegend=False,
            )
        )
        if not is_coupon and "importo" in part.columns:
            for _, event_row in part.iterrows():
                fig.add_annotation(
                    x=event_row["data"],
                    y=event_row["ticker"],
                    xref="x",
                    yref="y",
                    text=fmt_eur_it(event_row["importo"], 2),
                    showarrow=False,
                    xshift=18,
                    yshift=-14,
                    xanchor="left",
                    yanchor="middle",
                    font=dict(size=10, color=color),
                    bgcolor="rgba(255,255,255,0.88)",
                )
                fig.add_annotation(
                    x=event_row["data"],
                    y=event_row["ticker"],
                    xref="x",
                    yref="y",
                    text=f"{pd.to_datetime(event_row['data']):%d/%m/%Y}",
                    showarrow=False,
                    xshift=18,
                    yshift=12,
                    xanchor="left",
                    yanchor="bottom",
                    font=dict(size=10, color="#64748B"),
                    bgcolor="rgba(255,255,255,0.88)",
                )

    for ticker in tickers:
        fig.add_annotation(
            x=ticker_label_x,
            y=ticker,
            xref="x",
            yref="y",
            text=f"<span style='color:{gov_color}'>{ticker}</span>",
            showarrow=False,
            xshift=0,
            xanchor="right",
            yanchor="middle",
            font=dict(size=12, color=gov_color),
            align="right",
        )

    fig.add_shape(
        type="line",
        x0=today,
        x1=today,
        y0=0,
        y1=1,
        xref="x",
        yref="paper",
        line=dict(width=1.6, dash="dash", color="#64748B"),
    )
    fig.add_annotation(
        x=today,
        y=1,
        xref="x",
        yref="paper",
        text="Oggi",
        showarrow=False,
        yanchor="bottom",
        yshift=8,
        font=dict(size=11, color="#64748B"),
        bgcolor="rgba(255,255,255,0.85)",
    )

    fig = finalize_chart(fig, "btp_timeline", hovermode="closest", uirevision="btp-timeline")
    fig.update_layout(
        title_text="",
        showlegend=False,
        height=max(400, 118 + 72 * len(tickers)),
        margin=dict(l=0, r=32, t=34, b=104),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    fig.update_xaxes(
        title=None,
        tickformat="%d/%m/%y",
        tickangle=0,
        automargin=True,
        ticklabelmode="instant",
        rangeslider_visible=False,
    )
    fig = apply_settings(fig, "btp_timeline")
    fig.update_xaxes(
        rangeslider_visible=False,
        ticklabelmode="instant",
        automargin=True,
        range=[min_data - pd.Timedelta(days=70), max_data + pd.Timedelta(days=20)],
    )
    y_bottom_pad = get_chart_setting("btp_timeline", "y_bottom_padding", -0.5)
    fig.update_yaxes(
        title=None,
        categoryorder="array",
        categoryarray=tickers[::-1],
        showticklabels=False,
        range=[y_bottom_pad, len(tickers) - 0.5],
    )
    return fig


def render_btp_calendar_table(
    calendar_df: pd.DataFrame,
    theme: ThemeConfig | None = None,
    pmc_map: dict[str, float] | None = None,
) -> None:
    """Render the BTP legend + events table (non-cached: leggera).

    Ripete la stessa preparazione dati leggera di build_btp_calendar_figure
    (calendar_df è la tabella eventi BTP, piccola, non gli 823 giorni di
    storico: duplicarla è un costo trascurabile e mantiene le due funzioni
    autonome/testabili).
    """
    df = calendar_df.copy()
    midday = pd.Timedelta(hours=12)
    df["data"] = pd.to_datetime(df["data"], errors="coerce").dt.normalize() + midday
    df["data_inizio"] = pd.to_datetime(df.get("data_inizio"), errors="coerce").dt.normalize() + midday
    df["data_fine"] = pd.to_datetime(df.get("data_fine"), errors="coerce").dt.normalize() + midday
    df = df.dropna(subset=["data"]).sort_values(["ticker", "data"])
    if df.empty:
        return

    events = df[df["tipo_riga"] == "evento"].copy()

    def _strike_text(value: str) -> str:
        text = str(value or "")
        if not text:
            return text
        return "".join(ch + "̶" for ch in text)

    st.markdown(
        f"""
        <div style="display:flex;justify-content:center;gap:10px;flex-wrap:wrap;margin:6px 0 10px 0;">
          <span style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border:1px solid #e5e7eb;border-radius:999px;background:#f8fafc;font-size:0.78rem;color:#0F8A38;">
            <span style="width:18px;height:0;border-top:3px solid #0F8A38;display:inline-block;"></span> Trascorso
          </span>
          <span style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border:1px solid #e5e7eb;border-radius:999px;background:#f8fafc;font-size:0.78rem;color:#92400e;">
            <span style="width:18px;height:0;border-top:3px solid #F59E0B;display:inline-block;"></span> Residuo
          </span>
          <span style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border:1px solid #e5e7eb;border-radius:999px;background:#f8fafc;font-size:0.78rem;color:#166534;">
            <span style="width:10px;height:10px;border-radius:50%;background:{COLORS['success']};display:inline-block;"></span> Incassata
          </span>
          <span style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border:1px solid #e5e7eb;border-radius:999px;background:#f8fafc;font-size:0.78rem;color:#b91c1c;">
            <span style="width:10px;height:10px;border-radius:50%;background:{COLORS['danger']};display:inline-block;"></span> Futura
          </span>
          <span style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border:1px solid #e5e7eb;border-radius:999px;background:#f8fafc;font-size:0.78rem;color:#475569;">
            <span style="width:18px;height:0;border-top:2px dashed #64748B;display:inline-block;"></span> Oggi
          </span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    table_rows = events.copy()
    if table_rows.empty:
        return

    # Data come chiave di ordinamento primaria: la tabella si apre già
    # ordinata cronologicamente, non raggruppata per ticker.
    table_rows = table_rows.sort_values(["data", "ticker"], kind="stable").reset_index(drop=True)

    table_rows["Data"] = table_rows["data"].dt.strftime("%d/%m/%Y")
    table_rows["Evento"] = table_rows["tipo_evento"].map({"cedola": "Cedola", "scadenza": "Scadenza"})
    row_states = table_rows["stato_evento"].astype(str).reset_index(drop=True)

    # ── Calcola Lordo, Imposte, Netto per ogni riga ──────────────────────
    lordinata: list[float] = []
    imposte_list: list[float | None] = []
    netta: list[float] = []

    for _, row in table_rows.iterrows():
        tipo = str(row.get("tipo_evento") or "")
        importo = float(row.get("importo") or 0.0)
        _il = row.get("importo_lordo")
        importo_lordo = float(_il) if _il is not None and pd.notna(_il) else importo
        _ri = row.get("imposte")
        imposte_reali = float(_ri) if _ri is not None and pd.notna(_ri) else None

        if imposte_reali is not None:
            # Evento realmente registrato (build_btp_calendar l'ha gia'
            # riconciliato con registro_eventi): usa le imposte davvero
            # pagate, non una stima da aliquota fissa.
            lordo_v = importo_lordo
            netto_v = importo
            imp_v: float | None = imposte_reali
        elif tipo == "cedola":
            _il2 = row.get("importo_lordo")
            if _il2 is not None and pd.notna(_il2) and float(_il2) > importo * (1.0 + 1e-6):
                lordo_v = float(_il2)
            else:
                # importo_lordo assente/uguale al netto (cache stale): calcoliamo dal netto
                lordo_v = importo / (1.0 - _ALIQUOTA_BTP) if _ALIQUOTA_BTP < 1.0 else importo
            netto_v = importo
            imp_v = lordo_v - netto_v
        elif tipo == "scadenza":
            lordo_v = importo_lordo
            ticker = str(row.get("ticker") or "")
            pmc = pmc_map.get(ticker) if pmc_map else None
            imp_v = _stima_imposte_scadenza(lordo_v, pmc)
            netto_v = lordo_v - imp_v if imp_v is not None else lordo_v
        else:
            lordo_v = importo_lordo
            imp_v = None
            netto_v = importo

        lordinata.append(lordo_v)
        imposte_list.append(imp_v)
        netta.append(netto_v)

    table_rows["_lordo"] = lordinata
    table_rows["_imposte"] = imposte_list
    table_rows["_netto"] = netta

    # ── Mantieni i valori monetari come float (uguale alla tabella GOV yield
    #    sulla stessa pagina): Streamlit right-allinea automaticamente i float.
    #    Imposte=None → NaN, formattato come "—" dal format(). ────────────────
    import math as _math

    tot_lordo = float(table_rows["_lordo"].sum())
    imp_nonnull = [v for v in imposte_list if v is not None]
    tot_imposte_v = sum(imp_nonnull) if imp_nonnull else float("nan")
    tot_netto = float(table_rows["_netto"].sum())

    display_df = (
        table_rows[["ticker", "Data", "Evento", "_lordo", "_imposte", "_netto"]]
        .rename(columns={"ticker": "Ticker", "_lordo": "Lordo", "_imposte": "Imposte", "_netto": "Netto"})
        .reset_index(drop=True)
    )
    # Converti None → NaN nella colonna Imposte per mantenere dtype float
    display_df["Imposte"] = pd.to_numeric(display_df["Imposte"], errors="coerce")

    def _row_style(row: pd.Series) -> list[str]:
        idx = row.name
        is_incassata = idx < len(row_states) and row_states.iloc[idx] == "incassata"
        styles: list[str] = []
        for _ in row.index:
            if is_incassata:
                styles.append("color:#DC2626;text-decoration:line-through;")
            else:
                styles.append("")
        return styles

    # Applica strikethrough al testo sulle colonne stringa (Ticker, Data, Evento)
    incassata_indices = [i for i, s in enumerate(row_states) if s == "incassata"]
    for col in ["Ticker", "Data", "Evento"]:
        display_df.loc[incassata_indices, col] = display_df.loc[incassata_indices, col].map(_strike_text)

    def _fmt_money(v: object) -> str:
        if v is None or (isinstance(v, float) and _math.isnan(v)):
            return "—"
        return fmt_eur_it(float(v), 2)

    def _fmt_money_strike(v: object) -> str:
        return _strike_text(_fmt_money(v))

    # Stesso pattern della tabella "Yield prospettico GOV" sulla stessa pagina:
    # .style.format() lascia il dtype float → Streamlit right-allinea da solo.
    styler = (
        display_df.style
        .hide(axis="index")
        .apply(_row_style, axis=1)
        .format({"Lordo": _fmt_money, "Imposte": _fmt_money, "Netto": _fmt_money})
    )
    if incassata_indices:
        styler = styler.format(
            _fmt_money_strike,
            subset=pd.IndexSlice[incassata_indices, ["Lordo", "Imposte", "Netto"]],
        )
    # Larghezze esplicite e condivise con la riga Totale qui sotto: st.dataframe
    # e st.table calcolano la larghezza delle colonne con motori di rendering
    # diversi (canvas vs HTML) e non combaciano mai se lasciati "auto".
    column_widths = {
        "Ticker": 90, "Data": 110, "Evento": 100,
        "Lordo": 130, "Imposte": 130, "Netto": 130,
    }
    column_config = {
        col: st.column_config.Column(width=width) for col, width in column_widths.items()
    }
    render_styled_table(styler, height="content", column_config=column_config)

    # ── Totale come riga fissa e non ordinabile, separata dalla tabella
    #    eventi: st.dataframe riordina l'intero corpo dati al click
    #    sull'intestazione, quindi una riga di totale inclusa nella stessa
    #    tabella si sposterebbe insieme alle altre. Resa anch'essa con
    #    st.dataframe (stesso motore, stesse larghezze) così le colonne
    #    restano allineate; con una sola riga non c'è nulla da riordinare.
    totale_df = pd.DataFrame([{
        "Ticker": "Totale", "Data": "", "Evento": "",
        "Lordo": tot_lordo, "Imposte": tot_imposte_v, "Netto": tot_netto,
    }])
    totale_styler = (
        totale_df.style
        .hide(axis="index")
        .set_properties(**{"font-weight": "700"})
        .format({"Lordo": _fmt_money, "Imposte": _fmt_money, "Netto": _fmt_money})
    )
    totale_column_config = {
        col: st.column_config.Column(label=" ", width=width)
        for col, width in column_widths.items()
    }
    render_styled_table(totale_styler, height="content", column_config=totale_column_config)


def render_btp_calendar(
    calendar_df: pd.DataFrame,
    theme: ThemeConfig | None = None,
    pmc_map: dict[str, float] | None = None,
) -> None:
    """Render BTP timeline with possession span, coupons and maturity.

    Thin wrapper mantenuto per non rompere l'import in ui/pages/operazioni.py
    (presente ma mai chiamato lì). Il chiamante che vuole la cache sulla
    figura (ui/pages/cruscotti.py) usa direttamente build_btp_calendar_figure
    dentro fcache.get_or_build, seguito da render_btp_calendar_table.
    """
    if calendar_df is None or calendar_df.empty:
        return
    fig = build_btp_calendar_figure(calendar_df, theme, pmc_map=pmc_map)
    st.plotly_chart(fig, width="stretch")
    render_btp_calendar_table(calendar_df, theme, pmc_map=pmc_map)
