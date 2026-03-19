"""
ÜSTAT v5.5.1 — order_send Direct Call Fix (v2)
================================================
MT5 C extension, order_send (yazma işlemi) çağrılarını
ThreadPoolExecutor worker thread'inden reddediyor.
Lambda fix yeterli değil — order_send'in doğrudan ana thread'de çağrılması gerekiyor.

Bu script _safe_call fonksiyonunu günceller:
  - order_send fonksiyonu tespit edildiğinde ThreadPoolExecutor KULLANILMAZ
  - Doğrudan ana thread'de çağrılır (timeout koruması signal ile sağlanır)
  - Diğer tüm MT5 fonksiyonları (okuma) eski gibi ThreadPoolExecutor'da çalışır

KULLANIM:
  1. ÜSTAT'ı kapat
  2. python fix_order_send_v2.py
  3. ÜSTAT'ı tekrar aç
"""

import os
import sys
import shutil

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BRIDGE_FILE = os.path.join(SCRIPT_DIR, "engine", "mt5_bridge.py")
BACKUP_FILE = BRIDGE_FILE + ".bak.v2"

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


def main():
    print(f"\n{BOLD}{CYAN}{'='*60}{RESET}")
    print(f"{BOLD}{CYAN}  ÜSTAT v5.5.1 — order_send Direct Call Fix (v2){RESET}")
    print(f"{BOLD}{CYAN}{'='*60}{RESET}\n")

    if not os.path.exists(BRIDGE_FILE):
        print(f"{RED}HATA: {BRIDGE_FILE} bulunamadı!{RESET}")
        sys.exit(1)

    with open(BRIDGE_FILE, "r", encoding="utf-8") as f:
        content = f.read()
        lines = content.split("\n")

    # ── _safe_call fonksiyonunu bul ve değiştir ──
    # Mevcut _safe_call'ın "with concurrent.futures.ThreadPoolExecutor" satırını bul

    # Eski _safe_call bloğu (lambda fix dahil)
    OLD_BLOCK = """        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(lambda: func(*args, **kwargs))
            try:
                result = future.result(timeout=timeout)
                self._cb_record_success()
                return result
            except concurrent.futures.TimeoutError:
                self._cb_record_failure()
                logger.error(
                    f"MT5 API TIMEOUT ({timeout}s): {func.__name__}({args}) — "
                    f"terminal donmuş olabilir, reconnect tetiklenecek"
                )
                self._connected = False
                if self._health:
                    self._health.record_disconnect()
                raise TimeoutError(
                    f"MT5 {func.__name__} çağrısı {timeout}s içinde yanıt vermedi"
                )"""

    NEW_BLOCK = """        # v5.5.1: order_send yazma işlemlerini ana thread'de çağır.
        # MT5 C extension, order_send'i worker thread'den reddediyor.
        # Okuma fonksiyonları (copy_rates, symbol_info vb.) thread-safe.
        _is_write_op = func.__name__ == "order_send"

        if _is_write_op:
            # ── YAZMA: Doğrudan çağrı (ThreadPoolExecutor YOK) ──
            try:
                result = func(*args, **kwargs)
                self._cb_record_success()
                return result
            except Exception as exc:
                self._cb_record_failure()
                logger.error(
                    f"MT5 order_send EXCEPTION: {func.__name__}({args}) — "
                    f"{type(exc).__name__}: {exc}"
                )
                raise
        else:
            # ── OKUMA: ThreadPoolExecutor ile timeout korumalı ──
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(lambda: func(*args, **kwargs))
                try:
                    result = future.result(timeout=timeout)
                    self._cb_record_success()
                    return result
                except concurrent.futures.TimeoutError:
                    self._cb_record_failure()
                    logger.error(
                        f"MT5 API TIMEOUT ({timeout}s): {func.__name__}({args}) — "
                        f"terminal donmuş olabilir, reconnect tetiklenecek"
                    )
                    self._connected = False
                    if self._health:
                        self._health.record_disconnect()
                    raise TimeoutError(
                        f"MT5 {func.__name__} çağrısı {timeout}s içinde yanıt vermedi"
                    )
                except Exception as exc:
                    self._cb_record_failure()
                    logger.error(
                        f"MT5 API EXCEPTION: {func.__name__}({args}) — "
                        f"{type(exc).__name__}: {exc}"
                    )
                    raise"""

    if OLD_BLOCK in content:
        print(f"  {GREEN}Eski _safe_call bloğu bulundu (lambda fix mevcut){RESET}")
        content = content.replace(OLD_BLOCK, NEW_BLOCK)
        applied = True
    else:
        # Lambda fix olmayan eski versiyonu da dene
        OLD_BLOCK_NO_LAMBDA = OLD_BLOCK.replace(
            "future = executor.submit(lambda: func(*args, **kwargs))",
            "future = executor.submit(func, *args, **kwargs)"
        )
        if OLD_BLOCK_NO_LAMBDA in content:
            print(f"  {YELLOW}Eski _safe_call bloğu bulundu (lambda fix YOK){RESET}")
            content = content.replace(OLD_BLOCK_NO_LAMBDA, NEW_BLOCK)
            applied = True
        else:
            # v2 fix zaten uygulanmış mı?
            if "_is_write_op = func.__name__" in content:
                print(f"  {GREEN}✓ v2 fix zaten uygulanmış — değişiklik gerekmedi.{RESET}")
                applied = False
            else:
                print(f"  {RED}HATA: _safe_call bloğu tanınamadı!{RESET}")
                print(f"  {YELLOW}Manuel kontrol gerekli.{RESET}")
                # Debug
                for i, line in enumerate(lines, 1):
                    if "executor.submit" in line or "ThreadPoolExecutor" in line:
                        print(f"    Satır {i}: {line.strip()}")
                sys.exit(1)

    if applied:
        # Yedek al
        shutil.copy2(BRIDGE_FILE, BACKUP_FILE)
        print(f"  Yedek: {BACKUP_FILE}")

        # Yaz
        with open(BRIDGE_FILE, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  {GREEN}{BOLD}✓ v2 fix uygulandı!{RESET}")

    # __pycache__ temizliği
    print(f"\n  __pycache__ temizleniyor...")
    cache_count = 0
    for root, dirs, files in os.walk(SCRIPT_DIR):
        for d in list(dirs):
            if d == "__pycache__":
                cache_path = os.path.join(root, d)
                try:
                    shutil.rmtree(cache_path)
                    cache_count += 1
                except Exception as e:
                    print(f"    {YELLOW}Silinemedi: {cache_path} — {e}{RESET}")
    print(f"  {GREEN}✓ {cache_count} __pycache__ dizini silindi{RESET}")

    # Doğrulama
    with open(BRIDGE_FILE, "r", encoding="utf-8") as f:
        verify = f.read()

    if "_is_write_op = func.__name__" in verify and "order_send" in verify:
        print(f"\n  {GREEN}{BOLD}═══ DOĞRULAMA BAŞARILI ═══{RESET}")
        print(f"  {GREEN}order_send artık doğrudan çağrılacak (ThreadPoolExecutor yok).{RESET}")
        print(f"  {GREEN}Diğer MT5 fonksiyonları hâlâ timeout korumalı.{RESET}")
        print(f"  {GREEN}ÜSTAT'ı yeniden başlatın.{RESET}")
    else:
        print(f"\n  {RED}{BOLD}═══ DOĞRULAMA BAŞARISIZ ═══{RESET}")
        sys.exit(1)

    print()


if __name__ == "__main__":
    main()
