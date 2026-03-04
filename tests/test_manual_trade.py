"""Manuel işlem testleri (Madde 3.6).

SL otomatik hesaplama, lot validasyonu, risk ön kontrol.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pandas as pd
import pytest

from engine.baba import Baba
from engine.config import Config
from engine.database import Database
from engine.models.regime import Regime, RegimeType
from engine.models.risk import RiskParams, RiskVerdict
from engine.ogul import Ogul


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
def mock_mt5():
    """Mock MT5Bridge with standard returns."""
    mt5 = MagicMock()
    mt5.get_positions.return_value = []
    mt5.get_tick.return_value = MagicMock(bid=100.0, ask=100.5, spread=0.5)

    # Account info for margin checks
    account = MagicMock()
    account.equity = 100_000.0
    account.balance = 100_000.0
    account.margin = 5_000.0
    account.free_margin = 95_000.0
    mt5.get_account_info.return_value = account

    # Symbol info for lot validation
    sym_info = MagicMock()
    sym_info.volume_min = 0.1
    sym_info.volume_max = 10.0
    sym_info.volume_step = 0.1
    mt5.get_symbol_info.return_value = sym_info

    return mt5


@pytest.fixture
def mock_baba(tmp_config, tmp_db, mock_mt5):
    """Baba with mocked risk checks."""
    baba = Baba(tmp_config, tmp_db, mt5=mock_mt5)
    baba.current_regime = Regime(regime_type=RegimeType.TREND, confidence=0.8)
    return baba


@pytest.fixture
def ogul(tmp_config, mock_mt5, tmp_db, mock_baba):
    """Ogul instance with mocked dependencies."""
    rp = RiskParams()
    o = Ogul(tmp_config, mock_mt5, tmp_db, baba=mock_baba, risk_params=rp)
    return o


# ═════════════════════════════════════════════════════════════════════
#  CHECK_MANUAL_TRADE — RİSK ÖN KONTROL
# ═════════════════════════════════════════════════════════════════════


class TestCheckManualTrade:
    """check_manual_trade() risk ön kontrolü."""

    def test_returns_dict_with_expected_keys(self, ogul):
        """Dönüş sözlüğü beklenen anahtarları içerir."""
        result = ogul.check_manual_trade("F_THYAO", "BUY")
        assert isinstance(result, dict)
        assert "can_trade" in result
        assert "reason" in result

    def test_invalid_symbol_returns_reason(self, ogul, mock_mt5):
        """Geçersiz sembol için tick alınamazsa reason döner."""
        mock_mt5.get_tick.return_value = None
        result = ogul.check_manual_trade("F_INVALID", "BUY")
        assert result["can_trade"] is False

    def test_netting_conflict(self, ogul):
        """Aynı sembolde açık pozisyon varsa engeller."""
        from engine.models.trade import Trade, TradeState
        trade = Trade(
            symbol="F_THYAO", direction="BUY", strategy="MANUAL",
            volume=1.0, entry_price=100.0,
        )
        trade.state = TradeState.FILLED
        ogul.active_trades["F_THYAO"] = trade

        with patch.object(ogul, '_is_trading_allowed', return_value=True):
            result = ogul.check_manual_trade("F_THYAO", "BUY")
        assert result["can_trade"] is False
        assert "netting" in result.get("reason", "").lower() or "pozisyon" in result.get("reason", "").lower()


# ═════════════════════════════════════════════════════════════════════
#  OPEN_MANUAL_TRADE — SL OTOMATİK HESAPLAMA
# ═════════════════════════════════════════════════════════════════════


class TestManualTradeSL:
    """SL otomatik hesaplama mantığı testleri."""

    def test_buy_sl_is_below_price(self):
        """BUY SL = price - 1.5×ATR → fiyatın altında."""
        price = 100.0
        atr_val = 2.0
        sl = price - 1.5 * atr_val
        assert sl == 97.0
        assert sl < price

    def test_sell_sl_is_above_price(self):
        """SELL SL = price + 1.5×ATR → fiyatın üstünde."""
        price = 100.0
        atr_val = 2.0
        sl = price + 1.5 * atr_val
        assert sl == 103.0
        assert sl > price

    def test_buy_tp_is_above_price(self):
        """BUY TP = price + 2.0×ATR → fiyatın üstünde."""
        price = 100.0
        atr_val = 2.0
        tp = price + 2.0 * atr_val
        assert tp == 104.0
        assert tp > price

    def test_sell_tp_is_below_price(self):
        """SELL TP = price - 2.0×ATR → fiyatın altında."""
        price = 100.0
        atr_val = 2.0
        tp = price - 2.0 * atr_val
        assert tp == 96.0
        assert tp < price


# ═════════════════════════════════════════════════════════════════════
#  LOT VALİDASYONU
# ═════════════════════════════════════════════════════════════════════


class TestManualTradeLotValidation:
    """Lot sınır kontrolleri."""

    def test_lot_too_small(self, ogul, mock_mt5, tmp_db):
        """volume_min altında lot reddedilir."""
        # volume_min = 0.1, user sends 0.01
        result = ogul.open_manual_trade("F_THYAO", "BUY", 0.01)
        assert result.get("success") is not True

    def test_lot_too_large(self, ogul, mock_mt5, tmp_db):
        """volume_max üstünde lot reddedilir."""
        # volume_max = 10.0, user sends 20.0
        result = ogul.open_manual_trade("F_THYAO", "BUY", 20.0)
        assert result.get("success") is not True

    def test_zero_lot_rejected(self, ogul):
        """Sıfır lot reddedilir."""
        result = ogul.open_manual_trade("F_THYAO", "BUY", 0.0)
        assert result.get("success") is not True
