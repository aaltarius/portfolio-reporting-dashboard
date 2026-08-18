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

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from core.services.sator import compute_instrument_buckets, compute_instrument_quota_status, ensure_sator_settings
from ui.form_server.shell import STREAMLIT_URL, _ROOT_VARS_BLOCK

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
.alert-ok{background:var(--emerald-50,#ecfdf5);color:var(--emerald-700,#047857);padding:10px 14px;border-radius:10px;margin-bottom:14px}
.alert-warn{background:var(--rose-50,#fff1f2);color:var(--rose-700,#be123c);padding:10px 14px;border-radius:10px;margin-bottom:14px}
.btn-salva{padding:9px 24px;background:var(--indigo-500);color:var(--white);border:none;border-radius:9px;font-size:.9rem;font-weight:700;cursor:pointer}
</style>"""


def _bucket_tickers(data: dict) -> dict[str, list[str]]:
    from core.services.sator import _tickers_posseduti  # riuso privato intenzionale, stesso file di dominio
    from core.finance import compute_portfolio_state

    state_df = compute_portfolio_state(data, include_closed=True).get("df")
    if data.get("_positions_df") is not None and not data["_positions_df"].empty:
        state_df = data["_positions_df"]
    held = _tickers_posseduti(state_df) if state_df is not None else set()
    buckets = compute_instrument_buckets(data, held)
    out: dict[str, list[str]] = {b: [] for b in _BUCKETS}
    for ticker, bucket in buckets.items():
        out.setdefault(bucket, []).append(ticker)
    for b in out:
        out[b].sort()
    return out


def _render_quote_interne_page(*, ok_msg: str = "", err_msg: str = "") -> str:
    from persistence.storage import load_data, load_settings

    data = load_data()
    settings = load_settings()
    cfg = ensure_sator_settings(settings)
    tickers_by_bucket = _bucket_tickers(data)
    status = compute_instrument_quota_status(data, settings)

    ok_html = f'<div class="alert-ok">{escape(ok_msg)}</div>' if ok_msg else ""
    err_html = f'<div class="alert-warn">{escape(err_msg)}</div>' if err_msg else ""

    bucket_sections = []
    for bucket in _BUCKETS:
        tickers = tickers_by_bucket.get(bucket, [])
        quotas = cfg["instrument_quotas"].get(bucket, {})
        if not tickers:
            bucket_sections.append(f'<div class="qi-card"><h2>{bucket}</h2><p>Nessuno strumento posseduto in questo bucket.</p></div>')
            continue
        rows = "".join(
            f'<div class="qi-row"><label>{escape(ticker)}</label>'
            f'<input type="number" min="0" max="100" step="0.5" '
            f'data-bucket="{bucket}" data-ticker="{escape(ticker)}" '
            f'value="{quotas.get(ticker, 0.0) * 100:.1f}" class="qi-input"></div>'
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
        status_rows.append(f"<tr><td>{bucket}</td><td>{stato_label}</td><td>{s['sum_target']*100:.1f}%</td></tr>")

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

    return f"""<!DOCTYPE html>
<html lang="it">
<head><meta charset="utf-8"><title>Quote & impostazioni</title>{_CSS}</head>
<body>
<div class="qi">
  <h1>Quote interne per bucket</h1>
  {ok_html}{err_html}
  <form method="post" action="/quote-interne" onsubmit="return collectQuotas()">
    <input type="hidden" name="azione" value="salva_quote">
    <input type="hidden" name="quotas_json" id="quotas_json">
    {"".join(bucket_sections)}
    <button type="submit" class="btn-salva">Salva quote</button>
  </form>
  <div class="qi-card">
    <h2>Stato attuale</h2>
    <table><thead><tr><th>Bucket</th><th>Stato</th><th>Somma quote</th></tr></thead>
    <tbody>{"".join(status_rows)}</tbody></table>
  </div>
  {settings_section}
  <p><a href="{STREAMLIT_URL}">&larr; Torna all'app</a></p>
</div>
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
async def get_quote_interne(ok: str = "", err: str = ""):
    return HTMLResponse(_render_quote_interne_page(ok_msg=ok, err_msg=err))


@router.post("/quote-interne", response_class=HTMLResponse)
async def post_quote_interne(
    azione: str = Form(""),
    quotas_json: str = Form(""),
    w_fit: str = Form("30"), w_mom: str = Form("25"), w_risk: str = Form("20"),
    w_div: str = Form("15"), w_cost: str = Form("10"),
    bucket_first_allocation: str = Form(""),
    band_tolerance_pp: str = Form("3"),
):
    from persistence.storage import load_settings, save_settings

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
        settings = load_settings()
        settings.setdefault("sator", {})
        settings["sator"]["score_weights"] = weights
        settings["sator"]["bucket_first_allocation"] = bool(bucket_first_allocation)
        settings["sator"]["band_tolerance_pp"] = max(0.0, min(20.0, float(band_tolerance_pp or 0))) / 100.0
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

    for bucket, weights in parsed.items():
        if bucket not in _BUCKETS or not isinstance(weights, dict):
            continue
        total = sum(float(v or 0.0) for v in weights.values())
        if weights and abs(total - 100.0) > 0.5:
            return HTMLResponse(_render_quote_interne_page(
                err_msg=f"Le quote di {bucket} non somma a 100 (somma attuale: {total:.1f})."
            ))

    settings = load_settings()
    settings.setdefault("sator", {})
    normalized: dict[str, dict[str, float]] = {b: {} for b in _BUCKETS}
    for bucket, weights in parsed.items():
        if bucket not in _BUCKETS or not isinstance(weights, dict):
            continue
        for ticker, weight in weights.items():
            tk = str(ticker or "").strip().upper()
            if tk:
                normalized[bucket][tk] = round(float(weight or 0.0) / 100.0, 6)
    settings["sator"]["instrument_quotas"] = normalized

    try:
        save_settings(settings)
    except Exception as exc:
        logger.error("Errore salvataggio quote interne: %s", exc, exc_info=True)
        return HTMLResponse(_render_quote_interne_page(err_msg=f"Errore durante il salvataggio: {exc}"))

    return RedirectResponse("/quote-interne?ok=Quote%20salvate.", status_code=303)
