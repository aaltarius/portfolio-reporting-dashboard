"""JSON canonico per gli hash di sincronizzazione v2 (ispirato a RFC 8785 / JCS).

Serve perché Desktop (Python) e Worker (JavaScript) calcolino la STESSA impronta. Regole:
- oggetti con chiavi ordinate per unità di codice UTF-16; nessuno spazio; array nell'ordine dato;
- numeri come `Number.prototype.toString` di JavaScript: 2.0 -> `2`, 1e21 -> `1e+21`, 1e-7 -> `1e-7`,
  -0 -> `0`; NaN e infiniti vietati; i booleani non sono numeri;
- stringhe con le sequenze di escape di `JSON.stringify` (caratteri di controllo `\\u00xx` minuscoli);
  surrogati spaiati vietati; le altre non-ASCII restano in chiaro (UTF-8);
- solo dict, list, str, int, float, bool, None.
Vettori di prova condivisi: docs/sync/vettori_hash_canonico_v2.json."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal


def format_number(x) -> str:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise TypeError("numero atteso")
    if isinstance(x, int):
        if abs(x) >= 2 ** 53:
            raise ValueError("intero oltre 2^53: non rappresentabile in modo identico in JavaScript")
        return str(x)
    if x != x or x in (float("inf"), float("-inf")):
        raise ValueError("NaN/infinito non ammessi")
    if x == 0:
        return "0"
    sign, digits, exp = Decimal(repr(abs(x))).normalize().as_tuple()
    ds = "".join(map(str, digits))
    k, n = len(ds), exp + len(ds)
    if k <= n <= 21:
        body = ds + "0" * (n - k)
    elif 0 < n <= 21:
        body = ds[:n] + "." + ds[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * (-n) + ds
    else:
        e = n - 1
        mant = ds[0] + ("." + ds[1:] if k > 1 else "")
        body = f"{mant}e{'+' if e >= 0 else '-'}{abs(e)}"
    return ("-" if x < 0 else "") + body


def _string(s: str) -> str:
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("surrogato spaiato non ammesso") from None
    return json.dumps(s, ensure_ascii=False)


def _utf16_key(s: str) -> bytes:
    return s.encode("utf-16-be")


def canonical_dumps(value) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return format_number(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonical_dumps(v) for v in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            raise TypeError("chiavi non stringa")
        return "{" + ",".join(_string(k) + ":" + canonical_dumps(value[k]) for k in sorted(value, key=_utf16_key)) + "}"
    raise TypeError(f"tipo non ammesso: {type(value).__name__}")


def canonical_sha256(value) -> str:
    return hashlib.sha256(canonical_dumps(value).encode("utf-8")).hexdigest()
