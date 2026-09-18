"""
core/domain/tax.py — Stima imposta italiana sulla vendita di uno strumento.

Unica formula finanziaria nuova introdotta dal ribilanciamento v2 (vedi
docs/superpowers/specs/2026-09-19-ribilanciamento-v2-giudizio-esperto.md):
aliquote fisse per legge italiana, non un modello di calcolo - 12,5% sui
titoli di Stato, 26% standard sul resto, zero su una perdita (mai
un'imposta negativa)."""
from __future__ import annotations

_ALIQUOTA_TITOLI_DI_STATO = 0.125
_ALIQUOTA_STANDARD = 0.26


def stima_imposta_vendita(pl_eur: float, is_gov_bond: bool) -> float:
    """Imposta stimata su una vendita con P/L pl_eur. Zero se pl_eur <= 0
    (mai un'imposta su una perdita). Aliquota 12,5% per i titoli di Stato
    italiani, 26% per tutto il resto (ETF, azioni, fondi, ETC)."""
    if pl_eur <= 0:
        return 0.0
    aliquota = _ALIQUOTA_TITOLI_DI_STATO if is_gov_bond else _ALIQUOTA_STANDARD
    return pl_eur * aliquota
