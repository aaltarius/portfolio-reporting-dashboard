from __future__ import annotations

from persistence.storage import _build_instrument_master


def test_build_instrument_master_does_not_freeze_benchmark():
    strumenti = [{"ticker": "SWDA.MI", "tipo": "ETF Az. Globale", "nome": "iShares Core MSCI World"}]
    master = _build_instrument_master(strumenti)
    # benchmark_code NON deve essere scritto/congelato in fase di build:
    # resolve_instrument_benchmark lo calcolera' sempre fresco a valle.
    assert master["SWDA.MI"]["benchmark_code"] is None
    assert master["SWDA.MI"]["benchmark_label"] is None
