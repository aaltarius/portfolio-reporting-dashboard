"""ui/form_server/inserisci.py — pagina "Inserisci operazione" del form-server.

Estratto da form_server.py. Condivide la stessa pipeline di storage dell'app
principale: nessuna logica duplicata.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from html import escape

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse

from ui.form_server.shell import CSS, STREAMLIT_URL, safe_f as _safe_f

logger = logging.getLogger("portafoglio.form_server.inserisci")

router = APIRouter()


# ─── Helpers dati ─────────────────────────────────────────────────────────────

def _calc_qty_per_ticker(data: dict) -> dict[str, float]:
    qty: dict[str, float] = {}
    for ev in data.get("registro_eventi", []):
        tk = str(ev.get("ticker", "") or "")
        tipo = str(ev.get("tipo_evento", "") or "").upper()
        q = _safe_f(ev.get("quantita", 0))
        if not tk:
            continue
        if tipo == "ACQUISTO":
            qty[tk] = qty.get(tk, 0.0) + q
        elif tipo in {"VENDITA", "RIMBORSO A SCADENZA"}:
            qty[tk] = qty.get(tk, 0.0) - q
    return {tk: max(v, 0.0) for tk, v in qty.items()}


def _fmt_qty(q: float) -> str:
    if q <= 1e-9:
        return ""
    if abs(q - round(q)) < 1e-6:
        return f"{int(round(q)):,}".replace(",", ".")
    return f"{q:,.4f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _get_tickers_info(data: dict) -> list[dict]:
    from persistence.storage import macro_cat
    from core.validation import _supports_coupon, _supports_dividend, _supports_redemption

    qty_map = _calc_qty_per_ticker(data)
    out = []
    for s in data.get("strumenti", []):
        if s.get("stato", "aperto") == "chiuso":
            continue
        tk = str(s.get("ticker", "") or "")
        nome = str(s.get("nome", tk) or tk)
        tipo = str(s.get("tipo", "") or "")
        q = qty_map.get(tk, 0.0)
        qty_str = f" ({_fmt_qty(q)} quote)" if q > 1e-9 else ""
        out.append({
            "ticker": tk,
            "label": f"{tk}{qty_str} — {nome[:40]}",
            "is_gov": macro_cat(tipo) == "GOV",
            "cedola": bool(_supports_coupon(data, tk)),
            "dividendo": bool(_supports_dividend(data, tk)),
            "rimborso": bool(_supports_redemption(data, tk)),
            "prezzo": _safe_f(s.get("prezzo", 0)),
            "qty": q,
        })
    return out


# ─── HTML ─────────────────────────────────────────────────────────────────────

_JS = """
<script>
const $ = id => document.getElementById(id);
const qv = id => parseFloat($(id)?.value)||0;
const fmtN = (v,d=2)=>v.toLocaleString('it-IT',{minimumFractionDigits:d,maximumFractionDigits:d});
const fmtDateIt = iso => { if(!iso) return ''; const p=String(iso).slice(0,10).split('-'); return p.length===3 ? `${p[2]}/${p[1]}/${p[0]}` : iso; };

const TRADE=['ACQUISTO','VENDITA','RIMBORSO A SCADENZA'];
const PROVENTO=['CEDOLA','DIVIDENDO'];

let cart=[];

/* ── area / evento ─────────────────────────────────────────── */
function getArea(){return document.querySelector('input[name=area]:checked')?.value||'titolo'}
function getEvento(){return $('sel_evento')?.value||''}
function getCalcMode(){return $('sel_calc')?.value||'imp'}

function switchArea(){
  const a=getArea();
  $('sec_titolo').className='section'+(a==='titolo'?' on':'');
  $('sec_liq').className   ='section'+(a==='liquidita'?' on':'');
  if(a==='titolo')switchEvento();
}

function switchEvento(){
  const ev=getEvento();
  const isTrade=TRADE.includes(ev);
  const isProv =PROVENTO.includes(ev);
  $('sec_trade').className   ='section'+(isTrade?' on':'');
  $('sec_provento').className='section'+(isProv ?' on':'');
  $('wrap_autoliq').style.display=ev==='ACQUISTO'?'':'none';
  $('wrap_imposte').style.display=(ev==='VENDITA'||ev==='RIMBORSO A SCADENZA')?'':'none';
  refreshAliquota();
  applyCalcMode();
}

function refreshAliquota(){
  const tk=$('sel_ticker');
  const opt=tk?.options[tk.selectedIndex];
  const isGov=opt?.dataset.gov==='true';
  if($('inp_aliq') && getEvento()==='CEDOLA') $('inp_aliq').value=isGov?12.5:26;
}

/* ── triplet con campo bloccato ─────────────────────────────── */
function applyCalcMode(){
  const mode=getCalcMode();
  // sbloccali tutti prima
  ['inp_qty','inp_prezzo','inp_importo'].forEach(id=>{
    const el=$(id); if(!el)return;
    el.readOnly=false; el.classList.remove('computed');
  });
  // blocca il campo calcolato
  const locked={imp:'inp_importo',pr:'inp_prezzo',qty:'inp_qty'}[mode];
  if(locked){const el=$(locked);if(el){el.readOnly=true;el.classList.add('computed');}}
  calcTriplet();
}

function calcTriplet(){
  const mode=getCalcMode();
  const qty=qv('inp_qty'), pr=qv('inp_prezzo'), imp=qv('inp_importo');
  if(mode==='imp'&&qty>0&&pr>0){
    $('inp_importo').value=(qty*pr).toFixed(2);
  } else if(mode==='pr'&&qty>0&&imp>0){
    $('inp_prezzo').value=(imp/qty).toFixed(4);
  } else if(mode==='qty'&&pr>0&&imp>0){
    $('inp_qty').value=(imp/pr).toFixed(4);
  }
}

function calcProvento(){
  const lordo=qv('inp_lordo'),aliq=qv('inp_aliq');
  const info=$('provento_info');if(!info)return;
  if(lordo>0){
    const imp=lordo*aliq/100;
    info.style.display='';
    info.innerHTML=`Imposta: <b>${fmtN(imp,2)} €</b> &nbsp;·&nbsp; Netto: <b>${fmtN(lordo-imp,2)} €</b>`;
  } else info.style.display='none';
}

/* ── carrello ───────────────────────────────────────────────── */
function addToCart(){
  const area=getArea();
  let item,desc;

  if(area==='titolo'){
    const ticker=$('sel_ticker').value;
    const evento=getEvento();
    const dataVal=$('data_titolo').value;
    if(!dataVal){showErr('Inserisci la data.');return;}

    if(TRADE.includes(evento)){
      const qty=qv('inp_qty'),pr=qv('inp_prezzo'),imp=qv('inp_importo');
      if(qty<=0||pr<=0||imp<=0){showErr('Compila tutti e tre i campi numerici (uno viene calcolato automaticamente).');return;}
      const comm=qv('inp_comm'),tax=qv('inp_imposte');
      const autoLiq=$('chk_auto_liq').checked && evento==='ACQUISTO';
      item={tipo:'trade',ticker,evento,data:dataVal,qty,prezzo:pr,importo:imp,commissioni:comm,imposte:tax,auto_liq:autoLiq,note:$('note_titolo').value};
      const segno=evento==='ACQUISTO'?'-':'+';
      const netto=evento==='ACQUISTO'?-(imp+comm+tax):(imp-comm-tax);
      desc=`<b>${evento}</b> ${ticker} &nbsp;·&nbsp; ${fmtN(qty,4)} × ${fmtN(pr,4)} = <b>${fmtN(imp,2)} €</b>&nbsp;&nbsp;<span style="color:#64748b;font-size:.8rem">netto ${fmtN(netto,2)} €</span>`;
    } else if(PROVENTO.includes(evento)){
      const lordo=qv('inp_lordo'),aliq=qv('inp_aliq');
      if(lordo<=0){showErr('Inserisci un importo lordo.');return;}
      const imp=lordo*aliq/100;
      item={tipo:'provento',ticker,evento,data:dataVal,importo_lordo:lordo,aliquota:aliq,note:$('note_titolo').value};
      desc=`<b>${evento}</b> ${ticker} &nbsp;·&nbsp; lordo <b>${fmtN(lordo,2)} €</b> &nbsp;·&nbsp; netto <b>${fmtN(lordo-imp,2)} €</b>`;
    } else {showErr('Seleziona un tipo di operazione.');return;}
  } else {
    const mov=$('sel_mov').value;
    const dataVal=$('data_liq').value;
    const imp=qv('inp_cash');
    if(!dataVal){showErr('Inserisci la data.');return;}
    if(imp<=0){showErr('Inserisci un importo maggiore di zero.');return;}
    item={tipo:'cash',movimento:mov,data:dataVal,importo:imp,note:$('note_liq').value};
    const segno=mov==='VERSAMENTO'?'+':'-';
    desc=`<b>${mov}</b> &nbsp;·&nbsp; <b>${fmtN(imp,2)} €</b>`;
  }

  item._desc=desc;
  item._date=fmtDateIt(item.data);
  cart.push(item);
  renderCart();
  resetInputs();
  showErr('');
}

function removeFromCart(i){
  cart.splice(i,1);
  renderCart();
}

function renderCart(){
  const tbody=$('cart_body');
  const empty=$('cart_empty');
  const confirmBtn=$('btn_confirm');
  const countEl=$('cart_count');

  const tbl=$('cart_table');
  if(cart.length===0){
    tbody.innerHTML='';
    empty.style.display='';
    if(tbl)tbl.style.display='none';
    confirmBtn.disabled=true;
    if(countEl)countEl.textContent='';
    return;
  }
  empty.style.display='none';
  if(tbl)tbl.style.display='';
  confirmBtn.disabled=false;
  if(countEl)countEl.textContent=`${cart.length} ${cart.length===1?'voce':'voci'}`;

  tbody.innerHTML=cart.map((item,i)=>`
    <tr>
      <td style="color:#94a3b8;width:24px;font-size:.78rem">${i+1}</td>
      <td>${item._desc}</td>
      <td style="color:#94a3b8;font-size:.78rem;white-space:nowrap">${item._date}</td>
      <td><button type="button" class="rm-btn" onclick="removeFromCart(${i})">✕</button></td>
    </tr>`).join('');

  $('cart_data').value=JSON.stringify(cart.map(({_desc,_date,...rest})=>rest));
}

function resetInputs(){
  // quote/prezzo/importo
  ['inp_qty','inp_prezzo','inp_importo'].forEach(id=>{
    const el=$(id);if(el&&!el.readOnly)el.value='';
  });
  // ripristina il campo calcolato (sempre azzerato)
  const locked={imp:'inp_importo',pr:'inp_prezzo',qty:'inp_qty'}[getCalcMode()];
  if(locked)$(locked).value='';
  // provento
  if($('inp_lordo'))$('inp_lordo').value='';
  if($('inp_comm'))$('inp_comm').value='0';
  if($('inp_imposte'))$('inp_imposte').value='0';
  if($('note_titolo'))$('note_titolo').value='';
  if($('note_liq'))$('note_liq').value='';
  if($('inp_cash'))$('inp_cash').value='';
  if($('provento_info'))$('provento_info').style.display='none';
}

function showErr(msg){
  const el=$('err_msg');
  if(!el)return;
  el.textContent=msg;
  el.style.display=msg?'':'none';
}

/* ── init ───────────────────────────────────────────────────── */
document.querySelectorAll('input[name=area]').forEach(r=>r.addEventListener('change',switchArea));
document.addEventListener('DOMContentLoaded',()=>{
  $('sel_evento')?.addEventListener('change',switchEvento);
  $('sel_calc')?.addEventListener('change',applyCalcMode);
  $('sel_ticker')?.addEventListener('change',refreshAliquota);
  ['inp_qty','inp_prezzo'].forEach(id=>$(id)?.addEventListener('input',calcTriplet));
  // inp_importo: calcola solo se non è il campo bloccato
  $('inp_importo')?.addEventListener('input',()=>{if(getCalcMode()!=='imp')calcTriplet();});
  ['inp_lordo','inp_aliq'].forEach(id=>$(id)?.addEventListener('input',calcProvento));
  switchArea();
  renderCart();
});
</script>
"""


def _render_form(tickers: list[dict], error: str = "") -> str:
    today = date.today().isoformat()
    ticker_opts = "\n".join(
        f'<option value="{escape(t["ticker"])}" '
        f'data-gov="{str(t["is_gov"]).lower()}">'
        f'{escape(t["label"])}</option>'
        for t in tickers
    )
    err_html = f'<div class="alert-err" id="err_msg" style="display:{"" if error else "none"}">{escape(error)}</div>' \
        if error else '<div class="alert-err" id="err_msg" style="display:none"></div>'

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Inserisci Operazione</title>
{CSS}
</head>
<body>
<div class="card">
  <h1>📋 Inserisci Operazioni</h1>
  {err_html}
  <form method="POST" action="/operazioni" id="opform" autocomplete="off">
    <input type="hidden" id="cart_data" name="cart_data" value="[]">

    <!-- ── Sezione input ── -->
    <div class="area-group">
      <label><input type="radio" name="area" value="titolo" checked> Titolo</label>
      <label><input type="radio" name="area" value="liquidita"> Liquidità / Costi</label>
    </div>

    <!-- TITOLO -->
    <div id="sec_titolo" class="section">
      <div class="row2" style="margin-top:4px">
        <div>
          <label class="lbl">Strumento</label>
          <select name="_ticker_ui" id="sel_ticker">{ticker_opts}</select>
        </div>
        <div>
          <label class="lbl">Operazione</label>
          <select name="_evento_ui" id="sel_evento">
            <option value="ACQUISTO">ACQUISTO</option>
            <option value="VENDITA">VENDITA</option>
            <option value="CEDOLA">CEDOLA</option>
            <option value="DIVIDENDO">DIVIDENDO</option>
            <option value="RIMBORSO A SCADENZA">RIMBORSO A SCADENZA</option>
          </select>
        </div>
      </div>

      <label class="lbl">Data</label>
      <input type="date" id="data_titolo" name="_data_titolo_ui" value="{today}">

      <!-- trade -->
      <div id="sec_trade" class="section">
        <label class="lbl">Calcola automaticamente</label>
        <select id="sel_calc" name="_calc_ui">
          <option value="imp">Importo € (da Quote × Prezzo)</option>
          <option value="pr">Prezzo (da Quote e Importo €)</option>
          <option value="qty">Quote (da Prezzo e Importo €)</option>
        </select>

        <div class="row3" style="margin-top:12px">
          <div>
            <label class="lbl">Quote</label>
            <input type="number" id="inp_qty" step="0.0001" min="0" placeholder="0.0000">
          </div>
          <div>
            <label class="lbl">Prezzo</label>
            <input type="number" id="inp_prezzo" step="0.0001" min="0" placeholder="0.0000">
          </div>
          <div>
            <label class="lbl">Importo €</label>
            <input type="number" id="inp_importo" step="0.01" min="0" placeholder="auto" class="computed" readonly>
          </div>
        </div>
        <div class="hint">Il campo evidenziato in blu viene calcolato automaticamente.</div>

        <div class="row2" style="margin-top:12px">
          <div>
            <label class="lbl">Commissioni €</label>
            <input type="number" id="inp_comm" step="0.01" min="0" value="0" placeholder="0.00">
          </div>
          <div id="wrap_imposte">
            <label class="lbl">Imposte €</label>
            <input type="number" id="inp_imposte" step="0.01" min="0" value="0" placeholder="0.00">
          </div>
        </div>
        <div id="wrap_autoliq">
          <label class="check-wrap">
            <input type="checkbox" id="chk_auto_liq" checked>
            <span>Registra automaticamente il versamento di cassa (controvalore + commissioni)</span>
          </label>
        </div>
      </div>

      <!-- provento -->
      <div id="sec_provento" class="section">
        <label class="lbl">Importo lordo €</label>
        <input type="number" id="inp_lordo" step="0.01" min="0" placeholder="0.00">
        <label class="lbl">Aliquota imposta %</label>
        <input type="number" id="inp_aliq" step="0.5" min="0" max="100" value="26">
        <div id="provento_info" class="hint" style="display:none;color:#4338ca;margin-top:6px"></div>
      </div>

      <label class="lbl">Note</label>
      <input type="text" id="note_titolo" placeholder="opzionale" maxlength="120">
    </div>

    <!-- LIQUIDITÀ -->
    <div id="sec_liq" class="section">
      <div class="row2" style="margin-top:4px">
        <div>
          <label class="lbl">Movimento</label>
          <select id="sel_mov">
            <option value="VERSAMENTO">VERSAMENTO</option>
            <option value="PRELIEVO">PRELIEVO</option>
            <option value="COMMISSIONE">COMMISSIONE</option>
            <option value="IMPOSTA">IMPOSTA</option>
          </select>
        </div>
        <div>
          <label class="lbl">Data</label>
          <input type="date" id="data_liq" value="{today}">
        </div>
      </div>
      <label class="lbl">Importo €</label>
      <input type="number" id="inp_cash" step="0.01" min="0" placeholder="0.00">
      <label class="lbl">Note</label>
      <input type="text" id="note_liq" placeholder="opzionale" maxlength="120">
    </div>

    <button type="button" class="btn-add" onclick="addToCart()">➕ Aggiungi al carrello</button>

    <!-- ── Carrello ── -->
    <hr class="divider">
    <h2>Carrello <span id="cart_count" class="cart-count"></span></h2>
    <div id="cart_empty" class="cart-empty">Nessuna voce aggiunta — usa il pulsante qui sopra.</div>
    <table class="cart-table" id="cart_table" style="display:none">
      <thead><tr>
        <th>#</th><th>Operazione</th><th>Data</th><th></th>
      </tr></thead>
      <tbody id="cart_body"></tbody>
    </table>

    <button type="submit" class="btn-confirm" id="btn_confirm" disabled>
      ✅ Registra tutto
    </button>
  </form>

  <div class="back-links">
    <a href="{STREAMLIT_URL}" target="_blank">← Torna a Streamlit</a>
    <a href="/operazioni">↺ Nuova sessione</a>
  </div>
</div>
{_JS}
</body>
</html>"""


def _render_success(summary: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Operazioni registrate</title>
{CSS}
</head>
<body>
<div class="card" style="text-align:center;padding-top:36px">
  <div class="success-icon">✅</div>
  <h1 style="margin-bottom:10px">Operazioni registrate</h1>
  <p style="color:#475569;margin:0 0 6px;white-space:pre-line">{escape(summary)}</p>
  <p style="color:#94a3b8;font-size:.82rem;margin-top:12px">
    Streamlit aggiornerà i dati al prossimo click o interazione.
  </p>
  <hr class="divider">
  <div class="back-links" style="justify-content:center">
    <a href="/operazioni">↺ Inserisci altre operazioni</a>
    <a href="{STREAMLIT_URL}" target="_blank">← Torna a Streamlit</a>
  </div>
</div>
</body>
</html>"""


@router.get("/", response_class=HTMLResponse)
@router.get("/operazioni", response_class=HTMLResponse)
async def get_form():
    from persistence.storage import load_data, load_settings, apply_privacy_filter
    try:
        data = apply_privacy_filter(load_data(), load_settings())
        tickers = _get_tickers_info(data)
    except Exception as exc:
        logger.error("Errore caricamento dati: %s", exc)
        tickers = []
    return HTMLResponse(_render_form(tickers))


@router.post("/operazioni", response_class=HTMLResponse)
async def post_form(cart_data: str = Form("[]")):
    from persistence.storage import load_data, save_data, _new_event_id
    from core.finance import append_evento_portafoglio

    def show_error(msg: str):
        from persistence.storage import load_data as _ld, load_settings as _ls, apply_privacy_filter
        try:
            tickers = _get_tickers_info(apply_privacy_filter(_ld(), _ls()))
        except Exception:
            tickers = []
        return HTMLResponse(_render_form(tickers, error=msg))

    try:
        items = json.loads(cart_data)
    except Exception:
        return show_error("Carrello non valido.")

    if not items:
        return show_error("Carrello vuoto — aggiungi almeno una voce prima di confermare.")

    try:
        data = load_data()  # NON filtrato: qui finisce in save_data() più sotto
    except Exception as exc:
        return show_error(f"Impossibile caricare i dati: {exc}")

    TRADE_EV = {"ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA"}
    PROVENTO_EV = {"CEDOLA", "DIVIDENDO"}

    # Valida tutto prima di salvare (tutto o niente)
    events_to_append: list[dict] = []
    summaries: list[str] = []

    for i, item in enumerate(items, 1):
        tipo = str(item.get("tipo", ""))
        try:
            data_str = str(item.get("data", "")).strip()
            data_obj = date.fromisoformat(data_str)

            if tipo == "trade":
                evento = str(item.get("evento", "")).upper()
                ticker = str(item.get("ticker", "")).strip()
                qty_f   = _safe_f(item.get("qty"))
                pr_f    = _safe_f(item.get("prezzo"))
                imp_f   = _safe_f(item.get("importo"))
                comm_f  = _safe_f(item.get("commissioni"))
                tax_f   = _safe_f(item.get("imposte"))
                auto_liq = bool(item.get("auto_liq"))

                if qty_f <= 0 or pr_f <= 0 or imp_f <= 0:
                    raise ValueError("Quote, Prezzo e Importo devono essere tutti maggiori di zero.")
                netto = -(imp_f + comm_f + tax_f) if evento == "ACQUISTO" else (imp_f - comm_f - tax_f)

                if auto_liq and evento == "ACQUISTO":
                    events_to_append.append({
                        "data": str(data_obj),
                        "ticker": "",
                        "tipo_evento": "VERSAMENTO",
                        "importo_lordo": imp_f + comm_f + tax_f,
                        "importo_netto": imp_f + comm_f + tax_f,
                        "note": f"Versamento automatico per acquisto {ticker}",
                    })
                events_to_append.append({
                    "data": str(data_obj),
                    "ticker": ticker,
                    "tipo_evento": evento,
                    "quantita": qty_f,
                    "prezzo_unitario": pr_f,
                    "importo_lordo": imp_f,
                    "commissioni": comm_f,
                    "imposte": tax_f,
                    "importo_netto": netto,
                    "ignore_cash_check": auto_liq,
                    "note": str(item.get("note", "")),
                })
                summaries.append(f"{evento} {ticker}: {qty_f:.4f} × {pr_f:.4f} = {imp_f:.2f} €")

            elif tipo == "provento":
                evento = str(item.get("evento", "")).upper()
                ticker = str(item.get("ticker", "")).strip()
                lordo_f = _safe_f(item.get("importo_lordo"))
                aliq_f  = _safe_f(item.get("aliquota"), 26.0)
                if lordo_f <= 0:
                    raise ValueError("Importo lordo deve essere maggiore di zero.")
                imposte_f = lordo_f * aliq_f / 100.0
                events_to_append.append({
                    "data": str(data_obj),
                    "ticker": ticker,
                    "tipo_evento": evento,
                    "importo_lordo": lordo_f,
                    "imposte": imposte_f,
                    "aliquota": aliq_f / 100.0,
                    "importo_netto": lordo_f - imposte_f,
                    "note": str(item.get("note", "")),
                })
                summaries.append(f"{evento} {ticker}: lordo {lordo_f:.2f} €")

            elif tipo == "cash":
                mov = str(item.get("movimento", "VERSAMENTO")).upper()
                imp_f = _safe_f(item.get("importo"))
                if imp_f <= 0:
                    raise ValueError("Importo deve essere maggiore di zero.")
                netto_cash = imp_f if mov == "VERSAMENTO" else -imp_f
                events_to_append.append({
                    "data": str(data_obj),
                    "ticker": "",
                    "tipo_evento": mov,
                    "importo_lordo": imp_f,
                    "importo_netto": netto_cash,
                    "note": str(item.get("note", "")),
                })
                summaries.append(f"{mov}: {imp_f:.2f} €")

            else:
                raise ValueError(f"Tipo non riconosciuto: {tipo}")

        except ValueError as exc:
            return show_error(f"Voce {i}: {exc}")
        except Exception as exc:
            logger.error("Errore validazione voce %d: %s", i, exc, exc_info=True)
            return show_error(f"Voce {i}: errore interno — {exc}")

    # Salva tutto atomicamente
    try:
        for ev in events_to_append:
            ev["event_id"] = _new_event_id(data)
            append_evento_portafoglio(data, ev)
        save_data(data)
    except ValueError as exc:
        return show_error(str(exc))
    except Exception as exc:
        logger.error("Errore salvataggio carrello: %s", exc, exc_info=True)
        return show_error(f"Errore salvataggio: {exc}")

    count = len([e for e in events_to_append if e.get("tipo_evento") not in {"VERSAMENTO"} or not any(
        x in str(e.get("note", "")) for x in ["automatico"]
    )])
    summary_text = "\n".join(summaries)
    logger.info("Carrello registrato via form server: %d voci\n%s", len(summaries), summary_text)
    return HTMLResponse(_render_success(summary_text))
