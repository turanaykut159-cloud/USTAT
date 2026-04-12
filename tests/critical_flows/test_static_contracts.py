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


# ── Flow 4u: NABIZ thresholds backend canonical (H8 + H9) ──
def test_nabiz_thresholds_are_backend_driven():
    """
    Widget Denetimi H8 + H9 — NABIZ sayfasi tablo satir esikleri,
    ozet kart esikleri ve log dosyasi display limiti eskiden
    `desktop/src/components/Nabiz.jsx` icinde hardcoded sabitlerdi
    (TABLE_THRESHOLDS dict, inline 500/1000/2000/80/90 magic sayilari,
    `files.slice(0, 15)` kirpmasi). Artik canonical kaynak
    `api/routes/nabiz.py::NABIZ_TABLE_ROW_THRESHOLDS` + `NABIZ_SUMMARY_THRESHOLDS`
    + `NABIZ_LOG_FILES_DISPLAY_LIMIT` modul sabitleridir; `/api/nabiz`
    response'unda `thresholds` alani uzerinden UI'ya akar. Frontend
    fallback olarak DEFAULT_* kopyalarini tutar (backend erisilemezse sayfa
    bos gorunmesin).

    Bu test:
      (a) api/routes/nabiz.py canonical sabitleri + `_build_thresholds_info`
          helper + response'ta "thresholds" alani mevcut
      (b) api/routes/nabiz.py icinde NABIZ_TABLE_ROW_THRESHOLDS en az 10 tablo
          icerir (regression: birkac tablo silinirse test kirilir)
      (c) Nabiz.jsx eski `const TABLE_THRESHOLDS` hardcode tanimi YASAK
          (DEFAULT_TABLE_THRESHOLDS fallback olarak izinli, ama canli tuketim
          `tableRowThresholds` prop'u uzerinden olmali)
      (d) Nabiz.jsx `data?.thresholds` tuketimi + `tableRowThresholds`
          prop zinciri mevcut
      (e) Nabiz.jsx inline `> 1000 ?`, `> 500 ?`, `> 2000 ?`, `> 90 ?`, `> 80 ?`
          SummaryCard karar pattern'leri YASAK — `pickSummaryStatus` helper +
          `summaryThresholds` uzerinden akmali (regression koruma)
      (f) Nabiz.jsx `files.slice(0, 15)` hardcode kirpma YASAK —
          `files.slice(0, displayLimit)` kullanimi mevcut
    """
    root = Path(__file__).resolve().parent.parent.parent
    import re as _re_h8

    # (a) Backend canonical + helper + response alani
    nabiz_route_path = root / "api" / "routes" / "nabiz.py"
    nabiz_route_src = nabiz_route_path.read_text(encoding="utf-8")
    assert "NABIZ_TABLE_ROW_THRESHOLDS" in nabiz_route_src, (
        "api/routes/nabiz.py NABIZ_TABLE_ROW_THRESHOLDS canonical sabiti yok — "
        "H8 geri ciktiginda frontend hardcode tekrar eder."
    )
    assert "NABIZ_SUMMARY_THRESHOLDS" in nabiz_route_src, (
        "api/routes/nabiz.py NABIZ_SUMMARY_THRESHOLDS canonical sabiti yok."
    )
    assert "NABIZ_LOG_FILES_DISPLAY_LIMIT" in nabiz_route_src, (
        "api/routes/nabiz.py NABIZ_LOG_FILES_DISPLAY_LIMIT canonical sabiti yok."
    )
    assert "def _build_thresholds_info" in nabiz_route_src, (
        "api/routes/nabiz.py _build_thresholds_info helper yok — "
        "thresholds response alanina nasil aktariliyor?"
    )
    assert '"thresholds": _build_thresholds_info()' in nabiz_route_src, (
        "api/routes/nabiz.py /nabiz response'unda 'thresholds' alani yok — "
        "frontend DEFAULT_* fallback'lerine dusecek."
    )

    # (b) Canonical dictte en az 10 tablo
    # Kayit: NABIZ_TABLE_ROW_THRESHOLDS bloguna bakip key sayisini yaklasik say
    # (Pythonic parse yerine regex — statik sozlesme testi basit kalmali)
    dict_match = _re_h8.search(
        r"NABIZ_TABLE_ROW_THRESHOLDS\s*:\s*dict.*?=\s*\{(.*?)\n\}",
        nabiz_route_src,
        _re_h8.DOTALL,
    )
    assert dict_match is not None, (
        "NABIZ_TABLE_ROW_THRESHOLDS dict tanimi parse edilemedi — "
        "format degistiyse bu testi guncelle."
    )
    dict_body = dict_match.group(1)
    key_count = len(_re_h8.findall(r'^\s*"[a-z_]+"\s*:', dict_body, _re_h8.MULTILINE))
    assert key_count >= 10, (
        f"NABIZ_TABLE_ROW_THRESHOLDS sadece {key_count} tablo iceriyor. "
        "Kritik tablolarin cogu temsil edilmeli (bars, trades, risk_snapshots, "
        "events, vb.)."
    )

    # (c-f) Frontend kontrolleri
    nabiz_jsx_path = root / "desktop" / "src" / "components" / "Nabiz.jsx"
    nabiz_jsx_src = nabiz_jsx_path.read_text(encoding="utf-8")

    # (c) Eski "const TABLE_THRESHOLDS = {" hardcode yok (DEFAULT_ prefix'li izinli)
    assert "const TABLE_THRESHOLDS" not in nabiz_jsx_src, (
        "Nabiz.jsx eski 'const TABLE_THRESHOLDS = {' hardcode geri eklenmis — "
        "canonical kaynak backend olmali, frontend sadece DEFAULT_TABLE_THRESHOLDS "
        "fallback'ini tutabilir. (H8 regression)"
    )
    assert "DEFAULT_TABLE_THRESHOLDS" in nabiz_jsx_src, (
        "Nabiz.jsx DEFAULT_TABLE_THRESHOLDS fallback sabiti yok — backend "
        "erisilemezse sayfa renk kodlamasi calismaz."
    )

    # (d) data?.thresholds + tableRowThresholds tuketimi
    assert "data?.thresholds" in nabiz_jsx_src, (
        "Nabiz.jsx 'data?.thresholds' tuketimi yok — backend'den akan esikler "
        "okunmuyor."
    )
    assert "tableRowThresholds" in nabiz_jsx_src, (
        "Nabiz.jsx tableRowThresholds prop/variable'i yok — TableSizesPanel "
        "hala hardcode'a dusuyor olabilir."
    )
    assert "getRowColor(name, count, tableRowThresholds)" in nabiz_jsx_src, (
        "Nabiz.jsx getRowColor cagrisi tableRowThresholds argumanini gecmiyor — "
        "hardcode kullanilmaya devam ediyor."
    )

    # (e) Inline > 1000 / > 500 / > 2000 / > 90 / > 80 SummaryCard karar pattern'leri YASAK
    inline_magic_patterns = [
        r"file_size_mb\s*>\s*1000",
        r"total_size_mb\s*>\s*2000",
        r"usage_pct\s*>\s*90",
    ]
    for pat in inline_magic_patterns:
        assert not _re_h8.search(pat, nabiz_jsx_src), (
            f"Nabiz.jsx'te inline magic pattern geri eklenmis: {pat}. "
            "SummaryCard karari pickSummaryStatus + summaryThresholds uzerinden "
            "akmali (H8 regression)."
        )
    assert "pickSummaryStatus" in nabiz_jsx_src, (
        "Nabiz.jsx pickSummaryStatus helper yok — SummaryCard karari "
        "hardcode'a geri dusmus olabilir."
    )
    assert "summaryThresholds" in nabiz_jsx_src, (
        "Nabiz.jsx summaryThresholds variable'i yok — backend esik "
        "degerleri okunmuyor."
    )

    # (f) files.slice(0, 15) hardcode YASAK — displayLimit prop'u kullanilmali
    assert "files.slice(0, 15)" not in nabiz_jsx_src, (
        "Nabiz.jsx hala 'files.slice(0, 15)' hardcode kirpmasi yapiyor — "
        "backend NABIZ_LOG_FILES_DISPLAY_LIMIT uzerinden akmali. (H9 regression)"
    )
    assert "files.slice(0, displayLimit)" in nabiz_jsx_src, (
        "Nabiz.jsx LogFilesPanel 'files.slice(0, displayLimit)' kullanmiyor — "
        "log listesi kirpmasi backend'den akmiyor."
    )


# ── Flow 4v: Settings acik tema disabled (Widget Denetimi H12) ───
def test_settings_light_theme_disabled():
    """Settings.jsx icinde acik tema UI'den secilemez olmali.

    H12: acik tema CSS degiskenleri hazir ama tum bilesenlerde
    dogrulanmadigi icin Settings sayfasinda 'Koyu Tema aktif' yazip
    acik temayi sessizce uyguluyordu. Regression koruma:
        (a) 'simdilik sadece koyu tema' yaniltici yorumu kaldirilmis
        (b) 'Widget Denetimi H12' marker mevcut
        (c) applyTheme guard: 'dark' disinda cagrilar reddedilir
        (d) Acik tema karti disabled class + title tooltip + aria-disabled
        (e) Regresyon: onClick={() => applyTheme('light')} YOK
    """
    settings_jsx = ROOT / "desktop" / "src" / "components" / "Settings.jsx"
    assert settings_jsx.exists(), "desktop/src/components/Settings.jsx yok."
    src = settings_jsx.read_text(encoding="utf-8")

    # (a) Yaniltici yorum kaldirilmis olmali
    assert "şimdilik sadece koyu tema" not in src, (
        "Settings.jsx hala 'şimdilik sadece koyu tema' yorumunu tasiyor — "
        "H12 temizligi tamam degil."
    )

    # (b) H12 marker mevcut
    assert "Widget Denetimi H12" in src, (
        "Settings.jsx icinde 'Widget Denetimi H12' marker yok — canonical "
        "referans kaybolmus."
    )

    # (c) applyTheme guard mevcut
    assert "if (newTheme !== 'dark')" in src, (
        "Settings.jsx applyTheme fonksiyonu 'dark' disindaki temalari "
        "reddetmiyor — H12 guard kaybolmus."
    )

    # (d) Acik tema karti disabled + title + aria-disabled tasimali
    assert 'className="st-theme-card disabled"' in src, (
        "Settings.jsx Acik Tema karti 'disabled' class tasimiyor — "
        "H12 regression."
    )
    assert 'aria-disabled="true"' in src, (
        "Settings.jsx Acik Tema karti aria-disabled=\"true\" tasimiyor — "
        "erisilebilirlik regression."
    )
    # Title tooltip icinde H12 atfi bulunmali
    title_match = re.search(
        r'title="[^"]*Widget Denetimi H12[^"]*"', src
    )
    assert title_match, (
        "Settings.jsx Acik Tema karti title tooltip'i 'Widget Denetimi H12' "
        "atfini icermiyor."
    )

    # (e) Regresyon: onClick applyTheme('light') cagrisi OLMAMALI
    assert "applyTheme('light')" not in src, (
        "Settings.jsx hala applyTheme('light') cagirmaya calisiyor — "
        "H12 disable regression."
    )


# ── Flow 4w: TopBar regime dead field removal (Widget Denetimi H18) ─
def test_topbar_no_dead_regime_initial_state():
    """TopBar.jsx initial state'inde `regime` alani bulunmamali.

    H18: TopBar.jsx render'inda `status.regime` hicbir yerde okunmuyor —
    initial state'te `regime: 'TREND'` yaniltici bir default idi. Dead
    field removal sonrasi regression koruma:
        (a) `regime: 'TREND'` initial state literal'i YASAK
        (b) `regime:` initial state alan tanimi YASAK (baska default ile
            geri gelmesini de engelle)
        (c) `status.regime` consumption YASAK (ileride render'da
            kullanilacaksa ayri bir state olarak eklenmeli)
        (d) `Widget Denetimi H18` marker mevcut (canonical atif)
    """
    topbar_jsx = ROOT / "desktop" / "src" / "components" / "TopBar.jsx"
    assert topbar_jsx.exists(), "desktop/src/components/TopBar.jsx yok."
    src = topbar_jsx.read_text(encoding="utf-8")

    # (a) Eski literal YASAK
    assert "regime: 'TREND'" not in src, (
        "TopBar.jsx initial state'inde 'regime: TREND' yaniltici default "
        "geri gelmis — H18 dead field regression."
    )

    # (b) useState icinde `regime:` alan tanimi YASAK
    # useState blok yakalayici (parantez ici bolgeyi hedefle)
    usestate_block = re.search(
        r"useState\s*\(\s*\{([^}]*)\}", src, re.DOTALL
    )
    assert usestate_block, (
        "TopBar.jsx icinde useState({...}) initial state blogu bulunamadi — "
        "dosya yapisi degismis olabilir."
    )
    initial_state = usestate_block.group(1)
    assert not re.search(r"\bregime\s*:", initial_state), (
        "TopBar.jsx useState initial state'inde `regime:` alani var — "
        "dead field H18 regression, alan tamamen kaldirilmali."
    )

    # (c) status.regime consumption YASAK
    assert "status.regime" not in src, (
        "TopBar.jsx icinde `status.regime` consumption var — H18 sonrasi "
        "bu alan kaldirildi, ileride gerekirse ayri bir state eklenmeli."
    )

    # (d) H18 marker mevcut
    assert "Widget Denetimi H18" in src, (
        "TopBar.jsx icinde 'Widget Denetimi H18' marker yok — canonical "
        "atif kaybolmus, refactor sirasinda dead field kaldirildigi "
        "bilgisi silinmis olabilir."
    )


# ── Flow 4x: Settings dummy Sifre FieldRow kaldirma (Widget Denetimi H11) ─
def test_settings_no_dummy_password_fieldrow():
    """Settings.jsx icinde dummy sabit sifre FieldRow bulunmamali.

    H11: Eski Settings'te `<FieldRow label="Sifre" value="........" />`
    satiri vardi — /api/account MT5 sifresini guvenlik nedeniyle hic
    dondurmez (Windows credential store'da keyring ile tutulur), bu
    alan hicbir backend verisine bagli degildi, sabit 8 bullet
    gosteriyordu. Kullaniciya "uygulama sifreyi bilip maskeliyor"
    yanlis mesaji veriyordu. Dead decorative field. Regression koruma:
        (a) 8 bullet sabit ("\u2022" * 8) literal'i Settings.jsx'te
            YASAK — dummy sifre satirinin geri gelmesini engeller.
        (b) Settings.jsx icinde `label="Sifre"` (tam eslesen) literal
            icin HERHANGI bir `value=` atamasi YASAK — boylece
            ileride biri basit bir kaynak gozden kacirip dummy'yi
            tekrar eklerse test yakalayabilir.
        (c) `Widget Denetimi H11` marker yorumu mevcut (canonical atif).
    """
    settings_jsx = ROOT / "desktop" / "src" / "components" / "Settings.jsx"
    assert settings_jsx.exists(), "desktop/src/components/Settings.jsx yok."
    src = settings_jsx.read_text(encoding="utf-8")

    # (a) 8 bullet sabit literal YASAK
    bullet_literal = "\u2022" * 8
    assert bullet_literal not in src, (
        "Settings.jsx icinde 8 karakterlik sabit bullet stringi "
        "('\u2022' * 8) bulundu — dummy 'Sifre' FieldRow geri gelmis "
        "olabilir. /api/account sifreyi hic dondurmez, bu tamamen "
        "dekoratif olu UI idi, Widget Denetimi H11 ile kaldirildi."
    )

    # (b) Sifre label'i ile FieldRow-style value= yasagi
    # Eski kalip: <FieldRow label="Sifre" value="..." />
    # Turkce i karakteri hassasiyeti: hem "Sifre" (S-i-f-r-e) hem
    # "\u015eifre" (Ş-ifre) varyantlarini kontrol et.
    for variant in ("Şifre", "Sifre"):
        pattern = rf'label="{variant}"\s*value='
        match = re.search(pattern, src)
        assert match is None, (
            f"Settings.jsx icinde `label=\"{variant}\"` ile `value=` "
            f"atamasi bulundu — bu dummy sifre FieldRow'u yeniden "
            f"getirmeye cok benziyor. Widget Denetimi H11: sifre UI'de "
            f"GOSTERILMEZ; MT5 sifresi Windows credential store'dadir, "
            f"renderer'a guvenlik gereği aktarilmaz."
        )

    # (c) H11 marker
    assert "Widget Denetimi H11" in src, (
        "Settings.jsx icinde 'Widget Denetimi H11' marker yok — canonical "
        "atif kaybolmus, refactor sirasinda dummy sifre satirinin neden "
        "kaldirildigi bilgisi silinmis olabilir."
    )


# ── Flow 4y: Win rate breakeven esiği canonical kaynak (Widget Denetimi H13) ─
def test_win_rate_breakeven_canonical_source():
    """Win rate 50 esiği formatters.js disinda hardcode olmamali.

    H13: UstatBrain kontrat profilleri, Performance Long/Short paneli,
    Performance ozet kartlar, TradeHistory filtered stats, Dashboard hero
    stat card ve HybridTrade perf paneli olmak uzere 6 ayri yerde ayni
    magic number `50` win rate esiği olarak hardcode ediliyordu. Artik
    `desktop/src/utils/formatters.js` icindeki WIN_RATE_BREAKEVEN_PCT
    sabiti + winRateClass/winRateColor helper'lari TEK canonical kaynak.
    Regression koruma:
        (a) formatters.js icinde `WIN_RATE_BREAKEVEN_PCT` sabiti
            tanimlanmis olmali.
        (b) formatters.js icinde winRateClass ve winRateColor export
            edilmis olmali.
        (c) formatters.js DISINDA `win_rate >= 50` ve `winRate >= 50`
            hardcode literal'leri YASAK — herhangi bir bilesen yeni bir
            win rate renklendirmesi eklerse canonical helper'lari
            kullanmasi zorunlu.
        (d) `Widget Denetimi H13` marker yorumu formatters.js'te mevcut.
    """
    fmt_js = ROOT / "desktop" / "src" / "utils" / "formatters.js"
    assert fmt_js.exists(), "desktop/src/utils/formatters.js yok."
    fmt_src = fmt_js.read_text(encoding="utf-8")

    # (a) Canonical sabit mevcut
    assert "WIN_RATE_BREAKEVEN_PCT" in fmt_src, (
        "formatters.js icinde WIN_RATE_BREAKEVEN_PCT sabiti yok — "
        "Widget Denetimi H13 canonical kaynak kaldirilmis olabilir."
    )

    # (b) Helper'lar export edilmis
    assert re.search(r"export\s+function\s+winRateClass\b", fmt_src), (
        "formatters.js icinde winRateClass helper'i export edilmis degil."
    )
    assert re.search(r"export\s+function\s+winRateColor\b", fmt_src), (
        "formatters.js icinde winRateColor helper'i export edilmis degil."
    )

    # (c) formatters.js DISINDA hardcode `win_rate >= 50` / `winRate >= 50`
    # YASAK. Tum desktop/src/components'i tara.
    components_dir = ROOT / "desktop" / "src" / "components"
    hardcode_pattern = re.compile(r"\b(?:win_rate|winRate)\s*>=\s*50\b")
    offenders = []
    for jsx_file in sorted(components_dir.rglob("*.jsx")):
        jsx_src = jsx_file.read_text(encoding="utf-8")
        if hardcode_pattern.search(jsx_src):
            offenders.append(jsx_file.relative_to(ROOT).as_posix())
    assert not offenders, (
        "Asagidaki bilesen(ler)de hardcode `win_rate >= 50` veya "
        "`winRate >= 50` bulundu (Widget Denetimi H13 ihlali) — "
        "formatters.js::winRateClass veya winRateColor helper'lari "
        f"kullanilmalidir: {offenders}"
    )

    # (d) H13 marker
    assert "Widget Denetimi H13" in fmt_src, (
        "formatters.js icinde 'Widget Denetimi H13' marker yok — "
        "canonical atif kaybolmus, refactor sirasinda merkezi kaynak "
        "bilgisi silinmis olabilir."
    )


# ── Flow 4z: Hata Takip taxonomy backend sync (Widget Denetimi H7) ──
def test_error_taxonomy_backend_sync():
    """Frontend errorTaxonomy.js backend ERROR_CATEGORIES + SEVERITY ile sync.

    H7: ErrorTracker.jsx icinde CATEGORY_COLORS, SEVERITY_COLORS,
    SEVERITY_LABELS ve filtre option literal'leri ayri ayri hardcode
    ediliyordu. Backend `engine/error_tracker.py` ERROR_CATEGORIES dict
    veya SEVERITY_PRIORITY dict degistirilirse frontend sessizce kopardi
    (drift). Artik canonical kaynak `desktop/src/utils/errorTaxonomy.js`
    ve bu test backend ile sync'i CI'da garanti eder.

    Regression koruma:
        (a) errorTaxonomy.js dosyasi mevcut olmali ve gerekli export'lar
            tanimli olmali (CATEGORY_COLORS, SEVERITY_COLORS,
            SEVERITY_LABELS, CATEGORY_FILTER_OPTIONS, SEVERITY_FILTER_OPTIONS).
        (b) Backend `engine/error_tracker.py` ERROR_CATEGORIES dict'inden
            cikarilan unique kategori seti ile errorTaxonomy.js
            CATEGORY_COLORS keys seti EXACT match olmali — backend yeni
            kategori eklerse veya kaldirirsa bu test FAIL eder.
        (c) Backend SEVERITY_PRIORITY dict keys'i frontend SEVERITY_COLORS
            keys'inin uzerkumesi olmali (frontend INFO/DEBUG opsiyonel
            gosterse de gostermese de drift olmamali).
        (d) ErrorTracker.jsx artik yerel CATEGORY_COLORS / SEVERITY_COLORS /
            SEVERITY_LABELS const tanimi ICERMEMELI (regression engelle).
        (e) ErrorTracker.jsx errorTaxonomy.js'den import yapiyor olmali.
        (f) `Widget Denetimi H7` marker yorumu errorTaxonomy.js'te mevcut.
    """
    # ── (a) Canonical modul + export'lar ──
    tax_js = ROOT / "desktop" / "src" / "utils" / "errorTaxonomy.js"
    assert tax_js.exists(), (
        "desktop/src/utils/errorTaxonomy.js yok — H7 canonical modul kaldirilmis."
    )
    tax_src = tax_js.read_text(encoding="utf-8")
    for export_name in (
        "CATEGORY_COLORS",
        "SEVERITY_COLORS",
        "SEVERITY_LABELS",
        "CATEGORY_FILTER_OPTIONS",
        "SEVERITY_FILTER_OPTIONS",
    ):
        assert re.search(rf"export\s+const\s+{export_name}\b", tax_src), (
            f"errorTaxonomy.js icinde '{export_name}' export'u yok."
        )

    # ── (b) Backend ERROR_CATEGORIES unique values seti vs frontend keys ──
    backend_py = ROOT / "engine" / "error_tracker.py"
    assert backend_py.exists(), "engine/error_tracker.py yok."
    backend_src = backend_py.read_text(encoding="utf-8")

    err_cat_match = re.search(
        r"ERROR_CATEGORIES\s*=\s*\{(.*?)\}", backend_src, re.DOTALL
    )
    assert err_cat_match, "engine/error_tracker.py icinde ERROR_CATEGORIES dict bulunamadi."
    err_cat_block = err_cat_match.group(1)
    backend_cats = set(re.findall(r":\s*\"([^\"]+)\"", err_cat_block))
    assert backend_cats, "ERROR_CATEGORIES values parse edilemedi."

    cat_colors_match = re.search(
        r"export\s+const\s+CATEGORY_COLORS\s*=\s*\{(.*?)\};",
        tax_src,
        re.DOTALL,
    )
    assert cat_colors_match, "errorTaxonomy.js CATEGORY_COLORS bloku parse edilemedi."
    cat_colors_block = cat_colors_match.group(1)
    frontend_cats = set(re.findall(r"'([^']+)'\s*:", cat_colors_block))
    assert frontend_cats, "CATEGORY_COLORS keys parse edilemedi."

    missing_in_frontend = backend_cats - frontend_cats
    extra_in_frontend = frontend_cats - backend_cats
    assert not missing_in_frontend, (
        f"Backend ERROR_CATEGORIES.values() icinde olup frontend "
        f"CATEGORY_COLORS keys'inde OLMAYAN kategori(ler): "
        f"{sorted(missing_in_frontend)}. errorTaxonomy.js guncellenmeli."
    )
    assert not extra_in_frontend, (
        f"Frontend CATEGORY_COLORS keys'inde olup backend "
        f"ERROR_CATEGORIES.values() icinde OLMAYAN kategori(ler): "
        f"{sorted(extra_in_frontend)}. errorTaxonomy.js veya backend "
        f"engine/error_tracker.py guncel degil."
    )

    # ── (c) Backend SEVERITY_PRIORITY keys vs frontend SEVERITY_COLORS keys ──
    sev_match = re.search(
        r"SEVERITY_PRIORITY\s*=\s*\{(.*?)\}", backend_src, re.DOTALL
    )
    assert sev_match, "SEVERITY_PRIORITY dict bulunamadi."
    backend_sevs = set(re.findall(r"\"([A-Z]+)\"\s*:", sev_match.group(1)))
    assert backend_sevs, "SEVERITY_PRIORITY keys parse edilemedi."

    sev_colors_match = re.search(
        r"export\s+const\s+SEVERITY_COLORS\s*=\s*\{(.*?)\};",
        tax_src,
        re.DOTALL,
    )
    assert sev_colors_match, "SEVERITY_COLORS bloku parse edilemedi."
    frontend_sevs = set(re.findall(r"\b([A-Z]+)\s*:", sev_colors_match.group(1)))
    assert frontend_sevs, "SEVERITY_COLORS keys parse edilemedi."

    # Frontend SEVERITY_COLORS, backend SEVERITY_PRIORITY'nin alt kumesi olmali
    # (frontend DEBUG'i gostermez ama varsa da gostermek istemez).
    sev_drift = frontend_sevs - backend_sevs
    assert not sev_drift, (
        f"Frontend SEVERITY_COLORS icinde backend SEVERITY_PRIORITY'de "
        f"olmayan key(ler) var: {sorted(sev_drift)}. Backend ile drift."
    )

    # ── (d) ErrorTracker.jsx yerel const tanimi YASAK ──
    et_jsx = ROOT / "desktop" / "src" / "components" / "ErrorTracker.jsx"
    assert et_jsx.exists(), "ErrorTracker.jsx yok."
    et_src = et_jsx.read_text(encoding="utf-8")
    local_const_pattern = re.compile(
        r"^\s*const\s+(?:CATEGORY_COLORS|SEVERITY_COLORS|SEVERITY_LABELS)\s*=",
        re.MULTILINE,
    )
    assert not local_const_pattern.search(et_src), (
        "ErrorTracker.jsx icinde yerel CATEGORY_COLORS / SEVERITY_COLORS / "
        "SEVERITY_LABELS const tanimi var — H7 ihlali; canonical kaynak "
        "errorTaxonomy.js'tir, import edilmeli."
    )

    # ── (e) ErrorTracker.jsx errorTaxonomy import yapmali ──
    assert "from '../utils/errorTaxonomy'" in et_src, (
        "ErrorTracker.jsx errorTaxonomy.js'den import yapmiyor — "
        "H7 canonical kaynak kullanilmiyor."
    )

    # ── (f) H7 marker ──
    assert "Widget Denetimi" in tax_src and "H7" in tax_src, (
        "errorTaxonomy.js icinde 'Widget Denetimi H7' marker yok — "
        "canonical kaynak rolu/atif kaybolmus."
    )


# ── Flow 4za: Operator kimligi canonical kaynak (Widget Denetimi H16) ─
def test_operator_identity_canonical_source():
    """Widget Denetimi H16 (+K7): Operator kimligi hardcode 'operator'
    string'i drift yuzeyindeydi.

    Eski drift yuzeyi (3 ayri call site):
      - TradeHistory.jsx::handleApprove satir 366: approveTrade(id, 'operator', '')
      - SideNav.jsx::handleKillSwitch satir 89: activateKillSwitch('operator')
      - TopBar.jsx::handleKsReset satir 134: acknowledgeKillSwitch('operator')

    Sonuc: backend audit log her zaman 'APPROVED by operator' yaziyordu —
    birden fazla operator calissa bile ayirt edilemiyordu.

    Yeni canonical kaynak: desktop/src/utils/operator.js
      - getOperatorName() / setOperatorName(name) / OPERATOR_NAME_KEY
      - localStorage['ustat_operator_name'] tek dogru kaynak
      - Bos / yok ise DEFAULT_OPERATOR ('operator') fallback (geriye uyumlu)
      - Settings.jsx 'Operator Adi' alani setOperatorName ile yazar

    Bu test:
      (a) operator.js mevcut + 3 export regex dogrulanir
      (b) Uc tuketici dosyada hardcode 'operator' literal'i YASAK
      (c) Uc tuketici dosya '../utils/operator' import yapmali
      (d) Settings.jsx setOperatorName helper'ini import etmeli
      (e) DEFAULT_OPERATOR fallback'i operator.js'te 'operator' olmali
      (f) Widget Denetimi H16 marker mevcut (canonical kaynak rolu)
    """
    op_path = ROOT / "desktop" / "src" / "utils" / "operator.js"
    assert op_path.exists(), f"operator.js bulunamadi: {op_path}"
    op_src = op_path.read_text(encoding="utf-8")

    # (a) 3 export tanimli
    for export_name in ("OPERATOR_NAME_KEY", "DEFAULT_OPERATOR", "getOperatorName", "setOperatorName"):
        assert re.search(rf"export\s+(?:const|function)\s+{export_name}\b", op_src), (
            f"operator.js icinde 'export {export_name}' bulunamadi — "
            f"canonical kaynak API kontrati bozuk."
        )

    # (e) DEFAULT_OPERATOR fallback degeri 'operator' olmali (geriye uyum)
    assert re.search(r"DEFAULT_OPERATOR\s*=\s*['\"]operator['\"]", op_src), (
        "DEFAULT_OPERATOR fallback 'operator' string'i degil — eski "
        "audit log davranisi bozuldu, geriye uyumluluk kaybi."
    )

    # (f) H16 marker
    assert "Widget Denetimi" in op_src and "H16" in op_src, (
        "operator.js icinde 'Widget Denetimi H16' marker yok — canonical "
        "kaynak rolu/atif kaybolmus."
    )

    # (b) + (c) Uc tuketici dosyada hardcode 'operator' literal'i YASAK,
    # ve operator.js import edilmeli
    consumers = [
        ("desktop/src/components/TradeHistory.jsx", "approveTrade"),
        ("desktop/src/components/SideNav.jsx", "activateKillSwitch"),
        ("desktop/src/components/TopBar.jsx", "acknowledgeKillSwitch"),
    ]
    for rel_path, fn_name in consumers:
        path = ROOT / rel_path
        assert path.exists(), f"{rel_path} bulunamadi"
        src = path.read_text(encoding="utf-8")

        # Hardcode 'operator' literal'i ilgili fonksiyon cagrisinda YASAK.
        # Pattern: fn_name( ... 'operator' ... )  (tek/cift tirnak, opsiyonel
        # whitespace ve oncesi parametreler).
        forbidden = re.search(
            rf"{fn_name}\s*\([^)]*['\"]operator['\"]",
            src,
        )
        assert forbidden is None, (
            f"{rel_path} icinde {fn_name}() cagrisi hala literal 'operator' "
            f"string'i kullaniyor — H16 regression. getOperatorName() "
            f"helper'ina gecirilmis olmasi gerekirdi."
        )

        # operator.js import edilmis olmali
        assert "from '../utils/operator'" in src or 'from "../utils/operator"' in src, (
            f"{rel_path} icinde '../utils/operator' import'u yok — "
            f"getOperatorName helper'i kullanilmiyor olabilir."
        )
        assert "getOperatorName" in src, (
            f"{rel_path} icinde getOperatorName referansi yok."
        )

    # (d) Settings.jsx setOperatorName import etmeli (UI yazma yolu)
    settings_path = ROOT / "desktop" / "src" / "components" / "Settings.jsx"
    settings_src = settings_path.read_text(encoding="utf-8")
    assert "setOperatorName" in settings_src, (
        "Settings.jsx setOperatorName helper'ini import etmiyor — "
        "Operator Adi alani yazma yolu kopuk."
    )
    assert "from '../utils/operator'" in settings_src or 'from "../utils/operator"' in settings_src, (
        "Settings.jsx '../utils/operator' import'u yok."
    )


# ── Flow 4zb: Hibrit SL/TP gorunurlugu (Widget Denetimi A8 / K10) ──
def test_hybrid_sltp_visibility_in_positions_response():
    """Widget Denetimi A8 (K10): Hibrit pozisyonlarda MT5 native sl/tp '—'
    goruluyordu (genelde 0), gercek koruma h_engine.hybrid_positions[ticket]
    .current_sl / current_tp icinde sanal olarak tutuluyordu. Kullanici
    Dashboard'da hibrit satirini 'korumasiz' sanabilirdi.

    Yeni sozlesme:
      - PositionItem schema'sina hybrid_sl + hybrid_tp alanlari eklendi.
      - api/routes/positions.py::get_positions icinde ticket hibrit_tickets
        icindeyse h_engine.hybrid_positions[ticket].current_sl / current_tp
        okunur ve schema'ya doldurulur. Manuel/Otomatik/MT5 satirlarinda
        iki alan da varsayilan 0.0 kalir.
      - Dashboard.jsx SL/TP hucresi: hibrit satir + native MT5 sl==0 iken
        pos.hybrid_sl italik + tooltip ('MT5 native degil, H-Engine sanal
        koruma') ile gosterilir. Native varsa MT5 degeri oncelik.

    Bu test:
      (a) PositionItem schema'sinda hybrid_sl + hybrid_tp alanlari var
      (b) api/routes/positions.py hibrit ticket icin hybrid_positions
          sozlugunu okuyor ve current_sl / current_tp'yi aliyor
      (c) api/routes/positions.py PositionItem constructor'inda hybrid_sl
          ve hybrid_tp kwarg'larini veriyor
      (d) Dashboard.jsx pos.hybrid_sl / pos.hybrid_tp referanslari + tooltip
          mesaji mevcut (sanal koruma metni)
      (e) Widget Denetimi A8 / K10 marker mevcut (backend + frontend)
    """
    # (a) Schema alanlari
    schema_path = ROOT / "api" / "schemas.py"
    schema_src = schema_path.read_text(encoding="utf-8")
    assert re.search(r"hybrid_sl\s*:\s*float\s*=", schema_src), (
        "api/schemas.py PositionItem icinde 'hybrid_sl: float =' alani yok "
        "— A8 schema kontrati bozuk."
    )
    assert re.search(r"hybrid_tp\s*:\s*float\s*=", schema_src), (
        "api/schemas.py PositionItem icinde 'hybrid_tp: float =' alani yok "
        "— A8 schema kontrati bozuk."
    )

    # (b) + (c) Route hibrit ticket icin hybrid_positions okuyor ve kwarg
    #     veriyor
    route_path = ROOT / "api" / "routes" / "positions.py"
    route_src = route_path.read_text(encoding="utf-8")
    assert "h_engine.hybrid_positions" in route_src, (
        "api/routes/positions.py h_engine.hybrid_positions sozlugunu "
        "okumuyor — hibrit SL/TP backend'den hic gelmiyor."
    )
    assert "current_sl" in route_src and "current_tp" in route_src, (
        "api/routes/positions.py HybridPosition.current_sl / current_tp "
        "alanlarini okumuyor — sanal koruma degerleri bos kaliyor."
    )
    assert re.search(r"hybrid_sl\s*=\s*hybrid_sl_val", route_src), (
        "api/routes/positions.py PositionItem constructor'inda hybrid_sl "
        "kwarg'i yok — schema doldurulmuyor."
    )
    assert re.search(r"hybrid_tp\s*=\s*hybrid_tp_val", route_src), (
        "api/routes/positions.py PositionItem constructor'inda hybrid_tp "
        "kwarg'i yok — schema doldurulmuyor."
    )

    # (d) Dashboard.jsx hybrid_sl / hybrid_tp referanslari + tooltip
    dashboard_path = ROOT / "desktop" / "src" / "components" / "Dashboard.jsx"
    dash_src = dashboard_path.read_text(encoding="utf-8")
    assert "pos.hybrid_sl" in dash_src, (
        "Dashboard.jsx pos.hybrid_sl referansi yok — hibrit satirda sanal "
        "SL gosterimi eklenmemis."
    )
    assert "pos.hybrid_tp" in dash_src, (
        "Dashboard.jsx pos.hybrid_tp referansi yok — hibrit satirda sanal "
        "TP gosterimi eklenmemis."
    )
    assert "sanal koruma" in dash_src.lower() or "h-engine sanal" in dash_src.lower(), (
        "Dashboard.jsx hibrit SL/TP tooltip metni ('H-Engine sanal koruma') "
        "bulunamadi — kullanici 'bu deger MT5 native mi?' ayrimini goremez."
    )

    # (e) Widget Denetimi A8 marker backend + frontend
    assert "A8" in schema_src and "K10" in schema_src, (
        "api/schemas.py icinde 'A8 (K10)' marker yok — audit izi kaybolmus."
    )
    assert "A8" in route_src and "K10" in route_src, (
        "api/routes/positions.py icinde 'A8 (K10)' marker yok — audit izi "
        "kaybolmus."
    )
    assert "A8" in dash_src and "K10" in dash_src, (
        "Dashboard.jsx icinde 'A8 (K10)' marker yok — audit izi kaybolmus."
    )


# ── Flow 4zc: Error resolve message_prefix DB yazimi (A15 / B18) ──
def test_error_resolve_message_prefix_persistence():
    """Widget Denetimi A15 (B18): Hata Takip Paneli "Cozumle" butonu
    spesifik mesaj icin tiklandiginda DB'ye message_prefix kolonuyla yazilmali.
    Eski davranis: sadece error_type yaziliyordu, ayni tipin tum mesajlari
    sessizce bastiriliyordu (frontend'de "tek satir cozumledim" yanilsamasi).

    Bu test 5 sozlesme noktasini dogrular:
      1. error_tracker.py: _resolved_keys field + _ensure_resolution_table
         icinde message_prefix migration mantigi
      2. error_tracker.py: resolve_group icinde prefix_key dallanmasi +
         INSERT'in 4 kolonlu olmasi
      3. error_tracker.py: record_error icinde iki seviyeli suppression
         kontrolu (_resolved_types VEYA _resolved_keys)
      4. error_dashboard.py: /resolve endpoint INSERT'i message_prefix dahil
         + _get_resolution_map sadece wildcard satirlari okur
      5. Audit markerlari (A15 + B18) error_tracker.py + error_dashboard.py
    """
    et_path = ROOT / "engine" / "error_tracker.py"
    rd_path = ROOT / "api" / "routes" / "error_dashboard.py"
    et_src = et_path.read_text(encoding="utf-8")
    rd_src = rd_path.read_text(encoding="utf-8")

    # 1. _resolved_keys field + migration mantigi
    assert "_resolved_keys" in et_src, (
        "engine/error_tracker.py icinde _resolved_keys field tanimli degil — "
        "iki seviyeli (wildcard + spesifik) bastirma yok."
    )
    assert "message_prefix" in et_src, (
        "engine/error_tracker.py icinde message_prefix kolonu adi yok — "
        "A15 fix uygulanmamis."
    )
    assert "ALTER TABLE error_resolutions RENAME" in et_src, (
        "engine/error_tracker.py icinde error_resolutions A15 gocu yok — "
        "eski sema sessizce kalir, frontend yanilsamasi devam eder."
    )
    assert "PRIMARY KEY (error_type, message_prefix)" in et_src, (
        "engine/error_tracker.py icinde composite PK tanimi yok — "
        "ayni tip + farkli prefix satiri eklenemez."
    )

    # 2. resolve_group prefix_key dallanmasi + 4 kolonlu INSERT
    assert "prefix_key" in et_src, (
        "engine/error_tracker.py::resolve_group icinde prefix_key degiskeni "
        "yok — spesifik vs wildcard ayrimi yapilmaz."
    )
    et_insert_pattern = re.compile(
        r"INSERT\s+OR\s+REPLACE\s+INTO\s+error_resolutions\s*"
        r"\(\s*error_type\s*,\s*message_prefix\s*,\s*resolved_at\s*,\s*resolved_by\s*\)",
        re.IGNORECASE,
    )
    assert et_insert_pattern.search(et_src), (
        "engine/error_tracker.py icinde 4 kolonlu INSERT (error_type, "
        "message_prefix, resolved_at, resolved_by) yok — kalici DB yazimi "
        "eski semada kaliyor."
    )
    # DELETE events de prefix duyarli olmali
    assert "substr(trim(message), 1, 80)" in et_src, (
        "engine/error_tracker.py::resolve_group DELETE statement'i "
        "substr(trim(message), 1, 80) prefix eslestirmesi yapmiyor — "
        "spesifik cozumlemede ayni tipin diger mesajli event'leri de silinir."
    )

    # 3. record_error iki seviyeli suppression
    assert "_resolved_keys" in et_src and "in self._resolved_keys" in et_src, (
        "engine/error_tracker.py::record_error icinde "
        "(error_type, prefix) in self._resolved_keys kontrolu yok — "
        "spesifik cozumlemeler bastirilmaz."
    )

    # 4. error_dashboard.py route fix
    rd_insert_pattern = re.compile(
        r"INSERT\s+OR\s+REPLACE\s+INTO\s+error_resolutions\s*"
        r"\(\s*error_type\s*,\s*message_prefix\s*,\s*resolved_at\s*,\s*resolved_by\s*\)",
        re.IGNORECASE,
    )
    assert rd_insert_pattern.search(rd_src), (
        "api/routes/error_dashboard.py icinde 4 kolonlu INSERT yok — "
        "/resolve ve /resolve-all endpoint'leri eski semada yazmaya devam eder."
    )
    assert "WHERE message_prefix = ''" in rd_src, (
        "api/routes/error_dashboard.py::_get_resolution_map sadece wildcard "
        "satirlari okumuyor — spesifik cozumleme tum tipi 'cozulmus' "
        "gosterir, audit bulgusu B18 tekrarlar."
    )
    assert "prefix_key" in rd_src, (
        "api/routes/error_dashboard.py::resolve_error_group icinde prefix_key "
        "yok — message_prefix kolonu DB'ye sifir uzunluk gibi yazilir."
    )

    # 5. Audit markerlari
    assert "A15" in et_src and "B18" in et_src, (
        "engine/error_tracker.py icinde 'A15' veya 'B18' audit markerlari yok."
    )
    assert "A15" in rd_src and "B18" in rd_src, (
        "api/routes/error_dashboard.py icinde 'A15' veya 'B18' audit "
        "markerlari yok."
    )


# ── Flow 4zd: Performans equity vs deposit ayrimi (A6 / B14) ─────
def test_performance_net_equity_separation():
    """Widget Denetimi A6 (B14): Equity Egrisi yatirim transferleri
    sayesinde sismeyecek. Backend her snapshot icin cumulative_deposits
    ve net_equity = equity - cumulative_deposits hesaplar; frontend
    'Net Sermaye' serisi olarak cizer.

    5 sozlesme noktasi:
      1. schemas.EquityPoint icinde net_equity + cumulative_deposits
         alanlari
      2. performance.py icinde delta_unexplained tespiti
         (delta_balance - explained pnl) ve threshold dali
      3. performance.py icinde net_equity = eq - cumulative_deposits
         ve EquityPoint(...net_equity=) olusturma
      4. Performance.jsx icinde dataKey="net_equity" Area + 'Net Sermaye'
         legend etiketi
      5. Audit markerlari (A6 + B14) hem backend hem frontend dosyalarda
    """
    sc_path = ROOT / "api" / "schemas.py"
    pf_path = ROOT / "api" / "routes" / "performance.py"
    fe_path = ROOT / "desktop" / "src" / "components" / "Performance.jsx"
    sc_src = sc_path.read_text(encoding="utf-8")
    pf_src = pf_path.read_text(encoding="utf-8")
    fe_src = fe_path.read_text(encoding="utf-8")

    # 1. Schema alanlari
    assert "net_equity" in sc_src, (
        "api/schemas.py icinde net_equity alani yok — A6 fix uygulanmamis."
    )
    assert "cumulative_deposits" in sc_src, (
        "api/schemas.py icinde cumulative_deposits alani yok — yatirim "
        "transferleri kumulatif olarak takip edilmiyor."
    )

    # 2. performance.py delta_unexplained tespiti
    assert "delta_unexplained" in pf_src, (
        "api/routes/performance.py icinde delta_unexplained degiskeni yok — "
        "deposit/withdrawal tespiti eksik."
    )
    assert "daily_balance_impact" in pf_src, (
        "api/routes/performance.py icinde daily_balance_impact map yok — "
        "trade pnl + commission + swap toplami hesaplanmiyor, "
        "komisyon gurultusu yatirim sayilir."
    )
    assert "cumulative_deposits" in pf_src, (
        "api/routes/performance.py icinde cumulative_deposits degiskeni "
        "yok — kumulatif yatirim takibi yok."
    )

    # 3. net_equity hesaplama + EquityPoint enjeksiyonu
    assert "net_equity = eq - cumulative_deposits" in pf_src, (
        "api/routes/performance.py icinde net_equity = eq - "
        "cumulative_deposits formulu yok."
    )
    pf_eq_point_pattern = re.compile(
        r"EquityPoint\(.*?net_equity\s*=", re.DOTALL,
    )
    assert pf_eq_point_pattern.search(pf_src), (
        "api/routes/performance.py icinde EquityPoint(...net_equity=...) "
        "kurucu cagrisi yok — alan bos donuyor."
    )

    # 4. Frontend net_equity Area + legend
    assert 'dataKey="net_equity"' in fe_src, (
        "desktop/src/components/Performance.jsx icinde "
        'dataKey="net_equity" yok — UI net sermayeyi cizmiyor.'
    )
    assert "Net Sermaye" in fe_src, (
        "desktop/src/components/Performance.jsx icinde 'Net Sermaye' "
        "etiketi yok — kullanici hangi seriyi gordugunu bilmez."
    )

    # 5. Audit markerlari
    assert "A6" in pf_src and "B14" in pf_src, (
        "api/routes/performance.py icinde 'A6' veya 'B14' audit "
        "markerlari yok."
    )
    assert "A6" in fe_src and "B14" in fe_src, (
        "desktop/src/components/Performance.jsx icinde 'A6' veya 'B14' "
        "audit markerlari yok."
    )


# ── Flow 4ze: Hibrit/Otomatik scratch + ozet ayrimi (B8) ─────────
def test_hybrid_scratch_and_auto_summary_enrichment():
    """B8: get_hybrid_performance scratches alanini dondurur,
    HybridTrade Esit hucresini gosterir, AutoTrading Otomatik Ozeti
    sessiz karttan zenginlestirilmis ozete cevrilir."""
    db_path = ROOT / "engine" / "database.py"
    ht_path = ROOT / "desktop" / "src" / "components" / "HybridTrade.jsx"
    at_path = ROOT / "desktop" / "src" / "components" / "AutoTrading.jsx"
    db_src = db_path.read_text(encoding="utf-8")
    ht_src = ht_path.read_text(encoding="utf-8")
    at_src = at_path.read_text(encoding="utf-8")

    # 1. database.py: get_hybrid_performance scratches alani
    assert "scratches = total - winners - losers" in db_src, (
        "engine/database.py::get_hybrid_performance icinde "
        "'scratches = total - winners - losers' formulu yok — "
        "B8 invariant (total = w + l + s) saglanmiyor."
    )
    db_perf_pattern = re.compile(
        r"def get_hybrid_performance.*?\"scratches\":\s*scratches",
        re.DOTALL,
    )
    assert db_perf_pattern.search(db_src), (
        "get_hybrid_performance return dict'inde 'scratches' anahtari "
        "yok — frontend Esit hucresini dolduramaz."
    )
    # Empty case'de de scratches alani olmali (default 0)
    assert '"scratches": 0' in db_src, (
        "get_hybrid_performance bos kayit dalinda 'scratches: 0' "
        "default'u yok — schema istikrarli degil."
    )

    # 2. HybridTrade.jsx Esit hucresi
    assert "perfStats.scratches" in ht_src, (
        "HybridTrade.jsx icinde 'perfStats.scratches' kullanimi yok — "
        "B8 scratch sayisi UI'de gizli kaliyor."
    )
    # Esit etiketi performans grid'inde gozukmeli
    assert ">Eşit<" in ht_src, (
        "HybridTrade.jsx icinde 'Eşit' performans hucresi etiketi yok."
    )

    # 3. AutoTrading.jsx Otomatik Ozet zenginlestirme
    assert "auto-summary-grid" in at_src, (
        "AutoTrading.jsx icinde 'auto-summary-grid' yok — Otomatik Ozet "
        "kart sessiz duplicate olarak kalmis (B8/A12)."
    )
    assert "Otomatik Özet" in at_src, (
        "AutoTrading.jsx Otomatik Pozisyon Özeti karti baslik "
        "guncellemesi yok — eski 'Otomatik Pozisyonlar' baslikli "
        "duplicate kart hala duruyor olabilir."
    )
    # Strateji dagilim mantigi
    assert "stratCounts" in at_src, (
        "AutoTrading.jsx Otomatik Ozet'inde strateji dagilimi "
        "(stratCounts) yok."
    )

    # 4. Audit markerlari
    assert "B8" in db_src, (
        "engine/database.py icinde 'B8' audit markerin yok."
    )
    assert "B8" in ht_src, (
        "desktop/src/components/HybridTrade.jsx icinde 'B8' "
        "audit markerin yok."
    )
    assert "B8" in at_src, (
        "desktop/src/components/AutoTrading.jsx icinde 'B8' "
        "audit markerin yok."
    )


# ── Flow 4zf: PRIMNET esikleri gorunur kart (A11/S4) ─────────────
def test_primnet_thresholds_visible_card():
    """A11 (S4): HybridTrade Ozet karti PRIMNET trailing/target prim
    esiklerini modal acmadan gostermeli. Backend HybridStatusResponse
    uzerinden primnet.trailing_prim ve primnet.target_prim canli akiyor.
    Eger kart silinirse, kullanici esikleri sadece PrimnetDetail
    modalini acarak gorebilir — gorunurluk regresyonu sayilir."""
    ht_path = ROOT / "desktop" / "src" / "components" / "HybridTrade.jsx"
    schemas_path = ROOT / "api" / "schemas.py"
    route_path = ROOT / "api" / "routes" / "hybrid_trade.py"
    css_path = ROOT / "desktop" / "src" / "styles" / "theme.css"

    ht_src = ht_path.read_text(encoding="utf-8")
    schemas_src = schemas_path.read_text(encoding="utf-8")
    route_src = route_path.read_text(encoding="utf-8")
    css_src = css_path.read_text(encoding="utf-8")

    # 1. Backend schema canli (PrimnetConfig + HybridStatusResponse.primnet)
    assert "class PrimnetConfig" in schemas_src, (
        "api/schemas.py icinde PrimnetConfig sinifi yok — backend kanali "
        "kirilmis."
    )
    assert "primnet: PrimnetConfig" in schemas_src, (
        "HybridStatusResponse.primnet alani yok — A11 frontend kart "
        "kaynaksiz kalir."
    )
    assert "trailing_prim=h_engine.primnet_trailing" in route_src, (
        "api/routes/hybrid_trade.py icinde primnet_cfg trailing_prim "
        "atamasi yok — engine canonical kaynaktan kopmus."
    )
    assert "target_prim=h_engine.primnet_target" in route_src, (
        "api/routes/hybrid_trade.py icinde primnet_cfg target_prim "
        "atamasi yok — engine canonical kaynaktan kopmus."
    )

    # 2. Frontend HybridTrade.jsx kart icerigi
    assert "PRİMNET Eşikleri" in ht_src, (
        "HybridTrade.jsx Ozet kartinda 'PRİMNET Eşikleri' baslikli kart "
        "yok — A11/S4 gorunurluk bulgu duzeltmesi geri alinmis."
    )
    assert "hybridStatus.primnet?.trailing_prim" in ht_src, (
        "HybridTrade.jsx kart icinde 'hybridStatus.primnet?.trailing_prim' "
        "referansi yok — eski hardcode dondu mu?"
    )
    assert "hybridStatus.primnet?.target_prim" in ht_src, (
        "HybridTrade.jsx kart icinde 'hybridStatus.primnet?.target_prim' "
        "referansi yok — eski hardcode dondu mu?"
    )

    # 3. CSS sinifi mevcut
    assert ".op-sc-value--primnet" in css_src, (
        "theme.css icinde '.op-sc-value--primnet' modifier sinifi yok — "
        "A11 kart gorsel olarak digerleriyle ayni boyutta cikar."
    )

    # 4. Audit markerlari
    assert "A11" in ht_src, (
        "HybridTrade.jsx icinde A11 audit markerin yok."
    )
    assert "A11" in css_src, (
        "theme.css icinde A11 audit markerin yok."
    )


# ── Flow 4zk: NABIZ retention/cleanup coverage + critical threshold (A26/K4) ──
def test_nabiz_cleanup_conflict_bars_coverage_and_critical_scan():
    """A26 (K4): NABIZ _build_cleanup_conflict_info iki kritik hata
    iceriyordu:

    1. `retention_covered` set'i `bars`'i icermiyordu ama bars cleanup
       ile yonetiliyordu — bars "retention YOK" olarak listelenip
       kullaniciya sessizce yanlis sinyal veriyordu.
    2. `has_conflict` sensoru sadece retention tamamen kapaliyken True
       donuyordu. Bars 183,078 satirla danger esigini (150,000) asmis
       olsa bile conflict accordion'u gizli kaliyordu — erken uyari kor.

    Duzeltme:
    - cleanup_covered = {"bars"} eklendi
    - managed_tables = retention_covered | cleanup_covered
    - NABIZ_TABLE_ROW_THRESHOLDS taramasi yapiliyor — danger esigini
      asan tablolar `critical_over_threshold` listesinde raporlaniyor
    - has_conflict = affected | missing | critical_over_threshold
    - Frontend Nabiz.jsx'e CriticalOverThresholdPanel eklendi
    """
    import re
    nabiz_path = ROOT / "api" / "routes" / "nabiz.py"
    assert nabiz_path.exists(), "api/routes/nabiz.py bulunamadi"
    src = nabiz_path.read_text(encoding="utf-8")

    # 1) cleanup_covered set ayri tutuluyor + bars iceriyor
    assert re.search(r'cleanup_covered\s*=\s*\{\s*"bars"\s*\}', src), (
        "api/routes/nabiz.py icinde `cleanup_covered = {\"bars\"}` tanimi yok "
        "— A26 fix uygulanmamis."
    )

    # 2) managed_tables birlesimi kullaniliyor
    assert "managed_tables = retention_covered | cleanup_covered" in src, (
        "api/routes/nabiz.py icinde `managed_tables = retention_covered | "
        "cleanup_covered` birlesimi yok."
    )
    assert "table not in managed_tables" in src, (
        "api/routes/nabiz.py icinde `table not in managed_tables` kontrolu "
        "yok — missing listesi hala `retention_covered` tekil setine bakiyor."
    )

    # 3) NABIZ_TABLE_ROW_THRESHOLDS danger esik taramasi yapiliyor
    assert "critical_over_threshold" in src, (
        "api/routes/nabiz.py icinde `critical_over_threshold` listesi yok."
    )
    assert re.search(
        r'for\s+table,\s*thresholds\s+in\s+NABIZ_TABLE_ROW_THRESHOLDS\.items\(\)',
        src,
    ), (
        "api/routes/nabiz.py _build_cleanup_conflict_info icinde "
        "NABIZ_TABLE_ROW_THRESHOLDS uzerinden iterasyon yok — esik "
        "taramasi eksik."
    )
    assert re.search(r'count\s*>=\s*danger', src), (
        "api/routes/nabiz.py icinde `count >= danger` esik karsilastirmasi yok."
    )

    # 4) has_conflict uc katmanli — affected/missing/critical_over_threshold
    has_conflict_match = re.search(
        r'has_conflict\s*=\s*\(\s*len\(affected\).*?len\(missing\).*?'
        r'len\(critical_over_threshold\).*?\)',
        src,
        re.DOTALL,
    )
    assert has_conflict_match, (
        "api/routes/nabiz.py icinde `has_conflict` uc katmanli degil: "
        "affected, missing ve critical_over_threshold birlesimi bekleniyor."
    )

    # 5) Return payload'inda critical_over_threshold alani var
    assert re.search(
        r'"critical_over_threshold"\s*:\s*critical_over_threshold',
        src,
    ), (
        "api/routes/nabiz.py return payload'inda `critical_over_threshold` "
        "alani yok — frontend alanı okuyamaz."
    )

    # 6) A26 audit marker backend'te
    assert "A26" in src, (
        "api/routes/nabiz.py icinde A26 audit markerin yok."
    )

    # 7) Frontend Nabiz.jsx CriticalOverThresholdPanel bileseni ve render
    nabiz_jsx = ROOT / "desktop" / "src" / "components" / "Nabiz.jsx"
    assert nabiz_jsx.exists(), "desktop/src/components/Nabiz.jsx bulunamadi"
    jsx = nabiz_jsx.read_text(encoding="utf-8")

    assert "function CriticalOverThresholdPanel" in jsx, (
        "Nabiz.jsx icinde CriticalOverThresholdPanel fonksiyonu yok."
    )
    assert re.search(
        r'<CriticalOverThresholdPanel\s+items=\{conflict\.critical_over_threshold',
        jsx,
    ), (
        "Nabiz.jsx render agacinda "
        "`<CriticalOverThresholdPanel items={conflict.critical_over_threshold...` "
        "cagrisi yok."
    )
    assert "A26" in jsx, (
        "Nabiz.jsx icinde A26 audit markerin yok."
    )


# ── Flow 4zj: Event 5000 limit truncation alarm (A25/K3) ──
def test_error_dashboard_event_truncation_alarm():
    """A25 (K3): /api/errors/summary endpoint'i 7 gunluk event sorgusunda
    5000 limit'i ile DB'den okuma yapiyor. Mevcut WARNING akisi (saat
    tepesi 124, gun toplami >=129) 7 gun x 5000 sinirini delebilir.
    Limite degildiginde ozet kayar, eski kayitlar sessizce dusurulur ve
    kullanici bunu fark etmez.

    Duzeltme:
    - _fetch_events_from_db: len(rows) >= limit ise logger.warning
    - ErrorSummaryResponse: truncation_warning: str | None alani
    - get_error_summary: len(events) >= 5000 ise truncation_warning
      doldurulur
    - ErrorTracker.jsx: s.truncation_warning varsa sari banner gosterir

    Bu test 5 sozlesme noktasini regex ile dogrular."""
    ed_path = ROOT / "api" / "routes" / "error_dashboard.py"
    et_path = ROOT / "desktop" / "src" / "components" / "ErrorTracker.jsx"
    ed_src = ed_path.read_text(encoding="utf-8")
    et_src = et_path.read_text(encoding="utf-8")

    # 1. ErrorSummaryResponse schema'sinda truncation_warning alani
    assert re.search(
        r"class ErrorSummaryResponse\(BaseModel\):.*?truncation_warning\s*:\s*str\s*\|\s*None\s*=\s*None",
        ed_src,
        re.DOTALL,
    ), (
        "A25 (K3): ErrorSummaryResponse.truncation_warning alani eksik "
        "— banner kaynagi yok."
    )

    # 2. _fetch_events_from_db icinde truncation logger.warning
    fetch_match = re.search(
        r"def _fetch_events_from_db\(.*?\nreturn rows\n\s*except",
        ed_src,
        re.DOTALL,
    )
    # Daha esnek yakalama
    fetch_block_match = re.search(
        r"def _fetch_events_from_db\(.*?(?=\ndef |\Z)",
        ed_src,
        re.DOTALL,
    )
    assert fetch_block_match, "_fetch_events_from_db parse edilemedi"
    fetch_body = fetch_block_match.group(0)
    assert "len(rows) >= limit" in fetch_body, (
        "A25 (K3): _fetch_events_from_db truncation kontrolu "
        "(len(rows) >= limit) eksik."
    )
    assert "logger.warning" in fetch_body and "truncation" in fetch_body, (
        "A25 (K3): _fetch_events_from_db truncation logger.warning "
        "cagrisi eksik."
    )

    # 3. get_error_summary icinde truncation_warning hesaplama
    summary_match = re.search(
        r"async def get_error_summary\(.*?(?=\n@router|\ndef |\Z)",
        ed_src,
        re.DOTALL,
    )
    assert summary_match, "get_error_summary parse edilemedi"
    summary_body = summary_match.group(0)
    assert "truncation_warning" in summary_body, (
        "A25 (K3): get_error_summary truncation_warning yerel degiskeni "
        "yok."
    )
    assert "SUMMARY_EVENT_LIMIT" in summary_body, (
        "A25 (K3): get_error_summary SUMMARY_EVENT_LIMIT sabiti yok "
        "(magic number)."
    )
    assert re.search(
        r"len\(events\)\s*>=\s*SUMMARY_EVENT_LIMIT",
        summary_body,
    ), (
        "A25 (K3): get_error_summary truncation kontrol formulu eksik."
    )
    assert re.search(
        r"truncation_warning\s*=\s*truncation_warning",
        summary_body,
    ), (
        "A25 (K3): ErrorSummaryResponse kuruculugunda truncation_warning "
        "geciliyor mu kontrol edin."
    )

    # 4. Frontend banner — ErrorTracker.jsx
    assert "s.truncation_warning" in et_src, (
        "A25 (K3): ErrorTracker.jsx s.truncation_warning kosulu yok "
        "— banner render edilmiyor."
    )
    assert "error-truncation-banner" in et_src, (
        "A25 (K3): ErrorTracker.jsx error-truncation-banner className "
        "eksik (drift koruma anchor)."
    )

    # 5. A25 audit marker
    assert "A25" in ed_src, (
        "error_dashboard.py A25 audit markerin yok."
    )
    assert "A25" in et_src, (
        "ErrorTracker.jsx A25 audit markerin yok."
    )


# ── Flow 4zi: HybridTrade handleCheck/handleTransfer error handling (A24/K2) ──
def test_hybrid_trade_check_transfer_have_try_catch():
    """A24 (K2): HybridTrade.jsx::handleCheck ve handleTransfer eskiden
    try/catch'siz idi. checkHybridTransfer/transferToHybrid bir hata
    firlatirsa (network/500/timeout) setChecking(false)/setTransferring(false)
    hic cagrilmiyor, loading spinner sonsuza kadar donuyor ve kullanici
    hatadan haberdar olmuyordu — canli para uzerinde 'butonum donmus' UX
    hatasi.

    Duzeltme: Her iki fonksiyon try/catch/finally ile sarildi. Hata
    setErrorModal ile ConfirmModal'a basilir, loading state finally
    blogunda kapatilir.

    Bu test her iki useCallback blogunu statik parse eder ve try, catch,
    finally + setErrorModal cagrisinin varligini dogrular."""
    ht_path = ROOT / "desktop" / "src" / "components" / "HybridTrade.jsx"
    src = ht_path.read_text(encoding="utf-8")

    # 1. handleCheck blogu
    check_match = re.search(
        r"const handleCheck = useCallback\(\s*async \(\) => \{(.*?)\},\s*\[.*?\]\s*\);",
        src,
        re.DOTALL,
    )
    assert check_match, (
        "HybridTrade.jsx handleCheck useCallback bloku parse edilemedi."
    )
    check_body = check_match.group(1)
    assert "try {" in check_body, (
        "A24 (K2): handleCheck try blogu eksik — API hatasinda spinner "
        "donuk kalir, eski bug geri donmus."
    )
    assert "catch" in check_body, (
        "A24 (K2): handleCheck catch blogu eksik."
    )
    assert "finally" in check_body, (
        "A24 (K2): handleCheck finally blogu eksik — setChecking(false) "
        "exception path'inde cagrilmiyor olabilir."
    )
    assert "setErrorModal" in check_body, (
        "A24 (K2): handleCheck catch blogunda setErrorModal cagrisi yok "
        "— kullaniciya hata gosterilmeyecek."
    )
    assert "setChecking(false)" in check_body, (
        "A24 (K2): handleCheck finally blogunda setChecking(false) yok."
    )

    # 2. handleTransfer blogu
    transfer_match = re.search(
        r"const handleTransfer = useCallback\(\s*async \(\) => \{(.*?)\},\s*\[.*?\]\s*\);",
        src,
        re.DOTALL,
    )
    assert transfer_match, (
        "HybridTrade.jsx handleTransfer useCallback bloku parse edilemedi."
    )
    transfer_body = transfer_match.group(1)
    assert "try {" in transfer_body, (
        "A24 (K2): handleTransfer try blogu eksik — devir hatasinda "
        "spinner donuk kalir."
    )
    assert "catch" in transfer_body, (
        "A24 (K2): handleTransfer catch blogu eksik."
    )
    assert "finally" in transfer_body, (
        "A24 (K2): handleTransfer finally blogu eksik — "
        "setTransferring(false) exception path'inde cagrilmiyor olabilir."
    )
    assert "setErrorModal" in transfer_body, (
        "A24 (K2): handleTransfer catch blogunda setErrorModal cagrisi "
        "yok — kullaniciya devir hatasi gosterilmeyecek."
    )
    assert "setTransferring(false)" in transfer_body, (
        "A24 (K2): handleTransfer finally blogunda setTransferring(false) "
        "yok."
    )

    # 3. Audit marker
    assert "A24" in src, (
        "HybridTrade.jsx A24 audit markerin yok — regresyon takibi icin "
        "gerekli."
    )


# ── Flow 4zh: ManualTrade handleExecute stale closure fix (A23/K1) ──
def test_manual_trade_handle_execute_no_stale_closure():
    """A23 (K1): ManualTrade.jsx::handleExecute useCallback dependency
    array'i eksik idi — body'de sl/tp kullaniliyor ama dependency array
    [symbol, direction, lot, fetchRecentTrades] halinde sadece ilk 4
    degeri izliyordu. Sonuc: kullanici sl/tp degerini degistirip 5 saniye
    icinde 'Calistir'a basarsa eski (stale) sl/tp degeri MT5'e gidiyordu.
    Duzeltme: dependency array'e sl, tp, handleReset eklendi.

    Bu test handleExecute useCallback blogunu statik olarak parse eder
    ve dependency listesinde kritik state'lerin varligini dogrular."""
    mt_path = ROOT / "desktop" / "src" / "components" / "ManualTrade.jsx"
    src = mt_path.read_text(encoding="utf-8")

    # handleExecute useCallback blogu
    match = re.search(
        r"const handleExecute = useCallback\(\s*async \(\) => \{.*?\},\s*\[(.*?)\]\s*\);",
        src,
        re.DOTALL,
    )
    assert match, (
        "ManualTrade.jsx handleExecute useCallback bloku parse edilemedi "
        "— imza degismis olabilir."
    )
    deps_raw = match.group(1)
    deps = {d.strip() for d in deps_raw.split(",") if d.strip()}

    required = {"symbol", "direction", "lot", "sl", "tp", "fetchRecentTrades"}
    missing = required - deps
    assert not missing, (
        f"A23 (K1): handleExecute useCallback dependency array'inde "
        f"eksik state/fonksiyon: {sorted(missing)}. Eski bug geri dondu "
        f"— sl/tp degistirildikten sonra stale closure MT5'e eski "
        f"degeri gonderir."
    )

    # Audit marker
    assert "A23" in src, (
        "ManualTrade.jsx A23 audit markerin yok — regresyon takibi icin "
        "gerekli."
    )


# ── Flow 4zg: DATA_GAP gurultu azaltma (A28/K6) ──────────────────
def test_data_gap_noise_reduction():
    """A28 (K6): Ayarlar sayfasinda Sistem log ilk 5 kaydi hepsi
    'DATA_GAP WARNING' olarak gozukuyordu. Rutin piyasa-saati gap'leri
    recoverable gurultudur; severity INFO'ya dusurulmeli ve cooldown
    5 dakikadan 15 dakikaya cikarilmali. Gercek bayatlik
    check_data_freshness() icinde ayri WARNING loglar."""
    dp_path = ROOT / "engine" / "data_pipeline.py"
    dp_src = dp_path.read_text(encoding="utf-8")

    # 1. DATA_GAP DB event severity INFO olmali (WARNING degil)
    # _detect_gaps icindeki insert_event blogunu bul
    detect_gaps_match = re.search(
        r"def _detect_gaps.*?(?=\n    def |\nclass )",
        dp_src,
        re.DOTALL,
    )
    assert detect_gaps_match, "_detect_gaps fonksiyonu bulunamadi."
    detect_body = detect_gaps_match.group(0)

    assert 'event_type="DATA_GAP"' in detect_body, (
        "_detect_gaps icinde 'event_type=\"DATA_GAP\"' insert_event cagrisi "
        "yok — DB event kanali kirilmis."
    )
    # Severity INFO kontrolu (WARNING degil)
    gap_event_match = re.search(
        r'event_type="DATA_GAP".*?severity="(\w+)"',
        detect_body,
        re.DOTALL,
    )
    assert gap_event_match, (
        "DATA_GAP insert_event cagrisi severity parametresi bulunamadi."
    )
    severity = gap_event_match.group(1)
    assert severity == "INFO", (
        f"A28 (K6): DATA_GAP severity 'INFO' olmali, mevcut: '{severity}'. "
        "Rutin piyasa-saati gap'leri recoverable gurultudur; WARNING "
        "olarak kalirsa Sistem log ilk 5 kaydini doldurur."
    )

    # 2. Per-symbol cooldown 900 saniye (15 dakika) olmali
    # "> 900.0" throttle kontrolu
    assert (
        "> 900.0" in detect_body or "> 900" in detect_body
    ), (
        "A28 (K6): _detect_gaps per-symbol cooldown 900 saniye (15dk) "
        "olmali. Eski 300s degeri DATA_GAP gurultusunu azaltmiyordu."
    )
    # dedup_seconds=900 da kontrol (insert_event dedup)
    assert "dedup_seconds=900" in detect_body, (
        "A28 (K6): insert_event dedup_seconds=900 olmali (15 dakika). "
        "Eski 300 degeri per-symbol dedup araligini dar tutuyordu."
    )

    # 3. Audit marker
    assert "A28" in dp_src, (
        "data_pipeline.py icinde A28 audit markerin yok — regresyon "
        "takibi icin gerekli."
    )

    # 4. check_data_freshness hala STALE icin WARNING loglamali
    # (rutin gap'ler INFO'ya inerken gercek bayatlik WARNING kalir)
    freshness_match = re.search(
        r"def check_data_freshness.*?(?=\n    def |\nclass )",
        dp_src,
        re.DOTALL,
    )
    assert freshness_match, "check_data_freshness fonksiyonu bulunamadi."
    freshness_body = freshness_match.group(0)
    assert "logger.warning" in freshness_body, (
        "check_data_freshness STALE durumunda WARNING loglamali — "
        "gercek bayatlik tespiti gorunur kalmali."
    )


# ── Flow 4zl: RiskManagement lot tier badge + banner (A13/H17) ──
def test_risk_management_lot_tier_badge_and_banner():
    """Widget Denetimi A13 (H17): Risk sayfasinda `lot_multiplier`
    sayisal cikti olarak gosteriliyordu ama operatore "lot neden dustu"
    sorusunun cevabi yoktu — graduated lot, haftalik kayip, OLAY rejimi
    veya kill-switch hangi katmanin lotu indirdiginin gorunurlugu yoktu.

    Cozum (frontend-only, Yesil Bolge):
    - getLotTier(mult) helper: Normal/Yarim/Ceyrek/Asgari/Iptal tier'larini
      lot_multiplier degerine gore donduyor.
    - Lot Carpani kartina rozet (`risk-lot-tier-badge`) eklendi.
    - lot_multiplier < 0.99 oldugunda altta `risk-lot-banner` aciklayici
      banner cikiyor (risk_reason ile birlikte).
    - CSS theme.css'te tier sinifi varyantlari + banner stilleri.

    Bu test 5 sozlesme noktasini regex ile dogrular."""
    rm_path = ROOT / "desktop" / "src" / "components" / "RiskManagement.jsx"
    css_path = ROOT / "desktop" / "src" / "styles" / "theme.css"
    assert rm_path.exists(), "RiskManagement.jsx bulunamadi"
    assert css_path.exists(), "theme.css bulunamadi"
    rm_src = rm_path.read_text(encoding="utf-8")
    css_src = css_path.read_text(encoding="utf-8")

    # 1) getLotTier helper fonksiyonu
    assert "function getLotTier" in rm_src, (
        "A13 (H17): RiskManagement.jsx icinde `getLotTier` helper "
        "fonksiyonu yok — tier hesaplama tek noktada degil."
    )
    # Tier label'lari
    for label in ("Normal Lot", "Yarım Lot", "Çeyrek Lot", "Lot İptal"):
        assert label in rm_src, (
            f"A13 (H17): getLotTier '{label}' label'i eksik."
        )

    # 2) Tier rozeti render'i
    assert "risk-lot-tier-badge" in rm_src, (
        "A13 (H17): RiskManagement.jsx icinde `risk-lot-tier-badge` "
        "className kullanilmiyor — rozet render edilmiyor."
    )
    assert re.search(
        r"const\s+lotTier\s*=\s*getLotTier\(\s*risk\.lot_multiplier",
        rm_src,
    ), (
        "A13 (H17): `lotTier = getLotTier(risk.lot_multiplier)` cagrisi "
        "render fonksiyonunda yok."
    )

    # 3) Lot azaltma banner'i
    assert "risk-lot-banner" in rm_src, (
        "A13 (H17): RiskManagement.jsx icinde `risk-lot-banner` className "
        "yok — lot azaltma banner'i render edilmiyor."
    )
    assert re.search(
        r"\{\s*lotReduced\s*&&", rm_src
    ), (
        "A13 (H17): `{lotReduced && (...)}` kosullu render bloku eksik — "
        "banner sadece lot < 1.0 iken cikmali."
    )

    # 4) CSS'te tier varyantlari + banner sinifi
    for cls in (
        "lot-tier-normal",
        "lot-tier-half",
        "lot-tier-quarter",
        "lot-tier-min",
        "lot-tier-blocked",
        "risk-lot-banner",
    ):
        assert cls in css_src, (
            f"A13 (H17): theme.css icinde `{cls}` CSS sinifi yok — "
            "tier rengi/banner stili eksik."
        )

    # 5) A13 audit markerlari
    assert "A13" in rm_src, (
        "A13 (H17): RiskManagement.jsx icinde 'A13' audit markerin yok."
    )
    assert "A13" in css_src, (
        "A13 (H17): theme.css icinde 'A13' audit markerin yok."
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
    # archive/, tests/, .agent/, desktop/scripts/, .claude/ tum test/archive/worktree dosyalari atlanacak
    skip_prefixes = ("archive/", "tests/", ".agent/", "desktop/scripts/", ".claude/")

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
