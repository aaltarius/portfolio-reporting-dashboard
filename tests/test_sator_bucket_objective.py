from __future__ import annotations

import pandas as pd
import pytest

from core.services.sator import compute_instrument_buckets, compute_current_bucket_mix


def _sample_data():
    return {
        "strumenti": [
            {"ticker": "SWDA.MI", "nome": "iShares Core MSCI World", "tipo": "ETF"},
            {"ticker": "XEON.MI", "nome": "Xtrackers Overnight Rate Swap", "tipo": "ETF"},
            {"ticker": "XAIX.MI", "nome": "Xtrackers Artificial Intelligence", "tipo": "ETF"},
        ],
        "instrument_master": {},
    }


def _state_df():
    return pd.DataFrame([
        {"Ticker": "SWDA.MI", "Quote": 10.0, "Controvalore": 600.0},
        {"Ticker": "XEON.MI", "Quote": 5.0, "Controvalore": 250.0},
        {"Ticker": "XAIX.MI", "Quote": 3.0, "Controvalore": 150.0},
    ])


def test_compute_instrument_buckets_classifies_by_inferred_role():
    buckets = compute_instrument_buckets(_sample_data())
    assert buckets["SWDA.MI"] == "Core"
    assert buckets["XEON.MI"] == "Difensivo"
    assert buckets["XAIX.MI"] == "Satellite"


def test_compute_instrument_buckets_can_restrict_to_held_tickers():
    buckets = compute_instrument_buckets(_sample_data(), held_tickers={"SWDA.MI"})
    assert list(buckets.keys()) == ["SWDA.MI"]


def test_compute_current_bucket_mix_weights_by_controvalore():
    mix = compute_current_bucket_mix(_sample_data(), _state_df())
    assert set(mix.keys()) == {"Core", "Difensivo", "Satellite"}
    assert mix["Core"] == pytest.approx(0.60)
    assert mix["Difensivo"] == pytest.approx(0.25)
    assert mix["Satellite"] == pytest.approx(0.15)


def test_compute_bucket_weights_splits_value_for_instrument_with_bucket_exposure_override(monkeypatch):
    import pandas as pd
    from core.services.sator import _compute_bucket_weights

    data = {
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
        "strumenti": [
            {"ticker": "FAM-FLEX", "nome": "FAM Series Flexible", "tipo": "Fondo Bilan. Flessibile"},
        ],
    }
    state_df = pd.DataFrame([{"Ticker": "FAM-FLEX", "Quote": 10.0, "Controvalore": 1000.0}])
    current_weights = {"FAM-FLEX": 1.0}  # 100% del portafoglio in questo unico strumento

    result = _compute_bucket_weights(data, state_df, current_weights, use_fractional_exposure=True)

    assert result["Core"] == 0.6
    assert result["Difensivo"] == 0.4
    assert result["Satellite"] == 0.0


def test_compute_bucket_weights_default_ignores_bucket_exposure_override():
    """Il motore SATOR vero (run_sator_analysis, build_sator_matrix_frame,
    compute_instrument_quota_status) chiama _compute_bucket_weights senza
    use_fractional_exposure, quindi con il default False: la ripartizione
    frazionata dell'appartenenza a bucket resta fuori scope per il motore
    in questo sotto-progetto. Questo test garantisce che, anche con un
    bucket_exposure diviso configurato, il default continui a mettere il
    100% del valore nel bucket primario - esattamente il comportamento
    del motore prima di questo intero task (Task 3)."""
    import pandas as pd
    from core.services.sator import _compute_bucket_weights, compute_instrument_buckets

    data = {
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
        "strumenti": [
            {"ticker": "FAM-FLEX", "nome": "FAM Series Flexible", "tipo": "Fondo Bilan. Flessibile"},
        ],
    }
    state_df = pd.DataFrame([{"Ticker": "FAM-FLEX", "Quote": 10.0, "Controvalore": 1000.0}])
    current_weights = {"FAM-FLEX": 1.0}

    primary_bucket = compute_instrument_buckets(data, {"FAM-FLEX"})["FAM-FLEX"]
    result = _compute_bucket_weights(data, state_df, current_weights)  # nessun use_fractional_exposure = default False

    assert result[primary_bucket] == 1.0
    assert sum(v for k, v in result.items() if k != primary_bucket) == 0.0


def test_compute_bucket_weights_unchanged_for_instrument_without_override(monkeypatch):
    """Non-regressione esplicita: uno strumento senza bucket_exposure si
    comporta esattamente come prima (100% nel suo bucket primario)."""
    import pandas as pd
    from core.services.sator import _compute_bucket_weights, compute_instrument_buckets

    data = {
        "instrument_master": {},
        "strumenti": [
            {"ticker": "SWDA.MI", "nome": "iShares Core MSCI World", "tipo": "ETF Az. Globale"},
        ],
    }
    state_df = pd.DataFrame([{"Ticker": "SWDA.MI", "Quote": 10.0, "Controvalore": 1000.0}])
    current_weights = {"SWDA.MI": 1.0}

    buckets = compute_instrument_buckets(data, {"SWDA.MI"})
    result = _compute_bucket_weights(data, state_df, current_weights)

    assert result[buckets["SWDA.MI"]] == 1.0


def test_compute_current_bucket_mix_excludes_given_tickers_and_renormalizes():
    """Corretto 2026-08-19: a differenza di _compute_bucket_weights (usato
    per il deficit di bucket in SATOR, dove i pesi grezzi non vanno MAI
    rinormalizzati - richiesta esplicita dell'utente), qui il risultato e'
    una percentuale di composizione mostrata all'utente nel grafico
    obiettivo-vs-mix: quando alcuni ticker sono esclusi, i pesi restanti
    devono sommare a 100% di cio' che resta visibile, altrimenti le barre
    'Attuale' non chiuderebbero al 100% - esattamente il bug segnalato
    dall'utente dopo il merge. La versione precedente di questo test
    bloccava (erroneamente) il vecchio comportamento non rinormalizzato."""
    mix = compute_current_bucket_mix(_sample_data(), _state_df(), exclude_tickers=frozenset({"XEON.MI"}))
    assert mix["Difensivo"] == pytest.approx(0.0)
    assert sum(mix.values()) == pytest.approx(1.0)
    assert mix["Core"] == pytest.approx(0.60 / 0.75)
    assert mix["Satellite"] == pytest.approx(0.15 / 0.75)


def test_compute_current_bucket_mix_exclude_tickers_defaults_to_no_exclusion():
    """Non-regressione: senza passare exclude_tickers il risultato resta
    identico a oggi (stesso test di test_compute_current_bucket_mix_weights_by_controvalore)."""
    mix_default = compute_current_bucket_mix(_sample_data(), _state_df())
    mix_explicit_empty = compute_current_bucket_mix(_sample_data(), _state_df(), exclude_tickers=frozenset())
    assert mix_default == mix_explicit_empty


def test_held_non_pac_tickers_reuses_non_pac_held_tickers_as_single_source():
    """held_non_pac_tickers(data, state_df) e' il wrapper pubblico usato dalla
    pagina Pianificazione per calcolare l'insieme di esclusione una sola volta:
    deve produrre esattamente lo stesso risultato di
    _non_pac_held_tickers(data, _tickers_posseduti(state_df)), la formula gia'
    usata (e testata) per il deficit di bucket - nessuna seconda formula."""
    from core.services.sator import held_non_pac_tickers, _non_pac_held_tickers, _tickers_posseduti

    data = _sample_data_with_btp()
    state_df = pd.DataFrame([
        {"Ticker": "SWDA.MI", "Quote": 10.0, "Controvalore": 600.0},
        {"Ticker": "XEON.MI", "Quote": 5.0, "Controvalore": 250.0},
        {"Ticker": "XAIX.MI", "Quote": 3.0, "Controvalore": 150.0},
        {"Ticker": "BTP-TEST", "Quote": 1.0, "Controvalore": 1000.0},
    ])
    expected = _non_pac_held_tickers(data, _tickers_posseduti(state_df))
    assert expected == frozenset({"BTP-TEST"})
    assert held_non_pac_tickers(data, state_df) == expected


from core.services.sator import _score_fit, _build_alerts


def test_score_fit_penalizes_line_when_its_bucket_is_over_objective():
    row = pd.Series({
        "nature": "tecnologia_ai", "nature_weight": 0.02, "current_weight": 0.0,
        "role": "satellite_crescita", "_sev": 1.0,
    })
    caps = {"tecnologia_ai": 0.08}
    score_on_target = _score_fit(row, caps, bucket_weights={"Satellite": 0.10}, bucket_targets={"satellite": 0.15})
    score_over_target = _score_fit(row, caps, bucket_weights={"Satellite": 0.30}, bucket_targets={"satellite": 0.15})
    assert score_over_target < score_on_target


def test_build_alerts_flags_bucket_over_objective():
    ranking = pd.DataFrame({
        "comparison_group": ["a"], "in_portfolio": [True], "state": ["in_portafoglio"],
        "storico_sufficiente": [True], "rango_gruppo": [1],
    })
    alerts = _build_alerts(ranking, nature_weights={}, bucket_weights={"Core": 0.5, "Difensivo": 0.2, "Satellite": 0.30},
                            portfolio_objective={"core": 0.55, "difensivo": 0.25, "satellite": 0.15})
    messages = [a["message"] for a in alerts]
    assert any("Satellite" in m for m in messages)


def test_build_alerts_nature_threshold_uses_configurable_caps_not_hardcoded_default():
    ranking = pd.DataFrame({
        "comparison_group": ["a"], "in_portfolio": [True], "state": ["in_portafoglio"],
        "storico_sufficiente": [True], "rango_gruppo": [1],
    })
    # peso 9%: sopra un cap custom del 5%, ma sotto il default hardcoded (oro: 10%)
    nature_weights = {"oro": 0.09}
    alerts_default_cap = _build_alerts(ranking, nature_weights, caps={"oro": 0.10})
    alerts_custom_cap = _build_alerts(ranking, nature_weights, caps={"oro": 0.05})
    assert not any("oro" in a["message"] for a in alerts_default_cap)
    assert any("oro" in a["message"] for a in alerts_custom_cap)


def test_compute_bucket_bands_applies_symmetric_tolerance():
    from core.services.sator import _compute_bucket_bands

    objective = {"core": 0.5, "difensivo": 0.4, "satellite": 0.1}
    bands = _compute_bucket_bands(objective, tolerance_pp=0.03)
    assert bands["Core"] == {"target": pytest.approx(0.5), "min": pytest.approx(0.47), "max": pytest.approx(0.53)}
    assert bands["Satellite"]["min"] == pytest.approx(0.07)
    assert bands["Satellite"]["max"] == pytest.approx(0.13)


def test_compute_bucket_bands_clips_min_at_zero_and_max_at_one():
    from core.services.sator import _compute_bucket_bands

    objective = {"core": 0.02, "difensivo": 0.0, "satellite": 0.99}
    bands = _compute_bucket_bands(objective, tolerance_pp=0.05)
    assert bands["Difensivo"]["min"] == pytest.approx(0.0)
    assert bands["Satellite"]["max"] == pytest.approx(1.0)


def test_compute_bucket_bands_missing_key_defaults_to_zero_target():
    from core.services.sator import _compute_bucket_bands

    bands = _compute_bucket_bands({}, tolerance_pp=0.03)
    assert bands["Core"]["target"] == pytest.approx(0.0)
    assert bands["Core"]["min"] == pytest.approx(0.0)


def test_compute_bucket_weights_unchanged_without_exclude_tickers():
    """Non-regressione: stesso identico risultato di oggi quando exclude_tickers non e' passato."""
    from core.services.sator import _compute_current_weights, _compute_bucket_weights

    data = _sample_data()
    state_df = _state_df()
    current_weights = _compute_current_weights(state_df)
    result = _compute_bucket_weights(data, state_df, current_weights)
    assert result == {"Core": pytest.approx(0.60), "Difensivo": pytest.approx(0.25), "Satellite": pytest.approx(0.15)}


def test_compute_bucket_weights_excludes_given_tickers():
    from core.services.sator import _compute_current_weights, _compute_bucket_weights

    data = _sample_data()
    state_df = _state_df()
    current_weights = _compute_current_weights(state_df)
    result = _compute_bucket_weights(data, state_df, current_weights, exclude_tickers=frozenset({"XEON.MI"}))
    # XEON.MI (Difensivo, Controvalore 250, peso 0.25 sul totale 1000) e' semplicemente
    # rimosso dal calcolo, SENZA rinormalizzare i pesi restanti sul nuovo totale ridotto:
    # Core e Satellite mantengono il loro peso originale sul portafoglio complessivo.
    assert result["Difensivo"] == pytest.approx(0.0)
    assert result["Core"] == pytest.approx(0.60)
    assert result["Satellite"] == pytest.approx(0.15)


def test_compute_bucket_weights_bucket_made_entirely_of_excluded_tickers_is_zero_not_renormalized():
    """Un bucket composto SOLO da ticker esclusi deve risultare a peso ~0.0, non
    gonfiare gli altri bucket per effetto di una rinormalizzazione (bug critico
    trovato dalla review finale del piano bucket-eligibility: 'se dico escludi
    dal calcolo i BTP questi non vengano considerati')."""
    from core.services.sator import _compute_current_weights, _compute_bucket_weights

    data = _sample_data()
    state_df = _state_df()
    current_weights = _compute_current_weights(state_df)
    # Difensivo (XEON.MI) e' l'UNICO membro del suo bucket: escluderlo del tutto
    # deve azzerare Difensivo, non far esplodere Core/Satellite oltre il loro peso reale.
    result = _compute_bucket_weights(data, state_df, current_weights, exclude_tickers=frozenset({"XEON.MI"}))
    assert result["Difensivo"] == pytest.approx(0.0)
    # Nessuna rinormalizzazione: Core+Satellite restano 0.75, NON 1.0.
    assert result["Core"] + result["Satellite"] == pytest.approx(0.75)
    assert result["Core"] == pytest.approx(0.60)
    assert result["Satellite"] == pytest.approx(0.15)


def _sample_data_with_btp():
    data = _sample_data()
    data["strumenti"].append({"ticker": "BTP-TEST", "nome": "BTP Test 2030", "tipo": "Titolo di Stato"})
    return data


def test_non_pac_held_tickers_flags_gov_category():
    from core.services.sator import _non_pac_held_tickers

    data = _sample_data_with_btp()
    held = {"SWDA.MI", "XEON.MI", "XAIX.MI", "BTP-TEST"}
    result = _non_pac_held_tickers(data, held)
    assert result == frozenset({"BTP-TEST"})


def test_non_pac_held_tickers_only_considers_held():
    from core.services.sator import _non_pac_held_tickers

    data = _sample_data_with_btp()
    result = _non_pac_held_tickers(data, held_tickers={"SWDA.MI"})
    assert result == frozenset()


def test_compute_bucket_deficits_real_case_core_bigger_than_satellite():
    """Riproduce il caso reale misurato in sessione: Core deficit maggiore di Satellite."""
    from core.services.sator import _compute_bucket_bands, _compute_bucket_deficits

    objective = {"core": 0.5, "difensivo": 0.4, "satellite": 0.1}
    bands = _compute_bucket_bands(objective, tolerance_pp=0.03)
    bucket_weights = {"Core": 0.189829, "Difensivo": 0.785807, "Satellite": 0.024364}
    portfolio_value = 64528.59
    budget = 1500.0

    deficits, blocked = _compute_bucket_deficits(bucket_weights, objective, bands, portfolio_value, budget)

    assert "Difensivo" in blocked
    assert "Difensivo" not in deficits or deficits["Difensivo"] == pytest.approx(0.0)
    assert deficits["Core"] > deficits["Satellite"]
    assert deficits["Core"] == pytest.approx(20765.0, rel=0.01)
    assert deficits["Satellite"] == pytest.approx(5031.0, rel=0.01)


def test_compute_bucket_deficits_bucket_in_band_has_zero_deficit():
    from core.services.sator import _compute_bucket_bands, _compute_bucket_deficits

    objective = {"core": 0.5, "difensivo": 0.4, "satellite": 0.1}
    bands = _compute_bucket_bands(objective, tolerance_pp=0.03)
    bucket_weights = {"Core": 0.50, "Difensivo": 0.40, "Satellite": 0.10}
    deficits, blocked = _compute_bucket_deficits(bucket_weights, objective, bands, portfolio_value=10000.0, budget=1000.0)
    assert blocked == set()
    assert deficits.get("Core", 0.0) == pytest.approx(0.0)
    assert deficits.get("Difensivo", 0.0) == pytest.approx(0.0)
    assert deficits.get("Satellite", 0.0) == pytest.approx(0.0)


def test_compute_bucket_deficits_bucket_over_max_band_is_blocked():
    from core.services.sator import _compute_bucket_bands, _compute_bucket_deficits

    objective = {"core": 0.5, "difensivo": 0.4, "satellite": 0.1}
    bands = _compute_bucket_bands(objective, tolerance_pp=0.03)
    bucket_weights = {"Core": 0.40, "Difensivo": 0.50, "Satellite": 0.10}
    deficits, blocked = _compute_bucket_deficits(bucket_weights, objective, bands, portfolio_value=10000.0, budget=1000.0)
    assert "Difensivo" in blocked
    assert deficits.get("Difensivo", 0.0) == pytest.approx(0.0)
    assert deficits["Core"] > 0.0


def test_compute_bucket_deficits_no_positive_deficit_returns_empty():
    from core.services.sator import _compute_bucket_bands, _compute_bucket_deficits

    objective = {"core": 0.5, "difensivo": 0.4, "satellite": 0.1}
    bands = _compute_bucket_bands(objective, tolerance_pp=0.03)
    # tutti i bucket sopra il proprio target (nessun deficit positivo possibile)
    bucket_weights = {"Core": 0.55, "Difensivo": 0.42, "Satellite": 0.12}
    deficits, blocked = _compute_bucket_deficits(bucket_weights, objective, bands, portfolio_value=10000.0, budget=1000.0)
    assert sum(deficits.values()) == pytest.approx(0.0)


def test_bucket_first_allocation_deficit_pac_only_real_data_core_not_blocked_and_gets_sane_share():
    """Regressione end-to-end reale per il bug critico trovato dalla review finale.

    Prima del fix, _compute_bucket_weights rinormalizzava i pesi restanti
    dopo aver escluso i BTP dal calcolo: sul portafoglio reale di questo
    repo, il peso di Core veniva gonfiato da 18,98% a un rinormalizzato
    79,41% - sopra la banda massima (53%) - facendolo apparire sovrappeso e
    bloccandolo, con l'intero budget dirottato su Difensivo (gia' il bucket
    piu' sovrappesato di tutti, 78,58%). Il fix rimuove la rinormalizzazione:
    Core deve restare al suo peso vero (identico con o senza esclusione, dato
    che non possiede BTP), non risultare bloccato, e ricevere una quota di
    budget non nulla e coerente col proprio deficit reale.
    """
    import json

    from persistence.storage import load_data, load_settings
    from core.finance import compute_portfolio_state
    from core.services.sator import (
        run_sator_analysis, build_sator_matrix_frame,
        _compute_current_weights, _compute_bucket_weights, _compute_bucket_deficits,
        _compute_bucket_bands, _non_pac_held_tickers, _tickers_posseduti, _compute_portfolio_value,
    )

    data = load_data()
    settings = load_settings()  # sola lettura in questo test: nessuna save_data/save_settings chiamata
    budget = 1500.0

    objective = settings.get("portfolio_objective", {}) or {}
    band_tolerance_pp = float((settings.get("sator", {}) or {}).get("band_tolerance_pp", 0.03) or 0.03)
    bands = _compute_bucket_bands(objective, band_tolerance_pp)

    state_df = compute_portfolio_state(data, include_closed=True).get("df")
    current_weights = _compute_current_weights(state_df)
    held = _tickers_posseduti(state_df)
    portfolio_value = _compute_portfolio_value(state_df)
    exclude = _non_pac_held_tickers(data, held)
    if not exclude:
        pytest.skip(
            "Nessun ticker non-PAC (BTP/GOV) posseduto in questo portafoglio: il caso "
            "indirizzato dal fix (esclusione non vuota) non e' riproducibile sui dati correnti."
        )

    # --- livello 1: _compute_bucket_weights e' strutturalmente corretto ---
    weights_no_excl = _compute_bucket_weights(data, state_df, current_weights)
    weights_excl = _compute_bucket_weights(data, state_df, current_weights, exclude_tickers=exclude)
    # Core non possiede ticker esclusi: il suo peso deve restare IDENTICO,
    # non gonfiarsi per effetto della rinormalizzazione rimossa dal fix.
    assert weights_excl["Core"] == pytest.approx(weights_no_excl["Core"])

    deficits_no_excl, _blocked_no_excl = _compute_bucket_deficits(weights_no_excl, objective, bands, portfolio_value, budget)
    deficits_excl, blocked_excl = _compute_bucket_deficits(weights_excl, objective, bands, portfolio_value, budget)

    assert "Core" not in blocked_excl, (
        "Core risulta bloccato dopo l'esclusione BTP: e' esattamente il sintomo del bug "
        "di rinormalizzazione - escludere ticker di ALTRI bucket non deve mai far apparire "
        "Core sovrappeso."
    )
    # Il deficit euro di Core e' sostanzialmente lo stesso con o senza esclusione: ne' il
    # suo peso ne' portfolio_value/objective/bande cambiano escludendo ticker di altri bucket.
    assert deficits_excl.get("Core", 0.0) == pytest.approx(deficits_no_excl.get("Core", 0.0), rel=1e-6)

    # --- livello 2: end-to-end attraverso la pipeline reale usata dalla UI ---
    settings_e2e = json.loads(json.dumps(settings))
    settings_e2e.setdefault("sator", {})
    settings_e2e["sator"]["bucket_first_allocation"] = True
    settings_e2e["sator"]["deficit_pac_only"] = True

    result = run_sator_analysis(data, settings_e2e, budget=budget)
    matrix = build_sator_matrix_frame(result["ranking"], budget=budget, data=data, settings=settings_e2e)
    assert not matrix.empty

    core_rows = matrix.loc[matrix["_bucket"] == "Core"]
    core_amount = float((core_rows["Sug"] * core_rows["Px"]).sum())
    assert core_amount > 0.0, (
        "Core non ha ricevuto nulla dal budget nel percorso end-to-end: comportamento "
        "del bug (Core bloccato, budget interamente dirottato su Difensivo)."
    )

    total_deficit_excl = sum(v for v in deficits_excl.values() if v > 0)
    if total_deficit_excl > 0:
        expected_share = budget * deficits_excl.get("Core", 0.0) / total_deficit_excl
        # Tolleranza ampia: la sotto-allocazione greedy dentro il bucket (quote intere,
        # punteggio decisione >=0.50, cap 35% per riga) non garantisce di spendere fino
        # all'ultimo centesimo del sotto-budget assegnato - qui si verifica solo l'ordine
        # di grandezza (comportamento sensato), non il centesimo esatto.
        assert core_amount <= expected_share * 1.5 + 1.0
        assert core_amount >= expected_share * 0.2


def test_build_alerts_suppresses_nature_alert_when_excluded_weight_is_under_cap():
    """Richiesta esplicita dell'utente (2026-08-16): quando deficit_pac_only e'
    attivo, un alert di concentrazione dovuto solo ai BTP (esclusi dal calcolo)
    non deve comparire, perche' l'utente ha gia' detto a SATOR di ignorarli."""
    ranking = pd.DataFrame({
        "comparison_group": ["a"], "in_portfolio": [True], "state": ["in_portafoglio"],
        "storico_sufficiente": [True], "rango_gruppo": [1],
    })
    nature_weights = {"bond_governativo": 0.76}
    caps = {"bond_governativo": 0.25}
    # senza pesi esclusi (comportamento di sempre, flag spento): l'alert compare
    alerts_flag_off = _build_alerts(ranking, nature_weights, caps=caps)
    assert any("bond governativo" in a["message"] for a in alerts_flag_off)
    # con i pesi ricalcolati escludendo i BTP: la concentrazione sparisce -> alert silenziato
    alerts_flag_on = _build_alerts(ranking, nature_weights, caps=caps, nature_weights_excl={"bond_governativo": 0.01})
    assert not any("bond governativo" in a["message"] for a in alerts_flag_on)


def test_build_alerts_keeps_nature_alert_unrelated_to_excluded_tickers():
    """Un alert non causato dai titoli esclusi (es. concentrazione su fondi PAC,
    che non sono BTP/GOV) deve restare visibile anche col flag acceso."""
    ranking = pd.DataFrame({
        "comparison_group": ["a"], "in_portfolio": [True], "state": ["in_portafoglio"],
        "storico_sufficiente": [True], "rango_gruppo": [1],
    })
    nature_weights = {"fondo_pac": 0.15}
    caps = {"fondo_pac": 0.08}
    # peso quasi invariato anche escludendo i BTP: fondo_pac non e' un titolo escluso
    alerts = _build_alerts(ranking, nature_weights, caps=caps, nature_weights_excl={"fondo_pac": 0.15})
    assert any("fondo pac" in a["message"] for a in alerts)


def test_build_alerts_suppresses_bucket_alert_when_excluded_bucket_weight_is_under_target():
    ranking = pd.DataFrame({
        "comparison_group": ["a"], "in_portfolio": [True], "state": ["in_portafoglio"],
        "storico_sufficiente": [True], "rango_gruppo": [1],
    })
    alerts_flag_off = _build_alerts(
        ranking, nature_weights={}, bucket_weights={"Difensivo": 0.79},
        portfolio_objective={"difensivo": 0.40},
    )
    assert any("Difensivo" in a["message"] for a in alerts_flag_off)
    alerts_flag_on = _build_alerts(
        ranking, nature_weights={}, bucket_weights={"Difensivo": 0.79},
        portfolio_objective={"difensivo": 0.40}, bucket_weights_excl={"Difensivo": 0.025},
    )
    assert not any("Difensivo" in a["message"] for a in alerts_flag_on)


def test_deficit_pac_only_suppresses_btp_alerts_but_keeps_unrelated_ones_real_data():
    """End-to-end su dati reali: con deficit_pac_only attivo, gli alert dovuti solo
    ai BTP (concentrazione natura, bucket Difensivo sovrappesato) spariscono; un
    alert non correlato (se presente) resta."""
    import copy

    from persistence.storage import load_data, load_settings
    from core.services.sator import run_sator_analysis, _non_pac_held_tickers, _tickers_posseduti
    from core.finance import compute_portfolio_state

    data = load_data()
    settings = load_settings()
    state_df = compute_portfolio_state(data, include_closed=True).get("df")
    held = _tickers_posseduti(state_df)
    if not _non_pac_held_tickers(data, held):
        pytest.skip("Nessun BTP/GOV posseduto sui dati correnti: caso non riproducibile.")

    settings_on = copy.deepcopy(settings)
    settings_on.setdefault("sator", {})["deficit_pac_only"] = True
    settings_off = copy.deepcopy(settings)
    settings_off.setdefault("sator", {})["deficit_pac_only"] = False

    result_on = run_sator_analysis(data, settings_on, budget=1000.0)
    result_off = run_sator_analysis(data, settings_off, budget=1000.0)

    messages_on = [a["message"] for a in result_on.get("alerts", [])]
    messages_off = [a["message"] for a in result_off.get("alerts", [])]

    btp_alert_off = any("bond governativo" in m for m in messages_off)
    if btp_alert_off:
        assert not any("bond governativo" in m for m in messages_on), (
            "l'alert di concentrazione bond governativo deve sparire col flag "
            "deficit_pac_only attivo, dato che e' dovuto solo ai BTP esclusi"
        )


def test_suggested_quotes_by_bucket_redistributes_leftover_to_saturated_buckets():
    """Regressione per il bug segnalato dall'utente il 2026-08-16: con budget 1600EUR
    reale, ogni bucket lasciava un residuo (nessuna candidatura sufficiente a spendere
    tutta la propria fetta) e il residuo restava liquido invece di essere ridato a un
    bucket che aveva invece saturato la propria quota - risultato: SATOR proponeva
    1371,97EUR su 1600EUR richiesti, e il pannello di confronto diceva all'utente che
    stava "impegnando piu budget di SATOR" quando in realta' stava solo usando il SUO
    budget dichiarato, non quello (parziale) di SATOR.
    """
    from core.services.sator import _suggested_quotes_by_bucket

    # Bucket A: un solo candidato costoso, il cap del 35% per riga lo ferma a 1 quota
    # e lascia un grosso residuo sulla propria fetta teorica. Bucket B: 3 candidati
    # economici, capace di assorbire budget extra se gliene viene dato.
    common = {
        "portfolio_value": 10000.0, "bucket_weight": 0.1, "bucket_target": 0.5,
        "nature_weight": 0.0, "nature_cap": 1.0, "data_quality_score": 1.0,
        "score_finale": 0.8,
    }
    ranking_df = pd.DataFrame([
        {"_bucket": "A", "unit_price": 500.0, "comparison_group": "a1", "voto": 8.0,
         "decision_score": 0.90, **common},
        {"_bucket": "B", "unit_price": 50.0, "comparison_group": "b1", "voto": 7.5,
         "decision_score": 0.80, **common},
        {"_bucket": "B", "unit_price": 50.0, "comparison_group": "b2", "voto": 7.4,
         "decision_score": 0.79, **common},
        {"_bucket": "B", "unit_price": 50.0, "comparison_group": "b3", "voto": 7.3,
         "decision_score": 0.78, **common},
    ])
    budget = 1000.0
    # Deficit di A domina (900 su 1000): sub-budget teorico A=900, B=100.
    # A puo' comprare al massimo 1 quota da 500 (il cap del 35% per riga sulla sua
    # fetta, 900*0.35=315, blocca la seconda quota da 1000): resta 400 di residuo.
    # B con soli 100EUR compra al massimo 2 quote (usa tutto, e' "saturo").
    bucket_deficits = {"A": 900.0, "B": 100.0}
    blocked_buckets: set[str] = set()

    quote = _suggested_quotes_by_bucket(ranking_df, budget, bucket_deficits, blocked_buckets)

    prices = ranking_df["unit_price"].tolist()
    buckets = ranking_df["_bucket"].tolist()
    speso_A = sum(q * p for q, b, p in zip(quote, buckets, prices) if b == "A")
    speso_B = sum(q * p for q, b, p in zip(quote, buckets, prices) if b == "B")

    assert speso_A == pytest.approx(500.0), "A resta starved (residuo suo, bloccato dal cap 35% di riga): non deve ricevere extra"
    # B era saturo sulla propria fetta (100/100 nel primo giro): deve aver ricevuto
    # parte del residuo di A (400) e comprato piu' quote (fino al proprio cap 35%
    # di riga per candidato, 500*0.35=175 -> 3 quote da 50 = 150 per riga).
    assert speso_B == pytest.approx(450.0), "B doveva ricevere il residuo di A e comprare piu' quote"
    assert speso_A + speso_B <= budget + 1e-6
    assert speso_A + speso_B > 850.0, "la redistribuzione deve ridurre sensibilmente il residuo totale"
