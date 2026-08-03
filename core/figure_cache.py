import logging
import json
import gzip
import pickle
import os
import time
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Callable, Dict, Any
import streamlit as st
import plotly.graph_objects as go
import plotly.io as pio

from core.cache_signatures import cache_key, figure_signature
from persistence.storage import DATA_DIR


logger = logging.getLogger("portafoglio.figure_cache")


class CachingStrategy:
    """Enum-like class for caching strategies."""
    DISABLED = "disabled"
    SESSION_ONLY = "session_only"
    DISK_ONLY = "disk_only"
    HYBRID = "hybrid"


class FigureCache:
    """Hybrid cache infrastructure for Plotly figures (session + disk)."""

    # Class constants
    CACHE_DIR = Path(DATA_DIR) / "cache" / "figures"
    MANIFEST_FILE = Path(DATA_DIR) / "cache" / "cache_manifest.json"
    USE_GZIP = True  # Enable gzip compression for figures (Streamlit best practice: Tip #5)
    _MANIFEST_LOCK = threading.RLock()
    _BUILD_LOCKS_GUARD = threading.RLock()
    _BUILD_LOCKS: Dict[str, threading.Lock] = {}
    # Manifest tenuto in memoria per tutta la durata del processo: evita di
    # fare un read-modify-write(+fsync) del file su ogni singolo cache miss
    # (con manifest grandi, es. migliaia di entry, questo costava decine di ms
    # per figura, moltiplicati per le decine di miss di un run con molte
    # invalidazioni). Viene scritto su disco solo da flush_manifest().
    _MANIFEST_CACHE: Optional[Dict[str, Any]] = None
    _MANIFEST_DIRTY: bool = False
    # Registro diagnostico in-memory: log_label -> parti firma dell'ultima build/hit.
    # Persiste per tutta la durata del processo Streamlit (sopravvive ai rerun).
    _DIAG_PARTS: Dict[str, Dict[str, Any]] = {}

    def __init__(self):
        """Initialize FigureCache and ensure cache directory exists."""
        self._ensure_cache_dir()
        self._sanitize_manifest()
        logger.info("FigureCache initialized")

    def _ensure_cache_dir(self) -> None:
        """Create cache directory if it doesn't exist. Handle errors gracefully."""
        try:
            self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Cache directory ensured at {self.CACHE_DIR}")
        except Exception as e:
            logger.error(f"Failed to create cache directory {self.CACHE_DIR}: {e}")

    def _cache_file_stem(self, chart_id: str, fig_sig: str) -> str:
        """Nome base del file cache senza estensione finale.

        cache_key() restituisce già un nome con suffisso .json; se aggiungiamo
        ancora .json.gz otteniamo file *.json.json.gz. Questo helper normalizza
        lo stem una sola volta.
        """
        file_key = cache_key(chart_id, fig_sig)
        if file_key.endswith(".json"):
            file_key = file_key[:-5]
        return file_key

    def _iter_cache_files(self):
        """Itera tutti i formati cache figura supportati."""
        if not self.CACHE_DIR.exists():
            return []
        patterns = ("*.json.gz", "*.json.json.gz", "*.pickle.gz", "*.pickle")
        files = []
        for pattern in patterns:
            files.extend(self.CACHE_DIR.glob(pattern))
        seen = set()
        unique = []
        for path in files:
            if path not in seen:
                seen.add(path)
                unique.append(path)
        return unique

    def _load_cleanup_preferences(self) -> tuple[int, float]:
        try:
            from persistence.storage import load_settings
            from core.settings_profiles import get_figure_cache_settings

            cache_cfg = get_figure_cache_settings(load_settings() or {})
        except Exception:
            cache_cfg = {}
        cleanup_days = int(cache_cfg.get("auto_cleanup_days", 30) or 30)
        max_size_mb = float(cache_cfg.get("max_cache_size_mb", 500) or 500)
        return cleanup_days, max_size_mb

    def _auto_cleanup(self) -> None:
        try:
            cleanup_days, max_size_mb = self._load_cleanup_preferences()
            now = datetime.now()
            cutoff = now - timedelta(days=max(cleanup_days, 0))
            removed = 0
            kept_files: list[tuple[Path, os.stat_result]] = []
            for path in self.CACHE_DIR.glob("*"):
                if not path.is_file():
                    continue
                try:
                    stat = path.stat()
                except Exception:
                    continue
                mtime = datetime.fromtimestamp(stat.st_mtime)
                if cleanup_days > 0 and mtime < cutoff:
                    try:
                        path.unlink(missing_ok=True)
                        removed += 1
                    except Exception:
                        continue
                else:
                    kept_files.append((path, stat))

            max_size_bytes = max_size_mb * 1024 * 1024
            total_size = sum(item[1].st_size for item in kept_files)
            if max_size_bytes > 0 and total_size > max_size_bytes:
                for path, stat in sorted(kept_files, key=lambda item: item[1].st_mtime):
                    if total_size <= max_size_bytes:
                        break
                    try:
                        path.unlink(missing_ok=True)
                        total_size -= stat.st_size
                        removed += 1
                    except Exception:
                        continue

            if removed:
                self._sanitize_manifest()
                logger.info("Figure cache cleanup: rimossi %s file obsoleti", removed)
        except Exception as exc:
            logger.warning("Figure cache cleanup non eseguito: %s", exc)

    def get_or_build(
        self,
        chart_id: str,
        data_sig: str,
        theme_sig: str,
        charts_settings_sig: str,
        builder: Callable[[], go.Figure],
        page_mode: Optional[str] = None,
        extra_params: Optional[Dict[str, Any]] = None,
        strategy: str = CachingStrategy.HYBRID,
        record_event: bool = True,
    ) -> go.Figure:
        """
        Get figure from cache or build it.

        Logic:
        1. Generate fig_sig via figure_signature()
        2. Check session cache first (if strategy != DISABLED)
        3. Check disk cache (if strategy in DISK_ONLY, HYBRID)
        4. Call builder() on miss
        5. Save to session and disk (if enabled)
        6. Return figure

        Args:
            chart_id: Identifier for the chart
            data_sig: Signature of data
            theme_sig: Signature of theme
            charts_settings_sig: Signature of charts settings
            builder: Callable that builds the figure
            page_mode: Optional page mode
            extra_params: Optional extra parameters
            strategy: Caching strategy (default: HYBRID)

        Returns:
            go.Figure: The cached or built figure
        """
        try:
            # Generate figure signature
            fig_sig = figure_signature(
                chart_id=chart_id,
                data_sig=data_sig,
                theme_sig=theme_sig,
                charts_settings_sig=charts_settings_sig,
                page_mode=page_mode or "Rapida",
                extra_params=extra_params
            )
            session_key = f"_fig_cache_{chart_id}_{fig_sig}"
            build_key = f"{chart_id}:{fig_sig}"
            log_label = self._log_label(chart_id, extra_params)

            logger.debug(f"get_or_build: chart_id={log_label}, fig_sig={fig_sig}, strategy={strategy}")

            # Check session cache first (if enabled and not DISK_ONLY)
            if strategy != CachingStrategy.DISABLED and strategy != CachingStrategy.DISK_ONLY:
                if session_key in st.session_state:
                    logger.debug(f"Cache HIT (session): {log_label}")
                    if record_event:
                        self._record_cache_event(chart_id, "session_hit", fig_sig)
                    self._update_diag_parts(log_label, fig_sig, data_sig, theme_sig, charts_settings_sig, page_mode, extra_params)
                    return st.session_state[session_key]
                else:
                    logger.debug(f"Cache MISS (session): {log_label}")

            # Check disk cache (if strategy in DISK_ONLY, HYBRID)
            if strategy in (CachingStrategy.DISK_ONLY, CachingStrategy.HYBRID):
                fig = self._load_from_disk(chart_id, fig_sig)
                if fig is not None:
                    logger.debug(f"Cache HIT (disk): {log_label}")
                    if record_event:
                        self._record_cache_event(chart_id, "disk_hit", fig_sig)
                    # Restore to session cache for future hits (if not DISK_ONLY)
                    if strategy == CachingStrategy.HYBRID:
                        st.session_state[session_key] = fig
                    self._update_diag_parts(log_label, fig_sig, data_sig, theme_sig, charts_settings_sig, page_mode, extra_params)
                    return fig
                else:
                    logger.debug(f"Cache MISS (disk): {log_label}")

            with self._get_build_lock(build_key):
                # Re-check cache inside lock to deduplicate concurrent builds
                if strategy != CachingStrategy.DISABLED and strategy != CachingStrategy.DISK_ONLY:
                    if session_key in st.session_state:
                        logger.debug(f"Cache HIT (session-after-wait): {log_label}")
                        if record_event:
                            self._record_cache_event(chart_id, "session_hit", fig_sig)
                        return st.session_state[session_key]

                if strategy in (CachingStrategy.DISK_ONLY, CachingStrategy.HYBRID):
                    fig = self._load_from_disk(chart_id, fig_sig)
                    if fig is not None:
                        logger.debug(f"Cache HIT (disk-after-wait): {log_label}")
                        if record_event:
                            self._record_cache_event(chart_id, "disk_hit", fig_sig)
                        if strategy == CachingStrategy.HYBRID:
                            st.session_state[session_key] = fig
                        return fig

                # Cache miss - build figure
                logger.debug(f"Cache MISS: building {log_label}")
                if record_event:
                    self._record_cache_event(chart_id, "miss", fig_sig)
                self._log_miss_diff(log_label, {
                    "fig_sig": fig_sig,
                    "data_sig": data_sig,
                    "theme_sig": theme_sig,
                    "charts_settings_sig": charts_settings_sig,
                    "page_mode": page_mode or "Rapida",
                    "extra_params": dict(extra_params) if extra_params else None,
                })
                fig = builder()
                self._update_diag_parts(log_label, fig_sig, data_sig, theme_sig, charts_settings_sig, page_mode, extra_params)

                # Save to session cache (if not DISK_ONLY)
                if strategy != CachingStrategy.DISABLED and strategy != CachingStrategy.DISK_ONLY:
                    st.session_state[session_key] = fig
                    logger.debug(f"Figure cached in session: {log_label}")

                # Save to disk cache (if enabled)
                if strategy in (CachingStrategy.DISK_ONLY, CachingStrategy.HYBRID):
                    self._save_to_disk(chart_id, fig_sig, fig)

                return fig

        except Exception as e:
            logger.error(f"Error in get_or_build for {log_label}: {e}", exc_info=True)
            # Graceful degradation: build and return without caching
            return builder()

    @classmethod
    def _get_build_lock(cls, build_key: str) -> threading.Lock:
        with cls._BUILD_LOCKS_GUARD:
            lock = cls._BUILD_LOCKS.get(build_key)
            if lock is None:
                lock = threading.Lock()
                cls._BUILD_LOCKS[build_key] = lock
            return lock

    @staticmethod
    def _log_label(chart_id: str, extra_params: Optional[Dict[str, Any]]) -> str:
        if not extra_params:
            return chart_id
        preferred_keys = ("category", "ticker", "instrument", "profile", "scope")
        parts: list[str] = []
        for key in preferred_keys:
            value = extra_params.get(key)
            if value is not None and value != "":
                parts.append(f"{key}={value}")
        if not parts:
            for key in sorted(extra_params):
                value = extra_params.get(key)
                if value is not None and value != "":
                    parts.append(f"{key}={value}")
        if not parts:
            return chart_id
        return f"{chart_id}[{', '.join(parts)}]"

    def _update_diag_parts(
        self,
        log_label: str,
        fig_sig: str,
        data_sig: str,
        theme_sig: str,
        charts_settings_sig: str,
        page_mode: Optional[str],
        extra_params: Optional[Dict[str, Any]],
    ) -> None:
        """Memorizza le parti della firma corrente per confronto ai miss successivi."""
        type(self)._DIAG_PARTS[log_label] = {
            "fig_sig": fig_sig,
            "data_sig": data_sig,
            "theme_sig": theme_sig,
            "charts_settings_sig": charts_settings_sig,
            "page_mode": page_mode or "Rapida",
            "extra_params": dict(extra_params) if extra_params else None,
        }

    def _log_miss_diff(self, log_label: str, current_parts: Dict[str, Any]) -> None:
        """Confronta la firma corrente con la precedente e logga il diff strutturato.

        Produce una riga INFO con reason + old/new sig, e una riga DEBUG con il
        dettaglio completo dei campi cambiati. Usato esclusivamente per diagnostica.
        """
        prev = type(self)._DIAG_PARTS.get(log_label)
        old_sig = prev.get("fig_sig", "?") if prev else None
        new_sig = current_parts.get("fig_sig", "?")

        if not prev:
            logger.info(
                "[MISS_DIAG] %s | reason=cache_mai_popolata | new_sig=%s",
                log_label, new_sig,
            )
            return

        diff: Dict[str, Any] = {}
        for key in ("data_sig", "theme_sig", "charts_settings_sig", "page_mode"):
            old_v = prev.get(key)
            new_v = current_parts.get(key)
            if old_v != new_v:
                diff[key] = {"old": old_v, "new": new_v}

        old_extra = prev.get("extra_params") or {}
        new_extra = current_parts.get("extra_params") or {}
        extra_keys = set(list(old_extra.keys()) + list(new_extra.keys()))
        extra_diff = {
            k: {"old": old_extra.get(k), "new": new_extra.get(k)}
            for k in extra_keys
            if old_extra.get(k) != new_extra.get(k)
        }
        if extra_diff:
            diff["extra_params"] = extra_diff

        if not diff:
            reason = "INVARIATA_file_mancante"
        elif "data_sig" in diff:
            reason = "data_sig_cambiata"
        elif "theme_sig" in diff:
            reason = "tema_cambiato"
        elif "charts_settings_sig" in diff:
            reason = "settings_grafici_cambiati"
        elif "page_mode" in diff:
            reason = "page_mode_cambiato"
        else:
            reason = "extra_params_cambiati"

        logger.info(
            "[MISS_DIAG] %s | reason=%s | old_sig=%s | new_sig=%s | diff_keys=%s",
            log_label, reason, old_sig, new_sig, list(diff.keys()),
        )
        logger.debug("[MISS_DIAG_DETAIL] %s | %s", log_label, json.dumps(diff, default=str))

    def _load_from_disk(self, chart_id: str, fig_sig: str) -> Optional[go.Figure]:
        """
        Carica figura da disco con JSON+gzip (nuovo) o pickle.gz (migrazione legacy).

        Strategia:
        1. Prova .json.gz (nuovo formato)
        2. Fallback su .pickle.gz (legacy), converti, salva come .json.gz, cancella legacy
        3. Ritorna None se non trovato

        Args:
            chart_id: Identificatore grafico
            fig_sig: Firma figura

        Returns:
            go.Figure oppure None se non trovato o errore
        """
        try:
            file_key = self._cache_file_stem(chart_id, fig_sig)

            # Prova JSON prima (nuovo formato in 4.9.9+)
            json_candidates = [
                self.CACHE_DIR / f"{file_key}.json.gz",
                self.CACHE_DIR / f"{file_key}.json.json.gz",  # legacy bug 4.9.x
            ]
            for json_path in json_candidates:
                if json_path.exists():
                    try:
                        with gzip.open(json_path, 'rt', encoding='utf-8') as f:
                            json_str = f.read()
                            fig = pio.from_json(json_str)
                        logger.debug(f"Caricata figura da JSON: {json_path}")

                        correct_path = self.CACHE_DIR / f"{file_key}.json.gz"
                        if json_path.name.endswith(".json.json.gz") and not correct_path.exists():
                            try:
                                self._save_to_disk(chart_id, fig_sig, fig)
                                json_path.unlink(missing_ok=True)
                                logger.info(f"Migrata cache legacy {json_path.name} -> {correct_path.name}")
                            except Exception as mig_exc:
                                logger.warning(f"Migrazione cache legacy non riuscita per {json_path}: {mig_exc}")

                        return fig
                    except Exception as e:
                        logger.warning(f"Errore caricamento figura JSON {json_path}: {e}")

            # Fallback su pickle.gz (legacy, con migrazione one-time)
            pickle_candidates = [
                self.CACHE_DIR / f"{file_key}.pickle.gz",
                self.CACHE_DIR / f"{file_key}.json.pickle.gz",
            ]
            for pickle_path in pickle_candidates:
                if pickle_path.exists():
                    try:
                        with gzip.open(pickle_path, 'rb') as f:
                            fig = pickle.load(f)
                        logger.info(f"Caricata figura pickle legacy: {pickle_path}, conversione a JSON")
                        self._save_to_disk(chart_id, fig_sig, fig)
                        try:
                            pickle_path.unlink(missing_ok=True)
                            logger.info(f"Cancellato cache pickle legacy: {pickle_path}")
                        except Exception as e:
                            logger.warning(f"Impossibile cancellare file pickle legacy {pickle_path}: {e}")
                        return fig
                    except Exception as e:
                        logger.error(f"Errore caricamento figura pickle legacy {pickle_path}: {e}")

            logger.debug(f"File cache disco non trovato: {file_key}.*")
            return None

        except Exception as e:
            logger.error(f"Errore caricamento figura da disco per {chart_id}: {e}")
            return None

    def _save_to_disk(self, chart_id: str, fig_sig: str, fig: go.Figure) -> None:
        """
        Salva figura su disco come JSON+gzip (nuovo formato).

        Args:
            chart_id: Identificatore grafico
            fig_sig: Firma figura
            fig: Figura da salvare
        """
        try:
            file_key = self._cache_file_stem(chart_id, fig_sig)

            # Salva come JSON+gzip (nuovo formato in 4.9.9+)
            file_path = self.CACHE_DIR / f"{file_key}.json.gz"
            json_str = pio.to_json(fig)
            with gzip.open(file_path, 'wt', encoding='utf-8') as f:
                f.write(json_str)

            file_size = file_path.stat().st_size
            logger.debug(f"Figura salvata su disco (JSON): {file_path} ({file_size} bytes)")

            # Aggiorna manifest
            self._update_manifest(chart_id, fig_sig, file_size)

        except Exception as e:
            logger.error(f"Errore salvataggio figura su disco per {chart_id}: {e}")

    def _salvage_manifest_text(self, raw_text: str) -> Dict[str, Any]:
        """Try to recover the first valid JSON object from a corrupted manifest."""
        try:
            decoder = json.JSONDecoder()
            payload, _ = decoder.raw_decode((raw_text or "").lstrip())
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _backup_corrupted_manifest(self, raw_text: str) -> None:
        """Persist a copy of the corrupted manifest for post-mortem analysis."""
        try:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.MANIFEST_FILE.with_name(f"{self.MANIFEST_FILE.stem}.corrupt.{stamp}.json")
            backup_path.write_text(raw_text, encoding="utf-8")
            logger.warning(f"Corrupted manifest backed up to {backup_path}")
        except Exception as e:
            logger.warning(f"Failed to backup corrupted manifest: {e}")

    def _sanitize_manifest(self) -> None:
        """Repair a legacy corrupted manifest once at startup if possible."""
        try:
            with self._MANIFEST_LOCK:
                repaired = self._load_manifest(repair_on_corruption=True)
                if repaired:
                    logger.debug("Manifest sanity check completed")
        except Exception as e:
            logger.warning(f"Manifest sanitize skipped: {e}")

    def _load_manifest(self, *, repair_on_corruption: bool = False) -> Dict[str, Any]:
        """Restituisce il manifest in memoria, caricandolo da disco una sola volta.

        Le mutazioni successive (_update_manifest) restano in questo stesso
        dict finche' non arriva un flush_manifest() esplicito.
        """
        cls = type(self)
        with self._MANIFEST_LOCK:
            if cls._MANIFEST_CACHE is not None:
                return cls._MANIFEST_CACHE
            manifest = self._read_manifest_from_disk(repair_on_corruption=repair_on_corruption)
            cls._MANIFEST_CACHE = manifest
            return manifest

    def _read_manifest_from_disk(self, *, repair_on_corruption: bool = False) -> Dict[str, Any]:
        """Load manifest safely from disk, recovering gracefully from malformed JSON."""
        if not self.MANIFEST_FILE.exists():
            return {}
        try:
            raw_text = self.MANIFEST_FILE.read_text(encoding="utf-8")
            if not raw_text.strip():
                return {}
            payload = json.loads(raw_text)
            return payload if isinstance(payload, dict) else {}
        except json.JSONDecodeError as e:
            raw_text = ""
            try:
                raw_text = self.MANIFEST_FILE.read_text(encoding="utf-8")
            except Exception:
                pass
            salvaged = self._salvage_manifest_text(raw_text)
            if salvaged:
                logger.warning(f"Manifest corrupted, salvaged first JSON object: {e}")
                if repair_on_corruption:
                    self._write_manifest(salvaged)
                return salvaged
            logger.warning(f"Manifest corrupted and not recoverable: {e}")
            if raw_text:
                self._backup_corrupted_manifest(raw_text)
            return {}
        except Exception as e:
            logger.warning(f"Error reading manifest: {e}")
            return {}

    def _write_manifest(self, manifest: Dict[str, Any]) -> None:
        """Write manifest atomically to avoid partial or interleaved JSON writes."""
        self.MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.MANIFEST_FILE.with_name(
            f"{self.MANIFEST_FILE.stem}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2)
                f.flush()
                os.fsync(f.fileno())

            last_error: Exception | None = None
            for attempt in range(5):
                try:
                    os.replace(temp_path, self.MANIFEST_FILE)
                    return
                except PermissionError as exc:
                    last_error = exc
                    time.sleep(0.05 * (attempt + 1))
            if last_error is not None:
                raise last_error
        finally:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass

    def _update_manifest(self, chart_id: str, fig_sig: str, file_size: int) -> None:
        """
        Update cache manifest with new entry (in memory only; vedi flush_manifest()).

        Args:
            chart_id: Chart identifier
            fig_sig: Figure signature
            file_size: Size of cached file in bytes
        """
        try:
            with self._MANIFEST_LOCK:
                manifest = self._load_manifest(repair_on_corruption=True)

                key = f"{chart_id}_{fig_sig}"
                manifest[key] = {
                    "chart_id": chart_id,
                    "signature": fig_sig,
                    "file_size": file_size,
                    "timestamp": datetime.now().isoformat()
                }
                type(self)._MANIFEST_DIRTY = True
                logger.debug(f"Manifest updated (in memory, pending flush): {key}")

        except Exception as e:
            logger.error(f"Error updating manifest: {e}")

    def flush_manifest(self) -> bool:
        """Scrive su disco il manifest in-memory, se sporco.

        Va chiamata una volta per run (es. a fine rendering pagina), non ad
        ogni singolo cache miss: batchare qui il read-modify-write(+fsync)
        evita che un refresh con molti grafici invalidati paghi N volte il
        costo di I/O sull'intero file manifest.

        Returns:
            True se ha effettivamente scritto su disco, False se non c'era
            nulla da scrivere.
        """
        try:
            with self._MANIFEST_LOCK:
                cls = type(self)
                if not cls._MANIFEST_DIRTY or cls._MANIFEST_CACHE is None:
                    return False
                self._write_manifest(cls._MANIFEST_CACHE)
                cls._MANIFEST_DIRTY = False
                logger.debug("Manifest figure cache scritto su disco (flush)")
                return True
        except Exception as e:
            logger.error(f"Error flushing manifest: {e}")
            return False

    def maintain_cache(self, *, migrate_legacy: bool = True, remove_orphans: bool = True, enforce_limits: bool = True) -> Dict[str, Any]:
        """Manutenzione operativa della cache figure.

        - migra i vecchi *.json.json.gz in *.json.gz;
        - elimina pickle legacy quando esiste già il JSON corrispondente;
        - elimina file orfani non presenti nel manifest, se richiesto;
        - applica i limiti di età/dimensione configurati.

        Ritorna un report sintetico utilizzabile in Gestione Dati.
        """
        report = {
            "migrated_legacy_json": 0,
            "removed_legacy_pickle": 0,
            "removed_orphans": 0,
            "removed_by_policy": 0,
            "errors": [],
        }

        try:
            self._ensure_cache_dir()
            manifest = self._load_manifest(repair_on_corruption=True)
            manifest_filenames = set()

            for entry in manifest.values():
                chart_id = entry.get("chart_id")
                fig_sig = entry.get("signature")
                if chart_id and fig_sig:
                    stem = self._cache_file_stem(str(chart_id), str(fig_sig))
                    manifest_filenames.add(f"{stem}.json.gz")
                    manifest_filenames.add(f"{stem}.json.json.gz")
                    manifest_filenames.add(f"{stem}.pickle.gz")
                    manifest_filenames.add(f"{stem}.json.pickle.gz")

            if migrate_legacy and self.CACHE_DIR.exists():
                for legacy_path in list(self.CACHE_DIR.glob("*.json.json.gz")):
                    try:
                        new_name = legacy_path.name.replace(".json.json.gz", ".json.gz")
                        new_path = legacy_path.with_name(new_name)
                        if not new_path.exists():
                            legacy_path.replace(new_path)
                            report["migrated_legacy_json"] += 1
                        else:
                            legacy_path.unlink(missing_ok=True)
                            report["removed_orphans"] += 1
                    except Exception as exc:
                        report["errors"].append(f"migrazione {legacy_path.name}: {exc}")

            if self.CACHE_DIR.exists():
                # Se esiste un JSON nuovo, i pickle equivalenti sono superflui.
                for pickle_path in list(self.CACHE_DIR.glob("*.pickle*")):
                    try:
                        new_json_name = (
                            pickle_path.name
                            .replace(".json.pickle.gz", ".json.gz")
                            .replace(".pickle.gz", ".json.gz")
                            .replace(".pickle", ".json.gz")
                        )
                        if pickle_path.with_name(new_json_name).exists():
                            pickle_path.unlink(missing_ok=True)
                            report["removed_legacy_pickle"] += 1
                    except Exception as exc:
                        report["errors"].append(f"pickle {pickle_path.name}: {exc}")

            if remove_orphans and manifest_filenames and self.CACHE_DIR.exists():
                for path in list(self._iter_cache_files()):
                    try:
                        if path.name not in manifest_filenames and not path.name.endswith(".json.gz"):
                            path.unlink(missing_ok=True)
                            report["removed_orphans"] += 1
                    except Exception as exc:
                        report["errors"].append(f"orphan {path.name}: {exc}")

            if enforce_limits:
                before = len(self._iter_cache_files())
                self._auto_cleanup()
                after = len(self._iter_cache_files())
                report["removed_by_policy"] = max(0, before - after)

            self._sanitize_manifest()
        except Exception as exc:
            report["errors"].append(str(exc))

        return report


    def clear_all(self) -> int:
        """
        Clear all cached figures and manifest.

        Returns:
            int: Number of deleted files
        """
        try:
            deleted_count = 0

            # Delete all supported cache figure files
            if self.CACHE_DIR.exists():
                for file_path in self._iter_cache_files():
                    try:
                        file_path.unlink()
                        deleted_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to delete {file_path}: {e}")

            # Delete manifest file and reset the in-memory copy, altrimenti un
            # flush_manifest() successivo riscriverebbe su disco le entry
            # appena cancellate.
            with self._MANIFEST_LOCK:
                if self.MANIFEST_FILE.exists():
                    try:
                        self.MANIFEST_FILE.unlink()
                    except Exception as e:
                        logger.warning(f"Failed to delete manifest: {e}")
                type(self)._MANIFEST_CACHE = {}
                type(self)._MANIFEST_DIRTY = False

            logger.info(f"Cache cleared: {deleted_count} files deleted")
            return deleted_count

        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
            return 0

    def clear_by_pattern(self, pattern: str) -> int:
        """
        Clear cached figures matching a pattern.

        Più robusto del solo match sul nome file:
        - elimina file il cui nome contiene il pattern;
        - legge il manifest e intercetta i chart_id che contengono il pattern;
        - elimina tutti i file associati alle signature intercettate.
        """
        try:
            deleted_count = 0
            pattern_lower = str(pattern or "").lower().strip()
            if not pattern_lower:
                return 0

            targets = set()

            if self.CACHE_DIR.exists():
                for file_path in self._iter_cache_files():
                    if pattern_lower in file_path.name.lower():
                        targets.add(file_path)

            try:
                with self._MANIFEST_LOCK:
                    manifest = self._load_manifest(repair_on_corruption=True)
                    manifest_keys_to_delete = []

                for key, entry in list(manifest.items()):
                    chart_id = str(entry.get("chart_id") or "")
                    fig_sig = str(entry.get("signature") or "")
                    if chart_id and fig_sig and pattern_lower in chart_id.lower():
                        manifest_keys_to_delete.append(key)
                        stem = self._cache_file_stem(chart_id, fig_sig)
                        for suffix in (".json.gz", ".json.json.gz", ".pickle.gz", ".json.pickle.gz", ".pickle"):
                            candidate = self.CACHE_DIR / f"{stem}{suffix}"
                            if candidate.exists():
                                targets.add(candidate)
                    elif pattern_lower in str(key).lower():
                        manifest_keys_to_delete.append(key)
                if manifest_keys_to_delete:
                    with self._MANIFEST_LOCK:
                        manifest = self._load_manifest(repair_on_corruption=True)
                        for key in manifest_keys_to_delete:
                            manifest.pop(key, None)
                        type(self)._MANIFEST_DIRTY = True
                    self.flush_manifest()
            except Exception as exc:
                logger.warning("Manifest non usato per clear_by_pattern(%s): %s", pattern, exc)

            for file_path in sorted(targets):
                try:
                    file_path.unlink()
                    deleted_count += 1
                except Exception as e:
                    logger.warning(f"Failed to delete {file_path}: {e}")

            logger.info(f"Cache cleared by pattern '{pattern}': {deleted_count} files deleted")
            return deleted_count

        except Exception as e:
            logger.error(f"Error clearing cache by pattern: {e}")
            return 0

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            dict with keys:
            - num_files: Number of cached figures
            - total_size_bytes: Total size in bytes
            - total_size_mb: Total size in MB
            - charts: List of unique chart IDs
            - chart_counts: Dict of chart_id -> count
            - oldest_timestamp: Oldest cache entry timestamp
            - newest_timestamp: Newest cache entry timestamp
            - cache_age_hours: Hours since newest cache entry
        """
        try:
            stats = {
                "num_files": 0,
                "total_size_bytes": 0,
                "total_size_mb": 0.0,
                "charts": [],
                "chart_counts": {},
                "oldest_timestamp": None,
                "newest_timestamp": None,
                "cache_age_hours": 0
            }

            # Return empty stats if cache doesn't exist
            if not self.CACHE_DIR.exists():
                return stats

            if self.MANIFEST_FILE.exists():
                try:
                    with self._MANIFEST_LOCK:
                        manifest = self._load_manifest(repair_on_corruption=True)

                    if manifest:
                        timestamps = []
                        for entry in manifest.values():
                            if not isinstance(entry, dict):
                                continue
                            file_size = int(entry.get("file_size", 0) or 0)
                            chart_id = entry.get("chart_id")
                            timestamp = entry.get("timestamp")

                            stats["num_files"] += 1
                            stats["total_size_bytes"] += file_size
                            if chart_id:
                                if chart_id not in stats["charts"]:
                                    stats["charts"].append(chart_id)
                                stats["chart_counts"][chart_id] = stats["chart_counts"].get(chart_id, 0) + 1
                            if timestamp:
                                timestamps.append(timestamp)

                        stats["json_files"] = stats["num_files"]
                        stats["pickle_files"] = 0
                        stats["legacy_double_json_files"] = 0
                        stats["total_size_mb"] = round(stats["total_size_bytes"] / (1024 * 1024), 2)
                        stats["scan_mode"] = "manifest"

                        if timestamps:
                            timestamps.sort()
                            stats["oldest_timestamp"] = timestamps[0]
                            stats["newest_timestamp"] = timestamps[-1]
                            try:
                                newest_dt = datetime.fromisoformat(timestamps[-1])
                                cache_age_seconds = (datetime.now() - newest_dt).total_seconds()
                                stats["cache_age_hours"] = max(0, int(cache_age_seconds / 3600))
                            except Exception as e:
                                logger.warning(f"Error calculating cache age: {e}")
                                stats["cache_age_hours"] = 0
                        logger.debug(f"Cache stats da manifest: {stats}")
                        return stats
                except Exception as e:
                    logger.warning(f"Error reading manifest stats: {e}")

            # Count files and calculate size for all supported formats
            timestamps = []
            json_files = 0
            pickle_files = 0
            legacy_double_json_files = 0

            for file_path in self._iter_cache_files():
                try:
                    file_size = file_path.stat().st_size
                    stats["num_files"] += 1
                    stats["total_size_bytes"] += file_size
                    if file_path.name.endswith(".json.json.gz"):
                        legacy_double_json_files += 1
                    elif file_path.name.endswith(".json.gz"):
                        json_files += 1
                    elif ".pickle" in file_path.name:
                        pickle_files += 1
                except Exception as e:
                    logger.warning(f"Error getting file stats for {file_path}: {e}")

            stats["json_files"] = json_files
            stats["pickle_files"] = pickle_files
            stats["legacy_double_json_files"] = legacy_double_json_files
            stats["scan_mode"] = "disk_scan"

            # Convert to MB
            stats["total_size_mb"] = round(stats["total_size_bytes"] / (1024 * 1024), 2)

            # Load manifest for chart info
            if self.MANIFEST_FILE.exists():
                try:
                    with self._MANIFEST_LOCK:
                        manifest = self._load_manifest(repair_on_corruption=True)

                    for key, entry in manifest.items():
                        chart_id = entry.get("chart_id")
                        timestamp = entry.get("timestamp")

                        if chart_id:
                            if chart_id not in stats["charts"]:
                                stats["charts"].append(chart_id)
                            stats["chart_counts"][chart_id] = stats["chart_counts"].get(chart_id, 0) + 1

                        if timestamp:
                            timestamps.append(timestamp)

                    if timestamps:
                        timestamps.sort()
                        stats["oldest_timestamp"] = timestamps[0]
                        stats["newest_timestamp"] = timestamps[-1]

                        # Calculate cache age in hours from newest entry
                        try:
                            newest_dt = datetime.fromisoformat(timestamps[-1])
                            cache_age_seconds = (datetime.now() - newest_dt).total_seconds()
                            stats["cache_age_hours"] = max(0, int(cache_age_seconds / 3600))
                        except Exception as e:
                            logger.warning(f"Error calculating cache age: {e}")
                            stats["cache_age_hours"] = 0
                except Exception as e:
                    logger.warning(f"Error reading manifest: {e}")

            logger.debug(f"Cache stats: {stats}")
            return stats

        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return {
                "num_files": 0,
                "total_size_bytes": 0,
                "total_size_mb": 0.0,
                "charts": [],
                "chart_counts": {},
                "oldest_timestamp": None,
                "newest_timestamp": None,
                "cache_age_hours": 0
            }

    def _record_cache_event(self, chart_id: str, event_type: str, signature: str) -> None:
        """
        Record cache event via render_profiler.

        Args:
            chart_id: Chart identifier
            event_type: Type of event ('session_hit', 'disk_hit', 'miss')
            signature: Figure signature
        """
        try:
            from core.render_profiler import record_render_event

            # Map event_type to detail string
            detail_map = {
                "session_hit": "cache_hit_session",
                "disk_hit": "cache_hit_disk",
                "miss": "cache_miss"
            }
            detail = detail_map.get(event_type, event_type)

            record_render_event(
                page="cache",
                step=f"fig_{chart_id}",
                elapsed=0.0,
                status="CACHE",
                detail=detail,
            )

        except Exception as e:
            logger.debug(f"Failed to record cache event: {e}")
            # Don't fail on logging error


# Singleton instance
_figure_cache_instance: Optional[FigureCache] = None
_figure_cache_instance_lock = threading.Lock()


def get_figure_cache() -> FigureCache:
    """
    Get the global FigureCache singleton instance.

    Returns:
        FigureCache: The global cache instance
    """
    global _figure_cache_instance
    if _figure_cache_instance is None:
        with _figure_cache_instance_lock:
            if _figure_cache_instance is None:
                _figure_cache_instance = FigureCache()
    return _figure_cache_instance


def flush_figure_cache_manifest() -> bool:
    """Scrive su disco il manifest della figure cache, se ci sono modifiche in sospeso.

    Da chiamare una volta a fine rendering pagina (non ad ogni figura), per
    evitare N riscritture del manifest in un run con molti cache miss.
    """
    try:
        return get_figure_cache().flush_manifest()
    except Exception:
        logger.exception("Errore durante il flush del manifest figure cache")
        return False
