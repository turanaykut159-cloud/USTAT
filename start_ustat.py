"""
USTAT v5.8 - Baslatici

API + Vite + Electron baslatir.
Her adimi PORT KONTROLU ile dogrulayarak ilerler.
Vite hazir olmadan Electron baslatilmaz.

Akis:
  0. Temizlik: Eski API + Electron + Vite process'lerini sonlandir
  1. API baslat (her zaman temiz instance, PID api.pid'e kaydedilir)
  2. Vite baslat (temiz instance)
  3. Electron baslat (DETACHED_PROCESS)

Yasam dongusu:
  Electron "Cikis" → main.js api.pid okur → taskkill ile API durdurulur
  Boylece USTAT kapali iken MT5'e hicbir sinyal gitmez.

Kullanim:
  python start_ustat.py        (konsol ile)
  wscript start_ustat.vbs      (VBS uzerinden gizli)
"""

import subprocess
import socket
import time
import os
import sys

# Otomatik: script neredeyse USTAT_DIR orasi olur (tasima destegi)
USTAT_DIR = os.path.dirname(os.path.abspath(__file__))
DESKTOP_DIR = os.path.join(USTAT_DIR, "desktop")
LOG_FILE = os.path.join(USTAT_DIR, "startup.log")
API_PID_FILE = os.path.join(USTAT_DIR, "api.pid")
CREATE_NO_WINDOW = 0x08000000


def log(msg):
    """Log mesajini dosyaya yaz."""
    ts = time.strftime("%H:%M:%S")
    line = f"{ts} | {msg}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except:
        pass


def port_open(port):
    """Port acik mi kontrol et (IPv4 + IPv6).

    NEDEN IKISI DE:
      Vite bazen sadece [::1]:5173 (IPv6) uzerinde dinliyor.
      Sadece 127.0.0.1 kontrol edilirse port bos sanilir,
      yeni Vite baslatilmaya calisilir, 'port already in use' hatasi alinir.
    """
    for host, family in [("127.0.0.1", socket.AF_INET), ("::1", socket.AF_INET6)]:
        try:
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                if s.connect_ex((host, port)) == 0:
                    return True
        except:
            pass
    return False


def wait_for_port(port, name, timeout_secs=15):
    """Port acilana kadar bekle (200ms aralikla hizli polling)."""
    max_checks = timeout_secs * 5  # 200ms × 5 = 1sn
    for i in range(max_checks):
        if port_open(port):
            elapsed = (i + 1) * 0.2
            log(f"  {name} hazir (port {port}, {elapsed:.1f}sn)")
            return True
        time.sleep(0.2)
    log(f"  HATA: {name} {timeout_secs}sn icinde baslamadi (port {port})")
    return False


def kill_port(port):
    """Belirtilen portu dinleyen process'i sonlandir.

    netstat -ano ile PID bulunur, taskkill ile oldurulur.
    """
    try:
        result = subprocess.run(
            f'netstat -ano | findstr ":{port} " | findstr "LISTENING"',
            capture_output=True, text=True, shell=True,
            creationflags=CREATE_NO_WINDOW,
        )
        killed = set()
        for line in result.stdout.strip().split("\n"):
            parts = line.strip().split()
            if len(parts) >= 5:
                pid = parts[-1]
                if pid not in killed and pid != "0":
                    r = subprocess.run(
                        ["taskkill", "/F", "/PID", pid],
                        capture_output=True, text=True,
                        creationflags=CREATE_NO_WINDOW,
                    )
                    if "SUCCESS" in r.stdout.upper():
                        log(f"  Port {port} -> PID {pid} sonlandirildi")
                        killed.add(pid)
                    else:
                        # taskkill başarısız (admin process) — CIM ile dene
                        r2 = subprocess.run(
                            ["powershell", "-Command",
                             f"Get-CimInstance Win32_Process -Filter 'ProcessId={pid}' "
                             f"| Invoke-CimMethod -MethodName Terminate"],
                            capture_output=True, text=True,
                            creationflags=CREATE_NO_WINDOW,
                        )
                        if "0" in r2.stdout:
                            log(f"  Port {port} -> PID {pid} sonlandirildi (CIM)")
                            killed.add(pid)
                        else:
                            log(f"  UYARI: Port {port} PID {pid} sonlandirilamadi!")
        return len(killed) > 0
    except:
        return False


def cleanup():
    """Eski API, Electron ve Vite process'lerini temizle (hizli, minimum bekleme)."""
    log("[0/3] Temizlik yapiliyor...")

    # 0. Eski API'yi kapat (api.pid dosyasindan PID oku)
    try:
        if os.path.exists(API_PID_FILE):
            pid = open(API_PID_FILE).read().strip()
            if pid:
                r = subprocess.run(
                    ["taskkill", "/F", "/PID", pid],
                    capture_output=True, text=True,
                    creationflags=CREATE_NO_WINDOW,
                )
                if "SUCCESS" in r.stdout.upper():
                    log(f"  Eski API sonlandirildi (PID {pid})")
            try:
                os.remove(API_PID_FILE)
            except Exception:
                pass
    except Exception:
        pass

    # Fallback: port 8000 hala aciksa kill_port ile temizle
    if port_open(8000):
        kill_port(8000)
        time.sleep(0.3)

    # 1. Eski electron.exe process'lerini oldur (bekleme yok)
    try:
        r = subprocess.run(
            ["taskkill", "/F", "/IM", "electron.exe"],
            capture_output=True, text=True,
            creationflags=CREATE_NO_WINDOW,
        )
        output = (r.stdout + r.stderr).upper()
        if "SUCCESS" in output:
            log("  Eski electron.exe sonlandirildi")
            time.sleep(0.3)  # Single-instance lock serbest kalmasi icin kisa bekleme
        if "ENGELLENDI" in output or "ACCESS" in output:
            log("  UYARI: electron.exe admin olarak calisiyor, taskkill ile durdurulamiyor!")
            log("  Gorev Yoneticisi'nden elle sonlandirin veya bilgisayari yeniden baslatin.")
    except Exception:
        pass

    # 2. Eski Vite temizle (port 5173) — kisa bekleme
    if port_open(5173):
        kill_port(5173)
        time.sleep(0.3)
        if port_open(5173):
            log("  UYARI: Port 5173 hala acik")
        else:
            log("  Port 5173 temizlendi")
    else:
        log("  Port 5173 zaten bos")


def start_api():
    """API sunucusunu baslat (her zaman temiz instance).

    Eski API cleanup()'da sonlandirilmis olmali.
    Port hala aciksa fallback olarak kill_port ile temizle.
    """
    if port_open(8000):
        log("[1/3] API hala calisiyor (port 8000), yeniden baslatiliyor...")
        kill_port(8000)
        time.sleep(1)

    log("[1/3] API baslatiliyor...")
    api_log = open(os.path.join(USTAT_DIR, "api.log"), "w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.server:app",
         "--host", "127.0.0.1", "--port", "8000"],
        cwd=USTAT_DIR,
        stdout=api_log,
        stderr=subprocess.STDOUT,
        creationflags=CREATE_NO_WINDOW,
    )

    # PID kaydet — Electron kapatilinca API'yi durdurmak icin
    try:
        with open(API_PID_FILE, "w") as f:
            f.write(str(proc.pid))
        log(f"  API PID: {proc.pid}")
    except Exception:
        pass

    return wait_for_port(8000, "API", 15)


def start_vite():
    """Vite dev server baslat (port bekleme YAPMAZ — Electron splash ile bekleyecek)."""
    if port_open(5173):
        log("[2/3] Vite zaten calisiyor (port 5173)")
        return True

    log("[2/3] Vite baslatiliyor (async — Electron bekleyecek)...")
    vite_log = open(os.path.join(USTAT_DIR, "vite.log"), "w")

    vite_cmd = os.path.join(DESKTOP_DIR, "node_modules", ".bin", "vite.cmd")

    if os.path.exists(vite_cmd):
        log(f"  Komut: {vite_cmd}")
        subprocess.Popen(
            [vite_cmd, "--port", "5173"],
            cwd=DESKTOP_DIR,
            stdout=vite_log,
            stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW,
        )
    else:
        vite_js = os.path.join(DESKTOP_DIR, "node_modules", "vite", "bin", "vite.js")
        if os.path.exists(vite_js):
            log(f"  vite.cmd yok, node ile: {vite_js}")
            subprocess.Popen(
                ["node", vite_js, "--port", "5173"],
                cwd=DESKTOP_DIR,
                stdout=vite_log,
                stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW,
            )
        else:
            log("  HATA: Vite bulunamadi! (ne vite.cmd ne vite.js)")
            return False

    log("  Vite arka planda baslatildi")
    return True


def build_frontend():
    """Vite production build olustur (FAZ 2.11)."""
    log("[BUILD] Vite production build baslatiliyor...")
    npm_cmd = os.path.join(DESKTOP_DIR, "node_modules", ".bin", "vite.cmd")
    if not os.path.exists(npm_cmd):
        # Fallback: npx
        npm_cmd = "npx"
        args = [npm_cmd, "vite", "build"]
    else:
        args = [npm_cmd, "build"]

    try:
        result = subprocess.run(
            args,
            cwd=DESKTOP_DIR,
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            log("  Build basarili")
            return True
        else:
            log(f"  Build hatasi: {result.stderr[:200]}")
            return False
    except Exception as e:
        log(f"  Build exception: {e}")
        return False


def start_electron():
    """Electron uygulamasini baslat."""
    is_prod = "--prod" in sys.argv
    log(f"[3/3] Electron baslatiliyor... (mod={'production' if is_prod else 'development'})")
    electron_exe = os.path.join(
        DESKTOP_DIR, "node_modules", "electron", "dist", "electron.exe"
    )
    if not os.path.exists(electron_exe):
        log(f"  HATA: electron.exe bulunamadi: {electron_exe}")
        return False

    log(f"  Exe: {electron_exe}")
    log(f"  CWD: {DESKTOP_DIR}")

    env = os.environ.copy()
    env["NODE_ENV"] = "production" if is_prod else "development"

    # DETACHED_PROCESS: Electron'u gizli Python'dan bagimsiz calistir.
    # Boylece Python'un konsol durumunu (SW_HIDE) miras ALMAZ,
    # kendi BrowserWindow'unu normal sekilde olusturabilir.
    DETACHED = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [electron_exe, "."],
        cwd=DESKTOP_DIR,
        env=env,
        creationflags=DETACHED,
    )
    log(f"  Electron baslatildi (DETACHED_PROCESS, NODE_ENV={env['NODE_ENV']})")
    return True


HEARTBEAT_FILE = os.path.join(USTAT_DIR, "engine.heartbeat")
SHUTDOWN_SIGNAL_FILE = os.path.join(USTAT_DIR, "shutdown.signal")  # v5.5: Electron kasıtlı kapanış sinyali
WATCHDOG_STALE_SECS = 45       # v5.4.1: heartbeat bu kadar saniye eskiyse engine ölmüş kabul et
WATCHDOG_CHECK_INTERVAL = 15   # v5.4.1: kontrol aralığı (saniye)
WATCHDOG_INITIAL_DELAY = 10    # v5.9.2: OTP bekleme kısaltıldı (Electron kendi bekliyor)
MAX_AUTO_RESTARTS = 5          # v5.4.1: maksimum ardışık otomatik yeniden başlatma
WATCHDOG_PID_FILE = os.path.join(USTAT_DIR, "watchdog.pid")  # v5.7.2: singleton watchdog kilidi


def check_shutdown_signal():
    """v5.5: Electron kasıtlı kapanış sinyali kontrolü.

    Electron 'safeQuit' ile kapanırken shutdown.signal dosyası oluşturur.
    Bu dosya varsa kullanıcı kasıtlı kapatmış demektir → watchdog durmalı.

    Returns:
        True ise kasıtlı kapanış (watchdog durmalı), False ise değil.
    """
    try:
        if os.path.exists(SHUTDOWN_SIGNAL_FILE):
            log(f"[WATCHDOG] shutdown.signal bulundu — kullanici kasitli kapatti")
            # v5.7.2: Signal dosyasını SİLME — birden fazla watchdog olabilir, hepsi görmeli
            # Signal sadece main() başlangıcında temizlenir (yeni başlatma = temiz sayfa)
            return True
    except Exception:
        pass
    return False


def check_heartbeat():
    """v5.4.1: Engine heartbeat dosyasını kontrol et.

    Returns:
        True ise engine canlı, False ise stale/ölü.
    """
    try:
        if not os.path.exists(HEARTBEAT_FILE):
            return False
        with open(HEARTBEAT_FILE, "r") as f:
            ts = float(f.read().strip())
        age = time.time() - ts
        return age < WATCHDOG_STALE_SECS
    except Exception:
        return False


def watchdog_loop():
    """v5.4.1: Engine watchdog — heartbeat izle, gerekirse yeniden başlat.

    Ana fonksiyon tamamlandıktan sonra çalışır.
    Engine heartbeat'i stale olursa:
      1. Eski process'leri temizle
      2. API'yi yeniden başlat
      3. Electron'u yeniden başlat
    """
    restart_count = 0

    # v5.7.2: Singleton watchdog — başka AKTİF bir watchdog çalışıyorsa başlatma
    # Kontrol: watchdog.pid dosyasının son güncelleme zamanı < 60sn ise aktif demek
    # Watchdog her döngüde (15sn) PID dosyasını günceller, 60sn eskiyse ölmüş/durmuş
    try:
        if os.path.exists(WATCHDOG_PID_FILE):
            pid_age = time.time() - os.path.getmtime(WATCHDOG_PID_FILE)
            if pid_age < 60:
                with open(WATCHDOG_PID_FILE, "r") as f:
                    old_pid = f.read().strip()
                log(f"[WATCHDOG] Aktif watchdog mevcut (PID {old_pid}, {pid_age:.0f}sn once guncellendi) — bu watchdog baslatilmayacak")
                return
            else:
                log(f"[WATCHDOG] Eski watchdog.pid bulundu ({pid_age:.0f}sn) — stale, devam ediliyor")
    except (ValueError, FileNotFoundError, OSError):
        pass

    # Kendi PID'imizi yaz (timestamp olarak dosya zamanı kullanılır)
    try:
        with open(WATCHDOG_PID_FILE, "w") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass

    log("[WATCHDOG] Engine watchdog baslatildi")
    log(f"  Stale esigi: {WATCHDOG_STALE_SECS}sn, kontrol araligi: {WATCHDOG_CHECK_INTERVAL}sn")

    # v5.9: İlk açılışta OTP girişi için bekleme — eski heartbeat dosyasını da temizle
    if os.path.exists(HEARTBEAT_FILE):
        try:
            os.remove(HEARTBEAT_FILE)
            log(f"[WATCHDOG] Eski heartbeat temizlendi")
        except Exception:
            pass
    log(f"[WATCHDOG] Ilk bekleme: {WATCHDOG_INITIAL_DELAY}sn (OTP + MT5 baglantisi icin)")
    time.sleep(WATCHDOG_INITIAL_DELAY)

    # İlk heartbeat dosyasının oluşmasını bekle (engine başlangıcı)
    for _ in range(60):
        if os.path.exists(HEARTBEAT_FILE):
            break
        time.sleep(1)

    while True:
        time.sleep(WATCHDOG_CHECK_INTERVAL)

        # v5.7.2: PID dosyasını güncelle (singleton heartbeat — her 15sn)
        try:
            with open(WATCHDOG_PID_FILE, "w") as f:
                f.write(str(os.getpid()))
        except Exception:
            pass

        # v5.5: Önce kasıtlı kapanış sinyali kontrol et
        if check_shutdown_signal():
            log("[WATCHDOG] Kullanici kasitli kapatti — watchdog durduruluyor")
            break

        if not port_open(8000):
            # API portu kapalı — kullanıcı sistemi kapattı
            if not port_open(5173):
                log("[WATCHDOG] API ve Vite kapali — kullanici cikis yapmis, watchdog durduruluyor")
                break
            # Tekrar kontrol: belki shutdown signal gecikmeli yazıldı
            time.sleep(2)
            if check_shutdown_signal():
                log("[WATCHDOG] Kullanici kasitli kapatti (gecikmeli sinyal) — watchdog durduruluyor")
                break
            # Sadece API düştü
            log("[WATCHDOG] API portu kapali — engine crash tespit edildi")
        elif check_heartbeat():
            # Her şey normal
            restart_count = 0
            continue
        else:
            log("[WATCHDOG] Heartbeat STALE — engine dondurulmus veya crash")

        # Auto-restart limiti
        restart_count += 1
        if restart_count > MAX_AUTO_RESTARTS:
            log(f"[WATCHDOG] {MAX_AUTO_RESTARTS} restart basarisiz — agresif temizlik + son deneme")
            # Agresif temizlik: tüm portları ve PID'leri zorla temizle
            try:
                cleanup()
                for _pf in [HEARTBEAT_FILE, "api.pid"]:
                    _fp = os.path.join(USTAT_DIR, _pf) if not os.path.isabs(_pf) else _pf
                    if os.path.exists(_fp):
                        os.remove(_fp)
            except Exception:
                pass
            time.sleep(30)  # 30 saniye tam temizlik bekleme
            # SON DENEME
            if check_shutdown_signal():
                break
            log("[WATCHDOG] Son deneme baslatiliyor...")
            if start_api():
                if not port_open(5173):
                    start_vite()
                start_electron()
                log("[WATCHDOG] Son deneme tamamlandi — 60sn heartbeat bekleniyor")
                time.sleep(60)
                if check_heartbeat():
                    log("[WATCHDOG] Son deneme BASARILI — normal izlemeye donuluyor")
                    restart_count = 0
                    continue
            log("[WATCHDOG] KRITIK: Son deneme de basarisiz — watchdog durduruluyor")
            log("[WATCHDOG] Manuel mudahale gerekli!")
            break

        log(f"[WATCHDOG] Otomatik yeniden baslatma #{restart_count}/{MAX_AUTO_RESTARTS}")

        # v5.9.2-fix: Restart öncesi L3 kill-switch kontrolü
        # L3 aktifse motor kasıtlı olarak durmuş demektir — restart yapma
        try:
            import urllib.request as _urlreq
            import json as _json_mod
            _resp = _urlreq.urlopen("http://localhost:8000/status", timeout=3)
            _status_data = _json_mod.loads(_resp.read())
            _ks_level = _status_data.get("kill_switch_level", 0)
            if _ks_level >= 3:
                log(f"[WATCHDOG] L3 kill-switch aktif (level={_ks_level}) — restart ENGELLENDI")
                log("[WATCHDOG] Motor kasitli olarak durmus. Manuel mudahale gerekli.")
                continue
        except Exception:
            pass  # API cevap vermiyorsa normal restart akışına devam

        # v5.7.1: Restart öncesi SON shutdown.signal kontrolü (yarış durumu önlemi)
        if check_shutdown_signal():
            log("[WATCHDOG] Restart oncesi shutdown.signal tespit edildi — watchdog durduruluyor")
            break

        # Eski process'leri temizle
        try:
            cleanup()
        except Exception as exc:
            log(f"[WATCHDOG] Temizlik hatasi: {exc}")

        # Heartbeat dosyasını temizle
        try:
            if os.path.exists(HEARTBEAT_FILE):
                os.remove(HEARTBEAT_FILE)
        except Exception:
            pass

        # API'yi yeniden başlat
        if not start_api():
            log("[WATCHDOG] API baslatilamadi — bir sonraki denemede tekrar deneyecek")
            continue

        # Vite kontrol
        if not port_open(5173):
            start_vite()

        # Electron başlatmadan HEMEN ÖNCE son signal kontrolü (yarış penceresi kapatma)
        if check_shutdown_signal():
            log("[WATCHDOG] Electron oncesi shutdown.signal tespit edildi — watchdog durduruluyor")
            break

        # Electron başlat
        start_electron()

        log(f"[WATCHDOG] Yeniden baslatma #{restart_count} tamamlandi — heartbeat bekleniyor...")
        # Yeni engine'in başlaması için bekle
        time.sleep(30)


def main():
    # Temiz log
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("")

    is_prod = "--prod" in sys.argv
    is_watchdog = "--no-watchdog" not in sys.argv  # v5.4.1
    log(f"=== USTAT v5.7 Baslatici {'(PRODUCTION)' if is_prod else '(DEVELOPMENT)'} ===")
    log(f"Python: {sys.executable}")
    log(f"Watchdog: {'AKTIF' if is_watchdog else 'DEVRE DISI'}")

    # v5.9.1: shutdown.signal → her başlatmada koşulsuz temizle
    # Signal'in amacı watchdog'u durdurmak (check_shutdown_signal() bunu yapar)
    # Kullanıcı kısayoldan başlattığında bu KASITLİ bir başlatmadır → engellenmemeli
    try:
        if os.path.exists(SHUTDOWN_SIGNAL_FILE):
            signal_age = time.time() - os.path.getmtime(SHUTDOWN_SIGNAL_FILE)
            os.remove(SHUTDOWN_SIGNAL_FILE)
            log(f"shutdown.signal temizlendi ({signal_age:.0f}sn)")
    except Exception:
        pass

    # 0. Hizli temizlik (minimum bekleme)
    cleanup()

    # 1. API
    start_api()

    if is_prod:
        # 2. Production: Vite build yap (dist/ olustur)
        if not build_frontend():
            log("HATA: Frontend build basarisiz, development modda devam ediliyor")
            start_vite()
    else:
        # 2. Vite (bekleme YAPMAZ — Electron splash ekrani gosterir, Vite'i kendisi bekler)
        start_vite()

    # 3. Electron HEMEN baslat (splash screen gosterir, Vite hazir olunca uygulamayi yukler)
    start_electron()

    log("=== Tamamlandi ===")

    # v5.4.1: Watchdog döngüsü — engine'i izle ve gerekirse yeniden başlat
    if is_watchdog:
        try:
            watchdog_loop()
        except KeyboardInterrupt:
            log("[WATCHDOG] Ctrl+C — watchdog durduruluyor")
        except Exception as exc:
            log(f"[WATCHDOG] Beklenmeyen hata: {exc}")
        finally:
            # v5.7.2: Watchdog PID dosyasını temizle
            try:
                if os.path.exists(WATCHDOG_PID_FILE):
                    os.remove(WATCHDOG_PID_FILE)
            except Exception:
                pass


if __name__ == "__main__":
    main()
