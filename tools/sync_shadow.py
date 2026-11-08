"""Modalità ombra della sincronizzazione: calcola la fotografia per il Mobile e ne stampa un riepilogo.

Uso:  python -m tools.sync_shadow [--data percorso.json] [--json]

Solo lettura: non scrive file, non apre connessioni, non modifica i dati. Serve a controllare che la
fotografia che il Desktop invierebbe coincida con quella dell'esportatore attuale del Mobile."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.sync.snapshot import build_snapshot


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=None, help="file del portafoglio (predefinito: quello dell'app)")
    ap.add_argument("--json", action="store_true", help="stampa la fotografia completa")
    args = ap.parse_args(argv)
    if args.data is None:
        from persistence.storage import DATA_FILE
        args.data = Path(DATA_FILE)
    raw = args.data.read_bytes()
    try:
        snap = build_snapshot(json.loads(raw.decode("utf-8-sig")), source_bytes=raw)
    except ValueError as exc:
        print(f"Fotografia non costruibile: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(snap, ensure_ascii=False, indent=2))
        return 0
    total = snap["cash"] + sum(p["value"] for p in snap["positions"])
    print(f"Fotografia {snap['schema']} (solo calcolo, nulla inviato)")
    print(f"  posizioni: {len(snap['positions'])} | eventi: {snap['sourceEventCount']} | ultimo evento: {snap['sourceLastEventDate']}")
    print(f"  liquidità: {snap['cash']:.2f} | patrimonio: {total:.2f}")
    print(f"  revisione: {snap['revision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
