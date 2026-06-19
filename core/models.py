"""
core/models.py — Re-export delle funzioni di modello dati da persistence.storage.
Fornisce un'API stabile per il dominio degli eventi e della categorizzazione
senza dipendere direttamente da persistence nei moduli di livello superiore.
"""
from persistence.storage import (
    # Costanti di dominio
    APP_VERSION,
    SCHEMA_VERSION,
    TIPI_EVENTO_PORTAFOGLIO,
    EVENTI_CON_STRUMENTO,
    EVENTI_CON_QUANTITA,
    EVENTI_CON_PREZZO,
    EVENTI_CON_IMPORTO,
    BENCH,

    # Categorizzazione strumenti
    _normalize_macro_label,
    macro_cat,

    # Funzioni evento
    _event_sort_key,
    _new_event_id,
    _normalize_event_record,
    _rebuild_cash_ledger_from_events,

    # Accessori registro
    get_registro_eventi,
    get_proventi_normalizzati,

    # Serializzazione cache
    _serialize_df_for_cache,
    _restore_df_from_cache,

    # Firma cache
    _state_signature,
    _portfolio_state_signature,

    # Instrument master
    _build_instrument_master,
)

__all__ = [
    "APP_VERSION", "SCHEMA_VERSION",
    "TIPI_EVENTO_PORTAFOGLIO", "EVENTI_CON_STRUMENTO", "EVENTI_CON_QUANTITA",
    "EVENTI_CON_PREZZO", "EVENTI_CON_IMPORTO", "BENCH",
    "_normalize_macro_label", "macro_cat",
    "_event_sort_key", "_new_event_id",
    "_normalize_event_record", "_rebuild_cash_ledger_from_events",
    "get_registro_eventi", "get_proventi_normalizzati",
    "_serialize_df_for_cache", "_restore_df_from_cache",
    "_state_signature", "_portfolio_state_signature",
    "_build_instrument_master",
]
