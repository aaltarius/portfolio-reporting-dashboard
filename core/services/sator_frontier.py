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
MIN_CLOUD_UNIQUE_FRACTION = 0.5


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


def _sample_capped_weights(n: int, max_share: float, rng: np.random.Generator, *, max_attempts: int = 5000) -> np.ndarray:
    """Un vettore di pesi long-only sul simplesso (Dirichlet alpha=1),
    ricampionato finche' nessun peso supera `max_share` (rifiuto), fino a
    `max_attempts` tentativi. Se `max_share` e' sotto il minimo
    matematicamente raggiungibile (1/n - es. un cap troppo stretto per il
    numero di strumenti), si usa 1/n come cap effettivo: altrimenti
    nessun vettore sarebbe mai ammissibile e il campionamento non
    terminerebbe mai (bug corretto in fix round 1, segnalato da code
    review). Se il cap e' tecnicamente raggiungibile ma con un tasso di
    accettazione bassissimo, dopo `max_attempts` tentativi si ricade su
    pesi uniformi (1/n ciascuno, sempre ammissibili per costruzione) -
    garanzia di terminazione anche nel caso limite."""
    effective_cap = max(max_share, 1.0 / n) if n > 0 else max_share
    if effective_cap >= 1.0:
        return rng.dirichlet(np.ones(n))
    for _ in range(max_attempts):
        w = rng.dirichlet(np.ones(n))
        if w.max() <= effective_cap:
            return w
    return np.full(n, 1.0 / n)


def _simulate_random_portfolios(
    mean_returns: pd.Series, cov: pd.DataFrame, max_share: float, n_scenarios: int, seed: int | None = None,
) -> pd.DataFrame:
    """Nuvola di portafogli casuali long-only sui ticker di `mean_returns`,
    col cap di concentrazione `max_share` (stessa soglia gia' usata da
    SATOR per le linee, `cfg["max_share_per_line"]`). Nessun ottimizzatore:
    la "frontiera" e' il bordo superiore osservato di questa nuvola.

    Rifiuto vettorizzato a blocchi (non un ciclo Python campione-per-
    campione): quando il cap e' stretto rispetto al numero di strumenti
    il tasso di accettazione puo' essere molto basso (es. ~0.3% con 3
    strumenti e cap 0.35), e un ciclo Python a un campione per iterazione
    misurato in code review impiegava oltre 25 secondi sui default -
    campionare a blocchi con numpy riduce lo stesso numero di estrazioni
    a una frazione di secondo. Se il cap e' matematicamente irraggiungibile
    (sotto 1/n) si usa 1/n come cap effettivo; se restano scenari non
    accettati dopo un numero massimo di blocchi, si completa con pesi
    uniformi (1/n ciascuno, sempre ammissibili). cov viene riempita con
    fillna(0.0) prima dell'uso, stessa convenzione di _portfolio_point in
    Task 1 - evita vol NaN quando due strumenti non hanno storico
    sovrapposto nella finestra scelta."""
    tickers = list(mean_returns.index)
    n = len(tickers)
    if n == 0:
        return pd.DataFrame(columns=["ret", "vol"])
    rng = np.random.default_rng(seed)
    mean_arr = mean_returns.to_numpy()
    cov_arr = cov.reindex(index=tickers, columns=tickers).fillna(0.0).to_numpy()

    effective_cap = max(max_share, 1.0 / n)
    if effective_cap >= 1.0:
        weights = rng.dirichlet(np.ones(n), size=n_scenarios)
    else:
        batch_size = max(n_scenarios * 4, 2000)
        max_batches = 50
        accepted = np.empty((0, n))
        for _ in range(max_batches):
            if len(accepted) >= n_scenarios:
                break
            batch = rng.dirichlet(np.ones(n), size=batch_size)
            ok = batch[batch.max(axis=1) <= effective_cap]
            accepted = np.vstack([accepted, ok]) if len(accepted) else ok
        if len(accepted) < n_scenarios:
            missing = n_scenarios - len(accepted)
            fallback = np.full((missing, n), 1.0 / n)
            accepted = np.vstack([accepted, fallback]) if len(accepted) else fallback
        weights = accepted[:n_scenarios]

    rets = weights @ mean_arr
    variances = np.einsum("ij,jk,ik->i", weights, cov_arr, weights)
    vols = np.sqrt(np.maximum(variances, 0.0))
    return pd.DataFrame({"ret": rets, "vol": vols})


def _extract_cloud_extremes(cloud: pd.DataFrame) -> tuple[FrontierMarker, FrontierMarker]:
    """Punto a minor volatilita' e punto a miglior Sharpe *osservati* nella
    nuvola simulata (non un ottimo matematico)."""
    min_row = cloud.loc[cloud["vol"].idxmin()]
    min_risk = FrontierMarker(
        label="Min-rischio", ret=float(min_row["ret"]), vol=float(min_row["vol"]),
        sharpe=float(min_row["ret"] / min_row["vol"]) if min_row["vol"] > 1e-9 else 0.0,
    )
    sharpe = cloud["ret"] / cloud["vol"].replace(0.0, np.nan)
    if sharpe.notna().any():
        best_idx = sharpe.idxmax()
        max_sharpe = FrontierMarker(
            label="Miglior Sharpe", ret=float(cloud.loc[best_idx, "ret"]), vol=float(cloud.loc[best_idx, "vol"]),
            sharpe=float(sharpe.loc[best_idx]),
        )
    else:
        # Tutta la nuvola ha volatilita' zero (strumenti a varianza nulla
        # nella finestra scelta): nessuno Sharpe e' definito, "miglior
        # Sharpe" coincide col minimo rischio per definizione.
        max_sharpe = FrontierMarker(label="Miglior Sharpe", ret=min_risk.ret, vol=min_risk.vol, sharpe=min_risk.sharpe)
    return min_risk, max_sharpe


def _classify_vs_current(current: FrontierMarker, candidate: FrontierMarker) -> str:
    """Etichetta di confronto candidate vs current, tabella 3x3 completa su
    d_ret/d_vol con una banda neutra - vedi design, sezione classificazione,
    per la tabella per esteso. "atteso" della roadmap riformulato in
    "storico" per coerenza col resto della sezione (mai la parola "atteso")."""
    d_ret = candidate.ret - current.ret
    d_vol = candidate.vol - current.vol
    ret_sign = "+" if d_ret > RETURN_NEUTRAL_BAND else ("-" if d_ret < -RETURN_NEUTRAL_BAND else "neutro")
    vol_sign = "+" if d_vol > VOL_NEUTRAL_BAND else ("-" if d_vol < -VOL_NEUTRAL_BAND else "neutro")
    table = {
        ("-", "-"): "riduce il rischio ma sacrifica rendimento storico",
        ("-", "neutro"): "migliora",
        ("-", "+"): "migliora",
        ("neutro", "-"): "peggiora",
        ("neutro", "neutro"): "neutro",
        ("neutro", "+"): "migliora",
        ("+", "-"): "peggiora",
        ("+", "neutro"): "peggiora",
        ("+", "+"): "migliora il target ma aumenta troppo il rischio",
    }
    return table[(vol_sign, ret_sign)]


def _classify_vs_frontier(candidate: FrontierMarker, cloud: pd.DataFrame) -> str:
    """"Vicino"/"lontano dalla proposta efficiente": confronta la
    volatilita' del candidato col minimo osservato nella nuvola tra i
    portafogli simulati con rendimento pari o superiore. Se la nuvola e'
    vuota o nessun punto raggiunge il rendimento del candidato, e' "vicino"
    per definizione (non c'e' un'alternativa osservata migliore)."""
    if cloud is None or cloud.empty:
        return "vicino alla proposta efficiente"
    at_or_above = cloud[cloud["ret"] >= candidate.ret]
    if at_or_above.empty:
        return "vicino alla proposta efficiente"
    best_vol = float(at_or_above["vol"].min())
    gap = candidate.vol - best_vol
    return "vicino alla proposta efficiente" if gap <= FRONTIER_CLOSE_BAND else "lontano dalla proposta efficiente"


@dataclass(frozen=True)
class SatorFrontierResult:
    available: bool
    reason: str
    cloud: pd.DataFrame
    markers: list[FrontierMarker]
    excluded_tickers: list[str]
    n_universe: int
    has_proposal: bool
    cloud_degenerate: bool
    verdict_vs_current: str
    verdict_vs_frontier: str


def _unavailable(reason: str) -> SatorFrontierResult:
    return SatorFrontierResult(
        available=False, reason=reason, cloud=pd.DataFrame(columns=["ret", "vol"]),
        markers=[], excluded_tickers=[], n_universe=0, has_proposal=False, cloud_degenerate=False,
        verdict_vs_current="", verdict_vs_frontier="",
    )


def build_sator_frontier(
    data: dict[str, Any],
    settings: dict[str, Any],
    *,
    precomputed_result: dict[str, Any],
    lookback_months: int = 12,
    manual_slider_pct: float = 0.0,
    n_scenarios: int = N_SCENARIOS_DEFAULT,
    seed: int | None = None,
) -> SatorFrontierResult:
    ranking = precomputed_result.get("ranking", pd.DataFrame())
    returns_frame = precomputed_result.get("returns_frame", pd.DataFrame())
    cfg = precomputed_result.get("sator_settings", {}) or {}
    if ranking is None or ranking.empty:
        return _unavailable("Nessuno strumento nell'universo SATOR.")

    if "storico_sufficiente" in ranking.columns:
        universe = [str(t) for t in ranking.loc[ranking["storico_sufficiente"].astype(bool), "ticker"].tolist()]
        short_history = [str(t) for t in ranking.loc[~ranking["storico_sufficiente"].astype(bool), "ticker"].tolist()]
    else:
        universe = [str(t) for t in ranking["ticker"].tolist()]
        short_history = []
    mean_returns, cov, excluded = _historical_return_and_cov(returns_frame, universe, lookback_months)
    excluded = short_history + excluded
    if len(mean_returns) < MIN_UNIVERSE_SIZE:
        return _unavailable(
            f"Servono almeno {MIN_UNIVERSE_SIZE} strumenti con storico sufficiente "
            f"sull'orizzonte scelto ({lookback_months} mesi), disponibili {len(mean_returns)}."
        )
    included = list(mean_returns.index)
    max_share = float(cfg.get("max_share_per_line", 0.35) or 0.35)
    budget = float(cfg.get("default_budget", 0.0) or 0.0)
    matrix = build_sator_matrix_frame(ranking, budget=budget) if budget > 0 else pd.DataFrame()

    current_values = _current_value_weights(ranking, included)
    proposed_values = _proposed_value_weights(ranking, matrix, included)

    current_point = _portfolio_point(current_values, mean_returns, cov)
    if current_point is None:
        return _unavailable("Nessuna posizione attuale con storico sufficiente sull'orizzonte scelto.")
    proposed_point = _portfolio_point(proposed_values, mean_returns, cov) or current_point

    has_proposal = False
    if not matrix.empty:
        sug_map = dict(zip(matrix["_ticker"].astype(str), matrix["Sug"]))
        has_proposal = any(float(sug_map.get(tk, 0) or 0) > 0 for tk in included)

    manual_values = _blend_weights(current_values, proposed_values, manual_slider_pct)
    manual_point = _portfolio_point(manual_values, mean_returns, cov) or current_point

    cloud = _simulate_random_portfolios(mean_returns, cov, max_share, n_scenarios, seed)
    if cloud.empty:
        min_risk_point, max_sharpe_point = current_point, current_point
        cloud_degenerate = True
    else:
        min_risk_point, max_sharpe_point = _extract_cloud_extremes(cloud)
        unique_fraction = len(cloud.drop_duplicates()) / len(cloud)
        cloud_degenerate = unique_fraction < MIN_CLOUD_UNIQUE_FRACTION

    markers = [
        FrontierMarker(label="Attuale", ret=current_point.ret, vol=current_point.vol, sharpe=current_point.sharpe),
        FrontierMarker(label="Proposta SATOR", ret=proposed_point.ret, vol=proposed_point.vol, sharpe=proposed_point.sharpe),
        FrontierMarker(label="Manuale", ret=manual_point.ret, vol=manual_point.vol, sharpe=manual_point.sharpe),
        FrontierMarker(label="Min-rischio", ret=min_risk_point.ret, vol=min_risk_point.vol, sharpe=min_risk_point.sharpe),
        FrontierMarker(label="Miglior Sharpe", ret=max_sharpe_point.ret, vol=max_sharpe_point.vol, sharpe=max_sharpe_point.sharpe),
    ]
    return SatorFrontierResult(
        available=True, reason="", cloud=cloud, markers=markers,
        excluded_tickers=excluded, n_universe=len(included), has_proposal=has_proposal,
        cloud_degenerate=cloud_degenerate,
        verdict_vs_current=_classify_vs_current(current_point, manual_point),
        verdict_vs_frontier=_classify_vs_frontier(manual_point, cloud),
    )
