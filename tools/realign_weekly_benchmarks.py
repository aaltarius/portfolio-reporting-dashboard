"""Riallinea le barre settimanali dei benchmark salvate con la data del lunedì (BM-16).

Dry-run: python -m tools.realign_weekly_benchmarks
Apply:   python -m tools.realign_weekly_benchmarks --apply [--reference <backup.sqlite3>]

Contesto. Yahoo etichetta la barra settimanale con il lunedì ma il prezzo è la chiusura del venerdì:
il benchmark risultava sfalsato di quattro giorni rispetto allo strumento e la correlazione crollava.
In più le barre «discovery» erano state scritte con `replace_existing` anche sulle serie che avevano già
prezzi giornalieri: i lunedì di quelle serie contengono la chiusura del venerdì precedente.

Interventi (solo righe con source='discovery' e giorno della settimana lunedì):
  1. serie composte soltanto da quelle righe -> la data passa al venerdì della stessa settimana;
  2. serie che hanno anche altre sorgenti -> il valore del lunedì è ripristinato dal database di
     riferimento (backup precedente alla sovrascrittura) se lì la data esiste con un'altra sorgente,
     altrimenti la riga è eliminata (un buco di un giorno è assorbito dall'allineamento).
Le serie BLEND sono già datate al venerdì e non vengono toccate. Lo strumento è idempotente e sicuro
anche dopo il passaggio alle barre giornaliere: interviene soltanto sulle serie le cui righe 'discovery'
sono tutte di lunedì; una serie con righe 'discovery' in altri giorni (già giornaliera o già riallineata)
viene saltata, perché i suoi lunedì sono prezzi veri.
Prima di scrivere crea una copia coerente del database (anche con WAL) nella cartella di backup.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from core.verified_benchmarks.store import db_path

_SRC = "discovery"


def _is_monday(day: str) -> bool:
    try:
        return date.fromisoformat(day[:10]).weekday() == 0
    except ValueError:
        return False


def _latest_reference(db: Path) -> Path | None:
    folder = db.parent / "backup_reset_benchmark"
    files = sorted(folder.glob("*.sqlite3")) if folder.is_dir() else []
    return files[-1] if files else None


def plan(rd: sqlite3.Connection, reference: Path | None) -> dict:
    """Calcola cosa cambierebbe, senza scrivere."""
    rows = rd.execute("SELECT series_id,date,level,source FROM index_prices").fetchall()
    by: dict[str, list[tuple[str, float, str]]] = {}
    for sid, day, level, src in rows:
        by.setdefault(sid, []).append((day, level, src))
    ref: dict[str, dict[str, tuple[float, str]]] = {}
    if reference is not None:
        with sqlite3.connect(f"file:{reference.as_posix()}?mode=ro", uri=True) as rf:
            for sid, day, level, src in rf.execute("SELECT series_id,date,level,source FROM index_prices"):
                ref.setdefault(sid, {})[day] = (level, src)
    shift, restore, delete = [], [], []
    for sid, items in by.items():
        discovery = [d for d, _lv, s in items if s == _SRC]
        # Una serie con righe 'discovery' anche in giorni diversi dal lunedi e' gia' giornaliera (scaricata dopo il
        # passaggio alle barre giornaliere) o gia' riallineata (venerdi, BLEND): i suoi lunedi sono prezzi veri e
        # non vanno toccati. Si interviene solo sulle serie le cui righe 'discovery' sono TUTTE di lunedi.
        if not discovery or any(not _is_monday(d) for d in discovery):
            continue
        mon = [(d, lv, s) for d, lv, s in items if s == _SRC and _is_monday(d)]
        if not mon:
            continue
        only_weekly = all(s == _SRC and _is_monday(d) for d, _, s in items)
        if only_weekly:
            shift += [(sid, d) for d, _, _ in mon]
            continue
        known = ref.get(sid, {})
        for d, _lv, _s in mon:
            old = known.get(d)
            if old is not None and old[1] != _SRC:
                restore.append((sid, d, old[0], old[1]))
            else:
                delete.append((sid, d))
    return {"shift": shift, "restore": restore, "delete": delete}


def apply_plan(db: Path, changes: dict, *, backup_dir: Path | None = None) -> Path:
    backup_root = backup_dir or (db.parent / "backup_realign_benchmark")
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = backup_root / ("benchmarks_before_realign_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".sqlite3")
    with sqlite3.connect(str(db), timeout=30) as rw:
        rw.execute("PRAGMA busy_timeout=30000")
        with sqlite3.connect(str(backup)) as dest:
            rw.backup(dest)
        rw.execute("BEGIN IMMEDIATE")
        try:
            for sid, day in changes["shift"]:
                friday = (date.fromisoformat(day) + timedelta(days=4)).isoformat()
                rw.execute("UPDATE index_prices SET date=? WHERE series_id=? AND date=? AND source=?",
                           (friday, sid, day, _SRC))
            for sid, day, level, src in changes["restore"]:
                rw.execute("UPDATE index_prices SET level=?,source=? WHERE series_id=? AND date=? AND source=?",
                           (level, src, sid, day, _SRC))
            for sid, day in changes["delete"]:
                rw.execute("DELETE FROM index_prices WHERE series_id=? AND date=? AND source=?", (sid, day, _SRC))
            rw.commit()
        except Exception:
            rw.rollback()
            raise
    return backup


def realign(db: Path, *, apply: bool = False, reference: Path | None = None, backup_dir: Path | None = None) -> dict:
    db = Path(db)
    if not db.is_file():
        raise FileNotFoundError(f"Database SQLite non trovato: {db}")
    reference = reference or _latest_reference(db)
    with sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True) as rd:
        changes = plan(rd, reference)
    result = {
        "database": str(db), "riferimento": str(reference) if reference else None,
        "serie_spostate_a_venerdi": len({s for s, _ in changes["shift"]}), "righe_spostate": len(changes["shift"]),
        "righe_ripristinate_dal_riferimento": len(changes["restore"]),
        "righe_eliminate": len(changes["delete"]), "applicato": False,
    }
    if not apply or not (changes["shift"] or changes["restore"] or changes["delete"]):
        return result
    result["backup_sqlite"] = str(apply_plan(db, changes, backup_dir=backup_dir))
    result["applicato"] = True
    return result


def main(argv=None) -> int:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--db", type=Path, default=db_path())
    a.add_argument("--reference", type=Path, default=None, help="database precedente da cui ripristinare i lunedì")
    a.add_argument("--apply", action="store_true")
    args = a.parse_args(argv)
    print(json.dumps(realign(args.db, apply=args.apply, reference=args.reference), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
