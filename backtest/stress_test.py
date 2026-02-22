"""Tarihsel stres testi senaryoları — VİOP backtest.

Önceden tanımlı dönemler:
    - 2020 Mart (COVID çöküşü)
    - 2023 Seçim (Türkiye genel seçimi)
    - 2024 TCMB şokları (Merkez Bankası faiz kararları)

Ek olarak rejim kayma testi (regime drift) içerir.

Kullanım:
    st = StressTestEngine(data, config)
    results = st.run_all()
    drift = st.run_regime_drift_test()
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import numpy as np

from engine.logger import get_logger
from backtest.runner import BacktestRunner
from backtest.report import BacktestReport

logger = get_logger(__name__)


# ═════════════════════════════════════════════════════════════════════
#  VERİ MODELLERİ
# ═════════════════════════════════════════════════════════════════════


@dataclass
class StressScenario:
    """Stres testi senaryo tanımı."""

    name: str
    description: str
    start_date: str           # "YYYY-MM-DD"
    end_date: str             # "YYYY-MM-DD"
    max_allowed_dd: float     # Kabul edilebilir maks drawdown
    category: str             # "crisis", "election", "central_bank", "regime_drift"


@dataclass
class StressTestResult:
    """Tek bir stres senaryosunun sonucu."""

    scenario: StressScenario
    report: BacktestReport | None
    metrics: dict[str, Any]
    max_drawdown: float
    total_pnl: float
    n_trades: int
    passed: bool
    data_available: bool      # Tarih aralığında veri yoksa False
    error: str | None = None


# ═════════════════════════════════════════════════════════════════════
#  ÖN TANIMLI SENARYOLAR
# ═════════════════════════════════════════════════════════════════════

STRESS_SCENARIOS: list[StressScenario] = [
    StressScenario(
        name="COVID_2020",
        description="2020 Mart COVID krizi — global piyasa cokusu",
        start_date="2020-02-15",
        end_date="2020-04-30",
        max_allowed_dd=0.20,
        category="crisis",
    ),
    StressScenario(
        name="ELECTION_2023",
        description="2023 Mayis Turkiye genel secimi",
        start_date="2023-04-15",
        end_date="2023-06-30",
        max_allowed_dd=0.15,
        category="election",
    ),
    StressScenario(
        name="TCMB_2024",
        description="2024 TCMB faiz kararlari ve kur soklari",
        start_date="2024-01-01",
        end_date="2024-06-30",
        max_allowed_dd=0.15,
        category="central_bank",
    ),
]


# ═════════════════════════════════════════════════════════════════════
#  STRES TEST MOTORU
# ═════════════════════════════════════════════════════════════════════


class StressTestEngine:
    """Önceden tanımlı stres dönemleri üzerinde backtest çalıştır.

    Her senaryo için:
        1. Veriyi senaryonun tarih aralığına filtrele
        2. BacktestRunner çalıştır
        3. Maks DD'yi eşikle karşılaştır
        4. Geçti/kaldı raporla

    Args:
        data: Tam OHLCV DataFrame.
        config: BacktestRunner konfigürasyonu.
        scenarios: Senaryo listesi (varsayılan: ``STRESS_SCENARIOS``).
    """

    def __init__(
        self,
        data: pd.DataFrame,
        config: dict | None = None,
        scenarios: list[StressScenario] | None = None,
    ):
        self.data = data
        self.config = config or {}
        self.scenarios = scenarios or STRESS_SCENARIOS

    # ── Veri filtreleme ──────────────────────────────────────────────

    def _filter_data(self, scenario: StressScenario) -> pd.DataFrame:
        """Veriyi senaryo tarih aralığına filtrele."""
        ts_col = "timestamp" if "timestamp" in self.data.columns else "time"
        df = self.data.copy()
        df[ts_col] = pd.to_datetime(df[ts_col])

        start = pd.Timestamp(scenario.start_date)
        end = pd.Timestamp(scenario.end_date)

        mask = (df[ts_col] >= start) & (df[ts_col] <= end)
        return df[mask].copy()

    # ── Tek senaryo çalıştırma ──────────────────────────────────────

    def run_scenario(self, scenario: StressScenario) -> StressTestResult:
        """Tek bir stres senaryosunu çalıştır.

        Args:
            scenario: Çalıştırılacak senaryo.

        Returns:
            ``StressTestResult`` — metrikler ve geçti/kaldı bilgisi.
        """
        logger.info(
            f"Stres test: {scenario.name} "
            f"({scenario.start_date} — {scenario.end_date})",
        )

        filtered = self._filter_data(scenario)

        if len(filtered) < 50:
            logger.warning(
                f"{scenario.name} icin yetersiz veri: {len(filtered)} bar",
            )
            return StressTestResult(
                scenario=scenario,
                report=None,
                metrics={"total_trades": 0},
                max_drawdown=0.0,
                total_pnl=0.0,
                n_trades=0,
                passed=False,
                data_available=False,
                error="Tarih araliginda yetersiz veri",
            )

        try:
            runner = BacktestRunner(filtered, self.config)
            report = runner.run()
        except Exception as e:
            logger.error(f"Stres test {scenario.name} hatasi: {e}")
            return StressTestResult(
                scenario=scenario,
                report=None,
                metrics={"total_trades": 0},
                max_drawdown=0.0,
                total_pnl=0.0,
                n_trades=0,
                passed=False,
                data_available=True,
                error=str(e),
            )

        metrics = report.summary()

        max_dd = metrics.get("max_drawdown", 0.0)
        total_pnl = metrics.get("total_pnl", 0.0)
        passed = max_dd < scenario.max_allowed_dd

        logger.info(
            f"Stres test {scenario.name}: DD={max_dd:.2%}, "
            f"PnL={total_pnl:.2f}, GECTI={passed}",
        )

        return StressTestResult(
            scenario=scenario,
            report=report,
            metrics=metrics,
            max_drawdown=max_dd,
            total_pnl=total_pnl,
            n_trades=metrics.get("total_trades", 0),
            passed=passed,
            data_available=True,
        )

    # ── Tüm senaryoları çalıştır ────────────────────────────────────

    def run_all(self) -> list[StressTestResult]:
        """Tüm stres senaryolarını çalıştır.

        Returns:
            Senaryo sonuçları listesi.
        """
        results: list[StressTestResult] = []
        for scenario in self.scenarios:
            result = self.run_scenario(scenario)
            results.append(result)
        return results

    # ── Rejim kayma testi ───────────────────────────────────────────

    def run_regime_drift_test(self) -> list[StressTestResult]:
        """Rejim değişiklikleri arasında strateji dayanıklılığını test et.

        Yaklaşım:
            1. Tam veri setini çeyreklere böl.
            2. Her çeyrekte ayrı backtest çalıştır.
            3. Çeyrekler arası performansı karşılaştır.
            4. Herhangi bir çeyrek en iyi çeyreğin %50'sinden
               kötüyse FAIL.

        Bu, stratejinin tek bir rejime aşırı uydurulmadığını
        test eder.

        Returns:
            Çeyrek bazlı sonuçlar listesi.
        """
        ts_col = "timestamp" if "timestamp" in self.data.columns else "time"
        df = self.data.copy()
        df[ts_col] = pd.to_datetime(df[ts_col])

        start = df[ts_col].min()
        end = df[ts_col].max()
        total_days = (end - start).days
        quarter_days = total_days // 4

        if quarter_days < 30:
            logger.warning("Rejim kayma testi icin yetersiz veri")
            return []

        results: list[StressTestResult] = []

        for q in range(4):
            q_start = start + pd.Timedelta(days=q * quarter_days)
            q_end = q_start + pd.Timedelta(days=quarter_days)

            scenario = StressScenario(
                name=f"REGIME_DRIFT_Q{q + 1}",
                description=f"Rejim kayma testi ceyrek {q + 1}",
                start_date=q_start.strftime("%Y-%m-%d"),
                end_date=q_end.strftime("%Y-%m-%d"),
                max_allowed_dd=0.15,
                category="regime_drift",
            )

            result = self.run_scenario(scenario)
            results.append(result)

        # Kayma kontrolü: herhangi bir çeyrek PnL < en iyi çeyreğin %50'si
        pnls = [r.total_pnl for r in results if r.data_available]
        if pnls:
            best_pnl = max(pnls)
            for r in results:
                if r.data_available and best_pnl > 0:
                    if r.total_pnl < best_pnl * 0.5:
                        r.passed = False
                        logger.warning(
                            f"Rejim kaymasi: {r.scenario.name} "
                            f"PnL={r.total_pnl:.2f} < %50 × en iyi "
                            f"({best_pnl:.2f})",
                        )

        return results
