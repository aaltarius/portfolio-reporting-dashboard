"""ui/form_server/export_pp.py — pagina Export Portfolio Performance del form-server.

Estratto da form_server.py. Condivide la stessa pipeline di storage dell'app
principale: nessuna logica duplicata.
"""
from __future__ import annotations

import logging
from html import escape

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

from ui.form_server.shell import CSS, STREAMLIT_URL

logger = logging.getLogger("portafoglio.form_server.export_pp")

router = APIRouter()


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
{CSS}
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


@router.get("/export_pp", response_class=HTMLResponse)
async def get_export_pp():
    from persistence.storage import load_data as _ld
    try:
        d = _ld()
    except Exception:
        d = {}
    return HTMLResponse(_render_export_pp_page(d))


@router.get("/export_pp/transazioni")
async def get_export_pp_transazioni():
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


@router.get("/export_pp/prezzi")
async def get_export_pp_prezzi():
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
