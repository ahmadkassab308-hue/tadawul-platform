#!/usr/bin/env python3
"""Generate agent definition markdown files from the registered SPECS."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.aggregate import SPECS  # registers all
from engine.universe import ROOT as BRAIN


TEMPLATE = """# {name_ar}

- المعرّف: `{agent_id}`
- الاسم الإنجليزي: {name_en}
- المجموعة: {group}
- الملف: `agents/{folder}/{filename}`
- الوزن الافتراضي في التصويت: {weight}
- ترتيب التنفيذ: المرحلة {pass_order}

## الدور

{role}

## المدخلات

{inputs}

## المنهج

{method}

## مخطط المخرجات

{output_schema}

## قواعد الدماغ

- موضوع واحد في هذا الملف.
- إن نقصت المدخلات يخرج الوكيل `NOT FOUND` ويُستبعد من التصويت — يُمنع التخمين.
- يُذكر مصدر البيانات في حقل source ويُستشهد به في التقرير.
- دالة التنفيذ في محرك بايثون مربوطة بالمعرّف `{agent_id}`.
"""


def main() -> None:
    n = 0
    for spec in SPECS.values():
        folder = BRAIN / "agents" / spec.folder
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / spec.filename
        path.write_text(
            TEMPLATE.format(
                name_ar=spec.name_ar,
                agent_id=spec.agent_id,
                name_en=spec.name_en,
                group=spec.group,
                folder=spec.folder,
                filename=spec.filename,
                weight=spec.weight,
                pass_order=spec.pass_order,
                role=spec.role,
                inputs=spec.inputs,
                method=spec.method,
                output_schema=spec.output_schema,
            ),
            encoding="utf-8",
        )
        n += 1
    print(f"wrote {n} agent markdown files")


if __name__ == "__main__":
    main()
