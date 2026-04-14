# -*- coding: utf-8 -*-
"""
ÜSTAT Plus V6.0 — Governance test paketi: manifest-kod senkron.

Bu testler check_constitution.py aracını pytest içinden çalıştırır ve
hayalet kayıt / kilitli değer değişimi / hash uyuşmazlığı durumunda kırılır.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "tools" / "check_constitution.py"


def _run_checker(*extra_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHECKER), *extra_args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_manifest_exists():
    assert (REPO_ROOT / "governance" / "protected_assets.yaml").is_file(), \
        "Korunan varlık sicili bulunamadı"


def test_anayasa_exists():
    assert (REPO_ROOT / "USTAT_ANAYASA.md").is_file(), \
        "USTAT_ANAYASA.md bulunamadı"


def test_checker_tool_exists():
    assert CHECKER.is_file(), "tools/check_constitution.py bulunamadı"


def test_no_ghost_entries():
    """Sicildeki hiçbir dosya/fonksiyon hayalet olmamalı — exit 2 yasak."""
    result = _run_checker("--quiet")
    assert result.returncode != 2, (
        f"Anayasa doğrulama KRİTİK ihlal verdi:\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )


def test_locked_config_values():
    """Kilitli config değerleri (risk eşikleri) değişmemiş olmalı."""
    result = _run_checker("--quiet")
    # Exit 2 = kritik (hayalet + kilitli değer değişimi bunu tetikler)
    if result.returncode == 2:
        assert "KİLİTLİ DEĞER DEĞİŞTİ" not in result.stdout, (
            f"Kilitli config değeri değişmiş:\n{result.stdout}"
        )


def test_anayasa_hash_integrity():
    """Anayasa hash eşleşmezse test kırılır."""
    result = _run_checker("--quiet")
    assert "ANAYASA HASH UYUŞMAZLIĞI" not in result.stdout, (
        f"Anayasa metni hash ile eşleşmiyor — C3 prosedürü gerekli:\n{result.stdout}"
    )
