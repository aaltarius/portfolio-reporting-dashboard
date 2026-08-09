"""core/services/sator_explain.py — Spiegazione standalone del voto SATOR
(Progetto D, ROADMAP_AI_FINANZA_LIBRO.md): per ogni strumento della
classifica, quanto contribuisce ciascuno dei 5 fattori al voto finale.

Nessun nuovo calcolo di punteggio: riusa i pesi e le etichette gia'
definiti in core/services/sator.py (PESI_DIMENSIONI, NOME_FATTORE) e i
punteggi fattore gia' calcolati da run_sator_analysis. Diversa dalla
spiegazione "competitiva" gia' esistente in sator.py (selection_reason,
_build_comparative_reasons): quella spiega perche' uno strumento batte o
perde contro un rivale nella sua funzione; questa spiega il profilo dello
strumento preso da solo, a prescindere dai concorrenti.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core.services.sator import NOME_FATTORE, PESI_DIMENSIONI

_BALANCED_THRESHOLD = 0.03


@dataclass(frozen=True)
class FactorContribution:
    factor: str
    label: str
    raw_score: float
    weight: float
    contribution: float


@dataclass(frozen=True)
class InstrumentExplanation:
    ticker: str
    name: str
    voto: float
    contributions: list[FactorContribution]
    summary_text: str


def _build_summary_text(contributions: list[FactorContribution]) -> str:
    ranked = sorted(contributions, key=lambda c: c.contribution, reverse=True)
    top1, top2, bottom = ranked[0], ranked[1], ranked[-1]
    if top1.contribution - bottom.contribution < _BALANCED_THRESHOLD:
        return "Voto equilibrato: nessun fattore domina in modo netto."
    return (
        f"Punteggio trainato soprattutto da {top1.label} e {top2.label}; "
        f"il fattore che porta meno punti al voto è {bottom.label}."
    )


def build_sator_explanations(
    ranking: pd.DataFrame, weights: dict[str, float] | None = None
) -> list[InstrumentExplanation]:
    required_cols = {"ticker", "name", "voto", *PESI_DIMENSIONI.keys()}
    if ranking is None or ranking.empty or not required_cols.issubset(set(ranking.columns)):
        return []

    explanations: list[InstrumentExplanation] = []
    for _, row in ranking.iterrows():
        contributions = [
            FactorContribution(
                factor=factor,
                label=NOME_FATTORE[factor],
                raw_score=float(row[factor]),
                weight=(weights or {}).get(factor, PESI_DIMENSIONI[factor]),
                contribution=float(row[factor]) * (weights or {}).get(factor, PESI_DIMENSIONI[factor]),
            )
            for factor in PESI_DIMENSIONI.keys()
        ]
        explanations.append(InstrumentExplanation(
            ticker=str(row["ticker"]),
            name=str(row["name"]),
            voto=float(row["voto"]),
            contributions=contributions,
            summary_text=_build_summary_text(contributions),
        ))
    explanations.sort(key=lambda e: e.voto, reverse=True)
    return explanations
