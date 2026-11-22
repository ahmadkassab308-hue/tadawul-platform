"""Fetch live market data. On failure, return None and record a note — never invent values."""
from __future__ import annotations

import json
import urllib.request
from typing import Optional

import pandas as pd
import yfinance as yf

from .indicators import compute_all
from .models import MarketData
from .universe import DEFAULT_WATCHLIST, MACRO_TICKERS, name_ar, news_aliases, peers_for
from . import sources


def _empty_to_none(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    return df


def _history(ticker: str, period: str = "2y") -> Optional[pd.DataFrame]:
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period=period, auto_adjust=True)
        if hist is None or hist.empty:
            return None
        # Ensure expected columns and drop rows without a close.
        for col in ("Open", "High", "Low", "Close", "Volume"):
            if col not in hist.columns:
                return None
        hist = hist.dropna(subset=["Close"])
        if hist.empty:
            return None
        return hist
    except Exception:
        return None


def _info(ticker: str) -> dict:
    try:
        info = yf.Ticker(ticker).info or {}
        return info if isinstance(info, dict) else {}
    except Exception:
        return {}


def _news(ticker: str) -> list:
    try:
        news = yf.Ticker(ticker).news or []
        return news if isinstance(news, list) else []
    except Exception:
        return []


def _statement(ticker: str, attr: str) -> Optional[pd.DataFrame]:
    try:
        df = getattr(yf.Ticker(ticker), attr)
        return _empty_to_none(df)
    except Exception:
        return None


def try_sama_rates() -> Optional[dict]:
    """Best-effort free fetch of Saudi policy / money-market rates.
    Returns None if no trusted source responds with parseable data.
    """
    # FRED series for Saudi Arabia official / money-market rates (CSV).
    # If the series is missing or the request fails, we return None (NOT FOUND).
    candidates = [
        # IMF / IFS deposit or policy-adjacent series sometimes mirrored on FRED
        "https://fred.stlouisfed.org/graph/fredgraph.csv?id=IRSTCI01SAM156N",
        "https://fred.stlouisfed.org/graph/fredgraph.csv?id=INTDSRSAM193N",
    ]
    for url in candidates:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "tadawul-brain/1.0"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            if len(lines) < 2 or "DATE" not in lines[0].upper():
                continue
            # last non-missing observation
            last = None
            for ln in reversed(lines[1:]):
                parts = ln.split(",")
                if len(parts) >= 2 and parts[1] not in ("", ".", "ND"):
                    try:
                        last = {"date": parts[0], "value": float(parts[1]), "source_url": url}
                        break
                    except ValueError:
                        continue
            if last:
                last["source"] = "FRED CSV " + url.split("id=")[-1]
                return last
        except Exception:
            continue
    return None



def _yf_safe(ticker: str, attr: str, default=None):
    try:
        obj = getattr(yf.Ticker(ticker), attr)
        return obj
    except Exception:
        return default


def fetch_earnings_bundle(ticker: str) -> dict:
    out = {"earnings_dates": None, "earnings_history": None, "calendar": {}, "dividends": None, "notes": []}
    tk = yf.Ticker(ticker)
    try:
        df = tk.get_earnings_dates(limit=12)
        out["earnings_dates"] = _empty_to_none(df)
    except Exception as exc:
        out["notes"].append(f"earnings_dates: {type(exc).__name__}")
        try:
            out["earnings_dates"] = _empty_to_none(getattr(tk, "earnings_dates", None))
        except Exception as exc2:
            out["notes"].append(f"earnings_dates retry: {type(exc2).__name__}")
    try:
        out["earnings_history"] = _empty_to_none(tk.earnings_history)
    except Exception as exc:
        out["notes"].append(f"earnings_history: {type(exc).__name__}")
    try:
        cal = tk.calendar
        out["calendar"] = cal if isinstance(cal, dict) else {}
    except Exception as exc:
        out["notes"].append(f"calendar: {type(exc).__name__}")
    try:
        div = tk.dividends
        if div is not None and len(div):
            out["dividends"] = div
    except Exception as exc:
        out["notes"].append(f"dividends: {type(exc).__name__}")
    return out


def _watchlist_bundle(tickers: list[str], period: str = "1y") -> tuple[dict, dict]:
    hist = _peer_closes(tickers, period)
    pes = {}
    # lightweight: only fill PE when already cheap? Fetching info for 20 names is ok but slower.
    # Skip here; PE median for DCF is collected on demand in the analyst if watchlist_pe empty,
    # or we grab from a single batch below only for tickers we already touch.
    return hist, pes


def fetch_macro() -> dict:
    """Fetch shared macro series once per run."""
    notes = []
    wl = list(DEFAULT_WATCHLIST)
    wl_hist, wl_pe = _watchlist_bundle(wl, "1y")
    # cheap PE pass: use yf.download already done; info is heavier — cap to 20
    for tkr in wl[:8]:
        try:
            pe = (yf.Ticker(tkr).info or {}).get("trailingPE")
            if pe is not None:
                pes = float(pe)
                if pes == pes and pes > 0:
                    wl_pe[tkr] = pes
        except Exception:
            continue
    flows = sources.try_investor_flows()
    petro = sources.try_petrochem_prices()
    out = {
        "brent": _history(MACRO_TICKERS["brent"], "1y"),
        "wti": _history(MACRO_TICKERS["wti"], "1y"),
        "tasi_hist": _history(MACRO_TICKERS["tasi"], "2y"),
        "tasi_spot": _info(MACRO_TICKERS["tasi"]),
        "ksa_etf": _history(MACRO_TICKERS["ksa_etf"], "2y"),
        "usd_sar": _history(MACRO_TICKERS["usd_sar"], "1y"),
        "sama": try_sama_rates(),
        "watchlist_hist": wl_hist,
        "watchlist_pe": wl_pe,
        "investor_flows": flows,
        "petrochem": petro,
        "notes": notes,
    }
    if not flows or not flows.get("data"):
        notes.append("تقارير تدفقات المستثمرين الأسبوعية من السوق المالية غير متاحة في هذه الجلسة (غالباً HTTP 403).")
    if not petro or not petro.get("data"):
        notes.append("لا مصدر مجاني موثوق لفروقات أسعار المنتجات/اللقيم البتروكيماوية في هذه الجلسة.")
    if out["tasi_hist"] is None or len(out["tasi_hist"]) < 5:
        notes.append(
            "سلسلة تاريخية كاملة لمؤشر تاسي (^TASI.SR) غير متاحة عبر Yahoo Finance "
            "(غالباً نقطة واحدة فقط). سيُستخدم السعر الفوري ونطاق 52 أسبوعاً ومتوسط 50/200 يوم من info، "
            "وصندوق KSA كوكيل لاتجاه السوق عند الحاجة، مع ذكر المصدر."
        )
    if out["sama"] is None:
        notes.append("لم يُعثر على مصدر مجاني موثوق لمعدلات ساما/سايبور في هذه الجلسة.")
    if out["brent"] is None:
        notes.append("تعذر جلب سعر خام برنت (BZ=F).")
    if out["ksa_etf"] is None:
        notes.append("تعذر جلب صندوق KSA (وكيل سوق السعودية).")
    out["notes"] = notes
    return out


def _peer_closes(tickers: list[str], period: str = "6mo") -> dict:
    if not tickers:
        return {}
    try:
        data = yf.download(
            tickers,
            period=period,
            progress=False,
            auto_adjust=True,
            threads=True,
            group_by="ticker",
        )
    except Exception:
        data = None
    closes = {}
    if data is None or data.empty:
        # fall back to one-by-one
        for t in tickers:
            h = _history(t, period)
            if h is not None:
                closes[t] = h["Close"]
        return closes
    # yfinance shape differs for 1 vs many tickers
    if len(tickers) == 1:
        t = tickers[0]
        if "Close" in data.columns:
            s = data["Close"].dropna()
            if len(s):
                closes[t] = s
        return closes
    for t in tickers:
        try:
            if isinstance(data.columns, pd.MultiIndex):
                # group_by=ticker -> (ticker, field) or (field, ticker)
                if t in data.columns.get_level_values(0):
                    s = data[t]["Close"].dropna()
                elif "Close" in data.columns.get_level_values(0) and t in data.columns.get_level_values(1):
                    s = data["Close"][t].dropna()
                else:
                    continue
            else:
                continue
            if len(s):
                closes[t] = s
        except Exception:
            continue
    return closes


def fetch_stock(ticker: str, macro: Optional[dict] = None, with_peers: bool = True,
                saudi_sources: Optional[bool] = None) -> MarketData:
    """saudi_sources=None means auto: only .SR tickers query saudiexchange.sa (announcements,
    foreign ownership). Non-Saudi tickers skip them (NOT FOUND, not applicable) — used by tadawul-web."""
    ticker = ticker.strip().upper()
    if ticker.isdigit():
        ticker = ticker + ".SR"
    if saudi_sources is None:
        saudi_sources = ticker.endswith(".SR")
    notes = []
    hist = _history(ticker, "2y")
    if hist is None:
        # try 6 months as a fallback window
        hist = _history(ticker, "6mo")
        if hist is None:
            raise RuntimeError(f"NOT FOUND — تعذر جلب أسعار {ticker} من Yahoo Finance.")
        notes.append("تم جلب 6 أشهر فقط بعد فشل نافذة سنتين.")
    info = _info(ticker)
    news = _news(ticker)
    financials = _statement(ticker, "financials")
    quarterly = _statement(ticker, "quarterly_financials")
    balance = _statement(ticker, "balance_sheet")
    cashflow = _statement(ticker, "cashflow")
    q_balance = _statement(ticker, "quarterly_balance_sheet")
    q_cashflow = _statement(ticker, "quarterly_cashflow")
    earn = fetch_earnings_bundle(ticker)
    notes.extend(earn.get("notes") or [])
    if saudi_sources:
        anns = sources.try_tadawul_announcements(ticker)
        fo = sources.try_foreign_ownership(ticker)
    else:
        anns, fo = None, None
        notes.append("رمز خارج السوق السعودية: لم تُطلب إعلانات تداول ولا ملكية الأجانب (غير منطبق).")
    if saudi_sources and (not anns or not anns.get("items")):
        notes.append("إعلانات السوق المالية الرسمية غير متاحة في هذه الجلسة (غالباً حجب 403 من saudiexchange.sa).")
    if saudi_sources and (not fo or not fo.get("data")):
        notes.append("نسب ملكية الأجانب من تداول غير متاحة في هذه الجلسة.")

    price = float(hist["Close"].iloc[-1])
    prev_close = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else info.get("previousClose")
    last_bar = hist.index[-1]
    try:
        last_bar_date = last_bar.tz_convert("Asia/Riyadh").strftime("%Y-%m-%d")
    except Exception:
        try:
            last_bar_date = last_bar.tz_localize("Asia/Riyadh").strftime("%Y-%m-%d") if last_bar.tzinfo is None else last_bar.strftime("%Y-%m-%d")
        except Exception:
            last_bar_date = str(last_bar)[:10]

    long_name = info.get("longName") or info.get("shortName") or ticker
    sector = info.get("sector") or ""
    industry = info.get("industry") or ""
    currency = info.get("currency") or ("SAR" if ticker.endswith(".SR") else "NOT FOUND")
    ar = name_ar(ticker, long_name)

    if macro is None:
        macro = fetch_macro()
    notes.extend(macro.get("notes") or [])

    peer_hist = {}
    if with_peers and saudi_sources:
        plist = peers_for(ticker, sector, industry)[:8]
        if plist:
            peer_hist = _peer_closes(plist, "6mo")
            missing = [p for p in plist if p not in peer_hist]
            if missing:
                notes.append("تعذر جلب أسعار بعض النظراء: " + ", ".join(missing))

    try:
        indicators = compute_all(hist)
    except Exception as exc:
        indicators = {}
        notes.append(f"فشل حساب بعض المؤشرات الفنية: {type(exc).__name__}")

    return MarketData(
        ticker=ticker,
        name=long_name,
        name_ar=ar,
        sector=sector,
        industry=industry,
        currency=currency,
        price=price,
        prev_close=float(prev_close) if prev_close is not None else None,
        last_bar_date=last_bar_date,
        hist=hist,
        info=info,
        news=news,
        financials=financials,
        quarterly_financials=quarterly,
        balance_sheet=balance,
        cashflow=cashflow,
        brent=macro.get("brent"),
        wti=macro.get("wti"),
        tasi_spot=macro.get("tasi_spot") or None,
        tasi_hist=macro.get("tasi_hist"),
        ksa_etf=macro.get("ksa_etf"),
        usd_sar=macro.get("usd_sar"),
        sama=macro.get("sama"),
        peer_hist=peer_hist,
        peer_names={},
        indicators=indicators,
        fetch_notes=notes,
        earnings_dates=earn.get("earnings_dates"),
        earnings_history=earn.get("earnings_history"),
        calendar=earn.get("calendar") or {},
        dividends=earn.get("dividends"),
        quarterly_balance_sheet=q_balance,
        quarterly_cashflow=q_cashflow,
        announcements=anns,
        foreign_ownership=fo,
        investor_flows=(macro or {}).get("investor_flows"),
        petrochem=(macro or {}).get("petrochem"),
        watchlist_hist=(macro or {}).get("watchlist_hist") or {},
        watchlist_pe=(macro or {}).get("watchlist_pe") or {},
    )


def pct_change(series: pd.Series, bars: int) -> Optional[float]:
    s = series.dropna()
    if len(s) <= bars:
        return None
    a, b = float(s.iloc[-1]), float(s.iloc[-1 - bars])
    if b == 0:
        return None
    return (a / b) - 1.0


def info_number(info: dict, *keys) -> Optional[float]:
    for k in keys:
        v = info.get(k)
        if v is None:
            continue
        try:
            f = float(v)
            if f == f:  # not NaN
                return f
        except (TypeError, ValueError):
            continue
    return None


def normalize_yield(value: Optional[float]) -> Optional[float]:
    """Yahoo dividendYield is sometimes 0.051 and sometimes 5.14. Return a fraction."""
    if value is None:
        return None
    if value > 1.0:
        return value / 100.0
    return value
