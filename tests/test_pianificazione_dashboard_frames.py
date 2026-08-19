from __future__ import annotations

import pandas as pd
import pytest

from core.services.sator import SATOR_NATURE_VALUES, build_portfolio_rings_frame


def _data(strumenti=None, instrument_master=None):
    return {
        "strumenti": strumenti or [],
        "instrument_master": instrument_master or {},
    }


def _state_df(rows):
    return pd.DataFrame(rows)


class TestBuildPortfolioRingsFrame:

    def test_empty_state_returns_empty_frame_with_columns(self):
        df = build_portfolio_rings_frame(_data(), _state_df([]))
        assert list(df.columns) == ["ticker", "name", "bucket", "natura", "nature", "value"]
        assert df.empty

    def test_held_instrument_included_with_bucket_and_natura(self):
        data = _data(strumenti=[
            {"ticker": "SWDA.MI", "nome": "iShares Core MSCI World", "tipo": "ETF", "natura": "Azionario globale core"},
        ])
        state_df = _state_df([{"Ticker": "SWDA.MI", "Quote": 10.0, "Controvalore": 600.0}])
        df = build_portfolio_rings_frame(data, state_df)
        assert len(df) == 1
        row = df.iloc[0]
        assert row["ticker"] == "SWDA.MI"
        assert row["bucket"] == "Core"
        assert row["natura"] == "Azionario globale core"
        assert row["value"] == pytest.approx(600.0)

    def test_held_instrument_nature_column_holds_sator_code_not_free_text(self):
        """'natura' resta il testo libero legacy (compatibilita'); 'nature' e'
        il nuovo codice tassonomia SATOR inferito da infer_sator_metadata,
        usato da Task 5 per pilotare get_nature_visual(). Per SWDA.MI
        (nome contiene 'World') infer_sator_metadata classifica sempre
        nature='azionario_globale_core', indipendentemente dal testo libero
        salvato in item['natura']."""
        data = _data(strumenti=[
            {"ticker": "SWDA.MI", "nome": "iShares Core MSCI World", "tipo": "ETF", "natura": "Testo libero legacy qualsiasi"},
        ])
        state_df = _state_df([{"Ticker": "SWDA.MI", "Quote": 10.0, "Controvalore": 600.0}])
        df = build_portfolio_rings_frame(data, state_df)
        row = df.iloc[0]
        assert row["natura"] == "Testo libero legacy qualsiasi"
        assert row["nature"] == "azionario_globale_core"
        assert row["nature"] in SATOR_NATURE_VALUES

    def test_missing_natura_falls_back_to_esposizione_diversificata(self):
        data = _data(strumenti=[{"ticker": "XEON.MI", "nome": "Xtrackers Overnight", "tipo": "ETF"}])
        state_df = _state_df([{"Ticker": "XEON.MI", "Quote": 5.0, "Controvalore": 250.0}])
        df = build_portfolio_rings_frame(data, state_df)
        assert df.iloc[0]["natura"] == "Esposizione diversificata"

    def test_instrument_not_held_is_excluded(self):
        data = _data(strumenti=[
            {"ticker": "SWDA.MI", "nome": "iShares Core MSCI World", "tipo": "ETF", "natura": "Azionario globale core"},
            {"ticker": "VWCE.MI", "nome": "Vanguard All-World", "tipo": "ETF", "natura": "Azionario globale core"},
        ])
        state_df = _state_df([
            {"Ticker": "SWDA.MI", "Quote": 10.0, "Controvalore": 600.0},
            {"Ticker": "VWCE.MI", "Quote": 0.0, "Controvalore": 0.0},
        ])
        df = build_portfolio_rings_frame(data, state_df)
        assert list(df["ticker"]) == ["SWDA.MI"]

    def test_excluded_ticker_is_dropped_even_if_held(self):
        """Punto di innesto per il toggle 'Escludi BTP/GOV' esteso a tutta la
        pagina Pianificazione: la mappa di allocazione (donut + tabella) deve
        poter escludere un ticker posseduto, stesso principio gia' usato per
        il deficit di bucket (_compute_bucket_weights, exclude_tickers)."""
        data = _data(strumenti=[
            {"ticker": "SWDA.MI", "nome": "iShares Core MSCI World", "tipo": "ETF", "natura": "Azionario globale core"},
            {"ticker": "BTP-TEST", "nome": "BTP Test 2030", "tipo": "Titolo di Stato", "natura": "Titoli di Stato"},
        ])
        state_df = _state_df([
            {"Ticker": "SWDA.MI", "Quote": 10.0, "Controvalore": 600.0},
            {"Ticker": "BTP-TEST", "Quote": 1.0, "Controvalore": 1000.0},
        ])
        df = build_portfolio_rings_frame(data, state_df, exclude_tickers=frozenset({"BTP-TEST"}))
        assert list(df["ticker"]) == ["SWDA.MI"]

    def test_exclude_tickers_defaults_to_no_exclusion(self):
        data = _data(strumenti=[
            {"ticker": "SWDA.MI", "nome": "iShares Core MSCI World", "tipo": "ETF", "natura": "Azionario globale core"},
        ])
        state_df = _state_df([{"Ticker": "SWDA.MI", "Quote": 10.0, "Controvalore": 600.0}])
        df_default = build_portfolio_rings_frame(data, state_df)
        df_explicit_empty = build_portfolio_rings_frame(data, state_df, exclude_tickers=frozenset())
        pd.testing.assert_frame_equal(df_default, df_explicit_empty)

    def test_two_buckets_two_rows(self):
        data = _data(strumenti=[
            {"ticker": "SWDA.MI", "nome": "iShares Core MSCI World", "tipo": "ETF", "natura": "Azionario globale core"},
            {"ticker": "XEON.MI", "nome": "Xtrackers Overnight", "tipo": "ETF", "natura": "Liquidità"},
        ])
        state_df = _state_df([
            {"Ticker": "SWDA.MI", "Quote": 10.0, "Controvalore": 600.0},
            {"Ticker": "XEON.MI", "Quote": 5.0, "Controvalore": 250.0},
        ])
        df = build_portfolio_rings_frame(data, state_df)
        assert set(df["bucket"]) == {"Core", "Difensivo"}


from core.services.sator import latest_sator_decision


class TestLatestSatorDecision:

    def test_empty_list_returns_none(self):
        assert latest_sator_decision([]) is None

    def test_returns_item_with_max_created_at(self):
        items = [
            {"decision_id": "a", "created_at": "2026-06-01T10:00:00"},
            {"decision_id": "b", "created_at": "2026-07-01T10:00:00"},
        ]
        result = latest_sator_decision(items)
        assert result["decision_id"] == "b"
