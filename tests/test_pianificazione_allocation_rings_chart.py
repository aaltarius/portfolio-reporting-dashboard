from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import plotly.graph_objects as go
import pytest

from ui.charts.pianificazione import build_allocation_rings_chart


def _theme():
    return SimpleNamespace()


def _rings_df():
    return pd.DataFrame([
        {"ticker": "SWDA.MI", "name": "iShares Core MSCI World", "bucket": "Core", "natura": "Azionario globale core", "value": 600.0},
        {"ticker": "VWCE.MI", "name": "Vanguard All-World", "bucket": "Core", "natura": "Azionario globale core", "value": 300.0},
        {"ticker": "XEON.MI", "name": "Xtrackers Overnight", "bucket": "Difensivo", "natura": "Liquidità", "value": 100.0},
    ])


class TestBuildAllocationRingsChart:

    def test_empty_frame_returns_figure_without_traces(self):
        fig = build_allocation_rings_chart(pd.DataFrame(), {}, _theme())
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 0

    def test_two_pie_traces(self):
        fig = build_allocation_rings_chart(_rings_df(), {}, _theme())
        assert len(fig.data) == 2
        assert all(isinstance(t, go.Pie) for t in fig.data)

    def test_inner_ring_is_bucket_totals_in_fixed_order(self):
        fig = build_allocation_rings_chart(_rings_df(), {}, _theme())
        inner = fig.data[0]
        assert list(inner.labels) == ["Core", "Difensivo"]
        assert list(inner.values) == [900.0, 100.0]

    def test_outer_ring_aggregates_by_natura(self):
        fig = build_allocation_rings_chart(_rings_df(), {}, _theme())
        outer = fig.data[1]
        values = dict(zip(outer.labels, outer.values))
        assert values["Azionario globale core"] == pytest.approx(900.0)
        assert values["Liquidità"] == pytest.approx(100.0)

    def test_rings_have_visible_gap(self):
        fig = build_allocation_rings_chart(_rings_df(), {}, _theme())
        inner, outer = fig.data[0], fig.data[1]
        inner_outer_radius = (inner.domain.x[1] - inner.domain.x[0]) / 2.0
        outer_inner_radius = outer.hole * 0.5
        assert outer_inner_radius > inner_outer_radius

    def test_only_outer_ring_shows_in_legend(self):
        fig = build_allocation_rings_chart(_rings_df(), {}, _theme())
        inner, outer = fig.data[0], fig.data[1]
        assert inner.showlegend is False
        assert outer.showlegend is not False
