"""
core/services/rebalancing.py — Ribilanciamento in Pianificazione.

Estende la banda di tolleranza gia' esistente in core/services/sator.py
(oggi usata solo per bloccare nuovi acquisti su un bucket sopra banda) in
modo bidirezionale: individua sia i bucket in surplus (candidati alla
riduzione) sia quelli in deficit (candidati al rinforzo, con lo stesso
motore SATOR gia' esistente). Nessuna formula finanziaria nuova: ogni
funzione qui sotto riusa dati/funzioni gia' presenti in sator.py.
Vedi docs/superpowers/specs/2026-09-18-ribilanciamento-pianificazione-design.md.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from core.domain.bonds import calc_ytm_and_duration
from core.finance import build_risk_contribution_table
from core.services.instrument_clustering import _build_redundant_pairs
from core.services.sator import (
    compute_bucket_bands,
    compute_instrument_bucket_exposures,
    ensure_sator_settings,
    infer_sator_metadata,
    resolve_instrument_no_sell,
    run_sator_analysis,
)
from core.services.sator_explain import build_sator_explanations

_BUCKETS = ("Core", "Difensivo", "Satellite")
_MATERIALITY_EUR = 50.0


def compute_bucket_drift(
    current_mix: dict[str, float],
    bands: dict[str, dict[str, float]],
    portfolio_value: float,
) -> dict[str, dict[str, float | str]]:
    """Per ciascun bucket fuori banda, stato (surplus/deficit) e importo in
    euro necessario per rientrare al BORDO della banda (non al target
    esatto - meno turnover). I bucket in banda sono omessi dal risultato:
    nessun avviso quando non serve intervenire."""
    drift: dict[str, dict[str, float | str]] = {}
    for bucket in _BUCKETS:
        attuale = float(current_mix.get(bucket, 0.0))
        band = bands.get(bucket, {"target": 0.0, "min": 0.0, "max": 1.0})
        if attuale > band["max"]:
            amount_eur = (attuale - band["max"]) * portfolio_value
            if amount_eur >= _MATERIALITY_EUR:
                drift[bucket] = {"status": "surplus", "amount_eur": amount_eur}
        elif attuale < band["min"]:
            amount_eur = (band["min"] - attuale) * portfolio_value
            if amount_eur >= _MATERIALITY_EUR:
                drift[bucket] = {"status": "deficit", "amount_eur": amount_eur}
    return drift


_SOGLIA_OPERATIVA_MINIMA_EUR = 500.0
_CAP_RIGA_FRAZIONE_SURPLUS = 0.5


_MESI_SCADENZA_ANTI_RACCOMANDAZIONE = 24.0


def _classify_reduction_candidate(
    *,
    role: str,
    contributo_eur: float,
    pl_eur: float,
    is_gov_bond: bool = False,
    duration_anni: float | None = None,
    mesi_a_scadenza: float | None = None,
    voto: float | None = None,
    voto_medio_bucket: float | None = None,
    correlazione_ridondante: float | None = None,
    voto_pari_ridondante: float | None = None,
    rapporto_rischio_peso: float | None = None,
) -> tuple[int, tuple[float, ...], str]:
    """Classifica un candidato alla riduzione in un livello di convenienza
    (0 = venduto per primo) con una chiave interna omogenea al livello e
    una frase 'perche''. Livelli: 0 (liquidita'), 1 (ridondanza per
    correlazione), 2 (bassa convinzione SATOR), 3a (duration titoli di
    Stato) e 3b (rischio/peso sproporzionato, stesso livello numerico "3"
    di 3a - non competono mai per lo stesso strumento, vedi il controllo
    is_gov_bond che precede 3b nell'ordine), 5 (anti-raccomandazione) e il
    fallback 4.

    Nessun punteggio composito: livelli discreti, mai una somma pesata tra
    grandezze non comparabili (voto 1-10, anni di duration, correlazione
    0-1)."""
    if role == "liquidita":
        return 0, (-contributo_eur,), "Liquidita'/monetario: nessun rischio prezzo, nessuna duration."

    if correlazione_ridondante is not None and voto_pari_ridondante is not None:
        # Ridondanza per correlazione: piu' forte della sola bassa convinzione
        # (Livello 2), va controllata prima - un titolo ridondante e' da
        # vendere anche se il suo voto SATOR non e' il piu' basso del bucket.
        voto_display = voto if voto is not None else 0.0
        return 1, (-correlazione_ridondante, voto_display), (
            f"Correlazione {correlazione_ridondante:.2f} con un'altra posizione gia' posseduta "
            f"(voto {voto_pari_ridondante:.1f} contro {voto_display:.1f} di questo): venderlo non "
            "toglie diversificazione, la stai gia' coprendo altrove."
        )

    if voto is not None and voto_medio_bucket is not None and voto < voto_medio_bucket:
        return 2, (voto, pl_eur), (
            f"Convinzione piu' bassa della media del bucket (voto {voto:.1f} contro "
            f"media {voto_medio_bucket:.1f}): tra i meno convincenti da tenere."
        )

    if rapporto_rischio_peso is not None and rapporto_rischio_peso > 1.2:
        return 3, (-rapporto_rischio_peso, pl_eur), (
            f"Porta il {rapporto_rischio_peso:.1f}x del rischio rispetto al suo peso nel "
            "portafoglio: venderlo libera piu' rischio per euro di quanto suggerisca il suo importo."
        )

    if is_gov_bond and duration_anni is not None:
        is_plusvalenza = pl_eur > 0
        is_duration_piu_corta_nota = duration_anni <= 2.0  # soglia qualitativa "corta" per un BTP
        is_vicino_a_scadenza = mesi_a_scadenza is not None and mesi_a_scadenza <= _MESI_SCADENZA_ANTI_RACCOMANDAZIONE
        if is_plusvalenza and is_duration_piu_corta_nota and is_vicino_a_scadenza:
            return 5, (-contributo_eur,), (
                f"Non toccare se non necessario: scadenza vicina ({mesi_a_scadenza:.0f} mesi), "
                f"duration bassa ({duration_anni:.2f} anni), in plusvalenza - torna a rimborso da sola."
            )
        return 3, (-duration_anni, pl_eur), (
            f"Duration {duration_anni:.2f} anni: venderlo libera piu' rischio tasso per euro "
            "rispetto a un titolo di Stato con scadenza piu' vicina."
        )

    return 4, (-contributo_eur, pl_eur), "Nessun segnale di qualita' disponibile per questa categoria."


def build_reduction_candidates(
    data: dict[str, Any],
    state_df: pd.DataFrame,
    bucket: str,
    surplus_eur: float,
    exclude_tickers: frozenset[str] = frozenset(),
    ranking: pd.DataFrame | None = None,
    returns_frame: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Candidati alla riduzione per un bucket in surplus, classificati per
    LIVELLO di convenienza (vedi _classify_reduction_candidate), non per
    solo importo. L'importo decide il dimensionamento (quanto vendere di
    ciascun candidato), mai la selezione primaria - vedi
    docs/superpowers/specs/2026-09-19-ribilanciamento-v2-giudizio-esperto.md.
    Esclude sempre NO_SELL e i ticker in exclude_tickers (stesso insieme
    del toggle "Escludi BTP/GOV" gia' esistente in Pianificazione, se
    attivo). Un candidato sotto _SOGLIA_OPERATIVA_MINIMA_EUR non viene
    proposto (la commissione supererebbe il beneficio), a meno che sia
    l'ultimo pezzo necessario a coprire il residuo; se il taglio parziale
    lascerebbe un residuo sulla posizione sotto la stessa soglia, si esce
    dalla posizione per intero invece di lasciare uno scampolo."""
    if state_df is None or state_df.empty or surplus_eur <= 0:
        return {"candidates": [], "covered_eur": 0.0, "coverage_pct": 0.0}

    held = state_df[state_df["Controvalore"] > 0].copy()
    held["Ticker"] = held["Ticker"].astype(str).str.strip().str.upper()
    tickers = [str(t) for t in held["Ticker"]]
    exposures = compute_instrument_bucket_exposures(data, held_tickers=set(tickers))
    rows_by_ticker = held.set_index("Ticker").to_dict(orient="index")
    items_by_ticker = {
        str(item.get("ticker") or "").strip().upper(): item
        for item in data.get("strumenti", []) or []
    }

    voto_by_ticker: dict[str, float] = {}
    voto_medio_bucket: float | None = None
    if ranking is not None and not ranking.empty and "voto" in ranking.columns:
        bucket_ranking = ranking[(ranking.get("_bucket") == bucket) & (ranking.get("in_portfolio") == True)]
        if not bucket_ranking.empty:
            voto_by_ticker = dict(zip(bucket_ranking["ticker"].astype(str).str.upper(), bucket_ranking["voto"]))
            pesi = bucket_ranking["ticker"].astype(str).str.upper().map(
                lambda t: float(rows_by_ticker.get(t, {}).get("Controvalore", 0.0))
            )
            if pesi.sum() > 0:
                voto_medio_bucket = float((bucket_ranking["voto"] * pesi).sum() / pesi.sum())

    # Livello 1 (ridondanza per correlazione): per ogni ticker posseduto,
    # tiene la coppia ridondante (corr >= REDUNDANCY_THRESHOLD, riusa
    # _build_redundant_pairs - nessuna correlazione ricalcolata qui) con la
    # correlazione piu' alta il cui "compagno" e' un'ALTRA posizione gia'
    # posseduta (held_tickers_upper, non un candidato SATOR qualsiasi) con
    # un voto migliore. Se ce n'e' piu' di una, vince la correlazione piu'
    # alta, coerente con la chiave interna del Livello 1.
    redundant_by_ticker: dict[str, tuple[float, float]] = {}
    if ranking is not None and not ranking.empty and returns_frame is not None:
        held_tickers_upper = set(tickers)
        pairs = _build_redundant_pairs(ranking, returns_frame)
        for _, prow in pairs.iterrows():
            a, b = str(prow["ticker_a"]).upper(), str(prow["ticker_b"]).upper()
            corr = float(prow["correlazione"])
            for me, other in ((a, b), (b, a)):
                if me in held_tickers_upper and other in held_tickers_upper and other in voto_by_ticker:
                    voto_other = float(voto_by_ticker[other])
                    voto_me = float(voto_by_ticker.get(me, 0.0))
                    if voto_other > voto_me:
                        prev = redundant_by_ticker.get(me)
                        if prev is None or corr > prev[0]:
                            redundant_by_ticker[me] = (corr, voto_other)

    # Livello 3b (rischio/peso): calcolato una sola volta per tutti i ticker
    # posseduti (non per ogni candidato dentro il loop) riusando
    # build_risk_contribution_table gia' esistente in core/finance.py -
    # nessuna formula di rischio ricalcolata qui.
    rischio_by_ticker: dict[str, float] = {}
    if returns_frame is not None and not returns_frame.empty:
        risk_table = build_risk_contribution_table(held.reset_index(drop=True), returns_frame)
        if not risk_table.empty:
            rischio_by_ticker = dict(zip(
                risk_table["Ticker"].astype(str).str.upper(),
                risk_table["Rapporto rischio/peso"],
            ))

    raw: list[dict[str, Any]] = []
    for ticker in tickers:
        if ticker in exclude_tickers:
            continue
        if resolve_instrument_no_sell(data, ticker):
            continue
        frac = float(exposures.get(ticker, {}).get(bucket, 0.0))
        if frac <= 0:
            continue
        if frac < 0.999:
            # Esclude strumenti a esposizione frazionata su piu' bucket in
            # questo task: il gross-up (quota_bucket_eur / frac) e la
            # distinzione "altro bucket in deficit vs in banda/surplus"
            # arrivano nel design ma non sono implementati qui - restano
            # come nella v1 (scartati silenziosamente). Nota per la review
            # finale: v2 non chiude questo gap, lo eredita dalla v1.
            continue
        row = rows_by_ticker[ticker]
        contributo_eur = frac * float(row.get("Controvalore", 0.0))
        if contributo_eur <= 0:
            continue
        pl_eur = float(row.get("P/L €", 0.0))
        item = items_by_ticker.get(ticker, {"ticker": ticker})
        is_gov_bond = not bool(infer_sator_metadata(item, True).get("pac_enabled", True))
        role = str(infer_sator_metadata(item, True).get("role", ""))
        duration_anni = None
        mesi_a_scadenza = None
        if is_gov_bond:
            _, duration_anni = calc_ytm_and_duration(item)
            scadenza_raw = item.get("scadenza")
            if scadenza_raw:
                from core.domain.calendar import _to_ts
                scadenza_ts = _to_ts(scadenza_raw)
                if scadenza_ts is not None:
                    mesi_a_scadenza = (scadenza_ts - pd.Timestamp.today().normalize()).days / 30.44
        redundant = redundant_by_ticker.get(ticker)
        livello, chiave_interna, motivo = _classify_reduction_candidate(
            role=role, contributo_eur=contributo_eur, pl_eur=pl_eur,
            is_gov_bond=is_gov_bond, duration_anni=duration_anni, mesi_a_scadenza=mesi_a_scadenza,
            voto=voto_by_ticker.get(ticker), voto_medio_bucket=voto_medio_bucket,
            correlazione_ridondante=(redundant or (None, None))[0],
            voto_pari_ridondante=(redundant or (None, None))[1],
            rapporto_rischio_peso=(rischio_by_ticker.get(ticker) if not is_gov_bond else None),
        )
        raw.append({
            "ticker": ticker,
            "name": row.get("Strumento", ticker),
            "contributo_eur": contributo_eur,
            "pl_eur": pl_eur,
            "is_minusvalenza": pl_eur < 0,
            "is_gov_bond": is_gov_bond,
            "_livello": livello,
            "_chiave_interna": chiave_interna,
            "perche": motivo,
            "non_toccare": livello == 5,
        })

    raw.sort(key=lambda c: (c["_livello"], c["_chiave_interna"]))

    def _dimensiona(items: list[dict[str, Any]], residuo: float) -> tuple[list[dict[str, Any]], float, float]:
        esiti: list[dict[str, Any]] = []
        covered = 0.0
        for c in items:
            if residuo <= 0:
                break
            cap_riga = surplus_eur if (c["_livello"] > 0 and len(items) == 1) else (
                surplus_eur * _CAP_RIGA_FRAZIONE_SURPLUS if c["_livello"] > 0 else surplus_eur
            )
            quota = min(c["contributo_eur"], residuo, cap_riga)
            if quota < _SOGLIA_OPERATIVA_MINIMA_EUR and residuo > _SOGLIA_OPERATIVA_MINIMA_EUR:
                continue
            if c["contributo_eur"] - quota < _SOGLIA_OPERATIVA_MINIMA_EUR:
                # Uscita completa invece di lasciare uno scampolo sulla
                # posizione: qui si accetta deliberatamente di superare il
                # residuo/cap di riga (coverage_pct resta comunque limitato a
                # 1.0 piu' sotto) - il letterale min(..., residuo) del brief
                # vanificherebbe l'uscita completa proprio nel caso a un solo
                # candidato che il test dedicato copre.
                quota = c["contributo_eur"]
            esiti.append({**c, "quota_suggerita_eur": quota})
            covered += quota
            residuo -= quota
        return esiti, covered, residuo

    # Livello 5 (anti-raccomandazione) e' escluso dal dimensionamento finche'
    # esistono alternative: prima passata su tutti i candidati non-5, seconda
    # passata sui soli candidati di Livello 5 e solo se il residuo resta
    # scoperto dopo aver esaurito gli altri. Nota implementativa (task 3): la
    # guardia a singola passata suggerita nel brief ("continue" dentro un
    # unico for su `raw`) non funziona - raw contiene sempre candidati non-5
    # anche dopo che sono stati esauriti, quindi la condizione "any(other
    # is livello!=5)" resterebbe vera per sempre e i Livello 5 non
    # verrebbero mai selezionati nemmeno a residuo scoperto. Da qui le due
    # liste separate ed elaborate in sequenza.
    raw_normali = [c for c in raw if c["_livello"] != 5]
    raw_livello5 = [c for c in raw if c["_livello"] == 5]

    candidates, covered, residuo = _dimensiona(raw_normali, surplus_eur)
    if residuo > 0 and raw_livello5:
        esiti_livello5, covered_livello5, residuo = _dimensiona(raw_livello5, residuo)
        candidates = candidates + esiti_livello5
        covered += covered_livello5

    coverage_pct = min(1.0, covered / surplus_eur) if surplus_eur > 0 else 0.0
    return {"candidates": candidates, "covered_eur": covered, "coverage_pct": coverage_pct}


# NOTA (2026-09-18, review finale): questa funzione chiama run_sator_analysis
# per intero ad ogni bucket in deficit (fino a 2-3 volte per render) - budget
# incide poco sullo scoring (_score_cost), quindi le classifiche sono quasi
# identiche e gran parte del lavoro e' ridondante. Non ristrutturato qui
# deliberatamente (fix-wave finale, rischio di un refactor cross-funzione
# senza un secondo giro di verifica) - vedi STATO_OPERATIVO_5.0_PRE.md per il
# follow-up aperto.
def build_reinforcement_candidates(
    data: dict[str, Any],
    settings: dict[str, Any],
    bucket: str,
    budget_eur: float,
    top_n: int = 3,
) -> list[dict[str, Any]]:
    """Primi top_n candidati al rinforzo per un bucket in deficit, riusando
    interamente run_sator_analysis (nessun calcolo nuovo: e' lo stesso
    motore che oggi propone gli acquisti in Pianificazione/SATOR)."""
    if budget_eur <= 0:
        return []
    result = run_sator_analysis(data, settings, budget=budget_eur)
    ranking = result.get("ranking")
    if ranking is None or ranking.empty:
        return []
    subset = ranking[ranking["_bucket"] == bucket].sort_values("voto", ascending=False)
    # Riusa la spiegazione SATOR gia' esistente (core/services/sator_explain.py,
    # stesso ranking gia' ottenuto sopra): nessun nuovo calcolo, solo la
    # stessa frase "perche'" gia' mostrata altrove nell'app per il voto SATOR.
    explanations_by_ticker = {e.ticker: e.summary_text for e in build_sator_explanations(ranking)}
    return [
        {
            "ticker": row.get("ticker"),
            "name": row.get("name"),
            "voto": float(row.get("voto", 0.0)),
            "in_portfolio": bool(row.get("in_portfolio", False)),
            "perche": explanations_by_ticker.get(str(row.get("ticker")), ""),
        }
        for _, row in subset.head(top_n).iterrows()
    ]


def build_rebalancing_plan(
    data: dict[str, Any],
    settings: dict[str, Any],
    state_df: pd.DataFrame,
    current_mix: dict[str, float],
    portfolio_value: float,
    exclude_tickers: frozenset[str] = frozenset(),
) -> dict[str, dict[str, Any]]:
    """Piano di ribilanciamento completo: solo i bucket fuori banda
    compaiono nel risultato. Il budget per il rinforzo di ciascun bucket
    in deficit e' il ricavato EFFETTIVAMENTE coperto dai bucket in
    surplus (mai inventato), ripartito in proporzione al deficit di
    ciascun bucket in deficit.

    `portfolio_value` DEVE essere lo stesso denominatore usato dal
    chiamante per calcolare `current_mix` (mai ricavato qui da
    `state_df["Controvalore"].sum()`): se il chiamante applica un
    filtro come il toggle "Escludi BTP/GOV" a monte di `current_mix`
    ma non a `state_df`, i due userebbero basi diverse e ogni importo
    in euro del piano risulterebbe gonfiato o compresso rispetto al
    surplus/deficit percentuale reale (bug reale, review finale
    2026-09-18: fattore ~2x su un portafoglio reale con BTP/GOV grandi
    e il toggle attivo)."""
    objective = settings.get("portfolio_objective", {}) if isinstance(settings, dict) else {}
    cfg = ensure_sator_settings(settings)
    bands = compute_bucket_bands(objective, cfg["band_tolerance_pp"])

    drift = compute_bucket_drift(current_mix, bands, portfolio_value)
    if not drift:
        return {}

    # run_sator_analysis chiamata una sola volta per l'intero piano, con
    # budget neutro (0.0): qui serve solo il `ranking` (voto per ticker) per
    # il Livello 2 in build_reduction_candidates, non per dimensionare
    # acquisti. NOTA (temporaneo, si chiude nel Task 7): build_reinforcement_
    # candidates piu' sotto richiama ANCORA run_sator_analysis per conto suo
    # con il proprio budget (per bucket in deficit) - quindi ci sono
    # temporaneamente due chiamate al motore per render quando c'e' un
    # surplus da reinvestire. Consolidamento completo nel Task 7.
    result = run_sator_analysis(data, settings, budget=0.0)
    ranking = result.get("ranking")

    plan: dict[str, dict[str, Any]] = {}
    total_covered = 0.0
    for bucket, info in drift.items():
        if info["status"] != "surplus":
            continue
        reduction = build_reduction_candidates(
            data, state_df, bucket, float(info["amount_eur"]), exclude_tickers, ranking=ranking,
            returns_frame=result.get("returns_frame"),
        )
        plan[bucket] = {**info, "reduction": reduction}
        total_covered += reduction["covered_eur"]

    deficit_buckets = {b: i for b, i in drift.items() if i["status"] == "deficit"}
    total_deficit = sum(float(i["amount_eur"]) for i in deficit_buckets.values())
    for bucket, info in deficit_buckets.items():
        quota_budget = (
            total_covered * (float(info["amount_eur"]) / total_deficit) if total_deficit > 0 else 0.0
        )
        reinforcement = build_reinforcement_candidates(data, settings, bucket, quota_budget)
        plan[bucket] = {**info, "budget_eur": quota_budget, "reinforcement": reinforcement}

    return plan
