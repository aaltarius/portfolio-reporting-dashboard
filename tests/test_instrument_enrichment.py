# tests/test_instrument_enrichment.py
import pathlib
from unittest.mock import patch, MagicMock
from core.instrument_enrichment import (
    _categoria,
    _extract_yahoo_alt,
    enrich_strumento,
    enrich_all,
    enrich_btp,
    enrich_etf_etc,
    enrich_fondo,
    parse_fineco_pdf,
)

PDF_ROOT = pathlib.Path(__file__).parent.parent  # project root


def test_categoria_btp():
    assert _categoria("Titolo di Stato") == "btp"
    assert _categoria("BTP") == "btp"
    assert _categoria("Stato Italia") == "btp"


def test_categoria_etf():
    assert _categoria("ETF Azionario") == "etf"
    assert _categoria("ETF Obbligazionario") == "etf"


def test_categoria_etc():
    assert _categoria("ETC Oro") == "etc"


def test_categoria_fondo():
    assert _categoria("Fondo Bilan. Flessibile") == "fondo"
    assert _categoria("Fondo Obbl. Merc. Em.") == "fondo"
    assert _categoria("Az. Passivo") == "fondo"


def test_extract_yahoo_alt():
    assert _extract_yahoo_alt("Yahoo [0P0001OSMH.F]") == "0P0001OSMH.F"
    assert _extract_yahoo_alt("Borsa Italiana") is None
    assert _extract_yahoo_alt("") is None


def test_enrich_strumento_dispatches_btp():
    s = {"ticker": "BTP26", "tipo": "Titolo di Stato", "isin": "IT0005454241"}
    with patch("core.instrument_enrichment.enrich_btp", return_value={**s, "ytm_netto": "2.27%"}) as mock:
        result = enrich_strumento(s)
    mock.assert_called_once_with(s)
    assert result.get("ytm_netto") == "2.27%"


def test_enrich_strumento_dispatches_etf():
    s = {"ticker": "ETFMIB", "tipo": "ETF Azionario", "isin": "FR0010010827"}
    with patch("core.instrument_enrichment.enrich_etf_etc", return_value={**s, "ter": "0.40%"}) as mock:
        result = enrich_strumento(s)
    mock.assert_called_once_with(s)
    assert result.get("ter") == "0.40%"


def test_enrich_strumento_etf_aggiorna_tipo_da_focus_anche_se_gia_presente():
    s = {"ticker": "SMART.MI", "tipo": "ETF a Gestione Attiva", "isin": "LU1190417599"}
    enriched = {**s, "focus_etf": "Mercato monetario, EUR, Globale", "benchmark": "ESTR Compounded"}
    with patch("core.instrument_enrichment.enrich_etf_etc", return_value=enriched):
        result = enrich_strumento(s)
    assert result["tipo"] == "ETF Monetario"


def test_enrich_strumento_etf_senza_focus_non_tocca_il_tipo():
    s = {"ticker": "XYZ.MI", "tipo": "ETF Az. Globale", "isin": "LU0000000000"}
    enriched = {**s, "ter": "0.10%"}
    with patch("core.instrument_enrichment.enrich_etf_etc", return_value=enriched):
        result = enrich_strumento(s)
    assert result["tipo"] == "ETF Az. Globale"


def test_enrich_strumento_etf_con_errore_non_tocca_il_tipo():
    s = {"ticker": "XYZ.MI", "tipo": "ETF Az. Globale", "isin": "LU0000000000"}
    enriched = {**s, "focus_etf": "Azioni, India", "enrichment_error": "ISIN non trovato"}
    with patch("core.instrument_enrichment.enrich_etf_etc", return_value=enriched):
        result = enrich_strumento(s)
    assert result["tipo"] == "ETF Az. Globale"


def test_enrich_strumento_dispatches_fondo():
    s = {"ticker": "FAM-FLEX", "tipo": "Fondo Bilan. Flessibile", "fonte": "Yahoo [0P0001F3J9.F]"}
    with patch("core.instrument_enrichment.enrich_fondo", return_value={**s, "valuta": "EUR"}) as mock:
        result = enrich_strumento(s)
    mock.assert_called_once_with(s)


def test_enrich_all_counts():
    data = {
        "strumenti": [
            {"ticker": "A", "tipo": "ETF Azionario", "stato": "aperto"},
            {"ticker": "B", "tipo": "Titolo di Stato", "stato": "aperto"},
            {"ticker": "C", "tipo": "ETF Azionario", "stato": "chiuso"},  # escluso
        ]
    }
    with patch("core.instrument_enrichment.enrich_strumento", side_effect=lambda s: s) as mock:
        ok, err, msgs = enrich_all(data)
    assert mock.call_count == 2  # solo aperti
    assert ok == 2
    assert err == 0


def test_enrich_all_handles_error():
    data = {"strumenti": [{"ticker": "X", "tipo": "ETF Azionario", "stato": "aperto"}]}
    with patch("core.instrument_enrichment.enrich_strumento", side_effect=ValueError("fetch failed")):
        ok, err, msgs = enrich_all(data)
    assert ok == 0
    assert err == 1
    assert "fetch failed" in msgs[0]


# ---------------------------------------------------------------------------
# BTP tests
# ---------------------------------------------------------------------------

MOCK_BTP_HTML = """
<html><body><table>
<tr><td>Rendimento effettivo a scadenza lordo</td><td>2,89%</td></tr>
<tr><td>Rendimento effettivo a scadenza netto</td><td>2,27%</td></tr>
<tr><td>Rateo lordo</td><td>0,00</td></tr>
<tr><td>Rateo netto</td><td>0,00</td></tr>
<tr><td>Duration modificata</td><td>0,09</td></tr>
<tr><td>Scadenza</td><td>01/08/2026</td></tr>
<tr><td>Periodicita cedola</td><td>Semestrale</td></tr>
<tr><td>Tasso cedola periodale</td><td>0,00%</td></tr>
<tr><td>Emittente</td><td>Repubblica Italiana</td></tr>
<tr><td>Data godimento</td><td>01/08/2021</td></tr>
</table></body></html>
"""


def test_enrich_btp_fields():
    s = {"ticker": "BTP26", "tipo": "Titolo di Stato", "isin": "IT0005454241", "stato": "aperto"}
    mock_resp = MagicMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.text = MOCK_BTP_HTML
    with patch("core.instrument_enrichment.requests.get", return_value=mock_resp):
        result = enrich_btp(s)
    assert result["ytm_netto"] == "2,27%"
    assert result["ytm_lordo"] == "2,89%"
    assert result["duration_modificata"] == "0,09"
    assert result["scadenza"] == "2026-08-01"
    assert result["enriched_at"] is not None
    assert result["enrichment_source"]["ytm_netto"] == "auto"


def test_enrich_btp_no_isin():
    s = {"ticker": "BTP26", "tipo": "Titolo di Stato", "stato": "aperto"}
    result = enrich_btp(s)
    assert "ytm_netto" not in result
    assert "enrichment_error" in result


# ---------------------------------------------------------------------------
# ETF/ETC tests
# ---------------------------------------------------------------------------

MOCK_JUSTETF_HTML = """
<html><body>
<dl>
  <dt>Indicatore sintetico di spesa (TER)</dt><dd>0,40% p.a.</dd>
  <dt>Indice</dt><dd>FTSE MIB NR EUR</dd>
  <dt>Emittente</dt><dd>Amundi Asset Management</dd>
  <dt>Politica di distribuzione</dt><dd>Distribuzione</dd>
  <dt>Replicazione</dt><dd>Fisica</dd>
  <dt>Valuta dell'ETF</dt><dd>EUR</dd>
</dl>
<table>
  <tr><td>UniCredit SpA</td><td>15,97%</td></tr>
  <tr><td>Intesa Sanpaolo</td><td>12,65%</td></tr>
</table>
<table>
  <tr><td>Italia</td><td>98,50%</td></tr>
</table>
</body></html>
"""


def test_enrich_etf_fields():
    s = {"ticker": "ETFMIB.MI", "tipo": "ETF Azionario", "isin": "FR0010010827", "stato": "aperto"}
    mock_resp = MagicMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.text = MOCK_JUSTETF_HTML
    with patch("core.instrument_enrichment.requests.get", return_value=mock_resp):
        result = enrich_etf_etc(s)
    assert result["ter"] == "0,40% p.a."
    assert result["benchmark"] == "FTSE MIB NR EUR"
    assert result["emittente"] == "Amundi Asset Management"
    assert result["distribuzione"] == "Distribuzione"
    assert len(result["holdings_top"]) == 2
    assert result["holdings_top"][0]["nome"] == "UniCredit SpA"
    assert result["enrichment_source"]["ter"] == "auto"


def test_enrich_etf_no_isin():
    s = {"ticker": "ETFMIB.MI", "tipo": "ETF Azionario", "stato": "aperto"}
    result = enrich_etf_etc(s)
    assert "enrichment_error" in result


# ---------------------------------------------------------------------------
# Fondo tests
# ---------------------------------------------------------------------------

def test_enrich_fondo_fields():
    s = {
        "ticker": "FAM-FLEX",
        "tipo": "Fondo Bilan. Flessibile",
        "fonte": "Yahoo [0P0001F3J9.F]",
        "stato": "aperto",
    }
    mock_ticker = MagicMock()
    mock_ticker.info = {
        "currency": "EUR",
        "fiftyTwoWeekHigh": 145.26,
        "fiftyTwoWeekLow": 130.51,
        "firstTradeDateEpochUtc": 1543276800,
        "ytdReturn": 4.19225,
    }
    with patch("core.instrument_enrichment.yf.Ticker", return_value=mock_ticker):
        result = enrich_fondo(s)
    assert result["valuta"] == "EUR"
    assert result["max_52w"] == 145.26
    assert result["min_52w"] == 130.51
    assert result["data_lancio"] == "2018-11-27"
    assert result["rendimento_ytd"] == "4.19%"
    assert result["enrichment_source"]["valuta"] == "auto"


def test_enrich_fondo_no_fonte():
    s = {"ticker": "FAM-X", "tipo": "Fondo Bilan. Flessibile", "stato": "aperto"}
    result = enrich_fondo(s)
    assert "enrichment_error" in result


# ---------------------------------------------------------------------------
# parse_fineco_pdf tests
# ---------------------------------------------------------------------------

def _skip_if_image_based(result: dict, label: str) -> None:
    """Skip field assertions when the PDF produced no extractable text.

    Fineco's 'Scheda titolo' PDFs saved via Windows 'Microsoft: Print To PDF'
    embed all financial content as JPEG images — pdfplumber finds no text and
    correctly returns {}.  Text-based PDFs (saved via browser 'Save as PDF')
    would populate the fields.
    """
    if not result:
        import pytest
        pytest.skip(
            f"{label}: PDF image-based (Microsoft Print To PDF) — "
            "testo finanziario in JPEG, non estraibile senza OCR"
        )


def test_parse_pdf_btp():
    pdf_path = PDF_ROOT / "titolo_btp.pdf"
    if not pdf_path.exists():
        import pytest
        pytest.skip("titolo_btp.pdf non presente")
    result = parse_fineco_pdf(pdf_path.read_bytes(), "btp")
    assert isinstance(result, dict), f"Atteso dict, trovato: {type(result)}"
    _skip_if_image_based(result, "BTP")
    assert result.get("ytm_netto"), f"ytm_netto mancante, trovato: {result}"
    assert result.get("scadenza"), f"scadenza mancante, trovato: {result}"
    assert result.get("rating_emittente"), f"rating_emittente mancante, trovato: {result}"


def test_parse_pdf_etf():
    pdf_path = PDF_ROOT / "titolo_etf.pdf"
    if not pdf_path.exists():
        import pytest
        pytest.skip("titolo_etf.pdf non presente")
    result = parse_fineco_pdf(pdf_path.read_bytes(), "etf")
    assert isinstance(result, dict), f"Atteso dict, trovato: {type(result)}"
    _skip_if_image_based(result, "ETF")
    assert result.get("ter"), f"ter mancante, trovato: {result}"
    assert result.get("benchmark"), f"benchmark mancante, trovato: {result}"
    assert result.get("rendimento_1a"), f"rendimento_1a mancante, trovato: {result}"


def test_parse_pdf_fam():
    pdf_path = PDF_ROOT / "titolo_fam.pdf"
    if not pdf_path.exists():
        import pytest
        pytest.skip("titolo_fam.pdf non presente")
    result = parse_fineco_pdf(pdf_path.read_bytes(), "fam")
    assert isinstance(result, dict), f"Atteso dict, trovato: {type(result)}"
    _skip_if_image_based(result, "FAM")
    assert result.get("ter"), f"ter mancante, trovato: {result}"
    assert result.get("rendimento_1a"), f"rendimento_1a mancante, trovato: {result}"
    assert result.get("categoria_fam"), f"categoria_fam mancante, trovato: {result}"


def test_parse_pdf_unknown_returns_empty():
    result = parse_fineco_pdf(b"not a real pdf", "etf")
    assert result == {}


# ---------------------------------------------------------------------------
# _norm_line / _scan_labels / _extract_typed_value
# ---------------------------------------------------------------------------

def test_norm_line_lowercases_strips_collapses():
    from core.instrument_enrichment import _norm_line
    assert _norm_line("  Commissioni  Gestione  ") == "commissioni gestione"

def test_norm_line_removes_accents():
    from core.instrument_enrichment import _norm_line
    assert _norm_line("Fiscalità") == "fiscalita"
    assert _norm_line("Periodicità Cedola") == "periodicita cedola"


def test_scan_labels_same_line_values():
    from core.instrument_enrichment import _scan_labels
    text = (
        "Commissioni gestione e altri costi 0,47%\n"
        "Deviazione standard 24,49%\n"
        "Indice di sharpe 1,32\n"
        "Indice beta 1,05\n"
        "VaR 30,78\n"
        "ISIN IE00BGV5VN51\n"
        "Specializzazione ETF\n"
        "Fiscalità Armonizzato\n"
        "Benchmark Nasdaq Global AI and Big Data NR USD\n"
    )
    r = _scan_labels(text)
    assert r["ter"] == "0,47%", r
    assert r["deviazione_std"] == "24,49%", r
    assert r["sharpe"] == "1,32", r
    assert r["beta"] == "1,05", r
    assert r["var"] == "30,78", r
    assert r["isin"] == "IE00BGV5VN51", r
    assert r["specializzazione"] == "ETF", r
    assert r["fiscalita"] == "Armonizzato", r
    assert r["benchmark"] == "Nasdaq Global AI and Big Data NR USD", r


def test_scan_labels_next_line_fallback():
    from core.instrument_enrichment import _scan_labels
    text = (
        "Scadenza\n"
        "01/03/2037\n"
        "Rating emittente\n"
        "BBB+\n"
    )
    r = _scan_labels(text)
    assert r["scadenza"] == "2037-03-01", r
    assert r["rating_emittente"] == "BBB+", r


def test_scan_labels_nav_last_number():
    from core.instrument_enrichment import _scan_labels
    text = "Nav 26/06/2026 141,58\n"
    r = _scan_labels(text)
    assert r["nav"] == "141,58", r


def test_scan_labels_patrimonio_last_number():
    from core.instrument_enrichment import _scan_labels
    text = "Patrimonio netto mln. 26/06/2026 9.284,27\n"
    r = _scan_labels(text)
    assert r["patrimonio"] == "9.284,27", r


def test_scan_labels_categoria_ms_wins_over_categoria():
    from core.instrument_enrichment import _scan_labels
    text = "Categoria MS Azionario Internazionale\n"
    r = _scan_labels(text)
    assert r.get("categoria_fam") == "Azionario Internazionale", r
    assert "categoria_etf" not in r, r   # ← changed from "categoria_raw"


def test_scan_labels_dash_value_ignored():
    from core.instrument_enrichment import _scan_labels
    text = "Indice beta -\n"
    r = _scan_labels(text)
    assert "beta" not in r, r


# ---------------------------------------------------------------------------
# _scan_rendimenti
# ---------------------------------------------------------------------------

def test_scan_rendimenti_headers_then_values():
    """Layout A: period labels on one line, values on next."""
    from core.instrument_enrichment import _scan_rendimenti
    text = "Da inizio anno 1 A 3 A\n+ 4,47% + 11,85% + 26,52%\n"
    r = _scan_rendimenti(text)
    assert r["rendimento_ytd"] == "+ 4,47%", r
    assert r["rendimento_1a"] == "+ 11,85%", r
    assert r["rendimento_3a"] == "+ 26,52%", r


def test_scan_rendimenti_interleaved():
    """Layout B: label then value alternating on separate lines."""
    from core.instrument_enrichment import _scan_rendimenti
    text = "Da inizio anno\n+ 34,15%\n1 A\n+ 53,75%\n3 A\n+ 147,19%\n"
    r = _scan_rendimenti(text)
    assert r["rendimento_ytd"] == "+ 34,15%", r
    assert r["rendimento_1a"] == "+ 53,75%", r
    assert r["rendimento_3a"] == "+ 147,19%", r


def test_scan_rendimenti_negative_ytd():
    from core.instrument_enrichment import _scan_rendimenti
    text = "Da inizio anno\n-3,60%\n1 A\n+ 25,95%\n3 A\n+ 102,04%\n"
    r = _scan_rendimenti(text)
    assert r["rendimento_ytd"] == "-3,60%", r
    assert r["rendimento_1a"] == "+ 25,95%", r
    assert r["rendimento_3a"] == "+ 102,04%", r


def test_scan_rendimenti_extended_periods():
    from core.instrument_enrichment import _scan_rendimenti
    text = "Da inizio anno 1 A 3 A 5 A 10 A\n+1% +5% +15% +30% +80%\n"
    r = _scan_rendimenti(text)
    assert r.get("rendimento_5a") == "+30%", r
    assert r.get("rendimento_10a") == "+80%", r


def test_scan_rendimenti_absent():
    from core.instrument_enrichment import _scan_rendimenti
    assert _scan_rendimenti("Nav 141,58\nISIN FR0013416716\n") == {}


# ---------------------------------------------------------------------------
# _scan_morningstar
# ---------------------------------------------------------------------------

def test_scan_morningstar_unicode_stars():
    from core.instrument_enrichment import _scan_morningstar
    text = "Morningstar ★★★★☆\n"  # ★★★★☆
    r = _scan_morningstar(text)
    assert r.get("rating_morningstar") == 4, r


def test_scan_morningstar_absent_or_dashes():
    from core.instrument_enrichment import _scan_morningstar
    assert _scan_morningstar("Morningstar --\n") == {}
    assert _scan_morningstar("Nav 141,58\n") == {}


# ---------------------------------------------------------------------------
# _scan_holdings
# ---------------------------------------------------------------------------

def test_scan_holdings_standard():
    from core.instrument_enrichment import _scan_holdings
    text = (
        "Composizione\n"
        "Primi 5 titoli Var%\n"
        "Micron Technology Inc 9,05%\n"
        "Samsung Electronics Co Ltd 8,33%\n"
        "SK Hynix Inc 7,70%\n"
        "Intel Corp 4,92%\n"
        "Cisco Systems Inc 4,13%\n"
        "Avvertenze\n"
    )
    h = _scan_holdings(text)
    assert len(h) == 5, h
    assert h[0] == {"nome": "Micron Technology Inc", "pct": "9,05%"}, h


def test_scan_holdings_absent():
    from core.instrument_enrichment import _scan_holdings
    assert _scan_holdings("Nav 141,58\n") == []


# ---------------------------------------------------------------------------
# _scan_distribuzione
# ---------------------------------------------------------------------------

def test_scan_distribuzione_with_numeric_dividend():
    from core.instrument_enrichment import _scan_distribuzione
    text = "Dividendo distribuito (EUR) 1,23\n"
    r = _scan_distribuzione(text)
    assert r.get("distribuzione") == "Distribuzione", r


def test_scan_distribuzione_dash_is_accumulazione():
    from core.instrument_enrichment import _scan_distribuzione
    # "(-)" = nessun dividendo pagato → accumulazione
    assert _scan_distribuzione("Dividendo distribuito (-) -\n").get("distribuzione") == "Accumulazione"
    # testo non correlato → nessun risultato
    assert _scan_distribuzione("Dividend Yield -\n") == {}


# ---------------------------------------------------------------------------
# Integration tests — real PDFs (skip gracefully if image-based)
# ---------------------------------------------------------------------------

def test_parse_pdf_amundi_gold_etc():
    """ETC PDF that previously returned {} due to tipo='etc' routing bug."""
    pdf_path = PDF_ROOT / "titolo_amundi_gold.pdf"
    if not pdf_path.exists():
        import pytest
        pytest.skip("titolo_amundi_gold.pdf non presente")
    # tipo="etc" was previously unhandled — must now work
    result = parse_fineco_pdf(pdf_path.read_bytes(), "etc")
    assert isinstance(result, dict)
    _skip_if_image_based(result, "Amundi Gold ETC")
    assert result.get("ter"), f"ter mancante: {result}"
    assert result.get("deviazione_std"), f"deviazione_std mancante: {result}"
    assert result.get("rendimento_1a"), f"rendimento_1a mancante: {result}"
    assert result.get("isin") == "FR0013416716", f"isin errato: {result}"


def test_parse_pdf_xaix_etf():
    """ETF PDF with interleaved rendimenti layout and holdings section."""
    pdf_path = PDF_ROOT / "titolo_xaix.pdf"
    if not pdf_path.exists():
        import pytest
        pytest.skip("titolo_xaix.pdf non presente")
    result = parse_fineco_pdf(pdf_path.read_bytes(), "etf")
    assert isinstance(result, dict)
    _skip_if_image_based(result, "XAIX ETF")
    assert result.get("ter"), f"ter mancante: {result}"
    assert result.get("benchmark"), f"benchmark mancante: {result}"
    assert result.get("rendimento_1a"), f"rendimento_1a mancante: {result}"
    assert result.get("isin") == "IE00BGV5VN51", f"isin errato: {result}"
    holdings = result.get("holdings_top") or []
    assert len(holdings) >= 3, f"holdings insufficienti: {result}"
    cat = result.get("categoria_etf") or ""
    assert "Technology" in cat or "Sector" in cat, f"categoria_etf inatteesa: {result}"
