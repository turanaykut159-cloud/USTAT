"""Slippage modeli — VİOP backtest.

Rejim-farkındalıklı Normal dağılım slippage simülasyonu:
    Normal rejim:   ~ Normal(mu=1 tick, sigma=0.5)
    Volatile rejim: ~ Normal(mu=3 tick, sigma=2)
    Market emri:    2x çarpan

Tüm değerler tick cinsindendir.
"""

from __future__ import annotations

import numpy as np

from engine.logger import get_logger

logger = get_logger(__name__)


class SlippageModel:
    """Slippage modeli — Normal dağılım tabanlı.

    Sınıf özellikleri (class attributes) sensitivity testi için
    monkey-patch ile değiştirilebilir.
    """

    # ── Sabitler (sensitivity testi için class attribute) ────────
    NORMAL_MU: float = 1.0
    NORMAL_SIGMA: float = 0.5
    VOLATILE_MU: float = 3.0
    VOLATILE_SIGMA: float = 2.0
    MARKET_ORDER_MULT: float = 2.0

    def __init__(
        self,
        mean_slippage: float = 1.0,
        max_slippage: float = 10.0,
        seed: int | None = None,
    ):
        self.mean_slippage = mean_slippage
        self.max_slippage = max_slippage
        self._rng = np.random.default_rng(seed)

    # ── Ana hesaplama ───────────────────────────────────────────────

    def get_slippage(
        self,
        volume: float = 1.0,
        liquidity: float = 1.0,
        is_volatile: bool = False,
        is_market_order: bool = False,
    ) -> float:
        """Slippage hesapla (tick cinsinden).

        Args:
            volume: İşlem hacmi (lot) — geriye uyumluluk.
            liquidity: Likidite çarpanı — geriye uyumluluk.
            is_volatile: ``True`` ise VOLATILE / OLAY rejimi.
            is_market_order: ``True`` ise market emri (2x çarpan).

        Returns:
            Slippage (tick), her zaman >= 0, max_slippage ile sınırlı.
        """
        if is_volatile:
            mu, sigma = self.VOLATILE_MU, self.VOLATILE_SIGMA
        else:
            mu, sigma = self.NORMAL_MU, self.NORMAL_SIGMA

        slippage = self._rng.normal(mu, sigma)
        slippage = abs(slippage)  # slippage her zaman pozitif

        if is_market_order:
            slippage *= self.MARKET_ORDER_MULT

        return min(slippage, self.max_slippage)
