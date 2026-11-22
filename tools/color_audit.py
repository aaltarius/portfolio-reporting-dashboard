"""tools/color_audit.py — nessun colore esadecimale nuovo fuori dai registri (TD-06).

I colori dell'app seguono la palette e l'accento scelti in Setup (ui/theme_tokens.py): nel codice si
usa `theme_color("slate-500")` (Python), `var(--slate-500)` (HTML/CSS) oppure i nomi semantici
success/danger/warning/info. Questo controllo e' un "cricchetto": conta i colori scritti a mano per
file e fallisce se il numero SALE rispetto a tools/color_audit_baseline.json. Quando se ne tolgono,
rilanciare con --update per abbassare la soglia.

Uso:  PYTHONPATH=. python tools/color_audit.py [--update]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = Path(__file__).with_name("color_audit_baseline.json")
HEX = re.compile(r"(?<![&\w])#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
# Registri dei colori: qui gli esadecimali sono la fonte di verita'.
REGISTRY = {
    "core/palettes.py", "core/config.py", "core/constants.py", "core/asset_categories.py",
    "ui/theme.py", "ui/styles.py", "ui/charts/settings.py", "ui/form_server/theme.py", "ui/theme_tokens.py",
    "ui/charts/natura_icons.py",  # tinte per natura di strumento: palette categorica, non di tema
}


def count() -> dict[str, int]:
    out: dict[str, int] = {}
    for area in ("ui", "core"):
        for f in sorted((ROOT / area).rglob("*.py")):
            rel = f.relative_to(ROOT).as_posix()
            if rel in REGISTRY:
                continue
            n = len(HEX.findall(f.read_text(encoding="utf-8", errors="replace")))
            if n:
                out[rel] = n
    return out


def main() -> int:
    now = count()
    if "--update" in sys.argv:
        BASELINE.write_text(json.dumps(now, indent=1, sort_keys=True), encoding="utf-8")
        print(f"soglia aggiornata: {sum(now.values())} colori in {len(now)} file")
        return 0
    base = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    worse = {f: (base.get(f, 0), n) for f, n in now.items() if n > base.get(f, 0)}
    for f, (b, n) in sorted(worse.items()):
        print(f"AUMENTATI i colori scritti a mano in {f}: {b} -> {n}")
    print(f"colori scritti a mano: {sum(now.values())} in {len(now)} file (soglia {sum(base.values())})")
    return 1 if worse else 0


if __name__ == "__main__":
    sys.exit(main())
