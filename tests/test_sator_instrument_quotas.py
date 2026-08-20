"""Ricostruzione della rete di sicurezza per la feature "quote target per
strumento dentro ogni bucket" (core/services/sator.py). La feature e' gia'
mergiata in main e verificata corretta su dati reali; questi test sono
stati riscritti da zero contro il codice di produzione reale dopo la perdita
accidentale della suite originale (worktree rimosso a fine sessione,
tests/ e' gitignored). Vedi STATO_OPERATIVO_5.0_PRE.md e
docs/superpowers/specs/2026-08-18-quote-interne-bucket-design.md.
"""
from __future__ import annotations

import pandas as pd
import pytest

from core.services.sator import (
    SatorContext,
    _compute_instrument_quota_status,
    compute_instrument_quota_status,
    ensure_sator_settings,
    run_sator_analysis,
)


# --------------------------------------------------------------------------- #
# ensure_sator_settings: schema instrument_quotas / instrument_quota_tolerance_pp
# --------------------------------------------------------------------------- #

def test_ensure_sator_settings_default_instrument_quotas():
    cfg = ensure_sator_settings({})
    assert cfg["instrument_quotas"] == {"Core": {}, "Difensivo": {}, "Satellite": {}}
    assert cfg["instrument_quota_tolerance_pp"] == pytest.approx(0.05)


def test_ensure_sator_settings_normalizes_instrument_quotas():
    settings = {
        "sator": {
            "instrument_quotas": {
                "Core": {"swda.mi": 0.75, "xmme.mi": 0.25, "bad": "not-a-number", "over": 1.5},
                "Difensivo": "not-a-dict",
            },
            "instrument_quota_tolerance_pp": 0.9,
        }
    }
    cfg = ensure_sator_settings(settings)
    assert cfg["instrument_quotas"]["Core"] == {"SWDA.MI": 0.75, "XMME.MI": 0.25}
    assert cfg["instrument_quotas"]["Difensivo"] == {}
    assert cfg["instrument_quotas"]["Satellite"] == {}
    assert cfg["instrument_quota_tolerance_pp"] == pytest.approx(0.20)


def test_ensure_sator_settings_instrument_quota_tolerance_pp_clamped_at_zero():
    cfg = ensure_sator_settings({"sator": {"instrument_quota_tolerance_pp": -1.0}})
    assert cfg["instrument_quota_tolerance_pp"] == pytest.approx(0.0)


def test_ensure_sator_settings_negative_weight_rejected():
    cfg = ensure_sator_settings({"sator": {"instrument_quotas": {"Core": {"SWDA.MI": -0.1}}}})
    assert cfg["instrument_quotas"]["Core"] == {}


def test_ensure_sator_settings_weight_exactly_zero_and_one_allowed():
    cfg = ensure_sator_settings({"sator": {"instrument_quotas": {"Core": {"AAA": 0.0, "BBB": 1.0}}}})
    assert cfg["instrument_quotas"]["Core"] == {"AAA": 0.0, "BBB": 1.0}


# --------------------------------------------------------------------------- #
# _compute_instrument_quota_status: funzione pura
# --------------------------------------------------------------------------- #

def test_quota_status_valid_bucket():
    status = _compute_instrument_quota_status(
        instrument_buckets={"SWDA.MI": "Core", "XMME.MI": "Core"},
        current_weights={"SWDA.MI": 0.30, "XMME.MI": 0.10},
        bucket_weights={"Core": 0.40, "Difensivo": 0.0, "Satellite": 0.0},
        instrument_quotas={"Core": {"SWDA.MI": 0.75, "XMME.MI": 0.25}},
    )
    core = status["Core"]
    assert core["valid"] is True
    assert core["missing_tickers"] == []
    assert core["stale_tickers"] == []
    assert core["sum_target"] == pytest.approx(1.0)
    assert core["current_weights"]["SWDA.MI"] == pytest.approx(0.75)
    assert core["current_weights"]["XMME.MI"] == pytest.approx(0.25)
    assert core["deviations_pp"]["SWDA.MI"] == pytest.approx(0.0)
    assert core["deviations_pp"]["XMME.MI"] == pytest.approx(0.0)
    assert core["target_weights"] == {"SWDA.MI": pytest.approx(0.75), "XMME.MI": pytest.approx(0.25)}
    # Ogni chiamata restituisce sempre le 3 chiavi Core/Difensivo/Satellite.
    assert set(status.keys()) == {"Core", "Difensivo", "Satellite"}
    assert status["Difensivo"]["valid"] is True
    assert status["Satellite"]["valid"] is True


def test_quota_status_missing_ticker_invalid():
    status = _compute_instrument_quota_status(
        instrument_buckets={"SWDA.MI": "Core", "XMME.MI": "Core"},
        current_weights={"SWDA.MI": 0.30, "XMME.MI": 0.10},
        bucket_weights={"Core": 0.40, "Difensivo": 0.0, "Satellite": 0.0},
        instrument_quotas={"Core": {"SWDA.MI": 1.0}},  # XMME.MI non censito
    )
    core = status["Core"]
    assert core["valid"] is False
    assert core["missing_tickers"] == ["XMME.MI"]
    assert core["stale_tickers"] == []


def test_quota_status_sum_not_100_invalid():
    status = _compute_instrument_quota_status(
        instrument_buckets={"SWDA.MI": "Core"},
        current_weights={"SWDA.MI": 0.40},
        bucket_weights={"Core": 0.40, "Difensivo": 0.0, "Satellite": 0.0},
        instrument_quotas={"Core": {"SWDA.MI": 0.80}},
    )
    assert status["Core"]["valid"] is False
    assert status["Core"]["sum_target"] == pytest.approx(0.80)
    assert status["Core"]["missing_tickers"] == []


def test_quota_status_empty_bucket_no_holdings_and_no_quotas_is_valid():
    status = _compute_instrument_quota_status(
        instrument_buckets={},
        current_weights={},
        bucket_weights={"Core": 0.0, "Difensivo": 0.0, "Satellite": 0.0},
        instrument_quotas={},
    )
    assert status["Core"]["valid"] is True
    assert status["Difensivo"]["valid"] is True
    assert status["Satellite"]["valid"] is True
    assert status["Core"]["sum_target"] == pytest.approx(0.0)
    assert status["Core"]["current_weights"] == {}
    assert status["Core"]["target_weights"] == {}


def test_quota_status_stale_ticker_excluded_from_sum_and_breaks_validity():
    # SWDA chiuso (non piu' in instrument_buckets) aveva quota 75%: la somma
    # dei ticker ancora attivi (solo XMME 25%) scende sotto 100% -> invalido.
    status = _compute_instrument_quota_status(
        instrument_buckets={"XMME.MI": "Core"},
        current_weights={"XMME.MI": 0.10},
        bucket_weights={"Core": 0.10, "Difensivo": 0.0, "Satellite": 0.0},
        instrument_quotas={"Core": {"SWDA.MI": 0.75, "XMME.MI": 0.25}},
    )
    core = status["Core"]
    assert core["valid"] is False
    assert core["stale_tickers"] == ["SWDA.MI"]
    assert core["missing_tickers"] == []
    assert core["sum_target"] == pytest.approx(0.25)  # SWDA escluso dalla somma
    # SWDA non compare in target_weights/current_weights: e' stale, fuori bucket attivo.
    assert "SWDA.MI" not in core["target_weights"]
    assert "SWDA.MI" not in core["current_weights"]


def test_quota_status_stale_ticker_with_zero_target_does_not_break_validity():
    """Caso limite documentato dalla spec: strumento chiuso con quota target
    0% non fa scendere la somma sotto 100% -> nessun blocco (non c'era nulla
    da ribilanciare)."""
    status = _compute_instrument_quota_status(
        instrument_buckets={"XMME.MI": "Core"},
        current_weights={"XMME.MI": 0.40},
        bucket_weights={"Core": 0.40, "Difensivo": 0.0, "Satellite": 0.0},
        instrument_quotas={"Core": {"SWDA.MI": 0.0, "XMME.MI": 1.0}},
    )
    core = status["Core"]
    assert core["stale_tickers"] == ["SWDA.MI"]
    assert core["sum_target"] == pytest.approx(1.0)
    assert core["valid"] is True


def test_quota_status_never_configured_bucket_is_valid_even_with_holdings():
    # CORREZIONE 2026-08-18: un bucket con instrument_quotas completamente
    # vuoto deve restare valido anche se possiede strumenti attivi - la
    # feature e' opt-in, non deve bloccare SATOR per chi non l'ha mai
    # usata. Prima della correzione questo caso risultava (erroneamente)
    # invalido con missing_tickers=["SWDA.MI","XMME.MI"].
    status = _compute_instrument_quota_status(
        instrument_buckets={"SWDA.MI": "Core", "XMME.MI": "Core"},
        current_weights={"SWDA.MI": 0.30, "XMME.MI": 0.10},
        bucket_weights={"Core": 0.40, "Difensivo": 0.0, "Satellite": 0.0},
        instrument_quotas={},  # Core non configurato affatto
    )
    core = status["Core"]
    assert core["valid"] is True
    assert core["missing_tickers"] == []
    assert core["sum_target"] == pytest.approx(0.0)
    # I pesi attuali sono comunque riportati (utili per la UI) anche se
    # il bucket non e' "configurato": solo la validita' non ne risente.
    assert core["current_weights"]["SWDA.MI"] == pytest.approx(0.75)
    assert core["current_weights"]["XMME.MI"] == pytest.approx(0.25)


def test_quota_status_zero_target_weight_allowed():
    status = _compute_instrument_quota_status(
        instrument_buckets={"SWDA.MI": "Core", "XMME.MI": "Core"},
        current_weights={"SWDA.MI": 0.40, "XMME.MI": 0.0},
        bucket_weights={"Core": 0.40, "Difensivo": 0.0, "Satellite": 0.0},
        instrument_quotas={"Core": {"SWDA.MI": 1.0, "XMME.MI": 0.0}},
    )
    assert status["Core"]["valid"] is True
    assert status["Core"]["target_weights"]["XMME.MI"] == pytest.approx(0.0)


def test_quota_status_configured_bucket_with_zero_active_tickers_is_valid_regardless_of_sum():
    """Caso limite reale (non esplicitamente nella spec, ma presente nel
    codice attuale): un bucket CON quote configurate ma che al momento non
    possiede alcuno strumento attivo (es. tutti venduti) e' valido a
    prescindere dalla somma delle quote residue - missing_tickers e' sempre
    vuoto quando active_tickers e' vuoto (nessuno strumento attivo da cui
    pretendere una quota), e la formula di validita' short-circuita su
    'not active_tickers'."""
    status = _compute_instrument_quota_status(
        instrument_buckets={},  # nessuno strumento attivo nel bucket Core
        current_weights={},
        bucket_weights={"Core": 0.0, "Difensivo": 0.0, "Satellite": 0.0},
        instrument_quotas={"Core": {"SWDA.MI": 0.6}},  # somma 60%, non 100%
    )
    core = status["Core"]
    assert core["missing_tickers"] == []
    assert core["stale_tickers"] == ["SWDA.MI"]
    assert core["sum_target"] == pytest.approx(0.0)  # SWDA escluso (non attivo)
    assert core["valid"] is True


def test_quota_status_current_weights_zero_when_bucket_total_is_zero():
    status = _compute_instrument_quota_status(
        instrument_buckets={"SWDA.MI": "Core"},
        current_weights={"SWDA.MI": 0.0},
        bucket_weights={"Core": 0.0, "Difensivo": 0.0, "Satellite": 0.0},
        instrument_quotas={"Core": {"SWDA.MI": 1.0}},
    )
    assert status["Core"]["current_weights"]["SWDA.MI"] == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# compute_instrument_quota_status: wrapper pubblico standalone
# --------------------------------------------------------------------------- #

def test_compute_instrument_quota_status_public_wrapper_empty_portfolio():
    data = {"strumenti": [], "_positions_df": None}
    status = compute_instrument_quota_status(data, {})
    for bucket in ("Core", "Difensivo", "Satellite"):
        assert status[bucket]["valid"] is True
        assert status[bucket]["missing_tickers"] == []
        assert status[bucket]["stale_tickers"] == []
        assert status[bucket]["sum_target"] == pytest.approx(0.0)
        assert status[bucket]["current_weights"] == {}
        assert status[bucket]["target_weights"] == {}
        assert status[bucket]["deviations_pp"] == {}


def test_compute_instrument_quota_status_public_wrapper_matches_manual_pipeline():
    """Il wrapper deve limitarsi a incollare le stesse funzioni gia' testate
    (compute_instrument_buckets, _compute_current_weights,
    _compute_bucket_weights, _compute_instrument_quota_status) senza
    ricalcolare nulla di suo: verificato riproducendo la pipeline a mano."""
    from core.services.sator import (
        _compute_bucket_weights,
        _compute_current_weights,
        _tickers_posseduti,
        compute_instrument_buckets,
    )

    data = {
        "strumenti": [
            {"ticker": "SWDA.MI", "nome": "Alpha", "tipo": "ETF", "prezzo": 90.0},
            {"ticker": "XMME.MI", "nome": "Beta", "tipo": "ETF", "prezzo": 30.0},
        ],
        "instrument_master": {},
        "_positions_df": pd.DataFrame([
            {"Ticker": "SWDA.MI", "Quote": 10.0, "Controvalore": 900.0},
            {"Ticker": "XMME.MI", "Quote": 10.0, "Controvalore": 300.0},
        ]),
    }
    settings = {"sator": {"instrument_quotas": {"Core": {"SWDA.MI": 0.75, "XMME.MI": 0.25}}}}

    actual = compute_instrument_quota_status(data, settings)

    state_df = data["_positions_df"]
    held = _tickers_posseduti(state_df)
    instrument_buckets = compute_instrument_buckets(data, held)
    current_weights = _compute_current_weights(state_df)
    bucket_weights = _compute_bucket_weights(data, state_df, current_weights)
    cfg = ensure_sator_settings(settings)
    expected = _compute_instrument_quota_status(instrument_buckets, current_weights, bucket_weights, cfg["instrument_quotas"])

    assert actual == expected
    assert actual["Core"]["valid"] is True


def test_compute_instrument_quota_status_excludes_ticker_with_bucket_exposure_override():
    """Uno strumento con bucket_exposure_user_edited=True non deve comparire
    tra i ticker richiesti per la validazione delle quote interne del suo
    bucket - ne' come 'mancante' se non ha una quota, ne' nel calcolo della
    somma-100%. Deciso esplicitamente con l'utente: l'interazione piena tra
    divisione bucket e quote interne e' fuori scopo per questo sotto-progetto."""
    from core.services.sator import compute_instrument_buckets

    data = {
        "strumenti": [
            {"ticker": "FAM-FLEX", "nome": "FAM Series Flexible", "tipo": "Fondo Bilan. Flessibile", "prezzo": 100.0},
            {"ticker": "SWDA.MI", "nome": "iShares Core MSCI World", "tipo": "ETF", "prezzo": 90.0},
        ],
        "instrument_master": {
            "FAM-FLEX": {
                "manual_overrides": {
                    "sator": {
                        "bucket_exposure": {"Core": 0.6, "Difensivo": 0.4, "Satellite": 0.0},
                        "bucket_exposure_user_edited": True,
                    }
                }
            }
        },
        "_positions_df": pd.DataFrame([
            {"Ticker": "FAM-FLEX", "Quote": 10.0, "Controvalore": 1000.0},
            {"Ticker": "SWDA.MI", "Quote": 10.0, "Controvalore": 900.0},
        ]),
    }
    cfg = ensure_sator_settings({})
    # Configura una quota interna SOLO per SWDA.MI nel suo bucket, per attivare
    # la modalita' "stretta" (opt-in-per-bucket) - senza toccare FAM-FLEX.
    buckets = compute_instrument_buckets(data)
    swda_bucket = buckets["SWDA.MI"]
    cfg["instrument_quotas"][swda_bucket] = {"SWDA.MI": 1.0}
    settings = {"sator": cfg}

    status = compute_instrument_quota_status(data, settings)

    for bucket_status in status.values():
        assert "FAM-FLEX" not in bucket_status["missing_tickers"]
        assert "FAM-FLEX" not in bucket_status["stale_tickers"]
        assert "FAM-FLEX" not in bucket_status["current_weights"]
        assert "FAM-FLEX" not in bucket_status["target_weights"]


def test_bucket_stays_valid_when_split_instrument_had_a_pre_existing_quota():
    """Regressione trovata dalla review finale: attivare la divisione tra
    bucket per uno strumento che aveva gia' una quota interna configurata
    non deve invalidare permanentemente il bucket - la spec (sezione 6)
    promette esplicitamente che la quota resta salvata ma viene ignorata
    ai fini della validazione. FAM-FLEX e SWDA.MI risolvono entrambi nel
    bucket "Core" (verificato con compute_instrument_buckets)."""
    from core.services.sator import compute_instrument_buckets

    data = {
        "strumenti": [
            {"ticker": "FAM-FLEX", "nome": "FAM Series Flexible", "tipo": "Fondo Bilan. Flessibile", "prezzo": 100.0},
            {"ticker": "SWDA.MI", "nome": "iShares Core MSCI World", "tipo": "ETF", "prezzo": 90.0},
        ],
        "instrument_master": {
            "FAM-FLEX": {
                "manual_overrides": {
                    "sator": {
                        "bucket_exposure": {"Core": 0.6, "Difensivo": 0.4, "Satellite": 0.0},
                        "bucket_exposure_user_edited": True,
                    }
                }
            }
        },
        "_positions_df": pd.DataFrame([
            {"Ticker": "FAM-FLEX", "Quote": 10.0, "Controvalore": 1000.0},
            {"Ticker": "SWDA.MI", "Quote": 10.0, "Controvalore": 900.0},
        ]),
    }
    # Verifica preliminare della fixture: entrambi devono risolvere nello
    # stesso bucket "Core" prima di fidarsi del test sotto.
    buckets = compute_instrument_buckets(data)
    assert buckets["FAM-FLEX"] == "Core"
    assert buckets["SWDA.MI"] == "Core"

    settings = {"sator": {"instrument_quotas": {"Core": {"FAM-FLEX": 0.4, "SWDA.MI": 0.6}}}}

    status = compute_instrument_quota_status(data, settings)

    assert status["Core"]["valid"] is True
    assert status["Core"]["missing_tickers"] == []
    assert status["Core"]["sum_target"] == pytest.approx(0.6)


def test_bucket_without_any_split_instrument_validates_exactly_as_before():
    """Non-regressione: se nessuno strumento del bucket ha una divisione tra
    bucket attiva, il fix del reserved-percentage non deve alterare nulla -
    stesso comportamento pre-esistente (somma quote vs 100% flat)."""
    data = {
        "strumenti": [
            {"ticker": "SWDA.MI", "nome": "iShares Core MSCI World", "tipo": "ETF", "prezzo": 90.0},
            {"ticker": "XMME.MI", "nome": "iShares MSCI EM", "tipo": "ETF", "prezzo": 30.0},
        ],
        "instrument_master": {},
        "_positions_df": pd.DataFrame([
            {"Ticker": "SWDA.MI", "Quote": 10.0, "Controvalore": 900.0},
            {"Ticker": "XMME.MI", "Quote": 10.0, "Controvalore": 300.0},
        ]),
    }
    settings = {"sator": {"instrument_quotas": {"Core": {"SWDA.MI": 0.75, "XMME.MI": 0.25}}}}

    status = compute_instrument_quota_status(data, settings)

    assert status["Core"]["valid"] is True
    assert status["Core"]["sum_target"] == pytest.approx(1.0)

    # E lo stesso scenario con una somma NON al 100% deve restare invalido
    # esattamente come prima (nessuna divisione bucket coinvolta).
    settings_bad = {"sator": {"instrument_quotas": {"Core": {"SWDA.MI": 0.75, "XMME.MI": 0.10}}}}
    status_bad = compute_instrument_quota_status(data, settings_bad)
    assert status_bad["Core"]["valid"] is False


def test_compute_instrument_quota_status_leaves_other_overrides_unaffected():
    """Solo bucket_exposure_user_edited=True esclude uno strumento. Altri
    flag di override manuale (es. user_edited del ruolo, o
    benchmark_user_edited) non devono avere alcun effetto su questo filtro:
    lo strumento resta soggetto alla validazione delle quote interne come
    prima."""
    data = {
        "strumenti": [
            {"ticker": "SWDA.MI", "nome": "iShares Core MSCI World", "tipo": "ETF", "prezzo": 90.0},
        ],
        "instrument_master": {
            "SWDA.MI": {
                "manual_overrides": {
                    "sator": {
                        "user_edited": True,
                        "benchmark_user_edited": True,
                    }
                }
            }
        },
        "_positions_df": pd.DataFrame([
            {"Ticker": "SWDA.MI", "Quote": 10.0, "Controvalore": 900.0},
        ]),
    }
    settings = {"sator": {"instrument_quotas": {"Core": {"SWDA.MI": 1.0}}}}

    status = compute_instrument_quota_status(data, settings)

    core = status["Core"]
    assert core["valid"] is True
    assert "SWDA.MI" in core["current_weights"]
    assert "SWDA.MI" in core["target_weights"]


# --------------------------------------------------------------------------- #
# SatorContext.blocked_buckets_quota: default
# --------------------------------------------------------------------------- #

def test_sator_context_blocked_buckets_quota_defaults_to_empty_frozenset():
    ctx = SatorContext(
        data={}, settings={}, budget=0.0, state_df=pd.DataFrame(), price_frame=pd.DataFrame(),
        returns_frame=pd.DataFrame(), current_weights={}, nature_weights={}, bucket_weights={},
        portfolio_value=0.0, correlations={}, selected_categories=(), include_fee_instruments=True,
        liquidita=0.0,
    )
    assert ctx.blocked_buckets_quota == frozenset()


# --------------------------------------------------------------------------- #
# run_sator_analysis: integrazione quota_status / blocked_buckets_quota
# --------------------------------------------------------------------------- #

def _fixture_data_core_valid():
    """Core: 2 strumenti posseduti (SWDA/XMME, inferiti entrambi in Core
    tramite pattern del ticker), quote assegnate correttamente (somma 100%).
    Difensivo/Satellite: nessuno strumento posseduto, non configurati ->
    validi per definizione. AGGH.MI (bond, Difensivo) e IUSN.MI (fallback
    "altro"/satellite_tematico, Satellite) sono candidati NON posseduti,
    usati per verificare se compaiono o meno nel ranking."""
    return {
        "strumenti": [
            {"ticker": "SWDA.MI", "nome": "iShares Core MSCI World", "tipo": "ETF", "prezzo": 90.0},
            {"ticker": "XMME.MI", "nome": "iShares MSCI EM", "tipo": "ETF", "prezzo": 30.0},
            {"ticker": "AGGH.MI", "nome": "iShares Global Aggregate Bond", "tipo": "ETF", "prezzo": 5.0},
            {"ticker": "IUSN.MI", "nome": "Strumento Non Classificato", "tipo": "ETF", "prezzo": 40.0},
        ],
        "instrument_master": {},
        "_positions_df": pd.DataFrame([
            {"Ticker": "SWDA.MI", "Quote": 10.0, "Controvalore": 900.0},
            {"Ticker": "XMME.MI", "Quote": 10.0, "Controvalore": 300.0},
        ]),
    }


def test_fixture_roles_are_inferred_as_expected():
    """Verifica preliminare (non sul comportamento della feature, ma sulla
    fixture stessa): conferma che l'inferenza automatica dei ruoli
    classifichi i ticker scelti nei bucket attesi PRIMA di fidarsi dei test
    di integrazione sotto - i pattern di riconoscimento sono nel codice
    reale (infer_sator_metadata), non negli esempi del piano."""
    from core.services.sator import compute_instrument_buckets

    data = _fixture_data_core_valid()
    buckets_all = compute_instrument_buckets(data)  # nessun filtro held: tutti i ticker
    assert buckets_all["SWDA.MI"] == "Core"
    assert buckets_all["XMME.MI"] == "Core"
    assert buckets_all["AGGH.MI"] == "Difensivo"
    assert buckets_all["IUSN.MI"] == "Satellite"


def test_run_sator_analysis_returns_quota_status_key():
    data = _fixture_data_core_valid()
    settings = {"sator": {"instrument_quotas": {"Core": {"SWDA.MI": 0.75, "XMME.MI": 0.25}}}}
    result = run_sator_analysis(data, settings, budget=1000.0)
    assert "quota_status" in result
    assert set(result["quota_status"].keys()) == {"Core", "Difensivo", "Satellite"}
    assert result["quota_status"]["Core"]["valid"] is True


def test_run_sator_analysis_keeps_candidates_when_all_buckets_valid():
    data = _fixture_data_core_valid()
    settings = {"sator": {"instrument_quotas": {"Core": {"SWDA.MI": 0.75, "XMME.MI": 0.25}}}}
    result = run_sator_analysis(data, settings, budget=1000.0)
    ranking = result["ranking"]
    ranking_tickers = set(ranking["ticker"]) if not ranking.empty else set()
    assert "AGGH.MI" in ranking_tickers
    assert "IUSN.MI" in ranking_tickers


def test_run_sator_analysis_blocks_bucket_with_held_ticker_missing_quota():
    """Difensivo diventa opt-in-ma-incompleto: XEON.MI (liquidita, inferito
    Difensivo) ha una quota assegnata, VAGF.MI (bond, inferito Difensivo) no
    -> copertura incompleta -> Difensivo invalido -> i suoi candidati NON
    posseduti (AGGH.MI) spariscono dal ranking. Satellite resta intonso."""
    data = _fixture_data_core_valid()
    data["strumenti"].append({"ticker": "XEON.MI", "nome": "Xtrackers Overnight Rate Swap", "tipo": "ETF", "prezzo": 100.0})
    data["strumenti"].append({"ticker": "VAGF.MI", "nome": "Vanguard Global Aggregate Bond", "tipo": "ETF", "prezzo": 50.0})
    data["_positions_df"] = pd.concat([
        data["_positions_df"],
        pd.DataFrame([
            {"Ticker": "XEON.MI", "Quote": 5.0, "Controvalore": 500.0},
            {"Ticker": "VAGF.MI", "Quote": 5.0, "Controvalore": 500.0},
        ]),
    ], ignore_index=True)

    # Verifica preliminare della fixture: entrambi devono finire in Difensivo.
    from core.services.sator import compute_instrument_buckets
    buckets = compute_instrument_buckets(data, {"XEON.MI", "VAGF.MI"})
    assert buckets["XEON.MI"] == "Difensivo"
    assert buckets["VAGF.MI"] == "Difensivo"

    settings = {
        "sator": {
            "instrument_quotas": {
                "Core": {"SWDA.MI": 0.75, "XMME.MI": 0.25},
                "Difensivo": {"XEON.MI": 1.0},  # VAGF.MI posseduto ma senza quota -> missing
            },
        }
    }
    result = run_sator_analysis(data, settings, budget=1000.0)
    assert "Difensivo" in result["quota_status"]
    assert result["quota_status"]["Difensivo"]["valid"] is False
    assert result["quota_status"]["Difensivo"]["missing_tickers"] == ["VAGF.MI"]

    ranking = result["ranking"]
    ranking_tickers = set(ranking["ticker"]) if not ranking.empty else set()
    assert "AGGH.MI" not in ranking_tickers, "AGGH.MI (Difensivo) deve sparire: il bucket e' bloccato"
    assert "IUSN.MI" in ranking_tickers, "Satellite non e' toccato dal blocco di Difensivo"


def test_run_sator_analysis_blocks_bucket_regardless_of_bucket_first_allocation():
    """Stessa fixture del test precedente, ma con bucket_first_allocation=True:
    il blocco avviene in _score_universe, A MONTE della biforcazione tra
    _suggested_quotes e _suggested_quotes_by_bucket, quindi deve valere
    identico in entrambe le modalita' (requisito esplicito della spec)."""
    data = _fixture_data_core_valid()
    data["strumenti"].append({"ticker": "XEON.MI", "nome": "Xtrackers Overnight Rate Swap", "tipo": "ETF", "prezzo": 100.0})
    data["strumenti"].append({"ticker": "VAGF.MI", "nome": "Vanguard Global Aggregate Bond", "tipo": "ETF", "prezzo": 50.0})
    data["_positions_df"] = pd.concat([
        data["_positions_df"],
        pd.DataFrame([
            {"Ticker": "XEON.MI", "Quote": 5.0, "Controvalore": 500.0},
            {"Ticker": "VAGF.MI", "Quote": 5.0, "Controvalore": 500.0},
        ]),
    ], ignore_index=True)

    settings = {
        "sator": {
            "instrument_quotas": {
                "Core": {"SWDA.MI": 0.75, "XMME.MI": 0.25},
                "Difensivo": {"XEON.MI": 1.0},
            },
            "bucket_first_allocation": True,
        }
    }
    result = run_sator_analysis(data, settings, budget=1000.0)
    ranking = result["ranking"]
    ranking_tickers = set(ranking["ticker"]) if not ranking.empty else set()
    assert "AGGH.MI" not in ranking_tickers


def test_run_sator_analysis_unconfigured_bucket_never_blocks_candidates():
    """Un bucket con SOLO quote non configurate (dict vuoto) non deve
    bloccare nulla, a differenza di uno configurato ma incompleto (test
    sopra) - confronto diretto usando la STESSA fixture di holding, per
    isolare l'unica variabile che cambia: se Difensivo e' configurato o no."""
    data = _fixture_data_core_valid()
    data["strumenti"].append({"ticker": "XEON.MI", "nome": "Xtrackers Overnight Rate Swap", "tipo": "ETF", "prezzo": 100.0})
    data["strumenti"].append({"ticker": "VAGF.MI", "nome": "Vanguard Global Aggregate Bond", "tipo": "ETF", "prezzo": 50.0})
    data["_positions_df"] = pd.concat([
        data["_positions_df"],
        pd.DataFrame([
            {"Ticker": "XEON.MI", "Quote": 5.0, "Controvalore": 500.0},
            {"Ticker": "VAGF.MI", "Quote": 5.0, "Controvalore": 500.0},
        ]),
    ], ignore_index=True)

    settings = {
        "sator": {
            "instrument_quotas": {
                "Core": {"SWDA.MI": 0.75, "XMME.MI": 0.25},
                # Difensivo assente/vuoto: mai configurato -> opt-out, nessun blocco
                # anche se XEON.MI/VAGF.MI sono entrambi posseduti senza quota.
            },
        }
    }
    result = run_sator_analysis(data, settings, budget=1000.0)
    assert result["quota_status"]["Difensivo"]["valid"] is True
    ranking = result["ranking"]
    ranking_tickers = set(ranking["ticker"]) if not ranking.empty else set()
    assert "AGGH.MI" in ranking_tickers


def test_run_sator_analysis_invalid_core_blocks_its_own_held_candidates_too():
    """Il blocco non riguarda solo i candidati non posseduti: se Core e'
    invalido, anche SWDA.MI/XMME.MI (gia' in portafoglio) spariscono dal
    ranking - '_score_universe' filtra per bucket, non per stato di possesso."""
    data = _fixture_data_core_valid()
    settings = {
        "sator": {
            "instrument_quotas": {
                "Core": {"SWDA.MI": 1.0},  # XMME.MI posseduto ma senza quota -> Core invalido
            },
        }
    }
    result = run_sator_analysis(data, settings, budget=1000.0)
    assert result["quota_status"]["Core"]["valid"] is False
    ranking = result["ranking"]
    ranking_tickers = set(ranking["ticker"]) if not ranking.empty else set()
    assert "SWDA.MI" not in ranking_tickers
    assert "XMME.MI" not in ranking_tickers
    # Satellite/Difensivo restano intonsi (non configurati, nessun possesso).
    assert "AGGH.MI" in ranking_tickers
    assert "IUSN.MI" in ranking_tickers
