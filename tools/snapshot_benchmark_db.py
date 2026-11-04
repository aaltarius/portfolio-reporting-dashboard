"""Backup SQLite consistente (anche con database WAL): python -m tools.snapshot_benchmark_db SRC DEST"""
from __future__ import annotations
import argparse
from pathlib import Path
import sqlite3

def snapshot(source:Path,dest:Path)->bool:
    if not source.exists():return False
    dest.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(f'file:{source.absolute()}?mode=ro',uri=True) as con:
        with sqlite3.connect(dest) as target:con.backup(target)
    return True

def main(argv=None):
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('source',type=Path);a.add_argument('destination',type=Path)
    args=a.parse_args(argv)
    print('Backup:',args.destination if snapshot(args.source,args.destination) else 'Database sorgente inesistente: nessun backup')
    return 0
if __name__=='__main__':raise SystemExit(main())
