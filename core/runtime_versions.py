"""Versioni delle librerie effettivamente installate, per il pulsante "Versioni" della sidebar.

L'elenco dei pacchetti NON e' duplicato a mano: si legge da `requirements.txt`
(una sola fonte), cosi' una libreria aggiunta li' compare da sola. La versione
mostrata e' quella realmente caricata nell'ambiente (`importlib.metadata`), non
quella scritta nel file: se le due divergono, l'utente lo vede.
"""
from __future__ import annotations

import os
import platform
import re
from functools import lru_cache
from importlib import metadata

_REQUIREMENTS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "requirements.txt")
_NAME_RE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)")


def _requirement_names(path: str) -> list[str]:
    """Nomi dei pacchetti in requirements.txt, nell'ordine del file, senza extras/specificatori."""
    names: list[str] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.split("#", 1)[0].strip()
                if not line or line.startswith("-"):
                    continue
                m = _NAME_RE.match(line)
                if m and m.group(1) not in names:
                    names.append(m.group(1))
    except OSError:
        return []
    return names


def _installed_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "non installata"
    except Exception:
        return "n/d"


@lru_cache(maxsize=1)
def get_runtime_versions() -> tuple[tuple[str, str], ...]:
    """((etichetta, versione), ...): Python, poi le librerie di requirements.txt.

    Calcolato una volta per processo: le versioni installate non cambiano mentre
    l'app e' in esecuzione, quindi nessun costo ai rerun."""
    rows: list[tuple[str, str]] = [("Python", platform.python_version())]
    rows.extend((name, _installed_version(name)) for name in _requirement_names(_REQUIREMENTS_FILE))
    return tuple(rows)
