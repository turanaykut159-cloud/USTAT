"""Walk-forward out-of-sample doğrulama motoru.

Varsayılan: 4 ay IS (In-Sample) + 2 ay OOS (Out-of-Sample),
minimum 3 pencere.

Her pencere tam bir BacktestRunner çalıştırır ve OOS sonuçlarını
toplar.

Kullanım:
    wf = WalkForwardEngine(data, config)
    result = wf.run()
    print(result.passed)
    print(result.aggregate_metrics)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import numpy as np

from engine.logger import get_logger
from backtest.runner import BacktestRunner
from backtest.report import BacktestReport

logger = get_logger(__name__)


# ── Sabitler ────────────────────────────────────────────────────────

DEFAULT_IS_MONTHS: int = 4      # In-sample eğitim penceresi
DEFAULT_OOS_MONTHS: int = 2     # Out-of-sample test penceresi
MIN_WINDOWS: int = 3            # Minimum gerekli pencere


# ═════════════════════════════════════════════════════════════════════
#  VERİ MODELLERİ
# ═════════════════════════════════════════════════════════════════════


@dataclass
class WalkForwardWindow:
    """Tek bir walk-forward pencere sonucu."""

    window_id: int
    is_start: str
    is_end: str
    oos_start: str
    oos_end: str
    is_report: BacktestReport
    oos_report: BacktestReport
    oos_metrics: dict[str, Any]


@dataclass
class WalkForwardResult:
    """Toplu walk-forward sonuçları."""

    windows: list[WalkForwardWindow]
    combined_oos_trades: list[dict]
    combined_oos_equity: list[float]
    aggregate_metrics: dict[str, Any]
    passed: bool    # Tüm pencereler pozitif beklenti gösteriyor mu


# ═════════════════════════════════════════════════════════════════════
#  WALK-FORWARD MOTORU
# ═════════════════════════════════════════════════════════════════════


class WalkForwardEngine:
    """Walk-forward out-of-sample doğrulama.

    Veriyi [IS_1 | OOS_1] [IS_2 | OOS_2] ... [IS_N | OOS_N] olarak böler.
    Her IS 4 ay, OOS 2 ay. Pencereler OOS periyodu kadar ilerler.

    Args:
        data: Tam OHLCV DataFrame.
        config: BacktestRunner konfigürasyonu.
        is_months: In-sample ay sayısı.
        oos_months: Out-of-sample ay sayısı.
        min_windows: Minimum gerekli pencere sayısı.
    """

    def __init__(
        self,
        data: pd.DataFrame,
        config: dict | None = None,
        is_months: int = DEFAULT_IS_MONTHS,
        oos_months: int = DEFAULT_OOS_MONTHS,
        min_windows: int = MIN_WINDOWS,
    ):
        self.data = data
        self.config = config or {}
        self.is_months = is_months
        self.oos_months = oos_months
        self.min_windows = min_windows

    # ── Pencere bölme ───────────────────────────────────────────────

    def _split_windows(self) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
        """Veriyi IS/OOS pencere çiftlerine böl.

        Returns:
            ``(is_data, oos_data)`` DataFrame çiftleri listesi.
        """
        ts_col = "timestamp" if "timestamp" in self.data.columns else "time"
        df = self.data.copy()
        df[ts_col] = pd.to_datetime(df[ts_col])

        start = df[ts_col].min()
        end = df[ts_col].max()

        windows: list[tuple[pd.DataFrame, pd.DataFrame]] = []
        current_start = start

        while True:
            is_end = current_start + pd.DateOffset(months=self.is_months)
            oos_end = is_end + pd.DateOffset(months=self.oos_months)

            if oos_end > end:
                break

            is_mask = (df[ts_col] >= current_start) & (df[ts_col] < is_end)
            oos_mask = (df[ts_col] >= is_end) & (df[ts_col] < oos_end)

            is_data = df[is_mask].copy()
            oos_data = df[oos_mask].copy()

            if len(is_data) > 100 and len(oos_data) > 50:
                windows.append((is_data, oos_data))

            # OOS periyodu kadar ilerle
            current_start += pd.DateOffset(months=self.oos_months)

        return windows

    # ── Ana çalıştırma ──────────────────────────────────────────────

    def run(self) -> WalkForwardResult:
        """Walk-forward doğrulamayı çalıştır.

        Returns:
            ``WalkForwardResult`` — pencere bazlı ve toplu metrikler.

        Raises:
            ValueError: Yeterli pencere oluşturulamazsa.
        """
        windows = self._split_windows()

        if len(windows) < self.min_windows:
            raise ValueError(
                f"Yetersiz veri: sadece {len(windows)} pencere "
                f"(gereken {self.min_windows}). "
                f"Daha fazla veri sağlayın veya pencere boyutlarını küçültün.",
            )

        results: list[WalkForwardWindow] = []
        combined_oos_trades: list[dict] = []
        combined_oos_equity: list[float] = []

        ts_col = "timestamp" if "timestamp" in self.data.columns else "time"

        for idx, (is_data, oos_data) in enumerate(windows):
            logger.info(
                f"Walk-forward pencere {idx + 1}/{len(windows)}: "
                f"IS={is_data[ts_col].min()} → {is_data[ts_col].max()}, "
                f"OOS={oos_data[ts_col].min()} → {oos_data[ts_col].max()}",
            )

            # IS backtest (referans için)
            is_runner = BacktestRunner(is_data, self.config)
            is_report = is_runner.run()

            # OOS backtest (gerçek doğrulama)
            oos_runner = BacktestRunner(oos_data, self.config)
            oos_report = oos_runner.run()

            oos_metrics = oos_report.summary()

            wf_window = WalkForwardWindow(
                window_id=idx + 1,
                is_start=str(is_data[ts_col].min()),
                is_end=str(is_data[ts_col].max()),
                oos_start=str(oos_data[ts_col].min()),
                oos_end=str(oos_data[ts_col].max()),
                is_report=is_report,
                oos_report=oos_report,
                oos_metrics=oos_metrics,
            )
            results.append(wf_window)

            combined_oos_trades.extend(oos_report.trades)
            combined_oos_equity.extend(oos_report.equity_curve)

        # Toplu metrikler
        all_pnls = [t.get("pnl", 0) for t in combined_oos_trades]
        win_count = sum(1 for p in all_pnls if p > 0)

        windows_profitable = sum(
            1 for w in results if w.oos_metrics.get("total_pnl", 0) > 0
        )

        aggregate: dict[str, Any] = {
            "total_windows": len(results),
            "total_oos_trades": len(combined_oos_trades),
            "combined_pnl": sum(all_pnls),
            "combined_win_rate": (
                win_count / len(all_pnls) * 100 if all_pnls else 0
            ),
            "windows_profitable": windows_profitable,
            "oos_consistency": windows_profitable / len(results) * 100,
        }

        # Geçiş kriteri: en az %60 pencere kârlı
        passed = aggregate["oos_consistency"] >= 60.0

        return WalkForwardResult(
            windows=results,
            combined_oos_trades=combined_oos_trades,
            combined_oos_equity=combined_oos_equity,
            aggregate_metrics=aggregate,
            passed=passed,
        )
