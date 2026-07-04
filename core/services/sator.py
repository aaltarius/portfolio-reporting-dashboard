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

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from core.finance import build_ptf_df, compute_portfolio_state
from core.price_frames import build_expanded_price_frame
from persistence.storage import macro_cat


# --------------------------------------------------------------------------- #
# Costanti
# --------------------------------------------------------------------------- #

SATOR_STATE_VALUES = ("in_portafoglio", "watchlist", "candidato", "escluso", "fuori_piano")
SATOR_COMMISSION_VALUES = ("zero_commissioni", "standard", "non_definito")
SATOR_ROLE_VALUES = (
    "core_globale", "core_regionale", "core_difensivo",
    "satellite_crescita", "satellite_difensivo", "satellite_tematico",
    "liquidita", "oro", "bond", "altro",
)
SATOR_INVESTIBLE_CATEGORIES = ("ETF", "ETC")

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
}
CAP_MORBIDO_DEFAULT = 0.08

# Nature selezionabili nell'editor universo (le stesse usate per i cap morbidi).
SATOR_NATURE_VALUES = tuple(CAP_MORBIDO_NATURA.keys()) + ("fondo_pac", "altro")

FINESTRE = {"ret_1m": 21, "ret_3m": 63, "ret_6m": 126, "ret_12m": 252}
PESI_MOMENTUM = {"ret_1m": 0.10, "ret_3m": 0.35, "ret_6m": 0.35, "ret_12m": 0.20}
MIN_PUNTI_STORICO = 30
MAX_LINEE_SUGGERITE = 5  # tetto di funzioni servite dalle quote suggerite

DEFAULT_SATOR_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "budget_preset": 900.0,
    "default_budget": 900.0,
    "include_watchlist": True,
    "include_candidates": True,
    "include_portfolio": True,
    "investible_categories": list(SATOR_INVESTIBLE_CATEGORIES),
    "max_share_per_line": 0.35,   # nessuna linea oltre il 35% del budget suggerito
    "score_weights": dict(PESI_DIMENSIONI),
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
    correlations: dict[str, float]
    selected_categories: tuple[str, ...]
    liquidita: float
    concentration_severity: float = 1.0


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
    non_strutturali = ("active", "state", "commission_mode", "pac_enabled", "zero_commission", "ter", "spread_pct")
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
    nature, role = "altro", "altro"

    def tk_in(*codici: str) -> bool:
        return any(c in tkl for c in codici)

    if category == "GOV":
        nature, role = "bond_governativo", "bond"
    elif category == "FND":
        nature, role = "fondo_pac", "core_difensivo"
    elif "money" in name or "overnight" in name or "monetar" in name or tk_in("xeon", "csh", "ern", "smart"):
        nature, role = "monetario", "liquidita"
    elif "gold" in name or "oro " in name or " oro" in name or "physical gold" in name or tk_in("xgdu", "sgld", "gold", "phau", "sgbs"):
        nature, role = "oro", "oro"
    elif "health" in name or "salute" in name or "medical" in name or tk_in("xdwh", "hlt", "wely"):
        nature, role = "healthcare", "satellite_difensivo"
    elif "quality" in name or "qualit" in name or tk_in("iwqu", "iwfq", "iqsa"):
        nature, role = "quality_factor", "core_regionale"
    elif "real estate" in name or "immobil" in name or "reit" in name or "property" in name or tk_in("xdre", "iwda"):
        nature, role = "real_estate", "satellite_tematico"
    elif "artificial" in name or "intelligence" in name or "big data" in name or "robot" in name or "semicond" in name or tk_in("xaix", "ai4u", "aiq", "rbot", "smh"):
        nature, role = "tecnologia_ai", "satellite_crescita"
    elif "energy" in name or "energia" in name or "oil" in name or "petrol" in name or tk_in("enrg", "wnrg", "ius"):
        nature, role = "energia", "satellite_tematico"
    elif "metal" in name or "mining" in name or "miner" in name or "miniere" in name or tk_in("famamw", "spgp", "gdx"):
        nature, role = "metalli_miniere", "satellite_tematico"
    elif "commodity" in name or "commodities" in name or "materie prime" in name or "broad commodit" in name or tk_in("xdbc", "cmod", "icom"):
        nature, role = "commodities", "satellite_tematico"
    elif "ftse mib" in name or "italia" in name or "italy" in name or "mib" in name or tk_in("etfmib", "midx"):
        nature, role = "italia", "satellite_tematico"
    elif "emerging" in name or "emergenti" in name or "emerg" in name or tk_in("xmme", "emim", "iemg", "vfem"):
        nature, role = "azionario_emergenti", "core_regionale"
    elif "aggregate" in name or "bond" in name or "obbligaz" in name or "treasury" in name or "govt" in name or "bund" in name or tk_in("xbae", "aggh", "vagf", "eunh"):
        nature, role = "bond_globale", "bond"
    elif ("world" in name or "all-world" in name or "all world" in name or "global" in name or "msci acwi" in name or "developed" in name
          or tk_in("swda", "vwce", "iwda", "sppw", "vwrl", "eunl")):
        nature, role = "azionario_globale_core", "core_globale"
    elif category in ("ETF", "ETC"):
        # non riconosciuto: resta "altro" e finisce in un gruppo dedicato, NON
        # forzato nel core globale (era questo a falsare i confronti)
        nature, role = "altro", "satellite_tematico"

    return {
        "active": True,
        "state": "in_portafoglio" if in_portfolio else "candidato",
        "nature": nature,
        "role": role,
        "comparison_group": _infer_comparison_group(nature, role, ticker, name),
        "function_label": _infer_function_label(nature, role),
        "commission_mode": "non_definito",
        "pac_enabled": category != "GOV",
        "zero_commission": False,
        "ter": 0.0,
        "spread_pct": 0.0,
    }


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
            "Stato": str(sator.get("state") or inf["state"]),
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
            "state": _coerce_choice(row.get("Stato"), SATOR_STATE_VALUES, "candidato"),
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


def _fetch_ter_for_symbol(symbol: str) -> float | None:
    """Compatibilita': restituisce solo il TER (frazione) o None."""
    return _fetch_costs_for_symbol(symbol).get("ter")


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
    portfolio_returns = _build_portfolio_return_series(returns_frame, state_df, current_weights)
    correlations = _compute_correlations(returns_frame, portfolio_returns)

    ctx = SatorContext(
        data=data, settings=settings, budget=budget,
        state_df=state_df if isinstance(state_df, pd.DataFrame) else pd.DataFrame(),
        price_frame=price_frame, returns_frame=returns_frame,
        current_weights=current_weights, nature_weights=nature_weights,
        correlations=correlations, selected_categories=allowed, liquidita=liquidita,
        concentration_severity=concentration_severity,
    )

    ranking = _score_universe(ctx, cfg)
    alerts = _build_alerts(ranking, nature_weights)
    summary = {
        "budget": budget,
        "liquidita_corrente": liquidita,
        "investible_categories": list(allowed),
        "universe_count": int(len(ranking)),
        "watchlist_count": int((ranking["state"] == "watchlist").sum()) if not ranking.empty else 0,
        "candidate_count": int((ranking["state"] == "candidato").sum()) if not ranking.empty else 0,
        "storico_incompleto": int((~ranking["storico_sufficiente"]).sum()) if not ranking.empty else 0,
    }
    return {"summary": summary, "ranking": ranking, "alerts": alerts, "scenarios": {}, "sator_settings": cfg}


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
    metrics_batch = _compute_all_metrics_batch(all_tickers, ctx.price_frame)

    rows = []
    for item in ctx.data.get("strumenti", []) or []:
        ticker = str(item.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        sator = ((master.get(ticker, {}).get("manual_overrides") or {}).get("sator") or {})
        inf = infer_sator_metadata(item, ticker in positions_map)
        if not bool(sator.get("active", inf["active"])):
            continue
        state = _coerce_choice(sator.get("state", inf["state"]), SATOR_STATE_VALUES, inf["state"])
        if state in ("escluso", "fuori_piano"):
            continue
        category = macro_cat(str(item.get("tipo") or ""))
        if category not in ctx.selected_categories:
            continue
        if state == "watchlist" and not cfg.get("include_watchlist", True):
            continue
        if state == "candidato" and not cfg.get("include_candidates", True):
            continue
        in_ptf = _safe_float(positions_map.get(ticker, {}).get("Quote"), 0.0) > 1e-9
        if in_ptf and not cfg.get("include_portfolio", True):
            continue

        unit_price = _safe_float(item.get("prezzo"), latest.get(ticker, 0.0))
        if unit_price <= 0:
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
            "commission_mode": str(sator.get("commission_mode") or inf["commission_mode"]),
            "pac_enabled": bool(sator.get("pac_enabled", inf["pac_enabled"])),
            "zero_commission": bool(sator.get("zero_commission", inf["zero_commission"])),
            "ter": _safe_float(sator.get("ter", inf["ter"]), 0.0),
            "spread_pct": _safe_float(sator.get("spread_pct", inf["spread_pct"]), 0.0),
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

    df["strategic_fit"] = df.apply(_score_fit, axis=1)
    df["tactical_momentum"] = df.apply(_score_momentum, axis=1)
    df["risk_efficiency"] = df.apply(_score_risk, axis=1)
    df["diversification_benefit"] = df.apply(_score_diversification, axis=1)
    df["cost_efficiency"] = df.apply(lambda r: _score_cost(r, ctx.budget), axis=1)

    # Voto = somma pesata ESCLUSIVAMENTE dei cinque fattori mostrati in tabella.
    # Nessun termine nascosto: cosi' il numero che l'utente legge coincide sempre
    # con le cinque barre. La concentrazione c'e' eccome, ma resta VISIBILE, perche'
    # gia' incorporata in Fit (termine sulla linea sovrappesata) e in
    # Diversificazione (s_linea): non va sottratta una seconda volta al totale.
    weights = cfg.get("score_weights", PESI_DIMENSIONI)
    df["score_finale"] = sum(df[k] * _safe_float(weights.get(k), PESI_DIMENSIONI[k]) for k in PESI_DIMENSIONI).clip(0.0, 1.0)
    df["voto"] = (1.0 + df["score_finale"] * 9.0).round(1)
    df["storico_sufficiente"] = df["n_punti"] >= MIN_PUNTI_STORICO

    # classifica unica: lo stesso punteggio che si vede ordina le righe
    df = df.sort_values("score_finale", ascending=False).reset_index(drop=True)
    df["rank_totale"] = df["score_finale"].rank(ascending=False, method="first").astype(int)
    df["rango_gruppo"] = df.groupby("comparison_group")["score_finale"].rank(ascending=False, method="first").astype(int)
    df["challenger_flag"] = np.where(df["in_portfolio"], "Incumbent",
                              np.where(df["state"] == "watchlist", "Watchlist", "Challenger"))
    df["selection_reason"] = _build_comparative_reasons(df)
    return df


# --------------------------------------------------------------------------- #
# Le cinque dimensioni (scala assoluta 0-1)
# --------------------------------------------------------------------------- #

def _score_fit(row: pd.Series) -> float:
    cap = CAP_MORBIDO_NATURA.get(str(row.get("nature")), CAP_MORBIDO_DEFAULT)
    riempimento = min(1.5, _safe_float(row.get("nature_weight"), 0.0) / cap) if cap > 0 else 1.0
    concentrazione_linea = min(1.5, _safe_float(row.get("current_weight"), 0.0) / cap) if cap > 0 else 0.0
    score = 0.55 + float(np.clip((1.0 - riempimento) * 0.45, -0.35, 0.30))
    # penalita' per la linea gia' sovrappesata, scalata dalla severita' scelta
    # dall'utente (0 = ignora la concentrazione, 1 = standard, 2 = doppia).
    severita = _safe_float(row.get("_sev"), 1.0)
    score -= float(np.clip(concentrazione_linea * 0.22, 0.0, 0.25)) * severita
    if str(row.get("role")) in {"core_globale", "core_regionale", "core_difensivo"}:
        score += 0.05
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


def _score_diversification(row: pd.Series) -> float:
    cap = CAP_MORBIDO_NATURA.get(str(row.get("nature")), CAP_MORBIDO_DEFAULT)
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
    suggerite = _suggested_quotes(work, budget, max_lines=max_lines)
    ranghi = pd.to_numeric(work["rango_gruppo"], errors="coerce").fillna(0).astype(int).tolist()

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
        "Sug": [int(q) for q in suggerite],
        "Gruppo": work["function_label"].astype(str),
        "_ticker": work["ticker"].astype(str),
        "_isin": work.get("isin", pd.Series("", index=work.index)).fillna("").astype(str),
        "_name": work["name"].astype(str),
        "_state": work["state"].astype(str),
        "_price": pd.to_numeric(work["unit_price"], errors="coerce").fillna(0.0),
        "_score": pd.to_numeric(work["score_finale"], errors="coerce").fillna(0.0),
        "_fit": pd.to_numeric(work["strategic_fit"], errors="coerce").fillna(0.0),
        "_mom": pd.to_numeric(work["tactical_momentum"], errors="coerce").fillna(0.0),
        "_risk": pd.to_numeric(work["risk_efficiency"], errors="coerce").fillna(0.0),
        "_div": pd.to_numeric(work["diversification_benefit"], errors="coerce").fillna(0.0),
        "_cost": pd.to_numeric(work["cost_efficiency"], errors="coerce").fillna(0.0),
        "_rango_gruppo": pd.to_numeric(work["rango_gruppo"], errors="coerce").fillna(0).astype(int),
        "_bucket": work["role"].astype(str).map(_role_bucket),
        "_funzione": work["function_label"].astype(str),
        "_storico_ok": work["storico_sufficiente"].astype(bool),
        "_why": work["selection_reason"].astype(str),
    })
    return frame


def _role_bucket(role: str) -> str:
    role = str(role or "")
    if role in {"core_globale", "core_regionale", "core_difensivo"}:
        return "Core"
    if role in {"liquidita", "bond", "oro", "satellite_difensivo"}:
        return "Difensivo"
    return "Satellite"


def _suggested_quotes(ranking_df: pd.DataFrame, budget: float, *, max_lines: int = MAX_LINEE_SUGGERITE) -> list[int]:
    """Allocazione suggerita trasparente, a quote intere, entro budget.

    Logica leggibile: si scorrono le funzioni in ordine di voto e si prende il
    miglior candidato di ciascuna (il vincitore del gruppo). Si assegna prima 1
    quota a testa nei limiti del budget, poi si aggiungono quote ai voti piu'
    alti senza superare il tetto per linea. NON e' obbligatorio spendere tutto:
    il residuo resta liquido. Cosi' "quante quote" e' una conseguenza diretta e
    spiegabile del voto, non un riempimento forzato.
    """
    n = len(ranking_df)
    quote = [0] * n
    if budget <= 0 or n == 0:
        return quote
    df = ranking_df.reset_index(drop=True)
    cap_linea = budget * 0.35
    # un solo candidato per funzione: il migliore del gruppo. Calcolato qui,
    # senza dipendere da colonne derivate eventualmente assenti.
    if "comparison_group" in df.columns:
        gruppi = df["comparison_group"].astype(str)
    else:
        gruppi = pd.Series([str(i) for i in range(n)], index=df.index)
    migliori = df.groupby(gruppi)["score_finale"].idxmax().tolist()
    candidati = [
        (int(i), _safe_float(df.loc[i, "score_finale"]), _safe_float(df.loc[i, "unit_price"]))
        for i in migliori
        if 0 < _safe_float(df.loc[i, "unit_price"]) <= budget
    ]
    candidati.sort(key=lambda x: (-x[1], x[2]))
    # equilibrio: si servono al massimo le MIGLIORI funzioni per voto, per evitare
    # dieci righe minuscole. Il resto del budget resta liquido (residuo ammesso).
    candidati = candidati[: max(1, int(max_lines or MAX_LINEE_SUGGERITE))]
    speso = 0.0
    for i, _score, price in candidati:
        if speso + price <= budget:
            quote[i] = 1
            speso += price
    progredito = True
    while progredito:
        progredito = False
        for i, _score, price in candidati:
            if speso + price > budget:
                continue
            if (quote[i] + 1) * price > cap_linea:
                continue
            quote[i] += 1
            speso += price
            progredito = True
    return quote


# --------------------------------------------------------------------------- #
# Alert onesti (legati alle spiegazioni)
# --------------------------------------------------------------------------- #

def _build_alerts(ranking: pd.DataFrame, nature_weights: dict[str, float]) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    if ranking is None or ranking.empty:
        return alerts
    for nature, peso in nature_weights.items():
        cap = CAP_MORBIDO_NATURA.get(nature, CAP_MORBIDO_DEFAULT)
        if peso > cap * 1.25:
            alerts.append({"level": "warning", "title": "Concentrazione elevata",
                           "message": f"La funzione \"{nature.replace('_', ' ')}\" pesa {peso:.0%} (soglia indicativa {cap:.0%}): "
                                      "il fit e la diversificazione dei titoli con questa natura sono penalizzati di conseguenza."})
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

def _compute_metrics(ticker: str, price_frame: pd.DataFrame) -> dict[str, float]:
    metrics = {k: np.nan for k in ("ret_1m", "ret_3m", "ret_6m", "ret_12m", "vol", "drawdown", "rend_vol")}
    metrics["n_punti"] = 0.0
    if price_frame is None or price_frame.empty or ticker not in price_frame.columns:
        return metrics
    serie = pd.to_numeric(price_frame[ticker], errors="coerce").dropna().astype(float)
    serie = serie[serie > 0]
    metrics["n_punti"] = float(len(serie))
    if len(serie) < 3:
        return metrics
    for k, w in FINESTRE.items():
        metrics[k] = _rolling_return(serie, w)
    rendimenti = serie.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    if len(rendimenti) >= 10:
        fin = rendimenti.tail(126) if len(rendimenti) >= 126 else rendimenti
        metrics["vol"] = float(fin.std(ddof=1) * math.sqrt(252))
    metrics["drawdown"] = float(((serie / serie.cummax()) - 1.0).min())
    if pd.notna(metrics["ret_6m"]) and pd.notna(metrics["vol"]) and metrics["vol"] > 1e-9:
        rend_annuo = (1.0 + metrics["ret_6m"]) ** 2 - 1.0
        metrics["rend_vol"] = float(rend_annuo / metrics["vol"])
    return metrics


def _rolling_return(serie: pd.Series, finestra: int) -> float:
    if len(serie) <= finestra or finestra <= 0:
        return np.nan
    inizio = float(serie.iloc[-1 - finestra])
    fine = float(serie.iloc[-1])
    return (fine / inizio) - 1.0 if inizio > 0 else np.nan


def _compute_all_metrics_batch(tickers: list[str], price_frame: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Versione vettorizzata di _compute_metrics: calcola tutte le metriche per tutti
    i ticker in una sola passata sul DataFrame invece di N passate separate."""
    _empty: dict[str, float] = {k: np.nan for k in ("ret_1m", "ret_3m", "ret_6m", "ret_12m", "vol", "drawdown", "rend_vol")}
    _empty["n_punti"] = 0.0
    if not tickers or price_frame is None or price_frame.empty:
        return {t: dict(_empty) for t in tickers}
    cols = [t for t in tickers if t in price_frame.columns]
    if not cols:
        return {t: dict(_empty) for t in tickers}

    frame = price_frame[cols].apply(pd.to_numeric, errors="coerce")
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

    pct = frame.pct_change().replace([np.inf, -np.inf], np.nan)
    tail = pct.tail(126)
    vol = tail.std(ddof=1) * math.sqrt(252)
    vol = vol.where(tail.notna().sum() >= 10)

    dd = (frame / frame.cummax() - 1.0).min()

    ret_6m = ret_series.get("ret_6m", pd.Series(np.nan, index=frame.columns))
    rend_annuo = (1.0 + ret_6m) ** 2 - 1.0
    rend_vol = (rend_annuo / vol).where(vol > 1e-9)

    n_dict = frame.notna().sum().to_dict()
    vol_dict = vol.to_dict()
    dd_dict = dd.to_dict()
    rv_dict = rend_vol.to_dict()
    ret_dicts = {k: s.to_dict() for k, s in ret_series.items()}

    result: dict[str, dict[str, float]] = {}
    for t in tickers:
        if t not in cols:
            result[t] = dict(_empty)
            continue
        m: dict[str, float] = {"n_punti": float(n_dict.get(t, 0.0) or 0.0)}
        for k, rd in ret_dicts.items():
            v = rd.get(t, np.nan)
            m[k] = float(v) if pd.notna(v) else np.nan
        for attr, d in (("vol", vol_dict), ("drawdown", dd_dict), ("rend_vol", rv_dict)):
            v = d.get(t, np.nan)
            m[attr] = float(v) if pd.notna(v) else np.nan
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
    if returns_frame is None or returns_frame.empty or not weights:
        return pd.Series(dtype=float)
    cols = [t for t in weights if t in returns_frame.columns and weights[t] > 0]
    if not cols:
        return pd.Series(dtype=float)
    tot = sum(weights[t] for t in cols)
    w = pd.Series({t: weights[t] / tot for t in cols})
    return returns_frame[cols].fillna(0.0).mul(w, axis=1).sum(axis=1)


def _compute_correlations(returns_frame: pd.DataFrame, portfolio_returns: pd.Series) -> dict[str, float]:
    if returns_frame is None or returns_frame.empty or portfolio_returns is None or portfolio_returns.empty:
        return {}
    common = returns_frame.index.intersection(portfolio_returns.index)
    if len(common) < 15:
        return {}
    rf = returns_frame.loc[common]
    pt = portfolio_returns.loc[common]
    valid_pairs = rf.notna().mul(pt.notna(), axis=0).sum()
    corr_all = rf.corrwith(pt)
    return {
        str(col): float(corr_all[col])
        for col in corr_all.index
        if valid_pairs.get(col, 0) >= 15 and pd.notna(corr_all[col])
    }


def _compute_current_weights(state_df: pd.DataFrame) -> dict[str, float]:
    if state_df is None or state_df.empty or "Controvalore" not in state_df.columns:
        return {}
    tot = _safe_float(pd.to_numeric(state_df["Controvalore"], errors="coerce").fillna(0.0).sum(), 0.0)
    if tot <= 0:
        return {}
    out = {}
    for _, row in state_df.iterrows():
        t = str(row.get("Ticker") or "").strip().upper()
        if t:
            out[t] = _safe_float(row.get("Controvalore"), 0.0) / tot
    return out


def _compute_nature_weights(data: dict[str, Any], state_df: pd.DataFrame, current_weights: dict[str, float]) -> dict[str, float]:
    master = data.get("instrument_master", {}) if isinstance(data.get("instrument_master", {}), dict) else {}
    held = _tickers_posseduti(state_df)
    out: dict[str, float] = {}
    for item in data.get("strumenti", []) or []:
        t = str(item.get("ticker") or "").strip().upper()
        if t not in held:
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
        if _safe_float(row.get("Quote"), 0.0) > 1e-9
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
