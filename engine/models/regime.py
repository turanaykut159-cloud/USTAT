"""Piyasa rejim veri modeli — v14.0 spesifikasyonu.

4 rejim:
    TREND    — ADX>25, EMA mesafesi artıyor, yön tutarlılığı
    RANGE    — ADX<20, BB dar, dar range
    VOLATILE — ATR>ort×2.5 VEYA spread>normal×4 VEYA %2.5+ hareket
    OLAY     — TCMB/FED günü (12:00-15:30) VEYA kur>%2 VEYA vade son 2 gün

Risk çarpanları:
    TREND=1.0, RANGE=0.7, VOLATILE=0.25, OLAY=0.0

Rejim → aktif strateji eşleme:
    TREND=[TREND_FOLLOW, BREAKOUT], RANGE=[MEAN_REVERSION, BREAKOUT],
    VOLATILE=[], OLAY=[]

v14 değişiklikleri:
    - TREND rejimine BREAKOUT eklendi (güçlü trend kırılımları)
    - VOLATILE: yeni sinyal yok ama kârdaki pozisyonlar trailing ile korunur
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from engine.models.signal import StrategyType


class RegimeType(Enum):
    """Piyasa rejim tipleri (v14.0)."""
    TREND    = "TREND"
    RANGE    = "RANGE"
    VOLATILE = "VOLATILE"
    OLAY     = "OLAY"


# Rejim → risk çarpanı
RISK_MULTIPLIERS: dict[RegimeType, float] = {
    RegimeType.TREND:    1.0,
    RegimeType.RANGE:    0.7,
    RegimeType.VOLATILE: 0.25,
    RegimeType.OLAY:     0.0,
}

# Rejim → izin verilen stratejiler (risk kararı — BABA otoritesi)
REGIME_STRATEGIES: dict[RegimeType, list[StrategyType]] = {
    RegimeType.TREND:    [StrategyType.TREND_FOLLOW, StrategyType.BREAKOUT],
    RegimeType.RANGE:    [StrategyType.MEAN_REVERSION, StrategyType.BREAKOUT],
    RegimeType.VOLATILE: [],    # tüm sinyaller durur
    RegimeType.OLAY:     [],    # sistem pause
}


@dataclass
class Regime:
    """Piyasa rejimi."""
    regime_type: RegimeType
    confidence: float = 0.0
    risk_multiplier: float = 1.0
    adx_value: float = 0.0
    atr_ratio: float = 0.0
    bb_width_ratio: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    allowed_strategies: list[StrategyType] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.risk_multiplier = RISK_MULTIPLIERS.get(
            self.regime_type, 1.0
        )
        self.allowed_strategies = list(
            REGIME_STRATEGIES.get(self.regime_type, [])
        )


@dataclass
class EarlyWarning:
    """Erken uyarı sinyali."""
    warning_type: str       # SPREAD_SPIKE, PRICE_SHOCK, VOLUME_SPIKE, USDTRY_SHOCK
    symbol: str
    severity: str           # WARNING, CRITICAL
    value: float            # tetikleyen değer
    threshold: float        # eşik değeri
    liquidity_class: str    # A, B, C
    message: str = ""
