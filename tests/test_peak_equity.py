"""Peak equity kalıcılık testleri (Madde 3.6).

Peak equity DB'de saklanır ve engine yeniden başlatılsa bile korunur.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from engine.config import Config
from engine.data_pipeline import DataPipeline
from engine.database import Database


# ═════════════════════════════════════════════════════════════════════
#  FIXTURES
# ═════════════════════════════════════════════════════════════════════


@pytest.fixture
def tmp_config(tmp_path):
    db_path = str(tmp_path / "test.db")
    cfg_file = tmp_path / "test_config.json"
    cfg_file.write_text(
        json.dumps({"strategies": {}, "database": {"path": db_path}}),
        encoding="utf-8",
    )
    return Config(str(cfg_file))


@pytest.fixture
def tmp_db(tmp_config):
    return Database(tmp_config)


@pytest.fixture
def pipeline(tmp_config, tmp_db):
    """DataPipeline with mocked MT5."""
    mt5 = MagicMock()
    return DataPipeline(mt5, tmp_db, tmp_config)


# ═════════════════════════════════════════════════════════════════════
#  PEAK EQUITY
# ═════════════════════════════════════════════════════════════════════


class TestPeakEquity:
    """_calculate_drawdown() ve peak equity kalıcılığı."""

    def test_first_call_sets_peak(self, pipeline, tmp_db):
        """İlk çağrıda peak equity mevcut equity olarak ayarlanır."""
        dd = pipeline._calculate_drawdown(100_000.0)
        assert dd == 0.0
        stored = tmp_db.get_state("peak_equity")
        assert stored is not None
        assert float(stored) == 100_000.0

    def test_higher_equity_updates_peak(self, pipeline, tmp_db):
        """Daha yüksek equity peak'i günceller."""
        pipeline._calculate_drawdown(100_000.0)
        pipeline._calculate_drawdown(110_000.0)
        stored = float(tmp_db.get_state("peak_equity"))
        assert stored == 110_000.0

    def test_lower_equity_does_not_reduce_peak(self, pipeline, tmp_db):
        """Düşen equity peak'i azaltmaz."""
        pipeline._calculate_drawdown(100_000.0)
        dd = pipeline._calculate_drawdown(90_000.0)
        stored = float(tmp_db.get_state("peak_equity"))
        assert stored == 100_000.0
        assert dd == pytest.approx(0.1, abs=0.001)  # %10 drawdown

    def test_drawdown_calculation_correct(self, pipeline):
        """Drawdown formülü doğru: (peak - current) / peak."""
        pipeline._calculate_drawdown(200_000.0)
        dd = pipeline._calculate_drawdown(170_000.0)
        expected = (200_000.0 - 170_000.0) / 200_000.0  # 0.15
        assert dd == pytest.approx(expected, abs=0.0001)

    def test_peak_persists_across_instances(self, tmp_config, tmp_db):
        """Peak equity yeni pipeline instance'ında da korunur."""
        mt5_1 = MagicMock()
        p1 = DataPipeline(mt5_1, tmp_db, tmp_config)
        p1._calculate_drawdown(150_000.0)

        # Yeni pipeline instance (engine restart simülasyonu)
        mt5_2 = MagicMock()
        p2 = DataPipeline(mt5_2, tmp_db, tmp_config)
        dd = p2._calculate_drawdown(130_000.0)

        # Peak hâlâ 150k, drawdown = (150k - 130k) / 150k
        expected = (150_000.0 - 130_000.0) / 150_000.0
        assert dd == pytest.approx(expected, abs=0.001)

    def test_zero_equity_returns_zero(self, pipeline):
        """Sıfır equity → drawdown sıfır."""
        dd = pipeline._calculate_drawdown(0.0)
        assert dd == 0.0

    def test_drawdown_never_negative(self, pipeline):
        """Drawdown hiçbir zaman negatif olamaz."""
        pipeline._calculate_drawdown(100_000.0)
        dd = pipeline._calculate_drawdown(120_000.0)
        assert dd >= 0.0

    def test_drawdown_precision(self, pipeline):
        """Drawdown 6 decimal'e yuvarlanır."""
        pipeline._calculate_drawdown(100_000.0)
        dd = pipeline._calculate_drawdown(99_999.0)
        # 1 / 100000 = 0.00001 (5 decimal)
        assert dd == pytest.approx(0.00001, abs=0.000001)
