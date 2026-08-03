"""
core/services/report_archive.py - Archivio locale dei report Summary.

Il modulo e' puro Python: salva HTML/JSON e mantiene un manifest leggero
usato dalla pagina Summary per riprendere o rimuovere report generati.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from persistence.storage import DATA_DIR

_SUMMARY_REPORTS_DIR = Path(DATA_DIR) / "reports" / "summary"
_SUMMARY_REPORTS_MANIFEST = _SUMMARY_REPORTS_DIR / "manifest.json"


def save_summary_report_archive(
    *,
    html_bytes: bytes,
    json_bytes: bytes,
    filename: str,
    payload: dict[str, Any] | None,
    options: dict[str, Any] | None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Salva un report Summary e aggiorna il manifest locale."""
    generated_at = generated_at or datetime.now()
    payload = payload or {}
    options = options or {}
    _SUMMARY_REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    stem = _safe_stem(Path(filename or "portfolio_report").stem)
    report_id = _unique_report_id(generated_at)
    html_file = f"{report_id}_{stem}.html"
    json_file = f"{report_id}_{stem}.json"
    html_path = _SUMMARY_REPORTS_DIR / html_file
    json_path = _SUMMARY_REPORTS_DIR / json_file
    html_path.write_bytes(html_bytes or b"")
    json_path.write_bytes(json_bytes or b"{}")

    entry = {
        "id": report_id,
        "saved_at": generated_at.isoformat(timespec="seconds"),
        "filename": filename,
        "html_file": html_file,
        "json_file": json_file,
        "html_size": int(html_path.stat().st_size),
        "json_size": int(json_path.stat().st_size),
        "period_label": str(options.get("period_label") or "ALL"),
        "period_start": _date_to_str(options.get("period_start")),
        "period_end": _date_to_str(options.get("period_end")),
        "portfolio_id": str(payload.get("portfolio_id") or "main"),
        "portfolio_name": str(payload.get("portfolio_name") or "Portafoglio"),
        "total_market_value": _finite_float(payload.get("total_market_value")),
        "total_pl": _finite_float(payload.get("total_pl")),
        "holdings_count": int(_finite_float(payload.get("holdings_count"))),
        "options": _compact_options(options),
    }
    manifest = [item for item in load_summary_report_manifest() if item.get("id") != report_id]
    manifest.insert(0, entry)
    _write_manifest(manifest)
    return entry


def load_summary_report_manifest(limit: int | None = None) -> list[dict[str, Any]]:
    if not _SUMMARY_REPORTS_MANIFEST.exists():
        return []
    try:
        raw = json.loads(_SUMMARY_REPORTS_MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        return []
    reports = raw.get("reports", raw) if isinstance(raw, dict) else raw
    if not isinstance(reports, list):
        return []
    cleaned = [item for item in reports if isinstance(item, dict) and item.get("id")]
    cleaned.sort(key=lambda item: str(item.get("saved_at") or item.get("id") or ""), reverse=True)
    return cleaned[:limit] if limit is not None else cleaned


def read_summary_report_file(report_id: str, kind: str = "html") -> bytes:
    entry = _find_report_entry(report_id)
    if not entry:
        return b""
    key = "json_file" if kind == "json" else "html_file"
    path = _safe_report_path(str(entry.get(key) or ""))
    if path is None or not path.exists():
        return b""
    try:
        return path.read_bytes()
    except Exception:
        return b""


def delete_summary_report(report_id: str) -> bool:
    entry = _find_report_entry(report_id)
    if not entry:
        return False
    deleted = False
    for key in ("html_file", "json_file"):
        path = _safe_report_path(str(entry.get(key) or ""))
        if path is None:
            continue
        try:
            path.unlink(missing_ok=True)
            deleted = True
        except Exception:
            pass
    manifest = [item for item in load_summary_report_manifest() if item.get("id") != report_id]
    _write_manifest(manifest)
    return deleted


def _find_report_entry(report_id: str) -> dict[str, Any] | None:
    report_id = str(report_id or "").strip()
    if not report_id:
        return None
    for entry in load_summary_report_manifest():
        if str(entry.get("id") or "") == report_id:
            return entry
    return None


def _write_manifest(reports: list[dict[str, Any]]) -> None:
    _SUMMARY_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "updated_at": datetime.now().isoformat(timespec="seconds"), "reports": reports}
    _SUMMARY_REPORTS_MANIFEST.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _safe_report_path(filename: str) -> Path | None:
    name = Path(filename).name
    if not name:
        return None
    path = (_SUMMARY_REPORTS_DIR / name).resolve()
    root = _SUMMARY_REPORTS_DIR.resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def _unique_report_id(generated_at: datetime) -> str:
    base = generated_at.strftime("%Y-%m-%d_%H-%M-%S")
    candidate = base
    suffix = 2
    existing = {str(item.get("id") or "") for item in load_summary_report_manifest()}
    while candidate in existing or any(_SUMMARY_REPORTS_DIR.glob(f"{candidate}_*")):
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def _safe_stem(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "portfolio_report")).strip("._")
    return safe[:90] or "portfolio_report"


def _date_to_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except Exception:
        return float(default)
    return result if result == result and abs(result) != float("inf") else float(default)


def _compact_options(options: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "include_charts",
        "include_tables",
        "include_benchmark",
        "include_operations",
        "include_income",
        "period_label",
        "period_start",
        "period_end",
    )
    return {key: _date_to_str(options.get(key)) for key in keep if key in options}
