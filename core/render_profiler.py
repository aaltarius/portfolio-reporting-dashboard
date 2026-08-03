"""
core/render_profiler.py — profilatore leggero runtime Streamlit.

Serve a capire quali sotto-sezioni delle pagine lente assorbono tempo.
Non modifica dati, cache, grafici o calcoli: registra solo tempi in st.session_state.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import json
import statistics
import time
from pathlib import Path
from typing import Any, Iterator

import streamlit as st

from persistence.storage import DATA_DIR

_RENDER_PROFILE_KEY = "_portfolio_render_profile_events"
_RENDER_PROFILE_VERSION = "deep-render-log-v3+tree"
_RENDER_PROFILE_STACK_KEY = "_portfolio_render_profile_stack"
_RENDER_PROFILE_COUNTER_KEY = "_portfolio_render_profile_event_counter"
_RENDER_PROFILE_HISTORY_FILE = Path(DATA_DIR) / "logs" / "render_profile_history.jsonl"
_PRE_RENDER_EVENTS_FILE = Path(DATA_DIR) / "logs" / "pre_render_events.json"
_RENDER_PROFILE_HISTORY_MAX_RUNS = 120


def _build_render_event(
    page: str,
    step: str,
    elapsed: float,
    *,
    status: str = "OK",
    detail: str = "",
    count: int | None = None,
    event_id: str = "",
    parent_event_id: str = "",
    depth: int = 0,
) -> dict[str, Any]:
    return {
        "version": _RENDER_PROFILE_VERSION,
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "page": str(page),
        "step": str(step),
        "elapsed": float(elapsed or 0.0),
        "status": str(status or "OK"),
        "detail": str(detail or ""),
        "count": count,
        "event_id": str(event_id or ""),
        "parent_event_id": str(parent_event_id or ""),
        "depth": int(depth or 0),
    }


def _next_render_event_id() -> str:
    try:
        current = int(st.session_state.get(_RENDER_PROFILE_COUNTER_KEY, 0) or 0) + 1
        st.session_state[_RENDER_PROFILE_COUNTER_KEY] = current
        return f"evt-{current:05d}"
    except Exception:
        return f"evt-{int(time.time() * 1000000)}"


def _get_profile_stack() -> list[dict[str, Any]]:
    try:
        stack = st.session_state.get(_RENDER_PROFILE_STACK_KEY, [])
        if isinstance(stack, list):
            return stack
    except Exception:
        pass
    return []


def _push_profile_stack(item: dict[str, Any]) -> None:
    try:
        stack = _get_profile_stack()
        stack.append(item)
        st.session_state[_RENDER_PROFILE_STACK_KEY] = stack
    except Exception:
        return


def _pop_profile_stack(event_id: str) -> None:
    try:
        stack = _get_profile_stack()
        if stack and str(stack[-1].get("event_id") or "") == str(event_id or ""):
            stack.pop()
        else:
            stack = [item for item in stack if str(item.get("event_id") or "") != str(event_id or "")]
        st.session_state[_RENDER_PROFILE_STACK_KEY] = stack
    except Exception:
        return


def _current_parent() -> tuple[str, int]:
    stack = _get_profile_stack()
    if not stack:
        return "", 0
    return str(stack[-1].get("event_id") or ""), len(stack)


def _build_pre_render_payload(signature: str, events: list[dict[str, Any]], *, cycle_id: str | None = None) -> dict[str, Any]:
    return {
        "signature": str(signature or ""),
        "cycle_id": str(cycle_id or datetime.now().strftime("%Y%m%d%H%M%S%f")),
        "events": list(events or []),
    }


def reset_render_profile() -> None:
    """Svuota il profilo del render corrente."""
    try:
        st.session_state[_RENDER_PROFILE_KEY] = []
        st.session_state[_RENDER_PROFILE_STACK_KEY] = []
        st.session_state[_RENDER_PROFILE_COUNTER_KEY] = 0
    except Exception:
        return


def _load_persisted_pre_render_events(signature: str | None = None) -> list[dict[str, Any]]:
    try:
        if not _PRE_RENDER_EVENTS_FILE.exists():
            return []
        payload = json.loads(_PRE_RENDER_EVENTS_FILE.read_text(encoding="utf-8"))
        stored_signature = str(payload.get("signature") or "")
        if signature is not None and stored_signature != str(signature or ""):
            return []
        events = payload.get("events", [])
        return events if isinstance(events, list) else []
    except Exception:
        return []


def _load_persisted_pre_render_payload(signature: str | None = None) -> dict[str, Any]:
    try:
        if not _PRE_RENDER_EVENTS_FILE.exists():
            return {}
        payload = json.loads(_PRE_RENDER_EVENTS_FILE.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {}
        stored_signature = str(payload.get("signature") or "")
        if signature is not None and stored_signature != str(signature or ""):
            return {}
        events = payload.get("events", [])
        payload["events"] = events if isinstance(events, list) else []
        payload["signature"] = stored_signature
        payload["cycle_id"] = str(payload.get("cycle_id") or "")
        return payload
    except Exception:
        return {}


def persist_pre_render_event(
    signature: str,
    page: str,
    step: str,
    elapsed: float,
    *,
    status: str = "OK",
    detail: str = "",
    count: int | None = None,
    reset_cycle: bool = False,
) -> None:
    try:
        current_signature = str(signature or "")
        event = _build_render_event(
            page,
            step,
            elapsed,
            status=status,
            detail=detail,
            count=count,
        )
        payload = _load_persisted_pre_render_payload(current_signature)
        stored_signature = str(payload.get("signature") or "")
        if reset_cycle or stored_signature != current_signature:
            payload = _build_pre_render_payload(current_signature, [event])
        else:
            events = payload.get("events", [])
            events = events if isinstance(events, list) else []
            events.append(event)
            payload = _build_pre_render_payload(
                current_signature,
                events,
                cycle_id=str(payload.get("cycle_id") or ""),
            )
        _PRE_RENDER_EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PRE_RENDER_EVENTS_FILE.write_text(
            json.dumps(payload, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    except Exception:
        return


def get_render_profile_events(*, persisted_pre_render_signature: str | None = None) -> list[dict[str, Any]]:
    """Restituisce gli eventi del render corrente."""
    events: list[dict[str, Any]] = []
    try:
        current = st.session_state.get(_RENDER_PROFILE_KEY, [])
        if isinstance(current, list):
            events.extend(current)
    except Exception:
        pass
    persisted = _load_persisted_pre_render_events(persisted_pre_render_signature)
    if persisted:
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in [*persisted, *events]:
            try:
                marker = json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
            except Exception:
                marker = str(item)
            if marker in seen:
                continue
            seen.add(marker)
            deduped.append(item)
        return deduped
    return events


def record_render_event(
    page: str,
    step: str,
    elapsed: float,
    *,
    status: str = "OK",
    detail: str = "",
    count: int | None = None,
    event_id: str = "",
    parent_event_id: str | None = None,
    depth: int | None = None,
) -> None:
    """Registra un singolo evento di performance."""
    try:
        if not event_id:
            event_id = _next_render_event_id()
        if parent_event_id is None or depth is None:
            parent_from_stack, depth_from_stack = _current_parent()
            if parent_event_id is None:
                parent_event_id = parent_from_stack
            if depth is None:
                depth = depth_from_stack
        events = get_render_profile_events()
        events.append(
            _build_render_event(
                page,
                step,
                elapsed,
                status=status,
                detail=detail,
                count=count,
                event_id=event_id,
                parent_event_id=str(parent_event_id or ""),
                depth=int(depth or 0),
            )
        )
        st.session_state[_RENDER_PROFILE_KEY] = events
    except Exception:
        return


@contextmanager
def profile_step(page: str, step: str, *, detail: str = "", count: int | None = None) -> Iterator[None]:
    """Context manager per misurare una sotto-fase del render.

    Dalla versione deep-render-log-v3 registra anche parent/depth, così il log
    può distinguere tempo totale, tempo dei figli e tempo esclusivo non ancora
    scomposto da ulteriori profile_step.
    """
    parent_event_id, depth = _current_parent()
    event_id = _next_render_event_id()
    _push_profile_stack({"event_id": event_id, "page": str(page), "step": str(step)})
    t0 = time.perf_counter()
    status = "OK"
    err = ""
    try:
        yield
    except Exception as exc:
        status = "ERRORE"
        err = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        elapsed = time.perf_counter() - t0
        _pop_profile_stack(event_id)
        final_detail = detail
        if err:
            final_detail = (final_detail + " | " if final_detail else "") + err
        record_render_event(
            page,
            step,
            elapsed,
            status=status,
            detail=final_detail,
            count=count,
            event_id=event_id,
            parent_event_id=parent_event_id,
            depth=depth,
        )



def _canonical_page_name(label: str) -> str:
    raw = str(label or "").strip()
    known_pages = [
        ("Quotazioni", "Quotazioni"),
        ("Portafoglio", "Portafoglio"),
        ("Operazioni", "Operazioni"),
        ("Cruscotti", "Cruscotti"),
        ("Mercati", "Mercati"),
        ("Summary", "Summary"),
        ("Confronto", "Confronto"),
        ("Pianificazione", "Pianificazione"),
        ("Gestione Dati", "Dati"),
        ("Dati", "Dati"),
        ("AI", "AI"),
        ("Impostazioni", "Setup"),
        ("Setup", "Setup"),
    ]
    raw_lower = raw.lower()
    for token, canonical in known_pages:
        if token.lower() in raw_lower:
            return canonical
    return raw


def _root_page_for_event(page: str) -> str:
    raw = str(page or "n/d").split("/", 1)[0]
    return _canonical_page_name(raw)


def render_profile_coverage_text(
    page_steps: list[tuple[str, float, int, str, str]],
    *,
    persisted_pre_render_signature: str | None = None,
) -> str:
    """Confronta tempi pagina e sotto-fasi radice per evidenziare tempo non profilato.

    È una diagnostica: non altera cache, dati o UI. Serve a capire se una
    pagina lenta è lenta dentro step già misurati oppure in codice non ancora
    avvolto da profile_step.
    """
    events = get_render_profile_events(persisted_pre_render_signature=persisted_pre_render_signature)
    root_by_page: dict[str, float] = {}
    all_by_page: dict[str, float] = {}
    for event in events:
        page = _root_page_for_event(str(event.get("page") or "n/d"))
        elapsed = float(event.get("elapsed", 0.0) or 0.0)
        all_by_page[page] = all_by_page.get(page, 0.0) + elapsed
        if not str(event.get("parent_event_id") or ""):
            root_by_page[page] = root_by_page.get(page, 0.0) + elapsed

    lines: list[str] = []
    lines.append("=== COPERTURA PROFILING PAGINE ===")
    lines.append("Lettura: gap alto = tempo della pagina non spiegato da sotto-fasi radice; overlap alto = sotto-fasi annidate sommate più volte.")
    lines.append("Pagina                     | pagina | root_step | gap_non_profilato | tutte_sottofasi | overlap_annidato")
    for label, elapsed, _step, status, _error_msg in page_steps:
        page = _canonical_page_name(str(label))
        page_elapsed = float(elapsed or 0.0)
        root_elapsed = float(root_by_page.get(page, 0.0) or 0.0)
        all_elapsed = float(all_by_page.get(page, 0.0) or 0.0)
        gap = page_elapsed - root_elapsed
        overlap = all_elapsed - root_elapsed
        lines.append(
            f"{page:<26} | {page_elapsed:6.3f}s | {root_elapsed:8.3f}s | {gap:16.3f}s | {all_elapsed:13.3f}s | {overlap:15.3f}s"
            + (f" | {status}" if status != "OK" else "")
        )
    return "\n".join(lines)


def render_profile_tree_text(*, min_seconds: float = 0.0, persisted_pre_render_signature: str | None = None, limit: int = 40) -> str:
    """Riepilogo degli eventi con tempo esclusivo, utile per trovare l'arcano."""
    events = [
        e for e in get_render_profile_events(persisted_pre_render_signature=persisted_pre_render_signature)
        if float(e.get("elapsed", 0.0) or 0.0) >= min_seconds
    ]
    if not events:
        return "=== PROFILING AD ALBERO / TEMPO ESCLUSIVO ===\nNessun evento disponibile."

    child_sum: dict[str, float] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for event in events:
        event_id = str(event.get("event_id") or "")
        if event_id:
            by_id[event_id] = event
        parent_id = str(event.get("parent_event_id") or "")
        if parent_id:
            child_sum[parent_id] = child_sum.get(parent_id, 0.0) + float(event.get("elapsed", 0.0) or 0.0)

    rows: list[tuple[float, float, float, int, str, str, str, int | None]] = []
    for event in events:
        elapsed = float(event.get("elapsed", 0.0) or 0.0)
        event_id = str(event.get("event_id") or "")
        children = child_sum.get(event_id, 0.0)
        exclusive = max(0.0, elapsed - children)
        rows.append((exclusive, elapsed, children, int(event.get("depth", 0) or 0), str(event.get("page") or "n/d"), str(event.get("step") or ""), str(event.get("detail") or ""), event.get("count")))

    lines = ["=== PROFILING AD ALBERO / TEMPO ESCLUSIVO ==="]
    lines.append("Lettura: esclusivo alto = lavoro dentro quello step non ancora scomposto; figli alto = tempo già spiegato da sotto-step annidati.")
    lines.append("Evento                                              | totale | figli | esclusivo | depth | count | dettaglio")
    for exclusive, elapsed, children, depth, page, step, detail, count in sorted(rows, key=lambda r: (r[0], r[1]), reverse=True)[: max(1, int(limit))]:
        indent = "  " * min(depth, 4)
        count_txt = "" if count is None else str(count)
        detail_txt = detail[:90]
        label = f"{indent}{page} / {step}"[:52]
        lines.append(f"{label:<52} | {elapsed:6.3f}s | {children:5.3f}s | {exclusive:9.3f}s | {depth:5d} | {count_txt:<5} | {detail_txt}")
    return "\n".join(lines)


def _format_bool_it(value: Any) -> str:
    return "sì" if bool(value) else "no"


def render_invalidation_plan_text() -> str:
    """Rende nel log il piano diagnostico di invalidazione/cache dell'ultimo evento.

    Non decide nulla: legge quanto registrato da core.cache.record_cache_decision
    e lo presenta accanto al render log per capire se le cache invalidate sono
    coerenti con la mutazione reale.
    """
    try:
        plan = st.session_state.get("_portfolio_last_cache_decision", {})
    except Exception:
        plan = {}
    if not isinstance(plan, dict) or not plan:
        return "=== INVALIDATION PLAN / CACHE IMPACT ===\nNessuna decisione cache registrata in questo ciclo."

    details = plan.get("mutation_details") if isinstance(plan.get("mutation_details"), dict) else {}
    dirty_active = plan.get("dirty_active") if isinstance(plan.get("dirty_active"), list) else []
    changed_tickers = plan.get("changed_tickers") if isinstance(plan.get("changed_tickers"), list) else []
    changed_categories = plan.get("changed_categories") if isinstance(plan.get("changed_categories"), list) else []
    dep_rows = plan.get("dependency_plan") if isinstance(plan.get("dependency_plan"), list) else []
    notes = plan.get("notes") if isinstance(plan.get("notes"), list) else []

    lines: list[str] = []
    lines.append("=== INVALIDATION PLAN / CACHE IMPACT ===")
    lines.append(f"versione: {plan.get('version', 'n/d')}")
    lines.append(f"timestamp_decisione: {plan.get('timestamp', 'n/d')}")
    lines.append(f"reason: {plan.get('reason', 'n/d')}")
    lines.append(f"invalidated: {_format_bool_it(plan.get('invalidated'))}")
    lines.append(f"token: {plan.get('token', 0)}")
    lines.append(f"force_reload: {_format_bool_it(plan.get('force_reload'))}")
    lines.append(f"scenario: {plan.get('scenario') or 'n/d'}")
    lines.append(f"render_scope_richiesto: {plan.get('render_scope_requested') or 'n/d'}")
    warning = str(plan.get("render_scope_warning") or "")
    if warning:
        lines.append(f"warning_scope: {warning}")
    lines.append(f"dirty_flags_attivi: {', '.join(str(x) for x in dirty_active) if dirty_active else 'none'}")
    lines.append(f"figure_session_clear: {_format_bool_it(plan.get('figure_session_clear'))}")
    lines.append("")
    lines.append("--- Mutazione reale dichiarata ---")
    lines.append(f"event_type: {details.get('event_type') or 'n/d'}")
    lines.append(f"material_change: {_format_bool_it(details.get('material_change'))}")
    lines.append(f"changed_count: {plan.get('changed_count', 0)}")
    lines.append(f"changed_tickers: {', '.join(str(x) for x in changed_tickers) if changed_tickers else 'none'}")
    lines.append(f"changed_categories: {', '.join(str(x) for x in changed_categories) if changed_categories else 'none'}")
    if details.get("benchmarks_refreshed") is not None:
        lines.append(f"benchmarks_refreshed: {details.get('benchmarks_refreshed')}")
    if details.get("material_quote_diffs"):
        diffs = details.get("material_quote_diffs")
        if isinstance(diffs, list):
            lines.append("material_quote_diffs: " + "; ".join(str(x) for x in diffs[:12]))
    changes = details.get("changed_instruments")
    if isinstance(changes, list) and changes:
        lines.append("strumenti_cambiati_dettaglio:")
        for item in changes[:12]:
            if not isinstance(item, dict):
                lines.append(f"  - {item}")
                continue
            lines.append(
                "  - "
                f"{item.get('ticker', 'n/d')} | categoria={item.get('categoria', 'n/d')} | "
                f"old={item.get('old_price', 'n/d')} -> new={item.get('new_price', 'n/d')} | "
                f"delta={item.get('delta_abs', 'n/d')} ({item.get('delta_pct', 'n/d')})"
            )
    lines.append("")
    lines.append("--- Cache / bundle invalidati secondo dirty_flags attuali ---")
    lines.append("cache                         | invalida | trigger_flags                         | descrizione")
    for row in dep_rows:
        if not isinstance(row, dict):
            continue
        triggers = row.get("trigger_flags") if isinstance(row.get("trigger_flags"), list) else []
        lines.append(
            f"{str(row.get('cache') or ''):<29} | {_format_bool_it(row.get('invalidate')):<8} | "
            f"{(', '.join(str(x) for x in triggers) if triggers else '—'):<37} | {row.get('description') or ''}"
        )
    if notes:
        lines.append("")
        lines.append("--- Note diagnostiche ---")
        for note in notes:
            lines.append(f"- {note}")
    lines.append("")
    lines.append("Lettura: questa sezione non ottimizza nulla; evidenzia se la mutazione reale giustifica la portata dell'invalidazione.")
    return "\n".join(lines)

def render_profile_text(*, min_seconds: float = 0.0, persisted_pre_render_signature: str | None = None) -> str:
    """Crea un report testuale copiabile degli eventi registrati."""
    events = [
        e
        for e in get_render_profile_events(persisted_pre_render_signature=persisted_pre_render_signature)
        if float(e.get("elapsed", 0.0) or 0.0) >= min_seconds
    ]
    lines: list[str] = []
    lines.append("=== DETTAGLIO SOTTO-FASI — DEEP RENDER LOG ===")
    lines.append(f"versione_log_dettaglio: {_RENDER_PROFILE_VERSION}")
    lines.append(f"eventi_registrati: {len(events)}")
    lines.append("")

    # Cache summary
    cache_hits = len([e for e in events if "cache hit" in str(e.get("detail", "")).lower()])
    cache_misses = len([e for e in events if "cache miss" in str(e.get("detail", "")).lower()])
    if cache_hits or cache_misses:
        lines.append("=== CACHE SUMMARY ===")
        lines.append(f"Cache hits: {cache_hits}")
        lines.append(f"Cache misses: {cache_misses}")
        if cache_hits + cache_misses > 0:
            hit_rate = (cache_hits / (cache_hits + cache_misses)) * 100
            lines.append(f"Hit rate: {hit_rate:.1f}%")
        lines.append("")

    if not events:
        lines.append("Nessun evento di dettaglio registrato.")
        return "\n".join(lines)

    try:
        lines.append(render_profile_tree_text(min_seconds=min_seconds, persisted_pre_render_signature=persisted_pre_render_signature, limit=30))
        lines.append("")
    except Exception:
        pass

    by_page: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        by_page.setdefault(str(e.get("page") or "n/d"), []).append(e)

    for page, page_events in by_page.items():
        total = sum(float(e.get("elapsed", 0.0) or 0.0) for e in page_events)
        lines.append(f"--- {page} | totale sotto-fasi registrate: {total:.3f}s ---")
        for e in sorted(page_events, key=lambda item: float(item.get("elapsed", 0.0) or 0.0), reverse=True):
            detail = str(e.get("detail") or "")
            count = e.get("count")
            count_txt = f" | count={count}" if count is not None else ""
            detail_txt = f" | {detail}" if detail else ""
            lines.append(
                f"{str(e.get('step') or ''):<48} | {float(e.get('elapsed', 0.0) or 0.0):8.3f}s | {e.get('status','OK')}{count_txt}{detail_txt}"
            )
        lines.append("")

    lines.append("--- Lettura benchmark/quotazioni ---")
    lines.append("Se compaiono righe 'scaricamento benchmark yfinance' con tempi alti, la pagina Quotazioni sta ancora interrogando la rete per i benchmark.")
    lines.append("Se invece le righe benchmark sono 'cache hit' o assenti, il collo di bottiglia è più probabilmente nei grafici Plotly o nei dataframe intermedi.")
    return "\n".join(lines)


def append_render_profile_run(
    *,
    signature: str,
    cohort: str | None = None,
    scenario: str | None = None,
    total_render_seconds: float,
    page_steps: list[tuple[str, float, int, str, str]],
    metadata: dict[str, Any] | None = None,
    persisted_pre_render_signature: str | None = None,
) -> None:
    """Salva un run strutturato su disco per confronti tra esecuzioni con la stessa signature."""
    try:
        payload = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "version": _RENDER_PROFILE_VERSION,
            "signature": str(signature or ""),
            "cohort": str(cohort or signature or ""),
            "scenario": str(scenario or ""),
            "total_render_seconds": float(total_render_seconds or 0.0),
            "pages": [
                {
                    "label": str(label),
                    "elapsed": float(elapsed or 0.0),
                    "step": int(step or 0),
                    "status": str(status or "OK"),
                    "error": str(error_msg or ""),
                }
                for label, elapsed, step, status, error_msg in page_steps
            ],
            "events": get_render_profile_events(persisted_pre_render_signature=persisted_pre_render_signature),
            "metadata": metadata or {},
        }
        _RENDER_PROFILE_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        history_lines: list[str] = []
        if _RENDER_PROFILE_HISTORY_FILE.exists():
            try:
                history_lines = _RENDER_PROFILE_HISTORY_FILE.read_text(encoding="utf-8").splitlines()
            except Exception:
                history_lines = []
        history_lines.append(json.dumps(payload, ensure_ascii=False, default=str))
        if len(history_lines) > _RENDER_PROFILE_HISTORY_MAX_RUNS:
            history_lines = history_lines[-_RENDER_PROFILE_HISTORY_MAX_RUNS:]
        _RENDER_PROFILE_HISTORY_FILE.write_text("\n".join(history_lines) + "\n", encoding="utf-8")
    except Exception:
        pass


def render_profile_history_text(*, cohort: str, limit: int = 12) -> str:
    """Riepilogo storico degli ultimi run della stessa cohort, per isolare i colli di bottiglia reali."""
    lines: list[str] = []
    lines.append("=== STORICO RENDER COMPARABILI ===")
    lines.append(f"cohort_filtro: {cohort}")
    if not _RENDER_PROFILE_HISTORY_FILE.exists():
        lines.append("Storico non ancora disponibile.")
        return "\n".join(lines)

    runs: list[dict[str, Any]] = []
    try:
        for raw in _RENDER_PROFILE_HISTORY_FILE.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            item = json.loads(raw)
            item_cohort = str(item.get("cohort", item.get("signature", "")) or "")
            if item_cohort == str(cohort or ""):
                runs.append(item)
    except Exception as exc:
        lines.append(f"Errore lettura storico: {type(exc).__name__}: {exc}")
        return "\n".join(lines)

    if not runs:
        lines.append("Nessun run precedente con questa signature.")
        return "\n".join(lines)

    runs = runs[-max(1, int(limit)):]
    totals = [float(r.get("total_render_seconds", 0.0) or 0.0) for r in runs]
    totals_sorted = sorted(totals)
    p95_idx = min(len(totals_sorted) - 1, max(0, int(round((len(totals_sorted) - 1) * 0.95))))
    lines.append(f"run_considerati: {len(runs)}")
    scenario_counts: dict[str, int] = {}
    for run in runs:
        scenario = str(run.get("scenario") or "n/d")
        scenario_counts[scenario] = scenario_counts.get(scenario, 0) + 1
    if scenario_counts:
        scenario_txt = ", ".join(f"{k}={v}" for k, v in sorted(scenario_counts.items()))
        lines.append(f"scenari: {scenario_txt}")
    total_median = statistics.median(totals)
    latest_total = totals[-1] if totals else 0.0
    latest_delta = latest_total - total_median
    lines.append(
        f"totale_render median={total_median:.3f}s min={min(totals_sorted):.3f}s max={max(totals_sorted):.3f}s p95={totals_sorted[p95_idx]:.3f}s"
    )
    lines.append(
        f"ultimo_run={latest_total:.3f}s delta_vs_mediana={latest_delta:+.3f}s"
    )
    lines.append("")

    latest_run = runs[-1] if runs else {}
    latest_event_keys: set[str] = set()
    for event in latest_run.get("events", []) or []:
        latest_event_keys.add(f"{str(event.get('page') or 'n/d')} / {str(event.get('step') or 'n/d')}")

    page_samples: dict[str, list[float]] = {}
    event_samples: dict[str, list[float]] = {}
    for run in runs:
        for page in run.get("pages", []) or []:
            page_samples.setdefault(str(page.get("label") or "n/d"), []).append(float(page.get("elapsed", 0.0) or 0.0))
        for event in run.get("events", []) or []:
            key = f"{str(event.get('page') or 'n/d')} / {str(event.get('step') or 'n/d')}"
            event_samples.setdefault(key, []).append(float(event.get("elapsed", 0.0) or 0.0))

    lines.append("--- Pagine più variabili / costose ---")
    page_rows = []
    for label, samples in page_samples.items():
        if not samples:
            continue
        med = statistics.median(samples)
        mx = max(samples)
        mn = min(samples)
        spread = mx - mn
        page_rows.append((med, spread, label, mn, mx))
    for med, spread, label, mn, mx in sorted(page_rows, key=lambda x: (x[0], x[1]), reverse=True)[:8]:
        lines.append(f"{label:<18} median={med:6.3f}s min={mn:6.3f}s max={mx:6.3f}s spread={spread:6.3f}s")
    lines.append("")

    lines.append("--- Sotto-fasi attive più costose ---")
    lines.append("Filtro: mostra solo eventi ancora presenti nell'ultimo run, cosi' i vecchi step rimossi non restano falsi colli di bottiglia.")
    event_rows = []
    for key, samples in event_samples.items():
        if latest_event_keys and key not in latest_event_keys:
            continue
        if not samples:
            continue
        med = statistics.median(samples)
        mx = max(samples)
        mn = min(samples)
        spread = mx - mn
        if med <= 0 and mx <= 0:
            continue
        event_rows.append((med, spread, key, mn, mx))
    if event_rows:
        for med, spread, key, mn, mx in sorted(event_rows, key=lambda x: (x[0], x[1]), reverse=True)[:12]:
            lines.append(f"{key:<54} median={med:6.3f}s min={mn:6.3f}s max={mx:6.3f}s spread={spread:6.3f}s")
    else:
        lines.append("Nessuna sotto-fase attiva con tempo significativo nell'ultimo run.")
    lines.append("")
    lines.append("Lettura: i colli di bottiglia reali sono quelli attivi nell'ultimo run e con mediana alta su più run comparabili.")
    return "\n".join(lines)
