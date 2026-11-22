"""Shared helpers for analyst scoring functions."""
from __future__ import annotations

from typing import Callable, Optional

from .indicators import last_valid
from .models import AgentSpec, AnalystResult, MarketData

SPECS: dict[str, AgentSpec] = {}
FUNCS: dict[str, Callable] = {}

OUTPUT_SCHEMA = (
    "signal: رقم بين 1- و 1+ (أو null عند NOT FOUND)؛ "
    "confidence: من 0 إلى 1؛ "
    "reason_ar: جملة عربية واحدة مع الرقم الأساسي؛ "
    "source: مصدر البيانات (ملف أو Yahoo Finance / الحقل)؛ "
    "إن نقصت البيانات: found=false والسبب يبدأ بـ NOT FOUND — دون تخمين."
)


def register(
    agent_id: str,
    name_ar: str,
    name_en: str,
    group: str,
    folder: str,
    filename: str,
    weight: float,
    role: str,
    inputs: str,
    method: str,
    pass_order: int = 1,
):
    spec = AgentSpec(
        agent_id=agent_id,
        name_ar=name_ar,
        name_en=name_en,
        group=group,
        folder=folder,
        filename=filename,
        weight=weight,
        role=role,
        inputs=inputs,
        method=method,
        output_schema=OUTPUT_SCHEMA,
        pass_order=pass_order,
    )

    def deco(fn: Callable):
        SPECS[agent_id] = spec
        FUNCS[agent_id] = fn
        fn.spec = spec
        return fn

    return deco


def nf(spec: AgentSpec, why: str, source: str = "NOT FOUND") -> AnalystResult:
    reason = why if why.startswith("NOT FOUND") else f"NOT FOUND — {why}"
    return AnalystResult(
        agent_id=spec.agent_id,
        name_ar=spec.name_ar,
        group=spec.group,
        weight=spec.weight,
        signal=None,
        confidence=0.0,
        reason_ar=reason,
        source=source,
        found=False,
    )


def ok(spec: AgentSpec, signal: float, confidence: float, reason_ar: str, source: str) -> AnalystResult:
    return AnalystResult(
        agent_id=spec.agent_id,
        name_ar=spec.name_ar,
        group=spec.group,
        weight=spec.weight,
        signal=max(-1.0, min(1.0, float(signal))),
        confidence=max(0.0, min(1.0, float(confidence))),
        reason_ar=reason_ar,
        source=source,
        found=True,
    )


def ind(data: MarketData, key: str, bars: int = 1):
    series = data.indicators.get(key)
    if series is None:
        return None
    if isinstance(series, list):
        return series
    return last_valid(series, bars)


def need_bars(data: MarketData, n: int) -> bool:
    return data.hist is not None and len(data.hist.dropna(subset=["Close"])) >= n


def src_hist(data: MarketData) -> str:
    return f"Yahoo Finance / history ({data.ticker}) — ملف الأسعار في الجلسة"


def src_info(data: MarketData, field: str) -> str:
    return f"Yahoo Finance / info.{field} ({data.ticker})"


def clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def linear_score(value: float, bear: float, bull: float) -> float:
    """Map value to [-1, 1] where `bear` is fully bearish and `bull` fully bullish."""
    if bull == bear:
        return 0.0
    t = (value - bear) / (bull - bear)
    return clamp(-1.0 + 2.0 * t)


def ret_over(series, bars: int) -> Optional[float]:
    if series is None:
        return None
    s = series.dropna()
    if len(s) <= bars:
        return None
    b = float(s.iloc[-1 - bars])
    if b == 0:
        return None
    return float(s.iloc[-1]) / b - 1.0


def fmt(x: float, nd: int = 2) -> str:
    return f"{x:.{nd}f}"


def fmt_pct(frac: float, nd: int = 1) -> str:
    return f"{frac * 100:.{nd}f}%"
