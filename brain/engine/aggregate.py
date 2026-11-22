"""Run all analysts, weighted vote, debate, and final committee verdict."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .analysts_common import FUNCS, SPECS, fmt, fmt_pct
from .indicators import last_valid
from .models import AnalystResult, MarketData, Recommendation

# Import side-effects: register all agents.
from . import analysts_technical  # noqa: F401
from . import analysts_fundamental  # noqa: F401
from . import analysts_sentiment  # noqa: F401
from . import analysts_macro_liq_risk  # noqa: F401
from . import analysts_debate  # noqa: F401
from . import analysts_extended  # noqa: F401
from . import analysts_candles  # noqa: F401

RIYADH = ZoneInfo("Asia/Riyadh")

BUY_TH = 0.25
SELL_TH = -0.25


def _call(agent_id: str, data: MarketData, prior: list[AnalystResult] | None = None) -> AnalystResult:
    spec = SPECS[agent_id]
    fn = FUNCS[agent_id]
    try:
        # debate / committee accept prior results
        if spec.pass_order >= 2:
            return fn(data, spec, prior)
        return fn(data, spec)
    except Exception as exc:
        from .analysts_common import nf

        return nf(spec, f"خطأ أثناء الحساب: {type(exc).__name__}: {exc}", "engine")


def run_analysts(data: MarketData) -> list[AnalystResult]:
    results: list[AnalystResult] = []
    # pass 0: regime + performance auditor (set weight modifiers on data)
    for agent_id, spec in SPECS.items():
        if spec.pass_order == 0:
            results.append(_call(agent_id, data))
    # pass 1
    for agent_id, spec in SPECS.items():
        if spec.pass_order == 1:
            results.append(_call(agent_id, data))
    # pass 2 debate
    for agent_id, spec in SPECS.items():
        if spec.pass_order == 2:
            results.append(_call(agent_id, data, results))
    # pass 3 placeholder (verdict filled later)
    for agent_id, spec in SPECS.items():
        if spec.pass_order == 3:
            results.append(_call(agent_id, data, results))
    return results


def effective_weight(r: AnalystResult, data: MarketData | None = None) -> float:
    """Base weight × regime factor × accuracy factor. Documented in MEMORY.md / market-regime.md."""
    w = r.weight
    if data is None:
        return w
    if r.agent_id in ("market-regime", "performance-auditor", "committee-judge") or r.weight <= 0:
        return w
    w *= float((data.regime_weight_factors or {}).get(r.agent_id, 1.0))
    w *= float((data.accuracy_weight_factors or {}).get(r.agent_id, 1.0))
    return w


def weighted_score(results: list[AnalystResult], data: MarketData | None = None) -> tuple[float, int]:
    num = den = 0.0
    n = 0
    for r in results:
        if r.group == "committee" or r.weight <= 0:
            continue
        if not r.found or r.signal is None:
            continue
        w = effective_weight(r, data) * r.confidence
        num += (r.signal or 0.0) * w
        den += w
        n += 1
    if den == 0:
        return 0.0, n
    return num / den, n


def _verdict(score: float, n_found: int) -> tuple[str, str]:
    if n_found < 15:
        # too thin: only take a non-hold if score is decisive
        if score >= 0.40:
            return "شراء", "buy"
        if score <= -0.40:
            return "بيع", "sell"
        return "احتفاظ", "hold"
    if score >= BUY_TH:
        return "شراء", "buy"
    if score <= SELL_TH:
        return "بيع", "sell"
    return "احتفاظ", "hold"


def _levels(data: MarketData, rec_en: str) -> dict:
    atr = last_valid(data.indicators["atr14"]) if data.indicators.get("atr14") is not None else None
    if atr is None:
        atr = data.price * 0.02
    px = data.price
    lows = data.indicators.get("swings_lo") or []
    highs = data.indicators.get("swings_hi") or []
    support = max((p for _, p in lows if p < px), default=None)
    resist = min((p for _, p in highs if p > px), default=None)

    if rec_en == "buy":
        entry_low = max(px - 0.4 * atr, support if support else px - 0.5 * atr)
        if entry_low > px:
            entry_low = px - 0.2 * atr
        entry_high = px + 0.15 * atr
        mid = (entry_low + entry_high) / 2.0
        # Always at least 1.5 ATR; support may widen the stop up to 2.5 ATR, never tighten it.
        stop = mid - 1.5 * atr
        if support and support < mid:
            cand = support - 0.15 * atr
            if cand < stop:
                stop = max(cand, mid - 2.5 * atr)
        if stop >= mid:
            stop = mid - 1.5 * atr
        risk = mid - stop
        t1, t2, t3 = mid + 1.5 * risk, mid + 2.5 * risk, mid + 4.0 * risk
    elif rec_en == "sell":
        entry_high = min(px + 0.4 * atr, resist if resist else px + 0.5 * atr)
        if entry_high < px:
            entry_high = px + 0.2 * atr
        entry_low = px - 0.15 * atr
        mid = (entry_low + entry_high) / 2.0
        stop = mid + 1.5 * atr
        if resist and resist > mid:
            cand = resist + 0.15 * atr
            if cand > stop:
                stop = min(cand, mid + 2.5 * atr)
        if stop <= mid:
            stop = mid + 1.5 * atr
        risk = stop - mid
        t1, t2, t3 = mid - 1.5 * risk, mid - 2.5 * risk, mid - 4.0 * risk
        t1 = max(t1, 0.01)
        t2 = max(t2, 0.01)
        t3 = max(t3, 0.01)
    else:
        entry_low, entry_high = px - 0.25 * atr, px + 0.25 * atr
        mid = px
        stop = mid - 1.5 * atr
        risk = mid - stop
        t1, t2, t3 = mid + 1.5 * risk, mid + 2.5 * risk, mid + 4.0 * risk

    return {
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop": stop,
        "t1": t1,
        "t2": t2,
        "t3": t3,
        "risk": risk if risk > 0 else None,
        "atr": atr,
    }


def _top_reasons(results: list[AnalystResult], rec_en: str, k: int = 5) -> list[str]:
    found = [r for r in results if r.found and r.signal is not None and r.group != "committee"]
    if rec_en == "sell":
        picked = sorted(found, key=lambda r: (r.signal or 0) * r.confidence * r.weight)[:k]
    elif rec_en == "buy":
        picked = sorted(found, key=lambda r: (r.signal or 0) * r.confidence * r.weight, reverse=True)[:k]
    else:
        # strongest absolute
        picked = sorted(found, key=lambda r: abs((r.signal or 0) * r.confidence * r.weight), reverse=True)[:k]
    out = []
    for r in picked:
        out.append(f"{r.name_ar}: {r.reason_ar} (إشارة {fmt(r.signal or 0, 2)}، ثقة {fmt_pct(r.confidence)}، المصدر: {r.source})")
    return out


def _key_risks(results: list[AnalystResult], rec_en: str, k: int = 4) -> list[str]:
    found = [r for r in results if r.found and r.signal is not None]
    # risks: bearish items if buying, bullish if selling, plus risk-group always
    risks = []
    for r in found:
        if r.group == "risk":
            risks.append(r)
        elif rec_en == "buy" and (r.signal or 0) < -0.2:
            risks.append(r)
        elif rec_en == "sell" and (r.signal or 0) > 0.2:
            risks.append(r)
        elif rec_en == "hold" and abs(r.signal or 0) >= 0.45:
            risks.append(r)
    # unique by id, strongest first
    seen = set()
    ordered = []
    keyfn = (lambda r: abs((r.signal or 0) * r.confidence * max(r.weight, 0.3)))
    for r in sorted(risks, key=keyfn, reverse=True):
        if r.agent_id in seen:
            continue
        seen.add(r.agent_id)
        ordered.append(f"{r.name_ar}: {r.reason_ar} (المصدر: {r.source})")
        if len(ordered) >= k:
            break
    return ordered


def _dissenters(results: list[AnalystResult], rec_en: str) -> list[str]:
    found = [r for r in results if r.found and r.signal is not None and r.group not in ("committee",)]
    out = []
    for r in sorted(found, key=lambda r: (r.signal or 0) * r.confidence):
        sig = r.signal or 0
        if rec_en == "buy" and sig <= -0.2:
            out.append(f"{r.name_ar}: {r.reason_ar} (إشارة {fmt(sig, 2)}، المصدر: {r.source})")
        elif rec_en == "sell" and sig >= 0.2:
            out.append(f"{r.name_ar}: {r.reason_ar} (إشارة {fmt(sig, 2)}، المصدر: {r.source})")
        elif rec_en == "hold" and abs(sig) >= 0.55:
            side = "صاعد" if sig > 0 else "هابط"
            out.append(f"{r.name_ar} ({side}): {r.reason_ar} (إشارة {fmt(sig, 2)}، المصدر: {r.source})")
    return out[:8]


def _debate_summaries(results: list[AnalystResult]) -> tuple[str, str]:
    bull = next((r for r in results if r.agent_id == "bull-advocate"), None)
    bear = next((r for r in results if r.agent_id == "bear-advocate"), None)
    b = bull.reason_ar if bull and bull.found else "NOT FOUND — لا ملخص للثور."
    d = bear.reason_ar if bear and bear.found else "NOT FOUND — لا ملخص للدب."
    if bull and bull.found:
        b = f"{bull.reason_ar} (إشارة {fmt(bull.signal or 0, 2)}، ثقة {fmt_pct(bull.confidence)}، المصدر: {bull.source})"
    if bear and bear.found:
        d = f"{bear.reason_ar} (إشارة {fmt(bear.signal or 0, 2)}، ثقة {fmt_pct(bear.confidence)}، المصدر: {bear.source})"
    return b, d


def decide(data: MarketData, results: list[AnalystResult]) -> Recommendation:
    score, n_vote = weighted_score(results, data)
    n_found = sum(1 for r in results if r.found and r.group != "committee")
    n_total = sum(1 for r in results if r.group != "committee")
    # include committee in total listing separately
    n_total_all = len(results)
    rec_ar, rec_en = _verdict(score, n_found)
    levels = _levels(data, rec_en)

    # confidence from |score|, agreement, coverage
    found_dir = [r for r in results if r.found and r.signal is not None and r.weight > 0]
    if found_dir:
        if rec_en == "buy":
            agree = sum(1 for r in found_dir if (r.signal or 0) > 0) / len(found_dir)
        elif rec_en == "sell":
            agree = sum(1 for r in found_dir if (r.signal or 0) < 0) / len(found_dir)
        else:
            agree = sum(1 for r in found_dir if abs(r.signal or 0) < 0.25) / len(found_dir)
            agree = max(agree, 1.0 - abs(score) / 0.25 * 0.3)
    else:
        agree = 0.0
    coverage = n_found / max(1, n_total)
    conf = min(0.9, 0.25 + 0.45 * min(1.0, abs(score) / 0.5) + 0.2 * agree + 0.1 * coverage)
    if n_found < 15:
        conf *= 0.7

    regime_line = ""
    if data.regime:
        rg = data.regime
        acc = data.accuracy_weight_factors or {}
        acc_n = len(acc)
        regime_line = (
            f"حالة السوق: {rg.get('label')} (وكيل {rg.get('proxy')}) — تُعدَّل الأوزان وفق جدول MEMORY.md "
            f"(اتجاه {rg['factors']['trend']}، تذبذب {rg['factors']['oscillator']}، "
            f"أساسي {rg['factors']['fundamental']}، مخاطر {rg['factors']['risk']}). "
            f"تعديل الدقة: {'لا تعديل (عينة غير كافية)' if not acc_n else f'عوامل لـ {acc_n} وكيلاً'}."
        )
    else:
        regime_line = "حالة السوق: NOT FOUND — لم يُصنَّف نظام أوزان إضافي في هذه الجلسة."

    bull_s, bear_s = _debate_summaries(results)
    reasons = _top_reasons(results, rec_en)
    risks = _key_risks(results, rec_en)
    dissent = _dissenters(results, rec_en)
    not_found = [f"{r.name_ar}: {r.reason_ar} (المصدر: {r.source})" for r in results if (not r.found) and r.group != "committee"]

    daily = None
    if data.prev_close:
        daily = data.price / data.prev_close - 1.0

    now = datetime.now(RIYADH)
    generated_at = now.strftime("%Y-%m-%d %H:%M") + " (توقيت الرياض، Asia/Riyadh)"

    sector = data.sector or "غير محدد"
    chg = f"{fmt_pct(daily)}" if daily is not None else "غير متاح"
    sign = "+" if daily and daily > 0 else ""
    if daily is not None:
        chg = f"{sign}{fmt_pct(daily)}"

    def p(x):
        return fmt(x) if x is not None else "غير متاح"

    entry = f"{p(levels['entry_low'])} – {p(levels['entry_high'])} ر.س"
    mid = None
    if levels["entry_low"] is not None and levels["entry_high"] is not None:
        mid = (levels["entry_low"] + levels["entry_high"]) / 2.0
        if levels["stop"] is not None and mid:
            sl_pct = (levels["stop"] / mid - 1.0)
            sl_txt = f"{p(levels['stop'])} ر.س  ({fmt_pct(sl_pct)} من منتصف الدخول)"
        else:
            sl_txt = p(levels["stop"])
    else:
        sl_txt = p(levels["stop"])

    rr = ""
    if levels["risk"] and mid:
        rr = (
            f"  الهدف 1: {p(levels['t1'])} ر.س  (1.5R)\n"
            f"  الهدف 2: {p(levels['t2'])} ر.س  (2.5R)\n"
            f"  الهدف 3: {p(levels['t3'])} ر.س  (4.0R)"
        )
    else:
        rr = f"  الهدف 1: {p(levels['t1'])}\n  الهدف 2: {p(levels['t2'])}\n  الهدف 3: {p(levels['t3'])}"

    reasons_txt = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(reasons)) or "  NOT FOUND"
    risks_txt = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(risks)) or "  لم تُرصد مخاطر مفصّلة من الوكلاء المكتملين."
    dissent_txt = "\n".join(f"  - {t}" for t in dissent) or "  لا مخالفين بارزين."
    nf_txt = "\n".join(f"  - {t}" for t in not_found) if not_found else "  لا يوجد."

    if rec_en == "buy":
        judge = (
            f"اللجنة ترجّح الشراء بعد درجة موزونة {fmt(score, 2)} "
            f"وتوافق تقريبي {fmt_pct(agree)} بين الوكلاء المصوّتين."
        )
    elif rec_en == "sell":
        judge = (
            f"اللجنة ترجّح البيع بعد درجة موزونة {fmt(score, 2)} "
            f"وتوافق تقريبي {fmt_pct(agree)} بين الوكلاء المصوّتين."
        )
    else:
        judge = (
            f"اللجنة تُبقي على الاحتفاظ؛ الدرجة الموزونة {fmt(score, 2)} لم تتجاوز عتبة ±0.25 "
            f"(أو خُفِّض الحكم لقلّة البيانات)."
        )

    cr = getattr(data, "_candle_risk", None)
    candle_line = ""
    if cr:
        tgt = f"، الهدف عند المستوى التالي {fmt(cr['target'])}" if cr.get("target") is not None else ""
        candle_line = (f"\nإبطال نمط الشموع ({cr['pattern']}): {fmt(cr['stop'])} ر.س{tgt} "
                       f"— وكيل candle-risk-stop وفق knowledge/candlesticks/RULES.md (وقف النمط لا يحل محل وقف اللجنة أعلاه).")
    cc = getattr(data, "_candle_cache", None)
    if cc and cc.get("note") and cc["note"] not in data.fetch_notes:
        data.fetch_notes.append("مجموعة الشموع: " + cc["note"])

    notes = ""
    if data.fetch_notes:
        notes = "\nقيود البيانات:\n" + "\n".join(f"  - {n}" for n in data.fetch_notes)

    disclaimer = (
        "إخلاء مسؤولية: هذا التحليل آلي لأغراض تعليمية ومعلوماتية فقط، "
        "ولا يُعد توصية أو استشارة مالية مرخّصة، ولا يشكل عرضاً للشراء أو البيع. "
        "تداول الأسهم ينطوي على مخاطر، وقد تخسر جزءاً من رأس مالك أو كله. "
        "القرار الاستثماري مسؤوليتك وحدك، ويُستحسن مراجعة مستشار مرخّص."
    )

    report = f"""════════════════════════════════════════
تداول — تقرير لجنة التحليل
════════════════════════════════════════
السهم: {data.name_ar} ({data.ticker})
الاسم الإنجليزي: {data.name}
السوق: تداول — {sector} — {data.industry or 'صناعة غير محددة'}
السعر: {fmt(data.price)} ر.س  |  التغير اليومي: {chg}
تاريخ آخر إغلاق مستخدم: {data.last_bar_date}
وقت التقرير: {generated_at}
مصدر الأسعار والأساسيات: Yahoo Finance (ملف الجلسة / info)
عدد الشموع المستخدمة: {len(data.hist)}

التوصية: {rec_ar}
الثقة: {fmt_pct(conf, 0)}
الدرجة الموزونة: {fmt(score, 2)} (من -1 إلى +1)
عدد الوكلاء المشاركين (مكتملين): {n_found} من {n_total} (اللجنة لا تصوّت)
{regime_line}

منطقة الدخول: {entry}
وقف الخسارة: {sl_txt}
الأهداف:
{rr}
حجم المركز المقترح: مخاطرة 1% من رأس المال ÷ المسافة إلى الوقف (لا يُفترض حجم حساب).{candle_line}

أبرز الأسباب:
{reasons_txt}

المخاطر الرئيسية:
{risks_txt}

الوكلاء المخالفون (صوّتوا عكس التوصية أو بقوة في حالة الاحتفاظ):
{dissent_txt}

ملخص النقاش (الثور مقابل الدب):
  الثور: {bull_s}
  الدب: {bear_s}
  حكم اللجنة: {judge}

وكلاء NOT FOUND (استُبعدوا من التصويت):
{nf_txt}
{notes}

{disclaimer}
════════════════════════════════════════
"""

    # update committee result reason to the judge line
    for r in results:
        if r.agent_id == "committee-judge":
            r.reason_ar = judge
            r.signal = score
            r.confidence = conf
            r.found = True
            r.source = "engine/aggregate.py + نتائج الوكلاء"

    return Recommendation(
        ticker=data.ticker,
        name_ar=data.name_ar,
        rec_ar=rec_ar,
        rec_en=rec_en,
        confidence=conf,
        weighted_score=score,
        price=data.price,
        last_bar_date=data.last_bar_date,
        entry_low=levels["entry_low"],
        entry_high=levels["entry_high"],
        stop_loss=levels["stop"],
        target1=levels["t1"],
        target2=levels["t2"],
        target3=levels["t3"],
        risk_r=levels["risk"],
        top_reasons=reasons,
        key_risks=risks,
        dissenters=dissent,
        bull_summary=bull_s,
        bear_summary=bear_s,
        committee_summary=judge,
        n_found=n_found,
        n_total=n_total,
        not_found=not_found,
        results=results,
        report_ar=report,
        source_note="Yahoo Finance + MEMORY.md + نتائج الوكلاء في stocks/",
        generated_at=generated_at,
    )
