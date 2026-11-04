"""Servizi read-only per la trasparenza del benchmark di portafoglio.

Il modulo non modifica dati, cache o impostazioni: rende esplicita la logica
benchmark gia' usata dall'applicativo e produce payload pronti per Cruscotti e
Impostazioni.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from persistence.storage import macro_cat
from core.benchmark_registry import resolve_instrument_benchmark as _central_resolve_instrument_benchmark
from core.domain.positions import held_tickers
from core.domain.returns import simple_period_return, normalize_asof_datetime

BENCHMARK_TICKER_FALLBACKS = {}

# Fallback per macro-categoria usati quando l'anagrafica strumento non ha
# un benchmark puntuale ma altre aree dell'applicativo mostrano comunque un
# riferimento concettuale (es. GOV -> Bond Index in Quotazioni).
# Non rende il proxy perfetto: lo rende esplicito e calcolabile quando la
# relativa serie e' presente in cache.
# Nessun fallback di classe/categoria: si usa solo il registro centrale.
INSTRUMENT_BENCHMARK_CATEGORY_FALLBACKS = {}
INSTRUMENT_BENCHMARK_TYPE_FALLBACKS = {}


def get_effective_portfolio_benchmark_label(settings: dict[str, Any] | None) -> str:
    if not isinstance(settings, dict):
        return "Blend automatico"
    benchmarking = settings.get("benchmarking", {}) if isinstance(settings.get("benchmarking", {}), dict) else {}
    raw_components = benchmarking.get("custom_components", [])
    valid_custom = bool(benchmarking.get("custom_enabled", False)) and isinstance(raw_components, list) and any(
        isinstance(item, dict) and str(item.get("ticker", "")).strip() and _safe_float(item.get("weight"), 0.0) > 0
        for item in raw_components
    )
    if valid_custom:
        return str(benchmarking.get("custom_name") or "Benchmark personalizzato")
    return str(settings.get("portfolio_benchmark_default") or benchmarking.get("default_portfolio_benchmark") or "Blend automatico")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def resolve_effective_benchmark_components(
    settings: dict[str, Any] | None,
    da_frame: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Componenti effettivi del benchmark di portafoglio, letti dall'archivio (ricerca sul web, ADR-0021)."""
    from core.benchmark_discovery.portfolio import resolve_portfolio_components
    from core.verified_benchmarks import IndexStore
    return resolve_portfolio_components(settings, da_frame, IndexStore(),
                                        label=get_effective_portfolio_benchmark_label(settings))


def _history_frame(records: Any, value_col: str = "indice") -> pd.DataFrame:
    if not isinstance(records, list) or not records:
        return pd.DataFrame(columns=["date", value_col])
    df = pd.DataFrame(records)
    if "data" not in df.columns or value_col not in df.columns:
        return pd.DataFrame(columns=["date", value_col])
    # Le date dei JSON applicativi sono ISO. dayfirst=True converte
    # ambiguamente 2024-01-02 in 02/01 o 01/02 e tronca i confronti!
    as_text=df['data'].astype(str).str.strip()
    iso=as_text.str.match(r'^\d{4}-\d{2}-\d{2}(?:T.*)?$')
    df['date']=pd.NaT
    df.loc[iso,'date']=pd.to_datetime(as_text[iso].str[:10],format='%Y-%m-%d',errors='coerce')
    df.loc[~iso,'date']=pd.to_datetime(as_text[~iso],dayfirst=True,errors='coerce')
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
    return df.dropna(subset=["date", value_col]).sort_values("date")[["date", value_col]].reset_index(drop=True)


def _series_return(df: pd.DataFrame, col: str = "indice") -> float | None:
    if df is None or df.empty or col not in df.columns or len(df) < 2:
        return None
    vals = pd.to_numeric(df[col], errors="coerce").dropna()
    if len(vals) < 2:
        return None
    return simple_period_return(vals.iloc[0], vals.iloc[-1])


def _series_cagr(df: pd.DataFrame, col: str = "indice") -> float | None:
    ret = _series_return(df, col)
    if ret is None or ret <= -1 or df is None or df.empty or len(df) < 2:
        return None
    days = max(int((pd.to_datetime(df["date"].iloc[-1]) - pd.to_datetime(df["date"].iloc[0])).days), 1)
    return float((1.0 + ret) ** (365.25 / days) - 1.0)


def _series_max_drawdown(df: pd.DataFrame, col: str = "indice") -> float | None:
    if df is None or df.empty or col not in df.columns or len(df) < 2:
        return None
    vals = pd.to_numeric(df[col], errors="coerce").dropna()
    if len(vals) < 2:
        return None
    running = vals.cummax()
    dd = vals / running - 1.0
    return float(dd.min())


def _component_cache_state(data:dict[str,Any]|None,ticker:str)->dict[str,Any]:
    from core.verified_benchmarks import IndexStore, stored_history
    raw=stored_history(data if isinstance(data,dict) else {},ticker)
    try:kind=IndexStore()._spec(ticker).asset_kind
    except ValueError:kind=''
    label='SQLite • ETF proxy' if kind=='etf_proxy' else 'SQLite • indice'
    return {'points':len(raw),'first_date':min(raw,default=''),
            'last_date':max(raw,default=''),'source':label if raw else 'Da aggiornare'}


def _rows_to_price_frame(date_raw_list: list[Any], value_list: list[Any], value_col: str) -> pd.DataFrame:
    """Converte liste parallele data/valore in serie ordinata e pulita.

    Vettorizza la conversione: `pd.to_datetime`/`pd.to_numeric` vengono
    chiamati una sola volta sull'intera lista invece che riga per riga
    (l'anti-pattern precedente costava ~5.7s su 976 date x 16 strumenti).
    Contratto di output invariato: stesse colonne, stesso ordinamento,
    stesso dedup, stesso filtro (data valida, valore valido, valore > 0).
    """
    if not date_raw_list:
        return pd.DataFrame(columns=["date", value_col])
    # format="mixed": la versione riga-per-riga precedente parsava ogni data
    # indipendentemente (pd.to_datetime(date_raw) per elemento); la versione
    # vettorizzata senza questo parametro inferisce UN solo formato dal primo
    # elemento e forza a NaT tutto cio' che non lo rispetta. Con format="mixed"
    # torna l'inferenza per-elemento (sempre vettorizzata, non un loop
    # Python), restando robusta a date storiche/eterogenee anche se sui dati
    # di produzione (uniformemente YYYY-MM-DD) la differenza e' oggi dormiente.
    dates = pd.to_datetime(pd.Series(date_raw_list), errors="coerce", format="mixed")
    values = pd.to_numeric(pd.Series(value_list), errors="coerce")
    mask = dates.notna() & values.notna() & (values > 0)
    if not mask.any():
        return pd.DataFrame(columns=["date", value_col])
    df = pd.DataFrame({
        "date": dates[mask].reset_index(drop=True),
        value_col: values[mask].astype(float).reset_index(drop=True),
    })
    return df.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)


def _date_price_mapping_to_frame(mapping: Any, value_col: str = "price") -> pd.DataFrame:
    """Converte un mapping data->prezzo in serie ordinata e pulita."""
    if not isinstance(mapping, dict) or not mapping:
        return pd.DataFrame(columns=["date", value_col])
    return _rows_to_price_frame(list(mapping.keys()), list(mapping.values()), value_col)


def instrument_price_history(data: dict[str, Any] | None, ticker: str) -> pd.DataFrame:
    storico = data.get("storico_prezzi", {}) if isinstance(data, dict) else {}
    if not isinstance(storico, dict) or not ticker:
        return pd.DataFrame(columns=["date", "strumento"])
    date_raw_list = []
    value_list = []
    for date_raw, by_ticker in storico.items():
        if not isinstance(by_ticker, dict) or ticker not in by_ticker:
            continue
        date_raw_list.append(date_raw)
        value_list.append(by_ticker.get(ticker))
    return _rows_to_price_frame(date_raw_list, value_list, "strumento")


def benchmark_price_history(data: dict[str, Any] | None, bench_ticker: str) -> pd.DataFrame:
    from core.verified_benchmarks import stored_history
    raw = stored_history(data if isinstance(data,dict) else {},bench_ticker)
    return _date_price_mapping_to_frame(raw, "benchmark")


def _align_instrument_benchmark(inst: pd.DataFrame, bench: pd.DataFrame) -> pd.DataFrame:
    if inst is None or inst.empty or bench is None or bench.empty:
        return pd.DataFrame(columns=["date", "strumento", "benchmark"])
    left = inst.copy()
    right = bench.copy()
    left["date"] = pd.to_datetime(left["date"], errors="coerce")
    right["date"] = pd.to_datetime(right["date"], errors="coerce")
    left = left.dropna(subset=["date", "strumento"]).set_index("date").sort_index()
    right = right.dropna(subset=["date", "benchmark"]).set_index("date").sort_index()
    if left.empty or right.empty:
        return pd.DataFrame(columns=["date", "strumento", "benchmark"])
    # Allineamento rigoroso sul periodo comune, senza estrapolazione del
    # benchmark oltre l'ultima quotazione valida (o prima del primo dato).
    start=max(left.index.min(),right.index.min())
    end=min(left.index.max(),right.index.max())
    if end<=start:
        return pd.DataFrame(columns=["date", "strumento", "benchmark"])
    aligned = pd.concat([left, right], axis=1).sort_index()
    last_left=pd.Series(aligned.index.where(aligned["strumento"].notna()),index=aligned.index).ffill()
    last_right=pd.Series(aligned.index.where(aligned["benchmark"].notna()),index=aligned.index).ffill()
    aligned=aligned.ffill().loc[(aligned.index>=start)&(aligned.index<=end)]
    last_left=last_left.loc[aligned.index]
    last_right=last_right.loc[aligned.index]
    # Non trasformare lunghi buchi di quotazioni in una curva fittizia piatta.
    age_left=(aligned.index.to_series()-last_left).dt.days
    age_right=(aligned.index.to_series()-last_right).dt.days
    aligned=aligned.loc[(age_left<=7)&(age_right<=7)].dropna(subset=["strumento", "benchmark"])
    if aligned.empty:
        return pd.DataFrame(columns=["date", "strumento", "benchmark"])
    return aligned.reset_index()


def _return_from_aligned(aligned: pd.DataFrame, col: str) -> float | None:
    if aligned is None or aligned.empty or col not in aligned.columns or len(aligned) < 2:
        return None
    vals = pd.to_numeric(aligned[col], errors="coerce").dropna()
    if len(vals) < 2 or float(vals.iloc[0]) == 0:
        return None
    return float(vals.iloc[-1] / vals.iloc[0] - 1.0)


def _aligned_return_metrics(aligned: pd.DataFrame) -> dict[str, Any]:
    if aligned is None or aligned.empty or len(aligned) < 2:
        return {
            "instrument_return": None,
            "benchmark_return": None,
            "extra_return": None,
            "correlation": None,
            "tracking_error": None,
            "points": int(len(aligned)) if aligned is not None else 0,
            "start": "",
            "end": "",
        }
    out = {
        "instrument_return": _return_from_aligned(aligned, "strumento"),
        "benchmark_return": _return_from_aligned(aligned, "benchmark"),
        "extra_return": None,
        "correlation": None,
        "tracking_error": None,
        "points": int(len(aligned)),
        "start": pd.to_datetime(aligned["date"].iloc[0]).date().isoformat(),
        "end": pd.to_datetime(aligned["date"].iloc[-1]).date().isoformat(),
    }
    if out["instrument_return"] is not None and out["benchmark_return"] is not None:
        out["extra_return"] = float(out["instrument_return"] - out["benchmark_return"])
    returns = aligned[["strumento", "benchmark"]].pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    if len(returns) >= 10:
        corr = returns["strumento"].corr(returns["benchmark"])
        if pd.notna(corr):
            out["correlation"] = float(corr)
        diff = returns["strumento"] - returns["benchmark"]
        te = diff.std(ddof=1)
        if pd.notna(te):
            out["tracking_error"] = float(te * np.sqrt(252.0))
    return out


def _resolve_instrument_benchmark(
    *,
    raw_type: str,
    category: str,
    master_entry: dict[str, Any] | None = None,
    instrument: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Wrapper locale sul registro centrale benchmark strumenti."""
    assignment = _central_resolve_instrument_benchmark(
        instrument if isinstance(instrument, dict) else {},
        raw_type=raw_type,
        category=category,
        master_entry=master_entry,
        prefer_master=True,
    )
    return {**assignment.as_dict(), 'relation_grade':str(assignment.relation_grade),
            'operational_kind':assignment.operational_kind,'note':assignment.note,
            'components':list(assignment.components)}

def _benchmark_source(raw_type: str, bench_ticker: str | None, source_hint: str | None = None) -> str:
    if source_hint:
        return str(source_hint)
    if not bench_ticker:
        return "assente"
    return "registro centrale"

def _compatibility_score(raw_type: str, bench_ticker: str | None, correlation: Any, points: int) -> float | None:
    if not bench_ticker:
        return None
    mapping_confidence = 0.25 if bench_ticker else 0.0
    if correlation is None or pd.isna(correlation):
        data_confidence = 0.25 if int(points or 0) >= 20 else 0.10
    else:
        # correlation -1..1 -> 0..0.75, con taglio prudente entro il range.
        data_confidence = max(0.0, min(0.75, ((float(correlation) + 1.0) / 2.0) * 0.75))
    return float(max(0.0, min(1.0, mapping_confidence + data_confidence)))


def _compatibility_label(score: Any, points: int, bench_ticker: str | None) -> str:
    if not bench_ticker:
        return "Senza benchmark"
    if int(points or 0) < 20:
        return "Dati insufficienti"
    if score is None or pd.isna(score):
        return "Da verificare"
    score = float(score)
    if score >= 0.78:
        return "Alta"
    if score >= 0.58:
        return "Media"
    if score >= 0.40:
        return "Bassa"
    return "Da verificare"


def _benchmark_status(compatibility: str, extra_return: Any) -> str:
    if compatibility == "Senza benchmark":
        return "Senza benchmark"
    if compatibility in {"Dati insufficienti", "Da verificare"}:
        return compatibility
    v = _safe_float(extra_return, None)
    if v is None:
        return "Confronto parziale"
    if v >= 0.02:
        return "Sovraperforma"
    if v <= -0.02:
        return "Sottoperforma"
    return "Allineato"


def _position_values_by_ticker(da_frame: pd.DataFrame | None) -> dict[str, float]:
    if da_frame is None or da_frame.empty or "Ticker" not in da_frame.columns:
        return {}
    value_col = "Controvalore" if "Controvalore" in da_frame.columns else None
    if value_col is None:
        return {}
    tmp = da_frame.copy()
    tmp["Ticker"] = tmp["Ticker"].astype(str)
    tmp[value_col] = pd.to_numeric(tmp[value_col], errors="coerce").fillna(0.0)
    return tmp.groupby("Ticker")[value_col].sum().to_dict()


def build_instrument_benchmark_matrix(
    data: dict[str, Any] | None,
    da_frame: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Costruisce una matrice read-only strumento/benchmark.

    Il confronto e' prezzo strumento vs prezzo benchmark, normalizzato sul periodo
    comune disponibile. Non simula i flussi di acquisto reali dell'investitore.
    """
    data = data if isinstance(data, dict) else {}
    strumenti = data.get("strumenti", []) if isinstance(data.get("strumenti", []), list) else []
    master = data.get("instrument_master", {}) if isinstance(data.get("instrument_master", {}), dict) else {}
    values = _position_values_by_ticker(da_frame)
    held = held_tickers(data)
    rows: list[dict[str, Any]] = []
    for s in strumenti:
        if not isinstance(s, dict):
            continue
        ticker = str(s.get("ticker") or "").strip()
        if not ticker:
            continue
        # "In portafoglio" per questa matrice significa "possiedo quote ora":
        # il campo stato puo' restare "aperto" anche dopo una vendita totale
        # se nessuno lo ritagga a mano, quindi il criterio e' la quantita'
        # reale calcolata dagli eventi (held_tickers), non lo stato dichiarato
        # — stesso criterio di ui/charts/benchmark.py::get_all_historical_tickers.
        if ticker not in held:
            continue
        m = master.get(ticker, {}) if isinstance(master.get(ticker, {}), dict) else {}
        raw_type = str(m.get("type_raw") or s.get("tipo") or "")
        category = macro_cat(raw_type)
        resolved_benchmark = _resolve_instrument_benchmark(raw_type=raw_type, category=category, master_entry=m, instrument=s)
        bench_ticker = str(resolved_benchmark.get("ticker") or "").strip() or None
        bench_label = str(resolved_benchmark.get("label") or bench_ticker or "").strip()
        source = _benchmark_source(raw_type, bench_ticker, resolved_benchmark.get("source"))
        aligned = pd.DataFrame()
        metrics = _aligned_return_metrics(aligned)
        if bench_ticker:
            inst_hist = instrument_price_history(data, ticker)
            bench_hist = benchmark_price_history(data, bench_ticker)
            aligned = _align_instrument_benchmark(inst_hist, bench_hist)
            metrics = _aligned_return_metrics(aligned)
        score = _compatibility_score(raw_type, bench_ticker, metrics.get("correlation"), int(metrics.get("points") or 0))
        label = _compatibility_label(score, int(metrics.get("points") or 0), bench_ticker)
        # Correlazione statistica alta non rende congruo un ETF proxy.
        # Separazione tra coerenza economica e somiglianza dei prezzi.
        grade=str(resolved_benchmark.get('relation_grade') or '')
        kind=str(resolved_benchmark.get('operational_kind') or '')
        # La correlazione misura somiglianza statistica, non congruenza
        # economica; mai assegnare Alta a ETF/spot o parenti lontani.
        if kind in ('etf_proxy','spot_proxy','composite') and label=='Alta':
            label='Media'
        if grade in ('MADRE','CUGINA','NONNA','ZIA','ULTIMO_PARENTE') and label in ('Alta','Media'):
            label='Bassa'
        if not bench_ticker:label='Senza benchmark'
        rows.append({
            "ticker": ticker,
            "strumento": str(s.get("nome") or m.get("name") or ticker),
            "tipo": raw_type,
            "categoria": category,
            "benchmark_ticker": bench_ticker or "",
            "benchmark_label": bench_label or "—",
            "benchmark_source": source,
            "relation_grade": resolved_benchmark.get('relation_grade',''),
            "benchmark_note": resolved_benchmark.get('note',''),
            "benchmark_kind": resolved_benchmark.get('operational_kind',''),
            "benchmark_components": resolved_benchmark.get('components',[]),
            "compatibility_score": score,
            "compatibility_label": label,
            "instrument_return": metrics.get("instrument_return"),
            "benchmark_return": metrics.get("benchmark_return"),
            "extra_return": metrics.get("extra_return"),
            "correlation": metrics.get("correlation"),
            "tracking_error": metrics.get("tracking_error"),
            "points": int(metrics.get("points") or 0),
            "period_start": metrics.get("start") or "",
            "period_end": metrics.get("end") or "",
            "status": ("Indicativo" if kind in ("etf_proxy","spot_proxy","composite") or grade in ("MADRE","CUGINA","NONNA","ZIA","ULTIMO_PARENTE") else _benchmark_status(label, metrics.get("extra_return"))),
            "controvalore": float(values.get(ticker, 0.0) or 0.0),
        })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    order_cols = ["compatibility_score", "controvalore", "ticker"]
    return df.sort_values(order_cols, ascending=[False, False, True], na_position="last").reset_index(drop=True)


def build_benchmark_transparency_payload(
    *,data: dict[str, Any] | None, settings: dict[str, Any] | None,
    da_frame: pd.DataFrame | None, summary_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """KPI e grafico sempre ricalcolati su dati SQLite e DATE COMUNI.

    Summary puo' rimanere congelato per la UI, ma non puo' essere fonte
    di benchmark_history o di metriche relative gia' superate dal refresh DB.
    """
    from core.finance import build_portfolio_benchmark_series
    from core.verified_benchmarks import IndexStore
    summary_payload=summary_payload if isinstance(summary_payload,dict) else {}
    data=data if isinstance(data,dict) else {}
    cfg=resolve_effective_benchmark_components(settings,da_frame)
    store=IndexStore()
    components=[]
    for item in cfg.get('components',[]):
        state=_component_cache_state(data,str(item.get('ticker') or ''))
        components.append({**item,**state})
    port=_history_frame(summary_payload.get('summary_history',[]),'indice')
    bench=pd.DataFrame(columns=['date','indice'])
    diagnostic=[]
    if cfg.get('missing_components'):
        diagnostic.append('Componenti non disponibili in SQLite: '+', '.join(x['family'] for x in cfg['missing_components']))
    if not port.empty and not cfg.get('missing_components'):
        try:
            b=build_portfolio_benchmark_series(
                data,cfg.get('label',''),da_frame if da_frame is not None else pd.DataFrame(),
                min_date=port['date'].iloc[0],settings=settings)
            if b is not None and len(b)>=2:
                bench=pd.DataFrame({'date':pd.to_datetime(b.index),'indice':pd.to_numeric(b.values,errors='coerce')})
            else:
                diagnostic.append('Benchmark composito privo di storico comune sufficiente.')
        except Exception as exc:
            diagnostic.append(f'Calcolo benchmark non riuscito: {type(exc).__name__}: {exc}')

    # Periodo comune senza anticipare quotazioni, ffill massimo 7 giorni.
    aligned=pd.DataFrame(columns=['date','portafoglio','benchmark'])
    if not port.empty:
        left=normalize_asof_datetime(port.rename(columns={'indice':'portafoglio'}))
        if not bench.empty:
            right=normalize_asof_datetime(bench.rename(columns={'indice':'benchmark'}))
            if not left.empty and not right.empty:
                start=max(left['date'].min(),right['date'].min())
                end=min(left['date'].max(),right['date'].max())
                if end>start:
                    left=left.loc[left['date'].between(start,end)]
                    # backward ONLY: nessun look-ahead e niente trascinamento
                    # di quotazioni vecchie oltre una settimana.
                    aligned=pd.merge_asof(left,right,on='date',direction='backward',
                                          tolerance=pd.Timedelta(days=7)).dropna(subset=['portafoglio','benchmark'])
        if aligned.empty:
            aligned=left.copy()
            aligned['benchmark']=np.nan
    available=aligned.dropna(subset=['benchmark']) if not aligned.empty else pd.DataFrame()
    comparable=len(available)>=2
    if comparable:
        p_ret=_series_return(available[['date','portafoglio']].rename(columns={'portafoglio':'indice'}))
        b_ret=_series_return(available[['date','benchmark']].rename(columns={'benchmark':'indice'}))
        p_cagr=_series_cagr(available[['date','portafoglio']].rename(columns={'portafoglio':'indice'}))
        b_cagr=_series_cagr(available[['date','benchmark']].rename(columns={'benchmark':'indice'}))
        p_dd=_series_max_drawdown(available[['date','portafoglio']].rename(columns={'portafoglio':'indice'}))
        b_dd=_series_max_drawdown(available[['date','benchmark']].rename(columns={'benchmark':'indice'}))
        daily=available[['portafoglio','benchmark']].pct_change().replace([np.inf,-np.inf],np.nan).dropna()
        active=daily['portafoglio']-daily['benchmark'] if len(daily)>=10 else pd.Series(dtype=float)
        std=float(active.std(ddof=1)) if len(active)>1 else 0.0
        tracking=float(std*np.sqrt(252)) if std>0 else None
        info=float(active.mean()/std*np.sqrt(252)) if std>0 else None
        period={'start':available['date'].iloc[0].date().isoformat(),
                'end':available['date'].iloc[-1].date().isoformat()}
    else:
        p_ret=_series_return(port);b_ret=None
        p_cagr=_series_cagr(port);b_cagr=None
        p_dd=_series_max_drawdown(port);b_dd=None
        tracking=info=None
        period={'start':port['date'].iloc[0].date().isoformat() if not port.empty else '',
                'end':port['date'].iloc[-1].date().isoformat() if not port.empty else ''}
    metrics={
        'portfolio_return':p_ret,'benchmark_return':b_ret,
        'excess_return':float(p_ret-b_ret) if p_ret is not None and b_ret is not None else None,
        'portfolio_cagr':p_cagr,'benchmark_cagr':b_cagr,
        'portfolio_max_drawdown':p_dd,'benchmark_max_drawdown':b_dd,
        'tracking_error':tracking,'information_ratio':info,
    }
    matrix=build_instrument_benchmark_matrix(data,da_frame)
    last_cache_date=max((str(c.get('last_date') or '') for c in components),default='')
    return {
       'config':{**cfg,'components':components},'period':period,
       'last_cache_date':last_cache_date,'history':aligned,
       'instrument_matrix':matrix,'metrics':metrics,
       'availability':{'portfolio_points':len(port),'benchmark_points':len(bench),
                       'aligned_points':len(available),'instrument_benchmark_rows':len(matrix),
                       'has_benchmark':comparable,'problems':diagnostic},
       'method_note':cfg.get('method_note',''),
       'data_revision':store.revision_token(),
    }


def benchmark_explanation(payload: dict[str, Any]) -> str:
    cfg = payload.get("config", {}) if isinstance(payload, dict) else {}
    metrics = payload.get("metrics", {}) if isinstance(payload, dict) else {}
    label = str(cfg.get("label") or "Benchmark")
    mode = str(cfg.get("mode") or "")
    ex = metrics.get("excess_return")
    te = metrics.get("tracking_error")
    ir = metrics.get("information_ratio")
    bits = [f"Benchmark attivo: {label} ({mode})."]
    note = str(payload.get("method_note") or "")
    if note:
        bits.append(note)
    if ex is not None:
        ex_v = _safe_float(ex)
        bits.append("Il portafoglio e' sopra il benchmark nel periodo selezionato." if ex_v >= 0 else "Il portafoglio e' sotto il benchmark nel periodo selezionato.")
    if te is not None:
        te_v = _safe_float(te)
        if te_v < 0.05:
            bits.append("Tracking error contenuto: il portafoglio si muove vicino al riferimento.")
        elif te_v < 0.15:
            bits.append("Tracking error intermedio: il portafoglio si discosta in modo apprezzabile dal riferimento.")
        else:
            bits.append("Tracking error elevato: il portafoglio e' molto diverso dal riferimento.")
    if ir is not None:
        ir_v = _safe_float(ir)
        if ir_v >= 0.5:
            bits.append("Information ratio positivo e robusto: l'extra-rendimento e' coerente con lo scostamento assunto.")
        elif ir_v >= 0:
            bits.append("Information ratio positivo ma prudente: l'extra-rendimento c'e', ma non e' ancora molto robusto.")
        else:
            bits.append("Information ratio negativo: lo scostamento dal benchmark non ha prodotto valore aggiunto nel periodo.")
    return " ".join(bits)
