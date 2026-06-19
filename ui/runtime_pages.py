from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

import streamlit as st

from core.render_profiler import (
    append_render_profile_run,
    render_profile_history_text,
    render_profile_coverage_text,
    render_invalidation_plan_text,
    render_profile_text,
    reset_render_profile,
)


@dataclass(slots=True)
class PageDef:
    page_id: str
    label: str
    renderer: Callable[[Any, Any], None]


def trigger_tab_navigation(page_label: str) -> None:
    html = f"""<script>
(function(){{
  function scrollTop(){{
    try{{
      var d=window.parent.document;
      var anchor=d.getElementById('page-top');
      if(anchor){{ anchor.scrollIntoView({{behavior:'auto',block:'start'}}); }}
      window.parent.scrollTo({{top:0,behavior:'auto'}});
      if(d.documentElement) d.documentElement.scrollTop=0;
      if(d.body) d.body.scrollTop=0;
    }}catch(e){{ window.scrollTo({{top:0,behavior:'auto'}}); }}
  }}
  scrollTop();
  setTimeout(scrollTop, 80);
  setTimeout(scrollTop, 320);
  setTimeout(scrollTop, 600);
}})();
</script>"""
    if hasattr(st, "html"):
        try:
            st.html(html, unsafe_allow_javascript=True)
            return
        except TypeError:
            st.html(html)
            return
        except Exception:
            return


def _clamp_active_tab_index(page_defs: list[PageDef]) -> int:
    active_tab = st.session_state.get("active_tab", 0)
    try:
        index = int(active_tab)
    except (TypeError, ValueError):
        index = 0
    return max(0, min(index, max(len(page_defs) - 1, 0)))


def _render_page_selector(page_defs: list[PageDef], *, active_index: int) -> int:
    labels = [page.label for page in page_defs]
    selected_label = st.radio(
        "Sezione",
        labels,
        index=active_index,
        horizontal=True,
        key="dashboard_active_page_label",
        label_visibility="collapsed",
    )
    try:
        return labels.index(selected_label)
    except ValueError:
        return active_index


def _render_page_step(
    *,
    label: str,
    step: int,
    total: int,
    render_func,
    target,
    context,
    render_started_at: float,
    render_progress,
    sidebar_progress=None,
    render_steps: list[tuple[str, Any, Any]],
    app_logger,
) -> None:
    t0 = time.perf_counter()
    percent_before = int(((step - 1) / max(total, 1)) * 100)
    elapsed_before = time.perf_counter() - render_started_at
    if render_progress is not None:
        render_progress.progress(percent_before, text=f"Rendering {label}... ({elapsed_before:.1f}s)")
    if sidebar_progress is not None:
        sidebar_progress.progress(max(1, percent_before), text=f"Debug sidebar: {label}")
    status = "OK"
    error_msg = ""
    try:
        render_func(target, context)
    except Exception as exc:
        status = "ERRORE"
        error_msg = f"{type(exc).__name__}: {exc}"
        app_logger.exception("Errore durante rendering pagina %s", label)
        raise
    finally:
        elapsed = time.perf_counter() - t0
        render_steps.append((label, elapsed, step, status, error_msg))
        percent_after = int((step / max(total, 1)) * 100)
        elapsed_after = time.perf_counter() - render_started_at
        if render_progress is not None:
            render_progress.progress(
                percent_after,
                text=(f"Completato: {label} ({elapsed_after:.1f}s)" if status == "OK" else f"Errore: {label} ({elapsed_after:.1f}s)"),
            )
        if sidebar_progress is not None:
            sidebar_progress.progress(
                max(1, percent_after),
                text=(f"Debug sidebar: {label} OK" if status == "OK" else f"Debug sidebar: {label} errore"),
            )


def _render_active_page(page_defs: list[PageDef], ctx: Any) -> tuple[PageDef, float]:
    active_index = _clamp_active_tab_index(page_defs)
    selected_index = _render_page_selector(page_defs, active_index=active_index)
    if selected_index != active_index:
        st.session_state["active_tab"] = selected_index
        active_index = selected_index
    active_page = page_defs[active_index]
    st.session_state["current_page_index"] = active_index
    st.session_state["current_page_total"] = len(page_defs)
    st.session_state["current_page_id"] = active_page.page_id
    t0 = time.perf_counter()
    active_page.renderer(st.container(), ctx)
    return active_page, time.perf_counter() - t0


def _render_standard_tabs(page_defs: list[PageDef], ctx: Any) -> None:
    tab_targets = st.tabs([page.label for page in page_defs])
    for idx, (page, target) in enumerate(zip(page_defs, tab_targets)):
        st.session_state["current_page_index"] = idx
        st.session_state["current_page_total"] = len(page_defs)
        st.session_state["current_page_id"] = page.page_id
        page.renderer(target, ctx)



def _format_dirty_flags(dirty_flags: dict[str, bool] | None) -> str:
    if not isinstance(dirty_flags, dict) or not dirty_flags:
        return "none"
    active = [str(k) for k, v in dirty_flags.items() if bool(v)]
    return ",".join(active) if active else "none"


def _format_skipped_pages(page_defs: list[PageDef], active_page_id: str) -> str:
    skipped = [p.page_id for p in page_defs if p.page_id != active_page_id]
    return ",".join(skipped) if skipped else "none"


def _resolve_operational_active_index(
    page_defs: list[PageDef],
    *,
    origin_page_id: str = "",
    origin_page_index: int | None = None,
) -> int:
    """Sceglie la pagina da renderizzare in un rerun operativo leggero.

    La pagina sorgente ha priorita su active_tab perche, dopo uno st.rerun
    lanciato da una pagina renderizzata dentro st.tabs, active_tab puo ancora
    valere 0 o il default. Questo evita che un salvataggio da Impostazioni,
    Operazioni o SATOR faccia renderizzare Quotazioni.
    """
    origin_id = str(origin_page_id or "").strip()
    if origin_id:
        for idx, page in enumerate(page_defs):
            if page.page_id == origin_id:
                return idx
    if origin_page_index is not None:
        try:
            idx = int(origin_page_index)
            return max(0, min(idx, max(len(page_defs) - 1, 0)))
        except Exception:
            pass
    return _clamp_active_tab_index(page_defs)

def render_dashboard_tabs(
    *,
    page_defs: list[PageDef],
    ctx: Any,
    debug_enabled: bool,
    debug_progress_enabled: bool,
    debug_log_enabled: bool,
    render_overview,
    app_logger,
    app_version: str,
    schema_version: str,
    data_mtime: float,
    cache_bust: Any,
    portfolio_signature: str,
    pre_render_signature: str | None,
    profiling_cohort: str,
    profiling_scenario: str,
    profiling_signature_diff_lines: list[str] | None = None,
    debug_render_scope: str = "current_page",
    operational_render_scope: str = "full_tabs",
    operational_reason: str = "",
    operational_origin_page_id: str = "",
    operational_origin_page_index: int | None = None,
    dirty_flags: dict[str, bool] | None = None,
    progress_host=None,
) -> None:
    render_started_at = time.perf_counter()
    render_steps: list[tuple[str, Any, Any]] = []
    debug_full_sweep = debug_enabled and str(debug_render_scope or "current_page") == "full_sweep"
    operational_scope = str(operational_render_scope or "full_tabs")
    if operational_scope == "current_page_only":
        # Con st.tabs native passive il render selettivo lascia le altre pagine
        # vuote, perché il cambio linguetta non genera un nuovo script run.
        # La navigazione principale deve quindi restare full-tabs.
        operational_scope = "full_tabs"
    operational_light = False
    render_progress = None
    if debug_progress_enabled:
        try:
            render_progress = (progress_host or st).progress(0, text="Preparazione caricamento dashboard...")
        except Exception:
            render_progress = st.progress(0, text="Preparazione caricamento dashboard...")

    if debug_enabled:
        reset_render_profile()
        debug_mode_label = "sweep completo" if debug_full_sweep else "UI completa a schede"
        st.markdown(f"### Monitor rendering pagine — modalità debug attiva ({debug_mode_label})")
        render_log = st.empty() if debug_log_enabled else None
        sidebar_progress = None
        try:
            st.sidebar.caption("Monitor rendering attivo")
            sidebar_progress = st.sidebar.progress(5, text=f"Rendering debug: {debug_mode_label}")
        except Exception:
            pass
        render_elapsed = time.perf_counter() - render_started_at
        if render_progress is not None:
            render_progress.progress(3, text=f"Rendering Overview / KPI iniziali... ({render_elapsed:.1f}s)")
        render_overview(st.container(), ctx)
        render_elapsed = time.perf_counter() - render_started_at
        if render_progress is not None:
            render_progress.progress(8, text=f"Completato: Overview / KPI iniziali ({render_elapsed:.1f}s)")
    else:
        render_elapsed = time.perf_counter() - render_started_at
        if render_progress is not None:
            render_progress.progress(3, text=f"Rendering Overview / KPI iniziali... ({render_elapsed:.1f}s)")
        render_overview(st.container(), ctx)
        render_elapsed = time.perf_counter() - render_started_at
        if render_progress is not None:
            render_progress.progress(8, text=f"Completato: Overview / KPI iniziali ({render_elapsed:.1f}s)")
        render_log = None
        sidebar_progress = None

    st.markdown("---")

    if operational_light:
        active_index = _resolve_operational_active_index(
            page_defs,
            origin_page_id=operational_origin_page_id,
            origin_page_index=operational_origin_page_index,
        )
        active_page = page_defs[active_index]
        st.session_state["active_tab"] = active_index
        total_render_steps = 1
        st.session_state["current_page_index"] = active_index
        st.session_state["current_page_total"] = len(page_defs)
        st.session_state["current_page_id"] = active_page.page_id
        _render_page_step(
            label=active_page.label,
            step=1,
            total=total_render_steps,
            render_func=active_page.renderer,
            target=st.container(),
            context=ctx,
            render_started_at=render_started_at,
            render_progress=render_progress,
            sidebar_progress=sidebar_progress,
            render_steps=render_steps,
            app_logger=app_logger,
        )
        render_elapsed_total = time.perf_counter() - render_started_at
        if render_progress is not None:
            render_progress.progress(100, text=f"Dashboard pronta in {render_elapsed_total:.1f} secondi")
        if debug_log_enabled:
            try:
                skipped_pages = _format_skipped_pages(page_defs, active_page.page_id)
                render_lines = [
                    "=== PORTFOLIO DASHBOARD — RENDER LOG ===",
                    "versione_log: render-log-v1+deep-v4",
                    "profiling_mode: operational_current_page_only",
                    f"render_scope: {operational_scope}",
                    f"operational_reason: {operational_reason or 'n/d'}",
                    f"origin_page: {operational_origin_page_id or active_page.page_id}",
                    f"dirty_flags: {_format_dirty_flags(dirty_flags)}",
                    f"skipped_pages: {skipped_pages}",
                    f"timestamp_locale: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    f"app_version: {app_version}",
                    f"schema_version: {schema_version}",
                    f"data_mtime: {data_mtime:.6f}",
                    f"cache_bust: {cache_bust}",
                    f"signature: {portfolio_signature}",
                    f"profiling_cohort: {profiling_cohort}",
                    *(profiling_signature_diff_lines or []),
                    f"totale_render_secondi: {render_elapsed_total:.3f}",
                    "",
                    "--- Tempi per pagina ---",
                ]
                for label, elapsed, step, status, error_msg in render_steps:
                    render_lines.append(f"{step:02d}. {label:<15} | {elapsed:8.3f}s | {status}" + (f" | {error_msg}" if error_msg else ""))
                render_lines.extend(
                    [
                        "",
                        render_invalidation_plan_text(),
                        "",
                    render_profile_coverage_text(render_steps, persisted_pre_render_signature=pre_render_signature),
                    "",
                        render_profile_text(min_seconds=0.0, persisted_pre_render_signature=pre_render_signature),
                        "",
                        "--- Lettura rapida ---",
                        "Rerun operativo leggero: dopo una mutazione viene renderizzata solo la pagina corrente.",
                        "Le pagine saltate restano disponibili e torneranno alla modalita standard al rerun successivo.",
                    ]
                )
                render_log_text = "\n".join(render_lines)
                if render_log is not None:
                    render_log.caption("Tempi rendering pagine — rerun operativo leggero.")
                    with st.expander("📋 Log testuale rendering / performance", expanded=False):
                        st.text_area("Log rendering copiabile", render_log_text, height=420)
                        st.download_button(
                            "Scarica log rendering .txt",
                            data=render_log_text.encode("utf-8"),
                            file_name=f"portfolio_render_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                            mime="text/plain",
                            key="download_render_log_txt",
                        )
            except Exception as exc:
                app_logger.warning("Impossibile mostrare log rendering operativo: %s", exc)
    elif debug_full_sweep:
        tab_targets = st.tabs([page.label for page in page_defs])
        total_render_steps = len(page_defs)
        for idx, (page, target) in enumerate(zip(page_defs, tab_targets), start=1):
            st.session_state["current_page_index"] = idx - 1
            st.session_state["current_page_id"] = page.page_id
            _render_page_step(
                label=page.label,
                step=idx,
                total=total_render_steps,
                render_func=page.renderer,
                target=target,
                context=ctx,
                render_started_at=render_started_at,
                render_progress=render_progress,
                sidebar_progress=sidebar_progress,
                render_steps=render_steps,
                app_logger=app_logger,
            )

        render_elapsed_total = time.perf_counter() - render_started_at
        if render_progress is not None:
            render_progress.progress(100, text=f"Dashboard pronta in {render_elapsed_total:.1f} secondi")
        try:
            render_lines = [
                "=== PORTFOLIO DASHBOARD — RENDER LOG ===",
                "versione_log: render-log-v1+deep-v3",
                "profiling_mode: full_sweep",
                f"render_scope: {operational_scope}",
                f"operational_reason: {operational_reason or 'n/d'}",
                f"dirty_flags: {_format_dirty_flags(dirty_flags)}",
                f"timestamp_locale: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"app_version: {app_version}",
                f"schema_version: {schema_version}",
                f"data_mtime: {data_mtime:.6f}",
                f"cache_bust: {cache_bust}",
                f"signature: {portfolio_signature}",
                f"profiling_cohort: {profiling_cohort}",
                *(profiling_signature_diff_lines or []),
                f"totale_render_secondi: {render_elapsed_total:.3f}",
                "",
                "--- Tempi per pagina ---",
            ]
            for label, elapsed, step, status, error_msg in render_steps:
                render_lines.append(f"{step:02d}. {label:<15} | {elapsed:8.3f}s | {status}" + (f" | {error_msg}" if error_msg else ""))

            try:
                append_render_profile_run(
                    signature=portfolio_signature,
                    cohort=profiling_cohort,
                    scenario=profiling_scenario,
                    total_render_seconds=render_elapsed_total,
                    page_steps=render_steps,
                    persisted_pre_render_signature=pre_render_signature,
                    metadata={
                        "app_version": app_version,
                        "schema_version": schema_version,
                        "data_mtime": data_mtime,
                        "cache_bust": cache_bust,
                    },
                )
            except Exception as exc:
                app_logger.warning("Impossibile salvare storico render: %s", exc)

            render_lines.extend(
                [
                    "",
                    render_invalidation_plan_text(),
                    "",
                    render_profile_coverage_text(render_steps, persisted_pre_render_signature=pre_render_signature),
                    "",
                    render_profile_text(min_seconds=0.0, persisted_pre_render_signature=pre_render_signature),
                    "",
                    render_profile_history_text(cohort=profiling_cohort, limit=12),
                    "",
                    "--- Lettura rapida ---",
                    "Se una pagina supera 3-5 secondi, il collo di bottiglia è probabilmente nei grafici o nel payload di quella pagina.",
                    "Se il totale resta alto, verificare orchestrazione iniziale, cache e caricamento dati.",
                    "Se il totale cresce dopo salvataggi/import/aggiornamento quotazioni, verificare invalidazione cache e firma dati.",
                ]
            )
            render_log_text = "\n".join(render_lines)
            if render_log is not None:
                render_log.caption("Tempi rendering pagine — copia il log qui sotto e incollamelo per l'analisi.")
                with st.expander("📋 Log testuale rendering / performance", expanded=False):
                    st.text_area("Log rendering copiabile", render_log_text, height=420)
                    st.download_button(
                        "Scarica log rendering .txt",
                        data=render_log_text.encode("utf-8"),
                        file_name=f"portfolio_render_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                        mime="text/plain",
                        key="download_render_log_txt",
                    )
        except Exception as exc:
            app_logger.warning("Impossibile mostrare log rendering dettagliato: %s", exc)
    elif debug_enabled:
        tab_targets = st.tabs([page.label for page in page_defs])
        total_render_steps = len(page_defs)
        for idx, (page, target) in enumerate(zip(page_defs, tab_targets), start=1):
            st.session_state["current_page_index"] = idx - 1
            st.session_state["current_page_total"] = len(page_defs)
            st.session_state["current_page_id"] = page.page_id
            _render_page_step(
                label=page.label,
                step=idx,
                total=total_render_steps,
                render_func=page.renderer,
                target=target,
                context=ctx,
                render_started_at=render_started_at,
                render_progress=render_progress,
                sidebar_progress=sidebar_progress,
                render_steps=render_steps,
                app_logger=app_logger,
            )
        render_elapsed_total = time.perf_counter() - render_started_at
        if render_progress is not None:
            render_progress.progress(100, text=f"Dashboard pronta in {render_elapsed_total:.1f} secondi")
        if debug_log_enabled:
            try:
                render_lines = [
                    "=== PORTFOLIO DASHBOARD — RENDER LOG ===",
                    "versione_log: render-log-v1+deep-v3",
                    "profiling_mode: ui_full_tabs",
                    f"render_scope: {operational_scope}",
                    f"operational_reason: {operational_reason or 'n/d'}",
                    f"dirty_flags: {_format_dirty_flags(dirty_flags)}",
                    f"timestamp_locale: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    f"app_version: {app_version}",
                    f"schema_version: {schema_version}",
                    f"data_mtime: {data_mtime:.6f}",
                    f"cache_bust: {cache_bust}",
                    f"signature: {portfolio_signature}",
                    f"profiling_cohort: {profiling_cohort}",
                    *(profiling_signature_diff_lines or []),
                    f"totale_render_secondi: {render_elapsed_total:.3f}",
                    "",
                    "--- Tempi per pagina ---",
                ]
                for label, elapsed, step, status, error_msg in render_steps:
                    render_lines.append(f"{step:02d}. {label:<15} | {elapsed:8.3f}s | {status}" + (f" | {error_msg}" if error_msg else ""))
                render_lines.extend(
                    [
                        "",
                        render_invalidation_plan_text(),
                        "",
                    render_profile_coverage_text(render_steps, persisted_pre_render_signature=pre_render_signature),
                    "",
                        render_profile_text(min_seconds=0.0, persisted_pre_render_signature=pre_render_signature),
                        "",
                        render_profile_history_text(cohort=profiling_cohort, limit=12),
                        "",
                        "--- Lettura rapida ---",
                        "L'app standard mantiene il pre-render completo iniziale delle schede.",
                        "Questo riepilogo misura i tempi pagina-per-pagina senza cambiare la navigazione.",
                    ]
                )
                render_log_text = "\n".join(render_lines)
                if render_log is not None:
                    render_log.caption("Tempi rendering pagine — copia il log qui sotto e incollamelo per l'analisi.")
                    with st.expander("📋 Log testuale rendering / performance", expanded=False):
                        st.text_area("Log rendering copiabile", render_log_text, height=420)
                        st.download_button(
                            "Scarica log rendering .txt",
                            data=render_log_text.encode("utf-8"),
                            file_name=f"portfolio_render_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                            mime="text/plain",
                            key="download_render_log_txt",
                        )
            except Exception as exc:
                app_logger.warning("Impossibile mostrare log rendering dettagliato: %s", exc)
    else:
        _render_standard_tabs(page_defs, ctx)
        render_elapsed_total = time.perf_counter() - render_started_at
        if render_progress is not None:
            render_progress.progress(100, text=f"Dashboard pronta in {render_elapsed_total:.1f} secondi")
