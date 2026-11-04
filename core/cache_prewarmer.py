"""
core/cache_prewarmer.py — Pre-warming background della cache figure.
"""
from __future__ import annotations
import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from persistence.storage import DATA_DIR
from core.settings_profiles import get_pre_render_settings
from core.render_profiler import persist_pre_render_event, record_render_event

_prewarm_lock = threading.Lock()
_prewarm_thread: threading.Thread | None = None
_PREWARM_COOLDOWN_SECONDS = 1800  # 30 minuti
_PREWARM_STATE_FILE = Path(DATA_DIR) / "cache" / "prewarm_state.txt"
logger = logging.getLogger("portafoglio.core.cache_prewarmer")


def _record_prewarm_event(step: str, elapsed: float, *, status: str = "OK", detail: str = "", count: int | None = None) -> None:
    try:
        record_render_event("PreRender", step, elapsed, status=status, detail=detail, count=count)
    except Exception:
        return


def _persist_prewarm_event(signature: str, step: str, elapsed: float, *, status: str = "OK", detail: str = "", count: int | None = None) -> None:
    try:
        persist_pre_render_event(signature, "PreRender", step, elapsed, status=status, detail=detail, count=count)
    except Exception:
        return


def _read_prewarm_state() -> dict[str, Any]:
    """Legge stato e firma dell'ultima run di pre-warming dal file di stato."""
    try:
        if _PREWARM_STATE_FILE.exists():
            raw = _PREWARM_STATE_FILE.read_text().strip()
            if not raw:
                return {"ts": 0.0, "signature": ""}
            if raw.startswith("{"):
                data = json.loads(raw)
                return {
                    "ts": float(data.get("ts", 0.0) or 0.0),
                    "signature": str(data.get("signature", "") or ""),
                }
            return {"ts": float(raw), "signature": ""}
    except Exception as exc:
        logger.debug("Lettura prewarm state fallita: %s", exc)
    return {"ts": 0.0, "signature": ""}


def _write_prewarm_state(ts: float, signature: str = "") -> None:
    try:
        _PREWARM_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PREWARM_STATE_FILE.write_text(json.dumps({"ts": float(ts), "signature": str(signature or "")}))
    except Exception as exc:
        logger.warning("Scrittura prewarm state fallita: %s", exc)


def compute_prewarm_signature(ctx: Any, theme: Any, settings: dict | None = None) -> str:
    """Firma del prewarm per rilanciare la build quando cambia davvero il contenuto utile."""
    from core.cache_signatures import build_portfolio_data_signature, theme_signature, charts_settings_signature, figure_signature

    pre_render_settings = get_pre_render_settings(settings)
    data_sig = build_portfolio_data_signature(
        getattr(ctx, "data", {}),
        app_version=str(getattr(ctx, "app_version", "n/d")),
        schema_version=str(getattr(ctx, "schema_version", "n/d")),
    )
    theme_sig = theme_signature(theme)
    settings_sig = charts_settings_signature("ui/charts/settings.py")
    return figure_signature(
        chart_id="prewarm_bundle",
        data_sig=data_sig,
        theme_sig=theme_sig,
        charts_settings_sig=settings_sig,
        page_mode="Completa",
        extra_params={"scope": pre_render_settings.get("scope", "core_charts_v1")},
    )


def should_prewarm(
    *,
    force: bool = False,
    signature: str | None = None,
    cooldown_seconds: int | None = None,
) -> bool:
    """True se serve un pre-warming per cooldown scaduto o firma cambiata."""
    if force:
        return True
    state = _read_prewarm_state()
    if signature and signature != state.get("signature", ""):
        return True
    cooldown = int(cooldown_seconds or _PREWARM_COOLDOWN_SECONDS)
    elapsed = time.time() - float(state.get("ts", 0.0) or 0.0)
    return elapsed > cooldown


def mark_prewarm_deferred(signature: str | None) -> None:
    """Marca il pre-warm della firma corrente come rinviato/già gestito.

    Serve a evitare che, dopo una mutazione operativa in cui il pre-render è
    stato saltato intenzionalmente, il run immediatamente successivo rilanci
    un pre-render sincrono pesante solo perché la firma è nuova.
    """
    if signature:
        _write_prewarm_state(time.time(), str(signature))


def get_prewarm_status(settings: dict | None = None) -> dict[str, Any]:
    """Stato corrente del pre-warming (per UI Impostazioni)."""
    pre_render_settings = get_pre_render_settings(settings)
    cooldown = int(pre_render_settings.get("cooldown_seconds", _PREWARM_COOLDOWN_SECONDS))
    state = _read_prewarm_state()
    last_ts = float(state.get("ts", 0.0) or 0.0)
    running = _prewarm_thread is not None and _prewarm_thread.is_alive()
    return {
        "running": running,
        "last_run": datetime.fromtimestamp(last_ts).strftime("%d/%m/%Y %H:%M") if last_ts > 0 else "Mai",
        "next_run_in_minutes": max(0, int((cooldown - (time.time() - last_ts)) / 60)),
        "scope": pre_render_settings.get("scope", "core_charts_v1"),
    }


def trigger_background_prewarm(ctx: Any, theme: Any, settings: dict, prewarm_fn: "Callable[..., Any]") -> bool:
    """
    Avvia il pre-warming in background se non già in esecuzione.
    Ritorna True se il thread è stato avviato, False se già in esecuzione.
    """
    global _prewarm_thread
    with _prewarm_lock:
        if _prewarm_thread is not None and _prewarm_thread.is_alive():
            return False
        _prewarm_thread = threading.Thread(
            target=_do_prewarm,
            args=(ctx, theme, settings, prewarm_fn),
            daemon=True,
            name="CachePrewarmer",
        )
        _prewarm_thread.start()
    return True


def run_initial_prewarm(ctx: Any, theme: Any, settings: dict, prewarm_fn: "Callable[..., Any]") -> bool:
    """Esegue il pre-render iniziale in modo sincrono, evitando doppie run concorrenti."""
    with _prewarm_lock:
        if _prewarm_thread is not None and _prewarm_thread.is_alive():
            return False
        _do_prewarm(ctx, theme, settings, prewarm_fn)
    return True


def _do_prewarm(ctx: Any, theme: Any, settings: dict, prewarm_fn: "Callable[..., Any]") -> None:
    """
    Esegue il pre-warming: build e salva su disco le figure principali.
    Usa DISK_ONLY strategy per non inquinare session_state.

    prewarm_fn e' iniettata dal chiamante (app.py) invece di essere importata
    qui: core/ non deve dipendere da ui/ (violazione di layering corretta
    nel Master Plan v5.0, Fase 1 Task 1.5).
    """
    from core.cache_orchestrator import get_registered_figure_cache
    from core.figure_cache import CachingStrategy
    from core.cache_signatures import build_portfolio_data_signature, theme_signature, charts_settings_signature

    started_at = time.perf_counter()
    fcache = get_registered_figure_cache()
    prewarm_signature = compute_prewarm_signature(ctx, theme, settings)

    # Signatures
    d_sig = build_portfolio_data_signature(
        ctx.data,
        app_version=str(getattr(ctx, "app_version", "n/d")),
        schema_version=str(getattr(ctx, "schema_version", "n/d")),
    )
    t_sig = theme_signature(theme)
    s_sig = charts_settings_signature("ui/charts/settings.py")
    strat = CachingStrategy.DISK_ONLY
    scope = str(get_pre_render_settings(settings).get("scope", "core_charts_v1"))
    _record_prewarm_event("start", 0.0, detail=f"scope={scope}")
    _persist_prewarm_event(prewarm_signature, "start", 0.0, detail=f"scope={scope}")
    try:
        stats = prewarm_fn(
            ctx=ctx,
            theme=theme,
            settings=settings,
            figure_cache=fcache,
            strategy=strat,
            prewarm_signature=prewarm_signature,
            data_sig=d_sig,
            theme_sig=t_sig,
            charts_settings_sig=s_sig,
            write_state=_write_prewarm_state,
        ) or {}
        elapsed = time.perf_counter() - started_at
        detail = (
            f"scope={scope} | attempted={int(stats.get('attempted', 0))} "
            f"built={int(stats.get('built', 0))} cache_hits={int(stats.get('cache_hits', 0))} "
            f"skipped={int(stats.get('skipped', 0))} errors={int(stats.get('errors', 0))}"
        )
        _record_prewarm_event("done", elapsed, detail=detail, count=int(stats.get("attempted", 0)))
        _persist_prewarm_event(prewarm_signature, "done", elapsed, detail=detail, count=int(stats.get("attempted", 0)))
    except Exception as exc:
        elapsed = time.perf_counter() - started_at
        _record_prewarm_event("done", elapsed, status="ERRORE", detail=f"{type(exc).__name__}: {exc}")
        _persist_prewarm_event(prewarm_signature, "done", elapsed, status="ERRORE", detail=f"{type(exc).__name__}: {exc}")
        raise
