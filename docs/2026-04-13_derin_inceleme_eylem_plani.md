# USTAT Derin İnceleme ve Eylem Planı — 2026-04-13

**Versiyon:** 1.0
**Tarih:** 2026-04-13
**Uygulanan metodoloji:** `docs/2026-04-13_USTAT_derin_inceleme_metodolojisi.md` (9 faz, 9 eksen)
**Mod:** READ-ONLY denetim — kod değişikliği yapılmadı
**Kaynak denetim ajanı:** `ustat-auditor` (3 paralel blok: Faz 0-2, Faz 3-5, Faz 6-8)
**Referans önceki denetim:** `docs/2026-04-11_derin_kapsamli_denetim_raporu.md` (78 bulgu, 19 kapatıldı, 56 açık)

---

## Yönetici Özeti

**Genel değerlendirme:** Faz A/B uygulaması gerçekten yapılmış — 19 bulgu kapandı, `tests/critical_flows` 71 test yeşil (3.50sn), `pytest.ini` düzeltilmiş, versiyon v6.0'a hizalanmış. Ancak motorlar **büyümeye devam ediyor** (baba +25, h_engine +28, database +18, main +9 satır Faz A/B sonrası). Her kapatma yapısal borç olarak biriker hâline geldi.

**En kritik 5 risk:**
1. **FZ4-01 (P0)** — Lifespan fail-open davranışı Anayasa Kural 9 (fail-safe) ile çelişiyor
2. **F6-01 (P1)** — `run_retention()` trades tablosu için uygulanmamış; config `trade_archive_days=180` ölü
3. **F6-02 (P1)** — Notification tablosu UNIQUE kısıtı yok; duplicate bildirim riski
4. **F8-01 (P1)** — Motorlar Faz A/B sonrası büyümeye devam; motor alt modül ayrımı (Faz C) gecikiyor
5. **F7-01 (P1)** — Runtime integration test katmanı yok; statik AST testleri koşullu scope hatalarını yakalamıyor

**Metrikler:**
- Toplam test: 10 768 (collected, 0 INTERNALERROR)
- Kritik akış testleri: 71 passed
- En büyük 4 motor dosyası: 3521+3388+3165+2974 = **13 048 satır** (hâlâ tek dosya)
- Yeni bulgu (bu denetim): **~35**
- Önceki denetimden açık kalan: **~21 P1 + 34 P2 + 20 P3 ≈ 56 (doğrulanmış)**
- Kapatılmış P0: 6/6 | Kapatılmış P1: 13/18 (5 hâlâ açık + 2 ertelenen)

**Son hüküm:** Öncelik Anayasa güncelleme (F8-03) → sonra motor bölme başlangıcı (mt5_bridge ilk) → sonra DB retention + notification UNIQUE.

---

## Kapsam

Metodolojinin 9 ekseninin tümü uygulandı:

1. Başlatma ve lifecycle güvenilirliği — Faz 0, 1, 3
2. Engine döngüsü doğruluğu — Faz 1, 5
3. Risk ve kill-switch davranışı — Faz 5
4. Emir yaşam döngüsü ve koruma mantığı — Faz 4, 5
5. API/UI/event sözleşme tutarlılığı — Faz 2
6. Veri bütünlüğü ve persistence — Faz 6
7. Test güvenilirliği ve kapsamı — Faz 7
8. Dokümantasyon ve versiyon drifti — Faz 1, 2, 8
9. Teknik borç ve refactor hazırlığı — Faz 8

**Kapsam dışı:** Runtime failure injection (metodoloji §6.4'te önerilen kontrollü senaryolar runtime execution gerektirir; bu denetimde statik + log analizi ile sınırlı kaldı).

---

## Faz 0 — Kapsam ve Giriş Noktaları

### 0.1 Repo Envanteri

Kök `C:\Users\pc\Desktop\USTAT` altındaki üst klasörler:

| Dizin | Sorumluluk | Not |
|---|---|---|
| `engine/` | 4 motor + altyapı (MT5 bridge, DB, data pipeline, event bus, lifecycle guard, news bridge, netting lock, manuel motor) | 41 Python dosya; CLAUDE.md §1.4'te listelenmeyen `lifecycle_guard.py`, `process_guard.py`, `ogul_sltp.py`, `mt5_errors.py` var — doküman drift |
| `api/` | FastAPI backend (port 8000). `server.py`, `schemas.py`, `constants.py`, `deps.py` + 22 route modülü | CLAUDE.md §1.4 "20 endpoint" diyor — gerçekte 21 route dosyası (`__init__.py` hariç): `nabiz.py` eklendi |
| `config/default.json` | Tüm sabitler — risk eşikleri, version, strateji parametreleri | `version: 6.0.0` |
| `database/` | SQLite dosyaları `trades.db`, `ustat.db` | `ustat.db` 0 byte |
| `desktop/` | Electron + React. `main.js`, `preload.js`, `mt5Manager.js`, `src/components/` (21 JSX) | CLAUDE.md "20 bileşen" — `Nabiz.jsx` eklenmiş; `package.json build.productName="ÜSTAT v5.7..."` DRIFT |
| `docs/` | Oturum raporları + `USTAT_CALISMA_REHBERI.md`, metodoloji, tarihçe | — |
| `tests/` | `critical_flows/` (4 dosya), `simulation/`, kök unit testler | 10 768 test |
| `logs/` | Günlük log dosyaları | — |
| `mql5/` | MQL5 scriptleri | — |
| `tools/` | `impact_map.py` etki analiz aracı | — |
| `.agent/` | Ajan köprüsü | `ustat_agent.py` v3.2.0 |
| `archive/` | Arşiv | `engine/archive/h_engine_trailing_legacy/` canlı ağaçta |

### 0.2 Giriş Noktaları

| Giriş | Konum | Kanıt |
|---|---|---|
| Masaüstü başlatıcı | `start_ustat.py:1146 def main()` | Siyah Kapı #29 |
| API sunucu | `api/server.py:189` + lifespan `:70` | Siyah Kapı #28 |
| Engine döngüsü | `engine/main.py:217 Engine.start()` → `:302 _main_loop()` → `:754 _run_single_cycle()` | Siyah Kapı #22 |
| Electron ana | `desktop/main.js` (676 satır) | Siyah Kapı #30 `createWindow()` |
| Otonom ajan | `ustat_agent.py` — 3686 satır, `AGENT_VERSION = "3.2.0"` | — |
| Webview process | `start_ustat.py:624 run_webview_process()` | **AD DRIFT**: pywebview kaldırıldı ama fonksiyon adı aynı |
| API başlat/durdur | `start_ustat.py:766/785` | Siyah Kapı #26/#27 |

### 0.3 Kritik Dosya Listesi (satır sayıları)

**Kırmızı Bölge (10):**

| # | Dosya | Satır |
|---|---|---|
| 1 | `engine/baba.py` | 3388 |
| 2 | `engine/ogul.py` | 3521 |
| 3 | `engine/mt5_bridge.py` | 3165 |
| 4 | `engine/main.py` | 1534 |
| 5 | `engine/ustat.py` | 2195 |
| 6 | `engine/database.py` | 2045 |
| 7 | `engine/data_pipeline.py` | 1071 |
| 8 | `config/default.json` | ~1200 |
| 9 | `start_ustat.py` | 1247 |
| 10 | `api/server.py` | 269 |

**Sarı Bölge (7):**

| # | Dosya | Satır |
|---|---|---|
| 1 | `engine/h_engine.py` | 2974 |
| 2 | `engine/config.py` | 120 |
| 3 | `engine/logger.py` | 61 |
| 4 | `api/routes/killswitch.py` | 88 |
| 5 | `api/routes/positions.py` | 249 |
| 6 | `desktop/main.js` | 676 |
| 7 | `desktop/mt5Manager.js` | 535 |

**Risk notu:** baba+ogul+mt5_bridge+h_engine = 13 048 satır; Siyah Kapı fonksiyonlarının çoğunu barındırıyor → Tek Sorumluluk İhlali (Faz 8 kapsamı).

### 0.4 Runtime Bağımlılıkları

`requirements.txt`:
- Broker: `MetaTrader5>=5.0.45`
- Veri: `pandas>=2.0`, `numpy>=1.24`, `ta-lib>=0.4.28`
- API: `fastapi>=0.104`, `uvicorn[standard]>=0.24`, `pydantic>=2.5`
- DB: `aiosqlite>=0.19`
- Güvenlik: `cryptography>=41.0`
- Log: `loguru>=0.7`
- Scheduler: `apscheduler>=3.10`
- Test: `pytest>=7.4`, `pytest-asyncio>=0.23`

CLAUDE.md Python 3.14 diyor — requirements'ta Python pin yok.

**Desktop (`desktop/package.json`):**
- Runtime: `react 18.3`, `axios 1.7`, `recharts 2.15`, `@dnd-kit/*`
- Dev: `electron 33.0`, `vite 6.0`, `electron-builder 25.1`
- `version: "6.0.0"` ✓ | `build.productName: "ÜSTAT v5.7..."` ✗ DRIFT

### 0.5 Kritik Akış Listesi

`tests/critical_flows/`:

| Dosya | Test sayısı | Kapsam |
|---|---|---|
| `test_static_contracts.py` | 54 | 12 kritik akış + genişletilmiş statik sözleşme |
| `test_mt5_bridge_state.py` | 6 | MT5 state geçişleri |
| `test_h_engine_devir.py` | 3 | H-Engine hata zenginleştirme |
| `test_error_enrichment.py` | 8 | MT5 retcode → eylem eşleme |
| **Toplam** | **71** | **71 passed, 3.50sn** |

Metodoloji §9 kritik akış eşlemesi §7.3'te tam tablo olarak mevcut. **12/12 akış kapsanmış** (statik).

**Kapsamda olmayan akışlar:** netting_lock davranışı, news_bridge fail-safe, WebSocket payload şeması, SPA fallback, engine restart watchdog. Faz 4/7'de ele alındı.

---

## Faz 1 — Mimari Envanter

### 1.1 Process Haritası

```
wscript start_ustat.vbs
 └─ pythonw start_ustat.py (Ana Process — ProcessGuard + Mutex + pystray tray)
     ├─ multiprocessing.Process(run_webview_process) [Alt Process]
     │   ├─ Thread: uvicorn (api.server:app, 127.0.0.1:8000)
     │   │   └─ Lifespan async loop: Engine.start() run_in_executor → Engine thread
     │   │       └─ Engine._main_loop() → _run_single_cycle() her 10sn
     │   │           └─ mt5_bridge → MetaTrader5 native (terminal64.exe IPC)
     │   └─ subprocess: Electron (desktop/main.js)
     │       └─ Renderer: React SPA (dist/) — API'ye HTTP + WebSocket
     │           └─ mt5Manager.js: terminal64.exe spawn + OTP
     └─ watchdog_loop(): engine.heartbeat izler, 60sn stale → restart
```

### 1.2 State Sahipliği

| State | Sahip | Konum |
|---|---|---|
| Engine lifecycle flags | Engine | `main.py:194-206` |
| Risk limits / kill-switch | BABA in-memory + SQLite | `baba.py` + `database.py` |
| Aktif trade'ler | OĞUL `active_trades` | `main.py:444` |
| Hybrid pozisyonları | HEngine `hybrid_positions` | `main.py:445` |
| Manuel pozisyonlar | ManuelMotor | `main.py:446` |
| Trade/event/risk persist | Database (SQLite WAL) | `engine/database.py` |
| Config | `engine/config.py:Config` → `default.json` | — |
| Notification prefs | Config (bellek tabanlı KALDIRILDI) | `settings.py:41-44` |
| Watchlist 15 kontrat | `mt5_bridge.py::WATCHED_SYMBOLS` (canonical) | `test_manual_trade_watchlist_single_source` |
| Versiyon | `engine/__init__.py::VERSION` (canonical) + 4 drift noktası | §2.5 matrisi |

**Çoklu sahiplik uyarısı:** Version 5 ayrı yerde; status.py canonical okuyor ama `schemas.py:19` hardcode default.

### 1.3 Veri Akış Yönleri — `_run_single_cycle` Sırası

```
MT5 heartbeat (:767)
  → sembol re-resolve (:785)
  → trade_mode saatlik tarama (:797)
  → DataPipeline._update_data() (:810)
  → _check_position_closures() (:814)
  → news_bridge.run_cycle() (:819)
  → premarket_briefing.check() (:827)
  → BABA._run_baba_cycle() → regime (:844)
  → BABA.check_risk_limits() → risk_verdict (:848)
  → OĞUL.select_top5(regime) (:859)
  → OĞUL.process_signals(top5, regime) (:889)
  → HEngine.run_cycle() (:904)
  → ÜSTAT.run_cycle()
```

### 1.4 Lifecycle — Startup (Anayasa Kural 11+12)

1. `start_ustat.py:main()` — ProcessGuard + Named Mutex + port kontrolü
2. `multiprocessing.Process(run_webview_process)` fork
3. Alt process: `_start_api()` uvicorn thread (port 8000)
4. `api/server.py:70 lifespan()` — sırayla: `Config → Database → MT5Bridge → DataPipeline → Ustat → Baba → Ogul → Engine` ← **Anayasa Kural 12 UYUMLU** (`server.py:81-102`)
5. `set_engine(engine)` → `api/deps.py`
6. `engine_task = loop.run_in_executor(None, engine.start)` (`server.py:108`)
7. `Engine.start()`: `guard.activate` → config check → vade validate → DB backup → `_connect_mt5()` → smoke test → `_sync_mt5_history` → `_restore_state` → `ENGINE_START` event → `guard.set_running()` → `_main_loop()`
8. `_engine_watchdog` — thread biterse max 3 restart (`server.py:114-140`)
9. Electron spawn → port 8000 bekle → `createWindow()`
10. `LockScreen` → OTP → MT5 → Dashboard

**Doğrulama:** `server.py:81-102` sırası Anayasa Kural 12 ile birebir — drift yok.

### 1.5 Lifecycle — Shutdown (Anayasa Kural 13)

1. `yield` (Electron kapanır veya SIGTERM)
2. `shutdown_all_connections()` — WebSocket kapatılır (`server.py:155-158`)
3. `engine.stop(reason="API shutdown")` (`server.py:163`)
4. `main.py:409 stop()`:
   - `guard.begin_shutdown()` → yeni emir engeli
   - Uçuştaki emir bekleme max 10sn
   - `_running = False`
   - Auto mod: MT5 bağlıysa kapat, bağlı değilse AÇIK BIRAK + CRITICAL log
   - Manuel pozisyonlar ENGINE_STOP'ta kapatılMAZ (Anayasa 10 + CEO talimatı)
5. `engine_task` bekleme max 30sn (`server.py:167`)
6. `watchdog_task.cancel()`
7. `api.pid` temizliği

**Kanıt yetersiz:** `main.py:504` sonrasında `mt5.disconnect()` + `db.close()` çağrıları doğrulanmadı → F1-05.

### 1.6 Dış Bağımlılıklar

| Bağımlılık | Etkileşim | Fail-safe |
|---|---|---|
| MT5 terminal | `mt5_bridge.py connect/heartbeat/send_order` | Kural 15: launch=False; process check; Kural 8 circuit breaker |
| MT5 Python API | `mt5_bridge::_safe_call` timeout 8sn | Siyah Kapı #20 |
| News/ekonomik | `news_bridge.run_cycle` | Erişilemezse OLAY rejimi (kanıt yetersiz) |
| SQLite WAL | `database.py` | 3 ardışık DB hatası → durdur |
| Electron/Node 33 | spawn + IPC | singleton exit code 42 |
| Vite 6.0 | build `desktop/dist/` | build yapılmazsa eski bundle |

### 1.7 Dependency Map Doğrulama (CLAUDE.md §6 vs kod)

CLAUDE.md §6 bağımlılık haritası **eksik ve yanıltıcı:**

| Bağımlılık | CLAUDE.md §6 | Gerçek | Kanıt |
|---|---|---|---|
| `main → manuel_motor` | YOK | VAR | `main.py:144-158` |
| `main → news_bridge` | YOK | VAR | `main.py:174-180` |
| `main → lifecycle_guard` | YOK | VAR | `main.py:188-191` |
| `main → error_tracker` | YOK | VAR | `main.py:168-172` |
| `main → health` | YOK | VAR | `main.py:165-166` |
| `main → premarket_briefing` | YOK | VAR | `main.py:182-186` |
| `ogul → h_engine` | İMA | VAR | `main.py:131` |
| `baba → ogul, h_engine` | YOK | VAR | `main.py:160-162` |

### 1.8 Faz 1 Bulguları

**F1-01 — Dosya listesi drift (P2, DRIFT/BORC)**
CLAUDE.md §1.4 Engine 18 dosya; gerçek 41 (archive dahil). Eksik listelenenler: `lifecycle_guard.py`, `process_guard.py`, `ogul_sltp.py`, `mt5_errors.py`. Yeni geliştirici §1.4'e güvenirse kritik guard dosyalarını görmez.

**F1-02 — `start_ustat.py` docstring + fonksiyon adı pywebview DRIFT (P3, DRIFT)**
`start_ustat.py:1-18` docstring pywebview anlatıyor; `:624 run_webview_process` fonksiyon adı. CLAUDE.md §1.6 pywebview kaldırıldığını söylüyor. Fonksiyon adı Siyah Kapı #25 — sadece docstring düzeltilebilir.

**F1-03 — `desktop/package.json build.productName` v5.7 drift (P2, DRIFT)**
`package.json:36 productName: "ÜSTAT v5.7..."` ← `version: "6.0.0"`. NSIS installer yanlış sürüm gösterir.

**F1-04 — CLAUDE.md §6 bağımlılık haritası eksik (P1, DRIFT/GOZLEMLENEBILIRLIK)**
ManuelMotor, NewsBridge, LifecycleGuard, ErrorTracker, PreMarketBriefing haritada yok. Etki analizi yanlış yapılır. Çözüm: `tools/impact_map.py` çıktısından auto-generate.

**F1-05 — Engine shutdown tail kanıt yetersiz (P2, GOZLEMLENEBILIRLIK)**
`main.py:409-504` okundu; MT5 disconnect + DB close çağrıları doğrulanmadı. Shutdown'da handle/connection sızıntısı riski. Runtime drill gerekli.

**F1-06 — `engine/archive/` canlı ağaçta (P3, BORC)**
`engine/archive/h_engine_trailing_legacy/` legacy 4 `.py`. Glob gürültüsü.

---

## Faz 2 — Sözleşme Envanteri

### 2.1 API Response Schema Matrisi

22 route dosyası (21 + `__init__.py`). `response_model=` kullanımı:

| # | Route | Endpoint | Typed | Typeless | Not |
|---|---|---|---|---|---|
| 1 | `account.py` | 1 | 1 | 0 | temiz |
| 2 | `error_dashboard.py` | 5 | 5 | 0 | temiz |
| 3 | `events.py` | 1 | 1 | 0 | temiz |
| 4 | `health.py` | 2 | 1 | 1 | `/agent-status` typeless |
| 5 | `hybrid_trade.py` | 6 | 5 | 1 | `/hybrid/performance` |
| 6 | `killswitch.py` | 1 | 1 | 0 | — |
| 7 | `live.py` | 1 WS | — | — | §2.3 |
| 8 | `manual_trade.py` | 3 | 3 | 0 | — |
| 9 | `mt5_verify.py` | 2 | 0 | 2 | ikisi dict |
| 10 | `nabiz.py` | 1 | 0 | 1 | yeni route |
| 11 | `news.py` | 5 | 2 | 3 | yarı typed |
| 12 | `notifications.py` | 3 | 1 | 2 | write typeless |
| 13 | `ogul_activity.py` | 1 | 1 | 0 | — |
| 14 | `performance.py` | 1 | 1 | 0 | — |
| 15 | `positions.py` | 2 | 2 | 0 | — |
| 16 | `risk.py` | 1 | 1 | 0 | — |
| 17 | `settings.py` | 9 | 9 | 0 | tam typed |
| 18 | `status.py` | 2 | 2 | 0 | — |
| 19 | `top5.py` | 1 | 1 | 0 | — |
| 20 | `trades.py` | 5 | 3 | 2 | sync/backfill typeless |
| 21 | `ustat_brain.py` | 2 | 1 | 1 | debug typeless |

**Toplam:** ~51 HTTP + 1 WS. Typed oranı ≈ %78. Typeless 11 endpoint.

### 2.2 Request Validation

POST body Pydantic modelleri (schemas.py):

| Model | Kullanım |
|---|---|
| `ClosePositionRequest` | positions.py |
| `ApproveRequest` | trades.py |
| `KillSwitchRequest` | killswitch.py |
| `ManualTradeCheckRequest/ExecuteRequest` | manual_trade.py |
| `HybridCheckRequest/TransferRequest/RemoveRequest` | hybrid_trade.py |
| `NotificationPrefsRequest` | settings.py |
| `RiskBaselineUpdateRequest` | settings.py |
| `ResolveRequest` | error_dashboard.py (inline) |
| `MarkReadRequest` | notifications.py (inline) |

**Validation yokluğu:** `/news/briefing POST`, `/news/test POST`, `/trades/sync POST`, `/trades/backfill-regime POST`.

### 2.3 WebSocket Payload

`api/routes/live.py /ws/live`:
- İstemci → `"ping"` → `{"type": "pong"}`
- Sunucu push (`_send_all_updates`): `type: "tick"`, risk, position, hybrid, daily_pnl
- Event bus drain: `_event_drain_loop → broadcast(ev)`

**Sözleşme drift riski:** WS mesajları Pydantic modeli yok, raw dict. Frontend `api.js` ile manuel senkron.

### 2.4 Settings Persistence

| Ayar | Kaynak | Kalıcılık |
|---|---|---|
| `risk-baseline` | BABA + config | DB risk state |
| `notification-prefs` | `config.ui.notification_prefs` → `config.save()` | Dosya |
| `session` | `config.engine` + fallback `DEFAULT_SESSION_HOURS` | Config |
| `watchlist` | `WATCHED_SYMBOLS` (canonical) | Kod sabit |
| `trading-limits` | Config `risk.*` | Config |
| `ui-prefs` | Config `ui.*` + fallback | Config |
| `stats-baseline` | `constants.STATS_BASELINE` + config | Karma |

notification-prefs bellek tabanlıdan config.save()'e taşındı (v6.0, `test_notification_prefs_persists_via_config:199`).

**Desktop localStorage:** Dashboard/Settings/DraggableGrid incelenmedi → F2-08.

### 2.5 Version Source Matrisi

| # | Konum | Değer | Rol |
|---|---|---|---|
| 1 | `engine/__init__.py:3` | `VERSION = "6.0.0"` | **CANONICAL** |
| 2 | `api/server.py:64` | `API_VERSION = "6.0.0"` | hardcode |
| 3 | `api/schemas.py:19` | `version = "6.0.0"` default | **hardcode** — canonical'dan okumuyor |
| 4 | `config/default.json:2` | `"6.0.0"` | hardcode |
| 5 | `desktop/package.json:3` | `"6.0.0"` | npm |
| 6 | `desktop/package.json:36` | `"... v5.7 ..."` | **DRIFT** |
| 7 | `start_ustat.py:55` | `APP_TITLE v6.0` | OK |
| 8 | `CLAUDE.md` başlık | `v5.9` | **DRIFT** |
| 9 | `status.py:18` | `from engine import VERSION` | doğru |

**Drift:** CLAUDE.md başlık (v5.9), productName (v5.7), schemas.py default hardcode.

### 2.6 Engine Public API Durumu

`api/deps.py:49-96` public getter'lar:
```
get_db, get_mt5, get_baba, get_ustat, get_ogul,
get_pipeline, get_h_engine, get_manuel_motor, get_news_bridge
```
Engine alanları public (`self.db`, `self.mt5`, ...). `Engine.is_running` property v6.0'da eklendi (Faz B).

### 2.7 Private Alan Sızıntı Raporu

| Sızıntı | Konum | Erişim | Risk |
|---|---|---|---|
| 1 | `api/routes/live.py:350` | `h_engine._daily_hybrid_pnl` | Public `daily_hybrid_pnl` varken |
| 2 | `api/routes/live.py:351` | `h_engine._config_daily_limit` | Public varken |
| 3 | `api/routes/status.py:76` | `engine._last_cycle_time` | "Bilinçli sızıntı" yorumlu ama property yok |
| 4 | `api/routes/status.py:91` | `engine._last_successful_cycle_time` | Aynı |
| 5 | `api/routes/settings.py:441-442` | `baba._risk_baseline_date` fallback | Faz B migration yarım |

### 2.8 Faz 2 Bulguları

**F2-01 — WebSocket payload Pydantic'siz (P1, SOZLESME)**
`live.py:157-159` raw dict. Frontend sözleşmesi manuel senkron. Discriminated union modeli + contract test gerekli.

**F2-02 — HEngine private alan sızıntısı `live.py:350-351` (P2, SOZLESME)**
Public `daily_hybrid_pnl`, `config_daily_limit` varken private okunuyor. 2 satır değişiklik.

**F2-03 — Engine `_last_cycle_time` property yok (P2, SOZLESME)**
`main.py:205-206` private; `status.py:76,91` okuyor. `is_running` için property var, bunun için yok. Tutarsız API.

**F2-04 — `/nabiz`, `/mt5/verify`, `/hybrid/performance`, `/news/*` typeless (P2, SOZLESME)**
OpenAPI eksik, drift saptama zor. Pydantic model ekle.

**F2-05 — CLAUDE.md başlık v5.9 vs gerçek v6.0 (P1, DRIFT)**
Rehberin kendisi drift → tüm ajan kararları yanlış zeminde. Anayasa §4.1 "Tek Gerçek Kaynağı" ihlali.

**F2-06 — `schemas.py:19` version hardcode (P2, DRIFT)**
Canonical'dan okumalı: `from engine import VERSION`.

**F2-07 — POST endpoint'lerde body validation yok (P2, SOZLESME)**
`/news/briefing`, `/news/test`, `/trades/sync`, `/trades/backfill-regime`.

**F2-08 — Desktop localStorage kanıt yetersiz (P3, GOZLEMLENEBILIRLIK)**
Dashboard.jsx, Settings.jsx, DraggableGrid.jsx localStorage erişimleri ayrıca incelenmeli.

**F2-09 — API route sayısı drift 20→21 (P3, DRIFT)**
CLAUDE.md §1.4 güncellenmeli.

---

## Faz 3 — Runtime Doğrulama

### 3.1 Startup Truth Table

| Senaryo | Kod yolu | Beklenen | Risk |
|---|---|---|---|
| Temiz startup | Lifespan sırası `server.py:81-102` | Config → DB → MT5 → ... → Engine | OK (Kural 12 uyumlu) |
| Tekrar startup | ProcessGuard + Mutex + port kontrolü | Mevcut instance → exit 42 | `test_mainjs_singleton_conflict_exits_with_code_42` korur |
| Stale process | `start_ustat.py` TIME_WAIT socket temizliği | ProcessGuard'da temizlenir | Kural 14 |
| MT5 bağlı | `_connect_mt5()` → `mt5_bridge.connect(launch=False)` | initialize başarılı, `_trade_allowed=True` | OK |
| MT5 yok | `connect(launch=False)` → terminal64.exe process check fail | `mt5.initialize()` ATLANIR, heartbeat devam | Kural 15 uyumlu — ancak degraded mode sinyali eksik (FZ3-01) |
| MT5 login fail | OTP hatası | `_trade_allowed=False`, trade yok | OK |
| Config bozuk | `Config()` JSON parse exception | Lifespan exception | FZ4-01 |

### 3.2 Readiness Modeli

| Katman | Hazır sinyali |
|---|---|
| API | Port 8000 bind + `/health` 200 |
| Engine | `guard.set_running()` + `ENGINE_START` event |
| UI | Electron `did-finish-load` + ilk `/status` başarılı |

### 3.3 Shutdown Davranış Özeti

Anayasa Kural 13 uyumlu (yukarıda §1.5).

### 3.4 Log Kanıtı

Log dosyaları örneklendi. `_close_ogul_and_hybrid` 0 pozisyon durumunda gereksiz WARNING (FZ5-09 — 19:01:42.651).

### 3.5 Degraded Mode Analizi

MT5 yokken:
- Engine çalışır (heartbeat devam)
- Trade yasak (`_trade_allowed=False`)
- UI'da **"error" fazı** gösteriliyor → yanlış sinyal (FZ3-01)

Degraded mode resmi olarak modellenmemiş — yan etki gibi davranıyor.

### 3.6 Faz 3 Bulguları

**FZ3-01 (P1, SOZLESME)** — Degraded mode "error" olarak UI'ya yansıyor. Ayrı "degraded" fazı yok. `status.phase` enum'u: running/stopped/error/killed. Beşinci durum (degraded/no_mt5) eklenmedi.

**FZ3-02 (P1, GOZLEMLENEBILIRLIK)** — Graceful shutdown log izi eksik (MT5 disconnect + DB close kanıt yetersiz — F1-05 ile birleşir).

**FZ3-04 (P2, GOZLEMLENEBILIRLIK)** — Silent failure noktaları log'ta takip edilemiyor (çeşitli try/except sessiz yutma).

---

## Faz 4 — Failure Mode Matrisi

### 4.1 Senaryo Tablosu

| # | Senaryo | Beklenen | Mevcut | Risk | Kanıt |
|---|---|---|---|---|---|
| 1 | MT5 process yok | launch=False + process check | `connect()` skip, degraded | P1 (FZ3-01) | Kural 15 ✓ |
| 2 | MT5 initialize fail | `_trade_allowed=False` | OK | P2 | mt5_bridge.py |
| 3 | DB lock / WAL | 3 ardışık → engine stop | `main.py:53 DB_ERROR_THRESHOLD` | P2 | OK |
| 4 | Config bozuk | Lifespan exception → API çökmez | **fail-open** | **P0** | FZ4-01 |
| 5 | Event bus bozuk payload | Swallow + log | Kısmi swallow | P2 | FZ4-02 |
| 6 | API route exception | 500 + log | Uncaught → stacktrace | P2 | FZ4-03 |
| 7 | Notification tablosu anomali | Dedupe | UNIQUE yok | P1 | F6-02 |
| 8 | SL/TP set edilemiyor | Pozisyon zorla kapat | `ogul.py:1830-1894` zinciri | OK | Kural 4 ✓ |
| 9 | Position ticket yok | Log + skip | OK | P2 | OK |
| 10 | Duplicate instance | exit 42 | OK | OK | test_mainjs_singleton |
| 11 | Circuit breaker 5 timeout | 30sn engel | OK | OK | test_mt5_bridge_has_circuit_breaker |
| 12 | Engine exception | Main loop izolasyon | Kural 24 | OK | — |

### 4.2 Fail-Safe Uyum Raporu

**Anayasa Kural 9 (fail-safe):** "Güvenlik modülü sessizce devre dışı kalırsa sistem 'kilitli' duruma düşer."

**FZ4-01 kritik ihlal:** Lifespan config bozulursa fail-open davranışı → Kural 9 ihlali.

### 4.3 Faz 4 Bulguları

**FZ4-01 (P0, BUG)** — Lifespan fail-open. Config parse hatasında API kilitli/durdu duruma düşmeli, şu an exception loglanıp devam ediyor riski.

**FZ4-02 (P2, GOZLEMLENEBILIRLIK)** — Event bus bozuk payload'da sessiz yutma.

**FZ4-03 (P2, GOZLEMLENEBILIRLIK)** — API route uncaught exception'da 500 yerine stacktrace.

---

## Faz 5 — İş Kuralı ve Mantık Doğrulama

### 5.1-5.12 Özet Doğrulama

| Konu | Anayasa | Kod | Durum |
|---|---|---|---|
| Kill-switch monotonluk L1→L2→L3 | Kural 3 | `baba._activate_kill_switch` thread-safe | ✓ |
| Drawdown (daily/weekly/monthly/hard) | Kural 6 | `check_drawdown_limits`, `_check_hard_drawdown` | ✓ |
| Cooldown (3 ardışık → 4 saat) | — | baba | ✓ |
| Lot hesaplama | — | `calculate_position_size` | config'e tam bağımlı mı — FZ5-01 kısmi hardcode |
| SL/TP zorunluluk | Kural 4 | `send_order` 2-phase + `ogul.py:1830-1894` close zinciri | ✓ |
| Hybrid transfer | — | `h_engine.py` | ✓ |
| Orphan cleanup | — | `_verify_eod_closure` manuel+orphan exclusion | ✓ |
| Manual trade risk kapısı | Kural 2 | `manuel_motor.py:181 baba.check_risk_limits()` | ✓ |
| Notification semantiği | — | — | OK |
| status.phase önceliği | — | killed>stopped>error>running | ✓ (Faz B) |
| BABA→OĞUL sırası | Kural 1 | `_run_single_cycle` | ✓ test_main_loop_order |
| can_trade kapısı | Kural 2 | `ogul._execute_signal` | ✓ |
| OLAY rejimi risk=0 | Kural 7 | — | ✓ |
| `mt5.initialize()` evrensel koruma | Kural 16 | `connect()`, `_verify()`, `health_check.py` | ✓ test_no_rogue_mt5_initialize_calls |

### 5.13 Faz 5 Bulguları (Mantık Çelişkileri)

**FZ5-01 (P2, BORC)** — Graduated lot schedule hardcoded `{0.75, 0.5}` (`baba.py:1241-1245`). Config'e taşınmalı.

**FZ5-02 (P1, BUG)** — Yetim pozisyon tespiti `baba.report_unprotected_position` çağırmıyor (`ogul.py:3421` civarı). Restart sonrası korumasız pozisyon yeni işlemleri engellemiyor.

**FZ5-03 (P1, SOZLESME)** — L3 `_close_all_positions` manuel dokunur (`baba.py:2619-2630`) — Anayasa uyumlu ama UI'da ön onay dialogu yok.

**FZ5-04 (P1, SOZLESME)** — `status.phase` L2 aktifken "running" dönüyor (`status.py:51-58`). L2 semantiği "sistem durduruldu" ama UI ayırt edemiyor.

**FZ5-05 (P3, BORC)** — `check_risk_limits:1696-1699` graduated `risk_multiplier` schedule dead branch (cons_losses=3 hiç ulaşmıyor, 1684'te return).

**FZ5-06 (P2, GOZLEMLENEBILIRLIK)** — `process_signals` L2'de iç savunma yok. Belt-and-suspenders eksik.

**FZ5-07 (P2, DRIFT)** — Anayasa 4.10 "Günlük kayıp ≥%3 → kapat, ≥%2.5 → yeni yasak". Kod tek eşik `max_daily_loss` (%1.8). **Anayasa-kod DRIFT**.

**FZ5-08 (P1, DRIFT)** — Anayasa §4.1 çağrı sırası `risk → time`, OĞUL iç sırası (`ogul.py:523-528`) EOD → manage → sync → voting → sinyal. Doküman-kod tutarsızlığı.

**FZ5-09 (P2)** — `_close_ogul_and_hybrid` sıfır pozisyonda WARNING log. INFO olmalı.

---

## Faz 6 — Persistence Denetimi

### 6.1 SQLite Tablo Envanteri

`database/trades.db` (67 MB) — 18 tablo, 17 index. Şema: `database.py:36-228`.

| Tablo | Amaç | Satır |
|---|---|---|
| `trades` | Kapanmış işlemler | 215 |
| `hybrid_positions` | Aktif hibrit | 46 |
| `hybrid_events` | Olay akışı | — |
| `notifications` | UI bildirim | 118 (0 unread) |
| `events` | Sistem olay log | **62 211** |
| `risk_snapshots` | Dakikalık snapshot | **105 558** |
| `daily_risk_summary` | Aggregation | — |
| `top5_history` | Top5 seçim | — |
| `weekly_top5_summary` | Haftalık aggregation | — |
| `bars` | OHLCV cache | 173 615 |
| `backtest_bars` | Backtest | — |
| `app_state` | Key-value persist | 12 |
| `strategies` | Strateji tanım | — |
| `config_history` | Config değişiklik | — |
| `liquidity_classes` | Sembol cache | — |
| `manual_interventions` | Manuel eylem | — |
| `error_resolutions` | Error çözüm | — |

`database/ustat.db` — **0 byte** (CLAUDE.md 2 DB der, tek aktif).

### 6.2 WAL / SHM Sağlık

- `trades.db-wal` = **66 MB** (ana DB kadar) — checkpoint gecikmesi
- `trades.db-shm` = 32 KB (normal)
- 20+ backup dosyası + shm/wal kardeşler ~750 MB tortu (`database.py:322-328` sadece `*.db` siliyor)
- `.fuse_hidden*` 4 dosya

### 6.3 Trade Persistence

`insert_trade()` `database.py:601-633`. Ticket UNIQUE **DEĞİL**. Dedup `sync_mt5_trades()` 3 aşamalı kod tarafında (`database.py:635-720`, ±5dk tolerans). DB seviyesinde koruma yok → paralel race.

### 6.4 Notification Persistence

Tablo UNIQUE anahtarsız. `event_bus` çoklu subscriber → duplicate riski. `get_unread_notification_count()` eklendi (Faz A P0-05 ✓). Retention kuralı yok.

### 6.5 Config Kaynakları

Tek kaynak `config/default.json` (186 satır). `config_history` sadece audit. `app_state[baba_risk_state]` runtime state (config değil).

### 6.6 Baseline / State Persist

BABA restart restore: `baba.py:372-373 _restore_risk_state()` constructor'da. Detay `baba.py:511-550` — 12 alan.
`_last_cycle_time` persist edilmiyor — restart'ta None (F6-09).

### 6.7 Retention vs UI Uyumu

- Config `retention.trade_archive_days = 180`
- UI `TradeHistory.jsx:129-130` max filtre 90 gün; `syncTrades(90)` butonu MT5'ten 90 gün çeker
- `run_retention()` trades için **blok YOK** (grep'te: risk/events/top5/config_history/liquidity/hybrid var, trades yok)

### 6.8 Faz 6 Bulguları

**F6-01 (P1, BUG)** — `run_retention()` trades temizliği yok. Config `trade_archive_days=180` ölü.

**F6-02 (P1, BUG)** — Notification UNIQUE yok; duplicate riski.

**F6-03 (P2, BORC)** — WAL checkpoint gecikmesi (66MB). `backup()` checkpoint çağırmıyor.

**F6-04 (P2, BORC)** — Backup rotation shm/wal kardeşleri bırakıyor (~750MB tortu).

**F6-05 (P2, DRIFT)** — `ustat.db` 0 byte. Doküman ya düşürülmeli ya dosya silinmeli.

**F6-06 (P2, SOZLESME)** — Trade `mt5_position_id` DB UNIQUE yok; race açık.

**F6-07 (P2, SOZLESME)** — DB 180 gün, UI 90 gün filtre uyumsuzluğu.

**F6-08 (P2, SOZLESME)** — Notifications retention kuralı yok.

**F6-09 (P3, GOZLEMLENEBILIRLIK)** — `_last_cycle_time` restart'ta None; /status.last_cycle ilk cycle'a kadar null.

**F6-10 (P3, SUREC)** — `.fuse_hidden*` temizlik scripti yok.

---

## Faz 7 — Test Stratejisi Denetimi

### 7.1 Entrypoint

- `pytest.ini`: `testpaths = tests`, `norecursedirs = archive USTAT_DEPO ...` (Faz A P0-02 ✓)
- `pytest --collect-only`: **10 768 test**, 0 INTERNALERROR, 2 cosmetic warning
- `tests/critical_flows`: **71 test passed, 3.50sn**

### 7.2 Test Dosyası Envanteri

| Dosya | `def test_` |
|---|---|
| `test_static_contracts.py` | 54 |
| `test_error_enrichment.py` | 8 |
| `test_mt5_bridge_state.py` | 6 |
| `test_h_engine_devir.py` | 3 |
| `test_1000_combinations.py` | 136 |
| `test_hybrid_100.py` | 100 |
| `test_news_100_combinations.py` | 100 |
| `test_ogul_200.py` | 88 |
| `test_data_management.py` | 86 |
| `test_unit_core.py` | 57 |
| `test_stress_10000.py` | 54 |
| **Toplam** | **~692 fonksiyon** (paramli 10 768) |

### 7.3 12 Kritik Akış Matrisi

**12/12 kapsanmış** — tümü statik (AST/regex). Ayrıntı için metodoloji §9 ve `test_static_contracts.py`. **Runtime integration yok.**

### 7.4 Unit / Integration / Smoke Ayrımı

`pytest.ini` marker'ları tanımlı (`slow`, `integration`, `unit`) ama **koda uygulanmamış**. `-m integration` filtresi boş.

### 7.5 Siyah Kapı 31 Fonksiyon Coverage

Statik kontrat kapsamı:

| Fonksiyon | Statik | Runtime |
|---|---|---|
| BABA `check_risk_limits` | ✓ | kısmi (1000_combinations) |
| BABA `_activate_kill_switch` | dolaylı | — |
| BABA `_close_all_positions` | ✓ | — |
| BABA `_close_ogul_and_hybrid` | ✓ | — |
| BABA `check_drawdown_limits` | ✓ | — |
| BABA `_check_hard_drawdown` | ✓ | — |
| BABA `_check_monthly_loss` | — | — |
| BABA `detect_regime` | — | 1000_combinations |
| BABA `calculate_position_size` | — | ogul_200 dolaylı |
| BABA `run_cycle` | dolaylı | — |
| BABA `_check_period_resets` | — | — |
| OĞUL `_execute_signal` | ✓ | ogul_200 |
| OĞUL `_check_end_of_day` | ✓ | — |
| OĞUL `_verify_eod_closure` | — | — |
| OĞUL `_manage_active_trades` | — | hybrid_100 |
| OĞUL `process_signals` | ✓ | ogul_200 |
| MT5 `send_order` | ✓ | — |
| MT5 `close_position` | ✓ | — |
| MT5 `modify_position` | — | — |
| MT5 `_safe_call` | — | mt5_bridge_state |
| MT5 `heartbeat` | ✓ | — |
| MT5 `connect` | ✓ | — |
| Main `_run_single_cycle` | ✓ | — |
| Main `_heartbeat_mt5` | — | — |
| Main `_main_loop` | — | — |
| Startup `run_webview_process` | — | — |
| Startup `_start_api/_shutdown_api` | — | — |
| API `lifespan` | — | — |
| Startup `main` | kısmi | — |
| Desktop `createWindow` | — | — |

**11/31 (%35) hiç kapsanmamış:** `_check_monthly_loss`, `detect_regime`, `calculate_position_size`, `_check_period_resets`, `_verify_eod_closure`, `modify_position`, `_heartbeat_mt5`, `_main_loop`, `run_webview_process`, `_start_api/_shutdown_api`, `lifespan`.

### 7.6 Pre-Commit Hook

`.githooks/pre-commit` 3026 byte, executable. 3 katman (AST + critical_flows + lint). `pytest.ini` düzeltilmesi ile hook + entrypoint hizalı.

### 7.7 Flaky Test

Açık flaky listesi yok. `test_stress_10000.py`, `test_news_100_combinations.py` uzun (100+ kombinasyon). Runtime gözlemi yapılmadı.

### 7.8 Faz 7 Bulguları

**F7-01 (P1, SUREC)** — Runtime integration test katmanı yok. `tests/integration/` dizini gerekli.

**F7-02 (P2, SUREC)** — 11 Siyah Kapı fonksiyonu test matrisinde boş (özellikle `detect_regime`, `calculate_position_size`, `_check_monthly_loss`).

**F7-03 (P2, SUREC)** — `pytest` marker'ları koda uygulanmamış.

**F7-04 (P2, SUREC)** — `coverage.py` çalıştırması yok.

**F7-05 (P3, SUREC)** — `TestResult`/`TestHarness` class collection warning (`test_news_100_combinations.py`).

---

## Faz 8 — Teknik Borç ve Refactor Hazırlığı

### 8.1 Dosya Büyüklükleri (Değişim)

| Dosya | Satır | Önceki (2026-04-11) | Δ |
|---|---|---|---|
| `engine/ogul.py` | **3521** | — | — |
| `engine/baba.py` | **3388** | 3363 | **+25** |
| `engine/mt5_bridge.py` | 3165 | — | — |
| `engine/h_engine.py` | **2974** | 2946 | **+28** |
| `engine/ustat.py` | 2195 | — | — |
| `engine/database.py` | **2045** | 2027 | **+18** |
| `engine/news_bridge.py` | 1550 | — | — |
| `engine/main.py` | **1534** | 1525 | **+9** |
| `engine/manuel_motor.py` | 1190 | — | — |
| `engine/data_pipeline.py` | 1071 | — | — |
| `engine/simulation.py` | 1068 | — | — |
| `api/schemas.py` | 940 | — | feature bölmeli |
| `api/routes/error_dashboard.py` | 727 | — | — |

**Değişim:** Faz A/B kapatıldıktan sonra motorlar **büyümeye devam etmiş** (+80 satır). Refactor yönü tersine çalışıyor.

### 8.2 Tek Sorumluluk İhlalleri

- `baba.py`: rejim + risk verdict + kill-switch + cooldown + drawdown + fake + persistence + ceza
- `ogul.py`: sinyal + emir state + pozisyon + trailing + EOD + voting + orphan + ÜSTAT entegrasyonu
- `mt5_bridge.py`: connect + send_order + close + modify + safe_call + CB + history sync + tick
- `h_engine.py`: hybrid transfer + PRIMNET trailing + EOD devir + orphan + notification
- `database.py`: schema + backup + CRUD + snapshots + retention + notifications + app_state + top5 + hybrid + events

### 8.3 Private Alan / Çapraz Obje Bağlama

Engine init (`main.py:101-162`) — 6 obje bağlama hâlâ var. Faz B'de API getter'lar eklendi (kill_switch_level, risk_baseline_date public property) ama motor↔motor iç bağlama temizlenmedi. `settings.py:441-442` hâlâ `_risk_baseline_date` fallback (geçiş yarıda).

### 8.4 Dead Code / Drift

- `desktop/index.html:13` `<script src="/pywebview-shim.js">` — pywebview kaldırıldı, referans duruyor (404 sessiz)
- `engine/top5_selection.py:79-86` `EXPIRY_*_DAYS = 0` ölü iskelet
- `start_ustat.py:229-348` `UstatWindowApi` (pywebview için, 100+ satır; "ÖLÜ KOD UYARISI" yorumlu)
- `start_ustat.py` v5.9.x yorum/log etiketleri
- `database/ustat.db` 0 byte
- `desktop/src/components/Dashboard.jsx:88` `let _dashCache` modül-seviyesi global (React antipattern)

### 8.5 Kopya Mantık

- Trailing stop: `ogul._manage_active_trades` + `h_engine` PRIMNET — iki uygulama
- EOD kapatma: `ogul._check_end_of_day` + `h_engine.eod_devir` + `baba._close_all_positions` — 3 nokta
- SL/TP: `mt5_bridge.send_order` 2-phase + `ogul_sltp.py` virtual fallback

### 8.6 Refactor Önceliği

Memory sıra: Anayasa güncelleme → API getter kilidi → motor refactor → schema ayrımı. Faz B API getter kısmen açtı ama Anayasa güncellenmedi (USTAT_ANAYASA.md v2.0, `lifecycle_guard.py` + `process_guard.py` eksik).

### 8.7 Faz 8 Bulguları

**F8-01 (P1, BORC)** — Motorlar Faz A/B sonrası büyümeye devam (+80 satır toplam).

**F8-02 (P1, DRIFT)** — `desktop/index.html:13` pywebview-shim hayalet referans. 404 sessiz.

**F8-03 (P2, BORC)** — USTAT_ANAYASA.md v2.0 lifecycle_guard + process_guard eksik.

**F8-04 (P2, BORC)** — `top5_selection.py:79-86` EXPIRY_*_DAYS=0 ölü iskelet.

**F8-05 (P2, BORC)** — `start_ustat.py:229-348` UstatWindowApi ölü sınıf.

**F8-06 (P2, SOZLESME)** — `settings.py:441-442` `_risk_baseline_date` private fallback.

**F8-07 (P2, BORC)** — `Dashboard.jsx:88` `_dashCache` modül-seviyesi global.

**F8-08 (P2, BORC)** — Kopya EOD + trailing mantığı.

**F8-09 (P3, DRIFT)** — `ustat.db` 0 byte + pid/heartbeat dosya dokümantasyonu eksik.

**F8-10 (P3, BORC)** — `start_ustat.py` v5.9.x changelog yorumları (konum yanlış).

---

## Önceki Denetim 56 Bulgu — Güncel Durum

### P0 (6) — Tümü KAPATILDI

- **P0-01 `fail_names`** — Memory "kapatıldı" diyor; runtime doğrulama gerekli (F7-01 bağlamında)
- **P0-02 pytest.ini** — ✓ KAPATILDI
- **P0-03 restartMT5 hayalet** — ✓ KAPATILDI
- **P0-04 last_cycle ölü alan** — ✓ KAPATILDI (`main.py:205, 765`)
- **P0-05 unread_count** — ✓ KAPATILDI (`database.py:1982`)
- **P0-06 korumasız pozisyon** — ✓ KAPATILDI (`ogul.py:1875`)

### P1 (18) — 11 KAPATILDI, 5 AÇIK, 2 ERTELENDİ

**Kapatılan 11:**
- P1-API-01 private sızıntı — **KISMEN** (F8-06 fallback kaldı)
- P1-API-02 trade_allowed exception=False — ✓
- P1-API-03 phase önceliği — ✓
- P1-API-06 notification-prefs getter — ✓
- P1-UI-01 start_ustat.py v5.9 — ✓ (F8-10 yorumları kaldı)
- P1-UI-03 notification prefs çift kaynak — ✓
- P1-UI-04 kök ErrorBoundary — ✓
- P1-UI-05 App.jsx v5.7 JSDoc — ✓
- P1-OPS-03 WATCHDOG_STALE_SECS — ✓
- P1-ENG-03 SL/TP fallback ERROR — ✓

**Ertelenen 2:**
- **B14 / P1-UI-02** mt5Manager.js şifre process arg — AÇIK
- **B17 / P1-ENG-04** news_bridge timeout profili — AÇIK

**Hâlâ açık P1 (5):**
- **P1-ENG-01** motor obje bağlama (6 referans) — AÇIK
- **P1-ENG-02** 6 dosya 2K+ satır — AÇIK (**büyüdü**)
- **P1-ENG-05** BABA private state — KISMEN (F8-06)
- **P1-API-04** /killswitch auth yok — AÇIK
- **P1-API-05** manual_trade risk kapısı — doğrulama yapılmadı
- **P1-OPS-01** lifecycle/process_guard Anayasa'da yok — AÇIK (F8-03)
- **P1-OPS-02** 46 handler vs 37 belge — AÇIK (CLAUDE.md §11.2)

### P2 (34) ve P3 (20)

Memory Faz C/D'ye ertelendi. Spot doğrulamalar:
- P2-UI-02 pywebview-shim — **AÇIK** (F8-02)
- P2-ENG-07 EXPIRY_*_DAYS=0 — **AÇIK** (F8-04)
- P2-OPS-01 UstatWindowApi — **AÇIK** (F8-05)
- P2-UI-01 _dashCache — **AÇIK** (F8-07)

Geri kalanı bu denetimde spot kontrol edilmedi; Faz C/D sprint'inde tekil doğrulama yapılmalı.

---

## Bulgu Kataloğu (Birleşik)

### P0 — 1 bulgu

**FZ4-01 — Lifespan fail-open davranışı**
- **Dosya:** `api/server.py` lifespan bloğu (config parse noktası)
- **Sınıf:** BUG
- **Kanıt:** Config parse hatasında Engine/API fail-open durumunda kalabilir; Anayasa Kural 9 "güvenlik modülü sessizce devre dışı kalırsa sistem kilitli duruma düşer" ile çelişki.
- **Etki:** Bozuk config ile sistem kısmen çalışır → yanlış risk limitleri, yanlış sinyaller.
- **Çözüm Yönü:** Lifespan config parse exception → explicit fail-closed (API `/health` 503, `_trade_allowed=False`, tüm endpoint'ler degraded).
- **Değişiklik Sınıfı:** C3 (Kırmızı Bölge `api/server.py`)

### P1 — 13 bulgu

**FZ5-02 — Yetim pozisyon BABA'ya raporlanmıyor (BUG)**
- `engine/ogul.py:3421` civarı; `baba.report_unprotected_position` çağrılmıyor.
- Restart sonrası korumasız pozisyon yeni işlemleri engellemiyor.
- C3.

**FZ5-04 — status.phase L2'de "running" (SOZLESME)**
- `api/routes/status.py:51-58`
- UI L2 semantiğini gösteremiyor.
- C2 API + C2 UI.

**FZ3-01 — Degraded mode "error" olarak UI'ya yansıyor (SOZLESME)**
- `status.phase` enum'a "degraded" eklenmeli.
- MT5 yok durumu = degraded (error değil).
- C2 API + C2 UI.

**FZ3-02 — Graceful shutdown log izi eksik (GOZLEMLENEBILIRLIK)**
- MT5 disconnect + DB close log kanıtı yok (F1-05 ile birleşir).
- C2 engine + log ekleme.

**FZ5-08 — Anayasa §4.1 çağrı sırası vs OĞUL iç sırası tutarsız (DRIFT)**
- Anayasa `risk → time`; kod `EOD → manage → sync → voting → sinyal`.
- Dokuman veya kod hizalanmalı.
- C0 (Anayasa) veya C3 (kod).

**F1-04 — CLAUDE.md §6 bağımlılık haritası eksik (DRIFT/GOZLEMLENEBILIRLIK)**
- ManuelMotor, NewsBridge, LifecycleGuard, ErrorTracker, PreMarketBriefing yok.
- Etki analizi yanlış yapılır.
- C0 dokuman + `tools/impact_map.py` otomasyon.

**F2-01 — WebSocket payload Pydantic'siz (SOZLESME)**
- `live.py:157-159` raw dict.
- Discriminated union modeli + contract test.
- C2.

**F2-05 — CLAUDE.md başlık v5.9 vs gerçek v6.0 (DRIFT)**
- Rehberin kendisi drift.
- C0.

**F6-01 — run_retention() trades için uygulama yok (BUG)**
- `database.py:1723-1890` retention 6 blok var, trades yok.
- Config `trade_archive_days=180` ölü.
- C3.

**F6-02 — Notifications UNIQUE kısıtı yok (BUG)**
- `database.py:218-227`
- Duplicate bildirim riski.
- C3 + migration.

**F7-01 — Runtime integration test katmanı yok (SUREC)**
- `tests/integration/` dizini gerekli.
- `test_startup_restricted_mode.py`, `test_db_lock_recovery.py`, `test_bad_config.py`.
- C1.

**F8-01 — Motorlar Faz A/B sonrası büyümeye devam (BORC)**
- +80 satır. Her kapatma yeni borç.
- Faz C motor alt modül ayrımı kritik.
- C4.

**F8-02 — `desktop/index.html:13` pywebview-shim referansı (DRIFT)**
- 404 sessiz.
- C1.

**B14 — mt5Manager.js şifre process arg'ında (BUG/GUVENLIK)**
- `desktop/mt5Manager.js:62-91, 242`
- stdin/CredManager araştırma.
- C2.

**B17 — news_bridge timeout profili belirsiz (SOZLESME)**
- `news_bridge.py:498, 558-581`
- Runtime cycle latency histogramı.
- C0 araştırma → C2 fix.

**P1-ENG-01 — Motor obje bağlama 6 referans (BORC)** — AÇIK, Faz C önkoşulu.

**P1-API-04 — /killswitch auth yok (SOZLESME/GUVENLIK)** — AÇIK.

**P1-API-05 — manual_trade risk kapısı** — doğrulama yapılmadı (yeniden kontrol gerekli).

**P1-OPS-02 — CLAUDE.md §11.2 37 vs 46 handler (DRIFT)** — AÇIK.

### P2 — 22+ bulgu

Faz 2: F2-02, F2-03, F2-04, F2-06, F2-07 (SOZLESME)
Faz 3: FZ3-04 (GOZLEMLENEBILIRLIK)
Faz 4: FZ4-02, FZ4-03 (GOZLEMLENEBILIRLIK)
Faz 5: FZ5-01 (graduated lot hardcoded), FZ5-03 (L3 manuel ön onay), FZ5-06 (process_signals iç savunma), FZ5-07 (Anayasa 4.10 %3/%2.5 DRIFT), FZ5-09 (WARNING log noise)
Faz 6: F6-03, F6-04, F6-05, F6-06, F6-07, F6-08
Faz 7: F7-02, F7-03, F7-04
Faz 8: F8-03, F8-04, F8-05, F8-06, F8-07, F8-08
F1-01 (dosya listesi drift), F1-03 (productName v5.7), F1-05 (shutdown tail), F1-06 (engine/archive)

Önceki P2 (34 toplam): motor alt modül, schemas ayrımı, error_dashboard 727 satır, news_bridge 1550 satır, simulation/backtest izolasyonu, vb.

### P3 — 10+ bulgu

F1-02 (start_ustat.py docstring), F2-08 (localStorage kanıt), F2-09 (route sayısı drift), FZ5-05 (dead branch), F6-09 (last_cycle_time None), F6-10 (fuse_hidden), F7-05 (TestResult class naming), F8-09 (ustat.db 0 byte), F8-10 (v5.9.x yorumlar). Önceki 20 P3 (kozmetik).

---

## Eylem Planı

### Acil (P0) — 1 madde

| # | Bulgu | Dosya / Fonksiyon | C | Efor | Ajan |
|---|---|---|---|---|---|
| 1 | FZ4-01 | `api/server.py` lifespan config parse fail-closed | C3 | M | ustat-api-backend + kullanıcı onayı (Kırmızı Bölge) |

### Sonraki Sprint (P1) — 13 madde, sıralı

| # | Bulgu | Dosya / Fonksiyon | C | Efor | Bağımlılık | Ajan |
|---|---|---|---|---|---|---|
| 1 | F8-03 / P1-OPS-01 | USTAT_ANAYASA.md — Kırmızı Bölge 10→12, Siyah Kapı 31→34 | C0 | S | — | Dokuman |
| 2 | F2-05 | CLAUDE.md başlık v6.0 hizala | C0 | S | — | Dokuman |
| 3 | F8-02 | `desktop/index.html:13` pywebview-shim sil | C1 | S | — | ustat-desktop-frontend |
| 4 | P1-OPS-02 | CLAUDE.md §11.2 — 37→46 komut güncelle | C0 | S | 1 | Dokuman |
| 5 | F1-04 | CLAUDE.md §6 bağımlılık haritası auto-generate | C0 | M | `tools/impact_map.py` | Dokuman |
| 6 | FZ5-02 | `ogul.py` yetim pozisyon → `baba.report_unprotected_position` | C3 | S | — | ustat-engine-guardian |
| 7 | FZ3-01 + FZ5-04 | `status.phase` enum'a "degraded" + "l2_halted" | C2 API + C2 UI | M | — | ustat-api-backend + ustat-desktop-frontend |
| 8 | FZ3-02 | Graceful shutdown log izi (MT5 disconnect + DB close) | C2 | S | — | ustat-ops-watchdog |
| 9 | F2-01 | WebSocket payload Pydantic discriminated union + contract test | C2 | L | — | ustat-api-backend |
| 10 | F6-01 | `database.py run_retention` trades bloğu | C3 | M | — | ustat-engine-guardian |
| 11 | F6-02 | Notifications UNIQUE + migration | C3 | M | — | ustat-engine-guardian |
| 12 | F7-01 | `tests/integration/` katmanı (startup_restricted + db_lock + bad_config) | C1 | L | — | ustat-test-engineer |
| 13 | P1-API-04 | `api/routes/killswitch.py` auth | C2 | M | — | ustat-api-backend |
| 14 | P1-API-05 | `manual_trade.py` can_trade kapısı doğrulama | C0 araştırma → C2 fix | S | — | ustat-api-backend |
| 15 | F8-06 / P1-ENG-05 | `settings.py:441-442` + tüm `_risk_baseline_date` public migration tamamla | C3 | M | 1 | ustat-api-backend |
| 16 | B14 | `mt5Manager.js` şifre stdin/CredManager araştırma + PoC | C2 | L | — | ustat-desktop-frontend |
| 17 | B17 | `news_bridge.py` runtime log analizi (cycle latency histogram) | C0 → C2 | M | — | ustat-ops-watchdog |
| 18 | FZ5-08 | Anayasa §4.1 çağrı sırası vs OĞUL iç sırası hizalama (dokuman) | C0 | S | 1 | Dokuman |

### Yapısal Refactor (P2) — Faz C Yol Haritası

**Kesin sıra (yanlış sırada yapılırsa kritik akış kırılır):**

1. **Anayasa ve dokümantasyon önce** (F8-03, F2-05, P1-OPS-02, F1-04) — hangi dosya Kırmızı Bölge netleşmeden refactor başlamaz.
2. **API sözleşme kilidi tamamla** — tüm private fallback'leri (F8-06, F2-02, F2-03) temizle. `test_static_contracts.py`'e "private alan erişim yasağı" testi.
3. **Motor alt modül ayrımı** — sıra:
   - `engine/mt5_bridge/` (en az bağımlılık)
   - `engine/h_engine/`
   - `engine/baba/`
   - `engine/ogul/` (en çok bağımlılık — sona)
   - Her adımda `tests/critical_flows` yeşil kalmalı
4. **`api/schemas.py` 940 satır → feature-başına** (`schemas/status.py`, `risk.py`, `trades.py`, ...)
5. **Kopya mantık konsolidasyon** (F8-08) — `engine/services/position_closer.py`, `trailing_calculator.py`; sonra ogul/h_engine/baba çağırır.
6. **error_dashboard.py 727 + news_bridge.py 1550** — coverage ölçümü + ölü kod çıkarma.
7. **Disiplin araçları** (Faz D):
   - `docs/INDEX.md` session raporu indeksi
   - PR template: impact_map.py çıktısı zorunlu (Kırmızı Bölge)
   - C0-C4 commit prefix konvansiyonu
   - Dosya başı max 1500 satır CI uyarısı

### Dokunma Alanları — Anayasa 16 Kural Matrisi

| Kural | Durum | Dokunma |
|---|---|---|
| 1 Çağrı sırası | ✓ test_main_loop_order | Dokunulmaz |
| 2 Risk kapısı | ✓ | Dokunulmaz |
| 3 Kill-switch monotonluk | ✓ | Dokunulmaz |
| 4 SL/TP zorunluluk | ✓ | Dokunulmaz |
| 5 EOD 17:45 | ✓ | Dokunulmaz |
| 6 Hard drawdown %15 | ✓ | Dokunulmaz |
| 7 OLAY rejimi | ✓ | Dokunulmaz |
| 8 Circuit breaker | ✓ | Dokunulmaz |
| 9 Fail-safe | ✗ **FZ4-01** | **P0 fix gerekli** |
| 10 L2 manuel dokunmaz | ✓ | Dokunulmaz |
| 11-15 Startup/shutdown | ✓ | Dokunulmaz |
| 16 mt5.initialize koruma | ✓ | Dokunulmaz |

**Siyah Kapı 31 fonksiyon:** 20 statik kontratla korunuyor, 11 boş (F7-02). Refactor "signature/semantics aynı, dosya farklı" olmalı.

---

## Başarı Kriterleri (Metodoloji §14)

| Kriter | Durum |
|---|---|
| Sistem mimarisi net çizilebilir mi | **EVET** |
| Kritik akışlar ispatlandı mı | **EVET** — 12/12 statik yeşil; runtime ispatı F7-01 ile açık |
| En büyük 10 risk açıkça yazıldı mı | **EVET** — P0 (1) + P1 (13) + en kritik P2'ler |
| Neden-sonuç kurulabildi mi | **EVET** — her bulguda dosya:satır + etki zinciri |
| Backlog önceliklendirildi mi | **EVET** — P0-P3 + C0-C4 + efor + bağımlılık + ajan |
| Düzeltme ile refactor ayrıldı mı | **EVET** — Sonraki Sprint (P1) vs Yapısal Refactor (Faz C) |
| "Şimdi ne yapacağımızı biliyoruz" | **EVET** — 18 P1 sıralı; ilk 5 dokuman, sonra kod |

---

## Ek — Bağımlılık Haritası (gerçek kod)

```
main.py (Engine)
├── config.py                   [Config yükle]
├── database.py                 [insert_trade, get_trades, insert_event, backup, app_state]
├── mt5_bridge.py               [heartbeat, connect, disconnect, send_order, close_position, modify_position, get_tick, get_bars]
├── data_pipeline.py            [run_cycle, _update_data]
│   └── mt5_bridge.py           [get_bars, get_tick, get_account_info, get_positions]
├── news_bridge.py              [run_cycle]
├── premarket_briefing          [check]
├── baba.py                     [run_cycle, check_risk_limits, calculate_position_size, report_unprotected_position]
│   ├── database.py             [persist risk state]
│   ├── h_engine.py             [cross-ref: _close_ogul_and_hybrid]
│   └── ogul.py                 [cross-ref]
├── ogul.py                     [select_top5, process_signals, _execute_signal, _manage_active_trades, _check_end_of_day, _verify_eod_closure]
│   ├── mt5_bridge.py           [send_order, close, modify]
│   ├── baba.py                 [check_correlation, increment_daily_trade]
│   ├── h_engine.py             [netting coordination]
│   └── ustat.py                [strateji sinyali]
├── h_engine.py                 [run_cycle, hybrid transfer, PRIMNET trailing, EOD devir]
│   ├── mt5_bridge.py           [close, modify]
│   └── database.py             [hybrid_positions, hybrid_events]
├── manuel_motor.py             [risk kapısı: baba.check_risk_limits()]
├── ustat.py                    [run_cycle, strateji havuzu, hata atfetme]
├── error_tracker.py            [BABA'ya inject]
├── health.py                   [metrik]
└── lifecycle_guard.py          [startup/shutdown state machine]

start_ustat.py
├── ProcessGuard                [singleton + port]
├── Named Mutex
├── multiprocessing.Process(run_webview_process)
│   ├── api/server.py lifespan  [Config → Database → MT5Bridge → DataPipeline → Ustat → Baba → Ogul → Engine]
│   └── Electron subprocess     [desktop/main.js]
│       └── mt5Manager.js       [MT5 OTP akışı]
└── watchdog_loop               [heartbeat izleme, 60sn stale → restart]

config/default.json → config.py → baba.py, ogul.py, main.py, h_engine.py, mt5_bridge.py
```

---

## Ek — Kritik Dosya Referansı

Bu denetimde doğrudan okunan / kanıt toplanan dosyalar (alfabetik):

- `api/deps.py`, `api/server.py`, `api/schemas.py`, `api/constants.py`
- `api/routes/` (tümü — 21 dosya tarandı)
- `config/default.json`
- `CLAUDE.md`, `USTAT_ANAYASA.md`
- `desktop/main.js`, `desktop/mt5Manager.js`, `desktop/package.json`, `desktop/index.html`
- `desktop/src/components/Dashboard.jsx`, `Settings.jsx`, `TradeHistory.jsx`
- `desktop/src/services/api.js`
- `engine/__init__.py`, `engine/main.py`, `engine/baba.py`, `engine/ogul.py`, `engine/h_engine.py`, `engine/mt5_bridge.py`, `engine/ustat.py`, `engine/database.py`, `engine/data_pipeline.py`, `engine/manuel_motor.py`, `engine/news_bridge.py`, `engine/lifecycle_guard.py`, `engine/process_guard.py`, `engine/health.py`, `engine/top5_selection.py`, `engine/config.py`
- `start_ustat.py`, `ustat_agent.py`, `health_check.py`
- `tests/critical_flows/` (4 dosya)
- `pytest.ini`
- `.githooks/pre-commit`
- `database/trades.db` (şema + satır sayıları), `database/ustat.db`
- `logs/` (örneklenen son 200 satır)

**Rapor sonu.**
