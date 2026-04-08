# ÜSTAT ANAYASA — DEĞİŞTİRİLEMEZ KORUMA KATMANI

**Yürürlük Tarihi:** 2026-03-14
**Kapsamı:** Tüm geliştiriciler (insan ve AI) için bağlayıcıdır.
**Amacı:** Uygulamanın çalışan kritik sistemlerinin bakım/onarım/geliştirme süreçlerinde yanlışlıkla devre dışı bırakılmasını önlemek.

> Bu belgedeki hiçbir madde, kullanıcının açık yazılı talimatı olmadan değiştirilemez, yumuşatılamaz veya atlanamaz.

---

## BÖLÜM 1 — MÜDAHALE ÖNCESİ ZORUNLU ADIMLAR

Herhangi bir dosyada herhangi bir değişiklik yapmadan ÖNCE aşağıdaki adımlar tamamlanmalıdır. Atlama YASAK.

### Madde 1.1 — Kök Neden Kanıtı
Bir sorun bildirildiğinde:
- Sorunun gerçek kaynağı log, çıktı veya test ile kanıtlanmalıdır.
- "Muhtemelen buradan kaynaklanıyor" ile müdahale YASAK.
- Kanıt bulunamazsa: kullanıcıya soru sorulur, debug scripti yazılır, kullanıcı çalıştırır, gerçek veriyle devam edilir.

### Madde 1.2 — Etki Analizi Raporu
Değişiklik yapılacak dosya belirlendikten sonra:
- O dosyadaki değişecek fonksiyonu kim çağırıyor? (caller chain)
- O fonksiyonun çıktısını kim kullanıyor? (consumer chain)
- Değişiklik hangi akışları etkiliyor? (data flow)
- Kırmızı Bölge dosyalarına (Bölüm 2) dokunuyor mu?
Bu rapor kullanıcıya sunulur. Kullanıcı onaylamadan uygulamaya geçilmez.

### Madde 1.3 — Kullanıcı Onayı
Etki analizi raporu sunulduktan sonra kullanıcıdan açık onay alınmalıdır.
- "Tamam", "onayla", "yap" gibi açık bir ifade gerekir.
- Sessizlik veya belirsiz yanıt onay sayılmaz.
- Kırmızı Bölge dosyalarında onay alınmadan tek satır bile değiştirilemez.

### Madde 1.4 — Geri Alma Planı
Her değişiklik öncesi:
- Değişiklik başarısız olursa nasıl geri alınacak belirtilir.
- Geri alma komutları hazır tutulur.
- Kırmızı Bölge dosyalarında değişiklik yapılmadan önce mevcut dosyanın kopyası alınır.

---

## BÖLÜM 2 — KIRMIZI BÖLGE (DOKUNULMAZ DOSYALAR)

Aşağıdaki dosyalar uygulamanın can damarıdır. Bu dosyalardaki herhangi bir değişiklik, Bölüm 1'deki tüm adımlara ek olarak aşağıdaki özel koşulları gerektirir:

### 2.1 — Kırmızı Bölge Listesi

| # | Dosya | Koruma Nedeni |
|---|-------|---------------|
| 1 | `engine/baba.py` | Risk yönetimi, kill-switch, drawdown koruması, rejim algılama |
| 2 | `engine/ogul.py` | Emir state-machine, SL/TP uygulama, EOD kapanış, pozisyon yönetimi |
| 3 | `engine/mt5_bridge.py` | MT5 emir gönderimi, SL/TP ekleme, pozisyon kapatma, circuit breaker |
| 4 | `engine/main.py` | Ana döngü, modül çağrı sırası, heartbeat, hata yönetimi |
| 5 | `engine/ustat.py` | Strateji yönetimi, Top 5 seçim, portföy kararları |
| 6 | `engine/database.py` | Trade kayıtları, risk state persistence, P&L takibi |
| 7 | `engine/data_pipeline.py` | Piyasa verisi besleme, tüm modüllerin veri kaynağı |
| 8 | `config/default.json` | Risk parametreleri, strateji sabitleri, tüm eşik değerleri |
| 9 | `start_ustat.py` | Başlatma zinciri, watchdog, graceful shutdown — startup performansı koruması |
| 10 | `api/server.py` | API lifespan, Engine oluşturma sırası, route kayıt — startup performansı koruması |

### 2.2 — Kırmızı Bölge Özel Kuralları

**a) Çift doğrulama:** Değişiklik planı sunulur → kullanıcı onaylar → değişiklik yapılır → sonuç raporlanır → kullanıcı sonucu doğrular.

**b) Tek seferde tek değişiklik:** Kırmızı Bölge dosyalarında aynı anda birden fazla fonksiyon değiştirilmez. Her değişiklik ayrı ayrı yapılır ve doğrulanır.

**c) Fonksiyon silme yasağı:** Kırmızı Bölge'deki hiçbir fonksiyon silinemez veya devre dışı bırakılamaz. İhtiyaç duyulmayan fonksiyonlar yorum satırı ile değil, kullanıcı kararıyla ve belgeli şekilde kaldırılır.

**d) Sabit değer değiştirme uyarısı:** `config/default.json` veya kod içi sabitlerde (threshold, limit, multiplier) herhangi bir değer değiştirilmeden önce mevcut değer ve yeni değer yan yana gösterilir. Kullanıcı farkı onaylar.

---

## BÖLÜM 3 — SİYAH KAPI (ASLA DEĞİŞTİRİLEMEZ FONKSİYONLAR)

Aşağıdaki fonksiyonlar uygulamanın "hayatta kalma refleksleri"dir. Bu fonksiyonların mantığı, akışı, çağrı sırası veya çıktı yapısı hiçbir koşulda değiştirilemez.

### 3.1 — Risk Koruması (baba.py)

| # | Fonksiyon | Koruma Nedeni |
|---|-----------|---------------|
| 1 | `check_risk_limits()` | İşlem açılıp açılmayacağına karar veren merkezi kapı. Devre dışı kalırsa tüm limitler çöker. |
| 2 | `_activate_kill_switch()` | Acil durum kapatma tetikleyicisi. L1/L2/L3 seviyeleri. Devre dışı kalırsa kriz anında pozisyonlar açık kalır. |
| 3 | `_close_all_positions()` | L3 tetiklendiğinde tüm pozisyonları kapatan fonksiyon. Çalışmazsa L3 kağıt üzerinde kalır. |
| 4 | `check_drawdown_limits()` | Günlük ve toplam drawdown kapısı. Devre dışı kalırsa %15+ kayıp mümkün. |
| 5 | `_check_hard_drawdown()` | Felaket drawdown tespiti (≥%15 hard, ≥%10 soft). Çalışmazsa hesap sıfırlanabilir. |
| 6 | `_check_monthly_loss()` | Aylık %7 kayıp sınırı. Çalışmazsa tek ayda %20+ kayıp mümkün. |
| 7 | `detect_regime()` | Piyasa rejim sınıflandırması. risk_multiplier'ı kontrol eder. Devre dışı kalırsa OLAY rejiminde bile tam riskle işlem açılır. |
| 8 | `calculate_position_size()` | Risk bazlı pozisyon boyutlandırma. Devre dışı kalırsa kontrolsüz lot açılır. |
| 9 | `run_cycle()` | BABA'nın her 10 saniyede bir çalışan ana döngüsü. Durması = tüm risk yönetiminin durması. |
| 10 | `_check_period_resets()` | Günlük/haftalık/aylık sıfırlama. Durması = eski limitler temizlenmez, işlem yapılamaz. |

### 3.2 — Emir Güvenliği (ogul.py)

| # | Fonksiyon | Koruma Nedeni |
|---|-----------|---------------|
| 11 | `_send_order_signal()` | Emir gönderme öncesi tüm kontroller: saat, margin, korelasyon, lot. Devre dışı kalırsa ham emir gider. |
| 12 | `_check_end_of_day()` | 17:45 zorunlu kapanış. Çalışmazsa gecelik pozisyon riski. |
| 13 | `_verify_eod_closure()` | EOD sonrası hayalet pozisyon temizliği. Çalışmazsa ertesi gün sürpriz pozisyonlar. |
| 14 | `_check_advanced_risk_rules()` | Günlük -%3 kayıpta tüm pozisyonları kapat. Çalışmazsa kayıp derinleşir. |
| 15 | `_manage_active_trades()` | OLAY rejiminde tüm pozisyonları kapat. Çalışmazsa kriz anında açık kalır. |
| 16 | `process_signals()` | Ana sinyal işleme döngüsü — çağrı sırası: EOD → advance → sync → manage → risk → time. Sıralama değiştirilmez. |

### 3.3 — MT5 Köprüsü (mt5_bridge.py)

| # | Fonksiyon | Koruma Nedeni |
|---|-----------|---------------|
| 17 | `send_order()` | 2 aşamalı emir: önce emir, sonra SL/TP. SL/TP başarısız olursa pozisyon zorla kapatılır. Bu mantık DEĞİŞTİRİLEMEZ. |
| 18 | `close_position()` | Pozisyon kapatma. VİOP netting koruması içerir. Manuel lot koruması kaldırılamaz. |
| 19 | `modify_position()` | SL/TP güncelleme. Trailing stop mekanizmasının bağlı olduğu fonksiyon. |
| 20 | `_safe_call()` | Timeout + circuit breaker sarmalayıcı. Tüm MT5 çağrılarının koruyucusu. Kaldırılırsa MT5 dondurmasında engine takılır. |
| 21 | `heartbeat()` | 10 saniye bağlantı kontrolü. Kaldırılırsa MT5 kopuşu tespit edilemez. |
| 31 | `connect()` | MT5 bağlantı fonksiyonu. launch=False modda terminal64.exe process kontrolü yapar — process yoksa mt5.initialize() ÇAĞRILMAZ. Bu koruma kaldırılırsa uygulama açıldığında MT5 otomatik başlar, startup akışı bozulur (OTP girememe, yanlış sırada başlatma). MT5 açma sorumluluğu SADECE Electron'dadır. |

### 3.4 — Ana Döngü (main.py)

| # | Fonksiyon | Koruma Nedeni |
|---|-----------|---------------|
| 22 | `_run_single_cycle()` | Modül çağrı sırası. BABA her zaman OĞUL'dan önce çalışır. Bu sıralama DEĞİŞTİRİLEMEZ. |
| 23 | `_heartbeat_mt5()` | MT5 bağlantı kurtarma. 3 deneme sonrası engine durur. Bu davranış DEĞİŞTİRİLEMEZ. |
| 24 | `_main_loop()` | 10 saniye döngü + hata izolasyonu + heartbeat yazma. Döngü yapısı DEĞİŞTİRİLEMEZ. |

### 3.5 — Startup/Shutdown Koruması (start_ustat.py + api/server.py + desktop/main.js)

| # | Fonksiyon | Dosya | Koruma Nedeni |
|---|-----------|-------|---------------|
| 25 | `run_webview_process()` | start_ustat.py | API thread → port bekleme → Electron başlatma → kapanış zinciri. Sıra DEĞİŞTİRİLEMEZ. |
| 26 | `_start_api()` | start_ustat.py | Uvicorn başlatma. Config/parametre değişikliği startup performansını bozar. |
| 27 | `_shutdown_api()` | start_ustat.py | Graceful shutdown zinciri: uvicorn stop → lifespan exit → engine.stop() → MT5 disconnect → DB close. |
| 28 | `lifespan()` | api/server.py | Engine nesne oluşturma sırası: Config→DB→MT5→Pipeline→Ustat→Baba→Ogul→Engine. Sıra DEĞİŞTİRİLEMEZ. |
| 29 | `main()` | start_ustat.py | ProcessGuard + Named Mutex + subprocess yönetimi. Tek instance koruması. |
| 30 | `createWindow()` | desktop/main.js | Electron pencere oluşturma + API hazır bekleme + crash recovery. |

---

## BÖLÜM 4 — DEĞİŞTİRİLEMEZ KURALLAR

Bu kurallar kodun davranışıdır, koddaki hiçbir değişiklik bu davranışları bozmamalıdır:

### 4.1 — Çağrı Sırası Kuralı
```
_heartbeat_mt5() → _update_data() → _run_baba_cycle() → check_risk_limits() → process_signals()
```
BABA her zaman OĞUL'dan önce çalışır. Bu sıra hiçbir koşulda değiştirilemez.

### 4.2 — Risk Kapısı Kuralı
`risk_verdict.can_trade == False` ise OĞUL yeni sinyal üretemez, yeni emir gönderemez. Bu kapı atlanamaz, devre dışı bırakılamaz.

### 4.3 — Kill-Switch Monotonluk Kuralı
Kill-switch seviyesi sadece yukarı gidebilir: L1 → L2 → L3. Otomatik düşürme YASAK. Sadece kullanıcı (`acknowledge_kill_switch`) düşürebilir.

### 4.4 — SL/TP Zorunluluk Kuralı
`send_order()` fonksiyonunda SL/TP ekleme başarısız olursa pozisyon zorla kapatılır. Korumasız pozisyon YASAK. Bu davranış DEĞİŞTİRİLEMEZ.

### 4.5 — EOD Zorunlu Kapanış Kuralı
17:45'te tüm pozisyonlar kapatılır. 17:50'de hayalet pozisyon kontrolü yapılır. Bu süreçler atlanamaz.

### 4.6 — Felaket Drawdown Kuralı
Hard drawdown ≥%15 → L3 tetiklenir → tüm pozisyonlar anında kapatılır. Bu eşik ve davranış DEĞİŞTİRİLEMEZ.

### 4.7 — OLAY Rejimi Kuralı
OLAY rejiminde risk_multiplier = 0.0. Yeni işlem açılmaz, mevcut pozisyonlar kapatılır. Bu davranış DEĞİŞTİRİLEMEZ.

### 4.8 — Circuit Breaker Kuralı
5 ardışık MT5 timeout → 30 saniye tüm MT5 çağrıları engellenir. Bu mekanizma DEĞİŞTİRİLEMEZ.

### 4.9 — Fail-Safe Kuralı
Herhangi bir güvenlik modülü sessizce devre dışı kalırsa sistem "açık" değil "kilitli" duruma düşmelidir. Şüphede işlem açma, dur.

### 4.10 — Günlük Kayıp Kuralı
Günlük kayıp ≥%3 → tüm pozisyonlar kapatılır. Günlük kayıp ≥%2.5 → yeni işlem açılmaz. Bu eşikler DEĞİŞTİRİLEMEZ.

### 4.11 — Başlatma Zinciri Kuralı
`start_ustat.py → ProcessGuard → Mutex → API thread (uvicorn) → port_open bekleme → Electron → wait`. Bu sıra DEĞİŞTİRİLEMEZ. API, Electron'dan ÖNCE hazır olmalıdır.

### 4.12 — Lifespan Oluşturma Sırası Kuralı
`Config → Database → MT5Bridge → DataPipeline → Ustat → Baba → Ogul → Engine`. Bu constructor sırası DEĞİŞTİRİLEMEZ. Bağımlılık zinciri bozulursa Engine başlatılamaz.

### 4.13 — Kapanış Sırası Kuralı
Electron ÖNCE kapanır → lifespan engine.stop() tetiklenir → MT5 disconnect → DB close → port serbest. Bu sıra DEĞİŞTİRİLEMEZ. Tersine çevirmek renderer crash'e ve TIME_WAIT birikimesine neden olur.

### 4.14 — Startup Performans Koruması
API port hazır süresi ≤5sn olmalıdır. Gecikme ≥10sn tespit edilirse kök neden araştırılır. TIME_WAIT socket temizliği ProcessGuard'da yapılır. Bu performans hedefi düşürülemez.

### 4.15 — MT5 Başlatma Sorumluluğu Kuralı
MT5 terminal (terminal64.exe) açma sorumluluğu SADECE Electron'dadır (mt5Manager.js → launchMT5). Engine veya API hiçbir koşulda MT5'i kendisi başlatamaz.

**Doğru başlatma sırası:**
```
ÜSTAT açılır → LockScreen → Electron mt5Manager.js launchMT5() → terminal64.exe başlar → Kullanıcı OTP girer → MT5 bağlantısı kurulur → Engine MT5'e bağlanır → Dashboard
```

**Koruma mekanizması:** `mt5_bridge.py connect()` fonksiyonunda `launch=False` modunda `mt5.initialize()` çağrılmadan ÖNCE `terminal64.exe` process kontrolü yapılır. Process çalışmıyorsa bağlantı atlanır — mt5.initialize() asla çağrılmaz.

**NEDEN:** Python MetaTrader5 kütüphanesi, `mt5.initialize()` çağrıldığında path verilmese bile Windows registry'den MT5 yolunu bulup terminal64.exe'yi OTOMATİK BAŞLATIR. Bu davranış `launch=False` modda istenmiyor.

**Bu kural ihlal edilirse:** Uygulama açıldığında kullanıcı müdahalesi olmadan MT5 otomatik başlar, OTP sırası bozulur, startup akışı kırılır.

Bu koruma DEĞİŞTİRİLEMEZ.

### 4.16 — mt5.initialize() Evrensel Process Kontrolü Kuralı
Projede `mt5.initialize()` çağrılan HER NOKTADA, çağrıdan ÖNCE `terminal64.exe` process kontrolü yapılmalıdır. MT5 process çalışmıyorsa `initialize()` ÇAĞRILMAZ.

**Korunan noktalar (2026-04-08 derin tarama):**

| # | Dosya | Fonksiyon | Durum |
|---|-------|-----------|-------|
| 1 | `engine/mt5_bridge.py` | `connect()` | Korumalı (Siyah Kapı #31) |
| 2 | `api/routes/mt5_verify.py` | `_verify()` | Korumalı (#129) |
| 3 | `health_check.py` | ana blok | Korumalı (#129) |

**Yeni mt5.initialize() çağrısı EKLEMEK YASAKTIR.** Tüm MT5 bağlantı işlemleri `mt5_bridge.py connect()` üzerinden yapılmalıdır. Doğrudan `mt5.initialize()` çağrısı yeni bir dosyaya veya fonksiyona eklenemez.

Bu kural ihlal edilirse derin tarama tekrarlanır ve yeni çağrı noktası ya kaldırılır ya da process kontrolü eklenir.

Bu kural DEĞİŞTİRİLEMEZ.

---

## BÖLÜM 5 — SARILAR (DİKKATLE DEĞİŞTİRİLEBİLİR)

Bu dosyalar Kırmızı Bölge'de değil ama dikkatli müdahale gerektirir:

| # | Dosya | Nedeni |
|---|-------|--------|
| 1 | `engine/h_engine.py` | Hibrit motor — kendi SL/TP ve pozisyon yönetimi var |
| 2 | `engine/config.py` | Konfigürasyon yükleme — yanlış yükleme tüm parametreleri bozar |
| 3 | `engine/logger.py` | Loglama — bozulursa hata tespiti imkansızlaşır |
| 4 | `api/routes/killswitch.py` | Kill-switch API endpoint — frontend tetikleme mekanizması |
| 5 | `api/routes/positions.py` | Açık pozisyon API — yanlış veri frontend'i yanıltır |
| 6 | `desktop/main.js` | Electron ana process — safeQuit, killApiProcess, OTP akışı, tray yönetimi |
| 7 | `desktop/mt5Manager.js` | MT5 OTP otomasyon — admin Python zinciri |

Sarı dosyalarda Bölüm 1'deki standart adımlar (kök neden + etki analizi + onay) yeterlidir.

---

## BÖLÜM 6 — İHLAL PROTOKOLÜ

### 6.1 — İhlal Tespit Edilirse
Herhangi bir Siyah Kapı fonksiyonunda veya Değiştirilemez Kuralda kasıtsız değişiklik tespit edilirse:
1. Değişiklik anında geri alınır (git revert veya backup)
2. Etki analizi yapılır: bu değişiklik aktifken hangi işlemler açıldı?
3. Açık pozisyonlar varsa manuel kontrol edilir
4. Olay session raporuna yazılır

### 6.2 — Değişiklik Öncesi Uyarı Tetikleme
AI veya geliştirici şu dosyalardan birine dokunmak istediğinde otomatik uyarı tetiklenir:
- Kırmızı Bölge dosyası → "⛔ KIRMIZI BÖLGE: Bu dosya anayasa koruması altında. Etki analizi ve kullanıcı onayı zorunlu."
- Siyah Kapı fonksiyonu → "🚫 SİYAH KAPI: Bu fonksiyonun mantığı değiştirilemez. Sadece bug fix (kanıtlı) izin verilir."
- Değiştirilemez Kural → "⚠️ DEĞİŞTİRİLEMEZ KURAL: Bu davranış anayasa ile korunmaktadır."

### 6.3 — İzin Verilen Müdahaleler
Kırmızı Bölge ve Siyah Kapı fonksiyonlarında şunlar İZİNLİDİR:
- Kanıtlanmış bug fix (log/çıktı ile ispatlı kök neden)
- Performans iyileştirmesi (mantık ve çıktı değişmeden)
- Yeni güvenlik katmanı ekleme (mevcut korumayı azaltmadan)
- Yorum ve docstring ekleme/güncelleme

Şunlar YASAKTIR:
- Fonksiyon silme veya devre dışı bırakma
- Eşik değerleri değiştirme (kullanıcı talimatı olmadan)
- Çağrı sırasını değiştirme
- Hata yönetimini (try/except) kaldırma veya zayıflatma
- "Geçici olarak devre dışı bırakma" — geçici bile olsa YASAK

---

## BÖLÜM 7 — KRİTİK SABİTLER TABLOSU

Bu değerler uygulamanın güvenlik parametreleridir. Değiştirilmeleri Bölüm 2.2(d) kapsamındadır: mevcut ve yeni değer yan yana gösterilir, kullanıcı onaylar.

| Sabit | Değer | Konum | Açıklama |
|-------|-------|-------|----------|
| `max_daily_loss_pct` | %1.8 | config/default.json | Günlük maks kayıp |
| `max_total_drawdown_pct` | %10 | config/default.json | Toplam drawdown limiti |
| `hard_drawdown_pct` | %15 | config/default.json | Felaket drawdown → L3 |
| `max_weekly_loss_pct` | %4 | config/default.json | Haftalık kayıp → lot yarılama |
| `max_monthly_loss_pct` | %7 | config/default.json | Aylık kayıp → L2 + pause |
| `max_floating_loss_pct` | %1.5 | config/default.json | Açık zarar → yeni işlem yasak |
| `risk_per_trade_pct` | %1 | config/default.json | İşlem başına risk |
| `max_open_positions` | 5 | config/default.json | Maks eşzamanlı pozisyon |
| `max_correlated_positions` | 3 | config/default.json | Maks korelasyonlu pozisyon |
| `max_daily_trades` | 5 | config/default.json | Maks günlük işlem |
| `consecutive_loss_limit` | 3 | config/default.json | Ardışık kayıp → cooldown |
| `cooldown_hours` | 4 | config/default.json | Cooldown süresi |
| `margin_reserve_pct` | %20 | config/default.json | Min serbest marjin |
| `CYCLE_INTERVAL` | 10sn | engine/main.py | Ana döngü aralığı |
| `ORDER_TIMEOUT_SEC` | 15sn | engine/ogul.py | Emir timeout |
| `MAX_SLIPPAGE_ATR_MULT` | 0.5 | engine/ogul.py | Maks slippage |
| `CB_FAILURE_THRESHOLD` | 5 | engine/mt5_bridge.py | Circuit breaker eşiği |
| `CB_COOLDOWN_SECS` | 30sn | engine/mt5_bridge.py | Circuit breaker bekleme |
| `MT5_CALL_TIMEOUT` | 8sn | engine/mt5_bridge.py | MT5 çağrı timeout |
| `WATCHDOG_STALE_SECS` | 45sn | start_ustat.py | Watchdog heartbeat eşiği |
| `MAX_AUTO_RESTARTS` | 5 | start_ustat.py | Maks otomatik yeniden başlatma |

---

## BÖLÜM 8 — BAĞIMLILIK HARİTASI

Hangi dosya hangi dosyayı çağırıyor — değişiklik yapmadan önce bu haritaya bakılmalıdır.

```
main.py
├── baba.py          [run_cycle, check_risk_limits, calculate_position_size]
├── ogul.py          [select_top5, process_signals]
│   └── mt5_bridge.py  [send_order, close_position, modify_position, get_tick, get_bars]
│   └── baba.py        [check_correlation_limits, increment_daily_trade_count]
├── h_engine.py      [run_cycle]
│   └── mt5_bridge.py  [close_position, modify_position]
├── ustat.py         [run_cycle]
├── data_pipeline.py [run_cycle]
│   └── mt5_bridge.py  [get_bars, get_tick, get_account_info, get_positions]
├── database.py      [insert_trade, get_trades, insert_event, backup]
└── mt5_bridge.py    [heartbeat, connect, disconnect]

start_ustat.py
├── api/server.py    [uvicorn ile başlatır]
├── desktop/main.js  [Electron başlatır]
│   └── mt5Manager.js  [MT5 OTP akışı]
└── watchdog_loop()  [heartbeat izler, crash'te yeniden başlatır]

config/default.json → engine/config.py → baba.py, ogul.py, main.py, h_engine.py
```

**Kritik bağımlılık zincirleri:**
- `config/default.json` → `baba.py` sabitleri → `check_risk_limits()` kararları → `ogul.py` işlem açma/kapama
- `mt5_bridge.py` → `ogul.py` emir gönderimi → `baba.py` günlük sayaç
- `main.py` çağrı sırası → BABA önce → OĞUL sonra (tersine çevrilirse risk kontrolü atlanır)

---

# ANAYASA v2 — CEO GENİŞLETMESİ

**Değişiklik Tarihi:** 2026-03-21
**Değişiklik Sebebi:** ÜSTATLAR ÜSTADI (CEO) göreve başladı. 6 direktörlük taraması sonucunda ANAYASA'nın savunma odaklı olduğu ancak yönetişim, büyüme, acil durum ve koordinasyon boyutlarının eksik kaldığı tespit edildi.
**Onay:** Kullanıcı (Turan Aykut) tarafından 2026-03-21 tarihinde onaylandı.

> Bölüm 1-8 (orijinal ANAYASA) değiştirilmemiştir. Aşağıdaki bölümler orijinal anayasanın üzerine eklenen CEO yönetim katmanıdır.

---

## BÖLÜM 9 — DEĞİŞİKLİK GEÇMİŞİ VE NEDEN-SONUÇ KAYDI

> **NEDEN EKLENDİ:** Orijinal ANAYASA hangi tarihte, neden, kim tarafından değiştirildiğini takip etmiyordu. Kurumsal hafıza yoktu. Bir değişikliğin gerekçesi kaybolduğunda, gelecekte aynı hata tekrarlanıyordu.
>
> **SONUÇ:** Her ANAYASA değişikliği artık gerekçesiyle birlikte kayıt altına alınır. Gelecekte "bu neden eklendi?" sorusu her zaman cevaplanabilir.

### 9.1 — Değişiklik Kayıt Zorunluluğu

ANAYASA'da yapılan her değişiklik aşağıdaki bilgilerle kayıt altına alınmalıdır:

| Alan | Açıklama |
|------|----------|
| Tarih | Değişiklik tarihi |
| Versiyon | ANAYASA versiyon numarası |
| Değiştiren | Kim talep etti (kullanıcı/CEO) |
| Bölüm | Hangi bölüm(ler) etkilendi |
| NEDEN | Değişikliğin kök sebebi — hangi sorun tespit edildi? |
| SONUÇ | Değişiklikle ne sağlandı? |
| Onay | Kullanıcı onay durumu |

### 9.2 — Değişiklik Geçmişi Tablosu

| # | Tarih | Versiyon | Bölüm | NEDEN | SONUÇ | Onay |
|---|-------|----------|-------|-------|-------|------|
| 1 | 2026-03-14 | v1.0 | 1-8 | Kritik dosyaların yanlışlıkla bozulması riski | Kırmızı Bölge + Siyah Kapı koruma sistemi kuruldu | Turan Aykut |
| 2 | 2026-03-21 | v2.0 | 9-15 | CEO taramasında yönetişim, büyüme, acil durum, koordinasyon eksikleri tespit edildi | CEO yönetim katmanı, geliştirme pipeline, test zorunluluğu, acil durum playbook, ajan koordinasyonu eklendi | Turan Aykut |
| 3 | 2026-04-08 | v2.1 | 3.3, 4 | MT5 auto-launch bug: Engine connect(launch=False) mt5.initialize() çağrarak MT5'i otomatik açıyordu. 10/10 test ile doğrulandı. | Siyah Kapı #31 (connect), Kural 4.15 (MT5 Başlatma Sorumluluğu) eklendi. Process kontrolü koruma bloğu eklendi. | Turan Aykut |
| 4 | 2026-04-08 | v2.2 | 4 | 11 vektörlü derin tarama: mt5_verify.py ve health_check.py'de korumasız mt5.initialize() çağrıları tespit edildi. | Kural 4.16 (mt5.initialize() Evrensel Koruma) eklendi. Tüm mt5.initialize() noktaları process kontrolü altına alındı. Yeni çağrı eklemek YASAKLANDI. | Turan Aykut |

---

## BÖLÜM 10 — YÖNETİM YAPISI (CEO MEKANİZMASI)

> **NEDEN EKLENDİ:** ANAYASA "kullanıcı onaylar" diyordu ama karar mekanizması tanımsızdı. Sistem büyüdükçe (ajan sistemi, multi-agent çalışma) kimin neyi yapabileceği, hangi kararların otomatik alınabileceği belirsiz kaldı. 6 direktörlük çalıştırıldığında hiçbirinin yetki sınırı tanımlı değildi.
>
> **SONUÇ:** Hiyerarşik yönetim yapısı, yetki matrisi ve karar mekanizması tanımlandı. Her seviye neyi yapabilir, neyde üst onay gerekir — artık netleştirildi.

### 10.1 — Hiyerarşi

```
KULLANICI (Turan Aykut) — Nihai Otorite
    │
    └── ÜSTATLAR ÜSTADI (CEO) — Stratejik Yönetim
            │
            ├── Risk & Güvenlik Direktörlüğü
            ├── Ticaret Operasyonları Direktörlüğü
            ├── Altyapı & Veritabanı Direktörlüğü
            ├── Kalite & Test Direktörlüğü
            ├── Frontend & UX Direktörlüğü
            └── Yönetişim & Dokümantasyon Direktörlüğü
```

### 10.2 — CEO Yetki ve Sorumlulukları

**CEO (Üstatlar Üstadı) YAPABILIR:**
- Sarı Bölge dosyalarında değişiklik (Bölüm 1 standart adımlarıyla)
- Yeşil Bölge (yeni dosya, yardımcı modül, dokümantasyon) değişiklikleri
- Direktörlük ajanlarını çalıştırma ve koordine etme
- Sistem durum değerlendirmesi ve rapor üretme
- Bug fix önerisi sunma (kanıtlı)
- Test yazma ve çalıştırma
- Build alma ve deploy etme (ajan üzerinden)

**CEO KULLANICI ONAYI İLE YAPABİLİR:**
- Kırmızı Bölge dosyalarında değişiklik
- Siyah Kapı fonksiyonlarında bug fix
- Kritik sabit değer değişikliği (Bölüm 7)
- ANAYASA değişikliği
- Versiyon yükseltme
- Strateji parametresi değişikliği

**CEO ASLA YAPAMAZ:**
- ANAYASA Bölüm 1-8'i kullanıcı talimatı olmadan değiştirmek
- Siyah Kapı fonksiyonlarının mantığını değiştirmek
- Çağrı sırasını değiştirmek
- Kill-switch'i devre dışı bırakmak
- Risk limitlerini gevşetmek

### 10.3 — Direktörlük Yetkileri

Direktörlükler (alt ajanlar) CEO tarafından görevlendirilir. Kuralları:

| Direktörlük | Yetkisi | Sınırı |
|---|---|---|
| Risk & Güvenlik | Analiz, rapor, test yazma | Kod değiştirme YASAK — sadece CEO'ya rapor |
| Ticaret Operasyonları | Analiz, sinyal kalitesi testi | Strateji parametresi değiştirme YASAK |
| Altyapı & Veritabanı | Analiz, sorgu optimizasyonu | Şema değişikliği CEO onayıyla |
| Kalite & Test | Test yazma, çalıştırma, raporlama | Kod değiştirme YASAK |
| Frontend & UX | Analiz, CSS/UI öneri | Kırmızı Bölge API değişikliği YASAK |
| Yönetişim & Dokümantasyon | Dokümantasyon güncelleme | ANAYASA değişikliği CEO + Kullanıcı onayıyla |

**Direktörlük Genel Kuralı:** Hiçbir direktörlük ajansı doğrudan kod değişikliği yapamaz. Tüm değişiklikler CEO üzerinden, CEO ise Bölüm 1 prosedürleriyle yapar.

### 10.4 — Karar Alma Süreci

```
Sorun/Talep Tespit Edildi
    │
    ├── Yeşil Bölge → CEO tek başına karar alır → Uygular → Raporlar
    │
    ├── Sarı Bölge → CEO etki analizi yapar → Kullanıcıya sunar → Onay → Uygular
    │
    ├── Kırmızı Bölge → CEO etki analizi + geri alma planı → Kullanıcıya sunar
    │                    → Çift onay (plan + sonuç) → Tek değişiklik → Doğrulama
    │
    └── Siyah Kapı → CEO kanıtlı bug raporu hazırlar → Kullanıcıya sunar
                     → Üçlü onay (kanıt + plan + sonuç) → Minimal müdahale
```

---

## BÖLÜM 11 — GELİŞTİRME PIPELINE

> **NEDEN EKLENDİ:** ANAYASA "koru" diyordu ama "nasıl büyütülecek" tanımsızdı. Yeni özellik ekleme, refactor, optimizasyon süreçleri belirsizdi. 50 iterasyon boyunca süreç ad-hoc yürütüldü. Piyasa açıkken yapılan riskli değişiklikler ile piyasa kapalıyken yapılabilecek güvenli değişiklikler ayrılmamıştı.
>
> **SONUÇ:** Savaş zamanı / barış zamanı kuralları, feature pipeline, refactor prosedürü tanımlandı. Artık her değişikliğin ne zaman yapılacağı da belirli.

### 11.1 — Savaş Zamanı vs Barış Zamanı

| Zaman | Saat | İzin Verilen |
|-------|------|-------------|
| **SAVAŞ ZAMANI** (Piyasa Açık) | Pazartesi-Cuma 09:30-18:15 | Sadece: Kanıtlı bug fix, L3 acil müdahale, log/monitoring ekleme |
| **BARIŞ ZAMANI** (Piyasa Kapalı) | Hafta içi 18:15 sonrası + Hafta sonu | Her şey: Refactor, yeni özellik, test, optimizasyon, ANAYASA değişikliği |
| **GRİ BÖLGE** (Açılış/Kapanış) | 09:15-09:30 ve 17:45-18:15 | HİÇBİR DEĞİŞİKLİK — sadece izle |

**Savaş Zamanı İhlali:** Piyasa açıkken Kırmızı Bölge'ye dokunmak — kullanıcının açık yazılı "acil" talimatı gerekir. CEO bile tek başına karar veremez.

### 11.2 — Feature Pipeline

Yeni özellik ekleme süreci:

```
1. TALEP          → Kullanıcı veya CEO önerir
2. ETKİ ANALİZİ   → Hangi dosyalar etkilenir? Kırmızı/Sarı/Yeşil?
3. TASARIM         → CEO mimari tasarım yapar, kullanıcıya sunar
4. ONAY            → Kullanıcı onaylar
5. TEST YAZIMI     → Özellik için test senaryoları ÖNCE yazılır
6. GELİŞTİRME     → Barış zamanında uygulanır
7. TEST ÇALIŞTIRMA → Tüm testler geçmeli
8. BUILD & DEPLOY  → Ajan üzerinden build + uygulama yeniden başlatma
9. DOĞRULAMA       → Ekran görüntüsü veya fonksiyonel test
10. İŞLEMİ BİTİR   → USTAT_OKU Bölüm 5 prosedürü (tarihçe, versiyon, git, rapor)
```

### 11.3 — Refactor Prosedürü

Monolitik dosya bölme kuralları (ör. ogul.py 4.879 satır):

1. Mevcut tüm testler ÖNCE çalıştırılır (baseline)
2. Refactor planı hazırlanır (hangi fonksiyonlar hangi modüle)
3. Kullanıcı onaylar
4. Bağımlılık haritası güncellenir
5. Değişiklik BARIŞ ZAMANINDA yapılır
6. Tüm import zincirleri kontrol edilir
7. Tüm testler tekrar çalıştırılır
8. Diff karşılaştırması: mantık değişmediği doğrulanır
9. Build + deploy + fonksiyonel test

### 11.4 — Kod Renk Sistemi

| Renk | Dosyalar | Değişiklik Kuralı |
|------|---------|-------------------|
| **KIRMIZI** | Bölüm 2.1 listesi (8 dosya) | Bölüm 1 + Bölüm 2.2 tam prosedür |
| **SARI** | Bölüm 5 listesi (9 dosya) | Bölüm 1 standart adımları |
| **YEŞİL** | Diğer tüm dosyalar | CEO tek başına uygulayabilir, İŞLEMİ BİTİR yeterli |
| **MAVİ** | Yeni dosyalar (henüz mevcut değil) | CEO oluşturabilir, renk ataması sonradan yapılır |

---

## BÖLÜM 12 — TEST ZORUNLULUĞU

> **NEDEN EKLENDİ:** 6 direktörlük taramasında en büyük risk "test yok" olarak tespit edildi. 29.945 satır kritik trading kodu %0 aktif test coverage ile çalışıyordu. tests_aktif/ klasöründe 7 test dosyası var ama üretimde çalıştırılmıyordu. Risk yönetimi kodu (para kaybettiren) test edilmeden canlıya gidiyordu.
>
> **SONUÇ:** Test zorunluluğu ANAYASA düzeyinde tanımlandı. Kırmızı Bölge değişikliklerinde test çalıştırmadan deploy YASAK.

### 12.1 — Test Kuralları

| Kural | Açıklama |
|-------|----------|
| **Kırmızı Bölge Testi** | Kırmızı Bölge dosyasında değişiklik yapıldığında, o dosyanın mevcut testleri MUTLAKA çalıştırılır. Test yoksa, ÖNCE test yazılır. |
| **Siyah Kapı Testi** | Siyah Kapı fonksiyonunda bug fix yapıldığında, fix'i doğrulayan test yazılır ve eklenir. |
| **Deploy Öncesi** | `İŞLEMİ BİTİR` Adım 2'de (Build) test çalıştırma zorunludur. Build başarılı olsa bile test başarısızsa deploy YASAK. |
| **Regression** | Her değişiklik sonrası tüm mevcut testler çalıştırılır. Yeni hata üretilmediği doğrulanır. |

### 12.2 — Test Öncelik Sırası

Aşağıdaki modüller için test varlığı zorunludur (öncelik sırasıyla):

| Öncelik | Modül | Neden |
|---------|-------|-------|
| P0 | `check_risk_limits()` | İşlem açma/kapama kararı — hata = para kaybı |
| P0 | `_activate_kill_switch()` | Acil durum koruması — hata = korumasız pozisyon |
| P0 | `send_order()` + SL/TP | Emir gönderimi — hata = yanlış emir veya korumasız pozisyon |
| P0 | `check_drawdown_limits()` | Drawdown koruması — hata = hesap sıfırlanma |
| P1 | `detect_regime()` | Rejim algılama — hata = yanlış risk çarpanı |
| P1 | `process_signals()` | Sinyal işleme — hata = yanlış trade |
| P1 | `_check_end_of_day()` | EOD kapanış — hata = gecelik pozisyon |
| P2 | `calculate_position_size()` | Pozisyon boyutu — hata = aşırı lot |
| P2 | `heartbeat()` | Bağlantı kontrolü — hata = kopuş algılanamaz |

### 12.3 — Deploy Öncesi Kontrol Listesi

Her deploy öncesi şu kontrol listesi tamamlanmalıdır:

```
[ ] Tüm mevcut testler çalıştırıldı ve geçti
[ ] Değişen dosyanın spesifik testleri çalıştırıldı
[ ] Build başarılı (vite build hatasız)
[ ] Kırmızı Bölge dosyası değiştiyse: çift doğrulama tamamlandı
[ ] Siyah Kapı fonksiyonu değiştiyse: kanıt + test + üçlü onay tamamlandı
[ ] git diff incelendi — istenmeyen değişiklik yok
[ ] Uygulama yeniden başlatıldı ve Dashboard kontrolü yapıldı
```

---

## BÖLÜM 13 — ACİL DURUM PLAYBOOK

> **NEDEN EKLENDİ:** CEO taramasında 5 kritik bulgu tespit edildi: korumasız pozisyon, circuit breaker delinmesi, L3 başarısız kapanış, peak equity race condition, equity=0 hatası. ANAYASA bu senaryolarda "log yazılır" diyordu ama acil müdahale adımları tanımlı değildi. Piyasa açıkken bu hatalar oluşursa saniyeler içinde müdahale gerekir.
>
> **SONUÇ:** Her kritik senaryo için adım adım müdahale playbook'u tanımlandı. Kim ne yapacak, hangi sırayla, ne kadar sürede — artık belirli.

### 13.1 — Acil Durum Seviyeleri

| Seviye | Tanım | Müdahale Süresi | Yetkili |
|--------|-------|----------------|---------|
| **SEV-1** | Para kaybı devam ediyor, pozisyon korumasız | DERHAL (saniyeler) | Kullanıcı veya CEO+Ajan |
| **SEV-2** | Sistem çalışıyor ama risk kontrolü devre dışı | 5 dakika içinde | CEO |
| **SEV-3** | Performans sorunu, veri gecikmesi | 30 dakika içinde | CEO |
| **SEV-4** | UI hatası, log sorunu | Barış zamanında | CEO veya Direktörlük |

### 13.2 — SEV-1: Korumasız Pozisyon (SL/TP Ekleme Başarısız + Kapatma Başarısız)

```
ALARM: "KORUMASIZ POZİSYON" (Dashboard kırmızı banner)

1. CEO → Ajan: "stop_app" komutu → Engine durdurulur
2. CEO → Ajan: MT5'te açık pozisyon listesi al
3. Kullanıcıya bildir: "X sembolünde Y lot korumasız pozisyon var"
4. Kullanıcı kararı bekle:
   a) "Kapat" → CEO → Ajan: MT5'te manuel kapanış
   b) "SL/TP ekle" → CEO → Ajan: MT5'te manuel SL/TP
   c) "Bırak" → Kullanıcı riski kabul eder
5. Sorun çözüldükten sonra engine yeniden başlatılır
6. Olay session raporuna yazılır
```

### 13.3 — SEV-1: L3 Kill-Switch Tetiklendi Ama Pozisyon Kapatılamadı

```
ALARM: "L3 BAŞARISIZ KAPANIŞ" (Dashboard kırmızı banner)

1. BABA otomatik: can_trade = False (yeni işlem yasak)
2. BABA otomatik: 10 deneme × 2sn aralık ile kapatmayı tekrarla
3. Hâlâ başarısızsa:
   a) CEO → Ajan: MT5 terminalini yeniden başlat
   b) CEO → Ajan: Kapatma tekrar dene
   c) Hâlâ başarısızsa: Kullanıcıya ACIL bildir
4. Kullanıcı MT5'ten manuel kapatır
5. CEO: Başarısız ticket listesi temizlenir
6. CEO: can_trade = False KALIR — kullanıcı açıkça izin verene kadar
```

### 13.4 — SEV-1: MT5 Bağlantı Kopması (Açık Pozisyon Varken)

```
ALARM: "MT5 KOPTU — AÇIK POZİSYON VAR"

1. Engine otomatik: 3 reconnect denemesi (10sn aralık)
2. Başarısızsa: can_trade = False
3. CEO → Kullanıcıya bildir: "MT5 bağlantısı koptu, X açık pozisyon var"
4. Reconnect başarılı olursa:
   a) Pozisyon senkronizasyonu: DB vs MT5 karşılaştır
   b) Uyuşmazlık varsa kullanıcıya raporla
   c) SL/TP'leri kontrol et — eksik varsa ekle
5. Olay raporlanır
```

### 13.5 — SEV-2: Circuit Breaker Açıldı

```
UYARI: "CIRCUIT BREAKER AKTİF — MT5 İLETİŞİMİ DURDU"

1. 30sn cooldown otomatik başlar
2. Cooldown sonrası probe çağrısı yapılır
3. Probe başarılıysa: normal çalışmaya dön
4. Probe başarısızsa: cooldown tekrar + kullanıcı bilgilendir
5. 3 ardışık cooldown başarısızsa: Engine durdur + kullanıcı bildir
```

### 13.6 — SEV-2: Equity Sıfır veya Negatif

```
ALARM: "EQUITY SIFIR — MARGIN CALL RİSKİ"

1. BABA otomatik: can_trade = False
2. BABA otomatik: Tüm pozisyonları kapat (L3 tetikle)
3. CEO → Kullanıcıya ACIL bildir
4. Engine DURDURULUR — kullanıcı müdahalesi gerekir
5. Kullanıcı hesap durumunu kontrol eder
```

---

## BÖLÜM 14 — AJAN KOORDİNASYONU

> **NEDEN EKLENDİ:** ÜSTAT Ajan Sistemi (ustat_agent.py) kuruldu ve Claude ile Windows arasında köprü oluşturuldu. Ancak ajanın yetki sınırları, paralel çalışma kuralları, çakışma yönetimi tanımlı değildi. CEO 6 direktörlük ajanını aynı anda çalıştırdığında koordinasyon kuralı yoktu.
>
> **SONUÇ:** Ajan türleri, yetkileri, çakışma kuralları ve güvenlik sınırları tanımlandı.

### 14.1 — Ajan Türleri

| Tür | Görev | Örnek |
|-----|-------|-------|
| **Yürütücü Ajan** | Windows üzerinde komut çalıştırır | ustat_agent.py (start_app, build, screenshot) |
| **Direktörlük Ajanı** | Kod analizi, rapor üretir | Risk Direktörü, Kalite Direktörü vb. |
| **Gözlemci Ajan** | Sistem durumunu izler | Heartbeat kontrolü, log tarama |

### 14.2 — Ajan Güvenlik Kuralları

| Kural | Açıklama |
|-------|----------|
| **Salt Okunur Direktörlük** | Direktörlük ajanları KOD DEĞİŞTİRMEZ. Sadece okur, analiz eder, rapor üretir. |
| **Tek Yürütücü** | Aynı anda sadece 1 yürütücü ajan komutu çalıştırabilir. Sıralı kuyruk. |
| **CEO Geçidi** | Tüm kod değişiklikleri CEO üzerinden yapılır. Direktörlük ajanı doğrudan edit YASAK. |
| **Çakışma Önleme** | İki ajan aynı dosyayı aynı anda okuyabilir ama yazma işlemi CEO tarafından sıralanır. |
| **Kırmızı Bölge Yasağı** | Hiçbir ajan (CEO dahil) kullanıcı onayı olmadan Kırmızı Bölge dosyasını değiştiremez. |

### 14.3 — Paralel Çalışma Kuralları

```
CEO 6 Direktörlüğü aynı anda çalıştırabilir (paralel):
  ├── Tümü SALT OKUNUR çalışır
  ├── Her biri kendi raporunu üretir
  ├── CEO raporları toplar ve birleştirir
  └── Aksiyon kararı CEO'da, uygulama sıralı yapılır

YASAK: İki ajanın aynı anda aynı dosyayı YAZMASI
YASAK: Bir ajanın başka bir ajanın çıktısını onaysız kullanması
```

### 14.4 — Ajan İletişim Protokolü

```
Claude (CEO) ←→ .agent/commands/ ←→ ustat_agent.py (Windows)
                     │
                     ├── cmd_XXXX.json (komut)
                     └── .agent/results/cmd_XXXX.json (sonuç)

Heartbeat: .agent/heartbeat.json (her 10sn güncellenir)
Ajan Durumu: Dashboard TopBar'da yeşil/kırmızı gösterge
```

---

## BÖLÜM 15 — ANAYASA DEĞİŞİKLİK KURALLARI

> **NEDEN EKLENDİ:** Orijinal ANAYASA kendi değişiklik kurallarını tanımlamıyordu. "Hiçbir madde kullanıcının açık yazılı talimatı olmadan değiştirilemez" deniyordu ama değişiklik prosedürü yoktu. Versiyon numarası, onay süreci, koruma mekanizması tanımsızdı.
>
> **SONUÇ:** ANAYASA'nın kendisi de artık korunan ve versiyonlanan bir belge. Değişiklik prosedürü netleştirildi.

### 15.1 — Değişiklik Prosedürü

ANAYASA'da değişiklik yapmak için:

```
1. CEO veya Kullanıcı değişiklik önerir
2. NEDEN-SONUÇ gerekçesi yazılır
3. Mevcut maddeyle çelişki analizi yapılır
4. Kullanıcı açık onay verir ("ANAYASA değişikliğini onaylıyorum")
5. Değişiklik uygulanır
6. Bölüm 9.2 tablosuna kayıt eklenir
7. Versiyon numarası güncellenir
8. git commit ile kalıcılaştırılır
```

### 15.2 — Koruma Seviyeleri

| Bölüm | Koruma | Değişiklik Koşulu |
|-------|--------|-------------------|
| **Bölüm 1-4** (Müdahale + Kırmızı Bölge + Siyah Kapı + Kurallar) | DOKUNULMAZ | Sadece kullanıcı talimatıyla, CEO + Kullanıcı çift onay |
| **Bölüm 5-8** (Sarılar + İhlal + Sabitler + Harita) | KORUNMUŞ | CEO öneri + Kullanıcı onay |
| **Bölüm 9-15** (CEO Genişletmesi) | GELİŞTİRİLEBİLİR | CEO öneri + Kullanıcı onay, mevcut korumalar korunarak |

### 15.3 — Versiyon Numaralandırma

```
ANAYASA v[MAJOR].[MINOR]

MAJOR: Yapısal değişiklik (yeni bölüm, bölüm kaldırma, temel kural değişikliği)
MINOR: İçerik güncellemesi (tablo güncelleme, açıklama ekleme, tarih düzeltme)

Örnekler:
v1.0 → Orijinal ANAYASA (Bölüm 1-8)
v2.0 → CEO Genişletmesi (Bölüm 9-15 eklendi)
v2.1 → Bir tabloya yeni satır eklendi
v3.0 → Yeni bölüm eklendi
```

### 15.4 — Değiştirilemez Çekirdek

Aşağıdaki maddeler ANAYASA'nın çekirdeğidir ve HİÇBİR KOŞULDA değiştirilemez:

1. **Bölüm 4.1** — Çağrı Sırası Kuralı (BABA önce, OĞUL sonra)
2. **Bölüm 4.2** — Risk Kapısı Kuralı (can_trade kapısı)
3. **Bölüm 4.4** — SL/TP Zorunluluk Kuralı
4. **Bölüm 4.6** — Felaket Drawdown Kuralı (%15 → L3)
5. **Bölüm 4.9** — Fail-Safe Kuralı (şüphede dur)

Bu 5 madde ÜSTAT'ın hayatta kalma refleksleridir. CEO bile dokunma yetkisine sahip değildir.

---

## MEVCUT ANAYASA VERSİYONU

```
ANAYASA v2.0
Oluşturulma: 2026-03-14 (v1.0)
Son Güncelleme: 2026-03-21 (v2.0 — CEO Genişletmesi)
Toplam Bölüm: 15
Orijinal Bölümler: 1-8 (değiştirilmedi)
CEO Bölümleri: 9-15 (yeni)
Onaylayan: Turan Aykut
Uygulayan: ÜSTATLAR ÜSTADI (CEO)
```
