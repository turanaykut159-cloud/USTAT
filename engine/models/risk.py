"""Risk yönetimi veri modelleri.

RiskParams      — Tüm risk parametrelerini tanımlar.
RiskVerdict     — check_risk_limits() dönüş tipi.
FakeLayerResult — Fake sinyal tek katman sonucu.
FakeAnalysis    — Fake sinyal 4 katmanlı analiz sonucu.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RiskParams:
    """Risk parametreleri."""

    # ── Mevcut alanlar (değiştirilmiyor) ────────────────────────────
    max_position_size: float = 1.0
    max_daily_loss: float = 0.025       # v14: %1.8→%2.5 günlük max kayıp
    max_total_drawdown: float = 0.10    # %10 toplam max drawdown
    risk_per_trade: float = 0.01        # %1 işlem başına risk
    max_open_positions: int = 5
    max_correlated_positions: int = 3

    # ── Çok katmanlı kayıp limitleri ────────────────────────────────
    max_weekly_loss: float = 0.04       # %4 haftalık → lot %50 azalt
    max_monthly_loss: float = 0.07      # %7 aylık → sistem dur
    hard_drawdown: float = 0.15         # %15 hard drawdown → tam kapanış
    max_floating_loss: float = 0.020    # v14: %1.5→%2.0 floating loss → yeni işlem engeli
    max_daily_trades: int = 8           # v14: 5→8 günlük max işlem sayısı (sadece otomatik)
    max_daily_manual_trades: int = 10   # v5.9.3 — BULGU #3: manuel işlemler için ayrı günlük sayac
    max_risk_per_trade_hard: float = 0.02  # tek işlem max %2 (hard cap)
    consecutive_loss_limit: int = 3     # üst üste kayıp → cooldown
    cooldown_hours: int = 2             # v14: 4→2 saat cool-down süresi

    # ── Korelasyon limitleri ────────────────────────────────────────
    max_same_direction: int = 3         # aynı yönde max pozisyon
    max_same_sector_direction: int = 2  # aynı sektörde aynı yönde max
    max_index_weight_score: float = 0.25  # endeks ağırlık skoru limiti

    # ── ÜSTAT bildirim kuyruğu ────────────────────────────────────
    # ÜSTAT parametreleri değiştirdiğinde buraya mesaj ekler.
    # BABA her cycle başında bu kuyruğu okur ve loglar, sonra temizler.
    ustat_notifications: list[str] = field(default_factory=list)


@dataclass
class RiskVerdict:
    """check_risk_limits() dönüş tipi.

    Attributes:
        can_trade: True ise yeni işlem açılabilir.
        lot_multiplier: Lot çarpanı (1.0=normal, 0.5=yarılama, 0.0=dur).
        reason: Engel nedeni (boş ise engel yok).
        kill_switch_level: Aktif kill-switch seviyesi (0=yok).
        blocked_symbols: L1 ile durdurulmuş semboller.
        details: Ek detaylar.
    """
    can_trade: bool = True
    lot_multiplier: float = 1.0
    risk_multiplier: float = 1.0   # v5.9.2: sürekli risk çarpanı [0.0-1.0]
    reason: str = ""
    kill_switch_level: int = 0
    blocked_symbols: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeLayerResult:
    """Fake sinyal analizi — tek katman sonucu.

    Attributes:
        name: Katman adı ("volume", "spread", "multi_tf", "momentum").
        triggered: True ise bu katman FAKE olarak işaretledi.
        weight: Katman ağırlığı (1 veya 2).
        score: Tetiklendiyse weight, değilse 0.
        details: Açıklama metni.
    """
    name: str
    triggered: bool
    weight: int
    score: int
    details: str = ""


@dataclass
class FakeAnalysis:
    """Fake sinyal analizi — tek pozisyon için 4 katmanlı sonuç.

    Attributes:
        symbol: Kontrat sembolü.
        direction: Pozisyon yönü ("BUY" / "SELL").
        ticket: MT5 pozisyon ticket numarası.
        volume_layer: Hacim katmanı sonucu.
        spread_layer: Spread katmanı sonucu.
        multi_tf_layer: Çoklu zaman dilimi katmanı sonucu.
        momentum_layer: Momentum katmanı sonucu.
    """
    symbol: str
    direction: str
    ticket: int
    volume_layer: FakeLayerResult = field(
        default_factory=lambda: FakeLayerResult("volume", False, 1, 0),
    )
    spread_layer: FakeLayerResult = field(
        default_factory=lambda: FakeLayerResult("spread", False, 2, 0),
    )
    multi_tf_layer: FakeLayerResult = field(
        default_factory=lambda: FakeLayerResult("multi_tf", False, 1, 0),
    )
    momentum_layer: FakeLayerResult = field(
        default_factory=lambda: FakeLayerResult("momentum", False, 2, 0),
    )

    @property
    def total_score(self) -> int:
        """Toplam fake skor (max 6)."""
        return (
            self.volume_layer.score
            + self.spread_layer.score
            + self.multi_tf_layer.score
            + self.momentum_layer.score
        )
