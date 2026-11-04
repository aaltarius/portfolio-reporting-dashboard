"""Azzeramento reversibile delle selezioni manuali dei benchmark in SQLite.

Dry-run: python -m tools.reset_manual_benchmarks
Apply:   python -m tools.reset_manual_benchmarks --apply

Non tocca strumenti, storico prezzi, JSON del portafoglio o assegnazioni storiche.
Conserva il benchmark strategico di portafoglio, ma disattiva i mix personalizzati.
"""
from __future__ import annotations
import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from core.verified_benchmarks.store import db_path


def reset(db:Path,*,apply:bool=False,backup_dir:Path|None=None)->dict:
    db=Path(db)
    if not db.is_file():
        raise FileNotFoundError(f'Database SQLite non trovato: {db}')
    # Non creare un database vuoto durante la verifica.
    with sqlite3.connect(f'file:{db.as_posix()}?mode=ro',uri=True) as rd:
        n=rd.execute('SELECT COUNT(*) FROM instrument_override').fetchone()[0]
        old=rd.execute("SELECT payload FROM benchmark_preferences WHERE key='portfolio_benchmark_settings'").fetchone()
    prefs=json.loads(old[0]) if old else {}
    custom=bool((prefs.get('benchmarking') or {}).get('custom_enabled'))
    result={'database':str(db),'overrides':n,'benchmark_portafoglio_personalizzato':custom,
            'applicato':False,'note':'Le vecchie scelte manuali sono ignorate dal motore V4 anche senza azzeramento.'}
    if not apply:return result
    backup_root=backup_dir or (db.parent/'backup_reset_benchmark')
    backup_root.mkdir(parents=True,exist_ok=True)
    backup=backup_root/('benchmarks_before_reset_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3')
    with sqlite3.connect(str(db),timeout=30) as rw:
        rw.execute('PRAGMA busy_timeout=30000')
        with sqlite3.connect(str(backup)) as dest:
            rw.backup(dest)  # snapshot coerente anche con SQLite WAL
        rw.execute('BEGIN IMMEDIATE')
        try:
            rw.execute('DELETE FROM instrument_override')
            rw.execute('DELETE FROM assignment_snapshot')
            if old:
                settings=prefs.get('benchmarking')
                if isinstance(settings,dict):
                    settings['custom_enabled']=False
                    settings['custom_components']=[]
                    settings['custom_name']=''
                rw.execute('UPDATE benchmark_preferences SET payload=?,updated_at=? WHERE key=?',
                           (json.dumps(prefs,ensure_ascii=False),datetime.now().isoformat(),
                            'portfolio_benchmark_settings'))
            rw.commit()
        except Exception:
            rw.rollback();raise
    result.update({'applicato':True,'backup_sqlite':str(backup)})
    return result


def main(argv=None)->int:
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--db',type=Path,default=db_path())
    a.add_argument('--apply',action='store_true')
    args=a.parse_args(argv)
    print(json.dumps(reset(args.db,apply=args.apply),ensure_ascii=False,indent=2))
    return 0

if __name__=='__main__':raise SystemExit(main())
