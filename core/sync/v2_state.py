"""Stato locale della sincronizzazione v2 (cartella dedicata, ignorata da git: `data/cache/sync_v2/`).

- `state.json`: epoca, sequenza, impronte dell'ultimo stato CONFERMATO dal Worker e, se c'è, l'invio in corso (`pending`);
- `dataset.json`: l'ultimo dataset confermato (serve a calcolare i delta);
- `pending_dataset.json`: il dataset dell'invio in corso (diventa quello confermato solo dopo la conferma).

Un invio si scrive qui PRIMA di essere spedito: se la risposta si perde o l'app si chiude, al prossimo avvio si capisce
(interrogando il Worker) se è stato applicato oppure no. Scritture atomiche; file illeggibile = stato assente."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def _write_atomic(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class SyncStore:
    def __init__(self, root):
        self.root = Path(root)

    @property
    def _state(self) -> Path:
        return self.root / "state.json"

    def load(self) -> dict:
        """{confirmed: {...}|None, pending: {...}|None}"""
        state = _read(self._state)
        if not isinstance(state, dict):
            return {"confirmed": None, "pending": None}
        return {"confirmed": state.get("confirmed"), "pending": state.get("pending")}

    def dataset(self):
        return _read(self.root / "dataset.json")

    def pending_dataset(self):
        return _read(self.root / "pending_dataset.json")

    def set_pending(self, pending: dict, dataset: dict) -> None:
        _write_atomic(self.root / "pending_dataset.json", dataset)
        cur = self.load()
        _write_atomic(self._state, {"confirmed": cur["confirmed"], "pending": pending})

    def confirm(self, confirmed: dict, dataset: dict) -> None:
        """Il dataset diventa quello confermato e l'invio in corso viene chiuso."""
        _write_atomic(self.root / "dataset.json", dataset)
        _write_atomic(self._state, {"confirmed": confirmed, "pending": None})
        try:
            (self.root / "pending_dataset.json").unlink()
        except OSError:
            pass

    def clear_pending(self) -> None:
        cur = self.load()
        _write_atomic(self._state, {"confirmed": cur["confirmed"], "pending": None})
