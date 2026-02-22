"""VİOP seans boşluk modeli — backtest.

Modeller:
    - Gece boşlukları (18:15 kapanış → 09:30 açılış)
    - Öğle boşlukları (12:30 → 14:00)
    - Boşluk SL tetiklenmesi: gap SL'den geçerse pozisyon
      olumsuz slippage ile kapatılır.

VİOP seans saatleri engine/utils/time_utils.py'den alınır.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from engine.utils.time_utils import (
    VIOP_OPEN,
    VIOP_CLOSE,
    VIOP_LUNCH_START,
    VIOP_LUNCH_END,
)


# ═════════════════════════════════════════════════════════════════════
#  VERİ MODELLERİ
# ═════════════════════════════════════════════════════════════════════


@dataclass
class GapEvent:
    """Bir seans boşluğunu temsil eder."""

    gap_type: str              # "overnight" veya "lunch"
    close_price: float         # Boşluk öncesi son fiyat
    open_price: float          # Boşluk sonrası ilk fiyat
    gap_size: float            # open_price - close_price (işaretli)
    gap_pct: float             # gap_size / close_price × 100
    close_time: datetime       # Boşluk öncesi zaman
    open_time: datetime        # Boşluk sonrası zaman


# ═════════════════════════════════════════════════════════════════════
#  SEANS MODELİ
# ═════════════════════════════════════════════════════════════════════


class SessionModel:
    """VİOP seans boşluk yönetimi.

    Barlar arasındaki boşlukları tespit eder ve açık pozisyonların
    stop-loss'larının boşluk tarafından tetiklenip tetiklenmediğini
    değerlendirir.
    """

    # Seans sınırları
    SESSION_OPEN: time = VIOP_OPEN          # 09:30
    SESSION_CLOSE: time = VIOP_CLOSE        # 18:15
    LUNCH_START: time = VIOP_LUNCH_START    # 12:30
    LUNCH_END: time = VIOP_LUNCH_END        # 14:00

    # Gap SL dolum varsayımı: açılış + olumsuz slippage
    GAP_SL_ADVERSE_TICKS: float = 2.0

    def __init__(self) -> None:
        self._last_bar_time: datetime | None = None
        self._last_close: float | None = None

    # ── Boşluk tespiti ──────────────────────────────────────────────

    def is_session_gap(
        self,
        prev_time: datetime,
        curr_time: datetime,
    ) -> str | None:
        """İki bar zaman damgası arasında seans boşluğu var mı?

        Args:
            prev_time: Önceki bar zaman damgası.
            curr_time: Mevcut bar zaman damgası.

        Returns:
            ``"overnight"`` gece boşluğu, ``"lunch"`` öğle boşluğu,
            ``None`` boşluk yok.
        """
        # Farklı günler → gece boşluğu
        if prev_time.date() != curr_time.date():
            return "overnight"

        # Aynı gün: önceki öğleden önce, sonraki öğleden sonra
        prev_t = prev_time.time()
        curr_t = curr_time.time()

        if prev_t <= self.LUNCH_START and curr_t >= self.LUNCH_END:
            return "lunch"

        return None

    def detect_gap(
        self,
        prev_close: float,
        curr_open: float,
        prev_time: datetime,
        curr_time: datetime,
    ) -> GapEvent | None:
        """Seans boşluğunu tespit ve ölç.

        Args:
            prev_close: Önceki barın kapanış fiyatı.
            curr_open: Mevcut barın açılış fiyatı.
            prev_time: Önceki barın zaman damgası.
            curr_time: Mevcut barın zaman damgası.

        Returns:
            ``GapEvent`` boşluk tespit edildiyse, ``None`` değilse.
        """
        gap_type = self.is_session_gap(prev_time, curr_time)
        if gap_type is None:
            return None

        gap_size = curr_open - prev_close
        gap_pct = (gap_size / prev_close * 100) if prev_close > 0 else 0.0

        return GapEvent(
            gap_type=gap_type,
            close_price=prev_close,
            open_price=curr_open,
            gap_size=gap_size,
            gap_pct=gap_pct,
            close_time=prev_time,
            open_time=curr_time,
        )

    # ── Gap SL kontrolü ────────────────────────────────────────────

    def check_gap_sl(
        self,
        gap: GapEvent,
        direction: str,
        sl: float,
        tick_size: float = 0.01,
    ) -> dict | None:
        """Boşluğun stop-loss tetikleyip tetiklemediğini kontrol et.

        BUY pozisyonlar: SL tetiklenir eğer gap açılışı SL'nin altında.
        SELL pozisyonlar: SL tetiklenir eğer gap açılışı SL'nin üstünde.

        Boşlukta SL tetiklendiğinde dolum fiyatı = gap açılış + olumsuz
        slippage (SL'den daha kötü).

        Args:
            gap: Tespit edilen boşluk olayı.
            direction: ``"BUY"`` veya ``"SELL"``.
            sl: Stop-loss fiyatı.
            tick_size: Minimum fiyat artışı.

        Returns:
            ``{"triggered": True, "fill_price": float, ...}`` SL
            tetiklendiyse, ``None`` tetiklenmediyse.
        """
        triggered = False
        fill_price = gap.open_price

        if direction == "BUY":
            # SL giriş altında. Gap SL altında açılırsa → tetiklenir.
            if gap.open_price <= sl:
                triggered = True
                # Long için olumsuz: daha düşük dolum
                fill_price = gap.open_price - self.GAP_SL_ADVERSE_TICKS * tick_size
        elif direction == "SELL":
            # SL giriş üstünde. Gap SL üstünde açılırsa → tetiklenir.
            if gap.open_price >= sl:
                triggered = True
                # Short için olumsuz: daha yüksek dolum
                fill_price = gap.open_price + self.GAP_SL_ADVERSE_TICKS * tick_size

        if triggered:
            return {
                "triggered": True,
                "fill_price": fill_price,
                "gap_type": gap.gap_type,
                "gap_size": gap.gap_size,
                "sl": sl,
            }
        return None

    # ── Seans kontrolü ──────────────────────────────────────────────

    def is_in_session(self, dt: datetime) -> bool:
        """Zaman damgasının işlem saatleri içinde olup olmadığını kontrol et.

        Öğle arası hariç tutulur.

        Args:
            dt: Kontrol edilecek zaman damgası.

        Returns:
            ``True`` işlem saatleri içinde ve öğle arası değilse.
        """
        t = dt.time()

        # Seans dışı
        if t < self.SESSION_OPEN or t > self.SESSION_CLOSE:
            return False

        # Öğle arası
        if self.LUNCH_START <= t <= self.LUNCH_END:
            return False

        # Hafta sonu
        if dt.weekday() >= 5:
            return False

        return True
