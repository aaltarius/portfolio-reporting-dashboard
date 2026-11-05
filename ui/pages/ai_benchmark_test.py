# ui/pages/ai_benchmark_test.py
"""Tab di prova: benchmark ufficiali degli strumenti in portafoglio, chiesti a Gemini in una sola richiesta."""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import streamlit as st

from core.ai_analysis import AI_CALL_COUNT_KEY
from core.ai_benchmark_probe import BenchmarkProbeResult, collect_probe_instruments, run_benchmark_probe
from ui.components import legend_block, render_section_title, vertical_gap

_RESULT_KEY = "_ai_benchmark_probe_result_v1"
_COLUMNS = {
    "ticker": "Ticker",
    "benchmark_ufficiale": "Benchmark ufficiale",
    "fornitore_indice": "Fornitore indice",
    "variante": "Variante",
    "confidenza": "Confidenza",
    "fonte": "Fonte dichiarata",
    "note": "Note",
}


def render_ai_benchmark_test(ctx: SimpleNamespace, *, api_key: str, model: str) -> None:
    render_section_title(
        "Test: benchmark ufficiali via Gemini",
        comment="Prova su richiesta: una sola chiamata chiede a Gemini il benchmark ufficiale di tutti gli strumenti in portafoglio. Il risultato non viene salvato né usato dai calcoli.",
        icon="analysis",
    )
    legend_block(
        "A Google vengono inviati solo ticker, ISIN, nome e tipo degli strumenti posseduti: nessuna quantità, importo o P/L. "
        "Le risposte non sono verificate: controllale sul KID o sulla scheda dell'emittente prima di fidartene.",
        variant="bottom",
    )
    vertical_gap("xs")

    instruments = collect_probe_instruments(getattr(ctx, "data", {}) or {}, getattr(ctx, "da", pd.DataFrame()))
    if not instruments:
        st.info("Nessuno strumento in portafoglio da interrogare.")
        return

    use_search = st.checkbox(
        "Usa la ricerca Google (grounding) per i documenti ufficiali",
        value=False,
        key="_ai_benchmark_probe_search",
        help="Di default spenta, come Analisi e Chat: la risposta si basa sulla conoscenza del modello. La ricerca ha una quota propria (per Gemini 3 è fatturata a parte) e sul piano gratuito può dare errore 429.",
    )
    st.caption(f"{len(instruments)} strumenti · modello {model} · 1 richiesta")
    if st.button("Chiedi i benchmark a Gemini", type="primary", key="_ai_benchmark_probe_btn"):
        with st.spinner("Richiesta a Gemini in corso…"):
            try:
                st.session_state[_RESULT_KEY] = run_benchmark_probe(instruments, api_key, model=model, use_search=use_search)
                st.session_state[AI_CALL_COUNT_KEY] = st.session_state.get(AI_CALL_COUNT_KEY, 0) + 1
            except RuntimeError as exc:
                st.error(str(exc))
                return

    result: BenchmarkProbeResult | None = st.session_state.get(_RESULT_KEY)
    if result is None:
        return
    if result.rows:
        frame = pd.DataFrame(result.rows)
        shown = [c for c in _COLUMNS if c in frame.columns]
        st.dataframe(frame[shown].rename(columns=_COLUMNS), hide_index=True, width="stretch")
    if result.missing:
        st.warning("Strumenti non presenti nella risposta: " + ", ".join(result.missing))
    with st.expander("Risposta grezza di Gemini"):
        st.code(result.raw_text)
