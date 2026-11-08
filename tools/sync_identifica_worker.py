"""Identifica quale versione del Worker Mobile è un file di codice (esportato dalla dashboard), SENZA eseguirlo.

  python -m tools.sync_identifica_worker C:\\percorso\\codice_worker_produzione.js [--riferimenti docs\\sync]

Come ottenere il file: nella dashboard Cloudflare apri il Worker > Edit code > seleziona tutto > incolla in un file di testo (FUORI dal
progetto). Lo strumento confronta l'impronta (SHA-256) con le versioni note, lette direttamente dai pacchetti .zip del Mobile (si leggono i
byte, nulla viene estratto né eseguito); se non coincide, mostra quanto somiglia a ciascuna versione e quali funzioni v2 contiene."""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path

# (nome pacchetto, nome del file nel pacchetto) > versione
KNOWN_MEMBERS = [
    ("SESTANTE_MOBILE_150_PROVA.zip", "src/worker_1454_baseline.js", "1.4.5.4 (base)"),
    ("SESTANTE_MOBILE_150_PROVA.zip", "worker.js", "1.5.0 PROVA"),
    ("SESTANTE_MOBILE_151_PROVA.zip", "worker.js", "1.5.1 PROVA"),
    ("ALLEGATI_TECNICI_SESTANTE_MOBILE_REDATTI.zip", "sorgenti/worker_1_4_5_REDATTO.js", "1.4.5 (copia redatta)"),
]
MARKERS = {"protocollo v2 (stato/bootstrap/update)": "/api/v2/state", "guardia solo-prova": "V2_TEST_ONLY",
           "endpoint prezzi": "/api/v2/observations", "scritture v1": "/api/sync"}


def _norm(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def load_known(folder: Path) -> list[tuple[str, bytes]]:
    out = []
    for zip_name, member, version in KNOWN_MEMBERS:
        path = folder / zip_name
        if not path.is_file():
            continue
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.endswith(member)]
            if names:
                out.append((version, _norm(z.read(names[0]))))
    return out


def similarity(a: bytes, b: bytes) -> float:
    la, lb = set(a.decode("utf-8", "replace").splitlines()), set(b.decode("utf-8", "replace").splitlines())
    return len(la & lb) / max(1, len(la | lb))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path)
    ap.add_argument("--riferimenti", type=Path, default=Path(__file__).resolve().parent.parent / "docs" / "sync")
    args = ap.parse_args(argv)
    if not args.file.is_file():
        print("File non trovato.", file=sys.stderr)
        return 2
    data = _norm(args.file.read_bytes())
    digest = hashlib.sha256(data).hexdigest()
    known = load_known(args.riferimenti)
    if not known:
        print("Nessun pacchetto di riferimento trovato in", args.riferimenti, file=sys.stderr)
        return 2
    n_lines = data.count(b"\n") + 1
    print(f"File: {len(data)} byte, {n_lines} righe, SHA-256 {digest[:16]}…")
    for version, ref in known:
        if hashlib.sha256(ref).hexdigest() == digest:
            print(f"\nCOINCIDE ESATTAMENTE con la versione {version}.")
            return 0
    print("\nNon coincide con nessuna versione nota. Somiglianza (righe in comune) con ciascuna:")
    for version, ref in sorted(known, key=lambda x: -similarity(data, x[1])):
        print(f"  {similarity(data, ref):6.1%}  {version}")
    text = data.decode("utf-8", "replace")
    print("\nContiene:")
    for label, marker in MARKERS.items():
        print(f"  {'sì' if marker in text else 'no':<3} {label}")
    ver = re.findall(r"(?:APP_VERSION|VERSION|version)['\"\s:=]+['\"]?(\d+\.\d+(?:\.\d+){0,2}[^'\"\s,;]*)", text)
    if ver:
        print("\nStringhe di versione trovate:", ", ".join(sorted(set(ver))[:6]))
    print("\nConserva comunque una copia di questo file: serve per tornare indietro.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
