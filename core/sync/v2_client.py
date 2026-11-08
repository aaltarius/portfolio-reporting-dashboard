"""Client Desktop della sincronizzazione v2: decide cosa inviare (bootstrap o update) e gestisce gli imprevisti.

Principi (specifica 05 v2.1, §3, §4, §8):
- prima di ogni invio si interroga `GET /api/v2/state`: niente invii alla cieca;
- l'invio si registra su disco PRIMA di essere spedito (`SyncStore`): dopo una risposta persa o un riavvio si interroga
  il Worker e si distingue «applicato» da «non applicato»; in quest'ultimo caso si rispedisce lo STESSO messaggio;
- un'epoca diversa dalla propria (rollback, altro Desktop, reset) FERMA l'invio: nessuna ripubblicazione automatica;
- un calo degli eventi non si invia mai da soli: serve una riconciliazione esplicita;
- un `busy` (puntatore cambiato in parallelo) si risolve rileggendo lo stato, non rispedendo alla cieca.
Nessun gancio di runtime chiama questo modulo: va invocato da `tools/sync_v2.py`."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from core.sync import v2
from core.sync.config import is_enabled
from core.sync.transport import TransportRefused

DEFAULT_PATHS = {"v2_state": "/api/v2/state", "v2_bootstrap": "/api/v2/bootstrap", "v2_update": "/api/v2/update"}
MAX_BUSY_RETRIES = 3


def _now_iso(now: datetime | None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


class V2Client:
    def __init__(self, transport, store, *, paths: dict | None = None, new_id=lambda: str(uuid.uuid4())):
        self.t, self.store = transport, store
        self.paths = {**DEFAULT_PATHS, **(paths or {})}
        self.new_id = new_id

    # ---- utilità -------------------------------------------------------------------------------------------
    def _remote(self):
        return self.t.get_json(self.paths["v2_state"])

    @staticmethod
    def _meta(msg_or_state: dict, ds: dict, seq: int, epoch: str) -> dict:
        return {"epochId": epoch, "seq": seq, "datasetRevision": v2.dataset_revision(ds),
                "snapshotRevision": v2.snapshot_revision(ds["snapshot"]), "eventCount": ds["snapshot"]["sourceEventCount"]}

    def _confirm(self, epoch: str, seq: int, ds: dict, now) -> None:
        meta = self._meta({}, ds, seq, epoch)
        meta["confirmedAt"] = _now_iso(now)
        self.store.confirm(meta, ds)

    # ---- invii ---------------------------------------------------------------------------------------------
    def _send_bootstrap(self, parts: list[dict]) -> dict:
        ack = {}
        for part in parts:
            ack = self.t.post(self.paths["v2_bootstrap"], v2_encode(part))
        if ack.get("staged"):                                   # 202/«staged» sull'ultima parte: mancano parti, nessun commit
            raise RuntimeError("bootstrap non completato dal Worker")
        return ack

    def _send_update(self, message_json: bytes) -> dict:
        return self.t.post(self.paths["v2_update"], message_json)

    def _refused(self, exc: TransportRefused, **extra) -> dict:
        code = exc.code or "rejected"
        status = {"busy": "busy", "resync": "resync_needed", "conflict": "conflict", "regression": "regression",
                  "event_regression": "regression", "expired": "expired", "maintenance": "maintenance",
                  "maintenance_required": "maintenance"}.get(code, "rejected")
        return {"status": status, "reason": str(exc), **extra}

    # ---- pendente ------------------------------------------------------------------------------------------
    def _resolve_pending(self, local: dict, remote: dict, now):
        """Restituisce un esito se l'invio in corso blocca il ciclo, altrimenti None (risolto e chiuso)."""
        pend = local["pending"]
        if not pend:
            return None
        ds = self.store.pending_dataset()
        if ds is None:
            self.store.clear_pending()
            return None
        applied = (remote.get("bootstrapped") and remote.get("epochId") == pend["epochId"]
                   and remote.get("seq") == pend["seq"] and remote.get("datasetRevision") == pend["datasetRevision"])
        if applied:
            self._confirm(pend["epochId"], pend["seq"], ds, now)
            return None
        try:
            if pend["kind"] == "update":
                same_base = (remote.get("bootstrapped") and remote.get("epochId") == pend["epochId"]
                             and remote.get("seq") == pend["seq"] - 1)
                if not same_base:
                    return {"status": "diverged", "reason": "l'invio in corso non è né applicato né applicabile: serve una diagnosi"}
                self._send_update(pend["message"].encode("utf-8"))
            else:
                if remote.get("bootstrapped") and remote.get("epochId") != pend["epochId"] and not pend.get("replace"):
                    return {"status": "stopped_epoch", "reason": "il Worker ha un'epoca diversa da quella del bootstrap in corso"}
                self._send_bootstrap([json.loads(x) for x in pend["parts"]])
        except TransportRefused as exc:
            return self._refused(exc, pending=True)
        except RuntimeError as exc:
            return {"status": "unknown_outcome", "reason": str(exc), "pending": True}
        self._confirm(pend["epochId"], pend["seq"], ds, now)
        return None

    # ---- ciclo ---------------------------------------------------------------------------------------------
    def sync(self, dataset: dict, *, settings, kind: str = "prices", reason: str | None = None, now: datetime | None = None,
             min_interval_s: int = 0, allow_rebootstrap: bool = False, dry_run: bool = False) -> dict:
        if not is_enabled(settings):
            return {"status": "disabled"}
        ds = v2.normalize(dataset)
        new_rev = v2.dataset_revision(ds)
        for attempt in range(MAX_BUSY_RETRIES + 2):
            try:
                remote = self._remote()
            except RuntimeError as exc:
                return {"status": "offline", "reason": str(exc)}
            local = self.store.load()
            blocked = self._resolve_pending(local, remote, now)
            if blocked:
                return blocked
            if local["pending"]:
                continue                                       # l'invio in sospeso è chiuso: si rilegge lo stato del Worker
            local = self.store.load()
            conf = local["confirmed"]

            if not remote.get("bootstrapped"):
                if conf and not allow_rebootstrap:
                    return {"status": "remote_reset", "reason": "il Worker non ha più uno stato: serve un nuovo bootstrap esplicito"}
                return self._do_bootstrap(ds, new_rev, now, reason="resync" if conf else "initial",
                                          previous=conf["epochId"] if conf else None, dry_run=dry_run)
            if conf is None:
                if remote.get("datasetRevision") == new_rev:       # stato locale perso ma Worker allineato: si adotta
                    if not dry_run:
                        self._confirm(remote["epochId"], remote["seq"], ds, now)
                    return {"status": "adopted", "seq": remote["seq"]}
                if not allow_rebootstrap:
                    return {"status": "unknown_remote", "reason": "il Worker ha uno stato che il Desktop non riconosce: serve un bootstrap esplicito"}
                return self._do_bootstrap(ds, new_rev, now, reason="resync", previous=remote.get("epochId"), dry_run=dry_run)
            if remote["epochId"] != conf["epochId"]:
                if allow_rebootstrap:      # decisione esplicita dell'utente: il Desktop è l'autorità e riparte con una nuova epoca
                    return self._do_bootstrap(ds, new_rev, now, reason="resync", previous=remote["epochId"], dry_run=dry_run)
                return {"status": "stopped_epoch", "reason": "epoca del Worker diversa da quella del Desktop (rollback o altro Desktop): nessun invio automatico"}
            if remote["seq"] != conf["seq"] or remote["datasetRevision"] != conf["datasetRevision"]:
                if allow_rebootstrap:
                    return self._do_bootstrap(ds, new_rev, now, reason="resync", previous=remote["epochId"], dry_run=dry_run)
                return {"status": "diverged", "reason": "il Worker non è allo stesso punto dell'ultimo invio confermato"}
            if new_rev == conf["datasetRevision"]:
                return {"status": "in_sync", "seq": conf["seq"]}
            if ds["snapshot"]["sourceEventCount"] < remote.get("eventCount", 0):
                return {"status": "regression", "reason": "meno eventi di quelli già pubblicati: serve una riconciliazione esplicita"}
            if kind == "prices" and min_interval_s > 0 and conf.get("confirmedAt"):
                last = datetime.strptime(conf["confirmedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                if ((now or datetime.now(timezone.utc)) - last).total_seconds() < min_interval_s:
                    return {"status": "waiting"}
            prev = self.store.dataset()
            if prev is None:
                return {"status": "diverged", "reason": "dataset locale confermato mancante: serve un nuovo bootstrap esplicito"}
            msg = v2.build_update(prev, ds, epoch_id=conf["epochId"], seq=conf["seq"] + 1, kind=kind, reason=reason,
                                  generated_at=_now_iso(now))
            body = v2_encode(msg)
            if dry_run:
                return {"status": "would_update", "bytes": len(body), "seq": msg["seq"]}
            self.store.set_pending({"kind": "update", "epochId": conf["epochId"], "seq": msg["seq"], "datasetRevision": new_rev,
                                    "messageHash": msg["messageHash"], "message": body.decode("utf-8")}, ds)
            try:
                self._send_update(body)
            except TransportRefused as exc:
                if exc.code == "busy" and attempt < MAX_BUSY_RETRIES:
                    continue                                   # il puntatore è cambiato in parallelo: si rilegge lo stato
                res = self._refused(exc)
                if res["status"] in ("conflict", "regression", "rejected", "resync_needed", "expired", "maintenance"):
                    self.store.clear_pending()                  # rifiutato: non è applicato, non resta in sospeso
                return res
            except RuntimeError as exc:
                return {"status": "unknown_outcome", "reason": str(exc), "pending": True}
            self._confirm(conf["epochId"], msg["seq"], ds, now)
            return {"status": "updated", "seq": msg["seq"], "bytes": len(body)}
        return {"status": "busy", "reason": "il Worker è rimasto occupato"}

    def _do_bootstrap(self, ds, new_rev, now, *, reason, previous, dry_run) -> dict:
        epoch, bid = self.new_id(), uuid.uuid4().hex
        parts = v2.build_bootstrap_parts(ds, epoch_id=epoch, bootstrap_id=bid, reason=reason, generated_at=_now_iso(now),
                                         previous_epoch_id=previous)
        size = sum(len(v2_encode(p)) for p in parts)
        if dry_run:
            return {"status": "would_bootstrap", "parts": len(parts), "bytes": size}
        self.store.set_pending({"kind": "bootstrap", "epochId": epoch, "seq": 1, "datasetRevision": new_rev,
                                "replace": previous is not None, "parts": [v2_encode(p).decode("utf-8") for p in parts]}, ds)
        try:
            self._send_bootstrap(parts)
        except TransportRefused as exc:
            res = self._refused(exc)
            if res["status"] in ("conflict", "regression", "rejected", "expired", "maintenance"):
                self.store.clear_pending()
            return res
        except RuntimeError as exc:
            return {"status": "unknown_outcome", "reason": str(exc), "pending": True}
        self._confirm(epoch, 1, ds, now)
        return {"status": "bootstrapped", "parts": len(parts), "bytes": size}


def v2_encode(message: dict) -> bytes:
    return json.dumps(message, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
