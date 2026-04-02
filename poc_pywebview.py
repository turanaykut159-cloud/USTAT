"""
ÜSTAT v6.0 — Faz 0 PoC (Proof of Concept)

AMAÇ: pywebview ile mevcut FastAPI + React build'in çalışıp çalışmadığını doğrula.
       Mevcut kodda HİÇBİR DEĞİŞİKLİK YOK — sadece yeni başlatma yöntemi.

ÇALIŞMA:
  1. FastAPI (API + Engine) → uvicorn thread'de başlar (port 8000)
  2. React build (dist/) → FastAPI statik dosya olarak sunar
  3. pywebview → native WebView2 penceresi açar → localhost:8000 yükler

TEK PROCESS: Pencere kapandığında → Python biter → Engine durur → MT5'e sinyal YOK.

KULLANIM:
  python poc_pywebview.py
"""

import os
import sys
import time
import socket
import threading

# ── Çalışma dizini ayarla ─────────────────────────────────────────
USTAT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(USTAT_DIR)
sys.path.insert(0, USTAT_DIR)

# ── Sabitler ──────────────────────────────────────────────────────
API_HOST = "127.0.0.1"
API_PORT = 8000
DIST_DIR = os.path.join(USTAT_DIR, "desktop", "dist")
BG_COLOR = "#0d1117"

APP_TITLE = "ÜSTAT v6.0 — PoC"

SPLASH_HTML = f"""<!DOCTYPE html>
<html style="background:{BG_COLOR};height:100%;margin:0">
<head><meta charset="utf-8"><title>{APP_TITLE}</title></head>
<body style="display:flex;align-items:center;justify-content:center;height:100%;
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#e6edf3;margin:0">
<div style="text-align:center">
<h1 style="font-size:48px;margin:0;font-weight:300;letter-spacing:2px">
ÜSTAT <span style="color:#484f58;font-size:24px">v6.0</span></h1>
<p style="color:#484f58;margin:20px 0 30px;font-size:14px">PoC — pywebview + FastAPI</p>
<div style="width:36px;height:36px;border:3px solid #21262d;border-top-color:#58a6ff;
border-radius:50%;animation:s 1s linear infinite;margin:0 auto"></div>
<p id="status" style="color:#30363d;font-size:13px;margin-top:24px">API başlatılıyor...</p>
</div>
<style>@keyframes s{{to{{transform:rotate(360deg)}}}}</style>
</body></html>"""


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[PoC] {ts} | {msg}")


def port_open(port):
    """Port açık mı kontrol et."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            return s.connect_ex((API_HOST, port)) == 0
    except Exception:
        return False


def start_api_server():
    """FastAPI + Engine'i uvicorn ile başlat (thread içinde)."""
    import uvicorn

    log("uvicorn başlatılıyor...")
    config = uvicorn.Config(
        "api.server:app",
        host=API_HOST,
        port=API_PORT,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    # Signal handler'ları devre dışı bırak (main thread değiliz)
    server.install_signal_handlers = lambda: None
    server.run()


def bootstrap(window):
    """Pencere açıldıktan sonra arka planda çalışır.

    1. API'yi thread'de başlat
    2. Port hazır olana kadar bekle
    3. React UI'ı yükle
    """
    # 1. API thread başlat
    api_thread = threading.Thread(target=start_api_server, daemon=True)
    api_thread.start()
    log("API thread başlatıldı")

    # 2. Port bekleme
    for i in range(150):  # 30 saniye timeout (150 × 0.2)
        if port_open(API_PORT):
            elapsed = (i + 1) * 0.2
            log(f"API hazır (port {API_PORT}, {elapsed:.1f}sn)")
            break
        time.sleep(0.2)
    else:
        log(f"HATA: API {30}sn içinde başlamadı!")
        window.evaluate_js(
            'document.getElementById("status").textContent = "API başlatılamadı!";'
            'document.getElementById("status").style.color = "#ef5350";'
        )
        return

    # 3. React UI yükle
    log(f"React UI yükleniyor: http://{API_HOST}:{API_PORT}")
    window.load_url(f"http://{API_HOST}:{API_PORT}")
    log("UI yüklendi — PoC başarılı!")


def main():
    import webview

    log("=" * 50)
    log(f"ÜSTAT v6.0 — Faz 0 PoC")
    log(f"Python: {sys.executable}")
    log(f"pywebview: 6.x (installed)")
    log(f"dist/: {os.path.exists(os.path.join(DIST_DIR, 'index.html'))}")
    log("=" * 50)

    # dist/ var mı kontrol
    if not os.path.isfile(os.path.join(DIST_DIR, "index.html")):
        log("HATA: desktop/dist/index.html bulunamadı!")
        log("Çözüm: cd desktop && npm run build")
        sys.exit(1)

    # Port meşgul mü kontrol
    if port_open(API_PORT):
        log(f"UYARI: Port {API_PORT} zaten açık — mevcut API kullanılacak")
        # Doğrudan UI'a bağlan
        window = webview.create_window(
            APP_TITLE,
            url=f"http://{API_HOST}:{API_PORT}",
            width=1400,
            height=900,
            min_size=(1200, 800),
            background_color=BG_COLOR,
            frameless=True,
            easy_drag=True,
            on_top=True,
        )
        webview.start(debug=True)
    else:
        # Normal akış: splash → API başlat → UI yükle
        window = webview.create_window(
            APP_TITLE,
            html=SPLASH_HTML,
            width=1400,
            height=900,
            min_size=(1200, 800),
            background_color=BG_COLOR,
            frameless=True,
            easy_drag=True,
            on_top=True,
        )
        webview.start(bootstrap, window, debug=True)

    # ← Buraya gelince pencere kapanmış demektir
    log("Pencere kapatıldı — process sonlanıyor")
    log("Engine, API, MT5 bağlantısı — HEPSİ durduruldu")


if __name__ == "__main__":
    main()
