"""Data pipeline modülü testleri."""

import pytest
import pandas as pd

from engine.data_pipeline import DataPipeline
from engine.config import Config
from engine.database import Database
from engine.mt5_bridge import MT5Bridge


class TestDataPipeline:
    """DataPipeline sınıfı testleri."""

    def setup_method(self):
        self.config = Config()
        self.db = Database(self.config)
        self.mt5 = MT5Bridge(self.config)
        self.pipeline = DataPipeline(self.mt5, self.db, self.config)

    def test_clean_removes_duplicates(self):
        """Temizleme fonksiyonu tekrar eden verileri kaldırmalı."""
        df = pd.DataFrame({
            "time": pd.to_datetime([
                "2025-01-01 09:30:00",
                "2025-01-01 09:30:00",
                "2025-01-01 09:31:00",
            ]),
            "open": [100, 100, 101],
            "high": [102, 102, 103],
            "low": [99, 99, 100],
            "close": [101, 101, 102],
            "tick_volume": [50, 50, 60],
        })
        result, _ = self.pipeline.clean_data(df, "F_THYAO", "M1")
        assert len(result) == 2

    def test_clean_drops_na(self):
        """Temizleme fonksiyonu NaN değerleri kaldırmalı."""
        df = pd.DataFrame({
            "time": pd.to_datetime([
                "2025-01-01 09:30:00",
                None,
                "2025-01-01 09:32:00",
            ]),
            "open": [100, None, 102],
            "high": [102, None, 104],
            "low": [99, None, 101],
            "close": [101, None, 103],
            "tick_volume": [50, None, 70],
        })
        result, _ = self.pipeline.clean_data(df, "F_THYAO", "M1")
        assert result.isna().sum().sum() == 0
