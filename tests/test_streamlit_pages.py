from __future__ import annotations

from pathlib import Path

import pytest

from test_streamlit_smoke import _format_exceptions, _run_app, _session_get

EXPECTED_PAGES: list[tuple[str, str]] = [
    ("quotazioni", "Quotazioni"),
    ("portafoglio", "Portafoglio"),
    ("operazioni", "Operazioni"),
    ("cruscotti", "Cruscotti"),
    ("summary", "Summary"),
    ("confronto", "Confronto"),
    ("pianificazione", "Pianificazione"),
    ("ai", "AI"),
    ("gestione_dati", "Dati"),
    ("impostazioni", "Setup"),
]


def _assert_no_exceptions(app) -> None:
    assert not list(app.exception), _format_exceptions(app)


def test_page_registry_contract_is_stable(app_file: Path):
    """
    Test rapido sul contratto della navigazione custom.

    Non esegue Streamlit: controlla che il registro pagine in app.py contenga
    ancora le 9 sezioni attese. Se una futura modifica rinomina/rimuove una
    pagina, il test lo segnala esplicitamente.
    """
    source = app_file.read_text(encoding="utf-8")

    assert "_PAGE_DEFS" in source
    assert "_PAGE_COUNT = len(_PAGE_DEFS)" in source
    for page_id, label in EXPECTED_PAGES:
        assert f'PageDef("{page_id}"' in source
        assert label in source


def test_all_standard_tabs_render_and_end_on_last_page(portfolio_test_env, app_file: Path):
    """
    La modalità standard dell'app renderizza tutte le tab.

    Il controllo su current_page_id == impostazioni intercetta regressioni nel
    loop di rendering delle pagine senza dover cliccare elementi distruttivi.
    """
    app = _run_app(app_file, timeout=120)

    _assert_no_exceptions(app)
    assert _session_get(app, "total_pages") == len(EXPECTED_PAGES)
    assert _session_get(app, "current_page_total") == len(EXPECTED_PAGES)
    assert _session_get(app, "current_page_id") == EXPECTED_PAGES[-1][0]


@pytest.mark.parametrize(
    ("flag_name", "expected_active_tab"),
    [
        ("goto_tab_quotazioni", 0),
        ("goto_tab_operazioni", 2),
    ],
)
def test_startup_navigation_flags_are_safe(portfolio_test_env, app_file: Path, flag_name: str, expected_active_tab: int):
    """
    Verifica le scorciatoie di navigazione impostate da sidebar/azioni interne.

    Il test non clicca pulsanti: inizializza solo il session_state come farebbe
    l'app prima di un rerun e controlla che il render rimanga pulito.
    """
    app = _run_app(app_file, initial_state={flag_name: True})

    _assert_no_exceptions(app)
    assert _session_get(app, "active_tab") == expected_active_tab
    assert _session_get(app, flag_name, None) is None


@pytest.mark.parametrize("active_tab", [-50, 999, "non-numerico"])
def test_invalid_active_tab_values_do_not_break_render(portfolio_test_env, app_file: Path, active_tab):
    """
    Un active_tab sporco non deve rompere il caricamento dell'app.

    È un caso realistico dopo refactor, aggiornamenti di session_state o riprese
    da vecchie sessioni browser.
    """
    app = _run_app(app_file, initial_state={"active_tab": active_tab})

    _assert_no_exceptions(app)
    assert _session_get(app, "total_pages") == len(EXPECTED_PAGES)
    assert _session_get(app, "current_page_id") in {page_id for page_id, _ in EXPECTED_PAGES}


def test_main_tabs_remain_passive_and_non_stateful(project_root: Path):
    source = (project_root / "ui" / "runtime_pages.py").read_text(encoding="utf-8")
    assert "on_change" not in source
    assert "default=" not in source
    assert ".open" not in source
    assert 'key="portfolio_main_tabs' not in source


def test_quote_refresh_does_not_force_second_full_rerun(project_root: Path):
    source = (project_root / "ui" / "sidebar.py").read_text(encoding="utf-8")
    marker = 'st.session_state["goto_tab_quotazioni"] = True'
    assert marker in source
    tail = source[source.index(marker):]
    assert "st.rerun()" not in tail


def test_quote_refresh_same_price_after_midnight_is_not_data_change(project_root: Path):
    """Un refresh dopo mezzanotte non deve creare una nuova data se il prezzo e' invariato."""
    source = (project_root / "ui" / "sidebar.py").read_text(encoding="utf-8")

    assert "reference_px_for_change" in source
    assert "current_hist_before" in source
    assert "latest_hist_px" in source
    assert "candidate_today_prices" in source
    assert "_quote_value_materially_changed" in source
    assert "pending_instrument_updates" in source
    assert "if quotes_data_changed:" in source
    assert "Refresh quotazioni senza variazioni materiali" in source
    assert "refresh_benchmark_cache(data)" in source


def test_quote_refresh_does_not_mutate_instruments_before_material_commit(project_root: Path):
    source = (project_root / "ui" / "sidebar.py").read_text(encoding="utf-8")
    elif_start = source.index("elif pr:")
    apply_start = source.index("if quotes_data_changed:", elif_start)
    elif_block = source[elif_start:apply_start]

    assert 's["prezzo"] = pr' not in elif_block
    assert 's["fonte"] = src' not in elif_block
    assert 's["aggiornato"] = price_date or ts' not in elif_block
    assert 'pending_instrument_updates.append' in elif_block


def test_sator_refresh_button_precedes_reference_summary(project_root: Path):
    """Il tasto Aggiorna deve comparire prima della card Fotografia di
    riferimento e forzare un rerun esplicito, cosi' che load_sator_decisions()
    (gia' senza cache, legge sempre da disco) venga rieseguito e mostri
    l'ultima fotografia salvata anche se l'utente l'ha registrata da un
    altro processo (pagina SATOR standalone su porta 8502)."""
    source = (project_root / "ui" / "pages" / "pianificazione.py").read_text(encoding="utf-8")
    button_marker = 'st.button("🔄 Aggiorna", key="sator_refresh_snapshot"'
    call_marker = '_render_sator_reference_summary(latest_decision, theme, data)'
    assert button_marker in source
    assert call_marker in source
    button_idx = source.index(button_marker)
    call_idx = source.index(call_marker)
    assert button_idx < call_idx, "Il tasto Aggiorna deve comparire prima della card"
    tail = source[button_idx:call_idx]
    assert "st.rerun()" in tail
