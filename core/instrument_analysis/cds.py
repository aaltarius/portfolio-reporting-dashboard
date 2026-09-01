"""Motore Core/Difensivo/Satellite.

Porting ripulito delle funzioni "congelate" del prototipo POC17.2
(`HANDOFF_PROGRAMMATORE_BENCHMARK_CDS/reference/poc17_2_engine_CDS_BASELINE_REFERENCE.py`),
la logica su cui e' tarata la fixture di regressione a 111 strumenti.

Differenze rispetto al prototipo, tutte deliberate:

- input: il prototipo lavorava su `Evidence` (testo grezzo dai provider) +
  `Profile` (derivato localmente da quel testo). Qui l'ingresso e' un
  `InstrumentProfile` gia' normalizzato (A8): il testo libero non esiste
  piu', quindi ogni segnale che nel prototipo veniva letto da nome/
  descrizione/benchmark viene ricavato dai campi strutturali del profilo
  (vedi `_derive_view`).
- output: `CDSAssignment` (contratto A1) al posto del `RoleFit` locale.
- nessuna rete, nessuna cache, nessun logging: `log(cb, msg)`,
  `cache_get`/`cache_put` e le chiamate `yfinance`/HTTP del prototipo non
  sono state portate.

Catena di calcolo (identica al prototipo, funzione `role()` a riga 1703):

    profilo -> _derive_view -> _structural_type
            -> _exposure_fingerprint
            -> _hierarchical_role_prior   (percentuali grezze + ruoli protetti)
            -> _quantize_effective        (soglia 20% + arrotondamento a 5)
            -> CDSAssignment
"""
from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass, field

from core.instrument_analysis.contracts import CDSAssignment, InstrumentProfile

__all__ = ["ROLE_MIN_PERCENT", "compute_cds"]

#: Soglia operativa: un ruolo sotto il 20% non viene esposto, salvo protezione
#: strutturale (POC17.2, costante `ROLE_MIN_PERCENT`).
ROLE_MIN_PERCENT = 20.0

_ROLES = ("core", "defensive", "satellite")

#: Token che nel prototipo venivano cercati nel testo libero per riconoscere
#: il debito ad alto rischio di credito (POC17.2: "emerging", "high yield",
#: "em debt", "credit opportunities").
_CREDIT_OPPORTUNITY_TOKENS = (
    "emerging",
    "high_yield",
    "high yield",
    "highyield",
    "em_debt",
    "em debt",
    "credit_opportunities",
    "credit opportunities",
    "junk",
    "speculative_grade",
)

#: Il vocabolario canonico dei tipi strutturali e' quello prodotto da
#: `structural_type()` in POC17.2 ed e' lo stesso usato dalla fixture di
#: regressione (BROAD_EQUITY, SHORT_GOV_BOND, ...). Qui accettiamo anche la
#: forma "famiglia prima" (EQUITY_BROAD, BOND_SHORT_GOV, ...) usata da alcuni
#: chiamanti, riportandola alla forma canonica: e' pura tolleranza di
#: denominazione, non cambia la logica.
_STRUCTURAL_TYPE_ALIASES = {
    "EQUITY_BROAD": "BROAD_EQUITY",
    "BROAD_EQUITY": "BROAD_EQUITY",
    "EQUITY_THEMATIC": "THEMATIC_EQUITY",
    "EQUITY_SMALL_CAP": "SMALL_CAP_EQUITY",
    "EQUITY_SMALL": "SMALL_CAP_EQUITY",
    "EQUITY_EX_MEGA_CAP": "EX_MEGA_CAP_EQUITY",
    "EQUITY_EMERGING_BROAD": "EMERGING_BROAD_EQUITY",
    "EQUITY_EMERGING": "EMERGING_BROAD_EQUITY",
    "EQUITY_SINGLE_COUNTRY": "SINGLE_COUNTRY_EQUITY",
    "EQUITY_COUNTRY_BROAD": "COUNTRY_BROAD_EQUITY",
    "BOND_GOV": "GOV_BOND",
    "BOND_GOVERNMENT": "GOV_BOND",
    "BOND_SHORT_GOV": "SHORT_GOV_BOND",
    "BOND_ULTRA_SHORT_GOV": "ULTRA_SHORT_GOV_BOND",
    "BOND_AGGREGATE": "AGGREGATE_BOND",
    "BOND_CORPORATE": "BOND",
    "BOND_INFLATION_LINKED": "INFLATION_LINKED_BOND",
    "CASH": "MONEY_MARKET",
    "MONETARY": "MONEY_MARKET",
    "MONEY_MARKET_FUND": "MONEY_MARKET",
    "CRYPTO": "DIGITAL_ASSET",
    "DIGITAL_ASSETS": "DIGITAL_ASSET",
    "PRECIOUS_METAL_GOLD": "GOLD",
}

_BOND_STRUCTURAL_TYPES = {
    "BOND",
    "GOV_BOND",
    "SHORT_GOV_BOND",
    "ULTRA_SHORT_GOV_BOND",
    "AGGREGATE_BOND",
    "INFLATION_LINKED_BOND",
}

#: Codici categoria del progetto (`core/asset_categories.py`) -> famiglia
#: economica del prototipo. ETF/FND/DER/ALTRO non dicono nulla sull'asset
#: sottostante e restano volutamente non mappati.
_ASSET_CLASS_TO_FAMILY = {
    "LIQ": "cash",
    "GOV": "bond",
    "OBB": "bond",
    "AZI": "equity",
    "ETC": "commodity",
}


# ---------------------------------------------------------------------------
# utility numeriche (porting da POC17.2: `_clip01`, `pct`, `mix`)
# ---------------------------------------------------------------------------

def _clip01(x) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.0


def _pct(x) -> float:
    """POC17.2 `pct()`: accetta sia 0.65 sia 65 e normalizza a frazione."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, v / 100.0 if v > 1.5 else v)


def _ascii_token(x) -> str:
    """POC17.2 `ascii_text()`, ridotto a quello che serve qui."""
    s = unicodedata.normalize("NFKD", str(x or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).strip().lower()


def _mix(asset_mix: dict[str, float] | None) -> tuple[float, float, float, float]:
    """POC17.2 `mix(e)`: ripartisce il mix in equity/bond/cash/altro."""
    eq = bond = cash = other = 0.0
    for k, v in (asset_mix or {}).items():
        kk = _ascii_token(k)
        if "stock" in kk or "equity" in kk or "azion" in kk:
            eq += _pct(v)
        elif "bond" in kk or "obblig" in kk:
            bond += _pct(v)
        elif "cash" in kk or "liquid" in kk:
            cash += _pct(v)
        else:
            other += _pct(v)
    return eq, bond, cash, other


# ---------------------------------------------------------------------------
# vista strutturale: l'equivalente del `Profile` di POC17.2, ricostruito dai
# campi di InstrumentProfile
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class _StructuralView:
    asset: str = ""
    geography: str = ""
    geo_scope: str = ""
    breadth: str = ""
    sector: str = ""
    theme: str = ""
    factor: str = ""
    market_breadth: float = 0.0
    size: str = ""
    issuer_type: str = ""
    bond_style: str = ""
    duration_years: float | None = None
    hedged: bool = False
    gold: bool = False
    digital_asset: bool = False
    confidence: float = 0.0
    # segnali che nel prototipo arrivavano dal testo libero
    credit_opportunity: bool = False
    target_maturity: bool = False
    has_external_evidence: bool = False
    mix: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


def _normalise_structural_type(value: str) -> str:
    st = _ascii_token(value).upper().replace("-", "_").replace(" ", "_")
    if not st:
        return ""
    if st in _STRUCTURAL_TYPE_ALIASES:
        return _STRUCTURAL_TYPE_ALIASES[st]
    if st.startswith("MULTI_ASSET"):
        return "MULTI_ASSET"
    return st


def _family_from_structural_type(st: str) -> str:
    if st == "DIGITAL_ASSET":
        return "digital_asset"
    if st in ("GOLD", "COMMODITY"):
        return "commodity"
    if st == "MONEY_MARKET":
        return "cash"
    if st == "MULTI_ASSET":
        return "multiasset"
    if st in _BOND_STRUCTURAL_TYPES:
        return "bond"
    if st.startswith("SECTOR_") or st.startswith("FACTOR_") or st.endswith("_EQUITY") or st == "EQUITY":
        return "equity"
    return ""


def _has_credit_opportunity(profile: InstrumentProfile, family: str) -> bool:
    """Sostituto strutturale del test testuale di POC17.2 su EM/high yield."""
    haystack = " ".join(
        _ascii_token(x) for x in (profile.issuer_type, profile.theme, profile.sector, profile.factor)
    )
    if any(tok in haystack for tok in _CREDIT_OPPORTUNITY_TOKENS):
        return True
    # Un obbligazionario non governativo su area emergente e' esattamente il
    # caso che nel prototipo veniva intercettato dal token "emerging".
    issuer = _ascii_token(profile.issuer_type)
    return family == "bond" and _ascii_token(profile.geography) == "emerging" and issuer != "government"


def _derive_view(profile: InstrumentProfile, asset_mix: dict[str, float] | None) -> _StructuralView:
    """Ricostruisce i segnali che POC17.2 leggeva da `Evidence`/`Profile`.

    Nessuna invenzione: se un segnale non e' desumibile dai campi di
    `InstrumentProfile` resta vuoto e la catena scivola sul ramo UNKNOWN,
    esattamente come nel prototipo quando il testo non era interpretabile.
    """
    view = _StructuralView()
    st = _normalise_structural_type(profile.structural_type)

    mix_source = asset_mix if asset_mix else profile.asset_mix
    view.mix = _mix(mix_source)
    eq, bond, cash, _other = view.mix

    view.geography = _ascii_token(profile.geography)
    view.geo_scope = _ascii_token(profile.geo_scope)
    view.sector = _ascii_token(profile.sector)
    view.theme = _ascii_token(profile.theme)
    view.factor = _ascii_token(profile.factor)
    view.size = _ascii_token(profile.size)
    view.issuer_type = _ascii_token(profile.issuer_type)
    view.duration_years = profile.duration_years
    view.hedged = bool(profile.hedged)
    view.market_breadth = float(profile.market_breadth or 0.0)
    view.confidence = float(profile.confidence or 0.0)
    view.has_external_evidence = bool(profile.provenance)
    # Un titolo con scadenza nota e' un singolo bond o un fondo target-maturity:
    # e' il segnale che POC17.2 cercava come " ibonds " / " target maturity ".
    view.target_maturity = bool(profile.maturity_date)

    commodity_type = _ascii_token(profile.commodity_type)
    view.gold = st == "GOLD" or commodity_type in ("gold", "oro")
    view.digital_asset = st == "DIGITAL_ASSET" or commodity_type in ("crypto", "bitcoin", "digital_asset")

    # --- famiglia economica -------------------------------------------------
    family = _family_from_structural_type(st)
    if not family:
        # POC17.2 `profile()`: il mix strutturale ha precedenza su tutto.
        if eq >= 0.15 and bond >= 0.10:
            family = "multiasset"
        elif view.gold or commodity_type:
            family = "commodity"
        elif view.digital_asset:
            family = "digital_asset"
        elif cash >= 0.50:
            family = "cash"
        elif bond >= 0.75:
            family = "bond"
        elif eq >= 0.75:
            family = "equity"
        else:
            family = _ASSET_CLASS_TO_FAMILY.get(_ascii_token(profile.asset_class).upper(), "")
    view.asset = family

    # --- specializzazioni implicite nel tipo strutturale --------------------
    if st.startswith("SECTOR_") and not view.sector:
        suffix = st[len("SECTOR_"):]
        view.sector = suffix.lower() if suffix and suffix != "EQUITY" else ""
    if st.startswith("FACTOR_") and not view.factor:
        view.factor = st[len("FACTOR_"):].lower()
    if st == "SMALL_CAP_EQUITY" and not view.size:
        view.size = "small"
    if st == "EX_MEGA_CAP_EQUITY" and not view.size:
        view.size = "ex_mega"
    if st == "EMERGING_BROAD_EQUITY" and not view.geography:
        view.geography = "emerging"
    if st in ("SINGLE_COUNTRY_EQUITY", "COUNTRY_BROAD_EQUITY") and not view.geo_scope:
        view.geo_scope = "country"

    # --- ampiezza (POC17.2 `Profile.breadth`) ------------------------------
    if st == "THEMATIC_EQUITY" or view.theme:
        view.breadth = "thematic"
    elif st.startswith("SECTOR_") or view.sector:
        view.breadth = "sector"
    elif st == "SINGLE_COUNTRY_EQUITY":
        view.breadth = "single_country"
    elif family == "equity":
        # `profile()` chiude sempre con: equity senza ampiezza esplicita = broad.
        view.breadth = "broad"

    if view.breadth == "thematic":
        view.market_breadth = view.market_breadth or 0.15
    elif view.breadth == "sector":
        view.market_breadth = view.market_breadth or 0.25

    # --- obbligazionario ----------------------------------------------------
    if family == "bond":
        if not view.issuer_type:
            if st in ("GOV_BOND", "SHORT_GOV_BOND", "ULTRA_SHORT_GOV_BOND"):
                view.issuer_type = "government"
            elif st == "AGGREGATE_BOND":
                view.issuer_type = "aggregate"
            elif _ascii_token(profile.asset_class).upper() == "GOV":
                view.issuer_type = "government"
        if st == "INFLATION_LINKED_BOND":
            view.bond_style = "inflation_linked"
        elif "inflation" in _ascii_token(profile.factor) or "inflation" in _ascii_token(profile.theme):
            view.bond_style = "inflation_linked"
        else:
            view.bond_style = "nominal_fixed"

    view.credit_opportunity = _has_credit_opportunity(profile, family)
    return view


def _structural_type(view: _StructuralView) -> str:
    """Porting di `structural_type(p)` (POC17.2, riga 1136)."""
    if view.digital_asset:
        return "DIGITAL_ASSET"
    if view.gold:
        return "GOLD"
    if view.asset == "commodity":
        return "COMMODITY"
    if view.asset == "cash":
        return "MONEY_MARKET"
    if view.asset == "multiasset":
        return "MULTI_ASSET"
    if view.asset == "bond":
        if view.bond_style == "inflation_linked":
            return "INFLATION_LINKED_BOND"
        if view.issuer_type == "government" and view.duration_years is not None and view.duration_years <= 1.25:
            return "ULTRA_SHORT_GOV_BOND"
        if view.issuer_type == "government" and view.duration_years is not None and view.duration_years <= 3:
            return "SHORT_GOV_BOND"
        if view.issuer_type == "government":
            return "GOV_BOND"
        if view.issuer_type == "aggregate":
            return "AGGREGATE_BOND"
        return "BOND"
    if view.asset == "equity":
        if view.breadth == "thematic" or view.theme:
            return "THEMATIC_EQUITY"
        if view.breadth == "sector" or view.sector:
            return "SECTOR_" + (view.sector.upper() if view.sector else "EQUITY")
        if view.factor:
            return "FACTOR_" + view.factor.upper()
        if view.size == "small":
            return "SMALL_CAP_EQUITY"
        if view.size == "ex_mega":
            return "EX_MEGA_CAP_EQUITY"
        if view.geography == "emerging":
            return "EMERGING_BROAD_EQUITY"
        if view.geo_scope == "country":
            return "SINGLE_COUNTRY_EQUITY" if view.market_breadth < 0.45 else "COUNTRY_BROAD_EQUITY"
        return "BROAD_EQUITY"
    return "UNKNOWN"


def _resolve_structural_type(profile: InstrumentProfile, view: _StructuralView) -> str:
    """Il tipo dichiarato nel profilo vince; altrimenti lo si deriva."""
    declared = _normalise_structural_type(profile.structural_type)
    if declared and _family_from_structural_type(declared):
        return declared
    return _structural_type(view)


# ---------------------------------------------------------------------------
# fingerprint di esposizione (POC17.2 `exposure_fingerprint`, riga 1170)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class _ExposureFingerprint:
    representativeness: float = 0.0
    breadth: float = 0.0
    diversification: float = 0.0
    concentration: float = 0.0
    specialization: float = 0.0
    geo_concentration: float = 0.0
    sector_concentration: float = 0.0
    factor_tilt: float = 0.0
    size_tilt: float = 0.0
    capital_stability: float = 0.0
    rate_risk: float = 0.0
    credit_risk: float = 0.0
    currency_risk: float = 0.0
    inflation_risk: float = 0.0
    sovereign_quality: float = 0.0
    liquidity: float = 0.0
    commodity_exposure: float = 0.0
    digital_exposure: float = 0.0
    leverage_risk: float = 0.0
    inverse_risk: float = 0.0
    multiasset_balance: float = 0.0
    evidence_confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)


def _exposure_fingerprint(view: _StructuralView) -> _ExposureFingerprint:
    """Impronta economica locale, solo CPU: nessuna chiamata di rete.

    Porting fedele di POC17.2 riga 1170. I rami su `leveraged`/`inverse` del
    prototipo non sono portati: `InstrumentProfile` non espone quei segnali e
    non intervengono nel percorso che produce le percentuali.
    """
    f = _ExposureFingerprint()
    eq, bd, ca, ot = view.mix

    strong_words = sum(
        bool(x)
        for x in (
            view.asset, view.geography, view.breadth, view.sector,
            view.factor, view.size, view.issuer_type, view.bond_style,
        )
    )
    f.evidence_confidence = _clip01(
        0.50 * view.confidence
        + 0.04 * strong_words
        + 0.08 * bool(eq or bd or ca or ot)
        + 0.06 * view.has_external_evidence
    )

    # Ampiezza / rappresentativita' / diversificazione.
    if view.asset == "equity":
        f.breadth = 0.92 if view.breadth == "broad" else (0.45 if view.breadth == "sector" else (0.25 if view.breadth == "thematic" else 0.55))
        f.representativeness = 0.92 if view.breadth == "broad" and view.geography in ("world", "usa", "europe") else 0.55
        f.diversification = 0.85 if view.breadth == "broad" else (0.50 if view.breadth == "sector" else 0.30)
    elif view.asset == "bond":
        f.breadth = 0.80 if view.issuer_type in ("government", "aggregate") else 0.62
        f.representativeness = 0.80 if view.issuer_type == "aggregate" else 0.62
        f.diversification = 0.82 if view.issuer_type == "aggregate" else 0.62
    elif view.asset == "multiasset":
        f.breadth = 0.80
        f.representativeness = 0.72
        f.diversification = 0.88
    elif view.asset == "cash":
        f.breadth = 0.55
        f.representativeness = 0.75
        f.diversification = 0.60
    elif view.gold:
        f.breadth = 0.10
        f.representativeness = 0.15
        f.diversification = 0.15
    elif view.asset == "commodity":
        f.breadth = 0.35
        f.representativeness = 0.30
        f.diversification = 0.35
    elif view.digital_asset:
        f.breadth = 0.05
        f.representativeness = 0.05
        f.diversification = 0.05

    # Concentrazione da struttura.
    if view.breadth == "thematic":
        f.specialization = 0.98
        f.concentration = 0.88
    elif view.breadth == "sector":
        f.specialization = 0.88
        f.sector_concentration = 0.92
        f.concentration = 0.78
    elif view.breadth == "single_country":
        f.specialization = 0.55
        f.geo_concentration = 0.90
        f.concentration = 0.70
    elif view.breadth == "broad":
        f.specialization = 0.12

    if view.geography in ("italy", "italia", "japan", "korea", "china"):
        f.geo_concentration = max(f.geo_concentration, 0.82)
        f.specialization = max(f.specialization, 0.45)
    elif view.geography in ("usa", "europe"):
        f.geo_concentration = max(f.geo_concentration, 0.35)
    elif view.geography == "emerging":
        f.geo_concentration = max(f.geo_concentration, 0.30)
        f.specialization = max(f.specialization, 0.28)

    if view.factor:
        f.factor_tilt = 0.72 if view.factor in ("minimum_volatility", "low_beta", "quality", "value", "momentum", "dividend") else 0.60
        f.specialization = max(f.specialization, 0.48)
    if view.size == "small":
        f.size_tilt = 0.82
        f.specialization = max(f.specialization, 0.58)
    elif view.size == "ex_mega":
        f.size_tilt = 0.60
        f.specialization = max(f.specialization, 0.42)

    # Dimensioni difensive.
    if view.asset == "cash":
        f.capital_stability = 0.99
        f.liquidity = 0.98
        f.sovereign_quality = 0.90
    elif view.asset == "bond":
        duration = float(view.duration_years if view.duration_years is not None else 5.0)
        f.rate_risk = _clip01(duration / 10.0)
        if view.issuer_type == "government":
            f.sovereign_quality = 0.90
            f.credit_risk = 0.08
            f.capital_stability = _clip01(0.92 - 0.045 * max(0, duration - 1))
        elif view.issuer_type == "aggregate":
            f.sovereign_quality = 0.55
            f.credit_risk = 0.28
            f.capital_stability = 0.72
        elif view.issuer_type == "corporate":
            f.credit_risk = 0.48
            f.capital_stability = 0.58
        else:
            f.credit_risk = 0.35
            f.capital_stability = 0.64
        if view.credit_opportunity:
            f.credit_risk = max(f.credit_risk, 0.78)
            f.specialization = max(f.specialization, 0.62)
            f.capital_stability *= 0.78
        if view.bond_style == "inflation_linked":
            f.inflation_risk = 0.48
            f.specialization = max(f.specialization, 0.38)
            f.capital_stability = max(f.capital_stability, 0.70)
        f.liquidity = 0.75
    elif view.gold:
        f.capital_stability = 0.52
        f.liquidity = 0.88
    elif view.asset == "commodity":
        f.capital_stability = 0.18
        f.liquidity = 0.78
    elif view.digital_asset:
        f.capital_stability = 0.03
        f.liquidity = 0.72
    elif view.asset == "equity":
        f.capital_stability = 0.22 if view.factor not in ("minimum_volatility", "low_beta") else 0.42
        f.liquidity = 0.80

    if view.hedged:
        f.currency_risk = 0.08
    elif view.geography == "world":
        f.currency_risk = 0.42
    else:
        f.currency_risk = 0.18

    # Domini alternativi.
    if view.gold:
        f.commodity_exposure = 1.0
        f.specialization = max(f.specialization, 0.82)
        f.concentration = max(f.concentration, 0.85)
    elif view.asset == "commodity":
        f.commodity_exposure = 0.90
        f.specialization = max(f.specialization, 0.75)
    if view.digital_asset:
        f.digital_exposure = 1.0
        f.specialization = 1.0
        f.concentration = 1.0

    if view.asset == "multiasset":
        tot = max(1e-9, eq + bd + ca + ot)
        eq, bd, ca, ot = eq / tot, bd / tot, ca / tot, ot / tot
        f.multiasset_balance = _clip01(1.0 - abs(eq - bd))
        f.capital_stability = _clip01(0.18 * eq + 0.74 * bd + 0.98 * ca + 0.25 * ot)
        f.specialization = max(f.specialization, 0.25 * ot)

    f.reasons.append(
        f"Fingerprint: breadth={f.breadth:.2f}, diversification={f.diversification:.2f}, "
        f"specialization={f.specialization:.2f}, stability={f.capital_stability:.2f}."
    )
    return f


# ---------------------------------------------------------------------------
# quantizzazione (POC17.2 `_quantize_effective`, riga 1604)
# ---------------------------------------------------------------------------

def _quantize_effective(raw, threshold, protected=None, min_keep_ratio=0.65):
    protected = set(protected or ())
    keep_floor = threshold * min_keep_ratio

    kept = {}
    for k, v in raw.items():
        if v >= threshold:
            kept[k] = v
        elif k in protected and v >= keep_floor:
            kept[k] = v
        else:
            kept[k] = 0.0

    if sum(kept.values()) <= 0:
        winner = max(raw, key=raw.get)
        kept[winner] = raw[winner]

    kt = sum(kept.values()) or 1.0
    er = {k: 100.0 * v / kt for k, v in kept.items()}

    # Quantizzazione a 5 punti con il metodo del resto maggiore.
    unit = 5.0
    exact = {k: v / unit for k, v in er.items()}
    floors = {k: int(math.floor(v + 1e-12)) for k, v in exact.items()}
    remaining = int(round(100 / unit)) - sum(floors.values())
    order = sorted(exact, key=lambda k: (exact[k] - floors[k], er[k]), reverse=True)
    for k in order[:max(0, remaining)]:
        floors[k] += 1

    out = {k: float(floors[k] * unit) for k in floors}

    # Un ruolo protetto sopravvissuto economicamente non deve tornare a zero
    # per effetto dell'arrotondamento: prende un quanto dal ruolo maggiore.
    for k in protected:
        if kept.get(k, 0) > 0 and out.get(k, 0) == 0:
            donor = max((x for x in out if x != k), key=lambda x: out[x], default=None)
            if donor and out[donor] >= 10:
                out[donor] -= 5.0
                out[k] = 5.0

    return out


# ---------------------------------------------------------------------------
# prior gerarchico (POC17.2 `_hierarchical_role_prior`, riga 1644)
# ---------------------------------------------------------------------------

def _hierarchical_role_prior(view: _StructuralView, st: str):
    flags = ["ARCHETYPE:" + st]
    reasons: list[str] = []
    protected: set[str] = set()
    keep_ratio = 0.65

    if st == "DIGITAL_ASSET":
        raw = {"core": 0, "defensive": 0, "satellite": 100}
        protected = {"satellite"}
    elif st == "GOLD":
        raw = {"core": 0, "defensive": 70, "satellite": 30}
        protected = {"defensive", "satellite"}
    elif st == "COMMODITY":
        raw = {"core": 0, "defensive": 0, "satellite": 100}
        protected = {"satellite"}
    elif st == "MONEY_MARKET":
        raw = {"core": 0, "defensive": 100, "satellite": 0}
        protected = {"defensive"}
    elif view.asset == "multiasset":
        eq, bd, ca, ot = view.mix
        total = eq + bd + ca + ot
        if total > 0.25:
            eq, bd, ca, ot = eq / total, bd / total, ca / total, ot / total
            scores = {
                "core": 2 + 6.5 * eq + 2 * bd,
                "defensive": 0.7 + 7.5 * bd + 8.5 * ca,
                "satellite": 0.5 + 2.5 * eq + 5 * ot,
            }
            ss = sum(scores.values())
            raw = {k: 100 * v / ss for k, v in scores.items()}
            reasons.append(
                f"Mix strutturale multi-asset: equity {eq:.0%}, bond {bd:.0%}, "
                f"cash {ca:.0%}, altro {ot:.0%}."
            )
        else:
            raw = {"core": 50, "defensive": 40, "satellite": 10}
            reasons.append("Identita' multi-asset nota, allocazione incompleta.")
        # Il multi-asset tiene la soglia operativa del 20% in modo stretto: uno
        # spicchio minore non deve sopravvivere solo perche' esiste.
        protected = {k for k, v in raw.items() if v >= 20}
    elif view.asset == "bond":
        if st == "ULTRA_SHORT_GOV_BOND":
            raw = {"core": 0, "defensive": 100, "satellite": 0}
            protected = {"defensive"}
        elif st == "SHORT_GOV_BOND":
            # I singoli sovrani vicini a scadenza restano Difensivo puro; i
            # fondi governativi 1-3 anni diversificati tengono un po' di Core.
            if view.target_maturity:
                raw = {"core": 0, "defensive": 100, "satellite": 0}
                protected = {"defensive"}
            else:
                raw = {"core": 20, "defensive": 80, "satellite": 0}
                protected = {"core", "defensive"}
        elif st == "GOV_BOND":
            raw = {"core": 25, "defensive": 75, "satellite": 0}
            protected = {"core", "defensive"}
        elif st == "INFLATION_LINKED_BOND":
            raw = {"core": 20, "defensive": 70, "satellite": 10}
            protected = {"core", "defensive", "satellite"}
            keep_ratio = 0.40
        elif view.credit_opportunity:
            raw = {"core": 20, "defensive": 45, "satellite": 35}
            protected = {"core", "defensive", "satellite"}
        elif view.issuer_type == "corporate":
            raw = {"core": 35, "defensive": 65, "satellite": 0}
            protected = {"core", "defensive"}
        elif view.issuer_type == "aggregate":
            raw = {"core": 35, "defensive": 65, "satellite": 0}
            protected = {"core", "defensive"}
        else:
            raw = {"core": 35, "defensive": 65, "satellite": 0}
            protected = {"core", "defensive"}
    elif view.asset == "equity":
        if st == "THEMATIC_EQUITY":
            raw = {"core": 0, "defensive": 0, "satellite": 100}
            protected = {"satellite"}
        elif st.startswith("SECTOR_"):
            raw = {"core": 25, "defensive": 0, "satellite": 75}
            protected = {"core", "satellite"}
        elif view.factor in ("minimum_volatility", "low_beta"):
            raw = {"core": 70, "defensive": 30, "satellite": 0}
            protected = {"core", "defensive"}
        elif view.factor == "quality":
            raw = {
                "core": 75 if view.geography == "world" else 65,
                "defensive": 0,
                "satellite": 25 if view.geography == "world" else 35,
            }
            protected = {"core", "satellite"}
        elif view.size == "small":
            raw = {"core": 55, "defensive": 0, "satellite": 45}
            protected = {"core", "satellite"}
        elif view.size == "ex_mega":
            raw = {"core": 60, "defensive": 0, "satellite": 40}
            protected = {"core", "satellite"}
        elif st == "EMERGING_BROAD_EQUITY":
            raw = {"core": 70, "defensive": 0, "satellite": 30}
            protected = {"core", "satellite"}
        elif st == "SINGLE_COUNTRY_EQUITY":
            raw = {"core": 20, "defensive": 0, "satellite": 80}
            protected = {"core", "satellite"}
        elif st == "COUNTRY_BROAD_EQUITY":
            raw = {"core": 75, "defensive": 0, "satellite": 25}
            protected = {"core", "satellite"}
        elif view.geo_scope == "regional":
            raw = {"core": 80, "defensive": 0, "satellite": 20}
            protected = {"core", "satellite"}
        elif view.geography == "world" or view.geo_scope == "global":
            raw = {"core": 100, "defensive": 0, "satellite": 0}
            protected = {"core"}
        else:
            raw = {"core": 85, "defensive": 0, "satellite": 15}
            protected = {"core"}
    else:
        raw = {"core": 34, "defensive": 33, "satellite": 33}

    return raw, protected, keep_ratio, flags, reasons


# ---------------------------------------------------------------------------
# funzione pubblica (POC17.2 `role`, riga 1703)
# ---------------------------------------------------------------------------

def compute_cds(
    profile: InstrumentProfile,
    *,
    asset_mix: dict[str, float] | None = None,
    threshold: float = ROLE_MIN_PERCENT,
) -> CDSAssignment:
    """Assegna le quote Core/Difensivo/Satellite a partire dal profilo.

    `asset_mix` (chiavi tipo ``equity``/``bond``/``cash``) ha la precedenza su
    `profile.asset_mix` ed e' il segnale primario per i multi-asset.

    Il risultato soddisfa sempre ``core+defensive+satellite == 100`` entro la
    tolleranza di `CDSAssignment.validate()`: la quantizzazione a resto
    maggiore distribuisce esattamente 20 quanti da 5 punti.
    """
    view = _derive_view(profile, asset_mix)
    st = _resolve_structural_type(profile, view)
    fingerprint = _exposure_fingerprint(view)

    raw, protected, keep_ratio, flags, reasons = _hierarchical_role_prior(view, st)
    total = sum(max(0, float(v)) for v in raw.values()) or 1
    raw = {k: 100 * max(0, float(v)) / total for k, v in raw.items()}
    effective = _quantize_effective(raw, threshold, protected, keep_ratio)

    evidence_count = sum(
        [
            bool(profile.asset_class),
            bool(profile.structural_type),
            bool(view.mix[0] or view.mix[1] or view.mix[2] or view.mix[3]),
            bool(view.asset),
            bool(view.geography),
            bool(view.breadth),
            view.duration_years is not None,
            view.has_external_evidence,
        ]
    )
    identity = 0.88 if st != "UNKNOWN" else 0.45
    confidence = min(
        0.99,
        0.50 * view.confidence + 0.22 * fingerprint.evidence_confidence + 0.16 * identity + 0.015 * evidence_count,
    )
    if view.gold or view.digital_asset or view.asset == "cash":
        confidence = max(confidence, 0.92)
    if st in ("ULTRA_SHORT_GOV_BOND", "SHORT_GOV_BOND"):
        confidence = max(confidence, 0.92)

    flags.append("ROLE_AWARE_KEEP:" + (",".join(sorted(protected)) if protected else "none"))

    assignment = CDSAssignment(
        raw_core_pct=raw["core"],
        raw_defensive_pct=raw["defensive"],
        raw_satellite_pct=raw["satellite"],
        core_pct=effective["core"],
        defensive_pct=effective["defensive"],
        satellite_pct=effective["satellite"],
        active_roles=[role.capitalize() for role in _ROLES if effective.get(role, 0.0) > 0],
        confidence=confidence,
        validation_flags=flags,
        reasons=list(fingerprint.reasons) + reasons,
    )
    assignment.validate()
    return assignment
