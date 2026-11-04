"""Download incrementali: indici veri, ETF proxy e indice BCE €STR.

La sorgente viene tracciata e non si sovrascrivono dati preesistenti.
"""
from __future__ import annotations
import csv
import io
import os
import logging
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote,urlparse
import requests
from .store import IndexStore

logger=logging.getLogger(__name__)

def fetch_yahoo(code: str, start: str|None=None, *,timeout:float=12.0) -> dict[str,float]:
    """Endpoint Yahoo Chart; solo simboli gia' registrati in archivio."""
    from datetime import datetime
    from urllib.parse import quote
    end=int(datetime.now(timezone.utc).timestamp())+86400
    p1=int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp()) if start else 0
    url='https://query1.finance.yahoo.com/v8/finance/chart/'+quote(code,safe='')
    r=requests.get(url,params={'period1':p1,'period2':end,'interval':'1d'},
                   headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'},timeout=timeout)
    r.raise_for_status()
    result=(r.json().get('chart') or {}).get('result') or []
    if not result:return {}
    ts=result[0].get('timestamp') or []
    indicators=result[0].get('indicators') or {}
    quotes=((indicators.get('quote') or [{}])[0].get('close') or [])
    # Gli ETF a distribuzione vanno confrontati preferibilmente con il loro
    # prezzo adjusted close. La normalizzazione resta esplicita nel catalogo.
    # Per gli indici adjclose coincide con la chiusura; per gli ETF include i dividendi.
    adjusted=(indicators.get('adjclose') or [{}])[0].get('adjclose') or []
    if len(adjusted)==len(quotes) and any(v is not None for v in adjusted):
        quotes=[a if a is not None else b for a,b in zip(adjusted,quotes)]
    out={}
    for t,v in zip(ts,quotes):
        if v is None or float(v)<=0:continue
        day=datetime.fromtimestamp(t,timezone.utc).date().isoformat()
        out[day]=float(v)
    return out

def fetch_fred(code: str,start: str|None=None, *,timeout:float=6.0) -> dict[str,float]:
    # URL pubblico dei valori, non un indice ricostruito.
    import csv,io
    rawcode=code.removeprefix('FRED:')
    r=requests.get('https://fred.stlouisfed.org/graph/fredgraph.csv',
                   params={'id':rawcode,**({'cosd':start} if start else {})},
                   headers={'User-Agent':'Mozilla/5.0'},timeout=timeout)
    r.raise_for_status()
    out={}
    for row in csv.DictReader(io.StringIO(r.text)):
        try:
            day=row.get('observation_date') or row.get('DATE') or row.get('date')
            value=float(row.get(rawcode,''))
            if date.fromisoformat(day) and value>0:out[day]=value
        except (ValueError,TypeError,KeyError):pass
    return out

def fetch_ecb(code: str,start: str|None=None, *,timeout:float=12.0)->dict[str,float]:
    """Livelli dell'indice composto €STR, NON il tasso percentuale €STR."""
    if code!='ECB:EST.B.EU000A2QQF08.CI':
        raise ValueError(f'Serie BCE non censita: {code}')
    url='https://data-api.ecb.europa.eu/service/data/EST/B.EU000A2QQF08.CI'
    params={'format':'csvdata'}
    if start:params['startPeriod']=start
    response=requests.get(url,params=params,headers={'Accept':'text/csv','User-Agent':'PortfolioBenchmark/2.0'},timeout=timeout)
    response.raise_for_status()
    out={}
    for row in csv.DictReader(io.StringIO(response.text)):
        try:
            day=(row.get('TIME_PERIOD') or '').strip()[:10]
            value=float(row.get('OBS_VALUE') or '')
            if date.fromisoformat(day) and value>0:out[day]=value
        except (ValueError,TypeError):pass
    return out



def fetch_authorized_csv(code:str,start:str|None=None,*,timeout:float=12.0)->dict[str,float]:
    """Utilizza SOLO feed CSV HTTPS esplicitamente configurato dall'operatore.

    Non ipotizza URL Investing.com/Bloomberg. Senza URL autorizzato
    l'indice resta 'licensed_data_required', con i dati locali conservati.
    Una riga CSV deve riportare Date e Price/Level; l'indice è dichiarato
    nella chiave della variabile d'ambiente, non dedotto dal file.
    """
    from .import_csv import inspect_index_csv
    url=os.environ.get('SESTANTE_BLOOMBERG_'+code+'_CSV_URL','').strip()
    parsed=urlparse(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Configurare un URL HTTPS autorizzato per '+code)
    # Non si registrano credenziali, query string o URL negli errori.
    headers={'User-Agent':'SestanteBenchmark/5.3','Accept':'text/csv'}
    key=os.environ.get('SESTANTE_BLOOMBERG_CSV_API_TOKEN','').strip()
    if key:headers['Authorization']='Bearer '+key
    response=requests.get(url,headers=headers,timeout=timeout,allow_redirects=False)
    response.raise_for_status()
    if response.status_code!=200 or not response.content or len(response.content)>12_000_000:
        raise ValueError('Feed CSV vuoto o troppo grande')
    report=inspect_index_csv(response.content,min_points=1)
    return {d:v for d,v in report.values.items() if start is None or d>=start}


def refresh_index(store: IndexStore,code: str, *,force:bool=False,days_fresh:int=2,
                  yahoo_fetch=fetch_yahoo,fred_fetch=fetch_fred) -> dict:
    spec=store._spec(code)
    configured=bool(os.environ.get('SESTANTE_BLOOMBERG_'+code+'_CSV_URL','').strip()) if spec.provider=='licensed' else False
    if spec.provider in ('cf','lbma') or (spec.provider=='licensed' and not configured):
        # Dati di indici soggetti a licenza: l'API pubblica non offre uno storico
        # ufficiale riutilizzabile. Nessuna curva sintetica o falso download.
        last=store.last_date(code)
        if last and (date.today()-date.fromisoformat(last)).days<=days_fresh:
            return {'code':code,'status':'fresh','last_date':last,'added':0}
        return {'code':code,'status':'licensed_data_required','last_date':last,
                'added':0,'reason':'Serve storico indice Bloomberg ottenuto da fonte autorizzata: '+spec.url}
    state=store.fetch_state(code)
    last=store.last_date(code)
    # Evita scaricamenti ripetuti quando il provider e' temporaneamente bloccato.
    last_fetch=state.get('last_fetch_at')
    if not force and last_fetch:
        try:
            previous_status=str(state.get('last_fetch_status') or '')
            # Errore 404: non ripetere lo stesso URL ad ogni clic. La serie
            # rimane NON disponibile, non e' presentata come cache riuscita.
            cooldown=(timedelta(hours=24) if previous_status.endswith(':404') else
                      timedelta(minutes=15) if previous_status.startswith('error:') else
                      timedelta(minutes=60))
            if datetime.now(timezone.utc)-datetime.fromisoformat(last_fetch)<cooldown:
                if previous_status.startswith('error:'):
                    return {'code':code,'status':'retry_deferred','last_date':last,'added':0,
                            'reason':'Fonte non disponibile nell’ultimo tentativo; nuova prova rinviata ('+
                                     ('404, simbolo non trovato' if previous_status.endswith(':404') else 'errore provider')+')'}
                return {'code':code,'status':'cached','last_date':last,'added':0}
        except (ValueError,TypeError):pass
    if not force and last and (date.today()-date.fromisoformat(last)).days<=days_fresh:
        return {'code':code,'status':'fresh','last_date':last,'added':0}
    start=(date.fromisoformat(last)-timedelta(days=7)).isoformat() if last else None
    try:
        if spec.provider=='yahoo':retrieved=yahoo_fetch(code,start)
        elif spec.provider=='fred':retrieved=fred_fetch(code,start)
        elif spec.provider=='ecb':retrieved=fetch_ecb(code,start)
        elif spec.provider=='licensed':retrieved=fetch_authorized_csv(code,start)
        elif spec.provider in ('cf','lbma'):
            return {'code':code,'status':'manual_import_required','last_date':last,
                    'reason':'Storico ufficiale con possibile licenza: importare un CSV tracciabile, mai sintetizzare prezzi.'}
        else:raise ValueError('Provider non gestito: '+spec.provider)
        if not retrieved:raise ValueError('Storico remoto vuoto')
        # Non sostituisce valori storici preesistenti, evita regressioni su cache.
        provenance='licensed_csv' if spec.provider=='licensed' else spec.provider
        added=store.upsert(code,retrieved,source=provenance,replace_existing=False)
        store.mark_fetch(code,'ok',provenance)
        return {'code':code,'status':'updated' if added else 'unchanged',
                'last_date':store.last_date(code),'added':added}
    except Exception as exc:
        logger.warning('Indice %s: aggiornamento impossibile (%s)',code,exc)
        http_status=getattr(getattr(exc,'response',None),'status_code',None)
        status_tag=f'error:{type(exc).__name__}'+(f':{http_status}' if http_status else '')
        store.mark_fetch(code,status_tag,spec.provider)
        if http_status==404:
            reason='HTTP 404: il provider '+spec.provider+' non trova lo storico del simbolo '+code
        elif http_status==429:
            reason='HTTP 429: il provider '+spec.provider+' ha limitato temporaneamente le richieste'
        else:
            reason=str(exc)
        return {'code':code,'status':'failed','reason':reason,'last_date':last,'added':0}


def refresh_fx(store:IndexStore, code:str='EURUSD=X', *,fetcher=fetch_yahoo)->dict:
    """Fonte ausiliaria: CAMBI, non benchmark. Backfill fino all'inizio."""
    if code not in ('EURUSD=X','EURGBP=X','EURJPY=X','EURCHF=X'):
        return {'code':code,'status':'not_allowed'}
    old=store.read_fx(code)
    start=min(old) if old else None
    # Si richiede lo storico completo anche se il precedente JSON contiene
    # pochi mesi: altrimenti la conversione troncava il benchmark al 2026.
    try:
        fresh=fetcher(code,None if start and start>'2022-01-01' else (max(old) if old else None))
        n=store.upsert_fx(code,fresh,source='yahoo_fx')
        return {'code':code,'status':'updated' if n else 'unchanged','added':n}
    except Exception as exc:
        logger.warning('FX %s: dati non aggiornati: %s',code,exc)
        return {'code':code,'status':'failed','reason':str(exc)}
