"""Trasporti dell'invio Desktop -> Mobile.

- `LocalDirTransport`: scrive in una cartella locale ("cloud finto" per i collaudi).
- `HttpTransport`: POST verso il Worker. Per costruzione parla SOLO con gli host passati in `allowed_hosts`
  (di fatto: quello dell'ambiente di PROVA scelto in `cloudflare.json`); senza elenco rifiuta ogni host. Solo HTTPS, nessun reindirizzamento, il token non compare mai
  in messaggi di errore o log.

Struttura nella cartella:  head.json  (puntatore alla versione corrente)  +  snapshots/<revisione>.json
(versioni immutabili, mai sovrascritte né cancellate da questo modulo)."""
from __future__ import annotations

import gzip
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_REVISION = re.compile(r"[0-9a-f]{64}")

ALLOWED_HOSTS = frozenset()   # vuoto di proposito: i server consentiti li indica chi chiama (dalla configurazione personale)
MAX_BODY_CHARS = 200_000  # limite del Worker per /api/sync
MIN_TOKEN_CHARS = 32
USER_AGENT = "Sestante-Desktop-Sync/1.0"  # senza, Cloudflare risponde 403 (errore 1010) allo stile di richiesta di Python


class TransportRefused(Exception):
    """Il server ha rifiutato l'invio (regressione, schema, dimensione, sequenza): non è un guasto di rete.
    `status` è il codice HTTP e `code` quello applicativo v2 (resync, conflict, busy, regression, invalid)."""

    def __init__(self, message, status=None, code=None):
        super().__init__(message)
        self.status, self.code = status, code


def load_token(path) -> str:
    """Legge il token da un file locale (fuori dal repository). Non lo stampa e non lo conserva altrove."""
    p = Path(path)
    if not p.is_file():
        raise ValueError("file del token non trovato")
    token = p.read_text(encoding="utf-8").strip()
    if len(token) < MIN_TOKEN_CHARS:
        raise ValueError("token troppo corto")
    return token


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class LocalDirTransport:
    def __init__(self, root):
        self.root = Path(root)

    @property
    def _head_path(self) -> Path:
        return self.root / "head.json"

    def _write_atomic(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def get_head(self) -> dict | None:
        """Versione corrente, o None se non è mai stato inviato nulla. Solleva se head.json è illeggibile."""
        if not self._head_path.exists():
            return None
        head = json.loads(self._head_path.read_text(encoding="utf-8"))
        if not isinstance(head, dict) or not _REVISION.fullmatch(str(head.get("revision", ""))):
            raise ValueError("head.json non valido")
        return head

    def put_snapshot(self, snap: dict) -> dict:
        """Scrive la versione (immutabile) e poi sposta il puntatore. Ordine voluto: un guasto a metà lascia
        al massimo una versione in più, mai un puntatore che indica un file inesistente."""
        revision = str(snap.get("revision", ""))
        if not _REVISION.fullmatch(revision):
            raise ValueError("revisione non valida")
        target = self.root / "snapshots" / f"{revision}.json"
        if not target.exists():
            self._write_atomic(target, json.dumps(snap, ensure_ascii=False, sort_keys=True))
        head = {"revision": revision, "eventCount": int(snap.get("sourceEventCount", 0)),
                "sourceUpdatedAt": snap.get("sourceUpdatedAt")}
        self._write_atomic(self._head_path, json.dumps(head, ensure_ascii=False, sort_keys=True))
        return head


class HttpTransport:
    def __init__(self, base_url: str, token: str, *, allowed_hosts=None, allow_insecure_loopback=False, timeout=20,
                 user_agent=None, gzip_body=False):
        parsed = urllib.parse.urlsplit(str(base_url))
        hosts = ALLOWED_HOSTS if allowed_hosts is None else set(allowed_hosts)
        host = parsed.hostname or ""
        loopback_ok = allow_insecure_loopback and host == "127.0.0.1"
        if host not in hosts or parsed.username or parsed.password:
            raise ValueError("host non consentito: il trasporto di rete è limitato all'ambiente di prova")
        if parsed.scheme != "https" and not (loopback_ok and parsed.scheme == "http"):
            raise ValueError("solo HTTPS")
        if len(str(token or "")) < MIN_TOKEN_CHARS:
            raise ValueError("token troppo corto")
        self._token = token
        self.timeout = timeout
        self.user_agent = user_agent or USER_AGENT
        self.gzip = bool(gzip_body)
        netloc = host if parsed.port is None else f"{host}:{parsed.port}"
        self.endpoint = f"{parsed.scheme}://{netloc}/api/sync"

    def get_head(self):
        return None  # lo stato lo giudica il server (unchanged / 409): nessuna lettura con il token di invio

    def put_snapshot(self, snap: dict) -> dict:
        body = json.dumps(snap, ensure_ascii=False, sort_keys=True).encode("utf-8")
        if len(body) > MAX_BODY_CHARS:
            raise TransportRefused("fotografia oltre il limite del Worker")
        payload = self.post("/api/sync", body)
        return {"revision": payload.get("revision", snap.get("revision")), "unchanged": bool(payload.get("unchanged"))}

    def _url(self, path: str) -> str:
        if not str(path).startswith("/api/") or "?" in path or ".." in path:
            raise ValueError("percorso non consentito")
        return self.endpoint.rsplit("/api/sync", 1)[0] + path

    def _call(self, req) -> dict:
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            code = None
            try:
                code = (json.loads(exc.read().decode("utf-8")) or {}).get("code")
            except (OSError, ValueError, AttributeError):
                pass
            if exc.code in (409, 413, 422):
                raise TransportRefused(f"HTTP {exc.code}", status=exc.code, code=code if isinstance(code, str) else None) from None
            raise RuntimeError(f"HTTP {exc.code}") from None
        except (urllib.error.URLError, OSError, ValueError):
            raise RuntimeError("server non raggiungibile o risposta non valida") from None
        if not isinstance(payload, dict) or not payload.get("ok"):
            raise RuntimeError("risposta del server non valida")
        return payload

    def post(self, path: str, body: bytes, *, gzip_body: bool | None = None) -> dict:
        """POST autenticato verso un endpoint di sincronizzazione. Restituisce la risposta JSON del Worker."""
        if len(body) > MAX_BODY_CHARS * 3:
            raise TransportRefused("invio oltre ogni limite del Worker")
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   "User-Agent": self.user_agent, "X-Sestante-Sync-Token": self._token}
        if self.gzip if gzip_body is None else gzip_body:
            body = gzip.compress(body, mtime=0)
            headers["Content-Encoding"] = "gzip"
        return self._call(urllib.request.Request(self._url(path), data=body, method="POST", headers=headers))

    def get_json(self, path: str) -> dict:
        """GET autenticato (solo lettura dello stato)."""
        return self._call(urllib.request.Request(self._url(path), method="GET", headers={
            "Accept": "application/json", "User-Agent": self.user_agent, "X-Sestante-Sync-Token": self._token}))
