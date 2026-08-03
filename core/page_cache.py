from __future__ import annotations

import copy
import gzip
import hashlib
import json
import logging
import pickle
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import streamlit as st

from core.render_profiler import record_render_event
from persistence.storage import DATA_DIR


logger = logging.getLogger("portafoglio.core.page_cache")


CACHE_SCHEMA_VERSION = "page-cache-v1"
PAGE_ARTIFACT_CACHE_DIR = Path(DATA_DIR) / "cache" / "page_artifacts"
PAGE_ARTIFACT_MANIFEST_FILE = Path(DATA_DIR) / "cache" / "page_artifacts_manifest.json"
_PROCESS_CACHE: dict[tuple[str, str, str], Any] = {}
_MANIFEST_LOCK = threading.RLock()
_DISK_CODECS = {"gzip", "pickle"}


@dataclass(frozen=True)
class PageArtifact:
    """Risultato standard del layer cache pagina."""

    page_id: str
    layer: str
    signature: str
    source: str
    value: Any


def _json_default(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}
    return repr(value)


def _stable_hash(payload: Any, *, length: int = 16) -> str:
    raw = json.dumps(payload, sort_keys=True, default=_json_default, ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


def build_page_artifact_signature(
    *,
    page_id: str,
    layer: str,
    inputs: dict[str, Any],
    version: str,
) -> str:
    """Firma unica per gli artefatti pagina.

    La firma contiene solo segnali espliciti: dati, tema, impostazioni, versione
    logica. Le pagine non devono costruire chiavi cache ad hoc.
    """

    return _stable_hash(
        {
            "schema": CACHE_SCHEMA_VERSION,
            "page_id": str(page_id),
            "layer": str(layer),
            "version": str(version),
            "inputs": inputs or {},
        }
    )


def _session_key(page_id: str, layer: str, signature: str) -> str:
    return f"_page_artifact::{page_id}::{layer}::{signature}"


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return cleaned.strip("._") or "artifact"


def _normalize_disk_codec(value: str | None) -> str:
    codec = str(value or "gzip").strip().lower()
    return codec if codec in _DISK_CODECS else "gzip"


def _disk_path(page_id: str, layer: str, signature: str, *, disk_codec: str = "gzip") -> Path:
    stem = _stable_hash({"page_id": page_id, "layer": layer, "signature": signature}, length=24)
    suffix = ".pickle" if _normalize_disk_codec(disk_codec) == "pickle" else ".pickle.gz"
    return PAGE_ARTIFACT_CACHE_DIR / f"{_safe_name(page_id)}__{_safe_name(layer)}__{stem}{suffix}"


def _empty_manifest() -> dict[str, Any]:
    return {
        "schema": CACHE_SCHEMA_VERSION,
        "updated_at": 0.0,
        "entries": {},
    }


def _read_manifest() -> dict[str, Any]:
    with _MANIFEST_LOCK:
        try:
            if not PAGE_ARTIFACT_MANIFEST_FILE.exists():
                return _empty_manifest()
            raw = PAGE_ARTIFACT_MANIFEST_FILE.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {}
            if not isinstance(data, dict):
                return _empty_manifest()
            entries = data.get("entries", {})
            if not isinstance(entries, dict):
                entries = {}
            return {
                "schema": str(data.get("schema") or CACHE_SCHEMA_VERSION),
                "updated_at": float(data.get("updated_at", 0.0) or 0.0),
                "entries": entries,
            }
        except Exception as exc:
            logger.warning("Lettura manifest page artifacts non riuscita: %s", exc)
            return _empty_manifest()


def _write_manifest(manifest: dict[str, Any]) -> None:
    with _MANIFEST_LOCK:
        try:
            PAGE_ARTIFACT_MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "schema": CACHE_SCHEMA_VERSION,
                "updated_at": time.time(),
                "entries": dict((manifest or {}).get("entries", {}) or {}),
            }
            PAGE_ARTIFACT_MANIFEST_FILE.write_text(
                json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Scrittura manifest page artifacts non riuscita: %s", exc)


def _manifest_entry_key(page_id: str, layer: str, signature: str) -> str:
    return f"{_safe_name(page_id)}::{_safe_name(layer)}::{signature}"


def _value_kind(value: Any) -> str:
    module = getattr(type(value), "__module__", "")
    name = getattr(type(value), "__name__", type(value).__class__.__name__)
    if module and module != "builtins":
        return f"{module}.{name}"
    return name


def _record_manifest_entry(page_id: str, layer: str, signature: str, value: Any, path: Path, *, disk_codec: str = "gzip") -> None:
    manifest = _read_manifest()
    entries = dict(manifest.get("entries", {}) or {})
    try:
        size_bytes = int(path.stat().st_size) if path.exists() else 0
    except Exception:
        size_bytes = 0
    entries[_manifest_entry_key(page_id, layer, signature)] = {
        "schema": CACHE_SCHEMA_VERSION,
        "page_id": str(page_id),
        "layer": str(layer),
        "signature": str(signature),
        "path": str(path),
        "file": path.name,
        "size_bytes": size_bytes,
        "created_at": time.time(),
        "value_kind": _value_kind(value),
        "disk_codec": _normalize_disk_codec(disk_codec),
    }
    manifest["entries"] = entries
    _write_manifest(manifest)


def _read_artifact_payload(path: Path) -> dict[str, Any] | None:
    try:
        if path.name.endswith(".pickle"):
            with open(path, "rb") as handle:
                payload = pickle.load(handle)
        else:
            with gzip.open(path, "rb") as handle:
                payload = pickle.load(handle)
        if not isinstance(payload, dict):
            return None
        if payload.get("schema") != CACHE_SCHEMA_VERSION:
            return None
        if not payload.get("page_id") or not payload.get("layer") or not payload.get("signature"):
            return None
        return payload
    except Exception as exc:
        logger.warning("Lettura page artifact per manifest non riuscita (%s): %s", path.name, exc)
        return None


def rebuild_page_artifact_manifest() -> dict[str, Any]:
    """Ricostruisce il manifest leggendo gli artefatti pagina gia' presenti su disco.

    Serve soprattutto dopo l'introduzione del manifest: gli artefatti creati in
    precedenza sono validi, ma non comparirebbero nelle statistiche di Dati.
    """

    scanned = 0
    indexed = 0
    skipped = 0
    entries: dict[str, dict[str, Any]] = {}

    try:
        files = sorted({
            *PAGE_ARTIFACT_CACHE_DIR.glob("*.pickle.gz"),
            *PAGE_ARTIFACT_CACHE_DIR.glob("*.pickle"),
        })
    except Exception as exc:
        logger.warning("Scansione page artifacts non riuscita: %s", exc)
        files = []

    for path in files:
        scanned += 1
        payload = _read_artifact_payload(path)
        if not payload:
            skipped += 1
            continue
        page_id = str(payload.get("page_id") or "")
        layer = str(payload.get("layer") or "")
        signature = str(payload.get("signature") or "")
        value = payload.get("value")
        try:
            stat = path.stat()
            size_bytes = int(stat.st_size)
            fallback_created_at = float(stat.st_mtime)
        except Exception:
            size_bytes = 0
            fallback_created_at = 0.0
        entries[_manifest_entry_key(page_id, layer, signature)] = {
            "schema": CACHE_SCHEMA_VERSION,
            "page_id": page_id,
            "layer": layer,
            "signature": signature,
            "path": str(path),
            "file": path.name,
            "size_bytes": size_bytes,
            "created_at": float(payload.get("created_at", 0.0) or fallback_created_at),
            "value_kind": _value_kind(value),
            "disk_codec": "pickle" if path.name.endswith(".pickle") else "gzip",
        }
        indexed += 1

    _write_manifest({"entries": entries})
    return {
        "schema": CACHE_SCHEMA_VERSION,
        "scanned": scanned,
        "indexed": indexed,
        "skipped": skipped,
        "manifest_file": str(PAGE_ARTIFACT_MANIFEST_FILE),
        "cache_dir": str(PAGE_ARTIFACT_CACHE_DIR),
    }


def _has_disk_artifact_files() -> bool:
    try:
        return any(PAGE_ARTIFACT_CACHE_DIR.glob("*.pickle.gz")) or any(PAGE_ARTIFACT_CACHE_DIR.glob("*.pickle"))
    except Exception:
        return False


def _clone_if_requested(value: Any, *, clone: bool) -> Any:
    if not clone:
        return value
    if isinstance(value, (dict, list, tuple, set)):
        try:
            return copy.deepcopy(value)
        except Exception:
            return value
    try:
        if hasattr(value, "copy"):
            return value.copy(deep=True)
    except TypeError:
        try:
            return value.copy()
        except Exception:
            pass
    except Exception:
        pass
    try:
        return copy.deepcopy(value)
    except Exception:
        return value


def _load_from_disk(page_id: str, layer: str, signature: str, *, disk_codec: str = "gzip") -> Any | None:
    preferred_codec = _normalize_disk_codec(disk_codec)
    fallback_codec = "gzip" if preferred_codec == "pickle" else "pickle"
    for codec in (preferred_codec, fallback_codec):
        path = _disk_path(page_id, layer, signature, disk_codec=codec)
        if not path.exists():
            continue
        try:
            payload = _read_artifact_payload(path)
            if not isinstance(payload, dict):
                continue
            if payload.get("signature") != signature:
                continue
            return payload.get("value")
        except Exception as exc:
            logger.warning("Errore lettura page artifact %s/%s: %s", page_id, layer, exc)
    return None


def _save_to_disk(page_id: str, layer: str, signature: str, value: Any, *, disk_codec: str = "gzip") -> None:
    try:
        PAGE_ARTIFACT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        codec = _normalize_disk_codec(disk_codec)
        path = _disk_path(page_id, layer, signature, disk_codec=codec)
        payload = {
            "schema": CACHE_SCHEMA_VERSION,
            "page_id": page_id,
            "layer": layer,
            "signature": signature,
            "value": value,
            "created_at": time.time(),
        }
        if codec == "pickle":
            with open(path, "wb") as handle:
                pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
        else:
            with gzip.open(path, "wb") as handle:
                pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
        _record_manifest_entry(page_id, layer, signature, value, path, disk_codec=codec)
    except Exception as exc:
        logger.warning("Errore salvataggio page artifact %s/%s: %s", page_id, layer, exc)


def get_or_build_page_artifact(
    *,
    page_id: str,
    layer: str,
    signature: str,
    builder: Callable[[], Any],
    profile_page: str | None = None,
    clone_on_read: bool = False,
    persist_disk: bool = True,
    disk_codec: str = "gzip",
) -> PageArtifact:
    """Recupera o costruisce un artefatto pagina secondo la policy unica.

    Ordine standard: sessione -> processo -> disco -> build.
    Ogni accesso produce un evento nel render log, così il costo è spiegabile.
    """

    page_id = str(page_id or "unknown")
    layer = str(layer or "artifact")
    signature = str(signature or "no-signature")
    disk_codec = _normalize_disk_codec(disk_codec)
    cache_key = (page_id, layer, signature)
    session_key = _session_key(page_id, layer, signature)
    started_at = time.perf_counter()
    source = "build"
    disk_detail = ""

    if session_key in st.session_state:
        value = st.session_state[session_key]
        source = "session"
    elif cache_key in _PROCESS_CACHE:
        value = _PROCESS_CACHE[cache_key]
        source = "process"
        st.session_state[session_key] = value
    else:
        preferred_path = _disk_path(page_id, layer, signature, disk_codec=disk_codec)
        fallback_codec = "gzip" if disk_codec == "pickle" else "pickle"
        fallback_path = _disk_path(page_id, layer, signature, disk_codec=fallback_codec)
        preferred_exists_before = preferred_path.exists()
        fallback_exists_before = fallback_path.exists()
        value = _load_from_disk(page_id, layer, signature, disk_codec=disk_codec) if persist_disk else None
        if value is not None:
            source = "disk"
            _PROCESS_CACHE[cache_key] = value
            st.session_state[session_key] = value
            loaded_codec = disk_codec if preferred_exists_before else fallback_codec
            migrated = False
            if persist_disk and disk_codec != "gzip" and not preferred_path.exists():
                _save_to_disk(page_id, layer, signature, value, disk_codec=disk_codec)
                migrated = fallback_exists_before
            disk_detail = f"; codec={loaded_codec}"
            if migrated:
                disk_detail += f"->{disk_codec}"
        else:
            value = builder()
            _PROCESS_CACHE[cache_key] = value
            st.session_state[session_key] = value
            if persist_disk:
                _save_to_disk(page_id, layer, signature, value, disk_codec=disk_codec)
            disk_detail = f"; codec={disk_codec}"

    elapsed = time.perf_counter() - started_at
    try:
        record_render_event(
            profile_page or page_id,
            f"L3 page artifact {layer}",
            elapsed,
            detail=f"source={source}; sig={signature}{disk_detail}",
        )
    except Exception:
        pass

    return PageArtifact(
        page_id=page_id,
        layer=layer,
        signature=signature,
        source=source,
        value=_clone_if_requested(value, clone=clone_on_read),
    )


def clear_page_artifact_process_cache() -> None:
    """Utility diagnostica/test: svuota solo la cache process degli artefatti pagina."""

    _PROCESS_CACHE.clear()


def get_page_artifact_runtime_stats() -> dict[str, Any]:
    """Snapshot leggero della cache runtime, senza scansioni disco.

    Serve nel render log per distinguere un vero warm rerun da un riavvio
    processo/sessione: se session/process sono vuoti, il disco e' atteso.
    """

    session_entries = 0
    session_layers: dict[str, int] = {}
    try:
        keys = list(st.session_state.keys())
        for raw_key in keys:
            key = str(raw_key)
            if not key.startswith("_page_artifact::"):
                continue
            session_entries += 1
            parts = key.split("::")
            if len(parts) >= 3:
                layer_key = f"{parts[1]}.{parts[2]}"
                session_layers[layer_key] = session_layers.get(layer_key, 0) + 1
    except Exception:
        session_entries = 0
        session_layers = {}

    process_layers: dict[str, int] = {}
    for page_id, layer, _signature in list(_PROCESS_CACHE.keys()):
        layer_key = f"{page_id}.{layer}"
        process_layers[layer_key] = process_layers.get(layer_key, 0) + 1

    return {
        "schema": CACHE_SCHEMA_VERSION,
        "process_entries": len(_PROCESS_CACHE),
        "session_entries": session_entries,
        "process_layers": dict(sorted(process_layers.items())),
        "session_layers": dict(sorted(session_layers.items())),
    }


def list_page_artifact_cache_rows() -> list[dict[str, Any]]:
    """Righe diagnostiche read-only per la cache artefatti pagina."""

    manifest = _read_manifest()
    rows: list[dict[str, Any]] = []
    for entry in (manifest.get("entries", {}) or {}).values():
        if not isinstance(entry, dict):
            continue
        path = Path(str(entry.get("path") or ""))
        exists = path.exists()
        try:
            size_bytes = int(path.stat().st_size) if exists else int(entry.get("size_bytes", 0) or 0)
        except Exception:
            size_bytes = int(entry.get("size_bytes", 0) or 0)
        rows.append(
            {
                "page_id": str(entry.get("page_id") or ""),
                "layer": str(entry.get("layer") or ""),
                "signature": str(entry.get("signature") or ""),
                "file": str(entry.get("file") or path.name),
                "size_bytes": size_bytes,
                "created_at": float(entry.get("created_at", 0.0) or 0.0),
                "value_kind": str(entry.get("value_kind") or ""),
                "exists": bool(exists),
            }
        )
    return sorted(rows, key=lambda item: float(item.get("created_at", 0.0) or 0.0), reverse=True)


def get_page_artifact_cache_stats() -> dict[str, Any]:
    """Statistiche leggere per Dati/diagnostica sugli artefatti pagina."""

    rows = list_page_artifact_cache_rows()
    rebuilt_manifest = False
    if not rows and _has_disk_artifact_files():
        rebuild_page_artifact_manifest()
        rows = list_page_artifact_cache_rows()
        rebuilt_manifest = True
    by_page: dict[str, int] = {}
    by_layer: dict[str, int] = {}
    missing_files = 0
    total_size_bytes = 0
    for row in rows:
        by_page[str(row.get("page_id") or "n/d")] = by_page.get(str(row.get("page_id") or "n/d"), 0) + 1
        by_layer[str(row.get("layer") or "n/d")] = by_layer.get(str(row.get("layer") or "n/d"), 0) + 1
        total_size_bytes += int(row.get("size_bytes", 0) or 0)
        if not bool(row.get("exists")):
            missing_files += 1
    return {
        "schema": CACHE_SCHEMA_VERSION,
        "num_entries": len(rows),
        "process_entries": len(_PROCESS_CACHE),
        "total_size_bytes": total_size_bytes,
        "total_size_mb": round(total_size_bytes / (1024 * 1024), 2),
        "missing_files": missing_files,
        "by_page": by_page,
        "by_layer": by_layer,
        "rebuilt_manifest": rebuilt_manifest,
        "manifest_file": str(PAGE_ARTIFACT_MANIFEST_FILE),
        "cache_dir": str(PAGE_ARTIFACT_CACHE_DIR),
    }


def clear_page_artifact_disk_cache(*, page_id: str | None = None, layer: str | None = None) -> int:
    """Svuota in modo selettivo gli artefatti pagina su disco.

    Non viene chiamata automaticamente: serve a Dati/test/manutenzione esplicita.
    """

    wanted_page = str(page_id or "").strip()
    wanted_layer = str(layer or "").strip()
    manifest = _read_manifest()
    entries = dict(manifest.get("entries", {}) or {})
    removed = 0
    kept: dict[str, Any] = {}
    for key, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        if wanted_page and str(entry.get("page_id") or "") != wanted_page:
            kept[key] = entry
            continue
        if wanted_layer and str(entry.get("layer") or "") != wanted_layer:
            kept[key] = entry
            continue
        try:
            path = Path(str(entry.get("path") or ""))
            candidate_paths = {path}
            entry_page = str(entry.get("page_id") or "")
            entry_layer = str(entry.get("layer") or "")
            entry_signature = str(entry.get("signature") or "")
            if entry_page and entry_layer and entry_signature:
                candidate_paths.add(_disk_path(entry_page, entry_layer, entry_signature, disk_codec="gzip"))
                candidate_paths.add(_disk_path(entry_page, entry_layer, entry_signature, disk_codec="pickle"))
            for candidate in candidate_paths:
                if candidate.exists():
                    candidate.unlink()
                    removed += 1
        except Exception as exc:
            logger.warning("Rimozione page artifact fallita per %s: %s", key, exc)
            kept[key] = entry
    manifest["entries"] = kept
    _write_manifest(manifest)
    if wanted_page or wanted_layer:
        for key in list(_PROCESS_CACHE.keys()):
            key_page, key_layer, _sig = key
            if wanted_page and key_page != wanted_page:
                continue
            if wanted_layer and key_layer != wanted_layer:
                continue
            _PROCESS_CACHE.pop(key, None)
    else:
        _PROCESS_CACHE.clear()
    return removed
