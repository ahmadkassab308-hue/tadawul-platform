#!/usr/bin/env python3
"""CLI: analyse one or more Tadawul tickers, or scan a watchlist.

Examples:
  .venv/bin/python engine/run.py 2222.SR
  .venv/bin/python engine/run.py 2222.SR 1120.SR
  .venv/bin/python engine/run.py --watchlist
  .venv/bin/python engine/run.py --watchlist watchlist.txt --limit 6
  .venv/bin/python engine/run.py --list-agents
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python engine/run.py` from repo root or `python -m engine.run`.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.aggregate import decide, run_analysts
from engine.analysts_common import SPECS
from engine.fetch import fetch_macro, fetch_stock
from engine.report import persist, write_scan
from engine.universe import DEFAULT_WATCHLIST, ROOT as BRAIN_ROOT


def load_watchlist(path: Path | None) -> list[str]:
    if path is None:
        default = BRAIN_ROOT / "watchlist.txt"
        path = default if default.exists() else None
    if path is None:
        return list(DEFAULT_WATCHLIST)
    tickers = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip().upper()
        if not line:
            continue
        if line.isdigit():
            line = line + ".SR"
        tickers.append(line)
    return tickers or list(DEFAULT_WATCHLIST)


def list_agents() -> str:
    lines = [f"عدد الوكلاء المعرّفين: {len(SPECS)}", ""]
    groups: dict[str, list] = {}
    for spec in SPECS.values():
        groups.setdefault(spec.group, []).append(spec)
    for g, items in groups.items():
        lines.append(f"## {g} ({len(items)})")
        for s in items:
            lines.append(f"- {s.agent_id}: {s.name_ar}  [{s.folder}/{s.filename}] وزن={s.weight}")
        lines.append("")
    return "\n".join(lines)


def analyse_ticker(ticker: str, macro: dict, persist_files: bool = True):
    data = fetch_stock(ticker, macro=macro, with_peers=True)
    results = run_analysts(data)
    rec = decide(data, results)
    paths = persist(rec) if persist_files else {}
    return rec, paths, data


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="تداول — محرك تحليل الأسهم متعدد الوكلاء (السوق السعودية أولاً)."
    )
    p.add_argument("tickers", nargs="*", help="رموز Yahoo مثل 2222.SR أو 2222")
    p.add_argument("--watchlist", nargs="?", const="__default__", help="مسح قائمة المراقبة (ملف اختياري)")
    p.add_argument("--limit", type=int, default=0, help="حد أعلى لعدد الأسهم في المسح (0 = الكل)")
    p.add_argument("--list-agents", action="store_true", help="عرض الوكلاء المعرّفين")
    p.add_argument("--no-persist", action="store_true", help="طباعة التقرير دون الإلحاق بالملفات")
    args = p.parse_args(argv)

    if args.list_agents:
        print(list_agents())
        return 0

    tickers: list[str] = []
    scan_mode = args.watchlist is not None
    if scan_mode:
        path = None if args.watchlist == "__default__" else Path(args.watchlist)
        tickers.extend(load_watchlist(path))
        if args.limit and args.limit > 0:
            tickers = tickers[: args.limit]
    tickers.extend(t.upper() if not t.upper().endswith(".SR") and t.isdigit() else t.upper() for t in args.tickers)
    # normalize bare numbers
    norm = []
    for t in tickers:
        t = t.strip().upper()
        if t.isdigit():
            t = t + ".SR"
        if t not in norm:
            norm.append(t)
    tickers = norm
    if not tickers:
        p.print_help()
        print("\nمثال: python engine/run.py 2222.SR", file=sys.stderr)
        return 2

    print(f"جلب البيانات الكلية مرة واحدة، ثم تحليل {len(tickers)} رمز(رموز)...", file=sys.stderr)
    macro = fetch_macro()
    recs = []
    errors = []
    for t in tickers:
        try:
            rec, paths, _data = analyse_ticker(t, macro, persist_files=not args.no_persist)
        except Exception as exc:
            errors.append((t, f"{type(exc).__name__}: {exc}"))
            print(f"\n[{t}] NOT FOUND / خطأ: {type(exc).__name__}: {exc}\n", file=sys.stderr)
            continue
        recs.append(rec)
        print(rec.report_ar)
        if paths:
            print(f"(حُفظ في: {paths.get('stock')}  و  {paths.get('decisions')})\n")

    if scan_mode and recs and not args.no_persist:
        scan_path = write_scan(recs)
        print(f"\nملف ترتيب المسح: {scan_path}\n")
        # Arabic ranking table to stdout
        print("════════ ترتيب قائمة المراقبة ════════")
        ranked = sorted(recs, key=lambda r: r.weighted_score, reverse=True)
        for i, r in enumerate(ranked, 1):
            print(
                f"{i:2d}. {r.ticker:10s} {r.name_ar:24s}  {r.rec_ar:6s}  "
                f"درجة {r.weighted_score:+.2f}  ثقة {r.confidence*100:.0f}%  سعر {r.price:.2f}"
            )
        print("══════════════════════════════════════\n")

    if errors:
        print("تعذر تحليل:", file=sys.stderr)
        for t, e in errors:
            print(f"  {t}: {e}", file=sys.stderr)
        # if everything failed
        if not recs:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
