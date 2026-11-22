"""Bull / bear advocates — second-pass agents that read other analysts' results."""
from __future__ import annotations

from .analysts_common import fmt, nf, ok, register
from .models import AnalystResult, MarketData


def _found(results: list[AnalystResult]) -> list[AnalystResult]:
    return [r for r in results if r.found and r.signal is not None]


@register(
    "bull-advocate",
    "المحامي الثور",
    "Bull Advocate",
    "debate",
    "debate",
    "bull-advocate.md",
    0.55,
    "جمع أقوى الحجج الشرائية من وكلاء المرحلة الأولى وصياغتها كتصويت صاعد.",
    "نتائج الوكلاء المكتملة (قبل الثور/الدب/اللجنة).",
    "الإشارة = متوسط مرجح لأقوى الحجج الموجبة (أعلى 8 إشارات موجبة وزناً وثقة). إن لم توجد حجة موجبة: إشارة صفر بثقة منخفضة أو NOT FOUND إن لم تكتمل أي نتائج.",
    pass_order=2,
)
def bull_advocate(data: MarketData, spec, prior: list[AnalystResult] | None = None):
    prior = prior or []
    found = [r for r in _found(prior) if r.group != "debate"]
    if not found:
        return nf(spec, "لا نتائج مكتملة ليبني عليها الثور.", "نتائج الوكلاء — المرحلة 1")
    bulls = [r for r in found if (r.signal or 0) > 0.05]
    if not bulls:
        return ok(
            spec,
            0.0,
            0.25,
            "لم يجد الثور حججاً موجبة ذات شأن بين الوكلاء المكتملين.",
            "نتائج الوكلاء — المرحلة 1",
        )
    bulls = sorted(bulls, key=lambda r: (r.signal or 0) * r.confidence * r.weight, reverse=True)
    top = bulls[:8]
    wsum = sum(r.confidence * r.weight for r in top) or 1.0
    sig = sum((r.signal or 0) * r.confidence * r.weight for r in top) / wsum
    # coverage: how many of all found are bullish
    share = len(bulls) / len(found)
    conf = min(0.8, 0.35 + 0.4 * share)
    names = "؛ ".join(f"{r.name_ar} ({fmt(r.signal or 0, 2)})" for r in top[:4])
    return ok(
        spec,
        sig,
        conf,
        f"أقوى حجج الشراء ({len(bulls)} وكيلاً): {names}.",
        "نتائج الوكلاء — المرحلة 1",
    )


@register(
    "bear-advocate",
    "المحامي الدب",
    "Bear Advocate",
    "debate",
    "debate",
    "bear-advocate.md",
    0.55,
    "جمع أقوى الحجج البيعية من وكلاء المرحلة الأولى وصياغتها كتصويت هابط.",
    "نتائج الوكلاء المكتملة (قبل الثور/الدب/اللجنة).",
    "الإشارة = متوسط مرجح لأقوى الحجج السالبة (أكثرها هبوطاً). إن لم توجد حجة سالبة: إشارة صفر بثقة منخفضة.",
    pass_order=2,
)
def bear_advocate(data: MarketData, spec, prior: list[AnalystResult] | None = None):
    prior = prior or []
    found = [r for r in _found(prior) if r.group != "debate"]
    if not found:
        return nf(spec, "لا نتائج مكتملة ليبني عليها الدب.", "نتائج الوكلاء — المرحلة 1")
    bears = [r for r in found if (r.signal or 0) < -0.05]
    if not bears:
        return ok(
            spec,
            0.0,
            0.25,
            "لم يجد الدب حججاً سالبة ذات شأن بين الوكلاء المكتملين.",
            "نتائج الوكلاء — المرحلة 1",
        )
    bears = sorted(bears, key=lambda r: (-(r.signal or 0)) * r.confidence * r.weight, reverse=True)
    top = bears[:8]
    wsum = sum(r.confidence * r.weight for r in top) or 1.0
    sig = sum((r.signal or 0) * r.confidence * r.weight for r in top) / wsum
    share = len(bears) / len(found)
    conf = min(0.8, 0.35 + 0.4 * share)
    names = "؛ ".join(f"{r.name_ar} ({fmt(r.signal or 0, 2)})" for r in top[:4])
    return ok(
        spec,
        sig,
        conf,
        f"أقوى حجج البيع ({len(bears)} وكيلاً): {names}.",
        "نتائج الوكلاء — المرحلة 1",
    )


@register(
    "committee-judge",
    "اللجنة الحاكمة",
    "Committee Judge",
    "committee",
    "committee",
    "committee-judge.md",
    0.0,
    "إصدار الحكم النهائي (شراء/احتفاظ/بيع) بعد التصويت الموزون ونقاش الثور والدب، دون أن تصوّت اللجنة لنفسها.",
    "كل نتائج الوكلاء بما فيها الثور والدب، والسعر وATR لتحديد مناطق الدخول والوقف والأهداف.",
    "الدرجة = مجموع (الإشارة × الثقة × الوزن) / مجموع (الثقة × الوزن) للوكلاء المكتملين فقط. عتبات: فوق +0.25 شراء، تحت -0.25 بيع، وإلا احتفاظ. إن ضعف عدد الوكلاء المكتملين (<15) تُخفض الثقة ويُفضَّل الاحتفاظ عند الدرجة الحدية. الوزن للجنة صفر حتى لا تصوّت لنفسها. الثقة تُخفض إذا كان خلاف الثور/الدب حاداً أو اختلف وكلاء المخاطرة بشدة.",
    pass_order=3,
)
def committee_judge(data: MarketData, spec, prior: list[AnalystResult] | None = None):
    """The actual verdict is produced in aggregate.py; this returns a descriptive result
    that is not included in the weighted vote (weight=0)."""
    prior = prior or []
    found = _found(prior)
    if not found:
        return nf(spec, "لا وكلاء مكتملين لإصدار حكم.", "نتائج الوكلاء")
    return ok(
        spec,
        0.0,
        0.0,
        f"اللجنة استلمت {len(found)} نتيجة مكتملة وستُصدر الحكم في محرك التجميع (وزن التصويت = 0).",
        "engine/aggregate.py",
    )
