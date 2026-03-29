# ÜSTAT v5.9 — ANA REHBER

**Versiyon:** 3.2 | **Tarih:** 28 Mart 2026 | **Kaynak:** Kod tabanı doğrulaması
**Anayasa Referansı:** USTAT_ANAYASA.md (v2.0) — ayrı belge, kendi versiyonlaması var

> Bu dosya ÜSTAT projesinin TEK rehberidir. Tüm geliştiriciler (insan ve AI) bu kurallara MUTLAK uyum gösterir. Varsayım, olasılık, tahmin YASAKTIR — her karar kanıta dayanır.

---

## BÖLÜM 1: ÜSTAT NEDİR?

ÜSTAT v5.8, Borsa İstanbul VİOP (Vadeli İşlem ve Opsiyon Piyasası) üzerinde otomatik alım-satım yapan algoritmik bir trading platformudur. GCM Capital aracılığında MetaTrader 5 terminali üzerinden **canlı piyasada gerçek para ile** işlem yapar.

**Finansal risk uyarısı:** Bu uygulamadaki her hata, kullanıcıya doğrudan finansal zarar olarak yansır. Bu nedenle tüm kurallar kesindir, istisnası yoktur.

### 1.1 Dört Motor Mimarisi

Sistem dört bağımsız motor üzerinde çalışır. Her 10 saniyede bir SABİT sırada çalıştırılır:

| Sıra | Motor | Görev | Dosya |
|------|-------|-------|-------|
| 1 | **BABA** | Risk yönetimi, kill-switch, drawdown, rejim algılama | `engine/baba.py` |
| 2 | **OĞUL** | Top 5 kontrat seçimi, sinyal üretimi, emir yönetimi, pozisyon takibi | `engine/ogul.py` |
| 3 | **H-Engine** | Hibrit pozisyon yönetimi (breakeven, trailing stop, EOD) | `engine/h_engine.py` |
| 4 | **ÜSTAT** | Hata atfetme, strateji havuzu, kontrat profilleri, analiz | `engine/ustat.py` |

**KURAL:** Bu çağrı sırası DEĞİŞTİRİLEMEZ. BABA her zaman OĞUL'dan önce çalışır. İstisna yoktur.

### 1.2 Motorlar Arası Veri Akışı

```
DataPipeline (OHLCV veri) → BABA (rejim + risk kararı)
                                ↓
                          can_trade kararı
                                ↓
                            OĞUL (sinyal üret + emir gönder)
                                ↓
                          H-Engine (pozisyon yönet)
                                ↓
                            ÜSTAT (analiz + hata atfet)
```

### 1.3 Teknoloji Yığını

| Katman | Teknoloji |
|--------|-----------|
| Trading Engine | Python 3.14 |
| API Backend | FastAPI + Uvicorn (port 8000) |
| Frontend | React 18 (JSX) + Vite 6 (port 5173) |
| Masaüstü | Electron 33 |
| Veritabanı | SQLite (trades.db, ustat.db) |
| Broker Bağlantısı | MetaTrader 5 API |
| Grafikler | Recharts |
| HTTP İstemci | Axios |

### 1.4 Proje Dosya Yapısı

```
C:\Users\pc\Desktop\USTAT\
├── engine/                    # Python Trading Engine (4 motor)
│   ├── __init__.py            # VERSION = "5.8.0"
│   ├── main.py                # Ana döngü (Engine sınıfı)
│   ├── baba.py                # Risk yöneticisi (BABA)
│   ├── ogul.py                # Sinyal üretici (OĞUL)
│   ├── h_engine.py            # Hibrit pozisyon yöneticisi
│   ├── ustat.py               # Strateji havuzu + hata atfetme
│   ├── mt5_bridge.py          # MetaTrader 5 API köprüsü
│   ├── database.py            # SQLite sarmalayıcı
│   ├── data_pipeline.py       # Piyasa verisi besleme
│   ├── config.py              # Konfigürasyon yükleyici
│   ├── error_tracker.py       # Hata izleme
│   ├── event_bus.py           # Olay yayınlama
│   ├── health.py              # Sağlık metrikleri
│   ├── logger.py              # Loglama
│   ├── manuel_motor.py        # Manuel işlem motoru
│   ├── netting_lock.py        # Pozisyon netting koruması
│   ├── news_bridge.py         # Haber entegrasyonu
│   ├── top5_selection.py      # Top 5 kontrat seçici
│   ├── simulation.py          # Simülasyon modu
│   ├── backtest.py            # Backtesting
│   ├── models/                # Veri modelleri
│   │   ├── regime.py          # RegimeType, EarlyWarning
│   │   ├── risk.py            # RiskParams, RiskVerdict, FakeAnalysis
│   │   ├── signal.py          # Signal, SignalType, StrategyType
│   │   └── trade.py           # Trade, TradeState
│   └── utils/                 # Yardımcı modüller
│       ├── indicators.py      # Teknik indikatörler
│       ├── signal_engine.py   # Sinyal motoru
│       ├── multi_tf.py        # Çoklu zaman dilimi analizi
│       ├── price_action.py    # Fiyat aksiyonu algılama
│       ├── helpers.py         # Genel yardımcılar
│       └── time_utils.py      # Zaman yardımcıları
│
├── api/                       # FastAPI Backend (port 8000)
│   ├── server.py              # FastAPI uygulama kurulumu
│   ├── schemas.py             # Pydantic modelleri
│   ├── constants.py           # API sabitleri
│   ├── deps.py                # Bağımlılık enjeksiyonu
│   └── routes/                # 18 endpoint modülü
│       ├── account.py         # MT5 hesap bilgisi
│       ├── error_dashboard.py # Hata izleme paneli
│       ├── events.py          # Olay takibi
│       ├── health.py          # Sistem sağlığı
│       ├── hybrid_trade.py    # Hibrit pozisyon yönetimi
│       ├── killswitch.py      # Kill-switch tetikleme
│       ├── live.py            # WebSocket canlı veri
│       ├── manual_trade.py    # Manuel işlem
│       ├── mt5_verify.py      # MT5 bağlantı doğrulama
│       ├── news.py            # Haber ve olaylar
│       ├── ogul_activity.py   # OĞUL sinyal aktivitesi
│       ├── performance.py     # Performans metrikleri
│       ├── positions.py       # Açık pozisyonlar
│       ├── risk.py            # Risk durumu
│       ├── settings.py        # Ayarlar
│       ├── status.py          # Sistem durumu
│       ├── top5.py            # Top 5 kontrat
│       ├── trades.py          # İşlem geçmişi
│       └── ustat_brain.py     # Strateji havuzu
│
├── config/
│   └── default.json           # Ana konfigürasyon (TÜM sabitler buradan)
│
├── database/
│   ├── trades.db              # Ana işlem veritabanı
│   └── ustat.db               # ÜSTAT analiz veritabanı
│
├── desktop/                   # Electron + React Masaüstü Uygulaması
│   ├── main.js                # Electron ana process
│   ├── preload.js             # IPC köprüsü
│   ├── mt5Manager.js          # MT5 terminal yönetimi
│   ├── package.json           # v5.8.0
│   ├── index.html             # Giriş HTML
│   ├── vite.config.js         # Vite yapılandırması
│   └── src/
│       ├── App.jsx            # Ana React bileşeni
│       ├── main.jsx           # React giriş noktası
│       ├── components/        # 16 React bileşeni
│       │   ├── AutoTrading.jsx
│       │   ├── ConfirmModal.jsx
│       │   ├── Dashboard.jsx
│       │   ├── ErrorBoundary.jsx
│       │   ├── ErrorTracker.jsx
│       │   ├── HybridTrade.jsx
│       │   ├── LockScreen.jsx
│       │   ├── ManualTrade.jsx
│       │   ├── Monitor.jsx
│       │   ├── NewsPanel.jsx
│       │   ├── Performance.jsx
│       │   ├── RiskManagement.jsx
│       │   ├── Settings.jsx
│       │   ├── SideNav.jsx
│       │   ├── TopBar.jsx
│       │   ├── TradeHistory.jsx
│       │   └── UstatBrain.jsx
│       ├── services/
│       │   ├── api.js         # API istemcisi
│       │   └── mt5Launcher.js # MT5 başlatıcı + browser fallback
│       ├── styles/
│       └── utils/
│           └── formatters.js
│
├── docs/                      # Oturum raporları ve dokümantasyon
│   ├── USTAT_GELISIM_TARIHCESI.md
│   └── YYYY-MM-DD_session_raporu_*.md
│
├── tests/                     # Test paketi
│   ├── test_unit_core.py
│   └── test_news_100_combinations.py
│
├── mql5/                      # MQL5 scriptleri
├── logs/                      # Log dosyaları
├── .agent/                    # Ajan köprüsü ve komutları
│
├── CLAUDE.md                  # BU DOSYA — Ana rehber
├── USTAT_ANAYASA.md           # Anayasa (değiştirilemez koruma katmanı)
├── start_ustat.py             # Başlatıcı + watchdog
├── ustat_agent.py             # Otonom ajan (v2.0)
├── health_check.py            # Sağlık kontrolü
├── create_shortcut.ps1        # Kısayol oluşturucu
├── update_shortcut.ps1        # Kısayol güncelleyici
└── restart_all.bat            # Tüm servisleri yeniden başlat
```

### 1.5 Ana Döngü — 10 Saniye Çevrimi (main.py `_run_single_cycle`)

Her 10 saniyede aşağıdaki adımlar SABİT SIRAYLA çalışır:

1. MT5 Heartbeat kontrolü (bağlantı var mı?)
2. DataPipeline: 15 kontratın OHLCV verisi güncellenir (M1/M5/M15/H1)
3. BABA `run_cycle()`: Rejim algılama + erken uyarılar + fake analiz
4. BABA `check_risk_limits()`: `can_trade` kararı verilir
5. OĞUL `select_top5()`: Top 5 kontrat seçimi (30 dakikada bir)
6. OĞUL `process_signals()`: Sinyal üretimi + emir yönetimi + pozisyon takibi
7. H-Engine `run_cycle()`: Hibrit pozisyon yönetimi (breakeven, trailing, EOD)
8. ÜSTAT `run_cycle()`: Hata atfetme, strateji havuzu, analiz güncelleme

### 1.6 Başlama Zinciri

```
Masaüstü kısayolu → wscript.exe start_ustat.vbs
    → start_ustat.py (Admin yetkisi)
        → Port temizleme (8000, 5173)
        → API başlat (uvicorn, port 8000) + Engine thread
        → Vite başlat (port 5173)
        → Electron başlat (localhost:5173 yükler)
        → Watchdog döngüsü (heartbeat izle, crash'te yeniden başlat)
```

**PID dosyaları:** `api.pid` (API process), `watchdog.pid` (watchdog singleton), `engine.heartbeat` (motor kalp atışı)

---

## BÖLÜM 2: MEVCUT DURUM

### 2.1 Piyasa Rejimleri (BABA Algılar)

| Rejim | Koşul | Risk Çarpanı |
|-------|-------|-------------|
| **TREND** | ADX > 25, EMA ayrışması | 1.0 (tam risk) |
| **RANGE** | ADX < 20, BB daralmış | 0.7 |
| **VOLATILE** | ATR > ortalama × 2.5 | 0.25 |
| **OLAY** | Haber/olay günü | 0.0 (işlem YASAK) |

### 2.2 Top 5 Seçim Algoritması (OĞUL — `select_top5`)

OĞUL her 30 dakikada 15 kontrat arasından en iyi 5'ini seçer.

Filtreleme sırası: Ham skor → Winsorize + Min-Max normalizasyon → Ağırlıklı toplam → Ortalama filtre → Min 3 garanti → Vade filtresi → Haber/kazanç filtresi

### 2.3 Sinyal Stratejileri (OĞUL Üretir)

| Strateji | Koşullar | SL/TP |
|----------|---------|-------|
| **Trend Follow** | EMA 20/50 kesişimi, ADX > 25, MACD teyit | SL: 1.5×ATR, TP: 2.0×ATR |
| **Mean Reversion** | RSI aşırı alım/satım, BB genişliği, Williams %R | SL: 1.0×ATR, breakeven: %0.5 |
| **Breakout** | 20-bar lookback, 1.5× hacim, 1.2× ATR genişleme | Trailing: 2.0×ATR |

### 2.4 Trade State Machine (OĞUL — Emir Durumları)

```
SIGNAL → PENDING → SENT → FILLED → CLOSED
                      ↓        ↓
                  TIMEOUT   PARTIAL (≥%50 kabul)
                      ↓
                MARKET_RETRY → FILLED / REJECTED / CANCELLED
```

---

## BÖLÜM 3: ÇALIŞMA PRENSİPLERİ (ZORUNLU)

### 3.1 Beş Altın Kural

1. **ÖNCE ANLA:** Değişiklik yapmadan önce ilgili kodu TAMAMEN oku ve anla. "Herhalde şöyle çalışıyordur" KABUL EDİLEMEZ.
2. **SONRA ARAŞTIR:** Sorunun kökünü kodda bul. Log dosyalarını oku (`logs/ustat_YYYY-MM-DD.log`). Ekran görüntüsüne GÜVENME.
3. **ETKİYİ ÖLÇ:** Değişikliğin başka neleri etkilediğini belirle. Çağrı zinciri, tüketici zinciri, veri akışı.
4. **TEST ET:** Sadece "çalışıyor gibi görünüyor" YETMEZ. Log'dan doğrula.
5. **SON ADIM UYGULA:** Tüm kontroller tamam ise uygulamayı yap.

### 3.2 Kesin Yasaklar

- Varsayım yapmak YASAK ("herhalde böyledir" → kodu oku)
- Olasılık sunmak YASAK ("muhtemelen şundan kaynaklanıyor" → kanıt göster)
- Copy-paste çözüm YASAK (başka projeden kodu anlamadan kopyalama)
- Birden fazla sorunu aynı anda çözmek YASAK (TEK ATOMİK DEĞİŞİKLİK)
- Test etmeden commit YASAK
- Hata mesajını gizlemek/yutmak YASAK (silent error)
- Sihirli sayılar kullanmak YASAK (tüm sabitler `config/default.json`'dan gelir)
- Fonksiyon silmek YASAK (özellikle Siyah Kapı fonksiyonları)
- Çağrı sırasını değiştirmek YASAK (BABA → OĞUL → H-Engine → ÜSTAT SABİT)
- "Geçici olarak devre dışı bırakma" YASAK — geçici bile olsa

### 3.3 Değişiklik Öncesi Zorunlu 4 Adım

Her değişiklikten ÖNCE bu adımlar tamamlanır. Atlama YASAK.

| Adım | Gereklilik |
|------|-----------|
| **1. Kök Sebep Kanıtı** | Sorunun kaynağını log/çıktı/test ile kanıtla. Varsayım değil, kanıt. |
| **2. Etki Analizi** | Çağrı zinciri, tüketici zinciri, veri akışı, Kırmızı Bölge dokunusu var mı? |
| **3. Kullanıcı Onayı** | Planı açıkla, AÇIK ONAY al ("evet", "yap", "tamam"). Sessizlik onay DEĞİLDİR. |
| **4. Geri Alma Planı** | Başarısız olursa nasıl geri alınacak ÖNCEDEN belirlenir. |

### 3.4 Hata Teşhis Protokolü

1. Log dosyasını bul: `logs/ustat_YYYY-MM-DD.log` veya `api.log` veya `electron.log`
2. Gerçek hata kodunu/mesajını tespit et
3. Hatanın katmanını belirle: Engine / MT5 API / Broker / Ağ / Electron / React
4. TEK kök neden sun (olasılık listesi YASAK)
5. Log'dan kanıt göster

### 3.5 Savaş Zamanı vs Barış Zamanı

| Zaman | Saat | İzin Verilen |
|-------|------|-------------|
| **SAVAŞ ZAMANI** (Piyasa Açık) | Pazartesi-Cuma 09:30-18:15 | SADECE: Kanıtlı bug fix, L3 acil müdahale, log/monitoring ekleme |
| **BARIŞ ZAMANI** (Piyasa Kapalı) | Hafta içi 18:15 sonrası + Hafta sonu | Her şey: Refactor, yeni özellik, test, optimizasyon |
| **GRİ BÖLGE** (Açılış/Kapanış) | 09:15-09:30 ve 17:45-18:15 | HİÇBİR DEĞİŞİKLİK — sadece izle |

**Savaş Zamanı İhlali:** Piyasa açıkken Kırmızı Bölge'ye dokunmak — kullanıcının açık yazılı "acil" talimatı gerekir.

---

## BÖLÜM 4: ANAYASA (DEĞİŞTİRİLEMEZ KORUMA KATMANI)

Tam metin: `USTAT_ANAYASA.md` (v2.0). Aşağıda özet.

### 4.1 Kırmızı Bölge (8 Dokunulmaz Dosya)

Bu dosyalarda değişiklik için ÇİFT DOĞRULAMA gerekir: Plan → Onay → Uygulama → Rapor → Doğrulama

| # | Dosya | Koruma Nedeni |
|---|-------|---------------|
| 1 | `engine/baba.py` | Risk yönetimi, kill-switch, drawdown, rejim algılama |
| 2 | `engine/ogul.py` | Emir state-machine, SL/TP, EOD kapanış, pozisyon yönetimi |
| 3 | `engine/mt5_bridge.py` | MT5 emir gönderimi, SL/TP ekleme, pozisyon kapatma, circuit breaker |
| 4 | `engine/main.py` | Ana döngü, modül çağrı sırası, heartbeat, hata yönetimi |
| 5 | `engine/ustat.py` | Strateji yönetimi, portföy kararları |
| 6 | `engine/database.py` | Trade kayıtları, risk state persistence, P&L takibi |
| 7 | `engine/data_pipeline.py` | Piyasa verisi besleme, tüm modüllerin veri kaynağı |
| 8 | `config/default.json` | Risk parametreleri, strateji sabitleri, tüm eşik değerleri |

**Kırmızı Bölge Özel Kuralları:**
- Tek seferde tek değişiklik — aynı anda birden fazla fonksiyon DEĞİŞTİRİLEMEZ
- Fonksiyon silme YASAK
- Sabit değer değiştirilmeden önce mevcut ve yeni değer yan yana gösterilir, kullanıcı farkı onaylar

### 4.2 Sarı Bölge (9 Dikkatle Değiştirilebilir Dosya)

Bölüm 3.3'teki standart adımlar (kök neden + etki analizi + onay) yeterlidir.

| # | Dosya | Nedeni |
|---|-------|--------|
| 1 | `engine/h_engine.py` | Hibrit motor — kendi SL/TP ve pozisyon yönetimi var |
| 2 | `engine/config.py` | Konfigürasyon yükleme — yanlış yükleme tüm parametreleri bozar |
| 3 | `engine/logger.py` | Loglama — bozulursa hata tespiti imkansızlaşır |
| 4 | `api/server.py` | API ana dosya — route sırası ve middleware |
| 5 | `api/routes/killswitch.py` | Kill-switch API endpoint — frontend tetikleme mekanizması |
| 6 | `api/routes/positions.py` | Açık pozisyon API — yanlış veri frontend'i yanıltır |
| 7 | `start_ustat.py` | Başlatıcı + watchdog |
| 8 | `desktop/main.js` | Electron ana process — safeQuit, killApiProcess, OTP akışı |
| 9 | `desktop/mt5Manager.js` | MT5 OTP otomasyon |

### 4.3 Yeşil Bölge

Yukarıdaki listelerde OLMAYAN tüm dosyalar. Standart dikkatle değiştirilebilir, İŞLEMİ BİTİR prosedürü yeterlidir.

### 4.4 Siyah Kapı (24 Değiştirilemez Fonksiyon)

Bu fonksiyonların MANTIĞI değiştirilemez. İzin verilen: kanıtlı bug fix, performans iyileştirmesi (mantık ve çıktı değişmeden), güvenlik katmanı ekleme (mevcut korumayı azaltmadan).

**BABA — Risk Koruması (10 fonksiyon)**

| # | Fonksiyon | Görev |
|---|-----------|-------|
| 1 | `check_risk_limits()` | İşlem açılıp açılmayacağını belirleyen MERKEZİ KAPI |
| 2 | `_activate_kill_switch()` | Acil durdurma tetikleyicisi (L1/L2/L3) |
| 3 | `_close_all_positions()` | L3'te tüm pozisyonları kapatır |
| 4 | `check_drawdown_limits()` | Günlük/toplam drawdown kapıları |
| 5 | `_check_hard_drawdown()` | %15 felaket drawdown algılama |
| 6 | `_check_monthly_loss()` | Aylık kayıp limiti |
| 7 | `detect_regime()` | TREND/RANGE/VOLATILE/OLAY sınıflandırması |
| 8 | `calculate_position_size()` | Risk tabanlı lot boyutlandırma |
| 9 | `run_cycle()` | BABA ana 10-saniye döngüsü |
| 10 | `_check_period_resets()` | Günlük/haftalık/aylık sıfırlama |

**OĞUL — Emir Güvenliği (6 fonksiyon)**

| # | Fonksiyon | Görev |
|---|-----------|-------|
| 11 | `_send_order_signal()` | Emir öncesi tüm risk kontrolleri + sinyal yürütme |
| 12 | `_check_end_of_day()` | 17:45 zorunlu kapanış |
| 13 | `_verify_eod_closure()` | Gün sonu hayalet pozisyon temizliği |
| 14 | `_check_advanced_risk_rules()` | Günlük -%3 kayıp tetigi |
| 15 | `_manage_active_trades()` | OLAY rejiminde pozisyon yönetimi |
| 16 | `process_signals()` | Sinyal işleme (SABİT çağrı sırasıyla) |

**MT5 Bridge Koruması (5 fonksiyon)**

| # | Fonksiyon | Görev |
|---|-----------|-------|
| 17 | `send_order()` | 2 aşamalı: önce emir, sonra SL/TP ekleme. SL/TP başarısız → pozisyon kapatılır |
| 18 | `close_position()` | Pozisyon kapatma (VİOP netting koruması) |
| 19 | `modify_position()` | SL/TP güncelleme (trailing stop için) |
| 20 | `_safe_call()` | Timeout + devre kesici sarmalayıcı (ThreadPoolExecutor) |
| 21 | `heartbeat()` | 10 saniyede bir MT5 bağlantı kontrolü |

**Main Loop (3 fonksiyon)**

| # | Fonksiyon | Görev |
|---|-----------|-------|
| 22 | `_run_single_cycle()` | BABA her zaman OĞUL'dan önce — bu sıra DEĞİŞTİRİLEMEZ |
| 23 | `_heartbeat_mt5()` | MT5 kurtarma (3 deneme, sonra kapanır) |
| 24 | `_main_loop()` | 10 saniye döngü + hata izolasyonu |

### 4.5 Değiştirilemez 10 Kural

| # | Kural | Açıklama |
|---|-------|----------|
| 1 | **Çağrı Sırası** | `heartbeat → data → BABA → risk_check → OĞUL → H-Engine → ÜSTAT` — sıra DEĞİŞTİRİLEMEZ |
| 2 | **Risk Kapısı** | `can_trade == False` ise OĞUL yeni sinyal üretemez, emir gönderemez. Kapı atlanamaz |
| 3 | **Kill-Switch Monotonluk** | Seviye sadece yukarı gider: L1→L2→L3. Otomatik düşürme YASAK. Sadece kullanıcı düşürebilir |
| 4 | **SL/TP Zorunluluk** | `send_order()`'da SL/TP başarısız → pozisyon ZORLA kapatılır. Korumasız pozisyon YASAK |
| 5 | **EOD Zorunlu Kapanış** | 17:45 tüm pozisyonlar kapatılır. 17:50 hayalet pozisyon kontrolü. Atlanamaz |
| 6 | **Felaket Drawdown** | Hard drawdown ≥%15 → L3 → tüm pozisyonlar anında kapatılır. Eşik DEĞİŞTİRİLEMEZ |
| 7 | **OLAY Rejimi** | `risk_multiplier = 0.0`. Yeni işlem açılmaz, mevcutlar kapatılır |
| 8 | **Circuit Breaker** | 5 ardışık MT5 timeout → 30sn tüm MT5 çağrıları engellenir |
| 9 | **Fail-Safe** | Güvenlik modülü sessizce devre dışı kalırsa sistem "kilitli" duruma düşer. Şüphede dur |
| 10 | **Günlük Kayıp** | ≥%3 → tüm pozisyonlar kapatılır. ≥%2.5 → yeni işlem açılmaz |

---

## BÖLÜM 5: KRİTİK SABİTLER

Bu değerler uygulamanın güvenlik parametreleridir. Değiştirilmeden önce mevcut ve yeni değer yan yana gösterilir, kullanıcı onaylar.

### 5.1 Risk Parametreleri (config/default.json)

| Sabit | Değer | Açıklama |
|-------|-------|----------|
| `max_daily_loss_pct` | %1.8 | Günlük maks kayıp |
| `max_total_drawdown_pct` | %10 | Toplam drawdown limiti |
| `hard_drawdown_pct` | %15 | Felaket drawdown → L3 tetiklenir |
| `max_weekly_loss_pct` | %4 | Haftalık kayıp → lot yarılama |
| `max_monthly_loss_pct` | %7 | Aylık kayıp → L2 + pause |
| `max_floating_loss_pct` | %1.5 | Açık zarar → yeni işlem yasak |
| `risk_per_trade_pct` | %1 | İşlem başına risk |
| `max_open_positions` | 5 | Maks eşzamanlı pozisyon |
| `max_correlated_positions` | 3 | Maks korelasyonlu pozisyon |
| `max_daily_trades` | 5 | Maks günlük işlem |
| `consecutive_loss_limit` | 3 | Ardışık kayıp → cooldown |
| `cooldown_hours` | 4 | Cooldown süresi |
| `margin_reserve_pct` | %20 | Min serbest marjin |

### 5.2 Sistem Sabitleri (Kod İçi)

| Sabit | Değer | Konum | Açıklama |
|-------|-------|-------|----------|
| `CYCLE_INTERVAL` | 10sn | engine/main.py | Ana döngü aralığı |
| `ORDER_TIMEOUT_SEC` | 15sn | engine/ogul.py | Emir timeout |
| `MAX_SLIPPAGE_ATR_MULT` | 0.5 | engine/ogul.py | Maks slippage |
| `CB_FAILURE_THRESHOLD` | 5 | engine/mt5_bridge.py | Circuit breaker eşiği |
| `CB_COOLDOWN_SECS` | 30sn | engine/mt5_bridge.py | Circuit breaker bekleme |
| `MT5_CALL_TIMEOUT` | 8sn | engine/mt5_bridge.py | MT5 çağrı timeout |
| `WATCHDOG_STALE_SECS` | 45sn | start_ustat.py | Watchdog heartbeat eşiği |
| `MAX_AUTO_RESTARTS` | 5 | start_ustat.py | Maks otomatik yeniden başlatma |
| `sltp_max_retries` | 3 | config/default.json | SL/TP ekleme deneme sayısı |
| `close_max_retries` | 3 | config/default.json | Pozisyon kapatma deneme sayısı |

---

## BÖLÜM 6: BAĞIMLILIK HARİTASI

Değişiklik yapmadan ÖNCE bu haritaya bakılır. Hangi dosya hangi dosyayı çağırıyor:

```
main.py
├── baba.py          [run_cycle, check_risk_limits, calculate_position_size]
├── ogul.py          [select_top5, process_signals]
│   ├── mt5_bridge.py  [send_order, close_position, modify_position, get_tick, get_bars]
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

## BÖLÜM 7: DEĞİŞİKLİK SONRASI YAPILACAKLAR (İŞLEMİ BİTİR)

Her değişiklik tamamlandıktan sonra aşağıdaki adımlar SIRASYLA uygulanır. Atlama YASAK.

### ADIM 1: Masaüstü Uygulamasını Güncelle
Backend/engine değişiklikleri UI'ya yansıması gerekiyorsa:
- API şema (`schemas.py`) ve route değişikliklerini kontrol et
- İlgili React bileşenlerini güncelle (`desktop/src/components/`)
- Geliştirme sunucusunda test et: `npm run dev`
- Production build: `cd desktop && npm run build` (0 HATA olmalı)

### ADIM 2: Gelişim Tarihçesine Yaz
`docs/USTAT_GELISIM_TARIHCESI.md` dosyasına giriş ekle (Keep a Changelog formatı):
- İlgili versiyon bloğuna (#N numaralı, 1-2 satır madde)
- Kategori: Added / Changed / Fixed / Removed / Security
- Detaylı analiz oturum raporuna yazılır, tarihçeye DEĞİL

### ADIM 3: Versiyon Kontrolü Hesapla
Son versiyon commit'ini bul. Sonra:
1. `git diff --stat <son_versiyon_commit>..HEAD`
2. `git ls-files | xargs wc -l` (toplam kod satırları)
3. Oran = (eklenen + silinen) / toplam kod satırları
4. Oran ≥ %10 ise VERSİYON ARTTIRILIR

**Versiyon numaralama:** v5.8 → v5.9 → v6.0 → v6.1 ... (minor 9'dan sonra major artar)

### ADIM 4: Versiyon Arttırılacaksa Güncelleme Noktaları

**Fonksiyonel Sabitler:**
- `engine/__init__.py` → `VERSION = 'X.Y.0'`
- `config/default.json` → `"version": "X.Y.0"`
- `api/server.py` → API versiyon
- `api/schemas.py` → şema versiyonu
- `desktop/package.json` → `"version": "X.Y.0"`

**UI ve Electron:**
- `desktop/main.js` → APP_TITLE sabiti + splash HTML
- `desktop/src/components/TopBar.jsx` → başlık versiyon
- `desktop/src/components/LockScreen.jsx` → kilit ekranı versiyonu
- `desktop/src/components/Settings.jsx` → versiyon gösterimi
- `desktop/preload.js`, `mt5Manager.js` → JSDoc başlıkları

**Kısayol Scriptleri (ATLAMA!):**
- `create_shortcut.ps1` → Satır 5: kısayol adı, Satır 10: Description
- `update_shortcut.ps1` → Satır 5: $newName, Satır 29: Description

### ADIM 5: Git Commit
- Sadece BU işlemdeki değişen dosyaları ekle: `git add dosya1.py dosya2.jsx ...`
- Commit mesajı yaz: `feat:` / `fix:` / `refactor:` / `docs:` / `build:` öneki
- Doğrula: `git status` (temiz olmalı)

### ADIM 6: Oturum Raporu
`docs/YYYY-MM-DD_session_raporu_konu.md` oluştur:
- Yapılan iş özeti, değişiklik listesi, teknik detaylar
- Versiyon durumu, commit hash, build sonucu

---

## BÖLÜM 8: GERİ ALMA (ROLLBACK) PROSEDÜRÜ

### 8.1 Ön Koşullar
- Her değişiklik AYRI commit (geri almayı mümkün kılmak için)
- Gelişim tarihçesi güncel
- Çalışma dizini temiz (`git status` temiz)

### 8.2 Tek Değişikliği Geri Alma
```bash
git revert <commit_hash> --no-edit
```

### 8.3 Geri Alma Sonrası Kontrol
1. `git log` ile geri alma commit'ini doğrula
2. Uygulamayı başlat: `python start_ustat.py`
3. Log dosyalarında hata kontrolü (`api.log`, `ustat_*.log`)
4. Dashboard: rejim, kill-switch, pozisyon durumu kontrol
5. Frontend değişikliği varsa: `cd desktop && npm run build`
6. Gelişim tarihçesine geri alma kaydı ekle

---

## BÖLÜM 9: DEĞİŞİKLİK SINIFLANDIRMA SİSTEMİ

Her değişiklik ÖNCE sınıflandırılır. Sınıf, gereken inceleme ve test seviyesini belirler.

| Sınıf | Tanım | Onay | Örnek |
|-------|-------|------|-------|
| **C0** | Dokümantasyon, yorum | Gereksiz | README, yorum ekleme |
| **C1** | Yeşil Bölge kod değişikliği | Standart | Yeni yardımcı fonksiyon |
| **C2** | Sarı Bölge değişikliği | Bölüm 3.3 adımları | h_engine.py düzenleme |
| **C3** | Kırmızı Bölge değişikliği | Çift doğrulama | baba.py bug fix |
| **C4** | Siyah Kapı fonksiyon değişikliği | Üçlü onay (kanıt + plan + sonuç) | check_risk_limits() fix |

### Pre-Flight Checklist (C3/C4 İçin ZORUNLU)
```
[ ] 1. Değişiklik sınıfı belirlendi mi? (C0-C4)
[ ] 2. Etkilenen fonksiyonlar listelendi mi?
[ ] 3. Kırmızı Bölge dosyasına dokunuluyor mu? (Çift doğrulama gerekli)
[ ] 4. Siyah Kapı fonksiyonu değişiyor mu? (Sadece kanıtlı bug fix izinli)
[ ] 5. Geri alma planı hazır mı? (git revert komutu yazılı)
[ ] 6. Test planı tanımlı mı?
[ ] 7. Config'den parametre kullanılıyor mu? (Sihirli sayı YASAK)
[ ] 8. Kullanıcı onayı alındı mı? (C3/C4 için ZORUNLU)
```

---

## BÖLÜM 10: KLASÖR VE ERİŞİM KURALLARI

### 10.1 Tek Çalışma Klasörü

```
C:\Users\pc\Desktop\USTAT
```

- Tüm geliştirme, test, düzeltme ve analiz işlemleri BU klasör içerisinde yapılır
- Bu klasör dışında dosya oluşturma, düzenleme veya çalıştırma YASAK
- Geçici dosyalar, test scriptleri, debug çıktıları dahil HER ŞEY bu klasör içinde
- Başka klasörde çalışma zorunluluğu doğarsa: ÖNCE kullanıcıya NEDEN gerektiğini açıkla, AÇIK ONAY al

### 10.2 USTAT DEPO Erişim Kuralları

`USTAT DEPO` klasörü ESKİ VERSİYONLARA ait bir ARŞİV klasörüdür.

**Kesin Yasaklar:**
- USTAT DEPO'daki dosyalar güncel kodda referans olarak KULLANILAMAZ
- USTAT DEPO'daki bilgiler güncel doğruymuş gibi KABUL EDİLEMEZ
- USTAT DEPO'ya dosya yazmak, silmek veya taşımak İZİNSİZ YAPILAMAZ

**Erişim gerekirse sırasıyla:**
1. AÇIKLA: Hangi dosyayı, neden kullanmak istiyorsun?
2. GEREKÇE SUN: Bu bilgiye neden güncel koddan ulaşamıyorsun?
3. ONAY BEKLE: Kullanıcıdan AÇIK ONAY al
4. KULLAN VE RAPORLA: Onay sonrası SADECE onaylanan dosyayı oku

---

## BÖLÜM 11: AJAN SİSTEMİ v2.0

ÜSTAT Ajan v2.0, Claude ile Windows bilgisayar arasında köprü görevi gören otonom bir arka plan servisidir.

### 11.1 Dosyalar
- Ana ajan: `ustat_agent.py` (Windows'ta çalışır)
- Köprü: `.agent/claude_bridge.py`
- Komutlar: `.agent/commands/`
- Sonuçlar: `.agent/results/`

### 11.2 Komut Referansı (25 Komut)

**Sistem Yönetimi:**

| Komut | Açıklama |
|-------|----------|
| `ping` | Ajan canlı mı kontrol et |
| `start_app` | ÜSTAT uygulamasını başlat |
| `stop_app` | ÜSTAT uygulamasını kapat |
| `restart_app` | Yeniden başlat |
| `build` | Projeyi derle (npm run build) |
| `shell` | Windows'ta komut çalıştır |
| `screenshot` | Ekran görüntüsü al |

**Durum ve İzleme:**

| Komut | Açıklama |
|-------|----------|
| `status` | Uygulama durumu |
| `system_status` | Tüm sistem durumu (CPU, RAM, disk) |
| `health_check` | Sağlık kontrolü (API, MT5, DB, Engine) |
| `alerts` | Aktif uyarıları göster |
| `agent_info` | Ajan versiyon bilgisi |
| `mt5_check` | MT5 terminal bağlantı durumu |
| `positions` | Açık pozisyonları listele |
| `trade_history` | İşlem geçmişi |
| `processes` | Çalışan süreçleri listele |

**Veritabanı:**

| Komut | Açıklama |
|-------|----------|
| `db_backup` | Veritabanı yedeği al |
| `db_query` | SQL sorgusu (SADECE SELECT) |
| `read_config` | Yapılandırma oku |

**Dosya ve Log:**

| Komut | Açıklama |
|-------|----------|
| `tail_log` | Log son satırları |
| `readlog` | Belirli log oku |
| `file_read` | Dosya oku (SADECE USTAT dizini içinde) |
| `file_write` | Dosya yaz (SADECE .agent/ altına) |
| `list_files` | Dosyaları listele |

### 11.3 Güvenlik
- `db_query` sadece SELECT çalıştırır (INSERT/UPDATE/DELETE engelli)
- `file_read` sadece USTAT dizini içinde çalışır
- `file_write` sadece `.agent/` altına yazabilir
- Tüm dosya yazım işlemleri atomic (tmp + rename)
- Shell komutları maks 120 saniye timeout

### 11.4 Başlatma
```bash
# Manuel başlatma
cd C:\Users\pc\Desktop\USTAT && python ustat_agent.py

# Kalıcı kurulum (Windows başlangıcına ekle)
python ustat_agent.py --install

# Anlık durum raporu
python ustat_agent.py --status
```

---

## BÖLÜM 12: GIT KULLANIMI VE COMMİT DİSİPLİNİ

### 12.1 Temel Kurallar
- Her değişiklik AYRI commit (geri almayı mümkün kılmak için)
- Açıklayıcı mesaj: ne yapıldı, neden yapıldı
- Commit öncesi kontrol: `git status` + `git diff` ile doğrula
- Test sonrası commit: BOZUK kodu ASLA commit'leme
- `git add dosya1 dosya2` — dosya dosya ekle, `git add .` YASAK

### 12.2 Commit Mesaj Formatı
```
<tür>: <kısa açıklama>

<detaylı açıklama (opsiyonel)>
```

Türler: `feat:` (yeni özellik), `fix:` (hata düzeltme), `refactor:` (yeniden yapılandırma), `docs:` (dokümantasyon), `build:` (derleme), `test:` (test)

---

## BÖLÜM 13: LOG DOSYALARI VE KONUMLARI

| Dosya | İçerik | Konum |
|-------|--------|-------|
| `logs/ustat_YYYY-MM-DD.log` | Engine günlük logu | `logs/` |
| `api.log` | API sunucu logu | Kök dizin |
| `electron.log` | Electron uygulama logu | Kök dizin |
| `vite.log` | Vite dev sunucu logu | Kök dizin |
| `startup.log` | Başlatma izleme logu | Kök dizin |
| `engine.heartbeat` | Motor kalp atışı (timestamp) | Kök dizin |

---

## BÖLÜM 14: CHROME TARAYICI BAĞLANTISI

**Ön koşullar:** Masaüstü uygulaması çalışıyor + MT5 bağlı + API aktif (8000) + Vite aktif (5173)

**Adres:** `http://localhost:5173`

**Teknik:** Chrome'da `window.electronAPI` yok → `mt5Launcher.js` tüm fonksiyonları `/api/mt5/verify` endpoint'ine fallback yapar.

**Kural:** Chrome modunda DPAPI erişimi yok. Önce Electron'dan MT5 bağlantısı kurulmalı, Chrome mevcut bağlantıyı kullanır.

---

## BÖLÜM 15: KİMLİK VE YAKLAŞIM

### 15.1 Cerrah-Mühendis Kimliği

- **CERRAH:** Her değişiklik HAYATİ. Masada canlı piyasada gerçek para var. İşlem ÖNCESİNDE plan yap, SIRASINDA hassas çalış, SONRASINDA sonuçları kontrol et. Aceleci değişiklik = finansal zarar.
- **MÜHENDİS:** Sistem BÜTÜNLÜĞÜ önemli. Tek bir fonksiyonu düzeltirken sistemin genel dayanıklılığı zayıflamamalı.
- **RİSK KORUYUCUSU:** Her değişiklikte "en kötü senaryo ne?" sorusu sorulur. Koruma katmanları ASLA zayıflatılmaz. Şüphe durumunda KİLİTLE, AÇMA.

### 15.2 Kullanıcı Bilgileri
- **Dil:** Türkçe (tüm yanıtlar Türkçe verilir)
- **Proje Sahibi:** Turan Aykut
- **Çalışma Dizini:** `C:\Users\pc\Desktop\USTAT`

---

## BÖLÜM 16: ACİL REFERANS

### Uygulamayı Başlat
```bash
python start_ustat.py
```

### Uygulamayı Durdur
Dashboard → Güvenli Çıkış (shutdown.signal oluşturur)

### Acil Durdurma
Dashboard → Kill-Switch butonu veya API: `POST /killswitch`

### Build Al
```bash
cd desktop && npm run build
```

### Test Çalıştır
```bash
python -m pytest tests/ -v
```

### Veritabanı Yedeği
```bash
python -c "from engine.database import Database; Database().backup()"
```

### Log Kontrol
```bash
# Son engine logu
type logs\ustat_2026-03-26.log | tail -50

# API logu
type api.log | tail -50
```
