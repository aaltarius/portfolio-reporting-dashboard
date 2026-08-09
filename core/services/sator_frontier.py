"""core/services/sator_frontier.py — SATOR Frontier (Progetto A,
ROADMAP_AI_FINANZA_LIBRO.md): vista rischio/rendimento simulata che
confronta portafoglio attuale, proposta SATOR e una modifica manuale
dell'utente, con minimo-rischio e miglior Sharpe individuati su una
nuvola di portafogli casuali.

Nessun ottimizzatore, nessuna stima previsiva puntuale: solo rendimento
storico realizzato (mai "atteso") e simulazione — stesso spirito di
core/services/portfolio_simulation.py (Progetto B). La "frontiera" e' il
bordo superiore osservato della nuvola simulata, non un ottimo
matematico: coerente con la mitigazione della roadmap "non usare la
frontiera come raccomandazione meccanica".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from core.services.sator import MIN_PUNTI_STORICO, build_sator_matrix_frame

TRADING_DAYS_PER_MONTH = 21
MIN_UNIVERSE_SIZE = 3
N_SCENARIOS_DEFAULT = 4000
RETURN_NEUTRAL_BAND = 0.005
VOL_NEUTRAL_BAND = 0.005
FRONTIER_CLOSE_BAND = 0.01


@dataclass(frozen=True)
class FrontierMarker:
    label: str
    ret: float
    vol: float
    sharpe: float


def _historical_return_and_cov(
    returns_frame: pd.DataFrame, tickers: list[str], lookback_months: int
) -> tuple[pd.Series, pd.DataFrame, list[str]]:
    """Rendimento storico annualizzato (media giornaliera * 252, la
    convenzione standard di Markowitz — non il CAGR composto usato altrove
    per le schede strumento) e covarianza annualizzata (cov giornaliera *
    252) sugli ultimi `lookback_months` mesi di `returns_frame`.

    Include solo i ticker con almeno MIN_PUNTI_STORICO osservazioni valide
    nella finestra; gli altri finiscono in `excluded`. Ritorna
    (mean_returns, cov, excluded): mean_returns e cov sono indicizzati sui
    soli ticker inclusi.
    """
    if returns_frame is None or returns_frame.empty:
        return pd.Series(dtype=float), pd.DataFrame(), list(tickers)
    lookback_days = int(lookback_months) * TRADING_DAYS_PER_MONTH
    window = returns_frame.tail(lookback_days)
    included: list[str] = []
    excluded: list[str] = []
    for tk in tickers:
        if tk not in window.columns or window[tk].dropna().shape[0] < MIN_PUNTI_STORICO:
            excluded.append(tk)
        else:
            included.append(tk)
    if not included:
        return pd.Series(dtype=float), pd.DataFrame(), excluded
    sub = window[included]
    mean_returns = sub.mean() * 252.0
    cov = sub.cov() * 252.0
    return mean_returns, cov, excluded


def _portfolio_point(
    weights: dict[str, float], mean_returns: pd.Series, cov: pd.DataFrame
) -> "FrontierMarker | None":
    """Rendimento/volatilita'/Sharpe di un portafoglio dato dai suoi pesi.

    I pesi si rinormalizzano a somma 1 sui soli ticker presenti in
    `mean_returns` (stessa convenzione di combine_weighted_returns in
    core/domain/returns.py): un ticker assente (storico insufficiente
    sull'orizzonte scelto) non fa perdere massa, il suo peso si
    ridistribuisce sugli altri. Ritorna None se nessun ticker di `weights`
    e' presente in `mean_returns`, o se il peso totale e' zero.
    """
    cols = [t for t in weights if t in mean_returns.index and weights[t] > 0]
    if not cols:
        return None
    total = sum(weights[t] for t in cols)
    if total <= 0:
        return None
    w = pd.Series({t: weights[t] / total for t in cols})
    ret = float((w * mean_returns.reindex(w.index)).sum())
    cov_sub = cov.reindex(index=w.index, columns=w.index).fillna(0.0)
    variance = float(w.to_numpy() @ cov_sub.to_numpy() @ w.to_numpy())
    vol = float(np.sqrt(max(variance, 0.0)))
    sharpe = ret / vol if vol > 1e-9 else 0.0
    return FrontierMarker(label="", ret=ret, vol=vol, sharpe=sharpe)


def _current_value_weights(ranking: pd.DataFrame, tickers: list[str]) -> dict[str, float]:
    """Pesi a valore corrente (quantita' * prezzo unitario) sui soli `tickers`."""
    work = ranking[ranking["ticker"].isin(tickers)]
    return {
        str(r["ticker"]): float(r.get("current_qty", 0.0) or 0.0) * float(r.get("unit_price", 0.0) or 0.0)
        for _, r in work.iterrows()
    }


def _proposed_value_weights(
    ranking: pd.DataFrame, matrix: pd.DataFrame, tickers: list[str]
) -> dict[str, float]:
    """Pesi a valore proposto (valore attuale + quote suggerite * prezzo)
    sui soli `tickers`. Se `matrix` e' vuota (nessuna quota suggerita,
    es. budget esaurito), coincide con i pesi correnti."""
    current = _current_value_weights(ranking, tickers)
    if matrix is None or matrix.empty:
        return current
    sug_by_ticker = dict(zip(matrix["_ticker"].astype(str), matrix["Sug"]))
    px_by_ticker = dict(zip(matrix["_ticker"].astype(str), matrix["_price"]))
    values = dict(current)
    for tk in tickers:
        sug = float(sug_by_ticker.get(tk, 0) or 0)
        px = float(px_by_ticker.get(tk, 0.0) or 0.0)
        values[tk] = values.get(tk, 0.0) + sug * px
    return values


def _blend_weights(weights_a: dict[str, float], weights_b: dict[str, float], pct_b: float) -> dict[str, float]:
    """Interpola linearmente due vettori di pesi a valore (0.0 = tutto A,
    1.0 = tutto B) - usata per il marker Manuale (slider Attuale->Proposta)."""
    pct_b = max(0.0, min(1.0, pct_b))
    keys = set(weights_a) | set(weights_b)
    return {k: weights_a.get(k, 0.0) * (1.0 - pct_b) + weights_b.get(k, 0.0) * pct_b for k in keys}
