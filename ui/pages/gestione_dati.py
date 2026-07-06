"""
ui/pages/gestione_dati.py — Tab Gestione Dati: sistema, diagnostica e manutenzione.
"""
import logging
import os
import re
import shutil
from pathlib import Path
from datetime import date, datetime
from types import SimpleNamespace

import pandas as pd
import streamlit as st

from core.asset_categories import ASSET_CATEGORY_REGISTRY, infer_category_code
from core.cache import invalidate_portfolio_cache
from streamlit.delta_generator import DeltaGenerator

from core.finance import _build_snapshot_from_data, _rebuild_cash_ledger_from_events
from core.services.integrity import build_integrity_checks
from core.settings_profiles import get_backup_settings, get_figure_cache_settings
from core.diagnostics import (
    build_cache_chart_rows,
    build_cache_health_rows,
    build_diagnostic_recommendations,
    build_render_event_rows,
    build_runtime_diagnostic_rows,
    build_session_state_rows,
    make_arrow_safe_dataframe,
)
from core.render_profiler import get_render_profile_events, render_profile_text
from core.logging_utils import get_default_log_file_path, get_log_file_stats, read_log_tail
from core.validators import validate_date, validate_quote_import, validate_selection
from persistence.storage import (
    BACKUP_DIR,
    BENCHMARK_CACHE_FILE,
    DATA_DIR,
    PRICES_DIR,
    DATA_FILE,
    META_FILE,
    QUOTES_LOG_FILE,
    SETTINGS_FILE,
    SNAPSHOTS_FILE,
    append_audit_event,
    create_backup_bundle,
    load_meta,
    load_data,
    load_quotes_log,
    load_snapshots,
    load_settings,
    save_data,
    save_quotes_log,
    save_settings,
    save_snapshots,
)
from ui.components import back_to_top, kpi_card, legend_block, render_styled_table, vertical_gap, render_section_title
from ui.formatting import fmt_dt_it, fmt_date_only_it, fmt_num_it
from ui.page_chrome import render_page_intro as render_page_intro_shared, render_section_line as render_section_line_shared
from ui.theme import get_theme_context
from ui.notifications import queue_info, queue_success, update_status
from ui.ux_helpers import confirm_danger, render_danger_hint

logger = logging.getLogger("portafoglio.ui.gestione_dati")

def _scan_cache_tree(base_dir: str) -> dict[str, object]:
    """Inventario fisico della cartella cache, indipendente dalla sola cache figure."""
    stats = {
        "exists": os.path.exists(base_dir),
        "total_files": 0,
        "total_size_bytes": 0,
        "by_suffix": {},
    }
    if not os.path.exists(base_dir):
        return stats
    for root, _dirs, files in os.walk(base_dir):
        for name in files:
            path = os.path.join(root, name)
            try:
                size = os.path.getsize(path)
            except Exception:
                size = 0
            suffix = "".join(Path(name).suffixes) or "(senza estensione)"
            stats["total_files"] += 1
            stats["total_size_bytes"] += size
            bucket = stats["by_suffix"].setdefault(suffix, {"files": 0, "size_bytes": 0})
            bucket["files"] += 1
            bucket["size_bytes"] += size
    return stats


def _mb_label(num_bytes: float | int) -> str:
    return f"{(float(num_bytes or 0) / (1024 * 1024)):.2f} MB"

def _record_cache_action(action: str) -> None:
    """Registra timestamp sintetico delle ultime azioni cache in settings.json."""
    try:
        current_settings = dict(load_settings() or {})
        actions = dict(current_settings.get("cache_action_log", {}) or {})
        actions[action] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        current_settings["cache_action_log"] = actions
        save_settings(current_settings)
    except Exception as exc:
        logger.warning("Cache action log non aggiornato: %s", exc)


def _get_cache_action_log(settings: dict) -> dict:
    try:
        return dict((settings or {}).get("cache_action_log", {}) or {})
    except Exception:
        return {}

PHP_REMOTE_TEMPLATE = '<?php\n/**\n * aggiorna_remoto.php — Aggiornamento quotazioni da remoto\n *\n * ISTRUZIONI:\n * 1. Carica questo file su una cartella con nome segreto del tuo sito (es. /privato/xk7q2/)\n * 2. Aggiorna la sezione CONFIGURAZIONE con i tuoi strumenti (usa il bottone\n *    "Aggiornamento quotazioni da remoto" nella pagina Impostazioni della dashboard)\n * 3. Visita la pagina da qualsiasi browser per scaricare il file JSON aggiornato\n * 4. Al rientro, esegui: python importa_quotazioni.py quotazioni_YYYY-MM-DD.json\n *\n * REQUISITI HOSTING: PHP 7.4+ con curl abilitato (standard su qualsiasi hosting condiviso)\n */\n\n// ============================================================\n// CONFIGURAZIONE — Aggiorna con i tuoi strumenti\n// (usa il bottone "Esporta config PHP" in Impostazioni)\n// ============================================================\n$strumenti = [\n    // ETF e fondi: usa il ticker Yahoo Finance\n    // ["ticker" => "VWCE.DE",  "isin" => "IE00BK5BQT80", "tipo" => "ETF",  "nome" => "Vanguard FTSE All-World"],\n    // BTP: usa sempre il prefisso BTP- e l\'ISIN completo\n    // ["ticker" => "BTP-8128", "isin" => "IT0005518128", "tipo" => "BTP",  "nome" => "BTP 2052"],\n];\n\n$strumenti = [\n    ["ticker" => "BTP-0826", "isin" => "IT0005454241", "tipo" => "BTP", "nome" => "BTP Tf 0% Ago 2026"],\n    ["ticker" => "XMME.MI", "isin" => "IE00BTJRMP35", "tipo" => "ETF", "nome" => "Xtrackers MSCI Emerging Markets UCITS ETF 1C"],\n    ["ticker" => "SWDA.MI", "isin" => "IE00B4L5Y983", "tipo" => "ETF", "nome" => "iShares Core MSCI World UCITS ETF USD (Acc)"],\n    ["ticker" => "ETFMIB.MI", "isin" => "FR0010010827", "tipo" => "ETF", "nome" => "Amundi FTSE MIB UCITS ETF Dist"],\n    ["ticker" => "XEON.MI", "isin" => "LU0290358497", "tipo" => "ETF", "nome" => "Xtrackers EUR Overnight Rate Swap UCITS ETF 1C"],\n    ["ticker" => "FAM-FLEX", "isin" => "IE00BDRNRJ06", "tipo" => "PAC", "nome" => "FAM Series Flexible Eq. Strategy A EUR Acc"],\n    ["ticker" => "FAM-PU6", "isin" => "IE000KTYLDC4", "tipo" => "PAC", "nome" => "Fineco AM Passive Underlyings 6 A EUR Acc"],\n    ["ticker" => "FAM-PU8", "isin" => "IE000DWG3DP6", "tipo" => "PAC", "nome" => "Fineco AM Passive Underlyings 8 A EUR Acc"],\n    ["ticker" => "FAM-EMD", "isin" => "IE00BDRMFG04", "tipo" => "PAC", "nome" => "FAM Series Emerging Markets Debt AH EUR Acc"],\n    ["ticker" => "BTP-15MZ28", "isin" => "IT0005433690", "tipo" => "BTP", "nome" => "Btp Tf 0,25% Mz28"],\n    ["ticker" => "BTP-1DC28", "isin" => "IT0005340929", "tipo" => "BTP", "nome" => "Btp Tf 2,80% Dc28"],\n    ["ticker" => "XDBC.MI", "isin" => "LU0292106167", "tipo" => "ETF", "nome" => "Xtrack Bloom Ex Agri Livest Sw Ucits Etf"],\n    ["ticker" => "ENRG.MI", "isin" => "LU1834988278", "tipo" => "ETF", "nome" => "Amundi Stoxx Europe 600 Energy Screened Ucits Etf Acc"],\n    ["ticker" => "XDWH.MI", "isin" => "IE00BM67HK77", "tipo" => "ETF", "nome" => "Xtrackers Msci World Heal Care Ucits Etf"],\n    ["ticker" => "XDRE.MI", "isin" => "IE00BN2BCY94", "tipo" => "ETF", "nome" => "Xtrackers Developed Green Real Estate Esg Ucits Etf"],\n    ["ticker" => "XAIX.MI", "isin" => "IE00BGV5VN51", "tipo" => "ETF", "nome" => "Xtrackers Art Intel &amp; Big Data Ucits Etf"],\n];\n\n// ============================================================\n// FINE CONFIGURAZIONE\n// ============================================================\n\nif (empty($strumenti)) {\n    header("Content-Type: text/html; charset=utf-8");\n    echo "<h2>aggiorna_remoto.php</h2>";\n    echo "<p><strong>Configurazione mancante.</strong> Apri la dashboard, vai in Impostazioni &rarr; ";\n    echo "\\"Aggiornamento quotazioni da remoto (PHP)\\" e copia il blocco generato in questo file.</p>";\n    exit;\n}\n\n$data_oggi = date("Y-m-d");\n$ora_gen   = date("Y-m-d H:i:s");\n$prezzi    = [];\n$log       = [];\n\n/**\n * Scarica il prezzo da Yahoo Finance (query1 + query2 come fallback).\n */\nfunction get_yahoo_price(string $ticker): ?float {\n    // Prova query1 e query2 come fallback\n    foreach (["query1", "query2"] as $host) {\n        $url = "https://{$host}.finance.yahoo.com/v8/finance/chart/"\n             . rawurlencode($ticker)\n             . "?interval=1d&range=5d";\n        $ch = curl_init($url);\n        curl_setopt_array($ch, [\n            CURLOPT_RETURNTRANSFER => true,\n            CURLOPT_TIMEOUT        => 15,\n            CURLOPT_HTTPHEADER     => [\n                "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",\n                "Accept: application/json,text/plain,*/*",\n                "Accept-Language: it-IT,it;q=0.9,en;q=0.8",\n                "Referer: https://finance.yahoo.com/",\n            ],\n            CURLOPT_SSL_VERIFYPEER => false,\n            CURLOPT_FOLLOWLOCATION => true,\n        ]);\n        $resp     = curl_exec($ch);\n        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);\n        curl_close($ch);\n        if (!$resp || $httpCode >= 400) continue;\n        $js = json_decode($resp, true);\n        if (!isset($js["chart"]["result"][0])) continue;\n        $closes = $js["chart"]["result"][0]["indicators"]["quote"][0]["close"] ?? [];\n        $closes = array_values(array_filter($closes, function($v) { return $v !== null; }));\n        if (!empty($closes)) return (float) end($closes);\n    }\n    return null;\n}\n\n/**\n * Cerca il ticker Yahoo Finance tramite ISIN (utile per fondi senza ticker standard).\n * Replica get_yahoo_ticker() di core/market_data.py\n */\nfunction get_yahoo_ticker_by_isin(string $isin): ?string {\n    $url = "https://query2.finance.yahoo.com/v1/finance/search?q=" . rawurlencode($isin) . "&quotesCount=5&newsCount=0";\n    $ch = curl_init($url);\n    curl_setopt_array($ch, [\n        CURLOPT_RETURNTRANSFER => true,\n        CURLOPT_TIMEOUT        => 10,\n        CURLOPT_HTTPHEADER     => ["User-Agent: Mozilla/5.0"],\n        CURLOPT_SSL_VERIFYPEER => false,\n    ]);\n    $resp = curl_exec($ch);\n    curl_close($ch);\n    if (!$resp) return null;\n    $js     = json_decode($resp, true);\n    $quotes = $js["quotes"] ?? [];\n    // 1. Preferisce ticker .MI (Borsa Italiana)\n    foreach ($quotes as $q) {\n        $sym = $q["symbol"] ?? "";\n        if (substr(strtoupper($sym), -3) === ".MI") return $sym;\n    }\n    // 2. Qualsiasi ticker con punto ma non 0P (fondi Yahoo)\n    foreach ($quotes as $q) {\n        $sym = $q["symbol"] ?? "";\n        if (strpos($sym, "0P") !== 0 && strpos($sym, ".") !== false) return $sym;\n    }\n    // 3. Qualsiasi ticker trovato (inclusi fondi 0P...)\n    if (!empty($quotes)) return $quotes[0]["symbol"] ?? null;\n    return null;\n}\n\n/**\n * Fallback per ticker .MI (Borsa Italiana): scraping pagina ETF/fondo.\n */\nfunction get_borsaitaliana_etf_price(string $isin): ?float {\n    $urls = [\n        "https://www.borsaitaliana.it/borsa/etf/dati-completi.html?isin=" . urlencode($isin) . "&lang=it",\n        "https://www.borsaitaliana.it/borsa/fondi/etf/scheda/" . urlencode($isin) . ".html?lang=it",\n    ];\n    foreach ($urls as $url) {\n        $ch = curl_init($url);\n        curl_setopt_array($ch, [\n            CURLOPT_RETURNTRANSFER => true,\n            CURLOPT_TIMEOUT        => 15,\n            CURLOPT_HTTPHEADER     => [\n                "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)",\n                "Accept-Language: it-IT,it;q=0.9",\n            ],\n            CURLOPT_SSL_VERIFYPEER => false,\n            CURLOPT_FOLLOWLOCATION => true,\n        ]);\n        $html = curl_exec($ch);\n        curl_close($ch);\n        if (!$html) continue;\n        foreach (["Prezzo Ultimo", "Ultimo Prezzo", "Prezzo di Riferimento", "Nav"] as $term) {\n            $pos = stripos($html, $term);\n            if ($pos === false) continue;\n            $chunk = strip_tags(substr($html, $pos, 400));\n            if (preg_match(\'/\\b(\\d{1,3}(?:[.,]\\d{3})*[.,]\\d{2,4})\\b/\', $chunk, $m)) {\n                // Normalizza: rimuove separatore migliaia, converte virgola decimale\n                $raw = $m[1];\n                // Se ha punto come separatore migliaia (es. 1.234,56) → rimuovi punto\n                if (preg_match(\'/\\d\\.\\d{3},/\', $raw)) {\n                    $raw = str_replace(\'.\', \'\', $raw);\n                }\n                $v = (float) str_replace(\',\', \'.\', $raw);\n                if ($v > 0.01 && $v < 100000) return $v;\n            }\n        }\n    }\n    return null;\n}\n\n/**\n * Scarica il prezzo di un BTP da Borsa Italiana via curl + regex.\n */\nfunction get_btp_price(string $isin): ?float {\n    $urls = [\n        "https://www.borsaitaliana.it/borsa/obbligazioni/mot/btp/dati-completi.html?isin=" . urlencode($isin) . "&lang=it",\n        "https://www.borsaitaliana.it/borsa/obbligazioni/mot/btp/scheda/" . urlencode($isin) . "-MOTX.html?lang=it",\n    ];\n    foreach ($urls as $url) {\n        $ch = curl_init($url);\n        curl_setopt_array($ch, [\n            CURLOPT_RETURNTRANSFER => true,\n            CURLOPT_TIMEOUT        => 15,\n            CURLOPT_HTTPHEADER     => [\n                "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)",\n                "Accept-Language: it-IT,it;q=0.9",\n            ],\n            CURLOPT_SSL_VERIFYPEER => false,\n            CURLOPT_FOLLOWLOCATION => true,\n        ]);\n        $html = curl_exec($ch);\n        curl_close($ch);\n        if (!$html) continue;\n        foreach (["Prezzo Ultimo Contratto", "Prezzo di Riferimento", "prezzo_rif"] as $term) {\n            $pos = stripos($html, $term);\n            if ($pos === false) continue;\n            $chunk = substr($html, $pos, 500);\n            if (preg_match_all(\'/\\b(\\d{2,3}[,\\.]\\d{1,4})\\b/\', strip_tags($chunk), $m)) {\n                foreach ($m[1] as $raw) {\n                    $v = (float) str_replace(\',\', \'.\', str_replace(\'.\', \'\', $raw));\n                    if ($v > 30 && $v < 200) return $v;\n                }\n            }\n        }\n    }\n    return null;\n}\n\n// Raccolta prezzi\nforeach ($strumenti as $s) {\n    $tk   = $s["ticker"];\n    $isin = $s["isin"];\n    $tipo = strtoupper($s["tipo"]);\n    $nome = $s["nome"];\n\n    if (strpos($tipo, "BTP") !== false || strpos($tk, "BTP-") === 0) {\n        // ── BTP: scraping Borsa Italiana ──────────────────────────────────\n        $prezzo = get_btp_price($isin);\n        $fonte  = "Borsa Italiana";\n    } else {\n        $tkUp   = strtoupper($tk);\n        $prezzo = null;\n        $fonte  = "Non trovato";\n\n        // ── Passo 1: Yahoo Finance con il ticker configurato ──────────────\n        if ($prezzo === null) {\n            $prezzo = get_yahoo_price($tk);\n            if ($prezzo !== null) $fonte = "Yahoo Finance [{$tk}]";\n        }\n\n        // ── Passo 2: cerca ticker reale via ISIN (fondi FAM, ecc.) ────────\n        if ($prezzo === null) {\n            $autoTk = get_yahoo_ticker_by_isin($isin);\n            if ($autoTk !== null && strtoupper($autoTk) !== $tkUp) {\n                $prezzo = get_yahoo_price($autoTk);\n                if ($prezzo !== null) $fonte = "Yahoo Finance [{$autoTk}]";\n            }\n        }\n\n        // ── Passo 3: Borsa Italiana per ticker .MI o tipo PAC ─────────────\n        if ($prezzo === null && (substr($tkUp, -3) === ".MI" || strtoupper($tipo) === "PAC")) {\n            $prezzo = get_borsaitaliana_etf_price($isin);\n            if ($prezzo !== null) $fonte = "Borsa Italiana (fallback)";\n        }\n    }\n\n    if ($prezzo !== null) {\n        $prezzi[$tk] = $prezzo;\n        $log[] = ["ticker" => $tk, "nome" => $nome, "prezzo" => $prezzo, "fonte" => $fonte, "esito" => "OK"];\n    } else {\n        $log[] = ["ticker" => $tk, "nome" => $nome, "prezzo" => null, "fonte" => $fonte, "esito" => "ERRORE"];\n    }\n    usleep(200000); // 0.2 sec tra le richieste\n}\n\n$output = [\n    "data"     => $data_oggi,\n    "generato" => $ora_gen,\n    "fonte"    => "aggiorna_remoto.php",\n    "prezzi"   => $prezzi,\n    "log"      => $log,\n];\n\n$json_out = json_encode($output, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);\n$filename = "quotazioni_" . $data_oggi . ".json";\n\nheader("Content-Type: application/json; charset=utf-8");\nheader("Content-Disposition: attachment; filename=\\"$filename\\"");\nheader("Content-Length: " . strlen($json_out));\nheader("Cache-Control: no-cache, no-store, must-revalidate");\necho $json_out;\nexit;\n?>\n'


def _php_escape(value: object) -> str:
    """Escape minimo per valori inseriti nel template PHP."""
    text = str(value or "")
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _build_php_tools_block(data: dict) -> str:
    """Genera il blocco $strumenti coerente con gli strumenti attesi dall'app."""
    rows = []
    for item in data.get("strumenti", []) or []:
        ticker = _php_escape(item.get("ticker", ""))
        isin = _php_escape(item.get("isin", ""))
        tipo = _php_escape(item.get("tipo", ""))
        nome = _php_escape(item.get("nome", ""))
        if not ticker:
            continue
        rows.append(
            f'    ["ticker" => "{ticker}", "isin" => "{isin}", "tipo" => "{tipo}", "nome" => "{nome}"],'
        )
    if not rows:
        return "$strumenti = [\n];"
    return "$strumenti = [\n" + "\n".join(rows) + "\n];"


def _sync_remote_php_template(template: str, data: dict) -> str:
    """Aggiorna il PHP esistente sostituendo tutti i blocchi $strumenti con quello corrente.

    Lo script storico conteneva anche un blocco $strumenti di esempio/commento e un blocco reale:
    per evitare doppioni o strumenti vecchi, qui si sostituisce l'intera area compresa tra
    il primo $strumenti = [ e la fine dell'ultimo blocco $strumenti prima delle funzioni operative.
    """
    tools_block = _build_php_tools_block(data)
    text = template or ""

    first = text.find("$strumenti = [")
    if first == -1:
        return "<?php\n" + tools_block + "\n" + text

    # Trova tutti i blocchi $strumenti = [ ... ];
    matches = list(re.finditer(r"\$strumenti\s*=\s*\[(.*?)\];", text, flags=re.DOTALL))
    if not matches:
        return text[:first] + tools_block + "\n" + text[first:]

    last = matches[-1]
    # Mantiene intestazione/commenti prima del primo blocco, poi inserisce un solo blocco corrente.
    return text[:matches[0].start()] + tools_block + text[last.end():]


def _build_remote_quotes_php(data: dict) -> str:
    """Restituisce aggiorna_remoto.php esistente, ma con strumenti rigenerati dai dati correnti."""
    return _sync_remote_php_template(PHP_REMOTE_TEMPLATE, data)

def _parse_runtime_date(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    for candidate in (text[:19], text[:10]):
        try:
            if len(candidate) == 10:
                return datetime.strptime(candidate, "%Y-%m-%d")
            return datetime.strptime(candidate, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return None


def _build_observability_checks(
    *,
    data: dict,
    settings: dict,
    log_stats: dict[str, object],
    snapshots_state: dict | None = None,
) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    quote_timestamp = _parse_runtime_date(data.get("last_quotes_update"))
    quote_age_days = (date.today() - quote_timestamp.date()).days if quote_timestamp else None
    snapshots_count = len(((snapshots_state or {}).get("snapshots", []) if isinstance(snapshots_state, dict) else []) or [])
    storico_count = len(data.get("storico_prezzi", {}) or {})
    instruments_count = len(data.get("strumenti", []) or [])
    missing_prices = sum(1 for item in (data.get("strumenti", []) or []) if item.get("prezzo") in (None, ""))

    # CONFIGURAZIONE checks
    checks.append({
        "Controllo": "Configurazione applicativa (settings.json)",
        "Stato": "ok" if os.path.exists(SETTINGS_FILE) else "warning",
        "Sintesi": "File configurazione presente." if os.path.exists(SETTINGS_FILE) else "File configurazione assente!",
    })
    checks.append({
        "Controllo": "Metadati (meta.json)",
        "Stato": "ok" if os.path.exists(META_FILE) else "warning",
        "Sintesi": "File metadati presente." if os.path.exists(META_FILE) else "File metadati assente!",
    })

    # DATI CRITICI checks
    checks.append({
        "Controllo": "Dati principali (data.json)",
        "Stato": "ok" if os.path.exists(DATA_FILE) else "error",
        "Sintesi": f"Presente ({round(os.path.getsize(DATA_FILE)/1024, 1)} KB)" if os.path.exists(DATA_FILE) else "Assente!",
    })
    checks.append({
        "Controllo": "Snapshot storici (snapshots.json)",
        "Stato": "ok" if snapshots_count > 0 else "warning",
        "Sintesi": f"{snapshots_count} snapshot disponibili per i confronti.",
    })
    checks.append({
        "Controllo": "Log quotazioni (quotes_log.json)",
        "Stato": "ok" if os.path.exists(QUOTES_LOG_FILE) else "warning",
        "Sintesi": "Log presente." if os.path.exists(QUOTES_LOG_FILE) else "Log quotazioni assente.",
    })
    checks.append({
        "Controllo": "Cache benchmark (benchmark_cache.json)",
        "Stato": "ok" if os.path.exists(BENCHMARK_CACHE_FILE) else "warning",
        "Sintesi": "Cache presente." if os.path.exists(BENCHMARK_CACHE_FILE) else "Cache benchmark assente.",
    })

    # FRESCHEZZA DATI
    checks.append({
        "Controllo": "Freschezza quotazioni",
        "Stato": "warning" if quote_age_days is None or quote_age_days > 3 else "ok",
        "Sintesi": (
            "Nessuna data di aggiornamento rilevata."
            if quote_age_days is None
            else f"Ultimo aggiornamento di {quote_age_days} giorni fa."
        ),
    })
    checks.append({
        "Controllo": "Copertura prezzi correnti",
        "Stato": "warning" if missing_prices > 0 else "ok",
        "Sintesi": f"{missing_prices} strumenti senza prezzo corrente su {instruments_count}.",
    })
    checks.append({
        "Controllo": "Storico prezzi",
        "Stato": "warning" if storico_count == 0 else "ok",
        "Sintesi": f"{storico_count} date archiviate nello storico prezzi.",
    })

    # BACKUP E POLICY
    checks.append({
        "Controllo": "Policy backup",
        "Stato": "warning" if not bool(settings.get("backup", {}).get("enabled", True)) else "ok",
        "Sintesi": "Backup automatici attivi." if bool(settings.get("backup", {}).get("enabled", True)) else "Backup disattivati nelle regole di Gestione Dati.",
    })
    checks.append({
        "Controllo": "File log applicativo",
        "Stato": "warning" if not bool(log_stats.get("exists")) else "ok",
        "Sintesi": (
            "File log assente."
            if not bool(log_stats.get("exists"))
            else f"Dimensione attuale: {round((int(log_stats.get('size_bytes') or 0) / 1024), 1)} KB."
        ),
    })
    return checks

def _render_diagnostic_table(rows: object, *, height: int | str = "content") -> None:
    """Renderizza una tabella diagnostica evitando warning/errori Arrow."""
    render_styled_table(make_arrow_safe_dataframe(rows).style, height=height)



def _category_ticker_inventory(raw_data: dict, category_code: str) -> tuple[list[str], pd.DataFrame]:
    category_code = str(category_code or "").upper()
    strumenti = list(raw_data.get("strumenti", []) or [])
    tickers = [
        str(item.get("ticker") or "")
        for item in strumenti
        if str(item.get("ticker") or "") and infer_category_code(item.get("tipo", "")) == category_code
    ]
    tickers = sorted(dict.fromkeys(tickers))

    def _matches_record(record: object) -> bool:
        if not isinstance(record, dict):
            return False
        ticker = str(record.get("ticker") or "").strip()
        if ticker:
            return ticker in tickers
        blob = " | ".join(
            str(record.get(key) or "")
            for key in ("note", "descrizione", "strumento", "nome")
        ).upper()
        return any(tk.upper() in blob for tk in tickers)

    inventory_rows: list[dict[str, object]] = []
    inventory_rows.append({"Sezione": "strumenti", "Occorrenze": len(tickers), "Dettaglio": ", ".join(tickers) if tickers else "—"})

    instrument_master = raw_data.get("instrument_master", {})
    instrument_master_count = sum(1 for tk in tickers if isinstance(instrument_master, dict) and tk in instrument_master)
    inventory_rows.append({"Sezione": "instrument_master", "Occorrenze": instrument_master_count, "Dettaglio": f"{instrument_master_count} record"})

    for key in ("operazioni", "registro_eventi", "proventi", "registro_liquidita"):
        section = list(raw_data.get(key, []) or [])
        count = sum(1 for item in section if _matches_record(item))
        inventory_rows.append({"Sezione": key, "Occorrenze": count, "Dettaglio": f"{count} record"})

    storico = raw_data.get("storico_prezzi", {}) or {}
    date_hits = 0
    value_hits = 0
    for values in storico.values():
        if not isinstance(values, dict):
            continue
        local_hits = sum(1 for tk in tickers if tk in values)
        if local_hits:
            date_hits += 1
            value_hits += local_hits
    inventory_rows.append({"Sezione": "storico_prezzi", "Occorrenze": value_hits, "Dettaglio": f"{value_hits} letture su {date_hits} date"})

    quotes_log = load_quotes_log()
    quote_log_items = list((quotes_log or {}).get("items", []) or [])
    quote_log_count = sum(1 for item in quote_log_items if _matches_record(item))
    inventory_rows.append({"Sezione": "quotes_log", "Occorrenze": quote_log_count, "Dettaglio": f"{quote_log_count} letture log"})

    return tickers, pd.DataFrame(inventory_rows)


def _delete_category_records(raw_data: dict, tickers: list[str], sections: list[str]) -> dict[str, int]:
    selected_tickers = {str(tk or "").strip() for tk in tickers if str(tk or "").strip()}
    selected_sections = {str(section or "").strip() for section in sections if str(section or "").strip()}
    removed: dict[str, int] = {}

    def _matches_record(record: object) -> bool:
        if not isinstance(record, dict):
            return False
        ticker = str(record.get("ticker") or "").strip()
        if ticker:
            return ticker in selected_tickers
        blob = " | ".join(
            str(record.get(key) or "")
            for key in ("note", "descrizione", "strumento", "nome")
        ).upper()
        return any(tk.upper() in blob for tk in selected_tickers)

    if "strumenti" in selected_sections:
        before = len(raw_data.get("strumenti", []) or [])
        raw_data["strumenti"] = [item for item in list(raw_data.get("strumenti", []) or []) if str(item.get("ticker") or "") not in selected_tickers]
        removed["strumenti"] = before - len(raw_data["strumenti"])

    if "instrument_master" in selected_sections and isinstance(raw_data.get("instrument_master"), dict):
        master = dict(raw_data.get("instrument_master", {}) or {})
        before = len(master)
        for ticker in selected_tickers:
            master.pop(ticker, None)
        raw_data["instrument_master"] = master
        removed["instrument_master"] = before - len(master)

    for key in ("operazioni", "registro_eventi", "proventi", "registro_liquidita"):
        if key not in selected_sections:
            continue
        before = len(raw_data.get(key, []) or [])
        raw_data[key] = [item for item in list(raw_data.get(key, []) or []) if not _matches_record(item)]
        removed[key] = before - len(raw_data[key])

    if "storico_prezzi" in selected_sections:
        storico = raw_data.get("storico_prezzi", {}) or {}
        removed_values = 0
        cleaned_storico = {}
        for raw_date, values in storico.items():
            if not isinstance(values, dict):
                continue
            current = dict(values)
            for ticker in selected_tickers:
                if ticker in current:
                    removed_values += 1
                    current.pop(ticker, None)
            if current:
                cleaned_storico[raw_date] = current
        raw_data["storico_prezzi"] = cleaned_storico
        removed["storico_prezzi"] = removed_values

    if any(key in selected_sections for key in ("registro_eventi", "registro_liquidita")):
        raw_data["registro_liquidita"] = _rebuild_cash_ledger_from_events(raw_data.get("registro_eventi", []) or [])

    raw_data["cache_posizioni"] = {}
    raw_data["cache_storico_portafoglio"] = {}
    return removed

def _page_icon_svg(kind: str = "default") -> str:
    icons = {
        "summary": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-summary" x1="3" y1="3" x2="21" y2="21"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="3.5" y="3" width="17" height="18" rx="4" fill="url(#g-summary)" opacity=".16"/>
          <path d="M8 8.2h8M8 12h8M8 15.8h5" fill="none" stroke="url(#g-summary)" stroke-width="1.9" stroke-linecap="round"/>
          <circle cx="17" cy="16" r="2.2" fill="url(#g-summary)"/>
        </svg>
        """,
        "confronto": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-confronto" x1="4" y1="20" x2="20" y2="4"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="3" y="4" width="18" height="16" rx="4" fill="url(#g-confronto)" opacity=".14"/>
          <path d="M7 16.5V11M12 16.5V7.5M17 16.5v-4" fill="none" stroke="url(#g-confronto)" stroke-width="2.1" stroke-linecap="round"/>
          <path d="M6.5 17.5h11" stroke="url(#g-confronto)" stroke-width="1.8" stroke-linecap="round"/>
        </svg>
        """,
        "pianificazione": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-plan" x1="4" y1="4" x2="20" y2="20"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="3.5" y="5" width="17" height="15.5" rx="4" fill="url(#g-plan)" opacity=".15"/>
          <path d="M8 3.5v3M16 3.5v3M6.5 9h11" stroke="url(#g-plan)" stroke-width="1.8" stroke-linecap="round"/>
          <path d="M8 13h3l1.5 2.2L16.5 11" fill="none" stroke="url(#g-plan)" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        """,
        "gestione": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-data" x1="4" y1="4" x2="20" y2="20"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="4" y="3.5" width="16" height="17" rx="4" fill="url(#g-data)" opacity=".15"/>
          <path d="M8 8h8M8 12h8M8 16h5" stroke="url(#g-data)" stroke-width="1.8" stroke-linecap="round"/>
          <circle cx="17" cy="16" r="2.2" fill="url(#g-data)"/>
        </svg>
        """,
        "impostazioni": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-settings" x1="4" y1="4" x2="20" y2="20"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <circle cx="12" cy="12" r="8.5" fill="url(#g-settings)" opacity=".15"/>
          <path d="M12 8.1v-2M12 18v-2M8.1 12h-2M18 12h-2M9.25 9.25 7.8 7.8M16.2 16.2l-1.45-1.45M14.75 9.25 16.2 7.8M7.8 16.2l1.45-1.45" stroke="url(#g-settings)" stroke-width="1.7" stroke-linecap="round"/>
          <circle cx="12" cy="12" r="3.1" fill="none" stroke="url(#g-settings)" stroke-width="2"/>
        </svg>
        """,
        "default": """
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs><linearGradient id="g-default" x1="4" y1="4" x2="20" y2="20"><stop stop-color="var(--page-accent)"/><stop offset="1" stop-color="var(--page-accent-2)"/></linearGradient></defs>
          <rect x="4" y="4" width="16" height="16" rx="4" fill="url(#g-default)" opacity=".15"/>
          <path d="M8 9h8M8 13h8M8 17h5" stroke="url(#g-default)" stroke-width="1.8" stroke-linecap="round"/>
        </svg>
        """,
    }
    return icons.get(kind, icons["default"])


def _render_page_intro(title: str, comment: str, icon: str = "default", theme=None) -> None:
    return render_page_intro_shared(title, comment, icon, theme)
    theme = theme or get_theme_context()
    accent = getattr(theme, "color_blue", "#3b82f6")
    accent_2 = getattr(theme, "color_green", "#22c55e")
    font = getattr(theme, "font_color", "#111827")
    panel_bg = getattr(theme, "panel_bg", "#f8fafc")
    border = getattr(theme, "border_color", "rgba(148,163,184,.32)")
    muted = getattr(theme, "muted_color", "#64748b")
    st.markdown(
        f"""
        <style>
        .page-intro {{
            --page-accent:{accent};
            --page-accent-2:{accent_2};
            margin:0;
            padding:0;
        }}
        .page-intro-title {{
            display:flex;
            align-items:center;
            gap:10px;
            margin:0 0 8px 0;
            color:{font};
            font-size:1.28rem;
            font-weight:850;
            line-height:1.18;
            letter-spacing:-0.01em;
        }}
        .page-intro-icon {{
            width:27px;
            height:27px;
            display:inline-flex;
            align-items:center;
            justify-content:center;
            flex:0 0 27px;
        }}
        .page-intro-icon svg {{
            width:27px;
            height:27px;
            display:block;
        }}
        .page-intro-comment {{
            margin:0;
            padding:10px 14px;
            color:{font};
            background:{panel_bg};
            border:1px solid {border};
            border-left:4px solid {accent};
            border-radius:14px;
            font-size:0.92rem;
            line-height:1.42;
            font-weight:500;
            box-shadow:0 8px 18px rgba(15,23,42,.04);
        }}
        .section-line {{
            margin:14px 0 14px 0;
            border:0;
            border-top:1px solid rgba(148,163,184,.30);
        }}
        .page-intro + .section-line {{
            margin-top:28px !important;
            margin-bottom:14px !important;
        }}
        </style>
        <div class="page-intro">
          <div class="page-intro-title">
            <span class="page-intro-icon">{_page_icon_svg(icon)}</span>
            <span>{title}</span>
          </div>
          <div class="page-intro-comment">{comment}</div>
        </div>
        <hr class="section-line" />
        """,
        unsafe_allow_html=True,
    )


def _section_line() -> None:
    return render_section_line_shared()


def _render_arricchimento(data: dict, ctx) -> None:
    from persistence.storage import load_data

    # Legge sempre dal disco (ctx.data è una copia filtrata/cached non adatta al salvataggio)
    raw_data = load_data()
    strumenti = [s for s in (raw_data.get("strumenti") or []) if str(s.get("stato", "aperto")) == "aperto"]

    from core.instrument_enrichment import _categoria

    _CORE: dict[str, list[str]] = {
        "btp":   ["ytm_netto", "ytm_lordo", "duration_modificata", "scadenza",
                  "cedola_annuale", "cedola_frequenza", "tipo_cedola", "rating_emittente"],
        "etf":   ["rendimento_1a", "rendimento_3a", "ter", "benchmark",
                  "categoria_etf", "distribuzione", "data_lancio", "rating_morningstar"],
        "etc":   ["rendimento_1a", "rendimento_3a", "ter", "benchmark",
                  "categoria_etf", "distribuzione", "data_lancio"],
        "fondo": ["rendimento_ytd", "rendimento_1a", "rendimento_3a", "ter",
                  "categoria_fam", "rating_morningstar", "data_lancio", "patrimonio"],
    }

    def _stato(s: dict) -> str:
        if s.get("enrichment_error"):
            return "⚠ errore"
        if s.get("enriched_at"):
            return "✓ arricchito"
        return "— mai"

    def _completezza(s: dict) -> int:
        if not s.get("enriched_at"):
            return 0
        fields = _CORE.get(_categoria(s.get("tipo", "")), [])
        if not fields:
            return 0
        filled = sum(1 for f in fields if s.get(f) not in (None, "", "—"))
        return round(filled / len(fields) * 100)

    _tickers_for_count = {s.get("ticker", "") for s in strumenti}
    date_count_by_ticker: dict = dict.fromkeys(_tickers_for_count, 0)
    for _day_prices in (raw_data.get("storico_prezzi") or {}).values():
        if isinstance(_day_prices, dict):
            for _tk in _day_prices:
                if _tk in date_count_by_ticker:
                    date_count_by_ticker[_tk] += 1

    rows = [
        {
            "Ticker":       s.get("ticker", ""),
            "Nome":         s.get("nome", ""),
            "Tipo":         s.get("tipo", ""),
            "Stato":        _stato(s),
            "Aggiornato":   fmt_date_only_it((s.get("enriched_at") or "")[:10]) if s.get("enriched_at") else "—",
            "%":            _completezza(s),
            "Date storico": date_count_by_ticker.get(s.get("ticker", ""), 0),
        }
        for s in strumenti
    ]

    if rows:
        row_h = 35
        table_h = 38 + len(rows) * row_h
        st.dataframe(
            rows,
            width="stretch",
            hide_index=True,
            height=table_h,
            column_config={
                "Ticker":       st.column_config.TextColumn("Ticker", width="small"),
                "Nome":         st.column_config.TextColumn("Nome"),
                "Tipo":         st.column_config.TextColumn("Tipo"),
                "Stato":        st.column_config.TextColumn("Stato", width="small"),
                "Aggiornato":   st.column_config.TextColumn("Aggiornato", width="small"),
                "%":            st.column_config.ProgressColumn("Completezza", min_value=0, max_value=100, width="small", format="%d%%"),
                "Date storico": st.column_config.NumberColumn("Date storico", width="small"),
            },
        )

    st.caption(
        "Arricchimento automatico, import da PDF Fineco e modifica manuale dei campi si fanno tutti da "
        "Strumenti → tab \"Arricchimento\" (sidebar) — non da qui."
    )


def render_gestione_dati(tab: DeltaGenerator, ctx: SimpleNamespace) -> None:
    theme = get_theme_context()
    data = ctx.data
    fmtd = ctx.fmtd
    settings = ctx.settings

    with tab:

        _render_page_intro("Gestione Dati", "Controllo dati, backup, cache grafici, import quotazioni e log applicativo.", "gestione", theme)

        # ─────────────────────────────────────────────
        # 1. Stato sintetico
        # ─────────────────────────────────────────────
        render_section_title(
            "Stato dati",
            comment="Stato sintetico di archivio, anagrafica, prezzi, storico e coerenza minima del portafoglio prima di ogni intervento operativo.",
            icon="data",
        )

        log_stats = get_log_file_stats()
        quote_timestamp = _parse_runtime_date(data.get("last_quotes_update"))
        quote_age_days = (date.today() - quote_timestamp.date()).days if quote_timestamp else None
        freshness_label = (
            "Oggi" if quote_age_days == 0
            else f"{quote_age_days} giorni" if quote_age_days is not None
            else "n/d"
        )

        s1, s2, s3, s4 = st.columns(4, gap="small")
        with s1:
            kpi_card("Strumenti", fmt_num_it(len(data.get("strumenti", []) or []), 0), "Anagrafica", accent=theme.color_blue)
        with s2:
            kpi_card("Date storico", fmt_num_it(len(data.get("storico_prezzi", {}) or {}), 0), "Prezzi salvati", accent=theme.color_green)
        with s3:
            kpi_card("Quotazioni", freshness_label, fmt_dt_it(data.get("last_quotes_update")), accent=theme.color_orange)
        with s4:
            kpi_card("Log", "Presente" if log_stats.get("exists") else "Assente", f"{fmt_num_it((int(log_stats.get('size_bytes') or 0) / 1024), 1)} KB", accent=theme.color_red)

        vertical_gap("sm")

        with st.expander("Inventario file dati", expanded=False):
            storico_gz_path = os.path.join(PRICES_DIR, "portafoglio_storico_prezzi.json.gz")
            storico_parquet_path = os.path.join(PRICES_DIR, "portafoglio_storico_prezzi.parquet")
            files_inventory = pd.DataFrame(
                [
                    {"Categoria": "Configurazione", "File": "settings.json", "Presente": os.path.exists(SETTINGS_FILE), "Dimensione KB": round((os.path.getsize(SETTINGS_FILE) / 1024), 1) if os.path.exists(SETTINGS_FILE) else 0.0},
                    {"Categoria": "Configurazione", "File": "meta.json", "Presente": os.path.exists(META_FILE), "Dimensione KB": round((os.path.getsize(META_FILE) / 1024), 1) if os.path.exists(META_FILE) else 0.0},
                    {"Categoria": "Dati", "File": "data.json", "Presente": os.path.exists(DATA_FILE), "Dimensione KB": round((os.path.getsize(DATA_FILE) / 1024), 1) if os.path.exists(DATA_FILE) else 0.0},
                    {"Categoria": "Dati", "File": "snapshots.json", "Presente": os.path.exists(SNAPSHOTS_FILE), "Dimensione KB": round((os.path.getsize(SNAPSHOTS_FILE) / 1024), 1) if os.path.exists(SNAPSHOTS_FILE) else 0.0},
                    {"Categoria": "Dati", "File": "quotes_log.json", "Presente": os.path.exists(QUOTES_LOG_FILE), "Dimensione KB": round((os.path.getsize(QUOTES_LOG_FILE) / 1024), 1) if os.path.exists(QUOTES_LOG_FILE) else 0.0},
                    {"Categoria": "Dati", "File": "benchmark_cache.json", "Presente": os.path.exists(BENCHMARK_CACHE_FILE), "Dimensione KB": round((os.path.getsize(BENCHMARK_CACHE_FILE) / 1024), 1) if os.path.exists(BENCHMARK_CACHE_FILE) else 0.0},
                    {"Categoria": "Storico", "File": "storico_prezzi.json.gz", "Presente": os.path.exists(storico_gz_path), "Dimensione KB": round((os.path.getsize(storico_gz_path) / 1024), 1) if os.path.exists(storico_gz_path) else 0.0},
                    {"Categoria": "Storico", "File": "storico_prezzi.parquet", "Presente": os.path.exists(storico_parquet_path), "Dimensione KB": round((os.path.getsize(storico_parquet_path) / 1024), 1) if os.path.exists(storico_parquet_path) else 0.0},
                ]
            )
            render_styled_table(files_inventory.style, height="content")

        with st.expander("Bonifica avanzata per categoria / ticker", expanded=False):
            st.caption("Strumento tecnico per ispezionare e rimuovere record di test o porzioni incoerenti dei dataset applicativi.")
            raw_data = load_data()
            category_options = [code for code in ASSET_CATEGORY_REGISTRY.keys() if code != "ALTRO"]
            cleanup_category = st.selectbox(
                "Categoria da ispezionare",
                options=category_options,
                index=category_options.index("AZI") if "AZI" in category_options else 0,
                key="datahub_cleanup_category",
                format_func=lambda code: f"{code} - {ASSET_CATEGORY_REGISTRY.get(code, {}).get('name', code)}",
            )
            tickers_in_category, inventory_df = _category_ticker_inventory(raw_data, cleanup_category)
            selected_cleanup_tickers = st.multiselect(
                "Ticker coinvolti",
                options=tickers_in_category,
                default=tickers_in_category,
                key="datahub_cleanup_tickers",
                help="Puoi limitare la cancellazione a uno o più ticker specifici della categoria.",
            )
            render_styled_table(inventory_df.style, height="content")
            cleanup_sections = st.multiselect(
                "Sezioni JSON da ripulire",
                options=[
                    "strumenti",
                    "instrument_master",
                    "operazioni",
                    "registro_eventi",
                    "proventi",
                    "registro_liquidita",
                    "storico_prezzi",
                    "quotes_log",
                ],
                default=[
                    "strumenti",
                    "instrument_master",
                    "operazioni",
                    "registro_eventi",
                    "proventi",
                    "registro_liquidita",
                    "storico_prezzi",
                    "quotes_log",
                ],
                key="datahub_cleanup_sections",
            )
            render_danger_hint("L'azione rimuove i record selezionati dalle sezioni indicate e poi invalida le cache interne. Usare solo quando sai esattamente cosa stai eliminando.")
            cleanup_confirm = confirm_danger(
                "Confermo la bonifica avanzata dei record selezionati",
                key="datahub_cleanup_confirm",
                help_text="La conferma e' richiesta per evitare cancellazioni tecniche accidentali sui dataset JSON.",
            )
            if st.button("🧨 Cancella record selezionati", type="primary", width="stretch", key="datahub_cleanup_execute", disabled=not cleanup_confirm):
                status_box = st.status("Bonifica dati in corso...", expanded=True)
                status_box.write("Eliminazione record selezionati e invalidazione cache.")
                try:
                    if not selected_cleanup_tickers:
                        raise ValueError("Seleziona almeno un ticker da cancellare.")
                    if not cleanup_sections:
                        raise ValueError("Seleziona almeno una sezione JSON da ripulire.")
                    removed = _delete_category_records(raw_data, selected_cleanup_tickers, cleanup_sections)
                    save_data(raw_data)
                    if "quotes_log" in cleanup_sections:
                        quotes_log = load_quotes_log()
                        quote_items = list((quotes_log or {}).get("items", []) or [])
                        before = len(quote_items)
                        quotes_log["items"] = [
                            item for item in quote_items
                            if str((item or {}).get("ticker") or "").strip() not in set(selected_cleanup_tickers)
                        ]
                        removed["quotes_log"] = before - len(quotes_log["items"])
                        save_quotes_log(quotes_log)
                    append_audit_event(
                        "data_cleanup_brutal",
                        {
                            "category": cleanup_category,
                            "tickers": selected_cleanup_tickers,
                            "sections": cleanup_sections,
                            "removed": removed,
                        },
                    )
                    invalidate_portfolio_cache("bonifica brutale dati")
                    queue_success("Bonifica completata: " + ", ".join(f"{key}={value}" for key, value in removed.items() if value))
                    update_status(status_box, label="Bonifica completata", state="complete")
                    st.rerun()
                except Exception as exc:
                    update_status(status_box, label="Bonifica non riuscita", state="error", expanded=True)
                    st.error(f"Bonifica non riuscita: {exc}")

        # ─────────────────────────────────────────────
        # 2. Backup e ripristino
        # ─────────────────────────────────────────────
        render_section_title(
            "Backup e ripristino",
            comment="Qui controlli copie di sicurezza, ripristino e regole automatiche. Le modifiche in questo blocco incidono sulla protezione dei dati, non sui numeri di portafoglio.",
            icon="data",
        )

        b1, b2 = st.columns(2)
        if b1.button("📦 Crea backup ora", width="stretch", key="datahub_backup_now"):
            status_box = st.status("Creazione backup in corso...", expanded=True)
            folder, _ = create_backup_bundle()
            logger.info("Backup manuale creato da Gestione Dati: folder=%s", folder)
            update_status(status_box, label="Backup creato", state="complete")
            queue_success(f"Backup creato in: {folder}")

        if b2.button("📸 Salva snapshot corrente", width="stretch", key="datahub_snapshot_now"):
            snaps = load_snapshots()
            snaps.setdefault("snapshots", []).append(_build_snapshot_from_data(data, label=f"Snapshot manuale {fmtd(date.today())}"))
            save_snapshots(snaps)
            logger.info("Snapshot manuale creato da Gestione Dati")
            append_audit_event("snapshot_created", {"label": f"Snapshot manuale {fmtd(date.today())}"})
            queue_success("Snapshot salvato.")

        with st.expander("Ripristino, eliminazione e regole backup", expanded=False):
            current_settings = dict(load_settings() or settings or {})
            backup_cfg = get_backup_settings(current_settings)

            st.caption(
                "Queste opzioni non eseguono subito un backup: definiscono quando l'app deve crearne uno automaticamente."
            )
            p1, p2, p3 = st.columns(3)
            backup_enabled_cfg = p1.checkbox(
                "Backup automatici attivi",
                value=bool(backup_cfg.get("enabled", True)),
                key="datahub_policy_backup_enabled",
                help="Interruttore generale: se disattivato, l'app non crea backup automatici nelle operazioni presidiate.",
            )
            backup_before_migration_cfg = p2.checkbox(
                "Backup prima di migrazioni",
                value=bool(backup_cfg.get("backup_before_migration", True)),
                key="datahub_policy_backup_migration",
                help="Crea una copia dei dati prima di aggiornamenti/migrazioni dello schema dati.",
            )
            backup_before_save_cfg = p3.checkbox(
                "Backup prima dei salvataggi",
                value=bool(backup_cfg.get("backup_before_save", False)),
                key="datahub_policy_backup_save",
                help="Crea una copia prima dei salvataggi ordinari. È più sicuro ma può generare molti backup.",
            )
            p4, p5 = st.columns(2)
            keep_last_n_cfg = p4.number_input(
                "Numero massimo backup",
                min_value=1,
                max_value=200,
                value=int(backup_cfg.get("keep_last_n", 20)),
                step=1,
                key="datahub_policy_backup_keep",
                help="Numero di backup da mantenere nelle politiche automatiche di conservazione.",
            )
            quote_log_retention_cfg = p5.number_input(
                "Storico aggiornamenti quotazioni",
                min_value=1,
                max_value=200,
                value=int(current_settings.get("quote_log_retention", 20)),
                step=1,
                key="datahub_policy_quote_retention",
                help="Numero di cicli di aggiornamento quotazioni da conservare nel log visibile nella scheda Quotazioni.",
            )
            if st.button("💾 Salva regole backup/log", width="stretch", type="primary", key="datahub_save_retention_policy"):
                current_settings["backup"] = {
                    **current_settings.get("backup", {}),
                    "enabled": bool(backup_enabled_cfg),
                    "backup_before_migration": bool(backup_before_migration_cfg),
                    "backup_before_save": bool(backup_before_save_cfg),
                    "keep_last_n": int(keep_last_n_cfg),
                    "folder": "backups",
                }
                current_settings["quote_log_retention"] = int(quote_log_retention_cfg)
                save_settings(current_settings)
                queue_success("Regole backup/log aggiornate.")
                st.rerun()

            st.divider()

            backup_list = sorted(
                [name for name in os.listdir(BACKUP_DIR) if os.path.isdir(os.path.join(BACKUP_DIR, name))],
                reverse=True,
            ) if os.path.exists(BACKUP_DIR) else []

            if backup_list:
                selected_backup = st.selectbox("Backup disponibili", backup_list, key="datahub_restore_bkp_sel")
                rb1, rb2 = st.columns(2)
                if rb1.button("♻️ Ripristina backup", width="stretch", key="datahub_restore_backup_btn", type="primary"):
                    status_box = st.status("Ripristino backup in corso...", expanded=True)
                    status_box.write("Copia dei file dati dal backup selezionato.")
                    try:
                        validate_selection([selected_backup], backup_list, label="Backup selezionato")
                        backup_path = os.path.abspath(os.path.join(BACKUP_DIR, selected_backup))
                        backup_root = os.path.abspath(BACKUP_DIR)
                        if not backup_path.startswith(backup_root) or not os.path.isdir(backup_path):
                            raise ValueError("Il backup selezionato non è disponibile.")
                        restored = []
                        for target_file in [DATA_FILE, SETTINGS_FILE, SNAPSHOTS_FILE, QUOTES_LOG_FILE, BENCHMARK_CACHE_FILE, META_FILE]:
                            source_file = os.path.join(backup_path, os.path.basename(target_file))
                            if os.path.exists(source_file):
                                os.makedirs(os.path.dirname(target_file), exist_ok=True)
                                shutil.copy2(source_file, target_file)
                                restored.append(os.path.basename(target_file))
                        if restored:
                            append_audit_event("backup_restored", {"backup": selected_backup, "files_restored": len(restored)})
                            queue_success(f"Ripristinati {len(restored)} file dal backup '{selected_backup}'.")
                            update_status(status_box, label="Backup ripristinato", state="complete")
                            invalidate_portfolio_cache("ripristino backup")
                            st.rerun()
                        else:
                            update_status(status_box, label="Nessun file ripristinabile trovato", state="error", expanded=True)
                            st.error("Nessun file trovato nel backup selezionato.")
                    except ValueError as exc:
                        update_status(status_box, label="Ripristino backup non riuscito", state="error", expanded=True)
                        st.error(str(exc))

                if rb2.button("🗑️ Elimina backup", width="stretch", key="datahub_delete_backup_btn"):
                    status_box = st.status("Eliminazione backup in corso...", expanded=True)
                    try:
                        validate_selection([selected_backup], backup_list, label="Backup selezionato")
                        backup_path = os.path.abspath(os.path.join(BACKUP_DIR, selected_backup))
                        backup_root = os.path.abspath(BACKUP_DIR)
                        if not backup_path.startswith(backup_root) or not os.path.isdir(backup_path):
                            raise ValueError("Il backup selezionato non è disponibile.")
                        shutil.rmtree(backup_path, ignore_errors=True)
                        append_audit_event("backup_deleted", {"backup": selected_backup})
                        queue_success(f"Backup '{selected_backup}' eliminato.")
                        update_status(status_box, label="Backup eliminato", state="complete")
                        st.rerun()
                    except ValueError as exc:
                        update_status(status_box, label="Eliminazione backup non riuscita", state="error", expanded=True)
                        st.error(str(exc))
            else:
                st.info("Nessun backup disponibile.")

        # ─────────────────────────────────────────────
        # 3. Arricchimento strumenti
        # ─────────────────────────────────────────────
        _section_line()
        render_section_title(
            "Arricchimento strumenti",
            comment="Stato dell'arricchimento dati per strumento (YTM, TER, benchmark, composizione) e volume di storico prezzi salvato. Tutte le azioni (automatico, PDF, manuale) si eseguono da Strumenti → Arricchimento, non da qui.",
            icon="data",
        )
        _render_arricchimento(data, ctx)
        vertical_gap("sm")

        # ─────────────────────────────────────────────
        # 4. Esporta per Portfolio Performance
        # ─────────────────────────────────────────────
        if str((settings or {}).get("export_pp_mode", "entrambi")) != "sidebar":
            _section_line()
            render_section_title(
                "Esporta per Portfolio Performance",
                comment="Genera un CSV importabile in Portfolio Performance (app open source). Include tutte le transazioni: acquisti, vendite, cedole, dividendi, rimborsi, versamenti e prelievi.",
                icon="data",
            )

            with st.expander("Esporta transazioni → Portfolio Performance", expanded=False):
                legend_block(
                    "Il file CSV generato è compatibile con Portfolio Performance (portfolio-performance.info). "
                    "Per importarlo: apri PP → File → Importa → CSV. "
                    "Assicurati che il conto deposito e il conto liquidità siano già creati in PP prima di importare."
                )
                try:
                    from core.services.portfolio_performance_export import build_portfolio_performance_csv
                    n_eventi = len(data.get("registro_eventi") or [])
                    st.caption(f"Registro eventi: {n_eventi} record da esportare.")
                    pp_csv = build_portfolio_performance_csv(data)
                    st.download_button(
                        "⬇️ Scarica portfolio_performance.csv",
                        data=pp_csv.encode("utf-8-sig"),
                        file_name="portfolio_performance.csv",
                        mime="text/csv",
                        width="stretch",
                        key="datahub_download_pp_csv",
                    )
                except Exception as _pp_exc:
                    st.error(f"Errore generazione CSV: {_pp_exc}")

            with st.expander("Esporta prezzi storici → Portfolio Performance", expanded=False):
                legend_block(
                    "Genera uno ZIP con un file CSV di prezzi storici per ogni strumento. "
                    "Utile per BTP e fondi FAM che PP non riesce a quotare automaticamente. "
                    "Come importare: in PP seleziona il titolo → tab 'Dati storici' → tasto Importa → scegli il file CSV corrispondente."
                )
                try:
                    from core.services.portfolio_performance_export import build_portfolio_performance_prices_zip
                    sp = data.get("storico_prezzi") or {}
                    n_dates = len(sp)
                    all_tickers: set = set()
                    for d in sp.values():
                        all_tickers.update(d.keys())
                    st.caption(f"Storico prezzi: {n_dates} date, {len(all_tickers)} strumenti.")
                    pp_zip = build_portfolio_performance_prices_zip(data)
                    st.download_button(
                        "⬇️ Scarica prezzi_storici_pp.zip",
                        data=pp_zip,
                        file_name="prezzi_storici_pp.zip",
                        mime="application/zip",
                        width="stretch",
                        key="datahub_download_pp_prices_zip",
                    )
                except Exception as _pp_exc2:
                    st.error(f"Errore generazione ZIP prezzi: {_pp_exc2}")

        # ─────────────────────────────────────────────
        # 4. Cache grafici
        # ─────────────────────────────────────────────
        _section_line()
        render_section_title(
            "Cache grafici",
            comment="Questo blocco agisce solo sulla memorizzazione delle figure e dei prerender. Non modifica operazioni, prezzi o storico del portafoglio.",
            icon="quotes",
        )

        try:
            from core.figure_cache import get_figure_cache
            from core.cache_prewarmer import get_prewarm_status, trigger_background_prewarm

            fcache = get_figure_cache()
            fstats = fcache.get_stats()
            current_settings_for_cache = load_settings() or settings or {}
            cache_settings = get_figure_cache_settings(current_settings_for_cache)
            cache_actions = _get_cache_action_log(current_settings_for_cache)
            cache_tree = _scan_cache_tree(os.path.join(DATA_DIR, "cache"))

            strategy = str(cache_settings.get("strategy", "hybrid"))
            enabled = bool(cache_settings.get("enabled", True))
            cleanup_days = int(cache_settings.get("auto_cleanup_days", 30) or 30)
            max_cache_size_mb = float(cache_settings.get("max_cache_size_mb", 500) or 500)

            c1, c2, c3, c4 = st.columns(4, gap="small")
            with c1:
                kpi_card("Stato", "Attiva" if enabled else "Disattiva", f"Strategia: {strategy}", accent=theme.color_blue)
            with c2:
                kpi_card("File grafici", fmt_num_it(fstats.get("num_files", 0), 0), "JSON/legacy/pickle", accent=theme.color_green)
            with c3:
                kpi_card("Spazio grafici", f"{float(fstats.get('total_size_mb', 0) or 0):.2f} MB", "Cache figure", accent=theme.color_orange)
            with c4:
                kpi_card("Limite", f"{max_cache_size_mb:.0f} MB", f"Pulizia oltre {cleanup_days} gg", accent=theme.color_red)

            vertical_gap("sm")

            a1, a2, a3 = st.columns(3, gap="small")
            a1.caption(f"Ultima ottimizzazione: {fmt_dt_it(cache_actions.get('optimized')) if cache_actions.get('optimized') else 'mai'}")
            a2.caption(f"Ultimo svuotamento: {fmt_dt_it(cache_actions.get('cleared')) if cache_actions.get('cleared') else 'mai'}")
            a3.caption(f"Ultimo pre-warming: {fmt_dt_it(cache_actions.get('prewarm_started')) if cache_actions.get('prewarm_started') else 'mai'}")

            col_maint, col_clear, col_prewarm = st.columns(3, gap="small")
            with col_maint:
                if st.button("🧹 Ottimizza cache", width="stretch", type="primary", key="datahub_cache_maintain"):
                    status_box = st.status("Ottimizzazione cache in corso...", expanded=True)
                    status_box.write("Migrazione legacy, rimozione orfani e applicazione limiti.")
                    report = fcache.maintain_cache(migrate_legacy=True, remove_orphans=True, enforce_limits=True)
                    invalidate_portfolio_cache("cache figure ottimizzata")
                    _record_cache_action("optimized")
                    queue_success(
                        f"Cache ottimizzata: migrati {report.get('migrated_legacy_json', 0)} · "
                        f"rimossi pickle {report.get('removed_legacy_pickle', 0)} · "
                        f"orfani {report.get('removed_orphans', 0)} · "
                        f"policy {report.get('removed_by_policy', 0)}"
                    )
                    if report.get("errors"):
                        update_status(status_box, label="Cache ottimizzata con avvisi", state="complete")
                        with st.expander("Errori manutenzione cache", expanded=False):
                            st.code("\n".join(report.get("errors", [])), language="text")
                    else:
                        update_status(status_box, label="Cache ottimizzata", state="complete")
                    st.rerun()

            with col_clear:
                clear_confirm = confirm_danger(
                    "Confermo svuotamento cache grafici",
                    key="datahub_clear_cache_confirm",
                    help_text="Non elimina dati di portafoglio, ma forza la rigenerazione dei grafici alla prossima apertura.",
                )
                if st.button("🗑️ Svuota cache", width="stretch", type="secondary", key="datahub_clear_cache", disabled=not clear_confirm):
                    status_box = st.status("Svuotamento cache in corso...", expanded=True)
                    count = fcache.clear_all()
                    invalidate_portfolio_cache("cache figure svuotata")
                    _record_cache_action("cleared")
                    queue_success(f"Cache grafici ripulita: {count} file rimossi")
                    update_status(status_box, label="Cache grafici ripulita", state="complete")
                    st.rerun()

            with col_prewarm:
                status = get_prewarm_status()
                if status["running"]:
                    st.info("Pre-warming in esecuzione...")
                elif st.button("⚡ Pre-warming", width="stretch", type="secondary", key="datahub_prewarm_now"):
                    started = trigger_background_prewarm(ctx, theme, settings)
                    if started:
                        _record_cache_action("prewarm_started")
                        queue_success("Pre-warming avviato. I grafici verranno preparati in background se il pre-warmer trova chart supportati.")
                    else:
                        st.info("Pre-warming già in esecuzione.")

            with st.expander("Dettagli, diagnostica e regole cache", expanded=False):
                st.caption("Sintesi read-only di cache figure, pre-warming, spazio fisico e ultime azioni di manutenzione.")
                cache_health_rows = build_cache_health_rows(
                    cache_settings=cache_settings,
                    figure_stats=fstats,
                    cache_tree=cache_tree,
                    prewarm_status=status,
                    action_log=cache_actions,
                )
                render_styled_table(pd.DataFrame(cache_health_rows).style, height="content")

                cache_rows = [
                    {"Voce": "JSON attivi", "File": int(fstats.get("json_files", 0) or 0), "Dimensione": f"{float(fstats.get('total_size_mb', 0) or 0):.2f} MB"},
                    {"Voce": "Legacy doppio suffisso", "File": int(fstats.get("legacy_double_json_files", 0) or 0), "Dimensione": "da migrare"},
                    {"Voce": "Pickle legacy", "File": int(fstats.get("pickle_files", 0) or 0), "Dimensione": "legacy"},
                    {"Voce": "Totale data/cache", "File": int(cache_tree.get("total_files", 0) or 0), "Dimensione": _mb_label(cache_tree.get("total_size_bytes", 0))},
                ]
                render_styled_table(pd.DataFrame(cache_rows).style, height="content")

                chart_rows = build_cache_chart_rows(fstats, limit=10)
                if chart_rows:
                    with st.popover("Chart piu' presenti in cache", width="stretch"):
                        render_styled_table(pd.DataFrame(chart_rows).style, height="content")
                else:
                    st.caption("Manifest cache ancora vuoto o non leggibile: i chart appariranno dopo la generazione dei grafici.")

                cache_recommendations = build_diagnostic_recommendations(
                    cache_settings=cache_settings,
                    figure_stats=fstats,
                    cache_tree=cache_tree,
                    render_rows=[],
                )
                st.caption("Diagnostica: " + " ".join(cache_recommendations))

                current_settings = dict(load_settings() or settings or {})
                current_cache = get_figure_cache_settings(current_settings)
                cc1, cc2 = st.columns(2)
                cache_enabled = cc1.checkbox("Cache attiva", value=bool(current_cache.get("enabled", True)), key="datahub_cache_enabled")
                cache_strategy = cc2.selectbox(
                    "Strategia cache",
                    ["disabled", "session_only", "disk_only", "hybrid"],
                    index=["disabled", "session_only", "disk_only", "hybrid"].index(str(current_cache.get("strategy", "hybrid")) if str(current_cache.get("strategy", "hybrid")) in ["disabled", "session_only", "disk_only", "hybrid"] else "hybrid"),
                    key="datahub_cache_strategy",
                    help=(
                        "disabled: niente cache figure; session_only: cache solo finché la sessione Streamlit resta aperta; "
                        "disk_only: cache persistente su disco; hybrid: prima sessione, poi disco. Hybrid è normalmente la scelta migliore."
                    ),
                )
                st.caption(
                    "Hybrid usa prima la memoria di sessione e poi il disco: riduce i tempi nei rerun e conserva i grafici tra un avvio e l'altro."
                )
                cc3, cc4 = st.columns(2)
                auto_cleanup_days = cc3.number_input("Rimuovi oltre N giorni", min_value=1, max_value=365, value=int(current_cache.get("auto_cleanup_days", 30) or 30), step=1, key="datahub_cache_cleanup_days")
                max_size_cfg = cc4.number_input("Dimensione massima MB", min_value=10.0, max_value=5000.0, value=float(current_cache.get("max_cache_size_mb", 500) or 500), step=10.0, key="datahub_cache_max_mb")
                if st.button("💾 Salva regole cache", width="stretch", type="primary", key="datahub_save_cache_rules"):
                    current_settings["ui_figure_cache"] = {
                        **current_settings.get("ui_figure_cache", {}),
                        "enabled": bool(cache_enabled),
                        "strategy": str(cache_strategy),
                        "auto_cleanup_days": int(auto_cleanup_days),
                        "max_cache_size_mb": float(max_size_cfg),
                    }
                    save_settings(current_settings)
                    queue_success("Regole cache aggiornate.")
                    st.rerun()

                st.divider()
                page_map = {"summary": "Riepilogo", "andamento": "Andamento", "quotazioni": "Quotazioni", "analisi": "Analisi", "cruscotti": "Cruscotti"}
                col_sel, col_reset = st.columns([2, 1])
                with col_sel:
                    selected_page = st.selectbox("Reset selettivo pagina", options=list(page_map.keys()), format_func=lambda x: page_map.get(x, x), key="cache_page_select")
                with col_reset:
                    st.markdown("<div style='height:1.65rem;'></div>", unsafe_allow_html=True)
                    if st.button("🔄 Reset pagina", width="stretch", type="secondary", key=f"reset_cache_{selected_page}"):
                        count = fcache.clear_by_pattern(selected_page)
                        if count > 0:
                            queue_success(f"Cache {page_map.get(selected_page, selected_page)} ripulita: {count} file rimossi")
                        else:
                            queue_info(
                                f"Nessun file eliminato per {page_map.get(selected_page, selected_page)}. "
                                "Il reset selettivo funziona se i chart_id o i nomi cache sono riconducibili alla pagina selezionata."
                            )
                        st.rerun()

        except Exception as e:
            logger.error("Cache section error: %s", e)
            st.error(f"Errore nella gestione cache: {e}")

        # ─────────────────────────────────────────────
        # 5. Import quotazioni e log
        # ─────────────────────────────────────────────
        _section_line()
        render_section_title(
            "Import e log",
            comment="Raccolta degli strumenti operativi per import quotazioni, osservare il log applicativo e fare diagnostica tecnica.",
            icon="operations",
        )

        with st.expander("Importa quotazioni da file esterno", expanded=False):
            legend_block(
                "Carica il file JSON scaricato dal tuo script PHP remoto. Le quotazioni vengono aggiornate nel portafoglio senza connessione internet da questa app."
            )

            php_code = _build_remote_quotes_php(data)
            st.download_button(
                "⬇️ Scarica aggiorna_remoto.php",
                data=php_code,
                file_name="aggiorna_remoto.php",
                mime="application/x-httpd-php",
                width="stretch",
                key="datahub_download_remote_php",
            )
            st.caption("Il file PHP viene generato partendo da aggiorna_remoto.php del progetto, ma con l'elenco strumenti sincronizzato con l'anagrafica attuale dell'app.")

            uploaded_quotes = st.file_uploader(
                "Seleziona file quotazioni",
                type=["json"],
                key="datahub_import_quotes_uploader",
            )
            if uploaded_quotes is not None and st.button("⬇️ Importa quotazioni", type="primary", width="stretch", key="datahub_import_quotes_btn"):
                status_box = st.status("Import quotazioni in corso...", expanded=True)
                status_box.write("Validazione file e aggiornamento storico prezzi.")
                try:
                    import json as _json
                    quotes_payload = _json.loads(uploaded_quotes.read().decode("utf-8"))
                    validate_quote_import(quotes_payload)
                    prices = quotes_payload.get("prezzi", {})
                    timestamp = quotes_payload.get("timestamp", str(date.today()))
                    timestamp_date = timestamp[:10] if isinstance(timestamp, str) and len(timestamp) >= 10 else str(date.today())
                    validate_date(timestamp_date)

                    updated = 0
                    skipped = 0
                    info_map = {item["ticker"]: item for item in data.get("strumenti", [])}
                    for ticker, px in prices.items():
                        try:
                            px_float = float(px)
                        except (TypeError, ValueError):
                            skipped += 1
                            continue
                        if px_float <= 0 or ticker not in info_map:
                            skipped += 1
                            continue
                        info_map[ticker]["prezzo"] = px_float
                        info_map[ticker]["fonte"] = "remoto"
                        info_map[ticker]["aggiornato"] = timestamp_date
                        if date.today().weekday() < 5:
                            data["storico_prezzi"].setdefault(timestamp_date, {})[ticker] = px_float
                        updated += 1

                    if updated <= 0:
                        raise ValueError("Il file non contiene ticker riconosciuti del portafoglio.")
                    data["last_quotes_update"] = timestamp_date + " 00:00:00 (importato)"
                    save_data(data)
                    append_audit_event("quotes_imported", {"updated": updated, "skipped": skipped, "timestamp": timestamp_date})
                    invalidate_portfolio_cache("quotazioni importate")
                    queue_success(f"Import completato: {updated} aggiornati, {skipped} saltati.")
                    update_status(status_box, label="Import quotazioni completato", state="complete")
                    st.rerun()
                except Exception as exc:
                    update_status(status_box, label="Import quotazioni non riuscito", state="error", expanded=True)
                    st.error(f"Import non riuscito: {exc}")

        with st.expander("Log applicativo", expanded=False):
            log_path = str(log_stats.get("path") or get_default_log_file_path())
            st.caption(f"File log: {log_path}")
            log_tail = read_log_tail(lines=60)
            if log_tail:
                st.code("".join(log_tail), language="text")
            else:
                st.caption("Nessuna riga disponibile.")

        with st.expander("Diagnostica tecnica", expanded=False):
            checks = _build_observability_checks(
                data=data,
                settings=settings,
                log_stats=log_stats,
                snapshots_state=getattr(ctx, "snapshots_state", None),
            )
            checks_df = pd.DataFrame(checks)
            _render_diagnostic_table(checks_df, height="content")

            runtime_rows = build_runtime_diagnostic_rows(
                data=data,
                settings=settings,
                log_stats=log_stats,
                snapshots_state=getattr(ctx, "snapshots_state", None),
            )
            _render_diagnostic_table(runtime_rows, height="content")

            render_events = get_render_profile_events()
            render_rows = build_render_event_rows(render_events, limit=12, min_seconds=0.001)
            recommendations = build_diagnostic_recommendations(
                cache_settings=get_figure_cache_settings(settings or {}),
                figure_stats=None,
                cache_tree=None,
                render_rows=render_rows,
            )
            if recommendations:
                st.info(" ".join(recommendations))

            dcol1, dcol2 = st.columns(2, gap="small")
            with dcol1:
                with st.popover("Sessione Streamlit", width="stretch"):
                    _render_diagnostic_table(build_session_state_rows(st.session_state), height="content")
            with dcol2:
                if render_rows:
                    with st.popover("Sotto-fasi lente", width="stretch"):
                        _render_diagnostic_table(render_rows, height="content")
                        st.download_button(
                            "Scarica render profile",
                            data=render_profile_text(min_seconds=0.0),
                            file_name="render_profile.txt",
                            mime="text/plain",
                            width="stretch",
                            key="datahub_download_render_profile",
                        )
                else:
                    st.caption("Nessuna sotto-fase di render registrata in questa sessione.")

            meta_state = load_meta()
            runtime = meta_state.get("runtime", {}) if isinstance(meta_state.get("runtime", {}), dict) else {}
            migration = meta_state.get("migration", {}) if isinstance(meta_state.get("migration", {}), dict) else {}

            tech_rows = pd.DataFrame(
                [
                    {"Voce": "Ultimo avvio", "Valore": fmt_dt_it(runtime.get("last_start"))},
                    {"Voce": "Ultimo salvataggio", "Valore": fmt_dt_it(runtime.get("last_successful_save"))},
                    {"Voce": "Ultima migrazione", "Valore": fmt_dt_it(migration.get("migration_timestamp"))},
                ]
            )
            _render_diagnostic_table(tech_rows, height="content")

        _section_line()
        render_section_title(
            "Controlli integrita",
            comment="Verifica incrociata tra anagrafica, eventi, prezzi e metadati GOV/BTP. Serve a capire se il portafoglio e' leggibile correttamente prima ancora di interpretarne i risultati.",
            icon="risk",
        )
        integrity_checks = build_integrity_checks(
            data=data,
            btp_calendar_df=getattr(ctx, "btp_calendar_df", pd.DataFrame()),
        )
        integrity_df = pd.DataFrame(integrity_checks)
        severity_sort = {"Errore": 0, "Warning": 1, "Info": 2, "OK": 3}
        if not integrity_df.empty and "Severita" in integrity_df.columns:
            integrity_df["_sort"] = integrity_df["Severita"].map(lambda v: severity_sort.get(str(v), 9))
            integrity_df = integrity_df.sort_values(["_sort", "Ambito", "Elemento"]).drop(columns=["_sort"])

            def _style_integrity(row):
                sev = str(row.get("Severita", ""))
                sev_color = {
                    "Errore": theme.color_red,
                    "Warning": theme.color_orange,
                    "Info": theme.color_blue,
                    "OK": theme.color_green,
                }.get(sev, theme.font_color)
                styles = []
                for col in row.index:
                    style = ""
                    if col == "Severita":
                        style += f"color:{sev_color};font-weight:700;"
                    if col == "Elemento":
                        style += "font-weight:600;"
                    styles.append(style)
                return styles

            styled_integrity = integrity_df.style.apply(_style_integrity, axis=1)
            render_styled_table(styled_integrity, height="content")
        else:
            st.info("Nessun controllo disponibile.")

        vertical_gap("lg")
        back_to_top()
