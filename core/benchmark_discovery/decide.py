"""Passi 2-5: ricerca per livelli, misura, scelta e traccia completa.

`discover` e' pura rispetto al web: tutto cio' che riguarda la rete passa da
`CandidateSource`, sostituibile nei test con una fonte fittizia.
"""
from __future__ import annotations

import itertools
import re

import pandas as pd
from dataclasses import asdict, dataclass, field
from typing import Protocol

from .params import PARAMS
from .profile import DiscoveryProfile
from .queries import build_queries, clean_index_name
from .scoring import Fit, blend_series, coherence, fit as measure, grade, score, weekly_returns
from .vocabulary import listing_currency

ALLOWED_TYPES = ("ETF", "INDEX")


@dataclass(frozen=True)
class Candidate:
    symbol: str
    name: str
    quote_type: str


class CandidateSource(Protocol):
    def search(self, text: str) -> list[Candidate]: ...
    def history(self, symbol: str) -> dict[str, float]: ...
    def isin(self, symbol: str) -> str: ...


@dataclass
class Decision:
    status: str                       # SCELTO | IN_ATTESA
    choice: Candidate | None
    grade: str
    level: int
    score: float
    fit: Fit | None
    trace: dict = field(default_factory=dict)


Pool = list[tuple[dict, Candidate, Fit]]


def _is_fund_name(name: str) -> bool:
    """Yahoo etichetta come ETF anche fondi comuni illiquidi: i nomi che dicono 'Fund' e non 'ETF' passano dopo."""
    toks = set(re.findall(r"[a-z0-9]+", str(name or "").lower()))
    return "fund" in toks and not toks & {"etf", "etc", "ucits"}


def _entry(c: Candidate, level: int) -> dict:
    return {"symbol": c.symbol, "name": c.name, "type": c.quote_type, "level": level,
            "coherence": None, "corr": None, "te_pct": None, "n": 0, "score": None, "valid": False, "reason": ""}


def _query_words_for(p: DiscoveryProfile, query_text: str, level: int) -> list[str] | None:
    """Le parole della frase di livello 1 garantiscono la coerenza solo se coprono tutto l'indice
    dichiarato oppure sono almeno 3: una frase accorciata a 2 parole e' troppo generica."""
    if level != 1:
        return None
    words = query_text.split()
    full = len(clean_index_name(p.index_declared))
    return words if (len(words) == full or len(words) >= 3) else None


def _collect(p: DiscoveryProfile, own_history: dict[str, float], source: CandidateSource) -> tuple[Pool, dict]:
    """Cerca per livelli, valuta e restituisce i candidati validi con la traccia."""
    trace: dict = {"profile": asdict(p), "levels": []}
    queries = build_queries(p)
    own_ok = len(weekly_returns(own_history)) >= PARAMS["min_obs"]
    seen: set[str] = set()
    pool: Pool = []

    for level in (1, 2, 3, 4):
        phrases = [q for q in queries if q.level == level]
        if not phrases:
            continue
        lv: dict = {"level": level, "queries": [], "evaluated": []}
        found: list[tuple[Candidate, str]] = []
        for q in phrases:
            res = [c for c in source.search(q.text) if c.quote_type in ALLOWED_TYPES]
            lv["queries"].append({"text": q.text, "found": len(res)})
            for c in res:
                if c.symbol not in seen:
                    seen.add(c.symbol)
                    found.append((c, q.text))

        # 1) coerenza dei metadati su TUTTI i candidati trovati (nessuna rete)
        coherent: list[tuple[float, int, Candidate, dict]] = []
        qtext_of: dict[str, str] = {}
        for i, (c, qtext) in enumerate(found):
            qtext_of[c.symbol] = qtext
            e = _entry(c, level)
            lv["evaluated"].append(e)
            if c.symbol.upper() == p.ticker.upper():
                e["reason"] = "stesso simbolo dello strumento"
                continue
            name_for_coherence = c.name
            long_name = getattr(source, "long_name", None)
            if callable(long_name) and len(c.name.strip()) >= PARAMS["truncated_name_len"]:
                # i nomi brevi dei fornitori sono troncati (qui sparisce spesso proprio la parola del tipo)
                name_for_coherence = long_name(c.symbol) or c.name
            coh = coherence(p, name_for_coherence, c.quote_type, query_words=_query_words_for(p, qtext, level))
            e["coherence"] = round(coh, 3)
            if coh < PARAMS["min_coherence"]:
                e["reason"] = "coerenza dei metadati sotto soglia"
                continue
            coherent.append((coh, i, c, e))

        # 2) misura solo i piu' coerenti (storico dalla rete)
        coherent.sort(key=lambda t: (_is_fund_name(t[2].name), -t[0], t[1]))
        attempts = valid_here = 0
        for coh, _, c, e in coherent:
            if valid_here >= PARAMS["max_eval_per_level"] or attempts >= PARAMS["max_eval_per_level"] * PARAMS["attempt_factor"]:
                break
            attempts += 1
            hist = source.history(c.symbol)
            hist_len = len(weekly_returns(hist))
            f = measure(own_history, hist) if own_ok else Fit(None, None, 0)
            e.update(corr=None if f.corr is None else round(f.corr, 4),
                     te_pct=None if f.te_pct is None else round(f.te_pct, 2), n=f.n)
            if own_ok and f.corr is None:
                e["reason"] = "storico in comune insufficiente"
                continue
            if own_ok and f.corr < PARAMS["min_corr"]:
                e["reason"] = "correlazione troppo bassa"
                continue
            if not own_ok and hist_len < PARAMS["min_obs"]:
                e["reason"] = "storico del candidato insufficiente"
                continue
            long_name = getattr(source, "long_name", None)
            if callable(long_name):
                full = long_name(c.symbol) or c.name
                coh = coherence(p, full, c.quote_type, query_words=_query_words_for(p, qtext_of[c.symbol], level))
                e["coherence"] = round(coh, 3)
                if coh < PARAMS["min_coherence"]:
                    e["reason"] = "coerenza (nome completo) sotto soglia"
                    continue
            penalty = PARAMS["w_ccy"] if listing_currency(c.symbol) != PARAMS["target_currency"] else 0.0
            # senza strumento proprio non c'e' misura: un indice e' il riferimento stesso, un ETF ne e' solo un proxy
            index_bonus = PARAMS["index_preference"] if (not own_ok and c.quote_type == "INDEX") else 0.0
            e["score"] = round(score(f, coh, hist_len) - penalty + index_bonus, 4)
            e["valid"] = True
            valid_here += 1
            pool.append((e, c, f))
        trace["levels"].append(lv)
        best = max((f.corr for _, _, f in pool if f.corr is not None), default=None)
        if len(pool) >= PARAMS["min_valid"] and (best is None or best >= PARAMS["good_corr"]):
            break
    return pool, trace


def _name_similarity(a: str, b: str) -> float:
    ta, tb = set(re.findall(r"[a-z0-9]+", a.lower())), set(re.findall(r"[a-z0-9]+", b.lower()))
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def _prefer_target_listing(p: DiscoveryProfile, own_history: dict[str, float], source: CandidateSource,
                           chosen: tuple[dict, Candidate, Fit]) -> tuple[tuple[dict, Candidate, Fit], str | None]:
    """Se il candidato e' quotato in un'altra valuta, cerca la stessa quotazione nella valuta del portafoglio
    (stesso ISIN) e la usa se non peggiora la misura oltre la tolleranza: elimina il rumore di cambio."""
    e, c, f = chosen
    target = PARAMS["target_currency"]
    if listing_currency(c.symbol) == target:
        return chosen, None
    iso = (source.isin(c.symbol) or "").strip()
    own_ok = len(weekly_returns(own_history)) >= PARAMS["min_obs"]
    # stessa quotazione in valuta del portafoglio: per ISIN se disponibile, altrimenti per nome quasi identico
    options: list[tuple[Candidate, bool]] = []
    if iso:
        options += [(a, False) for a in source.search(iso)]
    if c.name:
        options += [(a, True) for a in source.search(c.name)]
    best = None
    seen_alt: set[str] = set()
    for alt, by_name in options:
        if alt.symbol in seen_alt:
            continue
        seen_alt.add(alt.symbol)
        if alt.quote_type not in ALLOWED_TYPES or alt.symbol == c.symbol or listing_currency(alt.symbol) != target:
            continue
        if by_name and _name_similarity(c.name, alt.name) < PARAMS["same_product_name_similarity"]:
            continue
        hist = source.history(alt.symbol)
        hist_len = len(weekly_returns(hist))
        fa = measure(own_history, hist) if own_ok else Fit(None, None, 0)
        if own_ok:
            if fa.corr is None or (f.corr is not None and fa.corr < f.corr - PARAMS["listing_tolerance"]):
                continue
        elif hist_len < PARAMS["min_obs"]:
            continue
        if best is None or (fa.corr or 0) > (best[1].corr or 0):
            best = (alt, fa, hist_len)
    if best is None:
        return chosen, None
    alt, fa, hist_len = best
    e2 = _entry(alt, e["level"])
    e2.update(coherence=e["coherence"], corr=None if fa.corr is None else round(fa.corr, 4),
              te_pct=None if fa.te_pct is None else round(fa.te_pct, 2), n=fa.n,
              score=round(score(fa, e["coherence"], hist_len), 4), valid=True, reason="quotazione nella valuta del portafoglio",
              listing_replaced=c.symbol)
    return (e2, alt, fa), c.symbol


def discover(p: DiscoveryProfile, own_history: dict[str, float], source: CandidateSource,
             manual: str | None = None) -> Decision:
    if manual:
        trace = {"profile": asdict(p), "levels": [], "manual": True,
                 "choice": {"symbol": manual, "reason": "scelta manuale dell'utente"}}
        return Decision("SCELTO", Candidate(manual, "", "MANUAL"), "MANUALE", 0, 1.0, None, trace)

    pool, trace = _collect(p, own_history, source)
    if not pool:
        trace["choice"] = None
        return Decision("IN_ATTESA", None, "", 0, 0.0, None, trace)

    ranked = sorted(pool, key=lambda t: (-t[0]["score"], t[0]["symbol"]))
    # la quotazione in valuta del portafoglio si cerca per i primi candidati, non solo per il primo:
    # un prodotto della natura giusta quotato in altra valuta altrimenti perde contro uno regionale in euro
    k = PARAMS["listing_top_k"]
    refined = [_prefer_target_listing(p, own_history, source, t)[0] for t in ranked[:k]] + ranked[k:]
    ranked = sorted(refined, key=lambda t: (-t[0]["score"], t[0]["symbol"]))
    chosen = None
    for e, c, f in ranked[:3]:
        iso = (source.isin(c.symbol) or "").upper()
        if iso and p.isin and iso == p.isin.upper():
            e["valid"] = False
            e["reason"] = "stesso ISIN dello strumento"
            continue
        chosen = (e, c, f)
        break
    if chosen is None:
        chosen = ranked[min(3, len(ranked) - 1)]
    e, c, f = chosen
    g = grade(e["level"], c.quote_type, f.corr is not None)
    trace["choice"] = {"symbol": c.symbol, "name": c.name, "level": e["level"], "grade": g, "score": e["score"]}
    if e.get("listing_replaced"):
        trace["choice"]["listing_replaced"] = e["listing_replaced"]
    return Decision("SCELTO", c, g, e["level"], e["score"], f, trace)


def _leg_profile(p: DiscoveryProfile, kind: str) -> DiscoveryProfile:
    words = set(p.descriptor.lower().replace(",", " ").split())
    if kind == "equity":
        area = [a for a in p.area_terms if a != "euro"]
    else:
        area = ["euro"] if "eur" in words else []
    return DiscoveryProfile(ticker=p.ticker + "#" + kind, isin="", name=p.name, country=p.country, kind=kind,
                            area_terms=area, currency=p.currency, descriptor=p.descriptor)


def _estimate_equity_weight(own: dict[str, float], eq_hist: dict[str, float], bd_hist: dict[str, float]) -> float | None:
    """Peso azionario (in %) che minimizza lo scostamento tra il fondo e il composito delle due gambe
    (rendimenti settimanali, pesi da 0 a 100 a passi del 5%). None se la finestra comune e' troppo corta."""
    ro, re_, rb = weekly_returns(own), weekly_returns(eq_hist), weekly_returns(bd_hist)
    if ro.empty or re_.empty or rb.empty:
        return None
    j = pd.concat([ro, re_, rb], axis=1, join="inner").dropna().tail(PARAMS["window_weeks"])
    if len(j) < PARAMS["min_obs"]:
        return None
    best_w, best_te = None, None
    for w in range(0, 101, 5):
        te = float((j.iloc[:, 0] - (w / 100.0 * j.iloc[:, 1] + (1 - w / 100.0) * j.iloc[:, 2])).std())
        if best_te is None or te < best_te:
            best_w, best_te = float(w), te
    return best_w


def discover_composite(p: DiscoveryProfile, own_history: dict[str, float], source: CandidateSource) -> Decision | None:
    """Fondo multi-asset: composito pesato di due gambe (azioni e obbligazioni). Le gambe candidate vengono
    dallo stesso algoritmo; i pesi sono quelli dichiarati nell'arricchimento oppure, se mancano, stimati dallo
    storico del fondo; la coppia si sceglie misurando quale composito segue meglio il fondo."""
    declared = bool(p.equity_pct and p.bond_pct)
    own_ok = len(weekly_returns(own_history)) >= PARAMS["min_obs"]
    if not declared and not own_ok:
        return None
    k = PARAMS["composite_top_k"]
    sides = []
    for kind in ("equity", "bond"):
        pool, trace = _collect(_leg_profile(p, kind), {}, source)
        if not pool:
            return None
        top = sorted(pool, key=lambda t: (listing_currency(t[1].symbol) != PARAMS["target_currency"],
                                          -t[0]["score"], t[0]["symbol"]))[:k]
        sides.append((kind, [c for _, c, _ in top], trace))
    best = None
    for eq, bd in itertools.product(sides[0][1], sides[1][1]):
        h_eq, h_bd = source.history(eq.symbol), source.history(bd.symbol)
        w_eq = p.equity_pct if declared else _estimate_equity_weight(own_history, h_eq, h_bd)
        if w_eq is None:
            continue
        w_bd = p.bond_pct if declared else 100.0 - w_eq
        blend = blend_series([(h_eq, w_eq), (h_bd, w_bd)])
        if not blend:
            continue
        f = measure(own_history, blend) if own_ok else Fit(None, None, 0)
        off_target = sum(1 for leg in (eq, bd) if listing_currency(leg.symbol) != PARAMS["target_currency"])
        s = score(f, 1.0, len(blend)) - PARAMS["w_ccy"] * off_target
        if best is None or s > best[0]:  # a parita' vince la prima coppia (liste gia' ordinate: risultato deterministico)
            best = (s, eq, bd, f, w_eq, w_bd)
    if best is None:
        return None
    s, eq, bd, f, w_eq, w_bd = best
    source_w = "dichiarato" if declared else "stimato"
    label = f"{eq.symbol} {w_eq:g}% + {bd.symbol} {w_bd:g}%"
    legs = [{"kind": "equity", "symbol": eq.symbol, "name": eq.name, "weight_pct": w_eq, "weight_source": source_w},
            {"kind": "bond", "symbol": bd.symbol, "name": bd.name, "weight_pct": w_bd, "weight_source": source_w}]
    trace = {"profile": asdict(p), "legs": legs, "leg_traces": [t for _, _, t in sides],
             "candidates_per_leg": {kd: [c.symbol for c in cs] for kd, cs, _ in sides},
             "choice": {"symbol": "BLEND", "name": label, "grade": "COMPOSITO"}}
    return Decision("SCELTO", Candidate("BLEND", label, "COMPOSITE"), "COMPOSITO", 0, s, f, trace)


def resolve(p: DiscoveryProfile, own_history: dict[str, float], source: CandidateSource,
            manual: str | None = None) -> Decision:
    """Punto di ingresso: scelta manuale, composito per i fondi con composizione, altrimenti scoperta."""
    if not manual and (p.kind == "multi_asset" or (p.equity_pct and p.bond_pct)):
        composite = discover_composite(p, own_history, source)
        if composite is not None:
            return composite
    return discover(p, own_history, source, manual)
