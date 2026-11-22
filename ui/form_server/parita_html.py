"""ui/form_server/parita_html.py — pagina HTML «A parità di investimento» (PA-01).

Solo presentazione: nessun calcolo finanziario (sta in core/services/parita_investimento.py). Ordinamenti, filtri
e dettagli di riga girano nel browser con un piccolo JavaScript, senza ricaricare la pagina. Ogni testo dinamico
passa da `html.escape`.
"""
from __future__ import annotations

from html import escape

from ui.form_server.parita_charts import paths_figure, pl_bars_figure
from ui.form_server.shell import CSS
from ui.form_server.theme import FORM_COLORS

_POS, _NEG = FORM_COLORS["emerald-600"], FORM_COLORS["red-600"]


def mini_bar_html(ret: float, max_abs: float) -> str:
    """Barra proporzionale (max 90 px) per la cella del rendimento."""
    width = 0 if not max_abs else min(abs(ret) / max_abs, 1.0) * 90
    return f'<span class="pp-mini" style="width:{width:.0f}px;background:{_POS if ret >= 0 else _NEG}"></span>'

_DIST_WARNING = "distribuisce: proventi non inclusi, rendimento sottostimato"


def _e(value) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def _short(name: str, limit: int = 26) -> str:
    return name if len(name) <= limit else name[: limit - 1].rstrip() + "…"


def _eur(value: float, *, sign: bool = False) -> str:
    s = f"{abs(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    prefix = ("+" if value > 0 else "−" if value < 0 else "") if sign else ("−" if value < 0 else "")
    return f"{prefix}{s} €"


def _pct(value: float, *, sign: bool = True) -> str:
    s = f"{abs(value) * 100:.2f}".replace(".", ",")
    prefix = ("+" if value > 0 else "−" if value < 0 else "") if sign else ("−" if value < 0 else "")
    return f"{prefix}{s}%"


def _pp(value: float) -> str:
    s = f"{abs(value):.2f}".replace(".", ",")
    return f"{'+' if value > 0 else '−' if value < 0 else ''}{s} pp"


def _cls(value: float | None) -> str:
    if value is None or value == 0:
        return ""
    return "pp-pos" if value > 0 else "pp-neg"


_VERDICT_CLS = {
    "in controtendenza positiva": "pp-v-pos", "meglio del riferimento": "pp-v-pos",
    "ha limitato la perdita": "pp-v-mid", "parità": "pp-v-nd", "inferiore": "pp-v-neg",
    "dato insufficiente": "pp-v-nd", "riferimento": "pp-v-ref",
}

_STYLE = f"""<style>
.pp{{max-width:1380px;margin:0 auto}}
.pp-card{{background:var(--white);border-radius:14px;padding:18px 22px;box-shadow:0 2px 12px var(--black-a06);margin-bottom:14px}}
.pp-form{{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end}}
.pp-form .f{{display:flex;flex-direction:column;min-width:150px}}
.pp-form label{{font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--slate-500);margin-bottom:3px}}
.pp-form input,.pp-form select{{padding:7px 9px;border:1px solid var(--slate-300);border-radius:8px;font-size:.9rem;width:100%}}
.pp-btn{{background:var(--indigo-600);color:var(--white);border:0;border-radius:8px;padding:9px 22px;font-weight:700;cursor:pointer}}
.pp-origin{{font-size:.82rem;color:var(--slate-600);margin-top:8px}}
.pp-err{{background:var(--red-50);border:1px solid var(--red-300);color:var(--red-700);border-radius:10px;padding:10px 14px;margin-bottom:14px}}
.pp-cov{{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin-bottom:10px;font-size:.88rem}}
.pp-pill{{display:inline-block;border-radius:99px;padding:2px 10px;font-size:.72rem;font-weight:700;white-space:nowrap}}
.pp-v-pos{{background:var(--green-100);color:var(--green-800)}}
.pp-v-mid{{background:var(--amber-50);color:var(--amber-800)}}
.pp-v-neg{{background:var(--red-50);color:var(--red-700)}}
.pp-v-nd{{background:var(--slate-100);color:var(--slate-500)}}
.pp-v-ref{{background:var(--indigo-50);color:var(--indigo-700)}}
table.pp-t{{width:100%;border-collapse:collapse;font-size:.85rem}}
table.pp-t th,table.pp-t td{{white-space:nowrap}}
table.pp-t th{{text-align:right;font-size:.68rem;text-transform:uppercase;color:var(--slate-500);padding:6px 8px;border-bottom:2px solid var(--slate-200);cursor:pointer;white-space:nowrap;user-select:none}}
table.pp-t th:first-child,table.pp-t td:first-child{{text-align:left}}
table.pp-t td{{text-align:right;padding:6px 8px;border-bottom:1px solid var(--slate-100)}}
table.pp-t tr.pp-row{{cursor:pointer}}
table.pp-t tr.pp-row:hover{{background:var(--slate-hover)}}
table.pp-t tr[data-ref="1"]{{background:var(--indigo-50);font-weight:700}}
table.pp-t tr.pp-det td{{text-align:left;background:var(--slate-50);font-size:.8rem;color:var(--slate-600)}}
table.pp-t tr.pp-det{{display:none}}
table.pp-t tr.pp-det.open{{display:table-row}}
.pp-pos{{color:var(--emerald-600)}}.pp-neg{{color:var(--red-600)}}
.pp-mini{{display:inline-block;height:8px;border-radius:4px;vertical-align:middle;margin-right:6px}}
.pp-filters{{display:flex;gap:16px;flex-wrap:wrap;margin:8px 0 10px;font-size:.84rem}}
.pp-empty{{padding:18px;text-align:center;color:var(--slate-500);background:var(--slate-50);border-radius:8px}}
.pp-judg{{background:var(--indigo-50);border-left:4px solid var(--indigo-600);border-radius:8px;padding:14px 18px}}
.pp-j-ref{{font-size:.98rem;margin-bottom:12px;line-height:1.5}}
.pp-j-row{{display:flex;gap:12px;align-items:flex-start;padding:8px 0;border-top:1px solid var(--indigo-200)}}
.pp-j-row .pp-pill{{flex:0 0 190px;text-align:center;font-size:.78rem}}
.pp-chips{{display:flex;flex-wrap:wrap;gap:6px}}
.pp-chip{{background:var(--white);border:1px solid var(--slate-300);border-radius:6px;padding:2px 8px;font-size:.78rem;font-weight:600;color:var(--slate-700)}}
.pp-plot{{width:100%}}
.pp-excl li{{margin:3px 0;font-size:.84rem;color:var(--amber-800)}}
.pp-warn{{color:var(--amber-800)}}
h2.pp-h{{margin:0 0 8px}}
</style>"""

_PLOT_JS = """<script src="/assets/plotly.min.js"></script>
<script>
document.querySelectorAll('.pp-plot').forEach(function(el){
  var src=document.getElementById(el.id+'-json'); if(!src||!window.Plotly) return;
  var f=JSON.parse(src.textContent);
  Plotly.newPlot(el.id,f.data,f.layout,{responsive:true,displaylogo:false,modeBarButtonsToRemove:['lasso2d','select2d']});
});
</script>"""

_JS = """<script>
(function(){
  var tb=document.getElementById('pp-body'); if(!tb) return;
  function pairs(){var r=[];tb.querySelectorAll('tr.pp-row').forEach(function(x){r.push([x,x.nextElementSibling]);});return r;}
  tb.addEventListener('click',function(e){var tr=e.target.closest('tr.pp-row'); if(tr&&tr.nextElementSibling) tr.nextElementSibling.classList.toggle('open');});
  document.querySelectorAll('table.pp-t th[data-c]').forEach(function(th){
    th.addEventListener('click',function(){
      var c=+th.dataset.c, asc=th.dataset.o!=='asc'; th.dataset.o=asc?'asc':'desc';
      document.querySelectorAll('table.pp-t th').forEach(function(o){o.textContent=o.textContent.replace(/ [▲▼]$/,'');});
      th.textContent+=asc?' ▲':' ▼';
      var p=pairs(); p.sort(function(a,b){
        var x=a[0].children[c].dataset.v, y=b[0].children[c].dataset.v, nx=parseFloat(x), ny=parseFloat(y);
        var r=(isNaN(nx)||isNaN(ny))?String(x).localeCompare(String(y)):nx-ny; return asc?r:-r;});
      p.forEach(function(q){tb.appendChild(q[0]);tb.appendChild(q[1]);});
    });
  });
  function applyFilters(){
    var held=document.getElementById('f-held').checked, obs=document.getElementById('f-obs').checked,
        gain=document.getElementById('f-gain').checked, better=document.getElementById('f-better').checked;
    pairs().forEach(function(q){var r=q[0], ok=true;
      if(r.dataset.ref!=='1'){
        var st=r.dataset.status;
        if(st==='posseduto'&&!held) ok=false;
        if((st==='osservato'||st==='chiuso')&&!obs) ok=false;
        if(gain&&!(parseFloat(r.dataset.pl)>0)) ok=false;
        if(better&&!(parseFloat(r.dataset.adv)>0)) ok=false;
      }
      r.style.display=ok?'':'none'; if(!ok) q[1].classList.remove('open'); q[1].style.display=ok?'':'none';});
  }
  ['f-held','f-obs','f-gain','f-better'].forEach(function(id){document.getElementById(id).addEventListener('change',applyFilters);});
})();
function ppMode(){var m=document.getElementById('pp-mode').value;
  document.getElementById('pp-amount-f').style.display=m==='libero'?'':'none';
  document.getElementById('pp-cap-f').style.display=m==='libero'?'none':'';}
document.addEventListener('DOMContentLoaded',ppMode);
</script>"""


def _form(instruments, form, resolved) -> str:
    def opt(items, selected):
        return "".join(f'<option value="{_e(v)}"{" selected" if v == selected else ""}>{_e(lbl)}</option>'
                       for v, lbl in items)

    mode = form.get("mode", "libero")
    modes = [("libero", "Importo libero"), ("speso", "Quanto ho speso su uno strumento"),
             ("controvalore", "Controvalore a inizio periodo")]
    instr_opts = [("", "—")] + [(t, f"{t} · {n}") for t, n in instruments]
    ref_opts = [(t, f"{t} · {n}") for t, n in instruments]
    units = form.get("units", "whole")
    origin = ""
    if resolved is not None and resolved.usable:
        origin = f'<div class="pp-origin">Capitale: <b>{_e(resolved.origin)}</b>'
        if resolved.carry_cost is not None:
            origin += (f'<br>Nel dettaglio, costo di carico delle quote ancora possedute: '
                       f'<b>{_e(_eur(resolved.carry_cost))}</b>')
        origin += "</div>"
    return (
        '<form method="post" action="/parita" class="pp-card"><div class="pp-form">'
        f'<div class="f"><label>Dal</label><input type="date" name="start" value="{_e(form.get("start", ""))}" required></div>'
        f'<div class="f"><label>Al</label><input type="date" name="end" value="{_e(form.get("end", ""))}" required></div>'
        f'<div class="f"><label>Capitale</label><select name="mode" id="pp-mode" onchange="ppMode()">{opt(modes, mode)}</select></div>'
        f'<div class="f" id="pp-amount-f"><label>Importo (€)</label><input type="number" step="0.01" min="0" name="amount" value="{_e(form.get("amount", "1000"))}"></div>'
        f'<div class="f" id="pp-cap-f"><label>Strumento del capitale</label><select name="cap_ticker">{opt(instr_opts, form.get("cap_ticker", ""))}</select></div>'
        f'<div class="f"><label>Riferimento</label><select name="reference">{opt(ref_opts, form.get("reference", ""))}</select></div>'
        f'<div class="f"><label>Modalità</label><select name="units">{opt([("whole", "Quote acquistabili"), ("theory", "Capitale interamente investito")], units)}</select></div>'
        '<div class="f"><button class="pp-btn" type="submit">Confronta</button></div></div>'
        f'{origin}</form>')


def _judgment(result) -> str:
    rows = result.rows
    if not rows:
        return '<div class="pp-judg">Nessuno strumento confrontabile nel periodo.</div>'
    if not result.reference_ok:
        return ('<div class="pp-judg">Il riferimento non ha prezzi utilizzabili alle due date: '
                'la graduatoria relativa non è disponibile.</div>')
    ref = next(r for r in rows if r.is_reference)
    verb = "perde" if ref.pl < 0 else "guadagna"
    out = [f'<div class="pp-judg"><div class="pp-j-ref">Il riferimento <b>{_e(ref.ticker)}</b> ({_e(ref.name)}) '
           f'{verb} <b>{_e(_eur(abs(ref.pl)))}</b> ({_e(_pct(ref.ret))}) su {_e(_eur(result.capital))}.</div>']
    groups = [("in controtendenza positiva", "In controtendenza positiva", "pp-v-pos"),
              ("meglio del riferimento", "Meglio del riferimento", "pp-v-pos"),
              ("ha limitato la perdita", "Ha limitato la perdita", "pp-v-mid"),
              ("parità", "In parità", "pp-v-nd"), ("inferiore", "Peggio del riferimento", "pp-v-neg")]
    for key, label, cls in groups:
        members = [r for r in rows if r.verdict == key]
        if not members:
            continue
        chips = "".join(f'<span class="pp-chip" title="{_e(r.name)}">{_e(r.ticker)}</span>' for r in members)
        out.append(f'<div class="pp-j-row"><span class="pp-pill {cls}">{label} · {len(members)}</span>'
                   f'<div class="pp-chips">{chips}</div></div>')
    out.append("</div>")
    return "".join(out)


def _table(result) -> str:
    rows = result.rows
    max_abs = max((abs(r.ret) for r in rows), default=0.0)
    heads = ["Strumento", "Stato", "Rendimento", "P/L €", "Valore finale", "Vs rif. €", "Vs rif. pp", "Giudizio", "Data finale"]
    out = ['<table class="pp-t"><thead><tr>' + "".join(f'<th data-c="{i}">{h}</th>' for i, h in enumerate(heads))
           + '</tr></thead><tbody id="pp-body">']
    for r in rows:
        adv = "" if r.adv_eur is None else _eur(r.adv_eur, sign=True)
        advp = "" if r.adv_pp is None else _pp(r.adv_pp)
        star = "★ " if r.is_reference else ""
        dist = f' <span class="pp-warn" title="{_e(_DIST_WARNING)}">ⓘ</span>' if r.distributes else ""
        out.append(
            f'<tr class="pp-row" data-ref="{1 if r.is_reference else 0}" data-status="{_e(r.status)}" '
            f'data-pl="{r.pl:.4f}" data-adv="{"" if r.adv_eur is None else f"{r.adv_eur:.4f}"}">'
            f'<td data-v="{_e(r.name)}" title="{_e(r.name)}">{star}{_e(_short(r.name))}{dist}<br><small style="color:var(--slate-500)">{_e(r.ticker)}</small></td>'
            f'<td data-v="{_e(r.status)}">{_e(r.status)}</td>'
            f'<td data-v="{r.ret:.6f}" style="text-align:left">{mini_bar_html(r.ret, max_abs)}'
            f'<span class="{_cls(r.ret)}">{_e(_pct(r.ret))}</span></td>'
            f'<td data-v="{r.pl:.4f}" class="{_cls(r.pl)}">{_e(_eur(r.pl, sign=True))}</td>'
            f'<td data-v="{r.final_value:.4f}">{_e(_eur(r.final_value))}</td>'
            f'<td data-v="{"" if r.adv_eur is None else f"{r.adv_eur:.4f}"}" class="{_cls(r.adv_eur)}">{_e(adv)}</td>'
            f'<td data-v="{"" if r.adv_pp is None else f"{r.adv_pp:.4f}"}" class="{_cls(r.adv_pp)}">{_e(advp)}</td>'
            f'<td data-v="{_e(r.verdict)}"><span class="pp-pill {_VERDICT_CLS.get(r.verdict, "pp-v-nd")}">{_e(r.verdict)}</span></td>'
            f'<td data-v="{_e(r.end_date)}">{_e(r.end_date)}</td></tr>')
        warn = f'<br><span class="pp-warn">⚠ {_e(_DIST_WARNING)}</span>' if r.distributes else ""
        out.append(
            f'<tr class="pp-det"><td colspan="9">Date effettive: {_e(r.start_date)} → {_e(r.end_date)} · '
            f'prezzi {_e(f"{r.start_price:,.4f}")} → {_e(f"{r.end_price:,.4f}")} · quote {_e(f"{r.qty:,.4f}")} · '
            f'capitale impiegato {_e(_eur(r.invested))} · residuo {_e(_eur(r.residual))}{warn}</td></tr>')
    out.append("</tbody></table>")
    return "".join(out)


def render_parita_page(*, instruments, form, resolved, result, err_msg: str = "") -> str:
    """Pagina completa. `instruments`: elenco (ticker, nome); `form`: valori correnti del modulo."""
    body = [f'<div class="pp"><h1>⚖️ A parità di investimento</h1>', _form(instruments, form, resolved)]
    if err_msg:
        body.append(f'<div class="pp-err">{_e(err_msg)}</div>')
    if result is not None and not result.error:
        ok, total = result.coverage
        ref_note = "" if result.reference_ok else ' · <span class="pp-warn">riferimento senza prezzi: nessuna graduatoria relativa</span>'
        body.append(
            '<div class="pp-card"><div class="pp-cov">'
            f'<span class="pp-pill pp-v-ref">{ok} su {total} strumenti confrontabili</span>'
            f'<span>Capitale {_e(_eur(result.capital))}{ref_note}</span></div>'
            '<div class="pp-filters">'
            '<label><input type="checkbox" id="f-held" checked> Posseduti</label>'
            '<label><input type="checkbox" id="f-obs" checked> Osservati e chiusi</label>'
            '<label><input type="checkbox" id="f-gain"> Solo in guadagno</label>'
            '<label><input type="checkbox" id="f-better"> Solo meglio del riferimento</label>'
            '<span style="color:var(--slate-500)">Clic su un’intestazione per ordinare, su una riga per il dettaglio.</span></div>'
            + _table(result) + "</div>")
        if result.excluded:
            items = "".join(f"<li><b>{_e(x.name)}</b> ({_e(x.ticker)}): {_e(x.reason)}</li>" for x in result.excluded)
            body.append(f'<div class="pp-card"><h2 class="pp-h">Esclusi dal confronto</h2><ul class="pp-excl">{items}</ul></div>')
        names = {r.ticker: r.name for r in result.rows}
        for pid, title, fig in (
            ("ppPaths", f"Percorso di {_eur(result.capital)} giorno per giorno",
             paths_figure(result.paths, result.capital, result.reference, names)),
            ("ppBars", "Guadagno o perdita in euro per strumento", pl_bars_figure(result.rows)),
        ):
            if fig:
                body.append(f'<div class="pp-card"><h2 class="pp-h">{_e(title)}</h2><div id="{pid}" class="pp-plot"></div>'
                            f'<script type="application/json" id="{pid}-json">{fig}</script></div>')
            else:
                body.append(f'<div class="pp-card"><h2 class="pp-h">{_e(title)}</h2><div class="pp-empty">Nessun dato da mostrare</div></div>')
        body.append(f'<div class="pp-card"><h2 class="pp-h">Giudizio del periodo</h2>{_judgment(result)}</div>')
    body.append("</div>")
    return ('<!DOCTYPE html><html lang="it"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>A parità di investimento</title>{CSS}{_STYLE}</head><body>'
            + "".join(body) + _PLOT_JS + _JS + "</body></html>")
