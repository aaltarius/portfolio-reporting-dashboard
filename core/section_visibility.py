"""Visibilita' delle sezioni di pagina: registro, preset e override utente.

Funzioni pure. `ui.components.should_render_section` delega qui; la pagina
Impostazioni usa `PAGE_SECTIONS` per elencare gli interruttori e
`build_custom_visibility` per salvarli in `appearance.custom_visibility`
(solo le differenze rispetto al preset attivo).

Una sezione compare in `PAGE_SECTIONS` solo se il codice della pagina la
nasconde davvero chiamando `should_render_section`: aggiungere qui una
sezione senza avvolgerla nella pagina darebbe un interruttore che non fa nulla.
"""
from __future__ import annotations

from typing import Any

#: Sezioni nascondibili per pagina, nell'ordine in cui compaiono nella pagina.
PAGE_SECTIONS: dict[str, list[str]] = {
    "Portafoglio": [
        "Andamento ultima giornata",
        "Sintesi allocazione",
        "Controvalore del Portafoglio",
        "Andamento dell'ultima settimana",
        "Proventi per strumento",
        "P/L per Categoria",
        "Analisi per Macro-Categoria",
        "Posizioni Chiuse",
    ],
}

VISIBILITY_PRESETS = ("Essenziale", "Standard", "Completo")

#: Sezioni mostrate dal preset "Essenziale"; Standard e Completo mostrano tutto.
_ESSENZIALE_SECTIONS: dict[str, list[str]] = {
    "Portafoglio": ["Andamento ultima giornata", "Sintesi allocazione", "Controvalore del Portafoglio"],
    "Quotazioni": ["Storico Prezzi", "Diagnostica"],
    "Operazioni": ["Centro Operativo", "Registro operazioni"],
    "Cruscotti": ["Dashboard principale"],
    "Summary": ["Identità report", "Genera report"],
    "Confronto": ["Confronto"],
    "Pianificazione": ["Scenari futuri"],
    "Gestione Dati": ["Sistema e Backup"],
}


def preset_default_visible(page: str, section: str, mode: str) -> bool:
    if mode == "Essenziale":
        return section in _ESSENZIALE_SECTIONS.get(page, [])
    return True


def _appearance(settings: dict[str, Any] | None) -> dict[str, Any]:
    appearance = (settings or {}).get("appearance", {})
    return appearance if isinstance(appearance, dict) else {}


def is_section_visible(page: str, section: str, settings: dict[str, Any] | None) -> bool:
    appearance = _appearance(settings)
    page_visibility = (appearance.get("custom_visibility") or {}).get(page, {})
    if isinstance(page_visibility, dict) and section in page_visibility:
        return bool(page_visibility[section])
    return preset_default_visible(page, section, str(appearance.get("visibility_mode", "Standard")))


def build_custom_visibility(
    wanted: dict[tuple[str, str], bool],
    mode: str,
    existing: dict[str, Any] | None,
) -> dict[str, dict[str, bool]]:
    """Nuovo `custom_visibility`: per ogni (pagina, sezione) in `wanted` salva
    il valore solo se diverso dal preset `mode`, altrimenti rimuove l'override.
    Le voci non presenti in `wanted` restano com'erano."""
    out: dict[str, dict[str, bool]] = {
        page: dict(sections) for page, sections in (existing or {}).items() if isinstance(sections, dict)
    }
    for (page, section), value in wanted.items():
        page_map = out.setdefault(page, {})
        if bool(value) == preset_default_visible(page, section, mode):
            page_map.pop(section, None)
        else:
            page_map[section] = bool(value)
    return {page: sections for page, sections in out.items() if sections}
