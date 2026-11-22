"""ui/theme_tokens.py — i colori dell'intera app seguono il tema scelto in Setup (palette e accento).

`FORM_COLORS` (ui/form_server/theme.py) resta il registro dei nomi e dei valori di base; qui i valori
vengono ricalcolati dalla palette («Aspetto → palette») e dal colore accento scelti in Setup, a ogni
richiesta, senza riavviare nulla. Con la palette «Default» e l'accento «Default» l'aspetto resta quello di
sempre, salvo l'accento che passa dall'indaco al blu dell'app.

Un solo punto di verità: `resolve_form_colors()` per chi ha bisogno dei valori (grafici),
`theme_style_block()` per le pagine (variabili CSS che sovrascrivono quelle di base).
"""
from __future__ import annotations

import re

from ui.form_server.theme import FORM_COLORS  # registro dei nomi e dei valori di base

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _rgb(color: str) -> tuple[int, int, int] | None:
    c = (color or "").strip()
    if not _HEX.match(c):
        return None
    c = c[1:]
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v))) for v in rgb)


def mix(a: str, b: str, t: float) -> str:
    """Colore a `t` di strada fra `a` (t=0) e `b` (t=1). Se uno dei due non è esadecimale, torna `a`."""
    ra, rb = _rgb(a), _rgb(b)
    if ra is None or rb is None:
        return a
    return _hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def is_dark(color: str) -> bool:
    rgb = _rgb(color)
    if rgb is None:
        return False
    r, g, b = rgb
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) < 110


def rgba(color: str, alpha: float) -> str:
    rgb = _rgb(color)
    if rgb is None:
        return color
    return "rgba(%d,%d,%d,%s)" % (*rgb, ("%.2f" % alpha).rstrip("0").rstrip("."))


def _load_setup() -> tuple[dict, str]:
    """Palette e accento scelti in Setup; se le impostazioni non si leggono, i valori predefiniti."""
    from core.palettes import get_palette
    from ui.theme import ACCENT_VARIANTS

    settings: dict = {}
    try:
        from persistence.storage import load_settings

        settings = load_settings() or {}
    except Exception:
        settings = {}
    palette = get_palette(str((settings.get("appearance") or {}).get("color_palette", "Default")))
    from core.settings_profiles import get_ui_preferences

    variant = str(get_ui_preferences(settings).get("accent_variant", "Default") or "Default")
    accent = ACCENT_VARIANTS.get(variant, ACCENT_VARIANTS["Default"])
    return palette, accent


def resolve_form_colors(palette: dict | None = None, accent: str | None = None) -> dict[str, str]:
    """I colori del form-server per la palette e l'accento di Setup (o per quelli passati)."""
    if palette is None or accent is None:
        palette, accent = _load_setup()
    bg, surf, alt = palette["bg_app"], palette["bg_surface"], palette["bg_surface_alt"]
    fg, muted = palette["font_color"], palette["muted_color"]
    border, grid = palette["border_color"], palette["grid_color"]
    dark = is_dark(bg)
    deep = "#ffffff" if dark else "#000000"      # verso dove si "scurisce" un colore del testo

    def tint(c: str, t: float) -> str:           # sfondo tenue dello stesso colore
        return mix(bg, c, t)

    def shade(c: str, t: float) -> str:          # variante più marcata (hover, testo)
        return mix(c, deep, t)

    c = dict(FORM_COLORS)
    c.update({
        "white": bg, "page-bg": alt, "slate-50": surf, "slate-100": alt, "slate-hover": mix(surf, bg, .5),
        "slate-200": grid, "slate-300": border, "slate-400": mix(muted, bg, .35), "slate-500": muted,
        "slate-600": mix(muted, fg, .5), "slate-700": mix(fg, muted, .25), "slate-800": fg, "slate-900": fg,
        "black-a06": "rgba(0,0,0,.06)" if not dark else "rgba(0,0,0,.35)",
        "black-a07": "rgba(0,0,0,.07)" if not dark else "rgba(0,0,0,.40)",
        "indigo-500": accent, "indigo-600": shade(accent, .15), "indigo-700": shade(accent, .32),
        "indigo-50": tint(accent, .10), "indigo-200": tint(accent, .38), "indigo-500-a12": rgba(accent, .12),
    })
    for name, base, steps in (
        ("green", palette["color_green"], {"50": .08, "100": .14, "200": .26, "300": .4}),
        ("red", palette["color_red"], {"50": .08, "100": .13, "200": .24, "300": .4}),
        ("amber", palette["color_orange"], {"50": .08, "100": .14, "200": .26, "300": .4}),
        ("orange", palette["color_orange"], {"50": .08}),
        ("yellow", palette["color_yellow"], {"50": .08, "100": .15}),
        ("blue", palette["color_blue"], {"50": .08, "100": .14, "200": .26}),
        ("violet", palette["color_purple"], {"100": .14}),
    ):
        for k, t in steps.items():
            c[f"{name}-{k}"] = tint(base, t)
    g, r, o, y, b, p = (palette[k] for k in ("color_green", "color_red", "color_orange", "color_yellow", "color_blue", "color_purple"))
    c.update({
        "green-500": g, "green-600": shade(g, .12), "green-700": shade(g, .25), "green-800": shade(g, .45),
        "emerald-500": g, "emerald-600": shade(g, .12), "emerald-700": shade(g, .25),
        "red-500": r, "red-600": shade(r, .1), "red-700": shade(r, .25), "red-800": shade(r, .4),
        "amber-500": o, "amber-700": shade(o, .3), "amber-800": shade(o, .45),
        "orange-500": o, "orange-700": shade(o, .3),
        "yellow-800": shade(y, .45),
        "blue-500": b, "blue-700": shade(b, .3),
        "sky-50": tint(b, .08), "sky-200": tint(b, .28),
        "violet-600": p,
        # nomi semantici dell'app (guadagno, perdita, avviso, accento): seguono la palette e l'accento di Setup
        "success": g, "danger": r, "warning": o, "info": accent,
    })
    return c


def theme_style_block(palette: dict | None = None, accent: str | None = None, *, full: bool = False) -> str:
    """Blocco <style> che ridefinisce le variabili CSS dopo quelle di base, e porta il colore di fondo."""
    colors = resolve_form_colors(palette, accent)
    changed = colors if full else {k: v for k, v in colors.items() if FORM_COLORS.get(k) != v}
    body = "".join(f"--{k}:{v};" for k, v in changed.items())
    return f'<style id="setup-theme">:root{{{body}color-scheme:{"dark" if is_dark(colors["white"]) else "light"}}}</style>'


# ─── Uso nel resto dell'app ──────────────────────────────────────────────────

import time as _time

_TTL_S = 1.0
_cache: dict = {"t": 0.0, "v": None}


def tokens() -> dict[str, str]:
    """Colori del tema di Setup, riletti al massimo una volta al secondo (le impostazioni cambiano di rado)."""
    now = _time.monotonic()
    if _cache["v"] is None or now - _cache["t"] > _TTL_S:
        _cache["v"], _cache["t"] = resolve_form_colors(), now
    return _cache["v"]


def theme_color(name: str) -> str:
    """Un colore del tema per nome (es. theme_color("slate-500")), per grafici e codice Python."""
    return tokens()[name]


def var(name: str) -> str:
    """Lo stesso colore come variabile CSS, per HTML e CSS (es. var("slate-500") -> "var(--slate-500)")."""
    return f"var(--{name})"


def inject_theme(html: str) -> str:
    """Aggiunge il blocco delle variabili del tema a una pagina HTML intera o a un frammento."""
    block = theme_style_block(full=True)
    if "</head>" in html:
        return html.replace("</head>", block + "</head>", 1)
    return block + html
