"""
core/data_models.py — Classi Pydantic per type safety.
Modelli di dati per Portfolio, State, Theme, etc.
"""
from datetime import date, datetime
from typing import Optional, Dict, List, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.config import COLORS


class ThemeConfig(BaseModel):
    """Configurazione tema (colori, stile)."""
    primary_color: str = COLORS["info"]
    bg_app: str = COLORS["bg_app"]
    bg_surface: str = COLORS["bg_surface"]
    bg_surface_alt: str = COLORS.get("bg_surface_alt", "#f1f5f9")
    bg_chart: str = COLORS["bg_chart"]
    font_color: str = COLORS["font"]
    muted_color: str = "rgba(34,49,68,0.60)"
    border_color: str = "rgba(34,49,68,0.12)"
    grid_color: str = "rgba(34,49,68,0.10)"
    shadow_color: str = "0 14px 32px rgba(31,45,61,0.08)"
    color_green: str = COLORS["success"]
    color_red: str = COLORS["danger"]
    color_orange: str = COLORS["warning"]
    color_yellow: str = COLORS["yellow"]
    color_purple: str = COLORS["purple"]
    color_gray: str = COLORS["gray"]
    color_blue: str = COLORS["info"]
    colors: Dict[str, str] = Field(default_factory=lambda: dict(COLORS))


