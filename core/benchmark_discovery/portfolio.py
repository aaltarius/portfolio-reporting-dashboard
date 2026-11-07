"""Riferimenti del benchmark di PORTAFOGLIO (menu «60/40 MSCI World / Bond», «100% GOV»...).

Ogni voce del menu e' un profilo di TESTO (le parole dell'etichetta scelta dall'utente), non uno
strumento: lo stesso algoritmo cerca sul web il riferimento e lo salva in archivio come decisione
di uno «strumento virtuale» `PORTFOLIO:<concetto>`. Senza uno strumento proprio manca la misura di
correlazione: la scelta si basa su coerenza del nome e storico, e un indice vale piu' di un ETF.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .decide import CandidateSource, resolve
from .profile import DiscoveryProfile
from .runner import persist

REFERENCE_PROFILES: dict[str, DiscoveryProfile] = {
    "GLOBAL_EQUITY": DiscoveryProfile(ticker="PORTFOLIO:GLOBAL_EQUITY", isin="", name="MSCI World", kind="equity",
                                      index_declared="MSCI World", area_terms=["world"]),
    "BOND": DiscoveryProfile(ticker="PORTFOLIO:BOND", isin="", name="Global Aggregate Bond", kind="bond",
                             theme_terms=["aggregate"], area_terms=["global"]),
    "GOV_BOND": DiscoveryProfile(ticker="PORTFOLIO:GOV_BOND", isin="", name="Italy Government Bond", kind="bond",
                                 theme_terms=["government"], area_terms=["italy"]),
}


@dataclass(frozen=True)
class Choice:
    code: str
    levels: dict[str, float]
    family: str
    rank: int
    currency: str
    fallback: bool = False

    @property
    def start(self):
        return min(self.levels)

    @property
    def end(self):
        return max(self.levels)

    @property
    def span_days(self):
        return (date.fromisoformat(self.end) - date.fromisoformat(self.start)).days


def discover_references(store, source: CandidateSource) -> dict[str, bool]:
    """Cerca e salva il riferimento di ciascun concetto del menu; True se la decisione e' stata salvata."""
    out = {}
    for family, profile in REFERENCE_PROFILES.items():
        decision = resolve(profile, {}, source)
        decision.grade = "RIFERIMENTO"  # senza strumento proprio la parentela non ha senso: e' un riferimento di mercato
        out[family] = persist(store, profile.ticker, profile, decision, source) is not None
    return out


def reference_choice(store, family: str, *, min_points: int = 20) -> Choice | None:
    """Riferimento salvato per un concetto, con serie in euro; None se manca o e' troppo corta.

    Una serie ferma da giorni e' valida: la sua eta' la segnala `resolve_portfolio_components` (BM-14)."""
    from core.verified_benchmarks.engine import _series_eur

    a = store.assignment("PORTFOLIO:" + family)
    if not a or not a.get("discovery") or not a.get("ticker"):
        return None
    try:
        series, currency = _series_eur(store, a["ticker"])
    except ValueError:
        return None
    if len(series) < min_points or currency != "EUR":
        return None
    return Choice(a["ticker"], series, family, 0, currency)


def custom_component_options(store) -> dict[str, str]:
    """Etichetta -> codice delle serie presenti in archivio (scoperte, importate o fissate a mano)."""
    with store._connect() as con:
        rows = con.execute("SELECT series_id,name FROM index_series WHERE series_id NOT LIKE 'BLEND:%' "
                           "AND series_id NOT LIKE '%=X' ORDER BY name").fetchall()
    return {f"{name} ({code})": code for code, name in rows}


# ── Menu del benchmark di portafoglio ─────────────────────────────────────────
# Etichetta -> pesi per concetto. I concetti sono profili di testo (REFERENCE_PROFILES): lo strumento
# concreto lo sceglie la ricerca sul web e sta in archivio. «Blend automatico» ha pesi calcolati.
PORTFOLIO_MENU: dict[str, list[tuple[str, float]]] = {
    "Blend automatico": [],
    "60/40 MSCI World / Bond": [("GLOBAL_EQUITY", 0.60), ("BOND", 0.40)],
    "100% MSCI World": [("GLOBAL_EQUITY", 1.0)],
    "100% GOV": [("GOV_BOND", 1.0)],
}


def _num(value, default=0.0) -> float:
    try:
        v = float(value)
        return v if v == v else default
    except (TypeError, ValueError):
        return default


def _government_share(frame) -> float:
    if frame is None or getattr(frame, "empty", True) or "Controvalore" not in frame:
        return 0.0
    import pandas as pd
    from persistence.storage import macro_cat
    values = pd.to_numeric(frame["Controvalore"], errors="coerce").fillna(0)
    total = float(values.sum())
    col = "Tipo" if "Tipo" in frame.columns else "Tipologia" if "Tipologia" in frame.columns else None
    if total <= 0 or col is None:
        return 0.0
    return float(values.loc[frame[col].apply(macro_cat) == "GOV"].sum()) / total


def _entry(store, code: str, label: str, weight: float, family: str, series: dict, currency: str, requested: str = "") -> dict:
    spec = store._spec(code)
    from core.verified_benchmarks.freshness import staleness
    age = staleness(series)
    return {"ticker": code, "label": label or spec.label, "weight": weight, "kind": spec.asset_kind, "currency": currency,
            "requested_ticker": requested, "family": family, "points": len(series), "first_date": min(series),
            "last_date": max(series), "source": "SQLite", "age_days": age["age_days"], "stale": age["stale"]}


def resolve_portfolio_components(settings: dict | None, da_frame, store, *, label: str | None = None) -> dict:
    """Componenti effettivi del benchmark di portafoglio, letti dall'archivio. Nessuna sostituzione silenziosa."""
    from core.verified_benchmarks.engine import _series_eur
    from core.verified_benchmarks.freshness import staleness

    settings = settings if isinstance(settings, dict) else {}
    bench = settings.get("benchmarking") if isinstance(settings.get("benchmarking"), dict) else {}
    chosen = label or str(settings.get("portfolio_benchmark_default") or bench.get("default_portfolio_benchmark")
                          or "Blend automatico")
    custom = [c for c in (bench.get("custom_components") or []) if isinstance(c, dict)] if bench.get("custom_enabled") else []
    requested: list[dict] = []
    mode = "predefinito"
    known = {code for code in custom_component_options(store).values()}
    if custom:
        mode = "personalizzato"
        weights: dict[str, float] = {}
        for item in custom:
            code, w = str(item.get("ticker") or "").strip(), _num(item.get("weight"))
            if code in known and w > 0:
                weights[code] = weights.get(code, 0.0) + w
        total = sum(weights.values())
        requested = [{"ticker": c, "weight": w / total} for c, w in sorted(weights.items())] if total > 0 else []
    elif chosen in PORTFOLIO_MENU and PORTFOLIO_MENU[chosen]:
        requested = [{"family": f, "weight": w} for f, w in PORTFOLIO_MENU[chosen]]
    else:
        gov = _government_share(da_frame)
        requested = [{"family": "GOV_BOND", "weight": gov}, {"family": "GLOBAL_EQUITY", "weight": 1 - gov}]
        mode = "blend automatico"
        chosen = "Blend automatico"
    requested = [c for c in requested if c["weight"] > 1e-7]

    out, missing, notes = [], [], []
    for comp in requested:
        if "family" in comp:
            ref = reference_choice(store, comp["family"])
            if ref is None:
                missing.append({"family": comp["family"], "requested": "", "weight": comp["weight"], "attempted": []})
                continue
            out.append(_entry(store, ref.code, "", comp["weight"], comp["family"], ref.levels, ref.currency))
        else:
            try:
                series, currency = _series_eur(store, comp["ticker"])
            except ValueError:
                series, currency = {}, ""
            if len(series) < 20:
                missing.append({"family": comp["ticker"], "requested": comp["ticker"], "weight": comp["weight"], "attempted": []})
                continue
            out.append(_entry(store, comp["ticker"], "", comp["weight"], comp["ticker"], series, currency, comp["ticker"]))
    for e in out:
        if e["kind"] == "etf_proxy":
            notes.append(f"{e['ticker']} e' un ETF proxy, NON un indice ufficiale.")
    stale = [e for e in out if e.get("stale")]
    if stale:
        oldest = min(stale, key=lambda e: e["last_date"])
        notes.append(f"Dati fermi al {oldest['last_date'][8:10]}/{oldest['last_date'][5:7]}/{oldest['last_date'][:4]} "
                     f"({oldest['age_days']} giorni fa): premi «Aggiorna i prezzi dei benchmark scelti» in Cruscotti → Benchmark.")
    note = " ".join(dict.fromkeys(notes))
    if missing:
        note += " Componenti senza storico utilizzabile: " + ", ".join(m["family"] for m in missing) + ". Premi «Ricalcola la scelta» in Cruscotti → Benchmark."
    if mode == "blend automatico":
        note += " I pesi GOV dipendono dalla composizione attuale: non sono un benchmark strategico fisso."
    return {"label": chosen, "mode": mode, "components": out, "missing_components": missing,
            "requested_count": len(requested), "method_note": note.strip() or "Serie e pesi letti dall'archivio."}
