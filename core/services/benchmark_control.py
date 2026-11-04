"""Centro di controllo benchmark: metadati SQLite, miglioramenti e manutenzione.

Solo aggregazioni leggere nel render. Nessuno storico completo e nessuna rete sono
letti quando l'utente consulta la pagina. Gli aggiornamenti sono espliciti e
registrati in SQLite (mai in JSON).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import json
import sqlite3
from typing import Any

from core.domain.instrument_status import active_fetch_tickers
from core.verified_benchmarks.store import IndexStore
from core.verified_benchmarks.freshness import MAX_REFERENCE_AGE_DAYS

MIN_POINTS = 20
STALE_DAYS = MAX_REFERENCE_AGE_DAYS  # fonte comune per resolver e diagnostica
_BAD_SOURCES = frozenset({"legacy_json", "portfolio_quote_unadjusted"})


def _iso_date(value: Any) -> str:
    return str(value or "")[:10]


def _days_since(value: Any, today: date | None = None) -> int | None:
    try:
        return ((today or date.today()) - date.fromisoformat(_iso_date(value))).days
    except (ValueError, TypeError):
        return None


def _short_label(label: str, max_chars: int = 54) -> str:
    label = " ".join(str(label or "").split())
    return label if len(label) <= max_chars else label[:max_chars - 1].rstrip() + "…"


def _series_kind(return_type: str, provider: str) -> str:
    """Natura della serie ricavata dai dati registrati in archivio (nessun catalogo fisso)."""
    if return_type == "BLEND":
        return "composite"
    if return_type in ("ETF_ADJ_CLOSE", "ETF_ADJ_C"):
        return "etf_proxy"
    return "index"


def _read_rows(store: IndexStore) -> tuple[list[dict], dict[str, dict], list[dict]]:
    """Tre query aggregate e indicizzate; evita di trasferire tutte le quotazioni."""
    with store._connect() as con:
        series = con.execute("""
            SELECT s.series_id,s.name,s.provider,s.currency,s.return_type,s.family,
                   s.last_fetch_at,s.last_fetch_status,s.last_source,
                   COALESCE(p.n,0),p.start_date,p.end_date,COALESCE(p.sources,'')
            FROM index_series s LEFT JOIN (
                SELECT series_id,COUNT(*) n,MIN(date) start_date,MAX(date) end_date,
                       GROUP_CONCAT(DISTINCT source) sources
                FROM index_prices GROUP BY series_id
            ) p ON p.series_id=s.series_id ORDER BY s.series_id
        """).fetchall()
        snapshots = con.execute(
            "SELECT instrument_id,assignment_json,updated_at FROM assignment_snapshot"
        ).fetchall()
        history = con.execute("""
            SELECT h.instrument_id, h.created_at, h.assignment_json
            FROM assignment_history h ORDER BY h.id DESC LIMIT 30
        """).fetchall()
    rows = []
    for row in series:
        (code,name,provider,currency,return_type,family,fetch_at,fetch_status,last_source,
         points,start,end,sources) = row
        age = _days_since(end)
        source_list = [x for x in sources.split(",") if x]
        quality = ("Senza serie" if points < MIN_POINTS else
                   "Dato da controllare" if age is None or age > STALE_DAYS else
                   "Fonte legacy" if any(x in _BAD_SOURCES for x in source_list) else
                   "Caricato dall’utente" if any(x.startswith("user_supplied:") for x in source_list) else
                   "Recente")
        rows.append({"code":code,"label":name,"short":_short_label(name),"provider":provider,
                     "currency":currency,"return_type":return_type,"family":family,
                     "kind":_series_kind(return_type,provider), "last_fetch_at":fetch_at or "",
                     "last_fetch_status":fetch_status or "Non registrato", "last_source":last_source or "",
                     "points":points,"start":start or "","end":end or "",
                     "sources":source_list,"age_days":age,"state":quality,
                     "source_warning":bool(_BAD_SOURCES.intersection(source_list))})
    by_instrument = {}
    for ticker,raw,updated in snapshots:
        try:
            assignment = json.loads(raw)
        except (ValueError,TypeError):
            continue
        if isinstance(assignment,dict):
            by_instrument[ticker] = {**assignment,"recorded_at":updated}
    revisions = []
    for ticker,created,raw in history:
        try:
            doc=json.loads(raw)
        except (ValueError,TypeError):
            continue
        revisions.append({"ticker":ticker,"at":created,"code":doc.get("ticker") or "",
                          "grade":doc.get("grade") or "", "type":doc.get("kind") or ""})
    return rows,by_instrument,revisions


def _read_refresh_journal(store:IndexStore) -> tuple[dict[str,Any] | None,list[dict]]:
    with store._connect() as con:
        present=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='benchmark_refresh_runs'").fetchone()
        if not present:return None,[]
        runs=con.execute("""
            SELECT run_id,started_at,finished_at,status,requested,updated,failed
            FROM benchmark_refresh_runs ORDER BY run_id DESC LIMIT 20
        """).fetchall()
        row=con.execute("""
            SELECT run_id,started_at,finished_at,status,requested,updated,failed,details
            FROM benchmark_refresh_runs ORDER BY run_id DESC LIMIT 1
        """).fetchone()
        if not row:return None,[]
        items=con.execute("""
            SELECT code,status,added,last_date,reason FROM benchmark_refresh_items
            WHERE run_id=? ORDER BY CASE status WHEN 'failed' THEN 0 WHEN 'updated' THEN 1 ELSE 2 END,code
        """,(row[0],)).fetchall()
    recent=[{"id":r[0],"started":r[1],"finished":r[2],"status":r[3],
             "requested":r[4],"updated":r[5],"failed":r[6]} for r in runs]
    return ({"id":row[0],"started":row[1],"finished":row[2],"status":row[3],
            "requested":row[4],"updated":row[5],"failed":row[6],"details":row[7],
            "items":[{"code":i[0],"status":i[1],"added":i[2],"last_date":i[3],"reason":i[4]} for i in items]},recent)


def _instruments(data:dict) -> list[dict]:
    return [s for s in (data.get("strumenti") or []) if isinstance(s,dict) and s.get("ticker")]


def _instrument_macro_category(instrument:dict)->str:
    """Usa la classificazione centralizzata, evitando una palette duplicata."""
    from persistence.storage import macro_cat
    return str(macro_cat(instrument.get('tipo') or '') or 'ALTRO')


def read_control_snapshot(data:dict,store:IndexStore|None=None) -> dict:
    """Punto unico dati per UI: nessun fetch, nessuna costruzione di serie.

    Il benchmark di ogni strumento e' la decisione salvata (ricerca dal web o scelta manuale):
    qui non esistono candidati fissi ne' scale.
    """
    store=store or IndexStore()
    rows,assignments,history=_read_rows(store)
    by_code={r['code']:r for r in rows}
    last_run,runs=_read_refresh_journal(store)
    active=active_fetch_tickers(data)
    requested=[x for x in _instruments(data) if str(x['ticker']) in active]
    resolved=sum(bool(assignments.get(str(x['ticker']),{}).get('ticker')) for x in requested)
    return {"series":rows,"series_by_code":by_code,"assignments":assignments,
            "history":history,"opportunities":[],"candidate_codes":{},
            "instrument_count":len(requested),"resolved_snapshots":resolved,
            "stale":[r for r in rows if r['points']>=MIN_POINTS and r['age_days'] is not None and r['age_days']>STALE_DAYS],
            "legacy":[r for r in rows if r['source_warning']],
            "missing":[r for r in rows if r['points']<MIN_POINTS],
            "last_run":last_run,"refresh_history":runs,
            "instrument_categories":{str(x['ticker']):_instrument_macro_category(x) for x in _instruments(data)},
            "last_market_date":max((r['end'] for r in rows if r['end']),default='')}


def financial_series_revision(store:IndexStore|None=None) -> str:
    """Firma sui dati finanziari, non su tentativi di fetch o log diagnostici.

    MAX(imported_at) cambia per le osservazioni nuove/sostituite; conteggi e
    cambi FX coprono anche operazioni con date storiche. Una query aggregata
    ha costo contenuto rispetto alla ricostruzione dei payload finanziari.
    """
    store=store or IndexStore()
    with store._connect() as con:
        p=con.execute('SELECT COUNT(*),COALESCE(MAX(imported_at),\'\') FROM index_prices').fetchone()
        fx=con.execute('SELECT COUNT(*),COALESCE(MAX(rowid),0) FROM fx_rates').fetchone()
        assignments=con.execute('SELECT COALESCE(MAX(id),0) FROM assignment_history').fetchone()[0]
        manual_revision=('0','')
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='benchmark_user_imports'").fetchone():
            manual_revision=con.execute("SELECT COALESCE(MAX(id),0),COALESCE(MAX(undone_at),'') FROM benchmark_user_imports").fetchone()
        # Conteggio/ultimo rowid non intercettano ogni undo/correzione;
        # usare il registro manuale per tutti gli indici e le serie FX.
    return f"{p[0]}:{p[1]}|fx:{fx[0]}:{fx[1]}|manual:{manual_revision[0]}:{manual_revision[1]}|as:{assignments}"


