"""TradingView integration via official/public means only:
- Pine Script v5 generator (user pastes it into TradingView's Pine editor).
- Alert webhook receiver (TradingView paid plans send alert JSON to our URL) → engine run → alerts feed.
No scraping, no private APIs, no login automation."""
from __future__ import annotations

import json
import logging
import os
import threading
import urllib.request
from pathlib import Path

from . import engine_bridge as eb
from . import paper
from .yahoo import SUFFIX_TV

log = logging.getLogger("tv")
ALERTS = Path(__file__).resolve().parents[1] / "data" / "alerts.json"
_lock = threading.Lock()

TV_TO_SUFFIX = {}
for suf, ex in SUFFIX_TV.items():
    TV_TO_SUFFIX.setdefault(ex, suf)
TV_TO_SUFFIX.update({"EURONEXT": "PA", "KRX": "KS", "NSE": "NS"})
US_TV = {"NASDAQ", "NYSE", "AMEX", "CBOE", "OTC", "BATS", "ARCA", "NYSEARCA"}


def tv_to_yahoo(ticker: str, exchange: str = "") -> str:
    t = (ticker or "").strip().upper()
    ex = (exchange or "").strip().upper()
    if ":" in t:
        ex, t = t.split(":", 1)
    if not t:
        return ""
    if ex in ("", *US_TV):
        if t.isdigit() and len(t) == 4 and ex == "":
            return t + ".SR"
        return t.replace(".", "-")
    suf = TV_TO_SUFFIX.get(ex)
    if not suf:
        return t
    if suf == "HK":
        t = t.zfill(4)
    return f"{t.replace('_', '-')}.{suf}"


def pine(p: dict) -> str:
    def num(x):
        return "na" if x is None else f"{float(x):.4f}".rstrip("0").rstrip(".")
    tick = p["ticker"].split(".")[0]
    verdict = {"BUY": "شراء", "SELL": "بيع"}.get(p.get("verdict_en"), "احتفاظ")
    conf = round((p.get("confidence") or 0) * 100)
    return f'''//@version=5
// Tadawul Brain — لجنة {p.get("n_total")} وكيلاً | {p["ticker"]} | {p.get("generated_at")} (توقيت الرياض)
// الحكم: {verdict} | الثقة {conf}% | الدرجة {p.get("score")} | آخر شمعة {p.get("last_bar_date")}
// تعليمي فقط — ليس توصية مالية. المصدر: tadawul-brain/engine + Yahoo Finance.
indicator("Tadawul Brain · {p["ticker"]} · {verdict} {conf}%", overlay=true, max_labels_count=5)

entryLow  = input.float({num(p.get("entry_low"))}, "بداية منطقة الدخول")
entryHigh = input.float({num(p.get("entry_high"))}, "نهاية منطقة الدخول")
stopLvl   = input.float({num(p.get("stop"))}, "وقف الخسارة")
t1        = input.float({num(p.get("t1"))}, "الهدف 1")
t2        = input.float({num(p.get("t2"))}, "الهدف 2")
t3        = input.float({num(p.get("t3"))}, "الهدف 3")
showWarn  = input.bool(true, "تنبيه إذا كان الرمز مختلفاً")

pHi = plot(entryHigh, "دخول (أعلى)", color=color.new(color.blue, 0), style=plot.style_linebr)
pLo = plot(entryLow,  "دخول (أدنى)", color=color.new(color.blue, 0), style=plot.style_linebr)
fill(pHi, pLo, color=color.new(color.blue, 85), title="منطقة الدخول")
plot(stopLvl, "وقف", color=color.new(color.red, 0), linewidth=2, style=plot.style_linebr)
plot(t1, "T1", color=color.new(color.green, 30), style=plot.style_linebr)
plot(t2, "T2", color=color.new(color.green, 15), style=plot.style_linebr)
plot(t3, "T3", color=color.new(color.green, 0), linewidth=2, style=plot.style_linebr)

var label lb = na
if barstate.islast
    label.delete(lb)
    txt = "Tadawul Brain: {verdict} · ثقة {conf}%\\nدخول " + str.tostring(entryLow) + "–" + str.tostring(entryHigh) + " · وقف " + str.tostring(stopLvl) + "\\nأهداف " + str.tostring(t1) + " / " + str.tostring(t2) + " / " + str.tostring(t3)
    lb := label.new(bar_index, high, txt, color={"color.new(color.green, 10)" if verdict == "شراء" else ("color.new(color.red, 10)" if verdict == "بيع" else "color.new(color.gray, 10)")}, textcolor=color.white, style=label.style_label_down, size=size.normal)
    if showWarn and syminfo.ticker != "{tick}"
        label.new(bar_index, low, "تنبيه: هذا السكربت مولّد لـ {tick} والرمز المفتوح " + syminfo.ticker, color=color.orange, textcolor=color.black, style=label.style_label_up)

alertcondition(close <= stopLvl, "كسر وقف الخسارة", "{p["ticker"]}: السعر كسر وقف الخسارة")
alertcondition(close >= t1, "بلوغ الهدف 1", "{p["ticker"]}: السعر بلغ الهدف 1")
alertcondition(close >= entryLow and close <= entryHigh, "داخل منطقة الدخول", "{p["ticker"]}: السعر داخل منطقة الدخول")
'''


def load_alerts() -> list[dict]:
    if ALERTS.exists():
        try:
            return json.loads(ALERTS.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save(items):
    ALERTS.parent.mkdir(parents=True, exist_ok=True)
    tmp = ALERTS.with_suffix(".tmp")
    tmp.write_text(json.dumps(items[-300:], ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ALERTS)


def _upsert(item):
    with _lock:
        items = load_alerts()
        items = [x for x in items if x["id"] != item["id"]] + [item]
        _save(items)


def forward(text: str, extra: dict | None = None) -> str:
    url = os.environ.get("GROKBOT_WEBHOOK_URL", "").strip()
    if not url:
        return "not-configured"
    auth = os.environ.get("GROKBOT_WEBHOOK_AUTH", "").strip()
    body = json.dumps({"text": text, "source": "tadawul-web", **(extra or {})}, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["Authorization"] = auth if " " in auth else f"Bearer {auth}"
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            return f"sent ({r.status})"
    except Exception as exc:
        return f"failed: {type(exc).__name__}"


def handle_alert(item: dict) -> None:
    try:
        p = eb.analyse(item["yahoo"], force=False)
        item.update(status="done", verdict_ar=p["verdict_ar"], verdict_en=p["verdict_en"], confidence=p["confidence"],
                    score=p["score"], price=p["price"], stop=p["stop"], t1=p["t1"], name=p.get("name_ar"),
                    analysed_at=p["generated_at"], currency=p.get("currency"))
        paper.add_signal(p, "تنبيه TradingView")
        msg = (f"تنبيه TradingView على {item['yahoo']} ({item.get('message') or ''}). "
               f"حكم اللجنة: {p['verdict_ar']} بثقة {round(p['confidence']*100)}%، السعر {p['price']}، "
               f"وقف {p['stop']}، الهدف الأول {p['t1']}. تعليمي وليس توصية مالية.")
        item["forward"] = forward(msg, {"ticker": item["yahoo"], "kind": "tradingview-alert"})
    except Exception as exc:
        item.update(status="error", error=f"{type(exc).__name__}: {str(exc)[:200]}")
    _upsert(item)


def receive(payload: dict, raw: str) -> dict:
    import uuid
    ticker = str(payload.get("ticker") or payload.get("symbol") or "").strip()
    exchange = str(payload.get("exchange") or "").strip()
    y = tv_to_yahoo(ticker, exchange)
    item = {"id": uuid.uuid4().hex[:10], "received_at": eb.now_riyadh(), "tv_ticker": ticker, "tv_exchange": exchange,
            "yahoo": y, "tv_price": payload.get("price") or payload.get("close"),
            "message": str(payload.get("message") or payload.get("text") or "")[:300],
            "interval": payload.get("interval"), "raw": raw[:500], "status": "queued" if y else "error"}
    if not y:
        item["error"] = "لا يوجد ticker في التنبيه"
        _upsert(item)
        return item
    _upsert(item)
    threading.Thread(target=handle_alert, args=(item,), daemon=True).start()
    return item
