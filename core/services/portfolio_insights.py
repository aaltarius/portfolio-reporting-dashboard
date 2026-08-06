"""Insight decisionali sintetici per la pagina Portafoglio.

Il modulo e' volutamente read-only: usa dati, impostazioni e report gia'
calcolati dalla Home per produrre priorita' operative senza creare una seconda
fonte di verita' sui numeri del portafoglio.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import pandas as pd

from core.instrument_classification import classify_natura
from core.services.sator import compute_current_bucket_mix, compute_instrument_buckets, latest_sator_decision
from persistence.storage import load_sator_decisions, macro_cat


_BUCKET_LABELS = {
    "core": "Core",
    "difensivo": "Difensivo",
    "satellite": "Satellite",
}
_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2, "positive": 3}


@dataclass(frozen=True)
class PortfolioInsight:
    id: str
    severity: str
    area: str
    title: str
    message: str
    action: str
    rank: int
    ticker: str = ""
    name: str = ""
    category: str = ""
    bucket: str = ""
    natura: str = ""
    value: float | None = None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _fmt_pct(value: float, decimals: int = 1, *, signed: bool = False) -> str:
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{value * 100:.{decimals}f}%".replace(".", ",")


def _fmt_pp(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value * 100:.1f} pp".replace(".", ",")


def _fmt_eur(value: float) -> str:
    sign = "+" if value > 0 else "-" if value < 0 else ""
    abs_value = abs(value)
    formatted = f"{abs_value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{sign}EUR {formatted}"


def _fmt_date_it(value: str) -> str:
    text = str(value or "").strip()[:10]
    try:
        dt = pd.to_datetime(text, errors="raise")
    except Exception:
        return text
    return dt.strftime("%d/%m/%Y")


def _add_unique(items: list[PortfolioInsight], insight: PortfolioInsight) -> None:
    if not any(existing.id == insight.id for existing in items):
        items.append(insight)


def _instrument_metadata(data: dict[str, Any], da: pd.DataFrame | None) -> dict[str, dict[str, str]]:
    held = set()
    if da is not None and not da.empty and "Ticker" in da.columns:
        held = {str(tk).strip().upper() for tk in da["Ticker"].dropna()}
    try:
        buckets = compute_instrument_buckets(data, held)
    except Exception:
        buckets = {}
    out: dict[str, dict[str, str]] = {}
    for item in data.get("strumenti", []) or []:
        ticker = str(item.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        natura = str(item.get("natura") or "").strip()
        if not natura:
            try:
                natura = classify_natura(item)
            except Exception:
                natura = "Esposizione diversificata"
        out[ticker] = {
            "category": macro_cat(item.get("tipo", "")),
            "bucket": str(buckets.get(ticker) or ""),
            "natura": natura or "Esposizione diversificata",
            "name": str(item.get("nome") or ticker),
        }
    return out


def _meta_value(metadata: dict[str, dict[str, str]], ticker: str, key: str) -> str:
    return str(metadata.get(str(ticker or "").strip().upper(), {}).get(key) or "")


def _resolve_sator_decisions(sator_decisions: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if sator_decisions is not None:
        return sator_decisions
    try:
        return list(load_sator_decisions().get("items", []) or [])
    except Exception:
        return []


def _latest_sator_suggestions_by_bucket(decisions: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    latest = latest_sator_decision(decisions or [])
    if not latest:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for line in latest.get("order_lines", []) or []:
        if not isinstance(line, dict):
            continue
        ticker = str(line.get("ticker") or "").strip().upper()
        bucket = str(line.get("bucket") or "").strip()
        amount = _safe_float(line.get("amount", line.get("importo")), 0.0)
        if not ticker or not bucket or amount <= 0:
            continue
        score = (
            _safe_float(line.get("target_improvement_pp"), 0.0),
            amount,
            _safe_float(line.get("voto", line.get("score_finale", line.get("score"))), 0.0),
        )
        current = out.get(bucket)
        if current is None or score > current["_score_tuple"]:
            enriched = dict(line)
            enriched["_score_tuple"] = score
            out[bucket] = enriched
    return out


def _build_target_gap_insights(
    da: pd.DataFrame,
    data: dict[str, Any],
    settings: dict[str, Any],
    metadata: dict[str, dict[str, str]],
    *,
    bucket_mix: dict[str, float] | None,
    sator_suggestions: dict[str, dict[str, Any]] | None,
) -> list[PortfolioInsight]:
    if da is None or da.empty:
        return []
    if bucket_mix is None:
        try:
            bucket_mix = compute_current_bucket_mix(data, da)
        except Exception:
            bucket_mix = {}

    objective = settings.get("portfolio_objective", {}) if isinstance(settings, dict) else {}
    items: list[PortfolioInsight] = []
    for key, label in _BUCKET_LABELS.items():
        target = max(0.0, _safe_float(objective.get(key), 0.0))
        current = max(0.0, _safe_float(bucket_mix.get(label), 0.0))
        if target <= 0:
            continue
        delta = current - target
        abs_delta = abs(delta)
        if abs_delta < 0.035:
            continue
        underweight = delta < 0
        severity = "warning" if abs_delta >= 0.08 else "info"
        ticker = ""
        action = f"Evita nuovo peso su {label} finche' lo scostamento non rientra."
        if underweight:
            suggestion = (sator_suggestions or {}).get(label)
            if suggestion:
                ticker = str(suggestion.get("ticker") or "").strip().upper()
                amount = _safe_float(suggestion.get("amount", suggestion.get("importo")), 0.0)
                vote = suggestion.get("voto") or suggestion.get("score") or suggestion.get("score_finale")
                vote_text = f", voto {_safe_float(vote):.1f}".replace(".", ",") if vote not in (None, "") else ""
                action = f"Priorita' concreta: valuta {ticker} per circa {_fmt_eur(amount)}{vote_text}."
            else:
                action = f"Apri SATOR e filtra {label}: serve un acquisto che aumenti questo bucket."
        _add_unique(
            items,
            PortfolioInsight(
                id=f"target-gap-{key}",
                severity=severity,
                area="Allocazione",
                title=f"{label} {'sotto target' if underweight else 'sopra target'}",
                message=(
                    f"Peso attuale {_fmt_pct(current)} contro obiettivo {_fmt_pct(target)} "
                    f"({_fmt_pp(delta)})."
                ),
                action=action,
                rank=int(abs_delta * 1000),
                ticker=ticker,
                name=_meta_value(metadata, ticker, "name"),
                category=_meta_value(metadata, ticker, "category"),
                bucket=label,
                natura=_meta_value(metadata, ticker, "natura"),
                value=delta,
            ),
        )
    return items


def _build_concentration_insight(
    da: pd.DataFrame,
    settings: dict[str, Any],
    metadata: dict[str, dict[str, str]],
) -> PortfolioInsight | None:
    if da is None or da.empty or "Peso %" not in da.columns:
        return None
    alerts = settings.get("alerts", {}) if isinstance(settings, dict) else {}
    threshold_raw = alerts.get("concentration_threshold_pct")
    threshold = _safe_float(threshold_raw, 0.0) / 100.0 if threshold_raw not in (None, "") else 0.25
    threshold = threshold if threshold > 0 else 0.25
    weights = pd.to_numeric(da["Peso %"], errors="coerce").fillna(0.0)
    if weights.empty:
        return None
    idx = weights.idxmax()
    top_weight = float(weights.loc[idx])
    if top_weight < max(0.18, threshold * 0.75):
        return None
    row = da.loc[idx]
    ticker = str(row.get("Ticker") or "").strip().upper()
    name = str(row.get("Strumento") or ticker)
    severity = "warning" if top_weight >= threshold else "info"
    return PortfolioInsight(
        id=f"concentration-{ticker or 'top'}",
        severity=severity,
        area="Concentrazione",
        title="Peso dominante",
        message=f"{ticker or name} pesa {_fmt_pct(top_weight)} del portafoglio.",
        action=(
            "Usa i prossimi acquisti per diluire la posizione."
            if severity == "warning"
            else "Tienilo monitorato se continui ad accumulare."
        ),
        rank=int(top_weight * 1000),
        ticker=ticker,
        name=_meta_value(metadata, ticker, "name") or name,
        category=_meta_value(metadata, ticker, "category"),
        bucket=_meta_value(metadata, ticker, "bucket"),
        natura=_meta_value(metadata, ticker, "natura"),
        value=top_weight,
    )


def _build_daily_insights(
    da: pd.DataFrame,
    direction_map: dict[str, Any] | None,
    daily_report: dict[str, Any] | None,
    metadata: dict[str, dict[str, str]],
) -> list[PortfolioInsight]:
    insights: list[PortfolioInsight] = []
    if daily_report:
        worst = list(daily_report.get("worst") or [])
        best = list(daily_report.get("best") or [])
        if worst:
            item = worst[0]
            delta = _safe_float(item.get("delta"), 0.0)
            if abs(delta) >= 1.0:
                ticker = str(item.get("ticker") or "").strip().upper()
                pct_text = ""
                pct = item.get("pct_change")
                if pct is not None:
                    pct_text = f" ({_fmt_pct(_safe_float(pct), 2, signed=True)})"
                insights.append(
                    PortfolioInsight(
                        id=f"daily-worst-{item.get('ticker') or 'x'}",
                        severity="warning" if abs(delta) >= 10 else "info",
                        area="Giornata",
                        title="Impatto negativo principale",
                        message=f"{item.get('ticker') or item.get('name')} incide per {_fmt_eur(delta)}{pct_text}.",
                        action="Controlla se il movimento e' prezzo reale o dato ritardato.",
                        rank=int(abs(delta) * 10),
                        ticker=ticker,
                        name=_meta_value(metadata, ticker, "name") or str(item.get("name") or ""),
                        category=_meta_value(metadata, ticker, "category"),
                        bucket=_meta_value(metadata, ticker, "bucket"),
                        natura=_meta_value(metadata, ticker, "natura"),
                        value=delta,
                    )
                )
        if best:
            item = best[0]
            delta = _safe_float(item.get("delta"), 0.0)
            if delta >= 1.0:
                ticker = str(item.get("ticker") or "").strip().upper()
                insights.append(
                    PortfolioInsight(
                        id=f"daily-best-{item.get('ticker') or 'x'}",
                        severity="positive",
                        area="Giornata",
                        title="Contributo positivo principale",
                        message=f"{item.get('ticker') or item.get('name')} aggiunge {_fmt_eur(delta)} nella giornata.",
                        action="Usalo come confronto per leggere il saldo giornaliero complessivo.",
                        rank=int(delta * 10),
                        ticker=ticker,
                        name=_meta_value(metadata, ticker, "name") or str(item.get("name") or ""),
                        category=_meta_value(metadata, ticker, "category"),
                        bucket=_meta_value(metadata, ticker, "bucket"),
                        natura=_meta_value(metadata, ticker, "natura"),
                        value=delta,
                    )
                )

    if da is None or da.empty or not direction_map:
        return insights

    for _, row in da.iterrows():
        ticker = str(row.get("Ticker") or "").strip().upper()
        raw = direction_map.get(ticker)
        if not isinstance(raw, dict):
            continue
        current_pl = _safe_float(row.get("P/L €"), 0.0)
        delta = _safe_float(raw.get("delta_eur"), 0.0)
        previous_pl = current_pl - delta
        if abs(current_pl) < 0.01 or abs(previous_pl) < 0.01:
            continue
        if (previous_pl < 0 < current_pl) or (previous_pl > 0 > current_pl):
            positive = current_pl > 0
            insights.append(
                PortfolioInsight(
                    id=f"pl-cross-{ticker}",
                    severity="positive" if positive else "warning",
                    area="Cambio segno",
                    title=f"{ticker} cambia colore",
                    message=(
                        f"P/L da {_fmt_eur(previous_pl)} a {_fmt_eur(current_pl)} "
                        f"per effetto della variazione giornaliera."
                    ),
                    action="La riga in tabella evidenzia il passaggio di segno.",
                    rank=900 + int(abs(delta) * 10),
                    ticker=ticker,
                    name=_meta_value(metadata, ticker, "name"),
                    category=_meta_value(metadata, ticker, "category"),
                    bucket=_meta_value(metadata, ticker, "bucket"),
                    natura=_meta_value(metadata, ticker, "natura"),
                    value=current_pl,
                )
            )
    return insights


def _build_recent_trend_insights(
    da: pd.DataFrame,
    data: dict[str, Any],
    metadata: dict[str, dict[str, str]],
    *,
    window: int = 5,
) -> list[PortfolioInsight]:
    if da is None or da.empty or "Ticker" not in da.columns:
        return []
    storico = data.get("storico_prezzi", {}) if isinstance(data, dict) else {}
    if not isinstance(storico, dict) or not storico:
        return []
    all_dates = sorted(str(day) for day in storico.keys())
    if len(all_dates) < 3:
        return []
    latest_global = all_dates[-1]
    held_rows = da.set_index(da["Ticker"].astype(str).str.strip().str.upper(), drop=False)
    rows: list[dict[str, Any]] = []
    for ticker, row in held_rows.iterrows():
        points: list[tuple[str, float]] = []
        for day in all_dates:
            values = storico.get(day)
            if not isinstance(values, dict):
                continue
            price = _safe_float(values.get(ticker), 0.0)
            if price > 0:
                points.append((day, price))
        if len(points) < 3 or points[-1][0] != latest_global:
            continue
        recent = points[-max(3, int(window) + 1):]
        first_date, first_price = recent[0]
        last_date, last_price = recent[-1]
        if first_price <= 0 or first_date == last_date:
            continue
        ret = (last_price / first_price) - 1.0
        values = [price for _, price in recent]
        close_note = ""
        if last_price >= max(values) * 0.995:
            close_note = " e chiude sui massimi recenti"
        elif last_price <= min(values) * 1.005:
            close_note = " e chiude sui minimi recenti"
        rows.append(
            {
                "ticker": ticker,
                "name": _meta_value(metadata, ticker, "name") or str(row.get("Strumento") or ""),
                "ret": ret,
                "days": max(1, len(recent) - 1),
                "close_note": close_note,
            }
        )
    if not rows:
        return []

    insights: list[PortfolioInsight] = []
    best = max(rows, key=lambda item: item["ret"])
    worst = min(rows, key=lambda item: item["ret"])
    if _safe_float(best.get("ret"), 0.0) >= 0.005:
        ticker = str(best["ticker"])
        days = int(best["days"])
        insights.append(
            PortfolioInsight(
                id=f"recent-best-{ticker}",
                severity="positive",
                area="Trend",
                title=f"Miglior andamento a {days} sedute",
                message=f"{ticker} segna {_fmt_pct(best['ret'], 2, signed=True)} nelle ultime {days} sedute{best['close_note']}.",
                action="Momentum favorevole: utile come conferma, senza inseguire se peso e cap sono gia' tirati.",
                rank=int(abs(best["ret"]) * 1000),
                ticker=ticker,
                name=str(best.get("name") or ""),
                category=_meta_value(metadata, ticker, "category"),
                bucket=_meta_value(metadata, ticker, "bucket"),
                natura=_meta_value(metadata, ticker, "natura"),
                value=float(best["ret"]),
            )
        )
    if _safe_float(worst.get("ret"), 0.0) <= -0.005:
        ticker = str(worst["ticker"])
        days = int(worst["days"])
        insights.append(
            PortfolioInsight(
                id=f"recent-worst-{ticker}",
                severity="warning",
                area="Trend",
                title=f"Debolezza a {days} sedute",
                message=f"{ticker} segna {_fmt_pct(worst['ret'], 2, signed=True)} nelle ultime {days} sedute{worst['close_note']}.",
                action="Da leggere con SATOR: puo' essere opportunita' solo se migliora target, cap e qualita' dati.",
                rank=int(abs(worst["ret"]) * 1000),
                ticker=ticker,
                name=str(worst.get("name") or ""),
                category=_meta_value(metadata, ticker, "category"),
                bucket=_meta_value(metadata, ticker, "bucket"),
                natura=_meta_value(metadata, ticker, "natura"),
                value=float(worst["ret"]),
            )
        )
    return insights


def _latest_market_date(data: dict[str, Any]) -> str:
    storico = data.get("storico_prezzi", {}) if isinstance(data, dict) else {}
    valid_dates = [
        str(day)
        for day, values in (storico or {}).items()
        if isinstance(values, dict) and any(_safe_float(v, 0.0) > 0 for v in values.values())
    ]
    return max(valid_dates) if valid_dates else ""


def _build_data_freshness_insight(
    da: pd.DataFrame,
    data: dict[str, Any],
    metadata: dict[str, dict[str, str]],
) -> PortfolioInsight | None:
    if da is None or da.empty:
        return None
    latest_date = _latest_market_date(data)
    if not latest_date:
        return None
    held = {str(tk).strip().upper() for tk in da.get("Ticker", pd.Series(dtype=str)).dropna()}
    stale: list[str] = []
    for item in data.get("strumenti", []) or []:
        ticker = str(item.get("ticker") or "").strip().upper()
        if ticker not in held:
            continue
        updated = str(item.get("aggiornato") or "")[:10]
        if updated and updated < latest_date:
            stale.append(ticker)
    if not stale:
        return None
    sample = ", ".join(stale[:4])
    suffix = f" e altri {len(stale) - 4}" if len(stale) > 4 else ""
    latest_display = _fmt_date_it(latest_date)
    return PortfolioInsight(
        id="data-freshness",
        severity="info",
        area="Qualita' dati",
        title="Quotazioni non allineate",
        message=f"{len(stale)} strumenti risultano aggiornati prima del {latest_display}: {sample}{suffix}.",
        action="Prima di decidere nuovi ordini, aggiorna le quotazioni e ricontrolla gli scostamenti.",
        rank=100 + len(stale),
        ticker=stale[0] if stale else "",
        name=_meta_value(metadata, stale[0], "name") if stale else "",
        category=_meta_value(metadata, stale[0], "category") if stale else "",
        bucket=_meta_value(metadata, stale[0], "bucket") if stale else "",
        natura=_meta_value(metadata, stale[0], "natura") if stale else "",
        value=float(len(stale)),
    )


def _build_sator_insight(
    sator_decisions: list[dict[str, Any]],
    metadata: dict[str, dict[str, str]],
) -> PortfolioInsight | None:
    latest = latest_sator_decision(sator_decisions or [])
    if not latest:
        return None
    lines = [line for line in latest.get("order_lines", []) or [] if isinstance(line, dict)]
    if not lines:
        return None
    top = max(lines, key=lambda line: _safe_float(line.get("amount", line.get("importo")), 0.0))
    ticker = str(top.get("ticker") or "").strip().upper()
    amount = _safe_float(top.get("amount", top.get("importo")), 0.0)
    bucket = str(top.get("bucket") or "")
    vote = top.get("voto") or top.get("score") or top.get("final_score")
    vote_text = f", voto {_safe_float(vote):.1f}".replace(".", ",") if vote not in (None, "") else ""
    return PortfolioInsight(
        id=f"sator-latest-{ticker or 'decision'}",
        severity="info",
        area="SATOR",
        title="Prossimo acquisto suggerito",
        message=f"{ticker or 'Prima linea'} per {_fmt_eur(amount)}{vote_text} ({bucket or 'bucket non indicato'}).",
        action="Apri Pianificazione per leggere ranking, esclusioni e motivazioni.",
        rank=80,
        ticker=ticker,
        name=_meta_value(metadata, ticker, "name") or str(top.get("name") or ""),
        category=_meta_value(metadata, ticker, "category"),
        bucket=bucket or _meta_value(metadata, ticker, "bucket"),
        natura=_meta_value(metadata, ticker, "natura"),
        value=amount,
    )


_ALERT_SEVERITY_MAP = {"high": "critical", "medium": "warning", "low": "info"}
_ALERT_ACTIONS = {
    "concentration": "Valuta di ridurre il peso per rientrare sotto soglia.",
    "loss": "Valuta se mantenere la posizione o chiudere la perdita.",
    "risk_weight": "Rivedi la posizione: il rischio assunto e' alto rispetto al peso in portafoglio.",
    "drawdown": "Monitora l'andamento: il calo dai massimi ha superato la soglia impostata.",
    "volatility": "Aspettati oscillazioni ampie: la volatilita' ha superato la soglia impostata.",
}
_DEFAULT_ALERT_ACTION = "Valuta la posizione: ha superato una soglia di rischio impostata."


def _build_alert_insights(
    portfolio_alerts: list[dict[str, Any]] | None,
    metadata: dict[str, dict[str, str]],
) -> list[PortfolioInsight]:
    insights: list[PortfolioInsight] = []
    for item in portfolio_alerts or []:
        kind = str(item.get("kind") or "")
        ticker = str(item.get("ticker") or "").strip().upper()
        value = _safe_float(item.get("value"), 0.0)
        threshold = _safe_float(item.get("threshold"), 0.0)
        rank = int(round(abs(value) / max(abs(threshold), 1e-6) * 100))
        insights.append(
            PortfolioInsight(
                id=f"alert-{kind}-{ticker}",
                severity=_ALERT_SEVERITY_MAP.get(str(item.get("severity") or ""), "warning"),
                area="Rischio",
                title=str(item.get("title") or ""),
                message=str(item.get("message") or ""),
                action=_ALERT_ACTIONS.get(kind, _DEFAULT_ALERT_ACTION),
                rank=rank,
                ticker=ticker,
                name=_meta_value(metadata, ticker, "name") or ticker,
                category=_meta_value(metadata, ticker, "category"),
                bucket=_meta_value(metadata, ticker, "bucket"),
                natura=_meta_value(metadata, ticker, "natura"),
                value=value,
            )
        )
    return insights


def _build_maturity_insights(
    maturity_alerts: list[dict[str, Any]] | None,
    metadata: dict[str, dict[str, str]],
) -> list[PortfolioInsight]:
    insights: list[PortfolioInsight] = []
    for item in maturity_alerts or []:
        ticker = str(item.get("ticker") or "").strip().upper()
        giorni_scaduto = int(_safe_float(item.get("giorni_scaduto"), 0.0))
        quantita = _safe_float(item.get("quantita"), 0.0)
        nome = str(item.get("nome") or ticker)
        scadenza = str(item.get("scadenza") or "")
        insights.append(
            PortfolioInsight(
                id=f"maturity-{ticker}",
                severity="critical",
                area="Scadenze",
                title="Titolo scaduto non rimborsato",
                message=(
                    f"{nome} ({ticker}) scaduto il {scadenza}, {giorni_scaduto} giorni fa, "
                    f"quantita' ancora in portafoglio {quantita:.2f}."
                ),
                action="Registra il rimborso a scadenza dalla sidebar.",
                rank=giorni_scaduto,
                ticker=ticker,
                name=_meta_value(metadata, ticker, "name") or nome,
                category="GOV",
                bucket=_meta_value(metadata, ticker, "bucket"),
                natura=_meta_value(metadata, ticker, "natura"),
                value=quantita,
            )
        )
    return insights


def build_maturity_only_insights(
    maturity_alerts: list[dict[str, Any]] | None,
    data: dict[str, Any] | None,
    da: pd.DataFrame | None,
) -> list[PortfolioInsight]:
    """Scadenze GOV non rimborsate, calcolate sempre.

    A differenza del resto del Radar, questo segnale non dipende dal
    toggle "mostra insight" ne' dal calcolo di direction_map/daily_report:
    e' un problema di integrita' dati (rimborso non registrato), non una
    preferenza di visualizzazione, quindi deve restare visibile anche
    quando l'utente disattiva il Radar decisionale.
    """
    metadata = _instrument_metadata(data or {}, da)
    return _build_maturity_insights(maturity_alerts, metadata)


def build_portfolio_insights(
    da: pd.DataFrame,
    dfh: pd.DataFrame | None,
    data: dict[str, Any],
    settings: dict[str, Any] | None,
    *,
    direction_map: dict[str, Any] | None = None,
    daily_report: dict[str, Any] | None = None,
    bucket_mix: dict[str, float] | None = None,
    sator_decisions: list[dict[str, Any]] | None = None,
    portfolio_alerts: list[dict[str, Any]] | None = None,
    maturity_alerts: list[dict[str, Any]] | None = None,
    max_items: int = 9,
) -> list[PortfolioInsight]:
    """Ritorna le priorita' piu' utili da mostrare sopra la tabella Portafoglio."""
    settings = settings or {}
    data = data or {}
    metadata = _instrument_metadata(data, da)
    resolved_sator_decisions = _resolve_sator_decisions(sator_decisions)
    sator_suggestions = _latest_sator_suggestions_by_bucket(resolved_sator_decisions)
    alert_insights = _build_alert_insights(portfolio_alerts, metadata)
    maturity_insights = _build_maturity_insights(maturity_alerts, metadata)
    alert_concentration_tickers = {
        item.ticker for item in alert_insights if item.id.startswith("alert-concentration-")
    }
    insights: list[PortfolioInsight] = []
    insights.extend(
        _build_target_gap_insights(
            da,
            data,
            settings,
            metadata,
            bucket_mix=bucket_mix,
            sator_suggestions=sator_suggestions,
        )
    )
    concentration = _build_concentration_insight(da, settings, metadata)
    if concentration is not None and concentration.ticker not in alert_concentration_tickers:
        _add_unique(insights, concentration)
    for item in _build_daily_insights(da, direction_map, daily_report, metadata):
        _add_unique(insights, item)
    for item in _build_recent_trend_insights(da, data, metadata):
        _add_unique(insights, item)
    freshness = _build_data_freshness_insight(da, data, metadata)
    if freshness is not None:
        _add_unique(insights, freshness)
    sator = _build_sator_insight(resolved_sator_decisions, metadata)
    if sator is not None:
        _add_unique(insights, sator)

    ordered = _select_balanced_insights(
        insights,
        max_items=max(1, int(max_items or 9)),
    )
    return alert_insights + maturity_insights + ordered


def _sort_key(item: PortfolioInsight) -> tuple[int, int, str, str]:
    return (_SEVERITY_ORDER.get(item.severity, 9), -int(item.rank or 0), item.area, item.title)


def _select_balanced_insights(insights: list[PortfolioInsight], *, max_items: int) -> list[PortfolioInsight]:
    ordered = sorted(insights, key=_sort_key)
    selected: list[PortfolioInsight] = []

    def take(predicate) -> None:
        for item in ordered:
            if item in selected:
                continue
            if predicate(item):
                selected.append(item)
                return

    take(lambda item: item.area == "SATOR")
    take(lambda item: item.area == "Allocazione")
    take(lambda item: item.id.startswith("daily-worst-"))
    take(lambda item: item.id.startswith("daily-best-"))
    take(lambda item: item.id.startswith("recent-worst-"))
    take(lambda item: item.id.startswith("recent-best-"))
    take(lambda item: item.area == "Cambio segno")
    take(lambda item: item.area == "Concentrazione")
    take(lambda item: item.area == "Qualita' dati")

    for item in ordered:
        if len(selected) >= max_items:
            break
        if item not in selected:
            selected.append(item)
    return selected[:max_items]
