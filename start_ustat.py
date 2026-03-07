"""
USTAT v5.1 - Baslatici

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

USTAT_DIR = r"C:\USTAT"
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
    """Port acilana kadar bekle."""
    for i in range(timeout_secs):
        if port_open(port):
            log(f"  {name} hazir (port {port}, {i+1}sn)")
            return True
        time.sleep(1)
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
        time.sleep(0.5)

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
            time.sleep(1)  # Single-instance lock'un serbest kalmasi icin bekle
        if "ENGELLENDI" in output or "ACCESS" in output:
            log("  UYARI: electron.exe admin olarak calisiyor, taskkill ile durdurulamiyor!")
            log("  Gorev Yoneticisi'nden elle sonlandirin veya bilgisayari yeniden baslatin.")
    except Exception:
        pass

    # 2. Eski Vite temizle (port 5173) — kisa bekleme
    if port_open(5173):
        kill_port(5173)
        time.sleep(0.5)
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

    return wait_for_port(8000, "API", 30)


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


def start_electron():
    """Electron uygulamasini baslat."""
    log("[3/3] Electron baslatiliyor...")
    electron_exe = os.path.join(
        DESKTOP_DIR, "node_modules", "electron", "dist", "electron.exe"
    )
    if not os.path.exists(electron_exe):
        log(f"  HATA: electron.exe bulunamadi: {electron_exe}")
        return False

    log(f"  Exe: {electron_exe}")
    log(f"  CWD: {DESKTOP_DIR}")

    env = os.environ.copy()
    env["NODE_ENV"] = "development"

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
    log("  Electron baslatildi (DETACHED_PROCESS)")
    return True


def main():
    # Temiz log
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("")

    log("=== USTAT v5.0 Baslatici ===")
    log(f"Python: {sys.executable}")

    # 0. Hizli temizlik (minimum bekleme)
    cleanup()

    # 1. API
    start_api()

    # 2. Vite (bekleme YAPMAZ — Electron splash ekrani gosterir, Vite'i kendisi bekler)
    start_vite()

    # 3. Electron HEMEN baslat (splash screen gosterir, Vite hazir olunca uygulamayi yukler)
    start_electron()

    log("=== Tamamlandi ===")


if __name__ == "__main__":
    main()
