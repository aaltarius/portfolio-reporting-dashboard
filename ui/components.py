"""
ui/components.py — Componenti UI: KPI card, legend, tabelle, navigazione.
Consuma il tema centralizzato definito in ui.theme.
"""
import re
from typing import Any

import numpy as np
import pandas as pd
import streamlit as st
from core.asset_categories import get_selected_category_codes
from core.render_profiler import profile_step
from persistence.storage import macro_cat
from ui.formatting import (
    fmt_eur_it, fmt_num_it, fmt_pct_it, fmt_qty_it, hex_to_rgba,
)
from ui.streamlit_compat import render_html_iframe
from ui.theme import CAT_COLORS, P, instrument_color, macro_color


def _resolve_visible_category_codes(settings: dict[str, Any] | None = None) -> list[str]:
    return list(get_selected_category_codes(settings))


def macro_legend_html(settings: dict[str, Any] | None = None) -> str:
    items = [(code, macro_color(code)) for code in _resolve_visible_category_codes(settings)]
    return " ".join(
        f'<span style="display:inline-flex;align-items:center;margin-right:12px;">'
        f'<span style="display:inline-block;width:10px;height:10px;border-radius:999px;background:{color};margin-right:6px;"></span>{label}</span>'
        for label, color in items
    )


def count_instruments_by_category(
    strumenti_list: list[dict[str, Any]],
    settings: dict[str, Any] | None = None,
) -> dict[str, int]:
    """Conta gli strumenti per categoria visibile da un elenco di strumenti."""
    counts = {code: 0 for code in _resolve_visible_category_codes(settings)}
    for strumento in strumenti_list:
        cat = macro_cat(strumento.get("tipo", ""))
        if cat in counts:
            counts[cat] += 1
    return counts


# ══════════════════════════════════════════════════════════════════════════════
# KPI e Legend
# ══════════════════════════════════════════════════════════════════════════════

def legend_block(text: str, variant: str = "top", min_height: int | None = None) -> None:
    css_class = "leg leg-bottom" if variant == "bottom" else "leg leg-top"
    style_attr = f' style="min-height:{int(min_height)}px;"' if isinstance(min_height, int) and min_height > 0 else ""
    st.markdown(f'<div class="{css_class}"{style_attr}>{text}</div>', unsafe_allow_html=True)


def vertical_gap(size: str = "md") -> None:
    heights = {
        "xs": 6,
        "sm": 10,
        "md": 16,
        "lg": 24,
    }
    px = heights.get(str(size or "md"), 16)
    st.markdown(f"<div style='height:{px}px;'></div>", unsafe_allow_html=True)


def _section_icon_svg(kind: str = "default") -> str:
    icons = {
        "portfolio": """
        <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="5" width="17" height="14" rx="4" fill="currentColor" opacity=".16"/><path d="M7 9h10M7 13h6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        """,
        "analysis": """
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 16.5V11M12 16.5V7.5M18 16.5v-4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M5.5 18h13" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
        """,
        "income": """
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4.5v15M8.2 8.2c0-1.8 1.4-3 3.8-3 2.1 0 3.5.9 3.5 2.5 0 1.6-1.2 2.2-3.5 2.8-2.4.6-3.8 1.3-3.8 3.2 0 1.9 1.6 3.1 4 3.1 2.4 0 4-1.1 4.1-3" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        """,
        "risk": """
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4 19 7v5c0 4.2-2.8 6.9-7 8-4.2-1.1-7-3.8-7-8V7l7-3Z" fill="currentColor" opacity=".16"/><path d="M12 8v4.5M12 15.8h.01" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/></svg>
        """,
        "settings": """
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3.1" fill="none" stroke="currentColor" stroke-width="1.9"/><path d="M12 4.8v2.1M12 17.1v2.1M4.8 12h2.1M17.1 12h2.1M6.9 6.9l1.5 1.5M15.6 15.6l1.5 1.5M17.1 6.9l-1.5 1.5M8.4 15.6l-1.5 1.5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>
        """,
        "data": """
        <svg viewBox="0 0 24 24" aria-hidden="true"><ellipse cx="12" cy="6.5" rx="6.5" ry="2.5" fill="currentColor" opacity=".16"/><path d="M5.5 6.5v7c0 1.4 2.9 2.5 6.5 2.5s6.5-1.1 6.5-2.5v-7M5.5 10c0 1.4 2.9 2.5 6.5 2.5s6.5-1.1 6.5-2.5" fill="none" stroke="currentColor" stroke-width="1.7"/></svg>
        """,
        "quotes": """
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 16.5 9.2 12l3 2.5 5.8-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M5 19h14" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
        """,
        "operations": """
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 7h10M7 12h10M7 17h6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="16.8" cy="16.8" r="2.2" fill="currentColor" opacity=".18"/></svg>
        """,
        "default": """
        <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="4" fill="currentColor" opacity=".14"/><path d="M8 9h8M8 13h8M8 17h5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        """,
    }
    return icons.get(kind, icons["default"])


def _section_icon_style(kind: str = "default") -> tuple[str, str, str]:
    styles = {
        "portfolio": ("#2563eb", "rgba(37,99,235,.12)", "rgba(37,99,235,.28)"),
        "analysis": ("#7c3aed", "rgba(124,58,237,.12)", "rgba(124,58,237,.28)"),
        "income": ("#059669", "rgba(5,150,105,.12)", "rgba(5,150,105,.28)"),
        "risk": ("#dc2626", "rgba(220,38,38,.10)", "rgba(220,38,38,.24)"),
        "settings": ("#475569", "rgba(71,85,105,.12)", "rgba(71,85,105,.24)"),
        "data": ("#0f766e", "rgba(15,118,110,.12)", "rgba(15,118,110,.24)"),
        "quotes": ("#ea580c", "rgba(234,88,12,.12)", "rgba(234,88,12,.26)"),
        "operations": ("#0284c7", "rgba(2,132,199,.12)", "rgba(2,132,199,.26)"),
        "default": ("#3b82f6", "rgba(59,130,246,.12)", "rgba(59,130,246,.28)"),
    }
    return styles.get(kind, styles["default"])


def render_section_title(
    title: str,
    subtitle: str | None = None,
    comment: str | None = None,
    *,
    icon: str = "default",
    gap_after: str = "sm",
) -> None:
    icon_color, icon_bg, icon_border = _section_icon_style(icon)
    st.markdown(
        f"""
        <style>
        .ptf-section-title {{
            display:flex;
            align-items:center;
            gap:10px;
            margin:0 0 4px 0;
            color:var(--ptf-text, #111827);
            font-size:1.06rem;
            font-weight:800;
            line-height:1.2;
        }}
        .ptf-section-title__icon {{
            width:24px;
            height:24px;
            min-width:24px;
            border-radius:999px;
            display:inline-flex;
            align-items:center;
            justify-content:center;
        }}
        .ptf-section-title__icon svg {{
            width:15px;
            height:15px;
            display:block;
        }}
        </style>
        <div class="ptf-section-title">
          <span class="ptf-section-title__icon" style="color:{icon_color};background:{icon_bg};border:1px solid {icon_border};">{_section_icon_svg(icon)}</span>
          <span>{title}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if subtitle:
        st.caption(subtitle)
    if comment:
        legend_block(comment)
    vertical_gap(gap_after)


def render_frozen_analysis_status_text(slot, entry: dict[str, Any] | None, stale: bool, *, entity_label: str) -> None:
    """Testo di stato (info/warning/caption) per un'analisi congelata (Benchmark, Accumuli, ...).

    Va richiamato di nuovo con l'entry aggiornata subito dopo un eventuale
    refresh, nello stesso rerun: altrimenti il messaggio mostra ancora la data
    di prima del click anche quando l'analisi è già stata rigenerata, dando
    l'impressione che il primo click non abbia fatto nulla.
    """
    with slot.container():
        if entry is None:
            st.info(
                f"Nessuna analisi {entity_label} disponibile nella cache persistente. "
                "La prima analisi va generata una sola volta; poi verrà recuperata anche dopo il riavvio dell'app."
            )
            return
        created_at = str(entry.get("created_at") or "n/d")
        if stale:
            st.warning(
                f"Sto mostrando l'ultima analisi {entity_label} disponibile in cache, generata il {created_at}. "
                "I dati del portafoglio sono cambiati: rigenera solo se vuoi aggiornare questa lettura."
            )
            return
        source = str(entry.get("cache_source") or "cache")
        st.caption(f"Analisi {entity_label} in cache — generata il {created_at} — origine: {source}. Non viene rigenerata automaticamente nei rerun.")


def render_frozen_analysis_freeze_header(
    entry: dict[str, Any] | None,
    stale: bool,
    signature: str,
    *,
    title: str,
    comment: str | None,
    entity_label: str,
    key_prefix: str,
):
    """Header operativo con bottone Analizza/Aggiorna/Rigenera per un'analisi congelata.

    Ritorna (refresh_requested, status_slot). Il chiamante deve richiamare
    render_frozen_analysis_status_text(status_slot, ...) con l'entry aggiornata
    dopo un eventuale refresh, per evitare che il messaggio resti di un giro
    indietro rispetto ai dati che descrive.
    """
    render_section_title(title, comment=comment, icon="analysis")
    status_slot = st.empty()
    render_frozen_analysis_status_text(status_slot, entry, stale, entity_label=entity_label)

    if entry is None:
        return st.button(f"Analizza {entity_label}", type="primary", key=f"{key_prefix}_analyze_{signature}"), status_slot
    if stale:
        return st.button(f"Aggiorna analisi {entity_label}", type="primary", key=f"{key_prefix}_refresh_{signature}"), status_slot
    return st.button(f"Rigenera analisi {entity_label}", type="secondary", key=f"{key_prefix}_regen_{signature}"), status_slot


def kpi_card(
    title: str,
    value: str,
    subtitle: str = "",
    accent: str = P["blue"],
    value_color: str | None = None,
) -> None:
    vc = f"color:{value_color};" if value_color else ""
    st.markdown(
        f"""<div class="kpi-card" style="--accent:{accent};">
                <div class="kpi-label">{title}</div>
                <div class="kpi-value" style="{vc}">{value}</div>
                <div class="kpi-sub">{subtitle}</div>
            </div>""",
        unsafe_allow_html=True
    )


def kpi_triplet_card(
    title: str,
    items: list[tuple[str, str, str, str]],
    accent: str = P["blue"],
) -> None:
    cols = max(1, len(items))
    cells = "".join(
        f'<div class="kpi-triplet-cell"><div class="kpi-triplet-tag kpi-triplet-tag-{label.lower()}">{label}</div><div class="kpi-triplet-value">{value}</div><div class="kpi-triplet-pl {pl_class}">({pl_value})</div></div>'
        for label, value, pl_value, pl_class in items
    )
    st.markdown(
        f"""<div class="kpi-card" style="--accent:{accent};--kpi-triplet-cols:{cols};">
                <div class="kpi-label">{title}</div>
                <div class="kpi-triplet">{cells}</div>
                <div class="kpi-sub">Valore di mercato per macro-categoria con relativo P/L aggregato.</div>
            </div>""",
        unsafe_allow_html=True
    )


def kpi_compact_category_html(
    total_count: int,
    counts: dict[str, int],
    settings: dict[str, Any] | None = None,
) -> str:
    items = []
    visible_categories = _resolve_visible_category_codes(settings)
    grid_columns = max(1, min(len(visible_categories), 5))
    for cat in visible_categories:
        items.append(
            f'<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;'
            f'padding:8px 8px;border-radius:12px;background:{hex_to_rgba(macro_color(cat), 0.14)};min-height:82px;">'
            f'<span style="color:{macro_color(cat)};font-weight:700;font-size:0.80rem;line-height:1;text-align:center;">{cat}</span>'
            f'<span style="color:{macro_color(cat)};font-weight:800;font-size:1.06rem;line-height:1;text-align:center;">{fmt_num_it(counts.get(cat, 0), 0)}</span>'
            f'</div>'
        )
    cards = "".join(items)
    return f"""
    <div class="kpi-card" style="--accent:{P["orange"]};min-height:124px;height:124px;">
        <div class="kpi-label">Strumenti</div>
        <div style="display:grid;grid-template-columns:minmax(0,0.90fr) minmax(0,1.55fr);gap:16px;align-items:center;">
            <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:88px;">
                <div class="kpi-value" style="text-align:center;">{fmt_num_it(total_count, 0)}</div>
                <div class="kpi-sub" style="margin-top:8px;text-align:center;">Numero strumenti censiti nel portafoglio</div>
            </div>
            <div style="display:grid;grid-template-columns:repeat({grid_columns},minmax(0,1fr));gap:8px;align-items:stretch;">
                {cards}
            </div>
        </div>
    </div>
    """


# ══════════════════════════════════════════════════════════════════════════════
# Tabelle
# ══════════════════════════════════════════════════════════════════════════════

def table_base_style(styler: Any) -> Any:
    return styler.set_table_styles([
        {"selector": "th", "props": [("font-weight", "700")]},
    ], overwrite=False)


def render_styled_table(
    styler: Any,
    height: int | str = "content",
    column_config: dict[str, Any] | None = None,
    static: bool = False,
) -> None:
    try:
        row_count = len(getattr(styler, "data", styler))
    except Exception:
        row_count = None
    kwargs = {"width": "stretch", "hide_index": True}
    valid_height = None
    if isinstance(height, int) and height > 0:
        valid_height = height
    elif isinstance(height, str) and height in {"stretch", "content", "auto"}:
        valid_height = height
    if valid_height is not None:
        kwargs["height"] = valid_height
    if column_config:
        kwargs["column_config"] = column_config
    with profile_step("UI/Table", "table_base_style", count=row_count, detail=f"static={static}; height={height}"):
        styled = table_base_style(styler)
    with profile_step("UI/Table", "st.table" if static else "st.dataframe", count=row_count, detail=f"height={valid_height}; columns={len(column_config or {})}"):
        if static:
            st.table(styled)
        else:
            st.dataframe(styled, **kwargs)



# ══════════════════════════════════════════════════════════════════════════════
# Navigazione
# ══════════════════════════════════════════════════════════════════════════════

def back_to_top(show_prev: bool = True, show_next: bool = True, nav_key: str = "default") -> None:
    prev_mode = "true" if show_prev else "false"
    next_mode = "true" if show_next else "false"
    safe_key = re.sub(r"[^a-zA-Z0-9_-]", "_", str(nav_key or "default"))
    blue = P["blue"]
    orange = P["orange"]
    html_nav = """
<div id="tabnav-wrap-%(key)s" style="display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr) minmax(0,1fr);align-items:center;gap:10px;margin:8px 0 4px 0;font-family:sans-serif;width:100%%;box-sizing:border-box;">
  <button id="btn-prev-%(key)s" style="width:100%%;max-width:100%%;min-width:0;box-sizing:border-box;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer;padding:10px 12px;border-radius:12px;border:1px solid %(blue_border)s;background:transparent;color:%(blue)s;font-weight:700;font-size:0.88rem;transition:opacity .18s ease;">← Precedente</button>
  <a id="btn-top-%(key)s" href="#page-top" style="display:flex;align-items:center;justify-content:center;width:100%%;max-width:100%%;min-width:0;box-sizing:border-box;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:10px 12px;border-radius:12px;border:1px solid %(orange_border)s;background:transparent;color:%(orange)s;font-weight:700;font-size:0.88rem;text-decoration:none;">↑ Torna in cima</a>
  <button id="btn-next-%(key)s" style="width:100%%;max-width:100%%;min-width:0;box-sizing:border-box;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer;padding:10px 12px;border-radius:12px;border:1px solid %(blue_border)s;background:transparent;color:%(blue)s;font-weight:700;font-size:0.88rem;transition:opacity .18s ease;">Successiva →</button>
</div>
<script>
(function(){
  var prevBtn = document.getElementById('btn-prev-%(key)s');
  var nextBtn = document.getElementById('btn-next-%(key)s');
  var topBtn = document.getElementById('btn-top-%(key)s');
  var showPrev = %(prev)s;
  var showNext = %(next)s;
  function getParentDoc(){ try { return window.parent.document; } catch(e) { return document; } }
  function repeatedScrollTop(){
    [0, 60, 140, 260, 420, 620].forEach(function(delay){
      setTimeout(function(){
        try {
          var parentDoc = getParentDoc();
          var anchor = parentDoc.getElementById('page-top');
          if(anchor){ anchor.scrollIntoView({behavior:'smooth', block:'start'}); }
          window.parent.scrollTo({top:0, behavior:'smooth'});
          if(parentDoc.documentElement){ parentDoc.documentElement.scrollTop = 0; }
          if(parentDoc.body){ parentDoc.body.scrollTop = 0; }
        } catch(e) {
          window.scrollTo({top:0, behavior:'smooth'});
        }
      }, delay);
    });
  }
  function getTabs(){
    var parentDoc = getParentDoc();
    var tabList = parentDoc.querySelector('[role="tablist"]');
    if(!tabList) return [];
    return Array.from(tabList.querySelectorAll('[role="tab"]'));
  }
  function setButtonState(btn, visible){
    if(!btn) return;
    btn.style.visibility = visible ? 'visible' : 'hidden';
    btn.style.opacity = visible ? '1' : '0';
    btn.style.pointerEvents = visible ? 'auto' : 'none';
  }
  function refreshButtons(){
    setButtonState(prevBtn, !!showPrev);
    setButtonState(nextBtn, !!showNext);
  }
  function clickTab(dir){
    var tabs = getTabs();
    if(!tabs.length) return;
    var idx = tabs.findIndex(function(t){ return t.getAttribute('aria-selected') === 'true'; });
    if(idx < 0) return;
    var target = dir === 'prev' ? tabs[idx - 1] : tabs[idx + 1];
    if(target){
      target.click();
      repeatedScrollTop();
      setTimeout(refreshButtons, 120);
      setTimeout(refreshButtons, 320);
      setTimeout(refreshButtons, 640);
    }
  }
  if(prevBtn){ prevBtn.onclick = function(){ clickTab('prev'); }; }
  if(nextBtn){ nextBtn.onclick = function(){ clickTab('next'); }; }
  if(topBtn){ topBtn.onclick = function(e){ e.preventDefault(); repeatedScrollTop(); }; }
  setTimeout(refreshButtons, 40);
  setTimeout(refreshButtons, 220);
  setTimeout(refreshButtons, 520);
  setTimeout(refreshButtons, 1200);
  setTimeout(refreshButtons, 2800);
})();
</script>""" % {
        "prev": prev_mode,
        "next": next_mode,
        "key": safe_key,
        "blue": blue,
        "orange": orange,
        "blue_border": hex_to_rgba(blue, 0.40),
        "orange_border": hex_to_rgba(orange, 0.50),
    }
    render_html_iframe(html_nav, height=64)


def build_price_direction_map(data: dict[str, Any]) -> dict[str, str]:
    storico = data.get("storico_prezzi", {}) if isinstance(data, dict) else {}
    if not storico or len(storico) < 2:
        return {}
    dates = sorted(storico.keys())
    last_day = storico.get(dates[-1], {}) or {}
    prev_day = storico.get(dates[-2], {}) or {}
    out = {}
    tickers = set(last_day.keys()) | set(prev_day.keys())
    for tk in tickers:
        try:
            last_px = float(last_day.get(tk)) if last_day.get(tk) not in (None, "") else np.nan
        except Exception:
            last_px = np.nan
        try:
            prev_px = float(prev_day.get(tk)) if prev_day.get(tk) not in (None, "") else np.nan
        except Exception:
            prev_px = np.nan
        if pd.isna(last_px) or pd.isna(prev_px) or prev_px == 0:
            out[tk] = "flat"
        else:
            pct = (last_px - prev_px) / prev_px
            if pct > 0.03:
                out[tk] = "up_big"
            elif pct > 0:
                out[tk] = "up"
            elif pct < -0.03:
                out[tk] = "down_big"
            elif pct < 0:
                out[tk] = "down"
            else:
                out[tk] = "flat"
    return out
def wrap_radar_label(label: Any) -> str:
    txt = str(label or "").strip()
    txt = txt.replace(" / ", " /\n")
    if len(txt) > 18 and "\n" not in txt:
        parts = txt.split(" ")
        lines = []
        current = ""
        for part in parts:
            trial = (current + " " + part).strip()
            if len(trial) <= 11 or not current:
                current = trial
            else:
                lines.append(current)
                current = part
        if current:
            lines.append(current)
        txt = "\n".join(lines)
    return txt


def should_render_section(page_name: str, section_name: str, settings: dict) -> bool:
    """Check if section should be rendered based on visibility settings."""
    visibility = settings.get("appearance", {}).get("custom_visibility", {})
    page_visibility = visibility.get(page_name, {})

    # If custom_visibility has explicit setting, use it
    if section_name in page_visibility:
        return bool(page_visibility[section_name])

    # Otherwise, check visibility_mode preset
    mode = settings.get("appearance", {}).get("visibility_mode", "Standard")
    essenziale_sections = {
        "Portafoglio": ["Andamento ultima giornata", "Sintesi allocazione", "Controvalore del Portafoglio"],
        "Quotazioni": ["Storico Prezzi", "Diagnostica"],
        "Operazioni": ["Centro Operativo", "Registro operazioni"],
        "Cruscotti": ["Dashboard principale"],
        "Summary": ["Identità report", "Genera report"],
        "Confronto": ["Confronto"],
        "Pianificazione": ["Scenari futuri"],
        "Gestione Dati": ["Sistema e Backup"],
    }
    completo_excludes = set()  # Everything shown in completo

    if mode == "Essenziale":
        return section_name in essenziale_sections.get(page_name, [])
    elif mode == "Completo":
        return section_name not in completo_excludes
    else:  # Standard
        return True  # All sections in Standard
