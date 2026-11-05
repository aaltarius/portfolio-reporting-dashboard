"""
ui/pages/operazioni_timeline.py — Cronologia delle operazioni con filtri lato browser.

Produce una pagina HTML autonoma (iframe) con ricerca, filtri per tipo e periodo, totali che
seguono i filtri, righe espandibili ed esportazione CSV. Filtri e dettagli girano nel browser:
nessun widget Streamlit, nessun rerun, nessuna rete. Colori dal tema, passati dalla pagina.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

_MONTHS = ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno", "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]

_TEMPLATE = r"""<!doctype html><html lang="it"><head><meta charset="utf-8"><style>
:root{--sf:__SF__;--sf2:__SF2__;--tx:__TX__;--mu:__MU__;--bd:__BD__;--pr:__PR__;--ff:__FF__;
--k-acquisto:__C_ACQ__;--k-vendita:__C_VEN__;--k-rimborso:__C_RIM__;--k-cedola:__C_CED__;--k-dividendo:__C_DIV__;--k-versamento:__C_VER__;--k-prelievo:__C_PRE__;--k-costo:__C_COS__;
--pos:__POS__;--neg:__NEG__}
*{box-sizing:border-box}html,body{margin:0;height:100%;background:transparent;color:var(--tx);font-family:var(--ff);font-size:14px}
#app{display:flex;flex-direction:column;height:100%}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:2px 2px 10px}
.bar input,.bar select{height:36px;border-radius:10px;border:1px solid var(--bd);background:var(--sf);color:var(--tx);padding:0 12px;font:inherit}
.bar input{flex:1 1 220px;min-width:180px}
.chip{height:34px;padding:0 12px;border-radius:999px;border:1px solid var(--bd);background:var(--sf);color:var(--mu);font:600 12.5px var(--ff);cursor:pointer;display:inline-flex;align-items:center;gap:6px}
.chip.on{color:var(--tx);border-color:var(--pr);background:color-mix(in srgb,var(--pr) 12%,var(--sf))}
.chip i{font-style:normal;font-size:11px;color:var(--mu);font-weight:700}
.btn{height:36px;padding:0 14px;border-radius:10px;border:1px solid var(--pr);background:transparent;color:var(--pr);font:600 13px var(--ff);cursor:pointer}
.btn:hover{background:var(--pr);color:#fff}
.tot{display:flex;flex-wrap:wrap;gap:8px 20px;padding:8px 14px;margin-bottom:8px;border:1px solid var(--bd);border-radius:12px;background:var(--sf2);font-size:12.5px;color:var(--mu)}
.tot b{color:var(--tx);font-variant-numeric:tabular-nums}
#list{flex:1;overflow:auto;padding-right:4px}
.mh{position:sticky;top:0;z-index:2;display:flex;justify-content:space-between;gap:10px;padding:9px 14px;margin:10px 0 6px;border-radius:10px;background:var(--sf2);border:1px solid var(--bd);font-weight:800;font-size:13px}
.mh span{font-weight:600;color:var(--mu);font-size:12px}
.row{display:grid;grid-template-columns:52px 138px minmax(0,1fr) 170px 124px;gap:12px;align-items:center;padding:10px 14px;margin-bottom:6px;border:1px solid var(--bd);border-radius:14px;background:var(--sf);cursor:pointer;transition:border-color .12s}
.row:hover{border-color:color-mix(in srgb,var(--pr) 50%,var(--bd))}
.d{text-align:center;line-height:1.05}.d b{display:block;font-size:19px;font-weight:850}.d span{font-size:10.5px;text-transform:uppercase;letter-spacing:.08em;color:var(--mu);font-weight:700}
.badge{display:inline-flex;justify-content:center;padding:4px 10px;border-radius:999px;font-size:11.5px;font-weight:800;color:var(--kc);background:color-mix(in srgb,var(--kc) 13%,transparent);white-space:nowrap}
.ins{min-width:0}.tk{font-weight:800}.nm{color:var(--mu);margin-left:6px}.ins div{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sub{font-size:12px;color:var(--mu);margin-top:2px}
.qp{color:var(--mu);font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.net{text-align:right;font-weight:800;font-variant-numeric:tabular-nums;white-space:nowrap}.net.pos{color:var(--pos)}.net.neg{color:var(--neg)}
.tag{display:inline-block;font-size:11px;font-weight:700;padding:1px 8px;border-radius:999px;margin-right:5px;color:var(--mu);background:color-mix(in srgb,var(--mu) 12%,transparent)}
.tag.cov{color:var(--pos);background:color-mix(in srgb,var(--pos) 12%,transparent)}
.det{display:none;margin:-2px 0 8px;padding:12px 16px;border:1px dashed var(--bd);border-radius:12px;background:var(--sf2);grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px 18px}
.det.open{display:grid}.det div{font-size:12px;color:var(--mu)}.det b{display:block;color:var(--tx);font-size:13.5px;font-variant-numeric:tabular-nums;margin-top:1px}
.det .wide{grid-column:1/-1}
.empty{padding:36px;text-align:center;color:var(--mu)}
@media (max-width:760px){.row{grid-template-columns:44px 1fr 110px}.row .badge,.row .qp{display:none}}
</style></head><body><div id="app">
<div class="bar"><input id="q" type="search" placeholder="Cerca strumento, ticker o nota…" autocomplete="off">
<select id="per" aria-label="Periodo"></select><span id="chips"></span><button class="btn" id="csv" type="button">Esporta CSV</button></div>
<div class="tot" id="tot"></div><div id="list"></div></div>
<script>
const ROWS=__ROWS__,TODAY=new Date("__TODAY__T12:00:00"),MONTHS=__MONTHS__;
const GROUPS=[["acquisto","Acquisti",["acquisto"]],["vendita","Vendite e rimborsi",["vendita","rimborso"]],["proventi","Cedole e dividendi",["cedola","dividendo"]],["cassa","Versamenti e prelievi",["versamento","prelievo"]],["costo","Costi",["costo"]]];
const KC={acquisto:"var(--k-acquisto)",vendita:"var(--k-vendita)",rimborso:"var(--k-rimborso)",cedola:"var(--k-cedola)",dividendo:"var(--k-dividendo)",versamento:"var(--k-versamento)",prelievo:"var(--k-prelievo)",costo:"var(--k-costo)"};
const on=new Set(GROUPS.map(g=>g[0]));const open=new Set();
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const nf=(v,min,max)=>Math.abs(v).toLocaleString("it-IT",{minimumFractionDigits:min,maximumFractionDigits:max,useGrouping:"always"});
const eur=(v,signed)=>(v<0?"-":(signed&&v>0?"+":""))+"€ "+nf(v,2,2);
const kindOf=k=>GROUPS.find(g=>g[2].includes(k))[0];
const years=[...new Set(ROWS.map(r=>r.date.slice(0,4)))].sort().reverse();
$("per").innerHTML='<option value="all">Tutto il periodo</option><option value="ytd">Anno in corso</option><option value="365">Ultimi 12 mesi</option><option value="90">Ultimi 90 giorni</option>'+years.map(y=>`<option value="y${y}">Anno ${y}</option>`).join("");
function inPeriod(r){const p=$("per").value;if(p==="all")return true;if(p==="ytd")return r.date.slice(0,4)===String(TODAY.getFullYear());
if(p[0]==="y")return r.date.slice(0,4)===p.slice(1);const lim=new Date(TODAY);lim.setDate(lim.getDate()-parseInt(p,10));return new Date(r.date+"T12:00:00")>=lim;}
function match(r){const q=$("q").value.trim().toLowerCase();if(!q)return true;return (r.ticker+" "+r.name+" "+r.note+" "+r.label).toLowerCase().includes(q);}
function costOf(r){return r.kind==="costo"?Math.abs(r.net):(r.fees||0)+(r.taxes||0);}
function chips(base){$("chips").innerHTML=GROUPS.map(g=>{const n=base.filter(r=>g[2].includes(r.kind)).length;return `<button type="button" class="chip ${on.has(g[0])?"on":""}" data-g="${g[0]}">${g[1]} <i>${n}</i></button>`}).join("");}
function render(){
 const base=ROWS.filter(r=>inPeriod(r)&&match(r));chips(base);
 const rows=base.filter(r=>on.has(kindOf(r.kind)));
 let ac=0,inc=0,pro=0,cos=0;rows.forEach(r=>{if(r.kind==="acquisto")ac+=Math.abs(r.net);else if(r.kind==="vendita"||r.kind==="rimborso")inc+=Math.max(r.net,0);else if(r.kind==="cedola"||r.kind==="dividendo")pro+=r.net;cos+=costOf(r);});
 $("tot").innerHTML=`<span><b>${rows.length}</b> movimenti</span><span>Acquisti <b>${eur(ac)}</b></span><span>Vendite e rimborsi <b>${eur(inc)}</b></span><span>Cedole e dividendi <b>${eur(pro)}</b></span><span>Costi e imposte <b>${eur(cos)}</b></span>`;
 if(!rows.length){$("list").innerHTML='<div class="empty">Nessun movimento con questi filtri.</div>';return;}
 let html="",cur="",grp=[];
 const flush=()=>{if(!grp.length)return;const [y,m]=cur.split("-");let a=0,i=0;grp.forEach(r=>{if(r.kind==="acquisto")a+=Math.abs(r.net);else if(r.kind==="vendita"||r.kind==="rimborso"||r.kind==="cedola"||r.kind==="dividendo")i+=Math.max(r.net,0);});
  html+=`<div class="mh">${MONTHS[+m-1]} ${y}<span>${grp.length} movimenti · acquisti ${eur(a)} · incassi ${eur(i)}</span></div>`+grp.map(rowHtml).join("");grp=[];};
 rows.forEach(r=>{const mk=r.date.slice(0,7);if(mk!==cur){flush();cur=mk;}grp.push(r);});flush();
 $("list").innerHTML=html;
}
function rowHtml(r){
 const dd=r.date.slice(8,10),mm=MONTHS[+r.date.slice(5,7)-1].slice(0,3);
 const qp=r.qty?`${nf(r.qty,0,4)} × € ${nf(r.price,2,4)}`:"";
 const tags=[];if(r.fees)tags.push(`<span class="tag">Comm. € ${nf(r.fees,2,2)}</span>`);if(r.taxes)tags.push(`<span class="tag">Imposte € ${nf(r.taxes,2,2)}</span>`);
 if(r.cover!=null)tags.push(`<span class="tag cov">Versamento collegato ${eur(r.cover,true)}</span>`);
 const who=r.ticker?`<div><span class="tk" style="color:${r.catColor||"var(--tx)"}">${esc(r.ticker)}</span><span class="nm">${esc(r.name!==r.ticker?r.name:"")}</span></div>`:`<div><span class="tk">${esc(r.label)}</span></div>`;
 const note=r.note?`<div class="sub">${esc(r.note)}</div>`:`<div class="sub">${tags.join("")}</div>`;
 return `<div class="row" data-id="${esc(r.id)}" style="--kc:${KC[r.kind]}"><div class="d"><b>${dd}</b><span>${mm}</span></div><div><span class="badge">${esc(r.label)}</span></div><div class="ins">${who}${note}</div><div class="qp">${qp}</div><div class="net ${r.kind==="acquisto"?"":r.net>0?"pos":r.net<0?"neg":""}">${eur(r.net,true)}</div></div><div class="det" id="d_${esc(r.id)}"></div>`;
}
function detail(r){
 const f=(l,v)=>`<div>${l}<b>${v}</b></div>`;let h="";
 if(r.qty)h+=f("Quantità",nf(r.qty,0,4))+f("Prezzo unitario","€ "+nf(r.price,2,4));
 h+=f("Importo lordo",eur(r.gross))+f("Commissioni",eur(r.fees||0))+f("Imposte",eur(r.taxes||0))+f("Effetto sulla cassa",eur(r.net,true));
 if(r.cover!=null)h+=f("Versamento collegato",eur(r.cover,true))+f("Cassa dopo il versamento",eur(r.net+r.cover,true));
 h+=f("Data",r.date.split("-").reverse().join("/"));
 if(r.note)h+=`<div class="wide">Nota<b>${esc(r.note)}</b></div>`;return h;}
$("list").addEventListener("click",e=>{const row=e.target.closest(".row");if(!row)return;const id=row.dataset.id,box=document.getElementById("d_"+id),r=ROWS.find(x=>x.id===id);
 if(!box.classList.contains("open")){box.innerHTML=detail(r);box.classList.add("open");}else box.classList.remove("open");});
$("chips").addEventListener("click",e=>{const b=e.target.closest(".chip");if(!b)return;const g=b.dataset.g;on.has(g)?on.delete(g):on.add(g);render();});
$("q").addEventListener("input",render);$("per").addEventListener("change",render);
$("csv").addEventListener("click",()=>{const base=ROWS.filter(r=>inPeriod(r)&&match(r)&&on.has(kindOf(r.kind)));
 const n=v=>String(v==null?"":v).replace(".",",");const q=s=>'"'+String(s==null?"":s).replace(/"/g,'""')+'"';
 const head=["Data","Evento","Ticker","Strumento","Quantità","Prezzo","Lordo","Commissioni","Imposte","Netto cassa","Versamento collegato","Nota"];
 const lines=[head.join(";")].concat(base.map(r=>[r.date,q(r.label),q(r.ticker),q(r.name),n(r.qty),n(r.price),n(r.gross),n(r.fees),n(r.taxes),n(r.net),n(r.cover),q(r.note)].join(";")));
 const blob=new Blob(["﻿"+lines.join("\r\n")],{type:"text/csv;charset=utf-8"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="operazioni_"+"__TODAY__"+".csv";document.body.appendChild(a);a.click();a.remove();});
render();
</script></body></html>"""


def build_timeline_html(rows: list[dict[str, Any]], colors: dict[str, str], today: date | None = None) -> str:
    """Pagina HTML della cronologia. ``colors``: chiavi surface, surface2, text, muted, border, primary,
    font, acquisto, vendita, rimborso, cedola, dividendo, versamento, prelievo, costo, pos, neg."""
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    out = _TEMPLATE
    mapping = {
        "__SF__": colors["surface"], "__SF2__": colors["surface2"], "__TX__": colors["text"], "__MU__": colors["muted"],
        "__BD__": colors["border"], "__PR__": colors["primary"], "__FF__": colors["font"],
        "__C_ACQ__": colors["acquisto"], "__C_VEN__": colors["vendita"], "__C_RIM__": colors["rimborso"],
        "__C_CED__": colors["cedola"], "__C_DIV__": colors["dividendo"], "__C_VER__": colors["versamento"],
        "__C_PRE__": colors["prelievo"], "__C_COS__": colors["costo"], "__POS__": colors["pos"], "__NEG__": colors["neg"],
        "__TODAY__": (today or date.today()).isoformat(), "__MONTHS__": json.dumps(_MONTHS, ensure_ascii=False),
    }
    for key, value in mapping.items():
        out = out.replace(key, value)
    return out.replace("__ROWS__", payload)
