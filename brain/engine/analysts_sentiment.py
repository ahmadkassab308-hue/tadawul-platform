"""Sentiment / news / street-consensus analysts."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from .analysts_common import fmt, fmt_pct, nf, ok, register, src_hist, src_info
from .fetch import info_number
from .models import MarketData
from .universe import news_aliases, name_ar


POS_WORDS = (
    "ارتفاع", "نمو", "ربح", "أرباح", "توزيع", "توسع", "عقد", "شراكة", "أعلى", "شراء",
    "upgrade", "beat", "growth", "profit", "record", "contract", "partnership",
    "expansion", "dividend", "buy", "outperform", "raise", "surge", "rally", "strong",
)
NEG_WORDS = (
    "انخفاض", "خسائر", "خسارة", "هبوط", "غرامة", "تراجع", "هبوط", "تحقيق",
    "downgrade", "loss", "miss", "lawsuit", "cut", "decline", "crash", "fraud",
    "probe", "fine", "sell", "underperform", "weak", "slump", "drop", "plunge",
)


def _news_items(data: MarketData) -> list[dict]:
    out = []
    for item in data.news or []:
        content = item.get("content") if isinstance(item, dict) else None
        if not isinstance(content, dict):
            content = item if isinstance(item, dict) else {}
        title = content.get("title") or item.get("title") or ""
        summary = content.get("summary") or content.get("description") or ""
        pub = content.get("pubDate") or content.get("displayTime") or item.get("providerPublishTime")
        out.append({"title": str(title), "summary": str(summary or ""), "pub": pub})
    return out


def _relevant(data: MarketData, title: str, summary: str) -> bool:
    text = (title + " " + summary).lower()
    aliases = news_aliases(data.ticker, data.name)
    aliases.append(name_ar(data.ticker, "").lower())
    return any(a and a in text for a in aliases)


def _score_text(text: str) -> int:
    t = text.lower()
    pos = sum(1 for w in POS_WORDS if w.lower() in t)
    neg = sum(1 for w in NEG_WORDS if w.lower() in t)
    return pos - neg


def _parse_pub(pub) -> datetime | None:
    if pub is None:
        return None
    if isinstance(pub, (int, float)):
        try:
            return datetime.fromtimestamp(pub, tz=timezone.utc)
        except Exception:
            return None
    if isinstance(pub, str):
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(pub[:26].replace("Z", "").split(".")[0], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            except Exception:
                continue
            break
        try:
            return datetime.fromisoformat(pub.replace("Z", "+00:00"))
        except Exception:
            return None
    return None


@register(
    "news-sentiment",
    "وكيل معنويات الأخبار",
    "News Sentiment",
    "sentiment",
    "sentiment",
    "news-sentiment.md",
    0.7,
    "تقدير مشاعر العناوين المرتبطة بالشركة فقط عبر كلمات مفتاحية عربية/إنجليزية.",
    "Yahoo Finance ticker.news بعد فلترة العناوين التي تذكر اسم الشركة أو رمزها.",
    "فارق الكلمات الإيجابية والسلبية في العناوين ذات الصلة. الأخبار غير المرتبطة تُستبعد. إن لم تبقَ أخبار ذات صلة: NOT FOUND (لا يُفترض حياد السوق).",
)
def news_sentiment(data: MarketData, spec):
    items = _news_items(data)
    if not items:
        return nf(spec, "لا أخبار من Yahoo Finance لهذا الرمز في الجلسة.", f"Yahoo Finance / news ({data.ticker})")
    rel = [it for it in items if _relevant(data, it["title"], it["summary"])]
    if not rel:
        return nf(
            spec,
            f"وُجدت {len(items)} أخبار لكن أياً منها لا يذكر الشركة أو الرمز بوضوح.",
            f"Yahoo Finance / news ({data.ticker})",
        )
    scores = [_score_text(it["title"] + " " + it["summary"]) for it in rel]
    avg = sum(scores) / len(scores)
    sig = max(-1.0, min(1.0, avg / 2.0))
    conf = min(0.7, 0.3 + 0.1 * len(rel))
    sample = rel[0]["title"][:80]
    return ok(
        spec,
        sig,
        conf,
        f"{len(rel)} خبر ذو صلة من أصل {len(items)}؛ متوسط درجة الكلمات {fmt(avg, 2)}. مثال: {sample}.",
        f"Yahoo Finance / news ({data.ticker})",
    )


@register(
    "headline-momentum",
    "وكيل زخم العناوين",
    "Headline Momentum",
    "sentiment",
    "sentiment",
    "headline-momentum.md",
    0.55,
    "قياس كثافة الأخبار ذات الصلة زمنياً (هل هناك تدفق حديث؟).",
    "تواريخ نشر Yahoo Finance news ذات الصلة بالشركة.",
    "وجود عدة عناوين خلال 7 أيام يرفع درجة الزخم الإعلامي (إشارة خفيفة موجبة للكثافة لا للاتجاه). إن تعذر تحديد تواريخ أو لا أخبار ذات صلة: NOT FOUND.",
)
def headline_momentum(data: MarketData, spec):
    items = [it for it in _news_items(data) if _relevant(data, it["title"], it["summary"])]
    if not items:
        return nf(spec, "لا عناوين ذات صلة لقياس الزخم الإعلامي.", f"Yahoo Finance / news ({data.ticker})")
    now = datetime.now(timezone.utc)
    dated = []
    for it in items:
        dt = _parse_pub(it["pub"])
        if dt:
            dated.append(dt)
    if not dated:
        return nf(spec, "العناوين ذات الصلة بلا تواريخ قابلة للتحليل.", f"Yahoo Finance / news ({data.ticker})")
    recent7 = sum(1 for d in dated if now - d <= timedelta(days=7))
    recent30 = sum(1 for d in dated if now - d <= timedelta(days=30))
    if recent7 + recent30 == 0:
        return nf(spec, "لا عناوين ذات صلة خلال 30 يوماً.", f"Yahoo Finance / news ({data.ticker})")
    # density is not a directional buy/sell; slight positive for attention only if also recent
    sig = min(0.35, 0.1 * recent7 + 0.03 * recent30)
    conf = 0.35 + 0.05 * recent7
    return ok(
        spec,
        sig,
        min(0.55, conf),
        f"{recent7} عناوين ذات صلة خلال 7 أيام و{recent30} خلال 30 يوماً (زخم إعلامي لا حكم اتجاه).",
        f"Yahoo Finance / news ({data.ticker})",
    )


@register(
    "street-consensus",
    "وكيل إجماع المحللين",
    "Street Consensus",
    "sentiment",
    "sentiment",
    "street-consensus.md",
    0.85,
    "قراءة توصية المحللين والسعر المستهدف المعلنين على Yahoo Finance.",
    "info.recommendationMean (1 شراء قوي — 5 بيع) و recommendationKey و targetMeanPrice و numberOfAnalystOpinions.",
    "المتوسط يُحوَّل إلى إشارة: (3 - mean)/2. العلاوة/الخصم إلى السعر المستهدف يُضاف بوزن محدود. إن غاب الإجماع: NOT FOUND.",
)
def street_consensus(data: MarketData, spec):
    mean = info_number(data.info, "recommendationMean")
    target = info_number(data.info, "targetMeanPrice")
    n = info_number(data.info, "numberOfAnalystOpinions")
    key = data.info.get("recommendationKey")
    if mean is None and target is None:
        return nf(spec, "لا إجماع محللين ولا سعر مستهدف في المصدر.", src_info(data, "recommendationMean"))
    bits = []
    sig, conf = 0.0, 0.45
    if mean is not None:
        sig = max(-1.0, min(1.0, (3.0 - mean) / 2.0))
        conf = 0.55 + 0.05 * min(8, n or 0)
        bits.append(f"متوسط التوصية {fmt(mean, 2)} (1 شراء قوي — 5 بيع)")
        if key:
            bits.append(f"التصنيف {key}")
        if n:
            bits.append(f"عدد الآراء {int(n)}")
    if target is not None and data.price:
        upside = target / data.price - 1.0
        bits.append(f"المستهدف {fmt(target)} أي {fmt_pct(upside)} عن السعر")
        sig = 0.7 * sig + 0.3 * max(-1, min(1, upside / 0.2)) if mean is not None else max(-1, min(1, upside / 0.2))
        conf = max(conf, 0.55)
    return ok(spec, sig, min(0.8, conf), "؛ ".join(bits) + ".", src_info(data, "recommendationMean/targetMeanPrice"))


@register(
    "price-gap-reaction",
    "وكيل فجوات السعر",
    "Price Gap Reaction",
    "sentiment",
    "sentiment",
    "price-gap-reaction.md",
    0.7,
    "رصد فجوة الافتتاح الأخيرة وحجمها كأثر محتمل لخبر.",
    "Open/Close لآخر يومين والحجم.",
    "فجوة صاعدة ≥1% مع حجم فوق المتوسط = ميل إيجابي، وفجوة هابطة مماثلة سلبية. إن لم توجد فجوة واضحة: NOT FOUND.",
)
def price_gap(data: MarketData, spec):
    if len(data.hist) < 3:
        return nf(spec, "لا يكفي من الشموع لرصد فجوة.", src_hist(data))
    prev_close = float(data.hist["Close"].iloc[-2])
    last_open = float(data.hist["Open"].iloc[-1])
    if prev_close == 0:
        return nf(spec, "إغلاق سابق صفر غير صالح.", src_hist(data))
    gap = last_open / prev_close - 1.0
    if abs(gap) < 0.01:
        return nf(spec, f"لا فجوة واضحة (الفجوة {fmt_pct(gap)} أقل من 1%).", src_hist(data))
    vol = float(data.hist["Volume"].iloc[-1])
    vavg = None
    vs = data.indicators.get("vol_sma20")
    if vs is not None and len(vs.dropna()):
        vavg = float(vs.dropna().iloc[-1])
    conf = 0.55
    extra = ""
    if vavg and vavg > 0:
        extra = f" والحجم ×{fmt(vol / vavg, 2)} المتوسط"
        if vol > 1.3 * vavg:
            conf = 0.7
    sig = max(-1, min(1, gap / 0.03))
    kind = "صاعدة" if gap > 0 else "هابطة"
    return ok(
        spec,
        sig,
        conf,
        f"فجوة {kind} {fmt_pct(gap)} بين إغلاق {fmt(prev_close)} وافتتاح {fmt(last_open)}{extra}.",
        src_hist(data),
    )
