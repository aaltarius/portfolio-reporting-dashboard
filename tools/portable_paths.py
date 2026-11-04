"""Migrazione e diagnosi di portabilita' dei file ausiliari di Sestante.

Uso dalla cartella principale del progetto:
  python -m tools.portable_paths --check
  python -m tools.portable_paths --apply

NON modifica SQLite, operazioni, posizioni, quotazioni o backup storici.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

WINDOWS_ABSOLUTE = re.compile(r"[A-Za-z]:\\\\")  # stringhe JSON Windows escaped


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _dump(path: Path, data: Any) -> None:
    # Scrittura atomica: un arresto durante il salvataggio non tronca il JSON.
    temp = path.with_name(path.name + ".portable-tmp")
    try:
        temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def _artifact_name(page_id: str, layer: str, signature: str, codec: str) -> str:
    import re as _re
    def safe(s):
        return _re.sub(r"[^A-Za-z0-9_.-]+", "_", str(s or "").strip()).strip("._") or "artifact"
    raw = json.dumps({"page_id": page_id, "layer": layer, "signature": signature},
                     sort_keys=True, ensure_ascii=True)
    stem = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    suffix = ".pickle" if codec == "pickle" else ".pickle.gz"
    return f"{safe(page_id)}__{safe(layer)}__{stem}{suffix}"


def migrate_manifest(payload: Any) -> tuple[Any, int]:
    if not isinstance(payload, dict):
        return payload, 0
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        return payload, 0
    changed = 0
    new = {}
    for key, entry in entries.items():
        if not isinstance(entry, dict):
            changed += 1
            continue
        page = str(entry.get("page_id") or "")
        layer = str(entry.get("layer") or "")
        signature = str(entry.get("signature") or "")
        if not (page and layer and signature):
            changed += 1
            continue
        codec = "pickle" if entry.get("disk_codec") == "pickle" else "gzip"
        candidates = (_artifact_name(page, layer, signature, codec),
                      _artifact_name(page, layer, signature, "gzip" if codec == "pickle" else "pickle"))
        label = str(entry.get("file") or "")
        if not label:
            label = str(entry.get("path") or "").replace("\\", "/").split("/")[-1]
        if label not in candidates:
            changed += 1
            continue
        normalized = dict(entry)
        normalized["file"] = label
        normalized["path"] = f"data/cache/page_artifacts/{label}"
        normalized["disk_codec"] = "pickle" if label.endswith(".pickle") else "gzip"
        new[key] = normalized
        changed += (normalized != entry)
    result = dict(payload)
    result["entries"] = new
    return result, changed


def _backup_reference(value: Any, current_project: str) -> tuple[Any, str | None]:
    if not isinstance(value, str):
        return value, None
    parts = [part for part in value.replace("\\", "/").split("/") if part and part != "."]
    indices = [i for i, part in enumerate(parts) if part.lower() == "backups"]
    if not indices:
        return value, None
    i = indices[-1]
    if i == len(parts) - 1 or any(part == ".." for part in parts[i+1:]):
        return value, None
    previous = parts[i-1] if i > 0 else None
    origin = previous if previous and previous.lower() != current_project.lower() else None
    return "backups/" + "/".join(parts[i+1:]), origin


def migrate_metadata(payload: Any, current_project: str) -> tuple[Any, int]:
    if not isinstance(payload, dict):
        return payload, 0
    changed = 0
    migration = payload.get("migration")
    if isinstance(migration, dict) and isinstance(migration.get("backup_file"), str):
        before = migration["backup_file"]
        after, origin = _backup_reference(before, current_project)
        if after != before:
            migration["backup_file"] = after
            if origin:
                migration.setdefault("historical_project", origin)
            changed += 1
    events = (payload.get("audit") or {}).get("events")
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict) or not isinstance(event.get("details"), dict):
                continue
            details = event["details"]
            for k in ("folder", "backup"):
                if isinstance(details.get(k), str):
                    before = details[k]
                    after, origin = _backup_reference(before, current_project)
                    if before != after:
                        details[k] = after
                        if origin:
                            details.setdefault("historical_project", origin)
                        changed += 1
    return payload, changed


def migrate_report(payload: Any) -> tuple[Any, int]:
    if not isinstance(payload, dict):
        return payload, 0
    changed = 0
    for key in ("database", "database_path"):
        value = str(payload.get(key) or "")
        if value and (value.replace("\\", "/").endswith("/data/indices/benchmarks.sqlite3")):
            if value != "data/indices/benchmarks.sqlite3":
                payload[key] = "data/indices/benchmarks.sqlite3"
                changed += 1
    return payload, changed


def migrate_receipt(payload: Any) -> tuple[Any, int]:
    if not isinstance(payload, dict) or not ("files" in payload and "data" in payload):
        return payload, 0
    old = payload.get("project")
    if old == ".":
        return payload, 0
    result = dict(payload)
    result["project"] = "."
    result["project_marker"] = "sestante-portable-backup-v1"
    return result, 1


def _plan(project: Path):
    def item(name: str, path: Path, processor):
        if path.is_file():
            yield name, path, processor
    yield from item("manifest", project / "data/cache/page_artifacts_manifest.json", migrate_manifest)
    yield from item("meta", project / "data/config/portafoglio_meta.json",
                    lambda p: migrate_metadata(p, project.name))
    for path in sorted((project / "data/indices").glob("rapporto*.json")):
        yield "report", path, migrate_report
    for path in sorted((project / "backups").glob("*/receipt.json")):
        yield "receipt", path, migrate_receipt


def _pointer_update(project: Path) -> tuple[Path | None, str | None]:
    path = project / "backups/ultimo_backup_benchmark_final.txt"
    if not path.is_file():
        return None, None
    raw = path.read_text(encoding="utf-8-sig").strip()
    if not raw:
        return path, None
    parts = raw.replace("\\", "/").split("/")
    name = parts[-1]
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        raise ValueError("Nome backup nel puntatore non valido")
    return path, f"backups/{name}"


def execute(project: Path, *, apply: bool = False) -> dict:
    project = project.resolve()
    if not (project / "app.py").is_file():
        raise ValueError(f"Cartella Sestante non valida: {project}")
    files = []
    counts = {}
    for kind, path, normalize in _plan(project):
        content = _read(path)
        updated, edits = normalize(content)
        if edits:
            files.append(str(path.relative_to(project)).replace("\\", "/"))
            counts[kind] = counts.get(kind, 0) + edits
            if apply:
                _dump(path, updated)
    pointer, target = _pointer_update(project)
    if pointer and target and pointer.read_text(encoding="utf-8-sig").strip() != target:
        files.append(str(pointer.relative_to(project)).replace("\\", "/"))
        counts["pointer"] = counts.get("pointer", 0) + 1
        if apply:
            pointer.write_text(target + "\n", encoding="utf-8")
    return {"mode": "apply" if apply else "dry_run", "modified_files": files,
            "changes_by_type": counts, "modified_count": len(files)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--apply", action="store_true", help="Converte i file correnti")
    modes.add_argument("--check", action="store_true", help="Non scrive: mostra i file da convertire")
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    opts = parser.parse_args(argv)
    try:
        report = execute(opts.project, apply=opts.apply)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"Portabilita': ERRORE: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
