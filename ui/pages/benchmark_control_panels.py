"""Presentazione modulare del Centro benchmark.

Dati ricevuti dal core; componenti di tabella senza overflow incorporato e
palette/temi condivisi. Nessuna rete o lettura delle curve storiche.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

from core.services.benchmark_control import _short_label, STALE_DAYS
from ui.components import kpi_card, render_section_title
from ui.pages.benchmark_tables import render_benchmark_table
from ui.theme import P


RELATION_EXPLAIN={
    'PROPRIO':('Indice proprio','Riferimento della stessa famiglia dell’indice dichiarato; verificare comunque variante PR/TR, valuta e distribuzioni.'),
    'SORELLA':('Sorella','Altro prodotto o indice molto vicino; costi, selezione, copertura valutaria o dividendi possono variare.'),
    'MADRE':('Madre','Rappresenta un universo piu ampio: e utile per orientarsi, NON per attribuire in modo certo l’extra-rendimento.'),
    'NONNA':('Nonna','Riferimento ancora piu generale: possibili differenze strutturali importanti.'),
    'ZIA':('Zia','Settore o mercato correlato ma differente: il dato e soltanto esplorativo.'),
    'ULTIMO_PARENTE':('Ultimo parente','Ultimo riferimento disponibile: evitare giudizi di sovra/sottoperformance.'),
    'PROPRIA':('Indice proprio','L’indice dichiarato dallo strumento; verificare comunque variante e valuta.'),
    'CUGINA':('Cugina','Stesso tema o area ma non lo stesso indice: utile per orientarsi, non per attribuire con certezza l’extra-rendimento.'),
    'MANUALE':('Scelta manuale','Benchmark fissato dall’utente: prevale sulla ricerca automatica.'),
    'COMPOSITO':('Composito','Combinazione a pesi espliciti; rappresenta un comparatore strategico, non le partecipazioni correnti.'),
}


def _date(value:Any)->str:
    try:return datetime.strptime(str(value or '')[:10],'%Y-%m-%d').strftime('%d/%m/%Y')
    except ValueError:return '—'


def _datetime(value:Any)->str:
    try:return datetime.fromisoformat(str(value).replace('Z','+00:00')).astimezone().strftime('%d/%m/%Y %H:%M')
    except ValueError:return 'Mai registrato'


def _number(value:Any)->float|None:
    try:
        if pd.isna(value):return None
        return float(value)
    except (ValueError,TypeError):return None


def _percent(value:Any,*,signed:bool=False)->str:
    n=_number(value)
    if n is None:return '—'
    return f'{n*100:+.1f}%' if signed else f'{n*100:.1f}%'


def _grade(value:Any)->str:
    return str(value or 'NON_RISOLTO').upper()


def _relation_text(grade:str)->str:
    return RELATION_EXPLAIN.get(grade,('Da verificare','Identità economica non sufficientemente documentata.'))[1]


def _used_series_codes(snapshot:dict)->set[str]:
    """Serie realmente assegnate; quelle in catalogo non pesano sui KPI attivi."""
    result=set()
    for a in (snapshot.get('assignments') or {}).values():
        if not isinstance(a,dict):continue
        code=str(a.get('ticker') or '')
        if code:result.add(code)
        for leg in (a.get('components') or []):
            if isinstance(leg,dict):
                c=str(leg.get('series_id') or '')
                if c:result.add(c)
    return result


def _assigned_series(snapshot:dict, assignment:dict) -> list[dict]:
    """Ritorna tutte le gambe presenti nello store per un singolo abbinamento."""
    by_code = snapshot.get('series_by_code') or {}
    components = assignment.get('components') or []
    codes = [str(x.get('series_id')) for x in components if isinstance(x,dict) and x.get('series_id')]
    if not codes:
        codes = [str(assignment.get('ticker') or '')]
    return [by_code.get(code) or {} for code in codes if code]


def _series_condition(assignment:dict, snapshot:dict) -> tuple[bool,bool,bool]:
    """(assenza storico, storico datato, fonte legacy), per tutte le gambe."""
    series = _assigned_series(snapshot,assignment)
    if not series:
        return True, False, False
    missing = any(not s or s.get('points',0)<20 for s in series)
    stale = any(not s or s.get('age_days') is None or
                s['age_days'] > STALE_DAYS or s['age_days']<0 for s in series)
    legacy = any(bool(s.get('source_warning')) for s in series)
    return missing,stale,legacy


def render_health(snapshot:dict)->None:
    """Riepilogo di qualità in UNA riga, senza quattro KPI duplicati.

    La disponibilità dei dati non certifica automaticamente la qualità
    economica del benchmark, né il trattamento dei dividendi o dei cambi.
    """
    assigned=snapshot.get('assignments') or {}
    total=int(snapshot.get('instrument_count') or 0)
    resolved=int(snapshot.get('resolved_snapshots') or 0)
    conditions=[_series_condition(a,snapshot) for a in assigned.values()
                if isinstance(a,dict) and a.get('ticker')]
    paused=sum(bool(missing or stale or legacy) for missing,stale,legacy in conditions)
    old=sum(bool(stale) for _,stale,_ in conditions)
    uncertain=sum(bool(legacy) for _,_,legacy in conditions)
    st.caption(
        '**Stato dei dati:** '+str(resolved)+'/'+str(total)+' strumenti con riferimento'
        ' · '+str(paused)+' confronti sospesi'
        ' · '+str(old)+' serie da aggiornare'
        ' · '+str(uncertain)+' fonti da verificare'
        ' · ultima data archivio '+_date(snapshot.get('last_market_date'))+'.'
    )


def _inference(grade:str,kind:str,stale:bool,legacy:bool,missing:bool=False)->tuple[str,str]:
    if missing:
        return 'Dati mancanti','Mancano quotazioni sufficienti per confrontare le performance.'
    if stale:
        return 'Da aggiornare','Il benchmark ha osservazioni troppo vecchie: il confronto corrente è sospeso.'
    if legacy:
        return 'Storico incerto','Lo storico contiene valori di provenienza o rettifica non ancora verificata: il confronto è sospeso.'
    if grade in ('MADRE','CUGINA','NONNA','ZIA','ULTIMO_PARENTE'):
        return 'Confronto indicativo','L’indice rappresenta un mercato diverso o più ampio. Le differenze di rendimento non dimostrano una sovra/sottoperformance.'
    if kind=='composite':
        return 'Strategico, non reale','Il confronto rappresenta una combinazione teorica, non le posizioni effettive del fondo.'
    if kind in ('etf_proxy','spot_proxy'):
        return 'Proxy da interpretare','Dati disponibili; il proxy può differire per costi, coperture e dividendi.'
    return 'Dati disponibili','Serie corrente, ma confrontabilità di valuta, rendimento totale e metodologia non automaticamente certificata.'


def render_relation_guide() -> None:
    """Chiarimento del metodo, non seconda tabella di classificazione."""
    st.caption(
        '**Come leggere la parentela:** Proprio = indice specifico; '
        'Sorella = stesso mercato con metodo/prodotto diverso; '
        'Madre = riferimento più ampio o meno fedele; Nonna/Zia = confronto distante. '
        'Un **composito** combina più serie: non è un grado superiore. '
        'La parentela non misura la qualità dei rendimenti né garantisce total return, copertura FX o aggiornamento.'
    )


def _main_rows(matrix: pd.DataFrame, snapshot: dict) -> list[dict]:
    """Una riga per strumento: etichette separate da qualità e parentela."""
    states=snapshot.get('series_by_code') or {}
    result=[]
    for _,rec in matrix.iterrows():
        ticker=str(rec.get('ticker') or '')
        code=str(rec.get('benchmark_ticker') or '')
        grade=_grade(rec.get('relation_grade'))
        kind=str(rec.get('benchmark_kind') or '')
        parts=rec.get('benchmark_components')
        legs=parts if isinstance(parts,(list,tuple)) else []
        codes=[str(x.get('series_id')) for x in legs if isinstance(x,dict) and x.get('series_id')] or [code]
        actual=[states.get(c) for c in codes]
        missing=(not code or not actual or any(not isinstance(x,dict) or x.get('points',0)<20 for x in actual))
        stale=any(x.get('age_days') is None or x['age_days']>STALE_DAYS or x['age_days']<0
                  for x in actual if isinstance(x,dict))
        legacy=any(x.get('source_warning') for x in actual if isinstance(x,dict))
        last=min((x.get('end') for x in actual if isinstance(x,dict) and x.get('end')),default='')
        quality,impact=_inference(grade,kind,stale,legacy,missing)
        extra=_number(rec.get('extra_return'))
        # Non presentare KPI relativi quando la serie e' assente, vecchia o incerta.
        extra_text='—' if (missing or stale or legacy) else f'{extra*100:+.1f} pp' if extra is not None else '—'
        result.append({'Strumento':ticker,'Categoria':str(rec.get('categoria') or 'ALTRO'),
                       'Riferimento':code or '—',
                       'Parentela':('Composito' if grade=='COMPOSITO' else grade.replace('_',' ').title()),
                       'Ultimo':_date(last),'Extra':extra_text,'Verifica':quality,
                       '_impact':impact,'_stale':stale,'_legacy':legacy,'_missing':missing,
                       '_last_iso':last,'_sources':sorted({src for item in actual if isinstance(item,dict)
                                            for src in (item.get('sources') or [])})})
    return result


def _selected_detail(rec: pd.Series, row: dict, snapshot: dict) -> None:
    """Diagnosi in italiano operativo: evidenza, conseguenza, prossimo passo."""
    ticker=str(rec.get('ticker') or '')
    code=str(rec.get('benchmark_ticker') or '—')
    grade=_grade(rec.get('relation_grade'))
    cat=str(rec.get('categoria') or 'ALTRO')
    from ui.theme import macro_color
    suspended=bool(row['_stale'] or row['_legacy'] or row['_missing'])
    st.markdown(f'**{ticker}** · Benchmark: **{code}** · Categoria: {cat}')
    a,b,c=st.columns(3)
    with a:kpi_card('Adeguatezza',row['Parentela'],'Grado di vicinanza economica',accent=macro_color(cat))
    with b:kpi_card('Ultimo prezzo',row['Ultimo'],'Della serie di confronto',accent=P['orange'] if suspended else P['blue'])
    with c:kpi_card('Confronto',('Sospeso' if suspended else 'Consultabile'),row['Verifica'],accent=P['orange'] if suspended else P['blue'])
    left,right=st.columns([1,1],gap='medium')
    with left:
        st.markdown('**Perché è stato scelto questo riferimento**')
        st.write(_relation_text(grade))
        label=rec.get('benchmark_label')
        if label:st.caption('Nome del riferimento: '+_short_label(str(label),150))
        note=str(rec.get('benchmark_note') or '').strip()
        if note:st.caption('Differenze conosciute: '+_short_label(note,280))
    with right:
        st.markdown('**Cosa possiamo concludere**')
        st.write(row['_impact'])
        if not suspended:
            st.caption('Dal '+_date(rec.get('period_start'))+' al '+_date(rec.get('period_end'))+
                       ' · Strumento '+_percent(rec.get('instrument_return'),signed=True)+
                       ' · Riferimento '+_percent(rec.get('benchmark_return'),signed=True)+
                       ' · Differenza '+row['Extra'])
            st.caption('Sono rendimenti relativi sul periodo comune, non guadagni personali.')
        else:
            st.caption('Rendimenti comparati, tracking error e scarto non sono esposti finché i dati non sono utilizzabili.')
    st.markdown('**Cosa deve succedere adesso**')
    if row['_missing']:
        st.warning('Manca uno storico sufficiente. Usa «Aggiorna serie e ricontrolla candidati» per cercare quotazioni; se non vengono recuperate, il confronto resta sospeso.')
    if row['_stale']:
        st.warning('L’ultima quotazione è del '+row['Ultimo']+'. Usa «Aggiorna serie e ricontrolla candidati». Se la fonte resta ferma, serve un altro indice o un proxy coerente: i vecchi valori non vanno presentati come aggiornati.')
    if row['_legacy']:
        sources=', '.join(row.get('_sources') or []) or 'non identificata'
        st.warning('**Storico di origine non ancora verificata.** Sono presenti dati importati o non certificati come rettificati (fonte registrata: '+sources+'). Non è necessariamente un errore, ma le percentuali potrebbero essere alterate dal cambio o dai dividendi. **Non devi correggerli manualmente:** occorre una ricostruzione e un confronto automatico con una fonte indipendente. Il normale aggiornamento degli ultimi prezzi non risolve da solo questa verifica.')
    if not suspended:
        if grade in ('MADRE','CUGINA','NONNA','ZIA','ULTIMO_PARENTE'):
            st.info('Valuta un indice più fedele prima di attribuire significato all’extra-rendimento. Nella sezione «Dove intervenire» trovi gli eventuali candidati; nessuna sostituzione è automatica.')
        elif grade=='COMPOSITO':
            st.info('Per confermare l’utilità del confronto servono i pesi della strategia e il loro periodo di validità, non le singole partecipazioni del fondo.')
        else:
            st.info('Non è richiesta un’azione immediata sui prezzi. PR/TR, valuta e politica di distribuzione restano caratteristiche da documentare prima di trattare il confronto come certificato.')
    legs=rec.get('benchmark_components')
    if isinstance(legs,(list,tuple)) and len(legs)>1:
        st.caption('Combinazione di riferimento: '+' + '.join(
            f"{x.get('series_id','—')} {float(x.get('weight_pct',0)):.0f}%"
            for x in legs if isinstance(x,dict)))


def render_assignments(matrix:pd.DataFrame|None,snapshot:dict)->None:
    render_section_title('Strumenti e benchmark',icon='quotes',
        comment='Stessa tabella di Quotazioni e Portafoglio. «Stato» descrive il dato, «Parentela» quanto il riferimento assomiglia allo strumento.')
    if not isinstance(matrix,pd.DataFrame) or matrix.empty:
        st.info('Analisi non disponibile: usa «Analizza benchmark» per ricostruirla.');return
    rows=_main_rows(matrix,snapshot)
    render_benchmark_table(rows,key='assignments',category_key='Categoria',
        instrument_key='Strumento',tone_key='Extra',
        columns=[('Strumento','Ticker'),('Categoria','Cat.'),('Riferimento','Benchmark'),
            ('Parentela','Parentela'),('Ultimo','Ultimo dato'),('Extra','Extra'),('Verifica','Stato')],
        widths=[15,6,18,12,14,12,18])
    st.caption('Extra = differenza dei rendimenti in punti percentuali sul periodo comune. '
               'Il trattino «—» indica che non è corretto mostrare il confronto, non che il rendimento sia zero.')
    render_relation_guide()
    # Dettaglio pronto nel normale render, ma collassato per dare priorità ai
    # dati comparativi: NON si usano lazy tab né aggiornamenti automatici.
    with st.expander('Approfondisci uno strumento', expanded=False):
        options=[str(x) for x in matrix['ticker'] if x]
        if options:
            tk=st.selectbox('Strumento da esaminare',options,
                            key='benchmark_center_instrument_detail')
            row=next((x for x in rows if x['Strumento']==tk),None)
            rec=matrix.loc[matrix['ticker']==tk].iloc[0]
            if row:_selected_detail(rec,row,snapshot)


