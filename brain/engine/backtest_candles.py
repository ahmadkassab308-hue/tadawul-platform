#!/usr/bin/env python3
"""Backtest every candlestick pattern in engine/candles.py on the watchlist (~3 years daily).

Rules: the SAME detection code as the live analysts; shape/context at bar s use bars <= s only.
Measures forward 5/10-day directional hit rate from the pattern close (and from the confirmation
close for the "confirmed" subset). Baseline = share of all bars whose forward move was in the
same direction (so a bullish pattern is compared with the unconditional "up" rate).

Writes knowledge/candlesticks/backtest.json (read by engine/candles.bt_multiplier) and backtest.md.

  .venv/bin/python engine/backtest_candles.py            # watchlist.txt, period 3y
  .venv/bin/python engine/backtest_candles.py --period 5y
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import candles as C  # noqa: E402
from engine.run import load_watchlist  # noqa: E402

H = (5, 10)


def fetch(t: str, period: str):
    try:
        h = yf.Ticker(t).history(period=period, auto_adjust=True)
        h = h.dropna(subset=["Open", "High", "Low", "Close"])
        h = h[(h["High"] > 0) & (h["Volume"] > 0)]
        return h if len(h) > 260 else None
    except Exception:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default="3y")
    ap.add_argument("--watchlist", default=None)
    a = ap.parse_args(argv)
    tickers = load_watchlist(Path(a.watchlist) if a.watchlist else None)
    stats: dict = {}
    base = {h: {"up": 0, "dn": 0, "n": 0} for h in H}
    used, span = [], []
    for t in tickers:
        df = fetch(t, a.period)
        if df is None:
            print(f"{t}: NOT FOUND (no data)", file=sys.stderr)
            continue
        df, _ = C.completed_hist(df)   # drop today's unfinished candle (G1 p9 mistake 2)
        used.append(t)
        span.append((str(df.index[0])[:10], str(df.index[-1])[:10]))
        b = C.Bars(df)
        wk = C.weekly_trend_series(b)
        last = b.n - 1 - max(H)
        for s in range(60, b.n):
            if s <= last:
                for h in H:
                    r = b.c[s + h] / b.c[s] - 1
                    base[h]["n"] += 1
                    base[h]["up"] += r > 0
                    base[h]["dn"] += r < 0
            for e in C._shape_events(b, s):
                C.evaluate(b, e, wk)   # note: e.failed may look ahead; NOT used in the stats below
                eff = e.direction if e.direction != 0 else e.confirm_side
                skey = C.bt_key(e.key, eff)
                row = stats.setdefault(skey, {"key": e.key, "dir": eff, "n": 0, "hit5": 0, "hit10": 0, "ret5": 0.0, "ret10": 0.0,
                                               "ctx_n": 0, "ctx_hit10": 0, "conf_n": 0, "conf_hit10": 0,
                                               "full_n": 0, "full_hit10": 0, "tickers": set()})
                if s + 1 + max(H) >= b.n:
                    continue
                row["tickers"].add(t)
                row["n"] += 1
                for h in H:
                    r = (b.c[s + h] / b.c[s] - 1) * eff
                    row[f"hit{h}"] += r > 0
                    row[f"ret{h}"] += r
                r10 = (b.c[s + 10] / b.c[s] - 1) * eff
                ctx_ok = e.ladder_items["location"] and e.ladder_items["volume"]
                if ctx_ok:
                    row["ctx_n"] += 1
                    row["ctx_hit10"] += r10 > 0
                if e.confirmed:
                    # enter at the confirmation close when confirmation is a separate candle
                    sep = C.PATTERNS[e.key][5] in ("always", "preferred")
                    rc = (b.c[s + 1 + 10] / b.c[s + 1] - 1) * eff if sep else r10
                    row["conf_n"] += 1
                    row["conf_hit10"] += rc > 0
                    if e.ladder >= 4:
                        row["full_n"] += 1
                        row["full_hit10"] += rc > 0
        print(f"{t}: {b.n} bars", file=sys.stderr)

    up10 = base[10]["up"] / max(1, base[10]["n"])
    dn10 = base[10]["dn"] / max(1, base[10]["n"])
    up5 = base[5]["up"] / max(1, base[5]["n"])
    dn5 = base[5]["dn"] / max(1, base[5]["n"])
    out = {"generated_at": datetime.now(C.RIYADH).strftime("%Y-%m-%d %H:%M") + " Asia/Riyadh",
           "period": a.period, "tickers": used, "span": [min(x[0] for x in span), max(x[1] for x in span)] if span else None,
           "baseline": {"up5": up5, "down5": dn5, "up10": up10, "down10": dn10, "n": base[10]["n"]},
           "patterns": {}}
    for k, r in stats.items():
        n = r["n"]
        d = r["dir"]
        b10 = up10 if d > 0 else dn10
        b5 = up5 if d > 0 else dn5
        out["patterns"][k] = {
            "name_ar": C.PATTERNS[r["key"]][0] + ("" if C.PATTERNS[r["key"]][1] != 0 else (" بعد صعود" if d < 0 else " بعد هبوط")), "dir": d, "n": n, "n_tickers": len(r["tickers"]),
            "hit5": r["hit5"] / n if n else None, "hit10": r["hit10"] / n if n else None,
            "avg_ret5": r["ret5"] / n if n else None, "avg_ret10": r["ret10"] / n if n else None,
            "base5_dir": b5, "base10_dir": b10,
            "ctx_n": r["ctx_n"], "ctx_hit10": r["ctx_hit10"] / r["ctx_n"] if r["ctx_n"] else None,
            "conf_n": r["conf_n"], "conf_hit10": r["conf_hit10"] / r["conf_n"] if r["conf_n"] else None,
            "full_n": r["full_n"], "full_hit10": r["full_hit10"] / r["full_n"] if r["full_n"] else None,
        }
        pr = out["patterns"][k]
        pr["conf_mult"] = round(C.mult_from(pr, confirmed=False)[0], 3)
        pr["conf_mult_confirmed"] = round(C.mult_from(pr, confirmed=True)[0], 3)
    C.BACKTEST_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    write_md(out)
    print(f"wrote {C.BACKTEST_JSON} and backtest.md ({len(out['patterns'])} patterns, {len(used)} tickers)")


def pct(x):
    return "—" if x is None else f"{x*100:.0f}%"


def write_md(o):
    bl = o["baseline"]
    rows = sorted(o["patterns"].items(), key=lambda kv: -((kv[1]["hit10"] or 0) - kv[1]["base10_dir"]) if kv[1]["n"] >= 30 else 1)
    L = [
        "# اختبار خلفي لنماذج الشموع — backtest.md",
        "",
        f"- وقت التوليد: {o['generated_at']}",
        f"- البيانات: Yahoo Finance، أسعار يومية معدّلة، فترة {o['period']} ({o['span'][0]} → {o['span'][1]})، {len(o['tickers'])} سهماً من `watchlist.txt`.",
        "- السكربت: `engine/backtest_candles.py` — نفس كود الكشف في `engine/candles.py` الذي يستخدمه الوكلاء الأحياء.",
        "- لا نظر للمستقبل: الشكل والسياق عند الشمعة s يستخدمان الشموع حتى s فقط؛ التأكيد يستخدم الشمعة s+1 فقط.",
        "- «إصابة» = تحرّك السعر في اتجاه النمط بعد 5 أو 10 جلسات من إغلاق النمط (أو من إغلاق شمعة التأكيد في عمود «مؤكد»).",
        f"- خط الأساس (كل الشموع): صعود بعد 5 جلسات {pct(bl['up5'])}، هبوط {pct(bl['down5'])}؛ بعد 10 جلسات صعود {pct(bl['up10'])}، هبوط {pct(bl['down10'])} (n={bl['n']}). النمط الجيد يتفوق على أساس اتجاهه.",
        "- العائد المتوسط اتجاهي (موجب = في صالح النمط) وقبل العمولات.",
        "",
        "| النمط | اتجاه | n | أسهم | إصابة 5 | إصابة 10 | أساس 10 | الفارق | متوسط عائد 10 | سياق (مستوى+حجم) n / إصابة | مؤكد n / إصابة | سلّم ≥4 n / إصابة | معامل الثقة (غير مؤكد / مؤكد) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|---:|",
    ]
    for k, r in rows:
        diff = (r["hit10"] - r["base10_dir"]) if r["hit10"] is not None else None
        L.append(
            f"| {r['name_ar']} (`{k}`) | {'صاعد' if r['dir']>0 else 'هابط'} | {r['n']} | {r['n_tickers']} | {pct(r['hit5'])} | {pct(r['hit10'])} | {pct(r['base10_dir'])} | "
            f"{'—' if diff is None else f'{diff*100:+.0f}'} | {'—' if r['avg_ret10'] is None else f'{r['avg_ret10']*100:+.2f}%'} | "
            f"{r['ctx_n']} / {pct(r['ctx_hit10'])} | {r['conf_n']} / {pct(r['conf_hit10'])} | {r['full_n']} / {pct(r['full_hit10'])} | {r['conf_mult']} / {r['conf_mult_confirmed']} |"
        )
    L += [
        "",
        "## كيف تدخل النتائج في الثقة",
        "",
        f"- لكل نمط عينته n ≥ {C.P['min_bt_n']}: معامل الثقة = حد(1 + 2 × (إصابة 10 − أساس الاتجاه 10)، من 0.6 إلى 1.25). يُضرب في ثقة الوكيل الحي (`engine/candles.bt_multiplier`).",
        f"- إن كان النمط الحي مؤكداً بشمعة تالية وعينة «مؤكد» ≥ {C.P['min_bt_n']} يُستخدم معدل إصابة المؤكد بدلاً من العام.",
        "- الدوجي والقمة الدوارة يُقاسان منفصلين حسب الاتجاه السابق (بعد صعود = هابط، بعد هبوط = صاعد).",
        f"- عينة أقل من {C.P['min_bt_n']}: المعامل 1.0 — لا تُختلق دقة (قاعدة CLAUDE.md رقم 4).",
        "- المعامل لا يقلب اتجاه الإشارة؛ يغيّر الثقة فقط.",
        "",
        "## تحفظات",
        "",
        "- العينة داخل نفس قائمة المراقبة التي يحللها النظام (in-sample)؛ قد تتغير النسب على أسهم أو فترات أخرى.",
        "- الإصابة لا تساوي ربحاً: لا تشمل الوقف والهدف والعمولات والانزلاق. G3 §12: «لا توجد نسبة نجاح مفترضة لأي نموذج».",
        "- يُعاد التوليد دورياً: `.venv/bin/python engine/backtest_candles.py`.",
    ]
    (C.KDIR / "backtest.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
