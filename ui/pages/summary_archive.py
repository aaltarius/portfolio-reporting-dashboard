"""
ui/pages/summary_archive.py — Archivio dei report Summary: griglia a righe con anteprima.

Un report per riga (data, titolo e periodo, contenuti, valore e P/L, azioni).
L'anteprima si apre in un popup e, su richiesta, in una nuova scheda del browser.

Costo: a ogni rerun si legge solo il manifest (come prima) e si disegna HTML;
i file dei report si leggono soltanto quando l'utente apre un'anteprima.
Colori dalle variabili del tema (`--ptf-*`), nessun colore fisso.
"""
from __future__ import annotations

import base64
import html
from datetime import datetime
from typing import Any

import streamlit as st

from core.services.report_archive import (
    delete_summary_report,
    load_summary_report_manifest,
    read_summary_report_file,
)
from ui.formatting import fmt_eur_it
from ui.streamlit_compat import render_html_iframe
from ui.theme import get_theme_context

VISIBLE_REPORTS = 8
_MONTHS_IT = ("gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic")
_OPTION_TAGS = (
    ("include_charts", "Grafici"),
    ("include_tables", "Tabelle"),
    ("include_benchmark", "Benchmark"),
    ("include_operations", "Operazioni"),
    ("include_income", "Proventi"),
)
_ROW_RATIOS = [4.2, 2.3, 3.5]
_PERIOD_LABELS = {"1M": "Ultimo mese", "3M": "Ultimi 3 mesi", "6M": "Ultimi 6 mesi", "YTD": "Da inizio anno", "1Y": "Ultimo anno", "3Y": "Ultimi 3 anni", "ALL": "Dall'inizio", "Personalizzato": "Periodo personalizzato"}

_ARCHIVE_CSS = """
<style>
[class*="st-key-rpt_row_"]{
  border:1px solid var(--ptf-border);
  border-radius:16px;
  background:linear-gradient(135deg,var(--ptf-surface),color-mix(in srgb,var(--ptf-primary) 4%,var(--ptf-surface)));
  padding:.9rem 1rem!important;
  box-shadow:0 4px 14px rgba(15,23,42,.05);
  transition:border-color .15s ease, box-shadow .15s ease;
}
[class*="st-key-rpt_row_"]:hover{
  border-color:color-mix(in srgb,var(--ptf-primary) 45%,var(--ptf-border));
  box-shadow:0 8px 22px rgba(15,23,42,.10);
}
.rpt-head{display:grid;font-size:.68rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--ptf-muted);padding:0 .9rem;margin:.2rem 0 .1rem}
.rpt-info{display:flex;align-items:center;gap:14px;min-width:0;padding-bottom:1rem}
.rpt-date{flex:none;width:54px;border-radius:12px;overflow:hidden;text-align:center;border:1px solid var(--ptf-border);background:var(--ptf-surface)}
.rpt-date .m{background:var(--ptf-primary);color:#fff;font-size:.62rem;font-weight:800;letter-spacing:.1em;text-transform:uppercase;padding:2px 0}
.rpt-date .d{font-size:1.35rem;font-weight:850;line-height:1.15;color:var(--ptf-text)}
.rpt-date .y{font-size:.62rem;color:var(--ptf-muted);padding-bottom:3px}
.rpt-title{font-weight:750;font-size:.95rem;color:var(--ptf-text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rpt-meta{font-size:.78rem;color:var(--ptf-muted);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rpt-tags{display:flex;flex-wrap:nowrap;overflow:hidden;gap:5px;margin-top:6px}
.rpt-tag{white-space:nowrap;font-size:.66rem;font-weight:700;padding:1px 8px;border-radius:999px;color:var(--ptf-primary);background:color-mix(in srgb,var(--ptf-primary) 11%,transparent)}
.rpt-kpis{display:flex;gap:18px;align-items:center;height:100%;padding-bottom:1rem}
.rpt-kpi .l{font-size:.64rem;font-weight:800;letter-spacing:.07em;text-transform:uppercase;color:var(--ptf-muted)}
.rpt-kpi .v{font-size:1rem;font-weight:800;color:var(--ptf-text);font-variant-numeric:tabular-nums}
.rpt-kpi .v.pos{color:var(--ptf-success)}
.rpt-kpi .v.neg{color:var(--ptf-danger)}
.rpt-summary{font-size:.8rem;color:var(--ptf-muted);margin:.1rem 0 .5rem}
</style>
"""


def _parse_saved_at(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except Exception:
        return None


def _period_name(entry: dict[str, Any]) -> str:
    label = str(entry.get("period_label") or "ALL")
    return _PERIOD_LABELS.get(label, label)


def _fmt_period(entry: dict[str, Any]) -> str:
    start, end = str(entry.get("period_start") or ""), str(entry.get("period_end") or "")
    name = _period_name(entry)
    return f"{name} ({start or 'inizio'} → {end or 'oggi'})" if (start or end) else name


def _fmt_size(entry: dict[str, Any]) -> str:
    kb = (int(entry.get("html_size") or 0)) / 1024
    return f"{kb / 1024:.1f} MB" if kb >= 1024 else f"{kb:.0f} KB"


def _info_html(entry: dict[str, Any]) -> str:
    saved = _parse_saved_at(entry.get("saved_at"))
    month, day, year, hour = (
        (_MONTHS_IT[saved.month - 1], f"{saved.day:02d}", str(saved.year), saved.strftime("%H:%M")) if saved else ("—", "--", "", "")
    )
    options = entry.get("options") if isinstance(entry.get("options"), dict) else {}
    tags = "".join(f"<span class='rpt-tag'>{label}</span>" for key, label in _OPTION_TAGS if str(options.get(key)) == "True")
    name = str(entry.get("portfolio_name") or "Portafoglio")  # escapato una volta sola, nel join sotto
    title = html.escape(f"Report · {_period_name(entry)}")
    start, end = str(entry.get("period_start") or ""), str(entry.get("period_end") or "")
    holdings = int(entry.get("holdings_count") or 0)
    parts = [name, hour]
    if start or end:
        parts.append(f"{start or 'inizio'} → {end or 'oggi'}")
    if holdings:
        parts.append(f"{holdings} strumenti")
    parts.append(_fmt_size(entry))
    meta = html.escape(" · ".join(parts))
    return (
        "<div class='rpt-info'>"
        f"<div class='rpt-date'><div class='m'>{month}</div><div class='d'>{day}</div><div class='y'>{year}</div></div>"
        f"<div style='min-width:0'><div class='rpt-title' title='{html.escape(str(entry.get('filename') or ''))}'>{title}</div>"
        f"<div class='rpt-meta'>{meta}</div><div class='rpt-tags'>{tags}</div></div></div>"
    )


def _kpi_html(entry: dict[str, Any]) -> str:
    pl = float(entry.get("total_pl") or 0.0)
    cls = "pos" if pl > 0 else "neg" if pl < 0 else ""
    return (
        "<div class='rpt-kpis'>"
        f"<div class='rpt-kpi'><div class='l'>Valore</div><div class='v'>{fmt_eur_it(entry.get('total_market_value'), 0)}</div></div>"
        f"<div class='rpt-kpi'><div class='l'>P/L</div><div class='v {cls}'>{fmt_eur_it(pl, 0, signed=True)}</div></div>"
        "</div>"
    )


def _open_in_new_tab_html(html_bytes: bytes, primary: str) -> str:
    """Pulsante in un iframe: crea un Blob con il report e lo apre in una nuova scheda (solo al clic)."""
    payload = base64.b64encode(html_bytes).decode("ascii")
    return (
        "<style>body{margin:0}button{width:100%;height:40px;border-radius:10px;border:1px solid "
        f"{primary};background:transparent;color:{primary};font:600 14px system-ui,sans-serif;cursor:pointer}}"
        f"button:hover{{background:{primary};color:#fff}}</style>"
        "<button id='b'>Apri in una nuova scheda ↗</button>"
        f"<script>const D='{payload}';document.getElementById('b').onclick=()=>{{"
        "const u=Uint8Array.from(atob(D),c=>c.charCodeAt(0));"
        "const url=URL.createObjectURL(new Blob([u],{type:'text/html;charset=utf-8'}));"
        "window.open(url,'_blank');}</script>"
    )


@st.dialog("Anteprima report", width="large")
def _preview_dialog(report_id: str) -> None:
    entry = next((e for e in load_summary_report_manifest() if str(e.get("id")) == report_id), None)
    html_bytes = read_summary_report_file(report_id, "html")
    if not entry or not html_bytes:
        st.warning("File HTML non trovato per questo report.")
        return
    theme = get_theme_context()
    st.caption(f"{_fmt_period(entry)} · salvato il {(_parse_saved_at(entry.get('saved_at')) or datetime.now()):%d/%m/%Y %H:%M}")
    render_html_iframe(html_bytes.decode("utf-8", errors="replace"), height=620)
    c1, c2, c3 = st.columns(3, gap="small")
    with c1:
        render_html_iframe(_open_in_new_tab_html(html_bytes, str(theme.primary_color)), height=44)
    with c2:
        st.download_button(
            "Scarica HTML", data=html_bytes, file_name=str(entry.get("filename") or f"{report_id}.html"),
            mime="text/html", width="stretch", on_click="ignore", key=f"rpt_dl_{report_id}",
        )
    with c3:
        if st.button("Riprendi nel generatore", width="stretch", key=f"rpt_resume_{report_id}"):
            _resume(entry)
            st.rerun()


def _resume(entry: dict[str, Any]) -> None:
    report_id = str(entry.get("id") or "")
    html_bytes = read_summary_report_file(report_id, "html")
    if not html_bytes:
        st.warning("File HTML non trovato per questo report archiviato.")
        return
    saved = _parse_saved_at(entry.get("saved_at"))
    st.session_state["summary_report_output"] = {
        "html": html_bytes,
        "json": read_summary_report_file(report_id, "json"),
        "filename": str(entry.get("filename") or entry.get("html_file") or f"{report_id}.html"),
        "generated_at": saved.strftime("%d/%m/%Y %H:%M") if saved else "n/d",
        "archive_id": report_id,
    }


def _render_row(entry: dict[str, Any]) -> None:
    report_id = str(entry.get("id") or "")
    with st.container(key=f"rpt_row_{report_id}"):
        col_info, col_kpi, col_act = st.columns(_ROW_RATIOS, gap="small", vertical_alignment="center")
        col_info.markdown(_info_html(entry), unsafe_allow_html=True)
        col_kpi.markdown(_kpi_html(entry), unsafe_allow_html=True)
        with col_act:
            b1, b_dl, b2, b3 = st.columns([2.0, 0.8, 0.8, 0.8], gap="small")
            if b1.button("Anteprima", key=f"rpt_prev_{report_id}", icon=":material/visibility:", type="primary", width="stretch"):
                _preview_dialog(report_id)
            # Dati letti solo al clic (callable): nessuna lettura di file ad ogni rerun, nessun rerun al download.
            b_dl.download_button(
                "", data=lambda rid=report_id: read_summary_report_file(rid, "html"),
                file_name=str(entry.get("filename") or f"{report_id}.html"), mime="text/html",
                icon=":material/download:", width="stretch", on_click="ignore",
                key=f"rpt_dlrow_{report_id}", help="Scarica il report HTML",
            )
            if b2.button("", key=f"rpt_res_{report_id}", icon=":material/restore:", width="stretch",
                         help="Riprendi: riattiva i pulsanti di download del generatore con questo report."):
                _resume(entry)
                if st.session_state.get("summary_report_output", {}).get("archive_id") == report_id:
                    st.rerun()
            with b3.popover("", icon=":material/delete:", width="stretch", help="Elimina questo report"):
                st.caption("Eliminare definitivamente questo report?")
                if st.button("Sì, elimina", key=f"rpt_del_{report_id}", type="primary", width="stretch"):
                    delete_summary_report(report_id)
                    if (st.session_state.get("summary_report_output") or {}).get("archive_id") == report_id:
                        st.session_state.pop("summary_report_output", None)
                    st.rerun()


def render_report_archive() -> None:
    reports = load_summary_report_manifest()
    st.markdown(_ARCHIVE_CSS, unsafe_allow_html=True)
    if not reports:
        st.caption("Nessun report archiviato. Il prossimo report generato verrà salvato automaticamente qui.")
        return
    total_mb = sum(int(r.get("html_size") or 0) + int(r.get("json_size") or 0) for r in reports) / (1024 * 1024)
    st.markdown(
        f"<div class='rpt-summary'>{len(reports)} report salvati in locale · {total_mb:.1f} MB. "
        "Apri l'anteprima per sfogliarlo, aprirlo in una nuova scheda o scaricarlo.</div>",
        unsafe_allow_html=True,
    )
    cols = " ".join(f"{r}fr" for r in _ROW_RATIOS)
    st.markdown(
        f"<div class='rpt-head' style='grid-template-columns:{cols}'><div>Report</div><div>Valore e risultato</div><div></div></div>",
        unsafe_allow_html=True,
    )
    for entry in reports[:VISIBLE_REPORTS]:
        _render_row(entry)
    older = reports[VISIBLE_REPORTS:]
    if older:
        with st.expander(f"Report meno recenti ({len(older)})", expanded=False):
            for entry in older:
                _render_row(entry)
