"""ui/form_server/sator.py — pagina SATOR del form-server (route /sator).

Estratto da form_server.py. Condivide la stessa pipeline di storage dell'app
principale: nessuna logica duplicata.
"""
from __future__ import annotations

import json
import logging
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
.btn-analizza{padding:9px 24px;background:var(--indigo-500);color:var(--white);border:none;border-radius:9px;font-size:.9rem;font-weight:700;cursor:pointer;white-space:nowrap;transition:background .15s}
.btn-analizza:hover{background:var(--indigo-600)}
.sp-body{display:flex;gap:16px;align-items:flex-start}
.sp-table-col{flex:1;min-width:0}
.sp-eval-panel{width:278px;flex-shrink:0;position:sticky;top:16px}
.ev-h{font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--slate-400);margin:0 0 2px}
.ev-v{font-size:1.05rem;font-weight:800;color:var(--slate-800);transition:color .3s}
.ev-block{margin-bottom:14px;padding-bottom:14px;border-bottom:1px solid var(--slate-100)}
.ev-block:last-of-type{border-bottom:none;margin-bottom:0;padding-bottom:0}
.ev-row{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px}
.bar-wrap{background:var(--slate-200);border-radius:4px;height:7px;overflow:hidden;margin:3px 0 8px}
.bar-fill{height:100%;border-radius:4px;transition:width .4s ease}
.ev-headline{text-align:center;padding:10px 14px;border-radius:10px;font-weight:800;font-size:.9rem;margin:10px 0;display:none}
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
.sc-badge{display:inline-block;font-size:.72rem;font-weight:800;border-radius:4px;padding:2px 5px;line-height:1.2}
.sc-g{background:var(--green-100);color:var(--green-800)}.sc-m{background:var(--yellow-100);color:var(--yellow-800)}.sc-b{background:var(--red-100);color:var(--red-800)}
.rb-dot{display:inline-block;width:11px;height:11px;border-radius:3px;vertical-align:middle}
.rb-core{background:var(--blue-500)}.rb-dif{background:var(--green-500)}.rb-sat{background:var(--orange-500)}
.tbl-actions{display:flex;gap:8px;margin-bottom:12px;align-items:center;flex-wrap:wrap}
.btn-sm{padding:5px 12px;border:1px solid var(--slate-200);background:var(--slate-50);color:var(--slate-600);border-radius:7px;font-size:.78rem;font-weight:600;cursor:pointer;transition:all .15s;white-space:nowrap}
.btn-sm:hover{border-color:var(--indigo-500);color:var(--indigo-500);background:var(--indigo-50)}
.btn-sm-p{background:var(--indigo-50);color:var(--indigo-500);border-color:var(--indigo-200)}
.btn-sm-p:hover{background:var(--indigo-500);color:var(--white)}
.hist-row{display:flex;gap:10px;align-items:center;padding:10px 0;border-bottom:1px solid var(--slate-100);flex-wrap:wrap}
.hist-row:last-child{border-bottom:none}
.hist-detail{background:var(--slate-50);border-radius:8px;padding:12px 14px;margin-bottom:8px;font-size:.8rem;display:none}
.hist-detail .dl{display:flex;gap:10px;padding:4px 0;border-bottom:1px solid var(--slate-200);align-items:center}
.hist-detail .dl:last-child{border-bottom:none}
.alert-warn{background:var(--amber-50);border:1px solid var(--amber-300);border-radius:8px;padding:10px 14px;color:var(--amber-800);font-size:.84rem;margin-bottom:12px}
.alert-ok{background:var(--green-50);border:1px solid var(--green-300);border-radius:8px;padding:10px 14px;color:var(--green-800);font-size:.84rem;margin-bottom:12px}
.notice{background:var(--blue-50);border:1px solid var(--blue-200);border-radius:8px;padding:8px 14px;color:var(--blue-700);font-size:.8rem;margin-bottom:10px;display:none}
.empty-state{text-align:center;color:var(--slate-400);font-size:.84rem;padding:28px 0}
.legend-box{display:flex;flex-wrap:wrap;gap:6px 16px;background:var(--slate-50);border:1px solid var(--slate-200);border-radius:8px;padding:8px 12px;margin-bottom:12px;font-size:.74rem;color:var(--slate-600)}
.legend-box b{color:var(--slate-800)}
</style>"""


def _sc_badge(v: float, lo: float = 5.0, hi: float = 7.0) -> str:
    cls = "sc-g" if v >= hi else "sc-m" if v >= lo else "sc-b"
    return f'<span class="sc-badge {cls}">{v:.0f}</span>'


def _voto_badge(v: float) -> str:
    cls = "sc-g" if v >= 7.5 else "sc-m" if v >= 5.5 else "sc-b"
    return f'<span class="sc-badge {cls}" style="font-size:.8rem;padding:2px 7px">{v:.1f}</span>'


_RUOLO_BADGE_CLASS = {"Core": "rb-core", "Difensivo": "rb-dif", "Satellite": "rb-sat"}


def _ruolo_badge(bucket: str) -> str:
    bucket = bucket if bucket in _RUOLO_BADGE_CLASS else "Satellite"
    return f'<span class="rb-dot {_RUOLO_BADGE_CLASS[bucket]}" title="Ruolo: {bucket}"></span>'


_SATOR_LEGEND_HTML = (
    "<div class='legend-box'>"
    "<span><b>Ruolo</b>: Core = pilastro diversificato, Difensivo = stabilita/liquidita/oro/bond, Satellite = tattico/tematico</span>"
    "<span><b>Voto</b> 1–10: punteggio unico, ordina la classifica</span>"
    "<span><b>Fit</b> 30%: quanto la funzione serve ora al portafoglio</span>"
    "<span><b>Mom</b> 25%: andamento ponderato 1/3/6/12 mesi</span>"
    "<span><b>Risk</b> 20%: volatilità, drawdown, rendimento/rischio</span>"
    "<span><b>Div</b> 15%: bassa correlazione e copertura di vuoti</span>"
    "<span><b>Cost</b> 10%: commissioni, TER, spread, prezzo/budget</span>"
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
            "prezzo":   float(row.get("Px", row.get("_price", 0))),
            "qp":       float(row.get("Qp", 0)),
            "sug":      int(row.get("Sug", 0)),
            "fit":      float(row.get("Fit", 0)),
            "mom":      float(row.get("Mom", 0)),
            "risk":     float(row.get("Risk", 0)),
            "div_s":    float(row.get("Div", 0)),
            "cost":     float(row.get("Cost", 0)),
            "fit_raw":  float(row.get("_fit", 0)),
            "risk_raw": float(row.get("_risk", 0)),
            "why":      str(row.get("_why", "")),
            "sem":      str(row.get("Sem", "⚪")),
            "dati_ok":  bool(row.get("_storico_ok", True)),
            "zero_commission": bool(row.get("_zero_commission", False)),
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
        table_rows += (
            f"<tr>"
            f"<td style='font-size:1.05rem;padding-left:4px;width:22px'>{sem}</td>"
            f"<td style='font-weight:800;white-space:nowrap;width:66px;overflow:hidden;text-overflow:ellipsis'>{tk}{comm_badge}{dati_warning}</td>"
            f"<td style='width:106px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--slate-600)' title='{name_esc}'>{name_short}</td>"
            f"<td style='width:80px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:.7rem;color:var(--slate-500)' title='{escape(funz_full)}'>{funz}</td>"
            f"<td style='text-align:center;width:24px'>{_ruolo_badge(r['bucket'])}</td>"
            f"<td style='text-align:center;width:36px' title='{why_esc}'>{_voto_badge(r['voto'])}</td>"
            f"<td style='text-align:center;width:28px'>{_sc_badge(r['fit'])}</td>"
            f"<td style='text-align:center;width:28px'>{_sc_badge(r['mom'])}</td>"
            f"<td style='text-align:center;width:28px'>{_sc_badge(r['risk'])}</td>"
            f"<td style='text-align:center;width:28px'>{_sc_badge(r['div_s'])}</td>"
            f"<td style='text-align:center;width:28px'>{_sc_badge(r['cost'])}</td>"
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
        f"<span style='font-size:.74rem;color:var(--slate-400);margin-left:4px'>Modifica Qta → valutazione live a destra</span>"
        f"</div>"
        f"<div>"
        f"<table class='sr-table'><thead><tr>"
        f"<th style='width:22px'></th>"
        f"<th style='width:66px'>Ticker</th>"
        f"<th style='width:106px'>Strumento</th>"
        f"<th style='width:80px'>Funzione</th>"
        f"<th style='width:24px;text-align:center' title='Ruolo nel portafoglio: blu=Core (pilastro diversificato), verde=Difensivo (stabilita, liquidita, oro, bond), arancio=Satellite (tattico/tematico)'></th>"
        f"<th style='width:36px;text-align:center' title='Punteggio unico 1-10: ordina la classifica. Passa il mouse per il perche della posizione'>Voto</th>"
        f"<th style='width:28px;text-align:center' title='Fit allocativo 30%: quanto la funzione serve ora al portafoglio'>Fit</th>"
        f"<th style='width:28px;text-align:center' title='Momentum 25%: andamento ponderato 1/3/6/12 mesi'>Mom</th>"
        f"<th style='width:28px;text-align:center' title='Efficienza di rischio 20%: volatilita, drawdown, rendimento/rischio'>Risk</th>"
        f"<th style='width:28px;text-align:center' title='Diversificazione 15%: bassa correlazione e copertura di vuoti'>Div</th>"
        f"<th style='width:28px;text-align:center' title='Efficienza di costo 10%: commissioni, TER, spread, prezzo/budget'>Cost</th>"
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
    <div class="bar-wrap"><div class="bar-fill" id="ev_core_bar" style="background:var(--blue-500);width:0%"></div></div>
    <div style="display:flex;justify-content:space-between;font-size:.8rem"><span style="color:var(--green-500);font-weight:600">Difensivo</span><span id="ev_diff_pct">—</span></div>
    <div class="bar-wrap"><div class="bar-fill" id="ev_diff_bar" style="background:var(--green-500);width:0%"></div></div>
    <div style="display:flex;justify-content:space-between;font-size:.8rem"><span style="color:var(--orange-500);font-weight:600">Satellite</span><span id="ev_sat_pct">—</span></div>
    <div class="bar-wrap"><div class="bar-fill" id="ev_sat_bar" style="background:var(--orange-500);width:0%"></div></div>
  </div>
  <div class="ev-block" id="ev_scores_sec" style="display:none">
    <div class="ev-row"><span class="ev-h">Voto medio pond.</span><span class="ev-v" id="ev_voto">—</span></div>
    <div class="ev-row"><span class="ev-h">Strumenti</span><span id="ev_nsel" style="font-weight:700">—</span></div>
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

        body_section = (
            f'<div class="sp-body" id="sp_body">'
            f'<div class="sp-table-col sp-card"><h2>Classifica SATOR</h2>{ranking_html}</div>'
            f'{eval_panel}'
            f'</div>'
        )

    js_block = f"""<script>
const satorRows={rows_js};
const budget_val={budget_for_eval};
const hasAnalysis=satorRows.length>0;
const decisions={decisions_json.replace("</","<\\/")};

const fmtEur=v=>'€\xa0'+parseFloat(v||0).toLocaleString('it-IT',{{minimumFractionDigits:2,maximumFractionDigits:2}});
const fmtPct=v=>parseFloat(v||0).toFixed(1)+'%';
const fmtV=v=>parseFloat(v||0).toFixed(1);

function collectCats(){{
  const cats=[];
  document.querySelectorAll('input[name^="cat_"]:checked').forEach(cb=>cats.push(cb.value));
  document.getElementById('cats_hidden_input').value=cats.join(',');
}}

function computeEval(){{
  if(!hasAnalysis)return;
  let total=0,nsel=0;
  let bkts={{Core:0,Difensivo:0,Satellite:0}};
  let voto_s=0,fit_s=0,risk_s=0,peso_s=0;
  satorRows.forEach(r=>{{
    const sel=document.getElementById('sel_'+r.ticker)?.checked;
    const qta=parseInt(document.getElementById('qta_'+r.ticker)?.value||'0')||0;
    if(sel&&qta>0){{
      const amt=r.prezzo*qta; total+=amt; nsel++;
      bkts[r.bucket]=(bkts[r.bucket]||0)+amt;
      if(r.voto>0)voto_s+=r.voto*amt;
      fit_s+=r.fit_raw*amt; risk_s+=r.risk_raw*amt; peso_s+=amt;
    }}
  }});
  const t=document.getElementById('ev_total'),d=document.getElementById('ev_delta');
  t.textContent=nsel?fmtEur(total):'—'; t.style.color=nsel?'var(--slate-800)':'var(--slate-400)';
  const btn=document.getElementById('btn_save'); if(btn)btn.disabled=nsel===0;
  if(!nsel){{
    d.textContent='—';d.style.color='var(--slate-400)';
    document.getElementById('ev_rip_sec').style.display='none';
    document.getElementById('ev_scores_sec').style.display='none';
    document.getElementById('ev_headline_box').style.display='none';
    document.getElementById('ev_nsel').textContent='—';
    document.getElementById('ev_voto').textContent='—';
    return;
  }}
  const delta=total-budget_val;
  const overTol=Math.max(1,budget_val*.05),underLim=Math.max(50,budget_val*.10);
  d.textContent=(delta>=0?'+':'')+fmtEur(delta);
  d.style.color=delta>overTol?'var(--red-500)':delta>0?'var(--orange-500)':delta<-underLim?'var(--amber-500)':'var(--green-500)';
  const cpct=total>0?(bkts.Core||0)/total*100:0;
  const dpct=total>0?(bkts.Difensivo||0)/total*100:0;
  const spct=total>0?(bkts.Satellite||0)/total*100:0;
  document.getElementById('ev_rip_sec').style.display='';
  document.getElementById('ev_core_pct').textContent=fmtPct(cpct)+' · '+fmtEur(bkts.Core||0);
  document.getElementById('ev_diff_pct').textContent=fmtPct(dpct)+' · '+fmtEur(bkts.Difensivo||0);
  document.getElementById('ev_sat_pct').textContent=fmtPct(spct)+' · '+fmtEur(bkts.Satellite||0);
  document.getElementById('ev_core_bar').style.width=cpct+'%';
  document.getElementById('ev_diff_bar').style.width=dpct+'%';
  document.getElementById('ev_sat_bar').style.width=spct+'%';
  document.getElementById('ev_scores_sec').style.display='';
  document.getElementById('ev_nsel').textContent=nsel;
  const vm=peso_s>0?voto_s/peso_s:0;
  document.getElementById('ev_voto').textContent=fmtV(vm);
  const af=peso_s>0?fit_s/peso_s:0,ar=peso_s>0?risk_s/peso_s:0;
  let headline,hlBg,hlCol;
  if(delta>overTol){{headline='Fuori budget';hlBg='var(--red-50)';hlCol='var(--red-700)';}}
  else if(delta>0){{headline='Appena fuori budget';hlBg='var(--orange-50)';hlCol='var(--orange-700)';}}
  else if(delta<-underLim){{headline='Budget sottoutilizzato';hlBg='var(--yellow-50)';hlCol='var(--amber-800)';}}
  else if(af>=0.62&&ar>=0.50){{headline='Scelta coerente ✓';hlBg='var(--green-50)';hlCol='var(--green-700)';}}
  else{{headline='Scelta da rivedere';hlBg='var(--orange-50)';hlCol='var(--orange-700)';}}
  const hbox=document.getElementById('ev_headline_box');
  hbox.style.display='';hbox.style.background=hlBg;hbox.style.color=hlCol;hbox.textContent=headline;
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
  sorted.forEach((dec,ri)=>{{
    const origIdx=decisions.length-1-ri;
    const created=(dec.created_at||'').slice(0,16).replace('T',' ');
    const budget_d=parseFloat(dec.budget||0);
    const imp=parseFloat(dec.importo_ordine||0);
    const vm=parseFloat(dec.giudizio?.voto_medio||0);
    const glbl=dec.giudizio?.label||'—';
    const lines=dec.order_lines||[];
    const note=(dec.note||'').trim();
    const gCol=glbl.includes('coerente')?'var(--green-700)':glbl.includes('rivedere')?'var(--orange-700)':'var(--amber-800)';
    const gBg=glbl.includes('coerente')?'var(--green-50)':glbl.includes('rivedere')?'var(--orange-50)':'var(--yellow-50)';
    let linesHtml='';
    lines.forEach(l=>{{
      const am=parseFloat(l.amount||l.importo||0);
      linesHtml+=`<div class="dl"><span style="font-weight:800;min-width:60px">${{l.ticker}}</span><span style="flex:1;color:var(--slate-500)">${{l.name||''}}</span><span style="white-space:nowrap;color:var(--slate-600)">${{l.shares||l.quantita||0}} q × ${{fmtEur(l.price||l.prezzo||0)}}</span><span style="font-weight:700;margin-left:10px">${{fmtEur(am)}}</span></div>`;
    }});
    const ripartRow=Object.entries(dec.ripartizione||{{}}).filter(([,v])=>v.amount>0).map(([k,v])=>`<span style="font-size:.75rem;color:var(--slate-500)">${{k}}: ${{fmtPct(v.pct)}}</span>`).join(' · ');
    html+=`
    <div class="hist-row">
      <div style="min-width:105px;font-size:.75rem;color:var(--slate-500)">${{created}}</div>
      <div><span style="font-size:.72rem;color:var(--slate-400)">Budget</span> <strong style="font-size:.85rem">${{fmtEur(budget_d)}}</strong></div>
      <div><span style="font-size:.72rem;color:var(--slate-400)">Importo</span> <strong style="font-size:.85rem">${{fmtEur(imp)}}</strong></div>
      <div><span style="background:${{gBg}};color:${{gCol}};font-size:.74rem;font-weight:700;padding:2px 9px;border-radius:6px;display:inline-block">${{glbl}}</span></div>
      <div style="font-size:.78rem;color:var(--slate-500)">⭐ ${{fmtV(vm)}} · ${{lines.length}} str.</div>
      ${{ripartRow?`<div style="font-size:.75rem;color:var(--slate-400)">${{ripartRow}}</div>`:''}}
      ${{note?`<div style="font-size:.74rem;color:var(--slate-400);font-style:italic">«${{note}}»</div>`:''}}
      <div style="margin-left:auto;display:flex;gap:6px;flex-shrink:0">
        <button class="btn-sm" onclick="toggleHistDetail(${{origIdx}})">▼ Dettaglio</button>
        <button class="btn-sm btn-sm-p" onclick="loadDecision(${{origIdx}})" ${{!hasAnalysis?'style="opacity:.6"':''}}>↺ Riparti</button>
        <button class="btn-sm" style="color:var(--red-700);border-color:var(--red-200)" onclick="deleteDecision('${{dec.decision_id}}')">🗑 Elimina</button>
      </div>
    </div>
    <div id="hist_d_${{origIdx}}" class="hist-detail">${{linesHtml||'<em>Nessuna linea</em>'}}</div>`;
  }});
  container.innerHTML=html;
}}

renderHistory();
if(hasAnalysis){{prefillSug();}}
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

  <div class="sp-card">
    <h2>Decisioni precedenti <span id="hist_count" style="font-weight:400;color:var(--slate-400)"></span></h2>
    <div id="hist_container"></div>
  </div>

</div>
{js_block}
</body>
</html>"""


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
    decision_id: str = Form(""),
):
    from urllib.parse import quote as urlquote

    cats_str = categories_val.strip() or "ETF,ETC"
    categories_list = [c.strip() for c in cats_str.split(",") if c.strip()] or ["ETF", "ETC"]
    dec_json = _sator_decisions_json()

    def err_page(msg: str) -> HTMLResponse:
        return HTMLResponse(_render_sator_page(
            budget_str=budget, severity_str=severity,
            max_lines_str=max_lines, categories_val=cats_str,
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
                concentration_severity=sev_i,
            )
            ranking_df = analysis.get("ranking")
            if ranking_df is None or (hasattr(ranking_df, "empty") and ranking_df.empty):
                return err_page("Nessuno strumento corrisponde ai criteri selezionati.")

            alerts = list(analysis.get("alerts") or [])
            matrix_df = build_sator_matrix_frame(ranking_df, budget=budget_f, max_lines=ml_i)

            rj = ranking_df.to_json(orient="records", force_ascii=False)
            aj = json.dumps(alerts, ensure_ascii=False, default=str)
            table_html, rows_js = _build_sator_ranking_html(matrix_df, alerts)

            return HTMLResponse(_render_sator_page(
                budget_str=str(budget_f), severity_str=str(sev_i),
                max_lines_str=str(ml_i), categories_val=cats_str,
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

    return err_page("Azione non riconosciuta.")
