from __future__ import annotations

import html
import json
import math
from datetime import date

import pandas as pd
from core.config import COLORS
from core.domain.calendar import CEDOLA_FREQ_MONTHS, CEDOLA_FREQ_PAYMENTS, TAX_RATE_GOV_PCT, build_btp_calendar
from persistence.storage import macro_cat
from ui.charts.instrument_badges import ISSUER_BADGE_CSS, commission_badge, issuer_badge
from ui.charts.natura_icons import get_natura_visual
from ui.formatting import fmt_eur_it, fmt_num_it, fmt_pct_it
from ui.streamlit_compat import iframe_height_for_rows, render_html_iframe
from ui.theme import CATEGORY_COLORS, macro_color

# Modulo shared HTML/popup.
# Ruolo:
# - render tabella portafoglio arricchita con popup dettagli strumento
# - usato come supporto UI trasversale, non associato a un chart_id Plotly
#
# render_quotes_table_with_popup (l'altra funzione che viveva qui) e' stata
# rimossa il 2026-07-07: duplicata di ui/charts/quotes_popup.py, che e' la
# versione realmente importata da ui/pages/quotazioni.py — verificato con
# grep sull'intero repo.


def _build_ticker_info(df, data):
    """Dizionario per-ticker (nome/isin/prezzo/pmc/... + sparkline) usato dal modale di dettaglio.

    Condiviso da render_portfolio_table_with_popup e render_weekly_pl_table
    cosi' il click sul ticker apre lo stesso identico popup in entrambe le tabelle.
    """
    storico = data.get("storico_prezzi", {}) or {}
    info_map = {s["ticker"]: s for s in data.get("strumenti", [])}
    ds_sorted = sorted(storico.keys())[-60:]
    ticker_info = {}
    for _, row in df.iterrows():
        tk = str(row.get("Ticker", ""))
        info = info_map.get(tk, {})
        spark = []
        for d in ds_sorted:
            v = storico[d].get(tk)
            if v is not None:
                try:
                    spark.append({"d": d, "v": float(v)})
                except Exception:
                    pass
        try:
            _pl_e = float(row.get("P/L €", 0) or 0)
            _pl_p = float(row.get("P/L %", 0) or 0)
            _prezzo = float(row.get("Prezzo", 0) or 0)
            _pmc = float(row.get("PMC", 0) or 0)
            _qty = float(row.get("Quote", 0) or 0)
            _ctv = float(row.get("Controvalore", 0) or 0)
            _costo = float(row.get("Costo", 0) or 0)
            _comm = float(row.get("Comm.", 0) or 0)
        except Exception:
            _pl_e = _pl_p = _prezzo = _pmc = _qty = _ctv = _costo = _comm = 0.0
        ticker_info[tk] = {
            "nome": info.get("nome", tk),
            "isin": info.get("isin", "n/d"),
            "tipo": info.get("tipo", "n/d"),
            "fonte": info.get("fonte", "n/d"),
            "aggiornato": info.get("aggiornato", "n/d"),
            "prezzo": _prezzo,
            "pmc": _pmc,
            "qty": _qty,
            "ctv": _ctv,
            "costo": _costo,
            "comm": _comm,
            "pl_e": _pl_e,
            "pl_p": _pl_p,
            "spark": spark,
        }
    return ticker_info


def _fmt_date_it(value) -> str:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return "n/d"
    return ts.strftime("%d/%m/%Y")


def _as_float_or_none(value) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _safe_btp_tax_rate(value) -> float:
    raw = _as_float_or_none(value)
    if raw is None:
        return TAX_RATE_GOV_PCT / 100.0
    return raw if raw <= 1.0 else raw / 100.0


def _next_coupon_from_anagrafica(
    strumento: dict,
    today: pd.Timestamp,
    scadenza: pd.Timestamp,
) -> tuple[pd.Timestamp | None, float | None]:
    cedola_perc = _as_float_or_none(strumento.get("cedola_perc"))
    if cedola_perc is None or cedola_perc <= 0:
        return None, None
    first_coupon = pd.to_datetime(
        strumento.get("prima_cedola") or strumento.get("data_origine") or today,
        errors="coerce",
    )
    if pd.isna(first_coupon):
        return None, None
    freq = str(strumento.get("cedola_frequenza", "annuale") or "annuale").strip().lower()
    current = first_coupon.normalize()
    while current < today and current <= scadenza:
        current = current + pd.DateOffset(months=CEDOLA_FREQ_MONTHS.get(freq, 12))
    if current > scadenza:
        return None, None
    nominale = _as_float_or_none(strumento.get("nominale")) or 100.0
    quantita = _as_float_or_none(strumento.get("quantita")) or 1.0
    payments_per_year = CEDOLA_FREQ_PAYMENTS.get(freq, 1)
    tax_rate = _safe_btp_tax_rate(strumento.get("aliquota_cedola"))
    amount = (cedola_perc / 100.0) * nominale / payments_per_year * quantita * (1.0 - tax_rate)
    return current, amount


def _parse_decimal_it(value) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _as_float_or_none(value)
    text = str(value).strip().replace("%", "").replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")
    return _as_float_or_none(text)


def _coupon_bounds_from_maturity(scadenza: pd.Timestamp, today: pd.Timestamp, freq: str) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    step_months = CEDOLA_FREQ_MONTHS.get(str(freq or "").strip().lower(), 12)
    if step_months <= 0:
        step_months = 12
    next_coupon = scadenza.normalize()
    # I BTP ordinari pagano sulle date allineate alla scadenza. Risalire dalla
    # scadenza evita di dipendere da prima_cedola/data_origine, spesso legate
    # all'acquisto e non al periodo cedolare corrente.
    while next_coupon > today:
        prev_coupon = next_coupon - pd.DateOffset(months=step_months)
        if prev_coupon <= today:
            return prev_coupon.normalize(), next_coupon.normalize()
        next_coupon = prev_coupon.normalize()
    return next_coupon.normalize(), (next_coupon + pd.DateOffset(months=step_months)).normalize()


def _estimate_btp_accrued_interest(strumento: dict, today: pd.Timestamp) -> dict[str, object]:
    cedola_perc = _parse_decimal_it(strumento.get("cedola_perc"))
    scadenza = pd.to_datetime(strumento.get("scadenza"), errors="coerce")
    if cedola_perc is None or cedola_perc <= 0 or pd.isna(scadenza):
        return {
            "accrued_interest_net": None,
            "accrued_interest_gross": None,
            "accrued_interest_days": None,
            "accrued_interest_period_days": None,
        }
    last_coupon, next_coupon = _coupon_bounds_from_maturity(scadenza.normalize(), today, strumento.get("cedola_frequenza"))
    if last_coupon is None or next_coupon is None or next_coupon <= last_coupon:
        return {
            "accrued_interest_net": None,
            "accrued_interest_gross": None,
            "accrued_interest_days": None,
            "accrued_interest_period_days": None,
        }
    nominale = _parse_decimal_it(strumento.get("nominale")) or 100.0
    quantita = _parse_decimal_it(strumento.get("quantita")) or 1.0
    payments_per_year = CEDOLA_FREQ_PAYMENTS.get(str(strumento.get("cedola_frequenza", "annuale") or "annuale").strip().lower(), 1)
    coupon_gross = nominale * quantita * (cedola_perc / 100.0) / payments_per_year
    elapsed_days = max(int((today - last_coupon).days), 0)
    period_days = max(int((next_coupon - last_coupon).days), 1)
    gross = coupon_gross * min(elapsed_days, period_days) / period_days
    net = gross * (1.0 - _safe_btp_tax_rate(strumento.get("aliquota_cedola")))
    return {
        "accrued_interest_net": net,
        "accrued_interest_gross": gross,
        "accrued_interest_days": elapsed_days,
        "accrued_interest_period_days": period_days,
        "accrued_interest_last_coupon": last_coupon,
        "accrued_interest_next_coupon": next_coupon,
    }


def _build_btp_badge_map(data: dict) -> dict[str, dict[str, object]]:
    """Micro-sintesi GOV/BTP per la tabella Controvalore.

    Usa il calendario BTP gia' disponibile nel dominio: niente scraping, niente
    refresh rete. Se il calendario non e' costruibile, il chiamante mostra solo
    celle vuote.
    """
    try:
        calendar_df = build_btp_calendar(data)
    except Exception:
        calendar_df = pd.DataFrame()

    today = pd.Timestamp(date.today()).normalize()
    next_12m = today + pd.DateOffset(months=12)
    out: dict[str, dict[str, object]] = {}
    if calendar_df is not None and not calendar_df.empty:
        work = calendar_df.copy()
        work["data"] = pd.to_datetime(work.get("data"), errors="coerce")
        work = work.dropna(subset=["data"])
        work = work[work["tipo_riga"].astype(str).eq("evento")].copy()
        work["importo"] = pd.to_numeric(work.get("importo"), errors="coerce").fillna(0.0)

        for ticker, group in work.groupby(work["ticker"].astype(str), dropna=False):
            future = group[group["data"] >= today].sort_values("data")
            coupons = future[future["tipo_evento"].astype(str).str.lower().eq("cedola")]
            maturities = future[future["tipo_evento"].astype(str).str.lower().eq("scadenza")]
            next_coupon = coupons.iloc[0] if not coupons.empty else None
            next_maturity = maturities.iloc[0] if not maturities.empty else None
            coupon_12m = float(coupons.loc[coupons["data"] <= next_12m, "importo"].sum()) if not coupons.empty else 0.0
            days_coupon = int((pd.Timestamp(next_coupon["data"]).normalize() - today).days) if next_coupon is not None else None
            days_maturity = int((pd.Timestamp(next_maturity["data"]).normalize() - today).days) if next_maturity is not None else None
            out[str(ticker)] = {
                "next_coupon_date": next_coupon["data"] if next_coupon is not None else None,
                "next_coupon_amount": float(next_coupon["importo"]) if next_coupon is not None else 0.0,
                "days_coupon": days_coupon,
                "maturity_date": next_maturity["data"] if next_maturity is not None else None,
                "maturity_amount": float(next_maturity["importo"]) if next_maturity is not None else 0.0,
                "days_maturity": days_maturity,
                "coupon_12m": coupon_12m,
            }

    # Fallback anagrafico: utile quando l'anagrafica usa gia' "GOV" come
    # tipo sintetico e il calendario BTP di dominio non la include.
    for strumento in data.get("strumenti", []) or []:
        if macro_cat(strumento.get("tipo", "")) != "GOV":
            continue
        ticker = str(strumento.get("ticker") or "").strip()
        if not ticker:
            continue
        maturity_date = pd.to_datetime(strumento.get("scadenza"), errors="coerce")
        if pd.isna(maturity_date):
            continue
        maturity_date = maturity_date.normalize()
        entry = out.setdefault(ticker, {
            "next_coupon_date": None,
            "next_coupon_amount": None,
            "days_coupon": None,
            "maturity_date": None,
            "maturity_amount": None,
            "days_maturity": None,
            "coupon_12m": 0.0,
        })
        if entry.get("maturity_date") is None:
            nominale = _as_float_or_none(strumento.get("nominale")) or 100.0
            quantita = _as_float_or_none(strumento.get("quantita")) or 1.0
            entry["maturity_date"] = maturity_date
            entry["maturity_amount"] = nominale * quantita
            entry["days_maturity"] = int((maturity_date - today).days)
        if entry.get("next_coupon_date") is None:
            coupon_date, coupon_amount = _next_coupon_from_anagrafica(strumento, today, maturity_date)
            if coupon_date is not None:
                entry["next_coupon_date"] = coupon_date
                entry["next_coupon_amount"] = coupon_amount
                entry["days_coupon"] = int((coupon_date - today).days)
                if coupon_date <= next_12m:
                    entry["coupon_12m"] = float(coupon_amount or 0.0)
        entry.update(_estimate_btp_accrued_interest(strumento, today))
    return out


def _btp_info_badge(ticker: str, info: dict, status: dict[str, object] | None) -> str:
    if not status:
        return ""

    days_coupon = status.get("days_coupon")
    days_maturity = status.get("days_maturity")
    if isinstance(days_maturity, int) and days_maturity <= 180:
        cls, label, sort = "btp-maturity", "◆", 0
    elif isinstance(days_coupon, int) and days_coupon <= 45:
        cls, label, sort = "btp-coupon", "●", 1
    else:
        cls, label, sort = "btp-info", "●", 2

    coupon_parts = []
    if status.get("next_coupon_date") is not None:
        coupon_parts.append(
            f"Prossima cedola: {_fmt_date_it(status.get('next_coupon_date'))}"
            f" ({fmt_eur_it(status.get('next_coupon_amount'), 2)})"
        )
    if status.get("maturity_date") is not None:
        coupon_parts.append(
            f"Scadenza: {_fmt_date_it(status.get('maturity_date'))}"
            f" ({fmt_eur_it(status.get('maturity_amount'), 2)})"
        )
    coupon_parts.append(f"Cedole nette 12 mesi: {fmt_eur_it(status.get('coupon_12m'), 2)}")
    if status.get("accrued_interest_net") is not None:
        days = status.get("accrued_interest_days")
        period_days = status.get("accrued_interest_period_days")
        coupon_parts.append(
            "Rateo stimato oggi: "
            f"{fmt_eur_it(status.get('accrued_interest_net'), 2)} netto "
            f"({fmt_eur_it(status.get('accrued_interest_gross'), 2)} lordo; {days}/{period_days} gg)"
        )
    else:
        coupon_parts.append("Rateo stimato oggi: n/d")
    cached_rateo = []
    if info.get("rateo_netto") not in (None, ""):
        cached_rateo.append(f"netto {info.get('rateo_netto')}/100")
    if info.get("rateo_lordo") not in (None, ""):
        cached_rateo.append(f"lordo {info.get('rateo_lordo')}/100")
    if cached_rateo:
        coupon_parts.append("Rateo cache Borsa: " + ", ".join(cached_rateo))
    if info.get("rateo_disaggio") not in (None, ""):
        coupon_parts.append(f"Rateo disaggio cache: {info.get('rateo_disaggio')}/100")
    if info.get("cedola_perc") not in (None, ""):
        coupon_parts.append(f"Cedola annua: {info.get('cedola_perc')}%")
    title = " | ".join(str(part) for part in coupon_parts)
    return (
        f'<span class="btp-pill {cls}" data-sort="{sort}" '
        f'title="{html.escape(title, quote=True)}" aria-label="Info BTP {html.escape(ticker, quote=True)}">{label}</span>'
    )


def _mini_sparkline_svg(
    points,
    pl_positive: bool | None = None,
    reference_value: float | None = None,
    width: int = 72,
    height: int = 30,
) -> tuple[str, float]:
    """Mini grafico inline usato nella tabella principale, basato sulla sparkline del popup."""
    values: list[float] = []
    for point in points or []:
        try:
            values.append(float(point.get("v")))
        except Exception:
            continue
    if len(values) < 2:
        return '<span class="mini-spark-empty">—</span>', 0.0

    first = values[0]
    last = values[-1]
    sort_return = (last / first - 1.0) if abs(first) > 1e-12 else 0.0
    positive_color = (last >= first) if pl_positive is None else bool(pl_positive)
    color = COLORS["success"] if positive_color else COLORS["danger"]
    fill = "rgba(30,132,73,0.10)" if positive_color else "rgba(255,75,75,0.10)"

    try:
        ref = float(reference_value) if reference_value is not None else None
    except Exception:
        ref = None
    if ref is not None and abs(ref) <= 1e-12:
        ref = None

    scale_values = values + ([ref] if ref is not None else [])
    mn = min(scale_values)
    mx = max(scale_values)
    rng = mx - mn or 0.001
    pad = 2
    usable_w = width - pad * 2
    usable_h = height - pad * 2

    def to_y(value: float) -> float:
        return height - pad - ((value - mn) / rng) * usable_h

    coords: list[tuple[float, float]] = []
    for idx, value in enumerate(values):
        x = pad + (idx / (len(values) - 1)) * usable_w
        y = to_y(value)
        coords.append((x, y))

    line_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    area_points = f"{pad},{height - pad} {line_points} {width - pad},{height - pad}"
    dot_x, dot_y = coords[-1]
    ref_line = ""
    if ref is not None:
        ref_y = to_y(ref)
        ref_line = (
            f'<line class="mini-spark-pmc" x1="{pad}" x2="{width - pad}" y1="{ref_y:.1f}" y2="{ref_y:.1f}" '
            f'stroke="#6B7280" stroke-width="1" stroke-dasharray="4 3" opacity="0.72"></line>'
        )
    svg = (
        f'<svg class="mini-spark" viewBox="0 0 {width} {height}" preserveAspectRatio="none" aria-hidden="true">'
        f'<polygon points="{area_points}" fill="{fill}"></polygon>'
        f'{ref_line}'
        f'<polyline points="{line_points}" fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"></polyline>'
        f'<circle cx="{dot_x:.1f}" cy="{dot_y:.1f}" r="2.1" fill="{color}"></circle>'
        f'</svg>'
    )
    return svg, sort_return


_MODAL_CSS = """
a.tk-link{text-decoration:none;font-weight:700;cursor:pointer;border-bottom:1.5px dotted;transition:opacity .15s;}
a.tk-link:hover{opacity:0.65;}
#mo{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;align-items:center;justify-content:center;}
#mo.on{display:flex;}
#mc{background:#fff;border-radius:18px;padding:20px 24px 18px;max-width:900px;width:97%;max-height:90vh;overflow-y:auto;box-shadow:0 12px 52px rgba(0,0,0,.26);position:relative;color:#1f2937;}
#mc-close{position:absolute;top:10px;right:14px;cursor:pointer;font-size:1.3rem;color:#9ca3af;background:none;border:none;line-height:1;}
#mc-close:hover{color:#374151;}
.mc-cols{display:grid;grid-template-columns:40% 60%;gap:18px;align-items:start;}
.mc-left{min-width:0;}
.mc-right{min-width:0;display:flex;flex-direction:column;gap:8px;}
.mc-ticker{font-size:1.8rem;font-weight:900;letter-spacing:-.01em;margin-bottom:2px;}
.mc-nome{font-size:1.0rem;color:#374151;font-weight:600;}
.mc-meta{font-size:0.85rem;color:#9ca3af;margin:4px 0 12px;}
.mc-grid{display:grid;grid-template-columns:1fr 1fr;gap:5px;}
.mc-kpi{border:1px solid #e5e7eb;border-radius:8px;padding:8px 12px;}
.mc-kpi-l{font-size:0.82rem;text-transform:uppercase;color:#9ca3af;font-weight:700;letter-spacing:.04em;margin-bottom:3px;}
.mc-kpi-v{font-size:1.15rem;font-weight:700;font-variant-numeric:tabular-nums;}
.pos{color:#1E8449;} .neg{color:#FF4B4B;}
.mc-price-box{background:#f9fafb;border:1px solid #e5e7eb;border-radius:11px;padding:10px 14px;display:flex;align-items:baseline;gap:12px;}
.mc-price-val{font-size:2.0rem;font-weight:800;font-variant-numeric:tabular-nums;}
.mc-price-sub{font-size:0.95rem;color:#6b7280;}
.mc-spark-label{font-size:0.78rem;text-transform:uppercase;color:#9ca3af;font-weight:700;letter-spacing:.05em;}
svg.spark{width:100%;height:140px;display:block;border-radius:10px;background:#f9fafb;}
.mc-footer{font-size:0.78rem;color:#9ca3af;}
"""
_MODAL_CSS = _MODAL_CSS.replace("#1E8449", COLORS["success"]).replace("#FF4B4B", COLORS["danger"])

_MODAL_HTML = """
<div id="mo" onclick="if(event.target===this)closeM()">
<div id="mc">
  <button id="mc-close" onclick="closeM()">&#x2715;</button>
  <div class="mc-cols">
    <div class="mc-left">
      <div class="mc-ticker" id="m-tk"></div>
      <div class="mc-nome" id="m-nm"></div>
      <div class="mc-meta" id="m-meta"></div>
      <div class="mc-grid" id="m-grid"></div>
    </div>
    <div class="mc-right">
      <div class="mc-price-box">
        <div>
          <div style="font-size:0.78rem;text-transform:uppercase;color:#9ca3af;font-weight:700;margin-bottom:2px;">Prezzo attuale</div>
          <div class="mc-price-val" id="m-px"></div>
        </div>
        <div id="m-delta" class="mc-price-sub"></div>
      </div>
      <div class="mc-spark-label">Andamento prezzo (ultimi 60 giorni disponibili)</div>
      <svg class="spark" id="m-spark" viewBox="0 0 520 140" preserveAspectRatio="none"></svg>
      <div class="mc-footer" id="m-footer"></div>
    </div>
  </div>
</div>
</div>
"""

_MODAL_JS = """
var D=__TICKER_JSON__;
function fi(v,d,sgn){
  if(v==null||isNaN(v))return'n/d';
  var n=parseFloat(v).toLocaleString('it-IT',{minimumFractionDigits:d,maximumFractionDigits:d});
  return (sgn&&v>0?'+':'')+n;
}
function fe(v,d,sgn){return fi(v,d!=null?d:2,sgn)+' €';}
function fmtDateIt(v){if(!v)return 'n/d';var p=String(v).slice(0,10).split('-');return p.length===3?(p[2]+'/'+p[1]+'/'+p[0]):String(v);}
function fp(v,d,sgn){
  if(v==null||isNaN(v))return'n/d';
  var pct=parseFloat(v)*100;
  var n=pct.toLocaleString('it-IT',{minimumFractionDigits:d!=null?d:1,maximumFractionDigits:d!=null?d:1});
  return(sgn&&pct>0?'+':'')+n+'%';
}
function kpi(label,val,cls){
  return '<div class="mc-kpi"><div class="mc-kpi-l">'+label+'</div><div class="mc-kpi-v'+(cls?' '+cls:'')+'">'+val+'</div></div>';
}
function sparkline(data,plPositive,pmc){
  var svg=document.getElementById('m-spark');
  svg.innerHTML='';
  var W=520,H=140,pad=6;
  if(!data||data.length<2){
    var t=document.createElementNS('http://www.w3.org/2000/svg','text');
    t.setAttribute('x','50%');t.setAttribute('y','52%');t.setAttribute('text-anchor','middle');
    t.setAttribute('fill','#d1d5db');t.setAttribute('font-size','10');t.setAttribute('font-family','system-ui');
    t.textContent='Dati storici non disponibili';svg.appendChild(t);return;
  }
  var vals=data.map(function(p){return p.v;});
  var mn=Math.min.apply(null,vals),mx=Math.max.apply(null,vals);if(pmc!=null&&!isNaN(pmc)){mn=Math.min(mn,pmc);mx=Math.max(mx,pmc);}var rng=mx-mn||0.001;var toY=function(v){return H-pad-((v-mn)/rng*(H-pad*2));};
  var pts=[];
  vals.forEach(function(v,i){
    var x=pad+(i/(vals.length-1))*(W-pad*2);
    var y=toY(v);
    pts.push(x.toFixed(1)+','+y.toFixed(1));
  });
  var col=plPositive?'#1E8449':'#FF4B4B';
  var fill=plPositive?'rgba(30,132,73,0.12)':'rgba(255,75,75,0.12)';
  var lx=parseFloat(pts[vals.length-1].split(',')[0]),ly=parseFloat(pts[vals.length-1].split(',')[1]);var pmcY=(pmc!=null&&!isNaN(pmc))?toY(pmc):null;
  var area=document.createElementNS('http://www.w3.org/2000/svg','polygon');
  area.setAttribute('points',pts[0].split(',')[0]+','+(H-pad)+' '+pts.join(' ')+' '+lx+','+(H-pad));
  area.setAttribute('fill',fill);svg.appendChild(area);if(pmcY!=null){var pmcLine=document.createElementNS('http://www.w3.org/2000/svg','line');pmcLine.setAttribute('x1',pad);pmcLine.setAttribute('x2',W-pad);pmcLine.setAttribute('y1',pmcY);pmcLine.setAttribute('y2',pmcY);pmcLine.setAttribute('stroke','#6b7280');pmcLine.setAttribute('stroke-width','1.8');pmcLine.setAttribute('stroke-dasharray','7 5');pmcLine.setAttribute('opacity','0.98');svg.appendChild(pmcLine);var pmcText=document.createElementNS('http://www.w3.org/2000/svg','text');pmcText.setAttribute('x',W-pad-4);pmcText.setAttribute('y',Math.max(12,pmcY-4));pmcText.setAttribute('text-anchor','end');pmcText.setAttribute('fill','#4b5563');pmcText.setAttribute('font-size','10');pmcText.setAttribute('font-family','system-ui');pmcText.textContent='PMC';svg.appendChild(pmcText);}
  var line=document.createElementNS('http://www.w3.org/2000/svg','polyline');
  line.setAttribute('points',pts.join(' '));
  line.setAttribute('fill','none');line.setAttribute('stroke',col);line.setAttribute('stroke-width','2');
  svg.appendChild(line);
  var dot=document.createElementNS('http://www.w3.org/2000/svg','circle');
  dot.setAttribute('cx',lx);dot.setAttribute('cy',ly);dot.setAttribute('r','4');
  dot.setAttribute('fill',col);dot.setAttribute('stroke','#fff');dot.setAttribute('stroke-width','1.5');
  svg.appendChild(dot);
}
function showModal(tk){
  var d=D[tk];if(!d)return;
  var plCls=d.pl_e>=0?'pos':'neg';
  var delta=d.pmc>0?(d.prezzo/d.pmc-1)*100:null;
  document.getElementById('m-tk').textContent=tk;
  document.getElementById('m-tk').style.color=d.pl_e>=0?'#1E8449':'#374151';
  document.getElementById('m-nm').textContent=d.nome;
  document.getElementById('m-meta').textContent='ISIN: '+d.isin+' · '+d.tipo;
  document.getElementById('m-px').textContent=fe(d.prezzo,3,false);
  document.getElementById('m-px').className='mc-price-val '+plCls;
  document.getElementById('m-delta').innerHTML=delta!=null?'<span class="'+plCls+'">'+(delta>=0?'+':'')+fi(delta,2,false)+'% vs PMC</span>':'';
  document.getElementById('m-grid').innerHTML=
    kpi('PMC',fe(d.pmc,3,false))+
    kpi('Quantità',fi(d.qty,3,false))+
    kpi('Controvalore',fe(d.ctv,2,false))+
    kpi('Costo storico',fe(d.costo,2,false))+
    kpi('P/L €',fe(d.pl_e,2,true),plCls)+
    kpi('P/L %',fp(d.pl_p,2,true),plCls)+
    kpi('Commissioni',fe(d.comm,2,false))+
    kpi('Fonte / Agg.',d.fonte+' · '+fmtDateIt(d.aggiornato));
  sparkline(d.spark,d.pl_e>=0,d.pmc);
  document.getElementById('m-footer').textContent='Quotazione aggiornata al '+fmtDateIt(d.aggiornato)+' · Fonte: '+d.fonte;
  document.getElementById('mo').classList.add('on');
}
function closeM(){document.getElementById('mo').classList.remove('on');}
document.addEventListener('keydown',function(e){if(e.key==='Escape')closeM();});
"""
_MODAL_JS = _MODAL_JS.replace("#1E8449", COLORS["success"]).replace("#FF4B4B", COLORS["danger"])

_NEUTRAL_COLOR = "#9CA3AF"
_DAILY_EUR_DISPLAY_EPS = 0.005
_DAILY_PCT_DISPLAY_EPS = 0.00005


def _as_finite_float(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _zero_for_display(value, eps):
    if value is None:
        return None
    return 0.0 if abs(value) < eps else value


def _daily_variation_color(value, eps):
    if value is None:
        return _NEUTRAL_COLOR
    if value > eps:
        return COLORS["success"]
    if value < -eps:
        return COLORS["danger"]
    return _NEUTRAL_COLOR


def _signed_state(value, eps):
    if value is None:
        return 0
    if value > eps:
        return 1
    if value < -eps:
        return -1
    return 0


def _daily_variation_colors(day_delta, day_pct):
    delta_col = _daily_variation_color(day_delta, _DAILY_EUR_DISPLAY_EPS)
    pct_col = _daily_variation_color(day_pct, _DAILY_PCT_DISPLAY_EPS)
    if pct_col == _NEUTRAL_COLOR and delta_col != _NEUTRAL_COLOR and day_pct is not None:
        pct_col = delta_col
    return delta_col, pct_col


def _daily_trend_from_values(day_delta, day_pct, fallback_state="flat"):
    if day_pct is not None and abs(day_pct) >= _DAILY_PCT_DISPLAY_EPS:
        if day_pct > 0:
            return ("▲▲" if day_pct >= 0.03 else "▲", COLORS["success"], "up_big" if day_pct >= 0.03 else "up")
        return ("▼▼" if day_pct <= -0.03 else "▼", COLORS["danger"], "down_big" if day_pct <= -0.03 else "down")
    if day_delta is not None and abs(day_delta) >= _DAILY_EUR_DISPLAY_EPS:
        if day_delta > 0:
            return ("▲", COLORS["success"], "up")
        return ("▼", COLORS["danger"], "down")

    state = str(fallback_state or "flat")
    if day_delta is not None or day_pct is not None:
        state = "flat"
    if state == "up_big":
        return ("▲▲", COLORS["success"], state)
    if state == "up":
        return ("▲", COLORS["success"], state)
    if state == "down_big":
        return ("▼▼", COLORS["danger"], state)
    if state == "down":
        return ("▼", COLORS["danger"], state)
    return ("—", _NEUTRAL_COLOR, "flat")


def render_portfolio_table_with_popup(df, data, direction_map=None):
    """Render the portfolio table with inline popup details for each ticker.

    Chiamato da: flussi UI del portafoglio/home che mostrano la tabella holdings.
    Nota: non passa da apply_settings perche' non e' un grafico Plotly ma un blocco HTML.
    """
    if df is None or df.empty:
        return
    direction_map = direction_map or {}
    info_map = {s["ticker"]: s for s in data.get("strumenti", [])}
    ticker_info = _build_ticker_info(df, data)
    btp_badges = _build_btp_badge_map(data)
    cat_color_map = CATEGORY_COLORS

    def _cat_col(tipo):
        cat = macro_cat(tipo)
        return cat_color_map.get(cat, macro_color(cat))

    def _direction_entry(tk):
        raw = direction_map.get(str(tk or ""), "flat")
        if isinstance(raw, dict):
            return raw
        return {"state": raw}

    def _trend_sym(tk):
        state = str(_direction_entry(tk).get("state") or "flat")
        if state == "up_big":
            return ("▲▲", COLORS["success"])
        if state == "up":
            return ("▲", COLORS["success"])
        if state == "down_big":
            return ("▼▼", COLORS["danger"])
        if state == "down":
            return ("▼", COLORS["danger"])
        return ("—", "#9CA3AF")

    def _sort_val_num(v):
        try:
            return str(round(float(v or 0), 6))
        except Exception:
            return "0"

    rows_html = ""
    _total_ctv = float(pd.to_numeric(df["Controvalore"], errors="coerce").fillna(0).sum())
    _daily_deltas: list[float] = []
    for _, row in df.iterrows():
        tk = str(row.get("Ticker", ""))
        tipo = str(row.get("Tipo", ""))
        tipo_code = macro_cat(tipo)
        nome = str(row.get("Strumento", ""))
        info = info_map.get(tk, {})
        natura_label = str(info.get("natura") or "Esposizione diversificata")
        natura_color, natura_svg = get_natura_visual(natura_label)
        # "Zero commissioni" esiste solo come campo per ETF/ETC: per le altre
        # categorie il badge non e' applicabile, non va mostrato di default.
        comm_badge = commission_badge(info.get("zero_commissioni")) if tipo_code in ("ETF", "ETC") else ""
        btp_badge = _btp_info_badge(tk, info, btp_badges.get(tk)) if tipo_code == "GOV" else ""
        issuer_badge_html = issuer_badge(info, ticker=tk, tipo_code=tipo_code)
        col = _cat_col(tipo)
        direction = _direction_entry(tk)
        try:
            ctv = float(row.get("Controvalore", 0) or 0)
        except Exception:
            ctv = 0.0
        weight = ctv / _total_ctv if abs(_total_ctv) > 1e-09 else 0.0
        day_delta_raw = _as_finite_float(direction.get("delta_eur"))
        day_pct_raw = _as_finite_float(direction.get("delta_pct"))
        if (
            day_pct_raw is not None
            and abs(day_pct_raw) >= _DAILY_PCT_DISPLAY_EPS
            and (day_delta_raw is None or abs(day_delta_raw) < _DAILY_EUR_DISPLAY_EPS)
            and abs(1.0 + day_pct_raw) > 1e-12
            and abs(ctv) > _DAILY_EUR_DISPLAY_EPS
        ):
            reconstructed_delta = ctv - (ctv / (1.0 + day_pct_raw))
            if math.isfinite(reconstructed_delta):
                day_delta_raw = reconstructed_delta
        day_delta = _zero_for_display(day_delta_raw, _DAILY_EUR_DISPLAY_EPS)
        day_pct = _zero_for_display(day_pct_raw, _DAILY_PCT_DISPLAY_EPS)
        if day_delta_raw is not None:
            _daily_deltas.append(day_delta_raw)
        day_delta_col, day_pct_col = _daily_variation_colors(day_delta, day_pct)
        day_delta_str = fmt_eur_it(day_delta, 2, signed=True) if day_delta is not None else "—"
        day_pct_str = fmt_pct_it(day_pct, 2, signed=True) if day_pct is not None else "—"
        sym, sym_col, state = _daily_trend_from_values(day_delta, day_pct, direction.get("state"))
        try:
            pl_e = float(row.get("P/L €", 0) or 0)
            pl_p = float(row.get("P/L %", 0) or 0)
        except Exception:
            pl_e = pl_p = 0.0
        pl_col = COLORS["success"] if pl_e >= 0 else COLORS["danger"]
        pl_e_str = fmt_eur_it(pl_e, 2, signed=True)
        pl_p_str = fmt_pct_it(pl_p, 2, signed=True)
        previous_pl_e = (pl_e - day_delta_raw) if day_delta_raw is not None else None
        pl_state_now = _signed_state(pl_e, _DAILY_EUR_DISPLAY_EPS)
        pl_state_prev = _signed_state(previous_pl_e, _DAILY_EUR_DISPLAY_EPS)
        pl_crossed_zero = (
            day_delta_raw is not None
            and abs(day_delta_raw) >= _DAILY_EUR_DISPLAY_EPS
            and pl_state_now != pl_state_prev
            and (pl_state_now != 0 or pl_state_prev != 0)
        )
        pl_flip_class = " pl-flip-pos" if pl_crossed_zero and pl_state_now >= 0 else (" pl-flip-neg" if pl_crossed_zero else "")
        pl_flip_title = (
            f' title="Cambio colore P/L: prima della variazione giornaliera {fmt_eur_it(previous_pl_e, 2, signed=True)}, ora {pl_e_str}."'
            if pl_crossed_zero
            else ""
        )
        pl_flip_badge = '<span class="pl-flip-marker">!</span>' if pl_crossed_zero else ""
        mini_spark_svg, mini_spark_sort = _mini_sparkline_svg(
            ticker_info.get(tk, {}).get("spark", []),
            pl_positive=pl_e >= 0,
            reference_value=row.get("PMC", None),
        )
        sym_sort = {
            "up_big": "0",
            "up": "1",
            "flat": "2",
            "down": "3",
            "down_big": "4",
        }.get(state, "2")
        rows_html += (
            f'''<tr>\n          <td data-sort="{tk}">{issuer_badge_html}<a class="tk-link" style="color:{col}" href="#" onclick="showModal('{tk}');return false;">{tk}</a>{comm_badge}</td>\n'''
            f'''          <td data-sort="{nome}" style="color:{col};max-width:112px;" title="{nome}">{nome[:21]}</td>\n'''
            f'''          <td data-sort="{tipo_code}" style="color:{col};font-weight:700;max-width:54px;" title="{tipo}">{tipo_code}</td>\n'''
            f'''          <td class="natura-cell" title="{natura_label}" style="color:{natura_color};width:20px;text-align:center;">{natura_svg}</td>\n'''
            f'''          <td class="btp-info-cell" data-sort="{0 if btp_badge else 9}">{btp_badge}</td>\n'''
            f'''          <td class="num" data-sort="{_sort_val_num(row.get('PMC', ''))}">{fmt_eur_it(row.get('PMC', ''), 3)}</td>\n'''
            f'''          <td class="num" data-sort="{_sort_val_num(weight)}" style="font-weight:700;">{fmt_pct_it(weight, 2)}</td>\n'''
            f'''          <td class="num" data-sort="{_sort_val_num(row.get('Quote', ''))}">{fmt_num_it(row.get('Quote', ''), 3)}</td>\n'''
            f'''          <td class="num" data-sort="{_sort_val_num(row.get('Prezzo', ''))}">{fmt_eur_it(row.get('Prezzo', ''), 3)}</td>\n'''
            f'''          <td class="num" data-sort="{_sort_val_num(row.get('Controvalore', ''))}">{fmt_eur_it(row.get('Controvalore', ''), 2)}</td>\n'''
            f'''          <td class="mini-spark-cell" data-sort="{_sort_val_num(mini_spark_sort)}">{mini_spark_svg}</td>\n'''
            f'''          <td class="num pl-cell{pl_flip_class}" data-sort="{_sort_val_num(pl_e)}"{pl_flip_title} style="color:{pl_col};font-weight:700;">{pl_e_str}{pl_flip_badge}</td>\n'''
            f'''          <td class="num pl-cell{pl_flip_class}" data-sort="{_sort_val_num(pl_p)}"{pl_flip_title} style="color:{pl_col};font-weight:700;">{pl_p_str}</td>\n'''
            f'''          <td class="num" data-sort="{_sort_val_num(day_delta)}" style="color:{day_delta_col};font-weight:700;">{day_delta_str}</td>\n'''
            f'''          <td class="num" data-sort="{_sort_val_num(day_pct)}" style="color:{day_pct_col};font-weight:700;">{day_pct_str}</td>\n'''
            f'''          <td data-sort="{sym_sort}" style="color:{sym_col};font-weight:800;text-align:center;width:26px;">{sym}</td>\n'''
            f"""        </tr>"""
        )
    _total_cost = float(pd.to_numeric(df["Costo"], errors="coerce").fillna(0).sum())
    _total_pl_e = float(pd.to_numeric(df["P/L €"], errors="coerce").fillna(0).sum())
    _total_pl_p = _total_pl_e / abs(_total_cost) if abs(_total_cost) > 1e-09 else 0.0
    _total_pl_col = COLORS["success"] if _total_pl_e >= 0 else COLORS["danger"]
    _total_day_delta = sum(_daily_deltas) if _daily_deltas else None
    _total_day_base = (_total_ctv - _total_day_delta) if _total_day_delta is not None else 0.0
    _total_day_pct = (
        _total_day_delta / _total_day_base
        if _total_day_delta is not None and abs(_total_day_base) > 1e-09
        else None
    )
    _total_day_delta_display = _zero_for_display(_total_day_delta, _DAILY_EUR_DISPLAY_EPS)
    _total_day_pct_display = _zero_for_display(_total_day_pct, _DAILY_PCT_DISPLAY_EPS)
    _total_day_delta_col, _total_day_pct_col = _daily_variation_colors(_total_day_delta_display, _total_day_pct_display)
    tfoot_html = (
        f'<tfoot><tr><td colspan="5" style="font-weight:800;font-size:0.85rem;letter-spacing:.02em;padding:9px 12px;">TOTALE</td>'
        f'<td></td>'
        f'<td class="num" style="font-weight:800;padding:9px 12px;">{fmt_pct_it(1.0, 2) if abs(_total_ctv) > 1e-09 else "—"}</td>'
        f'<td></td><td></td>'
        f'<td class="num" style="font-weight:700;padding:9px 12px;">{fmt_eur_it(_total_ctv, 2)}</td>'
        f'<td></td>'
        f'<td class="num" style="color:{_total_pl_col};font-weight:800;padding:9px 12px;">{fmt_eur_it(_total_pl_e, 2, signed=True)}</td>'
        f'<td class="num" style="color:{_total_pl_col};font-weight:800;padding:9px 12px;">{fmt_pct_it(_total_pl_p, 2, signed=True)}</td>'
        f'<td class="num" style="color:{_total_day_delta_col};font-weight:800;padding:9px 12px;">{fmt_eur_it(_total_day_delta_display, 2, signed=True) if _total_day_delta_display is not None else "—"}</td>'
        f'<td class="num" style="color:{_total_day_pct_col};font-weight:800;padding:9px 12px;">{fmt_pct_it(_total_day_pct_display, 2, signed=True) if _total_day_pct_display is not None else "—"}</td>'
        f'<td></td></tr></tfoot>'
    )
    ticker_json = json.dumps(ticker_info, ensure_ascii=False)
    n_rows = len(df)
    iframe_h = iframe_height_for_rows(
        n_rows, row_height=35, header_height=48, padding=50, min_height=160, max_height=1100, content_until_rows=18
    )
    html_content = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box;margin:0;padding:0;}}
html,body{{background:transparent;font-family:"Source Sans Pro",system-ui,-apple-system,sans-serif;font-size:13px;overflow:hidden;color:#262730;}}
.tw{{border:1px solid #e6e9ef;border-radius:8px;overflow:hidden;background:#fff;width:100%;}}
table{{width:100%;border-collapse:collapse;table-layout:fixed;}}
thead th{{
  background:#f0f2f6;font-size:11.5px;font-weight:600;letter-spacing:.01em;
  color:#262730;padding:8px 7px;border-bottom:1px solid #e6e9ef;border-right:1px solid #e6e9ef;
  text-align:right;white-space:nowrap;position:relative;user-select:none;cursor:pointer;
}}
thead th:last-child{{border-right:none;}}
thead th:nth-child(4),thead th:nth-child(5),thead th:nth-child(16){{text-align:center;cursor:default;padding:8px 4px;}}
thead th:nth-child(1),thead th:nth-child(2),thead th:nth-child(3){{text-align:left;}}
thead th:hover:not(:nth-child(4)):not(:nth-child(5)):not(:nth-child(16)){{background:#e3e6e9;}}
thead th .sort-ind{{font-size:9px;margin-left:3px;color:#9094a3;}}
thead th.asc .sort-ind::after{{content:'▲';color:#262730;}}
thead th.desc .sort-ind::after{{content:'▼';color:#262730;}}
.rh{{position:absolute;right:0;top:0;height:100%;width:4px;cursor:col-resize;background:transparent;z-index:1;}}
.rh:hover{{background:#9094a3;opacity:.4;}}
tbody tr{{border-bottom:1px solid #f0f2f6;}}
tbody tr:last-child{{border-bottom:none;}}
tbody tr:hover{{background:#f0f2f6;}}
tbody td{{padding:8px 7px;vertical-align:middle;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;border-right:1px solid #f0f2f6;}}
tbody td:last-child{{border-right:none;}}
tbody td:nth-child(4),tbody td:nth-child(5),tbody td:nth-child(16){{padding:8px 4px;text-align:center;}}
.natura-cell svg{{width:15px;height:15px;}}
{ISSUER_BADGE_CSS}
.btp-info-cell{{text-align:center;overflow:visible;}}
.btp-pill{{display:inline-flex;align-items:center;justify-content:center;width:14px;height:14px;border-radius:999px;font-size:10px;font-weight:900;line-height:1;cursor:help;border:1px solid rgba(15,23,42,.12);box-shadow:0 0 0 2px rgba(255,255,255,.9);}}
.btp-pill.btp-info{{background:#EFF6FF;color:#2563EB;}}
.btp-pill.btp-coupon{{background:#ECFDF3;color:#1E8449;}}
.btp-pill.btp-maturity{{background:#FFF7ED;color:#F59E0B;border-radius:5px;}}
.mini-spark-cell{{text-align:center;padding:5px 4px;}}
.mini-spark{{display:block;width:64px;height:28px;margin:0 auto;overflow:visible;max-width:100%;}}
.mini-spark-empty{{color:#9CA3AF;font-weight:700;}}
.pl-cell.pl-flip-pos{{background:rgba(30,132,73,0.11);box-shadow:inset 0 -2px 0 rgba(30,132,73,0.36);}}
.pl-cell.pl-flip-neg{{background:rgba(255,75,75,0.10);box-shadow:inset 0 -2px 0 rgba(255,75,75,0.36);}}
.pl-flip-marker{{display:inline-flex;align-items:center;justify-content:center;width:13px;height:13px;margin-left:4px;border-radius:999px;background:#374151;color:#fff;font-size:9px;font-weight:900;line-height:1;vertical-align:1px;}}
tfoot tr{{border-top:2px solid #d1d5db;background:#f8f9fa;}}
tfoot td{{vertical-align:middle;white-space:nowrap;border-right:1px solid #e6e9ef;}}
tfoot td:last-child{{border-right:none;}}
.num{{text-align:right;font-variant-numeric:tabular-nums;}}
{_MODAL_CSS}
</style></head>
<body>
<div class="tw">
<table id="ptf-table">
<colgroup>
  <col style="width:11.2%">
  <col style="width:10.8%">
  <col style="width:4.0%">
  <col style="width:2.1%">
  <col style="width:2.4%">
  <col style="width:6.7%">
  <col style="width:5.8%">
  <col style="width:6.1%">
  <col style="width:7%">
  <col style="width:8.4%">
  <col style="width:6.2%">
  <col style="width:7.2%">
  <col style="width:6.2%">
  <col style="width:5.8%">
  <col style="width:5.8%">
  <col style="width:2.3%">
</colgroup>
<thead><tr>
  <th data-col="0">Ticker<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="1">Strumento<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="2">Cat.<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="3"></th>
  <th data-col="4" title="Cedole/scadenza BTP"></th>
  <th data-col="5">PMC<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="6">Peso %<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="7">Quote<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="8" title="Prezzo dell'ultima quotazione disponibile">Ult. quot.<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="9">Controv.<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="10">60g<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="11">P/L €<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="12">P/L %<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="13">Var gg €<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="14">Var gg %<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="15"></th>
</tr></thead>
<tbody id="ptf-body">{rows_html}</tbody>
{tfoot_html}
</table>
</div>
{_MODAL_HTML}
<script>
{_MODAL_JS}
var _sCol=-1,_sAsc=true;
function sortTable(col){{
  if(col===3||col===4||col===15)return;
  var tbody=document.getElementById('ptf-body');
  var rows=Array.from(tbody.querySelectorAll('tr'));
  var asc=(_sCol===col)?!_sAsc:true;_sCol=col;_sAsc=asc;
  rows.sort(function(a,b){{
    var av=a.children[col].getAttribute('data-sort')||'';
    var bv=b.children[col].getAttribute('data-sort')||'';
    var an=parseFloat(av),bn=parseFloat(bv);
    if(!isNaN(an)&&!isNaN(bn))return asc?an-bn:bn-an;
    return asc?av.localeCompare(bv,'it'):bv.localeCompare(av,'it');
  }});
  rows.forEach(function(r){{tbody.appendChild(r);}});
  document.querySelectorAll('thead th').forEach(function(th,i){{
    th.classList.remove('asc','desc');
    if(i===col)th.classList.add(asc?'asc':'desc');
  }});
}}
document.querySelectorAll('thead th[data-col]').forEach(function(th){{
  th.addEventListener('click',function(e){{
    if(e.target.classList.contains('rh'))return;
    sortTable(parseInt(th.getAttribute('data-col')));
  }});
}});
(function(){{
  var rz=null,sx,sw;
  document.querySelectorAll('.rh').forEach(function(h){{
    h.addEventListener('mousedown',function(e){{
      e.stopPropagation();e.preventDefault();
      rz=h.parentElement;sx=e.clientX;sw=rz.offsetWidth;
      document.addEventListener('mousemove',mv);document.addEventListener('mouseup',up);
    }});
  }});
  function mv(e){{if(!rz)return;rz.style.width=Math.max(36,sw+(e.clientX-sx))+'px';}}
  function up(){{rz=null;document.removeEventListener('mousemove',mv);document.removeEventListener('mouseup',up);}}
}})();
function sendH(){{
  var t=document.getElementById('ptf-table');
  if(!t)return;
  var h=Math.ceil(t.getBoundingClientRect().height)+2;
  var py=0; try{{py=window.parent.scrollY||window.parent.pageYOffset||0;}}catch(e){{}}
  window.parent.postMessage({{type:'streamlit:setFrameHeight',height:h}},'*');
  [10,60,200].forEach(function(d){{setTimeout(function(){{try{{window.parent.scrollTo({{top:py,behavior:'instant'}});}}catch(e){{}}}} ,d);}});
}}
sendH();
requestAnimationFrame(sendH);
setTimeout(sendH,150);
setTimeout(sendH,600);
</script>
</body></html>"""
    html_content = html_content.replace("__TICKER_JSON__", ticker_json)
    render_html_iframe(html_content, height=iframe_h, scrolling=False)


def render_weekly_pl_table(result, da, data):
    """Render the per-instrument weekly P/L table (Ticker/Strumento/Tipo/Quote + daily deltas + Totale).

    Chiamato da: ui/pages/home.py, sezione "Andamento dell'ultima settimana".
    Stesso popup di dettaglio ticker della tabella Controvalore (via _build_ticker_info/_MODAL_*).
    """
    if not result or not result.get("rows"):
        return
    days = result["days"]
    week_gap_before = result.get("week_gap_before") or [False] * len(days)
    rows = result["rows"]
    day_totals = result["day_totals"]
    grand_total = result["grand_total"]
    n_days = len(days)

    ticker_info = _build_ticker_info(da, data) if da is not None and data is not None else {}
    info_map = {s["ticker"]: s for s in (data or {}).get("strumenti", [])}

    def _cat_col(tipo):
        cat = macro_cat(tipo)
        return CATEGORY_COLORS.get(cat, macro_color(cat))

    def _sort_val(v):
        if v is None:
            return "-999999999"
        try:
            return str(round(float(v), 6))
        except Exception:
            return "-999999999"

    day_extrema = []
    for i in range(n_days):
        vals = [r["deltas"][i] for r in rows if r["deltas"][i] is not None]
        day_extrema.append((max(vals), min(vals)) if vals else (None, None))

    day_ths = "".join(
        f'<th data-col="{5 + i}"'
        + (' style="border-left:2px solid #d1d5db;"' if week_gap_before[i] else '')
        + f'>{d}<span class="sort-ind"></span><span class="rh"></span></th>\n'
        for i, d in enumerate(days)
    )
    arrow_col_idx = 5 + n_days
    total_col = arrow_col_idx + 1

    rows_html = ""
    for row in rows:
        tk = row["ticker"]
        col = _cat_col(row["tipo"])
        tipo_code = macro_cat(row["tipo"])
        natura_label = str(info_map.get(tk, {}).get("natura") or "Esposizione diversificata")
        natura_color, natura_svg = get_natura_visual(natura_label)
        # "Zero commissioni" esiste solo come campo per ETF/ETC: per le altre
        # categorie il badge non e' applicabile, non va mostrato di default.
        comm_badge = commission_badge(info_map.get(tk, {}).get("zero_commissioni")) if tipo_code in ("ETF", "ETC") else ""
        issuer_badge_html = issuer_badge(info_map.get(tk, {}), ticker=tk, tipo_code=tipo_code)
        cells = ""
        for i, v in enumerate(row["deltas"]):
            cell_col = COLORS["success"] if (v is not None and v >= 0) else (COLORS["danger"] if v is not None else "#9CA3AF")
            day_max, day_min = day_extrema[i]
            is_extreme = v is not None and (v == day_max or v == day_min)
            weight = "700" if is_extreme else "400"
            gap_style = "border-left:2px solid #d1d5db;" if week_gap_before[i] else ""
            cells += f'<td class="num" data-sort="{_sort_val(v)}" style="color:{cell_col};font-weight:{weight};{gap_style}">{fmt_num_it(v, 2, signed=True)}</td>\n'
        totale = row["totale"]
        tot_col = COLORS["success"] if totale >= 0 else COLORS["danger"]
        arrow_char = "↗" if totale >= 0 else "↘"
        strumento = str(row["strumento"])
        row_all_up = n_days == 7 and all(d is not None and d > 0 for d in row["deltas"])
        row_all_down = n_days == 7 and all(d is not None and d < 0 for d in row["deltas"])
        row_bg = "background-color:rgba(30,132,73,0.10);" if row_all_up else ("background-color:rgba(255,75,75,0.10);" if row_all_down else "")
        rows_html += (
            f'<tr style="{row_bg}">\n'
            f'<td data-sort="{tk}">{issuer_badge_html}<a class="tk-link" style="color:{col}" href="#" onclick="showModal(\'{tk}\');return false;">{tk}</a>{comm_badge}</td>\n'
            f'<td data-sort="{strumento}" style="color:{col};max-width:130px;" title="{strumento}">{strumento[:24]}</td>\n'
            f'<td data-sort="{tipo_code}" style="color:{col};">{tipo_code}</td>\n'
            f'<td class="natura-cell" title="{natura_label}" style="color:{natura_color};width:20px;text-align:center;">{natura_svg}</td>\n'
            f'<td class="num" data-sort="{_sort_val(row["quote"])}">{fmt_num_it(row["quote"], 3)}</td>\n'
            f'{cells}'
            f'<td style="color:{tot_col};font-weight:800;text-align:center;width:26px;">{arrow_char}</td>\n'
            f'<td class="num" data-sort="{_sort_val(totale)}" style="color:{tot_col};font-weight:700;">{fmt_eur_it(totale, 2, signed=True)}</td>\n'
            '</tr>'
        )

    total_cells = ""
    for i, v in enumerate(day_totals):
        cell_col = COLORS["success"] if v >= 0 else COLORS["danger"]
        gap_style = "border-left:2px solid #d1d5db;" if week_gap_before[i] else ""
        total_cells += f'<td class="num" style="color:{cell_col};font-weight:700;padding:9px 12px;{gap_style}">{fmt_num_it(v, 2, signed=True)}</td>\n'
    grand_col = COLORS["success"] if grand_total >= 0 else COLORS["danger"]
    tfoot_html = (
        '<tfoot><tr>'
        '<td colspan="5" style="font-weight:800;font-size:0.85rem;letter-spacing:.02em;padding:9px 12px;">TOTALE</td>'
        f'{total_cells}'
        '<td></td>'
        f'<td class="num" style="color:{grand_col};font-weight:800;padding:9px 12px;">{fmt_eur_it(grand_total, 2, signed=True)}</td>'
        '</tr></tfoot>'
    )

    ticker_json = json.dumps(ticker_info, ensure_ascii=False)
    n_rows = len(rows)
    iframe_h = iframe_height_for_rows(
        n_rows, row_height=35, header_height=48, padding=50, min_height=160, max_height=1100, content_until_rows=18
    )
    html_content = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box;margin:0;padding:0;}}
html,body{{background:transparent;font-family:"Source Sans Pro",system-ui,-apple-system,sans-serif;font-size:14px;overflow:hidden;color:#262730;}}
.tw{{border:1px solid #e6e9ef;border-radius:8px;overflow:hidden;background:#fff;width:100%;}}
table{{width:100%;border-collapse:collapse;table-layout:auto;}}
thead th{{
  background:#f0f2f6;font-size:12px;font-weight:600;letter-spacing:.01em;
  color:#262730;padding:9px 12px;border-bottom:1px solid #e6e9ef;border-right:1px solid #e6e9ef;
  text-align:right;white-space:nowrap;position:relative;user-select:none;cursor:pointer;
}}
thead th:last-child{{border-right:none;}}
thead th:nth-child(1),thead th:nth-child(2),thead th:nth-child(3){{text-align:left;}}
thead th:hover{{background:#e3e6e9;}}
thead th .sort-ind{{font-size:9px;margin-left:3px;color:#9094a3;}}
thead th.asc .sort-ind::after{{content:'▲';color:#262730;}}
thead th.desc .sort-ind::after{{content:'▼';color:#262730;}}
.rh{{position:absolute;right:0;top:0;height:100%;width:4px;cursor:col-resize;background:transparent;z-index:1;}}
.rh:hover{{background:#9094a3;opacity:.4;}}
tbody tr{{border-bottom:1px solid #f0f2f6;}}
tbody tr:last-child{{border-bottom:none;}}
tbody tr:hover{{background:#f0f2f6;}}
tbody td{{padding:9px 12px;vertical-align:middle;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;border-right:1px solid #f0f2f6;}}
tbody td:last-child{{border-right:none;}}
.natura-cell svg{{width:15px;height:15px;}}
{ISSUER_BADGE_CSS}
tfoot tr{{border-top:2px solid #d1d5db;background:#f8f9fa;}}
tfoot td{{vertical-align:middle;white-space:nowrap;border-right:1px solid #e6e9ef;}}
tfoot td:last-child{{border-right:none;}}
.num{{text-align:right;font-variant-numeric:tabular-nums;}}
{_MODAL_CSS}
</style></head>
<body>
<div class="tw">
<table id="wpl-table">
<thead><tr>
  <th data-col="0">Ticker<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="1">Strumento<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="2">Tipo<span class="sort-ind"></span><span class="rh"></span></th>
  <th data-col="3" style="text-align:center;width:20px;cursor:default;"></th>
  <th data-col="4">Quote<span class="sort-ind"></span><span class="rh"></span></th>
  {day_ths}
  <th data-col="{arrow_col_idx}" style="text-align:center;width:26px;cursor:default;"></th>
  <th data-col="{total_col}">P/L totale<span class="sort-ind"></span><span class="rh"></span></th>
</tr></thead>
<tbody id="wpl-body">{rows_html}</tbody>
{tfoot_html}
</table>
</div>
{_MODAL_HTML}
<script>
{_MODAL_JS}
var _sCol=-1,_sAsc=true;
var _naturaCol=3;
var _arrowCol={arrow_col_idx};
function sortTable(col){{
  if(col===_naturaCol||col===_arrowCol)return;
  var tbody=document.getElementById('wpl-body');
  var rows=Array.from(tbody.querySelectorAll('tr'));
  var asc=(_sCol===col)?!_sAsc:true;_sCol=col;_sAsc=asc;
  rows.sort(function(a,b){{
    var av=a.children[col].getAttribute('data-sort')||'';
    var bv=b.children[col].getAttribute('data-sort')||'';
    var an=parseFloat(av),bn=parseFloat(bv);
    if(!isNaN(an)&&!isNaN(bn))return asc?an-bn:bn-an;
    return asc?av.localeCompare(bv,'it'):bv.localeCompare(av,'it');
  }});
  rows.forEach(function(r){{tbody.appendChild(r);}});
  document.querySelectorAll('thead th').forEach(function(th,i){{
    th.classList.remove('asc','desc');
    if(i===col)th.classList.add(asc?'asc':'desc');
  }});
}}
document.querySelectorAll('thead th[data-col]').forEach(function(th){{
  th.addEventListener('click',function(e){{
    if(e.target.classList.contains('rh'))return;
    sortTable(parseInt(th.getAttribute('data-col')));
  }});
}});
(function(){{
  var rz=null,sx,sw;
  document.querySelectorAll('.rh').forEach(function(h){{
    h.addEventListener('mousedown',function(e){{
      e.stopPropagation();e.preventDefault();
      rz=h.parentElement;sx=e.clientX;sw=rz.offsetWidth;
      document.addEventListener('mousemove',mv);document.addEventListener('mouseup',up);
    }});
  }});
  function mv(e){{if(!rz)return;rz.style.width=Math.max(36,sw+(e.clientX-sx))+'px';}}
  function up(){{rz=null;document.removeEventListener('mousemove',mv);document.removeEventListener('mouseup',up);}}
}})();
function sendH(){{
  var t=document.getElementById('wpl-table');
  if(!t)return;
  var h=Math.ceil(t.getBoundingClientRect().height)+2;
  var py=0; try{{py=window.parent.scrollY||window.parent.pageYOffset||0;}}catch(e){{}}
  window.parent.postMessage({{type:'streamlit:setFrameHeight',height:h}},'*');
  [10,60,200].forEach(function(d){{setTimeout(function(){{try{{window.parent.scrollTo({{top:py,behavior:'instant'}});}}catch(e){{}}}} ,d);}});
}}
sendH();
requestAnimationFrame(sendH);
setTimeout(sendH,150);
setTimeout(sendH,600);
</script>
</body></html>"""
    html_content = html_content.replace("__TICKER_JSON__", ticker_json)
    render_html_iframe(html_content, height=iframe_h, scrolling=False)
