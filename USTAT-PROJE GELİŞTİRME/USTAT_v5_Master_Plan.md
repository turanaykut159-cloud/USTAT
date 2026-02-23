# ÜSTAT v5.0 — Proje Master Planı

**Claude Code'a Verilecek Proje Tanımı ve Uygulama Planı**

Tarih: 21 Şubat 2026
Referans Doküman: BABA-OĞUL-ÜSTAT v12.0 Spesifikasyonu

---

## PROJE ÖZETİ

ÜSTAT v5.0, VİOP vadeli kontratlar için algoritmik işlem sistemidir. İki ana katmandan oluşur:

- **Trading Engine (Backend):** Python — ÜSTAT, BABA, OĞUL modülleri. Sinyal üretimi, risk yönetimi, emir yönetimi, veri pipeline. Kaynak: v12.0 spesifikasyonu.
- **Desktop Uygulaması (Frontend):** Electron + React — MT5 başlatma, OTP, kilit ekranı, dashboard, işlem geçmişi. Kaynak: Bu konuşmada toplanan istekler.

Her iki katman `C:\USTAT\` klasöründe yaşar ve birlikte çalışır.

---

## FAZLAR VE SIRALAMA

### Genel Bakış

| Faz | İçerik | Tahmini Süre | Bağımlılık |
|-----|--------|-------------|------------|
| 0 | Proje İskeleti + CLAUDE.md | 1 session | Yok |
| 1 | MT5 Köprüsü + Veri Pipeline | 3-5 session | Faz 0 |
| 2 | Trading Engine Core (BABA + OĞUL + ÜSTAT) | 8-12 session | Faz 1 |
| 3 | Desktop Uygulaması (Electron Shell) | 3-5 session | Faz 1 |
| 4 | Dashboard + İşlem Geçmişi Ekranları | 5-8 session | Faz 2 + 3 |
| 5 | Entegrasyon + Test | 3-5 session | Faz 4 |
| 6 | Backtest Framework | 3-5 session | Faz 2 |

**Not:** Faz 2 ve Faz 3 paralel yürütülebilir — engine ve frontend aynı anda geliştirilebilir çünkü Faz 4'te birleşecekler.

---

## FAZ 0: PROJE İSKELETİ

**Amaç:** Klasör yapısını oluştur, CLAUDE.md yaz, temel config dosyalarını hazırla.

**Claude Code'a verilecek prompt:**

```
C:\USTAT\ klasöründe aşağıdaki proje yapısını oluştur:

C:\USTAT\
├── CLAUDE.md
├── README.md
├── requirements.txt
├── package.json
├── .gitignore
│
├── engine/                    # Trading Engine (Python)
│   ├── __init__.py
│   ├── main.py               # Ana döngü (10 saniye cycle)
│   ├── ustat.py              # Strateji yönetimi, Top 5 seçim
│   ├── baba.py               # Risk yönetimi, rejim algılama
│   ├── ogul.py               # Sinyal üretimi, emir state-machine
│   ├── mt5_bridge.py         # MetaTrader 5 bağlantı katmanı
│   ├── data_pipeline.py      # Veri çekme, temizleme, depolama
│   ├── database.py           # SQLite yönetimi
│   ├── config.py             # Konfigürasyon yönetimi
│   ├── logger.py             # Loglama
│   ├── models/               # Veri modelleri
│   │   ├── __init__.py
│   │   ├── trade.py
│   │   ├── signal.py
│   │   ├── risk.py
│   │   └── regime.py
│   └── utils/                # Yardımcı fonksiyonlar
│       ├── __init__.py
│       ├── indicators.py     # Teknik indikatörler (EMA, RSI, MACD, ADX, BB, ATR)
│       ├── time_utils.py     # VİOP seans saatleri, tatil günleri
│       └── constants.py      # Sabitler, kontrat listesi, sektör tanımları
│
├── desktop/                   # Electron + React Desktop Uygulaması
│   ├── main.js               # Electron ana process
│   ├── preload.js            # Electron preload
│   ├── package.json
│   ├── public/
│   │   └── icon.ico          # Üstat masaüstü ikonu
│   └── src/
│       ├── App.jsx
│       ├── index.jsx
│       ├── components/       # React bileşenleri
│       │   ├── LockScreen.jsx       # Kilit/OTP ekranı
│       │   ├── Dashboard.jsx        # Ana dashboard
│       │   ├── TradeHistory.jsx     # İşlem geçmişi
│       │   ├── OpenPositions.jsx    # Açık pozisyonlar
│       │   ├── Performance.jsx      # Performans analizi
│       │   ├── Settings.jsx         # Ayarlar
│       │   ├── TopBar.jsx           # Üst bilgi çubuğu
│       │   └── SideNav.jsx          # Sol menü
│       ├── services/
│       │   ├── api.js               # Backend API çağrıları
│       │   ├── mt5Launcher.js       # MT5 başlatma + OTP automation
│       │   └── storage.js           # Yerel depolama (hesap bilgileri)
│       └── styles/
│           └── theme.css            # Koyu tema
│
├── api/                       # FastAPI — Frontend-Backend köprüsü
│   ├── __init__.py
│   ├── server.py             # FastAPI sunucu
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── trades.py         # İşlem geçmişi endpoint'leri
│   │   ├── positions.py      # Açık pozisyonlar
│   │   ├── risk.py           # Risk verileri
│   │   ├── status.py         # Sistem durumu
│   │   └── mt5.py            # MT5 bağlantı durumu
│   └── schemas.py            # Pydantic modelleri
│
├── database/
│   └── trades.db             # SQLite veritabanı (runtime'da oluşur)
│
├── config/
│   ├── default.json          # Varsayılan konfigürasyon
│   └── credentials.enc       # Şifreli hesap bilgileri
│
├── logs/
│   └── .gitkeep
│
├── backtest/
│   ├── __init__.py
│   ├── runner.py             # Backtest motoru
│   ├── spread_model.py       # Stochastic spread modeli
│   ├── slippage_model.py     # Slippage modeli
│   └── report.py             # Backtest rapor üretici
│
└── tests/
    ├── test_mt5_bridge.py
    ├── test_baba.py
    ├── test_ogul.py
    ├── test_ustat.py
    └── test_data_pipeline.py

Tüm __init__.py dosyalarını boş oluştur.
Tüm .py dosyalarına temel docstring ve import'ları ekle.
requirements.txt'e gerekli paketleri yaz.
.gitignore'a Python, Node, SQLite, .env dosyalarını ekle.
```

**Faz 0 tamamlanma kriteri:** Klasör yapısı var, dosyalar oluşturuldu, `pip install -r requirements.txt` hatasız çalışıyor.

---

## FAZ 1: MT5 KÖPRÜsÜ + VERİ PIPELINE

**Amaç:** MT5'e bağlan, veri çek, veritabanına kaydet. Sistemin temeli.

### Session 1.1 — MT5 Bridge
```
engine/mt5_bridge.py dosyasını yaz.

MetaTrader5 Python kütüphanesi (pip install MetaTrader5) kullanacak.
Fonksiyonlar:
- connect(): MT5'e bağlan, başarılı/başarısız döndür
- disconnect(): Bağlantıyı kapat
- get_account_info(): Bakiye, equity, margin bilgileri
- get_symbol_info(symbol): Fiyat adımı, çarpan, tick değeri — mt5.symbol_info() ile
- get_bars(symbol, timeframe, count): OHLCV bar verisi
- get_tick(symbol): Anlık bid/ask/spread
- send_order(symbol, direction, lot, price, sl, tp, order_type): Emir gönder
- close_position(ticket): Pozisyon kapat
- get_positions(): Açık pozisyonlar
- get_history(date_from, date_to): İşlem geçmişi
- heartbeat(): Bağlantı kontrolü (10 saniyede bir)

15 kontrat listesi:
F_THYAO, F_AKBNK, F_ASELS, F_TCELL, F_HALKB, F_PGSUS, F_GUBRF, F_EKGYO,
F_SOKM, F_TKFEN, F_OYAKC, F_BRSAN, F_AKSEN, F_ASTOR, F_KONTR

Tüm fonksiyonlara:
- Type hints
- Docstring
- Try/except + loglama
- Reconnect mekanizması (5 deneme, artan bekleme)
```

### Session 1.2 — Database
```
engine/database.py dosyasını yaz.

SQLite veritabanı yöneticisi. Tablolar:
- bars: timestamp, symbol, open, high, low, close, volume, timeframe
- trades: id, strategy, symbol, direction, entry_time, exit_time, entry_price,
  exit_price, lot, pnl, slippage, commission, swap, regime, fake_score, exit_reason
- strategies: id, name, signal_type, parameters (JSON), status, metrics (JSON)
- risk_snapshots: timestamp, equity, floating_pnl, daily_pnl, positions_json,
  regime, drawdown, margin_usage
- events: timestamp, type, severity, message, action
- top5_history: date, time, rank, symbol, score, regime
- config_history: timestamp, param, old_value, new_value, changed_by
- manual_interventions: timestamp, action, reason, user
- liquidity_classes: date, symbol, avg_volume, avg_spread, class

Thread-safe olmalı (sqlite3 check_same_thread=False + Lock).
Her tablo için CRUD fonksiyonları.
Otomatik tablo oluşturma (ilk çalıştırmada).
```

### Session 1.3 — Data Pipeline
```
engine/data_pipeline.py dosyasını yaz.

Veri çekme ve temizleme pipeline'ı:
- fetch_bars(symbol, timeframe): MT5'ten bar verisi çek, DB'ye kaydet
- fetch_all_symbols(): 15 kontratın tümü için veri çek
- clean_data(bars): Gap temizleme, outlier filtreleme (z-score > 5 reddet),
  eksik veri kontrolü (3+ ardışık eksik = kontrat deaktif)
- fetch_tick_data(symbol): Anlık tick/spread verisi
- update_risk_snapshot(): Equity, floating PnL, pozisyonlar snapshot

Frekanslar:
- OHLCV: M1, M5, M15, H1
- Tick/spread: Her 10 saniye
- Risk snapshot: Her 10 saniye
```

### Session 1.4 — Teknik İndikatörler
```
engine/utils/indicators.py dosyasını yaz.

Saf Python + numpy ile (TA-Lib bağımlılığı olmadan):
- ema(data, period): Exponential Moving Average
- sma(data, period): Simple Moving Average
- rsi(data, period=14): Relative Strength Index
- macd(data, fast=12, slow=26, signal=9): MACD + histogram
- adx(high, low, close, period=14): Average Directional Index
- bollinger_bands(data, period=20, std=2): Upper, middle, lower
- atr(high, low, close, period=14): Average True Range

Tüm fonksiyonlar numpy array kabul edip döndürsün.
Her fonksiyona unit test yaz (bilinen değerlerle karşılaştırma).
```

**Faz 1 tamamlanma kriteri:** MT5'e bağlanıp 15 kontratın verisini çekebiliyor, veritabanına kaydediyor, indikatörleri hesaplayabiliyor.

---

## FAZ 2: TRADING ENGINE CORE

**Amaç:** BABA, OĞUL, ÜSTAT modüllerini v12.0 spesifikasyonuna göre yaz.

### Session 2.1 — BABA: Rejim Algılama
```
engine/baba.py dosyasına rejim algılama fonksiyonlarını yaz.

v12.0 spesifikasyonuna göre 4 rejim:
- TREND: ADX > 25 + EMA mesafesi artıyor + son 5 barın 4'ü aynı yön
- RANGE: ADX < 20 + BB genişliği < ort.×0.8 + dar range
- VOLATILE: ATR > ort.×2.0 VEYA spread > normal×3 VEYA %2+ hareket
- OLAY: TCMB/FED günü VEYA kur hareketi > %2 VEYA vade son 2 gün

Risk multiplier: TREND=1.0, RANGE=0.7, VOLATILE=0.25, OLAY=0

Erken uyarı tetikleyicileri (likidite sınıfına göre farklı eşik):
- Spread patlaması: A:3x, B:4x, C:5x (10s içinde)
- Ani fiyat hareketi: A:1.5%, B:2%, C:3% (son 1 bar)
- Hacim patlaması: 5dk hacim > ort.×5 (tüm sınıflar)
- USD/TRY şoku: 5dk'da %0.5+ hareket (tüm sınıflar)
```

### Session 2.2 — BABA: Risk Yönetimi
```
engine/baba.py dosyasına risk yönetimi fonksiyonlarını ekle.

Risk limitleri:
- Günlük zarar: %2 equity → tüm işlemler dur → ertesi gün 09:30 sıfırla
- Haftalık zarar: %4 equity → lot %50 azalt → Pazartesi 09:30 sıfırla
- Aylık zarar: %7 equity → sistem dur → manuel onay
- Max drawdown: %10 (hard %15) → tam kapanış → manuel onay + analiz
- Üst üste kayıp: 3 işlem → 4 saat cool-down
- Floating loss: %1.5 equity → yeni işlem engeli
- Günlük max işlem: 5
- Tek işlem risk: %1 equity (max %2)

Korelasyon yönetimi:
- Max 3 pozisyon aynı yönde
- Aynı sektörde max 2 pozisyon aynı yönde
- Endeks ağırlık skoru: lot × XU030 ağırlığı, toplam < 0.25

Kill-switch 3 seviye:
- LEVEL 1: Kontrat durdur (anomali)
- LEVEL 2: Sistem pause (risk limiti aşımı, 3 kayıp, OLAY)
- LEVEL 3: Tam kapanış (manuel buton 2s basılı + onay, DD %10+, flash crash)
```

### Session 2.3 — BABA: Fake Sinyal Analizi
```
engine/baba.py dosyasına fake sinyal analizi ekle.

4 katmanlı analiz:
1. Hacim: hacim / 20-bar ort. < 0.7 → FAKE (ağırlık: 1)
2. Spread: spread / 20-bar ort. > eşik → FAKE (ağırlık: 2)
   Eşikler: A sınıfı > 2.5x, B > 3.5x, C > 5.0x
3. Multi-TF: M5, M15, H1 yön uyumu < 2/3 → FAKE (ağırlık: 1)
4. Momentum: RSI > 80 veya < 20 + MACD diverjans → FAKE (ağırlık: 2)

Karar: Fake skor ≥ 3 → POZİSYON KAPAT
Her 10 saniyede tekrar hesapla (açık pozisyonlar için).
```

### Session 2.4 — OĞUL: Sinyal Üretimi
```
engine/ogul.py dosyasına sinyal üretimi yaz.

3 sinyal tipi (v12.0 spesifikasyonundaki koşullarla):

1. TREND FOLLOW:
   - Long: EMA(20) > EMA(50) + ADX > 25 + MACD histogram 2 bar pozitif
   - Short: EMA(20) < EMA(50) + ADX > 25 + MACD histogram 2 bar negatif
   - SL: Son swing low/high - 1 ATR VEYA giriş ± 1.5×ATR
   - TP: 2×ATR veya EMA(20) ihlali
   - Trailing: 1.5×ATR
   - Timeframe: M15 giriş + H1 onay

2. MEAN REVERSION:
   - Long: RSI(14) < 30 + BB alt bant teması + ADX < 20
   - Short: RSI(14) > 70 + BB üst bant teması + ADX < 20
   - SL: BB alt/üst bantı ± 1 ATR
   - TP: BB orta bandı (20 SMA)

3. BREAKOUT:
   - Long: 20-bar high kırılımı + hacim > ort.×1.5 + ATR genişleme
   - Short: 20-bar low kırılımı + hacim > ort.×1.5 + ATR genişleme
   - SL: Range orta noktası
   - TP: Range genişliğinin %100
   - Hacim filtresi ZORUNLU

Rejime göre aktif sinyaller:
- TREND → trend follow aktif, mean reversion deaktif
- RANGE → mean reversion aktif, breakout bekle
- VOLATILE → TÜM sinyaller durur
- OLAY → SİSTEM PAUSE
```

### Session 2.5 — OĞUL: Emir State-Machine
```
engine/ogul.py dosyasına emir state-machine ekle.

State'ler: SIGNAL → PENDING → SENT → FILLED / PARTIAL / TIMEOUT / REJECTED / CANCELLED

- SIGNAL: Sinyal oluştu → BABA onay → PENDING, red → CANCELLED
- PENDING: Son risk kontrolü → SENT
- SENT: LIMIT emir gönderildi → dolu=FILLED, kısmi=PARTIAL, 5s=TIMEOUT
- PARTIAL: Kalan lot hesapla → yeni emir veya iptal
- TIMEOUT: TREND/RANGE → MARKET_RETRY, VOLATILE/OLAY → CANCELLED
- MARKET_RETRY: Market emir → dolu=FILLED, red=REJECTED (max slippage kontrol)
- FILLED: Tamamlandı → BABA izlemeye alır
- REJECTED / CANCELLED: Neden logla

VOLATILE rejimde market emri YASAK.

İşlem sınırları (test süreci):
- Günlük max: 5 işlem
- Kontrat başına: 1 lot
- Teminat ayırma: %20
- Eş zamanlı pozisyon: max 5
- İşlem saatleri: 09:45-17:45
- Gece seansı: işlem yok
- 17:45'te tüm pozisyonlar kapatılır
```

### Session 2.6 — ÜSTAT: Strateji Yönetimi
```
engine/ustat.py dosyasını yaz.

Günlük Top 5 seçim süreci (09:15'te başla, 30 dakikada güncelle):
15 kontratı 0-100 arası puanla:
- Teknik sinyal gücü: %35 (EMA, ADX, RSI, MACD, BB uyumu)
- Hacim kalitesi: %20 (güncel / 20-günlük ortalama)
- Spread durumu: %15 (mevcut / ortalama spread)
- Tarihsel başarı: %20 (son 30 gün bu kontrat + rejimde başarı)
- Volatilite uyumu: %10 (ATR(14)/fiyat, rejime uygunluk)

Normalizasyon: Min-max 0-100, winsorization (1. ve 99. percentile)
Ortalama filtresi: Sadece Top 5 ortalamasının üzerindekilerde işlem aç

Vade geçiş mekanizması:
- 3 iş günü kala: yeni vade izlemeye al, eski vadede yeni işlem yok
- 1 iş günü kala: eski vade pozisyonlarını kapat
- Yeni vade: sembol listesi güncelle, ilk 2 gün sadece gözlem

Haber/bilanço filtresi:
- TCMB/FED günü → OLAY rejimi
- Bilanço günü ±1 → o kontratta işlem yok
- KAP özel durum → o kontratta durdur
- Manuel haber işareti → gün boyu deaktif
```

### Session 2.7 — Ana Döngü
```
engine/main.py dosyasını yaz.

Her 10 saniyede çalışan ana döngü:
1. Veri güncelleme: MT5'ten 15 kontratın fiyat, hacim, spread çek
2. BABA açık pozisyon denetimi: fake analiz, risk limitleri, erken uyarı
3. BABA risk kontrolü: günlük/haftalık/aylık zarar, floating, korelasyon
4. OĞUL sinyal: risk müsaitse + günlük limit dolmadıysa + Top 5 için sinyal ara
5. OĞUL emir: sinyal + BABA onayı = emir state-machine başlat
6. Loglama: tüm kararlar SQLite'a

BABA HER ZAMAN ÖNCE ÇALIŞIR — sıralama değiştirilemez.

Fail-safe:
- Ekonomik takvim erişilemezse → OLAY rejimi
- MT5 bağlantısı koparsa → 5x reconnect, başarısız → sistem durdur
- Veri anomalisi → o kontrat deaktif
- Disk/DB hatası → arşivle, başarısız → sistem durdur
```

**Faz 2 tamamlanma kriteri:** Engine paper trade modunda çalışıyor, sinyaller üretiyor, risk kontrolleri devrede, emirler simüle ediliyor.

---

## FAZ 3: DESKTOP UYGULAMASI (ELECTRON SHELL)

**Amaç:** Electron uygulamasını kur, MT5 başlatma, OTP, kilit ekranı.

### Session 3.1 — Electron Temel Yapı
```
desktop/ klasöründe Electron + React uygulamasını kur.

- Electron ana pencere: koyu tema, tam ekran başlangıç
- Always on top ayarı (MT5'in üstünde)
- Masaüstü ikonu: Üstat logosu
- Uygulama başlığı: ÜSTAT v5.0
- Pencere boyutu: 1400x900 minimum
- React + Vite setup
- React Router ile sayfa yönlendirme
```

### Session 3.2 — MT5 Başlatma + OTP
```
desktop/src/services/mt5Launcher.js dosyasını yaz.

Uygulama başlatma akışı:
1. Üstat ikonu tıklanınca:
   - Electron uygulaması açılır (ön plan)
   - MT5 terminal64.exe arka planda başlatılır (child_process.spawn)
   - Üstat always-on-top, MT5 arkada
2. MT5 giriş bilgileri:
   - İlk girişte kullanıcıdan al: sunucu adı, hesap no, şifre
   - Şifreli olarak kaydet (electron-store + encryption)
   - Sonraki girişlerde otomatik doldur
   - Şifre ekranda ****** olarak göster
   - Farklı hesap girişinde eski kayıt silinir, yeni kaydedilir
3. OTP akışı:
   - Üstat ekranında OTP giriş alanı göster
   - Kullanıcı OTP'yi girer
   - pyautogui/pywinauto ile MT5 penceresine OTP iletilir
4. OTP doğrulanana kadar:
   - Üstat bekleme modunda, tüm bilgiler gizli
5. OTP başarılı sonra:
   - Her iki uygulama aktif
   - Dashboard açılır
```

### Session 3.3 — Kilit Ekranı (LockScreen)
```
desktop/src/components/LockScreen.jsx dosyasını yaz.

Bekleme/kilit ekranı:
- ÜSTAT v5.0 logosu (ortada, büyük)
- Bağlantı durumu göstergesi (MT5'e bağlanıyor... / Bağlandı / Hata)
- Hesap bilgileri alanı:
  - Sunucu adı: [göster]
  - Hesap No: [göster]
  - Şifre: ******
  - "Farklı hesap" butonu (mevcut kaydı silip yeni giriş)
- OTP giriş alanı (6 haneli, büyük, ortada)
- Durum mesajı: "OTP bekleniyor..." / "Doğrulanıyor..." / "Başarılı!"
- Koyu tema, profesyonel görünüm
- Tüm dashboard bilgileri gizli — OTP'ye kadar hiçbir veri görünmez
```

**Faz 3 tamamlanma kriteri:** Electron uygulaması açılıyor, MT5'i başlatıyor, OTP alıp iletiyor, kilit ekranı çalışıyor.

---

## FAZ 4: DASHBOARD + EKRANLAR

**Amaç:** Frontend ekranlarını oluştur, API ile backend'e bağla.

### Session 4.1 — FastAPI Sunucu
```
api/server.py ve routes/ dosyalarını yaz.

Endpoint'ler:
- GET /api/status — Sistem durumu (bağlantı, rejim, faz)
- GET /api/account — Bakiye, equity, floating, günlük PnL
- GET /api/positions — Açık pozisyonlar
- GET /api/trades — İşlem geçmişi (filtreli)
- GET /api/trades/stats — İstatistikler (en kârlı, en zararlı, en uzun, en kısa)
- GET /api/risk — Risk snapshot (drawdown, limitleri, rejim)
- GET /api/performance — Performans metrikleri
- GET /api/top5 — Güncel Top 5 kontrat
- POST /api/trades/approve — İşlem onaylama (kayıt altına alma)
- POST /api/killswitch — Kill-switch tetikleme
- WebSocket /ws/live — Canlı veri akışı (fiyat, equity, pozisyonlar)
```

### Session 4.2 — Üst Bar + Sol Menü
```
TopBar.jsx: Üst bilgi çubuğu
- Sol: USTAT v5.0 logosu + Faz göstergesi (FAZ 0, 1, vb.) + Bağlantı durumu (yeşil/kırmızı nokta)
- Sağ: Bakiye, Equity, Floating, Günlük Kâr/Zarar (canlı güncelleme)

SideNav.jsx: Sol dikey navigasyon menüsü
- Dashboard (ana sayfa ikonu)
- İşlem Geçmişi
- Açık Pozisyonlar
- Performans Analizi
- Risk Yönetimi
- Ayarlar
- Kill-Switch butonu (en altta, kırmızı, 2s basılı tutma)
```

### Session 4.3 — Dashboard Ana Ekran
```
Dashboard.jsx: Ana dashboard ekranı

Profesyonel trading dashboard:

Üst kartlar (4 adet):
- Toplam İşlem (bugün)
- Başarı Oranı (%)
- Net Kâr/Zarar
- Profit Factor

Orta alan:
- Sol: Equity eğrisi grafiği (zaman serisi, çizgi grafik)
- Sağ: Günlük kâr/zarar çubuk grafiği (son 30 gün)

Alt sol: Son 5 işlem listesi (kısa özet tablo)
Alt sağ: Aktif rejim göstergesi + Top 5 kontrat listesi (puanlarıyla)

Canlı güncelleme: WebSocket ile her 10 saniyede
Grafik kütüphanesi: Recharts veya Chart.js
```

### Session 4.4 — İşlem Geçmişi Ekranı
```
TradeHistory.jsx: İşlem geçmişi ekranı

Veri kaynağı: MT5'ten Python-MT5 ile otomatik çekilir

Filtre çubuğu:
- Dönem: Bugün, Son hafta, Son ay, Son 3 ay, Son 6 ay, Son yıl, Özel tarih
- Sembol: Tüm semboller / tekli seçim (dropdown)
- Yön: Tümü / Buy / Sell
- Sonuç: Tümü / Kârlı / Zararlı

Özet kartlar (üst kısım, 4 adet):
- Toplam İşlem
- Başarı Oranı (yeşil %)
- Net Kâr/Zarar
- Profit Factor

İşlem tablosu sütunları:
- Sembol, Yön, Lot, Giriş Fiyatı, Çıkış Fiyatı, Giriş Tarihi, Çıkış Tarihi,
  Süre, Swap, Komisyon, Kâr/Zarar
- Buy-in ve sell-out eşleştirilip tek satır
- Kârlı işlemler yeşil, zararlı kırmızı
- Correction kayıtları ayrı etiketli

Performans paneli (sol):
- Toplam Kâr, Toplam Zarar, Kazanan, Kaybeden, Ort. Kazanç, Ort. Kayıp,
  Toplam Swap, Toplam Komisyon

Risk paneli (sağ):
- En İyi İşlem, En Kötü İşlem, Maks. Ardışık Kayıp, Sharpe Oranı,
  Maks. Drawdown, Ort. İşlem Süresi, Toplam Lot, Ort. Lot

Özel filtreler / hızlı erişim butonları:
- En kâr eden işlem
- En zarar eden işlem
- En uzun süren işlem
- En kısa süren işlem

Alt özet satırı:
- Para yatır, Para çek, Kâr, Swap, Komisyon, Bakiye

Onay sistemi: Yeni işlemler önce gösterilir, "Onayla ve Kaydet" butonu ile
kalıcı kayıt altına alınır.

Profesyonel görünüm — v4.0'daki koyu tema tarzında ama daha modern.
```

### Session 4.5 — Açık Pozisyonlar Ekranı
```
OpenPositions.jsx: Anlık açık pozisyonlar

Tablo:
- Sembol, Yön, Lot, Giriş Fiyatı, Anlık Fiyat, Stop Loss, Take Profit,
  Floating Kâr/Zarar, Süre, Rejim
- Canlı güncelleme (WebSocket)
- Kârdaysa yeşil, zardaysa kırmızı arka plan

Özet: Toplam açık pozisyon, toplam floating, teminat kullanım oranı
```

### Session 4.6 — Performans Analizi Ekranı
```
Performance.jsx: Detaylı performans analizi

- Aylık/haftalık/günlük kâr/zarar breakdown (tablo + grafik)
- Sembol bazlı başarı oranı (bar chart)
- Saat bazlı performans (hangi saatlerde daha başarılı — heatmap)
- Long vs Short performans karşılaştırma
- Strateji bazlı performans (Trend Follow vs Mean Reversion vs Breakout)
- Equity eğrisi (detaylı, zoom yapılabilir)
- Drawdown grafiği
- Win rate trend (hareketli ortalama)
```

### Session 4.7 — Ayarlar Ekranı
```
Settings.jsx: Ayarlar

- MT5 bağlantı bilgileri (sunucu, hesap, şifre maskeli)
- "Farklı hesap ile giriş" butonu
- Risk parametreleri görüntüleme (değiştirme değil — güvenlik)
- Tema ayarı (şimdilik sadece koyu tema)
- Bildirim tercihleri
- Sistem log görüntüleme
- Versiyon bilgisi
```

**Faz 4 tamamlanma kriteri:** Tüm ekranlar çalışıyor, API'dan veri geliyor, canlı güncelleme aktif.

---

## FAZ 5: ENTEGRASYON + TEST

**Amaç:** Her şeyi birleştir, uçtan uca test et.

```
Entegrasyon testleri:
1. Uygulama başlatma akışı: ikon → MT5 → OTP → dashboard (uçtan uca)
2. Veri akışı: MT5 → engine → API → dashboard (gerçek zamanlı)
3. İşlem akışı: sinyal → BABA onay → emir → pozisyon → dashboard'da görünme
4. Risk kontrolü: zarar limiti tetikleme → sistem durdurma → dashboard'da uyarı
5. Kill-switch: 3 seviye test
6. Bağlantı kopması: MT5 disconnect → reconnect → recovery
7. İşlem geçmişi: filtreler, istatistikler, onay sistemi
8. Performans: 15 kontrat canlı veri + dashboard güncellemesi < 1 saniye
```

---

## FAZ 6: BACKTEST FRAMEWORK

**Amaç:** Backtest motorunu kur, v12.0 validasyon protokolünü uygula.

```
backtest/ klasöründeki dosyaları yaz.

- Spread modeli: tarihsel ort. + stochastic noise (σ=ort.×0.3), volatile: t-dist (df=5)
- Slippage modeli: Normal μ=1 tick σ=0.5, volatile μ=3 σ=2, market: 2x çarpan
- Seans boşlukları: gap modelleme, gap içi SL tetiklenmesi
- Walk-forward OOS: 4 ay eğitim, 2 ay test, min 3 pencere
- Monte Carlo: 1000 permütasyon, %95 güvende DD < %15
- Stress test: 2020 Mart, 2023 seçim, 2024 TCMB şokları
- Regime drift testi
- Parametre hassasiyeti: %20 değişime dayanıklılık
- Rapor üretici: HTML/PDF rapor
```

---

## CLAUDE.md İÇERİĞİ

Aşağıdaki metin, Claude Code'a proje klasörünü seçtikten sonra ilk oluşturulacak CLAUDE.md dosyasıdır:

```markdown
# ÜSTAT v5.0 — BABA-OĞUL-ÜSTAT Algoritmik İşlem Sistemi

## Proje Tanımı
VİOP vadeli kontratlar (15 hisse senedi) için algoritmik işlem sistemi.
Platform: GCM Capital / MetaTrader 5.
Üç katmanlı mimari: ÜSTAT (strateji) + BABA (risk) + OĞUL (emir).
Felsefe: Önce sermayeyi koru, sonra kazan.
İlkeler: Dürüstlük, basitlik, kademeli gelişim, sermaye koruma, ölçülebilirlik.

## Tech Stack
- Trading Engine: Python 3.11+ (FastAPI, MetaTrader5, numpy, sqlite3)
- Desktop App: Electron + React (Vite)
- Database: SQLite
- MT5 Automation: pyautogui / pywinauto (OTP iletimi)
- Grafik: Recharts veya Chart.js

## Proje Yapısı
- engine/         → Trading engine (ÜSTAT, BABA, OĞUL, MT5 bridge, data pipeline)
- desktop/        → Electron + React masaüstü uygulaması
- api/            → FastAPI sunucu (frontend-backend köprüsü)
- backtest/       → Backtest framework
- config/         → Konfigürasyon dosyaları
- database/       → SQLite DB
- logs/           → Log dosyaları
- tests/          → Test dosyaları

## Kodlama Kuralları
- Tüm fonksiyonlara type hints ve docstring ZORUNLU
- Her fonksiyonda try/except + logging ile hata yönetimi
- Thread-safety: SQLite Lock, async operasyonlar için asyncio
- Değişken/fonksiyon isimleri İngilizce, yorum ve UI metinleri Türkçe olabilir
- Her modül için unit test yazılmalı
- Fail-closed prensip: hata durumunda güvenli tarafa düş

## 15 Kontrat Listesi
F_THYAO, F_AKBNK, F_ASELS, F_TCELL, F_HALKB (A sınıfı)
F_PGSUS, F_GUBRF, F_EKGYO, F_SOKM, F_TKFEN, F_OYAKC, F_BRSAN, F_AKSEN (B sınıfı)
F_ASTOR, F_KONTR (C sınıfı)

## Kritik Kurallar
- BABA HER ZAMAN ÖNCE ÇALIŞIR — sıralama değiştirilemez
- VOLATILE rejimde MARKET EMRİ YASAK
- Test sürecinde gece pozisyon taşıma YASAK (17:45 kapanış)
- Kill-switch LEVEL 3: 2 saniye basılı tut + onay sorusu
- Ekonomik takvim erişilemezse → TÜM günler OLAY rejimi

## Referans Doküman
Detaylı spesifikasyon: BABA-OĞUL-ÜSTAT v12.0 (proje kök dizininde)
```

---

## CLAUDE CODE KULLANIM KURALLARI

1. **Her session'da tek bir faza/session'a odaklan.** "Session 1.1 — MT5 Bridge" gibi.
2. **Auto accept kapalı başla.** Her değişikliği gözden geçir.
3. **Model seçimi:** Opus 4.6 — karmaşık mimari iş. Basit düzeltmelerde Sonnet.
4. **Plan Mode:** Yeni bir faza başlamadan önce Plan Mode'da analiz yaptır.
5. **Test:** Her session sonunda "bu modül için testleri çalıştır" de.
6. **Commit:** Her anlamlı değişiklikten sonra "git commit yaz" de.
7. **Context yönetimi:** Uzun session'larda /compact kullan. CLAUDE.md bağlamı korur.
