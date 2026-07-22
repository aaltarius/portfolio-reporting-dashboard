"""
ui/sidebar.py — Sidebar Streamlit: gestione strumenti, operazioni, aggiornamento quotazioni.
Richiede streamlit. Modifica data in-place e chiama st.rerun() quando necessario.
"""
import logging
import time
from datetime import date, datetime

import streamlit as st
from ui.notifications import queue_info, queue_success, update_status

from core.cache import invalidate_portfolio_cache, record_cache_decision, set_last_mutation_details
import pandas as pd

from persistence.storage import (
    APP_VERSION,
    _normalize_event_record, _rebuild_cash_ledger_from_events,
    _safe_float,
    get_registro_eventi,
    load_quotes_log, load_settings,
    macro_cat,
    save_data, save_quotes_log,
)
from core.market_data import deduce_type, find_name, find_ticker, get_price, get_price_details, get_isin_ticker_cache
from core.finance import refresh_benchmark_cache
from core.instrument_classification import is_nav_fund as _is_nav_fund
from ui.formatting import fmt_eur_it, fmt_num_it, fmt_qty_it, fmtds

logger = logging.getLogger("portafoglio.ui.sidebar")


def _latest_valid_price_for_ticker(data: dict, ticker: str) -> tuple[str | None, float | None]:
    """Restituisce ultima data storica e prezzo per ticker, se presenti."""
    try:
        for day in sorted((data.get("storico_prezzi") or {}).keys(), reverse=True):
            prices = (data.get("storico_prezzi") or {}).get(day) or {}
            if ticker in prices and prices.get(ticker) not in (None, ""):
                return str(day), float(prices.get(ticker))
    except Exception:
        pass
    return None, None


def _is_stale_price(price_date: str | None, latest_hist_date: str | None, ticker: str = "", tipo: str = "") -> bool:
    """True se la fonte restituisce un prezzo datato prima dell'ultimo storico valido.

    Non si applica quando latest_hist_date è oggi: il record odierno in storico
    è stato scritto da un run precedente della stessa fonte (chiusura di ieri sera),
    confrontare contro di esso sarebbe circolare e genererebbe falsi warning.
    I fondi NAV (OICVM) sono esentati: il loro NAV è strutturalmente T-1 e la
    data in storico può essere provvisoria (scritta prima della pubblicazione ufficiale).
    """
    if not price_date or not latest_hist_date:
        return False
    if _is_nav_fund(ticker, tipo):
        return False
    today_str = str(date.today())
    if str(latest_hist_date)[:10] >= today_str:
        return False
    try:
        return str(price_date)[:10] < str(latest_hist_date)[:10]
    except Exception:
        return False


def _is_stale_open_market(price_date: str | None, ticker: str = "", tipo: str = "") -> bool:
    """True se il prezzo è di un giorno precedente durante l'orario di borsa (fer. ≥ 09:30).

    A differenza di _is_stale_price non blocca l'aggiornamento del prezzo:
    segnala solo che la quotazione non riflette ancora la sessione odierna.
    Esclude i fondi gestiti/OICVM il cui NAV è strutturalmente T-1.
    """
    if not price_date:
        return False
    if str(price_date)[:10] >= str(date.today()):
        return False
    now = datetime.now()
    if now.weekday() >= 5:  # weekend
        return False
    from datetime import time as _t
    if now.time() < _t(9, 30):  # prima che il mercato sia ben avviato
        return False
    if _is_nav_fund(ticker, tipo):
        return False
    return True


def _apply_price_date_entries_to_storico(
    storico: dict[str, dict[str, float]],
    entries: dict[str, dict[str, float]],
) -> None:
    """Scrive in storico_prezzi i prezzi raccolti per data effettiva di mercato.

    Usata su weekend/festivi: i prezzi freschi hanno price_date = venerdì,
    ma ts (oggi) è sabato e wd=False quindi non verrebbero mai scritti nello storico.
    Opera in-place; usa setdefault+update per non sovrascrivere ticker già presenti.
    """
    for price_dt, prices in entries.items():
        storico.setdefault(price_dt, {}).update(prices)


def _quote_value_materially_changed(previous: object, current: object, *, decimals: int = 3) -> bool:
    """True solo se cambia il prezzo finanziariamente/visivamente significativo.

    Il refresh quotazioni può restituire micro-differenze decimali o aggiornare
    soltanto timestamp/fonte. Quelle variazioni non devono essere trattate come
    modifica del portafoglio, perché altrimenti scattano save_data(), cache_bust
    e rigenerazione completa di tutte le figure. La UI dell'app visualizza le
    quotazioni a 3 decimali: usiamo lo stesso livello come soglia di commit.
    """
    try:
        if previous in (None, "") and current in (None, ""):
            return False
        if previous in (None, "") or current in (None, ""):
            return True
        return round(float(previous), decimals) != round(float(current), decimals)
    except Exception:
        return str(previous) != str(current)



def render_sidebar(data: dict) -> None:
    """
    Renderizza la sidebar di gestione.
    Modifica `data` in-place, salva e chiama st.rerun() se necessario.
    """
    with st.sidebar:
        st.markdown("# ⚙️ Gestione")
        st.caption(f"v{APP_VERSION}")
        _btn_area = st.container()
        st.divider()
        _arresta_area = st.container()
        _msg_area = st.container()

    with _arresta_area:
        if st.button("⏻ Arresta Streamlit", width="stretch", key="sidebar_shutdown_streamlit"):
            st.session_state["portfolio_dashboard_shutdown_requested"] = True
            st.session_state["_portfolio_shutdown_timer_started"] = False
            st.rerun()

    with _btn_area:
        # --- Aggiorna Quotazioni ---
        if st.button("🔄 Aggiorna Quotazioni", width="stretch"):
            with _msg_area:
                status_box = st.status("Aggiornamento quotazioni in corso...", expanded=True)
                status_box.write("Recupero prezzi e riallineamento benchmark.")
                pg = st.progress(0)
            now_ts = datetime.now()
            ts = str(now_ts.date())
            ts_full = now_ts.strftime("%Y-%m-%d %H:%M:%S")
            wd = date.today().weekday() < 5
            res = []
            n = len(data["strumenti"])
            quotes_data_changed = False
            prev_prices = {}
            try:
                if data.get("storico_prezzi"):
                    _dates_sorted = sorted(data.get("storico_prezzi", {}).keys())
                    if _dates_sorted:
                        _today_str = str(date.today())
                        # Se l'ultimo giorno è oggi, prendi il penultimo (ieri)
                        # così il delta nel log è sempre vs giorno precedente
                        if _dates_sorted[-1] == _today_str and len(_dates_sorted) >= 2:
                            _prev_key = _dates_sorted[-2]
                        elif _dates_sorted[-1] != _today_str:
                            _prev_key = _dates_sorted[-1]
                        else:
                            # Solo oggi nello storico, nessun giorno precedente disponibile
                            _prev_key = None
                        if _prev_key:
                            prev_prices = (
                                data.get("storico_prezzi", {}).get(_prev_key, {}) or {}
                            ).copy()
            except Exception:
                prev_prices = {}
            quote_items = []
            candidate_today_prices: dict[str, float] = {}
            candidate_prices_by_date: dict[str, dict[str, float]] = {}
            pending_instrument_updates: list[tuple[dict, float, str, str]] = []
            material_quote_diffs: list[str] = []
            material_quote_changes: list[dict[str, object]] = []
            ticker_recent_histories: dict[str, dict[str, float]] = {}
            _ev_sb = get_registro_eventi(data)
            _rimborso_sb = {str(ev.get("ticker") or "") for ev in _ev_sb if ev.get("tipo_evento") == "RIMBORSO A SCADENZA" and str(ev.get("ticker") or "")}
            _chiusi_tickers_set = {
                str(s.get("ticker") or "")
                for s in (data.get("strumenti") or [])
                if str(s.get("ticker") or "")
                and (s.get("stato") == "chiuso" or str(s.get("ticker") or "") in _rimborso_sb)
            }
            _strumenti_attivi_sb = [s for s in data["strumenti"] if str(s.get("ticker", "")) not in _chiusi_tickers_set]
            for i, s in enumerate(_strumenti_attivi_sb):
                pg.progress((i + 1) / max(len(_strumenti_attivi_sb), 1), text=f"{s['ticker']}...")
                ticker = str(s.get("ticker", ""))
                current_price_before = s.get("prezzo")
                today_prices = (data.get("storico_prezzi") or {}).get(ts, {}) if wd else {}
                current_hist_before = today_prices.get(ticker) if isinstance(today_prices, dict) else None
                price_info = get_price_details(s["isin"], s["ticker"])
                pr = price_info.get("price")
                src = price_info.get("source", "Non trovato")
                price_date = price_info.get("price_date")
                rec_hist_item = price_info.get("recent_history") or {}
                if rec_hist_item:
                    ticker_recent_histories[ticker] = rec_hist_item

                latest_hist_date, latest_hist_px = _latest_valid_price_for_ticker(data, ticker)
                # Per decidere se il refresh cambia davvero il portafoglio non
                # bisogna confrontare il nuovo prezzo con la riga odierna assente.
                # Dopo mezzanotte current_hist_before e' spesso None, ma il prezzo
                # puo' essere identico all'ultimo valore valido: in quel caso il
                # refresh e' solo diagnostico/log e non deve aggiungere una nuova
                # data allo storico ne' invalidare tutte le cache grafiche.
                reference_px_for_change = (
                    current_hist_before
                    if current_hist_before not in (None, "")
                    else latest_hist_px if latest_hist_px is not None else s.get("prezzo")
                )
                prev_px = prev_prices.get(
                    ticker,
                    latest_hist_px if latest_hist_px is not None else s.get("prezzo")
                )

                stale = _is_stale_price(price_date, latest_hist_date, ticker=ticker, tipo=str(s.get("tipo", "")))
                stale_today = not stale and _is_stale_open_market(price_date, ticker, str(s.get("tipo", "")))
                if pr and stale:
                    kept = latest_hist_px if latest_hist_px is not None else s.get("prezzo")
                    # Non scriviamo nulla nello strumento per un dato stale: è
                    # un evento diagnostico da quotes_log, non una modifica dati.
                    detail = (
                        f"{src}: dato {price_date} più vecchio dello storico {latest_hist_date}; "
                        f"mantenuto {fmt_num_it(kept, 3) if kept not in (None, '') else '—'}"
                    )
                    res.append((s["ticker"], False, detail))
                    quote_items.append({
                        "timestamp": ts_full,
                        "ticker": s["ticker"],
                        "instrument_name": s.get("nome", s["ticker"]),
                        "source": src,
                        "status": "warning",
                        "price": None if kept in (None, "") else float(kept),
                        "previous_price": None if prev_px in (None, "") else float(prev_px),
                        "delta_pct": None,
                        "warning": detail,
                        "fallback_used": True,
                        "price_date": price_date,
                        "latest_history_date": latest_hist_date,
                    })
                elif pr:
                    pending_instrument_updates.append((s, float(pr), src, str(price_date or ts)))
                    reference_changed = _quote_value_materially_changed(reference_px_for_change, pr)
                    instrument_changed = _quote_value_materially_changed(current_price_before, pr)
                    is_nav = _is_nav_fund(ticker, str(s.get("tipo", "")))
                    if wd and reference_changed and not is_nav:
                        try:
                            candidate_today_prices[ticker] = float(pr)
                        except Exception:
                            logger.warning("Prezzo aggiornato non convertibile in float, ticker ignorato: ticker=%s value=%r", ticker, pr, exc_info=True)
                    elif reference_changed and price_date:
                        # Fondi NAV su wd: scrivi sulla data effettiva del NAV, non su oggi
                        # Strumenti non-wd: comportamento invariato
                        try:
                            candidate_prices_by_date.setdefault(str(price_date)[:10], {})[ticker] = float(pr)
                        except Exception:
                            logger.warning("Prezzo aggiornato (per data) non convertibile in float, ticker ignorato: ticker=%s value=%r", ticker, pr, exc_info=True)
                    if reference_changed or instrument_changed:
                        quotes_data_changed = True
                        try:
                            old_float = None if reference_px_for_change in (None, "") else float(reference_px_for_change)
                        except Exception:
                            old_float = None
                        try:
                            new_float = float(pr)
                        except Exception:
                            new_float = None
                        delta_abs = None
                        delta_pct = None
                        if old_float is not None and new_float is not None:
                            try:
                                delta_abs = new_float - old_float
                                if old_float != 0:
                                    delta_pct = (new_float / old_float) - 1.0
                            except Exception:
                                delta_abs = None
                                delta_pct = None
                        try:
                            material_quote_diffs.append(
                                f"{ticker}: {fmt_num_it(reference_px_for_change, 3)} -> {fmt_num_it(pr, 3)}"
                            )
                        except Exception:
                            material_quote_diffs.append(ticker)
                        material_quote_changes.append({
                            "ticker": ticker,
                            "isin": str(s.get("isin", "")),
                            "nome": str(s.get("nome", "")),
                            "categoria": str(
                                s.get("categoria")
                                or s.get("category")
                                or s.get("macro_categoria")
                                or macro_cat(s.get("tipo", ""))
                                or ""
                            ),
                            "tipologia": str(s.get("tipologia", s.get("tipo", "")) or ""),
                            "old_price": old_float,
                            "new_price": new_float,
                            "delta_abs": delta_abs,
                            "delta_pct": delta_pct,
                            "source": src,
                            "price_date": str(price_date or ts),
                        })
                    _stale_today_warn = (
                        f"Prezzo del {str(price_date)[:10]} — mercato aperto ma la fonte non ha ancora aggiornato la quotazione odierna."
                        if stale_today else None
                    )
                    res.append((s["ticker"], True, fmt_num_it(pr, 3)))
                    delta_pct = None
                    try:
                        if prev_px not in (None, "") and float(prev_px) != 0:
                            delta_pct = float(pr) / float(prev_px) - 1.0
                    except Exception:
                        delta_pct = None
                    quote_items.append({
                        "timestamp": ts_full,
                        "ticker": s["ticker"],
                        "instrument_name": s.get("nome", s["ticker"]),
                        "source": src,
                        "status": "warning" if stale_today else "ok",
                        "price": float(pr),
                        "previous_price": None if prev_px in (None, "") else float(prev_px),
                        "delta_pct": delta_pct,
                        "warning": _stale_today_warn,
                        "fallback_used": stale_today,
                        "price_date": price_date,
                        "latest_history_date": latest_hist_date,
                    })
                else:
                    old = s.get("prezzo")
                    detail = src + (
                        f" — mantenuto {fmt_num_it(old, 3)}" if old else " — nessun valore in archivio"
                    )
                    res.append((s["ticker"], False, detail))
                    quote_items.append({
                        "timestamp": ts_full,
                        "ticker": s["ticker"],
                        "instrument_name": s.get("nome", s["ticker"]),
                        "source": src,
                        "status": "warning" if old else "error",
                        "price": None if old in (None, "") else float(old),
                        "previous_price": None if prev_px in (None, "") else float(prev_px),
                        "delta_pct": None,
                        "warning": detail,
                        "fallback_used": True,
                        "price_date": price_date,
                        "latest_history_date": latest_hist_date,
                    })
                time.sleep(0.15)
            changed_tickers = [str(item.get("ticker")) for item in material_quote_changes if item.get("ticker")]
            changed_categories = sorted({str(item.get("categoria") or "") for item in material_quote_changes if str(item.get("categoria") or "")})
            mutation_details = {
                "event_type": "quote_refresh",
                "material_change": bool(quotes_data_changed),
                "changed_count": len(changed_tickers),
                "changed_tickers": changed_tickers,
                "changed_categories": changed_categories,
                "changed_instruments": material_quote_changes,
                "material_quote_diffs": list(material_quote_diffs),
                "candidate_today_prices_count": len(candidate_today_prices),
                "pending_instrument_updates_count": len(pending_instrument_updates),
                "refresh_timestamp": ts_full,
                "history_date": ts if wd else (", ".join(sorted(candidate_prices_by_date.keys())) or "non-working-day"),
            }
            set_last_mutation_details(mutation_details)

            if quotes_data_changed:
                for inst, new_price, new_source, new_date in pending_instrument_updates:
                    inst["prezzo"] = new_price
                    inst["fonte"] = new_source
                    inst["aggiornato"] = new_date
                if wd and candidate_today_prices:
                    data.setdefault("storico_prezzi", {}).setdefault(ts, {}).update(candidate_today_prices)
                if not wd and candidate_prices_by_date:
                    _apply_price_date_entries_to_storico(data.setdefault("storico_prezzi", {}), candidate_prices_by_date)
                logger.info(
                    "Refresh quotazioni con variazioni materiali: %s",
                    "; ".join(material_quote_diffs[:12]) or "n/d",
                )
            else:
                logger.info(
                    "Refresh quotazioni senza variazioni materiali: aggiornato solo quotes_log; "
                    "nessun save_data e nessuna invalidazione cache"
                )
            # --- Backfill giorni mancanti nello storico prezzi ---
            # Usa lo storico recente (7gg) restituito dal fetch per colmare i
            # gap dei giorni in cui non si è fatto l'aggiornamento.
            # Solo date precedenti a oggi; oggi è gestito dalla logica sopra.
            backfill_changed = False
            if ticker_recent_histories:
                storico_bf = data.setdefault("storico_prezzi", {})
                for ticker_bf, rec_hist_bf in ticker_recent_histories.items():
                    for hist_date_bf, hist_px_bf in sorted(rec_hist_bf.items()):
                        if hist_date_bf >= ts:
                            continue
                        if ticker_bf not in storico_bf.get(hist_date_bf, {}):
                            storico_bf.setdefault(hist_date_bf, {})[ticker_bf] = hist_px_bf
                            backfill_changed = True
                if backfill_changed:
                    logger.info(
                        "Backfill storico prezzi: aggiunte date precedenti mancanti per %d ticker",
                        len(ticker_recent_histories),
                    )
            # --- Fine backfill ---

            refreshed_benchmarks = 0
            if quotes_data_changed or backfill_changed:
                try:
                    refreshed_benchmarks = refresh_benchmark_cache(data)
                except Exception as exc:
                    logger.warning("Refresh benchmark non completato durante aggiornamento quotazioni: %s", exc)
                    refreshed_benchmarks = 0
            else:
                logger.info(
                    "Benchmark non riallineati: refresh quotazioni senza variazioni effettive di prezzo"
                )
            mutation_details["benchmarks_refreshed"] = int(refreshed_benchmarks or 0)
            mutation_details["effective_data_change"] = bool(quotes_data_changed or backfill_changed or bool(refreshed_benchmarks))
            set_last_mutation_details(mutation_details)
            effective_data_change = quotes_data_changed or backfill_changed or bool(refreshed_benchmarks)
            if effective_data_change:
                data["last_quotes_update"] = ts_full
                data["cache_lookup_strumenti"] = {**data.get("cache_lookup_strumenti", {}), **get_isin_ticker_cache()}
                save_data(data)
            pg.empty()
            quotes_log = load_quotes_log()
            quotes_log["last_refresh"] = ts_full
            retain = int(load_settings().get("quote_log_retention", 20) or 20)
            quotes_log["items"] = (
                quote_items
                + list(quotes_log.get("items", []))[: max(retain * max(n, 1), 0)]
            )
            save_quotes_log(quotes_log)
            # Il run corrente prosegue dopo la sidebar: passiamo il log appena
            # salvato ad app.py senza forzare un secondo riavvio dello script.
            st.session_state["_portfolio_quotes_log_override"] = quotes_log
            if effective_data_change:
                invalidate_portfolio_cache("aggiornamento quotazioni")
            else:
                record_cache_decision(
                    "aggiornamento quotazioni",
                    details=mutation_details,
                    invalidated=False,
                    force_reload=False,
                    scenario="quote_refresh_noop",
                    render_scope="full_tabs",
                    dirty_flags={},
                )
            ok = sum(1 for _, s, _ in res if s)
            if refreshed_benchmarks:
                queue_success(f"{ok}/{n} aggiornati · benchmark riallineati: {refreshed_benchmarks}")
                update_status(status_box, label="Quotazioni aggiornate e benchmark riallineati", state="complete")
            elif effective_data_change:
                queue_success(f"{ok}/{n} aggiornati")
                update_status(status_box, label="Quotazioni aggiornate", state="complete")
            else:
                queue_info("Nessuna variazione effettiva nelle quotazioni: cache e dashboard mantenute.")
                update_status(status_box, label="Nessuna variazione effettiva nelle quotazioni", state="complete")
            with _msg_area:
                for tk, success, detail in res:
                    st.caption(f"{'🟢' if success else '🔴'} {tk}: {detail}")
            st.session_state["goto_tab_quotazioni"] = True
            # Il click del bottone ha già avviato questo script run: lasciarlo
            # completare aggiorna la pagina una sola volta ed evita il doppio ciclo
            # update -> riavvio -> full render.

        _sidebar_settings = load_settings() or {}
        _op_mode = str(_sidebar_settings.get("operativo_mode", "entrambi"))
        _show_op_btns = _op_mode != "tradizionale"
        _sator_mode = str(_sidebar_settings.get("sator_mode", "entrambi"))
        _export_pp_mode = str(_sidebar_settings.get("export_pp_mode", "entrambi"))

        if _show_op_btns:
            if st.button("➕ Inserisci operazione", width="stretch"):
                import webbrowser
                webbrowser.open_new_tab("http://localhost:8502/operazioni")

            if st.button("📌 Strumenti", width="stretch"):
                import webbrowser
                webbrowser.open_new_tab("http://localhost:8502/strumenti")

            if st.button("📝 Operazioni", width="stretch"):
                import webbrowser
                webbrowser.open_new_tab("http://localhost:8502/operazioni_gestione")

            if st.button("💵 Liquidità", width="stretch"):
                import webbrowser
                webbrowser.open_new_tab("http://localhost:8502/liquidita_gestione")

        if _export_pp_mode != "tradizionale":
            if st.button("📊 Esporta PP", width="stretch"):
                import webbrowser
                webbrowser.open_new_tab("http://localhost:8502/export_pp")

        if _sator_mode != "tradizionale":
            if st.button("🧠 SATOR", width="stretch"):
                import webbrowser
                webbrowser.open_new_tab("http://localhost:8502/sator")

        if st.button("🔒 Privacy", width="stretch"):
            import webbrowser
            webbrowser.open_new_tab("http://localhost:8502/privacy")
