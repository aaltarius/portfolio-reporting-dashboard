"""
core/palettes.py — Color palettes for appearance customization.
Each palette is a complete ThemeConfig-compatible dict.
"""

PALETTE_DEFAULT = {
    "name": "Default",
    "bg_app": "#ffffff",
    "bg_surface": "#f8fafc",
    "bg_surface_alt": "#f1f5f9",
    "bg_chart": "#ffffff",
    "font_color": "#1b1b1f",
    "border_color": "#d9d9de",
    "shadow_color": "0 1px 3px rgba(0,0,0,0.08)",
    "color_green": "#1f9d55",
    "color_red": "#d64545",
    "color_blue": "#2f6fdb",
    "color_purple": "#7c4dff",
    "color_yellow": "#caa017",
    "color_orange": "#e08a1e",
    "color_gray": "#8a8a93",
    "muted_color": "#757580",
    "grid_color": "#e5e7eb",
}

PALETTE_COOL_BLUE = {
    "name": "Cool Blue",
    "bg_app": "#f0f4f8",
    "bg_surface": "#e8ecf1",
    "bg_surface_alt": "#dfe5ed",
    "bg_chart": "#f0f4f8",
    "font_color": "#1a2332",
    "border_color": "#b0bfd1",
    "shadow_color": "0 2px 4px rgba(26,35,50,0.12)",
    "color_green": "#0ea5a8",
    "color_red": "#dc2626",
    "color_blue": "#0284c7",
    "color_purple": "#7c3aed",
    "color_yellow": "#d97706",
    "color_orange": "#ea580c",
    "color_gray": "#64748b",
    "muted_color": "#475569",
    "grid_color": "#cbd5e1",
}

PALETTE_WARM_SUNSET = {
    "name": "Warm Sunset",
    "bg_app": "#fef5f1",
    "bg_surface": "#fde9df",
    "bg_surface_alt": "#fcddd2",
    "bg_chart": "#fef5f1",
    "font_color": "#3a2c25",
    "border_color": "#ddb892",
    "shadow_color": "0 2px 4px rgba(58,44,37,0.12)",
    "color_green": "#b45309",
    "color_red": "#dc2626",
    "color_blue": "#ca8a04",
    "color_purple": "#c084fc",
    "color_yellow": "#eab308",
    "color_orange": "#f97316",
    "color_gray": "#a16207",
    "muted_color": "#92400e",
    "grid_color": "#fde2d1",
}

PALETTE_DARK_NEUTRAL = {
    "name": "Dark Neutral",
    "bg_app": "#1a1a1a",
    "bg_surface": "#2d2d2d",
    "bg_surface_alt": "#3a3a3a",
    "bg_chart": "#1a1a1a",
    "font_color": "#f5f5f5",
    "border_color": "#4a4a4a",
    "shadow_color": "0 2px 8px rgba(0,0,0,0.4)",
    "color_green": "#34d399",
    "color_red": "#f87171",
    "color_blue": "#60a5fa",
    "color_purple": "#c084fc",
    "color_yellow": "#fbbf24",
    "color_orange": "#fb923c",
    "color_gray": "#9ca3af",
    "muted_color": "#6b7280",
    "grid_color": "#404040",
}

PALETTE_VIVID_ENERGY = {
    "name": "Vivid Energy",
    "bg_app": "#fffbf0",
    "bg_surface": "#fff3e0",
    "bg_surface_alt": "#ffe0b2",
    "bg_chart": "#fffbf0",
    "font_color": "#1a1a1a",
    "border_color": "#ffb74d",
    "shadow_color": "0 2px 6px rgba(255,107,53,0.2)",
    "color_green": "#22c55e",
    "color_red": "#ef4444",
    "color_blue": "#3b82f6",
    "color_purple": "#a855f7",
    "color_yellow": "#fbbf24",
    "color_orange": "#ff6b35",
    "color_gray": "#6b7280",
    "muted_color": "#9ca3af",
    "grid_color": "#fed7aa",
}

PALETTES = {
    "Default": PALETTE_DEFAULT,
    "Cool Blue": PALETTE_COOL_BLUE,
    "Warm Sunset": PALETTE_WARM_SUNSET,
    "Dark Neutral": PALETTE_DARK_NEUTRAL,
    "Vivid Energy": PALETTE_VIVID_ENERGY,
}

def get_palette(name: str) -> dict:
    """Return palette dict for given name, fallback to Default."""
    return PALETTES.get(name, PALETTE_DEFAULT)
