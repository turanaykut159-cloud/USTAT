"""
ÜSTAT v5.5.1 — order_send Fix v3 (FINAL)
==========================================
KÖK NEDEN: Python 3.14'te func(*args, **kwargs) ile doğrudan func(arg)
farklı C-level çağrı mekanizması kullanıyor. MT5 C extension
**kwargs geçildiğinde (boş olsa bile) argümanları reddediyor.

ÇÖZÜM: order_send için func(*args, **kwargs) yerine
doğrudan mt5.order_send(args[0]) çağır.
"""
import os, sys, shutil

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(SCRIPT_DIR, "engine", "mt5_bridge.py")

with open(BRIDGE, "r", encoding="utf-8") as f:
    content = f.read()

# v2 fix'in order_send bloğunu bul ve düzelt
OLD = """        if _is_write_op:
            # ── YAZMA: Doğrudan çağrı (ThreadPoolExecutor YOK) ──
            try:
                result = func(*args, **kwargs)
                self._cb_record_success()
                return result"""

NEW = """        if _is_write_op:
            # ── YAZMA: Doğrudan çağrı (ThreadPoolExecutor YOK) ──
            # v3: func(*args, **kwargs) yerine func(args[0]) kullan.
            # Python 3.14 vectorcall + MT5 C extension uyumsuzluğu:
            # **kwargs (boş bile olsa) geçildiğinde C extension reddediyor.
            try:
                result = func(args[0]) if args else func()
                self._cb_record_success()
                return result"""

if OLD in content:
    shutil.copy2(BRIDGE, BRIDGE + ".bak.v3")
    content = content.replace(OLD, NEW)
    with open(BRIDGE, "w", encoding="utf-8") as f:
        f.write(content)
    print("\033[92m✓ v3 fix uygulandı — func(args[0]) doğrudan çağrı\033[0m")
elif "func(args[0]) if args else func()" in content:
    print("\033[92m✓ v3 fix zaten mevcut.\033[0m")
else:
    print("\033[91m✗ v2 bloğu bulunamadı. Manuel kontrol gerekli.\033[0m")
    sys.exit(1)

# __pycache__ temizle
for root, dirs, _ in os.walk(SCRIPT_DIR):
    for d in list(dirs):
        if d == "__pycache__":
            try: shutil.rmtree(os.path.join(root, d))
            except: pass

# Doğrula
with open(BRIDGE, "r", encoding="utf-8") as f:
    code = f.read()
try:
    compile(code, BRIDGE, "exec")
    if "func(args[0])" in code:
        print("\033[92m✓ Syntax OK + doğrulama BAŞARILI\033[0m")
        print("\033[92m  ÜSTAT'ı yeniden başlatın.\033[0m")
    else:
        print("\033[91m✗ Fix uygulanamadı\033[0m")
except SyntaxError as e:
    print(f"\033[91m✗ Syntax hatası: {e}\033[0m")
