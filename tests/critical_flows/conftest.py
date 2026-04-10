"""Kritik akis testleri icin MT5 stub + ortak fixtures.

MT5 terminaline ihtiyac DUYMAZ — tamamen bellekte sahte bir broker taklidi
yapilir. Testler Linux/Windows her iki tarafta da calisir, CI'da dahil.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

# USTAT kokunu sys.path'e ekle
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── MT5 stub sabitleri ────────────────────────────────────────────
# Gercek MetaTrader5 API retcode'lari ile uyumlu
TRADE_RETCODE_DONE = 10009
TRADE_RETCODE_PLACED = 10008
TRADE_RETCODE_DONE_PARTIAL = 10010
TRADE_RETCODE_CLIENT_DISABLES_AT = 10027
TRADE_RETCODE_INVALID_ORDER = 10035
TRADE_RETCODE_REQUOTE = 10004

ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1
ORDER_TYPE_BUY_LIMIT = 2
ORDER_TYPE_SELL_LIMIT = 3
ORDER_TYPE_BUY_STOP = 4
ORDER_TYPE_SELL_STOP = 5
ORDER_TYPE_BUY_STOP_LIMIT = 6
ORDER_TYPE_SELL_STOP_LIMIT = 7

TRADE_ACTION_DEAL = 1
TRADE_ACTION_PENDING = 5
TRADE_ACTION_SLTP = 6
TRADE_ACTION_MODIFY = 7
TRADE_ACTION_REMOVE = 8
TRADE_ACTION_CLOSE_BY = 10


class FakeMT5Bridge:
    """MT5Bridge'in test stub'u — gercek bridge arayuzunu taklit eder.

    send_stop_limit, send_limit, modify_position, close_position cagrilari
    onceden yapilandirilmis senaryolara gore basarili/basarisiz doner.
    """

    def __init__(self) -> None:
        # Next call senaryosu — retcode + comment
        self.next_stop_limit_retcode: int = TRADE_RETCODE_DONE
        self.next_stop_limit_comment: str = ""
        self.next_limit_retcode: int = TRADE_RETCODE_DONE
        self.next_modify_retcode: int = TRADE_RETCODE_DONE
        self.next_modify_comment: str = ""
        # State field'lar — gercek bridge ile ayni interface
        self._last_stop_limit_error: dict[str, Any] = {}
        self._last_limit_error: dict[str, Any] = {}
        self._last_modify_error: dict[str, Any] = {}
        self._trade_allowed: bool = True
        # Cagri logu (dogrulama icin)
        self.calls: list[tuple[str, dict]] = []
        # Sahte ticket sayaci
        self._next_ticket = 1000000

    # ── Helpers ──────────────────────────────────────────────────
    def is_trade_allowed(self) -> bool:
        return self._trade_allowed

    def _new_ticket(self) -> int:
        self._next_ticket += 1
        return self._next_ticket

    # ── send_stop_limit ──────────────────────────────────────────
    def send_stop_limit(self, symbol, direction, lot, stop_price, limit_price, comment="") -> Any:
        self.calls.append(("send_stop_limit", {
            "symbol": symbol, "direction": direction, "lot": lot,
            "stop_price": stop_price, "limit_price": limit_price, "comment": comment,
        }))
        self._last_stop_limit_error = {}
        if self.next_stop_limit_retcode == TRADE_RETCODE_DONE:
            return {"order_ticket": self._new_ticket(), "retcode": TRADE_RETCODE_DONE}
        # Hata — bridge'in yaptigi gibi _last_stop_limit_error'a yaz
        self._last_stop_limit_error = {
            "retcode": int(self.next_stop_limit_retcode),
            "comment": str(self.next_stop_limit_comment),
        }
        return None

    # ── send_limit ───────────────────────────────────────────────
    def send_limit(self, symbol, direction, lot, price, comment="") -> Any:
        self.calls.append(("send_limit", {
            "symbol": symbol, "direction": direction, "lot": lot,
            "price": price, "comment": comment,
        }))
        self._last_limit_error = {}
        if self.next_limit_retcode == TRADE_RETCODE_DONE:
            return {"order_ticket": self._new_ticket(), "retcode": TRADE_RETCODE_DONE}
        self._last_limit_error = {"retcode": int(self.next_limit_retcode), "comment": ""}
        return None

    # ── modify_position ──────────────────────────────────────────
    def modify_position(self, ticket, sl=None, tp=None) -> Any:
        self.calls.append(("modify_position", {"ticket": ticket, "sl": sl, "tp": tp}))
        self._last_modify_error = {}
        if self.next_modify_retcode == TRADE_RETCODE_DONE:
            return {"retcode": TRADE_RETCODE_DONE}
        self._last_modify_error = {
            "retcode": int(self.next_modify_retcode),
            "comment": str(self.next_modify_comment),
        }
        return None

    # ── close_position ───────────────────────────────────────────
    def close_position(self, ticket) -> bool:
        self.calls.append(("close_position", {"ticket": ticket}))
        return True

    # ── Digerleri (no-op / stub) ─────────────────────────────────
    def get_tick(self, symbol):
        return SimpleNamespace(bid=100.0, ask=100.1, last=100.05, time=0)

    def get_positions(self):
        return []

    def heartbeat(self) -> bool:
        return True


@pytest.fixture
def fake_mt5() -> FakeMT5Bridge:
    """Her test icin temiz bir FakeMT5Bridge."""
    return FakeMT5Bridge()


@pytest.fixture
def fake_config():
    """Minimum config — kritik akis testleri icin gereken alanlar."""
    return {
        "broker": {"sltp_max_retries": 3, "close_max_retries": 3},
        "risk": {
            "risk_per_trade_pct": 1.0,
            "max_open_positions": 5,
            "max_daily_loss_pct": 1.8,
        },
        "hybrid": {
            "faz1_stop_prim": 1.5,
            "faz2_activation_prim": 3.0,
            "faz2_trailing_prim": 1.0,
            "target_prim": 5.0,
            "native_sltp": True,
        },
    }
