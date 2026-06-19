from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from persistence.storage import load_data
from core.finance import build_hist_df, build_portfolio_history_df


def main() -> None:
    data = load_data()
    dfh = build_hist_df(data)
    ptf_hist = build_portfolio_history_df(data)
    if dfh is None:
        print("dfh_none")
        return
    print(f"dfh_shape={dfh.shape}")
    print(f"dfh_columns={list(dfh.columns)[:20]}")
    if not dfh.empty:
        print("dfh_tail")
        print(dfh.tail(3).to_string())
    if len(dfh) < 2:
        print("storico_insufficiente")
    print(f"ptf_hist_shape={ptf_hist.shape if ptf_hist is not None else None}")
    if ptf_hist is None or ptf_hist.empty:
        print("ptf_hist_none")
        return
    print(f"ptf_hist_columns={list(ptf_hist.columns)[:30]}")
    print("ptf_hist_tail")
    print(ptf_hist.tail(3).to_string())
    if len(ptf_hist) < 2:
        print("ptf_hist_insufficiente")
        return
    last = ptf_hist.iloc[-1]
    prev = ptf_hist.iloc[-2]
    print(f"last_date={last.get('Data')}")
    print(f"prev_date={prev.get('Data')}")
    print(f"last_valore={float(last.get('Valore', 0.0)):.2f}")
    print(f"prev_valore={float(prev.get('Valore', 0.0)):.2f}")
    print(f"last_pl={float(last.get('P/L', 0.0)):.2f}")
    print(f"prev_pl={float(prev.get('P/L', 0.0)):.2f}")
    print(f"delta_pl={float(last.get('P/L', 0.0)) - float(prev.get('P/L', 0.0)):.2f}")

    rows = []
    for col in ptf_hist.columns:
        if not str(col).startswith("PL_"):
            continue
        tk = str(col)[3:]
        v_last = float(last.get(col, 0.0) or 0.0)
        v_prev = float(prev.get(col, 0.0) or 0.0)
        delta = v_last - v_prev
        if abs(delta) <= 1e-9:
            continue
        rows.append({"Ticker": tk, "PL_prev": v_prev, "PL_last": v_last, "Delta": delta})
    out = pd.DataFrame(rows)
    print("contributors")
    if out.empty or "Delta" not in out.columns:
        print("none")
    else:
        out = out.sort_values("Delta")
        print(out.to_string(index=False))


if __name__ == "__main__":
    main()
