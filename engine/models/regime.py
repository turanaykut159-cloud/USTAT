"""Piyasa rejim veri modeli — v12.0 spesifikasyonu.

4 rejim:
    TREND    — ADX>25, EMA mesafesi artıyor, yön tutarlılığı
    RANGE    — ADX<20, BB dar, dar range
    VOLATILE — ATR>ort×2 VEYA spread>3x VEYA %2+ hareket
    OLAY     — TCMB/FED günü VEYA kur>%2 VEYA vade son 2 gün

Risk çarpanları:
    TREND=1.0, RANGE=0.7, VOLATILE=0.25, OLAY=0.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RegimeType(Enum):
    """Piyasa rejim tipleri (v12.0)."""
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

    def __post_init__(self) -> None:
        self.risk_multiplier = RISK_MULTIPLIERS.get(
            self.regime_type, 1.0
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
