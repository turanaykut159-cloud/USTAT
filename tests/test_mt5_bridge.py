"""MT5 bridge modülü testleri."""

import pytest

from engine.mt5_bridge import MT5Bridge
from engine.config import Config


class TestMT5Bridge:
    """MT5Bridge sınıfı testleri."""

    def setup_method(self):
        self.config = Config()
        self.bridge = MT5Bridge(self.config)

    def test_initial_state(self):
        """Başlangıç durumu bağlantısız olmalı."""
        assert self.bridge.is_connected is False

    def test_get_positions_when_disconnected(self):
        """Bağlantı yokken boş liste dönmeli."""
        positions = self.bridge.get_positions()
        assert positions == []
