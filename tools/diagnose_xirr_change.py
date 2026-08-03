from __future__ import annotations

from datetime import date

import pandas as pd

from core.domain.cashflows import (
    build_portfolio_external_xirr_flows,
    build_xirr_flows,
    compute_xirr,
)
from core.domain.positions import compute_portfolio_state
from persistence.storage import get_proventi_normalizzati, load_data


def _pct(value):
    return None if value is None else value * 100.0


def main() -> None:
    data = load_data()
    state = compute_portfolio_state(data, include_closed=True)
    df = state.get("df", pd.DataFrame())
    if df.empty:
        da = pd.DataFrame()
    else:
        qty = pd.to_numeric(df.get("Quote", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
        da = df[qty > 0.0001].copy()

    liquidita = float(state.get("liquidita", 0.0) or 0.0)
    tv = (
        float(pd.to_numeric(da.get("Controvalore", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())
        if not da.empty
        else 0.0
    )
    patrimonio = tv + liquidita

    proventi = get_proventi_normalizzati(data)
    asset_flows, asset_dates = build_xirr_flows(data, da, proventi, tickers=None)
    portfolio_flows, portfolio_dates = build_portfolio_external_xirr_flows(
        data,
        patrimonio,
        as_of_date=date.today(),
    )

    xirr_assets = compute_xirr(asset_flows, asset_dates)
    xirr_portfolio = compute_xirr(portfolio_flows, portfolio_dates)

    print(f"tv_strumenti_aperti={tv:.6f}")
    print(f"liquidita={liquidita:.6f}")
    print(f"patrimonio_finale={patrimonio:.6f}")
    print(f"xirr_assets_old_pct={_pct(xirr_assets)}")
    print(f"xirr_portfolio_new_pct={_pct(xirr_portfolio)}")
    print(f"xirr_delta_pct={None if xirr_assets is None or xirr_portfolio is None else (xirr_portfolio - xirr_assets) * 100.0}")
    print(f"asset_flows_count={len(asset_flows)}")
    print(f"external_flows_count={len(portfolio_flows)}")
    print(f"asset_first_date={asset_dates[0].isoformat() if asset_dates else ''}")
    print(f"asset_last_date={asset_dates[-1].isoformat() if asset_dates else ''}")
    print(f"external_first_date={portfolio_dates[0].isoformat() if portfolio_dates else ''}")
    print(f"external_last_date={portfolio_dates[-1].isoformat() if portfolio_dates else ''}")
    print(f"asset_flows_before_final={sum(asset_flows[:-1]) if len(asset_flows) > 1 else 0.0:.6f}")
    print(f"asset_final={asset_flows[-1] if asset_flows else 0.0:.6f}")
    print(f"external_flows_before_final={sum(portfolio_flows[:-1]) if len(portfolio_flows) > 1 else 0.0:.6f}")
    print(f"external_final={portfolio_flows[-1] if portfolio_flows else 0.0:.6f}")


if __name__ == "__main__":
    main()
