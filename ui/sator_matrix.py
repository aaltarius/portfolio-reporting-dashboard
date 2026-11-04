"""
ui/sator_matrix.py — Convenzioni della tabella decisionale SATOR.

Scelta tecnica: niente pandas Styler dentro st.data_editor. I fattori usano
ProgressColumn nativa, con colore di colonna non punitivo: Streamlit consente
un colore statico per colonna, mentre il significato per valore resta nel numero
1-10 e nel semaforo di riga.
"""
from __future__ import annotations

from typing import Any

import streamlit as st


# Colonne mostrate nell'editor, nell'ordine: contesto, semaforo, i 5 fattori, voto, quote.
SATOR_MATRIX_COLUMNS = [
    "Sel", "Qta", "Sem", "Tk", "Qp", "Px",
    "Fit", "Mom", "Risk", "Div", "Cost",
    "Voto", "Sug", "Gruppo",
]
# Tutto e' in sola lettura tranne la selezione e la quantita' manuale.
SATOR_MATRIX_DISABLED_COLUMNS = [
    "Sem", "Tk", "Qp", "Px", "Fit", "Mom", "Risk", "Div", "Cost", "Voto", "Sug", "Gruppo",
]


def sator_matrix_column_config() -> dict[str, Any]:
    def fattore(label: str, aiuto: str, color: str = "green") -> Any:
        return st.column_config.ProgressColumn(
            label, help=aiuto, min_value=1, max_value=10, format="%.1f", width=68, color=color
        )
    return {
        "Sel": st.column_config.CheckboxColumn("S", help="Includi nella scelta manuale", width=42),
        "Qta": st.column_config.NumberColumn("Q", help="Quote da acquistare", min_value=0, step=1, format="%d", width=46),
        "Sem": st.column_config.TextColumn(
            "•", disabled=True, width=34,
            help="Verde = SATOR ne suggerisce l'acquisto. Giallo = migliore della sua funzione ma fuori budget. Bianco = battuto nella sua funzione.",
        ),
        "Tk": st.column_config.TextColumn("Tk", disabled=True, width=76),
        "Qp": st.column_config.NumberColumn("Qp", disabled=True, format="%.2f", width=58),
        "Px": st.column_config.NumberColumn("Px", disabled=True, format="%.2f", width=70),
        "Fit": fattore("Fit", "Fit allocativo: quanto la funzione serve ora al portafoglio (peso 30%).", "blue"),
        "Mom": fattore("Mom", "Andamento ponderato 1/3/6/12 mesi (peso 25%).", "orange"),
        "Risk": fattore("Risk", "Efficienza di rischio: volatilita', drawdown, rendimento/rischio (peso 20%).", "red"),
        "Div": fattore("Div", "Beneficio di diversificazione: bassa correlazione e copertura di vuoti (peso 15%).", "violet"),
        "Cost": fattore("Costo", "Efficienza operativa: commissioni, TER, spread, prezzo/budget (peso 10%).", "gray"),
        "Voto": st.column_config.ProgressColumn(
            "Voto", help="Punteggio unico 1-10. Ordina la tabella: il numero che leggi e' quello che decide la posizione.",
            min_value=1, max_value=10, format="%.1f", width=68, color="green",
        ),
        "Sug": st.column_config.NumberColumn("Sug", disabled=True, help="Quote suggerite entro budget (residuo ammesso)", format="%d", width=48),
        "Gruppo": st.column_config.TextColumn("Funz.", disabled=True, help="Gruppo omogeneo di confronto", width=160),
    }


def sator_matrix_height(row_count: int) -> int:
    return min(700, 82 + max(1, int(row_count or 1)) * 34)
