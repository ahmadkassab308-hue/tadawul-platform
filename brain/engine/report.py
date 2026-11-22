"""Persist Arabic reports into the flat-file brain (append-only)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .analysts_common import fmt, fmt_pct
from .models import Recommendation
from .universe import ROOT
from .accuracy import log_votes

RIYADH = ZoneInfo("Asia/Riyadh")
STOCKS = ROOT / "stocks"
DECISIONS = ROOT / "decisions.md"
SCANS = ROOT / "scans"


def stock_filename(ticker: str) -> str:
    return ticker.lower().replace(".", "-") + ".md"


def append_stock(rec: Recommendation) -> str:
    STOCKS.mkdir(parents=True, exist_ok=True)
    path = STOCKS / stock_filename(rec.ticker)
    header = (
        f"# {rec.name_ar} ({rec.ticker})\n\n"
        "ملف السهم — سجل تحليلات متسلسل (الأحدث أولاً). لا يُحذف السجل السابق.\n\n"
    )
    block = f"""## {rec.last_bar_date} | {rec.rec_ar} | ثقة {fmt_pct(rec.confidence, 0)} | سعر {fmt(rec.price)} ر.س

- وقت التقرير: {rec.generated_at}
- التوصية: {rec.rec_ar}
- الدرجة الموزونة: {fmt(rec.weighted_score, 2)}
- السعر (آخر إغلاق): {fmt(rec.price)} ر.س بتاريخ {rec.last_bar_date}
- منطقة الدخول: {fmt(rec.entry_low) if rec.entry_low else 'غير متاح'} – {fmt(rec.entry_high) if rec.entry_high else 'غير متاح'} ر.س
- وقف الخسارة: {fmt(rec.stop_loss) if rec.stop_loss else 'غير متاح'} ر.س
- الأهداف: {fmt(rec.target1) if rec.target1 else '—'} / {fmt(rec.target2) if rec.target2 else '—'} / {fmt(rec.target3) if rec.target3 else '—'} ر.س
- وكلاء مكتملون: {rec.n_found} من {rec.n_total}
- أبرز الأسباب:
{chr(10).join('  - ' + x for x in rec.top_reasons) or '  - NOT FOUND'}
- المخاطر:
{chr(10).join('  - ' + x for x in rec.key_risks) or '  - —'}
- المخالفون:
{chr(10).join('  - ' + x for x in rec.dissenters) or '  - لا مخالفين بارزين'}
- الثور: {rec.bull_summary}
- الدب: {rec.bear_summary}
- حكم اللجنة: {rec.committee_summary}
- المصدر: هذا الملف | decisions.md | Yahoo Finance
- إشارة لاحقة للدقة: (يُملأ لاحقاً عند المراجعة — لا تخمين)

"""
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing.startswith("# "):
            # keep title, insert after first blank line block
            parts = existing.split("\n", 3)
            # simpler: after header (first two paragraphs) prepend new block
            lines = existing.splitlines(True)
            # find first '##'
            idx = 0
            for i, ln in enumerate(lines):
                if ln.startswith("## "):
                    idx = i
                    break
            else:
                idx = len(lines)
            text = "".join(lines[:idx]) + block + "".join(lines[idx:])
        else:
            text = header + block + existing
        path.write_text(text, encoding="utf-8")
    else:
        path.write_text(header + block, encoding="utf-8")
    return str(path)


def append_decision(rec: Recommendation) -> str:
    DECISIONS.parent.mkdir(parents=True, exist_ok=True)
    if not DECISIONS.exists():
        DECISIONS.write_text(
            "# سجل القرارات — decisions.md\n\n"
            "سجل إلحاق فقط لكل توصية صادرة عن اللجنة. يُستخدم لاحقاً لتتبع الدقة.\n"
            "لا تُعدَّل القيود السابقة. إن نقص حقل يُكتب NOT FOUND لا تخمين.\n\n",
            encoding="utf-8",
        )
    entry = f"""## {rec.last_bar_date} | {rec.ticker} | {rec.rec_ar} | ثقة {fmt_pct(rec.confidence, 0)} | سعر {fmt(rec.price)}

- الاسم: {rec.name_ar}
- وقت التقرير: {rec.generated_at}
- التوصية: {rec.rec_ar}
- الدرجة الموزونة: {fmt(rec.weighted_score, 2)}
- سعر الإغلاق: {fmt(rec.price)} ر.س
- منطقة الدخول: {fmt(rec.entry_low) if rec.entry_low else 'NOT FOUND'}–{fmt(rec.entry_high) if rec.entry_high else 'NOT FOUND'}
- وقف الخسارة: {fmt(rec.stop_loss) if rec.stop_loss else 'NOT FOUND'}
- الأهداف: {fmt(rec.target1) if rec.target1 else 'NOT FOUND'} / {fmt(rec.target2) if rec.target2 else 'NOT FOUND'} / {fmt(rec.target3) if rec.target3 else 'NOT FOUND'}
- أبرز الأسباب: {'; '.join(rec.top_reasons[:3]) if rec.top_reasons else 'NOT FOUND'}
- المخاطر: {'; '.join(rec.key_risks[:3]) if rec.key_risks else 'NOT FOUND'}
- المخالفون: {'; '.join(rec.dissenters[:3]) if rec.dissenters else 'لا مخالفين بارزين'}
- المصدر: stocks/{stock_filename(rec.ticker)} | Yahoo Finance
- نتيجة لاحقة (للتتبع): (فارغ حتى المراجعة)

"""
    with DECISIONS.open("a", encoding="utf-8") as f:
        f.write(entry)
    return str(DECISIONS)


def write_scan(rows: list[Recommendation], title: str | None = None) -> str:
    SCANS.mkdir(parents=True, exist_ok=True)
    now = datetime.now(RIYADH)
    stamp = now.strftime("%Y-%m-%d")
    path = SCANS / f"watchlist-scan-{stamp}.md"
    lines = [
        f"# مسح قائمة المراقبة — {stamp}",
        "",
        f"وقت المسح: {now.strftime('%Y-%m-%d %H:%M')} (توقيت الرياض، Asia/Riyadh)",
        "الترتيب حسب الدرجة الموزونة تنازلياً. المصدر: Yahoo Finance + قرارات اللجنة في decisions.md و stocks/.",
        "",
        "| الترتيب | الرمز | الاسم | السعر | التوصية | الثقة | الدرجة | دخول | وقف | هدف 1 | وكلاء |",
        "|---|---|---|---:|---|---:|---:|---|---:|---:|---:|",
    ]
    ranked = sorted(rows, key=lambda r: r.weighted_score, reverse=True)
    for i, r in enumerate(ranked, 1):
        entry = (
            f"{fmt(r.entry_low)}–{fmt(r.entry_high)}"
            if r.entry_low is not None and r.entry_high is not None
            else "—"
        )
        lines.append(
            f"| {i} | {r.ticker} | {r.name_ar} | {fmt(r.price)} | {r.rec_ar} | {fmt_pct(r.confidence, 0)} "
            f"| {fmt(r.weighted_score, 2)} | {entry} | {fmt(r.stop_loss) if r.stop_loss else '—'} "
            f"| {fmt(r.target1) if r.target1 else '—'} | {r.n_found}/{r.n_total} |"
        )
    lines.append("")
    lines.append("إخلاء مسؤولية: تحليل آلي تعليمي، ليس استشارة مالية مرخّصة.")
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def persist(rec: Recommendation) -> dict:
    paths = {"stock": append_stock(rec), "decisions": append_decision(rec)}
    try:
        paths["votes"] = log_votes(rec, rec.results)
    except Exception:
        paths["votes"] = None
    return paths
