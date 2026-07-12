"""
core/config.py - Configurazione centralizzata per refactoring incrementale.

Questo modulo e' pensato come fonte stabile per costanti globali che oggi sono
ancora usate in piu' layer. Le fasi successive potranno sostituire gradualmente
i valori hardcoded importando da qui o dal tema UI.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"

COLORS: dict[str, str] = {
    "success": "#1E8449",
    "danger": "#FF4B4B",
    "info": "#5B8DEF",
    "warning": "#FFA726",
    "yellow": "#F39C12",
    "purple": "#8E44AD",
    "gray": "#6B7280",
    "muted": "#B0B3BC",
    "category_gov": "#E8B960",
    "category_etf": "#5B8DEF",
    "category_fnd": "#B07CC6",
    "category_etc": "#C2410C",
    "category_default": "#6EC6C6",
    "instrument_1": "#5B8DEF",
    "instrument_2": "#00D4AA",
    "instrument_3": "#FFA726",
    "instrument_4": "#B07CC6",
    "instrument_5": "#EF6C9A",
    "instrument_6": "#26A69A",
    "bg_app": "#F6F8FC",
    "bg_surface": "#FFFFFF",
    "bg_chart": "#FFFFFF",
    "font": "#223144",
    "muted_rgba": "rgba(34,49,68,0.60)",
    "border_rgba": "rgba(34,49,68,0.12)",
    "grid_rgba": "rgba(34,49,68,0.10)",
    "shadow": "0 14px 32px rgba(31,45,61,0.08)",
}

THRESHOLDS: dict[str, float] = {
    "risk_traffic_light_green": 1.0,
    "risk_traffic_light_yellow": 1.2,
    "concentration_warning": 0.35,
    "drawdown_alert": -0.10,
    "negative_pl_alert_eur": -500.0,
    "rebalance_minimum_eur": 50.0,
}

PRICES_DIR = DATA_DIR / "prices"

PATHS: dict[str, Path] = {
    "base_dir": BASE_DIR,
    "data_dir": DATA_DIR,
    "prices_dir": PRICES_DIR,
    "portfolio_data": DATA_DIR / "portfolio" / "portafoglio_data.json",
    "portfolio_meta": DATA_DIR / "config" / "portafoglio_meta.json",
    "quotes_log": DATA_DIR / "cache" / "portafoglio_quotes_log.json",
    "settings": DATA_DIR / "config" / "portafoglio_settings.json",
    "snapshots": DATA_DIR / "portfolio" / "portafoglio_snapshots.json",
    "storico_prezzi_json": PRICES_DIR / "portafoglio_storico_prezzi.json",
    "storico_prezzi_gz": PRICES_DIR / "portafoglio_storico_prezzi.json.gz",
    "storico_prezzi_parquet": PRICES_DIR / "portafoglio_storico_prezzi.parquet",
}

DEFAULT_SETTINGS: dict[str, Any] = {
    "target_profile": "Neutro",
    "benchmark": "Blend automatico",
    "lookback_days": 365,
    "include_proventi": True,
}
