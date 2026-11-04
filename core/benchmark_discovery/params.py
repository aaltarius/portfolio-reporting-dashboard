"""Parametri dell'algoritmo di scoperta, in un solo punto (specifica, sezione 12)."""
PARAMS = {
    "w_corr": 0.45,          # peso della correlazione
    "w_te": 0.25,            # peso del tracking error
    "w_meta": 0.20,          # peso della coerenza dei metadati
    "w_hist": 0.10,          # peso della lunghezza dello storico
    "te_ref_pct": 20.0,      # tracking error annuo oltre il quale il contributo e' nullo
    "hist_ref_weeks": 260,   # settimane di storico che danno il contributo pieno
    "min_coherence": 0.5,    # sotto questa soglia il candidato e' scartato
    "min_obs": 12,           # minimo assoluto di rendimenti settimanali in comune
    "window_weeks": 260,     # finestra massima di misura
    "min_valid": 3,          # ci si ferma al livello in cui i candidati validi sono almeno 3
    "max_eval_per_level": 15,
    "attempt_factor": 3,     # tentativi di valutazione per livello = max_eval_per_level x questo (se molti candidati non hanno storico)
    "good_corr": 0.80,       # finche' il migliore del livello e' sotto questa correlazione si scende di livello
    "min_corr": 0.30,        # sotto questa correlazione un candidato non e' un benchmark
    "low_vol_pct": 1.0,      # sotto questa volatilita' annua dello strumento la correlazione e' instabile: conta lo scostamento
    "w_ccy": 0.10,           # penalita' se la valuta di quotazione del candidato non e' quella del portafoglio
    "target_currency": "EUR",
    "listing_tolerance": 0.02,  # una quotazione in valuta del portafoglio vale se la correlazione non scende oltre questo
    "same_product_name_similarity": 0.6,  # somiglianza minima dei nomi per riconoscere la stessa quotazione
    "listing_top_k": 5,      # per quanti candidati in testa si cerca la quotazione nella valuta del portafoglio
    "truncated_name_len": 28,  # un nome breve lungo almeno cosi' e' quasi certamente troncato: si legge il nome completo
    "index_preference": 0.05,  # senza strumento proprio un indice vale di piu' di un ETF proxy
    "composite_top_k": 6,    # gambe candidate per ciascun lato di un composito
    "metadata_only_scale": 0.5,  # un candidato senza misura vale al massimo meta' di uno misurato
}
