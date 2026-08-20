"""ui/form_server/quote_interne.py — pagina "Quote & impostazioni" del
form-server (route /quote-interne).

Editor delle quote target per strumento dentro ogni bucket SATOR, piu' le
impostazioni SATOR avanzate (spostate qui su richiesta esplicita
dell'utente, che non vuole expander Streamlit per questi controlli).
Condivide la stessa pipeline di storage dell'app principale: nessuna
logica duplicata.
"""
from __future__ import annotations

import json
import logging
from html import escape

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from core.services.sator import (
    apply_no_sell_from_form,
    compute_instrument_buckets,
    compute_instrument_operational_status,
    compute_instrument_quota_status,
    compute_instrument_reference_ranges,
    ensure_sator_settings,
    held_non_pac_tickers,
)
from ui.form_server.shell import STREAMLIT_URL, TAB_JS, _ROOT_VARS_BLOCK

logger = logging.getLogger("portafoglio.form_server.quote_interne")

router = APIRouter()

_BUCKETS = ("Core", "Difensivo", "Satellite")

_CSS = _ROOT_VARS_BLOCK + """
*,*::before,*::after{box-sizing:border-box}
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--slate-100);color:var(--slate-800);margin:0;padding:16px 20px 60px;font-size:.9rem}
.qi{max-width:1100px;margin:0 auto}
.qi-card{background:var(--white);border-radius:14px;padding:20px 24px;box-shadow:0 2px 10px var(--black-a06);margin-bottom:16px}
h1{font-size:1.15rem;font-weight:800;margin:0 0 14px;color:var(--slate-800)}
h2{font-size:.75rem;font-weight:800;text-transform:uppercase;letter-spacing:.06em;color:var(--slate-500);margin:0 0 14px}
.qi-row{display:flex;gap:14px;align-items:center;padding:6px 0}
.qi-row label{flex:1;font-weight:600}
.qi-row input{width:100px;padding:6px 8px;border:1px solid var(--slate-300);border-radius:8px}
.qi-sum{font-weight:700;margin-top:8px}
.qi-hint{color:var(--slate-500);font-size:.78rem;margin-left:8px}
.alert-ok{background:var(--green-50);color:var(--green-800);padding:10px 14px;border-radius:10px;margin-bottom:14px}
.alert-warn{background:var(--red-50);color:var(--red-700);padding:10px 14px;border-radius:10px;margin-bottom:14px}
.btn-salva{padding:9px 24px;background:var(--indigo-500);color:var(--white);border:none;border-radius:9px;font-size:.9rem;font-weight:700;cursor:pointer}
.tabs{display:flex;gap:2px;border-bottom:2px solid var(--slate-200);margin-bottom:20px;margin-top:4px}
.tab-btn{background:none;border:none;border-bottom:3px solid transparent;margin-bottom:-2px;padding:8px 14px;font-size:.87rem;font-weight:600;color:var(--slate-500);cursor:pointer;transition:color .15s,border-color .15s}
.tab-btn.active{color:var(--indigo-500);border-bottom-color:var(--indigo-500)}
.tab-panel{display:none}
.tab-panel.active{display:block}
.qi-table{width:100%;border-collapse:collapse;font-size:.85rem}
.qi-table th{text-align:left;padding:8px;color:var(--slate-500);font-size:.72rem;text-transform:uppercase}
.qi-table td{padding:6px 8px;border-top:1px solid var(--slate-200)}
.stato-badge{padding:2px 8px;border-radius:999px;font-size:.75rem;font-weight:700}
.stato-in_target{background:var(--green-50);color:var(--green-800)}
.stato-sottopeso{background:var(--indigo-50);color:var(--indigo-700)}
.stato-sovrappeso{background:var(--red-50);color:var(--red-700)}
.stato-sovrappeso_no_sell{background:var(--amber-100);color:var(--amber-800)}
</style>"""


def _bucket_tickers(data: dict, *, exclude_tickers: frozenset[str] = frozenset()) -> dict[str, list[str]]:
    from core.services.sator import _tickers_posseduti  # riuso privato intenzionale, stesso file di dominio
    from core.finance import compute_portfolio_state

    state_df = compute_portfolio_state(data, include_closed=True).get("df")
    if data.get("_positions_df") is not None and not data["_positions_df"].empty:
        state_df = data["_positions_df"]
    held = _tickers_posseduti(state_df) if state_df is not None else set()
    buckets = compute_instrument_buckets(data, held)
    out: dict[str, list[str]] = {b: [] for b in _BUCKETS}
    for ticker, bucket in buckets.items():
        if ticker in exclude_tickers:
            continue
        out.setdefault(bucket, []).append(ticker)
    for b in out:
        out[b].sort()
    return out


def _render_quote_interne_page(*, ok_msg: str = "", err_msg: str = "", active_tab: str = "target") -> str:
    from core.finance import compute_portfolio_state
    from persistence.storage import load_data, load_settings

    data = load_data()
    settings = load_settings()
    cfg = ensure_sator_settings(settings)
    # Stesso toggle "Escludi BTP/GOV" gia' attivo su Pianificazione
    # (settings["sator"]["deficit_pac_only"], persistito): /quote-interne
    # deve rispettarlo allo stesso modo, altrimenti i BTP restano
    # visibili/editabili qui anche quando l'utente li ha esclusi altrove.
    exclude_tickers: frozenset[str] = frozenset()
    if cfg["deficit_pac_only"]:
        state_df = compute_portfolio_state(data, include_closed=True).get("df")
        if data.get("_positions_df") is not None and not data["_positions_df"].empty:
            state_df = data["_positions_df"]
        exclude_tickers = held_non_pac_tickers(data, state_df)
    tickers_by_bucket = _bucket_tickers(data, exclude_tickers=exclude_tickers)
    status = compute_instrument_quota_status(data, settings, exclude_tickers=exclude_tickers)
    reference_ranges = compute_instrument_reference_ranges(data, settings, tickers_by_bucket)
    operational_status = compute_instrument_operational_status(data, settings)

    ok_html = f'<div class="alert-ok">{escape(ok_msg)}</div>' if ok_msg else ""
    err_html = f'<div class="alert-warn">{escape(err_msg)}</div>' if err_msg else ""

    bucket_sections = []
    for bucket in _BUCKETS:
        tickers = tickers_by_bucket.get(bucket, [])
        quotas = cfg["instrument_quotas"].get(bucket, {})
        if not tickers:
            bucket_sections.append(f'<div class="qi-card"><h2>{bucket}</h2><p>Nessuno strumento posseduto in questo bucket.</p></div>')
            continue
        bucket_ranges = reference_ranges.get(bucket, {})
        _stato_label = {
            "in_target": "In target", "sottopeso": "Sottopeso",
            "sovrappeso": "Sovrappeso", "sovrappeso_no_sell": "Sovrappeso — NO_SELL",
        }
        rows = "".join(
            f'<div class="qi-row"><label>{escape(ticker)}</label>'
            f'<span style="width:90px;text-align:right">{operational_status.get(ticker, {}).get("peso_attuale", 0.0) * 100:.1f}%</span>'
            f'<input type="number" min="0" max="100" step="0.5" '
            f'data-bucket="{bucket}" data-ticker="{escape(ticker)}" '
            f'value="{quotas.get(ticker, 0.0) * 100:.1f}" class="qi-input">'
            f'<label style="flex:0 0 auto"><input type="checkbox" name="no_sell_{escape(ticker)}" value="1" '
            + ("checked" if operational_status.get(ticker, {}).get("no_sell") else "")
            + '> NO_SELL</label>'
            f'<span class="stato-badge stato-{operational_status.get(ticker, {}).get("stato", "in_target")}">'
            f'{_stato_label.get(operational_status.get(ticker, {}).get("stato", "in_target"), "")}</span>'
            + (
                f'<span class="qi-hint">riferimento indicativo: 0&ndash;{bucket_ranges[ticker][1] * 100:.0f}%</span>'
                if ticker in bucket_ranges else ""
            )
            + '</div>'
            for ticker in tickers
        )
        bucket_sections.append(
            f'<div class="qi-card"><h2>{bucket}</h2>{rows}'
            f'<div class="qi-sum" id="sum-{bucket}">Somma: --</div></div>'
        )

    status_rows = []
    for bucket in _BUCKETS:
        s = status[bucket]
        stato_label = "valido" if s["valid"] else "NON VALIDO"
        stale = s.get("stale_tickers") or []
        note = (
            f"quota orfana su {', '.join(escape(t) for t in stale)}, rimuovila o riassegnala"
            if stale else ""
        )
        status_rows.append(
            f"<tr><td>{bucket}</td><td>{stato_label}</td><td>{s['sum_target']*100:.1f}%</td><td>{note}</td></tr>"
        )

    caps = cfg["concentration_caps"]
    caps_rows = "".join(
        f'<div class="qi-row"><label>{escape(nature.replace("_", " "))}</label>'
        f'<input type="number" min="1" max="100" step="1" name="cap_{escape(nature)}" '
        f'value="{caps[nature]*100:.0f}"></div>'
        for nature in sorted(caps.keys())
    )
    weights = cfg["score_weights"]
    settings_section = f"""
  <form method="post" action="/quote-interne">
    <input type="hidden" name="azione" value="salva_impostazioni">
    <div class="qi-card"><h2>Limiti di concentrazione per asset class</h2>{caps_rows}</div>
    <div class="qi-card"><h2>Allocazione budget per bucket (avanzato)</h2>
      <div class="qi-row"><label>Dividi il budget per deficit di bucket</label>
        <input type="checkbox" name="bucket_first_allocation" value="1" {"checked" if cfg["bucket_first_allocation"] else ""}></div>
      <div class="qi-row"><label>Tolleranza banda attorno al target (pp)</label>
        <input type="number" name="band_tolerance_pp" min="0" max="20" step="0.5" value="{cfg['band_tolerance_pp']*100:.1f}"></div>
    </div>
    <div class="qi-card"><h2>Tolleranza quote interne per strumento</h2>
      <p>Scostamento in punti percentuali (tra quota attuale e quota di riferimento di un singolo strumento) entro cui la tabella "Attuale/Target" di Pianificazione lo colora ok invece che avviso/critico. Non influisce sul blocco di SATOR (quello richiede sempre somma esatta al 100%), solo sul colore.</p>
      <div class="qi-row"><label>Tolleranza per strumento (pp)</label>
        <input type="number" name="instrument_quota_tolerance_pp" min="0" max="20" step="0.5" value="{cfg['instrument_quota_tolerance_pp']*100:.1f}"></div>
    </div>
    <div class="qi-card"><h2>Pesi del punteggio SATOR</h2>
      <div class="qi-row"><label>Fit allocativo %</label><input type="number" name="w_fit" min="0" max="100" step="1" value="{weights['strategic_fit']*100:.0f}"></div>
      <div class="qi-row"><label>Momentum %</label><input type="number" name="w_mom" min="0" max="100" step="1" value="{weights['tactical_momentum']*100:.0f}"></div>
      <div class="qi-row"><label>Rischio %</label><input type="number" name="w_risk" min="0" max="100" step="1" value="{weights['risk_efficiency']*100:.0f}"></div>
      <div class="qi-row"><label>Diversificazione %</label><input type="number" name="w_div" min="0" max="100" step="1" value="{weights['diversification_benefit']*100:.0f}"></div>
      <div class="qi-row"><label>Costo %</label><input type="number" name="w_cost" min="0" max="100" step="1" value="{weights['cost_efficiency']*100:.0f}"></div>
    </div>
    <button type="submit" class="btn-salva">Salva impostazioni</button>
  </form>
  <div class="qi-card"><h2>Come funziona il calcolo interno</h2>
    <p>Momentum: media pesata dei rendimenti a 1/3/6/12 mesi (10/35/35/20%) — <code>_score_momentum</code>.<br>
    Rischio: volatilita' (40%) + drawdown massimo (30%) + rendimento/rischio a 12 mesi (30%) — <code>_score_risk</code>.<br>
    Costo: bonus zero commissioni/PAC, malus TER/spread — <code>_score_cost</code>.</p>
  </div>"""

    def _tb(label: str, key: str) -> str:
        cls = "tab-btn active" if key == active_tab else "tab-btn"
        return f'<button class="{cls}" data-tg="qi" data-t="{key}" onclick="switchTab(\'qi\',\'{key}\')">{escape(label)}</button>'

    def _tp(key: str, content: str) -> str:
        cls = "tab-panel active" if key == active_tab else "tab-panel"
        return f'<div class="{cls}" data-pg="qi" data-p="{key}">{content}</div>'

    tab_target = f"""
  {settings_section}
  <h2 style="margin-top:24px">Quote per bucket — Target strategico</h2>
  <p>Il riferimento indicativo accanto a ogni campo usa i limiti di concentrazione impostati sopra. Peso attuale e Stato sono calcolati, non editabili.</p>
  <form method="post" action="/quote-interne" onsubmit="return collectQuotas()">
    <input type="hidden" name="azione" value="salva_quote">
    <input type="hidden" name="quotas_json" id="quotas_json">
    {"".join(bucket_sections)}
    <button type="submit" class="btn-salva">Salva target e NO_SELL</button>
  </form>
  <div class="qi-card">
    <h2>Stato attuale</h2>
    <table><thead><tr><th>Bucket</th><th>Stato</th><th>Somma quote</th><th>Note</th></tr></thead>
    <tbody>{"".join(status_rows)}</tbody></table>
  </div>"""

    return f"""<!DOCTYPE html>
<html lang="it">
<head><meta charset="utf-8"><title>Quote & impostazioni</title>{_CSS}</head>
<body>
<div class="qi">
  <h1>Quote & impostazioni</h1>
  {ok_html}{err_html}
  <div class="tabs">
    {_tb("Target & Stato", "target")}
    {_tb("Ruolo & Benchmark", "ruolo")}
    {_tb("Esposizione Bucket", "bucket")}
  </div>
  {_tp("target", tab_target)}
  <p><a href="{STREAMLIT_URL}">&larr; Torna all'app</a></p>
</div>
{TAB_JS}
<script>
function collectQuotas() {{
  const buckets = {{}};
  document.querySelectorAll('.qi-input').forEach(function(input) {{
    const bucket = input.dataset.bucket, ticker = input.dataset.ticker;
    buckets[bucket] = buckets[bucket] || {{}};
    buckets[bucket][ticker] = parseFloat(input.value || '0');
  }});
  document.getElementById('quotas_json').value = JSON.stringify(buckets);
  return true;
}}
</script>
</body></html>"""


@router.get("/quote-interne", response_class=HTMLResponse)
async def get_quote_interne(ok: str = "", err: str = "", tab: str = "target"):
    return HTMLResponse(_render_quote_interne_page(ok_msg=ok, err_msg=err, active_tab=tab))


@router.post("/quote-interne", response_class=HTMLResponse)
async def post_quote_interne(
    request: Request,
    azione: str = Form(""),
    quotas_json: str = Form(""),
    w_fit: str = Form("30"), w_mom: str = Form("25"), w_risk: str = Form("20"),
    w_div: str = Form("15"), w_cost: str = Form("10"),
    bucket_first_allocation: str = Form(""),
    band_tolerance_pp: str = Form("3"),
    instrument_quota_tolerance_pp: str = Form("5"),
):
    from persistence.storage import load_data, load_settings, save_data, save_settings

    if azione == "salva_impostazioni":
        weights = {
            "strategic_fit": max(0.0, float(w_fit or 0)),
            "tactical_momentum": max(0.0, float(w_mom or 0)),
            "risk_efficiency": max(0.0, float(w_risk or 0)),
            "diversification_benefit": max(0.0, float(w_div or 0)),
            "cost_efficiency": max(0.0, float(w_cost or 0)),
        }
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}

        # I cap di concentrazione (cap_<natura>) non sono dichiarati come
        # parametri Form individuali (le natura sono dinamiche, vedi
        # CAP_MORBIDO_NATURA in core/services/sator.py): letti dal form
        # grezzo, stesso pattern di ui/form_server/strumenti.py
        # (post_strumenti, campi cand_N dinamici).
        form_data = dict(await request.form())
        caps: dict[str, float] = {}
        for key, value in form_data.items():
            if not key.startswith("cap_"):
                continue
            natura = key[len("cap_"):]
            try:
                pct = float(value)
            except (TypeError, ValueError):
                continue
            caps[natura] = max(1.0, min(100.0, pct)) / 100.0

        settings = load_settings()
        settings.setdefault("sator", {})
        settings["sator"]["score_weights"] = weights
        settings["sator"]["bucket_first_allocation"] = bool(bucket_first_allocation)
        settings["sator"]["band_tolerance_pp"] = max(0.0, min(20.0, float(band_tolerance_pp or 0))) / 100.0
        settings["sator"]["instrument_quota_tolerance_pp"] = max(0.0, min(20.0, float(instrument_quota_tolerance_pp or 0))) / 100.0
        if caps:
            settings["sator"]["concentration_caps"] = caps
        try:
            save_settings(settings)
        except Exception as exc:
            logger.error("Errore salvataggio impostazioni SATOR: %s", exc, exc_info=True)
            return HTMLResponse(_render_quote_interne_page(err_msg=f"Errore durante il salvataggio: {exc}"))
        return RedirectResponse("/quote-interne?ok=Impostazioni%20salvate.", status_code=303)

    if azione != "salva_quote":
        return HTMLResponse(_render_quote_interne_page(err_msg="Azione non riconosciuta."))

    try:
        parsed = json.loads(quotas_json) if quotas_json.strip() else {}
    except json.JSONDecodeError:
        return HTMLResponse(_render_quote_interne_page(err_msg="Dati quote non validi."))

    if not isinstance(parsed, dict):
        return HTMLResponse(_render_quote_interne_page(err_msg="Dati quote non validi."))

    # Ticker ammessi a scrivere NO_SELL in questo submit: esattamente le
    # chiavi di quotas_json, cioe' i ticker per cui _render_quote_interne_page
    # ha renderizzato sia l'input quota sia la checkbox NO_SELL nello stesso
    # ciclo (vedi Step 4). collectQuotas() lato client invia sempre tutte le
    # righe visibili di ogni bucket (anche quelle a 0, anche nei bucket
    # "non toccati"), quindi questo insieme coincide con "ticker mostrati in
    # pagina in questo momento" - mai l'intero catalogo strumenti.
    allowed_no_sell_tickers: set[str] = {
        str(ticker or "").strip().upper()
        for bucket, weights in parsed.items()
        if bucket in _BUCKETS and isinstance(weights, dict)
        for ticker in weights.keys()
        if str(ticker or "").strip()
    }

    # Opt-in per bucket (garanzia centrale della feature, confermata dal
    # proprietario del progetto): un bucket dove l'utente ha lasciato tutti i
    # valori a 0/vuoto va trattato come "mai configurato", non come una
    # richiesta di 0% ovunque - altrimenti sarebbe impossibile salvare le
    # quote di un solo bucket lasciando gli altri due intonsi (collectQuotas()
    # lato client invia sempre tutti e tre i bucket con 0 per i campi vuoti).
    # Un bucket "toccato" (almeno un valore > 0) resta invece soggetto alla
    # regola stretta e viene validato/scritto per intero, zeri espliciti
    # compresi (uno zero esplicito su uno strumento posseduto e' un target
    # valido, diverso da "quota mancante").
    for bucket, weights in parsed.items():
        if bucket not in _BUCKETS or not isinstance(weights, dict):
            continue
        numeric_weights = {str(t or "").strip().upper(): float(v or 0.0) for t, v in weights.items()}
        if not any(v > 0 for v in numeric_weights.values()):
            continue  # bucket non toccato: nessuna validazione, resta opt-out
        total = sum(numeric_weights.values())
        if abs(total - 100.0) > 0.5:
            return HTMLResponse(_render_quote_interne_page(
                err_msg=f"Le quote di {bucket} non somma a 100 (somma attuale: {total:.1f})."
            ))

    settings = load_settings()
    settings.setdefault("sator", {})
    normalized: dict[str, dict[str, float]] = {b: {} for b in _BUCKETS}
    for bucket, weights in parsed.items():
        if bucket not in _BUCKETS or not isinstance(weights, dict):
            continue
        numeric_weights = {
            str(ticker or "").strip().upper(): float(weight or 0.0)
            for ticker, weight in weights.items()
            if str(ticker or "").strip()
        }
        if not any(v > 0 for v in numeric_weights.values()):
            continue  # bucket non toccato (tutti zero/vuoti): resta {} come se mai configurato

        # Normalizza a somma esattamente 1.0 (il form accetta +-0.5pp di
        # tolleranza attorno a 100, ma _compute_instrument_quota_status in
        # core/services/sator.py richiede abs(sum_target - 1.0) < 1e-6: cio'
        # che viene salvato deve gia' essere esatto). Metodo del resto
        # piu' grande: arrotonda tutti i ticker tranne quello di peso
        # maggiore, poi quest'ultimo assorbe il residuo cosi' la somma
        # finale non si discosta da 1.0 per errori di arrotondamento.
        total = sum(numeric_weights.values())
        tickers = list(numeric_weights.keys())
        top_ticker = max(tickers, key=lambda t: numeric_weights[t])
        fracs: dict[str, float] = {}
        for tk in tickers:
            if tk == top_ticker:
                continue
            fracs[tk] = round(numeric_weights[tk] / total, 6)
        fracs[top_ticker] = round(1.0 - sum(fracs.values()), 6)
        normalized[bucket] = fracs
    settings["sator"]["instrument_quotas"] = normalized

    form_data_all = dict(await request.form())
    data_for_no_sell = load_data()
    if apply_no_sell_from_form(data_for_no_sell, form_data_all, allowed_tickers=allowed_no_sell_tickers):
        save_data(data_for_no_sell)

    try:
        save_settings(settings)
    except Exception as exc:
        logger.error("Errore salvataggio quote interne: %s", exc, exc_info=True)
        return HTMLResponse(_render_quote_interne_page(err_msg=f"Errore durante il salvataggio: {exc}"))

    return RedirectResponse("/quote-interne?ok=Quote%20salvate.", status_code=303)
