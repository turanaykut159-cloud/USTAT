"""#254 OP-D/E/Q statik sozlesme testleri (#36).

Kod icerik (AST/string) uzerinden kritik davranislarin korundugunu dogrular.
Runtime MT5/loguru gerektirmez.

Kapsam:
  - OP-D S1-2: ogul_sltp.set_initial_tp metodu mevcut + send_limit kullanir
  - OP-D S1-3: manuel_motor SL/TP fail report_unprotected_position cagirir
  - OP-D S1-4: h_engine._handle_direction_change force_close + baba.report
  - OP-E guc: baba._restore_risk_state ustat_floating_tightened tightening restore
  - KARAR #17 SE3 (#249): ogul._execute_signal trend_follow hard-block
  - OP-J (#250): manuel_motor insert_trade initial_volume alani set
  - OP-Q (#245-246): pre-commit hook + config.py autorepair
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _find_function(source: str, name: str) -> ast.FunctionDef | None:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


# ─── OP-D S1-2: ogul_sltp set_initial_tp ─────────────────────────────

def test_ogul_sltp_has_set_initial_tp():
    """ogul_sltp.py::set_initial_tp mevcut ve send_limit cagiriyor (#247)."""
    src = _src("engine/ogul_sltp.py")
    fn = _find_function(src, "set_initial_tp")
    assert fn is not None, "set_initial_tp metodu yok"
    body_str = ast.unparse(fn)
    assert "send_limit" in body_str, "set_initial_tp send_limit cagirmali"
    assert "tp_order_ticket" in body_str, "set_initial_tp tp_order_ticket set etmeli"


# ─── OP-D S1-3: manuel_motor report_unprotected_position ────────────

def test_manuel_motor_sltp_fail_calls_baba_report():
    """manuel_motor SL/TP fail durumunda baba.report_unprotected_position cagirir (#247)."""
    src = _src("engine/manuel_motor.py")
    # Bir yerde sl_tp_applied False kontrolu ve report cagrisi
    assert "report_unprotected_position" in src, \
        "manuel_motor report_unprotected_position cagrisi yok"
    assert "AX-4 MANUEL İSTİSNA" in src or "MANUEL ISTISNA" in src, \
        "AX-4 manuel istisna log etiketi yok"


# ─── OP-D S1-4: h_engine _handle_direction_change ───────────────────

def test_h_engine_handle_direction_change_exists():
    """h_engine _handle_direction_change metodu mevcut + force_close (#247)."""
    src = _src("engine/h_engine.py")
    fn = _find_function(src, "_handle_direction_change")
    assert fn is not None, "_handle_direction_change metodu yok"
    body_str = ast.unparse(fn)
    assert "close_position" in body_str, "force_close icin close_position cagrisi yok"
    assert "report_unprotected_position" in body_str, "fail durumunda BABA raporu yok"
    assert "DIRECTION_FLIP" in body_str, "DIRECTION_FLIP close_reason etiketi yok"


def test_h_engine_run_cycle_delegates_direction_change():
    """h_engine.run_cycle yon degisimi tespit edince _handle_direction_change cagirir."""
    src = _src("engine/h_engine.py")
    # run_cycle icinde _handle_direction_change cagrisi var mi?
    assert "_handle_direction_change(hp" in src, \
        "run_cycle _handle_direction_change'a delege etmiyor"


# ─── OP-E guc: baba restore floating_loss tightening ────────────────

def test_baba_restore_tightening_restores_threshold():
    """baba._restore_risk_state ustat_floating_tightened True ise rp.max_floating_loss da restore eder (#248)."""
    src = _src("engine/baba.py")
    fn = _find_function(src, "_restore_risk_state")
    assert fn is not None, "_restore_risk_state metodu yok"
    body_str = ast.unparse(fn)
    assert "ustat_floating_tightened" in body_str, \
        "_restore_risk_state tightening bayragi kontrolu eksik"
    assert "max_floating_loss" in body_str, \
        "_restore_risk_state rp.max_floating_loss restore etmiyor"


def test_baba_risk_state_has_tightening_key():
    """baba._risk_state init'te ustat_floating_tightened: False anahtari var (#244 + #248)."""
    src = _src("engine/baba.py")
    assert '"ustat_floating_tightened": False' in src, \
        "_risk_state init'te ustat_floating_tightened yok"


# ─── KARAR #17 → KARAR #18 (2026-05-04): hard-block kaldırıldı ──────
# Eski sözleşme (KARAR #17): _execute_signal trend_follow'u reddediyordu.
# Yeni sözleşme (KARAR #18): trend_follow şartlı izin (_generate_signal'da
#   ADX>=32 + günlük 5 trade limiti). Aktif HARD_BLOCK kodu kaldırıldı.
# Detay testler: tests/critical_flows/test_karar_18_contracts.py

def test_ogul_execute_signal_trend_follow_no_active_hardblock():
    """KARAR #18: _execute_signal'da aktif HARD_BLOCK kodu KALMAMALI.

    Eski KARAR #17 hard-block'u kaldırıldı; sadece yorumda tarihçe için
    kalıyor. Bu test, eski davranışın geri getirilmemesini garanti eder.

    KARAR #18 yeni sözleşmeleri için bkz: test_karar_18_contracts.py
    """
    src = _src("engine/ogul.py")
    fn = _find_function(src, "_execute_signal")
    assert fn is not None, "_execute_signal metodu yok"
    body_str = ast.unparse(fn)  # ast.unparse yorumları yutar, sadece kod kalır
    # Aktif kodda HARD_BLOCK log etiketi KALMAMALI
    assert "TREND_FOLLOW HARD_BLOCK" not in body_str, (
        "_execute_signal'da hala AKTİF HARD_BLOCK log var — "
        "KARAR #18 ile bu kaldırılmış olmalıydı"
    )
    # Aktif kodda 'trend_follow hard-block' literal'i KALMAMALI
    assert "trend_follow hard-block" not in body_str, (
        "_execute_signal'da hala AKTİF 'trend_follow hard-block' string var — "
        "KARAR #18 sözleşmesi bozulmuş"
    )
    # KARAR #18 referansı kodda var mı (yorumda da olabilir, ama dosya tarihçesinde olmalı)
    full_src = _src("engine/ogul.py")
    assert "KARAR #18" in full_src, (
        "ogul.py'de KARAR #18 referansı yok — tarihçe yorumu silinmiş"
    )


# ─── OP-J initial_volume backfill ───────────────────────────────────

def test_manuel_motor_insert_trade_sets_initial_volume():
    """manuel_motor insert_trade cagrilarinda initial_volume set edilir (#250)."""
    src = _src("engine/manuel_motor.py")
    # insert_trade dict'lerinde initial_volume var mi?
    # Minimum iki yerde olmali (app-open + mt5_direct adopt)
    occurrences = src.count('"initial_volume"')
    assert occurrences >= 2, \
        f"insert_trade initial_volume icermiyor (bulundu: {occurrences}, beklenen: >=2)"


# ─── OP-Q NULL-tail pre-commit hook ─────────────────────────────────

def test_precommit_hook_has_null_byte_check():
    """Pre-commit hook [6/7] NULL byte taramasi icerir (#245)."""
    hook = ROOT / ".githooks" / "pre-commit"
    if not hook.exists():
        import pytest
        pytest.skip(".githooks/pre-commit yok")
    src = hook.read_text(encoding="utf-8")
    assert "NULL byte taramasi" in src or "NULL BYTE" in src.upper(), \
        "Pre-commit hook NULL byte kontrolu yok"
    assert "null_tail_cleanup.py" in src, "null_tail_cleanup.py onerisi eksik"


# ─── OP-Q config boot autorepair ────────────────────────────────────

def test_config_boot_autorepair():
    """engine.Config._load NULL-tail autorepair icerir (#246)."""
    src = _src("engine/config.py")
    fn = _find_function(src, "_load")
    assert fn is not None, "Config._load metodu yok"
    body_str = ast.unparse(fn)
    assert "null_count" in body_str or "count(b" in body_str or '\\x00' in body_str or 'NULL' in body_str.upper(), \
        "_load NULL byte taramasi yok"
    assert "AUTOREPAIR" in body_str or "autorepair" in body_str, \
        "_load autorepair mekanizmasi yok"
    assert "corrupt-boot-" in body_str, \
        "_load zaman damgali yedek pattern'i yok"
