"""
core/services/cruscotti.py — Cruscotti, operations, and core portfolio functions.

Functions for building category dashboards, operations reporting, and portfolio overview.
Pure functions - no Streamlit dependencies, no side effects.
"""
import logging
from datetime import date
from typing import Any, List
import numpy as np
import pandas as pd
from core.asset_categories import ACTIVE_CATEGORY_CODES, get_selected_category_codes
from persistence.storage import _safe_float

logger = logging.getLogger("portafoglio.core.services.cruscotti")


def calcola_proventi_netti(proventi: list[dict[str, Any]]) -> float:
    """Somma i proventi netti da cedole e dividendi normalizzati."""
    return float(sum(float(p.get("importo_netto", 0) or 0) for p in (proventi or [])))


def build_operations_report(data: dict[str, Any]) -> pd.DataFrame:
    """
    Prepara il report operazioni formattato per export/report.

    Mantiene la compatibilita' con il formato esistente usato da build_report_html.
    """
    from core.formatting import fmtds, fmt_eur_it, fmt_qty_it

    ops = pd.DataFrame(data.get("operazioni", [])).copy() if data.get("operazioni") else pd.DataFrame()
    if ops.empty:
        return ops

    ops["Data"] = ops["data"].apply(fmtds)
    ops["Prezzo"] = ops["price"].apply(lambda v: fmt_eur_it(v, 4))
    ops["Commissioni"] = ops["comm"].apply(lambda v: fmt_eur_it(v, 2))
    ops["Capitale netto"] = ops.apply(
        lambda r: -(r["qty"] * r["price"] + r.get("comm", 0))
        if r["tipo"] == "ACQUISTO"
        else (r["qty"] * r["price"] - r.get("comm", 0)),
        axis=1
    ).apply(lambda v: fmt_eur_it(v, 2, signed=True))
    ops["Quantità"] = ops.apply(
        lambda r: fmt_qty_it(-r["qty"], 4) if r["tipo"] == "VENDITA" else fmt_qty_it(r["qty"], 4),
        axis=1
    )
    return ops.rename(columns={"ticker": "Ticker", "tipo": "Operazione", "note": "Note"})[
        ["Data", "Ticker", "Operazione", "Quantità", "Prezzo", "Commissioni", "Capitale netto", "Note"]
    ]


def estrai_posizioni_aperte_chiuse(
    df: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Separa posizioni aperte da chiuse.

    Args:
        df: DataFrame completo

    Returns:
        (df_aperte, df_chiuse)
    """
    if df is None or df.empty:
        return pd.DataFrame(), pd.DataFrame()

    da = df[df["Quote"] > 0.0001].copy()
    dc = df[df["Quote"] <= 0.0001].copy()
    return da, dc


def build_macro_summary_report(
    df_aperte: pd.DataFrame,
    tv: float,
    settings: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """
    Crea report sommario per macro categoria.

    Args:
        df_aperte: Posizioni aperte
        tv: Valore totale portafoglio

    Returns:
        DataFrame con colonne: Tipologia, Costo, Controvalore, Peso %, P/L €, P/L %
    """
    from persistence.storage import macro_cat

    if df_aperte is None or df_aperte.empty:
        return pd.DataFrame(
            columns=["Tipologia", "Costo", "Controvalore", "Peso %", "P/L €", "P/L %"]
        )

    df_aperte = df_aperte.copy()
    df_aperte["Categoria"] = df_aperte["Tipo"].apply(macro_cat)

    visible_categories = list(get_selected_category_codes(settings))
    report = (
        df_aperte.groupby("Categoria")
        .agg(Costo=("Costo", "sum"), Controvalore=("Controvalore", "sum"), PLe=("P/L €", "sum"))
        .reindex(visible_categories)
        .fillna(0)
        .reset_index()
    )

    report["Peso %"] = report["Controvalore"] / tv if tv > 0 else 0
    report["P/L %"] = report.apply(
        lambda r: r["PLe"] / abs(r["Costo"]) if abs(r["Costo"]) > 0.001 else 0,
        axis=1
    )

    report = report.rename(columns={"Categoria": "Tipologia", "PLe": "P/L €"})
    return report[["Tipologia", "Costo", "Controvalore", "Peso %", "P/L €", "P/L %"]]


def get_category_allocation_breakdown(
    df_aperte: pd.DataFrame,
    settings: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """
    Aggrega controvalore, costo e P/L per macro-categoria.

    Args:
        df_aperte: Posizioni aperte

    Returns:
        DataFrame con Categoria, Controvalore, Costo, P/L €, Comm., P/L %
    """
    from persistence.storage import macro_cat

    if df_aperte is None or df_aperte.empty:
        return pd.DataFrame(columns=["Categoria", "Controvalore", "Costo", "P/L €", "Comm.", "P/L %"])

    da_cat = df_aperte.copy()
    if "Categoria" not in da_cat.columns:
        da_cat["Categoria"] = da_cat["Tipo"].apply(macro_cat)

    visible_categories = list(get_selected_category_codes(settings))
    agg = (
        da_cat.groupby("Categoria")
        .agg({"Controvalore": "sum", "Costo": "sum", "P/L €": "sum", "Comm.": "sum"})
        .reindex(visible_categories)
        .dropna(how="all")
        .reset_index()
    )
    agg = agg[agg["Controvalore"].fillna(0) > 0]
    if agg.empty:
        return agg
    agg["P/L %"] = agg.apply(
        lambda r: r["P/L €"] / abs(r["Costo"]) if abs(r["Costo"]) > 0.001 else 0,
        axis=1
    )
    return agg


def category_value_pl_items(
    df_aperte: pd.DataFrame,
    settings: dict[str, Any] | None = None,
) -> list[tuple[str, str, str, str]]:
    """Build triplet items for category KPI cards."""
    from core.formatting import fmt_eur_it
    from core.asset_categories import get_selected_category_codes

    if df_aperte is None or df_aperte.empty or "Categoria" not in df_aperte.columns:
        return []

    items = []
    visible_categories = list(get_selected_category_codes(settings))
    for cat in visible_categories:
        cat_data = df_aperte[df_aperte["Categoria"] == cat]
        if not cat_data.empty:
            cat_value = fmt_eur_it(cat_data["Controvalore"].sum(), 0)
            cat_pl = cat_data["P/L €"].sum() if "P/L €" in cat_data.columns else 0.0
            cat_pl_str = fmt_eur_it(cat_pl, 0, signed=True)
            items.append((cat, cat_value, cat_pl_str, "green" if cat_pl >= 0 else "red"))
    return items


_NATURE_TO_RADAR_AXIS = {
    "azionario_globale_core": "Azionario", "azionario_emergenti": "Azionario",
    "tecnologia_ai": "Azionario", "healthcare": "Azionario", "energia": "Azionario",
    "italia": "Azionario", "quality_factor": "Azionario",
    "monetario": "Liquidità",
    "bond_governativo": "Obbligazionario governativo",
    "bond_globale": "Obbligazionario corporate",
    "oro": "Materie prime", "metalli_miniere": "Materie prime", "commodities": "Materie prime",
    "real_estate": "Immobiliare",
}
# Stessa classificazione nature->bucket gia' usata da infer_sator_metadata/_role_bucket
# in core/services/sator.py: riprodotta qui per evitare un import circolare (cruscotti -> sator
# esiste gia' altrove nel modulo, ma solo a runtime dentro le funzioni).
_NATURE_TO_BUCKET = {
    "azionario_globale_core": "core", "azionario_emergenti": "core", "quality_factor": "core",
    "monetario": "difensivo", "oro": "difensivo", "healthcare": "difensivo",
    "bond_governativo": "difensivo", "bond_globale": "difensivo",
    "tecnologia_ai": "satellite", "energia": "satellite", "metalli_miniere": "satellite",
    "commodities": "satellite", "italia": "satellite", "real_estate": "satellite",
}
_RADAR_QUANTITATIVE_AXES = [
    "Azionario", "Obbligazionario governativo", "Obbligazionario corporate",
    "Liquidità", "Materie prime", "Immobiliare", "Alternativi", "Criptovalute",
]


def _derive_quantitative_radar_target(portfolio_objective: dict[str, float] | None, concentration_caps: dict[str, float] | None) -> dict[str, float]:
    """8 assi quantitativi del radar, derivati dall'obiettivo Core/Difensivo/Satellite
    e dai cap di concentrazione per natura (entrambi editabili dall'utente in
    Pianificazione) — nessun preset separato, nessun valore nascosto."""
    objective = portfolio_objective or {}
    caps = concentration_caps or {}
    out = {axis: 0.0 for axis in _RADAR_QUANTITATIVE_AXES}
    for bucket_key in ("core", "difensivo", "satellite"):
        bucket_target_pct = float(objective.get(bucket_key, 0.0)) * 100.0
        natures_in_bucket = [n for n, b in _NATURE_TO_BUCKET.items() if b == bucket_key]
        cap_total = sum(float(caps.get(n, 0.0)) for n in natures_in_bucket)
        if cap_total <= 0:
            continue
        for nature in natures_in_bucket:
            axis = _NATURE_TO_RADAR_AXIS[nature]
            share = float(caps.get(nature, 0.0)) / cap_total
            out[axis] += bucket_target_pct * share
    return out


# Ancore di interpolazione: valori gia' presenti nel vecchio RADAR_PROFILE_PRESETS
# per i profili "Prudente" e "Dinamico", riusati come estremi di una scala continua
# invece che come 4 nomi discreti.
_RADAR_QUALITATIVE_ANCHORS = {
    "Rendimento atteso": (5.8, 8.0),
    "Volatilità": (8.6, 5.8),
    "Liquidità": (8.4, 7.0),
    "Esposizione valutaria": (8.0, 5.8),
    "Duration": (8.2, 5.8),
}
# Assi senza una tendenza chiara nei vecchi preset: restano fissi al valore
# "Equilibrato" storico, invece di inventare una formula arbitraria.
_RADAR_QUALITATIVE_FIXED = {
    "Diversificazione": 8.0,
    "Costi contenuti": 7.5,
    "Profilo ESG": 6.5,
}
_SATELLITE_SHARE_LOW = 0.10   # quota satellite del vecchio profilo "Prudente"
_SATELLITE_SHARE_HIGH = 0.35  # quota satellite del vecchio profilo "Dinamico"


def _derive_qualitative_radar_target(portfolio_objective: dict[str, float] | None) -> dict[str, float]:
    satellite = float((portfolio_objective or {}).get("satellite", 0.20))
    span = _SATELLITE_SHARE_HIGH - _SATELLITE_SHARE_LOW
    t = max(0.0, min(1.0, (satellite - _SATELLITE_SHARE_LOW) / span)) if span > 0 else 0.5
    out = {axis: lo + t * (hi - lo) for axis, (lo, hi) in _RADAR_QUALITATIVE_ANCHORS.items()}
    out.update(_RADAR_QUALITATIVE_FIXED)
    return out


def build_portfolio_radar_payload(
    df_aperte: pd.DataFrame,
    liquidita: float,
    portfolio_objective: dict[str, float] | None = None,
    concentration_caps: dict[str, float] | None = None,
    strumenti: list | None = None,
) -> dict[str, Any]:
    """Costruisce il payload reale per i due radar della home.

    Il radar quantitativo usa i pesi economici reali del portafoglio.
    Il radar qualitativo usa uno scoring euristico costruito sulla composizione reale.
    """
    from core.asset_categories import infer_category_code

    def _portfolio_text_blob(row: pd.Series) -> str:
        parts = [
            str(row.get("Ticker") or ""),
            str(row.get("Strumento") or ""),
            str(row.get("Tipo") or row.get("tipo") or ""),
        ]
        return " | ".join(parts).lower()

    # Enrichment lookup: ticker → strumento dict
    _enr: dict[str, dict] = {}
    for _s in (strumenti or []):
        _tk = str(_s.get("ticker") or "").strip()
        if _tk:
            _enr[_tk] = _s

    def _parse_it_float(s) -> float | None:
        """Parse Italian-format number string ('1,23%', '+ 47,38%') → float or None."""
        if s is None:
            return None
        try:
            cleaned = str(s).replace("%", "").replace("+", "").replace(" ", "").replace(",", ".")
            return float(cleaned)
        except (ValueError, TypeError):
            return None

    def _classify_radar_asset_class(row: pd.Series) -> str:
        txt = _portfolio_text_blob(row)
        category_code = infer_category_code(str(row.get("Tipo") or row.get("tipo") or ""), default="ALTRO")

        if any(token in txt for token in ("bitcoin", "btc", "ethereum", "eth", "crypto", "cript")):
            return "Criptovalute"
        if any(token in txt for token in ("reit", "real estate", "immob", "property")):
            return "Immobiliare"
        if any(token in txt for token in ("commod", "commodity", "materie prime", "gold", "silver", "oil", "gas", "metals", "agri")):
            return "Materie prime"
        if any(token in txt for token in ("hedge", "private", "alternative", "alternativ", "multi strategy", "absolute return")):
            return "Alternativi"
        if category_code == "GOV" or any(token in txt for token in ("btp", "bot", "cct", "gov", "sovran", "treasury", "titolo di stato")):
            return "Obbligazionario governativo"
        if category_code == "LIQ" or any(token in txt for token in ("liquid", "cash", "monetario", "overnight", "deposito", "conto")):
            return "Liquidità"
        if category_code == "OBB" or any(token in txt for token in ("corporate", "credit", "high yield", "aggregate bond", "bond", "obblig")):
            return "Obbligazionario corporate"
        if category_code == "ETF" and any(token in txt for token in ("bond", "aggregate", "corporate", "credit", "high yield", "fixed income")):
            return "Obbligazionario corporate"
        if category_code == "FND" and any(token in txt for token in ("obblig", "bond", "credit", "fixed income", "corporate")):
            return "Obbligazionario corporate"
        return "Azionario"

    def _build_quantitative_radar_weights(df_aperte: pd.DataFrame, liquidita: float) -> dict[str, float]:
        axes = [
            "Azionario",
            "Obbligazionario governativo",
            "Obbligazionario corporate",
            "Liquidità",
            "Materie prime",
            "Immobiliare",
            "Alternativi",
            "Criptovalute",
        ]
        weights = {axis: 0.0 for axis in axes}
        work = df_aperte.copy() if df_aperte is not None else pd.DataFrame()
        if work.empty and float(liquidita or 0.0) <= 0:
            return weights
        if not work.empty:
            work["Controvalore"] = pd.to_numeric(work.get("Controvalore"), errors="coerce").fillna(0.0)
            for _, row in work.iterrows():
                asset_class = _classify_radar_asset_class(row)
                weights[asset_class] += float(row.get("Controvalore", 0.0) or 0.0)
        if float(liquidita or 0.0) > 0:
            weights["Liquidità"] += float(liquidita or 0.0)
        total = sum(weights.values())
        if total <= 0:
            return weights
        return {k: (v / total) * 100.0 for k, v in weights.items()}

    def _score_quality_profile(
        quantitative_weights: dict[str, float],
        df_aperte: pd.DataFrame,
        enrichment_map: dict[str, dict],
    ) -> tuple[dict[str, float], dict[str, str]]:
        weights_ratio = {k: float(v or 0.0) / 100.0 for k, v in quantitative_weights.items()}
        expected_return_assumptions = {
            "Azionario": 7.0,
            "Obbligazionario governativo": 3.0,
            "Obbligazionario corporate": 4.2,
            "Liquidità": 1.5,
            "Materie prime": 4.5,
            "Immobiliare": 5.0,
            "Alternativi": 5.0,
            "Criptovalute": 8.5,
        }
        risk_assumptions = {
            "Azionario": 6.8,
            "Obbligazionario governativo": 2.3,
            "Obbligazionario corporate": 3.4,
            "Liquidità": 0.8,
            "Materie prime": 6.5,
            "Immobiliare": 5.1,
            "Alternativi": 6.0,
            "Criptovalute": 10.0,
        }
        liquidity_assumptions = {
            "Azionario": 8.0,
            "Obbligazionario governativo": 6.8,
            "Obbligazionario corporate": 6.0,
            "Liquidità": 10.0,
            "Materie prime": 8.0,
            "Immobiliare": 4.5,
            "Alternativi": 4.0,
            "Criptovalute": 8.5,
        }

        weighted_return = sum(weights_ratio[k] * expected_return_assumptions[k] for k in weights_ratio)
        weighted_risk = sum(weights_ratio[k] * risk_assumptions[k] for k in weights_ratio)
        weighted_liquidity = sum(weights_ratio[k] * liquidity_assumptions[k] for k in weights_ratio)

        hhi = sum(v * v for v in weights_ratio.values())
        diversification_score = max(0.0, min(10.0, (1.0 - hhi) * 12.0))

        work = df_aperte.copy() if df_aperte is not None else pd.DataFrame()
        if not work.empty:
            work["Costo"] = pd.to_numeric(work.get("Costo"), errors="coerce").fillna(0.0)
            work["Controvalore"] = pd.to_numeric(work.get("Controvalore"), errors="coerce").fillna(0.0)
            total_value = float(work["Controvalore"].sum()) or 1.0
            _macro_scores = {"GOV": 9.0, "ETF": 8.2, "FND": 5.8}
            cost_scores = []
            fx_penalties = []
            esg_scores = []
            duration_contributions: list[tuple[float, float]] = []
            ter_real_count = 0
            for _, row in work.iterrows():
                weight = float(row.get("Controvalore", 0.0) or 0.0) / total_value
                tipo = str(row.get("Tipo") or row.get("tipo") or "")
                txt = _portfolio_text_blob(row)
                ticker = str(row.get("Ticker") or row.get("ticker") or "").strip()
                enriched = enrichment_map.get(ticker, {})
                # TER: use real value if available, else heuristic by category
                ter_pct = _parse_it_float(enriched.get("ter"))
                if ter_pct is not None:
                    macro_score = max(0.0, min(10.0, 10.0 - ter_pct * 2.5))
                    ter_real_count += 1
                else:
                    macro = str(tipo)
                    macro_score = _macro_scores.get(
                        macro if macro in _macro_scores else (
                            "GOV" if "btp" in txt or "gov" in txt else
                            "ETF" if "etf" in txt else "FND"
                        ),
                        6.5,
                    )
                cost_scores.append(weight * macro_score)
                foreign_flag = any(token in txt for token in ("world", "global", "msci", "nasdaq", "s&p", "sp500", "usa", "us ", "emerging", "japan", "pacific"))
                fx_penalties.append(weight * (1.0 if foreign_flag else 0.2))
                esg_bonus = 8.5 if any(token in txt for token in ("esg", "sri", "sustain", "climate", "clean")) else 5.8
                esg_scores.append(weight * esg_bonus)
                # Duration: collect real data points
                dur_val = _parse_it_float(enriched.get("duration_modificata"))
                if dur_val is not None and weight > 0:
                    duration_contributions.append((weight, dur_val))
            costs_contained = max(0.0, min(10.0, sum(cost_scores)))
            fx_score = max(0.0, min(10.0, 10.0 - (sum(fx_penalties) * 6.0)))
            esg_score = max(0.0, min(10.0, sum(esg_scores)))
        else:
            costs_contained = 6.0
            fx_score = 6.0
            esg_score = 5.5
            duration_contributions = []
            ter_real_count = 0

        bond_share = weights_ratio["Obbligazionario governativo"] + weights_ratio["Obbligazionario corporate"]
        if duration_contributions:
            total_dur_weight = sum(w for w, _ in duration_contributions)
            avg_duration = sum(w * d for w, d in duration_contributions) / total_dur_weight if total_dur_weight > 0 else 0.0
            duration_score = max(0.0, min(10.0, 10.0 - avg_duration * 0.6))
            _duration_real = True
        else:
            avg_duration = None
            duration_score = max(0.0, min(10.0, 10.0 - (abs(bond_share - 0.45) / 0.45) * 6.0))
            _duration_real = False
        scores = {
            "Rendimento atteso": max(0.0, min(10.0, weighted_return)),
            "Volatilità": max(0.0, min(10.0, 10.0 - weighted_risk)),
            "Liquidità": max(0.0, min(10.0, weighted_liquidity)),
            "Diversificazione": diversification_score,
            "Costi contenuti": costs_contained,
            "Esposizione valutaria": fx_score,
            "Duration": duration_score,
            "Profilo ESG": esg_score,
        }

        def _fmt_terms(assumptions: dict[str, float]) -> str:
            terms = []
            for axis in quantitative_weights:
                weight_pct = float(quantitative_weights.get(axis, 0.0) or 0.0)
                if weight_pct <= 0:
                    continue
                terms.append(f"{weight_pct:.2f}%×{assumptions[axis]:.1f}")
            return " + ".join(terms) if terms else "nessun peso attivo"

        diagnostics = {
            "Rendimento atteso": (
                f"Leggo il peso di ogni asset class e lo moltiplico per un rendimento atteso convenzionale: "
                f"Azionario 7.0, Governativo 3.0, Corporate 4.2, Liquidità 1.5, Materie prime 4.5, Immobiliare 5.0, Alternativi 5.0, Criptovalute 8.5. "
                f"Nel tuo portafoglio la sostituzione è: {_fmt_terms(expected_return_assumptions)} = {weighted_return:.2f}. "
                f"Quindi il valore sale se cresce il peso delle classi a rendimento atteso più alto."
            ),
            "Volatilità": (
                f"Assegno a ogni asset class un rischio convenzionale: Azionario 6.8, Governativo 2.3, Corporate 3.4, Liquidità 0.8, Materie prime 6.5, Immobiliare 5.1, Alternativi 6.0, Criptovalute 10.0. "
                f"Faccio la media pesata di questi rischi e poi la trasformo in uno score desiderabile con la formula 10 - rischio medio pesato. "
                f"Nel tuo caso: 10 - ({_fmt_terms(risk_assumptions)}) = {scores['Volatilità']:.2f}."
            ),
            "Liquidità": (
                f"Assegno a ogni asset class un punteggio di facilità di smobilizzo: Azionario 8.0, Governativo 6.8, Corporate 6.0, Liquidità 10.0, Materie prime 8.0, Immobiliare 4.5, Alternativi 4.0, Criptovalute 8.5. "
                f"Poi faccio la media pesata sui pesi reali del portafoglio. "
                f"Nel tuo caso: {_fmt_terms(liquidity_assumptions)} = {scores['Liquidità']:.2f}."
            ),
            "Diversificazione": (
                f"Guardo quanto il portafoglio è distribuito tra le 8 asset class. "
                f"Uso l'indice HHI, che cresce quando il peso è concentrato su poche classi. "
                f"Poi trasformo quel valore in uno score dove alto = più diversificazione. "
                f"Nel tuo caso HHI = {hhi:.4f}, quindi lo score finale è {scores['Diversificazione']:.2f}. "
                f"Se poche classi dominano il portafoglio, questo indicatore scende rapidamente."
            ),
            "Costi contenuti": (
                (
                    f"Leggo il TER reale da {ter_real_count} strumenti su {len(work)} (fonte: arricchimento PDF). "
                    f"Per i restanti uso una stima per famiglia: GOV = 9.0, ETF = 8.2, FND = 5.8. "
                    f"Score TER reale: 10 − TER% × 2.5 (es. 0,5% → 8.75; 2% → 5). "
                    if ter_real_count > 0 else
                    f"Nessun dato TER reale disponibile (carica i PDF nella pagina Arricchimento). "
                    f"Uso una stima per famiglia: GOV = 9.0, ETF = 8.2, FND = 5.8. "
                ) + f"Poi faccio la media pesata per controvalore. Il risultato è {scores['Costi contenuti']:.2f}."
            ),
            "Esposizione valutaria": (
                f"Qui faccio una stima qualitativa, non una lettura precisa della valuta di ogni sottostante. "
                f"Se in ticker, nome o tipo trovo indizi come World, USA, Nasdaq, S&P, Emerging, Pacific o Japan, considero quello strumento più esposto a valute non EUR. "
                f"Parto da 10 e sottraggo una penalità proporzionale al peso di questi strumenti. "
                f"Il risultato finale è {scores['Esposizione valutaria']:.2f}. "
                f"Maggiore è la presenza di strumenti esteri non coperti, più il punteggio si abbassa."
            ),
            "Duration": (
                (
                    f"Leggo la Duration Modificata reale da {len(duration_contributions)} strumenti obbligazionari (fonte: arricchimento PDF). "
                    f"Duration media ponderata per controvalore: {avg_duration:.2f} anni. "
                    f"Score = 10 − duration × 0.6 → duration bassa = meno rischio tasso = score più alto. "
                    if _duration_real else
                    f"Nessun dato di duration reale disponibile (carica i PDF dei BTP/obbligazioni nella pagina Arricchimento). "
                    f"Uso un indicatore sintetico: quanto il peso obbligazionario totale ({bond_share * 100.0:.1f}%) si avvicina al 45% di riferimento. "
                ) + f"Score finale: {scores['Duration']:.2f}."
            ),
            "Profilo ESG": (
                f"Qui non uso rating ESG ufficiali esterni. "
                f"Leggo solo i testi disponibili nei tuoi strumenti: ticker, nome e tipo. "
                f"Se trovo parole chiave come ESG, SRI, Sustainable, Climate o Clean assegno a quello strumento 8.5; altrimenti 5.8. "
                f"Poi faccio la media pesata per controvalore. "
                f"Per questo il valore finale è {scores['Profilo ESG']:.2f}. "
                f"È quindi un indicatore orientativo, non un rating ESG ufficiale."
            ),
        }

        return scores, diagnostics

    quantitative_comparison_target = _derive_quantitative_radar_target(portfolio_objective, concentration_caps)
    qualitative_comparison_target = _derive_qualitative_radar_target(portfolio_objective)
    quantitative_weights = _build_quantitative_radar_weights(df_aperte, liquidita)
    quality_scores, quality_diagnostics = _score_quality_profile(quantitative_weights, df_aperte, _enr)

    quantitative_labels = [
        "Azionario",
        "Obbligazionario governativo",
        "Obbligazionario corporate",
        "Liquidità",
        "Materie prime",
        "Immobiliare",
        "Alternativi",
        "Criptovalute",
    ]
    qualitative_labels = [
        "Rendimento atteso",
        "Volatilità",
        "Liquidità",
        "Diversificazione",
        "Costi contenuti",
        "Esposizione valutaria",
        "Duration",
        "Profilo ESG",
    ]

    quantitative_amounts = {label: 0.0 for label in quantitative_labels}
    quantitative_tickers = {label: [] for label in quantitative_labels}
    work = df_aperte.copy() if df_aperte is not None else pd.DataFrame()
    if not work.empty:
        work["Controvalore"] = pd.to_numeric(work.get("Controvalore"), errors="coerce").fillna(0.0)
        for _, row in work.iterrows():
            asset_class = _classify_radar_asset_class(row)
            quantitative_amounts[asset_class] += float(row.get("Controvalore", 0.0) or 0.0)
            ticker = str(row.get("Ticker") or row.get("ticker") or "").strip()
            if ticker:
                quantitative_tickers[asset_class].append(ticker)
    if float(liquidita or 0.0) > 0:
        quantitative_amounts["Liquidità"] += float(liquidita or 0.0)

    quantitative_comparison = quantitative_comparison_target
    qualitative_comparison = qualitative_comparison_target

    quantitative_detail = [
        {
            "axis": label,
            "value": round(float(quantitative_weights[label]), 2),
            "amount": round(float(quantitative_amounts[label]), 2),
            "comparison": float(quantitative_comparison[label]),
            "is_outside": float(quantitative_weights[label]) > float(quantitative_comparison[label]),
            "method": (
                f"Questa asset class misura quanto pesa davvero questa famiglia sul patrimonio complessivo. "
                f"Formula: peso % = controvalore asset class / patrimonio totale incluso cash. "
                f"Qui: {quantitative_amounts[label]:.2f} / "
                f"{sum(quantitative_amounts.values()):.2f} = {quantitative_weights[label]:.2f}%. "
                f"Il totale considerato include anche la liquidità netta, se presente. "
                f"Strumenti agganciati: "
                f"{', '.join(quantitative_tickers[label]) if quantitative_tickers[label] else ('liquidità netta' if label == 'Liquidità' and float(liquidita or 0.0) > 0 else 'nessuno')}."
            ),
        }
        for label in quantitative_labels
    ]
    qualitative_detail = [
        {
            "axis": "Rendimento atteso",
            "value": round(float(quality_scores["Rendimento atteso"]), 2),
            "comparison": float(qualitative_comparison["Rendimento atteso"]),
            "is_outside": float(quality_scores["Rendimento atteso"]) < float(qualitative_comparison["Rendimento atteso"]),
            "method": quality_diagnostics["Rendimento atteso"],
        },
        {
            "axis": "Volatilità",
            "value": round(float(quality_scores["Volatilità"]), 2),
            "comparison": float(qualitative_comparison["Volatilità"]),
            "is_outside": float(quality_scores["Volatilità"]) < float(qualitative_comparison["Volatilità"]),
            "method": quality_diagnostics["Volatilità"],
        },
        {
            "axis": "Liquidità",
            "value": round(float(quality_scores["Liquidità"]), 2),
            "comparison": float(qualitative_comparison["Liquidità"]),
            "is_outside": float(quality_scores["Liquidità"]) < float(qualitative_comparison["Liquidità"]),
            "method": quality_diagnostics["Liquidità"],
        },
        {
            "axis": "Diversificazione",
            "value": round(float(quality_scores["Diversificazione"]), 2),
            "comparison": float(qualitative_comparison["Diversificazione"]),
            "is_outside": float(quality_scores["Diversificazione"]) < float(qualitative_comparison["Diversificazione"]),
            "method": quality_diagnostics["Diversificazione"],
        },
        {
            "axis": "Costi contenuti",
            "value": round(float(quality_scores["Costi contenuti"]), 2),
            "comparison": float(qualitative_comparison["Costi contenuti"]),
            "is_outside": float(quality_scores["Costi contenuti"]) < float(qualitative_comparison["Costi contenuti"]),
            "method": quality_diagnostics["Costi contenuti"],
        },
        {
            "axis": "Esposizione valutaria",
            "value": round(float(quality_scores["Esposizione valutaria"]), 2),
            "comparison": float(qualitative_comparison["Esposizione valutaria"]),
            "is_outside": float(quality_scores["Esposizione valutaria"]) < float(qualitative_comparison["Esposizione valutaria"]),
            "method": quality_diagnostics["Esposizione valutaria"],
        },
        {
            "axis": "Duration",
            "value": round(float(quality_scores["Duration"]), 2),
            "comparison": float(qualitative_comparison["Duration"]),
            "is_outside": float(quality_scores["Duration"]) < float(qualitative_comparison["Duration"]),
            "method": quality_diagnostics["Duration"],
        },
        {
            "axis": "Profilo ESG",
            "value": round(float(quality_scores["Profilo ESG"]), 2),
            "comparison": float(qualitative_comparison["Profilo ESG"]),
            "is_outside": float(quality_scores["Profilo ESG"]) < float(qualitative_comparison["Profilo ESG"]),
            "method": quality_diagnostics["Profilo ESG"],
        },
    ]

    return {
        "source_note": "Dati quantitativi reali del portafoglio; confronto costruito sull'obiettivo di portafoglio Core/Difensivo/Satellite. Il qualitativo resta uno scoring euristico sulla composizione.",
        "quantitative": {
            "labels": quantitative_labels,
            "portfolio": [round(float(quantitative_weights[label]), 2) for label in quantitative_labels],
            "comparison": [float(quantitative_comparison[label]) for label in quantitative_labels],
            "comparison_name": "Obiettivo di portafoglio",
            "detail": quantitative_detail,
        },
        "qualitative": {
            "labels": qualitative_labels,
            "portfolio": [round(float(quality_scores[label]), 2) for label in qualitative_labels],
            "comparison": [float(qualitative_comparison[label]) for label in qualitative_labels],
            "comparison_name": "Obiettivo di portafoglio",
            "detail": qualitative_detail,
        },
    }


def build_category_dashboard_metrics(
    *,
    category: str,
    data: dict[str, Any],
    category_df: pd.DataFrame,
    dh_flow: pd.DataFrame | None,
    proventi: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build the KPI payload used by the Cruscotti category dashboards."""
    from core.cashflow_indices import build_group_cashflow_indices
    from core.finance import build_xirr_flows, compute_xirr

    work = category_df.copy() if category_df is not None else pd.DataFrame()
    if work.empty:
        return []

    tickers = [str(tk) for tk in work.get("Ticker", pd.Series(dtype=str)).dropna().astype(str).tolist()]
    invested = float(pd.to_numeric(work.get("Costo"), errors="coerce").fillna(0.0).sum()) if "Costo" in work.columns else 0.0
    current_value = float(pd.to_numeric(work.get("Controvalore"), errors="coerce").fillna(0.0).sum()) if "Controvalore" in work.columns else 0.0
    pl_abs = float(pd.to_numeric(work.get("P/L €"), errors="coerce").fillna(0.0).sum()) if "P/L €" in work.columns else (current_value - invested)
    simple_return = (pl_abs / invested) if abs(invested) > 1e-9 else None

    # Calcola data della prima operazione PER QUESTA CATEGORIA
    tickers_set = set(str(tk) for tk in tickers)
    first_op_date = None
    ops = sorted(data.get("operazioni", []), key=lambda x: str(x.get("data", "")))
    if tickers:
        for op in ops:
            if str(op.get("ticker", "")).strip() not in tickers_set:
                continue
            try:
                first_op_date = pd.to_datetime(op.get("data")).date()
                break
            except Exception:
                logger.warning("build_category_dashboard_metrics: data operazione non valida ignorata durante ricerca prima operazione: %r", op.get("data"), exc_info=True)
                continue
    if first_op_date is None and "Ultimo evento" in work.columns:
        last_event_series = pd.to_datetime(work["Ultimo evento"], errors="coerce").dropna()
        if not last_event_series.empty:
            first_op_date = last_event_series.min().date()

    # Giorni SPECIFICI di questa categoria
    days_total = max((date.today() - first_op_date).days, 0) if first_op_date else 0
    years_total = (days_total / 365.25) if days_total > 0 else 0.0

    # CALCOLO GIACENZA MEDIA: Σ(esborso_i × giorni_i) / giorni_totali
    avg_balance = None

    # Prova a calcolare da operazioni
    if days_total > 0 and tickers and first_op_date:
        tickers_set = set(str(tk) for tk in tickers)
        operazioni = data.get("operazioni", [])

        # Filtra solo operazioni dei ticker di questa categoria
        category_ops = [op for op in operazioni if str(op.get("ticker", "")).strip() in tickers_set]

        if category_ops:
            total_weighted = 0.0
            today = date.today()

            for op in category_ops:
                try:
                    op_data = op.get("data")
                    op_tipo = str(op.get("tipo", "")).strip().upper()

                    # Calcola importo: prova prima con "importo", poi con qty × price
                    op_importo = float(op.get("importo", 0) or 0)
                    if op_importo == 0.0:
                        qty = float(op.get("qty", 0) or 0)
                        price = float(op.get("price", 0) or 0)
                        if qty > 0 and price > 0:
                            op_importo = qty * price

                    op_date = pd.to_datetime(op_data).date()

                    # Calcola giorni da questa operazione a oggi
                    giorni_i = (today - op_date).days

                    # ACQUISTO: aggiunge al totale
                    if op_tipo in ("ACQUISTO", "VERSAMENTO", "BUY"):
                        total_weighted += op_importo * giorni_i
                    # VENDITA/RIMBORSO: sottrae dal totale
                    elif op_tipo in ("VENDITA", "RIMBORSO A SCADENZA", "PRELIEVO", "SELL"):
                        total_weighted -= op_importo * giorni_i

                except Exception:
                    logger.warning("build_category_dashboard_metrics: operazione scartata nel calcolo giacenza media, ticker=%s data=%r", op.get("ticker"), op.get("data"), exc_info=True)
                    continue

            # Divide per giorni_totali
            if days_total > 0 and abs(total_weighted) > 1e-9:
                avg_balance = float(total_weighted / days_total)

    # FALLBACK: se calcolo da operazioni non ha funzionato, usa media storica del controvalore
    if (avg_balance is None or avg_balance < 1e-9) and current_value > 1e-9 and invested > 1e-9:
        # Stima: media tra valore attuale e costo aperto
        avg_balance = (current_value + invested) / 2.0

    twr_total = None
    volatility_ann = None

    if dh_flow is not None and not dh_flow.empty and tickers:
        index_df, returns_df, values_df, _flows_df = build_group_cashflow_indices(data, dh_flow, {category: tickers})

        # Filtra i dataframe per iniziare da first_op_date della categoria
        if first_op_date is not None:
            if index_df is not None and not index_df.empty:
                index_df = index_df[index_df.index >= pd.Timestamp(first_op_date)]
            if returns_df is not None and not returns_df.empty:
                returns_df = returns_df[returns_df.index >= pd.Timestamp(first_op_date)]
            if values_df is not None and not values_df.empty:
                values_df = values_df[values_df.index >= pd.Timestamp(first_op_date)]

        # GIACENZA MEDIA: media storica dei valori nel periodo della categoria
        if avg_balance is None and values_df is not None and not values_df.empty and category in values_df.columns:
            value_series = pd.to_numeric(values_df[category], errors="coerce").dropna()
            if not value_series.empty:
                avg_balance = float(value_series.mean())

        if index_df is not None and not index_df.empty and category in index_df.columns:
            twr_series = pd.to_numeric(index_df[category], errors="coerce").dropna()
            if not twr_series.empty and abs(float(twr_series.iloc[0])) > 1e-9:
                twr_total = (float(twr_series.iloc[-1]) / float(twr_series.iloc[0])) - 1.0
        if returns_df is not None and not returns_df.empty and category in returns_df.columns:
            ret_series = pd.to_numeric(returns_df[category], errors="coerce").dropna()
            if len(ret_series) >= 2:
                volatility_ann = float(ret_series.std(ddof=0) * np.sqrt(252.0))

    avg_balance_return = (pl_abs / avg_balance) if avg_balance is not None and abs(avg_balance) > 1e-9 else None
    annualized_linear = (simple_return / years_total) if simple_return is not None and years_total > 0 else None

    xirr_value = None
    if tickers:
        flows, flow_dates = build_xirr_flows(data, work, proventi or [], tickers=tickers)
        xirr_value = compute_xirr(flows, flow_dates)

    duration_note = f"{int(days_total)} giorni • {years_total:.2f} anni" if first_op_date else "Periodo non disponibile"

    return [
        {"label": "Prima operazione", "value": first_op_date, "kind": "date_with_duration", "note": duration_note},
        {"label": "Strumenti", "value": int(len(work)), "kind": "int", "note": "Numero strumenti in portafoglio"},
        {"label": "Totale investito", "value": invested, "kind": "eur", "note": "Costo aperto del comparto"},
        {"label": "Controvalore corrente", "value": current_value, "kind": "eur", "note": "Valore attuale di mercato"},
        {"label": "P/L assoluto", "value": pl_abs, "kind": "eur_signed", "note": "Risultato complessivo aperto"},
        {"label": "Rendimento semplice", "value": simple_return, "kind": "pct", "note": "P/L / investito"},
        {"label": "Giacenza media", "value": avg_balance, "kind": "eur", "note": "Media ponderata nel tempo del controvalore"},
        {"label": "Rend. su giacenza media", "value": avg_balance_return, "kind": "pct", "note": "P/L / giacenza media"},
        {"label": "Annualizzato lineare", "value": annualized_linear, "kind": "pct", "note": "Rendimento semplice / anni"},
        {"label": "XIRR", "value": xirr_value, "kind": "pct", "note": "Money-weighted return"},
        {"label": "TWR", "value": twr_total, "kind": "pct", "note": "Time-weighted return"},
        {"label": "Volatilità", "value": volatility_ann, "kind": "pct", "note": "Volatilità annualizzata"},
    ]


def get_portfolio_operations(eventi: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Filters portfolio events to get only operations.

    Args:
        eventi: List of event dicts from ctx.eventi_portafoglio

    Returns:
        Lista eventi ACQUISTO/VENDITA/RIMBORSO A SCADENZA ordinata per data DESC.
    """
    if not eventi:
        return []

    operations = [
        ev for ev in eventi
        if ev.get("tipo_evento") in {"ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA"}
    ]

    # Sort by date descending
    return sorted(operations, key=lambda x: x.get("data", ""), reverse=True)


def get_cash_movements(eventi: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Filters events to get cash movements.

    Args:
        eventi: List of event dicts from ctx.eventi_portafoglio

    Returns:
        Lista movimenti di cassa ordinata per data DESC.
    """
    if not eventi:
        return []

    cash_types = {
        "VERSAMENTO", "PRELIEVO", "CEDOLA", "DIVIDENDO",
        "COMMISSIONE", "IMPOSTA", "VENDITA", "RIMBORSO A SCADENZA", "ACQUISTO"
    }

    cash_movements = [
        ev for ev in eventi
        if ev.get("tipo_evento") in cash_types
    ]

    # Sort by date descending
    return sorted(cash_movements, key=lambda x: x.get("data", ""), reverse=True)


def build_monthly_purchase_spending(eventi: list[dict[str, Any]]) -> pd.DataFrame:
    """Aggrega per mese la spesa degli acquisti strumenti e il relativo cumulato."""
    if not eventi:
        return pd.DataFrame(columns=["Mese", "Spesa Acquisti", "Cumulato Acquisti"])

    rows: list[dict[str, Any]] = []
    for ev in eventi:
        if str(ev.get("tipo_evento", "") or "") != "ACQUISTO":
            continue
        try:
            dt = pd.to_datetime(ev.get("data"))
        except Exception:
            continue
        lordo = _safe_float(ev.get("importo_lordo", 0))
        commissioni = _safe_float(ev.get("commissioni", 0))
        imposta = _safe_float(ev.get("imposta", 0))
        qty = _safe_float(ev.get("quantita", 0))
        prezzo = _safe_float(ev.get("prezzo_unitario", 0))
        lordo_base = lordo if lordo > 0 else (qty * prezzo if qty > 0 and prezzo > 0 else 0.0)
        esborso = lordo_base + max(commissioni, 0.0) + max(imposta, 0.0)
        if esborso <= 0:
            continue
        rows.append(
            {
                "Mese": dt.to_period("M").strftime("%Y-%m"),
                "Spesa Acquisti": float(esborso),
            }
        )

    if not rows:
        return pd.DataFrame(columns=["Mese", "Spesa Acquisti", "Cumulato Acquisti"])

    monthly = pd.DataFrame(rows).groupby("Mese", as_index=False)["Spesa Acquisti"].sum()
    monthly = monthly.sort_values("Mese").reset_index(drop=True)
    monthly["Cumulato Acquisti"] = monthly["Spesa Acquisti"].cumsum()
    return monthly
