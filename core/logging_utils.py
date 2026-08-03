"""
core/logging_utils.py - Configurazione centralizzata del logging applicativo.
"""
from __future__ import annotations

import logging
import os
from collections import deque
from logging.handlers import RotatingFileHandler
from pathlib import Path


DEFAULT_LOGGER_NAME = "portafoglio"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3
LOG_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


def resolve_log_level(value: str | int | None, default: int = logging.INFO) -> int:
    if isinstance(value, int):
        return value
    label = str(value or "").upper()
    return LOG_LEVEL_MAP.get(label, default)


def _resolve_log_file(log_dir: str | os.PathLike[str] | None = None) -> Path:
    if log_dir is None:
        base_dir = Path(__file__).resolve().parent.parent
        target_dir = base_dir / "data" / "logs"
    else:
        target_dir = Path(log_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / "portafoglio.log"


def configure_logging(
    logger_name: str = DEFAULT_LOGGER_NAME,
    level: int = logging.INFO,
    log_dir: str | os.PathLike[str] | None = None,
) -> logging.Logger:
    """Configura un logger applicativo con handler file e stream, in modo idempotente."""
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.propagate = bool(os.getenv("PYTEST_CURRENT_TEST")) or os.getenv("PORTFOLIO_TESTING") == "1"

    log_file = _resolve_log_file(log_dir)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    existing_file_handler = None
    existing_stream_handler = None
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler):
            existing_file_handler = handler
        elif isinstance(handler, logging.StreamHandler):
            existing_stream_handler = handler
        handler.setLevel(level)
        handler.setFormatter(formatter)

    if existing_file_handler is None:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    if existing_stream_handler is None:
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(level)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    setattr(logger, "_portafoglio_log_file", str(log_file))
    return logger


def get_log_file_path(logger: logging.Logger) -> str | None:
    """Restituisce il path del file di log configurato, se presente."""
    return getattr(logger, "_portafoglio_log_file", None)


def get_default_log_file_path(log_dir: str | os.PathLike[str] | None = None) -> str:
    """Restituisce il path standard del file di log applicativo."""
    return str(_resolve_log_file(log_dir))


def read_log_tail(
    lines: int = 50,
    log_dir: str | os.PathLike[str] | None = None,
) -> list[str]:
    """Legge le ultime righe del file di log applicativo."""
    log_file = _resolve_log_file(log_dir)
    if not log_file.exists():
        return []
    max_lines = max(int(lines), 1)
    with log_file.open("r", encoding="utf-8", errors="replace") as handle:
        return list(deque(handle, maxlen=max_lines))


def get_log_file_stats(log_dir: str | os.PathLike[str] | None = None) -> dict[str, object]:
    """Restituisce metadati essenziali del file di log applicativo."""
    log_file = _resolve_log_file(log_dir)
    exists = log_file.exists()
    stat = log_file.stat() if exists else None
    return {
        "path": str(log_file),
        "exists": exists,
        "size_bytes": int(stat.st_size) if stat else 0,
        "modified_at": float(stat.st_mtime) if stat else None,
    }
