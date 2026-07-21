"""
core/formatting.py — Formattatori puri condivisi tra core e UI.
Nessuna dipendenza da streamlit.
"""

from datetime import datetime

import numpy as np


def fmt_dt_it(value):
    if not value:
        return "n/d"
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                value = datetime.strptime(value[:19], fmt)
                break
            except Exception:
                continue
    if hasattr(value, "day"):
        return f"{value.day:02d}/{value.month:02d}/{value.year} {getattr(value, 'hour', 0):02d}:{getattr(value, 'minute', 0):02d}"
    return str(value)


def fmt_date_only_it(value):
    """Formato data senza orario (gg/mm/aaaa)."""
    if not value:
        return "n/d"
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                value = datetime.strptime(value[:19], fmt)
                break
            except Exception:
                continue
    if hasattr(value, "day"):
        return f"{value.day:02d}/{value.month:02d}/{value.year}"
    return str(value)


def fmt_num_it(value, decimals=2, signed=False):
    try:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return "—"
        v = float(value)
    except Exception:
        return "—"
    sign = ""
    if signed:
        sign = "+" if v > 0 else ("-" if v < 0 else "")
    elif v < 0:
        sign = "-"
    av = abs(v)
    s = f"{av:,.{decimals}f}".replace(",", "§").replace(".", ",").replace("§", ".")
    return f"{sign}{s}"


def fmt_eur_it(value, decimals=2, signed=False):
    s = fmt_num_it(value, decimals=decimals, signed=signed)
    return s if s == "—" else f"€ {s}"


def fmt_pct_it(value, decimals=2, signed=False):
    try:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return "—"
        v = float(value) * 100
    except Exception:
        return "—"
    return f"{fmt_num_it(v, decimals=decimals, signed=signed)}%"


def fmt_qty_it(value, decimals=4):
    return fmt_num_it(value, decimals=decimals, signed=False)


def hex_to_rgba(value, alpha):
    try:
        if not value:
            return f"rgba(128,128,128,{alpha})"
        c = str(value).strip()
        if c.startswith("#"):
            h = c[1:]
            if len(h) == 3:
                h = "".join(ch * 2 for ch in h)
            if len(h) == 6:
                r = int(h[0:2], 16)
                g = int(h[2:4], 16)
                b = int(h[4:6], 16)
                return f"rgba({r},{g},{b},{alpha})"
        if c.startswith("rgb("):
            return c.replace("rgb(", "rgba(").rstrip(")") + f",{alpha})"
        if c.startswith("rgba("):
            parts = c[5:-1].split(",")
            if len(parts) >= 3:
                return f"rgba({parts[0].strip()},{parts[1].strip()},{parts[2].strip()},{alpha})"
    except Exception:
        pass
    return f"rgba(128,128,128,{alpha})"


MESI = {1: "gen", 2: "feb", 3: "mar", 4: "apr", 5: "mag", 6: "giu", 7: "lug", 8: "ago", 9: "set", 10: "ott", 11: "nov", 12: "dic"}


def fmtd(d):
    """Formatta data come '5 apr 2026' (giorno mese-abbreviato anno)."""
    if isinstance(d, str):
        try:
            d = datetime.strptime(d[:10], "%Y-%m-%d")
        except Exception:
            return str(d)
    if hasattr(d, "day"):
        return f"{d.day} {MESI.get(d.month, '?')} {d.year}"
    return str(d)


def fmtds(d):
    """Formatta data come 'GG/MM/AAAA'."""
    if isinstance(d, str):
        try:
            d = datetime.strptime(d[:10], "%Y-%m-%d")
        except Exception:
            return str(d)
    if hasattr(d, "day"):
        return f"{d.day:02d}/{d.month:02d}/{d.year}"
    return str(d)
