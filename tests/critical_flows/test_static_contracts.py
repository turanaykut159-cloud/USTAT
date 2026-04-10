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
