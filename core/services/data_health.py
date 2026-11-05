"""core/services/data_health.py — Sintesi «cosa fare ora» per la pagina Dati.

Funzione pura: non legge file né rete. Riusa gli esiti già calcolati dei controlli
di integrità e della tabella qualità strumenti, più età di quotazioni e backup,
e li traduce in poche azioni ordinate per importanza, in linguaggio non tecnico.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

# azione del dataset qualità -> (titolo, cosa fare, dove)
_QUALITY_HINTS: dict[str, tuple[str, str, str]] = {
    "Prezzo non aggiornato": ("Prezzo non aggiornato", "l'ultimo prezzo è vecchio di oltre due settimane", "Quotazioni → Aggiorna quotazioni"),
    "Carica prezzi": ("Nessun prezzo", "lo strumento non ha ancora alcun prezzo", "Quotazioni → Aggiorna quotazioni"),
    "Buchi storico": ("Buchi nello storico", "mancano molte date di prezzo", "Dati → Ripara buchi nello storico"),
    "Prezzo fermo": ("Prezzo fermo", "il prezzo non cambia da molti giorni: controlla la fonte", "Quotazioni"),
    "Completa arricchimento": ("Anagrafica da completare", "mancano i dati ufficiali dello strumento", "Portafoglio → scheda strumento"),
    "Verifica errore": ("Arricchimento fallito", "l'ultimo arricchimento automatico è andato in errore", "Portafoglio → scheda strumento"),
}
_SEV_ORDER = {"Errore": 0, "Warning": 1, "Info": 2}
MAX_ITEMS = 8


def _names(tickers: list[str], limit: int = 4) -> str:
    shown = ", ".join(tickers[:limit])
    return shown + (f" e altri {len(tickers) - limit}" if len(tickers) > limit else "")


def build_data_health(
    integrity_checks: list[dict[str, Any]] | None,
    quality: pd.DataFrame | None,
    *,
    quote_age_days: int | None,
    backup_age_days: int | None,
) -> dict[str, Any]:
    """Ritorna ``{"level": "ok"|"attenzione"|"problema", "headline": str, "items": [...]}``.

    Ogni item: ``{"severity", "title", "detail", "where"}``. Le segnalazioni
    puramente informative (severità Info) non diventano azioni."""
    items: list[dict[str, str]] = []

    for check in integrity_checks or []:
        sev = str(check.get("Severita", ""))
        if sev in {"Errore", "Warning"}:
            items.append({
                "severity": sev,
                "title": str(check.get("Elemento", "")),
                "detail": str(check.get("Dettaglio", "")),
                "where": "Dati → Controlli di integrità",
            })

    if isinstance(quality, pd.DataFrame) and not quality.empty and "action_required" in quality.columns:
        lifecycle = quality["lifecycle"] if "lifecycle" in quality.columns else pd.Series("in_portafoglio", index=quality.index)
        for action, (title, hint, where) in _QUALITY_HINTS.items():
            mask = quality["action_required"] == action
            owned = quality[mask & (lifecycle == "in_portafoglio")]["ticker"].astype(str).tolist()
            watched = quality[mask & (lifecycle == "osservato")]["ticker"].astype(str).tolist()
            if owned:
                items.append({"severity": "Warning", "title": f"{title} ({len(owned)})", "detail": f"{_names(owned)}: {hint}.", "where": where})
            if watched:
                items.append({"severity": "Info", "title": f"{title} su strumenti osservati ({len(watched)})", "detail": f"{_names(watched)}: {hint}. Non incide sul portafoglio.", "where": where})

    if quote_age_days is not None and quote_age_days > 4:
        items.append({"severity": "Warning", "title": f"Quotazioni ferme da {quote_age_days} giorni", "detail": "i valori del portafoglio usano prezzi vecchi.", "where": "Sidebar → Aggiorna quotazioni"})
    if backup_age_days is None:
        items.append({"severity": "Warning", "title": "Nessun backup", "detail": "non esiste ancora una copia di sicurezza dei dati.", "where": "Dati → Backup e ripristino"})
    elif backup_age_days > 14:
        items.append({"severity": "Info", "title": f"Ultimo backup di {backup_age_days} giorni fa", "detail": "conviene crearne uno prima di nuove modifiche importanti.", "where": "Dati → Backup e ripristino"})

    items.sort(key=lambda it: _SEV_ORDER.get(it["severity"], 3))
    actionable = [it for it in items if it["severity"] in {"Errore", "Warning"}]
    n = len(actionable)
    if any(it["severity"] == "Errore" for it in items):
        level, headline = "problema", ("1 cosa da correggere." if n == 1 else f"{n} cose da correggere: parti dall'alto.")
    elif actionable:
        level, headline = "attenzione", ("1 cosa da controllare, nessun errore bloccante." if n == 1 else f"{n} cose da controllare, nessun errore bloccante.")
    else:
        level, headline = "ok", "Dati in ordine: nessuna azione necessaria."
    return {"level": level, "headline": headline, "items": items[:MAX_ITEMS], "total": len(items)}
