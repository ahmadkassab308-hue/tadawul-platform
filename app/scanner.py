"""Background scanner: runs the engine over each market universe on a staggered schedule,
persists data/scans/<MARKET>.json, feeds the analysis cache and opens paper trades for Buys."""
from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import engine_bridge as eb
from . import paper
from .markets import MARKETS, UNIVERSE

log = logging.getLogger("scanner")
DATA = Path(__file__).resolve().parents[1] / "data" / "scans"
ORDER = ["SA", "US", "GULF", "EU", "ASIA", "EG"]
WORKERS = 2
status = {"running": None, "progress": 0, "total": 0, "started": None}


def path(m: str) -> Path:
    return DATA / f"{m}.json"


def load(m: str) -> dict | None:
    p = path(m)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _row(p: dict) -> dict:
    keep = ("ticker", "name", "name_ar", "market", "currency", "verdict_ar", "verdict_en", "confidence", "score",
            "price", "last_bar_date", "entry_low", "entry_high", "stop", "t1", "t2", "t3", "risk_r", "n_found", "n_total")
    r = {k: p.get(k) for k in keep}
    r["top_reason"] = (p.get("top_reasons") or [""])[0]
    r["patterns"] = [x["name"] for x in p.get("patterns") or []]
    return r


def scan_market(m: str) -> dict:
    uni = UNIVERSE.get(m) or []
    status.update(running=m, progress=0, total=len(uni), started=eb.now_riyadh())
    t0 = time.time()
    rows, errors = [], []

    def one(sym):
        try:
            p = eb.analyse(sym, force=True)
            paper.add_signal(p, "الماسح الآلي")
            return _row(p), None
        except Exception as exc:
            return None, {"ticker": sym, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
        finally:
            status["progress"] += 1

    eb.get_macro(m)  # warm once before threads
    with ThreadPoolExecutor(WORKERS) as ex:
        for row, err in ex.map(one, uni):
            if row:
                rows.append(row)
            if err:
                errors.append(err)
    rows.sort(key=lambda r: (r["score"] or -9), reverse=True)
    doc = {"market": m, "name_ar": MARKETS[m]["name_ar"], "scanned_at": eb.now_riyadh(), "epoch": time.time(),
           "duration_s": round(time.time() - t0), "universe": uni, "rows": rows, "errors": errors,
           "every_h": MARKETS[m]["every_h"]}
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = path(m).with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path(m))
    status.update(running=None)
    log.info("scan %s done: %d rows, %d errors, %ss", m, len(rows), len(errors), doc["duration_s"])
    return doc


def due(m: str) -> bool:
    d = load(m)
    if not d:
        return True
    return time.time() - d.get("epoch", 0) > MARKETS[m]["every_h"] * 3600


def loop(stop: threading.Event):
    try:
        paper.seed_from_decisions()
    except Exception as exc:
        log.warning("seed failed: %s", exc)
    while not stop.is_set():
        for m in ORDER:
            if stop.is_set():
                return
            if due(m):
                try:
                    scan_market(m)
                except Exception as exc:
                    log.exception("scan %s failed: %s", m, exc)
                    status.update(running=None)
                stop.wait(60)  # stagger markets
        stop.wait(300)


def paper_loop(stop: threading.Event):
    """Re-evaluate paper trades against new Yahoo bars every 30 minutes."""
    stop.wait(20)
    while not stop.is_set():
        try:
            paper.evaluate_all()
        except Exception as exc:
            log.warning("paper eval failed: %s", exc)
        stop.wait(1800)


def start() -> threading.Event:
    ev = threading.Event()
    threading.Thread(target=loop, args=(ev,), daemon=True, name="scanner").start()
    threading.Thread(target=paper_loop, args=(ev,), daemon=True, name="paper").start()
    return ev
