"""
ui/pages/overview.py — Above-tabs section: P/L chart + KPI cards
Pure rendering. Receives pre-computed ctx from orchestrator.
"""
from types import SimpleNamespace

import pandas as pd
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from ui.formatting import fmt_eur_it, fmt_pct_it
from ui.components import kpi_card, kpi_triplet_card
from ui.charts.overview import build_overview_time_chart
from ui.theme import P, get_theme_context
from ui.charts.settings import apply_settings


def render_overview(container: DeltaGenerator, ctx: SimpleNamespace) -> None:
    """Render above-tabs section (constant during tab navigation).

    Contains: P/L del portafoglio chart + KPI cards (2 rows).
    """
    with container:
        dfh_top = ctx.dfh_top
        da = ctx.da
        tv = ctx.tv
        tc = ctx.tc
        data = ctx.data
        pl_color = ctx.pl_color
        pl_totale = ctx.pl_totale
        pp = ctx.pp
        cap = ctx.cap
        capitale_versato_residuo = ctx.capitale_versato_residuo
        capitale_rientrato = ctx.capitale_rientrato
        proventi_netti_totali = ctx.proventi_netti_totali
        liquidita_attuale = ctx.liquidita_attuale
        total_return = ctx.total_return
        total_return_pct = ctx.total_return_pct
        total_return_color = ctx.total_return_color
        dfmt = ctx.dfmt
        CHART_BG = ctx.CHART_BG
        P_dict = P
        settings = getattr(ctx, "settings", {}) if hasattr(ctx, "settings") else {}

        if not dfh_top.empty and len(dfh_top) > 1:
            fig = build_overview_time_chart(dfh_top, da, "P/L del portafoglio", pl_color, pl_totale, CHART_BG, dfmt, get_theme_context(), settings=settings, total_return=total_return)
            latest_chart_date = ""
            latest_chart_value = 0.0
            if getattr(fig, "data", None):
                first_trace = fig.data[0]
                trace_x = getattr(first_trace, "x", None)
                trace_y = getattr(first_trace, "y", None)
                if trace_x is not None and len(trace_x) > 0:
                    latest_chart_date = str(list(trace_x)[-1])
                if trace_y is not None and len(trace_y) > 0:
                    try:
                        latest_chart_value = float(list(trace_y)[-1])
                    except Exception:
                        latest_chart_value = 0.0

            apply_settings(fig, "overview_pl_portafoglio")
            overview_chart_key = f"overview-chart|{latest_chart_date}|{round(latest_chart_value, 2)}"
            st.plotly_chart(fig, width="stretch", key=overview_chart_key)
        else:
            st.info("📌 Aggiorna le quotazioni per visualizzare l'andamento storico del P/L in home page.")

        triplet_items = getattr(ctx, "category_triplet_items", [])

        pl_attuale_posizioni = tv - tc
        pl_attuale_color = P_dict["green"] if pl_attuale_posizioni >= 0 else P_dict["red"]
        _formula_style = "display:block;margin-top:4px;font-size:inherit;line-height:inherit;opacity:0.92;"
        capitale_sub = (
            f"di cui capitale rientrato:<br>{fmt_eur_it(capitale_rientrato, 2)}"
            f"<span style='{_formula_style}'>versamenti - prelievi</span>"
        )
        valore_attuale_sub = (
            f"<span style='{_formula_style};margin-top:0'>quote residue × prezzo attuale</span>"
        )
        pl_attuale_sub = (
            "risultato sulle posizioni aperte ai prezzi correnti"
            f"<span style='{_formula_style}'>valore attuale - costo residuo</span>"
        )
        proventi_sub = (
            f"<span style='{_formula_style};margin-top:0'>cedole nette + dividendi netti</span>"
        )
        liquidita_sub = (
            f"<span style='{_formula_style};margin-top:0'>flussi netti di cassa</span>"
        )
        pl_storico_sub = (
            f"<span style='{_formula_style}'>valore attuale − costo residuo + realizzi vendite/rimborsi</span>"
        )
        total_return_sub = (
            f"<span style='{_formula_style};margin-top:0'>P/L storico + proventi netti</span>"
        )
        c1, c2, c3, c4 = st.columns([1.0, 1.08, 1.1, 2.25])
        with c1:
            kpi_card(
                "P/L Pos. Aperte <span title=\"Risultato delle sole posizioni aperte ai prezzi correnti.\" style=\"cursor:help; font-size:0.82em; opacity:0.8;\">ⓘ</span>",
                f"{fmt_eur_it(pl_attuale_posizioni, 2, signed=True)}<br><span style='font-size:1rem;font-weight:800'>{fmt_pct_it((pl_attuale_posizioni/abs(tc)) if abs(tc)>1e-9 else 0, 2, signed=True)}</span>",
                pl_attuale_sub,
                accent=P_dict["blue"],
                value_color=P_dict["blue"]
            )
        with c2:
            kpi_card(
                "P/L Storico <span title=\"Somma del P/L aperto e del realizzato netto gia' maturato.\" style=\"cursor:help; font-size:0.82em; opacity:0.8;\">ⓘ</span>",
                f"{fmt_eur_it(pl_totale, 2, signed=True)}<br><span style='font-size:1rem;font-weight:800'>{fmt_pct_it(pp, 2, signed=True)}</span>",
                pl_storico_sub,
                accent=pl_color,
                value_color=pl_color
            )
        with c3:
            kpi_card(
                "Total Return <span title=\"Risultato complessivo: P/L storico piu' proventi netti incassati.\" style=\"cursor:help; font-size:0.82em; opacity:0.8;\">ⓘ</span>",
                f"{fmt_eur_it(total_return, 2, signed=True)}<br><span style='font-size:1rem;font-weight:800'>{fmt_pct_it(total_return_pct, 2, signed=True)}</span>",
                total_return_sub,
                accent=P_dict["orange"],
                value_color=P_dict["orange"]
            )
        with c4:
            if triplet_items:
                kpi_triplet_card("Valore Attuale per Categoria", triplet_items, accent=P_dict["orange"])
            else:
                kpi_card("Valore Attuale per Categoria", "—", "Nessuna posizione aperta", accent=P_dict["orange"])

        st.markdown("<br>", unsafe_allow_html=True)
        pk1, pk2, pk3, pk4, pk5 = st.columns(5)
        with pk1:
            kpi_card(
                "Capitale Versato<br>Storico",
                fmt_eur_it(cap, 2),
                capitale_sub,
                accent=P_dict["gray"],
                value_color=P_dict["gray"]
            )
        with pk2:
            capitale_versato_residuo_sub = (
                f"<span style='{_formula_style}'>capitale versato − capitale rientrato</span>"
            )
            kpi_card(
                "Capitale Versato<br>Residuo",
                fmt_eur_it(capitale_versato_residuo, 2),
                "quota di capitale ancora investita nelle posizioni aperte" + capitale_versato_residuo_sub,
                accent=P_dict["gray"],
                value_color=P_dict["gray"]
            )
        with pk3:
            kpi_card(
                "Controvalore<br>Attuale",
                fmt_eur_it(tv, 2),
                valore_attuale_sub,
                accent=P_dict["blue"],
                value_color=P_dict["blue"]
            )
        with pk4:
            kpi_card(
                "Proventi<br>Netti",
                fmt_eur_it(proventi_netti_totali, 2),
                proventi_sub,
                accent=P_dict["green"],
                value_color=P_dict["green"]
            )
        with pk5:
            kpi_card(
                "Liquidità<br>Disponibile",
                fmt_eur_it(liquidita_attuale, 2),
                liquidita_sub,
                accent=P_dict["blue"],
                value_color=P_dict["blue"]
            )
