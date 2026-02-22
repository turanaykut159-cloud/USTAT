"""İşlem (trade) veri modeli.

State-machine akışı:
    SIGNAL → PENDING → SENT → FILLED / PARTIAL / TIMEOUT / REJECTED / CANCELLED
    TIMEOUT → MARKET_RETRY (TREND/RANGE) veya CANCELLED (VOLATILE/OLAY)
    MARKET_RETRY → FILLED / REJECTED
    PARTIAL → FILLED (≥%50 dolum kabul) veya CANCELLED (<50%)
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class TradeState(Enum):
    """Emir state-machine durumları."""
    IDLE = "idle"                  # başlangıç (legacy)
    SIGNAL = "signal"              # sinyal oluştu, BABA onay bekliyor
    PENDING = "pending"            # BABA onayladı, pre-flight kontrolleri
    SENT = "sent"                  # LIMIT emir MT5'e gönderildi
    FILLED = "filled"              # emir tamamen doldu, pozisyon aktif
    PARTIAL = "partial"            # kısmi dolum tespit edildi
    TIMEOUT = "timeout"            # LIMIT emir zaman aşımı
    MARKET_RETRY = "market_retry"  # market emir ile yeniden deneme
    REJECTED = "rejected"          # emir reddedildi (MT5 veya slippage)
    CLOSED = "closed"              # pozisyon kapatıldı
    CANCELLED = "cancelled"        # emir iptal edildi


@dataclass
class Trade:
    """Tek bir işlemi temsil eder."""
    symbol: str
    direction: str  # "BUY" veya "SELL"
    volume: float
    entry_price: float = 0.0
    exit_price: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    pnl: float = 0.0
    state: TradeState = TradeState.IDLE
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    ticket: int = 0
    strategy: str = ""           # "trend_follow", "mean_reversion", "breakout"
    trailing_sl: float = 0.0     # güncel trailing stop seviyesi
    db_id: int = 0               # DB satır id'si (update için)
    # ── State-machine alanları ──────────────────────────────────
    order_ticket: int = 0             # bekleyen emir ticket (pozisyon ticket'inden farklı)
    sent_at: datetime | None = None   # LIMIT emri gönderilme zamanı
    requested_volume: float = 0.0     # istenen lot (partial fill takibi)
    filled_volume: float = 0.0        # dolmuş lot miktarı
    limit_price: float = 0.0          # LIMIT emri fiyatı
    regime_at_entry: str = ""         # emir oluşturulurken rejim ("TREND", "RANGE", vb.)
    cancel_reason: str = ""           # iptal/red nedeni
    retry_count: int = 0              # market retry sayısı (max 1)
    max_slippage: float = 0.0         # kabul edilebilir maks slippage
