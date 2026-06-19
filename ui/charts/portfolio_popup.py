from __future__ import annotations

import json

import pandas as pd
from persistence.storage import macro_cat
from ui.streamlit_compat import iframe_height_for_rows, iframe_scroll_for_rows, render_html_iframe
from ui.theme import CATEGORY_COLORS, macro_color

# Modulo shared HTML/popup.
# Ruolo:
# - render tabella portafoglio arricchita con popup dettagli strumento
# - usato come supporto UI trasversale, non associato a un chart_id Plotly

def render_portfolio_table_with_popup(df, data, direction_map=None):
    """Render the portfolio table with inline popup details for each ticker.

    Chiamato da: flussi UI del portafoglio/home che mostrano la tabella holdings.
    Nota: non passa da apply_settings perche' non e' un grafico Plotly ma un blocco HTML.
    """
    if df is None or df.empty:
        return
    direction_map = direction_map or {}
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
    cat_color_map = CATEGORY_COLORS

    def _cat_col(tipo):
        cat = macro_cat(tipo)
        return cat_color_map.get(cat, macro_color(cat))

    def _trend_sym(tk):
        state = direction_map.get(str(tk or ""), "flat")
        if state == "up":
            return ("▲", "#1E8449")
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
        f'<tfoot><tr><td></td><td colspan="6" style="font-weight:800;font-size:0.85rem;letter-spacing:.02em;padding:9px 12px;">TOTALE</td>'
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
thead th:nth-child(1){{text-align:center;width:26px;cursor:default;padding:9px 6px;}}
thead th:nth-child(2),thead th:nth-child(3),thead th:nth-child(4){{text-align:left;}}
thead th:hover:not(:nth-child(1)){{background:#e3e6e9;}}
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
tbody td:nth-child(1){{padding:9px 6px;text-align:center;}}
tfoot tr{{border-top:2px solid #d1d5db;background:#f8f9fa;}}
tfoot td{{vertical-align:middle;white-space:nowrap;border-right:1px solid #e6e9ef;}}
tfoot td:first-child{{padding:9px 6px;text-align:center;border-right:1px solid #e6e9ef;}}
tfoot td:last-child{{border-right:none;}}
.num{{text-align:right;font-variant-numeric:tabular-nums;}}
a.tk-link{{text-decoration:none;font-weight:700;cursor:pointer;border-bottom:1.5px dotted;transition:opacity .15s;}}
a.tk-link:hover{{opacity:0.65;}}
#mo{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;align-items:center;justify-content:center;}}
#mo.on{{display:flex;}}
#mc{{background:#fff;border-radius:18px;padding:20px 24px 18px;max-width:900px;width:97%;max-height:90vh;overflow-y:auto;box-shadow:0 12px 52px rgba(0,0,0,.26);position:relative;color:#1f2937;}}
#mc-close{{position:absolute;top:10px;right:14px;cursor:pointer;font-size:1.3rem;color:#9ca3af;background:none;border:none;line-height:1;}}
#mc-close:hover{{color:#374151;}}
.mc-cols{{display:grid;grid-template-columns:40% 60%;gap:18px;align-items:start;}}
.mc-left{{min-width:0;}}
.mc-right{{min-width:0;display:flex;flex-direction:column;gap:8px;}}
.mc-ticker{{font-size:1.8rem;font-weight:900;letter-spacing:-.01em;margin-bottom:2px;}}
.mc-nome{{font-size:1.0rem;color:#374151;font-weight:600;}}
.mc-meta{{font-size:0.85rem;color:#9ca3af;margin:4px 0 12px;}}
.mc-grid{{display:grid;grid-template-columns:1fr 1fr;gap:5px;}}
.mc-kpi{{border:1px solid #e5e7eb;border-radius:8px;padding:8px 12px;}}
.mc-kpi-l{{font-size:0.82rem;text-transform:uppercase;color:#9ca3af;font-weight:700;letter-spacing:.04em;margin-bottom:3px;}}
.mc-kpi-v{{font-size:1.15rem;font-weight:700;font-variant-numeric:tabular-nums;}}
.pos{{color:#1E8449;}} .neg{{color:#FF4B4B;}}
.mc-price-box{{background:#f9fafb;border:1px solid #e5e7eb;border-radius:11px;padding:10px 14px;display:flex;align-items:baseline;gap:12px;}}
.mc-price-val{{font-size:2.0rem;font-weight:800;font-variant-numeric:tabular-nums;}}
.mc-price-sub{{font-size:0.95rem;color:#6b7280;}}
.mc-spark-label{{font-size:0.78rem;text-transform:uppercase;color:#9ca3af;font-weight:700;letter-spacing:.05em;}}
svg.spark{{width:100%;height:140px;display:block;border-radius:10px;background:#f9fafb;}}
.mc-footer{{font-size:0.78rem;color:#9ca3af;}}
</style></head>
<body>
<div class="tw">
<table id="ptf-table">
<thead><tr>
  <th data-col="0"></th>
  <th data-col="1">Ticker<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="2">Strumento<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="3">Tipo<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="4">Quote<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="5">Prezzo<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="6">PMC<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="7">Controvalore<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="8">Costo<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="9">Comm.<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="10">P/L €<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="11">P/L %<span class="sort-ind"></span><span class="rh"></span></th>
</tr></thead>
<tbody id="ptf-body">{rows_html}</tbody>
{tfoot_html}
</table>
</div>
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
<script>
var D=__TICKER_JSON__;
function fi(v,d,sgn){{
  if(v==null||isNaN(v))return'n/d';
  var n=parseFloat(v).toLocaleString('it-IT',{{minimumFractionDigits:d,maximumFractionDigits:d}});
  return (sgn&&v>0?'+':'')+n;
}}
function fe(v,d,sgn){{return fi(v,d!=null?d:2,sgn)+' €';}}
function fp(v,d,sgn){{
  if(v==null||isNaN(v))return'n/d';
  var pct=parseFloat(v)*100;
  var n=pct.toLocaleString('it-IT',{{minimumFractionDigits:d!=null?d:1,maximumFractionDigits:d!=null?d:1}});
  return(sgn&&pct>0?'+':'')+n+'%';
}}
function kpi(label,val,cls){{
  return '<div class="mc-kpi"><div class="mc-kpi-l">'+label+'</div><div class="mc-kpi-v'+(cls?' '+cls:'')+'">'+val+'</div></div>';
}}
function sparkline(data,plPositive,pmc){{
  var svg=document.getElementById('m-spark');
  svg.innerHTML='';
  var W=520,H=140,pad=6;
  if(!data||data.length<2){{
    var t=document.createElementNS('http://www.w3.org/2000/svg','text');
    t.setAttribute('x','50%');t.setAttribute('y','52%');t.setAttribute('text-anchor','middle');
    t.setAttribute('fill','#d1d5db');t.setAttribute('font-size','10');t.setAttribute('font-family','system-ui');
    t.textContent='Dati storici non disponibili';svg.appendChild(t);return;
  }}
  var vals=data.map(function(p){{return p.v;}});
  var mn=Math.min.apply(null,vals),mx=Math.max.apply(null,vals);if(pmc!=null&&!isNaN(pmc)){{mn=Math.min(mn,pmc);mx=Math.max(mx,pmc);}}var rng=mx-mn||0.001;var toY=function(v){{return H-pad-((v-mn)/rng*(H-pad*2));}};
  var pts=[];
  vals.forEach(function(v,i){{
    var x=pad+(i/(vals.length-1))*(W-pad*2);
    var y=toY(v);
    pts.push(x.toFixed(1)+','+y.toFixed(1));
  }});
  var col=plPositive?'#1E8449':'#FF4B4B';
  var fill=plPositive?'rgba(30,132,73,0.12)':'rgba(255,75,75,0.12)';
  var lx=parseFloat(pts[vals.length-1].split(',')[0]),ly=parseFloat(pts[vals.length-1].split(',')[1]);var pmcY=(pmc!=null&&!isNaN(pmc))?toY(pmc):null;
  var area=document.createElementNS('http://www.w3.org/2000/svg','polygon');
  area.setAttribute('points',pts[0].split(',')[0]+','+(H-pad)+' '+pts.join(' ')+' '+lx+','+(H-pad));
  area.setAttribute('fill',fill);svg.appendChild(area);if(pmcY!=null){{var pmcLine=document.createElementNS('http://www.w3.org/2000/svg','line');pmcLine.setAttribute('x1',pad);pmcLine.setAttribute('x2',W-pad);pmcLine.setAttribute('y1',pmcY);pmcLine.setAttribute('y2',pmcY);pmcLine.setAttribute('stroke','#6b7280');pmcLine.setAttribute('stroke-width','1.8');pmcLine.setAttribute('stroke-dasharray','7 5');pmcLine.setAttribute('opacity','0.98');svg.appendChild(pmcLine);var pmcText=document.createElementNS('http://www.w3.org/2000/svg','text');pmcText.setAttribute('x',W-pad-4);pmcText.setAttribute('y',Math.max(12,pmcY-4));pmcText.setAttribute('text-anchor','end');pmcText.setAttribute('fill','#4b5563');pmcText.setAttribute('font-size','10');pmcText.setAttribute('font-family','system-ui');pmcText.textContent='PMC';svg.appendChild(pmcText);}}
  var line=document.createElementNS('http://www.w3.org/2000/svg','polyline');
  line.setAttribute('points',pts.join(' '));
  line.setAttribute('fill','none');line.setAttribute('stroke',col);line.setAttribute('stroke-width','2');
  svg.appendChild(line);
  var dot=document.createElementNS('http://www.w3.org/2000/svg','circle');
  dot.setAttribute('cx',lx);dot.setAttribute('cy',ly);dot.setAttribute('r','4');
  dot.setAttribute('fill',col);dot.setAttribute('stroke','#fff');dot.setAttribute('stroke-width','1.5');
  svg.appendChild(dot);
}}
function showModal(tk){{
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
    kpi('Fonte / Agg.',d.fonte+' · '+d.aggiornato);
  sparkline(d.spark,d.pl_e>=0,d.pmc);
  document.getElementById('m-footer').textContent='Quotazione aggiornata al '+d.aggiornato+' · Fonte: '+d.fonte;
  document.getElementById('mo').classList.add('on');
}}
function closeM(){{document.getElementById('mo').classList.remove('on');}}
document.addEventListener('keydown',function(e){{if(e.key==='Escape')closeM();}});
var _sCol=-1,_sAsc=true;
function sortTable(col){{
  if(col===0)return;
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
  window.parent.postMessage({{type:'streamlit:setFrameHeight',height:h}},'*');
}}
sendH();
requestAnimationFrame(sendH);
setTimeout(sendH,150);
setTimeout(sendH,600);
</script>
</body></html>"""
    html_content = html_content.replace("__TICKER_JSON__", ticker_json)
    render_html_iframe(html_content, height=iframe_h, scrolling=False)


def render_quotes_table_with_popup(qdf, data, quotes_log):
    """Render the quotes diagnostics table with an inline popup on ticker click.

    The popup reuses the same visual language of the portfolio popup and shows:
    - current diagnostic snapshot
    - dashed PMC line when available
    - last 15 logged readings chart
    - last 15 logged readings table
    """
    if qdf is None or qdf.empty:
        return

    quotes_log = quotes_log or {}
    info_map = {s.get("ticker", ""): s for s in data.get("strumenti", [])}
    holdings_df = build_ptf_df(data)
    holdings_map = {}
    if isinstance(holdings_df, pd.DataFrame) and not holdings_df.empty and "Ticker" in holdings_df.columns:
        holdings_map = {str(row.get("Ticker", "")): row for _, row in holdings_df.iterrows()}
    cat_map = {s.get("ticker", ""): s.get("tipo", "") for s in data.get("strumenti", [])}

    def _cat_col(ticker):
        tipo = str(cat_map.get(str(ticker or ""), "") or "").lower()
        if "btp" in tipo or "titolo" in tipo:
            return CATEGORY_COLORS["GOV"]
        if "etf" in tipo:
            return CATEGORY_COLORS["ETF"]
        return CATEGORY_COLORS["FND"]

    def _fmt_num(v, dec=2):
        try:
            f = float(v)
            return f"{f:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
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

    def _fmt_pct(v, dec=2, signed=False):
        try:
            f = float(v) * 100
            s = _fmt_num(abs(f), dec)
            sign = "+" if signed and f > 0 else "-" if f < 0 else ""
            return f"{sign}{s}%"
        except Exception:
            return "n/d"

    def _sort_num(v):
        try:
            return str(round(float(v or 0.0), 8))
        except Exception:
            return "0"

    log_items = quotes_log.get("items", []) or []
    logs_by_ticker = {}
    for item in log_items:
        ticker = str(item.get("ticker") or "").strip()
        if not ticker:
            continue
        logs_by_ticker.setdefault(ticker, []).append(item)

    popup_payload = {}
    rows_html = ""
    for _, row in qdf.iterrows():
        ticker = str(row.get("Ticker") or "")
        info = info_map.get(ticker, {})
        holding = holdings_map.get(ticker, {})
        name = str(row.get("Strumento") or info.get("nome") or ticker)
        tipo = str(row.get("Tipologia") or info.get("tipo") or "")
        color = _cat_col(ticker)
        prezzo = row.get("Prezzo letto")
        prezzo_prec = row.get("Prezzo precedente")
        delta = row.get("Var. vs prec.")
        fonte = str(row.get("Fonte") or "")
        esito = str(row.get("Esito") or "")
        fallback = str(row.get("Fallback") or "")
        try:
            delta_val = float(delta) if delta is not None else 0.0
        except Exception:
            delta_val = 0.0
        if delta_val > 0:
            sym, sym_col, sym_sort = "▲", "#1E8449", "1"
        elif delta_val < 0:
            sym, sym_col, sym_sort = "▼", "#FF4B4B", "3"
        else:
            sym, sym_col, sym_sort = "—", "#9CA3AF", "2"
        esito_label = "🟢 OK" if esito == "OK" else "🟡 Warning" if ("WARNING" in esito or fallback == "Sì") else "🔴 Errore"
        esito_col = "#1E8449" if "OK" in esito_label else "#F59E0B" if "Warning" in esito_label else "#FF4B4B"
        rows_html += (
            f'<tr>'
            f'<td data-sort="{sym_sort}" style="text-align:center;padding:9px 6px;color:{sym_col};font-weight:800;">{sym}</td>'
            f'<td data-sort="{ticker}"><a class="tk-link" style="color:{color}" href="#" onclick="showQuoteModal(\'{ticker}\');return false;">{ticker}</a></td>'
            f'<td data-sort="{name}" style="color:{color};max-width:146px;" title="{name}">{name[:26]}</td>'
            f'<td data-sort="{tipo}" style="color:{color};font-weight:700;max-width:88px;" title="{tipo}">{tipo}</td>'
            f'<td class="num" data-sort="{_sort_num(prezzo)}">{_fmt_num(prezzo, 3)}</td>'
            f'<td class="num" data-sort="{_sort_num(prezzo_prec)}">{_fmt_num(prezzo_prec, 3)}</td>'
            f'<td class="num" data-sort="{_sort_num(delta_val)}" style="color:{sym_col};font-weight:700;">{_fmt_pct(delta, 2, signed=True)}</td>'
            f'<td data-sort="{fonte}">{fonte}</td>'
            f'<td data-sort="{esito_label}" style="color:{esito_col};font-weight:700;">{esito_label}</td>'
            f'</tr>'
        )

        ticker_logs = sorted(logs_by_ticker.get(ticker, []), key=lambda item: str(item.get("timestamp") or ""))[-15:]
        readings = []
        for item in ticker_logs:
            price = item.get("price")
            prev = item.get("previous_price")
            try:
                var_pct = float(item.get("delta_pct")) if item.get("delta_pct") is not None else None
            except Exception:
                var_pct = None
            try:
                price_num = float(price) if price is not None else None
            except Exception:
                price_num = None
            readings.append(
                {
                    "ts": str(item.get("timestamp") or ""),
                    "date": str(item.get("price_date") or ""),
                    "hist_date": str(item.get("latest_history_date") or ""),
                    "price": price_num,
                    "prev": prev,
                    "var_pct": var_pct,
                    "status": str(item.get("status") or ""),
                    "fallback": bool(item.get("fallback_used")),
                    "source": str(item.get("source") or ""),
                    "warning": str(item.get("warning") or ""),
                }
            )
        try:
            pmc = float(holding.get("PMC", 0) or 0)
        except Exception:
            pmc = 0.0
        try:
            qty = float(holding.get("Quote", 0) or 0)
        except Exception:
            qty = 0.0
        try:
            ctv = float(holding.get("Controvalore", 0) or 0)
        except Exception:
            ctv = 0.0
        try:
            cost = float(holding.get("Costo", 0) or 0)
        except Exception:
            cost = 0.0
        try:
            pl_e = float(holding.get("P/L €", 0) or 0)
        except Exception:
            pl_e = 0.0
        try:
            pl_p = float(holding.get("P/L %", 0) or 0)
        except Exception:
            pl_p = 0.0
        popup_payload[ticker] = {
            "nome": info.get("nome", name),
            "isin": info.get("isin", "n/d"),
            "tipo": info.get("tipo", tipo),
            "fonte": fonte or info.get("fonte", "n/d"),
            "aggiornato": info.get("aggiornato", "n/d"),
            "prezzo": prezzo,
            "prezzo_prec": prezzo_prec,
            "pmc": pmc if pmc > 0 else None,
            "qty": qty,
            "ctv": ctv,
            "costo": cost,
            "pl_e": pl_e,
            "pl_p": pl_p,
            "readings": readings,
        }

    payload_json = json.dumps(popup_payload, ensure_ascii=False)
    n_rows = len(qdf)
    iframe_h = iframe_height_for_rows(
        n_rows, row_height=39, header_height=44, padding=0, min_height=180, max_height=760, content_until_rows=14
    )
    scrolling = iframe_scroll_for_rows(n_rows, threshold=17)
    html_content = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box;margin:0;padding:0;}}
html,body{{background:transparent;font-family:"Source Sans Pro",system-ui,-apple-system,sans-serif;font-size:14px;overflow:hidden;color:#262730;}}
.tw{{border:1px solid #e6e9ef;border-radius:8px;overflow:hidden;background:#fff;width:100%;}}
table{{width:100%;border-collapse:collapse;table-layout:auto;}}
thead th{{background:#f0f2f6;font-size:12px;font-weight:600;letter-spacing:.01em;color:#262730;padding:9px 12px;border-bottom:1px solid #e6e9ef;border-right:1px solid #e6e9ef;text-align:right;white-space:nowrap;position:relative;user-select:none;cursor:pointer;}}
thead th:last-child{{border-right:none;}}
thead th:nth-child(1){{text-align:center;width:26px;cursor:default;padding:9px 6px;}}
thead th:nth-child(2),thead th:nth-child(3),thead th:nth-child(4),thead th:nth-child(8),thead th:nth-child(9){{text-align:left;}}
thead th:hover:not(:nth-child(1)){{background:#e3e6e9;}}
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
.num{{text-align:right;font-variant-numeric:tabular-nums;}}
a.tk-link{{text-decoration:none;font-weight:700;cursor:pointer;border-bottom:1.5px dotted;transition:opacity .15s;}}
a.tk-link:hover{{opacity:0.65;}}
#qmo{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;align-items:center;justify-content:center;}}
#qmo.on{{display:flex;}}
#qmc{{background:#fff;border-radius:18px;padding:20px 24px 18px;max-width:1020px;width:97%;max-height:92vh;overflow-y:auto;box-shadow:0 12px 52px rgba(0,0,0,.26);position:relative;color:#1f2937;}}
#qmc-close{{position:absolute;top:10px;right:14px;cursor:pointer;font-size:1.3rem;color:#9ca3af;background:none;border:none;line-height:1;}}
#qmc-close:hover{{color:#374151;}}
.mc-cols{{display:grid;grid-template-columns:36% 64%;gap:18px;align-items:start;}}
.mc-left{{min-width:0;}}
.mc-right{{min-width:0;display:flex;flex-direction:column;gap:10px;}}
.mc-ticker{{font-size:1.8rem;font-weight:900;letter-spacing:-.01em;margin-bottom:2px;}}
.mc-nome{{font-size:1.0rem;color:#374151;font-weight:600;}}
.mc-meta{{font-size:0.85rem;color:#9ca3af;margin:4px 0 12px;}}
.mc-grid{{display:grid;grid-template-columns:1fr 1fr;gap:5px;}}
.mc-kpi{{border:1px solid #e5e7eb;border-radius:8px;padding:8px 12px;}}
.mc-kpi-l{{font-size:0.82rem;text-transform:uppercase;color:#9ca3af;font-weight:700;letter-spacing:.04em;margin-bottom:3px;}}
.mc-kpi-v{{font-size:1.05rem;font-weight:700;font-variant-numeric:tabular-nums;}}
.pos{{color:#1E8449;}} .neg{{color:#FF4B4B;}}
.mc-price-box{{background:#f9fafb;border:1px solid #e5e7eb;border-radius:11px;padding:10px 14px;display:flex;align-items:baseline;gap:12px;}}
.mc-price-val{{font-size:2.0rem;font-weight:800;font-variant-numeric:tabular-nums;}}
.mc-price-sub{{font-size:0.95rem;color:#6b7280;}}
.mc-spark-label{{font-size:0.78rem;text-transform:uppercase;color:#9ca3af;font-weight:700;letter-spacing:.05em;}}
svg.spark{{width:100%;height:180px;display:block;border-radius:10px;background:#f9fafb;}}
.read-table{{border:1px solid #e5e7eb;border-radius:10px;overflow:hidden;background:#fff;}}
.read-table table{{width:100%;border-collapse:collapse;table-layout:fixed;}}
.read-table th,.read-table td{{padding:7px 9px;border-bottom:1px solid #eef0f4;font-size:12px;}}
.read-table th{{background:#f8fafc;text-align:left;color:#64748b;font-weight:700;}}
.read-table td.num{{text-align:right;font-variant-numeric:tabular-nums;}}
.read-table tr:last-child td{{border-bottom:none;}}
.tag-ok{{color:#1E8449;font-weight:700;}}
.tag-warn{{color:#F59E0B;font-weight:700;}}
.tag-err{{color:#FF4B4B;font-weight:700;}}
.mc-footer{{font-size:0.78rem;color:#9ca3af;}}
</style></head>
<body>
<div class="tw"><table id="quotes-table">
<thead><tr>
  <th data-col="0"></th>
  <th data-col="1">Ticker<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="2">Strumento<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="3">Tipologia<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="4">Prezzo letto<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="5">Prezzo prec.<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="6">Var.%<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="7">Fonte<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="8">Esito<span class="sort-ind"></span><span class="rh"></span></th>
</tr></thead>
<tbody id="quotes-body">__ROWS_HTML__</tbody>
</table></div>
<div id="qmo" onclick="if(event.target===this)closeQuoteModal()">
<div id="qmc">
  <button id="qmc-close" onclick="closeQuoteModal()">&#x2715;</button>
  <div class="mc-cols">
    <div class="mc-left">
      <div class="mc-ticker" id="qm-tk"></div>
      <div class="mc-nome" id="qm-nm"></div>
      <div class="mc-meta" id="qm-meta"></div>
      <div class="mc-grid" id="qm-grid"></div>
    </div>
    <div class="mc-right">
      <div class="mc-price-box">
        <div>
          <div style="font-size:0.78rem;text-transform:uppercase;color:#9ca3af;font-weight:700;margin-bottom:2px;">Ultimo prezzo letto</div>
          <div class="mc-price-val" id="qm-px"></div>
        </div>
        <div id="qm-delta" class="mc-price-sub"></div>
      </div>
      <div class="mc-spark-label">Ultime 15 letture disponibili</div>
      <svg class="spark" id="qm-spark" viewBox="0 0 620 180" preserveAspectRatio="none"></svg>
      <div class="read-table">
        <table>
          <thead><tr><th>Timestamp</th><th class="num">Prezzo</th><th class="num">Var.%</th><th>Esito</th><th>Data prezzo</th></tr></thead>
          <tbody id="qm-readings"></tbody>
        </table>
      </div>
      <div class="mc-footer" id="qm-footer"></div>
    </div>
  </div>
</div>
</div>
<script>
var QD=__QUOTES_JSON__;
function fi(v,d,sgn){if(v==null||isNaN(v))return'n/d';var n=parseFloat(v).toLocaleString('it-IT',{minimumFractionDigits:d,maximumFractionDigits:d});return (sgn&&v>0?'+':'')+n;}
function fe(v,d,sgn){return fi(v,d!=null?d:2,sgn)+' €';}
function fp(v,d,sgn){if(v==null||isNaN(v))return'n/d';var pct=parseFloat(v)*100;var n=Math.abs(pct).toLocaleString('it-IT',{minimumFractionDigits:d!=null?d:2,maximumFractionDigits:d!=null?d:2});return (sgn&&pct>0?'+':pct<0?'-':'')+n+'%';}
function fmtTs(v){if(!v)return 'n/d';return String(v).replace('T',' ');}
function kpi(label,val,cls){return '<div class="mc-kpi"><div class="mc-kpi-l">'+label+'</div><div class="mc-kpi-v'+(cls?' '+cls:'')+'">'+val+'</div></div>';}
function buildReadingsTable(readings){
  var body=document.getElementById('qm-readings');
  body.innerHTML='';
  if(!readings||!readings.length){
    body.innerHTML='<tr><td colspan="5" style="color:#94a3b8;">Nessuna lettura disponibile</td></tr>';
    return;
  }
  var ordered=readings.slice().reverse();
  ordered.forEach(function(r){
    var cls=r.status==='ok'?'tag-ok':(r.status==='warning'?'tag-warn':'tag-err');
    var label=r.status==='ok'?'OK':(r.status==='warning'?'Warning':'Errore');
    var tr=document.createElement('tr');
    tr.innerHTML='<td>'+fmtTs(r.ts)+'</td>'
      +'<td class="num">'+(r.price==null?'n/d':fi(r.price,3,false))+'</td>'
      +'<td class="num">'+(r.var_pct==null?'n/d':fp(r.var_pct,2,true))+'</td>'
      +'<td class="'+cls+'">'+label+(r.fallback?' · fallback':'')+'</td>'
      +'<td>'+(r.date||r.hist_date||'n/d')+'</td>';
    body.appendChild(tr);
  });
}
function sparklineReadings(readings, isPositive, pmc){
  var svg=document.getElementById('qm-spark');
  svg.innerHTML='';
  var W=620,H=180,padX=26,padY=18;
  var usable=(readings||[]).filter(function(r){return r.price!=null&&!isNaN(r.price);});
  if(usable.length<2){
    var t=document.createElementNS('http://www.w3.org/2000/svg','text');
    t.setAttribute('x','50%');t.setAttribute('y','52%');t.setAttribute('text-anchor','middle');
    t.setAttribute('fill','#cbd5e1');t.setAttribute('font-size','11');t.textContent='Storico letture insufficiente';
    svg.appendChild(t);return;
  }
  var vals=usable.map(function(p){return parseFloat(p.price);});
  var mn=Math.min.apply(null,vals),mx=Math.max.apply(null,vals);
  if(pmc!=null&&!isNaN(pmc)){mn=Math.min(mn,pmc);mx=Math.max(mx,pmc);}
  var rng=(mx-mn)||0.001;
  var toY=function(v){return H-padY-((v-mn)/rng*(H-padY*2));};
  var pts=[];
  usable.forEach(function(v,i){
    var x=padX+(i/(usable.length-1))*(W-padX*2);
    var y=toY(parseFloat(v.price));
    pts.push({x:x,y:y,raw:v});
  });
  var col=isPositive?'#1E8449':'#FF4B4B';
  var fill=isPositive?'rgba(30,132,73,0.12)':'rgba(255,75,75,0.12)';
  var area=document.createElementNS('http://www.w3.org/2000/svg','polygon');
  area.setAttribute('points',pts[0].x+','+(H-padY)+' '+pts.map(function(p){return p.x.toFixed(1)+','+p.y.toFixed(1);}).join(' ')+' '+pts[pts.length-1].x+','+(H-padY));
  area.setAttribute('fill',fill);svg.appendChild(area);
  if(pmc!=null&&!isNaN(pmc)){
    var py=toY(pmc);
    var lineP=document.createElementNS('http://www.w3.org/2000/svg','line');
    lineP.setAttribute('x1',padX);lineP.setAttribute('x2',W-padX);lineP.setAttribute('y1',py);lineP.setAttribute('y2',py);
    lineP.setAttribute('stroke','#6b7280');lineP.setAttribute('stroke-width','1.8');lineP.setAttribute('stroke-dasharray','7 5');
    svg.appendChild(lineP);
    var tx=document.createElementNS('http://www.w3.org/2000/svg','text');
    tx.setAttribute('x',W-padX-4);tx.setAttribute('y',Math.max(12,py-4));tx.setAttribute('text-anchor','end');
    tx.setAttribute('fill','#4b5563');tx.setAttribute('font-size','10');tx.textContent='PMC';
    svg.appendChild(tx);
  }
  for(var g=0;g<3;g++){
    var gy=padY+g*((H-padY*2)/2);
    var gl=document.createElementNS('http://www.w3.org/2000/svg','line');
    gl.setAttribute('x1',padX);gl.setAttribute('x2',W-padX);gl.setAttribute('y1',gy);gl.setAttribute('y2',gy);
    gl.setAttribute('stroke','#e5e7eb');gl.setAttribute('stroke-width','1');
    svg.appendChild(gl);
  }
  var poly=document.createElementNS('http://www.w3.org/2000/svg','polyline');
  poly.setAttribute('points',pts.map(function(p){return p.x.toFixed(1)+','+p.y.toFixed(1);}).join(' '));
  poly.setAttribute('fill','none');poly.setAttribute('stroke',col);poly.setAttribute('stroke-width','2.4');
  svg.appendChild(poly);
  pts.forEach(function(p,idx){
    var c=document.createElementNS('http://www.w3.org/2000/svg','circle');
    c.setAttribute('cx',p.x);c.setAttribute('cy',p.y);c.setAttribute('r',idx===pts.length-1?4:3);
    c.setAttribute('fill',p.raw.fallback?'#ffffff':col);
    c.setAttribute('stroke',p.raw.fallback?'#F59E0B':col);
    c.setAttribute('stroke-width',p.raw.fallback?'2':'1.4');
    svg.appendChild(c);
  });
  var first=usable[0], last=usable[usable.length-1];
  [['start',padX,first.ts],['end',W-padX,last.ts]].forEach(function(entry){
    var t=document.createElementNS('http://www.w3.org/2000/svg','text');
    t.setAttribute('x',entry[1]);t.setAttribute('y',H-4);t.setAttribute('text-anchor',entry[0]==='start'?'start':'end');
    t.setAttribute('fill','#94a3b8');t.setAttribute('font-size','10');t.textContent=fmtTs(entry[2]).slice(0,10);
    svg.appendChild(t);
  });
}
function showQuoteModal(tk){
  var d=QD[tk]; if(!d)return;
  var px=(d.prezzo!=null&&!isNaN(d.prezzo))?parseFloat(d.prezzo):null;
  var pmc=(d.pmc!=null&&!isNaN(d.pmc))?parseFloat(d.pmc):null;
  var prev=(d.prezzo_prec!=null&&!isNaN(d.prezzo_prec))?parseFloat(d.prezzo_prec):null;
  var latestReading=(d.readings&&d.readings.length)?d.readings[d.readings.length-1]:null;
  var refDelta=(pmc&&pmc>0&&px!=null)?((px/pmc)-1):((prev&&prev!==0&&px!=null)?((px/prev)-1):0);
  var positive=refDelta>=0;
  var cls=positive?'pos':'neg';
  document.getElementById('qm-tk').textContent=tk;
  document.getElementById('qm-tk').style.color=positive?'#1E8449':'#374151';
  document.getElementById('qm-nm').textContent=d.nome||tk;
  document.getElementById('qm-meta').textContent='ISIN: '+(d.isin||'n/d')+' · '+(d.tipo||'n/d');
  document.getElementById('qm-px').textContent=px==null?'n/d':fe(px,3,false);
  document.getElementById('qm-px').className='mc-price-val '+cls;
  document.getElementById('qm-delta').innerHTML=(pmc&&pmc>0&&px!=null)?('<span class="'+cls+'">'+fp((px/pmc)-1,2,true)+' vs PMC</span>'):((prev&&px!=null)?('<span class="'+cls+'">'+fp((px/prev)-1,2,true)+' vs precedente</span>'):'');
  document.getElementById('qm-grid').innerHTML=
    kpi('PMC',pmc&&pmc>0?fe(pmc,3,false):'n/d')+
    kpi('Quantità',d.qty?fi(d.qty,3,false):'0,000')+
    kpi('Controvalore',fe(d.ctv||0,2,false))+
    kpi('Costo storico',fe(d.costo||0,2,false))+
    kpi('P/L €',fe(d.pl_e||0,2,true),(d.pl_e||0)>=0?'pos':'neg')+
    kpi('P/L %',fp(d.pl_p||0,2,true),(d.pl_p||0)>=0?'pos':'neg')+
    kpi('Letture log',String((d.readings||[]).length))+
    kpi('Fonte / Agg.',(d.fonte||'n/d')+' · '+(d.aggiornato||'n/d'));
  sparklineReadings(d.readings||[], positive, pmc);
  buildReadingsTable(d.readings||[]);
  var foot='Ultime letture mostrate: '+String((d.readings||[]).length)+' · ';
  if(latestReading){foot+='ultimo timestamp '+fmtTs(latestReading.ts); if(latestReading.warning){foot+=' · '+latestReading.warning;}}
  document.getElementById('qm-footer').textContent=foot;
  document.getElementById('qmo').classList.add('on');
}
function closeQuoteModal(){document.getElementById('qmo').classList.remove('on');}
document.addEventListener('keydown',function(e){if(e.key==='Escape')closeQuoteModal();});
var _sc=-1,_sa=true;
function sortQ(ci){
  if(ci===0)return;
  if(_sc===ci)_sa=!_sa; else{_sc=ci;_sa=true;}
  document.querySelectorAll('#quotes-table thead th').forEach(function(t){t.classList.remove('asc','desc');});
  var th=document.querySelector('#quotes-table thead th[data-col="'+ci+'"]'); if(th)th.classList.add(_sa?'asc':'desc');
  var tb=document.getElementById('quotes-body');
  var rows=Array.from(tb.querySelectorAll('tr'));
  rows.sort(function(a,b){
    var av=a.cells[ci]?a.cells[ci].getAttribute('data-sort')||'':'';
    var bv=b.cells[ci]?b.cells[ci].getAttribute('data-sort')||'':'';
    var an=parseFloat(av), bn=parseFloat(bv);
    if(!isNaN(an)&&!isNaN(bn)) return _sa?an-bn:bn-an;
    return _sa?av.localeCompare(bv,'it'):bv.localeCompare(av,'it');
  });
  rows.forEach(function(r){tb.appendChild(r);});
}
document.querySelectorAll('#quotes-table thead th[data-col]').forEach(function(th){
  var ci=parseInt(th.getAttribute('data-col')); if(ci===0)return;
  th.addEventListener('click',function(){sortQ(ci);});
});
(function(){
  var rz=null,sx,sw;
  document.querySelectorAll('#quotes-table .rh').forEach(function(h){
    h.addEventListener('mousedown',function(e){
      e.stopPropagation();e.preventDefault();
      rz=h.parentElement;sx=e.clientX;sw=rz.offsetWidth;
      document.addEventListener('mousemove',mv);document.addEventListener('mouseup',up);
    });
  });
  function mv(e){if(!rz)return;rz.style.width=Math.max(36,sw+(e.clientX-sx))+'px';}
  function up(){rz=null;document.removeEventListener('mousemove',mv);document.removeEventListener('mouseup',up);}
})();
function sendH(){
  var t=document.getElementById('quotes-table');
  if(!t)return;
  var h=Math.ceil(t.getBoundingClientRect().height)+2;
  window.parent.postMessage({type:'streamlit:setFrameHeight',height:h},'*');
}
sendH();requestAnimationFrame(sendH);setTimeout(sendH,150);setTimeout(sendH,600);
</script>
</body></html>"""
    html_content = html_content.replace("__ROWS_HTML__", rows_html)
    html_content = html_content.replace("{{", "{").replace("}}", "}")
    html_content = html_content.replace("__QUOTES_JSON__", payload_json.replace("</", "<\\/"))
    render_html_iframe(html_content, height=iframe_h, scrolling=scrolling)
