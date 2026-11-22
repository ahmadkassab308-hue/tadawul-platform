"""Performance auditor helpers. Never invent accuracy from thin history."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

from .universe import ACCURACY_MIN_DECISIONS, ACCURACY_MIN_PER_AGENT, ROOT

RIYADH = ZoneInfo("Asia/Riyadh")
ACC_DIR = ROOT / "accuracy"
ACC_JSON = ACC_DIR / "agent-accuracy.json"
ACC_MD = ACC_DIR / "agent-accuracy.md"
VOTES_LOG = ACC_DIR / "votes-log.jsonl"
DECISIONS = ROOT / "decisions.md"
LEARNINGS = ROOT / "LEARNINGS.md"

HEAD_RE = re.compile(
    r"^##\s+(\d{4}-\d{2}-\d{2})\s+\|\s+([A-Z0-9]+(?:\.[A-Z]+)?)\s+\|\s+(شراء|احتفاظ|بيع)\s+\|\s+ثقة\s+(\d+)%\s+\|\s+سعر\s+([0-9.]+)",
    re.M,
)


def parse_decisions(text: Optional[str] = None) -> list[dict]:
    if text is None:
        if not DECISIONS.exists():
            return []
        text = DECISIONS.read_text(encoding="utf-8")
    rows = []
    for m in HEAD_RE.finditer(text):
        rows.append(
            {
                "date": m.group(1),
                "ticker": m.group(2),
                "rec": m.group(3),
                "confidence": int(m.group(4)) / 100.0,
                "price": float(m.group(5)),
            }
        )
    return rows


def subsequent_return(hist: Optional[pd.DataFrame], decision_date: str, decision_price: float) -> Optional[dict]:
    """Return after the first close strictly after decision_date, up to the latest close."""
    if hist is None or hist.empty or decision_price <= 0:
        return None
    idx = hist.index
    try:
        if getattr(idx, "tz", None) is not None:
            dates = idx.tz_convert("Asia/Riyadh").strftime("%Y-%m-%d")
        else:
            dates = pd.DatetimeIndex(idx).strftime("%Y-%m-%d")
    except Exception:
        dates = [str(x)[:10] for x in idx]
    later = [i for i, d in enumerate(dates) if d > decision_date]
    if not later:
        return None
    last_i = later[-1]
    last_px = float(hist["Close"].iloc[last_i])
    last_d = dates[last_i]
    ret = last_px / decision_price - 1.0
    return {"last_date": last_d, "last_price": last_px, "return": ret, "bars": len(later)}


def score_rec(rec_ar: str, ret: float) -> Optional[int]:
    """1 = consistent with recommendation, 0 = not. Hold: consistent if |ret| < 5%."""
    if rec_ar == "شراء":
        return 1 if ret > 0 else 0
    if rec_ar == "بيع":
        return 1 if ret < 0 else 0
    if rec_ar == "احتفاظ":
        return 1 if abs(ret) < 0.05 else 0
    return None


def load_accuracy() -> dict:
    if ACC_JSON.exists():
        try:
            return json.loads(ACC_JSON.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"updated": None, "committee": {}, "agents": {}, "notes": []}


def write_accuracy(doc: dict, narrative: list[str]) -> None:
    ACC_DIR.mkdir(parents=True, exist_ok=True)
    doc = dict(doc)
    doc["updated"] = datetime.now(RIYADH).strftime("%Y-%m-%d %H:%M") + " (توقيت الرياض، Asia/Riyadh)"
    ACC_JSON.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# دقة الوكلاء — agent-accuracy.md",
        "",
        f"آخر تحديث: {doc['updated']}",
        "",
        "لا تُعدَّل الأوزان بناءً على دقة مخمّنة. يُشترط حد أدنى من التوصيات المُقيَّمة "
        f"({ACCURACY_MIN_DECISIONS} للجنة، و{ACCURACY_MIN_PER_AGENT} لكل وكيل من ملف votes-log.jsonl).",
        "",
    ]
    comm = doc.get("committee") or {}
    lines.append("## دقة توصيات اللجنة")
    if comm.get("n"):
        lines.append(
            f"- تقييمات مكتملة: {comm['n']}، نجاح: {comm.get('wins', 0)}، نسبة: {comm.get('hit_rate')}"
        )
    else:
        lines.append("- NOT FOUND — لا توجد توصيات سابقة لها إغلاق لاحق يُقاس عليه.")
    lines.append("")
    lines.append("## دقة الوكلاء")
    agents = doc.get("agents") or {}
    if not agents:
        lines.append("- لا سجل أصوات تفصيلي كافٍ بعد. يبدأ التتبع لكل وكيل من `accuracy/votes-log.jsonl`.")
    else:
        for aid, a in sorted(agents.items()):
            lines.append(f"- `{aid}`: n={a.get('n')} hits={a.get('wins')} rate={a.get('hit_rate')} weight_factor={a.get('weight_factor', 1.0)}")
    lines.append("")
    lines.append("## ملاحظات هذه الجلسة")
    for n in narrative:
        lines.append(f"- {n}")
    lines.append("")
    ACC_MD.write_text("\n".join(lines), encoding="utf-8")


def append_learning(text: str) -> None:
    """Append a short factual lesson; never overwrite prior lessons."""
    LEARNINGS.parent.mkdir(parents=True, exist_ok=True)
    if not LEARNINGS.exists():
        LEARNINGS.write_text("# الدروس — LEARNINGS.md\n\n", encoding="utf-8")
    stamp = datetime.now(RIYADH).strftime("%Y-%m-%d %H:%M")
    block = f"\n### {stamp} (توقيت الرياض، Asia/Riyadh)\n\n{text.rstrip()}\n"
    existing = LEARNINGS.read_text(encoding="utf-8")
    if text.strip() in existing:
        return
    with LEARNINGS.open("a", encoding="utf-8") as f:
        f.write(block)


def log_votes(rec, results) -> str:
    ACC_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": rec.generated_at,
        "last_bar_date": rec.last_bar_date,
        "ticker": rec.ticker,
        "rec_ar": rec.rec_ar,
        "score": rec.weighted_score,
        "confidence": rec.confidence,
        "price": rec.price,
        "votes": [
            {
                "id": r.agent_id,
                "signal": r.signal,
                "confidence": r.confidence,
                "weight": r.weight,
                "found": r.found,
                "group": r.group,
            }
            for r in (rec.results or results or [])
        ],
    }
    with VOTES_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return str(VOTES_LOG)


def weight_factors_from_accuracy(doc: dict) -> dict:
    """Return {agent_id: factor} only when the per-agent sample is large enough."""
    out = {}
    for aid, a in (doc.get("agents") or {}).items():
        n = a.get("n") or 0
        if n < ACCURACY_MIN_PER_AGENT:
            continue
        rate = a.get("hit_rate")
        if rate is None:
            continue
        # 0.8 hit → 1.10, 0.5 → 1.00, 0.2 → 0.90; clip 0.75..1.25
        factor = 1.0 + (float(rate) - 0.5) * 0.4
        out[aid] = max(0.75, min(1.25, factor))
    return out
