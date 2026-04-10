"""AST tabanli etki haritasi — 'neden etki analizi yapmiyorsun?' sorusunun cevabi.

Bu arac herhangi bir dosya/fonksiyon icin bagimlilik zincirini cikarir:
    - HANGI DOSYALAR degisen modulu IMPORT ediyor? (yukari — tuketiciler)
    - HANGI DOSYALAR degisen fonksiyonu CAGIRIYOR? (reverse call graph)

Kullanim:
    # Bir dosyayi degistirmeden once etki analizi:
    python tools/impact_map.py engine/mt5_bridge.py

    # Bir fonksiyonu degistirmeden once:
    python tools/impact_map.py engine/mt5_bridge.py::send_stop_limit

    # JSON cikti:
    python tools/impact_map.py engine/baba.py --json

Cikti:
    - Dogrudan tuketiciler (hangi dosyalar import ediyor)
    - Dolayli tuketiciler (2. seviye)
    - Riskli bolge etiketleri (Red/Yellow/Black Box)
    - Test kapsami (hangi testler ilgili)

Not: Sadece statik analiz yapar — dinamik getattr/importlib bulamaz.
Pre-commit hook'u bu araci calistirip kirmizi bolge dokunusu uyarir.
"""
from __future__ import annotations

import ast
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# ── Bolge tanimlari (CLAUDE.md Bolum 4 ile uyumlu) ──────────────
RED_ZONE = {
    "engine/baba.py",
    "engine/ogul.py",
    "engine/mt5_bridge.py",
    "engine/main.py",
    "engine/ustat.py",
    "engine/database.py",
    "engine/data_pipeline.py",
    "config/default.json",
    "start_ustat.py",
    "api/server.py",
}
YELLOW_ZONE = {
    "engine/h_engine.py",
    "engine/config.py",
    "engine/logger.py",
    "api/routes/killswitch.py",
    "api/routes/positions.py",
    "desktop/main.js",
    "desktop/mt5Manager.js",
}
BLACK_BOX_FUNCTIONS = {
    "check_risk_limits", "_activate_kill_switch", "_close_all_positions",
    "_close_ogul_and_hybrid", "check_drawdown_limits", "_check_hard_drawdown",
    "_check_monthly_loss", "detect_regime", "calculate_position_size",
    "run_cycle", "_check_period_resets",
    "_execute_signal", "_check_end_of_day", "_verify_eod_closure",
    "_manage_active_trades", "process_signals",
    "send_order", "close_position", "modify_position", "_safe_call",
    "heartbeat", "connect",
    "_run_single_cycle", "_heartbeat_mt5", "_main_loop",
    "run_webview_process", "_start_api", "_shutdown_api", "lifespan",
    "main", "createWindow",
}


def zone_for(rel_path: str) -> str:
    p = rel_path.replace("\\", "/")
    if p in RED_ZONE:
        return "KIRMIZI"
    if p in YELLOW_ZONE:
        return "SARI"
    return "YESIL"


# ── Modul adi -> dosya eslemesi ─────────────────────────────────
def module_name_from_path(path: Path) -> str:
    """engine/mt5_bridge.py -> engine.mt5_bridge"""
    rel = path.relative_to(ROOT).with_suffix("")
    return ".".join(rel.parts)


def path_from_module(module: str) -> Path | None:
    """engine.mt5_bridge -> engine/mt5_bridge.py (varsa)"""
    candidate = ROOT / (module.replace(".", "/") + ".py")
    return candidate if candidate.exists() else None


# ── Import analizi ──────────────────────────────────────────────
def imports_of(path: Path) -> set[str]:
    """Dosyadan import edilen modul adlarini dondurur."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.add(node.module)
    return mods


def find_importers(target_module: str) -> list[Path]:
    """target_module'u import eden tum python dosyalarini bul."""
    importers: list[Path] = []
    for py in ROOT.rglob("*.py"):
        rel = py.relative_to(ROOT).as_posix()
        if rel.startswith(("archive/", ".agent/", "tests/critical_flows/")):
            continue
        mods = imports_of(py)
        for m in mods:
            if m == target_module or m.startswith(target_module + "."):
                importers.append(py)
                break
    return importers


# ── Fonksiyon cagri analizi ─────────────────────────────────────
def find_callers(func_name: str) -> list[tuple[Path, int, str]]:
    """Verilen fonksiyon/metot adini cagiran tum yerleri bul.

    Gercek attribute cagrilari (obj.method() ve fonksiyon cagrilari method()).
    Tanimlamalari sayar, sadece cagrilari dondurur.
    """
    callers: list[tuple[Path, int, str]] = []
    for py in ROOT.rglob("*.py"):
        rel = py.relative_to(ROOT).as_posix()
        if rel.startswith(("archive/", ".agent/")):
            continue
        try:
            text = py.read_text(encoding="utf-8")
            tree = ast.parse(text)
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            matched = False
            if isinstance(func, ast.Attribute) and func.attr == func_name:
                matched = True
            elif isinstance(func, ast.Name) and func.id == func_name:
                matched = True
            if matched:
                callers.append((py, node.lineno, rel))
    return callers


# ── Ana analiz ──────────────────────────────────────────────────
def analyze(target: str) -> dict[str, Any]:
    """target biciminleri:
        engine/mt5_bridge.py        -> modul etki analizi
        engine/mt5_bridge.py::func  -> fonksiyon cagri analizi
    """
    if "::" in target:
        path_part, func_name = target.split("::", 1)
    else:
        path_part, func_name = target, None

    target_path = (ROOT / path_part).resolve()
    if not target_path.exists():
        return {"error": f"Dosya bulunamadi: {target_path}"}

    rel = target_path.relative_to(ROOT).as_posix()
    zone = zone_for(rel)
    target_module = module_name_from_path(target_path) if target_path.suffix == ".py" else None

    result: dict[str, Any] = {
        "target": rel,
        "zone": zone,
        "warnings": [],
    }

    if zone == "KIRMIZI":
        result["warnings"].append(
            "KIRMIZI BOLGE — cift dogrulama + kullanici onayi zorunlu. "
            "Pre-commit kritik akis testleri zorunlu."
        )
    elif zone == "SARI":
        result["warnings"].append(
            "SARI BOLGE — standart kok sebep + etki analizi + onay gerekli."
        )

    if func_name:
        if func_name in BLACK_BOX_FUNCTIONS:
            result["warnings"].append(
                f"SIYAH KAPI fonksiyonu '{func_name}' — MANTIK degistirilemez. "
                f"Izin: bug fix, perf iyilestirme, guvenlik katmani."
            )
        callers = find_callers(func_name)
        result["function"] = func_name
        result["callers"] = [
            {"file": rel_p, "line": ln}
            for _, ln, rel_p in callers
        ]
        result["caller_count"] = len(callers)
    else:
        if target_module:
            importers = find_importers(target_module)
            result["module"] = target_module
            result["direct_importers"] = sorted({
                p.relative_to(ROOT).as_posix() for p in importers
            })
            result["importer_count"] = len(result["direct_importers"])

            # 2. seviye etki (importer'larin importer'lari)
            second: set[str] = set()
            for imp in importers:
                imp_module = module_name_from_path(imp)
                for p in find_importers(imp_module):
                    second.add(p.relative_to(ROOT).as_posix())
            result["indirect_importers"] = sorted(second - set(result["direct_importers"]))

    return result


def print_report(data: dict[str, Any]) -> None:
    if "error" in data:
        print(f"HATA: {data['error']}")
        return
    print(f"ETKI ANALIZI — {data['target']}")
    print(f"Bolge: {data['zone']}")
    for w in data["warnings"]:
        print(f"  !! {w}")
    if "function" in data:
        print(f"\nFonksiyon: {data['function']}")
        print(f"Cagiran sayisi: {data['caller_count']}")
        for c in data["callers"][:30]:
            print(f"  {c['file']}:{c['line']}")
        if data["caller_count"] > 30:
            print(f"  ... +{data['caller_count'] - 30} daha")
    if "module" in data:
        print(f"\nModul: {data['module']}")
        print(f"Dogrudan import eden: {data['importer_count']} dosya")
        for imp in data["direct_importers"][:30]:
            imp_zone = zone_for(imp)
            marker = "[K]" if imp_zone == "KIRMIZI" else "[S]" if imp_zone == "SARI" else "[Y]"
            print(f"  {marker} {imp}")
        if data["importer_count"] > 30:
            print(f"  ... +{data['importer_count'] - 30} daha")
        print(f"\nDolayli tuketici (2. seviye): {len(data['indirect_importers'])} dosya")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    target = sys.argv[1]
    as_json = "--json" in sys.argv[2:]
    data = analyze(target)
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print_report(data)
    return 0 if "error" not in data else 2


if __name__ == "__main__":
    sys.exit(main())
