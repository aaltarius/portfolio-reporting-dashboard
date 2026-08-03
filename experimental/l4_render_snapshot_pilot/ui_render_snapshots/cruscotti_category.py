from __future__ import annotations

import html
import importlib.util
from typing import Any, Callable

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

from ui.formatting import fmt_date_only_it, fmt_eur_it, fmt_num_it, fmt_pct_it
from ui.theme import P


_KALEIDO_AVAILABLE = importlib.util.find_spec("kaleido") is not None


class SnapshotUnavailable(RuntimeError):
    """Lo snapshot statico non e' producibile in questo ambiente."""


def static_figure_export_available() -> bool:
    return bool(_KALEIDO_AVAILABLE)


def _format_metric(metric: dict[str, Any]) -> tuple[str, str, str, str | None]:
    label = str(metric.get("label") or "-")
    kind = str(metric.get("kind") or "")
    value = metric.get("value")
    note = str(metric.get("note") or "")
    value_color = None
    if kind == "date_with_duration":
        display = fmt_date_only_it(value) if value is not None else "-"
    elif kind == "date":
        display = fmt_date_only_it(value) if value is not None else "-"
    elif kind == "int":
        display = fmt_num_it(value, 0) if value is not None else "-"
    elif kind == "float2":
        display = fmt_num_it(value, 2) if value is not None else "-"
    elif kind == "eur":
        display = fmt_eur_it(value, 2) if value is not None else "-"
    elif kind == "eur_signed":
        display = fmt_eur_it(value, 2, signed=True) if value is not None else "-"
        if value is not None:
            value_color = P["green"] if float(value) >= 0 else P["red"]
    elif kind == "pct":
        display = fmt_pct_it(value, 2, signed=True) if value is not None else "-"
        if value is not None:
            value_color = P["green"] if float(value) >= 0 else P["red"]
    else:
        display = str(value) if value not in (None, "") else "-"
    return label, display, note, value_color


def _metric_cards_html(metrics: list[dict[str, Any]], accent: str) -> str:
    cards: list[str] = []
    for metric in metrics or []:
        label, display, note, value_color = _format_metric(metric)
        value_style = f"color:{html.escape(value_color)};" if value_color else ""
        cards.append(
            "<div class='snapshot-kpi' style='--accent:{accent};'>"
            "<div class='snapshot-kpi-label'>{label}</div>"
            "<div class='snapshot-kpi-value' style='{value_style}'>{display}</div>"
            "<div class='snapshot-kpi-note'>{note}</div>"
            "</div>".format(
                accent=html.escape(str(accent)),
                label=html.escape(label),
                display=html.escape(display),
                note=html.escape(note),
                value_style=value_style,
            )
        )
    return f"<div class='snapshot-kpi-grid'>{''.join(cards)}</div>" if cards else ""


def _section(title: str, body: str, *, note: str = "", icon_color: str = "") -> str:
    note_html = f"<p class='snapshot-note'>{html.escape(note)}</p>" if note else ""
    accent_style = f"style='--section-accent:{html.escape(icon_color)};'" if icon_color else ""
    return (
        f"<section class='snapshot-section' {accent_style}>"
        f"<h2><span></span>{html.escape(title)}</h2>"
        f"{note_html}{body}</section>"
    )


def _figure_svg_html(fig: Any, *, title: str, width: int = 1180, height: int = 430) -> str:
    if fig is None:
        return f"<div class='snapshot-empty'>Grafico {html.escape(title)} non disponibile.</div>"
    if not static_figure_export_available():
        raise SnapshotUnavailable("kaleido non disponibile")
    try:
        clone = go.Figure(fig)
        clone.update_layout(width=width, height=height, autosize=False)
        svg = pio.to_image(clone, format="svg", width=width, height=height, scale=1)
        if isinstance(svg, bytes):
            svg_text = svg.decode("utf-8", errors="replace")
        else:
            svg_text = str(svg)
        if "<svg" not in svg_text[:200].lower():
            raise SnapshotUnavailable("export statico non valido")
        return f"<div class='snapshot-figure' aria-label='{html.escape(title)}'>{svg_text}</div>"
    except SnapshotUnavailable:
        raise
    except Exception as exc:
        raise SnapshotUnavailable(str(exc)) from exc


def _two_col(left: str, right: str) -> str:
    return f"<div class='snapshot-two-col'><div>{left}</div><div>{right}</div></div>"


def _page_css() -> str:
    return """
    *{box-sizing:border-box}
    html,body{margin:0;padding:0;background:transparent;color:#1f2937;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:14px;line-height:1.42}
    .snapshot-page{width:100%;padding:2px 2px 10px 2px}
    .snapshot-title{display:flex;align-items:flex-start;gap:12px;margin:0 0 10px 0}
    .snapshot-title-mark{width:6px;align-self:stretch;min-height:44px;border-radius:999px;background:var(--snapshot-accent)}
    .snapshot-title h1{margin:0;color:#111827;font-size:1.18rem;line-height:1.18;font-weight:820;letter-spacing:0}
    .snapshot-title p{margin:5px 0 0 0;color:#64748b;font-size:.88rem}
    .snapshot-kpi-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:6px 0 12px 0}
    .snapshot-kpi{border:1px solid rgba(148,163,184,.34);border-top:3px solid var(--accent);border-radius:8px;background:#fff;padding:10px 11px;min-height:84px;box-shadow:0 2px 8px rgba(15,23,42,.035)}
    .snapshot-kpi-label{font-size:.69rem;text-transform:uppercase;letter-spacing:.03em;color:#64748b;font-weight:760;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .snapshot-kpi-value{margin-top:5px;font-size:1.05rem;font-weight:820;color:#111827;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .snapshot-kpi-note{margin-top:3px;font-size:.76rem;color:#64748b;min-height:1em}
    .snapshot-section{margin:0 0 14px 0;padding:0;background:transparent}
    .snapshot-section h2{display:flex;align-items:center;gap:8px;margin:0 0 7px 0;color:#111827;font-size:1.02rem;line-height:1.22;font-weight:800}
    .snapshot-section h2 span{display:inline-block;width:18px;height:18px;border-radius:999px;background:color-mix(in srgb, var(--section-accent, #2563eb) 16%, white);border:1px solid color-mix(in srgb, var(--section-accent, #2563eb) 34%, white)}
    .snapshot-note{margin:0 0 9px 0;color:#64748b;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px;font-size:.84rem}
    .snapshot-figure{width:100%;overflow:hidden;border:1px solid #e2e8f0;border-radius:8px;background:#fff;margin:0 0 10px 0}
    .snapshot-figure svg{display:block;width:100%;height:auto}
    .snapshot-two-col{display:grid;grid-template-columns:1fr 1fr;gap:12px;align-items:start}
    .snapshot-empty{border:1px dashed #cbd5e1;border-radius:8px;padding:16px;color:#64748b;background:#f8fafc}
    .snapshot-pl-table{margin-top:4px}
    .snapshot-pl-table .pl-horizon-table-wrap{border-radius:8px}
    @media(max-width:820px){.snapshot-kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.snapshot-two-col{grid-template-columns:1fr}}
    """


def build_category_render_snapshot_html(
    bundle: Any,
    *,
    show_explanations: bool,
    accent: str,
    pl_horizon_table_html_builder: Callable[[pd.DataFrame, str, pd.DataFrame | None], str],
) -> dict[str, Any]:
    """Costruisce uno snapshot HTML statico per una tab categoria Cruscotti."""

    if not static_figure_export_available():
        raise SnapshotUnavailable("kaleido non disponibile")

    title = str(getattr(bundle, "title", "") or getattr(bundle, "category", "Cruscotto"))
    intro = str(getattr(bundle, "intro_text", "") or "") if show_explanations else ""
    category = str(getattr(bundle, "category", "") or "")
    metrics_html = _metric_cards_html(list(getattr(bundle, "metrics", []) or []), accent)
    figures: list[str] = []
    figures.append(_section("Sintesi della categoria", _figure_svg_html(getattr(bundle, "compact_figure", None), title="Sintesi categoria", height=390), icon_color=accent))
    figures.append(_section("Andamento del comparto", _figure_svg_html(getattr(bundle, "temporal_figure", None), title="Andamento comparto", height=430), icon_color=accent))
    figures.append(
        _two_col(
            _section("Distribuzione controvalore", _figure_svg_html(getattr(bundle, "value_pie_figure", None), title="Distribuzione controvalore", height=360), icon_color=accent),
            _section("Capitale investito vs P/L", _figure_svg_html(getattr(bundle, "capital_pl_pie_figure", None), title="Capitale investito vs P/L", height=360), icon_color=accent),
        )
    )
    invested_fig = getattr(bundle, "invested_vs_pl_figure", None)
    if invested_fig is not None:
        figures.append(_section("Investito vs P/L", _figure_svg_html(invested_fig, title="Investito vs P/L", height=390), icon_color=accent))
    drawdown_fig = getattr(bundle, "drawdown_figure", None)
    if drawdown_fig is not None:
        figures.append(_section("Drawdown", _figure_svg_html(drawdown_fig, title="Drawdown", height=360), icon_color=accent))
    monthly_fig = getattr(bundle, "monthly_returns_figure", None)
    if monthly_fig is not None:
        figures.append(_section("Rendimenti mensili", _figure_svg_html(monthly_fig, title="Rendimenti mensili", height=360), icon_color=accent))

    pl_table = getattr(bundle, "pl_horizon_table", None)
    table_html = ""
    row_count = 0
    if pl_table is not None and not getattr(pl_table, "empty", True):
        row_count = len(pl_table)
        table_html = pl_horizon_table_html_builder(pl_table, accent, getattr(bundle, "df", None))
        figures.append(
            _section(
                "Contributo P/L per orizzonte",
                f"<div class='snapshot-pl-table'>{table_html}</div>",
                note="Delta in euro per strumento: frecce e asterischi mantengono la stessa lettura della tabella nativa.",
                icon_color=accent,
            )
        )

    body = (
        f"<div class='snapshot-page' style='--snapshot-accent:{html.escape(accent)}'>"
        f"<div class='snapshot-title'><span class='snapshot-title-mark'></span><div><h1>{html.escape(title)}</h1>"
        f"<p>{html.escape(intro)}</p></div></div>"
        f"{metrics_html}{''.join(figures)}</div>"
    )
    estimated_height = 130 + (95 * max(1, (len(list(getattr(bundle, "metrics", []) or [])) + 3) // 4))
    estimated_height += 390 + 430 + 390 + 380
    estimated_height += 390 if invested_fig is not None else 0
    estimated_height += 360 if drawdown_fig is not None else 0
    estimated_height += 360 if monthly_fig is not None else 0
    estimated_height += 120 + (34 * row_count) if table_html else 0
    return {
        "html": f"<!doctype html><html><head><meta charset='utf-8'><style>{_page_css()}</style></head><body>{body}</body></html>",
        "height": min(max(900, estimated_height), 5200),
        "meta": {
            "category": category,
            "figures": len(figures),
            "rows": row_count,
            "static_export": "svg",
        },
    }
