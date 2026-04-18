"""#253 OP-D/F/G axiom manifest statik testler (#36).

governance/axioms.yaml'da listelenen enforced_in fonksiyonlarinin kaynak
dosyalarda gercekten var oldugunu dogrular. Manifest-kod drift'ine karsi
koruma.

- AX-1: ana dongu + ManuelMotor on-demand istisnasi (#252)
- AX-4: SL/TP Zorunlulugu 5 nokta (#247)
- AX-5: EOD zorunlu kapanis 3 nokta (#251)
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None  # pytest skip'lemek icin

ROOT = Path(__file__).resolve().parent.parent.parent
AXIOMS = ROOT / "governance" / "axioms.yaml"


def _load_axiom(axiom_id: str) -> dict:
    if yaml is None:
        pytest.skip("PyYAML gerekli")
    data = yaml.safe_load(AXIOMS.read_text(encoding="utf-8"))
    for ax in data.get("axioms", []):
        if ax.get("id") == axiom_id:
            return ax
    pytest.fail(f"{axiom_id} axioms.yaml'da yok")


def _function_exists(location: str) -> bool:
    """'engine/foo.py::bar' formatinda lokasyonu kod icinde ara."""
    if "::" not in location:
        return (ROOT / location).exists()
    file_rel, fn = location.split("::", 1)
    p = ROOT / file_rel
    if not p.exists():
        return False
    src = p.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn:
            return True
    return False


def _normalize_enforced_in(ax: dict) -> list[str]:
    e = ax.get("enforced_in")
    if isinstance(e, str):
        return [e]
    if isinstance(e, list):
        return e
    return []


def test_ax1_enforced_in_exists():
    """AX-1 enforced_in noktalari gercekten mevcut."""
    ax = _load_axiom("AX-1")
    locations = _normalize_enforced_in(ax)
    assert len(locations) >= 2, f"AX-1 en az 2 enforced_in beklenir (main+manuel), bulundu: {len(locations)}"
    for loc in locations:
        assert _function_exists(loc), f"AX-1 enforced_in pointer gecersiz: {loc}"


def test_ax4_enforced_in_5_nokta():
    """AX-4 SL/TP 5 motor noktasinda enforced (OP-D #247)."""
    ax = _load_axiom("AX-4")
    locations = _normalize_enforced_in(ax)
    assert len(locations) >= 5, f"AX-4 en az 5 enforced_in beklenir, bulundu: {len(locations)}"
    expected_hints = [
        "_execute_signal",
        "set_initial_sl",
        "set_initial_tp",
        "open_manual_trade",
        "_handle_direction_change",
    ]
    joined = " ".join(locations)
    for h in expected_hints:
        assert h in joined, f"AX-4 enforced_in '{h}' eksik"
    for loc in locations:
        assert _function_exists(loc), f"AX-4 enforced_in pointer gecersiz: {loc}"


def test_ax5_enforced_in_3_nokta():
    """AX-5 EOD 3 nokta enforced (OP-F #251)."""
    ax = _load_axiom("AX-5")
    locations = _normalize_enforced_in(ax)
    assert len(locations) >= 3, f"AX-5 en az 3 enforced_in beklenir, bulundu: {len(locations)}"
    for loc in locations:
        assert _function_exists(loc), f"AX-5 enforced_in pointer gecersiz: {loc}"


def test_ax4_statement_mentions_manual_istisna():
    """AX-4 statement manuel istisnasini acikca kapsar (#247 OP-D S1-3)."""
    ax = _load_axiom("AX-4")
    stmt = (ax.get("statement") or "").lower()
    assert re.search(r"manuel", stmt), "AX-4 statement 'manuel' anahtari eksik"
    assert re.search(r"report", stmt) or re.search(r"kayd", stmt), \
        "AX-4 statement 'report' veya 'kayd' anahtari eksik"


def test_ax1_statement_mentions_manuelmotor():
    """AX-1 ManuelMotor on-demand istisnasini kapsar (#252 OP-G)."""
    ax = _load_axiom("AX-1")
    stmt = (ax.get("statement") or "").lower()
    assert "manuelmotor" in stmt, "AX-1 ManuelMotor istisnasi statement'ta eksik"
    assert "on-demand" in stmt or "ana donguye girmez" in stmt, \
        "AX-1 on-demand acik degil"


def test_ax5_statement_mentions_overnight_istisna():
    """AX-5 overnight/hibrit istisnasini acikca kapsar (#251 OP-F)."""
    ax = _load_axiom("AX-5")
    stmt = (ax.get("statement") or "").lower()
    assert "overnight" in stmt or "istisna" in stmt, \
        "AX-5 overnight/istisna anahtari eksik"
