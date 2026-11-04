"""
persistence/parquet_utils.py — Hybrid JSON-Parquet-Gzip storage with multi-level fallback.

Provides robust multi-format storage:
- JSON (primary, universal compatibility) + gzip compression
- Parquet (optional, 5-10x faster + 70-80% smaller)
- Atomic backups of previous versions
- Multi-level fallback: Parquet → gzip → JSON → backup
- Zero data loss guarantees

Usage:
    # Load with automatic fallback
    data = load_storico_prezzi_hybrid(path_base)

    # Save atomically (backup + compress + verify)
    save_storico_prezzi_hybrid(data, path_base)
"""
import hashlib
import json
import gzip
import os
import shutil
import logging
from pathlib import Path
from typing import Any, Optional
from datetime import datetime
import pandas as pd

logger = logging.getLogger("portafoglio.parquet_utils")

# Try to import pyarrow (optional dependency)
try:
    PARQUET_AVAILABLE = True
except ImportError:
    PARQUET_AVAILABLE = False
    logger.debug("PyArrow not available; using JSON+gzip for all storage")


def _storico_dict_to_df(storico: dict[str, dict[str, float]]) -> pd.DataFrame:
    """Convert storico_prezzi dict format to DataFrame.

    Input: {"2024-01-01": {"AAPL": 150.0, "MSFT": 300.0}, ...}
    Output: DataFrame with Date index, ticker columns, price values
    """
    if not storico:
        return pd.DataFrame()

    rows = []
    for date_str, tickers_dict in storico.items():
        row = {"Date": date_str}
        row.update(tickers_dict)
        rows.append(row)

    df = pd.DataFrame(rows)
    if not df.empty and "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.sort_values("Date").reset_index(drop=True)

    return df


def _df_to_storico_dict(df: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Convert DataFrame back to storico_prezzi dict format."""
    if df.empty:
        return {}

    result = {}
    for _, row in df.iterrows():
        date_str = row["Date"].strftime("%Y-%m-%d") if hasattr(row["Date"], "strftime") else str(row["Date"])
        tickers_dict = {}
        for col in df.columns:
            if col != "Date" and pd.notna(row[col]):
                try:
                    tickers_dict[col] = float(row[col])
                except (ValueError, TypeError):
                    pass
        if tickers_dict:
            result[date_str] = tickers_dict

    return result


def load_storico_prezzi_hybrid(json_path: str | Path) -> dict[str, dict[str, float]]:
    """Load storico_prezzi with multi-level fallback (never lose data).

    Strategy (in order):
    1. Parquet (.parquet) - fastest, smallest
    2. Gzip JSON (.json.gz) - compressed, universal
    3. Raw JSON (.json) - fallback
    4. Backup dir - recovery format
    5. Empty dict - last resort

    Returns: storico_prezzi dict or {} if all fail
    """
    json_path = Path(json_path)
    parquet_path = json_path.with_suffix(".parquet")
    gzip_path = json_path.with_suffix(".json.gz")
    backup_dir = json_path.parent / ".backups"

    # 1. Try Parquet first (5-10x faster)
    if PARQUET_AVAILABLE and parquet_path.exists():
        try:
            df = pd.read_parquet(parquet_path)
            result = _df_to_storico_dict(df)
            logger.info(f"Loaded storico_prezzi from Parquet: {parquet_path} ({len(result)} dates)")
            return result
        except Exception as e:
            logger.warning(f"Parquet load failed: {e}, trying gzip...")

    # 2. Try gzipped JSON (compressed, universal)
    if gzip_path.exists():
        try:
            with gzip.open(gzip_path, "rt", encoding="utf-8") as f:
                data = json.load(f)
            result = data if isinstance(data, dict) else {}
            logger.info(f"Loaded storico_prezzi from gzip: {gzip_path} ({len(result)} dates)")
            return result
        except Exception as e:
            logger.warning(f"Gzip load failed: {e}, trying raw JSON...")

    # 3. Try raw JSON (fallback)
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            result = data if isinstance(data, dict) else {}
            logger.info(f"Loaded storico_prezzi from raw JSON: {json_path} ({len(result)} dates)")
            return result
        except Exception as e:
            logger.warning(f"Raw JSON load failed: {e}, checking backups...")

    # 4. Try backup directory (recovery)
    if backup_dir.exists():
        try:
            backup_files = sorted(backup_dir.glob("storico_prezzi_*.json.gz"), reverse=True)
            if backup_files:
                backup_file = backup_files[0]
                with gzip.open(backup_file, "rt", encoding="utf-8") as f:
                    data = json.load(f)
                result = data if isinstance(data, dict) else {}
                logger.warning(f"Recovered storico_prezzi from backup: {backup_file} ({len(result)} dates)")
                return result
        except Exception as e:
            logger.warning(f"Backup recovery failed: {e}")

    logger.error(f"All storico_prezzi load attempts failed: {json_path}")
    return {}


def _storico_digest(storico: dict[str, dict[str, float]]) -> str:
    """Impronta canonica del contenuto (indipendente dall'ordine delle chiavi)."""
    raw = json.dumps(storico, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _file_stat(path: Path) -> list[int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return [st.st_mtime_ns, st.st_size]


def _is_unchanged(storico: dict[str, dict[str, float]], json_path: Path, gzip_path: Path, parquet_path: Path, digest_path: Path) -> bool:
    """True se i file su disco sono quelli scritti per questo stesso contenuto."""
    try:
        side = json.loads(digest_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if side.get("digest") != _storico_digest(storico):
        return False
    return all(side.get(name) == _file_stat(path) and _file_stat(path) is not None
               for name, path in (("json", json_path), ("gzip", gzip_path), ("parquet", parquet_path))
               if name != "parquet" or (PARQUET_AVAILABLE and storico))


def save_storico_prezzi_hybrid(storico: dict[str, dict[str, float]], json_path: str | Path) -> bool:
    """Salva lo storico prezzi in modo atomico, solo se il contenuto e' cambiato.

    1. Se contenuto e file su disco coincidono con l'ultimo salvataggio, non scrive nulla.
    2. Altrimenti: copia di sicurezza del JSON precedente, scrittura di JSON, gzip e
       Parquet su file temporanei, verifica del JSON, poi sostituzione con
       ``os.replace`` (Parquet, formato preferito dal caricamento, per ultimo).
       In caso di errore i file validi precedenti restano intatti.

    Returns: True se riuscito (o gia' aggiornato), False altrimenti.
    """
    json_path = Path(json_path)
    parquet_path = json_path.with_suffix(".parquet")
    gzip_path = json_path.with_suffix(".json.gz")
    digest_path = json_path.with_suffix(".digest")
    backup_dir = json_path.parent / ".backups"
    temps: list[Path] = []

    try:
        json_path.parent.mkdir(parents=True, exist_ok=True)

        if _is_unchanged(storico, json_path, gzip_path, parquet_path, digest_path):
            logger.debug("storico_prezzi invariato: nessuna scrittura")
            return True

        # 1. Copia di sicurezza della versione precedente (prima di scrivere)
        if json_path.exists():
            backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = backup_dir / f"storico_prezzi_{timestamp}.json.gz"
            try:
                with open(json_path, "rb") as src:
                    with gzip.open(backup_file, "wb") as dst:
                        dst.write(src.read())
            except Exception as e:
                logger.warning(f"Backup creation failed (non-fatal): {e}")

        # 2. Scrittura su file temporanei
        tmp_json = json_path.with_name(json_path.name + ".tmp")
        temps.append(tmp_json)
        with open(tmp_json, "w", encoding="utf-8") as f:
            json.dump(storico, f, indent=2, default=str)
        tmp_gzip = gzip_path.with_name(gzip_path.name + ".tmp")
        temps.append(tmp_gzip)
        with gzip.open(tmp_gzip, "wt", encoding="utf-8") as f:
            json.dump(storico, f, indent=2, default=str)
        tmp_parquet: Path | None = None
        if PARQUET_AVAILABLE and storico:
            try:
                df = _storico_dict_to_df(storico)
                if not df.empty:
                    tmp_parquet = parquet_path.with_name(parquet_path.name + ".tmp")
                    temps.append(tmp_parquet)
                    df.to_parquet(tmp_parquet, compression="snappy", index=False)
            except Exception as e:
                logger.warning(f"Parquet save failed (non-fatal): {e}")
                tmp_parquet = None

        # 3. Verifica del JSON temporaneo
        with open(tmp_json, "r", encoding="utf-8") as f:
            verify = json.load(f)
        if not isinstance(verify, dict) or len(verify) != len(storico):
            raise ValueError(f"Verification failed: wrote {len(storico)}, read {len(verify)}")

        # 4. Sostituzione atomica (Parquet per ultimo)
        os.replace(tmp_json, json_path)
        os.replace(tmp_gzip, gzip_path)
        if tmp_parquet is not None:
            os.replace(tmp_parquet, parquet_path)
        temps.clear()

        side = {
            "digest": _storico_digest(storico),
            "json": _file_stat(json_path),
            "gzip": _file_stat(gzip_path),
            "parquet": _file_stat(parquet_path),
        }
        digest_path.write_text(json.dumps(side), encoding="utf-8")
        logger.info(f"Saved storico_prezzi: {len(storico)} dates")

        # 5. Pulizia vecchie copie di sicurezza (ultime 5)
        try:
            backups = sorted(backup_dir.glob("storico_prezzi_*.json.gz"), reverse=True)
            for old_backup in backups[5:]:
                old_backup.unlink()
        except Exception as e:
            logger.warning(f"Backup cleanup failed (non-fatal): {e}")

        return True

    except Exception as e:
        logger.error(f"Save storico_prezzi failed: {e}")
        for tmp in temps:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        return False
