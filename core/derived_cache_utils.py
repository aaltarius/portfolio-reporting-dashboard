"""core/derived_cache_utils.py — pulizia cache pickle derivate (data/cache/derived_runtime).

Le cache in derived_runtime sono memoization keyed by firma: ogni volta che la
firma cambia (nuovo prezzo, nuova data) viene scritto un nuovo file e quello
precedente diventa inutile (non è uno storico). Questo helper elimina i file
superati per la stessa chiave logica (es. ticker) subito dopo aver scritto la
nuova versione, cosi' la cartella non cresce senza limite.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("portafoglio.core.derived_cache_utils")


def prune_sibling_pkl(directory: str, key_prefix: str, keep_path: str) -> int:
    """Elimina in ``directory`` i file ``{key_prefix}_*.pkl`` diversi da ``keep_path``."""
    removed = 0
    try:
        if not os.path.isdir(directory):
            return 0
        keep_name = os.path.basename(keep_path)
        prefix = f"{key_prefix}_"
        for name in os.listdir(directory):
            if name == keep_name or not name.startswith(prefix) or not name.endswith(".pkl"):
                continue
            try:
                os.remove(os.path.join(directory, name))
                removed += 1
            except Exception:
                logger.warning("Impossibile rimuovere cache derivata obsoleta: %s", name, exc_info=True)
    except Exception:
        logger.warning("Pulizia cache derivata fallita per prefix=%s", key_prefix, exc_info=True)
    return removed
