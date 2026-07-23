"""ui/form_server/theme.py — Palette colori del design-system form-server.

Design-system deliberatamente separato da ui.theme/core.config.COLORS
(palette finanziaria dell'app principale): il form-server usa una
palette Tailwind CSS standard (indaco/slate), senza sovrapposizioni
visive con il resto dell'app. Questo modulo è la sola fonte di verità
per quei colori — non duplicarli come stringhe hex altrove in
ui/form_server/*.py.
"""
from __future__ import annotations

FORM_COLORS: dict[str, str] = {
    "white": "#fff",
    "indigo-50": "#eef2ff",
    "indigo-500": "#6366f1",
    "indigo-600": "#4f46e5",
    "indigo-700": "#4338ca",
    "indigo-500-a12": "rgba(99,102,241,.12)",
    "slate-50": "#f8fafc",
    "slate-100": "#f1f5f9",
    "slate-200": "#e2e8f0",
    "slate-300": "#cbd5e1",
    "slate-400": "#94a3b8",
    "slate-500": "#64748b",
    "slate-700": "#334155",
    "slate-800": "#1e293b",
    "black-a07": "rgba(0,0,0,.07)",
    "red-50": "#fef2f2",
    "red-300": "#fca5a5",
    "red-500": "#ef4444",
    "red-600": "#dc2626",
    "red-700": "#b91c1c",
    "amber-50": "#fffbeb",
    "amber-300": "#fcd34d",
    "amber-800": "#92400e",
    "emerald-600": "#059669",
    "emerald-700": "#047857",
    "green-50": "#f0fdf4",
    "green-300": "#86efac",
    "green-800": "#166534",
    "sky-50": "#f0f9ff",
    "sky-200": "#bae6fd",
}
