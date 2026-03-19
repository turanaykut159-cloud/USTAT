"""
ÜSTAT v5.5.1 — Syntax Error Fix
================================
v2 fix sonrası kalan fazlalık except bloğunu kaldırır.
"""
import os, shutil

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(SCRIPT_DIR, "engine", "mt5_bridge.py")

with open(BRIDGE, "r", encoding="utf-8") as f:
    content = f.read()

# Fazlalık except bloğu (v2 fix'ten sonra kalan eski circuit breaker)
BAD_BLOCK = """                    raise
            except Exception as exc:
                # v5.5.1: Tüm exception'ları circuit breaker'a kaydet
                # (OSError, RuntimeError vb. — sadece TimeoutError değil)
                self._cb_record_failure()
                logger.error(
                    f"MT5 API EXCEPTION: {func.__name__}({args}) — "
                    f"{type(exc).__name__}: {exc}"
                )
                raise

    # ── property"""

GOOD_BLOCK = """                    raise

    # ── property"""

if BAD_BLOCK in content:
    shutil.copy2(BRIDGE, BRIDGE + ".bak.v3")
    content = content.replace(BAD_BLOCK, GOOD_BLOCK)
    with open(BRIDGE, "w", encoding="utf-8") as f:
        f.write(content)
    print("\033[92m✓ Syntax hatası düzeltildi!\033[0m")
else:
    print("\033[92m✓ Syntax hatası zaten yok.\033[0m")

# __pycache__ temizle
import shutil as sh2
for root, dirs, _ in os.walk(SCRIPT_DIR):
    for d in list(dirs):
        if d == "__pycache__":
            try: sh2.rmtree(os.path.join(root, d))
            except: pass

# Doğrula
try:
    with open(BRIDGE, "r", encoding="utf-8") as f:
        compile(f.read(), BRIDGE, "exec")
    print("\033[92m✓ Syntax doğrulama BAŞARILI — ÜSTAT'ı başlatın.\033[0m")
except SyntaxError as e:
    print(f"\033[91m✗ Hâlâ syntax hatası var: {e}\033[0m")
