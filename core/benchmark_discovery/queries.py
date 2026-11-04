"""Passo 2: frasi di ricerca brevi, dal piu' specifico al piu' generale.

Nessuna lista di strumenti: le frasi nascono dal profilo (indice dichiarato
pulito, tema, area, tipo, fascia di durata). Il livello 1 accorcia l'indice una
parola alla volta; i livelli 2-4 tolgono i qualificatori uno alla volta.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .profile import DiscoveryProfile
from .vocabulary import AREA_PHRASES, KIND_QUERIES

# suffissi di rendimento/valuta e parole di marca che non descrivono l'indice
_JARGON = {"NR", "TR", "GR", "NTR", "PR", "USD", "EUR", "GBP", "CHF", "JPY", "INDEX", "CUSTOM", "NET", "TOTAL",
           "RETURN", "DAILY", "SELECT"}

_NAME_JARGON = {"ETF", "UCITS", "A", "B", "C", "ACC", "DIST", "CLASS", "FUND", "FONDO", "UNITS", "1C", "1D", "DR", "ETC"}

# fasce di durata: convenzione di mercato (anni), non strumenti
_BANDS = ((0, 1, "0-1"), (1, 3, "1-3"), (3, 5, "3-5"), (5, 7, "5-7"), (7, 10, "7-10"), (10, 999, "10+"))


@dataclass(frozen=True)
class Query:
    level: int
    text: str


def clean_index_name(text: str) -> list[str]:
    t = re.sub(r"[®™()]", " ", str(text or ""))
    t = re.sub(r"\b\d+\s*[-/]\s*\d+\b", " ", t)  # intervalli numerici (15/30, 1-3)
    t = t.replace("/", " ").replace("&", " and ")
    tokens: list[str] = []
    for w in t.split():
        w = w.strip(",.").rstrip("+")
        if not w:
            continue
        # i numeri con decimali, segno o percentuale non descrivono l'indice; gli interi (es. dimensione) si'
        if w.upper() in _JARGON or (re.fullmatch(r"[+\-]?\d+([.,]\d+)?%?", w) and not re.fullmatch(r"\d+", w)):
            continue
        tokens.append(w)
    return tokens


def _band(years: float | None) -> str:
    if years is None or years <= 0:
        return ""
    for lo, hi, label in _BANDS:
        if lo < years <= hi or (lo == 0 and years <= 1):
            return f"{label} year"
    return ""


def _short(words: list[str], limit: int = 4) -> str:
    return " ".join(" ".join(words).split()[:limit])


def build_queries(p: DiscoveryProfile) -> list[Query]:
    out: list[Query] = []
    seen: set[str] = set()

    def add(level: int, text: str) -> None:
        text = " ".join(str(text).split())
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            out.append(Query(level, text))

    # Livello 1: indice dichiarato, pulito e accorciato una parola alla volta
    tokens = clean_index_name(p.index_declared)
    if len(tokens) == 1:
        add(1, tokens[0])
    for n in range(len(tokens), 1, -1):
        add(1, " ".join(tokens[:n]))

    area = AREA_PHRASES.get(p.area_terms[0], p.area_terms[0]) if p.area_terms else ""
    # Livello 2: tema (+ area); per le obbligazioni anche la fascia di durata
    if p.kind == "bond":
        band = _band(p.duration_years)
        bond_theme = next((t for t in p.theme_terms if t in ("government", "corporate", "aggregate", "inflation linked")), "")
        if band:
            add(2, " ".join(x for x in [area, bond_theme, "bond", band] if x))
    for theme in p.theme_terms[:2]:
        if area:
            add(2, _short([area, theme]))
        add(2, _short([theme]))

    # Livello 3: tipo (+ area, + tema obbligazionario, + fascia di durata)
    variants = KIND_QUERIES.get(p.kind, [])
    if variants:
        bond_theme = next((t for t in p.theme_terms if t in ("government", "corporate", "aggregate", "inflation linked")), "")
        band = _band(p.duration_years) if p.kind == "bond" else ""
        main = variants[0]
        parts = [area, bond_theme, main]
        # il livello 3 aggiunge sempre qualcosa al solo tipo (area, tema, durata); il tipo da solo e' il livello 4
        if band and (area or bond_theme):
            add(3, " ".join(x for x in parts + [band] if x))
        phrase = " ".join(x for x in parts if x)
        if phrase != main:
            add(3, phrase)
        if area:
            add(3, _short([area, main]))
            for v in variants[1:]:
                add(3, _short([area, v]))

    # Livello 4: solo il tipo (tutte le formulazioni generiche); se il tipo non e' noto, le prime parole del nome
    for v in variants:
        add(4, v)
    if not out:
        words = [w for w in clean_index_name(p.name) if w.upper() not in _NAME_JARGON]
        add(4, " ".join(words[:3]))
    return out
