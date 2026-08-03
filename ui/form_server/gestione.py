"""ui/form_server/gestione.py — pagine "Operazioni gestione" e "Liquidità
gestione" del form-server (route /operazioni_gestione, /liquidita_gestione).

Estratto da form_server.py. Condivide la stessa pipeline di storage dell'app
principale: nessuna logica duplicata.

Nota: le funzioni _fs_rebuild_registers/_fs_delete_event/_fs_update_event qui
sotto sono la superficie operativa definitiva aperta dalla sidebar. La pagina
Operazioni dell'app principale resta un registro consultivo.
"""
from __future__ import annotations

import json
import logging
from html import escape

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from core.domain.calendar import TAX_RATE_OTHER_PCT
from ui.form_server.shell import CSS, STREAMLIT_URL, TAB_JS, safe_f as _safe_f

logger = logging.getLogger("portafoglio.form_server.gestione")

router = APIRouter()

_FS_PORTFOLIO_EVENT_TYPES = {"ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA", "CEDOLA", "DIVIDENDO"}
_FS_CASH_EVENT_TYPES = {"VERSAMENTO", "PRELIEVO", "COMMISSIONE", "IMPOSTA"}


# ─── Helpers dominio ──────────────────────────────────────────────────────────

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
        from core.domain.positions import sync_realized_split_fields
        sync_realized_split_fields(data)
    except Exception as exc:
        logger.error("sync_realized_split_fields fallita: %s", exc, exc_info=True)
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
            try:
                from core.domain.positions import sync_realized_split_fields
                sync_realized_split_fields(data)
            except Exception as exc:
                logger.error("sync_realized_split_fields fallita: %s", exc, exc_info=True)
            save_data(data)
            return True
    return False


def _fs_event_label(ev: dict) -> str:
    from core.formatting import fmt_date_only_it
    data_str = fmt_date_only_it(str(ev.get("data", "") or "")[:10])
    tipo = ev.get("tipo_evento", "—")
    ticker = ev.get("ticker") or "—"
    netto = _safe_f(ev.get("importo_netto", 0))
    sign = "+" if netto >= 0 else ""
    return f"{data_str} | {tipo} | {ticker} | {sign}{netto:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


# ─── Render ────────────────────────────────────────────────────────────────

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
<html lang="it"><head><meta charset="utf-8"><title>{escape(title)}</title>{CSS}</head>
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

    edit_provento = f"""
    <div class="row2" style="margin-top:10px">
      <div><label class="lbl">Importo lordo €</label><input type="number" id="e_lordo" name="importo_lordo" step="0.01" min="0" placeholder="0.00"></div>
      <div><label class="lbl">Aliquota %</label><input type="number" id="e_aliq" name="aliquota_perc" step="0.5" min="0" max="100" placeholder="{TAX_RATE_OTHER_PCT}"></div>
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
{CSS}
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
{TAB_JS}
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


# ─── Routes: Operazioni gestione ──────────────────────────────────────────────

@router.get("/operazioni_gestione", response_class=HTMLResponse)
async def get_operazioni_gestione(tab: str = "edit", ok: str = "", err: str = ""):
    from persistence.storage import load_data as _ld, load_settings as _ls, apply_privacy_filter
    try:
        d = apply_privacy_filter(_ld(), _ls())
    except Exception as exc:
        d = {}
        err = str(exc)
    return HTMLResponse(_render_eventi_page(
        d, _FS_PORTFOLIO_EVENT_TYPES,
        "📝 Operazioni di portafoglio", "operazioni_gestione",
        ok_msg=ok, err_msg=err, active_tab=tab,
    ))


@router.post("/operazioni_gestione", response_class=HTMLResponse)
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
    from persistence.storage import load_data as _ld, load_settings as _ls, apply_privacy_filter, _safe_float
    from urllib.parse import quote as urlquote

    def err_page(msg: str) -> HTMLResponse:
        # Solo per il re-render in caso di errore: qui SI applica il filtro
        # privacy. Il "d" usato per il salvataggio (sotto) resta invece
        # sempre non filtrato, altrimenti un salvataggio con privacy attiva
        # cancellerebbe per sempre lo strumento nascosto dal disco.
        try:
            d = apply_privacy_filter(_ld(), _ls())
        except Exception:
            d = {}
        return HTMLResponse(_render_eventi_page(
            d, _FS_PORTFOLIO_EVENT_TYPES,
            "📝 Operazioni di portafoglio", "operazioni_gestione",
            err_msg=msg,
        ))

    try:
        d = _ld()  # NON filtrato: puo' finire in save_data() più sotto
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


# ─── Routes: Liquidità gestione ───────────────────────────────────────────────

@router.get("/liquidita_gestione", response_class=HTMLResponse)
async def get_liquidita_gestione(tab: str = "edit", ok: str = "", err: str = ""):
    from persistence.storage import load_data as _ld, load_settings as _ls, apply_privacy_filter
    try:
        d = apply_privacy_filter(_ld(), _ls())
    except Exception as exc:
        d = {}
        err = str(exc)
    return HTMLResponse(_render_eventi_page(
        d, _FS_CASH_EVENT_TYPES,
        "💵 Movimenti di liquidità", "liquidita_gestione",
        ok_msg=ok, err_msg=err, active_tab=tab,
    ))


@router.post("/liquidita_gestione", response_class=HTMLResponse)
async def post_liquidita_gestione(
    azione: str = Form(""),
    event_id: str = Form(""),
    data_ev: str = Form("", alias="data"),
    note: str = Form(""),
    importo_lordo: str = Form("0"),
):
    from persistence.storage import load_data as _ld, load_settings as _ls, apply_privacy_filter, _safe_float
    from urllib.parse import quote as urlquote

    def err_page(msg: str) -> HTMLResponse:
        # Solo per il re-render in caso di errore: qui SI applica il filtro
        # privacy. Il "d" usato per il salvataggio (sotto) resta invece
        # sempre non filtrato, altrimenti un salvataggio con privacy attiva
        # cancellerebbe per sempre lo strumento nascosto dal disco.
        try:
            d = apply_privacy_filter(_ld(), _ls())
        except Exception:
            d = {}
        return HTMLResponse(_render_eventi_page(
            d, _FS_CASH_EVENT_TYPES,
            "💵 Movimenti di liquidità", "liquidita_gestione",
            err_msg=msg,
        ))

    try:
        d = _ld()  # NON filtrato: puo' finire in save_data() più sotto
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
