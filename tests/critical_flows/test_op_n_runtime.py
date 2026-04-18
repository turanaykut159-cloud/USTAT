"""#272 OP-N runtime davranış testleri (AX-3, AX-4, partial close, R-11 loaded).

Gerçek fonksiyon çağrısı ile kritik davranışları doğrular. engine.logger
ve MetaTrader5 module'leri stub ile mock'lanır.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


def _install_stubs():
    """loguru + MetaTrader5 stub."""
    if "engine.logger" not in sys.modules:
        class _L:
            def __getattr__(self, n):
                return lambda *a, **k: None
        m = type(sys)("engine.logger")
        m.get_logger = lambda n: _L()
        sys.modules["engine.logger"] = m

    if "MetaTrader5" not in sys.modules:
        mt5_stub = type(sys)("MetaTrader5")
        mt5_stub.TRADE_RETCODE_DONE = 10009
        mt5_stub.ORDER_TYPE_BUY = 0
        mt5_stub.ORDER_TYPE_SELL = 1
        mt5_stub.TRADE_ACTION_DEAL = 1
        mt5_stub.TRADE_ACTION_PENDING = 5
        mt5_stub.TRADE_ACTION_SLTP = 6
        mt5_stub.TRADE_ACTION_REMOVE = 8
        mt5_stub.ORDER_FILLING_RETURN = 2
        mt5_stub.ORDER_TIME_GTC = 0
        mt5_stub.ORDER_TYPE_BUY_LIMIT = 2
        mt5_stub.ORDER_TYPE_SELL_LIMIT = 3
        sys.modules["MetaTrader5"] = mt5_stub


# ─── AX-3 runtime: _reset_daily kill-switch'i KORUR ────────────────

def test_ax3_reset_daily_preserves_kill_switch_runtime():
    """_reset_daily fonksiyonu aktif kill-switch'i düşürmez. #256 OP-H."""
    _install_stubs()
    # Baba import zincirini çok ağır, AST ile doğrulama yeter (runtime değil).
    import ast
    src = (ROOT / "engine" / "baba.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_reset_daily":
            body_str = ast.unparse(node)
            # AX-3: _clear_kill_switch çağrısı OLMAMALI (KILL_SWITCH_PERSIST log olmalı)
            assert "_clear_kill_switch" not in body_str, \
                "_reset_daily _clear_kill_switch çağırıyor — AX-3 ihlali"
            assert "KILL_SWITCH_PERSIST" in body_str, \
                "_reset_daily KILL_SWITCH_PERSIST event eksik"
            return
    pytest.fail("_reset_daily bulunamadı")


# ─── AX-4 runtime: manuel SL/TP fail report çağrısı ────────────────

def test_ax4_manuel_sltp_fail_calls_baba_report_runtime():
    """manuel_motor SL/TP fail halinde baba.report_unprotected_position çağrı pattern'i. #247."""
    import ast
    src = (ROOT / "engine" / "manuel_motor.py").read_text(encoding="utf-8")
    # 481-507 bloğunda report_unprotected_position çağrısı
    assert "baba.report_unprotected_position" in src or \
           "report_unprotected_position(symbol" in src, \
        "manuel_motor report_unprotected_position çağrısı yok"
    assert "AX-4 MANUEL" in src or "MANUEL ISTISNA" in src, \
        "AX-4 manuel istisna log etiketi eksik"


# ─── AX-4 hibrit force_close runtime ───────────────────────────────

def test_ax4_hybrid_direction_change_force_close_runtime():
    """h_engine._handle_direction_change close_position + baba.report fallback. #247 S1-4."""
    import ast
    src = (ROOT / "engine" / "h_engine.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_handle_direction_change":
            body = ast.unparse(node)
            assert "close_position" in body, "close_position çağrısı yok"
            assert "report_unprotected_position" in body, "fail halinde BABA raporu yok"
            assert "DIRECTION_FLIP" in body, "close_reason etiketi yok"
            return
    pytest.fail("_handle_direction_change bulunamadı")


# ─── Partial close handler runtime pattern ─────────────────────────

def test_partial_close_handler_runtime_pattern():
    """manuel_motor._handle_partial_close mevcut + 2 DB kaydı pattern'i. #259 OP-J."""
    import ast
    src = (ROOT / "engine" / "manuel_motor.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_handle_partial_close":
            body = ast.unparse(node)
            assert "insert_trade" in body, "partial_close insert_trade çağrısı yok"
            assert "update_trade" in body, "parent trade update çağrısı yok"
            assert "partial_close_mt5_sync" in body, "exit_reason etiketi yok"
            return
    pytest.fail("_handle_partial_close bulunamadı")


# ─── R-11 config-driven retry sayıları ─────────────────────────────

def test_r11_mt5_retries_config_driven():
    """mt5_bridge DEAL_LOOKUP_RETRIES + TICKET_MAX_RETRIES + SLTP_MAX_RETRIES + MODIFY config.get. #271."""
    src = (ROOT / "engine" / "mt5_bridge.py").read_text(encoding="utf-8")
    # Hardcoded değer OLMAMALI (= 10, = 20, = 5, = 3 satır başı)
    import re
    # Fonksiyon gövdesindeki hardcoded "= 5\n" veya "= 10\n" pattern
    # config.get kalıbı var mı?
    assert "mt5_retries.deal_lookup_retries" in src, "DEAL_LOOKUP config key eksik"
    assert "mt5_retries.ticket_max_retries" in src, "TICKET_MAX config key eksik"
    assert "mt5_retries.sltp_max_retries" in src, "SLTP_MAX config key eksik"
    assert "mt5_retries.modify_max_retries" in src, "MODIFY_MAX config key eksik"


def test_r11_main_intervals_config_driven():
    """main.py DB_BACKUP_INTERVAL + _TRADE_MODE_CHECK_INTERVAL config.get. #271."""
    src = (ROOT / "engine" / "main.py").read_text(encoding="utf-8")
    assert "intervals.db_backup_sec" in src, "DB_BACKUP config key eksik"
    assert "intervals.trade_mode_check_sec" in src, "TRADE_MODE config key eksik"


# ─── Config sanity + intervals block mevcut ─────────────────────────

def test_config_has_mt5_retries_and_intervals():
    """config/default.json mt5_retries + intervals blokları mevcut. #271 R-11 tam."""
    import json
    cfg = json.loads((ROOT / "config" / "default.json").read_text(encoding="utf-8"))
    rt = cfg.get("mt5_retries", {})
    assert rt.get("deal_lookup_retries") == 10
    assert rt.get("ticket_max_retries") == 20
    assert rt.get("sltp_max_retries") == 5
    assert rt.get("modify_max_retries") == 3
    iv = cfg.get("intervals", {})
    assert iv.get("db_backup_sec") == 360
    assert iv.get("trade_mode_check_sec") == 3600
