"""Interruttore della sincronizzazione (spento di default)."""
from __future__ import annotations


def is_enabled(settings: dict | None) -> bool:
    cfg = settings.get("mobile_sync") if isinstance(settings, dict) else None
    return bool(isinstance(cfg, dict) and cfg.get("enabled", False))
