# ÜSTAT v5.0 — MASTER GÖREV: TAM ANALİZ RAPORU (FAZ 1)

**Tarih:** 2026-03-01  
**Kapsam:** Proje haritası, veritabanı, engine, API, frontend, eşzamanlılık, güvenlik, performans  
**Kural:** Bu fazda hiçbir dosyada değişiklik yapılmadı; sadece okuma ve raporlama.

---

# 1. PROJE HARİTASI

## 1.1 Dizin ve Dosya Özeti

| Dizin / Dosya | Amaç (tek cümle) | Satır (yaklaşık) |
|---------------|------------------|-------------------|
| **Kök** | | |
| start_ustat.py | API + Vite + Electron sıralı başlatma, port temizliği | ~100+ |
| requirements.txt | Python bağımlılıkları (MT5, pandas, FastAPI, loguru, vb.) | 35 |
| package.json | ÜSTAT npm script’leri (api, desktop, engine, test) | ~15 |
| config/default.json | Motor, risk, MT5, API, indikatör, strateji konfigürasyonu | 1 (minified) |
| **engine/** | | |
| main.py | Ana 10 sn cycle: heartbeat → veri → BABA → USTAT → OĞUL | 468 |
| baba.py | Risk, rejim, erken uyarı, kill-switch, drawdown limitleri | 1672 |
| ogul.py | Sinyal üretimi, emir state-machine, manuel işlem | ~2000 |
| ustat.py | Top 5 kontrat skorlama ve seçimi | ~930 |
| mt5_bridge.py | MT5 bağlantı, reconnect, emir/pozisyon/tick/bar | ~1235 |
| database.py | SQLite thread-safe katmanı, tüm tablolar | 940 |
| data_pipeline.py | Tick/OHLCV çekme, risk snapshot yazma | ~650 |
| config.py | JSON config yükleme, nokta-notasyonlu get | ~82 |
| logger.py | Loguru logger fabrikası | ~30 |
| utils/indicators.py | ADX, ATR, EMA, BB, RSI, MACD | ~430 |
| utils/time_utils.py | İş günü / vade yardımcıları | - |
| models/*.py | trade, signal, risk, regime veri modelleri | - |
| **api/** | | |
| server.py | FastAPI app, lifespan (engine başlat/durdur), CORS, router kayıtları | ~155 |
| deps.py | get_engine, get_baba, get_db, get_mt5, get_ogul, get_ustat, get_pipeline | ~60 |
| schemas.py | Pydantic request/response şemaları (Status, Account, Risk, vb.) | ~400 |
| routes/*.py | status, account, positions, trades, risk, performance, top5, killswitch, events, manual_trade, live (WS) | - |
| **desktop/** | | |
| main.js | Electron ana process, pencere, tray, IPC, splash | ~440 |
| preload.js | contextIsolation güvenli IPC köprüsü | ~80 |
| mt5Manager.js | MT5 başlatma, OTP (admin Python) | - |
| src/App.jsx | HashRouter, route tanımları | - |
| src/components/*.jsx | LockScreen, Dashboard, TopBar, SideNav, OpenPositions, TradeHistory, Performance, RiskManagement, Settings, ManualTrade | - |
| src/services/api.js | Axios client (timeout 5000), getStatus/getAccount/getRisk/…, WebSocket connectLiveWS | ~240 |
| src/styles/theme.css | Tema değişkenleri (koyu/açık) | - |

## 1.2 Import / Bağımlılık Haritası (Özet)

- **engine/main.py** → baba, config, data_pipeline, database, logger, regime, risk, mt5_bridge, ogul, ustat  
- **engine/baba.py** → config, database, logger, regime, risk, mt5_bridge, utils.indicators  
- **engine/ogul.py** → config, database, logger, regime, risk, signal, trade, mt5_bridge, utils.indicators  
- **engine/ustat.py** → config, database, logger, regime (VIOP_EXPIRY baba’dan import edilebiliyor)  
- **engine/mt5_bridge.py** → config, logger  
- **engine/database.py** → config, logger  
- **engine/data_pipeline.py** → config, database, mt5_bridge, logger, utils.indicators  
- **api/server.py** → lifespan’ta engine, config, database, mt5_bridge, data_pipeline, ustat, baba, ogul, main.Engine; routes: account, events, killswitch, live, manual_trade, performance, positions, risk, status, top5, trades  
- **api/routes/risk.py** → deps (get_baba, get_db, get_mt5, get_engine), schemas.RiskResponse  
- **api/deps.py** → global engine referansı, set_engine; get_engine/get_baba/get_db/get_mt5/get_ogul/get_ustat/get_pipeline

## 1.3 Dış Kütüphane Bağımlılıkları

**requirements.txt:** MetaTrader5, pandas, numpy, ta-lib, fastapi, uvicorn, pydantic, aiosqlite, cryptography, loguru, apscheduler, pytest, pytest-asyncio, matplotlib  

**package.json (kök):** scripts only (api, desktop, engine, test).  

**desktop/package.json:** electron, react, react-router-dom, axios, recharts, vite, vb.

---

# 2. VERİTABANI ANALİZİ (database.py)

## 2.1 CREATE TABLE ve Tablolar

**Kaynak:** engine/database.py satır 36–135 (_SCHEMA).

| Tablo | Sütunlar | Tip | İndeksler |
|-------|-----------|-----|-----------|
| bars | symbol, timeframe, timestamp, open, high, low, close, volume | TEXT/REAL, PK (symbol, timeframe, timestamp) | idx_bars_symbol |
| trades | id, strategy, symbol, direction, entry_time, exit_time, entry_price, exit_price, lot, pnl, slippage, commission, swap, regime, fake_score, exit_reason, mt5_position_id | INTEGER PK, TEXT, REAL | idx_trades_symbol, idx_trades_strategy, idx_trades_mt5pos |
| strategies | id, name, signal_type, parameters, status, metrics | INTEGER PK, TEXT | - |
| **risk_snapshots** | **timestamp**, **equity**, **floating_pnl**, **daily_pnl**, **positions_json**, **regime**, **drawdown**, **margin_usage** | TEXT/REAL, PK (timestamp) | idx_risk_timestamp |
| events | id, timestamp, type, severity, message, action | INTEGER PK, TEXT | idx_events_type, idx_events_severity |
| top5_history | date, time, rank, symbol, score, regime | TEXT/INTEGER, PK (date, time, rank) | idx_top5_date |
| config_history | id, timestamp, param, old_value, new_value, changed_by | INTEGER PK, TEXT | - |
| manual_interventions | id, timestamp, action, reason, user | INTEGER PK, TEXT | - |
| liquidity_classes | date, symbol, avg_volume, avg_spread, class | TEXT/REAL, PK (date, symbol) | - |

## 2.2 risk_snapshots: daily_drawdown_pct ve weekly_drawdown_pct

**Sonuç: YOK.**

- **CREATE TABLE risk_snapshots** (satır 79–88): Sütunlar yalnızca `timestamp, equity, floating_pnl, daily_pnl, positions_json, regime, drawdown, margin_usage`.  
- **daily_drawdown_pct** ve **weekly_drawdown_pct** ne tabloda ne de `insert_risk_snapshot` (satır 653–656) içinde geçiyor.  
- API şeması RiskResponse (api/schemas.py 178–179) bu alanları tanımlıyor; api/routes/risk.py bu alanları **hiç set etmiyor** (sadece snap.get("drawdown") → total_drawdown_pct).

## 2.3 Transaction Kullanımı

- **BEGIN / COMMIT / ROLLBACK:** Kodda açık transaction yok.  
- **Commit:** Her `_execute` ve `_executemany` çağrısında `commit=True` ile tek statement sonrası `self._conn.commit()` (satır 220–221, 244–245).  
- Çok adımlı atomik işlem yok; hata durumunda yarım kalan yazım için rollback yok.

## 2.4 Bağlantı Yönetimi

- **Açılış:** `__init__` içinde `sqlite3.connect(self._db_path, check_same_thread=False, timeout=30.0)` (satır 152–157).  
- **WAL:** `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`.  
- **Kapanış:** `close()` (satır 174–177) `self._conn.close()`.  
- **Havuz:** Yok; tek connection.  
- **Eşzamanlılık:** `threading.Lock()` (satır 162) ile tüm public metodlar tek lock altında; aynı process içinde thread-safe.

## 2.5 Eski Veri Temizliği / Purge

- **Mevcut:** `delete_bars`, `delete_trade`, `delete_strategy`, `delete_risk_snapshots`, `delete_events`, `delete_top5`, `delete_config_history`, `delete_interventions`, `delete_liquidity` — hepsi “before” / “before_date” ile manuel silme.  
- **Otomatik purge:** Yok; zamanlanmış cleanup veya retention politikası yok.

## 2.6 Disk Dolu / DB Bozulma

- Disk dolu veya DB bozulması için özel handling yok.  
- `sqlite3.Error` sadece loglanıp yeniden raise ediliyor; engine tarafında art arda DB hatası (DB_ERROR_THRESHOLD=3) sistem durduruyor (main.py 196–211).

---

# 3. ENGINE DERİN ANALİZ

## 3.1 engine/main.py

- **Ana döngü:** `_main_loop()` (satır 164–233): `while self._running` içinde `_run_single_cycle()`; sonra `elapsed = monotonic() - cycle_start`, `sleep_time = max(0, CYCLE_INTERVAL - elapsed)` (10 sn).  
- **Hata:** `_SystemStopError` → stop ve return. `_DBError` → ardışık sayacı artır, eşik (3) aşılırsa stop. Genel `Exception` → log + `_log_event_safe`, döngü devam.  
- **Start/stop:** `start()` MT5 bağlanır, sync, restore_state, sonra `_main_loop()` bloke eder. `stop()` _running=False, mt5.disconnect(), db.close(), _log_event_safe.  
- **MAX_MT5_RECONNECT (5):** Satır 47’de tanımlı; **_heartbeat_mt5** (satır 334–356) içinde **kullanılmıyor**. Heartbeat başarısızsa yalnızca bir kez `connect(launch=False)` deneniyor; 5 deneme döngüsü yok.

## 3.2 engine/baba.py

- **check_drawdown_limits** (satır 748–796):  
  - `snap` yoksa `return True`.  
  - **equity <= 0** (satır **765–766**): `return True` — yani limit kontrolü atlanıyor, işleme “izin var” kabul ediliyor.  
- **check_risk_limits:** Sıra: Kill L3 → L2 → aylık paused → check_drawdown_limits (False ise L2 activate) → hard/max drawdown → aylık kayıp → haftalık (lot yarılama) → floating loss → günlük işlem sayısı → cooldown → ardışık kayıp.  
- **_close_all_positions** (satır 1465–1494): `get_positions()` döngüsü, her ticket için `close_position(ticket)`. Başarısızda sadece `logger.error`; **başarısız ticket listesi dönmüyor**, API’ye iletilmiyor.  
- **_activate_kill_switch:** L1: sadece _killed_symbols güncellenir. L2: can_trade=False, pozisyon kapatılmaz. L3: _close_all_positions çağrılır.  
- **Günlük/haftalık drawdown:** Günlük kayıp **check_drawdown_limits** içinde `daily_pnl` ve `equity` ile yüzde hesaplanıyor (daily_loss_pct). Haftalık kayıp **_check_weekly_loss** içinde hafta başı equity ve mevcut equity ile hesaplanıyor; **risk_snapshots** veya snapshot dict’ine **daily_drawdown_pct / weekly_drawdown_pct** yazılmıyor; data_pipeline ve insert_risk_snapshot bu alanları üretmiyor.

## 3.3 engine/ogul.py

- Sinyal: `process_signals(symbols, regime)` → _check_end_of_day, _advance_orders, _manage_active_trades, _sync_positions, sonra symbols döngüsünde bias ve _generate_signal / _execute_signal.  
- Boş sembol listesi: Döngüler çalışmaz; EOD/orders/active_trades/sync yine çalışır.  
- Tick/veri yok: get_tick None dönünce sinyal üretilmez; get_bars boşsa None.  
- Pozisyon açma: _execute_signal → open_manual_trade veya otomatik akış; mt5_bridge.send_order kullanılır.

## 3.4 engine/ustat.py

- Skorlama: _refresh_scores → ham puanlar, normalize, sırala, ilk 5, ortalama filtresi, vade/haber filtresi → top5_final.  
- Tüm kontratlar elenirse top5_final boş liste; _current_top5 = [] atanır; main’e boş liste gider, ogul process_signals([], regime) güvenli.

## 3.5 engine/mt5_bridge.py

- **connect:** launch=True iken MAX_RETRIES_LAUNCH=5, launch=False iken MAX_RETRIES_RECONNECT=3; denemeler arası BASE_WAIT * 2^(attempt-1) sn.  
- **send_order:** symbol_info’dan volume_min, volume_max, volume_step alınıyor (SymbolInfo dataclass ve satır 390–392) ama **lot bu değerlerle kıyaslanmıyor**; request["volume"] = lot doğrudan gönderiliyor (satır 586–589).  
- **close_position:** positions_get(ticket), tick ile fiyat; retcode != DONE ise None.  
- **initialize timeout:** mt5.initialize() için ayrı timeout parametresi yok; bloklayan çağrı.

## 3.6 engine/config.py

- Yükleme: CONFIG_PATH = config/default.json; _load() ile json.load; dosya yoksa veya JSON hatasındaysa _data={}.  
- Validasyon: Yok; get(key, default) ile eksik anahtar default döner.

## 3.7 engine/data_pipeline.py

- **update_risk_snapshot** (satır 491–548): account, positions, floating_pnl, _calculate_daily_pnl, _calculate_drawdown, margin_usage; snapshot dict’e **equity, floating_pnl, daily_pnl, positions_json, regime, drawdown, margin_usage** yazılıyor. **daily_drawdown_pct** ve **weekly_drawdown_pct** hesaplanmıyor ve yazılmıyor.

---

# 4. API ANALİZİ

## 4.1 Endpoint Listesi

| Method | Path | Dosya | Açıklama |
|--------|------|-------|----------|
| GET | /api/status | status.py | Sistem durumu, rejim, kill-switch, uyarılar |
| GET | /api/account | account.py | Hesap bilgileri (MT5 + snapshot) |
| GET | /api/positions | positions.py | Açık pozisyonlar |
| GET | /api/trades | trades.py | İşlem geçmişi (filtreli) |
| GET | /api/trades/stats | trades.py | İstatistikler (limit 500 default, max 5000) |
| POST | /api/trades/approve | trades.py | İşlem onaylama |
| POST | /api/trades/sync | trades.py | MT5 senkronizasyonu |
| GET | /api/risk | risk.py | Risk snapshot, kill-switch, verdict |
| GET | /api/performance | performance.py | Performans metrikleri |
| GET | /api/top5 | top5.py | Top 5 kontrat |
| POST | /api/reactivate | status.py | Deaktif kontratları açma |
| POST | /api/killswitch | killswitch.py | activate / acknowledge |
| GET | /api/events | events.py | Sistem olayları |
| POST | /api/manual-trade/check | manual_trade.py | Manuel işlem kontrolü |
| POST | /api/manual-trade/execute | manual_trade.py | Manuel emir (ogul.open_manual_trade) |
| WS | /ws/live | live.py | Canlı veri (2 sn push) |

## 4.2 Authentication / Authorization

- **Yok.** Tüm route’lar auth gerektirmiyor; localhost/app origin’den herkes erişebilir.

## 4.3 CORS (server.py 118–130)

- allow_origins: http://localhost:5173, http://localhost:3000, http://127.0.0.1:5173, http://127.0.0.1:3000, app://.  
- allow_credentials=True, allow_methods=["*"], allow_headers=["*"].

## 4.4 Risk Endpoint: daily_drawdown_pct / weekly_drawdown_pct

- **api/routes/risk.py:** resp.daily_pnl, resp.floating_pnl, resp.total_drawdown_pct snapshot’tan set ediliyor. **resp.daily_drawdown_pct** ve **resp.weekly_drawdown_pct** hiç set edilmiyor (varsayılan 0.0 kalıyor).  
- **api/schemas.py** RiskResponse (satır 174–179): daily_drawdown_pct, weekly_drawdown_pct alanları var.

---

# 5. FRONTEND ANALİZİ

## 5.1 Bileşenler: Endpoint, Polling, Cleanup, Loading, Hata

| Bileşen | Çağrılan endpoint’ler | Polling interval | useEffect cleanup (satır) | Loading state | API hata gösterimi |
|---------|------------------------|------------------|---------------------------|---------------|--------------------|
| Dashboard | getStatus, getAccount, getPositions, getTradeStats, getTop5 | 10 sn (123–124) | return () => clearInterval(iv) (124) | Yok (ilk yükleme boş/0) | Sessiz fallback |
| TopBar | getStatus, getAccount (fetchData) | 2 sn (62–63) | clearInterval (63) | Yok | Sessiz fallback |
| OpenPositions | getPositions, getAccount | 5 sn (92–93) | clearInterval (93) | Yok | Sessiz fallback |
| RiskManagement | getRisk, getAccount | 5 sn (92–93) | clearInterval (93) | Yok | Sessiz fallback |
| ManualTrade | getTrades (fetchRecentTrades) | 10 sn (75–76) | clearInterval (76) | Yok | Sessiz fallback |
| TradeHistory | getTrades, getTradeStats | Tek sefer + bağımlılık | - | Var (fetchData) | Sessiz fallback |
| Performance | getPerformance | Tek sefer (127) | - | Var | Sessiz fallback |
| Settings | getEvents (refreshLogs), getStatus | Tek sefer / manuel | - | Var | Sessiz fallback |
| LockScreen | MT5/OTP akışı | setInterval 3 sn (111) | clearInterval (113,123,137,150) | Var | - |
| SideNav | - | Kill-Switch 2 sn basılı | clearInterval (51,70) | - | - |

## 5.2 desktop/src/services/api.js

- **Fonksiyonlar:** getStatus, getAccount, getPositions, getTrades, getTradeStats, approveTrade, syncTrades, getRisk, getPerformance, getTop5, getEvents, reactivateSymbols, activateKillSwitch, acknowledgeKillSwitch, checkManualTrade, executeManualTrade, connectLiveWS.  
- **try/catch:** Tüm export fonksiyonlarda catch bloğu var; **hata loglanmıyor** (console.error yok), sadece varsayılan obje dönülüyor.  
- **Timeout:** axios client timeout=5000 (satır 18).  
- **Retry:** Yok.

## 5.3 Polling Duplikasyonu

| Bileşen | Endpoint | Interval | Aynı endpoint’i çağıran diğer bileşenler |
|---------|----------|----------|------------------------------------------|
| Dashboard | /api/status | 10 sn | TopBar (2 sn) |
| Dashboard | /api/account | 10 sn | TopBar (2 sn), OpenPositions (5 sn), RiskManagement (5 sn) |
| Dashboard | /api/positions | 10 sn | OpenPositions (5 sn) |
| Dashboard | /api/trades/stats | 10 sn | TradeHistory (sayfa açılışında) |
| Dashboard | /api/top5 | 10 sn | - |
| TopBar | /api/status | 2 sn | Dashboard (10 sn) |
| TopBar | /api/account | 2 sn | Dashboard, OpenPositions, RiskManagement |
| OpenPositions | /api/positions | 5 sn | Dashboard |
| OpenPositions | /api/account | 5 sn | Dashboard, TopBar, RiskManagement |
| RiskManagement | /api/risk | 5 sn | - |
| RiskManagement | /api/account | 5 sn | Dashboard, TopBar, OpenPositions |

---

# 6. EŞZAMANLILIK ANALİZİ

- **Engine cycle** arka planda `run_in_executor(None, engine.start)` ile tek thread’de çalışıyor.  
- **DB:** Sadece `engine.database` içinde `threading.Lock`; API ve engine aynı DB instance’ını kullanıyor, tüm erişim lock ile seri.  
- **Lock/mutex:** asyncio.Lock veya ek mutex yok; engine thread’i ile API async handler’ları aynı process, farklı thread/async.  
- **Manuel işlem + engine:** İkisi de aynı `ogul` ve `mt5` kullanıyor. Kullanıcı İşlem Paneli’nden execute ederken aynı anda engine cycle process_signals → _execute_signal ile emir gönderebilir; **MT5’e iki paralel emir gidebilir**. Uygulama seviyesinde emir kilidi yok.  
- **Kill-Switch + engine:** L3 tetiklenince _close_all_positions senkron çalışıyor; bir sonraki cycle’da check_risk_limits L3 gördüğü için can_trade=False. Aynı cycle içinde hem L3 hem yeni pozisyon açılması check_risk_limits sırasıyla engelleniyor.  
- **Race riski:** (1) Manuel execute ile engine _execute_signal aynı anda send_order. (2) API’den gelen isteklerle engine aynı anda DB yazıyor — DB lock ile seri, tutarlılık korunuyor.

---

# 7. GÜVENLİK ANALİZİ

- **API auth:** Yok; /api/killswitch POST herkese açık (localhost/app origin).  
- **CORS:** Sadece localhost ve app://.  
- **Config:** default.json’da mt5.login, mt5.server null; şifre/OTP config’te yok.  
- **Log:** Hassas bilgi (şifre) loglanmıyor; equity, PnL, sembol loglarda olabilir.  
- **Electron:** main.js satır 93–94: contextIsolation: true, nodeIntegration: false. preload.js güvenli IPC köprüsü.

---

# 8. PERFORMANS ANALİZİ

- **getTradeStats:** limit default 500, max 5000; her çağrıda db.get_trades(since=RISK_BASELINE_DATE, limit=limit) — 500 kayıt.  
- **DB index:** idx_bars_symbol, idx_trades_symbol, idx_trades_strategy, idx_trades_mt5pos, idx_events_type, idx_events_severity, idx_top5_date, idx_risk_timestamp.  
- **Top 5:** 15 kontrat skorlama, DB’den bar verisi (get_bars), tek cycle’da bir kez.  
- **Dashboard:** Birden fazla useEffect/setInterval (saat 1 sn, fetchAll 10 sn); unmount’ta clearInterval var.  
- **Memory leak:** setInterval/WebSocket cleanup mevcut; connectLiveWS close() clearInterval(pingInterval) + ws.close(). Kontrol edilen bileşenlerde cleanup var.

---

# 9. BULGULAR (Format: Konum, Modül, Kategori, Öncelik, Süre, Durum, Sorun, Çözüm, Etki, Test)

═══════════════════════════════════════════════════════
BULGU #1
═══════════════════════════════════════════════════════

📍 KONUM: engine/baba.py:765–766
📂 MODÜL: Engine (BABA)
🏷️ KATEGORİ: Güvenlik / Stabilite
⚡ ÖNCELİK: YÜKSEK
⏱️ TAHMİNİ SÜRE: 15dk

🔍 MEVCUT DURUM:
```python
if equity <= 0:
    return True
```

❌ SORUN:
Equity sıfır veya negatifken “limit aşılmadı” kabul ediliyor; sıfır/negatif hesapta yeni işlem açılması riski.

✅ ÇÖZÜM:
equity <= 0 (ve isteğe bağlı balance <= 0) ise False döndür; logger.warning ile sebep yaz. check_risk_limits zaten check_drawdown_limits False iken L2 tetikliyor.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: engine/baba.py
- Yan etki riski: Düşük
- MT5 etkisi: Yok
- Canlı işlem riski: Yok (sadece engel)
- Geri dönüş: Kolay
- Bağımlı maddeler: Yok

🧪 TEST:
Equity 0 / negatif simülasyonu; check_risk_limits can_trade=False ve L2 tetiklemesi.

═══════════════════════════════════════════════════════
BULGU #2
═══════════════════════════════════════════════════════

📍 KONUM: engine/database.py:79–88 (risk_snapshots); api/routes/risk.py (daily/weekly set edilmiyor)
📂 MODÜL: Veritabanı / API
🏷️ KATEGORİ: Fonksiyonel
⚡ ÖNCELİK: YÜKSEK
⏱️ TAHMİNİ SÜRE: 1saat

🔍 MEVCUT DURUM:
risk_snapshots tablosunda daily_drawdown_pct ve weekly_drawdown_pct sütunları yok. data_pipeline update_risk_snapshot bu alanları hesaplamıyor. API get_risk() resp.daily_drawdown_pct ve resp.weekly_drawdown_pct set etmiyor.

❌ SORUN:
Risk ekranında günlük/haftalık drawdown barları anlamsız (0 veya fallback 12389).

✅ ÇÖZÜM:
(1) data_pipeline’da gün başı/hafta başı equity ile daily_drawdown_pct ve weekly_drawdown_pct hesapla; snapshot dict’e ekle. (2) DB şemasına opsiyonel sütunlar ekle veya API’de snapshot’lar üzerinden hesapla. (3) api/routes/risk.py’de bu alanları doldur. (4) Frontend’de 12389 kaldır, API’den gelen değerleri kullan.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: engine/data_pipeline.py, engine/database.py (şema), api/routes/risk.py, desktop RiskManagement.jsx
- Yan etki riski: Orta
- MT5 etkisi: Yok
- Canlı işlem riski: Yok
- Geri dönüş: Orta
- Bağımlı maddeler: Önceki #6, #7, #21 ile aynı hedef

🧪 TEST:
Snapshot sonrası API /api/risk’te daily_drawdown_pct, weekly_drawdown_pct dolu; UI’da barlar doğru.

═══════════════════════════════════════════════════════
BULGU #3
═══════════════════════════════════════════════════════

📍 KONUM: engine/baba.py:1465–1494 (_close_all_positions)
📂 MODÜL: Engine (BABA)
🏷️ KATEGORİ: Fonksiyonel
⚡ ÖNCELİK: ORTA
⏱️ TAHMİNİ SÜRE: 30dk

🔍 MEVCUT DURUM:
L3’te tüm pozisyonlar kapatılıyor; başarısız kapanışta sadece logger.error; closed_count sadece başarılıları sayıyor; çağıran/API sonuç almıyor.

❌ SORUN:
Kullanıcı hangi pozisyonların kapatılamadığını bilmiyor.

✅ ÇÖZÜM:
_close_all_positions başarısız ticket listesini döndürsün (veya closed/failed dict); API/KillSwitchResponse’a failed_tickets veya mesaj eklenebilir.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: engine/baba.py; isteğe bağlı api/routes/killswitch.py, schemas
- Yan etki riski: Düşük
- MT5 etkisi: Yok
- Canlı işlem riski: Yok
- Geri dönüş: Kolay
- Bağımlı maddeler: Yok

🧪 TEST:
L3 tetikle, bir pozisyonu kapatılamaz simüle et; API veya log’da failed listesi.

═══════════════════════════════════════════════════════
BULGU #4
═══════════════════════════════════════════════════════

📍 KONUM: engine/mt5_bridge.py:534–596 (send_order)
📂 MODÜL: MT5
🏷️ KATEGORİ: Fonksiyonel
⚡ ÖNCELİK: ORTA
⏱️ TAHMİNİ SÜRE: 30dk

🔍 MEVCUT DURUM:
symbol_info’dan volume_min, volume_max, volume_step alınıyor; request["volume"] = lot doğrudan; lot bu sınırlarla kıyaslanmıyor.

❌ SORUN:
Geçersiz lot MT5’e gidip retcode ile reddediliyor; ön validasyon yok.

✅ ÇÖZÜM:
Lot’u volume_min/max ile sınırla, volume_step’e göre yuvarla; uyumsuzsa None dön + _last_order_error; order_send çağırma.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: engine/mt5_bridge.py
- Yan etki riski: Düşük
- MT5 etkisi: Var (ön validasyon)
- Canlı işlem riski: Yok
- Geri dönüş: Kolay
- Bağımlı maddeler: Yok

🧪 TEST:
Lot 0, çok büyük, step uyumsuz; send_order None ve anlamlı hata mesajı.

═══════════════════════════════════════════════════════
BULGU #5
═══════════════════════════════════════════════════════

📍 KONUM: desktop/src/services/api.js (tüm catch blokları)
📂 MODÜL: Frontend
🏷️ KATEGORİ: UX / Stabilite
⚡ ÖNCELİK: YÜKSEK
⏱️ TAHMİNİ SÜRE: 30dk

🔍 MEVCUT DURUM:
try/catch ile varsayılan obje dönülüyor; hata loglanmıyor; kullanıcı “bağlantı hatası” görmez.

❌ SORUN:
Sessiz hata; ağ/API sorunları ayırt edilemiyor.

✅ ÇÖZÜM:
catch’te console.error veya merkezi log; isteğe bağlı retry (kritik endpoint’ler); isteğe bağlı UI’da “Bağlantı hatası” state + yenile.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: desktop/src/services/api.js; isteğe bağlı bileşenler
- Yan etki riski: Düşük
- MT5 etkisi: Yok
- Canlı işlem riski: Yok
- Geri dönüş: Kolay
- Bağımlı maddeler: Yok

🧪 TEST:
API kapat, timeout; log veya UI’da hata görünür.

═══════════════════════════════════════════════════════
BULGU #6
═══════════════════════════════════════════════════════

📍 KONUM: engine/main.py:47 (MAX_MT5_RECONNECT), 334–356 (_heartbeat_mt5)
📂 MODÜL: Engine
🏷️ KATEGORİ: Kod Kalitesi / Dokümantasyon
⚡ ÖNCELİK: DÜŞÜK
⏱️ TAHMİNİ SÜRE: 15dk

🔍 MEVCUT DURUM:
MAX_MT5_RECONNECT = 5 tanımlı; _heartbeat_mt5 içinde kullanılmıyor; heartbeat başarısızsa tek connect(False) denemesi.

❌ SORUN:
Dokümantasyon “5 deneme” diyor; kod 1+bridge içi 3 deneme.

✅ ÇÖZÜM:
_heartbeat_mt5’te MAX_MT5_RECONNECT kadar connect(False) dene; veya sabiti kaldırıp docstring’i “bir kez reconnect” olarak güncelle.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: engine/main.py
- Yan etki riski: Yok
- MT5 etkisi: Yok
- Canlı işlem riski: Yok
- Geri dönüş: Kolay
- Bağımlı maddeler: Yok

🧪 TEST:
Heartbeat fail simülasyonu; deneme sayısı veya doc tutarlı.

═══════════════════════════════════════════════════════
BULGU #7
═══════════════════════════════════════════════════════

📍 KONUM: engine/database.py — transaction yok; purge zamanlaması yok
📂 MODÜL: Veritabanı
🏷️ KATEGORİ: Stabilite
⚡ ÖNCELİK: ORTA
⏱️ TAHMİNİ SÜRE: 1saat

🔍 MEVCUT DURUM:
Her _execute commit=True ile tek statement commit. Çok adımlı işlemde rollback yok. delete_* var ama otomatik purge/retention yok.

❌ SORUN:
Yarım kalan yazımda tutarsızlık; DB süresiz büyüyebilir.

✅ ÇÖZÜM:
Kritik çok adımlı işlemlerde BEGIN/COMMIT/ROLLBACK veya with _lock içinde tek transaction. İsteğe bağlı: zamanlanmış purge (örn. risk_snapshots 90 gün, events 30 gün).

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: engine/database.py; isteğe bağlı scheduler
- Yan etki riski: Orta
- MT5 etkisi: Yok
- Canlı işlem riski: Yok
- Geri dönüş: Orta
- Bağımlı maddeler: Yok

🧪 TEST:
DB büyümesi; hata anında rollback davranışı.

═══════════════════════════════════════════════════════
BULGU #8
═══════════════════════════════════════════════════════

📍 KONUM: Engine thread + API aynı ogul/mt5; manual_trade/execute ve process_signals
📂 MODÜL: Eşzamanlılık
🏷️ KATEGORİ: Stabilite
⚡ ÖNCELİK: ORTA
⏱️ TAHMİNİ SÜRE: 1saat

🔍 MEVCUT DURUM:
Manuel emir ile engine sinyal emri aynı anda mt5.send_order çağırabilir; uygulama seviyesinde emir kilidi yok.

❌ SORUN:
Aynı anda iki emir gönderimi; limit aşımı veya istenmeyen pozisyon artışı riski.

✅ ÇÖZÜM:
Emir gönderimi için tek bir kuyruk veya threading.Lock (örn. mt5_bridge’de send_order öncesi lock); manuel ve otomatik aynı kuyruktan geçsin.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: engine/mt5_bridge.py veya ogul; api/routes/manual_trade.py
- Yan etki riski: Orta
- MT5 etkisi: Var
- Canlı işlem riski: Var (nadir senaryo)
- Geri dönüş: Orta
- Bağımlı maddeler: Yok

🧪 TEST:
Aynı anda manuel + otomatik emir denemesi; tek seferde bir emir.

═══════════════════════════════════════════════════════
BULGU #9
═══════════════════════════════════════════════════════

📍 KONUM: api/server.py — Authentication yok
📂 MODÜL: Güvenlik
🏷️ KATEGORİ: Güvenlik
⚡ ÖNCELİK: ORTA (localhost’a sınırlıysa DÜŞÜK)
⏱️ TAHMİNİ SÜRE: 2saat

🔍 MEVCUT DURUM:
Tüm route’lar auth gerektirmiyor; CORS sadece localhost/app.

❌ SORUN:
Aynı makinede çalışan başka bir uygulama veya tarayıcı 5173/3000’den /api/killswitch POST atabilir.

✅ ÇÖZÜM:
En azından /api/killswitch ve /api/manual-trade/execute için API key veya basit token (header); CORS zaten sınırlı.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: api/server.py, api/deps.py, desktop api.js (header)
- Yan etki riski: Düşük
- MT5 etkisi: Yok
- Canlı işlem riski: Yok
- Geri dönüş: Kolay
- Bağımlı maddeler: Yok

🧪 TEST:
Token olmadan 403; token ile 200.

═══════════════════════════════════════════════════════
BULGU #10
═══════════════════════════════════════════════════════

📍 KONUM: Dashboard.jsx, TopBar.jsx, OpenPositions.jsx — ilk yükleme
📂 MODÜL: Frontend
🏷️ KATEGORİ: UX
⚡ ÖNCELİK: DÜŞÜK
⏱️ TAHMİNİ SÜRE: 30dk

🔍 MEVCUT DURUM:
Mount’ta hemen fetch; veri gelene kadar state 0/boş; loading göstergesi yok.

❌ SORUN:
“0” ile “henüz yüklenmedi” ayrımı yok.

✅ ÇÖZÜM:
loading=true ile ilk fetch; tamamlanınca false; “Yükleniyor…” veya skeleton.

⚠️ ETKİ ANALİZİ:
- Etkilenen dosyalar: Dashboard.jsx, TopBar.jsx, OpenPositions.jsx
- Yan etki riski: Yok
- MT5 etkisi: Yok
- Canlı işlem riski: Yok
- Geri dönüş: Kolay
- Bağımlı maddeler: Yok

🧪 TEST:
Sayfa açılışı; kısa süre “Yükleniyor” görünür.

---

# 10. DOĞRULAMA TABLOSU (Önceki Raporlar #1–#22)

| Önceki # | İddia | Doğrulama / Düzeltme |
|----------|--------|------------------------|
| 1 | Dashboard ilk kart “Toplam İşlem” → “Günlük İşlem” | ✅ Doğru; değer daily_trade_count, başlık yanıltıcı. |
| 2 | Metrik penceresi tutarlılığı | ✅ getTradeStats(500), getPerformance(30) farklı pencereler. |
| 3 | “En Kısa” ⚡ → ⏱ | ✅ TradeHistory’de ikon tutarsızlığı var. |
| 4 | “Maks. Ardışık Kayıp” birim | ✅ Etiket tek başına “işlem” belirtmiyor. |
| 5 | Süre “s” saat/saniye belirsiz | ✅ elapsed() “1g 22s” gibi; “s” saat. |
| 6 | 12389 magic number, equity API’den | ✅ RiskManagement’ta sabit equity/drawdown fallback kullanılıyor; API’den gelmeli. |
| 7 | daily/weekly drawdown API’de doldurulsun | ✅ DOĞRULANDI: risk.py set etmiyor; snapshot’ta sütun yok. |
| 8 | FAZ 1 vs L1 terminoloji | ✅ TopBar vs Risk farklı etiket. |
| 9 | Para birimi API’den | ✅ ManualTrade’de TL sabit. |
| 10 | Grafik X ekseni; Sharpe tooltip | ✅ Performans’ta tick sıkışması ve 0.00 açıklaması. |
| 11 | Günlük K/Z vs Net K/Z etiket | ✅ TopBar MT5, Dashboard DB kaynaklı. |
| 12 | Top 5 bar maxScore | ✅ Liste üzerinden hesaplanabilir. |
| 13 | equity<=0 → False | ✅ baba.py:765–766 return True; rapor doğru. |
| 14 | L3 başarısız ticket dön | ✅ _close_all_positions sadece log, liste dönmüyor. |
| 15 | send_order lot validasyonu | ✅ volume_min/max/step kullanılmıyor. |
| 16 | API hata log + retry/UI | ✅ api.js catch sessiz. |
| 17 | MAX_MT5_RECONNECT kullanımı | ✅ main.py’de sabit kullanılmıyor. |
| 18 | Config validasyonu | ✅ config.py validasyon yok. |
| 19 | L3 loading/async | ✅ activate senkron, uzun sürebilir. |
| 20 | İlk yükleme loading | ✅ Dashboard/TopBar/OpenPositions’ta yok. |
| 21 | Snapshot + API daily/weekly | ✅ data_pipeline hesaplamıyor; #2/#7 ile aynı. |
| 22 | initialize timeout | ✅ mt5.initialize için timeout yok. |

---

# 11. BAĞIMLILIK HARİTASI

- **#2 (BULGU #2) + önceki #6 + #7 + #21:** Aynı iş: Önce backend’de daily_drawdown_pct ve weekly_drawdown_pct hesaplanıp snapshot/API’de doldurulmalı; sonra frontend 12389 kaldırılıp API/account equity kullanılmalı.
- **#3 (L3 failed tickets):** Bağımsız; #19 (L3 loading) ile birlikte düşünülebilir.
- **#5 (api.js hata) + #10 (loading):** İkisi de frontend; birlikte “hata ve yükleme” iyileştirmesi.
- **#8 (emir kilidi):** Bağımsız; uygulandıktan sonra manuel ve otomatik emir çakışmaz.

---

# 12. TAM ÖZET TABLO

| # | Modül | Kategori | Öncelik | Tahmini süre | Kısa Açıklama |
|---|-------|----------|---------|--------------|---------------|
| 1 | BABA | Güvenlik | YÜKSEK | 15dk | equity<=0 → False |
| 2 | DB/API/Frontend | Fonksiyonel | YÜKSEK | 1saat | daily/weekly drawdown snapshot+API+UI |
| 3 | BABA | Fonksiyonel | ORTA | 30dk | L3 failed tickets dön |
| 4 | MT5 | Fonksiyonel | ORTA | 30dk | send_order lot validasyonu |
| 5 | Frontend | UX | YÜKSEK | 30dk | API hata log + retry/UI mesajı |
| 6 | main | Kod kalitesi | DÜŞÜK | 15dk | MAX_MT5_RECONNECT kullan veya doc |
| 7 | DB | Stabilite | ORTA | 1saat | Transaction + isteğe bağlı purge |
| 8 | Engine/API | Stabilite | ORTA | 1saat | Emir gönderimi için lock/kuyruk |
| 9 | API | Güvenlik | ORTA | 2saat | Kill-switch/manuel için auth |
| 10 | Frontend | UX | DÜŞÜK | 30dk | İlk yükleme loading |

(Önceki raporlardaki UI/UX maddeleri #1–#12 aynen geçerli; bu tablo yeni master bulguları + kritik tekrarları özetliyor.)

---

# 13. UYGULAMA PLANI (3 DALGA)

**Dalga 1 (Kritik / Yüksek — tahmini 2–2.5 saat)**  
- BULGU #1: equity<=0 → False (baba.py)  
- BULGU #2: daily/weekly drawdown (data_pipeline, DB/şema veya API hesaplama, risk.py, frontend 12389 kaldır)  
- BULGU #5: api.js hata log + isteğe bağlı retry/UI  

**Dalga 2 (Orta — tahmini 2.5–3 saat)**  
- BULGU #3: L3 failed tickets  
- BULGU #4: send_order lot validasyonu  
- BULGU #7: DB transaction + isteğe bağlı purge  
- BULGU #8: Emir kilidi (mt5 veya ogul)  
- BULGU #9: Kill-switch/manuel auth (basit token)  

**Dalga 3 (Düşük / İyileştirme — tahmini 1–1.5 saat)**  
- BULGU #6: MAX_MT5_RECONNECT veya doc  
- BULGU #10: İlk yükleme loading  
- Önceki raporlardaki #1–#5, #8–#12 (UI/UX, terminoloji, birim, grafik, para birimi)

**Toplam tahmini:** ~6–7 saat (tek kişi, test dahil).

---

# 14. DOĞRULAYAMADIM LİSTESİ

| Madde | Neden emin değilim | Ne gerekli |
|-------|---------------------|------------|
| risk_snapshots’a yeni sütun eklenirse mevcut DB’lerde migration | Eski kurulumlarda ALTER TABLE yapılıp yapılmayacağı proje standartında yazılı değil | Migration script veya “yeni kurulumda geçerli” dokümantasyonu |
| Emir kilidi için en güvenli yer (mt5_bridge vs ogul) | mt5_bridge tüm send_order çağrılarını toplar; ogul sadece sinyal tarafı. Manuel trade de mt5’e gidiyor; lock mt5_bridge’de mi yoksa tek bir “order executor” katmanında mı olmalı net değil | Mimari karar: tek order queue mu, sadece send_order’a lock mu |
| CORS “app://.” dışında production’da başka origin kullanılıyor mu | Sadece server.py’deki liste görüldü; production build’de farklı origin olabilir | Build/config kontrolü |

---

**FAZ 1 TAMAMLANDI. Hiçbir dosyada değişiklik yapılmadı. FAZ 2 için “FAZ 2'ye geç” veya “Dalga 1'i uygula” komutunu bekliyorum.**
