"""
ui/pages/operazioni.py — Tab Operazioni: sintesi e cronologia degli eventi di portafoglio.
Pure rendering: i dati arrivano dai servizi (`core/services/operations_ledger.py`); filtri e
dettagli girano nel browser (`ui/pages/operazioni_timeline.py`), senza rerun.
"""
from types import SimpleNamespace

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from core.render_profiler import profile_step
from core.services.operations_ledger import build_operations_ledger, build_operations_summary
from persistence.storage import get_registro_eventi
from ui.components import back_to_top, kpi_card, render_section_title, vertical_gap
from ui.formatting import fmt_eur_it
from ui.i18n import t
from ui.page_chrome import render_page_intro as render_page_intro_shared
from ui.pages.operazioni_timeline import build_timeline_html
from ui.streamlit_compat import render_html_iframe
from ui.theme import get_theme_context, macro_color

TIMELINE_HEIGHT = 780


def _timeline_colors(theme) -> dict[str, str]:
    return {
        "surface": theme.bg_surface,
        "surface2": theme.colors.get("bg_surface_alt", theme.bg_surface),
        "text": theme.font_color,
        "muted": theme.muted_color,
        "border": theme.border_color,
        "primary": theme.primary_color,
        "font": theme.colors.get("font_family", "system-ui, -apple-system, sans-serif"),
        # stessa assegnazione colori delle vecchie tabelle (acquisto verde, vendita rosso, rimborso viola)
        "acquisto": theme.color_green,
        "vendita": theme.color_red,
        "rimborso": theme.color_purple,
        "cedola": theme.color_blue,
        "dividendo": theme.color_yellow,
        "versamento": theme.color_orange,
        "prelievo": theme.color_orange,
        "costo": theme.color_gray,
        "pos": theme.color_green,
        "neg": theme.color_red,
    }


def render_operazioni(tab: DeltaGenerator, ctx: SimpleNamespace) -> None:
    """Pure rendering for operazioni page (sintesi + cronologia)."""
    data = ctx.data
    settings = getattr(ctx, "settings", {}) if hasattr(ctx, "settings") else {}
    theme = get_theme_context()

    with tab:
        render_page_intro_shared(
            t(settings, "tab.operations", "Operazioni"),
            t(settings, "page_intro.operazioni.comment", "Registro consultivo degli eventi di portafoglio e dei movimenti di cassa. Le azioni operative si aprono dalla sidebar."),
            "operations",
            theme,
        )

        eventi = get_registro_eventi(data)
        info_map = {s["ticker"]: s for s in data.get("strumenti", []) if s.get("ticker")}
        with profile_step("Operazioni", "build registro e sintesi"):
            ledger = build_operations_ledger(eventi, info_map)
            summary = build_operations_summary(eventi)
            for row in ledger:
                row["catColor"] = macro_color(row["cat"]) if row.get("cat") else ""

        # ─── Sintesi ───────────────────────────────────────────────
        year, anno, tot = summary["year"], summary["anno"], summary["totale"]
        render_section_title(
            t(settings, "operations.summary_title", "Sintesi"),
            comment=f"Totali dell'anno {year}; sotto ogni valore, quanto da sempre. Calcolati dagli stessi eventi della cronologia.",
            gap_after="xs",
        )
        cols = st.columns(6, gap="small")
        cards = [
            ("Operazioni", f"{anno['operazioni']}", f"da sempre: {tot['operazioni']}", theme.color_blue),
            ("Acquistato", fmt_eur_it(anno["acquistato"], 0), f"da sempre: {fmt_eur_it(tot['acquistato'], 0)}", theme.color_green),
            ("Vendite e rimborsi", fmt_eur_it(anno["incassato"], 0), f"da sempre: {fmt_eur_it(tot['incassato'], 0)}", theme.color_purple),
            ("Cedole e dividendi", fmt_eur_it(anno["proventi"], 0), f"da sempre: {fmt_eur_it(tot['proventi'], 0)} (netti)", theme.color_yellow),
            ("Costi e imposte", fmt_eur_it(anno["costi"], 0), f"da sempre: {fmt_eur_it(tot['costi'], 0)}", theme.color_gray),
            ("Liquidità attuale", fmt_eur_it(getattr(ctx, "liquidita_attuale", 0.0), 0), "disponibile in cassa", theme.color_orange),
        ]
        for col, (title, value, sub, accent) in zip(cols, cards):
            with col:
                kpi_card(title, value, sub, accent=accent)
        vertical_gap("sm")

        # ─── Cronologia ────────────────────────────────────────────
        render_section_title(
            t(settings, "operations.timeline_title", "Cronologia"),
            comment=t(
                settings,
                "operations.timeline_note",
                "Operazioni e movimenti di cassa in un'unica lista, dal più recente. Il versamento che copre un acquisto è nella riga dell'acquisto. Filtra, cerca, apri una riga per il dettaglio ed esporta in CSV: tutto nel browser, senza ricaricare la pagina.",
            ),
            gap_after="xs",
        )
        if ledger:
            with profile_step("Operazioni", "render cronologia", count=len(ledger)):
                render_html_iframe(build_timeline_html(ledger, _timeline_colors(theme)), height=TIMELINE_HEIGHT)
        else:
            st.info(t(settings, "operations.portfolio_empty", "Nessuna operazione registrata."))

        back_to_top(show_prev=True, show_next=True, nav_key="operazioni")
