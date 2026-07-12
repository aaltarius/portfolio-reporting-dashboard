"""
ui/charts/settings.py — CABINA UNICA DEI GRAFICI PLOTLY

QUESTO È IL FILE DA MODIFICARE PER CAMBIARE L'ASPETTO DEI GRAFICI.

REGOLA BASE
- i builder in ui/charts/*.py costruiscono dati, tracce e calcoli.
- questo file decide layout/stile:
  titoli, font, assi, margini, legende, bottoni temporali, sfondi, griglie,
  range, formato k, protezione anti-taglio, annotazioni tecniche e MAX/MIN.

PRIORITÀ DEL TITOLO
1. Se charts.py passa un titolo dinamico valido, vince quello.
2. Se il titolo dinamico manca, è vuoto o è "undefined", viene usato title nel blocco CHARTS.
3. Se title=None, NON cancella il titolo dinamico: significa solo "nessun titolo fallback".
4. Se show_title=False, il titolo viene nascosto.

COME SI MODIFICA UN GRAFICO
- Per cambiare tutta la dashboard: modifica GLOBAL_STYLE.
- Per cambiare una famiglia di grafici: modifica time_margin_delta, bar_margin_delta, ecc.
- Per cambiare un solo grafico: cerca il suo chart_id in CHARTS.
- I grafici sono divisi per pagina/scheda: HOME, OVERVIEW, ANDAMENTO, QUOTAZIONI,
  ANALISI, CRUSCOTTI, CONFRONTO, SUMMARY.

MARGINI
- Usa margin_delta nel singolo grafico, non margin assoluti.
- margin_delta={"t":0,"b":0,"l":0,"r":0} = nessuna correzione.
- t positivo = più spazio sopra; t negativo = meno spazio sopra.
- b positivo = più spazio sotto; b negativo = meno spazio sotto.
- l positivo = più spazio a sinistra; r positivo = più spazio a destra.
- margin_override esiste solo per emergenze e vince su tutto.

GRAFICI BAR
- bar_width = spessore della barra (passato alle trace go.Bar).
- bargap = distanza tra categorie/barre adiacenti.
- bargroupgap = distanza tra barre nello stesso gruppo.
- row_height = spazio verticale assegnato a ogni barra/categoria nei grafici bar che lo supportano.
- min_height / max_height / height_base_pad = controlli opzionali per l'altezza dinamica.
- Se omessi, resta il comportamento standard del builder/di Plotly.
"""

from __future__ import annotations

from typing import Any

from ui.charts.axis_refs import (
    trace_xaxis_layout_name as _trace_xaxis_layout_name,
    trace_yaxis_layout_name as _trace_yaxis_layout_name,
)
from ui.charts.annotations import (
    add_quarter_gridlines as _add_quarter_gridlines_runtime,
    is_baseline_annotation as _is_baseline_annotation,
    normalise_annotations as _apply_annotation_normalisation,
    normalise_baseline_axis_titles as _apply_baseline_axis_title_normalisation,
    normalise_baseline_lines as _apply_baseline_line_normalisation,
    plotly_obj_to_dict as _plotly_obj_to_dict,
)
from ui.charts.bars import (
    apply_bar_protection as _apply_bar_protection_runtime,
    has_temporal_bar_trace as _has_temporal_bar_trace_runtime,
    time_edge_padding as _time_edge_padding_runtime,
)
from ui.charts.chrome import _apply_chart_chrome as _apply_chart_chrome_runtime
from ui.charts.config import (
    _get_chart_setting_value as _get_chart_setting_value_runtime,
    _resolve_chart_settings as _resolve_chart_settings_runtime,
)
from ui.charts.axes import (
    apply_axis_settings as _apply_axis_settings_runtime,
    data_range_for_axis as _data_range_for_axis_runtime,
    range_from_min_max as _range_from_min_max_runtime,
)
from ui.charts.categories import (
    force_all_x_categories as _apply_all_x_categories,
    force_all_y_categories as _apply_all_y_categories,
    force_heatmap_labels_and_square as _apply_heatmap_category_normalisation,
    has_horizontal_bar as _has_horizontal_bar,
    normalise_bar_text as _apply_bar_text_normalisation,
)
from ui.charts.layout import (
    apply_margin_delta as _apply_margin_delta_layout,
    coerce_axis_range as _coerce_axis_range_layout,
    computed_margin as _computed_margin_layout,
    effective_title as _effective_title_layout,
    is_undefined as _is_undefined_layout,
    legend_layout as _legend_layout_layout,
    setting_title as _setting_title_layout,
    show_buttons as _show_buttons_layout,
    show_legend as _show_legend_layout,
    show_title as _show_title_layout,
    title_text as _title_text_layout,
)
from ui.charts.money_axes import (
    axis_has_large_values as _axis_has_large_values,
    axis_title as _axis_title,
    compact_money_axes as _apply_compact_money_axes,
    looks_money as _looks_money,
)
from ui.charts.pipeline import (
    apply_settings_pipeline as _apply_settings_pipeline_runtime,
)
from ui.charts.postprocess import (
    apply_horizontal_bar_axis_spacing as _apply_horizontal_bar_axis_spacing_runtime,
    reapply_forced_ranges as _reapply_forced_ranges_runtime,
    reapply_y2_after_money as _reapply_y2_after_money_runtime,
)
from ui.charts.time_buttons import (
    apply_buttons as _apply_time_buttons,
    as_timedelta as _as_timedelta,
    clear_all_range_controls as _clear_all_range_controls,
    iter_xaxis_names as _iter_xaxis_names,
    plotly_date as _plotly_date,
    plotly_range as _plotly_range,
    time_extent as _time_extent,
)
from ui.charts.time_runtime import (
    apply_initial_visible_y_range as _apply_initial_visible_y_range_runtime,
    current_x_range_for_axis as _current_x_range_for_axis,
    force_time_default_range as _force_time_default_range_runtime,
)
from ui.charts.ranges import (
    numeric_values as _numeric_values,
    range_from_visible_values as _compute_range_from_visible_values,
    range_with_padding as _range_with_padding,
    trace_visible_y_values_for_x_range as _trace_visible_y_values_for_x_range,
    update_axis_range as _update_axis_range,
    visible_y_ranges_for_x_range as _compute_visible_y_ranges_for_x_range,
)

CHART_SETTINGS_VERSION = "2026-06-21-v5"
# Bump CHART_SETTINGS_VERSION ogni volta che si modifica annotations.py,
# perché la cache figure si basa solo sull'hash di questo file.
_ANNOTATIONS_VERSION = "2026-06-21-v5"  # sync con annotations.py

# ═══════════════════════════════════════════════════════════════════════════════
# 1) STILE GLOBALE — MODIFICA QUI PER CAMBIARE TUTTA LA DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

GLOBAL_STYLE: dict[str, Any] = {
    # ────────────────────────────────────────────────────────────────────────
    # INTERRUTTORI GLOBALI
    # ────────────────────────────────────────────────────────────────────────
    # True = funzione attiva su tutta la dashboard.
    # False = funzione spenta globalmente, anche se un singolo grafico la richiede.

    'show_titles': True,
    'show_legends': True,
    'show_buttons': True,

    # Linee verticali sui grafici temporali.
    # Valori possibili: 'quarter' | 'year' | None
    #   'quarter' → linee a ogni confine trimestrale + etichette T1/T2/T3/T4 + anno su Q1
    #   'year'    → solo linea e scritta anno (1 gennaio)
    #   None      → niente
    # Il singolo grafico può sovrascrivere con 'quarter_mode': ... nel suo dict in CHART_SETTINGS.
    'quarter_mode': 'quarter',

    # ────────────────────────────────────────────────────────────────────────
    # GRAFICI TEMPORALI / ANCORAGGIO A DESTRA
    # ────────────────────────────────────────────────────────────────────────
    # time_right_anchor='latest' mantiene i grafici temporali agganciati all'ultima data reale disponibile.
    # time_set_maxallowed=True impedisce al range selector di andare oltre l'ultima data.
    # time_use_calendar_offsets=True usa mesi/anni di calendario per 1M, 3M, 6M, 1Y.

    'time_right_anchor': 'latest',
    'time_set_maxallowed': True,
    'time_use_calendar_offsets': True,

    # time_force_iso_button_dates=True converte le date dei bottoni in stringhe ISO:
    # rende più stabile il comportamento dei relayout in Streamlit/Plotly.
    'time_force_iso_button_dates': True,
    # time_button_engine='relayout' usa bottoni Plotly espliciti con range calcolati da noi:
    # più stabile del rangeselector nativo quando serve restare agganciati all'ultima data.
    # Valori: 'relayout' consigliato; 'rangeselector' per tornare ai bottoni nativi Plotly.
    'time_button_engine': 'relayout',

    # time_reset_uirevision_on_render=True impedisce a Plotly/Streamlit di
    # conservare un vecchio zoom/range utente quando il grafico viene ridisegnato.
    # Se False, Plotly può mantenere l'ultimo range usato: utile in alcuni casi,
    # ma può far sembrare ALL un grafico che nel setting ha default_button='3M'.
    'time_reset_uirevision_on_render': True,

    # time_bar_edge_padding_days
    #   Padding automatico in giorni a sinistra/destra per grafici temporali con barre.
    #   Serve a non troncare la prima e l'ultima barra quando il range è agganciato
    #   esattamente a min/max data. Aumenta = più spazio ai bordi; 0 = disattivato.
    'time_bar_edge_padding_days': 2,

    # ────────────────────────────────────────────────────────────────────────
    # FONT GENERALI E FONT ASSI
    # ────────────────────────────────────────────────────────────────────────
    # font_size = font base Plotly.
    # axis_tick_font_size = numeri, date, ticker e categorie sugli assi. Aumenta = assi più leggibili.
    # axis_title_font_size = titoli degli assi. Aumenta = titoli asse più evidenti.

    'font_family': 'Inter, Arial, sans-serif',
    'font_size': 12,
    'axis_tick_font_size': 10,
    'axis_title_font_size': 10,

    # ────────────────────────────────────────────────────────────────────────
    # TITOLI
    # ────────────────────────────────────────────────────────────────────────
    # title_font_size = dimensione titolo principale.
    # subplot_title_font_size = dimensione titoli interni dei subplot.
    # title_y: aumenta = titolo più in alto; diminuisce = titolo più vicino al grafico.
    # title_x=0.5 mantiene il titolo centrato.

    'title_font_size': 16,
    'subplot_title_font_size': 16,
    'title_x': 0.5,
    'title_y': 0.95,
    'title_xanchor': 'center',
    'title_yanchor': 'top',

    # ────────────────────────────────────────────────────────────────────────
    # MARGINI STANDARD
    # ────────────────────────────────────────────────────────────────────────
    # Questi sono i margini base calcolati automaticamente.
    # margin_bottom_base si usa quando non ci sono né legenda né titolo asse X.
    # margin_bottom_with_x_title si usa quando c'è il titolo asse orizzontale.
    # margin_bottom_with_bottom_legend si usa quando la legenda è in basso.
    # temporal_right_margin è il margine destro minimo dei grafici temporali.

    'margin_top_base': 28,
    'margin_top_with_title': 44,
    'margin_top_with_buttons': 64,
    'margin_bottom_base': 24,
    'margin_bottom_with_x_title': 62,
    'margin_bottom_with_bottom_legend': 112,
    'margin_left_base': 46,
    'margin_right_base': 46,
    'temporal_right_margin': 90,

    # ────────────────────────────────────────────────────────────────────────
    # DELTA MARGINI PER FAMIGLIA DI GRAFICI
    # ────────────────────────────────────────────────────────────────────────
    # Sono correzioni globali per famiglia.
    # Valori positivi aggiungono spazio; valori negativi lo tolgono.
    # Esempio: bar_margin_delta['r']=20 dà più spazio a destra a tutti i grafici a barre.

    'time_margin_delta': {'t': 0, 'b': 0, 'l': 0, 'r': 0},
    'bar_margin_delta': {'t': 0, 'b': 0, 'l': 8, 'r': 18},
    'pie_margin_delta': {'t': 0, 'b': -8, 'l': -16, 'r': 0},
    'heatmap_margin_delta': {'t': 0, 'b': 0, 'l': 26, 'r': 0},
    'waterfall_margin_delta': {'t': 0, 'b': 0, 'l': 10, 'r': 28},

    # ────────────────────────────────────────────────────────────────────────
    # LEGENDA
    # ────────────────────────────────────────────────────────────────────────
    # legend_font_size = grandezza testo legenda.
    # bottom_legend_y: più negativo = legenda più in basso; meno negativo = legenda più vicina al grafico.
    # bottom_legend_tracegroupgap aumenta lo spazio tra gruppi di tracce.

    'legend_font_size': 10,
    'bottom_legend_y': -0.15,
    'bottom_legend_tracegroupgap': 8,
    'legend_itemwidth': 30,

    # ────────────────────────────────────────────────────────────────────────
    # BOTTONI TEMPORALI
    # ────────────────────────────────────────────────────────────────────────
    # button_y: aumenta = bottoni più in alto/lontani dal grafico; diminuisce = bottoni più vicini al grafico.
    # button_active = colore del bottone attivo/agganciato al range iniziale.
    # button_border_width=0 rende i bottoni senza bordo.

    'button_y': 1.1,
    'button_x': 0.0,
    'button_font_size': 10,
    'button_bg': 'rgba(0,0,0,0)',
    'button_active': 'rgba(0,0,0,0)',
    # Plotly disegna il bordo sull'intero gruppo updatemenus, non sul singolo bottone:
    # 0 evita il rettangolo grande attorno alle scritte. Il colore attivo resta evidente.
    'button_border_width': 0,
    'button_border_color': 'rgba(0,0,0,0)',
    # Padding interno del gruppo bottoni relayout.
    # Aumenta = contenitore bottoni più largo/alto; diminuisce = bottoni più compatti.
    # Per simulare i vecchi rangeselector piatti, lasciare tutti a 0 o 1.
    'button_pad_t': 0,
    'button_pad_b': 0,
    'button_pad_l': 0,
    'button_pad_r': 0,
    # button_label_brackets=True visualizza [1M] [3M] ecc.: evidenzia la selezione
    # senza usare il rettangolo colorato del bottone attivo Plotly.
    'button_label_brackets': True,
    # False spegne l'evidenziazione nativa Plotly del bottone attivo: evita l'alone colorato.
    'button_showactive': True,

    # ────────────────────────────────────────────────────────────────────────
    # MAX/MIN — ANNOTAZIONI DI MASSIMO E MINIMO
    # ────────────────────────────────────────────────────────────────────────
    # show_extrema_default
    #   False = MAX/MIN spenti di default; li accendi solo nei grafici con show_extrema=True.
    #   True  = MAX/MIN accesi di default; li spegni nei grafici con show_extrema=False.
    #
    # extrema_mode
    #   'max_min'  = mostra sia massimo sia minimo.
    #   'max_only' = mostra solo il massimo.
    #   'min_only' = mostra solo il minimo.
    #   'off'      = non mostra nulla anche se show_extrema=True.
    #
    # extrema_labels
    #   'short' = etichette compatte MAX / MIN.
    #   'long'  = etichette estese Massimo / Minimo.
    #
    # extrema_value_format
    #   'eur0'     = importo senza decimali, es. 12.000 €.
    #   'eur2'     = importo con 2 decimali.
    #   'percent1' = percentuale con 1 decimale.
    #   'percent2' = percentuale con 2 decimali.
    #   'number'   = numero semplice.
    #   'auto'     = prova a dedurre il formato dal grafico.
    #
    # extrema_include_series
    #   True  = nei grafici multi-linea aggiunge il nome della serie al testo MAX/MIN.
    #   False = mostra solo MAX/MIN e valore.
    #
    # extrema_multiline
    #   True  = testo su più righe, es. MAX\n12.000 €.
    #   False = testo su una riga, es. MAX: 12.000 €.
    #
    # extrema_marker_size / extrema_font_size
    #   aumentano o riducono dimensione marker e testo MAX/MIN.
    #
    # extrema_max_color / extrema_min_color
    #   Possono usare chiavi tema ('success', 'danger', 'warning', 'primary') oppure colori CSS/rgba.
    #
    # extrema_max_symbol / extrema_min_symbol
    #   Simbolo Plotly del marker. Valori utili:
    #   'circle', 'circle-open', 'square', 'square-open', 'diamond', 'diamond-open',
    #   'cross', 'x', 'star', 'hexagon', 'pentagon',
    #   'triangle-up', 'triangle-up-open', 'triangle-down', 'triangle-down-open',
    #   'triangle-left', 'triangle-right',
    #   'arrow-up', 'arrow-down', 'arrow-left', 'arrow-right'.
    #   Coppia consigliata: max='triangle-up', min='triangle-down'.
    #
    # extrema_max_textposition / extrema_min_textposition
    #   Posizione testo rispetto al marker. Valori Plotly utili:
    #   'top left', 'top center', 'top right',
    #   'middle left', 'middle center', 'middle right',
    #   'bottom left', 'bottom center', 'bottom right'.
    #   Se un testo a destra viene tagliato, prova 'top left' o 'bottom left'.
    #
    # extrema_cliponaxis
    #   False = evita che il testo MAX/MIN venga tagliato ai bordi del grafico.
    #   True  = consente il taglio sull'asse; di norma NON consigliato.

    'show_extrema_default': False,
    'extrema_mode': 'max_min',
    'extrema_labels': 'short',
    'extrema_value_format': 'eur0',
    'extrema_include_series': False,
    'extrema_multiline': False,
    'extrema_marker_size': 10,
    'extrema_font_size': 9,
    'extrema_marker_line_color': 'white',
    'extrema_marker_line_width': 1.5,
    'extrema_max_color': 'success',
    'extrema_min_color': 'danger',
    'extrema_max_symbol': 'circle',
    'extrema_min_symbol': 'circle',
    'extrema_max_textposition': 'top center',
    'extrema_min_textposition': 'bottom center',
    'extrema_cliponaxis': False,

    # ────────────────────────────────────────────────────────────────────────
    # ANNOTAZIONI TECNICHE BASE 100
    # ────────────────────────────────────────────────────────────────────────
    # Controllano testi tipo 'Base 100 = primo investimento'.
    # Sono annotazioni tecniche: non vengono ingrandite come i titoli.

    'baseline_annotation_font_size': 10,
    'baseline_annotation_color': 'rgba(220,38,38,0.95)',
    'baseline_annotation_yshift': 0,

    # Parametri della linea orizzontale Base 100.
    # Vengono applicati alle linee tecniche create nei grafici con fig.add_hline(y=100, ...).
    # Nota: la funzione di normalizzazione intercetta solo linee orizzontali con y0 == y1 == 100,
    # quindi non altera soglie, zeri o altre linee di supporto eventualmente presenti nei grafici.
    'baseline_line_color': 'rgba(220,38,38,0.95)',
    'baseline_line_dash': 'dash',
    'baseline_line_width': 1.6,
    'baseline_line_opacity': 0.85,
    # Colora anche i titoli asse che contengono 'Base 100' (es. Indice ... Base 100).
    'baseline_axis_title_color': 'rgba(220,38,38,0.95)',

    # ────────────────────────────────────────────────────────────────────────
    # BARRE / WATERFALL / PROTEZIONE ANTI-TAGLIO
    # ────────────────────────────────────────────────────────────────────────
    # bar_padding aumenta il respiro automatico dei grafici a barre.
    # waterfall_padding fa lo stesso per i waterfall.
    # bar_cliponaxis=False aiuta a non tagliare testi fuori barra.
    # horizontal_bar_left/right_margin_min fissano margini minimi per barre orizzontali.

    'bar_padding': 0.3,
    'waterfall_padding': 0.42,
    'bar_cliponaxis': False,
    'horizontal_bar_left_margin_min': 30,
    'horizontal_bar_right_margin_min': 90,
    # Distanza tra etichette dell'asse Y e barre orizzontali.
    # ticklen=0 e ticklabelstandoff=0 tengono i nomi strumenti più vicini alle barre.
    # Se le etichette risultano troppo attaccate, aumenta ticklabelstandoff a 2/4.
    'horizontal_bar_ticklen': 0,
    'horizontal_bar_ticklabelstandoff': 0,

    # ────────────────────────────────────────────────────────────────────────
    # ASSI / TACche / TITOLI ASSI
    # ────────────────────────────────────────────────────────────────────────
    # numeric_axis_nticks e percent_axis_nticks suggeriscono quante tacche mostrare.
    # axis_title_standoff: aumenta = titolo asse più lontano; diminuisce = titolo asse più vicino.
    # xaxis_tickangle inclina le etichette asse X se necessario.

    'numeric_axis_nticks': 6,
    'percent_axis_nticks': 6,
    'axis_title_standoff': 4,
    'xaxis_tickangle': None,

    # ────────────────────────────────────────────────────────────────────────
    # FORMATO IMPORTI / NOTAZIONE k
    # ────────────────────────────────────────────────────────────────────────
    # compact_money_ticks=True abilita assi monetari compatti.
    # compact_money_format='.3~s' produce valori tipo 10k, 100k.
    # force_k_for_money_axes=True forza la notazione k quando money_axis lo richiede.

    'compact_money_ticks': True,
    'compact_money_threshold': 1000,
    'compact_money_format': '.3~s',
    'force_k_for_money_axes': True,

    # ────────────────────────────────────────────────────────────────────────
    # SFONDI / GRIGLIE
    # ────────────────────────────────────────────────────────────────────────
    # transparent_background=True forza sfondi trasparenti.
    # paper_bgcolor = sfondo del riquadro Plotly; plot_bgcolor = area interna del grafico.
    # grid_color = colore griglia; zero_line_color = linea dello zero.

    'transparent_background': False,
    'paper_bgcolor': 'rgba(0,0,0,0)',
    'plot_bgcolor': 'rgba(0,0,0,0)',
    'grid_color': 'rgba(107,114,128,0.16)',
    'zero_line_color': 'rgba(107,114,128,0.35)',

    # Weekend / assi tempo
    # skip_weekends_default=False lascia visibili sabato/domenica salvo override del grafico.
    # time_set_minallowed=True/False consente di bloccare anche il limite sinistro storico.
    'skip_weekends_default': False,
    'time_set_minallowed': True,
    # Forza nuovamente il range iniziale alla fine di apply_settings.
    # Serve quando Plotly/Streamlit o uirevision provano a conservare ALL/zoom precedente.
    'time_force_default_range_after_render': True,

    # Barre orizzontali
    # show_all_y_categories_default=True forza la visualizzazione di tutte le etichette categoria/ticker sull'asse Y.
    # horizontal_bar_left_margin_min basso = barre più vicine ai testi asse Y; se i nomi si tagliano, aumentalo.
    'show_all_y_categories_default': True,
    # Se i valori delle barre orizzontali sono tutti positivi, forza l'asse X a partire da 0.
    # Riduce la distanza apparente tra etichette Y e inizio barre.
    'horizontal_bar_force_zero_start': True,
    # Auto-range specifico per barre orizzontali: riduce il vuoto inutile a sinistra
    # senza tagliare i valori testuali fuori barra a destra.
    'horizontal_bar_auto_range': True,
    'horizontal_bar_padding_positive': 0.12,
    'horizontal_bar_padding_mixed': 0.18,
    'bar_textposition': None,
    'bar_textfont_size': None,
    # Per le barre orizzontali, di default il valore numerico sta fuori dalla barra, a destra.
    'horizontal_bar_textposition': 'outside',
    'horizontal_bar_textfont_size': 10,
}

# ═══════════════════════════════════════════════════════════════════════════════
# 2) CONFIGURAZIONE DI OGNI GRAFICO — DIVISA PER PAGINA/SCHEDA
# ═══════════════════════════════════════════════════════════════════════════════
#
# PARAMETRI UTILIZZABILI NEL SINGOLO GRAFICO
#
# type
#   "time"      = grafico temporale con possibile rangeselector 1M/3M/6M/YTD/1Y/ALL.
#   "bar"       = grafico a barre verticali/orizzontali.
#   "pie"       = grafico a torta/ciambella.
#   "heatmap"   = matrice/heatmap.
#   "waterfall" = waterfall.
#   "custom"    = grafico particolare.
#
# title
#   Titolo manuale di fallback. Se charts.py passa un titolo valido, vince quello.
#   title=None = nessun fallback, ma NON cancella il titolo dinamico.
#
# show_title / show_legend / show_buttons
#   False spegne solo quel componente nel grafico specifico.
#   show_buttons funziona solo per type="time".
#
# height
#   Altezza in pixel. Aumenta = grafico più alto; diminuisce = grafico più compatto.
#   None = lascia l'altezza dinamica eventualmente calcolata da charts.py.
#
# legend
#   "bottom", "top", "right", "left", "off".
#
# default_button
#   Finestra temporale iniziale: "1M", "3M", "6M", "YTD", "1Y", "ALL".
#   Se time_right_anchor='latest', la finestra resta agganciata all'ultima data reale.
#
# margin_delta
#   Correzione rispetto allo standard globale.
#   Esempio: {"t":0,"b":-20,"l":0,"r":10} = meno spazio sotto, più spazio a destra.
#
# x_title / y_title / y2_title
#   Titoli assi. Se assenti o None, non vengono forzati dal setting.
#
# x_min / x_max / y_min / y_max
#   Forzano solo minimo o massimo dell'asse.
#
# x_range / y_range / y2_range
#   Forzano range completo, es. y_range=[0, 1.05].
#
# x_nticks / y_nticks / x_dtick / y_dtick
#   nticks suggerisce il numero di tacche; dtick forza il passo fisso.
#
# x_tickformat / y_tickformat / y2_tickformat
#   Formato Plotly delle tacche. Esempi: ".0%", ".1f", ",.0f", ".3~s".
#
# money_axis / force_k
#   money_axis="x", "y", "y2", "both", "auto", "off".
#   ATTENZIONE: "y" vale solo per asse sinistro; "y2" vale solo per asse destro.
#   "both" applica il formato a entrambi.
#   force_k=True forza la notazione in k sugli assi monetari selezionati.
#
# show_extrema / extrema_*
#   show_extrema=True  → accende MAX/MIN solo per questo grafico.
#   show_extrema=False → spegne MAX/MIN solo per questo grafico.
#
#   extrema_mode:
#     "max_min"  = massimo + minimo; "max_only" = solo massimo;
#     "min_only" = solo minimo;   "off" = nessuna indicazione.
#
#   extrema_labels:
#     "short" = MAX/MIN; "long" = Massimo/Minimo.
#
#   extrema_value_format:
#     "eur0", "eur2", "percent1", "percent2", "number", "auto".
#
#   extrema_max_symbol / extrema_min_symbol:
#     "circle", "circle-open", "square", "square-open", "diamond",
#     "diamond-open", "cross", "x", "star", "hexagon", "pentagon",
#     "triangle-up", "triangle-up-open", "triangle-down", "triangle-down-open",
#     "triangle-left", "triangle-right", "arrow-up", "arrow-down",
#     "arrow-left", "arrow-right".
#
#   extrema_max_textposition / extrema_min_textposition:
#     "top left", "top center", "top right",
#     "middle left", "middle center", "middle right",
#     "bottom left", "bottom center", "bottom right".
#
#   extrema_marker_size / extrema_font_size:
#     aumentano/diminuiscono marker e testo MAX/MIN.
#
#   extrema_cliponaxis=False:
#     evita il taglio del testo ai bordi; normalmente lasciarlo False.
#
# bar_padding / waterfall_padding
#   Aumentano il respiro degli assi per evitare taglio di barre/testi.

CHARTS: dict[str, dict[str, Any]] = {
    # ------------------------------------------------------------------
    # OVERVIEW
    # ------------------------------------------------------------------

    'overview_pl_portafoglio': {'type': 'time',
     'height': 400,
     'legend': 'bottom',
     'show_buttons': True,
     'default_button': '3M',
     'dynamic_y_to_initial_range': True,
     'dynamic_y_by_button': True,
     'dynamic_y_padding': 0.08,
     'margin_delta': {'t': 0, 'b': -20, 'l': 0, 'r': -20},
     'skip_weekends': True,
     'money_axis': 'auto',
     'force_k': True,
     'y_nticks': 10,
     'x_nticks': 15,
     'title': '<b>P/L del portafoglio</b>',
     'show_extrema': True},

    'overview_pl_categoria': {'type': 'time',
     'height': 400,
     'legend': 'bottom',
     'show_buttons': True,
     'default_button': '3M',
     'dynamic_y_to_initial_range': True,
     'dynamic_y_by_button': True,
     'dynamic_y_padding': 0.08,
     'margin_delta': {'t': 0, 'b': -20, 'l': 0, 'r': -20},
     'skip_weekends': True,
     'money_axis': 'auto',
     'force_k': True,
     'y_nticks': 10,
     'x_nticks': 15,
     'title': '<b>P/L cumulativo per Categoria</b>',
     'show_extrema': True},

    # ------------------------------------------------------------------
    # QUOTAZIONI
    # ------------------------------------------------------------------

    'quotazioni_quote_history': {'type': 'time',
     'height': 360,
     'legend': 'bottom',
     'show_buttons': True,
     'default_button': 'ALL',
     'margin_delta': {'t': 0, 'b': -20, 'l': 0, 'r': -50},
     'y_title': 'Indice di rendimento (Base 100)',
     'y_nticks': 6,
     'quarter_mode': None,
     'title': None},

    'quotazioni_instrument_performance_time_v2': {'type': 'time',
     'height': 420,
     'legend': 'bottom',
     'show_buttons': True,
     'default_button': '3M',
     'dynamic_y_to_initial_range': True,
     'dynamic_y_by_button': True,
     'dynamic_y_padding': 0.08,
     'margin_delta': {'t': 0, 'b': -50, 'l': 0, 'r': -20},
     'y_title': 'Indice dal 1° investimento (Base 100)',
     'y_nticks': 8,
     'x_nticks': 15,
     'quarter_mode': None,
     'title': '<b>Rendimento dello strumento</b>',
     'show_extrema': True,
     'extrema_value_format': 'pct1_base100'},

    # ------------------------------------------------------------------
    # PORTAFOGLIO
    # ------------------------------------------------------------------

    'home_portfolio_pl': {'type': 'time',
     'height': 360,
     'legend': 'off',
     'show_buttons': True,
     'default_button': '1M',
     'dynamic_y_to_initial_range': True,
     'dynamic_y_by_button': True,
     'dynamic_y_padding': 0.08,
     'margin_delta': {'t': 0, 'b': 0, 'l': 0, 'r': 10},
     'skip_weekends': True,
     'time_bar_edge_padding_days': 0.6,
     'y_nticks': 10,
     'x_nticks': 15,
     'x_tickformat': '%d/%m',
     'x_dtick': 86400000,
     'x_tickangle': 0,
     'title': '<b>Profit / Loss Complessivo</b>'},

    'home_portfolio_pl_category': {'type': 'time',
     'height': 360,
     'legend': 'bottom',
     'show_buttons': True,
     'default_button': '1M',
     'dynamic_y_to_initial_range': False,
     'dynamic_y_by_button': False,
     'y_range': [0, 100],
     'dynamic_y_padding': 0.0,
     'margin_delta': {'t': 0, 'b': -30, 'l': 0, 'r': 10},
     'skip_weekends': True,
     'time_bar_edge_padding_days': 0.6,
     'y_nticks': 10,
     'x_nticks': 15,
     'x_tickformat': '%d/%m',
     'x_dtick': 86400000,
     'x_tickangle': 0,
     'y_tickformat': '.0f',
     'y_ticksuffix': '%',
     'title': '<b>Composizione % del Profit / Loss per Macro-Categoria</b>'},

    'home_concentration': {'type': 'bar',
     'height': 400,
     'legend': 'bottom',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -50, 'l': 0, 'r': -20},
     'x_tickangle': 0,
     'y_title': 'Controvalore',
     'y2_title': 'Peso cumulato',
     'money_axis': 'y',
     'force_k': True,
     'y2_tickformat': '.0%',
     'y2_range': [0, 1.1],
     'y_nticks': 10,
     'bar_padding': 0.16,
     'y2_overlaying': 'y',
     'y2_side': 'right',
     'y2_showgrid': False,
     'y2_nticks': 10,
     'title': '<b>Concentrazione e distribuzione del portafoglio</b>'},

    'home_instrument_pie': {'type': 'pie',
     'height': 380,
     'legend': 'right',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': 10, 'l': 0, 'r': 0},
     'title': '<b>Allocazione globale per strumento</b>'},

    'home_category_pie': {'type': 'pie',
     'height': 380,
     'legend': 'right',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': 10, 'l': 0, 'r': 0},
     'title': '<b>Allocazione globale per categoria</b>'},

    'home_instrument_bar_perf': {'type': 'bar',
     'height': 420,
     'legend': 'off',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': 0, 'l': 0, 'r': -50},
     'bar_padding': 0.4,
     'horizontal_bar_auto_range': True,
     'horizontal_bar_force_zero_start': False,
     'horizontal_bar_padding_positive': 0.10,
     'horizontal_bar_padding_mixed': 0.10,
     'x_nticks': 10,
     'x_tickformat': '.1%',
     'show_all_y_categories': True,
     'title': '<b>Performance % per strumento</b>'},

    'home_instrument_bar_pl': {'type': 'bar',
     'height': 420,
     'legend': 'off',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': 0, 'l': 0, 'r': -50},
     'bar_padding': 0.4,
     'horizontal_bar_auto_range': True,
     'horizontal_bar_force_zero_start': False,
     'horizontal_bar_padding_positive': 0.10,
     'horizontal_bar_padding_mixed': 0.10,
     'money_axis': 'auto',
     'x_nticks': 10,
     'show_all_y_categories': True,
     'title': '<b>P/L per strumento</b>'},

    'home_category_bar_value': {'type': 'bar',
     'height': 360,
     'legend': 'off',
     'show_buttons': False,
     'margin_delta': {'t': 10, 'b': -10, 'l': 0, 'r': -50},
     'bar_padding': 0.3,
     'money_axis': 'y',
     'force_k': True,
     'y_nticks': 10,
     'title': '<b>Controvalore per categoria</b>'},

    'home_category_bar_pl': {'type': 'bar',
     'height': 360,
     'legend': 'off',
     'show_buttons': False,
     'margin_delta': {'t': 10, 'b': -10, 'l': 0, 'r': -50},
     'bar_padding': 0.3,
     'money_axis': 'y',
     'force_k': True,
     'y_nticks': 10,
     'title': '<b>P/L per categoria</b>'},

    'home_category_bar_perf': {'type': 'bar',
     'height': 360,
     'legend': 'off',
     'show_buttons': False,
     'margin_delta': {'t': 10, 'b': -10, 'l': 0, 'r': -50},
     'bar_padding': 0.3,
     'y_min': 0,
     'y_nticks': 10,
     'y_tickformat': '.1%',
     'title': '<b>Performance % per categoria</b>'},

    # ------------------------------------------------------------------
    # CRUSCOTTI - CATEGORIE
    # ------------------------------------------------------------------

    'cruscotti_compact_category_dashboard': {'type': 'bar',
     'height': None,
     'legend': 'off',
     'show_title': False,
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': 0, 'l': 0, 'r': -50},
     'bar_padding': 0.4,
     'horizontal_bar_auto_range': True,
     'horizontal_bar_force_zero_start': False,
     'horizontal_bar_padding_positive': 0.10,
     'horizontal_bar_padding_mixed': 0.10,
     'bar_textposition': 'outside',
     'bar_textfont_size': 10,
     'money_axis': 'auto',
     'x_nticks': 8,
     'show_all_y_categories': True,
     'title': '<b>Dashboard Categoria</b>'},

    'cruscotti_category_temporal': {'type': 'time',
     'height': 320,
     'legend': 'bottom',
     'show_buttons': True,
     'default_button': '3M',
     'dynamic_y_to_initial_range': True,
     'dynamic_y_by_button': True,
     'dynamic_y_padding': 0.08,
     'margin_delta': {'t': -50, 'b': -20, 'l': 0, 'r': 0},
     'money_axis': 'auto',
     'y_nticks': 10,
     'x_nticks': 15,
     'y_title': 'P/L (€)',
     'y2_title': 'Controvalore (€)',
     'y2_overlaying': 'y',
     'y2_side': 'right',
     'y2_showgrid': False,
     'y2_nticks': 10,
     'y_tickformat': '.3~s',
     'y2_tickformat': '.3~s',
     'title': None},

    'cruscotti_category_value_pie': {'type': 'pie',
     'height': 360,
     'legend': 'right',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': 20, 'l': 0, 'r': 0},
     'title': '<b>Distribuzione controvalore per strumento</b>'},

    'cruscotti_category_capital_pl_pie': {'type': 'pie',
     'height': 360,
     'legend': 'right',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': 0, 'l': 0, 'r': 0},
     'title': '<b>Capitale versato vs P/L</b>'},

    'cruscotti_category_invested_vs_pl': {'type': 'bar',
     'height': None,
     'legend': 'bottom',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -50, 'l': 0, 'r': -20},
     'x_title': '',
     'x_nticks': 15,
     'row_height': 36,
     'min_height': 280,
     'max_height': 860,
     'height_base_pad': 120,
     'bar_width': 0.75,
     'title': '<b>Capitale investito vs P/L</b>'},

    # ------------------------------------------------------------------
    # CRUSCOTTI - ACCUMULI / PAC
    # ------------------------------------------------------------------

    'cruscotti_accumuli_overview': {'type': 'scatter',
     'height': 380,
     'legend': 'off',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': 0, 'l': 8, 'r': -20},
     'x_tickformat': '.1%',
     'y_tickformat': '.1%',
     'x_nticks': 9,
     'y_nticks': 8,
     'title': '<b>Mappa sintetica accumuli</b>'},

    'cruscotti_accumuli_price_pmc': {'type': 'time',
     'height': 330,
     'legend': 'bottom',
     'show_buttons': True,
     'default_button': 'ALL',
     'dynamic_y_to_initial_range': True,
     'dynamic_y_by_button': True,
     'dynamic_y_padding': 0.08,
     'margin_delta': {'t': 0, 'b': -18, 'l': 0, 'r': -20},
     'y_nticks': 8,
     'x_nticks': 12,
     'y_title': '€/quota',
     'title': '<b>Prezzo vs PMC</b>'},

    'cruscotti_accumuli_value': {'type': 'time',
     'height': 330,
     'legend': 'bottom',
     'show_buttons': True,
     'default_button': 'ALL',
     'dynamic_y_to_initial_range': True,
     'dynamic_y_by_button': True,
     'dynamic_y_padding': 0.08,
     'margin_delta': {'t': 0, 'b': -18, 'l': 0, 'r': -20},
     'money_axis': 'auto',
     'force_k': True,
     'y_nticks': 8,
     'x_nticks': 12,
     'y_title': '€',
     'title': '<b>Capitale investito vs controvalore</b>'},

    'andamento_drawdown': {'type': 'time',
     'height': 420,
     'legend': 'off',
     'show_buttons': True,
     'default_button': 'ALL',
     'margin_delta': {'t': 0, 'b': 0, 'l': 0, 'r': -20},
     'y_nticks': 10,
     'x_nticks': 15,
     'y_tickformat': '.1f',
     'y_ticksuffix': '%',
     'title': '<b>Drawdown Portafoglio</b>',
     'show_extrema': True},

    'andamento_monthly_returns': {'type': 'time',
     'height': 480,
     'legend': 'off',
     'show_buttons': True,
     'default_button': 'ALL',
     'margin_delta': {'t': 0, 'b': 0, 'l': 0, 'r': -20},
     'y_nticks': 10,
     'x_nticks': 15,
     'y_tickformat': '.1f',
     'y_ticksuffix': '%',
     'title': '<b>Rendimenti mensili</b>'},

    # ------------------------------------------------------------------
    # CRUSCOTTI - ANALITICA
    # ------------------------------------------------------------------

    'andamento_portfolio_value': {'type': 'time',
     'height': 400,
     'legend': 'bottom',
     'show_buttons': True,
     'default_button': '3M',
     'margin_delta': {'t': 0, 'b': -20, 'l': 0, 'r': -20},
     'money_axis': 'y',
     'force_k': True,
     'y_nticks': 10,
     'x_nticks': 15,
     'title': '<b>Andamento Portafoglio</b>'},

    'andamento_pl_decomp_stacked': {'type': 'time',
     'height': 400,
     'legend': 'bottom',
     'show_buttons': True,
     'default_button': '3M',
     'margin_delta': {'t': 0, 'b': -50, 'l': 0, 'r': -20},
     'money_axis': 'auto',
     'y_nticks': 15,
     'title': '<b>Contributo al P/L (Area Stacked)</b>',
     'show_extrema': True},

    'andamento_percentage_return': {'type': 'time',
     'height': 400,
     'legend': 'bottom',
     'show_buttons': True,
     'default_button': '3M',
     'dynamic_y_to_initial_range': True,
     'dynamic_y_by_button': True,
     'dynamic_y_padding': 0.08,
     'margin_delta': {'t': 0, 'b': -20, 'l': 0, 'r': -20},
     'y_nticks': 10,
     'x_nticks': 15,
     'y_tickformat': '.1f',
     'y_ticksuffix': '%',
     'title': '<b>Rendimento percentuale</b>',
     'show_extrema': True},

    'analisi_performance_attribution': {'type': 'waterfall',
     'height': 380,
     'legend': 'off',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -20, 'l': 0, 'r': -50},
     'waterfall_padding': 0.22,
     'money_axis': 'auto',
     'y_nticks': 8,
     'show_all_x_categories': True,
     'x_tickangle': 0,
     'title': '<b>Contributo P/L per strumento (Waterfall)</b>'},

    'analisi_target_gap': {'type': 'bar',
     'height': 360,
     'legend': 'bottom',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -30, 'l': 0, 'r': -50},
     'bar_padding': 0.12,
     'horizontal_bar_auto_range': True,
     'horizontal_bar_force_zero_start': True,
     'horizontal_bar_padding_positive': 0.18,
     'horizontal_bar_padding_mixed': 0.20,
     'horizontal_bar_textposition': 'outside',
     'horizontal_bar_textfont_size': 10,
     'bar_cliponaxis': False,
     'x_title': 'Quota % del portafoglio / del rischio',
     'x_tickformat': '.0%',
     'show_all_y_categories': True,
     'x_nticks': 15,
     'title': '<b>Allineamento rispetto ad obiettivo</b>'},

    'analisi_risk_contribution2': {'type': 'bar',
     'height': 600,
     'legend': 'bottom',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -50, 'l': 0, 'r': -50},
     'bar_padding': 0.4,
     'horizontal_bar_auto_range': True,
     'horizontal_bar_force_zero_start': False,
     'horizontal_bar_padding_positive': 0.02,
     'horizontal_bar_padding_mixed': 0.04,
     'bar_textposition': 'outside',
     'bar_textfont_size': 10,
     'x_title': 'Quota % del portafoglio / del rischio',
     'x_tickformat': '.0%',
     'show_all_y_categories': True,
     'x_nticks': 15,
     'title': '<b>Contributo al rischio</b>'},

    'home_radar_allocation': {'type': 'radar',
     'height': 380,
     'legend': 'off',
     'show_buttons': False,
     'margin_delta': {'t': 20, 'b': 20, 'l': 0, 'r': 0},
     'polar_radial_range': [0, 45],
     'polar_radial_dtick': 5,
     'polar_ticksuffix': '%',
     'title': '<b>Allocazione quantitativa vs benchmark</b>'},

    'home_radar_quality': {'type': 'radar',
     'height': 380,
     'legend': 'off',
     'show_buttons': False,
     'margin_delta': {'t': 20, 'b': 20, 'l': 0, 'r': 0},
     'polar_radial_range': [0, 9],
     'polar_radial_dtick': 1,
     'title': '<b>Profilo qualitativo vs target</b>'},

    'cruscotti_benchmark_comparison': {'type': 'time',
     'height': 430,
     'legend': 'bottom',
     'show_buttons': True,
     'default_button': 'ALL',
     'dynamic_y_to_initial_range': True,
     'dynamic_y_by_button': True,
     'dynamic_y_padding': 0.08,
     'margin_delta': {'t': 0, 'b': -18, 'l': 0, 'r': -20},
     'y_title': 'Indice base 100',
     'y_nticks': 8,
     'x_nticks': 12,
     'quarter_mode': 'year',
     'title': '<b>Portafoglio vs Benchmark</b>'},

    'benchmark_normalized_performance': {'type': 'custom',
     'height': 420,
     'legend': 'bottom',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': 0, 'l': 0, 'r': 0},
     'title': '<b>Performance normalizzata — base 0%</b>'},

    'cruscotti_benchmark_instrument_scatter': {'type': 'scatter',
     'height': 500,
     'legend': 'bottom',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': 18, 'l': 0, 'r': -20},
     'x_title': 'Compatibilità benchmark',
     'y_title': 'Extra-rendimento',
     'x_tickformat': '.0%',
     'y_tickformat': '+.0%',
     'x_nticks': 6,
     'y_nticks': 7,
     'title': '<b>Compatibilità benchmark vs extra-rendimento</b>'},

    'quotazioni_category_performance_time_v2': {'type': 'time',
     'height': 420,
     'legend': 'bottom',
     'show_buttons': True,
     'default_button': '3M',
     'dynamic_y_to_initial_range': True,
     'dynamic_y_by_button': True,
     'dynamic_y_padding': 0.08,
     'margin_delta': {'t': 0, 'b': -20, 'l': 0, 'r': -20},
     'y_title': 'Indice dal 1° investimento (Base 100)',
     'y_nticks': 8,
     'x_nticks': 15,
     'quarter_mode': None,
     'title': '<b>Rendimento Omogeneizzato per Tipologia</b>',
     'show_extrema': True,
     'extrema_value_format': 'pct1_base100'},

    'quotazioni_instrument_drawdown': {'type': 'time',
     'height': 400,
     'legend': 'bottom',
     'show_buttons': True,
     'default_button': 'ALL',
     'margin_delta': {'t': 0, 'b': -20, 'l': 0, 'r': -20},
     'y_nticks': 6,
     'y_tickformat': '.0f',
     'y_ticksuffix': '%',
     'quarter_mode': None,
     'title': '<b>Drawdown per Strumento</b>'},

    'quotazioni_correlation_instruments': {'type': 'heatmap',
     'height': 540,
     'width': 540,
     'square': True,
     'legend': 'off',
     'show_buttons': False,
     'show_all_heatmap_labels': True,
     'x_tickangle': -90,
     'margin_delta': {'t': 10, 'b': 0, 'l': 0, 'r': 0},
     'title': None},

    'quotazioni_correlation_categories': {'type': 'heatmap',
     'height': 540,
     'width': 540,
     'square': True,
     'legend': 'off',
     'show_buttons': False,
     'show_all_heatmap_labels': True,
     'x_tickangle': -90,
     'margin_delta': {'t': 10, 'b': 0, 'l': 0, 'r': 0},
     'title': None},

    # ------------------------------------------------------------------
    # CRUSCOTTI - REDDITO
    # ------------------------------------------------------------------

    'btp_timeline': {'type': 'time',
     'height': 400,
     'legend': 'bottom',
     'show_legends': False,
     'show_buttons': False,
     'show_title': False,
     'dynamic_y_to_initial_range': False,
     'dynamic_y_by_button': False,
     'margin_delta': {'t': -20, 'b': -60, 'l': 10, 'r': 0},
     'skip_weekends': False,
     'y_nticks': 12,
     'x_nticks': 6,
     'x_tickformat': '%d/%m/%y',
     'x_dtick': 7776000000,
     'x_tickangle': 0,
     'quarter_mode': 'year',
     'y_bottom_padding': -0.7,
     'title': '<b>Scadenze e Cedole BTP</b>'},

    # ------------------------------------------------------------------
    # CRUSCOTTI - ACQUISTI
    # ------------------------------------------------------------------

    'andamento_monthly_spending': {'type': 'time',
     'height': 400,
     'legend': 'bottom',
     'show_buttons': True,
     'default_button': '1Y',
     'margin_delta': {'t': 0, 'b': -20, 'l': 4, 'r': 0},
     'money_axis': 'both',
     'force_k': True,
     'y_nticks': 10,
     'y_title': 'Spesa mese (€)',
     'y2_title': 'Cumulato (€)',
     'y2_overlaying': 'y',
     'y2_side': 'right',
     'y2_showgrid': False,
     'y2_nticks': 10,
     'y_tickformat': '.3~s',
     'y2_tickformat': '.3~s',
     'y2_range': [0, 120000],
     'title': '<b>Spesa acquisti mensile</b>'},

    'operations_purchase_installments': {'type': 'bar',
     'height': 480,
     'legend': 'off',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': 0, 'l': 0, 'r': -20},
     'bar_padding': 0.5,
     'y_title': 'N. acquisti',
     'y_nticks': 16,
     'y2_title': 'Prezzi acquisto (€)',
     'y2_range': [0, 200],
     'y2_overlaying': 'y',
     'y2_side': 'right',
     'y2_showgrid': False,
     'y2_nticks': 16,
     'y2_tickformat': ',.2f',
     'x_tickangle': 0,
     'title': '<b>Acquisti per strumento</b>'},

    # ------------------------------------------------------------------
    # SUMMARY
    # ------------------------------------------------------------------

    'summary_history': {'type': 'time',
     'height': 360,
     'legend': 'bottom',
     'show_buttons': True,
     'default_button': '3M',
     'skip_weekends': True,
     'dynamic_y_to_initial_range': True,
     'dynamic_y_by_button': True,
     'dynamic_y_padding': 0.08,
     'margin_delta': {'t': 0, 'b': -30, 'l': 0, 'r': -40},
     'y_title': 'Indice TWR proxy (Base 100)',
     'y_tickformat': '.1f',
     'y_nticks': 8,
     'title': '<b>Andamento TWR proxy del portafoglio</b>'},

    'summary_annual': {'type': 'bar',
     'height': 360,
     'legend': 'bottom',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -10, 'l': 0, 'r': -10},
     'bar_padding': 0.28,
     'y_tickformat': '.0%',
     'y_nticks': 8,
     'title': '<b>Rendimento annuale</b>'},

    'summary_allocation': {'type': 'pie',
     'height': 360,
     'legend': 'right',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': 20, 'l': 0, 'r': 0},
     'title': '<b>Allocazione</b>'},

    'summary_allocation_bar': {'type': 'bar',
     'height': 360,
     'legend': 'off',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -10, 'l': 20, 'r': 10},
     'bar_padding': 0.20,
     'x_tickformat': '.0%',
     'x_nticks': 8,
     'title': '<b>Allocazione per categoria</b>'},

    'summary_drawdown': {'type': 'time',
     'height': 360,
     'legend': 'bottom',
     'show_buttons': True,
     'default_button': '1Y',
     'skip_weekends': True,
     'dynamic_y_to_initial_range': True,
     'dynamic_y_by_button': True,
     'dynamic_y_padding': 0.10,
     'margin_delta': {'t': 0, 'b': -30, 'l': 0, 'r': -40},
     'y_title': 'Drawdown TWR proxy',
     'y_tickformat': '.0%',
     'y_nticks': 8,
     'title': '<b>Drawdown</b>'},

    'summary_category_history': {'type': 'time',
     'height': 360,
     'legend': 'bottom',
     'show_buttons': True,
     'default_button': 'ALL',
     'skip_weekends': True,
     'dynamic_y_to_initial_range': True,
     'dynamic_y_by_button': True,
     'dynamic_y_padding': 0.08,
     'margin_delta': {'t': 0, 'b': -30, 'l': 0, 'r': -40},
     'y_title': 'Indice categoria (Base 100)',
     'y_tickformat': '.1f',
     'y_nticks': 8,
     'title': '<b>Andamento categorie nel periodo</b>'},

    'summary_rolling_vol': {'type': 'time',
     'height': 360,
     'legend': 'bottom',
     'show_buttons': True,
     'default_button': '1Y',
     'dynamic_y_to_initial_range': True,
     'dynamic_y_by_button': True,
     'dynamic_y_padding': 0.10,
     'margin_delta': {'t': 0, 'b': -30, 'l': 0, 'r': -40},
     'y_title': 'Volatilità annua',
     'y_tickformat': '.1%',
     'y_nticks': 8,
     'title': '<b>Volatilità rolling</b>'},

    'summary_rolling_sharpe': {'type': 'time',
     'height': 360,
     'legend': 'off',
     'show_buttons': True,
     'default_button': '1Y',
     'dynamic_y_to_initial_range': True,
     'dynamic_y_by_button': True,
     'dynamic_y_padding': 0.10,
     'margin_delta': {'t': 0, 'b': -30, 'l': 0, 'r': -40},
     'y_title': 'Sharpe ratio',
     'y_tickformat': '.1f',
     'y_nticks': 8,
     'title': '<b>Sharpe rolling</b>'},

    'summary_rolling_12m': {'type': 'time',
     'height': 360,
     'legend': 'off',
     'show_buttons': True,
     'default_button': '1Y',
     'dynamic_y_to_initial_range': True,
     'dynamic_y_by_button': True,
     'margin_delta': {'t': 0, 'b': -20, 'l': 0, 'r': -10},
     'y_tickformat': '.0%',
     'y_nticks': 8,
     'title': '<b>Rendimento rolling 12 mesi</b>'},

    'summary_pl_scatter': {'type': 'custom',
     'height': 360,
     'legend': 'bottom',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -30, 'l': 0, 'r': 0},
     'x_title': 'Peso nel portafoglio',
     'x_tickformat': '.0%',
     'y_title': 'P/L %',
     'y_tickformat': '.0%',
     'money_axis': 'off',
     'force_k': False,
     'compact_money_ticks': False,
     'y_nticks': 8,
     'x_nticks': 8,
     'title': '<b>Distribuzione P/L</b>'},

    # ------------------------------------------------------------------
    # CONFRONTO
    # ------------------------------------------------------------------

    'confronto_snapshot': {'type': 'bar',
     'height': 400,
     'legend': 'bottom',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -20, 'l': 0, 'r': -20},
     'bar_padding': 0.25,
     'y_min': 0,
     'y_tickformat': '.0%',
     'y_nticks': 10,
     'title': '<b>Confronto allocazione per macro-categoria</b>'},

    'confronto_category_delta': {'type': 'bar',
     'height': 400,
     'legend': 'none',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -10, 'l': 0, 'r': -10},
     'bar_padding': 0.25,
     'y_tickformat': ',.0f',
     'y_nticks': 8,
     'title': '<b>Variazione valore per categoria</b>'},

    'confronto_contributors': {'type': 'bar',
     'height': 420,
     'legend': 'none',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -10, 'l': 20, 'r': -10},
     'bar_padding': 0.20,
     'x_tickformat': ',.0f',
     'x_nticks': 8,
     'title': '<b>Principali contributori al cambiamento</b>'},

    'confronto_assets_timeline': {'type': 'time',
     'height': 400,
     'legend': 'none',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -10, 'l': 0, 'r': -10},
     'y_tickformat': ',.0f',
     'y_nticks': 8,
     'title': '<b>Patrimonio sui momenti selezionati</b>'},

    'confronto_pl_timeline': {'type': 'time',
     'height': 400,
     'legend': 'none',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -10, 'l': 0, 'r': -10},
     'y_tickformat': ',.0f',
     'y_nticks': 8,
     'title': '<b>P/L sui momenti selezionati</b>'},

    'confronto_category_value_timeline': {'type': 'time',
     'height': 400,
     'legend': 'bottom',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -10, 'l': 0, 'r': -10},
     'y_tickformat': ',.0f',
     'y_nticks': 8,
     'title': '<b>Valore categorie nel tempo</b>'},

    'confronto_category_weight_timeline': {'type': 'time',
     'height': 400,
     'legend': 'bottom',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -10, 'l': 0, 'r': -10},
     'y_tickformat': '.0%',
     'y_nticks': 8,
     'title': '<b>Peso categorie nel tempo</b>'},

    'confronto_category_value_grouped': {'type': 'bar',
     'height': 400,
     'legend': 'bottom',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -10, 'l': 0, 'r': -10},
     'bar_padding': 0.24,
     'y_tickformat': ',.0f',
     'y_nticks': 8,
     'title': '<b>Valore categorie per snapshot</b>'},

    'confronto_category_weight_grouped': {'type': 'bar',
     'height': 400,
     'legend': 'bottom',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -10, 'l': 0, 'r': -10},
     'bar_padding': 0.24,
     'y_tickformat': '.0%',
     'y_nticks': 8,
     'title': '<b>Peso categorie per snapshot</b>'},

    'confronto_pl_delta': {'type': 'bar',
     'height': 420,
     'legend': 'none',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -10, 'l': 20, 'r': -10},
     'bar_padding': 0.20,
     'x_tickformat': ',.0f',
     'x_nticks': 8,
     'title': '<b>Variazione P/L per strumento</b>'},

    'confronto_return_delta': {'type': 'bar',
     'height': 420,
     'legend': 'none',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -10, 'l': 20, 'r': -10},
     'bar_padding': 0.20,
     'x_tickformat': '.0%',
     'x_nticks': 8,
     'title': '<b>Variazione rendimento per strumento</b>'},

    'confronto_holding_value_grouped': {'type': 'bar',
     'height': 420,
     'legend': 'bottom',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -10, 'l': 0, 'r': -10},
     'bar_padding': 0.20,
     'y_tickformat': ',.0f',
     'y_nticks': 8,
     'title': '<b>Controvalore strumenti per snapshot</b>'},

    'confronto_value_decomposition': {'type': 'bar',
     'height': 420,
     'legend': 'bottom',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -10, 'l': 0, 'r': -10},
     'bar_padding': 0.20,
     'y_tickformat': ',.0f',
     'y_nticks': 8,
     'title': '<b>Delta valore: capitale investito vs P/L</b>'},

    'confronto_holding_pl_grouped': {'type': 'bar',
     'height': 420,
     'legend': 'bottom',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -10, 'l': 0, 'r': -10},
     'bar_padding': 0.20,
     'y_tickformat': ',.0f',
     'y_nticks': 8,
     'title': '<b>P/L strumenti per snapshot</b>'},

    'confronto_multi_delta_pl': {'type': 'bar',
     'height': 420,
     'legend': 'none',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -10, 'l': 20, 'r': -10},
     'bar_padding': 0.20,
     'x_tickformat': ',.0f',
     'x_nticks': 8,
     'title': '<b>Delta P/L complessivo</b>'},

    'confronto_multi_delta_return': {'type': 'bar',
     'height': 420,
     'legend': 'none',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -10, 'l': 20, 'r': -10},
     'bar_padding': 0.20,
     'x_tickformat': '.0%',
     'x_nticks': 8,
     'title': '<b>Delta rendimento complessivo</b>'},

    # ------------------------------------------------------------------
    # PIANIFICAZIONE
    # ------------------------------------------------------------------

    'pianificazione_composizione': {'type': 'pie',
     'height': 300,
     'legend': 'right',
     'show_buttons': False,
     'margin_delta': {'t': -18, 'b': -14, 'l': -36, 'r': 60}},

    'pianificazione_ante_post': {'type': 'bar',
     'height': 260,
     'legend': 'right',
     'show_buttons': False,
     'margin_delta': {'t': -20, 'b': 1, 'l': -46, 'r': 0},
     'y_range': [0, 100],
     'y_tickformat': '.0f',
     'y_ticksuffix': '%'},

    'pianificazione_obiettivo_mix': {'type': 'bar',
     'height': 220,
     'legend': 'right',
     'show_buttons': False,
     'margin_delta': {'t': -20, 'b': 1, 'l': -46, 'r': 0},
     'y_range': [0, 100],
     'y_tickformat': '.0f',
     'y_ticksuffix': '%'},

    'pianificazione_allocation_rings': {'type': 'pie',
     'height': 420,
     'legend': 'right',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': 0, 'l': -20, 'r': 110},
     'title': '<b>Allocazione: bucket e strumenti</b>'},

    'pianificazione_coverage_matrix': {'type': 'heatmap',
     'height': None,
     'legend': 'off',
     'show_buttons': False,
     'show_all_heatmap_labels': True,
     'x_tickangle': -90,
     'margin_delta': {'t': 0, 'b': 0, 'l': 10, 'r': 0},
     'title': '<b>Copertura e sovrapposizione per area di mercato</b>'},

    'pianificazione_next_purchase_bubble': {'type': 'scatter',
     'height': 460,
     'legend': 'bottom',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': 0, 'l': 0, 'r': 0},
     'x_tickformat': '.2f',
     'y_tickformat': '.2f',
     'title': '<b>Prossimo acquisto: mappa decisionale</b>'},

    # ------------------------------------------------------------------
    # DA VERIFICARE / LEGACY
    # ------------------------------------------------------------------

    'andamento_pl_decomp_grouped': {'type': 'time',
     'height': 400,
     'legend': 'bottom',
     'show_buttons': True,
     'default_button': '3M',
     'margin_delta': {'t': 0, 'b': -10, 'l': 0, 'r': -20},
     'money_axis': 'auto',
     'y_nticks': 15,
     'title': '<b>Contributo al P/L (Grouped)</b>',
     'show_extrema': True},

    'summary_latest_instrument_pl': {'type': 'bar',
     'height': 520,
     'legend': 'off',
     'show_buttons': False,
     'margin_delta': {'t': 12, 'b': 8, 'l': 0, 'r': -50},
     'bar_padding': 0.4,
     'horizontal_bar_auto_range': True,
     'horizontal_bar_force_zero_start': False,
     'horizontal_bar_padding_positive': 0.04,
     'horizontal_bar_padding_mixed': 0.06,
     'money_axis': 'auto',
     'x_nticks': 15,
     'show_all_y_categories': True,
     'title': '<b>Ultimi P/L per strumento</b>'},

    'quotazioni_instrument_performance': {'type': 'time',
     'height': 420,
     'legend': 'bottom',
     'show_buttons': True,
     'default_button': '3M',
     'dynamic_y_to_initial_range': True,
     'dynamic_y_by_button': True,
     'dynamic_y_padding': 0.08,
     'margin_delta': {'t': 0, 'b': -20, 'l': 0, 'r': -20},
     'y_title': 'Indice dal 1° investimento (Base 100)',
     'y_nticks': 8,
     'x_nticks': 15,
     'quarter_mode': None,
     'title': '<b>Rendimento dello strumento</b>',
     'show_extrema': True,
     'extrema_value_format': 'pct1_base100'},

    'analisi_category_performance': {'type': 'time',
     'height': 420,
     'legend': 'bottom',
     'show_buttons': True,
     'default_button': '3M',
     'dynamic_y_to_initial_range': True,
     'dynamic_y_by_button': True,
     'dynamic_y_padding': 0.08,
     'margin_delta': {'t': 0, 'b': -20, 'l': 0, 'r': -20},
     'y_title': 'Indice dal 1° investimento (Base 100)',
     'y_nticks': 8,
     'x_nticks': 15,
     'title': '<b>Rendimento Omogeneizzato per Tipologia</b>',
     'show_extrema': True,
     'extrema_value_format': 'pct1_base100'},

    'analisi_correlation_heatmap': {'type': 'heatmap',
     'height': 540,
     'width': 540,
     'square': True,
     'legend': 'off',
     'show_buttons': False,
     'show_all_heatmap_labels': True,
     'x_tickangle': -90,
     'margin_delta': {'t': 10, 'b': 0, 'l': 0, 'r': 0},
     'title': None},

    'analisi_instrument_drawdown': {'type': 'time',
     'height': 400,
     'legend': 'bottom',
     'show_buttons': True,
     'default_button': 'ALL',
     'margin_delta': {'t': 0, 'b': -20, 'l': 0, 'r': -20},
     'y_nticks': 6,
     'y_tickformat': '.0f',
     'y_ticksuffix': '%',
     'title': '<b>Drawdown per Strumento</b>'},

    'analisi_risk_contribution1': {'type': 'bar',
     'height': 360,
     'legend': 'bottom',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -30, 'l': 0, 'r': -50},
     'bar_padding': 0.12,
     'horizontal_bar_auto_range': True,
     'horizontal_bar_force_zero_start': True,
     'horizontal_bar_padding_positive': 0.18,
     'horizontal_bar_padding_mixed': 0.20,
     'horizontal_bar_textposition': 'outside',
     'horizontal_bar_textfont_size': 10,
     'bar_cliponaxis': False,
     'x_title': 'Quota % del portafoglio / del rischio',
     'x_tickformat': '.0%',
     'show_all_y_categories': True,
     'x_nticks': 15,
     'title': '<b>Allineamento rispetto ad obiettivo</b>'},

    'analisi_risk_contribution2_v3': {'type': 'bar',
     'height': 600,
     'legend': 'bottom',
     'show_buttons': False,
     'margin_delta': {'t': 0, 'b': -50, 'l': 0, 'r': -50},
     'bar_padding': 0.4,
     'horizontal_bar_auto_range': True,
     'horizontal_bar_force_zero_start': False,
     'horizontal_bar_padding_positive': 0.02,
     'horizontal_bar_padding_mixed': 0.04,
     'bar_textposition': 'outside',
     'bar_textfont_size': 10,
     'x_title': 'Quota % del portafoglio / del rischio',
     'x_tickformat': '.0%',
     'show_all_y_categories': True,
     'x_nticks': 15,
     'title': '<b>Contributo al rischio</b>'},

    # ------------------------------------------------------------------
    # DEFAULT
    # ------------------------------------------------------------------

    '_default_timeseries': {'type': 'time',
     'height': None,
     'legend': 'bottom',
     'show_buttons': True,
     'default_button': 'ALL',
     'margin_delta': {'t': 0, 'b': 0, 'l': 0, 'r': 0},
     'auto_streamlit_extrema': False},
}

# ═══════════════════════════════════════════════════════════════════════════════
# 3) BOTTONI TEMPORALI
# ═══════════════════════════════════════════════════════════════════════════════

_RANGE_BUTTONS: dict[str, dict[str, Any]] = {
    "1M": dict(label="1M", step="month", count=1, stepmode="backward"),
    "3M": dict(label="3M", step="month", count=3, stepmode="backward"),
    "6M": dict(label="6M", step="month", count=6, stepmode="backward"),
    "YTD": dict(label="YTD", step="year", count=1, stepmode="todate"),
    "1Y": dict(label="1Y", step="year", count=1, stepmode="backward"),
    "ALL": dict(label="ALL", step="all"),
}
_RANGE_BUTTON_ORDER = ["1M", "3M", "6M", "YTD", "1Y", "ALL"]


# ═══════════════════════════════════════════════════════════════════════════════
# 4) MOTORE INTERNO — MODIFICA SOLO SE VUOI CAMBIARE IL COMPORTAMENTO GENERALE
# ═══════════════════════════════════════════════════════════════════════════════

def _chart_settings(chart_id: str) -> dict[str, Any]:
    return _resolve_chart_settings_runtime(CHARTS, chart_id)

def get_chart_setting(chart_id: str, key: str, default=None):
    """
    Restituisce un parametro operativo del grafico.

    Priorità reale:
    1. valore nel blocco CHARTS[chart_id];
    2. valore globale in GLOBAL_STYLE;
    3. valore nel fallback CHARTS['_default_timeseries'];
    4. default passato dalla chiamata.

    Nota: show_extrema usa GLOBAL_STYLE['show_extrema_default'] se il grafico
    non specifica show_extrema. I parametri extrema_* globali devono funzionare
    senza doverli ripetere in ogni singolo grafico.
    """
    return _get_chart_setting_value_runtime(CHARTS, GLOBAL_STYLE, chart_id, key, default)

def _layout_has_xaxis_title(fig) -> bool:
    from ui.charts.layout import layout_has_xaxis_title as _layout_has_xaxis_title_layout

    return _layout_has_xaxis_title_layout(fig)

def _coerce_axis_range(value):
    return _coerce_axis_range_layout(value)

def _title_text(fig) -> str:
    return _title_text_layout(fig)

def _is_undefined(text: str) -> bool:
    return _is_undefined_layout(text)

def _setting_title(settings: dict[str, Any]) -> str:
    return _setting_title_layout(settings)

def _effective_title(settings: dict[str, Any], fig) -> str:
    """
    Priorità titolo:
    1. titolo dinamico già presente nella figura, se valido;
    2. titolo manuale in CHARTS;
    3. nessun titolo.
    """
    return _effective_title_layout(settings, fig)

def _show_title(settings: dict[str, Any], fig) -> bool:
    return _show_title_layout(settings, fig, GLOBAL_STYLE)

def _show_legend(settings: dict[str, Any]) -> bool:
    return _show_legend_layout(settings, GLOBAL_STYLE)

def _show_buttons(settings: dict[str, Any]) -> bool:
    return _show_buttons_layout(settings, GLOBAL_STYLE)

def _legend_layout(where: str) -> dict[str, Any] | None:
    return _legend_layout_layout(where, GLOBAL_STYLE)

def _apply_margin_delta(base: dict[str, int], delta: dict[str, Any] | None) -> dict[str, int]:
    return _apply_margin_delta_layout(base, delta)

def _computed_margin(fig, settings: dict[str, Any]) -> dict[str, int]:
    return _computed_margin_layout(fig, settings, GLOBAL_STYLE)

def _button_range(min_date, max_date, key: str, left_pad=None, right_pad=None):
    """Restituisce il range temporale agganciato all'ultima data reale.

    left_pad/right_pad servono soprattutto per grafici temporali a barre:
    senza un piccolo respiro la prima/ultima barra può risultare troncata.
    Devono essere Timedelta, non interi, perché pandas non consente Timestamp +/- int.
    """
    from ui.charts.time_buttons import button_range as _compute_button_range

    return _compute_button_range(
        min_date,
        max_date,
        key,
        left_pad,
        right_pad,
        use_calendar=bool(GLOBAL_STYLE.get("time_use_calendar_offsets", True)),
    )

def _has_temporal_bar_trace(fig) -> bool:
    return _has_temporal_bar_trace_runtime(fig)

def _time_edge_padding(fig, settings: dict[str, Any]):
    return _time_edge_padding_runtime(fig, settings, GLOBAL_STYLE)

def _range_from_visible_values(values, settings: dict[str, Any]) -> list[float] | None:
    """Calcola il range Y sui soli valori visibili nella finestra temporale.

    È usata dai bottoni 1M/3M/6M/YTD/1Y/ALL quando dynamic_y_by_button=True
    e all'apertura iniziale quando dynamic_y_to_initial_range=True.
    A differenza della protezione barre, qui NON si forza lo zero: nei grafici
    temporali il range deve seguire min/max reali della porzione visibile.
    """
    pad = float(settings.get("dynamic_y_padding", GLOBAL_STYLE.get("dynamic_y_padding", 0.08)))
    return _compute_range_from_visible_values(values, pad)

def _visible_y_ranges_for_x_range(fig, x_range, settings: dict[str, Any]) -> dict[str, list[float]]:
    """Restituisce i range Y dinamici per ogni asse Y della figura.

    Nei grafici multi-asse/subplot i valori vengono raggruppati per asse Y
    reale della traccia, evitando che una serie monetaria allarghi l'asse di
    una serie percentuale o viceversa. Il risultato è un dizionario pronto per
    relayout, ad esempio {"yaxis": [min, max], "yaxis2": [min, max]}.
    """
    pad = float(settings.get("dynamic_y_padding", GLOBAL_STYLE.get("dynamic_y_padding", 0.08)))
    return _compute_visible_y_ranges_for_x_range(fig, x_range, pad)

def _apply_initial_visible_y_range(fig, settings: dict[str, Any]) -> None:
    """Applica il range Y dinamico all'apertura iniziale del grafico temporale.

    Serve quando dynamic_y_to_initial_range=True: dopo che il default_button ha
    fissato l'intervallo X iniziale, questa funzione ricalcola gli assi Y sui
    soli valori effettivamente visibili in quella finestra. Non interviene sui
    grafici non temporali e non sovrascrive range Y espliciti impostati a mano.
    """
    _apply_initial_visible_y_range_runtime(
        fig,
        settings,
        time_extent=_time_extent,
        time_edge_padding=_time_edge_padding,
        button_range=_button_range,
        plotly_range=_plotly_range,
        visible_y_ranges_for_x_range=_visible_y_ranges_for_x_range,
    )

def _apply_buttons(fig, settings: dict[str, Any]) -> None:
    """Applica i bottoni temporali.

    Con time_button_engine='relayout' i bottoni non usano il rangeselector nativo,
    ma impostano esplicitamente il range di tutti gli assi X: questo evita che
    1M/3M/6M perdano l'ancoraggio all'ultima data disponibile.
    """
    _apply_time_buttons(
        fig,
        settings,
        GLOBAL_STYLE,
        show_buttons=_show_buttons,
        time_edge_padding=_time_edge_padding,
        visible_y_ranges_for_x_range=_visible_y_ranges_for_x_range,
        range_buttons=_RANGE_BUTTONS,
        range_button_order=_RANGE_BUTTON_ORDER,
        button_range_fn=_button_range,
        plotly_range_fn=_plotly_range,
        plotly_date_fn=_plotly_date,
    )

def _data_range_for_axis(fig, data_axis: str) -> list[float] | None:
    return _data_range_for_axis_runtime(fig, data_axis, numeric_values=_numeric_values)

def _range_from_min_max(fig, data_axis: str, min_value, max_value) -> list[float] | None:
    return _range_from_min_max_runtime(
        fig,
        data_axis,
        min_value,
        max_value,
        numeric_values=_numeric_values,
    )

def _bar_protection(fig, settings: dict[str, Any]) -> None:
    _apply_bar_protection_runtime(
        fig,
        settings,
        GLOBAL_STYLE,
        numeric_values=_numeric_values,
        trace_xaxis_layout_name=_trace_xaxis_layout_name,
        range_with_padding=_range_with_padding,
        update_axis_range=_update_axis_range,
    )

def _compact_money_axes(fig, settings: dict[str, Any]) -> None:
    _apply_compact_money_axes(fig, settings, GLOBAL_STYLE, numeric_values=_numeric_values)

def _normalise_baseline_lines(fig, settings: dict[str, Any]) -> None:
    """
    Uniforma la linea tecnica Base 100 dai parametri di charts_settings.py.

    La linea Base 100 nasce dentro alcuni builder di charts.py con fig.add_hline(y=100, ...).
    Questa funzione la intercetta a valle, durante apply_settings, e consente di gestire
    colore, tratteggio, spessore e opacità senza rientrare nei singoli grafici.
    Per sicurezza modifica solo shapes di tipo line con y0 == y1 == 100.
    """
    _apply_baseline_line_normalisation(fig, settings, GLOBAL_STYLE)

def _normalise_baseline_axis_titles(fig, settings: dict[str, Any]) -> None:
    """Colora i titoli degli assi che contengono 'Base 100'.

    Alcune scritte Base 100 non sono annotazioni Plotly ma titoli asse, ad esempio
    "Indice dal 1° investimento (Base 100)". Qui uso dizionari Plotly puri
    per evitare che oggetti ``layout.yaxis.title.Font`` non vengano aggiornati
    correttamente quando Streamlit serializza la figura.
    """
    _apply_baseline_axis_title_normalisation(fig, settings, GLOBAL_STYLE)

def _normalise_annotations(fig, settings: dict[str, Any]) -> None:
    """Uniforma annotazioni/subplot title senza rovinare le note tecniche.

    Le annotazioni Base 100 vengono convertite in dizionari Plotly prima della
    modifica: è più affidabile rispetto all'assegnazione diretta ``ann.font = ...``
    sugli oggetti Annotation, che in alcuni casi resta grigia in Streamlit.
    """
    _apply_annotation_normalisation(
        fig,
        settings,
        GLOBAL_STYLE,
        show_title=_show_title(settings, fig),
        is_undefined=_is_undefined,
    )

def _add_quarter_gridlines(fig, settings: dict[str, Any]) -> None:
    _add_quarter_gridlines_runtime(fig, settings, GLOBAL_STYLE)

def _apply_axis_settings(fig, settings: dict[str, Any]) -> tuple[list[Any] | None, list[Any] | None, list[Any] | None]:
    """Applica range/tickformat/nticks e restituisce i range forzati per riapplicarli dopo il padding barre."""
    return _apply_axis_settings_runtime(
        fig,
        settings,
        GLOBAL_STYLE,
        coerce_axis_range=_coerce_axis_range,
        range_from_min_max_fn=_range_from_min_max,
    )

def _normalise_bar_text(fig, settings: dict[str, Any]) -> None:
    """Normalizza testo e clipping delle barre dai parametri di setting.

    La funzione lavora a valle dei builder in charts.py: non cambia i dati,
    ma uniforma solo la presentazione delle tracce go.Bar.

    Parametri principali:
    - horizontal_bar_textposition / horizontal_bar_textfont_size: valgono solo
      per barre orizzontali, dove l'obiettivo è avere il valore fuori barra a destra;
    - bar_textposition / bar_textfont_size: fallback generale per le altre barre;
    - bar_cliponaxis: se False evita che i testi fuori barra vengano tagliati.

    Nota: se nel singolo grafico un parametro è None, la funzione non forza quel
    dettaglio e lascia prevalere l'impostazione già definita in charts.py.
    """
    _apply_bar_text_normalisation(fig, settings, GLOBAL_STYLE)

def _force_all_y_categories(fig, settings: dict[str, Any]) -> None:
    """Forza la visualizzazione di tutte le categorie sull'asse Y nei grafici a barre orizzontali."""
    _apply_all_y_categories(fig, settings, GLOBAL_STYLE)

def _force_all_x_categories(fig, settings: dict[str, Any]) -> None:
    """Forza tutte le etichette sull'asse X per waterfall/barre verticali categoriali."""
    _apply_all_x_categories(fig, settings, GLOBAL_STYLE)

def _force_heatmap_labels_and_square(fig, settings: dict[str, Any]) -> None:
    """Rende le heatmap realmente quadrate e con tutte le etichette visibili.

    Nota Streamlit: layout.width=height da solo spesso non basta, perché
    st.plotly_chart(..., width="stretch") può stirare il contenitore. Per questo
    oltre a width/height si imposta anche aspect reale sugli assi Plotly tramite
    scaleanchor/scaleratio: in questo modo le celle della matrice restano quadrate
    anche se il contenitore esterno è più largo.
    """
    _apply_heatmap_category_normalisation(fig, settings)

def _force_time_default_range(fig, settings: dict[str, Any]) -> None:
    """Forza il range iniziale dei grafici temporali come ultimo passaggio.

    Evita che Streamlit/Plotly riapra il grafico in ALL conservando uno zoom precedente.
    Non fa nulla se il grafico non è temporale, se non ha bottoni o se il parametro globale è spento.
    """
    _force_time_default_range_runtime(
        fig,
        settings,
        GLOBAL_STYLE,
        show_buttons=_show_buttons,
        time_extent=_time_extent,
        time_edge_padding=_time_edge_padding,
        as_timedelta=_as_timedelta,
        button_range=_button_range,
        plotly_range=_plotly_range,
        iter_xaxis_names=_iter_xaxis_names,
        range_buttons=_RANGE_BUTTONS,
        range_button_order=_RANGE_BUTTON_ORDER,
    )

def _apply_horizontal_bar_axis_spacing(fig, settings: dict[str, Any]) -> None:
    _apply_horizontal_bar_axis_spacing_runtime(
        fig,
        settings,
        GLOBAL_STYLE,
        has_horizontal_bar=_has_horizontal_bar(fig),
    )

def _reapply_forced_ranges(fig, x_range, y_range, y2_range) -> None:
    _reapply_forced_ranges_runtime(
        fig,
        x_range=x_range,
        y_range=y_range,
        y2_range=y2_range,
    )

def _reapply_y2_after_money(fig, settings: dict[str, Any]) -> None:
    _reapply_y2_after_money_runtime(fig, settings)

def _apply_chart_chrome(fig, settings: dict[str, Any], margin: dict[str, int]) -> None:
    _apply_chart_chrome_runtime(
        fig,
        settings,
        GLOBAL_STYLE,
        margin=margin,
        show_title=_show_title(settings, fig),
        show_legend=_show_legend(settings),
        effective_title=_effective_title(settings, fig),
        legend_layout=_legend_layout(str(settings.get("legend", "bottom"))),
    )

def apply_settings(fig, chart_id: str):
    """Applica il layout finale. Deve essere l'ultima chiamata prima del return del grafico."""
    settings = _chart_settings(chart_id)
    return _apply_settings_pipeline_runtime(
        fig,
        settings,
        clear_all_range_controls=_clear_all_range_controls,
        computed_margin=_computed_margin,
        apply_chart_chrome=_apply_chart_chrome,
        apply_axis_settings=_apply_axis_settings,
        apply_buttons=_apply_buttons,
        bar_protection=_bar_protection,
        normalise_bar_text=_normalise_bar_text,
        force_all_y_categories=_force_all_y_categories,
        force_all_x_categories=_force_all_x_categories,
        force_heatmap_labels_and_square=_force_heatmap_labels_and_square,
        apply_horizontal_bar_axis_spacing=_apply_horizontal_bar_axis_spacing,
        reapply_forced_ranges=_reapply_forced_ranges,
        compact_money_axes=_compact_money_axes,
        reapply_y2_after_money=_reapply_y2_after_money,
        force_time_default_range=_force_time_default_range,
        apply_initial_visible_y_range=_apply_initial_visible_y_range,
        normalise_baseline_lines=_normalise_baseline_lines,
        normalise_baseline_axis_titles=_normalise_baseline_axis_titles,
        normalise_annotations=_normalise_annotations,
        add_quarter_gridlines=_add_quarter_gridlines,
    )
