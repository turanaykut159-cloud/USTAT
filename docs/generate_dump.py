"""USTAT v5.0 kod dokumu olusturucu."""
import os
import datetime

OUTPUT = r"C:\USTAT\docs\USTAT_v5_kod_dokumu_2026-02-23.md"

# Dosya gruplari: (baslik, [dosya yollari])
GROUPS = [
    ("1. KOK DOSYALAR (Root)", [
        ".gitignore", "CLAUDE.md", "README.md", "USTAT_REHBER.md",
        "requirements.txt", "package.json",
        "start_ustat.py", "start_ustat.bat", "start_ustat.vbs",
        "factory_reset.bat", "teshis.bat", "test_trade.py",
    ]),
    ("2. CONFIG", [
        "config/default.json",
        ".claude/launch.json",
        ".claude/settings.local.json",
    ]),
    ("3. ENGINE - Ana Motor", [
        "engine/__init__.py", "engine/config.py", "engine/logger.py",
        "engine/main.py", "engine/baba.py", "engine/ogul.py",
        "engine/ustat.py", "engine/mt5_bridge.py",
        "engine/database.py", "engine/data_pipeline.py",
    ]),
    ("4. ENGINE - Modeller", [
        "engine/models/__init__.py", "engine/models/regime.py",
        "engine/models/risk.py", "engine/models/signal.py",
        "engine/models/trade.py",
    ]),
    ("5. ENGINE - Yardimcilar (Utils)", [
        "engine/utils/__init__.py", "engine/utils/constants.py",
        "engine/utils/indicators.py", "engine/utils/time_utils.py",
    ]),
    ("6. API - FastAPI Sunucu", [
        "api/__init__.py", "api/deps.py", "api/schemas.py", "api/server.py",
    ]),
    ("7. API - Route'lar", [
        "api/routes/__init__.py", "api/routes/account.py",
        "api/routes/events.py", "api/routes/killswitch.py",
        "api/routes/live.py", "api/routes/manual_trade.py",
        "api/routes/performance.py", "api/routes/positions.py",
        "api/routes/risk.py", "api/routes/status.py",
        "api/routes/top5.py", "api/routes/trades.py",
    ]),
    ("8. DESKTOP - Electron Ana Surec", [
        "desktop/main.js", "desktop/preload.js", "desktop/mt5Manager.js",
        "desktop/package.json", "desktop/vite.config.js",
    ]),
    ("9. DESKTOP - React Bilesenler", [
        "desktop/src/main.jsx", "desktop/src/App.jsx",
        "desktop/src/components/Dashboard.jsx",
        "desktop/src/components/LockScreen.jsx",
        "desktop/src/components/ManualTrade.jsx",
        "desktop/src/components/OpenPositions.jsx",
        "desktop/src/components/Performance.jsx",
        "desktop/src/components/RiskManagement.jsx",
        "desktop/src/components/Settings.jsx",
        "desktop/src/components/SideNav.jsx",
        "desktop/src/components/TopBar.jsx",
        "desktop/src/components/TradeHistory.jsx",
    ]),
    ("10. DESKTOP - Servisler", [
        "desktop/src/services/api.js",
        "desktop/src/services/mt5Launcher.js",
        "desktop/src/services/storage.js",
    ]),
    ("11. DESKTOP - Stiller ve HTML", [
        "desktop/src/styles/theme.css",
        "desktop/index.html",
        "desktop/assets/icon.svg",
    ]),
    ("12. DESKTOP - Scriptler ve Araclar", [
        "desktop/scripts/mt5_automator.py",
        "desktop/scripts/otp_teshis.py",
        "desktop/assets/generate_icon.py",
        "desktop/assets/generate-icon.js",
    ]),
    ("13. BACKTEST", [
        "backtest/__init__.py", "backtest/runner.py", "backtest/report.py",
        "backtest/monte_carlo.py", "backtest/sensitivity.py",
        "backtest/session_model.py", "backtest/slippage_model.py",
        "backtest/spread_model.py", "backtest/stress_test.py",
        "backtest/walk_forward.py",
    ]),
    ("14. TESTLER", [
        "tests/test_baba.py", "tests/test_ogul.py", "tests/test_ustat.py",
        "tests/test_mt5_bridge.py", "tests/test_main.py",
        "tests/test_data_pipeline.py", "tests/test_indicators.py",
        "tests/test_integration.py",
    ]),
    ("15. DEBUG SCRIPTLERI", [
        "debug_mt5.py", "debug_otp_admin.py", "debug_pipeline.py",
        "debug_symbols.py", "debug_windows.py",
    ]),
]

EXT_LANG = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript",
    ".css": "css", ".html": "html", ".json": "json",
    ".md": "markdown", ".bat": "batch", ".vbs": "vbscript",
    ".svg": "xml",
}

BASE = r"C:\USTAT"
file_count = 0
line_count = 0

with open(OUTPUT, "w", encoding="utf-8") as out:
    # Header
    out.write("# USTAT v5.0 - TAM KOD DOKUMU\n")
    out.write(f"**Tarih:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    out.write("**Amac:** Projenin tamamen yeniden olusturulabilmesi icin eksiksiz kaynak kod yedegi\n\n")
    out.write("> Bu dosyadan tum proje dosyalari orijinal dizin yapisiyla yeniden olusturulabilir.\n")
    out.write("> Binary dosyalar (ico, png, exe, db) ve node_modules dahil degildir.\n\n")
    out.write("---\n\n")

    for group_title, files in GROUPS:
        sep = "=" * 72
        out.write(f"## {group_title}\n\n")
        out.write(f"{sep}\n\n")

        for rel_path in files:
            full_path = os.path.join(BASE, rel_path.replace("/", os.sep))
            if not os.path.isfile(full_path):
                out.write(f"### `{rel_path}` — DOSYA BULUNAMADI\n\n")
                continue

            ext = os.path.splitext(rel_path)[1]
            lang = EXT_LANG.get(ext, "")

            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except Exception as e:
                out.write(f"### `{rel_path}` — OKUMA HATASI: {e}\n\n")
                continue

            flines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
            file_count += 1
            line_count += flines

            out.write(f"### `{rel_path}` ({flines} satir)\n\n")
            out.write(f"```{lang}\n")
            out.write(content)
            if content and not content.endswith("\n"):
                out.write("\n")
            out.write("```\n\n")

        out.write("\n")

    # Footer - rebuild instructions
    out.write("---\n\n")
    out.write("## YENIDEN OLUSTURMA TALIMATLARI\n\n")
    out.write("Bu dokumden projeyi sifirdan olusturmak icin:\n\n")
    out.write("### 1. Dizin yapisini olustur:\n")
    out.write("```bash\n")
    out.write("mkdir -p engine/models engine/utils api/routes backtest tests config\n")
    out.write("mkdir -p desktop/src/components desktop/src/services desktop/src/styles\n")
    out.write("mkdir -p desktop/scripts desktop/assets logs database\n")
    out.write("```\n\n")
    out.write("### 2. Her dosyayi ilgili yoluna kopyala\n")
    out.write("Yukaridaki basliklardaki dosya yollarini kullan.\n\n")
    out.write("### 3. Python bagimliliklari:\n")
    out.write("```bash\npip install -r requirements.txt\n```\n\n")
    out.write("### 4. Node bagimliliklari:\n")
    out.write("```bash\ncd desktop && npm install\n```\n\n")
    out.write("### 5. Binary dosyalar (ayri yedeklenmeli):\n")
    out.write("- `desktop/assets/icon.ico` — Electron uygulama ikonu\n")
    out.write("- `desktop/assets/icon.png` — PNG versiyon\n")
    out.write("- `database/trades.db` — SQLite veritabani (calisma zamaninda otomatik olusur)\n\n")
    out.write("### 6. Calistirma:\n")
    out.write("```bash\npython start_ustat.py\n```\n\n")

    # Stats
    out.write("---\n\n")
    out.write(f"**Toplam kaynak dosya:** {file_count}\n\n")
    out.write(f"**Toplam satir:** {line_count:,}\n\n")
    out.write(f"**Dokum tarihi:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

# Summary
size = os.path.getsize(OUTPUT)
size_mb = size / (1024 * 1024)
print(f"{'=' * 50}")
print(f"  KOD DOKUMU TAMAMLANDI")
print(f"{'=' * 50}")
print(f"  Dosya    : {OUTPUT}")
print(f"  Kaynak   : {file_count} dosya")
print(f"  Satir    : {line_count:,}")
print(f"  Boyut    : {size_mb:.2f} MB ({size:,} byte)")
print(f"{'=' * 50}")
