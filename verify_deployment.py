"""ÜSTAT — Deployment Doğrulama Scripti

Her deployment öncesi çalıştırılır. Eski kod riski, versiyon tutarsızlığı,
cache kalıntısı ve eksik build gibi sorunları OTOMATIK tespit eder.

Kullanım:
    python verify_deployment.py          # Tam kontrol
    python verify_deployment.py --fix    # Sorunları otomatik düzelt

Knight Capital Dersi: Ölü kod production'da KALMAZ.
Bu script o dersin otomatik koruma katmanıdır.
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent
ENGINE = ROOT / "engine"
DESKTOP = ROOT / "desktop"
CONFIG = ROOT / "config" / "default.json"

PASS = "OK"
FAIL = "FAIL"
WARN = "UYARI"

results = []
fix_mode = "--fix" in sys.argv


def check(name: str, passed: bool, detail: str = "", fix_fn=None):
    """Kontrol sonucu kaydet."""
    status = PASS if passed else FAIL
    results.append((name, status, detail))
    if not passed and fix_mode and fix_fn:
        print(f"  DUZELTILIYOR: {name}")
        fix_fn()
        results[-1] = (name, PASS, f"{detail} (DUZELTILDI)")


def warn(name: str, detail: str):
    results.append((name, WARN, detail))


# ═══════════════════════════════════════════════════════════════════
#  1. ESKİ PYTHON CACHE KONTROLÜ
# ═══════════════════════════════════════════════════════════════════

def check_old_pycache():
    """Python 3.10/3.11/3.12/3.13 bytecode kalıntısı var mı?"""
    old_files = []
    for root, dirs, files in os.walk(ROOT):
        if "node_modules" in root or "DEPO" in root or ".git" in root:
            continue
        for f in files:
            if f.endswith(".pyc") and "cpython-314" not in f:
                old_files.append(os.path.join(root, f))

    def fix():
        for f in old_files:
            os.remove(f)

    check(
        "Eski Python cache",
        len(old_files) == 0,
        f"{len(old_files)} eski .pyc dosyası" if old_files else "",
        fix_fn=fix,
    )


# ═══════════════════════════════════════════════════════════════════
#  2. BACKUP DOSYA KONTROLÜ (Knight Capital)
# ═══════════════════════════════════════════════════════════════════

def check_backup_files():
    """Ölü .bak/.backup dosyaları var mı?"""
    bad_extensions = (".bak", ".backup", ".old", ".orig")
    dead_files = []
    for root, dirs, files in os.walk(ROOT):
        if "node_modules" in root or "DEPO" in root or ".git" in root or "archive" in root:
            continue
        for f in files:
            if any(f.endswith(ext) or ".bak." in f for ext in bad_extensions):
                dead_files.append(os.path.join(root, f))

    def fix():
        for f in dead_files:
            os.remove(f)

    check(
        "Backup/ölü dosyalar",
        len(dead_files) == 0,
        f"{len(dead_files)} dosya: {', '.join(Path(f).name for f in dead_files[:5])}" if dead_files else "",
        fix_fn=fix,
    )


# ═══════════════════════════════════════════════════════════════════
#  3. VERSİYON TUTARLILIĞI
# ═══════════════════════════════════════════════════════════════════

def check_version_consistency():
    """Tüm versiyon noktaları aynı mı?"""
    versions = {}

    # engine/__init__.py
    init_path = ENGINE / "__init__.py"
    if init_path.exists():
        for line in init_path.read_text().splitlines():
            if "VERSION" in line and "=" in line:
                v = line.split("=")[1].strip().strip("'\"")
                versions["engine/__init__.py"] = v
                break

    # config/default.json
    if CONFIG.exists():
        cfg = json.loads(CONFIG.read_text())
        versions["config/default.json"] = cfg.get("version", "?")

    # desktop/package.json
    pkg_path = DESKTOP / "package.json"
    if pkg_path.exists():
        pkg = json.loads(pkg_path.read_text())
        versions["desktop/package.json"] = pkg.get("version", "?")

    # Settings.jsx
    settings_path = DESKTOP / "src" / "components" / "Settings.jsx"
    if settings_path.exists():
        for line in settings_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "const VERSION" in line and "=" in line:
                v = line.split("=")[1].strip().strip("'\"; ")
                versions["Settings.jsx"] = v
                break

    unique = set(versions.values())
    all_same = len(unique) <= 1

    check(
        "Versiyon tutarlılığı",
        all_same,
        f"Farkli versiyonlar: {versions}" if not all_same else f"v{list(unique)[0] if unique else '?'}",
    )


# ═══════════════════════════════════════════════════════════════════
#  4. BUILD GÜNCELLIĞI
# ═══════════════════════════════════════════════════════════════════

def check_build_freshness():
    """Desktop build kaynak dosyalardan eski mi?"""
    dist_dir = DESKTOP / "dist"
    if not dist_dir.exists():
        check("Build mevcut", False, "desktop/dist/ yok — build alınmamış")
        return

    # Build'in en eski dosyasının zamanı
    build_files = list(dist_dir.rglob("*"))
    if not build_files:
        check("Build mevcut", False, "desktop/dist/ boş")
        return

    build_time = min(f.stat().st_mtime for f in build_files if f.is_file())

    # Kaynak dosyaların en yeni değişiklik zamanı
    src_dir = DESKTOP / "src"
    if not src_dir.exists():
        return

    src_files = list(src_dir.rglob("*.jsx")) + list(src_dir.rglob("*.js")) + list(src_dir.rglob("*.css"))
    if not src_files:
        return

    newest_src = max(f.stat().st_mtime for f in src_files)

    is_fresh = build_time >= newest_src

    def fix():
        subprocess.run(
            ["npx", "vite", "build", "--mode", "production"],
            cwd=str(DESKTOP), capture_output=True, timeout=60,
        )

    check(
        "Build güncelliği",
        is_fresh,
        f"Build {datetime.fromtimestamp(build_time):%H:%M}, kaynak {datetime.fromtimestamp(newest_src):%H:%M}" if not is_fresh else "",
        fix_fn=fix,
    )


# ═══════════════════════════════════════════════════════════════════
#  5. GIT DURUM KONTROLÜ
# ═══════════════════════════════════════════════════════════════════

def check_git_status():
    """Commit'siz kod değişikliği var mı?"""
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    changed = [
        f for f in result.stdout.strip().splitlines()
        if f.endswith((".py", ".jsx", ".js", ".json", ".css"))
        and "engine.heartbeat" not in f
    ]

    check(
        "Commit'siz kod",
        len(changed) == 0,
        f"{len(changed)} dosya: {', '.join(changed[:5])}" if changed else "",
    )


# ═══════════════════════════════════════════════════════════════════
#  6. PYTHON VERSİYONU
# ═══════════════════════════════════════════════════════════════════

def check_python_version():
    """Doğru Python versiyonu kullanılıyor mu?"""
    v = sys.version_info
    version_str = f"{v.major}.{v.minor}.{v.micro}"
    is_ok = v.major == 3 and v.minor >= 14

    check(
        "Python versiyonu",
        is_ok,
        f"Python {version_str}" + (" (eski!)" if not is_ok else ""),
    )


# ═══════════════════════════════════════════════════════════════════
#  7. KRİTİK DOSYA BÜTÜNLÜĞÜ
# ═══════════════════════════════════════════════════════════════════

def check_critical_files():
    """8 Kırmızı Bölge dosyası mevcut mu?"""
    critical = [
        "engine/baba.py", "engine/ogul.py", "engine/mt5_bridge.py",
        "engine/main.py", "engine/ustat.py", "engine/database.py",
        "engine/data_pipeline.py", "config/default.json",
    ]
    missing = [f for f in critical if not (ROOT / f).exists()]

    check(
        "Kritik dosyalar",
        len(missing) == 0,
        f"EKSİK: {', '.join(missing)}" if missing else "8/8 mevcut",
    )


# ═══════════════════════════════════════════════════════════════════
#  8. IMPORT TEST
# ═══════════════════════════════════════════════════════════════════

def check_imports():
    """Tüm engine modülleri import edilebiliyor mu?"""
    modules = [
        "engine.baba", "engine.ogul", "engine.h_engine", "engine.main",
        "engine.mt5_bridge", "engine.database", "engine.data_pipeline",
        "engine.top5_selection", "engine.config", "engine.manuel_motor",
    ]
    failed = []
    for mod in modules:
        try:
            __import__(mod)
        except Exception as e:
            failed.append(f"{mod}: {e}")

    check(
        "Modül import",
        len(failed) == 0,
        f"{len(failed)} hata: {failed[0]}" if failed else f"{len(modules)}/{len(modules)} OK",
    )


# ═══════════════════════════════════════════════════════════════════
#  9. VADE TAKVİMİ
# ═══════════════════════════════════════════════════════════════════

def check_expiry_calendar():
    """Gelecek 3 ayın vade tarihleri tanımlı mı?"""
    try:
        from engine.baba import VIOP_EXPIRY_DATES
        from datetime import date, timedelta
        today = date.today()
        three_months = today + timedelta(days=90)
        future = [d for d in VIOP_EXPIRY_DATES if today <= d <= three_months]
        check(
            "Vade takvimi",
            len(future) >= 2,
            f"{len(future)} vade tanımlı (sonraki 3 ay)" if future else "EKSİK!",
        )
    except Exception as e:
        check("Vade takvimi", False, str(e))


# ═══════════════════════════════════════════════════════════════════
#  10. TATİL TAKVİMİ
# ═══════════════════════════════════════════════════════════════════

def check_holiday_calendar():
    """Yıl sonuna kadar tatiller tanımlı mı?"""
    try:
        from engine.utils.time_utils import ALL_HOLIDAYS
        from datetime import date
        today = date.today()
        future = [d for d in ALL_HOLIDAYS if d >= today]
        check(
            "Tatil takvimi",
            len(future) >= 5,
            f"{len(future)} tatil tanımlı" if future else "EKSİK!",
        )
    except Exception as e:
        check("Tatil takvimi", False, str(e))


# ═══════════════════════════════════════════════════════════════════
#  ÇALIŞTIR
# ═══════════════════════════════════════════════════════════════════

def main():
    print()
    print("=" * 60)
    print("  ÜSTAT — DEPLOYMENT DOĞRULAMA")
    print(f"  Tarih: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"  Mod: {'DÜZELT' if fix_mode else 'KONTROL'}")
    print("=" * 60)
    print()

    check_old_pycache()
    check_backup_files()
    check_version_consistency()
    check_build_freshness()
    check_git_status()
    check_python_version()
    check_critical_files()
    check_imports()
    check_expiry_calendar()
    check_holiday_calendar()

    # Sonuçları yazdır
    pass_count = sum(1 for _, s, _ in results if s == PASS)
    fail_count = sum(1 for _, s, _ in results if s == FAIL)
    warn_count = sum(1 for _, s, _ in results if s == WARN)

    for name, status, detail in results:
        icon = {"OK": "+", "FAIL": "X", "UYARI": "!"}[status]
        detail_str = f" — {detail}" if detail else ""
        print(f"  [{icon}] {name:<30} {status}{detail_str}")

    print()
    print("-" * 60)
    print(f"  SONUC: {pass_count} OK, {fail_count} FAIL, {warn_count} UYARI")

    if fail_count > 0:
        print()
        print("  DEPLOYMENT YAPILAMAZ — önce FAIL sorunları düzeltin.")
        if not fix_mode:
            print("  Otomatik düzeltme: python verify_deployment.py --fix")
        print()
        sys.exit(1)
    else:
        print("  DEPLOYMENT GÜVENLİ — tüm kontroller geçti.")
        print()
        sys.exit(0)


if __name__ == "__main__":
    main()
