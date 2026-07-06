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
            return label

    return _FALLBACK_LABEL
