"""12 kritik akis — statik kontrat testleri.

Bu dosya, kod tabaninin kritik yerlerinde olmasi GEREKEN desenleri
statik olarak kontrol eder. Gercek MT5 baglantisina ihtiyac yoktur.

Calisma mantigi:
    - Belirli fonksiyonlarin source'u inspect ile okunur
    - Icinde olmasi gereken string'ler / cagri kaliplari ararir
    - Bir desen eksikse test patlar ve commit yapilamaz (pre-commit hook)

Bu testler 'tanimli davranis degismesin' koruma halkasidir. Claude/insan
bir yeri refactor ederken kritik bir korumayi sessizce kaldirirsa, burada
yakalanir.

Kapsam — 12 kritik akis:
    1. send_order 2-asamali SL/TP ekleme
    2. send_order SL/TP basarisiz -> pozisyon kapatma
    3. EOD 17:45 zorunlu kapanis
    4. Hard drawdown >=15% -> L3
    5. Kill-switch L2: _close_ogul_and_hybrid (manuel dokunulmaz)
    6. Kill-switch L3: _close_all_positions
    7. BABA can_trade kapisi OGUL'da kontrol
    8. Circuit breaker 5 ardisik timeout
    9. heartbeat terminal_info -> _trade_allowed yakalamasi
   10. main loop sirasi: BABA once, OGUL sonra
   11. Config'den sihirli sayi kullanimi (self.config.get ile)
   12. mt5.initialize() evrensel koruma (bridge disi yasak)
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


# ── Flow 1: send_order 2-asamali SL/TP ───────────────────────────
def test_send_order_has_two_phase_sltp():
    from engine.mt5_bridge import MT5Bridge

    src = inspect.getsource(MT5Bridge.send_order)
    # SL/TP ekleme retry mantigi
    assert "sltp" in src.lower() or "modify_position" in src.lower(), (
        "send_order'da SL/TP ekleme mantigi bulunamadi"
    )


# ── Flow 2: SL/TP basarisiz -> korumasiz pozisyon kapatilir ──────
def test_sltp_failure_closes_unprotected_position():
    """Anayasa Kural 4: SL/TP basarisiz -> korumasiz pozisyon KAPATILIR.

    Implementasyon bridge'de degil OGUL'da: TRADE_ACTION_SLTP basarisiz
    olduktan sonra OgulSLTP (Stop/Limit pending) devreye girer; o da
    basarisiz olursa Ogul close_position cagirir.

    Koruma noktasi: engine/ogul.py icinde 'Anayasa 4.4: Korumasiz'
    veya 'OgulSLTP' + close_position pattern.
    """
    ogul_src = (ROOT / "engine" / "ogul.py").read_text(encoding="utf-8")

    # 1) OgulSLTP fallback var mi?
    assert "OgulSLTP" in ogul_src or "ogul_sltp" in ogul_src, (
        "OgulSLTP fallback mekanizmasi bulunamadi — send_order SL/TP "
        "basarisiz oldugunda plan B yok."
    )

    # 2) Anayasa 4.4 atifi (bilincli koruma) VE close_position cagrisi var mi?
    assert (
        "Anayasa 4" in ogul_src or "korumasiz" in ogul_src.lower()
        or "KORUMA" in ogul_src
    ), (
        "OGUL icinde 'Anayasa 4' / 'korumasiz' yorumu yok — niyetli koruma "
        "yorumu kaybolmus olabilir."
    )
    assert "close_position" in ogul_src, (
        "OGUL close_position cagrisi yok — SL/TP basarisizliginda "
        "pozisyon kapatma guvencesi ortadan kalkmis."
    )


# ── Flow 3: EOD 17:45 zorunlu kapanis ────────────────────────────
def test_ogul_has_end_of_day_check():
    from engine.ogul import Ogul

    assert hasattr(Ogul, "_check_end_of_day"), (
        "OGUL _check_end_of_day fonksiyonu yok — EOD kapanisi bozulmus."
    )
    src = inspect.getsource(Ogul._check_end_of_day)
    # 17:45 sabitinin varligi
    assert ("17" in src) and ("45" in src), (
        "EOD fonksiyonunda 17:45 zaman referansi yok."
    )


# ── Flow 4: Hard drawdown >=15% -> L3 ────────────────────────────
def test_baba_has_hard_drawdown_check():
    from engine.baba import Baba

    assert hasattr(Baba, "_check_hard_drawdown"), (
        "_check_hard_drawdown kaldirilmis — felaket koruma yok."
    )


# ── Flow 4b: L2 aktifken hard drawdown eskalasyonu (Anayasa Kural #6) ──
# v5.9.4 — Widget Denetimi B1 fix: Onceki kodda L2 early return nedeniyle
# _check_hard_drawdown L0/L1 seviyesinde cagriliyordu. L2 aktifken drawdown
# %15'i asarsa L3'e otomatik yukselme zorunlu.
def test_check_risk_limits_escalates_l2_to_l3_on_hard_drawdown():
    from engine.baba import Baba

    src = inspect.getsource(Baba.check_risk_limits)
    # L2 blogu icinde _check_hard_drawdown cagrisi olmali
    # ve "hard" durumda L3 aktivasyonu olmali
    assert "KILL_SWITCH_L2" in src, "check_risk_limits L2 blogu kaybolmus"
    assert "_check_hard_drawdown" in src, (
        "check_risk_limits icinde _check_hard_drawdown cagrisi yok."
    )
    # L2 kontrolunden sonra dd_check_l2 ve L3 eskalasyonu kontrol et
    l2_block_start = src.find("KILL_SWITCH_L2:")
    assert l2_block_start > 0
    l2_block = src[l2_block_start:l2_block_start + 2500]
    assert "_check_hard_drawdown" in l2_block, (
        "L2 blogunda _check_hard_drawdown cagrisi yok — L2 aktifken "
        "drawdown %15'i asarsa L3'e otomatik yukselmiyor (Anayasa Kural #6)."
    )
    assert "KILL_SWITCH_L3" in l2_block, (
        "L2 blogunda L3 eskalasyon yolu yok — Anayasa Kural #6 olu."
    )
    assert "hard_drawdown" in l2_block, (
        "L2 blogunda hard_drawdown reason ile _activate_kill_switch yok."
    )


# ── Flow 4c: Trade stats SIGN_MISMATCH anomalilerini best/worst disinda birakir ──
def test_trade_stats_excludes_sign_mismatch_from_best_worst():
    """Widget Denetimi A2: MT5 netting sync'te parcali pozisyonlar
    weighted avg entry/exit ile MT5 raw pnl arasinda tutarsiz olabilir.
    get_trade_stats bu kayitlari best_trade/worst_trade secimi disinda
    birakir ki kullanici UI'da yanlis "en karli islem" gormesin.
    """
    from api.routes import trades as trades_route
    from api.schemas import TradeItem, TradeStatsResponse

    # Helper fonksiyon var mi
    assert hasattr(trades_route, "_check_trade_consistency"), (
        "_check_trade_consistency yardimci fonksiyonu yok."
    )

    # TradeItem schema'sinda data_warning alani olmali
    assert "data_warning" in TradeItem.model_fields, (
        "TradeItem.data_warning alani yok — SIGN_MISMATCH raporlanamiyor."
    )
    # TradeStatsResponse'ta anomaly_count olmali
    assert "anomaly_count" in TradeStatsResponse.model_fields, (
        "TradeStatsResponse.anomaly_count alani yok — hariç tutulan sayi "
        "UI'a iletilmez."
    )

    # get_trade_stats source'unda clean_items filtresi kullanilmali
    stats_src = inspect.getsource(trades_route.get_trade_stats)
    assert "data_warning" in stats_src, (
        "get_trade_stats icinde data_warning filtresi yok — best_trade "
        "secimi hala anomalileri iceriyor."
    )
    assert "clean_items" in stats_src or "data_warning is None" in stats_src, (
        "get_trade_stats'ta anomaly filtresi best/worst secimine "
        "uygulanmamis."
    )
    # Helper'in dogru mantiksal sonuc uretmesi
    # BUY + exit<entry + pnl>0 → SIGN_MISMATCH
    assert (
        trades_route._check_trade_consistency("BUY", 259.87, 257.80, 2705.0)
        == "SIGN_MISMATCH"
    ), "BUY + exit<entry + pnl>0 anomali olarak tespit edilmedi."
    # SELL + exit>entry + pnl>0 → SIGN_MISMATCH
    assert (
        trades_route._check_trade_consistency("SELL", 104.26, 104.40, 485.0)
        == "SIGN_MISMATCH"
    ), "SELL + exit>entry + pnl>0 anomali olarak tespit edilmedi."
    # BUY + exit>entry + pnl>0 → None (tutarli)
    assert (
        trades_route._check_trade_consistency("BUY", 100.0, 101.0, 50.0)
        is None
    ), "Tutarli BUY trade yanlislikla anomali sayildi."
    # SELL + exit<entry + pnl>0 → None (tutarli)
    assert (
        trades_route._check_trade_consistency("SELL", 101.0, 100.0, 50.0)
        is None
    ), "Tutarli SELL trade yanlislikla anomali sayildi."
    # pnl=None → None (kontrol edilemez)
    assert (
        trades_route._check_trade_consistency("BUY", 100.0, 101.0, None)
        is None
    )


# ── Flow 4d: Bildirim tercihleri config uzerinden kalicilasir ────
def test_notification_prefs_persists_via_config():
    """Widget Denetimi A3/S1: Eski `_notification_prefs` modul dict'i process
    bellegindeydi, restart edince kayboluyordu. Artik config.ui.notification_prefs
    uzerinden kalicilastirildi. Bu test hem eski dict'in kaldirildigini hem de
    yeni persistence zincirinin (config.set + config.save) kullanildigini
    garanti eder.
    """
    from api.routes import settings as settings_route
    import inspect

    src = inspect.getsource(settings_route)

    # 1. Eski bellek tabanli dict TANIMI kaldirilmis olmali (module-level assignment)
    assert "_notification_prefs: dict" not in src, (
        "Eski bellek tabanli _notification_prefs dict'i hala tanimli — "
        "restart sonrasi tercihler kaybolur."
    )
    assert "_notification_prefs.update(" not in src, (
        "Eski _notification_prefs.update cagrisi hala var — POST endpoint "
        "config'e yazmiyor olabilir."
    )

    # 2. DEFAULT fallback sabiti var
    assert hasattr(settings_route, "DEFAULT_NOTIFICATION_PREFS"), (
        "DEFAULT_NOTIFICATION_PREFS fallback sabiti yok."
    )
    defaults = settings_route.DEFAULT_NOTIFICATION_PREFS
    assert isinstance(defaults, dict), "DEFAULT_NOTIFICATION_PREFS dict degil."
    # Frontend DEFAULT_PREFS ile senkron 5 anahtar
    for key in ("soundEnabled", "killSwitchAlert", "tradeAlert",
                "drawdownAlert", "regimeAlert"):
        assert key in defaults, f"DEFAULT_NOTIFICATION_PREFS icinde {key} yok."

    # 3. Read helper var ve config uzerinden okur
    assert hasattr(settings_route, "_read_notification_prefs_from_config"), (
        "_read_notification_prefs_from_config helper'i yok."
    )
    read_src = inspect.getsource(settings_route._read_notification_prefs_from_config)
    assert "ui.notification_prefs" in read_src, (
        "Read helper config.ui.notification_prefs key'ini kullanmiyor."
    )

    # 4. POST endpoint config.set + config.save cagriyor
    update_src = inspect.getsource(settings_route.update_notification_prefs)
    assert 'config.set("ui.notification_prefs"' in update_src or \
           "config.set('ui.notification_prefs'" in update_src, (
        "POST /settings/notification-prefs config.set cagrmiyor — "
        "kalicilasmiyor."
    )
    assert "config.save()" in update_src, (
        "POST /settings/notification-prefs config.save() cagrmiyor — "
        "disk'e yazilmayan in-memory degisiklik kaliyor."
    )


# ── Flow 5: Kill-switch L2 _close_ogul_and_hybrid manuel dokunmaz ──
def test_baba_l2_only_closes_ogul_and_hybrid():
    from engine.baba import Baba

    assert hasattr(Baba, "_close_ogul_and_hybrid"), (
        "_close_ogul_and_hybrid fonksiyonu yok — L2 tetiginde manuel "
        "pozisyonlar yanlislikla kapanir."
    )


# ── Flow 6: Kill-switch L3 _close_all_positions ──────────────────
def test_baba_l3_closes_all_positions():
    from engine.baba import Baba

    assert hasattr(Baba, "_close_all_positions"), (
        "_close_all_positions fonksiyonu yok — L3 tam kapanis yapamiyor."
    )


# ── Flow 7: BABA can_trade kapisi OGUL'da ────────────────────────
def test_ogul_respects_baba_can_trade_gate():
    from engine.ogul import Ogul

    # _execute_signal fonksiyonu risk kontrolu yapmali
    src = inspect.getsource(Ogul._execute_signal)
    assert "can_trade" in src or "check_risk_limits" in src, (
        "_execute_signal BABA can_trade kapisini kontrol etmiyor — "
        "risk kapisi atlaniyor (Anayasa Kural 2)."
    )


# ── Flow 8: Circuit breaker 5 ardisik timeout ────────────────────
def test_mt5_bridge_has_circuit_breaker():
    bridge_src = (ROOT / "engine" / "mt5_bridge.py").read_text(encoding="utf-8")
    assert "CB_FAILURE_THRESHOLD" in bridge_src or "circuit" in bridge_src.lower()


# ── Flow 9: heartbeat terminal_info -> _trade_allowed ───────────
def test_heartbeat_captures_trade_allowed():
    from engine.mt5_bridge import MT5Bridge

    src = inspect.getsource(MT5Bridge.heartbeat)
    assert "_trade_allowed" in src, (
        "heartbeat _trade_allowed state'i guncellemiyor — TopBar banner "
        "MT5 Algo Trading kapanmasini algilayamaz."
    )
    assert "trade_allowed" in src  # info.trade_allowed okunmali


# ── Flow 10: Main loop BABA once, OGUL sonra ────────────────────
def test_main_loop_order():
    main_src = (ROOT / "engine" / "main.py").read_text(encoding="utf-8")
    # _run_single_cycle icinde baba.run_cycle OGUL'dan once gecmeli
    cycle_match = re.search(r"def _run_single_cycle.*?def ", main_src, re.DOTALL)
    assert cycle_match, "_run_single_cycle bulunamadi"
    cycle_body = cycle_match.group(0)
    idx_baba = cycle_body.find("baba")
    idx_ogul = cycle_body.find("ogul")
    assert idx_baba > 0 and idx_ogul > 0, "baba veya ogul cagrisi cycle icinde yok"
    assert idx_baba < idx_ogul, (
        "_run_single_cycle icinde BABA cagirisi OGUL'dan SONRA yapiliyor! "
        "Anayasa Kural 1 — cagri sirasi DEGISTIRILEMEZ."
    )


# ── Flow 11: Config'den sihirli sayi kullanimi ──────────────────
def test_no_magic_numbers_in_baba_risk_limits():
    """BABA check_risk_limits icindeki esik degerleri config'den gelmeli."""
    from engine.baba import Baba

    src = inspect.getsource(Baba.check_risk_limits)
    # Asagidaki literal sabitler kod icinde birlesik gorunmemeli:
    # %1.8, %10, %15 — bu degerler config'den gelmeli.
    # Kontrol: self.config kullanimi var mi?
    assert "self.config" in src or "config." in src or "_config" in src, (
        "check_risk_limits config'den parametre okumuyor — sihirli sayi riski."
    )


# ── Flow 12: mt5.initialize() evrensel koruma ────────────────────
def test_no_rogue_mt5_initialize_calls():
    """mt5.initialize() sadece yetkili dosyalarda olmali (gercek cagri).

    Anayasa Kural 16: 'Projede mt5.initialize() cagrilan her noktada process
    kontrolu zorunludur. Yeni mt5.initialize() cagrisi eklemek YASAKTIR.'

    Yetkili dosyalar: engine/mt5_bridge.py (connect), health_check.py,
    api/routes/mt5_verify.py (verify endpoint).

    AST kullanilarak sadece GERCEK fonksiyon cagrilari tespit edilir —
    docstring/yorum icindeki metin saniye cekilmez.
    """
    import ast as _ast

    allowed_files = {
        "engine/mt5_bridge.py",
        "health_check.py",
        "api/routes/mt5_verify.py",  # MT5 verify endpoint — dokunulabilir degil
    }
    # archive/, tests/, .agent/, desktop/scripts/ tum test/archive dosyalari atlanacak
    skip_prefixes = ("archive/", "tests/", ".agent/", "desktop/scripts/")

    violations: list[str] = []
    for py in ROOT.rglob("*.py"):
        rel = py.relative_to(ROOT).as_posix()
        if rel.startswith(skip_prefixes):
            continue
        if rel in allowed_files:
            continue
        try:
            text = py.read_text(encoding="utf-8", errors="ignore")
            tree = _ast.parse(text)
        except Exception:
            continue

        for node in _ast.walk(tree):
            if not isinstance(node, _ast.Call):
                continue
            func = node.func
            # mt5.initialize(...)
            if (
                isinstance(func, _ast.Attribute)
                and func.attr == "initialize"
                and isinstance(func.value, _ast.Name)
                and func.value.id == "mt5"
            ):
                violations.append(f"{rel}:{node.lineno}")
                break

    assert not violations, (
        f"Yetkisiz mt5.initialize() cagrilari bulundu: {violations}. "
        "Anayasa Kural 16 ihlal ediliyor — tum MT5 bagliligi "
        "mt5_bridge.connect() uzerinden yapilmali."
    )


# ── Flow 13: main.js singleton conflict kesin cikis ──────────────
def test_mainjs_singleton_conflict_exits_with_code_42():
    """desktop/main.js singleton lock basarisiz olunca app.exit(42).

    Bug: Onceki surumde 'app.quit()' asenkron oldugu icin
    whenReady() promise'i yine fire ediyor, createWindow() cagriliyor
    ve bir hayalet pencere olusup Chromium userData mutex'i tutuyordu.
    Sonraki her baslatma denemesi bu mutex yuzunden bloke oluyordu.

    Koruma: Singleton catismasinda app.exit(42) ile SENKRON cikis
    yapilmali — exit code 42 parent Python'a 'singleton catismasi'
    sinyali gonderir, boylece parent ProcessGuard sweep + retry
    uygulayabilir.
    """
    main_js = ROOT / "desktop" / "main.js"
    assert main_js.exists(), "desktop/main.js bulunamadi"
    src = main_js.read_text(encoding="utf-8", errors="ignore")

    # gotTheLock kontrolu var
    assert "gotTheLock" in src, "requestSingleInstanceLock kontrolu bulunamadi"

    # Singleton conflict branch'inde app.exit(42) olmali
    # Bolgeyi isolate et: 'if (!gotTheLock)' ile baslayan blok
    m = re.search(r"if\s*\(\s*!\s*gotTheLock\s*\)\s*\{([^}]*)\}", src, re.DOTALL)
    assert m, "'if (!gotTheLock) {...}' blogu bulunamadi"
    block = m.group(1)

    # Blokta app.exit(42) olmali (app.quit() yalniz degil — quit async!)
    assert re.search(r"app\.exit\s*\(\s*42\s*\)", block), (
        f"Singleton conflict blogunda 'app.exit(42)' bulunamadi. "
        f"Blok icerigi: {block!r}. "
        "BUG: app.quit() asenkron oldugu icin whenReady() fire eder ve "
        "hayalet pencere olusur — app.exit(42) ile senkron cikis zorunlu."
    )


# ── Flow 14: ustat_agent.py Electron killer gercek ───────────────
def test_agent_stop_app_kills_electron_reliably():
    """ustat_agent.py handle_stop_app psutil ile Electron'u oldurur.

    Bug: Eski surum PowerShell 'Get-Process | Where CommandLine -match' kullaniyordu.
    Get-Process Windows'ta CommandLine property'sini POPULATE ETMEZ —
    regex asla eslesmiyor, Electron asla oldurulmuyordu. Her restart_app
    bir zombi Electron yaratiyor, 3 restart sonrasi singleton kilidi bloke
    oluyordu.

    Koruma: handle_stop_app icinde psutil.process_iter ile electron.exe
    cmdline'i USTAT iceren process'ler bulunup taskkill ile oldurulmeli.
    """
    agent_py = ROOT / "ustat_agent.py"
    assert agent_py.exists(), "ustat_agent.py bulunamadi"
    src = agent_py.read_text(encoding="utf-8", errors="ignore")

    # handle_stop_app fonksiyonunu izole et
    m = re.search(
        r"def handle_stop_app\([^)]*\)[^:]*:(.*?)(?=\n(?:def |class )\w)",
        src, re.DOTALL,
    )
    assert m, "handle_stop_app fonksiyonu bulunamadi"
    body = m.group(1)

    # psutil + electron + USTAT cmdline filtresi ile kill marker
    assert "psutil" in body, (
        "handle_stop_app'ta 'psutil' referansi yok — "
        "PowerShell Get-Process.CommandLine calismadigi icin psutil zorunlu"
    )
    assert "electron" in body.lower(), (
        "handle_stop_app'ta 'electron' filtresi yok"
    )
    # Marker: yeni reliable kill cagrisi
    assert "_kill_ustat_electrons" in body or "kill_electron_processes" in body, (
        "handle_stop_app icinde USTAT Electron kill helper cagrisi bulunamadi. "
        "_kill_ustat_electrons(...) veya kill_electron_processes(...) marker'i gerekli."
    )


# ── Flow 15: start_ustat singleton exit code 42 retry ────────────
def test_start_ustat_handles_electron_exit_42():
    """start_ustat.py run_webview_process, Electron exit code 42'yi yakalar.

    Koruma: Electron singleton catismasi (exit 42) durumunda parent
    Python ProcessGuard ile orphan sweep yapmali ve en cok 1 kez retry
    denemeli. Ardisik 2 catisma sonrasi durulmali (sonsuz dongu korumasi).

    Bu koruma run_webview_process Siyah Kapi fonksiyonuna SADECE ADDITIVE
    bir katmandir — mevcut kapanis zinciri degismez.
    """
    start_py = ROOT / "start_ustat.py"
    assert start_py.exists(), "start_ustat.py bulunamadi"
    src = start_py.read_text(encoding="utf-8", errors="ignore")

    # run_webview_process fonksiyonunu izole et
    m = re.search(
        r"def run_webview_process\([^)]*\)[^:]*:(.*?)(?=\n(?:def |_\w+\s*=\s*None))",
        src, re.DOTALL,
    )
    assert m, "run_webview_process fonksiyonu bulunamadi"
    body = m.group(1)

    # Exit code 42 handling
    assert "42" in body, (
        "run_webview_process'ta exit code 42 referansi bulunamadi"
    )
    # Retry sayaci marker
    assert re.search(r"singleton_retry|SINGLETON_RETRY|_singleton_retries", body), (
        "run_webview_process'ta singleton retry sayaci marker'i bulunamadi. "
        "'singleton_retry' veya '_singleton_retries' degiskeni gerekli."
    )
    # Pre-flight sweep: ProcessGuard icin marker
    assert "_find_orphan_electrons" in body or "ProcessGuard" in body, (
        "run_webview_process'ta orphan Electron sweep marker'i bulunamadi"
    )


# ── Flow 16: USTAT->BABA notification chain (BULGU #7) ──────────
def test_ustat_to_baba_notification_chain_intact():
    """USTAT->BABA feedback loop'unun uc baglanti noktasi sag mi?

    BULGU #7 (v5.9.3): _process_ustat_notifications "dead code" gibi gorunur
    ama gercekte canli bir conditional consumer. Audit/refactor sirasinda
    silinmemesi icin uc nokta statik kontrol edilir:

      1. producer  : engine/ustat.py  rp.ustat_notifications.append(...)
      2. wire      : engine/main.py   baba._risk_params_ref = risk_params
                                      ustat._risk_params = risk_params
      3. consumer  : engine/baba.py   _process_ustat_notifications fonksiyonu
                                      VE run_cycle icinden cagrilmasi

    Eger bu uc noktadan biri kaybolursa, USTAT'in BABA'ya yaptigi parametre
    ayarlamasi bildirimi sessizce kaybolur, audit-trail bozulur. Bu test
    pre-commit hook'ta calisir ve kirik zincirde commit'i bloklar.
    """
    # 1. Producer: ustat.py rp.ustat_notifications.append(...) yaz
    ustat_src = (ROOT / "engine" / "ustat.py").read_text(encoding="utf-8")
    assert "ustat_notifications.append" in ustat_src, (
        "engine/ustat.py'da 'ustat_notifications.append(...)' producer "
        "satiri bulunamadi. BULGU #7 zincirinin producer ucu kirilmis."
    )

    # 2. Wire: main.py iki tarafa da risk_params referansini ver
    main_src = (ROOT / "engine" / "main.py").read_text(encoding="utf-8")
    assert "baba._risk_params_ref" in main_src and "= self.risk_params" in main_src, (
        "engine/main.py'da 'self.baba._risk_params_ref = self.risk_params' "
        "wire satiri bulunamadi. BULGU #7 zincirinin baba wire ucu kirilmis."
    )
    assert "ustat._risk_params" in main_src, (
        "engine/main.py'da 'self.ustat._risk_params = self.risk_params' "
        "wire satiri bulunamadi. BULGU #7 zincirinin ustat wire ucu kirilmis."
    )

    # 3. Consumer: baba.py _process_ustat_notifications fonksiyonu var
    baba_src = (ROOT / "engine" / "baba.py").read_text(encoding="utf-8")
    assert "def _process_ustat_notifications" in baba_src, (
        "engine/baba.py'da '_process_ustat_notifications' fonksiyon tanimi "
        "bulunamadi. BULGU #7 zincirinin consumer ucu silinmis."
    )

    # 3b. Consumer cagri: run_cycle bu fonksiyonu cagiriyor
    from engine.baba import Baba
    cycle_src = inspect.getsource(Baba.run_cycle)
    assert "_process_ustat_notifications" in cycle_src, (
        "Baba.run_cycle icinde '_process_ustat_notifications()' cagrisi "
        "bulunamadi. BULGU #7 consumer cagrisi kaybolmus — bildirimler "
        "asla okunmayacak."
    )

    # 3c. Consumer fonksiyonu hala notifications kuyrugunu okuyor
    consumer_src = inspect.getsource(Baba._process_ustat_notifications)
    assert "ustat_notifications" in consumer_src, (
        "Baba._process_ustat_notifications gevdesi kuyrugu artik okumuyor. "
        "BULGU #7 zinciri ic mantik kirilmis."
    )


# ── Flow 17: USTAT->BABA RISK_MISS feedback chain (BULGU #8) ────
def test_ustat_to_baba_risk_miss_chain_intact():
    """USTAT->BABA RISK_MISS feedback consumer zinciri sag mi?

    BULGU #8 (v5.9.3): receive_feedback() audit'te "never called" diye
    isaretlendi ama gercekte canli bir conditional consumer. Tetikledigi
    aksiyonlar gercek ve kritik:
      - 24h ayni sembolde 3+ miss -> L1 kill-switch o sembol icin
      - 24h toplam 5+ miss        -> floating_loss esigini %10 sikilastir

    Bu zincir kirilirsa BABA, USTAT'in RISK_MISS tespitlerine cevap veremez
    ve sembol bazli L1 koruma + floating_loss tightening sessizce kaybolur.
    """
    from engine.baba import Baba
    from engine.ustat import Ustat

    # 1. Producer: ustat.py icinde baba.receive_feedback(attribution) cagrisi
    ustat_src = (ROOT / "engine" / "ustat.py").read_text(encoding="utf-8")
    assert "baba.receive_feedback(attribution)" in ustat_src, (
        "engine/ustat.py'da 'baba.receive_feedback(attribution)' producer "
        "satiri bulunamadi. BULGU #8 zincirinin producer ucu kirilmis."
    )

    # 1b. Producer'in cevreledigi kosul: responsible == BABA
    assert 'attribution.get("responsible") == "BABA"' in ustat_src, (
        "engine/ustat.py producer kosul kontrolu kaybolmus. BULGU #8 "
        "zincirinin attribution filtresi kirilmis."
    )

    # 1c. _determine_fault hala BABA responsibility uretebiliyor
    df_src = inspect.getsource(Ustat._determine_fault)
    assert '"responsible": "BABA"' in df_src or "'responsible': 'BABA'" in df_src, (
        "Ustat._determine_fault artik BABA responsibility uretmiyor. "
        "BULGU #8 zincirinin atama mantigi kirilmis — receive_feedback "
        "asla cagrilmaz hale geldi."
    )

    # 2. Consumer: baba.receive_feedback fonksiyon tanimi var
    baba_src = (ROOT / "engine" / "baba.py").read_text(encoding="utf-8")
    assert "def receive_feedback" in baba_src, (
        "engine/baba.py'da 'def receive_feedback' tanimi bulunamadi. "
        "BULGU #8 zincirinin consumer ucu silinmis."
    )

    # 2b. Consumer ic mantigi: kill-switch + floating_loss aksiyonlari
    rf_src = inspect.getsource(Baba.receive_feedback)
    assert "_risk_miss_log" in rf_src, (
        "receive_feedback _risk_miss_log sayacini artik tutmuyor."
    )
    assert "_activate_kill_switch" in rf_src or "kill_switch" in rf_src.lower(), (
        "receive_feedback artik kill-switch tetiklemiyor. BULGU #8 zinciri "
        "ic aksiyon kaybolmus — sembol bazli L1 koruma yok."
    )
    assert "max_floating_loss" in rf_src, (
        "receive_feedback artik floating_loss esigini sikilastirmiyor. "
        "BULGU #8 ikinci aksiyonu kaybolmus."
    )

    # 3. Caller chain: ustat.run_cycle -> _check_error_attribution
    rc_src = inspect.getsource(Ustat.run_cycle)
    assert "_check_error_attribution" in rc_src, (
        "Ustat.run_cycle artik _check_error_attribution cagirmiyor — "
        "BULGU #8 zincirinin trigger'i kaybolmus."
    )
