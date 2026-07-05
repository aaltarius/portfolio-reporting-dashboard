"""
persistence/storage.py — I/O JSON, load/save, backup, costanti di dominio.
Nessuna dipendenza da streamlit o da altri moduli del progetto.
Contiene anche le funzioni di modello dati necessarie a load_data/save_data
per evitare import circolari.
"""
import logging
import json, os, shutil, hashlib
from datetime import datetime, date
import pandas as pd
import numpy as np
from core.asset_categories import (
    ACTIVE_CATEGORY_CODES,
    DEFAULT_VISIBLE_CATEGORY_CODES,
    category_name,
    infer_category_code,
    normalize_category_code,
    normalize_category_selection,
)
from core.benchmark_registry import LEGACY_BENCH, resolve_instrument_benchmark

logger = logging.getLogger("portafoglio.persistence.storage")

AUDIT_EVENT_CATALOG = {
    "settings_saved": {"label": "Impostazioni salvate", "category": "Configurazione"},
    "backup_created": {"label": "Backup creato", "category": "Backup"},
    "backup_restored": {"label": "Backup ripristinato", "category": "Backup"},
    "backup_deleted": {"label": "Backup eliminato", "category": "Backup"},
    "snapshot_created": {"label": "Snapshot creato", "category": "Snapshot"},
    "sator_decision_saved": {"label": "Decisione SATOR salvata", "category": "Pianificazione"},
    "quotes_imported": {"label": "Quotazioni importate", "category": "Quotazioni"},
    "quotes_reset": {"label": "Quotazioni resettate", "category": "Quotazioni"},
    "newsletter_preview_generated": {"label": "Anteprima newsletter generata", "category": "Newsletter"},
}

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------
BASE_DIR             = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR             = os.path.join(BASE_DIR, "data")
PRICES_DIR           = os.path.join(DATA_DIR, "prices")
DATA_FILE            = os.path.join(DATA_DIR, "portfolio", "portafoglio_data.json")
SETTINGS_FILE        = os.path.join(DATA_DIR, "config", "portafoglio_settings.json")
QUOTES_LOG_FILE      = os.path.join(DATA_DIR, "cache", "portafoglio_quotes_log.json")
SNAPSHOTS_FILE       = os.path.join(DATA_DIR, "portfolio", "portafoglio_snapshots.json")
SATOR_DECISIONS_FILE = os.path.join(DATA_DIR, "portfolio", "portafoglio_sator_decisions.json")
BENCHMARK_CACHE_FILE = os.path.join(DATA_DIR, "cache", "portafoglio_benchmark_cache.json")
META_FILE            = os.path.join(DATA_DIR, "config", "portafoglio_meta.json")
STORICO_PREZZI_FILE  = os.path.join(PRICES_DIR, "portafoglio_storico_prezzi.json")
BACKUP_DIR           = os.path.join(BASE_DIR, "backups")

# ---------------------------------------------------------------------------
# Migrazione automatica file JSON → sottocartella data/
# ---------------------------------------------------------------------------
_OLD_FILES = [
    ("portafoglio_data.json",            DATA_FILE),
    ("portafoglio_settings.json",        SETTINGS_FILE),
    ("portafoglio_quotes_log.json",      QUOTES_LOG_FILE),
    ("portafoglio_snapshots.json",       SNAPSHOTS_FILE),
    ("portafoglio_sator_decisions.json", SATOR_DECISIONS_FILE),
    ("portafoglio_benchmark_cache.json", BENCHMARK_CACHE_FILE),
    ("portafoglio_meta.json",            META_FILE),
]

def _migrate_json_to_data_dir():
    """Sposta i file JSON da BASE_DIR a DATA_DIR se non sono già lì."""
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "config"), exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "portfolio"), exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "cache"), exist_ok=True)
    os.makedirs(PRICES_DIR, exist_ok=True)
    for fname, new_path in _OLD_FILES:
        old_path = os.path.join(BASE_DIR, fname)
        if os.path.exists(old_path) and not os.path.exists(new_path):
            try:
                os.makedirs(os.path.dirname(new_path), exist_ok=True)
                shutil.move(old_path, new_path)
                logger.info("Migrazione file completata: %s -> %s", old_path, new_path)
            except Exception:
                logger.warning("Migrazione file fallita: %s -> %s", old_path, new_path, exc_info=True)
                pass

# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------
APP_VERSION    = "4.9.24"
SCHEMA_VERSION = "3.3"

TIPI_EVENTO_PORTAFOGLIO = [
    "ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA",
    "CEDOLA", "DIVIDENDO", "VERSAMENTO", "PRELIEVO", "COMMISSIONE", "IMPOSTA",
]
EVENTI_CON_STRUMENTO = {"ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA", "CEDOLA", "DIVIDENDO"}
EVENTI_CON_QUANTITA  = {"ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA"}
EVENTI_CON_PREZZO    = {"ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA"}
EVENTI_CON_IMPORTO   = {"CEDOLA", "DIVIDENDO", "VERSAMENTO", "PRELIEVO", "COMMISSIONE", "IMPOSTA"}

# Mappa tipo strumento → ticker benchmark
# Compatibilità storica: la risoluzione effettiva del benchmark è ora centralizzata
# in core.benchmark_registry.resolve_instrument_benchmark().
BENCH = dict(LEGACY_BENCH)


# ---------------------------------------------------------------------------
# Categorizzazione strumenti (macro_cat) — unica fonte di verità
# ---------------------------------------------------------------------------
def _normalize_macro_label(value):
    return infer_category_code(value, default="ALTRO")

def macro_cat(tipo):
    return _normalize_macro_label(tipo)

# ---------------------------------------------------------------------------
# I/O primitivi
# ---------------------------------------------------------------------------
def _ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def _read_json_file(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        logger.warning("Lettura JSON fallita, uso default: path=%s", path, exc_info=True)
    return json.loads(json.dumps(default))


def _write_json_file(path, payload):
    # Scrittura atomica: scrivi su tmp nella stessa dir, poi rinomina.
    # Evita file vuoti se il processo viene interrotto a metà write.
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _deep_clone(value):
    return json.loads(json.dumps(value))


def _deep_merge_defaults(defaults, payload):
    """Merge ricorsivo che preserva i valori esistenti e aggiunge i default mancanti."""
    if isinstance(defaults, dict) and isinstance(payload, dict):
        merged = {}
        keys = set(defaults.keys()) | set(payload.keys())
        for key in keys:
            if key in defaults and key in payload:
                merged[key] = _deep_merge_defaults(defaults[key], payload[key])
            elif key in payload:
                merged[key] = _deep_clone(payload[key])
            else:
                merged[key] = _deep_clone(defaults[key])
        return merged
    return _deep_clone(payload if payload is not None else defaults)


def _safe_float(value, default=0.0):
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _safe_date_str(value):
    if isinstance(value, str) and len(value) >= 10:
        return value[:10]
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)

# ---------------------------------------------------------------------------
# Strutture default
# ---------------------------------------------------------------------------
def default_data_v33():
    return {
        "schema_version": SCHEMA_VERSION,
        "portfolio_id": "main",
        "strumenti": [],
        "operazioni": [],
        "storico_prezzi": {},
        "proventi": [],
        "last_quotes_update": None,
        "instrument_master": {},
        "registro_eventi": [],
        "registro_liquidita": [],
        "cache_posizioni": {},
        "cache_storico_portafoglio": {},
        "cache_lookup_strumenti": {},
    }


_PROFILE_TO_PORTFOLIO_OBJECTIVE = {
    "Prudente": {"core": 0.50, "difensivo": 0.40, "satellite": 0.10},
    "Equilibrato": {"core": 0.55, "difensivo": 0.25, "satellite": 0.20},
    "Dinamico": {"core": 0.50, "difensivo": 0.15, "satellite": 0.35},
    "Neutro": {"core": 0.55, "difensivo": 0.25, "satellite": 0.20},
}


def default_settings():
    return {
        "schema_version": SCHEMA_VERSION,
        "portfolio_benchmark_default": "Blend automatico",
        "risk_traffic_light_thresholds": {"green_max": 1.0, "yellow_max": 1.2},
        "analysis_lookback_days": 365,
        "include_proventi_in_total_return": True,
        "classification_mode": "hybrid",
        "quote_log_retention": 20,
        "comparison_export_format_default": "csv",
        "portfolio_objective": {"core": 0.55, "difensivo": 0.25, "satellite": 0.20},
        "category_view": {
            "selected_categories": list(DEFAULT_VISIBLE_CATEGORY_CODES),
        },
        "ui_table_density": "Standard",
        "ui_show_explanations": True,
        "ui_summary_detail_level": "Completa",
        "ui_accent_variant": "Default",
        "ui_log_level": "INFO",
        "ui_summary_include_methodology": True,
        "ui_summary_include_holdings_table": True,
        "ui_summary_include_benchmark": True,
        "ui_summary_layout": "GIPS Completo",
        "ui_debug_render_monitor": False,
        "ui_show_page_mode_controls": True,
        "operativo_mode": "entrambi",
        "sator_mode": "entrambi",
        "export_pp_mode": "entrambi",
        "privacy_mode": {
            "enabled": False,
            "hidden_tickers": [],
            "hidden_categories": [],
        },
        "portfolio_profile": {
            "portfolio_id": "main",
            "portfolio_name": "Portafoglio Principale",
            "description": "",
            "base_currency": "EUR",
            "reporting_currency": "EUR",
        },
        "reporting_export": {
            "default_format": "csv",
            "decimal_places": 2,
            "include_history": True,
            "include_methodology": True,
            "include_holdings_table": True,
            "include_benchmark": True,
        },
        "calculations_metrics": {
            "analysis_lookback_days": 365,
            "include_proventi_in_total_return": True,
            "classification_mode": "hybrid",
            "risk_traffic_light_thresholds": {"green_max": 1.0, "yellow_max": 1.2},
            "rolling_window_days": 90,
            "inflation_rate": 0.0,
            "performance_fee_rate": 0.0,
        },
        "benchmarking": {
            "default_portfolio_benchmark": "Blend automatico",
            "custom_enabled": False,
            "custom_name": "",
            "custom_components": [],
        },
        "alerts": {
            "enabled": False,
            "show_overview": True,
            "max_items": 3,
            "risk_weight_monitoring": True,
            "loss_threshold_pct": None,
            "concentration_threshold_pct": None,
            "drawdown_threshold_pct": None,
            "volatility_threshold_pct": None,
        },
        "ui_preferences": {
            "table_density": "Standard",
            "show_explanations": True,
            "summary_detail_level": "Completa",
            "accent_variant": "Default",
            "font_scale": "Grande",
            "summary_layout": "GIPS Completo",
            "summary_show_commentary": True,
            "summary_show_advanced_metrics": True,
            "debug_render_monitor": False,
            "debug_render_progress": False,
            "debug_render_log": False,
            "debug_render_scope": "current_page",
            "show_page_mode_controls": True,
            "page_mode": "per_pagina",
        },
        "auditing": {
            "enabled": True,
            "track_settings_history": True,
            "track_import_export": True,
        },
        "newsletter": {
            "enabled": False,
            "delivery_mode": "manuale",
            "detail_level": "Completa",
            "include_summary": True,
            "include_alerts": True,
            "include_top_holdings": True,
            "include_macro_allocation": True,
            "include_benchmark_context": True,
            "include_commentary": True,
            "max_holdings": 5,
            "subject_prefix": "Daily Brief",
            "send_time_local": "18:00",
        },
        "i18n": {
            "language": "it",
            "locale": "it-IT",
            "date_format": "DD/MM/YYYY",
            "number_format": "it-IT",
        },
        "backup": {
            "enabled": True,
            "backup_before_migration": True,
            "backup_before_save": False,
            "keep_last_n": 20,
            "folder": "backups"
        },
        "ui_figure_cache": {
            "enabled": True,                    # Enable/disable figure caching
            "strategy": "hybrid",               # "disabled", "session_only", "disk_only", "hybrid"
            "use_gzip": False,                  # Compress JSON on disk
            "max_cache_size_mb": 500,           # Max disk cache size (soft limit)
            "auto_cleanup_days": 30,            # Auto-remove figures older than N days
        },
        "ui_pre_render": {
            "enabled": True,
            "initial_complete": True,
            "background_enabled": True,
            "cooldown_seconds": 1800,
            "scope": "core_charts_v1",
        },
        "sator": {
            "enabled": True,
            "budget_preset": 900.0,
            "default_budget": 900.0,
            "include_watchlist": True,
            "include_candidates": True,
            "include_portfolio": True,
            "allow_new_entries": True,
            "max_lines_per_scenario": 4,
            "max_new_entries": 2,
            "max_satellite_share": 0.40,
            "score_weights": {
                "strategic_fit": 0.30,
                "tactical_momentum": 0.25,
                "risk_efficiency": 0.20,
                "diversification_benefit": 0.15,
                "cost_efficiency": 0.10,
            },
            "scenario_mix": {
                "strategico": {"core": 0.72, "defensive": 0.20, "satellite": 0.08},
                "bilanciato": {"core": 0.58, "defensive": 0.25, "satellite": 0.17},
                "difensivo": {"core": 0.25, "defensive": 0.62, "satellite": 0.13},
                "opportunistico": {"core": 0.38, "defensive": 0.18, "satellite": 0.44},
                "nuovi_ingressi": {"core": 0.44, "defensive": 0.24, "satellite": 0.32},
            },
        },
        "appearance": {
            "color_palette": "Default",
            "typography": {
                "titles": "1.4rem",
                "subtitles": "1.1rem",
                "body": "0.95rem",
                "caption": "0.85rem"
            },
            "visibility_mode": "Standard",
            "custom_visibility": {}
        }
    }


def _normalize_settings_payload(settings):
    """Normalizza il payload settings e mantiene compatibilità tra chiavi flat e sezioni annidate."""
    defaults = default_settings()
    raw_settings = settings or {}

    def _prefer_nested_value(
        section_name: str,
        nested_key: str,
        flat_key: str,
        fallback: Any,
    ) -> Any:
        section_payload = raw_settings.get(section_name, {})
        if isinstance(section_payload, dict) and nested_key in section_payload:
            return section_payload.get(nested_key, fallback)
        return raw_settings.get(flat_key, fallback)

    # Retrocompatibilità: converti il vecchio bool ui_show_page_mode_controls al nuovo ui_page_mode
    if "ui_page_mode" not in raw_settings and "ui_show_page_mode_controls" in raw_settings:
        old_bool = raw_settings.get("ui_show_page_mode_controls", True)
        raw_settings["ui_page_mode"] = "per_pagina" if old_bool else "rapida"

    # Assicura che ui_page_mode sia sempre presente
    if "ui_page_mode" not in raw_settings:
        raw_settings["ui_page_mode"] = "per_pagina"  # default

    merged = _deep_merge_defaults(defaults, raw_settings)

    portfolio_profile = merged.setdefault("portfolio_profile", {})
    calculations = merged.setdefault("calculations_metrics", {})
    benchmarking = merged.setdefault("benchmarking", {})
    reporting = merged.setdefault("reporting_export", {})
    alerts = merged.setdefault("alerts", {})
    ui_preferences = merged.setdefault("ui_preferences", {})
    category_view = merged.setdefault("category_view", {})
    backup = merged.setdefault("backup", {})
    newsletter = merged.setdefault("newsletter", {})

    portfolio_objective = merged.setdefault("portfolio_objective", {})
    if "portfolio_objective" not in raw_settings:
        _seed_label = str(raw_settings.get("target_profile_default") or "")
        if _seed_label in _PROFILE_TO_PORTFOLIO_OBJECTIVE:
            portfolio_objective.update(_PROFILE_TO_PORTFOLIO_OBJECTIVE[_seed_label])
    portfolio_objective["core"] = max(0.0, _safe_float(portfolio_objective.get("core"), defaults["portfolio_objective"]["core"]))
    portfolio_objective["difensivo"] = max(0.0, _safe_float(portfolio_objective.get("difensivo"), defaults["portfolio_objective"]["difensivo"]))
    portfolio_objective["satellite"] = max(0.0, _safe_float(portfolio_objective.get("satellite"), defaults["portfolio_objective"]["satellite"]))
    _obj_total = portfolio_objective["core"] + portfolio_objective["difensivo"] + portfolio_objective["satellite"]
    if _obj_total > 0:
        portfolio_objective["core"] /= _obj_total
        portfolio_objective["difensivo"] /= _obj_total
        portfolio_objective["satellite"] /= _obj_total
    else:
        portfolio_objective.update(defaults["portfolio_objective"])
    merged["portfolio_objective"] = portfolio_objective

    # Legacy -> nested
    portfolio_profile["portfolio_id"] = str(merged.get("portfolio_id") or portfolio_profile.get("portfolio_id") or "main")
    calculations["analysis_lookback_days"] = int(
        _prefer_nested_value(
            "calculations_metrics",
            "analysis_lookback_days",
            "analysis_lookback_days",
            calculations.get("analysis_lookback_days", 365),
        )
    )
    calculations["include_proventi_in_total_return"] = bool(
        _prefer_nested_value(
            "calculations_metrics",
            "include_proventi_in_total_return",
            "include_proventi_in_total_return",
            calculations.get("include_proventi_in_total_return", True),
        )
    )
    calculations["classification_mode"] = str(
        _prefer_nested_value(
            "calculations_metrics",
            "classification_mode",
            "classification_mode",
            calculations.get("classification_mode", "hybrid"),
        )
    )
    calculations["risk_traffic_light_thresholds"] = _deep_merge_defaults(
        defaults["calculations_metrics"]["risk_traffic_light_thresholds"],
        _prefer_nested_value(
            "calculations_metrics",
            "risk_traffic_light_thresholds",
            "risk_traffic_light_thresholds",
            calculations.get("risk_traffic_light_thresholds", {}),
        ),
    )
    benchmarking["default_portfolio_benchmark"] = str(
        _prefer_nested_value(
            "benchmarking",
            "default_portfolio_benchmark",
            "portfolio_benchmark_default",
            benchmarking.get("default_portfolio_benchmark", "Blend automatico"),
        )
    )
    if benchmarking["default_portfolio_benchmark"] == "100% BTP Italia":
        benchmarking["default_portfolio_benchmark"] = "100% GOV"
    benchmarking["custom_enabled"] = bool(benchmarking.get("custom_enabled", False))
    benchmarking["custom_name"] = str(benchmarking.get("custom_name", "") or "").strip()
    raw_custom_components = benchmarking.get("custom_components", [])
    normalized_components = []
    if isinstance(raw_custom_components, list):
        for item in raw_custom_components:
            if not isinstance(item, dict):
                continue
            ticker = str(item.get("ticker", "") or "").strip()
            try:
                weight = float(item.get("weight", 0) or 0)
            except (TypeError, ValueError):
                weight = 0.0
            if ticker and weight > 0:
                normalized_components.append({"ticker": ticker, "weight": weight})
    benchmarking["custom_components"] = normalized_components
    reporting["default_format"] = str(
        _prefer_nested_value(
            "reporting_export",
            "default_format",
            "comparison_export_format_default",
            reporting.get("default_format", "csv"),
        )
    )
    ui_preferences["table_density"] = str(
        _prefer_nested_value("ui_preferences", "table_density", "ui_table_density", ui_preferences.get("table_density", "Standard"))
    )
    ui_preferences["show_explanations"] = bool(
        _prefer_nested_value("ui_preferences", "show_explanations", "ui_show_explanations", ui_preferences.get("show_explanations", True))
    )
    ui_preferences["summary_detail_level"] = str(
        _prefer_nested_value("ui_preferences", "summary_detail_level", "ui_summary_detail_level", ui_preferences.get("summary_detail_level", "Completa"))
    )
    ui_preferences["accent_variant"] = str(
        _prefer_nested_value("ui_preferences", "accent_variant", "ui_accent_variant", ui_preferences.get("accent_variant", "Default"))
    )
    ui_preferences["font_scale"] = str(
        _prefer_nested_value("ui_preferences", "font_scale", "ui_font_scale", ui_preferences.get("font_scale", "Grande"))
    )
    ui_preferences["log_level"] = str(
        _prefer_nested_value("ui_preferences", "log_level", "ui_log_level", ui_preferences.get("log_level", "INFO"))
    ).upper()
    ui_preferences["debug_render_monitor"] = bool(
        _prefer_nested_value("ui_preferences", "debug_render_monitor", "ui_debug_render_monitor", ui_preferences.get("debug_render_monitor", False))
    )
    ui_preferences["debug_render_progress"] = bool(
        ui_preferences.get("debug_render_progress", False)
    )
    ui_preferences["debug_render_log"] = bool(
        ui_preferences.get("debug_render_log", False)
    )
    ui_preferences["debug_render_scope"] = str(
        ui_preferences.get("debug_render_scope", "current_page") or "current_page"
    )
    ui_preferences["show_page_mode_controls"] = bool(
        _prefer_nested_value("ui_preferences", "show_page_mode_controls", "ui_show_page_mode_controls", ui_preferences.get("show_page_mode_controls", True))
    )
    ui_preferences["page_mode"] = str(
        _prefer_nested_value("ui_preferences", "page_mode", "ui_page_mode", ui_preferences.get("page_mode", "per_pagina"))
    )
    ui_preferences["summary_layout"] = str(
        _prefer_nested_value("ui_preferences", "summary_layout", "ui_summary_layout", ui_preferences.get("summary_layout", "GIPS Completo"))
    )
    ui_preferences["summary_show_commentary"] = bool(
        _prefer_nested_value("ui_preferences", "summary_show_commentary", "ui_summary_show_commentary", ui_preferences.get("summary_show_commentary", True))
    )
    ui_preferences["summary_show_advanced_metrics"] = bool(
        _prefer_nested_value("ui_preferences", "summary_show_advanced_metrics", "ui_summary_show_advanced_metrics", ui_preferences.get("summary_show_advanced_metrics", True))
    )
    reporting["include_methodology"] = bool(
        _prefer_nested_value("reporting_export", "include_methodology", "ui_summary_include_methodology", reporting.get("include_methodology", True))
    )
    reporting["include_holdings_table"] = bool(
        _prefer_nested_value("reporting_export", "include_holdings_table", "ui_summary_include_holdings_table", reporting.get("include_holdings_table", True))
    )
    reporting["include_benchmark"] = bool(
        _prefer_nested_value("reporting_export", "include_benchmark", "ui_summary_include_benchmark", reporting.get("include_benchmark", True))
    )
    alerts["enabled"] = bool(alerts.get("enabled", False))
    alerts["show_overview"] = bool(alerts.get("show_overview", True))
    alerts["risk_weight_monitoring"] = bool(alerts.get("risk_weight_monitoring", True))
    alerts["max_items"] = int(alerts.get("max_items", defaults["alerts"]["max_items"]) or defaults["alerts"]["max_items"])
    alerts["loss_threshold_pct"] = (
        float(alerts["loss_threshold_pct"]) if alerts.get("loss_threshold_pct") not in (None, "", False) else None
    )
    alerts["concentration_threshold_pct"] = (
        float(alerts["concentration_threshold_pct"]) if alerts.get("concentration_threshold_pct") not in (None, "", False) else None
    )
    alerts["drawdown_threshold_pct"] = (
        float(alerts["drawdown_threshold_pct"]) if alerts.get("drawdown_threshold_pct") not in (None, "", False) else None
    )
    alerts["volatility_threshold_pct"] = (
        float(alerts["volatility_threshold_pct"]) if alerts.get("volatility_threshold_pct") not in (None, "", False) else None
    )
    newsletter["enabled"] = bool(newsletter.get("enabled", False))
    newsletter["delivery_mode"] = str(newsletter.get("delivery_mode", "manuale") or "manuale")
    newsletter["detail_level"] = str(newsletter.get("detail_level", "Completa") or "Completa")
    newsletter["include_summary"] = bool(newsletter.get("include_summary", True))
    newsletter["include_alerts"] = bool(newsletter.get("include_alerts", True))
    newsletter["include_top_holdings"] = bool(newsletter.get("include_top_holdings", True))
    newsletter["include_macro_allocation"] = bool(newsletter.get("include_macro_allocation", True))
    newsletter["include_benchmark_context"] = bool(newsletter.get("include_benchmark_context", True))
    newsletter["include_commentary"] = bool(newsletter.get("include_commentary", True))
    newsletter["max_holdings"] = int(newsletter.get("max_holdings", defaults["newsletter"]["max_holdings"]) or defaults["newsletter"]["max_holdings"])
    newsletter["subject_prefix"] = str(newsletter.get("subject_prefix", "Daily Brief") or "Daily Brief").strip() or "Daily Brief"
    newsletter["send_time_local"] = str(newsletter.get("send_time_local", "18:00") or "18:00").strip() or "18:00"
    category_view["selected_categories"] = normalize_category_selection(
        category_view.get("selected_categories", defaults["category_view"]["selected_categories"])
    )
    backup["keep_last_n"] = int(backup.get("keep_last_n", 20))
    merged["quote_log_retention"] = int(merged.get("quote_log_retention", 20))

    # Nested -> legacy flat mirrors
    merged["portfolio_id"] = portfolio_profile["portfolio_id"]
    merged["portfolio_benchmark_default"] = benchmarking["default_portfolio_benchmark"]
    merged["risk_traffic_light_thresholds"] = _deep_clone(calculations["risk_traffic_light_thresholds"])
    merged["analysis_lookback_days"] = calculations["analysis_lookback_days"]
    merged["include_proventi_in_total_return"] = calculations["include_proventi_in_total_return"]
    merged["classification_mode"] = calculations["classification_mode"]
    merged["comparison_export_format_default"] = reporting["default_format"]
    merged["ui_table_density"] = ui_preferences["table_density"]
    merged["ui_show_explanations"] = ui_preferences["show_explanations"]
    merged["ui_summary_detail_level"] = ui_preferences["summary_detail_level"]
    merged["ui_accent_variant"] = ui_preferences["accent_variant"]
    merged["ui_font_scale"] = ui_preferences["font_scale"]
    merged["ui_debug_render_monitor"] = ui_preferences["debug_render_monitor"]
    merged["ui_show_page_mode_controls"] = ui_preferences["show_page_mode_controls"]
    merged["ui_page_mode"] = ui_preferences["page_mode"]
    merged["ui_summary_layout"] = ui_preferences["summary_layout"]
    merged["ui_summary_show_commentary"] = ui_preferences["summary_show_commentary"]
    merged["ui_summary_show_advanced_metrics"] = ui_preferences["summary_show_advanced_metrics"]
    merged["ui_summary_include_methodology"] = reporting["include_methodology"]
    merged["ui_summary_include_holdings_table"] = reporting["include_holdings_table"]
    merged["ui_summary_include_benchmark"] = reporting["include_benchmark"]
    merged["category_view"] = _deep_merge_defaults(defaults["category_view"], category_view)
    merged["backup"] = _deep_merge_defaults(defaults["backup"], backup)

    return merged


def _normalize_snapshot_payload(payload):
    base = default_snapshots()
    raw = payload if isinstance(payload, dict) else {}
    normalized = {
        "schema_version": str(raw.get("schema_version") or SCHEMA_VERSION),
        "snapshots": [],
    }
    raw_snapshots = raw.get("snapshots", [])
    if not isinstance(raw_snapshots, list):
        raw_snapshots = []
    for snap in raw_snapshots:
        if not isinstance(snap, dict):
            continue
        item = json.loads(json.dumps(snap))
        raw_weights = item.get("macro_weights", {})
        norm_weights = {code: 0.0 for code in ACTIVE_CATEGORY_CODES}
        if isinstance(raw_weights, dict):
            for raw_key, raw_value in raw_weights.items():
                norm_key = normalize_category_code(raw_key, default=str(raw_key or "").strip().upper())
                if norm_key in ACTIVE_CATEGORY_CODES:
                    try:
                        norm_weights[norm_key] = float(raw_value or 0.0)
                    except (TypeError, ValueError):
                        norm_weights[norm_key] = 0.0
        item["macro_weights"] = norm_weights
        holdings = item.get("holdings", [])
        if isinstance(holdings, list):
            normalized_holdings = []
            for holding in holdings:
                if not isinstance(holding, dict):
                    continue
                holding_item = json.loads(json.dumps(holding))
                if "categoria" in holding_item:
                    holding_item["categoria"] = normalize_category_code(holding_item.get("categoria"), default=str(holding_item.get("categoria") or ""))
                normalized_holdings.append(holding_item)
            item["holdings"] = normalized_holdings
        normalized["snapshots"].append(item)
    return _deep_merge_defaults(base, normalized)


def _normalize_sator_decisions_payload(payload):
    base = default_sator_decisions()
    raw = payload if isinstance(payload, dict) else {}
    normalized = {"schema_version": SCHEMA_VERSION, "items": []}
    raw_items = raw.get("items", [])
    if not isinstance(raw_items, list):
        raw_items = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        entry = json.loads(json.dumps(item))
        entry["decision_id"] = str(entry.get("decision_id") or "")
        entry["created_at"] = str(entry.get("created_at") or "")
        entry["month_id"] = str(entry.get("month_id") or "")
        entry["budget"] = _safe_float(entry.get("budget"), 0.0)
        entry["scenario_key"] = str(entry.get("scenario_key") or "")
        entry["scenario_label"] = str(entry.get("scenario_label") or "")
        entry["summary"] = entry.get("summary", {}) if isinstance(entry.get("summary", {}), dict) else {}
        entry["order_lines"] = entry.get("order_lines", []) if isinstance(entry.get("order_lines", []), list) else []
        entry["exclusions"] = entry.get("exclusions", []) if isinstance(entry.get("exclusions", []), list) else []
        entry["alerts"] = entry.get("alerts", []) if isinstance(entry.get("alerts", []), list) else []
        entry["ranking_head"] = entry.get("ranking_head", []) if isinstance(entry.get("ranking_head", []), list) else []
        entry["actual_order"] = entry.get("actual_order", []) if isinstance(entry.get("actual_order", []), list) else []
        entry["note"] = str(entry.get("note") or "")
        normalized["items"].append(entry)
    return _deep_merge_defaults(base, normalized)


def _normalize_portfolio_data_payload(payload):
    base = default_data_v33()
    raw = payload if isinstance(payload, dict) else {}
    normalized = _deep_merge_defaults(base, raw)
    instrument_master = normalized.get("instrument_master", {})
    if isinstance(instrument_master, dict):
        for ticker, info in instrument_master.items():
            if not isinstance(info, dict):
                continue
            macro_value = info.get("macro_category") or info.get("categoria") or info.get("tipo")
            info["macro_category"] = infer_category_code(macro_value, default="ALTRO")
            if not info.get("asset_class"):
                info["asset_class"] = category_name(info["macro_category"])
            instrument_master[ticker] = info
        normalized["instrument_master"] = instrument_master
    return normalized


def default_quotes_log():
    return {"schema_version": SCHEMA_VERSION, "last_refresh": None, "items": []}


def default_snapshots():
    return {"schema_version": SCHEMA_VERSION, "snapshots": []}


def default_sator_decisions():
    return {"schema_version": SCHEMA_VERSION, "items": []}


def default_benchmark_cache():
    return {"schema_version": SCHEMA_VERSION, "benchmark_data": {}}


def default_meta():
    return {
        "schema_version": SCHEMA_VERSION,
        "migration": {
            "migrated_from_legacy": False,
            "migration_timestamp": None,
            "source_file": os.path.basename(DATA_FILE),
            "backup_file": None,
            "notes": []
        },
        "runtime": {
            "last_start": None,
            "last_successful_save": None
        },
        "audit": {
            "last_event": None,
            "events": []
        }
    }


def _audit_timestamp() -> str:
    """Timestamp locale uniforme per gli eventi di audit."""
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _summarize_settings_changes(previous: dict, current: dict) -> list[str]:
    """Restituisce le macro-sezioni settings cambiate tra due payload normalizzati."""
    tracked_sections = [
        "portfolio_profile",
        "calculations_metrics",
        "benchmarking",
        "alerts",
        "sator",
        "reporting_export",
        "ui_preferences",
        "backup",
        "auditing",
        "newsletter",
        "i18n",
    ]
    changed = [
        section
        for section in tracked_sections
        if previous.get(section) != current.get(section)
    ]
    return changed


def describe_audit_event(entry: dict | None) -> dict[str, str]:
    """Restituisce etichetta, categoria e sintesi leggibile di un evento audit."""
    payload = entry if isinstance(entry, dict) else {}
    event_type = str(payload.get("event_type") or "unknown")
    details = payload.get("details", {}) if isinstance(payload.get("details", {}), dict) else {}
    meta = AUDIT_EVENT_CATALOG.get(event_type, {"label": event_type, "category": "Altro"})
    label = str(meta.get("label", event_type))
    category = str(meta.get("category", "Altro"))

    if event_type == "settings_saved":
        changed = details.get("changed_sections", [])
        changed_text = ", ".join(changed) if isinstance(changed, list) and changed else "nessuna sezione rilevata"
        summary = f"Sezioni aggiornate: {changed_text}"
    elif event_type == "backup_created":
        summary = f"Cartella {details.get('tag') or details.get('folder') or 'n/d'} - file copiati: {details.get('file_count', 'n/d')}"
    elif event_type == "backup_restored":
        summary = f"Backup {details.get('backup', 'n/d')} - file ripristinati: {details.get('files_restored', 'n/d')}"
    elif event_type == "backup_deleted":
        summary = f"Backup eliminato: {details.get('backup', 'n/d')}"
    elif event_type == "snapshot_created":
        summary = str(details.get("label") or "Snapshot manuale registrato")
    elif event_type == "quotes_imported":
        summary = f"Data {details.get('date', 'n/d')} - aggiornati: {details.get('updated', 0)} - ignorati: {details.get('skipped', 0)}"
    elif event_type == "quotes_reset":
        strumenti = details.get("strumenti", [])
        strumenti_text = ", ".join(strumenti) if isinstance(strumenti, list) else str(strumenti or "n/d")
        from_date = details.get("from_date")
        summary = f"Modalità: {details.get('mode', 'n/d')} - strumenti: {strumenti_text} - modificati: {details.get('changed', 0)}"
        if from_date:
            summary += f" - da data: {from_date}"
    else:
        summary = json.dumps(details, ensure_ascii=False) if details else ""

    return {"label": label, "category": category, "summary": summary}


def append_audit_event(event_type, details=None, status="ok"):
    """Aggiunge un evento al registro audit nel file meta."""
    meta = load_meta()
    audit = meta.setdefault("audit", default_meta()["audit"])
    events = audit.setdefault("events", [])
    entry = {
        "timestamp": _audit_timestamp(),
        "event_type": str(event_type or "unknown"),
        "status": str(status or "ok"),
        "details": details if isinstance(details, dict) else {},
    }
    entry["category"] = describe_audit_event(entry).get("category", "Altro")
    events.append(entry)
    audit["events"] = events[-100:]
    audit["last_event"] = entry
    save_meta(meta)
    logger.info("Audit event registrato: type=%s status=%s", entry["event_type"], entry["status"])

# ---------------------------------------------------------------------------
# Funzioni evento — necessarie per migrate_to_v33_if_needed e load_data
# ---------------------------------------------------------------------------
def _event_sort_key(evento):
    return (
        str(evento.get("data", "")),
        str(evento.get("event_id", "")),
        str(evento.get("tipo_evento", "")),
    )


def _new_event_id(data, prefix="evt"):
    seq = int(data.get("_event_seq", 0) or 0) + 1
    data["_event_seq"] = seq
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{seq:05d}"


def _normalize_event_record(ev):
    tipo = str(ev.get("tipo_evento", ev.get("tipo", ""))).strip().upper()
    out = {
        "event_id": ev.get("event_id") or ev.get("id") or "",
        "origine": ev.get("origine", "registro_eventi"),
        "indice_origine": ev.get("indice_origine"),
        "data": _safe_date_str(ev.get("data")),
        "tipo_evento": tipo,
        "ticker": ev.get("ticker", "") or "",
        "quantita": _safe_float(ev.get("quantita", ev.get("qty", 0))),
        "prezzo_unitario": _safe_float(ev.get("prezzo_unitario", ev.get("price", 0))),
        "importo_lordo": _safe_float(ev.get("importo_lordo", ev.get("gross_amount", 0))),
        "commissioni": _safe_float(ev.get("commissioni", ev.get("comm", 0))),
        "imposte": _safe_float(ev.get("imposte", ev.get("tax_amount", 0))),
        "importo_netto": ev.get("importo_netto", ev.get("net_cash_flow")),
        "aliquota": _safe_float(ev.get("aliquota", 0)),
        "note": ev.get("note", ""),
    }
    if out["importo_netto"] in (None, ""):
        if tipo in {"ACQUISTO", "COMMISSIONE", "IMPOSTA", "PRELIEVO"}:
            if tipo == "ACQUISTO":
                out["importo_netto"] = - (out["quantita"] * out["prezzo_unitario"] + out["commissioni"] + out["imposte"])
            else:
                out["importo_netto"] = - abs(out["importo_lordo"] or out["commissioni"] or out["imposte"])
        elif tipo in {"VENDITA", "RIMBORSO A SCADENZA", "CEDOLA", "DIVIDENDO", "VERSAMENTO"}:
            base = out["importo_lordo"]
            if tipo in {"VENDITA", "RIMBORSO A SCADENZA"} and base == 0:
                base = out["quantita"] * out["prezzo_unitario"]
            out["importo_netto"] = base - out["commissioni"] - out["imposte"]
        else:
            out["importo_netto"] = 0.0
    out["importo_netto"] = _safe_float(out["importo_netto"], 0.0)
    if not out["event_id"]:
        out["event_id"] = f"ev_{out['data'].replace('-', '')}_{abs(hash((out['tipo_evento'], out['ticker'], out['quantita'], out['prezzo_unitario'], out['importo_netto']))) % 1000000:06d}"
    return out


def _rebuild_cash_ledger_from_events(eventi):
    ledger = []
    for ev in sorted(eventi, key=_event_sort_key):
        importo = _safe_float(ev.get("importo_netto", 0))
        if abs(importo) <= 1e-12:
            continue
        ledger.append({
            "cash_id": f"cash_{ev.get('event_id','')}",
            "data": ev.get("data"),
            "causale": ev.get("tipo_evento"),
            "event_id": ev.get("event_id"),
            "importo": importo,
            "descrizione": ev.get("note") or f"{ev.get('tipo_evento')} {ev.get('ticker','')}`".replace('`','').strip(),
        })
    return ledger


def get_registro_eventi(data):
    eventi = [_normalize_event_record(x) for x in (data.get("registro_eventi", []) or [])]
    return sorted(eventi, key=_event_sort_key)


def get_proventi_normalizzati(data):
    out = []
    for ev in get_registro_eventi(data):
        if ev.get("tipo_evento") in {"CEDOLA", "DIVIDENDO"}:
            out.append({
                "data": ev.get("data"),
                "ticker": ev.get("ticker", ""),
                "tipo": ev.get("tipo_evento"),
                "importo_lordo": _safe_float(ev.get("importo_lordo", 0)),
                "aliquota": _safe_float(ev.get("aliquota", 0)),
                "importo_netto": _safe_float(ev.get("importo_netto", 0)),
                "note": ev.get("note", ""),
            })
    return out


def _serialize_df_for_cache(df):
    if df is None or df.empty:
        return []
    rows = []
    for rec in df.to_dict("records"):
        row = {}
        for k, v in rec.items():
            if isinstance(v, (pd.Timestamp, datetime, date)):
                row[k] = str(pd.to_datetime(v).date())
            elif isinstance(v, (np.floating, np.integer)):
                row[k] = float(v)
            else:
                row[k] = v
        rows.append(row)
    return rows


def _restore_df_from_cache(rows):
    df = pd.DataFrame(rows or [])
    if not df.empty and "Ultimo evento" in df.columns:
        try:
            df["Ultimo evento"] = df["Ultimo evento"].astype(str)
        except Exception:
            pass
    return df


def _state_signature(data, price_map=None, include_closed=True):
    """Firma unica per invalidare qualsiasi cache dipendente dallo stato portafoglio.
    Sostituisce _portfolio_state_signature — unica copia, usata da compute_portfolio_state
    e build_portfolio_history_df."""
    eventi = get_registro_eventi(data)
    price_map = price_map or {}
    # Includi i prezzi correnti degli strumenti nella firma: senza di questo, dopo un
    # aggiornamento quotazioni senza nuovi eventi la cache interna non viene invalidata
    # e restituisce prezzi obsoleti (es. dopo un refresh nel weekend).
    current_prices = {s.get("ticker", ""): s.get("prezzo") for s in data.get("strumenti", [])}
    eventi_sig = hashlib.md5(json.dumps(eventi, sort_keys=True, default=str).encode()).hexdigest()
    merged_prices = {**current_prices, **price_map}
    prezzi_sig = hashlib.md5(json.dumps(merged_prices, sort_keys=True, default=str).encode()).hexdigest()
    return f"{eventi_sig}|{prezzi_sig}|{1 if include_closed else 0}"

# Alias per retrocompatibilità con qualsiasi chiamata esistente nel file principale
_portfolio_state_signature = _state_signature

# ---------------------------------------------------------------------------
# Instrument master
# ---------------------------------------------------------------------------
def _build_instrument_master(strumenti, benchmark_data=None):
    benchmark_data = benchmark_data or {}
    out = {}
    for s in strumenti or []:
        tk = s.get("ticker", "")
        if not tk:
            continue
        raw_type = s.get("tipo", "")
        mc = macro_cat(raw_type)
        bench = resolve_instrument_benchmark(s, raw_type=raw_type, category=mc, prefer_master=False)
        bench_tk, bench_lbl = bench.ticker or None, bench.label or None
        out[tk] = {
            "ticker": tk,
            "isin": s.get("isin"),
            "name": s.get("nome", tk),
            "type_raw": raw_type,
            "macro_category": mc,
            "asset_class": category_name(mc),
            "sub_asset_class": raw_type or mc,
            "currency": "EUR",
            "country_area": "Italia" if mc == "GOV" else "Globale",
            "benchmark_code": bench_tk,
            "benchmark_label": bench_lbl,
            "source_quality": "derived",
            "manual_overrides": {}
        }
    return out

# ---------------------------------------------------------------------------
# Backup Utility
# ---------------------------------------------------------------------------
def create_backup_bundle(tag=None):
    _ensure_dir(BACKUP_DIR)
    stamp = tag or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    folder = os.path.join(BACKUP_DIR, stamp)
    _ensure_dir(folder)
    copied = []
    for src in [DATA_FILE, SETTINGS_FILE, QUOTES_LOG_FILE, SNAPSHOTS_FILE, BENCHMARK_CACHE_FILE, META_FILE]:
        if os.path.exists(src):
            dst = os.path.join(folder, os.path.basename(src))
            shutil.copy2(src, dst)
            copied.append(dst)
    logger.info("Backup bundle creato: folder=%s files=%s", folder, len(copied))
    settings = load_settings()
    auditing_cfg = settings.get("auditing", {})
    if auditing_cfg.get("enabled") and auditing_cfg.get("track_import_export"):
        append_audit_event(
            "backup_created",
            {"folder": folder, "file_count": len(copied), "tag": tag or stamp},
        )
    return folder, copied


# ---------------------------------------------------------------------------
# Load / Save
# ---------------------------------------------------------------------------
def load_settings():
    raw = _read_json_file(SETTINGS_FILE, default_settings())
    normalized = _normalize_settings_payload(raw)
    if raw != normalized:
        _write_json_file(SETTINGS_FILE, normalized)
    return normalized


def save_settings(settings):
    previous = _normalize_settings_payload(_read_json_file(SETTINGS_FILE, default_settings()))
    normalized = _normalize_settings_payload(settings)
    _write_json_file(SETTINGS_FILE, normalized)
    logger.info("Settings salvate: path=%s", SETTINGS_FILE)
    auditing_cfg = normalized.get("auditing", {})
    if auditing_cfg.get("enabled") and auditing_cfg.get("track_settings_history"):
        changed_sections = _summarize_settings_changes(previous, normalized)
        append_audit_event(
            "settings_saved",
            {
                "changed_sections": changed_sections,
                "portfolio_id": normalized.get("portfolio_id", "main"),
            },
        )


def load_quotes_log():
    q = _read_json_file(QUOTES_LOG_FILE, default_quotes_log())
    q.setdefault("schema_version", SCHEMA_VERSION)
    q.setdefault("last_refresh", None)
    q.setdefault("items", [])
    return q


def save_quotes_log(q):
    _write_json_file(QUOTES_LOG_FILE, q)
    logger.info("Quotes log salvato: path=%s items=%s", QUOTES_LOG_FILE, len(q.get("items", [])) if isinstance(q, dict) else 0)


def load_snapshots():
    raw = _read_json_file(SNAPSHOTS_FILE, default_snapshots())
    normalized = _normalize_snapshot_payload(raw)
    if raw != normalized:
        _write_json_file(SNAPSHOTS_FILE, normalized)
    return normalized


def save_snapshots(s):
    normalized = _normalize_snapshot_payload(s)
    _write_json_file(SNAPSHOTS_FILE, normalized)
    logger.info("Snapshots salvati: path=%s count=%s", SNAPSHOTS_FILE, len(normalized.get("snapshots", [])) if isinstance(normalized, dict) else 0)


def load_sator_decisions():
    raw = _read_json_file(SATOR_DECISIONS_FILE, default_sator_decisions())
    normalized = _normalize_sator_decisions_payload(raw)
    if raw != normalized:
        _write_json_file(SATOR_DECISIONS_FILE, normalized)
    return normalized


def save_sator_decisions(payload):
    normalized = _normalize_sator_decisions_payload(payload)
    _write_json_file(SATOR_DECISIONS_FILE, normalized)
    logger.info("Decisioni SATOR salvate: path=%s count=%s", SATOR_DECISIONS_FILE, len(normalized.get("items", [])) if isinstance(normalized, dict) else 0)


def remove_sator_decision(decisions: dict, decision_id: str) -> tuple[dict, bool]:
    """Rimuove dalla struttura decisioni SATOR l'item con il decision_id dato.

    Non scrive su disco: il chiamante deve invocare save_sator_decisions() col
    risultato. Ritorna (nuova_struttura, True) se un item e' stato rimosso,
    (struttura con items invariati, False) se il decision_id non esisteva.
    """
    items = list((decisions or {}).get("items") or [])
    remaining = [it for it in items if str((it or {}).get("decision_id")) != str(decision_id)]
    removed = len(remaining) != len(items)
    result = dict(decisions or {})
    result["items"] = remaining
    return result, removed


def load_meta():
    m = _read_json_file(META_FILE, default_meta())
    m.setdefault("schema_version", SCHEMA_VERSION)
    m.setdefault("migration", default_meta()["migration"])
    m.setdefault("runtime", default_meta()["runtime"])
    m.setdefault("audit", default_meta()["audit"])
    return m


def save_meta(m):
    _write_json_file(META_FILE, m)
    logger.debug("Meta salvati: path=%s", META_FILE)


def load_data():
    from persistence.parquet_utils import load_storico_prezzi_hybrid

    _migrate_json_to_data_dir()
    raw = _read_json_file(DATA_FILE, default_data_v33())
    d = _normalize_portfolio_data_payload(raw)
    base = default_data_v33()
    for k, v in base.items():
        d.setdefault(k, json.loads(json.dumps(v)))
    d.setdefault("benchmark_data", _read_json_file(BENCHMARK_CACHE_FILE, default_benchmark_cache()).get("benchmark_data", {}))

    # Load storico_prezzi with hybrid JSON-Parquet support
    d["storico_prezzi"] = load_storico_prezzi_hybrid(STORICO_PREZZI_FILE)

    d.setdefault("instrument_master", _build_instrument_master(d.get("strumenti", []), d.get("benchmark_data", {})))
    if raw != d:
        _write_json_file(DATA_FILE, d)
    logger.debug("Dati caricati: strumenti=%s eventi=%s storico_prezzi=%s", len(d.get("strumenti", [])), len(d.get("registro_eventi", [])), len(d.get("storico_prezzi", {})))
    return d


def save_data(data, *, include_storico: bool = True):
    from persistence.parquet_utils import save_storico_prezzi_hybrid

    settings = load_settings()
    if settings.get("backup", {}).get("enabled") and settings.get("backup", {}).get("backup_before_save"):
        create_backup_bundle()

    # Extract storico_prezzi for separate hybrid JSON-Parquet storage
    storico_prezzi = data.get("storico_prezzi", {})
    if include_storico:
        save_storico_prezzi_hybrid(storico_prezzi, STORICO_PREZZI_FILE)

    core = {
        "schema_version": SCHEMA_VERSION,
        "portfolio_id": data.get("portfolio_id", "main"),
        "strumenti": data.get("strumenti", []),
        "operazioni": data.get("operazioni", []),
        "storico_prezzi": {},  # Empty reference (loaded separately from Parquet/JSON)
        "proventi": data.get("proventi", []),
        "last_quotes_update": data.get("last_quotes_update"),
        "instrument_master": data.get("instrument_master") or _build_instrument_master(data.get("strumenti", []), data.get("benchmark_data", {})),
        "registro_eventi": data.get("registro_eventi", []),
        "registro_liquidita": data.get("registro_liquidita", []),
        "cache_posizioni": data.get("cache_posizioni", {}),
        "cache_storico_portafoglio": data.get("cache_storico_portafoglio", {}),
        "cache_lookup_strumenti": data.get("cache_lookup_strumenti", {}),
    }
    core = _normalize_portfolio_data_payload(core)
    _write_json_file(DATA_FILE, core)
    _write_json_file(BENCHMARK_CACHE_FILE, {"schema_version": SCHEMA_VERSION, "benchmark_data": data.get("benchmark_data", {})})
    meta = load_meta()
    meta.setdefault("runtime", {})["last_successful_save"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    save_meta(meta)
    logger.info(
        "Dati salvati: strumenti=%s operazioni=%s proventi=%s storico_date=%s",
        len(core.get("strumenti", [])),
        len(core.get("operazioni", [])),
        len(core.get("proventi", [])),
        len(storico_prezzi),
    )


def save_benchmark_data(data):
    """Salva solo la cache benchmark evitando di riscrivere anche lo storico prezzi."""
    _write_json_file(BENCHMARK_CACHE_FILE, {"schema_version": SCHEMA_VERSION, "benchmark_data": data.get("benchmark_data", {})})
    meta = load_meta()
    meta.setdefault("runtime", {})["last_successful_save"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    save_meta(meta)
    logger.info(
        "Cache benchmark salvata: serie=%s",
        len(data.get("benchmark_data", {})) if isinstance(data.get("benchmark_data", {}), dict) else 0,
    )


def _data_mtime() -> float:
    try:
        mtimes = [
            os.path.getmtime(path)
            for path in [DATA_FILE, SETTINGS_FILE, SNAPSHOTS_FILE, META_FILE]
            if os.path.exists(path)
        ]
        return max(mtimes) if mtimes else 0.0
    except OSError:
        return 0.0
