"""
ui/pages/overview.py — Above-tabs section: graph selector + KPI cards
Pure rendering. Receives pre-computed ctx from orchestrator.
"""
from types import SimpleNamespace

import pandas as pd
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from core.asset_categories import get_selected_category_codes
from core.settings_profiles import get_alerts_settings
from ui.formatting import fmt_eur_it, fmt_pct_it
from ui.components import kpi_card, kpi_triplet_card
from ui.charts.overview import build_overview_time_chart
from ui.theme import P, get_theme_context
from ui.charts.settings import apply_settings


def render_overview(container: DeltaGenerator, ctx: SimpleNamespace) -> None:
    """Render above-tabs section (constant during tab navigation).

    Contains: graph selector (3 modes) + dynamic plotly graphs + KPI cards (2 rows).
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
        capitale_rientrato = ctx.capitale_rientrato
        proventi_netti_totali = ctx.proventi_netti_totali
        liquidita_attuale = ctx.liquidita_attuale
        total_return = ctx.total_return
        total_return_pct = ctx.total_return_pct
        total_return_color = ctx.total_return_color
        dfmt = ctx.dfmt
        CHART_BG = ctx.CHART_BG
        P_dict = P
        portfolio_alerts = getattr(ctx, "portfolio_alerts", [])
        settings = getattr(ctx, "settings", {}) if hasattr(ctx, "settings") else {}
        alerts_settings = get_alerts_settings(settings)
        visible_categories = list(get_selected_category_codes(settings))
        categories_text = ", ".join(visible_categories)
        overview_default_chart = "P/L del portafoglio"

        if not dfh_top.empty and len(dfh_top) > 1:
            if "home_chart_vista" not in st.session_state or st.session_state.get("home_chart_vista") not in ["P/L del portafoglio", "P/L per Categoria"]:
                st.session_state["home_chart_vista"] = overview_default_chart if overview_default_chart in ["P/L del portafoglio", "P/L per Categoria"] else "P/L del portafoglio"
            _c_radio, _c_help = st.columns([12, 1])
            with _c_radio:
                _home_vista = st.radio(
                    "Vista grafico",
                    ["P/L del portafoglio", "P/L per Categoria"],
                    horizontal=True,
                    key="home_chart_vista",
                    label_visibility="collapsed",
                )
            with _c_help:
                st.markdown(
                    f'<div style="padding-top:6px"><span title="P/L del portafoglio: guadagno/perdita complessivo nel tempo. P/L per Categoria: andamento P/L delle categorie visibili ({categories_text}) separatamente." style="cursor:help;font-size:0.9rem;color:#9CA3AF;border:1px solid #9CA3AF;border-radius:50%;padding:0 3px;display:inline-block;line-height:1.3;">?</span></div>',
                    unsafe_allow_html=True,
                )
            fig = build_overview_time_chart(dfh_top, da, _home_vista, pl_color, pl_totale, CHART_BG, dfmt, get_theme_context(), settings=settings)
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

            # Mappa la view_mode al chart_id corrispondente
            _overview_chart_ids = {
                "P/L del portafoglio": "overview_pl_portafoglio",
                "P/L per Categoria":   "overview_pl_categoria",
            }
            apply_settings(fig, _overview_chart_ids.get(_home_vista, "overview_pl_portafoglio"))
            overview_chart_key = f"overview-chart|{_home_vista}|{latest_chart_date}|{round(latest_chart_value, 2)}"
            st.plotly_chart(fig, width="stretch", key=overview_chart_key)
        else:
            st.info("📌 Aggiorna le quotazioni per visualizzare l'andamento storico del P/L in home page.")

        if bool(alerts_settings.get("enabled", False)) and bool(alerts_settings.get("show_overview", True)) and portfolio_alerts:
            max_items = max(1, int(alerts_settings.get("max_items", 3) or 3))
            severity_icon = {"high": "🔴", "medium": "🟠", "low": "🔵"}
            lines = [
                f"- {severity_icon.get(str(item.get('severity')), '•')} **{item.get('title', 'Alert')}**: {item.get('message', '')}"
                for item in portfolio_alerts[:max_items]
            ]
            st.warning("**Avvisi attivi sul portafoglio**\n" + "\n".join(lines))

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
                "Capitale Versato<br>Storico",
                fmt_eur_it(cap, 2),
                capitale_sub,
                accent=P_dict["gray"],
                value_color=P_dict["gray"]
            )
        with c2:
            kpi_card(
                "Valore Investito<br>Attuale",
                fmt_eur_it(tv, 2),
                valore_attuale_sub,
                accent=P_dict["blue"],
                value_color=P_dict["blue"]
            )
        with c3:
            kpi_card(
                "P/L Attuale <span title=\"Risultato delle sole posizioni aperte ai prezzi correnti.\" style=\"cursor:help; font-size:0.82em; opacity:0.8;\">ⓘ</span>",
                f"{fmt_eur_it(pl_attuale_posizioni, 2, signed=True)}<br><span style='font-weight:800'>{fmt_pct_it((pl_attuale_posizioni/abs(tc)) if abs(tc)>1e-9 else 0, 2, signed=True)}</span>",
                pl_attuale_sub,
                accent=pl_attuale_color,
                value_color=pl_attuale_color
            )
        with c4:
            if triplet_items:
                kpi_triplet_card("Valore Attuale per Categoria", triplet_items, accent=P_dict["orange"])
            else:
                kpi_card("Valore Attuale per Categoria", "—", "Nessuna posizione aperta", accent=P_dict["orange"])

        st.markdown("<br>", unsafe_allow_html=True)
        pk1, pk2, pk3, pk4 = st.columns(4)
        with pk1:
            kpi_card(
                "Proventi Netti",
                fmt_eur_it(proventi_netti_totali, 2),
                proventi_sub,
                accent=P_dict["green"],
                value_color=P_dict["green"]
            )
        with pk2:
            kpi_card(
                "Liquidità Disponibile",
                fmt_eur_it(liquidita_attuale, 2),
                liquidita_sub,
                accent=P_dict["blue"],
                value_color=P_dict["blue"]
            )
        with pk3:
            kpi_card(
                "P/L Storico <span title=\"Somma del P/L aperto e del realizzato netto gia' maturato.\" style=\"cursor:help; font-size:0.82em; opacity:0.8;\">ⓘ</span>",
                f"{fmt_eur_it(pl_totale, 2, signed=True)}<br><span style='font-weight:800'>{fmt_pct_it(pp, 2, signed=True)}</span>",
                pl_storico_sub,
                accent=pl_color,
                value_color=pl_color
            )
        with pk4:
            kpi_card(
                "Total Return <span title=\"Risultato complessivo: P/L storico piu' proventi netti incassati.\" style=\"cursor:help; font-size:0.82em; opacity:0.8;\">ⓘ</span>",
                f"{fmt_eur_it(total_return, 2, signed=True)}<br><span style='font-size:1rem;font-weight:800'>{fmt_pct_it(total_return_pct, 2, signed=True)}</span>",
                total_return_sub,
                accent=total_return_color,
                value_color=total_return_color
            )
