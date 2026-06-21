"""BTP timeline visualization."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ui.charts.runtime import finalize_chart
from ui.charts.settings import apply_settings
from ui.formatting import fmt_eur_it
from ui.theme import ThemeConfig
from ui.theme import macro_color


_ALIQUOTA_BTP = 0.125


def _stima_imposte_scadenza(lordo: float, pmc: float | None) -> float | None:
    """Stima l'imposta sulla plusvalenza a rimborso per un BTP.

    Restituisce None se PMC non disponibile (la cella mostrerà '—').
    """
    # Formula valida per BTP con nominale=100: gain_frac = (100-PMC)/100, lordo = nominale*quantita
    if pmc is None:
        return None
    gain_frac = max(0.0, (100.0 - pmc) / 100.0)
    return lordo * gain_frac * _ALIQUOTA_BTP


def render_btp_calendar(
    calendar_df: pd.DataFrame,
    theme: ThemeConfig | None = None,
    pmc_map: dict[str, float] | None = None,
) -> None:
    """Render BTP timeline with possession span, coupons and maturity."""
    if calendar_df is None or calendar_df.empty:
        return

    df = calendar_df.copy()
    midday = pd.Timedelta(hours=12)
    df["data"] = pd.to_datetime(df["data"], errors="coerce").dt.normalize() + midday
    df["data_inizio"] = pd.to_datetime(df.get("data_inizio"), errors="coerce").dt.normalize() + midday
    df["data_fine"] = pd.to_datetime(df.get("data_fine"), errors="coerce").dt.normalize() + midday
    df = df.dropna(subset=["data"]).sort_values(["ticker", "data"])
    if df.empty:
        return

    tickers = list(df["ticker"].dropna().astype(str).drop_duplicates())
    min_data = df["data"].min()
    max_data = df["data"].max()
    ticker_label_x = min_data - pd.Timedelta(days=40)
    past_line_color = "#0F8A38"
    future_line_color = "#F59E0B"
    elapsed_text_color = "#0F8A38"
    gov_color = macro_color("GOV")
    colors = {
        ("cedola", "incassata"): "#1E8449",
        ("cedola", "futura"): "#FF4B4B",
        ("scadenza", "incassata"): "#1E8449",
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

    def _strike_text(value: str) -> str:
        text = str(value or "")
        if not text:
            return text
        return "".join(ch + "\u0336" for ch in text)

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
    fig.update_yaxes(
        title=None,
        categoryorder="array",
        categoryarray=tickers[::-1],
        showticklabels=False,
    )
    st.plotly_chart(fig, width="stretch")

    st.markdown(
        """
        <div style="display:flex;justify-content:center;gap:10px;flex-wrap:wrap;margin:6px 0 10px 0;">
          <span style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border:1px solid #e5e7eb;border-radius:999px;background:#f8fafc;font-size:0.78rem;color:#0F8A38;">
            <span style="width:18px;height:0;border-top:3px solid #0F8A38;display:inline-block;"></span> Trascorso
          </span>
          <span style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border:1px solid #e5e7eb;border-radius:999px;background:#f8fafc;font-size:0.78rem;color:#92400e;">
            <span style="width:18px;height:0;border-top:3px solid #F59E0B;display:inline-block;"></span> Residuo
          </span>
          <span style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border:1px solid #e5e7eb;border-radius:999px;background:#f8fafc;font-size:0.78rem;color:#166534;">
            <span style="width:10px;height:10px;border-radius:50%;background:#1E8449;display:inline-block;"></span> Incassata
          </span>
          <span style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border:1px solid #e5e7eb;border-radius:999px;background:#f8fafc;font-size:0.78rem;color:#b91c1c;">
            <span style="width:10px;height:10px;border-radius:50%;background:#FF4B4B;display:inline-block;"></span> Futura
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

        if tipo == "cedola":
            _il2 = row.get("importo_lordo")
            if _il2 is not None and pd.notna(_il2) and float(_il2) > importo * (1.0 + 1e-6):
                lordo_v = float(_il2)
            else:
                # importo_lordo assente/uguale al netto (cache stale): calcoliamo dal netto
                lordo_v = importo / (1.0 - _ALIQUOTA_BTP) if _ALIQUOTA_BTP < 1.0 else importo
            netto_v = importo
            imp_v: float | None = lordo_v - netto_v
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

    def _fmt_imp(v: float | None) -> str:
        return fmt_eur_it(v, 2) if v is not None else "—"

    table_rows["Lordo"] = table_rows["_lordo"].map(lambda v: fmt_eur_it(v, 2))
    table_rows["Imposte"] = table_rows["_imposte"].map(_fmt_imp)
    table_rows["Netto"] = table_rows["_netto"].map(lambda v: fmt_eur_it(v, 2))

    display_df = (
        table_rows[["ticker", "Data", "Evento", "Lordo", "Imposte", "Netto"]]
        .rename(columns={"ticker": "Ticker"})
        .reset_index(drop=True)
    )

    # ── Riga Totale ───────────────────────────────────────────────────────
    tot_lordo = float(table_rows["_lordo"].sum())
    # Somma imposte solo dove disponibile (non None)
    imp_nonnull = [v for v in imposte_list if v is not None]
    tot_imposte: float | None = sum(imp_nonnull) if imp_nonnull else None
    tot_netto = float(table_rows["_netto"].sum())
    totale_row = pd.DataFrame([{
        "Ticker": "Totale",
        "Data": "",
        "Evento": "",
        "Lordo": fmt_eur_it(tot_lordo, 2),
        "Imposte": _fmt_imp(tot_imposte),
        "Netto": fmt_eur_it(tot_netto, 2),
    }])
    display_df = pd.concat([display_df, totale_row], ignore_index=True)

    # ── Render HTML diretto (pandas Styler/st.dataframe ignorano text-align) ──
    n_orig = len(row_states)
    cols = ["Ticker", "Data", "Evento", "Lordo", "Imposte", "Netto"]
    right_cols = {"Lordo", "Imposte", "Netto"}

    TH = (
        "padding:7px 10px;font-size:0.80rem;font-weight:700;text-transform:uppercase;"
        "letter-spacing:.04em;color:#64748b;border-bottom:2px solid #e2e8f0;"
        "background:#f8fafc;white-space:nowrap;"
    )
    TD = "padding:7px 10px;font-size:0.88rem;border-bottom:1px solid #f0f4f8;"

    html_parts = [
        '<div style="overflow-x:auto;margin:6px 0 2px 0;">',
        '<table style="width:100%;border-collapse:collapse;font-family:inherit;">',
        "<thead><tr>",
    ]
    for col in cols:
        align = "right" if col in right_cols else "left"
        html_parts.append(f'<th style="{TH}text-align:{align};">{col}</th>')
    html_parts.append("</tr></thead><tbody>")

    for i, (_, row) in enumerate(display_df.iterrows()):
        is_totale = i == n_orig
        is_incassata = not is_totale and i < n_orig and row_states.iloc[i] == "incassata"
        html_parts.append("<tr>")
        for col in cols:
            val = str(row[col]) if row[col] is not None else "—"
            align = "right" if col in right_cols else "left"
            td_style = f"{TD}text-align:{align};"
            if is_totale:
                td_style += "font-weight:700;border-top:2px solid #e2e8f0;border-bottom:none;"
            elif is_incassata:
                td_style += "color:#DC2626;text-decoration:line-through;"
            html_parts.append(f'<td style="{td_style}">{val}</td>')
        html_parts.append("</tr>")

    html_parts.append("</tbody></table></div>")
    st.markdown("".join(html_parts), unsafe_allow_html=True)
