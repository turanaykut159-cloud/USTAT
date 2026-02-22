"""Monte Carlo permütasyon motoru — backtest dayanıklılık analizi.

İşlem P&L dizisini 1000 kez karıştırır, equity curve hesaplar
ve %95 güvenle DD < %15 kontrolü yapar.

Kullanım:
    mc = MonteCarloEngine(trades, initial_capital=100_000)
    result = mc.run()
    print(result.passed)           # True / False
    print(result.percentile_95_dd) # 0.12 → %12
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from engine.logger import get_logger

logger = get_logger(__name__)


# ── Varsayılanlar ───────────────────────────────────────────────────

DEFAULT_PERMUTATIONS: int = 1000
DEFAULT_CONFIDENCE: float = 0.95        # %95 yüzdelik dilim
DEFAULT_MAX_DD_THRESHOLD: float = 0.15  # %15


# ═════════════════════════════════════════════════════════════════════
#  VERİ MODELİ
# ═════════════════════════════════════════════════════════════════════


@dataclass
class MonteCarloResult:
    """Monte Carlo simülasyon sonuçları."""

    n_permutations: int
    n_trades: int
    original_max_dd: float
    percentile_95_dd: float
    percentile_99_dd: float
    mean_dd: float
    median_dd: float
    max_dd_distribution: list[float]    # Tüm maks DD'ler
    passed: bool                        # %95 DD < eşik
    threshold: float
    original_final_equity: float
    mean_final_equity: float
    percentile_5_final_equity: float


# ═════════════════════════════════════════════════════════════════════
#  MONTE CARLO MOTORU
# ═════════════════════════════════════════════════════════════════════


class MonteCarloEngine:
    """Monte Carlo permütasyon analizi.

    Yaklaşım:
        1. Tamamlanan işlemlerden P&L dizisini çıkar.
        2. P&L sırasını N kez karıştır (varsayılan 1000).
        3. Her permütasyonda kümülatif equity ve maks DD hesapla.
        4. Maks drawdown'ların %95 yüzdelik dilimini hesapla.
        5. %95 DD < %15 ise GEÇTİ.

    Args:
        trades: İşlem sözlükleri listesi (``"pnl"`` anahtarı gerekli).
        initial_capital: Başlangıç sermayesi (TRY).
        n_permutations: Permütasyon sayısı.
        confidence: Güven düzeyi (0-1).
        max_dd_threshold: Maksimum kabul edilebilir DD oranı.
        seed: Tekrarlanabilirlik için rastgele tohum.
    """

    def __init__(
        self,
        trades: list[dict],
        initial_capital: float = 100_000,
        n_permutations: int = DEFAULT_PERMUTATIONS,
        confidence: float = DEFAULT_CONFIDENCE,
        max_dd_threshold: float = DEFAULT_MAX_DD_THRESHOLD,
        seed: int | None = 42,
    ):
        self.trades = trades
        self.initial_capital = initial_capital
        self.n_permutations = n_permutations
        self.confidence = confidence
        self.max_dd_threshold = max_dd_threshold
        self._rng = np.random.default_rng(seed)

    # ── Yardımcı ────────────────────────────────────────────────────

    @staticmethod
    def _compute_max_drawdown(equity_curve: np.ndarray) -> float:
        """Zirve equity'nin oranı olarak maks drawdown hesapla."""
        if len(equity_curve) == 0:
            return 0.0
        peak = np.maximum.accumulate(equity_curve)
        drawdown = (peak - equity_curve) / peak
        return float(np.max(drawdown)) if len(drawdown) > 0 else 0.0

    # ── Ana çalıştırma ──────────────────────────────────────────────

    def run(self) -> MonteCarloResult:
        """Monte Carlo permütasyon analizini çalıştır.

        Returns:
            ``MonteCarloResult`` — DD dağılımı ve geçti/kaldı bilgisi.
        """
        pnls = np.array(
            [t.get("pnl", 0.0) for t in self.trades], dtype=np.float64,
        )
        n_trades = len(pnls)

        if n_trades < 5:
            logger.warning(
                "Monte Carlo: anlamlı analiz için yeterli işlem yok "
                f"({n_trades} < 5)",
            )
            return MonteCarloResult(
                n_permutations=0,
                n_trades=n_trades,
                original_max_dd=0.0,
                percentile_95_dd=0.0,
                percentile_99_dd=0.0,
                mean_dd=0.0,
                median_dd=0.0,
                max_dd_distribution=[],
                passed=False,
                threshold=self.max_dd_threshold,
                original_final_equity=self.initial_capital,
                mean_final_equity=self.initial_capital,
                percentile_5_final_equity=self.initial_capital,
            )

        # Orijinal equity curve
        original_equity = self.initial_capital + np.cumsum(pnls)
        original_equity = np.insert(original_equity, 0, self.initial_capital)
        original_max_dd = self._compute_max_drawdown(original_equity)

        # Permütasyonlar
        max_dds = np.empty(self.n_permutations, dtype=np.float64)
        final_equities = np.empty(self.n_permutations, dtype=np.float64)

        for k in range(self.n_permutations):
            shuffled = self._rng.permutation(pnls)
            equity = self.initial_capital + np.cumsum(shuffled)
            equity = np.insert(equity, 0, self.initial_capital)
            max_dds[k] = self._compute_max_drawdown(equity)
            final_equities[k] = equity[-1]

        percentile_idx = int(self.confidence * 100)
        percentile_95_dd = float(np.percentile(max_dds, percentile_idx))
        percentile_99_dd = float(np.percentile(max_dds, 99))

        passed = percentile_95_dd < self.max_dd_threshold

        result = MonteCarloResult(
            n_permutations=self.n_permutations,
            n_trades=n_trades,
            original_max_dd=original_max_dd,
            percentile_95_dd=percentile_95_dd,
            percentile_99_dd=percentile_99_dd,
            mean_dd=float(np.mean(max_dds)),
            median_dd=float(np.median(max_dds)),
            max_dd_distribution=sorted(max_dds.tolist()),
            passed=passed,
            threshold=self.max_dd_threshold,
            original_final_equity=float(original_equity[-1]),
            mean_final_equity=float(np.mean(final_equities)),
            percentile_5_final_equity=float(np.percentile(final_equities, 5)),
        )

        logger.info(
            f"Monte Carlo: {n_trades} islem, {self.n_permutations} perm, "
            f"%95 DD={percentile_95_dd:.2%}, esik={self.max_dd_threshold:.0%}, "
            f"GECTI={passed}",
        )

        return result
