"""Markets, scan universes and symbol → market mapping for tadawul-web.

Universes are static, liquid large caps per market (documented in README.md).
Abu Dhabi (ADX, .AD) is NOT FOUND on Yahoo Finance in this session — not included.
"""
from __future__ import annotations

import re

MARKETS = {
    "SA": {"name_ar": "السوق السعودية (تداول)", "short": "السعودية", "benchmark": "^TASI.SR", "every_h": 3},
    "US": {"name_ar": "السوق الأمريكية", "short": "أمريكا", "benchmark": "^GSPC", "every_h": 6},
    "EU": {"name_ar": "الأسواق الأوروبية", "short": "أوروبا", "benchmark": "^STOXX50E", "every_h": 8},
    "GULF": {"name_ar": "أسواق الخليج (دبي، قطر، الكويت)", "short": "الخليج", "benchmark": None, "every_h": 8},
    "ASIA": {"name_ar": "الأسواق الآسيوية", "short": "آسيا", "benchmark": "^N225", "every_h": 8},
    "EG": {"name_ar": "البورصة المصرية", "short": "مصر", "benchmark": None, "every_h": 12},
    "CRYPTO": {"name_ar": "العملات المشفرة والسلع", "short": "كريبتو وسلع", "benchmark": None, "every_h": 0},
}

UNIVERSE = {
    "SA": [
        # watchlist.txt + liquid TASI names
        "2222.SR", "1120.SR", "1180.SR", "1111.SR", "2010.SR", "1150.SR", "7010.SR", "1211.SR",
        "2020.SR", "2082.SR", "1010.SR", "1050.SR", "1060.SR", "5110.SR", "2280.SR", "4030.SR",
        "4190.SR", "7203.SR", "4263.SR", "4164.SR", "1080.SR", "1140.SR", "1020.SR", "1030.SR",
        "2350.SR", "2310.SR", "7020.SR", "7030.SR", "2380.SR", "9613.SR", "4071.SR", "4013.SR",
        "4002.SR", "2050.SR", "4001.SR", "4300.SR", "4280.SR", "2290.SR",
    ],
    "US": [
        "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "AVGO", "TSLA", "BRK-B", "JPM",
        "WMT", "LLY", "V", "ORCL", "MA", "NFLX", "XOM", "COST", "JNJ", "HD",
        "PG", "BAC", "ABBV", "PLTR", "KO", "UNH", "AMD", "CSCO", "CVX", "WFC",
        "IBM", "CRM", "MS", "GS", "ABT", "MCD", "PM", "LIN", "GE", "INTU",
        "T", "MRK", "PEP", "DIS", "ADBE", "QCOM", "TXN", "CAT", "NOW", "UBER",
    ],
    "EU": [
        "ASML.AS", "SAP.DE", "MC.PA", "NOVO-B.CO", "NESN.SW", "ROG.SW", "NOVN.SW", "AZN.L",
        "SHEL.L", "HSBA.L", "OR.PA", "SIE.DE", "TTE.PA", "ULVR.L", "ALV.DE", "SAN.PA",
        "AIR.PA", "BP.L", "DTE.DE", "RMS.PA", "IBE.MC", "ITX.MC", "ENEL.MI", "BNP.PA", "RHM.DE",
    ],
    "GULF": [
        "EMAAR.AE", "EMIRATESNBD.AE", "DIB.AE", "DEWA.AE", "SALIK.AE", "DU.AE",
        "QNBK.QA", "IQCD.QA", "QIBK.QA", "ORDS.QA",
        "NBK.KW", "KFH.KW", "ZAIN.KW", "BOUBYAN.KW",
    ],
    "ASIA": [
        "7203.T", "6758.T", "9984.T", "8306.T", "6861.T", "0700.HK", "9988.HK", "1299.HK",
        "0005.HK", "3690.HK", "005930.KS", "000660.KS", "2330.TW", "2317.TW", "RELIANCE.NS",
        "TCS.NS", "HDFCBANK.NS", "INFY.NS", "D05.SI", "BHP.AX", "CBA.AX",
    ],
    "EG": ["COMI.CA", "TMGH.CA", "EAST.CA", "SWDY.CA", "HRHO.CA", "ETEL.CA"],
    "CRYPTO": [],  # chart/quote/analysis on demand only, not scanned
}

POPULAR = {
    "CRYPTO": ["BTC-USD", "ETH-USD", "SOL-USD", "GC=F", "SI=F", "CL=F", "BZ=F"],
}

EU_SUF = {"L", "PA", "DE", "AS", "SW", "MC", "MI", "CO", "ST", "HE", "BR", "OL", "LS", "VI", "IR", "F", "XC", "IL"}
ASIA_SUF = {"T", "HK", "KS", "KQ", "TW", "TWO", "NS", "BO", "SI", "AX", "SS", "SZ", "JK", "BK", "KL", "NZ"}
GULF_SUF = {"AE", "QA", "KW", "AD", "BH", "OM"}

SYMBOL_RE = re.compile(r"^[A-Za-z0-9.\-=^&]{1,24}$")


def valid_symbol(sym: str) -> bool:
    return bool(sym) and bool(SYMBOL_RE.match(sym))


def market_of(sym: str) -> str:
    s = sym.upper()
    if s.endswith(".SR") or s.isdigit():
        return "SA"
    if s.endswith("-USD") or s.endswith("=F") or s.endswith("=X"):
        return "CRYPTO"
    if "." in s:
        suf = s.rsplit(".", 1)[1]
        if suf in GULF_SUF:
            return "GULF"
        if suf == "CA":
            return "EG"
        if suf in EU_SUF:
            return "EU"
        if suf in ASIA_SUF:
            return "ASIA"
    return "US"
