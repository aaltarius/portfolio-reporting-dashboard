"""ui/form_server/scheda_strumento.py — pagina "Scheda strumento" del form-server
(route /strumento/{ticker}).

Estratto da form_server.py. Condivide la stessa pipeline di storage dell'app
principale: nessuna logica duplicata.
"""
from __future__ import annotations

from html import escape

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from ui.form_server.shell import CSS

router = APIRouter()

_SCHEDA_CSS = CSS + """<style>
  *{box-sizing:border-box;margin:0;padding:0;}
  body{font-family:system-ui,-apple-system,sans-serif;background:var(--page-bg);color:var(--slate-900);padding:20px;}
  .page{max-width:780px;margin:0 auto;}
  /* Header */
  .hdr{background:var(--white);border-radius:14px;padding:20px 24px 16px;margin-bottom:14px;box-shadow:0 1px 6px var(--black-a07);}
  .hdr-name{font-size:21px;font-weight:800;color:var(--slate-900);margin-bottom:8px;line-height:1.2;}
  .chips{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px;}
  .chip{font-size:11px;font-weight:600;padding:3px 10px;border-radius:20px;}
  .chip-tipo{background:var(--blue-100);color:var(--blue-700);}
  .chip-ok{background:var(--green-100);color:var(--green-700);}
  .chip-warn{background:var(--amber-100);color:var(--amber-700);}
  .chip-gray{background:var(--slate-100);color:var(--slate-500);}
  .hdr-meta{font-size:12px;color:var(--slate-400);}
  /* Alerts */
  .alert{padding:9px 14px;border-radius:8px;font-size:13px;margin-bottom:12px;}
  .alert-ok{background:var(--green-50);color:var(--green-800);border:1px solid var(--green-300);}
  .alert-err{background:var(--red-50);color:var(--red-700);border:1px solid var(--red-300);}
  .alert-warn{background:var(--amber-50);color:var(--amber-800);border:1px solid var(--amber-300);}
  /* Actions bar */
  .actions{display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap;}
  .btn{display:inline-block;padding:8px 18px;border-radius:8px;font-size:13px;font-weight:600;text-decoration:none;cursor:pointer;border:none;white-space:nowrap;}
  .btn-primary{background:var(--slate-900);color:var(--white);}
  .btn-secondary{background:var(--white);color:var(--slate-600);border:1px solid var(--slate-200);}
  /* Hero KPIs */
  .hero{display:grid;gap:10px;margin-bottom:14px;}
  .hero-3{grid-template-columns:repeat(3,1fr);}
  .hero-2{grid-template-columns:repeat(2,1fr);}
  .kpi-card{background:var(--white);border-radius:12px;padding:16px 14px;box-shadow:0 1px 6px var(--black-a07);text-align:center;}
  .kpi-val{font-size:26px;font-weight:800;color:var(--slate-900);line-height:1;margin-bottom:5px;}
  .kpi-lbl{font-size:10px;color:var(--slate-400);font-weight:700;text-transform:uppercase;letter-spacing:.06em;}
  .kpi-card.pos .kpi-val{color:var(--green-600);}
  .kpi-card.neg .kpi-val{color:var(--red-600);}
  /* Sections */
  .sec{background:var(--white);border-radius:12px;padding:18px 20px;margin-bottom:12px;box-shadow:0 1px 6px var(--black-a07);}
  .sec-title{font-size:10px;font-weight:700;color:var(--slate-400);text-transform:uppercase;letter-spacing:.08em;margin-bottom:14px;}
  /* Data grid */
  .dg{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px 20px;}
  .dg-wide{grid-template-columns:repeat(auto-fill,minmax(300px,1fr));}
  .di .lbl{font-size:11px;color:var(--slate-400);margin-bottom:3px;}
  .di .val{font-size:14px;font-weight:600;color:var(--slate-800);}
  .di .val.pos{color:var(--green-600);}
  .di .val.neg{color:var(--red-600);}
  /* Composition bars */
  .comp-row{display:flex;align-items:center;gap:10px;margin-bottom:8px;}
  .comp-lbl{font-size:12px;color:var(--slate-600);min-width:120px;}
  .comp-bar-wrap{flex:1;background:var(--slate-100);border-radius:4px;height:7px;}
  .comp-bar{height:7px;border-radius:4px;}
  .bar-az{background:var(--blue-500);}
  .bar-ob{background:var(--emerald-500);}
  .bar-liq{background:var(--slate-400);}
  .comp-val{font-size:12px;font-weight:700;color:var(--slate-700);min-width:44px;text-align:right;}
  /* Stars */
  .stars{color:var(--amber-500);font-size:17px;letter-spacing:1px;}
  /* Source badge */
  .sbadge{display:inline-block;font-size:9px;padding:1px 5px;border-radius:8px;margin-left:5px;vertical-align:middle;}
  .sb-auto{background:var(--blue-100);color:var(--blue-700);}
  .sb-pdf{background:var(--violet-100);color:var(--violet-600);}
  .sb-manuale{background:var(--amber-100);color:var(--amber-700);}
  /* Completeness score */
  .score-row{display:flex;align-items:center;gap:10px;margin-top:10px;}
  .score-lbl{font-size:11px;color:var(--slate-400);font-weight:600;white-space:nowrap;}
  .score-bar-wrap{flex:1;background:var(--slate-200);border-radius:4px;height:6px;max-width:160px;}
  .score-bar{height:6px;border-radius:4px;}
  .score-text{font-size:11px;font-weight:700;}
  .sc-green{color:var(--green-700);} .sc-bar-green{background:var(--green-500);}
  .sc-yellow{color:var(--amber-700);} .sc-bar-yellow{background:var(--amber-500);}
  .sc-orange{color:var(--orange-700);} .sc-bar-orange{background:var(--orange-500);}
  .sc-red{color:var(--red-600);} .sc-bar-red{background:var(--red-500);}
  /* Footer */
  .foot{text-align:center;margin-top:20px;padding-bottom:10px;}
</style>"""


def _render_scheda_strumento(strumento: dict) -> str:
    ticker = strumento.get("ticker", "")
    nome   = strumento.get("nome", "")
    isin   = strumento.get("isin", "") or "—"
    tipo   = strumento.get("tipo", "")
    from core.formatting import fmt_date_only_it
    enriched_at_raw = (strumento.get("enriched_at") or "")[:10]
    enriched_at = fmt_date_only_it(enriched_at_raw) if enriched_at_raw else "mai"
    enrichment_error = strumento.get("enrichment_error") or ""
    src    = strumento.get("enrichment_source") or {}

    from core.instrument_enrichment import _categoria
    cat = _categoria(tipo)

    enrich_err_html = f'<div class="alert alert-warn">&#9888; Errore fetch: {enrichment_error}</div>' if enrichment_error else ""

    # Chip stato arricchimento
    if enrichment_error:
        stato_chip = '<span class="chip chip-warn">&#9888; Errore</span>'
    elif enriched_at != "mai":
        stato_chip = f'<span class="chip chip-ok">&#10003; Arricchito {enriched_at}</span>'
    else:
        stato_chip = '<span class="chip chip-gray">Non arricchito</span>'

    # Fonte dati label
    src_labels = {"auto": "Automatico", "pdf": "PDF Fineco", "manuale": "Manuale"}
    src_vals = set(v for v in (src or {}).values() if v)
    src_label = " · ".join(src_labels.get(v, v) for v in src_vals) if src_vals else ""

    # ── Punteggio completezza ─────────────────────────────────────────────────
    _CORE_FIELDS: dict[str, list[str]] = {
        "btp": ["ytm_netto", "ytm_lordo", "duration_modificata", "scadenza",
                "cedola_annuale", "cedola_frequenza", "tipo_cedola", "rating_emittente"],
        "etf": ["rendimento_1a", "rendimento_3a", "ter", "benchmark",
                "categoria_etf", "distribuzione", "data_lancio", "rating_morningstar"],
        "etc": ["rendimento_1a", "rendimento_3a", "ter", "benchmark",
                "categoria_etf", "distribuzione", "data_lancio"],
        "fondo": ["rendimento_ytd", "rendimento_1a", "rendimento_3a", "ter",
                  "categoria_fam", "rating_morningstar", "data_lancio", "patrimonio"],
    }
    _score_fields = _CORE_FIELDS.get(cat, [])
    if _score_fields and enriched_at != "mai":
        _filled = sum(1 for f in _score_fields if strumento.get(f) not in (None, "", "—"))
        _pct = int(_filled / len(_score_fields) * 100)
        if _pct == 100:
            _sc, _sc_bar, _sc_label = "sc-green", "sc-bar-green", "Completo"
        elif _pct >= 75:
            _sc, _sc_bar, _sc_label = "sc-yellow", "sc-bar-yellow", "Quasi completo"
        elif _pct >= 40:
            _sc, _sc_bar, _sc_label = "sc-orange", "sc-bar-orange", "Parziale"
        else:
            _sc, _sc_bar, _sc_label = "sc-red", "sc-bar-red", "Incompleto"
        _score_html = (
            f'<div class="score-row">'
            f'<span class="score-lbl">Completezza dati</span>'
            f'<div class="score-bar-wrap"><div class="score-bar {_sc_bar}" style="width:{_pct}%;"></div></div>'
            f'<span class="score-text {_sc}">{_pct}% — {_sc_label} ({_filled}/{len(_score_fields)})</span>'
            f'</div>'
        )
    else:
        _score_html = ""

    def _html_open() -> str:
        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Scheda {ticker}</title>
{_SCHEDA_CSS}</head><body><div class="page">
<div class="hdr">
  <div style="font-size:12px;font-weight:700;color:var(--slate-400);letter-spacing:.06em;margin-bottom:4px;">{ticker}</div>
  <div class="hdr-name">{nome}</div>
  <div class="chips">
    <span class="chip chip-tipo">{tipo}</span>
    {stato_chip}
  </div>
  <div class="hdr-meta">ISIN: {isin}{(' &nbsp;·&nbsp; Fonte: ' + src_label) if src_label else ''}</div>
  <div class="hdr-meta">Per arricchire, modificare o importare da PDF: <a href="/strumenti?tab=arricchimento&amp;ticker={ticker}" target="_blank">Strumenti &#8594; Arricchimento</a></div>
  {_score_html}
</div>
{enrich_err_html}
<div class="actions">
  <a href="javascript:window.close()" class="btn btn-secondary">Chiudi</a>
</div>"""

    def _html_close() -> str:
        return "</div></body></html>"

    if True:  # la Scheda completa e' sola lettura: modifica/PDF/arricchimento vivono in Strumenti
        def _vs(name: str) -> str:
            v = strumento.get(name)
            return str(v) if v is not None else ""

        def _vd(name: str) -> str:
            """Come _vs, ma formatta il valore come data italiana (GG/MM/AAAA)."""
            v = _vs(name)
            return fmt_date_only_it(v) if v else ""

        def _rend_cls(val: str) -> str:
            if not val:
                return ""
            s = val.replace(" ", "")
            # Normalize Italian number format: "9.284,27" (thousands sep) → "9284.27"
            n = s.replace(",", ".").replace("%", "")
            parts = n.split(".")
            if len(parts) > 2:
                n = "".join(parts[:-1]) + "." + parts[-1]
            if s.startswith("+") or (n.lstrip("-").replace(".", "").isdigit() and float(n) > 0):
                return " pos"
            if s.startswith("-"):
                return " neg"
            return ""

        def _kpi(val: str, lbl: str, extra_cls: str = "") -> str:
            if not val:
                return ""
            cls = (_rend_cls(val) if not extra_cls else extra_cls).strip()
            cls_attr = f" {cls}" if cls else ""
            return f'<div class="kpi-card{cls_attr}"><div class="kpi-val">{val}</div><div class="kpi-lbl">{lbl}</div></div>'

        def _di(lbl: str, name: str, cls: str = "", val_override: str = "") -> str:
            val = val_override or _vs(name)
            if not val:
                return ""
            src_v = (src or {}).get(name, "")
            badge = f'<span class="sbadge sb-{src_v}">{src_v[:3].upper()}</span>' if src_v else ""
            vc = f" {cls}" if cls else _rend_cls(val)
            return f'<div class="di"><div class="lbl">{lbl}</div><div class="val{vc}">{val}{badge}</div></div>'

        def _stars(name: str = "rating_morningstar") -> str:
            v = _vs(name)
            if not v:
                return ""
            try:
                n = int(float(v))
                return "★" * n + "☆" * (5 - n)
            except Exception:
                return v

        def _sec(title: str, content: str) -> str:
            return f'<div class="sec"><div class="sec-title">{title}</div>{content}</div>' if content.strip() else ""

        def _dg(*items: str, wide: bool = False) -> str:
            cls = "dg dg-wide" if wide else "dg"
            return f'<div class="{cls}">' + "".join(i for i in items if i) + "</div>"

        def _comp_bar(lbl: str, name: str, bar_cls: str) -> str:
            val = _vs(name)
            if not val:
                return ""
            pct_s = val.replace(",", ".").replace("%", "").strip()
            try:
                pct = min(max(float(pct_s), 0), 100)
            except Exception:
                pct = 0
            return (f'<div class="comp-row"><span class="comp-lbl">{lbl}</span>'
                    f'<div class="comp-bar-wrap"><div class="comp-bar {bar_cls}" style="width:{pct}%;"></div></div>'
                    f'<span class="comp-val">{val}</span></div>')

        # ── Posizione base (comune a tutti) ──────────────────────────────────
        prezzo_str = _vs("prezzo")
        agg_str    = _vd("aggiornato")
        pos_items  = []
        if prezzo_str:
            pos_items.append(f'<div class="di"><div class="lbl">Prezzo corrente</div><div class="val">{prezzo_str}</div></div>')
        if agg_str:
            pos_items.append(f'<div class="di"><div class="lbl">Aggiornato</div><div class="val">{agg_str}</div></div>')
        if _vs("quantita"):
            pos_items.append(f'<div class="di"><div class="lbl">Quantità</div><div class="val">{_vs("quantita")}</div></div>')
        if _vs("nominale"):
            pos_items.append(f'<div class="di"><div class="lbl">Nominale</div><div class="val">{_vs("nominale")}</div></div>')
        if _vs("data_origine"):
            pos_items.append(f'<div class="di"><div class="lbl">Data acquisto</div><div class="val">{_vd("data_origine")}</div></div>')
        posizione_sec = _sec("Posizione in portafoglio", _dg(*pos_items)) if pos_items else ""

        if cat == "btp":
            hero = (
                f'<div class="hero hero-3">'
                + _kpi(_vs("ytm_netto"), "YTM Netto")
                + _kpi(_vs("duration_modificata"), "Duration")
                + _kpi(_vd("scadenza"), "Scadenza")
                + "</div>"
            )
            body = (
                hero
                + _sec("Rendimento",
                    _dg(_di("YTM Netto", "ytm_netto"),
                        _di("YTM Lordo", "ytm_lordo"),
                        _di("Duration Modificata", "duration_modificata"),
                        _di("Rating Emittente", "rating_emittente")))
                + _sec("Cedola",
                    _dg(_di("Scadenza", "scadenza", val_override=_vd("scadenza")),
                        _di("Cedola Annuale", "cedola_annuale"),
                        _di("Frequenza", "cedola_frequenza"),
                        _di("Tipo", "tipo_cedola"),
                        _di("Prossima Cedola", "prossima_cedola", val_override=_vd("prossima_cedola")),
                        _di("Data Godimento", "data_godimento", val_override=_vd("data_godimento"))))
                + _sec("Ratei e Fiscalità",
                    _dg(_di("Rateo Lordo", "rateo_lordo"),
                        _di("Rateo Netto", "rateo_netto"),
                        _di("Rateo Interessi", "rateo_interessi"),
                        _di("Rateo Disagio", "rateo_disaggio"),
                        _di("Ritenute Totali", "ritenute_totali")))
                + _sec("Emissione",
                    _dg(_di("Emittente", "emittente_btp"),
                        _di("Struttura", "struttura"),
                        _di("Data Emissione", "data_emissione"),
                        _di("Prezzo Emissione", "prezzo_emissione"),
                        _di("Prezzo Rimborso", "prezzo_rimborso")))
                + posizione_sec
            )

        elif cat in ("etf", "etc"):
            ytd = _vs("rendimento_ytd"); r1 = _vs("rendimento_1a"); r3 = _vs("rendimento_3a")
            hero = (
                f'<div class="hero hero-3">'
                + _kpi(ytd if ytd else r1, "Da inizio anno (YTD)" if ytd else "Rendimento 1 Anno")
                + _kpi(r3, "Rendimento 3 Anni")
                + _kpi(_vs("ter"), "TER (costo annuo)")
                + "</div>"
            )
            stars_str = _stars()
            rating_item = (f'<div class="di"><div class="lbl">Rating Morningstar</div>'
                           f'<div class="val"><span class="stars">{stars_str}</span></div></div>') if stars_str else ""
            holdings_html = ""
            for h in (strumento.get("holdings_top") or [])[:5]:
                n_h = h.get("nome", ""); p_h = h.get("pct", "")
                try:
                    p_num = min(max(float(p_h.replace(",", ".").replace("%", "").strip()), 0), 100)
                except Exception:
                    p_num = 0
                holdings_html += (
                    f'<div class="comp-row">'
                    f'<span class="comp-lbl">{escape(n_h)}</span>'
                    f'<div class="comp-bar-wrap"><div class="comp-bar bar-az" style="width:{p_num}%;"></div></div>'
                    f'<span class="comp-val">{p_h}</span></div>'
                )
            val_sec = _sec("Valutazione",
                _dg(_di("P/E", "price_earnings"),
                    _di("P/BV", "price_to_book"),
                    _di("Dividend Yield", "dividend_yield"),
                    _di("Dividendo Distribuito", "dividendo_dist")))
            body = (
                hero
                + _sec("Rendimento e Rischio",
                    _dg(_di("Da inizio anno (YTD)", "rendimento_ytd"),
                        _di("Rendimento 1A", "rendimento_1a"),
                        _di("Rendimento 3A", "rendimento_3a"),
                        _di("Rendimento Medio Annuo", "rendimento_medio"),
                        _di("Beta", "beta"),
                        _di("Deviazione Standard", "deviazione_std"),
                        _di("Indice di Sharpe", "sharpe"),
                        _di("VaR", "var")))
                + val_sec
                + _sec("Costi e Categoria",
                    _dg(_di("TER", "ter"),
                        _di("Benchmark", "benchmark"),
                        _di("Categoria", "categoria_etf"),
                        _di("Emittente", "emittente"),
                        _di("Patrimonio (mln €)", "patrimonio"),
                        _di("Distribuzione", "distribuzione"),
                        _di("Fiscalità", "fiscalita"),
                        _di("Data Lancio", "data_lancio", val_override=_vd("data_lancio")),
                        rating_item))
                + (_sec("Top Holdings", holdings_html) if holdings_html else "")
                + posizione_sec
            )
        else:  # fam / fondo
            ytd = _vs("rendimento_ytd"); r1 = _vs("rendimento_1a"); r3 = _vs("rendimento_3a")
            hero = (
                f'<div class="hero hero-3">'
                + _kpi(ytd, "Da inizio anno (YTD)")
                + _kpi(r1, "Rendimento 1 Anno")
                + _kpi(r3, "Rendimento 3 Anni")
                + "</div>"
            )
            stars_str = _stars()
            stars_item = (f'<div class="di"><div class="lbl">Rating Morningstar</div>'
                          f'<div class="val"><span class="stars">{stars_str}</span></div></div>') if stars_str else ""
            comp_html = (
                _comp_bar("Azionario", "composizione_az", "bar-az")
                + _comp_bar("Obbligazionario", "composizione_obbl", "bar-ob")
                + _comp_bar("Liquidità", "composizione_liq", "bar-liq")
            )
            body = (
                hero
                + _sec("Rendimento",
                    _dg(_di("YTD", "rendimento_ytd"),
                        _di("1 Anno", "rendimento_1a"),
                        _di("3 Anni", "rendimento_3a")))
                + _sec("Costi e Categoria",
                    _dg(_di("TER (commissione gestione)", "ter"),
                        _di("Categoria Morningstar", "categoria_fam"),
                        _di("Livello Rischio (1–7)", "livello_rischio"),
                        stars_item))
                + (_sec("Composizione Asset", comp_html) if comp_html.strip() else "")
                + _sec("Dettagli Fondo",
                    _dg(_di("Data Lancio", "data_lancio"),
                        _di("Patrimonio", "patrimonio"),
                        _di("Valuta NAV", "valuta"),
                        _di("Max 52 Settimane", "max_52w"),
                        _di("Min 52 Settimane", "min_52w")))
                + posizione_sec
            )

        if not any(tag in body for tag in ("kpi-card", "sec")):
            body = f'<div class="sec"><p style="color:var(--slate-400);font-size:13px;">Nessun dato disponibile — vai in <strong><a href="/strumenti?tab=arricchimento&amp;ticker={ticker}">Strumenti &#8594; Arricchimento</a></strong> per caricarli (automatico, da PDF o a mano).</p></div>'

        return _html_open() + body + '<div class="foot"></div>' + _html_close()


@router.get("/strumento/{ticker}", response_class=HTMLResponse)
async def get_scheda_strumento(ticker: str):
    from persistence.storage import load_data as _ld, load_settings as _ls, apply_privacy_filter
    d = apply_privacy_filter(_ld(), _ls())
    strumento = next((s for s in (d.get("strumenti") or []) if s.get("ticker") == ticker), None)
    if strumento is None:
        return HTMLResponse(f"<h3>Strumento '{ticker}' non trovato.</h3>", status_code=404)
    return HTMLResponse(_render_scheda_strumento(strumento))
