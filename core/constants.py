"""
core/constants.py — Costanti globali, enumerazioni, configurazioni fisse.
Unica fonte di verità per enum e costanti.
"""
from enum import Enum
from typing import Dict, Tuple, Optional

from core.config import COLORS
# ═════════════════════════════════════════════════════════════════════
# Tipi di evento
# ═════════════════════════════════════════════════════════════════════
class TipoEvento(str, Enum):
    """Tipi di evento nel registro."""
    ACQUISTO = "ACQUISTO"
    VENDITA = "VENDITA"
    RIMBORSO_SCADENZA = "RIMBORSO A SCADENZA"
    CEDOLA = "CEDOLA"
    DIVIDENDO = "DIVIDENDO"
    VERSAMENTO = "VERSAMENTO"
    PRELIEVO = "PRELIEVO"
    COMMISSIONE = "COMMISSIONE"
    IMPOSTA = "IMPOSTA"


TIPI_EVENTO_PORTAFOGLIO = [e.value for e in TipoEvento]

EVENTI_CON_STRUMENTO = {
    TipoEvento.ACQUISTO, TipoEvento.VENDITA, TipoEvento.RIMBORSO_SCADENZA,
    TipoEvento.CEDOLA, TipoEvento.DIVIDENDO
}

EVENTI_CON_QUANTITA = {
    TipoEvento.ACQUISTO, TipoEvento.VENDITA, TipoEvento.RIMBORSO_SCADENZA
}

EVENTI_CON_PREZZO = {
    TipoEvento.ACQUISTO, TipoEvento.VENDITA, TipoEvento.RIMBORSO_SCADENZA
}

EVENTI_CON_IMPORTO = {
    TipoEvento.CEDOLA, TipoEvento.DIVIDENDO,
    TipoEvento.VERSAMENTO, TipoEvento.PRELIEVO,
    TipoEvento.COMMISSIONE, TipoEvento.IMPOSTA
}


# ═════════════════════════════════════════════════════════════════════
# Categorie di strumenti
# ═════════════════════════════════════════════════════════════════════
class Categoria(str, Enum):
    """Categorie di strumenti."""
    LIQ = "LIQ"
    GOV = "GOV"
    OBB = "OBB"
    AZI = "AZI"
    ETF = "ETF"
    ETC = "ETC"
    FND = "FND"
    DER = "DER"


CATEGORIE = [c.value for c in Categoria]

TIPO_A_CATEGORIA: Dict[str, str] = {
    "titolo di stato": "GOV",
    "btp": "GOV",
    "obbligazione": "OBB",
    "etf": "ETF",
    "etc": "ETC",
    "fondo chiuso": "FND",
    "fondo": "FND",
}


# ═════════════════════════════════════════════════════════════════════
# Colori per tema
# ═════════════════════════════════════════════════════════════════════
COLORI_CATEGORIA = {
    "LIQ": "#26A69A",
    "GOV": COLORS["category_gov"],
    "OBB": "#7E57C2",
    "AZI": "#EF6C9A",
    "ETF": COLORS["category_etf"],
    "ETC": COLORS["category_etc"],
    "FND": COLORS["category_fnd"],
    "DER": "#8E44AD",
    "default": COLORS["category_default"],
}

COLORI_SENTIMENTO = {
    "green": COLORS["success"],
    "red": COLORS["danger"],
    "orange": COLORS["warning"],
    "gray": COLORS["gray"],
    "blue": COLORS["info"],
    "muted": COLORS["muted"],
}

STRUMENTO_PALETTE = [
    COLORS["instrument_1"], COLORS["instrument_2"], COLORS["instrument_3"],
    COLORS["instrument_4"], COLORS["instrument_5"], COLORS["instrument_6"],
    "#7E57C2", "#42A5F5", "#FF7043", "#9CCC65", "#AB47BC", "#26C6DA",
]


# ═════════════════════════════════════════════════════════════════════
# Benchmark
# ═════════════════════════════════════════════════════════════════════
BENCHMARK_OPZIONI = [
    "Blend automatico",
    "60/40 MSCI World / Bond",
    "100% MSCI World",
    "100% GOV",
]

BENCHMARK_MAPPING: Dict[str, Tuple[str, Optional[str]]] = {
    "gov": ("BTI.MI", None),
    "etf": ("IWDA.AS", None),
    "fnd": ("IWDA.AS", None),
}


# ═════════════════════════════════════════════════════════════════════
# Profili di rischio
# ═════════════════════════════════════════════════════════════════════
PROFILI_RISCHIO = {
    "Prudente": {"GOV": 0.55, "ETF": 0.20, "FND": 0.25},
    "Equilibrato": {"GOV": 0.35, "ETF": 0.35, "FND": 0.30},
    "Dinamico": {"GOV": 0.20, "ETF": 0.50, "FND": 0.30},
    "Neutro": {"GOV": 1/3, "ETF": 1/3, "FND": 1/3},
}


# ═════════════════════════════════════════════════════════════════════
# Formati
# ═════════════════════════════════════════════════════════════════════
DATA_FORMAT_EXPORT = "%d/%m/%Y"
DATA_FORMAT_INTERNAL = "%Y-%m-%d"


# ═════════════════════════════════════════════════════════════════════
# Soglie e limiti
# ═════════════════════════════════════════════════════════════════════
SOGLIA_CONCENTRAZIONE = 0.35
SOGLIA_DRAWDOWN_ALERT = -0.10
SOGLIA_PL_NEGATIVO_ALERT = -500.0
SOGLIA_RIBILANCIAMENTO_MINIMO = 50.0
TOP_CONCENTRATION_POSITIONS_LIMIT = 5

# Soglia unica per "posizione azzerata" (quantita' <= soglia = posizione
# chiusa). Prima duplicata come 0.0001/1e-9/1e-12 in modo indipendente in
# core/portfolio_metrics.py, core/services/cruscotti.py, core/services/
# planning.py, core/services/snapshots.py, core/series_utils.py e altrove.
QTY_ZERO_EPS = 0.0001
