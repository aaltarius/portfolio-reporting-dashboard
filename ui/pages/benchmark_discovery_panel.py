"""Pannello «Benchmark scelto dal web»: stato per strumento, perche' della scelta, comandi dell'utente.

Nessun calcolo e nessuna rete nel render: legge solo l'archivio. Ricalcolo, aggiornamento dei prezzi
e scelta manuale partono dai pulsanti (callback passate dalla pagina).
"""
from __future__ import annotations

from typing import Callable

import streamlit as st

from core.benchmark_discovery.view import decision_detail, decision_rows
from ui.components import render_section_title
from ui.pages.benchmark_tables import render_benchmark_table

_STATE_LABEL = {"ok": "Aggiornato", "stale": "Dati non aggiornati", "manual": "Scelta manuale",
                "pending": "In attesa di calcolo"}
_GRADE_LABEL = {"PROPRIA": "Indice proprio", "SORELLA": "Sorella", "CUGINA": "Cugina", "ZIA": "Zia",
                "NONNA": "Nonna", "COMPOSITO": "Composito", "MANUALE": "Manuale"}


def _fmt(value, digits=2) -> str:
    return "n/d" if value is None else f"{value:.{digits}f}"


def render_discovery_panel(data: dict, store, *, on_rediscover: Callable, on_refresh_series: Callable,
                           on_fix_manual: Callable, on_clear_manual: Callable) -> None:
    render_section_title(
        "Benchmark scelto dal web", icon="analysis",
        comment="Per ogni strumento il programma cerca online il benchmark piu' idoneo a partire dai dati di "
                "arricchimento; un ETF che replica l'indice e' un proxy e viene indicato come tale. "
                "La rete si usa solo quando premi i pulsanti qui sotto.",
        gap_after="sm")
    rows = decision_rows(data, store)
    if not rows:
        st.caption("Nessuno strumento attivo.")
        return
    records = [{"Strumento": r["ticker"], "Benchmark": r["benchmark"] or "—", "Nome": r["label"] or "—",
                "Parentela": _GRADE_LABEL.get(r["grade"], r["grade"] or "—"),
                "Correlazione": _fmt(r["corr"]), "Scostamento %": _fmt(r["te_pct"], 1),
                "Dati al": r["updated"] or "—", "Stato": _STATE_LABEL.get(r["state"], r["state"])} for r in rows]
    render_benchmark_table(records, key="benchmark_discovery_table",
                           columns=[("Strumento", "Strumento"), ("Benchmark", "Benchmark"), ("Nome", "Nome"),
                                    ("Parentela", "Parentela"), ("Correlazione", "Correlazione"),
                                    ("Scostamento %", "Scostamento annuo %"), ("Dati al", "Dati al"), ("Stato", "Stato")],
                           widths=[10, 12, 28, 11, 10, 10, 10, 13])
    pending = sum(r["state"] == "pending" for r in rows)
    if pending:
        st.caption(f"**{pending} strumenti in attesa di calcolo.** Premi «Ricalcola la scelta» per cercare il benchmark sul web.")
    a, b = st.columns(2, gap="medium")
    with a:
        st.button("Ricalcola la scelta di tutti · cerca sul web", key="benchmark_discovery_all", use_container_width=True,
                  on_click=on_rediscover, type="primary",
                  help="Cerca di nuovo il benchmark di ogni strumento attivo. Le scelte manuali non cambiano; se la rete non risponde si conserva la scelta precedente.")
    with b:
        st.button("Aggiorna i prezzi dei benchmark scelti", key="benchmark_discovery_prices", use_container_width=True,
                  on_click=on_refresh_series, help="Riscarica solo i dati dei benchmark gia' scelti, senza cambiare la scelta.")

    options = [r["ticker"] for r in rows]
    ticker = st.selectbox("Perche' questo benchmark? Scegli uno strumento", options, key="benchmark_discovery_pick",
                          format_func=lambda t: t + " · " + next(r["name"] for r in rows if r["ticker"] == t)[:40])
    row = next(r for r in rows if r["ticker"] == ticker)
    detail = decision_detail(store, ticker)
    if detail is None:
        st.caption("Nessuna decisione salvata per questo strumento: premi «Ricalcola la scelta».")
    else:
        prof = detail["profile"]
        st.caption("**Profilo usato:** tipo " + str(prof.get("kind") or "n/d") + " · area " + (", ".join(prof.get("area_terms") or []) or "n/d")
                   + " · tema " + (", ".join(prof.get("theme_terms") or []) or "n/d")
                   + " · indice dichiarato " + (prof.get("index_declared") or "n/d"))
        if detail["legs"]:
            st.caption("**Composito:** " + " + ".join(f"{l['symbol']} {l['weight_pct']:g}% ({l.get('weight_source', '')})" for l in detail["legs"]))
        st.caption("**Frasi cercate:** " + " · ".join(f"{q['text']} ({q['found']})" for q in detail["queries"][:10]))
        cands = [{"Candidato": c["symbol"], "Nome": c["name"][:40], "Livello": c["level"],
                  "Coerenza": _fmt(c.get("coherence")), "Correlazione": _fmt(c.get("corr")),
                  "Punteggio": _fmt(c.get("score"), 3), "Esito": c.get("reason") or ("valido" if c.get("valid") else "non valutato")}
                 for c in detail["candidates"][:12]]
        if cands:
            with st.expander("Candidati valutati (primi 12)", expanded=False):
                render_benchmark_table(cands, key="benchmark_discovery_candidates",
                                       columns=[(k, k) for k in cands[0]], widths=[12, 28, 8, 10, 12, 10, 20])
    with st.expander("Fissa a mano il benchmark di " + ticker, expanded=False):
        st.caption("La scelta manuale prevale sempre sulla ricerca automatica. Indica il simbolo di un ETF o di un indice "
                   "(per esempio un simbolo di Yahoo Finance); lo storico viene scaricato ora.")
        st.text_input("Simbolo", key="benchmark_manual_symbol_" + ticker)
        c1, c2 = st.columns(2)
        with c1:
            st.button("Fissa questo benchmark", key="benchmark_manual_set_" + ticker, on_click=on_fix_manual, args=(ticker,))
        with c2:
            if row["state"] == "manual":
                st.button("Torna alla scelta automatica", key="benchmark_manual_clear_" + ticker, on_click=on_clear_manual, args=(ticker,))
