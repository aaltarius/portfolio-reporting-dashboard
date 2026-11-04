"""Migrazione ESPLICITA dai vecchi JSON verso l'unico archivio benchmark SQLite.

Eseguire con l'app CHIUSA:
  python -m tools.migrate_benchmark_json              # anteprima
  python -m tools.migrate_benchmark_json --apply      # backup + import + rimozione

Nessun file sorgente viene modificato prima di averne creato una copia.
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from core.verified_benchmarks import IndexStore
from persistence.storage import DATA_FILE,SETTINGS_FILE,BENCHMARK_CACHE_FILE,MARKET_LIVE_FILE,BACKUP_DIR, _strip_benchmark_instruments, _strip_benchmark_master


def _read(path:Path)->dict:
    if not path.exists():return {}
    data=json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data,dict):raise TypeError(f'JSON root non oggetto: {path}')
    return data


def _atomic_json(path:Path,data:dict):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.migration_tmp')
    try:
        with open(tmp,'w',encoding='utf-8') as f:
            json.dump(data,f,ensure_ascii=False,indent=2,allow_nan=True)
            f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if tmp.exists():tmp.unlink()


def _copy_backup(files:list[Path],backup:Path,db:Path):
    backup.mkdir(parents=True,exist_ok=False)
    for f in files:
        if f.exists():shutil.copy2(f,backup/f.name)
    if db.exists():
        with sqlite3.connect(str(db)) as c,sqlite3.connect(str(backup/'benchmarks_before.sqlite3')) as dest:
            c.backup(dest) # WAL-safe; niente copia incompleta del journal



def _sqlite_legacy_refs(db:Path)->dict[str,tuple[str,str]]:
    """Sorgente recupero una tantum dei dati arricchiti migrati in V2.

    Il valore e' la descrizione dell'indice sottostante, non un override.
    """
    if not db.is_file():return {}
    with sqlite3.connect(str(db)) as con:
        exists=con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='instrument_reference'").fetchone()[0]
        if not exists:return {}
        return {str(tk):(str(label),str(src)) for tk,label,src in con.execute(
            'SELECT instrument_id,official_reference,source FROM instrument_reference')}


def _restore_underlyings(root:dict,old_refs:dict[str,tuple[str,str]])->list[str]:
    """Riporta nella scheda solo i dati descrittivi eventualmente persi nella V2."""
    restored=[]
    for inst in root.get('strumenti') or []:
        if not isinstance(inst,dict):continue
        ticker=str(inst.get('ticker') or '')
        if inst.get('indice_sottostante') or inst.get('benchmark') or ticker not in old_refs:
            continue
        label,origin=old_refs[ticker]
        if not label:continue
        inst['indice_sottostante']=label
        src=inst.setdefault('enrichment_source',{})
        if isinstance(src,dict) and not src.get('indice_sottostante'):
            src['indice_sottostante']=origin or 'legacy'
        restored.append(ticker)
    return restored

def migrate(main:Path,settings:Path,cache:Path,market_live:Path,backup_root:Path,
            *,db:Path|None=None,apply:bool=False)->dict:
    root=_read(main); settings_raw=_read(settings); old_cache=_read(cache)
    # Anteprima realmente non mutante: non inizializzare uno SQLite inesistente.
    from core.verified_benchmarks.store import _DEFAULT_DB
    db_path=Path(db) if db is not None else _DEFAULT_DB
    store=None if (not apply and not db_path.exists()) else IndexStore(db_path)
    sqlite_refs=_sqlite_legacy_refs(db_path)
    old_analysis_dir=main.parent.parent/'cache'/'instrument_analysis'
    analysis_resolution=_read(old_analysis_dir/'resolution.json')
    analysis_series=_read(old_analysis_dir/'series.json')
    scheduler_state_path=main.parent.parent/'config'/'benchmark_last_refresh.json'
    scheduler_state=_read(scheduler_state_path)
    analysis_scheduler_path=main.parent.parent/'cache'/'instrument_analysis_auto_refresh_state.json'
    analysis_scheduler_state=_read(analysis_scheduler_path)
    legacy={}
    for document in (root,old_cache):
        for key,points in (document.get('benchmark_data') or {}).items():
            if str(key).startswith('bench_') and isinstance(points,dict):
                legacy.setdefault(key,{}).update(points)
    instrument_masters=root.get('instrument_master') or {}
    refs=[];legacy_overrides_ignored=[]
    for inst in root.get('strumenti') or []:
        if not isinstance(inst,dict):continue
        ticker=str(inst.get('ticker') or '')
        if ticker and inst.get('benchmark'):
            refs.append((ticker,str(inst['benchmark']),str((inst.get('enrichment_source') or {}).get('benchmark') or 'legacy')))
    for ticker,entry in instrument_masters.items():
        if not isinstance(entry,dict):continue
        manual=((entry.get('manual_overrides') or {}).get('sator') or {})
        code=str(manual.get('benchmark_code') or entry.get('benchmark_code') or '')
        if code and store is not None and store.has_series(code):
            legacy_overrides_ignored.append((ticker,code))  # non sono decisioni utente comprovate
    settings_pref={k:settings_raw[k] for k in ('benchmarking','portfolio_benchmark_default') if k in settings_raw}
    live={}
    for source in (root,old_cache,_read(market_live)):
        if isinstance(source.get('market_live_data'),dict):live.update(source['market_live_data'])
    report={
        'action':'apply' if apply else 'dry_run',
        'legacy_series':len(legacy),'instrument_references':len(refs),
        'sqlite_legacy_reference_records':len(sqlite_refs),
        'manual_overrides_imported':0,'legacy_overrides_ignored':len(legacy_overrides_ignored),
        'settings_sections':list(settings_pref),
        'market_live_records':len(live),
        'analysis_resolution_entries':len(analysis_resolution),
        'analysis_series_entries':len(analysis_series),
        'scheduler_refresh_entries':len(scheduler_state),
        'analysis_scheduler_entries':len(analysis_scheduler_state),
        'existing_sqlite':store.summary() if store is not None else {'series':0,'indices':0,'etf_proxies':0,'prices':0},
    }
    if not apply:return report
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup=backup_root/('benchmark_migration_'+stamp)
    _copy_backup([main,settings,cache,market_live,
                  old_analysis_dir/'resolution.json',old_analysis_dir/'series.json',scheduler_state_path,analysis_scheduler_path],backup,store.path)
    report['backup_dir']=str(backup)
    recovered=_restore_underlyings(root,sqlite_refs)
    report['underlyings_restored_from_sqlite']=recovered
    # Prima importa; se la migrazione fallisce, JSON originali intatti.
    imported=store.import_legacy({'benchmark_data':legacy})
    for key,points in legacy.items():
        code=key.removeprefix('bench_')
        if not store.has_series(code) and code not in ('EURUSD=X','EURGBP=X','EURJPY=X','EURCHF=X'):
            # Non eliminare dati fuori catalogo: storico conservato come
            # market_reference NON candidato, in attesa di classificazione.
            store.upsert_market(code,points,'legacy_uncatalogued')
    # La descrizione dell'indice effettivamente replicato appartiene alla
    # scheda strumento (indice_sottostante), non va duplicata in SQLite.
    # SQLite conserva invece le ASSEGNAZIONI di confronto e gli storici.
    if analysis_resolution:store.save_preference('analysis_resolution_cache',analysis_resolution)
    if analysis_series:store.save_preference('analysis_series_cache',analysis_series)
    if scheduler_state:store.save_preference('benchmark_last_refresh',scheduler_state)
    if analysis_scheduler_state:store.save_preference('instrument_analysis_auto_refresh_state',analysis_scheduler_state)
    # Niente ripristino degli override legacy; neanche dei compositi manuali.
    if settings_pref:
        conf=dict(settings_pref.get('benchmarking') or {})
        conf.update(custom_enabled=False,custom_components=[],custom_name='')
        store.save_preference('portfolio_benchmark_settings',{
            'benchmarking':conf,
            'portfolio_benchmark_default':settings_pref.get('portfolio_benchmark_default','Blend automatico')})
    # Rimozione da JSON eseguita solo DOPO migrazione, sempre con backup.
    root.pop('benchmark_data',None)
    root.pop('market_live_data',None)
    root['strumenti']=_strip_benchmark_instruments(root.get('strumenti',[]))
    root['instrument_master']=_strip_benchmark_master(instrument_masters)
    settings_raw.pop('benchmarking',None)
    settings_raw.pop('portfolio_benchmark_default',None)
    _atomic_json(main,root)
    if settings.exists():_atomic_json(settings,settings_raw)
    if live:_atomic_json(market_live,{'market_live_data':live})
    # Ex-cache non si usa piu': backup preservato, poi archivio sorgente eliminato.
    # Il valore originario e' ora univoco nella scheda; cancellare soltanto
    # i duplicati delle schede effettivamente presenti. I riferimenti di
    # strumenti rimossi restano nello snapshot/archivio per reversibilita'.
    copied={str(x.get('ticker') or '') for x in root.get('strumenti',[]) if isinstance(x,dict) and x.get('indice_sottostante')}
    with sqlite3.connect(str(store.path),timeout=30) as conn:
        deleted=conn.executemany('DELETE FROM instrument_reference WHERE instrument_id=?',[(tk,) for tk in copied]).rowcount
        conn.commit()
    report['redundant_sqlite_references_removed']=deleted
    if cache.exists():cache.unlink()
    if scheduler_state_path.exists():scheduler_state_path.unlink()
    if analysis_scheduler_path.exists():analysis_scheduler_path.unlink()
    for old_name in ('resolution.json','series.json'):
        stale=old_analysis_dir/old_name
        if stale.exists():stale.unlink()
    report['import']=imported
    report['database_after']=store.summary()
    report['legacy_cache_deleted']=not cache.exists()
    return report


def main(argv=None)->int:
    p=argparse.ArgumentParser(description='Separa definitivamente dati benchmark JSON → SQLite')
    p.add_argument('--apply',action='store_true',help='Richiede applicazione esplicita; senza, solo anteprima')
    p.add_argument('--json',type=Path,default=Path(DATA_FILE))
    p.add_argument('--settings',type=Path,default=Path(SETTINGS_FILE))
    p.add_argument('--legacy-cache',type=Path,default=Path(BENCHMARK_CACHE_FILE))
    p.add_argument('--market-live',type=Path,default=Path(MARKET_LIVE_FILE))
    p.add_argument('--backup-root',type=Path,default=Path(BACKUP_DIR))
    p.add_argument('--db',type=Path,default=None)
    args=p.parse_args(argv)
    out=migrate(args.json,args.settings,args.legacy_cache,args.market_live,args.backup_root,db=args.db,apply=args.apply)
    print(json.dumps(out,indent=2,ensure_ascii=False,default=str))
    if not args.apply:print('ANTEPRIMA: nessun file modificato. Chiudere Streamlit e ripetere con --apply.')
    return 0

if __name__=='__main__':raise SystemExit(main())
