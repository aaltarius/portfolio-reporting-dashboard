"""
ui/pages/pianificazione.py — Tab Pianificazione (t7): What-if simulator + liquidity planner
Pure rendering with pre-computed simulation data.
Fragment-based interactive components.
"""
import hashlib
from types import SimpleNamespace

import pandas as pd
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from core.cache import invalidate_portfolio_cache
from core.finance import compute_portfolio_state
from core.services.sator import (
    build_sator_matrix_frame,
    build_sator_decision_record,
    build_sator_universe_editor_frame,
    apply_sator_universe_editor_frame,
    fetch_sator_costs_from_web,
    compare_decision_to_actual,
    compute_current_bucket_mix,
    ensure_sator_metadata,
    ensure_sator_settings,
    run_sator_analysis,
    SATOR_STATE_VALUES,
    SATOR_ROLE_VALUES,
    SATOR_NATURE_VALUES,
    SATOR_STATE_LABELS,
    SATOR_ROLE_LABELS,
    SATOR_NATURE_LABELS,
    build_portfolio_rings_frame,
    compute_watchlist_reminders,
    build_next_purchase_bubble_frame,
    latest_sator_decision,
)
from persistence.storage import load_data, load_sator_decisions, load_settings, save_data, save_sator_decisions, save_settings
from ui.formatting import fmt_eur_it, fmt_pct_it
from ui.i18n import t
from ui.page_chrome import render_page_intro as render_page_intro_shared, render_section_line as render_section_line_shared
from ui.components import render_section_title, kpi_card, back_to_top, legend_block, render_styled_table
from ui.charts.tables import color_pl
from ui.charts.natura_icons import get_natura_visual
from core.instrument_classification import suggest_tipo_correction
from ui.charts.pianificazione import (
    build_composition_donut_chart,
    build_ante_post_bucket_chart,
    build_objective_mix_chart,
    build_allocation_rings_chart,
    build_next_purchase_bubble_chart,
)
from ui.sator_matrix import (
    SATOR_MATRIX_COLUMNS,
    SATOR_MATRIX_DISABLED_COLUMNS,
    sator_matrix_column_config,
    sator_matrix_height,
)
from ui.theme import bucket_color, get_theme_context
from ui.notifications import queue_success
from ui.ux_helpers import confirm_danger, render_danger_hint

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


# LEGACY_REVIEW 2026-07-26: helper del vecchio modulo SATOR interno.
# La pagina Pianificazione non richiama piu' _render_sator_module; SATOR e'
# definitivo su sidebar/form-server. Tenere questi helper solo per confronto
# e rimozione controllata nella prossima revisione.
def _render_sator_alerts(alerts: list[dict[str, str]]) -> None:
    for alert in alerts or []:
        level = str(alert.get("level") or "info")
        text = f"**{alert.get('title', 'Alert')}** - {alert.get('message', '')}"
        if level == "warning":
            st.warning(text)
        elif level == "error":
            st.error(text)
        else:
            st.info(text)


_EXPLAIN_COLS_TEMPLATES = {
    2: "minmax(90px,160px) 1fr",
    3: "minmax(70px,100px) 1fr minmax(80px,120px)",
    4: "minmax(70px,100px) 1fr minmax(50px,70px) minmax(80px,110px)",
}


def _build_sator_explain_html(rows: list[tuple[str, object]], title: str | None = None) -> str:
    """Costruisce l'HTML del riquadro chiave/testo (puro, senza st.markdown,
    per essere testabile). Se il testo e' una lista, ogni voce va a capo su
    una riga propria. Se una voce e' a sua volta una tupla di campi (invece
    di una stringa), i campi si allineano in colonne a larghezza fissa
    (grid CSS) cosi' ticker/natura/importo restano leggibili invece di
    un'unica riga di testo unita da punto e virgola."""
    title_html = f'<div class="sator-explain-title">{title}</div>' if title else ""
    blocks = []
    for key, text in rows:
        if isinstance(text, (list, tuple)):
            lines_html = []
            for line in text:
                if isinstance(line, (list, tuple)):
                    fields = [str(f) for f in line]
                    template = _EXPLAIN_COLS_TEMPLATES.get(len(fields), " ".join(["1fr"] * len(fields)))
                    spans = "".join(f"<span>{field}</span>" for field in fields)
                    lines_html.append(
                        f'<div class="sator-explain-line sator-explain-line--cols" '
                        f'style="grid-template-columns:{template}">{spans}</div>'
                    )
                else:
                    lines_html.append(f'<div class="sator-explain-line">{line}</div>')
            text_html = "".join(lines_html)
        else:
            text_html = str(text)
        blocks.append(
            f'<div class="sator-explain-row"><div class="sator-explain-key">{key}</div>'
            f'<div class="sator-explain-text">{text_html}</div></div>'
        )
    return f'<div class="sator-explain">{title_html}{"".join(blocks)}</div>'


def _render_sator_explain_box(rows: list[tuple[str, object]], title: str | None = None) -> None:
    """Vedi _build_sator_explain_html per la logica di costruzione dell'HTML."""
    st.markdown(_build_sator_explain_html(rows, title), unsafe_allow_html=True)


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


def _build_combo_kpis(combo_df: pd.DataFrame, budget: float) -> dict[str, float]:
    if combo_df is None or combo_df.empty:
        return {"total": 0.0, "delta": -float(budget), "fit": 0.0, "momentum": 0.0, "risk": 0.0, "diversification": 0.0}
    total = float(pd.to_numeric(combo_df["Importo"], errors="coerce").fillna(0.0).sum())
    return {
        "total": total,
        "delta": total - float(budget),
        "fit": float(pd.to_numeric(combo_df["Fit"], errors="coerce").fillna(0.0).mean()),
        "momentum": float(pd.to_numeric(combo_df["Momentum"], errors="coerce").fillna(0.0).mean()),
        "risk": float(pd.to_numeric(combo_df["Rischio"], errors="coerce").fillna(0.0).mean()),
        "diversification": float(pd.to_numeric(combo_df["Diversificazione"], errors="coerce").fillna(0.0).mean()),
    }


def _build_manual_choice_feedback(combo_df: pd.DataFrame, budget: float) -> tuple[str, list[str]]:
    if combo_df is None or combo_df.empty:
        return "Nessuna scelta costruita", ["Seleziona almeno uno strumento e inserisci le quote per ottenere un giudizio."]
    metrics = _build_combo_kpis(combo_df, budget)
    notes: list[str] = []
    underuse_limit = max(50.0, float(budget) * 0.10) if budget > 0 else 0.0
    over_tolerance = max(1.0, float(budget) * 0.05) if budget > 0 else 0.0
    if metrics["delta"] > over_tolerance:
        notes.append(f"La combinazione supera il budget di {fmt_eur_it(metrics['delta'], 2)}.")
        notes.append(f"Lo scostamento e' oltre la tolleranza operativa del 5% ({fmt_eur_it(over_tolerance, 2)}): va ridotta prima di considerarla coerente.")
    elif metrics["delta"] > 0:
        notes.append(f"La combinazione supera il budget di {fmt_eur_it(metrics['delta'], 2)}, ma resta entro la tolleranza operativa del 5%.")
        notes.append("Trattala come appena fuori budget: verifica prezzo reale e commissioni prima di eseguire l'ordine.")
    elif metrics["delta"] < -underuse_limit:
        used_pct = (metrics["total"] / float(budget) * 100.0) if budget > 0 else 0.0
        notes.append(f"La combinazione usa {fmt_eur_it(metrics['total'], 2)} su {fmt_eur_it(float(budget), 2)} ({used_pct:.0f}%): lontana dal budget impostato.")
        notes.append("Se non e' una scelta volutamente prudente, valuta di avvicinarti al budget o di rivedere la selezione.")
    else:
        notes.append(f"La combinazione resta entro budget con margine di {fmt_eur_it(abs(metrics['delta']), 2)}.")
    if metrics["fit"] >= 0.62:
        notes.append("La coerenza strategica media e' buona.")
    else:
        notes.append("La coerenza strategica media non e' ancora alta.")
    if metrics["diversification"] >= 0.58:
        notes.append("La selezione migliora in modo apprezzabile la diversificazione.")
    else:
        notes.append("Il beneficio di diversificazione e' modesto: attenzione a non aggiungere linee ridondanti.")
    if metrics["risk"] >= 0.58:
        notes.append("Il profilo rischio/rendimento resta equilibrato.")
    else:
        notes.append("La combinazione e' piu' aggressiva o meno efficiente sul rischio.")
    if metrics["delta"] > over_tolerance:
        headline = "Fuori budget"
    elif metrics["delta"] > 0:
        headline = "Appena fuori budget"
    elif metrics["delta"] < -underuse_limit:
        headline = "Budget sottoutilizzato"
    else:
        headline = "Scelta coerente" if metrics["fit"] >= 0.62 and metrics["risk"] >= 0.50 else "Scelta da rivedere"
    return headline, notes


def _build_sator_master_table(ranking_df: pd.DataFrame, budget: float, manual_alloc: dict[str, int] | None = None, max_lines: int = 5) -> pd.DataFrame:
    """LEGACY_REVIEW: usato solo dal vecchio modulo SATOR in-page."""
    return build_sator_matrix_frame(ranking_df, budget=budget, manual_alloc=manual_alloc, max_lines=int(max_lines))


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

    state_df = compute_portfolio_state(data, include_closed=True).get("df", pd.DataFrame())
    current_mix = compute_current_bucket_mix(data, state_df)
    _render_objective_mix_chart(objective, current_mix, theme)


def _render_objective_mix_chart(objective: dict, current_mix: dict, theme) -> None:
    """Obiettivo vs mix attuale: builder centralizzato in ui/charts/pianificazione.py,
    layout governato da ui/charts/settings.py (chart_id pianificazione_obiettivo_mix)."""
    fig = build_objective_mix_chart(objective, current_mix, theme)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def _satellite_target_from_objective(settings: dict) -> float:
    """LEGACY_REVIEW: helper del vecchio giudizio ordine SATOR in-page."""
    objective = (settings or {}).get("portfolio_objective", {})
    return float(objective.get("satellite", 0.20) or 0.20)


def _render_sator_order_evaluation(combo_df: pd.DataFrame, budget: float, settings: dict, theme) -> None:
    if combo_df is None or combo_df.empty:
        return
    importi = pd.to_numeric(combo_df["Importo"], errors="coerce").fillna(0.0)
    totale = float(importi.sum())
    if totale <= 0:
        return
    per_bucket = combo_df.assign(Importo=importi).groupby("Bucket")["Importo"].sum()
    quota = {b: float(per_bucket.get(b, 0.0)) / totale for b in ("Core", "Difensivo", "Satellite")}
    tetto_sat = _satellite_target_from_objective(settings)

    render_section_title(
        "Valutazione dell'ordine sul tuo obiettivo di portafoglio",
        comment=f"Composizione della scelta e lettura rispetto all'obiettivo Satellite {fmt_pct_it(tetto_sat, 0)}.",
        gap_after="sm",
    )
    col_grafico, col_lettura = st.columns([1.1, 1.0], gap="medium")

    with col_grafico:
        per_bucket_chart = per_bucket.reindex(["Core", "Difensivo", "Satellite"]).fillna(0.0)
        _render_composition_chart(per_bucket_chart, theme)

    with col_lettura:
        c1, c2, c3 = st.columns(3, gap="small")
        with c1:
            kpi_card("Core", fmt_pct_it(quota["Core"], 1), fmt_eur_it(float(per_bucket.get("Core", 0.0)), 2), accent=theme.color_blue)
        with c2:
            kpi_card("Difensivo", fmt_pct_it(quota["Difensivo"], 1), fmt_eur_it(float(per_bucket.get("Difensivo", 0.0)), 2), accent=theme.color_green)
        with c3:
            sat_accent = theme.color_red if quota["Satellite"] > tetto_sat + 1e-9 else theme.color_orange
            kpi_card("Satellite", fmt_pct_it(quota["Satellite"], 1), fmt_eur_it(float(per_bucket.get("Satellite", 0.0)), 2), accent=sat_accent)

        letture: list[str] = []
        if quota["Satellite"] > tetto_sat + 1e-9:
            letture.append(
                f"La quota satellite e' {fmt_pct_it(quota['Satellite'], 1)}, sopra l'obiettivo "
                f"{fmt_pct_it(tetto_sat, 0)}: valuta se ridurre i satelliti o aumentare core/difensivo."
            )
        else:
            letture.append(
                f"La quota satellite {fmt_pct_it(quota['Satellite'], 1)} resta entro l'obiettivo "
                f"{fmt_pct_it(tetto_sat, 0)}."
            )
        if quota["Core"] >= 0.50:
            letture.append("Il nucleo core domina l'ordine: scelta coerente con un'impostazione disciplinata.")
        if quota["Difensivo"] <= 0.05 and tetto_sat <= 0.10:
            letture.append("La componente difensiva e' minima: per un profilo prudente potresti destinarle piu' spazio.")
        nuovi = int((combo_df["Stato"] != "in_portafoglio").sum()) if "Stato" in combo_df.columns else 0
        if nuovi:
            letture.append(f"L'ordine introduce {nuovi} nuovo/i ingresso/i rispetto al portafoglio attuale.")
        legend_block("<br>".join(letture), variant="bottom")
    _render_bucket_detail_box(combo_df, importi)


def _render_bucket_detail_box(combo_df: pd.DataFrame, importi: pd.Series) -> None:
    work = combo_df.assign(Importo=importi).copy()
    rows: list[tuple[str, object]] = []
    for bucket in ("Core", "Difensivo", "Satellite"):
        part = work[work["Bucket"] == bucket]
        if part.empty:
            rows.append((bucket, "Nessuna quota selezionata."))
            continue
        totale = float(pd.to_numeric(part["Importo"], errors="coerce").fillna(0.0).sum())
        righe: list[str | tuple[str, str, str, str]] = [f"<b>Totale {fmt_eur_it(totale, 2)}</b>"]
        righe += [
            (str(r["Ticker"]), str(r["Funzione"]), f"{int(r['Quote'])}q", fmt_eur_it(float(r["Importo"]), 2))
            for _, r in part.iterrows()
        ]
        rows.append((bucket, righe))
    _render_sator_explain_box(rows, title="Dettaglio composizione ordine")


def _build_sator_reference_summary_html(latest: dict, theme, data: dict) -> str:
    """Card per 'Fotografia di riferimento' sotto la mappa a bolle dei
    prossimi acquisti: stessi campi gia' salvati da build_sator_decision_record
    (core/services/sator.py), nessuna nuova lettura di dati (solo lookup natura
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

    note_html = f'<span class="ref-snapshot-note">{note}</span>' if note else ''
    mix_html = f'<div class="ref-snapshot-mix">{mix_rows_html}</div>' if mix_rows_html else ''
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
        f'{mix_html}'
        f'{lines_html}'
        '</div>'
        '</div>'
    )


def _render_sator_reference_summary(latest: dict, theme, data: dict) -> None:
    st.markdown(_build_sator_reference_summary_html(latest, theme, data), unsafe_allow_html=True)


def _render_composition_chart(per_funzione: pd.Series, theme) -> None:
    """Donut della composizione Core/Difensivo/Satellite: builder centralizzato in
    ui/charts/pianificazione.py, layout governato da ui/charts/settings.py
    (chart_id pianificazione_composizione)."""
    if per_funzione is None or per_funzione.empty:
        return
    fig = build_composition_donut_chart(per_funzione, theme)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def _weighted_average(df: pd.DataFrame, value_col: str, amount_col: str = "Importo") -> float:
    if df is None or df.empty or value_col not in df.columns:
        return 0.0
    values = pd.to_numeric(df[value_col], errors="coerce").fillna(0.0)
    weights = pd.to_numeric(df.get(amount_col, 0.0), errors="coerce").fillna(0.0)
    total_weight = float(weights.sum())
    if total_weight <= 0:
        return float(values.mean()) if len(values) else 0.0
    return float((values * weights).sum() / total_weight)


def _build_sator_suggested_combo(master_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if master_df is None or master_df.empty:
        return pd.DataFrame(rows)
    for _, row in master_df.iterrows():
        qty_raw = pd.to_numeric(row.get("Sug", 0), errors="coerce")
        qty = int(qty_raw) if pd.notna(qty_raw) else 0
        if qty <= 0:
            continue
        price_raw = pd.to_numeric(row.get("_price", 0.0), errors="coerce")
        price = float(price_raw) if pd.notna(price_raw) else 0.0
        voto_raw = pd.to_numeric(row.get("Voto", 0.0), errors="coerce")
        rows.append({
            "Ticker": str(row.get("_ticker", "")),
            "Strumento": str(row.get("_name", row.get("_ticker", ""))),
            "Quote": qty,
            "Prezzo": price,
            "Importo": price * qty,
            "Voto": float(voto_raw) if pd.notna(voto_raw) else 0.0,
            "Bucket": str(row.get("_bucket", "")),
            "Funzione": str(row.get("_funzione", "")),
        })
    return pd.DataFrame(rows)


def _bucket_mix_text(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "nessuna composizione"
    importi = pd.to_numeric(df["Importo"], errors="coerce").fillna(0.0)
    total = float(importi.sum())
    per_bucket = df.assign(Importo=importi).groupby("Bucket")["Importo"].sum().reindex(["Core", "Difensivo", "Satellite"]).fillna(0.0)
    return " / ".join(
        f"{bucket}: {fmt_pct_it(float(value) / total, 1) if total > 0 else '0,0%'}"
        for bucket, value in per_bucket.items()
    )


def _render_sator_package_comparison(combo_df: pd.DataFrame, master_df: pd.DataFrame, budget: float, theme) -> None:
    """Confronta la scelta manuale dell'utente con la proposta automatica di SATOR.

    Il metro e' il voto ponderato per importo (un voto alto su una linea piccola
    pesa poco) piu' il rispetto del budget. Serve a rispondere a una domanda
    pratica: la combinazione che ho costruito a mano e' migliore, peggiore o
    uguale a quella che SATOR avrebbe suggerito da solo?
    """
    if combo_df is None or combo_df.empty:
        return
    suggested_df = _build_sator_suggested_combo(master_df)
    if suggested_df.empty:
        _render_sator_explain_box(
            [("Confronto", "SATOR non ha una proposta automatica valida entro budget da confrontare con la scelta manuale.")],
            title="Confronto scelta manuale vs proposta SATOR",
        )
        return

    manual_total = float(pd.to_numeric(combo_df["Importo"], errors="coerce").fillna(0.0).sum())
    sator_total = float(pd.to_numeric(suggested_df["Importo"], errors="coerce").fillna(0.0).sum())
    manual_vote = _weighted_average(combo_df, "Voto")
    sator_vote = _weighted_average(suggested_df, "Voto")
    vote_delta = manual_vote - sator_vote
    tolerance = max(1.0, float(budget) * 0.05) if budget > 0 else 0.0
    manual_ok = manual_total <= float(budget) + tolerance
    sator_ok = sator_total <= float(budget) + tolerance
    if vote_delta >= 0.15 and manual_ok:
        esito = "Meglio della proposta SATOR"
        accent = theme.color_green
    elif vote_delta <= -0.15 or (not manual_ok and sator_ok):
        esito = "Peggio della proposta SATOR"
        accent = theme.color_red
    else:
        esito = "Equivalente alla proposta SATOR"
        accent = theme.color_orange

    manual_tickers = set(combo_df["Ticker"].astype(str))
    sator_tickers = set(suggested_df["Ticker"].astype(str))
    overlap = len(manual_tickers & sator_tickers)
    render_section_title(
        "Confronto scelta manuale vs proposta SATOR",
        comment="Misura se il pacchetto che hai costruito migliora, peggiora o replica la proposta automatica.",
        gap_after="sm",
    )
    c1, c2, c3 = st.columns(3, gap="small")
    with c1:
        kpi_card("Esito", esito, f"delta voto {vote_delta:+.2f}", accent=accent)
    with c2:
        kpi_card("Voto ponderato", f"{manual_vote:.1f} vs {sator_vote:.1f}", "manuale / SATOR", accent=theme.color_blue)
    with c3:
        kpi_card(
            "Importo",
            f"{fmt_eur_it(manual_total, 2)} vs {fmt_eur_it(sator_total, 2)}",
            f"overlap {overlap}/{max(1, len(sator_tickers))}",
            accent=theme.color_orange,
        )

    only_manual = sorted(manual_tickers - sator_tickers)
    only_sator = sorted(sator_tickers - manual_tickers)
    rows = [
        ("Qualita'", [
            f"La tua scelta &middot; voto medio ponderato {manual_vote:.2f}.",
            f"Proposta SATOR &middot; voto medio ponderato {sator_vote:.2f}.",
            f"Differenza &middot; {vote_delta:+.2f}.",
        ]),
        ("Budget", [
            f"La tua scelta &middot; {fmt_eur_it(manual_total, 2)}.",
            f"Proposta SATOR &middot; {fmt_eur_it(sator_total, 2)}.",
            f"Tolleranza operativa &middot; {fmt_eur_it(tolerance, 2)}.",
        ]),
        ("Composizione", [f"La tua scelta &middot; {_bucket_mix_text(combo_df)}", f"SATOR &middot; {_bucket_mix_text(suggested_df)}"]),
        ("Solo nella tua scelta", only_manual or ["nessuno"]),
        ("Solo in SATOR", only_sator or ["nessuno"]),
    ]
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    _render_sator_explain_box(rows, title="Lettura del confronto")


def _render_ante_post_bucket_chart(bucket_df: pd.DataFrame, theme) -> None:
    """Mix Core/Difensivo/Satellite prima/dopo: builder centralizzato in
    ui/charts/pianificazione.py, layout governato da ui/charts/settings.py
    (chart_id pianificazione_ante_post)."""
    if bucket_df is None or bucket_df.empty:
        return
    fig = build_ante_post_bucket_chart(bucket_df, theme)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def _render_decision_dashboard_section(ctx: SimpleNamespace, theme) -> None:
    """Dashboard decisionale: 3 grafici indipendenti dal modulo SATOR
    congelato (_render_sator_module, in via di dismissione a favore della
    pagina SATOR attiva in sidebar). Usa solo il portafoglio corrente e
    l'ultima fotografia SATOR salvata su disco, mai lo stato di sessione
    del modulo congelato."""
    data = ctx.data
    settings = ctx.settings
    ensure_sator_metadata(data)
    state_df = compute_portfolio_state(data, include_closed=True).get("df", pd.DataFrame())

    rings_df = build_portfolio_rings_frame(data, state_df)

    held_tickers = set(rings_df["ticker"]) if not rings_df.empty else set()
    warnings: list[str] = []
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
        fig_rings = build_allocation_rings_chart(rings_df, objective, theme)
        st.plotly_chart(fig_rings, width="stretch", config={"displayModeBar": False})
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
        comment="Dati dall'ultima fotografia SATOR salvata (Storico decisionale piu' sotto, o dalla pagina SATOR attiva in sidebar) — non da un'analisi dal vivo.",
        gap_after="sm",
    )
    decisions_state = load_sator_decisions()
    bubble_df, missing_tickers = build_next_purchase_bubble_frame(data)
    if not (decisions_state.get("items") or []):
        st.info("Nessuna fotografia SATOR salvata: apri il modulo SATOR piu' sotto (o la pagina SATOR in sidebar) e salva una decisione per popolare questa mappa.")
    elif bubble_df.empty:
        st.info("L'ultima fotografia SATOR salvata non contiene ancora i punteggi necessari per questa mappa: salvane una nuova per popolarla.")
    else:
        if missing_tickers:
            st.warning("Dati insufficienti nell'ultima fotografia per: " + ", ".join(missing_tickers) + ". Salva una fotografia aggiornata per includerli.")
        fig_bubble = build_next_purchase_bubble_chart(bubble_df, theme)
        st.plotly_chart(fig_bubble, width="stretch", config={"displayModeBar": False})
        legend_block(
            "Quadranti: in basso a destra = buon contributo difensivo; in alto a destra = diversifica ma aumenta volatilita'; "
            "in alto a sinistra = satellite aggressivo/ridondante; in basso a sinistra = poco utile/non prioritario. "
            "Dimensione bolla = importo proposto nella fotografia.",
            variant="bottom",
        )
    latest_decision = latest_sator_decision(decisions_state.get("items") or [])
    if latest_decision:
        _col_spacer, _col_refresh = st.columns([5, 1])
        with _col_refresh:
            if st.button("🔄 Aggiorna", key="sator_refresh_snapshot", width="stretch"):
                st.rerun()
        _render_sator_reference_summary(latest_decision, theme, data)


def _render_sator_ante_post(combo_df: pd.DataFrame, master_df: pd.DataFrame, budget: float, theme) -> None:
    """Mostra come l'ordine sposta il mix Core/Difensivo/Satellite, prima e dopo.

    Attenzione al perimetro: il confronto e' calcolato sul SOLO universo ETF/ETC
    mostrato in tabella (valore attuale = quote possedute x prezzo), non sull'intero
    patrimonio. Serve a capire la direzione impressa dall'ordine, non a fotografare
    l'asset allocation complessiva.
    """
    if combo_df is None or combo_df.empty or master_df is None or master_df.empty:
        return
    base = master_df.copy()
    base["_price_num"] = pd.to_numeric(base.get("_price", 0.0), errors="coerce").fillna(0.0)
    base["_qp_num"] = pd.to_numeric(base.get("Qp", 0.0), errors="coerce").fillna(0.0)
    base["Valore prima"] = base["_qp_num"] * base["_price_num"]
    buy_amount = combo_df.groupby("Ticker")["Importo"].sum()
    buy_quotes = combo_df.groupby("Ticker")["Quote"].sum()
    base["Acquisto"] = base["_ticker"].astype(str).map(buy_amount).fillna(0.0)
    base["Quote buy"] = base["_ticker"].astype(str).map(buy_quotes).fillna(0.0)
    base["Valore dopo"] = base["Valore prima"] + base["Acquisto"]
    bucket = (
        base.groupby("_bucket")[["Valore prima", "Acquisto", "Valore dopo"]]
        .sum()
        .reindex(["Core", "Difensivo", "Satellite"])
        .fillna(0.0)
    )
    total_before = float(bucket["Valore prima"].sum())
    total_after = float(bucket["Valore dopo"].sum())
    bucket["% prima"] = bucket["Valore prima"].map(lambda v: float(v) / total_before if total_before > 0 else 0.0)
    bucket["% dopo"] = bucket["Valore dopo"].map(lambda v: float(v) / total_after if total_after > 0 else 0.0)
    bucket["Delta pp"] = (bucket["% dopo"] - bucket["% prima"]) * 100.0

    render_section_title(
        "Ante-post compositivo",
        comment="Confronto percentuale prima/dopo sul solo universo ETF/ETC SATOR mostrato in tabella.",
        gap_after="sm",
    )
    col_chart, col_text = st.columns([1.15, 1.0], gap="medium")
    with col_chart:
        _render_ante_post_bucket_chart(bucket, theme)
    with col_text:
        direzione = [
            f"{idx} &middot; {fmt_pct_it(float(row['% prima']), 1)} &rarr; {fmt_pct_it(float(row['% dopo']), 1)} ({float(row['Delta pp']):+.1f} pp)"
            for idx, row in bucket.iterrows()
        ]
        rows: list[tuple[str, object]] = [
            ("Patrimonio", f"Prima {fmt_eur_it(total_before, 2)}; dopo {fmt_eur_it(total_after, 2)}; ordine {fmt_eur_it(float(combo_df['Importo'].sum()), 2)}."),
            ("Direzione", direzione),
        ]
        nuove = combo_df[(combo_df["Stato"] != "in_portafoglio") | (pd.to_numeric(combo_df["Quote possedute"], errors="coerce").fillna(0.0) <= 0)]
        if not nuove.empty:
            rows.append(("New entry", [(str(r["Ticker"]), f"apre {r['Funzione']} ({int(r['Quote'])}q)") for _, r in nuove.iterrows()]))
        else:
            rows.append(("New entry", "Nessuna nuova linea: l'ordine incrementa strumenti gia' presenti."))
        _render_sator_explain_box(rows, title="Lettura ante-post")

    table = bucket.reset_index().rename(columns={"_bucket": "Bucket"})
    styled_bucket = (
        table.style
        .format({
            "Valore prima": lambda v: fmt_eur_it(v, 2),
            "Acquisto": lambda v: fmt_eur_it(v, 2),
            "Valore dopo": lambda v: fmt_eur_it(v, 2),
            "% prima": lambda v: fmt_pct_it(v, 1),
            "% dopo": lambda v: fmt_pct_it(v, 1),
            "Delta pp": lambda v: f"{float(v):+.1f}",
        })
        .set_properties(**{"text-align": "center"})
        .set_properties(subset=["Bucket"], **{"text-align": "left", "font-weight": "700"})
        .set_table_styles([{"selector": "th", "props": [("text-align", "center"), ("font-weight", "700")]}], overwrite=False)
    )
    render_styled_table(styled_bucket, height="content", static=True)


def _render_sator_universe_editor(ctx: SimpleNamespace) -> None:
    """LEGACY_REVIEW: editor usato dal vecchio modulo SATOR in-page.

    Tabella per inserire, una volta sola, classificazione e costi di ogni
    strumento: natura/funzione, TER, spread, zero-commissioni. I valori salvati
    qui contano come scelte dell'utente e non vengono piu' sovrascritti
    dall'inferenza automatica. TER e Spread si inseriscono in percentuale
    (es. 0,20 = 0,20%)."""
    data = ctx.data
    # La pagina usa uno StateManager cache-ato: se i costi sono stati appena
    # salvati o un'altra istanza Streamlit e' aperta, riallinea i metadati SATOR
    # dal file prima di costruire il data_editor.
    try:
        fresh_data = load_data()
        fresh_master = fresh_data.get("instrument_master", {}) if isinstance(fresh_data, dict) else {}
        if isinstance(fresh_master, dict):
            data.setdefault("instrument_master", {})
            current_tickers = {str(item.get("ticker") or "").strip().upper() for item in data.get("strumenti", []) or []}
            for ticker, meta in fresh_master.items():
                tk = str(ticker or "").strip().upper()
                if tk in current_tickers and isinstance(meta, dict):
                    data["instrument_master"][tk] = meta
    except Exception:
        pass
    with st.expander("Universo SATOR: classificazione e costi", expanded=False):
        st.caption(
            "Imposta qui i costi reali (TER, spread) e il flag zero-commissioni di ogni strumento: "
            "finche' restano a zero, il fattore Costo non riesce a distinguere i titoli. "
            "Puoi anche correggere natura e funzione. Dopo aver salvato, rilancia l'analisi."
        )
        col_btn, col_chk = st.columns([1.4, 1.0], gap="small")
        with col_btn:
            recupera = st.button("Recupera costi dalla rete (TER + spread)", key="sator_fetch_ter", width="stretch",
                                 help="Scarica da Yahoo il TER (sempre) e lo spread da bid/ask (solo a mercato aperto e se plausibile).")
        with col_chk:
            anche_presenti = st.checkbox("Riscarica anche i TER gia' inseriti", value=False, key="sator_fetch_overwrite")
        if recupera:
            with st.spinner("Recupero costi in corso..."):
                esito = fetch_sator_costs_from_web(data, only_missing=not anche_presenti)
            if esito["ter_trovati"] or esito["spread_trovati"]:
                save_data(data)
                invalidate_portfolio_cache("sator universe updated")
            if esito["ter_trovati"]:
                st.success("TER trovati: " + ", ".join(esito["ter_trovati"]))
            if esito["spread_trovati"]:
                st.success("Spread trovati (mercato aperto): " + ", ".join(esito["spread_trovati"]))
            else:
                st.info("Nessuno spread acquisito: a mercato chiuso i bid/ask non sono affidabili. Rilancia in orario di Borsa per popolarlo; resta comunque facoltativo.")
            if esito["non_trovati"]:
                st.warning(
                    "Nessun costo trovato per (inseriscili a mano o lasciali a zero): "
                    + ", ".join(esito["non_trovati"])
                )
            if esito["ter_trovati"] or esito["spread_trovati"] or esito["saltati"]:
                st.session_state.pop("sator_result", None)
                st.rerun()

        editor_df = build_sator_universe_editor_frame(data)
        if editor_df is None or editor_df.empty:
            st.info("Nessuno strumento da configurare.")
            return
        signature_cols = [
            "Ticker", "Attivo SATOR", "Stato", "Natura", "Ruolo",
            "Zero commissioni", "TER %", "Spread %",
        ]
        signature_payload = editor_df[[c for c in signature_cols if c in editor_df.columns]].to_json(
            orient="split", force_ascii=True
        )
        editor_key = "sator_universe_editor_" + hashlib.sha1(signature_payload.encode("utf-8")).hexdigest()[:12]
        st.caption("Modifica liberamente le celle: nulla si ricarica finche' non premi Salva.")
        with st.form("sator_universe_form", clear_on_submit=False):
            edited = st.data_editor(
                editor_df,
                width="stretch",
                hide_index=True,
                num_rows="fixed",
                key=editor_key,
                column_config={
                    "Ticker": st.column_config.TextColumn("Tk", disabled=True, width=80),
                    "Nome": st.column_config.TextColumn("Nome", disabled=True, width=220),
                    "Attivo SATOR": st.column_config.CheckboxColumn("Attivo", help="Se spento, lo strumento e' ignorato da SATOR", width=60),
                    "Stato": st.column_config.SelectboxColumn("Stato", options=list(SATOR_STATE_VALUES), width=130, format_func=lambda v: SATOR_STATE_LABELS.get(v, v)),
                    "Natura": st.column_config.SelectboxColumn("Natura", options=list(SATOR_NATURE_VALUES), width=180, format_func=lambda v: SATOR_NATURE_LABELS.get(v, v)),
                    "Ruolo": st.column_config.SelectboxColumn("Ruolo", options=list(SATOR_ROLE_VALUES), width=160, format_func=lambda v: SATOR_ROLE_LABELS.get(v, v)),
                    "Zero commissioni": st.column_config.CheckboxColumn("Zero comm.", help="Spunta se su Fineco lo compri senza commissioni; altrimenti il costo e' il TER", width=90),
                    "TER %": st.column_config.NumberColumn("TER %", help="Costo corrente annuo, in percentuale (es. 0,20)", min_value=0.0, step=0.01, format="%.3f", width=80),
                    "Spread %": st.column_config.NumberColumn("Spread %", help="Spread indicativo, in percentuale (facoltativo, lo riempie il recupero costi)", min_value=0.0, step=0.01, format="%.3f", width=80),
                },
            )
            salva = st.form_submit_button("Salva universo SATOR", width="stretch")
        if salva:
            n = apply_sator_universe_editor_frame(data, pd.DataFrame(edited))
            if n:
                save_data(data)
                invalidate_portfolio_cache("sator universe updated")
            st.session_state.pop("sator_result", None)  # forza un ricalcolo pulito
            st.success(f"Salvati i parametri di {n} strumento/i. Rilancia l'analisi per applicarli.")


def _render_sator_module(ctx: SimpleNamespace, theme) -> None:
    """LEGACY_REVIEW: vecchio SATOR interno, non chiamato da render_pianificazione."""
    settings = ctx.settings
    if str((settings or {}).get("sator_mode", "entrambi")) == "sidebar":
        return
    data = ctx.data
    ensure_sator_metadata(data)
    sator_cfg = ensure_sator_settings(settings)
    render_section_title(
        "SATOR - Strategic Allocation Tactical Order Recommender",
        comment=(
            "SATOR confronta solo ETF ed ETC e assegna a ciascuno un voto unico 1-10, scomposto nei cinque fattori. "
            "Il voto ordina la tabella: il numero che leggi e' quello che decide la posizione. Per ogni funzione il modulo "
            "dice quale strumento ha vinto, contro chi e su quale fattore. Imposta Sel e Qta e premi Esegui: SATOR misura la "
            "qualita' delle scelte, non decide al posto tuo."
        ),
        gap_after="sm",
    )

    # Applica richiesta di import da foto prima che i widget vengano istanziati
    if "_sator_import_request" in st.session_state:
        _req = st.session_state.pop("_sator_import_request")
        st.session_state["sator_budget"] = _req["budget"]
        st.session_state["sator_manual_alloc"] = _req["alloc"]
        st.session_state.pop("sator_master_table_editor", None)
        try:
            st.session_state["sator_result"] = run_sator_analysis(
                data, settings,
                budget=_req["budget"],
                selected_categories=["ETF", "ETC"],
                concentration_severity=float(st.session_state.get("sator_severita", 1.0)),
            )
        except Exception:
            st.session_state.pop("sator_result", None)

    col_budget, col_sev, col_lines = st.columns([1.3, 1.0, 1.0], gap="small")
    with col_budget:
        budget = st.number_input(
            "Budget mensile", min_value=0.0,
            value=float(st.session_state.get("sator_budget", sator_cfg.get("budget_preset", 900.0))),
            step=50.0, format="%.2f", key="sator_budget",
        )
    with col_sev:
        severita = st.slider(
            "Severita concentrazione", min_value=0.0, max_value=2.0,
            value=float(st.session_state.get("sator_severita", 1.0)), step=0.1, key="sator_severita",
            help="Quanto SATOR penalizza i titoli che gia' possiedi in grande quantita'. 0 = la ignora, 1 = standard, 2 = doppia.",
        )
    with col_lines:
        max_righe = st.number_input(
            "Max righe suggerite", min_value=1, max_value=12,
            value=int(st.session_state.get("sator_max_righe", 5)), step=1, key="sator_max_righe",
            help="Numero massimo di funzioni servite dalle quote suggerite (il resto resta liquido).",
        )

    _render_sator_universe_editor(ctx)

    if st.button("Analizza strumenti SATOR", key="sator_run", width="stretch"):
        st.session_state["sator_result"] = run_sator_analysis(
            data, settings, budget=float(budget), selected_categories=["ETF", "ETC"],
            concentration_severity=float(severita),
        )

    with st.expander("Storico decisionale SATOR", expanded=False):
        decisions_state = load_sator_decisions()
        items = list(decisions_state.get("items", []))
        note = st.text_input("Nota fotografia decisionale", value="", key="sator_decision_note")
        _payload = st.session_state.get("sator_result")
        _alloc = {t: int(q) for t, q in st.session_state.get("sator_manual_alloc", {}).items() if int(q) > 0}
        _can_save = bool(_payload) and bool(_alloc)
        if st.button("Salva fotografia decisionale corrente", key="sator_save_decision", width="stretch") and _can_save:
            _ranking = _payload.get("ranking", pd.DataFrame())
            order_lines = []
            for _ticker, _qty in _alloc.items():
                _row = _ranking[_ranking["ticker"].astype(str) == str(_ticker)] if not _ranking.empty else pd.DataFrame()
                if _row.empty:
                    continue
                _r = _row.iloc[0]
                _price = float(_r.get("unit_price", 0))
                order_lines.append({
                    "ticker": str(_ticker),
                    "isin": str(_r.get("isin", "") or ""),
                    "name": str(_r.get("name", _ticker)),
                    "shares": _qty,
                    "price": _price,
                    "amount": _price * _qty,
                })
            if order_lines:
                items.append(build_sator_decision_record(_payload, order_lines=order_lines, budget=float(budget), note=note))
                decisions_state["items"] = items
                save_sator_decisions(decisions_state)
                queue_success("Fotografia decisionale salvata.")
                st.rerun()
        if items:
            labels = [f"{item.get('month_id', 'n/d')} - {item.get('decision_id', '')}" for item in items]
            selected_idx = st.selectbox("Decisione salvata", range(len(items)), format_func=lambda idx: labels[idx], key="sator_saved_decision_idx")
            decision = items[int(selected_idx)]
            if decision.get("note"):
                st.caption(decision["note"])

            # ── Metriche della decisione salvata ──────────────────────────────
            _budget_sal = float(decision.get("budget") or 0.0)
            _imp_ord = float(decision.get("importo_ordine") or sum(
                float(l.get("amount") or 0.0) for l in decision.get("order_lines", [])
            ))
            _giudizio = decision.get("giudizio") or {}
            _voto_medio = float(_giudizio.get("voto_medio") or 0.0)
            _giudizio_label = _giudizio.get("label") or ""
            _rip = decision.get("ripartizione") or {}

            _mc1, _mc2, _mc3 = st.columns(3)
            with _mc1:
                st.metric("Budget impostato", fmt_eur_it(_budget_sal, 0))
                st.metric("Importo ordine", fmt_eur_it(_imp_ord, 0))
            with _mc2:
                if _voto_medio > 0:
                    st.metric("Voto medio soluzione", f"{_voto_medio:.1f} / 10")
                    st.metric("Giudizio", _giudizio_label)
            with _mc3:
                for _bucket_name in ("Core", "Difensivo", "Satellite"):
                    _b = _rip.get(_bucket_name) or {}
                    _b_amt = float(_b.get("amount") or 0.0)
                    _b_pct = float(_b.get("pct") or 0.0)
                    if _b_amt > 0:
                        st.metric(_bucket_name, fmt_eur_it(_b_amt, 0), f"{_b_pct:.1f}%")
            # ─────────────────────────────────────────────────────────────────

            if st.button("Carica in SATOR (rivaluta con dati odierni)", key="sator_load_from_foto", width="stretch"):
                _foto_alloc = {
                    str(l["ticker"]): int(l.get("shares") or 0)
                    for l in decision.get("order_lines", [])
                    if l.get("ticker") and int(l.get("shares") or 0) > 0
                }
                st.session_state["_sator_import_request"] = {
                    "budget": float(decision.get("budget") or 0.0),
                    "alloc": _foto_alloc,
                }
                queue_success("Foto caricata in SATOR — analisi ricalcolata con dati odierni.")
                st.rerun()

            render_danger_hint("L'eliminazione riguarda solo lo storico decisionale SATOR salvato; non modifica il portafoglio e non registra operazioni.")
            confirm_delete = confirm_danger(
                "Confermo l'eliminazione della fotografia decisionale selezionata",
                key="sator_delete_decision_confirm",
                help_text="La conferma evita la cancellazione accidentale di uno scenario SATOR salvato.",
            )
            if st.button("Elimina fotografia selezionata", key="sator_delete_decision", width="stretch", type="secondary", disabled=not confirm_delete):
                removed = items.pop(int(selected_idx))
                decisions_state["items"] = items
                save_sator_decisions(decisions_state)
                st.session_state.pop("sator_saved_decision_idx", None)
                queue_success(f"Fotografia eliminata: {removed.get('note') or removed.get('decision_id', 'decisione')}.")
                st.rerun()
            comparison_df = compare_decision_to_actual(decision)
            if not comparison_df.empty:
                isin_map = {
                    str(item.get("ticker") or ""): str(item.get("isin") or "")
                    for item in data.get("strumenti", []) or []
                }
                if "ISIN" in comparison_df.columns:
                    comparison_df["ISIN"] = comparison_df.apply(
                        lambda r: str(r.get("ISIN") or "").strip() or isin_map.get(str(r.get("Ticker") or ""), ""),
                        axis=1,
                    )
                formatters = {
                    "Quote proposte": lambda v: f"{float(v):.0f}",
                    "Ultimo prezzo": lambda v: fmt_eur_it(v, 2),
                    "Importo proposto": lambda v: fmt_eur_it(v, 2),
                }
                if "Quote effettive" in comparison_df.columns:
                    formatters["Quote effettive"] = lambda v: f"{float(v):.0f}"
                if "Delta quote" in comparison_df.columns:
                    formatters["Delta quote"] = lambda v: f"{float(v):+.0f}"
                if "Importo effettivo" in comparison_df.columns:
                    formatters["Importo effettivo"] = lambda v: fmt_eur_it(v, 2)
                if "Delta importo" in comparison_df.columns:
                    formatters["Delta importo"] = lambda v: fmt_eur_it(v, 2, signed=True)
                styled_cmp = comparison_df.style.format(formatters)
                if "Delta importo" in comparison_df.columns:
                    styled_cmp = styled_cmp.map(color_pl, subset=["Delta importo"])
                render_styled_table(styled_cmp, height="content")

    payload = st.session_state.get("sator_result")
    if not payload:
        legend_block("Lancia l'analisi per ottenere la classifica e le motivazioni.<br>Poi compila Sel/Qta in tabella e premi Esegui.", variant="bottom")
        return

    ranking = payload.get("ranking", pd.DataFrame())
    if ranking is None or ranking.empty:
        st.info("Nessun ETF/ETC investibile disponibile per SATOR con i filtri attuali.")
        return
    # Un risultato salvato in sessione da una versione precedente del motore puo'
    # avere uno schema diverso: invece di rompersi, viene scartato con un avviso.
    colonne_richieste = {
        "ticker", "score_finale", "voto", "comparison_group", "function_label",
        "selection_reason", "strategic_fit", "tactical_momentum", "risk_efficiency",
        "diversification_benefit", "cost_efficiency", "unit_price", "current_qty",
        "name", "state", "storico_sufficiente",
    }
    if not colonne_richieste.issubset(set(ranking.columns)):
        st.session_state.pop("sator_result", None)
        st.info("Il risultato SATOR in memoria proviene da una versione precedente del motore. Premi di nuovo \"Analizza strumenti SATOR\" per rigenerarlo.")
        return
    ranking = ranking.copy().sort_values("score_finale", ascending=False).reset_index(drop=True)
    _render_sator_alerts(payload.get("alerts", []))

    manual_key = "sator_manual_alloc"
    if manual_key not in st.session_state:
        st.session_state[manual_key] = {}
    current_alloc = st.session_state.get(manual_key, {})

    master_df = _build_sator_master_table(ranking, float(budget), current_alloc, max_lines=int(st.session_state.get("sator_max_righe", 5)))
    render_section_title("Classifica e motivazioni", comment="Un solo voto per strumento; barre proporzionali per ogni fattore.", gap_after="sm")
    _render_sator_explain_box(
        [
            ("Voto", "Punteggio unico 1-10 che ordina le righe: il numero che leggi e' quello che decide la posizione."),
            ("Fattori", "Fit 30%, Mom 25%, Risk 20%, Div 15%, Costo 10%. Sono le componenti del voto, sempre su scala 1-10."),
            ("Scala", "1-10 e' il range teorico. Se il paniere e' composto da strumenti validi e simili, e' normale vedere valori concentrati tra 5 e 9."),
            ("Barre", "La barra mostra intensita' dentro il singolo fattore; il colore distingue il fattore. Streamlit non gestisce colore diverso per cella in base al valore."),
            ("Sug", "Quote suggerite entro budget: il residuo puo' restare liquido, quindi non forza il 100% del budget."),
            ("Semaforo", "Verde = suggerito. Giallo = migliore della funzione ma non finanziato dal budget. Bianco = battuto nel suo gruppo."),
            ("Funzione", "Gruppo omogeneo di confronto. La motivazione sotto la tabella spiega chi vince, contro chi e su quale fattore."),
        ],
        title="Come leggere la tabella",
    )

    table_df = master_df[SATOR_MATRIX_COLUMNS].copy()
    table_df["Sel"] = master_df["_ticker"].astype(str).map(lambda t: t in current_alloc)
    table_df["Qta"] = master_df["_ticker"].astype(str).map(lambda t: int(current_alloc.get(t, 0)))

    with st.form("sator_matrix_form", clear_on_submit=False):
        edited_grid = st.data_editor(
            table_df,
            width="stretch",
            height=sator_matrix_height(len(table_df)),
            hide_index=True,
            num_rows="fixed",
            key="sator_master_table_editor",
            column_config=sator_matrix_column_config(),
            disabled=SATOR_MATRIX_DISABLED_COLUMNS,
        )
        submitted = st.form_submit_button("Esegui", width="stretch")

    working_df = master_df.copy()
    if submitted:
        edited_df = pd.DataFrame(edited_grid).reset_index(drop=True)
        updated_alloc = {}
        for idx, row in working_df.iterrows():
            is_selected = bool(edited_df.iloc[idx].get("Sel", False)) if idx < len(edited_df) else False
            raw_qty = pd.to_numeric(edited_df.iloc[idx].get("Qta", 0), errors="coerce") if idx < len(edited_df) else 0
            qty = int(raw_qty) if pd.notna(raw_qty) else 0
            if is_selected and qty > 0:
                updated_alloc[str(row["_ticker"])] = qty
        st.session_state[manual_key] = updated_alloc
        current_alloc = updated_alloc
        st.success("Selezione aggiornata.")
    working_df["Sel"] = working_df["_ticker"].astype(str).map(lambda t: t in current_alloc)
    working_df["Qta"] = working_df["_ticker"].astype(str).map(lambda t: int(current_alloc.get(t, 0)))

    # Motivazioni comparative: il cuore della trasparenza. Mostra i vincitori di
    # funzione e, se l'utente ha selezionato, le righe scelte con il loro perche'.
    vincitori = working_df[working_df["_rango_gruppo"] == 1]
    _render_sator_explain_box(
        [(str(r["_ticker"]), str(r["_why"])) for _, r in vincitori.iterrows()],
        title="Perche' questi strumenti vincono la loro funzione",
    )

    selected_rows = working_df[working_df["Sel"]].copy()
    combo_rows = []
    for _, row in selected_rows.iterrows():
        qty = int(row["Qta"])
        if qty <= 0:
            continue
        combo_rows.append({
            "Ticker": row["_ticker"], "ISIN": row.get("_isin", ""), "Strumento": row["_name"], "Stato": row["_state"],
            "Quote": qty, "Prezzo": float(row["_price"]), "Importo": float(row["_price"]) * qty,
            "Quote possedute": float(row["Qp"]),
            "Fit": float(row["_fit"]), "Momentum": float(row["_mom"]), "Rischio": float(row["_risk"]),
            "Diversificazione": float(row["_div"]), "Voto": float(row["Voto"]),
            "Funzione": str(row["_funzione"]), "Bucket": str(row["_bucket"]), "Perche'": str(row["_why"]),
        })
    combo_df = pd.DataFrame(combo_rows)

    if combo_df.empty:
        legend_block("Seleziona gli strumenti nella tabella, inserisci le quote e premi Esegui per il giudizio sulla combinazione.", variant="bottom")
        return

    feedback_df = combo_df.rename(columns={"Quote": "Quote manuali"})
    combo_kpis = _build_combo_kpis(feedback_df, float(budget))
    headline, notes = _build_manual_choice_feedback(feedback_df, float(budget))
    render_section_title("Giudizio sulla scelta costruita", comment="Risultato della combinazione che hai deciso tu.", gap_after="sm")
    total_amount = float(pd.to_numeric(combo_df["Importo"], errors="coerce").fillna(0.0).sum())
    k1, k2, k3 = st.columns(3, gap="small")
    with k1:
        kpi_card("Ordine", fmt_eur_it(total_amount, 2), f"{len(combo_df)} linee", accent=theme.color_blue)
    with k2:
        delta_accent = theme.color_red if headline == "Fuori budget" else (theme.color_orange if headline in {"Budget sottoutilizzato", "Appena fuori budget"} else theme.color_green)
        kpi_card("Delta budget", fmt_eur_it(total_amount - float(budget), 2, signed=True), "riferimento", accent=delta_accent)
    with k3:
        valuation_accent = theme.color_red if headline == "Fuori budget" else (theme.color_green if headline == "Scelta coerente" else theme.color_orange)
        kpi_card("Valutazione", headline, "", accent=valuation_accent)
    legend_block("<br>".join(notes), variant="bottom")

    _render_sator_package_comparison(combo_df, master_df, float(budget), theme)
    _render_sator_order_evaluation(combo_df, float(budget), settings, theme)
    _render_sator_ante_post(combo_df, master_df, float(budget), theme)
    _render_sator_explain_box([(str(r["Ticker"]), str(r["Perche'"])) for _, r in combo_df.iterrows()], title="Motivazione degli strumenti selezionati")


def render_pianificazione(tab: DeltaGenerator, ctx: SimpleNamespace) -> None:
    """
    Scheda Pianificazione: obiettivo di portafoglio e SATOR.
    """
    theme = get_theme_context()
    settings = ctx.settings
    data = ctx.data

    with tab:

        _render_page_intro(
            t(settings, "page_intro.pianificazione.title", "Pianificazione"),
            t(settings, "page_intro.pianificazione.comment", "Simula acquisti, vendite e strumenti ipotetici prima di toccare il portafoglio reale. Le stime sono scenari, non previsioni."),
            "pianificazione",
            theme,
        )
        with st.container():
            _render_portfolio_objective_section(ctx, theme)

        _section_line()
        with st.container():
            _render_decision_dashboard_section(ctx, theme)

        back_to_top()
