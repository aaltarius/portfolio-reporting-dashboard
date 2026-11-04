"""Politica unica dei volumi su disco: tetti di retention di backup, log e cache.

Modulo senza dipendenze (solo costanti) cosi' puo' essere importato da
`persistence`, `core` e `ui` senza cicli. Ogni artefatto che cresce nel tempo
deve avere qui il proprio tetto; i default dei settings e i fallback nel
codice leggono da questo file, mai numeri letterali sparsi.

Tetto teorico complessivo (escluso `.git` e `data/portfolio`, `data/prices`):
backup ~50 MB, log ~8 MB, storico profiler ~3 MB, cache figure 100 MB,
page_artifacts ~15 MB.
"""

# Backup: cartelle timestamp in `backups/` (~4,7 MB l'una), potate da
# `persistence.storage._prune_backups` a ogni save.
BACKUP_KEEP_LAST_N = 10
# Salvataggi automatici (aggiornamento quotazioni): al massimo un bundle di backup
# ogni 30 minuti. I salvataggi manuali (operazioni, strumenti, impostazioni) fanno
# sempre il backup. Ogni bundle pesa ~30 MB e costa ~0,3 s.
BACKUP_AUTO_MIN_INTERVAL_MINUTES = 30

# Log applicativo: RotatingFileHandler, tetto = MAX_BYTES * (1 + BACKUP_COUNT).
LOG_MAX_BYTES = 2 * 1024 * 1024
LOG_BACKUP_COUNT = 2

# Storico profiler render (`data/logs/render_profile_history.jsonl`): tetto sia
# sul numero di run sia sui byte (una run puo' pesare >100 KB).
RENDER_PROFILE_HISTORY_MAX_RUNS = 20
RENDER_PROFILE_HISTORY_MAX_BYTES = 3 * 1024 * 1024

# Cache figure (`data/cache/figures`): eta' massima e tetto in MB.
FIGURE_CACHE_CLEANUP_DAYS = 14
FIGURE_CACHE_MAX_MB = 100
# Varianti conservate per ogni figura (chart_id + parametri, es. un ticker): le
# firme cambiano a ogni variazione dei dati, le versioni vecchie non si
# riusano piu'. Prima: 4.766 file per le sole figure per strumento.
FIGURE_CACHE_MAX_VARIANTS_PER_CHART = 3

# Artefatti pagina (`data/cache/page_artifacts`): versioni per (pagina, layer).
PAGE_ARTIFACT_KEEP_PER_LAYER = 3
