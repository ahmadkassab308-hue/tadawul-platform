"""Shared data models for the Tadawul Brain engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd


@dataclass
class AnalystResult:
    agent_id: str
    name_ar: str
    group: str
    weight: float
    signal: Optional[float]  # -1..+1, None if NOT FOUND
    confidence: float  # 0..1
    reason_ar: str
    source: str
    found: bool

    def clipped_signal(self) -> Optional[float]:
        if not self.found or self.signal is None:
            return None
        return max(-1.0, min(1.0, float(self.signal)))


@dataclass
class MarketData:
    ticker: str
    name: str
    name_ar: str
    sector: str
    industry: str
    currency: str
    price: float
    prev_close: Optional[float]
    last_bar_date: str
    hist: pd.DataFrame
    info: dict
    news: list
    financials: Optional[pd.DataFrame] = None
    quarterly_financials: Optional[pd.DataFrame] = None
    balance_sheet: Optional[pd.DataFrame] = None
    cashflow: Optional[pd.DataFrame] = None
    brent: Optional[pd.DataFrame] = None
    wti: Optional[pd.DataFrame] = None
    tasi_spot: Optional[dict] = None
    tasi_hist: Optional[pd.DataFrame] = None
    ksa_etf: Optional[pd.DataFrame] = None
    usd_sar: Optional[pd.DataFrame] = None
    sama: Optional[dict] = None
    peer_hist: dict = field(default_factory=dict)  # ticker -> Close series
    peer_names: dict = field(default_factory=dict)
    indicators: dict = field(default_factory=dict)
    fetch_notes: list = field(default_factory=list)
    # Extended data for the 13 added analysts. None / empty means NOT FOUND upstream.
    earnings_dates: Optional[pd.DataFrame] = None
    earnings_history: Optional[pd.DataFrame] = None
    calendar: dict = field(default_factory=dict)
    dividends: Optional[pd.Series] = None
    quarterly_balance_sheet: Optional[pd.DataFrame] = None
    quarterly_cashflow: Optional[pd.DataFrame] = None
    announcements: Optional[list] = None
    foreign_ownership: Optional[dict] = None
    investor_flows: Optional[dict] = None
    petrochem: Optional[dict] = None
    watchlist_hist: dict = field(default_factory=dict)
    watchlist_pe: dict = field(default_factory=dict)
    regime: Optional[dict] = None
    regime_weight_factors: dict = field(default_factory=dict)
    accuracy_weight_factors: dict = field(default_factory=dict)


@dataclass
class AgentSpec:
    agent_id: str
    name_ar: str
    name_en: str
    group: str
    folder: str
    filename: str
    weight: float
    role: str
    inputs: str
    method: str
    output_schema: str
    pass_order: int = 1  # 1 = primary, 2 = debate (after others), 3 = committee


@dataclass
class Recommendation:
    ticker: str
    name_ar: str
    rec_ar: str  # شراء / احتفاظ / بيع
    rec_en: str
    confidence: float
    weighted_score: float
    price: float
    last_bar_date: str
    entry_low: Optional[float]
    entry_high: Optional[float]
    stop_loss: Optional[float]
    target1: Optional[float]
    target2: Optional[float]
    target3: Optional[float]
    risk_r: Optional[float]
    top_reasons: list
    key_risks: list
    dissenters: list
    bull_summary: str
    bear_summary: str
    committee_summary: str
    n_found: int
    n_total: int
    not_found: list
    results: list
    report_ar: str
    source_note: str
    generated_at: str
