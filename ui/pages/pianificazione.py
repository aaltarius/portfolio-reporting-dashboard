"""
ui/pages/pianificazione.py — Tab Pianificazione (t7): What-if simulator + liquidity planner
Pure rendering with pre-computed simulation data.
Fragment-based interactive components.
"""
from html import escape
from types import SimpleNamespace

import pandas as pd
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from core.cache import invalidate_portfolio_cache
from core.finance import compute_portfolio_state
from core.services.sator import (
    compute_current_bucket_mix,
    ensure_sator_metadata,
    ensure_sator_settings,
    build_portfolio_rings_frame,
    compute_watchlist_reminders,
    build_next_purchase_bubble_frame,
    latest_sator_decision,
)
from core.services.instrument_clustering import build_instrument_map
from persistence.storage import load_sator_decisions, load_settings, save_settings
from ui.formatting import fmt_eur_it, fmt_num_it, fmt_pct_it
from ui.i18n import t
from ui.page_chrome import render_page_intro as render_page_intro_shared, render_section_line as render_section_line_shared
from ui.components import render_section_title, back_to_top, legend_block
from ui.charts.natura_icons import get_natura_visual
from core.instrument_classification import suggest_tipo_correction
from core.render_profiler import profile_step
from ui.charts.pianificazione import (
    build_objective_mix_chart,
    build_allocation_rings_chart,
    build_next_purchase_bubble_chart,
    build_instrument_map_chart,
)
from ui.theme import bucket_color, get_theme_context
from ui.notifications import queue_success

def _page_icon_svg(kind: str = "default") -> str:
    icons = {
        "summary": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-summary" x1="3" y1="3" x2="21" y2="21"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="3.5" y="3" width="17" height="18" rx="4" fill="url(#g-summary)" opacity=".16"/>
          <path d="M8 8.2h8M8 12h8M8 15.8h5" fill="none" stroke="url(#g-summary)" stroke-width="1.9" stroke-linecap="round"/>
          <circle cx="17" cy="16" r="2.2" fill="url(#g-summary)"/>
        </svg>
        """,
        "confronto": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-confronto" x1="4" y1="20" x2="20" y2="4"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="3" y="4" width="18" height="16" rx="4" fill="url(#g-confronto)" opacity=".14"/>
          <path d="M7 16.5V11M12 16.5V7.5M17 16.5v-4" fill="none" stroke="url(#g-confronto)" stroke-width="2.1" stroke-linecap="round"/>
          <path d="M6.5 17.5h11" stroke="url(#g-confronto)" stroke-width="1.8" stroke-linecap="round"/>
        </svg>
        """,
        "pianificazione": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-plan" x1="4" y1="4" x2="20" y2="20"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="3.5" y="5" width="17" height="15.5" rx="4" fill="url(#g-plan)" opacity=".15"/>
          <path d="M8 3.5v3M16 3.5v3M6.5 9h11" stroke="url(#g-plan)" stroke-width="1.8" stroke-linecap="round"/>
          <path d="M8 13h3l1.5 2.2L16.5 11" fill="none" stroke="url(#g-plan)" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        """,
        "gestione": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-data" x1="4" y1="4" x2="20" y2="20"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="4" y="3.5" width="16" height="17" rx="4" fill="url(#g-data)" opacity=".15"/>
          <path d="M8 8h8M8 12h8M8 16h5" stroke="url(#g-data)" stroke-width="1.8" stroke-linecap="round"/>
          <circle cx="17" cy="16" r="2.2" fill="url(#g-data)"/>
        </svg>
        """,
        "impostazioni": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-settings" x1="4" y1="4" x2="20" y2="20"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <circle cx="12" cy="12" r="8.5" fill="url(#g-settings)" opacity=".15"/>
          <path d="M12 8.1v-2M12 18v-2M8.1 12h-2M18 12h-2M9.25 9.25 7.8 7.8M16.2 16.2l-1.45-1.45M14.75 9.25 16.2 7.8M7.8 16.2l1.45-1.45" stroke="url(#g-settings)" stroke-width="1.7" stroke-linecap="round"/>
          <circle cx="12" cy="12" r="3.1" fill="none" stroke="url(#g-settings)" stroke-width="2"/>
        </svg>
        """,
        "default": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-default" x1="4" y1="4" x2="20" y2="20"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="4" y="4" width="16" height="16" rx="4" fill="url(#g-default)" opacity=".15"/>
          <path d="M8 9h8M8 13h8M8 17h5" stroke="url(#g-default)" stroke-width="1.8" stroke-linecap="round"/>
        </svg>
        """,
    }
    return icons.get(kind, icons["default"])


def _render_page_intro(title: str, comment: str, icon: str = "default", theme=None) -> None:
    return render_page_intro_shared(title, comment, icon, theme)


def _section_line() -> None:
    return render_section_line_shared()


def _bucket_scost_severity(delta_pp: float) -> str:
    """Tolleranza di ribilanciamento: entro 3pp = ok, entro 8pp = attenzione,
    oltre = fuori target."""
    d = abs(delta_pp)
    if d <= 3.0:
        return "ok"
    if d <= 8.0:
        return "warn"
    return "bad"


def _build_bucket_allocation_table_html(
    rings_df: pd.DataFrame,
    bucket_totals: "pd.Series",
    current_mix: dict[str, float],
    objective: dict,
    objective_key: dict[str, str],
    theme,
    watchlist_reminders: dict[str, list[str]] | None = None,
) -> str:
    """Tabella unica Core/Difensivo/Satellite: una riga-bucket con barra
    obiettivo-vs-attuale (fill = attuale, tacca = obiettivo) seguita dalle
    righe-natura del bucket (strumenti aggregati per natura: importo sommato,
    peso riferito al gruppo natura, non al singolo strumento). Sostituisce
    sia il vecchio box testuale "Lettura dell'allocazione" sia il box
    "Strumenti per bucket": un solo oggetto visivo invece di grafico + due
    box di testo."""
    total_value = float(bucket_totals.sum())
    body_rows: list[str] = []
    for b in ("Core", "Difensivo", "Satellite"):
        sub = rings_df[rings_df["bucket"] == b]
        reminders_for_bucket = (watchlist_reminders or {}).get(b, [])
        if sub.empty and not reminders_for_bucket:
            continue
        tone = bucket_color(b, theme)
        target = float(objective.get(objective_key[b], 0.0))
        attuale = float(current_mix.get(b, 0.0))
        scost = (attuale - target) * 100.0
        severity = _bucket_scost_severity(scost)
        bucket_value = float(bucket_totals.get(b, 0.0))
        fill_pct = min(max(attuale * 100.0, 0.0), 100.0)
        target_pct = min(max(target * 100.0, 0.0), 100.0)
        body_rows.append(f'''
        <tr class="bucket-alloc-bucket-row" style="--tone:{tone}">
          <td colspan="2"><span class="bucket-alloc-bucket-name"><span class="dot"></span>{b}</span></td>
          <td class="num">{fmt_eur_it(bucket_value, 2)}</td>
          <td>
            <div class="bucket-alloc-bar-track">
              <div class="bucket-alloc-bar-fill" style="width:{fill_pct:.2f}%"></div>
              <div class="bucket-alloc-bar-target" style="left:{target_pct:.2f}%"></div>
            </div>
            <div class="bucket-alloc-bar-caption">
              <span>Attuale {fmt_pct_it(attuale, 1)} &middot; obiettivo {fmt_pct_it(target, 1)}</span>
              <span class="bucket-alloc-scost {severity}">{scost:+.1f}%</span>
            </div>
          </td>
        </tr>''')
        if not sub.empty:
            sub = sub.copy()
            sub["natura"] = sub["natura"].apply(lambda v: str(v) if v else "Esposizione diversificata")
            sub = sub.sort_values("value", ascending=False)
            natura_groups = (
                sub.groupby("natura", sort=False)
                .agg(value=("value", "sum"), tickers=("ticker", lambda s: ", ".join(s.astype(str))))
                .sort_values("value", ascending=False)
            )
            for natura_label, grp in natura_groups.iterrows():
                natura_color, natura_svg = get_natura_visual(natura_label)
                group_value = float(grp["value"])
                pct_of_bucket = (group_value / bucket_value * 100.0) if bucket_value > 0 else 0.0
                tickers_html = grp["tickers"]
                body_rows.append(f'''
                <tr class="bucket-alloc-instrument-row" style="--tone:{tone}">
                  <td><span class="bucket-alloc-natura" style="--natura-color:{natura_color}">{natura_svg}{natura_label}</span></td>
                  <td class="bucket-alloc-ticker">{tickers_html}</td>
                  <td class="num">{fmt_eur_it(group_value, 2)}</td>
                  <td>
                    <div class="bucket-alloc-mini-track">
                      <div class="bucket-alloc-mini-fill" style="width:{pct_of_bucket:.2f}%"></div>
                    </div>
                    <span class="bucket-alloc-mini-caption">{pct_of_bucket:.0f}% del bucket</span>
                  </td>
                </tr>''')
        for reminder_natura in reminders_for_bucket:
            natura_color, natura_svg = get_natura_visual(reminder_natura)
            body_rows.append(f'''
            <tr class="bucket-alloc-watchlist-row" style="--tone:{tone}">
              <td><span class="bucket-alloc-natura" style="--natura-color:{natura_color}">{natura_svg}{reminder_natura}</span></td>
              <td class="bucket-alloc-ticker"></td>
              <td class="num">{fmt_eur_it(0.0, 2)}</td>
              <td><span class="bucket-alloc-mini-caption">In osservazione</span></td>
            </tr>''')
    body_rows.append(f'''
    <tr class="bucket-alloc-total-row">
      <td colspan="2">TOTALE</td>
      <td class="num">{fmt_eur_it(total_value, 2)}</td>
      <td>100%</td>
    </tr>''')
    return (
        '<div class="bucket-alloc-card"><table class="bucket-alloc-table">'
        '<thead><tr><th>Natura</th><th>Strumenti</th><th class="num">Importo</th><th>Peso</th></tr></thead>'
        f'<tbody>{"".join(body_rows)}</tbody></table></div>'
    )


def _render_bucket_allocation_table(
    rings_df: pd.DataFrame,
    bucket_totals: "pd.Series",
    current_mix: dict[str, float],
    objective: dict,
    objective_key: dict[str, str],
    theme,
    watchlist_reminders: dict[str, list[str]] | None = None,
) -> None:
    st.markdown(
        _build_bucket_allocation_table_html(rings_df, bucket_totals, current_mix, objective, objective_key, theme, watchlist_reminders),
        unsafe_allow_html=True,
    )


def _normalize_objective_inputs(core: float, difensivo: float, satellite: float) -> dict[str, float]:
    total = max(0.0, core) + max(0.0, difensivo) + max(0.0, satellite)
    if total <= 0:
        return {"core": 1 / 3, "difensivo": 1 / 3, "satellite": 1 / 3}
    return {"core": max(0.0, core) / total, "difensivo": max(0.0, difensivo) / total, "satellite": max(0.0, satellite) / total}


_OBJECTIVE_PRESETS = {
    "Prudente (Core 50 / Difensivo 40 / Satellite 10)": {"core": 0.50, "difensivo": 0.40, "satellite": 0.10},
    "Equilibrato (Core 55 / Difensivo 25 / Satellite 20)": {"core": 0.55, "difensivo": 0.25, "satellite": 0.20},
    "Dinamico (Core 50 / Difensivo 15 / Satellite 35)": {"core": 0.50, "difensivo": 0.15, "satellite": 0.35},
}


def _state_float(key: str, fallback: float) -> float:
    try:
        return float(st.session_state.get(key, fallback) or fallback)
    except Exception:
        return float(fallback)


def _save_portfolio_objective_settings_from_state() -> None:
    settings = load_settings()
    preset_label = str(st.session_state.get("obj_preset", "-") or "-")
    preset = _OBJECTIVE_PRESETS.get(preset_label)
    if preset:
        objective = dict(preset)
    else:
        objective = _normalize_objective_inputs(
            _state_float("obj_core", 0.0),
            _state_float("obj_difensivo", 0.0),
            _state_float("obj_satellite", 0.0),
        )
    st.session_state["obj_core"] = objective["core"] * 100
    st.session_state["obj_difensivo"] = objective["difensivo"] * 100
    st.session_state["obj_satellite"] = objective["satellite"] * 100
    st.session_state["obj_preset"] = "-"

    sator_cfg = ensure_sator_settings(settings)
    caps = dict(sator_cfg["concentration_caps"])
    cap_edits = {
        nature: _state_float(f"cap_{nature}", float(value) * 100.0) / 100.0
        for nature, value in caps.items()
    }
    weights = {
        "strategic_fit": _state_float("w_fit", 0.0),
        "tactical_momentum": _state_float("w_mom", 0.0),
        "risk_efficiency": _state_float("w_risk", 0.0),
        "diversification_benefit": _state_float("w_div", 0.0),
        "cost_efficiency": _state_float("w_cost", 0.0),
    }
    weight_total = sum(max(0.0, value) for value in weights.values())

    settings["portfolio_objective"] = objective
    settings.setdefault("sator", {})["concentration_caps"] = cap_edits
    if weight_total > 0:
        settings["sator"]["score_weights"] = {
            key: max(0.0, value) / weight_total
            for key, value in weights.items()
        }
    save_settings(settings)
    st.session_state["_settings_runtime"] = settings
    invalidate_portfolio_cache("impostazioni obiettivo portafoglio salvate")
    queue_success("Obiettivo di portafoglio salvato. Cruscotti, Analitica e SATOR useranno subito il nuovo target.")


def _render_portfolio_objective_section(ctx: SimpleNamespace, theme) -> None:
    settings = ctx.settings
    data = ctx.data
    sator_cfg = ensure_sator_settings(settings)
    objective = settings.get("portfolio_objective", {"core": 0.55, "difensivo": 0.25, "satellite": 0.20})

    render_section_title(
        "Obiettivo di portafoglio",
        comment="Le percentuali Core/Difensivo/Satellite che guidano SATOR e la Liquidita' da investire. Nessun valore preimpostato nascosto: tutto qui e' quello che leggi.",
        gap_after="sm",
    )

    with st.form("portfolio_objective_form", clear_on_submit=False):
        st.selectbox("Preset rapido (facoltativo)", ["-"] + list(_OBJECTIVE_PRESETS.keys()), key="obj_preset")
        st.caption("Se scegli un preset, al salvataggio avra' priorita' sui tre valori manuali Core/Difensivo/Satellite.")
        c1, c2, c3 = st.columns(3, gap="small")
        core_pct = c1.number_input("Core %", min_value=0.0, max_value=100.0, step=1.0,
                                    value=float(st.session_state.get("obj_core", objective["core"] * 100)), key="obj_core")
        dif_pct = c2.number_input("Difensivo %", min_value=0.0, max_value=100.0, step=1.0,
                                   value=float(st.session_state.get("obj_difensivo", objective["difensivo"] * 100)), key="obj_difensivo")
        sat_pct = c3.number_input("Satellite %", min_value=0.0, max_value=100.0, step=1.0,
                                   value=float(st.session_state.get("obj_satellite", objective["satellite"] * 100)), key="obj_satellite")

        with st.expander("Limiti di concentrazione per asset class", expanded=False):
            caps = dict(sator_cfg["concentration_caps"])
            cap_edits: dict[str, float] = {}
            for nature in sorted(caps.keys()):
                cap_edits[nature] = st.number_input(
                    nature.replace("_", " "), min_value=1.0, max_value=100.0, step=1.0,
                    value=float(caps[nature] * 100), key=f"cap_{nature}",
                )

        with st.expander("Pesi del punteggio SATOR", expanded=False):
            weights = dict(sator_cfg["score_weights"])
            w_fit = st.number_input("Fit allocativo %", min_value=0.0, max_value=100.0, step=1.0, value=float(weights["strategic_fit"] * 100), key="w_fit")
            w_mom = st.number_input("Momentum %", min_value=0.0, max_value=100.0, step=1.0, value=float(weights["tactical_momentum"] * 100), key="w_mom")
            w_risk = st.number_input("Rischio %", min_value=0.0, max_value=100.0, step=1.0, value=float(weights["risk_efficiency"] * 100), key="w_risk")
            w_div = st.number_input("Diversificazione %", min_value=0.0, max_value=100.0, step=1.0, value=float(weights["diversification_benefit"] * 100), key="w_div")
            w_cost = st.number_input("Costo %", min_value=0.0, max_value=100.0, step=1.0, value=float(weights["cost_efficiency"] * 100), key="w_cost")

        with st.expander("Come funziona il calcolo interno (non modificabile)", expanded=False):
            st.markdown(
                "<ul style='margin:0;padding-left:18px;list-style:disc'>"
                "<li style='margin-bottom:8px'><b>Momentum</b>: media pesata dei rendimenti a 1/3/6/12 mesi (10/35/35/20%) — funzione <code>_score_momentum</code> in core/services/sator.py.</li>"
                "<li style='margin-bottom:8px'><b>Rischio</b>: volatilita' (40%) + drawdown massimo (30%) + rendimento/rischio a 12 mesi (30%) — funzione <code>_score_risk</code> in core/services/sator.py.</li>"
                "<li style='margin-bottom:8px'><b>Costo</b>: bonus zero commissioni/PAC, malus TER/spread, penalita' se il prezzo satura il budget — funzione <code>_score_cost</code> in core/services/sator.py.</li>"
                "<li>Per modificare questi dettagli serve intervenire direttamente nel codice: qui sopra trovi obiettivo, cap e pesi, che sono invece tuoi.</li>"
                "</ul>",
                unsafe_allow_html=True,
            )

        st.form_submit_button(
            "Salva obiettivo e aggiorna analisi",
            width="stretch",
            on_click=_save_portfolio_objective_settings_from_state,
        )

    with profile_step("Pianificazione", "obiettivo_state_mix"):
        state_df = compute_portfolio_state(data, include_closed=True).get("df", pd.DataFrame())
        current_mix = compute_current_bucket_mix(data, state_df)
    with profile_step("Pianificazione", "obiettivo_chart"):
        _render_objective_mix_chart(objective, current_mix, theme)


def _render_objective_mix_chart(objective: dict, current_mix: dict, theme) -> None:
    """Obiettivo vs mix attuale: builder centralizzato in ui/charts/pianificazione.py,
    layout governato da ui/charts/settings.py (chart_id pianificazione_obiettivo_mix)."""
    fig = build_objective_mix_chart(objective, current_mix, theme)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def _decision_float(value, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return default if pd.isna(result) else result


def _decision_line_amount(line: dict) -> float:
    amount = _decision_float(line.get("amount"), 0.0)
    if amount > 0:
        return amount
    shares = _decision_float(line.get("shares"), 0.0)
    price = _decision_float(line.get("price"), 0.0)
    return max(0.0, shares * price)


def _summarize_sator_execution_history(decisions: list[dict] | None) -> dict | None:
    executed_count = 0
    adherence_total = 0.0
    delta_total = 0.0
    skipped_total = 0
    added_total = 0
    skipped_by_ticker: dict[str, int] = {}
    target_left_weighted = 0.0
    target_left_amount = 0.0

    for decision in decisions or []:
        if not isinstance(decision, dict):
            continue
        actual_lines = [
            line for line in (decision.get("actual_order") or [])
            if isinstance(line, dict) and _decision_line_amount(line) > 0
        ]
        if not actual_lines:
            continue

        planned_lines = [
            line for line in (decision.get("order_lines") or [])
            if isinstance(line, dict) and _decision_line_amount(line) > 0
        ]
        planned_by_ticker = {
            str(line.get("ticker") or "").strip().upper(): line
            for line in planned_lines
            if str(line.get("ticker") or "").strip()
        }
        actual_by_ticker = {
            str(line.get("ticker") or "").strip().upper(): line
            for line in actual_lines
            if str(line.get("ticker") or "").strip()
        }
        planned_tickers = set(planned_by_ticker)
        actual_tickers = set(actual_by_ticker)
        proposed_total = _decision_float(decision.get("importo_ordine"), 0.0)
        if proposed_total <= 0:
            proposed_total = sum(_decision_line_amount(line) for line in planned_lines)
        actual_total = sum(_decision_line_amount(line) for line in actual_lines)

        if proposed_total > 0:
            adherence = max(0.0, 100.0 - (abs(actual_total - proposed_total) / proposed_total * 100.0))
        else:
            adherence = 0.0
        executed_count += 1
        adherence_total += adherence
        delta_total += actual_total - proposed_total

        skipped = sorted(planned_tickers - actual_tickers)
        added = sorted(actual_tickers - planned_tickers)
        skipped_total += len(skipped)
        added_total += len(added)

        for ticker in skipped:
            skipped_by_ticker[ticker] = skipped_by_ticker.get(ticker, 0) + 1
            line = planned_by_ticker[ticker]
            amount = _decision_line_amount(line)
            improvement = max(0.0, _decision_float(line.get("target_improvement_pp"), 0.0))
            if amount > 0 and improvement > 0:
                target_left_weighted += improvement * amount
                target_left_amount += amount

    if executed_count <= 0:
        return None

    adherence_avg = adherence_total / executed_count
    drift_count = skipped_total + added_total
    if adherence_avg >= 95.0 and drift_count == 0:
        label, label_class = "molto coerente", "ok"
    elif adherence_avg >= 85.0 and drift_count <= 2:
        label, label_class = "coerente", "ok"
    elif adherence_avg >= 70.0:
        label, label_class = "da monitorare", "warn"
    else:
        label, label_class = "dispersiva", "bad"

    most_skipped = None
    if skipped_by_ticker:
        most_skipped = sorted(skipped_by_ticker.items(), key=lambda item: (-item[1], item[0]))[0]

    return {
        "executed_count": executed_count,
        "adherence_avg": adherence_avg,
        "delta_total": delta_total,
        "skipped_total": skipped_total,
        "added_total": added_total,
        "target_left_pp": (target_left_weighted / target_left_amount) if target_left_amount > 0 else 0.0,
        "most_skipped": most_skipped,
        "label": label,
        "label_class": label_class,
    }


def _build_sator_execution_compact_html(decisions: list[dict] | None) -> str:
    summary = _summarize_sator_execution_history(decisions)
    if not summary:
        return ""

    most_skipped = summary["most_skipped"]
    if most_skipped:
        skipped_value = f"{escape(most_skipped[0])} <span>{int(most_skipped[1])}x</span>"
    else:
        skipped_value = "Nessuno"
    delta_class = "ok" if summary["delta_total"] >= 0 else "bad"
    drift_value = f'{int(summary["skipped_total"])} saltati / {int(summary["added_total"])} extra'
    return (
        '<div class="ref-snapshot-exec">'
        '<div class="ref-snapshot-exec-title">'
        '<span>Disciplina esecuzione</span>'
        f'<b class="{summary["label_class"]}">{escape(summary["label"])}</b>'
        '</div>'
        '<div><span>Foto eseguite</span>'
        f'<b>{int(summary["executed_count"])}</b></div>'
        '<div><span>Aderenza importo</span>'
        f'<b>{fmt_pct_it(summary["adherence_avg"] / 100.0, 1)}</b></div>'
        '<div><span>Delta eseguito</span>'
        f'<b class="{delta_class}">{fmt_eur_it(summary["delta_total"], 2)}</b></div>'
        '<div><span>Scostamenti</span>'
        f'<b>{drift_value}</b></div>'
        '<div><span>Target lasciato</span>'
        f'<b>{summary["target_left_pp"]:.2f} pp</b></div>'
        '<div><span>Saltato piu spesso</span>'
        f'<b>{skipped_value}</b></div>'
        '</div>'
    )


def _build_sator_reference_summary_html(latest: dict, theme, data: dict, decisions: list[dict] | None = None) -> str:
    """Card per 'Fotografia di riferimento' sotto la mappa a bolle dei
    prossimi acquisti: usa i campi della fotografia decisionale SATOR salvata
    su disco, senza ricalcolare l'analisi live (solo lookup natura
    per ticker da data['strumenti'], stessa fonte del donut ad anelli). Sostituisce
    il vecchio box testuale con una card in stile bucket-alloc (barra con tacca
    budget + lista righe ordine con nome/icona natura) per una lettura piu' immediata."""
    data_label = str(latest.get("month_id") or latest.get("created_at") or "n/d")
    note = str(latest.get("note") or "").strip()
    importo = float(latest.get("importo_ordine", 0.0))
    budget = float(latest.get("budget", 0.0))
    over_budget = budget > 0 and importo > budget
    total_scale = max(importo, budget, 1e-9)
    fill_pct = min(max((importo / total_scale) * 100.0, 0.0), 100.0)
    target_pct = min(max((budget / total_scale) * 100.0, 0.0), 100.0) if budget > 0 else 0.0
    over_pct = ((importo / budget) - 1.0) * 100.0 if over_budget else 0.0
    bar_tone = "var(--ptf-danger)" if over_budget else "var(--ptf-primary)"
    over_html = f'<span class="ref-snapshot-over bad">+{over_pct:.1f}% oltre budget</span>' if over_budget else ''
    target_html = f'<div class="ref-snapshot-bar-target" style="left:{target_pct:.2f}%"></div>' if budget > 0 else ''

    giudizio = latest.get("giudizio") or {}
    voto_medio = _decision_float(giudizio.get("voto_medio"))
    giudizio_label = str(giudizio.get("label") or "n/d").strip() or "n/d"
    giudizio_class = "ok" if voto_medio >= 7.5 else ("warn" if voto_medio >= 5.5 else "bad")
    giudizio_html = ""
    if voto_medio > 0:
        giudizio_html = (
            '<div class="ref-snapshot-judgement">'
            '<div><span>Giudizio SATOR</span>'
            f'<b class="{giudizio_class}">{voto_medio:.1f} · {escape(giudizio_label)}</b></div>'
            '<div><span>Uso budget</span>'
            f'<b>{fmt_pct_it((importo / budget) if budget > 0 else 0.0, 1)}</b></div>'
            '</div>'
        )

    alerts_html = ""
    alerts = [item for item in (latest.get("alerts") or []) if isinstance(item, dict)]
    if alerts:
        alert_items = ""
        for alert in alerts[:2]:
            title = escape(str(alert.get("title") or "Avviso"))
            message = escape(str(alert.get("message") or ""))
            alert_items += (
                '<div class="ref-snapshot-alert">'
                f'<b>{title}</b>'
                f'<span>{message}</span>'
                '</div>'
            )
        alerts_html = (
            '<div class="ref-snapshot-alerts">'
            '<div class="ref-snapshot-lines-label">Alert principali</div>'
            f'{alert_items}'
            '</div>'
        )

    mix_rows_html = ""
    ripartizione = latest.get("ripartizione") or {}
    for b in ("Core", "Difensivo", "Satellite"):
        entry = ripartizione.get(b) or {}
        pct = float(entry.get("pct", 0.0))
        if not entry:
            continue
        tone = bucket_color(b, theme)
        mix_rows_html += (
            f'<div class="ref-snapshot-mix-row" style="--tone:{tone}">'
            f'<span class="ref-snapshot-mix-label"><span class="dot"></span>{b}</span>'
            f'<div class="ref-snapshot-mix-track"><div class="ref-snapshot-mix-fill" style="width:{min(max(pct, 0.0), 100.0):.2f}%"></div></div>'
            f'<span class="ref-snapshot-mix-pct">{fmt_pct_it(pct / 100.0, 1)}</span>'
            f'</div>'
        )

    natura_by_ticker = {
        str(item.get("ticker") or "").strip().upper(): str(item.get("natura") or "").strip() or "Esposizione diversificata"
        for item in (data.get("strumenti") or [])
    }

    bucket_totals = {b: float((ripartizione.get(b) or {}).get("amount", 0.0)) for b in ("Core", "Difensivo", "Satellite")}

    lines_html = ""
    order_lines = latest.get("order_lines") or []
    if order_lines:
        bucket_order = {"Core": 0, "Difensivo": 1, "Satellite": 2}
        order_lines = sorted(order_lines, key=lambda l: bucket_order.get(str(l.get("bucket") or "Satellite"), 2))
        bucket_row_counts: dict[str, int] = {}
        for line in order_lines:
            b = str(line.get("bucket") or "Satellite")
            bucket_row_counts[b] = bucket_row_counts.get(b, 0) + 1
        buckets_rendered: set[str] = set()
        line_rows = ""
        for line in order_lines:
            ticker = str(line.get("ticker", ""))
            name = str(line.get("name") or "").strip() or ticker
            natura_label = natura_by_ticker.get(ticker.strip().upper(), "Esposizione diversificata")
            natura_color, natura_svg = get_natura_visual(natura_label)
            bucket = str(line.get("bucket") or "Satellite")
            bucket_tone = bucket_color(bucket, theme)
            if bucket in buckets_rendered:
                bucket_total_cell = ""
            else:
                buckets_rendered.add(bucket)
                bucket_total_cell = (
                    f'<td class="num ref-snapshot-bucket-total" rowspan="{bucket_row_counts[bucket]}">'
                    f'{fmt_eur_it(bucket_totals.get(bucket, 0.0), 2)}</td>'
                )
            line_rows += (
                '<tr>'
                '<td><span class="ref-snapshot-instrument">'
                f'<span class="ref-snapshot-bucket-dot" style="--tone:{bucket_tone}" title="{bucket}"></span>'
                f'<span class="ref-snapshot-natura" style="--natura-color:{natura_color}" title="{natura_label}">{natura_svg}</span>'
                f'<span class="ref-snapshot-instrument-text"><span class="ticker">{ticker}</span><span class="name">{name}</span></span>'
                '</span></td>'
                f'<td class="num">{int(line.get("shares", 0))}q</td>'
                f'<td class="num">{fmt_eur_it(float(line.get("price", 0.0)), 2)}</td>'
                f'<td class="num">{fmt_eur_it(float(line.get("amount", 0.0)), 2)}</td>'
                f'{bucket_total_cell}'
                '</tr>'
            )
        lines_html = (
            f'<div class="ref-snapshot-lines-label">Righe ordine ({len(order_lines)})</div>'
            '<div class="ref-snapshot-lines"><table>'
            '<thead><tr><th>Strumento</th><th class="num">Quote</th><th class="num">Prezzo*</th>'
            '<th class="num">Importo</th><th class="num">Totale bucket</th></tr></thead>'
            f'<tbody>{line_rows}</tbody></table></div>'
            '<div class="ref-snapshot-footnote">* Prezzo rilevato al momento del salvataggio della fotografia, non il prezzo attuale.</div>'
        )

    note_html = f'<span class="ref-snapshot-note">{escape(note)}</span>' if note else ''
    mix_html = f'<div class="ref-snapshot-mix">{mix_rows_html}</div>' if mix_rows_html else ''
    execution_html = _build_sator_execution_compact_html(decisions)
    return (
        '<div class="ref-snapshot-card">'
        '<div class="ref-snapshot-head">'
        f'<span class="ref-snapshot-title">Fotografia di riferimento &middot; {data_label}</span>'
        f'{note_html}'
        '</div>'
        '<div class="ref-snapshot-body">'
        '<div class="ref-snapshot-amount-row">'
        '<span>Importo ordine</span>'
        f'<span class="val">{fmt_eur_it(importo, 2)} <span class="cap">su budget {fmt_eur_it(budget, 2)}</span>{over_html}</span>'
        '</div>'
        f'<div class="ref-snapshot-bar-track" style="--tone:{bar_tone}">'
        f'<div class="ref-snapshot-bar-fill" style="width:{fill_pct:.2f}%"></div>'
        f'{target_html}'
        '</div>'
        f'{giudizio_html}'
        f'{execution_html}'
        f'{mix_html}'
        f'{alerts_html}'
        f'{lines_html}'
        '</div>'
        '</div>'
    )


def _render_sator_reference_summary(latest: dict, theme, data: dict, decisions: list[dict] | None = None) -> None:
    st.markdown(_build_sator_reference_summary_html(latest, theme, data, decisions), unsafe_allow_html=True)


def _render_decision_dashboard_section(ctx: SimpleNamespace, theme) -> None:
    """Dashboard decisionale basata sul portafoglio corrente e sull'ultima
    fotografia SATOR salvata su disco dalla pagina standalone in sidebar."""
    data = ctx.data
    settings = ctx.settings
    with profile_step("Pianificazione/SATOR", "state_and_rings"):
        ensure_sator_metadata(data)
        state_df = compute_portfolio_state(data, include_closed=True).get("df", pd.DataFrame())
        rings_df = build_portfolio_rings_frame(data, state_df)

    held_tickers = set(rings_df["ticker"]) if not rings_df.empty else set()
    warnings: list[str] = []
    with profile_step("Pianificazione/SATOR", "classification_checks", count=len(held_tickers)):
        for item in data.get("strumenti", []) or []:
            ticker = str(item.get("ticker") or "").strip().upper()
            if not ticker or ticker not in held_tickers:
                continue
            natura = str(item.get("natura") or "")
            if not natura or natura == "Esposizione diversificata":
                warnings.append(f"{ticker}: natura non chiaramente classificata (\"Esposizione diversificata\"); verifica in Arricchimento.")
            elif suggest_tipo_correction(item):
                warnings.append(f"{ticker}: benchmark/focus in contraddizione col tipo salvato; verifica in Arricchimento.")
    if warnings:
        st.warning("Classificazioni da verificare:\n\n" + "\n".join(f"- {w}" for w in warnings))

    objective = settings.get("portfolio_objective", {"core": 0.55, "difensivo": 0.25, "satellite": 0.20})
    objective_key = {"Core": "core", "Difensivo": "difensivo", "Satellite": "satellite"}

    if rings_df.empty:
        st.info("Nessuno strumento posseduto: la mappa di allocazione comparira' dopo il primo acquisto.")
    else:
        render_section_title(
            "Allocazione: bucket e strumenti", comment="Anello interno: Core/Difensivo/Satellite. Anello esterno: natura/esposizione (piu' strumenti della stessa natura si aggregano in un'unica fetta, colorata per natura; l'hover elenca i singoli strumenti che la compongono).", gap_after="sm",
        )
        with profile_step("Pianificazione/SATOR", "allocation_rings_chart"):
            fig_rings = build_allocation_rings_chart(rings_df, objective, theme)
            st.plotly_chart(fig_rings, width="stretch", config={"displayModeBar": False})
        with profile_step("Pianificazione/SATOR", "allocation_table_and_reminders"):
            bucket_totals = rings_df.groupby("bucket")["value"].sum()
            total_value = float(bucket_totals.sum())
            current_mix = {
                b: (float(bucket_totals.get(b, 0.0)) / total_value if total_value > 0 else 0.0)
                for b in ("Core", "Difensivo", "Satellite")
            }
            watchlist_reminders = compute_watchlist_reminders(data, state_df)
            _render_bucket_allocation_table(rings_df, bucket_totals, current_mix, objective, objective_key, theme, watchlist_reminders)
    render_section_title(
        "Prossimo acquisto: mappa decisionale",
        comment="Dati dall'ultima fotografia SATOR salvata dalla pagina SATOR attiva in sidebar, non da un'analisi dal vivo dentro Streamlit.",
        gap_after="sm",
    )
    with profile_step("Pianificazione/SATOR", "decision_snapshot_load"):
        decisions_state = load_sator_decisions()
        latest_decision = latest_sator_decision(decisions_state.get("items") or [])
    with profile_step("Pianificazione/SATOR", "decision_bubble_frame"):
        bubble_df, missing_tickers = build_next_purchase_bubble_frame(data)
    if not (decisions_state.get("items") or []):
        st.info("Nessuna fotografia SATOR salvata: apri SATOR dalla sidebar e salva una decisione per popolare questa mappa.")
    elif bubble_df.empty:
        st.info("L'ultima fotografia SATOR salvata non contiene ancora i punteggi necessari per questa mappa: salvane una nuova per popolarla.")
    else:
        if missing_tickers:
            st.warning("Dati insufficienti nell'ultima fotografia per: " + ", ".join(missing_tickers) + ". Salva una fotografia aggiornata per includerli.")
        with profile_step("Pianificazione/SATOR", "decision_bubble_chart", count=len(bubble_df)):
            fig_bubble = build_next_purchase_bubble_chart(bubble_df, theme)
            st.plotly_chart(fig_bubble, width="stretch", config={"displayModeBar": False})
        legend_block(
            "Quadranti: in basso a destra = buon contributo difensivo; in alto a destra = diversifica ma aumenta volatilita'; "
            "in alto a sinistra = satellite aggressivo/ridondante; in basso a sinistra = poco utile/non prioritario. "
            "Dimensione bolla = importo proposto nella fotografia.",
            variant="bottom",
        )
    if latest_decision:
        _col_spacer, _col_refresh = st.columns([5, 1])
        with _col_refresh:
            if st.button("🔄 Aggiorna", key="sator_refresh_snapshot", width="stretch"):
                st.rerun()
        with profile_step("Pianificazione/SATOR", "reference_summary"):
            _render_sator_reference_summary(latest_decision, theme, data, decisions_state.get("items") or [])

    render_section_title(
        "Mappa strumenti",
        comment="Rischio e rendimento storico osservato per ogni strumento posseduto o in osservazione, con segnalazione delle coppie molto correlate (possibile ridondanza). L'orizzonte del rendimento varia per strumento (12/6/3/1 mesi, il più lungo disponibile — vedi il tooltip di ogni punto). Nessuna previsione: solo comportamento passato.",
        gap_after="sm",
    )
    with profile_step("Pianificazione/SATOR", "instrument_map"):
        try:
            instrument_map = build_instrument_map(data, settings)
        except Exception:
            instrument_map = None
    if instrument_map is None:
        st.info("Mappa strumenti non disponibile su questi dati.")
    elif instrument_map.scatter_df.empty:
        st.info("Storico prezzi insufficiente per calcolare rischio/rendimento di almeno uno strumento dell'universo SATOR.")
    else:
        with profile_step("Pianificazione/SATOR", "instrument_map_chart", count=len(instrument_map.scatter_df)):
            fig_instrument_map = build_instrument_map_chart(instrument_map.scatter_df, theme)
            st.plotly_chart(fig_instrument_map, width="stretch", config={"displayModeBar": False})
        if instrument_map.redundant_pairs.empty:
            st.caption("Nessuna coppia di strumenti sopra la soglia di ridondanza (correlazione 0,90) nell'universo attuale.")
        else:
            st.markdown("**Coppie potenzialmente ridondanti**")
            display_pairs = instrument_map.redundant_pairs.rename(columns={
                "ticker_a": "Strumento A", "ticker_b": "Strumento B",
                "category_a": "Categoria A", "category_b": "Categoria B",
                "correlazione": "Correlazione",
            })[["Strumento A", "Categoria A", "Strumento B", "Categoria B", "Correlazione"]]
            display_pairs["Correlazione"] = display_pairs["Correlazione"].map(lambda v: fmt_num_it(v, 2))
            st.dataframe(display_pairs, hide_index=True, width="stretch")


def render_pianificazione(tab: DeltaGenerator, ctx: SimpleNamespace) -> None:
    """
    Scheda Pianificazione: obiettivo di portafoglio e SATOR.
    """
    theme = get_theme_context()
    settings = ctx.settings
    data = ctx.data

    with tab:

        with profile_step("Pianificazione", "intro"):
            _render_page_intro(
                t(settings, "page_intro.pianificazione.title", "Pianificazione"),
                t(settings, "page_intro.pianificazione.comment", "Simula acquisti, vendite e strumenti ipotetici prima di toccare il portafoglio reale. Le stime sono scenari, non previsioni."),
                "pianificazione",
                theme,
            )
        with st.container():
            with profile_step("Pianificazione", "obiettivo_section"):
                _render_portfolio_objective_section(ctx, theme)

        _section_line()
        with st.container():
            with profile_step("Pianificazione", "decision_dashboard_section"):
                _render_decision_dashboard_section(ctx, theme)

        with profile_step("Pianificazione", "footer"):
            back_to_top()
