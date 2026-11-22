"""Technical analyst scoring functions."""
from __future__ import annotations

import numpy as np

from .analysts_common import fmt, fmt_pct, ind, linear_score, need_bars, nf, ok, register, src_hist
from .models import MarketData


@register(
    "trend-ema",
    "وكيل اتجاه المتوسطات الأسية",
    "EMA Trend",
    "technical",
    "technical",
    "trend-ema.md",
    1.0,
    "قياس اتجاه السعر عبر محاذاة EMA 12/26/50 وموقع الإغلاق منها.",
    "سلسلة الإغلاق اليومية من Yahoo Finance، مؤشرات ema12 و ema26 و ema50.",
    "إشارة صعود إذا كان EMA12 > EMA26 > EMA50 والسعر فوق EMA50؛ والعكس للهبوط. قوة الإشارة تتناسب مع ابتعاد السعر عن EMA50 كنسبة من ATR.",
)
def trend_ema(data: MarketData, spec):
    if not need_bars(data, 60):
        return nf(spec, "عدد الشموع غير كافٍ لحساب EMA50.", src_hist(data))
    e12, e26, e50 = ind(data, "ema12"), ind(data, "ema26"), ind(data, "ema50")
    atr = ind(data, "atr14")
    if None in (e12, e26, e50, atr) or atr == 0:
        return nf(spec, "تعذر حساب المتوسطات الأسية أو ATR.", src_hist(data))
    px = data.price
    align = (1 if e12 > e26 else -1) + (1 if e26 > e50 else -1) + (1 if px > e50 else -1)
    dist = (px - e50) / atr
    signal = 0.35 * (align / 3.0) + 0.65 * max(-1.0, min(1.0, dist / 3.0))
    conf = 0.55 + 0.15 * abs(align) / 3.0
    return ok(
        spec,
        signal,
        conf,
        f"محاذاة EMA 12/26/50 = {fmt(e12)}/{fmt(e26)}/{fmt(e50)} والإغلاق {fmt(px)} يبعد {fmt(dist, 1)} ATR عن EMA50.",
        src_hist(data),
    )


@register(
    "trend-sma",
    "وكيل اتجاه المتوسطات البسيطة",
    "SMA Trend",
    "technical",
    "technical",
    "trend-sma.md",
    1.0,
    "تحديد الاتجاه العام عبر SMA 20/50/200 وموقع السعر منها.",
    "سلسلة الإغلاق، sma20 و sma50 و sma200 (SMA200 يتطلب تاريخاً كافياً).",
    "نظام كلاسيكي: سعر فوق المتوسطات الأطول مع ترتيب تصاعدي = صاعد. إن نقص SMA200 تُستخدم 20/50 بثقة أقل.",
)
def trend_sma(data: MarketData, spec):
    s20, s50, s200 = ind(data, "sma20"), ind(data, "sma50"), ind(data, "sma200")
    if s20 is None or s50 is None:
        return nf(spec, "عدد الشموع غير كافٍ لحساب SMA20/50.", src_hist(data))
    px = data.price
    if s200 is None:
        sig = (0.5 if px > s20 else -0.5) + (0.5 if s20 > s50 else -0.5)
        return ok(
            spec,
            sig,
            0.45,
            f"SMA200 غير متاح (تاريخ أقصر من 200 يوم). SMA20={fmt(s20)} وSMA50={fmt(s50)} والسعر {fmt(px)}.",
            src_hist(data),
        )
    parts = [(px > s20), (px > s50), (px > s200), (s20 > s50), (s50 > s200)]
    score = sum(1 if p else -1 for p in parts) / len(parts)
    return ok(
        spec,
        score,
        0.7,
        f"السعر {fmt(px)} مقابل SMA20/50/200 = {fmt(s20)}/{fmt(s50)}/{fmt(s200)} "
        f"{'وترتيب صاعد' if s20 > s50 > s200 else 'بدون ترتيب صاعد كامل'}.",
        src_hist(data),
    )


@register(
    "rsi",
    "وكيل القوة النسبية RSI",
    "RSI",
    "technical",
    "technical",
    "rsi.md",
    1.0,
    "رصد التشبع الشرائي/البيعي وزخم RSI(14) بأسلوب وايلدر.",
    "إغلاق يومي، مؤشر rsi14.",
    "RSI>70 تشبع شرائي (إشارة سالبة)، RSI<30 تشبع بيعي (موجبة). بين 40 و60 إشارة ضعيفة حول الصفر مع ثقة أقل. فوق/تحت 50 يُعطي ميلاً اتجاهياً خفيفاً.",
)
def rsi_agent(data: MarketData, spec):
    r = ind(data, "rsi14")
    prev = None
    series = data.indicators.get("rsi14")
    if series is not None:
        s = series.dropna()
        if len(s) >= 2:
            prev = float(s.iloc[-2])
    if r is None:
        return nf(spec, "تعذر حساب RSI(14).", src_hist(data))
    if r >= 70:
        sig, conf = -linear_score(min(r, 90), 70, 90), 0.75
        # linear_score(90,70,90)=1 so we want negative; use
        sig = -min(1.0, (r - 70) / 20.0)
        conf = 0.7 + 0.2 * min(1.0, (r - 70) / 15.0)
        txt = "تشبع شرائي"
    elif r <= 30:
        sig = min(1.0, (30 - r) / 20.0)
        conf = 0.7 + 0.2 * min(1.0, (30 - r) / 15.0)
        txt = "تشبع بيعي"
    else:
        sig = (r - 50) / 40.0  # mild trend reading in the mid zone
        conf = 0.4
        txt = "منطقة وسطى"
    if prev is not None and abs(r - prev) >= 3:
        txt += f" (تحرك من {fmt(prev, 1)})"
    return ok(spec, sig, conf, f"RSI(14) عند {fmt(r, 1)} — {txt}.", src_hist(data))


@register(
    "macd",
    "وكيل MACD",
    "MACD",
    "technical",
    "technical",
    "macd.md",
    1.05,
    "قياس زخم الاتجاه عبر خط MACD وإشارته والهيستوغرام (12/26/9).",
    "إغلاق يومي، macd_line و macd_signal و macd_hist.",
    "تقاطع صاعد + هيستوغرام موجّب ومتوسع = شراء. تقاطع هابط أو هيستوغرام سالب متوسع = بيع. الإشارة تُوزن بحجم الهيستوغرام نسبةً إلى السعر.",
)
def macd_agent(data: MarketData, spec):
    line, sig, hist = ind(data, "macd_line"), ind(data, "macd_signal"), ind(data, "macd_hist")
    series = data.indicators.get("macd_hist")
    prev_h = None
    if series is not None:
        s = series.dropna()
        if len(s) >= 2:
            prev_h = float(s.iloc[-2])
    if None in (line, sig, hist):
        return nf(spec, "تعذر حساب MACD.", src_hist(data))
    cross = 0.45 if line > sig else -0.45
    sign_h = 0.35 if hist > 0 else -0.35
    expand = 0.0
    if prev_h is not None:
        if hist > 0 and hist > prev_h:
            expand = 0.2
        elif hist < 0 and hist < prev_h:
            expand = -0.2
    signal = cross + sign_h + expand
    state = "تقاطع صاعد" if line > sig else "تقاطع هابط"
    return ok(
        spec,
        signal,
        0.68,
        f"MACD {fmt(line, 3)} مقابل الإشارة {fmt(sig, 3)} ({state}) والهيستوغرام {fmt(hist, 3)}.",
        src_hist(data),
    )


@register(
    "moving-averages-crossover",
    "وكيل تقاطع المتوسطات (ذهبي/ميت)",
    "Golden / Death Cross",
    "technical",
    "technical",
    "moving-averages-crossover.md",
    1.1,
    "رصد التقاطع الذهبي أو الميت بين SMA50 و SMA200، وموقع السعر منهما.",
    "sma50 و sma200 من سلسلة الإغلاق.",
    "SMA50 فوق SMA200 = تقاطع ذهبي (صاعد) والعكس تقاطع ميت. قرب التقاطع يرفع الثقة إذا وقع حديثاً (آخر 20 يوم).",
)
def ma_cross(data: MarketData, spec):
    s50, s200 = data.indicators.get("sma50"), data.indicators.get("sma200")
    if s50 is None or s200 is None:
        return nf(spec, "تعذر حساب SMA50/200.", src_hist(data))
    a = s50.dropna()
    b = s200.dropna()
    joined = a.to_frame("s50").join(b.to_frame("s200"), how="inner")
    if len(joined) < 5:
        return nf(spec, "التاريخ غير كافٍ لتقاطع SMA50/200.", src_hist(data))
    diff = joined["s50"] - joined["s200"]
    last = float(diff.iloc[-1])
    bull = last > 0
    # recency of cross
    recency = None
    for i in range(1, min(len(diff), 60)):
        if (float(diff.iloc[-i]) > 0) != bull:
            recency = i - 1
            break
    px = data.price
    s50v, s200v = float(joined["s50"].iloc[-1]), float(joined["s200"].iloc[-1])
    sig = 0.7 if bull else -0.7
    if px > s50v > s200v:
        sig = 0.85
    elif px < s50v < s200v:
        sig = -0.85
    conf = 0.62
    extra = "ترتيب قائم"
    if recency is not None and recency <= 20:
        conf = 0.8
        extra = f"تقاطع خلال آخر {recency} يوم"
    elif recency is None:
        extra = "لم يُرصد تقاطع خلال النافذة المتاحة"
    kind = "ذهبي" if bull else "ميت"
    return ok(
        spec,
        sig,
        conf,
        f"وضع {kind}: SMA50={fmt(s50v)} وSMA200={fmt(s200v)} ({extra}).",
        src_hist(data),
    )


@register(
    "bollinger",
    "وكيل بولينجر",
    "Bollinger Bands",
    "technical",
    "technical",
    "bollinger.md",
    1.0,
    "تحديد موقع السعر داخل نطاق بولينجر (20، انحرافين) والانضغاط.",
    "bb_pctb و bb_width و bb_up/lo.",
    "percentB فوق 1 (إغلاق فوق النطاق العلوي) إشارة تشبع شرائي سالبة، تحت 0 تشبع بيعي موجبة. عرض النطاق الضيق جداً يخفض ثقة الاتجاه ويرفع احتمال اختراق لاحق دون تخمين اتجاهه (إشارة أقرب للحياد).",
)
def bollinger_agent(data: MarketData, spec):
    pctb, width = ind(data, "bb_pctb"), ind(data, "bb_width")
    up, lo, mid = ind(data, "bb_up"), ind(data, "bb_lo"), ind(data, "bb_mid")
    if None in (pctb, width, up, lo, mid):
        return nf(spec, "تعذر حساب نطاقات بولينجر.", src_hist(data))
    # mean-reversion at extremes
    if pctb >= 1.0:
        sig = -0.55 - 0.25 * min(1.0, pctb - 1.0)
        txt = "إغلاق فوق النطاق العلوي"
        conf = 0.7
    elif pctb <= 0.0:
        sig = 0.55 + 0.25 * min(1.0, -pctb)
        txt = "إغلاق تحت النطاق السفلي"
        conf = 0.7
    else:
        sig = (pctb - 0.5) * 0.6  # mild
        txt = "داخل النطاق"
        conf = 0.4
    w_series = data.indicators.get("bb_width")
    squeeze = False
    if w_series is not None:
        ws = w_series.dropna()
        if len(ws) >= 60:
            q20 = float(ws.iloc[-60:].quantile(0.2))
            squeeze = width <= q20
    if squeeze:
        conf *= 0.75
        txt += " مع انضغاط العرض (ثقة اتجاه أقل)"
    return ok(
        spec,
        sig,
        conf,
        f"%B={fmt(pctb, 2)} والعرض النسبي {fmt(width, 3)} والنطاق {fmt(lo)}–{fmt(up)} — {txt}.",
        src_hist(data),
    )


@register(
    "volume-surge",
    "وكيل حجم التداول",
    "Volume Surge",
    "technical",
    "technical",
    "volume-surge.md",
    0.9,
    "تأكيد حركة السعر بحجم التداول مقابل متوسط 20 يوماً.",
    "Volume اليومي و vol_sma20 وإغلاق اليوم السابق.",
    "حجم أعلى من 1.5× المتوسط مع إغلاق صاعد = تأكيد شراء، ومع إغلاق هابط = تأكيد بيع. حجم ضعيف يُضعف الإشارة.",
)
def volume_surge(data: MarketData, spec):
    if not need_bars(data, 21):
        return nf(spec, "التاريخ غير كافٍ لمتوسط الحجم.", src_hist(data))
    vol = float(data.hist["Volume"].iloc[-1])
    avg = ind(data, "vol_sma20")
    if avg is None or avg == 0:
        return nf(spec, "متوسط الحجم غير متاح أو صفر.", src_hist(data))
    ratio = vol / avg
    chg = 0.0
    if data.prev_close:
        chg = data.price / data.prev_close - 1.0
    if ratio >= 1.5:
        sig = 0.7 if chg > 0 else (-0.7 if chg < 0 else 0.0)
        conf = min(0.85, 0.5 + 0.15 * (ratio - 1.5))
        txt = "حجم مرتفع يؤكد اتجاه الإغلاق"
    elif ratio <= 0.6:
        sig = -0.15 if chg > 0 else 0.1
        conf = 0.4
        txt = "حجم ضعيف لا يؤكد الحركة"
    else:
        sig = (0.25 if chg > 0 else -0.25) * min(1.0, ratio / 1.2)
        conf = 0.35
        txt = "حجم قريب من المتوسط"
    return ok(
        spec,
        sig,
        conf,
        f"الحجم {vol:,.0f} مقابل متوسط 20 يوماً {avg:,.0f} (×{fmt(ratio, 2)}) مع تغير {fmt_pct(chg)} — {txt}.",
        src_hist(data),
    )


@register(
    "support-resistance",
    "وكيل الدعم والمقاومة",
    "Support / Resistance",
    "technical",
    "technical",
    "support-resistance.md",
    1.05,
    "تحديد أقرب دعم ومقاومة من قمم وقيعان محلية ونطاق 20 يوماً.",
    "شموع عالية/منخفضة، نقاط swing (5/5)، دونشيان 20.",
    "قرب الدعم من الأسفل مع عدم كسره = ميل شرائي. قرب المقاومة مع ضغط عليها = ميل بيعي. الكسر دون الدعم إشارة سالبة والكسر فوق المقاومة موجبة.",
)
def support_resistance(data: MarketData, spec):
    highs, lows = data.indicators.get("swings_hi") or [], data.indicators.get("swings_lo") or []
    if not highs and not lows:
        return nf(spec, "لم تُستخرج قمم/قيعان محلية كافية.", src_hist(data))
    px = data.price
    atr = ind(data, "atr14") or (px * 0.02)
    # nearest resistance above, support below
    res = [p for _, p in highs if p > px]
    sup = [p for _, p in lows if p < px]
    # also recent 20-day high/low
    donch_hi, donch_lo = ind(data, "donch_hi"), ind(data, "donch_lo")
    if donch_hi and donch_hi > px:
        res.append(donch_hi)
    if donch_lo and donch_lo < px:
        sup.append(donch_lo)
    r = min(res) if res else None
    s = max(sup) if sup else None
    if r is None and s is None:
        return nf(spec, "لا دعم أو مقاومة واضحة فوق/تحت السعر الحالي.", src_hist(data))
    sig, conf, bits = 0.0, 0.5, []
    if s is not None:
        dist_s = (px - s) / atr
        bits.append(f"دعم {fmt(s)} (يبعد {fmt(dist_s, 1)} ATR)")
        if dist_s <= 1.0:
            sig += 0.55
            conf += 0.15
        elif dist_s <= 2.0:
            sig += 0.2
    if r is not None:
        dist_r = (r - px) / atr
        bits.append(f"مقاومة {fmt(r)} (تبعد {fmt(dist_r, 1)} ATR)")
        if dist_r <= 1.0:
            sig -= 0.55
            conf += 0.15
        elif dist_r <= 2.0:
            sig -= 0.2
    # breakout vs 20-day
    if donch_hi and px >= donch_hi * 0.999:
        sig += 0.35
        bits.append("عند أعلى 20 يوماً")
    if donch_lo and px <= donch_lo * 1.001:
        sig -= 0.35
        bits.append("عند أدنى 20 يوماً")
    return ok(spec, sig, min(0.85, conf), "؛ ".join(bits) + ".", src_hist(data))


@register(
    "chart-patterns",
    "وكيل النماذج السعرية",
    "Chart Patterns / Market Structure",
    "technical",
    "technical",
    "chart-patterns.md",
    0.95,
    "قراءة هيكل السوق (قمم/قيعان أعلى أو أدنى) ونماذج بسيطة كالقمة/القاع المزدوج التقريبي.",
    "نقاط الـ swing المستخرجة من الشموع اليومية.",
    "HH+HL = هيكل صاعد. LH+LL = هيكل هابط. قاعان متقاربان سعرياً بعد هبوط = قاع مزدوج محتمل (ثقة محدودة).",
)
def chart_patterns(data: MarketData, spec):
    highs, lows = data.indicators.get("swings_hi") or [], data.indicators.get("swings_lo") or []
    if len(highs) < 2 or len(lows) < 2:
        return nf(spec, "عدد القمم/القيعان غير كافٍ لقراءة الهيكل.", src_hist(data))
    h1, h2 = highs[-2][1], highs[-1][1]
    l1, l2 = lows[-2][1], lows[-1][1]
    hh, hl = h2 > h1, l2 > l1
    lh, ll = h2 < h1, l2 < l1
    sig, conf, label = 0.0, 0.5, "هيكل مختلط"
    if hh and hl:
        sig, conf, label = 0.7, 0.65, "قمم وقيعان أعلى (هيكل صاعد)"
    elif lh and ll:
        sig, conf, label = -0.7, 0.65, "قمم وقيعان أدنى (هيكل هابط)"
    elif hh and not hl:
        sig, conf, label = 0.25, 0.45, "قمة أعلى دون قاع أعلى"
    elif ll and not lh:
        sig, conf, label = -0.25, 0.45, "قاع أدنى دون قمة أدنى"
    # rough double bottom / top
    atr = ind(data, "atr14") or data.price * 0.02
    if abs(l2 - l1) <= 0.6 * atr and l2 <= min(l1, l2) + 0.6 * atr and data.price > max(l1, l2):
        if not (hh and hl):
            sig += 0.25
            label += " مع قاعين متقاربين"
    if abs(h2 - h1) <= 0.6 * atr and data.price < min(h1, h2):
        if not (lh and ll):
            sig -= 0.25
            label += " مع قمتين متقاربتين"
    return ok(
        spec,
        sig,
        conf,
        f"{label}: آخر قمتين {fmt(h1)} ثم {fmt(h2)} وآخر قاعين {fmt(l1)} ثم {fmt(l2)}.",
        src_hist(data),
    )


@register(
    "momentum-roc",
    "وكيل الزخم (معدل التغير)",
    "Momentum ROC",
    "technical",
    "technical",
    "momentum-roc.md",
    0.95,
    "قياس الزخم السعري عبر معدل التغير لـ 12 و 20 يوماً.",
    "roc12 و roc20 من الإغلاق.",
    "زخم موجب قوي = إشارة شراء، وسالب قوي = بيع. تضارب الأفقين يخفض الثقة.",
)
def momentum_roc(data: MarketData, spec):
    r12, r20 = ind(data, "roc12"), ind(data, "roc20")
    if r12 is None and r20 is None:
        return nf(spec, "تعذر حساب معدل التغير.", src_hist(data))
    r12 = r12 if r12 is not None else r20
    r20 = r20 if r20 is not None else r12
    # roc is in percent
    sig = 0.5 * np.tanh(r12 / 8.0) + 0.5 * np.tanh(r20 / 10.0)
    conf = 0.45 + 0.25 * min(1.0, abs(sig))
    if (r12 > 0) != (r20 > 0):
        conf *= 0.7
        note = "مع تضارب بين أفقي 12 و20 يوماً"
    else:
        note = "باتفاق الأفقين"
    return ok(
        spec,
        float(sig),
        conf,
        f"معدل التغير 12 يوماً {fmt(r12, 1)}% و20 يوماً {fmt(r20, 1)}% {note}.",
        src_hist(data),
    )


@register(
    "volatility-atr",
    "وكيل التقلب (ATR)",
    "ATR Volatility",
    "technical",
    "technical",
    "volatility-atr.md",
    0.85,
    "تقدير نظام التقلب الحالي عبر ATR% مقارنةً بمتوسطه التاريخي.",
    "atr14 والسعر وإغلاق 60 يوماً.",
    "تقلب منخفض نسبياً بعد اتجاه واضح يدعم استمرار هادئ (ميل خفيف مع الاتجاه). تقلب منفجر بعد حركة حادة يخفض جودة الدخول (إشارة حذر سالبة خفيفة). الوكيل ليس اتجاهياً صرفاً.",
)
def volatility_atr(data: MarketData, spec):
    atr_s = data.indicators.get("atr14")
    if atr_s is None or not need_bars(data, 40):
        return nf(spec, "تعذر حساب ATR أو التاريخ قصير.", src_hist(data))
    a = ind(data, "atr14")
    if a is None or data.price == 0:
        return nf(spec, "قيمة ATR غير متاحة.", src_hist(data))
    atr_pct = a / data.price
    hist_pct = (atr_s / data.hist["Close"]).dropna()
    if len(hist_pct) < 30:
        return nf(spec, "لا تكفي مشاهدات ATR% للمقارنة التاريخية.", src_hist(data))
    med = float(hist_pct.iloc[-60:].median()) if len(hist_pct) else float(hist_pct.median())
    ratio = atr_pct / med if med else None
    if ratio is None:
        return nf(spec, "متوسط ATR% التاريخي غير صالح.", src_hist(data))
    # direction of last 20d
    r20 = ind(data, "roc20") or 0.0
    if ratio > 1.6:
        sig = -0.35 if abs(r20) > 5 else -0.2
        txt = "تقلب مرتفع جداً مقابل وسيطه — جودة الدخول أضعف"
        conf = 0.6
    elif ratio < 0.7:
        sig = 0.15 if r20 > 0 else (-0.15 if r20 < 0 else 0.05)
        txt = "تقلب منخفض (انضغاط) — يميل مع الاتجاه الحالي بثقة محدودة"
        conf = 0.5
    else:
        sig = 0.05 if r20 > 0 else -0.05
        txt = "تقلب ضمن نطاقه المعتاد"
        conf = 0.4
    return ok(
        spec,
        sig,
        conf,
        f"ATR(14) = {fmt(a, 3)} أي {fmt_pct(atr_pct)} من السعر، ويساوي {fmt(ratio, 2)}× الوسيط التاريخي — {txt}.",
        src_hist(data),
    )


@register(
    "stochastic",
    "وكيل ستوكاستيك",
    "Stochastic Oscillator",
    "technical",
    "technical",
    "stochastic.md",
    0.9,
    "قياس الزخم السعري داخل النطاق عبر %K و %D (14،3،3).",
    "stoch_k و stoch_d.",
    "فوق 80 تشبع شرائي، تحت 20 تشبع بيعي. تقاطع %K لـ %D يُستخدم كتأكيد.",
)
def stochastic_agent(data: MarketData, spec):
    k, d = ind(data, "stoch_k"), ind(data, "stoch_d")
    if k is None or d is None:
        return nf(spec, "تعذر حساب ستوكاستيك.", src_hist(data))
    if k <= 20:
        sig = 0.5 + 0.3 * (20 - k) / 20.0
        conf = 0.7
        txt = "تشبع بيعي"
    elif k >= 80:
        sig = -0.5 - 0.3 * (k - 80) / 20.0
        conf = 0.7
        txt = "تشبع شرائي"
    else:
        sig = (k - 50) / 80.0
        conf = 0.4
        txt = "منتصف النطاق"
    if k > d:
        sig += 0.15
        txt += " مع تقاطع صاعد لـ %K"
    else:
        sig -= 0.15
        txt += " مع %K تحت %D"
    return ok(spec, sig, conf, f"ستوكاستيك %K={fmt(k, 1)} و %D={fmt(d, 1)} — {txt}.", src_hist(data))


@register(
    "adx-dmi",
    "وكيل قوة الاتجاه ADX/DMI",
    "ADX / DMI",
    "technical",
    "technical",
    "adx-dmi.md",
    1.05,
    "قياس قوة الاتجاه واتجاهه عبر ADX و +DI و -DI.",
    "adx و plus_di و minus_di.",
    "ADX فوق 25 اتجاه قوي (ثقة أعلى). إشارة الاتجاه من فرق +DI و -DI. ADX تحت 20 سوق عرضي (إشارة أقرب للصفر وثقة أقل).",
)
def adx_dmi(data: MarketData, spec):
    adx_v, pdi, mdi = ind(data, "adx"), ind(data, "plus_di"), ind(data, "minus_di")
    if None in (adx_v, pdi, mdi):
        return nf(spec, "تعذر حساب ADX/DMI.", src_hist(data))
    di_diff = (pdi - mdi) / 50.0
    if adx_v < 20:
        sig = 0.25 * max(-1, min(1, di_diff))
        conf = 0.35
        txt = "سوق أقرب للعرضي"
    else:
        strength = min(1.0, (adx_v - 20) / 25.0)
        sig = max(-1, min(1, di_diff)) * (0.5 + 0.5 * strength)
        conf = 0.5 + 0.3 * strength
        txt = "اتجاه قوي" if adx_v >= 25 else "اتجاه متوسط"
    side = "+DI يتقدم" if pdi > mdi else "-DI يتقدم"
    return ok(
        spec,
        sig,
        conf,
        f"ADX={fmt(adx_v, 1)} و+DI={fmt(pdi, 1)} و-DI={fmt(mdi, 1)} — {txt} و{side}.",
        src_hist(data),
    )


@register(
    "obv",
    "وكيل حجم التوازن OBV",
    "On-Balance Volume",
    "technical",
    "technical",
    "obv.md",
    0.9,
    "كشف تأكيد أو تضارب التدفق الحجمي عبر OBV مقابل متوسطه ومتوسط السعر.",
    "obv و obv_sma20 و sma20 للسعر.",
    "OBV فوق متوسطه مع سعر صاعد = تأكيد شراء. OBV هابط والسعر صاعد = تضارب سلبي.",
)
def obv_agent(data: MarketData, spec):
    o, osma = ind(data, "obv"), ind(data, "obv_sma20")
    s20 = ind(data, "sma20")
    if o is None or osma is None:
        return nf(spec, "تعذر حساب OBV أو متوسطه.", src_hist(data))
    series = data.indicators.get("obv")
    slope = None
    if series is not None and len(series.dropna()) >= 21:
        s = series.dropna()
        slope = float(s.iloc[-1] - s.iloc[-21])
    px_up = s20 is not None and data.price > s20
    obv_up = o > osma
    if obv_up and px_up:
        sig, conf, txt = 0.6, 0.65, "الحجم يؤكد صعود السعر"
    elif (not obv_up) and (not px_up):
        sig, conf, txt = -0.6, 0.65, "الحجم يؤكد هبوط السعر"
    elif (not obv_up) and px_up:
        sig, conf, txt = -0.35, 0.6, "تضارب: السعر فوق متوسطه وOBV ضعيف"
    else:
        sig, conf, txt = 0.25, 0.55, "تضارب: OBV صاعد والسعر تحت متوسطه"
    if slope is not None:
        txt += f" (تغير OBV في 20 يوماً {slope:,.0f})"
    return ok(spec, sig, conf, txt + ".", src_hist(data))


@register(
    "vwap",
    "وكيل VWAP",
    "Rolling VWAP",
    "technical",
    "technical",
    "vwap.md",
    0.85,
    "مقارنة الإغلاق بمتوسط السعر المرجح بالحجم لـ 20 يوماً (تقريب VWAP المتداول يومياً).",
    "vwap20 والإغلاق وATR.",
    "إغلاق فوق VWAP20 ميل شرائي، وتحته ميل بيعي. المسافة تُقاس بـ ATR. ملاحظة: هذا VWAP نافذة متحركة وليس VWAP جلسة واحدة.",
)
def vwap_agent(data: MarketData, spec):
    v = ind(data, "vwap20")
    atr = ind(data, "atr14")
    if v is None or atr is None or atr == 0:
        return nf(spec, "تعذر حساب VWAP20 أو ATR.", src_hist(data))
    dist = (data.price - v) / atr
    sig = max(-1.0, min(1.0, dist / 2.0))
    conf = 0.5 + 0.15 * min(1.0, abs(dist) / 2.0)
    side = "فوق" if data.price >= v else "تحت"
    return ok(
        spec,
        sig,
        conf,
        f"الإغلاق {fmt(data.price)} {side} VWAP(20) عند {fmt(v)} بمسافة {fmt(dist, 1)} ATR. المصدر نافذة متحركة لا VWAP جلسة.",
        src_hist(data),
    )


@register(
    "ichimoku",
    "وكيل إيشيموكو",
    "Ichimoku Cloud",
    "technical",
    "technical",
    "ichimoku.md",
    1.05,
    "قراءة الاتجاه عبر السحابة (سينكو أ/ب بعد الإزاحة 26) وتنكان/كيجون دون النظر إلى المستقبل.",
    "tenkan و kijun و span_a و span_b والإغلاق. السحابة المعروضة اليوم محسوبة قبل 26 يوماً.",
    "سعر فوق السحابة مع تنكان فوق كيجون = صاعد. تحت السحابة = هابط. داخل السحابة = محايد بثقة أقل.",
)
def ichimoku_agent(data: MarketData, spec):
    tenkan, kijun = ind(data, "tenkan"), ind(data, "kijun")
    sa, sb = ind(data, "span_a"), ind(data, "span_b")
    if None in (tenkan, kijun, sa, sb):
        return nf(spec, "التاريخ غير كافٍ لإيشيموكو (يلزم 52+26 شمعة).", src_hist(data))
    cloud_top, cloud_bot = max(sa, sb), min(sa, sb)
    px = data.price
    if px > cloud_top:
        loc, loc_sig = "فوق السحابة", 0.55
    elif px < cloud_bot:
        loc, loc_sig = "تحت السحابة", -0.55
    else:
        loc, loc_sig = "داخل السحابة", 0.0
    tk = 0.3 if tenkan > kijun else -0.3
    # chikou equivalent: close vs close 26 ago
    if len(data.hist) >= 27:
        past = float(data.hist["Close"].iloc[-27])
        ch = 0.15 if px > past else -0.15
    else:
        ch = 0.0
    sig = loc_sig + tk + ch
    conf = 0.55 if loc_sig != 0 else 0.35
    return ok(
        spec,
        sig,
        conf,
        f"السعر {loc} (أ={fmt(sa)}، ب={fmt(sb)}) وتنكان {fmt(tenkan)} مقابل كيجون {fmt(kijun)}.",
        src_hist(data),
    )


@register(
    "supertrend",
    "وكيل سوبرترند",
    "Supertrend",
    "technical",
    "technical",
    "supertrend.md",
    1.05,
    "اتجاه سوبرترند (ATR 10 × 3) كمرشح اتجاه.",
    "supertrend و supertrend_dir.",
    "اتجاه +1 (السعر فوق الخط) إشارة شراء، -1 إشارة بيع. المسافة من الخط كدعم/مقاومة ديناميكية تعدّل الثقة.",
)
def supertrend_agent(data: MarketData, spec):
    st, d = ind(data, "supertrend"), ind(data, "supertrend_dir")
    if st is None or d is None:
        return nf(spec, "تعذر حساب سوبرترند.", src_hist(data))
    atr = ind(data, "atr14") or abs(data.price - st) or 1.0
    dist = abs(data.price - st) / atr if atr else 0
    sig = 0.7 if d > 0 else -0.7
    conf = 0.6 + 0.15 * min(1.0, dist / 2.0)
    side = "صاعد" if d > 0 else "هابط"
    return ok(
        spec,
        sig,
        conf,
        f"سوبرترند {side} عند {fmt(st)} والإغلاق {fmt(data.price)} (مسافة {fmt(dist, 1)} ATR).",
        src_hist(data),
    )


# candlestick-patterns: retired 2026-11-22 — superseded by the 18-analyst candlestick group
# (engine/analysts_candles.py, knowledge/candlesticks/RULES.md). See decisions.md.


@register(
    "donchian-breakout",
    "وكيل اختراق دونشيان",
    "Donchian Breakout",
    "technical",
    "technical",
    "donchian-breakout.md",
    0.95,
    "رصد اختراق أعلى أو أدنى 20 يوماً (قناة دونشيان).",
    "donch_hi و donch_lo والإغلاق.",
    "إغلاق عند أعلى القناة أو فوقها = اختراق صاعد. عند الأدنى = اختراق هابط. في وسط القناة إشارة أضعف حسب الموقع النسبي.",
)
def donchian_agent(data: MarketData, spec):
    hi, lo = ind(data, "donch_hi"), ind(data, "donch_lo")
    if hi is None or lo is None or hi == lo:
        return nf(spec, "تعذر حساب قناة دونشيان 20.", src_hist(data))
    # Donchian high includes today; compare also to prior high
    series_h = data.indicators.get("donch_hi")
    series_l = data.indicators.get("donch_lo")
    pos = (data.price - lo) / (hi - lo)
    prev_hi = prev_lo = None
    if series_h is not None and len(series_h.dropna()) >= 2:
        # 20-day high excluding today approx: high of prior 20
        if len(data.hist) >= 21:
            prev_hi = float(data.hist["High"].iloc[-21:-1].max())
            prev_lo = float(data.hist["Low"].iloc[-21:-1].min())
    if prev_hi is not None and data.price > prev_hi:
        sig, conf, txt = 0.8, 0.75, f"اختراق أعلى {fmt(prev_hi)} (20 يوماً السابقة)"
    elif prev_lo is not None and data.price < prev_lo:
        sig, conf, txt = -0.8, 0.75, f"كسر أدنى {fmt(prev_lo)} (20 يوماً السابقة)"
    else:
        sig = (pos - 0.5) * 1.2
        conf = 0.4
        txt = f"داخل القناة عند موقع نسبي {fmt(pos, 2)}"
    return ok(
        spec,
        sig,
        conf,
        f"قناة دونشيان 20: {fmt(lo)}–{fmt(hi)} والإغلاق {fmt(data.price)} — {txt}.",
        src_hist(data),
    )


@register(
    "keltner-squeeze",
    "وكيل انضغاط كيلتنر/بولينجر",
    "Keltner / Bollinger Squeeze",
    "technical",
    "technical",
    "keltner-squeeze.md",
    0.85,
    "كشف الانضغاط عندما يقع نطاق بولينجر داخل قناة كيلتنر، ثم موقع السعر من كيلتنر.",
    "نطاقات بولينجر وقناة كيلتنر.",
    "انضغاط وحده لا يعطي اتجاهاً (حياد بثقة منخفضة). خروج السعر فوق كيلتنر العلوي بعد/بدون انضغاط = ميل صاعد، والعكس هابط.",
)
def keltner_agent(data: MarketData, spec):
    bu, bl = ind(data, "bb_up"), ind(data, "bb_lo")
    ku, kl, km = ind(data, "kel_up"), ind(data, "kel_lo"), ind(data, "kel_mid")
    if None in (bu, bl, ku, kl, km):
        return nf(spec, "تعذر حساب بولينجر أو كيلتنر.", src_hist(data))
    squeeze = bu < ku and bl > kl
    if data.price > ku:
        sig, txt = 0.65, "إغلاق فوق كيلتنر العلوي"
        conf = 0.7 if squeeze else 0.55
    elif data.price < kl:
        sig, txt = -0.65, "إغلاق تحت كيلتنر السفلي"
        conf = 0.7 if squeeze else 0.55
    else:
        sig = (data.price - km) / (ku - kl) if ku != kl else 0.0
        sig = max(-0.4, min(0.4, sig * 1.2))
        txt = "داخل قناة كيلتنر"
        conf = 0.3 if squeeze else 0.35
    if squeeze:
        txt += " بعد/مع انضغاط بولينجر داخل كيلتنر"
    return ok(
        spec,
        sig,
        conf,
        f"{txt}. بولينجر {fmt(bl)}–{fmt(bu)} وكيلتنر {fmt(kl)}–{fmt(ku)}.",
        src_hist(data),
    )


@register(
    "mfi",
    "وكيل مؤشر التدفق النقدي MFI",
    "Money Flow Index",
    "technical",
    "technical",
    "mfi.md",
    0.9,
    "قياس تدفق الأموال (سعر+حجم) عبر MFI(14).",
    "mfi14.",
    "فوق 80 تشبع شرائي، تحت 20 تشبع بيعي، وبينهما ميل خفيف حول 50.",
)
def mfi_agent(data: MarketData, spec):
    m = ind(data, "mfi14")
    if m is None:
        return nf(spec, "تعذر حساب MFI(14) (قد يكون الحجم صفراً).", src_hist(data))
    if m >= 80:
        sig, conf, txt = -0.65, 0.7, "تشبع شرائي"
    elif m <= 20:
        sig, conf, txt = 0.65, 0.7, "تشبع بيعي"
    else:
        sig, conf, txt = (m - 50) / 60.0, 0.4, "منطقة وسطى"
    return ok(spec, sig, conf, f"MFI(14) عند {fmt(m, 1)} — {txt}.", src_hist(data))


@register(
    "williams-r",
    "وكيل ويليامز %R",
    "Williams %R",
    "technical",
    "technical",
    "williams-r.md",
    0.85,
    "قياس موقع الإغلاق في نطاق 14 يوماً عبر ويليامز %R.",
    "willr.",
    "فوق -20 (قريب من صفر) تشبع شرائي، تحت -80 تشبع بيعي.",
)
def williams_agent(data: MarketData, spec):
    w = ind(data, "willr")
    if w is None:
        return nf(spec, "تعذر حساب ويليامز %R.", src_hist(data))
    if w <= -80:
        sig, conf, txt = 0.6, 0.68, "تشبع بيعي"
    elif w >= -20:
        sig, conf, txt = -0.6, 0.68, "تشبع شرائي"
    else:
        sig, conf, txt = (w + 50) / 50.0, 0.4, "منتصف النطاق"
        # w=-50 -> 0, w=-20 -> 0.6 already handled
        sig = (w + 50) / 60.0
    return ok(spec, sig, conf, f"ويليامز %R عند {fmt(w, 1)} — {txt}.", src_hist(data))


@register(
    "cci",
    "وكيل قناة السلع CCI",
    "CCI",
    "technical",
    "technical",
    "cci.md",
    0.85,
    "قياس الانحراف عن متوسط السعر النموذجي عبر CCI(20).",
    "cci20.",
    "CCI فوق +100 امتداد شرائي (ميل سالب لإرجاع المتوسط، مع ميل موجب خفيف إن كان الزخم مستمراً فوق +100 لكن الوكيل يتبع القراءة التذبذبية الكلاسيكية). تحت -100 امتداد بيعي (موجب).",
)
def cci_agent(data: MarketData, spec):
    v = ind(data, "cci20")
    if v is None:
        return nf(spec, "تعذر حساب CCI(20).", src_hist(data))
    if v >= 100:
        sig, conf, txt = -0.45, 0.6, "امتداد فوق +100"
    elif v <= -100:
        sig, conf, txt = 0.45, 0.6, "امتداد تحت -100"
    else:
        sig, conf, txt = max(-0.4, min(0.4, v / 200.0)), 0.4, "داخل النطاق الاعتيادي"
    return ok(spec, sig, conf, f"CCI(20) عند {fmt(v, 1)} — {txt}.", src_hist(data))


@register(
    "fibonacci-retracement",
    "وكيل فيبوناتشي",
    "Fibonacci Retracement",
    "technical",
    "technical",
    "fibonacci-retracement.md",
    0.8,
    "قياس ارتداد السعر من آخر موجة واضحة (قاع إلى قمة أو العكس) عند نسب 38.2% و50% و61.8%.",
    "آخر قمة وقاع swing والإغلاق.",
    "في موجة صاعدة، ارتداد إلى 38–62% دون كسر 78% = ميل شرائي. كسر ما بعد 78% = ضعف. في موجة هابطة المنطق معكوس. إن لم توجد موجة واضحة: NOT FOUND.",
)
def fibonacci_agent(data: MarketData, spec):
    highs, lows = data.indicators.get("swings_hi") or [], data.indicators.get("swings_lo") or []
    if not highs or not lows:
        return nf(spec, "لا قمم/قيعان كافية لرسم ارتداد فيبوناتشي.", src_hist(data))
    h_i, h_p = highs[-1]
    l_i, l_p = lows[-1]
    px = data.price
    if h_i == l_i or abs(h_p - l_p) == 0:
        return nf(spec, "الموجة الأخيرة غير صالحة (تطابق القمة والقاع).", src_hist(data))
    if h_i > l_i:
        # upswing then retrace
        rng = h_p - l_p
        retr = (h_p - px) / rng
        side = "موجة صاعدة"
        if retr < 0:  # new high
            sig, txt = 0.7, "تمديد فوق القمة (لا ارتداد)"
            conf = 0.6
        elif retr <= 0.382:
            sig, txt = 0.45, "ارتداد ضحل فوق 38.2%"
            conf = 0.55
        elif retr <= 0.618:
            sig, txt = 0.55, "ارتداد داخل منطقة 38.2–61.8%"
            conf = 0.6
        elif retr <= 0.786:
            sig, txt = 0.15, "ارتداد عميق قرب 78.6%"
            conf = 0.45
        else:
            sig, txt = -0.5, "كسر منطقة الارتداد العميق"
            conf = 0.6
    else:
        rng = h_p - l_p
        retr = (px - l_p) / rng  # bounce fraction of downswing
        side = "موجة هابطة"
        if retr < 0:
            sig, txt = -0.7, "تمديد تحت القاع"
            conf = 0.6
        elif retr <= 0.382:
            sig, txt = -0.45, "ارتداد ضحل دون 38.2%"
            conf = 0.55
        elif retr <= 0.618:
            sig, txt = -0.55, "ارتداد داخل 38.2–61.8% من الهبوط"
            conf = 0.6
        elif retr <= 0.786:
            sig, txt = -0.15, "ارتداد عميق"
            conf = 0.45
        else:
            sig, txt = 0.5, "استعادة معظم الموجة الهابطة"
            conf = 0.6
    return ok(
        spec,
        sig,
        conf,
        f"{side} من {fmt(l_p)} إلى {fmt(h_p)} والإغلاق {fmt(px)} — {txt} (نسبة الارتداد {fmt_pct(retr)}).",
        src_hist(data),
    )


@register(
    "parabolic-sar",
    "وكيل بارابوليك SAR",
    "Parabolic SAR",
    "technical",
    "technical",
    "parabolic-sar.md",
    0.9,
    "اتجاه بارابوليك SAR كنقطة وقف ديناميكية.",
    "sar و sar_dir.",
    "SAR تحت السعر = اتجاه صاعد، فوقه = هابط.",
)
def sar_agent(data: MarketData, spec):
    sar, d = ind(data, "sar"), ind(data, "sar_dir")
    if sar is None or d is None:
        return nf(spec, "تعذر حساب بارابوليك SAR.", src_hist(data))
    sig = 0.65 if d > 0 else -0.65
    side = "تحت السعر (صاعد)" if d > 0 else "فوق السعر (هابط)"
    return ok(
        spec,
        sig,
        0.6,
        f"بارابوليك SAR عند {fmt(sar)} {side}.",
        src_hist(data),
    )


@register(
    "chaikin-money-flow",
    "وكيل تدفق شايكين",
    "Chaikin Money Flow",
    "technical",
    "technical",
    "chaikin-money-flow.md",
    0.9,
    "قياس ضغط الشراء/البيع الحجمي عبر CMF(20).",
    "cmf20.",
    "CMF فوق +0.1 تدفق شراء، تحت -0.1 تدفق بيع، وبينهما ضعيف.",
)
def cmf_agent(data: MarketData, spec):
    v = ind(data, "cmf20")
    if v is None:
        return nf(spec, "تعذر حساب CMF(20).", src_hist(data))
    sig = max(-1.0, min(1.0, v / 0.25))
    conf = 0.45 + 0.3 * min(1.0, abs(v) / 0.2)
    txt = "تدفق شراء" if v > 0.1 else ("تدفق بيع" if v < -0.1 else "تدفق محايد/ضعيف")
    return ok(spec, sig, conf, f"CMF(20) عند {fmt(v, 3)} — {txt}.", src_hist(data))


@register(
    "hull-moving-average",
    "وكيل متوسط هال",
    "Hull Moving Average",
    "technical",
    "technical",
    "hull-moving-average.md",
    0.9,
    "اتجاه متوسط هال 21 وموقع السعر منه ومنحدره.",
    "hull21 والإغلاق.",
    "سعر فوق هال ومنحدر صاعد = شراء، والعكس بيع.",
)
def hull_agent(data: MarketData, spec):
    series = data.indicators.get("hull21")
    h = ind(data, "hull21")
    if h is None or series is None:
        return nf(spec, "تعذر حساب متوسط هال 21.", src_hist(data))
    s = series.dropna()
    slope = float(s.iloc[-1] - s.iloc[-6]) if len(s) >= 6 else 0.0
    sig = (0.45 if data.price > h else -0.45) + (0.4 if slope > 0 else -0.4)
    side = "صاعد" if slope > 0 else "هابط"
    loc = "فوق" if data.price > h else "تحت"
    return ok(
        spec,
        sig,
        0.58,
        f"الإغلاق {fmt(data.price)} {loc} متوسط هال 21 عند {fmt(h)} والمنحدر {side}.",
        src_hist(data),
    )


@register(
    "relative-strength-market",
    "وكيل القوة النسبية مقابل السوق",
    "Relative Strength vs Market",
    "technical",
    "technical",
    "relative-strength-market.md",
    1.05,
    "مقارنة عائد السهم بعائد وكيل سوق السعودية (صندوق KSA) وعلى نقطة تاسي إن وُجدت.",
    "تاريخ السهم وصندوق KSA (Yahoo: KSA). مؤشر تاسي ^TASI.SR إن توفرت سلسلة كافية، وإلا يُذكر القيد.",
    "عائد 20 و60 يوماً للسهم ناقص عائد السوق. تفوق مستمر = إشارة موجبة. إن غاب وكيل السوق: NOT FOUND.",
)
def relative_strength(data: MarketData, spec):
    if data.ksa_etf is None or data.ksa_etf.empty:
        return nf(spec, "لا بيانات لصندوق KSA وكيل السوق.", "Yahoo Finance / KSA")
    # align by date (ignore tz)
    def _close(df):
        s = df["Close"].copy()
        s.index = s.index.tz_localize(None) if s.index.tz is not None else s.index
        s.index = s.index.normalize()
        return s

    stock = _close(data.hist)
    mkt = _close(data.ksa_etf)
    joined = stock.to_frame("s").join(mkt.to_frame("m"), how="inner").dropna()
    if len(joined) < 25:
        return nf(spec, "لا تداخل كافٍ بين تاريخ السهم وصندوق KSA.", "Yahoo Finance / history + KSA")
    def rel(n):
        if len(joined) <= n:
            return None
        sr = float(joined["s"].iloc[-1] / joined["s"].iloc[-1 - n] - 1)
        mr = float(joined["m"].iloc[-1] / joined["m"].iloc[-1 - n] - 1)
        return sr, mr, sr - mr

    r20, r60 = rel(20), rel(60)
    if r20 is None:
        return nf(spec, "لا تكفي الأيام المشتركة لحساب 20 يوماً.", "Yahoo Finance / history + KSA")
    parts = [r20[2]]
    txt = f"20 يوماً: السهم {fmt_pct(r20[0])} والسوق(KSA) {fmt_pct(r20[1])} (فرق {fmt_pct(r20[2])})"
    if r60:
        parts.append(r60[2])
        txt += f"؛ 60 يوماً: فرق {fmt_pct(r60[2])}"
    extra = ""
    if data.tasi_hist is None or len(data.tasi_hist) < 5:
        extra = " سلسلة تاسي التاريخية غير كافية لذا استُخدم KSA فقط."
    avg = sum(parts) / len(parts)
    sig = max(-1.0, min(1.0, avg / 0.06))
    conf = 0.6 if r60 else 0.5
    return ok(spec, sig, conf, txt + "." + extra, "Yahoo Finance / history + KSA ETF")
