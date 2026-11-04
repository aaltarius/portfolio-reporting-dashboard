"""Cache persistente per payload analitici dei Cruscotti.

Serve per evitare che sezioni pesanti come Benchmark e Accumuli debbano
ricalcolare i propri payload a ogni rerun o dopo la chiusura dell'app.
La cache e' locale, versionata per firma logica e pensata come fallback
leggero: se la firma corrente esiste viene riusata; altrimenti si puo'
mostrare l'ultima analisi disponibile come contenuto stale.
"""
from __future__ import annotations

import gzip
import logging
import pickle
import re
from pathlib import Path
from typing import Any

from core.config import DATA_DIR

logger = logging.getLogger("portafoglio.analytics_cache")

CACHE_DIR = Path(DATA_DIR) / "cache" / "analytics"
_SAFE_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def _safe_token(value: str) -> str:
    token = _SAFE_RE.sub("_", str(value or "payload")).strip("._-")
    return token or "payload"


def _cache_path(payload_type: str, signature: str) -> Path:
    return CACHE_DIR / f"{_safe_token(payload_type)}_{_safe_token(signature)}.pickle.gz"


def _iter_payload_files(payload_type: str) -> list[Path]:
    prefix = f"{_safe_token(payload_type)}_"
    try:
        if not CACHE_DIR.exists():
            return []
        return sorted(
            [p for p in CACHE_DIR.glob(f"{prefix}*.pickle.gz") if p.is_file()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except Exception as exc:
        logger.warning("Lettura elenco cache analytics non riuscita per %s: %s", payload_type, exc)
        return []


def load_entry(payload_type: str, signature: str) -> tuple[dict[str, Any] | None, bool, str]:
    """Carica una entry persistente.

    Restituisce ``(entry, stale, source)``.
    - se esiste la firma corrente: stale=False;
    - se manca la firma corrente ma c'e' un payload precedente: stale=True;
    - se non c'e' nulla: entry=None.
    """
    current_path = _cache_path(payload_type, signature)
    current = _load_file(current_path)
    if isinstance(current, dict):
        return current, False, "disk"

    for path in _iter_payload_files(payload_type):
        if path == current_path:
            continue
        entry = _load_file(path)
        if isinstance(entry, dict):
            return entry, True, "disk_latest"
    return None, False, "miss"


def store_entry(payload_type: str, signature: str, entry: dict[str, Any], *, max_entries: int = 6) -> None:
    """Salva una entry su disco e mantiene solo le ultime ``max_entries``."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _cache_path(payload_type, signature)
        payload = dict(entry)
        payload.setdefault("signature", signature)
        payload.setdefault("payload_type", payload_type)
        with gzip.open(path, "wb") as fh:
            pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)
        _prune(payload_type, max_entries=max_entries)
    except Exception as exc:
        logger.warning("Salvataggio cache analytics non riuscito per %s/%s: %s", payload_type, signature, exc)


def _load_file(path: Path) -> dict[str, Any] | None:
    try:
        if not path.exists() or not path.is_file():
            return None
        with gzip.open(path, "rb") as fh:
            entry = pickle.load(fh)
        if isinstance(entry, dict):
            return entry
    except Exception as exc:
        logger.warning("Cache analytics non leggibile %s: %s", path, exc)
    return None


def _prune(payload_type: str, *, max_entries: int = 6) -> None:
    if max_entries <= 0:
        return
    files = _iter_payload_files(payload_type)
    for path in files[max_entries:]:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            continue
