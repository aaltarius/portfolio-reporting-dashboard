"""core/services/operations_ledger.py — Registro unificato delle operazioni e sintesi per la scheda Operazioni.

Funzioni pure, senza rete né lettura di file.

* ``build_operations_ledger``: un'unica cronologia (dal più recente) che unisce operazioni di
  portafoglio e movimenti di cassa. Il versamento automatico che copre un acquisto
  (``strumento_collegato`` + stessa data, oppure ``linked_trade_event_id``) non è una riga a sé:
  diventa il campo ``cash_cover`` dell'acquisto, così «cosa ho comprato» e «quanto è entrato per
  pagarlo» stanno nella stessa riga.
* ``build_operations_summary``: totali dell'anno e da sempre, dagli stessi eventi.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any

#: tipo_evento -> tipo di riga usato dalla pagina
KIND_BY_EVENT: dict[str, str] = {
    "ACQUISTO": "acquisto",
    "VENDITA": "vendita",
    "RIMBORSO A SCADENZA": "rimborso",
    "CEDOLA": "cedola",
    "DIVIDENDO": "dividendo",
    "VERSAMENTO": "versamento",
    "PRELIEVO": "prelievo",
    "COMMISSIONE": "costo",
    "IMPOSTA": "costo",
}
TRADE_KINDS = ("acquisto", "vendita", "rimborso")


def _num(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _day(value: Any) -> str:
    return str(value or "")[:10]


def build_operations_ledger(
    eventi: list[dict[str, Any]] | None,
    info_map: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Righe del registro, dal più recente. ``info_map``: ticker -> strumento (nome, tipo)."""
    info_map = info_map or {}
    events = [ev for ev in (eventi or []) if isinstance(ev, dict) and ev.get("tipo_evento") in KIND_BY_EVENT]

    # --- versamenti collegati agli acquisti ---------------------------------------------------
    deposits = [
        ev for ev in events
        if ev.get("tipo_evento") == "VERSAMENTO" and (ev.get("strumento_collegato") or ev.get("linked_trade_event_id"))
    ]
    by_link = {str(ev.get("linked_trade_event_id")): ev for ev in deposits if ev.get("linked_trade_event_id")}
    pool: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for ev in deposits:
        if ev.get("linked_trade_event_id"):
            continue
        pool.setdefault((_day(ev.get("data")), str(ev.get("strumento_collegato") or "")), []).append(ev)

    cover_for: dict[str, dict[str, Any]] = {}
    folded: set[int] = set()
    for ev in events:
        if ev.get("tipo_evento") != "ACQUISTO":
            continue
        dep = by_link.get(str(ev.get("event_id")))
        if dep is None:
            candidates = pool.get((_day(ev.get("data")), str(ev.get("ticker") or "")), [])
            dep = candidates.pop(0) if candidates else None
        if dep is not None and id(dep) not in folded:
            cover_for[str(ev.get("event_id"))] = dep
            folded.add(id(dep))

    # --- righe ---------------------------------------------------------------------------------
    from core.asset_categories import infer_category_code

    rows: list[dict[str, Any]] = []
    for index, ev in enumerate(events):
        if id(ev) in folded:
            continue
        tipo = str(ev["tipo_evento"])
        ticker = str(ev.get("ticker") or ev.get("strumento_collegato") or "")
        strumento = info_map.get(ticker, {}) if ticker else {}
        dep = cover_for.get(str(ev.get("event_id")))
        net = _num(ev.get("importo_netto"))
        if not net and tipo in {"VERSAMENTO", "PRELIEVO", "COMMISSIONE", "IMPOSTA"}:
            net = _num(ev.get("importo_lordo"))
            net = -abs(net) if tipo in {"PRELIEVO", "COMMISSIONE", "IMPOSTA"} else abs(net)
        rows.append({
            "id": str(ev.get("event_id") or f"ev{index}"),
            "date": _day(ev.get("data")),
            "kind": KIND_BY_EVENT[tipo],
            "label": tipo.capitalize() if tipo != "RIMBORSO A SCADENZA" else "Rimborso a scadenza",
            "ticker": ticker,
            "name": str(strumento.get("nome") or ticker),
            "cat": infer_category_code(strumento.get("tipo", ""), default="") if strumento else "",
            "qty": _num(ev.get("quantita")) if tipo in {"ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA"} else 0.0,
            "price": _num(ev.get("prezzo_unitario")) if tipo in {"ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA"} else 0.0,
            "gross": _num(ev.get("importo_lordo")),
            "fees": _num(ev.get("commissioni")),
            "taxes": _num(ev.get("imposte", ev.get("imposta"))),
            "net": net,
            "note": str(ev.get("note") or "").strip(),
            "cover": _num(dep.get("importo_netto") or dep.get("importo_lordo")) if dep is not None else None,
            "_order": index,
        })
    rows.sort(key=lambda r: (r["date"], r["_order"]), reverse=True)
    for r in rows:
        r.pop("_order", None)
    return rows


def build_operations_summary(
    eventi: list[dict[str, Any]] | None,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Totali per l'anno in corso e da sempre. Importi sempre positivi (verso di marcia nel nome)."""
    year = str((today or date.today()).year)
    zero = lambda: {"operazioni": 0, "acquistato": 0.0, "incassato": 0.0, "costi": 0.0, "proventi": 0.0}  # noqa: E731
    out = {"anno": zero(), "totale": zero(), "year": int(year)}
    for ev in eventi or []:
        tipo = ev.get("tipo_evento") if isinstance(ev, dict) else None
        if tipo not in KIND_BY_EVENT:
            continue
        buckets = [out["totale"]] + ([out["anno"]] if _day(ev.get("data")).startswith(year) else [])
        net = _num(ev.get("importo_netto"))
        costs = _num(ev.get("commissioni")) + _num(ev.get("imposte", ev.get("imposta")))
        for b in buckets:
            if tipo in {"ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA"}:
                b["operazioni"] += 1
            if tipo == "ACQUISTO":
                b["acquistato"] += abs(net)
            elif tipo in {"VENDITA", "RIMBORSO A SCADENZA"}:
                b["incassato"] += max(net, 0.0)
            elif tipo in {"CEDOLA", "DIVIDENDO"}:
                b["proventi"] += net
            if tipo in {"COMMISSIONE", "IMPOSTA"}:
                b["costi"] += abs(_num(ev.get("importo_lordo")) or net)
            elif tipo in {"ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA", "CEDOLA", "DIVIDENDO"}:
                b["costi"] += max(costs, 0.0)
    return out
