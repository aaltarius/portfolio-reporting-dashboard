"""Verifica NON distruttiva: JSON privi di benchmark operativi e SQLite integro."""
from __future__ import annotations
import argparse,json,sqlite3
from pathlib import Path
from core.verified_benchmarks.store import db_path
from persistence.storage import DATA_FILE

EXPECTED=('index_series','index_prices','fx_rates','instrument_override',
          'assignment_snapshot','assignment_history','benchmark_preferences')


def check(main:Path,db:Path)->dict:
    findings=[]
    if not main.is_file():return {'ok':False,'error':'JSON non trovato: '+str(main)}
    data=json.loads(main.read_text(encoding='utf-8-sig'))
    for key in ('benchmark_data','market_live_data'):
        if key in data:findings.append('Top-level JSON: '+key)
    for i,inst in enumerate(data.get('strumenti') or []):
        if not isinstance(inst,dict):continue
        if 'benchmark' in inst:findings.append(f'strumenti[{i}].benchmark')
        src=inst.get('enrichment_source') or {}
        if isinstance(src,dict) and 'benchmark' in src:
            findings.append(f'strumenti[{i}].enrichment_source.benchmark')
    for ticker,entry in (data.get('instrument_master') or {}).items():
        if not isinstance(entry,dict):continue
        for key in ('benchmark_code','benchmark_label','auto_benchmark_fallback'):
            if key in entry:findings.append(f'instrument_master.{ticker}.{key}')
        sator=((entry.get('manual_overrides') or {}).get('sator') or {})
        for key in ('benchmark_code','benchmark_label','benchmark_user_edited'):
            if key in sator:findings.append(f'instrument_master.{ticker}.sator.{key}')
    if not db.is_file():return {'ok':False,'error':'SQLite non trovato: '+str(db),'residuals':findings}
    try:
        with sqlite3.connect(f'file:{db.as_posix()}?mode=ro',uri=True) as con:
            tables={row[0] for row in con.execute('SELECT name FROM sqlite_master WHERE type=\'table\'')}
            missing=sorted(set(EXPECTED)-tables)
            manual=con.execute('SELECT COUNT(*) FROM instrument_override').fetchone()[0] if not missing else -1
            prices=con.execute('SELECT COUNT(*) FROM index_prices').fetchone()[0] if not missing else -1
            duplicates=con.execute('SELECT COUNT(*) FROM (SELECT series_id,date FROM index_prices GROUP BY series_id,date HAVING COUNT(*)>1)').fetchone()[0] if not missing else -1
    except sqlite3.Error as exc:
        return {'ok':False,'error':'SQLite illeggibile: '+str(exc),'residuals':findings}
    return {'ok':not findings and not missing and not manual and duplicates==0,
            'database':str(db),'json':str(main),'residuals':findings,'missing_tables':missing,
            'manual_overrides':manual,'price_observations':prices,'duplicate_series_days':duplicates,
            'instrument_underlyings':sum(bool(x.get('indice_sottostante')) for x in data.get('strumenti',[]) if isinstance(x,dict))}


def main(argv=None):
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--json',type=Path,default=Path(DATA_FILE))
    a.add_argument('--db',type=Path,default=db_path())
    args=a.parse_args(argv)
    result=check(args.json,args.db)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['ok'] else 2

if __name__=='__main__':raise SystemExit(main())
