# -*- coding: utf-8 -*-
"""
POC5.2 CORRECTED
================
- Fixes pandas DataFrame truth-value bug in Yahoo FundsData.
- No ETF can be selected as benchmark.
- Generic provider discovery (MSCI, Nasdaq) restores exact benchmarks.
- Exact Yahoo INDEX only, never ETF.
- Sovereign/BTP fallback is a synthetic constant-duration total-return curve.
- Generic EUR bond fallback uses a synthetic ECB duration-matched curve.
- Trend Similarity and Tracking Adherence are separate.
- Curve comparison is FX-normalised where possible.
- Core/Defensive/Satellite is ontology-driven, not ticker-driven.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from html import unescape
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
import json, math, re, unicodedata, pickle, time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import yfinance as yf

from poc5_2_catalog import BENCHMARK_IDENTITIES, BenchmarkIdentity  # optional provider bootstrap, never instrument mappings

HTTP_TIMEOUT = 10
YF_TIMEOUT = 10
ROLE_MIN_PERCENT = 20.0
CHART_MIN_COMMON_OBS = 60
CHART_TARGET_COMMON_OBS = 90
FETCH_DAYS = 400
SYNTH_MIN_OBS = 60
ProgressCallback = Callable[[str], None]


# Optional external portfolio JSON source.
# It is used ONLY as an instrument-history/metadata source, never as a benchmark map.
_PORTFOLIO_SOURCE = {"path": "", "data": None, "by_ticker": {}, "by_isin": {}, "history": {}}

def set_portfolio_data(path):
    """
    Load a portfolio JSON containing `strumenti` and `storico_prezzi`.
    Generic matching is by ticker/ISIN. No instrument-specific rules.
    """
    global _PORTFOLIO_SOURCE
    if not path:
        _PORTFOLIO_SOURCE = {"path": "", "data": None, "by_ticker": {}, "by_isin": {}, "history": {}}
        return False
    p=Path(path)
    data=json.loads(p.read_text(encoding="utf-8"))
    instruments=data.get("strumenti") or []
    by_ticker={}
    by_isin={}
    for row in instruments:
        if not isinstance(row,dict): continue
        t=norm(row.get("ticker")).upper()
        i=norm(row.get("isin")).upper()
        if t: by_ticker[t]=row
        if i: by_isin[i]=row
    hist=data.get("storico_prezzi") or {}
    _PORTFOLIO_SOURCE={"path":str(p),"data":data,"by_ticker":by_ticker,"by_isin":by_isin,"history":hist}
    return True

def portfolio_record(ticker="",isin=""):
    t=norm(ticker).upper(); i=norm(isin).upper()
    return _PORTFOLIO_SOURCE["by_isin"].get(i) or _PORTFOLIO_SOURCE["by_ticker"].get(t)

def portfolio_history_series(ticker="",isin="",history_key=""):
    """
    Extract instrument history from `storico_prezzi`.
    The external JSON can use an internal portfolio ticker different from Yahoo.
    """
    rec=portfolio_record(ticker,isin) or {}
    keys=[]
    for x in (history_key, rec.get("ticker"), ticker):
        x=norm(x)
        if x and x not in keys: keys.append(x)
    if not keys: return None
    vals=[]
    for ds,row in (_PORTFOLIO_SOURCE.get("history") or {}).items():
        if not isinstance(row,dict): continue
        value=None
        for k in keys:
            if k in row and row[k] is not None:
                value=row[k]; break
        if value is None: continue
        try: vals.append((pd.Timestamp(ds),float(value)))
        except Exception: pass
    if not vals: return None
    s=pd.Series(dict(vals),dtype=float).sort_index()
    return clean_series(s)

def _pct_text(v):
    if v is None:return None
    try:
        s=str(v).strip().replace("%","").replace(",",".")
        x=float(s)
        return x/100.0 if x>1 else x
    except Exception:return None

def merge_portfolio_metadata(e):
    """
    Generic enrichment from the user's own portfolio JSON.
    It can supply asset mix hints and benchmark/category text.
    """
    rec=portfolio_record(e.ticker,e.isin)
    if not rec:return
    # Portfolio descriptive names are first-class evidence. A venue alias
    # such as IWQU.L / XGIN.DE must never win over a richer economic name.
    e.name=_richer_text(e.name,norm(rec.get("nome")))
    e.currency=e.currency or norm(rec.get("valuta")) or norm(rec.get("valuta_etf"))
    cat=norm(rec.get("categoria_fam")) or norm(rec.get("categoria_etf")) or norm(rec.get("tipo"))
    nature=norm(rec.get("natura")); typ=norm(rec.get("tipo"))
    e.category=e.category or cat
    extra_desc=" | ".join(x for x in (nature,typ) if x)
    if extra_desc and extra_desc.casefold() not in (e.description or "").casefold():
        e.description=(e.description+" | " if e.description else "")+extra_desc
    e.benchmark_name=e.benchmark_name or norm(rec.get("benchmark"))
    eq=_pct_text(rec.get("composizione_az"))
    bd=_pct_text(rec.get("composizione_obbl"))
    if eq is not None or bd is not None:
        amap=dict(e.asset_classes)
        if eq is not None: amap["stockPosition"]=eq
        if bd is not None: amap["bondPosition"]=bd
        rem=max(0.0,1.0-sum(v for v in amap.values() if isinstance(v,(int,float)) and 0<=v<=1))
        if rem>0.001: amap.setdefault("cashPosition",rem)
        e.asset_classes=amap
    e.sources.append("Portfolio JSON")


@dataclass(slots=True)
class Evidence:
    ticker: str = ""
    isin: str = ""
    yahoo_symbol: str = ""
    history_key: str = ""
    instrument_type: str = ""
    name: str = ""
    description: str = ""
    category: str = ""
    currency: str = ""
    benchmark_name: str = ""
    benchmark_code: str = ""
    benchmark_area: str = ""
    country: str = ""
    maturity_date: str = ""
    maturity_years: float | None = None
    coupon_rate: float | None = None
    asset_classes: dict[str,float] = field(default_factory=dict)
    sector_weightings: dict[str,float] = field(default_factory=dict)
    bond_holdings: dict[str,float] = field(default_factory=dict)
    bond_ratings: dict[str,float] = field(default_factory=dict)
    top10_concentration: float | None = None
    volatility_1y: float | None = None
    sources: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Profile:
    asset: str = ""
    geography: str = ""
    geo_scope: str = ""
    breadth: str = ""
    sector: str = ""
    theme: str = ""
    factor: str = ""
    market_breadth: float = 0.0
    size: str = ""
    issuer_type: str = ""
    bond_style: str = ""
    duration_years: float | None = None
    duration_confidence: float = 0.0
    credit_quality: str = ""
    hedged: bool | None = None
    leveraged: bool = False
    inverse: bool = False
    gold: bool = False
    digital_asset: bool = False
    confidence: float = 0.0
    completeness: float = 0.0
    reasons: list[str] = field(default_factory=list)
    unrepresented: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExposureFingerprint:
    representativeness: float = 0.0
    breadth: float = 0.0
    diversification: float = 0.0
    concentration: float = 0.0
    specialization: float = 0.0
    geo_concentration: float = 0.0
    sector_concentration: float = 0.0
    factor_tilt: float = 0.0
    size_tilt: float = 0.0
    capital_stability: float = 0.0
    rate_risk: float = 0.0
    credit_risk: float = 0.0
    currency_risk: float = 0.0
    inflation_risk: float = 0.0
    sovereign_quality: float = 0.0
    liquidity: float = 0.0
    commodity_exposure: float = 0.0
    digital_exposure: float = 0.0
    leverage_risk: float = 0.0
    inverse_risk: float = 0.0
    multiasset_balance: float = 0.0
    evidence_confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Benchmark:
    level: str = ""
    provider: str = ""
    official_name: str = ""
    provider_id: str = ""
    variant: str = ""
    currency: str = ""
    operational_symbol: str = ""
    confidence: float = 0.0
    observations: int = 0
    last_date: str = ""
    target_duration: float | None = None
    components: str = ""
    note: str = ""
    series: pd.Series | None = None
    reference_components: list[dict[str,Any]] = field(default_factory=list)
    semantic_confidence: float = 0.0
    out_of_sample_score: float = 0.0
    relation_grade: str = ""
    geometry_score: float = 0.0
    selection_score: float = 0.0
    candidate_count: int = 0
    review_status: str = ""
    review_after_obs: int = 60
    next_review_obs: int = 0
    candidate_ladder: list[dict[str,Any]] = field(default_factory=list)
    role_similarity_score: float = 0.0
    candidate_role_core: float = 0.0
    candidate_role_defensive: float = 0.0
    candidate_role_satellite: float = 0.0


@dataclass(slots=True)
class RoleFit:
    raw_core: float = 0.0
    raw_defensive: float = 0.0
    raw_satellite: float = 0.0
    core: float = 0.0
    defensive: float = 0.0
    satellite: float = 0.0
    active_roles: list[str] = field(default_factory=list)
    confidence: float = 0.0
    flags: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CurveFit:
    available: bool = False
    common_obs: int = 0
    trend: float = 0.0
    trend_label: str = "N/D"
    corr5: float | None = None
    direction5: float | None = None
    spearman_level: float | None = None
    slope10_corr: float | None = None
    tracking: float = 0.0
    tracking_label: str = "N/D"
    corr1: float | None = None
    beta: float | None = None
    tracking_error: float | None = None
    path_rmse: float | None = None
    alignment_lag_days: int = 0
    note: str = ""


@dataclass(slots=True)
class Result:
    evidence: Evidence
    profile: Profile
    benchmark: Benchmark
    role: RoleFit
    instrument_series: pd.Series | None = None
    curve: CurveFit = field(default_factory=CurveFit)

    def flat(self) -> dict[str,Any]:
        return {
            "ticker": self.evidence.ticker,
            "isin": self.evidence.isin,
            "name": self.evidence.name,
            "structural_type": structural_type(self.profile),
            "profile_geography": self.profile.geography,
            "profile_geo_scope": self.profile.geo_scope,
            "profile_theme": self.profile.theme,
            "profile_sector": self.profile.sector,
            "profile_factor": self.profile.factor,
            "profile_size": self.profile.size,
            "profile_market_breadth": round(self.profile.market_breadth,3),
            "official_benchmark_identity_name": self.evidence.benchmark_name,
            "official_benchmark_identity_code": self.evidence.benchmark_code,
            "profile_confidence": round(self.profile.confidence,4),
            "profile_completeness": round(self.profile.completeness,4),
            "benchmark": self.benchmark.official_name,
            "benchmark_display_name": self.benchmark.official_name,
            "benchmark_code_display": (
                self.benchmark.operational_symbol
                or self.benchmark.provider_id
                or ""
            ),
            "benchmark_series_display": (
                self.benchmark.operational_symbol
                or (
                    f"{self.benchmark.provider}:{self.benchmark.provider_id}"
                    if self.benchmark.provider_id else ""
                )
            ),
            "benchmark_quality": benchmark_quality_label(self.benchmark),
            "provider": self.benchmark.provider,
            "resolution_level": self.benchmark.level,
            "provider_id": self.benchmark.provider_id,
            "operational_symbol": self.benchmark.operational_symbol,
            "benchmark_confidence": round(self.benchmark.confidence,4),
            "benchmark_obs": self.benchmark.observations,
            "benchmark_last_date": self.benchmark.last_date,
            "target_duration": round(self.benchmark.target_duration,4) if self.benchmark.target_duration is not None else "",
            "synthetic_components": self.benchmark.components,
            "raw_core_pct": round(self.role.raw_core,2),
            "raw_defensive_pct": round(self.role.raw_defensive,2),
            "raw_satellite_pct": round(self.role.raw_satellite,2),
            "core_pct": round(self.role.core,2),
            "defensive_pct": round(self.role.defensive,2),
            "satellite_pct": round(self.role.satellite,2),
            "active_roles": ", ".join(self.role.active_roles),
            "role_confidence": round(self.role.confidence,4),
            "role_validation_flags": " | ".join(self.role.flags),
            "cds_reliability_score": reliability_scores(self.evidence,self.profile,self.role,self.benchmark,self.curve)[0],
            "reference_reliability_score": reliability_scores(self.evidence,self.profile,self.role,self.benchmark,self.curve)[1],
            "overall_reliability_score": reliability_scores(self.evidence,self.profile,self.role,self.benchmark,self.curve)[2],
            "volatility_1y_pct": round(self.evidence.volatility_1y*100,2) if self.evidence.volatility_1y is not None else "",
            "trend_similarity_pct": round(self.curve.trend,2),
            "trend_label": self.curve.trend_label,
            "tracking_adherence_pct": round(self.curve.tracking,2),
            "tracking_label": self.curve.tracking_label,
            "curve_common_obs": self.curve.common_obs,
            "trend_return_5d_corr": round(self.curve.corr5,4) if self.curve.corr5 is not None else "",
            "trend_direction_5d_agreement_pct": round(self.curve.direction5*100,2) if self.curve.direction5 is not None else "",
            "trend_spearman_level": round(self.curve.spearman_level,4) if self.curve.spearman_level is not None else "",
            "trend_slope_10d_corr": round(self.curve.slope10_corr,4) if self.curve.slope10_corr is not None else "",
            "curve_return_corr": round(self.curve.corr1,4) if self.curve.corr1 is not None else "",
            "curve_beta": round(self.curve.beta,4) if self.curve.beta is not None else "",
            "curve_tracking_error_ann_pct": round(self.curve.tracking_error*100,3) if self.curve.tracking_error is not None else "",
            "curve_alignment_lag_days": self.curve.alignment_lag_days,
            "benchmark_note": self.benchmark.note,
            "reference_components": self.benchmark.reference_components,
            "reference_semantic_confidence": round(self.benchmark.semantic_confidence,4),
            "reference_oos_score": round(self.benchmark.out_of_sample_score,2),
            "reference_relation": self.benchmark.relation_grade,
            "reference_geometry_score": round(self.benchmark.geometry_score,2),
            "reference_role_similarity_score": round(self.benchmark.role_similarity_score,2),
            "reference_candidate_core_pct": round(self.benchmark.candidate_role_core,1),
            "reference_candidate_defensive_pct": round(self.benchmark.candidate_role_defensive,1),
            "reference_candidate_satellite_pct": round(self.benchmark.candidate_role_satellite,1),
            "reference_selection_score": round(self.benchmark.selection_score,2),
            "reference_candidate_count": self.benchmark.candidate_count,
            "reference_review_status": self.benchmark.review_status,
            "reference_next_review_obs": self.benchmark.next_review_obs,
            "reference_candidate_ladder": [
                {k:v for k,v in x.items() if k!="series"} for x in self.benchmark.candidate_ladder
            ],
            "curve_note": self.curve.note,
            "role_reasons": " | ".join(self.role.reasons),
            "sources": " | ".join(self.evidence.sources),
            "errors": " | ".join(self.evidence.errors),
        }


# ---------------- utilities ----------------

def log(cb,msg):
    if cb:
        try: cb(msg)
        except Exception: pass

def norm(x): return str(x or "").strip()

def ascii_text(x):
    s=unicodedata.normalize("NFKD",norm(x))
    return "".join(c for c in s if not unicodedata.combining(c)).casefold()

def tokens(x): return re.findall(r"[a-z0-9]+",ascii_text(x).replace("&"," and "))

def similarity(a,b):
    A,B=tokens(a),tokens(b)
    if not A or not B: return 0.0
    sa,sb=set(A),set(B); common=sa&sb
    j=len(common)/max(1,len(sa|sb))
    cov=len(common)/max(1,len(sa))
    seq=SequenceMatcher(None," ".join(A)," ".join(B)).ratio()
    return max(0.0,min(1.0,.34*j+.46*cov+.20*seq))

def pct(x):
    try: v=float(x)
    except Exception: return 0.0
    return max(0.0,v/100.0 if v>1.5 else v)

def http_bytes(url,headers=None):
    h={"User-Agent":"Mozilla/5.0 Chrome/124 Safari/537.36",
       "Accept-Language":"it-IT,it;q=0.9,en;q=0.8"}
    if headers: h.update(headers)
    with urlopen(Request(url,headers=h),timeout=HTTP_TIMEOUT) as r: return r.read()

def http_text(url,headers=None): return http_bytes(url,headers).decode("utf-8",errors="replace")

def strip_html(s):
    s=re.sub(r"<script\b[^>]*>.*?</script>"," ",s,flags=re.I|re.S)
    s=re.sub(r"<style\b[^>]*>.*?</style>"," ",s,flags=re.I|re.S)
    return re.sub(r"\s+"," ",unescape(re.sub(r"<[^>]+>"," ",s))).strip()

def extract(pat,text):
    m=re.search(pat,text,flags=re.I)
    return re.sub(r"\s+"," ",m.group(1)).strip(" -–—:;,.") if m else ""

def clean_series(s):
    """
    Normalize a history object to a dated pd.Series.
    Scalars are not histories and return None instead of crashing.
    """
    if s is None:
        return None
    if isinstance(s,pd.DataFrame):
        if s.empty:return None
        close_col=next((c for c in s.columns if str(c).lower() in ("close","adj close","price","value")),None)
        if close_col is None:
            nums=[c for c in s.columns if pd.api.types.is_numeric_dtype(s[c])]
            if not nums:return None
            close_col=nums[0]
        s=s[close_col]
    elif not isinstance(s,pd.Series):
        # numpy/python scalar or undated array/list -> not a usable time series
        return None

    if s.empty:return None
    vals=pd.to_numeric(s,errors="coerce")
    if not isinstance(vals,pd.Series):
        return None
    vals=vals.dropna().astype(float)
    if vals.empty:return None
    idx=pd.to_datetime(vals.index,errors="coerce")
    mask=~idx.isna()
    vals=vals.loc[mask]; idx=idx[mask]
    if len(vals)==0:return None
    try: idx=idx.tz_localize(None)
    except Exception: pass
    vals.index=idx.normalize()
    vals=vals[~vals.index.duplicated(keep="last")].sort_index()
    return vals if len(vals) else None


def mapping(raw):
    """Safe conversion: never evaluate pandas object truth-value."""
    if raw is None: return {}
    if isinstance(raw,dict): return dict(raw)
    if isinstance(raw,pd.Series): return raw.to_dict()
    if isinstance(raw,pd.DataFrame):
        if raw.empty: return {}
        if raw.shape[1]==1:
            c=raw.columns[0]; return {str(i):raw.loc[i,c] for i in raw.index}
        if raw.shape[0]==1: return raw.iloc[0].to_dict()
        c=raw.columns[0]; return {str(i):raw.loc[i,c] for i in raw.index}
    return {}

def float_mapping(raw,percent=False):
    out={}
    for k,v in mapping(raw).items():
        try: out[str(k)]=pct(v) if percent else float(v)
        except Exception: pass
    return out

def annual_vol(s):
    if s is None or len(s)<40: return None
    r=s.pct_change().dropna()
    return float(r.std(ddof=1)*math.sqrt(252)) if len(r)>=40 else None

def maturity_years(d):
    try: return max(0.0,(date.fromisoformat(d)-date.today()).days/365.25)
    except Exception: return None

def parse_coupon(name):
    m=re.search(r"(\d+(?:[.,]\d+)?)\s*%",norm(name))
    return float(m.group(1).replace(",","."))/100 if m else None

def infer_provider(name,code=""):
    v=f" {ascii_text(name)} "; c=norm(code).upper()
    if " msci " in v or c.startswith(("NDU","NCL","MX","M1")): return "MSCI"
    if " nasdaq " in v or c.startswith(("NYGB","NQ")): return "NASDAQ"
    if " stoxx " in v: return "STOXX"
    if " bloom" in v or "bloomberg" in v: return "BLOOMBERG"
    if " ftse " in v: return "FTSE RUSSELL"
    if " solactive " in v: return "SOLACTIVE"
    if " dow jones " in v or " s&p " in v: return "S&P DJI"
    if " lbma " in v or " gold fixing " in v: return "LBMA"
    return ""


CACHE_FILE = Path(__file__).with_name("benchmark_discovery_cache.json")

def load_benchmark_cache():
    try:
        if CACHE_FILE.exists():
            obj=json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            return obj if isinstance(obj,dict) else {}
    except Exception:
        pass
    return {}

def save_benchmark_cache(cache):
    try:
        CACHE_FILE.write_text(json.dumps(cache,ensure_ascii=False,indent=2),encoding="utf-8")
    except Exception:
        pass

def benchmark_cache_key(provider,vendor_code,name):
    return f"{norm(provider).upper()}|{norm(vendor_code).upper()}|{ascii_text(name)}"

def cache_get(provider,vendor_code,name):
    return load_benchmark_cache().get(benchmark_cache_key(provider,vendor_code,name))

def cache_put(provider,vendor_code,name,payload):
    cache=load_benchmark_cache()
    cache[benchmark_cache_key(provider,vendor_code,name)] = payload
    save_benchmark_cache(cache)

# Fast persistent caches: these are generic lookup/history caches, never
# instrument-specific benchmark mappings.
FAST_CACHE_JSON = Path(__file__).with_name("poc15_2_fast_cache.json")
FAST_HISTORY_CACHE = Path(__file__).with_name("poc15_2_history_cache.pkl")
FAST_CACHE_TTL_SEC = 24*3600

_FAST_CACHE = None
_LOOKUP_CACHE = {}
_DISCOVERY_CACHE = {}
_BORSA_CACHE = {}
_YAHOO_EVIDENCE_CACHE = {}

def _load_fast_cache():
    global _FAST_CACHE,_LOOKUP_CACHE,_DISCOVERY_CACHE,_BORSA_CACHE
    if _FAST_CACHE is not None:return
    obj={}
    try:
        if FAST_CACHE_JSON.exists():
            obj=json.loads(FAST_CACHE_JSON.read_text(encoding="utf-8"))
            if not isinstance(obj,dict):obj={}
    except Exception:
        obj={}
    _FAST_CACHE=obj
    _LOOKUP_CACHE.update(obj.get("lookup",{}) or {})
    _DISCOVERY_CACHE.update(obj.get("discovery",{}) or {})
    _BORSA_CACHE.update(obj.get("borsa",{}) or {})

def _save_fast_cache():
    try:
        FAST_CACHE_JSON.write_text(json.dumps({
            "lookup":_LOOKUP_CACHE,
            "discovery":_DISCOVERY_CACHE,
            "borsa":_BORSA_CACHE,
            "saved_at":time.time(),
        },ensure_ascii=False),encoding="utf-8")
    except Exception:
        pass

def _load_history_disk_cache():
    try:
        if FAST_HISTORY_CACHE.exists():
            obj=pickle.loads(FAST_HISTORY_CACHE.read_bytes())
            if isinstance(obj,dict):
                saved=float(obj.get("saved_at",0))
                data=obj.get("data",{})
                if time.time()-saved <= FAST_CACHE_TTL_SEC and isinstance(data,dict):
                    return data
    except Exception:
        pass
    return {}

def _save_history_disk_cache(cache):
    try:
        FAST_HISTORY_CACHE.write_bytes(pickle.dumps({"saved_at":time.time(),"data":cache}))
    except Exception:
        pass

# Session-level Yahoo/yfinance history cache.
_YF_HISTORY_CACHE = _load_history_disk_cache()

def yf_history_cached(symbols, period=None):
    symbols=list(dict.fromkeys(x for x in symbols if x))
    missing=[x for x in symbols if x not in _YF_HISTORY_CACHE]
    if missing:
        # One batch call for all missing symbols.
        kw=dict(tickers=missing,start=(date.today()-timedelta(days=FETCH_DAYS)).isoformat(),
                end=(date.today()+timedelta(days=1)).isoformat(),interval="1d",
                auto_adjust=True,actions=False,progress=False,threads=True,group_by="ticker")
        try:
            try: df=yf.download(timeout=YF_TIMEOUT,**kw)
            except TypeError: df=yf.download(**kw)
        except Exception:
            df=None
        for sym in missing:
            ser=None
            try:
                if isinstance(df,pd.DataFrame) and not df.empty:
                    if len(missing)==1 and not isinstance(df.columns,pd.MultiIndex):
                        ser=df["Close"] if "Close" in df else df.iloc[:,0]
                    elif isinstance(df.columns,pd.MultiIndex):
                        l0=set(map(str,df.columns.get_level_values(0))); l1=set(map(str,df.columns.get_level_values(1)))
                        if sym in l0:
                            block=df[sym]; ser=block["Close"] if "Close" in block else block.iloc[:,0]
                        elif sym in l1:
                            block=df.xs(sym,axis=1,level=1); ser=block["Close"] if "Close" in block else block.iloc[:,0]
            except Exception:
                ser=None
            _YF_HISTORY_CACHE[sym]=clean_series(ser) if ser is not None else None
        _save_history_disk_cache(_YF_HISTORY_CACHE)
    return {x:_YF_HISTORY_CACHE.get(x) for x in symbols}




def benchmark_quality_label(b):
    if b.level in ("EXACT_PROVIDER","EXACT_PROVIDER_DISCOVERED"):
        return "ESATTO"
    if b.level in ("EXACT_YAHOO_INDEX","EXACT_ALTERNATIVE_INDEX"):
        return "ESATTO/ALTERNATIVO"
    if b.level == "SYNTHETIC_SOVEREIGN_CURVE":
        return "SINTETICO SOVRANO"
    if b.level == "SYNTHETIC_BOND_CURVE":
        return "SINTETICO OBBLIG."
    if b.level == "SYNTHETIC_REFERENCE":
        return "RIF. SINTETICO"
    if b.level == "SINGLE_REFERENCE_INDEX":
        return "INDICE DI RIFERIMENTO"
    if b.level == "INDEX_CLASS_REFERENCE":
        return "INDICE DI CLASSE"
    if b.level == "MARKET_REFERENCE":
        return "RIF. DI MERCATO"
    if b.level == "IDENTITY_ONLY":
        return "IDENTITÀ NOTA / SERIE ASSENTE"
    return "NON RISOLTO"

# ---------------- network evidence ----------------

def borsa_etf(isin):
    _load_fast_cache()
    key=norm(isin).upper()
    if key in _BORSA_CACHE:
        cached=dict(_BORSA_CACHE[key])
        if norm(cached.get("instrument_name")):
            return cached
        # Old POC cache schema: refresh only this stale entry.
    detail="https://www.borsaitaliana.it/borsa/etf/dettaglio.html?"+urlencode({"isin":isin,"lang":"it"})
    raw=http_text(detail);text=strip_html(raw)
    title=""
    try:
        m=re.search(r"<title[^>]*>(.*?)</title>",raw,re.I|re.S)
        if m:
            title=strip_html(unescape(m.group(1)))
            title=re.sub(r"\s*-\s*Borsa Italiana.*$","",title,flags=re.I).strip()
    except Exception:pass
    pname=extract(r"(?:Denominazione|Nome)\s+(?!Indice Benchmark)(.{3,220}?)\s+(?:ISIN|Codice ISIN|Ticker|Simbolo)",text) or title
    out={
        "instrument_name":pname,
        "benchmark_name":extract(r"Benchmark:\s*(.{2,240}?)\s+Area Benchmark:",text),
        "benchmark_area":extract(r"Area Benchmark:\s*(.{2,140}?)\s+Emittente",text),
        "currency":extract(r"Valuta di Denominazione\s+([A-Z]{3})",text)
    }
    try:
        url=f"https://www.borsaitaliana.it/borsa/etf/indice-benchmark/{quote(isin)}-ETFP.html?lang=it"
        t=strip_html(http_text(url))
        full=extract(r"Denominazione Indice Benchmark\s+(.{2,260}?)\s+Reuters Ric",t)
        if full:out["benchmark_name"]=full
        out["benchmark_code"]=extract(r"Bloomberg Ticker\s+([A-Za-z0-9_.\-^]+)",t) or extract(r"Reuters Ric\s+([A-Za-z0-9_.\-^]+)",t)
    except Exception:
        out["benchmark_code"]=""
    _BORSA_CACHE[key]=out;_save_fast_cache()
    return dict(out)


def discover_yahoo_quote(isin,preferred_suffix=".MI"):
    _load_fast_cache()
    isin=norm(isin).upper()
    if not isin:return {"symbol":"","name":"","quote_type":""}
    key=f"META|{isin}|{preferred_suffix}"
    cached=_DISCOVERY_CACHE.get(key)
    if isinstance(cached,dict):return dict(cached)
    result={"symbol":"","name":"","quote_type":""}
    try:
        rows=[q for q in (getattr(yf.Search(isin,max_results=8),"quotes",None) or []) if isinstance(q,dict)]
        chosen=None
        for q in rows:
            sym=norm(q.get("symbol"))
            if sym and preferred_suffix and sym.upper().endswith(preferred_suffix):
                chosen=q;break
        if chosen is None:
            for q in rows:
                sym=norm(q.get("symbol"));qt=norm(q.get("quoteType")).upper()
                if sym and qt in ("ETF","MUTUALFUND","EQUITY"):
                    chosen=q;break
        if chosen is None and rows:chosen=rows[0]
        if chosen is not None:
            result={
                "symbol":norm(chosen.get("symbol")),
                "name":norm(chosen.get("longname") or chosen.get("shortname") or chosen.get("name")),
                "quote_type":norm(chosen.get("quoteType")).upper()
            }
    except Exception:
        pass
    _DISCOVERY_CACHE[key]=result;_save_fast_cache()
    return dict(result)

def discover_yahoo_quote_symbol(isin,preferred_suffix=".MI"):
    return norm(discover_yahoo_quote(isin,preferred_suffix).get("symbol"))


def yahoo_evidence(ticker,deep=False):
    cache_key=(ticker,bool(deep))
    if cache_key in _YAHOO_EVIDENCE_CACHE:
        out,ser=_YAHOO_EVIDENCE_CACHE[cache_key]
        return dict(out),ser

    out={}
    # History uses the session/disk batch cache.
    series=yf_history_cached([ticker]).get(ticker)

    if deep:
        t=yf.Ticker(ticker)
        try:
            fd=t.funds_data
            try: out["description"]=norm(fd.description)
            except Exception: pass
            try: out["category"]=norm(mapping(fd.fund_overview).get("categoryName"))
            except Exception: pass
            try: out["asset_classes"]=float_mapping(fd.asset_classes,True)
            except Exception: out["asset_classes"]={}
            try: out["sector_weightings"]=float_mapping(fd.sector_weightings,True)
            except Exception: out["sector_weightings"]={}
            try: out["bond_holdings"]=float_mapping(fd.bond_holdings,False)
            except Exception: out["bond_holdings"]={}
            try: out["bond_ratings"]=float_mapping(fd.bond_ratings,True)
            except Exception: out["bond_ratings"]={}
            try:
                th=fd.top_holdings
                if isinstance(th,pd.DataFrame) and not th.empty:
                    wc=next((c for c in th.columns if "percent" in str(c).casefold() or "weight" in str(c).casefold()),None)
                    if wc is not None:
                        vals=pd.to_numeric(th[wc],errors="coerce").dropna().map(pct)
                        out["top10"]=float(vals.head(10).sum())
            except Exception: pass
        except Exception as exc:
            out["funds_error"]=f"{type(exc).__name__}: {exc}"
        try:
            fi=t.fast_info
            out["currency"]=norm(getattr(fi,"currency","")).upper()
        except Exception:
            pass

    # Keep name from catalog/Borsa rather than doing the slow .info request.
    out.setdefault("name",ticker)
    _YAHOO_EVIDENCE_CACHE[cache_key]=(dict(out),series)
    return out,series

def needs_deep_yahoo(e,p):
    # Deep metadata only for genuinely ambiguous profiles.
    if p.confidence < .80:return True
    if p.asset=="multiasset" and not e.asset_classes:return True
    if p.asset=="bond" and not p.issuer_type:return True
    return False

def enrich_yahoo_deep(e):
    sym=e.yahoo_symbol or e.ticker
    if not sym:return
    try:
        y,_=yahoo_evidence(sym,deep=True)
    except Exception:
        return
    e.description=e.description or norm(y.get("description"))
    e.category=e.category or norm(y.get("category"))
    e.currency=e.currency or norm(y.get("currency"))
    if not e.asset_classes:e.asset_classes=float_mapping(y.get("asset_classes"),True)
    if not e.sector_weightings:e.sector_weightings=float_mapping(y.get("sector_weightings"),True)
    if not e.bond_holdings:e.bond_holdings=float_mapping(y.get("bond_holdings"),False)
    if not e.bond_ratings:e.bond_ratings=float_mapping(y.get("bond_ratings"),True)
    if e.top10_concentration is None:e.top10_concentration=y.get("top10")


def _richer_text(a,b):
    """Keep the text with the richer token set."""
    a=norm(a); b=norm(b)
    if not a:return b
    if not b:return a
    return a if len(set(tokens(a)))>=len(set(tokens(b))) else b

def collect(inst,cb=None):
    e=Evidence(ticker=norm(inst.get("ticker")).upper(),isin=norm(inst.get("isin")).upper(),
               yahoo_symbol=norm(inst.get("yahoo_symbol")),
               history_key=norm(inst.get("history_key")),
               instrument_type=norm(inst.get("type")).upper(),name=norm(inst.get("name_hint")),
               country=norm(inst.get("country")).upper(),maturity_date=norm(inst.get("maturity_date")))
    input_name=e.name
    e.maturity_years=maturity_years(e.maturity_date)
    e.coupon_rate=parse_coupon(e.name)

    # Portfolio history/metadata are authoritative evidence when present.
    merge_portfolio_metadata(e)
    input_name=e.name
    s=clean_series(portfolio_history_series(e.ticker,e.isin,e.history_key))
    if s is not None:
        e.volatility_1y=annual_vol(s)
        if "Portfolio JSON" not in e.sources:e.sources.append("Portfolio JSON")

    # Internal BTP aliases are NEVER Yahoo tickers when portfolio history exists.
    skip_yahoo=(e.instrument_type=="BTP" and s is not None)

    # For exchange-traded funds/products use ISIN-first discovery.
    # This avoids noisy 404s caused by a stale/wrong venue ticker.
    yahoo_query=""
    if not skip_yahoo:
        if e.instrument_type in ("ETF","ETC","ETP") and e.isin:
            discovered=discover_yahoo_quote(e.isin)
            recovered=norm(discovered.get("symbol"))
            dname=norm(discovered.get("name"))
            if dname:e.name=_richer_text(e.name,dname)
            if recovered:
                yahoo_query=recovered;e.yahoo_symbol=recovered
                log(cb,f"{e.ticker or e.isin}: Yahoo ISIN-first [{recovered}]")
        if not yahoo_query:
            yahoo_query=e.yahoo_symbol or e.ticker

    if yahoo_query and not skip_yahoo:
        try:
            y,ys=yahoo_evidence(yahoo_query)
            ys=clean_series(ys)
            if ys is not None:
                s=ys if s is None or len(ys)>=len(s) else s
            e.sources.append(f"Yahoo/yfinance [{yahoo_query}]")
            e.name=_richer_text(e.name,norm(y.get("name")))
            ydesc=norm(y.get("description"))
            if ydesc and ydesc.casefold() not in (e.description or "").casefold():
                e.description=(e.description+" | " if e.description else "")+ydesc
            ycat=norm(y.get("category"))
            if ycat and ycat.casefold() not in (e.category or "").casefold():
                e.category=(e.category+" | " if e.category else "")+ycat
            e.currency=norm(y.get("currency")) or e.currency
            e.asset_classes=float_mapping(y.get("asset_classes"),True)
            e.sector_weightings=float_mapping(y.get("sector_weightings"),True)
            e.bond_holdings=float_mapping(y.get("bond_holdings"),False)
            e.bond_ratings=float_mapping(y.get("bond_ratings"),True)
            e.top10_concentration=y.get("top10")
            e.volatility_1y=annual_vol(s)
            if y.get("funds_error"): e.errors.append("Yahoo FundsData: "+y["funds_error"])
        except Exception as exc:
            e.errors.append(f"Yahoo: {type(exc).__name__}: {exc}")

    # If ISIN-first returned no usable history, try one generic alternate quote search.
    if not skip_yahoo and s is None and e.isin:
        alt_discovery=discover_yahoo_quote(e.isin,preferred_suffix="")
        recovered=norm(alt_discovery.get("symbol"))
        if norm(alt_discovery.get("name")):
            e.name=_richer_text(e.name,norm(alt_discovery.get("name")))
        if recovered and recovered != yahoo_query:
            log(cb,f"{e.ticker or e.isin}: Yahoo alternate [{recovered}]")
            try:
                y,ys=yahoo_evidence(recovered)
                ys=clean_series(ys)
                if ys is not None:
                    s=ys;e.yahoo_symbol=recovered
                    e.sources.append(f"Yahoo/yfinance alternate [{recovered}]")
                    e.name=_richer_text(input_name,norm(y.get("name")))
                    e.description=e.description or norm(y.get("description"))
                    e.category=e.category or norm(y.get("category"))
                    e.currency=e.currency or norm(y.get("currency"))
                    if not e.asset_classes:e.asset_classes=float_mapping(y.get("asset_classes"),True)
                    if not e.sector_weightings:e.sector_weightings=float_mapping(y.get("sector_weightings"),True)
                    if not e.bond_holdings:e.bond_holdings=float_mapping(y.get("bond_holdings"),False)
                    if not e.bond_ratings:e.bond_ratings=float_mapping(y.get("bond_ratings"),True)
                    if e.top10_concentration is None:e.top10_concentration=y.get("top10")
                    e.volatility_1y=annual_vol(s)
            except Exception as exc:
                e.errors.append(f"Yahoo alternate: {type(exc).__name__}: {exc}")

    # Preserve richer source description.
    e.name=_richer_text(input_name,e.name)
    merge_portfolio_metadata(e)

    # Borsa is now lazy. Rich catalog names are enough for the first pass.
    # We call Borsa immediately only when the text is genuinely poor.
    if e.isin and e.instrument_type in ("ETF","ETC","ETP") and len(tokens(e.name))<4:
        log(cb,f"{e.ticker or e.isin}: Borsa (lazy)")
        try:
            b=borsa_etf(e.isin); e.sources.append("Borsa Italiana")
            bname=norm(b.get("instrument_name"))
            if bname:e.name=_richer_text(e.name,bname)
            e.benchmark_name=norm(b.get("benchmark_name")); e.benchmark_code=norm(b.get("benchmark_code"))
            e.benchmark_area=norm(b.get("benchmark_area")); e.currency=e.currency or norm(b.get("currency"))
        except Exception as exc:
            e.errors.append(f"Borsa: {type(exc).__name__}: {exc}")

    if e.instrument_type=="BTP":
        e.country=e.country or ("IT" if e.isin.startswith("IT") else "")
        e.currency=e.currency or "EUR"
        e.coupon_rate=e.coupon_rate or parse_coupon(e.name)

    return e,clean_series(s)



# ---------------- ontology / role ----------------

def mix(e):
    eq=bond=cash=other=0.0
    for k,v in e.asset_classes.items():
        kk=ascii_text(k)
        if "stock" in kk or "equity" in kk: eq+=pct(v)
        elif "bond" in kk: bond+=pct(v)
        elif "cash" in kk: cash+=pct(v)
        else: other+=pct(v)
    return eq,bond,cash,other

def yahoo_duration(e):
    for k,v in e.bond_holdings.items():
        if "duration" in ascii_text(k):
            try:
                x=float(v)
                if 0<x<100: return x
            except Exception: pass
    return None

def infer_target_maturity_years_from_text(e):
    text=ascii_text(" ".join(x for x in (e.name,e.description,e.benchmark_name) if x))
    years=[int(y) for y in re.findall(r"\b(20[2-4][0-9])\b",text)]
    if not years:return None
    now_year=pd.Timestamp.today().year
    future=[y for y in years if y>=now_year-1]
    if not future:return None
    y=min(future)
    return max(.05,y-now_year+.5)

COUNTRY_ALIASES={
    "italy":(" italy "," italian "," ftse mib "),
    "usa":(" usa "," united states "," u.s. "," s&p 500 "," russell 2000 "),
    "japan":(" japan "," japanese "," nikkei "," topix "),
    "china":(" china "," chinese "," hang seng "," csi "),
    "korea":(" korea "," korean "),
    "india":(" india "," indian "," nifty "," sensex "),
    "brazil":(" brazil "," brazilian "," bovespa "),
    "uk":(" united kingdom "," uk "," britain "," british "," ftse 100 "),
    "switzerland":(" switzerland "," swiss "," smi "),
    "australia":(" australia "," australian "," asx "),
    "canada":(" canada "," canadian "," tsx "),
    "taiwan":(" taiwan "," taiwanese "),
    "germany":(" germany "," german "," dax "),
    "france":(" france "," french "," cac 40 "),
    "spain":(" spain "," spanish "," ibex "),
}
THEME_PATTERNS=(
    ("clean_energy",(" clean energy "," renewable energy "," solar "," wind "," hydrogen ")),
    ("water",(" global water "," water index "," water ucits ")),
    ("robotics",(" robotics "," automation "," robo global ")),
    ("artificial_intelligence",(" artificial intelligence "," ai & big data "," ai and big data ")),
    ("cybersecurity",(" cyber security "," cybersecurity "," digital security ")),
    ("digitalisation",(" digitalisation "," digitalization ")),
    ("battery",(" battery "," batteries ")),
    ("gaming_esports",(" gaming "," esports "," e-sports ")),
    ("agribusiness",(" agribusiness "," agriculture ")),
    ("ageing",(" ageing "," aging population ")),
    ("electric_mobility",(" electric vehicle "," electric vehicles "," mobility ")),
    ("infrastructure",(" infrastructure ",)),
)

def _detect_geography(v):
    # An explicit country/index identity is stronger than a broad benchmark-area
    # label such as "Europe".
    for geo,aliases in COUNTRY_ALIASES.items():
        if any(x in v for x in aliases):
            return geo,"country"

    if (" emerging " in v
        or re.search(r"\bmsci\s+em(?:\s|$)",v)
        or " em imi " in v
        or " emerging markets " in v):
        return "emerging","regional"

    if any(x in v for x in (" world "," global "," all-world "," all world "," acwi ")):
        return "world","global"
    if any(x in v for x in (" europe "," eurozone "," euro area "," stoxx europe "," euro stoxx ")):
        return "europe","regional"
    return "",""


def _infer_market_breadth(v,p):
    if p.breadth=="thematic":return .15
    if p.breadth=="sector":return .25
    if any(x in v for x in (" all-world "," all world "," acwi "," all cap "," imi "," total market ")):return .98
    if " world " in v or " global " in v:return .94
    if any(x in v for x in (" stoxx europe 600 "," s&p 500 "," russell 2000 ")):return .86
    if any(x in v for x in (" europe 600 "," developed europe ")):return .84
    if " ftse mib " in v or " mib index " in v:return .34
    if p.geo_scope=="country" and (" msci " in v or " ftse " in v):return .70
    if any(x in v for x in (" 50 "," 40 "," 100 ")):return .55
    if p.geo_scope=="regional":return .76
    if p.geo_scope=="country":return .62
    return .72

def profile(e):
    p=Profile()
    text=" | ".join(x for x in (e.name,e.description,e.category,e.benchmark_name,e.benchmark_area,e.instrument_type) if x)
    v=f" {ascii_text(text)} ";eq,bond,cash,other=mix(e)
    multi_text=any(x in v for x in (" multi-asset "," multi asset "," balanced "," bilanciati "," bilanciato "," flexible "," flessibile "," allocation "," passive underlyings "))
    strong_bond=any(x in v for x in (
        " government bond "," govt bond "," sovereign bond "," treasury bond ",
        " corporate bond "," aggregate bond "," aggr bond "," fixed income ",
        " obbligazionario "," ibonds "," inflation linked "," inflation-linked ",
        " inf-link "," high yield "," emerging markets debt "
    ))
    strong_gold=any(x in v for x in (" physical gold "," gold etc "," gold etp "," gold bullion "," gold spot "))
    strong_crypto=any(x in v for x in (" bitcoin "," crypto "," cryptocurrency "," digital asset "," btc "))
    theme_hint=any(any(x in v for x in patterns) for _,patterns in THEME_PATTERNS)
    strong_equity=theme_hint or any(x in v for x in (" msci "," ftse "," stoxx "," s&p "," nasdaq "," dow jones "," russell "," equity "," azionario "))
    strong_commodity=any(x in v for x in (" commodity "," commodities "," comdty "))

    if eq>=.15 and bond>=.10:
        p.asset="multiasset";ac=.98;p.reasons.append(f"Multi-asset allocation: equity {eq:.0%}, bond {bond:.0%}, cash {cash:.0%}.")
    elif multi_text and e.instrument_type in ("FUND","MUTUALFUND",""):
        p.asset="multiasset";ac=.92;p.reasons.append("Multi-asset/flexible category has precedence over product-name equity words.")
    elif strong_gold:p.asset="commodity";p.gold=True;ac=.99
    elif strong_crypto:p.asset="digital_asset";p.digital_asset=True;ac=.99
    elif cash>=.50 or " overnight " in v or " estr " in v or " money market " in v:p.asset="cash";ac=.97
    elif e.instrument_type=="BTP":p.asset="bond";ac=.99
    elif bond>=.75 or strong_bond:p.asset="bond";ac=.97
    elif strong_commodity:p.asset="commodity";ac=.95
    elif eq>=.75 or strong_equity:p.asset="equity";ac=.99 if eq>=.75 else .95
    else:ac=.55

    p.geography,p.geo_scope=_detect_geography(v)

    for theme,patterns in THEME_PATTERNS:
        if any(x in v for x in patterns):p.theme=theme;p.breadth="thematic";break

    factors=[
        ("minimum_volatility",(" minimum volatility "," min volatility "," low volatility ")),
        ("low_beta",(" low beta ",)),
        ("quality",(" quality factor "," sector neutral quality "," quality index ")),
        ("value",(" value factor "," enhanced value ")),
        ("momentum",(" momentum ",)),("dividend",(" dividend ",)),
        ("multifactor",(" multifactor "," multi factor ")),
        ("quality",(" wide moat "," moat index "))
    ]
    for f,ps in factors:
        if any(x in v for x in ps):
            p.factor=f
            if not p.breadth:p.breadth="broad"
            break

    sizes=[("ex_mega",(" ex mega cap "," ex-mega cap ")),("small",(" small cap "," small-cap "," smallcap ")),("mid",(" mid cap "," mid-cap ")),("large",(" large cap "," large-cap "))]
    for sz,ps in sizes:
        if any(x in v for x in ps):p.size=sz;break

    sectors=[
        ("technology",(" information technology "," technology "," technology sector ")),
        ("healthcare",(" health care "," healthcare ")),
        ("energy",(" oil & gas "," oil and gas "," energy "," energy sector ")),
        ("real_estate",(" real estate "," reit "," property sector ")),
        ("financials",(" financials "," financial sector ")),
        ("industrials",(" industrials "," industrial sector ")),
        ("utilities",(" utilities "," utility sector ")),
        ("consumer_staples",(" consumer staples ",)),
        ("consumer_discretionary",(" consumer discretionary ",)),
        ("communication_services",(" communication services ",)),
        ("metals_mining",(" metals and mining "," metals & mining "," metals an "," metals mining ")),
        ("semiconductor",(" semiconductor sector "," semiconductors index "))
    ]
    if not p.theme:
        for sec,ps in sectors:
            if any(x in v for x in ps):
                p.sector=sec
                if " sector neutral " not in v:p.breadth="sector"
                break

    if p.asset=="equity" and not p.breadth:p.breadth="broad"
    p.market_breadth=_infer_market_breadth(v,p) if p.asset=="equity" else 0.0

    if p.asset=="bond":
        if e.instrument_type=="BTP" or any(x in v for x in (" government "," govt "," treasury "," sovereign ")):p.issuer_type="government"
        elif any(x in v for x in (" aggregate "," aggr ")):p.issuer_type="aggregate"
        elif " corporate " in v:p.issuer_type="corporate"
        if any(x in v for x in (" inflation-linked "," inflation linked "," inf-link ")):p.bond_style="inflation_linked"
        elif " floating " in v:p.bond_style="floating"
        else:p.bond_style="nominal_fixed"
        d=yahoo_duration(e)
        if d is not None:p.duration_years=d;p.duration_confidence=.96
        elif re.search(r"(?<!\d)0\s*[-–]\s*1(?:y|yr|yrs|year|years)?(?!\d)",v) or " 0 to 1 " in v:
            p.duration_years=.55;p.duration_confidence=.90
        elif re.search(r"(?<!\d)1\s*[-–]\s*3(?:y|yr|yrs|year|years)?(?!\d)",v) or " 1 to 3 " in v:
            p.duration_years=2.0;p.duration_confidence=.90
        elif re.search(r"(?<!\d)3\s*[-–]\s*5(?:y|yr|yrs|year|years)?(?!\d)",v) or " 3 to 5 " in v:
            p.duration_years=4.0;p.duration_confidence=.88
        elif re.search(r"(?<!\d)5\s*[-–]\s*7(?:y|yr|yrs|year|years)?(?!\d)",v) or " 5 to 7 " in v:
            p.duration_years=6.0;p.duration_confidence=.86
        elif e.maturity_years is not None and p.issuer_type=="government":p.duration_years=max(.15,e.maturity_years*.88);p.duration_confidence=.72
        else:
            tm=infer_target_maturity_years_from_text(e)
            if tm is not None and p.issuer_type=="government":p.duration_years=max(.15,tm*.82);p.duration_confidence=.80
        if " hedged " in v or " currency neutral " in v:p.hedged=True
        elif e.currency:p.hedged=False

    if " 2x " in v or " leveraged " in v:p.leveraged=True
    if " inverse " in v or " short daily " in v:p.inverse=True

    fields=[p.asset,p.geography,p.breadth,p.sector or p.theme,p.factor,p.size,p.issuer_type,p.bond_style]
    p.completeness=sum(bool(x) for x in fields)/max(1,len(fields))
    bonus=.04*bool(p.geography)+.04*bool(p.breadth)+.04*bool(p.sector or p.theme)+.03*bool(p.factor or p.size)
    p.confidence=min(.99,ac+bonus)
    if not p.asset:p.unrepresented.append("asset class")
    if p.asset=="equity" and not p.geography:p.unrepresented.append("geography")
    return p


def structural_type(p):
    if p.digital_asset:return "DIGITAL_ASSET"
    if p.gold:return "GOLD"
    if p.asset=="commodity":return "COMMODITY"
    if p.asset=="cash":return "MONEY_MARKET"
    if p.asset=="multiasset":return "MULTI_ASSET"
    if p.asset=="bond":
        if p.bond_style=="inflation_linked":return "INFLATION_LINKED_BOND"
        if p.issuer_type=="government" and p.duration_years is not None and p.duration_years<=1.25:return "ULTRA_SHORT_GOV_BOND"
        if p.issuer_type=="government" and p.duration_years is not None and p.duration_years<=3:return "SHORT_GOV_BOND"
        if p.issuer_type=="government":return "GOV_BOND"
        if p.issuer_type=="aggregate":return "AGGREGATE_BOND"
        return "BOND"
    if p.asset=="equity":
        if p.breadth=="thematic" or p.theme:return "THEMATIC_EQUITY"
        if p.breadth=="sector" or p.sector:return "SECTOR_"+(p.sector.upper() if p.sector else "EQUITY")
        if p.factor:return "FACTOR_"+p.factor.upper()
        if p.size=="small":return "SMALL_CAP_EQUITY"
        if p.size=="ex_mega":return "EX_MEGA_CAP_EQUITY"
        if p.geography=="emerging":return "EMERGING_BROAD_EQUITY"
        if p.geo_scope=="country":return "SINGLE_COUNTRY_EQUITY" if p.market_breadth<.45 else "COUNTRY_BROAD_EQUITY"
        return "BROAD_EQUITY"
    return "UNKNOWN"



# -------------------------------------------------------------------
# ROLE ENGINE 2.0: PARENT EXPOSURE + OVERLAYS
# -------------------------------------------------------------------

def _clip01(x):
    try:return max(0.0,min(1.0,float(x)))
    except Exception:return 0.0

def exposure_fingerprint(e,p):
    """
    Local/CPU-only economic fingerprint.
    It uses already available evidence and profile; no network calls.
    """
    f=ExposureFingerprint()
    eq,bd,ca,ot=mix(e)
    txt=f" {ascii_text(' '.join(x for x in (e.name,e.description,e.category,e.benchmark_name,e.benchmark_area) if x))} "

    # Evidence confidence: textual economic identity + provider metadata.
    strong_words=sum(bool(x) for x in (
        p.asset,p.geography,p.breadth,p.sector,p.factor,p.size,p.issuer_type,p.bond_style
    ))
    f.evidence_confidence=_clip01(.50*p.confidence + .04*strong_words + .08*bool(e.asset_classes) + .06*bool(e.benchmark_name))

    # Broadness / representativeness / diversification.
    if p.asset=="equity":
        f.breadth=.92 if p.breadth=="broad" else (.45 if p.breadth=="sector" else (.25 if p.breadth=="thematic" else .55))
        f.representativeness=.92 if p.breadth=="broad" and p.geography in ("world","usa","europe") else .55
        f.diversification=.85 if p.breadth=="broad" else (.50 if p.breadth=="sector" else .30)
    elif p.asset=="bond":
        f.breadth=.80 if p.issuer_type in ("government","aggregate") else .62
        f.representativeness=.80 if p.issuer_type=="aggregate" else .62
        f.diversification=.82 if p.issuer_type=="aggregate" else .62
    elif p.asset=="multiasset":
        f.breadth=.80; f.representativeness=.72; f.diversification=.88
    elif p.asset=="cash":
        f.breadth=.55;f.representativeness=.75;f.diversification=.60
    elif p.gold:
        f.breadth=.10;f.representativeness=.15;f.diversification=.15
    elif p.asset=="commodity":
        f.breadth=.35;f.representativeness=.30;f.diversification=.35
    elif p.digital_asset:
        f.breadth=.05;f.representativeness=.05;f.diversification=.05

    # Concentration from structure + holdings.
    if p.breadth=="thematic":
        f.specialization=.98;f.concentration=.88
    elif p.breadth=="sector":
        f.specialization=.88;f.sector_concentration=.92;f.concentration=.78
    elif p.breadth=="single_country":
        f.specialization=.55;f.geo_concentration=.90;f.concentration=.70
    elif p.breadth=="broad":
        f.specialization=.12

    if p.geography in ("italy","japan","korea","china"):
        f.geo_concentration=max(f.geo_concentration,.82)
        f.specialization=max(f.specialization,.45)
    elif p.geography in ("usa","europe"):
        f.geo_concentration=max(f.geo_concentration,.35)
    elif p.geography=="emerging":
        f.geo_concentration=max(f.geo_concentration,.30)
        f.specialization=max(f.specialization,.28)

    if p.factor:
        f.factor_tilt=.72 if p.factor in ("minimum_volatility","low_beta","quality","value","momentum","dividend") else .60
        f.specialization=max(f.specialization,.48)
    if p.size=="small":
        f.size_tilt=.82;f.specialization=max(f.specialization,.58)
    elif p.size=="ex_mega":
        f.size_tilt=.60;f.specialization=max(f.specialization,.42)

    if e.top10_concentration is not None:
        c=float(e.top10_concentration)
        f.concentration=max(f.concentration,_clip01((c-.15)/.60))
        f.diversification=max(0.0,f.diversification-.35*_clip01((c-.35)/.45))

    # Defensive dimensions.
    if p.asset=="cash":
        f.capital_stability=.99;f.liquidity=.98;f.sovereign_quality=.90
    elif p.asset=="bond":
        D=float(p.duration_years or 5.0)
        f.rate_risk=_clip01(D/10.0)
        if p.issuer_type=="government":
            f.sovereign_quality=.90
            f.credit_risk=.08
            f.capital_stability=_clip01(.92-.045*max(0,D-1))
        elif p.issuer_type=="aggregate":
            f.sovereign_quality=.55;f.credit_risk=.28;f.capital_stability=.72
        elif p.issuer_type=="corporate":
            f.credit_risk=.48;f.capital_stability=.58
        else:
            f.credit_risk=.35;f.capital_stability=.64
        if any(x in txt for x in (" emerging "," high yield "," em debt "," credit opportunities ")):
            f.credit_risk=max(f.credit_risk,.78)
            f.specialization=max(f.specialization,.62)
            f.capital_stability*=.78
        if p.bond_style=="inflation_linked":
            f.inflation_risk=.48;f.specialization=max(f.specialization,.38)
            f.capital_stability=max(f.capital_stability,.70)
        f.liquidity=.75
    elif p.gold:
        f.capital_stability=.52;f.liquidity=.88
    elif p.asset=="commodity":
        f.capital_stability=.18;f.liquidity=.78
    elif p.digital_asset:
        f.capital_stability=.03;f.liquidity=.72
    elif p.asset=="equity":
        f.capital_stability=.22 if p.factor not in ("minimum_volatility","low_beta") else .42
        f.liquidity=.80

    if p.hedged is True:
        f.currency_risk=.08
    elif p.hedged is False and p.geography=="world":
        f.currency_risk=.42
    else:
        f.currency_risk=.18

    # Alternative/special domains.
    if p.gold:
        f.commodity_exposure=1.0;f.specialization=max(f.specialization,.82);f.concentration=max(f.concentration,.85)
    elif p.asset=="commodity":
        f.commodity_exposure=.90;f.specialization=max(f.specialization,.75)
    if p.digital_asset:
        f.digital_exposure=1.0;f.specialization=1.0;f.concentration=1.0
    if p.leveraged:
        f.leverage_risk=1.0;f.specialization=1.0
    if p.inverse:
        f.inverse_risk=1.0;f.specialization=1.0

    if p.asset=="multiasset":
        tot=max(1e-9,eq+bd+ca+ot)
        eq,bd,ca,ot=eq/tot,bd/tot,ca/tot,ot/tot
        # balance peaks near a genuinely mixed portfolio
        f.multiasset_balance=_clip01(1.0-abs(eq-bd))
        f.capital_stability=_clip01(.18*eq+.74*bd+.98*ca+.25*ot)
        f.specialization=max(f.specialization,.25*ot)

    f.reasons.append(
        f"Fingerprint: breadth={f.breadth:.2f}, diversification={f.diversification:.2f}, "
        f"specialization={f.specialization:.2f}, stability={f.capital_stability:.2f}."
    )
    return f


def _role_utilities(e,p,f):
    """
    Monotonic utilities: each feature has a stable economic direction.
    """
    core=(
        5.2*f.representativeness +
        4.5*f.breadth +
        4.2*f.diversification +
        1.8*f.multiasset_balance
        - 3.5*f.specialization
        - 2.8*f.concentration
        - 2.2*f.geo_concentration
        - 2.3*f.sector_concentration
        - 1.5*f.factor_tilt
        - 1.6*f.size_tilt
        - 4.0*f.commodity_exposure
        - 6.0*f.digital_exposure
        - 5.0*f.leverage_risk
        - 5.0*f.inverse_risk
    )

    defensive=(
        7.0*f.capital_stability +
        2.4*f.liquidity +
        2.5*f.sovereign_quality
        - 3.0*f.rate_risk
        - 3.8*f.credit_risk
        - 2.0*f.currency_risk
        - 2.3*f.commodity_exposure
        - 6.0*f.digital_exposure
        - 4.5*f.leverage_risk
        - 4.5*f.inverse_risk
        + 1.0*f.inflation_risk
    )

    satellite=(
        5.2*f.specialization +
        3.4*f.concentration +
        2.7*f.geo_concentration +
        3.2*f.sector_concentration +
        2.5*f.factor_tilt +
        2.8*f.size_tilt +
        3.0*f.credit_risk +
        2.0*f.currency_risk +
        5.5*f.commodity_exposure +
        8.0*f.digital_exposure +
        7.0*f.leverage_risk +
        7.0*f.inverse_risk
        + 1.7*f.inflation_risk
    )

    # Asset-parent floors are utilities, not final percentages.
    if p.asset=="equity":
        core+=3.0
        satellite+=1.0
    elif p.asset=="bond":
        defensive+=4.5
        core+=1.0
    elif p.asset=="cash":
        defensive+=8.0
    elif p.asset=="multiasset":
        core+=2.0;defensive+=2.0
    elif p.gold:
        defensive+=5.2;satellite+=2.6
    elif p.asset=="commodity":
        satellite+=5.0
    elif p.digital_asset:
        satellite+=9.0

    return {
        "core":max(.05,core),
        "defensive":max(.05,defensive),
        "satellite":max(.05,satellite),
    }


def _normalise_roles(scores):
    tot=sum(max(0.0,float(v)) for v in scores.values()) or 1.0
    return {k:100.0*max(0.0,float(v))/tot for k,v in scores.items()}


def _project_constraints(raw,e,p,f):
    """
    Economic consistency projection conditioned FIRST by asset class.
    Equity concentration rules can never leak into bonds/cash/gold/etc.
    """
    flags=[]

    def renorm():
        for k in raw: raw[k]=max(0.0,float(raw[k]))
        tot=sum(raw.values()) or 1.0
        for k in raw: raw[k]=100.0*raw[k]/tot

    def cap(role,maxv):
        renorm()
        if raw[role] <= maxv:return
        excess=raw[role]-maxv
        raw[role]=maxv
        others=[k for k in raw if k!=role]
        sw=sum(max(raw[k],1e-9) for k in others)
        for k in others:
            raw[k]+=excess*max(raw[k],1e-9)/sw
        renorm()

    def floor(role,minv):
        renorm()
        if raw[role] >= minv:return
        need=minv-raw[role]
        others=[k for k in raw if k!=role]
        avail=sum(raw[k] for k in others)
        if avail<=1e-9:return
        for k in others:
            raw[k]-=need*raw[k]/avail
        raw[role]=minv
        renorm()

    # DIGITAL / LEVERAGE / INVERSE
    if p.digital_asset or f.digital_exposure>=.90:
        floor("satellite",97);cap("core",2);cap("defensive",2)
        flags.append("INV: digital asset -> Satellite dominant")
        return raw,flags

    if f.leverage_risk>.5 or f.inverse_risk>.5:
        floor("satellite",97);cap("core",2);cap("defensive",2)
        flags.append("INV: leveraged/inverse -> Satellite dominant")
        return raw,flags

    # GOLD / COMMODITY
    if p.gold:
        cap("core",3)
        floor("defensive",68)
        floor("satellite",28)
        cap("satellite",32)
        flags.append("INV: physical gold -> Defensive/Satellite")
        return raw,flags

    if p.asset=="commodity":
        floor("satellite",88);cap("core",5);cap("defensive",10)
        flags.append("INV: commodity -> Satellite dominant")
        return raw,flags

    # CASH
    if p.asset=="cash":
        floor("defensive",97);cap("core",3);cap("satellite",2)
        flags.append("INV: cash -> Defensive")
        return raw,flags

    # BONDS — no equity concentration invariant is allowed here.
    if p.asset=="bond":
        txt=ascii_text(" ".join(x for x in (e.name,e.description,e.benchmark_name) if x))
        D=float(p.duration_years or 5.0)

        if p.issuer_type=="government" and D<=1.25:
            floor("defensive",94);cap("core",6);cap("satellite",2)
            flags.append("INV: ultra-short sovereign -> Defensive")
            return raw,flags

        if p.issuer_type=="government" and any(x in txt for x in ("ibonds","target maturity","maturity")) and D<=2.0:
            floor("defensive",90);cap("core",10);cap("satellite",3)
            flags.append("INV: target-maturity sovereign -> Defensive")
            return raw,flags

        if p.issuer_type=="government":
            floor("defensive",70);floor("core",20);cap("satellite",8)
            flags.append("INV: government bond -> Core+Defensive")

        if p.bond_style=="inflation_linked":
            floor("defensive",66);floor("core",14);cap("satellite",18)
            flags.append("INV: inflation-linked -> Defensive dominant")

        if p.issuer_type=="corporate" and not any(x in txt for x in ("emerging","high yield","em debt","credit opportunities")):
            floor("defensive",58);floor("core",30);cap("satellite",12)
            flags.append("INV: corporate bond -> Core+Defensive")

        if any(x in txt for x in ("emerging","high yield","em debt","credit opportunities")):
            floor("defensive",40);floor("satellite",30);cap("core",25)
            flags.append("INV: EM/high-yield debt -> Defensive+Satellite")

        renorm()
        return raw,flags

    # MULTI-ASSET
    if p.asset=="multiasset":
        cap("satellite",45)
        flags.append("INV: multi-asset -> structural mix preserved")
        renorm()
        return raw,flags

    # EQUITIES ONLY
    if p.asset=="equity":
        if p.breadth=="thematic":
            floor("satellite",82);cap("defensive",8);cap("core",18)
            flags.append("INV: thematic equity -> Satellite dominant")
            renorm();return raw,flags

        if p.breadth=="sector" or p.sector:
            floor("satellite",70);floor("core",22);cap("defensive",6)
            flags.append("INV: sector equity -> Core+Satellite")
            renorm();return raw,flags

        if p.factor in ("minimum_volatility","low_beta"):
            floor("core",64);floor("defensive",26);cap("satellite",8)
            flags.append("INV: min-vol/low-beta -> Core+Defensive")
            renorm();return raw,flags

        if p.factor=="quality":
            floor("core",68);floor("satellite",24);cap("defensive",6)
            flags.append("INV: quality -> Core+Satellite")
            renorm();return raw,flags

        if p.size=="small":
            floor("core",52);floor("satellite",40);cap("defensive",6)
            flags.append("INV: small-cap -> Core+Satellite")
            renorm();return raw,flags

        if p.size=="ex_mega":
            floor("core",58);floor("satellite",34);cap("defensive",6)
            flags.append("INV: ex-mega -> Core+Satellite")
            renorm();return raw,flags

        # Geographic concentration applies only to equity.
        if p.breadth=="single_country" or f.geo_concentration>=.80:
            floor("satellite",68);floor("core",20);cap("defensive",6)
            flags.append("INV: single-country equity -> Core+Satellite")
            renorm();return raw,flags

        if p.geography=="emerging" and p.breadth=="broad":
            floor("core",65);floor("satellite",27);cap("defensive",6)
            flags.append("INV: broad EM equity -> Core+Satellite")
            renorm();return raw,flags

        if p.breadth=="broad" and p.geography=="world" and not p.factor and not p.size:
            floor("core",88);cap("defensive",7);cap("satellite",10)
            flags.append("INV: broad world equity -> Core")
            renorm();return raw,flags

        if p.breadth=="broad" and p.geography in ("usa","europe"):
            floor("core",72);floor("satellite",18);cap("defensive",8)
            flags.append("INV: broad regional equity -> Core+Satellite")
            renorm();return raw,flags

    renorm()
    return raw,flags


def _structural_role_policy(e,p,f):
    """
    Roles that are structurally meaningful must survive a 20% cutoff when
    they sit just below it because of normalization. This is family logic,
    never instrument hardcoding.
    """
    protected=set()
    min_keep_ratio=.65  # protected roles survive from 13% when threshold=20

    if p.digital_asset or f.digital_exposure>=.90:
        protected={"satellite"}
    elif p.gold:
        protected={"defensive","satellite"}
    elif p.asset=="cash":
        protected={"defensive"}
    elif p.asset=="commodity":
        protected={"satellite"}
    elif p.asset=="bond":
        txt=ascii_text(" ".join(x for x in (e.name,e.description,e.benchmark_name) if x))
        D=float(p.duration_years or 5.0)
        if p.issuer_type=="government" and D<=1.25:
            protected={"defensive"}
        elif any(x in txt for x in ("emerging","high yield","em debt","credit opportunities")):
            protected={"defensive","satellite"}
        else:
            protected={"core","defensive"}
    elif p.asset=="multiasset":
        eq,bd,ca,ot=mix(e)
        if eq>=.15: protected.add("core")
        if bd+ca>=.15: protected.add("defensive")
        if ot>=.20: protected.add("satellite")
    elif p.asset=="equity":
        if p.breadth=="thematic":
            protected={"satellite"}
        elif p.breadth=="sector" or p.sector:
            protected={"core","satellite"}
        elif p.factor in ("minimum_volatility","low_beta"):
            protected={"core","defensive"}
        elif p.factor=="quality":
            protected={"core","satellite"}
        elif p.size in ("small","ex_mega"):
            protected={"core","satellite"}
        elif p.breadth=="single_country" or f.geo_concentration>=.80:
            protected={"core","satellite"}
        elif p.geography=="emerging" and p.breadth=="broad":
            protected={"core","satellite"}
        elif p.breadth=="broad" and p.geography in ("usa","europe"):
            protected={"core","satellite"}
        else:
            protected={"core"}

    return protected,min_keep_ratio


def _quantize_effective(raw,threshold,protected=None,min_keep_ratio=.65):
    protected=set(protected or ())
    keep_floor=threshold*min_keep_ratio

    kept={}
    for k,v in raw.items():
        if v>=threshold:
            kept[k]=v
        elif k in protected and v>=keep_floor:
            kept[k]=v
        else:
            kept[k]=0.0

    if sum(kept.values())<=0:
        winner=max(raw,key=raw.get);kept[winner]=raw[winner]

    kt=sum(kept.values()) or 1.0
    er={k:100.0*v/kt for k,v in kept.items()}

    # 5-point largest-remainder quantization.
    unit=5.0
    exact={k:v/unit for k,v in er.items()}
    floors={k:int(math.floor(v+1e-12)) for k,v in exact.items()}
    remaining=int(round(100/unit))-sum(floors.values())
    order=sorted(exact,key=lambda k:(exact[k]-floors[k],er[k]),reverse=True)
    for k in order[:max(0,remaining)]:floors[k]+=1

    out={k:float(floors[k]*unit) for k in floors}

    # A protected role that survived economically must not be rounded back to zero.
    # Borrow one 5% quantum from the largest role when possible.
    for k in protected:
        if kept.get(k,0)>0 and out.get(k,0)==0:
            donor=max((x for x in out if x!=k),key=lambda x:out[x],default=None)
            if donor and out[donor]>=10:
                out[donor]-=5.0;out[k]=5.0

    return out


def _hierarchical_role_prior(e,p,f):
    st=structural_type(p)
    txt=ascii_text(" ".join(x for x in (e.name,e.description,e.category,e.benchmark_name) if x))
    flags=["ARCHETYPE:"+st];reasons=[];protected=set();keep_ratio=.65

    if st=="DIGITAL_ASSET":raw={"core":0,"defensive":0,"satellite":100};protected={"satellite"}
    elif st=="GOLD":raw={"core":0,"defensive":70,"satellite":30};protected={"defensive","satellite"}
    elif st=="COMMODITY":raw={"core":0,"defensive":0,"satellite":100};protected={"satellite"}
    elif st=="MONEY_MARKET":raw={"core":0,"defensive":100,"satellite":0};protected={"defensive"}
    elif p.asset=="multiasset":
        eq,bd,ca,ot=mix(e);total=eq+bd+ca+ot
        if total>.25:
            eq,bd,ca,ot=eq/total,bd/total,ca/total,ot/total
            scores={"core":2+6.5*eq+2*bd,"defensive":.7+7.5*bd+8.5*ca,"satellite":.5+2.5*eq+5*ot}
            ss=sum(scores.values());raw={k:100*v/ss for k,v in scores.items()}
            reasons.append(f"Multi-asset structural mix: equity {eq:.0%}, bond {bd:.0%}, cash {ca:.0%}, other {ot:.0%}.")
        else:
            raw={"core":50,"defensive":40,"satellite":10};reasons.append("Multi-asset identity known; allocation incomplete.")
        # Multi-asset keeps the operational 20% threshold strictly:
        # a minor sleeve must not survive only because it exists structurally.
        protected={k for k,v in raw.items() if v>=20}
    elif p.asset=="bond":
        if st=="ULTRA_SHORT_GOV_BOND":
            raw={"core":0,"defensive":100,"satellite":0};protected={"defensive"}
        elif st=="SHORT_GOV_BOND":
            # Individual sovereigns very close to maturity remain pure Defensive;
            # diversified 1-3y government funds retain a small Core role.
            is_near_btp=(e.instrument_type=="BTP" and (p.duration_years or 99)<=2.0)
            is_target=(" ibonds " in f" {txt} " or " target maturity " in f" {txt} ")
            if is_near_btp or is_target:
                raw={"core":0,"defensive":100,"satellite":0};protected={"defensive"}
            else:
                raw={"core":20,"defensive":80,"satellite":0};protected={"core","defensive"}
        elif st=="GOV_BOND":raw={"core":25,"defensive":75,"satellite":0};protected={"core","defensive"}
        elif st=="INFLATION_LINKED_BOND":
            raw={"core":20,"defensive":70,"satellite":10};protected={"core","defensive","satellite"};keep_ratio=.40
        elif any(x in txt for x in ("emerging","high yield","em debt","credit opportunities")):
            raw={"core":20,"defensive":45,"satellite":35};protected={"core","defensive","satellite"}
        elif p.issuer_type=="corporate":raw={"core":35,"defensive":65,"satellite":0};protected={"core","defensive"}
        elif p.issuer_type=="aggregate":raw={"core":35,"defensive":65,"satellite":0};protected={"core","defensive"}
        else:raw={"core":35,"defensive":65,"satellite":0};protected={"core","defensive"}
    elif p.asset=="equity":
        if st=="THEMATIC_EQUITY":raw={"core":0,"defensive":0,"satellite":100};protected={"satellite"}
        elif st.startswith("SECTOR_"):raw={"core":25,"defensive":0,"satellite":75};protected={"core","satellite"}
        elif p.factor in ("minimum_volatility","low_beta"):raw={"core":70,"defensive":30,"satellite":0};protected={"core","defensive"}
        elif p.factor=="quality":
            raw={"core":75 if p.geography=="world" else 65,"defensive":0,"satellite":25 if p.geography=="world" else 35};protected={"core","satellite"}
        elif p.size=="small":raw={"core":55,"defensive":0,"satellite":45};protected={"core","satellite"}
        elif p.size=="ex_mega":raw={"core":60,"defensive":0,"satellite":40};protected={"core","satellite"}
        elif st=="EMERGING_BROAD_EQUITY":raw={"core":70,"defensive":0,"satellite":30};protected={"core","satellite"}
        elif st=="SINGLE_COUNTRY_EQUITY":raw={"core":20,"defensive":0,"satellite":80};protected={"core","satellite"}
        elif st=="COUNTRY_BROAD_EQUITY":raw={"core":75,"defensive":0,"satellite":25};protected={"core","satellite"}
        elif p.geo_scope=="regional":raw={"core":80,"defensive":0,"satellite":20};protected={"core","satellite"}
        elif p.geography=="world" or p.geo_scope=="global":raw={"core":100,"defensive":0,"satellite":0};protected={"core"}
        else:raw={"core":85,"defensive":0,"satellite":15};protected={"core"}
    else:raw={"core":34,"defensive":33,"satellite":33}

    return raw,protected,keep_ratio,flags,reasons

def role(e,p,threshold=ROLE_MIN_PERCENT):
    f=exposure_fingerprint(e,p)
    raw,protected,keep_ratio,flags,reasons=_hierarchical_role_prior(e,p,f)
    total=sum(max(0,float(v)) for v in raw.values()) or 1
    raw={k:100*max(0,float(v))/total for k,v in raw.items()}
    effective=_quantize_effective(raw,threshold,protected,keep_ratio)
    evidence_count=sum([bool(e.name),bool(e.benchmark_name),bool(e.asset_classes),bool(p.asset),bool(p.geography),bool(p.breadth),e.volatility_1y is not None,e.top10_concentration is not None])
    identity=.88 if structural_type(p)!="UNKNOWN" else .45
    confidence=min(.99,.50*p.confidence+.22*f.evidence_confidence+.16*identity+.015*evidence_count)
    if p.gold or p.digital_asset or p.asset=="cash":confidence=max(confidence,.92)
    if structural_type(p) in ("ULTRA_SHORT_GOV_BOND","SHORT_GOV_BOND"):confidence=max(confidence,.92)
    flags.append("ROLE_AWARE_KEEP:"+(",".join(sorted(protected)) if protected else "none"))
    return RoleFit(raw["core"],raw["defensive"],raw["satellite"],
                   effective["core"],effective["defensive"],effective["satellite"],
                   [k.capitalize() for k,v in effective.items() if v>0],
                   confidence,flags,list(p.reasons)+list(f.reasons)+reasons)



# ---------------- benchmark provider functions ----------------

def identity_score(i,e):
    score=0.0
    c=re.sub(r"[^A-Z0-9]","",e.benchmark_code.upper()) if e.benchmark_code else ""
    codes={re.sub(r"[^A-Z0-9]","",x.upper()) for x in i.official_codes}
    if c and c in codes: score+=.60
    if e.benchmark_name:
        score+=.40*max([similarity(e.benchmark_name,i.official_name)]+[similarity(e.benchmark_name,a) for a in i.aliases])
    return min(1,score)

def msci_levels(code,variant="NETR",currency="USD"):
    url="https://app2.msci.com/products/service/index/indexmaster/getLevelDataForGraph?"+urlencode({
        "currency_symbol":currency,"index_variant":variant,
        "start_date":(date.today()-timedelta(days=FETCH_DAYS)).strftime("%Y%m%d"),
        "end_date":date.today().strftime("%Y%m%d"),"data_frequency":"DAILY","index_codes":code})
    try: payload=json.loads(http_text(url,{"Accept":"application/json,text/plain,*/*","Referer":"https://www.msci.com/"}))
    except Exception:return None
    rows=(payload.get("indexes") or {}).get("INDEX_LEVELS") or [];pts=[]
    for r in rows:
        if not isinstance(r,dict):continue
        dt=pd.to_datetime(str(r.get("calc_date") or ""),format="%Y%m%d",errors="coerce")
        val=pd.to_numeric(r.get("level_eod"),errors="coerce")
        if pd.notna(dt) and pd.notna(val):pts.append((pd.Timestamp(dt),float(val)))
    return clean_series(pd.Series([v for _,v in pts],index=[d for d,_ in pts])) if pts else None

def web_search(q):
    for url in (
        "https://www.google.com/search?"+urlencode({"q":q,"num":10}),
        "https://html.duckduckgo.com/html/?"+urlencode({"q":q})
    ):
        try:
            s=http_text(url,{"User-Agent":"Mozilla/5.0 Chrome/124 Safari/537.36"})
            if s:return s
        except Exception:pass
    return ""

def discover_msci(name, vendor_code=""):
    """
    Generic MSCI discovery, with self-learning benchmark cache.

    No ticker/ISIN rules and no hard-coded index list:
    1) dynamic cache lookup by provider+vendor code+benchmark name;
    2) web discovery using vendor code first, benchmark name second;
    3) official MSCI page verification;
    4) successful result persisted for future runs.
    """
    cached=cache_get("MSCI",vendor_code,name)
    if isinstance(cached,dict) and cached.get("provider_id"):
        return (
            str(cached.get("provider_id")),
            float(cached.get("similarity") or .95),
            str(cached.get("official_name") or name),
        )

    if not name and not vendor_code:
        return "",0.0,""
    queries=[]
    if vendor_code:
        queries.append(f'site:msci.com/indexes/index "{vendor_code}"')
        queries.append(f'site:msci.com/indexes/index MSCI {vendor_code}')
    if name:
        queries.append(f'site:msci.com/indexes/index "{name}"')
        queries.append(f'site:msci.com/indexes/index MSCI {" ".join(tokens(name)[:8])}')
    codes=[]
    for q in queries:
        h=unescape(web_search(q)).replace("\\/","/")
        for m in re.finditer(r"msci\.com/indexes/index/(\d{5,9})",h,re.I):
            if m.group(1) not in codes:codes.append(m.group(1))
        if codes:break
    best=("",0.0,"")
    for code in codes[:10]:
        try: page=strip_html(http_text(f"https://www.msci.com/indexes/index/{code}"))
        except Exception:continue
        m=re.search(r"(.{5,220}?)\s+Index code\s+"+re.escape(code),page,re.I)
        cname=re.sub(r"\s+"," ",m.group(1)).strip() if m else page[:500]
        sim=similarity(name,cname)
        if sim>best[1]:best=(code,sim,cname)
    if best[0]:
        cache_put(
            "MSCI",vendor_code,name,
            {
                "provider_id":best[0],
                "similarity":best[1],
                "official_name":best[2] or name,
                "discovered_at":datetime.now(timezone.utc).isoformat(),
            }
        )
    return best


def provider_exact_alt_candidates(provider, benchmark_name, benchmark_code):
    """
    Generic non-ETF recovery path.
    Searches Yahoo INDEX universe only using:
      - vendor code
      - official benchmark name
      - provider + code/name
    Returns candidate INDEX symbols with semantic scores.
    """
    queries=[]
    if benchmark_code:
        queries += [
            benchmark_code,
            f"{provider} {benchmark_code}",
        ]
    if benchmark_name:
        queries += [
            benchmark_name,
            f"{provider} {benchmark_name}",
        ]

    pool={}
    for q in queries:
        for sym,name in lookup_index(q):
            sim_name=similarity(benchmark_name,name) if benchmark_name else 0.0
            sim_code=1.0 if benchmark_code and benchmark_code.upper() in (sym.upper()+" "+name.upper()) else 0.0
            score=max(sim_name, .85*sim_code)
            if score>=.42:
                prev=pool.get(sym)
                if prev is None or score>prev[1]:
                    pool[sym]=(name,score)
    return pool

def recover_provider_exact_alt(provider,e,inst):
    """
    Generic provider recovery when direct vendor adapter is unavailable.
    Strictly Yahoo INDEX, never ETF.
    """
    pool=provider_exact_alt_candidates(provider,e.benchmark_name,e.benchmark_code)
    if not pool:
        return None

    h=yahoo_download(list(pool))
    viable=[]
    for sym,(name,sim) in pool.items():
        s=h.get(sym)
        if s is None or len(s)<SYNTH_MIN_OBS:
            continue
        cf=curve_fit(inst,s)
        trend=cf.trend if cf.available else 0.0
        # identity quality remains primarily semantic; trend only breaks ties.
        rank=.85*sim + .15*trend/100.0
        viable.append((rank,sim,trend,sym,name,s))
    if not viable:
        return None
    viable.sort(reverse=True,key=lambda x:x[0])
    rank,sim,trend,sym,name,s=viable[0]
    return Benchmark(
        level="EXACT_ALTERNATIVE_INDEX",
        provider="YAHOO",
        official_name=e.benchmark_name or name,
        provider_id=e.benchmark_code,
        variant="INDEX_LEVEL",
        currency="",
        operational_symbol=sym,
        confidence=min(.90,.65+.25*sim),
        observations=len(s),
        last_date=str(s.index.max().date()),
        note=(
            f"{provider} identity; Yahoo INDEX alternative exact/near-exact series; "
            f"semantic={sim:.2f}; trend={trend:.1f}%; never ETF."
        ),
        series=s,
    )

def nasdaq_history(code):
    if not code:return None
    url=f"https://api.nasdaq.com/api/quote/{quote(code)}/historical?"+urlencode({
        "assetclass":"index","fromdate":(date.today()-timedelta(days=FETCH_DAYS)).strftime("%m/%d/%Y"),
        "limit":5000,"todate":date.today().strftime("%m/%d/%Y")})
    try: payload=json.loads(http_text(url,{"Accept":"application/json,text/plain,*/*","Referer":f"https://indexes.nasdaq.com/Index/History/{code}"}))
    except Exception:return None
    data=payload.get("data") if isinstance(payload,dict) else None;rows=[]
    if isinstance(data,dict):
        for path in (("tradesTable","rows"),("historicalTable","rows")):
            obj=data
            for k in path:
                obj=obj.get(k) if isinstance(obj,dict) else None
            if isinstance(obj,list):rows=obj;break
    pts=[]
    for r in rows:
        if not isinstance(r,dict):continue
        dt=pd.to_datetime(r.get("date") or r.get("tradeDate"),errors="coerce")
        val=r.get("close") or r.get("value") or r.get("indexValue")
        if isinstance(val,str):val=val.replace("$","").replace(",","")
        val=pd.to_numeric(val,errors="coerce")
        if pd.notna(dt) and pd.notna(val):pts.append((pd.Timestamp(dt),float(val)))
    return clean_series(pd.Series([v for _,v in pts],index=[d for d,_ in pts])) if pts else None

def estr():
    url="https://data-api.ecb.europa.eu/service/data/EST/B.EU000A2X2A25.WT?"+urlencode({
        "startPeriod":(date.today()-timedelta(days=FETCH_DAYS)).isoformat(),
        "endPeriod":date.today().isoformat(),"format":"csvdata"})
    try:df=pd.read_csv(StringIO(http_text(url,{"Accept":"text/csv"})))
    except Exception:return None
    cols={str(c).upper():c for c in df.columns}
    if "TIME_PERIOD" not in cols or "OBS_VALUE" not in cols:return None
    return clean_series(pd.Series(pd.to_numeric(df[cols["OBS_VALUE"]],errors="coerce").values,
                                  index=pd.to_datetime(df[cols["TIME_PERIOD"]],errors="coerce")))

def compound_rate(r,spread_bps):
    if r is None or len(r)<2:return None
    days=pd.DatetimeIndex(r.index).to_series().diff().dt.days.fillna(1).astype(float)
    prev=r.shift(1).fillna(r.iloc[0])/100+spread_bps/10000
    ret=prev*days.values/360
    return clean_series(100*(1+ret).cumprod())

def lookup_index(query):
    _load_fast_cache()
    q=norm(query)
    if not q or not hasattr(yf,"Lookup"):return []
    key=ascii_text(q)
    cached=_LOOKUP_CACHE.get(key)
    if isinstance(cached,list):
        return [(norm(x[0]),norm(x[1])) for x in cached if isinstance(x,list) and len(x)>=2]
    out=[]
    try:
        df=yf.Lookup(q,timeout=3,raise_errors=False).get_index(count=15)
        if isinstance(df,pd.DataFrame) and not df.empty:
            w=df.reset_index(); low={str(c).casefold():c for c in w.columns}
            sc=low.get("symbol");nc=low.get("name") or low.get("longname") or low.get("shortname")
            for _,r in w.iterrows():
                sym=norm(r.get(sc)) if sc is not None else norm(r.iloc[0])
                if sym:out.append((sym,norm(r.get(nc)) if nc is not None else sym))
    except Exception:
        out=[]
    _LOOKUP_CACHE[key]=[[a,b] for a,b in out]
    _save_fast_cache()
    return out


def search_index_quotes(query):
    """
    Sparse Search fallback for index discovery.
    It is invoked only when the normal Lookup/static route cannot satisfy
    a close semantic tier. Results are persistently cached.
    """
    _load_fast_cache()
    q=norm(query)
    if not q:return []
    key="SEARCHINDEX2|"+ascii_text(q)
    cached=_LOOKUP_CACHE.get(key)
    if isinstance(cached,list):
        return [(norm(x[0]),norm(x[1])) for x in cached if isinstance(x,list) and len(x)>=2]

    out=[]
    try:
        rows=[x for x in (getattr(yf.Search(q,max_results=10),"quotes",None) or []) if isinstance(x,dict)]
        for row in rows:
            qt=norm(row.get("quoteType")).upper()
            if qt!="INDEX":continue
            sym=norm(row.get("symbol"))
            name=norm(row.get("longname") or row.get("shortname") or row.get("name") or sym)
            if sym:out.append((sym,name))
    except Exception:
        pass

    out=list(dict.fromkeys(out))
    _LOOKUP_CACHE[key]=[[a,b] for a,b in out]
    _save_fast_cache()
    return out


def yahoo_download(symbols):
    return yf_history_cached(symbols)

def maturity_token(y):
    m=max(1,int(round(y*12)));yy,mm=divmod(m,12)
    return f"{yy}Y{mm}M" if yy and mm else f"{yy}Y" if yy else f"{mm}M"

def ecb_gov_curve(y):
    key=f"B.U2.EUR.4F.G_N_C.SV_C_YM.PY_{maturity_token(y)}"
    url=f"https://data-api.ecb.europa.eu/service/data/YC/{key}?"+urlencode({
        "startPeriod":(date.today()-timedelta(days=FETCH_DAYS)).isoformat(),
        "endPeriod":date.today().isoformat(),"format":"csvdata"})
    try:df=pd.read_csv(StringIO(http_text(url,{"Accept":"text/csv"})))
    except Exception:return None
    cols={str(c).upper():c for c in df.columns}
    if "TIME_PERIOD" not in cols or "OBS_VALUE" not in cols:return None
    return clean_series(pd.Series(pd.to_numeric(df[cols["OBS_VALUE"]],errors="coerce").values,
                                  index=pd.to_datetime(df[cols["TIME_PERIOD"]],errors="coerce")))

def rendistato_band(y):
    bands=[("1Y-1Y6M",1.25),("1Y7M-2Y6M",2.04),("2Y7M-3Y6M",3.04),("3Y7M-4Y6M",4.04),
           ("4Y7M-6Y6M",5.54),("6Y7M-8Y6M",7.54),("8Y7M-12Y6M",10.54),("12Y7M-20Y6M",16.54),("20Y7M+",25)]
    return min(bands,key=lambda x:abs(x[1]-y))[0]

def rendistato_latest(y):
    """Discovers current official PDF from the Banca d'Italia Rendistato page."""
    page="https://www.bancaditalia.it/compiti/operazioni-mef/rendistato-rendiob/index.html?dotcache=refresh"
    try:html=http_text(page)
    except Exception:return None,""
    year=str(date.today().year);href=""
    for h in re.findall(r'href=["\']([^"\']+)["\']',html,re.I):
        h=unescape(h)
        if year in h and "rendistato" in h.casefold() and ".pdf" in h.casefold():
            href=h;break
    if not href:return None,""
    if href.startswith("/"):url="https://www.bancaditalia.it"+href
    elif href.startswith("http"):url=href
    else:url=page.rsplit("/",1)[0]+"/"+href
    try:
        from pypdf import PdfReader
        reader=PdfReader(BytesIO(http_bytes(url)));txt="\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception:return None,""
    label=rendistato_band(y)
    pats={
      "1Y-1Y6M":r"1\s+anno\s*[-–]\s*1\s+anno\s+6\s+mesi",
      "1Y7M-2Y6M":r"1\s+anno\s+7\s+mesi\s*[-–]\s*2\s+anni\s+6\s+mesi",
      "2Y7M-3Y6M":r"2\s+anni\s+7\s+mesi\s*[-–]\s*3\s+anni\s+6\s+mesi",
      "3Y7M-4Y6M":r"3\s+anni\s+7\s+mesi\s*[-–]\s*4\s+anni\s+6\s+mesi",
      "4Y7M-6Y6M":r"4\s+anni\s+7\s+mesi\s*[-–]\s*6\s+anni\s+6\s+mesi",
      "6Y7M-8Y6M":r"6\s+anni\s+7\s+mesi\s*[-–]\s*8\s+anni\s+6\s+mesi",
      "8Y7M-12Y6M":r"8\s+anni\s+7\s+mesi\s*[-–]\s*12\s+anni\s+6\s+mesi",
      "12Y7M-20Y6M":r"12\s+anni\s+7\s+mesi\s*[-–]\s*20\s+anni\s+6\s+mesi",
      "20Y7M+":r"20\s+anni\s+7\s+mesi\s+e\s+oltre"}
    ms=list(re.finditer(pats[label],txt,re.I))
    if not ms:return None,label
    sn=txt[ms[-1].end():ms[-1].end()+1000]
    vals=[]
    for x in re.findall(r"(?<!\d)(-?\d+[,.]\d{2,4})(?!\d)",sn):
        try:
            v=float(x.replace(",","."))
            if -5<=v<=20:vals.append(v)
        except Exception:pass
    return (vals[-1] if vals else None),label

def approximate_duration(T,coupon,yield_pct):
    T=max(.1,T);y=max(-.02,yield_pct/100);c=coupon if coupon is not None else max(0,y)
    f=2;n=max(1,int(round(T*f)));py=y/f;pc=c/f;pv=wt=0
    for i in range(1,n+1):
        t=i/f;cf=100*pc+(100 if i==n else 0);disc=(1+py)**i if 1+py>0 else 1
        x=cf/disc;pv+=x;wt+=t*x
    return (wt/pv)/(1+py) if pv>0 else .85*T

def synthetic_tr(yield_series,D):
    y=clean_series(yield_series)
    if len(y)<2:return None
    dy=(y.diff()/100).fillna(0)
    days=pd.DatetimeIndex(y.index).to_series().diff().dt.days.fillna(1).astype(float)
    carry=(y.shift(1).fillna(y.iloc[0])/100)*days.values/365
    convex=.70*D*D
    ret=carry-D*dy+.5*convex*(dy**2);ret.iloc[0]=0
    return clean_series(100*(1+ret).cumprod())

def sovereign_synthetic(e,p,cb=None):
    if p.asset!="bond" or p.issuer_type!="government":return None
    curve_maturity=e.maturity_years or p.duration_years
    if curve_maturity is None:return None
    log(cb,f"   curva sovereign EUR {curve_maturity:.2f}Y")
    yc=ecb_gov_curve(curve_maturity)
    if yc is None or len(yc)<SYNTH_MIN_OBS:return None
    latest_euro=float(yc.iloc[-1]);spread=0;provider="ECB";anchor="ECB euro-area government curve"
    if (e.country=="IT" or e.isin.startswith("IT")):
        it,band=rendistato_latest(curve_maturity)
        if it is not None:
            spread=it-latest_euro;provider="ECB + BANCA_D_ITALIA";anchor=f"Rendistato {band} anchor"
    country_curve=yc+spread
    if p.duration_years is not None:D=p.duration_years
    else:D=approximate_duration(curve_maturity,e.coupon_rate,float(country_curve.iloc[-1]))
    tr=synthetic_tr(country_curve,D)
    if tr is None or len(tr)<SYNTH_MIN_OBS:return None
    conf=.89 if provider.endswith("ITALIA") else .76
    is_italy=(e.country=="IT" or e.isin.startswith("IT"))
    if is_italy and provider.endswith("ITALIA"):
        sovereign_label="IT"
        display_name=f"Italy Sovereign Synthetic Total Return — duration {D:.2f}Y"
    elif is_italy:
        sovereign_label="EUR"
        display_name=f"EUR Sovereign Reference — duration {D:.2f}Y (Italy spread unavailable)"
        conf=min(conf,.58)
    else:
        sovereign_label="EUR"
        display_name=f"EUR Sovereign Synthetic Total Return — duration {D:.2f}Y"
    synthetic_code=f"{sovereign_label}-SOV-SYNTH-D{D:.2f}"
    return Benchmark("SYNTHETIC_SOVEREIGN_CURVE",provider,
        display_name,
        synthetic_code,"CONSTANT_DURATION_TR","EUR",synthetic_code,conf,len(tr),
        str(tr.index.max().date()),D,f"curve_maturity={curve_maturity:.2f}Y; duration={D:.2f}Y; spread={spread:.4f}pp",
        f"{anchor}; carry-duration-convexity; no ETF.",tr)

def bond_synthetic(e,p,cb=None):
    if p.asset!="bond" or p.duration_years is None or (e.currency and e.currency!="EUR"):return None
    yc=ecb_gov_curve(p.duration_years)
    if yc is None or len(yc)<SYNTH_MIN_OBS:return None
    tr=synthetic_tr(yc,p.duration_years)
    synthetic_code=f"EUR-BOND-SYNTH-D{p.duration_years:.2f}"
    return Benchmark("SYNTHETIC_BOND_CURVE","ECB",f"EUR Bond Synthetic Total Return — duration {p.duration_years:.2f}Y",
                     synthetic_code,"CONSTANT_DURATION_TR","EUR",synthetic_code,.65,len(tr),
                     str(tr.index.max().date()),p.duration_years,f"duration={p.duration_years:.2f}Y",
                     "Curve fallback; no ETF. Credit/spread risk only partially represented.",tr)


# ---------------- curve metrics / FX ----------------

def label(x):
    return "Molto alta" if x>=90 else "Alta" if x>=80 else "Buona" if x>=65 else "Moderata" if x>=50 else "Debole" if x>=35 else "Molto debole"

def safe_corr(a,b,method="pearson"):
    f=pd.concat([a.rename("a"),b.rename("b")],axis=1,join="inner").dropna()
    if len(f)<8 or f["a"].std()==0 or f["b"].std()==0:return None
    return float(f["a"].corr(f["b"],method=method))

def slopes(s,w=10):
    import numpy as np
    x=np.arange(w,dtype=float);xm=x.mean();den=((x-xm)**2).sum();vals=s.values;out=[float("nan")]*len(vals)
    for i in range(w-1,len(vals)):
        y=vals[i-w+1:i+1]
        if any(pd.isna(y)):continue
        out[i]=float(((x-xm)*(y-y.mean())).sum()/den)
    return pd.Series(out,index=s.index)

def curve_fit(inst,bm):
    """
    Trend is the primary operational metric.

    Daily tracking is diagnostic and automatically checks -1/0/+1 trading-day
    alignment because European instruments and global indices can have different
    closes/fixings. For near-zero-volatility references, unstable corr/beta are
    down-weighted in favour of absolute return error/path drift.
    """
    if inst is None or bm is None:
        return CurveFit(note="Serie mancante.")

    i=clean_series(inst); b=clean_series(bm)
    if len(i)<CHART_MIN_COMMON_OBS or len(b)<CHART_MIN_COMMON_OBS:
        f=pd.concat([i.rename("i"),b.rename("b")],axis=1,join="inner").dropna()
        return CurveFit(common_obs=len(f),note="Osservazioni comuni insufficienti.")

    # Generic fixing/close alignment: choose lag only from {-1,0,+1}.
    best=None
    for lag in (-1,0,1):
        bs=b.shift(lag)
        f=pd.concat([i.rename("i"),bs.rename("b")],axis=1,join="inner").dropna()
        if len(f)<CHART_MIN_COMMON_OBS:
            continue
        rr=f.pct_change().dropna()
        c=safe_corr(rr["i"],rr["b"]) if len(rr) else None
        score=-999 if c is None else c
        # Prefer zero lag when practically tied.
        score_adj=score-(0.004 if lag!=0 else 0)
        if best is None or score_adj>best[0]:
            best=(score_adj,lag,f)

    if best is None:
        return CurveFit(note="Osservazioni comuni insufficienti.")

    _,lag,f=best
    f=f.tail(CHART_TARGET_COMMON_OBS)
    norm=f/f.iloc[0]*100
    smooth=norm.rolling(5,min_periods=1).mean()

    sp=safe_corr(smooth["i"],smooth["b"],"spearman")
    r5=f.pct_change(5).dropna()
    c5=safe_corr(r5["i"],r5["b"])
    def sg(x): return 1 if x>.001 else -1 if x<-.001 else 0
    direction=float((r5["i"].map(sg)==r5["b"].map(sg)).mean()) if len(r5) else None
    lc=safe_corr(
        slopes(norm["i"].map(lambda x:math.log(max(x,1e-12)))),
        slopes(norm["b"].map(lambda x:math.log(max(x,1e-12))))
    )
    trend=100*(
        .30*max(0,sp or 0)
        +.30*max(0,c5 or 0)
        +.20*(direction or 0)
        +.20*max(0,lc or 0)
    )

    r=f.pct_change().dropna()
    c1=safe_corr(r["i"],r["b"])
    var=float(r["b"].var()) if len(r) else 0.0
    beta=float(r["i"].cov(r["b"])/var) if var>1e-14 else None
    te=float((r["i"]-r["b"]).std()*math.sqrt(252)) if len(r)>1 else None
    rmse=float(math.sqrt(((norm["i"]-norm["b"])**2).mean()))
    bvol=float(r["b"].std()*math.sqrt(252)) if len(r)>1 else 0.0
    mae=float((r["i"]-r["b"]).abs().mean()*math.sqrt(252)) if len(r) else None

    if bvol < .015:
        # Low-vol regime: corr and beta are numerically unstable.
        tracking=100*(
            .15*max(0,c1 or 0)
            +.45*max(0,1-(te or .05)/.05)
            +.25*max(0,1-(mae or .03)/.03)
            +.15*max(0,1-rmse/3)
        )
        regime="low-vol tracking"
    else:
        tracking=100*(
            .35*max(0,c1 or 0)
            +.30*max(0,1-(te or .20)/.20)
            +.20*max(0,1-abs((beta or 0)-1)/.5)
            +.15*max(0,1-rmse/10)
        )
        regime="standard tracking"

    return CurveFit(
        True,len(f),trend,label(trend),c5,direction,sp,lc,
        tracking,label(tracking),c1,beta,te,rmse,lag,
        f"Trend=5D/slope; {regime}; alignment lag={lag:+d}d."
    )

def fx_normalize(series,bm_ccy,inst_ccy,hedged):
    """
    Convert benchmark level into the instrument currency for comparison.

    Yahoo pair convention:
        EURUSD=X = USD per EUR.
    If benchmark=USD and instrument=EUR:
        benchmark_EUR = benchmark_USD / (USD per EUR)

    If direct pair fails, tries inverse pair and multiplies.
    """
    if series is None:
        return None,""
    b=norm(bm_ccy).upper()
    i=norm(inst_ccy).upper()
    if not b or not i or b==i or hedged is True:
        return series,""

    start=(date.today()-timedelta(days=FETCH_DAYS)).isoformat()
    end=(date.today()+timedelta(days=1)).isoformat()

    # Direct: instrument + benchmark = benchmark currency per instrument currency.
    direct=f"{i}{b}=X"
    try:
        h=yf.Ticker(direct).history(start=start,end=end,interval="1d",auto_adjust=True,actions=False)
        if isinstance(h,pd.DataFrame) and not h.empty and "Close" in h.columns:
            fx=clean_series(h["Close"])
            f=pd.concat([series.rename("b"),fx.rename("fx")],axis=1,join="inner").dropna()
            if not f.empty:
                return clean_series(f["b"]/f["fx"]),f"{b}->{i} FX-normalised via {direct}"
    except Exception:
        pass

    # Inverse: benchmark + instrument = instrument currency per benchmark currency.
    inverse=f"{b}{i}=X"
    try:
        h=yf.Ticker(inverse).history(start=start,end=end,interval="1d",auto_adjust=True,actions=False)
        if isinstance(h,pd.DataFrame) and not h.empty and "Close" in h.columns:
            fx=clean_series(h["Close"])
            f=pd.concat([series.rename("b"),fx.rename("fx")],axis=1,join="inner").dropna()
            if not f.empty:
                return clean_series(f["b"]*f["fx"]),f"{b}->{i} FX-normalised via {inverse}"
    except Exception:
        pass

    return series,"FX unavailable"



# -------------------------------------------------------------------
# POC17.2 FROZEN C/D/S + ROLE-GUIDED BENCHMARK RESOLVER ENGINE
# -------------------------------------------------------------------

# General market knowledge only: no instrument/ticker/ISIN mappings.
# Every item is a NON-ETF Yahoo/yfinance index or market reference.
REFERENCE_FAMILIES = {
    "GLOBAL_EQUITY": ["^GSPC", "^IXIC"],
    "USA_EQUITY": ["^GSPC", "^DJI", "^IXIC"],
    "EUROPE_EQUITY": ["^STOXX50E", "^FTSE", "^GDAXI"],
    "EMERGING_EQUITY": ["^HSI", "000001.SS", "^BSESN"],
    "SMALL_CAP": ["^RUT"],
    "TECH_GROWTH": ["^NDX", "^IXIC"],
    "ENERGY": ["^GSPE"],
    "MATERIALS": ["^SP500-15"],
    "HEALTHCARE": ["^SP500-35"],
    "REAL_ESTATE": ["^SP500-60", "^DJUSRE"],
    "FINANCIALS": ["^SP500-40"],
    "INDUSTRIALS": ["^SP500-20"],
    "UTILITIES": ["^SP500-55"],
    "CONSUMER_STAPLES": ["^SP500-30"],
    "CONSUMER_DISCRETIONARY": ["^SP500-25"],
    "COMMUNICATION_SERVICES": ["^SP500-50"],
    "FINANCIALS": ["^SP500-40"],
    "INDUSTRIALS": ["^SP500-20"],
    "UTILITIES": ["^SP500-55"],
    "CONSUMER_STAPLES": ["^SP500-30"],
    "CONSUMER_DISCRETIONARY": ["^SP500-25"],
    "COMMUNICATION_SERVICES": ["^SP500-50"],
    "COMMODITY": ["^SPGSCI", "^BCOM"],
    "GOLD": ["GC=F"],
    "BITCOIN": ["BTC-USD"],
}

def _download_first_available(symbols):
    symbols=list(dict.fromkeys(s for s in symbols if s))
    if not symbols:
        return None,None
    hs=yf_history_cached(symbols)
    for sym in symbols:
        s=hs.get(sym)
        if s is not None and len(s)>=SYNTH_MIN_OBS:
            return sym,s
    return None,None


# -------------------------------------------------------------------
# POC11 GEOMETRY-AWARE SELECTION
# -------------------------------------------------------------------

def _common_frame(a,b,max_obs=252):
    a=clean_series(a); b=clean_series(b)
    if a is None or b is None:return None
    f=pd.concat([a.rename("a"),b.rename("b")],axis=1,join="inner").dropna()
    if len(f)<2:return None
    return f.tail(max_obs)

def geometry_weight(n):
    # Once we have a meaningful history, visual/geometric behaviour becomes
    # the dominant selector among semantically admissible relatives.
    if n < 20:return .15
    if n < 40:return .30
    if n < 60:return .45
    if n < 120:return .55
    if n < 180:return .62
    return .68

def _shape_similarity(a,b):
    """
    Graph-oriented similarity, 0..100.
    Explicitly penalises curves that are visually far apart even when
    rank-correlation or direction happens to look good.
    """
    f=_common_frame(a,b,252)
    if f is None or len(f)<5:
        return 0.0,len(f) if f is not None else 0,{}

    n=len(f)
    na=f["a"]/f["a"].iloc[0]*100.0
    nb=f["b"]/f["b"].iloc[0]*100.0

    # 1) Absolute path distance in percentage points.
    path_gap=(na-nb).abs()
    mae=float(path_gap.mean())
    rmse=float((path_gap.pow(2).mean())**0.5)

    # Scale by actual movement of the instrument so flat/volatile curves
    # are judged on a comparable basis.
    movement=max(4.0,float((na.max()-na.min())))
    path_fit=max(0.0,1.0-min(1.0,rmse/(0.55*movement+2.0)))
    mae_fit=max(0.0,1.0-min(1.0,mae/(0.40*movement+1.5)))

    # 2) End-to-end development: final cumulative return should not be far away.
    terminal_gap=abs(float(na.iloc[-1]-nb.iloc[-1]))
    terminal_fit=max(0.0,1.0-min(1.0,terminal_gap/(0.50*movement+3.0)))

    # 3) Drawdown behaviour.
    dda=na/na.cummax()-1.0
    ddb=nb/nb.cummax()-1.0
    dd_rmse=float(((dda-ddb).pow(2).mean())**0.5)
    dd_fit=max(0.0,1.0-min(1.0,dd_rmse/.10))

    # 4) Multi-horizon movement/direction.
    horizon_scores=[]
    direction_scores=[]
    for h in (5,10,20,60):
        if n<=h+3:continue
        ra=na.pct_change(h).dropna()
        rb=nb.pct_change(h).dropna()
        rr=pd.concat([ra.rename("a"),rb.rename("b")],axis=1).dropna()
        if len(rr)<4:continue
        c=safe_corr(rr["a"],rr["b"])
        horizon_scores.append(max(0.0,(c or 0.0)))
        direction_scores.append(float(((rr["a"]>=0)==(rr["b"]>=0)).mean()))
    horizon_fit=sum(horizon_scores)/len(horizon_scores) if horizon_scores else 0.0
    direction_fit=sum(direction_scores)/len(direction_scores) if direction_scores else .5

    # 5) Local slope of normalized paths.
    la=slopes(na.map(lambda x:math.log(max(x,1e-12))))
    lb=slopes(nb.map(lambda x:math.log(max(x,1e-12))))
    slope_corr=safe_corr(la,lb)
    slope_fit=max(0.0,slope_corr or 0.0)

    # VISUAL score. Path/development gets 55% of total.
    score=100.0*(
        .25*path_fit +
        .15*mae_fit +
        .15*terminal_fit +
        .10*dd_fit +
        .15*horizon_fit +
        .10*direction_fit +
        .10*slope_fit
    )
    return max(0.0,min(100.0,score)),n,{
        "path_mae":mae,
        "path_rmse":rmse,
        "path_fit":path_fit,
        "terminal_gap":terminal_gap,
        "terminal_fit":terminal_fit,
        "drawdown_fit":dd_fit,
        "multi_horizon_fit":horizon_fit,
        "direction_fit":direction_fit,
        "slope_fit":slope_fit,
    }

def geometry_metrics(inst,ref):
    if inst is None or ref is None:return 0.0,0,{}
    best=None
    rr=clean_series(ref)
    if rr is None:return 0.0,0,{}
    for lag in (-1,0,1):
        score,n,m=_shape_similarity(inst,rr.shift(lag))
        adj=score-(0.25 if lag!=0 else 0.0)
        if best is None or adj>best[0]:
            mm=dict(m or {});mm["alignment_lag_days"]=lag;best=(adj,score,n,mm)
    return (best[1],best[2],best[3]) if best else (0.0,0,{})


_REFERENCE_ROLE_CACHE={}

def role_vector(rolefit):
    return (
        float(rolefit.core),
        float(rolefit.defensive),
        float(rolefit.satellite),
    )

def role_similarity_score(target_role,candidate_role):
    """
    L1 distance on the 100%-simplex.
    Max distance is 200, therefore 100 - L1/2 is naturally 0..100.
    """
    if target_role is None or candidate_role is None:return 50.0
    a=role_vector(target_role);b=role_vector(candidate_role)
    return max(0.0,min(100.0,100.0-(sum(abs(x-y) for x,y in zip(a,b))/2.0)))

def _candidate_context_text(name,symbol,tier_name,p,e,query=""):
    """
    Build an economic description of a candidate without any ticker-specific rule.
    Tier context is used only when the provider name is too generic.
    """
    n=norm(name);q=norm(query);tier=norm(tier_name).upper()
    geo=(p.geography or "").replace("_"," ")
    if tier=="THEME":
        th=(p.theme or "").replace("_"," ")
        ctx=f"{geo} {th} thematic equity index"
    elif tier=="SECTOR":
        sec=(p.sector or "").replace("_"," ")
        ctx=f"{geo} {sec} sector equity index"
    elif tier=="FACTOR":
        fac=(p.factor or "").replace("_"," ")
        ctx=f"{geo or 'global'} {fac} factor equity index"
    elif tier=="SIZE":
        sz=(p.size or "").replace("_"," ")
        ctx=f"{geo or 'global'} {sz} cap equity index"
    elif tier=="GEOGRAPHY":
        ctx=f"{geo or 'global'} broad equity index"
    elif tier=="EM_PARENT":
        ctx="emerging markets broad equity index"
    elif tier=="REGIONAL_PARENT":
        ctx=f"{geo or 'regional'} broad equity index"
    elif tier=="GLOBAL_PARENT":
        ctx="global broad equity index"
    elif tier=="BOND_STYLE":
        issuer=p.issuer_type or "government"
        ctx=f"{geo or 'global'} inflation linked {issuer} bond index"
    elif tier=="BOND_CLOSE":
        issuer=p.issuer_type or "aggregate"
        bucket=_maturity_bucket(p.duration_years or e.maturity_years)
        ctx=f"{geo or 'euro'} {issuer} bond {bucket} index"
    elif tier=="BOND_PARENT":
        issuer=p.issuer_type or "aggregate"
        ctx=f"{geo or 'global'} {issuer} bond index"
    else:
        ctx=""
    return " | ".join(x for x in (n,q,ctx) if x)

def _family_context_text(family,p,e):
    f=norm(family).upper()
    mapping={
        "GLOBAL_EQUITY":"global broad equity index",
        "EUROPE_EQUITY":"Europe broad equity index",
        "EMERGING_EQUITY":"emerging markets broad equity index",
        "SMALL_CAP":"global small cap equity index",
        "TECH_GROWTH":"global technology sector equity index",
        "ENERGY":"global energy sector equity index",
        "HEALTHCARE":"global healthcare sector equity index",
        "REAL_ESTATE":"global real estate sector equity index",
        "FINANCIALS":"global financials sector equity index",
        "INDUSTRIALS":"global industrials sector equity index",
        "UTILITIES":"global utilities sector equity index",
        "CONSUMER_STAPLES":"global consumer staples sector equity index",
        "CONSUMER_DISCRETIONARY":"global consumer discretionary sector equity index",
        "COMMUNICATION_SERVICES":"global communication services sector equity index",
        "MATERIALS":"global materials metals mining sector equity index",
        "GOLD":"physical gold",
        "BITCOIN":"bitcoin digital asset",
        "CASH":"money market overnight rate",
        "COMMODITY":"broad commodity index",
    }
    return mapping.get(f,f.replace("_"," ").lower()+" index")

def candidate_role_signature(name,symbol,tier_name,p,e,query="",family=""):
    """
    Infer the candidate C/D/S with the frozen generic C/D/S engine.
    Cached by economic descriptor; CPU-only.
    """
    desc=_family_context_text(family,p,e) if family else _candidate_context_text(name,symbol,tier_name,p,e,query)
    key=ascii_text(desc)
    if key in _REFERENCE_ROLE_CACHE:
        return _REFERENCE_ROLE_CACHE[key]
    ce=Evidence(
        name=desc or norm(name) or norm(symbol),
        instrument_type="INDEX",
        currency=e.currency,
    )
    cp=profile(ce)
    cr=role(ce,cp,ROLE_MIN_PERCENT)
    out={
        "core":float(cr.core),
        "defensive":float(cr.defensive),
        "satellite":float(cr.satellite),
        "structural_type":structural_type(cp),
        "role":cr,
        "descriptor":desc,
    }
    _REFERENCE_ROLE_CACHE[key]=out
    return out

def roleaware_reference_score(semantic,role_sim,geometry,n,history_quality=1.0):
    """
    Candidate ranking after domain/tier admissibility.
    Mature history: 30% semantic + 25% role + 40% geometry + 5% quality.
    With short history, geometry weight is redistributed to semantic/role.
    """
    sem=max(0.0,min(1.0,float(semantic)))
    rs=max(0.0,min(1.0,float(role_sim)/100.0))
    geom=max(0.0,min(1.0,float(geometry)/100.0))
    hq=max(0.0,min(1.0,float(history_quality)))
    if n < 20:
        sw,rw,gw,qw=.50,.40,0.0,.10
    elif n < 60:
        sw,rw,gw,qw=.40,.30,.25,.05
    elif n < 120:
        sw,rw,gw,qw=.34,.27,.34,.05
    else:
        sw,rw,gw,qw=.30,.25,.40,.05
    return 100.0*(sw*sem+rw*rs+gw*geom+qw*hq)

def _role_threshold_for_tier(tier_name):
    tier=norm(tier_name).upper()
    if tier in ("THEME","SECTOR","FACTOR","SIZE","BOND_STYLE","BOND_CLOSE"):
        return 72.0
    if tier in ("GEOGRAPHY","EM_PARENT","REGIONAL_PARENT","BOND_PARENT"):
        return 60.0
    return 45.0

def roleaware_candidate_quality_gate(semantic,role_sim,geom,n,tier_name=""):
    if semantic < .60:return False
    if role_sim < _role_threshold_for_tier(tier_name):return False
    if n < 20:
        return semantic>=.72 and role_sim>=75
    # Strong economic-role agreement can tolerate a modestly weaker visual fit;
    # weak role agreement requires a better geometry.
    relief=6.0 if role_sim>=95 and semantic>=.78 else 3.0 if role_sim>=85 else 0.0
    penalty=5.0 if role_sim<70 else 0.0
    if n < 40:need=45
    elif n < 60:need=50
    elif n < 120:need=55
    else:need=58
    return geom >= (need-relief+penalty)

def combined_reference_score(semantic,geometry,n,history_quality=1.0):
    gw=geometry_weight(n)
    quality=.05
    sw=max(0.0,1.0-gw-quality)
    return 100.0*(sw*semantic + gw*(geometry/100.0) + quality*history_quality)


def _review_status(n):
    if n < 20:return "INIZIALE_SEMANTICA"
    if n < 60:return "PROVVISORIA_GEOMETRICA"
    return "VALIDATA_DA_RIVEDERE_PERIODICAMENTE"

def _review_next_obs(n,step=60):
    if n < 20:return 20
    if n < 60:return 60
    return int((n//step+1)*step)

def _lookup_best_index(queries, e, instrument_series=None, minimum_similarity=.20, max_symbols=8):
    target=" ".join(x for x in (e.benchmark_name,e.benchmark_area,e.name,e.description) if x)
    candidates={}
    for q in queries:
        if not q: continue
        for sym,name in lookup_index(q):
            sim=similarity(target,name) if target else 0.0
            if sim < minimum_similarity: continue
            prev=candidates.get(sym)
            if prev is None or sim>prev[1]:
                candidates[sym]=(name,sim)
    ranked=sorted(((sim,sym,name) for sym,(name,sim) in candidates.items()), reverse=True)[:max_symbols]
    if not ranked:return None
    hs=yf_history_cached([x[1] for x in ranked])
    scored=[]
    for sim,sym,name in ranked:
        s=hs.get(sym)
        if s is None or len(s)<SYNTH_MIN_OBS:continue
        # lexical similarity is converted to a bounded semantic compatibility.
        semantic=min(.98,.60+.40*max(0.0,min(1.0,sim)))
        geom,n,_=geometry_metrics(instrument_series,s)
        total=combined_reference_score(semantic,geom,n,1.0)
        scored.append((total,geom,n,semantic,sim,sym,name,s))
    if not scored:return None
    scored.sort(reverse=True,key=lambda x:x[0])
    return scored[0] + (len(scored),)




# -------------------------------------------------------------------
# DOMAIN LOCK
# -------------------------------------------------------------------
# Static ontology of REFERENCE symbols is allowed: it describes public market
# references, never user instruments. It prevents e.g. physical gold from
# accidentally using gold-mining equities.
REFERENCE_SYMBOL_DOMAIN = {
    "GC=F":"gold",
    "^XAU":"equity_sector_metals_mining",
    "^GSPC":"equity",
    "^DJI":"equity",
    "^IXIC":"equity",
    "^NDX":"equity",
    "^STOXX50E":"equity",
    "^FTSE":"equity",
    "^GDAXI":"equity",
    "^N225":"equity",
    "^HSI":"equity",
    "^RUT":"equity",
    "^MID":"equity",
    "^BCOM":"commodity",
    "^SPGSCI":"commodity",
        "^GSPE":"equity_sector_energy",
    "^SP500-15":"equity_sector_materials",
    "^SP500-35":"equity_sector_healthcare",
    "^SP500-60":"equity_sector_real_estate",
    "^DJUSRE":"equity_sector_real_estate",
    "BTC-USD":"digital_asset",
    "€STR":"cash",
}

def economic_domain(p,e):
    if p.gold:return "gold"
    if p.digital_asset:return "digital_asset"
    if p.asset=="cash":return "cash"
    if p.asset=="commodity":return "commodity"
    if p.asset=="multiasset":return "multiasset"
    if p.asset=="bond":
        if p.bond_style=="inflation_linked":return "bond_inflation"
        if p.issuer_type=="government":return "bond_government"
        if p.issuer_type=="corporate":return "bond_corporate"
        return "bond"
    if p.asset=="equity":
        if p.sector:return "equity_sector_"+p.sector
        if p.factor:return "equity_factor_"+p.factor
        return "equity"
    return "unknown"

def _domain_family(domain):
    if domain.startswith("equity"):return "equity"
    if domain.startswith("bond"):return "bond"
    return domain

def _candidate_text_domain(name):
    t=(" "+ascii_text(name or "")+" ")
    if any(x in t for x in (" bitcoin "," crypto "," digital asset ")):return "digital_asset"
    if any(x in t for x in (" gold miners "," gold mining "," gold & silver "," gold and silver "," mining index ")):
        return "equity_sector_metals_mining"
    if any(x in t for x in (" gold spot "," gold bullion "," gold futures "," lbma gold "," gold price ")):return "gold"
    if any(x in t for x in (" commodity "," commodities "," gsci "," bloomberg commodity ")):return "commodity"
    if any(x in t for x in (" bond "," sovereign "," government "," treasury "," aggregate "," credit "," fixed income ")):
        if " inflation " in t:return "bond_inflation"
        if any(x in t for x in (" government "," sovereign "," treasury ")):return "bond_government"
        if " corporate " in t or " credit " in t:return "bond_corporate"
        return "bond"
    if any(x in t for x in (" equity "," stock "," s&p "," stoxx "," msci "," nasdaq "," dow jones "," ftse ")):
        return "equity"
    return "unknown"

def domain_compatible(p,e,symbol="",name=""):
    domain=economic_domain(p,e)
    if domain=="multiasset":return True
    refdom=REFERENCE_SYMBOL_DOMAIN.get(symbol) or _candidate_text_domain(name)
    if refdom=="unknown":
        # Unknown metadata is not automatically rejected, but must be judged
        # by required/forbidden concepts in semantic_gate.
        return True
    fam=_domain_family(domain); rfam=_domain_family(refdom)
    if fam!=rfam:return False
    # Within gold/digital/cash exact domain is strict.
    if domain in ("gold","digital_asset","cash"):
        return refdom==domain
    # Bond specializations can broaden to bond family, never cross to equity.
    if fam=="bond":return rfam=="bond"
    # Equity sector/factor can broaden to generic equity as aunt/grandmother.
    if fam=="equity":return rfam=="equity"
    if domain=="commodity":return refdom in ("commodity",)
    return True

def domain_required_forbidden(p,e):
    d=economic_domain(p,e)
    if d=="gold":
        return (("gold","bullion","lbma"),("miner","mining","equity","stock","producer","company"))
    if d=="digital_asset":
        return (("bitcoin","crypto","digital"),("equity","stock","bond"))
    if d=="cash":
        return (("overnight","cash","rate","estr","money market"),("equity","stock","commodity"))
    if d.startswith("bond"):
        req=("bond","government","sovereign","treasury","aggregate","credit","fixed income")
        forb=("equity","stock index","nasdaq","s&p 500","technology","commodity")
        return req,forb
    if d.startswith("equity"):
        return (("equity","stock","index","market"),("bond","treasury","sovereign","commodity futures"))
    if d=="commodity":
        return (("commodity","commodities","futures"),("equity","stock","bond"))
    return ((),())

def reference_domain_valid(p,e,b):
    if b is None or b.series is None:return False
    # Exact direct-provider benchmarks are accepted unless their visible
    # operational symbol is explicitly known to violate the domain.
    symbol=b.operational_symbol or b.provider_id or ""
    name=" ".join(x for x in (b.official_name,b.note,b.variant) if x)
    return domain_compatible(p,e,symbol,name)

def _maturity_bucket(years):
    if years is None:return ""
    if years <= 1.25:return "0-1 year"
    if years <= 3.5:return "1-3 year"
    if years <= 7.0:return "3-7 year"
    if years <= 12.0:return "7-10 year"
    return "10+ year"

GENERIC_THEME_TERMS = (
    "water","clean energy","renewable","solar","wind","hydrogen","battery",
    "robotics","automation","artificial intelligence","ai","cyber","security",
    "digital","gaming","esports","agribusiness","agriculture","food",
    "ageing","aging","health innovation","biotech","semiconductor",
    "infrastructure","mobility","electric vehicle","climate","carbon",
    "fintech","cloud","space","defence","defense","uranium","nuclear"
)

def generic_theme_terms(e):
    t=ascii_text(" ".join(x for x in (e.name,e.description,e.category,e.benchmark_name) if x))
    hits=[]
    for term in GENERIC_THEME_TERMS:
        if term in t and term not in hits:
            hits.append(term)
    return hits[:4]

def _smart_queries(p,e):
    qs=[]
    asset=(p.asset or "").lower()
    geo=(p.geography or "").lower()
    sector=(p.sector or "").lower()
    factor=(p.factor or "").lower()
    size=(p.size or "").lower()

    # Domain-specific branches MUST precede broad asset-class branches.
    if p.gold:
        qs += [
            "gold spot price index","gold bullion index","LBMA gold price index",
            "gold futures index","gold total return commodity index","precious metals commodity index"
        ]
    elif p.digital_asset:
        qs += ["bitcoin index","bitcoin reference rate index"]
    elif asset=="cash":
        qs += ["euro overnight rate index","euro money market index","ESTR index"]
    elif asset=="commodity":
        qs += ["broad commodity index","commodity total return index"]
    elif asset=="equity":
        themes=generic_theme_terms(e)
        for th in themes:
            qs += [
                f"global {th} equity index",
                f"{th} thematic index",
                f"{th} industry index",
                f"{th} sector index"
            ]
        if sector:
            qs += [f"{geo} {sector} equity index",f"global {sector} equity index",f"developed {sector} equity index"]
        if factor:
            aliases=[factor.replace("_"," ")]
            if factor=="minimum_volatility":aliases += ["minimum volatility","low volatility","low beta","defensive equity"]
            if factor=="quality":aliases += ["quality factor","high quality"]
            for a in aliases:
                qs += [f"global {a} equity index",f"developed {a} equity index",f"{geo} {a} equity index"]
        if size:
            qs += [f"{geo} {size.replace('_',' ')} cap equity index",f"global {size.replace('_',' ')} cap equity index"]
        if geo:
            qs += [f"{geo} equity index",f"{geo} broad market index"]
        qs += ["global equity index","developed markets equity index"]
    elif asset=="bond":
        bucket=_maturity_bucket(p.duration_years or e.maturity_years)
        country="Italy" if e.country=="IT" or p.geography=="italy" else (e.country or "")
        if p.bond_style=="inflation_linked":
            qs += [
                f"{country} inflation linked government bond {bucket} index" if country else "",
                f"Euro inflation linked government bond {bucket} index",
                "Euro inflation linked government bond index",
                "global inflation linked government bond index",
            ]
        if p.issuer_type=="government":
            if country:
                qs += [f"{country} government bond {bucket} index",f"{country} sovereign bond index"]
            qs += [
                f"Euro government bond {bucket} index","Euro sovereign bond index",
                "global government bond index"
            ]
        elif p.issuer_type=="corporate":
            qs += [f"Euro corporate bond {bucket} index","Euro corporate bond index","global corporate bond index"]
        else:
            qs += [f"Euro aggregate bond {bucket} index","Euro aggregate bond index","global aggregate bond index"]

    out=[];seen=set()
    for q in qs:
        q=" ".join((q or "").split())
        if q and q.lower() not in seen:
            seen.add(q.lower());out.append(q)
    return out[:20]


def _semantic_gate_from_text(target,name,p,e,symbol=""):
    if not domain_compatible(p,e,symbol,name):
        return 0.0

    base=similarity(target,name) if target else 0.0
    text=(" "+ascii_text(name or "")+" ")
    required,forbidden=domain_required_forbidden(p,e)

    # Strong negative concepts are a hard veto.
    if any(x and (" "+ascii_text(x)+" ") in text for x in forbidden):
        return 0.0

    positive=sum(1 for x in required if x and ascii_text(x) in text)
    # For strict domains, require at least one positive concept unless a
    # known reference symbol already establishes the domain.
    d=economic_domain(p,e)
    known_ref=REFERENCE_SYMBOL_DOMAIN.get(symbol)
    if d in ("gold","digital_asset","cash") and not known_ref and positive==0:
        return 0.0

    bonus=min(.20,.06*positive)
    for token in (
        (p.geography or "").replace("_"," "),
        (p.sector or "").replace("_"," "),
        (p.factor or "").replace("_"," "),
        (p.size or "").replace("_"," "),
        (p.issuer_type or "").replace("_"," "),
        (p.bond_style or "").replace("_"," "),
    ):
        token=ascii_text(token.strip())
        if token and len(token)>=3 and token in text: bonus+=.05

    if e.country=="IT" and (" italy " in text or " italian " in text):bonus+=.10
    return max(0.0,min(.98,.50+.34*base+bonus))


def _candidate_quality_gate(semantic,geom,n):
    if semantic < .60:return False
    if n < 20:return False
    if n < 40:return geom >= 45
    if n < 60:return geom >= 50
    if n < 120:return geom >= 55
    return geom >= 58


def _evaluate_candidate_pool_roleaware(pool,inst,p,e,target_role,tier_name="",limit=18):
    ranked=sorted(((sem,sym,name,q) for sym,(name,sem,q) in pool.items()),reverse=True)[:limit]
    if not ranked:return []
    hs=yf_history_cached([x[1] for x in ranked])
    out=[]
    for sem,sym,name,q in ranked:
        s=hs.get(sym)
        if s is None or len(s)<2:continue
        geom,n,gm=geometry_metrics(inst,s)
        sig=candidate_role_signature(name,sym,tier_name,p,e,q)
        rs=role_similarity_score(target_role,sig["role"])
        total=roleaware_reference_score(sem,rs,geom,n,1.0)
        out.append({
            "score":total,"geometry":geom,"n":n,"semantic":sem,
            "role_similarity":rs,
            "candidate_core":sig["core"],"candidate_defensive":sig["defensive"],
            "candidate_satellite":sig["satellite"],
            "candidate_structural_type":sig["structural_type"],
            "symbol":sym,"name":name,"query":q,"series":s,"metrics":gm
        })
    out.sort(key=lambda x:x["score"],reverse=True)
    return out

def _evaluate_candidate_pool(pool,inst,limit=14):
    ranked=sorted(((sem,sym,name,q) for sym,(name,sem,q) in pool.items()),reverse=True)[:limit]
    if not ranked:return []
    hs=yf_history_cached([x[1] for x in ranked])
    out=[]
    for sem,sym,name,q in ranked:
        s=hs.get(sym)
        if s is None or len(s)<2:continue
        geom,n,gm=geometry_metrics(inst,s)
        total=combined_reference_score(sem,geom,n,1.0)
        out.append({
            "score":total,"geometry":geom,"n":n,"semantic":sem,
            "symbol":sym,"name":name,"query":q,"series":s,"metrics":gm
        })
    out.sort(key=lambda x:x["score"],reverse=True)
    return out

def _smart_search_candidates(p,e,inst,cb=None):
    """
    Progressive search. Do NOT execute 20 Yahoo lookups up front.
    Search close relatives first; widen only when the current tier is weak.
    """
    queries=_smart_queries(p,e)
    target=" ".join(x for x in (
        e.benchmark_name,e.name,e.description,p.geography,p.sector,p.factor,p.size,p.issuer_type,p.bond_style
    ) if x)

    pool={}
    # Tier boundaries: most instruments stop after 4 queries.
    tiers=(4,8,12)
    previous=0
    best_out=[]
    for upto in tiers:
        for q in queries[previous:upto]:
            for sym,name in lookup_index(q):
                sem=_semantic_gate_from_text(target,name,p,e,sym)
                if sem < .60:continue
                prev=pool.get(sym)
                if prev is None or sem>prev[1]:
                    pool[sym]=(name,sem,q)
        previous=upto
        best_out=_evaluate_candidate_pool(pool,inst,limit=14)
        if best_out:
            b=best_out[0]
            if _candidate_quality_gate(b["semantic"],b["geometry"],b["n"]):
                return best_out
        if upto>=len(queries):break

    # Last widening only if all prior tiers failed.
    if previous < len(queries):
        for q in queries[previous:min(len(queries),16)]:
            for sym,name in lookup_index(q):
                sem=_semantic_gate_from_text(target,name,p,e,sym)
                if sem < .60:continue
                prev=pool.get(sym)
                if prev is None or sem>prev[1]:
                    pool[sym]=(name,sem,q)
        best_out=_evaluate_candidate_pool(pool,inst,limit=18)

    return best_out


def _relation_from_semantic(sem):
    if sem>=.90:return "SORELLA"
    if sem>=.80:return "CUGINA"
    if sem>=.70:return "ZIA"
    return "NONNA"

def _candidate_ladder_rows(candidates,limit=8):
    rows=[]
    for c in candidates[:limit]:
        rows.append({
            "symbol":c["symbol"],"name":c["name"],
            "relation":_relation_from_semantic(c["semantic"]),
            "semantic_confidence":round(c["semantic"],4),
            "geometry_score":round(c["geometry"],2),
            "selection_score":round(c["score"],2),
            "role_similarity_score":round(c.get("role_similarity",0.0),2),
            "candidate_core_pct":round(c.get("candidate_core",0.0),1),
            "candidate_defensive_pct":round(c.get("candidate_defensive",0.0),1),
            "candidate_satellite_pct":round(c.get("candidate_satellite",0.0),1),
            "candidate_structural_type":c.get("candidate_structural_type",""),
            "common_obs":int(c["n"]),"query":c["query"],
            "series":c["series"],
        })
    return rows

def _deep_relative_queries(p,e):
    """
    Second-stage precise queries used ONLY when the first reference is weak.
    Small bounded list -> speed remains controlled.
    """
    qs=[]
    geo=(p.geography or "").replace("_"," ")
    if p.asset=="equity":
        if p.sector:
            sec=p.sector.replace("_"," ")
            aliases={
                "energy":["energy","oil gas"],
                "healthcare":["health care","healthcare"],
                "real estate":["real estate","property"],
                "technology":["information technology","technology"],
                "financials":["financials","financial services"],
                "industrials":["industrials"],
                "utilities":["utilities"],
                "consumer staples":["consumer staples"],
                "consumer discretionary":["consumer discretionary"],
                "communication services":["communication services","telecommunication"],
            }.get(sec,[sec])
            for a in aliases[:2]:
                if geo: qs.append(f"{geo} {a} sector index")
                qs.append(f"global {a} sector index")
        themes=generic_theme_terms(e)
        for th in themes[:2]:
            qs.extend([
                f"STOXX {th} index",
                f"Solactive {th} index",
            ])
        if p.factor:
            fac=p.factor.replace("_"," ")
            qs.extend([f"MSCI World {fac} index",f"global {fac} factor index"])
    elif p.asset=="bond":
        bucket=_maturity_bucket(p.duration_years or e.maturity_years)
        issuer="government" if p.issuer_type=="government" else "corporate" if p.issuer_type=="corporate" else "aggregate"
        geo_name="Italy" if e.country=="IT" or p.geography=="italy" else ("Euro" if e.currency=="EUR" else (p.geography or "global"))
        if p.bond_style=="inflation_linked":
            qs.extend([f"{geo_name} inflation linked bond index",f"global inflation linked government bond index"])
        qs.extend([
            f"{geo_name} {issuer} bond {bucket} index",
            f"{geo_name} {issuer} bond index",
        ])
    return list(dict.fromkeys(q for q in qs if q))[:4]


def _deep_relative_reference(p,e,inst,cb=None,current=None):
    qs=_deep_relative_queries(p,e)
    if not qs:return current

    target=" ".join(x for x in (
        e.benchmark_name,e.name,e.description,p.geography,p.sector,p.factor,p.size,p.issuer_type,p.bond_style
    ) if x)
    pool={}
    for q in qs:
        for sym,name in lookup_index(q):
            sem=_semantic_gate_from_text(target,name,p,e,sym)
            if sem < .60:continue
            old=pool.get(sym)
            if old is None or sem>old[1]:pool[sym]=(name,sem,q)

    cand=_evaluate_candidate_pool(pool,inst,limit=16)
    if not cand:return current

    best=cand[0]
    current_geom=-1.0
    current_score=-1.0
    if current is not None and current.series is not None:
        current_geom,cn,_=geometry_metrics(inst,current.series)
        csem=max(.45,current.semantic_confidence or current.confidence)
        current_score=current.selection_score or combined_reference_score(csem,current_geom,cn,1.0)

    # A deep same-subdomain relative can replace a weak parent with modest margin;
    # if current geometry <40, any meaningfully better admissible relative wins.
    wins=(
        current is None or current.series is None
        or (current_geom<40 and best["geometry"]>=current_geom+4)
        or (best["geometry"]>=55 and best["score"]>=current_score+3)
        or (best["geometry"]>=current_geom+10 and best["semantic"]>=.65)
    )
    if not wins:return current

    rel=_relation_from_semantic(best["semantic"])
    return Benchmark(
        level="INDEX_CLASS_REFERENCE",provider="YFINANCE",
        official_name=best["name"],provider_id=best["symbol"],
        variant="DEEP_SUBDOMAIN_RELATIVE",currency="",operational_symbol=best["symbol"],
        confidence=min(.96,.58+.34*best["semantic"]),
        observations=len(best["series"]),last_date=str(best["series"].index.max().date()),
        note=f"{rel}: deep subdomain retry after weak first reference; semantic={best['semantic']:.2f}, geometry={best['geometry']:.1f}.",
        series=best["series"],
        reference_components=[{"symbol":best["symbol"],"name":best["name"],"weight_pct":100.0}],
        semantic_confidence=best["semantic"],relation_grade=rel,
        geometry_score=best["geometry"],selection_score=best["score"],
        candidate_count=len(cand),review_status=_review_status(best["n"]),
        next_review_obs=_review_next_obs(best["n"]),candidate_ladder=_candidate_ladder_rows(cand,8)
    )


GEOGRAPHY_REFERENCE_FAMILIES={
    "usa":["^GSPC","^DJI"],"europe":["^STOXX50E","^FTSE","^GDAXI"],"japan":["^N225"],
    "china":["^HSI","000001.SS"],"india":["^BSESN","^NSEI"],"korea":["^KS11"],
    "brazil":["^BVSP"],"italy":["FTSEMIB.MI"],
}
SECTOR_FAMILY={
    "technology":"TECH_GROWTH","energy":"ENERGY","healthcare":"HEALTHCARE","real_estate":"REAL_ESTATE",
    "financials":"FINANCIALS","industrials":"INDUSTRIALS","utilities":"UTILITIES",
    "consumer_staples":"CONSUMER_STAPLES","consumer_discretionary":"CONSUMER_DISCRETIONARY",
    "communication_services":"COMMUNICATION_SERVICES","materials":"MATERIALS","metals_mining":"MATERIALS",
}

def _reference_tiers(p,e):
    tiers=[];geo=p.geography or ""
    if p.asset=="equity":
        if p.theme:
            th=p.theme.replace("_"," ");tiers.append(("THEME",.82,[],[f"{th} index",f"global {th} equity index",f"STOXX {th} index",f"Solactive {th} index"]))
        if p.sector:
            fam=SECTOR_FAMILY.get(p.sector);static=REFERENCE_FAMILIES.get(fam,[]) if fam else [];sec=p.sector.replace("_"," ")
            tiers.append(("SECTOR",.82,static,[f"{geo} {sec} sector index" if geo else "",f"global {sec} sector index",f"developed {sec} equity index"]))
        if p.factor:
            fac=p.factor.replace("_"," ");tiers.append(("FACTOR",.80,[],[f"MSCI World {fac} index",f"global {fac} factor index",f"{geo} {fac} equity index" if geo else ""]))
        if p.size:
            sz=p.size.replace("_"," ");static=REFERENCE_FAMILIES.get("SMALL_CAP",[]) if p.size=="small" else []
            tiers.append(("SIZE",.78,static,[f"{geo} {sz} cap equity index" if geo else "",f"global {sz} cap equity index"]))
        if geo:tiers.append(("GEOGRAPHY",.72,GEOGRAPHY_REFERENCE_FAMILIES.get(geo,[]),[f"{geo} broad equity index",f"{geo} equity index"]))
        if p.geography=="emerging":tiers.append(("EM_PARENT",.70,REFERENCE_FAMILIES.get("EMERGING_EQUITY",[]),["emerging markets equity index"]))
        if p.geo_scope=="regional" and p.geography=="europe":tiers.append(("REGIONAL_PARENT",.68,REFERENCE_FAMILIES.get("EUROPE_EQUITY",[]),["Europe broad equity index"]))
        tiers.append(("GLOBAL_PARENT",.55,REFERENCE_FAMILIES.get("GLOBAL_EQUITY",[]),["global broad equity index"]))
    elif p.asset=="bond":
        bucket=_maturity_bucket(p.duration_years or e.maturity_years);issuer="government" if p.issuer_type=="government" else "corporate" if p.issuer_type=="corporate" else "aggregate"
        country="Italy" if e.country=="IT" or p.geography=="italy" else (p.geography or "")
        if p.bond_style=="inflation_linked":tiers.append(("BOND_STYLE",.82,[],[f"{country} inflation linked government bond {bucket} index" if country else "",f"Euro inflation linked government bond {bucket} index","global inflation linked government bond index"]))
        tiers.append(("BOND_CLOSE",.80,[],[f"{country} {issuer} bond {bucket} index" if country else "",f"Euro {issuer} bond {bucket} index"]))
        tiers.append(("BOND_PARENT",.68,[],[f"Euro {issuer} bond index",f"global {issuer} bond index"]))
    return tiers

def tiered_reference_search(p,e,inst,cb=None,target_role=None):
    target=" ".join(x for x in (e.benchmark_name,e.name,e.description,p.geography,p.sector,p.theme,p.factor,p.size,p.issuer_type,p.bond_style) if x)
    target_role=target_role or role(e,p,ROLE_MIN_PERCENT)
    best_fallback=None;ladder=[]
    for tier_no,(tier_name,base_sem,static_symbols,queries) in enumerate(_reference_tiers(p,e)):
        pool={}
        for sym in static_symbols:
            if domain_compatible(p,e,sym,tier_name):pool[sym]=(tier_name.replace("_"," ").title(),base_sem,"STATIC_FAMILY")
        for q in queries:
            q=" ".join((q or "").split())
            if not q:continue
            for sym,name in lookup_index(q):
                sem=_semantic_gate_from_text(target,name,p,e,sym)
                if sem<.60:continue
                sem=max(sem,base_sem if sem>=.55 else sem)
                old=pool.get(sym)
                if old is None or sem>old[1]:pool[sym]=(name,sem,q)
        cand=_evaluate_candidate_pool_roleaware(pool,inst,p,e,target_role,tier_name,limit=18)

        def _tier_pass(cand_rows):
            if not cand_rows:return False
            bb=cand_rows[0]
            return roleaware_candidate_quality_gate(
                max(base_sem,bb["semantic"]),bb.get("role_similarity",50.0),
                bb["geometry"],bb["n"],tier_name
            )

        # Exhaust the current semantic tier before descending. Search is paid
        # only if Lookup/static candidates are absent or fail the quality gate.
        if not _tier_pass(cand):
            added=False
            for q in [x for x in queries if x][:3]:
                for sym,name in search_index_quotes(q):
                    sem=_semantic_gate_from_text(target,name,p,e,sym)
                    if sem<.60:continue
                    sem=max(sem,base_sem if sem>=.55 else sem)
                    oldrow=pool.get(sym)
                    if oldrow is None or sem>oldrow[1]:
                        pool[sym]=(name,sem,"SEARCH:"+q);added=True
            if added:
                cand=_evaluate_candidate_pool_roleaware(pool,inst,p,e,target_role,tier_name,limit=18)

        if not cand:continue
        for c in cand[:6]:
            ladder.append({"tier":tier_name,"symbol":c["symbol"],"name":c["name"],"relation":_relation_from_semantic(c["semantic"]),
                           "semantic_confidence":round(c["semantic"],4),"geometry_score":round(c["geometry"],2),
                           "role_similarity_score":round(c.get("role_similarity",0.0),2),
                           "candidate_core_pct":round(c.get("candidate_core",0.0),1),
                           "candidate_defensive_pct":round(c.get("candidate_defensive",0.0),1),
                           "candidate_satellite_pct":round(c.get("candidate_satellite",0.0),1),
                           "candidate_structural_type":c.get("candidate_structural_type",""),
                           "selection_score":round(c["score"],2),"common_obs":int(c["n"]),"query":c["query"],"series":c["series"]})
        best=cand[0]
        passed=_tier_pass(cand)
        if passed:
            rel=_relation_from_semantic(max(base_sem,best["semantic"]))
            return Benchmark(level="TIERED_INDEX_REFERENCE",provider="YFINANCE",official_name=best["name"],provider_id=best["symbol"],variant=tier_name,
                currency="",operational_symbol=best["symbol"],confidence=min(.96,.58+.34*max(base_sem,best["semantic"])),
                observations=len(best["series"]),last_date=str(best["series"].index.max().date()),
                note=f"{rel}: tier {tier_name}; geometry ranks only admissible relatives in this tier.",series=best["series"],
                reference_components=[{"symbol":best["symbol"],"name":best["name"],"weight_pct":100.0}],
                semantic_confidence=max(base_sem,best["semantic"]),relation_grade=rel,geometry_score=best["geometry"],
                selection_score=best["score"],candidate_count=len(cand),review_status=_review_status(best["n"]),
                next_review_obs=_review_next_obs(best["n"]),candidate_ladder=ladder[:12],
                role_similarity_score=best["role_similarity"],candidate_role_core=best["candidate_core"],
                candidate_role_defensive=best["candidate_defensive"],candidate_role_satellite=best["candidate_satellite"])
        # Descending in kinship costs points; role compatibility is already
        # inside best["score"].
        penalized=best["score"]-tier_no*7
        if best_fallback is None or penalized>best_fallback[0]:best_fallback=(penalized,tier_name,base_sem,best)
    if best_fallback:
        _,tier_name,base_sem,best=best_fallback;rel=_relation_from_semantic(max(base_sem,best["semantic"]))
        return Benchmark(level="TIERED_INDEX_REFERENCE",provider="YFINANCE",official_name=best["name"],provider_id=best["symbol"],variant=tier_name,
            currency="",operational_symbol=best["symbol"],confidence=min(.90,.55+.30*max(base_sem,best["semantic"])),
            observations=len(best["series"]),last_date=str(best["series"].index.max().date()),note=f"{rel}: best available tiered relative; gate not fully met.",
            series=best["series"],reference_components=[{"symbol":best["symbol"],"name":best["name"],"weight_pct":100.0}],
            semantic_confidence=max(base_sem,best["semantic"]),relation_grade=rel,geometry_score=best["geometry"],selection_score=best["score"],
            candidate_count=1,review_status="FORCED_LOW_FIT" if best["geometry"]<55 else _review_status(best["n"]),
            next_review_obs=_review_next_obs(best["n"]),candidate_ladder=ladder[:12],
            role_similarity_score=best["role_similarity"],candidate_role_core=best["candidate_core"],
            candidate_role_defensive=best["candidate_defensive"],candidate_role_satellite=best["candidate_satellite"])
    return None

def _smart_relative_reference(p,e,inst,cb=None,current=None):
    candidates=_smart_search_candidates(p,e,inst,cb)
    if not candidates:return current
    ladder=_candidate_ladder_rows(candidates,8)

    accepted=None
    for c in candidates:
        if _candidate_quality_gate(c["semantic"],c["geometry"],c["n"]):
            accepted=c;break
    if accepted is None:
        usable=[c for c in candidates if c["n"]>=20]
        accepted=(usable or candidates)[0]

    if current is not None and current.series is not None:
        cgeom,cn,_=geometry_metrics(inst,current.series)
        csem=max(.60,current.semantic_confidence or current.confidence)
        cscore=current.selection_score or combined_reference_score(csem,cgeom,cn,1.0)
        if _candidate_quality_gate(csem,cgeom,cn) and accepted["score"] < cscore+8.0:
            current.candidate_ladder=ladder
            return current

    relation=_relation_from_semantic(accepted["semantic"])
    return Benchmark(
        level="INDEX_CLASS_REFERENCE",provider="YFINANCE",
        official_name=accepted["name"],provider_id=accepted["symbol"],
        variant="SMART_RELATIVE",currency="",operational_symbol=accepted["symbol"],
        confidence=min(.96,.58+.34*accepted["semantic"]),
        observations=len(accepted["series"]),last_date=str(accepted["series"].index.max().date()),
        note=(f"{relation}: selected from {len(candidates)} admissible indices; "
              f"semantic={accepted['semantic']:.2f}, geometry={accepted['geometry']:.1f}."),
        series=accepted["series"],
        reference_components=[{"symbol":accepted["symbol"],"name":accepted["name"],"weight_pct":100.0}],
        semantic_confidence=accepted["semantic"],relation_grade=relation,
        geometry_score=accepted["geometry"],selection_score=accepted["score"],
        candidate_count=len(candidates),review_status=_review_status(accepted["n"]),
        next_review_obs=_review_next_obs(accepted["n"]),candidate_ladder=ladder
    )


def _profile_family_ladder(p,e):
    ladder=[]
    if p.digital_asset:
        return [("PROPRIA",.92,"BITCOIN","digital-asset market reference")]
    if p.gold:
        return [("PROPRIA",.92,"GOLD","physical gold market reference"),
                ("PARENTE",.62,"COMMODITY","broad commodity reference")]
    if p.asset=="commodity":
        return [("CUGINA",.78,"COMMODITY","broad commodity index")]
    if p.asset!="equity":
        return ladder

    if p.sector:
        smap={
            "technology":"TECH_GROWTH","energy":"ENERGY",
            "metals_mining":"MATERIALS","materials":"MATERIALS",
            "healthcare":"HEALTHCARE","real_estate":"REAL_ESTATE",
            "financials":"FINANCIALS","industrials":"INDUSTRIALS",
            "utilities":"UTILITIES","consumer_staples":"CONSUMER_STAPLES",
            "consumer_discretionary":"CONSUMER_DISCRETIONARY",
            "communication_services":"COMMUNICATION_SERVICES",
        }
        fam=smap.get(p.sector)
        if fam:
            ladder.append(("CUGINA",.84,fam,f"same sector family: {p.sector}"))

    if p.breadth=="thematic":
        ladder.append(("CUGINA",.78,"TECH_GROWTH","thematic/growth market reference"))
    if p.size in ("small","ex_mega"):
        ladder.append(("CUGINA",.78,"SMALL_CAP","size-related market reference"))

    if p.factor:
        fam = "USA_EQUITY" if p.geography=="usa" else "EUROPE_EQUITY" if p.geography=="europe" else "GLOBAL_EQUITY"
        ladder.append(("PARENTE",.72,fam,f"broad parent for factor {p.factor}"))

    if p.geography=="usa":
        ladder.append(("PARENTE",.70,"USA_EQUITY","same geography broad equity"))
    elif p.geography=="europe":
        ladder.append(("PARENTE",.70,"EUROPE_EQUITY","same geography broad equity"))
    elif p.geography=="emerging":
        ladder.append(("PARENTE",.68,"EMERGING_EQUITY","emerging-market broad equity"))
    elif p.geography in ("world","global",""):
        ladder.append(("PARENTE",.68,"GLOBAL_EQUITY","global broad equity"))
    elif p.geography=="italy":
        ladder.append(("PARENTE",.70,"EUROPE_EQUITY","regional broad equity"))

    ladder.append(("ZIA LONTANA",.50,"GLOBAL_EQUITY","broad market comparison"))
    seen=set();out=[]
    for row in ladder:
        if row[2] in seen: continue
        seen.add(row[2]);out.append(row)
    return out

def build_reference_always(e,p,inst,cb=None,target_role=None):
    if p.asset=="bond":return None
    target_role=target_role or role(e,p,ROLE_MIN_PERCENT)
    family_candidates=[]
    for grade,sem,family,reason in _profile_family_ladder(p,e):
        syms=REFERENCE_FAMILIES.get(family,[]);hs=yf_history_cached(syms) if syms else {}
        tier=[]
        for sym in syms:
            s=hs.get(sym)
            if s is None or len(s)<SYNTH_MIN_OBS:continue
            geom,n,_=geometry_metrics(inst,s)
            sig=candidate_role_signature(family,sym,"FAMILY",p,e,family=family)
            rs=role_similarity_score(target_role,sig["role"])
            total=roleaware_reference_score(sem,rs,geom,n,1.0)
            row=(total,geom,n,grade,sem,family,reason,sym,s,rs,sig);family_candidates.append(row);tier.append(row)
        good=[x for x in tier if roleaware_candidate_quality_gate(x[4],x[9],x[1],x[2],"FAMILY")]
        if good:
            good.sort(reverse=True,key=lambda x:x[0]);total,geom,n,grade,conf,family,reason,sym,s,rs,sig=good[0]
            return Benchmark(level="MARKET_REFERENCE" if family in ("GOLD","BITCOIN") else "INDEX_CLASS_REFERENCE",
                provider="YFINANCE",official_name=f"Reference: {family.replace('_',' ').title()}",provider_id=sym,variant="NON_ETF_COMPARATOR",
                currency="",operational_symbol=sym,confidence=conf,observations=len(s),last_date=str(s.index.max().date()),
                note=f"{grade}: {reason}. Same-family candidate before broad lookup.",series=s,
                reference_components=[{"symbol":sym,"name":family,"weight_pct":100.0}],semantic_confidence=conf,relation_grade=grade,
                geometry_score=geom,selection_score=total,candidate_count=len(family_candidates),review_status=_review_status(n),next_review_obs=_review_next_obs(n),
                role_similarity_score=rs,candidate_role_core=sig["core"],candidate_role_defensive=sig["defensive"],candidate_role_satellite=sig["satellite"])
    qs=[]
    if e.benchmark_name:qs.append(e.benchmark_name)
    if e.benchmark_code:qs.append(e.benchmark_code)
    semantic=[x.replace("_"," ") for x in (p.geography,p.sector,p.theme,p.factor,p.size) if x]
    if semantic:qs.append(" ".join(semantic+["index"]))
    found=_lookup_best_index(qs,e,inst,.20,8)
    if found:
        total,geom,n,semantic_score,sim,sym,name,s,cand_count=found;conf=min(.94,.62+.25*semantic_score+.10*min(1,n/180))
        return Benchmark(level="SINGLE_REFERENCE_INDEX",provider="YFINANCE",official_name=f"Reference Index: {name}",provider_id=sym,
            variant="YAHOO_INDEX_REFERENCE",currency="",operational_symbol=sym,confidence=conf,observations=len(s),last_date=str(s.index.max().date()),
            note="Generic lookup used only after same-family ladder.",series=s,reference_components=[{"symbol":sym,"name":name,"weight_pct":100.0}],
            semantic_confidence=semantic_score,relation_grade="CUGINA" if semantic_score<.85 else "QUASI PROPRIA",geometry_score=geom,
            selection_score=total,candidate_count=cand_count,review_status=_review_status(n),next_review_obs=_review_next_obs(n))
    if family_candidates:
        family_candidates.sort(reverse=True,key=lambda x:x[0]);total,geom,n,grade,conf,family,reason,sym,s,rs,sig=family_candidates[0]
        return Benchmark(level="MARKET_REFERENCE" if family in ("GOLD","BITCOIN") else "INDEX_CLASS_REFERENCE",provider="YFINANCE",
            official_name=f"Reference: {family.replace('_',' ').title()}",provider_id=sym,variant="NON_ETF_COMPARATOR",currency="",operational_symbol=sym,
            confidence=conf,observations=len(s),last_date=str(s.index.max().date()),note=f"{grade}: best same-family fallback.",series=s,
            reference_components=[{"symbol":sym,"name":family,"weight_pct":100.0}],semantic_confidence=conf,relation_grade=grade,geometry_score=geom,
            selection_score=total,candidate_count=len(family_candidates),review_status="FORCED_LOW_FIT" if geom<55 else _review_status(n),next_review_obs=_review_next_obs(n),
            role_similarity_score=rs,candidate_role_core=sig["core"],candidate_role_defensive=sig["defensive"],candidate_role_satellite=sig["satellite"])
    return None


def _normalize_weights(weights):
    w={k:max(0.0,float(v)) for k,v in weights.items() if v is not None and float(v)>0}
    s=sum(w.values())
    return {k:v/s for k,v in w.items()} if s>0 else {}

def _composite_from_series(parts):
    """
    parts = [(name, weight, Series, symbol)]
    Build a daily-return composite; weights come from asset mix, never from curve fitting.
    """
    valid=[x for x in parts if x[2] is not None and len(x[2])>=SYNTH_MIN_OBS and x[1]>0]
    if not valid:return None
    frame=pd.concat([clean_series(x[2]).rename(x[0]) for x in valid],axis=1,join="outer").sort_index().ffill().dropna()
    if len(frame)<SYNTH_MIN_OBS:return None
    weights=_normalize_weights({x[0]:x[1] for x in valid})
    rets=frame.pct_change().fillna(0.0)
    cr=pd.Series(0.0,index=frame.index)
    for name,w in weights.items():
        cr=cr+rets[name]*w
    level=(1.0+cr).cumprod()*100.0
    comps=[]
    for name,w,s,symbol in valid:
        if name in weights:
            comps.append({"name":name,"symbol":symbol,"weight_pct":round(weights[name]*100,1)})
    return clean_series(level),comps

def _round5_pair(eq_weight):
    eq=max(0.05,min(0.95,float(eq_weight)))
    eq5=round(eq*20)/20.0
    eq5=max(.05,min(.95,eq5))
    return eq5,1.0-eq5

def build_composite_reference(e,p,instrument_series=None,cb=None):
    """
    MAX TWO components. Percentages always in 5% steps.
    Structure determines the neighbourhood; geometry selects the best admissible pair.
    No regression and no pharmaceutical-style multi-leg cocktail.
    """
    eq,bd,ca,ot=mix(e)
    if p.asset!="multiasset" and not (eq>=.10 and bd>=.10):
        return None

    if eq+bd+ca < .50:
        base_eq=.55
        mix_conf=.52
        mix_note="allocation incomplete; neutral structural estimate"
    else:
        # cash is merged into the defensive leg
        total=max(1e-9,eq+bd+ca)
        base_eq=eq/total
        mix_conf=.84
        mix_note="equity vs defensive structure from current allocation"

    eq0,def0=_round5_pair(base_eq)
    # geometry may refine only +/-5%, never invent a distant mix.
    weights=sorted(set(max(.05,min(.95,x)) for x in (eq0-.05,eq0,eq0+.05)))

    eq_symbols=REFERENCE_FAMILIES["GLOBAL_EQUITY"] + REFERENCE_FAMILIES["USA_EQUITY"][:1]
    eq_hist=yf_history_cached(list(dict.fromkeys(eq_symbols)))

    # defensive candidates: one generic bond curve + €STR. Only ONE defensive leg in final pair.
    defensive=[]
    pp=Profile(asset="bond",issuer_type="aggregate",duration_years=4.0,duration_confidence=.45)
    bb=bond_synthetic(e,pp,cb)
    if bb and bb.series is not None:
        defensive.append(("EUR Bond D4",bb.operational_symbol or bb.provider_id,bb.series))
    rr=estr()
    cs=compound_rate(rr,0.0) if rr is not None else None
    if cs is not None:
        defensive.append(("€STR","€STR",cs))

    candidates=[]
    for ew in weights:
        dw=1.0-ew
        for esym,eser in eq_hist.items():
            if eser is None or len(eser)<SYNTH_MIN_OBS:continue
            for dname,dsym,dser in defensive:
                built=_composite_from_series([
                    ("Equity",ew,eser,esym),
                    ("Defensive",dw,dser,dsym)
                ])
                if not built:continue
                series,components=built
                geom,n,_=geometry_metrics(instrument_series,series)
                # structural proximity penalty for moving +/-5%
                dist=abs(ew-eq0)
                semantic=max(.60,mix_conf-.80*dist)
                total=combined_reference_score(semantic,geom,n,1.0)
                candidates.append((total,geom,n,semantic,ew,esym,dname,dsym,series,components))
    if not candidates:return None
    candidates.sort(reverse=True,key=lambda x:x[0])
    total,geom,n,semantic,ew,esym,dname,dsym,series,components=candidates[0]
    dw=1.0-ew
    label=f"{ew*100:.0f}% {esym} + {dw*100:.0f}% {dname} ({dsym})"
    return Benchmark(
        level="COMPOSITE_REFERENCE",provider="COMPOSITE",
        official_name=label,provider_id=label,
        variant="TWO_LEG_5PCT_REFERENCE",currency=e.currency or "EUR",operational_symbol="COMPOSITE",
        confidence=min(.94,.58+.25*semantic+.08*min(1.0,n/180.0)),
        observations=len(series),last_date=str(series.index.max().date()),
        components=label,
        note=(f"Two-leg composite; {mix_note}. Max 2 indices/curves; weights in 5% steps. "
              "Geometry may refine the structural allocation only by ±5%."),
        series=series,reference_components=components,semantic_confidence=semantic,
        relation_grade="PROPRIA STRUTTURALE" if semantic>=.80 else "PARENTE",
        geometry_score=geom,selection_score=total,candidate_count=len(candidates),
        review_status=_review_status(n),next_review_obs=_review_next_obs(n)
    )


# ---------------- resolver ----------------

def _domain_role_series(role_name,e,p,cb=None):
    d=economic_domain(p,e); fam=_domain_family(d)
    role_name=role_name.lower()

    if d=="gold":
        sym,s=_download_first_available(["GC=F"])
        return ("Gold market",sym,s) if s is not None else None
    if d=="digital_asset":
        sym,s=_download_first_available(["BTC-USD"])
        return ("Bitcoin market",sym,s) if s is not None else None
    if d=="commodity":
        sym,s=_download_first_available(["^BCOM","^SPGSCI"])
        return ("Broad commodity",sym,s) if s is not None else None
    if d=="cash":
        r=estr();s=compound_rate(r,0.0) if r is not None else None
        return ("€STR","€STR",s) if s is not None else None

    if fam=="bond":
        # Every leg remains a BOND leg. Satellite means specialised bond risk,
        # not Nasdaq or equity.
        dur=p.duration_years or 4.0
        if role_name=="defensive":
            pp=Profile(asset="bond",issuer_type="government",duration_years=max(.5,min(3.0,dur)),duration_confidence=.4)
            b=sovereign_synthetic(e,pp,cb)
        elif role_name=="satellite":
            pp=Profile(asset="bond",issuer_type=p.issuer_type or "aggregate",
                       duration_years=max(2.0,dur),duration_confidence=.4,bond_style=p.bond_style)
            b=bond_synthetic(e,pp,cb)
        else:
            pp=Profile(asset="bond",issuer_type=p.issuer_type or "aggregate",
                       duration_years=dur,duration_confidence=.4,bond_style=p.bond_style)
            b=sovereign_synthetic(e,pp,cb) if p.issuer_type=="government" else bond_synthetic(e,pp,cb)
        if b and b.series is not None:return (f"{role_name.title()} bond",b.operational_symbol or b.provider_id,b.series)
        return None

    if fam=="equity":
        if p.sector=="energy":
            syms=["^GSPE","^GSPC"]
        elif p.sector=="healthcare":
            syms=["^SP500-35","^GSPC"]
        elif p.sector=="real_estate":
            syms=["^DJUSRE","^SP500-60","^GSPC"]
        elif p.sector in ("materials","metals_mining"):
            syms=["^SP500-15","^GSPC"]
        elif p.factor=="minimum_volatility":
            syms=["^DJI","^GSPC","^STOXX50E"]
        elif p.geography=="japan":
            syms=["^N225","^GSPC"]
        elif p.geography=="china":
            syms=["^HSI","000001.SS","^GSPC"]
        elif p.geography=="europe":
            syms=["^STOXX50E","^FTSE","^GDAXI","^GSPC"]
        else:
            syms=["^GSPC","^DJI","^IXIC"]
        sym,s=_download_first_available(syms)
        return (f"{role_name.title()} equity",sym,s) if s is not None else None
    return None

def _mixed_role_composite(e,p,inst,rolefit,cb=None):
    # Cross-domain composite is allowed ONLY for true multi-asset instruments.
    vals={"core":rolefit.core,"defensive":rolefit.defensive,"satellite":rolefit.satellite}
    active=sorted([(k,v) for k,v in vals.items() if v>0],key=lambda x:x[1],reverse=True)[:2]
    if len(active)<2:return None
    tot=sum(v for _,v in active)
    w1=round((active[0][1]/tot)*20)/20.0
    w1=max(.05,min(.95,w1));w2=1.0-w1

    if p.asset=="multiasset":
        # existing economic two-leg multi-asset builder is preferred elsewhere;
        # here use broad role legs.
        r1=_domain_role_series("core",e,Profile(asset="equity",geography=p.geography),cb)
        r2=_domain_role_series("defensive",e,Profile(asset="bond",issuer_type="aggregate",duration_years=4.0),cb)
    else:
        # Same economic domain for BOTH legs.
        r1=_domain_role_series(active[0][0],e,p,cb)
        r2=_domain_role_series(active[1][0],e,p,cb)
    if r1 is None or r2 is None:return None
    if r1[1]==r2[1]:
        ser=clean_series(r1[2])
        if ser is None:return None
        geom,n,_=geometry_metrics(inst,ser)
        return Benchmark(level="INDEX_CLASS_REFERENCE",provider="YFINANCE",official_name=r1[0],provider_id=r1[1],operational_symbol=r1[1],
                         confidence=.65,observations=len(ser),last_date=str(ser.index.max().date()),series=ser,semantic_confidence=.65,
                         relation_grade="SINGLE_DOMAIN_COLLAPSE",geometry_score=geom,selection_score=combined_reference_score(.65,geom,n,1.0),
                         note="Duplicate composite legs collapsed to one economic reference.")
    built=_composite_from_series([
        (active[0][0].title(),w1,r1[2],r1[1]),
        (active[1][0].title(),w2,r2[2],r2[1]),
    ])
    if not built:return None
    series,components=built
    geom,n,_=geometry_metrics(inst,series)
    label=f"{w1*100:.0f}% {r1[0]} ({r1[1]}) + {w2*100:.0f}% {r2[0]} ({r2[1]})"
    return Benchmark(
        level="ROLE_COMPOSITE_REFERENCE",provider="COMPOSITE",official_name=label,provider_id=label,
        variant="DOMAIN_LOCKED_TWO_ROLE_5PCT",currency=e.currency or "EUR",operational_symbol="COMPOSITE",
        confidence=.68,observations=len(series),last_date=str(series.index.max().date()),
        components=label,note=f"Domain-locked two-leg composite ({economic_domain(p,e)}).",
        series=series,reference_components=components,semantic_confidence=.70,
        relation_grade="NONNA COMPOSITA",geometry_score=geom,
        selection_score=combined_reference_score(.70,geom,n,1.0),candidate_count=2,
        review_status=_review_status(n),next_review_obs=_review_next_obs(n),
        candidate_ladder=[
            {"symbol":r1[1],"name":r1[0],"relation":"NONNA","semantic_confidence":.70,
             "geometry_score":round(geometry_metrics(inst,r1[2])[0],2),"selection_score":0.0,
             "common_obs":geometry_metrics(inst,r1[2])[1],"query":"domain grandmother","series":r1[2]},
            {"symbol":r2[1],"name":r2[0],"relation":"NONNA","semantic_confidence":.70,
             "geometry_score":round(geometry_metrics(inst,r2[2])[0],2),"selection_score":0.0,
             "common_obs":geometry_metrics(inst,r2[2])[1],"query":"domain grandmother","series":r2[2]},
        ]
    )


def _unknown_market_fallback(e,p,inst,cb=None):
    candidates=[]
    for label,sym in (
        ("Broad equity","^GSPC"),("Broad Europe equity","^STOXX50E"),
        ("Broad commodity","^BCOM"),("Gold","GC=F"),("Bitcoin","BTC-USD")
    ):
        s=yf_history_cached([sym]).get(sym)
        if s is not None:
            g,n,_=geometry_metrics(inst,s);candidates.append((g,n,label,sym,s))
    try:
        bp=Profile(asset="bond",issuer_type="aggregate",duration_years=4.0,duration_confidence=.25)
        bb=bond_synthetic(e,bp,cb)
        if bb and bb.series is not None:
            g,n,_=geometry_metrics(inst,bb.series);candidates.append((g,n,"Broad EUR bond",bb.operational_symbol or bb.provider_id,bb.series))
    except Exception:pass
    try:
        rr=estr();cs=compound_rate(rr,0.0) if rr is not None else None
        if cs is not None:
            g,n,_=geometry_metrics(inst,cs);candidates.append((g,n,"EUR cash / €STR","€STR",cs))
    except Exception:pass
    if not candidates:return None
    candidates.sort(reverse=True,key=lambda x:(x[0],x[1]))
    g,n,label,sym,s=candidates[0]
    return Benchmark(
        level="UNKNOWN_MARKET_GRANDMOTHER",provider="MARKET_FALLBACK",
        official_name=label,provider_id=sym,operational_symbol=sym,
        confidence=.25,observations=len(s),last_date=str(s.index.max().date()),
        series=s,semantic_confidence=.20,relation_grade="NONNA DI MERCATO",
        geometry_score=g,selection_score=max(20.0,g*.75),candidate_count=len(candidates),
        review_status="FORCED_UNKNOWN_DOMAIN",next_review_obs=_review_next_obs(n),
        note="Unknown-domain economic fallback selected by visual geometry from broad real-market families."
    )

def _emergency_baseline(inst,days=280):
    """
    Absolute technical last resort. It is NOT a market benchmark.
    It exists solely to honour the invariant: the UI never returns without a curve.
    """
    si=clean_series(inst)
    if si is not None and len(si)>=2:
        idx=si.index
    else:
        idx=pd.bdate_range(end=pd.Timestamp.today().normalize(),periods=days)
    # Flat Base-100 comparator. Explicitly low confidence.
    return pd.Series(100.0,index=idx,dtype=float)

def _mandatory_last_resort(e,p,inst,rolefit=None,cb=None):
    d=economic_domain(p,e)

    # Domain grandmother first.
    preferred_role = (
        "defensive" if _domain_family(d)=="bond"
        else "satellite" if d in ("commodity","digital_asset")
        else "core"
    )
    single=_domain_role_series(preferred_role,e,p,cb)
    if single is not None and clean_series(single[2]) is not None:
        ser=clean_series(single[2])
        geom,n,_=geometry_metrics(inst,ser)
        return Benchmark(
            level="FORCED_GRANDMOTHER",provider="YFINANCE/ECB",
            official_name=single[0],provider_id=single[1],operational_symbol=single[1],
            confidence=.45,observations=len(ser),last_date=str(ser.index.max().date()),
            series=ser,semantic_confidence=.55,relation_grade="NONNA FORZATA",
            geometry_score=geom,selection_score=combined_reference_score(.55,geom,n,1.0),
            review_status="FORCED_LOW_FIT" if geom<55 else _review_status(n),
            next_review_obs=_review_next_obs(n),
            note=f"Forced domain grandmother: {d}. Never blank."
        )

    # Composite only for genuine multi-asset economic sleeves.
    if p.asset=="multiasset" and rolefit is not None:
        c=_mixed_role_composite(e,p,inst,rolefit,cb)
        if c is not None and clean_series(c.series) is not None:
            if c.geometry_score<55:c.review_status="FORCED_LOW_FIT"
            return c

    # Before a flat technical line, use the closest REAL broad market family.
    real_unknown=_unknown_market_fallback(e,p,inst,cb)
    if real_unknown is not None:return real_unknown

    # Absolute emergency baseline: only if even broad public market curves failed.
    ser=_emergency_baseline(inst)
    return Benchmark(
        level="EMERGENCY_BASELINE",provider="INTERNAL",
        official_name=f"Emergency {d or 'generic'} baseline",
        provider_id="BASE100-EMERGENCY",operational_symbol="BASE100-EMERGENCY",
        confidence=.10,observations=len(ser),last_date=str(ser.index.max().date()),
        series=ser,semantic_confidence=.10,relation_grade="NONNA TECNICA",
        geometry_score=geometry_metrics(inst,ser)[0],
        selection_score=10.0,review_status="EMERGENCY_REPLACE_ASAP",
        next_review_obs=20,
        note="Technical emergency baseline used only because every external/domain reference failed."
    )


def implied_index_name(e):
    text=_richer_text(e.name,e.benchmark_name)
    if not text:return ""
    m=re.search(r"\b(MSCI|FTSE|STOXX|S&P|NASDAQ|RUSSELL|SOLACTIVE)\b(.+)",text,re.I)
    if not m:return ""
    candidate=(m.group(1)+" "+m.group(2)).strip()
    candidate=re.split(r"\b(?:UCITS|ETF|ETC|ETP|ACC|DIST|DISTRIBUTING|ACCUMULATING)\b",candidate,flags=re.I)[0]
    return re.sub(r"\s+"," ",candidate).strip(" -|")

def implied_index_reference(e,p,inst,target_role=None):
    q=implied_index_name(e)
    if not q:return None
    pool={}
    for sym,name in lookup_index(q):
        if not domain_compatible(p,e,sym,name):continue
        sim=similarity(q,name)
        if sim<.55:continue
        sem=max(.72,min(.96,.65+.30*sim));pool[sym]=(name,sem,q)
    target_role=target_role or role(e,p,ROLE_MIN_PERCENT)
    cand=_evaluate_candidate_pool_roleaware(pool,inst,p,e,target_role,"IMPLIED",limit=10)
    if not cand:return None
    best=cand[0]
    if best["n"]>=20 and best["semantic"]>=.78:
        return Benchmark(level="IMPLIED_INDEX_REFERENCE",provider="YFINANCE",official_name=best["name"],provider_id=best["symbol"],
            variant="PRODUCT_NAME_INDEX_IDENTITY",currency="",operational_symbol=best["symbol"],confidence=min(.95,best["semantic"]),
            observations=len(best["series"]),last_date=str(best["series"].index.max().date()),
            note=f"Index identity extracted generically from product name: {q}.",series=best["series"],
            reference_components=[{"symbol":best["symbol"],"name":best["name"],"weight_pct":100.0}],
            semantic_confidence=best["semantic"],relation_grade="QUASI PROPRIA",geometry_score=best["geometry"],
            selection_score=best["score"],candidate_count=len(cand),review_status=_review_status(best["n"]),
            role_similarity_score=best["role_similarity"],candidate_role_core=best["candidate_core"],
            candidate_role_defensive=best["candidate_defensive"],candidate_role_satellite=best["candidate_satellite"],
            next_review_obs=_review_next_obs(best["n"]),candidate_ladder=_candidate_ladder_rows(cand,8))
    return None

def resolve(e,p,inst,cb=None,target_role=None):
    log(cb,f"{e.ticker or e.isin}: benchmark cascade")
    target_role=target_role or role(e,p,ROLE_MIN_PERCENT)

    # 0 own-market references for explicit alternative assets.
    # These are economically direct, non-ETF references and need no broad fallback.
    if p.gold:
        s=yf_history_cached(["GC=F"]).get("GC=F")
        if s is not None:
            g,n,_=geometry_metrics(inst,s)
            return Benchmark(
                level="MARKET_REFERENCE",provider="YFINANCE",
                official_name="Reference: Gold",provider_id="GC=F",
                variant="DIRECT_MARKET_REFERENCE",currency="USD",operational_symbol="GC=F",
                confidence=.92,observations=len(s),last_date=str(s.index.max().date()),
                note="PROPRIA: physical gold direct market reference.",
                series=s,reference_components=[{"symbol":"GC=F","name":"GOLD","weight_pct":100.0}],
                semantic_confidence=.92,relation_grade="PROPRIA",
                geometry_score=g,selection_score=combined_reference_score(.92,g,n,1.0),
                candidate_count=1,review_status=_review_status(n),next_review_obs=_review_next_obs(n)
            )
    if p.digital_asset:
        s=yf_history_cached(["BTC-USD"]).get("BTC-USD")
        if s is not None:
            g,n,_=geometry_metrics(inst,s)
            return Benchmark(
                level="MARKET_REFERENCE",provider="YFINANCE",
                official_name="Reference: Bitcoin",provider_id="BTC-USD",
                variant="DIRECT_MARKET_REFERENCE",currency="USD",operational_symbol="BTC-USD",
                confidence=.92,observations=len(s),last_date=str(s.index.max().date()),
                note="PROPRIA: digital-asset direct market reference.",
                series=s,reference_components=[{"symbol":"BTC-USD","name":"BITCOIN","weight_pct":100.0}],
                semantic_confidence=.92,relation_grade="PROPRIA",
                geometry_score=g,selection_score=combined_reference_score(.92,g,n,1.0),
                candidate_count=1,review_status=_review_status(n),next_review_obs=_review_next_obs(n)
            )

    # 1 exact seed catalog
    ranked=sorted(((identity_score(i,e),i) for i in BENCHMARK_IDENTITIES),key=lambda x:-x[0])
    if ranked and ranked[0][0]>=.48:
        sc,i=ranked[0]
        if i.provider=="MSCI":
            s=msci_levels(i.provider_id,i.variant or "NETR",i.currency or "USD")
            if s is not None and len(s)>=SYNTH_MIN_OBS:
                return Benchmark("EXACT_PROVIDER","MSCI",i.official_name,i.provider_id,i.variant,i.currency,"",
                                 min(.99,.88+.11*sc),len(s),str(s.index.max().date()),None,"","MSCI Direct.",s)
        if i.kind=="RATE_COMPOUND":
            r=estr();spread=8.5
            s=compound_rate(r,spread) if r is not None else None
            if s is not None and len(s)>=SYNTH_MIN_OBS:
                return Benchmark("EXACT_PROVIDER","ECB",i.official_name,i.provider_id,"RATE_COMPOUND","EUR","",
                                 .99,len(s),str(s.index.max().date()),None,"","ECB €STR + spread.",s)
        if i.provider=="NASDAQ":
            s=nasdaq_history(i.provider_id)
            if s is not None and len(s)>=SYNTH_MIN_OBS:
                return Benchmark("EXACT_PROVIDER","NASDAQ",i.official_name,i.provider_id,i.variant,i.currency,"",
                                 .96,len(s),str(s.index.max().date()),None,"","Nasdaq official history.",s)

    provider=infer_provider(e.benchmark_name,e.benchmark_code)

    # 2 generic MSCI recovery
    if provider=="MSCI" and e.benchmark_name:
        log(cb,"   MSCI discovery online")
        code,sim,cname=discover_msci(e.benchmark_name,e.benchmark_code)
        if code and sim>=.40:
            s=msci_levels(code,"NETR","USD")
            if s is not None and len(s)>=SYNTH_MIN_OBS:
                return Benchmark("EXACT_PROVIDER_DISCOVERED","MSCI",cname or e.benchmark_name,code,"NETR","USD","",
                                 min(.97,.76+.21*sim),len(s),str(s.index.max().date()),None,"",
                                 f"MSCI numeric code discovered generically; sim={sim:.2f}.",s)

    # 3 generic Nasdaq recovery
    if provider=="NASDAQ" and e.benchmark_code:
        s=nasdaq_history(e.benchmark_code)
        if s is not None and len(s)>=SYNTH_MIN_OBS:
            return Benchmark("EXACT_PROVIDER_DISCOVERED","NASDAQ",e.benchmark_name,e.benchmark_code,"INDEX_LEVEL","USD","",
                             .94,len(s),str(s.index.max().date()),None,"","Nasdaq official history.",s)

    # 3B generic provider exact/alternative INDEX recovery.
    # Applies to any provider identity; never ETF.
    if provider:
        alt=recover_provider_exact_alt(provider,e,inst)
        if alt is not None:
            return alt

    # 3C explicit index identity embedded in the product name.
    implied=implied_index_reference(e,p,inst,target_role)
    if implied is not None:return implied

    # 4 exact Yahoo INDEX only
    pool={}
    for q in (e.benchmark_code,e.benchmark_name):
        if not q:continue
        for sym,name in lookup_index(q):
            sim=similarity(e.benchmark_name,name) if e.benchmark_name else 0
            if sim>=.50:pool[sym]=(name,sim)
    h=yahoo_download(list(pool))
    viable=[]
    for sym,(name,sim) in pool.items():
        if sym in h and len(h[sym])>=SYNTH_MIN_OBS:
            viable.append((sim,sym,name,h[sym]))
    if viable:
        viable.sort(reverse=True);sim,sym,name,s=viable[0]
        return Benchmark("EXACT_YAHOO_INDEX","YAHOO",e.benchmark_name or name,e.benchmark_code,"INDEX_LEVEL","",sym,
                         min(.96,.72+.24*sim),len(s),str(s.index.max().date()),None,"",
                         f"Yahoo INDEX identity candidate; semantic={sim:.2f}.",s)

    # 4C multi-asset composite reference: asset allocation decides the weights.
    comp=build_composite_reference(e,p,inst,cb)
    if comp is not None:
        return comp

    # 5 relation tiers. Real indices precede synthetic bond curves.
    tiered=tiered_reference_search(p,e,inst,cb,target_role)
    if tiered is not None:
        n=geometry_metrics(inst,tiered.series)[1] if inst is not None else 0
        if n<20 or _candidate_quality_gate(max(.60,tiered.semantic_confidence),tiered.geometry_score,n):
            return tiered

    b=sovereign_synthetic(e,p,cb)
    if b:return b
    b=bond_synthetic(e,p,cb)
    if b:return b

    # POC7 primitive reference graph.
    # If the official series was unavailable, build a robust non-ETF reference.
    ref=build_reference_always(e,p,inst,cb,target_role)
    if ref is not None:
        return ref

    # 6 best tiered fallback if no synthetic/reference route was superior.
    if tiered is not None:return tiered

    # 7 market references, still no ETF
    if p.gold:
        s=yahoo_download(["GC=F"]).get("GC=F")
        if s is not None:return Benchmark("MARKET_REFERENCE","YAHOO",e.benchmark_name or "Gold market reference",
                                          "","FUTURE_REFERENCE","USD","GC=F",.62,len(s),str(s.index.max().date()),
                                          None,"","LBMA history licensed; COMEX future used only as non-ETF reference.",s)
    if p.digital_asset:
        s=yahoo_download(["BTC-USD"]).get("BTC-USD")
        if s is not None:return Benchmark("MARKET_REFERENCE","YAHOO",e.benchmark_name or "Bitcoin market reference",
                                          "","SPOT_REFERENCE","USD","BTC-USD",.70,len(s),str(s.index.max().date()),
                                          None,"","Non-ETF spot/reference asset.",s)

    # Absolute last-resort comparator: a broad curve is more useful than identity-only.
    if p.asset in ("equity","commodity") or p.digital_asset or p.gold:
        sym,s=_download_first_available(["^GSPC","^STOXX50E","^IXIC"])
        if s is not None:
            return Benchmark(
                level="INDEX_CLASS_REFERENCE",provider="YFINANCE",
                official_name="Reference: broad market comparator",provider_id=sym,
                variant="LAST_RESORT_COMPARATOR",currency="",operational_symbol=sym,
                confidence=.38,observations=len(s),last_date=str(s.index.max().date()),
                note="ZIA LONTANA: broad non-ETF market curve used only as last-resort comparator.",
                series=s,semantic_confidence=.38,relation_grade="ZIA LONTANA"
            )

    # Identity remains only if even the last operational comparison curve fails.
    return Benchmark(
        level="IDENTITY_ONLY" if (e.benchmark_name or e.benchmark_code or provider) else "NO_PUBLIC_SERIES",
        provider=provider,
        official_name=e.benchmark_name,
        provider_id=e.benchmark_code,
        variant="",
        currency="",
        operational_symbol="",
        confidence=0.55 if (e.benchmark_name and provider) else (0.40 if e.benchmark_name else 0.0),
        observations=0,
        last_date="",
        target_duration=None,
        components="",
        note=(
            "Official benchmark identity retained; no acceptable public series was "
            "retrieved in this run. No ETF proxy used."
            if e.benchmark_name
            else "All provider/index/synthetic non-ETF routes failed."
        ),
        series=None,
    )


def enrich_ambiguous_identity(e,p):
    """
    Cheap second-pass identity recovery only for weak profiles.
    Uses existing caches first; network is paid only for ambiguous cases.
    """
    if p.confidence>=.78 and structural_type(p)!="UNKNOWN":
        return False
    changed=False

    # Search the resolved Yahoo symbol itself for a descriptive long name.
    sym=e.yahoo_symbol or e.ticker
    if sym:
        try:
            rows=[q for q in (getattr(yf.Search(sym,max_results=6),"quotes",None) or []) if isinstance(q,dict)]
            for q in rows:
                if norm(q.get("symbol")).upper()==sym.upper():
                    nm=norm(q.get("longname") or q.get("shortname") or q.get("name"))
                    if nm and len(tokens(nm))>len(tokens(e.name)):
                        e.name=nm;changed=True
                    break
        except Exception:
            pass

    # Borsa is queried only for unresolved Italian-listed ETF/ETC/ETP identities.
    if e.isin and e.instrument_type in ("ETF","ETC","ETP") and not e.benchmark_name:
        try:
            bx=borsa_etf(e.isin)
            bn=norm(bx.get("benchmark_name"))
            if bn:
                e.benchmark_name=bn;changed=True
            e.benchmark_code=e.benchmark_code or norm(bx.get("benchmark_code"))
            e.benchmark_area=e.benchmark_area or norm(bx.get("benchmark_area"))
            e.currency=e.currency or norm(bx.get("currency"))
            if "Borsa Italiana" not in e.sources:e.sources.append("Borsa Italiana")
        except Exception:
            pass
    return changed


def _benchmark_domain_hint(b):
    text=f" {ascii_text(' '.join(x for x in (b.official_name,b.note,b.operational_symbol,b.provider_id) if x))} "
    sym=(b.operational_symbol or b.provider_id or "").upper()
    if sym=="GC=F" or " gold " in text:return "gold"
    if sym=="BTC-USD" or " bitcoin " in text:return "digital_asset"
    if " bond " in text or "synth-d" in text or " sovereign " in text:return "bond"
    if any(x in text for x in (" equity "," s&p "," stoxx "," msci "," nasdaq "," ftse ")):return "equity"
    if " commodity " in text or "spgsci" in text or "bcom" in text:return "commodity"
    if "estr" in text or " cash " in text:return "cash"
    return ""


def reconcile_profile_with_reference(e,p,b,c):
    """
    Reference is a second opinion ONLY when profile is weak/UNKNOWN.
    It cannot override a strong profile.
    """
    if structural_type(p)!="UNKNOWN" and p.confidence>=.78:
        return p,False
    hint=_benchmark_domain_hint(b)
    strong_curve=(c.trend>=82 and (b.geometry_score>=55 or b.level in ("EXACT_PROVIDER","EXACT_ALTERNATIVE_INDEX")))
    if not hint or not strong_curve:
        return p,False

    p2=profile(e)
    if hint=="gold":
        p2.asset="commodity";p2.gold=True;p2.digital_asset=False
        p2.confidence=max(p2.confidence,.90)
        p2.reasons.append("Second opinion: strong Gold reference confirms commodity/gold domain.")
    elif hint=="digital_asset":
        p2.asset="digital_asset";p2.digital_asset=True;p2.gold=False
        p2.confidence=max(p2.confidence,.90)
        p2.reasons.append("Second opinion: strong Bitcoin reference confirms digital-asset domain.")
    elif hint=="bond" and not p2.asset:
        p2.asset="bond";p2.confidence=max(p2.confidence,.80)
        p2.reasons.append("Second opinion: strong bond reference confirms bond domain.")
    elif hint=="equity" and not p2.asset:
        p2.asset="equity";p2.breadth=p2.breadth or "broad";p2.confidence=max(p2.confidence,.80)
        p2.reasons.append("Second opinion: strong equity reference confirms equity domain.")
    elif hint=="cash" and not p2.asset:
        p2.asset="cash";p2.confidence=max(p2.confidence,.85)
        p2.reasons.append("Second opinion: strong cash reference confirms money-market domain.")
    else:
        return p,False
    p2.completeness=max(p2.completeness,.50)
    return p2,True


def benchmark_role_telemetry(b,p,e,target_role):
    if b is None:return 50.0,0.0,0.0,0.0
    if b.role_similarity_score>0:
        return (b.role_similarity_score,b.candidate_role_core,b.candidate_role_defensive,b.candidate_role_satellite)

    # Direct / exact / fallback references: infer locally from the final identity.
    tier=b.variant if b.variant in ("THEME","SECTOR","FACTOR","SIZE","GEOGRAPHY","EM_PARENT","REGIONAL_PARENT","GLOBAL_PARENT","BOND_STYLE","BOND_CLOSE","BOND_PARENT") else ""
    family=""
    if b.reference_components:
        family=norm(b.reference_components[0].get("name"))
        if family and " " in family and not family.isupper():family=""
    sig=candidate_role_signature(
        b.official_name,b.operational_symbol or b.provider_id,tier,p,e,b.note,family
    )
    rs=role_similarity_score(target_role,sig["role"])
    b.role_similarity_score=rs
    b.candidate_role_core=sig["core"];b.candidate_role_defensive=sig["defensive"];b.candidate_role_satellite=sig["satellite"]
    return rs,sig["core"],sig["defensive"],sig["satellite"]

def benchmark_roleaware_utility(b,p,e,target_role,inst):
    if b is None or b.series is None:return -1.0
    rs,_,_,_=benchmark_role_telemetry(b,p,e,target_role)
    geom,n,_=geometry_metrics(inst,b.series)
    sem=max(.45,b.semantic_confidence or b.confidence)
    return roleaware_reference_score(sem,rs,geom,n,1.0)

def reliability_scores(e,p,r,b,c):
    st=structural_type(p);identity=1.0 if st!="UNKNOWN" else .35
    cds=100*(.55*r.confidence+.30*p.confidence+.15*identity)
    if st=="UNKNOWN":cds-=25
    cds=max(0,min(100,cds))
    sem=max(b.semantic_confidence,b.confidence)
    role_sim=max(0.0,min(1.0,(b.role_similarity_score or 50.0)/100.0))
    exact=b.level in ("EXACT_PROVIDER","EXACT_PROVIDER_DISCOVERED","EXACT_ALTERNATIVE_INDEX","IMPLIED_INDEX_REFERENCE")
    relation_bonus=.05 if exact else .03 if b.relation_grade in ("PROPRIA","QUASI PROPRIA","SORELLA") else 0
    if c.common_obs:
        geom=b.geometry_score/100;cov=min(1,c.common_obs/60)
        ref=100*(.42*sem+.28*geom+.18*role_sim+.07*cov+relation_bonus)
    else:
        # Fit unavailable: economic-role compatibility becomes more important.
        series_cov=min(1,(b.observations or 0)/60)
        ref=100*(.58*sem+.27*role_sim+.10*series_cov+relation_bonus)
    if b.review_status=="FORCED_LOW_FIT":ref-=12
    if b.level=="EMERGENCY_BASELINE":ref=min(ref,15)
    ref=max(0,min(100,ref))
    return round(cds,1),round(ref,1),round(.48*cds+.52*ref,1)


def analyze(inst,cb=None,threshold=ROLE_MIN_PERCENT):
    e,s=collect(inst,cb)
    p=profile(e)
    # Ambiguous-only semantic enrichment: keeps speed for strong/easy profiles.
    if enrich_ambiguous_identity(e,p):
        p=profile(e)
    # Deep Yahoo metadata remains rare and lazy.
    if needs_deep_yahoo(e,p):
        enrich_yahoo_deep(e)
        p=profile(e)
    r=role(e,p,threshold)

    try:
        b=resolve(e,p,s,cb,r)
        if b.level in ("EXACT_PROVIDER","EXACT_PROVIDER_DISCOVERED"):
            b.semantic_confidence=max(b.semantic_confidence,.98)
        elif b.level in ("EXACT_YAHOO_INDEX","EXACT_ALTERNATIVE_INDEX"):
            b.semantic_confidence=max(b.semantic_confidence,.90)
    except Exception as exc:
        e.errors.append(f"Benchmark resolver: {type(exc).__name__}: {exc}")
        b=Benchmark(level="NO_PUBLIC_SERIES",note="Resolver exception; mandatory fallback will run.")

    if b is None or b.series is None or not reference_domain_valid(p,e,b):
        if b is not None and b.series is not None and not reference_domain_valid(p,e,b):
            e.errors.append(
                f"DOMAIN_LOCK_REJECTED: {economic_domain(p,e)} vs "
                f"{b.operational_symbol or b.provider_id or b.official_name}"
            )
        # Re-search inside domain before grandmother, guided by frozen C/D/S.
        b=tiered_reference_search(p,e,s,cb,r)
        if b is None or b.series is None or not reference_domain_valid(p,e,b):
            b=_mandatory_last_resort(e,p,s,r,cb) or Benchmark(level="NO_PUBLIC_SERIES")

    bm_for_curve,fxnote=fx_normalize(b.series,b.currency,e.currency,p.hedged)
    c=curve_fit(s,bm_for_curve)

    if b.series is not None:
        gscore,gn,_=geometry_metrics(s,bm_for_curve)
        if b.geometry_score<=0:b.geometry_score=gscore
        if b.selection_score<=0:
            sem=b.semantic_confidence if b.semantic_confidence>0 else b.confidence
            b.selection_score=combined_reference_score(max(.50,sem),gscore,gn,1.0)
        if not b.review_status:b.review_status=_review_status(gn)
        if not b.next_review_obs:b.next_review_obs=_review_next_obs(gn)
    if fxnote:
        c.note=(c.note+" " if c.note else "")+"FX: "+fxnote

    # Visually weak non-exact references reopen the search.
    exact_levels=("EXACT_PROVIDER","EXACT_PROVIDER_DISCOVERED","EXACT_ALTERNATIVE_INDEX")
    sem=max(.60,b.semantic_confidence or b.confidence)
    bg,bn,_=geometry_metrics(s,bm_for_curve) if bm_for_curve is not None else (0.0,0,{})
    if b.level not in exact_levels and not _candidate_quality_gate(sem,bg,bn):
        alt=tiered_reference_search(p,e,s,cb,r)
        if alt is not None and reference_domain_valid(p,e,alt):
            ag,an,_=geometry_metrics(s,alt.series)
            current_u=benchmark_roleaware_utility(b,p,e,r,s)
            alt_u=benchmark_roleaware_utility(alt,p,e,r,s)
            # Replace only if the total economic+semantic+visual utility improves.
            if alt_u >= current_u+2:
                b=alt
                bm_for_curve,fxnote2=fx_normalize(b.series,b.currency,e.currency,p.hedged)
                c=curve_fit(s,bm_for_curve)
                if fxnote2:c.note=(c.note+" " if c.note else "")+"FX: "+fxnote2
                bg,bn=ag,an

    # If first-pass reference is still weak, NOW pay for Borsa benchmark metadata.
    if b.level not in exact_levels and bg < 50 and e.isin and e.instrument_type in ("ETF","ETC","ETP") and not e.benchmark_name:
        try:
            bx=borsa_etf(e.isin)
            bn=norm(bx.get("instrument_name"))
            if bn:e.name=_richer_text(e.name,bn)
            e.benchmark_name=norm(bx.get("benchmark_name"));e.benchmark_code=norm(bx.get("benchmark_code"))
            e.benchmark_area=norm(bx.get("benchmark_area"));e.currency=e.currency or norm(bx.get("currency"))
            if "Borsa Italiana" not in e.sources:e.sources.append("Borsa Italiana")
            retry=resolve(e,p,s,cb,r)
            if retry is not None and retry.series is not None and reference_domain_valid(p,e,retry):
                rg,rn,_=geometry_metrics(s,retry.series)
                current_u=benchmark_roleaware_utility(b,p,e,r,s)
                retry_u=benchmark_roleaware_utility(retry,p,e,r,s)
                if retry_u>=current_u+2:
                    b=retry;bg,bn=rg,rn
                    bm_for_curve,fxnoteB=fx_normalize(b.series,b.currency,e.currency,p.hedged)
                    c=curve_fit(s,bm_for_curve)
                    if fxnoteB:c.note=(c.note+" " if c.note else "")+"FX: "+fxnoteB
        except Exception as exc:
            e.errors.append(f"Borsa lazy retry: {type(exc).__name__}: {exc}")

    # Still poor? Do not pretend it is validated: force the broad domain grandmother.
    if b.level not in exact_levels and bg < 45:
        forced=_mandatory_last_resort(e,p,s,r,cb)
        fg,fn,_=geometry_metrics(s,forced.series)
        current_u=benchmark_roleaware_utility(b,p,e,r,s)
        forced_u=benchmark_roleaware_utility(forced,p,e,r,s)
        # A broad grandmother may replace a close relative only if its TOTAL
        # role-aware utility is materially better, not merely its geometry.
        if forced_u >= current_u+3:
            b=forced
            bm_for_curve,fxnoteF=fx_normalize(b.series,b.currency,e.currency,p.hedged)
            c=curve_fit(s,bm_for_curve)
            if fxnoteF:c.note=(c.note+" " if c.note else "")+"FX: "+fxnoteF
        else:
            b.review_status="FORCED_LOW_FIT"

    # A role composite is meaningful only for a genuinely multi-asset instrument.
    if p.asset=="multiasset" and sum(1 for v in (r.core,r.defensive,r.satellite) if v>0)>=2 and b.level!="COMPOSITE_REFERENCE":
        if c.common_obs<20 or c.trend<55 or b.geometry_score<62:
            mixb=_mixed_role_composite(e,p,s,r,cb)
            if mixb is not None:
                mg,mn,_=geometry_metrics(s,mixb.series)
                bg,bn,_=geometry_metrics(s,b.series) if b.series is not None else (0,0,{})
                if mg>=bg+5 or bn<20:
                    b=mixb
                    bm_for_curve,fxnote3=fx_normalize(b.series,b.currency,e.currency,p.hedged)
                    c=curve_fit(s,bm_for_curve)
                    if fxnote3:c.note=(c.note+" " if c.note else "")+"FX: "+fxnote3

    # Absolute invariant: Result must never leave analyze() without a curve.
    if b is None or clean_series(b.series) is None:
        b=_mandatory_last_resort(e,p,s,r,cb)
        bm_for_curve,fxnote4=fx_normalize(b.series,b.currency,e.currency,p.hedged)
        c=curve_fit(s,bm_for_curve)
        if fxnote4:c.note=(c.note+" " if c.note else "")+"FX: "+fxnote4

    # Reopen the relation tiers if a specialised profile is still represented
    # by a broad parent or by a visually weak curve.
    if b.level not in ("EXACT_PROVIDER","EXACT_ALTERNATIVE_INDEX","EXACT_PROVIDER_DISCOVERED","IMPLIED_INDEX_REFERENCE"):
        specialised=bool(p.theme or p.sector or p.factor or p.size or p.asset=="bond")
        broad_relation=(b.relation_grade in ("PARENTE","ZIA","NONNA","ZIA LONTANA","NONNA FORZATA") or "broad" in ascii_text(b.note or ""))
        if specialised and (b.geometry_score<55 or c.trend<45 or broad_relation):
            deeper=tiered_reference_search(p,e,s,cb,r)
            if deeper is not None and deeper.series is not None:
                dg,dn,_=geometry_metrics(s,deeper.series)
                current_u=benchmark_roleaware_utility(b,p,e,r,s)
                deeper_u=benchmark_roleaware_utility(deeper,p,e,r,s)
                if deeper_u>=current_u+2:
                    b=deeper;bm_for_curve,fxnoteD=fx_normalize(b.series,b.currency,e.currency,p.hedged);c=curve_fit(s,bm_for_curve)
                    if fxnoteD:c.note=(c.note+" " if c.note else "")+"FX: "+fxnoteD

    # Final role compatibility telemetry for every reference, including exact ones.
    benchmark_role_telemetry(b,p,e,r)

    # Final reference status discipline: distinguish an unavailable fit from
    # a genuinely bad fit. A valid reference curve must not be penalised just
    # because the instrument has no overlapping history.
    fit_n=geometry_metrics(s,b.series)[1] if b.series is not None else 0
    if b.level not in ("EXACT_PROVIDER","EXACT_ALTERNATIVE_INDEX","EXACT_PROVIDER_DISCOVERED"):
        if fit_n<5 and b.series is not None:
            b.review_status="FIT_ND_REFERENCE_AVAILABLE"
        elif b.geometry_score < 40:
            b.review_status="FORCED_LOW_FIT"
        elif b.geometry_score < 55 and b.review_status=="VALIDATA_DA_RIVEDERE_PERIODICAMENTE":
            b.review_status="BORDERLINE_LOW_FIT"

    # Benchmark consistency is a second opinion only for weak/UNKNOWN profiles.
    p2,changed=reconcile_profile_with_reference(e,p,b,c)
    if changed:
        p=p2
        r=role(e,p,threshold)

    return Result(e,p,b,r,s,c)

def load_known(path=None):
    p=Path(path) if path else Path(__file__).with_name("known_instruments.json")
    return json.loads(p.read_text(encoding="utf-8"))

def _preflight_known(rows,cb=None):
    """
    One short preflight instead of hundreds of repeated serial network calls.
    1) concurrent ISIN->Yahoo symbol discovery
    2) one batch history download for resolved instrument symbols
    """
    _load_fast_cache()
    tasks=[]
    for x in rows:
        typ=norm(x.get("type")).upper()
        isin=norm(x.get("isin")).upper()
        if typ in ("ETF","ETC","ETP") and isin:
            tasks.append((isin,".MI"))

    uniq=list(dict.fromkeys(tasks))
    if uniq:
        log(cb,f"Preflight: risoluzione Yahoo di {len(uniq)} ISIN (cache/concorrenza)")
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs={ex.submit(discover_yahoo_quote_symbol,isin,suf):(isin,suf) for isin,suf in uniq}
            for fut in as_completed(futs):
                try:fut.result()
                except Exception:pass

    # Collect already-resolved symbols and download all histories in one call.
    symbols=[]
    for x in rows:
        typ=norm(x.get("type")).upper()
        isin=norm(x.get("isin")).upper()
        if typ in ("ETF","ETC","ETP") and isin:
            sym=discover_yahoo_quote_symbol(isin,".MI") or discover_yahoo_quote_symbol(isin,"")
            if sym:symbols.append(sym)
        else:
            ys=norm(x.get("yahoo_symbol"))
            if ys:symbols.append(ys)
    symbols=list(dict.fromkeys(symbols))
    if symbols:
        log(cb,f"Preflight: download batch storico {len(symbols)} simboli")
        yf_history_cached(symbols)

def analyze_known(cb=None,threshold=ROLE_MIN_PERCENT):
    out=[];rows=load_known()
    try:_preflight_known(rows,cb)
    except Exception as exc:log(cb,f"Preflight warning: {type(exc).__name__}: {exc}")
    for i,x in enumerate(rows,1):
        log(cb,f"[{i}/{len(rows)}] {x.get('ticker') or x.get('isin')}")
        try:out.append(analyze(x,cb,threshold))
        except Exception as exc:
            e=Evidence(ticker=norm(x.get("ticker")).upper(),isin=norm(x.get("isin")).upper(),
                       instrument_type=norm(x.get("type")).upper(),name=norm(x.get("name_hint")),
                       errors=[f"FATAL: {type(exc).__name__}: {exc}"])
            # Even fatal results keep the never-blank invariant.
            try:
                p=profile(e);r=role(e,p,threshold)
                b=_mandatory_last_resort(e,p,None,r,None)
            except Exception:
                p=Profile();r=RoleFit()
                ser=pd.Series(100.0,index=pd.bdate_range(end=pd.Timestamp.today().normalize(),periods=280))
                b=Benchmark(level="EMERGENCY_BASELINE",provider="INTERNAL",
                            official_name="Emergency baseline",provider_id="BASE100-EMERGENCY",
                            operational_symbol="BASE100-EMERGENCY",series=ser,
                            confidence=.10,semantic_confidence=.10,relation_grade="NONNA TECNICA")
            out.append(Result(e,p,b,r,None,CurveFit()))
    _save_fast_cache()
    _save_history_disk_cache(_YF_HISTORY_CACHE)
    return out


def candidate_comparison_frames(result,max_candidates=6):
    out=[]
    inst=clean_series(result.instrument_series)
    for row in (result.benchmark.candidate_ladder or [])[:max_candidates]:
        s=row.get("series")
        if s is None:continue
        s=clean_series(s)
        if s is None or len(s)<2:continue
        if inst is not None:
            f=pd.concat([inst.rename("Instrument"),s.rename("Candidate")],axis=1,join="inner").dropna()
            if len(f)>=2:
                f=f.tail(CHART_TARGET_COMMON_OBS)
                out.append((row,f/f.iloc[0]*100))
                continue
        g=pd.DataFrame({"Candidate":s.tail(CHART_TARGET_COMMON_OBS)})
        out.append((row,g/g.iloc[0]*100))
    return out

def comparison_frame(result):
    if result.benchmark.series is None:
        return None
    bm,_=fx_normalize(result.benchmark.series,result.benchmark.currency,result.evidence.currency,result.profile.hedged)
    bm=clean_series(bm)

    # BTP / instruments without a market ticker: show benchmark curve alone
    # rather than an empty graph.
    if result.instrument_series is None:
        if len(bm)<2:return None
        f=pd.DataFrame({"Benchmark":bm.tail(CHART_TARGET_COMMON_OBS)})
        return f/f.iloc[0]*100

    f=pd.concat([clean_series(result.instrument_series).rename("Instrument"),bm.rename("Benchmark")],
                axis=1,join="inner").dropna()
    if len(f)<2:
        # If alignment fails completely but both histories exist, still show reference.
        if len(bm)>=2:
            g=pd.DataFrame({"Benchmark":bm.tail(CHART_TARGET_COMMON_OBS)})
            return g/g.iloc[0]*100
        return None
    f=f.tail(CHART_TARGET_COMMON_OBS)
    return f/f.iloc[0]*100
