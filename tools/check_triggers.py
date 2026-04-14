#!/usr/bin/env python3
"""USTAT Anayasa v3.0 — Koruma Tetik Kontrolu

Her degisiklik oncesi cagrilir. Verilen dosyalar ve opsiyonel diff uzerinde
triggers.yaml'daki tetikleri degerlendirir, sonuc raporu dondurur.

Kullanim:
  python tools/check_triggers.py <file1> [file2 ...]
  python tools/check_triggers.py --from-git-staged
  python tools/check_triggers.py --diff-file <path>

Cikis kodu:
  0 - Temiz (trigger yok veya sadece require_*)
  2 - class_escalate/auditor trigger aktif (onay gerekli)
  3 - halt trigger aktif (degisiklik yasak)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("pyyaml gerekli: pip install pyyaml --break-system-packages", file=sys.stderr)
    sys.exit(10)

ROOT = Path(__file__).resolve().parent.parent
GOVERNANCE = ROOT / "governance"


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def classify_zone(file_path: str, protected: dict, matrix: dict) -> str:
    """Dosya hangi zone'da?"""
    path_normalized = file_path.replace("\\", "/")
    for entry in protected.get("protected_files", []):
        if entry["path"].replace("\\", "/") == path_normalized:
            return "red"
    for y in matrix.get("yellow_zone", []):
        if y.replace("\\", "/") == path_normalized:
            return "yellow"
    return "green"


def get_staged_files() -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=ROOT, capture_output=True, text=True, check=True,
        encoding="utf-8", errors="replace",
    ).stdout
    return [l for l in out.strip().split("\n") if l]


def read_diff(files: list[str]) -> str:
    """Git diff (staged + worktree) birlesik text — UTF-8 zorla.

    Default text=True Windows'ta cp1254 kullanir; binary patch hunk veya
    Turkce karakter icin UnicodeDecodeError olusur. errors=replace ile
    bozuk byte'lar kayipla da olsa devam eder (analiz icin yeterli).
    """
    out = subprocess.run(
        ["git", "diff", "HEAD", "--"] + files,
        cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    ).stdout
    return out


def scan_triggers(files: list[str], diff_text: str, protected: dict,
                  matrix: dict, triggers: dict) -> list[dict]:
    """Aktif tetikleri bul."""
    active = []
    # AX-7 tarayici: mt5.initialize cagrisi engine/mt5_bridge.py disinda mi?
    for m in re.finditer(r"\+.*mt5\.initialize\s*\(", diff_text):
        line = m.group(0)
        # Hangi dosyada?
        context_idx = diff_text.rfind("diff --git", 0, m.start())
        if context_idx >= 0:
            header = diff_text[context_idx:m.start()]
            if "engine/mt5_bridge.py" not in header:
                active.append({"id": "TR-AX7", "effect": "halt",
                               "reason": "Yeni mt5.initialize cagrisi mt5_bridge.py DISINDA",
                               "detail": line.strip()})
                break

    # TR-AX1 / TR-CALL-ORDER: main.py _run_single_cycle icinde sira degisimi
    if any(f.endswith("main.py") and "engine" in f for f in files):
        for m in re.finditer(r"_run_single_cycle", diff_text):
            ctx_start = max(0, m.start() - 200)
            ctx = diff_text[ctx_start:m.end() + 400]
            if any(mark in ctx for mark in ["BABA", "OGUL", "baba.run", "ogul.run"]):
                if "+" in ctx and any(k in ctx for k in ["baba", "ogul", "h_engine", "ustat"]):
                    active.append({"id": "TR-AX1", "effect": "halt",
                                   "reason": "main loop sirasina dokunuldu",
                                   "detail": "manuel inceleme zorunlu"})
                    break

    # TR-CONFIG: config/default.json degisiyor mu?
    if any("config/default.json" in f for f in files):
        active.append({"id": "TR-CONFIG", "effect": "class_escalate",
                       "to_class": "C3", "require_diff": True,
                       "reason": "config/default.json degisiyor"})

    # TR-UI: desktop frontend
    if any(f.startswith("desktop/src/") and f.endswith((".jsx", ".js", ".ts", ".tsx"))
           for f in files):
        active.append({"id": "TR-UI", "effect": "require_build",
                       "reason": "Frontend degisikligi — npm run build gerekli"})

    # TR-API: api schema/routes
    if any(f.startswith("api/") and f.endswith(".py") for f in files):
        active.append({"id": "TR-API", "effect": "class_escalate",
                       "to_class": "C2", "require_test": True,
                       "reason": "API contract degisimi"})

    # TR-SCHEMA: SQL schema
    if re.search(r"\+\s*(CREATE|ALTER|DROP)\s+TABLE", diff_text, re.IGNORECASE):
        active.append({"id": "TR-SCHEMA", "effect": "class_escalate",
                       "to_class": "C3", "require_backup": True,
                       "reason": "SQL schema degisimi"})

    # TR-RED-30: Kirmizi Bolge'de 30+ satir
    red_lines = 0
    for f in files:
        zone = classify_zone(f, protected, matrix)
        if zone == "red":
            # o dosyanin diff'indeki +/- satir sayisi
            pattern = re.compile(rf"diff --git a/{re.escape(f)}.*?(?=diff --git|\Z)", re.DOTALL)
            match = pattern.search(diff_text)
            if match:
                changed = sum(1 for line in match.group(0).split("\n")
                              if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))
                red_lines += changed
    if red_lines >= 30:
        active.append({"id": "TR-RED-30", "effect": "require_auditor",
                       "reason": f"Kirmizi Bolge'de {red_lines} satir degisim"})

    # TR-CRITICAL-FLOW: her zaman aktif
    active.append({"id": "TR-CRITICAL-FLOW", "effect": "require_test",
                   "test_target": "tests/critical_flows",
                   "reason": "Her commit oncesi kritik akis testi"})

    return active


def main() -> int:
    # Windows cp1254 codec hatasini onle — UTF-8 stdout zorla
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    p = argparse.ArgumentParser()
    p.add_argument("files", nargs="*")
    p.add_argument("--from-git-staged", action="store_true")
    p.add_argument("--json", action="store_true", help="JSON output")
    args = p.parse_args()

    files = args.files[:]
    if args.from_git_staged:
        files.extend(get_staged_files())
    if not files:
        print("Hicbir dosya verilmedi", file=sys.stderr)
        return 1

    protected = load_yaml(GOVERNANCE / "protected_assets.yaml")
    matrix = load_yaml(GOVERNANCE / "authority_matrix.yaml")
    triggers = load_yaml(GOVERNANCE / "triggers.yaml")
    diff_text = read_diff(files)

    active = scan_triggers(files, diff_text, protected, matrix, triggers)

    if args.json:
        print(json.dumps({"files": files, "triggers": active}, indent=2, ensure_ascii=False))
    else:
        print(f"Tetik kontrolu — {len(files)} dosya, {len(active)} aktif tetik")
        for t in active:
            print(f"  [{t['effect']:>18}] {t['id']:<12} — {t['reason']}")

    # Cikis kodu
    has_halt = any(t["effect"] == "halt" for t in active)
    has_escalate = any(t["effect"] in ("class_escalate", "require_auditor") for t in active)

    if has_halt:
        return 3
    if has_escalate:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
