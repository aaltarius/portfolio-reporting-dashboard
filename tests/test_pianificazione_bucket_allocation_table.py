from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from ui.pages.pianificazione import _build_bucket_allocation_table_html


def _rings_df():
    return pd.DataFrame([
        {"ticker": "SWDA.MI", "name": "iShares Core MSCI World", "bucket": "Core", "natura": "Azionario globale core", "nature": "azionario_globale_core", "value": 1000.0},
    ])


def _base_args(rings_df):
    bucket_totals = rings_df.groupby("bucket")["value"].sum()
    current_mix = {"Core": 1.0, "Difensivo": 0.0, "Satellite": 0.0}
    objective = {"core": 0.55, "difensivo": 0.25, "satellite": 0.20}
    objective_key = {"Core": "core", "Difensivo": "difensivo", "Satellite": "satellite"}
    return bucket_totals, current_mix, objective, objective_key, SimpleNamespace()


class TestBucketAllocationTableWatchlistReminders:

    def test_reminder_row_rendered_in_its_bucket(self):
        rings_df = _rings_df()
        bucket_totals, current_mix, objective, objective_key, theme = _base_args(rings_df)
        html = _build_bucket_allocation_table_html(
            rings_df, bucket_totals, current_mix, objective, objective_key, theme,
            watchlist_reminders={"Core": [], "Difensivo": [], "Satellite": ["criptovalute"]},
        )
        assert "bucket-alloc-watchlist-row" in html
        assert "Criptovalute" in html
        assert "In osservazione" in html

    def test_no_watchlist_reminders_argument_produces_no_extra_rows(self):
        rings_df = _rings_df()
        bucket_totals, current_mix, objective, objective_key, theme = _base_args(rings_df)
        html = _build_bucket_allocation_table_html(
            rings_df, bucket_totals, current_mix, objective, objective_key, theme,
        )
        assert "bucket-alloc-watchlist-row" not in html

    def test_empty_reminders_dict_produces_no_extra_rows(self):
        rings_df = _rings_df()
        bucket_totals, current_mix, objective, objective_key, theme = _base_args(rings_df)
        html = _build_bucket_allocation_table_html(
            rings_df, bucket_totals, current_mix, objective, objective_key, theme,
            watchlist_reminders={"Core": [], "Difensivo": [], "Satellite": []},
        )
        assert "bucket-alloc-watchlist-row" not in html

    def test_reminder_does_not_change_totale_value(self):
        rings_df = _rings_df()
        bucket_totals, current_mix, objective, objective_key, theme = _base_args(rings_df)
        html_without = _build_bucket_allocation_table_html(
            rings_df, bucket_totals, current_mix, objective, objective_key, theme,
        )
        html_with = _build_bucket_allocation_table_html(
            rings_df, bucket_totals, current_mix, objective, objective_key, theme,
            watchlist_reminders={"Core": [], "Difensivo": [], "Satellite": ["criptovalute"]},
        )
        assert "1.000,00" in html_without and "1.000,00" in html_with

    def test_reminder_renders_bucket_section_even_with_zero_holdings(self):
        # rings_df ha solo Core: il bucket Satellite non ha righe proprie.
        # Il promemoria deve comunque comparire (con l'header di bucket a 0 EUR),
        # non essere silenziosamente saltato dal filtro "sub.empty".
        rings_df = _rings_df()
        bucket_totals, current_mix, objective, objective_key, theme = _base_args(rings_df)
        html = _build_bucket_allocation_table_html(
            rings_df, bucket_totals, current_mix, objective, objective_key, theme,
            watchlist_reminders={"Core": [], "Difensivo": [], "Satellite": ["criptovalute"]},
        )
        assert "bucket-alloc-watchlist-row" in html
        assert "Criptovalute" in html
        satellite_pos = html.find(">Satellite<")
        reminder_pos = html.find("Criptovalute")
        assert satellite_pos != -1 and satellite_pos < reminder_pos


def _empty_quota_bucket_status() -> dict:
    return {
        "valid": True, "missing_tickers": [], "stale_tickers": [], "sum_target": 0.0,
        "current_weights": {}, "target_weights": {}, "deviations_pp": {},
    }


def _all_empty_quota_status() -> dict:
    return {b: _empty_quota_bucket_status() for b in ("Core", "Difensivo", "Satellite")}


class TestBucketAllocationTablePerTickerQuotaStatus:
    """Task 9 del piano: righe per ticker (non piu' raggruppate per natura)
    con quota di riferimento e quota di possesso quando quota_status e'
    passato, severita' basata sulla tolleranza per-strumento configurabile."""

    def test_shows_per_ticker_target_and_current_with_severity(self):
        rings_df = pd.DataFrame([
            {"ticker": "SWDA.MI", "name": "iShares Core MSCI World", "bucket": "Core", "natura": "Azionario globale core", "nature": "azionario_globale_core", "value": 3000.0},
            {"ticker": "XMME.MI", "name": "iShares MSCI EM", "bucket": "Core", "natura": "Azionario emergenti", "nature": "azionario_emergenti", "value": 1000.0},
        ])
        bucket_totals = pd.Series({"Core": 4000.0, "Difensivo": 0.0, "Satellite": 0.0})
        current_mix = {"Core": 1.0, "Difensivo": 0.0, "Satellite": 0.0}
        objective = {"core": 1.0, "difensivo": 0.0, "satellite": 0.0}
        objective_key = {"Core": "core", "Difensivo": "difensivo", "Satellite": "satellite"}
        quota_status = _all_empty_quota_status()
        quota_status["Core"] = {
            "valid": True, "missing_tickers": [], "stale_tickers": [], "sum_target": 1.0,
            "current_weights": {"SWDA.MI": 0.75, "XMME.MI": 0.25},
            "target_weights": {"SWDA.MI": 0.60, "XMME.MI": 0.40},
            "deviations_pp": {"SWDA.MI": 15.0, "XMME.MI": -15.0},
        }

        html = _build_bucket_allocation_table_html(
            rings_df, bucket_totals, current_mix, objective, objective_key, theme=SimpleNamespace(),
            quota_status=quota_status, instrument_tolerance_pp=5.0,
        )

        assert "SWDA.MI" in html
        assert "XMME.MI" in html
        assert "Attuale 75% &middot; Target 60%" in html
        assert "Attuale 25% &middot; Target 40%" in html
        # Scostamento di 15pp con tolleranza 5pp (tol*2=10) -> "bad" per entrambi.
        assert html.count('bucket-alloc-instrument-row bad') == 2

    def test_ticker_without_target_shows_only_current_and_ok_severity(self):
        rings_df = pd.DataFrame([
            {"ticker": "NEW.MI", "name": "Nuovo strumento", "bucket": "Core", "natura": "Altro", "nature": "altro", "value": 500.0},
        ])
        bucket_totals = pd.Series({"Core": 500.0, "Difensivo": 0.0, "Satellite": 0.0})
        current_mix = {"Core": 1.0, "Difensivo": 0.0, "Satellite": 0.0}
        objective = {"core": 1.0, "difensivo": 0.0, "satellite": 0.0}
        objective_key = {"Core": "core", "Difensivo": "difensivo", "Satellite": "satellite"}

        html = _build_bucket_allocation_table_html(
            rings_df, bucket_totals, current_mix, objective, objective_key, theme=SimpleNamespace(),
            quota_status=_all_empty_quota_status(), instrument_tolerance_pp=5.0,
        )

        assert '<span class="bucket-alloc-mini-caption">Attuale 100%</span>' in html
        assert "Target" not in html  # nessun ticker ha una quota assegnata in questo test
        assert 'bucket-alloc-instrument-row ok' in html

    def test_deviation_within_tolerance_is_ok_severity(self):
        rings_df = pd.DataFrame([
            {"ticker": "SWDA.MI", "name": "iShares Core MSCI World", "bucket": "Core", "natura": "Azionario globale core", "nature": "azionario_globale_core", "value": 1000.0},
        ])
        bucket_totals = pd.Series({"Core": 1000.0, "Difensivo": 0.0, "Satellite": 0.0})
        current_mix = {"Core": 1.0, "Difensivo": 0.0, "Satellite": 0.0}
        objective = {"core": 1.0, "difensivo": 0.0, "satellite": 0.0}
        objective_key = {"Core": "core", "Difensivo": "difensivo", "Satellite": "satellite"}
        quota_status = _all_empty_quota_status()
        quota_status["Core"] = {
            "valid": True, "missing_tickers": [], "stale_tickers": [], "sum_target": 1.0,
            "current_weights": {"SWDA.MI": 1.0},
            "target_weights": {"SWDA.MI": 1.0},
            "deviations_pp": {"SWDA.MI": 2.0},  # entro tolleranza 5pp
        }

        html = _build_bucket_allocation_table_html(
            rings_df, bucket_totals, current_mix, objective, objective_key, theme=SimpleNamespace(),
            quota_status=quota_status, instrument_tolerance_pp=5.0,
        )

        assert 'bucket-alloc-instrument-row ok' in html
        assert "bad" not in html and "warn" not in html

    def test_deviation_between_one_and_two_times_tolerance_is_warn_severity(self):
        rings_df = pd.DataFrame([
            {"ticker": "SWDA.MI", "name": "iShares Core MSCI World", "bucket": "Core", "natura": "Azionario globale core", "nature": "azionario_globale_core", "value": 1000.0},
        ])
        bucket_totals = pd.Series({"Core": 1000.0, "Difensivo": 0.0, "Satellite": 0.0})
        current_mix = {"Core": 1.0, "Difensivo": 0.0, "Satellite": 0.0}
        objective = {"core": 1.0, "difensivo": 0.0, "satellite": 0.0}
        objective_key = {"Core": "core", "Difensivo": "difensivo", "Satellite": "satellite"}
        quota_status = _all_empty_quota_status()
        quota_status["Core"] = {
            "valid": True, "missing_tickers": [], "stale_tickers": [], "sum_target": 1.0,
            "current_weights": {"SWDA.MI": 1.0},
            "target_weights": {"SWDA.MI": 1.0},
            "deviations_pp": {"SWDA.MI": 7.0},  # tra tol (5) e 2*tol (10)
        }

        html = _build_bucket_allocation_table_html(
            rings_df, bucket_totals, current_mix, objective, objective_key, theme=SimpleNamespace(),
            quota_status=quota_status, instrument_tolerance_pp=5.0,
        )

        assert 'bucket-alloc-instrument-row warn' in html

    def test_missing_quota_status_argument_defaults_to_no_target_shown(self):
        """Non-regressione: senza passare quota_status (default None), il
        comportamento resta quello di sempre - nessuna tacca target, nessuna
        severita' diversa da 'ok'."""
        rings_df = pd.DataFrame([
            {"ticker": "SWDA.MI", "name": "iShares Core MSCI World", "bucket": "Core", "natura": "Azionario globale core", "nature": "azionario_globale_core", "value": 1000.0},
        ])
        bucket_totals = pd.Series({"Core": 1000.0, "Difensivo": 0.0, "Satellite": 0.0})
        current_mix = {"Core": 1.0, "Difensivo": 0.0, "Satellite": 0.0}
        objective = {"core": 1.0, "difensivo": 0.0, "satellite": 0.0}
        objective_key = {"Core": "core", "Difensivo": "difensivo", "Satellite": "satellite"}

        html = _build_bucket_allocation_table_html(
            rings_df, bucket_totals, current_mix, objective, objective_key, theme=SimpleNamespace(),
        )

        assert '<span class="bucket-alloc-mini-caption">Attuale 100%</span>' in html
        assert 'bucket-alloc-instrument-row ok' in html


class TestBucketAllocationTableSplitInstrument:
    """Task 5 del piano appartenenza-frazionata-bucket: build_portfolio_rings_frame
    ora produce piu' righe (stesso ticker) per uno strumento con bucket_exposure
    diviso, una per bucket. Questo test verifica che _build_bucket_allocation_table_html
    non abbia alcuna struttura keyed-per-ticker che scarterebbe/sovrascriverebbe
    la seconda riga: il ticker diviso deve comparire in ENTRAMBE le sezioni di
    bucket, ciascuna col proprio importo frazionato."""

    def test_allocation_table_shows_split_instrument_in_both_buckets(self):
        rings_df = pd.DataFrame([
            {"ticker": "FAM-FLEX", "name": "FAM Series Flexible", "bucket": "Core", "natura": "Flessibile", "nature": "fondo_pac", "value": 600.0},
            {"ticker": "FAM-FLEX", "name": "FAM Series Flexible", "bucket": "Difensivo", "natura": "Flessibile", "nature": "fondo_pac", "value": 400.0},
        ])
        bucket_totals = rings_df.groupby("bucket")["value"].sum()
        current_mix = {"Core": 0.6, "Difensivo": 0.4, "Satellite": 0.0}
        objective = {"core": 0.55, "difensivo": 0.25, "satellite": 0.20}
        objective_key = {"Core": "core", "Difensivo": "difensivo", "Satellite": "satellite"}

        html = _build_bucket_allocation_table_html(
            rings_df, bucket_totals, current_mix, objective, objective_key, theme=SimpleNamespace(),
        )

        # Il ticker compare due volte (una riga-strumento per bucket), non una
        # sola: nessuna deduplica/overwrite per ticker.
        assert html.count("FAM-FLEX") == 2
        # Ogni riga mostra il proprio importo frazionato, non il totale pieno.
        assert "600,00" in html
        assert "400,00" in html
        # Entrambe le sezioni di bucket sono presenti con l'header del bucket.
        core_pos = html.find(">Core<")
        dif_pos = html.find(">Difensivo<")
        first_ticker_pos = html.find("FAM-FLEX")
        second_ticker_pos = html.find("FAM-FLEX", first_ticker_pos + 1)
        assert core_pos != -1 and dif_pos != -1
        assert core_pos < first_ticker_pos < dif_pos < second_ticker_pos
