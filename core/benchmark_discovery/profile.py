"""Passo 1: profilo dello strumento da TUTTE le informazioni dell'arricchimento."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .vocabulary import group_of, translate


@dataclass
class DiscoveryProfile:
    ticker: str
    isin: str
    name: str
    country: str = ""
    kind: str = ""
    index_declared: str = ""
    category_en: str = ""
    area_terms: list[str] = field(default_factory=list)
    theme_terms: list[str] = field(default_factory=list)
    currency: str = ""
    hedged: bool | None = None
    distribution: str | None = None
    duration_years: float | None = None
    issuer: str = ""
    ter: float | None = None
    aum: float | None = None
    equity_pct: float | None = None
    bond_pct: float | None = None
    descriptor: str = ""


def _s(*values: Any) -> str:
    for v in values:
        if v not in (None, "", [], {}):
            return str(v).strip()
    return ""


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    t = re.sub(r"[^0-9,.\-]", "", str(value))
    if not t:
        return None
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


def build_profile(inst: dict, master: dict | None = None) -> DiscoveryProfile:
    inst = inst if isinstance(inst, dict) else {}
    master = master if isinstance(master, dict) else {}
    isin = _s(inst.get("isin"), master.get("isin")).upper()
    descriptive = " ".join(_s(inst.get(k)) for k in
                           ("focus_etf", "categoria_etf", "categoria_fam", "natura", "tipo", "struttura",
                            "emittente_btp", "specializzazione"))
    descriptive += " " + _s(master.get("type_raw"), master.get("sub_asset_class"), master.get("asset_class"))
    words = translate(descriptive + " " + _s(inst.get("nome"), master.get("name")) + " " + _s(inst.get("indice_sottostante")))
    kinds = [w for w in words if group_of(w) == "kind"]
    # ordine di priorita' dei tipi quando il testo ne cita piu' d'uno
    kind = next((k for k in ("crypto", "money_market", "bond", "commodity", "multi_asset", "equity") if k in kinds), "")
    theme = [w for w in words if group_of(w) == "theme"]
    area = [w for w in words if group_of(w) == "area"]
    if kind in ("", "equity") and any(t in theme for t in ("gold", "precious metals")):
        kind = "commodity"
    raw_hedge = _s(inst.get("rischio_cambio")).lower()
    hedged = None
    if raw_hedge:
        hedged = False if "senza" in raw_hedge else True if "copert" in raw_hedge else None
    raw_dist = _s(inst.get("distribuzione")).lower()
    dist = "acc" if "accum" in raw_dist else "dist" if "distrib" in raw_dist else None
    return DiscoveryProfile(
        ticker=_s(inst.get("ticker"), master.get("ticker")), isin=isin,
        name=_s(inst.get("nome"), master.get("name")),
        country=isin[:2], kind=kind,
        index_declared=_s(inst.get("indice_sottostante")),
        category_en=_s(inst.get("categoria_etf")),
        area_terms=area, theme_terms=theme,
        currency=_s(inst.get("valuta_etf"), inst.get("valuta"), master.get("currency")),
        hedged=hedged, distribution=dist,
        duration_years=_num(inst.get("duration_modificata")),
        issuer=_s(inst.get("emittente"), inst.get("emittente_btp")),
        ter=_num(inst.get("ter")), aum=_num(inst.get("aum") or inst.get("patrimonio")),
        equity_pct=_num(inst.get("composizione_az")), bond_pct=_num(inst.get("composizione_obbl")),
        descriptor=(descriptive + " " + _s(inst.get("nome"), master.get("name"))).strip(),
    )
