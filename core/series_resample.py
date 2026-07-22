from __future__ import annotations

import pandas as pd


def downsample_for_display(
    series: pd.Series,
    *,
    recent_days: int = 90,
    freq: str = "W-FRI",
) -> pd.Series:
    """Riduce la risoluzione dei punti più vecchi di `recent_days` per la
    sola visualizzazione a grafico.

    Gli ultimi `recent_days` giorni (relativi all'ultima data della serie,
    non a oggi) restano a risoluzione giornaliera invariata. I punti più
    vecchi vengono aggregati a `freq` (default: settimanale, ancorata al
    venerdì — coerente con dati a giorni lavorativi) usando l'ultimo
    valore disponibile nel periodo — mai la media, per non alterare i
    valori esatti che l'utente vede nei tooltip.

    Se la serie ha `recent_days` punti o meno (indipendentemente
    dall'estensione temporale coperta), viene ritornata intatta senza
    aggregazione: una serie già scarsa (poche osservazioni su un arco
    lungo, es. strumenti poco liquidi) non va aggregata ulteriormente.

    Eventuali NaN presenti nella finestra "recente" non vengono rimossi:
    restano visibili nell'output (decisione esplicita di non nascondere
    buchi nei dati).

    Non tocca in alcun modo i dati sorgente: opera su una copia e va
    chiamata solo immediatamente prima di costruire il grafico, mai sui
    dataframe condivisi usati per calcoli finanziari (drawdown,
    correlazioni, XIRR, P&L, tabelle).
    """
    if series is None or series.empty:
        return series if series is not None else pd.Series(dtype=float)

    series = series.sort_index()

    if len(series) <= recent_days:
        return series

    cutoff = series.index.max() - pd.Timedelta(days=recent_days)

    recent = series[series.index > cutoff]
    older = series[series.index <= cutoff]

    if older.empty:
        return series

    older_resampled = older.resample(freq).last().dropna()

    combined = pd.concat([older_resampled, recent])
    return combined[~combined.index.duplicated(keep="last")].sort_index()
