"""
ÜSTAT v5.5.1 — order_send Lambda Fix Yama Scripti
===================================================
Bu script mt5_bridge.py dosyasındaki _safe_call fonksiyonunu yamalayarak
ThreadPoolExecutor'ın MT5 C extension ile uyumsuzluğunu düzeltir.

SORUN:
  executor.submit(func, *args, **kwargs)
  → MT5 C extension positional argümanları reddediyor: (-2, 'Unnamed arguments not allowed')

ÇÖZÜM:
  executor.submit(lambda: func(*args, **kwargs))
  → Lambda closure argümanları doğru şekilde geçirir

KULLANIM:
  1. ÜSTAT'ı kapat
  2. Bu scripti çalıştır: python fix_order_send.py
  3. ÜSTAT'ı tekrar aç

Bu script:
  - mt5_bridge.py dosyasını okur
  - _safe_call'daki executor.submit satırını yamalır
  - Tüm __pycache__ dizinlerini siler
  - Yedek alır (mt5_bridge.py.bak)
"""

import os
import sys
import shutil

# ── Dosya yolları ──
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BRIDGE_FILE = os.path.join(SCRIPT_DIR, "engine", "mt5_bridge.py")
BACKUP_FILE = BRIDGE_FILE + ".bak"

# ── Renkli çıktı ──
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"

def main():
    print(f"\n{BOLD}{CYAN}{'='*60}{RESET}")
    print(f"{BOLD}{CYAN}  ÜSTAT v5.5.1 — Lambda Fix Yama Scripti{RESET}")
    print(f"{BOLD}{CYAN}{'='*60}{RESET}\n")

    # 1. Dosya kontrolü
    if not os.path.exists(BRIDGE_FILE):
        print(f"{RED}HATA: {BRIDGE_FILE} bulunamadı!{RESET}")
        sys.exit(1)

    print(f"  Dosya: {BRIDGE_FILE}")

    # 2. Dosyayı oku
    with open(BRIDGE_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    # 3. Eski kodu bul
    OLD_CODE = "future = executor.submit(func, *args, **kwargs)"
    NEW_CODE = "future = executor.submit(lambda: func(*args, **kwargs))"

    if OLD_CODE in content:
        print(f"\n  {YELLOW}ESKİ KOD BULUNDU:{RESET}")
        print(f"    {RED}{OLD_CODE}{RESET}")
        print(f"  {GREEN}YENİ KOD İLE DEĞİŞTİRİLİYOR:{RESET}")
        print(f"    {GREEN}{NEW_CODE}{RESET}")

        # 4. Yedek al
        shutil.copy2(BRIDGE_FILE, BACKUP_FILE)
        print(f"\n  Yedek: {BACKUP_FILE}")

        # 5. Yamala
        content = content.replace(OLD_CODE, NEW_CODE)

        with open(BRIDGE_FILE, "w", encoding="utf-8") as f:
            f.write(content)

        print(f"\n  {GREEN}{BOLD}✓ Lambda fix uygulandı!{RESET}")

    elif NEW_CODE in content:
        print(f"\n  {GREEN}✓ Lambda fix zaten mevcut — değişiklik gerekmedi.{RESET}")
    else:
        print(f"\n  {RED}HATA: Ne eski ne yeni kod bulunamadı!")
        print(f"  executor.submit satırı beklenenden farklı.{RESET}")
        # Debug: executor.submit satırlarını göster
        for i, line in enumerate(content.split("\n"), 1):
            if "executor.submit" in line:
                print(f"    Satır {i}: {line.strip()}")
        sys.exit(1)

    # 6. __pycache__ temizliği
    print(f"\n  __pycache__ temizleniyor...")
    cache_count = 0
    for root, dirs, files in os.walk(SCRIPT_DIR):
        for d in dirs:
            if d == "__pycache__":
                cache_path = os.path.join(root, d)
                try:
                    shutil.rmtree(cache_path)
                    cache_count += 1
                except Exception as e:
                    print(f"    {YELLOW}Silinemedi: {cache_path} — {e}{RESET}")
    print(f"  {GREEN}✓ {cache_count} __pycache__ dizini silindi{RESET}")

    # 7. Doğrulama — dosyayı tekrar oku ve kontrol et
    with open(BRIDGE_FILE, "r", encoding="utf-8") as f:
        verify = f.read()

    if NEW_CODE in verify:
        print(f"\n  {GREEN}{BOLD}═══ DOĞRULAMA BAŞARILI ═══{RESET}")
        print(f"  {GREEN}Lambda fix dosyada doğrulandı.{RESET}")
        print(f"  {GREEN}ÜSTAT'ı yeniden başlatın.{RESET}")
    else:
        print(f"\n  {RED}{BOLD}═══ DOĞRULAMA BAŞARISIZ ═══{RESET}")
        print(f"  {RED}Lambda fix dosyaya yazılamadı!{RESET}")
        print(f"  {RED}Dosya izinlerini kontrol edin.{RESET}")
        sys.exit(1)

    print()


if __name__ == "__main__":
    main()
