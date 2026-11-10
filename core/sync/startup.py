"""Controllo all'avvio del Desktop: il Mobile è allineato, più indietro o ha prezzi più recenti?

Gira UNA volta per processo in un thread a parte (nessun ritardo all'avvio) e lascia un esito leggibile dalla barra in
alto (`get_status`). Non modifica il portafoglio. Se il Desktop è avanti, avvia l'invio automatico; se il Mobile ha
prezzi più recenti li valuta e li tiene in quarantena (vedi `observations`). Spento = nessuna rete e nessun segnale."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from core.sync.config import is_enabled

logger = logging.getLogger("portafoglio.sync")   # stessa famiglia di log dell'app (data/logs/portafoglio.log)

OFF_DETAIL = "Sincronizzazione Mobile spenta: si accende da Setup → Aggiornamenti automatici in rete"
COLORS = {"ok": "#10B981", "warn": "#F97316", "bad": "#EF4444", "idle": "#64748B", "info": "#0EA5E9"}
_LOCK = threading.Lock()
_STATUS: dict = {"state": "off"}
_STARTED = False
_GEN = 0   # cresce a ogni stop: un controllo avviato prima non sovrascrive l'esito di quello dopo


def _status(state, label, tone, detail="", now=None):
    return {"state": state, "label": label, "color": COLORS[tone], "detail": detail,
            "checked_at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")}


def _real_context(settings):
    """(transport, endpoints, dataset, data, state_dir, notify) con i componenti veri dell'app."""
    import json
    from pathlib import Path

    import persistence.storage as st
    from core.sync import auto
    from core.sync import cloudflare_config as cc
    from core.sync import v2
    from core.sync.snapshot import build_snapshot
    from core.sync.transport import HttpTransport
    from persistence.parquet_utils import load_storico_prezzi_hybrid

    cfg_path = cc.default_path()
    cfg = cc.load_config(cfg_path)
    env = cc.get_environment(cfg, (settings["mobile_sync"].get("ambiente") or "prova"), config_path=cfg_path)
    opts = cc.sending_options(cfg)
    transport = HttpTransport(env.url, env.token, allowed_hosts={env.host}, timeout=env.timeout_s,
                              user_agent=env.user_agent, gzip_body=opts["gzip"])
    raw = Path(st.DATA_FILE).read_bytes()
    data = json.loads(raw.decode("utf-8-sig"))
    snap = build_snapshot(data, source_bytes=raw)
    ds = v2.build_dataset(data, snap, load_storico_prezzi_hybrid(st.STORICO_PREZZI_FILE))
    return transport, env.endpoints, ds, data, Path(st.DATA_DIR) / "cache" / "sync_v2", lambda: auto.get_auto().notify(settings)


def _default_apply(found, **kwargs):
    from core.sync import apply_prices
    return apply_prices.apply(found, **kwargs)


def check_now(settings, *, context=None, now=None, apply_fn=None) -> dict:
    """Esegue il controllo e restituisce l'esito (non solleva mai)."""
    if not is_enabled(settings):
        return _status("off", "off", "idle", OFF_DETAIL, now)
    from core.sync import observations as obs
    from core.sync import v2
    from core.sync.cloudflare_config import ConfigError
    from core.sync.v2_state import SyncStore
    try:
        ctx = _real_context(settings) if context is None else context
        transport, endpoints, ds, data, state_dir, notify = ctx
    except ConfigError as exc:
        return _status("not_configured", "non configurato", "warn", str(exc), now)
    except (OSError, ValueError, KeyError) as exc:
        return _status("not_built", "dati non letti", "warn", str(exc), now)
    try:
        remote = transport.get_json(endpoints.get("v2_state", "/api/v2/state"))
    except RuntimeError as exc:
        return _status("unreachable", "offline", "warn", str(exc), now)
    store = SyncStore(state_dir)
    conf = store.load()["confirmed"]
    ds_rev = v2.dataset_revision(ds)
    result = None
    if not remote.get("bootstrapped"):
        notify()
        result = _status("sending", "invio", "info", "il Mobile non ha ancora i dati", now)
    elif conf is None:
        if remote.get("datasetRevision") == ds_rev:
            notify()
            result = _status("aligned", "allineato", "ok", "stesso contenuto del Desktop", now)
        else:
            result = _status("check", "da verificare", "bad", "il Mobile ha dati che il Desktop non riconosce", now)
    elif remote.get("epochId") != conf["epochId"]:
        result = _status("check", "da verificare", "bad", "il Mobile è stato ripristinato o usa un'altra epoca: nessun invio automatico. Per riprendere: sync_v2 --allow-rebootstrap", now)
    elif remote.get("seq") != conf["seq"] or remote.get("datasetRevision") != conf["datasetRevision"]:
        result = _status("check", "da verificare", "bad", "il Mobile non è all'ultimo invio confermato dal Desktop. Per riprendere: sync_v2 --allow-rebootstrap", now)
    elif ds_rev != conf["datasetRevision"]:
        notify()
        result = _status("sending", "invio", "info", "il Desktop ha dati più recenti del Mobile", now)
    else:
        result = _status("aligned", "allineato", "ok", f"Mobile aggiornato (invio n. {conf['seq']})", now)
    try:
        found = obs.fetch(transport, endpoints.get("v2_observations", obs.ENDPOINT))
        if found is not None:
            items = obs.evaluate(data, found)
            obs.quarantine(state_dir / "observations.json", items, now=now)
            newer = [i for i in items if i["decision"] == "newer_on_mobile"]
            if newer and result["state"] in ("aligned", "sending"):
                n = len(newer)
                mobile_cfg = settings.get("mobile_sync") if isinstance(settings.get("mobile_sync"), dict) else {}
                if mobile_cfg.get("importa_prezzi", True):
                    done = (apply_fn or _default_apply)(found, log_path=state_dir / "observations_log.jsonl", now=now)
                    k = len(done.get("applied") or [])
                    if done.get("error"):
                        result = _status("import_error", "import fallito", "warn", f"prezzi del Mobile non importati: {done['error']}", now)
                    elif k:
                        result = _status("imported", f"importati {k}", "ok", f"{k} {'prezzo' if k == 1 else 'prezzi'} più recenti dal Mobile applicati al Desktop", now)
                else:
                    result = _status("mobile_newer", "nuovi prezzi", "info",
                                     f"{n} {'prezzo' if n == 1 else 'prezzi'} più recenti sul Mobile; importazione spenta nel Setup", now)
        if context is None and apply_fn is None and (settings.get("mobile_sync") or {}).get("importa_prezzi", True):
            from core.sync import apply_prices
            apply_prices.reconcile_now()      # prezzi correnti senza riga nello storico: stessa «ultima seduta» su Desktop e Mobile
    except Exception:  # noqa: BLE001 - le osservazioni sono un di più: non devono rovinare l'esito principale
        logger.exception("Controllo avvio: osservazioni del Mobile non valutabili")
    return result


def get_status() -> dict:
    """Esito corrente per la barra in alto; se l'invio avviato dal controllo è andato a buon fine lo riflette."""
    with _LOCK:
        status = dict(_STATUS)
    if status.get("state") == "sending":
        try:
            from core.sync import auto
            last = (auto.get_auto().status().get("last") or {}).get("status")
            if last in ("updated", "bootstrapped", "in_sync", "adopted"):
                return _status("aligned", "allineato", "ok", "invio completato")
            if last and last not in ("waiting",):
                return _status("send_problem", "invio fallito", "warn", str(last))
        except Exception:  # noqa: BLE001
            pass
    return status


def start_once(settings, *, context=None) -> bool:
    """Avvia il controllo in un thread a parte, una sola volta per processo. Restituisce True se avviato."""
    global _STARTED, _GEN
    with _LOCK:
        if _STARTED or not is_enabled(settings):
            if not is_enabled(settings):
                _STATUS.clear()
                _STATUS.update(_status("off", "spento", "idle"))
            return False
        _STARTED = True
        gen = _GEN
        _STATUS.clear()
        _STATUS.update(_status("checking", "controllo", "info"))

    def _work():
        started = time.monotonic()
        logger.info("Controllo Mobile all'avvio: avviato")
        try:
            result = check_now(settings, context=context)
        except BaseException as exc:  # noqa: BLE001 - qualunque fine anomala deve lasciare un esito e una traccia nel log
            logger.exception("Controllo Mobile all'avvio fallito")
            result = _status("error", "errore", "warn", f"{type(exc).__name__}: {exc}")
        with _LOCK:
            if gen == _GEN:
                _STATUS.clear()
                _STATUS.update(result)
        logger.info("Controllo Mobile all'avvio: %s - %s (%.1f s)", result.get("state"), result.get("detail", ""), time.monotonic() - started)
    threading.Thread(target=_work, name="mobile-startup-check", daemon=True).start()
    return True


def reset_for_tests() -> None:
    global _STARTED
    with _LOCK:
        _STARTED = False
        _STATUS.clear()
        _STATUS.update({"state": "off"})


def wait_until_done(timeout: float = 8.0) -> dict:
    """Attende (al massimo `timeout` secondi) che il controllo in corso finisca; restituisce l'esito corrente."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _LOCK:
            if _STATUS.get("state") != "checking":
                break
        time.sleep(0.1)
    return get_status()


def chip_html(status: dict | None) -> str:
    """Pastiglia «Mobile» per la barra in alto (stesso markup delle altre). Sempre presente: spenta = «off» in grigio."""
    from html import escape
    if not status:
        return ""
    if status.get("state") in (None, "off"):          # spenta: la pastiglia resta, e dice chiaramente «off»
        status = {"label": "off", "color": COLORS["idle"], "detail": OFF_DETAIL}
    return (f'<div class="header-chip" title="{escape(str(status.get("detail") or ""))}">'
            '<span class="header-chip-label">Mobile</span><span class="header-chip-value">'
            f'<span class="header-status-dot" style="--status-color:{escape(str(status.get("color") or "#64748B"))};"></span>'
            f'<span>{escape(str(status.get("label") or ""))}</span></span></div>')


def stop() -> None:
    """Sincronizzazione spenta dalle impostazioni: nessun segnale, e un nuovo accendere farà un nuovo controllo."""
    global _STARTED, _GEN
    with _LOCK:
        _GEN += 1
        _STARTED = False
        _STATUS.clear()
        _STATUS.update({"state": "off"})
    logger.info("Sincronizzazione Mobile: spenta dalle impostazioni")


def apply_setting_change(settings) -> None:
    """Da chiamare dopo il salvataggio delle impostazioni: acceso → controllo subito; spento → tutto fermo."""
    if is_enabled(settings):
        if start_once(settings):
            logger.info("Sincronizzazione Mobile: accesa dalle impostazioni")
    else:
        with _LOCK:
            was_on = _STARTED or _STATUS.get("state") not in (None, "off")
        if was_on:
            stop()
