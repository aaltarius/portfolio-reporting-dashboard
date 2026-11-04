"""core/ai_analysis.py — Integrazione Gemini Flash per analisi portafoglio."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from core.config import PATHS

_AI_CONFIG_PATH: Path = PATHS["data_dir"] / "config" / "ai_config.json"
_AI_REPORTS_DIR: Path = PATHS["data_dir"] / "ai_reports"

_GEMINI_MODEL = "gemini-3.5-flash"
AI_CALL_COUNT_KEY = "_ai_gemini_call_count"

GEMINI_MODELS = [
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-flash-latest",
    "gemini-2.0-flash-lite",
    "gemini-flash-lite-latest",
]
_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent?key={api_key}"
)

_DEFAULT_PROMPT = """\
Sei un consulente finanziario indipendente. Analizza il portafoglio seguente e fornisci:
1. Una valutazione sintetica della composizione attuale (diversificazione, concentrazione, rischio).
2. I punti di forza e le criticità principali.
3. Suggerimenti concreti di ribilanciamento, se opportuno, motivando le scelte.
4. Eventuali alert su strumenti con P/L molto negativo o peso eccessivo.

Rispondi in italiano, in modo chiaro e diretto. Evita disclaimer generici.\
"""

_STRUCTURED_OUTPUT_SUFFIX = """

Rispondi ESCLUSIVAMENTE con un oggetto JSON valido (nessun testo extra, nessun markdown), con questa struttura esatta:
{
  "analysis_text": "testo analisi in italiano",
  "instrument_scores": [
    {"ticker": "TICKER", "risk": 1, "quality": 1, "diversification": 1}
  ],
  "category_projections": [
    {"category": "NOME", "expected_return_min_pct": 0.0, "expected_return_max_pct": 0.0}
  ],
  "stress_scenarios": [
    {"name": "NOME SCENARIO", "portfolio_impact_pct": 0.0}
  ]
}
I valori numerici per instrument_scores sono interi 1-10 (10 = ottimo).
Le proiezioni e gli scenari sono stime qualitative basate sulla composizione, NON previsioni finanziarie reali.
"""

_DIFF_PROMPT_TEMPLATE = """\
Di seguito trovi due analisi AI dello stesso portafoglio in momenti diversi.

=== ANALISI A (più vecchia) ===
{text_a}

=== ANALISI B (più recente) ===
{text_b}

Confronta le due analisi e rispondi in italiano con:
1. Cosa è cambiato nel portafoglio (composizione, pesi, P/L) tra le due analisi.
2. Come è cambiato il giudizio dell'AI (migliorato, peggiorato, nuovi alert).
3. Un breve sommario esecutivo della situazione attuale rispetto al passato.
"""


def build_portfolio_ai_payload(
    data: dict[str, Any],
    da: pd.DataFrame,
    *,
    filter_tickers: list[str] | None = None,
    filter_categories: list[str] | None = None,
    include_sections: set[str] | None = None,
) -> dict[str, Any]:
    """Costruisce il payload strutturato da passare al modello AI."""
    _DEFAULT_SECTIONS = {"allocation", "rebalancing", "totals"}
    sections = include_sections if include_sections is not None else _DEFAULT_SECTIONS

    if da is None or da.empty:
        result: dict[str, Any] = {"instruments": []}
        if "totals" in sections:
            result["totale_controvalore_eur"] = 0.0
            result["totale_pl_eur"] = 0.0
        if "allocation" in sections:
            result["allocation_by_category"] = {}
        if "rebalancing" in sections:
            result["rebalancing_target"] = (data.get("settings") or {}).get("rebalancing_target", {})
            result["portfolio_objective"] = (data.get("settings") or {}).get("portfolio_objective", {})
        return result

    totale_cv_full = float(da["Controvalore"].sum()) if "Controvalore" in da.columns else 0.0

    da_filtered = da.copy()
    if filter_tickers is not None:
        da_filtered = da_filtered[da_filtered["Ticker"].isin(filter_tickers)]
    if filter_categories is not None:
        da_filtered = da_filtered[da_filtered["Tipo"].isin(filter_categories)]

    totale_cv_filtered = float(da_filtered["Controvalore"].sum()) if "Controvalore" in da_filtered.columns else 0.0

    instruments = []
    for _, row in da_filtered.iterrows():
        cv = float(row.get("Controvalore", 0) or 0)
        pl = float(row.get("P/L", 0) or 0)
        pl_pct = float(row.get("P/L %", 0) or 0)
        peso = round((cv / totale_cv_full * 100) if totale_cv_full > 0 else 0.0, 2)
        instruments.append({
            "ticker": str(row.get("Ticker", "")),
            "tipo": str(row.get("Tipo", "")),
            "controvalore_eur": round(cv, 2),
            "pl_eur": round(pl, 2),
            "pl_pct": round(pl_pct * 100, 2) if abs(pl_pct) <= 10 else round(pl_pct, 2),
            "peso_pct": peso,
        })

    result = {"instruments": instruments}

    if "totals" in sections:
        result["totale_controvalore_eur"] = round(totale_cv_filtered, 2)
        result["totale_pl_eur"] = round(float(da_filtered["P/L"].sum()), 2) if "P/L" in da_filtered.columns else 0.0

    if "allocation" in sections:
        allocation: dict[str, float] = {}
        if "Tipo" in da_filtered.columns and "Controvalore" in da_filtered.columns:
            for tipo, group in da_filtered.groupby("Tipo"):
                allocation[str(tipo)] = round(
                    float(group["Controvalore"].sum()) / totale_cv_full * 100, 2
                ) if totale_cv_full > 0 else 0.0
        result["allocation_by_category"] = allocation

    if "rebalancing" in sections:
        result["rebalancing_target"] = (data.get("settings") or {}).get("rebalancing_target", {})
        result["portfolio_objective"] = (data.get("settings") or {}).get("portfolio_objective", {})

    return result


def build_gemini_prompt(
    payload: dict[str, Any],
    custom_prompt: str | None = None,
    *,
    structured: bool = False,
) -> str:
    """Assembla il testo del prompt completo da inviare a Gemini."""
    portfolio_json = json.dumps(payload, ensure_ascii=False, indent=2)
    base = custom_prompt.strip() if custom_prompt and custom_prompt.strip() else _DEFAULT_PROMPT
    if structured:
        base = base + _STRUCTURED_OUTPUT_SUFFIX
    return f"{base}\n\nDati portafoglio (JSON):\n```json\n{portfolio_json}\n```"


def list_gemini_models(api_key: str) -> list[str]:
    """Restituisce i modelli disponibili per questa chiave che supportano generateContent."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    response = requests.get(url, timeout=15)
    if response.status_code != 200:
        raise RuntimeError(f"Errore {response.status_code}: {response.text[:300]}")
    models = response.json().get("models", [])
    return [
        m["name"].replace("models/", "")
        for m in models
        if "generateContent" in m.get("supportedGenerationMethods", [])
    ]


def _parse_gemini_error(response: requests.Response) -> str:
    """Estrae il messaggio di errore strutturato dalla risposta Gemini."""
    try:
        err = response.json().get("error", {})
        msg = err.get("message", "")
        status = err.get("status", "")
        if msg:
            return f"[{status}] {msg}" if status else msg
    except Exception:
        pass
    return response.text[:600]


def call_gemini_flash(prompt: str, api_key: str, model: str = _GEMINI_MODEL) -> str:
    """Chiama Gemini Flash e restituisce il testo della risposta."""
    url = _GEMINI_URL.format(model=model, api_key=api_key)
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    try:
        response = requests.post(url, json=body, timeout=90)
    except requests.exceptions.Timeout:
        raise RuntimeError("Timeout: Gemini non ha risposto entro 90s. Riprova tra qualche momento.")
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Errore di rete Gemini: {exc}") from exc
    if response.status_code != 200:
        raise RuntimeError(f"Gemini API error {response.status_code}: {_parse_gemini_error(response)}")
    data = response.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError("Risposta Gemini vuota: nessun candidate restituito.")
    try:
        return candidates[0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Risposta Gemini in formato inatteso: {exc}") from exc


def test_gemini_connection(api_key: str, model: str = _GEMINI_MODEL) -> str:
    """Invia un prompt minimale per verificare che la connessione funzioni."""
    url = _GEMINI_URL.format(model=model, api_key=api_key)
    body = {"contents": [{"role": "user", "parts": [{"text": "Rispondi solo con la parola: OK"}]}]}
    response = requests.post(url, json=body, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"Errore {response.status_code}: {_parse_gemini_error(response)}")
    data = response.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError("Nessun candidate restituito.")
    return candidates[0]["content"]["parts"][0]["text"]


def load_ai_config() -> dict:
    """Legge la configurazione AI da disco. Ritorna {} se il file non esiste."""
    try:
        return json.loads(_AI_CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def save_ai_config(api_key: str, default_model: str) -> None:
    """Salva API key e modello default in data/config/ai_config.json."""
    _AI_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _AI_CONFIG_PATH.write_text(
        json.dumps({"api_key": api_key, "default_model": default_model}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def save_ai_report(report: dict) -> Path:
    """Salva un report AI su disco. Ritorna il Path del file creato."""
    _AI_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = _AI_REPORTS_DIR / f"{timestamp}.json"
    data_to_save = {k: v for k, v in report.items() if k != "_filename"}
    data_to_save["saved_at"] = datetime.now().isoformat()
    path.write_text(json.dumps(data_to_save, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_ai_reports() -> list[dict]:
    """Carica tutti i report salvati, ordinati dal più recente al più vecchio."""
    if not _AI_REPORTS_DIR.exists():
        return []
    reports = []
    for f in sorted(_AI_REPORTS_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            data["_filename"] = f.name
            reports.append(data)
        except Exception:
            continue
    return reports


def delete_ai_report(filename: str) -> None:
    """Elimina un report salvato per nome file. Non lancia eccezioni se non esiste."""
    target = _AI_REPORTS_DIR / filename
    try:
        target.unlink(missing_ok=True)
    except Exception:
        pass


def _parse_structured_response(text: str) -> dict:
    """Parsa la risposta JSON di Gemini, gestendo blocchi markdown."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner_lines = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        text = "\n".join(inner_lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Risposta Gemini non è JSON valido: {exc}") from exc


def call_gemini_structured(prompt: str, api_key: str, model: str = _GEMINI_MODEL) -> dict:
    """Chiama Gemini chiedendo risposta in JSON strutturato. Ritorna il dict parsato."""
    text = call_gemini_flash(prompt, api_key, model=model)
    return _parse_structured_response(text)


def call_gemini_chat(messages: list[dict], api_key: str, model: str = _GEMINI_MODEL) -> str:
    """Chiama Gemini con una storia di messaggi (multi-turn). Ritorna il testo della risposta."""
    url = _GEMINI_URL.format(model=model, api_key=api_key)
    body = {"contents": messages}
    try:
        response = requests.post(url, json=body, timeout=90)
    except requests.exceptions.Timeout:
        raise RuntimeError("Timeout: Gemini non ha risposto entro 90s. Riprova tra qualche momento.")
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Errore di rete Gemini: {exc}") from exc
    if response.status_code != 200:
        raise RuntimeError(f"Gemini API error {response.status_code}: {_parse_gemini_error(response)}")
    data = response.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError("Risposta Gemini vuota: nessun candidate restituito.")
    try:
        return candidates[0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Risposta Gemini in formato inatteso: {exc}") from exc


def call_gemini_diff(text_a: str, text_b: str, api_key: str, model: str = _GEMINI_MODEL) -> str:
    """Chiama Gemini per confrontare due analisi testuali. Ritorna il testo del confronto."""
    prompt = _DIFF_PROMPT_TEMPLATE.format(text_a=text_a, text_b=text_b)
    return call_gemini_flash(prompt, api_key, model=model)
