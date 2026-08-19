from __future__ import annotations

import pandas as pd

from core.services.sator import SATOR_NATURE_VALUES, compute_watchlist_reminders


def _data(strumenti, instrument_master=None):
    return {"strumenti": strumenti, "instrument_master": instrument_master or {}}


def _state_df(rows):
    return pd.DataFrame(rows)


def _watchlist_override(role="satellite_tematico"):
    return {"manual_overrides": {"sator": {"state": "watchlist", "role": role, "user_edited": True}}}


class TestComputeWatchlistReminders:

    def test_uncovered_watchlist_nature_appears_in_its_bucket(self):
        data = _data(
            [
                {"ticker": "CRYP.MI", "nome": "Crypto ETP", "tipo": "ETC", "natura": "Criptovalute"},
            ],
            instrument_master={"CRYP.MI": _watchlist_override()},
        )
        state_df = _state_df([])
        reminders = compute_watchlist_reminders(data, state_df)
        assert reminders["Satellite"] == ["criptovalute"]
        assert reminders["Satellite"][0] in SATOR_NATURE_VALUES
        assert reminders["Core"] == []
        assert reminders["Difensivo"] == []

    def test_watchlist_nature_already_held_in_same_bucket_is_skipped(self):
        data = _data(
            [
                {"ticker": "XDBC.MI", "nome": "Xtrackers Commodities", "tipo": "ETC", "natura": "Materie prime"},
                {"ticker": "CMOD2.MI", "nome": "Altro Commodities ETC", "tipo": "ETC", "natura": "Materie prime"},
            ],
            instrument_master={"CMOD2.MI": _watchlist_override()},
        )
        state_df = _state_df([{"Ticker": "XDBC.MI", "Quote": 10.0, "Controvalore": 500.0}])
        reminders = compute_watchlist_reminders(data, state_df)
        assert reminders["Satellite"] == []

    def test_watchlist_suppressed_by_nature_code_even_when_free_text_natura_differs(self):
        """Bug latente risolto da questo task: prima, la copertura era
        confrontata sul testo libero item['natura']. Due strumenti con la
        STESSA classificazione SATOR reale ma testo libero storico diverso
        (mai riallineato manualmente) non si deduplicavano correttamente.
        Ora il confronto e' sul codice 'nature' inferito da
        infer_sator_metadata, quindi si deduplicano anche se il campo
        legacy 'natura' e' testualmente differente."""
        data = _data(
            [
                {"ticker": "XDBC.MI", "nome": "Xtrackers Commodities Basket", "tipo": "ETC", "natura": "Paniere diversificato di materie prime"},
                {"ticker": "ICOM.MI", "nome": "iShares Commodity Curve", "tipo": "ETC", "natura": "Esposizione a singola commodity"},
            ],
            instrument_master={"ICOM.MI": _watchlist_override()},
        )
        state_df = _state_df([{"Ticker": "XDBC.MI", "Quote": 10.0, "Controvalore": 500.0}])
        reminders = compute_watchlist_reminders(data, state_df)
        assert reminders["Satellite"] == []

    def test_two_watchlist_instruments_same_nature_bucket_produce_one_row(self):
        data = _data(
            [
                {"ticker": "CRYP1.MI", "nome": "Crypto ETP A", "tipo": "ETC", "natura": "Criptovalute"},
                {"ticker": "CRYP2.MI", "nome": "Crypto ETP B", "tipo": "ETC", "natura": "Criptovalute"},
            ],
            instrument_master={
                "CRYP1.MI": _watchlist_override(),
                "CRYP2.MI": _watchlist_override(),
            },
        )
        state_df = _state_df([])
        reminders = compute_watchlist_reminders(data, state_df)
        assert reminders["Satellite"] == ["criptovalute"]

    def test_legacy_candidato_state_is_treated_as_watchlist(self):
        """'candidato' non e' piu' un valore valido di SATOR_STATE_VALUES,
        ma un vecchio dato salvato con questo valore si comporta come
        'watchlist' (alias in lettura, vedi _resolve_sator_state)."""
        data = _data(
            [
                {"ticker": "CRYP.MI", "nome": "Crypto ETP", "tipo": "ETC", "natura": "Criptovalute"},
            ],
            instrument_master={
                "CRYP.MI": {"manual_overrides": {"sator": {"state": "candidato", "role": "satellite_tematico", "user_edited": True}}}
            },
        )
        state_df = _state_df([])
        reminders = compute_watchlist_reminders(data, state_df)
        assert reminders["Satellite"] == ["criptovalute"]

    def test_legacy_fuori_piano_state_does_not_produce_reminder(self):
        """'fuori_piano' e' alias di 'escluso' (non piu' 'watchlist'): un
        vecchio dato salvato con questo valore resta escluso dal
        promemoria, come un'esclusione esplicita."""
        data = _data(
            [
                {"ticker": "CRYP.MI", "nome": "Crypto ETP", "tipo": "ETC", "natura": "Criptovalute"},
            ],
            instrument_master={
                "CRYP.MI": {"manual_overrides": {"sator": {"state": "fuori_piano", "role": "satellite_tematico", "user_edited": True}}}
            },
        )
        state_df = _state_df([])
        reminders = compute_watchlist_reminders(data, state_df)
        assert reminders["Satellite"] == []

    def test_no_watchlist_instruments_returns_empty_lists_for_all_buckets(self):
        data = _data([{"ticker": "SWDA.MI", "nome": "iShares Core MSCI World", "tipo": "ETF", "natura": "Azionario globale core"}])
        state_df = _state_df([{"Ticker": "SWDA.MI", "Quote": 10.0, "Controvalore": 1000.0}])
        reminders = compute_watchlist_reminders(data, state_df)
        assert reminders == {"Core": [], "Difensivo": [], "Satellite": []}

    def test_excluded_held_ticker_no_longer_covers_its_natura_for_reminders(self):
        """Punto di innesto per il toggle 'Escludi BTP/GOV': un ticker
        posseduto ma escluso non deve piu' 'coprire' la propria natura agli
        occhi del promemoria watchlist - stesso principio del test
        test_watchlist_nature_already_held_in_same_bucket_is_skipped, ma con
        lo strumento posseduto passato in exclude_tickers."""
        data = _data(
            [
                {"ticker": "XDBC.MI", "nome": "Xtrackers Commodities", "tipo": "ETC", "natura": "Materie prime"},
                {"ticker": "CMOD2.MI", "nome": "Altro Commodities ETC", "tipo": "ETC", "natura": "Materie prime"},
            ],
            instrument_master={"CMOD2.MI": _watchlist_override()},
        )
        state_df = _state_df([{"Ticker": "XDBC.MI", "Quote": 10.0, "Controvalore": 500.0}])
        reminders_without_exclusion = compute_watchlist_reminders(data, state_df)
        assert reminders_without_exclusion["Satellite"] == []
        reminders_with_exclusion = compute_watchlist_reminders(data, state_df, exclude_tickers=frozenset({"XDBC.MI"}))
        assert reminders_with_exclusion["Satellite"] == ["commodities"]

    def test_exclude_tickers_defaults_to_no_exclusion(self):
        data = _data([{"ticker": "SWDA.MI", "nome": "iShares Core MSCI World", "tipo": "ETF", "natura": "Azionario globale core"}])
        state_df = _state_df([{"Ticker": "SWDA.MI", "Quote": 10.0, "Controvalore": 1000.0}])
        assert compute_watchlist_reminders(data, state_df) == compute_watchlist_reminders(data, state_df, exclude_tickers=frozenset())

    def test_watchlist_nature_in_different_bucket_than_held_still_appears(self):
        data = _data(
            [
                {"ticker": "SWDA.MI", "nome": "iShares Core MSCI World", "tipo": "ETF", "natura": "Azionario globale core"},
                {"ticker": "CRYP.MI", "nome": "Crypto ETP", "tipo": "ETC", "natura": "Criptovalute"},
            ],
            instrument_master={"CRYP.MI": _watchlist_override()},
        )
        state_df = _state_df([{"Ticker": "SWDA.MI", "Quote": 10.0, "Controvalore": 1000.0}])
        reminders = compute_watchlist_reminders(data, state_df)
        assert reminders["Satellite"] == ["criptovalute"]
        assert reminders["Core"] == []
