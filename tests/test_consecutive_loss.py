"""Üst üste kayıp ve cooldown testleri (Madde 3.6).

Cooldown sonrası sıfırlama, trade sayaç yönetimi.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from engine.baba import Baba, RISK_BASELINE_DATE
from engine.config import Config
from engine.database import Database
from engine.models.risk import RiskParams


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
def baba(tmp_config, tmp_db):
    mt5 = MagicMock()
    mt5.get_positions.return_value = []
    return Baba(tmp_config, tmp_db, mt5=mt5)


# ═════════════════════════════════════════════════════════════════════
#  CONSECUTIVE LOSS COUNTER
# ═════════════════════════════════════════════════════════════════════


class TestConsecutiveLossCounter:
    """_update_consecutive_losses() sayaç mantığı."""

    def test_no_trades_yields_zero(self, baba):
        """Trade yokken sayaç sıfır."""
        baba._update_consecutive_losses()
        assert baba._risk_state["consecutive_losses"] == 0

    def test_three_consecutive_losses(self, baba, tmp_db):
        """3 üst üste kayıp doğru sayılır."""
        now = datetime.now()
        for i in range(3):
            tmp_db.insert_trade({
                "symbol": f"F_TEST{i}",
                "direction": "BUY",
                "strategy": "TREND_FOLLOW",
                "entry_price": 100.0,
                "entry_time": (now - timedelta(hours=3 - i)).isoformat(timespec="seconds"),
                "exit_time": (now - timedelta(hours=2 - i)).isoformat(timespec="seconds"),
                "exit_price": 95.0,
                "pnl": -50.0,
                "lot": 1.0,
            })
        baba._update_consecutive_losses()
        assert baba._risk_state["consecutive_losses"] == 3

    def test_win_breaks_streak(self, baba, tmp_db):
        """Kazanç streak'i kırar — sonra gelen kayıplar sayılmaz."""
        now = datetime.now()
        # Kayıp 1 (eski)
        tmp_db.insert_trade({
            "symbol": "F_OLD",
            "direction": "BUY",
            "strategy": "TREND_FOLLOW",
            "entry_price": 100.0,
            "entry_time": (now - timedelta(hours=5)).isoformat(timespec="seconds"),
            "exit_time": (now - timedelta(hours=4)).isoformat(timespec="seconds"),
            "exit_price": 95.0,
            "pnl": -50.0,
            "lot": 1.0,
        })
        # Kazanç (ortadaki)
        tmp_db.insert_trade({
            "symbol": "F_WIN",
            "direction": "BUY",
            "strategy": "TREND_FOLLOW",
            "entry_price": 100.0,
            "entry_time": (now - timedelta(hours=3)).isoformat(timespec="seconds"),
            "exit_time": (now - timedelta(hours=2)).isoformat(timespec="seconds"),
            "exit_price": 110.0,
            "pnl": 100.0,
            "lot": 1.0,
        })
        # Kayıp 2 (yeni)
        tmp_db.insert_trade({
            "symbol": "F_NEW",
            "direction": "BUY",
            "strategy": "TREND_FOLLOW",
            "entry_price": 100.0,
            "entry_time": (now - timedelta(hours=1)).isoformat(timespec="seconds"),
            "exit_time": now.isoformat(timespec="seconds"),
            "exit_price": 90.0,
            "pnl": -100.0,
            "lot": 1.0,
        })
        baba._update_consecutive_losses()
        # Son trade kayıp ama ondan önceki kazanç → sayaç 1
        assert baba._risk_state["consecutive_losses"] == 1


# ═════════════════════════════════════════════════════════════════════
#  COOLDOWN
# ═════════════════════════════════════════════════════════════════════


class TestCooldownMechanism:
    """Cooldown başlatma, kontrol ve sona erme."""

    def test_start_cooldown_sets_time(self, baba):
        """Cooldown başlatılınca süre ayarlanır."""
        rp = RiskParams()
        baba._start_cooldown(rp)
        until = baba._risk_state["cooldown_until"]
        assert until is not None
        assert until > datetime.now()

    def test_is_in_cooldown_during(self, baba):
        """Cooldown süresi içinde True döner."""
        baba._risk_state["cooldown_until"] = datetime.now() + timedelta(hours=2)
        assert baba._is_in_cooldown() is True

    def test_cooldown_expired_resets_counter(self, baba):
        """Süre dolunca sayaç sıfırlanır ve last_cooldown_end kaydedilir."""
        baba._risk_state["cooldown_until"] = datetime.now() - timedelta(seconds=1)
        baba._risk_state["consecutive_losses"] = 3

        result = baba._is_in_cooldown()
        assert result is False
        assert baba._risk_state["consecutive_losses"] == 0
        assert baba._risk_state["cooldown_until"] is None
        assert baba._risk_state["last_cooldown_end"] is not None

    def test_no_cooldown_returns_false(self, baba):
        """Cooldown olmadan False döner."""
        assert baba._is_in_cooldown() is False


# ═════════════════════════════════════════════════════════════════════
#  COOLDOWN SONRASI TRADE SAYACI
# ═════════════════════════════════════════════════════════════════════


class TestCooldownTradeCounter:
    """Madde 1.6: Cooldown sonrası sadece yeni trade'ler sayılır."""

    def test_trades_before_cooldown_not_counted(self, baba, tmp_db):
        """Cooldown öncesi trade'ler sayılmaz."""
        now = datetime.now()
        # Cooldown 1 saat önce bitmiş
        cooldown_end = now - timedelta(hours=1)
        baba._risk_state["last_cooldown_end"] = cooldown_end.isoformat(timespec="seconds")

        # Cooldown ÖNCESİ kayıp (2 saat önce kapanmış)
        tmp_db.insert_trade({
            "symbol": "F_OLD",
            "direction": "BUY",
            "strategy": "TREND_FOLLOW",
            "entry_price": 100.0,
            "entry_time": (now - timedelta(hours=3)).isoformat(timespec="seconds"),
            "exit_time": (now - timedelta(hours=2)).isoformat(timespec="seconds"),
            "exit_price": 90.0,
            "pnl": -100.0,
            "lot": 1.0,
        })
        # Cooldown SONRASI kayıp (30 dk önce kapanmış)
        tmp_db.insert_trade({
            "symbol": "F_NEW",
            "direction": "BUY",
            "strategy": "TREND_FOLLOW",
            "entry_price": 100.0,
            "entry_time": (now - timedelta(minutes=45)).isoformat(timespec="seconds"),
            "exit_time": (now - timedelta(minutes=30)).isoformat(timespec="seconds"),
            "exit_price": 90.0,
            "pnl": -100.0,
            "lot": 1.0,
        })

        baba._update_consecutive_losses()
        # Sadece cooldown sonrası trade sayılmalı
        assert baba._risk_state["consecutive_losses"] == 1
