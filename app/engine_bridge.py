"""Bridge between the web app and the tadawul-brain multi-agent engine.

- Saudi (.SR) tickers: exactly the engine's own path (fetch_macro + fetch_stock + run_analysts + decide).
- Non-Saudi tickers: a market-neutral macro (no TASI/KSA/SAMA/USD-SAR), no Saudi peers, and the
  Saudi-only analysts return NOT FOUND ("غير منطبق") instead of guessing. Nothing is persisted to
  tadawul-brain memory files (equivalent of run.py --no-persist).
"""
from __future__ import annotations

import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BRAIN = Path(os.environ.get("BRAIN_DIR") or (Path(__file__).resolve().parents[1] / "brain"))
if str(BRAIN) not in sys.path:
    sys.path.insert(0, str(BRAIN))

from engine.aggregate import _call, decide  # noqa: E402
from engine.analysts_common import SPECS, nf  # noqa: E402
from engine.fetch import _history, _peer_closes, fetch_macro, fetch_stock  # noqa: E402
from engine.universe import MACRO_TICKERS  # noqa: E402

from .markets import UNIVERSE, market_of  # noqa: E402

RIYADH = ZoneInfo("Asia/Riyadh")
CACHE_TTL = 15 * 60
MACRO_TTL = 60 * 60

SAUDI_ONLY = {
    "tasi-context", "sama-policy", "usd-sar-peg", "petrochem-spreads", "market-regime",
    "tadawul-announcements", "foreign-ownership", "investor-flows", "seasonality-calendar",
    "relative-strength-market", "beta-vs-market", "sector-rotation", "sector-relative",
}

GROUP_AR = {
    "technical": "فني", "fundamental": "أساسي", "sentiment": "معنويات وأخبار",
    "sector-macro": "قطاع وكلي", "liquidity": "سيولة", "risk": "مخاطر",
    "saudi-market": "السوق السعودي", "candlestick": "الشموع اليابانية", "debate": "ثور ودب",
    "committee": "اللجنة", "audit": "مدقق الأداء",
}

_macro_cache: dict[str, tuple[float, dict]] = {}
_macro_lock = threading.Lock()
_cache: dict[str, tuple[float, dict]] = {}
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def now_riyadh() -> str:
    return datetime.now(RIYADH).strftime("%Y-%m-%d %H:%M")


def get_macro(market: str) -> dict:
    key = "SA" if market == "SA" else "INTL:" + market
    with _macro_lock:
        hit = _macro_cache.get(key)
        if hit and time.time() - hit[0] < MACRO_TTL:
            return hit[1]
        if market == "SA":
            macro = fetch_macro()
        else:
            uni = UNIVERSE.get(market) or []
            macro = {
                "brent": _history(MACRO_TICKERS["brent"], "1y"),
                "wti": _history(MACRO_TICKERS["wti"], "1y"),
                "tasi_hist": None, "tasi_spot": {}, "ksa_etf": None, "usd_sar": None, "sama": None,
                "watchlist_hist": _peer_closes(uni[:20], "1y") if uni else {},
                "watchlist_pe": {}, "investor_flows": None, "petrochem": None,
                "notes": ["رمز خارج تداول: وكلاء تاسي/ساما/ربط الريال/تدفقات تداول/ملكية الأجانب غير منطبقة (NOT FOUND)."],
            }
        _macro_cache[key] = (time.time(), macro)
        return macro


def _run(data, saudi: bool):
    results = []
    for order in (0, 1, 2, 3):
        for agent_id, spec in SPECS.items():
            if spec.pass_order != order:
                continue
            if not saudi and agent_id in SAUDI_ONLY:
                results.append(nf(spec, "غير منطبق: الرمز خارج السوق السعودية (هذا الوكيل مبني على بيانات تداول/تاسي/ساما).", "tadawul-web / markets.py"))
                continue
            results.append(_call(agent_id, data, results) if order >= 2 else _call(agent_id, data))
    return results


def _r(x, nd=2):
    try:
        return None if x is None else round(float(x), nd)
    except Exception:
        return None


def to_payload(rec, data, market: str) -> dict:
    groups: dict[str, dict] = {}
    agents = []
    patterns = []
    for r in rec.results:
        g = groups.setdefault(r.group, {"group": r.group, "name_ar": GROUP_AR.get(r.group, r.group),
                                         "bull": 0, "bear": 0, "neutral": 0, "nf": 0, "sum": 0.0, "n": 0})
        sig = r.clipped_signal()
        if sig is None:
            g["nf"] += 1
        else:
            g["n"] += 1
            g["sum"] += sig
            if sig >= 0.15:
                g["bull"] += 1
            elif sig <= -0.15:
                g["bear"] += 1
            else:
                g["neutral"] += 1
        agents.append({"id": r.agent_id, "name": r.name_ar, "group": r.group, "signal": _r(sig),
                       "confidence": _r(r.confidence, 3), "reason": r.reason_ar, "source": r.source,
                       "found": bool(r.found)})
        if r.group == "candlestick" and r.found and sig is not None and r.agent_id not in ("candle-anatomy", "candle-structure", "candle-risk-stop", "candle-levels", "candle-volume", "candle-weekly", "candle-confirmation"):
            patterns.append({"id": r.agent_id, "name": r.name_ar, "signal": _r(sig), "confidence": _r(r.confidence, 3), "reason": r.reason_ar})
    for g in groups.values():
        g["avg"] = _r(g["sum"] / g["n"]) if g["n"] else None
        del g["sum"]
    sources = sorted({a["source"] for a in agents if a["found"] and a["source"]})[:40]
    return {
        "ticker": rec.ticker, "name": data.name, "name_ar": rec.name_ar, "market": market,
        "currency": data.currency, "sector": data.sector, "industry": data.industry,
        "verdict_ar": rec.rec_ar, "verdict_en": (rec.rec_en or "HOLD").upper(), "confidence": _r(rec.confidence, 3),
        "score": _r(rec.weighted_score, 3), "price": _r(rec.price, 4), "last_bar_date": rec.last_bar_date,
        "entry_low": _r(rec.entry_low, 4), "entry_high": _r(rec.entry_high, 4), "stop": _r(rec.stop_loss, 4),
        "t1": _r(rec.target1, 4), "t2": _r(rec.target2, 4), "t3": _r(rec.target3, 4), "risk_r": _r(rec.risk_r, 3),
        "top_reasons": rec.top_reasons, "key_risks": rec.key_risks, "dissenters": rec.dissenters,
        "bull": rec.bull_summary, "bear": rec.bear_summary, "committee": rec.committee_summary,
        "n_found": rec.n_found, "n_total": rec.n_total, "not_found": rec.not_found,
        "groups": list(groups.values()), "agents": agents, "patterns": patterns,
        "notes": list(dict.fromkeys(data.fetch_notes or [])), "sources": sources,
        "source_note": rec.source_note, "generated_at": now_riyadh(),
        "engine": "tadawul-brain/engine (" + str(len(SPECS)) + " وكيلاً) — بدون حفظ في الذاكرة (--no-persist)",
    }


def analyse(symbol: str, force: bool = False) -> dict:
    symbol = symbol.strip().upper()
    if symbol.isdigit():
        symbol += ".SR"
    with _locks_guard:
        lock = _locks.setdefault(symbol, threading.Lock())
    with lock:
        hit = _cache.get(symbol)
        if hit and not force and time.time() - hit[0] < CACHE_TTL:
            out = dict(hit[1])
            out["cached"] = True
            return out
        market = market_of(symbol)
        saudi = market == "SA"
        macro = get_macro(market)
        data = fetch_stock(symbol, macro=macro, with_peers=saudi, saudi_sources=saudi)
        results = _run(data, saudi)
        rec = decide(data, results)
        payload = to_payload(rec, data, market)
        payload["cached"] = False
        _cache[symbol] = (time.time(), payload)
        return payload


def cached(symbol: str) -> dict | None:
    hit = _cache.get(symbol.upper())
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    return None


def put_cache(symbol: str, payload: dict) -> None:
    _cache[symbol.upper()] = (time.time(), payload)
