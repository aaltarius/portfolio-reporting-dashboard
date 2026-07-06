"""
TDD — Grafico performance normalizzata sovrapposta.

Funzioni target:
    build_normalized_performance_chart(storico_prezzi, tickers, start_date) -> go.Figure
        in ui/charts/benchmark.py

    get_all_historical_tickers(data) -> list[dict]
        in ui/charts/benchmark.py

build_normalized_performance_chart:
    Dato storico_prezzi e una lista di ticker, normalizza ogni serie
    al punto zero sulla start_date (rendimento % da quella data).
    Ogni ticker diventa una linea sovrapposta.

get_all_historical_tickers:
    Ritorna tutti i ticker mai comparsi in storico_prezzi, con flag
    "active" (in strumenti) o "sold" (non più in portafoglio).
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import pytest


# ─── fixture dati minimali ────────────────────────────────────────────────────

STORICO = {
    "2026-01-02": {"SWDA": 100.0, "BTP": 98.0},
    "2026-01-05": {"SWDA": 105.0, "BTP": 97.0},
    "2026-01-06": {"SWDA": 110.0, "BTP": 99.0},
    "2026-01-07": {"SWDA": 108.0, "BTP": 100.5},
}

STORICO_CON_VENDUTO = {
    "2026-01-02": {"SWDA": 100.0, "VWCE": 50.0},
    "2026-01-05": {"SWDA": 105.0},           # VWCE venduto prima
    "2026-01-06": {"SWDA": 110.0},
}


def _make_data(strumenti=None, storico=None):
    return {
        "strumenti": strumenti or [{"ticker": "SWDA", "tipo": "ETF", "prezzo": 110.0}],
        "storico_prezzi": storico or STORICO,
        "operazioni": [],
    }


# ─── get_all_historical_tickers ───────────────────────────────────────────────

class TestGetAllHistoricalTickers:

    def _call(self, data):
        from ui.charts.benchmark import get_all_historical_tickers
        return get_all_historical_tickers(data)

    def test_empty_data_returns_empty_list(self):
        result = self._call({"strumenti": [], "storico_prezzi": {}})
        assert result == []

    def test_active_ticker_flagged_as_active(self):
        data = _make_data(
            strumenti=[{"ticker": "SWDA", "tipo": "ETF", "prezzo": 110.0}],
            storico={"2026-01-02": {"SWDA": 100.0}},
        )
        result = self._call(data)
        tickers = {r["ticker"]: r["active"] for r in result}
        assert "SWDA" in tickers
        assert tickers["SWDA"] is True

    def test_sold_ticker_flagged_as_sold(self):
        data = _make_data(
            strumenti=[{"ticker": "SWDA", "tipo": "ETF", "prezzo": 110.0}],
            storico=STORICO_CON_VENDUTO,
        )
        result = self._call(data)
        tickers = {r["ticker"]: r["active"] for r in result}
        assert "VWCE" in tickers
        assert tickers["VWCE"] is False

    def test_closed_instrument_not_flagged_as_active(self):
        """Uno strumento con stato 'chiuso' ha ancora un record in strumenti
        (l'anagrafica non sparisce quando vendi tutto), ma non deve risultare
        'active': non possiedi più quote, quindi per l'utente è fuori
        portafoglio esattamente come un ticker mai posseduto."""
        data = _make_data(
            strumenti=[
                {"ticker": "SWDA", "tipo": "ETF", "prezzo": 110.0, "stato": "aperto"},
                {"ticker": "VWCE", "tipo": "ETF", "prezzo": 50.0, "stato": "chiuso"},
            ],
            storico=STORICO_CON_VENDUTO,
        )
        result = self._call(data)
        tickers = {r["ticker"]: r["active"] for r in result}
        assert tickers["SWDA"] is True
        assert tickers["VWCE"] is False

    def test_mix_active_and_sold(self):
        data = _make_data(
            strumenti=[{"ticker": "SWDA", "tipo": "ETF", "prezzo": 110.0}],
            storico=STORICO_CON_VENDUTO,
        )
        result = self._call(data)
        tickers = {r["ticker"]: r["active"] for r in result}
        assert tickers["SWDA"] is True
        assert tickers["VWCE"] is False

    def test_no_duplicate_tickers(self):
        storico = {
            "2026-01-02": {"SWDA": 100.0},
            "2026-01-03": {"SWDA": 101.0},
        }
        data = _make_data(
            strumenti=[{"ticker": "SWDA", "tipo": "ETF", "prezzo": 101.0}],
            storico=storico,
        )
        result = self._call(data)
        tickers = [r["ticker"] for r in result]
        assert len(tickers) == len(set(tickers)), "Nessun ticker duplicato"

    def test_result_has_ticker_and_active_keys(self):
        data = _make_data()
        result = self._call(data)
        for r in result:
            assert "ticker" in r
            assert "active" in r

    def test_missing_strumenti_key_returns_empty(self):
        data = {"storico_prezzi": {"2026-01-02": {"SWDA": 100.0}}}
        result = self._call(data)
        # Senza strumenti tutti i ticker sono "sold" ma la funzione non deve crashare
        assert isinstance(result, list)


# ─── build_normalized_performance_chart ───────────────────────────────────────

class TestBuildNormalizedPerformanceChart:

    def _call(self, storico, tickers, start_date):
        from ui.charts.benchmark import build_normalized_performance_chart
        return build_normalized_performance_chart(storico, tickers, start_date)

    # ── Smoke: ritorna sempre un Figure ──

    def test_returns_go_figure(self):
        fig = self._call(STORICO, ["SWDA"], "2026-01-02")
        assert isinstance(fig, go.Figure)

    def test_empty_storico_returns_figure(self):
        fig = self._call({}, ["SWDA"], "2026-01-02")
        assert isinstance(fig, go.Figure)

    def test_no_tickers_returns_figure(self):
        fig = self._call(STORICO, [], "2026-01-02")
        assert isinstance(fig, go.Figure)

    # ── Normalizzazione ──

    def test_series_starts_at_zero_on_start_date(self):
        """Il primo punto di ogni serie normalizzata deve essere 0.0."""
        fig = self._call(STORICO, ["SWDA"], "2026-01-02")
        trace = fig.data[0]
        assert abs(float(trace.y[0])) < 1e-9, f"Primo punto deve essere 0.0, got {trace.y[0]}"

    def test_normalized_value_is_percent_return(self):
        """Con prezzo iniziale 100 e finale 110, il valore normalizzato deve essere +10%."""
        fig = self._call(STORICO, ["SWDA"], "2026-01-02")
        trace = fig.data[0]
        # Ultimo valore SWDA: 108.0, iniziale: 100.0 → (108/100 - 1) = +8%
        last_val = float(trace.y[-1])
        assert abs(last_val - 0.08) < 1e-9, f"Expected +8%, got {last_val:.6f}"

    def test_declining_series_has_negative_values(self):
        """Una serie che scende deve avere valori negativi dopo la normalizzazione."""
        storico = {
            "2026-01-02": {"BTP": 100.0},
            "2026-01-05": {"BTP": 95.0},
        }
        fig = self._call(storico, ["BTP"], "2026-01-02")
        trace = fig.data[0]
        last_val = float(trace.y[-1])
        assert last_val < 0.0, f"Serie in discesa deve avere valori negativi, got {last_val}"

    def test_two_tickers_produce_two_traces(self):
        fig = self._call(STORICO, ["SWDA", "BTP"], "2026-01-02")
        assert len(fig.data) == 2

    def test_trace_names_match_tickers(self):
        fig = self._call(STORICO, ["SWDA", "BTP"], "2026-01-02")
        names = {t.name for t in fig.data}
        assert "SWDA" in names
        assert "BTP" in names

    def test_missing_ticker_in_storico_is_skipped(self):
        """Un ticker non presente in storico non genera tracce né crash."""
        fig = self._call(STORICO, ["SWDA", "XXX_NON_ESISTE"], "2026-01-02")
        names = [t.name for t in fig.data]
        assert "SWDA" in names
        assert "XXX_NON_ESISTE" not in names

    def test_start_date_before_first_available_uses_first_date(self):
        """Se start_date è prima della prima data disponibile, parte dalla prima data."""
        fig = self._call(STORICO, ["SWDA"], "2025-01-01")  # nessuna data disponibile
        # Non deve crashare, e se ha tracce il primo punto è 0.0
        if fig.data:
            trace = fig.data[0]
            assert abs(float(trace.y[0])) < 1e-9

    def test_start_date_in_middle_normalizes_from_that_date(self):
        """Con start_date nel mezzo, normalizza dalla data più vicina disponibile."""
        # SWDA = 105.0 il 2026-01-05, 110.0 il 2026-01-06, 108.0 il 2026-01-07
        # (108 / 105 - 1) ≈ +0.02857
        fig = self._call(STORICO, ["SWDA"], "2026-01-05")
        trace = fig.data[0]
        assert abs(float(trace.y[0])) < 1e-9, "Primo punto deve essere 0.0"
        last_val = float(trace.y[-1])
        expected = (108.0 / 105.0) - 1.0
        assert abs(last_val - expected) < 1e-9, f"Expected {expected:.6f}, got {last_val:.6f}"

    def test_single_data_point_returns_figure_without_crash(self):
        storico = {"2026-01-02": {"SWDA": 100.0}}
        fig = self._call(storico, ["SWDA"], "2026-01-02")
        assert isinstance(fig, go.Figure)
        if fig.data:
            trace = fig.data[0]
            assert abs(float(trace.y[0])) < 1e-9


# ─── build_normalized_performance_chart — modalità align_starts ───────────────

class TestBuildNormalizedPerformanceChartAlignStarts:
    """
    Con align_starts=True l'asse X diventa "giorni dal punto zero" (int),
    non date di calendario. Ogni serie parte da 0 al giorno 0, permettendo
    il confronto visivo indipendentemente dalla data di ingresso.

    Esempio:
        SWDA ha storico dal 2020-01-02, BTP dal 2022-03-15.
        Con align_starts=True entrambi partono a (giorno=0, rendimento=0%).
        L'asse X mostra 0, 1, 2, ... (giorni trascorsi dalla prima data utile).
    """

    STORICO_ASIMMETRICO = {
        "2026-01-02": {"SWDA": 100.0},                      # SWDA inizia prima
        "2026-01-05": {"SWDA": 105.0, "BTP": 200.0},        # BTP inizia dopo
        "2026-01-06": {"SWDA": 110.0, "BTP": 220.0},
        "2026-01-07": {"SWDA": 108.0, "BTP": 210.0},
    }

    def _call(self, storico, tickers, start_date, align_starts=True):
        from ui.charts.benchmark import build_normalized_performance_chart
        return build_normalized_performance_chart(storico, tickers, start_date, align_starts=align_starts)

    # ── Smoke ──

    def test_align_starts_returns_go_figure(self):
        fig = self._call(STORICO, ["SWDA"], "2026-01-02")
        assert isinstance(fig, go.Figure)

    def test_align_starts_empty_storico_returns_figure(self):
        fig = self._call({}, ["SWDA"], "2026-01-02")
        assert isinstance(fig, go.Figure)

    # ── Asse X intero (giorni) ──

    def test_x_axis_is_integer_days(self):
        """Con align_starts=True, i valori x sono interi (0, 1, 2, ...)."""
        fig = self._call(STORICO, ["SWDA"], "2026-01-02")
        assert len(fig.data) == 1
        trace = fig.data[0]
        for val in trace.x:
            assert isinstance(val, (int,)), f"x deve essere int, got {type(val)}: {val}"

    def test_x_starts_at_zero(self):
        """Ogni serie deve iniziare da x=0."""
        fig = self._call(STORICO, ["SWDA", "BTP"], "2026-01-02")
        for trace in fig.data:
            assert int(trace.x[0]) == 0, f"Trace {trace.name}: x[0] deve essere 0, got {trace.x[0]}"

    # ── Normalizzazione y ──

    def test_y_starts_at_zero(self):
        """Ogni serie deve iniziare da y=0.0."""
        fig = self._call(STORICO, ["SWDA", "BTP"], "2026-01-02")
        for trace in fig.data:
            assert abs(float(trace.y[0])) < 1e-9, f"Trace {trace.name}: y[0] deve essere 0.0"

    def test_y_values_are_percent_return_from_own_start(self):
        """BTP: 200 → 220 → 210. Rendimenti: 0%, +10%, +5%."""
        fig = self._call(self.STORICO_ASIMMETRICO, ["BTP"], "2026-01-02")
        trace = fig.data[0]
        assert abs(float(trace.y[0])) < 1e-9
        assert abs(float(trace.y[1]) - 0.10) < 1e-9, f"Expected +10%, got {trace.y[1]}"
        assert abs(float(trace.y[2]) - 0.05) < 1e-9, f"Expected +5%, got {trace.y[2]}"

    # ── Serie con start asimmetriche ──

    def test_series_start_from_own_first_date_ignoring_calendar(self):
        """
        SWDA ha 4 punti (dal 2026-01-02), BTP ha 3 punti (dal 2026-01-05).
        Con align_starts, SWDA x=[0,1,2,3], BTP x=[0,1,2].
        Lunghezze diverse: non è un errore.
        """
        fig = self._call(self.STORICO_ASIMMETRICO, ["SWDA", "BTP"], "2026-01-02")
        traces = {t.name: t for t in fig.data}
        assert "SWDA" in traces
        assert "BTP" in traces
        assert len(traces["SWDA"].x) == 4
        assert len(traces["BTP"].x) == 3

    def test_align_starts_ignores_start_date_for_series_with_earlier_data(self):
        """
        Con align_starts=True la start_date serve solo come filtro minimo
        (non rimuove dati precedenti — ogni serie usa tutta la propria storia).
        In questo test SWDA ha dati dal 2026-01-02, start_date=2026-01-05:
        con align_starts il comportamento di riferimento è la PRIMA data della
        serie stessa (2026-01-02), non la start_date.
        """
        fig = self._call(self.STORICO_ASIMMETRICO, ["SWDA"], "2026-01-05")
        trace = fig.data[0]
        # SWDA ha 4 punti totali: deve partire da x=0, y=0 dalla sua prima data
        assert len(trace.x) == 4, f"SWDA deve usare tutti i 4 punti, got {len(trace.x)}"
        assert int(trace.x[0]) == 0
        assert abs(float(trace.y[0])) < 1e-9

    # ── align_starts=False invariato ──

    def test_false_align_uses_calendar_dates(self):
        """align_starts=False (default) usa date di calendario come x."""
        fig = self._call(STORICO, ["SWDA"], "2026-01-02", align_starts=False)
        trace = fig.data[0]
        import pandas as pd
        assert isinstance(trace.x[0], pd.Timestamp), f"x[0] deve essere Timestamp, got {type(trace.x[0])}"


# ─── resolve_period_start_date ────────────────────────────────────────────────

class TestResolvePeriodStartDate:
    """
    resolve_period_start_date(sorted_dates, period) -> str

    Calcola la start_date a partire dall'ultima data disponibile nello storico
    e dal periodo richiesto ("1M", "3M", "6M", "1A", "3A", "Tutto").

    Restituisce una stringa ISO "YYYY-MM-DD".
    "Tutto" restituisce la prima data disponibile.
    Se non ci sono date disponibili, restituisce "".
    """

    def _call(self, sorted_dates, period):
        from ui.charts.benchmark import resolve_period_start_date
        return resolve_period_start_date(sorted_dates, period)

    DATES = [
        "2023-01-02", "2023-06-01", "2024-01-02",
        "2024-06-01", "2025-01-02", "2025-06-01",
        "2026-01-02", "2026-06-13",  # ultima
    ]

    def test_tutto_returns_first_date(self):
        result = self._call(self.DATES, "Tutto")
        assert result == "2023-01-02"

    def test_empty_dates_returns_empty_string(self):
        result = self._call([], "1M")
        assert result == ""

    def test_1m_returns_date_one_month_before_last(self):
        # Ultima data: 2026-06-13 → -1 mese → 2026-05-13
        result = self._call(self.DATES, "1M")
        assert result == "2026-05-13"

    def test_3m_returns_date_three_months_before_last(self):
        # 2026-06-13 → -3 mesi → 2026-03-13
        result = self._call(self.DATES, "3M")
        assert result == "2026-03-13"

    def test_6m_returns_date_six_months_before_last(self):
        # 2026-06-13 → -6 mesi → 2025-12-13
        result = self._call(self.DATES, "6M")
        assert result == "2025-12-13"

    def test_1a_returns_date_one_year_before_last(self):
        # 2026-06-13 → -1 anno → 2025-06-13
        result = self._call(self.DATES, "1A")
        assert result == "2025-06-13"

    def test_3a_returns_date_three_years_before_last(self):
        # 2026-06-13 → -3 anni → 2023-06-13
        result = self._call(self.DATES, "3A")
        assert result == "2023-06-13"

    def test_result_never_before_first_available_date(self):
        # Con date brevi (solo 2 mesi), "1A" non può andare prima della prima data
        short_dates = ["2026-05-01", "2026-06-13"]
        result = self._call(short_dates, "1A")
        # Deve clampare alla prima data disponibile
        assert result >= "2026-05-01"

    def test_returns_iso_string(self):
        result = self._call(self.DATES, "3M")
        assert len(result) == 10
        parts = result.split("-")
        assert len(parts) == 3 and len(parts[0]) == 4
