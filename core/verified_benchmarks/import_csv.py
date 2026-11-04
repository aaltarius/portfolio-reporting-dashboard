"""Acquisizione verificata di file CSV autorizzati per gli indici XDBC.

Non effettua scraping e non presume che un alias pubblicato da terzi sia
lo stesso indice Bloomberg. L'identità della serie viene scelta esplicitamente.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
from datetime import date, datetime
from typing import NamedTuple

from .store import IndexStore

DATE_ALIASES = {'date','data','day','giorno','time period','time_period'}
PRICE_ALIASES = {'price','close','closing price','last','level','value','valore','prezzo','obs_value'}

class HistoricalImport(NamedTuple):
    values: dict[str, float]
    oldest: str
    newest: str
    source_fingerprint: str
    unusually_large_changes: int


def _date(value: str) -> str:
    text = str(value or '').strip().strip('"')
    for fmt in ('%Y-%m-%d','%d/%m/%Y','%d.%m.%Y','%d-%m-%Y','%b %d, %Y','%B %d, %Y'):
        try:
            d = datetime.strptime(text, fmt).date()
            if d > date.today():
                raise ValueError('Data futura: '+text)
            return d.isoformat()
        except ValueError as exc:
            if str(exc).startswith('Data futura:'):
                raise
    raise ValueError('Formato data non riconosciuto: '+text)


def _positive_level(value: str) -> float:
    text = str(value or '').strip().replace('\u00a0','').replace(' ','').replace("'",'')
    if not text: raise ValueError('Livello vuoto')
    if ',' in text and '.' in text:
        # Individua il separatore decimale dal simbolo più a destra.
        text = text.replace('.','').replace(',','.') if text.rfind(',')>text.rfind('.') else text.replace(',','')
    elif ',' in text:
        if text.count(',')==1 and len(text.split(',')[-1])==3:
            raise ValueError('Separatore numerico ambiguo: usare 1234.567 oppure 1.234,56')
        text = text.replace(',','.') if text.count(',')==1 else text.replace(',','')
    level = float(text)
    if not math.isfinite(level) or level <= 0:
        raise ValueError('Livello non valido')
    return level


def inspect_index_csv(content: bytes, *, min_points: int=20) -> HistoricalImport:
    """Controlla il CSV prima di qualsiasi scrittura. Fallisce interamente su errori.

    Accetta una colonna data + prezzo/livello, incluse esportazioni in formato
    locale; non trasforma prezzi e non costruisce retroattivamente storici.
    """
    if not isinstance(content, bytes) or not content or len(content)>12_000_000:
        raise ValueError('Il CSV deve esistere ed essere inferiore a 12 MB')
    try:
        text=content.decode('utf-8-sig')
    except UnicodeDecodeError:
        text=content.decode('cp1252')
    try:
        dialect=csv.Sniffer().sniff(text[:32768],delimiters=',;\t')
    except csv.Error:
        dialect=csv.excel
    rows=csv.DictReader(io.StringIO(text,newline=''),dialect=dialect)
    if not rows.fieldnames:
        raise ValueError('Il CSV non contiene intestazioni')
    mapped={str(h or '').strip().lower():h for h in rows.fieldnames}
    date_col=next((mapped[x] for x in DATE_ALIASES if x in mapped),None)
    price_col=next((mapped[x] for x in PRICE_ALIASES if x in mapped),None)
    if not date_col or not price_col:
        raise ValueError('Sono richieste due colonne: Date/Data e Price/Close/Level')
    values={}
    count=0
    for row in rows:
        if not row or all(not str(x or '').strip() for x in row.values()):
            continue
        count+=1
        try:
            day=_date(row.get(date_col,''))
            val=_positive_level(row.get(price_col,''))
        except (ValueError,TypeError) as exc:
            raise ValueError(f'Riga {count+1} non valida: {exc}') from exc
        if day in values and abs(values[day]-val)>1e-9:
            raise ValueError('Valori diversi per la stessa data: '+day)
        values[day]=val
    if len(values)<min_points:
        raise ValueError(f'Storico insufficiente: {len(values)} giornate, ne servono almeno {min_points}')
    if min_points>=20 and (date.fromisoformat(max(values))-date.fromisoformat(min(values))).days < 20:
        raise ValueError('Intervallo temporale inferiore a 20 giorni')
    previous=None
    changes=0
    for d in sorted(values):
        if previous is not None and abs(values[d]/previous-1)>0.25:
            changes+=1
        previous=values[d]
    return HistoricalImport(values,min(values),max(values),
                            hashlib.sha256(content).hexdigest(),changes)


def import_index_csv(store:IndexStore, *, code:str, content:bytes, source:str) -> dict:
    """Importa soltanto nel benchmark richiesto, dopo verifica esplicita della fonte.

    L'etichetta source deve identificare una fonte realmente autorizzata;
    l'utente non può rietichettare automaticamente codici provider ambigui.
    """
    if not store.has_series(code) or store._spec(code).asset_kind != 'index':
        raise ValueError('Si possono importare soltanto indici gia registrati in archivio (non ETF, ETC o prezzi spot)')
    source=' '.join(str(source or '').split())
    if len(source)<8 or len(source)>240:
        raise ValueError('Indicare una provenienza riconoscibile del CSV (almeno 8 caratteri)')
    preview=inspect_index_csv(content)
    origin='authorized_csv:'+preview.source_fingerprint[:16]
    inserted=store.upsert(code, preview.values, source=origin,replace_existing=False)
    store.mark_fetch(code,'manual_import_ok',source[:200])
    return {'code':code,'loaded':len(preview.values),'added':inserted,
            'oldest':preview.oldest,'newest':preview.newest,
            'source':source,'sha256':preview.source_fingerprint,
            'large_changes':preview.unusually_large_changes}
