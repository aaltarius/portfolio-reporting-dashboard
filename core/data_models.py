"""
core/data_models.py — Classi Pydantic per type safety.
Modelli di dati per Portfolio, State, Theme, etc.
"""
from datetime import date, datetime
from typing import Optional, Dict, List, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.config import COLORS


class Operazione(BaseModel):
    """Operazione normalizzata inserita dall'utente o importata da sorgenti esterne."""
    ticker: Optional[str] = None
    tipo: str
    data: date
    qty: Optional[float] = None
    prezzo: Optional[float] = None
    comm: float = 0.0
    note: Optional[str] = None

    @field_validator("tipo")
    @classmethod
    def tipo_non_vuoto(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("Il tipo operazione e' obbligatorio.")
        return value

    @field_validator("ticker")
    @classmethod
    def ticker_normalizzato(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = str(value).strip().upper()
        return value or None

    @field_validator("qty", "prezzo", "comm")
    @classmethod
    def numeri_non_negativi(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and value < 0:
            raise ValueError("Il valore non puo' essere negativo.")
        return value


class Strumento(BaseModel):
    """Un singolo strumento di portafoglio."""
    ticker: str
    nome: str
    tipo: str
    prezzo: float = 0.0
    isin: Optional[str] = None
    aggiornato: Optional[str] = None
    stato: str = "aperto"
    data_chiusura: Optional[str] = None
    motivo_chiusura: Optional[str] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator("ticker")
    @classmethod
    def ticker_obbligatorio(cls, value: str) -> str:
        value = str(value or "").strip().upper()
        if not value:
            raise ValueError("Il ticker e' obbligatorio.")
        return value

    @field_validator("nome", "tipo")
    @classmethod
    def testo_obbligatorio(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("Il campo e' obbligatorio.")
        return value

    @field_validator("prezzo")
    @classmethod
    def prezzo_non_negativo(cls, value: float) -> float:
        if value < 0:
            raise ValueError("Il prezzo non puo' essere negativo.")
        return value


class PortfolioPosition(BaseModel):
    """Una posizione nel portafoglio (open o closed)."""
    ticker: str
    strumento: str
    tipo: str
    quote: float
    prezzo: float
    pmc: float
    controvalore: float
    costo: float
    commissioni: float
    pl_eur: float
    pl_pct: float
    pl_realizzato_lordo: float
    pl_realizzato_netto: float
    imposte: float
    cedole_nette: float
    dividendi_netti: float
    ultimo_evento: Optional[str] = None


class PortfolioState(BaseModel):
    """Stato corrente del portafoglio."""
    posizioni: List[PortfolioPosition] = Field(default_factory=list)
    liquidita: float = 0.0
    patrimonio_totale: float = 0.0
    valore_investito: float = 0.0
    costo_totale: float = 0.0
    pl_non_realizzato: float = 0.0
    pl_realizzato_netto: float = 0.0
    pl_totale: float = 0.0
    pp_percentuale: float = 0.0
    timestamp: Optional[datetime] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ThemeConfig(BaseModel):
    """Configurazione tema (colori, stile)."""
    primary_color: str = COLORS["info"]
    bg_app: str = COLORS["bg_app"]
    bg_surface: str = COLORS["bg_surface"]
    bg_surface_alt: str = COLORS.get("bg_surface_alt", "#f1f5f9")
    bg_chart: str = COLORS["bg_chart"]
    font_color: str = COLORS["font"]
    muted_color: str = "rgba(34,49,68,0.60)"
    border_color: str = "rgba(34,49,68,0.12)"
    grid_color: str = "rgba(34,49,68,0.10)"
    shadow_color: str = "0 14px 32px rgba(31,45,61,0.08)"
    color_green: str = COLORS["success"]
    color_red: str = COLORS["danger"]
    color_orange: str = COLORS["warning"]
    color_yellow: str = COLORS["yellow"]
    color_purple: str = COLORS["purple"]
    color_gray: str = COLORS["gray"]
    color_blue: str = COLORS["info"]
    colors: Dict[str, str] = Field(default_factory=lambda: dict(COLORS))


class KPIData(BaseModel):
    """Dati per un KPI card."""
    titolo: str
    valore: str
    sottotitolo: Optional[str] = None
    accent_color: str = COLORS["info"]
    value_color: str = COLORS["info"]


class EventoPortafoglio(BaseModel):
    """Un evento nel registro (acquisto, vendita, cedola, etc.)."""
    event_id: str
    data: str
    tipo_evento: str
    ticker: Optional[str] = None
    quantita: Optional[float] = None
    prezzo_unitario: Optional[float] = None
    commissioni: Optional[float] = 0.0
    imposte: Optional[float] = 0.0
    importo_lordo: Optional[float] = None
    importo_netto: Optional[float] = None
    aliquota: Optional[float] = None
    note: Optional[str] = None

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "EventoPortafoglio":
        """Crea un evento validato da un dizionario grezzo."""
        return cls(**payload)

    @field_validator("event_id", "data", "tipo_evento")
    @classmethod
    def campi_base_obbligatori(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("Il campo e' obbligatorio.")
        return value

    @field_validator("ticker")
    @classmethod
    def evento_ticker_normalizzato(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = str(value).strip().upper()
        return value or None
