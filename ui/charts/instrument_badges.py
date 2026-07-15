"""Badge HTML per indicatori sintetici accanto al ticker nelle tabelle HTML
custom (Quotazioni, Portafoglio). Nessuna logica di dominio qui: solo aspetto
visivo, stesso principio di ui/charts/natura_icons.py."""
from __future__ import annotations

from typing import Any


def is_zero_commissioni(raw_value: Any) -> bool:
    """Normalizza il campo strumento `zero_commissioni` (salvato come stringa
    dal form in ui/form_server/strumenti.py) con la stessa regola già usata in
    core/services/sator.py, per non avere due letture diverse dello stesso dato.

    Accetta anche un bool già risolto (es. `zero_commission` calcolato dalla
    pipeline SATOR), così i chiamanti non devono sapere quale delle due forme
    hanno in mano.
    """
    if isinstance(raw_value, bool):
        return raw_value
    return str(raw_value or "").strip().lower() in ("true", "si", "sì", "1", "yes")


def commission_badge(zero_commissioni_raw: Any) -> str:
    """Badge "€" da affiancare al ticker per strumenti non a zero commissioni.

    Stesso stile (colori, dimensione) del badge già in uso in SATOR
    (ui/form_server/sator.py, classi .sc-badge.sc-m), qui inline perché le
    tabelle di Quotazioni/Portafoglio vivono in iframe HTML separati senza
    quel foglio di stile.
    """
    if is_zero_commissioni(zero_commissioni_raw):
        return ""
    return (
        "<span title=\"Non a zero commissioni: l'acquisto comporta un costo di negoziazione\" "
        "style=\"display:inline-block;font-size:.7rem;font-weight:800;border-radius:4px;"
        "padding:1px 4px;margin-left:3px;line-height:1.2;background:#fef9c3;color:#854d0e;\">€</span>"
    )
