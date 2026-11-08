"""Interruttore dell'invio automatico verso il Mobile (Worker di PROVA).

  python -m tools.sync_v2_switch status      mostra lo stato (non modifica nulla)
  python -m tools.sync_v2_switch on          accende: ogni salvataggio dei dati porta, entro pochi secondi, un invio al Worker di prova
  python -m tools.sync_v2_switch off         spegne

Modifica una sola voce, `mobile_sync`, nel file delle impostazioni (data/config/portafoglio_settings.json); il resto non
viene toccato. Serve riavviare l'app perché l'effetto si veda subito. La produzione resta bloccata nel codice."""
from __future__ import annotations

import sys


def main(argv=None) -> int:
    import persistence.storage as st
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "status"
    if cmd not in ("on", "off", "status"):
        print(__doc__)
        return 2
    disk = st._read_json_file(st.SETTINGS_FILE, {})
    disk = dict(disk) if isinstance(disk, dict) else {}
    cur = disk.get("mobile_sync") if isinstance(disk.get("mobile_sync"), dict) else {}
    if cmd == "status":
        print(f"Invio automatico: {'ACCESO' if cur.get('enabled') else 'spento'} (ambiente: {cur.get('ambiente', 'prova')})")
        return 0
    disk["mobile_sync"] = {**cur, "enabled": cmd == "on", "ambiente": cur.get("ambiente") or "prova"}
    st._write_json_file(st.SETTINGS_FILE, disk)
    print(f"Invio automatico: {'ACCESO' if cmd == 'on' else 'spento'} (ambiente: {disk['mobile_sync']['ambiente']}). Riavviare l'app.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
