"""
core/services/sator.py — Motore SATOR (Strategic Allocation Tactical Order
Recommender) riprogettato attorno a un principio unico: la trasparenza.

Regole di impianto:
  1. UN SOLO punteggio per strumento. Il voto che si vede in tabella e' lo
     stesso che ordina le righe: non esistono piu' due classifiche divergenti.
  2. Le cinque dimensioni sono mappate su scala ASSOLUTA e interpretabile, cosi'
     il voto di uno strumento non dipende dal resto del paniere.
  3. Il confronto "perche' questo e non quello" avviene per GRUPPO OMOGENEO: per
     ogni funzione utile il motore indica il vincitore, il rivale diretto e il
     fattore su cui si e' deciso il confronto, in italiano leggibile.
  4. Lo stato "in portafoglio" NON da' bonus: incide solo via peso e
     concentrazione. Un titolo gia' molto pesante puo' essere battuto da un pari
     funzione non posseduto, ma sempre per un motivo dichiarato.

Pesi delle dimensioni (dal documento di impianto):
   30% fit strategico | 25% momentum | 20% rischio | 15% diversificazione | 10% costo
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from core.constants import QTY_ZERO_EPS
from core.domain.risk import build_drawdown_series, rolling_sharpe, rolling_volatility_annualized
from core.domain.returns import combine_weighted_returns, normalize_to_first, simple_period_return
from core.finance import build_ptf_df, compute_portfolio_state
from core.price_frames import build_expanded_price_frame
from persistence.storage import load_sator_decisions, macro_cat

logger = logging.getLogger("portafoglio.core.services.sator")


# --------------------------------------------------------------------------- #
# Costanti
# --------------------------------------------------------------------------- #

SATOR_STATE_VALUES = ("in_portafoglio", "watchlist", "escluso")
SATOR_COMMISSION_VALUES = ("zero_commissioni", "standard", "non_definito")
SATOR_ROLE_VALUES = (
    "core_globale", "core_regionale", "core_difensivo",
    "satellite_crescita", "satellite_difensivo", "satellite_tematico",
    "liquidita", "oro", "bond", "altro",
)
SATOR_INVESTIBLE_CATEGORIES = ("ETF", "ETC")

# Etichette leggibili in italiano per le chiavi tecniche (snake_case) sopra:
# usate SOLO per la visualizzazione (es. format_func delle SelectboxColumn
# nell'editor universo SATOR in Pianificazione) - le chiavi stesse restano
# invariate perche' sono referenziate da punteggi/cap di concentrazione e da
# decisioni SATOR gia' salvate su disco.
SATOR_STATE_LABELS: dict[str, str] = {
    "in_portafoglio": "In portafoglio",
    "watchlist": "In osservazione",
    "escluso": "Escluso",
}
SATOR_ROLE_LABELS: dict[str, str] = {
    "core_globale": "Core globale",
    "core_regionale": "Core regionale",
    "core_difensivo": "Core difensivo",
    "satellite_crescita": "Satellite crescita",
    "satellite_difensivo": "Satellite difensivo",
    "satellite_tematico": "Satellite tematico",
    "liquidita": "Liquidità",
    "oro": "Oro",
    "bond": "Obbligazionario",
    "altro": "Altro",
}

PESI_DIMENSIONI: dict[str, float] = {
    "strategic_fit": 0.30,
    "tactical_momentum": 0.25,
    "risk_efficiency": 0.20,
    "diversification_benefit": 0.15,
    "cost_efficiency": 0.10,
}

# Etichette leggibili per le spiegazioni comparative.
NOME_FATTORE: dict[str, str] = {
    "strategic_fit": "fit allocativo",
    "tactical_momentum": "momentum",
    "risk_efficiency": "efficienza di rischio",
    "diversification_benefit": "diversificazione",
    "cost_efficiency": "efficienza di costo",
}

# Cap morbidi di concentrazione per natura: oltre il limite, fit e
# diversificazione calano. Sono soglie indicative, non vincoli rigidi.
CAP_MORBIDO_NATURA: dict[str, float] = {
    "azionario_globale_core": 0.55,
    "azionario_emergenti": 0.15,
    "azionario_paese_singolo": 0.08,
    "monetario": 0.20,
    "bond_governativo": 0.25,
    "bond_globale": 0.25,
    "oro": 0.10,
    "tecnologia_ai": 0.08,
    "healthcare": 0.08,
    "energia": 0.06,
    "metalli_miniere": 0.06,
    "commodities": 0.08,
    "italia": 0.10,
    "quality_factor": 0.12,
    "real_estate": 0.08,
    "difesa_sicurezza": 0.06,
    "criptovalute": 0.05,
}
CAP_MORBIDO_DEFAULT = 0.08

# Nature selezionabili nell'editor universo (le stesse usate per i cap morbidi).
SATOR_NATURE_VALUES = tuple(CAP_MORBIDO_NATURA.keys()) + ("fondo_pac", "altro")

# Etichette leggibili in italiano per SATOR_NATURE_VALUES - vedi nota su
# SATOR_STATE_LABELS/SATOR_ROLE_LABELS: solo visualizzazione, le chiavi
# restano invariate.
SATOR_NATURE_LABELS: dict[str, str] = {
    "azionario_globale_core": "Azionario globale core",
    "azionario_emergenti": "Azionario emergenti",
    "azionario_paese_singolo": "Azionario paese singolo",
    "monetario": "Monetario",
    "bond_governativo": "Obbligazionario governativo",
    "bond_globale": "Obbligazionario globale",
    "oro": "Oro",
    "tecnologia_ai": "Tecnologia / AI",
    "healthcare": "Salute",
    "energia": "Energia",
    "metalli_miniere": "Metalli e miniere",
    "commodities": "Materie prime",
    "italia": "Italia",
    "quality_factor": "Fattore qualità",
    "real_estate": "Immobiliare",
    "difesa_sicurezza": "Difesa / sicurezza",
    "criptovalute": "Criptovalute",
    "fondo_pac": "Fondo PAC",
    "altro": "Altro",
}

FINESTRE = {"ret_1m": 21, "ret_3m": 63, "ret_6m": 126, "ret_12m": 252}
PESI_MOMENTUM = {"ret_1m": 0.10, "ret_3m": 0.35, "ret_6m": 0.35, "ret_12m": 0.20}
MIN_PUNTI_STORICO = 30
MAX_LINEE_SUGGERITE = 5  # tetto di funzioni servite dalle quote suggerite

DEFAULT_SATOR_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "budget_preset": 900.0,
    "default_budget": 900.0,
    "include_watchlist": True,
    "include_portfolio": True,
    "investible_categories": list(SATOR_INVESTIBLE_CATEGORIES),
    "max_share_per_line": 0.35,   # nessuna linea oltre il 35% del budget suggerito
    "score_weights": dict(PESI_DIMENSIONI),
    "concentration_caps": dict(CAP_MORBIDO_NATURA),
    "band_tolerance_pp": 0.03,
    "deficit_pac_only": False,
    "bucket_first_allocation": False,
    "instrument_quotas": {"Core": {}, "Difensivo": {}, "Satellite": {}},
    "instrument_quota_tolerance_pp": 0.05,
}


@dataclass
class SatorContext:
    data: dict[str, Any]
    settings: dict[str, Any]
    budget: float
    state_df: pd.DataFrame
    price_frame: pd.DataFrame
    returns_frame: pd.DataFrame
    current_weights: dict[str, float]
    nature_weights: dict[str, float]
    bucket_weights: dict[str, float]
    portfolio_value: float
    correlations: dict[str, float]
    selected_categories: tuple[str, ...]
    include_fee_instruments: bool
    liquidita: float
    concentration_severity: float = 1.0
    blocked_buckets_quota: frozenset[str] = frozenset()
    instrument_bucket_exposures: dict[str, dict[str, float]] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Impostazioni e metadati
# --------------------------------------------------------------------------- #

def ensure_sator_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    merged = _deep_merge(DEFAULT_SATOR_SETTINGS, dict((settings or {}).get("sator", {}) or {}))
    merged["budget_preset"] = _safe_float(merged.get("budget_preset"), 900.0)
    merged["default_budget"] = _safe_float(merged.get("default_budget"), merged["budget_preset"])
    merged["max_share_per_line"] = float(min(1.0, max(0.05, _safe_float(merged.get("max_share_per_line"), 0.35))))
    raw = merged.get("investible_categories", SATOR_INVESTIBLE_CATEGORIES)
    if not isinstance(raw, (list, tuple, set)):
        raw = SATOR_INVESTIBLE_CATEGORIES
    norm = [str(c or "").strip().upper() for c in raw if str(c or "").strip().upper() in SATOR_INVESTIBLE_CATEGORIES]
    merged["investible_categories"] = tuple(norm or SATOR_INVESTIBLE_CATEGORIES)

    caps_raw = merged.get("concentration_caps", {}) or {}
    caps = {
        nature: float(min(1.0, max(0.01, _safe_float(caps_raw.get(nature), CAP_MORBIDO_NATURA[nature]))))
        for nature in CAP_MORBIDO_NATURA
    }
    merged["concentration_caps"] = caps

    raw_quotas = merged.get("instrument_quotas", {}) or {}
    norm_quotas: dict[str, dict[str, float]] = {"Core": {}, "Difensivo": {}, "Satellite": {}}
    if isinstance(raw_quotas, dict):
        for bucket in ("Core", "Difensivo", "Satellite"):
            bucket_raw = raw_quotas.get(bucket, {})
            if isinstance(bucket_raw, dict):
                for ticker, weight in bucket_raw.items():
                    tk = str(ticker or "").strip().upper()
                    w = _safe_float(weight, -1.0)
                    if tk and 0.0 <= w <= 1.0:
                        norm_quotas[bucket][tk] = w
    merged["instrument_quotas"] = norm_quotas
    merged["instrument_quota_tolerance_pp"] = float(
        min(0.20, max(0.0, _safe_float(merged.get("instrument_quota_tolerance_pp"), 0.05)))
    )

    weights_raw = merged.get("score_weights", {}) or {}
    weights = {k: max(0.0, _safe_float(weights_raw.get(k), PESI_DIMENSIONI[k])) for k in PESI_DIMENSIONI}
    weights_total = sum(weights.values())
    merged["score_weights"] = (
        {k: v / weights_total for k, v in weights.items()} if weights_total > 0 else dict(PESI_DIMENSIONI)
    )
    merged["band_tolerance_pp"] = float(min(0.20, max(0.0, _safe_float(merged.get("band_tolerance_pp"), 0.03))))
    merged["deficit_pac_only"] = bool(merged.get("deficit_pac_only", False))
    merged["bucket_first_allocation"] = bool(merged.get("bucket_first_allocation", False))
    return merged


def ensure_sator_metadata(data: dict[str, Any]) -> bool:
    """Garantisce l'esistenza del dizionario sator e dei soli campi NON
    strutturali. Natura, ruolo, gruppo e funzione NON vengono piu' persistiti:
    sono inferiti a runtime, cosi' un miglioramento della classificazione si
    applica subito e non resta congelato in metadati salvati da versioni vecchie.
    """
    changed = False
    instrument_master = data.setdefault("instrument_master", {})
    positions = compute_portfolio_state(data, include_closed=True).get("df", pd.DataFrame())
    held = _tickers_posseduti(positions)
    # I campi di costo (commission_mode, zero_commission, ter, spread_pct) NON
    # sono piu' tra i "non strutturali" seminati qui: si leggono a runtime dai
    # campi arricchimento dello strumento (infer_sator_metadata), cosi' un
    # aggiornamento in Strumenti -> Arricchimento si riflette subito nel
    # punteggio Costo. Restano overridabili a mano solo tramite l'editor
    # universo (flag user_edited), vedi _score_universe.
    non_strutturali = ("active", "state", "pac_enabled")
    for item in data.get("strumenti", []) or []:
        ticker = str(item.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        sator = instrument_master.setdefault(ticker, {}).setdefault("manual_overrides", {}).setdefault("sator", {})
        inferred = infer_sator_metadata(item, ticker in held)
        for key in non_strutturali:
            if sator.get(key) in (None, ""):
                sator[key] = inferred[key]
                changed = True
    return changed


def _meta_strutturale(sator: dict[str, Any], inf: dict[str, Any], key: str) -> str:
    """Campo strutturale: usa il valore salvato SOLO se l'utente l'ha modificato
    esplicitamente dall'editor universo (flag user_edited). Altrimenti vince
    sempre l'inferenza corrente, ignorando eventuali metadati legacy."""
    if bool(sator.get("user_edited")) and sator.get(key) not in (None, ""):
        return str(sator.get(key))
    return str(inf.get(key))


def infer_sator_metadata(item: dict[str, Any], in_portfolio: bool) -> dict[str, Any]:
    ticker = str(item.get("ticker") or "").strip().upper()
    tkl = ticker.split(".")[0].lower()
    name = str(item.get("nome") or ticker).lower()
    category = macro_cat(str(item.get("tipo") or ""))
    nature, role, confidence = "altro", "altro", "bassa"

    def tk_in(*codici: str) -> bool:
        return any(c in tkl for c in codici)

    # Grading confidence a 3 livelli (spec del piano): "alta" SOLO per match
    # esatto su ticker/ISIN via tk_in(...) (registro hardcoded, identificazione
    # precisa); "media" per un match generico su pattern/keyword nel nome
    # (indicativo, non un'identificazione certa); "bassa" per il fallback
    # generico finale. Ogni ramo che in precedenza univa ticker esatto e
    # keyword in una sola condizione OR (stessa confidence per entrambi) e'
    # stato separato in due rami adiacenti - stessa posizione nella catena
    # elif, quindi nessuna modifica alla priorita'/specificita' dei match,
    # solo alla confidence assegnata.
    if category == "GOV":
        nature, role, confidence = "bond_governativo", "bond", "alta"
    elif category == "FND":
        nature, role, confidence = "fondo_pac", "core_difensivo", "media"
    elif tk_in("btc", "ib1t"):
        nature, role, confidence = "criptovalute", "satellite_tematico", "alta"
    elif "bitcoin" in name or "crypto" in name or "criptovalut" in name:
        nature, role, confidence = "criptovalute", "satellite_tematico", "media"
    elif "defence" in name or "defense" in name or "difesa" in name or "military" in name or "aerospace" in name:
        # nessun ticker esatto noto per questo ramo: sempre un match a
        # parole chiave nel nome, mai un'identificazione precisa
        nature, role, confidence = "difesa_sicurezza", "satellite_tematico", "media"
    elif tk_in("xeon", "csh", "ern", "smart"):
        nature, role, confidence = "monetario", "liquidita", "alta"
    elif "money" in name or "overnight" in name or "monetar" in name:
        nature, role, confidence = "monetario", "liquidita", "media"
    elif tk_in("xgdu", "sgld", "gold", "phau", "sgbs"):
        nature, role, confidence = "oro", "oro", "alta"
    elif "gold" in name or "oro " in name or " oro" in name or "physical gold" in name:
        nature, role, confidence = "oro", "oro", "media"
    elif tk_in("xdwh", "hlt", "wely"):
        nature, role, confidence = "healthcare", "satellite_difensivo", "alta"
    elif "health" in name or "salute" in name or "medical" in name:
        nature, role, confidence = "healthcare", "satellite_difensivo", "media"
    elif tk_in("iwqu", "iwfq", "iqsa"):
        nature, role, confidence = "quality_factor", "core_regionale", "alta"
    elif "quality" in name or "qualit" in name:
        nature, role, confidence = "quality_factor", "core_regionale", "media"
    elif tk_in("xdre", "iwda"):
        nature, role, confidence = "real_estate", "satellite_tematico", "alta"
    elif "real estate" in name or "immobil" in name or "reit" in name or "property" in name:
        nature, role, confidence = "real_estate", "satellite_tematico", "media"
    elif tk_in("xaix", "ai4u", "aiq", "rbot", "smh"):
        nature, role, confidence = "tecnologia_ai", "satellite_crescita", "alta"
    elif ("artificial" in name or "intelligence" in name or "big data" in name or "robot" in name
          or "semicond" in name or "information technology" in name):
        nature, role, confidence = "tecnologia_ai", "satellite_crescita", "media"
    elif tk_in("enrg", "wnrg", "ius"):
        nature, role, confidence = "energia", "satellite_tematico", "alta"
    elif "energy" in name or "energia" in name or "oil" in name or "petrol" in name:
        nature, role, confidence = "energia", "satellite_tematico", "media"
    elif tk_in("famamw", "spgp", "gdx"):
        nature, role, confidence = "metalli_miniere", "satellite_tematico", "alta"
    elif "metal" in name or "mining" in name or "miner" in name or "miniere" in name:
        nature, role, confidence = "metalli_miniere", "satellite_tematico", "media"
    elif tk_in("xdbc", "cmod", "icom"):
        nature, role, confidence = "commodities", "satellite_tematico", "alta"
    elif "commodity" in name or "commodities" in name or "materie prime" in name or "broad commodit" in name:
        nature, role, confidence = "commodities", "satellite_tematico", "media"
    elif tk_in("etfmib", "midx"):
        nature, role, confidence = "italia", "satellite_tematico", "alta"
    elif "ftse mib" in name or "italia" in name or "italy" in name or "mib" in name:
        nature, role, confidence = "italia", "satellite_tematico", "media"
    elif tk_in("xbae", "aggh", "vagf", "eunh"):
        nature, role, confidence = "bond_globale", "bond", "alta"
    elif "aggregate" in name or "bond" in name or "obbligaz" in name or "treasury" in name or "govt" in name or "bund" in name:
        # Controllato PRIMA di "emerging": un fondo "EM Bond"/"Emerging
        # Markets Bond" e' prima di tutto un'obbligazione. Fix del bug di
        # specificita' (in precedenza "emerging" vinceva sempre, anche su
        # fondi obbligazionari mercati emergenti).
        nature, role, confidence = "bond_globale", "bond", "media"
    elif tk_in("xmme", "emim", "iemg", "vfem"):
        nature, role, confidence = "azionario_emergenti", "core_regionale", "alta"
    elif "emerging" in name or "emergenti" in name or "emerg" in name:
        nature, role, confidence = "azionario_emergenti", "core_regionale", "media"
    elif tk_in("swda", "vwce", "iwda", "sppw", "vwrl", "eunl"):
        nature, role, confidence = "azionario_globale_core", "core_globale", "alta"
    elif ("world" in name or "all-world" in name or "all world" in name or "global" in name
          or "msci acwi" in name or "developed" in name):
        nature, role, confidence = "azionario_globale_core", "core_globale", "media"
    elif any(tok in name for tok in ("india", "china", "cina", "brazil", "brasile", "japan", "giappone", "smallcap", "small cap", "ex mega", "single country")):
        # Paese singolo o segmento equity specifico (small cap, ex-mega-cap):
        # non e' "core globale" solo perche' e' azionario - e' una scommessa
        # di stile/paese, va in Satellite.
        nature, role, confidence = "azionario_paese_singolo", "satellite_tematico", "media"
    elif category in ("ETF", "ETC"):
        # non riconosciuto: resta "altro" e finisce in un gruppo dedicato, NON
        # forzato nel core globale (era questo a falsare i confronti)
        nature, role, confidence = "altro", "satellite_tematico", "bassa"

    # Costo: letto dai campi arricchimento dello strumento (tab Strumenti ->
    # Arricchimento), non da un editor separato — cosi' il flusso sidebar/
    # form_server (quello effettivamente usato) alimenta subito il fattore
    # Costo senza passare da nessuna pagina Streamlit dedicata.
    zero_commission = str(item.get("zero_commissioni") or "").strip().lower() in ("true", "si", "sì", "1", "yes")

    return {
        "active": True,
        "state": "in_portafoglio" if in_portfolio else "watchlist",
        "nature": nature,
        "role": role,
        "confidence": confidence,
        "comparison_group": _infer_comparison_group(nature, role, ticker, name),
        "function_label": _infer_function_label(nature, role),
        "commission_mode": "zero_commissioni" if zero_commission else "standard",
        "pac_enabled": category != "GOV",
        "zero_commission": zero_commission,
        "ter": _parse_it_pct(item.get("ter")),
        "spread_pct": _parse_it_pct(item.get("spread_pct")),
    }


def _resolve_instrument_meta(data: dict[str, Any], item: dict[str, Any], in_portfolio: bool, key: str) -> str:
    """Nucleo condiviso di resolve_instrument_nature/resolve_instrument_role:
    risolve un singolo campo strutturale (auto + override manuale) per uno
    strumento, stesso pattern gia' usato internamente da
    compute_instrument_buckets/compute_watchlist_reminders."""
    ticker = str(item.get("ticker") or "").strip().upper()
    master = data.get("instrument_master", {}) if isinstance(data.get("instrument_master", {}), dict) else {}
    sator = ((master.get(ticker, {}).get("manual_overrides") or {}).get("sator") or {})
    inf = infer_sator_metadata(item, in_portfolio)
    return _meta_strutturale(sator, inf, key)


def resolve_instrument_nature(data: dict[str, Any], item: dict[str, Any], in_portfolio: bool) -> str:
    """Nature SATOR risolta per un singolo strumento (auto + override manuale),
    stesso pattern gia' usato internamente da compute_instrument_buckets/
    compute_watchlist_reminders. Punto di accesso pubblico per la UI, che non
    deve importare _meta_strutturale (privata) ne' reimplementare la
    risoluzione master -> manual_overrides.sator -> infer_sator_metadata."""
    return _resolve_instrument_meta(data, item, in_portfolio, "nature")


def resolve_instrument_role(data: dict[str, Any], item: dict[str, Any], in_portfolio: bool) -> str:
    """Ruolo SATOR risolto per un singolo strumento (auto + override manuale),
    stesso pattern di resolve_instrument_nature. Punto di accesso pubblico per
    la UI, che non deve importare _meta_strutturale (privata) ne' reimplementare
    la risoluzione master -> manual_overrides.sator -> infer_sator_metadata."""
    return _resolve_instrument_meta(data, item, in_portfolio, "role")


def resolve_instrument_bucket_exposure(data: dict[str, Any], item: dict[str, Any], in_portfolio: bool) -> dict[str, float]:
    """Esposizione effettiva ai bucket Core/Difensivo/Satellite per uno
    strumento (auto + override manuale). Default (nessun override): 100%
    nel bucket primario derivato da resolve_instrument_role - identico al
    comportamento di compute_instrument_buckets per chi non usa la
    feature. bucket_exposure_user_edited e' un flag indipendente da
    user_edited (ruolo) e benchmark_user_edited: mai condiviso, per non
    ripetere il bug del sotto-progetto 1 dove un flag condiviso riattivava
    campi dormienti non richiesti."""
    ticker = str(item.get("ticker") or "").strip().upper()
    master = data.get("instrument_master", {}) if isinstance(data.get("instrument_master", {}), dict) else {}
    sator = ((master.get(ticker, {}).get("manual_overrides") or {}).get("sator") or {})
    override = sator.get("bucket_exposure")
    if bool(sator.get("bucket_exposure_user_edited")) and isinstance(override, dict) and override:
        cleaned = {
            k: max(0.0, _safe_float(v, 0.0))
            for k, v in override.items()
            if k in ("Core", "Difensivo", "Satellite")
        }
        total = sum(cleaned.values())
        if cleaned and abs(total - 1.0) < 1e-6:
            return cleaned
    role = resolve_instrument_role(data, item, in_portfolio)
    return {_role_bucket(role): 1.0}


def resolve_instrument_no_sell(data: dict[str, Any], ticker: str) -> bool:
    """Flag NO_SELL/posizione legacy per uno strumento: True solo se
    esplicitamente impostato dall'utente (stesso pattern-guardia di
    resolve_instrument_bucket_exposure — no_sell_user_edited e' un flag
    indipendente, mai condiviso con altri campi di manual_overrides.sator,
    per non ripetere il bug del sotto-progetto 1 dove un flag condiviso
    riattivava valori dormienti di un campo diverso). Nessun impatto sul
    motore SATOR: solo lettura per la UI (vedi
    compute_instrument_operational_status)."""
    ticker = str(ticker or "").strip().upper()
    master = data.get("instrument_master", {}) if isinstance(data.get("instrument_master", {}), dict) else {}
    sator = ((master.get(ticker, {}).get("manual_overrides") or {}).get("sator") or {})
    if not bool(sator.get("no_sell_user_edited")):
        return False
    return bool(sator.get("no_sell"))


def apply_no_sell_from_form(
    data: dict[str, Any], form_data: dict[str, Any], *, allowed_tickers: frozenset[str] | set[str],
) -> bool:
    """Legge i campi 'no_sell_<TICKER>' da un form POST e scrive
    l'override SOLO per i ticker in `allowed_tickers` - l'insieme esatto
    dei ticker per cui il chiamante ha effettivamente renderizzato una
    checkbox NO_SELL in QUESTA pagina, in QUESTO submit (su
    /quote-interne: le chiavi di quotas_json, cioe' esattamente i ticker
    del ciclo che genera sia l'input quota sia la checkbox NO_SELL - vedi
    _render_quote_interne_page). Bug reale corretto qui: iterare su TUTTO
    `data["strumenti"]` (catalogo intero, inclusi strumenti chiusi, mai
    posseduti, o esclusi dal toggle 'Escludi BTP/GOV' in quel momento)
    trattava l'assenza del campo per un ticker MAI mostrato in pagina come
    uno spegnimento esplicito dell'utente (checkbox non spuntata = campo
    assente, semantica corretta SOLO per ticker che erano davvero in
    pagina) - cancellando silenziosamente un NO_SELL=True impostato altrove
    (es. Strumenti->Arricchimento) ad ogni submit del form quote, anche
    senza che l'utente avesse mai visto quel ticker. Per un ticker in
    allowed_tickers, checkbox non spuntata = campo assente conta comunque
    come no_sell=False esplicito (submit completo, non incrementale, per
    i soli ticker ammessi). Muta `data` in place, non chiama save_data.
    Ritorna True se ha scritto qualcosa."""
    strumenti_by_ticker = {
        str(s.get("ticker") or "").strip().upper(): s
        for s in (data.get("strumenti") or [])
        if str(s.get("ticker") or "").strip()
    }
    allowed_upper = {str(t or "").strip().upper() for t in allowed_tickers}
    changed_any = False
    for ticker in strumenti_by_ticker:
        if ticker not in allowed_upper:
            continue
        submitted = bool(form_data.get(f"no_sell_{ticker}"))
        current = resolve_instrument_no_sell(data, ticker)
        if submitted == current:
            continue
        master = data.setdefault("instrument_master", {})
        entry = master.setdefault(ticker, {})
        overrides = entry.setdefault("manual_overrides", {}).setdefault("sator", {})
        overrides["no_sell"] = submitted
        overrides["no_sell_user_edited"] = True
        changed_any = True
    return changed_any


def apply_classification_override(
    data: dict[str, Any], strumento: dict[str, Any], *,
    role_val: str, benchmark_code_val: str, benchmark_label_val: str,
) -> bool:
    """Scrive l'override ruolo/benchmark per uno strumento se e solo se
    differisce dal valore attualmente risolto — logica estratta invariata
    dal ramo 'salva_classificazione' di ui/form_server/strumenti.py
    (sotto-progetto 3), ora condivisa da /strumenti e /quote-interne. Muta
    `data` in place, non chiama save_data: il chiamante decide quando
    persistere (una volta per richiesta, anche con piu' righe in batch).
    Ritorna True se ha scritto qualcosa."""
    from core.benchmark_registry import resolve_instrument_benchmark

    ticker = str(strumento.get("ticker") or "").strip()
    if not ticker:
        return False

    role_val = str(role_val or "").strip()
    benchmark_code_val = str(benchmark_code_val or "").strip()
    benchmark_label_val = str(benchmark_label_val or "").strip()

    master_all = data.get("instrument_master", {})
    master_all = master_all if isinstance(master_all, dict) else {}
    existing_entry = master_all.get(ticker, {})
    existing_entry = existing_entry if isinstance(existing_entry, dict) else {}

    current_role = resolve_instrument_role(data, strumento, True)
    current_bm = resolve_instrument_benchmark(strumento, master_entry=existing_entry, prefer_master=True)

    # Ruolo: validato contro SATOR_ROLE_VALUES prima di considerarlo un
    # cambiamento reale - un valore sconosciuto (POST malformato/manomesso)
    # non deve mai finire scritto verbatim in produzione: resta un no-op
    # sicuro sul campo ruolo, esattamente come se non fosse cambiato.
    role_changed = role_val in SATOR_ROLE_VALUES and role_val != current_role
    benchmark_submitted = bool(benchmark_code_val or benchmark_label_val)
    benchmark_changed = benchmark_submitted and (
        benchmark_code_val != (current_bm.ticker or "")
        or benchmark_label_val != (current_bm.label or "")
    )

    if not (role_changed or benchmark_changed):
        return False

    master = data.setdefault("instrument_master", {})
    entry = master.setdefault(ticker, {})
    overrides = entry.setdefault("manual_overrides", {}).setdefault("sator", {})
    if role_changed:
        overrides["role"] = role_val
        overrides["user_edited"] = True
        # nature/comparison_group/function_label sono SEMPRE derivati dal
        # ruolo risolto, non editabili da questo form: rimuove eventuali
        # chiavi legacy dormienti nello stesso dizionario (mai scritte da
        # qui, ma potenzialmente presenti da un meccanismo precedente)
        # PRIMA di alzare user_edited, cosi' il flag condiviso di
        # _meta_strutturale non le riattiva mai in modo silenzioso (bug
        # reale verificato su dati reali: salvare solo il ruolo di uno
        # strumento riattivava una 'nature' dormiente sbagliata,
        # cambiandone icona e cap).
        overrides.pop("nature", None)
        overrides.pop("comparison_group", None)
        overrides.pop("function_label", None)
    if benchmark_changed:
        overrides["benchmark_code"] = benchmark_code_val or None
        overrides["benchmark_label"] = benchmark_label_val or None
        overrides["benchmark_user_edited"] = True
    return True


def apply_bucket_exposure_override(
    data: dict[str, Any], strumento: dict[str, Any], submitted: dict[str, float],
) -> tuple[bool, str | None]:
    """Valida (somma=100%, tolleranza 1e-6) e scrive bucket_exposure se
    cambiato — logica estratta invariata dal ramo 'salva_bucket_exposure' di
    ui/form_server/strumenti.py (sotto-progetto 3), ora condivisa da
    /strumenti e /quote-interne. Muta `data` in place, non chiama
    save_data. Ritorna (scritto, messaggio_errore): messaggio_errore non
    None se la somma non torna, e in quel caso scritto e' sempre False — la
    riga va scartata dal chiamante, non l'intera richiesta (diverso dal
    ramo originale, pensato per un solo ticker per volta)."""
    ticker = str(strumento.get("ticker") or "").strip()
    if not ticker:
        return False, "Ticker non specificato."

    cleaned = {
        "Core": max(0.0, _safe_float(submitted.get("Core"), 0.0)),
        "Difensivo": max(0.0, _safe_float(submitted.get("Difensivo"), 0.0)),
        "Satellite": max(0.0, _safe_float(submitted.get("Satellite"), 0.0)),
    }
    total = sum(cleaned.values())
    if abs(total - 1.0) >= 1e-6:
        return False, "Le percentuali devono sommare a 100% - modifica non salvata."

    current_exposure = resolve_instrument_bucket_exposure(data, strumento, True)
    changed = any(
        abs(cleaned.get(b, 0.0) - current_exposure.get(b, 0.0)) > 1e-6
        for b in ("Core", "Difensivo", "Satellite")
    )
    if not changed:
        return False, None

    master = data.setdefault("instrument_master", {})
    entry = master.setdefault(ticker, {})
    overrides = entry.setdefault("manual_overrides", {}).setdefault("sator", {})
    overrides["bucket_exposure"] = cleaned
    overrides["bucket_exposure_user_edited"] = True
    return True, None


# --------------------------------------------------------------------------- #
# Editor universo (metadati modificabili dall'utente)
# --------------------------------------------------------------------------- #

def build_sator_universe_editor_frame(data: dict[str, Any]) -> pd.DataFrame:
    ensure_sator_metadata(data)
    positions = compute_portfolio_state(data, include_closed=True).get("df", pd.DataFrame())
    held = _tickers_posseduti(positions)
    master = data.get("instrument_master", {}) if isinstance(data.get("instrument_master", {}), dict) else {}
    rows = []
    for item in data.get("strumenti", []) or []:
        ticker = str(item.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        # solo l'universo investibile da SATOR: niente BTP (GOV) ne' fondi (FND)
        if macro_cat(str(item.get("tipo") or "")) not in SATOR_INVESTIBLE_CATEGORIES:
            continue
        sator = ((master.get(ticker, {}).get("manual_overrides") or {}).get("sator") or {})
        inf = infer_sator_metadata(item, ticker in held)
        zero = bool(sator.get("zero_commission", inf["zero_commission"])) or \
            str(sator.get("commission_mode") or inf["commission_mode"]) == "zero_commissioni"
        rows.append({
            "Ticker": ticker,
            "Nome": item.get("nome", ticker),
            "Attivo SATOR": bool(sator.get("active", inf["active"])),
            "Stato": _resolve_sator_state(sator.get("state"), inf["state"]),
            "Natura": _meta_strutturale(sator, inf, "nature"),
            "Ruolo": _meta_strutturale(sator, inf, "role"),
            "Zero commissioni": zero,
            "TER %": round(_safe_float(sator.get("ter", inf["ter"]), 0.0) * 100.0, 3),
            "Spread %": round(_safe_float(sator.get("spread_pct", inf["spread_pct"]), 0.0) * 100.0, 3),
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("Ticker").reset_index(drop=True)


def apply_sator_universe_editor_frame(data: dict[str, Any], editor_df: pd.DataFrame) -> int:
    if editor_df is None or editor_df.empty:
        return 0
    master = data.setdefault("instrument_master", {})
    changed = 0
    for _, row in editor_df.iterrows():
        ticker = str(row.get("Ticker") or "").strip().upper()
        if not ticker:
            continue
        sator = master.setdefault(ticker, {}).setdefault("manual_overrides", {}).setdefault("sator", {})
        nature = str(row.get("Natura") or "").strip() or "altro"
        role = _coerce_choice(row.get("Ruolo"), SATOR_ROLE_VALUES, "altro")
        zero = bool(row.get("Zero commissioni", False))
        # gruppo e funzione sono DERIVATI da natura/ruolo: non si chiedono all'utente
        payload = {
            "active": bool(row.get("Attivo SATOR", True)),
            "state": _resolve_sator_state(row.get("Stato"), "watchlist"),
            "nature": nature,
            "role": role,
            "comparison_group": _infer_comparison_group(nature, role, ticker, str(row.get("Nome") or "")),
            "function_label": _infer_function_label(nature, role),
            # le commissioni si riducono a: zero, oppure no (e il costo e' nel TER)
            "commission_mode": "zero_commissioni" if zero else "standard",
            "pac_enabled": True,
            "zero_commission": zero,
            "ter": round(_safe_float(row.get("TER %"), 0.0) / 100.0, 6),
            "spread_pct": round(_safe_float(row.get("Spread %"), 0.0) / 100.0, 6),
            "user_edited": True,
        }
        if sator != payload:
            master[ticker]["manual_overrides"]["sator"] = payload
            changed += 1
    return changed


# --------------------------------------------------------------------------- #
# Recupero automatico dei costi (TER) dalla rete
# --------------------------------------------------------------------------- #

def _ter_from_info(info: dict) -> float | None:
    """Estrae il TER (frazione) dai campi Yahoo. Normalizza % vs frazione."""
    for key in ("annualReportExpenseRatio", "netExpenseRatio", "expenseRatio", "grossExpenseRatio"):
        raw = info.get(key)
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if val <= 0:
            continue
        frazione = val / 100.0 if val > 0.03 else val   # normalizza % vs frazione
        if 0.0 < frazione < 0.03:
            return round(frazione, 6)
    return None


def _spread_from_info(info: dict) -> float | None:
    """Spread denaro-lettera (frazione) da bid/ask Yahoo, con filtro di sanita'.

    Accettato SOLO a mercato in contrattazione (i bid/ask di fine seduta sono
    larghi e stantii) e solo se plausibile (<= 0,6%). Sopra quella soglia, o a
    mercato chiuso, restituisce None: meglio nessun valore che uno inquinato.
    """
    if str(info.get("marketState") or "").upper() != "REGULAR":
        return None
    try:
        bid = float(info.get("bid"))
        ask = float(info.get("ask"))
    except (TypeError, ValueError):
        return None
    if not (ask >= bid > 0):
        return None
    mid = (ask + bid) / 2.0
    spread = (ask - bid) / mid if mid > 0 else None
    if spread is not None and 0.0 < spread <= 0.006:
        return round(spread, 6)
    return None


def _fetch_costs_for_symbol(symbol: str) -> dict[str, float | None]:
    """Una sola chiamata Yahoo per TER e spread. Entrambi possono essere None."""
    symbol = str(symbol or "").strip()
    out: dict[str, float | None] = {"ter": None, "spread": None}
    if not symbol:
        return out
    try:
        import yfinance as yf
    except Exception:
        return out
    try:
        tk = yf.Ticker(symbol)
        info = tk.get_info() if hasattr(tk, "get_info") else getattr(tk, "info", None)
    except Exception:
        info = None
    if not isinstance(info, dict):
        return out
    out["ter"] = _ter_from_info(info)
    out["spread"] = _spread_from_info(info)
    return out


def fetch_sator_costs_from_web(data: dict[str, Any], *, only_missing: bool = True) -> dict[str, list[str]]:
    """Scarica da Yahoo TER e (a mercato aperto) spread, salvandoli nei metadati.

    Il TER e' un dato stabile; lo spread viene scritto solo quando Yahoo lo
    fornisce credibile (mercato in contrattazione e valore plausibile). In tutti
    gli altri casi lo spread resta com'era. Restituisce l'esito per la UI.
    """
    ensure_sator_metadata(data)
    master = data.setdefault("instrument_master", {})
    ter_trovati: list[str] = []
    spread_trovati: list[str] = []
    non_trovati: list[str] = []
    saltati: list[str] = []
    for item in data.get("strumenti", []) or []:
        ticker = str(item.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        sator = master.setdefault(ticker, {}).setdefault("manual_overrides", {}).setdefault("sator", {})
        inferred = infer_sator_metadata(item, False)
        if not bool(sator.get("active", inferred["active"])):
            continue
        ter_gia = _safe_float(sator.get("ter"), 0.0) > 0
        spread_gia = _safe_float(sator.get("spread_pct"), 0.0) > 0
        if only_missing and ter_gia and spread_gia:
            saltati.append(ticker)
            continue
        costi = _fetch_costs_for_symbol(ticker)
        if costi["ter"] is not None and (not only_missing or not ter_gia):
            sator["ter"] = costi["ter"]
            ter_trovati.append(f"{ticker} ({costi['ter'] * 100:.2f}%)")
        if costi["spread"] is not None and (not only_missing or not spread_gia):
            sator["spread_pct"] = costi["spread"]
            spread_trovati.append(f"{ticker} ({costi['spread'] * 100:.3f}%)")
        if costi["ter"] is None and costi["spread"] is None:
            non_trovati.append(ticker)
    return {
        "ter_trovati": ter_trovati,
        "spread_trovati": spread_trovati,
        "non_trovati": non_trovati,
        "saltati": saltati,
    }



def run_sator_analysis(
    data: dict[str, Any],
    settings: dict[str, Any],
    *,
    budget: float,
    selected_categories: list[str] | None = None,
    include_fee_instruments: bool = True,
    concentration_severity: float = 1.0,
) -> dict[str, Any]:
    ensure_sator_metadata(data)
    cfg = ensure_sator_settings(settings)
    budget = max(0.0, _safe_float(budget, cfg["default_budget"]))
    concentration_severity = float(min(2.0, max(0.0, _safe_float(concentration_severity, 1.0))))

    state = compute_portfolio_state(data, include_closed=True)
    state_df = state.get("df", pd.DataFrame())
    if isinstance(data.get("_positions_df"), pd.DataFrame) and not data["_positions_df"].empty:
        state_df = data["_positions_df"].copy()
    liquidita = _safe_float(state.get("liquidita"), 0.0)
    if liquidita <= 0 and data.get("_liquidita") is not None:
        liquidita = _safe_float(data.get("_liquidita"), 0.0)
    price_frame = build_expanded_price_frame(data)
    price_frame = price_frame if isinstance(price_frame, pd.DataFrame) else pd.DataFrame()
    returns_frame = _build_returns_frame(price_frame)

    runtime = tuple(str(c or "").strip().upper() for c in (selected_categories or ()))
    allowed = tuple(c for c in runtime if c in cfg["investible_categories"]) or tuple(cfg["investible_categories"])

    current_weights = _compute_current_weights(state_df)
    nature_weights = _compute_nature_weights(data, state_df, current_weights)
    bucket_weights = _compute_bucket_weights(data, state_df, current_weights, use_fractional_exposure=True)
    held_tickers = _tickers_posseduti(state_df)
    instrument_buckets = compute_instrument_buckets(data, held_tickers)
    instrument_bucket_exposures = compute_instrument_bucket_exposures(data, held_tickers=None)
    quota_status = _compute_instrument_quota_status(
        instrument_buckets, current_weights, bucket_weights, cfg["instrument_quotas"],
    )
    blocked_buckets_quota = frozenset(b for b, s in quota_status.items() if not s["valid"])
    nature_weights_excl: dict[str, float] | None = None
    bucket_weights_excl: dict[str, float] | None = None
    if cfg["deficit_pac_only"]:
        held_per_alerts = _tickers_posseduti(state_df)
        exclude_per_alerts = _non_pac_held_tickers(data, held_per_alerts)
        if exclude_per_alerts:
            nature_weights_excl = _compute_nature_weights(data, state_df, current_weights, exclude_tickers=exclude_per_alerts)
            bucket_weights_excl = _compute_bucket_weights(data, state_df, current_weights, exclude_tickers=exclude_per_alerts)
    portfolio_value = _compute_portfolio_value(state_df)
    portfolio_returns = _build_portfolio_return_series(returns_frame, state_df, current_weights)
    correlations = _compute_correlations(returns_frame, portfolio_returns)

    ctx = SatorContext(
        data=data, settings=settings, budget=budget,
        state_df=state_df if isinstance(state_df, pd.DataFrame) else pd.DataFrame(),
        price_frame=price_frame, returns_frame=returns_frame,
        current_weights=current_weights, nature_weights=nature_weights,
        bucket_weights=bucket_weights, portfolio_value=portfolio_value,
        correlations=correlations, selected_categories=allowed,
        include_fee_instruments=bool(include_fee_instruments), liquidita=liquidita,
        concentration_severity=concentration_severity,
        blocked_buckets_quota=blocked_buckets_quota,
        instrument_bucket_exposures=instrument_bucket_exposures,
    )

    ranking = _score_universe(ctx, cfg)
    alerts = _build_alerts(
        ranking, nature_weights, ctx.bucket_weights, settings.get("portfolio_objective", {}),
        cfg.get("concentration_caps", CAP_MORBIDO_NATURA),
        nature_weights_excl=nature_weights_excl, bucket_weights_excl=bucket_weights_excl,
    )
    summary = {
        "budget": budget,
        "liquidita_corrente": liquidita,
        "investible_categories": list(allowed),
        "include_fee_instruments": bool(include_fee_instruments),
        "universe_count": int(len(ranking)),
        "watchlist_count": int((ranking["state"] == "watchlist").sum()) if not ranking.empty else 0,
        "storico_incompleto": int((~ranking["storico_sufficiente"]).sum()) if not ranking.empty else 0,
    }
    return {
        "summary": summary, "ranking": ranking, "alerts": alerts, "scenarios": {},
        "sator_settings": cfg, "returns_frame": returns_frame, "quota_status": quota_status,
    }


def _score_universe(ctx: SatorContext, cfg: dict[str, Any]) -> pd.DataFrame:
    master = ctx.data.get("instrument_master", {}) if isinstance(ctx.data.get("instrument_master", {}), dict) else {}
    positions_map = {}
    if ctx.state_df is not None and not ctx.state_df.empty and "Ticker" in ctx.state_df.columns:
        positions_map = ctx.state_df.set_index("Ticker").to_dict(orient="index")
    latest = _latest_prices(ctx.price_frame)

    all_tickers = [
        str(item.get("ticker") or "").strip().upper()
        for item in ctx.data.get("strumenti", []) or []
        if item.get("ticker")
    ]
    calc_settings = ctx.settings.get("calculations_metrics", {}) if isinstance(ctx.settings, dict) else {}
    rolling_window = int(min(3650.0, max(2.0, _safe_float(calc_settings.get("rolling_window_days"), 90.0))))
    metrics_batch = _compute_all_metrics_batch(all_tickers, ctx.price_frame, rolling_window)

    rows = []
    for item in ctx.data.get("strumenti", []) or []:
        ticker = str(item.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        sator = ((master.get(ticker, {}).get("manual_overrides") or {}).get("sator") or {})
        inf = infer_sator_metadata(item, ticker in positions_map)
        if not bool(sator.get("active", inf["active"])):
            continue
        state = _resolve_sator_state(sator.get("state"), inf["state"])
        if state == "escluso":
            continue
        category = macro_cat(str(item.get("tipo") or ""))
        if category not in ctx.selected_categories:
            continue
        if not ctx.include_fee_instruments and not bool(inf.get("zero_commission")):
            continue
        if state == "watchlist" and not cfg.get("include_watchlist", True):
            continue
        in_ptf = _safe_float(positions_map.get(ticker, {}).get("Quote"), 0.0) > QTY_ZERO_EPS
        if in_ptf and not cfg.get("include_portfolio", True):
            continue

        unit_price = _safe_float(item.get("prezzo"), latest.get(ticker, 0.0))
        if unit_price <= 0:
            continue

        role_for_bucket = _meta_strutturale(sator, inf, "role")
        exposure_for_eligibility = ctx.instrument_bucket_exposures.get(ticker) or {_role_bucket(role_for_bucket): 1.0}
        if all(bucket in ctx.blocked_buckets_quota for bucket, frac in exposure_for_eligibility.items() if frac > 0):
            continue

        nature = _meta_strutturale(sator, inf, "nature")
        metrics = metrics_batch.get(ticker, {k: np.nan for k in ("ret_1m", "ret_3m", "ret_6m", "ret_12m", "vol", "drawdown", "rend_vol", "n_punti")})
        peso_natura = ctx.nature_weights.get(nature, 0.0)
        rows.append({
            "ticker": ticker,
            "name": item.get("nome", ticker),
            "isin": item.get("isin"),
            "category": category,
            "state": state,
            "in_portfolio": in_ptf,
            "nature": nature,
            "role": _meta_strutturale(sator, inf, "role"),
            "comparison_group": _meta_strutturale(sator, inf, "comparison_group"),
            "function_label": _meta_strutturale(sator, inf, "function_label"),
            # Costo: SEMPRE dal valore live (Strumenti -> Arricchimento), mai
            # dal vecchio editor universo dormiente — anche se in passato uno
            # strumento e' stato marcato user_edited=True da li', quel dato e'
            # ormai fuori sincrono con l'unica fonte che l'utente aggiorna.
            "commission_mode": inf["commission_mode"],
            "pac_enabled": bool(sator.get("pac_enabled", inf["pac_enabled"])),
            "zero_commission": inf["zero_commission"],
            "ter": inf["ter"],
            "spread_pct": inf["spread_pct"],
            "current_qty": _safe_float(positions_map.get(ticker, {}).get("Quote"), 0.0),
            "current_weight": ctx.current_weights.get(ticker, 0.0),
            "nature_weight": peso_natura,
            "unit_price": unit_price,
            "portfolio_correlation": ctx.correlations.get(ticker, np.nan),
            **metrics,
        })

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["_sev"] = float(getattr(ctx, "concentration_severity", 1.0))

    caps = cfg.get("concentration_caps", CAP_MORBIDO_NATURA)
    portfolio_objective = ctx.settings.get("portfolio_objective", {}) if isinstance(ctx.settings, dict) else {}
    df["strategic_fit"] = df.apply(lambda r: _score_fit(r, caps, ctx.bucket_weights, portfolio_objective), axis=1)
    df["tactical_momentum"] = df.apply(_score_momentum, axis=1)
    df["risk_efficiency"] = df.apply(_score_risk, axis=1)
    df["diversification_benefit"] = df.apply(lambda r: _score_diversification(r, caps), axis=1)
    df["cost_efficiency"] = df.apply(lambda r: _score_cost(r, ctx.budget), axis=1)

    # Voto = somma pesata ESCLUSIVAMENTE dei cinque fattori mostrati in tabella.
    # Nessun termine nascosto: cosi' il numero che l'utente legge coincide sempre
    # con le cinque barre. La concentrazione c'e' eccome, ma resta VISIBILE, perche'
    # gia' incorporata in Fit (termine sulla linea sovrappesata) e in
    # Diversificazione (s_linea): non va sottratta una seconda volta al totale.
    weights = cfg.get("score_weights", PESI_DIMENSIONI)
    df["score_finale"] = sum(df[k] * _safe_float(weights.get(k), PESI_DIMENSIONI[k]) for k in PESI_DIMENSIONI).clip(0.0, 1.0)
    df["voto"] = (1.0 + df["score_finale"] * 9.0).round(1)
    df["storico_sufficiente"] = df["n_punti"] >= max(MIN_PUNTI_STORICO, rolling_window)
    df["_bucket"] = df["role"].astype(str).map(_role_bucket)
    df["_bucket_exposure"] = df["ticker"].map(lambda tk: ctx.instrument_bucket_exposures.get(tk) or {})
    df["bucket_weight"] = df["_bucket"].map(lambda b: _safe_float(ctx.bucket_weights.get(str(b)), 0.0))
    df["bucket_target"] = df["_bucket"].map(
        lambda b: _safe_float(portfolio_objective.get(_BUCKET_TO_OBJECTIVE_KEY.get(str(b), ""), 0.0), 0.0)
    )
    df["nature_cap"] = df["nature"].astype(str).map(lambda n: _safe_float(caps.get(n, CAP_MORBIDO_DEFAULT), CAP_MORBIDO_DEFAULT))
    df["portfolio_value"] = float(max(0.0, _safe_float(ctx.portfolio_value, 0.0)))
    df["data_quality_score"] = df["n_punti"].map(_data_quality_score)
    df["data_quality_label"] = df["n_punti"].map(_data_quality_label)

    # classifica unica: lo stesso punteggio che si vede ordina le righe
    df = df.sort_values("score_finale", ascending=False).reset_index(drop=True)
    df["rank_totale"] = df["score_finale"].rank(ascending=False, method="first").astype(int)
    df["rango_gruppo"] = df.groupby("comparison_group")["score_finale"].rank(ascending=False, method="first").astype(int)
    df["challenger_flag"] = np.where(df["in_portfolio"], "Incumbent", "In osservazione")
    df["selection_reason"] = _build_comparative_reasons(df)
    return df


# --------------------------------------------------------------------------- #
# Le cinque dimensioni (scala assoluta 0-1)
# --------------------------------------------------------------------------- #

_BUCKET_TO_OBJECTIVE_KEY = {"Core": "core", "Difensivo": "difensivo", "Satellite": "satellite"}


def _score_fit(
    row: pd.Series,
    caps: dict[str, float] | None = None,
    bucket_weights: dict[str, float] | None = None,
    bucket_targets: dict[str, float] | None = None,
) -> float:
    caps = caps if caps is not None else CAP_MORBIDO_NATURA
    cap = caps.get(str(row.get("nature")), CAP_MORBIDO_DEFAULT)
    riempimento = min(1.5, _safe_float(row.get("nature_weight"), 0.0) / cap) if cap > 0 else 1.0
    concentrazione_linea = min(1.5, _safe_float(row.get("current_weight"), 0.0) / cap) if cap > 0 else 0.0
    score = 0.55 + float(np.clip((1.0 - riempimento) * 0.45, -0.35, 0.30))
    # penalita' per la linea gia' sovrappesata, scalata dalla severita' scelta
    # dall'utente (0 = ignora la concentrazione, 1 = standard, 2 = doppia).
    severita = _safe_float(row.get("_sev"), 1.0)
    score -= float(np.clip(concentrazione_linea * 0.22, 0.0, 0.25)) * severita
    if str(row.get("role")) in {"core_globale", "core_regionale", "core_difensivo"}:
        score += 0.05
    if bucket_weights and bucket_targets:
        exposure = row.get("_bucket_exposure") or {_role_bucket(str(row.get("role"))): 1.0}
        penalty = 0.0
        for bucket, frac in exposure.items():
            if frac <= 0:
                continue
            target = _safe_float(bucket_targets.get(_BUCKET_TO_OBJECTIVE_KEY.get(bucket, ""), 0.0))
            peso_bucket = _safe_float(bucket_weights.get(bucket), 0.0)
            if target > 0:
                eccesso_bucket = max(0.0, (peso_bucket / target) - 1.0)
                penalty += frac * float(np.clip(eccesso_bucket * 0.15, 0.0, 0.20))
        score -= penalty * severita
    return float(np.clip(score, 0.0, 1.0))


def _score_momentum(row: pd.Series) -> float:
    disponibili = {k: row.get(k) for k in PESI_MOMENTUM if pd.notna(row.get(k))}
    if not disponibili:
        return 0.5
    peso_tot = sum(PESI_MOMENTUM[k] for k in disponibili)
    grezzo = sum(disponibili[k] * (PESI_MOMENTUM[k] / peso_tot) for k in disponibili)
    return float(1.0 / (1.0 + math.exp(-6.0 * grezzo)))


def _score_risk(row: pd.Series) -> float:
    vol, dd, rv = row.get("vol"), row.get("drawdown"), row.get("rend_vol")
    s_vol = float(np.clip(1.0 - (vol / 0.35), 0.0, 1.0)) if pd.notna(vol) else 0.5
    s_dd = float(np.clip(1.0 - (abs(dd) / 0.50), 0.0, 1.0)) if pd.notna(dd) else 0.5
    s_rv = float(np.clip(0.5 + rv * 0.30, 0.0, 1.0)) if pd.notna(rv) else 0.5
    return float(np.clip(s_vol * 0.40 + s_dd * 0.30 + s_rv * 0.30, 0.0, 1.0))


def _score_diversification(row: pd.Series, caps: dict[str, float] | None = None) -> float:
    caps = caps if caps is not None else CAP_MORBIDO_NATURA
    cap = caps.get(str(row.get("nature")), CAP_MORBIDO_DEFAULT)
    corr = row.get("portfolio_correlation")
    s_corr = 0.55 if pd.isna(corr) else float(np.clip(0.5 + (0.5 - _safe_float(corr)) * 0.85, 0.0, 1.0))
    s_vuoto = float(np.clip(1.0 - (_safe_float(row.get("nature_weight"), 0.0) / cap), 0.0, 1.0)) if cap > 0 else 0.5
    s_linea = float(np.clip(1.0 - (_safe_float(row.get("current_weight"), 0.0) / cap), 0.0, 1.0)) if cap > 0 else 0.5
    # la correlazione torna il segnale principale della diversificazione; la
    # concentrazione della singola linea resta, ma come fattore secondario.
    return float(np.clip(s_corr * 0.55 + s_vuoto * 0.25 + s_linea * 0.20, 0.0, 1.0))


def _score_cost(row: pd.Series, budget: float) -> float:
    score = 0.55
    if bool(row.get("zero_commission")) or str(row.get("commission_mode")) == "zero_commissioni":
        score += 0.16
    elif str(row.get("commission_mode")) == "standard":
        score -= 0.06
    if bool(row.get("pac_enabled")):
        score += 0.06
    score -= float(np.clip(_safe_float(row.get("ter")) * 25.0, 0.0, 0.20))
    score -= float(np.clip(_safe_float(row.get("spread_pct")) * 30.0, 0.0, 0.12))
    price = _safe_float(row.get("unit_price"))
    if budget > 0 and price > 0:
        rapporto = price / budget
        if rapporto > 0.80:
            score -= 0.12
        elif rapporto < 0.15:
            score += 0.05
    return float(np.clip(score, 0.0, 1.0))


# --------------------------------------------------------------------------- #
# Spiegazioni comparative (il fulcro della trasparenza)
# --------------------------------------------------------------------------- #

def _build_comparative_reasons(df: pd.DataFrame) -> pd.Series:
    reasons = pd.Series("", index=df.index, dtype=object)
    f10 = {k: (1.0 + df[k] * 9.0) for k in PESI_DIMENSIONI}
    for gruppo, idx in df.groupby("comparison_group").groups.items():
        membri = df.loc[idx].sort_values("score_finale", ascending=False)
        vincitore = membri.iloc[0]
        rivale = membri.iloc[1] if len(membri) > 1 else None
        for pos, (i, row) in enumerate(membri.iterrows()):
            if pos == 0:
                reasons.loc[i] = _testo_vincitore(row, rivale, f10, df)
            else:
                reasons.loc[i] = _testo_escluso(row, vincitore, f10, df)
    return reasons


def _fattore_chiave(a_idx: int, b_idx: int, df: pd.DataFrame) -> tuple[str, str]:
    """Fattore che ha spostato di piu' il VOTO a favore di a rispetto a b.

    Si pesa lo scarto di ciascun fattore per il suo peso nel voto (30/25/20/15/10):
    cosi' il fattore indicato e' davvero quello decisivo per la classifica, non
    quello con lo scarto grezzo piu' ampio ma poco rilevante.
    """
    contributo = {
        k: (float(df[k].loc[a_idx]) - float(df[k].loc[b_idx])) * PESI_DIMENSIONI[k]
        for k in PESI_DIMENSIONI
    }
    ordinati = sorted(contributo.items(), key=lambda kv: kv[1], reverse=True)
    primo = ordinati[0][0]
    secondo = ""
    if len(ordinati) > 1 and ordinati[1][1] > 0.01:
        secondo = f", e in seconda battuta su {NOME_FATTORE[ordinati[1][0]]}"
    return primo, secondo


def _testo_vincitore(row: pd.Series, rivale: pd.Series | None, f10: dict[str, pd.Series], df: pd.DataFrame) -> str:
    funzione = str(row.get("function_label") or row.get("comparison_group")).replace("_", " ")
    nota_ingresso = "" if bool(row.get("in_portfolio")) else " (nuovo ingresso rispetto al portafoglio)"
    if rivale is None:
        return f"Per «{funzione}» c'e' un solo candidato: {row['ticker']}, voto {row['voto']:.1f}{nota_ingresso}. Nessun concorrente da battere."
    a, b = row.name, rivale.name
    primo, secondo = _fattore_chiave(a, b, df)
    if abs(float(row["score_finale"]) - float(rivale["score_finale"])) <= 0.03:
        return (f"Per «{funzione}» {row['ticker']} (voto {row['voto']:.1f}) e {rivale['ticker']} (voto {rivale['voto']:.1f}) "
                f"si equivalgono: la scelta tra i due e' indifferente{nota_ingresso}.")
    return (f"Per «{funzione}» vince {row['ticker']} (voto {row['voto']:.1f}) su {rivale['ticker']} (voto {rivale['voto']:.1f}){nota_ingresso}: "
            f"e' avanti soprattutto su {NOME_FATTORE[primo]}{secondo} "
            f"({f10[primo].loc[a]:.1f} contro {f10[primo].loc[b]:.1f} su 10).")


def _testo_escluso(row: pd.Series, vincitore: pd.Series, f10: dict[str, pd.Series], df: pd.DataFrame) -> str:
    funzione = str(row.get("function_label") or row.get("comparison_group")).replace("_", " ")
    a, b = vincitore.name, row.name
    primo, _ = _fattore_chiave(a, b, df)
    return (f"Per «{funzione}» {row['ticker']} (voto {row['voto']:.1f}) cede a {vincitore['ticker']} (voto {vincitore['voto']:.1f}): "
            f"resta sotto soprattutto su {NOME_FATTORE[primo]} "
            f"({f10[primo].loc[b]:.1f} contro {f10[primo].loc[a]:.1f} su 10).")


# --------------------------------------------------------------------------- #
# Tabella per la UI + quote suggerite
# --------------------------------------------------------------------------- #

def build_sator_matrix_frame(
    ranking_df: pd.DataFrame,
    *,
    budget: float,
    manual_alloc: dict[str, int] | None = None,
    max_lines: int = MAX_LINEE_SUGGERITE,
    data: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> pd.DataFrame:
    if ranking_df is None or ranking_df.empty:
        return pd.DataFrame()
    manual_alloc = {str(k): int(v) for k, v in dict(manual_alloc or {}).items() if int(v or 0) > 0}
    work = ranking_df.copy().sort_values("score_finale", ascending=False).reset_index(drop=True)
    # robustezza: se la classifica arriva da una versione precedente del motore,
    # ricostruisci le colonne derivate invece di interrompere il rendering.
    if "rango_gruppo" not in work.columns:
        if "comparison_group" in work.columns:
            work["rango_gruppo"] = work.groupby("comparison_group")["score_finale"].rank(ascending=False, method="first").astype(int)
        else:
            work["rango_gruppo"] = 1

    cfg = ensure_sator_settings(settings) if (data is not None and settings is not None) else None
    # "bucket_weight" NON e' un requisito reale: i pesi sono sempre ricalcolati
    # da zero via _compute_bucket_weights piu' sotto, mai letti da questa colonna.
    bucket_columns_ok = "_bucket" in work.columns and "portfolio_value" in work.columns
    if cfg is not None and cfg["bucket_first_allocation"] and bucket_columns_ok:
        state_df = compute_portfolio_state(data, include_closed=True).get("df", pd.DataFrame())
        current_weights = _compute_current_weights(state_df)
        held = _tickers_posseduti(state_df)
        exclude = _non_pac_held_tickers(data, held) if cfg["deficit_pac_only"] else frozenset()
        bucket_weights = _compute_bucket_weights(
            data, state_df, current_weights, exclude_tickers=exclude, use_fractional_exposure=True,
        )
        objective = settings.get("portfolio_objective", {}) if isinstance(settings, dict) else {}
        bands = _compute_bucket_bands(objective, cfg["band_tolerance_pp"])
        portfolio_value = _safe_float(work["portfolio_value"].iloc[0], 0.0) if "portfolio_value" in work.columns else 0.0
        deficits, blocked = _compute_bucket_deficits(bucket_weights, objective, bands, portfolio_value, budget)
        if not deficits:
            logger.info(
                "SATOR bucket_first_allocation: nessun bucket in deficit, budget resta liquido "
                "(pesi=%s, bande=%s, bloccati=%s)",
                {k: round(v, 4) for k, v in bucket_weights.items()},
                {k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in bands.items()},
                sorted(blocked),
            )
        suggerite = _suggested_quotes_by_bucket(work, budget, deficits, blocked, max_lines_per_bucket=len(work))
    else:
        if cfg is not None and cfg["bucket_first_allocation"] and not bucket_columns_ok:
            missing = [c for c in ("_bucket", "portfolio_value") if c not in work.columns]
            logger.warning(
                "SATOR bucket_first_allocation e' attivo ma la classifica non contiene le colonne "
                "richieste %s (probabile snapshot obsoleto): fallback sull'allocazione greedy legacy",
                missing,
            )
        suggerite = _suggested_quotes(work, budget, max_lines=max_lines)

    ranghi = pd.to_numeric(work["rango_gruppo"], errors="coerce").fillna(0).astype(int).tolist()
    marginal = [
        _compute_marginal_purchase_metrics(work.iloc[i], int(suggerite[i]) * _safe_float(work.iloc[i].get("unit_price"), 0.0))
        for i in range(len(work))
    ]
    decision_amounts = [
        int(suggerite[i]) * _safe_float(work.iloc[i].get("unit_price"), 0.0)
        if int(suggerite[i]) > 0
        else _safe_float(work.iloc[i].get("unit_price"), 0.0)
        for i in range(len(work))
    ]
    decision_scores = [
        _purchase_decision_score(work.iloc[i], decision_amounts[i])
        for i in range(len(work))
    ]
    decision_reasons = [
        _decision_reason(work.iloc[i], decision_amounts[i])
        for i in range(len(work))
    ]

    def _semaforo(i: int) -> str:
        if int(suggerite[i]) > 0:
            return "\U0001F7E2"   # verde: SATOR ne suggerisce l'acquisto
        if ranghi[i] == 1:
            return "\U0001F7E1"   # giallo: migliore della sua funzione, ma non finanziato dal budget
        return "\u26AA"           # bianco: battuto nella sua funzione

    frame = pd.DataFrame({
        "Sel": work["ticker"].astype(str).map(lambda t: t in manual_alloc),
        "Qta": work["ticker"].astype(str).map(lambda t: int(manual_alloc.get(t, 0))),
        "Sem": [_semaforo(i) for i in range(len(work))],
        "Tk": work["ticker"].astype(str),
        "Qp": pd.to_numeric(work["current_qty"], errors="coerce").fillna(0.0).round(2),
        "Px": pd.to_numeric(work["unit_price"], errors="coerce").fillna(0.0).round(2),
        "Fit": (1.0 + pd.to_numeric(work["strategic_fit"], errors="coerce").fillna(0.0) * 9.0).round(1),
        "Mom": (1.0 + pd.to_numeric(work["tactical_momentum"], errors="coerce").fillna(0.0) * 9.0).round(1),
        "Risk": (1.0 + pd.to_numeric(work["risk_efficiency"], errors="coerce").fillna(0.0) * 9.0).round(1),
        "Div": (1.0 + pd.to_numeric(work["diversification_benefit"], errors="coerce").fillna(0.0) * 9.0).round(1),
        "Cost": (1.0 + pd.to_numeric(work["cost_efficiency"], errors="coerce").fillna(0.0) * 9.0).round(1),
        "Voto": pd.to_numeric(work["voto"], errors="coerce").fillna(0.0).round(1),
        "Prio": (1.0 + pd.Series(decision_scores, index=work.index) * 9.0).round(1),
        "Sug": [int(q) for q in suggerite],
        "Gruppo": work["function_label"].astype(str),
        "_ticker": work["ticker"].astype(str),
        "_isin": work.get("isin", pd.Series("", index=work.index)).fillna("").astype(str),
        "_name": work["name"].astype(str),
        "_state": work["state"].astype(str),
        "_price": pd.to_numeric(work["unit_price"], errors="coerce").fillna(0.0),
        "_score": pd.to_numeric(work["score_finale"], errors="coerce").fillna(0.0),
        "_decision_score": pd.Series(decision_scores, index=work.index).round(4),
        "_decision_reason": pd.Series(decision_reasons, index=work.index).astype(str),
        "_fit": pd.to_numeric(work["strategic_fit"], errors="coerce").fillna(0.0),
        "_mom": pd.to_numeric(work["tactical_momentum"], errors="coerce").fillna(0.0),
        "_risk": pd.to_numeric(work["risk_efficiency"], errors="coerce").fillna(0.0),
        "_div": pd.to_numeric(work["diversification_benefit"], errors="coerce").fillna(0.0),
        "_cost": pd.to_numeric(work["cost_efficiency"], errors="coerce").fillna(0.0),
        "_rango_gruppo": pd.to_numeric(work["rango_gruppo"], errors="coerce").fillna(0).astype(int),
        "_bucket": work.get("_bucket", work["role"].astype(str).map(_role_bucket)).astype(str),
        "_funzione": work["function_label"].astype(str),
        "_storico_ok": work["storico_sufficiente"].astype(bool),
        "_why": work["selection_reason"].astype(str),
        "_zero_commission": work["zero_commission"].astype(bool),
        "_portfolio_value": pd.to_numeric(work.get("portfolio_value", pd.Series(0.0, index=work.index)), errors="coerce").fillna(0.0),
        "_bucket_weight": pd.to_numeric(work.get("bucket_weight", pd.Series(0.0, index=work.index)), errors="coerce").fillna(0.0),
        "_nature_weight": pd.to_numeric(work.get("nature_weight", pd.Series(0.0, index=work.index)), errors="coerce").fillna(0.0),
        "_target_improvement_pp": [m["target_improvement_pp"] for m in marginal],
        "_post_bucket_weight": [m["post_bucket_weight"] for m in marginal],
        "_bucket_target": [m["bucket_target"] for m in marginal],
        "_post_nature_weight": [m["post_nature_weight"] for m in marginal],
        "_nature_cap": [m["nature_cap"] for m in marginal],
        "_cap_headroom_after_pp": [m["cap_headroom_after_pp"] for m in marginal],
        "_data_quality_score": pd.to_numeric(work.get("data_quality_score", pd.Series(0.0, index=work.index)), errors="coerce").fillna(0.0),
        "_data_quality_label": work.get("data_quality_label", pd.Series("N/D", index=work.index)).fillna("N/D").astype(str),
    })
    return frame


def _data_quality_score(n_punti: Any) -> float:
    n = max(0.0, _safe_float(n_punti, 0.0))
    if n >= 252:
        return 1.0
    if n >= 126:
        return 0.75
    if n >= MIN_PUNTI_STORICO:
        return 0.55
    if n > 0:
        return 0.25
    return 0.0


def _data_quality_label(n_punti: Any) -> str:
    n = max(0.0, _safe_float(n_punti, 0.0))
    if n >= 252:
        return "Alta"
    if n >= 126:
        return "Buona"
    if n >= MIN_PUNTI_STORICO:
        return "Minima"
    if n > 0:
        return "Debole"
    return "Assente"


def _compute_marginal_purchase_metrics(row: pd.Series, amount: float) -> dict[str, float]:
    """Effetto marginale di una singola riga d'acquisto sul portafoglio attuale.

    Restituisce numeri post-acquisto usati dalla tabella SATOR e dalla
    fotografia salvata: cosi' ranking, storico e dashboard decisionale leggono
    la stessa metrica.
    """
    amount = max(0.0, _safe_float(amount, 0.0))
    portfolio_value = max(0.0, _safe_float(row.get("portfolio_value"), 0.0))
    total_after = portfolio_value + amount
    bucket_weight = max(0.0, _safe_float(row.get("bucket_weight"), 0.0))
    bucket_target = max(0.0, _safe_float(row.get("bucket_target"), 0.0))
    nature_weight = max(0.0, _safe_float(row.get("nature_weight"), 0.0))
    nature_cap = max(0.0, _safe_float(row.get("nature_cap"), CAP_MORBIDO_DEFAULT))

    if total_after > 0:
        post_bucket_weight = ((bucket_weight * portfolio_value) + amount) / total_after
        post_nature_weight = ((nature_weight * portfolio_value) + amount) / total_after
    else:
        post_bucket_weight = bucket_weight
        post_nature_weight = nature_weight

    if bucket_target > 0:
        target_improvement = abs(bucket_weight - bucket_target) - abs(post_bucket_weight - bucket_target)
    else:
        target_improvement = 0.0
    cap_headroom_after = nature_cap - post_nature_weight if nature_cap > 0 else 0.0

    return {
        "target_improvement_pp": round(target_improvement * 100.0, 2),
        "post_bucket_weight": round(post_bucket_weight, 6),
        "bucket_target": round(bucket_target, 6),
        "post_nature_weight": round(post_nature_weight, 6),
        "nature_cap": round(nature_cap, 6),
        "cap_headroom_after_pp": round(cap_headroom_after * 100.0, 2),
    }


def _role_bucket(role: str) -> str:
    role = str(role or "")
    if role in {"core_globale", "core_regionale", "core_difensivo"}:
        return "Core"
    if role in {"liquidita", "bond", "oro", "satellite_difensivo"}:
        return "Difensivo"
    return "Satellite"


def compute_instrument_buckets(data: dict[str, Any], held_tickers: set[str] | None = None) -> dict[str, str]:
    """Ticker -> bucket (Core/Difensivo/Satellite). Unica fonte di verita' del
    ruolo strategico di ogni strumento, usata sia dal motore SATOR sia dalla UI
    di Pianificazione per il confronto col mix attuale.
    """
    master = data.get("instrument_master", {}) if isinstance(data.get("instrument_master", {}), dict) else {}
    out: dict[str, str] = {}
    for item in data.get("strumenti", []) or []:
        ticker = str(item.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        if held_tickers is not None and ticker not in held_tickers:
            continue
        sator = ((master.get(ticker, {}).get("manual_overrides") or {}).get("sator") or {})
        inf = infer_sator_metadata(item, ticker in (held_tickers or set()))
        role = _meta_strutturale(sator, inf, "role")
        out[ticker] = _role_bucket(role)
    return out


def compute_instrument_bucket_exposures(data: dict[str, Any], held_tickers: set[str] | None = None) -> dict[str, dict[str, float]]:
    """Ticker -> {bucket: frazione}. Analoga a compute_instrument_buckets ma
    pesata: per strumenti senza override e' sempre {bucket_primario: 1.0},
    identica informazione di compute_instrument_buckets in forma diversa.
    Usata SOLO dagli aggregatori che sommano controvalori/percentuali tra
    bucket (mix bucket corrente, grafico a ciambella) - il motore SATOR
    continua a usare compute_instrument_buckets (bucket singolo), invariato
    in questo sotto-progetto."""
    out: dict[str, dict[str, float]] = {}
    for item in data.get("strumenti", []) or []:
        ticker = str(item.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        if held_tickers is not None and ticker not in held_tickers:
            continue
        out[ticker] = resolve_instrument_bucket_exposure(data, item, ticker in (held_tickers or set()))
    return out


_BUCKET_OBJECTIVE_KEYS = {"Core": "core", "Difensivo": "difensivo", "Satellite": "satellite"}


def _compute_bucket_bands(objective: dict[str, float], tolerance_pp: float) -> dict[str, dict[str, float]]:
    """Banda [min,max] simmetrica attorno al target di ciascun bucket.

    tolerance_pp e' la meta'-ampiezza in punti percentuali (frazione, es.
    0.03 = 3pp). Stessa idea della soglia oggi hardcoded in
    ui/pages/pianificazione.py::_bucket_scost_severity, ma qui persistita
    e usata nella logica, non solo per colorare la UI.
    """
    bands: dict[str, dict[str, float]] = {}
    for bucket, obj_key in _BUCKET_OBJECTIVE_KEYS.items():
        target = _safe_float(objective.get(obj_key), 0.0)
        bands[bucket] = {
            "target": target,
            "min": max(0.0, target - tolerance_pp),
            "max": min(1.0, target + tolerance_pp),
        }
    return bands


def _compute_bucket_weights(
    data: dict[str, Any],
    state_df: pd.DataFrame,
    current_weights: dict[str, float],
    *,
    exclude_tickers: frozenset[str] = frozenset(),
    use_fractional_exposure: bool = False,
) -> dict[str, float]:
    """Peso per bucket (Core/Difensivo/Satellite) sul totale posseduto.

    use_fractional_exposure: di default False, ossia comportamento storico -
    ogni strumento pesa per intero sul suo bucket primario
    (compute_instrument_buckets), a prescindere da eventuali bucket_exposure
    configurati. run_sator_analysis (Task 1 del piano SATOR, 2026-08-21)
    chiama con use_fractional_exposure=True per far riflettere i pesi di
    bucket l'esposizione frazionata; build_sator_matrix_frame (Task 4 dello
    stesso piano) chiama anch'essa con use_fractional_exposure=True per il
    calcolo del deficit di bucket. compute_current_bucket_mix
    (la vista "mix corrente" mostrata all'utente, non usata per validare/bloccare
    alcunche') passa True, usando compute_instrument_bucket_exposures per far
    contribuire proporzionalmente a piu' bucket uno strumento con
    bucket_exposure configurato (vedi resolve_instrument_bucket_exposure).

    exclude_tickers: se non vuoto, quei ticker vengono semplicemente
    esclusi dal calcolo - il loro valore non conta per nessun bucket e
    NON c'e' alcuna rinormalizzazione dei pesi restanti. Un bucket
    composto interamente da ticker esclusi risulta correttamente a peso
    ~0.0 (nulla di "accumulabile" li'), non gonfiato dall'esclusione di
    un altro bucket. Usato dal flag deficit_pac_only per escludere
    BTP/GOV dal calcolo del deficit di bucket.
    """
    held = _tickers_posseduti(state_df)
    if use_fractional_exposure:
        exposures = compute_instrument_bucket_exposures(data, held)
    else:
        exposures = {ticker: {bucket: 1.0} for ticker, bucket in compute_instrument_buckets(data, held).items()}
    out: dict[str, float] = {"Core": 0.0, "Difensivo": 0.0, "Satellite": 0.0}
    for ticker, exposure in exposures.items():
        if ticker in exclude_tickers:
            continue
        raw_weight = max(0.0, current_weights.get(ticker, 0.0))
        for bucket, frac in exposure.items():
            out[bucket] = out.get(bucket, 0.0) + raw_weight * frac
    return out


def _compute_instrument_quota_status(
    instrument_buckets: dict[str, str],
    current_weights: dict[str, float],
    bucket_weights: dict[str, float],
    instrument_quotas: dict[str, dict[str, float]],
    *,
    reserved_by_bucket: dict[str, float] | None = None,
) -> dict[str, dict[str, Any]]:
    """Validita' e scostamento delle quote target per strumento dentro ogni
    bucket. La feature e' opt-in per bucket: se instrument_quotas[bucket] e'
    completamente vuoto (mai configurato dall'utente), il bucket e' sempre
    valido a prescindere da quanti strumenti attivi possiede - identico al
    comportamento pre-feature (nessun blocco). Solo quando esiste almeno una
    quota assegnata per quel bucket scatta la regola stretta: ogni strumento
    attivo del bucket deve avere una quota assegnata e la somma delle quote
    assegnate (sui soli ticker ancora attivi) deve essere ~100%. Le quote
    orfane (strumenti chiusi) sono escluse dalla somma e riportate in
    stale_tickers per messaggistica UI.

    reserved_by_bucket: percentuale (frazione 0..1), per bucket, "riservata"
    a strumenti esclusi da instrument_buckets perche' hanno una divisione tra
    bucket (bucket_exposure) attiva - la loro vecchia quota interna resta
    salvata ma va sottratta dal target-somma richiesto ai ticker ancora
    attivi, altrimenti attivare la divisione farebbe scendere la somma delle
    quote sotto 100% e invaliderebbe un bucket gia' correttamente
    configurato (vedi compute_instrument_quota_status). Default None/vuoto:
    nessuna riserva, target flat 1.0 - e' il caso usato da run_sator_analysis
    (vedi sotto), che non conosce questo concetto."""
    reserved = reserved_by_bucket or {}
    tickers_by_bucket: dict[str, list[str]] = {"Core": [], "Difensivo": [], "Satellite": []}
    for ticker, bucket in instrument_buckets.items():
        tickers_by_bucket.setdefault(bucket, []).append(ticker)

    out: dict[str, dict[str, Any]] = {}
    for bucket in ("Core", "Difensivo", "Satellite"):
        active_tickers = set(tickers_by_bucket.get(bucket, []))
        quotas = dict(instrument_quotas.get(bucket, {}) or {})
        if not quotas:
            # Mai configurato per questo bucket: feature inattiva, nessun
            # blocco a prescindere dal numero di strumenti posseduti.
            valid = True
            missing_tickers: list[str] = []
            stale_tickers: list[str] = []
            live_quotas: dict[str, float] = {}
            sum_target = 0.0
        else:
            missing_tickers = sorted(active_tickers - set(quotas.keys()))
            stale_tickers = sorted(set(quotas.keys()) - active_tickers)
            live_quotas = {t: w for t, w in quotas.items() if t in active_tickers}
            sum_target = sum(max(0.0, _safe_float(w, 0.0)) for w in live_quotas.values())
            expected_sum = 1.0 - max(0.0, min(1.0, _safe_float(reserved.get(bucket), 0.0)))
            valid = not missing_tickers and (not active_tickers or abs(sum_target - expected_sum) < 1e-6)
        bucket_total = max(0.0, _safe_float(bucket_weights.get(bucket), 0.0))
        current_in_bucket = {
            t: round(max(0.0, _safe_float(current_weights.get(t), 0.0)) / bucket_total, 15) if bucket_total > 0 else 0.0
            for t in active_tickers
        }
        deviations_pp = {
            t: round((current_in_bucket.get(t, 0.0) - _safe_float(live_quotas[t], 0.0)) * 100.0, 15)
            for t in live_quotas
        }
        out[bucket] = {
            "valid": valid,
            "missing_tickers": missing_tickers,
            "stale_tickers": stale_tickers,
            "sum_target": sum_target,
            "current_weights": current_in_bucket,
            "target_weights": {t: _safe_float(w, 0.0) for t, w in live_quotas.items()},
            "deviations_pp": deviations_pp,
        }
    return out


def compute_instrument_operational_status(
    data: dict[str, Any], settings: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Peso attuale, target strategico (in termini assoluti di
    portafoglio) e stato calcolato per ogni strumento posseduto. MAI
    persistito, ricalcolato ad ogni chiamata. Nessun impatto su SATOR
    (run_sator_analysis, blocked_buckets_quota) - solo lettura per la UI
    di /quote-interne.

    Conversione di denominatore (il punto delicato): instrument_quotas
    e' la quota DENTRO il bucket (le quote di un bucket sommano ~100% tra
    loro), current_weights e' il peso sul PORTAFOGLIO INTERO. Il target
    va riportato a termini di portafoglio intero prima del confronto:
    target_assoluto = instrument_quotas[bucket][ticker] * objective[bucket].

    Strumenti con bucket_exposure divisa tra piu' bucket (sotto-progetto
    2) sono esclusi dal risultato - stesso trattamento di
    compute_instrument_quota_status, per lo stesso motivo (il concetto di
    "il" bucket di uno strumento diviso non si applica).

    Riusa la costante module-level _BUCKET_OBJECTIVE_KEY definita piu'
    sotto in questo file (vedi compute_instrument_reference_ranges): la
    risoluzione dei nomi in un corpo di funzione avviene a runtime, non
    alla definizione, quindi l'ordine testuale non conta - evitato cosi'
    di duplicare una costante identica gia' esistente nel modulo."""
    cfg = ensure_sator_settings(settings)
    state = compute_portfolio_state(data, include_closed=True)
    state_df = state.get("df", pd.DataFrame())
    if isinstance(data.get("_positions_df"), pd.DataFrame) and not data["_positions_df"].empty:
        state_df = data["_positions_df"].copy()
    held_tickers = _tickers_posseduti(state_df)
    master = data.get("instrument_master", {}) if isinstance(data.get("instrument_master", {}), dict) else {}

    all_buckets = compute_instrument_buckets(data, held_tickers)
    split_tickers = {
        ticker for ticker in all_buckets
        if bool((master.get(ticker, {}).get("manual_overrides") or {}).get("sator", {}).get("bucket_exposure_user_edited"))
    }
    instrument_buckets = {tk: b for tk, b in all_buckets.items() if tk not in split_tickers}

    current_weights = _compute_current_weights(state_df)
    objective = settings.get("portfolio_objective", {}) or {}
    quotas = cfg["instrument_quotas"]
    tolerance = cfg["instrument_quota_tolerance_pp"]

    out: dict[str, dict[str, Any]] = {}
    for ticker, bucket in instrument_buckets.items():
        bucket_target_pct = _safe_float(objective.get(_BUCKET_OBJECTIVE_KEY.get(bucket, ""), 0.0), 0.0)
        quota_in_bucket = _safe_float((quotas.get(bucket, {}) or {}).get(ticker), 0.0)
        target_assoluto = quota_in_bucket * bucket_target_pct
        peso_attuale = _safe_float(current_weights.get(ticker), 0.0)
        no_sell = resolve_instrument_no_sell(data, ticker)
        delta = peso_attuale - target_assoluto
        if abs(delta) < tolerance:
            stato = "in_target"
        elif delta <= -tolerance:
            stato = "sottopeso"
        elif no_sell:
            stato = "sovrappeso_no_sell"
        else:
            stato = "sovrappeso"
        out[ticker] = {
            "bucket": bucket,
            "peso_attuale": peso_attuale,
            "target": target_assoluto,
            "no_sell": no_sell,
            "stato": stato,
        }
    return out


def compute_instrument_quota_status(
    data: dict[str, Any], settings: dict[str, Any], *, exclude_tickers: frozenset[str] = frozenset(),
) -> dict[str, dict[str, Any]]:
    """Entry point standalone (non richiede un'analisi SATOR completa):
    usato dal banner di Pianificazione e dalla pagina /quote-interne.

    exclude_tickers: stesso meccanismo gia' usato da ogni altra funzione
    toccata dal toggle "Escludi BTP/GOV" (held_non_pac_tickers) - i ticker
    esclusi non contano come "attivi" nel loro bucket, quindi non richiedono
    una quota e non pesano sulla somma. Aggiunto perche' /quote-interne
    mostrava ancora i BTP anche col toggle attivo su Pianificazione.

    Ticker con bucket_exposure_user_edited=True (appartenenza a bucket
    divisa manualmente su piu' bucket, vedi resolve_instrument_bucket_exposure)
    sono esclusi allo stesso modo: non richiedono una quota interna in
    nessun bucket e non pesano sulla somma-100% di nessun bucket. Decisione
    esplicita dell'utente - far convivere la divisione frazionata
    dell'appartenenza a bucket con la validazione delle quote interne e'
    fuori scopo per questo sotto-progetto ed e' rimandato.

    Se uno di questi ticker esclusi aveva GIA' una quota interna configurata
    prima di attivare la divisione (caso reale: strumento presente da tempo
    in un bucket con quote gia' complete al 100%), quella quota resta salvata
    ma va "riservata" - sottratta dal target-somma richiesto ai ticker ancora
    attivi del bucket - altrimenti il bucket, gia' correttamente configurato,
    risulterebbe invalido dal nulla al solo attivarsi della divisione (bug
    trovato dalla review finale: la spec, sezione 6, promette esplicitamente
    che "la quota resta salvata ma viene ignorata ai fini della validazione
    finche' la divisione tra bucket e' attiva"). Vedi reserved_by_bucket
    calcolato sotto e passato a _compute_instrument_quota_status. I ticker
    esclusi tramite exclude_tickers (es. toggle BTP/GOV di Pianificazione)
    NON entrano in questo calcolo: sono un meccanismo di esclusione diverso
    e non correlato, non toccato da questo fix.

    Divergenza deliberata e accettata: il motore SATOR vero e proprio
    (run_sator_analysis, blocked_buckets_quota) NON condivide ne' questa
    riserva ne' l'esclusione dei ticker con bucket_exposure attiva - chiama
    _compute_instrument_quota_status direttamente con il proprio
    instrument_buckets (compute_instrument_buckets, non filtrato) e senza
    reserved_by_bucket, quindi continua a richiedere una quota anche per uno
    strumento diviso tra bucket nella propria logica di blocco, invariata
    rispetto a prima di questo sotto-progetto. Questa funzione (usata dal
    banner di Pianificazione e da /quote-interne, cioe' la validazione
    "display") e il motore SATOR restano intenzionalmente non unificati."""
    cfg = ensure_sator_settings(settings)
    state = compute_portfolio_state(data, include_closed=True)
    state_df = state.get("df", pd.DataFrame())
    if isinstance(data.get("_positions_df"), pd.DataFrame) and not data["_positions_df"].empty:
        state_df = data["_positions_df"].copy()
    held_tickers = _tickers_posseduti(state_df)
    master = data.get("instrument_master", {}) if isinstance(data.get("instrument_master", {}), dict) else {}
    all_buckets = compute_instrument_buckets(data, held_tickers)
    split_tickers = {
        ticker
        for ticker in all_buckets
        if ticker not in exclude_tickers
        and bool((master.get(ticker, {}).get("manual_overrides") or {}).get("sator", {}).get("bucket_exposure_user_edited"))
    }
    instrument_buckets = {
        ticker: bucket for ticker, bucket in all_buckets.items()
        if ticker not in exclude_tickers and ticker not in split_tickers
    }
    reserved_by_bucket: dict[str, float] = {}
    for ticker in split_tickers:
        bucket = all_buckets[ticker]
        old_quota = _safe_float((cfg["instrument_quotas"].get(bucket, {}) or {}).get(ticker), 0.0)
        if old_quota > 0:
            reserved_by_bucket[bucket] = reserved_by_bucket.get(bucket, 0.0) + old_quota
    current_weights = _compute_current_weights(state_df)
    bucket_weights = _compute_bucket_weights(data, state_df, current_weights, exclude_tickers=exclude_tickers)
    return _compute_instrument_quota_status(
        instrument_buckets, current_weights, bucket_weights, cfg["instrument_quotas"],
        reserved_by_bucket=reserved_by_bucket,
    )


_BUCKET_OBJECTIVE_KEY = {"Core": "core", "Difensivo": "difensivo", "Satellite": "satellite"}


def compute_instrument_reference_ranges(
    data: dict[str, Any],
    settings: dict[str, Any],
    bucket_tickers: dict[str, list[str]],
) -> dict[str, dict[str, tuple[float, float]]]:
    """Forbice di riferimento (0.0, max) per ogni strumento di ogni bucket,
    puramente indicativa - nessun impatto su validita'/blocco SATOR (quello
    resta _compute_instrument_quota_status, invariato). Richiesta esplicita
    dell'utente dopo il merge di quote-interne-bucket: "dare un indirizzo e
    coerenza" partendo dai limiti di concentrazione per natura gia'
    esistenti (settings["sator"]["concentration_caps"]), non un vincolo.

    Formula: cap_natura / peso_target_del_bucket (clampato a 1.0), diviso in
    parti uguali tra gli strumenti dello stesso bucket che condividono la
    stessa natura SATOR (non l'etichetta visiva item["natura"] - la natura
    tecnica gia' usata per i cap, es. "azionario_emergenti"). Nature non
    mappate usano CAP_MORBIDO_DEFAULT, stessa convenzione di _score_fit
    (riga 734). Bucket con peso target 0 non produce alcuna forbice (nessun
    denominatore su cui riproporzionare)."""
    cfg = ensure_sator_settings(settings)
    caps = cfg["concentration_caps"]
    objective = settings.get("portfolio_objective", {}) or {}
    master = data.get("instrument_master", {}) if isinstance(data.get("instrument_master", {}), dict) else {}
    items_by_ticker = {
        str(item.get("ticker") or "").strip().upper(): item
        for item in data.get("strumenti", []) or []
    }

    out: dict[str, dict[str, tuple[float, float]]] = {}
    for bucket, tickers in bucket_tickers.items():
        bucket_target = _safe_float(objective.get(_BUCKET_OBJECTIVE_KEY.get(bucket, ""), 0.0), 0.0)
        ranges: dict[str, tuple[float, float]] = {}
        if bucket_target > 0 and tickers:
            nature_by_ticker: dict[str, str] = {}
            for ticker in tickers:
                item = items_by_ticker.get(ticker, {})
                sator = ((master.get(ticker, {}).get("manual_overrides") or {}).get("sator") or {})
                inf = infer_sator_metadata(item, True)
                nature_by_ticker[ticker] = _meta_strutturale(sator, inf, "nature")
            nature_counts: dict[str, int] = {}
            for nature in nature_by_ticker.values():
                nature_counts[nature] = nature_counts.get(nature, 0) + 1
            for ticker in tickers:
                nature = nature_by_ticker[ticker]
                cap = caps.get(nature, CAP_MORBIDO_DEFAULT)
                max_bucket_relative = min(1.0, cap / bucket_target)
                count = max(1, nature_counts.get(nature, 1))
                ranges[ticker] = (0.0, max_bucket_relative / count)
        out[bucket] = ranges
    return out


def _non_pac_held_tickers(data: dict[str, Any], held_tickers: set[str]) -> frozenset[str]:
    """Ticker posseduti non ad accumulo (oggi: categoria GOV, es. BTP).

    Riusa infer_sator_metadata (stessa fonte di 'pac_enabled' gia' usata
    per il bonus nel punteggio costo, core/services/sator.py:737) invece
    di ricalcolare il criterio categoria=='GOV' una seconda volta.
    """
    out: set[str] = set()
    for item in data.get("strumenti", []) or []:
        ticker = str(item.get("ticker") or "").strip().upper()
        if not ticker or ticker not in held_tickers:
            continue
        inferred = infer_sator_metadata(item, ticker in held_tickers)
        if not bool(inferred.get("pac_enabled", True)):
            out.add(ticker)
    return frozenset(out)


def held_non_pac_tickers(data: dict[str, Any], state_df: pd.DataFrame) -> frozenset[str]:
    """Ticker posseduti non ad accumulo (BTP/GOV): unica fonte per il toggle
    "Escludi BTP/GOV" della pagina Pianificazione, riusata dal deficit di
    bucket (run_sator_analysis, cfg["deficit_pac_only"]) e da ogni altro
    grafico/tabella della pagina che deve rispettare lo stesso toggle -
    nessuna seconda formula, solo _tickers_posseduti + _non_pac_held_tickers,
    gia' testate."""
    held = _tickers_posseduti(state_df)
    return _non_pac_held_tickers(data, held)


def _compute_bucket_deficits(
    bucket_weights: dict[str, float],
    objective: dict[str, float],
    bands: dict[str, dict[str, float]],
    portfolio_value: float,
    budget: float,
) -> tuple[dict[str, float], set[str]]:
    """Deficit in euro per bucket, e insieme dei bucket bloccati (sopra banda massima).

    Formula standard di ribilanciamento tramite nuovi flussi:
    Vpost = portfolio_value + budget
    TargetValue_k = Vpost * target_k
    Deficit_k = max(TargetValue_k - CurrentValue_k, 0)

    Un bucket sopra la propria banda massima e' bloccato: deficit forzato
    a 0 anche se la formula darebbe un valore positivo (non dovrebbe mai
    accadere se target e banda sono coerenti, ma la banda ha sempre
    l'ultima parola). Un bucket dentro banda (ne' sopra ne' sotto il
    minimo) non e' urgente: deficit 0, non bloccato.
    """
    vpost = portfolio_value + budget
    deficits: dict[str, float] = {}
    blocked: set[str] = set()
    for bucket, obj_key in _BUCKET_OBJECTIVE_KEYS.items():
        current_weight = _safe_float(bucket_weights.get(bucket), 0.0)
        band = bands.get(bucket, {"target": 0.0, "min": 0.0, "max": 1.0})
        if current_weight > band["max"]:
            blocked.add(bucket)
            continue
        if current_weight >= band["min"]:
            continue  # dentro banda, non urgente
        target_value = vpost * band["target"]
        current_value = portfolio_value * current_weight
        deficit = max(target_value - current_value, 0.0)
        if deficit > 0:
            deficits[bucket] = deficit
    return deficits, blocked


def compute_current_bucket_mix(
    data: dict[str, Any], state_df: pd.DataFrame, *, exclude_tickers: frozenset[str] = frozenset()
) -> dict[str, float]:
    """Mix Core/Difensivo/Satellite del portafoglio attuale (percentuale del
    controvalore totale). Chiamata sia da SATOR sia dalla UI di Pianificazione.

    exclude_tickers: a differenza di _compute_bucket_weights (usato per il
    deficit di bucket in SATOR, dove i pesi grezzi non vanno MAI
    rinormalizzati - richiesta esplicita dell'utente), qui il risultato e'
    una percentuale di composizione mostrata all'utente (grafico
    obiettivo-vs-mix, toggle "Escludi BTP/GOV" in Pianificazione): quando
    alcuni ticker sono esclusi, i pesi restanti vengono rinormalizzati per
    sommare a 100% di cio' che resta visibile, non del portafoglio intero -
    altrimenti le barre "Attuale" non chiuderebbero al 100%. Nessun'altra
    chiamata a questa funzione passa exclude_tickers non vuoto oggi
    (core/services/portfolio_insights.py:165 non lo passa affatto), quindi
    la rinormalizzazione non tocca alcun percorso SATOR."""
    current_weights = _compute_current_weights(state_df)
    raw = _compute_bucket_weights(
        data, state_df, current_weights, exclude_tickers=exclude_tickers, use_fractional_exposure=True,
    )
    if not exclude_tickers:
        return raw
    total = sum(raw.values())
    if total <= 0:
        return raw
    return {bucket: weight / total for bucket, weight in raw.items()}


def build_portfolio_rings_frame(
    data: dict[str, Any], state_df: pd.DataFrame, *, exclude_tickers: frozenset[str] = frozenset()
) -> pd.DataFrame:
    """Una riga per (strumento, bucket) posseduto: ticker, name, bucket
    (Core/Difensivo/Satellite), natura (testo libero legacy), nature
    (codice tassonomia SATOR), value (controvalore attribuito a quel
    bucket). Uno strumento senza bucket_exposure diviso produce UNA riga
    con il controvalore pieno (identico al comportamento precedente);
    uno strumento con bucket_exposure diviso produce una riga per ogni
    bucket con frazione > 0, con value proporzionale. Base dati per il
    donut ad anelli concentrici e per la tabella di allocazione bucket
    della Dashboard decisionale in Pianificazione - entrambi i consumatori
    filtrano gia' per colonna "bucket" e sommano "value", quindi ereditano
    la divisione senza modifiche proprie.

    exclude_tickers: ticker posseduti da omettere del tutto (toggle "Escludi
    BTP/GOV" della pagina Pianificazione)."""
    columns = ["ticker", "name", "bucket", "natura", "nature", "value"]
    held = _tickers_posseduti(state_df)
    if not held:
        return pd.DataFrame(columns=columns)
    exposures = compute_instrument_bucket_exposures(data, held)
    controvalore_map: dict[str, float] = {}
    if state_df is not None and not state_df.empty and "Ticker" in state_df.columns and "Controvalore" in state_df.columns:
        for _, row in state_df.iterrows():
            t = str(row.get("Ticker") or "").strip().upper()
            if t:
                controvalore_map[t] = controvalore_map.get(t, 0.0) + _safe_float(row.get("Controvalore"), 0.0)
    rows = []
    for item in data.get("strumenti", []) or []:
        ticker = str(item.get("ticker") or "").strip().upper()
        if ticker not in held or ticker in exclude_tickers:
            continue
        value = controvalore_map.get(ticker, 0.0)
        if value <= 0:
            continue
        nature = resolve_instrument_nature(data, item, True)
        natura_legacy = str(item.get("natura") or "Esposizione diversificata")
        name = str(item.get("nome") or ticker)
        exposure = exposures.get(ticker, {"Satellite": 1.0})
        for bucket, frac in exposure.items():
            if frac <= 0:
                continue
            rows.append({
                "ticker": ticker,
                "name": name,
                "bucket": bucket,
                "natura": natura_legacy,
                "nature": nature,
                "value": value * frac,
            })
    return pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)


def compute_watchlist_reminders(
    data: dict[str, Any], state_df: pd.DataFrame, *, exclude_tickers: frozenset[str] = frozenset()
) -> dict[str, list[str]]:
    """Bucket -> codici nature SATOR (SATOR_NATURE_VALUES, non piu' testo
    libero) in stato SATOR 'watchlist' non gia' coperte da uno strumento
    posseduto nello stesso bucket. Promemoria puro (nessun ticker o
    importo): segnala un'area seguita ma non ancora presidiata, per la
    tabella "Allocazione: bucket e strumenti" in Pianificazione.

    exclude_tickers: un ticker posseduto ma escluso (toggle "Escludi
    BTP/GOV") non "copre" piu' la propria nature agli occhi del promemoria."""
    held = _tickers_posseduti(state_df)
    master = data.get("instrument_master", {}) if isinstance(data.get("instrument_master", {}), dict) else {}

    held_nature_by_bucket: dict[str, set[str]] = {"Core": set(), "Difensivo": set(), "Satellite": set()}
    for item in data.get("strumenti", []) or []:
        ticker = str(item.get("ticker") or "").strip().upper()
        if not ticker or ticker not in held or ticker in exclude_tickers:
            continue
        role = resolve_instrument_role(data, item, True)
        bucket = _role_bucket(role)
        nature = resolve_instrument_nature(data, item, True)
        held_nature_by_bucket.setdefault(bucket, set()).add(nature)

    reminders: dict[str, list[str]] = {"Core": [], "Difensivo": [], "Satellite": []}
    seen_by_bucket: dict[str, set[str]] = {"Core": set(), "Difensivo": set(), "Satellite": set()}
    for item in data.get("strumenti", []) or []:
        ticker = str(item.get("ticker") or "").strip().upper()
        if not ticker or ticker in held:
            continue
        sator = ((master.get(ticker, {}).get("manual_overrides") or {}).get("sator") or {})
        inf = infer_sator_metadata(item, False)
        state = _resolve_sator_state(sator.get("state"), inf["state"])
        if state != "watchlist":
            continue
        role = resolve_instrument_role(data, item, False)
        bucket = _role_bucket(role)
        nature = resolve_instrument_nature(data, item, False)
        if nature in held_nature_by_bucket.get(bucket, set()):
            continue
        if nature in seen_by_bucket.setdefault(bucket, set()):
            continue
        seen_by_bucket[bucket].add(nature)
        reminders.setdefault(bucket, []).append(nature)

    for bucket_key in reminders:
        reminders[bucket_key] = sorted(reminders[bucket_key])
    return reminders


def latest_sator_decision(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Fotografia SATOR piu' recente per created_at, o None se items e' vuoto."""
    if not items:
        return None
    return max(items, key=lambda it: str(it.get("created_at") or ""))


def build_next_purchase_bubble_frame(
    data: dict[str, Any], *, exclude_tickers: frozenset[str] = frozenset()
) -> tuple[pd.DataFrame, list[str]]:
    """Legge l'ultima fotografia SATOR salvata (per created_at) e ritorna il
    frame per la mappa a bolle dei prossimi acquisti, piu' la lista di ticker
    esclusi per dati insufficienti (fotografia pre-esistente senza i punteggi,
    o strumento non piu' presente in data["strumenti"]).

    exclude_tickers: righe ordine per ticker esclusi dal toggle "Escludi
    BTP/GOV" spariscono dalla mappa, senza finire nella lista 'missing'
    (categoria diversa: dati insufficienti, non esclusione utente)."""
    columns = [
        "ticker", "name", "bucket", "importo", "diversification_benefit", "risk_efficiency",
        "target_improvement_pp", "post_nature_weight", "nature_cap", "cap_headroom_after_pp",
        "data_quality_score", "data_quality_label",
    ]
    decisions = load_sator_decisions()
    items = list((decisions or {}).get("items") or [])
    latest = latest_sator_decision(items)
    if latest is None:
        return pd.DataFrame(columns=columns), []
    strumenti_map = {
        str(item.get("ticker") or "").strip().upper(): item
        for item in data.get("strumenti", []) or []
    }
    rows = []
    missing: list[str] = []
    for line in latest.get("order_lines", []) or []:
        ticker = str(line.get("ticker") or "").strip().upper()
        if not ticker or ticker in exclude_tickers:
            continue
        risk = line.get("risk_efficiency")
        div = line.get("diversification_benefit")
        strumento = strumenti_map.get(ticker)
        if risk is None or div is None or strumento is None:
            missing.append(ticker)
            continue
        rows.append({
            "ticker": ticker,
            "name": str(line.get("name") or strumento.get("nome") or ticker),
            "bucket": str(line.get("bucket") or "Satellite"),
            "importo": _safe_float(line.get("amount"), 0.0),
            "diversification_benefit": _safe_float(div, 0.0),
            "risk_efficiency": _safe_float(risk, 0.0),
            "target_improvement_pp": _safe_float(line.get("target_improvement_pp"), 0.0),
            "post_nature_weight": _safe_float(line.get("post_nature_weight"), 0.0),
            "nature_cap": _safe_float(line.get("nature_cap"), 0.0),
            "cap_headroom_after_pp": _safe_float(line.get("cap_headroom_after_pp"), 0.0),
            "data_quality_score": _safe_float(line.get("data_quality_score"), 0.0),
            "data_quality_label": str(line.get("data_quality_label") or "N/D"),
        })
    frame = pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)
    return frame, missing


def _purchase_decision_score(row: pd.Series, amount: float) -> float:
    """Priorita' operativa dell'acquisto, distinta dal voto dello strumento.

    Il voto resta un giudizio qualitativo sullo strumento. Questo punteggio
    valuta invece se l'importo simulato e' utile adesso per il portafoglio:
    target, cap, qualita' dati, costi e qualita' generale vengono combinati in
    una metrica 0-1 usata solo per decidere cosa finanziare con il budget.
    """
    amount = max(0.0, _safe_float(amount, 0.0))
    metrics = _compute_marginal_purchase_metrics(row, amount)
    target_pp = _safe_float(metrics.get("target_improvement_pp"), 0.0)
    headroom_pp = _safe_float(metrics.get("cap_headroom_after_pp"), 0.0)
    quality = _safe_float(row.get("data_quality_score"), _data_quality_score(row.get("n_punti", 0)))
    score = _safe_float(row.get("score_finale"), 0.0)
    cost = _safe_float(row.get("cost_efficiency"), 0.5)

    target_component = float(np.clip(0.50 + target_pp / 8.0, 0.0, 1.0))
    cap_component = float(np.clip((headroom_pp + 2.0) / 8.0, 0.0, 1.0))
    decision = (
        target_component * 0.40
        + score * 0.25
        + cap_component * 0.15
        + quality * 0.10
        + cost * 0.10
    )
    if headroom_pp < 0:
        decision -= min(0.25, abs(headroom_pp) / 20.0)
    if target_pp < -0.10:
        decision -= min(0.18, abs(target_pp) / 20.0)
    if quality < 0.55:
        decision -= 0.06
    return float(np.clip(decision, 0.0, 1.0))


def _decision_reason(row: pd.Series, amount: float) -> str:
    metrics = _compute_marginal_purchase_metrics(row, amount)
    target_pp = _safe_float(metrics.get("target_improvement_pp"), 0.0)
    headroom_pp = _safe_float(metrics.get("cap_headroom_after_pp"), 0.0)
    quality_label = str(row.get("data_quality_label") or _data_quality_label(row.get("n_punti", 0)))
    parts: list[str] = []
    if target_pp > 0.10:
        parts.append(f"migliora il target di bucket di {target_pp:+.1f} pp")
    elif target_pp < -0.10:
        parts.append(f"peggiora il target di bucket di {target_pp:+.1f} pp")
    else:
        parts.append("ha impatto quasi neutro sul target di bucket")
    if headroom_pp < 0:
        parts.append(f"porta la natura oltre cap di {abs(headroom_pp):.1f} pp")
    elif headroom_pp < 1.0:
        parts.append("lascia la natura vicina al cap")
    else:
        parts.append(f"mantiene {headroom_pp:.1f} pp di spazio sul cap natura")
    parts.append(f"dati {quality_label.lower()}")
    return "; ".join(parts) + "."


def _suggested_quotes(ranking_df: pd.DataFrame, budget: float, *, max_lines: int = MAX_LINEE_SUGGERITE) -> list[int]:
    """Allocazione suggerita a quote intere, guidata dall'utilita' marginale.

    Il voto continua a ordinare la qualita' degli strumenti, ma le quote
    suggerite sono finanziate con un punteggio decisionale separato: ogni quota
    simulata deve risultare utile rispetto a target, cap, dati, costi e qualita'
    generale. Il residuo puo' restare liquido.
    """
    n = len(ranking_df)
    quote = [0] * n
    if budget <= 0 or n == 0:
        return quote
    df = ranking_df.reset_index(drop=True)
    cap_linea = budget * 0.35
    # Un solo candidato per funzione: il piu' utile operativamente per una quota.
    # Cosi' il suggerito non coincide per forza col voto piu' alto se peggiora
    # target/cap o ha dati deboli.
    if "comparison_group" in df.columns:
        gruppi = df["comparison_group"].astype(str)
    else:
        gruppi = pd.Series([str(i) for i in range(n)], index=df.index)
    initial_scores = pd.Series(
        [
            _purchase_decision_score(df.iloc[i], _safe_float(df.iloc[i].get("unit_price"), 0.0))
            for i in range(n)
        ],
        index=df.index,
    )
    migliori = initial_scores.groupby(gruppi).idxmax().tolist()
    candidati = [
        (int(i), _safe_float(initial_scores.loc[i]), _safe_float(df.loc[i, "unit_price"]))
        for i in migliori
        if 0 < _safe_float(df.loc[i, "unit_price"]) <= budget
    ]
    candidati.sort(key=lambda x: (-x[1], x[2]))
    # equilibrio: si servono al massimo le funzioni con priorita' operativa piu'
    # alta, per evitare troppe righe minuscole.
    candidati = candidati[: max(1, int(max_lines or MAX_LINEE_SUGGERITE))]
    speso = 0.0
    for i, dec_score, price in candidati:
        if dec_score < 0.50:
            continue
        if speso + price <= budget:
            quote[i] = 1
            speso += price
    progredito = True
    while progredito:
        progredito = False
        step_scores: list[tuple[float, float, int, float]] = []
        for i, _score, price in candidati:
            if speso + price > budget:
                continue
            if (quote[i] + 1) * price > cap_linea:
                continue
            next_amount = (quote[i] + 1) * price
            step_score = _purchase_decision_score(df.iloc[i], next_amount)
            if step_score < 0.50:
                continue
            step_scores.append((step_score, -price, i, price))
        if not step_scores:
            break
        step_scores.sort(reverse=True)
        _step_score, _neg_price, i, price = step_scores[0]
        quote[i] += 1
        speso += price
        progredito = True
    return quote


def _suggested_quotes_by_bucket(
    ranking_df: pd.DataFrame,
    budget: float,
    bucket_deficits: dict[str, float],
    blocked_buckets: set[str],
    *,
    max_lines_per_bucket: int | None = None,
) -> list[int]:
    """Come _suggested_quotes, ma il budget e' prima diviso tra i bucket
    proporzionalmente al loro deficit (Allocation_k = budget * deficit_k /
    sum(deficit)), poi _suggested_quotes (INVARIATA) viene richiamata una
    volta per bucket sul relativo sotto-budget. I bucket in blocked_buckets
    o senza deficit positivo non ricevono nulla.

    Secondo giro di redistribuzione: se un bucket non riesce a spendere
    tutto il proprio sotto-budget (candidati esauriti sotto soglia 0,50 di
    punteggio decisionale, o vincoli di cap/quote intere), il residuo non
    resta liquido a prescindere - viene riassegnato, in un solo giro
    aggiuntivo (deterministico, nessun loop), ai bucket che invece hanno
    saturato la propria quota (segno che potrebbero avere ancora candidati
    validi), in proporzione al loro deficit. Un bucket che ha gia' lasciato
    residuo nel primo giro non riceve mai altro nel secondo: se non aveva
    candidati sufficienti a spendere la propria fetta, darghene di piu' non
    aiuta. Se anche dopo la redistribuzione resta un residuo, quello si
    ferma li' (nessun ulteriore giro): stesso comportamento onesto di
    _suggested_quotes, il budget puo' restare parzialmente liquido quando
    davvero non ci sono abbastanza candidati validi in tutto l'universo
    eleggibile.

    max_lines_per_bucket=None (default): nessun tetto predeterminato, ogni
    riga del bucket puo' essere finanziata (equivalente a len(ranking_df)).

    Stesso contratto di _suggested_quotes: lista di interi allineata
    all'indice di ranking_df (dopo reset_index).
    """
    if max_lines_per_bucket is None:
        max_lines_per_bucket = len(ranking_df)
    n = len(ranking_df)
    quote = [0] * n
    if budget <= 0 or n == 0 or "_bucket" not in ranking_df.columns:
        return quote
    total_deficit = sum(v for v in bucket_deficits.values() if v > 0)
    if total_deficit <= 0:
        return quote
    df = ranking_df.reset_index(drop=True)
    prices = pd.to_numeric(df.get("unit_price"), errors="coerce").fillna(0.0)

    eligible_buckets = [
        bucket for bucket, deficit in bucket_deficits.items()
        if bucket not in blocked_buckets and deficit > 0
    ]
    sub_budgets = {b: budget * bucket_deficits[b] / total_deficit for b in eligible_buckets}
    speso_per_bucket: dict[str, float] = {}
    for bucket in eligible_buckets:
        sub_budget = sub_budgets[bucket]
        if sub_budget <= 0:
            speso_per_bucket[bucket] = 0.0
            continue
        bucket_df = df.loc[df["_bucket"] == bucket]
        if bucket_df.empty:
            speso_per_bucket[bucket] = 0.0
            continue
        bucket_quote = _suggested_quotes(bucket_df, sub_budget, max_lines=max_lines_per_bucket)
        for local_idx, q in zip(bucket_df.index, bucket_quote):
            quote[local_idx] = q
        speso_per_bucket[bucket] = sum(quote[i] * prices[i] for i in bucket_df.index)

    leftover = sum(sub_budgets[b] - speso_per_bucket.get(b, 0.0) for b in eligible_buckets)
    saturated = [
        b for b in eligible_buckets
        if speso_per_bucket.get(b, 0.0) >= sub_budgets[b] - max(1.0, sub_budgets[b] * 0.05)
    ]
    saturated_deficit_total = sum(bucket_deficits[b] for b in saturated)
    if leftover > 0.01 and saturated and saturated_deficit_total > 0:
        for bucket in saturated:
            extra = leftover * bucket_deficits[bucket] / saturated_deficit_total
            new_sub_budget = speso_per_bucket[bucket] + extra
            bucket_df = df.loc[df["_bucket"] == bucket]
            if bucket_df.empty:
                continue
            bucket_quote = _suggested_quotes(bucket_df, new_sub_budget, max_lines=max_lines_per_bucket)
            for local_idx, q in zip(bucket_df.index, bucket_quote):
                quote[local_idx] = q
        logger.info(
            "SATOR bucket_first_allocation: ridistribuiti %.2f EUR di residuo dai bucket "
            "sottospesi ai bucket saturi %s",
            leftover, saturated,
        )
    return quote


# --------------------------------------------------------------------------- #
# Alert onesti (legati alle spiegazioni)
# --------------------------------------------------------------------------- #

def _build_alerts(
    ranking: pd.DataFrame,
    nature_weights: dict[str, float],
    bucket_weights: dict[str, float] | None = None,
    portfolio_objective: dict[str, float] | None = None,
    caps: dict[str, float] | None = None,
    *,
    nature_weights_excl: dict[str, float] | None = None,
    bucket_weights_excl: dict[str, float] | None = None,
) -> list[dict[str, str]]:
    """Alert di concentrazione onesti: per default guardano sempre il peso reale
    (con tutti gli strumenti posseduti, BTP inclusi).

    nature_weights_excl/bucket_weights_excl (opzionali): quando il flag
    deficit_pac_only e' attivo, il chiamante passa qui i pesi ricalcolati
    escludendo gli strumenti non-PAC (BTP/GOV) - se presenti, un alert di
    concentrazione scatta solo se la soglia e' superata ANCHE dopo
    l'esclusione, cioe' se la concentrazione non e' interamente dovuta ai
    titoli che l'utente ha gia' detto di ignorare in quella modalita'.
    Se None (default o flag spento), il comportamento resta quello di
    sempre: si guarda solo il peso reale completo.
    """
    alerts: list[dict[str, str]] = []
    if ranking is None or ranking.empty:
        return alerts
    caps = caps if caps is not None else CAP_MORBIDO_NATURA
    for nature, peso in nature_weights.items():
        cap = caps.get(nature, CAP_MORBIDO_DEFAULT)
        if peso <= cap * 1.25:
            continue
        if nature_weights_excl is not None and nature_weights_excl.get(nature, 0.0) <= cap * 1.25:
            continue
        alerts.append({"level": "warning", "title": "Concentrazione elevata",
                       "message": f"La funzione \"{nature.replace('_', ' ')}\" pesa {peso:.0%} (soglia indicativa {cap:.0%}): "
                                  "il fit e la diversificazione dei titoli con questa natura sono penalizzati di conseguenza."})
    if bucket_weights and portfolio_objective:
        for bucket, key in _BUCKET_TO_OBJECTIVE_KEY.items():
            peso = float(bucket_weights.get(bucket, 0.0))
            target = _safe_float(portfolio_objective.get(key), 0.0)
            if target <= 0 or peso <= target * 1.25:
                continue
            if bucket_weights_excl is not None and float(bucket_weights_excl.get(bucket, 0.0)) <= target * 1.25:
                continue
            alerts.append({"level": "warning", "title": "Bucket sovrappesato",
                           "message": f"Il bucket \"{bucket}\" pesa {peso:.0%} contro un obiettivo di {target:.0%}: "
                                      "gli acquisti in questo gruppo sono penalizzati di conseguenza nel punteggio Fit."})
    challenger_vince = ranking[(ranking["rango_gruppo"] == 1) & (~ranking["in_portfolio"])]
    incombenti = set(ranking[ranking["in_portfolio"]]["comparison_group"])
    sostituzioni = challenger_vince[challenger_vince["comparison_group"].isin(incombenti)]
    for _, row in sostituzioni.iterrows():
        alerts.append({"level": "info", "title": "Challenger preferibile",
                       "message": f"Per \"{str(row['function_label']).replace('_', ' ')}\" il candidato non in portafoglio "
                                  f"{row['ticker']} supera l'incumbente: vedi la motivazione nella riga corrispondente."})
    if (~ranking["storico_sufficiente"]).any():
        n = int((~ranking["storico_sufficiente"]).sum())
        alerts.append({"level": "info", "title": "Storico incompleto",
                       "message": f"{n} strumento/i hanno serie troppo corte: momentum e rischio sono indicativi e segnalati in tabella."})
    return alerts


# --------------------------------------------------------------------------- #
# Storico decisionale
# --------------------------------------------------------------------------- #

def _giudizio_label(voto_medio: float) -> str:
    if voto_medio >= 8.0:
        return "Ottima"
    if voto_medio >= 6.5:
        return "Buona"
    if voto_medio >= 5.0:
        return "Sufficiente"
    return "Debole"


def build_sator_decision_record(
    analysis_payload: dict[str, Any],
    *,
    order_lines: list[dict[str, Any]],
    budget: float,
    note: str = "",
) -> dict[str, Any]:
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    ranking = analysis_payload.get("ranking") if isinstance(analysis_payload, dict) else None
    if ranking is None or not isinstance(ranking, pd.DataFrame):
        ranking = pd.DataFrame()

    # Arricchisce ogni linea con role, bucket e voto dal ranking
    enriched_lines = []
    for line in (order_lines or []):
        entry = dict(line)
        if not ranking.empty:
            row = ranking[ranking["ticker"].astype(str) == str(entry.get("ticker", ""))]
            if not row.empty:
                r = row.iloc[0]
                entry["role"] = str(r.get("role", ""))
                entry["bucket"] = _role_bucket(str(r.get("role", "")))
                entry["voto"] = round(float(_safe_float(r.get("voto"), 0.0)), 1)
                entry["score_finale"] = round(float(_safe_float(r.get("score_finale"), 0.0)), 4)
                entry["decision_score"] = round(float(_purchase_decision_score(r, _safe_float(entry.get("amount"), 0.0))), 4)
                entry["decision_reason"] = _decision_reason(r, _safe_float(entry.get("amount"), 0.0))
                entry["risk_efficiency"] = round(float(_safe_float(r.get("risk_efficiency"), 0.0)), 4)
                entry["diversification_benefit"] = round(float(_safe_float(r.get("diversification_benefit"), 0.0)), 4)
                marginal = _compute_marginal_purchase_metrics(r, _safe_float(entry.get("amount"), 0.0))
                entry.update(marginal)
                entry["data_quality_score"] = round(float(_safe_float(r.get("data_quality_score"), 0.0)), 4)
                entry["data_quality_label"] = str(r.get("data_quality_label") or "N/D")
        enriched_lines.append(entry)

    # Ripartizione core/difensivo/satellite (importi e percentuali)
    totale = sum(_safe_float(l.get("amount"), 0.0) for l in enriched_lines)
    rip: dict[str, float] = {"Core": 0.0, "Difensivo": 0.0, "Satellite": 0.0}
    for line in enriched_lines:
        bucket = str(line.get("bucket") or "Satellite")
        rip[bucket] = rip.get(bucket, 0.0) + _safe_float(line.get("amount"), 0.0)
    ripartizione = {
        k: {"amount": round(v, 2), "pct": round(v / totale * 100.0, 1) if totale > 0 else 0.0}
        for k, v in rip.items()
    }

    # Giudizio: voto medio ponderato per importo
    voti = [(l.get("voto", 0.0), _safe_float(l.get("amount"), 0.0)) for l in enriched_lines if l.get("voto")]
    if voti:
        tot_peso = sum(p for _, p in voti) or 1.0
        voto_medio = round(sum(v * p for v, p in voti) / tot_peso, 1)
    else:
        voto_medio = 0.0
    giudizio = {"voto_medio": voto_medio, "label": _giudizio_label(voto_medio)}

    importo_ordine = round(totale, 2)

    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    return {
        "decision_id": f"sator_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "created_at": timestamp,
        "month_id": datetime.now().strftime("%Y-%m"),
        "budget": round(_safe_float(budget), 2),
        "importo_ordine": importo_ordine,
        "giudizio": giudizio,
        "ripartizione": ripartizione,
        "order_lines": enriched_lines,
        "alerts": list(analysis_payload.get("alerts", [])) if isinstance(analysis_payload, dict) else [],
        "note": str(note or "").strip(),
        "actual_order": [],
    }


def compare_decision_to_actual(decision: dict[str, Any]) -> pd.DataFrame:
    proposal = pd.DataFrame(list(decision.get("order_lines", []) or []))
    actual = pd.DataFrame(list(decision.get("actual_order", []) or []))
    actual_present = not actual.empty
    proposal_cols = ["Ticker", "ISIN", "Strumento", "Quote proposte", "Ultimo prezzo", "Importo proposto"]
    compare_cols = proposal_cols + ["Quote effettive", "Importo effettivo", "Delta quote", "Delta importo"]
    if proposal.empty and actual.empty:
        return pd.DataFrame(columns=proposal_cols)
    for frame in (proposal, actual):
        defaults = {"ticker": "", "isin": "", "name": "", "shares": 0, "price": 0.0, "amount": 0.0}
        for c, default in defaults.items():
            if c not in frame.columns:
                frame[c] = default
    left = proposal.rename(columns={
        "ticker": "Ticker",
        "isin": "ISIN",
        "name": "Strumento",
        "shares": "Quote proposte",
        "price": "Ultimo prezzo",
        "amount": "Importo proposto",
    })
    if not actual_present:
        return left.reindex(columns=proposal_cols).sort_values("Ticker").reset_index(drop=True)
    merged = left.merge(
        actual.rename(columns={"ticker": "Ticker", "shares": "Quote effettive", "amount": "Importo effettivo"}),
        on="Ticker", how="outer").fillna(0)
    merged["Delta quote"] = pd.to_numeric(merged["Quote effettive"], errors="coerce").fillna(0) - pd.to_numeric(merged["Quote proposte"], errors="coerce").fillna(0)
    merged["Delta importo"] = pd.to_numeric(merged["Importo effettivo"], errors="coerce").fillna(0.0) - pd.to_numeric(merged["Importo proposto"], errors="coerce").fillna(0.0)
    return merged.reindex(columns=compare_cols).sort_values(["Delta importo", "Ticker"], ascending=[False, True]).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Metriche, serie, correlazioni, pesi
# --------------------------------------------------------------------------- #

def _rolling_return(serie: pd.Series, finestra: int) -> float:
    if len(serie) <= finestra or finestra <= 0:
        return np.nan
    inizio = float(serie.iloc[-1 - finestra])
    fine = float(serie.iloc[-1])
    if inizio <= 0:
        return np.nan
    ret = simple_period_return(inizio, fine)
    return ret if ret is not None else np.nan


def _compute_all_metrics_batch(tickers: list[str], price_frame: pd.DataFrame, window: int) -> dict[str, dict[str, float]]:
    """Rendimenti multi-orizzonte calcolati in un solo passaggio vettorizzato
    (nessuna fonte canonica equivalente, specifico del momentum SATOR);
    volatilita', drawdown e Sharpe riusano le funzioni canoniche di
    core/domain/risk.py — stessa fonte gia' usata da Summary e Cruscotti,
    chiamate una serie alla volta (non vettorizzabili sull'intero frame)."""
    _empty: dict[str, float] = {k: np.nan for k in ("ret_1m", "ret_3m", "ret_6m", "ret_12m", "vol", "drawdown", "rend_vol")}
    _empty["n_punti"] = 0.0
    if not tickers or price_frame is None or price_frame.empty:
        return {t: dict(_empty) for t in tickers}
    cols = list(dict.fromkeys(t for t in tickers if t in price_frame.columns))
    if not cols:
        return {t: dict(_empty) for t in tickers}

    frame = price_frame[cols].apply(pd.to_numeric, errors="coerce")
    frame = frame.loc[:, ~frame.columns.duplicated()]
    frame = frame.where(frame > 0)
    n_rows = len(frame)
    last = frame.iloc[-1]

    ret_series: dict[str, pd.Series] = {}
    for k, w in FINESTRE.items():
        if n_rows > w:
            start = frame.iloc[-(w + 1)]
            ret_series[k] = (last / start - 1.0).where(start > 0)
        else:
            ret_series[k] = pd.Series(np.nan, index=frame.columns)

    n_dict = frame.notna().sum().to_dict()
    ret_dicts = {k: s.to_dict() for k, s in ret_series.items()}

    vol_dict: dict[str, float] = {}
    dd_dict: dict[str, float] = {}
    rv_dict: dict[str, float] = {}
    for t in cols:
        prices = frame[t].dropna()
        if len(prices) < 2:
            vol_dict[t] = np.nan
            dd_dict[t] = np.nan
            rv_dict[t] = np.nan
            continue
        vol_series = rolling_volatility_annualized(prices, window)
        vol_dict[t] = float(vol_series.iloc[-1]) if not vol_series.empty else np.nan
        pct_returns = normalize_to_first(prices, as_pct=True)
        # build_drawdown_series lavora in punti percentuali; _score_risk si
        # aspetta una frazione decimale (es. -0.15, non -15.0): il /100.0 non
        # e' ridondante, converte l'unita' di misura.
        dd_dict[t] = min(build_drawdown_series(pct_returns.tolist())) / 100.0
        sharpe_series = rolling_sharpe(prices, window)
        rv_dict[t] = float(sharpe_series.iloc[-1]) if not sharpe_series.empty else np.nan

    result: dict[str, dict[str, float]] = {}
    for t in tickers:
        if t not in cols:
            result[t] = dict(_empty)
            continue
        m: dict[str, float] = {"n_punti": float(n_dict.get(t, 0.0) or 0.0)}
        for k, rd in ret_dicts.items():
            v = rd.get(t, np.nan)
            m[k] = float(v) if pd.notna(v) else np.nan
        m["vol"] = vol_dict.get(t, np.nan)
        m["drawdown"] = dd_dict.get(t, np.nan)
        m["rend_vol"] = rv_dict.get(t, np.nan)
        result[t] = m
    return result


def _build_returns_frame(price_frame: pd.DataFrame) -> pd.DataFrame:
    if price_frame is None or price_frame.empty:
        return pd.DataFrame()
    frame = price_frame.apply(pd.to_numeric, errors="coerce")
    frame = frame.where(frame > 0)
    returns = frame.pct_change().replace([np.inf, -np.inf], np.nan)
    return returns.dropna(how="all").sort_index()


def _build_portfolio_return_series(returns_frame: pd.DataFrame, state_df: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    _ = state_df  # non usato: firma invariata per compatibilita' con i chiamanti esistenti
    return combine_weighted_returns(returns_frame, pd.Series(weights or {}, dtype=float))


def _compute_correlations(returns_frame: pd.DataFrame, portfolio_returns: pd.Series) -> dict[str, float]:
    if returns_frame is None or returns_frame.empty or portfolio_returns is None or portfolio_returns.empty:
        return {}
    common = returns_frame.index.intersection(portfolio_returns.index)
    if len(common) < 15:
        return {}
    rf = returns_frame.loc[common]
    pt = portfolio_returns.loc[common]
    valid_pairs = rf.notna().mul(pt.notna(), axis=0).sum()
    # Filtra le colonne con overlap sufficiente PRIMA di corrwith, non dopo:
    # un titolo appena acquistato (es. 2 quotazioni) ha troppo poche
    # osservazioni per una covarianza reale, e corrwith calcolato su tutte
    # le colonne sollevava comunque "Degrees of freedom <= 0" da numpy per
    # quella colonna, scartata solo a valle — risultato finale gia'
    # corretto, ma warning inutile che puo' nascondere un warning vero
    # (bug reale, 2026-08-20). Nessuna colonna idonea -> nessun calcolo.
    eligible_cols = [col for col in rf.columns if valid_pairs.get(col, 0) >= 15]
    if not eligible_cols:
        return {}
    corr_all = rf[eligible_cols].corrwith(pt)
    return {
        str(col): float(corr_all[col])
        for col in corr_all.index
        if pd.notna(corr_all[col])
    }


def _compute_portfolio_value(state_df: pd.DataFrame) -> float:
    if state_df is None or state_df.empty or "Controvalore" not in state_df.columns:
        return 0.0
    return max(0.0, _safe_float(pd.to_numeric(state_df["Controvalore"], errors="coerce").fillna(0.0).sum(), 0.0))


def _compute_current_weights(state_df: pd.DataFrame) -> dict[str, float]:
    tot = _compute_portfolio_value(state_df)
    if tot <= 0:
        return {}
    out = {}
    for _, row in state_df.iterrows():
        t = str(row.get("Ticker") or "").strip().upper()
        if t:
            out[t] = _safe_float(row.get("Controvalore"), 0.0) / tot
    return out


def _compute_nature_weights(
    data: dict[str, Any],
    state_df: pd.DataFrame,
    current_weights: dict[str, float],
    *,
    exclude_tickers: frozenset[str] = frozenset(),
) -> dict[str, float]:
    master = data.get("instrument_master", {}) if isinstance(data.get("instrument_master", {}), dict) else {}
    held = _tickers_posseduti(state_df)
    out: dict[str, float] = {}
    for item in data.get("strumenti", []) or []:
        t = str(item.get("ticker") or "").strip().upper()
        if t not in held or t in exclude_tickers:
            continue
        sator = ((master.get(t, {}).get("manual_overrides") or {}).get("sator") or {})
        nature = _meta_strutturale(sator, infer_sator_metadata(item, True), "nature")
        out[nature] = out.get(nature, 0.0) + max(0.0, current_weights.get(t, 0.0))
    return out


# --------------------------------------------------------------------------- #
# Inferenze di gruppo / funzione
# --------------------------------------------------------------------------- #

def _infer_comparison_group(nature: str, role: str, ticker: str, name: str) -> str:
    mapping = {
        "azionario_globale_core": "core_azionario_globale",
        "azionario_emergenti": "azionario_emergenti",
        "monetario": "monetario",
        "bond_governativo": "bond_governativi",
        "bond_globale": "bond_globali",
        "oro": "oro",
        "tecnologia_ai": "satelliti_ai",
        "healthcare": "satelliti_difensivi",
        "energia": "real_assets",
        "metalli_miniere": "real_assets",
        "commodities": "commodities",
        "italia": "azionario_italia",
        "quality_factor": "fattoriali",
        "real_estate": "real_estate",
        "criptovalute": "criptovalute",
        "difesa_sicurezza": "difesa_sicurezza",
        "azionario_paese_singolo": "azionario_paese_singolo",
    }
    if nature in mapping:
        return mapping[nature]
    if role == "core_difensivo":
        return "core_difensivi"
    base = (ticker.split(".")[0] or name[:6]).lower()
    return f"altro_{base}"


def _infer_function_label(nature: str, role: str) -> str:
    mapping = {
        "azionario_globale_core": "core azionario globale",
        "azionario_emergenti": "mercati emergenti",
        "monetario": "liquidita remunerata",
        "bond_governativo": "stabilita governativa",
        "bond_globale": "obbligazionario globale",
        "oro": "copertura reale / oro",
        "tecnologia_ai": "satellite AI / crescita",
        "healthcare": "difensivo settoriale",
        "energia": "real assets / energia",
        "metalli_miniere": "real assets / metalli",
        "commodities": "materie prime",
        "italia": "azionario Italia",
        "quality_factor": "fattore qualita",
        "real_estate": "asset immobiliari",
        "fondo_pac": "linea PAC / fondo",
        "criptovalute": "satellite crypto",
        "difesa_sicurezza": "satellite difesa / sicurezza",
        "azionario_paese_singolo": "azionario paese singolo / stile",
    }
    if nature in mapping:
        return mapping[nature]
    if role == "core_globale":
        return "pilastro core"
    return "strumento osservato"


# --------------------------------------------------------------------------- #
# Utility
# --------------------------------------------------------------------------- #

def _tickers_posseduti(positions: pd.DataFrame) -> set[str]:
    if not isinstance(positions, pd.DataFrame) or positions.empty or "Ticker" not in positions.columns:
        return set()
    return {
        str(row.get("Ticker") or "").strip().upper()
        for _, row in positions.iterrows()
        if _safe_float(row.get("Quote"), 0.0) > QTY_ZERO_EPS
    }


def _latest_prices(price_frame: pd.DataFrame) -> dict[str, float]:
    out = {}
    if price_frame is not None and not price_frame.empty:
        for ticker in price_frame.columns:
            serie = pd.to_numeric(price_frame[ticker], errors="coerce").dropna()
            if not serie.empty:
                out[str(ticker)] = float(serie.iloc[-1])
    return out


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _parse_it_pct(value: Any) -> float:
    """Converte una percentuale in formato italiano ('0,40%', '+1,2 %') in
    frazione (0.0040). Stringa vuota o non numerica -> 0.0."""
    if value is None:
        return 0.0
    try:
        cleaned = str(value).replace("%", "").replace("+", "").replace(" ", "").replace(",", ".")
        if not cleaned:
            return 0.0
        return float(cleaned) / 100.0
    except (ValueError, TypeError):
        return 0.0


_SATOR_STATE_LEGACY_ALIASES: dict[str, str] = {
    "candidato": "watchlist",
    "fuori_piano": "escluso",
}


def _resolve_sator_state(raw_value: Any, default: str) -> str:
    """Risolve lo stato SATOR salvato. I valori storici 'candidato' e
    'fuori_piano' (rimossi da SATOR_STATE_VALUES nell'unificazione a 3
    stati) vengono interpretati come 'watchlist' ed 'escluso' senza
    riscrivere il dato salvato su disco - solo in lettura, qui."""
    text = str(raw_value or "").strip()
    text = _SATOR_STATE_LEGACY_ALIASES.get(text, text)
    return _coerce_choice(text, SATOR_STATE_VALUES, default)


def _coerce_choice(value: Any, allowed: tuple[str, ...], default: str) -> str:
    text = str(value or "").strip()
    return text if text in allowed else default


def _deep_merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in (incoming or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
