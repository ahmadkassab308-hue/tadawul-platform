"""Deterministic technical indicators. No lookahead. Only completed bars."""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n, min_periods=n).mean()


def ema(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(span=n, adjust=False, min_periods=n).mean()


def wilder_smooth(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def wma(series: pd.Series, n: int) -> pd.Series:
    weights = np.arange(1, n + 1, dtype=float)

    def _w(x):
        return np.dot(x, weights) / weights.sum()

    return series.rolling(n, min_periods=n).apply(_w, raw=True)


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = wilder_smooth(gain, n)
    avg_loss = wilder_smooth(loss, n)
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    hist = line - sig
    return line, sig, hist


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0):
    mid = sma(close, n)
    std = close.rolling(n, min_periods=n).std(ddof=0)
    upper = mid + k * std
    lower = mid - k * std
    width = (upper - lower) / mid.replace(0.0, np.nan)
    percent_b = (close - lower) / (upper - lower).replace(0.0, np.nan)
    return mid, upper, lower, width, percent_b


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["Close"].shift(1)
    tr = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return wilder_smooth(true_range(df), n)


def stochastic(df: pd.DataFrame, n: int = 14, k_smooth: int = 3, d_smooth: int = 3):
    low_n = df["Low"].rolling(n, min_periods=n).min()
    high_n = df["High"].rolling(n, min_periods=n).max()
    raw = 100.0 * (df["Close"] - low_n) / (high_n - low_n).replace(0.0, np.nan)
    k = raw.rolling(k_smooth, min_periods=k_smooth).mean()
    d = k.rolling(d_smooth, min_periods=d_smooth).mean()
    return k, d


def adx(df: pd.DataFrame, n: int = 14):
    up = df["High"].diff()
    down = -df["Low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr_s = wilder_smooth(true_range(df), n)
    plus_di = 100.0 * wilder_smooth(plus_dm, n) / tr_s.replace(0.0, np.nan)
    minus_di = 100.0 * wilder_smooth(minus_dm, n) / tr_s.replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    adx_s = wilder_smooth(dx, n)
    return adx_s, plus_di, minus_di


def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["Close"].diff()).fillna(0.0)
    return (direction * df["Volume"]).cumsum()


def typical_price(df: pd.DataFrame) -> pd.Series:
    return (df["High"] + df["Low"] + df["Close"]) / 3.0


def vwap_rolling(df: pd.DataFrame, n: int = 20) -> pd.Series:
    tp = typical_price(df)
    pv = tp * df["Volume"]
    vol = df["Volume"].rolling(n, min_periods=n).sum()
    return pv.rolling(n, min_periods=n).sum() / vol.replace(0.0, np.nan)


def ichimoku(df: pd.DataFrame, conv: int = 9, base: int = 26, span_b: int = 52, lag: int = 26):
    """Cloud compared with price uses spans displaced by `lag` bars (no lookahead).
    Chikou is evaluated as today's close vs the close `lag` bars ago.
    """
    conv_line = (df["High"].rolling(conv, min_periods=conv).max() + df["Low"].rolling(conv, min_periods=conv).min()) / 2.0
    base_line = (df["High"].rolling(base, min_periods=base).max() + df["Low"].rolling(base, min_periods=base).min()) / 2.0
    span_a_raw = (conv_line + base_line) / 2.0
    span_b_raw = (
        df["High"].rolling(span_b, min_periods=span_b).max() + df["Low"].rolling(span_b, min_periods=span_b).min()
    ) / 2.0
    # The cloud visible today was computed `lag` bars ago.
    span_a_now = span_a_raw.shift(lag)
    span_b_now = span_b_raw.shift(lag)
    return conv_line, base_line, span_a_now, span_b_now


def supertrend(df: pd.DataFrame, n: int = 10, mult: float = 3.0):
    atr_s = atr(df, n)
    hl2 = (df["High"] + df["Low"]) / 2.0
    upper_basic = hl2 + mult * atr_s
    lower_basic = hl2 - mult * atr_s
    close = df["Close"].to_numpy(dtype=float)
    ub = upper_basic.to_numpy(dtype=float)
    lb = lower_basic.to_numpy(dtype=float)
    fu = np.full(len(df), np.nan)
    fl = np.full(len(df), np.nan)
    st = np.full(len(df), np.nan)
    direction = np.ones(len(df), dtype=int)
    for i in range(len(df)):
        if np.isnan(ub[i]) or np.isnan(lb[i]):
            continue
        if i == 0 or np.isnan(fu[i - 1]):
            fu[i] = ub[i]
            fl[i] = lb[i]
            direction[i] = 1
            st[i] = fl[i]
            continue
        fu[i] = ub[i] if (ub[i] < fu[i - 1] or close[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lb[i] if (lb[i] > fl[i - 1] or close[i - 1] < fl[i - 1]) else fl[i - 1]
        if direction[i - 1] == 1:
            if close[i] < fl[i]:
                direction[i] = -1
                st[i] = fu[i]
            else:
                direction[i] = 1
                st[i] = fl[i]
        else:
            if close[i] > fu[i]:
                direction[i] = 1
                st[i] = fl[i]
            else:
                direction[i] = -1
                st[i] = fu[i]
    return pd.Series(st, index=df.index), pd.Series(direction, index=df.index)


def donchian(df: pd.DataFrame, n: int = 20):
    return (
        df["High"].rolling(n, min_periods=n).max(),
        df["Low"].rolling(n, min_periods=n).min(),
    )


def keltner(df: pd.DataFrame, n: int = 20, atr_n: int = 20, mult: float = 1.5):
    mid = ema(df["Close"], n)
    a = atr(df, atr_n)
    return mid, mid + mult * a, mid - mult * a


def mfi(df: pd.DataFrame, n: int = 14) -> pd.Series:
    tp = typical_price(df)
    mf = tp * df["Volume"]
    pos = mf.where(tp > tp.shift(1), 0.0)
    neg = mf.where(tp < tp.shift(1), 0.0)
    pos_sum = pos.rolling(n, min_periods=n).sum()
    neg_sum = neg.rolling(n, min_periods=n).sum()
    ratio = pos_sum / neg_sum.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + ratio))


def williams_r(df: pd.DataFrame, n: int = 14) -> pd.Series:
    hh = df["High"].rolling(n, min_periods=n).max()
    ll = df["Low"].rolling(n, min_periods=n).min()
    return -100.0 * (hh - df["Close"]) / (hh - ll).replace(0.0, np.nan)


def cci(df: pd.DataFrame, n: int = 20) -> pd.Series:
    tp = typical_price(df)
    mid = sma(tp, n)
    mad = tp.rolling(n, min_periods=n).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - mid) / (0.015 * mad.replace(0.0, np.nan))


def parabolic_sar(df: pd.DataFrame, af_start: float = 0.02, af_step: float = 0.02, af_max: float = 0.2):
    high = df["High"].to_numpy(dtype=float)
    low = df["Low"].to_numpy(dtype=float)
    n = len(df)
    sar = np.full(n, np.nan)
    trend = np.ones(n, dtype=int)
    if n < 3:
        return pd.Series(sar, index=df.index), pd.Series(trend, index=df.index)
    up = bool(high[1] >= high[0])
    ep = high[1] if up else low[1]
    sar[1] = low[0] if up else high[0]
    af = af_start
    trend[1] = 1 if up else -1
    for i in range(2, n):
        prev = sar[i - 1]
        s = prev + af * (ep - prev)
        if up:
            s = min(s, low[i - 1], low[i - 2])
            if low[i] < s:
                up = False
                s = ep
                ep = low[i]
                af = af_start
            else:
                if high[i] > ep:
                    ep = high[i]
                    af = min(af + af_step, af_max)
        else:
            s = max(s, high[i - 1], high[i - 2])
            if high[i] > s:
                up = True
                s = ep
                ep = high[i]
                af = af_start
            else:
                if low[i] < ep:
                    ep = low[i]
                    af = min(af + af_step, af_max)
        sar[i] = s
        trend[i] = 1 if up else -1
    return pd.Series(sar, index=df.index), pd.Series(trend, index=df.index)


def cmf(df: pd.DataFrame, n: int = 20) -> pd.Series:
    rng = (df["High"] - df["Low"]).replace(0.0, np.nan)
    mfm = ((df["Close"] - df["Low"]) - (df["High"] - df["Close"])) / rng
    mfv = mfm * df["Volume"]
    vol = df["Volume"].rolling(n, min_periods=n).sum()
    return mfv.rolling(n, min_periods=n).sum() / vol.replace(0.0, np.nan)


def hull_ma(close: pd.Series, n: int = 21) -> pd.Series:
    half = max(1, int(n / 2))
    sqrt_n = max(1, int(np.sqrt(n)))
    raw = 2.0 * wma(close, half) - wma(close, n)
    return wma(raw, sqrt_n)


def roc(close: pd.Series, n: int = 12) -> pd.Series:
    return close.pct_change(n) * 100.0


def swing_points(df: pd.DataFrame, left: int = 5, right: int = 5):
    highs, lows = [], []
    h = df["High"].to_numpy(dtype=float)
    l = df["Low"].to_numpy(dtype=float)
    end = len(df) - right
    for i in range(left, end):
        window_h = h[i - left : i + right + 1]
        window_l = l[i - left : i + right + 1]
        if np.isfinite(h[i]) and h[i] >= np.nanmax(window_h):
            highs.append((i, float(h[i])))
        if np.isfinite(l[i]) and l[i] <= np.nanmin(window_l):
            lows.append((i, float(l[i])))
    return highs, lows


def last_valid(series: pd.Series, bars: int = 1):
    s = series.dropna()
    if len(s) < bars:
        return None
    if bars == 1:
        return float(s.iloc[-1])
    return [float(x) for x in s.iloc[-bars:]]


def compute_all(df: pd.DataFrame) -> dict:
    """Pre-compute indicators used by many analysts."""
    c = df["Close"]
    out: dict = {}
    out["sma20"] = sma(c, 20)
    out["sma50"] = sma(c, 50)
    out["sma100"] = sma(c, 100)
    out["sma200"] = sma(c, 200)
    out["ema9"] = ema(c, 9)
    out["ema12"] = ema(c, 12)
    out["ema21"] = ema(c, 21)
    out["ema26"] = ema(c, 26)
    out["ema50"] = ema(c, 50)
    out["rsi14"] = rsi(c, 14)
    out["macd_line"], out["macd_signal"], out["macd_hist"] = macd(c)
    out["bb_mid"], out["bb_up"], out["bb_lo"], out["bb_width"], out["bb_pctb"] = bollinger(c)
    out["atr14"] = atr(df, 14)
    out["atr20"] = atr(df, 20)
    out["stoch_k"], out["stoch_d"] = stochastic(df)
    out["adx"], out["plus_di"], out["minus_di"] = adx(df)
    out["obv"] = obv(df)
    out["obv_sma20"] = sma(out["obv"], 20)
    out["vwap20"] = vwap_rolling(df, 20)
    out["tenkan"], out["kijun"], out["span_a"], out["span_b"] = ichimoku(df)
    out["supertrend"], out["supertrend_dir"] = supertrend(df)
    out["donch_hi"], out["donch_lo"] = donchian(df, 20)
    out["kel_mid"], out["kel_up"], out["kel_lo"] = keltner(df)
    out["mfi14"] = mfi(df)
    out["willr"] = williams_r(df)
    out["cci20"] = cci(df)
    out["sar"], out["sar_dir"] = parabolic_sar(df)
    out["cmf20"] = cmf(df)
    out["hull21"] = hull_ma(c, 21)
    out["roc12"] = roc(c, 12)
    out["roc20"] = roc(c, 20)
    out["vol_sma20"] = sma(df["Volume"], 20)
    out["vol_sma50"] = sma(df["Volume"], 50)
    # realized vol
    ret = np.log(c / c.shift(1))
    out["rvol20"] = ret.rolling(20, min_periods=20).std() * np.sqrt(252)
    out["rvol60"] = ret.rolling(60, min_periods=60).std() * np.sqrt(252)
    down = ret.clip(upper=0.0)
    out["dvol20"] = down.rolling(20, min_periods=20).std() * np.sqrt(252)
    out["swings_hi"], out["swings_lo"] = swing_points(df)
    return out
