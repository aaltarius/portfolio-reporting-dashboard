"""Registro centrale benchmark per singolo strumento.

Questo modulo e' l'unica fonte di verita' per assegnare un benchmark operativo
al singolo strumento. Non dipende da Streamlit e non legge/scrive file: espone
solo regole pure e riutilizzabili da Quotazioni, Cruscotti, Summary e refresh
cache benchmark.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.asset_categories import infer_category_code


@dataclass(frozen=True, slots=True)
class BenchmarkAssignment:
    ticker: str
    label: str
    source: str
    confidence: str = "Media"
    note: str = ""

    @property
    def has_benchmark(self) -> bool:
        return bool(str(self.ticker or "").strip())

    def as_dict(self) -> dict[str, str]:
        return {
            "ticker": str(self.ticker or "").strip(),
            "label": str(self.label or "").strip(),
            "source": str(self.source or "").strip(),
            "confidence": str(self.confidence or "").strip(),
            "note": str(self.note or "").strip(),
        }


# Regole specifiche: hanno priorita' massima per evitare ambiguita' su strumenti
# che condividono la stessa macro-categoria ma hanno sottostanti diversi.
BENCHMARK_BY_TICKER: dict[str, BenchmarkAssignment] = {
    "SWDA.MI": BenchmarkAssignment("IWDA.AS", "MSCI World", "ticker diretto", "Alta"),
    "IWQU.MI": BenchmarkAssignment("IWDA.AS", "MSCI World Quality proxy", "ticker diretto", "Media"),
    "XAIX.MI": BenchmarkAssignment("QQQ", "Nasdaq 100 / AI proxy", "ticker diretto", "Media"),
    "XMME.MI": BenchmarkAssignment("EEM", "MSCI Emerging Markets", "ticker diretto", "Alta"),
    "XDRE.MI": BenchmarkAssignment("VNQ", "REIT Index", "ticker diretto", "Media"),
    "XDWH.MI": BenchmarkAssignment("IXJ", "Healthcare proxy", "ticker diretto", "Media"),
    "XBAE.MI": BenchmarkAssignment("AGG", "Global Aggregate Bond", "ticker diretto", "Media"),
    "XDBC.MI": BenchmarkAssignment("DJP", "Bloomberg Commodity", "ticker diretto", "Alta"),
    "ENRG.MI": BenchmarkAssignment("XLE", "Energy Select", "ticker diretto", "Media"),
    "ETFMIB.MI": BenchmarkAssignment("FTSEMIB.MI", "FTSE MIB", "ticker diretto", "Alta"),
    "SGLD.MI": BenchmarkAssignment("GLD", "Gold proxy", "ticker diretto", "Alta", "ETC oro fisico: proxy oro spot/liquido."),
    "GOLD.MI": BenchmarkAssignment("GLD", "Gold proxy", "ticker diretto", "Alta", "ETC oro fisico: proxy oro spot/liquido."),
    "XGDU.MI": BenchmarkAssignment("GDX", "Gold Miners", "ticker diretto", "Media", "ETF/ETC minerari auriferi: proxy azionario minerario, non oro fisico."),
    "XEON.MI": BenchmarkAssignment("SHV", "Short Duration Treasury", "ticker diretto", "Media"),
    "FAMAMW.MI": BenchmarkAssignment("PICK", "Metals & Mining", "ticker diretto", "Media", "Segue MSCI World Metals and Mining (dato arricchito), non l'azionario globale generico."),
}

BENCHMARK_BY_ISIN: dict[str, BenchmarkAssignment] = {
    "IE00B4L5Y983": BENCHMARK_BY_TICKER["SWDA.MI"],
    "IE00B579F325": BENCHMARK_BY_TICKER["SGLD.MI"],
    "FR0013416716": BENCHMARK_BY_TICKER["GOLD.MI"],
    "DE000A2T0VU5": BENCHMARK_BY_TICKER["XGDU.MI"],
}

BENCHMARK_BY_TYPE: dict[str, BenchmarkAssignment] = {
    "etf az. globale": BenchmarkAssignment("IWDA.AS", "MSCI World", "tipo strumento", "Alta"),
    "etf az. emergenti": BenchmarkAssignment("EEM", "MSCI EM", "tipo strumento", "Alta"),
    "etf az. italia": BenchmarkAssignment("FTSEMIB.MI", "FTSE MIB", "tipo strumento", "Alta"),
    "etf monetario": BenchmarkAssignment("SHV", "Short Duration Treasury", "tipo strumento", "Media"),
    "etf": BenchmarkAssignment("IWDA.AS", "MSCI World", "tipo strumento", "Media"),
    "etf materie prime": BenchmarkAssignment("DJP", "Bloomberg Commodity", "tipo strumento", "Alta"),
    "etf energia": BenchmarkAssignment("XLE", "Energy Select", "tipo strumento", "Media"),
    "etf real estate": BenchmarkAssignment("VNQ", "REIT Index", "tipo strumento", "Media"),
    "etf ia": BenchmarkAssignment("QQQ", "Nasdaq 100", "tipo strumento", "Media"),
    "etc oro": BenchmarkAssignment("GLD", "Gold proxy", "tipo strumento", "Alta"),
    "oro": BenchmarkAssignment("GLD", "Gold proxy", "tipo strumento", "Alta"),
    "gold": BenchmarkAssignment("GLD", "Gold proxy", "tipo strumento", "Alta"),
    "metalli preziosi": BenchmarkAssignment("GLD", "Gold proxy", "tipo strumento", "Media"),
    "gold miners": BenchmarkAssignment("GDX", "Gold Miners", "tipo strumento", "Media"),
    "minerari auriferi": BenchmarkAssignment("GDX", "Gold Miners", "tipo strumento", "Media"),
    "titolo di stato": BenchmarkAssignment("BND", "Bond Index", "tipo strumento", "Media", "Proxy obbligazionario generico, non duration-specific."),
    "titolo governativo": BenchmarkAssignment("BND", "Bond Index", "tipo strumento", "Media", "Proxy obbligazionario generico, non duration-specific."),
    "btp": BenchmarkAssignment("BND", "Bond Index", "tipo strumento", "Media", "Proxy obbligazionario generico, non duration-specific."),
    "gov": BenchmarkAssignment("BND", "Bond Index", "tipo strumento", "Media", "Proxy obbligazionario generico, non duration-specific."),
    "fondo obbligazionario": BenchmarkAssignment("BND", "Bond Index", "tipo strumento", "Media"),
    "fondo obbl. merc. em.": BenchmarkAssignment("EMB", "JPM EMBI", "tipo strumento", "Media"),
    "fondo bilanciato": BenchmarkAssignment("IWDA.AS", "MSCI World", "tipo strumento", "Bassa", "Proxy semplificato: non replica la composizione del fondo."),
    "fondo bilan. flessibile": BenchmarkAssignment("IWDA.AS", "MSCI World", "tipo strumento", "Bassa", "Proxy semplificato: non replica la composizione del fondo."),
    "fondo azionario": BenchmarkAssignment("IWDA.AS", "MSCI World", "tipo strumento", "Media"),
    "fondo bilan. passivo": BenchmarkAssignment("IWDA.AS", "MSCI World", "tipo strumento", "Bassa"),
    "fondo az. passivo": BenchmarkAssignment("IWDA.AS", "MSCI World", "tipo strumento", "Media"),
    "azione": BenchmarkAssignment("FTSEMIB.MI", "FTSE MIB", "tipo strumento", "Bassa"),
    "azione italiana": BenchmarkAssignment("FTSEMIB.MI", "FTSE MIB", "tipo strumento", "Media"),
    "azione globalc": BenchmarkAssignment("IWDA.AS", "MSCI World", "tipo strumento", "Bassa"),
}

BENCHMARK_BY_MACRO: dict[str, BenchmarkAssignment] = {
    "GOV": BenchmarkAssignment("BND", "Bond Index", "macro-categoria", "Media", "Proxy obbligazionario generico."),
    "BOND": BenchmarkAssignment("BND", "Bond Index", "macro-categoria", "Media"),
    "OBB": BenchmarkAssignment("BND", "Bond Index", "macro-categoria", "Media"),
    "ETF": BenchmarkAssignment("IWDA.AS", "MSCI World", "macro-categoria", "Bassa", "Fallback generico per ETF non classificati."),
    "ETC": BenchmarkAssignment("DJP", "Bloomberg Commodity", "macro-categoria", "Bassa", "Fallback generico per ETC/commodity non classificati."),
    "FND": BenchmarkAssignment("IWDA.AS", "MSCI World", "macro-categoria", "Bassa", "Fallback generico per fondi non classificati."),
    "AZIONI": BenchmarkAssignment("IWDA.AS", "MSCI World", "macro-categoria", "Bassa"),
}

# Pattern per famiglie di indici reali (dal campo "benchmark" arricchito via
# justETF): lista ordinata dal piu' specifico al piu' generico, perche' il
# match e' per sottostringa e un indice come "MSCI World Information
# Technology" deve scegliere il proxy tecnologia, non il generico MSCI World.
BENCHMARK_BY_INDEX_PATTERN: list[tuple[str, BenchmarkAssignment]] = [
    ("bitcoin", BenchmarkAssignment("BTC-USD", "Bitcoin", "benchmark arricchito", "Alta")),
    ("information technology", BenchmarkAssignment("QQQ", "Nasdaq 100 (proxy tecnologia)", "benchmark arricchito", "Media")),
    ("india", BenchmarkAssignment("INDA", "MSCI India", "benchmark arricchito", "Media")),
    ("miner", BenchmarkAssignment("GDX", "Gold Miners", "benchmark arricchito", "Media")),
    ("gold", BenchmarkAssignment("GLD", "Gold proxy", "benchmark arricchito", "Alta")),
    ("msci emerging", BenchmarkAssignment("EEM", "MSCI EM", "benchmark arricchito", "Alta")),
    ("msci world", BenchmarkAssignment("IWDA.AS", "MSCI World", "benchmark arricchito", "Alta")),
    ("ftse all-world", BenchmarkAssignment("VWRL.AS", "FTSE All-World", "benchmark arricchito", "Alta")),
    ("ftse mib", BenchmarkAssignment("FTSEMIB.MI", "FTSE MIB", "benchmark arricchito", "Alta")),
    ("s&p 500", BenchmarkAssignment("SPY", "S&P 500", "benchmark arricchito", "Alta")),
    ("nasdaq", BenchmarkAssignment("QQQ", "Nasdaq 100", "benchmark arricchito", "Alta")),
    ("bloomberg commodity", BenchmarkAssignment("DJP", "Bloomberg Commodity", "benchmark arricchito", "Media")),
]

# Compatibilita' con il vecchio dizionario BENCH tipo -> (ticker, label).
LEGACY_BENCH: dict[str, tuple[str, str]] = {
    key: (assignment.ticker, assignment.label)
    for key, assignment in BENCHMARK_BY_TYPE.items()
}


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _norm_key(value: Any) -> str:
    return _norm(value).lower()


def _macro_from_type(raw_type: Any) -> str:
    return infer_category_code(raw_type, default="ALTRO")


def resolve_instrument_benchmark(
    instrument: dict[str, Any] | None = None,
    *,
    ticker: str | None = None,
    isin: str | None = None,
    raw_type: str | None = None,
    category: str | None = None,
    master_entry: dict[str, Any] | None = None,
    prefer_master: bool = True,
) -> BenchmarkAssignment:
    """Restituisce il benchmark operativo per uno strumento.

    Ordine di priorita':
    1. eventuale anagrafica master gia' valorizzata;
    2. regola specifica per ticker;
    3. regola specifica per ISIN;
    4. benchmark reale arricchito (campo "benchmark", da justETF);
    5. regola per tipo strumento;
    6. fallback per macro-categoria;
    7. assente.
    """
    inst = instrument if isinstance(instrument, dict) else {}
    master = master_entry if isinstance(master_entry, dict) else {}

    tk = _norm(ticker or inst.get("ticker") or master.get("ticker")).upper()
    isincode = _norm(isin or inst.get("isin") or master.get("isin")).upper()
    typ = _norm(raw_type or inst.get("tipo") or master.get("type_raw"))
    cat = _norm(category or master.get("macro_category") or _macro_from_type(typ)).upper()

    if prefer_master:
        overrides = (master.get("manual_overrides") or {}).get("sator") or {}
        if overrides.get("benchmark_user_edited"):
            mt = _norm(overrides.get("benchmark_code"))
            ml = _norm(overrides.get("benchmark_label"))
            if mt or ml:
                return BenchmarkAssignment(mt, ml or mt or "Benchmark concettuale", "anagrafica", "Alta")

    if tk in BENCHMARK_BY_TICKER:
        return BENCHMARK_BY_TICKER[tk]
    if isincode in BENCHMARK_BY_ISIN:
        return BENCHMARK_BY_ISIN[isincode]

    enriched_benchmark = _norm_key(inst.get("benchmark"))
    if enriched_benchmark:
        for pattern, assignment in BENCHMARK_BY_INDEX_PATTERN:
            if pattern in enriched_benchmark:
                return assignment

    key = _norm_key(typ)
    if key in BENCHMARK_BY_TYPE:
        return BENCHMARK_BY_TYPE[key]

    # Euristiche testuali leggere per evitare dipendenza totale dalla nomenclatura.
    if any(token in key for token in ("gold", "oro", "aurifer")):
        if any(token in key for token in ("miner", "mining", "producer", "xgdu")):
            return BenchmarkAssignment("GDX", "Gold Miners", "euristica tipo", "Media")
        return BenchmarkAssignment("GLD", "Gold proxy", "euristica tipo", "Alta")
    if any(token in key for token in ("btp", "govern", "titolo di stato")):
        return BENCHMARK_BY_TYPE["btp"]
    if any(token in key for token in ("commodity", "materie prime", "commod")):
        return BENCHMARK_BY_TYPE["etf materie prime"]

    if cat in BENCHMARK_BY_MACRO:
        return BENCHMARK_BY_MACRO[cat]

    return BenchmarkAssignment("", "—", "assente", "Bassa")


def known_benchmark_catalog() -> list[tuple[str, str]]:
    """Coppie (ticker, label) uniche di tutti i benchmark noti nel
    catalogo (BENCHMARK_BY_TICKER, BENCHMARK_BY_ISIN, BENCHMARK_BY_TYPE,
    BENCHMARK_BY_MACRO), ordinate per ticker - per popolare un <datalist>
    di scelta rapida nella UI. Il campo benchmark resta testo libero: la
    lista aiuta a scegliere un valore noto senza impedire di inserirne
    uno nuovo mai usato prima."""
    seen: dict[str, str] = {}
    for catalog in (BENCHMARK_BY_TICKER, BENCHMARK_BY_ISIN, BENCHMARK_BY_TYPE, BENCHMARK_BY_MACRO):
        for assignment in catalog.values():
            tk = str(assignment.ticker or "").strip()
            if tk and tk not in seen:
                seen[tk] = str(assignment.label or "").strip()
    return sorted(seen.items())
