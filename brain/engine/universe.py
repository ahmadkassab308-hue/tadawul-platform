"""Known Tadawul universe — names, peers, and paths. Documented also in MEMORY.md."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Arabic short names for frequently analysed Saudi listings (MEMORY.md).
NAMES_AR = {
    "2222.SR": "أرامكو السعودية",
    "1120.SR": "مصرف الراجحي",
    "1180.SR": "البنك الأهلي السعودي",
    "1111.SR": "مجموعة تداول السعودية",
    "2010.SR": "سابك",
    "1150.SR": "مصرف الإنماء",
    "7010.SR": "الاتصالات السعودية (اس تي سي)",
    "1211.SR": "معادن",
    "2020.SR": "سابك للمغذيات الزراعية",
    "2082.SR": "أكوا باور",
    "1010.SR": "بنك الرياض",
    "1050.SR": "البنك السعودي الفرنسي",
    "1060.SR": "البنك السعودي الأول",
    "5110.SR": "السعودية للطاقة",
    "2280.SR": "المراعي",
    "4030.SR": "البحري",
    "4190.SR": "جرير",
    "7203.SR": "علم",
    "4263.SR": "سال",
    "4164.SR": "النهدي",
    "1080.SR": "البنك العربي الوطني",
    "1140.SR": "بنك البلاد",
    "1020.SR": "بنك الجزيرة",
    "1030.SR": "بنك الاستثمار",
    "2350.SR": "كيان السعودية",
    "2310.SR": "سبكيم العالمية",
    "7020.SR": "موبايلي",
    "7030.SR": "زين السعودية",
    "2380.SR": "بترو رابغ",
}

# Extra name tokens used to decide whether a news item is actually about the company.
NEWS_ALIASES = {
    "2222.SR": ["aramco", "أرامكو", "saudi aramco", "2222"],
    "1120.SR": ["al rajhi", "alrajhi", "الراجحي", "rajhi", "1120"],
    "1180.SR": ["saudi national bank", "ahli", "الأهلي", "snb", "1180", "البنك الأهلي"],
    "1111.SR": ["tadawul group", "مجموعة تداول", "1111"],
    "2010.SR": ["sabic", "سابك", "2010"],
    "1150.SR": ["alinma", "الإنماء", "الانماء", "1150"],
    "7010.SR": ["stc", "saudi telecom", "الاتصالات", "اس تي سي", "7010"],
    "1211.SR": ["maaden", "معادن", "1211"],
    "2020.SR": ["sabic agri", "المغذيات", "2020"],
    "2082.SR": ["acwa", "أكوا", "اكوا", "2082"],
    "1010.SR": ["riyad bank", "بنك الرياض", "رياض", "1010"],
    "1050.SR": ["banque saudi fransi", "الفرنسي", "bsf", "1050"],
    "1060.SR": ["saudi awwal", "الأول", "sabb", "1060"],
    "5110.SR": ["saudi energy", "saudi electricity", "الكهرباء", "5110"],
    "2280.SR": ["almarai", "المراعي", "2280"],
    "4030.SR": ["bahri", "البحري", "4030"],
    "4190.SR": ["jarir", "جرير", "4190"],
    "7203.SR": ["elm", "علم", "7203"],
    "4263.SR": ["sal saudi", "سال", "4263"],
    "4164.SR": ["nahdi", "النهدي", "4164"],
    "1080.SR": ["arab national bank", "العربي الوطني", "anb", "1080"],
    "1140.SR": ["albilad", "al bilad", "البلاد", "1140"],
}

# Peers used for relative valuation / sector rotation (Yahoo Finance .SR tickers).
SECTOR_PEERS = {
    "Energy": ["2222.SR", "2380.SR"],
    "Financial Services": [
        "1120.SR",
        "1180.SR",
        "1150.SR",
        "1010.SR",
        "1060.SR",
        "1050.SR",
        "1080.SR",
        "1140.SR",
        "1020.SR",
        "1111.SR",
    ],
    "Banks": [
        "1120.SR",
        "1180.SR",
        "1150.SR",
        "1010.SR",
        "1060.SR",
        "1050.SR",
        "1080.SR",
        "1140.SR",
        "1020.SR",
    ],
    "Basic Materials": ["2010.SR", "1211.SR", "2020.SR", "2350.SR", "2310.SR"],
    "Communication Services": ["7010.SR", "7020.SR", "7030.SR"],
    "Utilities": ["5110.SR", "2082.SR"],
    "Consumer Defensive": ["2280.SR"],
    "Industrials": ["4030.SR", "4263.SR"],
    "Consumer Cyclical": ["4190.SR"],
    "Technology": ["7203.SR"],
    "Healthcare": ["4164.SR"],
}

# Oil-price sensitivity used by oil-price-link (qualitative mapping, cited from MEMORY.md).
# +1: rises with oil, -1: falls with oil, 0: weak/unclear — only applied when sector is known.
OIL_SENSITIVITY = {
    "Energy": 1.0,
    "Basic Materials": 0.6,  # petrochemicals / miners: partial
    "Utilities": 0.2,
    "Financial Services": 0.25,
    "Industrials": 0.15,
    "Communication Services": 0.1,
    "Consumer Defensive": -0.1,
    "Consumer Cyclical": 0.1,
    "Technology": 0.05,
    "Healthcare": 0.05,
}

DEFAULT_WATCHLIST = [
    "2222.SR",
    "1180.SR",
    "1120.SR",
    "2010.SR",
    "7010.SR",
    "1211.SR",
    "2082.SR",
    "1150.SR",
    "1010.SR",
    "2020.SR",
    "1060.SR",
    "1050.SR",
    "5110.SR",
    "2280.SR",
    "7203.SR",
    "1080.SR",
    "1140.SR",
    "4030.SR",
    "4164.SR",
    "4263.SR",
]

MACRO_TICKERS = {
    "brent": "BZ=F",
    "wti": "CL=F",
    "tasi": "^TASI.SR",
    "ksa_etf": "KSA",
    "usd_sar": "SAR=X",
}


def name_ar(ticker: str, fallback: str | None = None) -> str:
    return NAMES_AR.get(ticker, fallback or ticker)


def news_aliases(ticker: str, name: str = "") -> list[str]:
    aliases = list(NEWS_ALIASES.get(ticker, []))
    aliases.append(ticker.split(".")[0])
    if name:
        aliases.append(name.lower())
    return [a.lower() for a in aliases if a]


def peers_for(ticker: str, sector: str, industry: str = "") -> list[str]:
    pool: list[str] = []
    if industry and "Bank" in industry:
        pool = list(SECTOR_PEERS.get("Banks", []))
    elif sector in SECTOR_PEERS:
        pool = list(SECTOR_PEERS[sector])
    return [p for p in pool if p != ticker]


# Petrochemical / fertilizer issuers for petrochem-spreads (skip others).
PETROCHEM_TICKERS = {
    "2010.SR",  # SABIC
    "2020.SR",  # SABIC Agri-Nutrients
    "2350.SR",  # Kayan
    "2310.SR",  # Sipchem
    "2380.SR",  # Petro Rabigh
}

# Equity risk premium used ONLY when a live risk-free (SAMA) or a live
# watchlist median earnings yield is available. Never used alone as a discount rate.
# Documented prior — cited from MEMORY.md.
EQUITY_RISK_PREMIUM = 0.05
DCF_GROWTH_CAP = 0.05  # do not plug one-year 40% growth into a Gordon perpetuity

# Market-regime weight multipliers applied in aggregate.weighted_score.
# Keys: "trend", "oscillator", "fundamental", "sentiment", "risk", "other"
# market-regime and performance-auditor and committee are never self-modified.
REGIME_WEIGHTS = {
    "bull": {"trend": 1.15, "oscillator": 0.85, "fundamental": 1.00, "sentiment": 1.05, "risk": 0.95, "other": 1.00},
    "bear": {"trend": 0.90, "oscillator": 0.95, "fundamental": 1.10, "sentiment": 0.95, "risk": 1.20, "other": 1.00},
    "range": {"trend": 0.85, "oscillator": 1.15, "fundamental": 1.10, "sentiment": 0.90, "risk": 1.05, "other": 1.00},
}

TREND_AGENT_IDS = {
    "trend-ema", "trend-sma", "moving-averages-crossover", "adx-dmi",
    "supertrend", "ichimoku", "hull-moving-average", "parabolic-sar",
    "donchian-breakout", "multi-timeframe",
    "candle-structure", "candle-weekly",
}
OSCILLATOR_AGENT_IDS = {
    "rsi", "stochastic", "williams-r", "cci", "bollinger", "mfi",
}

# Minimum scored committee decisions / per-analyst votes before accuracy can change weights.
ACCURACY_MIN_DECISIONS = 5
ACCURACY_MIN_PER_AGENT = 5


def is_bank(sector: str, industry: str) -> bool:
    ind = industry or ""
    sec = sector or ""
    return "Bank" in ind or (sec == "Financial Services" and "Capital Markets" not in ind and "Tadawul" not in ind)


def is_petrochem(ticker: str, sector: str = "", industry: str = "") -> bool:
    if ticker in PETROCHEM_TICKERS:
        return True
    ind = (industry or "").lower()
    return any(s in ind for s in ("chemical", "agricultural input"))
