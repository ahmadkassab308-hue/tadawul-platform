"""Sector, macro, liquidity, and risk analysts."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .analysts_common import fmt, fmt_pct, ind, need_bars, nf, ok, register, ret_over, src_hist, src_info
from .models import MarketData
from .universe import OIL_SENSITIVITY, name_ar, peers_for


def _series_close(df: pd.DataFrame) -> pd.Series:
    s = df["Close"].copy()
    if s.index.tz is not None:
        s.index = s.index.tz_localize(None)
    s.index = s.index.normalize()
    return s


@register(
    "oil-price-link",
    "وكيل ارتباط النفط",
    "Oil Price Link",
    "sector-macro",
    "sector-macro",
    "oil-price-link.md",
    1.0,
    "ربط اتجاه خام برنت بحساسية قطاع الشركة كما هو موثّق في MEMORY.md / universe.OIL_SENSITIVITY.",
    "تاريخ BZ=F (برنت) وقطاع السهم. الحساسية نوعية ثابتة (ملف universe) لا معامل ارتباط مخمّن إن قلّت البيانات.",
    "عائد برنت 20 و60 يوماً يُضرب في حساسية القطاع (+ للطاقة/البتروكيماويات، ضعيف للمصارف…). إن غاب برنت أو القطاع: NOT FOUND.",
)
def oil_price_link(data: MarketData, spec):
    if data.brent is None or data.brent.empty:
        return nf(spec, "لا بيانات لخام برنت (BZ=F).", "Yahoo Finance / BZ=F")
    if not data.sector:
        return nf(spec, "قطاع الشركة غير معروف لتعيين حساسية النفط.", src_info(data, "sector"))
    sens = OIL_SENSITIVITY.get(data.sector)
    if sens is None:
        return nf(
            spec,
            f"لا حساسية نفط موثّقة لقطاع {data.sector} في MEMORY.md/universe.",
            "MEMORY.md / universe.OIL_SENSITIVITY",
        )
    r20 = ret_over(data.brent["Close"], 20)
    r60 = ret_over(data.brent["Close"], 60)
    if r20 is None and r60 is None:
        return nf(spec, "سلسلة برنت أقصر من أن تُحسب عوائد 20/60 يوماً.", "Yahoo Finance / BZ=F")
    parts = [p for p in (r20, r60) if p is not None]
    oil_move = sum(parts) / len(parts)
    # last price
    last = float(data.brent["Close"].iloc[-1])
    sig = max(-1.0, min(1.0, (oil_move / 0.08) * sens))
    conf = 0.45 + 0.25 * abs(sens)
    bits = [f"برنت {fmt(last, 2)} دولار"]
    if r20 is not None:
        bits.append(f"20 يوماً {fmt_pct(r20)}")
    if r60 is not None:
        bits.append(f"60 يوماً {fmt_pct(r60)}")
    bits.append(f"حساسية قطاع {data.sector} = {fmt(sens, 2)} (من MEMORY.md)")
    return ok(spec, sig, conf, "؛ ".join(bits) + ".", "Yahoo Finance / BZ=F + MEMORY.md")


@register(
    "sama-policy",
    "وكيل سياسة ساما",
    "SAMA Policy Rates",
    "sector-macro",
    "sector-macro",
    "sama-policy.md",
    0.9,
    "قراءة أثر معدل السياسة النقدية السعودية على السهم إن توفّر رقم حديث من مصدر مجاني.",
    "محاولة جلب سلسلة من FRED أو مصدر موثوق في fetch.try_sama_rates. لا يُستخدم رقم قديم محفوظ يدوياً.",
    "إن وُجد المعدل يُقيَّم مستواه واتجاه آخر ملاحظة مقابل السابقة. المصارف أكثر حساسية. إن فشل الجلب: NOT FOUND.",
)
def sama_policy(data: MarketData, spec):
    if not data.sama or data.sama.get("value") is None:
        return nf(
            spec,
            "لم يتوفر معدل ساما/سايبور من مصدر مجاني موثوق في هذه الجلسة.",
            "fetch.try_sama_rates",
        )
    val = float(data.sama["value"])
    # Without a documented path of what the series means for direction, only report
    # the observation and give a very cautious bank-tilt if the value is a rate.
    rate = val / 100.0 if val > 1 else val
    bank = "Bank" in (data.industry or "") or data.sector == "Financial Services"
    # High policy rates are a mixed positive for banks' NIMs and a headwind for leveraged sectors.
    # We do not guess the cycle turning point; we only map the level vs a wide band 1%–8%.
    if rate < 0 or rate > 0.25:
        return nf(spec, f"قيمة {val} لا تبدو معدل فائدة سنوي قابل للتفسير.", data.sama.get("source", "FRED"))
    if bank:
        sig = max(-0.4, min(0.4, (rate - 0.04) / 0.08))
        txt = "حساسية مصرفية لمستوى المعدل (علاوة هامش فائدة محتملة عند معدلات أعلى، دون توقع الدورة)"
    else:
        sig = max(-0.4, min(0.4, (0.05 - rate) / 0.08))
        txt = "معدلات أعلى عادةً رأس رياح على التقييم غير المصرفي (إشارة محدودة)"
    conf = 0.4
    src = data.sama.get("source") or "FRED"
    dt = data.sama.get("date") or "تاريخ غير محدد"
    return ok(
        spec,
        sig,
        conf,
        f"معدل مُستجلب {fmt_pct(rate)} بتاريخ {dt} من {src} — {txt}.",
        src,
    )


@register(
    "sector-relative",
    "وكيل المقارنة القطاعية",
    "Sector Relative Performance",
    "sector-macro",
    "sector-macro",
    "sector-relative.md",
    1.0,
    "مقارنة عائد السهم بنظرائه في نفس القطاع من قائمة MEMORY.md.",
    "أسعار النظراء عبر Yahoo Finance (peer_hist) وعائد 20/60 يوماً.",
    "تفوق على وسيط النظراء إشارة موجبة. إن قلّ عدد النظراء عن 2 ذوي بيانات: NOT FOUND.",
)
def sector_relative(data: MarketData, spec):
    peers = {k: v for k, v in (data.peer_hist or {}).items() if v is not None and len(v.dropna()) >= 25}
    if len(peers) < 2:
        return nf(
            spec,
            f"نظراء مكتملو البيانات: {len(peers)} (يلزم 2 على الأقل). القائمة من MEMORY.md.",
            "Yahoo Finance / peer history + MEMORY.md",
        )
    def r(series, n):
        s = series.dropna()
        if len(s) <= n or float(s.iloc[-1 - n]) == 0:
            return None
        return float(s.iloc[-1] / s.iloc[-1 - n] - 1)

    rows = []
    for n in (20, 60):
        sr = r(data.hist["Close"], n)
        prs = [r(s, n) for s in peers.values()]
        prs = [x for x in prs if x is not None]
        if sr is None or len(prs) < 2:
            continue
        med = float(np.median(prs))
        rows.append((n, sr, med, sr - med))
    if not rows:
        return nf(spec, "تعذر حساب عوائد متزامنة مع النظراء.", "Yahoo Finance / peer history")
    avg_gap = sum(x[3] for x in rows) / len(rows)
    sig = max(-1, min(1, avg_gap / 0.06))
    bits = [f"{n}ي: السهم {fmt_pct(sr)} ووسيط النظراء ({len(peers)}) {fmt_pct(med)} (فرق {fmt_pct(gap)})" for n, sr, med, gap in rows]
    return ok(
        spec,
        sig,
        0.6,
        "؛ ".join(bits) + ".",
        "Yahoo Finance / peer history + MEMORY.md",
    )


@register(
    "tasi-context",
    "وكيل سياق تاسي",
    "TASI Context",
    "sector-macro",
    "sector-macro",
    "tasi-context.md",
    0.95,
    "وصف موقع مؤشر تاسي من نطاق 52 أسبوعاً ومتوسطاته، واتجاه وكيل KSA إن لزم.",
    "info لـ ^TASI.SR (سعر، 52 أسبوعاً، متوسط 50 و200 يوم). سلسلة KSA التاريخية للاتجاه إن كانت سلسلة تاسي ناقصة.",
    "تاسي قرب قاع 52 أسبوعاً = سياق حذر/فرص انتقائية؛ قرب القمة امتداد. تحت متوسط 200 يوم اتجاه هابط للسوق. لا يُختلق تاريخ يومي مفقود.",
)
def tasi_context(data: MarketData, spec):
    info = data.tasi_spot or {}
    px = info.get("regularMarketPrice") or info.get("previousClose")
    hi = info.get("fiftyTwoWeekHigh")
    lo = info.get("fiftyTwoWeekLow")
    sma50 = info.get("fiftyDayAverage")
    sma200 = info.get("twoHundredDayAverage")
    chg52 = info.get("fiftyTwoWeekChangePercent")
    if px is None and hi is None:
        return nf(spec, "لا بيانات فورية لمؤشر تاسي (^TASI.SR).", "Yahoo Finance / ^TASI.SR info")
    bits = []
    sig, conf = 0.0, 0.5
    if px is not None:
        bits.append(f"تاسي {fmt(float(px), 2)}")
    if px and hi and lo and hi != lo:
        pos = (float(px) - float(lo)) / (float(hi) - float(lo))
        bits.append(f"موقع 52 أسبوعاً {fmt_pct(pos)} (النطاق {fmt(float(lo), 0)}–{fmt(float(hi), 0)})")
        sig += 0.4 * (pos - 0.5) * 2  # near high mild +, near low mild - (market-risk context)
        # actually near 52w low can be opportunity; we treat market trend via MAs more than this
        # Rebalance: location alone mild, MAs dominate
        sig = 0.2 * (pos - 0.5) * 2
    if px and sma50:
        bits.append(f"متوسط 50 يوماً {fmt(float(sma50), 2)}")
        sig += 0.25 if float(px) > float(sma50) else -0.25
    if px and sma200:
        bits.append(f"متوسط 200 يوم {fmt(float(sma200), 2)}")
        sig += 0.35 if float(px) > float(sma200) else -0.35
        conf = 0.6
    if chg52 is not None:
        ch = float(chg52)
        ch = ch / 100.0 if abs(ch) > 1.5 else ch
        bits.append(f"تغير 52 أسبوعاً {fmt_pct(ch)}")
    # KSA trend if TASI history missing
    if data.tasi_hist is None or len(data.tasi_hist) < 5:
        bits.append("السلسلة اليومية لتأسي غير مكتملة على Yahoo")
        if data.ksa_etf is not None and len(data.ksa_etf) >= 60:
            r20 = ret_over(data.ksa_etf["Close"], 20)
            r60 = ret_over(data.ksa_etf["Close"], 60)
            if r20 is not None:
                bits.append(f"وكيل KSA 20 يوماً {fmt_pct(r20)}")
                sig += 0.2 if r20 > 0 else -0.2
            if r60 is not None:
                bits.append(f"و60 يوماً {fmt_pct(r60)}")
    return ok(spec, max(-1, min(1, sig)), conf, "؛ ".join(bits) + ".", "Yahoo Finance / ^TASI.SR info + KSA")


@register(
    "usd-sar-peg",
    "وكيل ربط الريال",
    "USD/SAR Peg",
    "sector-macro",
    "sector-macro",
    "usd-sar-peg.md",
    0.6,
    "مراقبة سعر الدولار/الريال حول الربط التقليدي 3.75.",
    "Yahoo Finance SAR=X.",
    "انحراف محدود حول 3.75 يُعد استقراراً (حياد). انحراف واضح (>1%) يُسجَّل كخطر/إشارة حذر. إن غاب السعر: NOT FOUND. لا يُفترض الربط إن لم يُرَ السعر.",
)
def usd_sar_peg(data: MarketData, spec):
    if data.usd_sar is None or data.usd_sar.empty:
        return nf(spec, "لا بيانات لسعر SAR=X.", "Yahoo Finance / SAR=X")
    px = float(data.usd_sar["Close"].iloc[-1])
    # Yahoo SAR=X is typically USD per? Probe showed 3.678 — that's SAR per USD (the conventional quote).
    peg = 3.75
    dev = px / peg - 1.0
    if abs(dev) <= 0.01:
        sig, conf, txt = 0.05, 0.4, "قرب الربط التقليدي 3.75 (استقرار)"
    elif abs(dev) <= 0.03:
        sig, conf, txt = -0.15, 0.5, "انحراف ملحوظ عن 3.75"
    else:
        sig, conf, txt = -0.45, 0.7, "انحراف واضح عن مستوى الربط التقليدي"
    r20 = ret_over(data.usd_sar["Close"], 20)
    extra = f" وتغير 20 يوماً {fmt_pct(r20)}" if r20 is not None else ""
    return ok(
        spec,
        sig,
        conf,
        f"سعر SAR=X عند {fmt(px, 4)} مقابل 3.75 (انحراف {fmt_pct(dev)}) — {txt}{extra}.",
        "Yahoo Finance / SAR=X",
    )


@register(
    "sector-rotation",
    "وكيل تناوب القطاعات",
    "Sector Rotation",
    "sector-macro",
    "sector-macro",
    "sector-rotation.md",
    0.9,
    "قياس زخم قطاع السهم مقابل وكيل السوق (وسيط عوائد النظراء مقابل KSA).",
    "عوائد النظراء وصندوق KSA لـ 20 و60 يوماً.",
    "قطاع يتفوق على السوق = تناوب إيجابي يدعم السهم. إن نقص النظراء أو KSA: NOT FOUND.",
)
def sector_rotation(data: MarketData, spec):
    if data.ksa_etf is None or data.ksa_etf.empty:
        return nf(spec, "لا وكيل سوق (KSA) لحساب تناوب القطاعات.", "Yahoo Finance / KSA")
    peers = {k: v for k, v in (data.peer_hist or {}).items() if v is not None and len(v.dropna()) >= 25}
    # include the stock itself in the sector basket
    basket = dict(peers)
    basket[data.ticker] = data.hist["Close"]
    if len(basket) < 2:
        return nf(spec, "لا سلة قطاع كافية (يلزم السهم + نظير واحد على الأقل).", "Yahoo Finance / peers + KSA")

    def r(series, n):
        s = series.dropna()
        if len(s) <= n or float(s.iloc[-1 - n]) == 0:
            return None
        return float(s.iloc[-1] / s.iloc[-1 - n] - 1)

    bits = []
    gaps = []
    for n in (20, 60):
        prs = [r(s, n) for s in basket.values()]
        prs = [x for x in prs if x is not None]
        mr = r(data.ksa_etf["Close"], n)
        if mr is None or len(prs) < 2:
            continue
        med = float(np.median(prs))
        gaps.append(med - mr)
        bits.append(f"{n}ي: وسيط القطاع {fmt_pct(med)} مقابل KSA {fmt_pct(mr)}")
    if not gaps:
        return nf(spec, "تعذر حساب عوائد القطاع مقابل السوق.", "Yahoo Finance / peers + KSA")
    avg = sum(gaps) / len(gaps)
    sig = max(-1, min(1, avg / 0.05))
    return ok(spec, sig, 0.55, "؛ ".join(bits) + f" — فرق متوسط {fmt_pct(avg)}.", "Yahoo Finance / peers + KSA")


@register(
    "turnover-liquidity",
    "وكيل سيولة الدوران",
    "Turnover Liquidity",
    "liquidity",
    "liquidity",
    "turnover-liquidity.md",
    0.8,
    "قياس قيمة التداول اليومية مقابل القيمة السوقية (معدل الدوران).",
    "الحجم × السعر، ومتوسط 20 يوماً، و info.marketCap.",
    "دوران كافٍ يسهّل الدخول/الخروج (ميل إيجابي للجودة). سيولة شحيحة إشارة حذر. إن غابت القيمة السوقية يُستخدم متوسط قيمة التداول فقط بعتبات مطلقة بالريال.",
)
def turnover_liquidity(data: MarketData, spec):
    if not need_bars(data, 21):
        return nf(spec, "لا يكفي من أيام التداول لحساب السيولة.", src_hist(data))
    val = data.hist["Close"] * data.hist["Volume"]
    avg_val = float(val.iloc[-20:].mean())
    last_val = float(val.iloc[-1])
    mcap = data.info.get("marketCap")
    bits = [f"متوسط قيمة التداول 20 يوماً {fmt(avg_val/1e6, 1)} مليون ر.س", f"اليوم {fmt(last_val/1e6, 1)} مليون"]
    if mcap:
        mcap = float(mcap)
        flt = data.info.get("floatShares")
        denom, denom_lbl = mcap, "القيمة السوقية"
        if flt and data.price:
            denom = float(flt) * data.price
            denom_lbl = "قيمة الأسهم الحرة"
        turn = avg_val / denom if denom else 0.0
        bits.append(f"دوران يومي {fmt_pct(turn, 3)} من {denom_lbl}")
        # Absolute riyal volume dominates for mega-caps (full market cap turnover can look tiny).
        if avg_val >= 50e6:
            sig, conf = 0.5, 0.6
        elif turn >= 0.002:
            sig, conf = 0.45, 0.6
        elif turn >= 0.0005:
            sig, conf = 0.2, 0.5
        elif avg_val >= 8e6:
            sig, conf = 0.1, 0.45
        else:
            sig, conf = -0.35, 0.55
    else:
        if avg_val >= 20e6:
            sig, conf = 0.4, 0.5
        elif avg_val >= 5e6:
            sig, conf = 0.15, 0.4
        else:
            sig, conf = -0.4, 0.5
        bits.append("بلا قيمة سوقية للمقارنة")
    return ok(spec, sig, conf, "؛ ".join(bits) + ".", src_hist(data) + " + info.marketCap")


@register(
    "unusual-volume",
    "وكيل الحجم غير المعتاد",
    "Unusual Volume",
    "liquidity",
    "liquidity",
    "unusual-volume.md",
    0.75,
    "رصد انحراف حجم اليوم عن متوسط 20 و50 يوماً.",
    "Volume و vol_sma20 و vol_sma50 واتجاه الإغلاق.",
    "حجم غير معتاد (≥2×) يؤكد اتجاه الإغلاق. إن كان الحجم طبيعياً: إشارة قريبة من الصفر لا NOT FOUND (الطبيعة معلومة).",
)
def unusual_volume(data: MarketData, spec):
    v20, v50 = ind(data, "vol_sma20"), ind(data, "vol_sma50")
    if v20 is None or v20 == 0:
        return nf(spec, "لا متوسط حجم 20 يوماً.", src_hist(data))
    vol = float(data.hist["Volume"].iloc[-1])
    ratio = vol / v20
    chg = (data.price / data.prev_close - 1.0) if data.prev_close else 0.0
    if ratio >= 2.0:
        sig = 0.7 if chg > 0 else (-0.7 if chg < 0 else 0.1)
        conf, txt = 0.7, "حجم غير معتاد (≥2×)"
    elif ratio >= 1.5:
        sig = 0.4 if chg > 0 else (-0.4 if chg < 0 else 0.0)
        conf, txt = 0.55, "حجم مرتفع"
    else:
        sig, conf, txt = 0.0, 0.4, "لا حجم غير معتاد"
    extra = f" ومقابل متوسط 50 يوماً ×{fmt(vol/v50, 2)}" if v50 else ""
    return ok(
        spec,
        sig,
        conf,
        f"حجم اليوم ×{fmt(ratio, 2)} متوسط 20 يوماً {extra} مع تغير {fmt_pct(chg)} — {txt}.",
        src_hist(data),
    )


@register(
    "free-float-turnover",
    "وكيل دوران الأسهم الحرة",
    "Free Float Turnover",
    "liquidity",
    "liquidity",
    "free-float-turnover.md",
    0.7,
    "تقدير دوران الأسهم الحرة (الحجم / floatShares).",
    "info.floatShares أو sharesOutstanding والحجم المتوسط.",
    "دوران حر معقول إيجابي للسيولة. إن غاب عدد الأسهم الحرة: NOT FOUND.",
)
def free_float_turnover(data: MarketData, spec):
    flt = data.info.get("floatShares") or data.info.get("sharesOutstanding")
    field = "floatShares" if data.info.get("floatShares") else ("sharesOutstanding" if data.info.get("sharesOutstanding") else None)
    if not flt:
        return nf(spec, "لا عدد أسهم حرة ولا قائمة في المصدر.", src_info(data, "floatShares"))
    v20 = ind(data, "vol_sma20")
    if v20 is None:
        return nf(spec, "لا متوسط حجم لحساب الدوران الحر.", src_hist(data))
    turn = v20 / float(flt)
    used = "الأسهم الحرة" if field == "floatShares" else "الأسهم القائمة (بدل الحرة)"
    if turn >= 0.005:
        sig, conf = 0.45, 0.6
    elif turn >= 0.001:
        sig, conf = 0.2, 0.5
    else:
        sig, conf = -0.25, 0.5
    inst = data.info.get("heldPercentInstitutions")
    extra = f" ونسبة المؤسسات {fmt_pct(float(inst))}" if inst is not None else ""
    return ok(
        spec,
        sig,
        conf,
        f"متوسط الحجم {v20:,.0f} ÷ {used} {float(flt):,.0f} = دوران {fmt_pct(turn, 3)}{extra}.",
        src_info(data, field) + " + history",
    )


@register(
    "average-dollar-volume",
    "وكيل متوسط قيمة التداول",
    "Average Riyal Volume",
    "liquidity",
    "liquidity",
    "average-dollar-volume.md",
    0.7,
    "تصنيف متوسط قيمة التداول بالريال لصلاحية بناء المراكز.",
    "متوسط (السعر×الحجم) لـ 20 يوماً.",
    "فوق 25 مليون ر.س يومياً سيولة مريحة للأسهم القيادية، تحت 3 ملايين سيولة ضعيفة للمستثمر النشط.",
)
def average_dollar_volume(data: MarketData, spec):
    if not need_bars(data, 21):
        return nf(spec, "التاريخ غير كافٍ لمتوسط قيمة التداول.", src_hist(data))
    val = float((data.hist["Close"] * data.hist["Volume"]).iloc[-20:].mean())
    if val >= 50e6:
        sig, conf = 0.55, 0.65
    elif val >= 25e6:
        sig, conf = 0.35, 0.55
    elif val >= 8e6:
        sig, conf = 0.1, 0.45
    elif val >= 3e6:
        sig, conf = -0.15, 0.45
    else:
        sig, conf = -0.5, 0.6
    return ok(spec, sig, conf, f"متوسط قيمة التداول 20 يوماً {fmt(val/1e6, 2)} مليون ر.س.", src_hist(data))


@register(
    "max-drawdown",
    "وكيل أقصى انخفاض",
    "Max Drawdown",
    "risk",
    "risk",
    "max-drawdown.md",
    0.9,
    "قياس أقصى انخفاض من القمة خلال سنة (أو المتاح) والمسافة الحالية عن قمة 52 أسبوعاً.",
    "سلسلة الإغلاق و info.fiftyTwoWeekHigh.",
    "انخفاض حاد جارٍ يرفع المخاطر (إشارة سالبة). تعافٍ من انخفاض سابق دون قمم جديدة = حذر. انخفاض ضحل إشارة مخاطر أدنى.",
)
def max_drawdown(data: MarketData, spec):
    c = data.hist["Close"].dropna()
    if len(c) < 30:
        return nf(spec, "التاريخ قصير جداً لحساب الانخفاض.", src_hist(data))
    window = c.iloc[-252:] if len(c) >= 60 else c
    roll_max = window.cummax()
    dd = window / roll_max - 1.0
    mdd = float(dd.min())
    now_dd = float(dd.iloc[-1])
    hi52 = data.info.get("fiftyTwoWeekHigh")
    bits = [f"أقصى انخفاض في النافذة {fmt_pct(mdd)}", f"الانخفاض الحالي عن القمة المحلية {fmt_pct(now_dd)}"]
    if hi52:
        bits.append(f"يبعد {fmt_pct(data.price/float(hi52)-1)} عن أعلى 52 أسبوعاً ({fmt(float(hi52))})")
    # more negative current drawdown -> more risk / bearish tilt
    sig = max(-1.0, min(0.4, (now_dd + 0.1) / 0.25))
    conf = 0.6
    return ok(spec, sig, conf, "؛ ".join(bits) + ".", src_hist(data) + " + info.fiftyTwoWeekHigh")


@register(
    "beta-vs-market",
    "وكيل بيتا مقابل السوق",
    "Beta vs Market",
    "risk",
    "risk",
    "beta-vs-market.md",
    0.9,
    "قياس بيتا مقابل صندوق KSA (وكيل السوق) من العوائد اليومية، مع ذكر info.beta إن وُجد كمصدر إضافي لا بديل صامت.",
    "عوائد السهم وKSA المتزامنة لـ 60–252 يوماً. info.beta إن توفر.",
    "بيتا محسوبة إن توفّر تداخل كافٍ (≥60 يوماً). بيتا مرتفعة (>1.2) مخاطر أعلى (ميل حذر). بيتا منخفضة جداً أو سالبة تُذكر كما هي. إن نقص التداخل يُستخدم info.beta فقط إذا وُجد، وإلا NOT FOUND.",
)
def beta_vs_market(data: MarketData, spec):
    computed = None
    n_used = 0
    if data.ksa_etf is not None and not data.ksa_etf.empty:
        a = data.hist["Close"].pct_change()
        b = data.ksa_etf["Close"].pct_change()
        a.index = a.index.tz_localize(None).normalize() if a.index.tz is not None else a.index.normalize()
        b.index = b.index.tz_localize(None).normalize() if b.index.tz is not None else b.index.normalize()
        j = a.to_frame("s").join(b.to_frame("m"), how="inner").dropna()
        if len(j) >= 60:
            n_used = min(len(j), 252)
            j = j.iloc[-n_used:]
            var = float(j["m"].var())
            if var > 0:
                computed = float(j["s"].cov(j["m"]) / var)
    stated = data.info.get("beta")
    if computed is None and stated is None:
        return nf(spec, "لا بيتا محسوبة (تداخل غير كافٍ مع KSA) ولا info.beta.", "Yahoo Finance / KSA + info.beta")
    bits = []
    beta = computed if computed is not None else float(stated)
    if computed is not None:
        bits.append(f"بيتا المحسوبة مقابل KSA {fmt(computed, 2)} على {n_used} يوماً")
    if stated is not None:
        bits.append(f"info.beta={fmt(float(stated), 2)}")
    if beta >= 1.3:
        sig, conf = -0.45, 0.6
    elif beta >= 0.8:
        sig, conf = -0.1, 0.45
    elif beta >= 0.3:
        sig, conf = 0.2, 0.5
    else:
        sig, conf = 0.15, 0.45
        bits.append("بيتا منخفضة أو قريبة من صفر (ارتباط ضعيف بالوكيل)")
    return ok(spec, sig, conf, "؛ ".join(bits) + ".", "Yahoo Finance / KSA returns + info.beta")


@register(
    "position-sizing",
    "وكيل حجم المركز",
    "Position Sizing Quality",
    "risk",
    "risk",
    "position-sizing.md",
    0.8,
    "تقدير ما إذا كانت مسافة الوقف المعتمدة على ATR تسمح ببناء مركز عملي عند مخاطرة 1% من رأس المال.",
    "ATR(14) والسعر. لا يُفترض حجم حساب محدد؛ تُحسب النسبة المئوية للمخاطرة حتى الوقف (1.5×ATR).",
    "إن كانت مسافة الوقف بين 2% و8% فهي عملية. أضيق من 1.5% (وقف ضيق قد يُخرج مبكراً) أو أوسع من 12% (مركز صغير جداً أو مخاطرة كبيرة) إشارة جودة أضعف.",
)
def position_sizing(data: MarketData, spec):
    atr = ind(data, "atr14")
    if atr is None or data.price <= 0:
        return nf(spec, "لا ATR أو سعر لحساب مسافة الوقف.", src_hist(data))
    stop_dist = 1.5 * atr / data.price
    if 0.02 <= stop_dist <= 0.08:
        sig, conf = 0.45, 0.6
        txt = "مسافة وقف عملية"
    elif 0.015 <= stop_dist < 0.02 or 0.08 < stop_dist <= 0.12:
        sig, conf = 0.05, 0.45
        txt = "مسافة وقف مقبولة بتحفظ"
    else:
        sig, conf = -0.35, 0.55
        txt = "مسافة وقف غير مريحة (ضيقة جداً أو واسعة جداً)"
    shares = 0.01 / stop_dist if stop_dist else None
    extra = f" ما يعادل نحو {fmt(shares, 2)} سهم لكل 100 ر.س رأس مال عند مخاطرة 1%" if shares else ""
    return ok(
        spec,
        sig,
        conf,
        f"وقف مقترح 1.5×ATR يبعد {fmt_pct(stop_dist)} عن السعر — {txt}.{extra}.",
        src_hist(data),
    )


@register(
    "stop-loss-atr",
    "وكيل وقف الخسارة",
    "ATR Stop Quality",
    "risk",
    "risk",
    "stop-loss-atr.md",
    0.85,
    "اقتراح مستوى وقف قائم على ATR ودعم قريب، وتقييم جودة الموقع الحالي للدخول.",
    "ATR(14) وأقرب دعم من الـ swing.",
    "إن كان السعر ممتداً بعيداً فوق الدعم (>2 ATR) فجودة الدخول الشرائي أضعف. قرب الدعم يحسّن نقطة الوقف. الوكيل يقيّم الجودة ولا يتجاهل الاتجاه.",
)
def stop_loss_atr(data: MarketData, spec):
    atr = ind(data, "atr14")
    if atr is None or atr <= 0:
        return nf(spec, "لا ATR لحساب وقف.", src_hist(data))
    lows = data.indicators.get("swings_lo") or []
    supports = [p for _, p in lows if p < data.price]
    support = max(supports) if supports else None
    stop_atr = data.price - 1.5 * atr
    if support is not None and support < data.price:
        # use the lower of (just below support) and 2.5 ATR cap
        stop = min(support - 0.1 * atr, data.price - 1.0 * atr)
        if data.price - stop > 2.5 * atr:
            stop = data.price - 2.5 * atr
        dist_sup = (data.price - support) / atr
    else:
        stop = stop_atr
        dist_sup = None
    risk_pct = (data.price - stop) / data.price
    if dist_sup is not None and dist_sup <= 1.2:
        sig, conf, txt = 0.5, 0.6, "قرب الدعم يُحسّن جودة الوقف"
    elif dist_sup is not None and dist_sup > 2.5:
        sig, conf, txt = -0.35, 0.55, "السعر ممتد بعيداً عن الدعم"
    else:
        sig, conf, txt = 0.1, 0.45, "وقف مبني على ATR"
    extra = f" وأقرب دعم {fmt(support)}" if support else " بلا دعم محلي تحت السعر"
    return ok(
        spec,
        sig,
        conf,
        f"وقف تحليلي عند {fmt(stop)} (مخاطرة {fmt_pct(risk_pct)}) — {txt}{extra}.",
        src_hist(data),
    )


@register(
    "downside-volatility",
    "وكيل تقلب الجانب السلبي",
    "Downside Volatility",
    "risk",
    "risk",
    "downside-volatility.md",
    0.85,
    "مقارنة التقلب السالب (انحراف العوائد السالبة) بالتقلب الكلي.",
    "dvol20 و rvol20.",
    "تقلب سلبي مرتفع مقابل الكلي إشارة مخاطر أسوأ (سالب). إن نقصت الحسابات: NOT FOUND.",
)
def downside_vol(data: MarketData, spec):
    dv, rv = ind(data, "dvol20"), ind(data, "rvol20")
    if dv is None or rv is None or rv == 0:
        return nf(spec, "لا تقلب سلبي أو كلي كافٍ (يلزم ~20 يوماً).", src_hist(data))
    ratio = dv / rv
    bits = [f"التقلب السنوي 20 يوماً {fmt_pct(rv)}", f"السلبي {fmt_pct(dv)}", f"النسبة {fmt(ratio, 2)}"]
    # high downside ratio or high absolute vol -> caution
    sig = -0.3 * max(-1, min(1, (ratio - 0.7) / 0.3)) - 0.3 * max(0, min(1, (rv - 0.25) / 0.25))
    conf = 0.55
    return ok(spec, max(-1, min(1, sig)), conf, "؛ ".join(bits) + ".", src_hist(data))
