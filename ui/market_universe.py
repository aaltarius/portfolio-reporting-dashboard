"""Universo mercati usato da striscia Home e pagina Mercati."""
from __future__ import annotations

from datetime import time


MARKET_UNIVERSE_ITEMS: list[dict[str, object]] = [
    # Azionario globale
    {"section": "Azionario globale", "flag": "🌍", "label": "MSCI World", "ticker": "URTH", "aliases": ("URTH", "IWDA.AS", "SWDA.MI"), "tz": "America/New_York", "open": time(9, 30), "close": time(16, 0), "priority": 1},
    {"section": "Azionario globale", "flag": "🌍", "label": "ACWI", "ticker": "ACWI", "aliases": ("ACWI", "IUSQ.DE"), "tz": "America/New_York", "open": time(9, 30), "close": time(16, 0), "priority": 1},
    {"section": "Azionario globale", "flag": "🌍", "label": "Emerging Markets", "ticker": "EEM", "aliases": ("EEM", "IEMA.AS", "EIMI.MI"), "tz": "America/New_York", "open": time(9, 30), "close": time(16, 0), "priority": 1},
    {"section": "Azionario globale", "flag": "🌍", "label": "EAFE", "ticker": "EFA", "aliases": ("EFA",), "tz": "America/New_York", "open": time(9, 30), "close": time(16, 0), "priority": 2},

    # USA
    {"section": "USA", "flag": "🇺🇸", "label": "S&P 500", "ticker": "^GSPC", "aliases": ("^GSPC", "SPY"), "tz": "America/New_York", "open": time(9, 30), "close": time(16, 0), "priority": 1},
    {"section": "USA", "flag": "🇺🇸", "label": "Nasdaq", "ticker": "^IXIC", "aliases": ("^IXIC", "QQQ"), "tz": "America/New_York", "open": time(9, 30), "close": time(16, 0), "priority": 1},
    {"section": "USA", "flag": "🇺🇸", "label": "Nasdaq 100", "ticker": "^NDX", "aliases": ("^NDX", "QQQ"), "tz": "America/New_York", "open": time(9, 30), "close": time(16, 0), "priority": 1},
    {"section": "USA", "flag": "🇺🇸", "label": "Dow Jones", "ticker": "^DJI", "aliases": ("^DJI", "DIA"), "tz": "America/New_York", "open": time(9, 30), "close": time(16, 0), "priority": 1},
    {"section": "USA", "flag": "🇺🇸", "label": "Russell 2000", "ticker": "^RUT", "aliases": ("^RUT", "IWM"), "tz": "America/New_York", "open": time(9, 30), "close": time(16, 0), "priority": 2},

    # Europa
    {"section": "Europa", "flag": "🇪🇺", "label": "Euro Stoxx 50", "ticker": "^STOXX50E", "aliases": ("^STOXX50E", "FEZ"), "tz": "Europe/Paris", "open": time(9, 0), "close": time(17, 30), "priority": 1},
    {"section": "Europa", "flag": "🇪🇺", "label": "STOXX Europe 600", "ticker": "^STOXX", "aliases": ("^STOXX", "EXSA.DE"), "tz": "Europe/Paris", "open": time(9, 0), "close": time(17, 30), "priority": 1},
    {"section": "Europa", "flag": "🇮🇹", "label": "FTSE MIB", "ticker": "FTSEMIB.MI", "aliases": ("FTSEMIB.MI",), "tz": "Europe/Rome", "open": time(9, 0), "close": time(17, 30), "priority": 1},
    {"section": "Europa", "flag": "🇩🇪", "label": "DAX", "ticker": "^GDAXI", "aliases": ("^GDAXI", "DAX", "EXS1.DE"), "tz": "Europe/Berlin", "open": time(9, 0), "close": time(17, 30), "priority": 1},
    {"section": "Europa", "flag": "🇫🇷", "label": "CAC 40", "ticker": "^FCHI", "aliases": ("^FCHI", "EWQ"), "tz": "Europe/Paris", "open": time(9, 0), "close": time(17, 30), "priority": 1},
    {"section": "Europa", "flag": "🇬🇧", "label": "FTSE 100", "ticker": "^FTSE", "aliases": ("^FTSE", "ISF.L", "VUKE.L", "EWU"), "tz": "Europe/London", "open": time(8, 0), "close": time(16, 30), "priority": 1},
    {"section": "Europa", "flag": "🇪🇸", "label": "IBEX 35", "ticker": "^IBEX", "aliases": ("^IBEX", "EWP"), "tz": "Europe/Madrid", "open": time(9, 0), "close": time(17, 30), "priority": 2},
    {"section": "Europa", "flag": "🇨🇭", "label": "SMI", "ticker": "^SSMI", "aliases": ("^SSMI", "EWL"), "tz": "Europe/Zurich", "open": time(9, 0), "close": time(17, 30), "priority": 2},
    {"section": "Europa", "flag": "🇳🇱", "label": "AEX", "ticker": "^AEX", "aliases": ("^AEX", "EWN"), "tz": "Europe/Amsterdam", "open": time(9, 0), "close": time(17, 30), "priority": 2},

    # Asia-Pacifico
    {"section": "Asia-Pacifico", "flag": "🇯🇵", "label": "Nikkei 225", "ticker": "^N225", "aliases": ("^N225", "EWJ"), "tz": "Asia/Tokyo", "open": time(9, 0), "close": time(15, 0), "priority": 1},
    {"section": "Asia-Pacifico", "flag": "🇭🇰", "label": "Hang Seng", "ticker": "^HSI", "aliases": ("^HSI", "EWH"), "tz": "Asia/Hong_Kong", "open": time(9, 30), "close": time(16, 0), "priority": 1},
    {"section": "Asia-Pacifico", "flag": "🇨🇳", "label": "Shanghai Composite", "ticker": "000001.SS", "aliases": ("000001.SS", "ASHR"), "tz": "Asia/Shanghai", "open": time(9, 30), "close": time(15, 0), "priority": 1},
    {"section": "Asia-Pacifico", "flag": "🇨🇳", "label": "CSI 300", "ticker": "000300.SS", "aliases": ("000300.SS", "ASHR"), "tz": "Asia/Shanghai", "open": time(9, 30), "close": time(15, 0), "priority": 2},
    {"section": "Asia-Pacifico", "flag": "🇮🇳", "label": "Nifty 50", "ticker": "^NSEI", "aliases": ("^NSEI", "INDY"), "tz": "Asia/Kolkata", "open": time(9, 15), "close": time(15, 30), "priority": 1},
    {"section": "Asia-Pacifico", "flag": "🇰🇷", "label": "KOSPI", "ticker": "^KS11", "aliases": ("^KS11", "EWY"), "tz": "Asia/Seoul", "open": time(9, 0), "close": time(15, 30), "priority": 2},
    {"section": "Asia-Pacifico", "flag": "🇹🇼", "label": "Taiwan Weighted", "ticker": "^TWII", "aliases": ("^TWII", "EWT"), "tz": "Asia/Taipei", "open": time(9, 0), "close": time(13, 30), "priority": 2},
    {"section": "Asia-Pacifico", "flag": "🇦🇺", "label": "ASX 200", "ticker": "^AXJO", "aliases": ("^AXJO", "EWA"), "tz": "Australia/Sydney", "open": time(10, 0), "close": time(16, 0), "priority": 2},

    # Tassi/Bond
    {"section": "Tassi/Bond", "flag": "🇺🇸", "label": "US 10Y", "ticker": "^TNX", "aliases": ("^TNX",), "tz": "America/New_York", "open": time(8, 0), "close": time(17, 0), "priority": 1},
    {"section": "Tassi/Bond", "flag": "🇺🇸", "label": "US 2Y", "ticker": "^IRX", "aliases": ("^IRX",), "tz": "America/New_York", "open": time(8, 0), "close": time(17, 0), "priority": 1},
    {"section": "Tassi/Bond", "flag": "🇺🇸", "label": "Treasury 20+ ETF", "ticker": "TLT", "aliases": ("TLT",), "tz": "America/New_York", "open": time(9, 30), "close": time(16, 0), "priority": 1},
    {"section": "Tassi/Bond", "flag": "🇪🇺", "label": "Euro Gov Bond", "ticker": "IBGM.MI", "aliases": ("IBGM.MI", "IEGA.AS"), "tz": "Europe/Rome", "open": time(9, 0), "close": time(17, 30), "priority": 1},
    {"section": "Tassi/Bond", "flag": "🇺🇸", "label": "High Yield USA", "ticker": "HYG", "aliases": ("HYG", "JNK"), "tz": "America/New_York", "open": time(9, 30), "close": time(16, 0), "priority": 2},

    # Materie prime
    {"section": "Materie prime", "flag": "🟡", "label": "Oro", "ticker": "GC=F", "aliases": ("GC=F", "GLD"), "tz": "America/New_York", "open": time(8, 20), "close": time(17, 0), "priority": 1},
    {"section": "Materie prime", "flag": "⚪", "label": "Argento", "ticker": "SI=F", "aliases": ("SI=F", "SLV"), "tz": "America/New_York", "open": time(8, 25), "close": time(17, 0), "priority": 2},
    {"section": "Materie prime", "flag": "🛢️", "label": "WTI", "ticker": "CL=F", "aliases": ("CL=F", "USO"), "tz": "America/New_York", "open": time(9, 0), "close": time(17, 0), "priority": 1},
    {"section": "Materie prime", "flag": "🛢️", "label": "Brent", "ticker": "BZ=F", "aliases": ("BZ=F", "BNO"), "tz": "Europe/London", "open": time(8, 0), "close": time(18, 0), "priority": 1},
    {"section": "Materie prime", "flag": "🟠", "label": "Rame", "ticker": "HG=F", "aliases": ("HG=F", "CPER"), "tz": "America/New_York", "open": time(8, 0), "close": time(17, 0), "priority": 2},

    # Valute
    {"section": "Valute", "flag": "💶", "label": "EUR/USD", "ticker": "EURUSD=X", "aliases": ("EURUSD=X",), "tz": "Europe/Rome", "open": time(0, 0), "close": time(23, 59), "priority": 1},
    {"section": "Valute", "flag": "💶", "label": "EUR/GBP", "ticker": "EURGBP=X", "aliases": ("EURGBP=X",), "tz": "Europe/Rome", "open": time(0, 0), "close": time(23, 59), "priority": 1},
    {"section": "Valute", "flag": "🇬🇧", "label": "GBP/USD", "ticker": "GBPUSD=X", "aliases": ("GBPUSD=X",), "tz": "Europe/London", "open": time(0, 0), "close": time(23, 59), "priority": 2},
    {"section": "Valute", "flag": "💶", "label": "EUR/JPY", "ticker": "EURJPY=X", "aliases": ("EURJPY=X",), "tz": "Europe/Rome", "open": time(0, 0), "close": time(23, 59), "priority": 2},
    {"section": "Valute", "flag": "💵", "label": "Dollar Index", "ticker": "DX-Y.NYB", "aliases": ("DX-Y.NYB", "UUP"), "tz": "America/New_York", "open": time(8, 0), "close": time(17, 0), "priority": 1},

    # Rischio
    {"section": "Rischio", "flag": "⚠️", "label": "VIX", "ticker": "^VIX", "aliases": ("^VIX", "VXX"), "tz": "America/New_York", "open": time(9, 30), "close": time(16, 15), "priority": 1},
    {"section": "Rischio", "flag": "⚠️", "label": "MOVE proxy", "ticker": "MOVE", "aliases": ("MOVE", "TLT"), "tz": "America/New_York", "open": time(9, 30), "close": time(16, 0), "priority": 2},
    {"section": "Rischio", "flag": "₿", "label": "Bitcoin", "ticker": "BTC-USD", "aliases": ("BTC-USD",), "tz": "UTC", "open": time(0, 0), "close": time(23, 59), "priority": 2},
]


MARKET_SECTION_ORDER = [
    "Azionario globale",
    "USA",
    "Europa",
    "Asia-Pacifico",
    "Tassi/Bond",
    "Materie prime",
    "Valute",
    "Rischio",
]


MARKET_TAPE_LABELS = {
    "FTSE MIB",
    "Euro Stoxx 50",
    "DAX",
    "CAC 40",
    "FTSE 100",
    "S&P 500",
    "Nasdaq",
    "Dow Jones",
    "Nikkei 225",
    "Hang Seng",
    "EUR/GBP",
}

MARKET_TAPE_ITEMS = [item for item in MARKET_UNIVERSE_ITEMS if item["label"] in MARKET_TAPE_LABELS]
