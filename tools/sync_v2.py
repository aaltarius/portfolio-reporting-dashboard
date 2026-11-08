"""Sincronizzazione v2 Desktop -> Worker di PROVA (bootstrap / update), con tutti i controlli del client.

Misura senza inviare:  python -m tools.sync_v2 --dry-run
Invio:                 python -m tools.sync_v2 --ambiente prova --data data/portfolio/portafoglio_data.json
Operazione (straordinario): aggiungere  --kind operation --reason buy
Dopo reset del Worker o stato non riconosciuto: --allow-rebootstrap (esplicito).

Parametri, chiavi e nomi: data/segreti/cloudflare.json (modello docs/sync/cloudflare.esempio.json). La produzione è
bloccata nel codice. Lo stato locale (epoca, sequenza, invio in sospeso) è in data/cache/sync_v2/."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ON = {"mobile_sync": {"enabled": True}}  # accensione solo per questa chiamata esplicita da riga di comando
OK = {"bootstrapped", "updated", "in_sync", "adopted", "waiting", "would_bootstrap", "would_update"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ambiente", default="prova")
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--data", type=Path, default=None)
    ap.add_argument("--kind", choices=["prices", "operation"], default="prices")
    ap.add_argument("--reason", choices=["buy", "sell", "income", "redemption", "cash", "other"], default=None)
    ap.add_argument("--allow-rebootstrap", action="store_true")
    ap.add_argument("--gzip", action="store_true", help="comprime i corpi (solo se il Worker lo accetta)")
    ap.add_argument("--dry-run", action="store_true", help="costruisce e misura in locale, senza rete e senza scrivere stato")
    args = ap.parse_args(argv)

    import persistence.storage as st
    from persistence.parquet_utils import load_storico_prezzi_hybrid
    from core.sync import v2
    from core.sync.snapshot import build_snapshot
    from core.sync.v2_client import V2Client, v2_encode
    from core.sync.v2_state import SyncStore

    if not args.dry_run and args.data is None:
        print("Con l'invio il file dei dati va indicato sempre (--data).", file=sys.stderr)
        return 2
    path = args.data or Path(st.DATA_FILE)
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8-sig"))
    try:
        hist = load_storico_prezzi_hybrid(st.STORICO_PREZZI_FILE) if path == Path(st.DATA_FILE) else None
    except Exception:  # noqa: BLE001
        hist = None
    try:
        snap = build_snapshot(data, source_bytes=raw)
        ds = v2.build_dataset(data, snap, hist)
    except ValueError as exc:
        print(f"Dataset non costruibile: {exc}", file=sys.stderr)
        return 2
    store = SyncStore(Path(st.DATA_DIR) / "cache" / "sync_v2")
    if args.dry_run:
        parts = v2.build_bootstrap_parts(ds, epoch_id="00000000-0000-4000-8000-000000000000", bootstrap_id="0" * 32,
                                         generated_at="1970-01-01T00:00:00Z")
        print(f"Bootstrap: {len(parts)} parti, {sum(len(v2_encode(p)) for p in parts)} byte (Base64 compreso)")
        conf, prev = store.load()["confirmed"], store.dataset()
        if conf and prev:
            msg = v2.build_update(prev, ds, epoch_id=conf["epochId"], seq=conf["seq"] + 1, kind=args.kind, reason=args.reason,
                                  generated_at="1970-01-01T00:00:00Z")
            print(f"Update rispetto all'ultimo invio confermato: {len(v2_encode(msg))} byte")
        print(f"datasetRevision: {v2.dataset_revision(ds)}\nNessuna rete usata, nulla scritto.")
        return 0

    from core.sync import cloudflare_config as cc
    from core.sync.transport import HttpTransport
    try:
        cfg_path = args.config or cc.default_path()
        cfg = cc.load_config(cfg_path)
        env = cc.get_environment(cfg, args.ambiente, config_path=cfg_path)
        opts = cc.sending_options(cfg)
        transport = HttpTransport(env.url, env.token, allowed_hosts={env.host}, timeout=env.timeout_s,
                                  user_agent=env.user_agent, gzip_body=args.gzip)
    except ValueError as exc:
        print(f"Configurazione non valida: {exc}", file=sys.stderr)
        return 2
    client = V2Client(transport, store, paths={k: env.endpoints[k] for k in ("v2_state", "v2_bootstrap", "v2_update")})
    res = client.sync(ds, settings=ON, kind=args.kind, reason=args.reason, min_interval_s=opts["min_interval_s"],
                      allow_rebootstrap=args.allow_rebootstrap)
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res["status"] in OK else 2


if __name__ == "__main__":
    raise SystemExit(main())
