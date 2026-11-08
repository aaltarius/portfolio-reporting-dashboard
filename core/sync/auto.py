"""Invio automatico Desktop -> Worker di PROVA dopo ogni salvataggio dei dati.

Come funziona (tutto fuori dal thread dell'interfaccia, mai un errore verso l'app):
- `notify_saved(settings)` è chiamata da `persistence.storage.save_data` DOPO la scrittura riuscita. Se
  `mobile_sync.enabled` è spento (predefinito) non fa nulla;
- i salvataggi ravvicinati si accorpano (`debounce_s`, con tetto `max_wait_s`): un solo ciclo per raffica;
- un solo invio alla volta; un salvataggio durante l'invio ne programma esattamente un altro;
- guasti transitori (rete, esito incerto, Worker occupato) si ritentano con attesa crescente e un numero finito di
  volte; le condizioni che richiedono una decisione (conflitto, epoca diversa, calo eventi, reset del Worker…) NON
  si ritentano: restano segnalate in `status()` e nel log;
- `operation` (acquisto, vendita, cedola…) è riconosciuta dall'aumento degli eventi rispetto all'ultimo stato confermato.
L'ambiente è `mobile_sync.ambiente` (predefinito «prova»); la produzione è bloccata nel codice (SY-01)."""
from __future__ import annotations

import logging
import threading
import time

from core.sync.config import is_enabled

logger = logging.getLogger("portafoglio.sync")

TRANSIENT = {"offline", "unknown_outcome", "busy"}
_REASONS = (("ACQUISTO", "buy"), ("VENDITA", "sell"), ("CEDOLA", "income"), ("DIVIDEND", "income"), ("PROVENT", "income"),
            ("RIMBORSO", "redemption"), ("VERSAMENTO", "cash"), ("PRELIEVO", "cash"))


def operation_reason(new_events: list[dict]) -> str:
    kinds = set()
    for event in new_events:
        label = str(event.get("tipo_evento") or "").upper()
        kinds.add(next((reason for key, reason in _REASONS if key in label), "other"))
    return kinds.pop() if len(kinds) == 1 else "other"


class AutoSync:
    def __init__(self, runner, *, schedule=None, debounce_s=10, max_wait_s=60, retry_delays=(60, 180, 600), now=time.monotonic):
        self._runner, self._debounce, self._max_wait = runner, debounce_s, max_wait_s
        self._retry_delays, self._now = tuple(retry_delays), now
        self._schedule = schedule or (lambda delay, fn: _start_timer(delay, fn))
        self._lock = threading.RLock()
        self._timer, self._first_request, self._running, self._dirty = None, None, False, False
        self._retries_left, self._last = len(self._retry_delays), None

    def status(self) -> dict:
        with self._lock:
            return {"running": self._running, "pending": self._timer is not None, "last": self._last}

    def notify(self, settings) -> None:
        if not is_enabled(settings):
            return
        with self._lock:
            if self._running:
                self._dirty = True
                return
            first = self._first_request if self._first_request is not None else self._now()
            self._first_request = first
            delay = max(0.0, min(self._debounce, self._max_wait - (self._now() - first)))
            self._arm(delay)

    def _arm(self, delay) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._timer = self._schedule(delay, self._run)

    def _run(self) -> None:
        with self._lock:
            self._timer, self._first_request, self._running, self._dirty = None, None, True, False
        try:
            result = self._runner()
        except Exception as exc:  # noqa: BLE001 - nessun errore deve arrivare all'app
            logger.exception("Invio automatico: errore interno")
            result = {"status": "internal_error", "reason": str(exc)}
        with self._lock:
            self._running = False
            self._last = result
            status = result.get("status")
            if status in TRANSIENT and self._retries_left > 0:
                delay = self._retry_delays[len(self._retry_delays) - self._retries_left]
                self._retries_left -= 1
                self._arm(delay)
            else:
                if status not in TRANSIENT:
                    self._retries_left = len(self._retry_delays)
                if self._dirty:
                    self._first_request = self._now()
                    self._arm(self._debounce)
        level = logging.INFO if result.get("status") in ("in_sync", "updated", "bootstrapped", "adopted", "waiting", "disabled") else logging.WARNING
        logger.log(level, "Invio automatico: %s %s", result.get("status"), result.get("reason", ""))


def _start_timer(delay, fn):
    timer = threading.Timer(delay, fn)
    timer.daemon = True
    timer.start()
    return timer


def run_once() -> dict:
    """Un ciclo reale: legge i dati dal disco, costruisce il dataset e lo sincronizza con l'ambiente configurato."""
    import json
    from pathlib import Path

    import persistence.storage as st
    from core.sync import cloudflare_config as cc
    from core.sync import v2
    from core.sync.snapshot import build_snapshot
    from core.sync.transport import HttpTransport
    from core.sync.v2_client import V2Client
    from core.sync.v2_state import SyncStore
    from persistence.parquet_utils import load_storico_prezzi_hybrid

    settings = st.load_settings()
    if not is_enabled(settings):
        return {"status": "disabled"}
    try:
        cfg_path = cc.default_path()
        cfg = cc.load_config(cfg_path)
        env = cc.get_environment(cfg, (settings["mobile_sync"].get("ambiente") or "prova"), config_path=cfg_path)
        opts = cc.sending_options(cfg)
        transport = HttpTransport(env.url, env.token, allowed_hosts={env.host}, timeout=env.timeout_s,
                                  user_agent=env.user_agent, gzip_body=opts["gzip"])
    except ValueError as exc:
        return {"status": "config_error", "reason": str(exc)}
    raw = Path(st.DATA_FILE).read_bytes()
    data = json.loads(raw.decode("utf-8-sig"))
    try:
        snap = build_snapshot(data, source_bytes=raw)
        ds = v2.build_dataset(data, snap, load_storico_prezzi_hybrid(st.STORICO_PREZZI_FILE))
    except ValueError as exc:
        return {"status": "not_built", "reason": str(exc)}
    store = SyncStore(Path(st.DATA_DIR) / "cache" / "sync_v2")
    conf = store.load()["confirmed"]
    added = snap["sourceEventCount"] - conf["eventCount"] if conf else 0
    kind, reason = ("operation", operation_reason((data.get("registro_eventi") or [])[-added:])) if added > 0 else ("prices", None)
    client = V2Client(transport, store, paths={k: env.endpoints[k] for k in ("v2_state", "v2_bootstrap", "v2_update")})
    return client.sync(ds, settings=settings, kind=kind, reason=reason, min_interval_s=opts["min_interval_s"])


_AUTO = None
_AUTO_LOCK = threading.Lock()


def get_auto() -> AutoSync:
    global _AUTO
    with _AUTO_LOCK:
        if _AUTO is None:
            _AUTO = AutoSync(run_once)
        return _AUTO


def notify_saved(settings) -> None:
    """Gancio di `save_data`: costo trascurabile se spento, mai eccezioni verso il chiamante."""
    try:
        if is_enabled(settings):
            get_auto().notify(settings)
    except Exception:  # noqa: BLE001
        logger.exception("Invio automatico: gancio non eseguito")
