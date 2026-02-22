"""Parametre hassasiyet analizi — backtest.

Her strateji parametresini +/-%20 değiştirerek strateji
dayanıklılığını test eder.

Kullanım:
    sens = SensitivityEngine(data, config)
    result = sens.run()
    print(result.overall_resilient)
    print(result.sensitive_params)
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from engine.logger import get_logger
from backtest.runner import BacktestRunner
from backtest.report import BacktestReport

logger = get_logger(__name__)


# ═════════════════════════════════════════════════════════════════════
#  AYARLANABILIR PARAMETRELER
# ═════════════════════════════════════════════════════════════════════

SENSITIVITY_PARAMS: dict[str, dict[str, Any]] = {
    # ── Trend Follow ────────────────────────────────────────────
    "TF_EMA_FAST": {"module": "engine.ogul", "base": 20, "type": int},
    "TF_EMA_SLOW": {"module": "engine.ogul", "base": 50, "type": int},
    "TF_ADX_THRESHOLD": {"module": "engine.ogul", "base": 25.0, "type": float},
    "TF_SL_ATR_MULT": {"module": "engine.ogul", "base": 1.5, "type": float},
    "TF_TP_ATR_MULT": {"module": "engine.ogul", "base": 2.0, "type": float},
    "TF_TRAILING_ATR_MULT": {"module": "engine.ogul", "base": 1.5, "type": float},
    # ── Mean Reversion ──────────────────────────────────────────
    "MR_RSI_OVERSOLD": {"module": "engine.ogul", "base": 30.0, "type": float},
    "MR_RSI_OVERBOUGHT": {"module": "engine.ogul", "base": 70.0, "type": float},
    "MR_ADX_THRESHOLD": {"module": "engine.ogul", "base": 20.0, "type": float},
    "MR_SL_ATR_MULT": {"module": "engine.ogul", "base": 1.0, "type": float},
    # ── Breakout ────────────────────────────────────────────────
    "BO_LOOKBACK": {"module": "engine.ogul", "base": 20, "type": int},
    "BO_VOLUME_MULT": {"module": "engine.ogul", "base": 1.5, "type": float},
    "BO_ATR_EXPANSION": {"module": "engine.ogul", "base": 1.2, "type": float},
    # ── Spread / Slippage ───────────────────────────────────────
    "SPREAD_BASE": {"module": "backtest.spread_model", "base": 0.5, "type": float, "attr": "base_spread"},
    "SLIPPAGE_NORMAL_MU": {"module": "backtest.slippage_model", "base": 1.0, "type": float, "attr": "NORMAL_MU"},
}

VARIATION_PCT: float = 0.20  # +/- %20


# ═════════════════════════════════════════════════════════════════════
#  VERİ MODELLERİ
# ═════════════════════════════════════════════════════════════════════


@dataclass
class SensitivityVariation:
    """Tek bir parametre varyasyonunun sonucu."""

    param_name: str
    base_value: float
    varied_value: float
    variation: str              # "+20%" veya "-20%"
    metrics: dict[str, Any]
    sharpe_change_pct: float    # Temel Sharpe'dan % değişim
    dd_change_pct: float        # Temel maks DD'den % değişim
    pnl_change_pct: float       # Temel PnL'den % değişim
    resilient: bool             # Kabul edilebilir sınırlar içinde mi


@dataclass
class SensitivityResult:
    """Tam hassasiyet analizi sonucu."""

    baseline_metrics: dict[str, Any]
    variations: list[SensitivityVariation]
    sensitive_params: list[str]     # >%50 metrik bozulması yapan parametreler
    overall_resilient: bool         # Hiçbir parametre başarısızlık yaratmıyor mu


# ═════════════════════════════════════════════════════════════════════
#  HASSASİYET MOTORU
# ═════════════════════════════════════════════════════════════════════


class SensitivityEngine:
    """Parametre hassasiyet analizi motoru.

    Her parametre için:
        1. ``base_value × (1 + 0.20)`` ile backtest çalıştır
        2. ``base_value × (1 - 0.20)`` ile backtest çalıştır
        3. Sharpe, DD, PnL'yi temel ile karşılaştır
        4. Herhangi bir metrik >%50 kötüleşirse işaretle

    Uygulama notu: runner.py sabitleri modül seviyesinde import eder,
    bu yüzden geçici değişiklik için monkey-patching kullanılır.
    Her çalıştırma sonrası orijinal değer geri yüklenir.

    Args:
        data: OHLCV DataFrame.
        config: BacktestRunner konfigürasyonu.
        params: Test edilecek parametreler (varsayılan: ``SENSITIVITY_PARAMS``).
        variation_pct: Varyasyon yüzdesi (varsayılan: 0.20).
    """

    def __init__(
        self,
        data: pd.DataFrame,
        config: dict | None = None,
        params: dict[str, dict[str, Any]] | None = None,
        variation_pct: float = VARIATION_PCT,
    ):
        self.data = data
        self.config = config or {}
        self.params = params or SENSITIVITY_PARAMS
        self.variation_pct = variation_pct

    # ── Parametreli çalıştırma ──────────────────────────────────────

    def _run_with_param_override(
        self,
        param_name: str,
        param_info: dict,
        new_value: float,
    ) -> BacktestReport:
        """Tek bir parametre override edilmiş şekilde backtest çalıştır.

        Modül seviyesinde monkey-patching ile parametreyi değiştirir,
        BacktestRunner çalıştırır, ardından orijinal değeri geri yükler.
        """
        module = importlib.import_module(param_info["module"])

        # Bazı parametrelerin modüldeki adı farklı olabilir
        attr_name = param_info.get("attr", param_name)
        original = getattr(module, attr_name, param_info["base"])

        try:
            # Override
            if param_info["type"] == int:
                setattr(module, attr_name, max(1, int(new_value)))
            else:
                setattr(module, attr_name, new_value)

            runner = BacktestRunner(self.data, self.config)
            report = runner.run()
            return report
        finally:
            # Her zaman geri yükle
            setattr(module, attr_name, original)

    # ── Ana çalıştırma ──────────────────────────────────────────────

    def run(self) -> SensitivityResult:
        """Tam hassasiyet analizini çalıştır.

        Returns:
            ``SensitivityResult`` — varyasyonlar, hassas parametreler,
            genel dayanıklılık.
        """
        logger.info("Hassasiyet analizi baslatiliyor...")

        # 1. Temel (baseline) çalıştırma
        baseline_runner = BacktestRunner(self.data, self.config)
        baseline_report = baseline_runner.run()
        baseline_metrics = baseline_report.summary()

        baseline_sharpe = baseline_metrics.get("sharpe_ratio", 0.0)
        baseline_dd = baseline_metrics.get("max_drawdown", 0.0)
        baseline_pnl = baseline_metrics.get("total_pnl", 0.0)

        variations: list[SensitivityVariation] = []
        sensitive_params: list[str] = []

        for param_name, param_info in self.params.items():
            base_val = param_info["base"]

            for sign, label in [(1, "+20%"), (-1, "-20%")]:
                new_val = base_val * (1 + sign * self.variation_pct)

                logger.debug(f"Hassasiyet: {param_name} = {new_val} ({label})")

                try:
                    report = self._run_with_param_override(
                        param_name, param_info, new_val,
                    )
                    metrics = report.summary()
                except Exception as e:
                    logger.error(
                        f"Hassasiyet hatasi {param_name} {label}: {e}",
                    )
                    continue

                sharpe = metrics.get("sharpe_ratio", 0.0)
                dd = metrics.get("max_drawdown", 0.0)
                pnl = metrics.get("total_pnl", 0.0)

                sharpe_change = (
                    ((sharpe - baseline_sharpe) / abs(baseline_sharpe) * 100)
                    if baseline_sharpe != 0
                    else 0.0
                )
                dd_change = (
                    ((dd - baseline_dd) / baseline_dd * 100)
                    if baseline_dd != 0
                    else 0.0
                )
                pnl_change = (
                    ((pnl - baseline_pnl) / abs(baseline_pnl) * 100)
                    if baseline_pnl != 0
                    else 0.0
                )

                # Sharpe %50'den fazla düşmez VE DD %50'den fazla artmazsa
                resilient = (sharpe_change > -50.0) and (dd_change < 50.0)

                if not resilient and param_name not in sensitive_params:
                    sensitive_params.append(param_name)

                variations.append(
                    SensitivityVariation(
                        param_name=param_name,
                        base_value=base_val,
                        varied_value=new_val,
                        variation=label,
                        metrics=metrics,
                        sharpe_change_pct=sharpe_change,
                        dd_change_pct=dd_change,
                        pnl_change_pct=pnl_change,
                        resilient=resilient,
                    ),
                )

        overall_resilient = len(sensitive_params) == 0

        logger.info(
            f"Hassasiyet analizi tamamlandi: {len(variations)} varyasyon, "
            f"{len(sensitive_params)} hassas param, "
            f"genel_dayanikli={overall_resilient}",
        )

        return SensitivityResult(
            baseline_metrics=baseline_metrics,
            variations=variations,
            sensitive_params=sensitive_params,
            overall_resilient=overall_resilient,
        )
