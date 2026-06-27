from __future__ import annotations

import json
import math
import re

import pandas as pd

from persistence.storage import macro_cat
from core.finance import build_ptf_df
from ui.streamlit_compat import iframe_height_for_rows, iframe_scroll_for_rows, render_html_iframe
from ui.theme import macro_color


def render_quotes_table_with_popup(qdf, data, quotes_log):
    if qdf is None or qdf.empty:
        return

    quotes_log = quotes_log or {}
    storico = data.get("storico_prezzi", {}) or {}
    info_map = {s.get("ticker", ""): s for s in data.get("strumenti", [])}
    holdings_df = build_ptf_df(data)
    holdings_map = {}
    if isinstance(holdings_df, pd.DataFrame) and not holdings_df.empty and "Ticker" in holdings_df.columns:
        holdings_map = {str(row.get("Ticker", "")): row for _, row in holdings_df.iterrows()}
    cat_map = {s.get("ticker", ""): s.get("tipo", "") for s in data.get("strumenti", [])}

    def _cat_col(ticker):
        cat = macro_cat(cat_map.get(str(ticker or ""), ""))
        return macro_color(cat)

    def _lucide_svg(paths: list[str]) -> str:
        body = "".join(f'<path d="{path}" />' for path in paths)
        return (
            '<svg viewBox="0 0 24 24" aria-hidden="true" '
            'fill="none" stroke="currentColor" stroke-width="1.8" '
            'stroke-linecap="round" stroke-linejoin="round">'
            f"{body}</svg>"
        )

    def _nature_icon(tipo: str, ticker: str, name: str) -> tuple[str, str, str]:
        txt = f"{str(tipo or '')} {str(ticker or '')} {str(name or '')}".lower()
        if any(token in txt for token in ("fam-", "fless", "flex", "multi asset", "multi-asset", "bilanciato", "gestito")):
            return (
                "Fondo gestito / multi-asset",
                "#0F766E",
                _lucide_svg(
                    [
                        "M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z",
                        "M2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 12",
                        "M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 17",
                    ]
                ),
            )
        if any(token in txt for token in ("quality", "qualit", "quality factor")):
            return (
                "Quality factor",
                "#0EA5A4",
                _lucide_svg(
                    [
                        "M10.5 3 8 9l4 13 4-13-2.5-6",
                        "M17 3a2 2 0 0 1 1.6.8l3 4a2 2 0 0 1 .013 2.382l-7.99 10.986a2 2 0 0 1-3.247 0l-7.99-10.986A2 2 0 0 1 2.4 7.8l2.998-3.997A2 2 0 0 1 7 3z",
                        "M2 9h20",
                    ]
                ),
            )
        if any(token in txt for token in ("defence", "defense", "military", "aerospace", "security")):
            return (
                "Difesa / sicurezza",
                "#1D4ED8",
                _lucide_svg(
                    [
                        "M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z",
                    ]
                ),
            )
        if any(token in txt for token in ("oro", "gold", "xau", "metallo")):
            return (
                "Bene rifugio",
                "#C28A12",
                _lucide_svg(
                    [
                        "M10.5 3 8 9l4 13 4-13-2.5-6",
                        "M17 3a2 2 0 0 1 1.6.8l3 4a2 2 0 0 1 .013 2.382l-7.99 10.986a2 2 0 0 1-3.247 0l-7.99-10.986A2 2 0 0 1 2.4 7.8l2.998-3.997A2 2 0 0 1 7 3z",
                        "M2 9h20",
                    ]
                ),
            )
        if any(token in txt for token in ("commodity", "commodities", "broad cmdty", "raw material", "materie prime", "barrel", "dbc", "cmod")):
            return (
                "Commodities",
                "#F97316",
                _lucide_svg(
                    [
                        "M7 5.5h10l2 3.5-2 3.5H7L5 9l2-3.5",
                        "M7 12.5h10l2 3.5-2 3.5H7l-2-3.5 2-3.5",
                    ]
                ),
            )
        if any(token in txt for token in ("metals", "miners", "mining", "mine", "silver miners", "uranium", "copper", "metal miners")):
            return (
                "Metalli e miniere",
                "#B45309",
                _lucide_svg(
                    [
                        "m14 13-8.381 8.38a1 1 0 0 1-3.001-3L11 9.999",
                        "M15.973 4.027A13 13 0 0 0 5.902 2.373c-1.398.342-1.092 2.158.277 2.601a19.9 19.9 0 0 1 5.822 3.024",
                        "M16.001 11.999a19.9 19.9 0 0 1 3.024 5.824c.444 1.369 2.26 1.676 2.603.278A13 13 0 0 0 20 8.069",
                        "M18.352 3.352a1.205 1.205 0 0 0-1.704 0l-5.296 5.296a1.205 1.205 0 0 0 0 1.704l2.296 2.296a1.205 1.205 0 0 0 1.704 0l5.296-5.296a1.205 1.205 0 0 0 0-1.704z",
                    ]
                ),
            )
        if any(token in txt for token in ("emerging", "emergenti", "em market", "emerging markets")):
            return (
                "Mercati emergenti",
                "#14B8A6",
                _lucide_svg(
                    [
                        "M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20",
                        "M2 12h20",
                        "M14.5 9h5v5",
                        "M19.5 9l-5.6 5.6",
                        "M12 2a10 10 0 0 0 0 20",
                    ]
                ),
            )
        if any(token in txt for token in ("immob", "casa", "reit", "real estate", "realty", "property")):
            return (
                "Immobiliare",
                "#A16207",
                _lucide_svg(
                    [
                        "M10 12h4",
                        "M10 8h4",
                        "M14 21v-3a2 2 0 0 0-4 0v3",
                        "M6 10H4a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-2",
                        "M6 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16",
                    ]
                ),
            )
        if any(token in txt for token in ("overnight", "liquid", "cash", "xeon", "monet", "treasury bill")):
            return (
                "Liquidità",
                "#64748B",
                _lucide_svg(
                    [
                        "M17 14h.01",
                        "M7 7h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14",
                    ]
                ),
            )
        if any(token in txt for token in ("btp", "gov", "bond", "obbl", "bot", "cct", "titolo di stato", "sovereign")):
            return (
                "Obbligazionario / reddito",
                "#4F46E5",
                _lucide_svg(
                    [
                        "M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z",
                        "M14 2v5a1 1 0 0 0 1 1h5",
                        "M10 9H8",
                        "M16 13H8",
                        "M16 17H8",
                    ]
                ),
            )
        if any(token in txt for token in ("italia", "italy", "ftse mib", "mib", "mid cap italy", "pir")):
            return (
                "Italia azionario",
                "#16A34A",
                _lucide_svg(
                    [
                        "M4 22V4a1 1 0 0 1 .4-.8A6 6 0 0 1 8 2c3 0 5 2 7.333 2q2 0 3.067-.8A1 1 0 0 1 20 4v10a1 1 0 0 1-.4.8A6 6 0 0 1 16 16c-3 0-5-2-8-2a6 6 0 0 0-4 1.528",
                    ]
                ),
            )
        if any(token in txt for token in ("energy", "enrg", "oil", "gas", "xle")):
            return (
                "Energia",
                "#EA580C",
                _lucide_svg(
                    [
                        "M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z",
                    ]
                ),
            )
        if any(token in txt for token in ("health", "care", "pharma", "biotech", "xdwh")):
            return (
                "Salute",
                "#DC2626",
                _lucide_svg(
                    [
                        "M2 9.5a5.5 5.5 0 0 1 9.591-3.676.56.56 0 0 0 .818 0A5.49 5.49 0 0 1 22 9.5c0 2.29-1.5 4-3 5.5l-5.492 5.313a2 2 0 0 1-3 .019L5 15c-1.5-1.5-3-3.2-3-5.5",
                    ]
                ),
            )
        if any(token in txt for token in ("art intel", "artificial", "ai ", "xaix", "big data", "tech", "digital")):
            return (
                "Innovazione",
                "#6D28D9",
                _lucide_svg(
                    [
                        "M12 20v2",
                        "M12 2v2",
                        "M17 20v2",
                        "M17 2v2",
                        "M2 12h2",
                        "M2 17h2",
                        "M2 7h2",
                        "M20 12h2",
                        "M20 17h2",
                        "M20 7h2",
                        "M7 20v2",
                        "M7 2v2",
                        "M4 4h16v16H4z",
                        "M8 8h8v8H8z",
                    ]
                ),
            )
        if any(token in txt for token in ("emerging", "world", "all-world", "msci", "global", "vwce", "swda", "xmme")):
            return (
                "Azionario globale core",
                "#2563EB",
                _lucide_svg(
                    [
                        "M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20",
                        "M2 12h20",
                        "M12 2a14.5 14.5 0 0 1 0 20",
                    ]
                ),
            )
        return (
            "Esposizione diversificata",
            "#64748B",
            _lucide_svg(
                [
                    "M7 16v-4.5",
                    "M12 16V8.5",
                    "M17 16v-3",
                    "M6 18h12",
                ]
            ),
        )

    def _fmt_num(v, dec=2):
        try:
            f = float(v)
            return f"{f:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            return "n/d"

    def _fmt_pct(v, dec=2, signed=False):
        try:
            f = float(v) * 100
            if math.isnan(f) or math.isinf(f):
                return "n/d"
            s = _fmt_num(abs(f), dec)
            sign = "+" if signed and f > 0 else "-" if f < 0 else ""
            return f"{sign}{s}%"
        except Exception:
            return "n/d"

    def _sort_num(v):
        try:
            return str(round(float(v or 0.0), 8))
        except Exception:
            return "0"

    log_items = quotes_log.get("items", []) or []
    logs_by_ticker = {}
    for item in log_items:
        ticker = str(item.get("ticker") or "").strip()
        if not ticker:
            continue
        logs_by_ticker.setdefault(ticker, []).append(item)

    popup_payload = {}
    rows_html = ""
    for _, row in qdf.iterrows():
        ticker = str(row.get("Ticker") or "")
        info = info_map.get(ticker, {})
        holding = holdings_map.get(ticker, {})
        name = str(row.get("Strumento") or info.get("nome") or ticker)
        tipo = str(row.get("Tipologia") or info.get("tipo") or "")
        color = _cat_col(ticker)
        prezzo = row.get("Prezzo letto")
        prezzo_prec = row.get("Prezzo precedente")
        delta = row.get("Var. vs prec.")
        fonte = str(row.get("Fonte") or "")
        esito = str(row.get("Esito") or "")
        fallback = str(row.get("Fallback") or "")
        try:
            holding_qty = float(holding.get("Quote", 0) or 0)
        except Exception:
            holding_qty = 0.0
        try:
            holding_ctv = float(holding.get("Controvalore", 0) or 0)
        except Exception:
            holding_ctv = 0.0
        in_portfolio = abs(holding_qty) > 0 or abs(holding_ctv) > 0
        holding_label = "Sì" if in_portfolio else "No"
        holding_sort = "0" if in_portfolio else "1"
        holding_color = "#1E8449" if in_portfolio else "#9CA3AF"
        row_background = "" if in_portfolio else "background:#f3f4f6;"
        nature_label, nature_color, icon_svg = _nature_icon(tipo, ticker, name)
        try:
            delta_val = float(delta) if delta is not None else 0.0
        except Exception:
            delta_val = 0.0
        if delta_val > 0.03:
            sym, sym_col, sym_sort = "▲▲", "#1E8449", "0"
        elif delta_val > 0:
            sym, sym_col, sym_sort = "▲", "#1E8449", "1"
        elif delta_val < -0.03:
            sym, sym_col, sym_sort = "▼▼", "#FF4B4B", "4"
        elif delta_val < 0:
            sym, sym_col, sym_sort = "▼", "#FF4B4B", "3"
        else:
            sym, sym_col, sym_sort = "—", "#9CA3AF", "2"
        is_fam = nature_label == "Fondo gestito / multi-asset"
        if is_fam and "ERRORE" not in esito:
            esito_label, esito_title = "🔵 NAV", "Fondo gestito: NAV non confrontabile giornalmente"
        elif esito == "OK":
            esito_label, esito_title = "🟢 OK", ""
        elif "WARNING" in esito or fallback == "Sì":
            esito_label, esito_title = "🟡 Warn.", esito
        else:
            esito_label, esito_title = "🔴 Err.", esito
        esito_col = "#1E8449" if "OK" in esito_label else "#2563EB" if "NAV" in esito_label else "#F59E0B" if "Warn" in esito_label else "#FF4B4B"
        latest_log_item = max(logs_by_ticker.get(ticker, []), key=lambda x: str(x.get("timestamp") or ""), default=None)
        # Sovrascrive esito_title con il messaggio esteso dal log (warning dettagliato)
        if "Warn" in esito_label and latest_log_item:
            _log_warn = str(latest_log_item.get("warning") or "")
            if _log_warn:
                esito_title = _log_warn
        esito_title_attr = f' title="{esito_title}"' if esito_title else ""
        _pd_raw = str(latest_log_item.get("price_date") or "") if latest_log_item else ""
        _ts_raw = str(latest_log_item.get("timestamp") or "") if latest_log_item else ""
        # Data: da price_date se disponibile, altrimenti da timestamp
        _date_src = _pd_raw[:10] if len(_pd_raw) >= 10 else (_ts_raw[:10] if len(_ts_raw) >= 10 else "")
        try:
            _dy, _dm, _dd = _date_src.split("-")
            _date_part = f"{_dd}/{_dm}"
        except Exception:
            _date_part = ""
        # Ora: da price_date se include orario (len>=16); se price_date ha solo data non mostrare
        # l'orario del fetch (sarebbe fuorviante: es. "07:32" non è l'orario del prezzo BTP)
        _time_part = _pd_raw[11:16] if len(_pd_raw) >= 16 else ""
        price_date_fmt = f"{_date_part} - {_time_part}" if (_date_part and _time_part) else (_date_part or _time_part or "—")
        _sort_dt = _ts_raw[:16] if _ts_raw else "0"
        _title_dt = f"{_pd_raw} (letto {_ts_raw[:16]})" if _pd_raw else _ts_raw[:16]
        # Variazione assoluta di prezzo: prezzo letto − prezzo precedente
        try:
            _delta_eur = float(prezzo) - float(prezzo_prec) if (prezzo is not None and prezzo_prec is not None) else None
        except Exception:
            _delta_eur = None
        _delta_eur_sort = _sort_num(_delta_eur)
        if _delta_eur is not None and abs(_delta_eur) >= 0.0005:
            _sign = "+" if _delta_eur > 0 else "-" if _delta_eur < 0 else ""
            _delta_eur_fmt = f"{_sign}{_fmt_num(abs(_delta_eur), 3)}"
            _delta_eur_col = "#1E8449" if _delta_eur > 0 else "#FF4B4B"
        else:
            _delta_eur_fmt, _delta_eur_col = "—", "#9CA3AF"

        rows_html += (
            f'<tr style="{row_background}">'
            f'<td data-sort="{sym_sort}" style="text-align:center;padding:9px 6px;color:{sym_col};font-weight:800;">{sym}</td>'
            f'<td class="num" data-sort="{_sort_num(delta_val)}" style="color:{sym_col};font-weight:700;">{_fmt_pct(delta, 2, signed=True)}</td>'
            f'<td data-sort="{ticker}"><a class="tk-link" style="color:{color}" href="#" onclick="showQuoteModal(\'{ticker}\');return false;">{ticker}</a></td>'
            f'<td data-sort="{name}" style="color:{color};max-width:115px;" title="{name}">{name[:21]}</td>'
            f'<td data-sort="{nature_label}" style="text-align:center;width:36px;min-width:36px;max-width:36px;padding-left:4px;padding-right:4px;">'
            f'<span class="type-icon" title="{nature_label}" aria-label="{nature_label}" style="color:{nature_color};">{icon_svg}</span></td>'
            f'<td data-sort="{tipo}" style="color:{color};font-weight:700;max-width:31px;overflow:hidden;text-overflow:ellipsis;" title="{tipo}">{tipo}</td>'
            f'<td class="num" data-sort="{_sort_num(prezzo)}" style="max-width:68px;">{_fmt_num(prezzo, 3)}</td>'
            f'<td class="num" data-sort="{_sort_num(prezzo_prec)}" style="max-width:68px;">{_fmt_num(prezzo_prec, 3)}</td>'
            f'<td class="num" data-sort="{_delta_eur_sort}" style="color:{_delta_eur_col};font-weight:700;max-width:76px;">{_delta_eur_fmt}</td>'
            f'<td data-sort="{fonte}" style="max-width:88px;" title="{fonte}">{fonte}</td>'
            f'<td class="num" data-sort="{_sort_dt}" style="max-width:90px;color:#6b7280;white-space:nowrap;" title="{_title_dt}">{price_date_fmt}</td>'
            f'<td data-sort="{holding_sort}" style="text-align:center;max-width:32px;color:{holding_color};font-weight:700;">{holding_label}</td>'
            f'<td data-sort="{esito_label}" style="color:{esito_col};font-weight:700;max-width:60px;"{esito_title_attr}>{esito_label}</td>'
            f'</tr>'
        )

        ticker_logs = sorted(logs_by_ticker.get(ticker, []), key=lambda item: str(item.get("timestamp") or ""))
        daily_map = {}
        for item in ticker_logs:
            price = item.get("price")
            try:
                price_num = float(price) if price is not None else None
            except Exception:
                price_num = None
            try:
                var_pct = float(item.get("delta_pct")) if item.get("delta_pct") is not None else None
            except Exception:
                var_pct = None
            ts = str(item.get("timestamp") or "")
            price_date = str(item.get("price_date") or "")
            hist_date = str(item.get("latest_history_date") or "")
            day_key = (price_date or ts[:10] or hist_date or "n/d")[:10]
            payload = {
                "ts": ts,
                "date": price_date,
                "hist_date": hist_date,
                "price": price_num,
                "var_pct": var_pct,
                "status": str(item.get("status") or ""),
                "fallback": bool(item.get("fallback_used")),
                "warning": str(item.get("warning") or ""),
            }
            daily_map.setdefault(day_key, []).append(payload)
        readings = []
        hist_days = []
        for hist_day in sorted(storico.keys()):
            hist_payload = storico.get(hist_day, {})
            if not isinstance(hist_payload, dict):
                continue
            try:
                hist_price = hist_payload.get(ticker)
                hist_price_num = float(hist_price) if hist_price not in (None, "") else None
            except Exception:
                hist_price_num = None
            if hist_price_num is None:
                continue
            hist_days.append((hist_day, hist_price_num))
        for day_key, hist_close in hist_days[-12:]:
            day_items = sorted(daily_map.get(day_key, []), key=lambda row: row.get("ts") or "")
            valid_prices = [float(row["price"]) for row in day_items if row.get("price") is not None]
            status = "missing"
            fallback_used = False
            warning = ""
            last_ts = ""
            if day_items:
                statuses = {str(row.get("status") or "") for row in day_items}
                status = "ok"
                if "error" in statuses:
                    status = "error"
                elif "warning" in statuses:
                    status = "warning"
                fallback_used = any(bool(row.get("fallback")) for row in day_items)
                warning = str(day_items[-1].get("warning") or "")
                last_ts = str(day_items[-1].get("ts") or "")
            readings.append(
                {
                    "day": day_key,
                    "ts": last_ts,
                    "open": valid_prices[0] if valid_prices else hist_close,
                    "high": max(valid_prices) if valid_prices else hist_close,
                    "low": min(valid_prices) if valid_prices else hist_close,
                    "close": hist_close,
                    "count": len(day_items),
                    "status": status,
                    "fallback": fallback_used,
                    "warning": warning,
                    "date": day_key,
                    "hist_date": day_key,
                }
            )
        try:
            pmc = float(holding.get("PMC", 0) or 0)
        except Exception:
            pmc = 0.0
        try:
            qty = float(holding.get("Quote", 0) or 0)
        except Exception:
            qty = 0.0
        try:
            ctv = float(holding.get("Controvalore", 0) or 0)
        except Exception:
            ctv = 0.0
        try:
            cost = float(holding.get("Costo", 0) or 0)
        except Exception:
            cost = 0.0
        try:
            pl_e = float(holding.get("P/L €", 0) or 0)
        except Exception:
            pl_e = 0.0
        try:
            pl_p = float(holding.get("P/L %", 0) or 0)
        except Exception:
            pl_p = 0.0
        _isin = info.get("isin", "")
        _fonte_str = fonte or info.get("fonte", "n/d")
        if "Borsa Italiana" in _fonte_str and _isin:
            _source_url = f"https://www.borsaitaliana.it/borsa/obbligazioni/mot/btp/dati-completi.html?isin={_isin}&lang=it"
        elif "Yahoo" in _fonte_str:
            _yt = (re.search(r'\[(.+?)\]', _fonte_str) or type('', (), {'group': lambda s, n: ticker})()).group(1)
            _source_url = f"https://finance.yahoo.com/quote/{_yt}"
        else:
            _source_url = None

        # --- enrichment KPI ---
        from core.instrument_enrichment import _categoria as _enr_cat
        _cat = _enr_cat(info.get("tipo", ""))

        def _ev(field):
            v = info.get(field)
            return str(v) if v is not None else None

        if _cat == "btp":
            _kpi_rendimento = (_ev("ytm_netto"), "YTM Netto")
            _kpi_costo      = (None, "—")
            _kpi_rischio    = (_ev("duration_modificata"), "Duration mod.")
            _rating         = _ev("rating_emittente")
            _categoria_label = "Obbligazione Stato"
        elif _cat in ("etf", "etc"):
            _kpi_rendimento = (_ev("rendimento_1a"), "Rend. 1A")
            _kpi_costo      = (_ev("ter"), "TER")
            _kpi_rischio    = (_ev("beta"), "Beta")
            _r = info.get("rating_morningstar")
            try:
                _rating = ("★" * int(float(_r))) if _r else None
            except Exception:
                _rating = None
            _categoria_label = _ev("categoria_etf") or info.get("tipo", "")
        else:  # fam
            _ytd = _ev("rendimento_ytd")
            _1a  = _ev("rendimento_1a")
            _kpi_rendimento = (_1a or _ytd, "Rend. 1A" if _1a else "YTD")
            _kpi_costo      = (_ev("ter"), "Comm. gestione")
            _lr = _ev("livello_rischio")
            _kpi_rischio    = (f"{_lr}/7" if _lr else None, "Livello rischio")
            _r = info.get("rating_morningstar")
            try:
                _rating = ("★" * int(float(_r))) if _r else None
            except Exception:
                _rating = None
            _categoria_label = _ev("categoria_fam") or info.get("tipo", "")

        _enr_dict = {
            "kpi_rendimento": list(_kpi_rendimento),
            "kpi_costo":      list(_kpi_costo),
            "kpi_rischio":    list(_kpi_rischio),
            "rating":         _rating,
            "categoria":      _categoria_label,
            "enriched_at":    _ev("enriched_at"),
        }

        popup_payload[ticker] = {
            "nome": info.get("nome", name),
            "isin": _isin or "n/d",
            "tipo": info.get("tipo", tipo),
            "fonte": _fonte_str,
            "source_url": _source_url,
            "aggiornato": info.get("aggiornato", "n/d"),
            "prezzo": prezzo,
            "prezzo_prec": prezzo_prec,
            "pmc": pmc if pmc > 0 else None,
            "qty": qty,
            "ctv": ctv,
            "costo": cost,
            "pl_e": pl_e,
            "pl_p": pl_p,
            "daily_readings": readings,
            "available_days": len(readings),
            "log_days": sum(1 for row in readings if (row.get("count") or 0) > 0),
            "enrichment": _enr_dict,
        }

    payload_json = json.dumps(popup_payload, ensure_ascii=False).replace("</", "<\\/")
    compact_table = len(qdf) >= 20
    row_height = 30 if compact_table else 39
    iframe_h = iframe_height_for_rows(
        len(qdf), row_height=row_height, header_height=124, padding=0, min_height=380, max_height=2000, content_until_rows=18
    )
    scrolling = iframe_scroll_for_rows(len(qdf), threshold=40)
    head_pad = "6px 10px" if compact_table else "9px 12px"
    first_head_pad = "6px 6px" if compact_table else "9px 6px"
    body_pad = "5px 9px" if compact_table else "9px 12px"
    body_font = "12.25px" if compact_table else "14px"
    head_font = "11px" if compact_table else "12px"

    html_content = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{box-sizing:border-box;margin:0;padding:0;}
html,body{background:transparent;font-family:"Source Sans Pro",system-ui,-apple-system,sans-serif;font-size:__BODY_FONT__;overflow:hidden;color:#262730;}
.tw{border:1px solid #e6e9ef;border-radius:8px;overflow:hidden;background:#fff;width:100%;}
table{width:100%;border-collapse:collapse;table-layout:auto;}
thead th{background:#f0f2f6;font-size:__HEAD_FONT__;font-weight:600;letter-spacing:.01em;color:#262730;padding:__HEAD_PAD__;border-bottom:1px solid #e6e9ef;border-right:1px solid #e6e9ef;text-align:right;white-space:nowrap;position:relative;user-select:none;cursor:pointer;}
thead th:last-child{border-right:none;}
thead th:nth-child(1){text-align:center;width:26px;cursor:default;padding:__FIRST_HEAD_PAD__;}
thead th:nth-child(3),thead th:nth-child(4),thead th:nth-child(6),thead th:nth-child(10),thead th:nth-child(13){text-align:left;}
thead th:nth-child(7),thead th:nth-child(8){max-width:68px;}
thead th:hover:not(:nth-child(1)){background:#e3e6e9;}
thead th .sort-ind{font-size:9px;margin-left:3px;color:#9094a3;}
thead th.asc .sort-ind::after{content:'▲';color:#262730;}
thead th.desc .sort-ind::after{content:'▼';color:#262730;}
.rh{position:absolute;right:0;top:0;height:100%;width:4px;cursor:col-resize;background:transparent;z-index:1;}
.rh:hover{background:#9094a3;opacity:.4;}
tbody tr{border-bottom:1px solid #f0f2f6;}
tbody tr:last-child{border-bottom:none;}
tbody tr:hover{background:#f0f2f6;}
tbody td{padding:__BODY_PAD__;vertical-align:middle;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;border-right:1px solid #f0f2f6;}
tbody td:last-child{border-right:none;}
.type-icon{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;line-height:0;}
.type-icon svg{width:18px;height:18px;display:block;fill:none;}
.num{text-align:right;font-variant-numeric:tabular-nums;}
a.tk-link{text-decoration:none;font-weight:700;cursor:pointer;border-bottom:1.5px dotted;transition:opacity .15s;}
a.tk-link:hover{opacity:0.65;}
#qmo{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;align-items:center;justify-content:center;}
#qmo.on{display:flex;}
#qmc{background:#fff;border-radius:18px;padding:18px 22px 16px;max-width:1020px;width:97%;box-shadow:0 12px 52px rgba(0,0,0,.26);position:relative;color:#1f2937;}
#qmc-close{position:absolute;top:10px;right:14px;cursor:pointer;font-size:1.3rem;color:#9ca3af;background:none;border:none;line-height:1;}
#qmc-close:hover{color:#374151;}
.mc-cols{display:grid;grid-template-columns:36% 64%;gap:18px;align-items:start;}
.mc-left{min-width:0;}
.mc-right{min-width:0;display:flex;flex-direction:column;gap:10px;}
.mc-ticker{font-size:1.8rem;font-weight:900;letter-spacing:-.01em;margin-bottom:2px;}
.mc-nome{font-size:1.0rem;color:#374151;font-weight:600;}
.mc-meta{font-size:0.85rem;color:#9ca3af;margin:4px 0 12px;}
.mc-grid{display:grid;grid-template-columns:1fr 1fr;gap:5px;}
.mc-kpi{border:1px solid #e5e7eb;border-radius:8px;padding:8px 12px;}
.mc-kpi.span2{grid-column:1 / span 2;}
.mc-kpi-l{font-size:0.82rem;text-transform:uppercase;color:#9ca3af;font-weight:700;letter-spacing:.04em;margin-bottom:3px;}
.mc-kpi-v{font-size:1.05rem;font-weight:700;font-variant-numeric:tabular-nums;}
.pos{color:#1E8449;} .neg{color:#FF4B4B;}
.mc-price-box{background:#f9fafb;border:1px solid #e5e7eb;border-radius:11px;padding:10px 14px;display:flex;align-items:baseline;gap:12px;}
.mc-price-val{font-size:2.0rem;font-weight:800;font-variant-numeric:tabular-nums;}
.mc-price-sub{font-size:0.95rem;color:#6b7280;}
.mc-spark-label{font-size:0.78rem;text-transform:uppercase;color:#9ca3af;font-weight:700;letter-spacing:.05em;}
svg.spark{width:100%;height:152px;display:block;border-radius:10px;background:#f9fafb;}
.read-table{border:1px solid #e5e7eb;border-radius:10px;overflow:hidden;background:#fff;}
.read-table table{width:100%;border-collapse:collapse;table-layout:fixed;}
.read-table th,.read-table td{padding:5px 7px;border-bottom:1px solid #eef0f4;font-size:11px;line-height:1.15;}
.read-table th{background:#f8fafc;text-align:left;color:#64748b;font-weight:700;}
.read-table th:first-child,.read-table td:first-child{width:92px;}
.read-table td.num{text-align:right;font-variant-numeric:tabular-nums;}
.read-table tr:last-child td{border-bottom:none;}
.tag-ok{color:#1E8449;font-weight:700;}
.tag-warn{color:#F59E0B;font-weight:700;}
.tag-err{color:#FF4B4B;font-weight:700;}
.tag-miss{color:#94a3b8;font-weight:700;}
.mc-footer{font-size:0.78rem;color:#9ca3af;}
</style></head>
<body>
<div class="tw"><table id="quotes-table">
<thead><tr>
  <th data-col="0"></th>
  <th data-col="1">Var.%<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="2">Ticker<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="3">Strumento<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="4">Tipo<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="5">Tipologia<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="6">Prezzo<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="7">Prec.<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="8">Δ Prezzo<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="9">Fonte<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="10">Data quot.<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="11">Ptf<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="12">Esito<span class="sort-ind"></span><span class="rh"></span></th>
</tr></thead>
<tbody id="quotes-body">__ROWS__</tbody>
</table></div>
<div id="qmo" onclick="if(event.target===this)closeQuoteModal()">
<div id="qmc">
  <button id="qmc-close" onclick="closeQuoteModal()">&#x2715;</button>
  <div class="mc-cols">
    <div class="mc-left">
      <div class="mc-ticker" id="qm-tk"></div>
      <div class="mc-nome" id="qm-nm"></div>
      <div class="mc-meta" id="qm-meta"></div>
      <div class="mc-grid" id="qm-grid"></div>
    </div>
    <div class="mc-right">
      <div class="mc-price-box">
        <div>
          <div style="font-size:0.78rem;text-transform:uppercase;color:#9ca3af;font-weight:700;margin-bottom:2px;">Ultimo prezzo letto</div>
          <div class="mc-price-val" id="qm-px"></div>
        </div>
        <div id="qm-delta" class="mc-price-sub"></div>
      </div>
      <div class="mc-spark-label">Ultimi 12 giorni disponibili</div>
      <svg class="spark" id="qm-spark" viewBox="0 0 620 180" preserveAspectRatio="none"></svg>
      <div class="read-table">
        <table>
          <thead><tr><th>Giorno</th><th class="num">Apert.</th><th class="num">Chius.</th><th class="num">Range</th><th class="num">Lett.</th><th>Esito</th></tr></thead>
          <tbody id="qm-readings"></tbody>
        </table>
      </div>
      <div class="mc-footer" id="qm-footer"></div>
      <div id="qm-enr"></div>
    </div>
  </div>
</div>
</div>
<script>
var QD=__QUOTES_JSON__;
function fi(v,d,sgn){if(v==null||isNaN(v))return'n/d';var n=parseFloat(v).toLocaleString('it-IT',{minimumFractionDigits:d,maximumFractionDigits:d});return (sgn&&v>0?'+':'')+n;}
function fp(v,d,sgn){if(v==null||isNaN(v))return'n/d';var pct=parseFloat(v)*100;var n=Math.abs(pct).toLocaleString('it-IT',{minimumFractionDigits:d||2,maximumFractionDigits:d||2});return (sgn&&pct>0?'+':pct<0?'-':'')+n+'%';}
function fmtTs(v){if(!v)return 'n/d';return String(v).replace('T',' ');}
function kpi(label,val,cls){return '<div class="mc-kpi"><div class="mc-kpi-l">'+label+'</div><div class="mc-kpi-v'+(cls?' '+cls:'')+'">'+val+'</div></div>';}
function kpiWide(label,val,cls){return '<div class="mc-kpi span2"><div class="mc-kpi-l">'+label+'</div><div class="mc-kpi-v'+(cls?' '+cls:'')+'">'+val+'</div></div>';}
function buildReadingsTable(readings){
  var body=document.getElementById('qm-readings'); body.innerHTML='';
  if(!readings||!readings.length){body.innerHTML='<tr><td colspan="6" style="color:#94a3b8;">Nessuna lettura disponibile</td></tr>'; return;}
  readings.slice().reverse().forEach(function(r){
    var cls=r.status==='ok'?'tag-ok':(r.status==='warning'?'tag-warn':(r.status==='missing'?'tag-miss':'tag-err'));
    var label=r.status==='ok'?'OK':(r.status==='warning'?'Warning':(r.status==='missing'?'Solo storico':'Errore'));
    var range=(r.low!=null&&r.high!=null)?(fi(r.low,3,false)+' / '+fi(r.high,3,false)):'n/d';
    var tr=document.createElement('tr');
    tr.innerHTML='<td>'+(r.day||'n/d')+'</td><td class="num">'+(r.open==null?'n/d':fi(r.open,3,false))+'</td><td class="num">'+(r.close==null?'n/d':fi(r.close,3,false))+'</td><td class="num">'+range+'</td><td class="num">'+String(r.count||0)+'</td><td class="'+cls+'">'+label+(r.fallback?' · fb':'')+'</td>';
    body.appendChild(tr);
  });
}
function sparklineReadings(readings, isPositive, pmc){
  var svg=document.getElementById('qm-spark'); svg.innerHTML='';
  var W=620,H=180,padX=26,padY=18;
  var usable=(readings||[]).filter(function(r){return r.close!=null&&!isNaN(r.close);});
  if(usable.length<2){var t=document.createElementNS('http://www.w3.org/2000/svg','text'); t.setAttribute('x','50%'); t.setAttribute('y','52%'); t.setAttribute('text-anchor','middle'); t.setAttribute('fill','#cbd5e1'); t.setAttribute('font-size','11'); t.textContent='Storico letture insufficiente'; svg.appendChild(t); return;}
  var vals=[];
  usable.forEach(function(p){
    if(p.open!=null) vals.push(parseFloat(p.open));
    if(p.high!=null) vals.push(parseFloat(p.high));
    if(p.low!=null) vals.push(parseFloat(p.low));
    if(p.close!=null) vals.push(parseFloat(p.close));
  });
  var mn=Math.min.apply(null,vals), mx=Math.max.apply(null,vals);
  if(pmc!=null&&!isNaN(pmc)){mn=Math.min(mn,pmc); mx=Math.max(mx,pmc);}
  var rng=(mx-mn)||0.001;
  var toY=function(v){return H-padY-((v-mn)/rng*(H-padY*2));};
  var pts=[]; usable.forEach(function(v,i){var x=padX+(i/(usable.length-1))*(W-padX*2); var y=toY(parseFloat(v.close)); pts.push({x:x,y:y,raw:v});});
  var col=isPositive?'#1E8449':'#FF4B4B';
  var fill=isPositive?'rgba(30,132,73,0.12)':'rgba(255,75,75,0.12)';
  var area=document.createElementNS('http://www.w3.org/2000/svg','polygon');
  area.setAttribute('points',pts[0].x+','+(H-padY)+' '+pts.map(function(p){return p.x.toFixed(1)+','+p.y.toFixed(1);}).join(' ')+' '+pts[pts.length-1].x+','+(H-padY));
  area.setAttribute('fill',fill); svg.appendChild(area);
  if(pmc!=null&&!isNaN(pmc)){var py=toY(pmc); var lineP=document.createElementNS('http://www.w3.org/2000/svg','line'); lineP.setAttribute('x1',padX); lineP.setAttribute('x2',W-padX); lineP.setAttribute('y1',py); lineP.setAttribute('y2',py); lineP.setAttribute('stroke','#6b7280'); lineP.setAttribute('stroke-width','1.8'); lineP.setAttribute('stroke-dasharray','7 5'); svg.appendChild(lineP); var tx=document.createElementNS('http://www.w3.org/2000/svg','text'); tx.setAttribute('x',W-padX-4); tx.setAttribute('y',Math.max(12,py-4)); tx.setAttribute('text-anchor','end'); tx.setAttribute('fill','#4b5563'); tx.setAttribute('font-size','10'); tx.textContent='PMC'; svg.appendChild(tx);}
  pts.forEach(function(p){
    var raw=p.raw;
    var wick=document.createElementNS('http://www.w3.org/2000/svg','line');
    wick.setAttribute('x1',p.x); wick.setAttribute('x2',p.x); wick.setAttribute('y1',toY(parseFloat(raw.high))); wick.setAttribute('y2',toY(parseFloat(raw.low)));
    wick.setAttribute('stroke','#cbd5e1'); wick.setAttribute('stroke-width','2'); svg.appendChild(wick);
    if((raw.count||0) > 1 && raw.open!=null){
      var openTick=document.createElementNS('http://www.w3.org/2000/svg','line');
      openTick.setAttribute('x1',p.x-7); openTick.setAttribute('x2',p.x-1); openTick.setAttribute('y1',toY(parseFloat(raw.open))); openTick.setAttribute('y2',toY(parseFloat(raw.open)));
      openTick.setAttribute('stroke','#64748b'); openTick.setAttribute('stroke-width','1.6'); svg.appendChild(openTick);
    }
  });
  var poly=document.createElementNS('http://www.w3.org/2000/svg','polyline');
  poly.setAttribute('points',pts.map(function(p){return p.x.toFixed(1)+','+p.y.toFixed(1);}).join(' ')); poly.setAttribute('fill','none'); poly.setAttribute('stroke',col); poly.setAttribute('stroke-width','2.4'); svg.appendChild(poly);
  pts.forEach(function(p,idx){var c=document.createElementNS('http://www.w3.org/2000/svg','circle'); c.setAttribute('cx',p.x); c.setAttribute('cy',p.y); c.setAttribute('r',idx===pts.length-1?4:3); c.setAttribute('fill',p.raw.fallback?'#ffffff':col); c.setAttribute('stroke',p.raw.fallback?'#F59E0B':col); c.setAttribute('stroke-width',p.raw.fallback?'2':'1.4'); svg.appendChild(c);});
}
function showQuoteModal(tk){
  var d=QD[tk]; if(!d)return;
  var px=(d.prezzo!=null&&!isNaN(d.prezzo))?parseFloat(d.prezzo):null;
  var pmc=(d.pmc!=null&&!isNaN(d.pmc))?parseFloat(d.pmc):null;
  var prev=(d.prezzo_prec!=null&&!isNaN(d.prezzo_prec))?parseFloat(d.prezzo_prec):null;
  var latestReading=(d.daily_readings&&d.daily_readings.length)?d.daily_readings[d.daily_readings.length-1]:null;
  var refDelta=(pmc&&pmc>0&&px!=null)?((px/pmc)-1):((prev&&prev!==0&&px!=null)?((px/prev)-1):0);
  var positive=refDelta>=0; var cls=positive?'pos':'neg';
  document.getElementById('qm-tk').textContent=tk;
  document.getElementById('qm-tk').style.color=positive?'#1E8449':'#374151';
  document.getElementById('qm-nm').textContent=d.nome||tk;
  document.getElementById('qm-meta').textContent='ISIN: '+(d.isin||'n/d')+' · '+(d.tipo||'n/d');
  document.getElementById('qm-px').textContent=px==null?'n/d':fi(px,3,false);
  document.getElementById('qm-px').className='mc-price-val '+cls;
  document.getElementById('qm-delta').innerHTML=(pmc&&pmc>0&&px!=null)?('<span class="'+cls+'">'+fp((px/pmc)-1,2,true)+' vs PMC</span>'):((prev&&px!=null)?('<span class="'+cls+'">'+fp((px/prev)-1,2,true)+' vs precedente</span>'):'');
  document.getElementById('qm-grid').innerHTML=
    kpi('PMC',pmc&&pmc>0?fi(pmc,3,false):'n/d')+
    kpi('Quantità',d.qty?fi(d.qty,3,false):'0,000')+
    kpi('Controvalore',fi(d.ctv||0,2,false)+' €')+
    kpi('Costo storico',fi(d.costo||0,2,false)+' €')+
    kpi('P/L €',fi(d.pl_e||0,2,true)+' €',(d.pl_e||0)>=0?'pos':'neg')+
    kpi('P/L %',fp(d.pl_p||0,2,true),(d.pl_p||0)>=0?'pos':'neg')+
    kpi('Storico',String(d.available_days||0)+' gg')+
    kpi('Log letture',String(d.log_days||0)+' / '+String(d.available_days||0))+
    kpiWide('Fonte / AGG.',(d.fonte||'n/d')+' · '+(d.aggiornato||'n/d'))+
    (d.source_url?kpiWide('Link fonte','<a href="'+d.source_url+'" target="_blank" rel="noopener" style="color:#2563EB;text-decoration:underline;word-break:break-all;font-size:0.82rem;">'+d.source_url+'</a>'):'');
  sparklineReadings(d.daily_readings||[], positive, pmc);
  buildReadingsTable(d.daily_readings||[]);
  var foot='Grafico e tabella: ultimi 12 giorni disponibili dallo storico prezzi · giorni con log letture: '+String(d.log_days||0)+' / '+String(d.available_days||0); if(latestReading){foot+=' · ultima data '+(latestReading.day||fmtTs(latestReading.ts)); if(latestReading.warning){foot+=' · '+latestReading.warning;}}
  document.getElementById('qm-footer').textContent=foot;
  var enr=(d.enrichment||{}); var enrHtml='';
  if(enr.enriched_at){
    var kpiBox=function(val,label){var v=val||'—';return '<div style="flex:1;text-align:center;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 6px;"><div style="font-size:17px;font-weight:700;color:#0f172a;">'+v+'</div><div style="font-size:10px;color:#64748b;margin-top:2px;">'+label+'</div></div>';};
    var r=enr.kpi_rendimento||['—','']; var c=enr.kpi_costo||['—','']; var k=enr.kpi_rischio||['—',''];
    enrHtml+='<div style="margin-top:12px;border-top:1px solid #f1f5f9;padding-top:12px;">';
    enrHtml+='<div style="display:flex;gap:8px;margin-bottom:8px;">'+kpiBox(r[0],r[1])+kpiBox(c[0],c[1])+kpiBox(k[0],k[1])+'</div>';
    if(enr.rating||enr.categoria){enrHtml+='<div style="display:flex;gap:12px;font-size:12px;color:#475569;">'; if(enr.rating)enrHtml+='<span><b>Rating:</b> '+enr.rating+'</span>'; if(enr.categoria)enrHtml+='<span><b>Categoria:</b> '+enr.categoria+'</span>'; enrHtml+='</div>';}
    enrHtml+='</div>';
  } else {
    enrHtml+='<div style="margin-top:12px;border-top:1px solid #f1f5f9;padding-top:10px;font-size:11px;color:#94a3b8;">Dati finanziari non ancora caricati — <a href="http://localhost:8502/strumento/'+tk+'" target="_blank" style="color:#0ea5e9;">Arricchisci</a></div>';
  }
  enrHtml+='<div style="margin-top:8px;text-align:right;"><a href="http://localhost:8502/strumento/'+tk+'" target="_blank" style="font-size:11px;color:#0ea5e9;text-decoration:none;font-weight:600;">Scheda completa →</a></div>';
  document.getElementById('qm-enr').innerHTML=enrHtml;
  document.getElementById('qmo').classList.add('on');
}
function closeQuoteModal(){document.getElementById('qmo').classList.remove('on');}
document.addEventListener('keydown',function(e){if(e.key==='Escape')closeQuoteModal();});
var _sc=-1,_sa=true;
function sortQ(ci){if(ci===0)return; if(_sc===ci)_sa=!_sa; else{_sc=ci;_sa=true;} document.querySelectorAll('#quotes-table thead th').forEach(function(t){t.classList.remove('asc','desc');}); var th=document.querySelector('#quotes-table thead th[data-col="'+ci+'"]'); if(th)th.classList.add(_sa?'asc':'desc'); var tb=document.getElementById('quotes-body'); var rows=Array.from(tb.querySelectorAll('tr')); rows.sort(function(a,b){var av=a.cells[ci]?a.cells[ci].getAttribute('data-sort')||'':''; var bv=b.cells[ci]?b.cells[ci].getAttribute('data-sort')||'':''; var an=parseFloat(av), bn=parseFloat(bv); if(!isNaN(an)&&!isNaN(bn)) return _sa?an-bn:bn-an; return _sa?av.localeCompare(bv,'it'):bv.localeCompare(av,'it');}); rows.forEach(function(r){tb.appendChild(r);});}
document.querySelectorAll('#quotes-table thead th[data-col]').forEach(function(th){var ci=parseInt(th.getAttribute('data-col')); if(ci===0)return; th.addEventListener('click',function(){sortQ(ci);});});
sortQ(11);
function sendH(){
  var t=document.getElementById('quotes-table');
  var wrap=document.querySelector('.tw');
  if(!t && !wrap) return;
  var tableH=t?Math.ceil(t.getBoundingClientRect().height):0;
  var wrapH=wrap?Math.ceil(wrap.getBoundingClientRect().height):0;
  var bodyH=Math.ceil(document.body.scrollHeight||0);
  var docH=Math.ceil(document.documentElement.scrollHeight||0);
  var h=Math.max(tableH, wrapH, bodyH, docH) + 10;
  var py=0; try{py=window.parent.scrollY||window.parent.pageYOffset||0;}catch(e){}
  window.parent.postMessage({type:'streamlit:setFrameHeight',height:h},'*');
  [10,60,200].forEach(function(d){setTimeout(function(){try{window.parent.scrollTo({top:py,behavior:'instant'});}catch(e){}},d);});
}
sendH(); requestAnimationFrame(sendH); setTimeout(sendH,150); setTimeout(sendH,600);
</script>
</body></html>"""
    html_content = html_content.replace("__ROWS__", rows_html)
    html_content = html_content.replace("__QUOTES_JSON__", payload_json)
    html_content = html_content.replace("__BODY_FONT__", body_font)
    html_content = html_content.replace("__HEAD_FONT__", head_font)
    html_content = html_content.replace("__HEAD_PAD__", head_pad)
    html_content = html_content.replace("__FIRST_HEAD_PAD__", first_head_pad)
    html_content = html_content.replace("__BODY_PAD__", body_pad)
    render_html_iframe(html_content, height=iframe_h, scrolling=scrolling)
