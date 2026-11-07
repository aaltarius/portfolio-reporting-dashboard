"""Cruscotti > Benchmark: orchestrazione della UI e delle cache esistenti.

Pannelli di stato/controllo in un modulo dedicato; calcoli e figure restano
nel core, nello store analitico congelato e nella figure cache registrata.
"""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

import pandas as pd
import streamlit as st

from core.cache import record_cache_decision
from core.cache_signatures import build_portfolio_data_signature, charts_settings_signature, resolve_analysis_render_sig, theme_signature
from core.frozen_analysis_cache import cached_render_figure, get_frozen_analysis_cache, small_signature_part, store_frozen_analysis_cache
from core.render_profiler import profile_step
from core.services.benchmark import build_benchmark_transparency_payload, benchmark_explanation
from core.services.benchmark_control import read_control_snapshot, financial_series_revision
from ui.pages.benchmark_control_panels import render_health, render_assignments
from ui.pages.benchmark_discovery_panel import render_discovery_panel
from ui.pages.benchmark_manual_history import render_manual_history
from ui.charts.benchmark import build_portfolio_benchmark_comparison_chart
from ui.charts.benchmark_diagnostics import build_monthly_advantage_chart
from ui.components import kpi_card, legend_block, render_frozen_analysis_freeze_header, render_frozen_analysis_status_text, render_section_title, vertical_gap
from ui.formatting import fmt_date_only_it, fmt_eur_it, fmt_num_it, fmt_pct_it
from ui.theme import P, get_theme_context


BENCHMARK_PAYLOAD_CACHE_KEY = "_cruscotti_benchmark_payload_cache_v4_6"
BENCHMARK_RENDER_CACHE_KEY = "_cruscotti_benchmark_render_cache_v4_6"
_BENCHMARK_SIGNATURE_DICT_KEYS = frozenset({"benchmarking", "portfolio_benchmark_default", "settings_version"})


def _safe_count(value: Any) -> int:
    """Conta liste, tuple, dict, DataFrame e Series senza valutarli in booleano."""
    if value is None:
        return 0
    if isinstance(value, (pd.DataFrame, pd.Series)):
        return int(len(value))
    try:
        return int(len(value))
    except Exception:
        return 0


def _or_empty_sequence(value: Any) -> Any:
    """Ritorna [] solo per None, lasciando intatti DataFrame/Series/list già valorizzati."""
    return [] if value is None else value


def _benchmark_payload_signature(ctx: SimpleNamespace, settings: dict[str, Any], summary_payload: dict[str, Any] | None, control: dict | None = None) -> str:
    """Firma logica del payload benchmark, usata solo per capire se la cache è fresca."""
    summary_payload = summary_payload if isinstance(summary_payload, dict) else {}
    history = _or_empty_sequence(summary_payload.get("summary_history"))
    bench_history = _or_empty_sequence(summary_payload.get("benchmark_history"))
    try:
        sqlite_revision=financial_series_revision()
    except Exception:
        sqlite_revision='missing'
    # La firma cambia quando una serie assegnata OLTREPASSA la soglia di
    # freschezza, non a ogni mezzanotte né per un semplice tentativo HTTP.
    control = control if isinstance(control,dict) else {}
    assigned = control.get('assignments') or {}
    by_code = control.get('series_by_code') or {}
    expired=set()
    for ref in assigned.values():
        if not isinstance(ref,dict):continue
        ids=[leg.get('series_id') for leg in (ref.get('components') or []) if isinstance(leg,dict)]
        if not ids:ids=[ref.get('ticker')]
        for code in ids:
            row=by_code.get(code) or {}
            if row and (row.get('age_days') is None or row.get('age_days') > 10):
                expired.add(str(code))
    material = {
        "expired_assigned_series": sorted(expired),
        "sqlite_revision":sqlite_revision,
        "benchmark_algorithm_version":"v4.9-current-reference-visual",
        "data_sig": build_portfolio_data_signature(
            getattr(ctx, "data", {}),
            app_version=str(getattr(ctx, "app_version", "n/d")),
            schema_version=str(getattr(ctx, "schema_version", "n/d")),
        ),
        "benchmark_settings": small_signature_part(settings, _BENCHMARK_SIGNATURE_DICT_KEYS),
        "da": small_signature_part(getattr(ctx, "da", pd.DataFrame()), _BENCHMARK_SIGNATURE_DICT_KEYS),
        "summary": {
            "twr": summary_payload.get("twr"),
            "cagr": summary_payload.get("cagr"),
            "benchmark_return": summary_payload.get("benchmark_return"),
            "tracking_error": summary_payload.get("tracking_error"),
            "information_ratio": summary_payload.get("information_ratio"),
            "summary_history": small_signature_part(history, _BENCHMARK_SIGNATURE_DICT_KEYS),
            "benchmark_history": small_signature_part(bench_history, _BENCHMARK_SIGNATURE_DICT_KEYS),
        },
    }
    raw = json.dumps(material, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _fmt_pct(value: Any, signed: bool = True) -> str:
    v = _safe_float(value)
    return fmt_pct_it(v, 2, signed=signed) if v is not None else "n/d"


def _fmt_num(value: Any) -> str:
    v = _safe_float(value)
    return fmt_num_it(v, 2) if v is not None else "n/d"


def _excess_note(value: Any) -> str:
    v = _safe_float(value)
    if v is None:
        return "Confronto non disponibile"
    if v >= 0.03:
        return "Differenza positiva, dipende da periodo e qualita del benchmark"
    if v >= 0.0:
        return "Sopra benchmark"
    if v >= -0.03:
        return "Leggermente sotto benchmark"
    return "Differenza negativa, dipende da periodo e qualita del benchmark"


def _tracking_note(value: Any) -> str:
    v = _safe_float(value)
    if v is None:
        return "Non calcolabile"
    if v < 0.05:
        return "Bassa dispersione dei rendimenti relativi"
    if v < 0.15:
        return "Dispersione relativa intermedia"
    return "Elevata dispersione dei rendimenti relativi"


def _ir_note(value: Any) -> str:
    v = _safe_float(value)
    if v is None:
        return "Non calcolabile"
    if v >= 0.50:
        return "Indicativo: esito relativo positivo"
    if v >= 0.0:
        return "Extra-rendimento positivo"
    return "Scostamento medio negativo rispetto al rischio relativo"


def _drawdown_note(port_dd: Any, bench_dd: Any) -> str:
    p = _safe_float(port_dd)
    b = _safe_float(bench_dd)
    if p is None or b is None:
        return "Confronto non disponibile"
    if p > b:
        return "Drawdown meno profondo del benchmark"
    if p < b:
        return "Drawdown più profondo del benchmark"
    return "Drawdown allineato"


def _render_benchmark_kpis(metrics: dict[str, Any]) -> None:
    items = [
        ("Portafoglio", _fmt_pct(metrics.get("portfolio_return")), "Rendimento TWR proxy", P["blue"], P["green"] if (_safe_float(metrics.get("portfolio_return"), 0.0) or 0.0) >= 0 else P["red"]),
        ("Benchmark", _fmt_pct(metrics.get("benchmark_return")), "Rendimento riferimento", P["orange"], P["green"] if (_safe_float(metrics.get("benchmark_return"), 0.0) or 0.0) >= 0 else P["red"]),
        ("Extra-rendimento", _fmt_pct(metrics.get("excess_return")), _excess_note(metrics.get("excess_return")), P["green"], P["green"] if (_safe_float(metrics.get("excess_return"), 0.0) or 0.0) >= 0 else P["red"]),
        ("CAGR portafoglio", _fmt_pct(metrics.get("portfolio_cagr")), "Rendimento annualizzato", P["blue"], None),
        ("CAGR benchmark", _fmt_pct(metrics.get("benchmark_cagr")), "Riferimento annualizzato", P["orange"], None),
        ("Tracking error", _fmt_pct(metrics.get("tracking_error"), signed=False), _tracking_note(metrics.get("tracking_error")), P["orange"], None),
        ("Information ratio", _fmt_num(metrics.get("information_ratio")), _ir_note(metrics.get("information_ratio")), P["blue"], P["green"] if (_safe_float(metrics.get("information_ratio"), 0.0) or 0.0) >= 0 else P["red"]),
        ("Max drawdown", _fmt_pct(metrics.get("portfolio_max_drawdown")), _drawdown_note(metrics.get("portfolio_max_drawdown"), metrics.get("benchmark_max_drawdown")), P["red"], None),
    ]
    for chunk in (items[:4], items[4:]):
        cols = st.columns(4)
        for col, (label, value, subtitle, accent, value_color) in zip(cols, chunk):
            with col:
                kpi_card(label, value, subtitle, accent=accent, value_color=value_color)
        vertical_gap("xs")





def _format_period(period: dict[str, Any]) -> str:
    start = period.get("start")
    end = period.get("end")
    if not start or not end:
        return "Periodo confronto non disponibile"
    return f"Periodo confronto: {fmt_date_only_it(start)} → {fmt_date_only_it(end)}"


def render_benchmark(ctx: SimpleNamespace, summary_bundle: Any | None = None) -> None:
    """Renderizza la scheda Benchmark senza rigenerare automaticamente i payload pesanti."""
    settings = getattr(ctx, "settings", None)
    if not isinstance(settings, dict):
        settings = getattr(ctx, "data", {}).get("settings", {}) if isinstance(getattr(ctx, "data", {}), dict) else {}
    # Centro di controllo: metadati SQLite, nessuna lettura di tutte le curve
    # né chiamata di rete durante la consultazione ordinaria.
    data=getattr(ctx,'data',{}) if isinstance(getattr(ctx,'data',{}),dict) else {}
    from core.verified_benchmarks import IndexStore
    store=IndexStore()

    def _rediscover(ticker: str | None = None):
        from core.benchmark_discovery.service import rediscover
        with st.spinner('Ricerca del benchmark sul web'+(' di '+ticker if ticker else '')+'…'):
            result=rediscover(data,store=store,target_instrument=ticker)
        pending=result['pending']
        refs=result.get('references') or {}
        reasons=[f"{i['ticker']}: {i['detail']}" for i in result.get('items',[]) if i.get('status') in ('NON_SALVATO','ERRORE')][:3]
        st.session_state['_benchmark_center_last_result']=(
            ('**'+ticker+'** · ' if ticker else 'Ricalcolo generale · ')
            +f"{result['resolved']}/{result['requested']} strumenti con benchmark scelto e salvato."
            +(' In attesa (decisione precedente conservata): '+', '.join(pending)+'.' if pending else ' Nessuno strumento in attesa.')
            +(' Motivi: '+'; '.join(reasons)+'.' if reasons else '')
            +(f" Riferimenti di portafoglio salvati: {sum(1 for v in refs.values() if v)}/{len(refs)}." if refs else '')
            +' Per aggiornare grafici e KPI congelati usa «Analizza benchmark».')

    def _refresh_series(ticker: str | None = None):
        from core.benchmark_discovery.service import refresh_series
        with st.spinner('Aggiornamento dei prezzi dei benchmark scelti…'):
            result=refresh_series(data,store=store,target_instrument=ticker)
        reasons=[f"{i['ticker']}: {i['reason']}" for i in result.get('items',[]) if i.get('status')=='FALLITO' and i.get('reason')][:3]
        st.session_state['_benchmark_center_last_result']=(
            f"Prezzi aggiornati per {result['updated']} su {result['requested']} (strumenti e riferimenti di portafoglio); "
            f"{result['failed']} richieste non riuscite"+(' ('+'; '.join(reasons)+')' if reasons else '')+'. '
            'La scelta dei benchmark non è cambiata. Per aggiornare grafici e KPI congelati usa «Analizza benchmark».')

    def _fix_manual(ticker: str):
        from core.benchmark_discovery.runner import persist_manual, run_for_instrument
        from core.benchmark_discovery.yahoo_source import YahooSource
        symbol=str(st.session_state.get('benchmark_manual_symbol_'+ticker,'')).strip()
        if not symbol:
            st.session_state['_benchmark_center_last_result']='Indica il simbolo del benchmark da fissare.'
            return
        src=YahooSource()
        with st.spinner('Scarico lo storico di '+symbol+'…'):
            ok=persist_manual(store,ticker,symbol,src.long_name(symbol),src)
            if ok:
                run_for_instrument(data,ticker,store=store,source=src,manual=symbol)
        st.session_state['_benchmark_center_last_result']=(
            f'**{ticker}** · benchmark fissato a mano: {symbol}.' if ok else
            f'**{ticker}** · nessuno storico trovato per {symbol}: scelta non modificata.')

    def _clear_manual(ticker: str):
        store.save_override(ticker,'')
        st.session_state['_benchmark_center_last_result']=f'**{ticker}** · scelta manuale tolta: vale la scelta automatica più recente.'

    def _discovery_panel():
        with profile_step('Cruscotti/Benchmark','benchmark scelto dal web'):
            render_discovery_panel(data,store,on_rediscover=_rediscover,on_refresh_series=_refresh_series,
                                   on_fix_manual=_fix_manual,on_clear_manual=_clear_manual)

    with profile_step('Cruscotti/Benchmark','control: status/registry metadata'):
        control=read_control_snapshot(data,store=store)
    # Le verifiche e gli interventi sono mostrati a FONDO pagina.
    # La lettura anticipata dei soli metadati permette di riutilizzare
    # l'analisi congelata senza scaricare dati o cambiare le cache.

    summary_payload = getattr(summary_bundle, "payload", None) if summary_bundle is not None else None
    if summary_payload is None:
        summary_payload = getattr(ctx, "summary_payload", None)

    with profile_step("Cruscotti/Benchmark", "signature/cache/header"):
        signature = _benchmark_payload_signature(ctx, settings, summary_payload, control)
        entry, stale = get_frozen_analysis_cache(BENCHMARK_PAYLOAD_CACHE_KEY, "benchmark", signature)
        refresh_requested, status_slot = render_frozen_analysis_freeze_header(
            entry, stale, signature,
            title="Benchmark",
            comment="Analisi congelata: i calcoli benchmark vengono rigenerati solo su richiesta, per non appesantire i rerun dei Cruscotti.",
            entity_label="benchmark",
            key_prefix="benchmark",
        )

    # Un risultato congelato NON e' una fotografia valida se sono cambiati
    # algoritmo, SQLite, prezzi o classificazione. Evita la vecchia matrice
    # con Manuale/indici impropri dopo l'aggiornamento e ricostruisce il
    # payload corrente (anche su avvio della nuova patch).
    if stale:
        refresh_requested=True

    if refresh_requested:
        with st.status("Analisi benchmark in corso…", expanded=True) as status:
            st.write("Costruzione confronto portafoglio/benchmark e matrice strumenti/benchmark.")
            with profile_step("Cruscotti/Benchmark", "build transparency payload"):
                payload = build_benchmark_transparency_payload(
                    data=getattr(ctx, "data", {}),
                    settings=settings,
                    da_frame=getattr(ctx, "da", pd.DataFrame()),
                    summary_payload=summary_payload,
            )
            # La costruzione può aggiornare gli snapshot di assegnazione. Salva
            # l'entry con la revisione POST-calcolo per evitare un secondo
            # rebuild al rerun successivo, senza invalidare altre figure.
            signature = _benchmark_payload_signature(ctx, settings, summary_payload, control)
            entry = store_frozen_analysis_cache(BENCHMARK_PAYLOAD_CACHE_KEY, "benchmark", signature, payload)
            stale = False
            record_cache_decision(
                "analisi benchmark cruscotti",
                details={
                    "event_type": "benchmark_frozen_analysis_generate",
                    "artifact_id": "cruscotti.benchmark_frozen_analysis",
                    "signature": signature,
                    "material_change": False,
                    "changed_count": 0,
                },
                invalidated=False,
                token=0,
                force_reload=False,
                scenario="benchmark_frozen_analysis_isolated",
                render_scope="full_tabs",
                dirty_flags={},
            )
            status.update(label="Analisi benchmark aggiornata", state="complete", expanded=False)
        render_frozen_analysis_status_text(status_slot, entry, stale, entity_label="benchmark")
    elif entry is None:
        legend_block(
            "Questa sezione è intenzionalmente congelata: Benchmark è una lettura pesante e non viene ricalcolata durante i normali rerun di Cruscotti. "
            "Premi “Analizza benchmark” quando vuoi aggiornare grafici, KPI e matrice strumenti/benchmark.",
            variant="bottom",
        )
        # Anche senza un'analisi congelata, i controlli restano disponibili,
        # ma non occupano la parte alta della pagina.
        render_health(control)
        _discovery_panel()
        with profile_step('Cruscotti/Benchmark', 'gestione manuale storici universale'):
            render_manual_history(data)
        if st.session_state.get('_benchmark_center_last_result'):
            st.info(st.session_state['_benchmark_center_last_result'])
        return
    else:
        payload = entry.get("payload", {}) if isinstance(entry, dict) else {}
        with profile_step("Cruscotti/Benchmark", "reuse cached transparency payload"):
            pass

    # Usa la firma memorizzata nell'entry (versione dell'analisi) anziché quella
    # corrente del portfolio: così un refresh prezzi non invalida le figure
    # di un'analisi benchmark che non è stata rigenerata.
    render_sig = resolve_analysis_render_sig(signature, entry)
    _theme_sig = theme_signature(get_theme_context())
    _settings_sig = charts_settings_signature("ui/charts/settings.py")
    render_sig = f"{render_sig}|theme:{_theme_sig}|charts:{_settings_sig}"

    # Gerarchia visiva della scheda: KPI finanziari -> grafici -> matrice
    # -> approfondimento -> controlli ed interventi a fondo pagina.
    # Il layout non introduce render condizionale delle tab né nuovi rerun.
    with profile_step("Cruscotti/Benchmark", "render KPI principali"):
        cfg = payload.get("config", {})
        metrics = payload.get("metrics", {})
        availability = payload.get("availability", {})
        render_section_title(
            "Confronto complessivo del portafoglio",
            comment="Rendimenti e indicatori relativi al periodo comune. La qualità dei singoli abbinamenti è esaminata nella tabella sottostante.",
            icon="metrics",
        )
        _render_benchmark_kpis(metrics)
        parts = cfg.get('components', []) or []
        last_cache = payload.get('last_cache_date')
        cache_date = fmt_date_only_it(last_cache) if last_cache else "n/d"
        st.caption(
            '**Riferimento:** ' + str(cfg.get('label') or 'n/d') +
            ' · **Indici:** ' + fmt_num_it(len(parts), 0) +
            ' · **Cache al:** ' + cache_date +
            ' · ' + _format_period(payload.get('period', {}))
        )

    problems = availability.get('problems') or []
    if problems:
        for reason in problems:
            st.error('Confronto da verificare: ' + str(reason))
    elif availability.get('has_benchmark'):
        st.caption('Confronto sullo stesso periodo temporale per portafoglio e riferimento.')
    stale=availability.get('stale') or []
    if stale:
        oldest=min(stale,key=lambda x:x.get('last_date') or '')
        st.warning('Dati del benchmark fermi al '+fmt_date_only_it(oldest.get('last_date'))+f" ({oldest.get('age_days')} giorni fa): "
                   'il confronto arriva fin dove ci sono dati. Per aggiornarli premi «Aggiorna i prezzi dei benchmark scelti» e poi «Analizza benchmark».')

    with profile_step('Cruscotti/Benchmark','grafico comparativo principale'):
        history_count=_safe_count(payload.get('history'))
        comparison_fig=cached_render_figure(
            chart_id='cruscotti_benchmark_comparison',data_sig=render_sig,
            theme_sig=_theme_sig,charts_settings_sig=_settings_sig,
            builder=lambda:build_portfolio_benchmark_comparison_chart(payload.get('history')),
            page_label='Cruscotti/Benchmark',label='confronto doppio pannello',count=history_count,
            extra_params={'scope':'confronto','points':history_count,'chart_version':3})
        st.plotly_chart(comparison_fig,width='stretch')
    with profile_step('Cruscotti/Benchmark','componenti benchmark',
                      count=_safe_count(parts)):
        if parts:
            snippets=[]
            for part in parts:
                w=_safe_float(part.get('weight'))
                snippets.append(str(part.get('ticker') or '—')+' '+(f'{100*w:.0f}%' if w is not None else 'n/d'))
            st.caption('Componenti del benchmark: '+' + '.join(snippets)+'. Composizione indicativa e pesi di confronto, non partecipazioni reali.')

    # Un solo grafico aggiuntivo: il confronto principale incorpora gia' la
    # curva di vantaggio relativo nel pannello inferiore. Questo mantiene
    # contenuto il numero di oggetti Plotly pronti all'avvio (3 anziche' 4).
    if _safe_count(payload.get('history'))>=3:
        st.caption('Il grafico superiore confronta le curve base 100; quello inferiore '
                   'mostra il rapporto di crescita composto. I valori non sono un P/L personale.')
        monthly_fig=cached_render_figure(
            chart_id='cruscotti_benchmark_monthly_advantage',
            data_sig=render_sig,theme_sig=_theme_sig,charts_settings_sig=_settings_sig,
            builder=lambda:build_monthly_advantage_chart(payload.get('history')),
            page_label='Cruscotti/Benchmark',label='scarto mensile',count=history_count,
            extra_params={'scope':'monthly_advantage','points':history_count,'chart_version':1})
        st.plotly_chart(monthly_fig,width='stretch')
        st.caption('Le barre mensili mostrano la differenza in punti percentuali tra '
                   'rendimenti del mese. L’ultimo mese può essere parziale; '
                   'dividendi, cedole e varianti degli indici devono essere omogenei '
                   'per trarre conclusioni finanziarie.')

    with st.expander('Come leggere il confronto complessivo', expanded=False):
        st.write(benchmark_explanation(payload))

    # Lo storico, i grafici e tutti i KPI sono già stati predisposti.
    with profile_step("Cruscotti/Benchmark", "render matrice strumenti"):
        vertical_gap("sm")
        render_assignments(payload.get("instrument_matrix"), control)

    # Diagnostica riassunta, non una seconda griglia di KPI.
    with profile_step('Cruscotti/Benchmark', 'stato storico di riferimento'):
        render_health(control)

    # La coda operativa conclude la pagina e resta deliberatamente compatta.
    with profile_step('Cruscotti/Benchmark', 'benchmark scelto dal web'):
        vertical_gap('xs')
        _discovery_panel()
    with profile_step('Cruscotti/Benchmark', 'gestione manuale storici universale'):
        render_manual_history(data)
    if st.session_state.get('_benchmark_center_last_result'):
        st.info(st.session_state['_benchmark_center_last_result'])


