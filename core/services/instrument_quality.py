"""Dataset centrale qualita' dati e rischio/rendimento strumenti.

Il modulo e' indipendente dalla UI: prepara una tabella riusabile da Gestione
Dati, Cruscotti, Quotazioni e, piu' avanti, SATOR.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from core.asset_categories import infer_category_code
from core.domain.returns import compute_instrument_stats


RETURN_WINDOWS = {"ret_1m": 21, "ret_3m": 63, "ret_6m": 126, "ret_12m": 252}

ENRICHMENT_REQUIRED_FIELDS: dict[str, list[str]] = {
    "btp": [
        "ytm_netto",
        "ytm_lordo",
        "duration_modificata",
        "scadenza",
        "cedola_annuale",
        "cedola_frequenza",
        "tipo_cedola",
        "rating_emittente",
    ],
    "etf": [
        "rendimento_1a",
        "rendimento_3a",
        "ter",
        "benchmark",
        "categoria_etf",
        "distribuzione",
        "data_lancio",
        "rating_morningstar",
    ],
    "etc": [
        "rendimento_1a",
        "rendimento_3a",
        "ter",
        "benchmark",
        "categoria_etf",
        "distribuzione",
        "data_lancio",
    ],
    "fondo": [
        "rendimento_ytd",
        "rendimento_1a",
        "rendimento_3a",
        "ter",
        "categoria_fam",
        "rating_morningstar",
        "data_lancio",
        "patrimonio",
    ],
}


def _finite_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return out if math.isfinite(out) else None


def _enrichment_kind(tipo: Any) -> str:
    text = str(tipo or "").lower()
    if any(token in text for token in ("stato", "btp", "titolo")):
        return "btp"
    if "etc" in text:
        return "etc"
    if any(token in text for token in ("fond", "fam", "bilanc", "fless", "flex", "multi", "obbl. m", "az. pass", "passivo")):
        return "fondo"
    return "etf"


def _enrichment_status(instrument: dict[str, Any]) -> str:
    if instrument.get("enrichment_error"):
        return "Errore"
    if instrument.get("enriched_at"):
        return "OK"
    return "Mai"


def _enrichment_completeness(instrument: dict[str, Any]) -> int:
    if not instrument.get("enriched_at"):
        return 0
    fields = ENRICHMENT_REQUIRED_FIELDS.get(_enrichment_kind(instrument.get("tipo")), [])
    if not fields:
        return 0
    filled = sum(1 for field in fields if instrument.get(field) not in (None, "", "—", "-"))
    return int(round(filled / len(fields) * 100))


def _enrichment_source_label(instrument: dict[str, Any]) -> str:
    source = instrument.get("enrichment_source") or {}
    if not isinstance(source, dict) or not source:
        return "n/d" if instrument.get("enriched_at") else "Assente"
    labels = {
        "auto": "Aut",
        "pdf": "Pdf",
        "manuale": "Man",
    }
    ordered = []
    for key in ("auto", "pdf", "manuale"):
        if key in {str(value).strip().lower() for value in source.values() if value}:
            ordered.append(labels[key])
    if not ordered:
        ordered = sorted({labels.get(str(value).strip().lower(), str(value).strip()) for value in source.values() if value})
    return " + ".join(ordered) if ordered else "n/d"


def build_price_frame_from_storico(data: dict[str, Any] | None, tickers: list[str] | None = None) -> pd.DataFrame:
    """Converte `storico_prezzi` in DataFrame date x ticker pulito e ordinato."""
    storico = (data or {}).get("storico_prezzi", {})
    if not isinstance(storico, dict) or not storico:
        return pd.DataFrame(columns=list(tickers or []))

    wanted = {str(ticker or "").strip() for ticker in (tickers or []) if str(ticker or "").strip()}
    rows: list[dict[str, Any]] = []
    for raw_date, prices in storico.items():
        if not isinstance(prices, dict):
            continue
        dt = pd.to_datetime(raw_date, errors="coerce")
        if pd.isna(dt):
            continue
        row: dict[str, Any] = {"Data": dt}
        for ticker, price in prices.items():
            ticker_str = str(ticker or "").strip()
            if wanted and ticker_str not in wanted:
                continue
            parsed = _finite_float(price)
            if parsed is not None and parsed > 0:
                row[ticker_str] = parsed
        if len(row) > 1:
            rows.append(row)
    if not rows:
        return pd.DataFrame(columns=list(tickers or []))

    frame = pd.DataFrame(rows).sort_values("Data").drop_duplicates("Data", keep="last").set_index("Data")
    frame = frame.apply(pd.to_numeric, errors="coerce").where(lambda df: df > 0)
    if tickers:
        for ticker in tickers:
            if ticker not in frame.columns:
                frame[ticker] = np.nan
        frame = frame[[ticker for ticker in tickers if ticker in frame.columns]]
    return frame.sort_index()


def compute_trailing_risk_return_metrics(
    tickers: list[str],
    price_frame: pd.DataFrame,
) -> dict[str, dict[str, float]]:
    """Metriche trailing vettorizzate, pensate come base condivisa anche per SATOR."""
    empty = {key: np.nan for key in ("ret_1m", "ret_3m", "ret_6m", "ret_12m", "ytd", "vol", "drawdown", "rend_vol")}
    empty["n_punti"] = 0.0
    if not tickers or price_frame is None or price_frame.empty:
        return {ticker: dict(empty) for ticker in tickers}

    cols = [ticker for ticker in tickers if ticker in price_frame.columns]
    if not cols:
        return {ticker: dict(empty) for ticker in tickers}

    frame = price_frame[cols].apply(pd.to_numeric, errors="coerce")
    frame = frame.where(frame > 0)
    n_rows = len(frame)
    last = frame.iloc[-1]

    trailing: dict[str, pd.Series] = {}
    for key, window in RETURN_WINDOWS.items():
        if n_rows > window:
            start = frame.iloc[-(window + 1)]
            trailing[key] = (last / start - 1.0).where(start > 0)
        else:
            trailing[key] = pd.Series(np.nan, index=frame.columns)

    ytd = pd.Series(np.nan, index=frame.columns)
    try:
        current_year = int(pd.Timestamp(frame.index[-1]).year)
        year_frame = frame.loc[pd.to_datetime(frame.index).year == current_year]
        if len(year_frame) >= 2:
            year_start = year_frame.apply(lambda col: col.dropna().iloc[0] if not col.dropna().empty else np.nan)
            ytd = (last / year_start - 1.0).where(year_start > 0)
    except Exception:
        ytd = pd.Series(np.nan, index=frame.columns)

    returns = frame.pct_change().replace([np.inf, -np.inf], np.nan)
    tail = returns.tail(252)
    vol = tail.std(ddof=1) * math.sqrt(252)
    vol = vol.where(tail.notna().sum() >= 20)
    drawdown = (frame / frame.cummax() - 1.0).min()
    ret_12m = trailing.get("ret_12m", pd.Series(np.nan, index=frame.columns))
    rend_vol = (ret_12m / vol).where(vol > 1e-9)

    result: dict[str, dict[str, float]] = {}
    counts = frame.notna().sum().to_dict()
    dicts = {key: series.to_dict() for key, series in trailing.items()}
    dicts["ytd"] = ytd.to_dict()
    dicts["vol"] = vol.to_dict()
    dicts["drawdown"] = drawdown.to_dict()
    dicts["rend_vol"] = rend_vol.to_dict()

    for ticker in tickers:
        if ticker not in cols:
            result[ticker] = dict(empty)
            continue
        row = {"n_punti": float(counts.get(ticker, 0.0) or 0.0)}
        for key, values in dicts.items():
            value = values.get(ticker, np.nan)
            row[key] = float(value) if pd.notna(value) else np.nan
        result[ticker] = row
    return result


def _series_gap_stats(series: pd.Series) -> tuple[int, float]:
    clean = pd.Series(series).dropna()
    if len(clean) < 2:
        return 0, 0.0
    dates = pd.DatetimeIndex(clean.index).normalize().unique().sort_values()
    expected = pd.bdate_range(dates[0], dates[-1])
    missing = len([dt for dt in expected if dt not in dates])
    denominator = max(len(expected), 1)
    return int(missing), float(missing / denominator)


def _days_since_last_change(series: pd.Series) -> int | None:
    clean = pd.Series(series).dropna()
    if len(clean) < 2:
        return None
    last_value = float(clean.iloc[-1])
    run_start = clean.index[-1]
    for idx in reversed(clean.index[:-1]):
        value = _finite_float(clean.loc[idx])
        if value is None or abs(value - last_value) > 1e-9:
            break
        run_start = idx
    return int(max((pd.Timestamp(clean.index[-1]) - pd.Timestamp(run_start)).days, 0))


def _coerce_date(value: Any) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).normalize()


def _quality_label(score: float) -> str:
    if score >= 80:
        return "Alta"
    if score >= 55:
        return "Media"
    if score >= 30:
        return "Bassa"
    return "Critica"


def _quality_score(points: int, stale_days: int | None, gap_ratio: float, metrics_available: bool) -> int:
    history_score = min(max(points, 0) / 126.0, 1.0) * 35.0
    if stale_days is None:
        freshness_score = 0.0
    elif stale_days <= 3:
        freshness_score = 30.0
    elif stale_days <= 7:
        freshness_score = 22.0
    elif stale_days <= 14:
        freshness_score = 14.0
    else:
        freshness_score = 4.0
    if gap_ratio <= 0.10:
        gap_score = 20.0
    elif gap_ratio <= 0.25:
        gap_score = 12.0
    else:
        gap_score = 4.0
    metrics_score = 15.0 if metrics_available else 0.0
    return int(round(max(0.0, min(100.0, history_score + freshness_score + gap_score + metrics_score))))


def _history_coverage_label(points: int, stale_days: int | None, gap_ratio: float) -> str:
    if points <= 0:
        return "Assente"
    if points >= 126 and (stale_days is not None and stale_days <= 7) and gap_ratio <= 0.10:
        return "Buona"
    if points >= 63 and (stale_days is not None and stale_days <= 14) and gap_ratio <= 0.25:
        return "Media"
    return "Debole"


def _action_required(
    instrument: dict[str, Any],
    *,
    completeness: int,
    points: int,
    stale_days: int | None,
    missing_days: int,
    gap_ratio: float,
    stagnant_days: int | None,
    metrics_available: bool,
) -> str:
    if instrument.get("enrichment_error"):
        return "Verifica errore"
    if not instrument.get("enriched_at") or completeness < 40:
        return "Completa arricchimento"
    if stale_days is None:
        return "Carica prezzi"
    if stale_days > 14:
        return "Prezzo non aggiornato"
    if stagnant_days is not None and stagnant_days >= 10:
        return "Prezzo fermo"
    if missing_days >= 10 or gap_ratio > 0.25:
        return "Buchi storico"
    if points < 20:
        return "Storico corto"
    if completeness < 80:
        return "Completa campi"
    if not metrics_available:
        return "Storico da ampliare"
    return "OK"


def build_instrument_quality_dataset(
    data: dict[str, Any] | None,
    *,
    instruments: list[dict[str, Any]] | None = None,
    include_closed: bool = False,
    as_of: date | datetime | pd.Timestamp | None = None,
    include_financial_metrics: bool = True,
) -> pd.DataFrame:
    """Costruisce il dataset centrale per qualità dati e metriche strumento."""
    source = list(instruments if instruments is not None else (data or {}).get("strumenti", []) or [])
    if not include_closed:
        source = [item for item in source if str(item.get("stato", "aperto")) == "aperto"]
    tickers = [str(item.get("ticker") or "").strip() for item in source if str(item.get("ticker") or "").strip()]
    price_frame = build_price_frame_from_storico(data, tickers)
    # Quote realmente possedute (fonte: registro_eventi, unica fonte di
    # verita' per il possesso — vedi core/domain/positions.py): distingue
    # uno strumento in portafoglio da uno solo osservato/tracciato ma mai
    # acquistato. Best-effort: se `data` non porta un registro eventi
    # utilizzabile, tutti gli strumenti risultano semplicemente "non in
    # portafoglio" invece di far fallire il dataset.
    try:
        from core.domain.positions import calc_positions
        positions = calc_positions(data) if data else {}
    except Exception:
        positions = {}
    trailing = compute_trailing_risk_return_metrics(tickers, price_frame) if include_financial_metrics else {}
    as_of_ts = _coerce_date(as_of) or pd.Timestamp(date.today())

    rows: list[dict[str, Any]] = []
    for instrument in source:
        ticker = str(instrument.get("ticker") or "").strip()
        if not ticker:
            continue
        series = price_frame[ticker].dropna() if ticker in price_frame.columns else pd.Series(dtype=float)
        last_date = pd.Timestamp(series.index[-1]).normalize() if not series.empty else _coerce_date(instrument.get("aggiornato"))
        last_price = float(series.iloc[-1]) if not series.empty else _finite_float(instrument.get("prezzo"))
        first_date = pd.Timestamp(series.index[0]).normalize() if not series.empty else None
        history_days = int((last_date - first_date).days) if first_date is not None and last_date is not None else 0
        stale_days = int(max((as_of_ts - last_date).days, 0)) if last_date is not None else None
        missing_days, gap_ratio = _series_gap_stats(series)
        stagnant_days = _days_since_last_change(series)
        stats = compute_instrument_stats(series) if include_financial_metrics and len(series) >= 3 else None
        if include_financial_metrics:
            metrics_available = bool(stats) and int(trailing.get(ticker, {}).get("n_punti", 0.0) or 0.0) >= 20
        else:
            metrics_available = len(series) >= 20
        enrichment_completeness = _enrichment_completeness(instrument)
        score = _quality_score(len(series), stale_days, gap_ratio, metrics_available)
        category = infer_category_code(instrument.get("tipo", ""), default="ALTRO")
        trail = trailing.get(ticker, {})
        held_qty = float(positions.get(ticker, {}).get("qty", 0.0) or 0.0)
        rows.append({
            "ticker": ticker,
            "name": str(instrument.get("nome") or ""),
            "category": category,
            "tipo": str(instrument.get("tipo") or ""),
            "in_portfolio": abs(held_qty) > 1e-9,
            "enrichment_status": _enrichment_status(instrument),
            "enrichment_source_label": _enrichment_source_label(instrument),
            "enriched_at": str(instrument.get("enriched_at") or "")[:10],
            "enrichment_completeness": enrichment_completeness,
            "last_price": last_price,
            "last_price_date": last_date.strftime("%Y-%m-%d") if last_date is not None else "",
            "history_points": int(len(series)),
            "history_days": int(history_days),
            "missing_business_days": int(missing_days),
            "gap_ratio": float(gap_ratio),
            "history_coverage_label": _history_coverage_label(len(series), stale_days, gap_ratio),
            "stale_days": stale_days,
            "stagnant_days": stagnant_days,
            "metrics_available": metrics_available,
            "data_quality_score": score,
            "data_quality_label": _quality_label(score),
            "action_required": _action_required(
                instrument,
                completeness=enrichment_completeness,
                points=len(series),
                stale_days=stale_days,
                missing_days=missing_days,
                gap_ratio=gap_ratio,
                stagnant_days=stagnant_days,
                metrics_available=metrics_available,
            ),
            "ret_1m": trail.get("ret_1m", np.nan),
            "ret_3m": trail.get("ret_3m", np.nan),
            "ret_6m": trail.get("ret_6m", np.nan),
            "ret_12m": trail.get("ret_12m", np.nan),
            "ytd": trail.get("ytd", np.nan),
            "volatility_ann": trail.get("vol", np.nan),
            "max_drawdown": trail.get("drawdown", np.nan),
            "rend_vol": trail.get("rend_vol", np.nan),
            "sharpe": (stats or {}).get("Sharpe (rf 0%)", np.nan),
            "sortino": (stats or {}).get("Sortino", np.nan),
            "calmar": (stats or {}).get("Calmar", np.nan),
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(
        ["data_quality_score", "history_points", "ticker"],
        ascending=[True, True, True],
        kind="stable",
    ).reset_index(drop=True)


__all__ = [
    "ENRICHMENT_REQUIRED_FIELDS",
    "RETURN_WINDOWS",
    "build_instrument_quality_dataset",
    "build_price_frame_from_storico",
    "compute_trailing_risk_return_metrics",
]
