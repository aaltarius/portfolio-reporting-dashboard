"""
core/finance.py — Logica finanziaria centrale.
"""
import copy
import hashlib
import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, date
from typing import Any

logger = logging.getLogger(__name__)

import numpy as np
import pandas as pd
import yfinance as yf
from core.asset_categories import ACTIVE_CATEGORY_CODES, get_selected_category_codes
from core.portfolio_metrics import calcola_flussi_capitale, calcola_kpi_principali
from core.render_profiler import profile_step, record_render_event
import time

from persistence.storage import (
    DATA_DIR,
    _safe_float,
    _event_sort_key,
    get_registro_eventi,
    _serialize_df_for_cache,
    _restore_df_from_cache,
    _portfolio_state_signature,
    _rebuild_cash_ledger_from_events,
    _normalize_event_record,
    _new_event_id,
    SCHEMA_VERSION,
    BENCH,
    macro_cat,
    _normalize_macro_label,
    default_settings,
    save_data,
)
from core.validation import validate_evento_portafoglio
from core.benchmark_registry import resolve_instrument_benchmark
from core.constants import QTY_ZERO_EPS

# ══════════════════════════════════════════════════════════════════════════════
# Re-exports from core/domain modules (backward compatibility shim)
# Functions have been migrated to domain-specific modules
# ══════════════════════════════════════════════════════════════════════════════

from core.domain.positions import (
    compute_portfolio_state,
    calc_positions,
    build_ptf_df,
    get_cash_balance,
    sync_realized_split_fields,
    discharge_lot,
)
from core.series_utils import build_category_return_index, build_value_curve_frame
from core.domain.cashflows import compute_xirr, build_xirr_flows, build_portfolio_external_xirr_flows
from core.domain.returns import (
    business_day_deltas,
    build_analysis_returns,
    compute_instrument_stats,
    _build_summary_return_curve,
    _period_returns_from_curve,
    compute_return_curve_metrics,
)
from core.domain.risk import build_drawdown_series

__all__ = [
    # Migrated to domain
    "compute_portfolio_state",
    "calc_positions",
    "build_ptf_df",
    "get_cash_balance",
    "compute_xirr",
    "build_xirr_flows",
    "build_portfolio_external_xirr_flows",
    "build_analysis_returns",
    "compute_instrument_stats",
    "_build_summary_return_curve",
    "_period_returns_from_curve",
    "compute_return_curve_metrics",
    "build_drawdown_series",
    # Remaining unmigrated functions
    "append_evento_portafoglio",
    "build_hist_df",
    "build_portfolio_history_df",
    "_apply_event_to_pos",
    "_fmt_dt",
]

# ══════════════════════════════════════════════════════════════════════════════
# Utilità private
# ══════════════════════════════════════════════════════════════════════════════

_EPS = 1e-12
EventDict = dict[str, Any]


def _resolve_finance_category_codes(settings: dict[str, Any] | None = None) -> list[str]:
    if settings is None:
        return list(ACTIVE_CATEGORY_CODES)
    return list(get_selected_category_codes(settings))


def _build_category_value_maps(
    da_frame: pd.DataFrame,
    total_value: float,
    categories: list[str],
) -> tuple[dict[str, float], dict[str, float]]:
    macro_alloc = {cat: 0.0 for cat in categories}
    macro_values = {cat: 0.0 for cat in categories}
    if da_frame is None or da_frame.empty or total_value <= 0:
        return macro_alloc, macro_values

    tmp = da_frame.copy()
    tmp["Controvalore"] = pd.to_numeric(tmp.get("Controvalore", pd.Series(dtype=float)), errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0)
    tmp["Categoria"] = tmp["Tipo"].apply(macro_cat)
    macro = tmp.groupby("Categoria")["Controvalore"].sum().reindex(categories).fillna(0.0)
    total_value = _safe_float(total_value)
    macro_values = {k: _safe_float(v) for k, v in macro.items()}
    macro_alloc = {k: (_safe_float(v) / total_value) if total_value > 0 else 0.0 for k, v in macro.items()}
    return macro_alloc, macro_values


def _build_category_history_records(cat_idx: pd.DataFrame, categories: list[str]) -> list[dict[str, Any]]:
    if cat_idx is None or cat_idx.empty:
        return []
    records: list[dict[str, Any]] = []
    for idx, row in cat_idx.sort_index().iterrows():
        payload = {"data": pd.to_datetime(idx).strftime("%d/%m/%Y")}
        for cat in categories:
            val = _safe_float(row.get(cat), default=np.nan)
            payload[cat] = float(val) if np.isfinite(val) else None
        records.append(payload)
    return records


def _finite_numeric_series(values: Any, default: float = 0.0) -> pd.Series:
    """Converte una sequenza numerica neutralizzando NaN, inf e -inf."""
    if values is None:
        return pd.Series(dtype=float)
    numeric = pd.to_numeric(values, errors="coerce")
    if not isinstance(numeric, pd.Series):
        numeric = pd.Series(numeric)
    return numeric.map(lambda value: _safe_float(value, default=default))


def _finite_column_sum(frame: pd.DataFrame, column: str) -> float:
    if frame is None or frame.empty or column not in frame.columns:
        return 0.0
    return float(_finite_numeric_series(frame[column], default=0.0).sum())


def _sanitize_dashboard_numeric_columns(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return frame
    for col in ("Quote", "Prezzo", "PMC", "Controvalore", "Costo", "P/L €", "P/L %"):
        if col in frame.columns:
            frame[col] = _finite_numeric_series(frame[col], default=0.0)
    return frame


def _weighted_average_finite(values: Any, weights: Any, default: float = np.nan) -> float:
    vals = _finite_numeric_series(values, default=np.nan)
    wts = _finite_numeric_series(weights, default=0.0)
    mask = vals.notna() & wts.notna() & (wts > 0)
    if not mask.any():
        return default
    try:
        result = np.average(vals[mask], weights=wts[mask])
    except Exception:
        return default
    return float(result) if np.isfinite(result) else default


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


# ══════════════════════════════════════════════════════════════════════════════
# Analisi ritorni e statistiche
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# Stato portafoglio
# ══════════════════════════════════════════════════════════════════════════════


def append_evento_portafoglio(data: dict[str, Any], evento: EventDict) -> EventDict:
    data.setdefault("registro_eventi", [])
    data.setdefault("registro_liquidita", [])
    ok, msg = validate_evento_portafoglio(data, evento)
    if not ok:
        raise ValueError(msg)
    ev = _normalize_event_record(evento)
    if not ev.get("event_id"):
        ev["event_id"] = _new_event_id(data)
    data["registro_eventi"].append(ev)
    data["registro_eventi"].sort(key=_event_sort_key)
    data["registro_liquidita"] = _rebuild_cash_ledger_from_events(data["registro_eventi"])
    tipo = ev.get("tipo_evento")
    if tipo in {"ACQUISTO", "VENDITA"}:
        data.setdefault("operazioni", []).append({
            "data": ev.get("data"), "ticker": ev.get("ticker", ""), "tipo": tipo,
            "qty": _safe_float(ev.get("quantita", 0)), "price": _safe_float(ev.get("prezzo_unitario", 0)),
            "comm": _safe_float(ev.get("commissioni", 0)), "note": ev.get("note", "")
        })
        data["operazioni"].sort(key=lambda x: x.get("data", ""))
    elif tipo in {"CEDOLA", "DIVIDENDO"}:
        lordo = _safe_float(ev.get("importo_lordo", 0))
        netto = _safe_float(ev.get("importo_netto", 0))
        aliquota = (_safe_float(ev.get("imposte", 0)) / lordo) if lordo > 0 else _safe_float(ev.get("aliquota", 0))
        data.setdefault("proventi", []).append({
            "data": ev.get("data"), "ticker": ev.get("ticker", ""), "tipo": tipo,
            "importo_lordo": lordo, "aliquota": aliquota,
            "importo_netto": netto, "note": ev.get("note", "")
        })
        data["proventi"].sort(key=lambda x: x.get("data", ""))
    sync_realized_split_fields(data)
    if tipo in {"VENDITA", "RIMBORSO A SCADENZA"}:
        raw_ev = next(
            (e for e in data["registro_eventi"] if e.get("event_id") == ev.get("event_id")),
            None,
        )
        if raw_ev is not None:
            for field in ("capitale_liberato", "plusvalenza_lorda", "plusvalenza_netta"):
                if field in raw_ev:
                    ev[field] = raw_ev[field]
    data["schema_version"] = SCHEMA_VERSION
    data["cache_posizioni"] = {}
    data["cache_storico_portafoglio"] = {}
    return ev


# ══════════════════════════════════════════════════════════════════════════════
# Build DataFrame portafoglio (privati) e storico prezzi (pubblico)
# ══════════════════════════════════════════════════════════════════════════════


def build_hist_df(data: dict[str, Any]) -> pd.DataFrame:
    st = data.get("storico_prezzi", {})
    if not st:
        return pd.DataFrame()
    tks = [s["ticker"] for s in data["strumenti"]]
    sorted_dates = sorted(st.keys())
    tk_to_idx = {tk: i for i, tk in enumerate(tks)}
    arr = np.full((len(sorted_dates), len(tks)), np.nan, dtype=np.float64)
    for row_i, d in enumerate(sorted_dates):
        for tk, val in st[d].items():
            col_j = tk_to_idx.get(tk)
            if col_j is not None and val is not None:
                price = _safe_float(val, default=np.nan)
                if np.isfinite(price) and price > 0:
                    arr[row_i, col_j] = price
    df = pd.DataFrame(arr, index=pd.to_datetime(sorted_dates), columns=tks)
    df.index.name = "Data"
    return df


def _apply_event_to_pos(
    ev: EventDict,
    pos: dict[str, dict[str, float]],
    cash: float,
    realized_gross_total: float,
    realized_net_total: float,
    taxes_total: float,
) -> tuple[float, float, float, float]:
    tipo = ev.get("tipo_evento")
    tk = ev.get("ticker", "")
    qty = _safe_float(ev.get("quantita", 0))
    prezzo = _safe_float(ev.get("prezzo_unitario", 0))
    netto = _safe_float(ev.get("importo_netto", 0))
    comm = _safe_float(ev.get("commissioni", 0))
    imp = _safe_float(ev.get("imposte", 0))
    if tk and tk not in pos:
        pos[tk] = {"qty": 0.0, "cost": 0.0, "realized_net": 0.0, "realized_gross": 0.0}
    if tipo == "ACQUISTO" and tk:
        pos[tk]["qty"] += qty
        pos[tk]["cost"] += qty * prezzo + comm + imp
        cash += netto
    elif tipo in {"VENDITA", "RIMBORSO A SCADENZA"} and tk:
        result = discharge_lot(pos[tk]["qty"], pos[tk]["cost"], qty, prezzo, comm, imp)
        pos[tk]["qty"] = result.qty_dopo
        pos[tk]["cost"] = result.costo_dopo
        pos[tk]["realized_gross"] += result.plusvalenza_lorda
        pos[tk]["realized_net"] += result.plusvalenza_netta
        realized_gross_total += result.plusvalenza_lorda
        realized_net_total += result.plusvalenza_netta
        taxes_total += imp
        cash += netto
    elif tipo in {"CEDOLA", "DIVIDENDO", "VERSAMENTO", "PRELIEVO", "COMMISSIONE", "IMPOSTA"}:
        cash += netto
        taxes_total += imp
    return cash, realized_gross_total, realized_net_total, taxes_total


def _build_portfolio_history_core(sto: dict, eventi: list) -> tuple[list[dict], dict]:
    """Righe storiche reali (mai dipendenti da strumenti[].prezzo) + stato
    finale (posizioni/cassa/capitale/realizzato/ultimo prezzo valido/
    indice eventi) necessario per costruire, se serve, la riga sintetica
    "oggi" con i prezzi correnti (Fase 2bis Parte A: la riga sintetica non
    e' mai cache-ata da questa funzione, quindi lo stato finale va sempre
    ricalcolato o riletto dalla cache insieme alle righe storiche)."""
    ds = sorted(sto.keys())
    hp: list[dict] = []
    pos: dict[str, dict[str, float]] = {}
    cash = 0.0
    capital_versato = 0.0
    realized_net_total = 0.0
    realized_gross_total = 0.0
    taxes_total = 0.0
    last_valid_prices: dict[str, float] = {}
    idx = 0
    eventi_ordinati = sorted(eventi, key=_event_sort_key)
    for d in ds:
        while idx < len(eventi_ordinati) and str(eventi_ordinati[idx].get("data", "")) <= d:
            ev = eventi_ordinati[idx]
            _tipo = ev.get("tipo_evento")
            if _tipo == "VERSAMENTO":
                _imp = _safe_float(ev.get("importo_netto", 0)) or _safe_float(ev.get("importo_lordo", 0))
                capital_versato += abs(_imp)
            elif _tipo == "PRELIEVO":
                _imp = _safe_float(ev.get("importo_netto", 0)) or _safe_float(ev.get("importo_lordo", 0))
                capital_versato -= abs(_imp)
            cash, realized_gross_total, realized_net_total, taxes_total = _apply_event_to_pos(
                ev, pos, cash, realized_gross_total, realized_net_total, taxes_total
            )
            idx += 1
        pd_day = sto[d]
        valore_aperto = 0.0
        costo_aperto = 0.0
        row = {"Data": pd.to_datetime(d)}
        for tk, stp in pos.items():
            prezzo_raw = _safe_float(pd_day.get(tk, None))
            if pd.notna(prezzo_raw) and prezzo_raw > 0:
                last_valid_prices[tk] = float(prezzo_raw)
                prezzo = float(prezzo_raw)
            else:
                prezzo = float(last_valid_prices.get(tk, 0.0))
            qty = _safe_float(stp.get("qty", 0))
            cost = _safe_float(stp.get("cost", 0))
            valore_aperto += qty * prezzo
            costo_aperto += cost
            if qty > 0:
                row[f"PL_{tk}"] = qty * prezzo - cost
        row["Valore"] = valore_aperto + cash
        row["Costo"] = costo_aperto
        row["Capitale"] = capital_versato
        row["Liquidità"] = cash
        row["P/L"] = row["Valore"] - capital_versato
        row["P/L Realizzato Netto"] = realized_net_total
        row["P/L Realizzato Lordo"] = realized_gross_total
        row["Imposte"] = taxes_total
        hp.append(row)
    final_state = {
        "pos": pos,
        "cash": cash,
        "capital_versato": capital_versato,
        "realized_net_total": realized_net_total,
        "realized_gross_total": realized_gross_total,
        "taxes_total": taxes_total,
        "last_valid_prices": last_valid_prices,
        "idx": idx,
    }
    return hp, final_state


def _build_synthetic_today_row(
    data: dict[str, Any],
    ds: list,
    today_date,
    today_str: str,
    eventi_ordinati: list,
    final_state: dict,
) -> dict | None:
    """Riga sintetica "oggi" con i prezzi correnti (Fase 2bis Parte A):
    UNICO punto della pipeline che dipende da strumenti[].prezzo, per
    questo non va mai cache-ata — ricalcolata fresca ad ogni chiamata,
    economica (O(posizioni aperte), non O(giorni storico x strumenti)).

    Punto sintetico "oggi" solo su weekday, se lo storico non e' ancora
    aggiornato a oggi (snapshot infragiornaliero prima che arrivi la
    chiusura). Nel weekend niente: un refresh sabato/domenica scrive gia'
    i prezzi nell'ultimo giorno di borsa reale
    (_apply_price_date_entries_to_storico in ui/sidebar.py), quindi
    l'ultima riga storica e' gia' allineata - aggiungere qui un'altra riga
    etichettata con la data odierna duplicava lo stesso valore sotto una
    data di mercato chiuso, facendo sembrare sabato/domenica un giorno di
    trading reale.
    """
    is_weekday = today_date.weekday() < 5  # 0-4 = lunedì-venerdì, 5-6 = sabato-domenica
    if not (ds and ds[-1] < today_str and is_weekday):
        return None
    # ATTENZIONE - copia PROFONDA obbligatoria, non shallow: final_state
    # puo' essere lo stesso oggetto salvato dentro
    # data["cache_storico_portafoglio"]["final_state"] (riletto da cache
    # invariata tra una chiamata e l'altra). Il while sotto muta pos[tk]
    # IN PLACE (via _apply_event_to_pos, che fa pos[tk]["qty"] += ...,
    # non pos[tk] = {...}) per applicare gli eventi datati dopo l'ultimo
    # giorno di storico reale ma non oltre oggi. Senza deepcopy, una
    # seconda chiamata con lo stesso final_state cache-ato riapplicherebbe
    # quegli eventi una seconda volta sopra a uno stato gia' mutato dalla
    # chiamata precedente - un doppio conteggio silenzioso. Una copia
    # shallow (dict(...)) non basta: i dizionari interni per-ticker
    # resterebbero comunque condivisi con l'originale.
    pos = copy.deepcopy(final_state["pos"])
    cash = final_state["cash"]
    capital_versato = final_state["capital_versato"]
    realized_net_total = final_state["realized_net_total"]
    realized_gross_total = final_state["realized_gross_total"]
    taxes_total = final_state["taxes_total"]
    last_valid_prices = dict(final_state["last_valid_prices"])
    idx = final_state["idx"]
    while idx < len(eventi_ordinati):
        ev = eventi_ordinati[idx]
        _tipo = ev.get("tipo_evento")
        if _tipo == "VERSAMENTO":
            _imp = _safe_float(ev.get("importo_netto", 0)) or _safe_float(ev.get("importo_lordo", 0))
            capital_versato += abs(_imp)
        elif _tipo == "PRELIEVO":
            _imp = _safe_float(ev.get("importo_netto", 0)) or _safe_float(ev.get("importo_lordo", 0))
            capital_versato -= abs(_imp)
        cash, realized_gross_total, realized_net_total, taxes_total = _apply_event_to_pos(
            ev, pos, cash, realized_gross_total, realized_net_total, taxes_total
        )
        idx += 1
    cur_prices = {s["ticker"]: _safe_float(s.get("prezzo", 0)) for s in data.get("strumenti", [])}
    valore_aperto_t = 0.0
    costo_aperto_t = 0.0
    row_today = {"Data": pd.to_datetime(today_str)}
    for tk, stp in pos.items():
        prezzo_raw = cur_prices.get(tk, 0.0)
        if pd.notna(prezzo_raw) and prezzo_raw > 0:
            last_valid_prices[tk] = float(prezzo_raw)
            pr = float(prezzo_raw)
        else:
            pr = float(last_valid_prices.get(tk, 0.0))
        q = _safe_float(stp.get("qty", 0))
        c = _safe_float(stp.get("cost", 0))
        valore_aperto_t += q * pr
        costo_aperto_t += c
        if q > 0:
            row_today[f"PL_{tk}"] = q * pr - c
    row_today["Valore"] = valore_aperto_t + cash
    row_today["Costo"] = costo_aperto_t
    row_today["Capitale"] = capital_versato
    row_today["Liquidità"] = cash
    row_today["P/L"] = row_today["Valore"] - capital_versato
    row_today["P/L Realizzato Netto"] = realized_net_total
    row_today["P/L Realizzato Lordo"] = realized_gross_total
    row_today["Imposte"] = taxes_total
    return row_today


def build_portfolio_history_df(data: dict[str, Any]) -> pd.DataFrame:
    sto = data.get("storico_prezzi", {})
    if not sto:
        return pd.DataFrame()
    eventi = get_registro_eventi(data)
    eventi_ordinati = sorted(eventi, key=_event_sort_key)

    event_sig = hashlib.md5(json.dumps(eventi, sort_keys=True, default=str).encode()).hexdigest()
    # Fase 2bis Parte A: la firma della cache storica NON include piu' i
    # prezzi correnti ne' la data odierna - dipende solo da storico_prezzi
    # ed eventi, gli unici due input di cui le righe storiche sono
    # davvero funzione. I prezzi correnti influenzano solo la riga
    # sintetica "oggi" sotto, mai cache-ata.
    hist_sig = hashlib.md5(json.dumps({"sto": sto}, sort_keys=True, default=str).encode()).hexdigest()
    cache_sig = f"portfolio_history_v6|{event_sig}|{hist_sig}"

    cache = data.get("cache_storico_portafoglio", {}) or {}
    hp: list[dict] | None = None
    final_state: dict | None = None
    if cache.get("signature") == cache_sig and cache.get("rows") is not None and cache.get("final_state") is not None:
        try:
            cached_rows = cache.get("rows", [])
            hp = [
                {k: (pd.to_datetime(v) if k == "Data" else v) for k, v in r.items()}
                for r in cached_rows
            ]
            final_state = cache["final_state"]
        except Exception as e:
            logger.debug("cache restore fallback: %s", e)
            hp = None
            final_state = None

    if hp is None or final_state is None:
        hp, final_state = _build_portfolio_history_core(sto, eventi)
        data["cache_storico_portafoglio"] = {
            "signature": cache_sig,
            "rows": [{k: (v.strftime("%Y-%m-%d") if isinstance(v, pd.Timestamp) else v) for k, v in r.items()} for r in hp],
            "final_state": final_state,
        }

    ds = sorted(sto.keys())
    today_date = date.today()
    today_str = today_date.strftime("%Y-%m-%d")
    row_today = _build_synthetic_today_row(data, ds, today_date, today_str, eventi_ordinati, final_state)
    result_rows = list(hp)
    if row_today is not None:
        result_rows.append(row_today)
    return pd.DataFrame(result_rows)


# ══════════════════════════════════════════════════════════════════════════════
# Snapshot
# ══════════════════════════════════════════════════════════════════════════════

def _build_snapshot_from_data(data: dict[str, Any], label: str = "Snapshot automatico") -> dict[str, Any]:
    da = build_ptf_df(data)
    total_value = float(pd.to_numeric(da.get("Controvalore", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()) if not da.empty else 0.0
    total_cost = float(pd.to_numeric(da.get("Costo", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()) if not da.empty else 0.0
    macro_weights = {"GOV": 0.0, "ETF": 0.0, "FND": 0.0}
    holdings = []
    if not da.empty and total_value > 0:
        tmp = da.copy()
        tmp["Categoria"] = tmp["Tipo"].apply(macro_cat)
        grp = tmp.groupby("Categoria")["Controvalore"].sum()
        for k in macro_weights:
            macro_weights[k] = float(grp.get(k, 0.0)) / total_value if total_value > 0 else 0.0
        holdings = da.apply(lambda r: {
            "ticker": r["Ticker"],
            "strumento": r["Strumento"],
            "categoria": macro_cat(r["Tipo"]),
            "weight": float(r["Controvalore"]) / total_value if total_value > 0 else 0.0,
            "market_value": float(r["Controvalore"])
        }, axis=1).tolist()
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    return {
        "snapshot_id": f"snap_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "portfolio_id": "main",
        "label": label,
        "created_at": ts,
        "total_value": total_value,
        "total_cost": total_cost,
        "total_pl": total_value - total_cost,
        "macro_weights": macro_weights,
        "holdings": holdings,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Benchmark
# ══════════════════════════════════════════════════════════════════════════════

_BENCHMARK_SERIES_CACHE_DIR = os.path.join(DATA_DIR, "cache", "derived_runtime", "benchmark_series")


def get_cached_benchmark_series(
    data: dict[str, Any],
    bench_ticker: str,
    min_start: Any = None,
    period: str = "2y",
) -> pd.Series:
    """Restituisce la serie benchmark da cache; scarica solo se assente.

    Profilazione: registra cache hit / download yfinance per verificare se la lentezza
    deriva da benchmark riscaricati durante Summary/Analisi/Quotazioni.
    """
    t0 = time.perf_counter()
    if not bench_ticker:
        return pd.Series(dtype=float)
    bkey = f"bench_{bench_ticker}"
    had_cache = bkey in data.get("benchmark_data", {}) and bool(data.get("benchmark_data", {}).get(bkey, {}))
    if not had_cache:
        try:
            with profile_step("Core/Benchmark", "scaricamento benchmark yfinance", detail=f"ticker={bench_ticker}; period={period}"):
                bd = yf.Ticker(bench_ticker).history(period=period)
            if not bd.empty:
                data.setdefault("benchmark_data", {})[bkey] = {str(d.date()): float(v) for d, v in bd["Close"].items()}
                with profile_step("Core/Benchmark", "save_data benchmark", detail=f"ticker={bench_ticker}; punti={len(bd)}"):
                    from persistence.storage import save_benchmark_data
                    save_benchmark_data(data)
        except Exception as e:
            record_render_event(
                "Core/Benchmark",
                "download benchmark fallito",
                time.perf_counter() - t0,
                status="WARNING",
                detail=f"{bench_ticker}; {type(e).__name__}: {e}",
            )
            logger.warning("benchmark cache save failed: %s", e)
    bd = data.get("benchmark_data", {}).get(bkey, {})
    if had_cache:
        record_render_event(
            "Core/Benchmark",
            "benchmark cache hit",
            time.perf_counter() - t0,
            detail=f"ticker={bench_ticker}; punti={len(bd)}; min_start={min_start}",
            count=len(bd),
        )
    if not bd:
        return pd.Series(dtype=float)
    runtime_cache = data.setdefault("_runtime_benchmark_series_cache", {})
    cache_id = f"{bench_ticker}|{len(bd)}|{max(bd.keys(), default='')}"
    ser = runtime_cache.get(cache_id)
    if ser is None:
        os.makedirs(_BENCHMARK_SERIES_CACHE_DIR, exist_ok=True)
        persist_sig = hashlib.md5(cache_id.encode()).hexdigest()[:16]
        persist_path = os.path.join(_BENCHMARK_SERIES_CACHE_DIR, f"{bench_ticker}_{persist_sig}.pkl")
        persisted = None
        if os.path.exists(persist_path):
            try:
                persisted = pd.read_pickle(persist_path)
            except Exception:
                persisted = None
        if isinstance(persisted, dict) and persisted.get("cache_id") == cache_id:
            persisted_value = persisted.get("value")
            if isinstance(persisted_value, pd.Series):
                ser = persisted_value.sort_index()
                record_render_event(
                    "Core/Benchmark",
                    "benchmark raw persisted hit",
                    0.0,
                    detail=f"ticker={bench_ticker}; sig={persist_sig}; punti={len(ser)}",
                    count=len(ser),
                )
        if ser is None:
            with profile_step("Core/Benchmark", "conversione benchmark JSON->Series", detail=f"ticker={bench_ticker}; punti={len(bd)}", count=len(bd)):
                # Vettorizzato: pd.to_datetime() sull'intero elenco di chiavi in
                # un colpo solo, invece che una volta per punto in una dict
                # comprehension (stesso pattern gia' corretto in ranges.py e
                # time_buttons.py: profilato a 0.3-0.5s per benchmark, fino a
                # ~5s quando si aggiornano tutti i benchmark in un refresh).
                ser = pd.Series(list(bd.values()), index=pd.to_datetime(list(bd.keys())), dtype=float).sort_index()
                ser = ser[ser > 0]
            try:
                pd.to_pickle({"cache_id": cache_id, "value": ser.copy()}, persist_path)
                from core.derived_cache_utils import prune_sibling_pkl
                prune_sibling_pkl(_BENCHMARK_SERIES_CACHE_DIR, bench_ticker, persist_path)
            except Exception:
                pass
        runtime_cache[cache_id] = ser
    if min_start is not None and ser is not None and not ser.empty:
        return ser[ser.index >= pd.to_datetime(min_start)]
    return ser.copy() if ser is not None else pd.Series(dtype=float)


def refresh_benchmark_cache(data: dict[str, Any], period: str = "2y", force: bool = False) -> int:
    """Aggiorna la cache benchmark per gli strumenti presenti, se mancante o stale."""
    benchmark_data = data.setdefault("benchmark_data", {})
    target_tickers = {
        resolve_instrument_benchmark(item, prefer_master=False).ticker
        for item in data.get("strumenti", [])
        if isinstance(item, dict)
    }
    target_tickers = {tk for tk in target_tickers if tk}
    if not target_tickers:
        return 0

    today = datetime.now().date()
    refreshed = 0
    changed = False
    for bench_ticker in sorted(target_tickers):
        bkey = f"bench_{bench_ticker}"
        existing = benchmark_data.get(bkey, {}) if isinstance(benchmark_data.get(bkey), dict) else {}
        valid_dates = []
        for raw_date, raw_value in existing.items():
            if raw_value is None or pd.isna(raw_value):
                continue
            try:
                valid_dates.append(pd.to_datetime(raw_date).date())
            except Exception:
                continue
        needs_refresh = force or not existing
        if valid_dates and not force:
            last_valid = max(valid_dates)
            needs_refresh = (today - last_valid).days > 1
        if not needs_refresh:
            continue
        try:
            bd = yf.Ticker(bench_ticker).history(period=period)
            if bd.empty:
                continue
            fresh = {str(d.date()): float(v) for d, v in bd["Close"].items()}
            merged = {**existing, **fresh}
            if merged != existing:
                benchmark_data[bkey] = merged
                refreshed += 1
                changed = True
        except Exception as e:
            logger.warning("benchmark refresh failed for %s: %s", bench_ticker, e)
    if changed:
        from persistence.storage import save_benchmark_data
        save_benchmark_data(data)
    return refreshed


PORTFOLIO_BENCH_OPTIONS = [
    "Blend automatico",
    "60/40 MSCI World / Bond",
    "100% MSCI World",
    "100% GOV",
]

CUSTOM_BENCHMARK_LABEL = "Benchmark personalizzato"
CUSTOM_BENCHMARK_COMPONENT_OPTIONS = {
    "MSCI World (IWDA.AS)": "IWDA.AS",
    "Bond Emergenti (EMB)": "EMB",
    "GOV proxy (EMB)": "EMB",
    "Aggregate Bond EUR Hedged (AGGH)": "AGGH",
}

BENCHMARK_TICKER_FALLBACKS = {
    "BTI.MI": "EMB",
}


def get_effective_portfolio_benchmark_label(settings: dict[str, Any] | None) -> str:
    """Restituisce l'etichetta benchmark effettivamente attiva.

    Delega a core.services.benchmark (implementazione canonica). Import
    locale per evitare cicli: core.services.* a volte importa core.finance
    con import locale per lo stesso motivo (vedi Global Constraints)."""
    from core.services.benchmark import get_effective_portfolio_benchmark_label as _canonical
    return _canonical(settings)


def _resolve_custom_benchmark_components(settings: dict[str, Any] | None) -> list[tuple[str, float]]:
    """Normalizza i componenti del benchmark personalizzato."""
    if not isinstance(settings, dict):
        return []
    benchmarking = settings.get("benchmarking", {}) if isinstance(settings.get("benchmarking", {}), dict) else {}
    if not bool(benchmarking.get("custom_enabled", False)):
        return []
    raw_components = benchmarking.get("custom_components", [])
    if not isinstance(raw_components, list):
        return []
    normalized: list[tuple[str, float]] = []
    for item in raw_components:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker", "")).strip()
        try:
            weight = float(item.get("weight", 0) or 0)
        except (TypeError, ValueError):
            weight = 0.0
        if ticker and weight > 0:
            ticker = BENCHMARK_TICKER_FALLBACKS.get(ticker, ticker)
            normalized.append((ticker, weight))
    return normalized


def get_effective_portfolio_benchmark_config(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Restituisce la configurazione benchmark effettiva in forma pronta per UI/report."""
    label = get_effective_portfolio_benchmark_label(settings)
    raw_components = _resolve_custom_benchmark_components(settings)
    total_weight = sum(weight for _ticker, weight in raw_components)
    components = []
    for ticker, weight in raw_components:
        component_label = next(
            (name for name, mapped_ticker in CUSTOM_BENCHMARK_COMPONENT_OPTIONS.items() if mapped_ticker == ticker),
            ticker,
        )
        norm_weight = (weight / total_weight) if total_weight > 0 else 0.0
        components.append({
            "ticker": ticker,
            "label": component_label,
            "weight": float(norm_weight),
        })
    return {
        "label": label,
        "is_custom": bool(raw_components),
        "components": components,
    }


def build_portfolio_benchmark_series(
    data: dict[str, Any],
    bench_label: str,
    da_frame: pd.DataFrame,
    min_date: Any = None,
    settings: dict[str, Any] | None = None,
) -> pd.Series:
    """
    Costruisce una serie benchmark normalizzata a 100 alla min_date.
    """
    total = float(pd.to_numeric(da_frame["Controvalore"], errors="coerce").fillna(0).sum()) if da_frame is not None and not da_frame.empty else 0.0

    custom_components = _resolve_custom_benchmark_components(settings)
    if custom_components:
        components = custom_components
    elif bench_label == "Blend automatico":
        if total <= 0:
            return pd.Series(dtype=float)
        gov_w = float(
            pd.to_numeric(
                da_frame[da_frame["Tipo"].apply(macro_cat) == "GOV"]["Controvalore"],
                errors="coerce"
            ).fillna(0).sum()
        ) / total
        other_w = 1.0 - gov_w
        components = []
        if gov_w > 0.001:
            components.append(("EMB", gov_w))
        if other_w > 0.001:
            components.append(("IWDA.AS", other_w))
    elif bench_label == "60/40 MSCI World / Bond":
        components = [("IWDA.AS", 0.60), ("EMB", 0.40)]
    elif bench_label == "100% MSCI World":
        components = [("IWDA.AS", 1.0)]
    elif bench_label == "100% GOV":
        components = [(BENCHMARK_TICKER_FALLBACKS.get("BTI.MI", "EMB"), 1.0)]
    else:
        return pd.Series(dtype=float)

    if not components:
        return pd.Series(dtype=float)

    # Accorpa eventuali componenti duplicati dello stesso ticker.
    # Esempio reale: due righe IWDA.AS nel benchmark personalizzato non devono
    # produrre due serie distinte, ma un unico peso complessivo.
    weights_by_ticker: dict[str, float] = {}
    for ticker, weight in components:
        try:
            w = float(weight or 0.0)
        except Exception:
            w = 0.0
        if not ticker or w <= 0:
            continue
        weights_by_ticker[str(ticker)] = weights_by_ticker.get(str(ticker), 0.0) + w

    if not weights_by_ticker:
        return pd.Series(dtype=float)

    benchmark_data = data.get("benchmark_data", {}) if isinstance(data, dict) else {}
    blend_cache = data.setdefault("_runtime_portfolio_benchmark_blend_cache", {})
    component_state = {
        ticker: {
            "weight": round(float(weights_by_ticker.get(ticker, 0.0)), 10),
            "points": len(benchmark_data.get(f"bench_{ticker}", {}) or {}),
            "last_date": max((benchmark_data.get(f"bench_{ticker}", {}) or {}).keys(), default=""),
        }
        for ticker in sorted(weights_by_ticker.keys())
    }
    blend_cache_key = hashlib.md5(
        json.dumps(
            {
                "bench_label": str(bench_label or ""),
                "components": component_state,
            },
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()[:16]
    cached_blended = blend_cache.get(blend_cache_key)
    if isinstance(cached_blended, pd.Series) and not cached_blended.empty:
        record_render_event(
            "Core/Benchmark",
            "benchmark blend cache hit",
            0.0,
            detail=f"sig={blend_cache_key}; componenti={list(component_state.keys())}",
            count=len(cached_blended),
        )
        if min_date is not None:
            sliced_cached = cached_blended[cached_blended.index >= pd.to_datetime(min_date)]
            return sliced_cached.copy() if sliced_cached is not None else pd.Series(dtype=float)
        return cached_blended.copy()

    raw_parts: dict[str, pd.Series] = {}
    with profile_step("Core/Benchmark", "build_portfolio_benchmark_series / carica componenti", detail=f"componenti={list(weights_by_ticker.keys())}", count=len(weights_by_ticker)):
        for ticker in weights_by_ticker:
            ser = get_cached_benchmark_series(data, ticker, min_start=None)
            if ser is None or ser.empty:
                continue
            ser = pd.to_numeric(ser, errors="coerce").sort_index().dropna()
            if len(ser) < 2:
                continue
            raw_parts[ticker] = ser

    if not raw_parts:
        return pd.Series(dtype=float)

    with profile_step("Core/Benchmark", "concat/allineamento componenti benchmark", count=len(raw_parts)):
        raw_df = pd.concat(raw_parts, axis=1, sort=False).sort_index()

    # I mercati dei componenti benchmark non hanno tutti lo stesso calendario.
    # Se si sommano le serie con fill_value=0, nei giorni di chiusura di un
    # componente il benchmark crolla artificialmente del suo peso e poi rimbalza.
    # La logica corretta è mantenere l'ultima quotazione disponibile del
    # componente chiuso, senza creare rendimenti fittizi.
    with profile_step("Core/Benchmark", "ffill/dropna calendario benchmark", detail=f"shape_pre={raw_df.shape}"):
        raw_df = raw_df.ffill().dropna(how="any")
    if raw_df.empty:
        return pd.Series(dtype=float)

    weights = pd.Series(weights_by_ticker, dtype=float).reindex(raw_df.columns).fillna(0.0)
    total_w = float(weights.sum())
    if total_w <= 0:
        return pd.Series(dtype=float)
    weights = weights / total_w

    with profile_step("Core/Benchmark", "normalizzazione benchmark base100", detail=f"shape={raw_df.shape}"):
        norm_df = raw_df.divide(raw_df.iloc[0]).multiply(100.0)

    # Protezione anti-spike da singola quotazione errata.
    # Non rimuove grandi movimenti di mercato confermati, ma corregge il caso
    # tipico di un punto isolato che sale/scende molto e rientra subito il giorno
    # successivo, visivamente evidente nei benchmark.
    for col in norm_df.columns:
        s = pd.to_numeric(norm_df[col], errors="coerce").copy()
        ret_prev = s.pct_change()
        ret_next = s.shift(-1) / s - 1.0
        isolated_spike = (ret_prev.abs() > 0.10) & (ret_next.abs() > 0.10) & ((ret_prev * ret_next) < 0)
        if bool(isolated_spike.any()):
            s.loc[isolated_spike] = np.nan
            norm_df[col] = s.interpolate(method="time").ffill().bfill()

    with profile_step("Core/Benchmark", "blend benchmark pesato", detail=f"componenti={list(norm_df.columns)}"):
        blended = norm_df.mul(weights, axis=1).sum(axis=1)

    if min_date is not None:
        blended = blended[blended.index >= pd.to_datetime(min_date)]

    blended = pd.to_numeric(blended, errors="coerce").dropna()
    if blended.empty:
        return pd.Series(dtype=float)

    blend_cache[blend_cache_key] = blended.copy()
    return blended


# ══════════════════════════════════════════════════════════════════════════════
# Snapshot comparison e summary
# ══════════════════════════════════════════════════════════════════════════════

def _format_portfolio_objective_label(portfolio_objective: dict[str, float] | None) -> str:
    obj = portfolio_objective or {}
    core = round(float(obj.get("core", 0.0)) * 100)
    difensivo = round(float(obj.get("difensivo", 0.0)) * 100)
    satellite = round(float(obj.get("satellite", 0.0)) * 100)
    return f"Core {core}% / Difensivo {difensivo}% / Satellite {satellite}%"


def build_risk_contribution_table(da_frame: pd.DataFrame, returns_df: pd.DataFrame) -> pd.DataFrame:
    if da_frame is None or da_frame.empty or returns_df is None or returns_df.empty:
        return pd.DataFrame()
    work = da_frame.copy()
    work = work[pd.to_numeric(work["Controvalore"], errors="coerce").fillna(0) > 0].copy()
    if work.empty:
        return pd.DataFrame()
    tickers = [tk for tk in work["Ticker"] if tk in returns_df.columns]
    if len(tickers) < 2:
        return pd.DataFrame()
    ret = returns_df[tickers].dropna(how="all").copy()
    ret = ret.fillna(0.0)
    if len(ret) < 3:
        return pd.DataFrame()
    values = pd.to_numeric(work.set_index("Ticker").loc[tickers, "Controvalore"], errors="coerce").fillna(0.0)
    total_value = float(values.sum())
    if total_value <= 0:
        return pd.DataFrame()
    w = (values / total_value).astype(float)
    cov = ret.cov().values * 252.0
    wv = w.values.reshape(-1, 1)
    port_var = float((wv.T @ cov @ wv)[0, 0])
    if not np.isfinite(port_var) or port_var <= 0:
        return pd.DataFrame()
    mc_var = cov @ w.values
    rc_var = w.values * mc_var
    out = work.set_index("Ticker").loc[tickers, ["Strumento", "Tipo", "Controvalore"]].copy().reset_index()
    out["Peso %"] = w.values
    out["Contributo rischio %"] = rc_var / port_var
    out["Rapporto rischio/peso"] = out["Contributo rischio %"] / out["Peso %"].replace(0, np.nan)
    out["Volatilità stimata"] = np.sqrt(np.diag(cov))
    out["Categoria"] = out["Tipo"].apply(macro_cat)
    return out[["Ticker", "Strumento", "Categoria", "Controvalore", "Peso %", "Contributo rischio %", "Rapporto rischio/peso", "Volatilità stimata"]].sort_values("Contributo rischio %", ascending=False)


# ══════════════════════════════════════════════════════════════════════════════
# IRR / XIRR
# ══════════════════════════════════════════════════════════════════════════════
# compute_xirr / build_xirr_flows: ri-esportate da core.domain.cashflows
# (vedi import a inizio file).


# ══════════════════════════════════════════════════════════════════════════════
# Proventi
# ══════════════════════════════════════════════════════════════════════════════

def build_proventi_summary(proventi: list[dict[str, Any]], info_map: dict[str, dict[str, Any]]) -> pd.DataFrame:
    """Aggrega i proventi per ticker."""
    if not proventi:
        return pd.DataFrame(columns=["Ticker", "Strumento", "N", "Lordo totale", "Ritenute", "Netto totale"])
    agg = defaultdict(lambda: {"N": 0, "Lordo": 0.0, "Ritenute": 0.0, "Netto": 0.0})
    for p in proventi:
        tk = p.get("ticker", "")
        lordo = _safe_float(p.get("importo_lordo", 0))
        netto = _safe_float(p.get("importo_netto", 0))
        agg[tk]["N"] += 1
        agg[tk]["Lordo"] += lordo
        agg[tk]["Ritenute"] += lordo - netto
        agg[tk]["Netto"] += netto
    rows = []
    for tk, v in agg.items():
        rows.append({
            "Ticker": tk,
            "Strumento": info_map.get(tk, {}).get("nome", tk),
            "N": v["N"],
            "Lordo totale": v["Lordo"],
            "Ritenute": v["Ritenute"],
            "Netto totale": v["Netto"],
        })
    return pd.DataFrame(rows).sort_values("Netto totale", ascending=False).reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════════
# GOV / Titoli di Stato
# ══════════════════════════════════════════════════════════════════════════════

def extract_gov_maturity_date(name: Any) -> date | None:
    txt = str(name or "").upper().strip()
    month_map = {
        "GE": 1, "GN": 1, "JAN": 1,
        "FB": 2, "FE": 2, "FEB": 2,
        "MR": 3, "MZ": 3, "MAR": 3,
        "AP": 4, "AV": 4, "APR": 4,
        "MG": 5, "MA": 5, "MAY": 5,
        "GI": 6, "JU": 6, "JUN": 6,
        "LG": 7, "JL": 7, "JUL": 7,
        "AG": 8, "AU": 8, "AUG": 8,
        "ST": 9, "SE": 9, "SET": 9, "SEP": 9,
        "OT": 10, "OC": 10, "OTT": 10, "OCT": 10,
        "NV": 11, "NO": 11, "NOV": 11,
        "DC": 12, "DI": 12, "DEC": 12,
    }
    m = re.search(r'(\d{1,2})\s*([A-Z]{2,3})\s*(20\d{2}|\d{2})(?!\d)', txt)
    if m:
        day = int(m.group(1))
        month = month_map.get(m.group(2)[:3], month_map.get(m.group(2)[:2]))
        year = int(m.group(3))
        if year < 100:
            year += 2000 if year < 80 else 1900
        if month:
            try:
                return pd.Timestamp(year=year, month=month, day=day)
            except Exception:
                pass
    m = re.search(r'(20\d{2}|\d{2})', txt)
    if m:
        year = int(m.group(1))
        if year < 100:
            year += 2000 if year < 80 else 1900
        try:
            return pd.Timestamp(year=year, month=12, day=31)
        except Exception:
            return pd.NaT
    return pd.NaT


def build_gov_dashboard_data(da_frame: pd.DataFrame, data: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    if da_frame is None or da_frame.empty:
        return pd.DataFrame(), {}
    gov = da_frame[da_frame["Tipo"].apply(macro_cat) == "GOV"].copy()
    if gov.empty:
        return pd.DataFrame(), {}
    gov = _sanitize_dashboard_numeric_columns(gov)
    total_ptf = _finite_column_sum(da_frame, "Controvalore")
    total_gov = _finite_column_sum(gov, "Controvalore")
    gov["Peso comparto %"] = _finite_numeric_series(gov["Controvalore"], default=0.0) / max(total_gov, 1e-9)
    info_by_tk = {s.get("ticker"): s for s in data.get("strumenti", [])}
    gov["ISIN"] = gov["Ticker"].map(lambda tk: info_by_tk.get(tk, {}).get("isin", ""))
    gov["Data scadenza"] = gov["Strumento"].map(extract_gov_maturity_date)
    gov["Anno scadenza"] = gov["Data scadenza"].map(lambda x: pd.Timestamp(x).year if pd.notna(x) else np.nan)
    weighted_cur = _weighted_average_finite(gov["Prezzo"], gov["Quote"]) if len(gov) else np.nan
    weighted_pmc = _weighted_average_finite(gov["PMC"], gov["Quote"]) if len(gov) else np.nan
    maturity_valid = _finite_numeric_series(gov["Anno scadenza"], default=np.nan).dropna()
    summary = {
        "count": int(len(gov)),
        "value": total_gov,
        "weight": total_gov / total_ptf if total_ptf > 0 else 0.0,
        "pl": _finite_column_sum(gov, "P/L €"),
        "avg_price": float(weighted_cur) if np.isfinite(weighted_cur) else np.nan,
        "avg_pmc": float(weighted_pmc) if np.isfinite(weighted_pmc) else np.nan,
        "avg_maturity_year": float(maturity_valid.mean()) if not maturity_valid.empty else np.nan,
    }
    return gov, summary


def build_category_dashboard_data(da_frame: pd.DataFrame, category: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    empty_columns = ["Ticker", "Strumento", "Tipo", "Categoria", "Quote", "Prezzo", "PMC", "Controvalore", "Costo", "P/L €", "P/L %", "Peso comparto %"]
    if da_frame is None or da_frame.empty:
        return pd.DataFrame(columns=empty_columns), {}
    df = da_frame[da_frame["Tipo"].apply(macro_cat) == category].copy()
    if df.empty:
        return pd.DataFrame(columns=empty_columns), {}
    df = _sanitize_dashboard_numeric_columns(df)
    total_ptf = _finite_column_sum(da_frame, "Controvalore")
    total_cat = _finite_column_sum(df, "Controvalore")
    df["Peso comparto %"] = _finite_numeric_series(df["Controvalore"], default=0.0) / max(total_cat, 1e-9)
    weighted_cur = _weighted_average_finite(df["Prezzo"], df["Quote"]) if len(df) else np.nan
    weighted_pmc = _weighted_average_finite(df["PMC"], df["Quote"]) if len(df) else np.nan
    summary = {
        "count": int(len(df)),
        "value": total_cat,
        "weight": total_cat / total_ptf if total_ptf > 0 else 0.0,
        "pl": _finite_column_sum(df, "P/L €"),
        "avg_price": float(weighted_cur) if np.isfinite(weighted_cur) else np.nan,
        "avg_pmc": float(weighted_pmc) if np.isfinite(weighted_pmc) else np.nan,
    }
    return df, summary


def build_tutto_portfolio_dashboard_data(da_frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Aggrega dati di tutti gli strumenti (GOV + ETF + FND) per la vista complessiva."""
    if da_frame is None or da_frame.empty:
        return pd.DataFrame(), {}
    df = da_frame.copy()
    df = _sanitize_dashboard_numeric_columns(df)
    total_ptf = _finite_column_sum(df, "Controvalore")
    df["Peso comparto %"] = _finite_numeric_series(df["Controvalore"], default=0.0) / max(total_ptf, 1e-9)
    weighted_cur = _weighted_average_finite(df["Prezzo"], df["Quote"]) if len(df) else np.nan
    weighted_pmc = _weighted_average_finite(df["PMC"], df["Quote"]) if len(df) else np.nan
    summary = {
        "count": int(len(df)),
        "value": total_ptf,
        "weight": 1.0,
        "pl": _finite_column_sum(df, "P/L €"),
        "avg_price": float(weighted_cur) if np.isfinite(weighted_cur) else np.nan,
        "avg_pmc": float(weighted_pmc) if np.isfinite(weighted_pmc) else np.nan,
    }
    return df, summary


# ══════════════════════════════════════════════════════════════════════════════
# Summary payload
# ══════════════════════════════════════════════════════════════════════════════

def _build_summary_value_curve_fallback(dfh: pd.DataFrame | None) -> pd.DataFrame:
    """
    Fallback conservativo per non lasciare la Summary senza grafici se la curva
    NAV/TWR non è costruibile per colonne storiche mancanti o dati anomali.

    Usa la vecchia base visiva: Valore normalizzato a 100. Non viene usata per
    sostituire la metrica TWR quando la curva flow-adjusted è disponibile.
    """
    if dfh is None or dfh.empty or "Data" not in dfh.columns or "Valore" not in dfh.columns:
        return pd.DataFrame(columns=["date_dt", "indice", "ret"])
    work = build_value_curve_frame(dfh)
    work = work[work["value"] > 0]
    if len(work) < 2:
        return pd.DataFrame(columns=["date_dt", "indice", "ret"])
    work["indice"] = 100.0 * work["value"] / float(work["value"].iloc[0])
    work["ret"] = work["indice"].pct_change().fillna(0.0)
    return work[["date_dt", "indice", "ret", "value"]]


def build_portfolio_summary_payload(
    data: dict[str, Any],
    da_frame: pd.DataFrame,
    settings: dict[str, Any] | None,
    last_quotes_update: Any,
    proventi: list[dict[str, Any]] | None = None,
    dfh: pd.DataFrame | None = None,
    portfolio_df: pd.DataFrame | None = None,
    liquidita: float | None = None,
) -> dict[str, Any]:
    da_frame = da_frame.copy() if da_frame is not None else pd.DataFrame()
    proventi = proventi or []
    settings = settings or default_settings()
    portfolio_profile = settings.get("portfolio_profile", {}) if isinstance(settings, dict) else {}
    calculations_settings = settings.get("calculations_metrics", {}) if isinstance(settings, dict) else {}
    benchmark_config = get_effective_portfolio_benchmark_config(settings)
    effective_benchmark_label = str(benchmark_config.get("label") or "Blend automatico")
    portfolio_id = str(
        portfolio_profile.get("portfolio_id")
        or settings.get("portfolio_id")
        or data.get("portfolio_id", "main")
    )
    portfolio_name = str(portfolio_profile.get("portfolio_name") or "Portafoglio Principale")
    portfolio_description = str(portfolio_profile.get("description") or "")
    base_currency = str(portfolio_profile.get("base_currency") or "EUR")
    reporting_currency = str(portfolio_profile.get("reporting_currency") or base_currency)
    include_proventi = bool(calculations_settings.get("include_proventi_in_total_return", settings.get("include_proventi_in_total_return", True)))
    rolling_window_days = int(max(1, _safe_float(calculations_settings.get("rolling_window_days", 90), 90.0)))
    inflation_rate = _safe_float(calculations_settings.get("inflation_rate", 0.0))
    performance_fee_rate = _safe_float(calculations_settings.get("performance_fee_rate", 0.0))
    _state_all = None
    _df_all = portfolio_df.copy() if portfolio_df is not None else pd.DataFrame()
    if _df_all.empty:
        _state_all = compute_portfolio_state(data, include_closed=True)
        _df_all = _state_all.get("df", pd.DataFrame())
    if da_frame.empty and not _df_all.empty:
        da_frame = _df_all[_df_all["Quote"] > QTY_ZERO_EPS].copy()
    if liquidita is None:
        liquidita = _safe_float((_state_all or compute_portfolio_state(data, include_closed=True)).get("liquidita", 0.0))
    else:
        liquidita = _safe_float(liquidita)
    capital_flows = calcola_flussi_capitale(get_registro_eventi(data))
    kpi = calcola_kpi_principali(
        _df_all,
        liquidita,
        capitale_investito=capital_flows["cap_investito"],
    )
    tv = _safe_float(kpi["tv"])
    tc = _safe_float(kpi["tc"])
    pl = _safe_float(kpi["pl_totale"])
    pl_pct = _safe_float(kpi["pl_totale_pct"])
    holdings_count = int(len(da_frame)) if da_frame is not None else 0
    visible_categories = _resolve_finance_category_codes(settings)
    macro_alloc = {cat: 0.0 for cat in visible_categories}
    macro_values = {cat: 0.0 for cat in visible_categories}
    full_holdings = []
    if not da_frame.empty and tv > 0:
        macro_alloc, macro_values = _build_category_value_maps(da_frame, tv, visible_categories)
        tmp = da_frame.copy()
        for col in ("Controvalore", "Costo", "P/L €", "P/L %", "Quote", "Prezzo"):
            if col in tmp.columns:
                tmp[col] = pd.to_numeric(tmp[col], errors="coerce").map(_safe_float)
        tmp["Categoria"] = tmp["Tipo"].apply(macro_cat)
        full_holdings.extend(tmp.sort_values("Controvalore", ascending=False).apply(
            lambda r: {
                "ticker": r.get("Ticker"),
                "strumento": r.get("Strumento"),
                "categoria": macro_cat(r.get("Tipo", "")),
                "tipo": r.get("Tipo"),
                "peso": _safe_float(r.get("Controvalore", 0)) / tv if tv > 0 else 0.0,
                "controvalore": _safe_float(r.get("Controvalore", 0)),
                "costo": _safe_float(r.get("Costo", 0)),
                "pl_eur": _safe_float(r.get("P/L €", 0)),
                "pl_pct": _safe_float(r.get("P/L %", 0)),
                "quote": _safe_float(r.get("Quote", 0)),
                "prezzo": _safe_float(r.get("Prezzo", 0)),
            }, axis=1
        ).tolist())
    top_holdings = full_holdings[:15]
    xirr = xirr_assets = xirr_portfolio = twr_simple = cagr = cagr_real = vol_ann = max_dd = benchmark_return = excess_vs_benchmark = None
    xirr_scope = "n/d"
    sortino_ratio = calmar_ratio = information_ratio = tracking_error_ann = None
    quarterly_returns = []
    monthly_returns = []
    dfh = dfh if dfh is not None else build_portfolio_history_df(data)
    return_curve = pd.DataFrame()
    curve_for_charts = pd.DataFrame()
    benchmark_series = None
    try:
        flows, dates = build_xirr_flows(data, da_frame, proventi, tickers=None)
        xirr_assets = compute_xirr(flows, dates)
        external_flows, external_dates = build_portfolio_external_xirr_flows(
            data,
            tv + liquidita,
        )
        xirr_portfolio = compute_xirr(external_flows, external_dates)
        if xirr_portfolio is not None:
            xirr = xirr_portfolio
            xirr_scope = "portfolio_external"
        else:
            xirr = xirr_assets
            xirr_scope = "invested_assets"
    except Exception as e:
        logger.warning("XIRR computation failed: %s", e)
    try:
        return_curve = _build_summary_return_curve(dfh)
        curve_for_charts = return_curve if not return_curve.empty and len(return_curve) >= 2 else _build_summary_value_curve_fallback(dfh)
        benchmark_start_date = None
        if not curve_for_charts.empty and len(curve_for_charts) >= 2:
            benchmark_start_date = curve_for_charts["date_dt"].iloc[0]
        if benchmark_start_date is not None:
            benchmark_series = build_portfolio_benchmark_series(
                data,
                effective_benchmark_label,
                da_frame,
                min_date=benchmark_start_date,
                settings=settings,
            )
        if not return_curve.empty and len(return_curve) >= 2:
            metrics = compute_return_curve_metrics(
                return_curve,
                benchmark_curve=benchmark_series,
                inflation_rate=inflation_rate,
                max_accepted_benchmark_return=0.50,
            )
            twr_simple = metrics["twr"]
            cagr = metrics["cagr"]
            cagr_real = metrics["cagr_real"]
            vol_ann = metrics["volatility_ann"]
            max_dd = metrics["max_drawdown"]
            benchmark_return = metrics["benchmark_return"]
            excess_vs_benchmark = metrics["excess_vs_benchmark"]
            sortino_ratio = metrics["sortino"]
            calmar_ratio = metrics["calmar"]
            information_ratio = metrics["information_ratio"]
            tracking_error_ann = metrics["tracking_error"]
    except Exception as e:
        logger.warning("advanced stats failed: %s", e)

    summary_history = []
    benchmark_history = []
    category_history = []
    try:
        if not curve_for_charts.empty and len(curve_for_charts) >= 2:
            hist_payload = {
                "data": curve_for_charts["date_dt"].dt.strftime("%d/%m/%Y"),
                "indice": pd.to_numeric(curve_for_charts["indice"], errors="coerce").replace([np.inf, -np.inf], np.nan).round(4),
            }
            if "value" in curve_for_charts.columns:
                hist_payload["value"] = pd.to_numeric(curve_for_charts["value"], errors="coerce").replace([np.inf, -np.inf], np.nan).round(4)
            if "external_flow" in curve_for_charts.columns:
                hist_payload["external_flow"] = pd.to_numeric(curve_for_charts["external_flow"], errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0).round(4)
            hist_df = pd.DataFrame(hist_payload).dropna(subset=["data", "indice"])
            summary_history = hist_df.to_dict("records")
            if benchmark_series is not None and not benchmark_series.empty and benchmark_series.iloc[0] > 0:
                bench_norm = (benchmark_series / benchmark_series.iloc[0]) * 100.0
                bench_df = pd.DataFrame({
                    "data": pd.to_datetime(bench_norm.index).strftime("%d/%m/%Y"),
                    "indice": bench_norm.round(4),
                })
                benchmark_history = bench_df.to_dict("records")
            # I rendimenti periodici usano la curva flow-adjusted se disponibile;
            # in fallback mantengono comunque viva la tabella invece di svuotare la Summary.
            quarterly_returns = _period_returns_from_curve(curve_for_charts, "Q")
            monthly_returns = _period_returns_from_curve(curve_for_charts, "M")
        try:
            dh_hist = build_hist_df(data)
            cat_idx = build_category_return_index(dh_hist, data, positions=calc_positions(data))
            if cat_idx is not None and not cat_idx.empty:
                category_history = _build_category_history_records(cat_idx, visible_categories)
        except Exception as e:
            logger.warning("category history failed: %s", e)
    except Exception as e:
        logger.warning("benchmark/period history failed: %s", e)
    _prov_netto = 0.0
    _prov_lordo = 0.0
    for _p in proventi:
        _prov_netto += _safe_float(_p.get("importo_netto", 0))
        _prov_lordo += _safe_float(_p.get("importo_lordo", 0))
    category_breakdown = [
        {
            "categoria": cat,
            "peso": _safe_float(macro_alloc.get(cat, 0.0)),
            "controvalore": _safe_float(macro_values.get(cat, 0.0)),
        }
        for cat in visible_categories
    ]
    return {
        "standard": "Internal Portfolio Summary inspired by GIPS presentation logic and openfunds-style data structuring",
        "compliance_note": "Documento interno di sintesi ispirato a logiche GIPS/openfunds. Non costituisce una rendicontazione GIPS certificata né un file openfunds ufficiale.",
        "portfolio_id": portfolio_id,
        "portfolio_name": portfolio_name,
        "portfolio_description": portfolio_description,
        "valuation_timestamp": last_quotes_update,
        "base_currency": base_currency,
        "reporting_currency": reporting_currency,
        "target_profile": _format_portfolio_objective_label(settings.get("portfolio_objective", {})),
        "portfolio_benchmark": effective_benchmark_label,
        "portfolio_benchmark_is_custom": bool(benchmark_config.get("is_custom", False)),
        "portfolio_benchmark_components": benchmark_config.get("components", []),
        "include_proventi_in_total_return": include_proventi,
        "rolling_window_days": rolling_window_days,
        "inflation_rate": inflation_rate,
        "performance_fee_rate": performance_fee_rate,
        "total_market_value": tv,
        "total_cost": tc,
        "total_pl": pl,
        "total_pl_pct": pl_pct,
        "xirr": xirr,
        "xirr_assets": xirr_assets,
        "xirr_portfolio": xirr_portfolio,
        "xirr_scope": xirr_scope,
        "twr": twr_simple,
        "cagr": cagr,
        "cagr_real": cagr_real,
        "volatility_ann": vol_ann,
        "max_drawdown": max_dd,
        "benchmark_return": benchmark_return,
        "excess_vs_benchmark": excess_vs_benchmark,
        "net_proventi": _prov_netto,
        "gross_proventi": _prov_lordo,
        "holdings_count": holdings_count,
        "macro_allocation": macro_alloc,
        "category_breakdown": category_breakdown,
        "top_holdings": top_holdings,
        "full_holdings": full_holdings,
        "summary_history": summary_history,
        "benchmark_history": benchmark_history,
        "category_history": category_history,
        "sortino": sortino_ratio,
        "calmar": calmar_ratio,
        "information_ratio": information_ratio,
        "tracking_error": tracking_error_ann,
        "quarterly_returns": quarterly_returns,
        "monthly_returns": monthly_returns,
        "methodology": {
            "valuation_rule": "Controvalore = quantità x ultimo prezzo disponibile letto o mantenuto in cache.",
            "money_weighted_return": "XIRR del portafoglio calcolato sui flussi esterni (versamenti/prelievi) e sul patrimonio finale comprensivo di liquidita'; se non calcolabile, fallback sull'XIRR degli strumenti investiti.",
            "money_weighted_return_assets": "XIRR strumenti calcolato sui flussi irregolari di acquisto, vendita, proventi e controvalore finale degli strumenti.",
            "time_weighted_proxy": "TWR proxy calcolato su curva NAV flow-adjusted: i flussi esterni stimati dalla variazione del capitale netto vengono neutralizzati prima di calcolare rendimento, drawdown, volatilità e rendimenti periodici.",
            "benchmark_method": (
                "Benchmark personalizzato definito da componenti e pesi configurati nelle impostazioni, costruito come serie normalizzata a 100 dalla prima data utile."
                if bool(benchmark_config.get("is_custom", False))
                else "Benchmark di portafoglio definito da impostazioni e costruito come serie normalizzata a 100 dalla prima data utile."
            ),
            "include_proventi": "Sì" if include_proventi else "No",
            "rolling_window_days": rolling_window_days,
            "inflation_rate": inflation_rate,
            "performance_fee_rate": performance_fee_rate,
        }
    }
