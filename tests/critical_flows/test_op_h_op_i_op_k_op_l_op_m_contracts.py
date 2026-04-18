"""#264 Statik sözleşme testleri OP-H / OP-K / OP-L / OP-M / OP-K3 (#48).

Runtime MT5/loguru gerektirmez. AST + dosya içerik seviyesinde kritik
davranışların korunmuş olduğunu doğrular. Davranış testleri (mock harness)
daha büyük iş — hafta içi OP-N tam.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _find_function(source: str, name: str) -> ast.FunctionDef | None:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


# ─── OP-H AX-3 monotonluk ──────────────────────────────────────────

def test_baba_reset_daily_preserves_kill_switch():
    """_reset_daily kill-switch seviyesini KORUR (otomatik _clear_kill_switch YOK). #256."""
    src = _src("engine/baba.py")
    fn = _find_function(src, "_reset_daily")
    assert fn is not None
    body_str = ast.unparse(fn)
    # Otomatik kill-switch clear çağrısı olmamalı
    assert "_clear_kill_switch" not in body_str or "KILL_SWITCH_PERSIST" in body_str, \
        "_reset_daily otomatik _clear_kill_switch çağırmamalı (AX-3 ihlali)"


def test_baba_reset_daily_has_persist_log():
    """_reset_daily KS aktifse KILL_SWITCH_PERSIST event loglar. #256."""
    src = _src("engine/baba.py")
    fn = _find_function(src, "_reset_daily")
    body_str = ast.unparse(fn)
    assert "KILL_SWITCH_PERSIST" in body_str, \
        "_reset_daily KS aktifken KILL_SWITCH_PERSIST event'i eksik"
    assert "AX-3 MONOTONLUK" in body_str, \
        "_reset_daily AX-3 MONOTONLUK log etiketi eksik"


# ─── OP-K API auth ──────────────────────────────────────────────────

def test_api_deps_has_auth_guard():
    """api/deps.py require_localhost_and_token guard içerir. #261."""
    src = _src("api/deps.py")
    fn = _find_function(src, "require_localhost_and_token")
    assert fn is not None, "require_localhost_and_token guard eksik"
    body = ast.unparse(fn)
    assert "127.0.0.1" in body or "_LOCAL_IPS" in body, "Localhost IP kontrolü yok"
    assert "HTTPException" in body, "403/401 HTTPException eksik"
    assert "X-USTAT-TOKEN" in src or "x_ustat_token" in body, "Token header eksik"


@pytest.mark.parametrize("route", [
    "api/routes/killswitch.py",
    "api/routes/manual_trade.py",
    "api/routes/hybrid_trade.py",
    "api/routes/positions.py",
])
def test_kritik_endpoint_auth_guard(route):
    """4 kritik endpoint require_localhost_and_token ile korunur. #261 OP-K."""
    src = _src(route)
    assert "require_localhost_and_token" in src, \
        f"{route} require_localhost_and_token import/dependency eksik"


# ─── OP-L Trading saatleri config ──────────────────────────────────

def test_config_has_trading_hours_block():
    """config/default.json trading_hours bloğu mevcut. #262 OP-L."""
    cfg = json.loads(_src("config/default.json"))
    assert "trading_hours" in cfg, "config trading_hours bloğu yok"
    th = cfg["trading_hours"]
    for key in ("ogul_open", "ogul_close", "manuel_open", "manuel_close",
                "hybrid_open", "hybrid_close", "eod_notify"):
        assert key in th, f"trading_hours.{key} eksik"


def test_ogul_reads_trading_hours_from_config():
    """OGUL trading_hours.ogul_open fallback ile okur. #262."""
    src = _src("engine/ogul.py")
    assert "trading_hours.ogul_open" in src, "OGUL trading_hours.ogul_open okumuyor"


def test_h_engine_reads_trading_hours_from_config():
    """H-Engine _is_trading_hours config override fallback. #262."""
    src = _src("engine/h_engine.py")
    assert "trading_hours.hybrid_open" in src, "H-Engine trading_hours.hybrid_open okumuyor"


def test_manuel_motor_reads_trading_hours_from_config():
    """Manuel _is_trading_allowed config override fallback. #262."""
    src = _src("engine/manuel_motor.py")
    assert "trading_hours.manuel_open" in src, "Manuel trading_hours.manuel_open okumuyor"


# ─── OP-M SE3 news'siz revize ──────────────────────────────────────

def test_se3_news_event_stub():
    """signal_engine _source_news_event stub NEUTRAL döner. #263 OP-M."""
    src = _src("engine/utils/signal_engine.py")
    fn = _find_function(src, "_source_news_event")
    assert fn is not None
    body = ast.unparse(fn)
    assert 'NEUTRAL' in body, "news_event stub NEUTRAL dönmeli"
    assert 'removed_v6.1' in body or 'v6.1' in body, \
        "news_event stub v6.1 marker eksik (backward-compat doküman)"


def test_se3_docstring_mentions_news_stub():
    """generate_signal docstring 10 slot / 9 aktif belgelenmiş. #263."""
    src = _src("engine/utils/signal_engine.py")
    fn = _find_function(src, "generate_signal")
    assert fn is not None
    ds = ast.get_docstring(fn) or ""
    assert "9 aktif" in ds or "stub" in ds.lower(), \
        "generate_signal docstring news stub durumunu belgelemeli"


# ─── OP-K3 restricted mode ─────────────────────────────────────────

def test_data_pipeline_mt5_connection_check():
    """update_risk_snapshot MT5 bağlantı kontrolü öncesi snapshot skip. #260 OP-K3."""
    src = _src("engine/data_pipeline.py")
    fn = _find_function(src, "update_risk_snapshot")
    assert fn is not None
    body = ast.unparse(fn)
    assert "is_connected" in body or "mt5_connected" in body, \
        "update_risk_snapshot MT5 bağlantı kontrolü yok"
    assert "OP-K3" in body, "OP-K3 referansı eksik (audit trail)"


# ─── OP-K1/K2 sanity (önceki committe eklendi, regresyon koruma) ───

def test_peak_equity_anomaly_detection():
    """_calculate_drawdown PEAK_EQUITY_ANOMALY event trigger. #258 OP-K1."""
    src = _src("engine/data_pipeline.py")
    fn = _find_function(src, "_calculate_drawdown")
    assert fn is not None
    body = ast.unparse(fn)
    assert "PEAK_EQUITY_ANOMALY" in body, "peak_equity anomaly event eksik"


def test_margin_anomaly_detection():
    """update_risk_snapshot MARGIN_ANOMALY event trigger. #257 OP-K2."""
    src = _src("engine/data_pipeline.py")
    fn = _find_function(src, "update_risk_snapshot")
    body = ast.unparse(fn) if fn else ""
    assert "MARGIN_ANOMALY" in body, "margin anomaly event eksik"
    assert "MARGIN_SANITY_LIMIT" in body or "200" in body, "margin limit sabiti eksik"
