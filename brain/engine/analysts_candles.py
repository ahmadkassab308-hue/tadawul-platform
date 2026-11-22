"""Candlestick analyst group (18 analysts) — implements knowledge/candlesticks/RULES.md.

Every analyst returns signal -1..+1, confidence, one Arabic reason citing the guide (G1/G2/G3),
and NOT FOUND when there is no valid pattern / context. Shared engine: engine/candles.py.
"""
from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd

from . import candles as C
from .analysts_common import fmt, nf, ok, register
from .models import MarketData

G = "candlestick"
SRC = "knowledge/candlesticks/RULES.md + Yahoo Finance / history"


def _src(data: MarketData) -> str:
    return f"{SRC} ({data.ticker})"


def _ctx(data):
    return C.live_context(data)


def _pattern_agent(data: MarketData, spec, agent_id: str, what: str):
    cx = _ctx(data)
    if cx is None:
        return nf(spec, "أقل من 60 شمعة يومية مكتملة.", _src(data))
    res = C.summarize_events(cx, agent_id)
    if res is None:
        return nf(spec, f"لا {what} صالح (بالشكل + الاتجاه السابق) على آخر {C.P['active_bars']} شموع مكتملة.", _src(data))
    if "signal" not in res:
        f = res["failed"][0]
        return nf(spec, f"ظهر {f.name_ar} ثم أُبطل بإغلاق تجاوز {f.stop:.2f} — لا يُحتسب.", _src(data))
    return ok(spec, res["signal"], res["confidence"],
              f"{res['desc']}. {res['bt']}. المرجع: {res['cite']}.", _src(data))


def _reg(agent_id, name_ar, name_en, weight, role, inputs, method):
    return register(agent_id, name_ar, name_en, G, "candlestick", f"{agent_id}.md", weight, role, inputs, method)


# ── 1. anatomy ──────────────────────────────────────────────────────────────
@_reg("candle-anatomy", "وكيل تشريح الشمعة وموضع الإغلاق", "Candle Anatomy & Close Location", 0.5,
      "قياس آخر شمعة مكتملة: المدى والجسم ونسبة الجسم للمدى والظلال وموضع الإغلاق ومقارنتها بمتوسط الشموع السابقة.",
      "OHLC يومي مكتمل (تُحذف شمعة اليوم قبل 15:20 الرياض).",
      "G3 §3: المدى=H−L، الجسم=|C−O|، موضع الإغلاق=(C−L)/المدى (لا يُحسب إن كان المدى صفراً). G1 ص2: الشمعة التي لا تزيد عن متوسط السابقة لا تحمل رسالة → ثقة 0.2. جسم ≥1.3× متوسط 10 شموع (افتراضي) = رسالة: الإشارة من موضع الإغلاق. G3 §2: إن خالف لون الشمعة تغيّرها عن إغلاق الأمس (فجوة) تُنصف الإشارة.")
def candle_anatomy(data: MarketData, spec):
    cx = _ctx(data)
    if cx is None:
        return nf(spec, "أقل من 60 شمعة.", _src(data))
    b = cx["bars"]
    i = b.n - 1
    if not (b.rng[i] > 0):
        return nf(spec, "المدى صفر — لا تُحسب النسب (G3 §3).", _src(data))
    cl = float(b.close_loc[i])
    br = float(b.body_ratio[i])
    ab = b.avg_body[i]
    rel = b.body[i] / ab if np.isfinite(ab) and ab > 0 else None
    sig = (cl - 0.5) * 1.2
    net = b.c[i] - b.c[i - 1]
    gap_note = ""
    if (b.green(i) and net < 0) or (b.red(i) and net > 0):
        sig *= 0.5
        gap_note = "، واللون يخالف التغير عن إغلاق الأمس بسبب فجوة الافتتاح (G3 §2)"
    if rel is not None and rel >= C.P["long_body_mult"]:
        conf = 0.45
        msg = f"جسم أكبر من المتوسط ({rel:.1f}×) فيحمل رسالة"
    else:
        conf = 0.2
        sig *= 0.5
        msg = f"جسم {('%.1f×' % rel) if rel else '?'} المتوسط فلا يحمل رسالة مهمة (G1 ص2)"
    return ok(spec, sig, conf,
              f"شمعة {cx['dates'][i]}: الجسم {br*100:.0f}% من المدى، موضع الإغلاق {cl*100:.0f}%، ظل علوي {b.up[i]:.2f} وسفلي {b.lo_sh[i]:.2f}؛ {msg}{gap_note}. المرجع: G3 §3، G1 ص2.",
              _src(data))


# ── 2. market structure ─────────────────────────────────────────────────────
@_reg("candle-structure", "وكيل بنية السوق (القمم والقيعان)", "Market Structure HH/HL", 0.8,
      "تحديد الاتجاه من تسلسل القمم والقيعان المحورية المؤكدة قبل تسمية أي نموذج.",
      "قمم وقيعان محورية (3 شموع كل جانب، تُؤكَّد بعد 3 شموع) على آخر 250 شمعة.",
      "G1 §6 ص6-7، G2 9.1، G3 §4: قمم أعلى وقيعان أعلى = صاعد (+0.5)، قمم أدنى وقيعان أدنى = هابط (−0.5)، متساوية = عرضي، غير ذلك انتقالي (0). كسر آخر قمة/قاع مؤثر يُذكر.")
def candle_structure(data: MarketData, spec):
    cx = _ctx(data)
    if cx is None:
        return nf(spec, "أقل من 60 شمعة.", _src(data))
    b = cx["bars"]
    st = C.structure(b, b.n - 1)
    if not st["ok"]:
        return nf(spec, "لا قمتان وقاعان محوريان مؤكدان.", _src(data))
    px = b.c[-1]
    sig = 0.5 * st["dir"]
    extra = ""
    if st["dir"] == -1 and px > st["last_hi"]:
        sig, extra = 0.15, f"؛ لكن الإغلاق {px:.2f} تجاوز آخر قمة مؤثرة {st['last_hi']:.2f} فيضعف تسلسل القمم الهابطة (G3 §11)"
    elif st["dir"] == 1 and px < st["last_lo"]:
        sig, extra = -0.15, f"؛ لكن الإغلاق {px:.2f} كسر آخر قاع مؤثر {st['last_lo']:.2f}"
    conf = 0.6 if st["dir"] != 0 else 0.4
    return ok(spec, sig, conf,
              f"البنية {st['label']}: القمتان {st['prev_hi']:.2f}→{st['last_hi']:.2f} والقاعان {st['prev_lo']:.2f}→{st['last_lo']:.2f}{extra}. المرجع: G1 ص6-7، G2 9.1، G3 §4.",
              _src(data))


# ── 3. levels / breakout / false breakout ───────────────────────────────────
@_reg("candle-levels", "وكيل الدعم والمقاومة والاختراق الكاذب", "S/R, Breakout & False Breakout", 0.7,
      "موقع السعر من الدعوم والمقاومات (قمم/قيعان محورية ومتوسطات 20/50/200) وكشف الاختراق الحقيقي والكاذب وتبادل الأدوار.",
      "إغلاقات يومية مكتملة، حجم نسبي إلى متوسط 20، مستويات محورية على 120 شمعة.",
      "G3 §5 وG2 9.3: إغلاق فوق مقاومة كان دونها أمس = اختراق؛ بحجم ≥1.2× = +0.6 وبلا حجم = +0.2 (مشكوك). إغلاق عاد داخل النطاق بعد اختراق أمس = اختراق كاذب −0.5. ارتداد قرب دعم في بنية صاعدة +0.3، وقرب مقاومة في بنية هابطة −0.3. منتصف المسافة بلا مستوى = NOT FOUND (G1 ص9 خطأ 1).")
def candle_levels(data: MarketData, spec):
    cx = _ctx(data)
    if cx is None:
        return nf(spec, "أقل من 60 شمعة.", _src(data))
    b = cx["bars"]
    s = b.n - 1
    lv = C.levels(b, s - 1)
    piv_res = [(l, n) for l, n in lv["res"] if "محورية" in n]
    piv_sup = [(l, n) for l, n in lv["sup"] if "محوري" in n]
    rv = C.rvol(b, s)
    for lvl, nm in sorted(piv_res, key=lambda x: x[0]):
        if b.c[s - 1] <= lvl < b.c[s]:
            strong = rv is not None and rv >= C.P["vol_clear"]
            return ok(spec, 0.6 if strong else 0.2, 0.6 if strong else 0.4,
                      f"إغلاق {b.c[s]:.2f} اخترق مقاومة {lvl:.2f} بحجم نسبي {rv if rv else float('nan'):.2f}× — {'اختراق بحجم' if strong else 'اختراق بلا حجم مشكوك فيه'}. المرجع: G2 9.3، G3 §5.", _src(data))
    for lvl, nm in sorted(piv_sup, key=lambda x: -x[0]):
        if b.c[s - 1] >= lvl > b.c[s]:
            strong = rv is not None and rv >= C.P["vol_clear"]
            return ok(spec, -0.6 if strong else -0.2, 0.6 if strong else 0.4,
                      f"إغلاق {b.c[s]:.2f} كسر دعماً {lvl:.2f} بحجم نسبي {rv if rv else float('nan'):.2f}×. المرجع: G2 9.3، G3 §5.", _src(data))
    if s >= 2:
        lv2 = C.levels(b, s - 2)
        for lvl, nm in lv2["res"]:
            if "محورية" in nm and b.c[s - 2] <= lvl < b.c[s - 1] and b.c[s] < lvl:
                return ok(spec, -0.5, 0.55, f"اختراق كاذب: أغلق أمس فوق {lvl:.2f} ثم عاد اليوم دونه ({b.c[s]:.2f}) فأُبطل شرط الثبات. المرجع: G3 §5 و§11.", _src(data))
        for lvl, nm in lv2["sup"]:
            if "محوري" in nm and b.c[s - 2] >= lvl > b.c[s - 1] and b.c[s] > lvl:
                return ok(spec, 0.5, 0.55, f"كسر كاذب: أغلق أمس دون {lvl:.2f} ثم عاد فوقه ({b.c[s]:.2f}). المرجع: G3 §5.", _src(data))
    st = C.structure(b, s)
    lvn = C.levels(b, s)
    sup = C.near_level(b, s, b.l[s], "sup", lvn)
    res = C.near_level(b, s, b.h[s], "res", lvn)
    if sup and st.get("dir", 0) >= 0 and b.c[s] >= sup[0]:
        return ok(spec, 0.3, 0.45, f"السعر {b.c[s]:.2f} يختبر دعماً ({sup[1]} {sup[0]:.2f}) والبنية {st.get('label','?')}. المرجع: G1 ص7، G2 9.2.", _src(data))
    if res and st.get("dir", 0) <= 0 and b.c[s] <= res[0]:
        return ok(spec, -0.3, 0.45, f"السعر {b.c[s]:.2f} يختبر مقاومة ({res[1]} {res[0]:.2f}) والبنية {st.get('label','?')}. المرجع: G1 ص7، G2 9.2.", _src(data))
    return nf(spec, f"السعر {b.c[s]:.2f} في منطقة محايدة بعيداً عن الدعم والمقاومة (تسامح {lvn['tol']:.2f}) — لا يُقرأ (G1 ص9).", _src(data))


# ── 4-14. pattern families ──────────────────────────────────────────────────
@_reg("candle-single-reversal", "وكيل الشموع الانعكاسية المفردة", "Single-Candle Reversals", 0.7,
      "المطرقة، الرجل المشنوق، المطرقة المقلوبة، النجم الساقط، دوجي اليعسوب وشاهد القبر — يسمّيها الاتجاه السابق.",
      "OHLC، ATR14، اتجاه 10 شموع سابقة، المستويات، الحجم، RSI14، المتوسط 200، الاتجاه الأسبوعي.",
      "ظل ≥ 2× الجسم والظل المقابل ≤10% من المدى (G1 ص4، G2 5.3-5.4). تأكيد: إغلاق تالٍ فوق القمة (صاعد) أو تحت القاع (شهاب) أو تحت الجسم (مشنوق) (G1 ص4 وص8). RSI<30 يقوّي المطرقة وRSI>60 يضعفها، RSI>70 يقوّي الشهاب (G1 ص8). الثقة من سلّم الأدلة 5 بنود (G2 10.3) × معامل الاختبار الخلفي.")
def candle_single(data, spec):
    return _pattern_agent(data, spec, "candle-single-reversal", "نموذج انعكاس مفرد")


@_reg("candle-indecision", "وكيل الدوجي والقمة الدوارة", "Doji & Spinning Top", 0.45,
      "الدوجي القياسي وطويل الأرجل والقمة الدوارة كإنذار تعب الاتجاه — انتباه لا أمر.",
      "OHLC واتجاه 10 شموع سابقة والمستويات والتأكيد التالي.",
      "دوجي: الجسم ≤5% من المدى (افتراضي لـ«تقريباً»؛ G3 §11 يعامل جسماً بنسبة 10% كمطرقة محتملة). القمة الدوارة: جسم 5–30% وظلان ≥25% متقاربان (نسبة 0.5–2). في نطاق عرضي لا معنى له (G1 ص3) فلا يُسجَّل. يتحول لإشارة فقط عند مستوى + شمعة تأكيد عكس الاتجاه السابق (G2 ص9). الإشارة ≤0.5.")
def candle_indecision(data, spec):
    return _pattern_agent(data, spec, "candle-indecision", "دوجي أو قمة دوارة بعد اتجاه")


@_reg("candle-marubozu", "وكيل الماروبوزو", "Marubozu", 0.6,
      "شمعة القرار الحاسم: جسم طويل بلا ظلال تقريباً، وأقوى ما تكون عند اختراق مستوى.",
      "OHLC، متوسط الأجسام، المستويات.",
      "جسم ≥1.3× متوسط 10 أجسام وكل ظل ≤5% من المدى (افتراضي). صاعد يخترق مقاومة = شراء قوي، هابط يكسر دعماً = بيع (G2 5.1). بعد حركة ممتدة جداً قد تعني إجهاداً فتُخفض. لا يحتاج تأكيداً (G1 ص10). الوقف تحت أدنى الصاعد/فوق أعلى الهابط.")
def candle_marubozu(data, spec):
    return _pattern_agent(data, spec, "candle-marubozu", "ماروبوزو")


@_reg("candle-engulfing", "وكيل الابتلاع", "Engulfing", 0.75,
      "الابتلاع الشرائي والبيعي — أقوى نماذج الانعكاس شيوعاً.",
      "OHLC لشمعتين، اتجاه 10 شموع، المستويات، الحجم.",
      "حمراء ثم خضراء يبتلع جسمها جسم الأولى (افتتاح ≤ إغلاق الأولى وإغلاق ≥ افتتاحها) وجسم ثانٍ أطول، بعد هبوط؛ والعكس (G2 6.1، G1 ص5، G3 §7). لا يشترط ابتلاع الظلال. التأكيد مفضل: إغلاق تالٍ أبعد من إغلاق الابتلاع. الوقف خلف أدنى/أعلى سعر في النموذج.")
def candle_engulfing(data, spec):
    return _pattern_agent(data, spec, "candle-engulfing", "ابتلاع")


@_reg("candle-harami", "وكيل الحرامي", "Harami", 0.5,
      "الحرامي الشرائي والبيعي (وحرامي كروس) — توقف زخم لا انعكاس بعد.",
      "OHLC لشمعتين + الشمعة التالية للتأكيد.",
      "أم طويلة (≥1.3× المتوسط) وجسم صغير (≤50% من جسم الأم، افتراضي) داخل جسم الأم (G2 6.2، G1 ص5). يحتاج دائماً تأكيداً: إغلاق خارج مدى الأم (G1 ص5). دون تأكيد الثقة منخفضة.")
def candle_harami(data, spec):
    return _pattern_agent(data, spec, "candle-harami", "حرامي")


@_reg("candle-piercing-darkcloud", "وكيل خط الاختراق والسحابة الداكنة", "Piercing Line & Dark Cloud", 0.65,
      "نماذج المنتصف: خط الاختراق بعد هبوط وغطاء السحابة الداكنة بعد صعود.",
      "OHLC لشمعتين، منتصف جسم الأولى.",
      "الثانية تفتح أدنى من إغلاق الحمراء وتغلق فوق 50% من جسمها دون ابتلاعه — إلزامي (G2 6.3، G1 ص5)؛ والسحابة تفتح فوق إغلاق الخضراء وتغلق تحت منتصفها. الوقف تحت قاع/فوق قمة النموذج.")
def candle_piercing(data, spec):
    return _pattern_agent(data, spec, "candle-piercing-darkcloud", "خط اختراق أو سحابة داكنة")


@_reg("candle-tweezers", "وكيل الملقط", "Tweezer Top/Bottom", 0.55,
      "قاع الملقط وقمة الملقط: اختبار المستوى مرتين والفشل في كسره.",
      "قيعان/قمم شمعتين متتاليتين، ATR14، اتجاه سابق.",
      "تطابق القاعين ضمن 0.1×ATR (افتراضي لـ«تقريباً») بعد هبوط وعند أدنى قاع في 5 شموع (G2 6.4، G1 ص5). التأكيد: إغلاق فوق قمة الشمعة الثانية. الوقف تحت القاع المشترك مباشرة.")
def candle_tweezers(data, spec):
    return _pattern_agent(data, spec, "candle-tweezers", "ملقط")


@_reg("candle-stars", "وكيل نجمتي الصباح والمساء", "Morning/Evening Star", 0.8,
      "ملوك النماذج الانعكاسية الثلاثية (ونجمة الدوجي الأقوى).",
      "OHLC لثلاث شموع، منتصف جسم الأولى.",
      "حمراء طويلة، ثم نجمة جسمها ≤35% من الأولى منفصلة تحت إغلاقها، ثم خضراء تغلق فوق منتصف جسم الأولى بعد هبوط (G2 7.1، G1 ص6، G3 §7)؛ والعكس للمساء. الشمعة الثالثة هي التأكيد. الوقف تحت قاع النجمة/فوق قمتها.")
def candle_stars(data, spec):
    return _pattern_agent(data, spec, "candle-stars", "نجمة صباح أو مساء")


@_reg("candle-soldiers-crows", "وكيل الجنود البيض والغربان السود", "Three Soldiers / Crows", 0.7,
      "ثلاث شموع متتالية بزخم منظم صاعد أو هابط.",
      "OHLC لثلاث شموع.",
      "ثلاث خضراء كل منها ≥0.8× متوسط الجسم، تفتح داخل جسم السابقة وتغلق أعلى، وظل علوي ≤25% من المدى (G2 7.2، G1 ص6). بعد صعود ممتد (≥3 ATR) قد يكون تشبعاً فتُنصف الإشارة؛ والعكس للغربان. الوقف تحت قاع الجندي الأول/فوق قمة الغراب الأول.")
def candle_soldiers(data, spec):
    return _pattern_agent(data, spec, "candle-soldiers-crows", "جنود أو غربان")


@_reg("candle-three-inside", "وكيل الثلاثة الداخلية", "Three Inside Up/Down", 0.7,
      "الحرامي المؤكد: أم طويلة، داخلية صغيرة، ثم إغلاق خارج الأم.",
      "OHLC لثلاث شموع.",
      "حرامي ثم ثالثة تغلق فوق قمة الأولى (صاعد) أو تحت قاعها (هابط) كما نص G2 7.3 ص16. الوقف تحت قاع النموذج/فوق قمته.")
def candle_three_inside(data, spec):
    return _pattern_agent(data, spec, "candle-three-inside", "ثلاثة داخلية")


@_reg("candle-continuation", "وكيل الاستمرار والنوافذ", "Three Methods & Windows (Gaps)", 0.65,
      "الطرق الثلاث الصاعدة/الهابطة والنوافذ السعرية (الفجوات) كنماذج استمرار.",
      "OHLC لخمس شموع؛ فجوات بين جلستين.",
      "طويلة مع الاتجاه، ثلاث صغيرة داخل مداها، ثم خامسة تغلق خارج قمة/قاع الأولى (G2 8.1). نافذة صاعدة: قاع اليوم > قمة أمس وتصبح دعماً، وإغلاقها (العودة تحت حافتها) ضعف (G2 8.2). الوقف تحت قاع الشمعة الأولى/حافة النافذة.")
def candle_continuation(data, spec):
    return _pattern_agent(data, spec, "candle-continuation", "نموذج استمرار أو نافذة")


# ── 15. volume ──────────────────────────────────────────────────────────────
@_reg("candle-volume", "وكيل تأكيد الحجم للشموع", "Candle Volume Confirmation", 0.6,
      "قراءة الحجم كوقود الحركة: هل النموذج والاتجاه القصير مدعومان بحجم؟",
      "حجم يومي، متوسط 20 شمعة، آخر 10 شموع.",
      "G2 10.1: صعود بحجم متزايد +0.4، صعود بحجم متناقص −0.2 (ضعف شراء)، هبوط بحجم متناقص +0.2 (ضعف بيع)، هبوط بحجم متزايد −0.4. تغيّر الحجم = متوسط آخر 5 ÷ الخمسة قبلها (±10% افتراضي). G1 ص8: النمط بحجم ≥ متوسط 20 بوضوح مدعوم، والضعيف شكل بلا قوة.")
def candle_volume(data: MarketData, spec):
    cx = _ctx(data)
    if cx is None:
        return nf(spec, "أقل من 60 شمعة.", _src(data))
    b = cx["bars"]
    v = b.v[-10:]
    if not np.all(np.isfinite(v)) or np.nanmean(v[:5]) <= 0:
        return nf(spec, "حجم التداول غير متوفر لآخر 10 شموع.", _src(data))
    vchg = float(np.mean(v[5:]) / np.mean(v[:5]) - 1)
    pchg = float(b.c[-1] / b.c[-6] - 1)
    if abs(vchg) < 0.10:
        sig, txt = 0.1 * np.sign(pchg), "الحجم مستقر"
    elif pchg >= 0 and vchg > 0:
        sig, txt = 0.4, "صعود بحجم متزايد"
    elif pchg >= 0:
        sig, txt = -0.2, "صعود بحجم متناقص = ضعف في الشراء"
    elif vchg < 0:
        sig, txt = 0.2, "هبوط بحجم متناقص = ضعف في البيع"
    else:
        sig, txt = -0.4, "هبوط بحجم متزايد"
    pats = [e for e, _ in cx["events"] if not e.failed and e.direction != 0]
    ptxt = ""
    if pats:
        e = pats[0]
        rv = e.ctx.get("rvol")
        ptxt = f"؛ نمط {e.name_ar} حجمه النسبي {rv:.2f}× {'(مدعوم)' if rv and rv >= C.P['vol_clear'] else '(ضعيف — شكل بلا قوة)'}" if rv else ""
    return ok(spec, sig, 0.4,
              f"{txt}: السعر {pchg*100:+.1f}% في 5 جلسات والحجم {vchg*100:+.0f}% مقابل الخمس السابقة{ptxt}. المرجع: G2 10.1، G1 ص8.",
              _src(data))


# ── 16. confirmation / checklist gate ───────────────────────────────────────
def _strongest(cx):
    alive = [e for e, f in cx["events"] if not e.failed]
    if not alive:
        return None
    return max(alive, key=lambda e: (C.PATTERNS[e.key][4] * (0.5 + e.ladder / 5), e.end))


def _target(b, s, eff, entry):
    lv = C.levels(b, s)
    if eff > 0:
        cands = [l for l, n in lv["res"] if "محورية" in n and l > entry]
        return (min(cands), "أقرب مقاومة محورية") if cands else (None, None)
    cands = [l for l, n in lv["sup"] if "محوري" in n and l < entry]
    return (max(cands), "أقرب دعم محوري") if cands else (None, None)


@_reg("candle-confirmation", "وكيل شمعة التأكيد وقائمة الفحص", "Confirmation Candle & 7-Point Checklist", 0.6,
      "بوابة الدخول: لا صفقة إلا إذا اكتملت البنود السبعة؛ بند ناقص يعني الانتظار.",
      "أقوى نمط نشط من المجموعة، البنية، المستوى، الحجم، شمعة التأكيد، الهدف والوقف.",
      "G1 ص9 وG2 12.2: (1) اتجاه يومي محدد (2) عند مستوى (3) مع الاتجاه الأكبر أو انعكاس بعد اتجاه ممتد (4) حجم أعلى من المتوسط (5) شمعة تأكيد أغلقت في اتجاه الصفقة (6) وقف خلف النمط وهدف عند المستوى التالي بنسبة ≥2:1 (7) مخاطرة ≤2% (تُحسب دائماً). 7/7 = إشارة باتجاه النمط 0.75؛ وإلا «انتظار» إشارة 0 بثقة 0.45.")
def candle_confirmation(data: MarketData, spec):
    cx = _ctx(data)
    if cx is None:
        return nf(spec, "أقل من 60 شمعة.", _src(data))
    e = _strongest(cx)
    if e is None:
        return nf(spec, "لا نمط شموع نشط لتطبيق قائمة الفحص عليه.", _src(data))
    b = cx["bars"]
    s = b.n - 1
    eff = e.direction if e.direction != 0 else e.confirm_side
    st = e.ctx.get("structure") or {}
    entry = float(b.c[s])
    tgt, _ = _target(b, s, eff, entry)
    risk = abs(entry - e.stop)
    rr = (abs(tgt - entry) / risk) if (tgt is not None and risk > 0) else None
    rv = e.ctx.get("rvol")
    items = [
        ("الاتجاه اليومي محدد", st.get("ok", False) and "انتقالي" not in st.get("label", "")),
        ("عند مستوى", bool(e.ladder_items.get("location"))),
        ("يتفق مع الاتجاه الأكبر أو انعكاس بعد اتجاه ممتد", st.get("dir") == eff or (C.PATTERNS[e.key][2] == "reversal" and abs(e.ctx.get("prior_move_atr", 0)) >= C.P["extended_trend_atr"])),
        ("حجم أعلى من المتوسط", rv is not None and rv > 1.0),
        ("شمعة التأكيد أغلقت", e.confirmed is True),
        ("عائد/مخاطرة ≥ 2:1", rr is not None and rr >= C.P["rr_min"]),
        ("مخاطرة ≤ 2%", True),
    ]
    yes = sum(1 for _, v in items if v)
    missing = [n for n, v in items if not v]
    if yes == 7:
        return ok(spec, 0.75 * eff, 0.7, f"{e.name_ar}: اكتملت البنود السبعة. المرجع: G1 ص9، G2 12.2.", _src(data))
    return ok(spec, 0.0, 0.45,
              f"{e.name_ar}: {yes}/7 بنود — ناقص: {'، '.join(missing)} → القرار المهني انتظار. المرجع: G1 ص9، G2 12.2.",
              _src(data))


# ── 17. weekly timeframe ────────────────────────────────────────────────────
def _weekly_df(b: C.Bars) -> pd.DataFrame | None:
    df = b.df.copy()
    try:
        if getattr(df.index, "tz", None) is not None:
            df.index = df.index.tz_localize(None)
    except Exception:
        pass
    w = df.resample("W-THU").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
    if w.empty:
        return None
    last_day = df.index[-1]
    if last_day.weekday() != 3:  # Tadawul week ends Thursday: drop the unfinished week (G3 §2)
        w = w.iloc[:-1]
    return w


@_reg("candle-weekly", "وكيل الإطار الأسبوعي للشموع", "Weekly Candles & TF Agreement", 0.8,
      "قراءة الشموع والبنية على الإطار الأسبوعي (الأكبر له الأولوية) ومقارنتها باليومي.",
      "شموع أسبوعية مكتملة (الأسبوع ينتهي الخميس) مجمّعة من اليومي.",
      "G2 10.2 وG3 §8: ابدأ بالأسبوعي للقمم والقيعان الكبيرة؛ إذا تعارض الإطاران فالكلمة للأكبر. الإشارة = 0.4×بنية أسبوعية + إشارة أي نمط أسبوعي نشط (آخر أسبوعين). G1 ص1: الإطار الأكبر أوثق.")
def candle_weekly(data: MarketData, spec):
    cx = _ctx(data)
    if cx is None:
        return nf(spec, "أقل من 60 شمعة يومية.", _src(data))
    w = _weekly_df(cx["bars"])
    if w is None or len(w) < 40:
        return nf(spec, f"أقل من 40 شمعة أسبوعية مكتملة ({0 if w is None else len(w)}).", _src(data))
    wb = C.Bars(w)
    st = C.structure(wb, wb.n - 1)
    evs = []
    for s in range(wb.n - 2, wb.n):
        evs.extend([e for e in C.scan_at(wb, s, None) if not e.failed])
    sig = 0.4 * st.get("dir", 0) if st.get("ok") else 0.0
    parts = [f"البنية الأسبوعية {st.get('label', 'غير محددة')}"]
    if evs:
        e = max(evs, key=lambda e: C.PATTERNS[e.key][4])
        ps, pc, _ = C.score_event(e)
        sig += 0.6 * ps
        parts.append(f"نمط أسبوعي: {e.name_ar} (أسبوع {str(w.index[e.end])[:10]}، سلّم {e.ladder}/5)")
    dst = C.structure(cx["bars"], cx["bars"].n - 1)
    if dst.get("ok") and st.get("ok"):
        agree = dst["dir"] == st["dir"]
        parts.append(f"اليومي {dst['label']} — {'متوافق' if agree else 'غير متوافق؛ الأولوية للأسبوعي'}")
    if not st.get("ok") and not evs:
        return nf(spec, "لا بنية أسبوعية واضحة ولا نمط أسبوعي.", _src(data))
    conf = 0.55 if st.get("dir", 0) != 0 else 0.35
    return ok(spec, max(-1, min(1, sig)), conf, "؛ ".join(parts) + ". المرجع: G2 10.2، G3 §8، G1 ص1.", _src(data))


# ── 18. risk / invalidation ─────────────────────────────────────────────────
def _earnings_soon(data: MarketData, days: int = 7):
    cal = data.calendar or {}
    ed = cal.get("Earnings Date") or cal.get("earnings_date")
    if not ed:
        return None
    if not isinstance(ed, (list, tuple)):
        ed = [ed]
    today = datetime.now(C.RIYADH).date()
    for d in ed:
        try:
            dd = d if isinstance(d, date) else pd.Timestamp(d).date()
        except Exception:
            continue
        if 0 <= (dd - today).days <= days:
            return dd
    return None


@_reg("candle-risk-stop", "وكيل إبطال النمط ووقف الخسارة", "Pattern Invalidation & Stop", 0.7,
      "اشتقاق سعر الإبطال (الوقف) من النمط كما تنص الأدلة، والهدف عند المستوى التالي، ونسبة العائد للمخاطرة وحجم المركز.",
      "أقوى نمط نشط، آخر إغلاق، المستويات المحورية، تقويم الأرباح من Yahoo.",
      "الوقف خلف حدود النمط: تحت قاع المطرقة/النجمة/النموذج، فوق قمة الشهاب/النجمة، تحت القاع المشترك للملقط، تحت قاع الجندي الأول، حافة النافذة (G2 11.2 ص23 وكل نموذج). الهدف = المستوى المحوري التالي. ≥2:1 = إشارة باتجاه النمط 0.4؛ 1–2 = لا صفقة (0)؛ <1 = −0.2. حجم المركز = مبلغ المخاطرة (1–2%) ÷ مسافة الوقف (G2 11.2). إعلان نتائج خلال 7 أيام = انتظار (G1 ص9 خطأ 7).")
def candle_risk_stop(data: MarketData, spec):
    cx = _ctx(data)
    if cx is None:
        return nf(spec, "أقل من 60 شمعة.", _src(data))
    e = _strongest(cx)
    if e is None:
        return nf(spec, "لا نمط نشط يُشتق منه سعر إبطال.", _src(data))
    b = cx["bars"]
    s = b.n - 1
    eff = e.direction if e.direction != 0 else e.confirm_side
    entry = float(b.c[s])
    risk = (entry - e.stop) * eff
    if risk <= 0:
        return nf(spec, f"الإغلاق {entry:.2f} تجاوز سعر إبطال {e.name_ar} ({e.stop:.2f}).", _src(data))
    tgt, tname = _target(b, s, eff, entry)
    data._candle_risk = {"pattern": e.name_ar, "stop": e.stop, "target": tgt, "dir": eff, "entry": entry}
    per100k = f"لكل 100,000 ر.س ومخاطرة 1%: {int(1000 / risk)} سهماً تقريباً"
    soon = _earnings_soon(data)
    if soon:
        return ok(spec, 0.0, 0.5, f"{e.name_ar}: الإبطال {e.stop:.2f} لكن إعلان نتائج متوقع {soon} — لا تتداول النمط قبل الخبر (G1 ص9 خطأ 7).", _src(data) + " + Yahoo Finance / calendar")
    if tgt is None:
        return ok(spec, 0.0, 0.3, f"{e.name_ar}: الإبطال {e.stop:.2f} (مسافة {risk/entry*100:.1f}%)، والهدف NOT FOUND (لا مستوى محوري تالٍ)؛ {per100k}. المرجع: G2 11.2.", _src(data))
    rr = abs(tgt - entry) / risk
    if rr >= C.P["rr_min"]:
        sig, verdict = 0.4 * eff, "نسبة مقبولة"
    elif rr >= 1.0:
        sig, verdict = 0.0, "أقل من 2:1 → لا صفقة"
    else:
        sig, verdict = -0.2 * eff, "العائد أقل من المخاطرة"
    return ok(spec, sig, 0.55,
              f"{e.name_ar}: دخول {entry:.2f}، إبطال {e.stop:.2f} ({risk/entry*100:.1f}%)، هدف {tgt:.2f} ({tname})، عائد/مخاطرة {rr:.2f}:1 — {verdict}؛ {per100k}. المرجع: G2 11.2 و12.1، G1 ص9.",
              _src(data))
