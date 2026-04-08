# ÜSTAT v5.9 — MT5 Bağlantı, Veri Çekme ve OTP Süreci Tam Spesifikasyonu

**Tarih:** 4 Nisan 2026
**Kaynak:** mt5_bridge.py, mt5Manager.js, LockScreen.jsx, mt5Launcher.js, data_pipeline.py

---

## 1. GENEL MİMARİ

ÜSTAT ile MetaTrader 5 arasındaki iletişim 3 katmanlı bir yapıdadır:

```
┌─────────────────────────────────────────────────────────────────┐
│  KATMAN 1: Electron (desktop/mt5Manager.js)                     │
│  • MT5 terminal64.exe başlatma (spawn, fire-and-forget)         │
│  • Kimlik bilgisi saklama (DPAPI + safeStorage)                 │
│  • OTP kodu iletme (admin Python + PowerShell)                  │
│  • MT5 süreç kontrolü (tasklist)                                │
└───────────────────────────┬─────────────────────────────────────┘
                            │ IPC (preload.js)
┌───────────────────────────▼─────────────────────────────────────┐
│  KATMAN 2: FastAPI (api/routes/mt5_verify.py)                   │
│  • /api/mt5/verify endpoint                                      │
│  • Bağlantı doğrulama (mt5.initialize + account_info)           │
│  • Chrome/tarayıcı modu fallback                                │
└───────────────────────────┬─────────────────────────────────────┘
                            │ Python import
┌───────────────────────────▼─────────────────────────────────────┐
│  KATMAN 3: Engine (engine/mt5_bridge.py)                        │
│  • MetaTrader5 Python kütüphanesi (C++ DLL)                     │
│  • Bağlantı yönetimi (connect, heartbeat, reconnect)            │
│  • Veri çekme (OHLCV, tick, hesap, pozisyon)                    │
│  • Emir gönderme (send_order, close_position, modify_position)  │
│  • Circuit breaker, sembol çözümleme, VİOP netting              │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. BAŞLATMA AKIŞI (Uygulama Açılışından Dashboard'a Kadar)

### 2.1 Tam Akış Şeması

```
Kullanıcı masaüstü kısayoluna tıklar
    │
    ▼
start_ustat.py çalışır (Admin yetkisi, wscript.exe ile UAC)
    │
    ├── Port temizleme (8000, 5173)
    ├── FastAPI başlat (uvicorn, port 8000) + Engine thread
    ├── Vite başlat (port 5173)
    ├── Electron başlat (localhost:5173 yükler)
    │
    ▼
Electron penceresi açılır → LockScreen.jsx görünür
    │
    ▼
[ADIM 1: CHECKING] Kaydedilmiş credential var mı?
    │
    ├── EVET → DPAPI ile şifreyi çöz → ADIM 3'e git
    │
    └── HAYIR → ADIM 2'ye git
    │
    ▼
[ADIM 2: CREDENTIALS] Kullanıcıdan bilgi iste
    │
    Form alanları: Sunucu Adı, Hesap No, Şifre
    │
    "Bağlan" butonuna basınca:
    ├── Şifre DPAPI ile şifrelenir → %APPDATA%/ustat-desktop/mt5-credentials.json
    │
    ▼
[ADIM 3: MT5 BAŞLATMA — Fire-and-forget]
    │
    ├── terminal64.exe çalışıyor mu? (tasklist kontrolü)
    │   ├── EVET → Zaten çalışıyor, bağlantı kontrol et
    │   │   ├── Bağlıysa → ADIM 6'ya atla (Dashboard)
    │   │   └── Bağlı değilse → ADIM 4'e git (OTP gerekli)
    │   │
    │   └── HAYIR → spawn() ile başlat
    │       spawn('C:\Program Files\GCM MT5 Terminal\terminal64.exe',
    │             ['/login:HESAP', '/server:SUNUCU', '/password:ŞİFRE'],
    │             { detached: true, stdio: 'ignore' })
    │       child.unref() → parent'tan bağımsız
    │       HEMEN dön, bekleme YOK
    │
    ▼
[ADIM 4: WAITING — OTP Bekleme Ekranı]
    │
    Ekranda görünen:
    ├── Hesap bilgileri kartı (sunucu, hesap no, maskeli şifre)
    ├── "OTP Kodunuzu Girin" mesajı
    ├── OTP input alanı (4-8 haneli rakam)
    ├── "OTP Gönder" butonu
    ├── "Farklı Hesap" linki
    ├── Spinner + "MT5 bağlantısı bekleniyor... Xsn"
    │
    İKİ PARALEL İŞLEM:
    │
    ├── [A] POLLING: Her 3 saniyede bir bağlantı kontrolü
    │   │   verifyMT5Connection() → GET /api/mt5/verify
    │   │   → Python mt5.initialize() + mt5.account_info()
    │   │   120 saniye timeout — aşılırsa ERROR durumuna düşer
    │   │
    │   └── Bağlantı algılandıysa → ADIM 6'ya git
    │
    └── [B] OTP GÖNDERİMİ: Kullanıcı OTP kodunu girer
        │   "OTP Gönder" butonuna basar
        │   → ADIM 5'e git
        │
        VEYA kullanıcı OTP'yi doğrudan MT5 dialoguna girer
        → Polling bağlantıyı algılar → ADIM 6'ya git
    │
    ▼
[ADIM 5: OTP GÖNDERİMİ — Admin Python]
    │   (Detay bölüm 3'te)
    │
    ▼
[ADIM 6: CONNECTED — Dashboard'a Geçiş]
    │
    setConnStatus('connected')
    setStatusMsg('Bağlantı başarılı!')
    800ms bekle (kullanıcı mesajı görsün)
    onUnlock() → LockScreen kapanır → Dashboard açılır
    │
    ▼
Engine ana döngüsü başlar:
    mt5_bridge.connect(launch=True) → MT5 Python API ile bağlan
    _resolve_symbols() → 15 kontratı MT5 gerçek adlarına eşle
    Her 10 saniyede: heartbeat → data → BABA → OĞUL → H-Engine → ÜSTAT
```

### 2.2 Polling Sabitleri (LockScreen)

| Sabit | Değer | Açıklama |
|-------|-------|----------|
| `POLL_INTERVAL` | 3000ms | Bağlantı kontrol aralığı |
| `POLL_TIMEOUT` | 120000ms | Maksimum bekleme süresi |

### 2.3 ConnectionStatus Durumları

| Durum | Anlamı | Görsel |
|-------|--------|--------|
| `idle` | Başlangıç, henüz bir şey yapılmadı | — |
| `connecting` | MT5'e bağlanıyor / polling devam ediyor | Sarı dot + "MT5'e bağlanıyor..." |
| `connected` | Bağlantı başarılı | Yeşil dot + "Bağlandı" |
| `error` | Bağlantı hatası | Kırmızı dot + "Bağlantı Hatası" |

---

## 3. OTP (Tek Kullanımlık Şifre) MEKANİZMASI

### 3.1 OTP Neden Gerekli?

GCM Capital, MT5 hesabına girişte 2FA (iki faktörlü doğrulama) zorunlu kılıyor. MT5 terminaline login olurken bir OTP dialog penceresi açılıyor. Bu pencereye 4-8 haneli kod girilmeden MT5'e Python API ile bağlanılamıyor.

### 3.2 OTP İki Yolu

**Yol A — ÜSTAT üzerinden otomatik (admin Python):**
1. Kullanıcı ÜSTAT'ın kilit ekranındaki OTP inputuna kodu yazar
2. "OTP Gönder" butonuna basar
3. Kod admin Python scripti ile MT5 dialog penceresine iletilir

**Yol B — Doğrudan MT5'e manuel:**
1. Kullanıcı MT5'in kendi OTP dialog penceresine kodu girer
2. ÜSTAT'ın arka plan polling'i bağlantıyı algılar
3. Otomatik olarak dashboard'a geçilir

### 3.3 OTP Gönderim Mekanizması (Yol A — Detay)

```
Kullanıcı ÜSTAT'ta OTP kodunu girer → "OTP Gönder" butonuna basar
    │
    ▼
[React] LockScreen.jsx → handleOTPSubmit()
    │   Doğrulama: /^\d{4,8}$/ (4-8 haneli rakam)
    │
    ▼
[Service] mt5Launcher.js → sendOTP(otpCode)
    │   window.electronAPI.sendOTP(code) çağrısı
    │
    ▼
[IPC] preload.js → ipcRenderer.invoke('mt5:send-otp', code)
    │
    ▼
[Main Process] mt5Manager.js → sendOTPToMT5(otpCode)
    │
    ├── 1. Temp dosya yolu oluştur: %TEMP%/ustat_otp_<timestamp>.json
    │
    ├── 2. PowerShell komutu hazırla:
    │      Start-Process
    │        -FilePath 'C:\Users\pc\...\Python314\python.exe'
    │        -ArgumentList 'scripts/mt5_automator.py --otp XXXXXX --output tempfile'
    │        -Verb RunAs          ← ADMİN YETKİSİ İSTER (UAC penceresi açılır)
    │        -Wait                ← Script bitene kadar bekle
    │        -WindowStyle Hidden  ← Görünmez pencere
    │
    ├── 3. PowerShell çalıştır:
    │      spawn('powershell.exe', ['-NoProfile', '-Command', psCommand])
    │
    │      [UAC Dialog] → Kullanıcı "Evet" tıklar
    │          │
    │          ▼
    │      [Admin Python] mt5_automator.py --otp XXXXXX --output tempfile
    │          │
    │          ├── MT5 OTP dialog penceresini bul (Windows API)
    │          ├── OTP kodunu pencereye yaz (SendMessage)
    │          ├── Sonucu tempfile'a JSON olarak yaz
    │          └── Çık
    │
    ├── 4. PowerShell biter → temp dosyayı oku → JSON parse
    │
    └── 5. Sonucu LockScreen'e döndür
         │
         Başarılıysa: polling bağlantı algılayınca dashboard'a geçer
         Başarısızsa: hata mesajı gösterilir
```

### 3.4 OTP Admin Gereksinimine Neden

**Windows UIPI (User Interface Privilege Isolation) kuralı:**
MT5 terminal64.exe admin (elevated) olarak çalışıyor. Normal (non-elevated) bir process, admin pencereye SendMessage/PostMessage gönderemez. Bu Windows güvenlik katmanıdır. Bu yüzden Python scriptinin de admin olarak çalıştırılması gerekiyor (`-Verb RunAs`).

### 3.5 OTP Timeout ve Hata Durumları

| Durum | Süre | Sonuç |
|-------|------|-------|
| UAC onayı bekleme | 30sn max | Timeout → "UAC onayladınız mı?" mesajı |
| UAC reddedildi | — | "OTP gönderilemedi. UAC reddedilmiş olabilir." |
| Script çalışmadı | — | "OTP sonuç dosyası bulunamadı." |
| Geçersiz OTP kodu | — | "Geçersiz OTP kodu. 4-8 haneli rakam olmalı." |

---

## 4. KİMLİK BİLGİSİ YÖNETİMİ (Credential Management)

### 4.1 Depolama

Dosya: `%APPDATA%/ustat-desktop/mt5-credentials.json`

```json
{
  "server": "GCMFuturesTR-Demo",
  "login": "12345678",
  "encryptedPassword": "AQAAANCMnd8BFdERj...",  ← DPAPI ile şifrelenmiş (base64)
  "savedAt": "2026-04-04T10:30:00.000Z"
}
```

### 4.2 Şifreleme

Electron'un `safeStorage` API'si kullanılıyor. Bu API, Windows'ta **DPAPI (Data Protection API)** üzerinden çalışır.

- `safeStorage.encryptString(password)` → Buffer → base64 string olarak saklanır
- `safeStorage.decryptString(Buffer.from(base64, 'base64'))` → plaintext şifre
- DPAPI, şifrelemeyi Windows kullanıcı hesabına bağlar — başka kullanıcı/bilgisayar çözemez
- Chrome/tarayıcı modunda DPAPI erişimi YOK — bu yüzden önce Electron'dan bağlanılmalı

### 4.3 Credential Akış

| İşlem | Fonksiyon | Açıklama |
|-------|-----------|----------|
| Oku | `loadCredentials()` | DPAPI ile çöz, `{ server, login, password }` döndür |
| Kaydet | `saveCredentials(creds)` | Şifreyi DPAPI ile şifrele, JSON olarak yaz |
| Sil | `clearCredentials()` | Dosyayı sil ("Farklı Hesap" butonu) |
| Maskeli oku | `getSavedCredentialsMasked()` | `{ server, login, passwordMask: '******' }` |

---

## 5. MT5 BAĞLANTI YÖNETİMİ (Engine Tarafı — mt5_bridge.py)

### 5.1 connect() — İlk Bağlantı

```python
def connect(self, launch: bool = False) -> bool:
```

**İki mod:**

| Parametre | Amaç | MT5 kapalıysa | Deneme sayısı |
|-----------|-------|---------------|---------------|
| `launch=True` | İlk başlatma | Açar (path verilir) | 5 deneme |
| `launch=False` | Reconnect | Açmaz (path yok) | 3 deneme |

**Bağlantı adımları:**
1. Config'den `mt5.path`, `mt5.login`, `mt5.server` okunur
2. `mt5.initialize()` çağrılır (launch modda `path` eklenir)
3. Başarısızsa artan bekleme ile tekrar dener: 2sn → 4sn → 8sn → 16sn → 32sn
4. Başarılıysa `_resolve_symbols()` çağrılır (sembol eşleme)
5. `mt5.account_info()` ile hesap doğrulanır
6. `_connected = True`, `_last_heartbeat` güncellenir

**Başarısız olursa:** 5 (veya 3) deneme sonunda `_connected = False`, CRITICAL log yazılır.

### 5.2 heartbeat() — 10 Saniyelik Yaşam Kontrolü

Her 10 saniyede bir ana döngü tarafından çağrılır.

```
heartbeat() çağrılır
    │
    ├── Son heartbeat'ten 10sn geçmediyse → hemen True dön (skip)
    │
    ├── mt5.terminal_info() çağır (_safe_call ile timeout korumalı)
    │   │
    │   ├── None döndü → Bağlantı kopmuş → reconnect dene
    │   │
    │   ├── info.connected == False → Terminal bağlantı yok → reconnect dene
    │   │
    │   └── Başarılı → ping süresini kaydet → True dön
    │
    └── Exception → Bağlantı kopmuş → reconnect dene
```

**Reconnect akışı:** `_ensure_connection()` → `connect(launch=False)` → 3 deneme, artan bekleme

### 5.3 _safe_call() — Timeout + Circuit Breaker Koruyucu

Her MT5 API çağrısı bu fonksiyon üzerinden yapılır.

```python
def _safe_call(self, func, *args, timeout=8.0, **kwargs):
```

**İki farklı çalışma modu:**

| İşlem Türü | Fonksiyon | Çalışma Şekli | Neden |
|------------|-----------|---------------|-------|
| OKUMA | copy_rates, symbol_info, terminal_info, account_info, positions_get | ThreadPoolExecutor + timeout | Thread-safe |
| YAZMA | order_send | Doğrudan çağrı (executor YOK) | MT5 C extension worker thread'den reddediyor |

**Circuit Breaker mekanizması:**

```
Her başarısız MT5 çağrısı → _cb_failures sayacı +1
    │
    5 ardışık hata (CB_FAILURE_THRESHOLD) → Circuit breaker AÇILIR
    │
    30 saniye boyunca TÜM MT5 çağrıları engellenir (ConnectionError fırlatılır)
    │
    30sn sonra TEK bir "probe" denemesine izin verilir
    │
    ├── Probe başarılı → Circuit breaker kapanır, sayaç sıfırlanır
    └── Probe başarısız → Yeni 30sn bekleme başlar
```

| Sabit | Değer | Açıklama |
|-------|-------|----------|
| `CB_FAILURE_THRESHOLD` | 5 | Devre kesme eşiği |
| `CB_COOLDOWN_SECS` | 30sn | Bekleme süresi |
| `CB_PROBE_TIMEOUT` | 5sn | Probe çağrı timeout'u |
| `MT5_CALL_TIMEOUT` | 8sn | Normal çağrı timeout'u |

---

## 6. SEMBOL ÇÖZÜMLEME (VİOP Vade Sistemi)

### 6.1 Problem

VİOP kontrat adları vade soneki içerir: `F_THYAO0226` (Şubat 2026 vadeli). Her ay kontrat adı değişir. ÜSTAT kodda "base" isimler kullanır (`F_THYAO`), MT5'te gerçek ad farklıdır.

### 6.2 Çözüm: _resolve_symbols()

15 izlenen kontrat + USDTRY için MT5'teki gerçek ada eşleme yapılır.

```
İzlenen kontratlar (WATCHED_SYMBOLS):
    F_THYAO, F_AKBNK, F_ASELS, F_TCELL, F_HALKB,
    F_PGSUS, F_GUBRF, F_EKGYO, F_SOKM,  F_TKFEN,
    F_OYAKC, F_BRSAN, F_AKSEN, F_ASTOR, F_KONTR
    + USDTRY (BABA şok kontrolü için)
```

**İki yöntem:**

**YÖNTEM 1 — Vade Günü (otomatik geçiş):**
- Bugün VİOP vade günüyse → sonraki ayın suffix'i hesaplanır (ör. Mart sonu → "0426")
- Tüm kontratlar doğrudan bu suffix ile eşlenir
- Örnek: F_THYAO → F_THYAO0426

**YÖNTEM 2 — Normal Gün:**
- Base ile başlayan tüm MT5 sembollerini bul
- Artan sırala, her birini `mt5.symbol_select()` ile aktive et
- `trade_mode >= 4` (FULL) olan ilk kontratı seç
- CLOSEONLY/DISABLED olanları atla

**Eşleme haritaları:**
- `_symbol_map`: base → MT5 gerçek ad (ör. `F_THYAO → F_THYAO0226`)
- `_reverse_map`: MT5 gerçek ad → base (ör. `F_THYAO0226 → F_THYAO`)
- Atomik güncelleme: `_map_lock` ile tüm map tek seferde değiştirilir

### 6.3 Periyodik Vade Kontrolü: check_trade_modes()

Ana döngüden saatlik çağrılır. Mevcut map'teki kontratların trade_mode'unu kontrol eder. CLOSEONLY/DISABLED tespit ederse otomatik re-resolve tetikler.

---

## 7. VERİ ÇEKME (DataPipeline — data_pipeline.py)

### 7.1 Çekilen Veri Türleri

| Veri | Kaynak | Aralık | Detay |
|------|--------|--------|-------|
| OHLCV (bar verisi) | `mt5.copy_rates_from_pos()` | Timeframe'e göre | M1: 500 bar, M5: 300, M15: 200, H1: 100 |
| Tick (anlık fiyat) | `mt5.symbol_info_tick()` | Her 10sn | bid, ask, spread, zaman |
| Hesap bilgisi | `mt5.account_info()` | Her 10sn | bakiye, equity, margin, free_margin |
| Açık pozisyonlar | `mt5.positions_get()` | Her 10sn | ticket, symbol, volume, price, pnl |
| Sembol bilgisi | `mt5.symbol_info()` | Bağlantıda | point, tick_value, volume_min/max, spread |
| Terminal durumu | `mt5.terminal_info()` | Her 10sn (heartbeat) | Bağlantı durumu |

### 7.2 OHLCV Çekme Detayı

**Timeframe'ler ve bar sayıları:**

| Timeframe | MT5 sabiti | Bar sayısı | Beklenen bar aralığı |
|-----------|-----------|-----------|---------------------|
| M1 | `TIMEFRAME_M1` | 500 | 60 saniye |
| M5 | `TIMEFRAME_M5` | 300 | 300 saniye |
| M15 | `TIMEFRAME_M15` | 200 | 900 saniye |
| H1 | `TIMEFRAME_H1` | 100 | 3600 saniye |

**Çekme süreci:**
```
mt5_bridge.get_bars(symbol, timeframe, count)
    │
    ├── _ensure_connection() — bağlantı yoksa reconnect
    ├── _to_mt5(symbol) — base adı MT5 gerçek ada çevir
    ├── _safe_call(mt5.copy_rates_from_pos, mt5_name, timeframe, 0, count)
    │   └── ThreadPoolExecutor + 8sn timeout
    ├── DataFrame'e çevir (sütunlar: time, open, high, low, close, tick_volume, spread, real_volume)
    └── time sütununu datetime'a çevir (pd.to_datetime, unit='s')
```

**Paralel çekme DEVRE DIŞI:**
MT5 C++ DLL thread-safe DEĞİL. `MAX_WORKERS = 1` ile sıralı çalışma garanti altında. GIL sadece Python nesnelerini korur, C extension internal state'i KORUMAZ.

### 7.3 Tick Çekme

```
mt5_bridge.get_tick(symbol)
    │
    ├── _to_mt5(symbol)
    ├── _safe_call(mt5.symbol_info_tick, mt5_name)
    └── Tick(symbol=base_name, bid, ask, spread=ask-bid, time)
```

### 7.4 Veri Temizleme Kuralları

| Kural | Eşik | Eylem |
|-------|------|-------|
| Gap tespiti | Bar arası beklenen sürenin üstü | Logla |
| Outlier reddi | Z-score > 5.0 | Barı reddet |
| Eksik veri | 3+ ardışık eksik bar | Kontratı deaktif et |
| Bayatlık | Timeframe × 3.0 çarpan | STALE uyarısı |
| Deaktivasyon timeframe | Sadece M15 ve H1 | M1/M5'te sahte alarm önlenir |

### 7.5 Cache Sistemi (MT5'e Doğrudan Gitmeyi Önleme)

DataPipeline, MT5'ten çektiği verileri bellekte cache'ler:
- `latest_ticks`: Sembol bazlı son tick verileri
- `latest_account`: Son hesap bilgisi (AccountInfo)
- `latest_positions`: Son pozisyon listesi
- `_cache_time`: Son cache güncelleme zamanı

WebSocket ve API endpoint'leri bu cache'den okur, MT5'e doğrudan gitmez.

---

## 8. EMİR GÖNDERİMİ (send_order — 2 Aşamalı)

### 8.1 VİOP'ta Neden 2 Aşamalı?

VİOP exchange execution modunda ilk emre SL/TP eklenemez. Bu broker/exchange kısıtlamasıdır. Bu yüzden:

```
AŞAMA 1: Emri SL/TP olmadan gönder
    │
    └── Başarılı → ticket alındı
            │
            ▼
AŞAMA 2: TRADE_ACTION_SLTP ile SL/TP ekle
    │
    ├── Başarılı → Emir tamamlandı, SL/TP koruması aktif
    │
    └── Başarısız → 3 deneme daha yap (sltp_max_retries=3)
            │
            ├── 3 denemede de başarısız → POZİSYONU ZORLA KAPAT
            │   (Korumasız pozisyon YASAK — Anayasa kuralı #4)
            │
            └── Uyarı logu yaz
```

### 8.2 Emir Gönderme Detayı

**Kontroller (sırasıyla):**
1. Lifecycle Guard — Engine kapanıyorsa emir engellenir
2. `_order_lock` + `_write_lock` — aynı anda tek emir (race prevention)
3. `_ensure_connection()` — MT5 bağlantı kontrolü
4. Yön doğrulama: BUY veya SELL
5. Sembol çözümleme: `_to_mt5(symbol)`
6. Sembol bilgisi: tick_size, volume_min/max/step
7. Lot validasyonu ve yuvarlama
8. Filling mode: `ORDER_FILLING_RETURN` (VİOP netting zorunlu)
9. Market emirse güncel fiyat alınır

**Kilit mekanizması:**
- `_order_lock`: RLock — send_order içinden close_position çağrılabilsin (SL/TP fail → pozisyon kapat)
- `_write_lock`: RLock — tüm MT5 yazma işlemleri (close, modify) tek seferde

---

## 9. HEARTBEAT VE RECONNECT

### 9.1 Ana Döngüdeki Sıra (her 10 saniye)

```
1. mt5_bridge.heartbeat()          → MT5 bağlantı kontrolü
2. data_pipeline.run_cycle()       → Veri güncelleme
3. baba.run_cycle()                → Rejim algılama
4. baba.check_risk_limits()        → Risk kontrolü (can_trade kararı)
5. ogul.select_top5()              → Top 5 kontrat (30dk'da bir)
6. ogul.process_signals()          → Sinyal üretimi + emir
7. h_engine.run_cycle()            → Hibrit pozisyon yönetimi
8. ustat.run_cycle()               → Analiz + hata atfetme
```

### 9.2 Reconnect Sabitleri

| Sabit | Değer | Açıklama |
|-------|-------|----------|
| `MAX_RETRIES_LAUNCH` | 5 | İlk başlatma deneme sayısı |
| `MAX_RETRIES_RECONNECT` | 3 | Reconnect deneme sayısı |
| `BASE_WAIT` | 2.0 sn | İlk bekleme süresi |
| Bekleme formülü | `2 × 2^(deneme-1)` | 2sn → 4sn → 8sn → 16sn → 32sn |
| `HEARTBEAT_INTERVAL` | 10.0 sn | Heartbeat kontrol aralığı |

### 9.3 main.py _heartbeat_mt5() — Kurtarma Mekanizması

```
heartbeat() False döndü
    │
    ├── 1. deneme: connect(launch=False) — sadece bağlan, MT5 açma
    ├── 2. deneme: 4sn bekle + tekrar
    ├── 3. deneme: 8sn bekle + tekrar
    │
    └── 3 deneme de başarısız → Engine durur, kullanıcı müdahalesi gerekir
```

---

## 10. CHROME/TARAYICI MODU

Electron olmadan Chrome'da `http://localhost:5173` açıldığında:

**Farklılıklar:**
- `window.electronAPI` YOK → tüm fonksiyonlar API fallback kullanır
- DPAPI erişimi YOK → credential saklama çalışmaz
- OTP gönderim YOK → kullanıcı doğrudan MT5'e girmeli
- Bağlantı kontrolü: `fetch('/api/mt5/verify')` ile direkt FastAPI'ye gider

**Ön koşul:** Önce Electron'dan MT5 bağlantısı kurulmalı, Chrome mevcut bağlantıyı kullanır.

---

## 11. BAĞLANTI DOĞRULAMA ENDPOİNT'İ

### /api/mt5/verify (GET)

```
Electron → http.get('http://127.0.0.1:8000/api/mt5/verify')
Chrome  → fetch('/api/mt5/verify')
    │
    ▼
FastAPI handler:
    mt5.initialize()       → MT5'e bağlan (zaten bağlıysa hızlı)
    mt5.account_info()     → Hesap bilgilerini al
    │
    ├── Başarılı:
    │   { connected: true, account: { login, server, balance, equity, ... } }
    │
    └── Başarısız:
        { connected: false, message: "MT5 bağlantısı kurulamadı" }
```

**Timeout:** Electron tarafında 10sn, Chrome'da tarayıcı varsayılanı.

---

## 12. THREAD GÜVENLİĞİ VE KİLİTLER

| Kilit | Tür | Koruduğu Kaynak |
|-------|-----|----------------|
| `_order_lock` | RLock | send_order — tek seferde tek emir |
| `_write_lock` | RLock | Tüm MT5 yazma işlemleri (close, modify) |
| `_map_lock` | Lock | Sembol eşleme haritaları (_symbol_map, _reverse_map) |
| `_cb_lock` | Lock | Circuit breaker sayacı ve durumu |

**Neden RLock?** send_order() içinde SL/TP başarısız olursa close_position() çağrılır. Aynı thread reentrant erişim gerektirir — normal Lock deadlock'a neden olur.

---

## 13. ÖZET: UÇTAN UCA BAĞLANTI AKIŞI

```
[Masaüstü Kısayolu]
    → start_ustat.py (Admin)
        → FastAPI + Engine thread başlat
        → Electron başlat
            → LockScreen göster
                → Credential kontrol (DPAPI)
                    → MT5 spawn (fire-and-forget)
                        → OTP bekleme ekranı
                            → [Polling: 3sn aralık] /api/mt5/verify
                            → [OTP giriş] → admin Python → MT5 dialog
                                → mt5.initialize() başarılı
                                    → Dashboard açılır
                                        → Engine ana döngüsü başlar
                                            → mt5_bridge.connect(launch=True)
                                                → _resolve_symbols() (15+1 kontrat)
                                                    → heartbeat (her 10sn)
                                                    → data_pipeline (OHLCV + tick)
                                                    → BABA → OĞUL → H-Engine → ÜSTAT
```
