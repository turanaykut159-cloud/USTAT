"""Stokastik spread modeli — VİOP backtest.

Rejim-farkındalıklı spread simülasyonu:
    Normal rejim:   spread = avg + |noise|,  noise ~ Normal(0, avg × σ_factor)
    Volatile rejim: spread = avg + |noise|,  noise ~ t(df=5) × avg × σ_factor

Tüm değerler tick cinsindendir.
"""

from __future__ import annotations

import numpy as np

from engine.logger import get_logger

logger = get_logger(__name__)


class SpreadModel:
    """Stokastik spread modeli.

    Args:
        base_spread: Tarihsel ortalama spread (tick).
        sigma_factor: Gürültü ölçeği — σ = base_spread × sigma_factor.
        volatile_df: t-dağılımı serbestlik derecesi (volatile rejim).
        seed: Tekrarlanabilirlik için rastgele tohum.
    """

    def __init__(
        self,
        base_spread: float = 0.5,
        sigma_factor: float = 0.3,
        volatile_df: int = 5,
        seed: int | None = None,
    ):
        self.base_spread = base_spread
        self.sigma_factor = sigma_factor
        self.volatile_df = volatile_df
        self._rng = np.random.default_rng(seed)

    # ── Ana hesaplama ───────────────────────────────────────────────

    def get_spread(
        self,
        price: float,
        volatility: float = 0.0,
        is_volatile: bool = False,
    ) -> float:
        """Mevcut koşullara göre spread hesapla.

        Args:
            price: Mevcut fiyat (geriye uyumluluk).
            volatility: Mevcut ATR / volatilite ölçüsü (geriye uyumluluk).
            is_volatile: ``True`` ise VOLATILE / OLAY rejimi — t-dağılımı
                         kullanılır.

        Returns:
            Hesaplanan spread (tick cinsinden, her zaman >= 1 tick).
        """
        sigma = self.base_spread * self.sigma_factor

        if is_volatile:
            # t-dağılımı (df=5): kalın kuyruklar
            noise = self._rng.standard_t(df=self.volatile_df) * sigma
        else:
            # Normal dağılım
            noise = self._rng.normal(0, sigma)

        spread = self.base_spread + abs(noise)
        return max(1.0, spread)  # minimum 1 tick

    # ── Yardımcılar ─────────────────────────────────────────────────

    def set_base_spread(self, avg_spread: float) -> None:
        """Tarihsel veriden hesaplanan ortalama spread'i güncelle.

        Args:
            avg_spread: Hesaplanan tarihsel ortalama spread.
        """
        self.base_spread = max(0.5, avg_spread)
