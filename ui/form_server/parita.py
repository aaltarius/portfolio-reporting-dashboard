"""ui/form_server/parita.py — pagina «A parità di investimento» del form-server (route /parita, PA-01).

Sola lettura: carica i dati come le altre pagine del form-server, calcola con
core/services/parita_investimento.py solo su «Confronta» (POST) e non scrive nulla né apre la rete.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse

from core.services import parita_investimento as pi
from ui.form_server.parita_html import render_parita_page

logger = logging.getLogger("portafoglio.form_server.parita")

router = APIRouter()


def _load_market_data() -> dict:
    from persistence.storage import apply_privacy_filter, load_data, load_settings

    return apply_privacy_filter(load_data(), load_settings())


def _instrument_choices(data: dict) -> list[tuple[str, str]]:
    from persistence.storage import macro_cat

    out = []
    for s in data.get("strumenti") or []:
        tk = str(s.get("ticker") or "")
        if tk and macro_cat(str(s.get("tipo") or "")) in pi.PERIMETER:
            out.append((tk, str(s.get("nome") or tk)))
    return sorted(out, key=lambda x: x[0])


def _default_form(data: dict, choices: list[tuple[str, str]]) -> dict:
    days = [str(k)[:10] for k in (data.get("storico_prezzi") or {})]
    end = max(days) if days else date.today().isoformat()
    try:
        start = (date.fromisoformat(end) - timedelta(days=30)).isoformat()
    except ValueError:
        start = end
    return {"start": start, "end": end, "mode": "libero", "amount": "1000", "cap_ticker": "",
            "reference": choices[0][0] if choices else "", "units": "whole"}


@router.get("/parita", response_class=HTMLResponse)
async def get_parita():
    data = _load_market_data()
    choices = _instrument_choices(data)
    return HTMLResponse(render_parita_page(instruments=choices, form=_default_form(data, choices),
                                           resolved=None, result=None))


@router.post("/parita", response_class=HTMLResponse)
async def post_parita(
    start: str = Form(""), end: str = Form(""), mode: str = Form("libero"), amount: str = Form(""),
    cap_ticker: str = Form(""), reference: str = Form(""), units: str = Form("whole"),
):
    data = _load_market_data()
    choices = _instrument_choices(data)
    form = {"start": start, "end": end, "mode": mode, "amount": amount, "cap_ticker": cap_ticker,
            "reference": reference, "units": units}

    def page(err: str = "", resolved=None, result=None) -> HTMLResponse:
        return HTMLResponse(render_parita_page(instruments=choices, form=form, resolved=resolved,
                                               result=result, err_msg=err))

    try:
        amount_f = float(amount.replace(",", ".")) if amount.strip() else None
    except ValueError:
        amount_f = None
    try:
        resolved = pi.resolve_capital(data, mode, amount=amount_f, ticker=cap_ticker or None, start=start, end=end)
        if not resolved.usable:
            return page(resolved.message)
        result = pi.compare(data, start=start, end=end, capital=resolved.amount, reference=reference,
                            whole_units=(units != "theory"))
    except Exception:
        logger.exception("Confronto «a parità di investimento» fallito")
        return page("Calcolo non riuscito: controlla i dati e riprova.")
    if result.error:
        return page(result.error, resolved=resolved)
    return page(resolved=resolved, result=result)
