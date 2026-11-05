"""Archivio permanente SQLite (WAL): indici, ETF e proxy ammessi.

Le serie finanziarie sono fonte unica SQLite; l'anagrafica del portafoglio
resta nel suo JSON. L'import legacy e' disponibile esclusivamente in
modalita' di migrazione esplicita con backup, non durante il rendering.
"""
from __future__ import annotations
import json
import hashlib
import math
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping
from core.config import DATA_DIR
from .catalog import IndexSpec

_DEFAULT_DB = Path(DATA_DIR)/'indices'/'benchmarks.sqlite3'
_lock = threading.RLock()
# Percorsi dell'archivio gia' inizializzati in questo processo: schema e journal
# mode WAL (persistente nel file) si impostano una sola volta, non a ogni
# istanza o a ogni lettura (circa 5 s sull'avvio a freddo, misura 2026-11-04).
_READY_PATHS: set[str] = set()
# Scritture di sola manutenzione/derivate: non cambiano i dati su cui i benchmark si basano.
_REVISION_IGNORED_PREFERENCES=('instrument_analysis_auto_refresh_state','benchmark_last_refresh','analysis_resolution_cache','analysis_series_cache')
_REVISION_MEMO: dict[str,tuple[tuple,str]] = {}
_KIND = {'ETF_ADJ_CLOSE': 'etf_proxy', 'ETF_ADJ_C': 'etf_proxy', 'BLEND': 'composite'}

def db_path() -> Path:
    return _DEFAULT_DB

class IndexStore:
    def __init__(self,path: str | Path | None = None):
        self.path=Path(path) if path is not None else db_path()
        key=str(self.path)
        if key not in _READY_PATHS or not self.path.exists():
            self.path.parent.mkdir(parents=True,exist_ok=True)
            self._ensure()
            _READY_PATHS.add(key)

    @contextmanager
    def _connect(self):
        con=sqlite3.connect(str(self.path),timeout=25)
        try:
            con.execute('PRAGMA busy_timeout=25000')
            yield con
            con.commit()
        except:
            con.rollback()
            raise
        finally:
            con.close()

    def _ensure(self):
        with _lock,self._connect() as c:
            c.execute('PRAGMA journal_mode=WAL')
            c.executescript('''
            CREATE TABLE IF NOT EXISTS index_series(
                series_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                provider TEXT NOT NULL, currency TEXT NOT NULL,
                return_type TEXT NOT NULL, family TEXT NOT NULL,
                last_fetch_at TEXT, last_fetch_status TEXT,
                last_source TEXT);
            CREATE TABLE IF NOT EXISTS index_prices(
                series_id TEXT NOT NULL, date TEXT NOT NULL, level REAL NOT NULL CHECK(level>0),
                source TEXT NOT NULL, imported_at TEXT NOT NULL,
                PRIMARY KEY(series_id,date),
                FOREIGN KEY(series_id) REFERENCES index_series(series_id));
            CREATE INDEX IF NOT EXISTS ix_index_prices_date ON index_prices(date);
            CREATE TABLE IF NOT EXISTS fx_rates(
                fx_code TEXT NOT NULL, date TEXT NOT NULL, rate REAL NOT NULL CHECK(rate>0),
                source TEXT NOT NULL, PRIMARY KEY(fx_code,date));
            CREATE TABLE IF NOT EXISTS market_reference_prices(
                symbol TEXT NOT NULL, date TEXT NOT NULL, level REAL NOT NULL CHECK(level>0),
                source TEXT NOT NULL, PRIMARY KEY(symbol,date));
            CREATE TABLE IF NOT EXISTS benchmark_preferences(
                key TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS instrument_reference(
                instrument_id TEXT PRIMARY KEY, official_reference TEXT NOT NULL,
                source TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS instrument_override(
                instrument_id TEXT PRIMARY KEY, code TEXT NOT NULL, label TEXT NOT NULL,
                updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS assignment_snapshot(
                instrument_id TEXT PRIMARY KEY, assignment_json TEXT NOT NULL,
                updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS assignment_history(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instrument_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                assignment_json TEXT NOT NULL,
                created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS ix_assignment_history_inst ON assignment_history(instrument_id);
            ''')

    def _spec(self, code: str) -> IndexSpec:
        """Specifica di una serie: catalogo, oppure serie registrata in archivio (scoperta dal web)."""
        with self._connect() as c:
            row = c.execute('SELECT series_id,name,provider,currency,return_type,family FROM index_series WHERE series_id=?',(code,)).fetchone()
        if row is None:
            raise ValueError(f'Benchmark non censito nel catalogo: {code!r}')
        return IndexSpec(row[0], row[1], row[5], row[2], row[3], row[4], 'dynamic', '', _KIND.get(row[4], 'index'))

    def specs(self) -> dict[str, IndexSpec]:
        """Tutte le serie registrate in archivio: il registro dei benchmark e' l'archivio stesso."""
        with self._connect() as c:
            rows = c.execute('SELECT series_id,name,provider,currency,return_type,family FROM index_series').fetchall()
        return {r[0]: IndexSpec(r[0], r[1], r[5], r[2], r[3], r[4], 'dynamic', '', _KIND.get(r[4], 'index')) for r in rows}

    def has_series(self, code: str) -> bool:
        with self._connect() as c:
            return c.execute('SELECT 1 FROM index_series WHERE series_id=?', (code,)).fetchone() is not None

    def register_series(self, code: str, label: str, provider: str, currency: str, return_type: str, family: str) -> None:
        """Registra (o aggiorna) una serie scoperta dal web, perche' possa essere scritta, letta e scelta."""
        if not code or not label:
            raise ValueError('codice e nome della serie sono obbligatori')
        with _lock, self._connect() as c:
            c.execute('INSERT INTO index_series(series_id,name,provider,currency,return_type,family) VALUES(?,?,?,?,?,?) '
                      'ON CONFLICT(series_id) DO UPDATE SET name=excluded.name,provider=excluded.provider,'
                      'currency=excluded.currency,return_type=excluded.return_type,family=excluded.family',
                      (code, label, provider, currency, return_type, family))

    def upsert(self,code: str,prices: Mapping[str,float], *,source: str,replace_existing: bool = False) -> int:
        spec=self._spec(code)
        items=[]
        for day,value in (prices or {}).items():
            try:
                day=date.fromisoformat(str(day)[:10]).isoformat()
                value=float(value)
                if not math.isfinite(value) or value<=0: continue
                items.append((code,day,value,source,datetime.now(timezone.utc).isoformat()))
            except (ValueError,TypeError): continue
        if not items: return 0
        sql=('INSERT INTO index_prices VALUES (?,?,?,?,?) ON CONFLICT(series_id,date) DO UPDATE SET level=excluded.level, source=excluded.source, imported_at=excluded.imported_at' if replace_existing else 'INSERT OR IGNORE INTO index_prices VALUES (?,?,?,?,?)')
        with _lock,self._connect() as c:
            c.execute('INSERT INTO index_series(series_id,name,provider,currency,return_type,family,last_source) VALUES(?,?,?,?,?,?,?) ON CONFLICT(series_id) DO UPDATE SET last_source=excluded.last_source',
                     (spec.code,spec.label,spec.provider,spec.currency,spec.return_type,spec.family,source))
            before=c.total_changes
            c.executemany(sql,items)
            return c.total_changes-before

    def read(self,code: str,start: str|None=None,end: str|None=None) -> dict[str,float]:
        self._spec(code)
        where='series_id=?'; p=[code]
        if start: where+=' AND date>=?';p.append(str(start)[:10])
        if end: where+=' AND date<=?';p.append(str(end)[:10])
        with self._connect() as c:
            return {d:v for d,v in c.execute(f'SELECT date,level FROM index_prices WHERE {where} ORDER BY date',p)}

    def sources(self,code:str)->set[str]:
        """Provenienza delle osservazioni: distingue adjusted vs prezzi grezzi."""
        self._spec(code)
        with self._connect() as c:
            return {r[0] for r in c.execute(
                'SELECT DISTINCT source FROM index_prices WHERE series_id=?',(code,))}

    def last_date(self,code: str) -> str|None:
        self._spec(code)
        with self._connect() as c:
            x=c.execute('SELECT MAX(date) FROM index_prices WHERE series_id=?',(code,)).fetchone()
            return x[0] if x else None

    def fetch_state(self,code:str) -> dict:
        with self._connect() as c:
            row=c.execute('SELECT last_fetch_at,last_fetch_status,last_source FROM index_series WHERE series_id=?',(code,)).fetchone()
        return dict(zip(('last_fetch_at','last_fetch_status','last_source'),row)) if row else {}

    def mark_fetch(self,code:str,status:str,source:str):
        spec=self._spec(code)
        with _lock,self._connect() as c:
            c.execute('INSERT INTO index_series(series_id,name,provider,currency,return_type,family,last_fetch_at,last_fetch_status,last_source) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(series_id) DO UPDATE SET last_fetch_at=excluded.last_fetch_at,last_fetch_status=excluded.last_fetch_status,last_source=excluded.last_source',
             (code,spec.label,spec.provider,spec.currency,spec.return_type,spec.family,datetime.now(timezone.utc).isoformat(),status,source))

    def upsert_fx(self,code: str,prices: Mapping[str,float],source: str='legacy_json') -> int:
        if code not in ('EURUSD=X','EURGBP=X','EURJPY=X','EURCHF=X'):
            raise ValueError(f'Coppia FX non abilitata: {code}')
        rows=[]
        for k,v in (prices or {}).items():
            try:
                day=date.fromisoformat(str(k)[:10]).isoformat(); val=float(v)
                if math.isfinite(val) and val>0: rows.append((code,day,val,source))
            except (ValueError,TypeError): pass
        with _lock,self._connect() as c:
            before=c.total_changes
            c.executemany('INSERT OR IGNORE INTO fx_rates VALUES(?,?,?,?)',rows)
            return c.total_changes-before

    def read_fx(self,code:str) -> dict[str,float]:
        if code not in ('EURUSD=X','EURGBP=X','EURJPY=X','EURCHF=X'):
            return {}
        with self._connect() as c:
            return {d:v for d,v in c.execute('SELECT date,rate FROM fx_rates WHERE fx_code=? ORDER BY date',(code,))}

    def upsert_market(self,symbol:str,prices:Mapping[str,float],source:str='market_yahoo') -> int:
        """Serie Mercati non appartenenti al catalogo: database, mai JSON."""
        symbol=str(symbol or '').strip()
        if not symbol:return 0
        if self.has_series(symbol):
            return self.upsert(symbol,prices,source=source)
        rows=[]
        for d,v in (prices or {}).items():
            try:
                day=date.fromisoformat(str(d)[:10]).isoformat(); val=float(v)
                if math.isfinite(val) and val>0:rows.append((symbol,day,val,source))
            except (TypeError,ValueError):pass
        with _lock,self._connect() as c:
            before=c.total_changes
            c.executemany('INSERT OR IGNORE INTO market_reference_prices VALUES(?,?,?,?)',rows)
            return c.total_changes-before

    def read_market(self,symbol:str) -> dict[str,float]:
        with self._connect() as c:
            return {d:v for d,v in c.execute(
                'SELECT date,level FROM market_reference_prices WHERE symbol=? ORDER BY date',(symbol,))}

    def read_any(self,code:str) -> dict[str,float]:
        if self.has_series(code):return self.read(code)
        return self.read_market(code)

    def save_preference(self,key:str,payload) -> None:
        serialized=json.dumps(payload,ensure_ascii=False,sort_keys=True)
        with _lock,self._connect() as c:
            c.execute('INSERT INTO benchmark_preferences VALUES(?,?,?) '
                      'ON CONFLICT(key) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at',
                      (key,serialized,datetime.now(timezone.utc).isoformat()))

    def preference(self,key:str,default=None):
        with self._connect() as c:
            row=c.execute('SELECT payload FROM benchmark_preferences WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default

    def save_reference(self,instrument_id:str,label:str,source:str='legacy') -> None:
        if not instrument_id or not label:return
        with _lock,self._connect() as c:
            c.execute('INSERT INTO instrument_reference VALUES(?,?,?,?) ON CONFLICT(instrument_id) '
                      'DO UPDATE SET official_reference=excluded.official_reference,source=excluded.source,updated_at=excluded.updated_at',
                      (instrument_id,str(label),str(source),datetime.now(timezone.utc).isoformat()))

    def reference(self,instrument_id:str) -> dict|None:
        with self._connect() as c:
            row=c.execute('SELECT official_reference,source FROM instrument_reference WHERE instrument_id=?',(instrument_id,)).fetchone()
        return {'label':row[0],'source':row[1]} if row else None

    def save_override(self,instrument_id:str,code:str,label:str='') -> None:
        """Scelta manuale dell'utente per uno strumento (prevale sempre); `code` vuoto la toglie.
        Il codice deve essere una serie nota: del catalogo o registrata in archivio."""
        spec=self._spec(code) if code else None
        with _lock,self._connect() as c:
            if not code:
                c.execute('DELETE FROM instrument_override WHERE instrument_id=?',(instrument_id,))
            else:
                c.execute('INSERT INTO instrument_override VALUES(?,?,?,?) '
                          'ON CONFLICT(instrument_id) DO UPDATE SET code=excluded.code,label=excluded.label,updated_at=excluded.updated_at',
                          (instrument_id,code,label or spec.label,datetime.now(timezone.utc).isoformat()))

    def override(self,instrument_id:str) -> dict|None:
        with self._connect() as c:
            row=c.execute('SELECT code,label FROM instrument_override WHERE instrument_id=?',(instrument_id,)).fetchone()
        return {'benchmark_code':row[0],'benchmark_label':row[1], 'benchmark_user_edited':True} if row else None

    def market_count(self)->int:
        with self._connect() as c:
            return int(c.execute('SELECT COUNT(DISTINCT symbol) FROM market_reference_prices').fetchone()[0])

    def import_legacy(self,data:dict) -> dict:
        """Importa indici ed ETF proxy ammessi, esclude futures."""
        raw=data.get('benchmark_data') or {}
        stats={'indices':0,'etf_proxies':0,'quotes_added':0,'rejected':[],'fx_added':0}
        for key,prices in raw.items():
            if not str(key).startswith('bench_'): continue
            code=str(key)[6:]
            if code in ('EURUSD=X','EURGBP=X','EURJPY=X','EURCHF=X'):
                stats['fx_added']+=self.upsert_fx(code,prices,source='legacy_json')
                continue
            try: spec=self._spec(code)
            except ValueError:
                stats['rejected'].append(code);continue
            if not isinstance(prices,dict):continue
            count=self.upsert(code,prices,source='legacy_json',replace_existing=False)
            stats['indices' if spec.asset_kind=='index' else 'etf_proxies']+=1
            stats['quotes_added']+=count
        return stats

    def save_assignment(self,ticker:str,assignment:dict):
        """Snapshot corrente + versione STORICA quando cambiano gambe/pesi.

        Nessuna riscrittura delle vecchie composizioni: le versioni sono
        conservate e permettono di ricostruire quando il confronto cambio'.
        """
        if not ticker: return
        stamp=datetime.now(timezone.utc).isoformat()
        doc=json.dumps(assignment,ensure_ascii=False,sort_keys=True)
        identity={k:assignment.get(k) for k in ('ticker','kind','components','grade','currency')}
        fingerprint=hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        with _lock,self._connect() as c:
            current=c.execute('SELECT assignment_json FROM assignment_snapshot WHERE instrument_id=?',(ticker,)).fetchone()
            if current is not None and current[0]==doc:
                return  # lettura dei grafici: nessuna scrittura/rerun/ciclo cache
            last=c.execute('SELECT fingerprint FROM assignment_history WHERE instrument_id=? ORDER BY id DESC LIMIT 1',(ticker,)).fetchone()
            if not last or last[0]!=fingerprint:
                c.execute('INSERT INTO assignment_history(instrument_id,fingerprint,assignment_json,created_at) VALUES(?,?,?,?)',
                          (ticker,fingerprint,doc,stamp))
            c.execute('INSERT INTO assignment_snapshot VALUES (?,?,?) ON CONFLICT(instrument_id) DO UPDATE SET assignment_json=excluded.assignment_json,updated_at=excluded.updated_at',
                      (ticker,doc,stamp))

    def assignment_versions(self,ticker:str)->list[dict]:
        with self._connect() as c:
            rows=c.execute('SELECT assignment_json,created_at FROM assignment_history WHERE instrument_id=? ORDER BY id',(ticker,)).fetchall()
        return [{**json.loads(doc),'version_created_at':stamp} for doc,stamp in rows]

    def assignment(self,ticker:str) -> dict|None:
        with self._connect() as c:
            row=c.execute('SELECT assignment_json FROM assignment_snapshot WHERE instrument_id=?',(ticker,)).fetchone()
        return json.loads(row[0]) if row else None

    def summary(self):
        specs=self.specs()
        with self._connect() as c:
            count=c.execute('SELECT COUNT(*) FROM index_prices').fetchone()[0]
        return {'series':len(specs),
                'indices':sum(s.asset_kind=='index' for s in specs.values()),
                'etf_proxies':sum(s.asset_kind=='etf_proxy' for s in specs.values()),
                'prices':count}

    def stat_key(self) -> tuple:
        """(mtime, dimensione) di database e journal WAL: cambia a ogni scrittura.

        Serve solo come chiave per memoizzare letture; non e' un'impronta del
        contenuto (per quella vedi revision_token).
        """
        wal=Path(str(self.path)+'-wal')
        def one(p: Path):
            # Il WAL puo' sparire (checkpoint alla chiusura dell'ultima connessione)
            # tra il controllo e la lettura: in quel caso e' semplicemente assente.
            try:
                st=p.stat()
            except OSError:
                return None
            return (st.st_mtime_ns,st.st_size)
        return tuple(one(p) for p in (self.path,wal))

    def revision_token(self) -> str:
        """Impronta del CONTENUTO che incide sui benchmark, stabile tra processi.

        Prima era (mtime, dimensione) del file e del journal WAL: cambiava a ogni
        scrittura anche di sola manutenzione (stato dell'aggiornamento automatico,
        cache di analisi) e a ogni checkpoint, quindi invalidava la firma globale
        dei dati e tutte le figure a ogni avvio. Ora dipende solo da serie, prezzi,
        cambi, riferimenti, override, assegnazioni e preferenze scelte dall'utente.
        Il risultato e' memorizzato per (mtime, dimensione): la stat serve solo da
        chiave del memo, non entra nel token.
        """
        stat_key=self.stat_key()
        memo_key=str(self.path)
        with _lock:
            memo=_REVISION_MEMO.get(memo_key)
            if memo is not None and memo[0]==stat_key:
                return memo[1]
        if stat_key[0] is None:
            return 'missing'
        ignored=tuple(_REVISION_IGNORED_PREFERENCES)
        marks=','.join('?' for _ in ignored)
        with self._connect() as c:
            parts=[
                c.execute('SELECT COUNT(*),TOTAL(level),MAX(imported_at) FROM index_prices').fetchone(),
                c.execute('SELECT series_id,name,provider,currency,return_type,family FROM index_series ORDER BY series_id').fetchall(),
                c.execute('SELECT COUNT(*),TOTAL(rate) FROM fx_rates').fetchone(),
                c.execute('SELECT COUNT(*),TOTAL(level) FROM market_reference_prices').fetchone(),
                c.execute(f'SELECT key,payload FROM benchmark_preferences WHERE key NOT IN ({marks}) ORDER BY key',ignored).fetchall(),
                c.execute('SELECT instrument_id,official_reference,source FROM instrument_reference ORDER BY instrument_id').fetchall(),
                c.execute('SELECT instrument_id,code,label FROM instrument_override ORDER BY instrument_id').fetchall(),
                c.execute('SELECT instrument_id,assignment_json FROM assignment_snapshot ORDER BY instrument_id').fetchall(),
            ]
        token=hashlib.sha256(json.dumps(parts,sort_keys=True,default=str).encode('utf-8')).hexdigest()[:16]
        with _lock:
            _REVISION_MEMO[memo_key]=(stat_key,token)
        return token
