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

### 3.4 — Ana Döngü (main.py)

| # | Fonksiyon | Koruma Nedeni |
|---|-----------|---------------|
| 22 | `_run_single_cycle()` | Modül çağrı sırası. BABA her zaman OĞUL'dan önce çalışır. Bu sıralama DEĞİŞTİRİLEMEZ. |
| 23 | `_heartbeat_mt5()` | MT5 bağlantı kurtarma. 3 deneme sonrası engine durur. Bu davranış DEĞİŞTİRİLEMEZ. |
| 24 | `_main_loop()` | 10 saniye döngü + hata izolasyonu + heartbeat yazma. Döngü yapısı DEĞİŞTİRİLEMEZ. |

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

---

## BÖLÜM 5 — SARILAR (DİKKATLE DEĞİŞTİRİLEBİLİR)

Bu dosyalar Kırmızı Bölge'de değil ama dikkatli müdahale gerektirir:

| # | Dosya | Nedeni |
|---|-------|--------|
| 1 | `engine/h_engine.py` | Hibrit motor — kendi SL/TP ve pozisyon yönetimi var |
| 2 | `engine/config.py` | Konfigürasyon yükleme — yanlış yükleme tüm parametreleri bozar |
| 3 | `engine/logger.py` | Loglama — bozulursa hata tespiti imkansızlaşır |
| 4 | `api/server.py` | API ana dosya — route sırası ve middleware |
| 5 | `api/routes/killswitch.py` | Kill-switch API endpoint — frontend tetikleme mekanizması |
| 6 | `api/routes/positions.py` | Açık pozisyon API — yanlış veri frontend'i yanıltır |
| 7 | `start_ustat.py` | Başlatıcı + watchdog — bugünkü sorunun kaynağı |
| 8 | `desktop/main.js` | Electron ana process — safeQuit, killApiProcess, OTP akışı |
| 9 | `desktop/mt5Manager.js` | MT5 OTP otomasyon — admin Python zinciri |

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
