# -*- coding: utf-8 -*-
"""
ÜSTAT Plus V6.0 — Korunan Kural (R-XX) Statik Sözleşme Testleri.

Her kural için kodda beklenen davranışın en azından iskelet olarak
var olduğunu doğrular. Daha detaylı davranış testleri
tests/critical_flows içindedir; bu dosya manifest-kod bağını kontrol eder.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

try:
    import yaml
except ImportError:
    yaml = None

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "governance" / "protected_assets.yaml"


def _manifest() -> dict:
    assert yaml is not None, "PyYAML yüklü değil"
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def _read(rel: str) -> str:
    p = REPO_ROOT / rel
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def test_manifest_has_rules():
    m = _manifest()
    rules = m.get("protected_rules", [])
    assert len(rules) >= 12, f"Sicil en az 12 kural içermeli, bulunan: {len(rules)}"


def test_r01_call_order_present():
    src = _read("engine/main.py")
    assert "_run_single_cycle" in src, "R-01: _run_single_cycle eksik"
    # BABA, OĞUL, H-Engine, ÜSTAT sırası fonksiyon gövdesinde görünmeli
    assert src.find("baba") < src.find("ogul") or "run_cycle" in src, \
        "R-01: çağrı sırası iskeleti bulunamadı"


def test_r02_regime_detection():
    src = _read("engine/baba.py")
    assert "detect_regime" in src, "R-02: detect_regime yok"
    # 4 rejim adı geçmeli
    for regime in ("TREND", "RANGE", "VOLATILE"):
        assert regime in src.upper() or regime.lower() in src, f"R-02: {regime} rejimi görünmüyor"


def test_r03_top5_selection():
    src = _read("engine/ogul.py") + _read("engine/top5_selection.py")
    assert "select_top5" in src or "top5" in src.lower(), "R-03: select_top5 yok"


def test_r05_trade_state_machine():
    src = _read("engine/models/trade.py")
    assert src, "R-05: engine/models/trade.py yok"
    for state in ("PENDING", "SENT", "FILLED", "CLOSED"):
        assert state in src, f"R-05: {state} durumu yok"


def test_r06_eod_closure():
    src = _read("engine/ogul.py")
    assert "_check_end_of_day" in src, "R-06: _check_end_of_day yok"
    assert "_verify_eod_closure" in src, "R-06: _verify_eod_closure yok"


def test_r07_kill_switch_monotonic():
    src = _read("engine/baba.py")
    assert "_activate_kill_switch" in src, "R-07: _activate_kill_switch yok"


def test_r08_mt5_launch_only_electron():
    bridge = _read("engine/mt5_bridge.py")
    assert "launch=False" in bridge or "launch =" in bridge, \
        "R-08: mt5_bridge.connect launch parametresi görünmüyor"
    # Engine içinde mt5.initialize doğrudan çağrısı yasak (connect dışında)
    # Bu derinlemesine test_static_contracts tarafından yapılır.


def test_r09_sltp_mandatory():
    src = _read("engine/mt5_bridge.py")
    assert "send_order" in src, "R-09: send_order yok"


def test_r11_config_based_constants():
    # config/default.json yüklenebilir olmalı
    cfg = json.loads(_read("config/default.json") or "{}")
    assert "risk" in cfg, "R-11: config/default.json::risk bölümü yok"
    risk = cfg["risk"]
    for key in ("max_daily_loss_pct", "hard_drawdown_pct", "max_open_positions"):
        assert key in risk, f"R-11: risk.{key} config'te yok"


def test_inviolables_linked():
    """Her inviolable en az bir test referansına sahip olmalı."""
    m = _manifest()
    for inv in m.get("inviolables", []):
        assert inv.get("required_tests"), f"{inv['id']}: required_tests boş"


def test_protected_functions_have_linked_rule_or_inviolable():
    """BK-XX fonksiyonlarının en az bir kısmı CI-XX veya R-XX'e bağlı olmalı."""
    m = _manifest()
    linked_count = sum(
        1 for f in m.get("protected_functions", [])
        if f.get("linked_rules")
    )
    total = len(m.get("protected_functions", []))
    assert linked_count >= total // 3, (
        f"Korunan fonksiyonların en az üçte biri kural/ihlal edilemez'e bağlı olmalı. "
        f"Bağlı: {linked_count}/{total}"
    )
