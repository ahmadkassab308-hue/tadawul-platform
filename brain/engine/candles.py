"""Candlestick knowledge engine — deterministic implementation of knowledge/candlesticks/RULES.md.

Sources (copied into knowledge/candlesticks/):
  G1 = guide-1-comprehensive-11p.pdf  ("الدليل الشامل لقراءة الشموع اليابانية", 11 صفحة)
  G2 = guide-2-full-book-27p.pdf      ("الشموع اليابانية — الدليل الشامل", 27 صفحة)
  G3 = guide-3-reading-notebook.html  ("دليل قراءة الشموع اليابانية", 12 قسماً)

Every numeric threshold below is either quoted from a guide (comment `G#`) or a clearly
labelled DEFAULT (the guides say "تقريباً" / "طويل" without a number). No lookahead:
pattern shape and context at bar `s` use bars <= s only; confirmation uses bar s+1 only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
KDIR = ROOT / "knowledge" / "candlesticks"
BACKTEST_JSON = KDIR / "backtest.json"
RIYADH = ZoneInfo("Asia/Riyadh")

# ── thresholds ──────────────────────────────────────────────────────────────
P = {
    # G3 §3: range = H-L; body = |C-O|; close-location = (C-L)/range; range==0 -> skip
    "doji_body_max": 0.05,          # DEFAULT: "الافتتاح يساوي الإغلاق تقريباً" (G1 p3, G2 5.2) -> body <= 5% of range (G3 §11 ex.3: a 10% body is read as a potential hammer, not a doji)
    "small_body_max": 0.33,         # DEFAULT: "جسم صغير" -> body <= 1/3 of range
    "shadow_mult": 2.0,             # G1 p4, G2 5.3/5.4, G3 §6: long shadow >= 2x body
    "tiny_shadow_max": 0.10,        # DEFAULT: "ظل معدوم/قصير جداً" -> <= 10% of range
    "marubozu_shadow_max": 0.05,    # DEFAULT: "بلا ظلال تقريباً" (G1 p3, G2 5.1) -> each shadow <= 5% of range
    "long_body_mult": 1.3,          # DEFAULT: "جسم طويل" -> body >= 1.3x mean body of prior 10 candles (G1 p2 golden rule: candle not above average carries no message)
    "avg_bodies_n": 10,
    "prior_trend_n": 10,            # G2 4.1: "انظر إلى الشموع العشر السابقة وحدد الاتجاه"
    "prior_trend_atr": 1.5,         # DEFAULT: prior trend = |close move over 10 bars| >= 1.5 ATR14
    "extended_trend_atr": 3.0,      # DEFAULT: "اتجاه ممتد" >= 3 ATR over 10 bars
    "level_tol_atr": 0.5,           # DEFAULT: "عند دعم/مقاومة" -> within max(0.5 ATR, 1% price)
    "level_tol_pct": 0.01,
    "pivot_lr": 3,                  # DEFAULT pivot: high/low extreme of 3 bars each side (G3 §4: pivot can't be confirmed at formation)
    "levels_lookback": 120,         # DEFAULT: levels from the last ~6 months of daily bars
    "vol_avg_n": 20,                # G1 p8: volume vs average of last 20 candles
    "vol_clear": 1.2,               # DEFAULT for "أعلى بوضوح" (G1 p8); G3 §8 example of relative volume = 1.5x
    "vol_strong": 1.5,              # G3 §8 example (1.5M vs 1M average)
    "rsi_os": 30, "rsi_ob": 70, "rsi_mid": 60,   # G1 p8: hammer + RSI<30 stronger than RSI>60; shooting star + RSI>70
    "tweezer_tol_atr": 0.10,        # DEFAULT for "قاع متساوٍ تقريباً" (G1 p5, G2 6.4)
    "star_body_max_vs_first": 0.35, # DEFAULT: star "صغيرة الجسم" <= 35% of first candle body
    "soldier_shadow_max": 0.25,     # DEFAULT: soldiers "فتائل علوية قصيرة"/close near high (G1 p6, G2 7.2)
    "rr_min": 2.0,                  # G1 p9, G2 11.2/12.1: reward >= 2x risk
    "risk_pct": (0.01, 0.02),       # G1 p9, G2 11.2: risk 1–2% of capital
    "active_bars": 3,               # DEFAULT: a pattern stays "active" for the bar it completes + 2 follow-up bars
    "min_bt_n": 30,                 # DEFAULT: backtest sample needed before hit-rate changes confidence
}

# base strength per pattern from the reference tables (G2 appendix table 7 p25-26; G1 §10 p10-11)
# needs: "always" | "preferred" | "built_in" | "no"
PATTERNS = {
    # key: (name_ar, dir, kind, n, base, needs, agent, cite)
    "hammer": ("مطرقة", 1, "reversal", 1, 0.65, "always", "candle-single-reversal", "G2 ف5.3 ص9؛ G1 ص4؛ G3 §6"),
    "hanging_man": ("رجل مشنوق", -1, "reversal", 1, 0.45, "always", "candle-single-reversal", "G2 ف5.3 ص9؛ G1 ص4 وص11"),
    "inverted_hammer": ("مطرقة مقلوبة", 1, "reversal", 1, 0.45, "always", "candle-single-reversal", "G2 ف5.4 ص10؛ G1 ص4 وص11"),
    "shooting_star": ("نجم ساقط (شهاب)", -1, "reversal", 1, 0.65, "always", "candle-single-reversal", "G2 ف5.4 ص10؛ G1 ص4؛ G3 §6"),
    "dragonfly_doji": ("دوجي اليعسوب", 1, "reversal", 1, 0.55, "always", "candle-single-reversal", "G1 ص3 وص10؛ G2 ف5.2 ص8"),
    "gravestone_doji": ("دوجي شاهد القبر", -1, "reversal", 1, 0.55, "always", "candle-single-reversal", "G1 ص3 وص10؛ G2 ف5.2 ص8"),
    "doji": ("دوجي", 0, "indecision", 1, 0.35, "always", "candle-indecision", "G1 ص3؛ G2 ف5.2 ص8-9"),
    "long_legged_doji": ("دوجي طويل الأرجل", 0, "indecision", 1, 0.40, "always", "candle-indecision", "G2 ف5.2 ص8"),
    "spinning_top": ("قمة دوارة", 0, "indecision", 1, 0.30, "always", "candle-indecision", "G1 ص3؛ G2 ف5.5 ص10"),
    "bull_marubozu": ("ماروبوزو صاعد", 1, "continuation", 1, 0.65, "no", "candle-marubozu", "G2 ف5.1 ص8؛ G1 ص3 وص10"),
    "bear_marubozu": ("ماروبوزو هابط", -1, "continuation", 1, 0.65, "no", "candle-marubozu", "G2 ف5.1 ص8؛ G1 ص3 وص10"),
    "bull_engulfing": ("ابتلاع شرائي", 1, "reversal", 2, 0.85, "preferred", "candle-engulfing", "G2 ف6.1 ص11؛ G1 ص5؛ G3 §7"),
    "bear_engulfing": ("ابتلاع بيعي", -1, "reversal", 2, 0.85, "preferred", "candle-engulfing", "G2 ف6.1 ص11؛ G1 ص5"),
    "bull_harami": ("حرامي شرائي", 1, "reversal", 2, 0.45, "always", "candle-harami", "G2 ف6.2 ص12؛ G1 ص5 وص11؛ G3 §7"),
    "bear_harami": ("حرامي بيعي", -1, "reversal", 2, 0.45, "always", "candle-harami", "G2 ف6.2 ص12؛ G1 ص5 وص11"),
    "piercing": ("خط اختراق (ثاقب)", 1, "reversal", 2, 0.70, "preferred", "candle-piercing-darkcloud", "G2 ف6.3 ص12؛ G1 ص5"),
    "dark_cloud": ("غطاء السحابة الداكنة", -1, "reversal", 2, 0.70, "preferred", "candle-piercing-darkcloud", "G2 ف6.3 ص13؛ G1 ص5"),
    "tweezer_bottom": ("قاع الملقط", 1, "reversal", 2, 0.55, "always", "candle-tweezers", "G2 ف6.4 ص13؛ G1 ص5"),
    "tweezer_top": ("قمة الملقط", -1, "reversal", 2, 0.55, "always", "candle-tweezers", "G2 ف6.4 ص13؛ G1 ص5"),
    "morning_star": ("نجمة الصباح", 1, "reversal", 3, 0.90, "built_in", "candle-stars", "G2 ف7.1 ص14؛ G1 ص6؛ G3 §7"),
    "evening_star": ("نجمة المساء", -1, "reversal", 3, 0.90, "built_in", "candle-stars", "G2 ف7.1 ص14؛ G1 ص6"),
    "three_white_soldiers": ("الجنود البيض الثلاثة", 1, "reversal", 3, 0.75, "built_in", "candle-soldiers-crows", "G2 ف7.2 ص15؛ G1 ص6"),
    "three_black_crows": ("الغربان السود الثلاثة", -1, "reversal", 3, 0.75, "built_in", "candle-soldiers-crows", "G2 ف7.2 ص15؛ G1 ص6"),
    "three_inside_up": ("الثلاثة الداخلية الصاعدة", 1, "reversal", 3, 0.80, "built_in", "candle-three-inside", "G2 ف7.3 ص16"),
    "three_inside_down": ("الثلاثة الداخلية الهابطة", -1, "reversal", 3, 0.80, "built_in", "candle-three-inside", "G2 ف7.3 ص16"),
    "rising_three": ("الطرق الثلاث الصاعدة", 1, "continuation", 5, 0.75, "built_in", "candle-continuation", "G2 ف8.1 ص17"),
    "falling_three": ("الطرق الثلاث الهابطة", -1, "continuation", 5, 0.75, "built_in", "candle-continuation", "G2 ف8.1 ص17"),
    "rising_window": ("نافذة صاعدة (فجوة)", 1, "continuation", 2, 0.70, "no", "candle-continuation", "G2 ف8.2 ص17-18"),
    "falling_window": ("نافذة هابطة (فجوة)", -1, "continuation", 2, 0.70, "no", "candle-continuation", "G2 ف8.2 ص17-18"),
}


@dataclass
class Event:
    key: str
    end: int
    start: int
    direction: int
    low: float
    high: float
    stop: float
    confirm_level: Optional[float]   # close beyond this on bar end+1 confirms (None = built in)
    confirm_side: int                # +1 close above / -1 close below
    ctx: dict = field(default_factory=dict)
    confirmed: Optional[bool] = None  # None = pending (no next bar yet)
    failed: bool = False
    ladder: int = 0
    ladder_items: dict = field(default_factory=dict)
    note: str = ""

    @property
    def meta(self):
        return PATTERNS[self.key]

    @property
    def name_ar(self):
        return self.meta[0]


# ── basic arrays ────────────────────────────────────────────────────────────
class Bars:
    def __init__(self, df: pd.DataFrame):
        df = df.dropna(subset=["Open", "High", "Low", "Close"]).copy()
        self.df = df
        self.o = df["Open"].to_numpy(float)
        self.h = df["High"].to_numpy(float)
        self.l = df["Low"].to_numpy(float)
        self.c = df["Close"].to_numpy(float)
        self.v = df["Volume"].to_numpy(float) if "Volume" in df else np.full(len(df), np.nan)
        self.n = len(df)
        self.rng = self.h - self.l
        self.body = np.abs(self.c - self.o)
        self.top = np.maximum(self.o, self.c)
        self.bot = np.minimum(self.o, self.c)
        self.up = self.h - self.top
        self.lo_sh = self.bot - self.l
        with np.errstate(divide="ignore", invalid="ignore"):
            self.body_ratio = np.where(self.rng > 0, self.body / self.rng, np.nan)
            self.close_loc = np.where(self.rng > 0, (self.c - self.l) / self.rng, np.nan)  # G3 §3
        c = pd.Series(self.c)
        prev = c.shift(1)
        tr = pd.concat([pd.Series(self.rng), (pd.Series(self.h) - prev).abs(), (pd.Series(self.l) - prev).abs()], axis=1).max(axis=1)
        self.atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().to_numpy()
        self.avg_body = pd.Series(self.body).shift(1).rolling(P["avg_bodies_n"], min_periods=5).mean().to_numpy()
        self.vol_avg = pd.Series(self.v).shift(1).rolling(P["vol_avg_n"], min_periods=10).mean().to_numpy()
        self.sma20 = c.rolling(20).mean().to_numpy()
        self.sma50 = c.rolling(50).mean().to_numpy()
        self.sma200 = c.rolling(200).mean().to_numpy()
        d = c.diff()
        g = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        ls = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        self.rsi = (100 - 100 / (1 + g / ls.replace(0, np.nan))).to_numpy()
        # pivots (confirmed `lr` bars later)
        lr = P["pivot_lr"]
        self.piv_hi, self.piv_lo = [], []
        for i in range(lr, self.n - lr):
            if self.h[i] >= self.h[i - lr: i + lr + 1].max():
                self.piv_hi.append(i)
            if self.l[i] <= self.l[i - lr: i + lr + 1].min():
                self.piv_lo.append(i)

    def is_long(self, i) -> bool:
        ab = self.avg_body[i]
        return bool(np.isfinite(ab) and ab > 0 and self.body[i] >= P["long_body_mult"] * ab)

    def green(self, i):
        return self.c[i] > self.o[i]

    def red(self, i):
        return self.c[i] < self.o[i]

    def mid_body(self, i):
        return (self.o[i] + self.c[i]) / 2.0


# ── context (uses bars <= s only) ───────────────────────────────────────────
def prior_trend(b: Bars, start: int) -> tuple[int, float]:
    """G2 4.1: trend of the 10 candles before the pattern. Returns (dir, move_in_atr)."""
    k = P["prior_trend_n"]
    j = start - 1
    if j - k < 0 or not np.isfinite(b.atr[j]) or b.atr[j] <= 0:
        return 0, 0.0
    move = (b.c[j] - b.c[j - k]) / b.atr[j]
    if move >= P["prior_trend_atr"]:
        return 1, float(move)
    if move <= -P["prior_trend_atr"]:
        return -1, float(move)
    return 0, float(move)


def structure(b: Bars, s: int) -> dict:
    """G1 §6 p6-7, G2 9.1, G3 §4: trend from the sequence of confirmed swing highs/lows."""
    lr = P["pivot_lr"]
    his = [i for i in b.piv_hi if i + lr <= s and i >= s - 250]
    los = [i for i in b.piv_lo if i + lr <= s and i >= s - 250]
    if len(his) < 2 or len(los) < 2:
        return {"dir": 0, "label": "غير محدد", "ok": False}
    h1, h2 = b.h[his[-2]], b.h[his[-1]]
    l1, l2 = b.l[los[-2]], b.l[los[-1]]
    tol = 0.25 * (b.atr[s] if np.isfinite(b.atr[s]) else 0)
    hh, hl = h2 > h1 + tol, l2 > l1 + tol
    lh, ll = h2 < h1 - tol, l2 < l1 - tol
    if hh and hl:
        d, lab = 1, "صاعد (قمم أعلى وقيعان أعلى)"
    elif lh and ll:
        d, lab = -1, "هابط (قمم أدنى وقيعان أدنى)"
    elif abs(h2 - h1) <= tol and abs(l2 - l1) <= tol:
        d, lab = 0, "عرضي (قمم وقيعان متساوية تقريباً)"
    else:
        d, lab = 0, "انتقالي (لم تتضح البنية)"
    return {"dir": d, "label": lab, "ok": True, "last_hi": float(h2), "prev_hi": float(h1),
            "last_lo": float(l2), "prev_lo": float(l1), "hi_idx": his[-1], "lo_idx": los[-1]}


def levels(b: Bars, s: int) -> dict:
    """Support/resistance candidates visible at bar s (G1 p7-8, G2 9.2, G3 §5)."""
    lr = P["pivot_lr"]
    lb = P["levels_lookback"]
    sup = [(float(b.l[i]), "قاع محوري") for i in b.piv_lo if s - lb <= i and i + lr <= s]
    res = [(float(b.h[i]), "قمة محورية") for i in b.piv_hi if s - lb <= i and i + lr <= s]
    for arr, nm in ((b.sma20, "متوسط 20"), (b.sma50, "متوسط 50"), (b.sma200, "متوسط 200")):
        if np.isfinite(arr[s]):
            sup.append((float(arr[s]), nm))
            res.append((float(arr[s]), nm))
    tol = max(P["level_tol_atr"] * (b.atr[s] if np.isfinite(b.atr[s]) else 0), P["level_tol_pct"] * b.c[s])
    return {"sup": sup, "res": res, "tol": tol}


def near_level(b: Bars, s: int, price: float, side: str, lv: dict | None = None) -> Optional[tuple]:
    lv = lv or levels(b, s)
    best = None
    for lvl, nm in lv["sup" if side == "sup" else "res"]:
        dist = abs(price - lvl)
        if dist <= lv["tol"] and (best is None or dist < best[2]):
            best = (lvl, nm, dist)
    return best


def rvol(b: Bars, i: int) -> Optional[float]:
    a = b.vol_avg[i]
    if not np.isfinite(a) or a <= 0 or not np.isfinite(b.v[i]):
        return None
    return float(b.v[i] / a)


# ── pattern shape detection at bar s (no lookahead) ─────────────────────────
def _shape_events(b: Bars, s: int) -> list[Event]:
    ev: list[Event] = []
    if s < 1 or not (b.rng[s] > 0):
        return ev
    r, bd = b.rng[s], b.body[s]
    br = bd / r
    up, lo = b.up[s], b.lo_sh[s]
    long_lower = lo >= P["shadow_mult"] * max(bd, 1e-9) and br <= P["small_body_max"] and up <= P["tiny_shadow_max"] * r
    long_upper = up >= P["shadow_mult"] * max(bd, 1e-9) and br <= P["small_body_max"] and lo <= P["tiny_shadow_max"] * r
    is_doji = br <= P["doji_body_max"]
    t, _ = prior_trend(b, s)

    def E(key, start, lowp, highp, stop, cl, cs):
        ev.append(Event(key, s, start, PATTERNS[key][1], float(lowp), float(highp), float(stop), cl, cs))

    # single candles — naming depends on prior trend (G1 p4, G2 4.1)
    if is_doji:
        if lo >= 0.6 * r and up <= P["tiny_shadow_max"] * r and t == -1:
            E("dragonfly_doji", s, b.l[s], b.h[s], b.l[s], b.h[s], 1)
        elif up >= 0.6 * r and lo <= P["tiny_shadow_max"] * r and t == 1:
            E("gravestone_doji", s, b.l[s], b.h[s], b.h[s], b.l[s], -1)
        elif t != 0:
            # DEFAULT long-legged: both shadows >= 30% of range and range >= 1.3x ATR14 (G2 5.2 "فتيلان طويلان جداً")
            key = "long_legged_doji" if (up >= 0.3 * r and lo >= 0.3 * r and np.isfinite(b.atr[s]) and r >= 1.3 * b.atr[s]) else "doji"
            # confirmation = next close against the prior trend beyond the doji extreme (G2 ص9)
            if t == 1:
                E(key, s, b.l[s], b.h[s], b.h[s], b.l[s], -1)
            else:
                E(key, s, b.l[s], b.h[s], b.l[s], b.h[s], 1)
    else:
        if long_lower and t == -1:
            E("hammer", s, b.l[s], b.h[s], b.l[s], b.h[s], 1)              # stop under wick (G2 5.3); confirm close > high (G1 p8)
        if long_lower and t == 1:
            E("hanging_man", s, b.l[s], b.h[s], b.h[s], b.bot[s], -1)      # confirm close < body (G1 p4, G2 5.3); stop above high
        if long_upper and t == -1:
            E("inverted_hammer", s, b.l[s], b.h[s], b.l[s], b.h[s], 1)     # buy above wick top after confirm; stop under low (G2 5.4)
        if long_upper and t == 1:
            E("shooting_star", s, b.l[s], b.h[s], b.h[s], b.l[s], -1)      # confirm close < low (G1 p8); stop above wick (G2 5.4)
        if (br > P["doji_body_max"] and br <= 0.30 and up >= 0.25 * r and lo >= 0.25 * r
                and 0.5 <= (up / max(lo, 1e-9)) <= 2.0 and t != 0):
            # spinning top: small body, shadows of similar length (G1 p3, G2 5.5)
            if t == 1:
                E("spinning_top", s, b.l[s], b.h[s], b.h[s], b.l[s], -1)
            else:
                E("spinning_top", s, b.l[s], b.h[s], b.l[s], b.h[s], 1)
        if b.is_long(s) and up <= P["marubozu_shadow_max"] * r and lo <= P["marubozu_shadow_max"] * r:
            if b.green(s):
                E("bull_marubozu", s, b.l[s], b.h[s], b.l[s], None, 1)     # stop under low (G2 5.1)
            elif b.red(s):
                E("bear_marubozu", s, b.l[s], b.h[s], b.h[s], None, -1)

    p = s - 1
    if p >= 0 and b.rng[p] > 0:
        tp, _ = prior_trend(b, p)
        lo2, hi2 = min(b.l[p], b.l[s]), max(b.h[p], b.h[s])
        # engulfing (G2 6.1: body 2 engulfs body 1 fully, "أطول بوضوح"; shadows need not be engulfed)
        if b.red(p) and b.green(s) and b.o[s] <= b.c[p] and b.c[s] >= b.o[p] and b.body[s] > b.body[p] and tp == -1:
            E("bull_engulfing", p, lo2, hi2, lo2, b.c[s], 1)
        if b.green(p) and b.red(s) and b.o[s] >= b.c[p] and b.c[s] <= b.o[p] and b.body[s] > b.body[p] and tp == 1:
            E("bear_engulfing", p, lo2, hi2, hi2, b.c[s], -1)
        # harami (G2 6.2: long mother + small body fully inside mother body; G1 p5 confirm close outside mother range)
        if b.is_long(p) and b.body[s] <= 0.5 * b.body[p] and b.top[s] <= b.top[p] and b.bot[s] >= b.bot[p] and b.body[s] < b.body[p]:
            if b.red(p) and tp == -1:
                E("bull_harami", p, lo2, hi2, lo2, b.h[p], 1)
            if b.green(p) and tp == 1:
                E("bear_harami", p, lo2, hi2, hi2, b.l[p], -1)
        # piercing / dark cloud (G2 6.3: close beyond 50% of body 1 is mandatory, without full engulf; G1 p5 open below/above)
        if b.red(p) and b.is_long(p) and b.green(s) and b.o[s] < b.c[p] and b.mid_body(p) < b.c[s] < b.o[p] and tp == -1:
            E("piercing", p, lo2, hi2, lo2, b.c[s], 1)
        if b.green(p) and b.is_long(p) and b.red(s) and b.o[s] > b.c[p] and b.o[p] < b.c[s] < b.mid_body(p) and tp == 1:
            E("dark_cloud", p, lo2, hi2, hi2, b.c[s], -1)
        # tweezers (G2 6.4: equal lows/highs + prior trend; confirm above high of candle 2)
        tol = P["tweezer_tol_atr"] * (b.atr[s] if np.isfinite(b.atr[s]) else 0)
        if tol > 0 and abs(b.l[p] - b.l[s]) <= tol and tp == -1 and b.l[s] <= b.l[max(0, p - 5): p].min() + tol:
            E("tweezer_bottom", p, lo2, hi2, lo2, b.h[s], 1)
        if tol > 0 and abs(b.h[p] - b.h[s]) <= tol and tp == 1 and b.h[s] >= b.h[max(0, p - 5): p].max() - tol:
            E("tweezer_top", p, lo2, hi2, hi2, b.l[s], -1)
        # windows / gaps (G2 8.2)
        if b.l[s] > b.h[p] and tp >= 0:
            E("rising_window", p, b.h[p], b.l[s], b.h[p], None, 1)        # window edge = support; close below = exit
        if b.h[s] < b.l[p] and tp <= 0:
            E("falling_window", p, b.h[s], b.l[p], b.l[p], None, -1)

    a = s - 2
    if a >= 0:
        m = s - 1
        ta, _ = prior_trend(b, a)
        lo3, hi3 = min(b.l[a:s + 1]), max(b.h[a:s + 1])
        small_star = b.body[m] <= P["star_body_max_vs_first"] * b.body[a]
        # morning / evening star (G2 7.1, G1 p6, G3 §7: star body separated below/above first; 3rd closes beyond mid of 1st)
        if b.red(a) and b.is_long(a) and small_star and b.top[m] <= b.c[a] and b.green(s) and b.c[s] > b.mid_body(a) and ta == -1:
            e = Event("morning_star", s, a, 1, lo3, hi3, float(b.l[m]), None, 1)
            e.note = "نجمة دوجي (أقوى)" if b.body_ratio[m] <= P["doji_body_max"] else ""
            ev.append(e)
        if b.green(a) and b.is_long(a) and small_star and b.bot[m] >= b.c[a] and b.red(s) and b.c[s] < b.mid_body(a) and ta == 1:
            e = Event("evening_star", s, a, -1, lo3, hi3, float(b.h[m]), None, -1)
            e.note = "نجمة دوجي (أقوى)" if b.body_ratio[m] <= P["doji_body_max"] else ""
            ev.append(e)
        # three white soldiers / black crows (G2 7.2, G1 p6)
        idx = (a, m, s)
        avgb = b.avg_body[a]
        longish = all(np.isfinite(avgb) and b.body[i] >= 0.8 * avgb for i in idx)  # DEFAULT "طويلة": >= 0.8x avg body each
        if longish and all(b.green(i) for i in idx) and b.c[a] < b.c[m] < b.c[s] \
                and b.bot[m] <= b.o[m] <= b.top[a] and b.bot[s] <= b.o[s] <= b.top[m] \
                and all(b.up[i] <= P["soldier_shadow_max"] * b.rng[i] for i in idx) and ta <= 0:
            ev.append(Event("three_white_soldiers", s, a, 1, lo3, hi3, float(b.l[a]), None, 1))
        if longish and all(b.red(i) for i in idx) and b.c[a] > b.c[m] > b.c[s] \
                and b.bot[a] <= b.o[m] <= b.top[a] and b.bot[m] <= b.o[s] <= b.top[m] \
                and all(b.lo_sh[i] <= P["soldier_shadow_max"] * b.rng[i] for i in idx) and ta >= 0:
            ev.append(Event("three_black_crows", s, a, -1, lo3, hi3, float(b.h[a]), None, -1))
        # three inside up/down (G2 7.3: harami + 3rd closes above HIGH / below LOW of the first)
        if b.is_long(a) and b.body[m] <= 0.5 * b.body[a] and b.top[m] <= b.top[a] and b.bot[m] >= b.bot[a]:
            if b.red(a) and ta == -1 and b.c[s] > b.h[a]:
                ev.append(Event("three_inside_up", s, a, 1, lo3, hi3, lo3, None, 1))
            if b.green(a) and ta == 1 and b.c[s] < b.l[a]:
                ev.append(Event("three_inside_down", s, a, -1, lo3, hi3, hi3, None, -1))

    f = s - 4
    if f >= 0:
        tf, _ = prior_trend(b, f)
        inner = range(f + 1, s)
        if b.green(f) and b.is_long(f) and tf == 1 and all(b.h[i] <= b.h[f] and b.l[i] >= b.l[f] and b.body[i] < b.body[f] for i in inner) \
                and b.green(s) and b.c[s] > b.h[f]:
            ev.append(Event("rising_three", s, f, 1, float(min(b.l[f:s + 1])), float(max(b.h[f:s + 1])), float(b.l[f]), None, 1))
        if b.red(f) and b.is_long(f) and tf == -1 and all(b.h[i] <= b.h[f] and b.l[i] >= b.l[f] and b.body[i] < b.body[f] for i in inner) \
                and b.red(s) and b.c[s] < b.l[f]:
            ev.append(Event("falling_three", s, f, -1, float(min(b.l[f:s + 1])), float(max(b.h[f:s + 1])), float(b.h[f]), None, -1))
    return ev


def weekly_trend_series(b: Bars) -> np.ndarray:
    """Weekly trend known at each daily bar (completed Tadawul weeks only, week ends Thursday).
    +1 weekly close > weekly SMA10 and SMA10 rising, -1 opposite, else 0. (G2 10.2 top-down, G3 §8)."""
    idx = b.df.index
    try:
        di = pd.DatetimeIndex(idx).tz_localize(None) if getattr(idx, "tz", None) is not None else pd.DatetimeIndex(idx)
    except Exception:
        di = pd.DatetimeIndex(idx)
    s = pd.Series(b.c, index=di)
    wk = s.resample("W-THU").last().dropna()
    sma = wk.rolling(10).mean()
    tr = pd.Series(0, index=wk.index, dtype=float)
    tr[(wk > sma) & (sma.diff() > 0)] = 1
    tr[(wk < sma) & (sma.diff() < 0)] = -1
    tr[sma.isna()] = np.nan
    # weekly value is only known after the week's last bar: shift by one week label then forward-fill to days
    known = tr.copy()
    known.index = known.index + pd.Timedelta(days=1)  # available from Friday after the week closes
    out = known.reindex(di.union(known.index)).ffill().reindex(di)
    return out.to_numpy()


def evaluate(b: Bars, e: Event, wk: Optional[np.ndarray] = None) -> Event:
    s = e.end
    d = e.direction
    t, mv = prior_trend(b, e.start)
    lv = levels(b, s)
    st = structure(b, s)
    # location: bullish needs support near pattern low; bearish needs resistance near pattern high (G1 p7, G2 4.3/9.2)
    loc = None
    if d > 0 or (d == 0 and e.confirm_side > 0):
        loc = near_level(b, s, e.low, "sup", lv)
    elif d < 0 or (d == 0 and e.confirm_side < 0):
        loc = near_level(b, s, e.high, "res", lv)
    if e.key in ("bull_marubozu", "bear_marubozu", "rising_window", "falling_window"):
        # breakout of a level is the meaningful location for marubozu/windows (G2 5.1, 9.3)
        side = "res" if e.direction > 0 else "sup"
        loc = None
        for lvl, nm in lv[side]:
            if (e.direction > 0 and b.o[s] <= lvl < b.c[s]) or (e.direction < 0 and b.c[s] < lvl <= b.o[s]) \
                    or (e.key.endswith("window") and min(b.c[s - 1], b.c[s]) <= lvl <= max(b.c[s - 1], b.c[s])):
                loc = (lvl, nm + " (اختراق)", 0.0)
                break
    rv = rvol(b, s)
    if e.key in ("morning_star", "evening_star", "three_inside_up", "three_inside_down", "rising_three", "falling_three"):
        rv = rvol(b, s)
    # confirmation (next bar only)
    if e.meta[5] in ("built_in", "no"):
        conf = True
    elif s + 1 >= b.n:
        conf = None
    else:
        nx = b.c[s + 1]
        conf = bool(nx > e.confirm_level) if e.confirm_side > 0 else bool(nx < e.confirm_level)
    e.confirmed = conf
    # invalidation after completion
    last = b.n - 1
    for i in range(s + 1, last + 1):
        if (e.confirm_side > 0 and b.c[i] < e.stop) or (e.confirm_side < 0 and b.c[i] > e.stop):
            e.failed = True
            break
    wtr = None
    if wk is not None and s < len(wk) and np.isfinite(wk[s]):
        wtr = int(wk[s])
    eff_dir = d if d != 0 else e.confirm_side
    items = {
        "shape": True,                                             # G2 10.3 (1)
        "location": bool(loc) or (e.meta[2] == "reversal" and abs(mv) >= P["extended_trend_atr"]),  # (2) level or after extended move
        "volume": (rv is not None and rv >= P["vol_clear"]),       # (3)
        "confirmation": bool(conf),                                # (4)
        "higher_tf": (wtr is None or wtr == 0 or wtr == eff_dir) if wtr is not None else False,  # (5) weekly not opposing
    }
    e.ladder_items = items
    e.ladder = sum(1 for v in items.values() if v)
    rsi = b.rsi[s] if np.isfinite(b.rsi[s]) else None
    e.ctx = {
        "prior_trend": t, "prior_move_atr": mv, "structure": st, "level": loc, "rvol": rv,
        "rsi": rsi, "above200": (bool(b.c[s] > b.sma200[s]) if np.isfinite(b.sma200[s]) else None),
        "weekly": wtr, "atr": float(b.atr[s]) if np.isfinite(b.atr[s]) else None,
        "color": int(np.sign(b.c[s] - b.o[s])),
    }
    return e


def scan_at(b: Bars, s: int, wk: Optional[np.ndarray] = None) -> list[Event]:
    return [evaluate(b, e, wk) for e in _shape_events(b, s)]


# ── scoring (shared by live analysts) ───────────────────────────────────────
_BT_CACHE: dict | None = None


def load_backtest() -> dict:
    global _BT_CACHE
    if _BT_CACHE is None:
        try:
            _BT_CACHE = json.loads(BACKTEST_JSON.read_text(encoding="utf-8"))
        except Exception:
            _BT_CACHE = {}
    return _BT_CACHE


def bt_key(key: str, eff: int) -> str:
    """Indecision candles are measured separately by the prior trend they appear after."""
    return key if PATTERNS[key][1] != 0 else f"{key}:{'down' if eff < 0 else 'up'}"


def mult_from(row: dict, confirmed: bool) -> tuple[float, str]:
    """Measured hit-rate -> confidence multiplier (RULES.md §ج, backtest.md).
    mult = clamp(1 + 2*(hit10 - base10_dir), 0.6, 1.25) when the sample n >= 30; else 1.0 (no invented accuracy).
    A confirmed live event uses the 'confirmed' subset when that subset has n >= 30."""
    base = row.get("base10_dir", 0.5)
    if confirmed and (row.get("conf_n") or 0) >= P["min_bt_n"] and row.get("conf_hit10") is not None:
        hit, n, lab = row["conf_hit10"], row["conf_n"], "مؤكد"
    else:
        hit, n, lab = row.get("hit10"), row.get("n", 0), "عام"
    if hit is None or n < P["min_bt_n"]:
        return 1.0, f"اختبار خلفي: عينة {n} (<{P['min_bt_n']}) فلا تعديل"
    mult = max(0.6, min(1.25, 1.0 + 2.0 * (hit - base)))
    return mult, f"اختبار خلفي ({lab}) 10 جلسات: إصابة {hit*100:.0f}% مقابل أساس {base*100:.0f}% (n={n}) → معامل {mult:.2f}"


def bt_multiplier(key: str, eff: int = 1, confirmed: bool = False) -> tuple[float, str]:
    bt = load_backtest()
    row = (bt.get("patterns") or {}).get(bt_key(key, eff))
    if not row:
        return 1.0, "اختبار خلفي: NOT FOUND"
    return mult_from(row, confirmed)


def score_event(e: Event) -> tuple[float, float, str]:
    """Signal & confidence from the guides' evidence ladder (G2 10.3: 3/5 = medium, 5/5 = high)."""
    name, d, kind, n, base, needs, agent, cite = e.meta
    eff = d if d != 0 else e.confirm_side
    k = e.ladder
    ladder_f = {0: 0.2, 1: 0.25, 2: 0.35, 3: 0.6, 4: 0.8, 5: 1.0}[k]
    if needs == "always" and e.confirmed is not True:
        ladder_f = min(ladder_f, 0.35)   # G1 p11, G2: hanging man/inverted hammer/harami/doji need confirmation always
    if kind == "indecision":
        mag = 0.25 + 0.25 * (k >= 4)     # G2 ص9: doji alone = attention only
    else:
        mag = 0.35 + 0.55 * ladder_f
    st = e.ctx.get("structure") or {}
    # G2 9.1: in a downtrend ignore bullish patterns except under strict conditions (and mirror)
    if st.get("dir") == -eff and k < 5 and kind != "continuation":
        mag *= 0.5
    # G1 p8: above SMA200 bullish patterns more trustworthy
    a200 = e.ctx.get("above200")
    if a200 is not None and ((eff > 0 and not a200) or (eff < 0 and a200)):
        mag *= 0.85
    rsi = e.ctx.get("rsi")
    if rsi is not None and e.key in ("hammer", "inverted_hammer", "dragonfly_doji"):
        mag *= 1.15 if rsi < P["rsi_os"] else (0.8 if rsi > P["rsi_mid"] else 1.0)
    if rsi is not None and e.key in ("shooting_star", "hanging_man", "gravestone_doji"):
        mag *= 1.15 if rsi > P["rsi_ob"] else 1.0
    # G2 5.3 / 5.4: green hammer stronger than red; red shooting star stronger than green
    if e.key in ("hammer",) and e.ctx.get("color", 0) > 0:
        mag *= 1.05
    if e.key in ("shooting_star",) and e.ctx.get("color", 0) < 0:
        mag *= 1.05
    # G2 7.2: soldiers after an extended rise may be exhaustion
    if e.key == "three_white_soldiers" and e.ctx.get("prior_move_atr", 0) >= P["extended_trend_atr"]:
        mag *= 0.5
    if e.key == "three_black_crows" and e.ctx.get("prior_move_atr", 0) <= -P["extended_trend_atr"]:
        mag *= 0.5
    # G2 5.1: marubozu after a very extended move may be exhaustion
    if kind == "continuation" and e.key.endswith("marubozu") and abs(e.ctx.get("prior_move_atr", 0)) >= 2 * P["extended_trend_atr"]:
        mag *= 0.6
    mult, bt_txt = bt_multiplier(e.key, eff, bool(e.confirmed))
    conf = (0.15 + 0.65 * base * ladder_f) * mult
    if e.confirmed is None and needs in ("always", "preferred"):
        conf *= 0.8
    sig = eff * min(1.0, mag)
    return float(sig), float(max(0.05, min(0.9, conf))), bt_txt


def describe(e: Event, dates=None) -> str:
    it = e.ladder_items
    lv = e.ctx.get("level")
    parts = [f"{e.name_ar}{(' — ' + e.note) if e.note else ''}"]
    if dates is not None:
        parts.append(f"بتاريخ {dates[e.end]}")
    parts.append(f"سلّم الأدلة {e.ladder}/5")
    parts.append("عند " + f"{lv[1]} {lv[0]:.2f}" if lv else "بلا مستوى قريب")
    rv = e.ctx.get("rvol")
    parts.append(f"حجم نسبي {rv:.2f}x" if rv is not None else "حجم NOT FOUND")
    if e.confirmed is None:
        parts.append("بانتظار شمعة التأكيد")
    else:
        parts.append("مؤكد" if e.confirmed else "لم يتأكد")
    parts.append(f"الإبطال {e.stop:.2f}")
    return "، ".join(parts)


# ── live helpers ────────────────────────────────────────────────────────────
def completed_hist(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """G1 p9 mistake 2 / G3 §2: read only completed candles. Drop today's bar during the session."""
    if df is None or df.empty:
        return df, ""
    now = datetime.now(RIYADH)
    last = df.index[-1]
    try:
        ld = last.tz_convert(RIYADH).date() if getattr(last, "tzinfo", None) else last.date()
    except Exception:
        ld = pd.Timestamp(last).date()
    if ld == now.date() and (now.hour, now.minute) < (15, 20):
        return df.iloc[:-1], "حُذفت شمعة اليوم لأنها لم تكتمل (قبل 15:20 بتوقيت الرياض)"
    return df, ""


def dates_of(b: Bars) -> list[str]:
    return [str(x)[:10] for x in b.df.index]


def live_context(data) -> Optional[dict]:
    """Cache per MarketData: bars, weekly trend, active events (last 3 bars) with dedupe."""
    cache = getattr(data, "_candle_cache", None)
    if cache is not None:
        return cache
    if data.hist is None or len(data.hist) < 60:
        data._candle_cache = None
        return None
    df, note = completed_hist(data.hist)
    b = Bars(df)
    wk = weekly_trend_series(b)
    dates = dates_of(b)
    events: list[Event] = []
    for s in range(max(0, b.n - P["active_bars"]), b.n):
        events.extend(scan_at(b, s, wk))
    # dedupe overlapping events: same direction & overlapping bars -> strongest keeps full weight
    events.sort(key=lambda e: (PATTERNS[e.key][4], e.ladder, e.end), reverse=True)
    kept: list[tuple[Event, float]] = []
    for e in events:
        overl = any(k.direction == e.direction and not (e.end < k.start or k.end < e.start) for k, _ in kept)
        kept.append((e, 0.5 if overl else 1.0))
    cache = {"bars": b, "weekly": wk, "dates": dates, "events": kept, "note": note}
    data._candle_cache = cache
    return cache


def summarize_events(cache: dict, agent_id: str):
    """Pick the active, non-failed events owned by agent_id and fold them into one vote."""
    mine = [(e, f) for e, f in cache["events"] if PATTERNS[e.key][6] == agent_id]
    if not mine:
        return None
    alive = [(e, f) for e, f in mine if not e.failed]
    failed = [e for e, _ in mine if e.failed]
    if not alive:
        return {"failed": failed}
    num = den = 0.0
    descs, bts = [], []
    for e, f in alive:
        sig, conf, bt = score_event(e)
        conf *= f
        num += sig * conf
        den += conf
        descs.append(describe(e, cache["dates"]) + (" (متداخل مع نمط أقوى: نصف الثقة)" if f < 1 else ""))
        bts.append(bt)
    sig = num / den if den else 0.0
    conf = max(c for c in [score_event(e)[1] * f for e, f in alive])
    cites = sorted({PATTERNS[e.key][7] for e, _ in alive})
    return {"signal": sig, "confidence": conf, "desc": "؛ ".join(descs), "bt": "؛ ".join(sorted(set(bts))),
            "cite": " | ".join(cites), "alive": [e for e, _ in alive], "failed": failed}
