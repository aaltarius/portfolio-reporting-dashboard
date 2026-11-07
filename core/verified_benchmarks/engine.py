"""Risoluzione del benchmark di uno strumento dall'ARCHIVIO (ADR-0021).

Nessuna scala, nessun elenco di strumenti: la scelta nasce dalla ricerca sul web
(`core/benchmark_discovery`, solo su comando dell'utente) e qui si legge soltanto
quanto e' stato salvato. Una scelta manuale prevale sempre.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from .store import IndexStore
from .composite import in_eur
from .freshness import is_current_series


@dataclass
class Resolution:
    ticker: str
    label: str
    grade: str
    kind: str
    source: str
    family: str
    series: dict[str,float] = field(default_factory=dict)
    components: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    confidence: str = 'Bassa'
    coverage_start: str = ''
    coverage_end: str = ''
    currency: str = 'EUR'
    def metadata(self) -> dict:
        return {k:v for k,v in vars(self).items() if k!='series'} | {'points':len(self.series)}


def _series_eur(store:IndexStore,code:str,*,convert:bool=True)->tuple[dict[str,float],str]:
    spec=store._spec(code); prices=store.read(code)
    if spec.currency=='EUR' or not convert:return prices,spec.currency
    fx={'USD':'EURUSD=X','GBP':'EURGBP=X','JPY':'EURJPY=X','CHF':'EURCHF=X'}.get(spec.currency)
    if not fx:return {},f'{spec.currency} (cambio non supportato)'
    return in_eur(prices,spec.currency,store.read_fx(fx))


def _stored_resolution(ticker:str,store:IndexStore)->Resolution|None:
    """Scelta manuale dell'utente, poi ultima decisione della scoperta dal web: serie e traccia vengono
    dall'archivio (mai dalla rete). None se non esiste nessuna delle due."""
    override=store.override(ticker)
    a=store.assignment(ticker)
    discovered=bool(a and a.get('discovery'))
    if not override and not discovered:return None
    if override:
        code=override['benchmark_code']
        try:series=store.read(code)
        except ValueError:series={}
        if series:
            spec=store._spec(code)
            label=override.get('benchmark_label') or spec.label
            notes=["Scelta manuale dell'utente: prevale sulla ricerca automatica."]
            if a and a.get('ticker')==code:notes+=list(a.get('notes') or [])
            return _with_freshness(Resolution(code,label,'MANUALE',spec.asset_kind,"Scelta manuale dell'utente",
                spec.family,series,[{'series_id':code,'label':label,'weight_pct':100.0,'currency':spec.currency,
                'kind':spec.asset_kind,'url':spec.url,'source':spec.provider}],notes,'Media',min(series),max(series),spec.currency))
    if discovered:
        code=a.get('ticker')
        try:series=store.read(code)
        except ValueError:series={}
        if series:
            return _with_freshness(Resolution(code,a.get('label') or code,a.get('grade') or 'NONNA',a.get('kind') or 'etf_proxy',
                a.get('source') or 'Scoperta dal web',a.get('family') or '',series,list(a.get('components') or []),
                list(a.get('notes') or []),a.get('confidence') or 'Bassa',min(series),max(series),a.get('currency') or 'EUR'))
    return None


def _with_freshness(res:Resolution)->Resolution:
    if not is_current_series(res.series):
        res.notes.append('Serie non aggiornata: ricalcolare il benchmark su comando per scaricare i dati recenti.')
    return res


def resolve(inst:dict,master:dict|None=None,*,store:IndexStore|None=None,
            online:bool=False,min_points:int=20,min_start:str|None=None,
            allow_unconverted:bool=False,record_assignment:bool=True,
            product_isins:dict[str,str]|None=None)->Resolution|None:
    """Scelta manuale, poi ultima decisione della scoperta; None se lo strumento non e' ancora stato calcolato."""
    master=master if isinstance(master,dict) else {}
    ticker=str(inst.get('ticker') or master.get('ticker') or '').strip()
    if not ticker:return None
    return _stored_resolution(ticker,store or IndexStore())


def for_ticker(data:dict,ticker:str,*,store:IndexStore|None=None,online:bool=False,
               record_assignment:bool=True)->Resolution|None:
    inst=next((x for x in data.get('strumenti',[]) if str(x.get('ticker'))==ticker),None)
    if inst is None:return None
    return resolve(inst,(data.get('instrument_master') or {}).get(ticker),store=store)


def stored_history(data:dict,code:str,*,store:IndexStore|None=None)->dict[str,float]:
    store=store or IndexStore()
    try:
        s,cur=_series_eur(store,code)
    except ValueError:
        return {}
    # Una serie ferma da giorni resta disponibile: la freschezza si segnala (freshness.staleness), non si nasconde.
    return s if s and cur=='EUR' else {}
