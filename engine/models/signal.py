"""Sinyal veri modeli."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class SignalType(Enum):
    """Sinyal tipi."""
    BUY = "buy"
    SELL = "sell"
    CLOSE_BUY = "close_buy"
    CLOSE_SELL = "close_sell"


class StrategyType(Enum):
    """Sinyal strateji tipi."""
    TREND_FOLLOW = "trend_follow"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"


@dataclass
class Signal:
    """Trading sinyali."""
    symbol: str
    signal_type: SignalType
    price: float
    sl: float
    tp: float
    strength: float = 0.0  # 0-1 arası sinyal gücü
    timestamp: datetime = None
    reason: str = ""
    strategy: StrategyType = StrategyType.TREND_FOLLOW

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
