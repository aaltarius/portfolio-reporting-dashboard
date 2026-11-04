"""Gestione universale degli storici benchmark, senza download e senza nuove cache.

Il pannello e' in fondo a Cruscotti/Benchmark. Scrive solo dopo un click
esplicito, con convalida dei dati e tracciamento SQLite reversibile.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd
import streamlit as st

from core.verified_benchmarks.store import IndexStore
from core.verified_benchmarks.manual_history import (
    allowed_indices, FX_CODES, _read_target, parse_table, suggested_columns, parse_series, inspect_import,
    apply_import, last_imports, undo_import, export_csv, ParsedSeries,
)


def _it_date(iso: str)->str:
    try: return datetime.strptime(iso,'%Y-%m-%d').strftime('%d/%m/%Y')
    except ValueError:return iso


def _instrument_choices(data:dict)->dict[str,dict]:
    return {str(row['ticker']):row for row in (data.get('strumenti') or [])
            if isinstance(row,dict) and row.get('ticker')}


def _preferred_indices(ticker: str, data:dict)->list[str]:
    """Serie gia' scelta per lo strumento (decisione salvata in archivio), da proporre per prima."""
    if ticker == 'Tutti gli strumenti':return []
    from core.verified_benchmarks import IndexStore
    a=IndexStore().assignment(ticker) or {}
    code=str(a.get('ticker') or '')
    return [code] if code in allowed_indices() else []


def _display_table(parsed:ParsedSeries)->None:
    ordered=sorted(parsed.values.items())
    # Solo poche righe in anteprima, mai un componente che impaginale 5 anni.
    sample=(ordered[:4] + (ordered[-4:] if len(ordered)>4 else []))
    seen=set(); rows=[]
    for d,v in sample:
        if d not in seen:rows.append({'Data':_it_date(d),'Livello':v});seen.add(d)
    st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)


def _write_preview(store:IndexStore,code:str,parsed:ParsedSeries,source:str,
                   filename:str,key:str)->None:
    info=inspect_import(store,code,parsed)
    st.caption(f"**{len(parsed.values)} valori** ({_it_date(parsed.first)}–{_it_date(parsed.last)}) · "
               f"{info['new']} nuovi · {info['unchanged']} già uguali · {info['conflicts']} differenti")
    _display_table(parsed)
    if parsed.unusual_jumps:
        st.warning(f'{parsed.unusual_jumps} variazioni superiori al 25% tra osservazioni adiacenti: verifica scala, valuta e rettifiche prima di confermare.')
    if info['examples']:
        st.warning('**Conflitti con lo storico esistente:** ' + '; '.join(
            f'{_it_date(d)}: presente {old:g}, nuovo {new:g}' for d,old,new in info['examples'][:5]))
    if len(parsed.values)<20:
        st.info('Lo storico viene conservato anche se breve; pochi punti non bastano per un confronto finanziario completo.')
    mode=st.radio('Come gestire le date già presenti?',
                  ['Conserva i valori esistenti; aggiungi solo date nuove',
                   'Sostituisci anche i valori differenti (correzione registrata)'],
                  horizontal=False,key=f'{key}_conflict')
    correct=mode.startswith('Sostituisci')
    confirmed=st.checkbox('Confermo che la fonte corrisponde alla serie selezionata, con unità e valuta corrette, e che posso utilizzare questi dati.',key=f'{key}_confirm')
    if st.button('Salva nello storico SQLite',key=f'{key}_save',type='primary',
                 disabled=not confirmed or len(source.strip())<8):
        try:
            outcome=apply_import(store,code,parsed,source=source,filename=filename,
                                 mode='correct' if correct else 'append',
                                 expected_fingerprint=info['fingerprint'],confirmed=True)
            if outcome['batch_id']:
                st.success(f"Storico salvato: {outcome['inserted']} nuove date e "
                           f"{outcome['corrected']} correzioni. Operazione n. {outcome['batch_id']} reversibile.")
            else:
                st.info('Nessuna modifica: i valori sono già presenti o le differenze sono state conservate.')
            st.info('Per applicare i nuovi dati ai confronti, esegui «Verifica gli abbinamenti» e poi «Analizza benchmark». ' 
                    'Il caricamento non garantisce da solo che il benchmark sia congruente o che la valuta sia stata convertita.')
        except (ValueError,OSError) as exc:
            st.error('Importazione non effettuata: '+str(exc))


def _form_upload(store:IndexStore,code:str):
    st.caption('Carica un file CSV oppure XLSX con almeno due colonne: Data e Livello. '
               'Sono accettate date gg/mm/aaaa e valori con virgola decimale. '
               'Puoi scegliere le colonne anche se hanno nomi differenti.')
    st.download_button('Scarica un modello CSV vuoto',
                       data=b'\xef\xbb\xbfData;Valore\r\n',file_name='modello_storico_benchmark.csv',
                       mime='text/csv',key='manual_index_template')
    source=st.text_input('Fonte e provenienza dei dati',
                         placeholder='Per esempio: fornitore, indice esatto, documento e data di esportazione',
                         key='manual_index_source_file')
    file=st.file_uploader('Seleziona un CSV o un Excel (.xlsx)',type=['csv','xlsx'],
                          key='manual_index_uploaded')
    if file is None:return
    try:
        raw=file.getvalue()
        cols,rows=parse_table(raw,file.name)
        if len(cols)<2:raise ValueError('Occorrono almeno due colonne')
        default_date,default_value=suggested_columns(cols)
        a,b=st.columns(2)
        with a:
            date_col=st.selectbox('Colonna della data',cols,index=cols.index(default_date),key='manual_index_date_col')
        with b:
            value_options=[x for x in cols if x!=date_col]
            value_col=st.selectbox('Colonna del livello',value_options,
                                   index=value_options.index(default_value) if default_value in value_options else 0,
                                   key='manual_index_value_col')
        parsed=parse_series(cols,rows,date_col,value_col,raw)
    except (ValueError,KeyError,IndexError) as exc:
        st.error('Anteprima non disponibile: '+str(exc));return
    _write_preview(store,code,parsed,source,file.name,'manual_index_file')


def _form_paste(store:IndexStore,code:str):
    st.caption('Incolla due colonne copiate da Excel o da un sito finanziario, con o senza intestazioni. '
               'Esempio: Data;Valore. Prima di salvare vedrai tutte le anomalie.')
    source=st.text_input('Fonte dei valori incollati',
                         placeholder='Sito/fornitore, codice indice, data di consultazione',
                         key='manual_index_source_paste')
    pasted=st.text_area('Incolla qui le righe',height=145,
                        placeholder='Data;Valore\n29/10/2026;1034,56\n30/10/2026;1037,21',
                        key='manual_index_pasted')
    if not pasted.strip():return
    raw=pasted.encode('utf-8')
    try:
        cols,rows=parse_table(raw,'serie.csv')
        d,v=suggested_columns(cols)
        parsed=parse_series(cols,rows,d,v,raw)
    except (ValueError,IndexError) as exc:
        st.error('Controlla i valori incollati: '+str(exc));return
    _write_preview(store,code,parsed,source,'inserimento_da_appunti.csv','manual_index_paste')


def _form_single(store:IndexStore,code:str):
    st.caption('Per aggiungere una data mancante o correggere un singolo valore senza preparare un file.')
    with st.form('manual_index_single_form'):
        d=st.date_input('Data della quotazione',value=date.today(),format='DD/MM/YYYY')
        value=st.number_input('Livello dell’indice',min_value=0.00000001,value=100.0,format='%.6f')
        source=st.text_input('Fonte della quotazione',placeholder='Documento, provider o pagina della quotazione')
        correction=st.checkbox('Se la data esiste, autorizzo a correggere il valore precedente')
        confirm=st.checkbox('Confermo identità della serie, unità e valore inserito')
        submit=st.form_submit_button('Salva valore',type='primary')
    if not submit:return
    try:
        from hashlib import sha256
        iso=d.isoformat()
        text=f'{iso};{value}'.encode('utf-8')
        series=ParsedSeries({iso:float(value)},iso,iso,0,sha256(text).hexdigest())
        preview=inspect_import(store,code,series)
        if preview['conflicts'] and not correction:
            raise ValueError('Esiste già un valore diverso per questa data. Autorizza la correzione per sovrascriverlo.')
        result=apply_import(store,code,series,source=source,filename='modifica_manuale',
                            mode='correct' if correction else 'append',
                            expected_fingerprint=preview['fingerprint'],confirmed=confirm)
        st.success(f"Salvataggio completato: {result['inserted']} nuovo, {result['corrected']} corretto")
    except (ValueError,OSError) as exc:
        st.error('Valore non salvato: '+str(exc))


def _form_history(store:IndexStore,code:str):
    values=_read_target(store,code)
    if not values:
        st.caption('Nessuno storico memorizzato per questo indice.')
    else:
        ordered=sorted(values)
        st.caption(f'{len(values)} osservazioni · dal {_it_date(ordered[0])} al {_it_date(ordered[-1])}. '
                   'L’esportazione contiene i livelli effettivamente salvati, senza interpolazioni.')
        st.download_button('Esporta lo storico in CSV',data=export_csv(store,code),
                           file_name='storico_'+''.join(c if c.isalnum() else '_' for c in code)+'.csv',
                           mime='text/csv',key='manual_index_export')
    batches=last_imports(store,code)
    if not batches:return
    st.markdown('**Ultime importazioni manuali**')
    st.dataframe(pd.DataFrame([{
        'Operazione':x['id'], 'Data':x['at'][:19].replace('T',' '),
        'Fonte':x['source'][:75],'Nuove':x['inserted'],'Corrette':x['corrected'],
        'Annullata': 'Sì' if x['undone_at'] else 'No'
    } for x in batches]),hide_index=True,use_container_width=True)
    candidates=[x for x in batches if not x['undone_at']]
    if not candidates:return
    choice=st.selectbox('Operazione da annullare', [x['id'] for x in candidates],key='manual_index_batch_undo')
    confirmed=st.checkbox('Confermo il ripristino dei valori precedenti (solo se nessuno li ha modificati in seguito)',
                          key='manual_index_confirm_undo')
    if st.button('Annulla questa importazione',key='manual_index_undo',disabled=not confirmed):
        try:
            outcome=undo_import(store,code,choice)
            st.success(f"Operazione {choice} annullata: {outcome['restored']} osservazioni ripristinate/eliminate.")
        except (ValueError,OSError) as exc:
            st.error('Ripristino annullato: '+str(exc))


def render_manual_history(data:dict)->None:
    """Un solo punto di accesso per tutti gli strumenti e tutti i veri indici."""
    with st.expander('Gestione manuale degli storici · tutti gli strumenti',expanded=False):
        st.caption('Carica o correggi i livelli degli indici senza dipendere dai download automatici. '
                   'Il programma conserva lo storico originale, segnala le sovrapposizioni '
                   'e registra le modifiche. Non trasforma dati di ETF/ETC in indici.')
        all_indices=allowed_indices()
        all_instruments=_instrument_choices(data)
        instrument_options=['Tutti gli strumenti',*sorted(all_instruments)]
        suggested_instrument=st.session_state.get('benchmark_center_issue_selection','')
        instrument=st.selectbox('Strumento del portafoglio',instrument_options,
                                index=instrument_options.index(suggested_instrument) if suggested_instrument in instrument_options else 0,
                                key='manual_benchmark_instrument')
        suggested=_preferred_indices(instrument,data)
        if suggested:
            st.caption('Indici candidati già riconosciuti per lo strumento: '+', '.join(suggested[:8])+'. '
                       'Puoi scegliere un altro indice dal catalogo, ma il caricamento non modifica automaticamente la parentela.')
        category=st.radio('Tipo di serie da gestire',('Indice benchmark','Cambio valutario'),
                          horizontal=True,key='manual_index_kind')
        is_fx=category=='Cambio valutario'
        codes=sorted(FX_CODES) if is_fx else sorted(all_indices)
        initial=next((c for c in suggested if c in codes),codes[0]) if codes else ''
        if not codes:
            st.error('Catalogo non disponibile');return
        index=st.selectbox('Serie storica',codes,index=codes.index(initial),
                          format_func=lambda c: f'{c} · {FX_CODES[c] if is_fx else all_indices[c].label[:83]}',
                          key='manual_index_selected_fx' if is_fx else 'manual_index_selected_index')
        store=IndexStore()
        if is_fx:
            fx_values=_read_target(store,index)
            last_fx=max(fx_values) if fx_values else ''
            st.caption(f'**Cambio:** {index} · quotazione: {FX_CODES[index]} · '
                       f'**Ultima osservazione:** {_it_date(last_fx) if last_fx else "nessuna"}')
        else:
            spec=all_indices[index]
            last=store.last_date(index)
            st.caption(f'**Indice:** {spec.label} · **Valuta:** {spec.currency} · **Variante:** {spec.return_type} · '
                       f'**Ultima quotazione:** {_it_date(last) if last else "nessuna"}')
            if spec.currency!='EUR':
                st.info('Indice non denominato in euro: per un confronto in EUR può servire la serie '
                        'del cambio, caricabile da «Cambio valutario». La conversione spot non ricostruisce una copertura valutaria EUR hedged.')
        chosen=st.radio('Operazione',('Carica CSV/Excel','Incolla valori',
                                     'Inserisci o correggi una data','Esporta e annulla modifiche'),
                        horizontal=True,key='manual_index_mode')
        if chosen=='Carica CSV/Excel':_form_upload(store,index)
        elif chosen=='Incolla valori':_form_paste(store,index)
        elif chosen=='Inserisci o correggi una data':_form_single(store,index)
        else:_form_history(store,index)
        st.caption('Dopo il salvataggio, verifica gli abbinamenti e rigenera l’analisi Benchmark. '
                   'Le curve non si aggiornano durante il normale rendering perché Sestante usa la cache congelata.')
