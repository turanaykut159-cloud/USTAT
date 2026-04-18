"""#270 OP-N ek davranış testleri — idempotency yaygınlaştırma + R-11 sanity.

6 ek test:
  1. killswitch route idempotency pattern
  2. hybrid/transfer route idempotency pattern
  3. hybrid/remove route idempotency pattern
  4. positions/close route idempotency pattern
  5. news_bridge parametresi kaldırıldı (import + çağrı yok)
  6. CLOSE_MAX_RETRIES config'den okur (drift yok)
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ─── Idempotency 4 endpoint ────────────────────────────────────────

@pytest.mark.parametrize("route,expected_cached_type", [
    ("api/routes/killswitch.py", "KillSwitchResponse"),
    ("api/routes/hybrid_trade.py", "HybridTransferResponse"),
    ("api/routes/positions.py", "ClosePositionResponse"),
    ("api/routes/manual_trade.py", "ManualTradeExecuteResponse"),
])
def test_endpoint_idempotency_pattern(route, expected_cached_type):
    """4 kritik endpoint check_idempotency + get_idempotent_response pattern'ı içerir. #261+#267."""
    src = _src(route)
    assert "check_idempotency" in src, f"{route} check_idempotency import/kullanımı yok"
    assert "get_idempotent_response" in src, f"{route} get_idempotent_response eksik"
    assert expected_cached_type in src, f"{route} response type {expected_cached_type} yok"


def test_hybrid_remove_idempotency():
    """hybrid/remove endpoint idempotency aktif. #267."""
    src = _src("api/routes/hybrid_trade.py")
    # remove_from_hybrid fonksiyonu içinde idem_key kullanımı
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "remove_from_hybrid":
            body = ast.unparse(node)
            assert "idem_key" in body, "remove_from_hybrid idem_key parametre eksik"
            assert "get_idempotent_response" in body, "remove_from_hybrid cache check yok"
            return
    pytest.fail("remove_from_hybrid fonksiyonu bulunamadı")


# ─── News bridge temizlik (OP-O) ───────────────────────────────────

def test_news_bridge_parameter_removed():
    """signal_engine generate_signal imzasında news_bridge YOK. #266."""
    src = _src("engine/utils/signal_engine.py")
    # generate_signal fonksiyonunu bul
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "generate_signal":
            args = [a.arg for a in node.args.args] + [a.arg for a in node.args.kwonlyargs]
            assert "news_bridge" not in args, \
                f"generate_signal news_bridge parametresi kaldırılmamış: {args}"
            return
    pytest.fail("generate_signal fonksiyonu bulunamadı")


# ─── R-11 config drift ──────────────────────────────────────────────

def test_close_max_retries_config_driven():
    """baba.py CLOSE_MAX_RETRIES config'den okur (hardcoded değil). #269 R-11."""
    src = _src("engine/baba.py")
    # _close_all_positions veya benzeri içinde CLOSE_MAX_RETRIES
    assert 'CLOSE_MAX_RETRIES' in src, "CLOSE_MAX_RETRIES tanımı kaybolmuş"
    # Hardcoded "= 5" kalıbı OLMAMALI (drift fix)
    assert 'CLOSE_MAX_RETRIES = 5' not in src, \
        "CLOSE_MAX_RETRIES hala hardcoded 5 — drift fix edilmemiş"
    # Config read kalıbı olmalı
    assert re.search(r'CLOSE_MAX_RETRIES\s*=\s*int\(.*config\.get', src) or \
           re.search(r'CLOSE_MAX_RETRIES\s*=.*close_max_retries', src), \
        "CLOSE_MAX_RETRIES config.get ile okumalı"


def test_sanity_thresholds_in_config():
    """config sanity_thresholds blok mevcut. #265 R-11."""
    import json
    cfg = json.loads(_src("config/default.json"))
    st = cfg.get("sanity_thresholds")
    assert st, "sanity_thresholds bloğu yok"
    assert st.get("margin_usage_limit_pct") == 200.0
    assert st.get("peak_anomaly_dd_pct") == 30.0
