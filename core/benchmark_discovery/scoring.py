"""Passi 3-4: misura di somiglianza e punteggio di un candidato.

Una sola formula, parametri in `params.py`. Le funzioni sono pure.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .params import PARAMS
from .profile import DiscoveryProfile
from .vocabulary import (ABBREVIATIONS, AREA_EQUIVALENTS, KIND_NAME_WORDS, REGION_WORDS, STRATEGY_PAIRS,
                         STRATEGY_WORDS, WEAK_AREAS)

_GRADES = ["PROPRIA", "SORELLA", "CUGINA", "ZIA", "NONNA"]


@dataclass
class Fit:
    corr: float | None
    te_pct: float | None
    n: int
    own_vol_pct: float | None = None   # volatilita' annua dello strumento sulla finestra di misura


def weekly_returns(series: dict[str, float]) -> pd.Series:
    """Rendimenti settimanali (ultimo prezzo del venerdi'); valori nulli, negativi o non numerici ignorati."""
    clean: dict[pd.Timestamp, float] = {}
    for d, v in (series or {}).items():
        try:
            x = float(v)
            ts = pd.Timestamp(str(d)[:10])
        except (TypeError, ValueError):
            continue
        if math.isfinite(x) and x > 0:
            clean[ts] = x
    if len(clean) < 2:
        return pd.Series(dtype=float)
    s = pd.Series(clean).sort_index()
    weekly = s.resample("W-FRI").last().dropna()
    return weekly.pct_change().dropna()


def fit(own: dict[str, float], cand: dict[str, float]) -> Fit:
    a, b = weekly_returns(own), weekly_returns(cand)
    if a.empty or b.empty:
        return Fit(None, None, 0)
    j = pd.concat([a, b], axis=1, join="inner").dropna().tail(PARAMS["window_weeks"])
    n = len(j)
    if n < PARAMS["min_obs"]:
        return Fit(None, None, n)
    corr = j.iloc[:, 0].corr(j.iloc[:, 1])
    if corr is None or not math.isfinite(corr):
        return Fit(None, None, n)
    te = float((j.iloc[:, 0] - j.iloc[:, 1]).std() * np.sqrt(52) * 100)
    vol = float(j.iloc[:, 0].std() * np.sqrt(52) * 100)
    return Fit(float(corr), te, n, vol)


def _tokens(name: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", str(name or "").lower())
    out = []
    for t in toks:
        out.append(t)
        if t in ABBREVIATIONS:
            out.extend(ABBREVIATIONS[t].split())
    return out


def _hit(word: str, toks: list[str]) -> bool:
    """Una parola e' presente se un termine del nome la riproduce (prefisso di 5 lettere; sotto le 4 lettere, identita')."""
    if len(word) <= 3:
        return word in toks
    return any(t.startswith(word[:5]) for t in toks)


def _hedge_factor(p: DiscoveryProfile, name: str) -> float:
    """0,5 se il nome dichiara esplicitamente una copertura del cambio opposta a quella dello strumento."""
    if p.hedged is None:
        return 1.0
    low = str(name or "").lower()
    unhedged = bool(re.search(r"unhedg|unhdg|non hedged", low))
    hedged = bool(re.search(r"(?<!un)hedged|\bhdg\b|\(h\)", low)) and not unhedged
    if (p.hedged and unhedged) or (not p.hedged and hedged):
        return 0.5
    return 1.0


def _region_markers(name: str) -> set[str]:
    low = str(name or "").lower()
    found = {t for t in re.findall(r"[a-z]+", low) if t in REGION_WORDS}
    if re.search(r"(?<![a-z])u\.s\.?(?![a-z])|united states", low):
        found.add("us")
    return found


def _is_strategy_product(name: str, own_text: str) -> bool:
    """Prodotto a leva, inverso o con opzioni sopra, a meno che lo strumento stesso lo sia."""
    toks = set(re.findall(r"[a-z0-9]+", str(name or "").lower()))
    own = set(re.findall(r"[a-z0-9]+", str(own_text or "").lower()))
    if (toks & STRATEGY_WORDS) - own:
        return True
    return any(a in toks and b in toks and not (a in own and b in own) for a, b in STRATEGY_PAIRS)


def coherence(p: DiscoveryProfile, candidate_name: str, quote_type: str,
              query_words: list[str] | None = None) -> float:
    """Coerenza dei metadati tra profilo e candidato, da 0 a 1.

    Regole: un candidato di tipo diverso vale 0; almeno un termine di tema deve comparire (altrimenti il
    risultato e' dimezzato); le aree generiche (globale, mondo) non sono richieste; se il candidato
    contiene tutte le parole della frase che l'ha trovato (livello 1, l'indice dichiarato) vale 1;
    una copertura del cambio dichiarata nel nome e opposta a quella dello strumento dimezza il risultato.
    """
    toks = _tokens(candidate_name)
    if p.kind == "equity" and any(t in ("bond", "bd", "bnd", "govt", "gov", "obbl") for t in toks):
        return 0.0
    kind_words = KIND_NAME_WORDS.get(p.kind)
    if kind_words and not any(_hit(w, toks) for w in kind_words):
        return 0.0
    if _is_strategy_product(candidate_name, p.descriptor + " " + p.name):
        return 0.0
    hedge = _hedge_factor(p, candidate_name)
    if p.area_terms and all(a in WEAK_AREAS for a in p.area_terms):
        # strumento globale: un nome che dichiara una regione precisa e' un parente peggiore
        if _region_markers(candidate_name):
            hedge *= 0.5
    if query_words and all(_hit(w.lower(), toks) for w in query_words):
        return 1.0 * hedge
    themes = list(p.theme_terms)
    areas = [a for a in p.area_terms if a not in WEAK_AREAS]
    required = themes + areas
    if not required:
        return 0.5 * hedge

    def present(term: str) -> bool:
        options = AREA_EQUIVALENTS.get(term, [term])
        return any(all(_hit(w, toks) for w in o.split()) for o in options)

    hits = sum(1 for term in required if present(term))
    coh = hits / len(required)
    if themes and not any(present(t) for t in themes):
        coh *= 0.5
    return coh * hedge


def blend_series(legs: list[tuple[dict[str, float], float]]) -> dict[str, float]:
    """Indice settimanale di un composito: rendimenti delle gambe pesati (pesi in percentuale)."""
    rets = [(weekly_returns(h), w / 100.0) for h, w in legs]
    if not rets or any(r.empty for r, _ in rets):
        return {}
    joined = pd.concat([r for r, _ in rets], axis=1, join="inner").dropna()
    if joined.empty:
        return {}
    r = sum(joined.iloc[:, i] * w for i, (_, w) in enumerate(rets))
    idx = 100.0 * (1.0 + r).cumprod()
    return {d.strftime("%Y-%m-%d"): float(v) for d, v in idx.items()}


def score(f: Fit, coh: float, history_len: int) -> float:
    hist = min(history_len / PARAMS["hist_ref_weeks"], 1.0)
    if f.corr is None:
        meta = (PARAMS["w_meta"] * coh + PARAMS["w_hist"] * hist) / (PARAMS["w_meta"] + PARAMS["w_hist"])
        return PARAMS["metadata_only_scale"] * meta
    if f.own_vol_pct is not None and f.own_vol_pct < PARAMS["low_vol_pct"]:
        # strumento quasi privo di oscillazioni: la correlazione e' rumore, conta lo scostamento rispetto alla sua volatilita'
        te_part = 1.0 - min((f.te_pct or 0.0) / max(f.own_vol_pct, 0.1), 1.0)
        return ((PARAMS["w_corr"] + PARAMS["w_te"]) * te_part
                + PARAMS["w_meta"] * coh + PARAMS["w_hist"] * hist)
    te_part = 1.0 - min((f.te_pct or 0.0) / PARAMS["te_ref_pct"], 1.0)
    return (PARAMS["w_corr"] * max(f.corr, 0.0) + PARAMS["w_te"] * te_part
            + PARAMS["w_meta"] * coh + PARAMS["w_hist"] * hist)


def grade(level: int, quote_type: str, has_fit: bool) -> str:
    base = {1: 0 if str(quote_type).upper() == "INDEX" else 1, 2: 2, 3: 3, 4: 4}.get(level, 4)
    if not has_fit:
        base += 1
    return _GRADES[min(base, len(_GRADES) - 1)]
