"""ui/form_server/strumenti.py — pagina "Strumenti" del form-server (route
/strumenti): anagrafica, arricchimento (auto/PDF/manuale), storico prezzi.

Estratto da form_server.py. Condivide la stessa pipeline di storage dell'app
principale: nessuna logica duplicata.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from html import escape
from typing import Optional

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from ui.form_server.shell import CSS, STREAMLIT_URL, TAB_JS

logger = logging.getLogger("portafoglio.form_server.strumenti")

router = APIRouter()


# ─── Helpers dominio ──────────────────────────────────────────────────────────

def _fs_linked_events(data: dict, ticker: str) -> list:
    from persistence.storage import get_registro_eventi
    return [ev for ev in get_registro_eventi(data) if str(ev.get("ticker", "") or "") == str(ticker or "")]


def _fs_has_prices(data: dict, ticker: str) -> bool:
    for prices in (data.get("storico_prezzi") or {}).values():
        if isinstance(prices, dict) and ticker in prices:
            return True
    return False


def _fs_delete_instrument(data: dict, ticker: str) -> tuple:
    from persistence.storage import save_data
    linked = _fs_linked_events(data, ticker)
    if linked:
        return False, f"Lo strumento ha {len(linked)} eventi collegati. Elimina prima gli eventi oppure mantieni lo strumento."
    before = len(data.get("strumenti", []) or [])
    data["strumenti"] = [s for s in data.get("strumenti", []) if str(s.get("ticker", "")) != ticker]
    if len(data.get("strumenti", [])) == before:
        return False, "Strumento non trovato."
    for _, prices in (data.get("storico_prezzi") or {}).items():
        if isinstance(prices, dict):
            prices.pop(ticker, None)
    save_data(data)
    return True, "Strumento eliminato."


def _fs_backfill_storico(data: dict, ticker: str, since: str | None = None) -> tuple:
    """Scarica lo storico prezzi completo da Yahoo e lo integra senza sovrascrivere
    le date gia' presenti (vedi core.market_data.backfill_storico_prezzi). Se since
    e' indicato, importa solo dalla data indicata in poi: l'utente decide il
    perimetro invece di ricevere automaticamente tutto cio' che Yahoo restituisce."""
    from persistence.storage import save_data
    from core.market_data import get_yahoo_price_history_full, backfill_storico_prezzi
    from core.formatting import fmt_date_only_it

    history = get_yahoo_price_history_full(ticker)
    if not history:
        return False, f"Nessuno storico disponibile su Yahoo per {ticker}."
    added = backfill_storico_prezzi(data.setdefault("storico_prezzi", {}), ticker, history, since=since)
    save_data(data)
    perimetro = f" dal {fmt_date_only_it(since)} in poi" if since else ""
    if added:
        return True, f"{ticker}: aggiunte {added} date{perimetro} (su {len(history)} disponibili su Yahoo)."
    return True, f"{ticker}: nessuna data mancante{perimetro}."


def _fs_arricchisci_strumento(data: dict, ticker: str) -> tuple:
    """Recupera dati finanziari aggiuntivi per un singolo strumento (YTM, TER,
    benchmark, composizione, a seconda della categoria) e salva."""
    from persistence.storage import save_data
    from core.instrument_enrichment import enrich_strumento

    strumento = next((s for s in (data.get("strumenti") or []) if s.get("ticker") == ticker), None)
    if strumento is None:
        return False, f"Strumento '{ticker}' non trovato."
    enrich_strumento(strumento)
    save_data(data)
    if strumento.get("enrichment_error"):
        return False, f"{ticker}: {strumento['enrichment_error']}"
    return True, f"{ticker}: arricchimento completato."


def _fs_category_field_specs(cat: str) -> list:
    """(label, nome campo, placeholder) per categoria — usati nel form di
    modifica manuale dati completi (tab Arricchimento in Strumenti)."""
    if cat == "btp":
        return [
            ("YTM Netto", "ytm_netto", "es. 2,27%"), ("YTM Lordo", "ytm_lordo", "es. 2,89%"),
            ("Duration Modificata", "duration_modificata", "es. 0,09"), ("Scadenza", "scadenza", "es. 01/08/2026"),
            ("Cedola Annuale", "cedola_annuale", "es. 0,00%"), ("Frequenza Cedola", "cedola_frequenza", "es. Semestrale"),
            ("Tipo Cedola", "tipo_cedola", "es. FISSO"), ("Prossima Cedola", "prossima_cedola", "es. 01/08/2026"),
            ("Rateo Lordo", "rateo_lordo", ""), ("Rateo Netto", "rateo_netto", ""),
            ("Rating Emittente", "rating_emittente", "es. BBB+"), ("Data Emissione", "data_emissione", ""),
            ("Prezzo Emissione", "prezzo_emissione", ""), ("Prezzo Rimborso", "prezzo_rimborso", ""),
            ("Rateo Interessi", "rateo_interessi", ""), ("Rateo Disagio", "rateo_disaggio", ""),
            ("Ritenute Totali", "ritenute_totali", ""),
            ("Natura", "natura", "es. Fattore qualità"),
        ]
    if cat in ("etf", "etc"):
        return [
            ("TER", "ter", "es. 0,40%"),
            ("Zero commissioni", "zero_commissioni", "spunta se su Fineco lo compri senza commissioni"),
            ("Spread %", "spread_pct", "es. 0,05% (facoltativo)"),
            ("Benchmark", "benchmark", "es. FTSE MIB NR EUR"),
            ("Categoria", "categoria_etf", "es. Italy Equity"), ("Emittente", "emittente", "es. Amundi Asset Management"),
            ("Rating Morningstar (stelle)", "rating_morningstar", "es. 4"),
            ("Rendimento 1A", "rendimento_1a", "es. +37,30%"), ("Rendimento 3A", "rendimento_3a", "es. +117,68%"),
            ("Beta", "beta", "es. 1,05"), ("Deviazione Standard", "deviazione_std", "es. 13,00%"),
            ("Indice di Sharpe", "sharpe", "es. 2,00"), ("VaR", "var", "es. 35,61"),
            ("Distribuzione", "distribuzione", "es. Distribuzione"), ("Fiscalità", "fiscalita", "es. Armonizzato"),
            ("Data Lancio", "data_lancio", "es. 03/11/2003"),
            ("Natura", "natura", "es. Fattore qualità"),
        ]
    return [
        ("TER / Commissione Gestione", "ter", "es. 1,84%"),
        ("Categoria (Morningstar)", "categoria_fam", "es. Bilanciati Flessibili EUR"),
        ("Rating Morningstar (stelle)", "rating_morningstar", "es. 3"),
        ("Livello Rischio (1-7)", "livello_rischio", "es. 4"),
        ("Rendimento YTD", "rendimento_ytd", "es. 4,47%"), ("Rendimento 1A", "rendimento_1a", "es. 11,85%"),
        ("Rendimento 3A", "rendimento_3a", "es. 26,52%"),
        ("% Azionario", "composizione_az", "es. 60,50%"), ("% Obbligazionario", "composizione_obbl", "es. 20,40%"),
        ("% Liquidità", "composizione_liq", "es. 18,90%"),
        ("Valuta NAV", "valuta", "es. EUR"), ("Max 52 Settimane", "max_52w", "es. 145,26"),
        ("Min 52 Settimane", "min_52w", "es. 130,51"), ("Data Lancio", "data_lancio", "es. 27/11/2018"),
        ("Patrimonio", "patrimonio", "es. 422,73 Mln. EUR"),
        ("Natura", "natura", "es. Fattore qualità"),
    ]


def _fs_render_dati_completi_fields(strumento: dict) -> str:
    """Form dei campi arricchimento per lo strumento, precompilati con badge fonte
    (Auto/PDF/Manuale), per la modifica manuale nella tab Arricchimento."""
    from core.instrument_enrichment import _categoria
    cat = _categoria(strumento.get("tipo", ""))
    src = strumento.get("enrichment_source") or {}
    colors = {"auto": "#0ea5e9", "pdf": "#8b5cf6", "manuale": "#f59e0b"}
    labels = {"auto": "Auto", "pdf": "PDF", "manuale": "Manuale"}

    def _badge(field: str) -> str:
        s = src.get(field, "")
        if not s:
            return ""
        c = colors.get(s, "#94a3b8")
        lb = labels.get(s, s)
        return f'<span style="font-size:10px;padding:1px 6px;border-radius:9px;background:{c};color:#fff;margin-left:6px;">{lb}</span>'

    rows = []
    for label, name, placeholder in _fs_category_field_specs(cat):
        val = strumento.get(name, "")
        if name == "zero_commissioni":
            checked = "checked" if str(val).strip().lower() in ("true", "si", "sì", "1", "yes") else ""
            rows.append(
                f'<div style="margin-bottom:10px;">'
                f'<label style="font-size:12px;font-weight:600;color:#64748b;">{escape(label)}{_badge(name)}</label>'
                f'<label style="display:flex;align-items:center;gap:8px;margin-top:5px;cursor:pointer;font-size:13px;color:#334155;">'
                f'<input type="hidden" name="{name}" value="false">'
                f'<input type="checkbox" name="{name}" value="true" {checked} '
                f'style="width:16px;height:16px;accent-color:#6366f1;">'
                f'{escape(placeholder)}'
                f'</label>'
                f'</div>'
            )
            continue
        rows.append(
            f'<div style="margin-bottom:10px;">'
            f'<label style="font-size:12px;font-weight:600;color:#64748b;">{escape(label)}{_badge(name)}</label>'
            f'<input name="{name}" value="{escape(str(val or ""))}" placeholder="{escape(placeholder)}" '
            f'style="width:100%;padding:6px 10px;border:1px solid #e2e8f0;border-radius:6px;font-size:13px;margin-top:3px;box-sizing:border-box;">'
            f'</div>'
        )
    return "".join(rows)


def _fs_parse_flex_date(value: str) -> str:
    """Converte una data GG/MM/AAAA o YYYY-MM-DD in ISO YYYY-MM-DD. Stringa vuota -> vuota.

    Solleva ValueError (messaggio gia' in italiano) se il formato non e' riconosciuto.
    """
    value = (value or "").strip()
    if not value:
        return ""
    from core.validators import validate_date
    return validate_date(value).isoformat()


def _fs_resolve_strumento_scelto(form_values: dict, n_candidati: int) -> dict:
    """Dai campi del form di conferma aggiunta strumento (candidato scelto per
    indice, o inserimento manuale), restituisce i valori da salvare."""
    scelta = str(form_values.get("scelta", "")).strip()
    if scelta != "manuale" and n_candidati > 0:
        try:
            idx = int(scelta)
        except ValueError:
            idx = 0
        idx = max(0, min(idx, n_candidati - 1))
        prezzo_raw = str(form_values.get(f"cand_{idx}_prezzo", "")).strip()
        try:
            prezzo = float(prezzo_raw) if prezzo_raw else None
        except ValueError:
            prezzo = None
        return {
            "ticker": str(form_values.get(f"cand_{idx}_ticker", "")).strip(),
            "nome": str(form_values.get(f"cand_{idx}_nome", "")).strip(),
            "tipo": str(form_values.get(f"cand_{idx}_tipo", "")).strip(),
            "prezzo": prezzo,
            "fonte": str(form_values.get(f"cand_{idx}_fonte", "")).strip(),
        }
    return {
        "ticker": str(form_values.get("manuale_ticker", "")).strip(),
        "nome": str(form_values.get("manuale_nome", "")).strip(),
        "tipo": str(form_values.get("manuale_tipo", "")).strip(),
        "prezzo": None,
        "fonte": "Manuale",
    }


def _fs_apply_enrichment_if_eligible(isin: str, tk: str, nm: str, tp: str, fonte: str) -> dict:
    """Se lo strumento non e' un BTP e la scelta non e' manuale, arricchisce da
    justETF e ricalcola il tipo dal focus_etf se disponibile. Restituisce sempre
    almeno {'tipo': ..., 'natura': ...}, piu' gli eventuali campi di
    arricchimento riusciti da unire al record dello strumento salvato. Nessuna
    chiamata di rete se non ammissibile; nessun campo aggiuntivo se
    l'arricchimento fallisce."""
    from core.instrument_classification import classify_natura

    if isin.upper().startswith("IT") or fonte == "Manuale":
        natura = classify_natura({"isin": isin, "ticker": tk, "nome": nm, "tipo": tp})
        return {"tipo": tp, "natura": natura}

    from core.instrument_enrichment import enrich_etf_etc
    result = enrich_etf_etc({"isin": isin, "ticker": tk})
    if result.get("enrichment_error"):
        natura = classify_natura({"isin": isin, "ticker": tk, "nome": nm, "tipo": tp})
        return {"tipo": tp, "natura": natura}

    focus = result.get("focus_etf", "")
    new_tipo = tp
    if focus:
        from core.market_data import deduce_type
        new_tipo = deduce_type(isin, tk, nm, focus_etf=focus) or tp

    extra = {k: v for k, v in result.items() if k not in ("isin", "ticker", "enrichment_error")}
    natura = classify_natura({"isin": isin, "ticker": tk, "nome": nm, "tipo": new_tipo, **extra})
    return {"tipo": new_tipo, "natura": natura, **extra}


def _fs_resolve_price_and_enrichment(scelto: dict, isin: str, tk: str, nm: str, tp: str) -> tuple:
    """Risolve prezzo e fonte per il nuovo strumento (con fallback su
    ``get_price`` quando la scelta non ha gia' un prezzo, es. inserimento
    manuale) e applica l'arricchimento automatico eleggibile.

    Importante: la fonte usata come guardia per l'arricchimento (parametro
    ``fonte`` di `_fs_apply_enrichment_if_eligible`) e' la fonte ORIGINALE
    della scelta (``scelto["fonte"]``, es. ``"Manuale"``), non quella
    eventualmente sovrascritta dal fallback ``get_price`` qui sotto — altrimenti
    una scelta manuale (che ha sempre ``prezzo`` assente) finirebbe sempre per
    attivare il fallback e perdere il segnale "Manuale" prima di arrivare al
    guard, facendo scattare comunque la chiamata di rete a justETF."""
    pr = scelto["prezzo"]
    src = scelto["fonte"] or "Manuale"
    scelta_fonte = scelto["fonte"]
    if pr is None:
        from core.market_data import get_price
        try:
            pr, src = get_price(isin, tk)
        except Exception:
            pr, src = None, "Non trovato"

    enrichment_result = _fs_apply_enrichment_if_eligible(isin, tk, nm, tp, scelta_fonte)
    return pr, src, enrichment_result


def _fs_delete_storico_range(data: dict, ticker: str, date_from: str = "", date_to: str = "") -> tuple:
    """Elimina i prezzi storici salvati per un ticker, opzionalmente limitati a un
    intervallo di date (gia' in formato ISO YYYY-MM-DD). Nessun limite indicato =
    elimina tutto lo storico del ticker."""
    from persistence.storage import save_data
    from core.market_data import delete_storico_prezzi_range
    from core.formatting import fmt_date_only_it

    date_from = date_from.strip()
    date_to = date_to.strip()
    removed = delete_storico_prezzi_range(data.get("storico_prezzi", {}) or {}, ticker, date_from or None, date_to or None)
    if removed == 0:
        return True, f"{ticker}: nessuna data trovata nell'intervallo indicato."
    save_data(data)
    perimetro = f" tra {fmt_date_only_it(date_from) if date_from else '…'} e {fmt_date_only_it(date_to) if date_to else '…'}" if (date_from or date_to) else ""
    return True, f"{ticker}: rimosse {removed} date{perimetro}."


def _fs_is_btp_like(s: dict) -> bool:
    tipo = str(s.get("tipo", "")).strip().lower()
    ticker = str(s.get("ticker", "")).upper()
    return tipo in {"btp", "titolo di stato"} or ticker.startswith("BTP-")


def _fs_fmt_val(v: float, decimals: int = 2) -> str:
    return f"{v:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ─── Render ────────────────────────────────────────────────────────────────

def _fs_render_add_form() -> str:
    return """
    <form method="POST" action="/strumenti" autocomplete="off">
      <input type="hidden" name="azione" value="cerca">
      <label class="lbl">ISIN</label>
      <input type="text" name="isin" maxlength="12" placeholder="IT0001234567" style="text-transform:uppercase" required>
      <label class="lbl">Ticker (se già lo conosci, opzionale)</label>
      <input type="text" name="ticker_hint" placeholder="es. GOLD.MI" style="text-transform:uppercase">
      <div class="hint">Il sistema cerca i possibili strumenti corrispondenti all'ISIN: sceglierai tu quello giusto prima di salvare. Se conosci già il ticker giusto, scrivilo qui: verrà verificato e proposto per primo.</div>
      <button type="submit" class="btn-confirm" style="margin-top:20px">🔍 Cerca</button>
    </form>"""


def _fs_render_confirm_form(isin: str, candidati: list) -> str:
    from core.market_data import deduce_type

    def _prezzo_txt(prezzo: float | None) -> str:
        if prezzo is None:
            return "n/d"
        return f"{prezzo:.4f}".rstrip("0").rstrip(".")

    rows = []
    for i, c in enumerate(candidati):
        checked = " checked" if c.proposto else ""
        tipo = deduce_type(isin, c.ticker, c.nome or "")
        label = (
            f"{escape(c.ticker)} — {escape(c.borsa or '—')} — "
            f"{escape(c.nome or '(nome non disponibile)')} "
            f"({_prezzo_txt(c.prezzo)} · {escape(c.fonte)})"
        )
        rows.append(
            f'<label class="cand-row"><input type="radio" name="scelta" value="{i}"{checked} '
            f'onchange="toggleManualeStrumento()"> {label}</label><br>'
            f'<input type="hidden" name="cand_{i}_ticker" value="{escape(c.ticker)}">'
            f'<input type="hidden" name="cand_{i}_borsa" value="{escape(c.borsa or "")}">'
            f'<input type="hidden" name="cand_{i}_nome" value="{escape(c.nome or "")}">'
            f'<input type="hidden" name="cand_{i}_tipo" value="{escape(tipo)}">'
            f'<input type="hidden" name="cand_{i}_prezzo" value="{c.prezzo if c.prezzo is not None else ""}">'
            f'<input type="hidden" name="cand_{i}_fonte" value="{escape(c.fonte)}">'
        )
    candidati_html = "".join(rows) if rows else (
        "<div class='hint'>Nessun candidato trovato su Yahoo Finance per questo ISIN.</div>"
    )
    manuale_checked = " checked" if not candidati else ""
    manuale_display = "" if not candidati else "none"

    return f"""
    <form method="POST" action="/strumenti" autocomplete="off">
      <input type="hidden" name="azione" value="conferma_aggiungi">
      <input type="hidden" name="isin" value="{escape(isin)}">
      <label class="lbl">ISIN</label>
      <div class="hint">{escape(isin)}</div>
      <label class="lbl">Candidati trovati</label>
      {candidati_html}
      <label class="cand-row"><input type="radio" name="scelta" value="manuale"{manuale_checked} onchange="toggleManualeStrumento()"> Inserisci manualmente</label>
      <div id="manuale_strumento_wrap" style="display:{manuale_display}">
        <label class="lbl">Ticker</label>
        <input type="text" name="manuale_ticker" id="manuale_ticker">
        <label class="lbl">Nome</label>
        <input type="text" name="manuale_nome" id="manuale_nome">
        <label class="lbl">Tipo</label>
        <input type="text" name="manuale_tipo" id="manuale_tipo">
      </div>
      <button type="submit" class="btn-confirm" style="margin-top:20px">✅ Conferma e salva</button>
    </form>
    <form method="GET" action="/strumenti" style="margin-top:8px">
      <input type="hidden" name="tab" value="add">
      <button type="submit" class="btn-sm">✕ Annulla</button>
    </form>
    <script>
    function toggleManualeStrumento(){{
      var sel = document.querySelector('input[name=scelta]:checked');
      document.getElementById('manuale_strumento_wrap').style.display = (sel && sel.value==='manuale') ? '' : 'none';
    }}
    document.addEventListener('DOMContentLoaded', toggleManualeStrumento);
    </script>"""


def _render_strumenti_page(
    data: dict, ok_msg: str = "", err_msg: str = "", active_tab: str = "add",
    cerca_isin: str = "", candidati: "list | None" = None, selected_ticker: str = "",
) -> str:
    strumenti = data.get("strumenti", [])
    chiusi = [s for s in strumenti if s.get("stato", "aperto") == "chiuso"]

    from persistence.storage import get_registro_eventi
    from core.formatting import fmt_date_only_it
    ev_all = get_registro_eventi(data)
    linked_counts: dict = {}
    for ev in ev_all:
        tk = str(ev.get("ticker", "") or "")
        if tk:
            linked_counts[tk] = linked_counts.get(tk, 0) + 1

    def _it_date_or_empty(value) -> str:
        return fmt_date_only_it(value) if value else ""

    strumenti_js = json.dumps([{
        "ticker": s.get("ticker", ""),
        "nome": s.get("nome", ""),
        "tipo": s.get("tipo", ""),
        "is_btp": _fs_is_btp_like(s),
        "scadenza": _it_date_or_empty(s.get("scadenza")),
        "data_acquisto": _it_date_or_empty(s.get("data_acquisto")),
        "prima_cedola": _it_date_or_empty(s.get("prima_cedola") or s.get("data_origine")),
        "cedola_perc": float(s.get("cedola_perc", 0.0) or 0.0),
        "cedola_frequenza": str(s.get("cedola_frequenza", "annuale") or "annuale"),
        "aliquota_cedola": float(s.get("aliquota_cedola", 12.5) or 12.5),
        "nominale": float(s.get("nominale", 100.0) or 100.0),
        "linked": linked_counts.get(s.get("ticker", ""), 0),
        "has_prices": _fs_has_prices(data, s.get("ticker", "")),
    } for s in strumenti], ensure_ascii=False)

    def _tb(label: str, key: str) -> str:
        cls = "tab-btn active" if active_tab == key else "tab-btn"
        return f'<button class="{cls}" data-tg="str" data-t="{key}" onclick="switchTab(\'str\',\'{key}\')">{escape(label)}</button>'

    def _tp(key: str, content: str) -> str:
        cls = "tab-panel active" if active_tab == key else "tab-panel"
        return f'<div class="{cls}" data-pg="str" data-p="{key}">{content}</div>'

    str_opts = "\n".join(
        f'<option value="{escape(s.get("ticker",""))}">{escape(s.get("ticker",""))} — {escape(str(s.get("nome",""))[:45])}</option>'
        for s in strumenti
    )

    from core.market_data import earliest_storico_date

    _tickers_for_count = {s.get("ticker", "") for s in strumenti}
    date_count_by_ticker: dict = dict.fromkeys(_tickers_for_count, 0)
    first_date_by_ticker: dict = {}
    for _day_date, _day_prices in (data.get("storico_prezzi") or {}).items():
        if isinstance(_day_prices, dict):
            for _tk in _day_prices:
                if _tk in date_count_by_ticker:
                    date_count_by_ticker[_tk] += 1
                    if _tk not in first_date_by_ticker or _day_date < first_date_by_ticker[_tk]:
                        first_date_by_ticker[_tk] = _day_date

    storico_opts = "\n".join(
        f'<option value="{escape(s.get("ticker",""))}">{escape(s.get("ticker",""))} — {escape(str(s.get("nome",""))[:35])} '
        f'({date_count_by_ticker.get(s.get("ticker",""), 0)} date, dal {fmt_date_only_it(first_date_by_ticker.get(s.get("ticker",""))) if s.get("ticker","") in first_date_by_ticker else "n/d"})</option>'
        for s in strumenti
    )

    _suggested_since_iso = earliest_storico_date(data.get("storico_prezzi") or {}) or ""
    _suggested_since = fmt_date_only_it(_suggested_since_iso) if _suggested_since_iso else ""

    def _enrichment_status_label(s: dict) -> str:
        if s.get("enrichment_error"):
            return "errore"
        if s.get("enriched_at"):
            return f"arricchito {fmt_date_only_it((s.get('enriched_at') or '')[:10])}"
        return "mai arricchito"

    arricchimento_opts = "\n".join(
        f'<option value="{escape(s.get("ticker",""))}"{" selected" if s.get("ticker","")==selected_ticker else ""}>'
        f'{escape(s.get("ticker",""))} — {escape(str(s.get("nome",""))[:35])} ({_enrichment_status_label(s)})</option>'
        for s in strumenti
    )
    strumento_arricchimento = next((s for s in strumenti if s.get("ticker", "") == selected_ticker), None) if selected_ticker else None

    if chiusi:
        rows = "".join(
            f'<tr><td>{escape(s.get("ticker",""))}</td><td>{escape(str(s.get("nome",""))[:45])}</td>'
            f'<td>{escape(str(s.get("tipo","")))}</td><td>{escape(fmt_date_only_it(s.get("data_chiusura")) if s.get("data_chiusura") else "—")}</td>'
            f'<td>{escape(str(s.get("motivo_chiusura","") or ""))}</td></tr>'
            for s in chiusi
        )
        chiusi_html = (
            '<table class="table-simple"><thead><tr>'
            '<th>Ticker</th><th>Nome</th><th>Tipo</th><th>Chiuso il</th><th>Motivo</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>'
        )
    else:
        chiusi_html = '<div class="cart-empty">Nessuno strumento chiuso.</div>'

    feedback = ""
    if ok_msg:
        feedback = f'<div class="alert-ok">{escape(ok_msg)}</div>'
    elif err_msg:
        feedback = f'<div class="alert-err" style="display:block">{escape(err_msg)}</div>'

    no_str = '<div class="cart-empty">Nessuno strumento presente.</div>'

    tab_add = (
        _fs_render_confirm_form(cerca_isin, candidati) if candidati is not None
        else _fs_render_add_form()
    )

    tab_edit = no_str if not strumenti else f"""
    <label class="lbl">Strumento</label>
    <select id="sel_edit" onchange="loadEdit()">
      {str_opts}
    </select>
    <form method="POST" action="/strumenti" id="edit_form" autocomplete="off" style="margin-top:14px">
      <input type="hidden" name="azione" value="modifica">
      <input type="hidden" id="edit_orig_ticker" name="ticker">
      <label class="lbl">Denominazione</label>
      <input type="text" id="edit_nome" name="nome">
      <label class="lbl">Tipologia</label>
      <input type="text" id="edit_tipo" name="tipo">
      <label class="lbl">Ticker</label>
      <input type="text" id="edit_ticker_new" name="ticker_new">
      <div id="btp_fields" class="btp-fields">
        <div class="hint" style="margin-bottom:10px">Dati BTP usati per timeline, cedole e scadenza.</div>
        <div class="row2">
          <div><label class="lbl">Scadenza (GG/MM/AAAA)</label><input type="text" id="edit_scadenza" name="scadenza" placeholder="01/08/2026"></div>
          <div><label class="lbl">Data acquisto (GG/MM/AAAA)</label><input type="text" id="edit_data_acquisto" name="data_acquisto" placeholder="01/01/2025"></div>
        </div>
        <div class="row2">
          <div><label class="lbl">Prima cedola (GG/MM/AAAA)</label><input type="text" id="edit_prima_cedola" name="prima_cedola" placeholder="01/08/2025"></div>
          <div><label class="lbl">Cedola % annua</label><input type="number" id="edit_cedola_perc" name="cedola_perc" step="0.05" min="0" placeholder="0.00"></div>
        </div>
        <div class="row3">
          <div><label class="lbl">Frequenza cedola</label>
            <select id="edit_cedola_freq" name="cedola_frequenza">
              <option value="annuale">annuale</option>
              <option value="semestrale">semestrale</option>
              <option value="trimestrale">trimestrale</option>
            </select>
          </div>
          <div><label class="lbl">Aliquota cedola %</label><input type="number" id="edit_aliq_ced" name="aliquota_cedola" step="0.5" min="0" max="100" placeholder="12.5"></div>
          <div><label class="lbl">Nominale per quota</label><input type="number" id="edit_nominale" name="nominale" step="1" min="0" placeholder="100"></div>
        </div>
      </div>
      <button type="submit" class="btn-confirm" style="margin-top:18px">💾 Salva modifiche</button>
    </form>"""

    tab_del = no_str if not strumenti else f"""
    <label class="lbl">Strumento da eliminare</label>
    <select id="sel_del" onchange="loadDel()">
      {str_opts}
    </select>
    <div id="del_metrics" class="metrics" style="margin-top:14px"></div>
    <div id="del_warn" class="alert-warn" style="display:none">Eliminazione bloccata: sono presenti eventi collegati. Elimina prima operazioni/proventi/movimenti riferiti a questo ticker.</div>
    <div id="del_form_wrap">
      <form method="POST" action="/strumenti" autocomplete="off">
        <input type="hidden" name="azione" value="elimina">
        <input type="hidden" id="del_ticker_inp" name="ticker">
        <label class="check-wrap" style="margin-top:14px">
          <input type="checkbox" id="del_confirm_chk" onchange="toggleDel()">
          <span>Confermo l'eliminazione dello strumento selezionato</span>
        </label>
        <button type="submit" class="btn-danger" id="del_btn" disabled>🗑️ Elimina strumento</button>
      </form>
    </div>"""

    tab_storico = no_str if not strumenti else f"""
    <h2>Recupera storico</h2>
    <div class="hint" style="margin-bottom:14px">Per strumenti con storico prezzi troppo corto (es. aggiunti di recente): scarica da Yahoo Finance e integra senza sovrascrivere le date gia' salvate. La data di partenza e' proposta in base a cio' che il sistema ha gia' per gli altri strumenti — modificala se vuoi un perimetro diverso, o svuotala per importare tutto cio' che Yahoo ha disponibile.</div>
    <form method="POST" action="/strumenti" autocomplete="off">
      <input type="hidden" name="azione" value="recupera_storico">
      <label class="lbl">Strumento</label>
      <select name="ticker">
        {storico_opts}
      </select>
      <label class="lbl">Data di partenza (GG/MM/AAAA, opzionale)</label>
      <input type="text" name="storico_data_da" value="{escape(_suggested_since)}" placeholder="es. 30/05/2023">
      <button type="submit" class="btn-confirm" style="margin-top:18px">⬇ Recupera storico</button>
    </form>

    <h2 style="margin-top:26px">Elimina storico salvato</h2>
    <div class="hint" style="margin-bottom:14px">Rimuove i prezzi salvati per uno strumento, per intero o solo in un intervallo di date. Lascia entrambe le date vuote per eliminare tutto lo storico dello strumento.</div>
    <form method="POST" action="/strumenti" autocomplete="off">
      <input type="hidden" name="azione" value="elimina_storico">
      <label class="lbl">Strumento</label>
      <select name="ticker">
        {storico_opts}
      </select>
      <div class="row2">
        <div><label class="lbl">Da (GG/MM/AAAA, opzionale)</label><input type="text" name="storico_data_da" placeholder="lascia vuoto = dall'inizio"></div>
        <div><label class="lbl">A (GG/MM/AAAA, opzionale)</label><input type="text" name="storico_data_a" placeholder="lascia vuoto = fino alla fine"></div>
      </div>
      <label class="check-wrap" style="margin-top:14px">
        <input type="checkbox" required>
        <span>Confermo l'eliminazione dello storico prezzi selezionato</span>
      </label>
      <button type="submit" class="btn-danger" style="margin-top:14px">🗑️ Elimina storico</button>
    </form>"""

    if strumento_arricchimento is not None:
        _tk_sel = escape(strumento_arricchimento.get("ticker", ""))
        _stato_sel = escape(_enrichment_status_label(strumento_arricchimento))
        _fields_html = _fs_render_dati_completi_fields(strumento_arricchimento)
        arricchimento_dettaglio = f"""
    <div class="hint" style="margin:14px 0 20px">Stato: <b>{_stato_sel}</b></div>

    <form method="POST" action="/strumenti" autocomplete="off" style="margin-bottom:26px">
      <input type="hidden" name="azione" value="arricchisci">
      <input type="hidden" name="ticker" value="{_tk_sel}">
      <button type="submit" class="btn-confirm">⬇ Arricchisci automaticamente</button>
    </form>

    <h2>Importa da PDF Fineco</h2>
    <div class="hint" style="margin-bottom:14px">Carica il PDF della pagina Fineco dello strumento (Ctrl+P &rarr; Salva come PDF).</div>
    <form method="POST" action="/strumenti" enctype="multipart/form-data" autocomplete="off" style="margin-bottom:26px">
      <input type="hidden" name="azione" value="importa_pdf">
      <input type="hidden" name="ticker" value="{_tk_sel}">
      <input type="file" name="pdf_file" accept=".pdf">
      <button type="submit" class="btn-confirm" style="margin-top:12px">Importa PDF</button>
    </form>

    <h2>Modifica manuale</h2>
    <form method="POST" action="/strumenti" autocomplete="off">
      <input type="hidden" name="azione" value="salva_dati_completi">
      <input type="hidden" name="ticker" value="{_tk_sel}">
      {_fields_html}
      <button type="submit" class="btn-confirm" style="margin-top:14px">&#128190; Salva modifiche</button>
    </form>"""
    else:
        arricchimento_dettaglio = '<div class="hint" style="margin-top:14px">Seleziona uno strumento per arricchirlo, importare un PDF Fineco o modificarne i dati a mano.</div>'

    tab_arricchimento = no_str if not strumenti else f"""
    <h2>Arricchisci / modifica dati strumento</h2>
    <div class="hint" style="margin-bottom:14px">Per lo strumento selezionato: recupero automatico dalle fonti pubbliche (YTM/duration per i BTP, TER/benchmark/composizione per ETF ed ETC, rendimenti per i fondi FAM), import da PDF Fineco, o inserimento manuale dei campi.</div>
    <label class="lbl">Strumento</label>
    <select onchange="location.href='/strumenti?tab=arricchimento&amp;ticker='+encodeURIComponent(this.value)">
      <option value="">— seleziona —</option>
      {arricchimento_opts}
    </select>
    {arricchimento_dettaglio}"""

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Strumenti</title>
{CSS}
</head>
<body>
<div class="card">
  <h1>📌 Strumenti</h1>
  <p style="color:#64748b;font-size:.82rem;margin:-10px 0 16px">Gestisci l'anagrafica degli strumenti da un unico punto. Le eliminazioni sono protette se esistono eventi collegati.</p>
  {feedback}
  <div class="tabs">
    {_tb("➕ Aggiungi","add")}
    {_tb("✏️ Modifica","edit")}
    {_tb("🗑️ Elimina","del")}
    {_tb("📈 Storico","storico")}
    {_tb("🔎 Arricchimento","arricchimento")}
    {_tb("📁 Chiusi","closed")}
  </div>
  {_tp("add", tab_add)}
  {_tp("edit", tab_edit)}
  {_tp("del", tab_del)}
  {_tp("storico", tab_storico)}
  {_tp("arricchimento", tab_arricchimento)}
  {_tp("closed", chiusi_html)}
  <div class="back-links"><a href="{STREAMLIT_URL}" target="_blank">← Torna a Streamlit</a></div>
</div>
{TAB_JS}
<script>
const strumenti={strumenti_js};
function loadEdit(){{
  const tk=document.getElementById('sel_edit')?.value;
  const s=strumenti.find(x=>x.ticker===tk);
  if(!s)return;
  const set=(id,v)=>{{const el=document.getElementById(id);if(el)el.value=v??'';}}
  set('edit_orig_ticker',s.ticker);
  set('edit_nome',s.nome);
  set('edit_tipo',s.tipo);
  set('edit_ticker_new',s.ticker);
  const btp=document.getElementById('btp_fields');
  if(btp)btp.className='btp-fields'+(s.is_btp?' on':'');
  if(s.is_btp){{
    set('edit_scadenza',s.scadenza);
    set('edit_data_acquisto',s.data_acquisto);
    set('edit_prima_cedola',s.prima_cedola);
    set('edit_cedola_perc',s.cedola_perc);
    set('edit_aliq_ced',s.aliquota_cedola);
    set('edit_nominale',s.nominale);
    const fr=document.getElementById('edit_cedola_freq');
    if(fr)[...fr.options].forEach(o=>o.selected=(o.value===s.cedola_frequenza));
  }}
}}
function loadDel(){{
  const tk=document.getElementById('sel_del')?.value;
  const s=strumenti.find(x=>x.ticker===tk);
  if(!s)return;
  const m=document.getElementById('del_metrics');
  if(m)m.innerHTML=`
    <div class="metric"><div class="metric-lbl">Eventi collegati</div><div class="metric-val">${{s.linked}}</div></div>
    <div class="metric"><div class="metric-lbl">Storico prezzi</div><div class="metric-val">${{s.has_prices?'sì':'no'}}</div></div>
    <div class="metric"><div class="metric-lbl">Stato</div><div class="metric-val">${{s.linked?'bloccato':'eliminabile'}}</div></div>`;
  document.getElementById('del_warn').style.display=s.linked?'':'none';
  document.getElementById('del_form_wrap').style.display=s.linked?'none':'';
  document.getElementById('del_ticker_inp').value=s.ticker;
  const chk=document.getElementById('del_confirm_chk');if(chk)chk.checked=false;
  toggleDel();
}}
function toggleDel(){{
  const chk=document.getElementById('del_confirm_chk')?.checked;
  const btn=document.getElementById('del_btn');if(btn)btn.disabled=!chk;
}}
document.addEventListener('DOMContentLoaded',()=>{{loadEdit();loadDel();}});
</script>
</body>
</html>"""


# ─── Routes ────────────────────────────────────────────────────────────────

@router.get("/strumenti", response_class=HTMLResponse)
async def get_strumenti(tab: str = "add", ok: str = "", err: str = "", ticker: str = ""):
    from persistence.storage import load_data as _ld, load_settings as _ls, apply_privacy_filter
    try:
        d = apply_privacy_filter(_ld(), _ls())
    except Exception as exc:
        d = {}
        err = str(exc)
    return HTMLResponse(_render_strumenti_page(d, ok_msg=ok, err_msg=err, active_tab=tab, selected_ticker=ticker))


@router.post("/strumenti", response_class=HTMLResponse)
async def post_strumenti(
    request: Request,
    azione: str = Form(""),
    isin: str = Form(""),
    ticker_hint: str = Form(""),
    ticker: str = Form(""),
    ticker_new: str = Form(""),
    nome: str = Form(""),
    tipo: str = Form(""),
    scadenza: str = Form(""),
    data_acquisto: str = Form(""),
    prima_cedola: str = Form(""),
    cedola_perc: str = Form("0"),
    cedola_frequenza: str = Form("annuale"),
    aliquota_cedola: str = Form("12.5"),
    nominale: str = Form("100"),
    storico_data_da: str = Form(""),
    storico_data_a: str = Form(""),
    pdf_file: Optional[UploadFile] = File(None),
):
    from persistence.storage import load_data as _ld, load_settings as _ls, apply_privacy_filter, save_data

    def err_page(msg: str, tab: str = "add", sel_ticker: str = "") -> HTMLResponse:
        # Solo per il re-render in caso di errore: qui SI applica il filtro
        # privacy. I "d" usati per le operazioni di scrittura più sotto
        # restano invece sempre non filtrati, altrimenti un salvataggio con
        # privacy attiva cancellerebbe per sempre lo strumento nascosto.
        try:
            d = apply_privacy_filter(_ld(), _ls())
        except Exception:
            d = {}
        return HTMLResponse(_render_strumenti_page(d, err_msg=msg, active_tab=tab, selected_ticker=sel_ticker))

    if azione == "cerca":
        isin = isin.upper().strip()
        if len(isin) != 12:
            return err_page("L'ISIN deve avere 12 caratteri.", "add")
        try:
            d = apply_privacy_filter(_ld(), _ls())  # ramo di sola ricerca, non salva mai
        except Exception as exc:
            return err_page(str(exc), "add")
        if any(s.get("isin") == isin for s in d.get("strumenti", [])):
            return err_page("Strumento già presente.", "add")
        try:
            from core.market_data import find_ticker_candidates
            candidati = find_ticker_candidates(isin, ticker_hint=ticker_hint)
        except Exception as exc:
            return err_page(f"Errore ricerca dati: {exc}", "add")
        return HTMLResponse(_render_strumenti_page(
            d, active_tab="add", cerca_isin=isin, candidati=candidati,
        ))

    elif azione == "conferma_aggiungi":
        isin = isin.upper().strip()
        if len(isin) != 12:
            return err_page("L'ISIN deve avere 12 caratteri.", "add")
        try:
            d = _ld()
        except Exception as exc:
            return err_page(str(exc), "add")
        if any(s.get("isin") == isin for s in d.get("strumenti", [])):
            return err_page("Strumento già presente.", "add")

        form_data = dict(await request.form())
        n_candidati = 0
        while f"cand_{n_candidati}_ticker" in form_data:
            n_candidati += 1
        scelto = _fs_resolve_strumento_scelto(form_data, n_candidati)

        tk = scelto["ticker"].strip()
        if not tk:
            return err_page("Ticker non specificato.", "add")
        nm = scelto["nome"] or tk
        tp = scelto["tipo"] or ""

        from core.market_data import set_isin_ticker
        set_isin_ticker(isin, tk)

        pr, src, enrichment_result = _fs_resolve_price_and_enrichment(scelto, isin, tk, nm, tp)
        tp = enrichment_result.pop("tipo")

        strumento_record = {
            "isin": isin, "ticker": tk, "stato": "aperto",
            "nome": nm, "tipo": tp, "prezzo": pr, "fonte": src,
            "aggiornato": str(date.today()), "scadenza": "", "data_acquisto": "",
            "prima_cedola": "", "cedola_perc": 0.0, "cedola_frequenza": "annuale",
            "aliquota_cedola": 12.5, "nominale": 100.0,
        }
        strumento_record.update(enrichment_result)
        d.setdefault("strumenti", []).append(strumento_record)
        save_data(d)
        from urllib.parse import quote as urlquote
        return RedirectResponse(f"/strumenti?tab=edit&ok={urlquote('Aggiunto '+str(nm or tk))}", status_code=303)

    elif azione == "modifica":
        ticker = ticker.strip()
        ticker_new = ticker_new.strip()
        if not ticker:
            return err_page("Ticker non specificato.", "edit")
        try:
            d = _ld()
        except Exception as exc:
            return err_page(str(exc), "edit")
        se = next((s for s in d.get("strumenti", []) if s.get("ticker") == ticker), None)
        if se is None:
            return err_page("Strumento non trovato.", "edit")
        se["nome"] = nome
        se["tipo"] = tipo
        se["ticker"] = ticker_new or ticker
        isin_val = se.get("isin")
        if isin_val:
            from core.market_data import set_isin_ticker
            set_isin_ticker(isin_val, se["ticker"])
            d.setdefault("cache_lookup_strumenti", {})[isin_val] = se["ticker"]
        if _fs_is_btp_like(se):
            try:
                se["scadenza"] = _fs_parse_flex_date(scadenza)
                se["data_acquisto"] = _fs_parse_flex_date(data_acquisto)
                se["prima_cedola"] = _fs_parse_flex_date(prima_cedola)
            except ValueError as exc:
                return err_page(f"Data non valida: {exc}", "edit")
            try:
                se["cedola_perc"] = float(cedola_perc or 0)
                se["cedola_frequenza"] = str(cedola_frequenza or "annuale")
                se["aliquota_cedola"] = float(aliquota_cedola or 0)
                se["nominale"] = float(nominale or 0)
            except ValueError:
                pass
        if ticker and ticker != ticker_new:
            for op in d.get("operazioni", []):
                if op.get("ticker") == ticker:
                    op["ticker"] = ticker_new
            for ev in d.get("registro_eventi", []):
                if ev.get("ticker") == ticker:
                    ev["ticker"] = ticker_new
            for _, prices in (d.get("storico_prezzi") or {}).items():
                if isinstance(prices, dict) and ticker in prices:
                    prices[ticker_new] = prices.pop(ticker)
        save_data(d)
        from urllib.parse import quote as urlquote
        return RedirectResponse(f"/strumenti?tab=edit&ok={urlquote('Strumento aggiornato.')}", status_code=303)

    elif azione == "elimina":
        ticker = ticker.strip()
        if not ticker:
            return err_page("Ticker non specificato.", "del")
        try:
            d = _ld()
        except Exception as exc:
            return err_page(str(exc), "del")
        ok, msg = _fs_delete_instrument(d, ticker)
        if ok:
            from urllib.parse import quote as urlquote
            return RedirectResponse(f"/strumenti?tab=del&ok={urlquote(msg)}", status_code=303)
        return err_page(msg, "del")

    elif azione == "recupera_storico":
        ticker = ticker.strip()
        if not ticker:
            return err_page("Ticker non specificato.", "storico")
        try:
            since_iso = _fs_parse_flex_date(storico_data_da)
        except ValueError as exc:
            return err_page(f"Data di partenza non valida: {exc}", "storico")
        try:
            d = _ld()
        except Exception as exc:
            return err_page(str(exc), "storico")
        ok, msg = _fs_backfill_storico(d, ticker, since=since_iso or None)
        from urllib.parse import quote as urlquote
        if ok:
            return RedirectResponse(f"/strumenti?tab=storico&ok={urlquote(msg)}", status_code=303)
        return err_page(msg, "storico")

    elif azione == "elimina_storico":
        ticker = ticker.strip()
        if not ticker:
            return err_page("Ticker non specificato.", "storico")
        try:
            da_iso = _fs_parse_flex_date(storico_data_da)
            a_iso = _fs_parse_flex_date(storico_data_a)
        except ValueError as exc:
            return err_page(f"Data non valida: {exc}", "storico")
        try:
            d = _ld()
        except Exception as exc:
            return err_page(str(exc), "storico")
        ok, msg = _fs_delete_storico_range(d, ticker, da_iso, a_iso)
        from urllib.parse import quote as urlquote
        if ok:
            return RedirectResponse(f"/strumenti?tab=storico&ok={urlquote(msg)}", status_code=303)
        return err_page(msg, "storico")

    elif azione == "arricchisci":
        ticker = ticker.strip()
        if not ticker:
            return err_page("Ticker non specificato.", "arricchimento")
        try:
            d = _ld()
        except Exception as exc:
            return err_page(str(exc), "arricchimento", ticker)
        ok, msg = _fs_arricchisci_strumento(d, ticker)
        from urllib.parse import quote as urlquote
        if ok:
            return RedirectResponse(f"/strumenti?tab=arricchimento&ticker={urlquote(ticker)}&ok={urlquote(msg)}", status_code=303)
        return err_page(msg, "arricchimento", ticker)

    elif azione == "importa_pdf":
        ticker = ticker.strip()
        if not ticker:
            return err_page("Ticker non specificato.", "arricchimento")
        if not pdf_file or not pdf_file.filename:
            return err_page("Nessun file PDF selezionato.", "arricchimento", ticker)
        try:
            d = _ld()
        except Exception as exc:
            return err_page(str(exc), "arricchimento", ticker)
        strumento = next((s for s in (d.get("strumenti") or []) if s.get("ticker") == ticker), None)
        if strumento is None:
            return err_page("Strumento non trovato.", "arricchimento")
        from urllib.parse import quote as urlquote
        try:
            from core.instrument_enrichment import parse_fineco_pdf, _categoria
            pdf_bytes = await pdf_file.read()
            parsed = parse_fineco_pdf(pdf_bytes, _categoria(strumento.get("tipo", "")))
            if not parsed:
                return err_page("PDF non riconosciuto.", "arricchimento", ticker)
            src = strumento.get("enrichment_source") or {}
            for field, val in parsed.items():
                if field != "enrichment_source":
                    strumento[field] = val
                    src[field] = "pdf"
            strumento["enrichment_source"] = src
            import datetime as _dt
            strumento["enriched_at"] = _dt.datetime.utcnow().isoformat()
            save_data(d)
        except Exception as exc:
            return err_page(str(exc)[:120], "arricchimento", ticker)
        return RedirectResponse(f"/strumenti?tab=arricchimento&ticker={urlquote(ticker)}&ok={urlquote('PDF importato con successo.')}", status_code=303)

    elif azione == "salva_dati_completi":
        ticker = ticker.strip()
        if not ticker:
            return err_page("Ticker non specificato.", "arricchimento")
        try:
            d = _ld()
        except Exception as exc:
            return err_page(str(exc), "arricchimento", ticker)
        strumento = next((s for s in (d.get("strumenti") or []) if s.get("ticker") == ticker), None)
        if strumento is None:
            return err_page("Strumento non trovato.", "arricchimento")
        form_data = dict(await request.form())
        src = strumento.get("enrichment_source") or {}
        skip_keys = {"azione", "ticker"}
        for key, val in form_data.items():
            if key in skip_keys:
                continue
            val = str(val).strip()
            if val:
                strumento[key] = val
                src[key] = "manuale"
        strumento["enrichment_source"] = src
        import datetime as _dt
        strumento["enriched_at"] = _dt.datetime.utcnow().isoformat()
        save_data(d)
        from urllib.parse import quote as urlquote
        return RedirectResponse(f"/strumenti?tab=arricchimento&ticker={urlquote(ticker)}&ok={urlquote('Modifiche salvate.')}", status_code=303)

    return err_page("Azione non riconosciuta.", "add")
