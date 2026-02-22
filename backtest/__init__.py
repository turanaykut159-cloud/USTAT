"""USTAT Backtest Modulu.

Tarihsel veri uzerinde strateji simulasyonu, dogrulama ve rapor uretimi.

Kullanim:
    from backtest import BacktestRunner, BacktestReport, ReportGenerator
    from backtest import WalkForwardEngine, MonteCarloEngine
    from backtest import StressTestEngine, SensitivityEngine
"""

from backtest.runner import BacktestRunner
from backtest.report import BacktestReport, ReportGenerator
from backtest.spread_model import SpreadModel
from backtest.slippage_model import SlippageModel
from backtest.session_model import SessionModel
from backtest.walk_forward import WalkForwardEngine, WalkForwardResult
from backtest.monte_carlo import MonteCarloEngine, MonteCarloResult
from backtest.stress_test import StressTestEngine, StressTestResult, STRESS_SCENARIOS
from backtest.sensitivity import SensitivityEngine, SensitivityResult

__all__ = [
    "BacktestRunner",
    "BacktestReport",
    "ReportGenerator",
    "SpreadModel",
    "SlippageModel",
    "SessionModel",
    "WalkForwardEngine",
    "WalkForwardResult",
    "MonteCarloEngine",
    "MonteCarloResult",
    "StressTestEngine",
    "StressTestResult",
    "STRESS_SCENARIOS",
    "SensitivityEngine",
    "SensitivityResult",
]
