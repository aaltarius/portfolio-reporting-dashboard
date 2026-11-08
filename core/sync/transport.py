"""Trasporti dell'invio Desktop -> Mobile.

- `HttpTransport`: POST verso il Worker. Per costruzione parla SOLO con gli host passati in `allowed_hosts`
  (di fatto: quello dell'ambiente di PROVA scelto in `cloudflare.json`); senza elenco rifiuta ogni host. Solo HTTPS, nessun reindirizzamento, il token non compare mai
  in messaggi di errore o log.
"""
from __future__ import annotations

import gzip
import json
import urllib.error
import urllib.parse
import urllib.request

ALLOWED_HOSTS = frozenset()   # vuoto di proposito: i server consentiti li indica chi chiama (dalla configurazione personale)
MAX_BODY_CHARS = 200_000  # limite per corpo del Worker (richiesta singola: ×3 per le parti Base64)
MIN_TOKEN_CHARS = 32
USER_AGENT = "Sestante-Desktop-Sync/1.0"  # senza, Cloudflare risponde 403 (errore 1010) allo stile di richiesta di Python


class TransportRefused(Exception):
    """Il server ha rifiutato l'invio (regressione, schema, dimensione, sequenza): non è un guasto di rete.
    `status` è il codice HTTP e `code` quello applicativo v2 (resync, conflict, busy, regression, invalid)."""

    def __init__(self, message, status=None, code=None):
        super().__init__(message)
        self.status, self.code = status, code


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


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
