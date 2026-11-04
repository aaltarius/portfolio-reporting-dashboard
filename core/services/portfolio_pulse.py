"""Termometro del portafoglio: lettura "a colpo d'occhio" dell'andamento.

Funzioni pure, nessuna dipendenza da Streamlit. Nessuna formula nuova:
- rendimento % del portafoglio dalla curva TWR esistente
  (`core.domain.returns.build_portfolio_return_curve`), quindi neutro
  rispetto a versamenti e prelievi;
- importi in EUR degli orizzonti dalla variazione della colonna "P/L" dello
  storico (Valore - Capitale: neutra rispetto a versamenti e prelievi,
  include cedole e realizzi, quindi coerente con il rendimento TWR);
- importi in EUR per categoria e ampiezza dalle variazioni delle colonne
  `PL_<ticker>` (stessa regola di `core.services.analysis.build_pl_delta_series`:
  solo variazioni di mercato); uno strumento aperto dentro la finestra parte
  da 0, uno chiuso dentro la finestra e' escluso;
- % per categoria dall'indice TWR di `core.cashflow_indices` (solo se si
  passa `price_frame`);
- distanza dal picco sulla curva TWR del portafoglio;
- serie di giorni consecutivi e giorno migliore/peggiore, posizione nell'ultimo
  anno e volatilita' recente: tutti dalla stessa curva TWR (volatilita' da
  `core.domain.risk.rolling_volatility_annualized`, nessuna formula nuova);
- contributori del mese: variazioni delle colonne `PL_<ticker>` (come sopra).
Dove un numero non e' calcolabile il valore e' None, mai un numero finto.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from core.domain.returns import build_portfolio_return_curve
from core.domain.risk import rolling_volatility_annualized

_FLAT_EPS = 0.005  # sotto mezzo centesimo di EUR uno strumento e' "invariato"

_HORIZON_LABELS = (("oggi", "Oggi"), ("5g", "5 giorni"), ("1m", "1 mese"), ("ytd", "Da inizio anno"))


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


def _drop_synthetic_trailing_row(dfh: pd.DataFrame, data: dict[str, Any]) -> pd.DataFrame:
    """Toglie l'eventuale riga "oggi" sintetica aggiunta nei giorni senza
    mercato (non e' una data reale di `storico_prezzi`)."""
    real_dates = set((data or {}).get("storico_prezzi", {}).keys())
    if not real_dates or dfh.empty:
        return dfh
    last = pd.to_datetime(dfh.iloc[-1]["Data"]).strftime("%Y-%m-%d")
    return dfh.iloc[:-1] if last not in real_dates else dfh


def _reference_positions(dates: pd.Series) -> dict[str, tuple[int, bool]]:
    """Posizione della riga di riferimento per ogni orizzonte e se e' parziale
    (storia piu' corta dell'orizzonte: si usa la prima riga disponibile)."""
    last = len(dates) - 1
    last_date = dates.iloc[last]
    out: dict[str, tuple[int, bool]] = {"oggi": (last - 1, False)}
    out["5g"] = (max(0, last - 5), last - 5 < 0)
    one_month = last_date - pd.DateOffset(months=1)
    idx_m = dates.index[dates <= one_month]
    out["1m"] = (int(idx_m[-1]), False) if len(idx_m) else (0, True)
    year_end = pd.Timestamp(year=last_date.year - 1, month=12, day=31)
    idx_y = dates.index[dates <= year_end]
    out["ytd"] = (int(idx_y[-1]), False) if len(idx_y) else (0, True)
    return out


def _pl_delta_by_ticker(dfh: pd.DataFrame, ref_pos: int, last_pos: int) -> dict[str, float]:
    ref = dfh.iloc[ref_pos]
    last = dfh.iloc[last_pos]
    out: dict[str, float] = {}
    for col in dfh.columns:
        if not str(col).startswith("PL_"):
            continue
        v_last = _finite(last[col])
        if v_last is None:
            continue  # chiuso (o mai aperto) alla data finale: escluso
        v_ref = _finite(ref[col])
        out[str(col)[3:]] = v_last - (v_ref if v_ref is not None else 0.0)
    return out


def _category_twr_pct(
    data: dict[str, Any],
    price_frame: pd.DataFrame | None,
    groups: dict[str, list[str]],
    ref_date: pd.Timestamp,
) -> dict[str, float | None]:
    if price_frame is None or getattr(price_frame, "empty", True) or not groups:
        return {}
    from core.cashflow_indices import build_group_cashflow_indices

    index_df, _returns, _values, _flows = build_group_cashflow_indices(data, price_frame, groups)
    if index_df is None or index_df.empty:
        return {}
    out: dict[str, float | None] = {}
    for code in groups:
        if code not in index_df.columns:
            continue
        series = index_df[code].dropna()
        before = series[series.index <= ref_date]
        if series.empty or before.empty:
            out[code] = None
            continue
        base = _finite(before.iloc[-1])
        end = _finite(series.iloc[-1])
        out[code] = (end / base - 1.0) if base and end is not None else None
    return out


_VOL_RECENT_WINDOW = 20      # ~1 mese di borsa
_VOL_BASELINE_MAX = 250      # ~1 anno di borsa
_VOL_MIN_BASELINE = 60       # sotto questa storia il confronto non e' affidabile
_VOL_CALM_RATIO = 0.75       # recente < 75% della norma -> "calma"
_VOL_AGITATED_RATIO = 1.25   # recente > 125% della norma -> "agitata"
_YEAR_DAYS = 365
_TOP_CONTRIBUTORS = 3


def _streak_and_extremes(curve: pd.DataFrame, month_start: pd.Timestamp) -> dict[str, Any] | None:
    """Giorni consecutivi nello stesso verso (da `ret` della curva TWR) e
    giorno migliore/peggiore dall'ultimo mese."""
    if curve.empty or "ret" not in curve.columns:
        return None
    rets = curve.set_index("date_dt")["ret"].dropna()
    rets = rets.iloc[1:] if len(rets) > 1 else rets  # la prima riga e' la base (ret=0), non un giorno di mercato
    if rets.empty:
        return None
    signs = np.sign(rets.where(rets.abs() >= 0.00005, 0.0))  # sotto 0,005% e' "invariato"
    last_sign = float(signs.iloc[-1])
    days = 0
    for s in reversed(signs.tolist()):
        if s == last_sign:
            days += 1
        else:
            break
    month = rets[rets.index >= month_start]
    best = worst = None
    if not month.empty:
        b, w = month.idxmax(), month.idxmin()
        best = {"date": pd.Timestamp(b).strftime("%Y-%m-%d"), "pct": float(month.loc[b])}
        worst = {"date": pd.Timestamp(w).strftime("%Y-%m-%d"), "pct": float(month.loc[w])}
    return {
        "direction": "up" if last_sign > 0 else ("down" if last_sign < 0 else "flat"),
        "days": days,
        "best_day": best,
        "worst_day": worst,
    }


def _year_range(index_by_date: pd.Series) -> dict[str, Any] | None:
    """Dove sta l'indice TWR rispetto al minimo e al massimo degli ultimi 12 mesi."""
    idx = index_by_date.dropna()
    if len(idx) < 2:
        return None
    last_date = idx.index[-1]
    window = idx[idx.index >= last_date - pd.Timedelta(days=_YEAR_DAYS)]
    if len(window) < 2:
        return None
    lo, hi, cur = float(window.min()), float(window.max()), float(window.iloc[-1])
    if hi <= lo or lo <= 0 or hi <= 0:
        return None
    partial = bool(idx.index[0] > last_date - pd.Timedelta(days=_YEAR_DAYS))
    return {
        "position": (cur - lo) / (hi - lo),
        "from_high": cur / hi - 1.0,
        "from_low": cur / lo - 1.0,
        "partial": partial,
    }


def _recent_volatility(index_by_date: pd.Series) -> dict[str, Any] | None:
    """Volatilita' annualizzata dell'ultimo mese contro quella "normale" del
    portafoglio (fino a un anno di storia)."""
    idx = index_by_date.dropna()
    base_window = min(_VOL_BASELINE_MAX, len(idx) - 1)
    if base_window < _VOL_MIN_BASELINE:
        return None
    recent = _finite(rolling_volatility_annualized(idx, _VOL_RECENT_WINDOW).iloc[-1])
    baseline = _finite(rolling_volatility_annualized(idx, base_window).iloc[-1])
    if recent is None or baseline is None or baseline <= 0:
        return None
    ratio = recent / baseline
    label = "calma" if ratio < _VOL_CALM_RATIO else ("agitata" if ratio > _VOL_AGITATED_RATIO else "nella norma")
    return {"recent": recent, "baseline": baseline, "ratio": ratio, "label": label}


def _month_contributors(work: pd.DataFrame, ref_pos: int, last_pos: int) -> dict[str, list[dict[str, Any]]] | None:
    """I contributori positivi e negativi al P/L dell'ultimo mese (solo mercato)."""
    if not (0 <= ref_pos < last_pos):
        return None
    deltas = _pl_delta_by_ticker(work, ref_pos, last_pos)
    ups = sorted(((tk, v) for tk, v in deltas.items() if v > _FLAT_EPS), key=lambda kv: -kv[1])
    downs = sorted(((tk, v) for tk, v in deltas.items() if v < -_FLAT_EPS), key=lambda kv: kv[1])
    if not ups and not downs:
        return None
    return {
        "top": [{"ticker": tk, "eur": v} for tk, v in ups[:_TOP_CONTRIBUTORS]],
        "bottom": [{"ticker": tk, "eur": v} for tk, v in downs[:_TOP_CONTRIBUTORS]],
    }


def build_portfolio_pulse(
    dfh: pd.DataFrame | None,
    data: dict[str, Any] | None,
    *,
    categories: list[str],
    price_frame: pd.DataFrame | None = None,
) -> dict[str, Any] | None:
    """Ritorna il payload del Termometro, o None se lo storico e' troppo corto."""
    from persistence.storage import macro_cat  # import locale: stesso uso di core.services.analysis

    data = data or {}
    if dfh is None or dfh.empty or not {"Data", "Valore", "Capitale"}.issubset(dfh.columns):
        return None
    work = _drop_synthetic_trailing_row(dfh, data).copy()
    work["Data"] = pd.to_datetime(work["Data"], errors="coerce")
    work = work.dropna(subset=["Data"]).reset_index(drop=True)
    if len(work) < 2:
        return None

    last_pos = len(work) - 1
    dates = work["Data"]
    refs = _reference_positions(dates)

    curve = build_portfolio_return_curve(work)
    index_by_date = curve.set_index("date_dt")["indice"] if not curve.empty else pd.Series(dtype=float)

    horizons = []
    for key, label in _HORIZON_LABELS:
        ref_pos, partial = refs[key]
        if ref_pos < 0 or ref_pos >= last_pos:
            horizons.append({"key": key, "label": label, "eur": None, "pct": None, "partial": partial})
            continue
        eur = _finite(work.iloc[last_pos]["P/L"]) if "P/L" in work.columns else None
        eur_ref = _finite(work.iloc[ref_pos]["P/L"]) if "P/L" in work.columns else None
        eur = eur - eur_ref if eur is not None and eur_ref is not None else None
        pct = None
        ref_idx = _finite(index_by_date.get(dates.iloc[ref_pos]))
        last_idx = _finite(index_by_date.get(dates.iloc[last_pos]))
        if ref_idx and last_idx is not None:
            pct = last_idx / ref_idx - 1.0
        horizons.append({"key": key, "label": label, "eur": eur, "pct": pct, "partial": partial})

    drawdown = None
    idx_clean = index_by_date.dropna()
    if not idx_clean.empty:
        peak_date = idx_clean.idxmax()
        peak = float(idx_clean.loc[peak_date])
        drawdown = {
            "pct": float(idx_clean.iloc[-1]) / peak - 1.0 if peak else None,
            "peak_date": pd.Timestamp(peak_date).strftime("%Y-%m-%d"),
            "days_since_peak": int((idx_clean.index[-1] - peak_date).days),
        }

    ticker_cat = {str(s.get("ticker") or ""): macro_cat(s.get("tipo", "")) for s in data.get("strumenti", [])}
    ref5, _ = refs["5g"]
    deltas_5g = _pl_delta_by_ticker(work, ref5, last_pos) if 0 <= ref5 < last_pos else {}
    cat_eur: dict[str, float] = {}
    for tk, delta in deltas_5g.items():
        cat = ticker_cat.get(tk, "Altro")
        cat_eur[cat] = cat_eur.get(cat, 0.0) + delta
    groups: dict[str, list[str]] = {}
    for tk, cat in ticker_cat.items():
        if cat in categories and f"PL_{tk}" in work.columns:
            groups.setdefault(cat, []).append(tk)
    cat_pct = _category_twr_pct(data, price_frame, groups, dates.iloc[ref5]) if ref5 < last_pos else {}
    category_rows = [
        {"code": code, "eur": cat_eur.get(code, 0.0) if code in groups else None, "pct": cat_pct.get(code)}
        for code in categories
    ]

    day = _pl_delta_by_ticker(work, last_pos - 1, last_pos)
    down = sum(1 for v in day.values() if v < -_FLAT_EPS)
    up = sum(1 for v in day.values() if v > _FLAT_EPS)
    breadth: dict[str, Any] = {
        "down": down, "up": up, "flat": len(day) - down - up, "total": len(day),
        "worst": None, "best": None,
    }
    if day:
        worst_tk = min(day, key=day.get)
        best_tk = max(day, key=day.get)
        if day[worst_tk] < -_FLAT_EPS:
            breadth["worst"] = {"ticker": worst_tk, "eur": day[worst_tk]}
        if day[best_tk] > _FLAT_EPS:
            breadth["best"] = {"ticker": best_tk, "eur": day[best_tk]}

    return {
        "as_of": dates.iloc[last_pos].strftime("%Y-%m-%d"),
        "horizons": horizons,
        "drawdown": drawdown,
        "categories": category_rows,
        "breadth": breadth,
        "streak": _streak_and_extremes(curve, dates.iloc[refs["1m"][0]]),
        "year_range": _year_range(index_by_date),
        "volatility": _recent_volatility(index_by_date),
        "contributors": _month_contributors(work, refs["1m"][0], last_pos),
    }
