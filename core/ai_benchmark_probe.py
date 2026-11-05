"""core/ai_benchmark_probe.py — Prova: benchmark ufficiali degli strumenti via Gemini (una sola richiesta).

Pagina di test (AI → «Test benchmark»): chiede a Gemini, in una singola chiamata, l'indice
di riferimento ufficiale di ogni strumento posseduto. Il risultato NON viene salvato né
usato dai calcoli: serve a valutare se la risposta e' affidabile.
Alla richiesta vanno solo ticker, ISIN, nome e tipo: mai quantita', importi o P/L.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from core.ai_analysis import _parse_structured_response, call_gemini_flash

_PROBE_FIELDS = ("ticker", "isin", "nome", "tipo")

_PROMPT_HEADER = """\
Per ciascuno strumento finanziario elencato indica il benchmark (indice di riferimento) UFFICIALE
dichiarato dall'emittente nel KID/KIID, nel prospetto o nella scheda prodotto, e dove ottenere lo storico
giornaliero di quell'indice.

Regole:
- Usa solo informazioni ufficiali dell'emittente e non inventare: se non sei sicuro scrivi "non disponibile".
- "origine_dato" deve essere "documento consultato" solo se hai davvero letto il documento in questa risposta;
  se vai a memoria scrivi "ricordo". Non usare "alta" come confidenza se vai a memoria.
- Per titoli di Stato, ETC e strumenti senza indice ufficiale scrivi "nessun indice ufficiale" e spiega in "note".
- Indica la variante (TR = total return, NR = net return, PR = price return) solo se dichiarata.
- "indice_simbolo": il codice dell'indice come compare su un fornitore di dati (per esempio simbolo Yahoo Finance
  che inizia con ^, codice Bloomberg o RIC); "n.d." se non lo conosci.
- "storico_scaricabile": "si" solo se sai che lo storico giornaliero dell'indice (o del suo total return) si scarica
  gratuitamente; "parziale" se esiste solo una versione diversa (per esempio price return o un indice gemello);
  "no" o "n.d." altrimenti. Se "no", indica in "note" un ETF o indice proxy con storico scaricabile.
- "dove_scaricarlo": fornitore e simbolo o indirizzo preciso (per esempio il sito dell'amministratore dell'indice);
  "n.d." se non lo sai.

Rispondi ESCLUSIVAMENTE con un oggetto JSON valido (nessun testo extra), con questa struttura:
{"strumenti": [{"ticker": "...", "isin": "...", "benchmark_ufficiale": "...", "fornitore_indice": "...",
"variante": "TR|NR|PR|n.d.", "indice_simbolo": "...", "storico_scaricabile": "si|parziale|no|n.d.",
"dove_scaricarlo": "...", "origine_dato": "documento consultato|ricordo", "fonte": "documento o URL ufficiale",
"confidenza": "alta|media|bassa", "note": "..."}]}
Includi tutti gli strumenti, uno per riga, con lo stesso ticker dell'elenco.

Strumenti:
"""


@dataclass
class BenchmarkProbeResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    raw_text: str = ""


def collect_probe_instruments(data: dict[str, Any], da: pd.DataFrame | None) -> list[dict[str, str]]:
    """Strumenti attualmente in portafoglio (righe di ``da``), con soli ticker/ISIN/nome/tipo."""
    if da is None or da.empty or "Ticker" not in da.columns:
        return []
    held = [str(t) for t in da["Ticker"].tolist()]
    by_ticker = {str(s.get("ticker") or ""): s for s in (data.get("strumenti") or [])}
    rows: list[dict[str, str]] = []
    for ticker in dict.fromkeys(held):
        item = by_ticker.get(ticker, {})
        rows.append({key: str(item.get(key) or (ticker if key == "ticker" else "")) for key in _PROBE_FIELDS})
    return rows


def build_benchmark_probe_prompt(instruments: list[dict[str, str]]) -> str:
    lines = [
        f"- ticker: {r['ticker']} | ISIN: {r['isin'] or 'n.d.'} | nome: {r['nome'] or 'n.d.'} | tipo: {r['tipo'] or 'n.d.'}"
        for r in instruments
    ]
    return _PROMPT_HEADER + "\n".join(lines) + "\n"


def parse_benchmark_probe_response(text: str, expected_tickers: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Ritorna (righe, ticker attesi ma assenti dalla risposta). Solleva RuntimeError se non e' JSON."""
    payload = _parse_structured_response(text)
    rows = [r for r in (payload.get("strumenti") or []) if isinstance(r, dict)]
    answered = {str(r.get("ticker") or "") for r in rows}
    return rows, [t for t in expected_tickers if t not in answered]


def run_benchmark_probe(
    instruments: list[dict[str, str]], api_key: str, *, model: str, use_search: bool = False
) -> BenchmarkProbeResult:
    """Una sola chiamata a Gemini per tutti gli strumenti."""
    text = call_gemini_flash(build_benchmark_probe_prompt(instruments), api_key, model=model, use_search=use_search)
    rows, missing = parse_benchmark_probe_response(text, [r["ticker"] for r in instruments])
    return BenchmarkProbeResult(rows=rows, missing=missing, raw_text=text)
