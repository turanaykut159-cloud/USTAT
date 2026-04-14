#!/usr/bin/env python3
"""USTAT Anayasa v3.0 — Degisiklik Muhurleme (Seal)

Anayasa Bolum 7 "Islemi Bitir" adimlarini otomatize eder.
Claude edit/write yaptiktan sonra bu scripti cagirir.

Adimlar:
  1. check_triggers (halt -> dur)
  2. critical_flows test
  3. UI dosyasi varsa npm run build
  4. changelog satirini USTAT_GELISIM_TARIHCESI.md'ye ekle
  5. git add (sadece declared dosyalar)
  6. git commit

Kullanim:
  python tools/seal_change.py \
    --zone green --class C1 \
    --files desktop/src/components/PrimnetDetail.jsx \
    --commit-msg "fix(primnet): T10.6 K/Z fiyat-bazli"

  --mission M-ID          Misyon ID (decisions.yaml'a kaydolur)
  --changelog-category    Added/Changed/Fixed/Removed/Security (default: Fixed)
  --changelog-entry       Tek satir tarihce girisi (default: commit-msg)
  --skip-build            Build'i atla (ornek: sadece Python degisti)
  --skip-test             Test'i atla (TEHLIKELI — sadece acil durumda)
  --dry-run               Hicbir seyi yapma, ne yapilacagini yazdir
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "docs" / "USTAT_GELISIM_TARIHCESI.md"


def run(cmd: list[str], check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, check=check,
                          capture_output=capture, text=True)


def step_triggers(files: list[str]) -> int:
    print("[1/6] Tetik kontrolu...")
    r = run([sys.executable, "tools/check_triggers.py"] + files, check=False)
    if r.returncode == 3:
        print("   HALT — commit iptal")
        return r.returncode
    print(f"   -> exit {r.returncode}")
    return r.returncode


def step_test(skip: bool) -> int:
    if skip:
        print("[2/6] Test ATLANDI (--skip-test)")
        return 0
    print("[2/6] critical_flows test...")
    r = run(["python", "-m", "pytest", "tests/critical_flows", "-q", "--tb=short"],
            check=False)
    if r.returncode != 0:
        print("   KIRMIZI — commit iptal")
        return r.returncode
    print("   -> yesil")
    return 0


def step_build(files: list[str], skip: bool) -> int:
    needs_build = any(f.startswith("desktop/src/") and f.endswith((".jsx", ".js", ".ts", ".tsx"))
                      for f in files)
    if not needs_build:
        print("[3/6] Build gereksiz (UI dosyasi yok)")
        return 0
    if skip:
        print("[3/6] Build ATLANDI (--skip-build)")
        return 0
    print("[3/6] npm run build...")
    desktop = ROOT / "desktop"
    r = subprocess.run(["npm", "run", "build"], cwd=desktop, check=False,
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("   BUILD FAIL — commit iptal")
        print(r.stderr[-500:] if r.stderr else "")
        return r.returncode
    print("   -> yesil")
    return 0


def step_changelog(category: str, entry: str, mission: str | None) -> None:
    if not CHANGELOG.exists():
        print("[4/6] CHANGELOG yok, atlandi")
        return
    print(f"[4/6] CHANGELOG: {category} — {entry[:60]}...")
    today = datetime.now().strftime("%Y-%m-%d")
    text = CHANGELOG.read_text(encoding="utf-8")
    # Bugun icin bir blok var mi?
    header = f"## [Unreleased] - {today}"
    if header not in text:
        lines = text.split("\n")
        # Ilk ## satirindan once ekle
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.startswith("## "):
                insert_idx = i
                break
        new_block = [header, "", f"### {category}", f"- {entry}" + (f" ({mission})" if mission else ""), ""]
        lines = lines[:insert_idx] + new_block + lines[insert_idx:]
        CHANGELOG.write_text("\n".join(lines), encoding="utf-8")
    else:
        # Mevcut bloga ekle
        lines = text.split("\n")
        # Header'in altinda ilgili category'yi bul
        idx = lines.index(header)
        cat_header = f"### {category}"
        cat_idx = None
        for j in range(idx + 1, min(idx + 40, len(lines))):
            if lines[j].startswith("## "):
                break
            if lines[j].strip() == cat_header:
                cat_idx = j
                break
        if cat_idx is None:
            lines.insert(idx + 2, cat_header)
            lines.insert(idx + 3, f"- {entry}" + (f" ({mission})" if mission else ""))
        else:
            lines.insert(cat_idx + 1, f"- {entry}" + (f" ({mission})" if mission else ""))
        CHANGELOG.write_text("\n".join(lines), encoding="utf-8")


def step_stage(files: list[str]) -> None:
    print(f"[5/6] git add (sadece declared): {len(files)} dosya + changelog")
    for f in files:
        run(["git", "add", f])
    run(["git", "add", str(CHANGELOG.relative_to(ROOT))], check=False)


def step_commit(msg: str) -> None:
    print(f"[6/6] git commit: {msg}")
    run(["git", "commit", "-m", msg])
    r = run(["git", "rev-parse", "HEAD"], capture=True)
    print(f"   -> {r.stdout.strip()}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--zone", required=True, choices=["green", "yellow", "red"])
    p.add_argument("--class", dest="cls", required=True,
                   choices=["C0", "C1", "C2", "C3", "C4"])
    p.add_argument("--files", nargs="+", required=True)
    p.add_argument("--commit-msg", required=True)
    p.add_argument("--mission", default=None)
    p.add_argument("--changelog-category", default="Fixed",
                   choices=["Added", "Changed", "Fixed", "Removed", "Security"])
    p.add_argument("--changelog-entry", default=None)
    p.add_argument("--skip-build", action="store_true")
    p.add_argument("--skip-test", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if args.dry_run:
        print(f"DRY-RUN: zone={args.zone} class={args.cls}")
        print(f"  Files: {args.files}")
        print(f"  Commit: {args.commit_msg}")
        print(f"  Mission: {args.mission}")
        return 0

    print(f"=== SEAL: {args.zone}/{args.cls} — {len(args.files)} dosya ===")

    rc = step_triggers(args.files)
    if rc == 3:
        return 3

    rc = step_test(args.skip_test)
    if rc != 0:
        return 2

    rc = step_build(args.files, args.skip_build)
    if rc != 0:
        return 4

    entry = args.changelog_entry or args.commit_msg
    step_changelog(args.changelog_category, entry, args.mission)
    step_stage(args.files)
    step_commit(args.commit_msg)

    print("=== SEAL tamam ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
