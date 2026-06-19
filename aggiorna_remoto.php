<?php
/**
 * aggiorna_remoto.php — Aggiornamento quotazioni da remoto
 *
 * ISTRUZIONI:
 * 1. Carica questo file su una cartella con nome segreto del tuo sito (es. /privato/xk7q2/)
 * 2. Aggiorna la sezione CONFIGURAZIONE con i tuoi strumenti (usa il bottone
 *    "Aggiornamento quotazioni da remoto" nella pagina Impostazioni della dashboard)
 * 3. Visita la pagina da qualsiasi browser per scaricare il file JSON aggiornato
 * 4. Al rientro, esegui: python importa_quotazioni.py quotazioni_YYYY-MM-DD.json
 *
 * REQUISITI HOSTING: PHP 7.4+ con curl abilitato (standard su qualsiasi hosting condiviso)
 */

// ============================================================
// CONFIGURAZIONE — Aggiorna con i tuoi strumenti
// (usa il bottone "Esporta config PHP" in Impostazioni)
// ============================================================
$strumenti = [
    // ETF e fondi: usa il ticker Yahoo Finance
    // ["ticker" => "VWCE.DE",  "isin" => "IE00BK5BQT80", "tipo" => "ETF",  "nome" => "Vanguard FTSE All-World"],
    // BTP: usa sempre il prefisso BTP- e l'ISIN completo
    // ["ticker" => "BTP-8128", "isin" => "IT0005518128", "tipo" => "BTP",  "nome" => "BTP 2052"],
];

// Configura qui i tuoi strumenti oppure usa il bottone
// "Esporta config PHP" in Impostazioni per generare questo blocco automaticamente.
$strumenti = [];

// ============================================================
// FINE CONFIGURAZIONE
// ============================================================

if (empty($strumenti)) {
    header("Content-Type: text/html; charset=utf-8");
    echo "<h2>aggiorna_remoto.php</h2>";
    echo "<p><strong>Configurazione mancante.</strong> Apri la dashboard, vai in Impostazioni &rarr; ";
    echo "\"Aggiornamento quotazioni da remoto (PHP)\" e copia il blocco generato in questo file.</p>";
    exit;
}

$data_oggi = date("Y-m-d");
$ora_gen   = date("Y-m-d H:i:s");
$prezzi    = [];
$log       = [];

/**
 * Scarica il prezzo da Yahoo Finance (query1 + query2 come fallback).
 */
function get_yahoo_price(string $ticker): ?float {
    // Prova query1 e query2 come fallback
    foreach (["query1", "query2"] as $host) {
        $url = "https://{$host}.finance.yahoo.com/v8/finance/chart/"
             . rawurlencode($ticker)
             . "?interval=1d&range=5d";
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT        => 15,
            CURLOPT_HTTPHEADER     => [
                "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept: application/json,text/plain,*/*",
                "Accept-Language: it-IT,it;q=0.9,en;q=0.8",
                "Referer: https://finance.yahoo.com/",
            ],
            CURLOPT_SSL_VERIFYPEER => false,
            CURLOPT_FOLLOWLOCATION => true,
        ]);
        $resp     = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);
        if (!$resp || $httpCode >= 400) continue;
        $js = json_decode($resp, true);
        if (!isset($js["chart"]["result"][0])) continue;
        $closes = $js["chart"]["result"][0]["indicators"]["quote"][0]["close"] ?? [];
        $closes = array_values(array_filter($closes, function($v) { return $v !== null; }));
        if (!empty($closes)) return (float) end($closes);
    }
    return null;
}

/**
 * Cerca il ticker Yahoo Finance tramite ISIN (utile per fondi senza ticker standard).
 * Replica get_yahoo_ticker() di core/market_data.py
 */
function get_yahoo_ticker_by_isin(string $isin): ?string {
    $url = "https://query2.finance.yahoo.com/v1/finance/search?q=" . rawurlencode($isin) . "&quotesCount=5&newsCount=0";
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT        => 10,
        CURLOPT_HTTPHEADER     => ["User-Agent: Mozilla/5.0"],
        CURLOPT_SSL_VERIFYPEER => false,
    ]);
    $resp = curl_exec($ch);
    curl_close($ch);
    if (!$resp) return null;
    $js     = json_decode($resp, true);
    $quotes = $js["quotes"] ?? [];
    // 1. Preferisce ticker .MI (Borsa Italiana)
    foreach ($quotes as $q) {
        $sym = $q["symbol"] ?? "";
        if (substr(strtoupper($sym), -3) === ".MI") return $sym;
    }
    // 2. Qualsiasi ticker con punto ma non 0P (fondi Yahoo)
    foreach ($quotes as $q) {
        $sym = $q["symbol"] ?? "";
        if (strpos($sym, "0P") !== 0 && strpos($sym, ".") !== false) return $sym;
    }
    // 3. Qualsiasi ticker trovato (inclusi fondi 0P...)
    if (!empty($quotes)) return $quotes[0]["symbol"] ?? null;
    return null;
}

/**
 * Fallback per ticker .MI (Borsa Italiana): scraping pagina ETF/fondo.
 */
function get_borsaitaliana_etf_price(string $isin): ?float {
    $urls = [
        "https://www.borsaitaliana.it/borsa/etf/dati-completi.html?isin=" . urlencode($isin) . "&lang=it",
        "https://www.borsaitaliana.it/borsa/fondi/etf/scheda/" . urlencode($isin) . ".html?lang=it",
    ];
    foreach ($urls as $url) {
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT        => 15,
            CURLOPT_HTTPHEADER     => [
                "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept-Language: it-IT,it;q=0.9",
            ],
            CURLOPT_SSL_VERIFYPEER => false,
            CURLOPT_FOLLOWLOCATION => true,
        ]);
        $html = curl_exec($ch);
        curl_close($ch);
        if (!$html) continue;
        foreach (["Prezzo Ultimo", "Ultimo Prezzo", "Prezzo di Riferimento", "Nav"] as $term) {
            $pos = stripos($html, $term);
            if ($pos === false) continue;
            $chunk = strip_tags(substr($html, $pos, 400));
            if (preg_match('/\b(\d{1,3}(?:[.,]\d{3})*[.,]\d{2,4})\b/', $chunk, $m)) {
                // Normalizza: rimuove separatore migliaia, converte virgola decimale
                $raw = $m[1];
                // Se ha punto come separatore migliaia (es. 1.234,56) → rimuovi punto
                if (preg_match('/\d\.\d{3},/', $raw)) {
                    $raw = str_replace('.', '', $raw);
                }
                $v = (float) str_replace(',', '.', $raw);
                if ($v > 0.01 && $v < 100000) return $v;
            }
        }
    }
    return null;
}

/**
 * Scarica il prezzo di un BTP da Borsa Italiana via curl + regex.
 */
function get_btp_price(string $isin): ?float {
    $urls = [
        "https://www.borsaitaliana.it/borsa/obbligazioni/mot/btp/dati-completi.html?isin=" . urlencode($isin) . "&lang=it",
        "https://www.borsaitaliana.it/borsa/obbligazioni/mot/btp/scheda/" . urlencode($isin) . "-MOTX.html?lang=it",
    ];
    foreach ($urls as $url) {
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT        => 15,
            CURLOPT_HTTPHEADER     => [
                "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept-Language: it-IT,it;q=0.9",
            ],
            CURLOPT_SSL_VERIFYPEER => false,
            CURLOPT_FOLLOWLOCATION => true,
        ]);
        $html = curl_exec($ch);
        curl_close($ch);
        if (!$html) continue;
        foreach (["Prezzo Ultimo Contratto", "Prezzo di Riferimento", "prezzo_rif"] as $term) {
            $pos = stripos($html, $term);
            if ($pos === false) continue;
            $chunk = substr($html, $pos, 500);
            if (preg_match_all('/\b(\d{2,3}[,\.]\d{1,4})\b/', strip_tags($chunk), $m)) {
                foreach ($m[1] as $raw) {
                    $v = (float) str_replace(',', '.', str_replace('.', '', $raw));
                    if ($v > 30 && $v < 200) return $v;
                }
            }
        }
    }
    return null;
}

// Raccolta prezzi
foreach ($strumenti as $s) {
    $tk   = $s["ticker"];
    $isin = $s["isin"];
    $tipo = strtoupper($s["tipo"]);
    $nome = $s["nome"];

    if (strpos($tipo, "BTP") !== false || strpos($tk, "BTP-") === 0) {
        // ── BTP: scraping Borsa Italiana ──────────────────────────────────
        $prezzo = get_btp_price($isin);
        $fonte  = "Borsa Italiana";
    } else {
        $tkUp   = strtoupper($tk);
        $prezzo = null;
        $fonte  = "Non trovato";

        // ── Passo 1: Yahoo Finance con il ticker configurato ──────────────
        if ($prezzo === null) {
            $prezzo = get_yahoo_price($tk);
            if ($prezzo !== null) $fonte = "Yahoo Finance [{$tk}]";
        }

        // ── Passo 2: cerca ticker reale via ISIN (fondi FAM, ecc.) ────────
        if ($prezzo === null) {
            $autoTk = get_yahoo_ticker_by_isin($isin);
            if ($autoTk !== null && strtoupper($autoTk) !== $tkUp) {
                $prezzo = get_yahoo_price($autoTk);
                if ($prezzo !== null) $fonte = "Yahoo Finance [{$autoTk}]";
            }
        }

        // ── Passo 3: Borsa Italiana per ticker .MI o tipo PAC ─────────────
        if ($prezzo === null && (substr($tkUp, -3) === ".MI" || strtoupper($tipo) === "PAC")) {
            $prezzo = get_borsaitaliana_etf_price($isin);
            if ($prezzo !== null) $fonte = "Borsa Italiana (fallback)";
        }
    }

    if ($prezzo !== null) {
        $prezzi[$tk] = $prezzo;
        $log[] = ["ticker" => $tk, "nome" => $nome, "prezzo" => $prezzo, "fonte" => $fonte, "esito" => "OK"];
    } else {
        $log[] = ["ticker" => $tk, "nome" => $nome, "prezzo" => null, "fonte" => $fonte, "esito" => "ERRORE"];
    }
    usleep(200000); // 0.2 sec tra le richieste
}

$output = [
    "data"     => $data_oggi,
    "generato" => $ora_gen,
    "fonte"    => "aggiorna_remoto.php",
    "prezzi"   => $prezzi,
    "log"      => $log,
];

$json_out = json_encode($output, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);
$filename = "quotazioni_" . $data_oggi . ".json";

header("Content-Type: application/json; charset=utf-8");
header("Content-Disposition: attachment; filename=\"$filename\"");
header("Content-Length: " . strlen($json_out));
header("Cache-Control: no-cache, no-store, must-revalidate");
echo $json_out;
exit;
?>
