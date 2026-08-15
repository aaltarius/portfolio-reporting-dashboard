from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from core.cache_policy import iter_cache_artifact_specs


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("app.py", "core", "ui")


PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("streamlit_cache", re.compile(r"@st\.cache_(?:data|resource)|st\.cache_(?:data|resource)\.clear\(")),
    ("page_artifact", re.compile(r"get_or_build_page_artifact\(")),
    ("figure_cache", re.compile(r"(?:get_registered_figure_cache\(\)|get_or_build_registered_figure\(|fcache)\.get_or_build\(")),
    ("session_cache", re.compile(r"st\.session_state\[[^\]]*cache[^\]]*\]|st\.session_state\.setdefault\([^)]*cache", re.IGNORECASE)),
    ("module_cache", re.compile(r"\b[A-Z0-9_]*_CACHE\b\s*[:=]|\bCACHE_DIR\b|\b_DERIVED_CACHE_DIR\b")),
    ("persistent_cache_file", re.compile(r"data[\"']?\s*/\s*[\"']?cache|BENCHMARK_CACHE_FILE|derived_runtime|\.pickle\.gz|\.json\.gz|\.pkl")),
    ("prewarm", re.compile(r"prewarm|cache_prewarmer|run_prewarm_bundle", re.IGNORECASE)),
    ("frozen_analysis", re.compile(r"frozen_analysis_cache|analytics_payload_cache|get_frozen_analysis_cache|store_frozen_analysis_cache")),
)


@dataclass(frozen=True)
class CacheHit:
    family: str
    path: Path
    line_no: int
    text: str


def _iter_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        path = PROJECT_ROOT / root
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(
                p
                for p in path.rglob("*.py")
                if "__pycache__" not in p.parts
                and not any(part.startswith(".") for part in p.relative_to(PROJECT_ROOT).parts)
            )
    return sorted(files)


def collect_cache_hits() -> list[CacheHit]:
    hits: list[CacheHit] = []
    for path in _iter_files():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            for family, pattern in PATTERNS:
                if pattern.search(stripped):
                    hits.append(CacheHit(family, path.relative_to(PROJECT_ROOT), idx, stripped[:180]))
    return hits


def build_markdown_report() -> str:
    hits = collect_cache_hits()
    by_family: dict[str, list[CacheHit]] = {}
    for hit in hits:
        by_family.setdefault(hit.family, []).append(hit)
    specs = tuple(iter_cache_artifact_specs())
    by_status: dict[str, int] = {}
    for spec in specs:
        by_status[spec.status] = by_status.get(spec.status, 0) + 1

    lines = [
        "# Audit statico superfici cache",
        "",
        "Questo report e' generato da `tools/cache_surface_audit.py` e serve a",
        "individuare tutte le superfici cache ancora presenti nel codice.",
        "",
        "## Registry centrale",
        "",
        "| Stato | Artefatti |",
        "|---|---:|",
    ]

    for status in sorted(by_status):
        lines.append(f"| `{status}` | {by_status[status]} |")

    legacy_specs = [spec.artifact_id for spec in specs if spec.status == "legacy_provider"]
    lines.extend([
        "",
        f"`legacy_provider`: {len(legacy_specs)}",
        "",
        "## Superfici trovate nel codice",
        "",
        "| Famiglia | Occorrenze | Lettura 5.0 |",
        "|---|---:|---|",
    ])

    explanations = {
        "streamlit_cache": "Ammessa solo per singleton documentati o reset esplicito; non per cache dati di pagina.",
        "page_artifact": "Percorso corretto per gli artefatti L3 ordinari.",
        "figure_cache": "Provider L3 registrato: ammesso tramite core.cache_orchestrator e FigureCache/manifest.",
        "session_cache": "Ammessa solo se legata a stato UI o provider registrato; vietata come cache dati opaca.",
        "module_cache": "Ammessa solo se registry/provider/runtime_cache ne definiscono owner e invalidazione.",
        "persistent_cache_file": "Ammessa come store registrato o file di appoggio dichiarato nel registry.",
        "prewarm": "Ammesso solo come prebuild guidato dal registry, mai come render differito visibile.",
        "frozen_analysis": "Provider registrato per analisi ad azione esplicita, senza rebuild globale.",
    }

    for family in sorted(by_family):
        lines.append(f"| `{family}` | {len(by_family[family])} | {explanations.get(family, '')} |")

    lines.extend(["", "## Dettaglio", ""])
    for family in sorted(by_family):
        lines.append(f"### {family}")
        lines.append("")
        for hit in by_family[family]:
            lines.append(f"- `{hit.path}:{hit.line_no}` - `{hit.text}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    print(build_markdown_report(), end="")


if __name__ == "__main__":
    main()
