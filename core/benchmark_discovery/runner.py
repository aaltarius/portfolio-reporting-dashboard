"""Esecutore della scoperta: profilo, storico proprio, decisione, salvataggio in archivio.

Parte solo su comando dell'utente (ADR-0018): mai dal render. Una decisione `IN_ATTESA`
(rete assente, nessun candidato) non cancella quella precedente.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .decide import CandidateSource, Decision, resolve
from .profile import DiscoveryProfile, build_profile
from .scoring import blend_series
from .vocabulary import listing_currency

_CONFIDENCE = {"PROPRIA": "Alta", "SORELLA": "Alta", "COMPOSITO": "Media", "MANUALE": "Media",
               "CUGINA": "Media", "ZIA": "Bassa", "NONNA": "Bassa"}
_MAX_TRACE_ROWS = 20


def own_history(data: dict, ticker: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for day, prices in (data.get("storico_prezzi") or {}).items():
        if isinstance(prices, dict) and prices.get(ticker):
            try:
                out[str(day)] = float(prices[ticker])
            except (TypeError, ValueError):
                continue
    return out


def _trim_trace(trace: dict) -> dict:
    trimmed = {k: v for k, v in trace.items() if k not in ("levels", "leg_traces")}
    trimmed["profile"] = {k: v for k, v in trace.get("profile", {}).items() if k != "descriptor"}
    levels = []
    for lv in trace.get("levels", []):
        rows = sorted(lv.get("evaluated", []), key=lambda e: -(e.get("score") or -1))[:_MAX_TRACE_ROWS]
        levels.append({"level": lv.get("level"), "queries": lv.get("queries", []), "evaluated": rows})
    trimmed["levels"] = levels
    return trimmed


def _metadata(ticker: str, code: str, label: str, grade: str, kind: str, source_label: str, family: str,
              series: dict[str, float], currency: str, components: list[dict], decision: Decision | None,
              notes: list[str]) -> dict[str, Any]:
    days = sorted(series)
    meta: dict[str, Any] = {
        "ticker": code, "label": label, "grade": grade, "kind": kind, "source": source_label, "family": family,
        "components": components, "notes": notes, "confidence": _CONFIDENCE.get(grade, "Bassa"),
        "coverage_start": days[0] if days else "", "coverage_end": days[-1] if days else "",
        "currency": currency, "points": len(series),
    }
    disc: dict[str, Any] = {"decided_at": datetime.now(timezone.utc).isoformat(), "instrument": ticker}
    if decision is not None:
        fit = decision.fit
        disc.update(level=decision.level, score=decision.score,
                    corr=None if fit is None or fit.corr is None else round(fit.corr, 4),
                    te_pct=None if fit is None or fit.te_pct is None else round(fit.te_pct, 2),
                    trace=_trim_trace(decision.trace))
    meta["discovery"] = disc
    return meta


def persist(store, ticker: str, profile: DiscoveryProfile, decision: Decision, source: CandidateSource) -> dict | None:
    """Registra la serie scelta (o il composito) e salva l'assegnazione. None se non c'e' una serie da salvare."""
    choice = decision.choice
    if decision.status != "SCELTO" or choice is None:
        return None
    family = profile.kind or "UNCLASSIFIED"
    if choice.symbol == "BLEND":
        legs = decision.trace.get("legs", [])
        series = blend_series([(source.history(leg["symbol"]), leg["weight_pct"]) for leg in legs])
        if not series:
            return None
        for leg in legs:  # le gambe si salvano a loro volta: servono per aggiornare e ricostruire il composito
            leg_series = source.history(leg["symbol"])
            if leg_series:
                store.register_series(leg["symbol"], leg.get("name") or leg["symbol"], "yahoo",
                                      listing_currency(leg["symbol"]), "ETF_ADJ_CLOSE", leg.get("kind") or family)
                store.upsert(leg["symbol"], leg_series, source="discovery", replace_existing=True)
        code, label, currency = f"BLEND:{ticker}", choice.name, "EUR"
        kind, provider, return_type = "composite", "discovery", "BLEND"
        components = [{"series_id": leg["symbol"], "label": leg["name"], "weight_pct": leg["weight_pct"],
                       "currency": listing_currency(leg["symbol"]), "kind": "etf_proxy", "source": "yahoo",
                       "weight_source": leg.get("weight_source", "")} for leg in legs]
        notes = ["Composito pesato di due gambe scelte dalla ricerca; pesi " + legs[0].get("weight_source", "") + "."]
    else:
        code = choice.symbol
        series = source.history(code)
        if not series:
            return None
        label = choice.name or (store.override(ticker) or {}).get("benchmark_label") or code
        currency = listing_currency(code)
        kind = "index" if choice.quote_type == "INDEX" else "etf_proxy"
        provider, return_type = "yahoo", ("INDEX_LEVEL" if kind == "index" else "ETF_ADJ_CLOSE")
        components = [{"series_id": code, "label": label, "weight_pct": 100.0, "currency": currency,
                       "kind": kind, "source": provider}]
        notes = ["ETF proxy, NON indice: costi, tracking error e distribuzioni possono alterare la performance."
                 if kind == "etf_proxy" else "Indice di mercato."]
    store.register_series(code, label, provider, currency, return_type, family)
    store.upsert(code, series, source="discovery", replace_existing=True)
    source_label = "Scoperta dal web (Yahoo Finance)" if decision.grade != "MANUALE" else "Scelta manuale dell'utente"
    meta = _metadata(ticker, code, label, decision.grade, kind, source_label, family, series, currency,
                     components, decision, notes)
    store.save_assignment(ticker, meta)
    return meta


def persist_manual(store, ticker: str, symbol: str, label: str, source: CandidateSource) -> bool:
    """Fissa a mano il benchmark di uno strumento: scarica e registra la serie, poi salva la scelta."""
    series = source.history(symbol)
    if not series:
        return False
    currency = listing_currency(symbol)
    store.register_series(symbol, label or symbol, "yahoo", currency, "ETF_ADJ_CLOSE", "MANUAL")
    store.upsert(symbol, series, source="discovery", replace_existing=True)
    store.save_override(ticker, symbol, label or symbol)
    return True


def run_for_instrument(data: dict, ticker: str, *, store, source: CandidateSource,
                       manual: str | None = None) -> Decision | None:
    strumento = next((s for s in data.get("strumenti", []) if isinstance(s, dict) and s.get("ticker") == ticker), None)
    if strumento is None:
        return None
    profile = build_profile(strumento, (data.get("instrument_master") or {}).get(ticker))
    chosen_manual = manual or (store.override(ticker) or {}).get("benchmark_code")
    decision = resolve(profile, own_history(data, ticker), source, manual=chosen_manual)
    if decision.status == "SCELTO":
        if chosen_manual and not store.read(chosen_manual):
            persist_manual(store, ticker, chosen_manual, "", source)
        persist(store, ticker, profile, decision, source)
    return decision
