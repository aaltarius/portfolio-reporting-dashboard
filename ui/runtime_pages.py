from __future__ import annotations

import json
import os
import time
import uuid
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
from ui.streamlit_compat import render_html_iframe


_TAB_STATE_STORAGE_KEY = "sestante.activeTabIndex.v1"
_RUNTIME_PROCESS_TOKEN = uuid.uuid4().hex[:10]
_RUNTIME_MODULE_LOADED_AT = time.time()


@dataclass(slots=True)
class PageDef:
    page_id: str
    label: str
    renderer: Callable[[Any, Any], None]


def _render_inline_script(html: str) -> None:
    if hasattr(st, "html"):
        try:
            st.html(html, unsafe_allow_javascript=True)
            return
        except TypeError:
            st.html(html)
            return
        except Exception:
            return


def _render_copyable_render_log(render_log_text: str, *, key: str) -> None:
    """Mostra log tempi con azioni coerenti: copia negli appunti e download."""
    safe_key = "".join(ch if ch.isalnum() else "-" for ch in str(key or "render-log"))
    payload_json = json.dumps(str(render_log_text or ""))
    filename_json = json.dumps(f"portfolio_render_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    st.text_area("Log rendering / performance", render_log_text, height=420, key=f"{safe_key}_text")
    render_html_iframe(
        f"""
        <!doctype html>
        <html>
        <head>
        <meta charset="utf-8">
        <style>
        html,body{{
            margin:0;
            padding:0;
            background:transparent;
            overflow:hidden;
        }}
        .render-log-actions-{safe_key}{{
            display:grid;
            grid-template-columns:1fr 1fr;
            gap:8px;
            margin:0;
        }}
        .render-log-action-{safe_key}{{
            box-sizing:border-box;
            display:inline-flex;
            align-items:center;
            justify-content:center;
            width:100%;
            min-height:38px;
            border:1px solid rgba(49,51,63,.22);
            border-radius:8px;
            background:#fff;
            color:#31333f;
            font:600 14px/1.2 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
            padding:8px 12px;
            cursor:pointer;
            text-align:center;
        }}
        .render-log-action-{safe_key}:hover{{
            border-color:rgba(49,51,63,.38);
            background:#f8fafc;
        }}
        .render-log-status-{safe_key}{{
            display:block;
            min-height:16px;
            margin-top:4px;
            color:#64748b;
            font:500 12px/1.2 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
            text-align:right;
        }}
        @media (max-width: 640px){{
            .render-log-actions-{safe_key}{{grid-template-columns:1fr;}}
        }}
        </style>
        </head>
        <body>
        <div class="render-log-actions-{safe_key}">
          <button type="button" class="render-log-action-{safe_key}" id="render-log-download-{safe_key}">Scarica log rendering .txt</button>
          <button type="button" class="render-log-action-{safe_key}" id="render-log-copy-{safe_key}">Copia negli appunti</button>
        </div>
        <span class="render-log-status-{safe_key}" id="render-log-status-{safe_key}"></span>
        <script>
        (function(){{
          var text = {payload_json};
          var filename = {filename_json};
          var copyBtn = document.getElementById("render-log-copy-{safe_key}");
          var downloadBtn = document.getElementById("render-log-download-{safe_key}");
          var status = document.getElementById("render-log-status-{safe_key}");
          function setStatus(msg){{ if(status) status.textContent = msg; }}
          function fallbackCopy(){{
            var ta = document.createElement("textarea");
            ta.value = text;
            ta.setAttribute("readonly", "");
            ta.style.position = "fixed";
            ta.style.left = "-9999px";
            ta.style.top = "0";
            document.body.appendChild(ta);
            ta.focus();
            ta.select();
            var ok = false;
            try {{ ok = document.execCommand("copy"); }} catch(err) {{ ok = false; }}
            document.body.removeChild(ta);
            return ok;
          }}
          function downloadTextFile(){{
            var blob = new Blob([text], {{type: "text/plain;charset=utf-8"}});
            var url = URL.createObjectURL(blob);
            var a = document.createElement("a");
            a.href = url;
            a.download = filename;
            a.style.display = "none";
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            setTimeout(function(){{ URL.revokeObjectURL(url); }}, 1000);
          }}
          if(downloadBtn){{
            downloadBtn.addEventListener("click", function(){{
              try {{
                downloadTextFile();
                setStatus("Download avviato");
                setTimeout(function(){{ setStatus(""); }}, 1800);
              }} catch(err) {{
                setStatus("Download non riuscito: usa il testo sopra");
              }}
            }});
          }}
          if(copyBtn){{
            copyBtn.addEventListener("click", async function(){{
              try {{
                var copied = false;
                if(navigator.clipboard && window.isSecureContext) {{
                  try {{
                    await navigator.clipboard.writeText(text);
                    copied = true;
                  }} catch(err) {{
                    copied = false;
                  }}
                }}
                if(!copied) copied = fallbackCopy();
                if(!copied) throw new Error("clipboard unavailable");
                setStatus("Copiato");
                setTimeout(function(){{ setStatus(""); }}, 1800);
              }} catch(err) {{
                setStatus("Copia non riuscita: seleziona il testo sopra");
              }}
            }});
          }}
        }})();
        </script>
        </body>
        </html>
        """,
        height=64,
        scrolling=False,
    )


def _short_layers_summary(layers: dict[str, int], *, limit: int = 8) -> str:
    if not layers:
        return "none"
    items = [f"{key}={value}" for key, value in sorted(layers.items())[:limit]]
    remaining = max(0, len(layers) - limit)
    if remaining:
        items.append(f"+{remaining} altri")
    return ", ".join(items)


def _runtime_continuity_lines() -> list[str]:
    """Righe diagnostiche per capire se il run e' davvero caldo."""

    try:
        session_token = str(st.session_state.get("_sestante_session_token") or "")
        if not session_token:
            session_token = uuid.uuid4().hex[:10]
            st.session_state["_sestante_session_token"] = session_token
        run_ordinal = int(st.session_state.get("_sestante_session_run_ordinal", 0) or 0)
        if run_ordinal <= 0:
            run_ordinal = 1
            st.session_state["_sestante_session_run_ordinal"] = run_ordinal
    except Exception:
        session_token = "n/d"
        run_ordinal = 0

    try:
        from core.page_cache import get_page_artifact_runtime_stats

        stats = get_page_artifact_runtime_stats()
    except Exception:
        stats = {}

    process_layers = stats.get("process_layers") if isinstance(stats.get("process_layers"), dict) else {}
    session_layers = stats.get("session_layers") if isinstance(stats.get("session_layers"), dict) else {}
    module_age_seconds = max(0.0, time.time() - _RUNTIME_MODULE_LOADED_AT)

    return [
        f"process_pid: {os.getpid()}",
        f"process_token: {_RUNTIME_PROCESS_TOKEN}",
        f"runtime_module_age_seconds: {module_age_seconds:.1f}",
        f"session_token: {session_token}",
        f"session_run_ordinal: {run_ordinal}",
        (
            "page_cache_runtime: "
            f"process_entries={int(stats.get('process_entries', 0) or 0)}; "
            f"session_entries={int(stats.get('session_entries', 0) or 0)}"
        ),
        f"page_cache_process_layers: {_short_layers_summary(process_layers)}",
        f"page_cache_session_layers: {_short_layers_summary(session_layers)}",
    ]


def _install_tab_state_bridge(page_defs: list[PageDef]) -> None:
    """Mantiene la tab Streamlit selezionata anche dopo rerun causati da widget."""
    page_ids = [page.page_id for page in page_defs]
    page_ids_json = json.dumps(page_ids)
    html = f"""<script>
(function(){{
  var storageKey = {json.dumps(_TAB_STATE_STORAGE_KEY)};
  var pageIds = {page_ids_json};
  function parentDoc(){{ try{{ return window.parent.document; }}catch(e){{ return document; }} }}
  function tabs(){{
    var d = parentDoc();
    var tabList = d.querySelector('[role="tablist"]');
    if(!tabList) return [];
    return Array.from(tabList.querySelectorAll('[role="tab"]'));
  }}
  function selectedIndex(items){{
    return items.findIndex(function(t){{ return t.getAttribute('aria-selected') === 'true'; }});
  }}
  function saveIndex(idx){{
    if(idx < 0 || idx >= pageIds.length) return;
    try{{ window.parent.sessionStorage.setItem(storageKey, String(idx)); }}catch(e){{}}
  }}
  function readIndex(){{
    try{{
      var raw = window.parent.sessionStorage.getItem(storageKey);
      var idx = parseInt(raw || '', 10);
      if(Number.isFinite(idx) && idx >= 0 && idx < pageIds.length) return idx;
    }}catch(e){{}}
    return null;
  }}
  function bindAndRestore(){{
    var items = tabs();
    if(!items.length) return;
    items.forEach(function(tab, idx){{
      if(tab.dataset.sestanteTabBridge === '1') return;
      tab.dataset.sestanteTabBridge = '1';
      tab.addEventListener('click', function(){{ saveIndex(idx); }}, true);
    }});
    var wanted = readIndex();
    var current = selectedIndex(items);
    if(wanted !== null && wanted !== current && items[wanted]){{
      items[wanted].click();
    }} else if(current >= 0) {{
      saveIndex(current);
    }}
  }}
  [0, 60, 180, 360, 720, 1200].forEach(function(delay){{ setTimeout(bindAndRestore, delay); }});
}})();
</script>"""
    _render_inline_script(html)


def trigger_tab_navigation() -> None:
    try:
        total_pages = max(1, int(st.session_state.get("total_pages", 1) or 1))
    except Exception:
        total_pages = 1
    active_index = _clamp_active_tab_index([PageDef(str(i), str(i), lambda *_: None) for i in range(total_pages)])
    html = f"""<script>
(function(){{
  var storageKey = {json.dumps(_TAB_STATE_STORAGE_KEY)};
  var targetIndex = {active_index};
  try{{ window.parent.sessionStorage.setItem(storageKey, String(targetIndex)); }}catch(e){{}}
  function clickTargetTab(){{
    try{{
      var d=window.parent.document;
      var tabList=d.querySelector('[role="tablist"]');
      if(!tabList) return;
      var tabs=Array.from(tabList.querySelectorAll('[role="tab"]'));
      if(tabs[targetIndex] && tabs[targetIndex].getAttribute('aria-selected') !== 'true'){{ tabs[targetIndex].click(); }}
    }}catch(e){{}}
  }}
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
  clickTargetTab();
  scrollTop();
  setTimeout(clickTargetTab, 80);
  setTimeout(scrollTop, 80);
  setTimeout(clickTargetTab, 320);
  setTimeout(scrollTop, 320);
  setTimeout(clickTargetTab, 600);
  setTimeout(scrollTop, 600);
}})();
</script>"""
    _render_inline_script(html)


def _clamp_active_tab_index(page_defs: list[PageDef]) -> int:
    active_tab = st.session_state.get("active_tab", 0)
    try:
        index = int(active_tab)
    except (TypeError, ValueError):
        index = 0
    return max(0, min(index, max(len(page_defs) - 1, 0)))


def _format_final_progress_text(*, render_started_at: float, run_started_at: float | None) -> str:
    ui_elapsed = time.perf_counter() - render_started_at
    if run_started_at is None:
        return f"Dashboard pronta - UI {ui_elapsed:.1f}s"
    total_elapsed = time.perf_counter() - run_started_at
    return f"Dashboard pronta - UI {ui_elapsed:.1f}s - totale run {total_elapsed:.1f}s"


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
    progress_start_pct: int = 0,
    progress_span_pct: int = 100,
) -> None:
    t0 = time.perf_counter()
    progress_base = max(0, min(int(progress_start_pct), 99))
    progress_span = max(1, min(int(progress_span_pct), 100 - progress_base))
    percent_before = progress_base + int(((step - 1) / max(total, 1)) * progress_span)
    elapsed_before = time.perf_counter() - render_started_at
    if render_progress is not None:
        render_progress.progress(percent_before, text=f"Rendering {label}... UI {elapsed_before:.1f}s")
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
        if app_logger is not None:
            try:
                app_logger.info(
                    "[PAGE_RENDER] step=%s/%s label=%s status=%s elapsed=%.3fs ui_elapsed=%.3fs",
                    step,
                    total,
                    label,
                    status,
                    elapsed,
                    time.perf_counter() - render_started_at,
                )
            except Exception:
                pass
        percent_after = progress_base + int((step / max(total, 1)) * progress_span)
        elapsed_after = time.perf_counter() - render_started_at
        if render_progress is not None:
            render_progress.progress(
                percent_after,
                text=(f"Completato: {label} - UI {elapsed_after:.1f}s" if status == "OK" else f"Errore: {label} - UI {elapsed_after:.1f}s"),
            )
        if sidebar_progress is not None:
            sidebar_progress.progress(
                max(1, percent_after),
                text=(f"Debug sidebar: {label} OK" if status == "OK" else f"Debug sidebar: {label} errore"),
            )


def _render_standard_tabs(
    page_defs: list[PageDef],
    ctx: Any,
    *,
    render_started_at: float | None = None,
    render_progress=None,
    render_steps: list[tuple[str, Any, Any]] | None = None,
    app_logger=None,
) -> None:
    tab_targets = st.tabs([page.label for page in page_defs])
    _install_tab_state_bridge(page_defs)
    total_render_steps = len(page_defs)
    for idx, (page, target) in enumerate(zip(page_defs, tab_targets), start=1):
        st.session_state["current_page_index"] = idx - 1
        st.session_state["current_page_total"] = len(page_defs)
        st.session_state["current_page_id"] = page.page_id
        if render_progress is not None and render_started_at is not None and render_steps is not None and app_logger is not None:
            _render_page_step(
                label=page.label,
                step=idx,
                total=total_render_steps,
                render_func=page.renderer,
                target=target,
                context=ctx,
                render_started_at=render_started_at,
                render_progress=render_progress,
                render_steps=render_steps,
                app_logger=app_logger,
                progress_start_pct=8,
                progress_span_pct=90,
            )
        else:
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
    profiling_cache_condition: str = "n/d",
    profiling_signature_diff_lines: list[str] | None = None,
    debug_render_scope: str = "current_page",
    operational_render_scope: str = "full_tabs",
    operational_reason: str = "",
    operational_origin_page_id: str = "",
    operational_origin_page_index: int | None = None,
    dirty_flags: dict[str, bool] | None = None,
    progress_host=None,
    run_started_at: float | None = None,
) -> None:
    render_started_at = time.perf_counter()
    render_steps: list[tuple[str, Any, Any]] = []
    reset_render_profile()
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
            render_progress = (progress_host or st).progress(0, text="Preparazione interfaccia...")
        except Exception:
            render_progress = st.progress(0, text="Preparazione interfaccia...")

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
            render_progress.progress(3, text=f"Rendering Overview / KPI iniziali... UI {render_elapsed:.1f}s")
        render_overview(st.container(), ctx)
        render_elapsed = time.perf_counter() - render_started_at
        if render_progress is not None:
            render_progress.progress(8, text=f"Completato: Overview / KPI iniziali - UI {render_elapsed:.1f}s")
    else:
        render_elapsed = time.perf_counter() - render_started_at
        if render_progress is not None:
            render_progress.progress(3, text=f"Rendering Overview / KPI iniziali... UI {render_elapsed:.1f}s")
        render_overview(st.container(), ctx)
        render_elapsed = time.perf_counter() - render_started_at
        if render_progress is not None:
            render_progress.progress(8, text=f"Completato: Overview / KPI iniziali - UI {render_elapsed:.1f}s")
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
            progress_start_pct=8,
            progress_span_pct=90,
        )
        render_elapsed_total = time.perf_counter() - render_started_at
        if render_progress is not None:
            render_progress.progress(100, text=_format_final_progress_text(render_started_at=render_started_at, run_started_at=run_started_at))
        if debug_log_enabled:
            try:
                skipped_pages = _format_skipped_pages(page_defs, active_page.page_id)
                render_lines = [
                    "=== PORTFOLIO DASHBOARD — RENDER LOG ===",
                    "versione_log: render-log-v1+deep-v4",
                    "diagnostic_features: data_page_internal_profile,copy_download_twin_actions,current_run_history",
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
                    f"profiling_scenario: {profiling_scenario or 'n/d'}",
                    f"profiling_cache_condition: {profiling_cache_condition or 'n/d'}",
                    *_runtime_continuity_lines(),
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
                        "Render pagina singola: viene renderizzata solo la pagina corrente selezionata dalla sidebar.",
                        "La modalita completa resta disponibile solo per diagnostica/sweep o scelta esplicita.",
                    ]
                )
                render_log_text = "\n".join(render_lines)
                if render_log is not None:
                    render_log.caption("Tempi rendering pagine — rerun operativo leggero.")
                    with st.expander("📋 Log testuale rendering / performance", expanded=False):
                        _render_copyable_render_log(render_log_text, key="render_log_operational")
            except Exception as exc:
                app_logger.warning("Impossibile mostrare log rendering operativo: %s", exc)
    elif debug_full_sweep:
        tab_targets = st.tabs([page.label for page in page_defs])
        _install_tab_state_bridge(page_defs)
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
                progress_start_pct=8,
                progress_span_pct=90,
            )

        render_elapsed_total = time.perf_counter() - render_started_at
        if render_progress is not None:
            render_progress.progress(100, text=_format_final_progress_text(render_started_at=render_started_at, run_started_at=run_started_at))
        try:
            render_lines = [
                "=== PORTFOLIO DASHBOARD — RENDER LOG ===",
                "versione_log: render-log-v1+deep-v4",
                "diagnostic_features: data_page_internal_profile,copy_download_twin_actions,current_run_history",
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
                f"profiling_scenario: {profiling_scenario or 'n/d'}",
                f"profiling_cache_condition: {profiling_cache_condition or 'n/d'}",
                *_runtime_continuity_lines(),
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
                        "profiling_cache_condition": profiling_cache_condition,
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
                    _render_copyable_render_log(render_log_text, key="render_log_full_sweep")
        except Exception as exc:
            app_logger.warning("Impossibile mostrare log rendering dettagliato: %s", exc)
    elif debug_enabled:
        tab_targets = st.tabs([page.label for page in page_defs])
        _install_tab_state_bridge(page_defs)
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
                progress_start_pct=8,
                progress_span_pct=90,
            )
        render_elapsed_total = time.perf_counter() - render_started_at
        if render_progress is not None:
            render_progress.progress(100, text=_format_final_progress_text(render_started_at=render_started_at, run_started_at=run_started_at))
        if debug_log_enabled:
            try:
                render_lines = [
                    "=== PORTFOLIO DASHBOARD — RENDER LOG ===",
                    "versione_log: render-log-v1+deep-v4",
                    "diagnostic_features: data_page_internal_profile,copy_download_twin_actions,current_run_history",
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
                    f"profiling_scenario: {profiling_scenario or 'n/d'}",
                    f"profiling_cache_condition: {profiling_cache_condition or 'n/d'}",
                    *_runtime_continuity_lines(),
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
                            "profiling_cache_condition": profiling_cache_condition,
                            "profiling_mode": "ui_full_tabs",
                        },
                    )
                except Exception as exc:
                    app_logger.warning("Impossibile salvare storico render debug: %s", exc)
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
                        _render_copyable_render_log(render_log_text, key="render_log_debug")
            except Exception as exc:
                app_logger.warning("Impossibile mostrare log rendering dettagliato: %s", exc)
    else:
        _render_standard_tabs(
            page_defs,
            ctx,
            render_started_at=render_started_at,
            render_progress=render_progress,
            render_steps=render_steps,
            app_logger=app_logger,
        )
        render_elapsed_total = time.perf_counter() - render_started_at
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
                    "profiling_cache_condition": profiling_cache_condition,
                    "profiling_mode": "standard_full_tabs",
                },
            )
        except Exception as exc:
            app_logger.warning("Impossibile salvare storico render standard: %s", exc)
        try:
            app_logger.info(
                "[DASHBOARD_RENDER] mode=standard_full_tabs pages=%s elapsed=%.3fs",
                len(render_steps),
                render_elapsed_total,
            )
        except Exception:
            pass
        if render_progress is not None:
            render_progress.progress(100, text=_format_final_progress_text(render_started_at=render_started_at, run_started_at=run_started_at))
