"""Risk hesaplama testleri (Madde 3.6).

Drawdown, weekly loss, monthly loss edge case'leri.
Mevcut test_baba.py'deki temel testleri tamamlar.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
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
    """Geçici config dosyası."""
    db_path = str(tmp_path / "test.db")
    cfg_file = tmp_path / "test_config.json"
    cfg_file.write_text(
        json.dumps({"strategies": {}, "database": {"path": db_path}}),
        encoding="utf-8",
    )
    return Config(str(cfg_file))


@pytest.fixture
def tmp_db(tmp_config):
    """Geçici veritabanı."""
    db = Database(tmp_config)
    return db


@pytest.fixture
def baba(tmp_config, tmp_db):
    """Baba instance (MT5 mock)."""
    mt5 = MagicMock()
    mt5.get_positions.return_value = []
    b = Baba(tmp_config, tmp_db, mt5=mt5)
    return b


# ═════════════════════════════════════════════════════════════════════
#  HARD / SOFT DRAWDOWN EDGE CASES
# ═════════════════════════════════════════════════════════════════════


class TestDrawdownEdgeCases:
    """_check_hard_drawdown() sınır değer testleri."""

    def test_exactly_at_soft_threshold(self, baba):
        """Tam %10 drawdown → soft."""
        snap = {"drawdown": 0.10, "equity": 90000}
        rp = RiskParams()
        result = baba._check_hard_drawdown(rp, snap=snap)
        assert result == "soft"

    def test_just_below_soft_threshold(self, baba):
        """Eşiğin hemen altı → None."""
        snap = {"drawdown": 0.099, "equity": 90100}
        rp = RiskParams()
        result = baba._check_hard_drawdown(rp, snap=snap)
        assert result is None

    def test_exactly_at_hard_threshold(self, baba):
        """Tam %15 drawdown → hard."""
        snap = {"drawdown": 0.15, "equity": 85000}
        rp = RiskParams()
        result = baba._check_hard_drawdown(rp, snap=snap)
        assert result == "hard"

    def test_between_soft_and_hard(self, baba):
        """Soft ile hard arası → soft (hard_drawdown artık 0.12)."""
        snap = {"drawdown": 0.11, "equity": 89000}
        rp = RiskParams()
        result = baba._check_hard_drawdown(rp, snap=snap)
        assert result == "soft"

    def test_zero_drawdown(self, baba):
        """Sıfır drawdown → None."""
        snap = {"drawdown": 0.0, "equity": 100000}
        rp = RiskParams()
        result = baba._check_hard_drawdown(rp, snap=snap)
        assert result is None

    def test_no_snap_provided(self, baba, tmp_db):
        """Snap verilmediğinde DB'den okur."""
        # DB'ye snapshot ekle
        tmp_db.insert_risk_snapshot({
            "equity": 90000,
            "floating_pnl": 0.0,
            "daily_pnl": -10000,
            "drawdown": 0.10,
        })
        rp = RiskParams()
        result = baba._check_hard_drawdown(rp)
        assert result == "soft"


# ═════════════════════════════════════════════════════════════════════
#  FLOATING LOSS EDGE CASES
# ═════════════════════════════════════════════════════════════════════


class TestFloatingLossEdgeCases:
    """_check_floating_loss() sınır değer testleri."""

    def test_positive_floating_pnl(self, baba):
        """Kârdayken engel olmaz."""
        snap = {"equity": 110000, "floating_pnl": 10000}
        rp = RiskParams()
        result = baba._check_floating_loss(rp, snap=snap)
        assert result is False

    def test_zero_floating_pnl(self, baba):
        """Sıfır floating → engel yok."""
        snap = {"equity": 100000, "floating_pnl": 0.0}
        rp = RiskParams()
        result = baba._check_floating_loss(rp, snap=snap)
        assert result is False

    def test_small_loss_below_threshold(self, baba):
        """Eşiğin altında küçük kayıp → engel yok."""
        # Balance = 100000, floating = -1000, pct = 1%
        snap = {"equity": 99000, "floating_pnl": -1000}
        rp = RiskParams()
        result = baba._check_floating_loss(rp, snap=snap)
        assert result is False

    def test_loss_at_threshold(self, baba):
        """Tam eşikte → engel aktif."""
        # Balance = 100000, floating = -1500, pct = 1.5%
        snap = {"equity": 98500, "floating_pnl": -1500}
        rp = RiskParams()
        result = baba._check_floating_loss(rp, snap=snap)
        assert result is True

    def test_balance_zero_edge_case(self, baba):
        """Balance sıfır veya negatif → False (bölme hatası koruması)."""
        snap = {"equity": -5000, "floating_pnl": -5000}
        rp = RiskParams()
        result = baba._check_floating_loss(rp, snap=snap)
        assert result is False


# ═════════════════════════════════════════════════════════════════════
#  WEEKLY LOSS — HALVED FLAG
# ═════════════════════════════════════════════════════════════════════


class TestWeeklyLossHalved:
    """Haftalık kayıp — lot yarılama bayrağı."""

    def test_halved_flag_set_once(self, baba, tmp_db):
        """Bayrak bir kez set edilir — tekrar çağrılsa da değişmez."""
        # Hafta başı snapshot (Pazartesi)
        now = datetime.now()
        monday = now - timedelta(days=now.weekday())
        ts = monday.strftime("%Y-%m-%dT09:30:00")
        tmp_db.insert_risk_snapshot({
            "timestamp": ts,
            "equity": 100000,
            "floating_pnl": 0.0,
            "daily_pnl": 0.0,
        })
        # Mevcut equity %5 düşmüş
        snap = {"equity": 95000, "floating_pnl": 0.0, "daily_pnl": -5000, "drawdown": 0.05}
        rp = RiskParams()

        result1 = baba._check_weekly_loss(rp, snap=snap)
        result2 = baba._check_weekly_loss(rp, snap=snap)

        # Her iki çağrı da "halved" döner
        assert result1 == "halved"
        assert result2 == "halved"
        # Bayrak bir kez set edilmiş
        assert baba._risk_state["weekly_loss_halved"] is True
