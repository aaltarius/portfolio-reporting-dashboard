"""Task 2 (2026-08-19-classificazione-arricchimento-unificato): fix del bug
di specificita' in infer_sator_metadata (core/services/sator.py) - il ramo
"emerging" nel name veniva controllato PRIMA del ramo bond, quindi un fondo
"Emerging Markets Bond" finiva classificato come azionario invece che come
obbligazionario. Copre anche le 3 nature nuove (criptovalute, difesa_sicurezza,
azionario_paese_singolo, aggiunte in c7da74c) e il nuovo campo "confidence".
"""
from __future__ import annotations

from core.services.sator import infer_sator_metadata


def test_emerging_market_bond_classified_as_bond_not_equity():
    # NOTA: il brief del task usava nome="iShares EM Bond UCITS ETF", ma "EM"
    # (abbreviazione) non contiene la sottostringa "emerg" quindi quel testo
    # NON riproduce il bug (matcha gia' il ramo bond anche senza il fix,
    # verificato manualmente pre-implementazione). Per riprodurre davvero
    # l'ambiguita' descritta nel bug ("un fondo 'Emerging Markets Bond' viene
    # misclassificato come azionario") il nome deve contenere la parola
    # per esteso "Emerging" insieme a "Bond".
    item = {"ticker": "XEMB.MI", "nome": "iShares Emerging Markets Bond UCITS ETF", "tipo": "ETF Obbl. Em."}
    result = infer_sator_metadata(item, True)
    assert result["nature"] == "bond_globale"
    assert result["role"] == "bond"


def test_crypto_instrument_gets_dedicated_nature():
    item = {"ticker": "IB1T.PA", "nome": "iShares Bitcoin ETP", "tipo": "ETC"}
    result = infer_sator_metadata(item, True)
    assert result["nature"] == "criptovalute"


def test_defense_instrument_gets_dedicated_nature():
    item = {"ticker": "WDEF.MI", "nome": "Global Defence & Security UCITS ETF", "tipo": "ETF"}
    result = infer_sator_metadata(item, True)
    assert result["nature"] == "difesa_sicurezza"


def test_single_country_equity_gets_dedicated_nature_not_generic_core():
    # NOTA: `!= "azionario_globale_core"` da solo e' un'asserzione debole -
    # oggi (pre-fix) questo strumento finisce gia' in "altro" per esclusione
    # (nessun ramo lo riconosce), quindi il confronto "!=" sarebbe gia'
    # banalmente vero anche senza implementare il ramo dedicato. Rafforzato
    # per verificare che il nuovo ramo "azionario_paese_singolo" (aggiunto in
    # Task 1, c7da74c) venga effettivamente usato.
    item = {"ticker": "XXSC.MI", "nome": "Xtrackers MSCI EU Smallcap UCITS ETF", "tipo": "ETF"}
    result = infer_sator_metadata(item, True)
    assert result["nature"] != "azionario_globale_core"
    assert result["nature"] == "azionario_paese_singolo"


def test_inferred_metadata_has_confidence_field():
    item = {"ticker": "SWDA.MI", "nome": "iShares Core MSCI World UCITS ETF", "tipo": "ETF Az. Globale"}
    result = infer_sator_metadata(item, True)
    assert result["confidence"] in ("alta", "media", "bassa")
    assert result["confidence"] == "alta"  # match specifico su tk_in("swda", ...)


def test_unrecognized_instrument_has_low_confidence():
    item = {"ticker": "ZZZZ.XX", "nome": "Strumento Sconosciuto Ignoto", "tipo": "ETF"}
    result = infer_sator_metadata(item, True)
    assert result["confidence"] == "bassa"
