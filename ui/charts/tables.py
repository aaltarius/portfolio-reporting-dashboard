from __future__ import annotations

import math
import pandas as pd
import streamlit as st

from persistence.storage import _normalize_macro_label, macro_cat as _macro_cat
from ui.components import render_styled_table
from ui.formatting import fmt_eur_it, fmt_pct_it, fmt_qty_it
from ui.streamlit_compat import iframe_height_for_rows, iframe_scroll_for_rows, render_html_iframe
from ui.theme import CATEGORY_COLORS, P, macro_color

def color_pl(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    if v > 0:
        return f"color:{P['green']};font-weight:600;"
    if v < 0:
        return f"color:{P['red']};font-weight:600;"
    return f"color:{P['muted']};"


def color_trend_indicator(value):
    txt = str(value or "").strip()
    if txt == "▲":
        return f"color:{P['green']};font-weight:800;"
    if txt == "▼":
        return f"color:{P['red']};font-weight:800;"
    if txt == "—":
        return f"color:{P['muted']};font-weight:700;"
    return ""


def style_macro_cols(row):
    cat = _normalize_macro_label(row.get("Tipo", row.get("Tipologia", "")))
    color = macro_color(cat)
    styles = []
    for col in row.index:
        if col in {"Ticker", "Tipo", "Tipologia", "Descrizione"}:
            styles.append(f"color:{color};font-weight:700;")
        else:
            styles.append("")
    return styles


def small_pie_texts(values, threshold=0.06):
    vals = [float(v) if pd.notna(v) else 0.0 for v in values]
    total = sum(vals)
    if total <= 0:
        return ["" for _ in vals]
    out = []
    for v in vals:
        share = v / total
        out.append(fmt_pct_it(share, 1) if share >= threshold else "")
    return out


def render_diagnostica_table_html(qdf, data):
    if qdf is None or qdf.empty:
        return
    _cat_map = {s.get("ticker", ""): _macro_cat(s.get("tipo", "")) for s in data.get("strumenti", [])}

    def _col(tk):
        cat = _cat_map.get(str(tk or ""), "")
        return CATEGORY_COLORS.get(cat, "#374151")

    def _trend(v):
        try:
            f = float(v)
            if f > 0:
                return ("▲", "#1E8449", "1")
            if f < 0:
                return ("▼", "#FF4B4B", "3")
        except (TypeError, ValueError):
            pass
        return ("—", "#9CA3AF", "2")

    def _fnum(v, dec=3):
        try:
            f = float(v)
            return f"{f:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            return "n/d"

    def _fpct(v, dec=2):
        try:
            f = float(v) * 100
            if math.isnan(f) or math.isinf(f):
                return "n/d"
            s = f"{abs(f):,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
            return ("+" if f > 0 else "-" if f < 0 else "") + s + "%"
        except Exception:
            return "n/d"

    def _esito(status, fallback):
        if fallback == "Sì":
            return "🟡 Warning"
        if status == "OK":
            return "🟢 OK"
        if status == "WARNING":
            return "🟡 Warning"
        return "🔴 Errore"

    rows_html = ""
    for _, row in qdf.iterrows():
        tk = str(row.get("Ticker") or "")
        nome = str(row.get("Strumento") or tk)
        tipo = str(row.get("Tipologia") or _cat_map.get(tk, "") or "")
        col = _col(tk)
        delta = row.get("Var. vs prec.")
        sym, sym_col, sym_sort = _trend(delta)
        p_letto = row.get("Prezzo letto")
        p_prec = row.get("Prezzo precedente")
        fonte = str(row.get("Fonte") or "")
        esito = _esito(str(row.get("Esito") or ""), str(row.get("Fallback") or ""))
        try:
            var_f = float(delta) if delta is not None else 0.0
        except Exception:
            var_f = 0.0
        var_col = "#1E8449" if var_f > 0 else "#FF4B4B" if var_f < 0 else "#9CA3AF"
        esito_col = "#1E8449" if "OK" in esito else "#F59E0B" if "Warning" in esito else "#FF4B4B"
        rows_html += (
            f'<tr><td data-sort="{sym_sort}" style="text-align:center;padding:9px 6px;color:{sym_col};font-weight:800;">{sym}</td>'
            f'<td data-sort="{tk}" style="color:{col};font-weight:700;">{tk}</td>'
            f'<td data-sort="{nome}" style="color:{col};max-width:136px;" title="{nome}">{nome[:24]}</td>'
            f'<td data-sort="{tipo}" style="color:{col};font-weight:700;max-width:88px;" title="{tipo}">{tipo}</td>'
            f'<td class="num" data-sort="{(p_letto if p_letto is not None else 0)}">{_fnum(p_letto)}</td>'
            f'<td class="num" data-sort="{(p_prec if p_prec is not None else 0)}">{_fnum(p_prec)}</td>'
            f'<td class="num" data-sort="{var_f}" style="color:{var_col};font-weight:700;">{_fpct(delta)}</td>'
            f'<td data-sort="{fonte}">{fonte}</td>'
            f'<td data-sort="{esito}" style="color:{esito_col};font-weight:700;">{esito}</td></tr>'
        )
    n_rows = len(qdf)

    # Altezza iframe diagnostica: proporzionata alle righe, ma con limite massimo
    # per evitare grandi spazi bianchi nella pagina. Oltre il limite si usa lo scroll interno.
    row_h = 39
    header_h = 42
    padding_h = 6
    iframe_h = iframe_height_for_rows(
        n_rows, row_height=row_h, header_height=header_h, padding=padding_h, min_height=160, max_height=720, content_until_rows=14
    )
    iframe_scrolling = iframe_scroll_for_rows(n_rows, threshold=17)
    html_content = f"""<!DOCTYPE html>
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
thead th:nth-child(2){{width:90px;}}
thead th:nth-child(3){{width:142px;}}
thead th:nth-child(4){{width:88px;}}
thead th:nth-child(5),thead th:nth-child(6),thead th:nth-child(7){{width:102px;}}
thead th:nth-child(8){{width:92px;}}
thead th:nth-child(9){{width:94px;}}
tbody tr{{border-bottom:1px solid #f0f2f6;}}
tbody tr:last-child{{border-bottom:none;}}
tbody tr:hover{{background:#f0f2f6;}}
tbody td{{padding:9px 12px;vertical-align:middle;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;border-right:1px solid #f0f2f6;}}
tbody td:last-child{{border-right:none;}}
.num{{text-align:right;font-variant-numeric:tabular-nums;}}
</style></head>
<body><div class="tw"><table id="diag-table">
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
<tbody id="diag-body">{rows_html}</tbody>
</table></div>
<script>
var _sc=-1,_sa=true;
function sortD(ci){{
  if(_sc===ci)_sa=!_sa; else{{_sc=ci;_sa=true;}}
  document.querySelectorAll('#diag-table thead th').forEach(function(t){{t.classList.remove('asc','desc');}});
  var th=document.querySelector('#diag-table thead th[data-col="'+ci+'"]');
  if(th)th.classList.add(_sa?'asc':'desc');
  var tb=document.querySelector('#diag-table tbody');
  var rows=Array.from(tb.querySelectorAll('tr'));
  rows.sort(function(a,b){{
    var av=a.cells[ci]?a.cells[ci].getAttribute('data-sort')||'':'';
    var bv=b.cells[ci]?b.cells[ci].getAttribute('data-sort')||'':'';
    var an=parseFloat(av),bn=parseFloat(bv);
    if(!isNaN(an)&&!isNaN(bn))return _sa?an-bn:bn-an;
    return _sa?av.localeCompare(bv,'it'):bv.localeCompare(av,'it');
  }});
  rows.forEach(function(r){{tb.appendChild(r);}});
}}
document.querySelectorAll('#diag-table thead th[data-col]').forEach(function(th){{
  var ci=parseInt(th.getAttribute('data-col'));
  if(ci===0)return;
  th.addEventListener('click',function(){{sortD(ci);}});
}});
(function(){{
  var rz=null,sx,sw;
  document.querySelectorAll('#diag-table .rh').forEach(function(h){{
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
  var t=document.getElementById('diag-table');
  if(!t)return;
  var h=Math.ceil(t.getBoundingClientRect().height)+2;
  window.parent.postMessage({{type:'streamlit:setFrameHeight',height:h}},'*');
}}
sendH();requestAnimationFrame(sendH);setTimeout(sendH,150);setTimeout(sendH,600);
</script>
</body></html>"""
    render_html_iframe(html_content, height=iframe_h, scrolling=iframe_scrolling)


def render_portfolio_table_html(df, direction_map=None):
    if df is None or df.empty:
        return
    direction_map = direction_map or {}
    work = df[["Ticker", "Strumento", "Tipo", "Quote", "Prezzo", "PMC", "Controvalore", "Costo", "Comm.", "P/L €", "P/L %"]].copy()

    def _trend_symbol(ticker):
        state = direction_map.get(str(ticker or ""), "flat")
        if state == "up":
            return "▲"
        if state == "down":
            return "▼"
        return "—"

    work.insert(0, "+/-", work["Ticker"].map(_trend_symbol))

    def _style_row(row):
        cat = _normalize_macro_label(row.get("Tipo", ""))
        cat_col = macro_color(cat)
        out = []
        for col in row.index:
            style = ""
            if col == "+/-":
                sym = str(row.get(col, "—"))
                if sym == "▲":
                    style = f"color:{P['green']};font-weight:800;text-align:center;"
                elif sym == "▼":
                    style = f"color:{P['red']};font-weight:800;text-align:center;"
                else:
                    style = f"color:{P['muted']};font-weight:700;text-align:center;"
            elif col in {"Ticker", "Strumento", "Tipo"}:
                style = f"color:{cat_col};font-weight:700;"
            elif col in {"P/L €", "P/L %"}:
                try:
                    v = float(row.get(col, 0) or 0)
                except Exception:
                    v = 0.0
                if v > 0:
                    style = f"color:{P['green']};font-weight:700;"
                elif v < 0:
                    style = f"color:{P['red']};font-weight:700;"
                else:
                    style = f"color:{P['muted']};font-weight:600;"
            out.append(style)
        return out

    styled = (
        work.style.format(
            {
                "Quote": lambda v: fmt_qty_it(v, 3),
                "Prezzo": lambda v: fmt_eur_it(v, 2),
                "PMC": lambda v: fmt_eur_it(v, 2),
                "Controvalore": lambda v: fmt_eur_it(v, 2),
                "Costo": lambda v: fmt_eur_it(v, 2),
                "Comm.": lambda v: fmt_eur_it(v, 2),
                "P/L €": lambda v: fmt_eur_it(v, 2, signed=True),
                "P/L %": lambda v: fmt_pct_it(v, 2, signed=True),
            }
        )
        .apply(_style_row, axis=1)
        .set_properties(subset=["+/-"], **{"text-align": "center"})
        .set_properties(
            subset=["Quote", "Prezzo", "PMC", "Controvalore", "Costo", "Comm.", "P/L €", "P/L %"],
            **{"text-align": "right"},
        )
        .set_table_styles(
            [
                {"selector": "th.col0", "props": [("text-align", "center")]},
                {"selector": "td.col0", "props": [("text-align", "center")]},
                {
                    "selector": "th.col4,th.col5,th.col6,th.col7,th.col8,th.col9,th.col10,th.col11",
                    "props": [("text-align", "right")],
                },
                {
                    "selector": "td.col4,td.col5,td.col6,td.col7,td.col8,td.col9,td.col10,td.col11",
                    "props": [("text-align", "right")],
                },
            ],
            overwrite=False,
        )
    )
    render_styled_table(
        styled,
        column_config={
            "+/-": st.column_config.TextColumn("+/-", width=26),
            "Ticker": st.column_config.TextColumn("Ticker", width="small"),
            "Strumento": st.column_config.TextColumn("Strumento", width=190),
            "Tipo": st.column_config.TextColumn("Tipo", width=125),
            "Quote": st.column_config.NumberColumn("Quote", width="small"),
        },
    )
