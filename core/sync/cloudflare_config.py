"""Configurazione unica dei parametri Cloudflare (nomi, indirizzi, endpoint, chiavi), personalizzabile.

Il file vive in `data/segreti/cloudflare.json` (cartella ignorata da git: verificato). Nel repository c'è solo il
modello senza segreti `docs/sync/cloudflare.esempio.json`. Le chiavi possono stare nel file (`sync_token`) oppure in un
file a parte (`sync_token_file`); non vengono mai stampate né scritte nei log.

Guardia fissa nel codice, non nel file: l'ambiente di PRODUZIONE è bloccato finché SY-01 non è sbloccata
(`PRODUCTION_BLOCKED`). Cambiare questo valore è una decisione esplicita, separata e tracciata."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

PRODUCTION_BLOCKED = True
SCHEMA_VERSION = 1
MIN_TOKEN_CHARS = 32
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,62}$")
DEFAULT_ENDPOINTS = {
    "snapshot": "/api/sync", "history": "/api/history/sync", "brief": "/api/market/sync",
    "features": "/api/desktop/features/sync", "btp": "/api/history/btp/sync",
    "v2_state": "/api/v2/state", "v2_bootstrap": "/api/v2/bootstrap", "v2_update": "/api/v2/update",
}


EXAMPLE_CONFIG = {'schema_version': 1,
 '_nota': 'MODELLO senza segreti. Copiare in data/segreti/cloudflare.json (cartella ignorata da git) e '
          'compilare. Le chiavi non vanno MAI in questo file di esempio né in chat.',
 'user_agent': 'Sestante-Desktop-Sync/1.0',
 'invio': {'min_intervallo_s': 300,
           'btp_giorni_recenti': 10,
           'timeout_s': 20,
           'gzip': True,
           'file_stato': 'data/config/sync_state_prova.json'},
 'endpoint': {'_nota': 'Percorsi dei Worker; modificare solo se cambiano lato Mobile.',
              'snapshot': '/api/sync',
              'history': '/api/history/sync',
              'brief': '/api/market/sync',
              'features': '/api/desktop/features/sync',
              'btp': '/api/history/btp/sync',
              'v2_state': '/api/v2/state',
              'v2_bootstrap': '/api/v2/bootstrap',
              'v2_update': '/api/v2/update'},
 'ambienti': {'prova': {'invio_consentito': True,
                        'url': 'https://NOME-WORKER-PROVA.IL-TUO-ACCOUNT.workers.dev',
                        'worker': 'NOME-WORKER-PROVA',
                        'bucket': 'NOME-BUCKET-PROVA',
                        'binding_r2': 'SESTANTE_R2',
                        'nomi_secret': {'password': 'MOBILE_PASSWORD', 'sync_token': 'SYNC_TOKEN'},
                        'sync_token_file': 'token_prova.txt',
                        'sync_token': ''},
              'produzione': {'tipo': 'produzione',
                             'invio_consentito': False,
                             'url': 'https://NOME-WORKER-PRODUZIONE.IL-TUO-ACCOUNT.workers.dev',
                             'worker': 'NOME-WORKER-PRODUZIONE',
                             'bucket': 'NOME-BUCKET-PRODUZIONE',
                             'binding_r2': 'SESTANTE_R2',
                             'sync_token_file': ''}},
 'account': {'_nota': 'Dati NON segreti, per promemoria e per la diagnostica a sola lettura.',
             'account_id': '',
             'regola_blocco_backups': 'proteggi-backups (prefisso backups/, 7 giorni)'}}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Environment:
    name: str
    url: str
    host: str
    worker: str
    bucket: str
    binding_r2: str
    secret_names: dict
    endpoints: dict
    user_agent: str
    send_allowed: bool
    timeout_s: int
    _token: str = field(default="", repr=False)

    @property
    def token(self) -> str:
        if len(self._token) < MIN_TOKEN_CHARS:
            raise ConfigError("chiave di sincronizzazione mancante o troppo corta: impostare sync_token o sync_token_file")
        return self._token


def default_path() -> Path:
    import persistence.storage as st
    return Path(st.DATA_DIR) / "segreti" / "cloudflare.json"


def load_config(path=None) -> dict:
    p = Path(path) if path else default_path()
    try:
        cfg = json.loads(p.read_text(encoding="utf-8-sig"))
    except OSError:
        raise ConfigError(f"file di configurazione non trovato: {p.name}") from None
    except ValueError as exc:
        raise ConfigError(f"file di configurazione non valido: {exc}") from None
    if not isinstance(cfg, dict) or cfg.get("schema_version") != SCHEMA_VERSION or not isinstance(cfg.get("ambienti"), dict) or not cfg["ambienti"]:
        raise ConfigError("configurazione senza 'schema_version': 1 e 'ambienti'")
    urls = {}
    for name, env in cfg["ambienti"].items():
        if not isinstance(env, dict):
            raise ConfigError(f"ambiente '{name}' non valido")
        parts = urlsplit(str(env.get("url", "")))
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ConfigError(f"ambiente '{name}': 'url' deve essere un indirizzo https senza credenziali")
        for key in ("worker", "bucket", "binding_r2"):
            if not _NAME.match(str(env.get(key, ""))):
                raise ConfigError(f"ambiente '{name}': '{key}' mancante o con caratteri non validi")
        host = parts.hostname.lower()
        if host in urls:
            raise ConfigError(f"ambienti '{urls[host]}' e '{name}' puntano allo stesso indirizzo")
        urls[host] = name
    return cfg


def _read_token(env: dict, base: Path) -> str:
    inline = str(env.get("sync_token") or "").strip()
    if inline:
        return inline
    ref = str(env.get("sync_token_file") or "").strip()
    if not ref:
        return ""
    f = Path(ref)
    f = f if f.is_absolute() else base / f
    try:
        return f.read_text(encoding="utf-8").strip()
    except OSError:
        return ""  # la mancanza della chiave emerge solo quando serve davvero (Environment.token)


def get_environment(cfg: dict, name: str, *, base_dir=None, config_path=None) -> Environment:
    """Restituisce l'ambiente scelto, rifiutando la produzione e gli ambienti con invio non consentito."""
    env = cfg["ambienti"].get(name)
    if env is None:
        raise ConfigError(f"ambiente '{name}' non presente (disponibili: {', '.join(sorted(cfg['ambienti']))})")
    if PRODUCTION_BLOCKED and (name == "produzione" or env.get("tipo") == "produzione"):
        raise ConfigError("ambiente di produzione bloccato (SY-01): nessun invio consentito")
    if not env.get("invio_consentito", False):
        raise ConfigError(f"ambiente '{name}': invio non consentito ('invio_consentito' è false)")
    base = Path(base_dir) if base_dir else (Path(config_path).parent if config_path else default_path().parent)
    endpoints = {k: v for k, v in {**DEFAULT_ENDPOINTS, **(cfg.get("endpoint") or {}), **(env.get("endpoint") or {})}.items()
                 if not k.startswith("_")}
    for key, value in endpoints.items():
        if not str(value).startswith("/api/") or "?" in str(value) or ".." in str(value):
            raise ConfigError(f"endpoint '{key}' non valido")
    return Environment(
        name=name, url=env["url"].rstrip("/"), host=urlsplit(env["url"]).hostname.lower(), worker=env["worker"],
        bucket=env["bucket"], binding_r2=env["binding_r2"],
        secret_names={"password": "MOBILE_PASSWORD", "sync_token": "SYNC_TOKEN", **(env.get("nomi_secret") or {})},
        endpoints=endpoints, user_agent=str(cfg.get("user_agent") or "Sestante-Desktop-Sync/1.0"),
        send_allowed=True, timeout_s=int((cfg.get("invio") or {}).get("timeout_s", 20)), _token=_read_token(env, base))


def sending_options(cfg: dict) -> dict:
    inv = cfg.get("invio") or {}
    return {"min_interval_s": int(inv.get("min_intervallo_s", 300)), "btp_recent_days": int(inv.get("btp_giorni_recenti", 10)),
            "state_file": inv.get("file_stato", "data/config/sync_state_prova.json"), "gzip": bool(inv.get("gzip", True))}
