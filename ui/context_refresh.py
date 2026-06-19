from __future__ import annotations

from datetime import date
from typing import Any, Callable


def refresh_volatile_ctx_fields(
    ctx: Any,
    *,
    fmtd: Callable,
    fmtds: Callable,
    fmt_dt_it: Callable,
) -> None:
    """Aggiorna i campi del context che non sopravvivono alla cache disco.

    Va chiamata dopo ogni caricamento di orchestrate_data_cached, sia su hit
    che su miss, per garantire che:
    - header_date mostri la data di OGGI (non quella della sessione precedente)
    - fmtd/fmtds siano le funzioni correnti (non serializzate su disco)
    """
    last_upd = getattr(ctx, "last_quotes_update", None)
    ctx.header_date = (
        f"{fmtd(date.today())} "
        f"(ultimo aggiornamento quotazioni: {fmt_dt_it(last_upd)})"
    )
    ctx.fmtd = fmtd
    ctx.fmtds = fmtds
