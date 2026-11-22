"""The 13 added analysts (Saudi market, quality, regime, correlation, auditor)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from .accuracy import (
    ACCURACY_MIN_DECISIONS,
    ACCURACY_MIN_PER_AGENT,
    append_learning,
    load_accuracy,
    parse_decisions,
    score_rec,
    subsequent_return,
    weight_factors_from_accuracy,
    write_accuracy,
)
from .analysts_common import fmt, fmt_pct, ind, need_bars, nf, ok, register, src_hist, src_info
from .fetch import info_number, normalize_yield
from .models import MarketData
from .sources import calendar_context
from .universe import (
    DCF_GROWTH_CAP,
    EQUITY_RISK_PREMIUM,
    OSCILLATOR_AGENT_IDS,
    REGIME_WEIGHTS,
    TREND_AGENT_IDS,
    is_bank,
    is_petrochem,
)


def _row(df: Optional[pd.DataFrame], names: list[str]):
    if df is None or df.empty:
        return None, None
    lower = {str(i).lower(): i for i in df.index}
    for n in names:
        if n.lower() in lower:
            row = df.loc[lower[n.lower()]].dropna()
            if len(row):
                return str(lower[n.lower()]), row
    return None, None


def _to_date(val) -> Optional[date]:
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, (int, float)) and val > 10_000:
        try:
            return datetime.fromtimestamp(val, tz=timezone.utc).date()
        except Exception:
            try:
                return datetime.fromtimestamp(int(val), tz=timezone.utc).date()
            except Exception:
                return None
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val[:10]).date()
        except Exception:
            return None
    if isinstance(val, (list, tuple)) and val:
        return _to_date(val[0])
    # pandas timestamp
    try:
        return pd.Timestamp(val).date()
    except Exception:
        return None


def _asof(data: MarketData) -> date:
    try:
        return date.fromisoformat(data.last_bar_date)
    except Exception:
        return date.today()


# ── 1. official announcements ──────────────────────────────────────────────
@register(
    "tadawul-announcements",
    "وكيل إعلانات تداول",
    "Tadawul Official Announcements",
    "saudi-market",
    "saudi-market",
    "tadawul-announcements.md",
    1.15,
    "قراءة الإفصاحات الرسمية (نتائج، توزيعات، تغيير رأس المال) من السوق المالية أو أرقام إن توفرت.",
    "محاولة جلب saudiexchange.sa أو argaam.com عبر engine/sources.py. لا تُستخدم أخبار Yahoo بديلاً عن الإفصاح الرسمي.",
    "إن فُسِّر إفصاح حديث (نتائج/توزيع/رأس مال) تُسجَّل إشارة محدودة حسب طبيعة الخبر. إن حُجب المصدر أو تعذر التحليل: NOT FOUND دون تخمين.",
)
def tadawul_announcements(data: MarketData, spec):
    payload = data.announcements
    src = "saudiexchange.sa / argaam.com"
    if not payload or not payload.get("items"):
        err = (payload or {}).get("error") or "لا استجابة قابلة للتحليل"
        return nf(spec, f"تعذر جلب الإفصاحات الرسمية. {err}", src)
    items = payload["items"]
    n = len(items) if isinstance(items, list) else 1
    return ok(
        spec,
        0.0,
        0.4,
        f"تم جلب {n} إفصاحاً من المصدر الرسمي وسيُحلَّل نصّها في نسخة لاحقة إن توفرت الحقول.",
        payload.get("source") or src,
    )


# ── 2. foreign ownership ───────────────────────────────────────────────────
@register(
    "foreign-ownership",
    "وكيل ملكية الأجانب",
    "Foreign Ownership",
    "saudi-market",
    "saudi-market",
    "foreign-ownership.md",
    1.15,
    "متابعة نسبة تملك الأجانب وتغيرها اليومي كما تنشرها تداول.",
    "محاولة جلب نسب الملكية من saudiexchange.sa.",
    "ارتفاع صافي تملك الأجانب إشارة موجبة محدودة، والانخفاض سالبة. إن تعذر الجلب: NOT FOUND.",
)
def foreign_ownership(data: MarketData, spec):
    payload = data.foreign_ownership
    src = "saudiexchange.sa foreign ownership"
    if not payload or not payload.get("data"):
        err = (payload or {}).get("error") or "لا بيانات"
        return nf(spec, f"نسب ملكية الأجانب غير متاحة. {err}", src)
    return ok(spec, 0.0, 0.4, "توفرت بيانات ملكية أجانب وستُقرأ النسبة والتغير منها.", src)


# ── 3. investor flows ──────────────────────────────────────────────────────
@register(
    "investor-flows",
    "وكيل صافي تدفقات المستثمرين",
    "Investor Flows",
    "saudi-market",
    "saudi-market",
    "investor-flows.md",
    1.1,
    "قراءة صافي شراء المؤسسات مقابل الأفراد والمحلي مقابل الأجنبي من التقارير الأسبوعية لتداول.",
    "تقارير التداول الأسبوعية عبر saudiexchange.sa (engine/sources.try_investor_flows).",
    "صافي مؤسسي/أجنبي موجب يميل للشراء والعكس للبيع. إن تعذر الجلب: NOT FOUND.",
)
def investor_flows(data: MarketData, spec):
    payload = data.investor_flows
    src = "saudiexchange.sa weekly trading reports"
    if not payload or not payload.get("data"):
        err = (payload or {}).get("error") or "لا بيانات"
        return nf(spec, f"تقارير التدفقات الأسبوعية غير متاحة. {err}", src)
    return ok(spec, 0.0, 0.4, "توفرت بيانات تدفقات وستُحسب منها صافي المؤسسات/الأجانب.", src)


# ── 4. seasonality calendar ────────────────────────────────────────────────
@register(
    "seasonality-calendar",
    "وكيل المواسم والتقويم",
    "Seasonality / Calendar",
    "saudi-market",
    "saudi-market",
    "seasonality-calendar.md",
    0.9,
    "مراعاة رمضان والعطل الرسمية وتواريخ استحقاق التوزيع، وذكر نافذة مراجعة MSCI/FTSE دون تأكيد بيان غير موجود.",
    "تقويم أم القرى عبر مكتبة hijridate، عطل 22 فبراير و23 سبتمبر، وتاريخ الإكس من Yahoo Finance calendar/dividends.",
    "قرب الإكس يخفض إشارة الشراء قليلاً (فجوة التوزيع المحتملة). رمضان أو عطلة خلال 14 يوماً إشارة حذر/سيولة محدودة. إن لم يوجد أي حدث قريب: تُذكر الحالة كحياد بثقة منخفضة لا تخمين أثر موسمي.",
)
def seasonality_calendar(data: MarketData, spec):
    asof = _asof(data)
    ex = None
    cal = data.calendar or {}
    if cal.get("Ex-Dividend Date"):
        ex = _to_date(cal.get("Ex-Dividend Date"))
    if ex is None and data.dividends is not None and len(data.dividends):
        last = data.dividends.index[-1]
        try:
            ex_last = pd.Timestamp(last).tz_convert("Asia/Riyadh").date() if getattr(last, "tzinfo", None) else pd.Timestamp(last).date()
            # last paid ex is historical; only use if in the future or last 7 days
            if (ex_last - asof).days >= -7:
                ex = ex_last
        except Exception:
            pass
    ctx = calendar_context(asof, ex)
    events = ctx["events"]
    sig, conf = 0.0, 0.35
    if ctx["in_ramadan"]:
        sig -= 0.15
        conf = 0.45
    if ctx.get("days_to_ramadan") is not None and ctx["days_to_ramadan"] <= 14:
        sig -= 0.1
        conf = max(conf, 0.4)
    if ctx.get("days_to_ex") is not None and 0 <= ctx["days_to_ex"] <= 7:
        # approaching ex-div: long holders may see a drop ≈ dividend; mild caution
        sig -= 0.2
        conf = 0.55
        if data.info.get("lastDividendValue") and data.price:
            dps = float(data.info["lastDividendValue"])
            events.append(f"آخر توزيع معلن {fmt(dps)} ر.س للسهم (حوالي {fmt_pct(dps/data.price)} من السعر)")
    if not events:
        return ok(
            spec,
            0.0,
            0.3,
            f"لا رمضان ولا عطلة رسمية ولا إكس قريب من تاريخ الإغلاق {asof}. المصدر: {ctx['source']}.",
            ctx["source"],
        )
    return ok(spec, sig, conf, "؛ ".join(events) + f". المصدر: {ctx['source']}.", ctx["source"])


# ── 5. earnings surprise ───────────────────────────────────────────────────
@register(
    "earnings-surprise",
    "وكيل مفاجآت الأرباح",
    "Earnings Surprise",
    "fundamental",
    "fundamental",
    "earnings-surprise.md",
    1.2,
    "مقارنة الربح الفعلي بتقديرات المحللين ورصد ردّ فعل السعر بعد تاريخ الإعلان.",
    "Yahoo Finance earnings_dates / earnings_history وسلسلة الإغلاق.",
    "مفاجأة موجبة + رد فعل سعري صاعد بعد الإعلان = شراء. مفاجأة سالبة أو رد فعل معاكس = حذر/بيع. إن غاب الفعلي والتقدير: NOT FOUND.",
)
def earnings_surprise(data: MarketData, spec):
    df = data.earnings_dates
    hist = data.earnings_history
    surprise = None
    reported = None
    estimate = None
    edate = None
    source = "Yahoo Finance / earnings_dates"
    if df is not None and not df.empty:
        # rows with reported EPS
        col_rep = "Reported EPS" if "Reported EPS" in df.columns else None
        col_est = "EPS Estimate" if "EPS Estimate" in df.columns else None
        col_sur = "Surprise(%)" if "Surprise(%)" in df.columns else None
        if col_rep:
            have = df[df[col_rep].notna()]
            if len(have):
                row = have.iloc[0] if have.index[-1] else have.iloc[-1]
                # most recent reported: last index that has a report, but df is usually newest first
                row = have.iloc[0]
                reported = float(row[col_rep])
                estimate = float(row[col_est]) if col_est and pd.notna(row.get(col_est)) else None
                if col_sur and pd.notna(row.get(col_sur)):
                    surprise = float(row[col_sur]) / 100.0  # 13.49 → 0.1349
                elif estimate not in (None, 0):
                    surprise = reported / estimate - 1.0
                try:
                    edate = pd.Timestamp(have.index[0]).tz_convert("Asia/Riyadh").date() if getattr(have.index[0], "tzinfo", None) or (getattr(have.index, "tz", None) is not None) else pd.Timestamp(have.index[0]).date()
                except Exception:
                    edate = _to_date(have.index[0])
    if surprise is None and hist is not None and not hist.empty:
        source = "Yahoo Finance / earnings_history"
        # last row with epsActual
        if "epsActual" in hist.columns:
            have = hist[hist["epsActual"].notna()]
            if len(have):
                row = have.iloc[-1]
                reported = float(row["epsActual"])
                if "epsEstimate" in have.columns and pd.notna(row.get("epsEstimate")):
                    estimate = float(row["epsEstimate"])
                if "surprisePercent" in have.columns and pd.notna(row.get("surprisePercent")):
                    surprise = float(row["surprisePercent"])
                    # history is already a fraction (0.1349)
                    if abs(surprise) > 2:
                        surprise = surprise / 100.0
                elif estimate not in (None, 0):
                    surprise = reported / estimate - 1.0
                edate = _to_date(have.index[-1])
    if surprise is None:
        return nf(spec, "لا مفاجأة أرباح (فعلي مقابل تقدير) في earnings_dates ولا earnings_history.", source)
    bits = [f"المفاجأة {fmt_pct(surprise)}"]
    if reported is not None:
        bits.append(f"الفعلي {fmt(reported, 3)}")
    if estimate is not None:
        bits.append(f"التقدير {fmt(estimate, 3)}")
    if edate:
        bits.append(f"تاريخ الإعلان {edate}")
    sig = max(-1.0, min(1.0, surprise / 0.10))
    conf = 0.55 + 0.2 * min(1.0, abs(surprise) / 0.10)
    # post-earnings reaction if we have the date and subsequent bars
    if edate is not None and data.hist is not None:
        idx = data.hist.index
        try:
            dates = idx.tz_convert("Asia/Riyadh").strftime("%Y-%m-%d") if getattr(idx, "tz", None) is not None else pd.DatetimeIndex(idx).strftime("%Y-%m-%d")
        except Exception:
            dates = [str(x)[:10] for x in idx]
        after = [i for i, d in enumerate(dates) if d >= str(edate)]
        # price on/after earnings vs previous close
        if after:
            i0 = after[0]
            prev = float(data.hist["Close"].iloc[i0 - 1]) if i0 > 0 else None
            # reaction window: up to 5 sessions after
            i1 = min(after[0] + 5, len(data.hist) - 1)
            px = float(data.hist["Close"].iloc[i1])
            if prev:
                react = px / prev - 1.0
                bits.append(f"رد فعل حتى 5 جلسات {fmt_pct(react)}")
                sig = 0.6 * sig + 0.4 * max(-1, min(1, react / 0.05))
                conf = min(0.8, conf + 0.1)
    return ok(spec, sig, conf, "؛ ".join(bits) + ".", source)


# ── 6. earnings quality ────────────────────────────────────────────────────
@register(
    "earnings-quality",
    "وكيل جودة الأرباح",
    "Earnings Quality",
    "fundamental",
    "fundamental",
    "earnings-quality.md",
    1.15,
    "فحص ما إذا كانت الأرباح مدعومة بتدفق تشغيلي، وقياس المستحقات والبنود غير المتكررة.",
    "قوائم Yahoo: Net Income و Operating Cash Flow و Total Unusual Items / Impairment إن وُجدت.",
    "OCF أعلى من صافي الربح جودة أعلى. مستحقات كبيرة (NI-OCF) أو بنود غير اعتيادية كبيرة نسبة إلى الربح تخفض الجودة. للمصارف OCF مضلّل غالباً فيُعتمد على البنود غير المتكررة بثقة أقل أو NOT FOUND إن غابت.",
)
def earnings_quality(data: MarketData, spec):
    bank = is_bank(data.sector, data.industry)
    cf = data.quarterly_cashflow if data.quarterly_cashflow is not None else data.cashflow
    inc = data.quarterly_financials if data.quarterly_financials is not None else data.financials
    ni_name, ni_row = _row(inc, ["Net Income", "Net Income Common Stockholders"])
    ocf_name, ocf_row = _row(cf, ["Operating Cash Flow"])
    un_name, un_row = _row(inc, ["Total Unusual Items", "Total Unusual Items Excluding Goodwill"])
    if bank:
        # do not use NI-OCF as quality for banks
        if un_row is None or ni_row is None:
            return nf(
                spec,
                "للمصارف لا يُستخدم التدفق التشغيلي مقابل الربح (يتأثر بدفتر القروض). ولا بنود غير متكررة معلنة للمقارنة.",
                "Yahoo Finance / financials + ملاحظة مصرفية",
            )
        ni = float(ni_row.iloc[0])
        unusual = float(un_row.iloc[0])
        if ni == 0:
            return nf(spec, "صافي ربح صفري لا يصلح لنسبة البنود غير المتكررة.", "Yahoo Finance / financials")
        ratio = unusual / ni
        sig = -max(-1, min(1, abs(ratio) / 0.25)) * (1 if unusual < 0 else 0.7)
        # unusual negative for Aramco-like impairments reduces quality
        if abs(ratio) < 0.05:
            sig, conf, txt = 0.25, 0.45, "بنود غير متكررة ضئيلة"
        elif abs(ratio) < 0.15:
            sig, conf, txt = -0.15, 0.5, "بنود غير متكررة ملحوظة"
        else:
            sig, conf, txt = -0.5, 0.6, "بنود غير متكررة كبيرة نسبة إلى الربح"
        return ok(
            spec,
            sig,
            conf,
            f"قراءة مصرفية (بدون OCF): {txt} ({un_name}={fmt(unusual/1e9, 2)} مليار مقابل صافي {fmt(ni/1e9, 2)} أي {fmt_pct(ratio)}).",
            f"Yahoo Finance / financials[{un_name}]",
        )
    if ni_row is None or ocf_row is None:
        return nf(spec, "لا صافي ربح أو تدفق تشغيلي في القوائم لمقارنة الجودة.", "Yahoo Finance / cashflow+financials")
    ni = float(ni_row.iloc[0])
    ocf = float(ocf_row.iloc[0])
    bits = [f"التدفق التشغيلي {fmt(ocf/1e9, 2)} مليار", f"صافي الربح {fmt(ni/1e9, 2)} مليار"]
    if ni <= 0 and ocf > 0:
        sig, conf, txt = 0.2, 0.45, "ربح سالب مقابل تدفق تشغيلي موجب"
    elif ni <= 0 and ocf <= 0:
        sig, conf, txt = -0.55, 0.6, "ربح وتدفق تشغيلي غير موجبين"
    else:
        cover = ocf / ni
        bits.append(f"تغطية OCF/NI={fmt(cover, 2)}")
        accr = (ni - ocf) / abs(ni)
        bits.append(f"مستحقات نسبية {fmt_pct(accr)}")
        if cover >= 1.1:
            sig, conf, txt = 0.55, 0.7, "التدفق يدعم الأرباح"
        elif cover >= 0.8:
            sig, conf, txt = 0.15, 0.5, "تغطية مقبولة"
        else:
            sig, conf, txt = -0.45, 0.65, "الأرباح أعلى من التدفق (مستحقات مرتفعة)"
    if un_row is not None and ni:
        unusual = float(un_row.iloc[0])
        bits.append(f"بنود غير اعتيادية {fmt(unusual/1e9, 2)} مليار")
        if abs(unusual) > 0.15 * abs(ni):
            sig -= 0.2
            txt += " مع بنود غير متكررة مؤثرة"
    return ok(spec, max(-1, min(1, sig)), conf, f"{txt}؛ " + "، ".join(bits) + ".", "Yahoo Finance / cashflow+financials")


# ── 7. bank specialist ─────────────────────────────────────────────────────
@register(
    "bank-specialist",
    "الوكيل المصرفي المتخصص",
    "Bank Specialist",
    "fundamental",
    "fundamental",
    "bank-specialist.md",
    1.25,
    "مؤشرات مصرفية: نمو القروض، المخصصات إلى القروض، وهامش الفائدة وكفاية رأس المال ونسبة التعثر إن وُجدت.",
    "Yahoo Finance: Net Loan في الميزانية، Provisionand Write Offof Assets، وصافي دخل الفائدة إن وُجد. CAR و NPL غالباً غير متاحين على Yahoo.",
    "لغير المصارف: NOT FOUND فوراً. للمصارف يُسجَّل ما يتوفر فقط (مثلاً نمو القروض) مع إعلان NOT FOUND صريح لأي مؤشر غائب داخل السبب، بدون اختراع NIM/NPL/CAR.",
)
def bank_specialist(data: MarketData, spec):
    if not is_bank(data.sector, data.industry):
        return nf(spec, f"ليس مصرفاً (قطاع {data.sector or 'غير محدد'} / {data.industry or 'غير محدد'}).", "تصنيف Yahoo sector/industry")
    bs = data.quarterly_balance_sheet if data.quarterly_balance_sheet is not None else data.balance_sheet
    cf = data.quarterly_cashflow if data.quarterly_cashflow is not None else data.cashflow
    inc = data.quarterly_financials if data.quarterly_financials is not None else data.financials
    missing = []
    bits = []
    sigs = []
    # loans
    _, loan_row = _row(bs, ["Net Loan"])
    if loan_row is None or len(loan_row) < 2:
        missing.append("نمو القروض")
    else:
        a, b = float(loan_row.iloc[0]), float(loan_row.iloc[1])
        if b:
            g = a / b - 1.0
            bits.append(f"نمو صافي القروض {fmt_pct(g)} ({fmt(b/1e9, 1)}→{fmt(a/1e9, 1)} مليار)")
            sigs.append(max(-1, min(1, g / 0.08)))
        else:
            missing.append("نمو القروض")
    # deposits — often missing on Yahoo
    _, dep_row = _row(bs, ["Total Deposits", "Customer Deposits", "Deposits"])
    if dep_row is None or len(dep_row) < 2:
        missing.append("الودائع (لا صف ودائع في المصدر)")
    else:
        a, b = float(dep_row.iloc[0]), float(dep_row.iloc[1])
        if b:
            g = a / b - 1.0
            bits.append(f"نمو الودائع {fmt_pct(g)}")
            sigs.append(max(-1, min(1, g / 0.08)))
    # NIM
    _, nii = _row(inc, ["Net Interest Income"])
    _, ii = _row(inc, ["Interest Income", "Operating Revenue", "Total Revenue"])
    if nii is None or ii is None:
        missing.append("هامش الفائدة الصافي NIM")
    else:
        # For Islamic banks Yahoo may lack NII; if both exist:
        rev = float(ii.iloc[0])
        if rev:
            nim = float(nii.iloc[0]) / rev
            bits.append(f"تقريب NIM (صافي الفائدة/الإيراد) {fmt_pct(nim)}")
            sigs.append(max(-1, min(1, (nim - 0.5) / 0.3)))  # weak proxy, low weight later
    # NPL — almost never on Yahoo
    _, npl = _row(bs, ["Non Performing Loans", "Npl", "Nonperforming"])
    if npl is None:
        missing.append("نسبة القروض المتعثرة NPL")
    # CAR
    missing.append("كفاية رأس المال CAR") if True else None
    # provision / loans
    _, prov = _row(cf, ["Provisionand Write Offof Assets"])
    if loan_row is not None and prov is not None and float(loan_row.iloc[0]):
        pr = float(prov.iloc[0]) / float(loan_row.iloc[0])
        bits.append(f"المخصصات/صافي القروض {fmt_pct(pr, 2)} (ليست نسبة تعثر)")
        sigs.append(max(-1, min(1, (0.005 - pr) / 0.005)))
    else:
        missing.append("المخصصات إلى القروض")
    if not bits:
        return nf(spec, "لا مؤشرات مصرفية قابلة للحساب. الغائب: " + "، ".join(missing) + ".", "Yahoo Finance / statements")
    sig = sum(sigs) / len(sigs)
    conf = 0.35 + 0.1 * len(sigs)
    txt = "؛ ".join(bits)
    if missing:
        txt += " — غير متاح: " + "، ".join(missing)
    return ok(spec, sig, min(0.65, conf), txt + ".", "Yahoo Finance / balance_sheet+cashflow")


# ── 8. petrochem spreads ───────────────────────────────────────────────────
@register(
    "petrochem-spreads",
    "وكيل فروقات البتروكيماويات",
    "Petrochemical Spreads",
    "sector-macro",
    "sector-macro",
    "petrochem-spreads.md",
    1.15,
    "متابعة فروقات أسعار المنتجات مقابل اللقيم للشركات البتروكيماوية فقط.",
    "محاولة جلب أسعار منتجات/لقيم من مصدر سلعي مجاني (ليس أسعار أسهم شركات أجنبية بديلة).",
    "لغير البتروكيماويات: NOT FOUND. إن لم يتوفر فرق منتج-لقيم حقيقي: NOT FOUND (لا يُستخدم برنت وحده كبديل عن الفرق).",
)
def petrochem_spreads(data: MarketData, spec):
    if not is_petrochem(data.ticker, data.sector, data.industry):
        return nf(
            spec,
            f"ليست شركة بتروكيماويات/أسمدة في قائمة MEMORY.md (قطاع {data.industry or data.sector or 'غير محدد'}).",
            "MEMORY.md / universe.PETROCHEM_TICKERS",
        )
    payload = data.petrochem or {}
    if not payload.get("data"):
        err = payload.get("error") or "لا مصدر"
        return nf(spec, f"لا فرق منتج/لقيم مجاني موثوق. {err}", payload.get("source") or "commodity sources")
    return ok(spec, 0.0, 0.4, "توفرت أسعار منتجات/لقيم وستُحسب منها الفروقات.", payload.get("source"))


# ── 9. fair value DCF ──────────────────────────────────────────────────────
@register(
    "fair-value-dcf",
    "وكيل القيمة العادلة (خصم تدفقات/توزيعات)",
    "Fair Value DCF / DDM",
    "fundamental",
    "fundamental",
    "fair-value-dcf.md",
    1.15,
    "تقدير قيمة مبسّط بنموذج جوردون للتدفق الحر أو التوزيعات ومقارنته بالسعر.",
    "FCF أو التوزيعات وعدد الأسهم ونمو الإيرادات/الأرباح من Yahoo. معدل الخصم = معدل ساما المجلوب + علاوة 5% الموثّقة في MEMORY.md، أو وسيط عائد الربحية لأسهم قائمة المراقبة المجلوبة في الجلسة. سقف النمو المستدام 5%.",
    "إن غاب التدفق والتوزيع، أو غاب معدل خصم حي: NOT FOUND. لا يُستخدم 8% افتراضي مخمّن. يُذكر كل افتراض في السبب.",
)
def fair_value_dcf(data: MarketData, spec):
    fcf = info_number(data.info, "freeCashflow")
    if fcf is None and data.cashflow is not None:
        _, row = _row(data.cashflow, ["Free Cash Flow"])
        if row is not None:
            fcf = float(row.iloc[0])
    shares = info_number(data.info, "sharesOutstanding")
    dps = None
    if data.info.get("lastDividendValue") is not None:
        # last dividend may be quarterly; annualise only if we have 4 payments in last 365d
        dps = None
        if data.dividends is not None and len(data.dividends) >= 1:
            s = data.dividends.copy()
            try:
                if getattr(s.index, "tz", None) is not None:
                    s.index = s.index.tz_convert("Asia/Riyadh")
                cutoff = s.index[-1] - pd.Timedelta(days=365)
                annual = float(s[s.index >= cutoff].sum())
                if annual > 0:
                    dps = annual
            except Exception:
                dps = normalize_yield(info_number(data.info, "trailingAnnualDividendYield"))
                if dps is not None and data.price:
                    dps = dps * data.price
        else:
            y = normalize_yield(info_number(data.info, "trailingAnnualDividendYield", "dividendYield"))
            if y and data.price:
                dps = y * data.price
    # discount rate
    r = None
    r_src = ""
    if data.sama and data.sama.get("value") is not None:
        val = float(data.sama["value"])
        rf = val / 100.0 if val > 1 else val
        if 0 < rf < 0.25:
            r = rf + EQUITY_RISK_PREMIUM
            r_src = f"ساما {fmt_pct(rf)} + علاوة MEMORY.md {fmt_pct(EQUITY_RISK_PREMIUM)}"
    if r is None:
        pes = [v for v in (data.watchlist_pe or {}).values() if v and v > 0]
        if len(pes) >= 5:
            med_ey = float(np.median([1.0 / p for p in pes]))
            r = med_ey
            r_src = f"وسيط عائد الربحية لـ {len(pes)} أسهماً من قائمة المراقبة المجلوبة ({fmt_pct(med_ey)})"
    if r is None:
        return nf(
            spec,
            "لا معدل خصم حي: معدل ساما غير متاح، ووسيط عائد الربحية لقائمة المراقبة غير كافٍ (يلزم 5 مكررات على الأقل).",
            "fetch.try_sama_rates + watchlist trailingPE",
        )
    g_raw = info_number(data.info, "revenueGrowth")
    if g_raw is None:
        g_raw = info_number(data.info, "earningsGrowth")
    if g_raw is None:
        g = 0.0
        g_note = "نمو مستدام 0% (لا رقم نمو معلن؛ أبدية بلا نمو)"
    else:
        g = min(DCF_GROWTH_CAP, max(0.0, float(g_raw)))
        g_note = f"نمو مستدام {fmt_pct(g)} (سقف MEMORY.md {fmt_pct(DCF_GROWTH_CAP)} من نمو معلن {fmt_pct(g_raw)})"
    if r <= g + 0.01:
        return nf(spec, f"معدل الخصم {fmt_pct(r)} لا يتجاوز النمو {fmt_pct(g)} بهامش كافٍ؛ لا يُفرض رقم بديل.", r_src)
    # choose cash to owners
    per = None
    model = ""
    if fcf is not None and fcf > 0 and shares:
        per = (fcf / shares) * (1 + g)
        model = "جوردون للتدفق الحر"
        src = "Yahoo Finance / freeCashflow + sharesOutstanding"
    elif dps is not None and dps > 0:
        per = dps * (1 + g)
        model = "خصم التوزيعات (جوردون)"
        src = "Yahoo Finance / dividends"
    else:
        return nf(spec, "لا تدفق نقدي حر موجب ولا توزيع سنوي معلوم لبناء النموذج.", "Yahoo Finance / cashflow+dividends")
    fv = per / (r - g)
    if not data.price:
        return nf(spec, "لا سعر لمقارنة القيمة العادلة.", src_hist(data))
    gap = fv / data.price - 1.0
    sig = max(-1, min(1, gap / 0.25))
    conf = 0.45  # assumptions are coarse
    return ok(
        spec,
        sig,
        conf,
        f"{model}: قيمة تقديرية {fmt(fv)} ر.س مقابل سعر {fmt(data.price)} (فرق {fmt_pct(gap)}). الخصم {fmt_pct(r)} من {r_src}؛ {g_note}. النموذج حسّاس للافتراضات.",
        src + " + MEMORY.md",
    )


# ── 10. multi-timeframe ────────────────────────────────────────────────────
@register(
    "multi-timeframe",
    "وكيل الأطر الزمنية المتعددة",
    "Multi-Timeframe Alignment",
    "technical",
    "technical",
    "multi-timeframe.md",
    1.1,
    "التحقق من توافق الاتجاه على اليومي والأسبوعي والشهري.",
    "إعادة عيّنة سلسلة Yahoo اليومية إلى أسبوعي/شهري. الاتجاه: الإغلاق مقابل SMA50 (يومي) وSMA20 (أسبوعي/شهري إن كفى التاريخ) وميل المتوسط.",
    "3/3 صاعد = إشارة قوية، 2/3 معتدلة، تضارب يخفض الثقة. إن نقص التاريخ للشهري يُعلن ذلك ويُستخدم المتاح فقط إن وُجد إطاران على الأقل، وإلا NOT FOUND.",
)
def multi_timeframe(data: MarketData, spec):
    if not need_bars(data, 60):
        return nf(spec, "التاريخ اليومي أقصر من 60 شمعة.", src_hist(data))
    h = data.hist.copy()
    close = h["Close"]

    def _trend(series: pd.Series, sma_n: int) -> Optional[int]:
        s = series.dropna()
        if len(s) < sma_n + 5:
            return None
        ma = s.rolling(sma_n, min_periods=sma_n).mean().dropna()
        if len(ma) < 3:
            return None
        px, m, mprev = float(s.iloc[-1]), float(ma.iloc[-1]), float(ma.iloc[-3])
        up = px > m and m >= mprev
        down = px < m and m <= mprev
        if up:
            return 1
        if down:
            return -1
        return 1 if px > m else -1

    d = _trend(close, 50)
    # weekly / monthly last close
    try:
        c = close.copy()
        if getattr(c.index, "tz", None) is not None:
            c.index = c.index.tz_convert("Asia/Riyadh")
        w = c.resample("W").last().dropna()
        m = c.resample("ME").last().dropna()
    except Exception:
        w = m = None
    wt = _trend(w, 20) if w is not None else None
    mt = _trend(m, 10) if m is not None else None
    labels = []
    votes = []
    for name, v in (("يومي", d), ("أسبوعي", wt), ("شهري", mt)):
        if v is None:
            labels.append(f"{name}: غير كافٍ")
        else:
            labels.append(f"{name}: {'صاعد' if v>0 else 'هابط'}")
            votes.append(v)
    if len(votes) < 2:
        return nf(spec, "لا يكفي إطاران مكتملان للحكم. " + "؛ ".join(labels) + ".", src_hist(data))
    score = sum(votes) / len(votes)
    align = abs(sum(votes)) == len(votes)
    conf = 0.7 if (len(votes) == 3 and align) else (0.55 if align else 0.4)
    return ok(spec, score, conf, "توافق الأطر: " + "؛ ".join(labels) + ".", src_hist(data))


# ── 11. market regime (weight modifier) ────────────────────────────────────
@register(
    "market-regime",
    "وكيل حالة السوق (معدّل الأوزان)",
    "Market Regime (Weight Modifier)",
    "sector-macro",
    "sector-macro",
    "market-regime.md",
    0.8,
    "تصنيف السوق إلى صاعد/هابط/عرضي من وكيل KSA (أو تاسي إن اكتملت سلسلته) وتعديل أوزان الوكلاء وفق جدول MEMORY.md. الوكيل نفسه يصوّت ميلاً خفيفاً ولا يُعدَّل وزنه بجدوله.",
    "صندوق KSA: السعر مقابل متوسط 50 و200 يوم، وعائد 60 يوماً. مضاعفات الأوزان في universe.REGIME_WEIGHTS / MEMORY.md.",
    "صاعد: سعر فوق SMA200 وSMA50 فوق SMA200. هابط: العكس. غير ذلك عرضي. تُحفظ المضاعفات في data.regime_weight_factors وتُطبَّق في aggregate.weighted_score.",
    pass_order=0,
)
def market_regime(data: MarketData, spec):
    src = "Yahoo Finance / KSA ETF"
    series = None
    label = "KSA"
    if data.ksa_etf is not None and len(data.ksa_etf) >= 210:
        series = data.ksa_etf["Close"]
    elif data.tasi_hist is not None and len(data.tasi_hist) >= 210:
        series = data.tasi_hist["Close"]
        label = "^TASI.SR"
        src = "Yahoo Finance / ^TASI.SR"
    if series is None:
        # fallback: KSA shorter window or TASI spot only — cannot classify SMA200
        if data.ksa_etf is not None and len(data.ksa_etf) >= 60:
            series = data.ksa_etf["Close"]
        else:
            data.regime = None
            data.regime_weight_factors = {}
            return nf(spec, "لا سلسلة كافية (يلزم نحو 200 يوم) لتصنيف حالة السوق من KSA أو تاسي.", src)
    s = series.dropna()
    px = float(s.iloc[-1])
    sma50 = float(s.rolling(50).mean().iloc[-1]) if len(s) >= 50 else None
    sma200 = float(s.rolling(200).mean().iloc[-1]) if len(s) >= 200 else None
    r60 = float(s.iloc[-1] / s.iloc[-61] - 1) if len(s) > 60 else None
    if sma50 is None:
        data.regime = None
        data.regime_weight_factors = {}
        return nf(spec, "لا متوسط 50 يوماً لتصنيف الحالة.", src)
    if sma200 is not None and px > sma200 and sma50 > sma200:
        regime = "bull"
    elif sma200 is not None and px < sma200 and sma50 < sma200:
        regime = "bear"
    else:
        regime = "range"
    # if 60d is sharply against the SMA classification, prefer range
    if r60 is not None and regime == "bull" and r60 < -0.08:
        regime = "range"
    if r60 is not None and regime == "bear" and r60 > 0.08:
        regime = "range"
    factors = dict(REGIME_WEIGHTS[regime])
    data.regime = {
        "name": regime,
        "label": {"bull": "صاعد", "bear": "هابط", "range": "عرضي"}[regime],
        "proxy": label,
        "price": px,
        "sma50": sma50,
        "sma200": sma200,
        "r60": r60,
        "factors": factors,
    }
    # store per-agent factors for the vote (except this agent, auditor, committee)
    per = {}
    from .analysts_common import SPECS

    for aid, sp in SPECS.items():
        if aid in ("market-regime", "performance-auditor", "committee-judge") or sp.weight <= 0:
            per[aid] = 1.0
            continue
        if aid in TREND_AGENT_IDS:
            key = "trend"
        elif aid in OSCILLATOR_AGENT_IDS:
            key = "oscillator"
        elif sp.group == "fundamental":
            key = "fundamental"
        elif sp.group in ("sentiment",):
            key = "sentiment"
        elif sp.group == "risk":
            key = "risk"
        else:
            key = "other"
        per[aid] = factors[key]
    data.regime_weight_factors = per
    bits = [f"الحالة {data.regime['label']} عبر {label}", f"السعر {fmt(px, 2)}"]
    if sma50:
        bits.append(f"SMA50={fmt(sma50, 2)}")
    if sma200:
        bits.append(f"SMA200={fmt(sma200, 2)}")
    if r60 is not None:
        bits.append(f"60 يوماً {fmt_pct(r60)}")
    bits.append(
        f"مضاعفات الأوزان (MEMORY.md): اتجاه {factors['trend']}، تذبذب {factors['oscillator']}، أساسي {factors['fundamental']}، مخاطر {factors['risk']}"
    )
    sig = {"bull": 0.35, "bear": -0.35, "range": 0.0}[regime]
    return ok(spec, sig, 0.6, "؛ ".join(bits) + ".", src + " + MEMORY.md")


# ── 12. portfolio correlation ──────────────────────────────────────────────
@register(
    "portfolio-correlation",
    "وكيل ارتباط المحفظة",
    "Portfolio Correlation",
    "risk",
    "risk",
    "portfolio-correlation.md",
    0.85,
    "قياس ارتباط عوائد السهم بأسهم قائمة المراقبة ورصد التكدس (يُفيد خصوصاً في المسح).",
    "سلاسل الإغلاق لقائمة المراقبة المجلوبة في الجلسة (macro.watchlist_hist) وعوائد 60 يوماً.",
    "متوسط ارتباط فوق 0.7 أو ارتباط فوق 0.8 مع 3 نظراء أو أكثر = تكدس (إشارة حذر). تنويع أوضح إشارة أخف إيجابية. إن قلّ عدد السلاسل المشتركة عن 5: NOT FOUND.",
)
def portfolio_correlation(data: MarketData, spec):
    others = {k: v for k, v in (data.watchlist_hist or {}).items() if k != data.ticker and v is not None and len(v.dropna()) >= 60}
    if len(others) < 5:
        return nf(
            spec,
            f"سلاسل قائمة المراقبة المكتملة {len(others)} (يلزم 5 غير السهم نفسه).",
            "Yahoo Finance / watchlist history",
        )

    def _rets(s):
        x = s.dropna().pct_change().dropna()
        if getattr(x.index, "tz", None) is not None:
            x.index = x.index.tz_localize(None).normalize()
        else:
            x.index = x.index.normalize()
        return x.iloc[-80:] if len(x) > 80 else x

    base = _rets(data.hist["Close"])
    corrs = {}
    for tkr, s in others.items():
        r = _rets(s)
        j = base.to_frame("a").join(r.to_frame("b"), how="inner").dropna()
        if len(j) < 40:
            continue
        corrs[tkr] = float(j["a"].corr(j["b"]))
    if len(corrs) < 5:
        return nf(spec, "لا تداخل 40 يوماً مع 5 أسماء على الأقل.", "Yahoo Finance / watchlist history")
    vals = list(corrs.values())
    avg = float(np.mean(vals))
    high = sum(1 for v in vals if v >= 0.8)
    bits = [f"متوسط الارتباط مع {len(corrs)} اسماً من القائمة {fmt(avg, 2)}", f"عدد الارتباطات ≥0.80: {high}"]
    if avg >= 0.7 or high >= 3:
        sig, conf, txt = -0.45, 0.6, "تكدس مرتفع"
    elif avg >= 0.5:
        sig, conf, txt = -0.15, 0.45, "ارتباط متوسط"
    else:
        sig, conf, txt = 0.2, 0.45, "تنويع نسبي أفضل"
    # name the highest
    top = sorted(corrs.items(), key=lambda kv: -kv[1])[:3]
    bits.append("الأعلى: " + "، ".join(f"{k}={fmt(v, 2)}" for k, v in top))
    return ok(spec, sig, conf, f"{txt}؛ " + "؛ ".join(bits) + ".", "Yahoo Finance / watchlist history")


# ── 13. performance auditor ────────────────────────────────────────────────
@register(
    "performance-auditor",
    "مدقق الأداء",
    "Performance Auditor",
    "audit",
    "audit",
    "performance-auditor.md",
    0.7,
    "مراجعة توصيات decisions.md مقابل أسعار لاحقة، وحفظ الدقة في accuracy/agent-accuracy.md و json، وتعديل الأوزان فقط بعد عينة كافية، وتسجيل درس في LEARNINGS.md.",
    "decisions.md + سلسلة السعر الحالية. الأصوات التفصيلية تُحفظ لاحقاً في accuracy/votes-log.jsonl. لا تُختلق دقة من تاريخ قصير.",
    f"إن لم يوجد إغلاق بعد تاريخ التوصية: NOT FOUND مع توضيح. تعديل الوزن لكل وكيل يتطلب {ACCURACY_MIN_PER_AGENT} قياسات على الأقل من سجل الأصوات، وللجنة {ACCURACY_MIN_DECISIONS} توصيات مُقيَّمة.",
    pass_order=0,
)
def performance_auditor(data: MarketData, spec):
    decisions = parse_decisions()
    narrative = []
    scored = []
    for d in decisions:
        # Use this ticker's hist only for this ticker; skip others here (no silent guess).
        if d["ticker"] != data.ticker:
            continue
        nxt = subsequent_return(data.hist, d["date"], d["price"])
        if not nxt:
            narrative.append(
                f"{d['ticker']} في {d['date']} بسعر {fmt(d['price'])}: لا إغلاق لاحق بعد تاريخ التوصية "
                f"(آخر إغلاق في السلسلة {data.last_bar_date})."
            )
            continue
        hit = score_rec(d["rec"], nxt["return"])
        scored.append({**d, **nxt, "hit": hit})
        narrative.append(
            f"{d['ticker']} {d['rec']} في {d['date']} عند {fmt(d['price'])}: بعد {nxt['bars']} جلسة "
            f"إلى {fmt(nxt['last_price'])} في {nxt['last_date']} ({fmt_pct(nxt['return'])}) — "
            f"{'متوافق' if hit else 'غير متوافق'}."
        )
    # other tickers mentioned but not scored without their history
    other_n = sum(1 for d in decisions if d["ticker"] != data.ticker)
    if other_n:
        narrative.append(f"{other_n} توصية(ات) لرموز أخرى لم تُقيَّم في هذه الجلسة لأنها تحتاج سلسلة ذلك الرمز.")

    doc = load_accuracy()
    if scored:
        wins = sum(1 for s in scored if s["hit"])
        doc.setdefault("committee", {})
        # store per-ticker snapshot; do not invent a global hit rate mixing stale runs
        key = data.ticker
        doc["committee"][key] = {"n": len(scored), "wins": wins, "hit_rate": round(wins / len(scored), 3)}
        # overall only if we already have enough across keys — still just report, factors need min N
        all_n = sum(v.get("n", 0) for v in doc["committee"].values() if isinstance(v, dict) and "n" in v)
        if all_n >= ACCURACY_MIN_DECISIONS:
            # leave factors computation to weight_factors; committee factor not applied to analysts
            pass
    else:
        doc.setdefault("committee", {})

    factors = weight_factors_from_accuracy(doc)
    data.accuracy_weight_factors = factors
    write_accuracy(doc, narrative)
    if not scored:
        append_learning(
            "مدقق الأداء: لا إغلاق تداول لاحق بعد توصيات سجل decisions.md المتاحة لهذا الرمز في هذه الجلسة، "
            "لذلك لم تُحتسب دقة ولم تُعدَّل أوزان الوكلاء. المصدر: accuracy/agent-accuracy.md و decisions.md."
        )
        return nf(
            spec,
            "لا سعر لاحق لقياس دقة التوصيات السابقة على هذا الرمز (آخر إغلاق ما زال تاريخ التوصية أو أقدم). لم تُختلق دقة ولم تُغيَّر أوزان.",
            "decisions.md + Yahoo Finance / history",
        )
    wins = sum(1 for s in scored if s["hit"])
    rate = wins / len(scored)
    if len(scored) < ACCURACY_MIN_DECISIONS:
        append_learning(
            f"مدقق الأداء لـ {data.ticker}: توفرت {len(scored)} توصية مُقيَّمة (أقل من حد {ACCURACY_MIN_DECISIONS})، "
            f"نسبة التوافق {fmt_pct(rate)}. لا تعديل أوزان بعد. المصدر: accuracy/agent-accuracy.md."
        )
        return ok(
            spec,
            0.0,
            0.35,
            f"قُيِّمت {len(scored)} توصية سابقة على {data.ticker} بنسبة توافق {fmt_pct(rate)}، وهي دون حد تعديل الأوزان ({ACCURACY_MIN_DECISIONS}).",
            "decisions.md + Yahoo Finance / history + accuracy/agent-accuracy.md",
        )
    sig = max(-0.4, min(0.4, (rate - 0.5) * 0.8))
    return ok(
        spec,
        sig,
        0.5,
        f"دقة اللجنة على {data.ticker}: {wins}/{len(scored)} ({fmt_pct(rate)}). عوامل الوزن للوكلاء تُطبَّق فقط إن بلغ كل وكيل {ACCURACY_MIN_PER_AGENT} قياساً.",
        "decisions.md + accuracy/agent-accuracy.md",
    )
