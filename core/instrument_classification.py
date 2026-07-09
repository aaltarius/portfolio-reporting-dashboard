"""Classificazione automatica della "natura"/esposizione di uno strumento,
usata per l'icona in Quotazioni e Portafoglio. Usa i dati di arricchimento
affidabili (benchmark, focus_etf) oltre a tipo/nome, non solo il nome
abbreviato mostrato da Fineco."""
from __future__ import annotations

_SINGLE_COUNTRY_TOKENS: dict[str, tuple[str, ...]] = {
    "Italia": ("italia", "italy", "ftse mib", "mib", "mid cap italy", "pir"),
    "India": ("india", "ftse india", "nifty"),
    "Cina": ("china", "cina", "csi 300", "msci china"),
    "Brasile": ("brasile", "brazil", "bovespa"),
    "Giappone": ("giappone", "japan", "topix", "nikkei"),
}

_RULES: list[tuple[tuple[str, ...], str]] = [
    (("bitcoin", "crypto", "criptovalut", "btc"), "Criptovalute"),
    (("quality", "qualit"), "Quality factor"),
    (("defence", "defense", "military", "aerospace", "security"), "Difesa / sicurezza"),
    (("oro", "gold", "xau", "metallo"), "Bene rifugio"),
    (("metals", "miners", "mining", "mine", "silver miners", "uranium", "copper", "metal miners"), "Metalli e miniere"),
    (("commodity", "commodities", "broad cmdty", "raw material", "materie prime", "barrel", "dbc", "cmod"), "Commodities"),
    (("emerging", "emergenti", "em market", "emerging markets"), "Mercati emergenti"),
    (("immob", "casa", "reit", "real estate", "realty", "property"), "Immobiliare"),
    (("overnight", "liquid", "cash", "xeon", "monet", "treasury bill"), "Liquidità"),
    (("btp", "gov", "bond", "obbl", "bot", "cct", "titolo di stato", "sovereign"), "Obbligazionario / reddito"),
    # regola paese singolo inserita qui sotto dinamicamente
    (("energy", "enrg", "oil", "gas", "xle"), "Energia"),
    (("health", "care", "pharma", "biotech", "xdwh"), "Salute"),
    (("art intel", "artificial", "ai ", "xaix", "big data", "tech", "digital"), "Innovazione"),
    (("fless", "flex", "multi asset", "multi-asset", "bilanciato", "bilan", "gestito"), "Fondo gestito / multi-asset"),
    (("world", "all-world", "msci", "global", "vwce", "swda", "xmme"), "Azionario globale core"),
]

_FALLBACK_LABEL = "Esposizione diversificata"

_NAV_FUND_TOKENS = ("fam-", "fless", "flex", "multi asset", "multi-asset", "bilanciato", "gestito")


def is_nav_fund(ticker: str, tipo: str) -> bool:
    """True per fondi gestiti/OICVM che per natura pubblicano NAV non ogni
    giorno di mercato, ma quando il fondo stesso decide (es. i FAM-). Non va
    confuso con la classificazione "natura"/esposizione (classify_natura):
    un FAM- puo' avere natura "Mercati emergenti" o "Fondo bilanciato" ma
    resta comunque un fondo a pubblicazione NAV irregolare."""
    txt = f"{ticker} {tipo}".lower()
    return any(tok in txt for tok in _NAV_FUND_TOKENS)


def _match_text(strumento: dict) -> str:
    parts = (
        str(strumento.get("benchmark") or ""),
        str(strumento.get("focus_etf") or ""),
        str(strumento.get("tipo") or ""),
        str(strumento.get("nome") or ""),
    )
    return " ".join(parts).lower()


def classify_natura(strumento: dict) -> str:
    """Ritorna l'etichetta di natura/esposizione per uno strumento."""
    txt = _match_text(strumento)

    for tokens, label in _RULES[:10]:  # fino a "Obbligazionario / reddito" incluso
        if any(tok in txt for tok in tokens):
            return label

    for country, tokens in _SINGLE_COUNTRY_TOKENS.items():
        if any(tok in txt for tok in tokens):
            return f"Azionario {country}"

    for tokens, label in _RULES[10:]:  # da "Energia" in poi
        if any(tok in txt for tok in tokens):
            if label == "Fondo gestito / multi-asset" and "passivo" in txt:
                # "gestito" (gestione attiva) e "passivo" sono in aperta
                # contraddizione: un fondo il cui stesso tipo dice "Passivo"
                # non e' a gestione attiva, anche se multi-asset/bilanciato
                # (es. FAM-PU6, tipo "Fondo Bilan. Passivo").
                return "Fondo bilanciato"
            return label

    return _FALLBACK_LABEL


import re

_BOND_SIGNAL_TOKENS = ("obbligazio", "bond", " gov ", "aggregate", "titoli di stato")
_EQUITY_SIGNAL_TOKENS = ("azioni,", "azionario", "equity")


def suggest_tipo_correction(strumento: dict) -> str | None:
    """Se benchmark/focus_etf sono in aperta contraddizione con il tipo
    salvato (es. segnale obbligazionario ma tipo dice azionario), ritorna il
    tipo corretto. Altrimenti None. Non richiede dati di rete: usa solo campi
    gia' presenti sullo strumento."""
    benchmark = str(strumento.get("benchmark") or "")
    focus = str(strumento.get("focus_etf") or "")
    tipo = str(strumento.get("tipo") or "")
    if not (benchmark or focus) or not tipo:
        return None

    signal_text = f"{benchmark} {focus}".lower()
    tipo_lower = tipo.lower()

    signals_bond = any(tok in signal_text for tok in _BOND_SIGNAL_TOKENS)
    # Word-boundary match for equity tokens: a plain substring check on
    # "azioni," would false-positive inside "obbligazioni," (e.g. XBAE.MI's
    # bond-fund focus_etf text), wrongly flipping signals_equity to True.
    signals_equity = any(
        re.search(rf"\b{re.escape(tok)}", signal_text) for tok in _EQUITY_SIGNAL_TOKENS
    )
    tipo_says_equity = bool(re.search(r"\baz\.", tipo_lower)) or "azionario" in tipo_lower
    tipo_says_bond = "obbl" in tipo_lower or "titolo di stato" in tipo_lower

    if signals_bond and not signals_equity and tipo_says_equity and not tipo_says_bond:
        corrected = re.sub(r"\bAz\.", "Obbl.", tipo, flags=re.IGNORECASE)
        return corrected if corrected != tipo else None
    if signals_equity and not signals_bond and tipo_says_bond and not tipo_says_equity:
        corrected = re.sub(r"\bObbl\.", "Az.", tipo, flags=re.IGNORECASE)
        return corrected if corrected != tipo else None
    return None
