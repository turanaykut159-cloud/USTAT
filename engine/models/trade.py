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
    source: str = ""             # "app" (ManuelMotor UI), "mt5_direct" (MT5 terminali), "" (otomatik/eski)
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
    # ── Evrensel pozisyon yönetimi alanları ────────────────────
    peak_profit: float = 0.0          # ulaşılan en yüksek kâr (puan cinsinden)
    tp1_hit: bool = False             # TP1 tetiklendi mi (yarı kapanış)
    tp1_price: float = 0.0           # TP1 tetiklenme fiyatı
    cost_averaged: bool = False       # maliyetlendirme yapıldı mı
    initial_volume: float = 0.0      # TP1/ekleme öncesi orijinal lot
    breakeven_hit: bool = False       # breakeven seviyesi çekildi mi
    voting_score: int = 0            # anlık 4-gösterge oylama skoru (0-4)
    flat_candle_count: int = 0       # yatay mum sayacı (2 saat kontrol)
    # ── R-Multiple tracking (Van Tharp) ──────────────────────────
    initial_risk: float = 0.0        # 1R = |entry_price - initial_SL| × volume × contract_size
    r_multiple: float = 0.0          # anlık PnL / initial_risk
    r_multiple_at_close: float = 0.0 # kapanıştaki R-multiple (final)
    # ── Pyramiding (Turtle-style add to winners) ─────────────────
    pyramid_count: int = 0           # ekleme sayısı (max PYRAMID_MAX_ADDS)
    pyramid_prices: str = ""         # ekleme fiyatları (virgülle ayrılmış)
    # ── Maximum hold time ────────────────────────────────────────
    max_hold_warned: bool = False    # max süre uyarısı verildi mi
