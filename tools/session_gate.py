#!/usr/bin/env python3
"""USTAT Anayasa v3.0 — Oturum Acilis Kapisi

Her oturum basinda ZORUNLU calisir. Gectigin kontroller:
  1. Workspace temiz mi? (git status)
  2. Baska oturum/ajan kilidi var mi? (.ustat_session.lock)
  3. Branch guncel mi?
  4. .gitattributes mevcut mu?
  5. governance/ butunlugu (axioms, authority_matrix, triggers)

Cikis kodu:
  0 - Gecis serbest
  1 - Kirli workspace (kullanici onayi gerekli)
  2 - Baska oturum aktif
  3 - Branch geride
  4 - governance eksik

Kullanim:
  python tools/session_gate.py --session-id <id> --agent <name> --mission <desc>
  python tools/session_gate.py --release    # Oturum kapanisinda lock'i birak
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK_FILE = ROOT / ".ustat_session.lock"
GOVERNANCE = ROOT / "governance"
REQUIRED_GOVERNANCE = ["axioms.yaml", "authority_matrix.yaml", "triggers.yaml", "protected_assets.yaml"]


def run(cmd: list[str], check: bool = False) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if check and proc.returncode != 0:
        print(f"HATA: {' '.join(cmd)}\n{proc.stderr}", file=sys.stderr)
        sys.exit(proc.returncode)
    return proc.returncode, proc.stdout, proc.stderr


def check_workspace_clean() -> tuple[bool, str]:
    """Workspace temiz mi?"""
    _, out, _ = run(["git", "status", "--porcelain"])
    lines = [l for l in out.strip().split("\n") if l]
    if not lines:
        return True, ""
    return False, f"{len(lines)} modified/untracked dosya\n" + "\n".join(lines[:20])


def check_lock(session_id: str) -> tuple[bool, str]:
    """Baska oturum lock'u var mi?"""
    if not LOCK_FILE.exists():
        return True, ""
    try:
        data = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    except Exception:
        return False, "Lock dosyasi okunamiyor (bozuk) — manuel inceleme gerek"
    if data.get("session_id") == session_id:
        return True, f"Lock zaten bu oturuma ait ({session_id})"
    return False, f"Baska oturum aktif: {data.get('agent', '?')} / {data.get('session_id', '?')} (baslangic: {data.get('started', '?')})"


def check_gitattributes() -> tuple[bool, str]:
    if (ROOT / ".gitattributes").exists():
        return True, ""
    return False, ".gitattributes yok — CRLF/LF sorunu riski yuksek"


def check_governance() -> tuple[bool, str]:
    missing = [f for f in REQUIRED_GOVERNANCE if not (GOVERNANCE / f).exists()]
    if missing:
        return False, f"governance eksik: {', '.join(missing)}"
    return True, ""


def check_branch_status() -> tuple[bool, str]:
    """Main'den kac commit geride?"""
    code, out, _ = run(["git", "rev-list", "--count", "HEAD..main"])
    if code != 0:
        return True, "(branch kontrolu atlandi — main referansi yok)"
    behind = int(out.strip() or "0")
    if behind > 0:
        return False, f"Main'den {behind} commit geride"
    return True, ""


def acquire_lock(session_id: str, agent: str, mission: str) -> None:
    data = {
        "session_id": session_id,
        "agent": agent,
        "pid": os.getpid(),
        "started": datetime.now().isoformat(timespec="seconds"),
        "mission": mission,
    }
    LOCK_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def release_lock() -> None:
    if LOCK_FILE.exists():
        LOCK_FILE.unlink()
        print("Lock birakildi.")
    else:
        print("Lock zaten yok.")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--session-id", default=f"S-{datetime.now():%Y%m%d-%H%M%S}")
    p.add_argument("--agent", default="claude-cowork")
    p.add_argument("--mission", default="(tanimsiz)")
    p.add_argument("--release", action="store_true")
    p.add_argument("--force", action="store_true", help="Kirli workspace'e ragmen gecis (sadece manuel onay sonrasi)")
    args = p.parse_args()

    if args.release:
        release_lock()
        return 0

    print(f"USTAT Session Gate v3.0 — session={args.session_id} agent={args.agent}")
    print(f"Mission: {args.mission}")
    print("-" * 60)

    errors = []

    ok, msg = check_governance()
    print(f"  [{'OK' if ok else 'FAIL'}] governance dosyalari: {msg or 'hepsi mevcut'}")
    if not ok:
        errors.append((4, msg))

    ok, msg = check_gitattributes()
    print(f"  [{'OK' if ok else 'WARN'}] .gitattributes: {msg or 'mevcut'}")

    ok, msg = check_lock(args.session_id)
    print(f"  [{'OK' if ok else 'FAIL'}] lock durumu: {msg or 'temiz'}")
    if not ok:
        errors.append((2, msg))

    ok, msg = check_workspace_clean()
    print(f"  [{'OK' if ok else 'FAIL'}] workspace: {msg or 'temiz'}")
    if not ok:
        errors.append((1, msg))

    ok, msg = check_branch_status()
    print(f"  [{'OK' if ok else 'WARN'}] branch: {msg or 'guncel'}")

    print("-" * 60)

    if errors:
        if args.force:
            print(f"UYARI: {len(errors)} kontrol basarisiz, --force ile geciliyor")
            acquire_lock(args.session_id, args.agent, args.mission)
            return 0
        print("GATE KAPALI — asagidaki sorunlar cozulmeli:")
        for code, msg in errors:
            print(f"  (exit {code}) {msg}")
        return errors[0][0]

    acquire_lock(args.session_id, args.agent, args.mission)
    print("GATE ACIK — lock alindi, oturum basliyor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
