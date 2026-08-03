"""Badge HTML per indicatori sintetici accanto al ticker nelle tabelle HTML.

Centralizza micro-badge riusabili da Quotazioni, Portafoglio e tabelle derivate:
commissioni, emittente/logo sintetico e relativo CSS per iframe custom.
"""
from __future__ import annotations

import html
from typing import Any

ISSUER_BADGE_CSS = """
.issuer-badge{display:inline-flex;align-items:center;justify-content:center;min-width:17px;height:17px;margin-right:5px;border-radius:999px;font-size:9px;font-weight:900;line-height:1;vertical-align:-2px;border:1px solid rgba(15,23,42,.12);background:#f8fafc;color:#334155;}
.issuer-badge.issuer-it{font-size:14px;border:none;background:transparent;min-width:18px;margin-right:4px;}
.issuer-badge.issuer-amundi{background:#fff7ed;color:#b45309;}
.issuer-badge.issuer-fineco{background:#fffbe6;color:#8a6d00;}
.issuer-badge.issuer-ishares{background:#111827;color:#fff;}
.issuer-badge.issuer-xtrackers{background:#eff6ff;color:#1d4ed8;}
.issuer-badge.issuer-franklin{background:#ecfdf3;color:#047857;}
.issuer-badge.issuer-vanguard{background:#fef2f2;color:#b91c1c;}
"""


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


def issuer_badge(info: dict[str, Any] | None, ticker: str = "", tipo_code: str = "") -> str:
    """Logo sintetico dell'emittente da affiancare al ticker nelle tabelle HTML.

    Tiene qui la regola condivisa da Portafoglio, Quotazioni e tabelle derivate:
    il prefisso FAM- identifica i fondi Fineco AM anche quando l'anagrafica non
    contiene esplicitamente la parola "Fineco" nel nome dello strumento.
    """
    info = info or {}
    tk = str(ticker or info.get("ticker") or "").strip().upper()
    tipo = str(tipo_code or info.get("tipo") or "").strip()
    tipo_upper = tipo.upper()
    source = " ".join(
        str(value or "")
        for value in (
            tk,
            tipo,
            info.get("emittente"),
            info.get("fonte"),
            info.get("nome"),
            info.get("isin"),
        )
    ).lower()

    if tipo_upper == "GOV" or tk.startswith("BTP-") or "titolo di stato" in source:
        return '<span class="issuer-badge issuer-it" title="Italia">🇮🇹</span>'
    if tk.startswith("FAM-") or tk.startswith("FAM") or "fineco" in source:
        label, title, cls = "Fi", "Fineco", "issuer-fineco"
    elif "amundi" in source:
        label, title, cls = "Am", "Amundi", "issuer-amundi"
    elif "ishares" in source or "blackrock" in source:
        label, title, cls = "iS", "iShares", "issuer-ishares"
    elif "xtrackers" in source or "dws" in source:
        label, title, cls = "X", "Xtrackers", "issuer-xtrackers"
    elif "franklin" in source:
        label, title, cls = "Fr", "Franklin Templeton", "issuer-franklin"
    elif "vanguard" in source:
        label, title, cls = "Vg", "Vanguard", "issuer-vanguard"
    else:
        return ""
    return f'<span class="issuer-badge {cls}" title="{html.escape(title, quote=True)}">{label}</span>'
