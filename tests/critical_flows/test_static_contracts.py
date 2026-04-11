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


# ── Flow 4e: Monitor modStatus gercek sinyallere bagli ───────────
def test_monitor_modstatus_not_hardcoded():
    """Widget Denetimi A4/B9: Monitor.jsx `modStatus.manuel = 'ok'` sabit
    hardcode'uydu; BABA/OGUL/H-Engine rozetleri de engine_running ve
    errorCounts ile zenginlestirilmemisti. Bu test:
      1. `manuel: 'ok'` literal'inin kaldirildigini,
      2. modStatus blogunda engine_running kapisinin bulundugunu,
      3. modStatus blogunda errorCounts referansinin oldugunu,
      4. killLevel >= 2 icin OGUL/H-Engine err kapisinin oldugunu
    dogrular. Pre-commit hook ile korunur.
    """
    monitor_path = ROOT / "desktop" / "src" / "components" / "Monitor.jsx"
    assert monitor_path.exists(), "Monitor.jsx bulunamadi."
    src = monitor_path.read_text(encoding="utf-8")

    # modStatus blogunu izole et (kar\u0131\u015fmas\u0131n diye)
    mod_match = re.search(r"const modStatus\s*=(.*?)\n\s*//", src, re.DOTALL)
    assert mod_match, "modStatus tanimi Monitor.jsx icinde bulunamadi."
    mod_block = mod_match.group(1)

    # 1. Eski hardcode literal kaldirilmis olmali
    assert "manuel: 'ok'" not in mod_block and 'manuel: "ok"' not in mod_block, (
        "Monitor.jsx modStatus.manuel hala hardcode 'ok' — manuel motor "
        "hatasi hicbir zaman rozete yansimaz (Widget Denetimi B9)."
    )

    # 2. engine_running kapisi modStatus hesabinda kullanilmali
    assert "engineRunning" in mod_block, (
        "modStatus engine_running kontrolu yapmiyor — engine oldu bile "
        "BABA yesil gorunebilir."
    )

    # 3. errorCounts referansi modStatus blogunda olmali
    assert "errorCounts" in mod_block, (
        "modStatus errorCounts'u kullanmiyor — modul hatalari rozetlere "
        "yansimiyor."
    )

    # 4. killLevel >= 2 kapisi OGUL/H-Engine icin olmali (L2 -> err)
    assert "killLevel >= 2" in mod_block, (
        "modStatus L2 kill-switch kontrolu yapmiyor — OGUL/H-Engine "
        "durdugu halde yesil goruluyor olabilir."
    )


# ── Flow 4f: event_bus.emit dup-key koruma ───────────────────────
def test_event_bus_emit_preserves_outer_type():
    """Widget Denetimi B-finding: event_bus.emit dup-key bug'i.

    Eski kod `{"type": event, **(data or {})}` kullaniyordu — ic data'da
    'type' varsa dict spread dis event type'ini eziyordu. Sonuc: h_engine
    `emit("notification", {"type": "hybrid_eod", ...})` cagrisi payload'i
    `{"type": "hybrid_eod", ...}` olarak uretiyor, Dashboard WS branch'i
    `msg.type === 'notification'` hicbir zaman eslesmiyor (olu kod).

    Yeni mantik: ic 'type' notif_type'a tasinir, dis event her zaman
    'type' olarak yazilir. Bu test hem RUNTIME davranisi hem de
    KAYNAK KOD desenini kontrol eder.
    """
    from engine import event_bus
    import inspect

    # 1. Runtime davranisi — drain sonrasi outer type korunmali
    with event_bus._pending_lock:
        event_bus._pending.clear()
    event_bus.emit("notification", {
        "type": "hybrid_eod",
        "title": "Test",
        "message": "test msg",
        "severity": "warning",
    })
    events = event_bus.drain()
    assert len(events) == 1, f"drain 1 event beklendi, {len(events)} alindi"
    ev = events[0]
    assert ev["type"] == "notification", (
        f"Outer type dup-key ile ezildi! Beklenen 'notification', alinan "
        f"'{ev.get('type')}'. Dup-key bug geri donmus."
    )
    assert ev.get("notif_type") == "hybrid_eod", (
        f"Inner type notif_type'a tasinmamis. event: {ev}"
    )
    assert ev.get("message") == "test msg", (
        "Diger data alanlari kayboldu."
    )

    # 2. notif_type override edilmemeli (caller zaten notif_type set ettiyse)
    with event_bus._pending_lock:
        event_bus._pending.clear()
    event_bus.emit("notification", {
        "type": "inner_should_be_ignored",
        "notif_type": "explicit_value",
    })
    events = event_bus.drain()
    assert events[0].get("notif_type") == "explicit_value", (
        "Explicit notif_type caller tarafindan set edildiyse override edilmemeli."
    )

    # 3. Statik kaynak kontrolu — eski dup-key kalip YASAK
    src = inspect.getsource(event_bus.emit)
    assert '{"type": event, **' not in src, (
        "Eski dup-key dict literal kalip geri dondu — "
        '`{"type": event, **(data or {})}` kullanimi YASAK.'
    )
    assert "notif_type" in src, (
        "emit icinde notif_type dup-key korumasi yok."
    )


# ── Flow 4g: Monitor errorCounts structured classifier ──────────
def test_monitor_error_counts_uses_structured_classifier():
    """Widget Denetimi B25: Monitor.jsx `errorCounts` hesaplamasi eskiden
    `msg.toLowerCase().includes('baba')` gibi substring kontrolleri ile
    yapiliyordu. Iki kritik sorun:
      1) Gercek uretim event type'lari (KILL_SWITCH, DRAWDOWN_LIMIT,
         TRADE_ERROR, SYSTEM_STOP, DAILY_LOSS_STOP) mesaj metninde
         'baba'/'ogul' kelimesi icermiyor — substring fallback tum
         uretim olaylarini sayim disi birakiyordu (olu kod).
      2) `String.toLowerCase()` Turkce locale'e duyarsiz — `Oğul`,
         `Üstat` gibi Unicode karakterler inconsistent esleserdi.

    Yeni yaklasim: `classifyEventModule` helper'i once yapisal
    `event.type` prefix tablosu, sonra `toLocaleLowerCase('tr-TR')` +
    word-boundary regex fallback kullanir.

    Bu test Monitor.jsx kaynaginda:
      - classifyEventModule fonksiyonunun varligini
      - eski `msg.toLowerCase().includes('baba')` kalibinin artik
        kullanilmadigini
      - `toLocaleLowerCase('tr-TR')` kullanimini
      - MODULE_TYPE_PREFIX haritasinda uretim type'larinin var oldugunu
    dogrular.
    """
    monitor_path = ROOT / "desktop" / "src" / "components" / "Monitor.jsx"
    assert monitor_path.exists(), f"Monitor.jsx bulunamadi: {monitor_path}"
    src = monitor_path.read_text(encoding="utf-8")

    # 1. classifyEventModule helper tanimli
    assert "function classifyEventModule" in src, (
        "classifyEventModule helper kaldirildi — structured classifier "
        "yerine eski substring parse geri donmus olabilir."
    )

    # 2. Eski kirik substring kalibi YASAK
    assert "msg.includes('baba')" not in src, (
        "Eski substring parse kalibi geri dondu — uretim event'leri "
        "sayim disi kalir (B25 bug)."
    )
    assert ".toLowerCase().includes(" not in src, (
        "toLowerCase().includes() kalibi Monitor.jsx'te gorunmemeli — "
        "Turkce locale duyarsiz ve false-positive uretir."
    )

    # 3. Turkce locale lowercase
    assert "toLocaleLowerCase('tr-TR')" in src, (
        "Monitor.jsx'te Turkce locale lowercase kullanimi yok — "
        "'Oğul'/'Üstat' gibi Unicode mesajlar inconsistent eslesebilir."
    )

    # 4. Uretim type'lari MODULE_TYPE_PREFIX haritasinda olmali
    # Canli DB'de gorulen: KILL_SWITCH, DRAWDOWN_, TRADE_, SYSTEM_STOP,
    # DAILY_LOSS_STOP, HYBRID_ (hengine), MANUAL_/MANUEL_, USTAT_
    required_type_prefixes = [
        "KILL_SWITCH",
        "DRAWDOWN_",
        "TRADE_",
        "SYSTEM_STOP",
        "DAILY_LOSS_STOP",
        "HYBRID_",
        "MANUAL_",
        "MANUEL_",
        "USTAT_",
    ]
    for prefix in required_type_prefixes:
        assert prefix in src, (
            f"MODULE_TYPE_PREFIX haritasinda '{prefix}' eksik — "
            f"uretimde gorulen bu event type'i siniflandirilamaz."
        )

    # 5. Word-boundary regex fallback (ornek: \\bbaba\\b)
    assert r"\bbaba\b" in src, (
        "Word-boundary regex fallback kalibi yok — substring parse riski."
    )


# ── Flow 4h: Monitor ResponseBar eşikleri CYCLE_INTERVAL_MS tabanlı ──
def test_monitor_response_bars_use_cycle_interval_budget():
    """Widget Denetimi A9 (B10+H14): Monitor.jsx'te PERFORMANS paneli
    ResponseBar'lari eskiden hardcoded 50/100/300ms mikro-benchmark
    max degerleri kullaniyordu. Backend `config/default.json::
    engine.cycle_interval = 10` saniye (= 10000ms) bütçesinde çalışir;
    canli ortamda DataPipeline ~2600ms, toplam döngü ~2800ms cıkıyor,
    bu da UI'da tüm barlari daima dolu/kirmizi gosteriyordu.

    Yeni: `CYCLE_INTERVAL_MS = 10000` sabiti tanimlandi, tüm
    ResponseBar max'lari ve DÖNGÜ SÜRESİ StatCard eşikleri bu sabitin
    yüzdesi olarak hesaplanir. ResponseBar'a yük-yüzdesi tabanli renk
    mantigi eklendi (>%70 kirmizi, >%30 turuncu, aksi temel renk).

    Bu test:
      - CYCLE_INTERVAL_MS sabitinin tanimli oldugunu
      - Eski hardcoded literal max props'un (max={50}, max={100},
        max={300}) gitmis oldugunu
      - ResponseBar max props'un CYCLE_INTERVAL_MS kullandigini
      - Yük-yüzdesi renk mantiginin (pct > 70 / pct > 30) var oldugunu
      - DÖNGÜ SÜRESİ StatCard esigi'nin CYCLE_INTERVAL_MS tabanli
        oldugunu dogrular.
    """
    monitor_path = ROOT / "desktop" / "src" / "components" / "Monitor.jsx"
    assert monitor_path.exists(), f"Monitor.jsx bulunamadi: {monitor_path}"
    src = monitor_path.read_text(encoding="utf-8")

    # 1. CYCLE_INTERVAL_MS sabiti tanimli
    assert "CYCLE_INTERVAL_MS = 10000" in src, (
        "CYCLE_INTERVAL_MS sabiti (10000ms) kaldirildi — ResponseBar'lar "
        "artik backend dongu butcesiyle senkron degil."
    )

    # 2. Eski hardcoded max props YASAK (mikro-benchmark degerleri)
    forbidden_literals = ["max={50}", "max={100}", "max={300}"]
    for lit in forbidden_literals:
        assert lit not in src, (
            f"Eski mikro-benchmark max prop '{lit}' geri dondu — "
            f"canli ortamda ResponseBar daima dolu gorunecek."
        )

    # 3. ResponseBar max props CYCLE_INTERVAL_MS kullanmali (>= 6 kullanim)
    cycle_max_count = src.count("max={CYCLE_INTERVAL_MS}")
    assert cycle_max_count >= 6, (
        f"max={{CYCLE_INTERVAL_MS}} kullanimi {cycle_max_count}/6 — "
        f"BABA/OGUL/USTAT/H-ENGINE/VERI GUNCELLEME/TOPLAM DONGU "
        f"ResponseBar'larinin hepsi butce tabanli olmali."
    )

    # 4. Yuk-yuzdesi tabanli renk mantigi (ResponseBar icinde)
    assert "pct > 70" in src, (
        "ResponseBar yuk-yuzdesi kirmizi esigi (pct > 70) kaldirildi."
    )
    assert "pct > 30" in src, (
        "ResponseBar yuk-yuzdesi turuncu esigi (pct > 30) kaldirildi."
    )

    # 5. DÖNGÜ SÜRESİ StatCard esigi CYCLE_INTERVAL_MS tabanli
    # Eski: `cycleAvg > 50` sabit mikro-benchmark esigi YASAK
    assert "cycleAvg > 50 ?" not in src, (
        "Eski DONGU SURESI esigi 'cycleAvg > 50' geri dondu — "
        "CYCLE_INTERVAL_MS tabanli olmalidir."
    )
    assert "cycleAvg > CYCLE_INTERVAL_MS" in src, (
        "DONGU SURESI StatCard esigi CYCLE_INTERVAL_MS tabanli degil."
    )

    # 6. DONGU ISTATISTIK MAX esigi CYCLE_INTERVAL_MS tabanli
    # Eski: `(cycle?.max_ms ?? 0) > 100` hardcoded 100ms YASAK
    assert "> 100 ? '#f39c12'" not in src, (
        "Eski MAX esigi '> 100' hardcoded geri dondu — "
        "CYCLE_INTERVAL_MS tabanli olmalidir."
    )
    assert "cycle?.max_ms ?? 0) > CYCLE_INTERVAL_MS" in src, (
        "DONGU ISTATISTIK MAX esigi CYCLE_INTERVAL_MS tabanli degil."
    )


# ── Flow 4i: BIST seans saatleri config/api/frontend senkron ─────
def test_session_hours_from_config_to_frontend():
    """Widget Denetimi A17 (H6+H10): EOD saat sabitleri config'e tasindi.

    Eskiden ErrorTracker.jsx'te EOD_CLOSE_HOUR=17/EOD_CLOSE_MIN=45/
    VIOP_OPEN_HOUR=9/VIOP_CLOSE_HOUR=18 gibi hardcoded sabitler vardi.
    Performance.jsx heatmap'te de `for (let h = 9; h <= 18; h++)` ile
    literal 9-18 araligi kullaniliyordu. Backend `engine.trading_close`
    degistiginde frontend sessizce senkronsuz kaliyordu.

    Yeni: `config/default.json::session` blogu eklendi (market_open,
    market_close, eod_close). `api/schemas.py::SessionHoursResponse`
    ve `api/routes/settings.py::get_session_hours` endpoint'i sunuldu.
    Frontend `services/api.js::getSession()` cagirir, ErrorTracker ve
    Performance mount'ta fetch edip state'e koyar; hata durumunda
    DEFAULT fallback devreye girer (UI asla kirilmaz).

    Bu test:
      - config/default.json'da session blogu var (market_open,
        market_close, eod_close)
      - api/schemas.py'de SessionHoursResponse sinifi var
      - api/routes/settings.py'de get_session_hours endpoint'i var
        ve config.get("session") cagriyor
      - desktop/src/services/api.js'de getSession fonksiyonu
      - ErrorTracker.jsx ve Performance.jsx getSession'i import
        ediyor ve useEffect ile fetch ediyor
      - ErrorTracker.jsx'te eski hardcoded VIOP_* / EOD_* sabitleri
        KALDIRILDI (yalnizca DEFAULT_SESSION_HOURS fallback kaldi)
      - Performance.jsx'te eski `for (let h = 9; h <= 18; h++)`
        hardcoded literal'i KALDIRILDI (heatmapHours state'inden
        okunuyor).
    """
    import json

    # 1. config/default.json::session blogu
    config_path = ROOT / "config" / "default.json"
    assert config_path.exists(), f"config/default.json bulunamadi: {config_path}"
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    assert "session" in cfg, (
        "config/default.json'da 'session' blogu yok — "
        "BIST VIOP seans saatleri hardcoded kalmis."
    )
    session_block = cfg["session"]
    for key in ("market_open", "market_close", "eod_close"):
        assert key in session_block, (
            f"config session blogu eksik anahtar: {key} — frontend "
            f"fetch edip kullanamaz."
        )
        assert isinstance(session_block[key], str), (
            f"config session.{key} string olmalidir (HH:MM format)."
        )

    # 2. api/schemas.py::SessionHoursResponse
    schemas_path = ROOT / "api" / "schemas.py"
    schemas_src = schemas_path.read_text(encoding="utf-8")
    assert "class SessionHoursResponse" in schemas_src, (
        "api/schemas.py'de SessionHoursResponse sinifi yok — "
        "get_session endpoint'i response_model'siz kalir."
    )
    assert 'market_open: str' in schemas_src, (
        "SessionHoursResponse.market_open alani eksik."
    )
    assert 'market_close: str' in schemas_src, (
        "SessionHoursResponse.market_close alani eksik."
    )
    assert 'eod_close: str' in schemas_src, (
        "SessionHoursResponse.eod_close alani eksik."
    )

    # 3. api/routes/settings.py::get_session_hours
    settings_path = ROOT / "api" / "routes" / "settings.py"
    settings_src = settings_path.read_text(encoding="utf-8")
    assert "async def get_session_hours" in settings_src, (
        "api/routes/settings.py'de get_session_hours endpoint'i yok."
    )
    assert '"/settings/session"' in settings_src, (
        "settings.py'de GET /settings/session route kaydi yok."
    )
    assert 'config.get("session"' in settings_src, (
        "settings.py get_session_hours, config.get('session') "
        "cagirmiyor — backend senkronu kaybolmus."
    )

    # 4. desktop/src/services/api.js::getSession
    api_js_path = ROOT / "desktop" / "src" / "services" / "api.js"
    api_js_src = api_js_path.read_text(encoding="utf-8")
    assert "export async function getSession" in api_js_src, (
        "services/api.js'de getSession fonksiyonu yok — "
        "frontend session hours fetch edemez."
    )
    assert "'/settings/session'" in api_js_src, (
        "getSession /settings/session endpoint'ine cagri atmiyor."
    )

    # 5. ErrorTracker.jsx getSession import + kullanim
    et_path = ROOT / "desktop" / "src" / "components" / "ErrorTracker.jsx"
    et_src = et_path.read_text(encoding="utf-8")
    assert "getSession" in et_src, (
        "ErrorTracker.jsx getSession'i import etmiyor — session "
        "hours hardcoded fallback'e dusuyor."
    )
    # Eski hardcoded sabitler KALDIRILDI
    forbidden_et = [
        "const EOD_CLOSE_HOUR = 17",
        "const EOD_CLOSE_MIN = 45",
        "const VIOP_OPEN_HOUR = 9",
        "const VIOP_OPEN_MIN = 30",
        "const VIOP_CLOSE_HOUR = 18",
        "const VIOP_CLOSE_MIN = 15",
    ]
    for lit in forbidden_et:
        assert lit not in et_src, (
            f"ErrorTracker.jsx eski hardcoded sabit geri dondu: '{lit}' — "
            f"config/default.json::session'dan okunmali."
        )
    # Yeni DEFAULT fallback var
    assert "DEFAULT_SESSION_HOURS" in et_src, (
        "ErrorTracker.jsx DEFAULT_SESSION_HOURS fallback'i yok — "
        "API hatasinda UI kirilir."
    )

    # 6. Performance.jsx getSession + heatmap aralik
    perf_path = ROOT / "desktop" / "src" / "components" / "Performance.jsx"
    perf_src = perf_path.read_text(encoding="utf-8")
    assert "getSession" in perf_src, (
        "Performance.jsx getSession'i import etmiyor — heatmap "
        "hardcoded 9-18 araligina dusuyor."
    )
    # Eski hardcoded heatmap aralik literal'i YASAK
    assert "for (let h = 9; h <= 18; h++)" not in perf_src, (
        "Performance.jsx heatmap eski hardcoded 'for (let h = 9; "
        "h <= 18; h++)' aralik literal'i geri dondu — heatmapHours "
        "state'inden okunmali."
    )
    assert "heatmapHours" in perf_src, (
        "Performance.jsx heatmapHours state'i yok — session hours "
        "backend'den cekilmiyor."
    )


# ── Flow 4j: Stats baseline config->api->frontend tek kaynak zinciri (A7) ──
def test_stats_baseline_single_source_chain():
    """Widget Denetimi A7 — STATS_BASELINE artik
    config/default.json::risk.stats_baseline_date'den okunur, frontend
    /settings/stats-baseline endpoint'inden ceker ve Performance+TradeHistory
    sayfalarinda label olarak gosterir. Iki ayri baseline (stats vs risk)
    ayni API response'unda birlikte doner.
    """
    import json
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]

    # 1) config/default.json → risk.stats_baseline_date var mi?
    cfg_path = root / "config" / "default.json"
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    assert "risk" in cfg, "config/default.json 'risk' blogu eksik"
    assert "stats_baseline_date" in cfg["risk"], (
        "config/default.json::risk.stats_baseline_date yok — A7 tek kaynak "
        "ilkesi bozulmus."
    )
    assert isinstance(cfg["risk"]["stats_baseline_date"], str), (
        "risk.stats_baseline_date string olmali (YYYY-MM-DD)."
    )
    assert re.match(r"^\d{4}-\d{2}-\d{2}", cfg["risk"]["stats_baseline_date"]), (
        "risk.stats_baseline_date ISO tarih formatinda olmali."
    )
    # risk.baseline_date korunmali (ayri kavram)
    assert "baseline_date" in cfg["risk"], (
        "risk.baseline_date korundu mu? A7 yanlislikla risk baseline'i "
        "silmis olabilir."
    )

    # 2) api/constants.py → get_stats_baseline helper var mi?
    constants_src = (root / "api" / "constants.py").read_text(encoding="utf-8")
    assert "def get_stats_baseline" in constants_src, (
        "api/constants.py::get_stats_baseline helper'i yok — A7 tek kaynak "
        "ilkesi bozulmus."
    )
    assert 'risk.stats_baseline_date' in constants_src, (
        "api/constants.py get_stats_baseline() config anahtarini okumuyor."
    )
    assert "STATS_BASELINE = " in constants_src, (
        "api/constants.py STATS_BASELINE fallback sabiti kaldirildi — A7 "
        "geri uyumluluk bozulmus."
    )

    # 3) api/schemas.py → StatsBaselineResponse modeli
    schemas_src = (root / "api" / "schemas.py").read_text(encoding="utf-8")
    assert "class StatsBaselineResponse" in schemas_src, (
        "api/schemas.py StatsBaselineResponse sinifi yok."
    )
    assert "stats_baseline" in schemas_src and "risk_baseline" in schemas_src, (
        "StatsBaselineResponse alanlari eksik — (stats_baseline, risk_baseline) "
        "ikisi de olmalidir."
    )

    # 4) api/routes/settings.py → /settings/stats-baseline endpoint
    settings_src = (root / "api" / "routes" / "settings.py").read_text(encoding="utf-8")
    assert 'get_stats_baseline_endpoint' in settings_src or 'stats-baseline' in settings_src, (
        "api/routes/settings.py stats-baseline endpoint'i yok."
    )
    assert "/settings/stats-baseline" in settings_src, (
        "/settings/stats-baseline route'u eksik."
    )
    assert "get_stats_baseline()" in settings_src, (
        "settings.py endpoint get_stats_baseline() helper'ini cagirmiyor — "
        "fallback davranisi kirilmis."
    )

    # 5) api/routes/performance.py → helper kullanimi
    perf_py = (root / "api" / "routes" / "performance.py").read_text(encoding="utf-8")
    assert "get_stats_baseline" in perf_py, (
        "api/routes/performance.py get_stats_baseline helper'ini import "
        "etmiyor — hala sabit STATS_BASELINE'a bagli."
    )
    assert "baseline = get_stats_baseline()" in perf_py, (
        "performance.py get_stats_baseline() cagrisi yok — config tabaninda "
        "okumuyor."
    )

    # 6) api/routes/trades.py → /trades/stats helper fallback
    trades_py = (root / "api" / "routes" / "trades.py").read_text(encoding="utf-8")
    assert "get_stats_baseline" in trades_py, (
        "trades.py get_stats_baseline helper'ini import etmiyor."
    )
    assert "effective_since = since if since else get_stats_baseline()" in trades_py, (
        "trades.py /trades/stats since=None verildiginde helper fallback'i "
        "kullanmiyor — frontend aktif baseline'i override edemez."
    )

    # 7) services/api.js → getStatsBaseline helper
    api_js_src = (root / "desktop" / "src" / "services" / "api.js").read_text(encoding="utf-8")
    assert "export async function getStatsBaseline" in api_js_src, (
        "services/api.js getStatsBaseline helper'i export edilmiyor."
    )
    assert "/settings/stats-baseline" in api_js_src, (
        "services/api.js getStatsBaseline /settings/stats-baseline "
        "endpoint'ini cagirmiyor."
    )
    # STATS_BASELINE sabiti (fallback) korunmali — geri uyumluluk
    assert "export const STATS_BASELINE = '2026-02-01'" in api_js_src, (
        "services/api.js STATS_BASELINE fallback sabiti silinmis — geri "
        "uyumluluk bozulur (import eden bilesenler patlar)."
    )

    # 8) Performance.jsx → baselineInfo state + label
    perf_jsx_src = (
        root / "desktop" / "src" / "components" / "Performance.jsx"
    ).read_text(encoding="utf-8")
    assert "getStatsBaseline" in perf_jsx_src, (
        "Performance.jsx getStatsBaseline import'u eksik."
    )
    assert "baselineInfo" in perf_jsx_src, (
        "Performance.jsx baselineInfo state'i yok — baseline backend'den "
        "cekilmiyor."
    )
    assert "pf-baseline-label" in perf_jsx_src, (
        "Performance.jsx pf-baseline-label UI bloğu yok — kullanici aktif "
        "baseline'i gormuyor (A7 UI label gereksinimi)."
    )
    assert "baselineInfo.stats_baseline" in perf_jsx_src, (
        "Performance.jsx getTrades/getTradeStats baselineInfo state'ini "
        "kullanmiyor — hala sabit STATS_BASELINE'a bagli."
    )

    # 9) TradeHistory.jsx → baselineInfo state + label
    th_src = (
        root / "desktop" / "src" / "components" / "TradeHistory.jsx"
    ).read_text(encoding="utf-8")
    assert "getStatsBaseline" in th_src, (
        "TradeHistory.jsx getStatsBaseline import'u eksik."
    )
    assert "baselineInfo" in th_src, (
        "TradeHistory.jsx baselineInfo state'i yok."
    )
    assert "th-baseline-label" in th_src, (
        "TradeHistory.jsx th-baseline-label UI blogu yok."
    )
    assert "baselineInfo.stats_baseline" in th_src, (
        "TradeHistory.jsx fetchData baselineInfo state'ini kullanmiyor."
    )


# ── Flow 4k: TRADE_ERROR kategori eslemesi iki kaynakta senkron (A14 / B17) ──
def test_trade_error_category_mapping_consistent():
    """Widget Denetimi A14 (B17): TRADE_ERROR ve MANUAL_TRADE_ERROR event tipleri
    hem engine/error_tracker.py::ERROR_CATEGORIES hem de
    api/routes/error_dashboard.py::EVENT_TYPE_CATEGORY sozlukerinde 'emir'
    kategorisine eslenmelidir. Aksi halde canli hatalar 'sistem' veya 'diger'
    kategorisine dusup emir panelinde gorunmez."""
    # 1) engine ERROR_CATEGORIES kontrolu
    from engine.error_tracker import ERROR_CATEGORIES

    assert "TRADE_ERROR" in ERROR_CATEGORIES, (
        "engine/error_tracker.py::ERROR_CATEGORIES sozlugunde 'TRADE_ERROR' "
        "anahtari yok. ogul.py::_execute_signal send_order_failed durumunda "
        "TRADE_ERROR emit ediyor; kategori 'diger' default'una dusuyor."
    )
    assert ERROR_CATEGORIES["TRADE_ERROR"] == "emir", (
        f"engine/error_tracker.py::ERROR_CATEGORIES['TRADE_ERROR'] "
        f"beklenen 'emir', gelen {ERROR_CATEGORIES['TRADE_ERROR']!r}"
    )
    assert "MANUAL_TRADE_ERROR" in ERROR_CATEGORIES, (
        "engine/error_tracker.py::ERROR_CATEGORIES sozlugunde "
        "'MANUAL_TRADE_ERROR' anahtari yok. manuel_motor.py MT5 reject "
        "durumunda bu tipi emit ediyor."
    )
    assert ERROR_CATEGORIES["MANUAL_TRADE_ERROR"] == "emir", (
        f"engine/error_tracker.py::ERROR_CATEGORIES['MANUAL_TRADE_ERROR'] "
        f"beklenen 'emir', gelen {ERROR_CATEGORIES['MANUAL_TRADE_ERROR']!r}"
    )

    # 2) api EVENT_TYPE_CATEGORY kontrolu
    from api.routes.error_dashboard import EVENT_TYPE_CATEGORY

    assert "TRADE_ERROR" in EVENT_TYPE_CATEGORY, (
        "api/routes/error_dashboard.py::EVENT_TYPE_CATEGORY sozlugunde "
        "'TRADE_ERROR' anahtari yok. _categorize() default'u 'sistem' donduyor — "
        "Hata Takip panelinde TRADE_ERROR kayitlari 'sistem' kategorisine dusup "
        "emir kategori filtresinde gorunmuyor."
    )
    assert EVENT_TYPE_CATEGORY["TRADE_ERROR"] == "emir", (
        f"api/routes/error_dashboard.py::EVENT_TYPE_CATEGORY['TRADE_ERROR'] "
        f"beklenen 'emir', gelen {EVENT_TYPE_CATEGORY['TRADE_ERROR']!r}"
    )
    assert "MANUAL_TRADE_ERROR" in EVENT_TYPE_CATEGORY, (
        "api/routes/error_dashboard.py::EVENT_TYPE_CATEGORY sozlugunde "
        "'MANUAL_TRADE_ERROR' anahtari yok."
    )
    assert EVENT_TYPE_CATEGORY["MANUAL_TRADE_ERROR"] == "emir", (
        f"api/routes/error_dashboard.py::EVENT_TYPE_CATEGORY['MANUAL_TRADE_ERROR'] "
        f"beklenen 'emir', gelen {EVENT_TYPE_CATEGORY['MANUAL_TRADE_ERROR']!r}"
    )

    # 3) Parite kontrolu — iki sozlukte de TRADE_ERROR ayni kategoride olmali
    assert ERROR_CATEGORIES["TRADE_ERROR"] == EVENT_TYPE_CATEGORY["TRADE_ERROR"], (
        "ERROR_CATEGORIES ve EVENT_TYPE_CATEGORY 'TRADE_ERROR' icin farkli "
        "kategori donduruyor — backend query tutarsizligi olusur."
    )
    assert ERROR_CATEGORIES["MANUAL_TRADE_ERROR"] == EVENT_TYPE_CATEGORY["MANUAL_TRADE_ERROR"], (
        "ERROR_CATEGORIES ve EVENT_TYPE_CATEGORY 'MANUAL_TRADE_ERROR' icin "
        "farkli kategori donduruyor."
    )

    # 4) Engine tarafinda gerekten emit ediliyor mu (regresyon)
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[2]
    ogul_src = (repo_root / "engine" / "ogul.py").read_text(encoding="utf-8")
    assert 'event_type="TRADE_ERROR"' in ogul_src, (
        "engine/ogul.py TRADE_ERROR emit etmiyor — audit bulgusu gecersiz, "
        "test guncellenmeli."
    )
    manuel_src = (repo_root / "engine" / "manuel_motor.py").read_text(encoding="utf-8")
    assert 'event_type="MANUAL_TRADE_ERROR"' in manuel_src, (
        "engine/manuel_motor.py MANUAL_TRADE_ERROR emit etmiyor."
    )


# ── Flow 4l: Monitor Flow Diagram MT5 panel dinamik (B11) ───────
def test_monitor_mt5_panel_uses_dynamic_state():
    """Widget Denetimi B11: Monitor Flow Diagram ÜSTAT ModBox'inin 'MT5' detail
    satiri, gercek mt5Connected state'ine bagli olmali. Onceden 'BAĞLANTI YOK'
    string'i hardcode idi ve MT5 bagli iken bile YOK gorunuyordu."""
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[2]
    monitor_src = (repo_root / "desktop" / "src" / "components" / "Monitor.jsx").read_text(
        encoding="utf-8"
    )

    # 1) mt5Connected state'i hala mevcut
    assert "const mt5Connected" in monitor_src, (
        "Monitor.jsx mt5Connected state'i kaldirilmis — B11 dinamik bagla hedefi yok."
    )

    # 2) Hardcode 'BAĞLANTI YOK' kaldirilmis olmali (MT5 panel satirinda)
    # Diger kullanim alanlari olabilir diye spesifik pattern arariz:
    # ['MT5', 'BAĞLANTI YOK' ...] seklinde bir hardcode kalmamali.
    assert "['MT5', 'BAĞLANTI YOK'" not in monitor_src, (
        "Monitor.jsx 'MT5' detail satirinda 'BAĞLANTI YOK' hardcode hala mevcut — "
        "B11 fix geri alinmis veya yeni hardcode eklenmis."
    )

    # 3) Dinamik ifade mevcut — mt5Connected ile MT5 label'i ayni satirda
    # olmali. Cok kati regex yerine yakin gecinme kontrolu yeterli.
    mt5_label_idx = monitor_src.find("['MT5', mt5Connected")
    assert mt5_label_idx != -1, (
        "Monitor.jsx 'MT5' detail satirinda mt5Connected kullanimi yok — "
        "beklenen pattern: ['MT5', mt5Connected ? '✓ BAĞLI' : '✗ KOPUK', ...]"
    )


# ── Flow 4m: TopBar Günlük K/Z etiketi MT5 değil Snapshot (A10) ──
def test_topbar_daily_pnl_label_not_mt5():
    """Widget Denetimi A10 (B16): TopBar 'Günlük K/Z' metrik etiketinin veri kaynagi
    /api/account endpoint'i uzerinden db.get_latest_risk_snapshot() tablosundan
    geliyor, MT5 hesabindan degil. 'Günlük K/Z (MT5)' etiketi yaniltici. Etiket
    'Snapshot' olarak duzeltildi. Regression korumasi — hardcode geri gelmemeli."""
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[2]
    topbar_src = (repo_root / "desktop" / "src" / "components" / "TopBar.jsx").read_text(
        encoding="utf-8"
    )

    # 1) Yanlis etiket kaldirilmis olmali
    assert "Günlük K/Z (MT5)" not in topbar_src, (
        "TopBar.jsx 'Günlük K/Z (MT5)' etiketi hala mevcut — A10 fix geri alinmis. "
        "Veri risk_snapshots tablosundan geliyor, MT5 hesabindan degil; etiket yaniltici."
    )

    # 2) Dogru etiket mevcut
    assert "Günlük K/Z (Snapshot)" in topbar_src, (
        "TopBar.jsx 'Günlük K/Z (Snapshot)' etiketi yok — A10 duzeltmesi uygulanmamis."
    )

    # 3) Header yorumu da guncellenmis olmali
    assert "Günlük K/Z (MT5, 2sn)" not in topbar_src, (
        "TopBar.jsx dosya basi yorumunda 'Günlük K/Z (MT5, 2sn)' hala mevcut — "
        "yorum ile UI etiketi tutarsiz kalmis."
    )


# ── Flow 4n: SideNav kill_hold_ms config'den okunur (A19 / H5) ──
def test_sidenav_kill_hold_ms_from_config():
    """Widget Denetimi A19 (H5): SideNav kill-switch basili tutma suresi
    (KILL_HOLD_DURATION) config/default.json::ui.kill_hold_ms uzerinden backend
    endpoint /settings/ui-prefs araciligiyla frontend'e akiyor olmali. Hardcode
    geri eklenemez; backend zinciri kopmamali.

    6 asamali zincir kontrolu:
      (a) config/default.json::ui.kill_hold_ms var + pozitif int
      (b) api/schemas.py::UiPrefsResponse sinifi + kill_hold_ms alani mevcut
      (c) api/routes/settings.py::_read_ui_prefs_from_config + get_ui_prefs endpoint
      (d) services/api.js::getUiPrefs export var + '/settings/ui-prefs' endpoint
      (e) SideNav.jsx eski KILL_HOLD_DURATION = 2000 hardcode YOK + getUiPrefs import
      (f) SideNav.jsx killHoldMs state + useEffect fetch + setInterval/setTimeout
    """
    import json
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[2]

    # (a) config
    config_path = repo_root / "config" / "default.json"
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    assert "ui" in cfg, "config/default.json::ui bloku yok"
    assert "kill_hold_ms" in cfg["ui"], "ui.kill_hold_ms ayari yok — A19 fix kaldirilmis"
    val = cfg["ui"]["kill_hold_ms"]
    assert isinstance(val, int) and val >= 500 and val <= 10000, (
        f"ui.kill_hold_ms gecersiz deger: {val} (500-10000 araligi bekleniyor)"
    )

    # (b) schema
    from api.schemas import UiPrefsResponse
    assert hasattr(UiPrefsResponse, "model_fields"), "UiPrefsResponse Pydantic BaseModel degil"
    assert "kill_hold_ms" in UiPrefsResponse.model_fields, (
        "UiPrefsResponse.kill_hold_ms alani yok"
    )
    assert "source" in UiPrefsResponse.model_fields, (
        "UiPrefsResponse.source alani yok"
    )

    # (c) route
    settings_src = (repo_root / "api" / "routes" / "settings.py").read_text(encoding="utf-8")
    assert "_read_ui_prefs_from_config" in settings_src, (
        "settings.py::_read_ui_prefs_from_config helper fonksiyonu yok"
    )
    assert "/settings/ui-prefs" in settings_src, (
        "GET /settings/ui-prefs endpoint rotasi yok"
    )
    assert 'config.get("ui.kill_hold_ms"' in settings_src, (
        "_read_ui_prefs_from_config config.get('ui.kill_hold_ms') cagrisi yapmiyor"
    )

    # (d) services/api.js
    api_src = (repo_root / "desktop" / "src" / "services" / "api.js").read_text(
        encoding="utf-8"
    )
    assert "export async function getUiPrefs" in api_src, (
        "services/api.js getUiPrefs export'u yok"
    )
    assert "/settings/ui-prefs" in api_src, (
        "services/api.js '/settings/ui-prefs' endpoint cagrisi yok"
    )

    # (e) SideNav hardcode kaldirildi + import eklendi
    sidenav_src = (repo_root / "desktop" / "src" / "components" / "SideNav.jsx").read_text(
        encoding="utf-8"
    )
    assert "const KILL_HOLD_DURATION = 2000" not in sidenav_src, (
        "SideNav.jsx KILL_HOLD_DURATION = 2000 hardcode hala mevcut — A19 fix geri alinmis"
    )
    assert "getUiPrefs" in sidenav_src, (
        "SideNav.jsx getUiPrefs import/kullanimi yok"
    )

    # (f) state + effect + kullanim
    assert "killHoldMs" in sidenav_src, (
        "SideNav.jsx killHoldMs state'i yok"
    )
    assert "setKillHoldMs" in sidenav_src, (
        "SideNav.jsx setKillHoldMs setter'i yok"
    )
    assert "elapsed / killHoldMs" in sidenav_src, (
        "SideNav.jsx setInterval progress hesabi killHoldMs kullanmiyor — "
        "hala eski hardcode'a bagli olabilir"
    )


# ── Flow 4o: Dashboard max_open_positions config'den okunur (A18 / H2) ──
def test_dashboard_max_open_positions_from_config():
    """Widget Denetimi A18 (H2): Dashboard "Acik Pozisyonlar" rozeti eskiden
    "n / 5" seklinde hardcode'du. Artik config/default.json::risk.max_open_positions
    zinciri uzerinden /api/risk endpoint'i araciligiyla dinamik okunmalidir.
    Hardcode geri eklenemez; backend zinciri kopmamali.

    5 asamali zincir kontrolu:
      (a) config/default.json::risk.max_open_positions var + pozitif int
      (b) api/schemas.py::RiskResponse.max_open_positions alani mevcut
      (c) api/routes/risk.py resp.max_open_positions atamasi yapiyor
      (d) services/api.js::getRisk fallback'inde max_open_positions yer aliyor
      (e) Dashboard.jsx eski '} / 5' hardcode'u YOK + getRisk import + riskState
          state + riskState?.max_open_positions ifadesi mevcut
    """
    import json
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[2]

    # (a) config
    config_path = repo_root / "config" / "default.json"
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    assert "risk" in cfg, "config/default.json::risk bloku yok"
    assert "max_open_positions" in cfg["risk"], (
        "risk.max_open_positions ayari yok"
    )
    val = cfg["risk"]["max_open_positions"]
    assert isinstance(val, int) and val > 0, (
        f"risk.max_open_positions gecersiz deger: {val} (pozitif int bekleniyor)"
    )

    # (b) schema
    from api.schemas import RiskResponse
    assert hasattr(RiskResponse, "model_fields"), "RiskResponse Pydantic BaseModel degil"
    assert "max_open_positions" in RiskResponse.model_fields, (
        "RiskResponse.max_open_positions alani yok"
    )

    # (c) route
    risk_src = (repo_root / "api" / "routes" / "risk.py").read_text(encoding="utf-8")
    assert "resp.max_open_positions" in risk_src, (
        "api/routes/risk.py resp.max_open_positions atamasi yapmiyor"
    )

    # (d) services/api.js — getRisk fallback max_open_positions iceriyor mu?
    api_src = (repo_root / "desktop" / "src" / "services" / "api.js").read_text(
        encoding="utf-8"
    )
    assert "export async function getRisk" in api_src, (
        "services/api.js getRisk export'u yok"
    )
    # getRisk fonksiyonunda max_open_positions fallback degeri olmali
    import re as _re
    get_risk_match = _re.search(
        r"export async function getRisk\(\).*?^\}",
        api_src,
        _re.DOTALL | _re.MULTILINE,
    )
    assert get_risk_match, "getRisk fonksiyon govdesi bulunamadi"
    assert "max_open_positions" in get_risk_match.group(0), (
        "services/api.js getRisk fallback objesi max_open_positions icermiyor"
    )

    # (e) Dashboard.jsx — hardcode kaldirildi + import + state + kullanim
    dash_src = (repo_root / "desktop" / "src" / "components" / "Dashboard.jsx").read_text(
        encoding="utf-8"
    )
    # Eski hardcode pattern'i: "{(livePositions || []).length} / 5" — regresyon korumasi
    assert "|| []).length} / 5\n" not in dash_src, (
        "Dashboard.jsx '} / 5' hardcode pattern'i hala mevcut — A18 fix geri alinmis"
    )
    assert "getRisk" in dash_src, (
        "Dashboard.jsx getRisk import/kullanimi yok"
    )
    assert "riskState" in dash_src, (
        "Dashboard.jsx riskState state'i yok"
    )
    assert "setRiskState" in dash_src, (
        "Dashboard.jsx setRiskState setter'i yok"
    )
    assert "riskState?.max_open_positions" in dash_src, (
        "Dashboard.jsx riskState?.max_open_positions ifadesi yok — "
        "rozet hala eski hardcode'a bagli olabilir"
    )


# ── Flow 4p: Versiyon tek kaynak engine/__init__.py::VERSION (A5 / H1) ──
def test_version_single_source_of_truth():
    """Widget Denetimi A5 (H1): TopBar, Settings, LockScreen eskiden kendi
    hardcode "V6.0" / "VERSION = '6.0.0'" stringlerine sahipti. Artik tek kaynak
    engine/__init__.py::VERSION, /api/status endpoint'i uzerinden frontend'e akiyor.
    Hardcode geri eklenemez; backend zinciri kopmamali.

    5 asamali zincir kontrolu:
      (a) engine/__init__.py::VERSION var + semver formati (N.N.N)
      (b) api/routes/status.py engine VERSION import ediyor ve
          StatusResponse(version=ENGINE_VERSION, ...) cagirisi yapiyor
      (c) services/api.js getStatus fallback objesi 'version' alani iceriyor
      (d) TopBar.jsx eski <span>V6.0</span> hardcode'u YOK + status.version kullanimi
      (e) Settings.jsx eski `const VERSION = '6.0.0'` YOK + status?.version kullanimi
      (f) LockScreen.jsx eski <span>V6.0</span> hardcode'u YOK + appVersion state
          + getStatus import + mount useEffect fetch
    """
    import re as _re
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[2]

    # (a) engine/__init__.py::VERSION
    engine_init = (repo_root / "engine" / "__init__.py").read_text(encoding="utf-8")
    match = _re.search(r'VERSION\s*=\s*["\'](\d+\.\d+\.\d+)["\']', engine_init)
    assert match, (
        "engine/__init__.py::VERSION semver (N.N.N) formatinda degil ya da yok — "
        "A5 tek kaynak prensibi bozulmus"
    )
    engine_version = match.group(1)

    # (b) api/routes/status.py backend populate
    status_src = (repo_root / "api" / "routes" / "status.py").read_text(encoding="utf-8")
    assert "from engine import VERSION" in status_src, (
        "api/routes/status.py engine VERSION import etmiyor — "
        "status endpoint'i versiyon bilgisini saglamiyor"
    )
    assert "version=ENGINE_VERSION" in status_src, (
        "api/routes/status.py StatusResponse'a version=ENGINE_VERSION atamiyor"
    )

    # (c) services/api.js fallback
    api_src = (repo_root / "desktop" / "src" / "services" / "api.js").read_text(
        encoding="utf-8"
    )
    get_status_match = _re.search(
        r"export async function getStatus\(\).*?^\}",
        api_src,
        _re.DOTALL | _re.MULTILINE,
    )
    assert get_status_match, "services/api.js getStatus govdesi bulunamadi"
    assert "version:" in get_status_match.group(0), (
        "services/api.js getStatus fallback objesinde 'version' alani yok — "
        "backend erisilemezse LockScreen/TopBar/Settings versiyon gostermez"
    )

    # (d) TopBar.jsx hardcode kaldirildi + status.version kullanimi
    topbar_src = (repo_root / "desktop" / "src" / "components" / "TopBar.jsx").read_text(
        encoding="utf-8"
    )
    assert '<span className="version">V6.0</span>' not in topbar_src, (
        "TopBar.jsx hardcode '<span className=\"version\">V6.0</span>' hala mevcut — "
        "A5 fix geri alinmis"
    )
    assert "status.version" in topbar_src, (
        "TopBar.jsx status.version kullanimi yok — versiyon hala hardcode olabilir"
    )

    # (e) Settings.jsx hardcode kaldirildi + status?.version kullanimi
    settings_src = (repo_root / "desktop" / "src" / "components" / "Settings.jsx").read_text(
        encoding="utf-8"
    )
    assert "const VERSION = '6.0.0'" not in settings_src, (
        "Settings.jsx 'const VERSION = \\'6.0.0\\'' hardcode hala mevcut — "
        "A5 fix geri alinmis"
    )
    assert "status?.version" in settings_src, (
        "Settings.jsx status?.version kullanimi yok"
    )

    # (f) LockScreen.jsx hardcode kaldirildi + appVersion state + fetch
    lock_src = (repo_root / "desktop" / "src" / "components" / "LockScreen.jsx").read_text(
        encoding="utf-8"
    )
    assert '<span className="version">V6.0</span>' not in lock_src, (
        "LockScreen.jsx hardcode '<span className=\"version\">V6.0</span>' hala mevcut — "
        "A5 fix geri alinmis"
    )
    assert "appVersion" in lock_src, (
        "LockScreen.jsx appVersion state'i yok"
    )
    assert "getStatus" in lock_src, (
        "LockScreen.jsx getStatus import/kullanimi yok — "
        "versiyon backend'den okunamiyor"
    )


# ── Flow 4q: ManualTrade watchlist tek kaynak mt5_bridge.WATCHED_SYMBOLS (A-H3) ──
def test_manual_trade_watchlist_single_source():
    """Widget Denetimi A-H3: ManualTrade.jsx eskiden 15 VIOP kontratini
    kendi hardcode SYMBOLS dizisinde tutuyordu. Backend WATCHED_SYMBOLS
    listesi (engine/mt5_bridge.py) degistiginde dropdown sessizce
    senkronsuz kaliyordu. Artik canonical kaynak
    engine/mt5_bridge.py::WATCHED_SYMBOLS ve /api/settings/watchlist
    endpoint'i uzerinden ManualTrade dropdown'una akiyor.

    6 asamali zincir kontrolu:
      (a) engine/mt5_bridge.py::WATCHED_SYMBOLS var + list[str] + >=10 sembol
      (b) api/schemas.py::WatchlistResponse sinifi var + symbols alani
      (c) api/routes/settings.py _read_watchlist_symbols helper +
          /settings/watchlist route + WATCHED_SYMBOLS import
      (d) services/api.js::getWatchlistSymbols export var + /settings/watchlist
          endpoint cagrisi + fallback objesinde symbols alani
      (e) ManualTrade.jsx eski `const SYMBOLS = [` hardcode YASAK +
          getWatchlistSymbols import + watchlist state + setWatchlist setter
      (f) ManualTrade.jsx JSX'te dropdown watchlist state'inden map ediyor
          (SYMBOLS.map degil) + useEffect mount'ta fetch ediyor.
    """
    import re as _re
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[2]

    # (a) engine/mt5_bridge.py::WATCHED_SYMBOLS
    bridge_src = (repo_root / "engine" / "mt5_bridge.py").read_text(encoding="utf-8")
    assert "WATCHED_SYMBOLS: list[str] = [" in bridge_src, (
        "engine/mt5_bridge.py::WATCHED_SYMBOLS list[str] tanimi yok — "
        "A-H3 canonical kaynak kaldirilmis."
    )
    # Parantez icindeki semboller >=10 tane olmali (mevcut 15)
    match = _re.search(
        r'WATCHED_SYMBOLS: list\[str\] = \[(.*?)\]',
        bridge_src,
        _re.DOTALL,
    )
    assert match, "WATCHED_SYMBOLS liste govdesi parse edilemedi"
    body = match.group(1)
    symbol_count = len(_re.findall(r'"F_[A-Z]+"', body))
    assert symbol_count >= 10, (
        f"WATCHED_SYMBOLS sayisi {symbol_count} — en az 10 VIOP kontrati bekleniyor"
    )

    # (b) api/schemas.py::WatchlistResponse
    schemas_src = (repo_root / "api" / "schemas.py").read_text(encoding="utf-8")
    assert "class WatchlistResponse" in schemas_src, (
        "api/schemas.py::WatchlistResponse sinifi yok — "
        "/settings/watchlist endpoint'i response_model'siz kalir."
    )
    assert "symbols: list[str]" in schemas_src, (
        "WatchlistResponse.symbols: list[str] alani yok"
    )

    # (c) api/routes/settings.py helper + route + WATCHED_SYMBOLS import
    settings_src = (repo_root / "api" / "routes" / "settings.py").read_text(
        encoding="utf-8"
    )
    assert "def _read_watchlist_symbols" in settings_src, (
        "api/routes/settings.py _read_watchlist_symbols helper yok"
    )
    assert "from engine.mt5_bridge import WATCHED_SYMBOLS" in settings_src, (
        "_read_watchlist_symbols WATCHED_SYMBOLS import etmiyor — "
        "canonical kaynak bridge disindan okunuyor olabilir"
    )
    assert '@router.get("/settings/watchlist"' in settings_src, (
        "/settings/watchlist route kaydi yok"
    )
    assert "WatchlistResponse" in settings_src, (
        "settings.py WatchlistResponse import/kullanimi yok"
    )

    # (d) services/api.js::getWatchlistSymbols
    api_src = (repo_root / "desktop" / "src" / "services" / "api.js").read_text(
        encoding="utf-8"
    )
    assert "export async function getWatchlistSymbols" in api_src, (
        "services/api.js getWatchlistSymbols export yok"
    )
    get_wl_match = _re.search(
        r"export async function getWatchlistSymbols\(\).*?^\}",
        api_src,
        _re.DOTALL | _re.MULTILINE,
    )
    assert get_wl_match, "getWatchlistSymbols govdesi parse edilemedi"
    wl_body = get_wl_match.group(0)
    assert "/settings/watchlist" in wl_body, (
        "getWatchlistSymbols /settings/watchlist endpoint'ini cagirmiyor"
    )
    assert "symbols:" in wl_body, (
        "getWatchlistSymbols fallback objesinde 'symbols' alani yok — "
        "backend erisilemezse ManualTrade dropdown'u bos gorunur"
    )

    # (e) ManualTrade.jsx hardcode kaldirildi + state + import
    manual_src = (repo_root / "desktop" / "src" / "components" / "ManualTrade.jsx").read_text(
        encoding="utf-8"
    )
    assert "const SYMBOLS = [" not in manual_src, (
        "ManualTrade.jsx 'const SYMBOLS = [' hardcode hala mevcut — "
        "A-H3 fix geri alinmis (drift riski)"
    )
    assert "getWatchlistSymbols" in manual_src, (
        "ManualTrade.jsx getWatchlistSymbols import/kullanimi yok"
    )
    assert "const [watchlist, setWatchlist]" in manual_src, (
        "ManualTrade.jsx watchlist state'i yok"
    )

    # (f) JSX dropdown watchlist state'inden map + mount fetch
    assert "watchlist.map" in manual_src, (
        "ManualTrade.jsx dropdown watchlist.map kullanmiyor — "
        "muhtemelen hardcode SYMBOLS.map geri dondu"
    )
    assert "SYMBOLS.map" not in manual_src, (
        "ManualTrade.jsx hala SYMBOLS.map kullaniyor — state dropdown'a baglanmamis"
    )


# ── Flow 4r: ManualTrade lot input sinirlari config'den (H4) ──
def test_manual_trade_lot_limits_from_config():
    """Widget Denetimi H4: ManualTrade.jsx lot input eskiden hardcoded
    `min=1 max=10 step=1` kullaniyordu. Canonical kaynak
    `config/default.json.engine.max_lot_per_contract` (1.0) ile uyumsuzdu —
    kullanici 10 girebilirdi ama manuel_motor silent truncation ile 1.0'a
    kirpiyordu. Artik /api/settings/trading-limits endpoint'i uzerinden
    UI config'e senkronize olur. Sessiz kirpma kapisi kapandi.

    6 asamali zincir kontrolu:
      (a) config/default.json.engine.max_lot_per_contract >0 sayi
      (b) api/schemas.py::TradingLimitsResponse sinifi + 3 alan (lot_min,
          lot_max, lot_step)
      (c) api/routes/settings.py _read_trading_limits helper +
          /settings/trading-limits route + max_lot_per_contract okumasi +
          TradingLimitsResponse kullanimi
      (d) services/api.js::getTradingLimits export + /settings/trading-limits
          cagrisi + fallback objesinde lot_min/lot_max/lot_step alanlari
      (e) ManualTrade.jsx eski `min={1}` ve `max={10}` JSX literal YASAK +
          getTradingLimits import + lotLimits state + lot input lotLimits.*
          ile bagli
      (f) ManualTrade.jsx useEffect mount'ta getTradingLimits cagiriyor +
          gelen degeri setLotLimits ile state'e yaziyor
    """
    import json as _json
    import re as _re
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[2]

    # (a) config/default.json.engine.max_lot_per_contract
    cfg_path = repo_root / "config" / "default.json"
    cfg = _json.loads(cfg_path.read_text(encoding="utf-8"))
    engine_cfg = cfg.get("engine", {})
    assert "max_lot_per_contract" in engine_cfg, (
        "config.engine.max_lot_per_contract anahtari yok — "
        "H4 canonical kaynak kaldirilmis"
    )
    max_lot = engine_cfg["max_lot_per_contract"]
    assert isinstance(max_lot, (int, float)) and max_lot > 0, (
        f"max_lot_per_contract tipi/degeri gecersiz: {max_lot!r}"
    )

    # (b) api/schemas.py::TradingLimitsResponse
    schemas_src = (repo_root / "api" / "schemas.py").read_text(encoding="utf-8")
    assert "class TradingLimitsResponse" in schemas_src, (
        "api/schemas.py::TradingLimitsResponse sinifi yok — "
        "/settings/trading-limits response_model'siz kalir"
    )
    for field in ("lot_min:", "lot_max:", "lot_step:"):
        assert field in schemas_src, (
            f"TradingLimitsResponse {field} alani yok — H4 yaniti eksik"
        )

    # (c) api/routes/settings.py helper + route + config okuma
    settings_src = (repo_root / "api" / "routes" / "settings.py").read_text(
        encoding="utf-8"
    )
    assert "def _read_trading_limits" in settings_src, (
        "api/routes/settings.py _read_trading_limits helper yok"
    )
    assert 'engine.max_lot_per_contract' in settings_src, (
        "_read_trading_limits config.engine.max_lot_per_contract okumuyor — "
        "canonical kaynak atlanmis"
    )
    assert '@router.get("/settings/trading-limits"' in settings_src, (
        "/settings/trading-limits route kaydi yok"
    )
    assert "TradingLimitsResponse" in settings_src, (
        "settings.py TradingLimitsResponse import/kullanimi yok"
    )

    # (d) services/api.js::getTradingLimits
    api_src = (repo_root / "desktop" / "src" / "services" / "api.js").read_text(
        encoding="utf-8"
    )
    assert "export async function getTradingLimits" in api_src, (
        "services/api.js getTradingLimits export yok"
    )
    get_tl_match = _re.search(
        r"export async function getTradingLimits\(\).*?^\}",
        api_src,
        _re.DOTALL | _re.MULTILINE,
    )
    assert get_tl_match, "getTradingLimits govdesi parse edilemedi"
    tl_body = get_tl_match.group(0)
    assert "/settings/trading-limits" in tl_body, (
        "getTradingLimits /settings/trading-limits endpoint'ini cagirmiyor"
    )
    for field in ("lot_min", "lot_max", "lot_step"):
        assert field in tl_body, (
            f"getTradingLimits fallback objesinde '{field}' alani yok — "
            "backend erisilemezse ManualTrade lot input sinirsiz kalir"
        )

    # (e) ManualTrade.jsx hardcode kaldirildi + state + input binding
    manual_src = (repo_root / "desktop" / "src" / "components" / "ManualTrade.jsx").read_text(
        encoding="utf-8"
    )
    # Eski literaller kesinlikle yok (regex ile space toleransli)
    assert not _re.search(r"min=\{\s*1\s*\}", manual_src), (
        "ManualTrade.jsx 'min={1}' hardcode hala mevcut — H4 fix geri alinmis"
    )
    assert not _re.search(r"max=\{\s*10\s*\}", manual_src), (
        "ManualTrade.jsx 'max={10}' hardcode hala mevcut — H4 fix geri alinmis"
    )
    assert "getTradingLimits" in manual_src, (
        "ManualTrade.jsx getTradingLimits import/kullanimi yok"
    )
    assert "const [lotLimits, setLotLimits]" in manual_src, (
        "ManualTrade.jsx lotLimits state'i yok"
    )
    # Lot input min/max/step lotLimits.* ile bagli olmali
    assert "min={lotLimits.lot_min}" in manual_src, (
        "ManualTrade.jsx lot input min={lotLimits.lot_min} bagli degil"
    )
    assert "max={lotLimits.lot_max}" in manual_src, (
        "ManualTrade.jsx lot input max={lotLimits.lot_max} bagli degil"
    )
    assert "step={lotLimits.lot_step}" in manual_src, (
        "ManualTrade.jsx lot input step={lotLimits.lot_step} bagli degil"
    )

    # (f) useEffect mount'ta fetch + setLotLimits
    assert "setLotLimits" in manual_src, (
        "ManualTrade.jsx setLotLimits setter cagrisi yok — "
        "state hic guncellenmiyor"
    )


# ── Flow 4s: Monitor L1/L2/L3 yaklasik gostergesi (H15) ──
def test_monitor_kill_switch_levels_are_disclosed_as_approximate():
    """
    Widget Denetimi H15 — BABA kill-switch L1/L2/L3 tetikleyicileri
    event-driven (anomali, gunluk kayip, hard drawdown vb). Monitor.jsx
    bu seviyeleri limDaily * (0.5, 0.75, 1.0) illustratif carpanlariyla
    gosterir. Kullanici gercek esik sanmasin diye UI'de "~YAKLASIK"
    disclosure badge + her ksLevel karti icinde "~%pct" prefix + tooltip
    zorunludur.

    Bu test Monitor.jsx'te:
      (a) KS_LEVEL_PCT_FRACTIONS sabiti dokumante edilmis
      (b) Render header'inda "~YAKLASIK" string'i
      (c) Her ksLevel kartinda "~%{pct}" prefix
      (d) Tooltip (title) icinde "YAKLASIK gorselestirme" / "gercek esik degil"
          benzeri aciklama
    oldugunu dogrular.
    """
    root = Path(__file__).resolve().parent.parent.parent
    monitor_path = root / "desktop" / "src" / "components" / "Monitor.jsx"
    assert monitor_path.exists(), f"Monitor.jsx bulunamadi: {monitor_path}"
    monitor_src = monitor_path.read_text(encoding="utf-8")

    # (a) KS_LEVEL_PCT_FRACTIONS sabiti var
    assert "KS_LEVEL_PCT_FRACTIONS" in monitor_src, (
        "Monitor.jsx KS_LEVEL_PCT_FRACTIONS dokumante sabiti yok — "
        "0.5/0.75/1.0 carpanlari hala inline hardcode (H15)."
    )
    # Carpanlarin sabit uzerinden okundugunu dogrula
    assert "KS_LEVEL_PCT_FRACTIONS.L1" in monitor_src, (
        "ksLevels L1 yuzdesi KS_LEVEL_PCT_FRACTIONS.L1 uzerinden okunmuyor"
    )
    assert "KS_LEVEL_PCT_FRACTIONS.L2" in monitor_src, (
        "ksLevels L2 yuzdesi KS_LEVEL_PCT_FRACTIONS.L2 uzerinden okunmuyor"
    )
    assert "KS_LEVEL_PCT_FRACTIONS.L3" in monitor_src, (
        "ksLevels L3 yuzdesi KS_LEVEL_PCT_FRACTIONS.L3 uzerinden okunmuyor"
    )

    # (b) Render header'inda "~YAKLASIK" disclosure badge var (Turkce I)
    assert "~YAKLAŞIK" in monitor_src, (
        "Monitor.jsx RISK & KILL-SWITCH header'inda '~YAKLASIK' disclosure "
        "badge yok — kullanici gercek esik saniyor (H15)."
    )

    # (c) ksLevel kartinda "~%{pct}" prefix
    assert "~%{pct}" in monitor_src, (
        "Monitor.jsx ksLevel pct render'inda '~%{pct}' prefix yok — "
        "yuzdelerin yaklasik oldugu kullaniciya belirtilmemis (H15)."
    )

    # (d) Tooltip icinde gercek esik olmadigi aciklamasi
    #     Cesitli yazim: "gercek esik degil" / "gercek esigi degil" / "DEGIL"
    assert "gerçek eşik" in monitor_src or "gerçek eşiği" in monitor_src, (
        "Monitor.jsx ksLevel tooltip'inde 'gercek esik(i) degil' aciklamasi "
        "yok — yaklasik notu tam anlamli degil (H15)."
    )


# ── Flow 4t: RiskResponse dead field temizligi (H17) ──
def test_risk_response_has_no_dead_graduated_lot_mult():
    """
    Widget Denetimi H17 — `RiskResponse.graduated_lot_mult` v5.1'de placeholder
    olarak eklenmis bir alandi; hicbir uretici (api/routes/risk.py) populate
    etmiyor, hicbir frontend tuketicisi yok (RiskManagement.jsx sadece
    `lot_multiplier` okur). BABA graduated lot mantigi (0.75, 0.50, 0.25)
    zaten `verdict.lot_multiplier` -> `resp.lot_multiplier` uzerinden UI'ya
    akiyor ve "Lot Carpani" kartinda gorunur.

    Bu test:
      (a) api/schemas.py::RiskResponse icinde `graduated_lot_mult` alan TANIMI
          YOK (eski placeholder geri eklenmesin)
      (b) RiskResponse icinde `lot_multiplier` alani hala mevcut (canli yol)
      (c) api/routes/risk.py icinde `resp.lot_multiplier =` atamasi mevcut
          (verdict'ten populate ediliyor)
      (d) desktop/src/components/RiskManagement.jsx icinde `risk.lot_multiplier`
          goruntulemesi mevcut ("Lot Carpani" karti)
      (e) RiskManagement.jsx icinde `graduated_lot_mult` dead field'ina
          referans YOK (olasi eski placeholder UI kodu temizlenmis)
    """
    root = Path(__file__).resolve().parent.parent.parent

    # (a) Schema dead field yok
    schemas_path = root / "api" / "schemas.py"
    schemas_src = schemas_path.read_text(encoding="utf-8")
    # "graduated_lot_mult" alan tanimi var mi? (dokumantasyon yorumu disinda)
    import re as _re_h17
    # Alan tanimi tipi: "    graduated_lot_mult: float = ..."
    field_def_re = _re_h17.compile(r"^\s*graduated_lot_mult\s*:\s*", _re_h17.MULTILINE)
    assert not field_def_re.search(schemas_src), (
        "api/schemas.py::RiskResponse hala 'graduated_lot_mult' dead field'ini "
        "tasiyor. Bu alan hicbir yer tarafindan populate edilmiyor ve hicbir "
        "tuketicisi yok. Graduated lot mantigi 'lot_multiplier' uzerinden "
        "akiyor (Widget Denetimi H17)."
    )

    # (b) lot_multiplier alani hala var (canli yol)
    assert "lot_multiplier: float" in schemas_src, (
        "api/schemas.py::RiskResponse 'lot_multiplier' alani kaybolmus — "
        "graduated lot degerini UI'ya tasiyan tek canli alan bu."
    )

    # (c) risk.py route'u lot_multiplier'i verdict'ten populate ediyor
    risk_route_path = root / "api" / "routes" / "risk.py"
    risk_route_src = risk_route_path.read_text(encoding="utf-8")
    assert "resp.lot_multiplier = verdict.lot_multiplier" in risk_route_src, (
        "api/routes/risk.py icinde 'resp.lot_multiplier = verdict.lot_multiplier' "
        "atamasi yok. Graduated lot degeri UI'ya akmiyor."
    )

    # (d) RiskManagement.jsx lot_multiplier goruntulemesi
    rm_path = root / "desktop" / "src" / "components" / "RiskManagement.jsx"
    rm_src = rm_path.read_text(encoding="utf-8")
    assert "risk.lot_multiplier" in rm_src, (
        "RiskManagement.jsx 'risk.lot_multiplier' goruntulemesi yok — "
        "kullanici graduated lot degerini goremiyor."
    )
    assert "Lot Çarpanı" in rm_src, (
        "RiskManagement.jsx 'Lot Carpani' karti kaybolmus — "
        "graduated lot UI label'i eksik."
    )

    # (e) graduated_lot_mult dead field RiskManagement.jsx'te referans alinmiyor
    assert "graduated_lot_mult" not in rm_src, (
        "RiskManagement.jsx 'graduated_lot_mult' dead field'ini okuyor — "
        "bu alan artik schema'da yok, null/undefined doner."
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
