"""Importazione CONTROLLATA di uno storico ufficiale acquisito dall'utente.

Il programma non simula dati né preleva l'indice con scraping non autorizzato.
Esempio:
 python -m tools.import_benchmark_csv --code LBMA:GOLD_PM_USD --csv oro.csv \
     --source-url https://www.ice.com/iba/lbma-gold-price --apply

CSV UTF-8 o UTF-8 BOM con colonne date,level (alias data/valore, DATE/VALUE).
Anteprima di default. Sovrascrive osservazioni precedenti SOLO con --replace.
"""
from __future__ import annotations
import argparse,csv,json,math
from pathlib import Path
from datetime import date
from core.verified_benchmarks import IndexStore


def parse_file(path:Path)->dict[str,float]:
    with path.open('r',encoding='utf-8-sig',newline='') as stream:
        text=stream.read(4096)
        stream.seek(0)
        dialect=csv.Sniffer().sniff(text,delimiters=',;\t')
        rows=csv.DictReader(stream,dialect=dialect)
        names={str(x).strip().lower():x for x in (rows.fieldnames or [])}
        dkey=next((names[c] for c in ('date','data','observation_date','time_period') if c in names),None)
        vkey=next((names[c] for c in ('level','value','valore','obs_value','price') if c in names),None)
        if not dkey or not vkey:
            raise ValueError('CSV non riconosciuto: richieste colonne date,level oppure data,valore')
        out={}
        for lineno,row in enumerate(rows,2):
            day=str(row.get(dkey) or '').strip()
            value=str(row.get(vkey) or '').strip().replace(',','.')
            if not day and not value:continue
            try:
                day=date.fromisoformat(day[:10]).isoformat()
                val=float(value)
                if not(math.isfinite(val) and val>0):raise ValueError()
                if day in out and abs(out[day]-val)>1e-9:
                    raise ValueError('duplicate')
                out[day]=val
            except ValueError as exc:
                raise ValueError(f'CSV riga {lineno}: data, valore o duplicato non valido: {day}, {value}') from exc
    if len(out)<2:raise ValueError('Storico insufficiente: meno di due valori validi')
    return dict(sorted(out.items()))


def import_csv(path:Path,code:str,source_url:str,db:Path|None=None,*,apply=False,replace=False)->dict:
    store=IndexStore(db)
    if not store.has_series(code):raise ValueError('Codice non registrato in archivio: '+code)
    if not (source_url.startswith('https://') and '.' in source_url):
        raise ValueError('Indicare un URL HTTPS del fornitore come fonte, non una descrizione libera')
    prices=parse_file(path)
    out={'code':code,'series_name':store._spec(code).label,'source_url':source_url,
         'source_file':str(path),'n_prices':len(prices),'first':min(prices),'last':max(prices),
         'mode':'apply' if apply else 'dry_run','replaced':bool(replace)}
    if apply:
        out['inserted_or_updated']=store.upsert(code,prices,source='source_csv:'+source_url,
                                                 replace_existing=replace)
        out['db']=str(store.path)
    return out


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--code',required=True)
    p.add_argument('--csv',required=True,type=Path)
    p.add_argument('--source-url',required=True)
    p.add_argument('--db',type=Path)
    p.add_argument('--apply',action='store_true')
    p.add_argument('--replace',action='store_true')
    a=p.parse_args(argv)
    print(json.dumps(import_csv(a.csv,a.code,a.source_url,a.db,apply=a.apply,replace=a.replace),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
