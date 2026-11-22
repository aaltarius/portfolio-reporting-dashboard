"""ui/form_server/pl_periodo.py — pagina «Andamento» del form-server (route /andamento, PL-01).

Sola lettura: carica i dati come le altre pagine, costruisce le serie con core/services/pl_periodo.py e le
consegna alla pagina; nessuna scrittura, nessuna rete.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from core.services.pl_periodo import build_pl_periodo
from ui.form_server.pl_periodo_html import render_pl_periodo_page

logger = logging.getLogger("portafoglio.form_server.pl_periodo")

router = APIRouter()


def _load_data() -> dict:
    from persistence.storage import apply_privacy_filter, load_data, load_settings

    return apply_privacy_filter(load_data(), load_settings())


@router.get("/andamento", response_class=HTMLResponse)
async def get_pl_periodo():
    try:
        result = build_pl_periodo(_load_data())
    except Exception:
        logger.exception("Calcolo del P/L del periodo fallito")
        return HTMLResponse(render_pl_periodo_page({"dates": [], "series": []}))
    payload = {"dates": result.dates, "deposits": result.deposits, "series": [
        {"t": s.ticker, "n": s.name, "tipo": s.tipo, "cat": s.category, "st": s.status,
         "total": s.total, "value": s.value, "bought": s.bought,
         "realized": s.realized, "income": s.income, "ops": [list(o) for o in s.operations]} for s in result.series]}
    return HTMLResponse(render_pl_periodo_page(payload))
