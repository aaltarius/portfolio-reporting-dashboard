"""Gestione manuale degli storici di soli indici autentici, condivisa da tutti gli strumenti.

CSV, XLSX, copia/incolla e correzioni puntuali. Tutte le modifiche sono
atomiche, identificate e reversibili. Nessun dato viene creato per interpolazione.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import posixpath
import re
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping
from xml.etree import ElementTree as ET

from .store import IndexStore, _lock

MAX_BYTES = 15_000_000
MAX_ROWS = 150_000
FX_CODES = {'EURUSD=X':'USD per EUR', 'EURGBP=X':'GBP per EUR', 'EURJPY=X':'JPY per EUR', 'EURCHF=X':'CHF per EUR'}
DATE_COLS = ('data', 'date', 'day', 'giorno', 'time period', 'time_period', 'timestamp')
VALUE_COLS = ('valore', 'value', 'level', 'livello', 'prezzo', 'price', 'close', 'closing price', 'closing', 'chiusura', 'ultimo', 'last', 'obs_value')


def allowed_indices(store: IndexStore | None = None) -> dict:
    """Indici (non ETF) registrati in archivio: sono i soli su cui si puo' importare uno storico a mano."""
    return {code: spec for code, spec in (store or IndexStore()).specs().items() if spec.asset_kind == 'index'}


def _validate_index(code: str, store: IndexStore | None = None):
    spec = allowed_indices(store).get(str(code))
    if spec is None:
        raise ValueError('Si possono importare soltanto indici ufficiali già censiti. Non ETF, ETC o prezzi spot.')
    return spec


def _target_kind(code:str, store: IndexStore | None = None) -> str:
    if code in FX_CODES:
        return 'fx'
    _validate_index(code, store)
    return 'index'


def _read_target(store:IndexStore,code:str) -> dict[str,float]:
    return store.read_fx(code) if code in FX_CODES else store.read(code)


def _target_summary(code:str, store: IndexStore | None = None)->str:
    if code in FX_CODES:
        return 'Tasso di cambio '+FX_CODES[code]
    return _validate_index(code, store).label


def _parse_date(value: object) -> str:
    if isinstance(value, datetime):
        day = value.date()
    elif isinstance(value, date):
        day = value
    else:
        txt = str(value or '').strip()
        day = None
        for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%d.%m.%Y', '%Y/%m/%d', '%m/%d/%Y', '%b %d, %Y', '%B %d, %Y'):
            try:
                day = datetime.strptime(txt, fmt).date()
                break
            except ValueError:
                continue
        # Numeri di serie Excel: Excel sistema 1900, date moderne.
        if day is None and re.fullmatch(r'\d{5}(?:\.0+)?', txt):
            serial = int(float(txt))
            if 20000 <= serial <= 90000:
                day = date(1899, 12, 30) + timedelta(days=serial)
        if day is None:
            raise ValueError(f'Data non riconosciuta: {txt[:35]} (usa gg/mm/aaaa)')
    if day > date.today():
        raise ValueError(f'Data futura: {day.strftime("%d/%m/%Y")}')
    if day < date(1900, 1, 1):
        raise ValueError('Data precedente al 1900')
    return day.isoformat()


def _parse_level(value: object) -> float:
    txt = str(value or '').strip().replace('\u00a0', '').replace(' ', '').replace("'", '')
    if not txt:
        raise ValueError('Livello vuoto')
    if ',' in txt and '.' in txt:
        txt = txt.replace('.', '').replace(',', '.') if txt.rfind(',') > txt.rfind('.') else txt.replace(',', '')
    elif ',' in txt:
        if txt.count(',') == 1 and len(txt.split(',')[-1]) == 3:
            raise ValueError('Numero ambiguo: usare 1234.567 oppure 1.234,56')
        txt = txt.replace(',', '.') if txt.count(',') == 1 else txt.replace(',', '')
    try:
        result = float(txt)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'Numero non riconosciuto: {txt[:32]}') from exc
    if not math.isfinite(result) or result <= 0:
        raise ValueError('Il livello deve essere maggiore di zero e finito')
    return result


def _xlsx_records(raw: bytes) -> list[list[str]]:
    """Legge un foglio XLSX semplice usando la libreria standard (nessun plugin Excel)."""
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        raise ValueError('File XLSX non valido')
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
          'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
          'p': 'http://schemas.openxmlformats.org/package/2006/relationships'}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        infos = z.infolist()
        if sum(i.file_size for i in infos) > 50_000_000 or len(infos) > 500:
            raise ValueError('File XLSX troppo grande o anomalo')
        names = set(z.namelist())
        try:
            wb = ET.fromstring(z.read('xl/workbook.xml'))
            rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        except (KeyError, ET.ParseError) as exc:
            raise ValueError('Struttura XLSX non leggibile') from exc
        if wb.find('m:workbookPr', ns) is not None and wb.find('m:workbookPr',ns).attrib.get('date1904') in ('1','true'):
            raise ValueError('Questo file usa il calendario Excel 1904: salva il foglio come CSV')
        sheets = wb.find('m:sheets',ns)
        if sheets is None or len(sheets) == 0:
            raise ValueError('Nessun foglio nel file Excel')
        rid = sheets[0].attrib.get('{'+ns['r']+'}id')
        relations = {item.attrib['Id']: item.attrib.get('Target','') for item in rels}
        target = relations.get(rid,'')
        if not target:
            raise ValueError('Foglio Excel non trovato')
        if target.startswith('/'):
            sheet_path = target.lstrip('/')
        else:
            sheet_path = posixpath.normpath(posixpath.join('xl',target))
        if sheet_path not in names:
            raise ValueError('Foglio Excel non presente nel file')
        strings = []
        if 'xl/sharedStrings.xml' in names:
            root = ET.fromstring(z.read('xl/sharedStrings.xml'))
            strings = [''.join(t.text or '' for t in si.findall('.//m:t',ns)) for si in root.findall('m:si',ns)]
        root = ET.fromstring(z.read(sheet_path))
        cells = []
        for row in root.findall('.//m:sheetData/m:row',ns):
            found = {}
            for cell in row.findall('m:c',ns):
                ref = cell.attrib.get('r','')
                match = re.match(r'([A-Z]+)',ref)
                if not match:
                    continue
                col = 0
                for ch in match.group(1):
                    col = col * 26 + ord(ch) - 64
                if col > 100:
                    continue
                typ = cell.attrib.get('t','')
                v = cell.find('m:v',ns)
                if typ == 'inlineStr':
                    value = ''.join(t.text or '' for t in cell.findall('.//m:t',ns))
                elif typ == 'e':
                    value = '#EXCEL_ERROR'
                else:
                    value = v.text if v is not None and v.text is not None else ''
                    if typ == 's' and value:
                        try:
                            value = strings[int(value)]
                        except (IndexError,ValueError) as exc:
                            raise ValueError('Testo Excel non leggibile') from exc
                found[col] = value
            if found:
                cells.append([found.get(i,'') for i in range(1,max(found)+1)])
            if len(cells)>MAX_ROWS+3:
                raise ValueError(f'Troppe righe: massimo {MAX_ROWS}')
        return cells


def _csv_records(raw: bytes) -> list[list[str]]:
    try:
        content = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        content = raw.decode('cp1252')
    try:
        dialect=csv.Sniffer().sniff(content[:8192],delimiters=',;\t')
    except csv.Error:
        dialect=csv.excel
    rows = [line for line in csv.reader(io.StringIO(content,newline=''),dialect) if any(str(c).strip() for c in line)]
    if len(rows)>MAX_ROWS+3:
        raise ValueError(f'Troppe righe: massimo {MAX_ROWS}')
    return rows


def parse_table(raw: bytes,filename: str) -> tuple[list[str],list[list[str]]]:
    if not isinstance(raw,bytes) or not raw or len(raw)>MAX_BYTES:
        raise ValueError('File/testo vuoto o superiore a 15 MB')
    extension = Path(filename.lower()).suffix
    if extension == '.xlsx':
        rows=_xlsx_records(raw)
    elif extension in ('.csv','.txt'):
        rows=_csv_records(raw)
    else:
        raise ValueError('Formato non ammesso: usa CSV o XLSX')
    if not rows:
        raise ValueError('Nessuna riga di dati')
    # Alcune esportazioni antepongono titoli e note alla tabella.
    for i,row in enumerate(rows[:30]):
        lower=[str(c or '').strip().lower() for c in row]
        if any(h in DATE_COLS for h in lower) and any(h in VALUE_COLS for h in lower):
            return [str(x or '').strip() for x in row],rows[i+1:]
        try:
            _parse_date(row[0]); _parse_level(row[1])
        except (IndexError,ValueError):
            continue
        # Dati senza intestazione. Le colonne 1/2 sono data e livello.
        return ['Data','Valore'],[r[:2] for r in rows[i:]]
    if len(rows[0])>=2:
        # L'utente puo' scegliere a mano le due colonne in UI.
        return [str(x or '').strip() for x in rows[0]],rows[1:]
    raise ValueError('Non riesco a individuare Data e Livello: rimuovi le righe introduttive')


def suggested_columns(headers:list[str])->tuple[str,str]:
    lowered={h.lower().strip():h for h in headers}
    date_col=next((lowered[x] for x in DATE_COLS if x in lowered),headers[0] if headers else '')
    value_col=next((lowered[x] for x in VALUE_COLS if x in lowered),headers[1] if len(headers)>1 else '')
    return date_col,value_col


@dataclass(frozen=True)
class ParsedSeries:
    values: dict[str,float]
    first: str
    last: str
    unusual_jumps: int
    sha256: str


def parse_series(headers:list[str],rows:list[list],date_col:str,value_col:str,raw:bytes)->ParsedSeries:
    if date_col not in headers or value_col not in headers or date_col == value_col:
        raise ValueError('Scegli due colonne diverse: Data e Livello')
    di, vi=headers.index(date_col),headers.index(value_col)
    values={}
    for n,row in enumerate(rows,start=2):
        if not any(str(x or '').strip() for x in row):continue
        try:
            d=_parse_date(row[di] if di<len(row) else '')
            v=_parse_level(row[vi] if vi<len(row) else '')
        except (ValueError,IndexError) as exc:
            raise ValueError(f'Riga {n}: {exc}') from exc
        if d in values and not math.isclose(v,values[d],rel_tol=1e-10):
            raise ValueError(f'Riga {n}: due livelli differenti nella stessa data {d}')
        values[d]=v
    if not values:
        raise ValueError('Nessuna osservazione valida')
    previous=None; jumps=0
    for d in sorted(values):
        if previous is not None and abs(values[d]/previous-1)>0.25:
            jumps+=1
        previous=values[d]
    return ParsedSeries(values,min(values),max(values),jumps,hashlib.sha256(raw).hexdigest())


def _state_digest(values:Mapping[str,float],existing:Mapping[str,float])->str:
    h=hashlib.sha256()
    for d in sorted(values):
        prior=existing.get(d)
        h.update(f'{d}={prior!r};'.encode('utf-8'))
    return h.hexdigest()


def inspect_import(store:IndexStore,code:str,parsed:ParsedSeries)->dict:
    _target_kind(code, store)
    existing=_read_target(store,code)
    new=sum(d not in existing for d in parsed.values)
    same=sum(d in existing and math.isclose(v,existing[d],rel_tol=1e-10,abs_tol=1e-12) for d,v in parsed.values.items())
    conflicts=[(d,existing[d],v) for d,v in parsed.values.items() if d in existing and not math.isclose(v,existing[d],rel_tol=1e-10,abs_tol=1e-12)]
    return {'new':new,'unchanged':same,'conflicts':len(conflicts),'examples':sorted(conflicts)[:8],
            'fingerprint':_state_digest(parsed.values,existing), 'count_before':len(existing)}


def _ensure_audit(c:sqlite3.Connection):
    c.execute('''CREATE TABLE IF NOT EXISTS benchmark_user_imports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT NOT NULL,created_at TEXT NOT NULL,
        source_detail TEXT NOT NULL,filename TEXT NOT NULL,file_sha256 TEXT NOT NULL,
        inserted INTEGER NOT NULL,corrected INTEGER NOT NULL,undone_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS benchmark_user_import_rows (
        batch_id INTEGER NOT NULL,day TEXT NOT NULL,new_level REAL NOT NULL,
        old_level REAL,old_source TEXT,old_imported_at TEXT,
        PRIMARY KEY(batch_id,day))''')


def apply_import(store:IndexStore,code:str,parsed:ParsedSeries,*,source:str,filename:str,
                 mode:str='append',expected_fingerprint:str='',confirmed:bool=False)->dict:
    kind=_target_kind(code, store)
    spec=_validate_index(code, store) if kind=='index' else None
    if not confirmed:
        raise ValueError('Conferma esplicitamente che il file si riferisce all’indice selezionato')
    if mode not in ('append','correct'):
        raise ValueError('Modalità di importazione sconosciuta')
    source=' '.join(str(source or '').strip().split())
    if not (8<=len(source)<=300):
        raise ValueError('Indica una fonte riconoscibile (almeno 8 caratteri)')
    if not parsed.values:
        raise ValueError('Non ci sono valori da inserire')
    # Difesa a livello di dominio: anche gli import chiamati fuori dalla UI
    # devono rispettare le regole del parser (nessun prezzo inventato).
    for day,level in parsed.values.items():
        if _parse_date(day)!=day or _parse_level(level)!=float(level):
            raise ValueError(f'Dato non normalizzato: {day}')
    now=datetime.now(timezone.utc).isoformat()
    inserted=corrected=0
    with _lock,store._connect() as c:
        if kind=='index':
            query='SELECT date,level,source,imported_at FROM index_prices WHERE series_id=?'
        else:
            query='SELECT date,rate,source,NULL FROM fx_rates WHERE fx_code=?'
        if len(parsed.values)<=800:
            query+=f' AND date IN ({",".join("?" for _ in parsed.values)})'
            current={d:(v,s,t) for d,v,s,t in c.execute(query,(code,*parsed.values))}
        else:
            current={d:(v,s,t) for d,v,s,t in c.execute(query,(code,)) if d in parsed.values}
        if expected_fingerprint:
            current_val={d:row[0] for d,row in current.items()}
            if _state_digest(parsed.values,current_val)!=expected_fingerprint:
                raise ValueError('Lo storico è cambiato dall’anteprima. Ricarica la verifica prima di salvare.')
        _ensure_audit(c)
        if kind=='index':
            c.execute('INSERT INTO index_series(series_id,name,provider,currency,return_type,family,last_source) '
                      'VALUES(?,?,?,?,?,?,?) ON CONFLICT(series_id) DO NOTHING',
                      (code,spec.label,spec.provider,spec.currency,spec.return_type,spec.family,'manual_user'))
        changes=[]
        for d,v in sorted(parsed.values.items()):
            prev=current.get(d)
            if prev is None:
                changes.append((d,v,None,None,None)); inserted+=1
            elif mode=='correct' and not math.isclose(v,prev[0],rel_tol=1e-10,abs_tol=1e-12):
                changes.append((d,v,*prev)); corrected+=1
        if not changes:
            return {'inserted':0,'corrected':0,'unchanged':len(parsed.values),'batch_id':None}
        c.execute('INSERT INTO benchmark_user_imports(code,created_at,source_detail,filename,file_sha256,inserted,corrected) '
                  'VALUES(?,?,?,?,?,?,?)',(code,now,source,Path(filename).name[:200],parsed.sha256,inserted,corrected))
        batch_id=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        stamp=f'user_supplied:{batch_id}'
        c.executemany('INSERT INTO benchmark_user_import_rows(batch_id,day,new_level,old_level,old_source,old_imported_at) '
                      'VALUES(?,?,?,?,?,?)',[(batch_id,*change) for change in changes])
        if kind=='index':
            c.executemany('INSERT INTO index_prices(series_id,date,level,source,imported_at) '
                          'VALUES(?,?,?,?,?) ON CONFLICT(series_id,date) DO UPDATE SET '
                          'level=excluded.level,source=excluded.source,imported_at=excluded.imported_at',
                          [(code,d,v,stamp,now) for d,v,*_ in changes])
            c.execute('UPDATE index_series SET last_source=?,last_fetch_at=?,last_fetch_status=? WHERE series_id=?',
                      (stamp,now,'manual_import_needs_validation',code))
        else:
            c.executemany('INSERT INTO fx_rates(fx_code,date,rate,source) VALUES(?,?,?,?) '
                          'ON CONFLICT(fx_code,date) DO UPDATE SET rate=excluded.rate,source=excluded.source',
                          [(code,d,v,stamp) for d,v,*_ in changes])
    return {'inserted':inserted,'corrected':corrected,'unchanged':len(parsed.values)-inserted-corrected,'batch_id':batch_id}


def last_imports(store:IndexStore,code:str,limit:int=5)->list[dict]:
    with store._connect() as c:
        exists=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='benchmark_user_imports'").fetchone()
        if not exists:return []
        rows=c.execute('SELECT id,created_at,source_detail,filename,inserted,corrected,undone_at '
                       'FROM benchmark_user_imports WHERE code=? ORDER BY id DESC LIMIT ?',
                       (code,limit)).fetchall()
    return [dict(zip(('id','at','source','filename','inserted','corrected','undone_at'),row)) for row in rows]


def undo_import(store:IndexStore,code:str,batch_id:int)->dict:
    kind=_target_kind(code, store)
    with _lock,store._connect() as c:
        _ensure_audit(c)
        row=c.execute('SELECT undone_at FROM benchmark_user_imports WHERE id=? AND code=?',(batch_id,code)).fetchone()
        if row is None or row[0]:
            raise ValueError('Importazione non trovata oppure già annullata')
        changes=c.execute('SELECT day,new_level,old_level,old_source,old_imported_at '
                          'FROM benchmark_user_import_rows WHERE batch_id=? ORDER BY day',(batch_id,)).fetchall()
        for d,new,old,src,stamp in changes:
            cur=c.execute(('SELECT level,source FROM index_prices WHERE series_id=? AND date=?' if kind=='index' else 'SELECT rate,source FROM fx_rates WHERE fx_code=? AND date=?'),(code,d)).fetchone()
            if not cur or cur[1]!=f'user_supplied:{batch_id}' or not math.isclose(cur[0],new,rel_tol=1e-12):
                raise ValueError(f'Annullamento bloccato: il valore del {d} è stato modificato successivamente')
        for d,new,old,src,stamp in changes:
            if old is None:
                c.execute(('DELETE FROM index_prices WHERE series_id=? AND date=?' if kind=='index' else
                           'DELETE FROM fx_rates WHERE fx_code=? AND date=?'),(code,d))
            elif kind=='index':
                c.execute('UPDATE index_prices SET level=?,source=?,imported_at=? WHERE series_id=? AND date=?',
                          (old,src,stamp,code,d))
            else:
                c.execute('UPDATE fx_rates SET rate=?,source=? WHERE fx_code=? AND date=?',(old,src,code,d))
        now=datetime.now(timezone.utc).isoformat()
        c.execute('UPDATE benchmark_user_imports SET undone_at=? WHERE id=?',(now,batch_id))
        if kind=='index':
            c.execute('UPDATE index_series SET last_fetch_at=?,last_fetch_status=?,last_source=? WHERE series_id=?',
                      (now,'manual_import_undone',f'undone:{batch_id}',code))
    return {'restored':len(changes),'batch_id':batch_id}


def export_csv(store:IndexStore,code:str)->bytes:
    _target_kind(code, store)
    result=io.StringIO(newline='')
    writer=csv.writer(result,delimiter=';')
    writer.writerow(('Data','Valore'))
    for d,v in _read_target(store,code).items():
        writer.writerow((datetime.strptime(d,'%Y-%m-%d').strftime('%d/%m/%Y'),format(v,'.12g')))
    return result.getvalue().encode('utf-8-sig')
