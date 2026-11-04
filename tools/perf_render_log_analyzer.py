from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


PAGE_ATTENTION_SECONDS = {
    "Mercati": 0.50,
    "Summary": 0.80,
    "Confronto": 0.80,
    "Dati": 0.50,
    "Quotazioni": 5.00,
    "Portafoglio": 2.50,
    "Cruscotti": 7.00,
}

PAGE_TARGET_SECONDS = {
    "Mercati": 0.10,
    "Summary": 0.30,
    "Confronto": 0.30,
    "Dati": 0.10,
    "Quotazioni": 3.00,
    "Portafoglio": 1.50,
    "Cruscotti": 4.00,
}

TOTAL_ATTENTION_SECONDS = 15.00
TOTAL_TARGET_SECONDS = 10.00


@dataclass(frozen=True)
class PageTiming:
    name: str
    seconds: float
    status: str


@dataclass(frozen=True)
class ProfileCoverage:
    page: str
    page_seconds: float
    root_step_seconds: float
    gap_seconds: float
    all_child_seconds: float
    nested_overlap_seconds: float


@dataclass(frozen=True)
class ExclusiveEvent:
    label: str
    total_seconds: float
    child_seconds: float
    exclusive_seconds: float
    depth: int
    count: str
    detail: str


@dataclass(frozen=True)
class CacheEvent:
    label: str
    seconds: float
    status: str
    detail: str


@dataclass(frozen=True)
class RenderLogAnalysis:
    total_seconds: float | None
    signature_diff: str
    dirty_flags: str
    pages: list[PageTiming]
    coverage: list[ProfileCoverage]
    exclusive_events: list[ExclusiveEvent]
    cache_events: list[CacheEvent]

    @property
    def figure_cache_hits(self) -> int:
        return sum(1 for item in self.cache_events if "cache_hit" in item.detail)

    @property
    def figure_cache_misses(self) -> int:
        return sum(1 for item in self.cache_events if "cache_miss" in item.detail)

    @property
    def page_artifact_builds(self) -> list[CacheEvent]:
        return [
            item
            for item in self.cache_events
            if "L3 page artifact" in item.label and "source=build" in item.detail
        ]


def _plain_page_name(raw: str) -> str:
    cleaned = re.sub(r"[^\w &/]+", "", raw, flags=re.UNICODE).strip()
    aliases = {
        "Gestione Dati": "Dati",
        "Setup": "Setup",
    }
    return aliases.get(cleaned, cleaned)


def _parse_float(value: str) -> float:
    return float(value.strip().replace(",", "."))


def parse_render_log(text: str) -> RenderLogAnalysis:
    total_seconds: float | None = None
    signature_diff = ""
    dirty_flags = ""
    pages: list[PageTiming] = []
    coverage: list[ProfileCoverage] = []
    exclusive_events: list[ExclusiveEvent] = []
    cache_events: list[CacheEvent] = []

    in_page_timings = False
    in_coverage = False
    in_exclusive = False

    page_line = re.compile(r"^\s*\d+\.\s*(?P<name>.+?)\s+\|\s+(?P<sec>\d+(?:[.,]\d+)?)s\s+\|\s+(?P<status>\w+)")
    coverage_line = re.compile(
        r"^(?P<page>.+?)\s+\|\s+(?P<page_sec>\d+(?:[.,]\d+)?)s\s+\|\s+"
        r"(?P<root>\d+(?:[.,]\d+)?)s\s+\|\s+(?P<gap>\d+(?:[.,]\d+)?)s\s+\|\s+"
        r"(?P<all>\d+(?:[.,]\d+)?)s\s+\|\s+(?P<overlap>\d+(?:[.,]\d+)?)s"
    )
    event_line = re.compile(
        r"^(?P<label>.+?)\s+\|\s*(?P<total>\d+(?:[.,]\d+)?)s\s+\|\s*"
        r"(?P<children>\d+(?:[.,]\d+)?)s\s+\|\s*(?P<exclusive>\d+(?:[.,]\d+)?)s\s+\|\s*"
        r"(?P<depth>\d+)\s+\|\s*(?P<count>[^|]*)\|\s*(?P<detail>.*)$"
    )
    cache_line = re.compile(
        r"^(?P<label>.+?)\s+\|\s+(?P<sec>\d+(?:[.,]\d+)?)s\s+\|\s+(?P<status>CACHE|OK)\s+\|\s*(?P<detail>.*)$"
    )

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("dirty_flags:"):
            dirty_flags = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("signature_diff:"):
            signature_diff = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("totale_render_secondi:"):
            total_seconds = _parse_float(stripped.split(":", 1)[1])

        if stripped == "--- Tempi per pagina ---":
            in_page_timings = True
            in_coverage = False
            in_exclusive = False
            continue
        if stripped.startswith("=== COPERTURA PROFILING"):
            in_page_timings = False
            in_coverage = True
            in_exclusive = False
            continue
        if stripped.startswith("=== PROFILING AD ALBERO"):
            in_page_timings = False
            in_coverage = False
            in_exclusive = True
            continue
        if stripped.startswith("--- ") or stripped.startswith("==="):
            if in_page_timings:
                in_page_timings = False
            if in_coverage and not stripped.startswith("=== COPERTURA"):
                in_coverage = False

        if in_page_timings:
            match = page_line.match(stripped)
            if match:
                pages.append(
                    PageTiming(
                        name=_plain_page_name(match.group("name")),
                        seconds=_parse_float(match.group("sec")),
                        status=match.group("status"),
                    )
                )
            continue

        if in_coverage:
            match = coverage_line.match(stripped)
            if match and not stripped.startswith("Pagina"):
                coverage.append(
                    ProfileCoverage(
                        page=_plain_page_name(match.group("page")),
                        page_seconds=_parse_float(match.group("page_sec")),
                        root_step_seconds=_parse_float(match.group("root")),
                        gap_seconds=_parse_float(match.group("gap")),
                        all_child_seconds=_parse_float(match.group("all")),
                        nested_overlap_seconds=_parse_float(match.group("overlap")),
                    )
                )
            continue

        if in_exclusive:
            match = event_line.match(line)
            if match and not stripped.startswith("Evento"):
                label = match.group("label").strip()
                total_seconds_value = _parse_float(match.group("total"))
                detail = match.group("detail").strip()
                exclusive_events.append(
                    ExclusiveEvent(
                        label=label,
                        total_seconds=total_seconds_value,
                        child_seconds=_parse_float(match.group("children")),
                        exclusive_seconds=_parse_float(match.group("exclusive")),
                        depth=int(match.group("depth")),
                        count=match.group("count").strip(),
                        detail=detail,
                    )
                )
                if "source=" in detail or "cache_" in detail:
                    cache_events.append(
                        CacheEvent(
                            label=label,
                            seconds=total_seconds_value,
                            status="OK",
                            detail=detail,
                        )
                    )

        match = cache_line.match(stripped)
        if match:
            detail = match.group("detail").strip()
            status = match.group("status")
            label = match.group("label").strip()
            if status == "CACHE" or "source=" in detail or "cache_" in detail:
                cache_events.append(
                    CacheEvent(
                        label=label,
                        seconds=_parse_float(match.group("sec")),
                        status=status,
                        detail=detail,
                    )
                )

    return RenderLogAnalysis(
        total_seconds=total_seconds,
        signature_diff=signature_diff,
        dirty_flags=dirty_flags,
        pages=pages,
        coverage=coverage,
        exclusive_events=exclusive_events,
        cache_events=cache_events,
    )


def _status_for(value: float, target: float, attention: float) -> str:
    if value <= target:
        return "OK"
    if value <= attention:
        return "WATCH"
    return "ALERT"


def format_markdown_report(analysis: RenderLogAnalysis, *, top_n: int = 10) -> str:
    lines: list[str] = []
    lines.append("# Analisi render log")
    lines.append("")

    total = analysis.total_seconds
    if total is None:
        lines.append("- Totale render: n/d")
    else:
        status = _status_for(total, TOTAL_TARGET_SECONDS, TOTAL_ATTENTION_SECONDS)
        lines.append(f"- Totale render: {total:.3f}s ({status}; target {TOTAL_TARGET_SECONDS:.1f}s, attenzione {TOTAL_ATTENTION_SECONDS:.1f}s)")
    lines.append(f"- Firma dati: {analysis.signature_diff or 'n/d'}")
    lines.append(f"- Dirty flags: {analysis.dirty_flags or 'n/d'}")
    lines.append(f"- Figure cache: {analysis.figure_cache_hits} hit, {analysis.figure_cache_misses} miss")
    lines.append(f"- Artefatti pagina rebuild: {len(analysis.page_artifact_builds)}")
    lines.append("")

    lines.append("## Tempi pagina")
    lines.append("| Pagina | Tempo | Stato | Target | Attenzione |")
    lines.append("|---|---:|---|---:|---:|")
    for page in analysis.pages:
        target = PAGE_TARGET_SECONDS.get(page.name)
        attention = PAGE_ATTENTION_SECONDS.get(page.name)
        if target is None or attention is None:
            status = "INFO"
            target_text = "-"
            attention_text = "-"
        else:
            status = _status_for(page.seconds, target, attention)
            target_text = f"{target:.2f}s"
            attention_text = f"{attention:.2f}s"
        lines.append(f"| {page.name} | {page.seconds:.3f}s | {status} | {target_text} | {attention_text} |")
    lines.append("")

    slow_events = sorted(analysis.exclusive_events, key=lambda item: item.exclusive_seconds, reverse=True)[:top_n]
    lines.append(f"## Top {len(slow_events)} eventi esclusivi")
    lines.append("| Evento | Esclusivo | Totale | Count | Dettaglio |")
    lines.append("|---|---:|---:|---:|---|")
    for event in slow_events:
        count = event.count or ""
        lines.append(
            f"| {event.label} | {event.exclusive_seconds:.3f}s | {event.total_seconds:.3f}s | {count} | {event.detail} |"
        )
    lines.append("")

    interesting_cache = [
        item
        for item in analysis.cache_events
        if "source=build" in item.detail or "cache_miss" in item.detail or item.seconds >= 0.05
    ][:top_n]
    lines.append("## Cache da verificare")
    if interesting_cache:
        lines.append("| Evento | Tempo | Stato | Dettaglio |")
        lines.append("|---|---:|---|---|")
        for item in interesting_cache:
            lines.append(f"| {item.label} | {item.seconds:.3f}s | {item.status} | {item.detail} |")
    else:
        lines.append("- Nessun rebuild/miss lento nei primi eventi profilati.")
    lines.append("")

    gaps = sorted(analysis.coverage, key=lambda item: item.gap_seconds, reverse=True)
    lines.append("## Gap profiling")
    lines.append("| Pagina | Gap non profilato | Overlap annidato |")
    lines.append("|---|---:|---:|")
    for item in gaps:
        if item.gap_seconds >= 0.05 or item.nested_overlap_seconds >= 0.50:
            lines.append(f"| {item.page} | {item.gap_seconds:.3f}s | {item.nested_overlap_seconds:.3f}s |")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze a Sestante render log.")
    parser.add_argument("log_file", type=Path)
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    text = args.log_file.read_text(encoding="utf-8", errors="replace")
    analysis = parse_render_log(text)
    print(format_markdown_report(analysis, top_n=args.top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
