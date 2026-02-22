# ÜSTAT v5.0 — Proje Rehberi ve Çalışma Prensipleri

## Operasyon Modeli — HER GÖREVDE UYGULANACAK

Her görev 4 aşamada yürütülür. Atlama YASAK.

### 1. KEŞİF (Önce anla)
- Değişiklik yapmadan önce ilgili dosyaları oku
- Kök nedeni log/çıktı/kanıt ile göster
- "Bu değişiklik başka yeri bozar mı?" risk analizi yap
- Eksik bilgi varsa debug scripti yaz, kullanıcı çalıştırır, gerçek veriyle devam et

### 2. PLAN (Kod yazmadan önce planla)
- Hangi dosyalarda ne değişecek — listele
- Hangi test/komutla doğrulanacak — yaz
- Geri alma (rollback) planı — belirt
- "En küçük geri alınabilir değişiklik" prensibi

### 3. UYGULAMA (Minimal ve kontrollü)
- Yalnızca plan kapsamında değişiklik yap
- Tahmin YASAK — eksik bilgi varsa önce kanıt topla
- Değişiklikleri küçük parçalara böl, her parçayı doğrula
- Yeni bağımlılık ekleme, büyük refactor yasak (açık talimat yoksa)

### 4. DOĞRULAMA (Test yoksa bitmemiş sayılır)
- Her değişiklikten sonra test/doğrulama çalıştır
- Sonucu raporla: BAŞARILI / BAŞARISIZ + neden
- "Çalışıyor gibi" kabul edilmez, ölçülebilir kanıt gerekir

## YASAKLAR
- Tahmin üzerinde çalışma — "deneyelim, olmazsa başka yol" YASAK
- pyautogui/PostMessage ile NORMAL kullanıcı process'inden MT5'e OTP gönderme — UIPI engeli, ÇALIŞMAZ
- OTP gönderimi SADECE admin Python ile yapılabilir (PowerShell -Verb RunAs → mt5_automator.py)
- Birden fazla sorunu aynı anda çözmeye çalışma — tek tek ilerle
- Gri alan bırakma — "doğru/yanlış" netliği esas
- Kullanıcıya "3 olası neden" listesi sunma — kök nedeni bul, tek çözüm sun
- İhtimal/varsayım üzerinde çalışma — neden-sonuç ilişkisi kur

## İletişim Formatı
Her aşamada kısa ve net rapor ver:
1. Kök neden kanıtı (log/çıktı)
2. Değişiklik listesi (dosya + özet)
3. Doğrulama komutu ve sonucu
4. Rollback adımı

---

## Proje Tanımı
VİOP vadeli kontratlar için algoritmik işlem sistemi. GCM Capital / MetaTrader 5.
Üç modül: ÜSTAT (strateji yönetimi, Top 5 seçim), BABA (risk yönetimi, rejim algılama), OĞUL (sinyal üretimi, emir state-machine).
Felsefe: Önce sermayeyi koru, sonra kazan.

## Proje Yapısı
```
C:\USTAT\
├── engine/          → Python trading engine
│   ├── baba.py      → Risk yönetimi + rejim algılama (1951 satır)
│   ├── ogul.py      → Sinyal üretimi + emir state-machine (1629 satır)
│   ├── ustat.py     → Strateji yönetimi, Top 5 seçim (934 satır)
│   ├── mt5_bridge.py → MT5 bağlantı katmanı (906 satır)
│   ├── main.py      → Ana döngü, 10sn cycle (539 satır)
│   ├── database.py  → SQLite yönetimi (1027 satır)
│   ├── data_pipeline.py → Veri çekme/temizleme (606 satır)
│   ├── utils/indicators.py → Teknik indikatörler (430 satır)
│   └── models/      → Veri modelleri (trade, signal, risk, regime)
├── api/             → FastAPI sunucu (frontend-backend köprüsü)
│   ├── server.py    → Ana FastAPI app
│   └── routes/      → trades, positions, risk, status, killswitch, live
├── desktop/         → Electron + React masaüstü uygulaması
│   ├── src/components/ → LockScreen, Dashboard, TradeHistory, vb.
│   └── scripts/mt5_automator.py → MT5 OTP otomasyon (admin Python, SendMessageW ile)
├── backtest/        → Backtest framework
├── tests/           → 604 test (pytest)
└── config/          → Konfigürasyon dosyaları
```

## MT5 Bilgileri (GERÇEK — DOĞRULANMIŞ)
- MT5 exe yolu: C:\Program Files\GCM MT5 Terminal\terminal64.exe
- Sunucu: GCM-Real01
- Hesap: 7023084
- Python kütüphanesi: import MetaTrader5 as mt5
- Bağlantı kodu:
```python
mt5.initialize(path=r"C:\Program Files\GCM MT5 Terminal\terminal64.exe")
mt5.login(login=7023084, server="GCM-Real01")
info = mt5.account_info()
```

## OTP Akışı (KRİTİK — DOĞRULANMIŞ)
MT5, 2FA/OTP kullanıyor. Her girişte 6 haneli tek kullanımlık şifre gerekli.
OTP kodu MetaTrader 5 Mobile Authenticator'dan alınır (30 saniye geçerli).

GERÇEK: Python MetaTrader5 kütüphanesi OTP parametresi KABUL ETMEZ.
GERÇEK: Normal kullanıcı process'inden PostMessage/SendMessageW ile OTP gönderme UIPI engeli nedeniyle ÇALIŞMAZ.
ÇÖZÜM: Admin Python (PowerShell -Verb RunAs) ile SendMessageW ÇALIŞIR — debug_otp_admin.py ile doğrulandı.

MT5 OTP Dialog Bilgileri (debug_otp_admin.py ile doğrulanmış):
- Dialog başlığı: "&Giriş..."
- İçinde: "Tek kullanımlık şifre:" label + Edit field (id=10631)
- Butonlar: "Tamam" (id=1) ve "İptal"
- Admin Python → SendMessageW (WM_SETTEXT + BM_CLICK) ile OTP gönderilebilir

OTP GÖNDERİM MİMARİSİ:
- Electron (normal) → PowerShell -Verb RunAs → Python mt5_automator.py --otp XXX --output tempfile
- Admin Python: MT5 dialogunu bulur → OTP yazar → Tamam'a basar → sonucu JSON'a yazar
- Electron: tempfile'dan sonucu okur → UI'a döner
- Dosya zinciri: LockScreen.jsx → mt5Launcher.js → preload.js → main.js → mt5Manager.js → PowerShell → mt5_automator.py

DOĞRU AKIŞ:
1. Üstat ikonu tıklanır → Electron HEMEN açılır (2-3 sn)
2. Kilit ekranı gösterilir → MT5 arka planda başlatılır
3. WAITING ekranında OTP input alanı gösterilir
4. Kullanıcı OTP kodunu ÜSTAT'a girer → admin Python ile MT5 dialoguna iletilir
   (Alternatif: Kullanıcı OTP'yi doğrudan MT5 dialoguna da girebilir)
5. Arka planda mt5.initialize() polling başlar (3 sn aralık, max 120 sn)
6. mt5.initialize() + mt5.account_info() başarılı → Dashboard'a geç

## Bilinen AÇIK Sorunlar
1. ~~OTP gönderimi çalışmıyor~~ → ÇÖZÜLDÜ: Admin Python + SendMessageW ile OTP gönderimi eklendi
2. ~~Uygulama yavaş açılıyor~~ → ÇÖZÜLDÜ: Splash screen + Vite IPv6 fix + pollForVite düzeltmesi
3. ~~MT5 kontrolsüz tekrar açılıyor~~ → ÇÖZÜLDÜ:
   - connect(launch=False) ile heartbeat MT5 açmaz
   - Electron kapanınca API+Engine de durur (api.pid + killApiProcess)
   - Böylece ÜSTAT kapalıyken MT5'e hiçbir sinyal gitmez

## Komutlar
- pip install -r requirements.txt
- cd desktop && npm install
- cd desktop && npm run dev
- uvicorn api.server:app --port 8000
- pytest tests/
- python C:\USTAT\debug_mt5.py

## Kodlama Kuralları
- Type hints ve docstring ZORUNLU
- Try/except + logging ile hata yönetimi
- Değişken/fonksiyon isimleri İngilizce, UI metinleri Türkçe
- BABA HER ZAMAN ÖNCE ÇALIŞIR — sıralama değiştirilemez
- VOLATILE rejimde MARKET EMRİ YASAK

## 15 VİOP Kontratı
F_THYAO, F_AKBNK, F_ASELS, F_TCELL, F_HALKB (A sınıfı)
F_PGSUS, F_GUBRF, F_EKGYO, F_SOKM, F_TKFEN, F_OYAKC, F_BRSAN, F_AKSEN (B sınıfı)
F_ASTOR, F_KONTR (C sınıfı)

## Context Yönetimi
- /clear: Her yeni konuya geçerken kullan
- /compact: Uzun session'larda kritik kararları koru
- Session başına tek sorun odağı
