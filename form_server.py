"""
form_server.py — Mini-server FastAPI per inserimento operazioni senza rerun Streamlit.

Porta default 8502. Avviato in background da app.py via start_form_server().
Condivide la stessa pipeline di storage dell'app principale: nessuna logica duplicata.
Streamlit rileva le modifiche al JSON tramite StateManager.reload_if_changed() al
successivo rerun (o al click di qualsiasi widget).
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import date
from html import escape
from typing import Optional

try:
    from fastapi import File, UploadFile
    from starlette.requests import Request
except ImportError:
    File = None  # type: ignore[assignment]
    UploadFile = None  # type: ignore[assignment]
    Request = None  # type: ignore[assignment]

logger = logging.getLogger("portafoglio.form_server")

FORM_PORT = 8502
STREAMLIT_URL = "http://localhost:8501"

_started = threading.Event()


# ─── Helpers dati ─────────────────────────────────────────────────────────────

def _safe_f(v, default: float = 0.0) -> float:
    try:
        return float(v or 0)
    except Exception:
        return default


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


# ─── Helpers gestione strumenti/eventi ───────────────────────────────────────

_FS_PORTFOLIO_EVENT_TYPES = {"ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA", "CEDOLA", "DIVIDENDO"}
_FS_CASH_EVENT_TYPES = {"VERSAMENTO", "PRELIEVO", "COMMISSIONE", "IMPOSTA"}


def _fs_rebuild_registers(data: dict) -> None:
    from persistence.storage import get_registro_eventi, _rebuild_cash_ledger_from_events, _safe_float
    rebuilt_op, rebuilt_pr = [], []
    for ev in get_registro_eventi(data):
        tipo = ev.get("tipo_evento")
        if tipo in {"ACQUISTO", "VENDITA"}:
            rebuilt_op.append({
                "data": ev.get("data"),
                "ticker": ev.get("ticker", ""),
                "tipo": tipo,
                "qty": _safe_float(ev.get("quantita", 0)),
                "price": _safe_float(ev.get("prezzo_unitario", 0)),
                "comm": _safe_float(ev.get("commissioni", 0)),
                "note": ev.get("note", ""),
            })
        elif tipo in {"CEDOLA", "DIVIDENDO"}:
            lordo = _safe_float(ev.get("importo_lordo", 0))
            netto = _safe_float(ev.get("importo_netto", 0))
            aliquota = (
                (_safe_float(ev.get("imposte", 0)) / lordo)
                if lordo > 0 else _safe_float(ev.get("aliquota", 0))
            )
            rebuilt_pr.append({
                "data": ev.get("data"),
                "ticker": ev.get("ticker", ""),
                "tipo": tipo,
                "importo_lordo": lordo,
                "aliquota": aliquota,
                "importo_netto": netto,
                "note": ev.get("note", ""),
            })
    data["operazioni"] = rebuilt_op
    data["proventi"] = rebuilt_pr
    data["registro_liquidita"] = _rebuild_cash_ledger_from_events(get_registro_eventi(data))


def _fs_reopen_instruments(data: dict) -> None:
    qty_map: dict = {}
    for ev in data.get("registro_eventi", []):
        tk = str(ev.get("ticker", "") or "")
        tipo = str(ev.get("tipo_evento", "") or "").upper()
        q = float(ev.get("quantita", 0) or 0)
        if not tk:
            continue
        if tipo == "ACQUISTO":
            qty_map[tk] = qty_map.get(tk, 0.0) + q
        elif tipo in {"VENDITA", "RIMBORSO A SCADENZA"}:
            qty_map[tk] = qty_map.get(tk, 0.0) - q
    for s in data.get("strumenti", []):
        tk = str(s.get("ticker", "") or "")
        if s.get("stato") not in {"aperto"} and qty_map.get(tk, 0.0) > 1e-9:
            s["stato"] = "aperto"
            s["data_chiusura"] = None
            s["motivo_chiusura"] = None


def _fs_delete_event(data: dict, event_id: str) -> bool:
    from persistence.storage import _normalize_event_record, save_data
    event_id = str(event_id or "")
    before = len(data.get("registro_eventi", []) or [])
    data["registro_eventi"] = [
        ev for ev in data.get("registro_eventi", [])
        if str(_normalize_event_record(ev).get("event_id", "")) != event_id
    ]
    if len(data.get("registro_eventi", [])) == before:
        return False
    try:
        _fs_rebuild_registers(data)
    except Exception as exc:
        logger.error("_fs_rebuild_registers fallita: %s", exc, exc_info=True)
    try:
        _fs_reopen_instruments(data)
    except Exception as exc:
        logger.error("_fs_reopen_instruments fallita: %s", exc, exc_info=True)
    save_data(data)
    return True


def _fs_update_event(data: dict, event_id: str, updates: dict) -> bool:
    from persistence.storage import _normalize_event_record, _safe_float, save_data
    event_id = str(event_id or "")
    for ev in data.get("registro_eventi", []):
        if str(_normalize_event_record(ev).get("event_id", "")) == event_id:
            ev.update(updates)
            tipo = ev.get("tipo_evento", "")
            if tipo in {"ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA"}:
                lordo = _safe_float(ev.get("quantita", 0)) * _safe_float(ev.get("prezzo_unitario", 0))
                ev["importo_lordo"] = lordo
                comm = _safe_float(ev.get("commissioni", 0))
                imp = _safe_float(ev.get("imposte", 0))
                ev["importo_netto"] = -(lordo + comm + imp) if tipo == "ACQUISTO" else (lordo - comm - imp)
            elif tipo in {"CEDOLA", "DIVIDENDO"}:
                lordo = _safe_float(ev.get("importo_lordo", 0))
                aliquota = _safe_float(ev.get("aliquota", 0))
                ev["imposte"] = lordo * aliquota
                ev["importo_netto"] = lordo - ev["imposte"]
            elif tipo == "VERSAMENTO":
                ev["importo_netto"] = _safe_float(ev.get("importo_lordo", 0))
            elif tipo in {"PRELIEVO", "COMMISSIONE", "IMPOSTA"}:
                ev["importo_netto"] = -_safe_float(ev.get("importo_lordo", 0))
            try:
                _fs_rebuild_registers(data)
            except Exception as exc:
                logger.error("_fs_rebuild_registers fallita: %s", exc, exc_info=True)
            save_data(data)
            return True
    return False


def _fs_linked_events(data: dict, ticker: str) -> list:
    from persistence.storage import get_registro_eventi
    return [ev for ev in get_registro_eventi(data) if str(ev.get("ticker", "") or "") == str(ticker or "")]


def _fs_has_prices(data: dict, ticker: str) -> bool:
    for prices in (data.get("storico_prezzi") or {}).values():
        if isinstance(prices, dict) and ticker in prices:
            return True
    return False


def _fs_delete_instrument(data: dict, ticker: str) -> tuple:
    from persistence.storage import save_data
    linked = _fs_linked_events(data, ticker)
    if linked:
        return False, f"Lo strumento ha {len(linked)} eventi collegati. Elimina prima gli eventi oppure mantieni lo strumento."
    before = len(data.get("strumenti", []) or [])
    data["strumenti"] = [s for s in data.get("strumenti", []) if str(s.get("ticker", "")) != ticker]
    if len(data.get("strumenti", [])) == before:
        return False, "Strumento non trovato."
    for _, prices in (data.get("storico_prezzi") or {}).items():
        if isinstance(prices, dict):
            prices.pop(ticker, None)
    save_data(data)
    return True, "Strumento eliminato."


def _fs_backfill_storico(data: dict, ticker: str, since: str | None = None) -> tuple:
    """Scarica lo storico prezzi completo da Yahoo e lo integra senza sovrascrivere
    le date gia' presenti (vedi core.market_data.backfill_storico_prezzi). Se since
    e' indicato, importa solo dalla data indicata in poi: l'utente decide il
    perimetro invece di ricevere automaticamente tutto cio' che Yahoo restituisce."""
    from persistence.storage import save_data
    from core.market_data import get_yahoo_price_history_full, backfill_storico_prezzi
    from core.formatting import fmt_date_only_it

    history = get_yahoo_price_history_full(ticker)
    if not history:
        return False, f"Nessuno storico disponibile su Yahoo per {ticker}."
    added = backfill_storico_prezzi(data.setdefault("storico_prezzi", {}), ticker, history, since=since)
    save_data(data)
    perimetro = f" dal {fmt_date_only_it(since)} in poi" if since else ""
    if added:
        return True, f"{ticker}: aggiunte {added} date{perimetro} (su {len(history)} disponibili su Yahoo)."
    return True, f"{ticker}: nessuna data mancante{perimetro}."


def _fs_parse_flex_date(value: str) -> str:
    """Converte una data GG/MM/AAAA o YYYY-MM-DD in ISO YYYY-MM-DD. Stringa vuota -> vuota.

    Solleva ValueError (messaggio gia' in italiano) se il formato non e' riconosciuto.
    """
    value = (value or "").strip()
    if not value:
        return ""
    from core.validators import validate_date
    return validate_date(value).isoformat()


def _fs_delete_storico_range(data: dict, ticker: str, date_from: str = "", date_to: str = "") -> tuple:
    """Elimina i prezzi storici salvati per un ticker, opzionalmente limitati a un
    intervallo di date (gia' in formato ISO YYYY-MM-DD). Nessun limite indicato =
    elimina tutto lo storico del ticker."""
    from persistence.storage import save_data
    from core.market_data import delete_storico_prezzi_range
    from core.formatting import fmt_date_only_it

    date_from = date_from.strip()
    date_to = date_to.strip()
    removed = delete_storico_prezzi_range(data.get("storico_prezzi", {}) or {}, ticker, date_from or None, date_to or None)
    if removed == 0:
        return True, f"{ticker}: nessuna data trovata nell'intervallo indicato."
    save_data(data)
    perimetro = f" tra {fmt_date_only_it(date_from) if date_from else '…'} e {fmt_date_only_it(date_to) if date_to else '…'}" if (date_from or date_to) else ""
    return True, f"{ticker}: rimosse {removed} date{perimetro}."


def _fs_is_btp_like(s: dict) -> bool:
    tipo = str(s.get("tipo", "")).strip().lower()
    ticker = str(s.get("ticker", "")).upper()
    return tipo in {"btp", "titolo di stato"} or ticker.startswith("BTP-")


def _fs_event_label(ev: dict) -> str:
    from core.formatting import fmt_date_only_it
    data_str = fmt_date_only_it(str(ev.get("data", "") or "")[:10])
    tipo = ev.get("tipo_evento", "—")
    ticker = ev.get("ticker") or "—"
    netto = _safe_f(ev.get("importo_netto", 0))
    sign = "+" if netto >= 0 else ""
    return f"{data_str} | {tipo} | {ticker} | {sign}{netto:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _fs_fmt_val(v: float, decimals: int = 2) -> str:
    return f"{v:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ─── HTML ─────────────────────────────────────────────────────────────────────

_CSS = """
<style>
*,*::before,*::after{box-sizing:border-box}
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:#f1f5f9;color:#1e293b;margin:0;padding:20px 12px 48px;font-size:.94rem}
.card{background:#fff;border-radius:14px;padding:26px 28px 22px;max-width:720px;margin:0 auto;box-shadow:0 2px 16px rgba(0,0,0,.07)}
h1{font-size:1.15rem;font-weight:800;margin:0 0 20px;color:#1e293b}
h2{font-size:.82rem;font-weight:800;text-transform:uppercase;letter-spacing:.05em;color:#64748b;margin:22px 0 10px}
label.lbl{display:block;font-weight:600;font-size:.8rem;text-transform:uppercase;letter-spacing:.04em;margin:14px 0 4px;color:#64748b}
select,input[type=text],input[type=number],input[type=date]{width:100%;padding:9px 11px;border:1px solid #cbd5e1;border-radius:8px;font-size:.93rem;background:#fff;outline:none;transition:border-color .15s,box-shadow .15s}
select:focus,input:focus{border-color:#6366f1;box-shadow:0 0 0 3px rgba(99,102,241,.12)}
input.computed{background:#eef2ff!important;color:#4338ca!important;cursor:not-allowed}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.row3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}
.area-group{display:flex;gap:20px;margin-bottom:6px}
.area-group label{display:flex;align-items:center;gap:7px;font-weight:600;cursor:pointer;font-size:.93rem}
.area-group input[type=radio]{width:16px;height:16px;accent-color:#6366f1}
.hint{font-size:.76rem;color:#94a3b8;margin-top:4px}
.check-wrap{display:flex;align-items:flex-start;gap:9px;margin-top:14px;cursor:pointer}
.check-wrap input[type=checkbox]{width:17px;height:17px;margin-top:2px;accent-color:#6366f1;flex-shrink:0}
.check-wrap span{font-size:.87rem;color:#334155;line-height:1.4}
.btn-add{display:block;width:100%;padding:11px;background:#6366f1;color:#fff;border:none;border-radius:9px;font-size:.95rem;font-weight:700;cursor:pointer;margin-top:18px;transition:background .15s}
.btn-add:hover{background:#4f46e5}
.btn-confirm{display:block;width:100%;padding:13px;background:#059669;color:#fff;border:none;border-radius:9px;font-size:1rem;font-weight:700;cursor:pointer;margin-top:14px;transition:background .15s}
.btn-confirm:hover{background:#047857}
.btn-confirm:disabled{background:#94a3b8;cursor:not-allowed}
.section{display:none}
.section.on{display:block}
.alert-err{background:#fef2f2;border:1px solid #fca5a5;border-radius:9px;padding:12px 16px;margin-bottom:18px;color:#b91c1c;font-size:.87rem;line-height:1.5}
.cart-empty{text-align:center;color:#94a3b8;font-size:.85rem;padding:16px 0}
.cart-table{width:100%;border-collapse:collapse;font-size:.85rem}
.cart-table th{text-align:left;font-size:.73rem;text-transform:uppercase;letter-spacing:.04em;color:#94a3b8;font-weight:700;padding:0 8px 6px;border-bottom:1px solid #e2e8f0}
.cart-table td{padding:8px 8px;border-bottom:1px solid #f1f5f9;vertical-align:middle}
.cart-table tr:last-child td{border-bottom:none}
.rm-btn{background:none;border:none;color:#ef4444;cursor:pointer;font-size:1.1rem;padding:0 4px;line-height:1}
.rm-btn:hover{color:#b91c1c}
.divider{border:none;border-top:1px solid #e2e8f0;margin:20px 0}
.back-links{margin-top:16px;display:flex;gap:20px}
.back-links a{color:#6366f1;text-decoration:none;font-weight:600;font-size:.88rem}
.back-links a:hover{text-decoration:underline}
.success-icon{font-size:2.5rem;margin-bottom:10px}
.cart-count{font-size:.78rem;font-weight:700;color:#6366f1;float:right;margin-top:2px}
.tabs{display:flex;gap:2px;border-bottom:2px solid #e2e8f0;margin-bottom:20px;margin-top:4px}
.tab-btn{background:none;border:none;border-bottom:3px solid transparent;margin-bottom:-2px;padding:8px 14px;font-size:.87rem;font-weight:600;color:#64748b;cursor:pointer;transition:color .15s,border-color .15s}
.tab-btn.active{color:#6366f1;border-bottom-color:#6366f1}
.tab-panel{display:none}
.tab-panel.active{display:block}
.preview-box{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:12px 16px;margin:10px 0 14px;font-size:.85rem;line-height:1.6}
.preview-box .prow{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;font-size:.82rem}
.preview-box .plbl{color:#64748b;font-size:.70rem;font-weight:800;text-transform:uppercase;margin-bottom:2px}
.preview-box .pval{font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.preview-details{font-size:.82rem;margin-top:10px;border-top:1px solid #e2e8f0;padding-top:10px}
.preview-details .dr{display:flex;gap:8px;padding:3px 0}
.preview-details .dk{color:#64748b;font-size:.75rem;width:110px;flex-shrink:0}
.preview-details .dv{color:#1e293b}
.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:14px 0}
.metric{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;text-align:center}
.metric-lbl{font-size:.70rem;text-transform:uppercase;letter-spacing:.04em;color:#94a3b8;font-weight:700;margin-bottom:4px}
.metric-val{font-size:.95rem;font-weight:800;color:#1e293b}
.alert-warn{background:#fffbeb;border:1px solid #fcd34d;border-radius:8px;padding:11px 16px;color:#92400e;font-size:.87rem;margin-bottom:14px}
.alert-ok{background:#f0fdf4;border:1px solid #86efac;border-radius:8px;padding:11px 16px;color:#166534;font-size:.87rem;margin-bottom:14px}
.btp-fields{display:none;background:#f0f9ff;border:1px solid #bae6fd;border-radius:8px;padding:16px;margin-top:12px}
.btp-fields.on{display:block}
.table-simple{width:100%;border-collapse:collapse;font-size:.84rem}
.table-simple th{text-align:left;font-size:.71rem;text-transform:uppercase;color:#94a3b8;font-weight:700;padding:0 8px 8px;border-bottom:1px solid #e2e8f0}
.table-simple td{padding:8px;border-bottom:1px solid #f1f5f9;color:#334155}
.table-simple tr:last-child td{border-bottom:none}
.btn-danger{display:block;width:100%;padding:13px;background:#dc2626;color:#fff;border:none;border-radius:9px;font-size:1rem;font-weight:700;cursor:pointer;margin-top:14px;transition:background .15s}
.btn-danger:hover{background:#b91c1c}
.btn-danger:disabled{background:#94a3b8;cursor:not-allowed}
.edit-section{display:none}
.edit-section.on{display:block}
</style>
"""

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
{_CSS}
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
{_CSS}
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


# ─── Render: Strumenti ───────────────────────────────────────────────────────

_TAB_JS = """
<script>
function switchTab(g,n){
  document.querySelectorAll('[data-tg="'+g+'"]').forEach(b=>b.classList.toggle('active',b.dataset.t===n));
  document.querySelectorAll('[data-pg="'+g+'"]').forEach(p=>p.classList.toggle('active',p.dataset.p===n));
}
</script>"""


def _render_strumenti_page(data: dict, ok_msg: str = "", err_msg: str = "", active_tab: str = "add") -> str:
    strumenti = data.get("strumenti", [])
    chiusi = [s for s in strumenti if s.get("stato", "aperto") == "chiuso"]

    from persistence.storage import get_registro_eventi
    from core.formatting import fmt_date_only_it
    ev_all = get_registro_eventi(data)
    linked_counts: dict = {}
    for ev in ev_all:
        tk = str(ev.get("ticker", "") or "")
        if tk:
            linked_counts[tk] = linked_counts.get(tk, 0) + 1

    def _it_date_or_empty(value) -> str:
        return fmt_date_only_it(value) if value else ""

    strumenti_js = json.dumps([{
        "ticker": s.get("ticker", ""),
        "nome": s.get("nome", ""),
        "tipo": s.get("tipo", ""),
        "is_btp": _fs_is_btp_like(s),
        "scadenza": _it_date_or_empty(s.get("scadenza")),
        "data_acquisto": _it_date_or_empty(s.get("data_acquisto")),
        "prima_cedola": _it_date_or_empty(s.get("prima_cedola") or s.get("data_origine")),
        "cedola_perc": float(s.get("cedola_perc", 0.0) or 0.0),
        "cedola_frequenza": str(s.get("cedola_frequenza", "annuale") or "annuale"),
        "aliquota_cedola": float(s.get("aliquota_cedola", 12.5) or 12.5),
        "nominale": float(s.get("nominale", 100.0) or 100.0),
        "linked": linked_counts.get(s.get("ticker", ""), 0),
        "has_prices": _fs_has_prices(data, s.get("ticker", "")),
    } for s in strumenti], ensure_ascii=False)

    def _tb(label: str, key: str) -> str:
        cls = "tab-btn active" if active_tab == key else "tab-btn"
        return f'<button class="{cls}" data-tg="str" data-t="{key}" onclick="switchTab(\'str\',\'{key}\')">{escape(label)}</button>'

    def _tp(key: str, content: str) -> str:
        cls = "tab-panel active" if active_tab == key else "tab-panel"
        return f'<div class="{cls}" data-pg="str" data-p="{key}">{content}</div>'

    str_opts = "\n".join(
        f'<option value="{escape(s.get("ticker",""))}">{escape(s.get("ticker",""))} — {escape(str(s.get("nome",""))[:45])}</option>'
        for s in strumenti
    )

    from core.market_data import earliest_storico_date

    _tickers_for_count = {s.get("ticker", "") for s in strumenti}
    date_count_by_ticker: dict = dict.fromkeys(_tickers_for_count, 0)
    first_date_by_ticker: dict = {}
    for _day_date, _day_prices in (data.get("storico_prezzi") or {}).items():
        if isinstance(_day_prices, dict):
            for _tk in _day_prices:
                if _tk in date_count_by_ticker:
                    date_count_by_ticker[_tk] += 1
                    if _tk not in first_date_by_ticker or _day_date < first_date_by_ticker[_tk]:
                        first_date_by_ticker[_tk] = _day_date

    storico_opts = "\n".join(
        f'<option value="{escape(s.get("ticker",""))}">{escape(s.get("ticker",""))} — {escape(str(s.get("nome",""))[:35])} '
        f'({date_count_by_ticker.get(s.get("ticker",""), 0)} date, dal {fmt_date_only_it(first_date_by_ticker.get(s.get("ticker",""))) if s.get("ticker","") in first_date_by_ticker else "n/d"})</option>'
        for s in strumenti
    )

    _suggested_since_iso = earliest_storico_date(data.get("storico_prezzi") or {}) or ""
    _suggested_since = fmt_date_only_it(_suggested_since_iso) if _suggested_since_iso else ""

    if chiusi:
        rows = "".join(
            f'<tr><td>{escape(s.get("ticker",""))}</td><td>{escape(str(s.get("nome",""))[:45])}</td>'
            f'<td>{escape(str(s.get("tipo","")))}</td><td>{escape(fmt_date_only_it(s.get("data_chiusura")) if s.get("data_chiusura") else "—")}</td>'
            f'<td>{escape(str(s.get("motivo_chiusura","") or ""))}</td></tr>'
            for s in chiusi
        )
        chiusi_html = (
            '<table class="table-simple"><thead><tr>'
            '<th>Ticker</th><th>Nome</th><th>Tipo</th><th>Chiuso il</th><th>Motivo</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>'
        )
    else:
        chiusi_html = '<div class="cart-empty">Nessuno strumento chiuso.</div>'

    feedback = ""
    if ok_msg:
        feedback = f'<div class="alert-ok">{escape(ok_msg)}</div>'
    elif err_msg:
        feedback = f'<div class="alert-err" style="display:block">{escape(err_msg)}</div>'

    no_str = '<div class="cart-empty">Nessuno strumento presente.</div>'

    tab_add = """
    <form method="POST" action="/strumenti" autocomplete="off">
      <input type="hidden" name="azione" value="aggiungi">
      <label class="lbl">ISIN</label>
      <input type="text" name="isin" maxlength="12" placeholder="IT0001234567" style="text-transform:uppercase">
      <label class="lbl">Ticker manuale/opzionale</label>
      <input type="text" name="ticker_hint" placeholder="opzionale">
      <div class="hint">Per i BTP puoi completare o correggere scadenza, cedola e date nella scheda Modifica subito dopo l'inserimento.</div>
      <button type="submit" class="btn-confirm" style="margin-top:20px">🔍 Cerca e aggiungi</button>
    </form>"""

    tab_edit = no_str if not strumenti else f"""
    <label class="lbl">Strumento</label>
    <select id="sel_edit" onchange="loadEdit()">
      {str_opts}
    </select>
    <form method="POST" action="/strumenti" id="edit_form" autocomplete="off" style="margin-top:14px">
      <input type="hidden" name="azione" value="modifica">
      <input type="hidden" id="edit_orig_ticker" name="ticker">
      <label class="lbl">Denominazione</label>
      <input type="text" id="edit_nome" name="nome">
      <label class="lbl">Tipologia</label>
      <input type="text" id="edit_tipo" name="tipo">
      <label class="lbl">Ticker</label>
      <input type="text" id="edit_ticker_new" name="ticker_new">
      <div id="btp_fields" class="btp-fields">
        <div class="hint" style="margin-bottom:10px">Dati BTP usati per timeline, cedole e scadenza.</div>
        <div class="row2">
          <div><label class="lbl">Scadenza (GG/MM/AAAA)</label><input type="text" id="edit_scadenza" name="scadenza" placeholder="01/08/2026"></div>
          <div><label class="lbl">Data acquisto (GG/MM/AAAA)</label><input type="text" id="edit_data_acquisto" name="data_acquisto" placeholder="01/01/2025"></div>
        </div>
        <div class="row2">
          <div><label class="lbl">Prima cedola (GG/MM/AAAA)</label><input type="text" id="edit_prima_cedola" name="prima_cedola" placeholder="01/08/2025"></div>
          <div><label class="lbl">Cedola % annua</label><input type="number" id="edit_cedola_perc" name="cedola_perc" step="0.05" min="0" placeholder="0.00"></div>
        </div>
        <div class="row3">
          <div><label class="lbl">Frequenza cedola</label>
            <select id="edit_cedola_freq" name="cedola_frequenza">
              <option value="annuale">annuale</option>
              <option value="semestrale">semestrale</option>
              <option value="trimestrale">trimestrale</option>
            </select>
          </div>
          <div><label class="lbl">Aliquota cedola %</label><input type="number" id="edit_aliq_ced" name="aliquota_cedola" step="0.5" min="0" max="100" placeholder="12.5"></div>
          <div><label class="lbl">Nominale per quota</label><input type="number" id="edit_nominale" name="nominale" step="1" min="0" placeholder="100"></div>
        </div>
      </div>
      <button type="submit" class="btn-confirm" style="margin-top:18px">💾 Salva modifiche</button>
    </form>"""

    tab_del = no_str if not strumenti else f"""
    <label class="lbl">Strumento da eliminare</label>
    <select id="sel_del" onchange="loadDel()">
      {str_opts}
    </select>
    <div id="del_metrics" class="metrics" style="margin-top:14px"></div>
    <div id="del_warn" class="alert-warn" style="display:none">Eliminazione bloccata: sono presenti eventi collegati. Elimina prima operazioni/proventi/movimenti riferiti a questo ticker.</div>
    <div id="del_form_wrap">
      <form method="POST" action="/strumenti" autocomplete="off">
        <input type="hidden" name="azione" value="elimina">
        <input type="hidden" id="del_ticker_inp" name="ticker">
        <label class="check-wrap" style="margin-top:14px">
          <input type="checkbox" id="del_confirm_chk" onchange="toggleDel()">
          <span>Confermo l'eliminazione dello strumento selezionato</span>
        </label>
        <button type="submit" class="btn-danger" id="del_btn" disabled>🗑️ Elimina strumento</button>
      </form>
    </div>"""

    tab_storico = no_str if not strumenti else f"""
    <h2>Recupera storico</h2>
    <div class="hint" style="margin-bottom:14px">Per strumenti con storico prezzi troppo corto (es. aggiunti di recente): scarica da Yahoo Finance e integra senza sovrascrivere le date gia' salvate. La data di partenza e' proposta in base a cio' che il sistema ha gia' per gli altri strumenti — modificala se vuoi un perimetro diverso, o svuotala per importare tutto cio' che Yahoo ha disponibile.</div>
    <form method="POST" action="/strumenti" autocomplete="off">
      <input type="hidden" name="azione" value="recupera_storico">
      <label class="lbl">Strumento</label>
      <select name="ticker">
        {storico_opts}
      </select>
      <label class="lbl">Data di partenza (GG/MM/AAAA, opzionale)</label>
      <input type="text" name="storico_data_da" value="{escape(_suggested_since)}" placeholder="es. 30/05/2023">
      <button type="submit" class="btn-confirm" style="margin-top:18px">⬇ Recupera storico</button>
    </form>

    <h2 style="margin-top:26px">Elimina storico salvato</h2>
    <div class="hint" style="margin-bottom:14px">Rimuove i prezzi salvati per uno strumento, per intero o solo in un intervallo di date. Lascia entrambe le date vuote per eliminare tutto lo storico dello strumento.</div>
    <form method="POST" action="/strumenti" autocomplete="off">
      <input type="hidden" name="azione" value="elimina_storico">
      <label class="lbl">Strumento</label>
      <select name="ticker">
        {storico_opts}
      </select>
      <div class="row2">
        <div><label class="lbl">Da (GG/MM/AAAA, opzionale)</label><input type="text" name="storico_data_da" placeholder="lascia vuoto = dall'inizio"></div>
        <div><label class="lbl">A (GG/MM/AAAA, opzionale)</label><input type="text" name="storico_data_a" placeholder="lascia vuoto = fino alla fine"></div>
      </div>
      <label class="check-wrap" style="margin-top:14px">
        <input type="checkbox" required>
        <span>Confermo l'eliminazione dello storico prezzi selezionato</span>
      </label>
      <button type="submit" class="btn-danger" style="margin-top:14px">🗑️ Elimina storico</button>
    </form>"""

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Strumenti</title>
{_CSS}
</head>
<body>
<div class="card">
  <h1>📌 Strumenti</h1>
  <p style="color:#64748b;font-size:.82rem;margin:-10px 0 16px">Gestisci l'anagrafica degli strumenti da un unico punto. Le eliminazioni sono protette se esistono eventi collegati.</p>
  {feedback}
  <div class="tabs">
    {_tb("➕ Aggiungi","add")}
    {_tb("✏️ Modifica","edit")}
    {_tb("🗑️ Elimina","del")}
    {_tb("📈 Storico","storico")}
    {_tb("📁 Chiusi","closed")}
  </div>
  {_tp("add", tab_add)}
  {_tp("edit", tab_edit)}
  {_tp("del", tab_del)}
  {_tp("storico", tab_storico)}
  {_tp("closed", chiusi_html)}
  <div class="back-links"><a href="{STREAMLIT_URL}" target="_blank">← Torna a Streamlit</a></div>
</div>
{_TAB_JS}
<script>
const strumenti={strumenti_js};
function loadEdit(){{
  const tk=document.getElementById('sel_edit')?.value;
  const s=strumenti.find(x=>x.ticker===tk);
  if(!s)return;
  const set=(id,v)=>{{const el=document.getElementById(id);if(el)el.value=v??'';}}
  set('edit_orig_ticker',s.ticker);
  set('edit_nome',s.nome);
  set('edit_tipo',s.tipo);
  set('edit_ticker_new',s.ticker);
  const btp=document.getElementById('btp_fields');
  if(btp)btp.className='btp-fields'+(s.is_btp?' on':'');
  if(s.is_btp){{
    set('edit_scadenza',s.scadenza);
    set('edit_data_acquisto',s.data_acquisto);
    set('edit_prima_cedola',s.prima_cedola);
    set('edit_cedola_perc',s.cedola_perc);
    set('edit_aliq_ced',s.aliquota_cedola);
    set('edit_nominale',s.nominale);
    const fr=document.getElementById('edit_cedola_freq');
    if(fr)[...fr.options].forEach(o=>o.selected=(o.value===s.cedola_frequenza));
  }}
}}
function loadDel(){{
  const tk=document.getElementById('sel_del')?.value;
  const s=strumenti.find(x=>x.ticker===tk);
  if(!s)return;
  const m=document.getElementById('del_metrics');
  if(m)m.innerHTML=`
    <div class="metric"><div class="metric-lbl">Eventi collegati</div><div class="metric-val">${{s.linked}}</div></div>
    <div class="metric"><div class="metric-lbl">Storico prezzi</div><div class="metric-val">${{s.has_prices?'sì':'no'}}</div></div>
    <div class="metric"><div class="metric-lbl">Stato</div><div class="metric-val">${{s.linked?'bloccato':'eliminabile'}}</div></div>`;
  document.getElementById('del_warn').style.display=s.linked?'':'none';
  document.getElementById('del_form_wrap').style.display=s.linked?'none':'';
  document.getElementById('del_ticker_inp').value=s.ticker;
  const chk=document.getElementById('del_confirm_chk');if(chk)chk.checked=false;
  toggleDel();
}}
function toggleDel(){{
  const chk=document.getElementById('del_confirm_chk')?.checked;
  const btn=document.getElementById('del_btn');if(btn)btn.disabled=!chk;
}}
document.addEventListener('DOMContentLoaded',()=>{{loadEdit();loadDel();}});
</script>
</body>
</html>"""


# ─── Render: Operazioni gestione / Liquidità gestione ────────────────────────

def _render_eventi_page(
    data: dict,
    event_types: set,
    title: str,
    route: str,
    ok_msg: str = "",
    err_msg: str = "",
    active_tab: str = "edit",
) -> str:
    from persistence.storage import get_registro_eventi, _safe_float

    eventi = [ev for ev in get_registro_eventi(data) if ev.get("tipo_evento") in event_types]

    feedback = ""
    if ok_msg:
        feedback = f'<div class="alert-ok">{escape(ok_msg)}</div>'
    elif err_msg:
        feedback = f'<div class="alert-err" style="display:block">{escape(err_msg)}</div>'

    if not eventi:
        return f"""<!DOCTYPE html>
<html lang="it"><head><meta charset="utf-8"><title>{escape(title)}</title>{_CSS}</head>
<body><div class="card"><h1>{escape(title)}</h1>{feedback}
<div class="cart-empty" style="padding:30px 0">Nessun evento da gestire.</div>
<div class="back-links"><a href="{STREAMLIT_URL}" target="_blank">← Torna a Streamlit</a></div>
</div></body></html>"""

    eventi_js = json.dumps([{
        "event_id": ev.get("event_id", ""),
        "tipo": ev.get("tipo_evento", ""),
        "ticker": ev.get("ticker") or "",
        "data": str(ev.get("data", "") or "")[:10],
        "quantita": float(_safe_float(ev.get("quantita", 0))),
        "prezzo_unitario": float(_safe_float(ev.get("prezzo_unitario", 0))),
        "importo_lordo": float(_safe_float(ev.get("importo_lordo", 0))),
        "commissioni": float(_safe_float(ev.get("commissioni", 0))),
        "imposte": float(_safe_float(ev.get("imposte", 0))),
        "aliquota": float(_safe_float(ev.get("aliquota", 0)) * 100),
        "importo_netto": float(_safe_float(ev.get("importo_netto", 0))),
        "note": str(ev.get("note", "") or ""),
    } for ev in eventi], ensure_ascii=False)

    ev_opts = "\n".join(
        f'<option value="{escape(ev.get("event_id",""))}">{escape(_fs_event_label(ev))}</option>'
        for ev in eventi
    )

    def _tb(label: str, key: str) -> str:
        cls = "tab-btn active" if active_tab == key else "tab-btn"
        return f'<button class="{cls}" data-tg="ev" data-t="{key}" onclick="switchTab(\'ev\',\'{key}\')">{escape(label)}</button>'

    def _tp(key: str, content: str) -> str:
        cls = "tab-panel active" if active_tab == key else "tab-panel"
        return f'<div class="{cls}" data-pg="ev" data-p="{key}">{content}</div>'

    # Edit tab — campi variano per tipo evento
    TRADE = {"ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA"}
    PROVENTO = {"CEDOLA", "DIVIDENDO"}
    CASH = {"VERSAMENTO", "PRELIEVO", "COMMISSIONE", "IMPOSTA"}

    # Sezioni edit condizionali (visibili via JS)
    edit_trade = """
    <div class="row2" style="margin-top:10px">
      <div><label class="lbl">Qtà</label><input type="number" id="e_qty" name="quantita" step="0.0001" min="0" placeholder="0.0000"></div>
      <div><label class="lbl">Prezzo €</label><input type="number" id="e_pr" name="prezzo_unitario" step="0.0001" min="0" placeholder="0.0000"></div>
    </div>
    <div class="row2">
      <div><label class="lbl">Commissioni €</label><input type="number" id="e_comm" name="commissioni" step="0.01" min="0" placeholder="0.00"></div>
      <div id="e_imp_wrap"><label class="lbl">Imposte €</label><input type="number" id="e_imp" name="imposte" step="0.01" min="0" placeholder="0.00"></div>
    </div>"""

    edit_provento = """
    <div class="row2" style="margin-top:10px">
      <div><label class="lbl">Importo lordo €</label><input type="number" id="e_lordo" name="importo_lordo" step="0.01" min="0" placeholder="0.00"></div>
      <div><label class="lbl">Aliquota %</label><input type="number" id="e_aliq" name="aliquota_perc" step="0.5" min="0" max="100" placeholder="26.0"></div>
    </div>"""

    edit_cash = """
    <div style="margin-top:10px">
      <label class="lbl">Importo €</label>
      <input type="number" id="e_cash" name="importo_lordo" step="0.01" min="0" placeholder="0.00">
    </div>"""

    tab_edit = f"""
    <form method="POST" action="/{route}" autocomplete="off">
      <input type="hidden" name="azione" value="modifica">
      <input type="hidden" id="e_id" name="event_id">
      <label class="lbl">Data</label>
      <input type="date" id="e_data" name="data">
      <div id="es_trade" class="edit-section">{edit_trade}</div>
      <div id="es_provento" class="edit-section">{edit_provento}</div>
      <div id="es_cash" class="edit-section">{edit_cash}</div>
      <label class="lbl" style="margin-top:12px">Note</label>
      <input type="text" id="e_note" name="note" maxlength="120" placeholder="opzionale">
      <button type="submit" class="btn-confirm" style="margin-top:18px">💾 Salva modifiche</button>
    </form>"""

    tab_del = f"""
    <label class="check-wrap" style="margin-top:8px">
      <input type="checkbox" id="del_chk" onchange="toggleDelEv()">
      <span>Confermo l'eliminazione definitiva dell'evento selezionato</span>
    </label>
    <form method="POST" action="/{route}" autocomplete="off">
      <input type="hidden" name="azione" value="elimina">
      <input type="hidden" id="del_ev_id" name="event_id">
      <button type="submit" class="btn-danger" id="del_ev_btn" disabled>🗑️ Elimina evento</button>
    </form>"""

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
{_CSS}
</head>
<body>
<div class="card">
  <h1>{escape(title)}</h1>
  {feedback}
  <label class="lbl">Seleziona evento</label>
  <select id="sel_ev" onchange="loadEv()">
    {ev_opts}
  </select>
  <div id="ev_preview" class="preview-box" style="margin-top:12px"></div>
  <div class="tabs" style="margin-top:16px">
    {_tb("✏️ Modifica","edit")}
    {_tb("🗑️ Elimina","del")}
  </div>
  {_tp("edit", tab_edit)}
  {_tp("del", tab_del)}
  <div class="back-links"><a href="{STREAMLIT_URL}" target="_blank">← Torna a Streamlit</a></div>
</div>
{_TAB_JS}
<script>
const eventi={eventi_js};
const fv=(v,d=2)=>v.toLocaleString('it-IT',{{minimumFractionDigits:d,maximumFractionDigits:d}});
const fmtDateIt=iso=>{{if(!iso)return ''; const p=String(iso).slice(0,10).split('-'); return p.length===3?`${{p[2]}}/${{p[1]}}/${{p[0]}}`:iso;}};
const TRADE=new Set(['ACQUISTO','VENDITA','RIMBORSO A SCADENZA']);
const PROVENTO=new Set(['CEDOLA','DIVIDENDO']);

function loadEv(){{
  const id=document.getElementById('sel_ev')?.value;
  const ev=eventi.find(x=>x.event_id===id);
  if(!ev)return;

  // preview
  const sign=ev.importo_netto>=0?'+':'';
  document.getElementById('ev_preview').innerHTML=`
    <div class="prow">
      <div><div class="plbl">Data</div><div class="pval">${{fmtDateIt(ev.data)}}</div></div>
      <div><div class="plbl">Evento</div><div class="pval">${{ev.tipo}}</div></div>
      <div><div class="plbl">Ticker</div><div class="pval">${{ev.ticker||'—'}}</div></div>
      <div><div class="plbl">Netto</div><div class="pval">${{sign}}${{fv(ev.importo_netto,2)}} €</div></div>
    </div>
    <div class="preview-details">
      ${{ev.quantita>0?`<div class="dr"><div class="dk">Quantità</div><div class="dv">${{fv(ev.quantita,4)}}</div></div>`:''}}
      ${{ev.prezzo_unitario>0?`<div class="dr"><div class="dk">Prezzo</div><div class="dv">${{fv(ev.prezzo_unitario,4)}} €</div></div>`:''}}
      ${{ev.importo_lordo>0?`<div class="dr"><div class="dk">Lordo</div><div class="dv">${{fv(ev.importo_lordo,2)}} €</div></div>`:''}}
      ${{ev.commissioni>0?`<div class="dr"><div class="dk">Commissioni</div><div class="dv">${{fv(ev.commissioni,2)}} €</div></div>`:''}}
      ${{ev.imposte>0?`<div class="dr"><div class="dk">Imposte</div><div class="dv">${{fv(ev.imposte,2)}} €</div></div>`:''}}
      ${{ev.note?`<div class="dr"><div class="dk">Note</div><div class="dv">${{ev.note}}</div></div>`:''}}
      <div class="dr"><div class="dk">ID evento</div><div class="dv" style="font-size:.75rem;color:#94a3b8">${{ev.event_id}}</div></div>
    </div>`;

  // edit form populate
  const s=(id,v)=>{{const el=document.getElementById(id);if(el)el.value=v??'';}}
  s('e_id',ev.event_id); s('e_data',ev.data); s('e_note',ev.note);
  const isTrade=TRADE.has(ev.tipo), isProv=PROVENTO.has(ev.tipo);
  document.getElementById('es_trade').className='edit-section'+(isTrade?' on':'');
  document.getElementById('es_provento').className='edit-section'+(isProv?' on':'');
  document.getElementById('es_cash').className='edit-section'+(!isTrade&&!isProv?' on':'');
  if(isTrade){{
    s('e_qty',ev.quantita); s('e_pr',ev.prezzo_unitario);
    s('e_comm',ev.commissioni); s('e_imp',ev.imposte);
    document.getElementById('e_imp_wrap').style.display=ev.tipo==='ACQUISTO'?'none':'';
  }} else if(isProv){{
    s('e_lordo',ev.importo_lordo); s('e_aliq',ev.aliquota);
  }} else {{
    s('e_cash',ev.importo_lordo);
  }}

  // delete form
  s('del_ev_id',ev.event_id);
  const chk=document.getElementById('del_chk');if(chk)chk.checked=false;
  toggleDelEv();
}}

function toggleDelEv(){{
  const chk=document.getElementById('del_chk')?.checked;
  const btn=document.getElementById('del_ev_btn');if(btn)btn.disabled=!chk;
}}

document.addEventListener('DOMContentLoaded',loadEv);
</script>
</body>
</html>"""


# ─── Render: Privacy ─────────────────────────────────────────────────────────

def _render_privacy_page(data: dict, settings: dict, ok_msg: str = "", err_msg: str = "") -> str:
    pm = (settings or {}).get("privacy_mode", {}) or {}
    enabled = bool(pm.get("enabled", False))
    hidden_tickers = set(str(t) for t in (pm.get("hidden_tickers") or []))
    hidden_categories = set(str(c) for c in (pm.get("hidden_categories") or []))

    strumenti = [s for s in (data.get("strumenti") or []) if s.get("ticker")]
    all_types = sorted({str(s.get("tipo") or "") for s in strumenti if s.get("tipo")})

    ok_html = f'<div style="background:#f0fdf4;border:1px solid #86efac;border-radius:9px;padding:10px 14px;margin-bottom:14px;color:#166534;font-size:.87rem">✓ {escape(ok_msg)}</div>' if ok_msg else ""
    err_html = f'<div class="alert-err">✗ {escape(err_msg)}</div>' if err_msg else ""

    instr_rows = ""
    for s in strumenti:
        tk = str(s.get("ticker") or "")
        nome = str(s.get("nome") or tk)
        tipo = str(s.get("tipo") or "")
        chk = "checked" if tk in hidden_tickers else ""
        instr_rows += (
            f'<label style="display:flex;align-items:flex-start;gap:10px;padding:7px 0;'
            f'border-bottom:1px solid #f1f5f9;cursor:pointer">'
            f'<input type="checkbox" name="hidden_tickers" value="{escape(tk)}" {chk} '
            f'style="margin-top:3px;width:15px;height:15px;flex-shrink:0">'
            f'<span style="font-size:.87rem;color:#334155">{escape(tk)}'
            f'<span style="color:#94a3b8"> — {escape(nome)}</span>'
            f'<span style="color:#cbd5e1;font-size:.8rem"> ({escape(tipo)})</span></span></label>\n'
        )

    cat_rows = ""
    for tipo in all_types:
        chk = "checked" if tipo in hidden_categories else ""
        count = sum(1 for s in strumenti if str(s.get("tipo") or "") == tipo)
        cat_rows += (
            f'<label style="display:flex;align-items:center;gap:10px;padding:8px 0;'
            f'border-bottom:1px solid #f1f5f9;cursor:pointer">'
            f'<input type="checkbox" name="hidden_categories" value="{escape(tipo)}" {chk} '
            f'style="width:15px;height:15px;flex-shrink:0">'
            f'<span style="font-size:.87rem;color:#334155;font-weight:600">{escape(tipo)}'
            f'<span style="color:#94a3b8;font-weight:400"> — {count} strument{"o" if count==1 else "i"}</span>'
            f'</span></label>\n'
        )

    enabled_chk = "checked" if enabled else ""
    active_badge = (
        ' <span style="background:#ef4444;color:#fff;padding:2px 10px;border-radius:6px;'
        'font-size:.78rem;font-weight:700;vertical-align:middle">ATTIVA</span>'
        if enabled else ""
    )
    section_title = (
        'style="font-size:.78rem;font-weight:700;color:#64748b;text-transform:uppercase;'
        'letter-spacing:.05em;margin:20px 0 8px"'
    )

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Modalità Privacy</title>
{_CSS}
</head>
<body>
<div class="card">
  <h1>🔒 Modalità Privacy{active_badge}</h1>
  <p style="color:#64748b;font-size:.88rem;margin:0 0 16px">Nascondi temporaneamente strumenti o categorie dal portafoglio visualizzato. I dati restano invariati su disco — la visibilità cambia solo nella dashboard, subito dopo aver ricaricato.</p>
  {ok_html}{err_html}
  <form method="post" action="/privacy">
    <label style="display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:2px solid #e2e8f0;margin-bottom:16px;cursor:pointer">
      <input type="checkbox" name="enabled" value="1" id="chk_en" {enabled_chk} style="width:18px;height:18px">
      <span style="font-weight:700;font-size:1rem;color:#1e293b">Modalità privacy attiva</span>
    </label>
    <p {section_title}>Nascondi per categoria (intera famiglia)</p>
    {cat_rows or '<p style="color:#94a3b8;font-size:.85rem">Nessuna categoria disponibile.</p>'}
    <p {section_title}>Nascondi per strumento</p>
    {instr_rows or '<p style="color:#94a3b8;font-size:.85rem">Nessuno strumento disponibile.</p>'}
    <button type="submit" class="btn-confirm" style="margin-top:22px">💾 Salva configurazione privacy</button>
  </form>
  <div class="back-links">
    <a href="{STREAMLIT_URL}">← Torna alla dashboard</a>
  </div>
</div>
</body>
</html>"""


# ─── Render: Export PP ───────────────────────────────────────────────────────

def _render_export_pp_page(data: dict, ok_msg: str = "", err_msg: str = "") -> str:
    strumenti = data.get("strumenti") or {}
    n_str = len(strumenti)
    n_ev = len(data.get("registro_eventi") or [])
    storico = data.get("storico_prezzi") or {}
    all_dates: set = set()
    for prices in storico.values():
        if isinstance(prices, dict):
            all_dates.update(prices.keys())
    n_dates = len(all_dates)
    ok_html = f'<div class="alert-ok">{escape(ok_msg)}</div>' if ok_msg else ""
    err_html = f'<div class="alert-warn">{escape(err_msg)}</div>' if err_msg else ""
    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Esporta Portfolio Performance</title>
{_CSS}
</head>
<body>
<div class="card">
  <h1>📊 Esporta per Portfolio Performance</h1>
  {ok_html}{err_html}
  <div class="metrics">
    <div class="metric"><div class="metric-lbl">Strumenti</div><div class="metric-val">{n_str}</div></div>
    <div class="metric"><div class="metric-lbl">Transazioni</div><div class="metric-val">{n_ev}</div></div>
    <div class="metric"><div class="metric-lbl">Date prezzi</div><div class="metric-val">{n_dates}</div></div>
  </div>
  <hr class="divider">
  <h2>Transazioni</h2>
  <p style="font-size:.87rem;color:#475569;margin:0 0 10px">
    File CSV con tutte le operazioni (acquisto, vendita, cedole, dividendi) nel formato
    standard di Portfolio Performance.<br>
    <small style="color:#94a3b8">Separatore: <code>;</code> &nbsp;|&nbsp; Decimale: <code>,</code> &nbsp;|&nbsp; Encoding: UTF-8 con BOM</small>
  </p>
  <a href="/export_pp/transazioni" class="btn-confirm" style="text-align:center;text-decoration:none;display:block">⬇ Scarica CSV transazioni</a>
  <hr class="divider">
  <h2>Prezzi storici</h2>
  <p style="font-size:.87rem;color:#475569;margin:0 0 10px">
    Archivio ZIP con un CSV per strumento contenente lo storico prezzi.<br>
    <small style="color:#94a3b8">In PP: seleziona strumento → Dati storici → ⋯ → Importa da file CSV</small>
  </p>
  <a href="/export_pp/prezzi" class="btn-confirm" style="text-align:center;text-decoration:none;display:block">⬇ Scarica ZIP prezzi storici</a>
  <hr class="divider">
  <div class="back-links">
    <a href="{STREAMLIT_URL}" target="_blank">← Torna a Streamlit</a>
  </div>
</div>
</body>
</html>"""


# ─── Render: SATOR ───────────────────────────────────────────────────────────

_SATOR_DEFAULT_CATS = ["ETF", "ETC"]
_SATOR_ALL_CATS = ["ETF", "ETC", "FONDO", "AZIONE", "BTP", "ALTRO"]

_SATOR_CSS = """<style>
*,*::before,*::after{box-sizing:border-box}
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:#f1f5f9;color:#1e293b;margin:0;padding:16px 20px 60px;font-size:.9rem}
.sp{max-width:1440px;margin:0 auto}
.sp-card{background:#fff;border-radius:14px;padding:20px 24px;box-shadow:0 2px 10px rgba(0,0,0,.06);margin-bottom:16px}
h1{font-size:1.15rem;font-weight:800;margin:0 0 14px;color:#1e293b}
h2{font-size:.75rem;font-weight:800;text-transform:uppercase;letter-spacing:.06em;color:#64748b;margin:0 0 14px}
label.lbl{display:block;font-weight:700;font-size:.72rem;text-transform:uppercase;letter-spacing:.04em;margin:0 0 4px;color:#64748b}
select,input[type=text],input[type=number]{width:100%;padding:8px 10px;border:1px solid #cbd5e1;border-radius:8px;font-size:.88rem;background:#fff;outline:none;transition:border-color .15s,box-shadow .15s}
select:focus,input:focus{border-color:#6366f1;box-shadow:0 0 0 3px rgba(99,102,241,.12)}
.form-row{display:flex;gap:14px;align-items:flex-end;flex-wrap:wrap}
.fg{display:flex;flex-direction:column;gap:3px}
.fg-sm{min-width:100px}
.fg-md{min-width:150px}
.fg-lg{flex:1;min-width:180px}
.cat-wrap{display:flex;flex-wrap:wrap;gap:5px;margin-top:4px}
.cat-wrap label{display:inline-flex;align-items:center;gap:4px;font-size:.82rem;cursor:pointer;padding:4px 9px;border:1px solid #e2e8f0;border-radius:6px;background:#f8fafc;transition:all .15s;user-select:none}
.cat-wrap label:hover{border-color:#6366f1;background:#eef2ff}
.cat-wrap input[type=checkbox]{accent-color:#6366f1;width:13px;height:13px;flex-shrink:0}
.btn-analizza{padding:9px 24px;background:#6366f1;color:#fff;border:none;border-radius:9px;font-size:.9rem;font-weight:700;cursor:pointer;white-space:nowrap;transition:background .15s}
.btn-analizza:hover{background:#4f46e5}
.sp-body{display:flex;gap:16px;align-items:flex-start}
.sp-table-col{flex:1;min-width:0}
.sp-eval-panel{width:278px;flex-shrink:0;position:sticky;top:16px}
.ev-h{font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:#94a3b8;margin:0 0 2px}
.ev-v{font-size:1.05rem;font-weight:800;color:#1e293b;transition:color .3s}
.ev-block{margin-bottom:14px;padding-bottom:14px;border-bottom:1px solid #f1f5f9}
.ev-block:last-of-type{border-bottom:none;margin-bottom:0;padding-bottom:0}
.ev-row{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px}
.bar-wrap{background:#e2e8f0;border-radius:4px;height:7px;overflow:hidden;margin:3px 0 8px}
.bar-fill{height:100%;border-radius:4px;transition:width .4s ease}
.ev-headline{text-align:center;padding:10px 14px;border-radius:10px;font-weight:800;font-size:.9rem;margin:10px 0;display:none}
.note-inp{width:100%;padding:8px 10px;border:1px solid #cbd5e1;border-radius:8px;font-size:.84rem;outline:none;margin-bottom:8px}
.note-inp:focus{border-color:#059669}
.btn-save{display:block;width:100%;padding:11px;background:#059669;color:#fff;border:none;border-radius:9px;font-size:.9rem;font-weight:700;cursor:pointer;transition:background .15s}
.btn-save:hover{background:#047857}
.btn-save:disabled{background:#94a3b8;cursor:not-allowed}
.sr-table{width:100%;border-collapse:collapse;table-layout:fixed;font-size:.8rem}
.sr-table th{text-align:left;font-size:.64rem;text-transform:uppercase;letter-spacing:.03em;color:#94a3b8;font-weight:700;padding:4px 4px 8px;border-bottom:2px solid #e2e8f0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sr-table td{padding:6px 4px;border-bottom:1px solid #f1f5f9;vertical-align:middle;overflow:hidden}
.sr-table tr:hover td{background:#fafbfc}
.sr-table tr:last-child td{border-bottom:none}
.sc-badge{display:inline-block;font-size:.72rem;font-weight:800;border-radius:4px;padding:2px 5px;line-height:1.2}
.sc-g{background:#dcfce7;color:#166534}.sc-m{background:#fef9c3;color:#854d0e}.sc-b{background:#fee2e2;color:#991b1b}
.rb-dot{display:inline-block;width:11px;height:11px;border-radius:3px;vertical-align:middle}
.rb-core{background:#3b82f6}.rb-dif{background:#22c55e}.rb-sat{background:#f97316}
.tbl-actions{display:flex;gap:8px;margin-bottom:12px;align-items:center;flex-wrap:wrap}
.btn-sm{padding:5px 12px;border:1px solid #e2e8f0;background:#f8fafc;color:#475569;border-radius:7px;font-size:.78rem;font-weight:600;cursor:pointer;transition:all .15s;white-space:nowrap}
.btn-sm:hover{border-color:#6366f1;color:#6366f1;background:#eef2ff}
.btn-sm-p{background:#eef2ff;color:#6366f1;border-color:#c7d2fe}
.btn-sm-p:hover{background:#6366f1;color:#fff}
.hist-row{display:flex;gap:10px;align-items:center;padding:10px 0;border-bottom:1px solid #f1f5f9;flex-wrap:wrap}
.hist-row:last-child{border-bottom:none}
.hist-detail{background:#f8fafc;border-radius:8px;padding:12px 14px;margin-bottom:8px;font-size:.8rem;display:none}
.hist-detail .dl{display:flex;gap:10px;padding:4px 0;border-bottom:1px solid #e2e8f0;align-items:center}
.hist-detail .dl:last-child{border-bottom:none}
.alert-warn{background:#fffbeb;border:1px solid #fcd34d;border-radius:8px;padding:10px 14px;color:#92400e;font-size:.84rem;margin-bottom:12px}
.alert-ok{background:#f0fdf4;border:1px solid #86efac;border-radius:8px;padding:10px 14px;color:#166534;font-size:.84rem;margin-bottom:12px}
.notice{background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:8px 14px;color:#1d4ed8;font-size:.8rem;margin-bottom:10px;display:none}
.empty-state{text-align:center;color:#94a3b8;font-size:.84rem;padding:28px 0}
.legend-box{display:flex;flex-wrap:wrap;gap:6px 16px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 12px;margin-bottom:12px;font-size:.74rem;color:#475569}
.legend-box b{color:#1e293b}
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
            "style='color:#c2410c;font-size:.7rem;margin-left:2px'>&#9888;</span>"
        )
        table_rows += (
            f"<tr>"
            f"<td style='font-size:1.05rem;padding-left:4px;width:22px'>{sem}</td>"
            f"<td style='font-weight:800;white-space:nowrap;width:66px;overflow:hidden;text-overflow:ellipsis'>{tk}{dati_warning}</td>"
            f"<td style='width:106px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#475569' title='{name_esc}'>{name_short}</td>"
            f"<td style='width:80px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:.7rem;color:#64748b' title='{escape(funz_full)}'>{funz}</td>"
            f"<td style='text-align:center;width:24px'>{_ruolo_badge(r['bucket'])}</td>"
            f"<td style='text-align:center;width:36px' title='{why_esc}'>{_voto_badge(r['voto'])}</td>"
            f"<td style='text-align:center;width:28px'>{_sc_badge(r['fit'])}</td>"
            f"<td style='text-align:center;width:28px'>{_sc_badge(r['mom'])}</td>"
            f"<td style='text-align:center;width:28px'>{_sc_badge(r['risk'])}</td>"
            f"<td style='text-align:center;width:28px'>{_sc_badge(r['div_s'])}</td>"
            f"<td style='text-align:center;width:28px'>{_sc_badge(r['cost'])}</td>"
            f"<td style='text-align:right;white-space:nowrap;overflow:hidden;color:#475569;width:58px'>€ {px_it}</td>"
            f"<td style='text-align:center;color:#64748b;width:32px'>{qp_it}</td>"
            f"<td style='text-align:center;font-weight:700;color:#6366f1;width:28px'>{r['sug']}</td>"
            f"<td style='text-align:center;width:26px'>"
            f"<input type='checkbox' id='sel_{tk}' onchange='computeEval()' "
            f"style='accent-color:#6366f1;width:14px;height:14px;cursor:pointer'></td>"
            f"<td style='text-align:center;width:48px'>"
            f"<input type='number' id='qta_{tk}' min='0' step='1' value='0' oninput='computeEval()' "
            f"style='width:40px;padding:3px 4px;border:1px solid #cbd5e1;border-radius:6px;font-size:.8rem;text-align:center'></td>"
            f"</tr>"
        )

    table_html = (
        f"{alerts_html}"
        f"{_SATOR_LEGEND_HTML}"
        f"<div class='tbl-actions'>"
        f"<button type='button' class='btn-sm btn-sm-p' onclick='prefillSug()'>↺ Usa suggeriti SATOR</button>"
        f"<button type='button' class='btn-sm' onclick='clearSel()'>✕ Azzera</button>"
        f"<span style='font-size:.74rem;color:#94a3b8;margin-left:4px'>Modifica Qta → valutazione live a destra</span>"
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
    <div class="ev-row"><span class="ev-h">Totale ordine</span><span class="ev-v" id="ev_total" style="color:#94a3b8">—</span></div>
    <div class="ev-row"><span class="ev-h">Delta budget</span><span class="ev-v" id="ev_delta" style="color:#94a3b8">—</span></div>
  </div>
  <div class="ev-block" id="ev_rip_sec" style="display:none">
    <div class="ev-h" style="margin-bottom:8px">Ripartizione</div>
    <div style="display:flex;justify-content:space-between;font-size:.8rem"><span style="color:#3b82f6;font-weight:600">Core</span><span id="ev_core_pct">—</span></div>
    <div class="bar-wrap"><div class="bar-fill" id="ev_core_bar" style="background:#3b82f6;width:0%"></div></div>
    <div style="display:flex;justify-content:space-between;font-size:.8rem"><span style="color:#22c55e;font-weight:600">Difensivo</span><span id="ev_diff_pct">—</span></div>
    <div class="bar-wrap"><div class="bar-fill" id="ev_diff_bar" style="background:#22c55e;width:0%"></div></div>
    <div style="display:flex;justify-content:space-between;font-size:.8rem"><span style="color:#f97316;font-weight:600">Satellite</span><span id="ev_sat_pct">—</span></div>
    <div class="bar-wrap"><div class="bar-fill" id="ev_sat_bar" style="background:#f97316;width:0%"></div></div>
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
  t.textContent=nsel?fmtEur(total):'—'; t.style.color=nsel?'#1e293b':'#94a3b8';
  const btn=document.getElementById('btn_save'); if(btn)btn.disabled=nsel===0;
  if(!nsel){{
    d.textContent='—';d.style.color='#94a3b8';
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
  d.style.color=delta>overTol?'#ef4444':delta>0?'#f97316':delta<-underLim?'#f59e0b':'#22c55e';
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
  if(delta>overTol){{headline='Fuori budget';hlBg='#fef2f2';hlCol='#b91c1c';}}
  else if(delta>0){{headline='Appena fuori budget';hlBg='#fff7ed';hlCol='#c2410c';}}
  else if(delta<-underLim){{headline='Budget sottoutilizzato';hlBg='#fefce8';hlCol='#92400e';}}
  else if(af>=0.62&&ar>=0.50){{headline='Scelta coerente ✓';hlBg='#f0fdf4';hlCol='#15803d';}}
  else{{headline='Scelta da rivedere';hlBg='#fff7ed';hlCol='#c2410c';}}
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
    const gCol=glbl.includes('coerente')?'#15803d':glbl.includes('rivedere')?'#c2410c':'#92400e';
    const gBg=glbl.includes('coerente')?'#f0fdf4':glbl.includes('rivedere')?'#fff7ed':'#fefce8';
    let linesHtml='';
    lines.forEach(l=>{{
      const am=parseFloat(l.amount||l.importo||0);
      linesHtml+=`<div class="dl"><span style="font-weight:800;min-width:60px">${{l.ticker}}</span><span style="flex:1;color:#64748b">${{l.name||''}}</span><span style="white-space:nowrap;color:#475569">${{l.shares||l.quantita||0}} q × ${{fmtEur(l.price||l.prezzo||0)}}</span><span style="font-weight:700;margin-left:10px">${{fmtEur(am)}}</span></div>`;
    }});
    const ripartRow=Object.entries(dec.ripartizione||{{}}).filter(([,v])=>v.amount>0).map(([k,v])=>`<span style="font-size:.75rem;color:#64748b">${{k}}: ${{fmtPct(v.pct)}}</span>`).join(' · ');
    html+=`
    <div class="hist-row">
      <div style="min-width:105px;font-size:.75rem;color:#64748b">${{created}}</div>
      <div><span style="font-size:.72rem;color:#94a3b8">Budget</span> <strong style="font-size:.85rem">${{fmtEur(budget_d)}}</strong></div>
      <div><span style="font-size:.72rem;color:#94a3b8">Importo</span> <strong style="font-size:.85rem">${{fmtEur(imp)}}</strong></div>
      <div><span style="background:${{gBg}};color:${{gCol}};font-size:.74rem;font-weight:700;padding:2px 9px;border-radius:6px;display:inline-block">${{glbl}}</span></div>
      <div style="font-size:.78rem;color:#64748b">⭐ ${{fmtV(vm)}} · ${{lines.length}} str.</div>
      ${{ripartRow?`<div style="font-size:.75rem;color:#94a3b8">${{ripartRow}}</div>`:''}}
      ${{note?`<div style="font-size:.74rem;color:#94a3b8;font-style:italic">«${{note}}»</div>`:''}}
      <div style="margin-left:auto;display:flex;gap:6px;flex-shrink:0">
        <button class="btn-sm" onclick="toggleHistDetail(${{origIdx}})">▼ Dettaglio</button>
        <button class="btn-sm btn-sm-p" onclick="loadDecision(${{origIdx}})" ${{!hasAnalysis?'style="opacity:.6"':''}}>↺ Riparti</button>
        <button class="btn-sm" style="color:#b91c1c;border-color:#fecaca" onclick="deleteDecision('${{dec.decision_id}}')">🗑 Elimina</button>
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
      <a href="{STREAMLIT_URL}" target="_blank" style="font-size:.82rem;color:#6366f1;text-decoration:none;font-weight:600">← Torna a Streamlit</a>
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
    <h2>Decisioni precedenti <span id="hist_count" style="font-weight:400;color:#94a3b8"></span></h2>
    <div id="hist_container"></div>
  </div>

</div>
{js_block}
</body>
</html>"""


# ─── Render: Scheda Strumento ────────────────────────────────────────────────

def _render_scheda_strumento(strumento: dict, ok_msg: str = "", err_msg: str = "", mode: str = "view") -> str:
    ticker = strumento.get("ticker", "")
    nome   = strumento.get("nome", "")
    isin   = strumento.get("isin", "") or "—"
    tipo   = strumento.get("tipo", "")
    from core.formatting import fmt_date_only_it
    enriched_at_raw = (strumento.get("enriched_at") or "")[:10]
    enriched_at = fmt_date_only_it(enriched_at_raw) if enriched_at_raw else "mai"
    enrichment_error = strumento.get("enrichment_error") or ""
    src    = strumento.get("enrichment_source") or {}

    from core.instrument_enrichment import _categoria
    cat = _categoria(tipo)

    def _badge(field: str) -> str:
        s = src.get(field, "")
        colors = {"auto": "#0ea5e9", "pdf": "#8b5cf6", "manuale": "#f59e0b"}
        labels = {"auto": "Auto", "pdf": "PDF", "manuale": "Manuale"}
        if not s:
            return ""
        c = colors.get(s, "#94a3b8")
        lb = labels.get(s, s)
        return f'<span style="font-size:10px;padding:1px 6px;border-radius:9px;background:{c};color:#fff;margin-left:6px;">{lb}</span>'

    ok_html  = f'<div class="alert alert-ok">{ok_msg}</div>' if ok_msg else ""
    err_html = f'<div class="alert alert-err">{err_msg}</div>' if err_msg else ""
    enrich_err_html = f'<div class="alert alert-warn">&#9888; Errore fetch: {enrichment_error}</div>' if enrichment_error else ""

    # Chip stato arricchimento
    if enrichment_error:
        stato_chip = '<span class="chip chip-warn">&#9888; Errore</span>'
    elif enriched_at != "mai":
        stato_chip = f'<span class="chip chip-ok">&#10003; Arricchito {enriched_at}</span>'
    else:
        stato_chip = '<span class="chip chip-gray">Non arricchito</span>'

    # Fonte dati label
    src_labels = {"auto": "Automatico", "pdf": "PDF Fineco", "manuale": "Manuale"}
    src_vals = set(v for v in (src or {}).values() if v)
    src_label = " · ".join(src_labels.get(v, v) for v in src_vals) if src_vals else ""

    base_css = """
  *{box-sizing:border-box;margin:0;padding:0;}
  body{font-family:system-ui,-apple-system,sans-serif;background:#f0f4f8;color:#0f172a;padding:20px;}
  .page{max-width:780px;margin:0 auto;}
  /* Header */
  .hdr{background:#fff;border-radius:14px;padding:20px 24px 16px;margin-bottom:14px;box-shadow:0 1px 6px rgba(0,0,0,.07);}
  .hdr-name{font-size:21px;font-weight:800;color:#0f172a;margin-bottom:8px;line-height:1.2;}
  .chips{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px;}
  .chip{font-size:11px;font-weight:600;padding:3px 10px;border-radius:20px;}
  .chip-tipo{background:#dbeafe;color:#1d4ed8;}
  .chip-ok{background:#dcfce7;color:#15803d;}
  .chip-warn{background:#fef3c7;color:#b45309;}
  .chip-gray{background:#f1f5f9;color:#64748b;}
  .hdr-meta{font-size:12px;color:#94a3b8;}
  /* Alerts */
  .alert{padding:9px 14px;border-radius:8px;font-size:13px;margin-bottom:12px;}
  .alert-ok{background:#f0fdf4;color:#16a34a;border:1px solid #bbf7d0;}
  .alert-err{background:#fef2f2;color:#dc2626;border:1px solid #fecaca;}
  .alert-warn{background:#fffbeb;color:#b45309;border:1px solid #fde68a;}
  /* Actions bar */
  .actions{display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap;}
  .btn{display:inline-block;padding:8px 18px;border-radius:8px;font-size:13px;font-weight:600;text-decoration:none;cursor:pointer;border:none;white-space:nowrap;}
  .btn-primary{background:#0f172a;color:#fff;}
  .btn-fetch{background:#0ea5e9;color:#fff;}
  .btn-secondary{background:#fff;color:#475569;border:1px solid #e2e8f0;}
  /* Hero KPIs */
  .hero{display:grid;gap:10px;margin-bottom:14px;}
  .hero-3{grid-template-columns:repeat(3,1fr);}
  .hero-2{grid-template-columns:repeat(2,1fr);}
  .kpi-card{background:#fff;border-radius:12px;padding:16px 14px;box-shadow:0 1px 6px rgba(0,0,0,.07);text-align:center;}
  .kpi-val{font-size:26px;font-weight:800;color:#0f172a;line-height:1;margin-bottom:5px;}
  .kpi-lbl{font-size:10px;color:#94a3b8;font-weight:700;text-transform:uppercase;letter-spacing:.06em;}
  .kpi-card.pos .kpi-val{color:#16a34a;}
  .kpi-card.neg .kpi-val{color:#dc2626;}
  /* Sections */
  .sec{background:#fff;border-radius:12px;padding:18px 20px;margin-bottom:12px;box-shadow:0 1px 6px rgba(0,0,0,.07);}
  .sec-title{font-size:10px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:.08em;margin-bottom:14px;}
  /* Data grid */
  .dg{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px 20px;}
  .dg-wide{grid-template-columns:repeat(auto-fill,minmax(300px,1fr));}
  .di .lbl{font-size:11px;color:#94a3b8;margin-bottom:3px;}
  .di .val{font-size:14px;font-weight:600;color:#1e293b;}
  .di .val.pos{color:#16a34a;}
  .di .val.neg{color:#dc2626;}
  /* Composition bars */
  .comp-row{display:flex;align-items:center;gap:10px;margin-bottom:8px;}
  .comp-lbl{font-size:12px;color:#475569;min-width:120px;}
  .comp-bar-wrap{flex:1;background:#f1f5f9;border-radius:4px;height:7px;}
  .comp-bar{height:7px;border-radius:4px;}
  .bar-az{background:#3b82f6;}
  .bar-ob{background:#10b981;}
  .bar-liq{background:#94a3b8;}
  .comp-val{font-size:12px;font-weight:700;color:#334155;min-width:44px;text-align:right;}
  /* Stars */
  .stars{color:#f59e0b;font-size:17px;letter-spacing:1px;}
  /* Source badge */
  .sbadge{display:inline-block;font-size:9px;padding:1px 5px;border-radius:8px;margin-left:5px;vertical-align:middle;}
  .sb-auto{background:#dbeafe;color:#1d4ed8;}
  .sb-pdf{background:#ede9fe;color:#7c3aed;}
  .sb-manuale{background:#fef3c7;color:#b45309;}
  /* Completeness score */
  .score-row{display:flex;align-items:center;gap:10px;margin-top:10px;}
  .score-lbl{font-size:11px;color:#94a3b8;font-weight:600;white-space:nowrap;}
  .score-bar-wrap{flex:1;background:#e2e8f0;border-radius:4px;height:6px;max-width:160px;}
  .score-bar{height:6px;border-radius:4px;}
  .score-text{font-size:11px;font-weight:700;}
  .sc-green{color:#15803d;} .sc-bar-green{background:#22c55e;}
  .sc-yellow{color:#b45309;} .sc-bar-yellow{background:#f59e0b;}
  .sc-orange{color:#c2410c;} .sc-bar-orange{background:#f97316;}
  .sc-red{color:#dc2626;} .sc-bar-red{background:#ef4444;}
  /* Footer */
  .foot{text-align:center;margin-top:20px;padding-bottom:10px;}"""

    # ── Punteggio completezza ─────────────────────────────────────────────────
    _CORE_FIELDS: dict[str, list[str]] = {
        "btp": ["ytm_netto", "ytm_lordo", "duration_modificata", "scadenza",
                "cedola_annuale", "cedola_frequenza", "tipo_cedola", "rating_emittente"],
        "etf": ["rendimento_1a", "rendimento_3a", "ter", "benchmark",
                "categoria_etf", "distribuzione", "data_lancio", "rating_morningstar"],
        "etc": ["rendimento_1a", "rendimento_3a", "ter", "benchmark",
                "categoria_etf", "distribuzione", "data_lancio"],
        "fondo": ["rendimento_ytd", "rendimento_1a", "rendimento_3a", "ter",
                  "categoria_fam", "rating_morningstar", "data_lancio", "patrimonio"],
    }
    _score_fields = _CORE_FIELDS.get(cat, [])
    if _score_fields and enriched_at != "mai":
        _filled = sum(1 for f in _score_fields if strumento.get(f) not in (None, "", "—"))
        _pct = int(_filled / len(_score_fields) * 100)
        if _pct == 100:
            _sc, _sc_bar, _sc_label = "sc-green", "sc-bar-green", "Completo"
        elif _pct >= 75:
            _sc, _sc_bar, _sc_label = "sc-yellow", "sc-bar-yellow", "Quasi completo"
        elif _pct >= 40:
            _sc, _sc_bar, _sc_label = "sc-orange", "sc-bar-orange", "Parziale"
        else:
            _sc, _sc_bar, _sc_label = "sc-red", "sc-bar-red", "Incompleto"
        _score_html = (
            f'<div class="score-row">'
            f'<span class="score-lbl">Completezza dati</span>'
            f'<div class="score-bar-wrap"><div class="score-bar {_sc_bar}" style="width:{_pct}%;"></div></div>'
            f'<span class="score-text {_sc}">{_pct}% — {_sc_label} ({_filled}/{len(_score_fields)})</span>'
            f'</div>'
        )
    else:
        _score_html = ""

    def _html_open() -> str:
        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Scheda {ticker}</title>
<style>{base_css}</style></head><body><div class="page">
<div class="hdr">
  <div style="font-size:12px;font-weight:700;color:#94a3b8;letter-spacing:.06em;margin-bottom:4px;">{ticker}</div>
  <div class="hdr-name">{nome}</div>
  <div class="chips">
    <span class="chip chip-tipo">{tipo}</span>
    {stato_chip}
  </div>
  <div class="hdr-meta">ISIN: {isin}{(' &nbsp;·&nbsp; Fonte: ' + src_label) if src_label else ''}</div>
  {_score_html}
</div>
{ok_html}{err_html}{enrich_err_html}
<div class="actions">
  <a href="/strumento/{ticker}/fetch" class="btn btn-fetch">&#8635; Aggiorna dati</a>
  <a href="/strumento/{ticker}?mode=edit" class="btn btn-secondary">&#9998; Modifica</a>
  <a href="javascript:window.close()" class="btn btn-secondary">Chiudi</a>
</div>"""

    def _html_close() -> str:
        return "</div></body></html>"

    # ── VIEW MODE ──────────────────────────────────────────────────────────────
    if mode != "edit":
        def _v(name: str):
            return strumento.get(name)

        def _vs(name: str) -> str:
            v = strumento.get(name)
            return str(v) if v is not None else ""

        def _vd(name: str) -> str:
            """Come _vs, ma formatta il valore come data italiana (GG/MM/AAAA)."""
            v = _vs(name)
            return fmt_date_only_it(v) if v else ""

        def _rend_cls(val: str) -> str:
            if not val:
                return ""
            s = val.replace(" ", "")
            # Normalize Italian number format: "9.284,27" (thousands sep) → "9284.27"
            n = s.replace(",", ".").replace("%", "")
            parts = n.split(".")
            if len(parts) > 2:
                n = "".join(parts[:-1]) + "." + parts[-1]
            if s.startswith("+") or (n.lstrip("-").replace(".", "").isdigit() and float(n) > 0):
                return " pos"
            if s.startswith("-"):
                return " neg"
            return ""

        def _kpi(val: str, lbl: str, extra_cls: str = "") -> str:
            if not val:
                return ""
            cls = (_rend_cls(val) if not extra_cls else extra_cls).strip()
            cls_attr = f" {cls}" if cls else ""
            return f'<div class="kpi-card{cls_attr}"><div class="kpi-val">{val}</div><div class="kpi-lbl">{lbl}</div></div>'

        def _di(lbl: str, name: str, cls: str = "", val_override: str = "") -> str:
            val = val_override or _vs(name)
            if not val:
                return ""
            src_v = (src or {}).get(name, "")
            badge = f'<span class="sbadge sb-{src_v}">{src_v[:3].upper()}</span>' if src_v else ""
            vc = f" {cls}" if cls else _rend_cls(val)
            return f'<div class="di"><div class="lbl">{lbl}</div><div class="val{vc}">{val}{badge}</div></div>'

        def _stars(name: str = "rating_morningstar") -> str:
            v = _vs(name)
            if not v:
                return ""
            try:
                n = int(float(v))
                return "★" * n + "☆" * (5 - n)
            except Exception:
                return v

        def _sec(title: str, content: str) -> str:
            return f'<div class="sec"><div class="sec-title">{title}</div>{content}</div>' if content.strip() else ""

        def _dg(*items: str, wide: bool = False) -> str:
            cls = "dg dg-wide" if wide else "dg"
            return f'<div class="{cls}">' + "".join(i for i in items if i) + "</div>"

        def _comp_bar(lbl: str, name: str, bar_cls: str) -> str:
            val = _vs(name)
            if not val:
                return ""
            pct_s = val.replace(",", ".").replace("%", "").strip()
            try:
                pct = min(max(float(pct_s), 0), 100)
            except Exception:
                pct = 0
            return (f'<div class="comp-row"><span class="comp-lbl">{lbl}</span>'
                    f'<div class="comp-bar-wrap"><div class="comp-bar {bar_cls}" style="width:{pct}%;"></div></div>'
                    f'<span class="comp-val">{val}</span></div>')

        # ── Posizione base (comune a tutti) ──────────────────────────────────
        prezzo_str = _vs("prezzo")
        agg_str    = _vd("aggiornato")
        pos_items  = []
        if prezzo_str:
            pos_items.append(f'<div class="di"><div class="lbl">Prezzo corrente</div><div class="val">{prezzo_str}</div></div>')
        if agg_str:
            pos_items.append(f'<div class="di"><div class="lbl">Aggiornato</div><div class="val">{agg_str}</div></div>')
        if _vs("quantita"):
            pos_items.append(f'<div class="di"><div class="lbl">Quantità</div><div class="val">{_vs("quantita")}</div></div>')
        if _vs("nominale"):
            pos_items.append(f'<div class="di"><div class="lbl">Nominale</div><div class="val">{_vs("nominale")}</div></div>')
        if _vs("data_origine"):
            pos_items.append(f'<div class="di"><div class="lbl">Data acquisto</div><div class="val">{_vd("data_origine")}</div></div>')
        posizione_sec = _sec("Posizione in portafoglio", _dg(*pos_items)) if pos_items else ""

        if cat == "btp":
            hero = (
                f'<div class="hero hero-3">'
                + _kpi(_vs("ytm_netto"), "YTM Netto")
                + _kpi(_vs("duration_modificata"), "Duration")
                + _kpi(_vd("scadenza"), "Scadenza")
                + "</div>"
            )
            body = (
                hero
                + _sec("Rendimento",
                    _dg(_di("YTM Netto", "ytm_netto"),
                        _di("YTM Lordo", "ytm_lordo"),
                        _di("Duration Modificata", "duration_modificata"),
                        _di("Rating Emittente", "rating_emittente")))
                + _sec("Cedola",
                    _dg(_di("Scadenza", "scadenza", val_override=_vd("scadenza")),
                        _di("Cedola Annuale", "cedola_annuale"),
                        _di("Frequenza", "cedola_frequenza"),
                        _di("Tipo", "tipo_cedola"),
                        _di("Prossima Cedola", "prossima_cedola", val_override=_vd("prossima_cedola")),
                        _di("Data Godimento", "data_godimento", val_override=_vd("data_godimento"))))
                + _sec("Ratei e Fiscalità",
                    _dg(_di("Rateo Lordo", "rateo_lordo"),
                        _di("Rateo Netto", "rateo_netto"),
                        _di("Rateo Interessi", "rateo_interessi"),
                        _di("Rateo Disagio", "rateo_disaggio"),
                        _di("Ritenute Totali", "ritenute_totali")))
                + _sec("Emissione",
                    _dg(_di("Emittente", "emittente_btp"),
                        _di("Struttura", "struttura"),
                        _di("Data Emissione", "data_emissione"),
                        _di("Prezzo Emissione", "prezzo_emissione"),
                        _di("Prezzo Rimborso", "prezzo_rimborso")))
                + posizione_sec
            )

        elif cat in ("etf", "etc"):
            ytd = _vs("rendimento_ytd"); r1 = _vs("rendimento_1a"); r3 = _vs("rendimento_3a")
            hero = (
                f'<div class="hero hero-3">'
                + _kpi(ytd if ytd else r1, "Da inizio anno (YTD)" if ytd else "Rendimento 1 Anno")
                + _kpi(r3, "Rendimento 3 Anni")
                + _kpi(_vs("ter"), "TER (costo annuo)")
                + "</div>"
            )
            stars_str = _stars()
            rating_item = (f'<div class="di"><div class="lbl">Rating Morningstar</div>'
                           f'<div class="val"><span class="stars">{stars_str}</span></div></div>') if stars_str else ""
            holdings_html = ""
            for h in (strumento.get("holdings_top") or [])[:5]:
                n_h = h.get("nome", ""); p_h = h.get("pct", "")
                try:
                    p_num = min(max(float(p_h.replace(",", ".").replace("%", "").strip()), 0), 100)
                except Exception:
                    p_num = 0
                holdings_html += (
                    f'<div class="comp-row">'
                    f'<span class="comp-lbl">{escape(n_h)}</span>'
                    f'<div class="comp-bar-wrap"><div class="comp-bar bar-az" style="width:{p_num}%;"></div></div>'
                    f'<span class="comp-val">{p_h}</span></div>'
                )
            val_sec = _sec("Valutazione",
                _dg(_di("P/E", "price_earnings"),
                    _di("P/BV", "price_to_book"),
                    _di("Dividend Yield", "dividend_yield"),
                    _di("Dividendo Distribuito", "dividendo_dist")))
            body = (
                hero
                + _sec("Rendimento e Rischio",
                    _dg(_di("Da inizio anno (YTD)", "rendimento_ytd"),
                        _di("Rendimento 1A", "rendimento_1a"),
                        _di("Rendimento 3A", "rendimento_3a"),
                        _di("Rendimento Medio Annuo", "rendimento_medio"),
                        _di("Beta", "beta"),
                        _di("Deviazione Standard", "deviazione_std"),
                        _di("Indice di Sharpe", "sharpe"),
                        _di("VaR", "var")))
                + val_sec
                + _sec("Costi e Categoria",
                    _dg(_di("TER", "ter"),
                        _di("Benchmark", "benchmark"),
                        _di("Categoria", "categoria_etf"),
                        _di("Emittente", "emittente"),
                        _di("Patrimonio (mln €)", "patrimonio"),
                        _di("Distribuzione", "distribuzione"),
                        _di("Fiscalità", "fiscalita"),
                        _di("Data Lancio", "data_lancio", val_override=_vd("data_lancio")),
                        rating_item))
                + (_sec("Top Holdings", holdings_html) if holdings_html else "")
                + posizione_sec
            )
        else:  # fam / fondo
            ytd = _vs("rendimento_ytd"); r1 = _vs("rendimento_1a"); r3 = _vs("rendimento_3a")
            hero = (
                f'<div class="hero hero-3">'
                + _kpi(ytd, "Da inizio anno (YTD)")
                + _kpi(r1, "Rendimento 1 Anno")
                + _kpi(r3, "Rendimento 3 Anni")
                + "</div>"
            )
            stars_str = _stars()
            stars_item = (f'<div class="di"><div class="lbl">Rating Morningstar</div>'
                          f'<div class="val"><span class="stars">{stars_str}</span></div></div>') if stars_str else ""
            comp_html = (
                _comp_bar("Azionario", "composizione_az", "bar-az")
                + _comp_bar("Obbligazionario", "composizione_obbl", "bar-ob")
                + _comp_bar("Liquidità", "composizione_liq", "bar-liq")
            )
            body = (
                hero
                + _sec("Rendimento",
                    _dg(_di("YTD", "rendimento_ytd"),
                        _di("1 Anno", "rendimento_1a"),
                        _di("3 Anni", "rendimento_3a")))
                + _sec("Costi e Categoria",
                    _dg(_di("TER (commissione gestione)", "ter"),
                        _di("Categoria Morningstar", "categoria_fam"),
                        _di("Livello Rischio (1–7)", "livello_rischio"),
                        stars_item))
                + (_sec("Composizione Asset", comp_html) if comp_html.strip() else "")
                + _sec("Dettagli Fondo",
                    _dg(_di("Data Lancio", "data_lancio"),
                        _di("Patrimonio", "patrimonio"),
                        _di("Valuta NAV", "valuta"),
                        _di("Max 52 Settimane", "max_52w"),
                        _di("Min 52 Settimane", "min_52w")))
                + posizione_sec
            )

        if not any(tag in body for tag in ("kpi-card", "sec")):
            body = '<div class="sec"><p style="color:#94a3b8;font-size:13px;">Nessun dato disponibile — clicca <strong>Aggiorna dati</strong> per caricarli.</p></div>'

        return _html_open() + body + '<div class="foot"></div>' + _html_close()

    # ── EDIT MODE ──────────────────────────────────────────────────────────────
    def _field_row(label: str, name: str, placeholder: str = "") -> str:
        val = strumento.get(name, "")
        return f"""
        <div style="margin-bottom:10px;">
          <label style="font-size:12px;font-weight:600;color:#64748b;">{label}{_badge(name)}</label>
          <input name="{name}" value="{val or ''}" placeholder="{placeholder}"
                 style="width:100%;padding:6px 10px;border:1px solid #e2e8f0;border-radius:6px;font-size:13px;margin-top:3px;box-sizing:border-box;">
        </div>"""

    if cat == "btp":
        fields_html = (
            _field_row("YTM Netto", "ytm_netto", "es. 2,27%") + _field_row("YTM Lordo", "ytm_lordo", "es. 2,89%") +
            _field_row("Duration Modificata", "duration_modificata", "es. 0,09") + _field_row("Scadenza", "scadenza", "es. 01/08/2026") +
            _field_row("Cedola Annuale", "cedola_annuale", "es. 0,00%") + _field_row("Frequenza Cedola", "cedola_frequenza", "es. Semestrale") +
            _field_row("Tipo Cedola", "tipo_cedola", "es. FISSO") + _field_row("Prossima Cedola", "prossima_cedola", "es. 01/08/2026") +
            _field_row("Rateo Lordo", "rateo_lordo") + _field_row("Rateo Netto", "rateo_netto") +
            _field_row("Rating Emittente", "rating_emittente", "es. BBB+") + _field_row("Data Emissione", "data_emissione") +
            _field_row("Prezzo Emissione", "prezzo_emissione") + _field_row("Prezzo Rimborso", "prezzo_rimborso") +
            _field_row("Rateo Interessi", "rateo_interessi") + _field_row("Rateo Disagio", "rateo_disaggio") +
            _field_row("Ritenute Totali", "ritenute_totali")
        )
    elif cat in ("etf", "etc"):
        fields_html = (
            _field_row("TER", "ter", "es. 0,40%") + _field_row("Benchmark", "benchmark", "es. FTSE MIB NR EUR") +
            _field_row("Categoria", "categoria_etf", "es. Italy Equity") + _field_row("Emittente", "emittente", "es. Amundi Asset Management") +
            _field_row("Rating Morningstar (stelle)", "rating_morningstar", "es. 4") +
            _field_row("Rendimento 1A", "rendimento_1a", "es. +37,30%") + _field_row("Rendimento 3A", "rendimento_3a", "es. +117,68%") +
            _field_row("Beta", "beta", "es. 1,05") + _field_row("Deviazione Standard", "deviazione_std", "es. 13,00%") +
            _field_row("Indice di Sharpe", "sharpe", "es. 2,00") + _field_row("VaR", "var", "es. 35,61") +
            _field_row("Distribuzione", "distribuzione", "es. Distribuzione") + _field_row("Fiscalità", "fiscalita", "es. Armonizzato") +
            _field_row("Data Lancio", "data_lancio", "es. 03/11/2003")
        )
    else:  # fam
        fields_html = (
            _field_row("TER / Commissione Gestione", "ter", "es. 1,84%") +
            _field_row("Categoria (Morningstar)", "categoria_fam", "es. Bilanciati Flessibili EUR") +
            _field_row("Rating Morningstar (stelle)", "rating_morningstar", "es. 3") +
            _field_row("Livello Rischio (1-7)", "livello_rischio", "es. 4") +
            _field_row("Rendimento YTD", "rendimento_ytd", "es. 4,47%") + _field_row("Rendimento 1A", "rendimento_1a", "es. 11,85%") +
            _field_row("Rendimento 3A", "rendimento_3a", "es. 26,52%") +
            _field_row("% Azionario", "composizione_az", "es. 60,50%") + _field_row("% Obbligazionario", "composizione_obbl", "es. 20,40%") +
            _field_row("% Liquidità", "composizione_liq", "es. 18,90%") +
            _field_row("Valuta NAV", "valuta", "es. EUR") + _field_row("Max 52 Settimane", "max_52w", "es. 145,26") +
            _field_row("Min 52 Settimane", "min_52w", "es. 130,51") + _field_row("Data Lancio", "data_lancio", "es. 27/11/2018") +
            _field_row("Patrimonio", "patrimonio", "es. 422,73 Mln. EUR")
        )

    # edit mode: reuse _html_open (without fetch/modifica buttons) + edit sections
    edit_open = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Modifica {ticker}</title>
<style>{base_css}
  .section{{background:#fff;border-radius:12px;padding:18px 20px;margin-bottom:12px;box-shadow:0 1px 6px rgba(0,0,0,.07);}}
  .section h2{{font-size:10px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:.08em;margin-bottom:14px;}}
</style></head><body><div class="page">
<div class="hdr">
  <div class="hdr-name">{nome}</div>
  <div class="chips"><span class="chip chip-tipo">{tipo}</span>{stato_chip}</div>
  <div class="hdr-meta">ISIN: {isin}</div>
</div>
{ok_html}{err_html}{enrich_err_html}
<div class="actions">
  <a href="/strumento/{ticker}" class="btn btn-secondary">&#8592; Scheda</a>
  <a href="javascript:window.close()" class="btn btn-secondary">Chiudi</a>
</div>"""
    return (edit_open +
            f'<div class="section"><h2>Importa da PDF Fineco</h2>'
            f'<p style="font-size:12px;color:#64748b;margin-bottom:10px;">Carica il PDF dalla pagina Fineco del titolo (Ctrl+P &rarr; Salva come PDF).</p>'
            f'<form method="post" enctype="multipart/form-data" action="/strumento/{ticker}?action=pdf">'
            f'<input type="file" name="pdf_file" accept=".pdf" style="font-size:13px;">'
            f'<input type="submit" value="Importa PDF" class="btn btn-primary" style="margin-left:10px;"></form></div>' +
            f'<div class="section"><h2>Modifica manuale</h2>'
            f'<form method="post" action="/strumento/{ticker}?action=save">{fields_html}'
            f'<input type="submit" value="Salva modifiche" class="btn btn-primary"></form></div>'
            '</div></body></html>')


# ─── FastAPI app ──────────────────────────────────────────────────────────────

def _build_fastapi_app():
    from fastapi import FastAPI, Form, UploadFile, File, Request
    from fastapi.responses import HTMLResponse, RedirectResponse

    _app = FastAPI(title="Portafoglio Form", docs_url=None, redoc_url=None)

    @_app.get("/", response_class=HTMLResponse)
    @_app.get("/operazioni", response_class=HTMLResponse)
    async def get_form():
        from persistence.storage import load_data
        try:
            data = load_data()
            tickers = _get_tickers_info(data)
        except Exception as exc:
            logger.error("Errore caricamento dati: %s", exc)
            tickers = []
        return HTMLResponse(_render_form(tickers))

    @_app.post("/operazioni", response_class=HTMLResponse)
    async def post_form(cart_data: str = Form("[]")):
        from persistence.storage import load_data, save_data, _new_event_id
        from core.finance import append_evento_portafoglio

        def show_error(msg: str):
            from persistence.storage import load_data as _ld
            try:
                tickers = _get_tickers_info(_ld())
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
            data = load_data()
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

    # ── Strumenti ──────────────────────────────────────────────────────────────

    @_app.get("/strumenti", response_class=HTMLResponse)
    async def get_strumenti(tab: str = "add", ok: str = "", err: str = ""):
        from persistence.storage import load_data as _ld
        try:
            d = _ld()
        except Exception as exc:
            d = {}
            err = str(exc)
        return HTMLResponse(_render_strumenti_page(d, ok_msg=ok, err_msg=err, active_tab=tab))

    @_app.post("/strumenti", response_class=HTMLResponse)
    async def post_strumenti(
        azione: str = Form(""),
        isin: str = Form(""),
        ticker_hint: str = Form(""),
        ticker: str = Form(""),
        ticker_new: str = Form(""),
        nome: str = Form(""),
        tipo: str = Form(""),
        scadenza: str = Form(""),
        data_acquisto: str = Form(""),
        prima_cedola: str = Form(""),
        cedola_perc: str = Form("0"),
        cedola_frequenza: str = Form("annuale"),
        aliquota_cedola: str = Form("12.5"),
        nominale: str = Form("100"),
        storico_data_da: str = Form(""),
        storico_data_a: str = Form(""),
    ):
        from fastapi.responses import RedirectResponse
        from persistence.storage import load_data as _ld, save_data

        def err_page(msg: str, tab: str = "add") -> HTMLResponse:
            try:
                d = _ld()
            except Exception:
                d = {}
            return HTMLResponse(_render_strumenti_page(d, err_msg=msg, active_tab=tab))

        if azione == "aggiungi":
            isin = isin.upper().strip()
            if len(isin) != 12:
                return err_page("L'ISIN deve avere 12 caratteri.", "add")
            try:
                d = _ld()
            except Exception as exc:
                return err_page(str(exc), "add")
            if any(s.get("isin") == isin for s in d.get("strumenti", [])):
                return err_page("Strumento già presente.", "add")
            try:
                from core.market_data import deduce_type, find_name, find_ticker, get_price
                tk = ticker_hint.strip() or find_ticker(isin)
                nm = find_name(isin)
                tp = deduce_type(isin, tk, nm)
                pr, src = get_price(isin, tk)
            except Exception as exc:
                return err_page(f"Errore ricerca dati: {exc}", "add")
            d.setdefault("strumenti", []).append({
                "isin": isin, "ticker": tk, "stato": "aperto",
                "nome": nm or "—", "tipo": tp, "prezzo": pr, "fonte": src,
                "aggiornato": str(date.today()), "scadenza": "", "data_acquisto": "",
                "prima_cedola": "", "cedola_perc": 0.0, "cedola_frequenza": "annuale",
                "aliquota_cedola": 12.5, "nominale": 100.0,
            })
            save_data(d)
            from urllib.parse import quote as urlquote
            return RedirectResponse(f"/strumenti?tab=edit&ok={urlquote('Aggiunto '+str(nm or tk))}", status_code=303)

        elif azione == "modifica":
            ticker = ticker.strip()
            ticker_new = ticker_new.strip()
            if not ticker:
                return err_page("Ticker non specificato.", "edit")
            try:
                d = _ld()
            except Exception as exc:
                return err_page(str(exc), "edit")
            se = next((s for s in d.get("strumenti", []) if s.get("ticker") == ticker), None)
            if se is None:
                return err_page("Strumento non trovato.", "edit")
            se["nome"] = nome
            se["tipo"] = tipo
            se["ticker"] = ticker_new or ticker
            if _fs_is_btp_like(se):
                try:
                    se["scadenza"] = _fs_parse_flex_date(scadenza)
                    se["data_acquisto"] = _fs_parse_flex_date(data_acquisto)
                    se["prima_cedola"] = _fs_parse_flex_date(prima_cedola)
                except ValueError as exc:
                    return err_page(f"Data non valida: {exc}", "edit")
                try:
                    se["cedola_perc"] = float(cedola_perc or 0)
                    se["cedola_frequenza"] = str(cedola_frequenza or "annuale")
                    se["aliquota_cedola"] = float(aliquota_cedola or 0)
                    se["nominale"] = float(nominale or 0)
                except ValueError:
                    pass
            if ticker and ticker != ticker_new:
                for op in d.get("operazioni", []):
                    if op.get("ticker") == ticker:
                        op["ticker"] = ticker_new
                for ev in d.get("registro_eventi", []):
                    if ev.get("ticker") == ticker:
                        ev["ticker"] = ticker_new
                for _, prices in (d.get("storico_prezzi") or {}).items():
                    if isinstance(prices, dict) and ticker in prices:
                        prices[ticker_new] = prices.pop(ticker)
            save_data(d)
            from urllib.parse import quote as urlquote
            return RedirectResponse(f"/strumenti?tab=edit&ok={urlquote('Strumento aggiornato.')}", status_code=303)

        elif azione == "elimina":
            ticker = ticker.strip()
            if not ticker:
                return err_page("Ticker non specificato.", "del")
            try:
                d = _ld()
            except Exception as exc:
                return err_page(str(exc), "del")
            ok, msg = _fs_delete_instrument(d, ticker)
            if ok:
                from urllib.parse import quote as urlquote
                return RedirectResponse(f"/strumenti?tab=del&ok={urlquote(msg)}", status_code=303)
            return err_page(msg, "del")

        elif azione == "recupera_storico":
            ticker = ticker.strip()
            if not ticker:
                return err_page("Ticker non specificato.", "storico")
            try:
                since_iso = _fs_parse_flex_date(storico_data_da)
            except ValueError as exc:
                return err_page(f"Data di partenza non valida: {exc}", "storico")
            try:
                d = _ld()
            except Exception as exc:
                return err_page(str(exc), "storico")
            ok, msg = _fs_backfill_storico(d, ticker, since=since_iso or None)
            from urllib.parse import quote as urlquote
            if ok:
                return RedirectResponse(f"/strumenti?tab=storico&ok={urlquote(msg)}", status_code=303)
            return err_page(msg, "storico")

        elif azione == "elimina_storico":
            ticker = ticker.strip()
            if not ticker:
                return err_page("Ticker non specificato.", "storico")
            try:
                da_iso = _fs_parse_flex_date(storico_data_da)
                a_iso = _fs_parse_flex_date(storico_data_a)
            except ValueError as exc:
                return err_page(f"Data non valida: {exc}", "storico")
            try:
                d = _ld()
            except Exception as exc:
                return err_page(str(exc), "storico")
            ok, msg = _fs_delete_storico_range(d, ticker, da_iso, a_iso)
            from urllib.parse import quote as urlquote
            if ok:
                return RedirectResponse(f"/strumenti?tab=storico&ok={urlquote(msg)}", status_code=303)
            return err_page(msg, "storico")

        return err_page("Azione non riconosciuta.", "add")

    # ── Operazioni gestione ────────────────────────────────────────────────────

    @_app.get("/operazioni_gestione", response_class=HTMLResponse)
    async def get_operazioni_gestione(tab: str = "edit", ok: str = "", err: str = ""):
        from persistence.storage import load_data as _ld
        try:
            d = _ld()
        except Exception as exc:
            d = {}
            err = str(exc)
        return HTMLResponse(_render_eventi_page(
            d, _FS_PORTFOLIO_EVENT_TYPES,
            "📝 Operazioni di portafoglio", "operazioni_gestione",
            ok_msg=ok, err_msg=err, active_tab=tab,
        ))

    @_app.post("/operazioni_gestione", response_class=HTMLResponse)
    async def post_operazioni_gestione(
        azione: str = Form(""),
        event_id: str = Form(""),
        data_ev: str = Form("", alias="data"),
        note: str = Form(""),
        quantita: str = Form("0"),
        prezzo_unitario: str = Form("0"),
        commissioni: str = Form("0"),
        imposte: str = Form("0"),
        importo_lordo: str = Form("0"),
        aliquota_perc: str = Form("0"),
    ):
        from fastapi.responses import RedirectResponse
        from persistence.storage import load_data as _ld, _safe_float
        from urllib.parse import quote as urlquote

        def err_page(msg: str) -> HTMLResponse:
            try:
                d = _ld()
            except Exception:
                d = {}
            return HTMLResponse(_render_eventi_page(
                d, _FS_PORTFOLIO_EVENT_TYPES,
                "📝 Operazioni di portafoglio", "operazioni_gestione",
                err_msg=msg,
            ))

        try:
            d = _ld()
        except Exception as exc:
            return err_page(str(exc))

        if azione == "elimina":
            if not event_id:
                return err_page("ID evento mancante.")
            if _fs_delete_event(d, event_id):
                return RedirectResponse(f"/operazioni_gestione?tab=del&ok={urlquote('Operazione eliminata.')}", status_code=303)
            return err_page("Evento non trovato o già eliminato.")

        elif azione == "modifica":
            if not event_id:
                return err_page("ID evento mancante.")
            from persistence.storage import _normalize_event_record
            ev = next(
                (e for e in d.get("registro_eventi", [])
                 if str(_normalize_event_record(e).get("event_id", "")) == event_id),
                None,
            )
            if ev is None:
                return err_page("Evento non trovato.")
            tipo = ev.get("tipo_evento", "")
            updates: dict = {"data": data_ev.strip(), "note": note}
            if tipo in {"ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA"}:
                updates["quantita"] = _safe_float(quantita)
                updates["prezzo_unitario"] = _safe_float(prezzo_unitario)
                updates["commissioni"] = _safe_float(commissioni)
                if tipo != "ACQUISTO":
                    updates["imposte"] = _safe_float(imposte)
            elif tipo in {"CEDOLA", "DIVIDENDO"}:
                updates["importo_lordo"] = _safe_float(importo_lordo)
                updates["aliquota"] = _safe_float(aliquota_perc) / 100.0
            else:
                updates["importo_lordo"] = _safe_float(importo_lordo)
            if _fs_update_event(d, event_id, updates):
                return RedirectResponse(f"/operazioni_gestione?tab=edit&ok={urlquote('Operazione aggiornata.')}", status_code=303)
            return err_page("Aggiornamento fallito.")

        return err_page("Azione non riconosciuta.")

    # ── Liquidità gestione ─────────────────────────────────────────────────────

    @_app.get("/liquidita_gestione", response_class=HTMLResponse)
    async def get_liquidita_gestione(tab: str = "edit", ok: str = "", err: str = ""):
        from persistence.storage import load_data as _ld
        try:
            d = _ld()
        except Exception as exc:
            d = {}
            err = str(exc)
        return HTMLResponse(_render_eventi_page(
            d, _FS_CASH_EVENT_TYPES,
            "💵 Movimenti di liquidità", "liquidita_gestione",
            ok_msg=ok, err_msg=err, active_tab=tab,
        ))

    @_app.post("/liquidita_gestione", response_class=HTMLResponse)
    async def post_liquidita_gestione(
        azione: str = Form(""),
        event_id: str = Form(""),
        data_ev: str = Form("", alias="data"),
        note: str = Form(""),
        importo_lordo: str = Form("0"),
    ):
        from fastapi.responses import RedirectResponse
        from persistence.storage import load_data as _ld, _safe_float
        from urllib.parse import quote as urlquote

        def err_page(msg: str) -> HTMLResponse:
            try:
                d = _ld()
            except Exception:
                d = {}
            return HTMLResponse(_render_eventi_page(
                d, _FS_CASH_EVENT_TYPES,
                "💵 Movimenti di liquidità", "liquidita_gestione",
                err_msg=msg,
            ))

        try:
            d = _ld()
        except Exception as exc:
            return err_page(str(exc))

        if azione == "elimina":
            if not event_id:
                return err_page("ID evento mancante.")
            if _fs_delete_event(d, event_id):
                return RedirectResponse(f"/liquidita_gestione?tab=del&ok={urlquote('Movimento eliminato.')}", status_code=303)
            return err_page("Evento non trovato o già eliminato.")

        elif azione == "modifica":
            if not event_id:
                return err_page("ID evento mancante.")
            updates = {"data": data_ev.strip(), "note": note, "importo_lordo": _safe_float(importo_lordo)}
            if _fs_update_event(d, event_id, updates):
                return RedirectResponse(f"/liquidita_gestione?tab=edit&ok={urlquote('Movimento aggiornato.')}", status_code=303)
            return err_page("Aggiornamento fallito.")

        return err_page("Azione non riconosciuta.")

    # ── Export PP ─────────────────────────────────────────────────────────────

    @_app.get("/export_pp", response_class=HTMLResponse)
    async def get_export_pp():
        from persistence.storage import load_data as _ld
        try:
            d = _ld()
        except Exception as exc:
            d = {}
        return HTMLResponse(_render_export_pp_page(d))

    @_app.get("/export_pp/transazioni")
    async def get_export_pp_transazioni():
        from fastapi.responses import Response
        from persistence.storage import load_data as _ld
        from core.services.portfolio_performance_export import build_portfolio_performance_csv
        try:
            d = _ld()
            csv_str = build_portfolio_performance_csv(d)
            return Response(
                content=csv_str.encode("utf-8-sig"),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=\"portfolio_performance.csv\""},
            )
        except Exception as exc:
            logger.error("PP CSV export error: %s", exc, exc_info=True)
            return HTMLResponse(f"<h2>Errore export CSV</h2><pre>{escape(str(exc))}</pre>", status_code=500)

    @_app.get("/export_pp/prezzi")
    async def get_export_pp_prezzi():
        from fastapi.responses import Response
        from persistence.storage import load_data as _ld
        from core.services.portfolio_performance_export import build_portfolio_performance_prices_zip
        try:
            d = _ld()
            zip_bytes = build_portfolio_performance_prices_zip(d)
            return Response(
                content=zip_bytes,
                media_type="application/zip",
                headers={"Content-Disposition": "attachment; filename=\"prezzi_storici_pp.zip\""},
            )
        except Exception as exc:
            logger.error("PP ZIP export error: %s", exc, exc_info=True)
            return HTMLResponse(f"<h2>Errore export ZIP</h2><pre>{escape(str(exc))}</pre>", status_code=500)

    # ── Privacy ───────────────────────────────────────────────────────────────

    @_app.get("/privacy", response_class=HTMLResponse)
    async def get_privacy(ok: str = "", err: str = ""):
        from persistence.storage import load_data as _ld, load_settings as _ls
        try:
            d = _ld()
        except Exception:
            d = {}
        try:
            s = _ls()
        except Exception:
            s = {}
        return HTMLResponse(_render_privacy_page(d, s, ok_msg=ok, err_msg=err))

    @_app.post("/privacy", response_class=HTMLResponse)
    async def post_privacy(
        enabled: Optional[str] = Form(None),
        hidden_tickers: list[str] = Form(default=[]),
        hidden_categories: list[str] = Form(default=[]),
    ):
        from fastapi.responses import RedirectResponse
        from urllib.parse import quote as urlquote
        from persistence.storage import load_settings as _ls, save_settings as _ss
        try:
            s = _ls()
            s["privacy_mode"] = {
                "enabled": enabled == "1",
                "hidden_tickers": list(hidden_tickers),
                "hidden_categories": list(hidden_categories),
            }
            _ss(s)
            stato = "attiva" if enabled == "1" else "disattivata"
            return RedirectResponse(
                f"/privacy?ok={urlquote(f'Privacy {stato}. Ricarica la dashboard per applicare le modifiche.')}",
                status_code=303,
            )
        except Exception as exc:
            logger.error("Privacy save error: %s", exc, exc_info=True)
            return RedirectResponse(f"/privacy?err={urlquote(str(exc))}", status_code=303)

    # ── Scheda strumento ──────────────────────────────────────────────────────────

    @_app.get("/strumento/{ticker}/fetch")
    async def get_fetch_strumento(ticker: str):
        from persistence.storage import load_data as _ld, save_data as _sd
        from core.instrument_enrichment import enrich_strumento
        d = _ld()
        strumento = next((s for s in (d.get("strumenti") or []) if s.get("ticker") == ticker), None)
        if strumento is None:
            return RedirectResponse(f"/strumento/{ticker}?err=Strumento+non+trovato", status_code=303)
        enrich_strumento(strumento)
        _sd(d)
        if strumento.get("enrichment_error"):
            return RedirectResponse(f"/strumento/{ticker}?err={strumento['enrichment_error']}", status_code=303)
        return RedirectResponse(f"/strumento/{ticker}?ok=Arricchimento+completato", status_code=303)

    @_app.get("/strumento/{ticker}", response_class=HTMLResponse)
    async def get_scheda_strumento(ticker: str, ok: str = "", err: str = "", mode: str = "view"):
        from persistence.storage import load_data as _ld
        d = _ld()
        strumento = next((s for s in (d.get("strumenti") or []) if s.get("ticker") == ticker), None)
        if strumento is None:
            return HTMLResponse(f"<h3>Strumento '{ticker}' non trovato.</h3>", status_code=404)
        return HTMLResponse(_render_scheda_strumento(strumento, ok_msg=ok, err_msg=err, mode=mode))

    @_app.post("/strumento/{ticker}", response_class=HTMLResponse)
    async def post_scheda_strumento(
        ticker: str,
        request: Request,
        action: str = "save",
        pdf_file: Optional[UploadFile] = File(None),
    ):
        from persistence.storage import load_data as _ld, save_data as _sd
        d = _ld()
        strumento = next((s for s in (d.get("strumenti") or []) if s.get("ticker") == ticker), None)
        if strumento is None:
            return RedirectResponse(f"/strumento/{ticker}?err=Strumento+non+trovato", status_code=303)

        try:
            if action == "pdf":
                if not pdf_file or not pdf_file.filename:
                    return RedirectResponse(f"/strumento/{ticker}?err=Nessun+file+selezionato", status_code=303)
                from core.instrument_enrichment import parse_fineco_pdf, _categoria
                pdf_bytes = await pdf_file.read()
                tipo = _categoria(strumento.get("tipo", ""))
                parsed = parse_fineco_pdf(pdf_bytes, tipo)
                if not parsed:
                    return RedirectResponse(f"/strumento/{ticker}?err=PDF+non+riconosciuto", status_code=303)
                src = strumento.get("enrichment_source") or {}
                for field, val in parsed.items():
                    if field != "enrichment_source":
                        strumento[field] = val
                        src[field] = "pdf"
                strumento["enrichment_source"] = src
                import datetime as _dt
                strumento["enriched_at"] = _dt.datetime.utcnow().isoformat()
                _sd(d)
                return RedirectResponse(f"/strumento/{ticker}?ok=PDF+importato+con+successo", status_code=303)

            # action == "save" — form manuale
            form_data = await request.form()
            src = strumento.get("enrichment_source") or {}
            for key, val in form_data.items():
                val = str(val).strip()
                if val:
                    strumento[key] = val
                    src[key] = "manuale"
            strumento["enrichment_source"] = src
            import datetime as _dt
            strumento["enriched_at"] = _dt.datetime.utcnow().isoformat()
            _sd(d)
            return RedirectResponse(f"/strumento/{ticker}?ok=Modifiche+salvate", status_code=303)

        except Exception as exc:
            return RedirectResponse(f"/strumento/{ticker}?err={str(exc)[:80]}", status_code=303)

    # ── SATOR ─────────────────────────────────────────────────────────────────

    def _sator_decisions_json() -> str:
        from persistence.storage import load_sator_decisions
        try:
            dec = load_sator_decisions()
            return json.dumps(list(dec.get("items") or []), ensure_ascii=False, default=str)
        except Exception:
            return "[]"

    @_app.get("/sator", response_class=HTMLResponse)
    async def get_sator(ok: str = "", err: str = ""):
        return HTMLResponse(_render_sator_page(
            ok_msg=ok, err_msg=err,
            decisions_json=_sator_decisions_json(),
        ))

    @_app.post("/sator", response_class=HTMLResponse)
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
        from fastapi.responses import RedirectResponse
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
                from persistence.storage import load_data as _ld, load_settings as _ls
                from core.services.sator import run_sator_analysis, build_sator_matrix_frame

                data = _ld()
                settings = _ls()
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

    return _app


# ─── Avvio background ─────────────────────────────────────────────────────────

def start_form_server(port: int = FORM_PORT) -> None:
    """Avvia il form server in un thread daemon. Idempotente."""
    if _started.is_set():
        return
    _started.set()

    import asyncio
    import uvicorn

    fastapi_app = _build_fastapi_app()
    config = uvicorn.Config(
        fastapi_app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(server.serve())
        except Exception as exc:
            logger.error("Form server terminato inaspettatamente: %s", exc)
        finally:
            loop.close()

    t = threading.Thread(target=_run, daemon=True, name="PortafoglioFormServer")
    t.start()
    logger.info("Form server avviato su http://127.0.0.1:%d/operazioni", port)
