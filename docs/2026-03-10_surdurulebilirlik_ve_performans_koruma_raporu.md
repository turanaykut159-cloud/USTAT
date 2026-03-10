# USTAT v5.3 — Sürdürülebilirlik ve Performans Koruma Nihai Raporu

**Tarih:** 2026-03-10
**Kapsam:** ~40.000 satır kod tabanı (Engine, API, Desktop, MT5Bridge, Database)
**Yontem:** 5 paralel derinlemesine analiz — Engine, Database, API/Startup, Frontend, HANDOVER dokumanları

---

## YONETICI OZETI

USTAT v5.3, **normal kosullarda %90+ basariyla calisan** ama **yuksek volatilite, network kesintisi veya beklenmeyen cokme** durumlarinda **kritik zayifliklari** olan bir sistemdir. Bu rapor 5 katmanda toplam **80+ bulgu** tespit etmis, bunlarin **12'si kritik**, **18'i yuksek risk** seviyesindedir.

**En Kritik 5 Sorun:**
1. MT5 baglanti kopmasi → engine durur, acik pozisyonlar MT5'te kalir (kurtarma yok)
2. Restart sonrasi state tutarsizligi (partial restore → risk limiti bypass)
3. DB integrity check yok (bozuk DB sessizce calisir)
4. Frontend Error Boundary yok (tek bilesen hatasi tum UI'i cokertiyor)
5. Engine crash → API hayatta kalir ama olu veri sunar

---

## BOLUM 1: COKME SENARYOLARI VE KURTARMA REHBERI

### 1.1 Senaryo: MT5 Baglantisi Koptu

**Belirtiler:**
- Dashboard'da "MT5 Baglanti Yok" uyarisi
- Log'da: `MT5_RECONNECT`, `ENGINE_STOP`
- Pozisyonlar guncellenmez

**Ne Olur:**
1. Engine heartbeat (10sn) MT5'in kopuldugunu tespit eder
2. `_ensure_connection(launch=False)` → 3 deneme (2, 4, 8 sn bekleme)
3. Basarisiz → `_SystemStopError` → `engine.stop()` cagrilir
4. Engine durur, API hayatta kalir
5. **PROBLEM:** MT5'teki acik pozisyonlar yonetilmez halde kalir

**Kurtarma Adimlari:**
```
1. MT5 terminalini kontrol et (acik mi? internet var mi?)
2. MT5 terminali aciksa → USTAT'i yeniden baslat (start_ustat.bat)
3. MT5 terminali kapanmissa → MT5'i ac, OTP dogrulama yap, sonra USTAT baslat
4. Acik pozisyonlari MT5 terminalinden kontrol et
5. USTAT acildiktan sonra Dashboard'da pozisyon eslesmesini dogrula
```

**Riskler:**
- Reconnect denemesi sirasinda engine 14+ saniye bloke olur
- Heartbeat timeout siniri yok → sonsuz bekleme mumkun
- Acik pozisyonlar SL/TP olmadan MT5'te kalabilir (H-Engine software mode)

---

### 1.2 Senaryo: Uygulama Ani Kapandi (Kill, Elektrik Kesintisi)

**Belirtiler:**
- USTAT penceresi kapali
- Task Manager'da python.exe veya electron.exe kalintilari olabilir

**Ne Olur:**
1. Graceful shutdown calismaz (signal handler tetiklenmez)
2. DB'de yazilmamis transaction kaybedilir (WAL ile kismi kurtarma)
3. MT5 pozisyonlari acik kalir
4. PID dosyasi eski kalir → sonraki baslatmada port catismasi

**Kurtarma Adimlari:**
```
1. Task Manager → python.exe, electron.exe, node.exe varsa sonlandir
2. C:\USTAT\api.pid dosyasini sil (varsa)
3. Port kontrolu: netstat -ano | findstr ":8000" ve ":5173"
   - Dinleyen process varsa: taskkill /F /PID <pid>
4. MT5 terminalinden acik pozisyonlari kontrol et
5. start_ustat.bat ile yeniden baslat
6. Dashboard'da pozisyon eslesmesini kontrol et
```

**Riskler:**
- trades.db-wal dosyasi kilitli kalabilir → "database is locked" hatasi
- Partial write → veri tutarsizligi (trade kaydi eksik/duplike)

---

### 1.3 Senaryo: Veritabani Bozuldu veya Kitlendi

**Belirtiler:**
- Log'da: `SQL hatasi`, `database is locked`
- Dashboard'da veriler guncellenmiyor veya bos geliyor
- 3 ardisik DB hatasi → engine otomatik durur

**Ne Olur:**
1. `_consecutive_db_errors` sayaci artar
2. 3 veya daha fazla ardisik hata → `SYSTEM_STOP` event → engine durur
3. API hala calisir ama eski veri sunar

**Kurtarma Adimlari:**
```
1. USTAT'i tamamen kapat
2. C:\USTAT\data\ klasorune git
3. trades.db boyutunu kontrol et (normal: ~150-200 MB)
4. Integrity check (Python konsolunda):
   python -c "import sqlite3; c=sqlite3.connect('data/trades.db'); print(c.execute('PRAGMA integrity_check').fetchone())"
5. Sonuc "ok" ise → yeniden baslat
6. Sonuc hata ise → yedekten geri yukle:
   a. trades.db'yi trades.db.bozuk olarak yeniden adlandir
   b. En son trades_backup_*.db dosyasini trades.db olarak kopyala
   c. USTAT'i baslat
7. Hic yedek yoksa → trades.db'yi sil, USTAT temiz baslatma yapar
   (UYARI: Tum islem gecmisi kaybolur)
```

---

### 1.4 Senaryo: Engine Calisiyor Ama Islem Yapmiyor

**Belirtiler:**
- Dashboard'da cycle suresi 0 veya cok yuksek
- Yeni sinyal/islem uretilmiyor
- Health endpoint'te `engine_alive: true` ama `last_cycle_ts` eski

**Olasi Nedenler ve Cozumler:**

| Neden | Teshis | Cozum |
|-------|--------|-------|
| Kill-switch aktif (L2) | Dashboard → Risk paneli: `can_trade: false` | Beklenen davranis; cooldown suresi dolsun veya risk parametrelerini incele |
| OLAY rejimi | Log'da `OLAY rejimi aktif` | Piyasa kapanicaya kadar bekle; normal ise BABA parametreleri incele |
| Kontrat deaktif | Log'da `Sagliksiz kontrat deaktif edildi` | MT5'te ilgili kontratin verisi geliyormu kontrol et |
| Cycle exception | Log'da `CYCLE_ERROR` | Stack trace'i incele; ilgili moduldeki hatanin kokeni bul |
| MT5 veri gelmiyor | Log'da `fetch_bars bos dondu` | MT5 terminalini kontrol et, market acik mi? |

---

### 1.5 Senaryo: H-Engine Pozisyon Kapatamıyor (SL/TP Loop)

**Belirtiler:**
- Log'da tekrarlayan `close_position basarisiz` kayitlari
- Ayni ticket surekli kapatilmaya calisiliyor
- H-Engine pozisyon ACTIVE ama SL/TP hit etmis

**Ne Olur:**
1. Software SLTP mode'da SL/TP tetiklenir
2. `close_position()` cagirilir → MT5 baglantisi flaky → null donus
3. Pozisyon ACTIVE kalir → sonraki cycle (10sn) tekrar dener
4. Sonsuz retry dongusu baslar

**Kurtarma:**
```
1. MT5 terminalinden ilgili pozisyonu MANUEL kapat
2. USTAT'i yeniden baslat (H-Engine state DB'den restore edilir)
3. Kapatilan pozisyon DB'de CLOSED olarak guncellenecektir
```

---

## BOLUM 2: COKMEMESI ICIN NE YAPILMALI — SISTEM GUCLENDRME PLANI

### 2.1 Oncelik 1: Kritik Duzeltmeler (HEMEN)

#### 2.1.1 Engine Watchdog → Otomatik Restart
**Sorun:** Engine thread crash ederse API hayatta kalir ama olu veri sunar.
**Cozum:** `server.py`'deki watchdog exception yakaladginda API'yi de kapatmali:
```
_engine_watchdog() → Exception → logger.critical() → sys.exit(1)
```
**Etkilenen dosyalar:** `api/server.py:102-116`

#### 2.1.2 MT5 Reconnect Timeout
**Sorun:** MT5 heartbeat basarisiz olursa tek deneme yapilir, timeout siniri yok.
**Cozum:**
- Heartbeat'te reconnect denemesini 3'e cikar
- Her denemeye 10sn timeout koy
- Toplam reconnect suresi max 30sn ile sinirla
**Etkilenen dosyalar:** `engine/main.py:678-691`, `engine/mt5_bridge.py:221-310`

#### 2.1.3 DB Integrity Check (Baslangicta)
**Sorun:** Bozuk DB sessizce calisir → yanlis veri, hatali islem.
**Cozum:** Engine baslarken `PRAGMA integrity_check` calistir:
```python
result = self._conn.execute("PRAGMA integrity_check").fetchone()[0]
if result != "ok":
    raise RuntimeError(f"DB bozuk: {result}. Yedekten geri yukleyin.")
```
**Etkilenen dosyalar:** `engine/database.py:210-220`

#### 2.1.4 Frontend Error Boundary
**Sorun:** Tek bilesen hatasi tum React agacini cokertiyor.
**Cozum:** Her ana bilesen (Dashboard, Monitor, Performance, vb.) ErrorBoundary ile sarilmali.
**Etkilenen dosyalar:** Yeni: `desktop/src/components/ErrorBoundary.jsx`, tum sayfa bilesenlerini sar

#### 2.1.5 Event Bus Exception Logging
**Sorun:** Listener hatasi yutulur (`except: pass`), event kaybolur.
**Cozum:**
```python
except Exception as e:
    logger.error(f"Event listener hatasi [{event}]: {e}")
```
**Etkilenen dosyalar:** `engine/event_bus.py:28-31`

---

### 2.2 Oncelik 2: Yuksek Risk Duzeltmeleri (BU HAFTA)

#### 2.2.1 State Restore Atomicity
**Sorun:** BABA restore basarili, OGUL restore basarisiz → risk limitleri eski, trade'ler yeni.
**Cozum:** Tum restore islemleri try-catch icinde; herhangi biri basarisiz → tamamen rollback, clean start.
**Etkilenen dosyalar:** `engine/main.py:867-899`

#### 2.2.2 H-Engine Kapatma Retry Limiti
**Sorun:** Software SL/TP mode'da kapatma basarisiz → sonsuz retry loop.
**Cozum:**
- Max 3 retry; basarisiz → pozisyon state = `CLOSE_FAILED`
- `CLOSE_FAILED` state icin alert event emit et
- Kullaniciya "MANUEL KAPATMA GEREKLI" bildir
**Etkilenen dosyalar:** `engine/h_engine.py:536-599`

#### 2.2.3 Order Lock Timeout
**Sorun:** MT5Bridge `_order_lock` timeout yok → deadlock riski.
**Cozum:**
```python
acquired = self._order_lock.acquire(timeout=5.0)
if not acquired:
    raise TimeoutError("Emir kilidi 5sn icerisinde alinamadi")
```
**Etkilenen dosyalar:** `engine/mt5_bridge.py:108, 560-795`

#### 2.2.4 API Orphan Process Temizligi
**Sorun:** Electron kapandiginda API process'i arka planda kalabilir.
**Cozum:** `killApiProcess()` PID dosya bulunamazsa `tasklist` ile python.exe process'lerini tarayip port 8000'i dinleyeni bulsun.
**Etkilenen dosyalar:** `desktop/main.js:441-458`

#### 2.2.5 DB Backup Iyilestirmesi
**Sorun:** `shutil.copy2()` ile sicak kopyalama → WAL aktifken bozuk yedek riski.
**Cozum:** SQLite `backup()` API'sini kullan:
```python
backup_conn = sqlite3.connect(backup_path)
self._conn.backup(backup_conn)
backup_conn.close()
```
**Etkilenen dosyalar:** `engine/database.py:222-245`

---

### 2.3 Oncelik 3: Orta Vadeli Iyilestirmeler (BU AY)

#### 2.3.1 WebSocket Reconnection Guclendirilmesi
- Server-initiated heartbeat (5sn'de bir ping frame)
- Frontend'te exponential backoff + jitter
- Stale data detection (WS mesaj timestamp > 10sn ise uyari banner)
**Etkilenen dosyalar:** `api/routes/live.py`, `desktop/src/services/api.js`

#### 2.3.2 API Retry Wrapper
- Tum API cagrilarina retry middleware (max 3 deneme, exponential backoff)
- Timeout'u 5sn → 10sn'ye cikar (yavaş ağ icin)
**Etkilenen dosyalar:** `desktop/src/services/api.js:18-21`

#### 2.3.3 Memory Leak Onleme
- Tum setInterval/setTimeout cleanup'larini dogrula
- useCallback dependency array'lerini gozden gecir
- Recharts chart data downsampling (max 365 nokta)
**Etkilenen dosyalar:** `Dashboard.jsx`, `Performance.jsx`, `Monitor.jsx`

#### 2.3.4 Correlation ID
- Trade/emir akisinda benzersiz ID: MT5Bridge emir gonderirken, OGUL sinyal uretirken, event_bus emit ederken ayni ID loglanir
- Log'da `correlation_id=abc123` filtresiyle trade basdan sona izlenebilir
**Etkilenen dosyalar:** `engine/mt5_bridge.py`, `engine/event_bus.py`, loglama katmani

#### 2.3.5 Disk Alani Izleme
- Engine baslarken disk alani kontrolu
- %80 dolu → uyari log
- %95 dolu → eski yedekleri sil + engine durdur
**Etkilenen dosyalar:** `engine/main.py` (startup), `engine/database.py` (backup)

---

### 2.4 Oncelik 4: Uzun Vadeli Iyilestirmeler (GELECEK AY)

| # | Iyilestirme | Etki | Tahmini Sure |
|---|-------------|------|--------------|
| 1 | Unit test iskeleti (engine/utils, model siniflari) | Regresyon onleme | 3-4 gun |
| 2 | API smoke testleri (/health, /status, /risk) | Deploy oncesi dogrulama | 1-2 gun |
| 3 | PR sablonu (etkilenen moduller, handover guncellemesi) | Degisiklik kontrolu | 0.5 gun |
| 4 | Baseline performans olcum protokolu | Performans regresyon tespiti | 1-2 gun |
| 5 | Schema versioning (migration tracker table) | Gelecekte uyumluluk | 1 gun |
| 6 | Server-side pagination (TradeHistory) | Buyuk veri seti performansi | 1 gun |

---

## BOLUM 3: KATMAN BAZLI RISK HARITASI

### 3.1 Engine Katmani

| Bulgu | Risk | Durum | Konum |
|-------|------|-------|-------|
| MT5 reconnect timeout yok | KRITIK | Acik | main.py:678-691 |
| State restore atomic degil | YUKSEK | Acik | main.py:867-899 |
| DB kapanisi lock riski | YUKSEK | Acik | main.py:290-293 |
| Pozisyon kapanis senkron kaybı (restart) | ORTA | Acik | main.py:533-585 |
| Cycle error → silent devam | ORTA | Tasarim gereği | main.py:353-362 |
| H-Engine SL/TP retry loop | YUKSEK | Acik | h_engine.py:536-599 |
| H-Engine breakeven modify basarisiz | ORTA | Acik | h_engine.py:651-657 |
| Event bus exception yutma | DUSUK | Acik | event_bus.py:28-31 |
| Config parse hatasi sessiz | DUSUK | Acik | config.py:40-44 |
| Data pipeline cache stale kontrolu yok | ORTA | Acik | data_pipeline.py:111-123 |

### 3.2 Veritabani Katmani

| Bulgu | Risk | Durum | Konum |
|-------|------|-------|-------|
| Integrity check yok | COK YUKSEK | Acik | database.py:210-220 |
| Sicak kopyalama (hot copy) backup | YUKSEK | Acik | database.py:222-245 |
| Sync loop N+1 query | ORTA | Acik | database.py:533-681 |
| Transaction partial commit riski | YUKSEK | Acik | database.py:533-681 |
| Restore fonksiyonu yok | YUKSEK | Acik | - |
| Migration silent fail | ORTA | Acik | database.py:268-284 |
| Disk dolu senaryosu | YUKSEK | Acik | - |
| Hibrit state race condition | YUKSEK | Acik | database.py:1185-1327 |

### 3.3 API ve Baslama Katmani

| Bulgu | Risk | Durum | Konum |
|-------|------|-------|-------|
| Engine crash → API hayatta | YUKSEK | Acik | server.py:102-116 |
| Engine baslamazsa API 200 OK | YUKSEK | Acik | server.py:113-116 |
| WS event drain race condition | YUKSEK | Acik | live.py:89-103 |
| API orphan process | YUKSEK | Acik | main.js:441-458 |
| Vite PID tracking yok | ORTA | Acik | start_ustat.py:197-233 |
| Port killer race condition | ORTA | Acik | start_ustat.py:77-105 |
| Electron crash handler yok | ORTA | Acik | main.js |
| IPC handler timeout yok | ORTA | Acik | main.js:313-346 |
| WS broadcast stale client | ORTA | Acik | live.py:324-340 |

### 3.4 Frontend Katmani

| Bulgu | Risk | Durum | Konum |
|-------|------|-------|-------|
| Error Boundary yok | KRITIK | Acik | Tum bilesenler |
| WS reconnection zayif | KRITIK | Acik | api.js:387-488 |
| API retry mekanizmasi yok | KRITIK | Acik | api.js:18-21 |
| setInterval memory leak | YUKSEK | Acik | Dashboard.jsx |
| closePosition error handling | YUKSEK | Acik | api.js:75-83 |
| State race (HybridTrade unmount) | YUKSEK | Acik | HybridTrade.jsx:138-156 |
| Recharts memory leak | YUKSEK | Acik | Performance.jsx:400-442 |
| Monitor 6 paralel polling | ORTA | Acik | Monitor.jsx:149-175 |
| Date unit mismatch (ms vs s) | ORTA | Acik | Monitor.jsx:180, Dashboard.jsx:162 |
| PnL live vs REST race | ORTA | Acik | Dashboard.jsx:273-277 |

---

## BOLUM 4: PERFORMANS KORUMA STRATEJISI

### 4.1 Mevcut Performans Profili

| Metrik | Deger | Hedef | Durum |
|--------|-------|-------|-------|
| Cycle suresi | 2-5 sn (tipik) | < 10 sn | OK |
| DB islem suresi | ~3-5 ms/query | < 50 ms | OK |
| API yanit suresi | ~50-200 ms | < 500 ms | OK |
| RAM kullanimi | ~150-300 MB | < 500 MB | OK |
| DB boyutu | ~167 MB | < 500 MB | OK |
| WebSocket latency | ~2-5 sn | < 10 sn | OK |

### 4.2 Performans Bozulma Riskleri

| Risk | Tetikleyici | Etki | Onlem |
|------|-----------|------|-------|
| Cycle suresi artisi | Yeni indicator/strateji | > 10sn → gecikme | Her degisiklikte cycle_ms olc |
| DB buyumesi | Trade gecmisi birikimi | Sorgu yavaslamasi | 60 gun cleanup aktif |
| Memory leak | setInterval/Recharts | RAM > 1GB → crash | Interval cleanup, data downsampling |
| API yavaslama | Concurrent query | Lock timeout | Connection cache, async |
| Frontend donma | 1000+ trade render | UI freeze | Server-side pagination |
| WS flooding | 8 bilesen polling | 1700+ req/min | Shared polling context |

### 4.3 Performans Izleme Kontrol Listesi

Her buyuk degisiklik oncesi/sonrasi:
```
[ ] Cycle suresi: health endpoint'ten cycle_ms olc (oncesi vs sonrasi)
[ ] RAM: Task Manager'dan python.exe bellek kullanimi not et
[ ] DB boyutu: trades.db dosya boyutu kontrol et
[ ] API: /api/health yanit suresi olc
[ ] Frontend: Chrome DevTools → Performance tab → 60fps kontrol et
```

---

## BOLUM 5: ACIL DURUM PROSEDURU (RUNBOOK)

### Adim 1: Semptomu Tani

| Semptom | Olasi Neden | Git → |
|---------|------------|-------|
| USTAT penceresi kapali | Crash / kapatilmis | Senaryo 1.2 |
| "Baglanti Yok" uyarisi | MT5 koptu | Senaryo 1.1 |
| Veriler guncellenmiyor | Engine durmus / DB kitlendi | Senaryo 1.3, 1.4 |
| Pozisyon kapatilmiyor | H-Engine loop | Senaryo 1.5 |
| USTAT baslatilmiyor | Port catismasi / eski process | Senaryo 1.2 |
| Beyaz ekran | Frontend crash | Error Boundary yok |

### Adim 2: Hizli Kontrol

```bash
# 1. Process'ler calisiyor mu?
tasklist | findstr "python electron node"

# 2. Portlar acik mi?
netstat -ano | findstr ":8000"
netstat -ano | findstr ":5173"

# 3. API yanitliyor mu?
curl http://127.0.0.1:8000/api/health

# 4. Log'da son hatalar ne?
# C:\USTAT\logs\ klasorundeki en son log dosyasini ac
# ENGINE_STOP, CYCLE_ERROR, MT5_RECONNECT, SQL hatasi ara
```

### Adim 3: Kurtarma

```
Basit cozum:  USTAT'i kapat → start_ustat.bat ile ac
Orta cozum:   Task Manager'dan tum process'leri kapat → PID dosyalarini sil → baslat
Zor cozum:    DB yedekten geri yukle → baslat
Son care:     trades.db sil (veri kaybi!) → temiz baslat
```

---

## BOLUM 6: OZET VE SONUC

### Mevcut Durum Puanlama

| Kategori | Puan (10 uzerinden) | Aciklama |
|----------|---------------------|----------|
| Normal calisma | 8/10 | Normal kosullarda stabil |
| Cokme kurtarma | 4/10 | Manuel mudahale gerekli, otomasyon yok |
| State tutarliligi | 5/10 | Partial restore riski |
| Performans izleme | 3/10 | Baseline yok, otomatik alarm yok |
| Hata teshisi | 5/10 | Correlation ID yok, sessiz hatalar var |
| Frontend dayaniklilik | 4/10 | Error boundary yok, memory leak riski |
| Veritabani guvenliği | 5/10 | WAL iyi ama integrity check yok |

### Uygulama Sirasi Onerisi

```
HEMEN (1-2 gun):
  ├─ DB integrity check ekle
  ├─ Event bus exception logging
  ├─ Engine watchdog → sys.exit(1)
  └─ Frontend Error Boundary

BU HAFTA (3-5 gun):
  ├─ MT5 reconnect timeout
  ├─ State restore atomicity
  ├─ H-Engine retry limiti
  ├─ Order lock timeout
  └─ API orphan process cleanup

BU AY (1-2 hafta):
  ├─ DB backup iyilestirmesi (sqlite3.backup)
  ├─ WS reconnection guclendirilmesi
  ├─ API retry wrapper
  ├─ Memory leak duzeltmeleri
  └─ Correlation ID

GELECEK AY (2-3 hafta):
  ├─ Unit test iskeleti
  ├─ Baseline performans olcum
  ├─ Server-side pagination
  ├─ Schema versioning
  └─ Disk alani izleme
```

---

*Rapor: Claude Opus 4.6 tarafindan 5 paralel analiz ile hazirlanmistir.*
*Analiz kapsami: engine/, api/, desktop/, config/, USTAT_HANDOVER/ — toplam ~80+ bulgu*
