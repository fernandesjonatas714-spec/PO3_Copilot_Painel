from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class PriceLevel:
    code: str
    label: str
    value: float
    group: str


@dataclass(frozen=True)
class PriceZone:
    kind: str
    direction: str
    lower: float
    upper: float
    created_at: datetime
    timeframe: str = "D1"
    status: str = "ATIVA"


@dataclass(frozen=True)
class PO3Event:
    time: datetime
    title: str
    detail: str
    state: str = "observacao"


@dataclass
class MarketSnapshot:
    symbol: str
    as_of: datetime
    last_price: float | None
    connected: bool
    source: str
    bars: dict[str, list[dict]] = field(default_factory=dict)
    levels: dict[str, list[PriceLevel]] = field(default_factory=dict)
    zones: dict[str, list[PriceZone]] = field(default_factory=dict)
    events: list[PO3Event] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    account: dict[str, float] = field(default_factory=dict)
    macro: dict = field(default_factory=dict)
