"""
core/settings_profiles.py -- Accesso canonico ai domini delle impostazioni.
"""

from __future__ import annotations

from typing import Any, Mapping

from persistence.storage import _normalize_settings_payload, default_settings

PAGE_MODE_PER_PAGINA = "per_pagina"
PAGE_MODE_RAPIDA = "rapida"
PAGE_MODE_COMPLETA = "completa"
PAGE_MODE_VALUES = {PAGE_MODE_PER_PAGINA, PAGE_MODE_RAPIDA, PAGE_MODE_COMPLETA}
DEBUG_RENDER_SCOPE_CURRENT = "current_page"
DEBUG_RENDER_SCOPE_FULL = "full_sweep"
DEBUG_RENDER_SCOPE_VALUES = {DEBUG_RENDER_SCOPE_CURRENT, DEBUG_RENDER_SCOPE_FULL}

CACHE_STRATEGY_DISABLED = "disabled"
CACHE_STRATEGY_SESSION_ONLY = "session_only"
CACHE_STRATEGY_DISK_ONLY = "disk_only"
CACHE_STRATEGY_HYBRID = "hybrid"
CACHE_STRATEGY_VALUES = {
    CACHE_STRATEGY_DISABLED,
    CACHE_STRATEGY_SESSION_ONLY,
    CACHE_STRATEGY_DISK_ONLY,
    CACHE_STRATEGY_HYBRID,
}
LOG_LEVEL_VALUES = {"DEBUG", "INFO", "WARNING", "ERROR"}
DEFAULT_PRE_RENDER_SCOPE = "core_charts_v1"
MIN_PRE_RENDER_COOLDOWN_SECONDS = 60


def _normalized_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    payload = settings if isinstance(settings, dict) else default_settings()
    return _normalize_settings_payload(payload)


def _normalize_page_mode(value: Any) -> str:
    page_mode = str(value or PAGE_MODE_PER_PAGINA)
    return page_mode if page_mode in PAGE_MODE_VALUES else PAGE_MODE_PER_PAGINA


def _normalize_debug_render_scope(value: Any) -> str:
    scope = str(value or DEBUG_RENDER_SCOPE_CURRENT)
    return scope if scope in DEBUG_RENDER_SCOPE_VALUES else DEBUG_RENDER_SCOPE_CURRENT


def _normalize_cache_strategy(value: Any) -> str:
    strategy = str(value or CACHE_STRATEGY_HYBRID)
    return strategy if strategy in CACHE_STRATEGY_VALUES else CACHE_STRATEGY_HYBRID


def _normalize_log_level(value: Any) -> str:
    level = str(value or "INFO").upper()
    return level if level in LOG_LEVEL_VALUES else "INFO"


def get_portfolio_profile(settings: dict[str, Any] | None) -> dict[str, Any]:
    return dict(_normalized_settings(settings).get("portfolio_profile", {}))


def get_calculations_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    return dict(_normalized_settings(settings).get("calculations_metrics", {}))


def get_benchmarking_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    return dict(_normalized_settings(settings).get("benchmarking", {}))


def get_reporting_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    return dict(_normalized_settings(settings).get("reporting_export", {}))


def get_alerts_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    return dict(_normalized_settings(settings).get("alerts", {}))


def get_ui_preferences(settings: dict[str, Any] | None) -> dict[str, Any]:
    return dict(_normalized_settings(settings).get("ui_preferences", {}))


def get_category_view_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    return dict(_normalized_settings(settings).get("category_view", {}))


def get_newsletter_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    return dict(_normalized_settings(settings).get("newsletter", {}))


def get_i18n_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    return dict(_normalized_settings(settings).get("i18n", {}))


def get_backup_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    return dict(_normalized_settings(settings).get("backup", {}))


def get_figure_cache_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    normalized = _normalized_settings(settings)
    return dict(normalized.get("ui_figure_cache", {}))


def get_pre_render_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    normalized = _normalized_settings(settings)
    figure_cache = normalized.get("ui_figure_cache", {})
    pre_render = normalized.get("ui_pre_render", {})
    try:
        cooldown_seconds = int(pre_render.get("cooldown_seconds", 1800) or 1800)
    except (TypeError, ValueError):
        cooldown_seconds = 1800
    cooldown_seconds = max(MIN_PRE_RENDER_COOLDOWN_SECONDS, cooldown_seconds)
    return {
        "enabled": bool(pre_render.get("enabled", True)) and bool(figure_cache.get("enabled", True)),
        "initial_complete": bool(pre_render.get("initial_complete", True)),
        "background_enabled": bool(pre_render.get("background_enabled", True)),
        "cooldown_seconds": cooldown_seconds,
        "scope": str(pre_render.get("scope", DEFAULT_PRE_RENDER_SCOPE) or DEFAULT_PRE_RENDER_SCOPE),
    }


def get_runtime_ui_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    normalized = _normalized_settings(settings)
    ui_preferences = normalized.get("ui_preferences", {})
    figure_cache = normalized.get("ui_figure_cache", {})
    pre_render = get_pre_render_settings(normalized)
    return {
        "page_mode": _normalize_page_mode(ui_preferences.get("page_mode", PAGE_MODE_PER_PAGINA)),
        "show_page_mode_controls": bool(ui_preferences.get("show_page_mode_controls", True)),
        "debug_render_monitor": bool(ui_preferences.get("debug_render_monitor", False)),
        "debug_render_progress": bool(ui_preferences.get("debug_render_progress", False)),
        "debug_render_log": bool(ui_preferences.get("debug_render_log", False)),
        "debug_render_scope": _normalize_debug_render_scope(ui_preferences.get("debug_render_scope", DEBUG_RENDER_SCOPE_CURRENT)),
        "log_level": _normalize_log_level(ui_preferences.get("log_level", "INFO")),
        "font_scale": str(ui_preferences.get("font_scale", "Grande") or "Grande"),
        "figure_cache_enabled": bool(figure_cache.get("enabled", True)),
        "figure_cache_strategy": _normalize_cache_strategy(figure_cache.get("strategy", CACHE_STRATEGY_HYBRID)),
        "pre_render_enabled": bool(pre_render.get("enabled", True)),
        "pre_render_initial_complete": bool(pre_render.get("initial_complete", True)),
        "pre_render_background_enabled": bool(pre_render.get("background_enabled", True)),
        "pre_render_cooldown_seconds": int(pre_render.get("cooldown_seconds", 1800)),
        "pre_render_scope": str(pre_render.get("scope", DEFAULT_PRE_RENDER_SCOPE)),
    }


def get_effective_summary_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    reporting = get_reporting_settings(settings)
    ui_preferences = get_ui_preferences(settings)
    return {
        "export_decimals": int(reporting.get("decimal_places", 2) or 2),
        "include_history_exports": bool(reporting.get("include_history", True)),
        "include_methodology": bool(reporting.get("include_methodology", True)),
        "include_holdings_export": bool(reporting.get("include_holdings_table", True)),
        "include_benchmark": bool(reporting.get("include_benchmark", True)),
        "summary_layout": str(ui_preferences.get("summary_layout", "GIPS Completo") or "GIPS Completo"),
        "show_explanations": bool(ui_preferences.get("show_explanations", True)),
        "show_commentary": bool(ui_preferences.get("summary_show_commentary", True)),
        "show_advanced_metrics": bool(ui_preferences.get("summary_show_advanced_metrics", True)),
    }


def get_effective_page_mode(settings: dict[str, Any] | None) -> str:
    return str(get_runtime_ui_settings(settings).get("page_mode", PAGE_MODE_PER_PAGINA))


def get_effective_figure_cache_strategy(
    settings: dict[str, Any] | None,
    *,
    runtime_override: Any = None,
) -> str:
    if runtime_override not in (None, ""):
        return _normalize_cache_strategy(runtime_override)
    return str(get_runtime_ui_settings(settings).get("figure_cache_strategy", CACHE_STRATEGY_HYBRID))


def get_runtime_cache_override(runtime_state: Mapping[str, Any] | None = None) -> Any:
    if runtime_state is None:
        return None
    getter = getattr(runtime_state, "get", None)
    if callable(getter):
        return getter("cfg_cache_strategy")
    return None


def resolve_figure_cache_strategy(
    settings: dict[str, Any] | None,
    runtime_state: Mapping[str, Any] | None = None,
) -> str:
    return get_effective_figure_cache_strategy(
        settings,
        runtime_override=get_runtime_cache_override(runtime_state),
    )


def get_effective_show_explanations(settings: dict[str, Any] | None) -> bool:
    return bool(get_ui_preferences(settings).get("show_explanations", True))


def resolve_page_render_mode(
    settings: dict[str, Any] | None,
    *,
    local_mode: Any = None,
    default_local: str = "Rapida",
) -> dict[str, Any]:
    page_mode = get_effective_page_mode(settings)
    show_controls = page_mode == PAGE_MODE_PER_PAGINA
    if page_mode == PAGE_MODE_COMPLETA:
        render_mode = "Completa"
    elif page_mode == PAGE_MODE_RAPIDA:
        render_mode = "Rapida"
    else:
        render_mode = str(local_mode or default_local or "Rapida")
        if render_mode not in {"Rapida", "Completa"}:
            render_mode = "Rapida"
    return {
        "page_mode": page_mode,
        "show_controls": show_controls,
        "render_mode": render_mode,
        "include_advanced": render_mode == "Completa",
    }
