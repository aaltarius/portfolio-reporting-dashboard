"""Ricalcola il benchmark degli strumenti attivi cercandolo sul web (comando esplicito, mai dal render).

Uso (dalla radice del progetto):
    python tools/run_benchmark_discovery.py                 # tutti gli strumenti attivi
    python tools/run_benchmark_discovery.py --ticker XYZ.MI # un solo strumento
    python tools/run_benchmark_discovery.py --prices-only   # aggiorna solo i prezzi dei benchmark gia' scelti

Verso la rete escono solo testo descrittivo e simboli (ADR-0020). Il programma non contiene nomi di strumenti.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.benchmark_discovery.service import refresh_series, rediscover  # noqa: E402
from persistence.storage import load_data  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ticker", help="un solo strumento")
    parser.add_argument("--prices-only", action="store_true", help="aggiorna solo i prezzi delle serie gia' scelte")
    args = parser.parse_args()
    data = load_data()
    if args.prices_only:
        result = refresh_series(data, target_instrument=args.ticker)
        print(f"Prezzi aggiornati: {result['updated']} · non riusciti: {result['failed']}")
        return 0 if not result["failed"] else 1

    def progress(ticker: str, i: int, n: int) -> None:
        print(f"[{i}/{n}] {ticker}", flush=True)

    result = rediscover(data, target_instrument=args.ticker, progress=progress)
    for item in result["items"]:
        print(f"{item['ticker']:<14} {item['status']:<10} {item['grade']:<10} {item['benchmark']:<14} {item['detail'][:50]}")
    print(f"\nScelti: {result['resolved']}/{result['requested']}"
          + (f" · in attesa: {', '.join(result['pending'])}" if result["pending"] else ""))
    return 0 if not result["pending"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
