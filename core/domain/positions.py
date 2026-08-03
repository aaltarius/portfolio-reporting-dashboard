"""core/domain/positions.py — Stato del portafoglio e posizioni."""
from __future__ import annotations

from typing import Any
import pandas as pd
from datetime import datetime, date

from persistence.storage import (
    _safe_float,
    get_registro_eventi,
    _serialize_df_for_cache,
    _restore_df_from_cache,
    _portfolio_state_signature,
    _normalize_event_record,
    _rebuild_cash_ledger_from_events,
)
from core.validation import validate_evento_portafoglio
from core.domain._utils import _EPS
from typing import NamedTuple


class DischargeResult(NamedTuple):
    scarico_qty: float
    qty_dopo: float
    costo_dopo: float
    capitale_liberato: float
    plusvalenza_lorda: float
    plusvalenza_netta: float


def discharge_lot(
    qty_before: float,
    cost_before: float,
    quantita: float,
    prezzo_unitario: float,
    commissioni: float = 0.0,
    imposte: float = 0.0,
) -> DischargeResult:
    """Scarica una quantita' da una posizione al PMC corrente.

    Unica definizione canonica dello scarico PMC su VENDITA/RIMBORSO A
    SCADENZA: separa il capitale liberato (quota di costo storico che torna
    liquida, non e' reddito) dalla plusvalenza/minusvalenza netta
    (commissioni e imposte pesano solo su quest'ultima). Vale sempre
    l'invariante importo_netto == capitale_liberato + plusvalenza_netta.
    """
    qty_before = float(qty_before)
    cost_before = float(cost_before)
    scarico_qty = min(float(quantita), qty_before) if qty_before > 0 else 0.0
    pmc = (cost_before / qty_before) if qty_before > _EPS else 0.0
    capitale_liberato = scarico_qty * pmc
    plusvalenza_lorda = (scarico_qty * float(prezzo_unitario)) - capitale_liberato
    plusvalenza_netta = plusvalenza_lorda - float(commissioni) - float(imposte)
    return DischargeResult(
        scarico_qty=scarico_qty,
        qty_dopo=max(0.0, qty_before - scarico_qty),
        costo_dopo=max(0.0, cost_before - capitale_liberato),
        capitale_liberato=capitale_liberato,
        plusvalenza_lorda=plusvalenza_lorda,
        plusvalenza_netta=plusvalenza_netta,
    )


def _fmt_dt(value: Any) -> str:
    """Formattazione data per uso interno (senza dipendenza da ui.formatting)."""
    if not value:
        return "n/d"
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                value = datetime.strptime(value[:19], fmt)
                break
            except Exception:
                continue
    if hasattr(value, "day"):
        return f"{value.day:02d}/{value.month:02d}/{value.year} {getattr(value, 'hour', 0):02d}:{getattr(value, 'minute', 0):02d}"
    return str(value)


def get_cash_balance(data: dict[str, Any]) -> float:
    """Liquidity balance dal registro liquidita' (o ricostruito dagli eventi)."""
    ledger = data.get("registro_liquidita", []) or _rebuild_cash_ledger_from_events(get_registro_eventi(data))
    return float(sum(_safe_float(x.get("importo", 0)) for x in ledger))


def compute_portfolio_state(
    data: dict[str, Any],
    price_map: dict[str, float] | None = None,
    include_closed: bool = True,
) -> dict[str, Any]:
    """
    Builds portfolio position state from events.
    Returns: {df, liquidita, eventi}
    """
    price_map = price_map or {}
    signature = _portfolio_state_signature(data, price_map=price_map, include_closed=include_closed)
    cache_all = data.setdefault("cache_posizioni", {}) if isinstance(data, dict) else {}
    cache_bucket = cache_all.get("all") if include_closed else cache_all.get("open")
    if isinstance(cache_bucket, dict) and cache_bucket.get("signature") == signature:
        try:
            df_cached = _restore_df_from_cache(cache_bucket.get("rows", []))
            return {
                "df": df_cached,
                "liquidita": _safe_float(cache_bucket.get("liquidita", 0)),
                "eventi": get_registro_eventi(data),
                "eventi_arricchiti": [],
            }
        except Exception:
            pass

    eventi = get_registro_eventi(data)
    stato = {}
    liquidita = 0.0
    eventi_arricchiti: list[dict[str, Any]] = []
    for ev in eventi:
        tipo = ev.get("tipo_evento")
        tk = ev.get("ticker", "")
        qty = _safe_float(ev.get("quantita", 0))
        prezzo = _safe_float(ev.get("prezzo_unitario", 0))
        comm = _safe_float(ev.get("commissioni", 0))
        imp = _safe_float(ev.get("imposte", 0))
        netto = _safe_float(ev.get("importo_netto", 0))
        if tk and tk not in stato:
            stato[tk] = {
                "qty": 0.0,
                "cost": 0.0,
                "comm": 0.0,
                "realized_gross": 0.0,
                "realized_net": 0.0,
                "tax": 0.0,
                "dividendi_net": 0.0,
                "cedole_net": 0.0,
                "ultimo_evento": ev.get("data"),
            }
        if tipo == "ACQUISTO" and tk:
            stp = stato[tk]
            stp["qty"] += qty
            stp["cost"] += qty * prezzo + comm + imp
            stp["comm"] += comm
            stp["tax"] += imp
            stp["ultimo_evento"] = ev.get("data")
            liquidita += netto
        elif tipo in {"VENDITA", "RIMBORSO A SCADENZA"} and tk:
            stp = stato[tk]
            result = discharge_lot(
                stp.get("qty", 0.0), stp.get("cost", 0.0), qty, prezzo, comm, imp
            )
            stp["qty"] = result.qty_dopo
            stp["cost"] = result.costo_dopo
            stp["comm"] += comm
            stp["tax"] += imp
            stp["realized_gross"] += result.plusvalenza_lorda
            stp["realized_net"] += result.plusvalenza_netta
            stp["ultimo_evento"] = ev.get("data")
            liquidita += netto
            eventi_arricchiti.append({
                **ev,
                "capitale_liberato": result.capitale_liberato,
                "plusvalenza_lorda": result.plusvalenza_lorda,
                "plusvalenza_netta": result.plusvalenza_netta,
            })
        elif tipo in {"CEDOLA", "DIVIDENDO"}:
            if tk:
                stp = stato.setdefault(tk, {
                    "qty": 0.0, "cost": 0.0, "comm": 0.0, "realized_gross": 0.0, "realized_net": 0.0,
                    "tax": 0.0, "dividendi_net": 0.0, "cedole_net": 0.0, "ultimo_evento": ev.get("data")
                })
                if tipo == "CEDOLA":
                    stp["cedole_net"] += netto
                else:
                    stp["dividendi_net"] += netto
                stp["tax"] += imp
                stp["ultimo_evento"] = ev.get("data")
            liquidita += netto
        elif tipo == "VERSAMENTO":
            liquidita += abs(netto) if netto != 0 else abs(_safe_float(ev.get("importo_lordo", 0)))
        elif tipo in {"PRELIEVO", "COMMISSIONE", "IMPOSTA"}:
            base = netto if netto != 0 else -abs(_safe_float(ev.get("importo_lordo", 0)) or comm or imp)
            liquidita += base

    rows = []
    for s in data.get("strumenti", []):
        tk = s.get("ticker", "")
        stp = stato.get(tk, {"qty": 0.0, "cost": 0.0, "comm": 0.0, "realized_gross": 0.0, "realized_net": 0.0, "tax": 0.0, "dividendi_net": 0.0, "cedole_net": 0.0})
        qty = _safe_float(stp.get("qty", 0))
        if (not include_closed) and qty <= _EPS:
            continue
        price = _safe_float((price_map or {}).get(tk, s.get("prezzo", 0)))
        val = qty * price
        cost = _safe_float(stp.get("cost", 0))
        pmc = cost / qty if qty > _EPS else 0.0
        pl = val - cost
        pct = pl / abs(cost) if abs(cost) > _EPS else 0.0
        rows.append({
            "Ticker": tk,
            "Strumento": s.get("nome", tk),
            "Tipo": s.get("tipo", ""),
            "Quote": qty,
            "Prezzo": price,
            "PMC": pmc,
            "Controvalore": val,
            "Costo": cost,
            "Comm.": _safe_float(stp.get("comm", 0)),
            "P/L €": pl,
            "P/L %": pct,
            "P/L Realizzato Lordo": _safe_float(stp.get("realized_gross", 0)),
            "P/L Realizzato Netto": _safe_float(stp.get("realized_net", 0)),
            "Imposte €": _safe_float(stp.get("tax", 0)),
            "Cedole nette": _safe_float(stp.get("cedole_net", 0)),
            "Dividendi netti": _safe_float(stp.get("dividendi_net", 0)),
            "Ultimo evento": stp.get("ultimo_evento"),
        })
    df = pd.DataFrame(rows)
    cache_all["all" if include_closed else "open"] = {
        "signature": signature,
        "liquidita": liquidita,
        "rows": _serialize_df_for_cache(df),
        "updated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return {"df": df, "liquidita": liquidita, "eventi": eventi, "eventi_arricchiti": eventi_arricchiti}


def sync_realized_split_fields(data: dict[str, Any]) -> bool:
    """Riallinea capitale_liberato/plusvalenza_lorda/plusvalenza_netta sugli
    eventi VENDITA/RIMBORSO A SCADENZA persistiti in data['registro_eventi'].

    Va richiamata dopo ogni mutazione del registro eventi (append/modifica/
    cancellazione) e al caricamento dati. I valori persistiti sono una vista
    materializzata per display/audit: i calcoli finanziari (KPI, P/L, storico)
    ricalcolano sempre tramite discharge_lot()/compute_portfolio_state e non
    dipendono dalla presenza di questi campi. Idempotente: scrive solo se il
    valore persistito differisce da quello ricalcolato.
    """
    raw_eventi = data.get("registro_eventi") or []
    if not raw_eventi:
        return False
    original_cache_posizioni = data.get("cache_posizioni")
    data["cache_posizioni"] = {}
    state = compute_portfolio_state(data, include_closed=True)
    enriched_by_id = {
        str(ev.get("event_id") or ""): ev
        for ev in state.get("eventi_arricchiti", [])
    }
    changed = False
    for raw_ev in raw_eventi:
        norm_id = str(_normalize_event_record(raw_ev).get("event_id") or "")
        enriched = enriched_by_id.get(norm_id)
        if enriched is None:
            continue
        for field in ("capitale_liberato", "plusvalenza_lorda", "plusvalenza_netta"):
            new_value = round(float(enriched.get(field, 0.0)), 6)
            old_value = raw_ev.get(field)
            if old_value is None or round(_safe_float(old_value), 6) != new_value:
                raw_ev[field] = new_value
                changed = True
    if changed:
        data["cache_posizioni"] = {}
    else:
        # Nulla da correggere: non lasciare in giro un bucket ricalcolato al
        # volo (con updated_at fresco) al posto di quello pre-esistente, o
        # ogni chiamata (es. da load_data) risulterebbe "diversa" e
        # forzerebbe una riscrittura su disco anche a dati invariati.
        data["cache_posizioni"] = original_cache_posizioni if original_cache_posizioni is not None else {}
    return changed


def calc_positions(data: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Posizioni per ticker, forma slim (qty/cost/comm/realized_net/realized_gross/tax)."""
    state = compute_portfolio_state(data, include_closed=True)
    if state["df"].empty:
        return {}
    return state["df"].set_index("Ticker").apply(lambda row: {
        "qty": _safe_float(row.get("Quote", 0)),
        "cost": _safe_float(row.get("Costo", 0)),
        "comm": _safe_float(row.get("Comm.", 0)),
        "realized_net": _safe_float(row.get("P/L Realizzato Netto", 0)),
        "realized_gross": _safe_float(row.get("P/L Realizzato Lordo", 0)),
        "tax": _safe_float(row.get("Imposte €", 0)),
    }, axis=1).to_dict()


def build_ptf_df(data: dict[str, Any]) -> pd.DataFrame:
    """Build portfolio positions dataframe, con prezzo piu' recente dallo storico se disponibile."""
    storico = data.get("storico_prezzi", {})
    last_known = {}
    for d in sorted(storico.keys()):
        for tk, p in storico[d].items():
            if p:
                last_known[tk] = p
    state = compute_portfolio_state(data, price_map=last_known, include_closed=True)
    return state["df"] if isinstance(state.get("df"), pd.DataFrame) else pd.DataFrame()


def held_tickers(data: dict[str, Any]) -> frozenset[str]:
    """Ticker con quote correnti > 0, calcolate dagli eventi reali.

    Il campo `stato` sullo strumento non e' una fonte affidabile per "lo
    possiedo adesso": puo' restare "aperto" anche dopo una vendita totale se
    nessuno lo ha mai ritaggato manualmente. Le quote effettive calcolate da
    compute_portfolio_state riflettono sempre la realta' del registro eventi."""
    df = compute_portfolio_state(data, include_closed=True).get("df", pd.DataFrame())
    if df.empty or "Ticker" not in df.columns or "Quote" not in df.columns:
        return frozenset()
    qty = pd.to_numeric(df["Quote"], errors="coerce").fillna(0.0)
    return frozenset(df.loc[qty > _EPS, "Ticker"].astype(str))
