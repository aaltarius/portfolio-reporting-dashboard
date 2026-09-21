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
from core.services.sator_explain import build_sator_explanations
from core.services.sator import (
    _suggested_quotes_by_bucket,
    compute_bucket_bands,
    compute_instrument_bucket_exposures,
    ensure_sator_settings,
    infer_sator_metadata,
    resolve_instrument_no_sell,
    run_sator_analysis,
)

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
) -> tuple[float, tuple[float, ...], str]:
    """Classifica un candidato alla riduzione in un livello di convenienza
    (0 = venduto per primo) con una chiave interna omogenea al livello e
    una frase 'perche''. Livelli: 0 (liquidita'), poi SUBITO i titoli di
    Stato (3 = duration decrescente, oppure 5 = anti-raccomandazione) -
    controllati prima di 1/2/3b apposta, cosi' un BTP non puo' mai essere
    intercettato dai controlli pensati per ETF/ETC anche se in futuro
    SATOR arrivasse a dare un voto ai titoli di Stato. Poi 1 (ridondanza
    per correlazione), 2 (bassa convinzione SATOR), 3.5 (rischio/peso
    sproporzionato - numero diverso da 3 apposta: la chiave interna di 3
    (anni di duration) e quella di 3.5 (rapporto di rischio) non sono
    comparabili, non devono mai finire nello stesso livello numerico) e
    il fallback 4.

    Nessun punteggio composito: livelli discreti, mai una somma pesata tra
    grandezze non comparabili (voto 1-10, anni di duration, correlazione
    0-1)."""
    if role == "liquidita":
        return 0, (-contributo_eur,), "Liquidita'/monetario: nessun rischio prezzo, nessuna duration."

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
        return 3.5, (-rapporto_rischio_peso, pl_eur), (
            f"Porta il {rapporto_rischio_peso:.1f}x del rischio rispetto al suo peso nel "
            "portafoglio: venderlo libera piu' rischio per euro di quanto suggerisca il suo importo."
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
    deficit_buckets: frozenset[str] = frozenset(),
    venduto_reale_by_ticker: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Candidati alla riduzione per un bucket in surplus, classificati per
    LIVELLO di convenienza (vedi _classify_reduction_candidate), non per
    solo importo. L'importo decide il dimensionamento (quanto vendere di
    ciascun candidato), mai la selezione primaria - vedi
    docs/superpowers/specs/2026-09-19-ribilanciamento-v2-giudizio-esperto.md.
    Esclude sempre NO_SELL e i ticker in exclude_tickers (stesso insieme
    del toggle "Escludi BTP/GOV" gia' esistente in Pianificazione, se
    attivo). Un candidato sotto _SOGLIA_OPERATIVA_MINIMA_EUR (in euro di
    VENDITA REALE, non di sollievo-bucket - vedi gross-up sotto) non viene
    proposto, a meno che sia l'ultimo pezzo necessario a coprire il
    residuo; se il taglio parziale lascerebbe un residuo di vendita reale
    sotto la stessa soglia, si esce dalla posizione per intero invece di
    lasciare uno scampolo.

    Strumenti a esposizione frazionata su piu' bucket (frac < 1.0, es. un
    ETF 40% Core / 60% Difensivo): sono eleggibili con un "gross-up" -
    vendere quota_suggerita_eur di sollievo su QUESTO bucket richiede di
    vendere quota_vendita_eur = quota_suggerita_eur / frac euro TOTALI
    della posizione (la vendita riduce l'esposizione a TUTTI i bucket in
    proporzione, non solo a questo). Sono ESCLUSI solo se un altro bucket
    a cui sono esposti e' attualmente in deficit (deficit_buckets):
    venderli peggiorerebbe quel bucket. covered_eur e coverage_pct
    restano sempre nell'unita' di sollievo-bucket (quota_suggerita_eur),
    mai nell'unita' di vendita reale - misurano quanto del surplus DI
    QUESTO BUCKET e' stato coperto, non quanto si e' venduto in totale.

    Quando lo stesso strumento e' esposto (e quindi eleggibile) su piu'
    bucket contemporaneamente in surplus, `venduto_reale_by_ticker`
    (opzionale, chiave ticker -> euro di VENDITA REALE gia' impegnati in
    una card di un bucket precedente nello STESSO piano) impedisce che la
    somma delle vendite reali proposte per un ticker attraverso card
    diverse superi il suo Controvalore reale: il residuo vendibile per
    questo bucket e' Controvalore - venduto_reale_by_ticker.get(ticker,
    0.0), mai il Controvalore intero. E' compito del chiamante
    (build_rebalancing_plan) accumulare questo dict tra una chiamata e la
    successiva, bucket per bucket - build_reduction_candidates chiamato
    una volta da solo non puo' sapere cosa succede nelle altre card."""
    if state_df is None or state_df.empty or surplus_eur <= 0:
        return {"candidates": [], "tenuti": [], "covered_eur": 0.0, "coverage_pct": 0.0}

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
                if (
                    me in held_tickers_upper
                    and other in held_tickers_upper
                    and other in voto_by_ticker
                    and me in voto_by_ticker
                ):
                    voto_other = float(voto_by_ticker[other])
                    voto_me = float(voto_by_ticker[me])
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
    # Ogni strumento posseduto ESPOSTO a questo bucket (frac>0) deve finire
    # da qualche parte nel risultato finale - o in candidates (vendi/non
    # toccare) o in tenuti (tieni, con un motivo esplicito). Feedback
    # utente 2026-09-19: "vorrei vedere tutti gli strumenti" - prima gli
    # strumenti esclusi qui sparivano silenziosamente, senza lasciare
    # traccia del perche' non erano stati proposti.
    tenuti: list[dict[str, Any]] = []
    for ticker in tickers:
        esposizioni_ticker = exposures.get(ticker, {})
        frac = float(esposizioni_ticker.get(bucket, 0.0))
        if frac <= 0:
            continue  # non esposto a questo bucket: non e' una posizione di QUESTO bucket
        row = rows_by_ticker[ticker]
        name = row.get("Strumento", ticker)
        if ticker in exclude_tickers:
            tenuti.append({"ticker": ticker, "name": name, "motivo": "Escluso dal toggle attivo (es. \"Escludi BTP/GOV\")."})
            continue
        if resolve_instrument_no_sell(data, ticker):
            tenuti.append({"ticker": ticker, "name": name, "motivo": "Marcato NO_SELL: mai proposto per la vendita."})
            continue
        # Gross-up (Addendum v2.1): uno strumento a esposizione frazionata
        # su piu' bucket (frac < 1.0) e' eleggibile SOLO se nessun altro
        # bucket a cui e' esposto e' attualmente in deficit - venderlo
        # peggiorerebbe quel bucket. Se e' esposto solo su `bucket`
        # (frac ~= 1.0) altri_bucket_esposti e' vuoto e il controllo passa
        # sempre, comportamento identico a prima del gross-up.
        altri_bucket_esposti = [
            (b2, float(f2)) for b2, f2 in esposizioni_ticker.items()
            if b2 != bucket and float(f2) > 0
        ]
        bucket_penalizzato = next(
            (b2 for b2, _ in altri_bucket_esposti if b2 in deficit_buckets), None
        )
        if bucket_penalizzato is not None:
            tenuti.append({"ticker": ticker, "name": name, "motivo": f"Venderlo peggiorerebbe {bucket_penalizzato}, oggi in deficit."})
            continue
        controvalore = float(row.get("Controvalore", 0.0))
        # Fix post-review (doppio conteggio tra bucket condivisi): il
        # residuo vendibile per QUESTO bucket e' il Controvalore MENO
        # quanto di questo stesso ticker e' gia' stato impegnato in una
        # card di un bucket precedente nello stesso piano - mai il
        # Controvalore intero, altrimenti lo stesso strumento potrebbe
        # essere proposto per piu' del suo valore reale attraverso card
        # diverse.
        gia_venduto_eur = (venduto_reale_by_ticker or {}).get(ticker, 0.0)
        residuo_vendibile_eur = max(0.0, controvalore - gia_venduto_eur)
        contributo_eur = frac * residuo_vendibile_eur
        if contributo_eur <= 0:
            tenuti.append({"ticker": ticker, "name": name, "motivo": "Gia' impegnato per intero in un altro bucket con cui condivide l'esposizione."})
            continue
        pl_eur = float(row.get("P/L €", 0.0))
        prezzo = float(row.get("Prezzo", 0.0))
        quote_possedute = float(row.get("Quote", 0.0))
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
        if frac < 0.999:
            altri_nomi = ", ".join(sorted(b2 for b2, _ in altri_bucket_esposti))
            motivo = motivo + (
                f" Esposizione anche su {altri_nomi} (non in deficit): vendere qui non li "
                "penalizza, ma l'importo da vendere e' maggiore della quota attribuita a "
                "questo bucket."
            )
        raw.append({
            "ticker": ticker,
            "name": name,
            "contributo_eur": contributo_eur,
            "frac": frac,
            "prezzo": prezzo,
            "quote_possedute": quote_possedute,
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
            # Le due soglie (skip sopra, uscita completa sotto) vanno
            # confrontate con l'importo di VENDITA REALE (Addendum v2.1),
            # non con la quota di sollievo-bucket: su uno strumento a frac
            # piccolo, un residuo piccolo in termini di bucket corrisponde a
            # un residuo di vendita reale molto piu' grande (residuo_bucket
            # / frac), e la soglia esiste per evitare scampoli di vendita
            # reale sotto la commissione, non scampoli di sollievo-bucket.
            residuo_vendita_reale_eur = (c["contributo_eur"] - quota) / c["frac"]
            if residuo_vendita_reale_eur < _SOGLIA_OPERATIVA_MINIMA_EUR:
                # Uscita completa invece di lasciare uno scampolo sulla
                # posizione: qui si accetta deliberatamente di superare il
                # residuo/cap di riga (coverage_pct resta comunque limitato a
                # 1.0 piu' sotto) - il letterale min(..., residuo) del brief
                # vanificherebbe l'uscita completa proprio nel caso a un solo
                # candidato che il test dedicato copre.
                quota = c["contributo_eur"]
            quota_vendita_eur = quota / c["frac"]
            # Numero di quote da vendere (feedback utente: "non mi parla di
            # quote") - arrotondato, mai oltre quanto realmente posseduto
            # (min con quote_possedute: un arrotondamento per eccesso su un
            # residuo minimo non deve mai proporre di vendere piu' di
            # quanto si ha).
            quote_vendita = (
                min(c["quote_possedute"], round(quota_vendita_eur / c["prezzo"]))
                if c["prezzo"] > 0 else 0
            )
            esiti.append({
                **c,
                "quota_suggerita_eur": quota,
                "quota_vendita_eur": quota_vendita_eur,
                "quote_vendita": quote_vendita,
            })
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
    esiti_livello5: list[dict[str, Any]] = []
    if residuo > 0 and raw_livello5:
        esiti_livello5, covered_livello5, residuo = _dimensiona(raw_livello5, residuo)
        covered += covered_livello5

    # Ogni candidato di Livello 5 (anti-raccomandazione) deve comparire in
    # `candidates`, toccato o no: e' l'unico modo per cui l'utente vede
    # "NON TOCCARE" anche quando non e' mai stato necessario forzarne la
    # vendita. Quelli effettivamente venduti (perche' il residuo non era
    # coperto dagli altri livelli) portano forzato=True e la loro quota;
    # gli altri restano a quota 0 con forzato=False.
    forzati_tickers = {c["ticker"] for c in esiti_livello5}
    candidates = candidates + [{**c, "forzato": True} for c in esiti_livello5]
    candidates += [
        {**c, "quota_suggerita_eur": 0.0, "quota_vendita_eur": 0.0, "quote_vendita": 0, "forzato": False}
        for c in raw_livello5
        if c["ticker"] not in forzati_tickers
    ]

    # Candidati classificati (Livelli 0-4) ma NON scelti dal dimensionamento
    # (il surplus era gia' coperto da altri con priorita' maggiore): niente
    # da vendere, ma vanno comunque mostrati come "tieni" - non spariscono
    # in silenzio (stesso principio dei tenuti sopra).
    venduti_tickers = {c["ticker"] for c in candidates if float(c.get("quota_suggerita_eur", 0.0)) > 0}
    for c in raw_normali:
        if c["ticker"] not in venduti_tickers:
            tenuti.append({
                "ticker": c["ticker"], "name": c["name"],
                "motivo": f"{c['perche']} Non necessario ora: il surplus e' gia' coperto da altri candidati con priorita' maggiore.",
            })

    coverage_pct = min(1.0, covered / surplus_eur) if surplus_eur > 0 else 0.0
    return {"candidates": candidates, "tenuti": tenuti, "covered_eur": covered, "coverage_pct": coverage_pct}


_MARGINE_VOTO_LINEA_NUOVA = 0.5
_QUOTA_MINIMA_LINEA_NUOVA_EUR = 1000.0
_QUOTA_MINIMA_LINEA_NUOVA_FRAZIONE_PORTAFOGLIO = 0.01

_NATURE_OBBLIGAZIONARIO = frozenset({"bond_governativo", "bond_globale"})
_NATURE_NON_AZIONARIO_NON_BOND = frozenset({"monetario", "oro"})


def _asset_class_from_nature(nature: Any) -> str:
    """Classificazione azionario/obbligazionario per la UI (feedback
    utente 2026-09-20: "mi proponi solo di acquistare obbligazionario ma
    non hai pensato che magari vorrei fare azionario!") - riusa il campo
    `nature` gia' presente sul ranking SATOR (stesso vocabolario di
    CAP_MORBIDO_NATURA in sator.py), nessuna nuova classificazione
    finanziaria: solo un'etichetta di raggruppamento per un valore gia'
    calcolato altrove."""
    n = str(nature or "")
    if n in _NATURE_OBBLIGAZIONARIO:
        return "obbligazionario"
    if n in _NATURE_NON_AZIONARIO_NON_BOND:
        return n
    return "azionario"


def build_reinforcement_candidates(
    ranking: pd.DataFrame,
    data: dict[str, Any],
    settings: dict[str, Any],
    bucket: str,
    budget_eur: float,
    current_mix: dict[str, float],
    objective: dict[str, float],
    portfolio_value: float,
    surplus_buckets: frozenset[str] = frozenset(),
    already_used_tickers: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Candidati al rinforzo per un bucket in deficit, con importo E
    QUOTE reali (numero di pezzi, non solo euro) riusando l'allocatore
    SATOR gia' esistente (_suggested_quotes_by_bucket, stesso motore della
    pagina SATOR principale, cap di concentrazione max_share_per_line gia'
    rispettati). OGNI candidato (posseduto o no) sotto
    _SOGLIA_OPERATIVA_MINIMA_EUR e' scartato (stessa soglia gia' usata lato
    vendite: sotto quella cifra la commissione supererebbe il beneficio) -
    parere esperto 2026-09-19: senza questo filtro un budget piccolo si
    spalmava su tante mini-righe da 50-130 euro. Un candidato NON posseduto
    viene proposto solo se, IN PIU', (a) il suo voto supera di almeno
    _MARGINE_VOTO_LINEA_NUOVA il migliore posseduto nello stesso bucket, E
    (b) l'importo proposto raggiunge max(_QUOTA_MINIMA_LINEA_NUOVA_EUR,
    _QUOTA_MINIMA_LINEA_NUOVA_FRAZIONE_PORTAFOGLIO * portfolio_value) -
    altrimenti si preferisce rinforzare una posizione gia' esistente
    piuttosto che aprire una linea nuova troppo piccola per essere
    gestita.

    Ogni candidato porta un campo `perche'` che riusa
    core.services.sator_explain.build_sator_explanations - la STESSA
    scomposizione nei 5 fattori del voto SATOR (fit strategico, MOMENTUM,
    efficienza di rischio, diversificazione, efficienza di costo) gia'
    mostrata altrove nell'app, non una frase generica: nomina esplicitamente
    quando il momentum e' uno dei fattori trainanti (o non lo e').

    Ritorna TUTTI i candidati finanziati dall'allocatore, nessun taglio a
    top_n - feedback utente 2026-09-19: "vorrei vedere tutti gli
    strumenti", un taglio di visualizzazione nascosto dietro una nota
    "+ altri N" restava comunque inutilizzabile (non azionabile) per
    l'utente. covered_eur e' la somma di TUTTI i candidati restituiti, da
    sempre coerente con quanto mostrato."""
    if budget_eur <= 0 or ranking is None or ranking.empty:
        return {
            "candidates": [], "covered_eur": 0.0,
            "budget_insufficiente": budget_eur < _SOGLIA_OPERATIVA_MINIMA_EUR,
        }
    cfg = ensure_sator_settings(settings)
    bucket_deficits = {bucket: budget_eur}
    quantita = _suggested_quotes_by_bucket(
        ranking, budget_eur, bucket_deficits, blocked_buckets=set(),
        bucket_weights=current_mix, bucket_targets=objective,
        max_share=cfg["max_share_per_line"],
        # Bug reale trovato dall'utente 2026-09-19: senza questo, il tetto
        # di concentrazione per riga (max_share * budget) veniva calcolato
        # sul RICAVATO di questo giro (poche centinaia di euro, es. una
        # sola vendita) invece che sul portafoglio totale - una riga da
        # 35% di 867 euro e' un tetto senza alcun rapporto con un vero
        # rischio di concentrazione, e finiva per bloccare OGNI candidato
        # (nessuno superava mai la soglia minima di ticket): si vendeva
        # qualcosa ma non si comprava mai nulla col ricavato.
        cap_reference_budget=portfolio_value,
    )
    work = ranking.reset_index(drop=True)
    # _suggested_quotes_by_bucket instrada gia' ogni riga al bucket corretto
    # tramite _dominant_bucket (vedi sator.py), anche per strumenti a
    # esposizione split: ri-filtrare qui per la colonna statica _bucket
    # scarterebbe budget legittimamente allocato dall'allocatore.
    subset_idx = [i for i in range(len(quantita)) if int(quantita[i]) > 0]

    # Bug reale trovato dall'utente 2026-09-20 ("mi consigli di comprare
    # ETFMIB quando dal grafico vedo che e' per maggior parte Satellite e
    # oggi Satellite e' in esubero... che senso ha?!"). _dominant_bucket fa
    # SEMPRE vincere il bucket di esposizione maggioritaria di uno
    # strumento QUANDO piu' bucket sono eleggibili in concorrenza (Task
    # V-ter) - ma qui bucket_deficits ha UNA SOLA chiave (il bucket
    # richiesto): _dominant_bucket non ha alcun bucket concorrente tra cui
    # scegliere, quindi instrada qui anche uno strumento con appena una
    # minoranza di esposizione a questo bucket, pur di maggioranza in un
    # ALTRO bucket. Se quell'altro bucket (la sua vera maggioranza) e' gia'
    # in surplus, comprarne di piu' peggiora esattamente il problema che il
    # piano dovrebbe risolvere. Filtro mirato (non il blanket "_bucket ==
    # bucket" gia' scartato sopra, che scarterebbe anche contributi
    # minoritari legittimi verso un bucket non in surplus): esclude solo
    # chi ha la propria maggioranza reale in un bucket oggi in surplus.
    if surplus_buckets:
        subset_idx = [
            i for i in subset_idx
            if str(work.iloc[i].get("_bucket")) not in surplus_buckets
        ]

    # Dedup cross-bucket (bug reale utente 2026-09-21: "perche' mi ritrovo
    # 2 volte nella tabella in ribilanciamento il consiglio di comprare 4
    # quote di EM13.MI?!"). Uno strumento con esposizione frazionata su piu'
    # bucket (normale, vedi CDS in auto_instrument_bucket_exposure) risulta
    # eleggibile in OGNI chiamata isolata a questa funzione (una per bucket
    # in deficit, vedi build_rebalancing_plan) perche' bucket_deficits ha
    # sempre una sola chiave: il filtro surplus_buckets sopra esclude solo
    # chi ha la propria maggioranza reale in un bucket in SURPLUS, non fa
    # nulla quando i bucket a cui appartiene sono ENTRAMBI in deficit. Qui
    # si esclude chi e' gia' stato proposto da una chiamata precedente per
    # un altro bucket (il chiamante passa i ticker gia' usati, in ordine
    # deterministico Core/Difensivo/Satellite - il primo bucket vince).
    if already_used_tickers:
        subset_idx = [
            i for i in subset_idx
            if str(work.iloc[i].get("ticker")) not in already_used_tickers
        ]

    posseduti_voto = work.loc[
        (work["_bucket"] == bucket) & (work["in_portfolio"] == True), "voto"
    ]
    miglior_voto_posseduto = float(posseduti_voto.max()) if not posseduti_voto.empty else 0.0
    soglia_importo_linea_nuova = max(
        _QUOTA_MINIMA_LINEA_NUOVA_EUR,
        _QUOTA_MINIMA_LINEA_NUOVA_FRAZIONE_PORTAFOGLIO * portfolio_value,
    )
    spiegazioni_by_ticker = {
        e.ticker: e for e in build_sator_explanations(ranking)
    }

    def _top_factor_label(ticker: str) -> str:
        # Fattore SATOR con il contributo maggiore al voto (stessa
        # scomposizione in 5 fattori di build_sator_explanations, nessun
        # calcolo nuovo) - usato per una spiegazione GRAFICA compatta (un
        # chip, es. "momentum") invece di una frase intera troncata
        # (feedback utente 2026-09-20: "invece di trovare una soluzione
        # grafica... tronchi il testo").
        e = spiegazioni_by_ticker.get(ticker)
        if not e or not e.contributions:
            return ""
        return max(e.contributions, key=lambda c: c.contribution).label

    def _prova_concentrazione(row_i: pd.Series, budget: float) -> dict[str, Any] | None:
        in_portfolio_i = bool(row_i.get("in_portfolio", False))
        voto_i = float(row_i.get("voto", 0.0))
        if not (in_portfolio_i or voto_i >= miglior_voto_posseduto + _MARGINE_VOTO_LINEA_NUOVA):
            return None
        prezzo_i = float(row_i.get("unit_price", 0.0))
        if prezzo_i <= 0:
            return None
        cap_riga_eur = cfg["max_share_per_line"] * portfolio_value
        qty_i = int(min(budget, cap_riga_eur) // prezzo_i)
        importo_i = qty_i * prezzo_i
        supera_soglia_linea_nuova_i = in_portfolio_i or importo_i >= soglia_importo_linea_nuova
        if importo_i >= _SOGLIA_OPERATIVA_MINIMA_EUR and supera_soglia_linea_nuova_i:
            return {
                "row": row_i, "prezzo": prezzo_i, "qty": qty_i, "importo": importo_i,
                "in_portfolio": in_portfolio_i, "voto": voto_i,
            }
        return None

    def _candidato_da_esito(esito: dict[str, Any], *, alternativa: bool, primario_ticker: str = "") -> dict[str, Any]:
        row, prezzo, qty_concentrato, importo_concentrato = esito["row"], esito["prezzo"], esito["qty"], esito["importo"]
        in_portfolio, voto = esito["in_portfolio"], esito["voto"]
        ticker = str(row.get("ticker"))
        spiegazione_obj = spiegazioni_by_ticker.get(ticker)
        spiegazione = spiegazione_obj.summary_text if spiegazione_obj else ""
        if in_portfolio:
            perche = f"Gia' in portafoglio, voto SATOR {voto:.1f}."
        else:
            perche = (
                f"Voto SATOR {voto:.1f}, superiore di almeno {_MARGINE_VOTO_LINEA_NUOVA:.1f} punti "
                f"al migliore gia' posseduto in questo bucket ({miglior_voto_posseduto:.1f})."
            )
        if spiegazione:
            perche = f"{perche} {spiegazione}"
        if alternativa:
            perche = f"{perche} Alternativa a {primario_ticker}: cifra simile, asset class diversa - o l'uno o l'altro, non entrambi."
        else:
            perche = (
                f"{perche} Budget concentrato su un solo titolo: troppo piccolo per "
                "diversificare in modo sensato."
            )
        return {
            "ticker": ticker,
            "name": row.get("name"),
            "voto": voto,
            "in_portfolio": in_portfolio,
            "quote": qty_concentrato,
            "unit_price": prezzo,
            "importo_eur": importo_concentrato,
            "perche": perche,
            "top_factor": _top_factor_label(ticker),
            "alternativa": alternativa,
            "nature": row.get("nature"),
        }

    out: list[dict[str, Any]] = []
    for i in subset_idx:
        qty = int(quantita[i])
        if qty <= 0:
            continue
        row = work.iloc[i]
        in_portfolio = bool(row.get("in_portfolio", False))
        voto = float(row.get("voto", 0.0))
        importo = qty * float(row.get("unit_price", 0.0))
        # Ticket minimo (parere esperto 2026-09-19): prima questa soglia
        # valeva SOLO per le linee nuove (soglia_importo_linea_nuova,
        # 1000+) - una posizione GIA' posseduta passava senza alcun minimo,
        # quindi un budget piccolo si spalmava su tante mini-righe da 50-
        # 130 euro l'una (costo di commissione sproporzionato rispetto
        # all'importo, e un piano illeggibile). Riusa la stessa soglia gia'
        # usata lato vendite (_SOGLIA_OPERATIVA_MINIMA_EUR, "la commissione
        # supererebbe il beneficio") invece di inventarne una nuova.
        if importo < _SOGLIA_OPERATIVA_MINIMA_EUR:
            continue
        if not in_portfolio and (
            voto < miglior_voto_posseduto + _MARGINE_VOTO_LINEA_NUOVA
            or importo < soglia_importo_linea_nuova
        ):
            continue
        ticker = str(row.get("ticker"))
        spiegazione_obj = spiegazioni_by_ticker.get(ticker)
        spiegazione = spiegazione_obj.summary_text if spiegazione_obj else ""
        if in_portfolio:
            perche = f"Gia' in portafoglio, voto SATOR {voto:.1f}."
        else:
            perche = (
                f"Voto SATOR {voto:.1f}, superiore di almeno {_MARGINE_VOTO_LINEA_NUOVA:.1f} punti "
                f"al migliore gia' posseduto in questo bucket ({miglior_voto_posseduto:.1f})."
            )
        if spiegazione:
            perche = f"{perche} {spiegazione}"
        out.append({
            "ticker": ticker,
            "name": row.get("name"),
            "voto": voto,
            "in_portfolio": in_portfolio,
            "quote": qty,
            "unit_price": float(row.get("unit_price", 0.0)),
            "importo_eur": importo,
            "perche": perche,
            "top_factor": _top_factor_label(ticker),
            "alternativa": False,
            "nature": row.get("nature"),
        })

    if not out and budget_eur >= _SOGLIA_OPERATIVA_MINIMA_EUR and subset_idx:
        # Ripiego a concentrazione su un solo titolo (bug reale trovato
        # dall'utente 2026-09-19: "vendo XEON, poi che compro?!" - un piano
        # che genera ricavato e non dice mai cosa farne e' inutile).
        # L'allocatore SATOR (_suggested_quotes), per design, preferisce
        # aprire una prima quota su PIU' titoli diversi piuttosto che una
        # seconda quota dello stesso: l'utilita' marginale di una quota
        # aggiuntiva sullo stesso titolo scende rapidamente sotto soglia
        # (vedi _purchase_decision_score). Con un budget piccolo (poche
        # centinaia di euro) il risultato e' che OGNI riga resta sotto la
        # soglia minima di ticket e il ciclo sopra non produce nulla,
        # anche se il budget totale basterebbe a comprare una posizione
        # sensata se concentrato invece di spalmato. Con un budget cosi'
        # piccolo diversificare non e' comunque possibile in modo sensato:
        # si concentra tutto sul titolo con il voto migliore tra quelli
        # che l'allocatore aveva gia' giudicato eleggibili (subset_idx),
        # ignorando qui la logica di utilita' marginale per quota (che ha
        # senso solo quando si sceglie TRA piu' titoli, non per dimensionare
        # un'unica riga), comprando quante piu' quote il budget permette,
        # capped al tetto di concentrazione REALE sul portafoglio totale
        # (non sul budget di questo giro - stesso bug gia' corretto sopra
        # con cap_reference_budget).
        # Bug reale trovato dall'utente 2026-09-20 ("la questione budget
        # insufficiente non ha senso... potrei preferire comprare azionario
        # piuttosto che obbligazionario"): la versione precedente si
        # fermava al PRIMO candidato eleggibile per voto e, se il SUO
        # prezzo non ci stava nel budget (qty_concentrato troppo basso),
        # si arrendeva - senza mai provare un'alternativa piu' economica
        # con voto minore ma che avrebbe comunque superato la soglia
        # minima. Ora si scorre l'intera lista in ordine di voto
        # decrescente e si prende il PRIMO che produce davvero un
        # acquisto valido (quota intera >= soglia minima di ticket, e se
        # e' una linea nuova anche sopra la soglia di apertura linea) -
        # non il primo semplicemente eleggibile per voto a prescindere
        # dal prezzo.
        candidati_ordinati = sorted(subset_idx, key=lambda i: -float(work.iloc[i].get("voto", 0.0)))
        scelto = None
        for i in candidati_ordinati:
            esito = _prova_concentrazione(work.iloc[i], budget_eur)
            if esito is not None:
                scelto = esito
                break
        if scelto is not None:
            out.append(_candidato_da_esito(scelto, alternativa=False))

    # Feedback utente 2026-09-20: "mi proponi solo di acquistare
    # obbligazionario ma non hai pensato che magari vorrei fare
    # azionario!". Quando la proposta finale e' concentrata su UN solo
    # titolo (che sia passata dal ripiego sopra o perche' il ciclo
    # principale ha comunque prodotto una sola riga con budget piccolo),
    # se esiste un'alternativa valida di asset class DIVERSA per una
    # cifra simile, la si propone ACCANTO, non al posto: e' un OPPURE
    # (campo "alternativa" sulla riga), mai una seconda spesa dallo
    # stesso budget - vedi l'esclusione di alternativa=True da
    # covered_eur sotto.
    if len(out) == 1:
        primario_ticker = str(out[0]["ticker"])
        primaria_asset_class = _asset_class_from_nature(out[0].get("nature"))
        budget_alternativa = float(out[0]["importo_eur"])
        # Scandisce l'INTERO universo eleggibile per questo bucket
        # (work["_bucket"] == bucket - la sua propria maggioranza reale,
        # stessa colonna gia' usata per il filtro anti-surplus sopra), non
        # solo subset_idx: l'allocatore marginale puo' aver instradato
        # ZERO quota a un'alternativa perfettamente valida semplicemente
        # perche' ha preferito concentrare tutto sulla prima (design gia'
        # noto, vedi commento su _suggested_quotes) - qui si valuta ogni
        # candidato del bucket da zero, indipendentemente da cosa
        # l'allocatore gli abbia gia' assegnato.
        candidati_bucket_idx = [i for i in range(len(work)) if str(work.iloc[i].get("_bucket")) == bucket]
        candidati_ordinati_alt = sorted(candidati_bucket_idx, key=lambda i: -float(work.iloc[i].get("voto", 0.0)))
        for i in candidati_ordinati_alt:
            row_i = work.iloc[i]
            if str(row_i.get("ticker")) == primario_ticker:
                continue
            if str(row_i.get("ticker")) in already_used_tickers:
                continue
            if _asset_class_from_nature(row_i.get("nature")) == primaria_asset_class:
                continue
            esito_alt = _prova_concentrazione(row_i, budget_alternativa)
            if esito_alt is not None:
                out.append(_candidato_da_esito(esito_alt, alternativa=True, primario_ticker=primario_ticker))
                break

    # Tie-break su importo_eur decrescente (non solo voto): con budget
    # grandi (es. scenario "capitale nuovo") piu' candidati arrivano allo
    # stesso voto, e un ordinamento per il solo voto tronca a top_n in un
    # ordine arbitrario (quello originale del ranking) - potendo scartare
    # un'opportunita' di importo molto maggiore a favore di spiccioli con
    # lo stesso voto. Trovato con dati reali: senza questo tie-break,
    # "capitale nuovo" mostrava gli stessi 3 importi minuscoli di
    # "con il ricavato delle vendite" invece di sfruttare il budget piu'
    # ampio, sembrando (a torto) che il budget in piu' non servisse a nulla.
    out.sort(key=lambda c: (c["voto"], c["importo_eur"]), reverse=True)
    # Un'alternativa (stesso budget, asset class diversa - vedi sopra) non
    # e' una spesa aggiuntiva: sommarla qui raddoppierebbe il budget
    # davvero deployabile mostrato dalla UI.
    covered_eur = sum(float(c["importo_eur"]) for c in out if not c.get("alternativa"))
    return {
        "candidates": out, "covered_eur": covered_eur,
        # Esposto per la UI (feedback utente 2026-09-20: "mi dice che
        # mancano 1113,36 di core... ma non mi consiglia nessun core da
        # comprare! che senso ha?!" - la lista vuota da sola non spiega
        # SE il motivo e' che il ricavato per questo bucket e' sotto la
        # soglia minima di ticket, o che nessun titolo era eleggibile:
        # niente deve restare silenzioso), invece di duplicare la soglia
        # _SOGLIA_OPERATIVA_MINIMA_EUR in ui/pages/pianificazione.py.
        "budget_insufficiente": budget_eur < _SOGLIA_OPERATIVA_MINIMA_EUR,
    }


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

    # Addendum v2.1: un bucket in deficit non compare qui come "eleggibile
    # a farsi vendere sopra" - serve a build_reduction_candidates per
    # escludere strumenti a esposizione frazionata che lo penalizzerebbero
    # (vedi deficit_bucket_names nel loop sui ticker). Nome distinto da
    # deficit_buckets (il dict bucket->info usato piu' sotto per il lato
    # rinforzo) apposta: stesso concetto, tipo diverso, mai da confondere.
    deficit_bucket_names = frozenset(b for b, i in drift.items() if i["status"] == "deficit")
    # Passato a build_reinforcement_candidates per escludere strumenti la
    # cui esposizione maggioritaria REALE e' un bucket gia' in surplus
    # (vedi commento su surplus_buckets li' dentro - bug utente 2026-09-20).
    surplus_bucket_names = frozenset(b for b, i in drift.items() if i["status"] == "surplus")

    plan: dict[str, dict[str, Any]] = {}
    total_covered = 0.0
    venduto_reale_by_ticker: dict[str, float] = {}
    # run_sator_analysis a budget 0.0: qui serve solo il `ranking` (voto per
    # ticker) e il `returns_frame` per la classificazione lato riduzione
    # (Livelli 1/2/3b in build_reduction_candidates), che non dipende dal
    # budget - solo dal voto e dal returns_frame, quindi budget=0.0 va bene
    # qui, separato dalla chiamata con budget reale sotto (che serve solo
    # per dimensionare il rinforzo con _suggested_quotes_by_bucket).
    result_riduzione = run_sator_analysis(data, settings, budget=0.0)
    ranking_per_riduzione = result_riduzione.get("ranking")
    returns_frame_condiviso = result_riduzione.get("returns_frame")
    for bucket, info in drift.items():
        if info["status"] != "surplus":
            continue
        reduction = build_reduction_candidates(
            data, state_df, bucket, float(info["amount_eur"]), exclude_tickers,
            ranking=ranking_per_riduzione, returns_frame=returns_frame_condiviso,
            deficit_buckets=deficit_bucket_names,
            venduto_reale_by_ticker=venduto_reale_by_ticker,
        )
        plan[bucket] = {**info, "reduction": reduction}
        total_covered += reduction["covered_eur"]
        # Fix post-review: ogni euro di vendita reale gia' impegnato in
        # QUESTA card riduce cio' che resta disponibile per le card dei
        # bucket successivi (ordine = drift.items(), cioe' l'ordine di
        # _BUCKETS: Core, Difensivo, Satellite - un bucket precedente ha
        # priorita' su uno successivo quando condividono lo stesso
        # strumento, deterministico, nessuna preferenza finanziaria tra un
        # ordine e l'altro).
        for c in reduction["candidates"]:
            venduto_eur = float(c.get("quota_vendita_eur", 0.0))
            if venduto_eur > 0:
                venduto_reale_by_ticker[c["ticker"]] = (
                    venduto_reale_by_ticker.get(c["ticker"], 0.0) + venduto_eur
                )

    deficit_buckets = {b: i for b, i in drift.items() if i["status"] == "deficit"}
    total_deficit = sum(float(i["amount_eur"]) for i in deficit_buckets.values())
    # Feedback utente 2026-09-19: le "due opzioni" (con il ricavato delle
    # vendite / a capitale nuovo) sono state RESPINTE - confondevano piu'
    # di quanto chiarissero, nessuna delle due raggiungeva mai la cifra
    # indicata e l'utente non riusciva a capire quale seguire. Un solo
    # scenario, coerente con le vendite proposte nella STESSA tabella: il
    # budget e' il ricavato REALE che quelle vendite generano (quota_budget
    # sotto), non un'ipotesi di capitale fresco. Budget di riferimento per
    # il costo SATOR (_score_cost) = il ricavato reale, oppure il gap
    # totale se non c'e' ancora surplus (serve comunque un ranking per
    # poter mostrare cosa comprerebbe se si liberasse ricavato).
    ranking_per_rinforzo = (
        run_sator_analysis(data, settings, budget=max(total_covered, total_deficit)).get("ranking")
        if total_deficit > 0 else None
    )

    # Ticker gia' proposti come rinforzo in un bucket precedente di questo
    # stesso ciclo (bug reale utente 2026-09-21, vedi commento su
    # already_used_tickers in build_reinforcement_candidates): uno strumento
    # a esposizione frazionata su piu' bucket, entrambi in deficit, non deve
    # comparire due volte con lo stesso consiglio. Ordine = deficit_buckets
    # .items() = ordine di _BUCKETS (Core, Difensivo, Satellite), stesso
    # principio deterministico gia' usato per venduto_reale_by_ticker sopra.
    reinforced_tickers: set[str] = set()
    for bucket, info in deficit_buckets.items():
        amount_eur = float(info["amount_eur"])
        quota_budget = (
            total_covered * (amount_eur / total_deficit) if total_deficit > 0 else 0.0
        )
        quota_budget = min(quota_budget, amount_eur)  # mai oltre il gap-a-target
        result = (
            build_reinforcement_candidates(
                ranking_per_rinforzo, data, settings, bucket, quota_budget,
                current_mix, objective, portfolio_value,
                surplus_buckets=surplus_bucket_names,
                already_used_tickers=frozenset(reinforced_tickers),
            )
            if ranking_per_rinforzo is not None and quota_budget > 0 else
            {"candidates": [], "covered_eur": 0.0, "budget_insufficiente": True}
        )
        reinforced_tickers.update(str(c["ticker"]) for c in result["candidates"])
        # Copertura del lato rinforzo (stessa semantica del lato riduzione):
        # covered_eur e' GIA' la somma di TUTTI i candidati restituiti
        # (nessun taglio a top_n - vedi build_reinforcement_candidates),
        # quindi coverage_pct riflette il budget davvero deployabile.
        # Denominatore = amount_eur (il gap A TARGET), non quota_budget:
        # mostra la verita' anche quando la causa della copertura bassa e'
        # il ricavato insufficiente dal lato vendita.
        coverage_pct = min(1.0, result["covered_eur"] / amount_eur) if amount_eur > 0 else 0.0
        plan[bucket] = {
            **info,
            "budget_eur": quota_budget,
            "reinforcement": {**result, "coverage_pct": coverage_pct},
        }

    return plan


def build_full_instrument_view(
    data: dict[str, Any],
    state_df: pd.DataFrame,
    plan: dict[str, dict[str, Any]],
    exclude_tickers: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Vista completa: OGNI strumento posseduto compare con un verdetto
    (vendi/compra/non_toccare/tieni), non solo quelli del bucket in
    surplus analizzato per la vendita. Feedback utente 2026-09-19/20:
    "perche' me ne fai vedere solo 9 e non tutti?!" - un bucket in
    deficit (es. Core) non genera mai un candidato alla vendita per i
    suoi strumenti gia' posseduti (non avrebbe senso venderli, il bucket
    ha bisogno di PIU' non di meno), quindi questi restavano semplicemente
    ASSENTI dal risultato di build_rebalancing_plan - non "esclusi con un
    motivo", proprio mai considerati. Qui ogni strumento posseduto che il
    piano non ha gia' toccato (ne' come vendi/non_toccare/compra, ne' come
    tenuto nel bucket in surplus) compare comunque, con la sua
    composizione per bucket (`esposizione`, dict bucket->frazione, per una
    barra visiva) e un motivo minimo ("gia' in <bucket>, in deficit").

    Ogni riga porta anche `controvalore` (valore reale della posizione) e
    `esposizione`, utili per un'eventuale barra proporzionale lato UI -
    nessun calcolo di rischio o di peso nuovo, solo dati gia' presenti in
    build_rebalancing_plan/compute_instrument_bucket_exposures riletti in
    forma di riga singola."""
    if state_df is None or state_df.empty:
        return []
    held = state_df[state_df["Controvalore"] > 0].copy()
    held["Ticker"] = held["Ticker"].astype(str).str.strip().str.upper()
    tickers = [str(t) for t in held["Ticker"]]
    exposures = compute_instrument_bucket_exposures(data, held_tickers=set(tickers))
    rows_by_ticker = held.set_index("Ticker").to_dict(orient="index")

    righe: list[dict[str, Any]] = []
    accounted: set[str] = set()

    for bucket, info in plan.items():
        if info["status"] == "surplus":
            for c in info["reduction"]["candidates"]:
                ticker = str(c["ticker"])
                righe.append({
                    "ticker": ticker,
                    "name": c.get("name", ""),
                    "verdetto": "non_toccare" if c.get("non_toccare") else "vendi",
                    "quote": c.get("quote_vendita"),
                    "importo_eur": c.get("quota_vendita_eur"),
                    "motivo": c.get("perche", ""),
                    "forzato": bool(c.get("forzato", False)),
                    "pl_eur": c.get("pl_eur"),
                    "is_gov_bond": c.get("is_gov_bond"),
                    # Livello di convenienza (0-5) gia' classificato da
                    # _classify_reduction_candidate - riusato per un badge
                    # grafico compatto lato UI invece di una frase intera.
                    "livello": c.get("_livello"),
                    "esposizione": exposures.get(ticker, {}),
                    "controvalore": float(rows_by_ticker.get(ticker, {}).get("Controvalore", 0.0)),
                })
                accounted.add(ticker)
            for t in info["reduction"]["tenuti"]:
                ticker = str(t["ticker"])
                righe.append({
                    "ticker": ticker,
                    "name": t.get("name", ""),
                    "verdetto": "tieni",
                    "motivo": t.get("motivo", ""),
                    "esposizione": exposures.get(ticker, {}),
                    "controvalore": float(rows_by_ticker.get(ticker, {}).get("Controvalore", 0.0)),
                })
                accounted.add(ticker)
        else:
            for c in info["reinforcement"]["candidates"]:
                ticker = str(c["ticker"])
                righe.append({
                    "ticker": ticker,
                    "name": c.get("name", ""),
                    "verdetto": "compra",
                    "quote": c.get("quote"),
                    "importo_eur": c.get("importo_eur"),
                    "motivo": c.get("perche", ""),
                    "voto": c.get("voto"),
                    "top_factor": c.get("top_factor"),
                    # Un'alternativa (feedback utente 2026-09-20: "vorrei
                    # poter fare azionario") e' un OPPURE, non un acquisto
                    # aggiuntivo: stessa cifra del primario, non sommata al
                    # budget disponibile - la UI deve marcarla senza
                    # contarla come una seconda spesa.
                    "alternativa": bool(c.get("alternativa", False)),
                    "esposizione": exposures.get(ticker, {}),
                    "controvalore": float(rows_by_ticker.get(ticker, {}).get("Controvalore", 0.0)),
                })
                accounted.add(ticker)

    for ticker in tickers:
        if ticker in accounted:
            continue
        esposizione = exposures.get(ticker, {})
        bucket_labels = sorted(b for b, f in esposizione.items() if float(f) > 0)
        row = rows_by_ticker.get(ticker, {})
        if ticker in exclude_tickers:
            motivo = "Escluso dal toggle attivo (es. \"Escludi BTP/GOV\")."
        elif bucket_labels:
            motivo = f"Gia' in {'/'.join(bucket_labels)}, oggi in deficit o in banda: nulla da vendere qui."
        else:
            motivo = "Nessuna esposizione a bucket nota."
        righe.append({
            "ticker": ticker,
            "name": row.get("Strumento", ticker),
            "verdetto": "tieni",
            "motivo": motivo,
            "esposizione": esposizione,
            "controvalore": float(row.get("Controvalore", 0.0)),
        })
        accounted.add(ticker)

    return righe
