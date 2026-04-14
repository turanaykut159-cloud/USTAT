# ÜSTAT v5.9 — ANA REHBER

**Versiyon:** 3.3 | **Tarih:** 10 Nisan 2026 | **Kaynak:** Kod tabanı doğrulaması
**Anayasa Referansı:** USTAT_ANAYASA.md — **ÜSTAT Plus V6.0** (v2.0) — ayrı belge, kendi versiyonlaması var
**Anayasa Sicili:** `governance/protected_assets.yaml` (makine-okunur korunan varlık kaydı)
**Anayasa Doğrulayıcı:** `tools/check_constitution.py` (manifest-kod senkron kontrolü)
**Etki Raporu Aracı:** `tools/impact_report.py` (C2/C3 değişiklikler öncesi zorunlu)
**Kurulum:** `scripts/setup_repo.ps1` (pre-commit hook + PyYAML)

> Bu dosya ÜSTAT projesinin TEK rehberidir. Tüm geliştiriciler (insan ve AI) bu kurallara MUTLAK uyum gösterir. Varsayım, olasılık, tahmin YASAKTIR — her karar kanıta dayanır.

> **ZORUNLU OKUMA:** Çalışmaya başlamadan önce `docs/USTAT_CALISMA_REHBERI.md` dosyası okunmalıdır. Bu rehber; günlük kontrol listeleri, kod değişikliği kuralları, test disiplini, canlı izleme metrikleri, acil durum yönetimi ve deployment sürecini tanımlar. Tüm geliştiriciler (insan ve AI) bu rehbere uyum gösterir.

---

## BÖLÜM 1: ÜSTAT NEDİR?

ÜSTAT v5.9, Borsa İstanbul VİOP (Vadeli İşlem ve Opsiyon Piyasası) üzerinde otomatik alım-satım yapan algoritmik bir trading platformudur. GCM Capital aracılığında MetaTrader 5 terminali üzerinden **canlı piyasada gerçek para ile** işlem yapar.

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
│   ├── __init__.py            # VERSION = "5.9.0"
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
│   └── routes/                # 20 endpoint modülü
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
│       ├── notifications.py   # Bildirim sistemi
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
│   ├── package.json           # v5.9.0
│   ├── index.html             # Giriş HTML
│   ├── vite.config.js         # Vite yapılandırması
│   └── src/
│       ├── App.jsx            # Ana React bileşeni
│       ├── main.jsx           # React giriş noktası
│       ├── components/        # 20 React bileşeni
│       │   ├── AutoTrading.jsx
│       │   ├── ConfirmModal.jsx
│       │   ├── Dashboard.jsx
│       │   ├── DraggableGrid.jsx
│       │   ├── ErrorBoundary.jsx
│       │   ├── ErrorTracker.jsx
│       │   ├── HybridTrade.jsx
│       │   ├── LockScreen.jsx
│       │   ├── ManualTrade.jsx
│       │   ├── Monitor.jsx
│       │   ├── NewsPanel.jsx
│       │   ├── Performance.jsx
│       │   ├── PrimnetDetail.jsx
│       │   ├── RiskManagement.jsx
│       │   ├── Settings.jsx
│       │   ├── SideNav.jsx
│       │   ├── SortableCard.jsx
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
│   ├── USTAT_CALISMA_REHBERI.md  # Profesyonel çalışma rehberi (ZORUNLU OKUMA)
│   └── YYYY-MM-DD_session_raporu_*.md
│
├── tests/                     # Test paketi
│   ├── test_unit_core.py
│   ├── test_news_100_combinations.py
│   ├── test_1000_combinations.py
│   ├── test_hybrid_100.py
│   ├── test_ogul_200.py
│   └── test_stress_10000.py
│
├── mql5/                      # MQL5 scriptleri
├── logs/                      # Log dosyaları
├── .agent/                    # Ajan köprüsü ve komutları
│
├── CLAUDE.md                  # BU DOSYA — Ana rehber
├── USTAT_ANAYASA.md           # Anayasa (değiştirilemez koruma katmanı)
├── start_ustat.py             # Başlatıcı + watchdog
├── ustat_agent.py             # Otonom ajan (v3.2)
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
        → Single instance kilidi (Named Mutex + port + lock file)
        → Alt process başlat (multiprocessing):
            → API + Engine başlat (uvicorn, port 8000)
                → Engine._connect_mt5() → connect(launch=False)
                → ⚠️ terminal64.exe process kontrolü → yoksa mt5.initialize() ATLANIR
                → Engine MT5 olmadan çalışmaya başlar (heartbeat polling devam eder)
            → Electron başlat (USTAT_API_MODE=1, localhost:8000 yükler)
                → LockScreen gösterilir
                → Kullanıcı credentials → mt5Manager.js launchMT5() → terminal64.exe açılır
                → Kullanıcı OTP girer → MT5 bağlantısı kurulur
                → Engine heartbeat sonraki döngüde MT5'e bağlanır → Dashboard
            → Electron kapanınca → API/Engine güvenle durdur
        → System tray (pystray) başlat
        → Alt process izle (crash'te yeniden başlat)
```

**KRİTİK (Anayasa Kural 4.15):** MT5 terminal açma sorumluluğu SADECE Electron'dadır (mt5Manager.js → launchMT5). Engine hiçbir koşulda MT5'i başlatamaz. Bu kural DEĞİŞTİRİLEMEZ.

**NOT:** Production modda UI, Electron ile açılır (titleBarStyle: 'hidden' + titleBarOverlay).
Electron, Windows native pencere yönetimi kullanır (çoklu monitör, maximize, snap desteği).
pywebview KULLANILMAZ (v5.9.1 itibariyle kaldırıldı).

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

### 3.1 Altı Altın Kural

1. **ÖNCE ANLA:** Değişiklik yapmadan önce ilgili kodu TAMAMEN oku ve anla. "Herhalde şöyle çalışıyordur" KABUL EDİLEMEZ.
2. **SONRA ARAŞTIR:** Sorunun kökünü kodda bul. Log dosyalarını oku (`logs/ustat_YYYY-MM-DD.log`). Ekran görüntüsüne GÜVENME.
3. **ÇALIŞMA ZAMANINI DOĞRULA:** Değişiklik yapacağın dosyanın GERÇEKTEN çalışan dosya olduğunu kanıtla. Uygulamanın hangi modda (Electron/pywebview/Chrome), hangi process ile, hangi dosyayı kullanarak çalıştığını LOG veya PROCESS kontrolüyle doğrula. Yanlış dosyayı düzeltmek = sıfır iş. **Kontrol yöntemi:** `startup.log` oku, çalışan process'leri kontrol et, hangi portta ne dinliyor doğrula.
4. **ETKİYİ ÖLÇ:** Değişikliğin başka neleri etkilediğini belirle. Çağrı zinciri, tüketici zinciri, veri akışı.
5. **TEST ET:** Sadece "çalışıyor gibi görünüyor" YETMEZ. Log'dan doğrula.
6. **SON ADIM UYGULA:** Tüm kontroller tamam ise uygulamayı yap.

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

### 3.3 Değişiklik Öncesi Zorunlu 5 Adım

Her değişiklikten ÖNCE bu adımlar tamamlanır. Atlama YASAK.

| Adım | Gereklilik |
|------|-----------|
| **0. Çalışma Zamanı Doğrulama** | Değiştireceğin dosyanın GERÇEKTEN çalışan dosya olduğunu kanıtla. `startup.log` oku, process kontrol et, hangi runtime aktif (Electron vs pywebview vs Chrome) doğrula. **Yanlış dosyayı düzeltmek = sıfır iş.** |
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

### 4.1 Kırmızı Bölge (10 Dokunulmaz Dosya)

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
| 9 | `start_ustat.py` | Başlatma zinciri, watchdog, graceful shutdown — startup performansı koruması |
| 10 | `api/server.py` | API lifespan, Engine oluşturma sırası, route kayıt — startup performansı koruması |

**Kırmızı Bölge Özel Kuralları:**
- Tek seferde tek değişiklik — aynı anda birden fazla fonksiyon DEĞİŞTİRİLEMEZ
- Fonksiyon silme YASAK
- Sabit değer değiştirilmeden önce mevcut ve yeni değer yan yana gösterilir, kullanıcı farkı onaylar

### 4.2 Sarı Bölge (7 Dikkatle Değiştirilebilir Dosya)

Bölüm 3.3'teki standart adımlar (kök neden + etki analizi + onay) yeterlidir.

| # | Dosya | Nedeni |
|---|-------|--------|
| 1 | `engine/h_engine.py` | Hibrit motor — kendi SL/TP ve pozisyon yönetimi var |
| 2 | `engine/config.py` | Konfigürasyon yükleme — yanlış yükleme tüm parametreleri bozar |
| 3 | `engine/logger.py` | Loglama — bozulursa hata tespiti imkansızlaşır |
| 4 | `api/routes/killswitch.py` | Kill-switch API endpoint — frontend tetikleme mekanizması |
| 5 | `api/routes/positions.py` | Açık pozisyon API — yanlış veri frontend'i yanıltır |
| 6 | `desktop/main.js` | Electron ana process — safeQuit, killApiProcess, OTP akışı, tray yönetimi |
| 7 | `desktop/mt5Manager.js` | MT5 OTP otomasyon |

### 4.3 Yeşil Bölge

Yukarıdaki listelerde OLMAYAN tüm dosyalar. Standart dikkatle değiştirilebilir, İŞLEMİ BİTİR prosedürü yeterlidir.

### 4.4 Siyah Kapı (31 Değiştirilemez Fonksiyon)

Bu fonksiyonların MANTIĞI değiştirilemez. İzin verilen: kanıtlı bug fix, performans iyileştirmesi (mantık ve çıktı değişmeden), güvenlik katmanı ekleme (mevcut korumayı azaltmadan).

**BABA — Risk Koruması (11 fonksiyon)**

| # | Fonksiyon | Görev |
|---|-----------|-------|
| 1 | `check_risk_limits()` | İşlem açılıp açılmayacağını belirleyen MERKEZİ KAPI |
| 2 | `_activate_kill_switch()` | Acil durdurma tetikleyicisi (L1/L2/L3) |
| 3 | `_close_all_positions()` | L3'te tüm pozisyonları kapatır (manuel dahil) |
| 4 | `_close_ogul_and_hybrid()` | L2 günlük/aylık kayıp tetiğinde SADECE OĞUL + Hybrid pozisyonlarını kapatır — manuele dokunmaz |
| 5 | `check_drawdown_limits()` | Günlük/toplam drawdown kapıları |
| 6 | `_check_hard_drawdown()` | %15 felaket drawdown algılama |
| 7 | `_check_monthly_loss()` | Aylık kayıp limiti |
| 8 | `detect_regime()` | TREND/RANGE/VOLATILE/OLAY sınıflandırması |
| 9 | `calculate_position_size()` | Risk tabanlı lot boyutlandırma |
| 10 | `run_cycle()` | BABA ana 10-saniye döngüsü |
| 11 | `_check_period_resets()` | Günlük/haftalık/aylık sıfırlama |

**OĞUL — Emir Güvenliği (5 fonksiyon)**

| # | Fonksiyon | Görev |
|---|-----------|-------|
| 12 | `_execute_signal()` | Emir öncesi risk kontrolleri + sinyal yürütme (BABA `can_trade` kapısı arkasında) |
| 13 | `_check_end_of_day()` | 17:45 zorunlu kapanış (manuel + orphan hariç) |
| 14 | `_verify_eod_closure()` | Gün sonu hayalet pozisyon temizliği (manuel + orphan exclusion) |
| 15 | `_manage_active_trades()` | Pozisyon yönetimi (orphan guard'lı) |
| 16 | `process_signals()` | Sinyal işleme (SABİT çağrı sırasıyla — günlük/aylık kayıp kontrolü BABA'ya devredildi) |

**MT5 Bridge Koruması (6 fonksiyon)**

| # | Fonksiyon | Görev |
|---|-----------|-------|
| 17 | `send_order()` | 2 aşamalı: önce emir, sonra SL/TP ekleme. SL/TP başarısız → pozisyon kapatılır |
| 18 | `close_position()` | Pozisyon kapatma (VİOP netting koruması) |
| 19 | `modify_position()` | SL/TP güncelleme (trailing stop için) |
| 20 | `_safe_call()` | Timeout + devre kesici sarmalayıcı (ThreadPoolExecutor) |
| 21 | `heartbeat()` | 10 saniyede bir MT5 bağlantı kontrolü |
| 31 | `connect()` | MT5 bağlantı — launch=False modda terminal64.exe process kontrolü. MT5 çalışmıyorsa initialize() ÇAĞRILMAZ. MT5 açma sorumluluğu SADECE Electron'dadır |

**Main Loop (3 fonksiyon)**

| # | Fonksiyon | Görev |
|---|-----------|-------|
| 22 | `_run_single_cycle()` | BABA her zaman OĞUL'dan önce — bu sıra DEĞİŞTİRİLEMEZ |
| 23 | `_heartbeat_mt5()` | MT5 kurtarma (3 deneme, sonra kapanır) |
| 24 | `_main_loop()` | 10 saniye döngü + hata izolasyonu |

**Startup/Shutdown Koruması (6 fonksiyon)**

| # | Fonksiyon | Dosya | Görev |
|---|-----------|-------|-------|
| 25 | `run_webview_process()` | start_ustat.py | API thread → port bekleme → Electron başlatma → kapanış zinciri |
| 26 | `_start_api()` | start_ustat.py | Uvicorn başlatma — config değişikliği startup performansını BOZAR |
| 27 | `_shutdown_api()` | start_ustat.py | Graceful shutdown — engine.stop() zincirini tetikler |
| 28 | `lifespan()` | api/server.py | Engine nesne oluşturma sırası — constructor sırası DEĞİŞTİRİLEMEZ |
| 29 | `main()` | start_ustat.py | ProcessGuard + Mutex + subprocess — tek instance koruması |
| 30 | `createWindow()` | desktop/main.js | Electron pencere oluşturma + API bekleme + crash handler |

### 4.5 Değiştirilemez 16 Kural

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
| 10 | **Günlük Kayıp** | BABA günlük/aylık kayıp tetiğinde L2 kill-switch devreye girer → `_close_ogul_and_hybrid()` çağrılır → SADECE OĞUL + Hybrid pozisyonları kapanır (manuel dokunulmaz). OĞUL artık kendi günlük kayıp check'i yapmaz — tek merkez BABA'dır |
| 11 | **Başlatma Zinciri** | `start_ustat.py → ProcessGuard → Mutex → API thread (uvicorn) → port_open bekleme → Electron → wait` — sıra DEĞİŞTİRİLEMEZ |
| 12 | **Lifespan Sırası** | `Config → Database → MT5Bridge → DataPipeline → Ustat → Baba → Ogul → Engine` — constructor sırası DEĞİŞTİRİLEMEZ |
| 13 | **Kapanış Sırası** | Electron ÖNCE kapanır → lifespan engine.stop() → MT5 disconnect → DB close. Tersine çevirmek renderer crash'e neden olur |
| 14 | **Startup Performans** | API port hazır süresi ≤5sn olmalı. Gecikme tespit edilirse (≥10sn) kök neden araştırılır. TIME_WAIT socket temizliği start_ustat.py ProcessGuard'da yapılır |
| 15 | **MT5 Başlatma Sorumluluğu** | MT5 terminal açma sorumluluğu SADECE Electron'dadır (mt5Manager.js → launchMT5). Engine hiçbir koşulda MT5'i başlatamaz. `connect(launch=False)` modunda `mt5.initialize()` çağrılmadan ÖNCE `terminal64.exe` process kontrolü yapılır. Process yoksa bağlantı atlanır. Bu koruma DEĞİŞTİRİLEMEZ |
| 16 | **mt5.initialize() Evrensel Koruma** | Projede `mt5.initialize()` çağrılan HER noktada process kontrolü zorunludur. Yeni `mt5.initialize()` çağrısı eklemek YASAKTIR — tüm MT5 bağlantısı `mt5_bridge.py connect()` üzerinden yapılır. Korunan noktalar: connect(), _verify(), health_check.py |

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
| `SHUTDOWN_MAX_WAIT` | 45sn | start_ustat.py | Graceful shutdown max bekleme |
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

### ADIM 1: Masaüstü Uygulamasını Güncelle — BUILD ZORUNLULUĞU

**⚠️ KRİTİK MİMARİ BİLGİ — FRONTEND DEĞİŞİKLİKLERİ İÇİN ZORUNLU OKUMA:**

Uygulama Electron ile **production modda** çalışır. Electron, React kaynak dosyalarını (`.jsx`) doğrudan OKUMAZ — sadece `desktop/dist/` klasöründeki derlenmiş JavaScript bundle'ını yükler. Akış şöyledir:

```
Kaynak kod (.jsx) → npm run build → Derlenmiş bundle (dist/) → Electron BUNU yükler
```

Bu demektir ki: **kaynak dosyayı düzenlemek TEK BAŞINA yetmez.** Build yapılmazsa Electron eski `dist/` bundle'ını yüklemeye devam eder ve değişiklikler GÖRÜNMEZ. Dosya doğru, kod doğru, yer doğru — ama uygulama o dosyayı okumuyordur bile.

**Build yapılmadan önce değişiklik "uygulandı" SAYILMAZ. Bu adım atlanamaz.**

Adımlar:
- API şema (`schemas.py`) ve route değişikliklerini kontrol et
- İlgili React bileşenlerini güncelle (`desktop/src/components/`)
- **Windows makinede** production build çalıştır: `python .agent/claude_bridge.py build` (0 HATA olmalı)
- Build sonrası uygulamayı yeniden başlat: `python .agent/claude_bridge.py restart_app`
- Değişikliğin ekranda göründüğünü doğrula (ekran görüntüsü veya kullanıcı teyidi)

### ADIM 1.5: KRİTİK AKIŞ TESTLERİ — ZORUNLU KORUMA HALKASI

**⚠️ NEDEN ZORUNLU:** "Bir yeri tamir ederken başka bir yeri bozmamak" anayasal bir gerekliliktir. Bu adım atlandığı için geçmişte hibrit devir akışı, TopBar banner, send_order SL/TP gibi kritik davranışlar sessizce bozuldu. Artık HER değişiklik sonrası `tests/critical_flows` YEŞİLE dönmek zorundadır.

**Çalıştırma:**
```bash
python -m pytest tests/critical_flows -q --tb=short
```

**Beklenen çıktı:** `N passed` — başarısız test VARSA commit YASAK.

**Kapsam (12 kritik akış):**
1. `send_order` 2-aşamalı SL/TP ekleme (mt5_bridge)
2. SL/TP başarısız → korumasız pozisyon kapatma (ogul.py Anayasa 4.4)
3. EOD 17:45 zorunlu kapanış (ogul `_check_end_of_day`)
4. Hard drawdown ≥%15 → L3 (baba `_check_hard_drawdown`)
5. Kill-switch L2 — `_close_ogul_and_hybrid` (manuel dokunulmaz)
6. Kill-switch L3 — `_close_all_positions`
7. BABA `can_trade` kapısı OĞUL'da kontrol (`_execute_signal`)
8. Circuit breaker 5 ardışık timeout
9. heartbeat `terminal_info` → `_trade_allowed` yakalaması
10. Main loop sırası: BABA önce, OĞUL sonra
11. Config'den sihirli sayı kullanımı (`self.config.get` ile)
12. `mt5.initialize()` evrensel koruma (bridge dışı yasak)

**Eksik akış ekleme kuralı:** Yeni bir kritik davranış eklendiğinde (ör. yeni kill-switch katmanı, yeni koruma fonksiyonu) `tests/critical_flows/test_static_contracts.py` içinde statik sözleşme testi yazılır. Test yazılmadan commit YASAK.

**Pre-commit entegrasyonu:** `.githooks/pre-commit` bu testleri otomatik çalıştırır. Kurulum:
```bash
git config core.hooksPath .githooks
```

**Etki analizi aracı:** Kırmızı Bölge dosyasına dokunmadan ÖNCE:
```bash
python tools/impact_map.py <dosya_yolu>
python tools/impact_map.py <dosya>::<fonksiyon>  # Fonksiyon çağrı zinciri
```

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

## BÖLÜM 11: AJAN SİSTEMİ v3.2

ÜSTAT Ajan v3.2, Claude ile Windows bilgisayar arasında köprü görevi gören otonom bir arka plan servisidir. Singleton koruması (PID + psutil), atomik komut kilitleme (.processing rename), FUSE bypass, Claude-Cowork entegrasyonu ve Windows Service desteği sunar.

### 11.1 Dosyalar
- Ana ajan: `ustat_agent.py` (Windows'ta çalışır, 3686 satır)
- Köprü: `.agent/claude_bridge.py`
- Komutlar: `.agent/commands/`
- Sonuçlar: `.agent/results/`

### 11.2 Komut Referansı (37 Komut)

Kaynak: `ustat_agent.py` → `HANDLERS` sözlüğü
Kullanım: `python .agent/claude_bridge.py <komut> [parametreler]`

**Uygulama Yönetimi (5):**

| Komut | Handler | Açıklama |
|-------|---------|----------|
| `start_app` | `handle_start_app` | ÜSTAT'ı başlat (`schtasks /IT` ile kullanıcı oturumunda) |
| `stop_app` | `handle_stop_app` | Tüm ÜSTAT process'lerini durdur |
| `restart_app` | `handle_restart_app` | Akıllı restart (durdur + başlat + API bekle) |
| `build` | `handle_build` | Desktop `npm run build` — production derleme |
| `shortcut` | `handle_shortcut` | Masaüstü kısayolunu güncelle |

**Sistem Durumu ve İzleme (8):**

| Komut | Handler | Açıklama |
|-------|---------|----------|
| `ping` | `handle_ping` | Ajan canlılık kontrolü |
| `status` | `handle_system_status` | API, Engine, MT5, DB, disk durumu |
| `system_status` | `handle_system_status` | Detaylı sistem durumu (CPU, RAM, disk) |
| `health_check` | `handle_health_check` | Kapsamlı sağlık kontrolü |
| `mt5_check` | `handle_mt5_check` | MT5 terminal bağlantı durumu |
| `processes` | `handle_processes` | Çalışan süreçleri listele (filtre destekli) |
| `agent_info` | `handle_agent_info` | Ajan versiyon, PID, uptime, yetenekler |
| `alerts` | `handle_alerts` | Aktif uyarılar (unresolved/all/resolve) |

**Trading Bilgisi (2):**

| Komut | Handler | Açıklama |
|-------|---------|----------|
| `positions` | `handle_positions` | Açık pozisyonları listele |
| `trade_history` | `handle_trade_history` | İşlem geçmişi (symbol/limit filtreli) |

**Veritabanı (3):**

| Komut | Handler | Açıklama |
|-------|---------|----------|
| `db_backup` | `handle_db_backup` | Veritabanı yedeği al |
| `db_query` | `handle_db_query` | SQL sorgusu (SADECE SELECT — yazma engelli) |
| `read_config` | `handle_read_config` | Config dosyasını oku (key filtreli) |

**Log ve Dosya (5):**

| Komut | Handler | Açıklama |
|-------|---------|----------|
| `tail_log` | `handle_tail_log` | Birden fazla logdan son satırlar (api/startup/agent/electron) |
| `readlog` | `handle_readlog` | Belirli log dosyası oku (satır sayısı belirtilebilir) |
| `file_read` | `handle_file_read` | Dosya oku (SADECE USTAT dizini içinde) |
| `file_write` | `handle_file_write` | Dosya yaz (SADECE `.agent/` altına) |
| `list_files` | `handle_list_files` | Dizin listele (path + pattern filtreli) |

**Shell (2):**

| Komut | Handler | Açıklama |
|-------|---------|----------|
| `shell` | `handle_shell` | Windows'ta komut çalıştır (CMD/PowerShell, maks 120sn timeout) |
| `screenshot` | `handle_screenshot` | Ekran görüntüsü al |

**Log Yönetim Sistemi — v3.0 (5):**

| Komut | Handler | Açıklama |
|-------|---------|----------|
| `fresh_engine_log` | `handle_fresh_engine_log` | Engine logunu FUSE cache bypass ile oku |
| `search_all_logs` | `handle_search_all_logs` | Tüm loglarda arama (pattern destekli) |
| `log_digest` | `handle_log_digest` | Log özeti (hata/uyarı sayıları, son olaylar) |
| `log_stats` | `handle_log_stats` | Log istatistikleri (boyut, satır sayısı, tarih aralığı) |
| `log_export` | `handle_log_export` | Log dışa aktarma (tarih/seviye filtreli) |

**FUSE Bypass — Tam Dosya Erişim (5):**

| Komut | Handler | Açıklama |
|-------|---------|----------|
| `fresh_file_read` | `handle_fresh_file_read` | Dosya oku (önbellek bypass) |
| `fresh_file_stat` | `handle_fresh_file_stat` | Dosya bilgisi (boyut, tarih, izinler) |
| `fresh_dir_stat` | `handle_fresh_dir_stat` | Dizin bilgisi (dosya sayısı, toplam boyut) |
| `fresh_file_search` | `handle_fresh_file_search` | Dosya ara (pattern destekli) |
| `fresh_grep` | `handle_fresh_grep` | İçerik ara (regex destekli) |

**Claude-Cowork Entegrasyonu — v3.1 (12):**

| Komut | Handler | Açıklama |
|-------|---------|----------|
| `window_list` | `handle_window_list` | Açık pencereleri listele (HWND, başlık, PID, boyut) |
| `window_focus` | `handle_window_focus` | Pencereyi öne getir (HWND veya başlık ile) |
| `clipboard_read` | `handle_clipboard_read` | Pano içeriğini oku |
| `clipboard_write` | `handle_clipboard_write` | Panoya yaz |
| `system_info` | `handle_system_info` | Sistem bilgisi (OS, CPU, RAM, uptime) |
| `process_detail` | `handle_process_detail` | Detaylı process metrikleri (CPU, RAM, disk I/O) |
| `net_connections` | `handle_net_connections` | Ağ bağlantıları listesi |
| `env_vars` | `handle_env_vars` | Ortam değişkenlerini oku |
| `installed_software` | `handle_installed_software` | Yüklü yazılım listesi |
| `service_list` | `handle_service_list` | Windows servisleri listesi |
| `scheduled_tasks` | `handle_scheduled_tasks` | Zamanlanmış görevler listesi |
| `quick_look` | `handle_quick_look` | Hızlı sistem özeti (tek komutla her şey) |

### 11.3 Güvenlik
- `db_query` sadece SELECT çalıştırır (INSERT/UPDATE/DELETE engelli)
- `file_read` sadece USTAT dizini içinde çalışır
- `file_write` sadece `.agent/` altına yazabilir
- Tüm dosya yazım işlemleri atomic (tmp + rename)
- Shell komutları maks 120 saniye timeout
- Singleton koruması: PID dosyası + psutil ile çoklu instance engellenir
- Atomik komut kilitleme: `.processing` rename ile aynı komutun tekrar işlenmesi önlenir

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

### 12.2 Commit Mesaj Forma

Öneki + kısa özet + (gerekirse) detay:
- `feat:` yeni özellik
- `fix:` hata düzeltme
- `refactor:` davranış değişmeden yapı iyileştirme
- `docs:` sadece dokümantasyon
- `build:` build/deps
- `test:` test ekleme/düzenleme
- `chore:` bakım

Örnek: `fix(baba): hard drawdown tetiklenmiyordu (#142)`

---

## BÖLÜM 13: TOKEN DİSİPLİNİ VE PERFORMANS (TokenMax v3.0)

**Amaç:** Claude/Cowork session'larında token israfını minimuma, iş kalitesini maksimuma çıkarmak. Max plan kotası, context rot ve cache expiry'den kaynaklanan verim kaybını engellemek.

**Kaynak ölçümler:** Cache-aware rate limits (Şubat 2026 Anthropic güncellemesi), `.claudeignore` etkisi (%40-70 per-request), trigger-based CLAUDE.md (%54 initial context), skill on-demand loading.

### 13.1 Üç Katmanlı Context Yükleme

| Katman | Dosya | Ne Zaman |
|---|---|---|
| **L1 — CORE** | `CLAUDE_CORE.md` | Her session'da otomatik |
| **L2 — FULL** | `CLAUDE.md` (bu dosya) | L1 yetersiz kaldığında (C2/C3/C4 veya detay gerekli) |
| **L3 — ANAYASA** | `USTAT_ANAYASA.md` | Kırmızı Bölge / Siyah Kapı dokunuşu öncesi |

**Kural:** L2/L3'ü gerekmedikçe yükleme. Soru L1'de cevaplanabiliyorsa orada kal.

### 13.2 `.claudeignore` Kuralı

Proje kökündeki `.claudeignore` dosyası Claude tarafından otomatik okunur. Bu dosyanın içeriği **her session** başında filtre olarak devreye girer. İçeriği değişirse tüm ekip haberdar edilir.

**Kapsamı:** veritabanı binary'leri, `desktop/dist/`, `__pycache__/`, `logs/`, `.agent/results/`, `USTAT DEPO/`, IDE geçicileri.

### 13.3 Dosya Okuma Disiplini (Claude için)

1. **Grep > Read.** Fonksiyon aramak için önce `Grep`, sonra hedefli `Read offset+limit`.
2. **Edit > Write.** Mevcut dosyada değişiklik için `Edit` (diff gönderir). `Write` sadece yeni dosya veya tam yeniden yazım.
3. **Aynı session'da dosya tekrar okuma YASAK.** İlk okumayı hatırla, üzerine çalış.
4. **Tüm dosyayı okumak zorunlu ise** gerekçe söyle (örn: "Siyah Kapı fonksiyonu tüm imzasını görmem lazım").
5. **Log analizinde ajan kullan:** `tail_log`, `search_all_logs`, `log_digest` — full log dump'ı context'e çekme.

### 13.4 Model Seçim Matrisi

| İş Tipi | Model | Gerekçe |
|---|---|---|
| Log oku, küçük fix, rapor oku, basit refactor | **Haiku 4.5** | %80 ucuz, quota yakmaz |
| Orta karmaşıklık, C1/C2, build sonrası kontrol, Sarı Bölge | **Sonnet 4.6** | Varsayılan |
| C3/C4, Kırmızı Bölge, Siyah Kapı debug, karmaşık refactor | **Opus 4.6** | Sadece gerçekten gerekirse |

**Kural:** Opus kullanımında "reasoning effort = medium" (high → 3-5x token). Yüksek efor sadece imkansız debug için.

### 13.5 Zorunlu Task Prompt Şablonu

```
[ZONE: Green|Yellow|Red] [CLASS: C0-C4]
GOAL: <tek cümle>
FILES: <yol listesi — 3'ten fazlaysa önce plan al>
CONSTRAINTS: Anayasa ihlal YOK
OUTPUT: diff + etki + risk (max 300 token)
```

Şablon dışı prompt'lar kabul edilebilir ama token tüketimi otomatik artar. Açık uçlu sorularda önce ne istediğini daralt.

### 13.6 Session & Cache Kuralları

1. **Her farklı iş → yeni session veya `/clear`.** Aynı session'da konu atlama = context rot.
2. **Task bitince proaktif `/compact`.** Zorunlu compact'i bekleme.
3. **5 dakika idle → cache expire.** Uzun araya gidecekseniz session'ı kapatın. Cache expired bir session'a dönmek = tüm context yeniden process (10-20x token).
4. **Cache breakpoint stratejisi:** `CLAUDE_CORE.md` + (gerekirse) `USTAT_ANAYASA.md` birlikte ilk cache bloğu. Sık değişmeyen içerik önce.

### 13.7 MCP / Tool Disiplini

- Her aktif MCP ~1-5k token sabit yük.
- ÜSTAT workspace'inde gereksiz MCP'leri **kapalı tut**: Chrome MCP (trading işinde lazım değil), onboarding, plugin registry.
- `ENABLE_TOOL_SEARCH` / deferred tool loading Cowork'ta zaten aktif — schema'lar on-demand yüklenir.
- Yeni tool eklemeden önce token maliyet/fayda değerlendirmesi yap.

### 13.8 Agent Delegasyonu

Açık uçlu araştırma (3+ dosya tarama, "projede X nerede kullanılıyor") → `Agent` tool'a devredilir. Ayrı context, sadece özet ana session'a döner. Ana session şişmez.

**Ne zaman delege et:**
- "Tüm kodda X pattern'ini bul"
- "Tarih filtreli log özeti"
- "Bağımlılık zinciri çıkar"
- Birden fazla dosya açmayı gerektiren araştırma

### 13.9 Şeffaflık ve Uyarı Eşikleri

Claude, bir task için tahmini >15k token okuma/yazma yapacaksa **önce kullanıcıya söyler**: "Bu iş yaklaşık Xk token yiyecek — Haiku'ya mı alalım / plan+exec ayıralım mı?"

Sessiz kota yakma YASAK.

### 13.10 Beklenen Kazanım ve Doğrulama

Hedef: Max 20x kotası 3 gün yerine 7-10 güne yayılsın. İlk değer: %46/3 gün → hedef: %25-30/7 gün.

**Ölçüm:**
- Her session sonunda Claude Usage sayfası screenshot'ı `docs/token_audit/YYYY-MM-DD.png`
- Haftalık token audit: `docs/token_audit/weekly_YYYY-WW.md`
- Anomali (beklenenden %50 fazla) → kök neden analizi (hangi dosya, hangi tool, hangi model?)

### 13.11 İhlal Durumunda

- Token disiplini ihlali Savaş Zamanı yasağı değildir, ama israf olarak raporlanır.
- Tekrarlayan ihlal → prompt şablonu zorunluluğu + session başına `.claudeignore` doğrulama.

### 13.12 Claude Subagent Orkestrasyonu

USTAT için `C:\Users\pc\.claude\agents/` altında 6 özel subagent tanımlı. Her biri kendi şeridinde uzman, kendi token disiplinine sahip, ana session'ı şişirmeden iş yapar.

**Temel prensip:** *Ajan kullanımı = token tasarrufu.* Ajan ayrı context'te koşar, ana session'a sadece **özet rapor** döner. 15k+ token'lık araştırma/uygulama işi doğrudan ana session'da yapılırsa `CLAUDE.md` + `ANAYASA` + dosya okumaları üst üste yığılır. Aynı iş ajana devredildiğinde ana session ~500 token özet alır.

#### 13.12.1 Ajan Envanteri

| # | Ajan | Model | Alan | Rol |
|---|---|---|---|---|
| 1 | `ustat-engine-guardian` | **Opus** | `engine/*.py` | Kırmızı Bölge + Siyah Kapı implementasyonu |
| 2 | `ustat-api-backend` | Sonnet | `api/*.py` | FastAPI routes, schemas, lifespan |
| 3 | `ustat-desktop-frontend` | Sonnet | `desktop/` | Electron + React + Vite (build ZORUNLU) |
| 4 | `ustat-auditor` | **Opus** | READ-ONLY | Kök neden, etki analizi, plan — kod yazmaz |
| 5 | `ustat-ops-watchdog` | Sonnet | `start_ustat.py`, `.agent/`, logs | Startup, watchdog, ajan köprüsü |
| 6 | `ustat-test-engineer` | Sonnet | `tests/` | pytest, critical_flows, statik sözleşme |

**Opus sadece 2 ajanda** (engine-guardian + auditor) — maliyet bilinçli tasarım.

#### 13.12.2 Orkestrasyon Modelleri

| Model | Akış | Kullan | Tahmini Token |
|---|---|---|---|
| **A — Denetim→Uygulama→Test** | auditor → [onay] → engine-guardian → test-engineer → ops-watchdog | C3/C4, Kırmızı Bölge, Siyah Kapı | 20-30k |
| **B — Direkt Uzman** | <uzman> → test-engineer | C1/C2, tek dosya fix | 5-10k |
| **C — Sadece Araştırma** | auditor (tek başına) | Kök neden, dead code, etki haritası | 8-15k |
| **D — Paralel Koşu** | api-backend ‖ desktop-frontend (aynı mesajda) | Full-stack bağımsız feature | %50 süre tasarrufu |
| **E — Savaş Zamanı** | ops-watchdog → [ben] → ops-watchdog | Piyasa açıkken kritik arıza | 2-5k (hız > titizlik) |

#### 13.12.3 Karar Ağacı

```
Soru geldi
├── Sadece bilgi/araştırma (kod değişmeyecek) → auditor
├── Kırmızı Bölge + Siyah Kapı             → Model A (auditor+guardian+test)
├── Sarı/Yeşil Bölge engine                 → Model B (guardian+test)
├── API endpoint                            → api-backend (+ desktop-frontend impact varsa)
├── Frontend bileşen                        → desktop-frontend (build kontrol ZORUNLU)
├── Test ekleme/çalıştırma                  → test-engineer
├── Uygulama başlat/durdur/log/DB           → ops-watchdog
├── Mimari plan gerekli                     → auditor (Model C)
├── Claude/MCP/SDK sorusu                   → claude-code-guide (built-in)
└── Basit, net, tek satır                   → Ben direkt, ajan yok
```

#### 13.12.4 Ajan Çağırmama Kuralları (Maliyet Tuzağı)

Ajan her zaman token kazandırmaz. Aşağıdaki durumlarda **ajan çağırmak israftır**:

- Tek satır edit (değişken yeniden adlandırma, yorum düzeltmesi) → `Edit` tool yeter
- Hedef dosya + fonksiyon net biliniyor + <30 satır değişim → ana session
- Tek `grep` cevaplayabiliyor ("X sabiti nerede?") → `Grep` tool yeter
- Log'da tek hata satırı çekiliyor → `ustat_agent.py tail_log` yeter
- Bilgi sorusu, değişiklik yok ("BABA kaç motorlu çalışıyor?") → cevap zaten CORE'da

**Kural:** İş <3k token yiyecekse ajana atma — yönlendirme maliyeti kazancı yer.

#### 13.12.5 Ajan Maksimum Performans Kuralları

Her ajan dosyasında zaten "Token Disiplini" bölümü var. Ana session'dan ajana **doğru brief** vermek, ajanın maksimum performansla minimum token yemesini sağlar. Brief şablonu:

```
GOAL: <tek cümle, ne bekliyorum>
SCOPE: <dokunulacak dosya/alan — sınırı ben çiziyorum>
CONTEXT: <ajanın CLAUDE.md'den çekmesine gerek kalmayacak kritik bilgi — ör: "bu C3, Kırmızı Bölge, auditor raporu şunu dedi: X">
OUTPUT: <ajan çıktı formatındaki hangi alanlar kritik>
CONSTRAINTS: <özel yasaklar — ör: "h_engine.py'ye dokunma, sadece ogul.py">
```

**Kötü brief:** *"baba.py'deki bug'ı düzelt"* → Ajan tüm baba.py'yi okur, CLAUDE.md'yi okur, ANAYASA'yı okur, impact_map çalıştırır, tahmin yürütür. **~15k token**.

**İyi brief:** *"baba.py:347 `_check_hard_drawdown` L3 tetiklemiyor (auditor raporu: threshold karşılaştırması `>=` yerine `>` olmuş). Fix: tek karakter. Test: tests/critical_flows/test_hard_drawdown.py zaten var, yeşil dönmeli. C4 Siyah Kapı — çift doğrulama yaptım, kullanıcı onayı: evet."* → Ajan 200 satır okur, 1 karakter değiştirir, pytest çalıştırır. **~2k token**.

Fark: **7.5x tasarruf**. Ajan aynı ajan, iş aynı iş — brief kalitesi belirliyor.

#### 13.12.6 Ajan ile `ustat_agent.py` Farkı

Karıştırma:

| Araç | Tipi | Ne yapar |
|---|---|---|
| `ustat_agent.py` | OS-level autonomous (Python servis) | Windows'ta process/log/DB/shell komutları (37 komut) |
| 6 Claude subagent | LLM-level delegation (`.claude/agents/*.md`) | Kod düşünme + kod yazma + test + plan |

**Çoğu Model A akışı her ikisini de kullanır:** `ustat-ops-watchdog` (Claude subagent) içinden `python .agent/claude_bridge.py restart_app` (OS ajan komutu) çağırır. İki katmanlı.

#### 13.12.7 Ajan Kullanım Metrikleri (İsteğe Bağlı İleri)

Haftalık token audit'a (§13.10) ajan dağılımı da eklenir:

```
Session: 2026-04-14_tokenmax
Ana session tokens: 12.4k
Delegasyon:
  - ustat-auditor: 1 çağrı, ~8k (Opus)
  - ustat-engine-guardian: 1 çağrı, ~5k (Opus)
  - ustat-test-engineer: 1 çağrı, ~2k (Sonnet)
Toplam: 27.4k
Ajan kullanılmasaydı tahmini: 45-55k (ana session'da)
Tasarruf: ~%40
```

---
