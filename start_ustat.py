"""
ÜSTAT v6.0 — Başlatıcı (pywebview + FastAPI + pystray)

Mimari (pywebview resmi multiprocessing pattern):
  - Ana Process: pystray system tray (Göster/Gizle/Çıkış)
  - Alt Process: pywebview pencere + uvicorn API + Engine

Neden multiprocessing:
  pywebview (.NET WinForms) ve pystray (Win32 mesaj döngüsü) aynı process'te
  çalıştığında deadlock yapıyor. Resmi çözüm: ayrı process'ler.

Kapanış: Tray "Çıkış" → process.terminate() → OS seviyesinde öldürme → DEADLOCK İMKANSIZ.

Kullanım:
  python start_ustat.py              (normal)
  python start_ustat.py --dev        (Vite 5173 kullanır)
  python start_ustat.py --no-tray    (tray olmadan, pencere kapatınca çıkar)
"""

import os
import sys
import time
import socket
import threading
import multiprocessing

# ── Çalışma dizini ────────────────────────────────────────────────
USTAT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(USTAT_DIR)
sys.path.insert(0, USTAT_DIR)

# ── Sabitler ──────────────────────────────────────────────────────
API_HOST = "127.0.0.1"
API_PORT = 8000
DIST_DIR = os.path.join(USTAT_DIR, "desktop", "dist")
LOG_FILE = os.path.join(USTAT_DIR, "startup.log")
BG_COLOR = "#0d1117"
APP_TITLE = "ÜSTAT v5.9 VİOP Algorithmic Trading"

IS_DEV = "--dev" in sys.argv
NO_TRAY = "--no-tray" in sys.argv


# ── Loglama ───────────────────────────────────────────────────────
def slog(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"{ts} | {msg}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(f"[USTAT] {line}")


# ── Port ──────────────────────────────────────────────────────────
def port_open(port):
    for host, family in [("127.0.0.1", socket.AF_INET), ("::1", socket.AF_INET6)]:
        try:
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                if s.connect_ex((host, port)) == 0:
                    return True
        except Exception:
            pass
    return False


def kill_port(port):
    import subprocess
    CREATE_NO_WINDOW = 0x08000000
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
                        ["taskkill", "/F", "/T", "/PID", pid],
                        capture_output=True, text=True,
                        creationflags=CREATE_NO_WINDOW,
                    )
                    if "SUCCESS" in (r.stdout + r.stderr).upper():
                        slog(f"  Port {port} -> PID {pid} sonlandirildi")
                        killed.add(pid)
        return len(killed) > 0
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════
# ALT PROCESS: pywebview + FastAPI + Engine
# ══════════════════════════════════════════════════════════════════

SPLASH_HTML = f"""<!DOCTYPE html>
<html style="background:{BG_COLOR};height:100%;margin:0">
<head><meta charset="utf-8"><title>{APP_TITLE}</title></head>
<body style="display:flex;align-items:center;justify-content:center;height:100%;
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#e6edf3;margin:0">
<div style="text-align:center">
<h1 style="font-size:48px;margin:0;font-weight:300;letter-spacing:2px">
\u00dcSTAT <span style="color:#484f58;font-size:24px">v5.9</span></h1>
<p style="color:#484f58;margin:20px 0 30px;font-size:14px">V\u0130OP Algorithmic Trading</p>
<div style="width:36px;height:36px;border:3px solid #21262d;border-top-color:#58a6ff;
border-radius:50%;animation:s 1s linear infinite;margin:0 auto"></div>
<p id="status" style="color:#30363d;font-size:13px;margin-top:24px">Ba\u015Flat\u0131l\u0131yor...</p>
</div>
<style>@keyframes s{{to{{transform:rotate(360deg)}}}}</style>
</body></html>"""

ELECTRON_SHIM_JS = """
(function() {
    function createShim() {
        var api = window.pywebviewApi;
        if (!api) { setTimeout(createShim, 100); return; }
        window.electronAPI = {
            windowMinimize: function() { return api.minimize(); },
            windowMaximize: function() { return api.maximize(); },
            windowClose: function() { return api.close_window(); },
            windowIsMaximized: function() { return api.is_maximized(); },
            toggleAlwaysOnTop: function() { return api.toggle_on_top(); },
            getAlwaysOnTop: function() { return api.get_on_top(); },
            setAlwaysOnTop: function(val) { return api.set_on_top(val); },
            safeQuit: function() { return api.safe_quit(); },
            logToMain: function(level, msg) { return api.log_from_renderer(level, msg); },
            launchMT5: function(creds) { return api.launch_mt5(JSON.stringify(creds)); },
            sendOTP: function(code) { return api.send_otp(code); },
            getMT5Status: function() { return api.get_mt5_status(); },
            getSavedCredentials: function() { return api.get_saved_credentials(); },
            clearCredentials: function() { return api.clear_credentials(); },
            verifyMT5Connection: function() { return api.verify_mt5(); },
            onFocusOTPInputRequested: function(cb) { return function() {}; }
        };
        console.log('[USTAT] electronAPI shim aktif (pywebview backend)');
    }
    if (window.pywebview && window.pywebview.api) { createShim(); }
    else {
        window.addEventListener('pywebviewready', createShim);
        setTimeout(createShim, 500);
    }
})();
"""


class UstatWindowApi:
    """JS API bridge — React'in window.electronAPI cagrilarini karsilar."""

    def __init__(self, window_ref):
        self._window = window_ref
        self._on_top = True

    def minimize(self):
        w = self._window()
        if w: w.minimize()

    def maximize(self):
        w = self._window()
        if w:
            try:
                if hasattr(w, 'maximized') and w.maximized:
                    w.restore()
                    return False
                else:
                    w.maximize()
                    return True
            except Exception:
                w.maximize()
                return True
        return False

    def is_maximized(self):
        w = self._window()
        return bool(w.maximized) if w and hasattr(w, 'maximized') else False

    def close_window(self):
        w = self._window()
        if w: w.destroy()

    def toggle_on_top(self):
        w = self._window()
        if w:
            self._on_top = not self._on_top
            w.on_top = self._on_top
        return self._on_top

    def get_on_top(self):
        return self._on_top

    def set_on_top(self, value):
        w = self._window()
        if w:
            self._on_top = bool(value)
            w.on_top = self._on_top
        return self._on_top

    def safe_quit(self):
        slog("Guvenli cikis — pencere kapatiliyor")
        w = self._window()
        if w: w.destroy()

    def log_from_renderer(self, level, msg):
        slog(f"[Renderer/{level}] {msg}")

    def launch_mt5(self, creds_json):
        return self._api_get("/api/mt5/verify",
                             lambda r: {"success": r.get("connected", False),
                                        "message": "MT5 bagli" if r.get("connected") else "MT5 bagli degil",
                                        "alreadyConnected": r.get("connected", False)},
                             {"success": False, "message": "API erisilemedi"})

    def send_otp(self, otp_code):
        """OTP kodunu MT5 dialog'una gonder (admin Python ile)."""
        import subprocess, json, tempfile
        otp_script = os.path.join(USTAT_DIR, "desktop", "scripts", "mt5_automator.py")
        if not os.path.exists(otp_script):
            return {"success": False, "message": "mt5_automator.py bulunamadi"}

        # Temp dosya (admin process stdout yakalanamiyor)
        output_file = os.path.join(tempfile.gettempdir(), f"ustat_otp_{int(time.time())}.json")

        # PowerShell ile admin Python baslat (UAC onay gerekir)
        ps_cmd = (
            f"Start-Process -FilePath '{sys.executable}' "
            f"-ArgumentList '{otp_script} --otp {otp_code} --output {output_file}' "
            f"-Verb RunAs -Wait -WindowStyle Hidden"
        )
        try:
            proc = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=30,
                creationflags=0x08000000,
            )
            if proc.returncode != 0:
                return {"success": False, "message": "UAC reddedildi veya script hatasi"}

            # Sonuc dosyasini oku
            if os.path.exists(output_file):
                with open(output_file, "r", encoding="utf-8") as f:
                    result = json.loads(f.read())
                try:
                    os.remove(output_file)
                except Exception:
                    pass
                return result
            return {"success": False, "message": "OTP sonuc dosyasi bulunamadi"}
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "OTP zaman asimi (30sn)"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def get_mt5_status(self):
        return self._api_get("/api/mt5/verify",
                             lambda r: {"running": r.get("connected", False),
                                        "hasSaved": r.get("connected", False),
                                        "server": r.get("account", {}).get("server"),
                                        "login": str(r.get("account", {}).get("login", ""))},
                             {"running": False, "hasSaved": False})

    def get_saved_credentials(self):
        return self._api_get("/api/mt5/verify",
                             lambda r: ({"hasSaved": True,
                                         "server": r.get("account", {}).get("server", ""),
                                         "login": str(r.get("account", {}).get("login", "")),
                                         "passwordMask": "******"}
                                        if r.get("connected") else {"hasSaved": False}),
                             {"hasSaved": False})

    def clear_credentials(self):
        return True

    def verify_mt5(self):
        return self._api_get("/api/mt5/verify", lambda r: r,
                             {"connected": False, "message": "API erisilemedi"})

    def _api_get(self, path, transform, default):
        import json, urllib.request
        try:
            resp = urllib.request.urlopen(f"http://{API_HOST}:{API_PORT}{path}", timeout=5)
            return transform(json.loads(resp.read()))
        except Exception:
            return default


def run_webview_process():
    """ALT PROCESS olarak calisir. pywebview + FastAPI + Engine."""
    # Multiprocessing spawn: modul yeniden yuklenir, cwd/path ayarla
    ustat_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(ustat_dir)
    if ustat_dir not in sys.path:
        sys.path.insert(0, ustat_dir)

    import webview

    slog("[APP] Alt process baslatildi (pywebview + API)")

    _win = [None]
    def window_ref():
        return _win[0]

    api = UstatWindowApi(window_ref)

    window = webview.create_window(
        APP_TITLE,
        html=SPLASH_HTML,
        js_api=api,
        width=1400,
        height=900,
        min_size=(1200, 800),
        background_color=BG_COLOR,
        frameless=True,
        easy_drag=True,
        on_top=True,
    )
    _win[0] = window

    def bootstrap(win):
        # API baslat
        api_thread = threading.Thread(target=_start_api, daemon=True, name="uvicorn")
        api_thread.start()
        slog("[APP] API thread baslatildi")

        # Port bekle
        for i in range(150):
            if port_open(API_PORT):
                slog(f"[APP] API hazir (port {API_PORT}, {(i+1)*0.2:.1f}sn)")
                break
            time.sleep(0.2)
        else:
            slog("HATA: API baslamadi!")
            return

        # Shim enjekte
        try:
            win.evaluate_js(ELECTRON_SHIM_JS)
        except Exception:
            pass

        # UI yukle
        is_dev = os.environ.get("USTAT_DEV") == "1"
        if is_dev and port_open(5173):
            url = "http://localhost:5173"
        else:
            url = f"http://{API_HOST}:{API_PORT}"
        slog(f"[APP] UI yukleniyor: {url}")
        win.load_url(url)

        # Shim tekrar (sayfa yuklemesi sonrasi)
        time.sleep(2)
        try:
            win.evaluate_js(ELECTRON_SHIM_JS)
            slog("[APP] Electron API shim aktif")
        except Exception:
            pass

    webview.start(bootstrap, window)

    # Pencere kapandi
    slog("[APP] Pencere kapandi — alt process bitiyor")


def _start_api():
    import uvicorn
    slog("[APP] API baslatiliyor (uvicorn)...")
    config = uvicorn.Config(
        "api.server:app",
        host=API_HOST,
        port=API_PORT,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    server.run()


# ══════════════════════════════════════════════════════════════════
# ANA PROCESS: pystray system tray
# ══════════════════════════════════════════════════════════════════

webview_process = None


def start_webview():
    global webview_process
    webview_process = multiprocessing.Process(target=run_webview_process, daemon=True)
    webview_process.start()
    slog(f"Alt process baslatildi (PID {webview_process.pid})")


def stop_webview():
    global webview_process
    if webview_process and webview_process.is_alive():
        slog(f"Alt process sonlandiriliyor (PID {webview_process.pid})...")
        webview_process.terminate()
        webview_process.join(timeout=5)
        if webview_process.is_alive():
            slog("Graceful kapanma basarisiz — zorla olduruluyor")
            webview_process.kill()
            webview_process.join(timeout=3)
        slog("Alt process sonlandi")

    # Port temizligi (garanti)
    if port_open(API_PORT):
        slog(f"Port {API_PORT} hala acik — temizleniyor")
        kill_port(API_PORT)


def run_tray():
    """Ana process: system tray. icon.run() BLOKLAR."""
    from pystray import Icon, Menu, MenuItem
    from PIL import Image

    icon_path = os.path.join(USTAT_DIR, "desktop", "assets", "icon.png")
    if os.path.exists(icon_path):
        img = Image.open(icon_path).resize((64, 64))
    else:
        img = Image.new("RGB", (64, 64), color=(88, 166, 255))

    _icon_ref = [None]

    def on_show(icon, item):
        global webview_process
        if webview_process is None or not webview_process.is_alive():
            start_webview()
            # Yeni process icin monitor thread baslat
            _start_process_monitor(_icon_ref)

    def on_exit(icon, item):
        slog("[TRAY] Cikis")
        icon.stop()

    menu = Menu(
        MenuItem("Goster / Yeniden Ac", on_show, default=True),
        MenuItem("Cikis (Guvenli)", on_exit),
    )

    icon = Icon("ustat", img, APP_TITLE, menu=menu)
    _icon_ref[0] = icon

    # Monitor thread: pencere kapanirsa (alt process olurse) tray'i de kapat
    _start_process_monitor(_icon_ref)

    slog("[TRAY] System tray baslatildi")
    icon.run()  # BLOKLAR

    slog("[TRAY] System tray kapandi")


def _start_process_monitor(icon_ref):
    """Alt process olurse tray'i otomatik kapat."""
    def _monitor():
        global webview_process
        if webview_process:
            webview_process.join()  # Alt process bitene kadar bekle
            slog("[TRAY] Alt process kapandi — tray kapatiliyor")
            icon = icon_ref[0]
            if icon:
                icon.stop()

    t = threading.Thread(target=_monitor, daemon=True, name="process-monitor")
    t.start()


def main():
    # Temiz log
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("")

    slog("=" * 60)
    slog(f"USTAT v5.9 Baslatici (multiprocessing)")
    slog(f"Python: {sys.executable}")
    slog(f"Mod: {'DEV' if IS_DEV else 'PRODUCTION'}")
    slog("=" * 60)

    # dist/ kontrolu
    if not IS_DEV and not os.path.isfile(os.path.join(DIST_DIR, "index.html")):
        slog("HATA: desktop/dist/index.html bulunamadi!")
        sys.exit(1)

    # Port temizligi
    if port_open(API_PORT):
        slog(f"Port {API_PORT} mesgul — temizleniyor")
        kill_port(API_PORT)
        time.sleep(1)

    # Eski dosya temizligi
    for f in ["shutdown.signal", "api.pid", "watchdog.pid"]:
        fp = os.path.join(USTAT_DIR, f)
        if os.path.exists(fp):
            try:
                os.remove(fp)
            except Exception:
                pass

    # DEV flag'i alt process'e environment ile ilet
    if IS_DEV:
        os.environ["USTAT_DEV"] = "1"

    # Alt process: pywebview + API + Engine
    start_webview()

    if NO_TRAY:
        # Tray yok — alt process bitene kadar bekle
        slog("Tray devre disi — alt process bekleniyor")
        webview_process.join()
    else:
        # Ana process: system tray (BLOKLAR)
        run_tray()

    # Tray kapandi veya alt process bitti — temizlik
    stop_webview()
    slog("=== USTAT kapatildi ===")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
