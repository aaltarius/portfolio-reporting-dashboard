# FONTI ONLINE DA IMPLEMENTARE / VERIFICARE

## Borsa Italiana
Uso principale:
- identità ETF/bond;
- benchmark ufficiale;
- codici indice;
- metadata.

## OpenFIGI
Uso principale:
- mapping `ID_ISIN`;
- identità/security type/market sector/exchange;
- batch lookup.

## Yahoo / yfinance
Uso principale:
- Search;
- `Lookup(query).get_index()` per INDEX;
- storici;
- FundsData per look-through.

## Issuer / factsheet / KID
Uso principale:
- multi-asset;
- fondi;
- benchmark/allocazione non presenti altrove.

## Index providers
MSCI/STOXX/FTSE/S&P/Nasdaq/Solactive/Bloomberg/ICE/altro.
Uso:
- canonicalizzazione;
- exact series se disponibile;
- family relations.

## ECB / Banca d'Italia
Uso:
- €STR;
- sovereign curves;
- bond synthetic duration-specific.

## Regola tecnica

Adapter di fonte separati dal resolver.
Ogni adapter restituisce dati + provenance + timestamp.
Nessun adapter decide autonomamente il C/D/S o il benchmark finale.
