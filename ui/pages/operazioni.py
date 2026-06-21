"""
ui/pages/operazioni.py — Tab Operazioni: event log and transaction registry
Pure rendering with pre-filtered service data.
"""
import logging
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from core.cache import invalidate_portfolio_cache
from streamlit.delta_generator import DeltaGenerator

from persistence.storage import (
    macro_cat, _safe_float, _new_event_id,
    _normalize_event_record, _rebuild_cash_ledger_from_events,
    get_registro_eventi,
    save_data,
)
from core.validation import (
    _supports_coupon, _supports_dividend, _supports_redemption,
)
from core.validators import (
    validate_date,
    validate_number_input,
    validate_price,
    validate_quantity,
)
from core.finance import append_evento_portafoglio, compute_portfolio_state
from core.market_data import deduce_type, find_name, find_ticker, get_price
from core.services import (
    get_portfolio_operations,
    get_cash_movements,
    build_monthly_purchase_spending,
)
from ui.formatting import (
    fmt_dt_it, fmt_eur_it, fmt_qty_it, fmtds,
)
from ui.components import (
    macro_color, legend_block, back_to_top,
    render_styled_table,
    render_section_title, should_render_section,
)
from ui.charts.operazioni import (
    build_monthly_purchase_spending_time_chart,
    build_purchase_installments_chart,
)
from ui.charts.calendario_btp import render_btp_calendar
from ui.charts.settings import apply_settings
from ui.i18n import t
from ui.theme import get_theme_context
from ui.notifications import queue_info, queue_success
from ui.page_chrome import render_page_intro as render_page_intro_shared

logger = logging.getLogger("portafoglio.ui.operazioni")


def _trade_amount_label(event_type: str) -> str:
    return "Importo pagato / controvalore lordo €" if event_type == "ACQUISTO" else "Incasso lordo / controvalore lordo €"


def _compute_trade_triplet(mode: str, qty: float, price: float, gross: float) -> tuple[float, float, float]:
    qty = max(float(qty or 0.0), 0.0)
    price = max(float(price or 0.0), 0.0)
    gross = max(float(gross or 0.0), 0.0)
    if mode == "quote_prezzo":
        gross = qty * price
    elif mode == "quote_importo":
        price = (gross / qty) if qty > 0 else 0.0
    elif mode == "prezzo_importo":
        qty = (gross / price) if price > 0 else 0.0
    return qty, price, gross


def _default_tax_rate_pct(evento: str, ticker: str, info_map: dict[str, dict[str, Any]]) -> float:
    if evento != "CEDOLA":
        return 26.0
    instrument_type = info_map.get(ticker, {}).get("tipo", "")
    return 12.5 if macro_cat(instrument_type) == "GOV" else 26.0


def _default_batch_rows(max_rows: int) -> pd.DataFrame:
    today = date.today()
    return pd.DataFrame([
        {
            "Data": today,
            "Evento": "",
            "Ticker": "",
            "Qtà": 0.0,
            "Prezzo": 0.0,
            "Importo €": 0.0,
            "Comm €": 0.0,
            "Aliquota %": 0.0,
            "Auto liq": True,
            "Note": "",
        }
        for _ in range(max_rows)
    ])


def _render_batch_operations_style(theme) -> None:
    st.markdown(
        f"""
        <style>
        .ops-batch-guide {{
          padding: 16px 18px;
          border: 1px solid {theme.border_color};
          border-radius: 20px;
          background: {theme.bg_surface};
          box-shadow: {theme.shadow_color};
          margin: 0 0 14px 0;
        }}
        .ops-batch-guide-title {{
          font-size: 0.75rem;
          text-transform: uppercase;
          letter-spacing: .06em;
          font-weight: 800;
          color: {theme.color_gray};
          margin-bottom: 8px;
        }}
        .ops-batch-guide-text {{
          color: {theme.font_color};
          line-height: 1.56;
          font-size: 0.88rem;
        }}
        .ops-batch-help-grid {{
          display:grid;
          grid-template-columns:repeat(2,minmax(0,1fr));
          gap:12px;
          margin-top:12px;
        }}
        .ops-batch-help-box {{
          padding:12px 14px;
          border:1px solid {theme.border_color};
          border-radius:14px;
          background:{theme.colors.get('bg_surface_alt', theme.bg_surface)};
          color:{theme.font_color};
          line-height:1.56;
          font-size:0.86rem;
        }}
        .ops-batch-rule {{
          margin-top: 12px;
          padding: 12px 14px;
          border: 1px solid {theme.border_color};
          border-radius: 14px;
          background: {theme.colors.get('bg_surface_alt', theme.bg_surface)};
          color: {theme.font_color};
          line-height: 1.56;
          font-size: 0.86rem;
        }}
        .ops-batch-errorlist {{
          margin: 8px 0 0 0;
          padding-left: 18px;
          color: {theme.font_color};
        }}
        .ops-batch-errorlist li {{
          margin: 4px 0;
        }}
        @media (max-width: 960px) {{
          .ops-batch-help-grid {{
            grid-template-columns: 1fr;
          }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_batch_operations_guide(theme, batch_max_rows: int) -> None:
    _render_batch_operations_style(theme)
    st.markdown(
        f"""
        <div class="ops-batch-guide">
          <div class="ops-batch-guide-title">Inserimento multiplo guidato</div>
          <div class="ops-batch-guide-text">
            Compila fino a <b>{batch_max_rows} righe</b> e registra tutto con un solo invio.
            Per <b>ACQUISTO</b>, <b>VENDITA</b> e <b>RIMBORSO A SCADENZA</b> devi valorizzare
            <b>esattamente due campi</b> tra <b>Qtà</b>, <b>Prezzo</b> e <b>Importo €</b>:
            il terzo viene ricavato automaticamente in fase di validazione.
          </div>
          <div class="ops-batch-help-grid">
            <div class="ops-batch-help-box">
              <b>Titoli</b><br>
              `ACQUISTO`, `VENDITA`, `RIMBORSO A SCADENZA`:
              compila 2 campi su 3 tra `Qtà`, `Prezzo`, `Importo €`.
              Il terzo viene calcolato. Se vuoi il calcolo, lascia quel campo a `0`.
            </div>
            <div class="ops-batch-help-box">
              <b>Proventi e cassa</b><br>
              `CEDOLA` e `DIVIDENDO`: usa `Ticker`, `Importo €` e, solo se serve, `Aliquota`.
              `VERSAMENTO`, `PRELIEVO`, `COMMISSIONE`, `IMPOSTA`: conta soprattutto `Importo €`.
            </div>
          </div>
          <div class="ops-batch-rule">
            Se ci sono errori, <b>nessuna operazione viene registrata</b>. L'app ti mostra l'elenco delle righe da correggere.
            L'aliquota resta vuota a default per non creare ambiguità: se non la inserisci su cedole/dividendi,
            viene applicato automaticamente il valore standard in fase di controllo.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

@st.dialog("Aggiungi Operazione")
def form_operazione_dialog(data: dict[str, Any], ctx: SimpleNamespace) -> None:
    """Dialog modale per inserimento nuove operazioni."""
    da = ctx.da
    fmtds = ctx.fmtds

    tks_ops = [s["ticker"] for s in data.get("strumenti", []) if s.get("stato", "aperto") != "chiuso"]
    if not tks_ops:
        st.info("Aggiungi prima uno strumento.")
        return

    area_op = st.radio(
        "Ambito operativo",
        ["Titolo", "Liquidità / Costi generali"],
        horizontal=True,
        key="ops_dialog_area",
    )

    if area_op == "Titolo":
        _da_qty: dict[str, float] = {}
        if not da.empty and "Ticker" in da.columns and "Quote" in da.columns:
            for _, _r in da.iterrows():
                _t = str(_r.get("Ticker") or "")
                _q = _safe_float(_r.get("Quote", 0))
                if _t:
                    _da_qty[_t] = _q

        def _fmt_tk(t: str) -> str:
            q = _da_qty.get(t, 0.0)
            return f"{t} ({fmt_qty_it(q, 0)} quote)" if q > 1e-12 else t

        tk_sel = st.selectbox("Seleziona titolo", tks_ops, format_func=_fmt_tk, key="ops_dialog_ticker")
        strum_sel = next((s for s in data["strumenti"] if s["ticker"] == tk_sel), {})
        row_sel = da[da["Ticker"] == tk_sel] if not da.empty else pd.DataFrame()

        qty_disp = _safe_float(row_sel.iloc[0].get("Quote", 0)) if not row_sel.empty else 0.0
        pmc_disp = _safe_float(row_sel.iloc[0].get("PMC", 0)) if not row_sel.empty else 0.0
        prezzo_att = _safe_float(strum_sel.get("prezzo", 0))
        if qty_disp > 1e-12:
            st.caption(f"Quote disponibili: **{fmt_qty_it(qty_disp, 4)}**")

        ops_consentite = ["ACQUISTO"]
        if qty_disp > 1e-12:
            ops_consentite.append("VENDITA")
        if _supports_coupon(data, tk_sel):
            ops_consentite.append("CEDOLA")
        if _supports_dividend(data, tk_sel):
            ops_consentite.append("DIVIDENDO")
        if qty_disp > 1e-12 and _supports_redemption(data, tk_sel):
            ops_consentite.append("RIMBORSO A SCADENZA")

        evento_sel = st.selectbox("Operazione consentita", ops_consentite, key="ops_dialog_evento")

        if evento_sel == "ACQUISTO":
            _ev_acq_tk = [e for e in get_registro_eventi(data) if e.get("ticker") == tk_sel and e.get("tipo_evento") == "ACQUISTO"]
            _default_note = "Primo acquisto" if not _ev_acq_tk else "FND mensile"
        elif evento_sel == "VENDITA":
            _default_note = "Disinvestimento"
        elif evento_sel == "RIMBORSO A SCADENZA":
            _default_note = "Rimborso a scadenza"
        elif evento_sel == "CEDOLA":
            _default_note = "Cedola"
        elif evento_sel == "DIVIDENDO":
            _default_note = "Dividendo"
        else:
            _default_note = ""

        data_sel = st.date_input("Data", value=date.today(), format="DD/MM/YYYY", key=f"ops_dialog_date_{tk_sel}_{evento_sel}")
        auto_liq = False
        if evento_sel == "ACQUISTO":
            auto_liq = st.checkbox(
                "Registra automaticamente la liquidità necessaria per l'acquisto",
                value=True,
                key=f"ops_dialog_auto_liq_{tk_sel}",
            )
            st.caption("Se attivo, l'app registra in parallelo un versamento di cassa per coprire controvalore, commissioni e imposte.")

        if evento_sel in {"ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA"}:
            vendi_tutto = False
            if evento_sel in {"VENDITA", "RIMBORSO A SCADENZA"} and qty_disp > 0:
                vendi_tutto = st.checkbox(
                    f"Vendi tutte le quote disponibili ({fmt_qty_it(qty_disp, 4)} quote)",
                    value=False,
                    key=f"ops_dialog_sell_all_{tk_sel}_{evento_sel}",
                )

            mode_options = {
                "quote_prezzo": "Quote + Prezzo -> calcola Importo",
                "quote_importo": "Quote + Importo pagato -> calcola Prezzo",
                "prezzo_importo": "Prezzo + Importo pagato -> calcola Quote",
            }
            calc_mode = st.selectbox(
                "Modalità inserimento",
                list(mode_options.keys()),
                format_func=lambda key: mode_options[key],
                key=f"ops_dialog_calc_mode_{tk_sel}_{evento_sel}",
            )
            st.caption("Inserisci due valori e l'app calcola automaticamente il terzo.")

            qty_default = float(qty_disp) if (evento_sel in {"VENDITA", "RIMBORSO A SCADENZA"} and qty_disp > 0 and calc_mode != "prezzo_importo") else 0.0001
            price_default = prezzo_att if prezzo_att > 0 else max(pmc_disp, 0.0001)
            gross_default = max(qty_default * price_default, 0.01)
            amount_label = _trade_amount_label(evento_sel)

            c1, c2, c3 = st.columns(3)
            if calc_mode == "quote_prezzo":
                quantita_in = c1.number_input("Quote", min_value=0.0001, value=float(qty_default), step=0.01, format="%.4f", key=f"ops_dialog_qty_{tk_sel}_{evento_sel}")
                prezzo_in = c2.number_input("Prezzo", min_value=0.0001, value=float(price_default), step=0.01, format="%.4f", key=f"ops_dialog_price_{tk_sel}_{evento_sel}")
                quantita_op, prezzo_op, lordo_op = _compute_trade_triplet(calc_mode, quantita_in, prezzo_in, 0.0)
                c3.number_input(amount_label, min_value=0.0, value=float(lordo_op), step=0.01, format="%.2f", disabled=True, key=f"ops_dialog_gross_calc_{tk_sel}_{evento_sel}")
            elif calc_mode == "quote_importo":
                quantita_in = c1.number_input("Quote", min_value=0.0001, value=float(qty_default), step=0.01, format="%.4f", key=f"ops_dialog_qty_{tk_sel}_{evento_sel}")
                gross_in = c2.number_input(amount_label, min_value=0.01, value=float(gross_default), step=0.01, format="%.2f", key=f"ops_dialog_gross_{tk_sel}_{evento_sel}")
                quantita_op, prezzo_op, lordo_op = _compute_trade_triplet(calc_mode, quantita_in, 0.0, gross_in)
                c3.number_input("Prezzo calcolato", min_value=0.0, value=float(prezzo_op), step=0.01, format="%.4f", disabled=True, key=f"ops_dialog_price_calc_{tk_sel}_{evento_sel}")
            else:
                prezzo_in = c1.number_input("Prezzo", min_value=0.0001, value=float(price_default), step=0.01, format="%.4f", key=f"ops_dialog_price_{tk_sel}_{evento_sel}")
                gross_in = c2.number_input(amount_label, min_value=0.01, value=float(gross_default), step=0.01, format="%.2f", key=f"ops_dialog_gross_{tk_sel}_{evento_sel}")
                quantita_op, prezzo_op, lordo_op = _compute_trade_triplet(calc_mode, 0.0, prezzo_in, gross_in)
                c3.number_input("Quote calcolate", min_value=0.0, value=float(quantita_op), step=0.01, format="%.4f", disabled=True, key=f"ops_dialog_qty_calc_{tk_sel}_{evento_sel}")

            c4, c5 = st.columns(2)
            comm_op = c4.number_input("Commissioni €", min_value=0.0, step=0.5, format="%.2f", key=f"ops_dialog_comm_{tk_sel}_{evento_sel}")
            tax_op = c5.number_input("Imposte €", min_value=0.0, step=0.5, format="%.2f", key=f"ops_dialog_tax_{tk_sel}_{evento_sel}")
            note_op = st.text_input("Note", value=_default_note, key=f"ops_dialog_note_{tk_sel}_{evento_sel}")
            netto_op = -(lordo_op + comm_op + tax_op) if evento_sel == "ACQUISTO" else (lordo_op - comm_op - tax_op)
            st.caption(
                f"Quote: **{fmt_qty_it(quantita_op, 4)}** · Prezzo: **{fmt_eur_it(prezzo_op, 4)}** · "
                f"Controvalore: **{fmt_eur_it(lordo_op, 2)}** · Effetto cassa: **{fmt_eur_it(netto_op, 2, signed=True)}**"
            )

            if st.button("✅ Registra operazione", width="stretch", key=f"ops_dialog_submit_{tk_sel}_{evento_sel}"):
                actual_qty = qty_disp if (vendi_tutto and evento_sel in {"VENDITA", "RIMBORSO A SCADENZA"} and qty_disp > 0) else quantita_op
                if vendi_tutto and calc_mode == "prezzo_importo":
                    actual_lordo = lordo_op
                    prezzo_op = (actual_lordo / actual_qty) if actual_qty > 0 else prezzo_op
                else:
                    actual_lordo = actual_qty * prezzo_op
                actual_netto = -(actual_lordo + comm_op + tax_op) if evento_sel == "ACQUISTO" else (actual_lordo - comm_op - tax_op)
                try:
                    validate_date(data_sel)
                    validate_quantity(float(actual_qty), evento_sel, float(qty_disp))
                    validate_price(float(prezzo_op), strum_sel.get("tipo"))
                    validate_number_input(float(actual_lordo), 0.01, 1_000_000_000.0)
                    validate_number_input(float(comm_op), 0.0, 1_000_000.0)
                    validate_number_input(float(tax_op), 0.0, 1_000_000.0)
                    if evento_sel == "ACQUISTO" and auto_liq:
                        importo_versa = actual_lordo + comm_op + tax_op
                        append_evento_portafoglio(data, {
                            "event_id": _new_event_id(data),
                            "data": str(data_sel),
                            "ticker": "",
                            "tipo_evento": "VERSAMENTO",
                            "importo_lordo": importo_versa,
                            "importo_netto": importo_versa,
                            "note": f"Versamento automatico per acquisto {tk_sel}",
                        })
                    append_evento_portafoglio(data, {
                        "event_id": _new_event_id(data),
                        "data": str(data_sel),
                        "ticker": tk_sel,
                        "tipo_evento": evento_sel,
                        "quantita": actual_qty,
                        "prezzo_unitario": prezzo_op,
                        "importo_lordo": actual_lordo,
                        "commissioni": comm_op,
                        "imposte": tax_op,
                        "importo_netto": actual_netto,
                        "ignore_cash_check": bool(auto_liq),
                        "note": note_op,
                    })
                    if evento_sel == "RIMBORSO A SCADENZA" or (
                        evento_sel == "VENDITA" and actual_qty >= qty_disp - 1e-9  # tolleranza float
                    ):
                        _tipo_sel = next((s.get("tipo","") for s in data.get("strumenti",[]) if s.get("ticker")==tk_sel), "")
                        # GOV → chiuso definitivamente; ETF/ETC/FND → osservato (tornano monitorabili)
                        _stato_post_chiusura = "chiuso" if macro_cat(_tipo_sel) == "GOV" else "osservato"
                        _set_stato_strumento(data, tk_sel, _stato_post_chiusura, str(data_sel), evento_sel)
                    elif evento_sel == "ACQUISTO":
                        strum_cur = next(
                            (s for s in data.get("strumenti", []) if s.get("ticker") == tk_sel), {}
                        )
                        if strum_cur.get("stato") == "chiuso":
                            _set_stato_strumento(data, tk_sel, "aperto")
                    save_data(data)
                    logger.info(
                        "Operazione registrata: evento=%s ticker=%s quantita=%.4f netto=%.2f auto_liq=%s",
                        evento_sel,
                        tk_sel,
                        float(actual_qty),
                        float(actual_netto),
                        bool(auto_liq),
                    )
                    queue_success("Operazione registrata")
                    invalidate_portfolio_cache("operazione o movimento registrato")
                    st.rerun()
                except ValueError as e:
                    logger.warning("Validazione operazione fallita: evento=%s ticker=%s errore=%s", evento_sel, tk_sel, e)
                    st.error(str(e))
        else:
            lordo_pr = st.number_input("Importo lordo €", min_value=0.0, step=0.01, format="%.2f", key=f"ops_dialog_lordo_{tk_sel}_{evento_sel}")
            default_aliq = 12.5 if evento_sel == "CEDOLA" and macro_cat(strum_sel.get("tipo", "")) == "GOV" else 26.0
            aliq_pr = st.number_input("Aliquota imposta %", min_value=0.0, max_value=100.0, value=float(default_aliq), step=0.5, format="%.1f", key=f"ops_dialog_aliq_{tk_sel}_{evento_sel}")
            imposta_pr = lordo_pr * aliq_pr / 100.0
            netto_pr = lordo_pr - imposta_pr
            note_pr = st.text_input("Note", value=_default_note, key=f"ops_dialog_note_prov_{tk_sel}_{evento_sel}")
            st.caption(f"Imposta: **{fmt_eur_it(imposta_pr, 2)}** · Netto: **{fmt_eur_it(netto_pr, 2)}**")

            if st.button("✅ Registra provento", width="stretch", key=f"ops_dialog_submit_prov_{tk_sel}_{evento_sel}"):
                try:
                    validate_date(data_sel)
                    validate_number_input(float(lordo_pr), 0.01, 1_000_000_000.0)
                    validate_number_input(float(aliq_pr), 0.0, 100.0)
                    append_evento_portafoglio(data, {
                        "event_id": _new_event_id(data),
                        "data": str(data_sel),
                        "ticker": tk_sel,
                        "tipo_evento": evento_sel,
                        "importo_lordo": lordo_pr,
                        "imposte": imposta_pr,
                        "aliquota": aliq_pr / 100.0,
                        "importo_netto": netto_pr,
                        "note": note_pr,
                    })
                    save_data(data)
                    logger.info(
                        "Provento registrato: evento=%s ticker=%s lordo=%.2f netto=%.2f",
                        evento_sel,
                        tk_sel,
                        float(lordo_pr),
                        float(netto_pr),
                    )
                    queue_success("Provento registrato")
                    invalidate_portfolio_cache("operazione o movimento registrato")
                    st.rerun()
                except ValueError as e:
                    logger.warning("Validazione provento fallita: evento=%s ticker=%s errore=%s", evento_sel, tk_sel, e)
                    st.error(str(e))
    else:
        evento_cash = st.selectbox("Movimento", ["VERSAMENTO", "PRELIEVO", "COMMISSIONE", "IMPOSTA"], key="ops_dialog_cash")
        with st.form(f"form_cash_dialog_{evento_cash}"):
            data_cash = st.date_input("Data", value=date.today(), format="DD/MM/YYYY")
            importo_cash = st.number_input("Importo €", min_value=0.0, step=0.01, format="%.2f")
            tk_cash = st.selectbox("Strumento (facoltativo)", [""] + tks_ops if evento_cash in {"COMMISSIONE", "IMPOSTA"} else [""])
            note_cash = st.text_input("Note")
            netto_cash = importo_cash if evento_cash == "VERSAMENTO" else -importo_cash
            st.caption(f"Effetto cassa: **{fmt_eur_it(netto_cash, 2, signed=True)}**")

            if st.form_submit_button("✅ Registra movimento", width="stretch"):
                try:
                    validate_date(data_cash)
                    validate_number_input(float(importo_cash), 0.01, 1_000_000_000.0)
                    append_evento_portafoglio(data, {
                        "event_id": _new_event_id(data),
                        "data": str(data_cash),
                        "ticker": tk_cash,
                        "tipo_evento": evento_cash,
                        "importo_lordo": importo_cash,
                        "importo_netto": netto_cash,
                        "note": note_cash,
                    })
                    save_data(data)
                    logger.info(
                        "Movimento cassa registrato: evento=%s ticker=%s importo=%.2f netto=%.2f",
                        evento_cash,
                        tk_cash or "-",
                        float(importo_cash),
                        float(netto_cash),
                    )
                    queue_success("Movimento registrato")
                    invalidate_portfolio_cache("operazione o movimento registrato")
                    st.rerun()
                except ValueError as e:
                    logger.warning("Validazione movimento cassa fallita: evento=%s ticker=%s errore=%s", evento_cash, tk_cash or "-", e)
                    st.error(str(e))

@st.fragment
def render_batch_operations_fragment(
    data: dict,
    ctx: SimpleNamespace,
    theme,
    batch_max_rows: int,
) -> None:
    """
    Fragment interattivo per batch editing operazioni.
    Gestisce: modifica live, calcolo automatico, duplica, cancella, ordina, preset.
    Validazione e salvataggio rimangono nella funzione principale.

    Args:
        data: Portafoglio completo
        ctx: PageContext con da, settings, etc.
        theme: Tema applicativo corrente
        batch_max_rows: Numero di righe batch (default 10)
    """
    batch_key = "operations_batch_rows"
    batch_editor_key = "operations_batch_editor"

    # Inizializzazione session_state se non esiste
    if batch_key not in st.session_state or len(st.session_state.get(batch_key, [])) != batch_max_rows:
        st.session_state[batch_key] = _default_batch_rows(batch_max_rows)

    # Tabella editor interattiva
    # Legge e scrive direttamente su session_state[batch_key]
    render_section_title(
        "Editor operazioni",
        comment="Compila o correggi i campi dell'evento selezionato prima del salvataggio nel registro.",
        icon="operations",
        gap_after="xs",
    )

    # Radio per ordinamento
    st.markdown("**Ordina per**")
    sort_mode = st.radio(
        "Ordinamento righe",
        ["Nessun ordine", "Data (↑)", "Data (↓)", "Evento", "Ticker"],
        horizontal=True,
        key="batch_sort_mode_v1",
        label_visibility="collapsed",
    )

    # Applica ordinamento a batch_rows PRIMA di passare a data_editor
    batch_df_sorted = st.session_state[batch_key].copy()

    if sort_mode == "Data (↑)":
        batch_df_sorted = batch_df_sorted.sort_values("Data", na_position="last", ascending=True, ignore_index=True)
    elif sort_mode == "Data (↓)":
        batch_df_sorted = batch_df_sorted.sort_values("Data", na_position="last", ascending=False, ignore_index=True)
    elif sort_mode == "Evento":
        batch_df_sorted = batch_df_sorted.sort_values("Evento", na_position="last", ignore_index=True)
    elif sort_mode == "Ticker":
        batch_df_sorted = batch_df_sorted.sort_values("Ticker", na_position="last", ignore_index=True)
    # else: "Nessun ordine" — rimani ordinamento originale

    tks_ops = [s["ticker"] for s in data.get("strumenti", []) if s.get("stato", "aperto") != "chiuso"]
    batch_df = st.data_editor(
        batch_df_sorted,
        hide_index=True,
        width="stretch",
        num_rows="fixed",
        key=batch_editor_key,
        column_config={
            "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
            "Evento": st.column_config.SelectboxColumn(
                "Evento",
                options=["", "ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA", "CEDOLA", "DIVIDENDO", "VERSAMENTO", "PRELIEVO", "COMMISSIONE", "IMPOSTA"],
                width="medium",
            ),
            "Ticker": st.column_config.SelectboxColumn(
                "Ticker",
                options=[""] + tks_ops,
                width="small"
            ),
            "Qtà": st.column_config.NumberColumn("Qtà", format="%.4f", min_value=0.0),
            "Prezzo": st.column_config.NumberColumn("Prezzo", format="%.4f", min_value=0.0),
            "Importo €": st.column_config.NumberColumn("Importo €", format="%.2f", min_value=0.0),
            "Comm €": st.column_config.NumberColumn("Comm €", format="%.2f", min_value=0.0),
            "Aliquota %": st.column_config.NumberColumn(
                "Aliquota",
                format="%.1f",
                min_value=0.0,
                max_value=100.0,
                help="Usata solo per cedole e dividendi. Se lasci 0, l'app usa l'aliquota standard."
            ),
            "Auto liq": st.column_config.CheckboxColumn("Auto liq"),
            "Note": st.column_config.TextColumn("Note", width="medium"),
        },
    )

    # Aggiorna session_state con i dati modificati
    st.session_state[batch_key] = batch_df.copy()

    # Calcolo automatico del terzo campo (live, senza rerun)
    # Dopo modifica di una cella, se 2 di {Qtà, Prezzo, Importo} sono > 0, calcola il terzo

    for idx, row in batch_df.iterrows():
        evento = str(row.get("Evento", "") or "").strip()

        # Solo per ACQUISTO/VENDITA/RIMBORSO A SCADENZA
        if evento in {"ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA"}:
            qty = float(row.get("Qtà", 0.0) or 0.0)
            prezzo = float(row.get("Prezzo", 0.0) or 0.0)
            importo = float(row.get("Importo €", 0.0) or 0.0)

            # Conta quanti sono > 0
            positives = sum(1 for v in [qty, prezzo, importo] if v > 0)

            # Se esattamente 2, calcola il terzo
            if positives == 2:
                # Determina modalità di calcolo
                if qty > 0 and prezzo > 0:
                    mode = "quote_prezzo"
                elif qty > 0 and importo > 0:
                    mode = "quote_importo"
                else:  # prezzo > 0 and importo > 0
                    mode = "prezzo_importo"

                # Calcola il terzo campo
                qty_calc, prezzo_calc, importo_calc = _compute_trade_triplet(
                    mode, qty, prezzo, importo
                )

                # Aggiorna batch_df con il nuovo valore
                batch_df.at[idx, "Qtà"] = qty_calc
                batch_df.at[idx, "Prezzo"] = prezzo_calc
                batch_df.at[idx, "Importo €"] = importo_calc

    # Aggiorna session_state con i dati modificati (incluso calcolo automatico)
    st.session_state[batch_key] = batch_df.copy()

    st.caption("Regola pratica: il campo lasciato a 0 viene trattato come valore da ricavare, oppure come non rilevante per quel tipo di evento.")

    # ─── Funzioni vita quotidiana ───
    col_dup, col_del, col_space = st.columns([1, 1, 2])

    with col_dup:
        if st.button("📋 Duplica riga", key="batch_dup_btn"):
            # Trova l'ultima riga non vuota
            batch_df_current = st.session_state[batch_key]
            last_filled_idx = -1
            for idx in range(len(batch_df_current) - 1, -1, -1):
                row = batch_df_current.iloc[idx]
                if str(row.get("Evento", "")).strip():  # Se Evento non vuoto, riga è "filled"
                    last_filled_idx = idx
                    break

            # Se trovata una riga riempita, duplicala nella prossima riga vuota
            if last_filled_idx >= 0:
                last_row = batch_df_current.iloc[last_filled_idx].copy()

                # Trova prima riga vuota
                for idx in range(last_filled_idx + 1, len(batch_df_current)):
                    if not str(batch_df_current.iloc[idx].get("Evento", "")).strip():
                        # Copia last_row in questa riga vuota
                        for col in last_row.index:
                            batch_df_current.at[idx, col] = last_row[col]
                        break

            # Aggiorna session_state
            st.session_state[batch_key] = batch_df_current
            st.rerun()  # Triggera rerun del fragment (non della pagina intera)

    with col_del:
        if st.button("🗑️ Cancella riga", key="batch_del_btn"):
            # Rimuovi l'ultima riga non vuota
            batch_df_current = st.session_state[batch_key]

            for idx in range(len(batch_df_current) - 1, -1, -1):
                row = batch_df_current.iloc[idx]
                if str(row.get("Evento", "")).strip():  # Se Evento non vuoto
                    # Cancella il contenuto (reset a riga vuota)
                    default_row = _default_batch_rows(1).iloc[0]
                    for col in batch_df_current.columns:
                        batch_df_current.at[idx, col] = default_row[col]
                    break

            # Aggiorna session_state
            st.session_state[batch_key] = batch_df_current
            st.rerun()

    st.markdown("**Preset rapidi**")
    col_p1, col_p2, col_p3 = st.columns(3)

    with col_p1:
        if st.button("Acquisto BTP", key="batch_preset_btp"):
            # Riempi prima riga vuota con template ACQUISTO BTP
            batch_df_current = st.session_state[batch_key]
            for idx in range(len(batch_df_current)):
                if not str(batch_df_current.iloc[idx].get("Evento", "")).strip():
                    batch_df_current.at[idx, "Data"] = date.today()
                    batch_df_current.at[idx, "Evento"] = "ACQUISTO"
                    # Ticker lasciato vuoto (user lo sceglie dal selectbox)
                    batch_df_current.at[idx, "Auto liq"] = True
                    # Qtà, Prezzo, Importo rimangono 0 (user li compila)
                    break
            st.session_state[batch_key] = batch_df_current
            st.rerun()

    with col_p2:
        if st.button("Versamento mensile", key="batch_preset_versamento"):
            # Riempi prima riga vuota con template VERSAMENTO
            batch_df_current = st.session_state[batch_key]
            for idx in range(len(batch_df_current)):
                if not str(batch_df_current.iloc[idx].get("Evento", "")).strip():
                    batch_df_current.at[idx, "Data"] = date.today()
                    batch_df_current.at[idx, "Evento"] = "VERSAMENTO"
                    # Importo lasciato 0 (user lo compila)
                    break
            st.session_state[batch_key] = batch_df_current
            st.rerun()

    with col_p3:
        if st.button("Cedola standard", key="batch_preset_cedola"):
            # Riempi prima riga vuota con template CEDOLA (BTP standard = 12.5%)
            batch_df_current = st.session_state[batch_key]
            for idx in range(len(batch_df_current)):
                if not str(batch_df_current.iloc[idx].get("Evento", "")).strip():
                    batch_df_current.at[idx, "Data"] = date.today()
                    batch_df_current.at[idx, "Evento"] = "CEDOLA"
                    batch_df_current.at[idx, "Aliquota %"] = 12.5  # Default BTP
                    # Ticker e Importo lasciati vuoti (user li compila)
                    break
            st.session_state[batch_key] = batch_df_current
            st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# Carrello operazioni — componente custom (iframe lato client, zero rerun fino
# alla conferma finale). Affianca senza sostituire l'editor multiplo esistente.
# ─────────────────────────────────────────────────────────────────────────────

_OP_CART_COMPONENT = None


def _get_op_cart_component():
    """Dichiara (una sola volta) il componente custom del carrello operazioni."""
    global _OP_CART_COMPONENT
    if _OP_CART_COMPONENT is None:
        comp_dir = Path(__file__).resolve().parent / "_operazioni_component"
        _OP_CART_COMPONENT = components.declare_component("operation_entry_confirm_top_v1", path=str(comp_dir))
    return _OP_CART_COMPONENT



def _render_operation_entry_dialog_width() -> None:
    """Forza la larghezza del dialog Nuove operazioni.

    Senza questa regola il componente HTML entra in layout mobile/verticale.
    """
    st.markdown(
        """
        <style>
        div[data-testid="stDialog"] > div,
        div[data-testid="stDialog"] div[role="dialog"],
        div[data-testid="stDialog"] section {
            width: min(90vw, 800px) !important;
            max-width: min(90vw, 800px) !important;
        }
        div[data-testid="stDialog"] iframe {
            width: 100% !important;
            min-width: 0 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _op_cart_palette(theme) -> dict[str, str]:
    """Estrae dal tema applicativo la palette passata al componente."""
    def g(name: str, default: str) -> str:
        return str(getattr(theme, name, default) or default)

    colors = getattr(theme, "colors", {}) or {}
    return {
        "bg": g("bg_surface", "#ffffff"),
        "surface": str(colors.get("bg_surface_alt", g("bg_surface", "#f4f4f5"))),
        "border": g("border_color", "#d9d9de"),
        "font": g("font_color", "#1b1b1f"),
        "muted": g("color_gray", "#8a8a93"),
        "green": g("color_green", "#1f9d55"),
        "red": g("color_red", "#d64545"),
        "purple": g("color_purple", "#7c4dff"),
        "yellow": g("color_yellow", "#caa017"),
        "blue": g("color_blue", "#2f6fdb"),
        "orange": g("color_orange", "#e08a1e"),
    }


def _op_cart_tickers(data: dict[str, Any], ctx: SimpleNamespace) -> list[dict[str, Any]]:
    """Costruisce l'elenco strumenti con i dati necessari ai controlli lato client."""
    da = getattr(ctx, "da", None)
    out: list[dict[str, Any]] = []
    for s in data.get("strumenti", []):
        tk = s["ticker"]
        held = 0.0
        if da is not None and not getattr(da, "empty", True) and "Ticker" in getattr(da, "columns", []):
            row_sel = da[da["Ticker"] == tk]
            if not row_sel.empty:
                held = _safe_float(row_sel.iloc[0].get("Quote", 0))
        tipo = s.get("tipo", "")
        out.append({
            "ticker": tk,
            "nome": str(s.get("nome", tk) or tk),
            "held": float(held),
            "is_gov": macro_cat(tipo) == "GOV",
            "coupon": bool(_supports_coupon(data, tk)),
            "dividend": bool(_supports_dividend(data, tk)),
            "redemption": bool(_supports_redemption(data, tk)),
            "prezzo": float(_safe_float(s.get("prezzo", 0))),
        })
    return out


def _process_op_cart_items(
    data: dict[str, Any], ctx: SimpleNamespace, items: list[dict[str, Any]]
) -> tuple[int, list[dict[str, Any]]]:
    """
    Valida l'intero carrello e, solo in assenza di errori, registra ogni voce.
    Restituisce (numero voci registrate, elenco errori). In presenza di errori
    nessuna operazione viene scritta.
    """
    info_map = {s["ticker"]: s for s in data.get("strumenti", [])}
    da_ctx = getattr(ctx, "da", pd.DataFrame())
    qty_map: dict[str, float] = {}
    if (
        da_ctx is not None and not getattr(da_ctx, "empty", True)
        and "Ticker" in getattr(da_ctx, "columns", [])
        and "Quote" in getattr(da_ctx, "columns", [])
    ):
        qty_map = {
            str(r["Ticker"]): _safe_float(r.get("Quote", 0.0))
            for _, r in da_ctx.iterrows()
        }

    clean: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for i, raw in enumerate(items, start=1):
        evento = str(raw.get("evento", "") or "").strip()
        ticker = str(raw.get("ticker", "") or "").strip()
        note = str(raw.get("note", "") or "")
        try:
            if not evento:
                raise ValueError("evento mancante")
            data_str = str(raw.get("data", "") or "").strip()
            if not data_str:
                raise ValueError("data mancante")
            data_obj = date.fromisoformat(data_str)
            validate_date(data_obj)

            qty = float(raw.get("qty", 0.0) or 0.0)
            prezzo = float(raw.get("prezzo", 0.0) or 0.0)
            importo = float(raw.get("importo", 0.0) or 0.0)
            comm = float(raw.get("comm", 0.0) or 0.0)
            aliquota_pct = float(raw.get("aliquota", 0.0) or 0.0)
            auto_liq = bool(raw.get("auto_liq", False))

            if evento in {"ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA"}:
                if not ticker:
                    raise ValueError("ticker obbligatorio")
                positives = sum(1 for v in (qty, prezzo, importo) if v > 0)
                if positives != 2:
                    raise ValueError("compila esattamente 2 campi tra Qtà, Prezzo e Importo")
                mode = (
                    "quote_prezzo" if qty > 0 and prezzo > 0 else
                    "quote_importo" if qty > 0 and importo > 0 else
                    "prezzo_importo"
                )
                qty_op, prezzo_op, lordo_op = _compute_trade_triplet(mode, qty, prezzo, importo)
                validate_quantity(float(qty_op), evento, float(qty_map.get(ticker, 0.0)))
                validate_price(float(prezzo_op), info_map.get(ticker, {}).get("tipo"))
                validate_number_input(float(lordo_op), 0.01, 1_000_000_000.0)
                validate_number_input(float(comm), 0.0, 1_000_000.0)
                imposte_op = float(raw.get("imposte", 0.0) or 0.0) if evento == "RIMBORSO A SCADENZA" else 0.0
                validate_number_input(float(imposte_op), 0.0, 1_000_000.0)
                netto_op = -(lordo_op + comm + imposte_op) if evento == "ACQUISTO" else (lordo_op - comm - imposte_op)
                if evento == "ACQUISTO" and auto_liq:
                    clean.append({
                        "_kind": "auto_versa",
                        "data": str(data_obj),
                        "importo": lordo_op + comm + imposte_op,
                        "ticker": ticker,
                    })
                clean.append({
                    "_kind": "evento",
                    "data": str(data_obj),
                    "ticker": ticker,
                    "tipo_evento": evento,
                    "quantita": qty_op,
                    "prezzo_unitario": prezzo_op,
                    "importo_lordo": lordo_op,
                    "commissioni": comm,
                    "imposte": imposte_op,
                    "importo_netto": netto_op,
                    "ignore_cash_check": bool(auto_liq),
                    "note": note,
                })
            elif evento in {"CEDOLA", "DIVIDENDO"}:
                if not ticker:
                    raise ValueError("ticker obbligatorio")
                validate_number_input(float(importo), 0.01, 1_000_000_000.0)
                aliquota_eff = (
                    float(aliquota_pct) if float(aliquota_pct) > 0
                    else _default_tax_rate_pct(evento, ticker, info_map)
                )
                validate_number_input(float(aliquota_eff), 0.0, 100.0)
                imposte = importo * aliquota_eff / 100.0
                clean.append({
                    "_kind": "evento",
                    "data": str(data_obj),
                    "ticker": ticker,
                    "tipo_evento": evento,
                    "importo_lordo": importo,
                    "imposte": imposte,
                    "aliquota": aliquota_eff / 100.0,
                    "importo_netto": importo - imposte,
                    "note": note,
                })
            elif evento in {"VERSAMENTO", "PRELIEVO", "COMMISSIONE", "IMPOSTA"}:
                validate_number_input(float(importo), 0.01, 1_000_000_000.0)
                netto_cash = importo if evento == "VERSAMENTO" else -importo
                clean.append({
                    "_kind": "evento",
                    "data": str(data_obj),
                    "ticker": ticker if evento in {"COMMISSIONE", "IMPOSTA"} else "",
                    "tipo_evento": evento,
                    "importo_lordo": importo,
                    "importo_netto": netto_cash,
                    "note": note,
                })
            else:
                raise ValueError(f"evento non riconosciuto ({evento})")
        except Exception as exc:
            errors.append({"row": i, "msg": str(exc)})

    if errors:
        return 0, errors

    count = 0
    for payload in clean:
        if payload.get("_kind") == "auto_versa":
            append_evento_portafoglio(data, {
                "event_id": _new_event_id(data),
                "data": payload["data"],
                "ticker": "",
                "tipo_evento": "VERSAMENTO",
                "importo_lordo": payload["importo"],
                "importo_netto": payload["importo"],
                "note": f"Versamento automatico per acquisto {payload['ticker']}",
            })
        else:
            ev_payload = {k: v for k, v in payload.items() if k != "_kind"}
            ev_payload["event_id"] = _new_event_id(data)
            append_evento_portafoglio(data, ev_payload)
        count += 1
    save_data(data)
    return count, []


@st.dialog("➕ Nuove operazioni", width="large")
def nuove_operazioni_dialog(data: dict[str, Any], ctx: SimpleNamespace) -> None:
    """
    Popup di inserimento rapido: una riga di input con i relativi controlli,
    le voci si impilano come uno scontrino e vengono registrate tutte insieme
    alla conferma. Compilazione e impilamento avvengono lato client senza
    rerun; l'unico rerun è quello finale di registrazione.
    """
    _render_operation_entry_dialog_width()
    theme = get_theme_context()
    tickers = _op_cart_tickers(data, ctx)
    if not tickers:
        st.info("Aggiungi prima uno strumento dal relativo registro.")
        return

    component = _get_op_cart_component()
    # Usa st.container con larghezza massima per contenere il componente
    with st.container(border=False):
        result = component(
            tickers=tickers,
            palette=_op_cart_palette(theme),
            key="operation_entry_confirm_top_widget_v1",
            default=None,
        )

    errors_to_show = st.session_state.get("op_cart_errors")

    if isinstance(result, dict):
        nonce = result.get("nonce")
        if nonce and nonce != st.session_state.get("op_cart_nonce"):
            st.session_state["op_cart_nonce"] = nonce
            items = result.get("items") or []
            if not items:
                errors_to_show = ["Carrello vuoto: aggiungi almeno una voce prima di confermare."]
                st.session_state["op_cart_errors"] = errors_to_show
            else:
                count, errors = _process_op_cart_items(data, ctx, items)
                if errors:
                    errors_to_show = [f"Voce {e['row']}: {e['msg']}" for e in errors]
                    st.session_state["op_cart_errors"] = errors_to_show
                    for e in errors:
                        logger.warning(
                            "Carrello operazioni: voce %s non valida — %s", e["row"], e["msg"]
                        )
                else:
                    st.session_state.pop("op_cart_errors", None)
                    st.session_state.pop("op_cart_nonce", None)
                    invalidate_portfolio_cache("carrello operazioni registrato")
                    logger.info("Carrello operazioni registrato: %d voci", count)
                    queue_success(f"Registrate {count} operazioni/movimenti")
                    st.rerun()

    if errors_to_show:
        st.error(
            "Nessuna operazione registrata. Correggi le voci segnalate e premi di nuovo "
            "«Conferma e inserisci».\n\n" + "\n\n".join(errors_to_show)
        )



# ─────────────────────────────────────────────────────────────────────────────
# Centro Operativo — funzioni comuni e popup Streamlit
# ─────────────────────────────────────────────────────────────────────────────

PORTFOLIO_EVENT_TYPES = {"ACQUISTO", "VENDITA", "RIMBORSO A SCADENZA", "CEDOLA", "DIVIDENDO"}
CASH_EVENT_TYPES = {"VERSAMENTO", "PRELIEVO", "COMMISSIONE", "IMPOSTA"}




def _render_centro_operativo_dialog_style() -> None:
    """Stile compatto per popup gestionali del Centro Operativo."""
    st.markdown(
        """
        <style>
        div[data-testid="stDialog"] div[data-testid="stDataFrame"] {
            font-size: 0.82rem !important;
        }
        div[data-testid="stDialog"] label {
            font-size: 0.82rem !important;
        }
        div[data-testid="stDialog"] .stButton > button {
            min-height: 38px !important;
            border-radius: 12px !important;
            font-size: 0.88rem !important;
            font-weight: 700 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _fmt_event_date(value: Any) -> str:
    """Formatta date evento senza dipendere da variabili locali di render_operazioni."""
    try:
        return fmtds(value)
    except Exception:
        try:
            return fmt_dt_it(value)
        except Exception:
            return str(value or "—")



def _event_display_label(ev: dict[str, Any]) -> str:
    """Etichetta compatta per selezione/anteprima evento."""
    return (
        f"{_fmt_event_date(ev.get('data'))} | "
        f"{ev.get('tipo_evento', '—')} | "
        f"{ev.get('ticker') or '—'} | "
        f"{fmt_eur_it(ev.get('importo_netto', 0), 2, signed=True)}"
    )


def _render_event_preview(ev: dict[str, Any]) -> None:
    """Anteprima compatta evento prima di eliminazione.

    Non usa st.metric, perché nei dialog Streamlit genera caratteri enormi
    e valori troncati.
    """
    st.markdown(
        f"""
        <div style="
            border:1px solid rgba(148,163,184,0.35);
            border-radius:14px;
            padding:10px 12px;
            margin:8px 0 12px 0;
            background:rgba(248,250,252,0.75);
        ">
            <div style="
                display:grid;
                grid-template-columns:repeat(4,minmax(0,1fr));
                gap:8px;
                font-size:0.82rem;
                line-height:1.25;
            ">
                <div><div style="color:#64748b;font-size:0.70rem;font-weight:800;text-transform:uppercase;">Data</div><div style="font-weight:750;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{_fmt_event_date(ev.get("data"))}</div></div>
                <div><div style="color:#64748b;font-size:0.70rem;font-weight:800;text-transform:uppercase;">Evento</div><div style="font-weight:750;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{str(ev.get("tipo_evento", "—"))}</div></div>
                <div><div style="color:#64748b;font-size:0.70rem;font-weight:800;text-transform:uppercase;">Ticker</div><div style="font-weight:750;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{str(ev.get("ticker") or "—")}</div></div>
                <div><div style="color:#64748b;font-size:0.70rem;font-weight:800;text-transform:uppercase;">Netto</div><div style="font-weight:750;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{fmt_eur_it(ev.get("importo_netto", 0), 2, signed=True)}</div></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    details = {
        "Quantità": fmt_qty_it(ev.get("quantita", 0), 4),
        "Prezzo": fmt_eur_it(ev.get("prezzo_unitario", 0), 4),
        "Lordo": fmt_eur_it(ev.get("importo_lordo", 0), 2),
        "Commissioni": fmt_eur_it(ev.get("commissioni", 0), 2),
        "Imposte": fmt_eur_it(ev.get("imposte", 0), 2),
        "Note": str(ev.get("note", "") or "—"),
        "ID evento": str(ev.get("event_id", "—")),
    }

    dettagli_df = pd.DataFrame(
        [{"Campo": k, "Valore": v} for k, v in details.items()]
    )

    st.dataframe(
        dettagli_df,
        width="stretch",
        hide_index=True,
        height=285,
    )


def _rebuild_legacy_registers_after_event_delete(data: dict[str, Any]) -> None:
    """Ricostruisce registri legacy e registro liquidità dal registro_eventi."""
    data["operazioni"] = []
    data["proventi"] = []
    rebuilt = {"operazioni": [], "proventi": []}

    for ev in get_registro_eventi(data):
        tipo = ev.get("tipo_evento")
        if tipo in {"ACQUISTO", "VENDITA"}:
            rebuilt["operazioni"].append({
                "data": ev.get("data"),
                "ticker": ev.get("ticker", ""),
                "tipo": tipo,
                "qty": _safe_float(ev.get("quantita", 0)),
                "price": _safe_float(ev.get("prezzo_unitario", 0)),
                "comm": _safe_float(ev.get("commissioni", 0)),
                "note": ev.get("note", ""),
            })
        elif tipo in {"CEDOLA", "DIVIDENDO"}:
            lordo = _safe_float(ev.get("importo_lordo", 0))
            netto = _safe_float(ev.get("importo_netto", 0))
            aliquota = (
                (_safe_float(ev.get("imposte", 0)) / lordo)
                if lordo > 0
                else _safe_float(ev.get("aliquota", 0))
            )
            rebuilt["proventi"].append({
                "data": ev.get("data"),
                "ticker": ev.get("ticker", ""),
                "tipo": tipo,
                "importo_lordo": lordo,
                "aliquota": aliquota,
                "importo_netto": netto,
                "note": ev.get("note", ""),
            })

    data["operazioni"] = rebuilt["operazioni"]
    data["proventi"] = rebuilt["proventi"]
    data["registro_liquidita"] = _rebuild_cash_ledger_from_events(get_registro_eventi(data))


def _delete_event_by_id(data: dict[str, Any], event_id: str) -> bool:
    """Elimina un evento per ID e riallinea i registri derivati."""
    event_id = str(event_id or "")
    before = len(data.get("registro_eventi", []) or [])
    data["registro_eventi"] = [
        ev for ev in data.get("registro_eventi", [])
        if str(_normalize_event_record(ev).get("event_id", "")) != event_id
    ]
    after = len(data.get("registro_eventi", []) or [])

    if after == before:
        return False

    # TODO: se l'evento eliminato era VENDITA totale o RIMBORSO A SCADENZA, lo strumento
    # resta marcato "chiuso" anche se la posizione torna > 0. Known limitation.
    _rebuild_legacy_registers_after_event_delete(data)
    save_data(data)
    invalidate_portfolio_cache("eliminazione evento da Centro Operativo")
    return True


def _instrument_linked_events(data: dict[str, Any], ticker: str) -> list[dict[str, Any]]:
    return [ev for ev in get_registro_eventi(data) if str(ev.get("ticker", "") or "") == str(ticker or "")]


def _instrument_has_prices(data: dict[str, Any], ticker: str) -> bool:
    for prices in (data.get("storico_prezzi") or {}).values():
        if isinstance(prices, dict) and ticker in prices:
            return True
    return False


def _set_stato_strumento(
    data: dict[str, Any],
    ticker: str,
    stato: str,
    data_chiusura: Optional[str] = None,
    motivo_chiusura: Optional[str] = None,
) -> None:
    for s in data.get("strumenti", []):
        if s.get("ticker") == ticker:
            s["stato"] = stato
            if stato == "aperto":
                s["data_chiusura"] = None
                s["motivo_chiusura"] = None
            else:
                s["data_chiusura"] = data_chiusura
                s["motivo_chiusura"] = motivo_chiusura
            break


def _delete_instrument_if_safe(data: dict[str, Any], ticker: str) -> tuple[bool, str]:
    """Elimina solo anagrafica e storico prezzi se non ci sono eventi collegati."""
    linked = _instrument_linked_events(data, ticker)
    if linked:
        return False, f"Lo strumento ha {len(linked)} eventi collegati. Elimina prima gli eventi oppure mantieni lo strumento."

    before = len(data.get("strumenti", []) or [])
    data["strumenti"] = [s for s in data.get("strumenti", []) if str(s.get("ticker", "")) != ticker]
    after = len(data.get("strumenti", []) or [])

    if after == before:
        return False, "Strumento non trovato."

    for _, prices in (data.get("storico_prezzi") or {}).items():
        if isinstance(prices, dict):
            prices.pop(ticker, None)

    save_data(data)
    invalidate_portfolio_cache("eliminazione strumento da Centro Operativo")
    return True, "Strumento eliminato."


@st.dialog("📌 Strumenti")
def strumenti_dialog(data: dict[str, Any], ctx: SimpleNamespace) -> None:
    """Popup unico per aggiungere, modificare ed eliminare strumenti."""
    _render_centro_operativo_dialog_style()
    st.caption("Gestisci l'anagrafica degli strumenti da un unico punto. Le eliminazioni sono protette se esistono eventi collegati.")
    tab_add, tab_edit, tab_delete, tab_chiusi = st.tabs(["➕ Aggiungi", "✏️ Modifica", "🗑️ Elimina", "📁 Chiusi"])

    with tab_add:
        st.markdown("##### Aggiungi strumento")
        with st.form("centro_add_strumento_form"):
            isin = st.text_input("ISIN", max_chars=12).upper().strip()
            ticker_hint = st.text_input("Ticker manuale/opzionale").strip()
            st.caption("Per i BTP puoi completare o correggere scadenza, cedola e date nella scheda Modifica subito dopo l'inserimento.")
            submitted = st.form_submit_button("🔍 Cerca e aggiungi", width="stretch", type="primary")

        if submitted:
            if len(isin) != 12:
                st.error("L'ISIN deve avere 12 caratteri.")
            elif any(s.get("isin") == isin for s in data.get("strumenti", [])):
                st.warning("Strumento già presente.")
            else:
                with st.spinner("Ricerca dati strumento..."):
                    tk = ticker_hint or find_ticker(isin)
                    nm = find_name(isin)
                    tp = deduce_type(isin, tk, nm)
                    pr, src = get_price(isin, tk)
                data.setdefault("strumenti", []).append({
                    "isin": isin,
                    "ticker": tk,
                    "stato": "aperto",
                    "nome": nm or "—",
                    "tipo": tp,
                    "prezzo": pr,
                    "fonte": src,
                    "aggiornato": str(date.today()),
                    "scadenza": "",
                    "data_acquisto": "",
                    "prima_cedola": "",
                    "cedola_perc": 0.0,
                    "cedola_frequenza": "annuale",
                    "aliquota_cedola": 12.5,
                    "nominale": 100.0,
                })
                save_data(data)
                invalidate_portfolio_cache("aggiunta strumento da Centro Operativo")
                queue_success(f"Aggiunto {nm or tk}")
                st.rerun()

    with tab_edit:
        st.markdown("##### Modifica strumento")
        strumenti = data.get("strumenti", [])
        if not strumenti:
            st.info("Nessuno strumento presente.")
        else:
            labels = [
                f"{s.get('ticker', '—')} — {str(s.get('nome', ''))[:45]}"
                for s in strumenti
            ]
            idx = st.selectbox("Strumento", range(len(strumenti)), format_func=lambda i: labels[i], key="centro_edit_strumento_idx")
            se = strumenti[idx]
            is_btp_like = (
                str(se.get("tipo", "")).strip().lower() in {"btp", "titolo di stato"}
                or str(se.get("ticker", "")).upper().startswith("BTP-")
            )
            with st.form("centro_edit_strumento_form"):
                nome = st.text_input("Denominazione", value=se.get("nome", ""))
                tipo = st.text_input("Tipologia", value=se.get("tipo", ""))
                ticker_new = st.text_input("Ticker", value=se.get("ticker", ""))
                if is_btp_like:
                    st.caption("Dati BTP usati per timeline, cedole e scadenza.")
                    btp_col1, btp_col2 = st.columns(2)
                    with btp_col1:
                        scadenza = st.text_input("Scadenza (YYYY-MM-DD)", value=str(se.get("scadenza", "") or ""))
                        data_acquisto = st.text_input("Data acquisto (YYYY-MM-DD)", value=str(se.get("data_acquisto", "") or ""))
                        cedola_perc = st.number_input("Cedola % annua", min_value=0.0, step=0.05, value=float(se.get("cedola_perc", 0.0) or 0.0))
                    with btp_col2:
                        prima_cedola = st.text_input("Prima cedola (YYYY-MM-DD)", value=str(se.get("prima_cedola", se.get("data_origine", "")) or ""))
                        cedola_frequenza = st.selectbox(
                            "Frequenza cedola",
                            ["annuale", "semestrale", "trimestrale"],
                            index=["annuale", "semestrale", "trimestrale"].index(str(se.get("cedola_frequenza", "annuale") or "annuale").lower())
                            if str(se.get("cedola_frequenza", "annuale") or "annuale").lower() in {"annuale", "semestrale", "trimestrale"}
                            else 0,
                        )
                        aliquota_cedola = st.number_input("Aliquota cedola %", min_value=0.0, max_value=100.0, step=0.5, value=float(se.get("aliquota_cedola", 12.5) or 12.5))
                        nominale = st.number_input("Nominale per quota", min_value=0.0, step=1.0, value=float(se.get("nominale", 100.0) or 100.0))
                submitted = st.form_submit_button("💾 Salva modifiche", width="stretch", type="primary")

            if submitted:
                old = str(se.get("ticker", ""))
                ticker_new = ticker_new.strip()
                se["nome"] = nome
                se["tipo"] = tipo
                se["ticker"] = ticker_new
                if is_btp_like:
                    se["scadenza"] = scadenza.strip()
                    se["data_acquisto"] = data_acquisto.strip()
                    se["prima_cedola"] = prima_cedola.strip()
                    se["cedola_perc"] = float(cedola_perc or 0.0)
                    se["cedola_frequenza"] = str(cedola_frequenza or "annuale")
                    se["aliquota_cedola"] = float(aliquota_cedola or 0.0)
                    se["nominale"] = float(nominale or 0.0)
                if old and old != ticker_new:
                    for op in data.get("operazioni", []):
                        if op.get("ticker") == old:
                            op["ticker"] = ticker_new
                    for ev in data.get("registro_eventi", []):
                        if ev.get("ticker") == old:
                            ev["ticker"] = ticker_new
                    for _, prices in (data.get("storico_prezzi") or {}).items():
                        if isinstance(prices, dict) and old in prices:
                            prices[ticker_new] = prices.pop(old)
                save_data(data)
                invalidate_portfolio_cache("modifica strumento da Centro Operativo")
                queue_success("Strumento aggiornato.")
                st.rerun()

    with tab_delete:
        st.markdown("##### Elimina strumento")
        strumenti = data.get("strumenti", [])
        if not strumenti:
            st.info("Nessuno strumento presente.")
        else:
            tks = [s.get("ticker", "") for s in strumenti]
            tk = st.selectbox("Strumento da eliminare", tks, key="centro_delete_strumento_ticker")
            linked = _instrument_linked_events(data, tk)
            has_prices = _instrument_has_prices(data, tk)

            c1, c2, c3 = st.columns(3)
            c1.metric("Eventi collegati", len(linked))
            c2.metric("Storico prezzi", "sì" if has_prices else "no")
            c3.metric("Stato", "bloccato" if linked else "eliminabile")

            if linked:
                st.warning("Eliminazione bloccata: sono presenti eventi collegati. Elimina prima operazioni/proventi/movimenti riferiti a questo ticker.")
            else:
                confirm = st.checkbox("Confermo l'eliminazione dello strumento selezionato", key="centro_delete_strumento_confirm")
                if st.button("🗑️ Elimina strumento", width="stretch", type="primary", disabled=not confirm):
                    ok, msg = _delete_instrument_if_safe(data, tk)
                    if ok:
                        queue_success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

    with tab_chiusi:
        st.markdown("##### Strumenti chiusi")
        chiusi = [s for s in data.get("strumenti", []) if s.get("stato", "aperto") == "chiuso"]
        if not chiusi:
            st.info("Nessuno strumento chiuso.")
        else:
            df_chiusi = pd.DataFrame([{
                "Ticker": s.get("ticker", ""),
                "Nome": s.get("nome", ""),
                "Tipo": s.get("tipo", ""),
                "Chiuso il": s.get("data_chiusura", ""),
                "Motivo": s.get("motivo_chiusura", ""),
            } for s in chiusi])
            st.dataframe(df_chiusi, hide_index=True, use_container_width=True)


@st.dialog("📝 Operazioni di portafoglio")
def gestisci_operazioni_dialog(data: dict[str, Any], ctx: SimpleNamespace) -> None:
    """Popup per eliminare operazioni/proventi di portafoglio."""
    _render_centro_operativo_dialog_style()
    eventi = [ev for ev in get_registro_eventi(data) if ev.get("tipo_evento") in PORTFOLIO_EVENT_TYPES]
    if not eventi:
        st.info("Nessuna operazione di portafoglio da gestire.")
        return

    idx = st.selectbox(
        "Operazione da eliminare",
        range(len(eventi)),
        format_func=lambda i: _event_display_label(eventi[i]),
        key="centro_delete_port_event_idx",
    )
    ev = eventi[idx]
    _render_event_preview(ev)

    confirm = st.checkbox("Confermo l'eliminazione definitiva dell'operazione selezionata", key="centro_delete_port_event_confirm")
    if st.button("🗑️ Elimina operazione", width="stretch", type="primary", disabled=not confirm):
        if _delete_event_by_id(data, ev.get("event_id")):
            queue_success("Operazione eliminata.")
            st.rerun()
        else:
            st.error("Evento non trovato o già eliminato.")


@st.dialog("💵 Movimenti di liquidità")
def gestisci_liquidita_dialog(data: dict[str, Any], ctx: SimpleNamespace) -> None:
    """Popup per eliminare movimenti di liquidità."""
    _render_centro_operativo_dialog_style()
    eventi = [ev for ev in get_registro_eventi(data) if ev.get("tipo_evento") in CASH_EVENT_TYPES]
    if not eventi:
        st.info("Nessun movimento di liquidità da gestire.")
        return

    idx = st.selectbox(
        "Movimento da eliminare",
        range(len(eventi)),
        format_func=lambda i: _event_display_label(eventi[i]),
        key="centro_delete_cash_event_idx",
    )
    ev = eventi[idx]
    _render_event_preview(ev)

    confirm = st.checkbox("Confermo l'eliminazione definitiva del movimento selezionato", key="centro_delete_cash_event_confirm")
    if st.button("🗑️ Elimina movimento", width="stretch", type="primary", disabled=not confirm):
        if _delete_event_by_id(data, ev.get("event_id")):
            queue_success("Movimento eliminato.")
            st.rerun()
        else:
            st.error("Evento non trovato o già eliminato.")


def _render_centro_operativo(data: dict[str, Any], ctx: SimpleNamespace, theme) -> None:
    """Area unica di gestione operativa della scheda Operazioni."""
    render_section_title(
        "Centro Operativo",
        comment=(
            "Gestisci da qui inserimenti, strumenti, operazioni e movimenti di liquidità. "
            "La sidebar resta solo un accesso rapido, mentre le azioni operative sono concentrate in questa sezione."
        ),
        gap_after="xs",
    )

    c1, c2, c3, c4 = st.columns(4, gap="small")

    with c1:
        if st.button("➕ Nuove operazioni", key="centro_nuove_operazioni", type="primary", width="stretch"):
            nuove_operazioni_dialog(data, ctx)

    with c2:
        if st.button("📌 Strumenti", key="centro_strumenti", width="stretch"):
            strumenti_dialog(data, ctx)

    with c3:
        if st.button("📝 Operazioni", key="centro_operazioni", width="stretch"):
            gestisci_operazioni_dialog(data, ctx)

    with c4:
        if st.button("💵 Liquidità", key="centro_liquidita", width="stretch"):
            gestisci_liquidita_dialog(data, ctx)

    st.caption(
        "Le eliminazioni sono protette da anteprima e conferma. "
        "L'inserimento multiplo usa un componente dedicato senza ricaricamenti intermedi fino alla conferma finale."
    )


def _build_strumenti_chiusi_section(data: dict[str, Any]) -> None:
    """Renders closed-instrument summary at the bottom of the Operazioni page."""
    df_positions = compute_portfolio_state(data, include_closed=True).get("df", pd.DataFrame())
    if df_positions.empty:
        return
    df_chiusi_pos = df_positions[df_positions["Quote"] <= 0.0001]
    if df_chiusi_pos.empty:
        return
    # Strumenti con stato=="chiuso": GOV rimborsati/venduti definitivamente.
    chiusi_tickers = {
        str(s.get("ticker") or "")
        for s in data.get("strumenti", [])
        if s.get("stato") == "chiuso" and str(s.get("ticker") or "")
    }
    chiusi = [s for s in data.get("strumenti", []) if s.get("ticker") in chiusi_tickers]
    if not chiusi:
        return

    render_section_title(
        "Strumenti chiusi",
        comment=(
            "Riepilogo degli strumenti che hanno concluso il loro ciclo di vita nel portafoglio. "
            "I dati si riferiscono all'intero periodo di detenzione: "
            "P/L realizzato, cedole e dividendi incassati, imposte pagate, return totale."
        ),
        gap_after="xs",
    )

    # Derive first buy and closing event dates from the event log
    first_buy: dict[str, str] = {}
    last_close: dict[str, str] = {}
    close_motivo: dict[str, str] = {}
    for ev in get_registro_eventi(data):
        tk = str(ev.get("ticker", "") or "")
        tipo_ev = str(ev.get("tipo_evento", "") or "")
        if tipo_ev == "ACQUISTO" and tk and tk not in first_buy:
            first_buy[tk] = str(ev.get("data", "") or "")
        elif tipo_ev in ("VENDITA", "RIMBORSO A SCADENZA") and tk:
            last_close[tk] = str(ev.get("data", "") or "")
            close_motivo[tk] = tipo_ev

    theme = get_theme_context()
    rows = []
    for s in chiusi:
        ticker = str(s.get("ticker", "") or "")
        nome = str(s.get("nome", ticker) or ticker)
        tipo = macro_cat(str(s.get("tipo", "") or ""))
        data_apertura = fmtds(first_buy.get(ticker, "")) if first_buy.get(ticker) else "—"
        _close_date = last_close.get(ticker) or str(s.get("data_chiusura", "") or "")
        data_chius = fmtds(_close_date) if _close_date else "—"
        motivo = close_motivo.get(ticker) or str(s.get("motivo_chiusura", "") or "—")

        pos_row = df_positions[df_positions["Ticker"] == ticker] if not df_positions.empty else pd.DataFrame()
        if pos_row.empty:
            pl_netto = cedole = dividendi = imposte = 0.0
        else:
            r = pos_row.iloc[0]
            pl_netto = _safe_float(r.get("P/L Realizzato Netto", 0.0))
            cedole = _safe_float(r.get("Cedole nette", 0.0))
            dividendi = _safe_float(r.get("Dividendi netti", 0.0))
            imposte = _safe_float(r.get("Imposte €", 0.0))

        return_totale = pl_netto + cedole + dividendi
        rows.append({
            "Ticker": ticker,
            "Nome": nome,
            "Tipo": tipo,
            "Aperto il": data_apertura,
            "Chiuso il": data_chius,
            "Motivo": motivo,
            "P/L Realizzato €": pl_netto,
            "Cedole/Div. netti €": cedole + dividendi,
            "Imposte €": imposte,
            "Return Totale €": return_totale,
        })

    if not rows:
        return

    df_chiusi = pd.DataFrame(rows)

    def _style_chiusi(row):
        styles = []
        for col in row.index:
            s = ""
            if col == "Tipo":
                s = f"color:{macro_color(str(row['Tipo'] or ''))};font-weight:700;"
            elif col == "Return Totale €":
                try:
                    v = float(row[col])
                    c = theme.color_green if v >= 0 else theme.color_red
                    s = f"color:{c};font-weight:700;"
                except (TypeError, ValueError):
                    pass
            elif col in {"P/L Realizzato €", "Cedole/Div. netti €"}:
                try:
                    v = float(row[col])
                    c = theme.color_green if v >= 0 else theme.color_red
                    s = f"color:{c};font-weight:600;"
                except (TypeError, ValueError):
                    pass
            styles.append(s)
        return styles

    styled = df_chiusi.style.format({
        "P/L Realizzato €": lambda v: fmt_eur_it(v, 2, signed=True),
        "Cedole/Div. netti €": lambda v: fmt_eur_it(v, 2, signed=True),
        "Imposte €": lambda v: fmt_eur_it(v, 2),
        "Return Totale €": lambda v: fmt_eur_it(v, 2, signed=True),
    }).apply(_style_chiusi, axis=1)

    render_styled_table(styled, height="content")
    legend_block(
        "P/L Realizzato = differenza tra prezzo di rimborso/vendita e prezzo medio di carico, al netto di commissioni. "
        "Return Totale include anche cedole e dividendi netti incassati nel periodo di detenzione."
    )


def render_operazioni(tab: DeltaGenerator, ctx: SimpleNamespace) -> None:
    """
    Pure rendering for operazioni page (transaction log).
    All filtering is done by service functions.
    """
    data = ctx.data
    fmtds = ctx.fmtds
    settings = getattr(ctx, "settings", {}) if hasattr(ctx, "settings") else {}
    theme = get_theme_context()

    with tab:
        render_page_intro_shared(
            "Operazioni",
            "Centro operativo per inserire, correggere e consultare eventi di portafoglio, movimenti di cassa e anagrafica strumenti.",
            "operations",
            theme,
        )
        _render_centro_operativo(data, ctx, theme)

        operations = get_portfolio_operations(get_registro_eventi(data))

        # ─── Operazioni di portafoglio ──────────────────────────────
        render_section_title(
            t(settings, 'operations.portfolio_title', 'Registro operazioni di portafoglio'),
            comment=t(settings, "operations.portfolio_note", "Operazioni che incidono sulle posizioni del portafoglio: acquisti, vendite e rimborsi a scadenza."),
            gap_after="xs",
        )

        if operations:
            info_map = {s["ticker"]: s for s in data.get("strumenti", [])}
            dfp = pd.DataFrame(operations)

            # Build display columns
            dfp["Data"] = dfp["data"].apply(fmtds)
            dfp["Evento"] = dfp["tipo_evento"]
            dfp["Ticker"] = dfp["ticker"]
            dfp["Strumento"] = dfp["ticker"].map(
                lambda tk: (lambda n: n[:24] + "…" if len(n) > 24 else n)(
                    info_map.get(tk, {}).get("nome", tk)
                )
            )
            dfp["Tipo"] = dfp["ticker"].map(
                lambda tk: macro_cat(info_map.get(tk, {}).get("tipo", ""))
            ).fillna("")
            dfp["Qtà"] = pd.to_numeric(dfp.get("quantita", 0), errors="coerce")
            dfp["Prezzo €"] = pd.to_numeric(dfp.get("prezzo_unitario", 0), errors="coerce")
            dfp["Comm. €"] = pd.to_numeric(dfp.get("commissioni", 0), errors="coerce")
            dfp["Imposte €"] = pd.to_numeric(dfp.get("imposte", 0), errors="coerce")
            dfp["Netto €"] = pd.to_numeric(dfp.get("importo_netto", 0), errors="coerce")

            out = dfp[["Data", "Evento", "Ticker", "Strumento", "Tipo", "Qtà", "Prezzo €", "Comm. €", "Imposte €", "Netto €"]].copy()

            def _style_port(row):
                ev_color = {
                    "ACQUISTO": theme.color_green,
                    "VENDITA": theme.color_red,
                    "RIMBORSO A SCADENZA": theme.color_purple,
                }.get(str(row["Evento"]), theme.color_gray)
                cls_color = macro_color(row["Tipo"]) if row.get("Tipo") else None
                styles = []
                for col in row.index:
                    s = ""
                    if col == "Evento":
                        s += f"color:{ev_color};font-weight:700;"
                    if col in {"Ticker", "Tipo"} and cls_color:
                        s += f"color:{cls_color};font-weight:700;"
                    if col == "Strumento":
                        s += "font-weight:600;"
                    styles.append(s)
                return styles

            styled_port = out.style.format({
                "Qtà": lambda v: fmt_qty_it(v, 4),
                "Prezzo €": lambda v: fmt_eur_it(v, 4),
                "Comm. €": lambda v: fmt_eur_it(v, 2),
                "Imposte €": lambda v: fmt_eur_it(v, 2),
                "Netto €": lambda v: fmt_eur_it(v, 2, signed=True),
            }).apply(_style_port, axis=1)
            render_styled_table(styled_port, height=520)
        else:
            st.info(t(settings, "operations.portfolio_empty", "Nessuna operazione di portafoglio registrata."))

        # ─── Movimenti di liquidità ────────────────────────────────
        render_section_title(
            t(settings, 'operations.cash_title', 'Registro movimenti di liquidità'),
            comment=t(settings, "operations.cash_note", "Movimenti che incidono sulla cassa del portafoglio: versamenti, prelievi, vendite/rimborsi (entrate), acquisti (uscite), cedole, dividendi, commissioni e imposte."),
            gap_after="xs",
        )

        # Get pre-filtered cash movements from service
        cash_movements = get_cash_movements(get_registro_eventi(data))

        if cash_movements:
            info_map = {s["ticker"]: s for s in data.get("strumenti", [])}
            dfc = pd.DataFrame(cash_movements)

            # Build display columns
            dfc["Data"] = dfc["data"].apply(fmtds)
            dfc["Causale"] = dfc["tipo_evento"]
            dfc["Ticker"] = dfc["ticker"].fillna("")
            dfc["Strumento"] = dfc["ticker"].map(
                lambda tk: info_map.get(tk, {}).get("nome", tk) if tk else ""
            )
            dfc["Riferimento"] = dfc.apply(
                lambda r: (
                    f"{r['Ticker']} — {r['Strumento']}"
                    if str(r.get("Ticker", "")).strip() and str(r.get("Strumento", "")).strip()
                    else (str(r.get("Ticker", "")).strip() or str(r.get("Strumento", "")).strip() or "—")
                ),
                axis=1,
            )
            dfc["Lordo"] = pd.to_numeric(dfc.get("importo_lordo", 0), errors="coerce")
            dfc["Imposte"] = pd.to_numeric(dfc.get("imposte", 0), errors="coerce")
            dfc["Netto cassa"] = pd.to_numeric(dfc.get("importo_netto", 0), errors="coerce")
            dfc["Note"] = dfc.get("note", "")

            outc = dfc[["Data", "Causale", "Riferimento", "Lordo", "Imposte", "Netto cassa", "Note"]].copy()

            def _style_cash(row):
                ev_color = {
                    "VERSAMENTO": theme.color_green,
                    "PRELIEVO": theme.color_red,
                    "CEDOLA": theme.color_purple,
                    "DIVIDENDO": theme.color_yellow,
                    "COMMISSIONE": theme.color_gray,
                    "IMPOSTA": theme.color_gray,
                    "VENDITA": theme.color_blue,
                    "RIMBORSO A SCADENZA": theme.color_orange,
                    "ACQUISTO": theme.color_orange,
                }.get(str(row["Causale"]), theme.color_gray)
                styles = []
                for col in row.index:
                    s = ""
                    if col == "Causale":
                        s += f"color:{ev_color};font-weight:700;"
                    if col == "Riferimento" and str(row.get("Riferimento", "")).strip() not in {"", "—"}:
                        s += "font-weight:600;"
                    styles.append(s)
                return styles

            styled_cash = outc.style.format({
                "Lordo": lambda v: fmt_eur_it(v, 2),
                "Imposte": lambda v: fmt_eur_it(v, 2),
                "Netto cassa": lambda v: fmt_eur_it(v, 2, signed=True),
            }).apply(_style_cash, axis=1)
            render_styled_table(styled_cash, height=520)
        else:
            st.info(t(settings, "operations.cash_empty", "Nessun movimento di liquidità registrato."))

        # ─── Strumenti chiusi ──────────────────────────────────────
        _build_strumenti_chiusi_section(data)

        back_to_top(show_prev=True, show_next=True, nav_key="operazioni")
