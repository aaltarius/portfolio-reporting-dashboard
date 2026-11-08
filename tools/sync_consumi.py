"""Consumi della sincronizzazione visti dal Desktop: invii, byte e richieste stimate per giorno, dal registro dell'app.

  python -m tools.sync_consumi [--giorni 30]

Legge `data/logs/portafoglio.log*` (sola lettura). Sono i numeri DEL DESKTOP: le metriche vere del Worker e di R2 (richieste, operazioni,
spazio, fatturazione) vanno lette nella dashboard Cloudflare e confrontate con queste. Le richieste sono una stima per difetto:
ogni invio = 1 lettura dello stato + 1 POST (il bootstrap = 1 + n. parti); ogni controllo all'avvio = 1 lettura dello stato + 1 delle osservazioni."""
from __future__ import annotations

import argparse
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

DAY = r"(?P<day>\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2}"
SEND = re.compile(DAY + r" \| \w+ \| portafoglio\.sync \| Invio automatico: (?P<status>\w+) seq=(?P<seq>\S+) byte=(?P<bytes>\d+) parti=(?P<parts>\d+)")
CHECK = re.compile(DAY + r" \| \w+ \| portafoglio\.sync \| Controllo Mobile all'avvio: (?P<state>\w+) - ")
FREE_WORKER_REQUESTS_PER_DAY = 100_000     # piano gratuito dei Worker (da riverificare sul proprio account)


def summarize(lines, since: str) -> dict:
    days = defaultdict(lambda: {"updates": 0, "bootstraps": 0, "bytes": 0, "checks": 0, "requests": 0, "errors": 0})
    for line in lines:
        m = SEND.search(line)
        if m and m["day"] >= since:
            d = days[m["day"]]
            if m["status"] == "updated":
                d["updates"] += 1
                d["requests"] += 2
            elif m["status"] == "bootstrapped":
                d["bootstraps"] += 1
                d["requests"] += 1 + int(m["parts"])
            else:
                d["errors"] += 1
                d["requests"] += 1
            d["bytes"] += int(m["bytes"])
            continue
        m = CHECK.search(line)
        if m and m["day"] >= since:
            days[m["day"]]["checks"] += 1
            days[m["day"]]["requests"] += 2
    return dict(sorted(days.items()))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--giorni", type=int, default=30)
    ap.add_argument("--log", type=Path, default=None)
    args = ap.parse_args(argv)
    if args.log is None:
        import persistence.storage as st
        args.log = Path(st.DATA_DIR) / "logs" / "portafoglio.log"
    lines = []
    for p in sorted(args.log.parent.glob(args.log.name + "*")):
        try:
            lines += p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
    since = (datetime.now() - timedelta(days=args.giorni)).strftime("%Y-%m-%d")
    days = summarize(lines, since)
    if not days:
        print("Nessun invio o controllo trovato nel registro (la riga con i byte compare dagli invii effettuati dopo questo aggiornamento).")
        return 0
    print(f"{'giorno':<11}{'invii':>6}{'iniziali':>9}{'controlli':>10}{'byte inviati':>14}{'richieste (stima)':>19}")
    for day, d in days.items():
        print(f"{day:<11}{d['updates']:>6}{d['bootstraps']:>9}{d['checks']:>10}{d['bytes']:>14}{d['requests']:>19}")
    peak = max(d["requests"] for d in days.values())
    print(f"\nPicco giornaliero stimato: {peak} richieste ({peak / FREE_WORKER_REQUESTS_PER_DAY:.2%} del limite giornaliero del piano gratuito).")
    print("Confrontare con la dashboard Cloudflare (Workers > Metrics; R2 > Metrics) per le misure reali.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
