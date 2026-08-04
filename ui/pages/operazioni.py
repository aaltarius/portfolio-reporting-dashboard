"""
ui/pages/operazioni.py — Tab Operazioni: event log and transaction registry
Pure rendering with pre-filtered service data.
"""
from types import SimpleNamespace
from typing import Any

import pandas as pd
import streamlit as st

from streamlit.delta_generator import DeltaGenerator

from persistence.storage import (
    macro_cat,
    get_registro_eventi,
)
from core.domain.calendar import TAX_RATE_GOV_PCT, TAX_RATE_OTHER_PCT
from core.services import (
    get_portfolio_operations,
    get_cash_movements,
    build_monthly_purchase_spending,
)
from ui.formatting import (
    fmt_eur_it, fmt_qty_it, fmtds,
)
from ui.components import (
    macro_color, back_to_top,
    render_styled_table,
    render_section_title, should_render_section,
)
from ui.charts.operazioni import (
    build_monthly_purchase_spending_time_chart,
    build_purchase_installments_chart,
)
from ui.charts.calendario_btp import render_btp_calendar
from ui.charts.settings import apply_settings
from ui.i18n import t
from ui.theme import get_theme_context
from ui.page_chrome import render_page_intro as render_page_intro_shared

def _default_tax_rate_pct(evento: str, ticker: str, info_map: dict[str, dict[str, Any]]) -> float:
    if evento != "CEDOLA":
        return TAX_RATE_OTHER_PCT
    instrument_type = info_map.get(ticker, {}).get("tipo", "")
    return TAX_RATE_GOV_PCT if macro_cat(instrument_type) == "GOV" else TAX_RATE_OTHER_PCT


def render_operazioni(tab: DeltaGenerator, ctx: SimpleNamespace) -> None:
    """
    Pure rendering for operazioni page (transaction log).
    All filtering is done by service functions.
    """
    data = ctx.data
    fmtds = ctx.fmtds
    settings = getattr(ctx, "settings", {}) if hasattr(ctx, "settings") else {}
    theme = get_theme_context()

    with tab:
        render_page_intro_shared(
            t(settings, "tab.operations", "Operazioni"),
            t(settings, "page_intro.operazioni.comment", "Registro consultivo degli eventi di portafoglio e dei movimenti di cassa. Le azioni operative si aprono dalla sidebar."),
            "operations",
            theme,
        )

        operations = get_portfolio_operations(get_registro_eventi(data))

        # ─── Operazioni di portafoglio ──────────────────────────────
        render_section_title(
            t(settings, 'operations.portfolio_title', 'Registro operazioni di portafoglio'),
            comment=t(settings, "operations.portfolio_note", "Operazioni che incidono sulle posizioni del portafoglio: acquisti, vendite e rimborsi a scadenza."),
            gap_after="xs",
        )

        if operations:
            info_map = {s["ticker"]: s for s in data.get("strumenti", [])}
            dfp = pd.DataFrame(operations)

            # Build display columns
            dfp["Data"] = dfp["data"].apply(fmtds)
            dfp["Evento"] = dfp["tipo_evento"]
            dfp["Ticker"] = dfp["ticker"]
            dfp["Strumento"] = dfp["ticker"].map(
                lambda tk: (lambda n: n[:24] + "…" if len(n) > 24 else n)(
                    info_map.get(tk, {}).get("nome", tk)
                )
            )
            dfp["Tipo"] = dfp["ticker"].map(
                lambda tk: macro_cat(info_map.get(tk, {}).get("tipo", ""))
            ).fillna("")
            dfp["Qtà"] = pd.to_numeric(dfp.get("quantita", 0), errors="coerce")
            dfp["Prezzo €"] = pd.to_numeric(dfp.get("prezzo_unitario", 0), errors="coerce")
            dfp["Comm. €"] = pd.to_numeric(dfp.get("commissioni", 0), errors="coerce")
            dfp["Imposte €"] = pd.to_numeric(dfp.get("imposte", 0), errors="coerce")
            dfp["Netto €"] = pd.to_numeric(dfp.get("importo_netto", 0), errors="coerce")

            out = dfp[["Data", "Evento", "Ticker", "Strumento", "Tipo", "Qtà", "Prezzo €", "Comm. €", "Imposte €", "Netto €"]].copy()

            def _style_port(row):
                ev_color = {
                    "ACQUISTO": theme.color_green,
                    "VENDITA": theme.color_red,
                    "RIMBORSO A SCADENZA": theme.color_purple,
                }.get(str(row["Evento"]), theme.color_gray)
                cls_color = macro_color(row["Tipo"]) if row.get("Tipo") else None
                styles = []
                for col in row.index:
                    s = ""
                    if col == "Evento":
                        s += f"color:{ev_color};font-weight:700;"
                    if col in {"Ticker", "Tipo"} and cls_color:
                        s += f"color:{cls_color};font-weight:700;"
                    if col == "Strumento":
                        s += "font-weight:600;"
                    styles.append(s)
                return styles

            styled_port = out.style.format({
                "Qtà": lambda v: fmt_qty_it(v, 4),
                "Prezzo €": lambda v: fmt_eur_it(v, 4),
                "Comm. €": lambda v: fmt_eur_it(v, 2),
                "Imposte €": lambda v: fmt_eur_it(v, 2),
                "Netto €": lambda v: fmt_eur_it(v, 2, signed=True),
            }).apply(_style_port, axis=1)
            render_styled_table(styled_port, height=520)
        else:
            st.info(t(settings, "operations.portfolio_empty", "Nessuna operazione di portafoglio registrata."))

        # ─── Movimenti di liquidità ────────────────────────────────
        render_section_title(
            t(settings, 'operations.cash_title', 'Registro movimenti di liquidità'),
            comment=t(settings, "operations.cash_note", "Movimenti che incidono sulla cassa del portafoglio: versamenti, prelievi, vendite/rimborsi (entrate), acquisti (uscite), cedole, dividendi, commissioni e imposte."),
            gap_after="xs",
        )

        # Get pre-filtered cash movements from service
        cash_movements = get_cash_movements(get_registro_eventi(data))

        if cash_movements:
            info_map = {s["ticker"]: s for s in data.get("strumenti", [])}
            dfc = pd.DataFrame(cash_movements)

            # Build display columns
            dfc["Data"] = dfc["data"].apply(fmtds)
            dfc["Causale"] = dfc["tipo_evento"]
            dfc["Ticker"] = dfc["ticker"].fillna("")
            dfc["Strumento"] = dfc["ticker"].map(
                lambda tk: info_map.get(tk, {}).get("nome", tk) if tk else ""
            )
            dfc["Riferimento"] = dfc.apply(
                lambda r: (
                    f"{r['Ticker']} — {r['Strumento']}"
                    if str(r.get("Ticker", "")).strip() and str(r.get("Strumento", "")).strip()
                    else (str(r.get("Ticker", "")).strip() or str(r.get("Strumento", "")).strip() or "—")
                ),
                axis=1,
            )
            dfc["Lordo"] = pd.to_numeric(dfc.get("importo_lordo", 0), errors="coerce")
            dfc["Imposte"] = pd.to_numeric(dfc.get("imposte", 0), errors="coerce")
            dfc["Netto cassa"] = pd.to_numeric(dfc.get("importo_netto", 0), errors="coerce")
            dfc["Note"] = dfc.get("note", "")

            outc = dfc[["Data", "Causale", "Riferimento", "Lordo", "Imposte", "Netto cassa", "Note"]].copy()

            def _style_cash(row):
                ev_color = {
                    "VERSAMENTO": theme.color_green,
                    "PRELIEVO": theme.color_red,
                    "CEDOLA": theme.color_purple,
                    "DIVIDENDO": theme.color_yellow,
                    "COMMISSIONE": theme.color_gray,
                    "IMPOSTA": theme.color_gray,
                    "VENDITA": theme.color_blue,
                    "RIMBORSO A SCADENZA": theme.color_orange,
                    "ACQUISTO": theme.color_orange,
                }.get(str(row["Causale"]), theme.color_gray)
                styles = []
                for col in row.index:
                    s = ""
                    if col == "Causale":
                        s += f"color:{ev_color};font-weight:700;"
                    if col == "Riferimento" and str(row.get("Riferimento", "")).strip() not in {"", "—"}:
                        s += "font-weight:600;"
                    styles.append(s)
                return styles

            styled_cash = outc.style.format({
                "Lordo": lambda v: fmt_eur_it(v, 2),
                "Imposte": lambda v: fmt_eur_it(v, 2),
                "Netto cassa": lambda v: fmt_eur_it(v, 2, signed=True),
            }).apply(_style_cash, axis=1)
            render_styled_table(styled_cash, height=520)
        else:
            st.info(t(settings, "operations.cash_empty", "Nessun movimento di liquidità registrato."))

        back_to_top(show_prev=True, show_next=True, nav_key="operazioni")
