from __future__ import annotations

import pandas as pd

from core.services.benchmark import (
    benchmark_explanation,
    build_benchmark_transparency_payload,
    resolve_effective_benchmark_components,
)


def test_resolve_blend_automatic_components_from_gov_weight():
    settings = {"benchmarking": {"default_portfolio_benchmark": "Blend automatico"}}
    da = pd.DataFrame(
        [
            {"Tipo": "Titolo di Stato", "Controvalore": 250.0},
            {"Tipo": "ETF Azionario", "Controvalore": 750.0},
        ]
    )

    cfg = resolve_effective_benchmark_components(settings, da)

    assert cfg["mode"] == "blend automatico"
    weights = {item["ticker"]: item["weight"] for item in cfg["components"]}
    assert round(weights["EMB"], 6) == 0.25
    assert round(weights["IWDA.AS"], 6) == 0.75
    assert "proxy" in cfg["method_note"].lower() or "sintetico" in cfg["method_note"].lower()


def test_resolve_custom_benchmark_normalizes_duplicate_components():
    settings = {
        "benchmarking": {
            "custom_enabled": True,
            "custom_name": "Test custom",
            "custom_components": [
                {"ticker": "IWDA.AS", "weight": 0.20},
                {"ticker": "IWDA.AS", "weight": 0.30},
                {"ticker": "EMB", "weight": 0.50},
            ],
        }
    }

    cfg = resolve_effective_benchmark_components(settings, None)

    assert cfg["mode"] == "personalizzato"
    weights = {item["ticker"]: item["weight"] for item in cfg["components"]}
    assert round(weights["IWDA.AS"], 6) == 0.5
    assert round(weights["EMB"], 6) == 0.5


def test_build_benchmark_transparency_payload_adds_metrics_and_cache_state():
    settings = {"benchmarking": {"default_portfolio_benchmark": "60/40 MSCI World / Bond"}}
    data = {
        "benchmark_data": {
            "bench_IWDA.AS": {"2024-01-01": 100.0, "2024-02-01": 105.0},
            "bench_EMB": {"2024-01-01": 100.0, "2024-02-01": 101.0},
        }
    }
    summary_payload = {
        "summary_history": [
            {"data": "01/01/2024", "indice": 100.0},
            {"data": "01/02/2024", "indice": 104.0},
        ],
        "benchmark_history": [
            {"data": "01/01/2024", "indice": 100.0},
            {"data": "01/02/2024", "indice": 102.0},
        ],
        "twr": 0.04,
        "benchmark_return": 0.02,
        "excess_vs_benchmark": 0.02,
        "tracking_error": 0.04,
        "information_ratio": 0.5,
    }

    payload = build_benchmark_transparency_payload(
        data=data,
        settings=settings,
        da_frame=pd.DataFrame(),
        summary_payload=summary_payload,
    )

    assert payload["availability"]["has_benchmark"] is True
    assert payload["metrics"]["excess_return"] == 0.02
    assert len(payload["config"]["components"]) == 2
    assert all(item["points"] == 2 for item in payload["config"]["components"])
    assert not payload["history"].empty
    assert "Benchmark attivo" in benchmark_explanation(payload)


def test_build_instrument_benchmark_matrix_computes_relative_metrics():
    from core.services.benchmark import build_instrument_benchmark_matrix

    data = {
        "strumenti": [
            {"ticker": "SWDA.MI", "nome": "World ETF", "tipo": "ETF"},
            {"ticker": "NO_BENCH", "nome": "Senza benchmark", "tipo": "Altro"},
        ],
        "instrument_master": {
            "SWDA.MI": {
                "ticker": "SWDA.MI",
                "type_raw": "ETF",
                "macro_category": "ETF",
                "benchmark_code": "IWDA.AS",
                "benchmark_label": "MSCI World",
            },
            "NO_BENCH": {
                "ticker": "NO_BENCH",
                "type_raw": "Altro",
                "macro_category": "ALTRO",
                "benchmark_code": None,
                "benchmark_label": None,
            },
        },
        "storico_prezzi": {
            "2024-01-01": {"SWDA.MI": 100.0, "NO_BENCH": 10.0},
            "2024-01-02": {"SWDA.MI": 101.0, "NO_BENCH": 10.2},
            "2024-01-03": {"SWDA.MI": 102.0, "NO_BENCH": 10.4},
            "2024-01-04": {"SWDA.MI": 103.0, "NO_BENCH": 10.5},
            "2024-01-05": {"SWDA.MI": 104.0, "NO_BENCH": 10.7},
            "2024-01-08": {"SWDA.MI": 105.0, "NO_BENCH": 11.0},
            "2024-01-09": {"SWDA.MI": 106.0, "NO_BENCH": 11.1},
            "2024-01-10": {"SWDA.MI": 107.0, "NO_BENCH": 11.2},
            "2024-01-11": {"SWDA.MI": 108.0, "NO_BENCH": 11.3},
            "2024-01-12": {"SWDA.MI": 109.0, "NO_BENCH": 11.4},
            "2024-01-15": {"SWDA.MI": 110.0, "NO_BENCH": 11.5},
            "2024-01-16": {"SWDA.MI": 111.0, "NO_BENCH": 11.6},
            "2024-01-17": {"SWDA.MI": 112.0, "NO_BENCH": 11.7},
            "2024-01-18": {"SWDA.MI": 113.0, "NO_BENCH": 11.8},
            "2024-01-19": {"SWDA.MI": 114.0, "NO_BENCH": 11.9},
            "2024-01-22": {"SWDA.MI": 115.0, "NO_BENCH": 12.0},
            "2024-01-23": {"SWDA.MI": 116.0, "NO_BENCH": 12.1},
            "2024-01-24": {"SWDA.MI": 117.0, "NO_BENCH": 12.2},
            "2024-01-25": {"SWDA.MI": 118.0, "NO_BENCH": 12.3},
            "2024-01-26": {"SWDA.MI": 119.0, "NO_BENCH": 12.4},
            "2024-01-29": {"SWDA.MI": 120.0, "NO_BENCH": 12.5},
        },
        "benchmark_data": {
            "bench_IWDA.AS": {
                "2024-01-01": 100.0,
                "2024-01-02": 101.0,
                "2024-01-03": 102.0,
                "2024-01-04": 103.0,
                "2024-01-05": 104.0,
                "2024-01-08": 105.0,
                "2024-01-09": 106.0,
                "2024-01-10": 107.0,
                "2024-01-11": 108.0,
                "2024-01-12": 109.0,
                "2024-01-15": 110.0,
                "2024-01-16": 111.0,
                "2024-01-17": 112.0,
                "2024-01-18": 113.0,
                "2024-01-19": 114.0,
                "2024-01-22": 115.0,
                "2024-01-23": 116.0,
                "2024-01-24": 117.0,
                "2024-01-25": 118.0,
                "2024-01-26": 119.0,
                "2024-01-29": 120.0,
            }
        },
        # "In portafoglio" ora si calcola dalle quote reali (held_tickers):
        # entrambi vanno acquistati nel registro perche' compaiano in matrix.
        "registro_eventi": [
            {"tipo_evento": "ACQUISTO", "ticker": "SWDA.MI", "quantita": 10, "prezzo_unitario": 100.0, "data": "2024-01-01"},
            {"tipo_evento": "ACQUISTO", "ticker": "NO_BENCH", "quantita": 10, "prezzo_unitario": 10.0, "data": "2024-01-01"},
        ],
    }
    da = pd.DataFrame([{"Ticker": "SWDA.MI", "Controvalore": 1000.0}])

    matrix = build_instrument_benchmark_matrix(data, da)

    swda = matrix[matrix["ticker"] == "SWDA.MI"].iloc[0]
    assert swda["benchmark_ticker"] == "IWDA.AS"
    assert swda["extra_return"] == 0.0
    assert swda["compatibility_label"] in {"Alta", "Media"}
    assert swda["controvalore"] == 1000.0
    no_bench = matrix[matrix["ticker"] == "NO_BENCH"].iloc[0]
    assert no_bench["compatibility_label"] == "Senza benchmark"


def test_build_instrument_benchmark_matrix_excludes_closed_instruments():
    """Uno strumento venduto per intero non deve comparire in matrix, anche
    se il campo stato dice ancora 'aperto' (disallineato rispetto alla
    realta') — il criterio e' la quantita' effettiva calcolata dagli eventi,
    non il campo stato dichiarato sullo strumento."""
    from core.services.benchmark import build_instrument_benchmark_matrix

    data = {
        "strumenti": [
            {"ticker": "SWDA.MI", "nome": "World ETF", "tipo": "ETF", "stato": "aperto"},
            {"ticker": "VENDUTO.MI", "nome": "ETF venduto", "tipo": "ETF", "stato": "aperto"},
        ],
        "instrument_master": {},
        "registro_eventi": [
            {"tipo_evento": "ACQUISTO", "ticker": "SWDA.MI", "quantita": 10, "prezzo_unitario": 100.0, "data": "2024-01-01"},
            {"tipo_evento": "ACQUISTO", "ticker": "VENDUTO.MI", "quantita": 5, "prezzo_unitario": 50.0, "data": "2024-01-01"},
            {"tipo_evento": "VENDITA", "ticker": "VENDUTO.MI", "quantita": 5, "prezzo_unitario": 50.5, "data": "2024-01-02"},
        ],
        "storico_prezzi": {
            "2024-01-01": {"SWDA.MI": 100.0, "VENDUTO.MI": 50.0},
            "2024-01-02": {"SWDA.MI": 101.0, "VENDUTO.MI": 50.5},
        },
        "benchmark_data": {},
    }
    da = pd.DataFrame([{"Ticker": "SWDA.MI", "Controvalore": 1000.0}])

    matrix = build_instrument_benchmark_matrix(data, da)

    assert "SWDA.MI" in set(matrix["ticker"])
    assert "VENDUTO.MI" not in set(matrix["ticker"])


def test_gov_instrument_gets_bond_index_fallback_when_master_has_no_benchmark():
    from core.services.benchmark import build_instrument_benchmark_matrix

    data = {
        "strumenti": [
            {"ticker": "BTP-0826", "nome": "BTP agosto 2026", "tipo": "GOV"},
        ],
        "instrument_master": {
            "BTP-0826": {
                "ticker": "BTP-0826",
                "type_raw": "GOV",
                "macro_category": "GOV",
                "benchmark_code": None,
                "benchmark_label": None,
            },
        },
        "storico_prezzi": {
            "2024-01-01": {"BTP-0826": 100.0},
            "2024-01-02": {"BTP-0826": 100.1},
        },
        "benchmark_data": {},
        "registro_eventi": [
            {"tipo_evento": "ACQUISTO", "ticker": "BTP-0826", "quantita": 10, "prezzo_unitario": 100.0, "data": "2024-01-01"},
        ],
    }
    da = pd.DataFrame([{"Ticker": "BTP-0826", "Controvalore": 1000.0}])

    matrix = build_instrument_benchmark_matrix(data, da)

    row = matrix[matrix["ticker"] == "BTP-0826"].iloc[0]
    assert row["benchmark_ticker"] == "BND"
    assert row["benchmark_label"] == "Bond Index"
    assert row["benchmark_source"] in {"macro-categoria", "macro categoria", "tipo strumento", "tipo sintetico"}
    assert row["compatibility_label"] != "Senza benchmark"


def test_central_registry_assigns_gold_and_miners_benchmarks():
    from core.benchmark_registry import resolve_instrument_benchmark

    gold = resolve_instrument_benchmark({"ticker": "GOLD.MI", "isin": "FR0013416716", "tipo": "ETC oro"}, prefer_master=False)
    miners = resolve_instrument_benchmark({"ticker": "XGDU.MI", "tipo": "ETF minerari auriferi"}, prefer_master=False)

    assert gold.ticker == "GLD"
    assert "Gold" in gold.label
    assert miners.ticker == "GDX"
    assert "Miner" in miners.label


def test_famamw_usa_proxy_metalli_e_non_msci_world():
    """FAMAMW.MI segue davvero 'MSCI World Metals and Mining' (dato arricchito
    reale), non l'azionario globale generico: la regola per ticker deve
    riflettere il vero focus del fondo, non il nome commerciale."""
    from core.benchmark_registry import resolve_instrument_benchmark

    result = resolve_instrument_benchmark(
        {"ticker": "FAMAMW.MI", "isin": "IE000EE3Q489", "tipo": "ETF Az. Globale"},
        prefer_master=False,
    )

    assert result.ticker == "PICK"


def test_instrument_matrix_uses_central_registry_when_master_is_empty():
    from core.services.benchmark import build_instrument_benchmark_matrix

    data = {
        "strumenti": [
            {"ticker": "GOLD.MI", "nome": "ETC oro", "tipo": "ETC oro"},
            {"ticker": "XGDU.MI", "nome": "Gold miners", "tipo": "ETF minerari auriferi"},
        ],
        "instrument_master": {},
        "storico_prezzi": {},
        "benchmark_data": {},
        "registro_eventi": [
            {"tipo_evento": "ACQUISTO", "ticker": "GOLD.MI", "quantita": 10, "prezzo_unitario": 50.0, "data": "2024-01-01"},
            {"tipo_evento": "ACQUISTO", "ticker": "XGDU.MI", "quantita": 10, "prezzo_unitario": 30.0, "data": "2024-01-01"},
        ],
    }

    matrix = build_instrument_benchmark_matrix(data, pd.DataFrame())
    by_ticker = matrix.set_index("ticker")

    assert by_ticker.loc["GOLD.MI", "benchmark_ticker"] == "GLD"
    assert by_ticker.loc["GOLD.MI", "benchmark_source"] == "ticker diretto"
    assert by_ticker.loc["XGDU.MI", "benchmark_ticker"] == "GDX"


def test_enriched_benchmark_india_sceglie_proxy_specifico():
    from core.benchmark_registry import resolve_instrument_benchmark

    result = resolve_instrument_benchmark(
        {"ticker": "FLXI.MI", "isin": "IE00BHZRQZ17", "tipo": "ETF", "benchmark": "FTSE India 30/18 Capped"},
        prefer_master=False,
    )

    assert result.ticker == "INDA"
    assert result.source == "benchmark arricchito"


def test_enriched_benchmark_bitcoin_sceglie_proxy_specifico():
    from core.benchmark_registry import resolve_instrument_benchmark

    result = resolve_instrument_benchmark(
        {"ticker": "IB1T.PA", "isin": "XS2940466316", "tipo": "ETC", "benchmark": "Bitcoin"},
        prefer_master=False,
    )

    assert result.ticker == "BTC-USD"


def test_enriched_benchmark_compound_sceglie_il_pattern_piu_specifico():
    """'MSCI World Information Technology' deve scegliere il proxy tecnologia,
    non il generico MSCI World, anche se la stringa contiene entrambi (dato
    reale osservato per XDWT.MI)."""
    from core.benchmark_registry import resolve_instrument_benchmark

    result = resolve_instrument_benchmark(
        {"ticker": "XDWT.MI", "isin": "IE00BM67HT60", "tipo": "ETF IA",
         "benchmark": "MSCI World Information Technology 20/35 Custom"},
        prefer_master=False,
    )

    assert result.ticker == "QQQ"


def test_enriched_benchmark_senza_corrispondenza_ricade_su_tipo():
    from core.benchmark_registry import resolve_instrument_benchmark

    result = resolve_instrument_benchmark(
        {"ticker": "XYZ.MI", "tipo": "ETF Az. Globale", "benchmark": "Un indice mai sentito 123"},
        prefer_master=False,
    )

    assert result.ticker == "IWDA.AS"
    assert result.source == "tipo strumento"


def test_regola_ticker_esplicita_vince_su_benchmark_arricchito():
    from core.benchmark_registry import resolve_instrument_benchmark

    result = resolve_instrument_benchmark(
        {"ticker": "SWDA.MI", "isin": "IE00B4L5Y983", "tipo": "ETF", "benchmark": "FTSE India 30/18 Capped"},
        prefer_master=False,
    )

    assert result.ticker == "IWDA.AS"  # regola esplicita per SWDA.MI, non il pattern India
    assert result.source == "ticker diretto"


def test_campo_benchmark_assente_comportamento_identico_a_oggi():
    from core.benchmark_registry import resolve_instrument_benchmark

    result = resolve_instrument_benchmark(
        {"ticker": "XYZ.MI", "tipo": "ETF Az. Globale"},
        prefer_master=False,
    )

    assert result.ticker == "IWDA.AS"
    assert result.source == "tipo strumento"


def test_enriched_benchmark_bloomberg_bond_non_sceglie_commodity():
    """Un bond ETF con benchmark 'Bloomberg Global Aggregate Bond' non deve
    ricadere sul proxy commodity (DJP): il pattern 'bloomberg' era troppo
    ampio, perche' Bloomberg brand-izza anche molti indici obbligazionari.
    Senza un pattern obbligazionario in questo livello, deve ricadere sul
    fallback per tipo strumento."""
    from core.benchmark_registry import resolve_instrument_benchmark

    result = resolve_instrument_benchmark(
        {"ticker": "NEWBOND.MI", "tipo": "Fondo Obbligazionario",
         "benchmark": "Bloomberg Global Aggregate Bond"},
        prefer_master=False,
    )

    assert result.ticker == "BND"
    assert result.ticker != "DJP"


def test_master_benchmark_ignored_without_explicit_user_edited_flag():
    """Il congelamento e' rimosso: un benchmark_code presente in
    instrument_master ma SENZA benchmark_user_edited=True non deve piu'
    avere priorita' - il calcolo deve essere sempre fresco."""
    from core.benchmark_registry import resolve_instrument_benchmark

    master = {"ticker": "SWDA.MI", "benchmark_code": "VECCHIO.STALE", "benchmark_label": "Stale", "manual_overrides": {}}
    result = resolve_instrument_benchmark(ticker="SWDA.MI", master_entry=master, prefer_master=True)
    assert result.ticker != "VECCHIO.STALE"  # deve ricalcolare fresco (regola ticker esplicita)
    assert result.ticker == "IWDA.AS"  # BENCHMARK_BY_TICKER["SWDA.MI"]


def test_master_benchmark_used_when_explicitly_user_edited():
    from core.benchmark_registry import resolve_instrument_benchmark

    master = {
        "ticker": "SWDA.MI",
        "manual_overrides": {"sator": {"benchmark_code": "CUSTOM.BM", "benchmark_label": "Custom", "benchmark_user_edited": True}},
    }
    result = resolve_instrument_benchmark(ticker="SWDA.MI", master_entry=master, prefer_master=True)
    assert result.ticker == "CUSTOM.BM"
    assert result.source == "anagrafica"


def test_enriched_benchmark_gold_miners_sceglie_gdx_non_gld():
    """Un ETF gold-miners con benchmark 'NYSE Arca Gold Miners' deve
    ricevere il proxy minerario (GDX), non l'oro fisico (GLD): il pattern
    bare 'gold' intercettava anche gli indici di gold-miners prima di
    arrivare all'euristica tipo piu' specifica."""
    from core.benchmark_registry import resolve_instrument_benchmark

    result = resolve_instrument_benchmark(
        {"ticker": "NEWMINERS.MI", "tipo": "ETF", "benchmark": "NYSE Arca Gold Miners"},
        prefer_master=False,
    )

    assert result.ticker == "GDX"
