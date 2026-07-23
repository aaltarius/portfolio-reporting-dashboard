"""
ui/theme.py — Centralizza colori, tema, palette e configurazioni di stile.
Fornisce ThemeConfig e funzioni helper per tema coerente in tutta l'app.
"""
import hashlib
from typing import Any

import plotly.io as pio
import streamlit as st
from core.config import COLORS
from core.constants import COLORI_CATEGORIA, COLORI_SENTIMENTO, STRUMENTO_PALETTE
from core.data_models import ThemeConfig
from core.asset_categories import (
    ASSET_CATEGORY_REGISTRY,
    LEGACY_CATEGORY_ALIASES,
    category_color,
    infer_category_code,
    normalize_category_code,
)
from core.settings_profiles import get_ui_preferences
from core.palettes import get_palette
from persistence.storage import load_settings

def _build_category_color_maps() -> tuple[dict[str, str], dict[str, str]]:
    category_colors = {
        code: category_color(code)
        for code in ASSET_CATEGORY_REGISTRY
        if code != "ALTRO"
    }
    category_colors["ALTRO"] = category_color("ALTRO")

    legacy_aliases = {"BTP": "GOV", "PAC": "FND"}
    for alias, target in legacy_aliases.items():
        category_colors[alias] = category_color(target)

    cat_colors = {
        code.lower(): color
        for code, color in category_colors.items()
        if code != "ALTRO"
    }
    for alias, target in LEGACY_CATEGORY_ALIASES.items():
        normalized = normalize_category_code(target)
        if normalized in category_colors:
            cat_colors[alias.lower()] = category_colors[normalized]
    cat_colors["default"] = category_color("ALTRO")
    return cat_colors, category_colors


# Predefined font families - must match definitions in ui/pages/impostazioni.py
FONT_FAMILIES = {
    "Sans-serif predefinito": "system-ui, -apple-system, sans-serif",
    "Segoe UI": "'Segoe UI', Tahoma, sans-serif",
    "Roboto": "'Roboto', 'Helvetica', sans-serif",
    "Monospace": "'Courier New', monospace",
    "Georgia": "'Georgia', serif",
}
CAT_COLORS, CATEGORY_COLORS = _build_category_color_maps()
P = dict(COLORI_SENTIMENTO)
INSTRUMENT_PALETTE = list(STRUMENTO_PALETTE)
ACCENT_VARIANTS = {
    "Default": COLORS["info"],
    "Blu": COLORS["info"],
    "Verde": COLORS["success"],
    "Arancio": COLORS["warning"],
}


def init_plotly_template() -> dict:
    """
    Initializza template Plotly con stile coerente rispetto al tema runtime.
    """
    theme = get_theme_context()
    font_family = theme.colors.get("font_family", "system-ui, -apple-system, sans-serif")
    template = {
        "layout": {
            "font": {"family": font_family, "size": 11, "color": theme.font_color},
            "title": {"font": {"family": font_family, "size": 16, "color": theme.font_color}},
            "paper_bgcolor": theme.bg_app,
            "plot_bgcolor": theme.bg_chart,
            "colorway": INSTRUMENT_PALETTE,
            "xaxis": {
                "gridcolor": theme.grid_color,
                "linecolor": theme.border_color,
                "zerolinecolor": theme.border_color,
                "tickfont": {"color": theme.font_color},
                "title": {"font": {"color": theme.font_color}},
            },
            "yaxis": {
                "gridcolor": theme.grid_color,
                "linecolor": theme.border_color,
                "zerolinecolor": theme.border_color,
                "tickfont": {"color": theme.font_color},
                "title": {"font": {"color": theme.font_color}},
            },
            "legend": {
                "bgcolor": "rgba(0,0,0,0)",
                "font": {"color": theme.font_color},
                "title": {"font": {"color": theme.font_color}},
            },
            "hoverlabel": {
                "bgcolor": theme.bg_surface,
                "bordercolor": theme.border_color,
                "font": {"color": theme.font_color, "family": font_family},
            },
        }
    }
    pio.templates["portafoglio_runtime"] = template
    pio.templates.default = "portafoglio_runtime"
    return template


def inject_theme_styles() -> None:
    """
    Inietta variabili tema leggere prima degli stili globali.
    """
    theme = get_theme_context()
    surface_alt = theme.colors.get("bg_surface_alt", theme.bg_surface)
    font_family = theme.colors.get("font_family", "system-ui, -apple-system, sans-serif")
    css = f"""
    <style>
    :root {{
      --ptf-bg:{theme.bg_app};
      --ptf-surface:{theme.bg_surface};
      --ptf-surface-2:{surface_alt};
      --ptf-text:{theme.font_color};
      --ptf-muted:{theme.muted_color};
      --ptf-border:{theme.border_color};
      --ptf-grid:{theme.grid_color};
      --ptf-primary:{theme.primary_color};
      --ptf-shadow:{theme.shadow_color};
      --ptf-success:{theme.color_green};
      --ptf-danger:{theme.color_red};
      --ptf-warning:{theme.color_orange};
      --ptf-font-family:{font_family};
    }}
    html, body, .stMarkdown, .stButton, input, select, textarea {{
      font-family: var(--ptf-font-family) !important;
    }}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)


def _get_runtime_settings_payload() -> dict[str, Any]:
    try:
        cached = st.session_state.get("_settings_runtime")
        if isinstance(cached, dict) and cached:
            return cached
    except Exception:
        pass
    try:
        return load_settings()
    except Exception:
        return {}


def _resolve_primary_accent(settings: dict[str, Any] | None) -> str:
    ui_preferences = get_ui_preferences(settings)
    accent_variant = str(ui_preferences.get("accent_variant", "Default") or "Default")
    return ACCENT_VARIANTS.get(accent_variant, ACCENT_VARIANTS["Default"])


def build_theme_context(settings: dict[str, Any] | None = None) -> ThemeConfig:
    """
    Costruisce ThemeConfig completo partendo dalle impostazioni effettive.
    Light theme hardcoded (dark theme rimosso in 4.9.9).
    Carica color palette da settings se disponibile.

    Returns:
        ThemeConfig con colori light attuali o da palette selezionata
    """
    base_colors = dict(COLORS)
    primary_accent = _resolve_primary_accent(settings)

    # Carica palette da settings se disponibile
    palette_name = (settings or {}).get("appearance", {}).get("color_palette", "Default")
    palette = get_palette(palette_name)

    # Carica font family da settings
    font_family_key = (settings or {}).get("appearance", {}).get("typography", {}).get("family", "Sans-serif predefinito")
    font_family = FONT_FAMILIES.get(font_family_key, "system-ui, -apple-system, sans-serif")

    light_colors = {
        **base_colors,
        "bg_app": palette["bg_app"],
        "bg_surface": palette["bg_surface"],
        "bg_surface_alt": palette["bg_surface_alt"],
        "bg_chart": palette["bg_chart"],
        "font": palette["font_color"],
        "muted_rgba": palette["muted_color"],
        "border_rgba": palette["border_color"],
        "grid_rgba": palette["grid_color"],
        "shadow": palette["shadow_color"],
        "font_family": font_family,
    }
    light_colors["info"] = primary_accent
    return ThemeConfig(
        primary_color=primary_accent,
        bg_app=light_colors["bg_app"],
        bg_surface=light_colors["bg_surface"],
        bg_surface_alt=light_colors["bg_surface_alt"],
        bg_chart=light_colors["bg_chart"],
        font_color=light_colors["font"],
        muted_color=light_colors["muted_rgba"],
        border_color=light_colors["border_rgba"],
        grid_color=light_colors["grid_rgba"],
        shadow_color=light_colors["shadow"],
        color_green=palette["color_green"],
        color_red=palette["color_red"],
        color_orange=palette["color_orange"],
        color_yellow=palette["color_yellow"],
        color_purple=palette["color_purple"],
        color_gray=palette["color_gray"],
        color_blue=palette["color_blue"],
        colors=light_colors,
    )


def get_theme_context() -> ThemeConfig:
    """
    Ritorna ThemeConfig completo con valori attuali.
    CRITICO: questa funzione fornisce il tema centralizzato a tutta l'app.
    """
    return build_theme_context(_get_runtime_settings_payload())


def macro_color(categoria: str) -> str:
    """
    Ritorna colore per categoria (macro asset class).

    Args:
        categoria: "GOV", "ETF", "FND", ecc.

    Returns:
        Colore hex associato a categoria
    """
    cat = infer_category_code(categoria, default="ALTRO")
    if cat == "ALTRO":
        return COLORI_CATEGORIA["default"]
    return category_color(cat)


_BUCKET_COLOR_ATTR = {"Core": "color_blue", "Difensivo": "color_green", "Satellite": "color_orange"}
_BUCKET_COLOR_FALLBACK = {"Core": "#5B8DEF", "Difensivo": "#22c55e", "Satellite": "#E8B960"}


def bucket_color(bucket: str, theme: Any) -> str:
    """
    Ritorna colore per bucket Core/Difensivo/Satellite (Pianificazione/SATOR).

    Palette-aware: legge l'attributo color_blue/color_green/color_orange dal
    ThemeConfig passato (varia con la palette utente selezionata), con
    fallback statico per-bucket se l'attributo non e' presente.

    Args:
        bucket: "Core", "Difensivo" o "Satellite"
        theme: ThemeConfig (o oggetto duck-typed con gli stessi attributi)

    Returns:
        Colore hex associato al bucket
    """
    attr = _BUCKET_COLOR_ATTR.get(bucket, "color_orange")
    fallback = _BUCKET_COLOR_FALLBACK.get(bucket, "#E8B960")
    return getattr(theme, attr, fallback)


def instrument_color(ticker: str | None) -> str:
    """
    Ritorna un colore stabile per ticker basato sulla palette strumenti centralizzata.

    Args:
        ticker: simbolo dello strumento

    Returns:
        Colore hex stabile per il ticker
    """
    tk = (ticker or "").strip().upper()
    if not tk:
        return CAT_COLORS["default"]
    idx = int(hashlib.md5(tk.encode("utf-8")).hexdigest()[:8], 16) % len(INSTRUMENT_PALETTE)
    return INSTRUMENT_PALETTE[idx]
