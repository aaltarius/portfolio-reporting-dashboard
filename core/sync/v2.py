"""Sincronizzazione v2: insieme dei dati (dataset), impronte, `update` incrementali e `bootstrap` a parti.

Solo costruzione in memoria: nessuna rete, nessuna scrittura. Gli schemi formali sono in
docs/sync/schemi/sync_v2.schema.json; l'hash è il JSON canonico v2 (`core.sync.canonical`).

Definizioni (specifica 05 v2):
- `snapshotRevision`: hash canonico v2 della fotografia SENZA il campo `revision` (il campo `revision` v1,
  calcolato in Python con le sue regole, resta dentro la fotografia solo per compatibilità e non è confrontabile in JS);
- `datasetRevision`: hash canonico dell'intero stato pubblicato, con gli array in ordine canonico;
- `messageHash`: hash canonico del messaggio senza `messageHash` e `generatedAt`."""
from __future__ import annotations

import base64
import copy
import hashlib
import json

from core.sync.canonical import canonical_dumps, canonical_sha256

UPDATE_SCHEMA = "sestante.sync.update.v1"
BOOTSTRAP_SCHEMA = "sestante.sync.bootstrap.v1"
MAX_PART_BYTES = 120_000      # byte grezzi per frammento (Base64 ~160.000 caratteri < 200.000)
MAX_PARTS = 20
MAX_TOTAL_BYTES = 2 * 1024 * 1024


def snapshot_revision(snapshot: dict) -> str:
    return canonical_sha256({k: v for k, v in snapshot.items() if k != "revision"})


def build_dataset(data: dict, snapshot: dict, price_history: dict | None = None) -> dict:
    """Stato completo da pubblicare, con i motori e gli esportatori del Desktop. Solleva ValueError se un canale
    obbligatorio non è costruibile (nessun dato inventato)."""
    from core.sync import exports  # solo il Desktop costruisce il dataset: il riferimento del Worker non lo richiede
    hist, _ = exports.build_history(data, snapshot)
    brief, _ = exports.build_market_brief(data, snapshot, price_history)
    feats, _ = exports.build_features(data, snapshot)
    try:
        btp, _ = exports.build_btp_history(data, snapshot, price_history)
        btp_series = btp["series"]
    except ValueError as exc:
        if "Nessun BTP" not in str(exc):
            raise
        btp_series = {}
    return normalize({
        "snapshot": copy.deepcopy(snapshot), "history": {"points": hist["points"]}, "sessions": brief["sessions"],
        "catalog": feats["catalog"], "accumuli": feats["accumuli"], "futureGov": feats["futureGov"],
        "closedSummary": feats["closedSummary"], "calendarAsOf": feats["calendarAsOf"], "btpSeries": btp_series})


def normalize(ds: dict) -> dict:
    """Ordine canonico degli array (le chiavi degli oggetti le ordina l'hash)."""
    out = copy.deepcopy(ds)
    out["history"]["points"] = sorted(out["history"]["points"], key=lambda r: r["date"])
    out["sessions"] = sorted(out["sessions"], key=lambda r: r["date"])
    out["catalog"] = sorted(out["catalog"], key=lambda r: r["ticker"])
    out["accumuli"] = sorted(out["accumuli"], key=lambda r: r["ticker"])
    out["futureGov"] = sorted(out["futureGov"], key=lambda r: (r["date"], r["ticker"], r["event"]))
    out["btpSeries"] = {t: sorted(pts, key=lambda r: r["date"]) for t, pts in sorted(out["btpSeries"].items())}
    out["snapshot"]["positions"] = sorted(out["snapshot"]["positions"], key=lambda r: r["ticker"])
    return out


def dataset_revision(ds: dict) -> str:
    return canonical_sha256(normalize(ds))


def message_hash(message: dict) -> str:
    return canonical_sha256({k: v for k, v in message.items() if k not in ("messageHash", "generatedAt")})


def _by_key(rows, key):
    return {r[key]: r for r in rows}


def _diff_rows(old_rows, new_rows, key):
    old, new = _by_key(old_rows, key), _by_key(new_rows, key)
    upsert = [new[k] for k in sorted(new) if k not in old or canonical_dumps(old[k]) != canonical_dumps(new[k])]
    return upsert, sorted(set(old) - set(new))


def build_update(prev: dict, new: dict, *, epoch_id: str, seq: int, kind: str = "prices", reason: str | None = None,
                 generated_at: str) -> dict:
    prev, new = normalize(prev), normalize(new)
    if kind == "operation" and not reason:
        raise ValueError("un update di tipo operation richiede il motivo")
    msg = {"schema": UPDATE_SCHEMA, "portfolioId": new["snapshot"]["portfolioId"], "epochId": epoch_id, "seq": seq,
           "baseSeq": seq - 1, "kind": kind, "snapshotRevision": snapshot_revision(new["snapshot"]),
           "datasetRevision": dataset_revision(new), "generatedAt": generated_at, "snapshot": new["snapshot"],
           "calendarAsOf": new["calendarAsOf"]}
    if reason:
        msg["reason"] = reason
    for upsert_key, remove_key, old_rows, new_rows, key in (
            ("historyUpsert", "historyRemoveDates", prev["history"]["points"], new["history"]["points"], "date"),
            ("sessionsUpsert", "sessionsRemoveDates", prev["sessions"], new["sessions"], "date"),
            ("catalogUpsert", "catalogRemove", prev["catalog"], new["catalog"], "ticker"),
            ("accumuliUpsert", "accumuliRemove", prev["accumuli"], new["accumuli"], "ticker")):
        up, rm = _diff_rows(old_rows, new_rows, key)
        if up:
            msg[upsert_key] = up
        if rm:
            msg[remove_key] = rm
    if canonical_dumps(prev["futureGov"]) != canonical_dumps(new["futureGov"]):
        msg["futureGov"] = new["futureGov"]
    if canonical_dumps(prev["closedSummary"]) != canonical_dumps(new["closedSummary"]):
        msg["closedSummary"] = new["closedSummary"]
    btp_up, btp_rm = {}, {}
    for ticker, pts in new["btpSeries"].items():
        up, rm = _diff_rows(prev["btpSeries"].get(ticker, []), pts, "date")
        if up:
            btp_up[ticker] = up
        if rm:
            btp_rm[ticker] = rm
    if btp_up:
        msg["btpUpsert"] = btp_up
    if btp_rm:
        msg["btpRemoveDates"] = btp_rm
    gone = sorted(set(prev["btpSeries"]) - set(new["btpSeries"]))
    if gone:
        msg["btpRemoveTickers"] = gone
    msg["messageHash"] = message_hash(msg)
    return msg


def _apply_rows(rows, upsert, remove, key):
    cur = _by_key(rows, key)
    for r in upsert or []:
        cur[r[key]] = r
    for k in remove or []:
        cur.pop(k, None)
    return [cur[k] for k in sorted(cur)]


def apply_update(prev: dict, msg: dict) -> dict:
    """Implementazione di riferimento di ciò che farà il Worker; prova che le due parti concordano."""
    ds = normalize(prev)
    ds["snapshot"] = copy.deepcopy(msg["snapshot"])
    ds["history"]["points"] = _apply_rows(ds["history"]["points"], msg.get("historyUpsert"), msg.get("historyRemoveDates"), "date")
    ds["sessions"] = _apply_rows(ds["sessions"], msg.get("sessionsUpsert"), msg.get("sessionsRemoveDates"), "date")
    ds["catalog"] = _apply_rows(ds["catalog"], msg.get("catalogUpsert"), msg.get("catalogRemove"), "ticker")
    ds["accumuli"] = _apply_rows(ds["accumuli"], msg.get("accumuliUpsert"), msg.get("accumuliRemove"), "ticker")
    if msg.get("futureGov") is not None:
        ds["futureGov"] = msg["futureGov"]
    if msg.get("closedSummary") is not None:
        ds["closedSummary"] = msg["closedSummary"]
    ds["calendarAsOf"] = msg["calendarAsOf"]
    for ticker in msg.get("btpRemoveTickers") or []:
        ds["btpSeries"].pop(ticker, None)
    for ticker, dates in (msg.get("btpRemoveDates") or {}).items():
        if ticker in ds["btpSeries"]:
            ds["btpSeries"][ticker] = _apply_rows(ds["btpSeries"][ticker], None, dates, "date")
    for ticker, pts in (msg.get("btpUpsert") or {}).items():
        ds["btpSeries"][ticker] = _apply_rows(ds["btpSeries"].get(ticker, []), pts, None, "date")
    return normalize(ds)


def bootstrap_document(ds: dict, *, epoch_id: str, bootstrap_id: str) -> bytes:
    """Documento di trasporto: JSON canonico UTF-8 di {bootstrapId, dataset, epochId}. Sono i SUOI byte a essere
    frammentati; l'impronta del solo contenuto (`datasetRevision`) è un'altra cosa."""
    return canonical_dumps({"bootstrapId": bootstrap_id, "dataset": normalize(ds), "epochId": epoch_id}).encode("utf-8")


def build_bootstrap_parts(ds: dict, *, epoch_id: str, bootstrap_id: str, reason: str = "initial", generated_at: str,
                          previous_epoch_id: str | None = None, max_part_bytes: int = MAX_PART_BYTES) -> list[dict]:
    ds = normalize(ds)
    blob = bootstrap_document(ds, epoch_id=epoch_id, bootstrap_id=bootstrap_id)
    if len(blob) > MAX_TOTAL_BYTES:
        raise ValueError("documento di bootstrap oltre il limite complessivo")
    chunks = [blob[i:i + max_part_bytes] for i in range(0, len(blob), max_part_bytes)]
    if len(chunks) > MAX_PARTS:
        raise ValueError("troppe parti di bootstrap")
    base = {"schema": BOOTSTRAP_SCHEMA, "portfolioId": ds["snapshot"]["portfolioId"], "epochId": epoch_id, "seq": 1,
            "baseSeq": 0, "bootstrapId": bootstrap_id}
    parts = [{**base, "part": i, "parts": len(chunks), "last": i == len(chunks),
              "partHash": hashlib.sha256(chunk).hexdigest(), "data": base64.b64encode(chunk).decode("ascii")}
             for i, chunk in enumerate(chunks, start=1)]
    parts[-1].update(totalHash=hashlib.sha256(blob).hexdigest(), totalBytes=len(blob),
                     snapshotRevision=snapshot_revision(ds["snapshot"]), datasetRevision=dataset_revision(ds),
                     reason=reason, generatedAt=generated_at)
    if previous_epoch_id:
        parts[-1]["previousEpochId"] = previous_epoch_id
    return parts


def assemble_bootstrap(parts: list[dict]) -> dict:
    """Riferimento di ciò che farà il Worker alla parte `last`. Le parti possono arrivare in qualunque ordine e una
    parte ripetuta con lo stesso `partHash` è ignorata; con hash diverso il bootstrap è rifiutato. Tutto è validato
    prima di qualunque pubblicazione."""
    unique = {}
    for p in parts:
        prev = unique.get(p["part"])
        if prev is not None and prev["partHash"] != p["partHash"]:
            raise ValueError(f"parte {p['part']} ripetuta con impronta diversa")
        unique[p["part"]] = p
    ordered = [unique[k] for k in sorted(unique)]
    n = ordered[0]["parts"]
    if n > MAX_PARTS or [p["part"] for p in ordered] != list(range(1, n + 1)) or any(p["parts"] != n for p in ordered):
        raise ValueError("parti mancanti o incoerenti")
    if len({(p["bootstrapId"], p["epochId"]) for p in ordered}) != 1 or not ordered[-1]["last"] or any(p["last"] for p in ordered[:-1]):
        raise ValueError("parti di bootstrap diverse o ultima parte non valida")
    chunks = []
    for p in ordered:
        chunk = base64.b64decode(p["data"], validate=True)
        if hashlib.sha256(chunk).hexdigest() != p["partHash"]:
            raise ValueError(f"impronta della parte {p['part']} non valida")
        chunks.append(chunk)
    blob, last = b"".join(chunks), ordered[-1]
    if len(blob) > MAX_TOTAL_BYTES or len(blob) != last["totalBytes"] or hashlib.sha256(blob).hexdigest() != last["totalHash"]:
        raise ValueError("documento ricostruito diverso da quello dichiarato")
    doc = json.loads(blob.decode("utf-8"))
    if doc.get("epochId") != last["epochId"] or doc.get("bootstrapId") != last["bootstrapId"]:
        raise ValueError("identificativi interni diversi dall'involucro")
    ds = normalize(doc["dataset"])
    if dataset_revision(ds) != last["datasetRevision"] or snapshot_revision(ds["snapshot"]) != last["snapshotRevision"]:
        raise ValueError("revisione dello stato ricostruito diversa da quella dichiarata")
    return ds
