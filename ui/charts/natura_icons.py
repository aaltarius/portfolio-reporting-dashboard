"""Libreria icone/colori per l'etichetta di natura/esposizione di uno
strumento (vedi core/instrument_classification.py per la classificazione).
Nessuna logica di classificazione qui: solo aspetto visivo."""
from __future__ import annotations


def _lucide_svg(paths: list[str]) -> str:
    body = "".join(f'<path d="{path}" />' for path in paths)
    return (
        '<svg viewBox="0 0 24 24" aria-hidden="true" '
        'fill="none" stroke="currentColor" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        f"{body}</svg>"
    )


_FONDO_GESTITO = (
    "#0F766E",
    _lucide_svg([
        "M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z",
        "M2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 12",
        "M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 17",
    ]),
)
_QUALITY = (
    "#0EA5A4",
    _lucide_svg([
        "M10.5 3 8 9l4 13 4-13-2.5-6",
        "M17 3a2 2 0 0 1 1.6.8l3 4a2 2 0 0 1 .013 2.382l-7.99 10.986a2 2 0 0 1-3.247 0l-7.99-10.986A2 2 0 0 1 2.4 7.8l2.998-3.997A2 2 0 0 1 7 3z",
        "M2 9h20",
    ]),
)
_DIFESA = (
    "#1D4ED8",
    _lucide_svg([
        "M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z",
    ]),
)
_BENE_RIFUGIO = (
    "#C28A12",
    _lucide_svg([
        "M10.5 3 8 9l4 13 4-13-2.5-6",
        "M17 3a2 2 0 0 1 1.6.8l3 4a2 2 0 0 1 .013 2.382l-7.99 10.986a2 2 0 0 1-3.247 0l-7.99-10.986A2 2 0 0 1 2.4 7.8l2.998-3.997A2 2 0 0 1 7 3z",
        "M2 9h20",
    ]),
)
_METALLI = (
    "#B45309",
    _lucide_svg([
        "m14 13-8.381 8.38a1 1 0 0 1-3.001-3L11 9.999",
        "M15.973 4.027A13 13 0 0 0 5.902 2.373c-1.398.342-1.092 2.158.277 2.601a19.9 19.9 0 0 1 5.822 3.024",
        "M16.001 11.999a19.9 19.9 0 0 1 3.024 5.824c.444 1.369 2.26 1.676 2.603.278A13 13 0 0 0 20 8.069",
        "M18.352 3.352a1.205 1.205 0 0 0-1.704 0l-5.296 5.296a1.205 1.205 0 0 0 0 1.704l2.296 2.296a1.205 1.205 0 0 0 1.704 0l5.296-5.296a1.205 1.205 0 0 0 0-1.704z",
    ]),
)
_COMMODITIES = (
    "#F97316",
    _lucide_svg([
        "M7 5.5h10l2 3.5-2 3.5H7L5 9l2-3.5",
        "M7 12.5h10l2 3.5-2 3.5H7l-2-3.5 2-3.5",
    ]),
)
_EMERGENTI = (
    "#14B8A6",
    _lucide_svg([
        "M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20",
        "M2 12h20",
        "M14.5 9h5v5",
        "M19.5 9l-5.6 5.6",
        "M12 2a10 10 0 0 0 0 20",
    ]),
)
_IMMOBILIARE = (
    "#A16207",
    _lucide_svg([
        "M10 12h4",
        "M10 8h4",
        "M14 21v-3a2 2 0 0 0-4 0v3",
        "M6 10H4a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-2",
        "M6 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16",
    ]),
)
_LIQUIDITA = (
    "#64748B",
    _lucide_svg([
        "M17 14h.01",
        "M7 7h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14",
    ]),
)
_OBBLIGAZIONARIO = (
    "#4F46E5",
    _lucide_svg([
        "M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z",
        "M14 2v5a1 1 0 0 0 1 1h5",
        "M10 9H8",
        "M16 13H8",
        "M16 17H8",
    ]),
)
_AZIONARIO_PAESE_SINGOLO = (
    "#16A34A",
    _lucide_svg([
        "M4 22V4a1 1 0 0 1 .4-.8A6 6 0 0 1 8 2c3 0 5 2 7.333 2q2 0 3.067-.8A1 1 0 0 1 20 4v10a1 1 0 0 1-.4.8A6 6 0 0 1 16 16c-3 0-5-2-8-2a6 6 0 0 0-4 1.528",
    ]),
)
_ENERGIA = (
    "#EA580C",
    _lucide_svg([
        "M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z",
    ]),
)
_SALUTE = (
    "#DC2626",
    _lucide_svg([
        "M2 9.5a5.5 5.5 0 0 1 9.591-3.676.56.56 0 0 0 .818 0A5.49 5.49 0 0 1 22 9.5c0 2.29-1.5 4-3 5.5l-5.492 5.313a2 2 0 0 1-3 .019L5 15c-1.5-1.5-3-3.2-3-5.5",
    ]),
)
_INNOVAZIONE = (
    "#6D28D9",
    _lucide_svg([
        "M12 20v2", "M12 2v2", "M17 20v2", "M17 2v2", "M2 12h2", "M2 17h2", "M2 7h2",
        "M20 12h2", "M20 17h2", "M20 7h2", "M7 20v2", "M7 2v2",
        "M4 4h16v16H4z", "M8 8h8v8H8z",
    ]),
)
_GLOBALE_CORE = (
    "#2563EB",
    _lucide_svg([
        "M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20",
        "M2 12h20",
        "M12 2a14.5 14.5 0 0 1 0 20",
    ]),
)
_CRIPTOVALUTE = (
    "#B45309",
    _lucide_svg([
        "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z",
        "M9 8h4a2 2 0 0 1 0 4H9m0 0h5a2 2 0 0 1 0 4H9m2-8v8m0-10v2m0 8v2",
    ]),
)
_DIVERSIFICATA = (
    "#64748B",
    _lucide_svg(["M7 16v-4.5", "M12 16V8.5", "M17 16v-3", "M6 18h12"]),
)

_STATIC_VISUALS: dict[str, tuple[str, str]] = {
    "Fondo gestito / multi-asset": _FONDO_GESTITO,
    "Fondo bilanciato": _FONDO_GESTITO,
    "Fattore qualità": _QUALITY,
    "Difesa / sicurezza": _DIFESA,
    "Bene rifugio": _BENE_RIFUGIO,
    "Metalli e miniere": _METALLI,
    "Materie prime": _COMMODITIES,
    "Mercati emergenti": _EMERGENTI,
    "Immobiliare": _IMMOBILIARE,
    "Liquidità": _LIQUIDITA,
    "Obbligazionario / reddito": _OBBLIGAZIONARIO,
    "Energia": _ENERGIA,
    "Salute": _SALUTE,
    "Innovazione": _INNOVAZIONE,
    "Azionario globale core": _GLOBALE_CORE,
    "Criptovalute": _CRIPTOVALUTE,
    "Esposizione diversificata": _DIVERSIFICATA,
}


def get_natura_visual(label: str) -> tuple[str, str]:
    """Ritorna (colore_hex, markup_svg) per un'etichetta di natura. Le
    etichette 'Azionario {paese}' diverse da 'Azionario globale core' usano
    un'icona generica paese-singolo; etichette sconosciute usano il fallback
    diversificata."""
    if label in _STATIC_VISUALS:
        return _STATIC_VISUALS[label]
    if label.startswith("Azionario ") and label != "Azionario globale core":
        return _AZIONARIO_PAESE_SINGOLO
    return _DIVERSIFICATA
