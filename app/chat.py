"""بوت تداول — deterministic Arabic answers about the open symbol from the engine output."""
from __future__ import annotations

import re


def _pct(x):
    return "NOT FOUND" if x is None else f"{x*100:.0f}%"


def _f(x, cur=""):
    if x is None:
        return "NOT FOUND"
    return f"{x:,.2f}{(' ' + cur) if cur else ''}"


def _cur(p):
    c = p.get("currency") or ""
    return {"SAR": "ر.س", "USD": "$"}.get(c, c)


INTENTS = [
    ("help", r"مساعد|ساعد|وش تقدر|ماذا تستطيع|help|اوامر|أوامر"),
    ("levels", r"دخول|وقف|ستوب|هدف|اهداف|أهداف|target|stop|entry"),
    ("patterns", r"شمع|شموع|نمط|انماط|أنماط|candle"),
    ("risks", r"مخاطر|خطر|مخاطرة|risk|سلبي|عيوب"),
    ("reasons", r"ليش|لماذا|سبب|اسباب|أسباب|why|إيجابي|ايجابي"),
    ("debate", r"ثور|دب|نقاش|bull|bear"),
    ("groups", r"مجموع|فني|أساسي|اساسي|معنويات|سيولة"),
    ("sources", r"مصدر|مصادر|source"),
    ("nf", r"not found|ناقص|غير متوفر|بيانات"),
    ("price", r"سعر|كم|price|السعر"),
    ("verdict", r"توصية|رأي|راي|حكم|اشتري|أشتري|ابيع|أبيع|شراء|بيع|احتفاظ|قرار|تنصح"),
]


def intent(msg: str) -> str:
    m = msg.lower()
    for name, rx in INTENTS:
        if re.search(rx, m):
            return name
    return "summary"


def answer(msg: str, p: dict | None, quote: dict | None) -> str:
    it = intent(msg)
    if it == "help" or p is None and it != "price":
        base = ("أقدر أجاوبك عن السهم المفتوح: التوصية، السعر، الدخول والوقف والأهداف، أنماط الشموع، المخاطر، "
                "الأسباب، نقاش الثور والدب، المجموعات، المصادر، والبيانات الناقصة.")
        if p is None:
            base += " افتح سهماً واضغط «حلّل بـ94 محلل» أولاً، أو اسألني وأشغّل التحليل لك."
        return base
    if it == "price":
        if quote and quote.get("price") is not None:
            ch = quote.get("change_pct")
            st = "السوق مفتوح الآن" if quote.get("is_open") else "السوق مغلق (آخر سعر)"
            return (f"سعر {quote.get('symbol')}: {_f(quote['price'], quote.get('currency') or '')}"
                    + (f"، التغير {ch:+.2f}%" if ch is not None else "") + f". {st}. المصدر: Yahoo Finance.")
        if p:
            return f"آخر إغلاق حلّله المحرك: {_f(p['price'], _cur(p))} بتاريخ {p['last_bar_date']}."
        return "NOT FOUND — ما قدرت أجيب السعر."
    cur = _cur(p)
    head = f"{p['name_ar'] or p['ticker']} ({p['ticker']})"
    if it == "verdict" or it == "summary":
        return (f"{head}: حكم اللجنة **{p['verdict_ar']}** بثقة {_pct(p['confidence'])} ودرجة موزونة {p['score']:+.2f} "
                f"(صوّت {p['n_found']} من {p['n_total']}). السعر {_f(p['price'], cur)} على إغلاق {p['last_bar_date']}. "
                f"الدخول {_f(p['entry_low'])}–{_f(p['entry_high'])}، الوقف {_f(p['stop'])}، الأهداف {_f(p['t1'])} / {_f(p['t2'])} / {_f(p['t3'])}.\n"
                f"اللجنة: {p['committee']}\nتعليمي وليس توصية مالية.")
    if it == "levels":
        rr = p.get("risk_r")
        return (f"{head}: منطقة الدخول {_f(p['entry_low'])}–{_f(p['entry_high'])} {cur}، وقف الخسارة {_f(p['stop'])}، "
                f"الأهداف {_f(p['t1'])} ثم {_f(p['t2'])} ثم {_f(p['t3'])}" + (f"، مخاطرة/عائد R={rr}" if rr else "") +
                ". المستويات من وكيل وقف ATR والدعم/المقاومة في المحرك.")
    if it == "patterns":
        pats = p.get("patterns") or []
        if not pats:
            return f"{head}: ما فيه نمط شموع صالح (بالشكل + الاتجاه السابق) على آخر 3 شموع مكتملة. وكلاء الأنماط NOT FOUND."
        return f"{head} — أنماط الشموع الحالية:\n" + "\n".join(f"• {x['name']}: {x['reason']}" for x in pats)
    if it == "risks":
        return f"{head} — أهم المخاطر:\n" + "\n".join(f"• {r}" for r in (p.get("key_risks") or ["NOT FOUND"]))
    if it == "reasons":
        return f"{head} — أبرز الأسباب:\n" + "\n".join(f"• {r}" for r in (p.get("top_reasons") or ["NOT FOUND"]))
    if it == "debate":
        return f"🐂 الثور: {p['bull']}\n🐻 الدب: {p['bear']}\n⚖️ اللجنة: {p['committee']}"
    if it == "groups":
        return "\n".join(f"• {g['name_ar']}: صاعد {g['bull']}، هابط {g['bear']}، محايد {g['neutral']}، NOT FOUND {g['nf']}"
                         + (f"، متوسط {g['avg']:+.2f}" if g.get('avg') is not None else "") for g in p["groups"])
    if it == "sources":
        return "المصادر المستخدمة:\n" + "\n".join(f"• {s}" for s in (p.get("sources") or [])[:15])
    if it == "nf":
        return f"وكلاء NOT FOUND ({len(p.get('not_found') or [])}) استُبعدوا من التصويت:\n" + "\n".join(
            f"• {x}" for x in (p.get("not_found") or [])[:20])
    return answer("توصية", p, quote)
