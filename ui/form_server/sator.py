"""ui/form_server/sator.py — pagina SATOR del form-server (route /sator).

Estratto da form_server.py. Condivide la stessa pipeline di storage dell'app
principale: nessuna logica duplicata.
"""
from __future__ import annotations

import json
import logging
import math
from html import escape

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from ui.charts.instrument_badges import commission_badge
from ui.form_server.shell import STREAMLIT_URL, _ROOT_VARS_BLOCK

logger = logging.getLogger("portafoglio.form_server.sator")

router = APIRouter()

_SATOR_DEFAULT_CATS = ["ETF", "ETC"]
_SATOR_ALL_CATS = ["ETF", "ETC", "FONDO", "AZIONE", "BTP", "ALTRO"]

_SATOR_CSS = _ROOT_VARS_BLOCK + """
*,*::before,*::after{box-sizing:border-box}
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--slate-100);color:var(--slate-800);margin:0;padding:16px 20px 60px;font-size:.9rem}
.sp{max-width:1440px;margin:0 auto}
.sp-card{background:var(--white);border-radius:14px;padding:20px 24px;box-shadow:0 2px 10px var(--black-a06);margin-bottom:16px}
h1{font-size:1.15rem;font-weight:800;margin:0 0 14px;color:var(--slate-800)}
h2{font-size:.75rem;font-weight:800;text-transform:uppercase;letter-spacing:.06em;color:var(--slate-500);margin:0 0 14px}
label.lbl{display:block;font-weight:700;font-size:.72rem;text-transform:uppercase;letter-spacing:.04em;margin:0 0 4px;color:var(--slate-500)}
select,input[type=text],input[type=number]{width:100%;padding:8px 10px;border:1px solid var(--slate-300);border-radius:8px;font-size:.88rem;background:var(--white);outline:none;transition:border-color .15s,box-shadow .15s}
select:focus,input:focus{border-color:var(--indigo-500);box-shadow:0 0 0 3px var(--indigo-500-a12)}
.form-row{display:flex;gap:14px;align-items:flex-end;flex-wrap:wrap}
.fg{display:flex;flex-direction:column;gap:3px}
.fg-sm{min-width:100px}
.fg-md{min-width:150px}
.fg-lg{flex:1;min-width:180px}
.cat-wrap{display:flex;flex-wrap:wrap;gap:5px;margin-top:4px}
.cat-wrap label{display:inline-flex;align-items:center;gap:4px;font-size:.82rem;cursor:pointer;padding:4px 9px;border:1px solid var(--slate-200);border-radius:6px;background:var(--slate-50);transition:all .15s;user-select:none}
.cat-wrap label:hover{border-color:var(--indigo-500);background:var(--indigo-50)}
.cat-wrap input[type=checkbox]{accent-color:var(--indigo-500);width:13px;height:13px;flex-shrink:0}
.filter-check{display:inline-flex;align-items:center;gap:7px;font-size:.82rem;cursor:pointer;padding:8px 10px;border:1px solid var(--slate-200);border-radius:8px;background:var(--slate-50);color:var(--slate-600);user-select:none}
.filter-check:hover{border-color:var(--indigo-500);background:var(--indigo-50);color:var(--slate-800)}
.filter-check input{accent-color:var(--indigo-500);width:14px;height:14px;flex-shrink:0}
.btn-analizza{padding:9px 24px;background:var(--indigo-500);color:var(--white);border:none;border-radius:9px;font-size:.9rem;font-weight:700;cursor:pointer;white-space:nowrap;transition:background .15s}
.btn-analizza:hover{background:var(--indigo-600)}
.sp-body{display:flex;gap:16px;align-items:flex-start}
.sp-table-col{flex:1;min-width:0}
.sp-eval-panel{width:322px;flex-shrink:0;position:sticky;top:16px}
.sp-analysis-panel{display:none;padding-top:4px}
.sp-analysis-grid{display:grid;grid-template-columns:minmax(340px,1fr) minmax(340px,1fr);gap:14px;align-items:start}
.sp-analysis-grid .ev-block{margin:0;padding:0;border-bottom:none;min-width:0}
.sp-analysis-grid .ev-note{min-height:100%;font-size:.82rem}
.ev-h{font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--slate-400);margin:0 0 2px}
.ev-v{font-size:1.05rem;font-weight:800;color:var(--slate-800);transition:color .3s}
.ev-block{margin-bottom:14px;padding-bottom:14px;border-bottom:1px solid var(--slate-100)}
.ev-block:last-of-type{border-bottom:none;margin-bottom:0;padding-bottom:0}
.ev-row{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px}
.bar-wrap{background:var(--slate-200);border-radius:4px;height:7px;overflow:hidden;margin:3px 0 8px;position:relative}
.bar-fill{height:100%;border-radius:4px;transition:width .4s ease}
.bar-marker{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--slate-800);box-shadow:0 0 0 1px var(--white);opacity:.9;display:none}
.ev-headline{text-align:center;padding:10px 14px;border-radius:10px;font-weight:800;font-size:.9rem;margin:10px 0;display:none}
.ev-note{border:1px solid var(--slate-200);background:var(--slate-50);border-radius:10px;padding:10px 11px;font-size:.78rem;line-height:1.35;color:var(--slate-600)}
.ev-note strong{color:var(--slate-800)}
.ev-note .good{color:var(--green-700);font-weight:800}.ev-note .bad{color:var(--red-700);font-weight:800}.ev-note .warn{color:var(--amber-800);font-weight:800}
.ev-note ul{margin:7px 0 0;padding-left:16px}.ev-note li{margin:3px 0}
.ev-meter{margin:8px 0 10px}
.ev-meter-head{display:flex;justify-content:space-between;gap:8px;align-items:baseline;font-size:.76rem;margin-bottom:4px}
.ev-meter-head span:first-child{font-weight:800;color:var(--slate-700)}
.ev-meter-head span:last-child{font-weight:800;color:var(--slate-500);white-space:nowrap}
.ev-meter-track{height:8px;border-radius:999px;background:var(--slate-200);overflow:hidden;position:relative}
.ev-meter-fill{height:100%;width:0%;border-radius:999px;background:var(--slate-400);transition:width .28s ease,background .28s ease}
.ev-meter-marker{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--slate-800);box-shadow:0 0 0 1px var(--white);opacity:.9;display:none}
.ev-meter-caption{font-size:.69rem;color:var(--slate-400);margin-top:3px;line-height:1.25}
.decision-facts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:10px}
.decision-fact{border:1px solid var(--slate-200);background:var(--white);border-radius:8px;padding:8px 9px;min-width:0}
.decision-fact .k{font-size:.64rem;font-weight:850;text-transform:uppercase;letter-spacing:.04em;color:var(--slate-400);margin-bottom:3px}
.decision-fact .v{font-size:.8rem;font-weight:800;color:var(--slate-700);line-height:1.25}
.decision-pills{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}
.decision-pill{display:inline-flex;align-items:center;border-radius:7px;background:var(--slate-100);padding:3px 7px;font-size:.74rem;font-weight:800;color:var(--slate-700)}
.line-reasons{display:grid;gap:7px;margin-top:10px}
.line-reason{border:1px solid var(--slate-200);background:var(--white);border-radius:8px;padding:8px 9px}
.line-reason-head{display:flex;justify-content:space-between;gap:8px;align-items:baseline;margin-bottom:4px}
.line-reason-title{font-size:.82rem;font-weight:900;color:var(--slate-800);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.line-reason-meta{font-size:.69rem;font-weight:850;color:var(--slate-400);white-space:nowrap}
.line-reason-body{font-size:.76rem;color:var(--slate-600);line-height:1.32}
.line-reason-tags{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px}
.line-reason-tag{border-radius:7px;background:var(--slate-100);padding:2px 6px;font-size:.68rem;font-weight:800;color:var(--slate-600)}
.line-reason-tag.good{background:var(--green-50);color:var(--green-700)}
.line-reason-tag.warn{background:var(--yellow-50);color:var(--amber-800)}
.line-reason-tag.bad{background:var(--red-50);color:var(--red-700)}
.compare-head{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:10px 0}
.compare-metric{border:1px solid var(--slate-200);background:var(--white);border-radius:8px;padding:8px 9px;min-width:0}
.compare-metric .k{font-size:.63rem;font-weight:850;text-transform:uppercase;letter-spacing:.04em;color:var(--slate-400);margin-bottom:3px}
.compare-metric .v{font-size:.92rem;font-weight:900;color:var(--slate-800)}
.compare-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:8px 0}
.compare-card{border:1px solid var(--slate-200);background:var(--white);border-radius:8px;padding:9px 10px;min-width:0}
.compare-card .t{font-size:.66rem;font-weight:900;text-transform:uppercase;letter-spacing:.04em;margin-bottom:5px}
.compare-card.good .t{color:var(--green-700)}.compare-card.bad .t{color:var(--red-700)}.compare-card.neutral .t{color:var(--slate-500)}
.compare-card ul{margin:0;padding-left:16px}.compare-card li{margin:3px 0}
.quick-fix{border:1px solid var(--indigo-200);background:var(--indigo-50);border-radius:9px;padding:10px 12px;margin:10px 0 8px}
.quick-fix .t{font-size:.66rem;font-weight:900;text-transform:uppercase;letter-spacing:.05em;color:var(--indigo-600);margin-bottom:5px}
.quick-fix ol{margin:0;padding-left:18px}.quick-fix li{margin:4px 0}
.quick-fix-head{display:flex;justify-content:space-between;gap:8px;align-items:center;margin-bottom:5px}
.quick-action{margin-left:7px;border:1px solid var(--indigo-200);background:var(--white);color:var(--indigo-600);border-radius:7px;padding:2px 7px;font-size:.7rem;font-weight:850;cursor:pointer}
.quick-action:hover{background:var(--indigo-500);border-color:var(--indigo-500);color:var(--white)}
.quick-action:disabled{opacity:.45;cursor:not-allowed;background:var(--slate-100);color:var(--slate-400);border-color:var(--slate-200)}
.hist-compare{border:1px solid var(--indigo-200);background:var(--indigo-50);border-radius:10px;padding:12px 14px;margin:-4px 0 16px}
.hist-compare-title{display:flex;justify-content:space-between;gap:10px;align-items:baseline;margin-bottom:10px}
.hist-compare-title strong{font-size:.78rem;text-transform:uppercase;letter-spacing:.05em;color:var(--indigo-600)}
.hist-choice-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px}
.hist-choice{background:var(--white);border:1px solid var(--slate-200);border-radius:8px;padding:9px 10px;min-width:0}
.hist-choice.best{border-color:var(--green-300);box-shadow:0 0 0 2px var(--green-50)}
.hist-choice .rank{font-size:.65rem;font-weight:900;text-transform:uppercase;letter-spacing:.05em;color:var(--slate-400);margin-bottom:4px}
.hist-choice .score{font-size:1rem;font-weight:900;color:var(--slate-800)}
.hist-choice .meta{font-size:.72rem;color:var(--slate-500);line-height:1.35;margin-top:4px}
.note-inp{width:100%;padding:8px 10px;border:1px solid var(--slate-300);border-radius:8px;font-size:.84rem;outline:none;margin-bottom:8px}
.note-inp:focus{border-color:var(--emerald-600)}
.btn-save{display:block;width:100%;padding:11px;background:var(--emerald-600);color:var(--white);border:none;border-radius:9px;font-size:.9rem;font-weight:700;cursor:pointer;transition:background .15s}
.btn-save:hover{background:var(--emerald-700)}
.btn-save:disabled{background:var(--slate-400);cursor:not-allowed}
.sr-table{width:100%;border-collapse:collapse;table-layout:fixed;font-size:.8rem}
.sr-table th{text-align:left;font-size:.64rem;text-transform:uppercase;letter-spacing:.03em;color:var(--slate-400);font-weight:700;padding:4px 4px 8px;border-bottom:2px solid var(--slate-200);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sr-table td{padding:6px 4px;border-bottom:1px solid var(--slate-100);vertical-align:middle;overflow:hidden}
.sr-table tr:hover td{background:var(--slate-hover)}
.sr-table tr:last-child td{border-bottom:none}
.sr-row.sr-changed td{background:var(--indigo-50)}
.sr-row.sr-changed td:first-child{box-shadow:inset 3px 0 0 var(--indigo-500)}
.qta-changed{border-color:var(--indigo-500)!important;box-shadow:0 0 0 2px var(--indigo-500-a12)}
.sc-badge{display:inline-block;font-size:.72rem;font-weight:800;border-radius:4px;padding:2px 5px;line-height:1.2}
.sc-g{background:var(--green-100);color:var(--green-800)}.sc-m{background:var(--yellow-100);color:var(--yellow-800)}.sc-b{background:var(--red-100);color:var(--red-800)}
.rb-dot{display:inline-block;width:11px;height:11px;border-radius:3px;vertical-align:middle}
.rb-core{background:var(--blue-500)}.rb-dif{background:var(--green-500)}.rb-sat{background:var(--orange-500)}
.tbl-actions{display:flex;gap:8px;margin-bottom:12px;align-items:center;flex-wrap:wrap}
.btn-sm{padding:5px 12px;border:1px solid var(--slate-200);background:var(--slate-50);color:var(--slate-600);border-radius:7px;font-size:.78rem;font-weight:600;cursor:pointer;transition:all .15s;white-space:nowrap}
.btn-sm:hover{border-color:var(--indigo-500);color:var(--indigo-500);background:var(--indigo-50)}
.btn-sm-p{background:var(--indigo-50);color:var(--indigo-500);border-color:var(--indigo-200)}
.btn-sm-p:hover{background:var(--indigo-500);color:var(--white)}
.btn-filter-active{background:var(--indigo-500);color:var(--white);border-color:var(--indigo-500)}
.filter-count{font-size:.74rem;color:var(--slate-400);margin-left:4px}
.sort-wrap{display:inline-flex;align-items:center;gap:6px;margin-left:auto;font-size:.74rem;color:var(--slate-400)}
.sort-wrap select{width:auto;min-width:145px;padding:5px 8px;font-size:.78rem;border-radius:7px}
.hist-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:14px}
.hist-summary .box{border:1px solid var(--slate-200);border-radius:8px;background:var(--slate-50);padding:10px 12px}
.hist-summary .k{font-size:.66rem;font-weight:800;text-transform:uppercase;letter-spacing:.05em;color:var(--slate-400);margin-bottom:3px}
.hist-summary .v{font-size:.95rem;font-weight:850;color:var(--slate-800)}
.hist-insights{display:grid;grid-template-columns:1.2fr 1fr 1fr;gap:10px;margin:-4px 0 16px}
.hist-insights .insight{border:1px solid var(--slate-200);border-radius:8px;background:var(--white);padding:10px 12px;min-width:0}
.hist-insights .label{font-size:.66rem;font-weight:800;text-transform:uppercase;letter-spacing:.05em;color:var(--slate-400);margin-bottom:5px}
.hist-insights .text{font-size:.82rem;line-height:1.35;color:var(--slate-600)}
.hist-insights .tag{display:inline-flex;align-items:center;margin:2px 4px 2px 0;padding:3px 7px;border-radius:7px;background:var(--slate-100);font-size:.74rem;font-weight:800;color:var(--slate-700)}
.hist-learning{border:1px solid var(--slate-200);border-radius:8px;background:var(--slate-50);padding:10px 12px;margin:-6px 0 16px}
.hist-learning table{width:100%;border-collapse:collapse;font-size:.78rem}
.hist-learning th{text-align:left;font-size:.64rem;text-transform:uppercase;letter-spacing:.04em;color:var(--slate-400);font-weight:800;padding:2px 6px 6px}
.hist-learning td{border-top:1px solid var(--slate-200);padding:6px;color:var(--slate-600);vertical-align:middle}
.hist-learning td.num{text-align:right;font-weight:800;color:var(--slate-700);white-space:nowrap}
.hist-month{display:flex;justify-content:space-between;align-items:center;margin:16px 0 6px;padding:6px 2px;border-bottom:1px solid var(--slate-200);font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;color:var(--slate-500);font-weight:800}
.hist-month span:last-child{font-weight:600;color:var(--slate-400);text-transform:none;letter-spacing:0}
.hist-row{display:flex;gap:10px;align-items:center;padding:10px 0;border-bottom:1px solid var(--slate-100);flex-wrap:wrap}
.hist-row:last-child{border-bottom:none}
.hist-detail{background:var(--slate-50);border-radius:8px;padding:12px 14px;margin-bottom:8px;font-size:.8rem;display:none}
.hist-detail .dl{display:flex;gap:10px;padding:4px 0;border-bottom:1px solid var(--slate-200);align-items:center}
.hist-detail .dl:last-child{border-bottom:none}
.hist-actual{background:var(--blue-50);border:1px solid var(--blue-200);border-radius:8px;padding:8px 10px;margin-top:8px;color:var(--blue-700);font-size:.76rem}
.hist-actual .dl{border-color:var(--blue-200)}
.hist-actual-edit{border:1px dashed var(--slate-300);border-radius:8px;padding:10px;margin-top:10px;background:var(--white)}
.hist-actual-grid{display:grid;grid-template-columns:minmax(120px,1fr) 78px 94px 104px;gap:7px;align-items:end;margin-top:7px}
.hist-actual-grid label{font-size:.65rem;text-transform:uppercase;letter-spacing:.04em;color:var(--slate-400);font-weight:800}
.hist-actual-grid input{font-size:.78rem;padding:6px 8px}
.alert-warn{background:var(--amber-50);border:1px solid var(--amber-300);border-radius:8px;padding:10px 14px;color:var(--amber-800);font-size:.84rem;margin-bottom:12px}
.alert-ok{background:var(--green-50);border:1px solid var(--green-300);border-radius:8px;padding:10px 14px;color:var(--green-800);font-size:.84rem;margin-bottom:12px}
.notice{background:var(--blue-50);border:1px solid var(--blue-200);border-radius:8px;padding:8px 14px;color:var(--blue-700);font-size:.8rem;margin-bottom:10px;display:none}
.empty-state{text-align:center;color:var(--slate-400);font-size:.84rem;padding:28px 0}
.legend-box{display:flex;flex-wrap:wrap;gap:6px 16px;background:var(--slate-50);border:1px solid var(--slate-200);border-radius:8px;padding:8px 12px;margin-bottom:12px;font-size:.74rem;color:var(--slate-600)}
.legend-box b{color:var(--slate-800)}
@media(max-width:1120px){.sp-body{flex-direction:column}.sp-eval-panel{position:static;width:100%}.sp-analysis-grid{grid-template-columns:1fr}}
</style>"""


def _sc_badge(v: float, lo: float = 5.0, hi: float = 7.0) -> str:
    cls = "sc-g" if v >= hi else "sc-m" if v >= lo else "sc-b"
    return f'<span class="sc-badge {cls}">{v:.0f}</span>'


def _voto_badge(v: float) -> str:
    cls = "sc-g" if v >= 7.5 else "sc-m" if v >= 5.5 else "sc-b"
    return f'<span class="sc-badge {cls}" style="font-size:.8rem;padding:2px 7px">{v:.1f}</span>'


def _impact_badge(pp: float, post_bucket_weight: float, bucket_target: float) -> str:
    cls = "sc-g" if pp > 0.10 else "sc-b" if pp < -0.10 else "sc-m"
    sign = "+" if pp > 0 else ""
    title = (
        f"Impatto sul target del bucket: {sign}{pp:.1f} punti percentuali. "
        f"Peso post-acquisto {post_bucket_weight:.1%}, obiettivo {bucket_target:.1%}."
    )
    return f'<span class="sc-badge {cls}" title="{escape(title)}">{sign}{pp:.1f}</span>'


def _cap_badge(headroom_pp: float, post_nature_weight: float, nature_cap: float) -> str:
    cls = "sc-g" if headroom_pp > 1.0 else "sc-m" if headroom_pp >= 0.0 else "sc-b"
    label = "OK" if headroom_pp > 1.0 else "Pieno" if headroom_pp >= 0.0 else "Oltre"
    title = (
        f"Concentrazione natura dopo l'acquisto: {post_nature_weight:.1%}. "
        f"Cap indicativo: {nature_cap:.1%}. Spazio residuo: {headroom_pp:.1f} pp."
    )
    return f'<span class="sc-badge {cls}" title="{escape(title)}">{label}</span>'


def _data_badge(score: float, label: str) -> str:
    cls = "sc-g" if score >= 0.75 else "sc-m" if score >= 0.55 else "sc-b"
    short = "A" if score >= 0.75 else "B" if score >= 0.55 else "C"
    title = f"Qualita' dello storico prezzi: {label}."
    return f'<span class="sc-badge {cls}" title="{escape(title)}">{short}</span>'


_RUOLO_BADGE_CLASS = {"Core": "rb-core", "Difensivo": "rb-dif", "Satellite": "rb-sat"}


def _ruolo_badge(bucket: str) -> str:
    bucket = bucket if bucket in _RUOLO_BADGE_CLASS else "Satellite"
    return f'<span class="rb-dot {_RUOLO_BADGE_CLASS[bucket]}" title="Ruolo: {bucket}"></span>'


_SATOR_LEGEND_HTML = (
    "<div class='legend-box'>"
    "<span><b>Ruolo</b>: Core = pilastro diversificato, Difensivo = stabilita/liquidita/oro/bond, Satellite = tattico/tematico</span>"
    "<span><b>Voto</b> 1–10: punteggio unico, ordina la classifica</span>"
    "<span><b>Prio</b> 1–10: priorita' d'acquisto concreta sul portafoglio attuale</span>"
    "<span><b>Fit</b> 30%: quanto la funzione serve ora al portafoglio</span>"
    "<span><b>Mom</b> 25%: andamento ponderato 1/3/6/12 mesi</span>"
    "<span><b>Risk</b> 20%: volatilità, drawdown, rendimento/rischio</span>"
    "<span><b>Div</b> 15%: bassa correlazione e copertura di vuoti</span>"
    "<span><b>Cost</b> 10%: commissioni, TER, spread, prezzo/budget</span>"
    "<span><b>Imp</b>: miglioramento (+) o peggioramento (-) del target di bucket, in punti percentuali</span>"
    "<span><b>Cap</b>: stato della concentrazione di natura dopo l'acquisto suggerito</span>"
    "<span><b>Dato</b>: robustezza dello storico prezzi usato da momentum/rischio</span>"
    "<span>\U0001F7E2 suggerito · \U0001F7E1 migliore ma fuori budget · ⚪ battuto nella funzione</span>"
    "<span>&#9888; storico troppo corto (&lt;30gg): Momentum e Rischio sono indicativi</span>"
    "</div>"
)


def _build_sator_ranking_html(matrix_df, alerts: list) -> "tuple[str, str]":
    """Returns (table_html, rows_js_json) for embedding in the SATOR page."""
    rows_data = []
    for _, row in matrix_df.iterrows():
        rows_data.append({
            "ticker":   str(row.get("_ticker", row.get("Tk", ""))),
            "isin":     str(row.get("_isin", "")),
            "name":     str(row.get("_name", "")),
            "funzione": str(row.get("Gruppo", "")),
            "bucket":   str(row.get("_bucket", "Satellite")),
            "voto":     float(row.get("Voto", 0)),
            "score":    float(row.get("_score", 0)),
            "prio":     float(row.get("Prio", 0)),
            "decision_score": float(row.get("_decision_score", 0)),
            "decision_reason": str(row.get("_decision_reason", "")),
            "prezzo":   float(row.get("Px", row.get("_price", 0))),
            "qp":       float(row.get("Qp", 0)),
            "sug":      int(row.get("Sug", 0)),
            "fit":      float(row.get("Fit", 0)),
            "mom":      float(row.get("Mom", 0)),
            "risk":     float(row.get("Risk", 0)),
            "div_s":    float(row.get("Div", 0)),
            "cost":     float(row.get("Cost", 0)),
            "fit_raw":  float(row.get("_fit", 0)),
            "mom_raw":  float(row.get("_mom", 0)),
            "risk_raw": float(row.get("_risk", 0)),
            "div_raw":  float(row.get("_div", 0)),
            "cost_raw": float(row.get("_cost", 0)),
            "why":      str(row.get("_why", "")),
            "sem":      str(row.get("Sem", "⚪")),
            "dati_ok":  bool(row.get("_storico_ok", True)),
            "zero_commission": bool(row.get("_zero_commission", False)),
            "target_imp_pp": float(row.get("_target_improvement_pp", 0)),
            "post_bucket_weight": float(row.get("_post_bucket_weight", 0)),
            "bucket_target": float(row.get("_bucket_target", 0)),
            "post_nature_weight": float(row.get("_post_nature_weight", 0)),
            "nature_cap": float(row.get("_nature_cap", 0)),
            "cap_headroom_after_pp": float(row.get("_cap_headroom_after_pp", 0)),
            "data_quality_score": float(row.get("_data_quality_score", 0)),
            "data_quality_label": str(row.get("_data_quality_label", "N/D")),
            "portfolio_value": float(row.get("_portfolio_value", 0)),
            "bucket_weight": float(row.get("_bucket_weight", 0)),
            "nature_weight": float(row.get("_nature_weight", 0)),
        })

    rows_js = json.dumps(rows_data, ensure_ascii=False).replace("</", "<\\/")

    alerts_html = "".join(
        f'<div class="alert-warn">{escape(str(a.get("message", a) if isinstance(a, dict) else a))}</div>'
        for a in (alerts or [])[:4]
    )

    table_rows = ""
    for r in rows_data:
        tk = escape(r["ticker"])
        name_esc = escape(r["name"])
        name_short = escape(r["name"][:16] + ("…" if len(r["name"]) > 16 else ""))
        funz_full = r["funzione"]
        funz = escape(funz_full[:11] + ("…" if len(funz_full) > 11 else ""))
        px_it = f"{r['prezzo']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        qp_it = f"{r['qp']:.2f}".replace(".", ",")
        why_esc = escape(r["why"])
        sem = escape(r["sem"])
        dati_warning = "" if r["dati_ok"] else (
            "<span title='Storico troppo corto (<30 giorni di quotazioni): Momentum e Rischio sono indicativi' "
            "style='color:var(--orange-700);font-size:.7rem;margin-left:2px'>&#9888;</span>"
        )
        comm_badge = commission_badge(r["zero_commission"])
        data_zero = "1" if r["zero_commission"] else "0"
        data_sug = "1" if int(r["sug"]) > 0 else "0"
        data_voto = f"{r['voto']:.4f}"
        data_score = f"{r['score']:.6f}"
        data_decision = f"{r['decision_score']:.6f}"
        data_imp = f"{r['target_imp_pp']:.4f}"
        data_cap = f"{r['cap_headroom_after_pp']:.4f}"
        data_dato = f"{r['data_quality_score']:.4f}"
        data_prezzo = f"{r['prezzo']:.6f}"
        table_rows += (
            f"<tr class='sr-row' id='row_{tk}' data-ticker='{tk}' data-zero='{data_zero}' data-sug='{data_sug}' "
            f"data-voto='{data_voto}' data-score='{data_score}' data-decision='{data_decision}' data-imp='{data_imp}' "
            f"data-cap='{data_cap}' data-dato='{data_dato}' data-prezzo='{data_prezzo}'>"
            f"<td style='font-size:1.05rem;padding-left:4px;width:22px'>{sem}</td>"
            f"<td style='font-weight:800;white-space:nowrap;width:66px;overflow:hidden;text-overflow:ellipsis'>{tk}{comm_badge}{dati_warning}</td>"
            f"<td style='width:106px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--slate-600)' title='{name_esc}'>{name_short}</td>"
            f"<td style='width:80px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:.7rem;color:var(--slate-500)' title='{escape(funz_full)}'>{funz}</td>"
            f"<td style='text-align:center;width:24px'>{_ruolo_badge(r['bucket'])}</td>"
            f"<td style='text-align:center;width:36px' title='{why_esc}'>{_voto_badge(r['voto'])}</td>"
            f"<td style='text-align:center;width:36px' title='{escape(r['decision_reason'])}'>{_voto_badge(r['prio'])}</td>"
            f"<td style='text-align:center;width:28px'>{_sc_badge(r['fit'])}</td>"
            f"<td style='text-align:center;width:28px'>{_sc_badge(r['mom'])}</td>"
            f"<td style='text-align:center;width:28px'>{_sc_badge(r['risk'])}</td>"
            f"<td style='text-align:center;width:28px'>{_sc_badge(r['div_s'])}</td>"
            f"<td style='text-align:center;width:28px'>{_sc_badge(r['cost'])}</td>"
            f"<td style='text-align:center;width:38px'>{_impact_badge(r['target_imp_pp'], r['post_bucket_weight'], r['bucket_target'])}</td>"
            f"<td style='text-align:center;width:42px'>{_cap_badge(r['cap_headroom_after_pp'], r['post_nature_weight'], r['nature_cap'])}</td>"
            f"<td style='text-align:center;width:32px'>{_data_badge(r['data_quality_score'], r['data_quality_label'])}</td>"
            f"<td style='text-align:right;white-space:nowrap;overflow:hidden;color:var(--slate-600);width:58px'>€ {px_it}</td>"
            f"<td style='text-align:center;color:var(--slate-500);width:32px'>{qp_it}</td>"
            f"<td style='text-align:center;font-weight:700;color:var(--indigo-500);width:28px'>{r['sug']}</td>"
            f"<td style='text-align:center;width:26px'>"
            f"<input type='checkbox' id='sel_{tk}' onchange='computeEval()' "
            f"style='accent-color:var(--indigo-500);width:14px;height:14px;cursor:pointer'></td>"
            f"<td style='text-align:center;width:48px'>"
            f"<input type='number' id='qta_{tk}' min='0' step='1' value='0' oninput='computeEval()' "
            f"style='width:40px;padding:3px 4px;border:1px solid var(--slate-300);border-radius:6px;font-size:.8rem;text-align:center'></td>"
            f"</tr>"
        )

    table_html = (
        f"{alerts_html}"
        f"{_SATOR_LEGEND_HTML}"
        f"<div class='tbl-actions'>"
        f"<button type='button' class='btn-sm btn-sm-p' onclick='prefillSug()'>↺ Usa suggeriti SATOR</button>"
        f"<button type='button' class='btn-sm' onclick='clearSel()'>✕ Azzera</button>"
        f"<span style='font-size:.74rem;color:var(--slate-400);margin-left:4px'>Modifica Qta → valutazione live a destra · righe azzurre = diverse da SATOR</span>"
        f"</div>"
        f"<div class='tbl-actions' style='margin-top:-4px'>"
        f"<button type='button' class='btn-sm btn-filter-active' data-filter-btn='all' onclick=\"filterDecisionRows('all')\">Tutti</button>"
        f"<button type='button' class='btn-sm' data-filter-btn='suggested' onclick=\"filterDecisionRows('suggested')\">Suggeriti</button>"
        f"<button type='button' class='btn-sm' data-filter-btn='impact' onclick=\"filterDecisionRows('impact')\">Migliora target</button>"
        f"<button type='button' class='btn-sm' data-filter-btn='cap' onclick=\"filterDecisionRows('cap')\">Cap OK</button>"
        f"<button type='button' class='btn-sm' data-filter-btn='quality' onclick=\"filterDecisionRows('quality')\">Dati solidi</button>"
        f"<button type='button' class='btn-sm' data-filter-btn='zero' onclick=\"filterDecisionRows('zero')\">Zero comm.</button>"
        f"<span class='filter-count' id='filter_count'></span>"
        f"<span class='sort-wrap'><span>Ordina</span>"
        f"<select id='decision_sort' onchange='sortDecisionRows(this.value)'>"
        f"<option value='decision'>Priorita acquisto</option>"
        f"<option value='score'>Voto SATOR</option>"
        f"<option value='impact'>Impatto target</option>"
        f"<option value='cap'>Margine cap</option>"
        f"<option value='quality'>Qualita dati</option>"
        f"<option value='price_asc'>Prezzo crescente</option>"
        f"<option value='price_desc'>Prezzo decrescente</option>"
        f"</select></span>"
        f"</div>"
        f"<div>"
        f"<table class='sr-table'><thead><tr>"
        f"<th style='width:22px'></th>"
        f"<th style='width:66px'>Ticker</th>"
        f"<th style='width:106px'>Strumento</th>"
        f"<th style='width:80px'>Funzione</th>"
        f"<th style='width:24px;text-align:center' title='Ruolo nel portafoglio: blu=Core (pilastro diversificato), verde=Difensivo (stabilita, liquidita, oro, bond), arancio=Satellite (tattico/tematico)'></th>"
        f"<th style='width:36px;text-align:center' title='Punteggio unico 1-10: ordina la classifica. Passa il mouse per il perche della posizione'>Voto</th>"
        f"<th style='width:36px;text-align:center' title='Priorita acquisto 1-10: utilita concreta della riga rispetto a target, cap, dati, costi e qualita'>Prio</th>"
        f"<th style='width:28px;text-align:center' title='Fit allocativo 30%: quanto la funzione serve ora al portafoglio'>Fit</th>"
        f"<th style='width:28px;text-align:center' title='Momentum 25%: andamento ponderato 1/3/6/12 mesi'>Mom</th>"
        f"<th style='width:28px;text-align:center' title='Efficienza di rischio 20%: volatilita, drawdown, rendimento/rischio'>Risk</th>"
        f"<th style='width:28px;text-align:center' title='Diversificazione 15%: bassa correlazione e copertura di vuoti'>Div</th>"
        f"<th style='width:28px;text-align:center' title='Efficienza di costo 10%: commissioni, TER, spread, prezzo/budget'>Cost</th>"
        f"<th style='width:38px;text-align:center' title='Impatto in punti percentuali sullo scostamento dal target del bucket dopo l'acquisto suggerito'>Imp</th>"
        f"<th style='width:42px;text-align:center' title='Concentrazione della natura dopo l'acquisto: OK, piena o oltre cap indicativo'>Cap</th>"
        f"<th style='width:32px;text-align:center' title='Qualita dello storico prezzi: A alta/buona, B minima, C debole/assente'>Dato</th>"
        f"<th style='width:58px;text-align:right'>Prezzo</th>"
        f"<th style='width:32px;text-align:center'>Qp</th>"
        f"<th style='width:28px;text-align:center' title='Quote suggerite entro budget (residuo ammesso)'>Sug</th>"
        f"<th style='width:26px;text-align:center'>Sel</th>"
        f"<th style='width:48px;text-align:center'>Qta</th>"
        f"</tr></thead><tbody>{table_rows}</tbody></table></div>"
    )
    return table_html, rows_js


def _render_sator_page(
    budget_str: str = "5000",
    severity_str: str = "2",
    max_lines_str: str = "5",
    categories_val: str = "ETF,ETC",
    include_fee_instruments: bool = True,
    ok_msg: str = "",
    err_msg: str = "",
    ranking_html: str = "",
    rows_js: str = "[]",
    budget_for_eval: float = 0.0,
    ranking_json_esc: str = "",
    alerts_json_esc: str = "",
    decisions_json: str = "[]",
) -> str:
    ok_html  = f'<div class="alert-ok">{escape(ok_msg)}</div>'  if ok_msg  else ""
    err_html = f'<div class="alert-warn">{escape(err_msg)}</div>' if err_msg else ""

    selected_cats = [c.strip() for c in categories_val.split(",") if c.strip()]

    def _cat_chk(cat: str) -> str:
        chk = "checked" if cat in selected_cats else ""
        return (
            f'<label><input type="checkbox" name="cat_{cat}" value="{cat}" {chk}>'
            f'{cat}</label>'
        )

    cat_checks = "".join(_cat_chk(c) for c in _SATOR_ALL_CATS)
    fee_checked = "checked" if include_fee_instruments else ""

    sev_opts = "".join(
        f'<option value="{i}" {"selected" if str(i) == severity_str else ""}>'
        f'{i} – {"Bassa" if i==1 else "Media" if i==2 else "Alta" if i==3 else "Massima"}'
        f'</option>'
        for i in range(1, 5)
    )
    ml_opts = "".join(
        f'<option value="{i}" {"selected" if str(i) == max_lines_str else ""}>{i}</option>'
        for i in range(1, 11)
    )

    body_section = ""
    if ranking_html:
        save_form = (
            f'<form id="salva_form" method="post" action="/sator">'
            f'<input type="hidden" name="azione" value="salva">'
            f'<input type="hidden" name="budget" value="{budget_for_eval}">'
            f'<input type="hidden" name="severity" value="{escape(severity_str)}">'
            f'<input type="hidden" name="max_lines" value="{escape(max_lines_str)}">'
            f'<input type="hidden" name="categories_val" value="{escape(categories_val)}">'
            f'<input type="hidden" name="include_fee_instruments" value="{"1" if include_fee_instruments else "0"}">'
            f'<input type="hidden" name="ranking_json" value="{ranking_json_esc}">'
            f'<input type="hidden" name="alerts_json" value="{alerts_json_esc}">'
            f'<input type="hidden" name="order_lines_json" id="order_lines_json">'
            f'<input type="hidden" name="note_foto" id="note_foto_hidden">'
            f'</form>'
        )

        eval_panel = f"""<div class="sp-eval-panel sp-card">
  <h2>Valutazione live</h2>
  <div class="ev-block">
    <div class="ev-row"><span class="ev-h">Budget</span><span style="font-size:.88rem;font-weight:700">€ {budget_for_eval:,.2f}".replace(",","X").replace(".","​,").replace("X",".")</span></div>
    <div class="ev-row"><span class="ev-h">Totale ordine</span><span class="ev-v" id="ev_total" style="color:var(--slate-400)">—</span></div>
    <div class="ev-row"><span class="ev-h">Delta budget</span><span class="ev-v" id="ev_delta" style="color:var(--slate-400)">—</span></div>
  </div>
  <div class="ev-block" id="ev_rip_sec" style="display:none">
    <div class="ev-h" style="margin-bottom:8px">Ripartizione</div>
    <div style="display:flex;justify-content:space-between;font-size:.8rem"><span style="color:var(--blue-500);font-weight:600">Core</span><span id="ev_core_pct">—</span></div>
    <div class="bar-wrap"><div class="bar-fill" id="ev_core_bar" style="background:var(--blue-500);width:0%"></div><div class="bar-marker" id="ev_core_marker"></div></div>
    <div style="display:flex;justify-content:space-between;font-size:.8rem"><span style="color:var(--green-500);font-weight:600">Difensivo</span><span id="ev_diff_pct">—</span></div>
    <div class="bar-wrap"><div class="bar-fill" id="ev_diff_bar" style="background:var(--green-500);width:0%"></div><div class="bar-marker" id="ev_diff_marker"></div></div>
    <div style="display:flex;justify-content:space-between;font-size:.8rem"><span style="color:var(--orange-500);font-weight:600">Satellite</span><span id="ev_sat_pct">—</span></div>
    <div class="bar-wrap"><div class="bar-fill" id="ev_sat_bar" style="background:var(--orange-500);width:0%"></div><div class="bar-marker" id="ev_sat_marker"></div></div>
    <div class="ev-meter-caption">Tacca scura = proposta SATOR.</div>
  </div>
  <div class="ev-block" id="ev_scores_sec" style="display:none">
    <div class="ev-row"><span class="ev-h">Voto medio pond.</span><span class="ev-v" id="ev_voto">—</span></div>
    <div class="ev-row"><span class="ev-h">Priorita media</span><span class="ev-v" id="ev_prio">—</span></div>
    <div class="ev-row"><span class="ev-h">Impatto target</span><span class="ev-v" id="ev_target">—</span></div>
    <div class="ev-row"><span class="ev-h">Cap natura</span><span class="ev-v" id="ev_cap">—</span></div>
    <div class="ev-row"><span class="ev-h">Qualita' dati</span><span class="ev-v" id="ev_dataq">—</span></div>
    <div class="ev-row"><span class="ev-h">Strumenti</span><span id="ev_nsel" style="font-weight:700">—</span></div>
  </div>
  <div class="ev-block" id="ev_meters_sec" style="display:none">
    <div class="ev-h" style="margin-bottom:8px">Indicatori</div>
    <div class="ev-meter">
      <div class="ev-meter-head"><span>Scelta</span><span id="ev_meter_quality_txt">—</span></div>
      <div class="ev-meter-track"><div class="ev-meter-fill" id="ev_meter_quality_fill"></div><div class="ev-meter-marker" id="ev_meter_quality_marker"></div></div>
      <div class="ev-meter-caption" id="ev_meter_quality_cap">Qualita complessiva dell'ordine.</div>
    </div>
    <div class="ev-meter">
      <div class="ev-meter-head"><span>Allineamento SATOR</span><span id="ev_meter_sator_txt">—</span></div>
      <div class="ev-meter-track"><div class="ev-meter-fill" id="ev_meter_sator_fill"></div><div class="ev-meter-marker" id="ev_meter_sator_marker"></div></div>
      <div class="ev-meter-caption" id="ev_meter_sator_cap">Quanto la modifica resta vicina alla proposta.</div>
    </div>
    <div class="ev-meter">
      <div class="ev-meter-head"><span>Timing</span><span id="ev_meter_timing_txt">—</span></div>
      <div class="ev-meter-track"><div class="ev-meter-fill" id="ev_meter_timing_fill"></div><div class="ev-meter-marker" id="ev_meter_timing_marker"></div></div>
      <div class="ev-meter-caption" id="ev_meter_timing_cap">Momentum e rischio medio delle righe scelte.</div>
    </div>
    <div class="ev-meter">
      <div class="ev-meter-head"><span>Guardrail</span><span id="ev_meter_guard_txt">—</span></div>
      <div class="ev-meter-track"><div class="ev-meter-fill" id="ev_meter_guard_fill"></div><div class="ev-meter-marker" id="ev_meter_guard_marker"></div></div>
      <div class="ev-meter-caption" id="ev_meter_guard_cap">Cap, dati e rischio sotto controllo.</div>
    </div>
  </div>
  <div class="ev-headline" id="ev_headline_box"></div>
  <div class="ev-block" style="border:none;padding:0;margin:0">
    <div id="load_notice" class="notice"></div>
    <input class="note-inp" type="text" id="note_foto_input" placeholder="Note fotografia (opzionale)">
    <button class="btn-save" id="btn_save" onclick="salvaSator()" disabled>📸 Salva fotografia</button>
  </div>
  {save_form}
</div>"""

        # Fix the budget display (avoid nested f-string issue)
        budget_it = f"{budget_for_eval:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        eval_panel = eval_panel.replace(
            f'€ {budget_for_eval:,.2f}".replace(",","X").replace(".","​,").replace("X",".")',
            f"€ {budget_it}"
        )

        analysis_panel = """<div class="sp-analysis-panel sp-card" id="ev_analysis_panel">
  <h2>Analisi della selezione</h2>
  <div class="sp-analysis-grid">
    <div class="ev-block" id="ev_compare_sec" style="display:none">
      <div class="ev-h" style="margin-bottom:8px">Rispetto a SATOR</div>
      <div class="ev-note" id="ev_compare"></div>
    </div>
    <div class="ev-block" id="ev_timing_sec" style="display:none">
      <div class="ev-h" style="margin-bottom:8px">Guida operativa</div>
      <div class="ev-note" id="ev_timing"></div>
    </div>
  </div>
</div>"""

        body_section = (
            f'<div class="sp-body" id="sp_body">'
            f'<div class="sp-table-col">'
            f'<div class="sp-card"><h2>Classifica SATOR</h2>{ranking_html}</div>'
            f'{analysis_panel}'
            f'</div>'
            f'{eval_panel}'
            f'</div>'
        )

    js_block = f"""<script>
const satorRows={rows_js};
const budget_val={budget_for_eval};
const hasAnalysis=satorRows.length>0;
const decisions={decisions_json.replace("</","<\\/")};
let activeDecisionFilter='all';
let quickFixUndoStack=[];

const fmtEur=v=>'€\xa0'+parseFloat(v||0).toLocaleString('it-IT',{{minimumFractionDigits:2,maximumFractionDigits:2}});
const fmtPct=v=>parseFloat(v||0).toFixed(1)+'%';
const fmtV=v=>parseFloat(v||0).toFixed(1);
const fmtPP=v=>(parseFloat(v||0)>=0?'+':'')+parseFloat(v||0).toFixed(1)+' pp';
const escHtml=v=>String(v??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');

function collectCats(){{
  const cats=[];
  document.querySelectorAll('input[name^="cat_"]:checked').forEach(cb=>cats.push(cb.value));
  document.getElementById('cats_hidden_input').value=cats.join(',');
  const fee=document.getElementById('include_fee_checkbox');
  document.getElementById('include_fee_hidden_input').value=fee&&fee.checked?'1':'0';
}}

function targetImpactFor(r, amt){{
  const base=parseFloat(r.portfolio_value||0),target=parseFloat(r.bucket_target||0),bw=parseFloat(r.bucket_weight||0);
  const totalAfter=base+amt;
  if(!(target>0)||!(totalAfter>0))return 0;
  const post=((bw*base)+amt)/totalAfter;
  return (Math.abs(bw-target)-Math.abs(post-target))*100;
}}

function capHeadroomFor(r, amt){{
  const base=parseFloat(r.portfolio_value||0),cap=parseFloat(r.nature_cap||0),nw=parseFloat(r.nature_weight||0);
  const totalAfter=base+amt;
  if(!(cap>0)||!(totalAfter>0))return 0;
  const post=((nw*base)+amt)/totalAfter;
  return (cap-post)*100;
}}

function dataQualityLabel(score){{
  score=parseFloat(score||0);
  if(score>=.75)return 'Alta';
  if(score>=.55)return 'Minima';
  if(score>0)return 'Debole';
  return 'Assente';
}}

function evalOrder(useSuggested){{
  let total=0,nsel=0;
  let bkts={{Core:0,Difensivo:0,Satellite:0}};
  let voto_s=0,prio_s=0,fit_s=0,risk_s=0,mom_s=0,target_s=0,data_s=0,peso_s=0,capBad=0,capTight=0;
  const lines=[];
  satorRows.forEach(r=>{{
    const qta=useSuggested
      ? (parseInt(r.sug||'0')||0)
      : (parseInt(document.getElementById('qta_'+r.ticker)?.value||'0')||0);
    const selected=useSuggested ? qta>0 : !!document.getElementById('sel_'+r.ticker)?.checked;
    if(selected&&qta>0){{
      const amt=r.prezzo*qta;
      const target=targetImpactFor(r,amt);
      const head=capHeadroomFor(r,amt);
      total+=amt;nsel++;
      bkts[r.bucket]=(bkts[r.bucket]||0)+amt;
      voto_s+=(parseFloat(r.voto||0))*amt;
      prio_s+=(parseFloat(r.decision_score||0))*amt;
      fit_s+=(parseFloat(r.fit_raw||0))*amt;
      risk_s+=(parseFloat(r.risk_raw||0))*amt;
      mom_s+=(parseFloat(r.mom||0))*amt;
      target_s+=target*amt;
      data_s+=(parseFloat(r.data_quality_score||0))*amt;
      if(head<0)capBad++;
      else if(head<1)capTight++;
      peso_s+=amt;
      lines.push({{
        ticker:r.ticker,
        name:r.name||r.ticker,
        funzione:r.funzione||'',
        qta,amt,target,head,
        bucket:r.bucket,
        voto:parseFloat(r.voto||0),
        prio:parseFloat(r.decision_score||0),
        mom:parseFloat(r.mom||0),
        risk:parseFloat(r.risk||0),
        fit:parseFloat(r.fit||0),
        div_s:parseFloat(r.div_s||0),
        cost:parseFloat(r.cost||0),
        data_quality_label:r.data_quality_label||dataQualityLabel(r.data_quality_score||0),
        reason:r.decision_reason||''
      }});
    }}
  }});
  return {{
    total,nsel,bkts,capBad,capTight,lines,
    votoAvg:peso_s>0?voto_s/peso_s:0,
    prioAvg:peso_s>0?prio_s/peso_s:0,
    fitAvg:peso_s>0?fit_s/peso_s:0,
    riskAvg:peso_s>0?risk_s/peso_s:0,
    momAvg:peso_s>0?mom_s/peso_s:0,
    targetAvg:peso_s>0?target_s/peso_s:0,
    dataAvg:peso_s>0?data_s/peso_s:0
  }};
}}

function updateDeviationRows(){{
  satorRows.forEach(r=>{{
    const sel=document.getElementById('sel_'+r.ticker);
    const qta=document.getElementById('qta_'+r.ticker);
    const row=document.getElementById('row_'+r.ticker);
    const suggested=parseInt(r.sug||'0')||0;
    const current=sel&&sel.checked?(parseInt(qta?.value||'0')||0):0;
    const changed=current!==suggested;
    if(row)row.classList.toggle('sr-changed',changed);
    if(qta)qta.classList.toggle('qta-changed',changed);
  }});
}}

function selectionSnapshot(){{
  const snap={{}};
  satorRows.forEach(r=>{{
    const sel=document.getElementById('sel_'+r.ticker);
    const qta=document.getElementById('qta_'+r.ticker);
    snap[r.ticker]={{checked:!!sel?.checked,qta:qta?.value||'0'}};
  }});
  return snap;
}}

function restoreSelectionSnapshot(snap){{
  if(!snap)return;
  satorRows.forEach(r=>{{
    const state=snap[r.ticker]||{{checked:false,qta:'0'}};
    const sel=document.getElementById('sel_'+r.ticker);
    const qta=document.getElementById('qta_'+r.ticker);
    if(sel)sel.checked=!!state.checked;
    if(qta)qta.value=state.qta;
  }});
  computeEval();
}}

function updateQuickUndoButton(){{
  const btn=document.getElementById('quick_undo_btn');
  if(btn)btn.disabled=quickFixUndoStack.length===0;
}}

function pushQuickUndo(){{
  quickFixUndoStack.push(selectionSnapshot());
  if(quickFixUndoStack.length>8)quickFixUndoStack.shift();
}}

function undoQuickFix(){{
  const snap=quickFixUndoStack.pop();
  restoreSelectionSnapshot(snap);
}}

function applyQuickFix(ticker,targetQty){{
  pushQuickUndo();
  const q=Math.max(0,parseInt(targetQty||'0')||0);
  const sel=document.getElementById('sel_'+ticker);
  const qta=document.getElementById('qta_'+ticker);
  if(sel)sel.checked=q>0;
  if(qta)qta.value=q;
  computeEval();
}}

function alignAllQuickFixes(){{
  pushQuickUndo();
  prefillSug();
}}

function changedLinesHtml(cur, ref){{
  const refMap={{}},curMap={{}};
  (ref.lines||[]).forEach(l=>{{refMap[l.ticker]=l;}});
  (cur.lines||[]).forEach(l=>{{curMap[l.ticker]=l;}});
  const tickers=Array.from(new Set([...Object.keys(refMap),...Object.keys(curMap)])).sort();
  const changes=[];
  tickers.forEach(t=>{{
    const r=refMap[t],c=curMap[t];
    const rq=r?parseFloat(r.qta||0):0;
    const cq=c?parseFloat(c.qta||0):0;
    const dq=cq-rq;
    if(Math.abs(dq)<0.000001)return;
    const refAmt=r?parseFloat(r.amt||0):0;
    const curAmt=c?parseFloat(c.amt||0):0;
    const dAmt=curAmt-refAmt;
    let label='modificato',cls='warn';
    if(rq===0&&cq>0){{label='aggiunto';cls='good';}}
    else if(rq>0&&cq===0){{label='tolto';cls='bad';}}
    else if(dq>0){{label='aumentato';cls='warn';}}
    else if(dq<0){{label='ridotto';cls='warn';}}
    changes.push({{ticker:t,label,cls,dq,dAmt,rq,cq}});
  }});
  if(!changes.length)return '<div style="margin-top:8px;color:var(--slate-500)">Strumenti e quote coincidono con la proposta SATOR.</div>';
  const visible=changes.slice(0,6).map(x=>`
    <li><span class="${{x.cls}}" style="font-weight:850">${{x.label}}</span> <strong>${{x.ticker}}</strong>: ${{x.rq}} → ${{x.cq}} quote (${{x.dq>0?'+':''}}${{x.dq}}), ${{x.dAmt>=0?'+':''}}${{fmtEur(x.dAmt)}}</li>
  `).join('');
  const extra=changes.length>6?`<li>Altre ${{changes.length-6}} modifiche minori non mostrate.</li>`:'';
  return `<div style="margin-top:8px"><strong>Modifiche strumenti</strong><ul>${{visible}}${{extra}}</ul></div>`;
}}

function quickFixHtml(cur, ref){{
  const refMap={{}},curMap={{}};
  (ref.lines||[]).forEach(l=>{{refMap[l.ticker]=l;}});
  (cur.lines||[]).forEach(l=>{{curMap[l.ticker]=l;}});
  const actions=[];
  Array.from(new Set([...Object.keys(refMap),...Object.keys(curMap)])).forEach(t=>{{
    const r=refMap[t],c=curMap[t];
    const rq=r?parseFloat(r.qta||0):0;
    const cq=c?parseFloat(c.qta||0):0;
    const dq=rq-cq;
    if(Math.abs(dq)<0.000001)return;
    const refAmt=r?parseFloat(r.amt||0):0;
    const curAmt=c?parseFloat(c.amt||0):0;
    const weight=Math.abs(refAmt-curAmt);
    let text;
    if(cq===0&&rq>0)text=`aggiungi ${{t}}: ${{rq}} quote come da SATOR`;
    else if(cq>0&&rq===0)text=`togli ${{t}}: non era nella proposta SATOR`;
    else if(dq>0)text=`aumenta ${{t}} di ${{dq}} quote per riallinearti`;
    else text=`riduci ${{t}} di ${{Math.abs(dq)}} quote per avvicinarti a SATOR`;
    actions.push({{ticker:t,targetQty:rq,text,weight}});
  }});
  const undoBtn=`<button type="button" id="quick_undo_btn" class="quick-action" onclick="undoQuickFix()" ${{quickFixUndoStack.length?'':'disabled'}}>Annulla ultima</button>`;
  const alignBtn='<button type="button" class="quick-action" onclick="alignAllQuickFixes()">Allinea tutto</button>';
  const tools=`<div>${{actions.length?alignBtn:''}}${{undoBtn}}</div>`;
  if(!actions.length)return `<div class="quick-fix"><div class="quick-fix-head"><div class="t">Correzione rapida</div>${{tools}}</div>Sei gia allineato alla proposta SATOR: non serve correggere quote.</div>`;
  actions.sort((a,b)=>b.weight-a.weight);
  const rows=actions.slice(0,4).map(a=>`<li>${{a.text}} <button type="button" class="quick-action" onclick="applyQuickFix('${{a.ticker}}',${{a.targetQty}})">Applica</button></li>`).join('');
  const extra=actions.length>4?`<li>Altre ${{actions.length-4}} micro-correzioni meno rilevanti.</li>`:'';
  return `<div class="quick-fix"><div class="quick-fix-head"><div class="t">Correzione rapida verso SATOR</div>${{tools}}</div><ol>${{rows}}${{extra}}</ol></div>`;
}}

function compareHtml(cur, ref){{
  if(!ref.nsel)return '<strong>Nessuna proposta SATOR di riferimento.</strong>';
  const dTot=cur.total-ref.total;
  const dPrio=(cur.prioAvg-ref.prioAvg)*10;
  const dTarget=cur.targetAvg-ref.targetAvg;
  const dData=cur.dataAvg-ref.dataAvg;
  const absPrio=Math.abs(dPrio),absTarget=Math.abs(dTarget),absAmount=Math.abs(dTot);
  const materialAmount=Math.max(25,budget_val*.03);
  const dataNow=dataQualityLabel(cur.dataAvg),dataRef=dataQualityLabel(ref.dataAvg);
  const capBetter=cur.capBad<ref.capBad,capWorse=cur.capBad>ref.capBad;
  const overTol=Math.max(1,budget_val*.05),underLim=Math.max(50,budget_val*.10);
  const curScores=meterScores(cur,ref,cur.total-budget_val,overTol,underLim);
  const refScores=meterScores(ref,ref,ref.total-budget_val,overTol,underLim);
  const qualityGap=(curScores.qualityScore-refScores.qualityScore)*100;
  const distance=(1-curScores.similarity)*100;
  const dataLabelWorse=dataNow!==dataRef&&cur.dataAvg<ref.dataAvg;
  const hardWorse=capWorse||dTarget<-0.25||dataLabelWorse||qualityGap<=-8;
  const hardBetter=capBetter||dTarget>0.25||qualityGap>=8;
  let title,verdictClass,meaning,action;
  if(distance<=5&&Math.abs(qualityGap)<=3&&!hardWorse&&!hardBetter){{
    title=qualityGap<-1?'Quasi equivalente, leggermente sotto SATOR':qualityGap>1?'Quasi equivalente, leggermente sopra SATOR':'Equivalente a SATOR';
    verdictClass='good';
    action='Verdetto: differenza minima. Puoi salvarla, ma non e una scelta davvero migliore della proposta automatica.';
    meaning='La proposta finale resta molto vicina a SATOR: non stai facendo una scelta sbagliata, stai solo facendo una variante quasi neutra.';
  }}else if(distance<=12&&qualityGap<0&&!hardWorse){{
    title='Leggermente sotto SATOR';
    verdictClass='warn';
    action='Verdetto: SATOR resta un filo preferibile, ma la tua variante non e una cavolata.';
    meaning='La distanza e bassa: il peggioramento e marginale e va letto come preferenza, non come errore operativo.';
  }}else if(distance<=12&&qualityGap>0&&!hardBetter){{
    title='Leggermente sopra SATOR';
    verdictClass='good';
    action='Verdetto: la tua variante e un filo migliore, ma il vantaggio non e enorme.';
    meaning='La proposta finale resta vicina a SATOR, con un piccolo miglioramento complessivo.';
  }}else if(hardWorse){{
    title='Peggiore di SATOR';
    verdictClass='bad';
    action='Verdetto: resta sulla proposta SATOR, salvo una ragione personale molto precisa.';
    meaning='Qui la modifica non e solo diversa: introduce un peggioramento materiale su qualita complessiva, target, cap o dati.';
  }}else if(hardBetter){{
    title='Migliore di SATOR';
    verdictClass='good';
    action='Verdetto: la tua proposta finale e preferibile alla proposta automatica.';
    meaning='Il miglioramento e abbastanza netto da giustificare la modifica rispetto alla proposta automatica.';
  }}else{{
    title='Diversa, non chiaramente migliore';
    verdictClass='warn';
    action='Verdetto: non c’e un vincitore chiaro; scegli solo se hai una preferenza consapevole sugli strumenti.';
    meaning='Hai cambiato la proposta, ma il beneficio netto non e evidente.';
  }}
  const prioTxt=absPrio<.25
    ? 'priorita quasi identica'
    : `priorita ${{dPrio>0?'piu alta':'piu bassa'}} di ${{Math.abs(dPrio).toFixed(1)}} punti`;
  const targetTxt=absTarget<.10
    ? 'target invariato nella pratica'
    : `target ${{dTarget>0?'migliore':'peggiore'}} di ${{fmtPP(Math.abs(dTarget))}}`;
  const amountTxt=absAmount<=materialAmount
    ? 'importo sostanzialmente uguale'
    : `importo ${{dTot>0?'piu alto':'piu basso'}} di ${{fmtEur(Math.abs(dTot))}}`;
  const capTxt=capWorse?'cap peggiora':capBetter?'cap migliora':'cap invariato';
  const dataTxt=dataNow===dataRef
    ? `dati restano ${{dataNow}}`
    : `dati passano da ${{dataRef}} a ${{dataNow}}`;
  const dataDetail=Math.abs(dData)<.05
    ? 'differenza dati trascurabile'
    : `robustezza dati ${{dData>0?'piu alta':'piu bassa'}} di ${{Math.abs(dData*100).toFixed(0)}} punti interni`;
  const pros=[],cons=[],same=[];
  const pushDelta=(condition,positive,textGood,textBad,textSame)=>{{
    if(!condition){{same.push(textSame);return;}}
    (positive?pros:cons).push(positive?textGood:textBad);
  }};
  pushDelta(absPrio>=.25,dPrio>0,`priorita media piu alta di ${{Math.abs(dPrio).toFixed(1)}} punti`,`priorita media piu bassa di ${{Math.abs(dPrio).toFixed(1)}} punti`,'priorita quasi identica');
  pushDelta(absTarget>=.10,dTarget>0,`target migliore di ${{fmtPP(Math.abs(dTarget))}}`,`target peggiore di ${{fmtPP(Math.abs(dTarget))}}`,'target invariato nella pratica');
  pushDelta(absAmount>materialAmount,dTot<0,`usi meno budget: ${{fmtEur(Math.abs(dTot))}} non impegnati`,`impegni piu budget: ${{fmtEur(Math.abs(dTot))}} oltre SATOR`,'importo sostanzialmente uguale');
  if(capBetter)pros.push('cap natura piu pulito');
  else if(capWorse)cons.push('cap natura peggiora');
  else same.push('cap natura invariato');
  if(Math.abs(dData)>=.05){{
    (dData>0?pros:cons).push(`dati ${{dData>0?'piu robusti':'meno robusti'}} di ${{Math.abs(dData*100).toFixed(0)}} punti interni`);
  }}else same.push('qualita dati quasi identica');
  if(Math.abs(qualityGap)>=3){{
    (qualityGap>0?pros:cons).push(`score complessivo ${{qualityGap>0?'migliore':'peggiore'}} di ${{Math.abs(qualityGap).toFixed(0)}} punti`);
  }}else same.push('score complessivo quasi allineato');
  const listHtml=(title,items,cls,empty)=>`<div class="compare-card ${{cls}}"><div class="t">${{title}}</div><ul>${{(items.length?items:[empty]).map(x=>`<li>${{x}}</li>`).join('')}}</ul></div>`;
  return `
    <strong class="${{verdictClass}}">${{title}}</strong><br>
    <span class="${{verdictClass}}" style="font-weight:850">${{action}}</span><br>
    ${{meaning}}
    <div class="compare-head">
      <div class="compare-metric"><div class="k">Differenza netta</div><div class="v">${{qualityGap>=0?'+':''}}${{qualityGap.toFixed(0)}} pt</div></div>
      <div class="compare-metric"><div class="k">Distanza da SATOR</div><div class="v">${{Math.round(distance)}}%</div></div>
      <div class="compare-metric"><div class="k">Score</div><div class="v">${{Math.round(curScores.qualityScore*100)}}% vs ${{Math.round(refScores.qualityScore*100)}}%</div></div>
    </div>
    <div class="compare-grid">
      ${{listHtml('Cosa migliori',pros,'good','Nessun vantaggio materiale')}}
      ${{listHtml('Cosa peggiori',cons,'bad','Nessuna penalita materiale')}}
      ${{listHtml('Cosa resta uguale',same.slice(0,4),'neutral','Pochi elementi invariati')}}
    </div>
    <div style="color:var(--slate-500);font-size:.76rem;line-height:1.35">${{prioTxt}} · ${{targetTxt}} · ${{amountTxt}} · ${{capTxt}} · ${{dataTxt}}; ${{dataDetail}}.</div>
    ${{quickFixHtml(cur,ref)}}
    ${{changedLinesHtml(cur,ref)}}`;
}}

function clamp01(v){{return Math.max(0,Math.min(1,parseFloat(v||0)));}}

function meterTone(score){{
  score=clamp01(score);
  if(score>=.78)return ['var(--green-500)','Forte'];
  if(score>=.62)return ['var(--amber-500)','Discreto'];
  if(score>=.45)return ['var(--orange-500)','Fragile'];
  return ['var(--red-500)','Debole'];
}}

function setMeter(id,score,label,caption,refScore){{
  score=clamp01(score);
  refScore=refScore===undefined||refScore===null?null:clamp01(refScore);
  const tone=meterTone(score);
  const fill=document.getElementById(id+'_fill');
  const marker=document.getElementById(id+'_marker');
  const txt=document.getElementById(id+'_txt');
  const cap=document.getElementById(id+'_cap');
  if(fill){{fill.style.width=Math.round(score*100)+'%';fill.style.background=tone[0];}}
  if(marker){{
    if(refScore===null)marker.style.display='none';
    else{{marker.style.display='';marker.style.left=Math.round(refScore*100)+'%';}}
  }}
  if(txt){{txt.textContent=(label||tone[1])+' · '+Math.round(score*100)+'%';txt.style.color=tone[0];}}
  if(cap)cap.textContent=caption||'';
}}

function setAllocationBar(prefix,pct,refPct){{
  const bar=document.getElementById(prefix+'_bar');
  const marker=document.getElementById(prefix+'_marker');
  const safePct=Math.max(0,Math.min(100,parseFloat(pct||0)));
  const safeRef=Math.max(0,Math.min(100,parseFloat(refPct||0)));
  if(bar)bar.style.width=safePct+'%';
  if(marker){{
    marker.style.display='';
    marker.style.left=safeRef+'%';
  }}
}}

function meterScores(ev,ref,delta,overTol,underLim){{
  const targetScore=clamp01(.55+ev.targetAvg/2.0);
  const momScore=clamp01((ev.momAvg-4.5)/4.0);
  const riskScore=clamp01((ev.riskAvg-4.5)/4.0);
  const timingScore=clamp01(momScore*.65+riskScore*.35);
  const capScore=ev.capBad>0?.12:ev.capTight>0?.62:.90;
  const dataScore=clamp01(ev.dataAvg);
  const budgetPenalty=delta>overTol?.18:delta<-underLim?.08:0;
  const qualityScore=clamp01(ev.prioAvg*.38+targetScore*.22+timingScore*.18+dataScore*.12+capScore*.10-budgetPenalty);

  const dPrio=Math.abs((ev.prioAvg-ref.prioAvg)*10);
  const dTarget=Math.abs(ev.targetAvg-ref.targetAvg);
  const dAmount=Math.abs(ev.total-ref.total)/Math.max(1,budget_val||ref.total||1);
  const capDelta=ev.capBad!==ref.capBad?.18:0;
  const similarity=clamp01(1-(Math.min(1,dPrio/2)*.34+Math.min(1,dTarget/1)*.30+Math.min(1,dAmount)*.18+capDelta));
  const guardScore=clamp01(capScore*.45+dataScore*.35+riskScore*.20);
  return {{qualityScore,timingScore,guardScore,similarity}};
}}

function updateMeters(ev,ref,delta,overTol,underLim){{
  const cur=meterScores(ev,ref,delta,overTol,underLim);
  const refDelta=ref.total-budget_val;
  const base=meterScores(ref,ref,refDelta,overTol,underLim);
  base.similarity=1;

  const choiceLabel=cur.qualityScore>=.78?'Convincente':cur.qualityScore>=.62?'Accettabile':cur.qualityScore>=.45?'Da capire':'Da rivedere';
  const satorLabel=cur.similarity>=.82?'Allineata':cur.similarity>=.62?'Variante':cur.similarity>=.45?'Diverge':'Molto diversa';
  const timingLabel=cur.timingScore>=.78?'Favorevole':cur.timingScore>=.62?'Neutro+':cur.timingScore>=.45?'Incerto':'Debole';
  const guardLabel=cur.guardScore>=.78?'Puliti':cur.guardScore>=.62?'OK':cur.guardScore>=.45?'Attenzione':'Critici';

  setMeter('ev_meter_quality',cur.qualityScore,choiceLabel,`Qualita complessiva dell'ordine. Tacca scura = proposta SATOR (${{Math.round(base.qualityScore*100)}}%).`,base.qualityScore);
  setMeter('ev_meter_sator',cur.similarity,satorLabel,'Quanto ti stai allontanando dalla proposta automatica. La tacca scura resta al 100% SATOR.',base.similarity);
  setMeter('ev_meter_timing',cur.timingScore,timingLabel,`Forza di momento e rischio medio. Tacca scura = proposta SATOR (${{Math.round(base.timingScore*100)}}%).`,base.timingScore);
  setMeter('ev_meter_guard',cur.guardScore,guardLabel,`Controllo di cap, dati e rischio. Tacca scura = proposta SATOR (${{Math.round(base.guardScore*100)}}%).`,base.guardScore);
}}

function lineTagCls(value, goodAt, badBelow){{
  value=parseFloat(value||0);
  if(value>=goodAt)return 'good';
  if(value<badBelow)return 'bad';
  return 'warn';
}}

function lineReasonsHtml(ev){{
  const lines=[...ev.lines].sort((a,b)=>b.amt-a.amt).slice(0,5);
  if(!lines.length)return '<div class="line-reasons"><div class="line-reason"><div class="line-reason-body">Nessuna riga selezionata.</div></div></div>';
  const cards=lines.map(x=>{{
    const targetCls=x.target>.1?'good':x.target<-.1?'bad':'warn';
    const capCls=x.head<0?'bad':x.head<1?'warn':'good';
    const reason=x.reason||'Motivazione non disponibile per questa riga.';
    return `<div class="line-reason">
      <div class="line-reason-head">
        <div class="line-reason-title">${{escHtml(x.ticker)}} <span style="font-weight:650;color:var(--slate-500)">${{escHtml(x.name)}}</span></div>
        <div class="line-reason-meta">${{x.qta}} quote · ${{fmtEur(x.amt)}}</div>
      </div>
      <div class="line-reason-body"><strong>${{escHtml(x.funzione||x.bucket)}}</strong>: ${{escHtml(reason)}}</div>
      <div class="line-reason-tags">
        <span class="line-reason-tag ${{lineTagCls(x.prio*10,7,5.8)}}">Prio ${{fmtV(x.prio*10)}}</span>
        <span class="line-reason-tag ${{lineTagCls(x.mom,6.5,5.2)}}">Mom ${{fmtV(x.mom)}}</span>
        <span class="line-reason-tag ${{lineTagCls(x.risk,5.5,4.5)}}">Risk ${{fmtV(x.risk)}}</span>
        <span class="line-reason-tag ${{targetCls}}">Target ${{fmtPP(x.target)}}</span>
        <span class="line-reason-tag ${{capCls}}">Cap ${{x.head<0?'oltre':x.head<1?'stretto':'OK'}}</span>
        <span class="line-reason-tag">Dati ${{escHtml(x.data_quality_label)}}</span>
      </div>
    </div>`;
  }}).join('');
  const more=ev.lines.length>5?`<div class="line-reason-body" style="margin-top:6px;color:var(--slate-400)">Altre ${{ev.lines.length-5}} righe selezionate non mostrate.</div>`:'';
  return `<div class="line-reasons">${{cards}}${{more}}</div>`;
}}

function timingHtml(ev){{
  const topLines=[...ev.lines].sort((a,b)=>b.amt-a.amt).slice(0,3);
  const top=topLines.map(x=>`<span class="decision-pill">${{x.ticker}} · ${{fmtEur(x.amt)}}</span>`).join('');
  const momLabel=ev.momAvg>=6.6?'favorevole':ev.momAvg>=5.2?'neutrale':'debole';
  const riskLabel=ev.riskAvg>=5.5?'accettabile':ev.riskAvg>=4.5?'da pesare':'critico';
  const prioLabel=ev.prioAvg>=.72?'alta':ev.prioAvg>=.62?'media':'bassa';
  let title,body,cls;
  if(ev.capBad>0||ev.targetAvg<-.25||ev.dataAvg<.55){{
    title='Fermati e rivedi';
    cls='bad';
    body='La selezione ha un problema strutturale: cap, target o dati non sono abbastanza puliti. Prima di aumentare quote, correggi la composizione.';
  }}else if(ev.prioAvg>=.72&&ev.momAvg>=6.6&&ev.riskAvg>=5.5&&ev.targetAvg>=0){{
    title='Puoi spingere';
    cls='good';
    body='La proposta combina priorita alta, momentum favorevole e impatto target non negativo. Se il budget e quello previsto, aumentare le quote sulle righe principali e coerente.';
  }}else if(ev.prioAvg>=.62&&ev.targetAvg>=0&&ev.riskAvg>=5.0){{
    title='Ingresso graduale';
    cls='warn';
    body='La scelta e sensata, ma il momento non e cosi forte da giustificare aggressivita. Meglio distribuire o restare vicino alle quote suggerite.';
  }}else if(ev.momAvg<5.2&&ev.targetAvg>=0){{
    title='Accumulo prudente';
    cls='warn';
    body='Il target migliora, ma il momentum medio e debole. Ha senso comprare per riequilibrio, non perche il timing sia particolarmente favorevole.';
  }}else{{
    title='Scelta da motivare';
    cls='warn';
    body='Non emerge un vantaggio netto. Se stai modificando SATOR, serve una ragione precisa: costo, preferenza sullo strumento, o rischio che vuoi accettare.';
  }}
  return `<strong class="${{cls}}">${{title}}</strong><br>${{body}}
    <div class="decision-facts">
      <div class="decision-fact"><div class="k">Strumenti principali</div><div class="v">${{topLines.length?top:'Nessuna riga selezionata'}}</div></div>
      <div class="decision-fact"><div class="k">Momento di ingresso</div><div class="v">${{momLabel}} · punteggio ${{fmtV(ev.momAvg)}}/10</div></div>
      <div class="decision-fact"><div class="k">Qualita scelta</div><div class="v">priorita ${{prioLabel}} · rischio ${{riskLabel}}</div></div>
    </div>
    ${{lineReasonsHtml(ev)}}`;
}}

function computeEval(){{
  if(!hasAnalysis)return;
  const ev=evalOrder(false),ref=evalOrder(true);
  const total=ev.total,nsel=ev.nsel,bkts=ev.bkts,capBad=ev.capBad,capTight=ev.capTight;
  const t=document.getElementById('ev_total'),d=document.getElementById('ev_delta');
  t.textContent=nsel?fmtEur(total):'—'; t.style.color=nsel?'var(--slate-800)':'var(--slate-400)';
  const btn=document.getElementById('btn_save'); if(btn)btn.disabled=nsel===0;
  updateDeviationRows();
  if(!nsel){{
    d.textContent='—';d.style.color='var(--slate-400)';
    document.getElementById('ev_analysis_panel').style.display='none';
    document.getElementById('ev_rip_sec').style.display='none';
    document.getElementById('ev_scores_sec').style.display='none';
    document.getElementById('ev_meters_sec').style.display='none';
    document.getElementById('ev_compare_sec').style.display='none';
    document.getElementById('ev_timing_sec').style.display='none';
    document.getElementById('ev_headline_box').style.display='none';
    document.getElementById('ev_nsel').textContent='—';
    document.getElementById('ev_voto').textContent='—';
    document.getElementById('ev_prio').textContent='—';
    document.getElementById('ev_target').textContent='—';
    document.getElementById('ev_cap').textContent='—';
    document.getElementById('ev_dataq').textContent='—';
    return;
  }}
  const delta=total-budget_val;
  const overTol=Math.max(1,budget_val*.05),underLim=Math.max(50,budget_val*.10);
  d.textContent=(delta>=0?'+':'')+fmtEur(delta);
  d.style.color=delta>overTol?'var(--red-500)':delta>0?'var(--orange-500)':delta<-underLim?'var(--amber-500)':'var(--green-500)';
  const cpct=total>0?(bkts.Core||0)/total*100:0;
  const dpct=total>0?(bkts.Difensivo||0)/total*100:0;
  const spct=total>0?(bkts.Satellite||0)/total*100:0;
  const refTotal=ref.total||0;
  const rcpct=refTotal>0?(ref.bkts.Core||0)/refTotal*100:0;
  const rdpct=refTotal>0?(ref.bkts.Difensivo||0)/refTotal*100:0;
  const rspct=refTotal>0?(ref.bkts.Satellite||0)/refTotal*100:0;
  document.getElementById('ev_rip_sec').style.display='';
  document.getElementById('ev_core_pct').textContent=fmtPct(cpct)+' · SATOR '+fmtPct(rcpct);
  document.getElementById('ev_diff_pct').textContent=fmtPct(dpct)+' · SATOR '+fmtPct(rdpct);
  document.getElementById('ev_sat_pct').textContent=fmtPct(spct)+' · SATOR '+fmtPct(rspct);
  setAllocationBar('ev_core',cpct,rcpct);
  setAllocationBar('ev_diff',dpct,rdpct);
  setAllocationBar('ev_sat',spct,rspct);
  document.getElementById('ev_scores_sec').style.display='';
  document.getElementById('ev_nsel').textContent=nsel;
  const vm=ev.votoAvg;
  document.getElementById('ev_voto').textContent=fmtV(vm);
  document.getElementById('ev_prio').textContent=fmtV(ev.prioAvg*10);
  document.getElementById('ev_prio').style.color=ev.prioAvg>=.72?'var(--green-500)':ev.prioAvg>=.60?'var(--amber-500)':'var(--red-500)';
  const targetAvg=ev.targetAvg;
  const dataAvg=ev.dataAvg;
  const capText=capBad>0?capBad+' oltre cap':capTight>0?capTight+' al limite':'OK';
  document.getElementById('ev_target').textContent=fmtPP(targetAvg);
  document.getElementById('ev_target').style.color=targetAvg>.1?'var(--green-500)':targetAvg<-.1?'var(--red-500)':'var(--amber-500)';
  document.getElementById('ev_cap').textContent=capText;
  document.getElementById('ev_cap').style.color=capBad>0?'var(--red-500)':capTight>0?'var(--amber-500)':'var(--green-500)';
  document.getElementById('ev_dataq').textContent=dataQualityLabel(dataAvg);
  document.getElementById('ev_dataq').style.color=dataAvg>=.75?'var(--green-500)':dataAvg>=.55?'var(--amber-500)':'var(--red-500)';
  document.getElementById('ev_analysis_panel').style.display='block';
  document.getElementById('ev_meters_sec').style.display='';
  updateMeters(ev,ref,delta,overTol,underLim);
  document.getElementById('ev_compare_sec').style.display='';
  document.getElementById('ev_compare').innerHTML=compareHtml(ev,ref);
  updateQuickUndoButton();
  document.getElementById('ev_timing_sec').style.display='';
  document.getElementById('ev_timing').innerHTML=timingHtml(ev);
  const af=ev.fitAvg,ar=ev.riskAvg;
  let headline,hlBg,hlCol;
  if(delta>overTol){{headline='Fuori budget';hlBg='var(--red-50)';hlCol='var(--red-700)';}}
  else if(delta>0){{headline='Appena fuori budget';hlBg='var(--orange-50)';hlCol='var(--orange-700)';}}
  else if(delta<-underLim){{headline='Budget sottoutilizzato';hlBg='var(--yellow-50)';hlCol='var(--amber-800)';}}
  else if(capBad>0){{headline='Oltre cap da valutare';hlBg='var(--orange-50)';hlCol='var(--orange-700)';}}
  else if(targetAvg<-.25){{headline='Peggiora il target';hlBg='var(--orange-50)';hlCol='var(--orange-700)';}}
  else if(dataAvg<.55){{headline='Dati deboli';hlBg='var(--yellow-50)';hlCol='var(--amber-800)';}}
  else if(af>=0.62&&ar>=0.50&&targetAvg>=0){{headline='Scelta coerente ✓';hlBg='var(--green-50)';hlCol='var(--green-700)';}}
  else{{headline='Scelta da rivedere';hlBg='var(--orange-50)';hlCol='var(--orange-700)';}}
  const hbox=document.getElementById('ev_headline_box');
  hbox.style.display='';hbox.style.background=hlBg;hbox.style.color=hlCol;hbox.textContent=headline;
}}

function filterDecisionRows(mode){{
  activeDecisionFilter=mode||'all';
  let visible=0,total=0;
  document.querySelectorAll('.sr-row').forEach(row=>{{
    total++;
    const imp=parseFloat(row.dataset.imp||0),cap=parseFloat(row.dataset.cap||0),dato=parseFloat(row.dataset.dato||0);
    let show=true;
    if(activeDecisionFilter==='suggested')show=row.dataset.sug==='1';
    else if(activeDecisionFilter==='impact')show=imp>.1;
    else if(activeDecisionFilter==='cap')show=cap>=0;
    else if(activeDecisionFilter==='quality')show=dato>=.55;
    else if(activeDecisionFilter==='zero')show=row.dataset.zero==='1';
    row.style.display=show?'':'none';
    if(show)visible++;
  }});
  document.querySelectorAll('[data-filter-btn]').forEach(btn=>{{
    btn.classList.toggle('btn-filter-active',btn.dataset.filterBtn===activeDecisionFilter);
  }});
  const c=document.getElementById('filter_count');
  if(c)c.textContent=activeDecisionFilter==='all'?'':visible+' / '+total+' righe';
}}

function sortDecisionRows(mode){{
  const tbody=document.querySelector('.sr-table tbody');
  if(!tbody)return;
  const rows=Array.from(tbody.querySelectorAll('.sr-row'));
  const valueFor=row=>{{
    if(mode==='decision')return parseFloat(row.dataset.decision||0);
    if(mode==='impact')return parseFloat(row.dataset.imp||0);
    if(mode==='cap')return parseFloat(row.dataset.cap||0);
    if(mode==='quality')return parseFloat(row.dataset.dato||0);
    if(mode==='price_asc'||mode==='price_desc')return parseFloat(row.dataset.prezzo||0);
    return parseFloat(row.dataset.score||row.dataset.voto||0);
  }};
  rows.sort((a,b)=>{{
    const diff=valueFor(a)-valueFor(b);
    if(mode==='price_asc')return diff;
    return -diff;
  }});
  rows.forEach(row=>tbody.appendChild(row));
  filterDecisionRows(activeDecisionFilter);
}}

function prefillSug(){{
  if(!hasAnalysis)return;
  satorRows.forEach(r=>{{
    const sel=document.getElementById('sel_'+r.ticker);
    const qta=document.getElementById('qta_'+r.ticker);
    if(r.sug>0){{if(sel)sel.checked=true;if(qta)qta.value=r.sug;}}
    else{{if(sel)sel.checked=false;if(qta)qta.value=0;}}
  }});
  computeEval();
}}

function clearSel(){{
  satorRows.forEach(r=>{{
    const sel=document.getElementById('sel_'+r.ticker);
    const qta=document.getElementById('qta_'+r.ticker);
    if(sel)sel.checked=false;if(qta)qta.value=0;
  }});
  computeEval();
}}

function salvaSator(){{
  const selected=[];
  satorRows.forEach(r=>{{
    const sel=document.getElementById('sel_'+r.ticker)?.checked;
    const qta=parseInt(document.getElementById('qta_'+r.ticker)?.value||'0')||0;
    if(sel&&qta>0)selected.push({{ticker:r.ticker,isin:r.isin,name:r.name,shares:qta,price:r.prezzo,amount:Math.round(r.prezzo*qta*100)/100}});
  }});
  if(!selected.length){{alert('Seleziona almeno uno strumento con quantità > 0.');return;}}
  document.getElementById('order_lines_json').value=JSON.stringify(selected);
  document.getElementById('note_foto_hidden').value=document.getElementById('note_foto_input')?.value||'';
  document.getElementById('salva_form').submit();
}}

function deleteDecision(id){{
  if(!window.confirm('Eliminare questa decisione? Non modifica il portafoglio.'))return;
  document.getElementById('delete_decision_id').value=id;
  document.getElementById('delete_form').submit();
}}

function actualEditableLines(dec){{
  const result=[],seen=new Set();
  (dec.order_lines||[]).forEach(l=>{{
    const key=String(l.ticker||'').trim();
    if(!key)return;
    seen.add(key);result.push(l);
  }});
  (dec.actual_order||[]).forEach(l=>{{
    const key=String(l.ticker||'').trim();
    if(!key||seen.has(key))return;
    seen.add(key);result.push(l);
  }});
  return result;
}}

function actualLineFor(dec,ticker){{
  const key=String(ticker||'').trim();
  return (dec.actual_order||[]).find(l=>String(l.ticker||'').trim()===key)||null;
}}

function saveActualOrder(idx){{
  const dec=decisions[idx];
  if(!dec)return;
  const actual=[];
  actualEditableLines(dec).forEach((line,i)=>{{
    const q=parseFloat(document.getElementById(`act_q_${{idx}}_${{i}}`)?.value||'0')||0;
    const p=parseFloat(document.getElementById(`act_p_${{idx}}_${{i}}`)?.value||'0')||0;
    if(q>0){{
      actual.push({{ticker:line.ticker,isin:line.isin||'',name:line.name||'',shares:q,price:p,amount:Math.round(q*p*100)/100}});
    }}
  }});
  if(!actual.length&&!window.confirm('Salvare eseguito vuoto e rimuovere il confronto da questa fotografia?'))return;
  document.getElementById('actual_decision_id').value=dec.decision_id||'';
  document.getElementById('actual_order_json').value=JSON.stringify(actual);
  document.getElementById('actual_form').submit();
}}

function loadDecision(idx){{
  const dec=decisions[idx];
  if(!hasAnalysis){{
    alert('Prima esegui l\\'analisi cliccando "Analizza", poi potrai ricaricare questa configurazione.');
    return;
  }}
  const lines=dec.order_lines||[];
  satorRows.forEach(r=>{{
    const sel=document.getElementById('sel_'+r.ticker);
    const qta=document.getElementById('qta_'+r.ticker);
    if(sel)sel.checked=false;if(qta)qta.value=0;
  }});
  let loaded=0,missed=[];
  lines.forEach(l=>{{
    const qty=parseInt(l.shares||l.quantita||0);
    const sel=document.getElementById('sel_'+l.ticker);
    const qta=document.getElementById('qta_'+l.ticker);
    if(sel&&qta&&qty>0){{sel.checked=true;qta.value=qty;loaded++;}}
    else if(qty>0)missed.push(l.ticker);
  }});
  computeEval();
  document.getElementById('sp_body')?.scrollIntoView({{behavior:'smooth',block:'start'}});
  const notice=document.getElementById('load_notice');
  if(notice){{
    if(missed.length){{
      notice.textContent='Non trovati nell\\'analisi corrente: '+missed.join(', ')+'. Verifica categorie selezionate.';
      notice.style.display='';
      setTimeout(()=>{{notice.style.display='none';}},9000);
    }}else{{notice.style.display='none';}}
  }}
}}

function toggleHistDetail(idx){{
  const el=document.getElementById('hist_d_'+idx);
  if(el){{el.style.display=el.style.display==='none'?'block':'none';}}
}}

function decisionMetrics(lines){{
  let amount=0,target=0,data=0,capBad=0,capTight=0;
  (lines||[]).forEach(l=>{{
    const am=parseFloat(l.amount||l.importo||0);
    if(!(am>0))return;
    amount+=am;
    target+=(parseFloat(l.target_improvement_pp||0))*am;
    data+=(parseFloat(l.data_quality_score||0))*am;
    const cap=parseFloat(l.cap_headroom_after_pp||0);
    if(cap<0)capBad++;
    else if(cap<1)capTight++;
  }});
  const targetAvg=amount>0?target/amount:0;
  const dataAvg=amount>0?data/amount:0;
  return {{
    target:targetAvg,
    data:dataAvg,
    capLabel:capBad>0?capBad+' oltre cap':capTight>0?capTight+' al limite':'OK',
    capClass:capBad>0?'bad':capTight>0?'warn':'ok'
  }};
}}

function photoQuality(dec){{
  const lines=dec.order_lines||[];
  const dm=decisionMetrics(lines);
  const amount=parseFloat(dec.importo_ordine||0)||lines.reduce((s,l)=>s+parseFloat(l.amount||l.importo||0),0);
  const budget=parseFloat(dec.budget||0)||amount||1;
  const voto=(parseFloat(dec.giudizio?.voto_medio||0)||0)/10;
  const targetScore=clamp01(.55+dm.target/2.0);
  const dataScore=clamp01(dm.data);
  const capScore=dm.capClass==='bad'?.12:dm.capClass==='warn'?.62:.90;
  const budgetUse=clamp01(1-Math.abs(amount-budget)/Math.max(1,budget));
  const score=clamp01(voto*.34+targetScore*.24+dataScore*.18+capScore*.16+budgetUse*.08);
  let label='Da rivedere';
  if(score>=.78)label='Molto forte';
  else if(score>=.66)label='Buona';
  else if(score>=.54)label='Intermedia';
  const note=dm.capClass==='bad'
    ? 'cap oltre'
    : dm.target<-.1
      ? 'peggiora target'
      : dm.data<.55
        ? 'dati deboli'
        : 'equilibrio ok';
  return {{score,label,note,dm,amount,budget,voto:voto*10,lines}};
}}

function photoComparisonHtml(sorted){{
  if(!sorted||sorted.length<2)return '';
  const ranked=sorted.map((dec,ri)=>({{
      dec,
      origIdx:decisions.length-1-ri,
      created:(dec.created_at||'').slice(0,16).replace('T',' '),
      q:photoQuality(dec)
    }}))
    .filter(x=>x.q.lines.length>0)
    .sort((a,b)=>b.q.score-a.q.score)
    .slice(0,3);
  if(!ranked.length)return '';
  const cards=ranked.map((x,i)=>{{
    const cls=i===0?'hist-choice best':'hist-choice';
    const rank=i===0?'Migliore foto':i===1?'Seconda scelta':'Alternativa';
    const dm=x.q.dm;
    return `<div class="${{cls}}">
      <div class="rank">${{rank}}</div>
      <div class="score">${{Math.round(x.q.score*100)}}% · ${{x.q.label}}</div>
      <div class="meta">${{x.created||'Senza data'}} · ${{x.q.lines.length}} strumenti · ${{fmtEur(x.q.amount)}}</div>
      <div class="meta">Voto ${{fmtV(x.q.voto)}} · Target ${{fmtPP(dm.target)}} · Cap ${{dm.capLabel}} · Dati ${{dataQualityLabel(dm.data)}}</div>
      <div class="meta"><strong>${{x.q.note}}</strong></div>
      <button class="btn-sm btn-sm-p" style="margin-top:8px" onclick="loadDecision(${{x.origIdx}})" ${{!hasAnalysis?'disabled':''}}>Riparti da questa</button>
    </div>`;
  }}).join('');
  const best=ranked[0];
  return `<div class="hist-compare">
    <div class="hist-compare-title"><strong>Confronto foto salvate</strong><span style="font-size:.74rem;color:var(--slate-500)">Migliore: ${{best.created||'Senza data'}} · ${{Math.round(best.q.score*100)}}%</span></div>
    <div class="hist-choice-grid">${{cards}}</div>
  </div>`;
}}

function executionStats(dec){{
  const proposed=dec.order_lines||[];
  const actual=dec.actual_order||[];
  if(!actual.length)return null;
  const proposedTotal=parseFloat(dec.importo_ordine||0)||proposed.reduce((s,l)=>s+parseFloat(l.amount||l.importo||0),0);
  const actualTotal=actual.reduce((s,l)=>s+parseFloat(l.amount||l.importo||0),0);
  const proposedTickers=new Set(proposed.map(l=>String(l.ticker||'').trim()).filter(Boolean));
  const actualTickers=new Set(actual.map(l=>String(l.ticker||'').trim()).filter(Boolean));
  const skippedTickers=[],addedTickers=[];
  proposedTickers.forEach(t=>{{if(!actualTickers.has(t))skippedTickers.push(t);}});
  actualTickers.forEach(t=>{{if(!proposedTickers.has(t))addedTickers.push(t);}});
  const delta=actualTotal-proposedTotal;
  const adherence=proposedTotal>0?Math.max(0,100-(Math.abs(delta)/proposedTotal*100)):0;
  return {{proposedTotal,actualTotal,delta,adherence,skipped:skippedTickers.length,added:addedTickers.length,skippedTickers,addedTickers}};
}}

function topTickerTags(items){{
  const counts={{}};
  (items||[]).forEach(t=>{{counts[t]=(counts[t]||0)+1;}});
  return Object.entries(counts)
    .sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0]))
    .slice(0,4)
    .map(([ticker,count])=>`<span class="tag">${{ticker}}${{count>1?' x'+count:''}}</span>`)
    .join('');
}}

function decisionDisciplineLabel(avgAdherence, skipped, added){{
  if(avgAdherence>=95&&skipped===0&&added===0)return 'Molto coerente';
  if(avgAdherence>=85&&skipped+added<=2)return 'Coerente con piccoli scostamenti';
  if(avgAdherence>=70)return 'Da monitorare';
  return 'Dispersiva';
}}

function decisionDisciplineNote(summary){{
  if(summary.avgAdherence>=95&&summary.skipped===0&&summary.added===0)return 'Le decisioni salvate vengono eseguite quasi alla lettera: SATOR sta funzionando come piano operativo.';
  if(summary.skipped>summary.added)return 'Tendi a tagliare alcune righe rispetto alla proposta: utile capire se dipende da budget, prezzo o convinzione sullo strumento.';
  if(summary.added>summary.skipped)return 'Tendi ad aggiungere strumenti non proposti: verifica se sono opportunita reali o deviazioni tattiche dal piano.';
  if(Math.abs(summary.totalDelta)>0)return 'Lo scostamento e soprattutto sull\\'importo: controlla se stai sistematicamente sotto o sopra il budget deciso.';
  return 'Scostamenti contenuti: continua a registrare gli eseguiti per rendere il campione piu robusto.';
}}

function roleLabel(line){{
  const raw=String(line.function_label||line.role||line.bucket||'Non classificato').trim();
  return raw.replaceAll('_',' ');
}}

function decisionLearningRows(items){{
  const rows={{}};
  (items||[]).forEach(dec=>{{
    const actual=dec.actual_order||[];
    if(!actual.length)return;
    const actualTickers=new Set(actual.map(l=>String(l.ticker||'').trim()).filter(Boolean));
    (dec.order_lines||[]).forEach(line=>{{
      const ticker=String(line.ticker||'').trim();
      if(!ticker)return;
      const bucket=String(line.bucket||'N/D').trim()||'N/D';
      const role=roleLabel(line);
      const key=bucket+' · '+role;
      const rec=rows[key]||{{key,bucket,role,proposed:0,executed:0,skipped:0,amount:0,skippedAmount:0,skippedImpact:0,capIssues:0,weakData:0}};
      const amount=parseFloat(line.amount||line.importo||0)||0;
      const target=parseFloat(line.target_improvement_pp||0)||0;
      const cap=parseFloat(line.cap_headroom_after_pp||0);
      const data=parseFloat(line.data_quality_score||0);
      rec.proposed+=1;rec.amount+=amount;
      if(actualTickers.has(ticker)){{
        rec.executed+=1;
        if(cap<0)rec.capIssues+=1;
        if(data>0&&data<.55)rec.weakData+=1;
      }}else{{
        rec.skipped+=1;rec.skippedAmount+=amount;rec.skippedImpact+=Math.max(target,0)*amount;
      }}
      rows[key]=rec;
    }});
  }});
  return Object.values(rows)
    .filter(r=>r.proposed>0)
    .sort((a,b)=>b.skipped-a.skipped||b.skippedImpact-a.skippedImpact||b.proposed-a.proposed)
    .slice(0,5);
}}

function learningRowsHtml(rows){{
  if(!rows||!rows.length)return '';
  const body=rows.map(r=>{{
    const leftImpact=r.skippedAmount>0?r.skippedImpact/r.skippedAmount:0;
    const note=r.capIssues>0?`${{r.capIssues}} cap oltre`:r.weakData>0?`${{r.weakData}} dati deboli`:'OK';
    return `<tr><td><strong>${{r.bucket}}</strong><br><span style="font-size:.72rem;color:var(--slate-500)">${{r.role}}</span></td><td class="num">${{r.skipped}}</td><td class="num">${{r.executed}}/${{r.proposed}}</td><td class="num">${{fmtPP(leftImpact)}}</td><td class="num">${{note}}</td></tr>`;
  }}).join('');
  return `<div class="hist-learning"><div class="label" style="font-size:.66rem;font-weight:800;text-transform:uppercase;letter-spacing:.05em;color:var(--slate-400);margin-bottom:7px">Apprendimento per funzione</div><table><thead><tr><th>Funzione</th><th>Saltati</th><th>Eseguiti</th><th>Target lasciato</th><th>Nota</th></tr></thead><tbody>${{body}}</tbody></table></div>`;
}}

function historyExecutionSummary(items){{
  const stats=items.map(executionStats).filter(Boolean);
  if(!stats.length)return null;
  const totalDelta=stats.reduce((s,x)=>s+x.delta,0);
  const avgAdherence=stats.reduce((s,x)=>s+x.adherence,0)/stats.length;
  const skipped=stats.reduce((s,x)=>s+x.skipped,0);
  const added=stats.reduce((s,x)=>s+x.added,0);
  const skippedTickers=stats.flatMap(x=>x.skippedTickers||[]);
  const addedTickers=stats.flatMap(x=>x.addedTickers||[]);
  const discipline=decisionDisciplineLabel(avgAdherence,skipped,added);
  const learningRows=decisionLearningRows(items);
  return {{count:stats.length,totalDelta,avgAdherence,skipped,added,skippedTickers,addedTickers,discipline,learningRows}};
}}

function renderHistory(){{
  const cnt=document.getElementById('hist_count');
  const container=document.getElementById('hist_container');
  if(!decisions.length){{
    container.innerHTML='<div class="empty-state">Nessuna decisione registrata. Salva la prima fotografia per vederla qui.</div>';
    if(cnt)cnt.textContent='';return;
  }}
  if(cnt)cnt.textContent='('+decisions.length+')';
  let html='';
  const sorted=[...decisions].reverse();
  html+=photoComparisonHtml(sorted);
  const executionSummary=historyExecutionSummary(sorted);
  if(executionSummary){{
    html+=`
      <div class="hist-summary">
        <div class="box"><div class="k">Foto eseguite</div><div class="v">${{executionSummary.count}}</div></div>
        <div class="box"><div class="k">Aderenza media</div><div class="v">${{fmtPct(executionSummary.avgAdherence)}}</div></div>
        <div class="box"><div class="k">Delta totale</div><div class="v" style="color:${{executionSummary.totalDelta>=0?'var(--amber-800)':'var(--blue-700)'}}">${{fmtEur(executionSummary.totalDelta)}}</div></div>
        <div class="box"><div class="k">Scostamenti</div><div class="v">${{executionSummary.skipped}} saltati · ${{executionSummary.added}} aggiunti</div></div>
      </div>
      <div class="hist-insights">
        <div class="insight"><div class="label">Lettura operativa</div><div class="text"><strong>${{executionSummary.discipline}}</strong><br>${{decisionDisciplineNote(executionSummary)}}</div></div>
        <div class="insight"><div class="label">Saltati spesso</div><div class="text">${{topTickerTags(executionSummary.skippedTickers)||'Nessun pattern evidente'}}</div></div>
        <div class="insight"><div class="label">Aggiunti extra</div><div class="text">${{topTickerTags(executionSummary.addedTickers)||'Nessun pattern evidente'}}</div></div>
      </div>
      ${{learningRowsHtml(executionSummary.learningRows)}}`;
  }}
  const monthKeyFor=(dec)=>dec.month_id||(dec.created_at||'').slice(0,7)||'Senza mese';
  const monthLabelFor=(key)=>{{
    if(key==='Senza mese')return key;
    const parts=key.split('-');
    if(parts.length!==2)return key;
    const months=['Gennaio','Febbraio','Marzo','Aprile','Maggio','Giugno','Luglio','Agosto','Settembre','Ottobre','Novembre','Dicembre'];
    const monthIdx=parseInt(parts[1],10)-1;
    return `${{months[monthIdx]||parts[1]}} ${{parts[0]}}`;
  }};
  const monthStatsFor=(key)=>{{
    const items=sorted.filter(d=>monthKeyFor(d)===key);
    const amount=items.reduce((s,d)=>s+parseFloat(d.importo_ordine||0),0);
    return `${{items.length}} foto · ${{fmtEur(amount)}}`;
  }};
  let currentMonth='';
  sorted.forEach((dec,ri)=>{{
    const origIdx=decisions.length-1-ri;
    const created=(dec.created_at||'').slice(0,16).replace('T',' ');
    const monthKey=monthKeyFor(dec);
    if(monthKey!==currentMonth){{
      currentMonth=monthKey;
      html+=`<div class="hist-month"><span>${{monthLabelFor(monthKey)}}</span><span>${{monthStatsFor(monthKey)}}</span></div>`;
    }}
    const budget_d=parseFloat(dec.budget||0);
    const imp=parseFloat(dec.importo_ordine||0);
    const vm=parseFloat(dec.giudizio?.voto_medio||0);
    const glbl=dec.giudizio?.label||'—';
    const lines=dec.order_lines||[];
    const actual=dec.actual_order||[];
    const note=(dec.note||'').trim();
    const dm=decisionMetrics(lines);
    const gCol=glbl.includes('coerente')?'var(--green-700)':glbl.includes('rivedere')?'var(--orange-700)':'var(--amber-800)';
    const gBg=glbl.includes('coerente')?'var(--green-50)':glbl.includes('rivedere')?'var(--orange-50)':'var(--yellow-50)';
    const targetColor=dm.target>.1?'var(--green-700)':dm.target<-.1?'var(--red-700)':'var(--amber-800)';
    const capColor=dm.capClass==='bad'?'var(--red-700)':dm.capClass==='warn'?'var(--amber-800)':'var(--green-700)';
    const dataColor=dm.data>=.75?'var(--green-700)':dm.data>=.55?'var(--amber-800)':'var(--red-700)';
    let linesHtml='';
    lines.forEach(l=>{{
      const am=parseFloat(l.amount||l.importo||0);
      const imp=parseFloat(l.target_improvement_pp||0);
      const cap=parseFloat(l.cap_headroom_after_pp||0);
      const ql=l.data_quality_label||dataQualityLabel(l.data_quality_score||0);
      linesHtml+=`<div class="dl"><span style="font-weight:800;min-width:60px">${{l.ticker}}</span><span style="flex:1;color:var(--slate-500)">${{l.name||''}}</span><span style="white-space:nowrap;color:var(--slate-600)">${{l.shares||l.quantita||0}} q × ${{fmtEur(l.price||l.prezzo||0)}}</span><span style="font-size:.72rem;color:var(--slate-400);white-space:nowrap">Imp ${{fmtPP(imp)}} · Cap ${{cap.toFixed(1)}} pp · Dati ${{ql}}</span><span style="font-weight:700;margin-left:10px">${{fmtEur(am)}}</span></div>`;
    }});
    const actualTotal=actual.reduce((s,l)=>s+parseFloat(l.amount||l.importo||0),0);
    const actualDelta=actualTotal-imp;
    const actualColor=actualDelta>0?'var(--amber-800)':actualDelta<0?'var(--blue-700)':'var(--green-700)';
    const actualSummary=actual.length?`<div style="font-size:.75rem;color:${{actualColor}}">Eseguito ${{fmtEur(actualTotal)}} · Delta ${{fmtEur(actualDelta)}}</div>`:'';
    let actualHtml='';
    if(actual.length){{
      actualHtml='<div class="hist-actual"><strong>Ordine effettivo</strong>';
      actual.forEach(l=>{{
        const am=parseFloat(l.amount||l.importo||0);
        actualHtml+=`<div class="dl"><span style="font-weight:800;min-width:60px">${{l.ticker}}</span><span style="flex:1">${{l.name||''}}</span><span style="white-space:nowrap">${{l.shares||l.quantita||0}} q</span><span style="font-weight:700;margin-left:10px">${{fmtEur(am)}}</span></div>`;
      }});
      actualHtml+='</div>';
    }}
    let actualEditHtml='';
    const editable=actualEditableLines(dec);
    if(editable.length){{
      actualEditHtml='<div class="hist-actual-edit"><div style="font-weight:800;color:var(--slate-700);font-size:.78rem">Registra o aggiorna ordine effettivo</div>';
      editable.forEach((l,i)=>{{
        const saved=actualLineFor(dec,l.ticker)||l;
        const q=parseFloat(saved.shares||saved.quantita||0)||0;
        const p=parseFloat(saved.price||saved.prezzo||0)||0;
        actualEditHtml+=`
          <div class="hist-actual-grid">
            <div><label>Strumento</label><div style="font-weight:800;color:var(--slate-700);font-size:.78rem">${{l.ticker}}</div></div>
            <div><label>Quote</label><input type="number" id="act_q_${{origIdx}}_${{i}}" min="0" step="0.000001" value="${{q}}"></div>
            <div><label>Prezzo</label><input type="number" id="act_p_${{origIdx}}_${{i}}" min="0" step="0.000001" value="${{p}}"></div>
            <div><label>Stimato</label><div style="font-weight:800;color:var(--slate-600);font-size:.78rem">${{fmtEur(q*p)}}</div></div>
          </div>`;
      }});
      actualEditHtml+=`<div style="display:flex;justify-content:flex-end;margin-top:10px"><button class="btn-sm btn-sm-p" onclick="saveActualOrder(${{origIdx}})">Salva eseguito</button></div></div>`;
    }}
    const ripartRow=Object.entries(dec.ripartizione||{{}}).filter(([,v])=>v.amount>0).map(([k,v])=>`<span style="font-size:.75rem;color:var(--slate-500)">${{k}}: ${{fmtPct(v.pct)}}</span>`).join(' · ');
    html+=`
    <div class="hist-row">
      <div style="min-width:105px;font-size:.75rem;color:var(--slate-500)">${{created}}</div>
      <div><span style="font-size:.72rem;color:var(--slate-400)">Budget</span> <strong style="font-size:.85rem">${{fmtEur(budget_d)}}</strong></div>
      <div><span style="font-size:.72rem;color:var(--slate-400)">Importo</span> <strong style="font-size:.85rem">${{fmtEur(imp)}}</strong></div>
      <div><span style="background:${{gBg}};color:${{gCol}};font-size:.74rem;font-weight:700;padding:2px 9px;border-radius:6px;display:inline-block">${{glbl}}</span></div>
      <div style="font-size:.78rem;color:var(--slate-500)">⭐ ${{fmtV(vm)}} · ${{lines.length}} str.</div>
      <div style="font-size:.75rem;color:var(--slate-500)">
        <span style="color:${{targetColor}}">Target ${{fmtPP(dm.target)}}</span> ·
        <span style="color:${{capColor}}">Cap ${{dm.capLabel}}</span> ·
        <span style="color:${{dataColor}}">Dati ${{dataQualityLabel(dm.data)}}</span>
      </div>
      ${{ripartRow?`<div style="font-size:.75rem;color:var(--slate-400)">${{ripartRow}}</div>`:''}}
      ${{actualSummary}}
      ${{note?`<div style="font-size:.74rem;color:var(--slate-400);font-style:italic">«${{note}}»</div>`:''}}
      <div style="margin-left:auto;display:flex;gap:6px;flex-shrink:0">
        <button class="btn-sm" onclick="toggleHistDetail(${{origIdx}})">▼ Dettaglio</button>
        <button class="btn-sm btn-sm-p" onclick="loadDecision(${{origIdx}})" ${{!hasAnalysis?'style="opacity:.6"':''}}>↺ Riparti</button>
        <button class="btn-sm" style="color:var(--red-700);border-color:var(--red-200)" onclick="deleteDecision('${{dec.decision_id}}')">🗑 Elimina</button>
      </div>
    </div>
    <div id="hist_d_${{origIdx}}" class="hist-detail">${{linesHtml||'<em>Nessuna linea</em>'}}${{actualHtml}}${{actualEditHtml}}</div>`;
  }});
  container.innerHTML=html;
}}

renderHistory();
if(hasAnalysis){{sortDecisionRows('decision');prefillSug();}}
</script>"""

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SATOR – Analisi portafoglio</title>
{_SATOR_CSS}
</head>
<body>
<div class="sp">

  <div class="sp-card">
    <div style="display:flex;align-items:center;justify-content:space-between;gap:20px;flex-wrap:wrap;margin-bottom:14px">
      <h1 style="margin:0">🧠 SATOR – Analisi e pianificazione</h1>
      <a href="{STREAMLIT_URL}" target="_blank" style="font-size:.82rem;color:var(--indigo-500);text-decoration:none;font-weight:600">← Torna a Streamlit</a>
    </div>
    {ok_html}{err_html}
    <form method="post" action="/sator" onsubmit="collectCats()">
      <input type="hidden" name="azione" value="analizza">
      <input type="hidden" name="categories_val" id="cats_hidden_input">
      <input type="hidden" name="include_fee_instruments" id="include_fee_hidden_input" value="{'1' if include_fee_instruments else '0'}">
      <div class="form-row">
        <div class="fg fg-lg">
          <label class="lbl">Budget (€)</label>
          <input type="number" name="budget" value="{escape(budget_str)}" min="100" max="1000000" step="100" required>
        </div>
        <div class="fg fg-md">
          <label class="lbl">Severità concentrazione</label>
          <select name="severity">{sev_opts}</select>
        </div>
        <div class="fg fg-sm">
          <label class="lbl">Max linee ordine</label>
          <select name="max_lines">{ml_opts}</select>
        </div>
        <div class="fg" style="flex:2;min-width:220px">
          <label class="lbl">Categorie da analizzare</label>
          <div class="cat-wrap">{cat_checks}</div>
        </div>
        <div class="fg" style="min-width:235px">
          <label class="lbl">Costi operativi</label>
          <label class="filter-check" title="Se disattivo, SATOR esclude dall'universo gli strumenti non marcati a zero commissioni.">
            <input type="checkbox" id="include_fee_checkbox" {fee_checked}>
            <span>Includi commissioni non zero</span>
          </label>
        </div>
        <div class="fg" style="align-self:flex-end;padding-bottom:1px">
          <button type="submit" class="btn-analizza">🔍 Analizza</button>
        </div>
      </div>
    </form>
  </div>

  {body_section}

  <form id="delete_form" method="post" action="/sator" style="display:none">
    <input type="hidden" name="azione" value="elimina">
    <input type="hidden" name="decision_id" id="delete_decision_id">
  </form>
  <form id="actual_form" method="post" action="/sator" style="display:none">
    <input type="hidden" name="azione" value="eseguito">
    <input type="hidden" name="decision_id" id="actual_decision_id">
    <input type="hidden" name="actual_order_json" id="actual_order_json">
  </form>

  <div class="sp-card">
    <h2>Decisioni precedenti <span id="hist_count" style="font-weight:400;color:var(--slate-400)"></span></h2>
    <div id="hist_container"></div>
  </div>

</div>
{js_block}
</body>
</html>"""


def _finite_float(value, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _normalize_actual_order_lines(lines) -> list[dict]:
    if not isinstance(lines, list):
        return []
    normalized = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        ticker = str(line.get("ticker") or "").strip()
        if not ticker:
            continue
        shares = _finite_float(line.get("shares", line.get("quantita", 0.0)), 0.0)
        price = _finite_float(line.get("price", line.get("prezzo", 0.0)), 0.0)
        amount = _finite_float(line.get("amount", line.get("importo", 0.0)), 0.0)
        if amount <= 0 and shares > 0 and price > 0:
            amount = shares * price
        if shares <= 0 and amount <= 0:
            continue
        normalized.append({
            "ticker": ticker,
            "isin": str(line.get("isin") or "").strip(),
            "name": str(line.get("name") or line.get("strumento") or "").strip(),
            "shares": round(shares, 6),
            "price": round(price, 6),
            "amount": round(amount, 2),
        })
    return normalized


def _sator_decisions_json() -> str:
    from persistence.storage import load_sator_decisions
    try:
        dec = load_sator_decisions()
        return json.dumps(list(dec.get("items") or []), ensure_ascii=False, default=str)
    except Exception:
        return "[]"


@router.get("/sator", response_class=HTMLResponse)
async def get_sator(ok: str = "", err: str = ""):
    return HTMLResponse(_render_sator_page(
        ok_msg=ok, err_msg=err,
        decisions_json=_sator_decisions_json(),
    ))


@router.post("/sator", response_class=HTMLResponse)
async def post_sator(
    azione: str = Form(""),
    budget: str = Form("5000"),
    severity: str = Form("2"),
    max_lines: str = Form("5"),
    ranking_json: str = Form(""),
    alerts_json: str = Form(""),
    order_lines_json: str = Form(""),
    note_foto: str = Form(""),
    categories_val: str = Form(""),
    include_fee_instruments: str = Form("1"),
    decision_id: str = Form(""),
    actual_order_json: str = Form(""),
):
    from urllib.parse import quote as urlquote

    cats_str = categories_val.strip() or "ETF,ETC"
    categories_list = [c.strip() for c in cats_str.split(",") if c.strip()] or ["ETF", "ETC"]
    include_fee = str(include_fee_instruments or "1").strip().lower() in ("1", "true", "on", "yes", "si", "sì")
    dec_json = _sator_decisions_json()

    def err_page(msg: str) -> HTMLResponse:
        return HTMLResponse(_render_sator_page(
            budget_str=budget, severity_str=severity,
            max_lines_str=max_lines, categories_val=cats_str,
            include_fee_instruments=include_fee,
            err_msg=msg, decisions_json=dec_json,
        ))

    if azione == "analizza":
        try:
            import pandas as pd
            from persistence.storage import load_data as _ld, load_settings as _ls, apply_privacy_filter
            from core.services.sator import run_sator_analysis, build_sator_matrix_frame

            settings = _ls()
            data = apply_privacy_filter(_ld(), settings)
            budget_f = float(budget or 5000)
            sev_i = max(1, min(4, int(severity or 2)))
            ml_i = max(1, min(10, int(max_lines or 5)))

            analysis = run_sator_analysis(
                data, settings,
                budget=budget_f,
                selected_categories=categories_list,
                include_fee_instruments=include_fee,
                concentration_severity=sev_i,
            )
            ranking_df = analysis.get("ranking")
            if ranking_df is None or (hasattr(ranking_df, "empty") and ranking_df.empty):
                return err_page("Nessuno strumento corrisponde ai criteri selezionati.")

            alerts = list(analysis.get("alerts") or [])
            matrix_df = build_sator_matrix_frame(ranking_df, budget=budget_f, max_lines=ml_i, data=data, settings=settings)

            rj = ranking_df.to_json(orient="records", force_ascii=False)
            aj = json.dumps(alerts, ensure_ascii=False, default=str)
            table_html, rows_js = _build_sator_ranking_html(matrix_df, alerts)

            return HTMLResponse(_render_sator_page(
                budget_str=str(budget_f), severity_str=str(sev_i),
                max_lines_str=str(ml_i), categories_val=cats_str,
                include_fee_instruments=include_fee,
                ranking_html=table_html, rows_js=rows_js,
                budget_for_eval=budget_f,
                ranking_json_esc=escape(rj),
                alerts_json_esc=escape(aj),
                decisions_json=dec_json,
            ))
        except Exception as exc:
            logger.error("SATOR analisi fallita: %s", exc, exc_info=True)
            return err_page(f"Errore durante l'analisi: {exc}")

    elif azione == "salva":
        try:
            import pandas as pd
            from io import StringIO
            from persistence.storage import load_sator_decisions, save_sator_decisions
            from core.services.sator import build_sator_decision_record

            if not order_lines_json.strip():
                return err_page("Nessuna linea di ordine fornita.")
            if not ranking_json.strip():
                return err_page("Dati analisi mancanti — riavvia l'analisi.")

            order_lines = json.loads(order_lines_json)
            ranking_df = pd.read_json(StringIO(ranking_json), orient="records")
            alerts_list = json.loads(alerts_json) if alerts_json.strip() else []

            analysis_payload = {"ranking": ranking_df, "alerts": alerts_list}
            record = build_sator_decision_record(
                analysis_payload,
                order_lines=order_lines,
                budget=float(budget or 0),
                note=note_foto,
            )

            decisions = load_sator_decisions()
            items = list(decisions.get("items") or [])
            items.append(record)
            decisions["items"] = items
            save_sator_decisions(decisions)

            n = record.get("decision_id", "")
            return RedirectResponse(
                f"/sator?ok={urlquote(f'Fotografia salvata ({n}).')}",
                status_code=303,
            )
        except Exception as exc:
            logger.error("SATOR salva fallito: %s", exc, exc_info=True)
            return err_page(f"Errore durante il salvataggio: {exc}")

    elif azione == "elimina":
        try:
            from persistence.storage import load_sator_decisions, save_sator_decisions, remove_sator_decision

            decisions = load_sator_decisions()
            updated, removed = remove_sator_decision(decisions, decision_id)
            save_sator_decisions(updated)
            msg = "Fotografia eliminata." if removed else "Fotografia non trovata (gia' rimossa?)."
            return RedirectResponse(f"/sator?ok={urlquote(msg)}", status_code=303)
        except Exception as exc:
            logger.error("SATOR elimina fallito: %s", exc, exc_info=True)
            return err_page(f"Errore durante l'eliminazione: {exc}")

    elif azione == "eseguito":
        try:
            from datetime import datetime
            from persistence.storage import load_sator_decisions, save_sator_decisions

            if not str(decision_id or "").strip():
                return err_page("Fotografia non identificata.")
            raw_lines = json.loads(actual_order_json) if actual_order_json.strip() else []
            actual_lines = _normalize_actual_order_lines(raw_lines)

            decisions = load_sator_decisions()
            items = list(decisions.get("items") or [])
            found = False
            for item in items:
                if str((item or {}).get("decision_id")) == str(decision_id):
                    item["actual_order"] = actual_lines
                    item["actual_saved_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                    found = True
                    break
            if not found:
                return err_page("Fotografia non trovata.")
            decisions["items"] = items
            save_sator_decisions(decisions)
            msg = "Ordine effettivo aggiornato." if actual_lines else "Ordine effettivo svuotato."
            return RedirectResponse(f"/sator?ok={urlquote(msg)}", status_code=303)
        except Exception as exc:
            logger.error("SATOR eseguito fallito: %s", exc, exc_info=True)
            return err_page(f"Errore durante il salvataggio dell'eseguito: {exc}")

    return err_page("Azione non riconosciuta.")
