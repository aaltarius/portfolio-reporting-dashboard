from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go

from core.config import COLORS
from ui.charts.extrema import add_extrema_markers
from ui.charts.runtime import finalize_chart
from ui.charts.settings import apply_settings
from ui.components import wrap_radar_label
from ui.formatting import fmt_eur_it, fmt_num_it, fmt_pct_it, hex_to_rgba
from ui.theme import P, instrument_color, macro_color


# ─────────────────────────────────────────────────────────────────────────────
# Builders spostati da ui/charts/andamento.py
# ─────────────────────────────────────────────────────────────────────────────

def build_portfolio_value_time_chart(dfh, dfmt, theme):
	"""Build standalone portfolio value chart.

	chart_id: andamento_portfolio_value
	chiamato da: ui/pages/andamento.py e ui/prewarm_bundle.py
	"""
	fig = go.Figure()
	fig.add_trace(
		go.Scatter(
			x=dfh["Data"],
			y=dfh["Valore"],
			name="Valore di Mercato",
			line=dict(color=theme.color_blue, width=2.5),
			fill="tozeroy",
			fillcolor=hex_to_rgba(theme.color_blue, 0.08),
		)
	)
	fig.add_trace(
		go.Scatter(
			x=dfh["Data"],
			y=dfh["Costo"],
			name="Costo Contabile",
			line=dict(color=theme.color_orange, width=2, dash="dash"),
		)
	)
	fig.add_trace(
		go.Scatter(
			x=dfh["Data"],
			y=dfh["Capitale"],
			name="Capitale Versato",
			line=dict(color=theme.color_gray, width=1.5, dash="dashdot"),
		)
	)
	return finalize_chart(fig, "andamento_portfolio_value", hovermode="x unified", uirevision="andamento-value")


def build_percentage_return_time_chart(dfh, pct_cap, pct_cost, pl_color, pl_total, dfmt, theme):
	"""Build percentage return chart for Andamento.

	chart_id: andamento_percentage_return
	chiamato da: ui/pages/andamento.py e ui/prewarm_bundle.py
	"""
	pct_cap = list(pct_cap or [])
	pct_cost = list(pct_cost or [])
	if dfh is not None and not dfh.empty:
		try:
			last_capitale = float(pd.to_numeric(dfh["Capitale"], errors="coerce").iloc[-1] or 0.0)
		except Exception:
			last_capitale = 0.0
		try:
			last_costo = float(pd.to_numeric(dfh["Costo"], errors="coerce").iloc[-1] or 0.0)
		except Exception:
			last_costo = 0.0
		try:
			valore_aperto_col = dfh["ValoreAperto"] if "ValoreAperto" in dfh.columns else dfh["Valore"]
			last_pl_aperto = float(pd.to_numeric(valore_aperto_col, errors="coerce").iloc[-1] or 0.0) - last_costo
		except Exception:
			last_pl_aperto = 0.0
		if pct_cap and last_capitale:
			pct_cap[-1] = (float(pl_total or 0.0) / last_capitale) * 100.0
		if pct_cost and last_costo:
			# Non usare pl_total qui: include liquidita' e guadagni realizzati
			# da vendite passate, non comparabili con "Costo" (solo posizioni
			# ancora aperte) - vedi build_percentage_return_series.
			pct_cost[-1] = (last_pl_aperto / last_costo) * 100.0
	fig = go.Figure()
	fig.add_trace(
		go.Scatter(
			x=dfh["Data"],
			y=pct_cap,
			name="Rend. su Capitale %",
			line=dict(color=pl_color, width=2.5),
			fill="tozeroy",
			fillcolor=hex_to_rgba(theme.color_green, 0.08) if pl_total >= 0 else hex_to_rgba(theme.color_red, 0.08),
		)
	)
	fig.add_trace(
		go.Scatter(
			x=dfh["Data"],
			y=pct_cost,
			name="Rend. su Costo %",
			line=dict(color=theme.color_orange, width=1.8, dash="dash"),
		)
	)
	fig.add_hline(y=0, line_dash="dot", line_color=hex_to_rgba(COLORS["gray"], 0.55), opacity=0.8)
	return finalize_chart(fig, "andamento_percentage_return", hovermode="x unified", uirevision="rend-capitale")


def build_pl_decomposition_time_chart(dfh, pl_cols, viz_mode, dfmt, theme):
	"""Build P/L contribution by instrument for Andamento.

	chart_id runtime: andamento_pl_decomp_stacked oppure andamento_pl_decomp_grouped
	chiamato da: ui/pages/andamento.py; stacked anche da ui/prewarm_bundle.py
	"""
	_ = dfmt
	fig = go.Figure()
	for col in pl_cols:
		tk = col[3:]
		stackgroup = "pl" if viz_mode == "Stacked" else None
		fig.add_trace(
			go.Scatter(
				x=dfh["Data"],
				y=dfh[col].fillna(0),
				name=tk,
				mode="lines",
				stackgroup=stackgroup,
				line=dict(width=0.7, color=instrument_color(tk)),
				fillcolor=instrument_color(tk),
			)
		)
	chart_id = "andamento_pl_decomp_stacked" if viz_mode == "Stacked" else "andamento_pl_decomp_grouped"
	if viz_mode == "Stacked" and pl_cols:
		# Il marker deve riflettere il totale che lo stack mostra davvero (somma
		# riga per riga delle sole componenti visualizzate), non l'aggregato
		# "P/L" del portafoglio: quest'ultimo include anche liquidita' e
		# guadagni realizzati da vendite passate, non rappresentati nello
		# stack, e produrrebbe un massimo/minimo che il grafico non raggiunge
		# mai visivamente.
		stack_total = dfh[pl_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0).sum(axis=1)
		if not stack_total.dropna().empty:
			add_extrema_markers(
				fig,
				chart_id,
				dfh["Data"],
				stack_total,
				theme=theme,
				value_formatter=lambda v: fmt_eur_it(v, 2),
			)
	elif "P/L" in dfh.columns and (not dfh["P/L"].dropna().empty):
		add_extrema_markers(
			fig,
			chart_id,
			dfh["Data"],
			pd.to_numeric(dfh["P/L"], errors="coerce"),
			theme=theme,
			value_formatter=lambda v: fmt_eur_it(v, 2),
		)
	return finalize_chart(
		fig,
		chart_id,
		hovermode="x unified",
		uirevision="stacked-pl",
		layout_updates={"barmode": "stack" if viz_mode == "Stacked" else "group"},
	)


# ─────────────────────────────────────────────────────────────────────────────
# Builders spostati da ui/charts/analisi.py
# ─────────────────────────────────────────────────────────────────────────────

def build_target_gap_chart(macro_target_df):
	"""Build target allocation gap chart for Analisi.

	chart_id: analisi_target_gap
	chiamato da: ui/dashboard_bundles.py (get_analitica_bundle)
	"""
	fig = go.Figure()
	peso_attuale = pd.to_numeric(macro_target_df["Peso attuale"], errors="coerce").fillna(0.0)
	fig.add_trace(
		go.Bar(
			y=macro_target_df["Categoria"],
			x=peso_attuale,
			orientation="h",
			name="Peso attuale",
			marker_color=[hex_to_rgba(macro_color(c), 0.45) for c in macro_target_df["Categoria"]],
			text=[fmt_pct_it(v, 1) for v in peso_attuale],
			textposition="outside",
			textfont=dict(size=10),
			cliponaxis=False,
			hovertemplate="%{y}<br>Peso attuale: %{x:.1%}<extra></extra>",
		)
	)
	fig.add_trace(
		go.Scatter(
			y=macro_target_df["Categoria"],
			x=macro_target_df["Peso target"],
			name="Peso target",
			mode="markers",
			marker=dict(symbol="diamond-wide", size=12, color=P["orange"]),
			hovertemplate="%{y}<br>Peso target: %{x:.1%}<extra></extra>",
		)
	)
	fig.update_layout(barmode="overlay")
	return apply_settings(fig, "analisi_target_gap")


def build_risk_contribution_chart(risk_df):
	"""Build risk contribution chart for Analisi.

	chart_id: analisi_risk_contribution2
	chiamato da: ui/pages/analisi.py
	"""
	fig = go.Figure()
	fig.add_trace(
		go.Bar(
			y=risk_df["Etichetta"],
			x=risk_df["Peso %"],
			orientation="h",
			name="Peso di mercato",
			marker_color=[hex_to_rgba(macro_color(c), 0.4) for c in risk_df["Categoria"]],
			text=[fmt_pct_it(v, 1) for v in risk_df["Peso %"]],
			textposition="outside",
		)
	)
	fig.add_trace(
		go.Bar(
			y=risk_df["Etichetta"],
			x=risk_df["Contributo rischio %"],
			orientation="h",
			name="Contributo al rischio",
			marker_color=[macro_color(c) for c in risk_df["Categoria"]],
			text=[fmt_pct_it(v, 1) for v in risk_df["Contributo rischio %"]],
			textposition="inside",
		)
	)
	fig.update_layout(barmode="group")
	return apply_settings(fig, "analisi_risk_contribution2")


def build_performance_attribution(da_frame, dfh):
	"""Waterfall chart: contributo P/L di ogni strumento al totale.

	chart_id: analisi_performance_attribution
	chiamato da: ui/pages/analisi.py
	"""
	_ = dfh
	if da_frame is None or da_frame.empty:
		fig = go.Figure()
		fig.add_trace(go.Waterfall(y=[0]))
		return apply_settings(fig, "analisi_performance_attribution")
	df = da_frame[["Ticker", "Strumento", "P/L €", "Tipo"]].copy()
	df = df.sort_values("P/L €", ascending=False)
	total = float(df["P/L €"].sum())
	fig = go.Figure(
		go.Waterfall(
			x=df["Ticker"].tolist() + ["TOTALE"],
			y=df["P/L €"].tolist() + [total],
			measure=["relative"] * len(df) + ["total"],
			connector=dict(line=dict(color="rgba(100,100,100,0.3)", width=1)),
			increasing=dict(marker_color=P["green"]),
			decreasing=dict(marker_color=P["red"]),
			totals=dict(marker_color=P["blue"]),
			text=[fmt_eur_it(v, 0, signed=True) for v in df["P/L €"].tolist() + [total]],
			textposition="outside",
			hovertemplate="%{x}<br>P/L: %{y:,.0f}€<extra></extra>",
		)
	)
	fig.update_layout(hovermode="x unified")
	return apply_settings(fig, "analisi_performance_attribution")


# ─────────────────────────────────────────────────────────────────────────────
# Builders spostati da ui/charts/home.py
# ─────────────────────────────────────────────────────────────────────────────

def _build_radar_figure(labels, portfolio_values, comparison_values, comparison_name, theme, chart_id):
	"""Shared radar builder for Home.

	chart_id runtime: home_radar_allocation oppure home_radar_quality
	chiamato da: build_asset_allocation_radar / build_quality_profile_radar
	"""
	theta = [wrap_radar_label(label) for label in labels]
	theta_closed = theta + [theta[0]]
	portfolio_closed = list(portfolio_values) + [portfolio_values[0]]
	comparison_closed = list(comparison_values) + [comparison_values[0]]
	data_max = max([float(v or 0.0) for v in portfolio_values + comparison_values] or [1.0])
	if chart_id == "home_radar_allocation":
		radial_max = min(100.0, max(20.0, data_max + 5.0))
		radial_dtick = 5 if radial_max <= 50 else 10
		ticksuffix = "%"
	else:
		radial_max = min(10.0, max(6.0, data_max + 0.8))
		radial_dtick = 1
		ticksuffix = None

	fig = go.Figure()
	fig.add_trace(
		go.Scatterpolar(
			r=portfolio_closed,
			theta=theta_closed,
			mode="lines",
			name="Portafoglio attuale",
			line=dict(color=theme.color_blue, width=3),
			fill="toself",
			fillcolor=hex_to_rgba(theme.color_blue, 0.16),
			hovertemplate="%{theta}<br>Portafoglio attuale: %{r:.1f}<extra></extra>",
		)
	)
	fig.add_trace(
		go.Scatterpolar(
			r=comparison_closed,
			theta=theta_closed,
			mode="lines",
			name=comparison_name,
			line=dict(color="rgba(107,114,128,0.95)", width=2.2, dash="dash"),
			hovertemplate=f"%{{theta}}<br>{comparison_name}: %{{r:.1f}}<extra></extra>",
		)
	)
	fig = apply_settings(fig, chart_id)
	radialaxis_cfg = dict(range=[0, radial_max], dtick=radial_dtick)
	if ticksuffix:
		radialaxis_cfg["ticksuffix"] = ticksuffix
	fig.update_layout(polar=dict(radialaxis=radialaxis_cfg))
	return fig


def build_asset_allocation_radar(radar_payload: dict[str, Any], theme):
	"""Radar quantitativo basato sull'allocazione reale del portafoglio.

	chart_id: home_radar_allocation
	chiamato da: ui/pages/home.py
	"""
	block = radar_payload.get("quantitative", {}) if isinstance(radar_payload, dict) else {}
	return _build_radar_figure(
		block.get("labels", []),
		block.get("portfolio", []),
		block.get("comparison", []),
		str(block.get("comparison_name") or "Benchmark moderato"),
		theme,
		"home_radar_allocation",
	)


def build_quality_profile_radar(radar_payload: dict[str, Any], theme):
	"""Radar qualitativo 0-10 basato sul profilo reale del portafoglio.

	chart_id: home_radar_quality
	chiamato da: ui/pages/home.py
	"""
	block = radar_payload.get("qualitative", {}) if isinstance(radar_payload, dict) else {}
	return _build_radar_figure(
		block.get("labels", []),
		block.get("portfolio", []),
		block.get("comparison", []),
		str(block.get("comparison_name") or "Profilo target"),
		theme,
		"home_radar_quality",
	)


def build_portfolio_simulation_chart(result, theme):
	"""Build Monte Carlo fan chart for Analitica.

	chart_id: analisi_monte_carlo
	chiamato da: ui/dashboard_bundles.py (_build_analitica_bundle)
	"""
	if not result.available:
		fig = go.Figure()
		fig.add_annotation(
			text=result.reason or "Dati insufficienti per la simulazione.",
			xref="paper", yref="paper",
			x=0.5, y=0.5,
			showarrow=False,
			font=dict(size=12),
		)
		return apply_settings(fig, "analisi_monte_carlo")

	fan = result.fan_percentiles
	band_color = getattr(theme, "color_blue", "#1f5eff")
	fig = go.Figure()
	fig.add_trace(go.Scatter(
		x=fan["trading_day"], y=fan["p95"], mode="lines",
		line=dict(width=0), showlegend=False, hoverinfo="skip",
	))
	fig.add_trace(go.Scatter(
		x=fan["trading_day"], y=fan["p5"], mode="lines",
		line=dict(width=0), fill="tonexty", fillcolor=hex_to_rgba(band_color, 0.12),
		name="Intervallo 5°-95° percentile",
		hovertemplate="Giorno %{x}: %{y:,.0f} €<extra></extra>",
	))
	fig.add_trace(go.Scatter(
		x=fan["trading_day"], y=fan["p75"], mode="lines",
		line=dict(width=0), showlegend=False, hoverinfo="skip",
	))
	fig.add_trace(go.Scatter(
		x=fan["trading_day"], y=fan["p25"], mode="lines",
		line=dict(width=0), fill="tonexty", fillcolor=hex_to_rgba(band_color, 0.28),
		name="Intervallo 25°-75° percentile",
		hovertemplate="Giorno %{x}: %{y:,.0f} €<extra></extra>",
	))
	fig.add_trace(go.Scatter(
		x=fan["trading_day"], y=fan["p50"], mode="lines",
		line=dict(width=2.4, color=band_color),
		name="Mediana scenari simulati",
		hovertemplate="Giorno %{x}: %{y:,.0f} €<extra></extra>",
	))
	return apply_settings(fig, "analisi_monte_carlo")
