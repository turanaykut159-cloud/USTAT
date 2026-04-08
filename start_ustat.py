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
import json
import socket
import signal
import atexit
import threading
import multiprocessing

# ── stdout/stderr koruması ────────────────────────────────────────
# pythonw.exe ile başlatıldığında sys.stdout ve sys.stderr None olur.
# Bu durumda uvicorn, logging ve tüm kütüphaneler sessizce çöker.
# Koruma: None ise dosyaya yönlendir, API/Engine normal çalışsın.
if sys.stdout is None or sys.stderr is None:
    _ustat_base = os.path.dirname(os.path.abspath(__file__))
    _fallback_log = os.path.join(_ustat_base, "startup_stdio.log")
    _fallback_fh = open(_fallback_log, "a", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = _fallback_fh
    if sys.stderr is None:
        sys.stderr = _fallback_fh

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
        var api = (window.pywebview && window.pywebview.api) || window.pywebviewApi;
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

TOPBAR_DRAG_JS = """
(function() {
    function setup() {
        var topBar = document.querySelector('.top-bar');
        if (!topBar) { setTimeout(setup, 500); return; }
        if (topBar._drag) return;
        topBar._drag = true;

        var api = (window.pywebview && window.pywebview.api) || window.pywebviewApi;
        if (!api || !api.begin_drag) { setTimeout(setup, 300); return; }

        var dragging = false, sx = 0, sy = 0, wx = 0, wy = 0;

        topBar.addEventListener('mousedown', function(e) {
            if (e.target.closest('.window-controls, button, a, input, select')) return;
            sx = e.screenX; sy = e.screenY;
            e.preventDefault();
            api.begin_drag().then(function(p) { wx = p.x; wy = p.y; dragging = true; });
        });
        document.addEventListener('mousemove', function(e) {
            if (!dragging) return;
            api.move_window_abs(wx + e.screenX - sx, wy + e.screenY - sy);
        });
        document.addEventListener('mouseup', function() {
            if (dragging) { dragging = false; api.clamp_to_monitor(); }
        });
    }
    setTimeout(setup, 1000);
})();
"""


# ── Windows Monitor Yardimcilari ─────────────────────────────────
def _get_monitor_work_area(x, y):
    """(x,y) noktasindaki monitörün calisma alanini dondurur: (left, top, width, height)."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", ctypes.c_ulong),
        ]

    pt = POINT(int(x), int(y))
    hmon = user32.MonitorFromPoint(pt, 2)  # MONITOR_DEFAULTTONEAREST
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
        w = mi.rcWork
        return (w.left, w.top, w.right - w.left, w.bottom - w.top)
    return None


class UstatWindowApi:
    """JS API bridge — React'in window.electronAPI cagrilarini karsilar."""

    def __init__(self, window_ref):
        self._window = window_ref
        self._on_top = True
        self._maximized = False
        self._restore_rect = None  # (x, y, w, h)

    # ── Pencere kontrolleri ───────────────────────────────────────

    def minimize(self):
        w = self._window()
        if w:
            w.minimize()

    def maximize(self):
        """Maximize ↔ Restore toggle. Pencerenin BULUNDUGU monitöre göre çalışır."""
        w = self._window()
        if not w:
            return False

        if self._maximized:
            # ── Restore ──────────────────────────────────────────
            self._maximized = False
            if self._restore_rect:
                rx, ry, rw, rh = self._restore_rect
                # Restore boyutunu hedef monitöre kenetle
                area = _get_monitor_work_area(rx + rw // 2, ry + 20)
                if area:
                    ml, mt, mw, mh = area
                    rw = min(rw, mw)
                    rh = min(rh, mh)
                    rx = max(ml, min(rx, ml + mw - rw))
                    ry = max(mt, min(ry, mt + mh - rh))
                w.resize(rw, rh)
                w.move(rx, ry)
            return False
        else:
            # ── Maximize ─────────────────────────────────────────
            # Mevcut boyutu kaydet
            try:
                self._restore_rect = (w.x, w.y,
                                      getattr(w, 'width', 1400),
                                      getattr(w, 'height', 900))
            except Exception:
                self._restore_rect = None

            # Pencerenin merkezindeki monitörün work area'sina tam sigdir
            area = _get_monitor_work_area(
                w.x + getattr(w, 'width', 1400) // 2,
                w.y + 20,
            )
            if area:
                ml, mt, mw, mh = area
                w.move(ml, mt)
                w.resize(mw, mh)
            else:
                w.maximize()

            self._maximized = True
            return True

    def is_maximized(self):
        return self._maximized

    def close_window(self):
        w = self._window()
        if w:
            w.destroy()

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

    # ── Drag & monitor kenetleme ─────────────────────────────────

    def begin_drag(self):
        """Drag baslarken pencere pozisyonunu dondur."""
        w = self._window()
        if w:
            self._maximized = False  # Drag basladiysa artik maximize degil
            return {"x": w.x, "y": w.y}
        return {"x": 0, "y": 0}

    def move_window(self, dx, dy):
        w = self._window()
        if w:
            w.move(w.x + int(dx), w.y + int(dy))

    def move_window_abs(self, x, y):
        w = self._window()
        if w:
            w.move(int(x), int(y))

    def clamp_to_monitor(self):
        """Pencereyi bulundugu monitörün sinirlarina kenetle.

        Drag sonrasi ve boundary guard tarafindan cagrilir.
        WebView2 pencere ekran sinirlarini astiginda beyaz ekran verir;
        bu metod bunu onler.
        """
        w = self._window()
        if not w:
            return
        try:
            ww = getattr(w, 'width', 1920)
            wh = getattr(w, 'height', 1080)
            area = _get_monitor_work_area(w.x + ww // 2, w.y + 20)
            if not area:
                return

            ml, mt, mw, mh = area
            new_w = min(ww, mw)
            new_h = min(wh, mh)
            changed = (new_w != ww or new_h != wh)

            if changed:
                w.resize(new_w, new_h)

            # Pozisyonu da kenetle
            new_x = max(ml, min(w.x, ml + mw - new_w))
            new_y = max(mt, min(w.y, mt + mh - new_h))
            if new_x != w.x or new_y != w.y:
                w.move(new_x, new_y)

            # Boyut degistiyse compositor'u uyandirmak icin 1px sarsma
            if changed:
                time.sleep(0.05)
                w.resize(new_w, new_h - 1)
                time.sleep(0.05)
                w.resize(new_w, new_h)
        except Exception:
            pass

    def safe_quit(self):
        slog("Guvenli cikis — pencere kapatiliyor")
        w = self._window()
        if w: w.destroy()

    def log_from_renderer(self, level, msg):
        slog(f"[Renderer/{level}] {msg}")

    def launch_mt5(self, creds_json):
        """MT5 terminal'i baslat ve credentials'i kaydet."""
        import json, subprocess, keyring

        MT5_PATH = r"C:\Program Files\GCM MT5 Terminal\terminal64.exe"
        KEYRING_SERVICE = "ustat-mt5"

        # Credentials parse
        try:
            creds = json.loads(creds_json) if creds_json else {}
        except Exception:
            creds = {}

        server = creds.get("server", "")
        login = creds.get("login", "")
        password = creds.get("password", "")

        # Eger credentials bossa, kayitli olanlari kullan
        if not server or not login:
            try:
                saved = keyring.get_password(KEYRING_SERVICE, "credentials")
                if saved:
                    saved_data = json.loads(saved)
                    server = server or saved_data.get("server", "")
                    login = login or saved_data.get("login", "")
                    password = password or saved_data.get("password", "")
            except Exception:
                pass

        # Credentials kaydet (Windows Credential Manager)
        if server and login and password:
            try:
                keyring.set_password(KEYRING_SERVICE, "credentials",
                                     json.dumps({"server": server, "login": login, "password": password}))
                slog(f"[APP] MT5 credentials kaydedildi: {server}/{login}")
            except Exception as e:
                slog(f"[APP] Credential kaydetme hatasi: {e}")

        # Zaten bagli mi kontrol
        verify = self._api_get("/api/mt5/verify", lambda r: r, {})
        if verify.get("connected"):
            return {"success": True, "alreadyConnected": True, "message": "MT5 zaten bagli"}

        # MT5 terminal baslatilsin mi?
        if not os.path.exists(MT5_PATH):
            return {"success": False, "message": f"MT5 bulunamadi: {MT5_PATH}"}

        # MT5'i baslat (fire-and-forget)
        try:
            login_arg = f"/login:{login}" if login else ""
            server_arg = f"/server:{server}" if server else ""
            cmd = [MT5_PATH]
            if login_arg: cmd.append(login_arg)
            if server_arg: cmd.append(server_arg)

            subprocess.Popen(cmd, creationflags=0x00000008)  # DETACHED_PROCESS
            slog(f"[APP] MT5 baslatildi: {server}/{login}")
            return {"success": True, "message": "MT5 baslatildi — OTP bekleniyor"}
        except Exception as e:
            return {"success": False, "message": f"MT5 baslatilamadi: {e}"}

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
        """MT5 durumu: keyring'den kayitli bilgi + API'den baglanti durumu."""
        saved = self._load_credentials()
        verify = self._api_get("/api/mt5/verify", lambda r: r, {})
        return {
            "running": verify.get("connected", False),
            "hasSaved": saved is not None,
            "server": saved.get("server") if saved else verify.get("account", {}).get("server"),
            "login": saved.get("login") if saved else str(verify.get("account", {}).get("login", "")),
        }

    def get_saved_credentials(self):
        """Kayitli credentials (Windows Credential Manager)."""
        saved = self._load_credentials()
        if saved:
            return {
                "hasSaved": True,
                "server": saved.get("server", ""),
                "login": saved.get("login", ""),
                "passwordMask": "******",
            }
        return {"hasSaved": False}

    def clear_credentials(self):
        """Kayitli credentials'i sil."""
        try:
            import keyring
            keyring.delete_password("ustat-mt5", "credentials")
            slog("[APP] Credentials silindi")
        except Exception:
            pass
        return True

    def _load_credentials(self):
        """Keyring'den credentials oku."""
        import json
        try:
            import keyring
            raw = keyring.get_password("ustat-mt5", "credentials")
            if raw:
                return json.loads(raw)
        except Exception:
            pass
        return None

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


def _write_electron_pid(pid):
    """Electron PID'ini .ustat_pids.json dosyasına ekle.

    Alt process'te (run_webview_process) çalıştığı için doğrudan
    ProcessGuard instance'a erişim yok — dosyayı direkt güncelle.
    """
    pid_file = os.path.join(USTAT_DIR, ".ustat_pids.json")
    try:
        data = {}
        if os.path.exists(pid_file):
            with open(pid_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        pids = data.get("pids", {})
        pids["electron"] = pid
        data["pids"] = pids
        tmp = pid_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        if os.path.exists(pid_file):
            os.remove(pid_file)
        os.rename(tmp, pid_file)
        slog(f"[APP] Electron PID kaydedildi: {pid}")
    except Exception as e:
        slog(f"[APP] Electron PID kayit hatasi: {e}")


_electron_pid_for_cleanup = None  # Alt process'teki Electron PID referansı


def _monitor_parent(parent_pid):
    """Ana process olurse alt process'i de kapat (orphan koruması).

    Windows'ta parent olunce child otomatik olmuyor.
    Bu thread parent PID'i izler, olurse alt process'i temizler.

    v5.9.2: Electron torun process'i de öldürülür (tree-kill).
    """
    import ctypes
    import subprocess
    kernel32 = ctypes.windll.kernel32
    SYNCHRONIZE = 0x00100000
    INFINITE = 0xFFFFFFFF

    handle = kernel32.OpenProcess(SYNCHRONIZE, False, parent_pid)
    if not handle:
        slog(f"[APP] UYARI: Parent process handle alinamadi (PID {parent_pid})")
        return

    slog(f"[APP] Parent monitor aktif (PID {parent_pid})")
    # Parent olene kadar bekle (BLOKLAR)
    kernel32.WaitForSingleObject(handle, INFINITE)
    kernel32.CloseHandle(handle)

    slog("[APP] Parent process oldu — alt process kapatiliyor!")

    # Electron torun process'ini öldür (tree-kill)
    if _electron_pid_for_cleanup:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(_electron_pid_for_cleanup)],
                capture_output=True, timeout=5,
                creationflags=0x08000000,
            )
            slog(f"[APP] Electron tree-kill basarili (PID {_electron_pid_for_cleanup})")
        except Exception as e:
            slog(f"[APP] Electron tree-kill hatasi: {e}")

    _shutdown_api()
    os._exit(0)


def run_webview_process(parent_pid=None):
    """ALT PROCESS olarak calisir. Electron + FastAPI + Engine.

    v5.9.1: pywebview yerine Electron kullanilir (ÜSTAT Finans sistemi).
    Electron native pencere yönetimi sayesinde coklu monitor, maximize,
    minimize, drag islemleri sorunsuz calisir.
    """
    import subprocess as _sp

    # Multiprocessing spawn: modul yeniden yuklenir, cwd/path ayarla
    ustat_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(ustat_dir)
    if ustat_dir not in sys.path:
        sys.path.insert(0, ustat_dir)

    # Orphan korumasi: parent olurse bizi de kapat
    if parent_pid:
        t = threading.Thread(
            target=_monitor_parent, args=(parent_pid,),
            daemon=True, name="parent-monitor",
        )
        t.start()

    # Alt process kapanirken Engine'i güvenle durdur (atexit)
    atexit.register(_shutdown_api)

    slog("[APP] Alt process baslatildi (Electron + API)")

    # ── 1. API + Engine baslat ────────────────────────────────────
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

    # api.pid dosyasını yaz — Electron'un killApiProcess() metodu bunu okur
    # Alt process PID'ini yazıyoruz (uvicorn bu process'te çalışıyor)
    try:
        api_pid_path = os.path.join(ustat_dir, "api.pid")
        with open(api_pid_path, "w") as f:
            f.write(str(os.getpid()))
        slog(f"[APP] api.pid yazıldı: {os.getpid()}")
    except Exception as e:
        slog(f"[APP] api.pid yazma hatası: {e}")

    # ── 2. Electron baslat ────────────────────────────────────────
    # NOT: Duplicate Electron koruması Electron tarafında yapılır:
    # main.js → app.requestSingleInstanceLock() — HER ZAMAN aktif.
    # İkinci Electron başlarsa otomatik kapanır, mevcut pencere öne gelir.

    desktop_dir = os.path.join(ustat_dir, "desktop")
    electron_cmd = os.path.join(desktop_dir, "node_modules", ".bin", "electron.cmd")

    if not os.path.exists(electron_cmd):
        # Fallback: npx electron
        electron_cmd = "npx.cmd"
        electron_args = [electron_cmd, "electron", "."]
        slog("[APP] electron.cmd bulunamadi, npx kullaniliyor")
    else:
        electron_args = [electron_cmd, "."]

    env = os.environ.copy()
    env["USTAT_API_MODE"] = "1"
    env["USTAT_API_PORT"] = str(API_PORT)

    slog(f"[APP] Electron baslatiliyor: {' '.join(electron_args)}")
    try:
        electron_proc = _sp.Popen(
            electron_args,
            cwd=desktop_dir,
            env=env,
        )
        slog(f"[APP] Electron baslatildi (PID {electron_proc.pid})")

        # Electron PID'ini kaydet (ProcessGuard üzerinden — hayalet koruması)
        global _electron_pid_for_cleanup
        _electron_pid_for_cleanup = electron_proc.pid
        _write_electron_pid(electron_proc.pid)

        # Electron kapanana kadar bekle (BLOKLAR)
        exit_code = electron_proc.wait()
        slog(f"[APP] Electron kapandi (exit code: {exit_code})")
    except FileNotFoundError:
        slog("[APP] HATA: Electron bulunamadi! 'cd desktop && npm install' calistirin.")
        # Electron yoksa API'yi de kapat
    except Exception as e:
        slog(f"[APP] Electron hata: {e}")

    # ── 3. Electron kapandi — Engine/API kapat ────────────────────
    slog("[APP] Pencere kapandi — Engine/API kapatiliyor...")
    _shutdown_api()
    slog("[APP] Alt process bitiyor")


_uvicorn_server = None  # Alt process'te uvicorn referansi (graceful shutdown icin)


def _start_api():
    global _uvicorn_server
    import uvicorn
    slog("[APP] API baslatiliyor (uvicorn)...")
    config = uvicorn.Config(
        "api.server:app",
        host=API_HOST,
        port=API_PORT,
        log_level="warning",
        access_log=False,
    )
    _uvicorn_server = uvicorn.Server(config)
    _uvicorn_server.install_signal_handlers = lambda: None
    _uvicorn_server.run()


_shutdown_api_called = False  # Çift çağrı koruması


def _shutdown_api():
    """Uvicorn'u graceful durdur → FastAPI lifespan → engine.stop() tetiklenir.

    Bu zincir: uvicorn shutdown → lifespan __aexit__ → engine.stop()
      → LifecycleGuard (emir kapisi kapatilir) → pozisyonlar kapatilir
      → MT5 disconnect → DB close.

    Timeout hesabi:
      engine.stop() icindeki islemler:
        - Ucustaki emir bekleme:   10sn
        - Pozisyon kapatma:        ~10sn (3 retry × ~3sn)
        - MT5 disconnect:           5sn
        - DB close + WAL flush:     2sn
        - Uvicorn kendi kapanisi:   3sn
      TOPLAM:                      ~30sn → Timeout = 45sn (guvenli marj)
    """
    global _uvicorn_server, _shutdown_api_called

    # Çift çağrı koruması (atexit + explicit çağrı)
    if _shutdown_api_called:
        return
    _shutdown_api_called = True

    if _uvicorn_server is None:
        return

    my_pid = os.getpid()
    slog(f"[APP] Uvicorn durduruluyor (graceful, PID={my_pid})...")
    _uvicorn_server.should_exit = True

    # Engine.stop() zincirinin tamamlanmasını bekle (max 45sn)
    # Eski değer 20sn idi — engine.stop() 20-30sn sürebilir, bu yüzden
    # kesiyordu ve graceful shutdown tamamlanamıyordu.
    max_wait_secs = 45
    for i in range(max_wait_secs * 2):  # 0.5sn aralıklarla kontrol
        if not port_open(API_PORT):
            slog(f"[APP] API graceful kapandi ({(i + 1) * 0.5:.1f}sn)")
            return
        time.sleep(0.5)

    # Port hala acik — ama SADECE kendi PID'imizse kapat (baska instance'i oldurme!)
    slog(f"[APP] UYARI: API {max_wait_secs}sn icinde kapanamadi (PID={my_pid})")
    try:
        import subprocess
        result = subprocess.run(
            f'netstat -ano | findstr ":{API_PORT} " | findstr "LISTENING"',
            capture_output=True, text=True, shell=True,
            creationflags=0x08000000,
        )
        for line in result.stdout.strip().split("\n"):
            parts = line.strip().split()
            if len(parts) >= 5:
                port_pid = parts[-1]
                if port_pid == str(my_pid):
                    slog(f"[APP] Kendi PID'imiz ({my_pid}) — zorla kapatiliyor")
                    kill_port(API_PORT)
                else:
                    slog(f"[APP] Port {API_PORT} baska process'e ait (PID={port_pid}) — dokunulmadi")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════
# ANA PROCESS: pystray system tray
# ══════════════════════════════════════════════════════════════════

webview_process = None
_process_guard = None  # ProcessGuard instance (modül seviyesi — cleanup erişimi için)


def start_webview():
    global webview_process
    my_pid = os.getpid()
    webview_process = multiprocessing.Process(
        target=run_webview_process,
        args=(my_pid,),
        daemon=True,
    )
    webview_process.start()
    slog(f"Alt process baslatildi (PID {webview_process.pid}, parent={my_pid})")

    # ProcessGuard'a subprocess PID'ini kaydet
    if _process_guard:
        _process_guard.register_pid("subprocess", webview_process.pid)


def stop_webview():
    global webview_process

    # ── 1. Electron torun process'i öldür (subprocess durumundan BAĞIMSIZ) ──
    # Electron PID'i ALT PROCESS tarafından dosyaya yazılır,
    # ana process'in _pids dict'inde OLMAZ — dosyadan oku.
    # Alt process ölmüş olsa bile Electron hayatta kalabilir.
    if _process_guard:
        try:
            e_pid = _process_guard._get_electron_pid_from_file()
            if e_pid:
                slog(f"Electron tree-kill: PID {e_pid}")
                _process_guard._tree_kill(e_pid, "electron")
                time.sleep(0.5)
        except Exception:
            pass

    # ── 2. Alt process'i sonlandır ───────────────────────────────────
    if webview_process and webview_process.is_alive():
        slog(f"Alt process sonlandiriliyor (PID {webview_process.pid})...")
        webview_process.terminate()
        webview_process.join(timeout=5)
        if webview_process.is_alive():
            slog("Graceful kapanma basarisiz — zorla olduruluyor")
            webview_process.kill()
            webview_process.join(timeout=3)
        slog("Alt process sonlandi")

    # ── 3. Port temizligi (garanti) ──────────────────────────────────
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


LOCK_FILE = os.path.join(USTAT_DIR, "ustat.lock")
# Global\ namespace: admin ve normal kullanıcı oturumları arasında paylaşılır.
# Local\ kullanıldığında admin (runas) ve normal process birbirini görmüyor
# → iki instance aynı anda açılabiliyor. Global\ bunu önler.
MUTEX_NAME = "Global\\USTAT_SINGLE_INSTANCE_v59"
_mutex_handle = None


def _bring_existing_to_front():
    """Zaten calisan USTAT penceresini on plana getir (Windows API)."""
    try:
        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32

        # EnumWindows ile USTAT penceresini bul
        WNDENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
        )
        target_hwnd = [None]

        def enum_callback(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value
                    if "STAT" in title and "Trading" in title:
                        target_hwnd[0] = hwnd
                        return False  # dur
            return True  # devam

        user32.EnumWindows(WNDENUMPROC(enum_callback), 0)

        if target_hwnd[0]:
            SW_RESTORE = 9
            user32.ShowWindow(target_hwnd[0], SW_RESTORE)
            user32.SetForegroundWindow(target_hwnd[0])
            return True
    except Exception:
        pass
    return False


def _is_ustat_actually_running():
    """Port 8000 veya USTAT penceresi aktif mi kontrol et."""
    if port_open(API_PORT):
        return True
    # Pencere araniyor
    return _bring_existing_to_front()


def _check_single_instance():
    """Single instance kilidi — Windows Named Mutex + port + lock file.

    Stale mutex korumasi: Mutex var ama process olmus → mutex devralinir.
    Bu durum crash/taskkill sonrasi olusur.
    """
    global _mutex_handle

    # KATMAN 1: Named Mutex (birincil — race-condition yok)
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)
        last_error = kernel32.GetLastError()

        if handle and last_error == 183:  # ERROR_ALREADY_EXISTS
            # Mutex var — gercekten calisan bir USTAT var mi?
            if _is_ustat_actually_running():
                kernel32.CloseHandle(handle)
                slog(f"Aktif instance tespit edildi (Mutex + port/pencere)")
                _bring_existing_to_front()
                return False

            # STALE MUTEX: Process olmus ama mutex kalmis
            slog("Stale mutex tespit edildi — devraliniyor...")
            # WaitForSingleObject ile abandoned mutex sahipligini al
            WAIT_ABANDONED = 0x00000080
            WAIT_OBJECT_0 = 0x00000000
            wait_result = kernel32.WaitForSingleObject(handle, 0)
            if wait_result in (WAIT_OBJECT_0, WAIT_ABANDONED):
                _mutex_handle = handle
                slog(f"Mutex devralindi (wait={wait_result:#x}) — tek instance")
            else:
                # Devralamadik ama aktif instance de yok — zorla devam
                kernel32.CloseHandle(handle)
                slog(f"UYARI: Mutex devralinamadi (wait={wait_result:#x}) — "
                     f"aktif instance yok, devam ediliyor")

        elif handle:
            _mutex_handle = handle
            slog(f"Named Mutex olusturuldu ({MUTEX_NAME}) — tek instance")
        else:
            slog(f"UYARI: Mutex olusturulamadi (hata: {last_error})")
    except Exception as e:
        slog(f"UYARI: Mutex kontrolu basarisiz ({e})")

    # KATMAN 2: Port kontrolu (yedek)
    if _mutex_handle is None and port_open(API_PORT):
        slog(f"Port {API_PORT} zaten dinleniyor — baska instance calisiyor")
        _bring_existing_to_front()
        return False

    # KATMAN 3: Lock file (yedek)
    if _mutex_handle is None and os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r") as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)  # PID hala yasiyor mu?
            slog(f"Lock file PID {old_pid} hala calisiyor")
            _bring_existing_to_front()
            return False
        except (ProcessLookupError, ValueError, OSError):
            slog("Stale lock temizlendi")
            try:
                os.remove(LOCK_FILE)
            except Exception:
                pass

    try:
        with open(LOCK_FILE, "w") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass

    return True


def _release_mutex():
    """Mutex ve lock dosyasini temizle."""
    global _mutex_handle
    if _mutex_handle:
        try:
            import ctypes
            ctypes.windll.kernel32.ReleaseMutex(_mutex_handle)
            ctypes.windll.kernel32.CloseHandle(_mutex_handle)
            _mutex_handle = None
            slog("[CLEANUP] Mutex serbest birakildi")
        except Exception:
            pass
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass


def _emergency_cleanup():
    """atexit handler — process her ne sebeple kapanirsa temizlik yapar.

    Normal kapanis, crash, signal, taskkill — hepsinde calisir.
    Idempotent: birden fazla cagirilsa da sorun cikmaz.
    """
    slog("[CLEANUP] Acil temizlik baslatildi")

    # 1. ProcessGuard ile tüm alt ağacı temizle (Electron dahil)
    if _process_guard:
        try:
            _process_guard.shutdown_all()
        except Exception:
            pass

    # 2. Alt process'i durdur (ProcessGuard başarısız olsa bile yedek)
    try:
        stop_webview()
    except Exception:
        pass

    # 3. Port hala aciksa zorla kapat (orphan engine koruması)
    try:
        if port_open(API_PORT):
            slog(f"[CLEANUP] Port {API_PORT} hala acik — zorla kapatiliyor")
            kill_port(API_PORT)
    except Exception:
        pass

    # 4. Mutex ve lock temizle
    _release_mutex()

    slog("[CLEANUP] Temizlik tamamlandi")


def main():
    global _process_guard

    # Temiz log
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("")

    slog("=" * 60)
    slog(f"USTAT v5.9 Baslatici (multiprocessing)")
    slog(f"Python: {sys.executable}")
    slog(f"Mod: {'DEV' if IS_DEV else 'PRODUCTION'}")
    slog("=" * 60)

    # ── ProcessGuard: Hayalet process temizliği ──────────────────
    # TEK SORUMLU: Önceki oturumdan kalan orphan process'leri bul + öldür
    # Single instance kilidinden ÖNCE çalışır — stale process'ler kilidi tutabilir
    try:
        from engine.process_guard import ProcessGuard
        _process_guard = ProcessGuard(
            ustat_dir=USTAT_DIR, api_port=API_PORT, slog=slog,
        )
        cleanup_report = _process_guard.startup_cleanup()
        if not cleanup_report["clean"]:
            slog(f"Hayalet temizlik raporu: {cleanup_report['killed']}")
            # Temizlik sonrası port'un serbest kalmasını bekle
            time.sleep(1)
    except Exception as e:
        slog(f"UYARI: ProcessGuard baslatilamadi ({e}) — devam ediliyor")
        _process_guard = None

    # ── Acil temizlik kaydı (crash/signal/exit) ──────────────────
    atexit.register(_emergency_cleanup)

    def _signal_handler(signum, frame):
        sig_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
        slog(f"[SIGNAL] {sig_name} alindi — guvenli kapanis baslatiliyor")
        # atexit handler'i calisacak, sadece cik
        sys.exit(0)

    try:
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)
    except Exception:
        pass  # Worker thread'den cagrilirsa basarisiz olabilir

    # ── Single instance kilidi ────────────────────────────────────
    if not _check_single_instance():
        slog("=== Mevcut instance aktif — cikiliyor ===")
        atexit.unregister(_emergency_cleanup)  # Temizlik gereksiz
        sys.exit(0)

    # ── ProcessGuard: Ana process PID kaydet ─────────────────────
    if _process_guard:
        _process_guard.register_self()

    # dist/ kontrolu
    if not IS_DEV and not os.path.isfile(os.path.join(DIST_DIR, "index.html")):
        slog("HATA: desktop/dist/index.html bulunamadi!")
        sys.exit(1)

    # Port temizligi (sadece stale/orphan process icin — normal instance yukarida yakalandi)
    # NOT: ProcessGuard zaten port temizliği yaptı, bu YEDEK kontrol
    if port_open(API_PORT):
        slog(f"Port {API_PORT} mesgul (orphan process) — temizleniyor")
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
    # (atexit de calisacak ama burada da explicit cagiralim)
    stop_webview()
    _release_mutex()

    slog("=== USTAT kapatildi ===")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
