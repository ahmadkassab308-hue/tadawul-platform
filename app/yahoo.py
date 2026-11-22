"""Server-side Yahoo Finance access (no CORS in the browser): quote, OHLC chart, symbol search.
Also maps Yahoo symbols to TradingView symbols (EXCHANGE:TICKER) for official TradingView widgets/links."""
from __future__ import annotations

import json
import time
import urllib.parse
import threading

from curl_cffi import requests as _cr

from .markets import market_of

_tls = threading.local()


def _session():
    s = getattr(_tls, "s", None)
    if s is None:
        s = _tls.s = _cr.Session(impersonate="chrome")
    return s

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36"}
_cache: dict[str, tuple[float, object]] = {}


def _get_json(url: str, ttl: int = 20):
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    last = None
    for host in ("query1", "query2"):
        u = url.replace("https://query1.", f"https://{host}.")
        try:
            r = _session().get(u, timeout=12)
            if r.status_code == 404:
                data = r.json()
                _cache[url] = (time.time(), data)
                return data
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}")
            data = r.json()
            _cache[url] = (time.time(), data)
            return data
        except Exception as exc:  # try the other host
            last = exc
    raise RuntimeError(f"Yahoo Finance غير متاح: {last}")


TF = {  # timeframe -> (range, interval)
    "1D": ("1d", "5m"), "1W": ("5d", "30m"), "1M": ("1mo", "60m"),
    "1Y": ("1y", "1d"), "5Y": ("5y", "1wk"), "MAX": ("max", "1mo"),
}


def chart(symbol: str, tf: str = "1Y") -> dict:
    rng, itv = TF.get(tf, TF["1Y"])
    q = urllib.parse.quote(symbol)
    data = _get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{q}?range={rng}&interval={itv}&includePrePost=false",
                     ttl=30 if tf in ("1D", "1W") else 300)
    res = (data.get("chart") or {}).get("result") or []
    if not res and tf == "1D":
        return chart(symbol, "1W")
    if not res:
        raise RuntimeError("NOT FOUND — لا بيانات أسعار لهذا الرمز على Yahoo Finance")
    r = res[0]
    meta = r.get("meta") or {}
    ts = r.get("timestamp") or []
    qd = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    bars = []
    for i, t in enumerate(ts):
        o, h, l, c, v = (qd.get(k, [None] * len(ts))[i] for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, l, c):
            continue
        bars.append({"time": int(t), "open": o, "high": h, "low": l, "close": c, "volume": v or 0})
    if tf == "1D" and len(bars) < 3:
        return chart(symbol, "1W")
    return {"symbol": symbol, "tf": tf, "interval": itv, "intraday": itv.endswith("m"),
            "tz": meta.get("exchangeTimezoneName"), "bars": bars, "meta": _meta(meta)}


def _meta(meta: dict) -> dict:
    reg = ((meta.get("currentTradingPeriod") or {}).get("regular")) or {}
    now = time.time()
    is_open = bool(reg) and reg.get("start", 0) <= now <= reg.get("end", 0)
    price = meta.get("regularMarketPrice")
    prev = meta.get("previousClose") or meta.get("chartPreviousClose")
    chg = (price - prev) if (price is not None and prev) else None
    return {
        "symbol": meta.get("symbol"), "name": meta.get("longName") or meta.get("shortName") or meta.get("symbol"),
        "currency": meta.get("currency"), "exchange": meta.get("exchangeName"),
        "exchange_name": meta.get("fullExchangeName"), "type": meta.get("instrumentType"),
        "price": price, "prev_close": prev, "change": chg,
        "change_pct": (chg / prev * 100) if (chg is not None and prev) else None,
        "day_high": meta.get("regularMarketDayHigh"), "day_low": meta.get("regularMarketDayLow"),
        "volume": meta.get("regularMarketVolume"), "high52": meta.get("fiftyTwoWeekHigh"),
        "low52": meta.get("fiftyTwoWeekLow"), "market_time": meta.get("regularMarketTime"),
        "tz": meta.get("exchangeTimezoneName"), "is_open": is_open,
        "session_start": reg.get("start"), "session_end": reg.get("end"),
    }


def quote(symbol: str) -> dict:
    q = urllib.parse.quote(symbol)
    data = _get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{q}?range=1d&interval=5m", ttl=20)
    res = (data.get("chart") or {}).get("result") or []
    if not res:
        raise RuntimeError("NOT FOUND — رمز غير معروف على Yahoo Finance")
    m = _meta(res[0].get("meta") or {})
    m["market"] = market_of(symbol)
    m["tv_symbol"] = tv_symbol(symbol, m.get("exchange"))
    m["source"] = "Yahoo Finance / v8 chart meta"
    return m


def search(q: str) -> list[dict]:
    if not q.strip():
        return []
    url = "https://query1.finance.yahoo.com/v1/finance/search?" + urllib.parse.urlencode(
        {"q": q, "quotesCount": 12, "newsCount": 0, "listsCount": 0, "enableFuzzyQuery": "true"})
    data = _get_json(url, ttl=600)
    out = []
    for x in data.get("quotes") or []:
        sym = x.get("symbol")
        if not sym or x.get("quoteType") not in ("EQUITY", "ETF", "CRYPTOCURRENCY", "FUTURE", "INDEX", "CURRENCY", "MUTUALFUND"):
            continue
        out.append({"symbol": sym, "name": x.get("longname") or x.get("shortname") or sym,
                    "exchange": x.get("exchDisp") or x.get("exchange"), "type": x.get("quoteType"),
                    "market": market_of(sym), "tv_symbol": tv_symbol(sym, x.get("exchange"))})
    return out


# ---------- TradingView symbol mapping (public symbol format EXCHANGE:TICKER) ----------
SUFFIX_TV = {
    "SR": "TADAWUL", "AE": "DFM", "AD": "ADX", "QA": "QSE", "KW": "KSE", "CA": "EGX",
    "T": "TSE", "HK": "HKEX", "KS": "KRX", "KQ": "KRX", "TW": "TWSE", "TWO": "TPEX", "NS": "NSE", "BO": "BSE",
    "SI": "SGX", "AX": "ASX", "L": "LSE", "PA": "EURONEXT", "AS": "EURONEXT", "BR": "EURONEXT", "LS": "EURONEXT",
    "DE": "XETR", "F": "FWB", "SW": "SIX", "MC": "BME", "MI": "MIL", "CO": "OMXCOP", "ST": "OMXSTO",
    "HE": "OMXHEX", "OL": "OSL", "VI": "VIE", "IR": "EURONEXT", "SS": "SSE", "SZ": "SZSE", "TO": "TSX", "V": "TSXV",
}
US_EX = {"NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NAS": "NASDAQ", "NasdaqGS": "NASDAQ",
         "NYQ": "NYSE", "NYSE": "NYSE", "ASE": "AMEX", "PCX": "AMEX", "BTS": "CBOE", "PNK": "OTC", "OQX": "OTC"}
SPECIAL = {"GC=F": "COMEX:GC1!", "SI=F": "COMEX:SI1!", "CL=F": "NYMEX:CL1!", "BZ=F": "NYMEX:BB1!",
           "NG=F": "NYMEX:NG1!", "^GSPC": "SP:SPX", "^IXIC": "NASDAQ:IXIC", "^DJI": "DJ:DJI",
           "^TASI.SR": "TADAWUL:TASI", "^N225": "TVC:NI225", "^HSI": "TVC:HSI", "^STOXX50E": "TVC:SX5E"}


def tv_symbol(sym: str, yahoo_exchange: str | None = None) -> str:
    s = sym.upper()
    if s in SPECIAL:
        return SPECIAL[s]
    if s.endswith("-USD"):
        return "BINANCE:" + s[:-4] + "USDT" if s[:-4] not in ("BTC", "ETH") else "BITSTAMP:" + s[:-4] + "USD"
    if "." in s and not s.startswith("^"):
        base, suf = s.rsplit(".", 1)
        ex = SUFFIX_TV.get(suf)
        if ex:
            if suf == "HK":
                base = base.lstrip("0") or "0"
            return f"{ex}:{base.replace('-', '_')}"
    base = s.replace("-", ".")
    ex = US_EX.get(yahoo_exchange or "")
    return f"{ex}:{base}" if ex else base
