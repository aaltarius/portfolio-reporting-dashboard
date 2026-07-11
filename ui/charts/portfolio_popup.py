from __future__ import annotations

import json

import pandas as pd
from persistence.storage import macro_cat
from ui.charts.natura_icons import get_natura_visual
from ui.streamlit_compat import iframe_height_for_rows, render_html_iframe
from ui.theme import CATEGORY_COLORS, macro_color

# Modulo shared HTML/popup.
# Ruolo:
# - render tabella portafoglio arricchita con popup dettagli strumento
# - usato come supporto UI trasversale, non associato a un chart_id Plotly
#
# render_quotes_table_with_popup (l'altra funzione che viveva qui) e' stata
# rimossa il 2026-07-07: duplicata di ui/charts/quotes_popup.py, che e' la
# versione realmente importata da ui/pages/quotazioni.py — verificato con
# grep sull'intero repo.


def _build_ticker_info(df, data):
    """Dizionario per-ticker (nome/isin/prezzo/pmc/... + sparkline) usato dal modale di dettaglio.

    Condiviso da render_portfolio_table_with_popup e render_weekly_pl_table
    cosi' il click sul ticker apre lo stesso identico popup in entrambe le tabelle.
    """
    storico = data.get("storico_prezzi", {}) or {}
    info_map = {s["ticker"]: s for s in data.get("strumenti", [])}
    ds_sorted = sorted(storico.keys())[-60:]
    ticker_info = {}
    for _, row in df.iterrows():
        tk = str(row.get("Ticker", ""))
        info = info_map.get(tk, {})
        spark = []
        for d in ds_sorted:
            v = storico[d].get(tk)
            if v is not None:
                try:
                    spark.append({"d": d, "v": float(v)})
                except Exception:
                    pass
        try:
            _pl_e = float(row.get("P/L €", 0) or 0)
            _pl_p = float(row.get("P/L %", 0) or 0)
            _prezzo = float(row.get("Prezzo", 0) or 0)
            _pmc = float(row.get("PMC", 0) or 0)
            _qty = float(row.get("Quote", 0) or 0)
            _ctv = float(row.get("Controvalore", 0) or 0)
            _costo = float(row.get("Costo", 0) or 0)
            _comm = float(row.get("Comm.", 0) or 0)
        except Exception:
            _pl_e = _pl_p = _prezzo = _pmc = _qty = _ctv = _costo = _comm = 0.0
        ticker_info[tk] = {
            "nome": info.get("nome", tk),
            "isin": info.get("isin", "n/d"),
            "tipo": info.get("tipo", "n/d"),
            "fonte": info.get("fonte", "n/d"),
            "aggiornato": info.get("aggiornato", "n/d"),
            "prezzo": _prezzo,
            "pmc": _pmc,
            "qty": _qty,
            "ctv": _ctv,
            "costo": _costo,
            "comm": _comm,
            "pl_e": _pl_e,
            "pl_p": _pl_p,
            "spark": spark,
        }
    return ticker_info


_MODAL_CSS = """
a.tk-link{text-decoration:none;font-weight:700;cursor:pointer;border-bottom:1.5px dotted;transition:opacity .15s;}
a.tk-link:hover{opacity:0.65;}
#mo{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;align-items:center;justify-content:center;}
#mo.on{display:flex;}
#mc{background:#fff;border-radius:18px;padding:20px 24px 18px;max-width:900px;width:97%;max-height:90vh;overflow-y:auto;box-shadow:0 12px 52px rgba(0,0,0,.26);position:relative;color:#1f2937;}
#mc-close{position:absolute;top:10px;right:14px;cursor:pointer;font-size:1.3rem;color:#9ca3af;background:none;border:none;line-height:1;}
#mc-close:hover{color:#374151;}
.mc-cols{display:grid;grid-template-columns:40% 60%;gap:18px;align-items:start;}
.mc-left{min-width:0;}
.mc-right{min-width:0;display:flex;flex-direction:column;gap:8px;}
.mc-ticker{font-size:1.8rem;font-weight:900;letter-spacing:-.01em;margin-bottom:2px;}
.mc-nome{font-size:1.0rem;color:#374151;font-weight:600;}
.mc-meta{font-size:0.85rem;color:#9ca3af;margin:4px 0 12px;}
.mc-grid{display:grid;grid-template-columns:1fr 1fr;gap:5px;}
.mc-kpi{border:1px solid #e5e7eb;border-radius:8px;padding:8px 12px;}
.mc-kpi-l{font-size:0.82rem;text-transform:uppercase;color:#9ca3af;font-weight:700;letter-spacing:.04em;margin-bottom:3px;}
.mc-kpi-v{font-size:1.15rem;font-weight:700;font-variant-numeric:tabular-nums;}
.pos{color:#1E8449;} .neg{color:#FF4B4B;}
.mc-price-box{background:#f9fafb;border:1px solid #e5e7eb;border-radius:11px;padding:10px 14px;display:flex;align-items:baseline;gap:12px;}
.mc-price-val{font-size:2.0rem;font-weight:800;font-variant-numeric:tabular-nums;}
.mc-price-sub{font-size:0.95rem;color:#6b7280;}
.mc-spark-label{font-size:0.78rem;text-transform:uppercase;color:#9ca3af;font-weight:700;letter-spacing:.05em;}
svg.spark{width:100%;height:140px;display:block;border-radius:10px;background:#f9fafb;}
.mc-footer{font-size:0.78rem;color:#9ca3af;}
"""

_MODAL_HTML = """
<div id="mo" onclick="if(event.target===this)closeM()">
<div id="mc">
  <button id="mc-close" onclick="closeM()">&#x2715;</button>
  <div class="mc-cols">
    <div class="mc-left">
      <div class="mc-ticker" id="m-tk"></div>
      <div class="mc-nome" id="m-nm"></div>
      <div class="mc-meta" id="m-meta"></div>
      <div class="mc-grid" id="m-grid"></div>
    </div>
    <div class="mc-right">
      <div class="mc-price-box">
        <div>
          <div style="font-size:0.78rem;text-transform:uppercase;color:#9ca3af;font-weight:700;margin-bottom:2px;">Prezzo attuale</div>
          <div class="mc-price-val" id="m-px"></div>
        </div>
        <div id="m-delta" class="mc-price-sub"></div>
      </div>
      <div class="mc-spark-label">Andamento prezzo (ultimi 60 giorni disponibili)</div>
      <svg class="spark" id="m-spark" viewBox="0 0 520 140" preserveAspectRatio="none"></svg>
      <div class="mc-footer" id="m-footer"></div>
    </div>
  </div>
</div>
</div>
"""

_MODAL_JS = """
var D=__TICKER_JSON__;
function fi(v,d,sgn){
  if(v==null||isNaN(v))return'n/d';
  var n=parseFloat(v).toLocaleString('it-IT',{minimumFractionDigits:d,maximumFractionDigits:d});
  return (sgn&&v>0?'+':'')+n;
}
function fe(v,d,sgn){return fi(v,d!=null?d:2,sgn)+' €';}
function fmtDateIt(v){if(!v)return 'n/d';var p=String(v).slice(0,10).split('-');return p.length===3?(p[2]+'/'+p[1]+'/'+p[0]):String(v);}
function fp(v,d,sgn){
  if(v==null||isNaN(v))return'n/d';
  var pct=parseFloat(v)*100;
  var n=pct.toLocaleString('it-IT',{minimumFractionDigits:d!=null?d:1,maximumFractionDigits:d!=null?d:1});
  return(sgn&&pct>0?'+':'')+n+'%';
}
function kpi(label,val,cls){
  return '<div class="mc-kpi"><div class="mc-kpi-l">'+label+'</div><div class="mc-kpi-v'+(cls?' '+cls:'')+'">'+val+'</div></div>';
}
function sparkline(data,plPositive,pmc){
  var svg=document.getElementById('m-spark');
  svg.innerHTML='';
  var W=520,H=140,pad=6;
  if(!data||data.length<2){
    var t=document.createElementNS('http://www.w3.org/2000/svg','text');
    t.setAttribute('x','50%');t.setAttribute('y','52%');t.setAttribute('text-anchor','middle');
    t.setAttribute('fill','#d1d5db');t.setAttribute('font-size','10');t.setAttribute('font-family','system-ui');
    t.textContent='Dati storici non disponibili';svg.appendChild(t);return;
  }
  var vals=data.map(function(p){return p.v;});
  var mn=Math.min.apply(null,vals),mx=Math.max.apply(null,vals);if(pmc!=null&&!isNaN(pmc)){mn=Math.min(mn,pmc);mx=Math.max(mx,pmc);}var rng=mx-mn||0.001;var toY=function(v){return H-pad-((v-mn)/rng*(H-pad*2));};
  var pts=[];
  vals.forEach(function(v,i){
    var x=pad+(i/(vals.length-1))*(W-pad*2);
    var y=toY(v);
    pts.push(x.toFixed(1)+','+y.toFixed(1));
  });
  var col=plPositive?'#1E8449':'#FF4B4B';
  var fill=plPositive?'rgba(30,132,73,0.12)':'rgba(255,75,75,0.12)';
  var lx=parseFloat(pts[vals.length-1].split(',')[0]),ly=parseFloat(pts[vals.length-1].split(',')[1]);var pmcY=(pmc!=null&&!isNaN(pmc))?toY(pmc):null;
  var area=document.createElementNS('http://www.w3.org/2000/svg','polygon');
  area.setAttribute('points',pts[0].split(',')[0]+','+(H-pad)+' '+pts.join(' ')+' '+lx+','+(H-pad));
  area.setAttribute('fill',fill);svg.appendChild(area);if(pmcY!=null){var pmcLine=document.createElementNS('http://www.w3.org/2000/svg','line');pmcLine.setAttribute('x1',pad);pmcLine.setAttribute('x2',W-pad);pmcLine.setAttribute('y1',pmcY);pmcLine.setAttribute('y2',pmcY);pmcLine.setAttribute('stroke','#6b7280');pmcLine.setAttribute('stroke-width','1.8');pmcLine.setAttribute('stroke-dasharray','7 5');pmcLine.setAttribute('opacity','0.98');svg.appendChild(pmcLine);var pmcText=document.createElementNS('http://www.w3.org/2000/svg','text');pmcText.setAttribute('x',W-pad-4);pmcText.setAttribute('y',Math.max(12,pmcY-4));pmcText.setAttribute('text-anchor','end');pmcText.setAttribute('fill','#4b5563');pmcText.setAttribute('font-size','10');pmcText.setAttribute('font-family','system-ui');pmcText.textContent='PMC';svg.appendChild(pmcText);}
  var line=document.createElementNS('http://www.w3.org/2000/svg','polyline');
  line.setAttribute('points',pts.join(' '));
  line.setAttribute('fill','none');line.setAttribute('stroke',col);line.setAttribute('stroke-width','2');
  svg.appendChild(line);
  var dot=document.createElementNS('http://www.w3.org/2000/svg','circle');
  dot.setAttribute('cx',lx);dot.setAttribute('cy',ly);dot.setAttribute('r','4');
  dot.setAttribute('fill',col);dot.setAttribute('stroke','#fff');dot.setAttribute('stroke-width','1.5');
  svg.appendChild(dot);
}
function showModal(tk){
  var d=D[tk];if(!d)return;
  var plCls=d.pl_e>=0?'pos':'neg';
  var delta=d.pmc>0?(d.prezzo/d.pmc-1)*100:null;
  document.getElementById('m-tk').textContent=tk;
  document.getElementById('m-tk').style.color=d.pl_e>=0?'#1E8449':'#374151';
  document.getElementById('m-nm').textContent=d.nome;
  document.getElementById('m-meta').textContent='ISIN: '+d.isin+' · '+d.tipo;
  document.getElementById('m-px').textContent=fe(d.prezzo,3,false);
  document.getElementById('m-px').className='mc-price-val '+plCls;
  document.getElementById('m-delta').innerHTML=delta!=null?'<span class="'+plCls+'">'+(delta>=0?'+':'')+fi(delta,2,false)+'% vs PMC</span>':'';
  document.getElementById('m-grid').innerHTML=
    kpi('PMC',fe(d.pmc,3,false))+
    kpi('Quantità',fi(d.qty,3,false))+
    kpi('Controvalore',fe(d.ctv,2,false))+
    kpi('Costo storico',fe(d.costo,2,false))+
    kpi('P/L €',fe(d.pl_e,2,true),plCls)+
    kpi('P/L %',fp(d.pl_p,2,true),plCls)+
    kpi('Commissioni',fe(d.comm,2,false))+
    kpi('Fonte / Agg.',d.fonte+' · '+fmtDateIt(d.aggiornato));
  sparkline(d.spark,d.pl_e>=0,d.pmc);
  document.getElementById('m-footer').textContent='Quotazione aggiornata al '+fmtDateIt(d.aggiornato)+' · Fonte: '+d.fonte;
  document.getElementById('mo').classList.add('on');
}
function closeM(){document.getElementById('mo').classList.remove('on');}
document.addEventListener('keydown',function(e){if(e.key==='Escape')closeM();});
"""


def render_portfolio_table_with_popup(df, data, direction_map=None):
    """Render the portfolio table with inline popup details for each ticker.

    Chiamato da: flussi UI del portafoglio/home che mostrano la tabella holdings.
    Nota: non passa da apply_settings perche' non e' un grafico Plotly ma un blocco HTML.
    """
    if df is None or df.empty:
        return
    direction_map = direction_map or {}
    info_map = {s["ticker"]: s for s in data.get("strumenti", [])}
    ticker_info = _build_ticker_info(df, data)
    cat_color_map = CATEGORY_COLORS

    def _cat_col(tipo):
        cat = macro_cat(tipo)
        return cat_color_map.get(cat, macro_color(cat))

    def _trend_sym(tk):
        state = direction_map.get(str(tk or ""), "flat")
        if state == "up_big":
            return ("▲▲", "#1E8449")
        if state == "up":
            return ("▲", "#1E8449")
        if state == "down_big":
            return ("▼▼", "#FF4B4B")
        if state == "down":
            return ("▼", "#FF4B4B")
        return ("—", "#9CA3AF")

    def _fmt_num(v, dec=2):
        try:
            f = float(v)
            s = f"{f:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
            return s
        except Exception:
            return "n/d"

    def _fmt_eur(v, dec=2, signed=False):
        try:
            f = float(v)
            s = _fmt_num(f, dec)
            if signed and f > 0:
                return f"+{s} €"
            return f"{s} €"
        except Exception:
            return "n/d"

    def _fmt_pct(v, dec=1, signed=False):
        try:
            f = float(v) * 100
            s = _fmt_num(f, dec)
            if signed and f > 0:
                return f"+{s}%"
            return f"{s}%"
        except Exception:
            return "n/d"

    def _sort_val_num(v):
        try:
            return str(round(float(v or 0), 6))
        except Exception:
            return "0"

    rows_html = ""
    for _, row in df.iterrows():
        tk = str(row.get("Ticker", ""))
        tipo = str(row.get("Tipo", ""))
        nome = str(row.get("Strumento", ""))
        info = info_map.get(tk, {})
        natura_label = str(info.get("natura") or "Esposizione diversificata")
        natura_color, natura_svg = get_natura_visual(natura_label)
        col = _cat_col(tipo)
        sym, sym_col = _trend_sym(tk)
        try:
            pl_e = float(row.get("P/L €", 0) or 0)
            pl_p = float(row.get("P/L %", 0) or 0)
        except Exception:
            pl_e = pl_p = 0.0
        pl_col = "#1E8449" if pl_e >= 0 else "#FF4B4B"
        pl_e_str = _fmt_eur(pl_e, 2, signed=True)
        pl_p_str = _fmt_pct(pl_p, 2, signed=True)
        sym_sort = "1" if sym == "▲" else "2" if sym == "—" else "3"
        rows_html += (
            f'''<tr>\n          <td data-sort="{sym_sort}" style="color:{sym_col};font-weight:800;">{sym}</td>\n'''
            f'''          <td data-sort="{tk}"><a class="tk-link" style="color:{col}" href="#" onclick="showModal('{tk}');return false;">{tk}</a></td>\n'''
            f'''          <td data-sort="{nome}" style="color:{col};max-width:140px;" title="{nome}">{nome[:24]}</td>\n'''
            f'''          <td data-sort="{tipo}" style="color:{col};max-width:80px;" title="{tipo}">{tipo[:16]}</td>\n'''
            f'''          <td class="natura-cell" title="{natura_label}" style="color:{natura_color};width:20px;text-align:center;">{natura_svg}</td>\n'''
            f'''          <td class="num" data-sort="{_sort_val_num(row.get('Quote', ''))}">{_fmt_num(row.get('Quote', ''), 3)}</td>\n'''
            f'''          <td class="num" data-sort="{_sort_val_num(row.get('Prezzo', ''))}">{_fmt_eur(row.get('Prezzo', ''), 3)}</td>\n'''
            f'''          <td class="num" data-sort="{_sort_val_num(row.get('PMC', ''))}">{_fmt_eur(row.get('PMC', ''), 3)}</td>\n'''
            f'''          <td class="num" data-sort="{_sort_val_num(row.get('Controvalore', ''))}">{_fmt_eur(row.get('Controvalore', ''), 2)}</td>\n'''
            f'''          <td class="num" data-sort="{_sort_val_num(row.get('Costo', ''))}">{_fmt_eur(row.get('Costo', ''), 2)}</td>\n'''
            f'''          <td class="num" data-sort="{_sort_val_num(row.get('Comm.', ''))}">{_fmt_eur(row.get('Comm.', ''), 2)}</td>\n'''
            f'''          <td class="num" data-sort="{_sort_val_num(pl_e)}" style="color:{pl_col};font-weight:700;">{pl_e_str}</td>\n'''
            f'''          <td class="num" data-sort="{_sort_val_num(pl_p)}" style="color:{pl_col};font-weight:700;">{pl_p_str}</td>\n'''
            f"""        </tr>"""
        )
    _total_ctv = float(pd.to_numeric(df["Controvalore"], errors="coerce").fillna(0).sum())
    _total_cost = float(pd.to_numeric(df["Costo"], errors="coerce").fillna(0).sum())
    _total_comm = float(pd.to_numeric(df["Comm."], errors="coerce").fillna(0).sum())
    _total_pl_e = float(pd.to_numeric(df["P/L €"], errors="coerce").fillna(0).sum())
    _total_pl_p = _total_pl_e / abs(_total_cost) if abs(_total_cost) > 1e-09 else 0.0
    _total_pl_col = "#1E8449" if _total_pl_e >= 0 else "#FF4B4B"
    tfoot_html = (
        f'<tfoot><tr><td></td><td colspan="7" style="font-weight:800;font-size:0.85rem;letter-spacing:.02em;padding:9px 12px;">TOTALE</td>'
        f'<td class="num" style="font-weight:700;padding:9px 12px;">{_fmt_eur(_total_ctv, 2)}</td>'
        f'<td class="num" style="font-weight:700;padding:9px 12px;">{_fmt_eur(_total_cost, 2)}</td>'
        f'<td class="num" style="font-weight:700;padding:9px 12px;">{_fmt_eur(_total_comm, 2)}</td>'
        f'<td class="num" style="color:{_total_pl_col};font-weight:800;padding:9px 12px;">{_fmt_eur(_total_pl_e, 2, signed=True)}</td>'
        f'<td class="num" style="color:{_total_pl_col};font-weight:800;padding:9px 12px;">{_fmt_pct(_total_pl_p, 2, signed=True)}</td></tr></tfoot>'
    )
    ticker_json = json.dumps(ticker_info, ensure_ascii=False)
    n_rows = len(df)
    iframe_h = iframe_height_for_rows(
        n_rows, row_height=35, header_height=48, padding=50, min_height=160, max_height=1100, content_until_rows=18
    )
    html_content = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box;margin:0;padding:0;}}
html,body{{background:transparent;font-family:"Source Sans Pro",system-ui,-apple-system,sans-serif;font-size:14px;overflow:hidden;color:#262730;}}
.tw{{border:1px solid #e6e9ef;border-radius:8px;overflow:hidden;background:#fff;width:100%;}}
table{{width:100%;border-collapse:collapse;table-layout:auto;}}
thead th{{
  background:#f0f2f6;font-size:12px;font-weight:600;letter-spacing:.01em;
  color:#262730;padding:9px 12px;border-bottom:1px solid #e6e9ef;border-right:1px solid #e6e9ef;
  text-align:right;white-space:nowrap;position:relative;user-select:none;cursor:pointer;
}}
thead th:last-child{{border-right:none;}}
thead th:nth-child(1),thead th:nth-child(5){{text-align:center;width:26px;cursor:default;padding:9px 6px;}}
thead th:nth-child(2),thead th:nth-child(3),thead th:nth-child(4){{text-align:left;}}
thead th:hover:not(:nth-child(1)):not(:nth-child(5)){{background:#e3e6e9;}}
thead th .sort-ind{{font-size:9px;margin-left:3px;color:#9094a3;}}
thead th.asc .sort-ind::after{{content:'▲';color:#262730;}}
thead th.desc .sort-ind::after{{content:'▼';color:#262730;}}
.rh{{position:absolute;right:0;top:0;height:100%;width:4px;cursor:col-resize;background:transparent;z-index:1;}}
.rh:hover{{background:#9094a3;opacity:.4;}}
tbody tr{{border-bottom:1px solid #f0f2f6;}}
tbody tr:last-child{{border-bottom:none;}}
tbody tr:hover{{background:#f0f2f6;}}
tbody td{{padding:9px 12px;vertical-align:middle;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;border-right:1px solid #f0f2f6;}}
tbody td:last-child{{border-right:none;}}
tbody td:nth-child(1),tbody td:nth-child(5){{padding:9px 6px;text-align:center;}}
.natura-cell svg{{width:15px;height:15px;}}
tfoot tr{{border-top:2px solid #d1d5db;background:#f8f9fa;}}
tfoot td{{vertical-align:middle;white-space:nowrap;border-right:1px solid #e6e9ef;}}
tfoot td:first-child{{padding:9px 6px;text-align:center;border-right:1px solid #e6e9ef;}}
tfoot td:last-child{{border-right:none;}}
.num{{text-align:right;font-variant-numeric:tabular-nums;}}
{_MODAL_CSS}
</style></head>
<body>
<div class="tw">
<table id="ptf-table">
<thead><tr>
  <th data-col="0"></th>
  <th data-col="1">Ticker<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="2">Strumento<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="3">Tipo<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="4"></th>
  <th data-col="5">Quote<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="6">Prezzo<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="7">PMC<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="8">Controvalore<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="9">Costo<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="10">Comm.<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="11">P/L €<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="12">P/L %<span class="sort-ind"></span><span class="rh"></span></th>
</tr></thead>
<tbody id="ptf-body">{rows_html}</tbody>
{tfoot_html}
</table>
</div>
{_MODAL_HTML}
<script>
{_MODAL_JS}
var _sCol=-1,_sAsc=true;
function sortTable(col){{
  if(col===0||col===4)return;
  var tbody=document.getElementById('ptf-body');
  var rows=Array.from(tbody.querySelectorAll('tr'));
  var asc=(_sCol===col)?!_sAsc:true;_sCol=col;_sAsc=asc;
  rows.sort(function(a,b){{
    var av=a.children[col].getAttribute('data-sort')||'';
    var bv=b.children[col].getAttribute('data-sort')||'';
    var an=parseFloat(av),bn=parseFloat(bv);
    if(!isNaN(an)&&!isNaN(bn))return asc?an-bn:bn-an;
    return asc?av.localeCompare(bv,'it'):bv.localeCompare(av,'it');
  }});
  rows.forEach(function(r){{tbody.appendChild(r);}});
  document.querySelectorAll('thead th').forEach(function(th,i){{
    th.classList.remove('asc','desc');
    if(i===col)th.classList.add(asc?'asc':'desc');
  }});
}}
document.querySelectorAll('thead th[data-col]').forEach(function(th){{
  th.addEventListener('click',function(e){{
    if(e.target.classList.contains('rh'))return;
    sortTable(parseInt(th.getAttribute('data-col')));
  }});
}});
(function(){{
  var rz=null,sx,sw;
  document.querySelectorAll('.rh').forEach(function(h){{
    h.addEventListener('mousedown',function(e){{
      e.stopPropagation();e.preventDefault();
      rz=h.parentElement;sx=e.clientX;sw=rz.offsetWidth;
      document.addEventListener('mousemove',mv);document.addEventListener('mouseup',up);
    }});
  }});
  function mv(e){{if(!rz)return;rz.style.width=Math.max(36,sw+(e.clientX-sx))+'px';}}
  function up(){{rz=null;document.removeEventListener('mousemove',mv);document.removeEventListener('mouseup',up);}}
}})();
function sendH(){{
  var t=document.getElementById('ptf-table');
  if(!t)return;
  var h=Math.ceil(t.getBoundingClientRect().height)+2;
  var py=0; try{{py=window.parent.scrollY||window.parent.pageYOffset||0;}}catch(e){{}}
  window.parent.postMessage({{type:'streamlit:setFrameHeight',height:h}},'*');
  [10,60,200].forEach(function(d){{setTimeout(function(){{try{{window.parent.scrollTo({{top:py,behavior:'instant'}});}}catch(e){{}}}} ,d);}});
}}
sendH();
requestAnimationFrame(sendH);
setTimeout(sendH,150);
setTimeout(sendH,600);
</script>
</body></html>"""
    html_content = html_content.replace("__TICKER_JSON__", ticker_json)
    render_html_iframe(html_content, height=iframe_h, scrolling=False)


def render_weekly_pl_table(result, da, data):
    """Render the per-instrument weekly P/L table (Ticker/Strumento/Tipo/Quote + daily deltas + Totale).

    Chiamato da: ui/pages/home.py, sezione "Andamento dell'ultima settimana".
    Stesso popup di dettaglio ticker della tabella Controvalore (via _build_ticker_info/_MODAL_*).
    """
    if not result or not result.get("rows"):
        return
    days = result["days"]
    week_gap_before = result.get("week_gap_before") or [False] * len(days)
    rows = result["rows"]
    day_totals = result["day_totals"]
    grand_total = result["grand_total"]
    n_days = len(days)

    ticker_info = _build_ticker_info(da, data) if da is not None and data is not None else {}
    info_map = {s["ticker"]: s for s in (data or {}).get("strumenti", [])}

    def _cat_col(tipo):
        cat = macro_cat(tipo)
        return CATEGORY_COLORS.get(cat, macro_color(cat))

    def _fmt_num(v, dec=2):
        try:
            f = float(v)
            s = f"{f:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
            return s
        except Exception:
            return "n/d"

    def _fmt_eur(v, dec=2, signed=False):
        try:
            f = float(v)
            s = _fmt_num(f, dec)
            if signed and f > 0:
                return f"+{s} €"
            return f"{s} €"
        except Exception:
            return "n/d"

    def _fmt_day(v):
        if v is None:
            return "—"
        try:
            f = float(v)
        except Exception:
            return "—"
        s = _fmt_num(abs(f), 2)
        if f > 0:
            return f"+{s}"
        if f < 0:
            return f"-{s}"
        return s

    def _sort_val(v):
        if v is None:
            return "-999999999"
        try:
            return str(round(float(v), 6))
        except Exception:
            return "-999999999"

    day_extrema = []
    for i in range(n_days):
        vals = [r["deltas"][i] for r in rows if r["deltas"][i] is not None]
        day_extrema.append((max(vals), min(vals)) if vals else (None, None))

    day_ths = "".join(
        f'<th data-col="{5 + i}"'
        + (' style="border-left:2px solid #d1d5db;"' if week_gap_before[i] else '')
        + f'>{d}<span class="sort-ind"></span><span class="rh"></span></th>\n'
        for i, d in enumerate(days)
    )
    arrow_col_idx = 5 + n_days
    total_col = arrow_col_idx + 1

    rows_html = ""
    for row in rows:
        tk = row["ticker"]
        col = _cat_col(row["tipo"])
        tipo_code = macro_cat(row["tipo"])
        natura_label = str(info_map.get(tk, {}).get("natura") or "Esposizione diversificata")
        natura_color, natura_svg = get_natura_visual(natura_label)
        cells = ""
        for i, v in enumerate(row["deltas"]):
            cell_col = "#1E8449" if (v is not None and v >= 0) else ("#FF4B4B" if v is not None else "#9CA3AF")
            day_max, day_min = day_extrema[i]
            is_extreme = v is not None and (v == day_max or v == day_min)
            weight = "700" if is_extreme else "400"
            gap_style = "border-left:2px solid #d1d5db;" if week_gap_before[i] else ""
            cells += f'<td class="num" data-sort="{_sort_val(v)}" style="color:{cell_col};font-weight:{weight};{gap_style}">{_fmt_day(v)}</td>\n'
        totale = row["totale"]
        tot_col = "#1E8449" if totale >= 0 else "#FF4B4B"
        arrow_char = "↗" if totale >= 0 else "↘"
        strumento = str(row["strumento"])
        rows_html += (
            '<tr>\n'
            f'<td data-sort="{tk}"><a class="tk-link" style="color:{col}" href="#" onclick="showModal(\'{tk}\');return false;">{tk}</a></td>\n'
            f'<td data-sort="{strumento}" style="color:{col};max-width:130px;" title="{strumento}">{strumento[:24]}</td>\n'
            f'<td data-sort="{tipo_code}" style="color:{col};">{tipo_code}</td>\n'
            f'<td class="natura-cell" title="{natura_label}" style="color:{natura_color};width:20px;text-align:center;">{natura_svg}</td>\n'
            f'<td class="num" data-sort="{_sort_val(row["quote"])}">{_fmt_num(row["quote"], 3)}</td>\n'
            f'{cells}'
            f'<td style="color:{tot_col};font-weight:800;text-align:center;width:26px;">{arrow_char}</td>\n'
            f'<td class="num" data-sort="{_sort_val(totale)}" style="color:{tot_col};font-weight:700;">{_fmt_eur(totale, 2, signed=True)}</td>\n'
            '</tr>'
        )

    total_cells = ""
    for i, v in enumerate(day_totals):
        cell_col = "#1E8449" if v >= 0 else "#FF4B4B"
        gap_style = "border-left:2px solid #d1d5db;" if week_gap_before[i] else ""
        total_cells += f'<td class="num" style="color:{cell_col};font-weight:700;padding:9px 12px;{gap_style}">{_fmt_day(v)}</td>\n'
    grand_col = "#1E8449" if grand_total >= 0 else "#FF4B4B"
    tfoot_html = (
        '<tfoot><tr>'
        '<td colspan="5" style="font-weight:800;font-size:0.85rem;letter-spacing:.02em;padding:9px 12px;">TOTALE</td>'
        f'{total_cells}'
        '<td></td>'
        f'<td class="num" style="color:{grand_col};font-weight:800;padding:9px 12px;">{_fmt_eur(grand_total, 2, signed=True)}</td>'
        '</tr></tfoot>'
    )

    ticker_json = json.dumps(ticker_info, ensure_ascii=False)
    n_rows = len(rows)
    iframe_h = iframe_height_for_rows(
        n_rows, row_height=35, header_height=48, padding=50, min_height=160, max_height=1100, content_until_rows=18
    )
    html_content = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box;margin:0;padding:0;}}
html,body{{background:transparent;font-family:"Source Sans Pro",system-ui,-apple-system,sans-serif;font-size:14px;overflow:hidden;color:#262730;}}
.tw{{border:1px solid #e6e9ef;border-radius:8px;overflow:hidden;background:#fff;width:100%;}}
table{{width:100%;border-collapse:collapse;table-layout:auto;}}
thead th{{
  background:#f0f2f6;font-size:12px;font-weight:600;letter-spacing:.01em;
  color:#262730;padding:9px 12px;border-bottom:1px solid #e6e9ef;border-right:1px solid #e6e9ef;
  text-align:right;white-space:nowrap;position:relative;user-select:none;cursor:pointer;
}}
thead th:last-child{{border-right:none;}}
thead th:nth-child(1),thead th:nth-child(2),thead th:nth-child(3){{text-align:left;}}
thead th:hover{{background:#e3e6e9;}}
thead th .sort-ind{{font-size:9px;margin-left:3px;color:#9094a3;}}
thead th.asc .sort-ind::after{{content:'▲';color:#262730;}}
thead th.desc .sort-ind::after{{content:'▼';color:#262730;}}
.rh{{position:absolute;right:0;top:0;height:100%;width:4px;cursor:col-resize;background:transparent;z-index:1;}}
.rh:hover{{background:#9094a3;opacity:.4;}}
tbody tr{{border-bottom:1px solid #f0f2f6;}}
tbody tr:last-child{{border-bottom:none;}}
tbody tr:hover{{background:#f0f2f6;}}
tbody td{{padding:9px 12px;vertical-align:middle;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;border-right:1px solid #f0f2f6;}}
tbody td:last-child{{border-right:none;}}
.natura-cell svg{{width:15px;height:15px;}}
tfoot tr{{border-top:2px solid #d1d5db;background:#f8f9fa;}}
tfoot td{{vertical-align:middle;white-space:nowrap;border-right:1px solid #e6e9ef;}}
tfoot td:last-child{{border-right:none;}}
.num{{text-align:right;font-variant-numeric:tabular-nums;}}
{_MODAL_CSS}
</style></head>
<body>
<div class="tw">
<table id="wpl-table">
<thead><tr>
  <th data-col="0">Ticker<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="1">Strumento<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="2">Tipo<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="3" style="text-align:center;width:20px;cursor:default;"></th>
  <th data-col="4">Quote<span class="sort-ind"></span><span class="rh"></span></th>
  {day_ths}
  <th data-col="{arrow_col_idx}" style="text-align:center;width:26px;cursor:default;"></th>
  <th data-col="{total_col}">P/L totale<span class="sort-ind"></span><span class="rh"></span></th>
</tr></thead>
<tbody id="wpl-body">{rows_html}</tbody>
{tfoot_html}
</table>
</div>
{_MODAL_HTML}
<script>
{_MODAL_JS}
var _sCol=-1,_sAsc=true;
var _naturaCol=3;
var _arrowCol={arrow_col_idx};
function sortTable(col){{
  if(col===_naturaCol||col===_arrowCol)return;
  var tbody=document.getElementById('wpl-body');
  var rows=Array.from(tbody.querySelectorAll('tr'));
  var asc=(_sCol===col)?!_sAsc:true;_sCol=col;_sAsc=asc;
  rows.sort(function(a,b){{
    var av=a.children[col].getAttribute('data-sort')||'';
    var bv=b.children[col].getAttribute('data-sort')||'';
    var an=parseFloat(av),bn=parseFloat(bv);
    if(!isNaN(an)&&!isNaN(bn))return asc?an-bn:bn-an;
    return asc?av.localeCompare(bv,'it'):bv.localeCompare(av,'it');
  }});
  rows.forEach(function(r){{tbody.appendChild(r);}});
  document.querySelectorAll('thead th').forEach(function(th,i){{
    th.classList.remove('asc','desc');
    if(i===col)th.classList.add(asc?'asc':'desc');
  }});
}}
document.querySelectorAll('thead th[data-col]').forEach(function(th){{
  th.addEventListener('click',function(e){{
    if(e.target.classList.contains('rh'))return;
    sortTable(parseInt(th.getAttribute('data-col')));
  }});
}});
(function(){{
  var rz=null,sx,sw;
  document.querySelectorAll('.rh').forEach(function(h){{
    h.addEventListener('mousedown',function(e){{
      e.stopPropagation();e.preventDefault();
      rz=h.parentElement;sx=e.clientX;sw=rz.offsetWidth;
      document.addEventListener('mousemove',mv);document.addEventListener('mouseup',up);
    }});
  }});
  function mv(e){{if(!rz)return;rz.style.width=Math.max(36,sw+(e.clientX-sx))+'px';}}
  function up(){{rz=null;document.removeEventListener('mousemove',mv);document.removeEventListener('mouseup',up);}}
}})();
function sendH(){{
  var t=document.getElementById('wpl-table');
  if(!t)return;
  var h=Math.ceil(t.getBoundingClientRect().height)+2;
  var py=0; try{{py=window.parent.scrollY||window.parent.pageYOffset||0;}}catch(e){{}}
  window.parent.postMessage({{type:'streamlit:setFrameHeight',height:h}},'*');
  [10,60,200].forEach(function(d){{setTimeout(function(){{try{{window.parent.scrollTo({{top:py,behavior:'instant'}});}}catch(e){{}}}} ,d);}});
}}
sendH();
requestAnimationFrame(sendH);
setTimeout(sendH,150);
setTimeout(sendH,600);
</script>
</body></html>"""
    html_content = html_content.replace("__TICKER_JSON__", ticker_json)
    render_html_iframe(html_content, height=iframe_h, scrolling=False)
