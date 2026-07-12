"""ui/form_server/privacy.py — pagina Privacy del form-server (route /privacy).

Estratto da form_server.py. Condivide la stessa pipeline di storage dell'app
principale: nessuna logica duplicata.
"""
from __future__ import annotations

import logging
from html import escape
from typing import Optional

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from ui.form_server.shell import CSS, STREAMLIT_URL

logger = logging.getLogger("portafoglio.form_server.privacy")

router = APIRouter()


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
{CSS}
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


@router.get("/privacy", response_class=HTMLResponse)
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


@router.post("/privacy", response_class=HTMLResponse)
async def post_privacy(
    enabled: Optional[str] = Form(None),
    hidden_tickers: list[str] = Form(default=[]),
    hidden_categories: list[str] = Form(default=[]),
):
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
