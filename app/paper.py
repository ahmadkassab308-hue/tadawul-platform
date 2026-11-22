"""Paper (simulated / ورقية) tracking of the engine's Buy signals.

Rules (documented in README):
- Every committee Buy with a stop and targets opens one paper trade per ticker (if none open),
  entry = close of the signal bar (rec.price). Sources: scanner runs, TradingView alerts, manual analyses,
  and the Buy rows already logged in tadawul-brain/decisions.md.
- Evaluation uses daily Yahoo Finance bars AFTER the signal date only.
  If a bar touches both stop and T1 the stop is assumed first (conservative); a gap through the stop fills at the open.
  After T1 is hit the stop moves to entry (breakeven); the trade closes at T3 or at the breakeven stop.
- A trade is a winner once T1 was reached before the stop. Gain = highest target reached vs entry.
Nothing here is invented: no signal, no fill, no price that is not in the logs / Yahoo history.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

from .engine_bridge import BRAIN, now_riyadh
from .markets import market_of

DATA = Path(__file__).resolve().parents[1] / "data"
PAPER = DATA / "paper.json"
_lock = threading.Lock()


def load() -> list[dict]:
    if PAPER.exists():
        try:
            return json.loads(PAPER.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def save(trades: list[dict]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = PAPER.with_suffix(".tmp")
    tmp.write_text(json.dumps(trades, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(PAPER)


def add_signal(p: dict, source: str) -> dict | None:
    """p = engine_bridge payload. Opens a paper trade for a Buy if none is open for the ticker."""
    if p.get("verdict_en") != "BUY" and p.get("verdict_ar") != "شراء":
        return None
    if not (p.get("price") and p.get("stop") and p.get("t1")):
        return None
    with _lock:
        trades = load()
        for t in trades:
            if t["ticker"] == p["ticker"] and t["status"] == "open":
                return None
            if t["ticker"] == p["ticker"] and t["signal_date"] == p["last_bar_date"]:
                return None
        t = {
            "id": uuid.uuid4().hex[:10], "ticker": p["ticker"], "name": p.get("name_ar") or p.get("name"),
            "market": p.get("market") or market_of(p["ticker"]), "currency": p.get("currency"),
            "source": source, "opened_at": now_riyadh(), "signal_date": p["last_bar_date"],
            "confidence": p.get("confidence"), "score": p.get("score"),
            "entry": p["price"], "stop": p["stop"], "t1": p["t1"], "t2": p.get("t2"), "t3": p.get("t3"),
            "status": "open", "best_target": 0, "last_price": p["price"], "pnl_pct": 0.0,
            "closed_at": None, "checked_at": None,
        }
        trades.append(t)
        save(trades)
        return t


def seed_from_decisions() -> int:
    """Import Buy rows already logged by the engine in tadawul-brain/decisions.md (real past signals)."""
    path = BRAIN / "decisions.md"
    if not path.exists():
        return 0
    text = path.read_text(encoding="utf-8")
    blocks = re.split(r"\n(?=## \d{4}-\d{2}-\d{2} \|)", text)
    n = 0
    for b in blocks:
        m = re.match(r"## (\d{4}-\d{2}-\d{2}) \| (\S+) \| (\S+) \| ثقة (\d+)% \| سعر ([\d.]+)", b)
        if not m or m.group(3) != "شراء":
            continue
        stop = re.search(r"وقف الخسارة: ([\d.]+)", b)
        tg = re.search(r"الأهداف: ([\d.]+) / ([\d.]+) / ([\d.]+)", b)
        name = re.search(r"الاسم: (.+)", b)
        if not (stop and tg):
            continue
        p = {"ticker": m.group(2), "verdict_ar": "شراء", "verdict_en": "BUY", "price": float(m.group(5)),
             "stop": float(stop.group(1)), "t1": float(tg.group(1)), "t2": float(tg.group(2)), "t3": float(tg.group(3)),
             "last_bar_date": m.group(1), "confidence": int(m.group(4)) / 100, "name_ar": name.group(1).strip() if name else m.group(2),
             "market": market_of(m.group(2)), "currency": "SAR" if m.group(2).endswith(".SR") else None}
        if add_signal(p, "decisions.md (سجل المحرك)"):
            n += 1
    return n


def _eval_one(t: dict, hist: pd.DataFrame) -> dict:
    sd = pd.Timestamp(t["signal_date"])
    idx = hist.index.tz_localize(None) if hist.index.tz is not None else hist.index
    h = hist.loc[[d.normalize() > sd for d in idx]]
    stop = t["stop"]
    best = 0
    status = "open"
    closed = None
    exit_px = None
    tg = [t.get("t1"), t.get("t2"), t.get("t3")]
    for d, row in h.iterrows():
        lo, hi, op = float(row["Low"]), float(row["High"]), float(row["Open"])
        if lo <= stop:
            status = "stopped" if best == 0 else "closed_breakeven"
            closed = str(d)[:10]
            exit_px = min(stop, op)  # gap below the stop fills at the open (worse), never better
            break
        for i, lvl in enumerate(tg, 1):
            if lvl and hi >= lvl and best < i:
                best = i
        if best >= 1:
            stop = max(stop, t["entry"])  # breakeven after T1
        if best == 3:
            status = "target3"
            closed = str(d)[:10]
            break
    last = float(h["Close"].iloc[-1]) if len(h) else t["entry"]
    t["best_target"] = best
    t["bars_after"] = int(len(h))
    t["last_price"] = round(last, 4)
    t["exit_price"] = round(exit_px, 4) if exit_px is not None else None
    if status == "stopped":
        t["pnl_pct"] = round((exit_px / t["entry"] - 1) * 100, 2)
    elif best >= 1:
        t["pnl_pct"] = round((tg[best - 1] / t["entry"] - 1) * 100, 2)
    else:
        t["pnl_pct"] = round((last / t["entry"] - 1) * 100, 2)
    if status == "open" and best >= 1:
        status = f"target{best}"  # still running toward next target
        t["running"] = True
    else:
        t["running"] = status == "open"
    t["status"] = status
    t["closed_at"] = closed
    t["checked_at"] = now_riyadh()
    return t


def evaluate_all() -> list[dict]:
    with _lock:
        trades = load()
        live = [t for t in trades if t["status"] in ("open",) or t.get("running")]
        tickers = sorted({t["ticker"] for t in live})
        for tk in tickers:
            try:
                hist = yf.Ticker(tk).history(period="6mo", auto_adjust=False)
            except Exception:
                continue
            if hist is None or hist.empty:
                continue
            for t in trades:
                if t["ticker"] == tk and (t["status"] == "open" or t.get("running")):
                    if t.get("running") and t["status"].startswith("target"):
                        t["status"] = "open"  # re-walk from signal date
                    _eval_one(t, hist)
        save(trades)
        return trades


def summary(market: str | None = None) -> dict:
    trades = load()
    if market:
        trades = [t for t in trades if t.get("market") == market]
    winners = sorted([t for t in trades if t.get("best_target", 0) >= 1], key=lambda t: -t.get("pnl_pct", 0))
    stopped = [t for t in trades if t["status"] == "stopped"]
    open_ = [t for t in trades if t["status"] == "open"]
    closed = len(winners) + len(stopped)
    return {"winners": winners, "stopped": stopped, "open": open_, "total": len(trades),
            "win_rate": round(len(winners) / closed * 100, 1) if closed else None, "closed": closed}
