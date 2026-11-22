"""ui/form_server/pl_periodo_html.py — pagina «Andamento» (PL-01): grafico P/L o controvalore in stile Yahoo Finance.

Solo presentazione. Il server consegna le serie giornaliere (core/services/pl_periodo.py); somme, finestra di date,
parziali ed estremi si calcolano nel browser. Il grafico è disegnato con Plotly (`/assets/plotly.min.js`, locale) in
modo statico; mirino, punto, suggerimento e selezione trascinando sono elementi HTML sovrapposti, comandati dal mouse
con `requestAnimationFrame`: nessun ridisegno di Plotly mentre ci si muove, quindi nessuno scatto. Linea e area sono
verdi sopra la linea di riferimento (zero in modalità P/L, valore iniziale in modalità controvalore) e rosse sotto.
Ogni testo dinamico passa da `esc()`; il JSON incorporato ha `<` sostituito con `\\u003c`.
"""
from __future__ import annotations

import json

from ui.form_server.shell import CSS
from ui.theme_tokens import resolve_form_colors

_CSS = """<style>
:root{--pl-shade:rgba(15,23,42,.14);--pl-shade-mk:rgba(15,23,42,.35);--pl-band:rgba(79,70,229,.13)}
.pl{max-width:1380px;margin:0 auto}
.pl h1{margin:0 0 16px}
.pl-card{background:var(--white);border-radius:14px;padding:18px 22px;box-shadow:0 2px 12px var(--black-a06);margin-bottom:14px}
.pl-top{display:flex;flex-wrap:wrap;gap:16px;align-items:flex-end}
.pl-top .f{display:flex;flex-direction:column}
.pl-top label{font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--slate-500);margin-bottom:3px}
.pl-top select,.pl-top input{padding:8px 8px;border:1px solid var(--slate-300);border-radius:8px;font-size:.9rem;background:var(--white)}
#pl-sel{min-width:220px;max-width:280px}
.seg{display:flex;gap:4px;background:var(--slate-100);border-radius:12px;padding:4px}
.seg button{border:0;background:transparent;color:var(--slate-700);border-radius:8px;padding:8px 12px;font-weight:700;font-size:.82rem;cursor:pointer}
.seg button:focus-visible,.pl-top select:focus-visible,.pl-top input:focus-visible{outline:2px solid var(--indigo-600);outline-offset:2px}
.seg button:hover{background:var(--slate-200)}
.seg button:active{transform:translateY(1px)}
html,body{overflow-x:clip}
.seg button.on{background:var(--white);color:var(--indigo-700);box-shadow:0 1px 3px var(--black-a07)}
.pl-name{font-size:1rem;font-weight:700;color:var(--slate-700)}
.pl-bigrow{display:flex;align-items:baseline;gap:16px;flex-wrap:wrap}
.pl-big{font-size:2.3rem;font-weight:800;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.pl-pct{font-size:1.2rem;font-weight:700}
.pl-sub{color:var(--slate-500);font-size:.82rem;margin-bottom:8px}
.pl-pos{color:var(--emerald-600)}.pl-neg{color:var(--red-600)}.pl-zero{color:var(--slate-500)}
#pl-wrap{position:relative;width:100%;height:430px;user-select:none;cursor:crosshair}
#pl-chart{position:absolute;inset:0}
.ov{position:absolute;pointer-events:none;display:none}
#pl-hline{height:0;border-top:1px dashed var(--slate-500)}
#pl-cross{width:0;border-left:1px dashed var(--slate-500)}
#pl-dot{width:12px;height:12px;border-radius:50%;border:2px solid var(--white);box-shadow:0 0 0 1px var(--slate-300);transform:translate(-50%,-50%)}
.k-A{background:var(--indigo-600)}.k-V{background:var(--amber-500)}.k-R{background:var(--slate-500)}.k-C{background:var(--slate-600)}.k-T{background:var(--slate-700)}
.t-A{color:var(--indigo-600)}.t-V{color:var(--amber-700)}.t-R{color:var(--slate-500)}.t-C{color:var(--slate-600)}
#pl-ytag{transform:translateY(-50%);background:var(--slate-700);color:var(--white);font-size:.72rem;font-weight:700;padding:4px 8px;border-radius:4px;font-variant-numeric:tabular-nums;white-space:nowrap}
#pl-last{transform:translateY(-50%);color:var(--white);font-size:.72rem;font-weight:700;padding:4px 8px;border-radius:4px;font-variant-numeric:tabular-nums;white-space:nowrap}
#pl-marks{position:absolute;inset:0;pointer-events:none}
.mk{position:absolute;width:18px;height:18px;margin:-8px 0 0 -8px;border-radius:50%;color:var(--white);font-size:10px;font-weight:800;display:flex;align-items:center;justify-content:center;border:2px solid var(--white);box-shadow:0 1px 4px var(--pl-shade-mk);pointer-events:none}
#pl-dot{z-index:3}#pl-tip{z-index:4}
.pl-legend{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:.74rem;color:var(--slate-500);margin:8px 0 0}
.pl-legend span{display:inline-flex;align-items:center;gap:4px}
.pl-legend .mk{position:static;margin:0;width:15px;height:15px;font-size:9px;box-shadow:none;border-width:0}
.tip-op{display:block;margin-top:2px;color:var(--slate-700);font-size:.75rem;white-space:nowrap}
.tip-op em{font-style:normal;font-weight:800}
#pl-band{background:var(--pl-band);border-left:1px solid var(--indigo-600);border-right:1px solid var(--indigo-600)}
#pl-tip{background:var(--white);border:1px solid var(--slate-200);border-radius:10px;box-shadow:0 4px 16px var(--pl-shade);padding:8px 12px;font-size:.8rem;min-width:150px}
#pl-tip>span{display:block}
#pl-tip b{display:block;font-size:1.02rem;font-variant-numeric:tabular-nums}
#pl-tip>span{color:var(--slate-500)}
.pl-hint{font-size:.74rem;color:var(--slate-500);margin:4px 0 0}
.pl-per{margin:16px 0 8px;padding:12px 16px;border-radius:12px;background:var(--slate-100);font-size:.9rem;color:var(--slate-700)}
#pl-stats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
@media(max-width:900px){#pl-stats{grid-template-columns:minmax(0,1fr)}}
.pl-sec{border:1px solid var(--slate-200);border-radius:12px;padding:16px 20px}
.pl-sec h3{margin:0;font-size:.82rem;font-weight:800;text-transform:uppercase;letter-spacing:.05em;color:var(--slate-500)}
.pl-sec p{margin:4px 0 0;font-size:.82rem;color:var(--slate-500)}
.pl-rows{margin-top:8px}
.pl-row{display:flex;justify-content:space-between;align-items:baseline;gap:16px;padding:8px 0;border-top:1px solid var(--slate-100)}
.pl-row:first-child{border-top:0}
.pl-row .l{display:block;font-size:.9rem;font-weight:600;color:var(--slate-700)}
.pl-row i{display:block;font-style:normal;font-size:.78rem;color:var(--slate-500)}
.pl-row .v{font-size:1.05rem;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap;text-align:right}
.pl-row.tot{border-top:2px solid var(--slate-300);margin-top:4px;padding-top:12px}
.pl-row.tot .v{font-size:1.2rem}
.pl-empty{padding:28px;text-align:center;color:var(--slate-500)}
</style>"""

_JS = r"""<script>
var DATA=JSON.parse(document.getElementById('pl-data').textContent);
var COL=__COLORS__;
var D=DATA.dates,N=D.length,S=DATA.series,DM=D.map(function(d,i){return i;});
var DEP=DATA.deposits||[];
var sel='all',mode='pl',i0=0,i1=N-1,rangeKey='1M',G=null,AGG={};
var $=function(id){return document.getElementById(id);};
function esc(s){return String(s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
var fEur=new Intl.NumberFormat('it-IT',{style:'currency',currency:'EUR',minimumFractionDigits:2,maximumFractionDigits:2,useGrouping:'always'});
function eur(v,sign){var s=fEur.format(Math.abs(v)).replace(/\s/g,'\u00a0');return (v<-0.004?'−':(sign&&v>0.004?'+':''))+s;}
function pct(v,sign){if(v===null||!isFinite(v))return 'n/d';return (v<0?'−':(sign&&v>0?'+':''))+Math.abs(v*100).toFixed(2).replace('.',',')+'%';}
function dIt(s){return s.slice(8,10)+'/'+s.slice(5,7)+'/'+s.slice(0,4);}
function dS(s){return s.slice(8,10)+'/'+s.slice(5,7);}
function cls(v){return v>0.004?'pl-pos':(v<-0.004?'pl-neg':'pl-zero');}
function short(s,n){return s.length>n?s.slice(0,n-1)+'…':s;}

function keysFor(k){
  if(k==='all')return S;
  if(k==='held')return S.filter(function(s){return s.st==='posseduto';});
  if(k==='closed')return S.filter(function(s){return s.st==='chiuso';});
  if(k.indexOf('cat:')===0)return S.filter(function(s){return s.cat===k.slice(4);});
  if(k.indexOf('tipo:')===0)return S.filter(function(s){return s.tipo===k.slice(5);});
  return S.filter(function(s){return 'tk:'+s.t===k;});
}
function labelFor(k){
  if(k==='all')return 'Tutto il portafoglio';
  if(k==='held')return 'Strumenti posseduti';
  if(k==='closed')return 'Strumenti chiusi';
  if(k.indexOf('cat:')===0)return 'Categoria '+k.slice(4);
  if(k.indexOf('tipo:')===0)return k.slice(5);
  var s=S.filter(function(x){return 'tk:'+x.t===k;})[0];return s?(s.t+' · '+s.n):k;
}
function agg(k){
  if(AGG[k])return AGG[k];
  var t=new Float64Array(N),v=new Float64Array(N),b=new Float64Array(N),r=new Float64Array(N),c=new Float64Array(N);
  var ops={};
  keysFor(k).forEach(function(s){for(var i=0;i<N;i++){t[i]+=s.total[i];v[i]+=s.value[i];b[i]+=s.bought[i];r[i]+=s.realized[i];c[i]+=s.income[i];}
    s.ops.forEach(function(o){(ops[o[0]]=ops[o[0]]||[]).push({t:s.t,k:o[1],q:o[2],a:o[3]});});});
  var pl=new Float64Array(N);for(var q=0;q<N;q++)pl[q]=t[q]-c[q];
  return AGG[k]={pl:pl,total:t,value:v,bought:b,real:r,inc:c,ops:ops};
}
function nearest(ms){var lo=i0,hi=i1;while(hi-lo>1){var m=(lo+hi)>>1;if(DM[m]<=ms)lo=m;else hi=m;}return (ms-DM[lo]<=DM[hi]-ms)?lo:hi;}
function setWindowByDates(a,b){
  var s=0,e=N-1,i;
  for(i=0;i<N;i++){if(D[i]<=a)s=i;}for(i=0;i<N;i++){if(D[i]<=b)e=i;}
  if(e<=s){if(s<N-1)e=s+1;else s=Math.max(0,e-1);}
  i0=s;i1=e;
}
function rangeStart(k){
  var last=new Date(D[N-1]+'T00:00:00'),d=new Date(last);
  if(k==='1S')d.setDate(d.getDate()-7);else if(k==='1M')d.setMonth(d.getMonth()-1);
  else if(k==='3M')d.setMonth(d.getMonth()-3);else if(k==='6M')d.setMonth(d.getMonth()-6);
  else if(k==='1A')d.setFullYear(d.getFullYear()-1);else if(k==='YTD')d=new Date(last.getFullYear()-1,11,31);
  else return D[0];
  var m=d.getMonth()+1,dd=d.getDate();return d.getFullYear()+'-'+(m<10?'0':'')+m+'-'+(dd<10?'0':'')+dd;
}
function applyRange(k){rangeKey=k;setWindowByDates(rangeStart(k),D[N-1]);render();}

/* ---- calcoli sulla finestra [i0,i1] ---- */
/* dal primo giorno in poi la partenza è «prima di qualunque operazione» (zero), come i totali dell'app; altrimenti è la chiusura del giorno iniziale */
function S0(arr){return i0===0?0:arr[i0];}
function M(a){return mode==='val'?a.value:(mode==='tr'?a.total:a.pl);}
function capAt(j){return (mode==='tr'&&sel==='all'&&DEP[j]>0.005)?DEP[j]:A.bought[j];}
function capName(){return (mode==='tr'&&sel==='all'&&DEP[i1]>0.005)?'Capitale netto versato':'Capitale investito';}
function capNote(){return (mode==='tr'&&sel==='all'&&DEP[i1]>0.005)?'versamenti meno prelievi fino al '+dS(D[i1])+': base della %':'acquisti totali dall’inizio al '+dS(D[i1])+': base della %';}
function stats(a){
  var m=M(a),off=mode!=='val'?S0(m):0,base=mode!=='val'?0:S0(m),pl=m[i1]-S0(m),cap=capAt(i1);
  var hi={v:-1e18},lo={v:1e18},dd={v:0},up={v:-1e18},dn={v:1e18},peak=-1e18,peakDay=null;
  for(var i=i0;i<=i1;i++){
    var y=m[i]-off;
    if(y>hi.v){hi={v:y,day:D[i]};} if(y<lo.v){lo={v:y,day:D[i]};}
    if(y>peak){peak=y;peakDay=D[i];} if(peak-y>dd.v){dd={v:peak-y,from:peakDay,to:D[i]};}
    if(i>i0){var d=m[i]-m[i-1];if(mode!=='val'){if(d>up.v)up={v:d,day:D[i]};if(d<dn.v)dn={v:d,day:D[i]};}}
  }
  return {pl:pl,cap:cap,pct:cap>0?pl/cap:null,base:base,off:off,hi:hi,lo:lo,dd:dd,up:up,dn:dn,
    dU:(a.total[i1]-a.real[i1]-a.inc[i1])-(S0(a.total)-S0(a.real)-S0(a.inc)),dR:a.real[i1]-S0(a.real),dI:a.inc[i1]-S0(a.inc),
    buy:a.bought[i1]-S0(a.bought),v0:S0(a.value),v1:a.value[i1],dv:a.value[i1]-S0(a.value)};
}

/* ---- intestazione ---- */
var A=null,ST=null;
function header(j){
  var big,p,c,sub,e=(j===null)?i1:j;
  if(mode!=='val'){
    var pl=(j===null)?ST.pl:M(A)[j]-S0(M(A)),cap=capAt(e),nm=mode==='tr'?'Total return':'P/L';
    big=eur(pl,true);p=cap>0?pl/cap:null;c=cls(pl);
    sub=nm+' dal '+dIt(D[i0])+' al '+dIt(D[e])+(mode==='tr'?' (P/L più cedole e dividendi netti)':' (prezzi e vendite realizzate; cedole e dividendi esclusi)')+'. Percentuale sul '+capName().toLowerCase()+', come nel resto di Sestante.';
    $('pl-pct').textContent=(pl>0.004?'▲ ':(pl<-0.004?'▼ ':''))+pct(p,true);
  }else{
    var v=A.value[e],dv=v-S0(A.value);
    big=eur(v);p=S0(A.value)>0?dv/S0(A.value):null;c=cls(dv);
    sub='Controvalore al '+dIt(D[e])+'. Variazione rispetto al '+dIt(D[i0])+': '+eur(dv,true)+' (comprende gli acquisti fatti nel periodo).';
    $('pl-pct').textContent=(dv>0.004?'▲ ':(dv<-0.004?'▼ ':''))+pct(p,true);
  }
  $('pl-big').className='pl-big '+(mode!=='val'?c:'');$('pl-big').textContent=big;
  $('pl-pct').className='pl-pct '+c;$('pl-sub').textContent=sub;
}
function stat(l,v,note,tot){return '<div class="pl-row'+(tot?' tot':'')+'"><div><span class="l">'+l+'</span>'+(note?'<i>'+note+'</i>':'')+'</div><span class="v">'+v+'</span></div>';}
function sec(t,p,items){p=p.trim();return '<div class="pl-sec"><h3>'+t+'</h3>'+(p?'<p>'+p+'</p>':'')+'<div class="pl-rows">'+items+'</div></div>';}
function colored(v){return '<span class="'+cls(v)+'">'+eur(v,true)+'</span>';}
function opsSummary(){
  var r={A:[0,0],V:[0,0],R:[0,0],C:[0,0]};
  Object.keys(A.ops).forEach(function(i){i=+i;if(i<i0||i>i1)return;A.ops[i].forEach(function(o){r[o.k][0]++;r[o.k][1]+=o.a;});});
  return r;
}
function stats_html(){
  var s=ST,per='',h='';
  if(mode!=='val'){
    var tr=mode==='tr';
    h+=sec(tr?'Da cosa deriva il total return':'Da cosa deriva il P/L',tr?'Total return = P/L più cedole e dividendi netti.':'P/L come nel resto di Sestante: prezzi e vendite realizzate, senza cedole e dividendi.',
      stat('Variazione dei prezzi',colored(s.dU),'comprende l’utile già maturato che poi diventa realizzato (voce sotto), con segno opposto')
      +stat('Vendite e rimborsi realizzati',colored(s.dR),'guadagno o perdita incassati vendendo o a scadenza, al netto delle imposte')
      +(tr?stat('Cedole e dividendi',colored(s.dI),'proventi netti incassati'):'')
      +stat(tr?'Totale total return':'Totale P/L',colored(s.pl),tr?'P/L '+eur(s.dU+s.dR,true)+' più proventi '+eur(s.dI,true):'cedole e dividendi nel periodo: '+eur(s.dI,true)+' (solo nel total return)',true));
    h+=sec('Capitale',per,
      stat('Valore a inizio periodo',eur(s.v0),'chiusura del '+dS(D[i0]))
      +stat('Acquisti nel periodo',eur(s.buy),'soldi messi in più')
      +stat(capName(),eur(s.cap),capNote())
      +stat('Valore a fine periodo',eur(s.v1),'chiusura del '+dS(D[i1])));
    h+=sec('Estremi del grafico',per+' Si riferiscono alla linea che vedi, non a tutta la storia.',
      stat('Punto più alto',colored(s.hi.v),'il '+dIt(s.hi.day))
      +stat('Punto più basso',colored(s.lo.v),'il '+dIt(s.lo.day))
      +stat('Calo massimo',s.dd.v>0?'<span class="pl-neg">'+eur(-s.dd.v)+'</span>':'—',s.dd.v>0?'dal punto più alto del '+dS(s.dd.from)+' al più basso del '+dS(s.dd.to):'nessun calo nel periodo')
      +stat('Maggior rialzo in un giorno',s.up.v>-1e17?colored(s.up.v):'—',s.up.day?'il '+dIt(s.up.day):'')
      +stat('Maggior calo in un giorno',s.dn.v<1e17?colored(s.dn.v):'—',s.dn.day?'il '+dIt(s.dn.day):''));
  }else{
    h+=sec('Controvalore nel periodo',per,
      stat('Valore a inizio periodo',eur(s.v0),'chiusura del '+dS(D[i0]))
      +stat('Valore a fine periodo',eur(s.v1),'chiusura del '+dS(D[i1]))
      +stat('Variazione',colored(s.dv),pct(s.v0>0?s.dv/s.v0:null,true)));
    h+=sec('Da cosa deriva la variazione',per,
      stat('Acquisti nel periodo',eur(s.buy),'soldi messi in più')
      +stat('Prezzi, vendite e rimborsi',colored(s.dv-s.buy),'tutto il resto: andamento dei prezzi, quote vendute o rimborsate'));
    h+=sec('Estremi del grafico',per+' Si riferiscono alla linea che vedi, non a tutta la storia.',
      stat('Valore più alto',eur(s.hi.v),'il '+dIt(s.hi.day))
      +stat('Valore più basso',eur(s.lo.v),'il '+dIt(s.lo.day))
      +stat('Calo massimo',s.dd.v>0?'<span class="pl-neg">'+eur(-s.dd.v)+'</span>':'—',s.dd.v>0?'dal valore più alto del '+dS(s.dd.from)+' al più basso del '+dS(s.dd.to):'nessun calo nel periodo'));
  }
  var o=opsSummary();
  h+=sec('Operazioni nel periodo',per+' Sono i segnali che vedi sul grafico.',
    stat('Acquisti',eur(o.A[1]),o.A[0]+(o.A[0]===1?' operazione':' operazioni'))
    +stat('Vendite',eur(o.V[1]),o.V[0]+(o.V[0]===1?' operazione':' operazioni'))
    +(o.R[0]?stat('Rimborsi a scadenza',eur(o.R[1]),o.R[0]+(o.R[0]===1?' operazione':' operazioni')):'')
    +stat('Cedole e dividendi',eur(o.C[1]),o.C[0]+(o.C[0]===1?' incasso':' incassi')));
  return h;
}

/* ---- grafico ---- */
var PAD={l:14,r:78,t:14,b:30};
function iso(v){return v;}
var MESI=['gen','feb','mar','apr','mag','giu','lug','ago','set','ott','nov','dic'];
function xTicks(){var n=6,span=i1-i0,v=[],t=[],long=(Date.parse(D[i1])-Date.parse(D[i0]))>200*86400000,k,ix,d;
  for(k=0;k<=n;k++){ix=Math.round(i0+span*k/n);if(v.length&&v[v.length-1]===ix)continue;d=D[ix];v.push(ix);t.push(long?MESI[+d.slice(5,7)-1]+' '+d.slice(2,4):dS(d));}
  return {v:v,t:t};}
function buildGeom(){
  var a=A,m=M(a),off=mode!=='val'?S0(m):0,base=mode!=='val'?0:S0(m),pts=[],j;
  for(j=i0;j<=i1;j++)pts.push({t:DM[j],y:m[j]-off});
  var aug=[pts[0]];
  for(j=1;j<pts.length;j++){var p=pts[j-1],q=pts[j];
    if((p.y-base)*(q.y-base)<0){var tc=p.t+(q.t-p.t)*(base-p.y)/(q.y-p.y);aug.push({t:tc,y:base});}
    aug.push(q);}
  var lo=base,hi=base;aug.forEach(function(p){if(p.y<lo)lo=p.y;if(p.y>hi)hi=p.y;});
  var pad=(hi-lo)*0.10||Math.max(1,Math.abs(base)*0.01),rg=hi-lo+2*pad,bot=lo-pad-rg*0.20;
  return {aug:aug,base:base,off:off,lo:bot,hi:hi+pad,t0:DM[i0],t1:DM[i1],lane:0.17};
}
function lineRuns(aug,base){
  var g={x:[],y:[]},r={x:[],y:[]};
  for(var k=1;k<aug.length;k++){
    var a=aug[k-1],b=aug[k],c=((a.y+b.y)/2>=base)?g:r,lx=c.x.length?c.x[c.x.length-1]:null;
    if(!c.x.length||lx!==iso(a.t)){if(c.x.length){c.x.push(null);c.y.push(null);}c.x.push(iso(a.t));c.y.push(a.y);}
    c.x.push(iso(b.t));c.y.push(b.y);}
  return [g,r];
}
function niceTicks(lo,hi){
  var raw=(hi-lo)/5,mag=Math.pow(10,Math.floor(Math.log10(raw))),f=raw/mag,st=(f<1.5?1:f<3?2:f<7?5:10)*mag,out=[];
  for(var v=Math.ceil(lo/st)*st;v<=hi+1e-9;v+=st)out.push(Math.round(v/st)*st);
  return {vals:out,step:st};
}
function chart(){
  G=buildGeom();var el=$('pl-chart'),W=el.clientWidth||900,H=el.clientHeight||430;
  var xs=G.aug.map(function(p){return iso(p.t);}),base=G.base;
  var yg=G.aug.map(function(p){return Math.max(p.y,base);}),yr=G.aug.map(function(p){return Math.min(p.y,base);});
  var bl={x:[iso(G.t0),iso(G.t1)],y:[base,base],mode:'lines',line:{color:COL.muted,width:1,dash:'dot'},hoverinfo:'skip'};
  var runs=lineRuns(G.aug,base),nof={line:{width:0},hoverinfo:'skip',mode:'lines'};
  var gG={type:'vertical',colorscale:[[0,'rgba(5,150,105,0)'],[1,'rgba(5,150,105,.34)']]},gR={type:'vertical',colorscale:[[0,'rgba(220,38,38,.34)'],[1,'rgba(220,38,38,0)']]};
  var data=[bl,Object.assign({x:xs,y:yg,fill:'tonexty',fillgradient:gG,fillcolor:'rgba(5,150,105,.16)'},nof),
    {x:[iso(G.t0),iso(G.t1)],y:[base,base],mode:'lines',line:{width:0},hoverinfo:'skip'},
    Object.assign({x:xs,y:yr,fill:'tonexty',fillgradient:gR,fillcolor:'rgba(220,38,38,.14)'},nof),
    {x:runs[0].x,y:runs[0].y,mode:'lines',line:{color:COL.pos,width:2,shape:'linear'},hoverinfo:'skip',connectgaps:false},
    {x:runs[1].x,y:runs[1].y,mode:'lines',line:{color:COL.neg,width:2,shape:'linear'},hoverinfo:'skip',connectgaps:false}];
  var lay={width:W,height:H,margin:{l:PAD.l,r:PAD.r,t:PAD.t,b:PAD.b},paper_bgcolor:COL.white,plot_bgcolor:COL.white,separators:',.',
    font:{family:"system-ui,-apple-system,'Segoe UI',sans-serif",size:12,color:COL.text},showlegend:false,dragmode:false,
    xaxis:{type:'linear',tickmode:'array',tickvals:xTicks().v,ticktext:xTicks().t,range:[iso(G.t0),iso(G.t1)],showgrid:false,fixedrange:true,automargin:false,showline:true,linecolor:COL.grid,ticks:'outside',tickcolor:COL.grid,tickfont:{color:COL.muted,size:11}},
    yaxis:{range:[G.lo,G.hi],side:'right',gridcolor:COL.grid2,gridwidth:1,fixedrange:true,automargin:false,tickformat:',.0f',ticksuffix:' €',zeroline:false,showline:false,tickfont:{color:COL.muted,size:11}}};
  var m=M(A),bx=[],by=[],bc=[],abs=[];
  for(var j=i0+(i0===0?0:1);j<=i1;j++){var dv=m[j]-(j===0?0:m[j-1]);bx.push(iso(DM[j]));by.push(dv);bc.push(dv>=0?'rgba(5,150,105,.45)':'rgba(220,38,38,.45)');abs.push(Math.abs(dv));}
  abs.sort(function(a,b){return a-b;});var cap=abs.length?(abs[Math.floor(abs.length*0.95)]||abs[abs.length-1]):1;if(!(cap>0))cap=1;
  data.push({type:'bar',x:bx,y:by,yaxis:'y2',marker:{color:bc,line:{width:0}},width:0.8,hoverinfo:'skip'});
  var nt=niceTicks(G.lo+(G.hi-G.lo)*0.2,G.hi);G.step=nt.step;
  lay.yaxis2={domain:[0,G.lane],range:[-cap,cap],visible:false,fixedrange:true};
  lay.yaxis.tickmode='array';lay.yaxis.tickvals=nt.vals;
  lay.yaxis.ticktext=nt.vals.map(function(v){return nt.step<1?v.toFixed(2).replace('.',','):((Math.round(v)||0).toLocaleString('it-IT',{useGrouping:true}).replace(/^(\d)(\d{3})$/,'$1.$2'))+' €';});
  Plotly.react('pl-chart',data,lay,{staticPlot:true,responsive:false});
  G.W=W;G.H=H;drawMarks();
}
function X(ms){return PAD.l+(ms-G.t0)/(G.t1-G.t0)*(G.W-PAD.l-PAD.r);}
function Y(v){return PAD.t+(1-(v-G.lo)/(G.hi-G.lo))*(G.H-PAD.t-PAD.b);}

/* ---- segnali di operazione e prezzo finale ---- */
var KC={A:COL.buy,V:COL.sell,R:COL.muted,C:COL.inc},KN={A:'Acquisto',V:'Vendita',R:'Rimborso',C:'Cedola/dividendo'},KL={A:'A',V:'V',R:'R',C:'€'};
function drawMarks(){
  var m=M(A),h='',lastX=-99,cur=null,flush=function(){if(cur){h+='<div class="mk k-'+(cur.ks.length>1?'T':cur.ks[0])+'" style="left:'+cur.x+'px;top:'+cur.y+'px">'+(cur.ks.length>1?'•':KL[cur.ks[0]])+'</div>';}};
  for(var j=i0;j<=i1;j++){var o=A.ops[j];if(!o)continue;
    var x=X(DM[j]),y=Y(m[j]-G.off),ks=[];o.forEach(function(e){if(ks.indexOf(e.k)<0)ks.push(e.k);});
    if(cur&&x-cur.x<16){ks.forEach(function(k){if(cur.ks.indexOf(k)<0)cur.ks.push(k);});continue;}
    flush();cur={x:x,y:y,ks:ks};}
  flush();$('pl-marks').innerHTML=h;
  var ly=m[i1]-G.off,up=ly>=G.base-0.004,t=$('pl-last');
  t.style.display='block';t.style.left=(G.W-PAD.r+4)+'px';t.style.top=Y(ly)+'px';t.style.background=up?COL.pos:COL.neg;
  t.textContent=eur(ly);
}

/* ---- sovrapposizioni: mirino, suggerimento, selezione ---- */
var wrap,cross,hline,dot,tip,band,ytag,raf=0,mx=null,drag=null;
function overlay(){
  raf=0;if(!G||mx===null){cross.style.display=hline.style.display=dot.style.display=tip.style.display=ytag.style.display='none';return;}
  var ms=G.t0+(mx-PAD.l)/(G.W-PAD.l-PAD.r)*(G.t1-G.t0),j=nearest(ms),m=M(A),y=m[j]-G.off,px=X(DM[j]),py=Y(y);
  cross.style.display=hline.style.display=dot.style.display=tip.style.display=ytag.style.display='block';
  hline.style.left=PAD.l+'px';hline.style.width=(G.W-PAD.l-PAD.r)+'px';hline.style.top=py+'px';
  cross.style.left=px+'px';cross.style.top=PAD.t+'px';cross.style.height=(G.H-PAD.t-PAD.b)+'px';
  var up=y>=G.base-0.004;dot.style.left=px+'px';dot.style.top=py+'px';dot.style.background=up?COL.pos:COL.neg;
  var line1,line2;
  if(mode!=='val'){var cap=capAt(j);line1='<b class="'+cls(y)+'">'+eur(y,true)+'</b>';line2='<span>'+pct(cap>0?y/cap:null,true)+' · dal '+dS(D[i0])+'</span>';}
  else{var dv=y-G.base;line1='<b>'+eur(y)+'</b>';line2='<span class="'+cls(dv)+'">'+eur(dv,true)+' dal '+dS(D[i0])+'</span>';}
  var ol='',oo=A.ops[j]||[];
  oo.slice(0,4).forEach(function(e){ol+='<span class="tip-op"><em class="t-'+e.k+'">'+KN[e.k]+'</em> '+(e.k==='C'?'':e.q.toLocaleString('it-IT',{maximumFractionDigits:4})+' × ')+esc(e.t)+' · '+eur(e.a)+'</span>';});
  if(oo.length>4)ol+='<span class="tip-op">… e altre '+(oo.length-4)+'</span>';
  ytag.style.left=(G.W-PAD.r+4)+'px';ytag.style.top=py+'px';ytag.textContent=eur(y,mode!=='val');
  var dd=j>0?m[j]-m[j-1]:0;line2+='<span>Variazione del giorno: <b style="display:inline;font-size:.8rem" class="'+cls(dd)+'">'+eur(dd,true)+'</b></span>';
  tip.innerHTML='<span>'+dIt(D[j])+'</span>'+line1+line2+ol;
  var tw=tip.offsetWidth,tl=px+16;if(tl+tw>G.W-4)tl=px-16-tw;tip.style.left=Math.max(4,tl)+'px';tip.style.top=Math.max(4,Math.min(py-30,G.H-PAD.b-tip.offsetHeight-6))+'px';
  header(j);
}
function schedule(){if(!raf)raf=requestAnimationFrame(overlay);}
function inPlot(x){return x>=PAD.l&&x<=G.W-PAD.r;}
function wireMouse(){
  wrap=$('pl-wrap');ytag=$('pl-ytag');cross=$('pl-cross');hline=$('pl-hline');dot=$('pl-dot');tip=$('pl-tip');band=$('pl-band');
  wrap.addEventListener('mousemove',function(e){
    if(!G)return;var x=e.clientX-wrap.getBoundingClientRect().left;
    if(drag){drag.x1=Math.max(PAD.l,Math.min(G.W-PAD.r,x));
      band.style.display='block';band.style.left=Math.min(drag.x0,drag.x1)+'px';band.style.width=Math.abs(drag.x1-drag.x0)+'px';
      band.style.top=PAD.t+'px';band.style.height=(G.H-PAD.t-PAD.b)+'px';}
    mx=inPlot(x)?x:null;schedule();});
  wrap.addEventListener('mouseleave',function(){mx=null;if(!drag){schedule();header(null);}});
  wrap.addEventListener('mousedown',function(e){var x=e.clientX-wrap.getBoundingClientRect().left;if(G&&inPlot(x))drag={x0:x,x1:x};});
  window.addEventListener('mouseup',function(){
    if(!drag)return;var d=drag;drag=null;band.style.display='none';
    if(Math.abs(d.x1-d.x0)>8){var a=Math.min(d.x0,d.x1),b=Math.max(d.x0,d.x1),t=function(x){return G.t0+(x-PAD.l)/(G.W-PAD.l-PAD.r)*(G.t1-G.t0);};
      var ia=nearest(t(a)),ib=nearest(t(b));if(ib>ia){i0=ia;i1=ib;rangeKey='';render();}}});
  wrap.addEventListener('dblclick',function(){applyRange('Max');});
}

function render(){
  A=agg(sel);ST=stats(A);
  document.querySelectorAll('#pl-ranges button').forEach(function(b){b.classList.toggle('on',b.dataset.k===rangeKey);});
  document.querySelectorAll('#pl-mode button').forEach(function(b){b.classList.toggle('on',b.dataset.m===mode);});
  $('pl-from').value=D[i0];$('pl-to').value=D[i1];$('pl-name').textContent=labelFor(sel);
  header(null);chart();$('pl-per').innerHTML='Periodo selezionato: <b>dal '+dIt(D[i0])+' al '+dIt(D[i1])+'</b>. I numeri qui sotto si riferiscono solo a questo periodo, non a tutta la storia.';$('pl-stats').innerHTML=stats_html();
}
function init(){
  var cats={},tipi={},o='<optgroup label="Portafoglio"><option value="all">Tutto il portafoglio</option><option value="held">Strumenti posseduti</option><option value="closed">Strumenti chiusi</option></optgroup>';
  S.forEach(function(s){cats[s.cat]=1;tipi[s.tipo]=1;});
  o+='<optgroup label="Categorie">'+Object.keys(cats).sort().map(function(c){return '<option value="cat:'+esc(c)+'">'+esc(c)+'</option>';}).join('')+'</optgroup>';
  o+='<optgroup label="Tipi">'+Object.keys(tipi).sort().map(function(c){return '<option value="tipo:'+esc(c)+'">'+esc(c)+'</option>';}).join('')+'</optgroup>';
  o+='<optgroup label="Strumenti">'+S.slice().sort(function(a,b){return a.t.localeCompare(b.t);}).map(function(s){return '<option value="tk:'+esc(s.t)+'">'+esc(s.t)+' · '+esc(short(s.n,40))+'</option>';}).join('')+'</optgroup>';
  $('pl-sel').innerHTML=o;
  $('pl-sel').addEventListener('change',function(){sel=this.value;render();});
  document.querySelectorAll('#pl-ranges button').forEach(function(b){b.addEventListener('click',function(){applyRange(b.dataset.k);});});
  document.querySelectorAll('#pl-mode button').forEach(function(b){b.addEventListener('click',function(){mode=b.dataset.m;render();});});
  ['pl-from','pl-to'].forEach(function(id){$(id).addEventListener('change',function(){setWindowByDates($('pl-from').value,$('pl-to').value);rangeKey='';render();});});
  $('pl-from').min=$('pl-to').min=D[0];$('pl-from').max=$('pl-to').max=D[N-1];
  wireMouse();var rt;window.addEventListener('resize',function(){clearTimeout(rt);rt=setTimeout(render,150);});
  applyRange('1M');
}
if(N>1&&window.Plotly)init();
</script>"""


def render_pl_periodo_page(payload: dict) -> str:
    """Pagina completa. `payload`: {"dates": [...], "series": [{"t","n","tipo","cat","st","total","value","bought","realized","income"}]}."""
    head = ('<!DOCTYPE html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width,initial-scale=1"><title>Andamento</title>' + CSS + _CSS + "</head><body>")
    if len(payload.get("dates") or []) < 2:
        return (head + '<div class="pl"><h1>📈 Andamento</h1><div class="pl-card"><div class="pl-empty">Nessun movimento '
                'registrato: l\'andamento si calcola dagli acquisti e dalle vendite.</div></div></div></body></html>')
    C = resolve_form_colors()
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    colors = json.dumps({"pos": C["emerald-600"], "neg": C["red-600"], "white": C["white"], "text": C["slate-700"],
                         "muted": C["slate-500"], "grid": C["slate-200"], "grid2": C["slate-100"],
                         "buy": C["indigo-600"], "sell": C["amber-500"], "inc": C["slate-600"]})
    legend = "".join(f'<span><i class="mk k-{k}">{ch}</i>{label}</span>' for k, ch, label in (
        ("A", "A", "Acquisto"), ("V", "V", "Vendita"), ("R", "R", "Rimborso a scadenza"), ("C", "€", "Cedola o dividendo"),
        ("T", "•", "Più operazioni vicine")))
    legend = f'<div class="pl-legend">{legend}</div>'
    ranges = "".join(f'<button type="button" data-k="{k}">{k}</button>' for k in ("1S", "1M", "3M", "6M", "YTD", "1A", "Max"))
    body = (
        '<div class="pl"><h1>📈 Andamento</h1>'
        '<div class="pl-card"><div class="pl-top">'
        '<div class="f"><label>Strumento o aggregazione</label><select id="pl-sel"></select></div>'
        '<div class="f"><label>Cosa mostrare</label><div class="seg" id="pl-mode"><button type="button" data-m="pl">P/L</button>'
        '<button type="button" data-m="tr">Total return</button><button type="button" data-m="val">Controvalore</button></div></div>'
        f'<div class="f"><label>Periodo</label><div class="seg" id="pl-ranges">{ranges}</div></div>'
        '<div class="f"><label>Dal</label><input type="date" id="pl-from"></div>'
        '<div class="f"><label>Al</label><input type="date" id="pl-to"></div></div></div>'
        '<div class="pl-card"><div class="pl-name" id="pl-name"></div>'
        '<div class="pl-bigrow"><span class="pl-big" id="pl-big"></span><span class="pl-pct" id="pl-pct"></span></div>'
        '<div class="pl-sub" id="pl-sub"></div>'
        '<div id="pl-wrap"><div id="pl-chart"></div><div class="ov" id="pl-band"></div><div class="ov" id="pl-cross"></div><div class="ov" id="pl-hline"></div>'
        '<div id="pl-marks"></div><div class="ov" id="pl-last"></div><div class="ov" id="pl-ytag"></div>'
        '<div class="ov" id="pl-dot"></div><div class="ov" id="pl-tip"></div></div>'
        + legend +
        '<p class="pl-hint">Muovi il mouse sul grafico per leggere il valore giorno per giorno. Trascina per scegliere un tratto; '
        'doppio clic per tornare a tutto lo storico. Verde = sopra la linea tratteggiata (il punto di partenza), rosso = sotto.</p>'
        '<div class="pl-per" id="pl-per"></div><div id="pl-stats"></div></div></div>'
        f'<script type="application/json" id="pl-data">{data_json}</script>'
        '<script src="/assets/plotly.min.js"></script>'
    )
    return head + body + _JS.replace("__COLORS__", colors) + "</body></html>"
