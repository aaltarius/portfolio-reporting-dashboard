"""core/services/portfolio_simulation.py — Simulazione Monte Carlo del
portafoglio posseduto (Progetto B, ROADMAP_AI_FINANZA_LIBRO.md).

Bootstrap storico: ricampiona con rimpiazzo i rendimenti giornalieri
semplici osservati del portafoglio (combinazione pesata dei rendimenti
per-strumento sui pesi correnti), non un modello gaussiano/parametrico —
preserva la distribuzione reale (codulate, code) senza stimare una matrice
di covarianza dedicata. Ogni risultato e' uno scenario simulato: nessun
numero qui equivale a un valore garantito o a una promessa di rendimento.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from core.domain.returns import build_simple_returns, combine_weighted_returns

MIN_OBSERVATIONS = 60
HORIZON_DAYS_MAX = 504
_HORIZONS: tuple[tuple[int, str], ...] = ((126, "6 mesi"), (252, "12 mesi"), (504, "24 mesi"))
_FAN_STEP_DAYS = 5
# Percentili annidati (5-95, 10-90, 25-75, 40-60) per un effetto "fan chart"
# a piu' livelli di opacita' intorno alla mediana, invece di due sole bande
# piatte - stessa tecnica dei fan chart di banca centrale.
_FAN_PERCENTILES: tuple[int, ...] = (5, 10, 25, 40, 50, 60, 75, 90, 95)
_FAN_COLUMNS: tuple[str, ...] = tuple(f"p{p}" for p in _FAN_PERCENTILES)


@dataclass(frozen=True)
class HorizonMetrics:
    trading_days: int
    label: str
    median_value: float
    p5_value: float
    p95_value: float
    prob_loss: float
    var_5pct: float
    cvar_5pct: float


@dataclass(frozen=True)
class PortfolioSimulationResult:
    available: bool
    reason: str
    initial_value: float
    n_observations: int
    n_scenarios: int
    extrapolated: bool
    fan_percentiles: pd.DataFrame
    horizons: list[HorizonMetrics]
    excluded_tickers: tuple[str, ...] = ()
    excluded_weight: float = 0.0


def _unavailable(reason: str, n_observations: int) -> PortfolioSimulationResult:
    return PortfolioSimulationResult(
        available=False,
        reason=reason,
        initial_value=0.0,
        n_observations=n_observations,
        n_scenarios=0,
        extrapolated=False,
        fan_percentiles=pd.DataFrame(columns=["trading_day", *_FAN_COLUMNS]),
        horizons=[],
        excluded_tickers=(),
        excluded_weight=0.0,
    )


def build_portfolio_simulation(
    price_frame: pd.DataFrame,
    risk_df: pd.DataFrame,
    *,
    n_scenarios: int = 2000,
    seed: int | None = None,
) -> PortfolioSimulationResult:
    if risk_df is None or risk_df.empty or "Ticker" not in risk_df.columns:
        return _unavailable("Nessuna posizione con dati sufficienti per simulare il portafoglio.", 0)

    weights = risk_df.set_index("Ticker")["Peso %"]
    tickers = [t for t in weights.index if price_frame is not None and t in price_frame.columns]
    if not tickers:
        return _unavailable("Nessuno strumento posseduto ha una storia prezzi disponibile.", 0)

    simple_returns_all = build_simple_returns(price_frame, tickers)

    # Uno strumento appena aperto (poche quotazioni proprie) non deve
    # bloccare l'intero portafoglio: se restasse nel paniere, la finestra
    # comune sotto (dropna(how="any") su TUTTI i ticker pesati) crollerebbe
    # al suo storico corto anche per strumenti con anni di dati. Lo si
    # esclude dal paniere simulato invece di abbassare la soglia o
    # fabbricare rendimenti che non esistono ancora per lui.
    per_ticker_obs = simple_returns_all.count()
    eligible_tickers = [tk for tk in tickers if int(per_ticker_obs.get(tk, 0)) >= MIN_OBSERVATIONS]
    excluded_tickers = [tk for tk in tickers if tk not in eligible_tickers]
    excluded_weight = float(weights.reindex(excluded_tickers).fillna(0.0).sum()) if excluded_tickers else 0.0

    if not eligible_tickers:
        return _unavailable(
            f"Storico insufficiente per una simulazione affidabile: nessuno strumento "
            f"posseduto ha almeno {MIN_OBSERVATIONS} quotazioni proprie.",
            0,
        )

    # Restringe alla finestra comune ai soli ticker ammessi: combine_weighted_returns
    # fa fillna(0.0) sui buchi (comportamento voluto per SATOR, dove serve su
    # finestre parziali), ma per il bootstrap Monte Carlo un giorno in cui uno
    # strumento posseduto non ha ancora storico prezzi non e' un rendimento
    # reale dello 0% con peso pieno: e' un dato mancante che, se lasciato,
    # diluirebbe artificialmente la volatilita' del pool campionato.
    # dropna(how="any") scarta quei giorni prima di combinare, cosi'
    # n_observations riflette solo osservazioni vere.
    simple_returns = simple_returns_all[eligible_tickers].dropna(how="any")
    portfolio_returns = combine_weighted_returns(simple_returns, weights.reindex(eligible_tickers)).dropna()

    n_observations = int(len(portfolio_returns))
    if n_observations < MIN_OBSERVATIONS:
        return _unavailable(
            f"Storico insufficiente per una simulazione affidabile "
            f"(servono almeno {MIN_OBSERVATIONS} osservazioni, disponibili {n_observations}).",
            n_observations,
        )

    eligible_set = set(eligible_tickers)
    initial_value = float(
        pd.to_numeric(
            risk_df.loc[risk_df["Ticker"].isin(eligible_set), "Controvalore"], errors="coerce"
        ).fillna(0.0).sum()
    )
    if initial_value <= 0:
        return _unavailable("Controvalore complessivo non disponibile.", n_observations)

    rng = np.random.default_rng(seed)
    draws = rng.choice(portfolio_returns.to_numpy(), size=(int(n_scenarios), HORIZON_DAYS_MAX), replace=True)
    paths = np.cumprod(1.0 + draws, axis=1)
    values = paths * initial_value

    fan_days = list(range(0, HORIZON_DAYS_MAX, _FAN_STEP_DAYS))
    if fan_days[-1] != HORIZON_DAYS_MAX - 1:
        fan_days.append(HORIZON_DAYS_MAX - 1)
    fan_rows = [{"trading_day": 0, **{col: initial_value for col in _FAN_COLUMNS}}]
    for day in fan_days:
        column = values[:, day]
        pct_values = np.percentile(column, _FAN_PERCENTILES)
        fan_rows.append({
            "trading_day": day + 1,
            **{col: float(v) for col, v in zip(_FAN_COLUMNS, pct_values)},
        })
    fan_percentiles = pd.DataFrame(fan_rows)

    horizons: list[HorizonMetrics] = []
    for trading_days, label in _HORIZONS:
        final_values = values[:, trading_days - 1]
        p5, p50, p95 = (float(v) for v in np.percentile(final_values, [5, 50, 95]))
        prob_loss = float(np.mean(final_values < initial_value))
        var_5pct = initial_value - p5
        tail = final_values[final_values <= p5]
        cvar_5pct = (initial_value - float(tail.mean())) if len(tail) > 0 else var_5pct
        horizons.append(HorizonMetrics(
            trading_days=trading_days, label=label, median_value=p50,
            p5_value=p5, p95_value=p95, prob_loss=prob_loss,
            var_5pct=var_5pct, cvar_5pct=cvar_5pct,
        ))

    return PortfolioSimulationResult(
        available=True,
        reason="",
        initial_value=initial_value,
        n_observations=n_observations,
        n_scenarios=int(n_scenarios),
        extrapolated=n_observations < HORIZON_DAYS_MAX,
        fan_percentiles=fan_percentiles,
        horizons=horizons,
        excluded_tickers=tuple(excluded_tickers),
        excluded_weight=excluded_weight,
    )
