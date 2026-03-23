"""
ÜSTAT AJAN v1.0 — Claude ↔ Windows Köprü Ajanı

Bu ajan Windows'ta arka planda çalışır ve Claude'un (Linux VM)
Windows bilgisayarınızda komut çalıştırmasını sağlar.

Mimari:
  Claude (Linux VM) → .agent/commands/cmd_XXXX.json yazar
  AJAN (Windows)    → komutu okur → çalıştırır → .agent/results/cmd_XXXX.json yazar
  Claude (Linux VM) → sonucu okur → raporlar

Kullanım:
  python ustat_agent.py              (normal başlatma)
  python ustat_agent.py --install    (Windows başlangıcına ekle)
  python ustat_agent.py --uninstall  (başlangıçtan kaldır)

Desteklenen Komut Tipleri:
  shell      → PowerShell/CMD/Python komutu çalıştır
  start_app  → ÜSTAT uygulamasını başlat
  stop_app   → ÜSTAT uygulamasını durdur
  build      → Desktop npm run build
  screenshot → Ekran görüntüsü al
  shortcut   → Masaüstü kısayolunu güncelle
  status     → Sistem durumu raporu
  readlog    → Log dosyası oku
  processes  → Çalışan süreçleri listele
  ping       → Ajan canlı mı kontrolü
"""

import json
import os
import sys
import time
import subprocess
import platform
import hashlib
import shutil
import traceback
from datetime import datetime, timezone
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
# YAPILANDIRMA
# ═══════════════════════════════════════════════════════════════

USTAT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
AGENT_DIR = USTAT_DIR / ".agent"
CMD_DIR = AGENT_DIR / "commands"
RESULT_DIR = AGENT_DIR / "results"
LOG_FILE = AGENT_DIR / "agent.log"
PID_FILE = AGENT_DIR / "agent.pid"
HEARTBEAT_FILE = AGENT_DIR / "heartbeat.json"
DESKTOP_DIR = USTAT_DIR / "desktop"

POLL_INTERVAL = 1.5          # saniye — komut klasörünü kontrol aralığı
HEARTBEAT_INTERVAL = 10      # saniye — canlılık sinyali
MAX_COMMAND_AGE = 300         # saniye — 5 dk'dan eski komutlar atlanır
MAX_SHELL_TIMEOUT = 120       # saniye — shell komut zaman aşımı
MAX_LOG_LINES = 200           # log okumada maks satır

AGENT_VERSION = "1.0.0"


# ═══════════════════════════════════════════════════════════════
# LOGLAMA
# ═══════════════════════════════════════════════════════════════

def safe_print(msg: str):
    """Windows cp1254 uyumlu print."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))


def log(msg: str, level: str = "INFO"):
    """Ajan log dosyasina yaz."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} [{level}] {msg}"
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    # Konsola da yaz
    prefix = {"INFO": "->", "WARN": "!!", "ERROR": "XX", "OK": "OK"}.get(level, "->")
    safe_print(f"  {prefix} {msg}")


# ═══════════════════════════════════════════════════════════════
# KLASÖR HAZIRLIĞI
# ═══════════════════════════════════════════════════════════════

def ensure_dirs():
    """Ajan klasörlerini oluştur."""
    CMD_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    # .gitignore — ajan dosyaları repo'ya girmesin
    gitignore = AGENT_DIR / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n", encoding="utf-8")


# ═══════════════════════════════════════════════════════════════
# HEARTBEAT
# ═══════════════════════════════════════════════════════════════

_last_heartbeat = 0.0

def write_heartbeat():
    """Claude'un ajanın canlı olduğunu bilmesi için."""
    global _last_heartbeat
    now = time.time()
    if now - _last_heartbeat < HEARTBEAT_INTERVAL:
        return
    _last_heartbeat = now
    data = {
        "alive": True,
        "pid": os.getpid(),
        "version": AGENT_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": int(now - _agent_start_time),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "ustat_dir": str(USTAT_DIR),
        "commands_processed": _commands_processed,
    }
    try:
        HEARTBEAT_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
# KOMUT OKUMA / SONUÇ YAZMA
# ═══════════════════════════════════════════════════════════════

def read_command(path: Path) -> dict | None:
    """Komut dosyasını oku."""
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception as e:
        log(f"Komut okunamadı: {path.name} — {e}", "ERROR")
        return None


def write_result(cmd_id: str, success: bool, output: str, error: str = "", duration: float = 0.0, extra: dict = None):
    """Sonuç dosyası yaz."""
    data = {
        "id": cmd_id,
        "success": success,
        "output": output,
        "error": error,
        "duration_seconds": round(duration, 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_version": AGENT_VERSION,
    }
    if extra:
        data.update(extra)
    result_file = RESULT_DIR / f"{cmd_id}.json"
    try:
        result_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log(f"Sonuç yazılamadı: {cmd_id} — {e}", "ERROR")


# ═══════════════════════════════════════════════════════════════
# KOMUT İŞLEYİCİLER
# ═══════════════════════════════════════════════════════════════

def handle_shell(cmd: dict) -> tuple[bool, str, str]:
    """Shell komutu çalıştır (PowerShell / CMD / Python)."""
    command = cmd.get("command", "")
    cwd = cmd.get("cwd", str(USTAT_DIR))
    timeout = min(cmd.get("timeout", MAX_SHELL_TIMEOUT), MAX_SHELL_TIMEOUT)
    shell_type = cmd.get("shell", "powershell")  # powershell | cmd | python

    if not command:
        return False, "", "Komut boş"

    if shell_type == "powershell":
        args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
    elif shell_type == "python":
        args = [sys.executable, "-c", command]
    else:
        args = ["cmd", "/c", command]

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        output = result.stdout.strip()
        error = result.stderr.strip()
        success = result.returncode == 0
        return success, output, error
    except subprocess.TimeoutExpired:
        return False, "", f"Zaman aşımı ({timeout}s)"
    except Exception as e:
        return False, "", str(e)


def handle_start_app(cmd: dict) -> tuple[bool, str, str]:
    """ÜSTAT uygulamasını başlat."""
    try:
        start_script = USTAT_DIR / "start_ustat.py"
        if not start_script.exists():
            return False, "", "start_ustat.py bulunamadı"

        # Detached process olarak başlat
        CREATE_NO_WINDOW = 0x08000000
        DETACHED_PROCESS = 0x00000008

        proc = subprocess.Popen(
            [sys.executable, str(start_script)],
            cwd=str(USTAT_DIR),
            creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(3)

        if proc.poll() is None:
            return True, f"ÜSTAT başlatıldı (PID: {proc.pid})", ""
        else:
            stderr = proc.stderr.read().decode("utf-8", errors="replace")
            return False, "", f"Başlatma başarısız: {stderr}"
    except Exception as e:
        return False, "", str(e)


def handle_stop_app(cmd: dict) -> tuple[bool, str, str]:
    """ÜSTAT uygulamasını durdur."""
    killed = []
    errors = []
    targets = ["python.*start_ustat", "uvicorn", "node.*electron", "node.*vite"]

    for target in targets:
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Get-Process | Where-Object {{$_.CommandLine -match '{target}'}} | Stop-Process -Force -PassThru"],
                capture_output=True, text=True, timeout=15, encoding="utf-8", errors="replace"
            )
            if result.stdout.strip():
                killed.append(target)
        except Exception as e:
            errors.append(f"{target}: {e}")

    if killed:
        return True, f"Durduruldu: {', '.join(killed)}", "\n".join(errors) if errors else ""
    elif errors:
        return False, "", "\n".join(errors)
    else:
        return True, "Çalışan ÜSTAT süreci bulunamadı", ""


def handle_build(cmd: dict) -> tuple[bool, str, str]:
    """Desktop npm run build."""
    try:
        if not DESKTOP_DIR.exists():
            return False, "", "desktop/ klasörü bulunamadı"

        # Önce node_modules kontrolü
        if not (DESKTOP_DIR / "node_modules").exists():
            log("node_modules yok, npm install çalıştırılıyor...", "WARN")
            subprocess.run(
                ["npm", "install"],
                cwd=str(DESKTOP_DIR),
                capture_output=True, text=True, timeout=120,
                shell=True, encoding="utf-8", errors="replace"
            )

        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(DESKTOP_DIR),
            capture_output=True, text=True, timeout=120,
            shell=True, encoding="utf-8", errors="replace"
        )

        output = result.stdout.strip()
        error = result.stderr.strip()
        success = result.returncode == 0

        if success:
            return True, f"Build başarılı.\n{output}", ""
        else:
            return False, output, error
    except subprocess.TimeoutExpired:
        return False, "", "Build zaman aşımı (120s)"
    except Exception as e:
        return False, "", str(e)


def handle_screenshot(cmd: dict) -> tuple[bool, str, str]:
    """Ekran görüntüsü al."""
    try:
        # pillow ile ekran görüntüsü
        from PIL import ImageGrab
        filename = cmd.get("filename", f"screenshot_{int(time.time())}.png")
        filepath = AGENT_DIR / filename
        img = ImageGrab.grab()
        img.save(str(filepath), "PNG")
        return True, str(filepath), ""
    except ImportError:
        # mss alternatifi dene
        try:
            import mss
            filename = cmd.get("filename", f"screenshot_{int(time.time())}.png")
            filepath = AGENT_DIR / filename
            with mss.mss() as sct:
                sct.shot(output=str(filepath))
            return True, str(filepath), ""
        except ImportError:
            return False, "", "Pillow veya mss kurulu değil. Kur: pip install Pillow"
    except Exception as e:
        return False, "", str(e)


def handle_shortcut(cmd: dict) -> tuple[bool, str, str]:
    """Masaüstü kısayolunu güncelle — update_shortcut.ps1 çalıştır."""
    try:
        script = USTAT_DIR / "update_shortcut.ps1"
        if not script.exists():
            return False, "", "update_shortcut.ps1 bulunamadı"

        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            capture_output=True, text=True, timeout=30,
            cwd=str(USTAT_DIR), encoding="utf-8", errors="replace",
            input="\n"  # Read-Host için Enter gönder
        )
        output = result.stdout.strip()
        error = result.stderr.strip()
        return result.returncode == 0 or "olusturuldu" in output.lower(), output, error
    except Exception as e:
        return False, "", str(e)


def handle_status(cmd: dict) -> tuple[bool, str, str]:
    """Sistem durumu raporu."""
    info = {}

    # Platform
    info["platform"] = platform.platform()
    info["python"] = platform.python_version()
    info["cwd"] = str(USTAT_DIR)

    # ÜSTAT süreçleri
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process | Where-Object {$_.ProcessName -match 'python|node|electron'} | "
             "Select-Object ProcessName, Id, CPU, WorkingSet64 | ConvertTo-Json"],
            capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace"
        )
        if result.stdout.strip():
            info["processes"] = json.loads(result.stdout)
        else:
            info["processes"] = []
    except Exception:
        info["processes"] = "kontrol edilemedi"

    # Port kontrolü (API: 8000, Vite: 5173)
    import socket
    for name, port in [("API", 8000), ("Vite", 5173)]:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(("127.0.0.1", port))
            info[f"port_{port}_{name}"] = "AÇIK" if result == 0 else "KAPALI"
            sock.close()
        except Exception:
            info[f"port_{port}_{name}"] = "kontrol edilemedi"

    # Disk
    try:
        usage = shutil.disk_usage(str(USTAT_DIR))
        info["disk_free_gb"] = round(usage.free / (1024**3), 1)
        info["disk_total_gb"] = round(usage.total / (1024**3), 1)
    except Exception:
        pass

    # api.pid
    pid_file = USTAT_DIR / "api.pid"
    if pid_file.exists():
        info["api_pid"] = pid_file.read_text(encoding="utf-8").strip()
    else:
        info["api_pid"] = "yok"

    return True, json.dumps(info, indent=2, ensure_ascii=False), ""


def handle_readlog(cmd: dict) -> tuple[bool, str, str]:
    """Log dosyası oku."""
    logname = cmd.get("file", "")
    lines = cmd.get("lines", MAX_LOG_LINES)
    search = cmd.get("search", "")

    # Yaygın log yolları
    log_paths = {
        "api": USTAT_DIR / "api.log",
        "startup": USTAT_DIR / "startup.log",
        "agent": LOG_FILE,
        "electron": USTAT_DIR / "desktop" / "electron.log",
    }

    if logname in log_paths:
        target = log_paths[logname]
    else:
        target = USTAT_DIR / logname
        if not target.exists():
            # logs/ klasöründe ara
            target = USTAT_DIR / "logs" / logname

    if not target.exists():
        available = [k for k, v in log_paths.items() if v.exists()]
        return False, "", f"Log bulunamadı: {logname}\nMevcut: {', '.join(available)}"

    try:
        all_lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        if search:
            all_lines = [l for l in all_lines if search.lower() in l.lower()]
        tail = all_lines[-lines:]
        return True, "\n".join(tail), ""
    except Exception as e:
        return False, "", str(e)


def handle_processes(cmd: dict) -> tuple[bool, str, str]:
    """Çalışan süreçleri listele."""
    filter_name = cmd.get("filter", "python|node|electron|uvicorn|mt5")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Get-Process | Where-Object {{$_.ProcessName -match '{filter_name}'}} | "
             "Format-Table ProcessName, Id, CPU, @{N='MB';E={[math]::Round($_.WorkingSet64/1MB,1)}} -AutoSize | Out-String"],
            capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace"
        )
        return True, result.stdout.strip() or "Eşleşen süreç yok", ""
    except Exception as e:
        return False, "", str(e)


def handle_ping(cmd: dict) -> tuple[bool, str, str]:
    """Canlılık kontrolü."""
    return True, f"AJAN CANLI — v{AGENT_VERSION} — PID {os.getpid()} — uptime {int(time.time() - _agent_start_time)}s", ""


# ═══════════════════════════════════════════════════════════════
# KOMUT DAĞITICI
# ═══════════════════════════════════════════════════════════════

HANDLERS = {
    "shell": handle_shell,
    "start_app": handle_start_app,
    "stop_app": handle_stop_app,
    "build": handle_build,
    "screenshot": handle_screenshot,
    "shortcut": handle_shortcut,
    "status": handle_status,
    "readlog": handle_readlog,
    "processes": handle_processes,
    "ping": handle_ping,
}


def process_command(cmd_file: Path):
    """Tek bir komutu işle."""
    global _commands_processed

    cmd = read_command(cmd_file)
    if cmd is None:
        cmd_file.unlink(missing_ok=True)
        return

    cmd_id = cmd.get("id", cmd_file.stem)
    cmd_type = cmd.get("type", "")
    created = cmd.get("created", "")

    # Sonuç zaten var mı? (tekrar işleme)
    result_file = RESULT_DIR / f"{cmd_id}.json"
    if result_file.exists():
        cmd_file.unlink(missing_ok=True)
        return

    # Çok eski komutlar atla
    if created:
        try:
            created_time = datetime.fromisoformat(created)
            age = (datetime.now(timezone.utc) - created_time).total_seconds()
            if age > MAX_COMMAND_AGE:
                log(f"Eski komut atlandı: {cmd_id} ({int(age)}s)", "WARN")
                write_result(cmd_id, False, "", f"Komut çok eski ({int(age)}s > {MAX_COMMAND_AGE}s)")
                cmd_file.unlink(missing_ok=True)
                return
        except Exception:
            pass

    handler = HANDLERS.get(cmd_type)
    if handler is None:
        log(f"Bilinmeyen komut tipi: {cmd_type} ({cmd_id})", "ERROR")
        write_result(cmd_id, False, "", f"Bilinmeyen komut tipi: {cmd_type}\nDesteklenen: {', '.join(HANDLERS.keys())}")
        cmd_file.unlink(missing_ok=True)
        return

    log(f"Komut işleniyor: [{cmd_type}] {cmd_id}")
    start = time.time()

    try:
        success, output, error = handler(cmd)
        duration = time.time() - start
        write_result(cmd_id, success, output, error, duration)
        status = "OK" if success else "ERROR"
        log(f"  Tamamlandı: [{cmd_type}] {cmd_id} → {status} ({duration:.1f}s)", status)
    except Exception as e:
        duration = time.time() - start
        tb = traceback.format_exc()
        write_result(cmd_id, False, "", f"{str(e)}\n{tb}", duration)
        log(f"  İstisna: [{cmd_type}] {cmd_id} → {e}", "ERROR")

    # Komutu sil (işlendi)
    cmd_file.unlink(missing_ok=True)
    _commands_processed += 1


# ═══════════════════════════════════════════════════════════════
# WINDOWS BAŞLANGIÇ KAYIT
# ═══════════════════════════════════════════════════════════════

def install_startup():
    """Windows başlangıcına ekle."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE
        )
        vbs_path = str(USTAT_DIR / "start_agent.vbs")
        winreg.SetValueEx(key, "USTAT_Agent", 0, winreg.REG_SZ,
                          f'wscript.exe "{vbs_path}"')
        winreg.CloseKey(key)
        safe_print("  [OK] USTAT Ajan Windows baslangicina eklendi.")
        safe_print(f"    Kayit: HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\USTAT_Agent")
    except Exception as e:
        safe_print(f"  [HATA] Baslangic kaydi basarisiz: {e}")


def uninstall_startup():
    """Windows başlangıcından kaldır."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE
        )
        winreg.DeleteValue(key, "USTAT_Agent")
        winreg.CloseKey(key)
        safe_print("  [OK] USTAT Ajan baslangictan kaldirildi.")
    except FileNotFoundError:
        safe_print("  -> Zaten kayitli degil.")
    except Exception as e:
        safe_print(f"  [HATA] Kaldirma basarisiz: {e}")


# ═══════════════════════════════════════════════════════════════
# ANA DÖNGÜ
# ═══════════════════════════════════════════════════════════════

_agent_start_time = time.time()
_commands_processed = 0


def main():
    """Ajan ana döngüsü."""
    # Argüman kontrolü
    if "--install" in sys.argv:
        install_startup()
        return
    if "--uninstall" in sys.argv:
        uninstall_startup()
        return

    ensure_dirs()

    # PID dosyası
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

    safe_print("")
    safe_print("  +----------------------------------------------+")
    safe_print("  |    USTAT AJAN v1.0 - Claude <> Windows       |")
    safe_print("  +----------------------------------------------+")
    safe_print(f"  |  PID     : {os.getpid():<33}|")
    safe_print(f"  |  Klasor  : {str(USTAT_DIR):<33}|")
    safe_print(f"  |  Komut   : .agent/commands/                 |")
    safe_print(f"  |  Sonuc   : .agent/results/                  |")
    safe_print("  |  Durmak  : Ctrl+C                           |")
    safe_print("  +----------------------------------------------+")
    safe_print("")

    log(f"Ajan başlatıldı — PID {os.getpid()} — v{AGENT_VERSION}")

    try:
        while True:
            try:
                # Heartbeat güncelle
                write_heartbeat()

                # Komut dosyalarını tara
                if CMD_DIR.exists():
                    cmd_files = sorted(CMD_DIR.glob("*.json"))
                    for cmd_file in cmd_files:
                        process_command(cmd_file)

            except KeyboardInterrupt:
                raise
            except Exception as e:
                log(f"Döngü hatası: {e}", "ERROR")

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        safe_print("\n  -> Ajan durduruluyor...")
        log("Ajan durduruldu (Ctrl+C)")
    finally:
        # Temizlik
        PID_FILE.unlink(missing_ok=True)
        heartbeat = {"alive": False, "timestamp": datetime.now(timezone.utc).isoformat()}
        HEARTBEAT_FILE.write_text(json.dumps(heartbeat), encoding="utf-8")
        safe_print("  [OK] Ajan kapatildi.")


if __name__ == "__main__":
    main()
