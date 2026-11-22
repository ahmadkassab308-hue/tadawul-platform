"""Fundamental analyst scoring functions. Never invent a missing statement or ratio."""
from __future__ import annotations

from typing import Optional

from .analysts_common import fmt, fmt_pct, nf, ok, register, src_info
from .fetch import info_number, normalize_yield
from .models import MarketData


def _ratio_from_peers(data: MarketData, key: str) -> Optional[float]:
    # Peer histories are prices only; peer fundamentals are not pre-fetched to avoid
    # silent guesses. Relative PE is handled only when we already have the stock's own
    # ratio. This helper is a placeholder so callers do not invent peer fundamentals.
    return None


@register(
    "pe-valuation",
    "وكيل مكرر الربحية",
    "P/E Valuation",
    "fundamental",
    "fundamental",
    "pe-valuation.md",
    1.2,
    "تقييم مكرر الربحية الحالي مقابل المكرر الآجل فقط من بيانات السهم نفسه.",
    "info.trailingPE و info.forwardPE.",
    "إن وُجد المكرر الآجل وهو أقل من الحالي فالسوق يسعّر نمواً (ميل إيجابي محدود). مكرر حالي دون 8 أو فوق 35 يُعد طرفياً (ثقة أعلى). لا يُستخدم متوسط قطاع مخمّن. إن غاب المكرر: NOT FOUND.",
)
def pe_valuation(data: MarketData, spec):
    pe = info_number(data.info, "trailingPE")
    fpe = info_number(data.info, "forwardPE")
    if pe is None and fpe is None:
        return nf(spec, "لا مكرر ربحية حالي ولا آجل في Yahoo Finance.", src_info(data, "trailingPE/forwardPE"))
    bits = []
    sig, conf = 0.0, 0.4
    if pe is not None:
        bits.append(f"مكرر حالي {fmt(pe, 1)}×")
        if pe < 8:
            sig += 0.55
            conf = 0.65
        elif pe > 35:
            sig -= 0.55
            conf = 0.65
        elif pe > 25:
            sig -= 0.2
        elif pe < 12:
            sig += 0.2
    if fpe is not None:
        bits.append(f"آجل {fmt(fpe, 1)}×")
        if pe is not None and pe > 0:
            if fpe < pe * 0.9:
                sig += 0.35
                conf = max(conf, 0.6)
                bits.append("الآجل أقل بوضوح من الحالي")
            elif fpe > pe * 1.15:
                sig -= 0.25
                conf = max(conf, 0.55)
                bits.append("الآجل أعلى من الحالي")
    return ok(spec, sig, conf, "؛ ".join(bits) + ".", src_info(data, "trailingPE/forwardPE"))


@register(
    "pb-valuation",
    "وكيل مكرر القيمة الدفترية",
    "P/B Valuation",
    "fundamental",
    "fundamental",
    "pb-valuation.md",
    1.05,
    "تقييم السعر إلى القيمة الدفترية حسب طبيعة القطاع (المصارف تُقيَّم عادة عند مكررات مختلفة عن الصناعي).",
    "info.priceToBook و info.bookValue والقطاع.",
    "للمصارف: P/B تحت 1 ميل إيجابي، فوق 3 حذر. لغيرها: تحت 1.2 إيجابي، فوق 5 حذر. الحدود قواعد معلنة في method لا متوسطات مخمّنة من السوق.",
)
def pb_valuation(data: MarketData, spec):
    pb = info_number(data.info, "priceToBook")
    bv = info_number(data.info, "bookValue")
    if pb is None:
        return nf(spec, "لا مكرر قيمة دفترية في المصدر.", src_info(data, "priceToBook"))
    bank = "Bank" in (data.industry or "") or "Financial" in (data.sector or "")
    if bank:
        if pb < 1:
            sig, conf = 0.6, 0.65
        elif pb < 1.5:
            sig, conf = 0.25, 0.5
        elif pb <= 3.0:
            sig, conf = 0.0, 0.4
        else:
            sig, conf = -0.4 if pb <= 4.5 else -0.65, 0.6
        ctx = "قطاع مالي"
    else:
        if pb < 1.2:
            sig, conf = 0.55, 0.6
        elif pb < 2.5:
            sig, conf = 0.15, 0.45
        elif pb <= 5:
            sig, conf = -0.15, 0.45
        else:
            sig, conf = -0.55, 0.6
        ctx = "غير مالي"
    extra = f" والقيمة الدفترية للسهم {fmt(bv)} ر.س" if bv else ""
    return ok(spec, sig, conf, f"مكرر القيمة الدفترية {fmt(pb, 2)}× ({ctx}){extra}.", src_info(data, "priceToBook"))


@register(
    "ev-ebitda",
    "وكيل EV/EBITDA",
    "EV / EBITDA",
    "fundamental",
    "fundamental",
    "ev-ebitda.md",
    1.1,
    "تقييم المضاعف المؤسسي EV/EBITDA إن توفر (غالباً غير مناسب للمصارف).",
    "info.enterpriseToEbitda.",
    "تحت 6 ميل رخيص، 6–12 معتدل، فوق 18 مرتفع. إن غاب الحقل (شائع للمصارف): NOT FOUND.",
)
def ev_ebitda(data: MarketData, spec):
    v = info_number(data.info, "enterpriseToEbitda")
    if v is None:
        return nf(
            spec,
            "لا قيمة EV/EBITDA في Yahoo Finance (شائع في المصارف).",
            src_info(data, "enterpriseToEbitda"),
        )
    if v < 0:
        return nf(spec, f"قيمة EV/EBITDA سالبة ({fmt(v, 1)}) ولا تُفسر كرخص.", src_info(data, "enterpriseToEbitda"))
    if v < 6:
        sig, conf = 0.6, 0.65
    elif v <= 12:
        sig, conf = 0.15, 0.45
    elif v <= 18:
        sig, conf = -0.2, 0.5
    else:
        sig, conf = -0.6, 0.65
    return ok(spec, sig, conf, f"EV/EBITDA عند {fmt(v, 1)}×.", src_info(data, "enterpriseToEbitda"))


@register(
    "earnings-growth",
    "وكيل نمو الأرباح",
    "Earnings Growth",
    "fundamental",
    "fundamental",
    "earnings-growth.md",
    1.15,
    "تقييم نمو الأرباح المعلن إن وُجد.",
    "info.earningsGrowth. لا يُشتق رقم من القوائم إن غاب الحقل إلا إذا توفرت أرباح صافية سنوية صريحة في financials.",
    "نمو موجب قوي (>15%) إشارة موجبة، انكماش إشارة سالبة. إن غاب الحقل والقوائم: NOT FOUND.",
)
def earnings_growth(data: MarketData, spec):
    g = info_number(data.info, "earningsGrowth")
    source = src_info(data, "earningsGrowth")
    if g is None and data.financials is not None and not data.financials.empty:
        # try Net Income row across columns (most recent two years)
        for key in data.financials.index:
            if str(key).lower() in ("net income", "net income common stockholders", "net income continuous operations"):
                row = data.financials.loc[key].dropna()
                if len(row) >= 2:
                    a, b = float(row.iloc[0]), float(row.iloc[1])
                    if b != 0:
                        g = a / b - 1.0
                        source = f"Yahoo Finance / financials[{key}] ({data.ticker})"
                        break
    if g is None:
        return nf(spec, "لا رقم لنمو الأرباح في info ولا في قائمة الدخل.", source)
    sig = max(-1.0, min(1.0, g / 0.25))
    conf = 0.55 + 0.2 * min(1.0, abs(g) / 0.2)
    return ok(spec, sig, conf, f"نمو الأرباح المعلن {fmt_pct(g)}.", source)


@register(
    "revenue-growth",
    "وكيل نمو الإيرادات",
    "Revenue Growth",
    "fundamental",
    "fundamental",
    "revenue-growth.md",
    1.1,
    "تقييم نمو الإيرادات المعلن.",
    "info.revenueGrowth.",
    "نمو إيرادات قوي يدعم الشراء، والانكماش يحذّر. إن غاب: NOT FOUND.",
)
def revenue_growth(data: MarketData, spec):
    g = info_number(data.info, "revenueGrowth")
    if g is None:
        return nf(spec, "لا رقم لنمو الإيرادات.", src_info(data, "revenueGrowth"))
    sig = max(-1.0, min(1.0, g / 0.2))
    conf = 0.55 + 0.2 * min(1.0, abs(g) / 0.15)
    return ok(spec, sig, conf, f"نمو الإيرادات المعلن {fmt_pct(g)}.", src_info(data, "revenueGrowth"))


@register(
    "profit-margins",
    "وكيل الهوامش الربحية",
    "Profit Margins",
    "fundamental",
    "fundamental",
    "profit-margins.md",
    1.1,
    "قراءة هامش الربح التشغيلي والصافي.",
    "info.profitMargins و info.operatingMargins و info.grossMargins.",
    "هوامش صافية فوق 15% قوية (غير المصارف)، والمصارف تُقرأ بهامش أعلى عادة. هامش سالب إشارة ضعيفة واضحة. إن غابت كلها: NOT FOUND.",
)
def profit_margins(data: MarketData, spec):
    p = info_number(data.info, "profitMargins")
    o = info_number(data.info, "operatingMargins")
    g = info_number(data.info, "grossMargins")
    if p is None and o is None:
        return nf(spec, "لا هوامش ربحية في المصدر.", src_info(data, "profitMargins"))
    bank = "Bank" in (data.industry or "")
    bits = []
    base = p if p is not None else o
    if p is not None:
        bits.append(f"صافي {fmt_pct(p)}")
    if o is not None:
        bits.append(f"تشغيلي {fmt_pct(o)}")
    if g is not None and g != 0:
        bits.append(f"إجمالي {fmt_pct(g)}")
    # banks often have very high 'profitMargins' on a different base — still use the number but mild
    if bank:
        sig = max(-1, min(1, (base - 0.35) / 0.35)) if base is not None else 0
        conf = 0.5
        bits.append("قراءة مصرفية")
    else:
        if base is not None and base < 0:
            sig, conf = -0.8, 0.75
        elif base is not None and base >= 0.2:
            sig, conf = 0.65, 0.7
        elif base is not None and base >= 0.1:
            sig, conf = 0.35, 0.55
        elif base is not None and base >= 0.05:
            sig, conf = 0.1, 0.45
        else:
            sig, conf = -0.25, 0.5
    return ok(spec, sig, conf, "الهوامش: " + "، ".join(bits) + ".", src_info(data, "profitMargins/operatingMargins"))


@register(
    "debt-leverage",
    "وكيل الرفع والدين",
    "Debt / Leverage",
    "fundamental",
    "fundamental",
    "debt-leverage.md",
    1.05,
    "تقييم عبء الدين عبر Debt/Equity أو إجمالي الدين إلى النقد.",
    "info.debtToEquity أو info.totalDebt مع info.totalCash. Yahoo يورد debtToEquity عادة مضروباً في 100 (19.4 تعني 19.4%).",
    "للشركات غير المالية: D/E تحت 50% مريح، فوق 150% حذر. للمصارف الحقل غالباً غير مناسب أو غائب فيُعلَن NOT FOUND إن لم يتوفر مقياس صالح.",
)
def debt_leverage(data: MarketData, spec):
    de = info_number(data.info, "debtToEquity")
    debt = info_number(data.info, "totalDebt")
    cash = info_number(data.info, "totalCash")
    bank = "Bank" in (data.industry or "")
    if bank and de is None:
        return nf(
            spec,
            "مقياس الدين/حقوق الملكية غير متاح للمصرف في المصدر، ولا يُستنتج من إجمالي الدين وحده.",
            src_info(data, "debtToEquity"),
        )
    if de is not None:
        de_frac = de / 100.0 if de > 5 else de  # if already a ratio around 0.2 keep it; 19.4 -> 0.194
        # Heuristic documented: values > 5 are treated as percent units used by Yahoo.
        if de <= 5:
            de_frac = de
        sig = 0.5 if de_frac < 0.5 else (0.15 if de_frac < 1.0 else (-0.35 if de_frac < 1.5 else -0.7))
        conf = 0.6
        txt = f"الدين/حقوق الملكية {fmt(de, 1)} (وحدة Yahoo، أي نحو {fmt_pct(de_frac)})."
        source = src_info(data, "debtToEquity")
    elif debt is not None and cash is not None:
        net = debt - cash
        if cash > 0 and net <= 0:
            sig, conf, txt = 0.55, 0.55, f"صافي نقدي: نقد {debt and fmt(cash/1e9, 1)} مقابل دين {fmt(debt/1e9, 1)} مليار."
        else:
            return nf(spec, "لا نسبة دين/حقوق ملكية، وصافي الدين وحده لا يكفي بدون حقوق الملكية.", src_info(data, "totalDebt"))
        source = src_info(data, "totalDebt/totalCash")
        # fix typo in txt if we got here with net<=0
        txt = f"النقد يغطي الدين (نقد {fmt(cash/1e9, 1)} مليار ودين {fmt(debt/1e9, 1)} مليار)."
    else:
        return nf(spec, "لا بيانات دين كافية.", src_info(data, "debtToEquity"))
    return ok(spec, sig, conf, txt, source)


@register(
    "free-cash-flow",
    "وكيل التدفق النقدي الحر",
    "Free Cash Flow",
    "fundamental",
    "fundamental",
    "free-cash-flow.md",
    1.15,
    "تقييم التدفق النقدي الحر وعلاقته بالقيمة السوقية.",
    "info.freeCashflow و info.operatingCashflow و info.marketCap. أو قائمة التدفقات إن وُجد صف Free Cash Flow.",
    "تدفق حر موجب وعائد FCF (FCF/القيمة السوقية) فوق 5% إشارة قوية. تدفق سالب إشارة ضعيفة. للمصارف الحقل قد يغيب: NOT FOUND.",
)
def free_cash_flow(data: MarketData, spec):
    fcf = info_number(data.info, "freeCashflow")
    ocf = info_number(data.info, "operatingCashflow")
    mcap = info_number(data.info, "marketCap")
    source = src_info(data, "freeCashflow")
    if fcf is None and data.cashflow is not None and not data.cashflow.empty:
        for key in data.cashflow.index:
            if str(key).lower() in ("free cash flow",):
                row = data.cashflow.loc[key].dropna()
                if len(row):
                    fcf = float(row.iloc[0])
                    source = f"Yahoo Finance / cashflow[Free Cash Flow] ({data.ticker})"
                    break
    if fcf is None:
        if ocf is None:
            return nf(spec, "لا تدفق نقدي حر ولا تشغيلي في المصدر.", source)
        # do not treat OCF as FCF
        return nf(spec, "لا رقم للتدفق النقدي الحر (يتوفر تشغيلي فقط ولم يُستخدم بديلاً).", source)
    if fcf <= 0:
        sig, conf = -0.55, 0.65
        txt = f"تدفق نقدي حر سالب أو صفر ({fmt(fcf/1e9, 2)} مليار)."
    elif mcap and mcap > 0:
        yld = fcf / mcap
        sig = max(-0.2, min(1.0, (yld - 0.03) / 0.07))
        conf = 0.7
        txt = f"التدفق الحر {fmt(fcf/1e9, 2)} مليار وعائده {fmt_pct(yld)} من القيمة السوقية."
    else:
        sig, conf = 0.4, 0.5
        txt = f"تدفق نقدي حر موجب {fmt(fcf/1e9, 2)} مليار دون قيمة سوقية للمقارنة."
    return ok(spec, sig, conf, txt, source)


@register(
    "dividend-yield",
    "وكيل العائد التوزيعات",
    "Dividend Yield",
    "fundamental",
    "fundamental",
    "dividend-yield.md",
    1.0,
    "تقييم عائد التوزيع النقدي.",
    "info.dividendYield أو trailingAnnualDividendYield (يُطبَّع إن ورد كنسبة مئوية).",
    "عائد 3–7% جذاب لكثير من الأسهم القيادية السعودية. فوق 10% يثير تساؤل الاستدامة (ثقة أقل وميل محايد/حذر). صفر أو غائب: إن وُجد payout=0 يُذكر بدون تخمين سياسة مستقبلية؛ وإن غاب تماماً NOT FOUND.",
)
def dividend_yield(data: MarketData, spec):
    raw = info_number(data.info, "dividendYield", "trailingAnnualDividendYield")
    if raw is None:
        return nf(spec, "لا عائد توزيعات في المصدر.", src_info(data, "dividendYield"))
    y = normalize_yield(raw)
    if y is None:
        return nf(spec, "تعذر تطبيع رقم عائد التوزيعات.", src_info(data, "dividendYield"))
    if y < 0.005:
        sig, conf = -0.1, 0.4
        txt = f"عائد التوزيعات ضئيل {fmt_pct(y)}."
    elif y < 0.03:
        sig, conf = 0.15, 0.5
        txt = f"عائد توزيعات {fmt_pct(y)} (معتدل/منخفض)."
    elif y <= 0.07:
        sig, conf = 0.55, 0.7
        txt = f"عائد توزيعات {fmt_pct(y)} ضمن نطاق جذاب للقياديات."
    elif y <= 0.10:
        sig, conf = 0.25, 0.5
        txt = f"عائد توزيعات مرتفع {fmt_pct(y)} ويستدعي مراجعة الاستدامة."
    else:
        sig, conf = -0.15, 0.45
        txt = f"عائد توزيعات مرتفع جداً {fmt_pct(y)} وقد لا يكون مستداماً — دون حكم قطعي."
    field = "dividendYield" if data.info.get("dividendYield") is not None else "trailingAnnualDividendYield"
    return ok(spec, sig, conf, txt, src_info(data, field))


@register(
    "roe-roa",
    "وكيل العائد على حقوق الملكية والأصول",
    "ROE / ROA",
    "fundamental",
    "fundamental",
    "roe-roa.md",
    1.1,
    "قياس كفاءة الربحية عبر ROE و ROA.",
    "info.returnOnEquity و info.returnOnAssets.",
    "ROE فوق 15% قوي، تحت 5% ضعيف. ROA يُقرأ بحذر في المصارف (منخفض عادة). إن غاب الاثنان: NOT FOUND.",
)
def roe_roa(data: MarketData, spec):
    roe = info_number(data.info, "returnOnEquity")
    roa = info_number(data.info, "returnOnAssets")
    if roe is None and roa is None:
        return nf(spec, "لا ROE ولا ROA في المصدر.", src_info(data, "returnOnEquity"))
    bits = []
    sig, conf = 0.0, 0.5
    if roe is not None:
        bits.append(f"ROE {fmt_pct(roe)}")
        sig += max(-1, min(1, (roe - 0.12) / 0.15))
        conf = 0.65
    if roa is not None:
        bits.append(f"ROA {fmt_pct(roa)}")
        bank = "Bank" in (data.industry or "")
        if not bank:
            sig = 0.7 * sig + 0.3 * max(-1, min(1, (roa - 0.05) / 0.08))
    return ok(spec, max(-1, min(1, sig)), conf, "، ".join(bits) + ".", src_info(data, "returnOnEquity/returnOnAssets"))


@register(
    "peg-ratio",
    "وكيل مكرر الربحية إلى النمو PEG",
    "PEG Ratio",
    "fundamental",
    "fundamental",
    "peg-ratio.md",
    1.1,
    "تقييم PEG إن صرّح به المصدر.",
    "info.pegRatio.",
    "PEG تحت 1 جذاب، بين 1 و2 معتدل، فوق 2 مرتفع. لا يُحسب يدوياً من PE ونمو مخمّن. إن غاب: NOT FOUND.",
)
def peg_ratio(data: MarketData, spec):
    p = info_number(data.info, "pegRatio")
    if p is None:
        return nf(spec, "لا نسبة PEG في المصدر.", src_info(data, "pegRatio"))
    if p < 0:
        return nf(spec, f"PEG سالب ({fmt(p, 2)}) ولا يُفسر كرخص.", src_info(data, "pegRatio"))
    if p < 1:
        sig, conf = 0.65, 0.7
    elif p <= 2:
        sig, conf = 0.1, 0.45
    else:
        sig, conf = -0.45 if p <= 4 else -0.7, 0.65
    return ok(spec, sig, conf, f"نسبة PEG عند {fmt(p, 2)}.", src_info(data, "pegRatio"))


@register(
    "earnings-yield",
    "وكيل عائد الربحية",
    "Earnings Yield",
    "fundamental",
    "fundamental",
    "earnings-yield.md",
    1.05,
    "عكس مكرر الربحية كعائد أرباح للمقارنة مع العوائد النقدية.",
    "1 / trailingPE. يُذكر معدل ساما فقط إن توفر فعلاً من الجلسة.",
    "عائد أرباح أعلى أفضل. إن توفر معدل ساما/سايبور يُقارن به، وإلا يُعرض العائد وحده دون افتراض سعر فائدة.",
)
def earnings_yield(data: MarketData, spec):
    pe = info_number(data.info, "trailingPE")
    if pe is None or pe <= 0:
        return nf(spec, "لا مكرر ربحية موجب لحساب عائد الربحية.", src_info(data, "trailingPE"))
    ey = 1.0 / pe
    txt = f"عائد الربحية {fmt_pct(ey)} (مقلوب مكرر {fmt(pe, 1)}×)"
    sig = max(-1, min(1, (ey - 0.05) / 0.06))
    conf = 0.55
    if data.sama and data.sama.get("value") is not None:
        try:
            rate = float(data.sama["value"])
            # FRED series may be percent
            rate_frac = rate / 100.0 if rate > 1 else rate
            gap = ey - rate_frac
            sig = max(-1, min(1, gap / 0.04))
            conf = 0.7
            txt += f" مقابل معدل {fmt_pct(rate_frac)} من {data.sama.get('source')}"
        except (TypeError, ValueError):
            pass
    return ok(spec, sig, conf, txt + ".", src_info(data, "trailingPE"))


@register(
    "current-ratio",
    "وكيل السيولة الجارية",
    "Current Ratio",
    "fundamental",
    "fundamental",
    "current-ratio.md",
    0.9,
    "تقييم القدرة على تغطية الالتزامات المتداولة.",
    "info.currentRatio و info.quickRatio. غالباً غير مناسب/غائب للمصارف.",
    "نسبة جارية فوق 1.5 مريحة، تحت 1 إشارة ضغط سيولة. للمصارف إن غاب الحقل: NOT FOUND.",
)
def current_ratio(data: MarketData, spec):
    cr = info_number(data.info, "currentRatio")
    qr = info_number(data.info, "quickRatio")
    if cr is None and qr is None:
        return nf(spec, "لا نسبة جارية ولا سريعة (شائع في المصارف).", src_info(data, "currentRatio"))
    bits = []
    base = cr if cr is not None else qr
    if cr is not None:
        bits.append(f"الجارية {fmt(cr, 2)}")
    if qr is not None:
        bits.append(f"السريعة {fmt(qr, 2)}")
    if base >= 1.5:
        sig, conf = 0.5, 0.6
    elif base >= 1.0:
        sig, conf = 0.15, 0.45
    else:
        sig, conf = -0.55, 0.7
    return ok(spec, sig, conf, "نسب السيولة: " + "، ".join(bits) + ".", src_info(data, "currentRatio/quickRatio"))


@register(
    "payout-sustainability",
    "وكيل استدامة التوزيعات",
    "Payout Sustainability",
    "fundamental",
    "fundamental",
    "payout-sustainability.md",
    0.95,
    "تقييم نسبة التوزيع من الأرباح مع العائد.",
    "info.payoutRatio و عائد التوزيع إن وجد.",
    "توزيع بين 30% و70% مع عائد معقول مستدام غالباً. فوق 100% (توزيع أعلى من الربح) إشارة حذر. إن غاب payout: NOT FOUND.",
)
def payout_sustainability(data: MarketData, spec):
    p = info_number(data.info, "payoutRatio")
    if p is None:
        return nf(spec, "لا نسبة توزيع (payoutRatio) في المصدر.", src_info(data, "payoutRatio"))
    # already a fraction in the probe (0.72)
    frac = p / 100.0 if p > 1.5 else p
    y = normalize_yield(info_number(data.info, "dividendYield", "trailingAnnualDividendYield"))
    if frac < 0:
        return nf(spec, "نسبة توزيع سالبة لا تُفسر هنا.", src_info(data, "payoutRatio"))
    if frac > 1.0:
        sig, conf = -0.5, 0.7
        txt = f"نسبة التوزيع {fmt_pct(frac)} تتجاوز الأرباح"
    elif frac >= 0.3 and frac <= 0.7:
        sig, conf = 0.45, 0.65
        txt = f"نسبة التوزيع {fmt_pct(frac)} ضمن نطاق مستدام عادة"
    elif frac < 0.3:
        sig, conf = 0.2, 0.5
        txt = f"نسبة التوزيع منخفضة {fmt_pct(frac)} (سعة للإبقاء أو الرفع، دون توقع)"
    else:
        sig, conf = -0.15, 0.5
        txt = f"نسبة التوزيع مرتفعة {fmt_pct(frac)}"
    if y:
        txt += f" مع عائد {fmt_pct(y)}"
    return ok(spec, sig, conf, txt + ".", src_info(data, "payoutRatio"))
