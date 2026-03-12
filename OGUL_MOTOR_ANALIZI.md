# OĞUL Motor Analizi — Ferrari mi, Renault mu?

**Tarih:** 13 Mart 2026
**Dosya:** engine/ogul.py (~4000+ satır, v12.0+)
**Analiz:** Motor kapasitesi, sinyal stratejileri, pozisyon yönetimi, risk kuralları

---

## KISA CEVAP

**Ne Ferrari F163-CF, ne de Renault motoru. OĞUL bir "Porsche 911 GT3 motoru" — yani ciddi bir mühendislik var ama bazı parçaları hâlâ test bankasında vidalanmamış.** Motor kapasitesi yüksek, mimari doğru, ama bazı kritik ayarlar canlı piyasada optimize edilmeli. Şu anki haliyle güvenilir bir şekilde çalışabilir.

---

## 1. SİNYAL STRATEJİLERİ — "Motor Silindirleri"

### 1.1 TREND FOLLOW (Ana Silindir)

**Koşullar:** EMA(20) > EMA(50) + ADX > 22-28 (hysteresis) + MACD histogram 2 bar pozitif
**H1 Onay:** M15 sinyali, H1 EMA crossover ile doğrulanıyor
**SL:** Swing low/high tabanlı (yoksa 1.5×ATR fallback)
**TP:** 2×ATR

**Değerlendirme: 8/10**

Güçlü yönler:
- ADX hysteresis (22-28 geçiş bölgesi) klasik ADX > 25 eşiğinden çok daha sofistike. Rejim geçişlerinde erken/geç giriş sorununu çözüyor.
- MACD histogram 2-bar onayı, whipsaw'ları etkili filtreler. Tek bar yerine 2 bar beklemek, yanlış sinyal oranını önemli ölçüde düşürür.
- H1 çoklu zaman dilimi onayı, VİOP gibi orta-düşük likit piyasalarda kritik bir filtre. M15 noise'u H1 ile doğrulama, profesyonel bir yaklaşım.
- Swing low/high tabanlı SL, sabit ATR çarpanı yerine piyasa yapısına dayalı stop kullanıyor.

Zayıf yönler:
- EMA(20/50) crossover parametreleri VİOP'un seans yapısına (8 saatlik gün, 09:45-17:45) özel optimize edilmemiş — genel parametre kullanılıyor.
- TP'nin 2×ATR ile sabit olması, güçlü trendlerde kazancı erken keser. Trailing stop bunu kısmen telafi ediyor ama TP1'den sonraki yarı pozisyon için daha agresif bir hedef olabilirdi.

---

### 1.2 MEAN REVERSION (İkinci Silindir)

**Koşullar:** RSI(14) < 20 (veya > 80) + BB alt/üst bant teması + ADX < 22-28 (hysteresis) + Williams %R çift onay
**SL:** BB bant ± 1×ATR
**TP:** BB orta bant

**Değerlendirme: 7/10**

Güçlü yönler:
- 4 katmanlı onay sistemi (RSI + BB + ADX + Williams %R) yanlış sinyal oranını çok düşürür.
- RSI eşikleri (20/80) agresif değil — %30/%70 yerine %20/%80 kullanarak çok aşırı bölgelere düşmüş fiyatları hedefliyor.
- Williams %R çift onay (C3 iyileştirmesi), mean reversion sinyallerinin güvenilirliğini artırıyor.

Zayıf yönler:
- **TP hedefi çok muhafazakâr.** BB orta bant (SMA 20), genellikle çok yakın bir hedef. Fiyat oversold bölgeden döndüğünde BB orta banda kadar hareketin büyük kısmı zaten spread + komisyonla erir. Risk:Ödül oranı düşük kalabilir.
- **MR_SL_ATR_MULT = 1.0** VİOP'ta düşük likidite anlarında yetersiz kalabilir. Spread genişlediğinde 1×ATR SL çok dar olabilir, özellikle C sınıfı kontratlarda.
- VİOP'ta mean reversion sinyalleri seyrek gelir (RSI < 20 nadir), yani motor çoğu zaman bu silindirle çalışamaz.

---

### 1.3 BREAKOUT (Üçüncü Silindir)

**Koşullar:** 20-bar high/low kırılımı + hacim > ort×1.5-3× (likidite bazlı) + ATR genişleme (1.2-1.5× likidite bazlı)
**SL:** 1.5×ATR
**TP:** %100 range genişliği
**Bonus:** BB-KC Squeeze çıkışı (+0.15 strength)

**Değerlendirme: 8/10**

Güçlü yönler:
- **Likidite sınıfı bazlı parametreler** çok akıllı bir tasarım. A sınıfı (F_THYAO, F_AKBNK) için 1.5× hacim yeterli, C sınıfı (F_KONTR) için 3× gerekiyor. Bu, farklı likidite seviyelerindeki kontratlar arasında adil filtreleme sağlıyor.
- ATR genişleme kontrolü, sahte kırılımları filtreler.
- BB-KC Squeeze bonusu, teknik analiz dünyasında bilinen bir edge. Sıkışma sonrası kırılımlar daha güvenilir olur.
- False breakout tespiti (3 bar geri dönüş → kapat) sağlam bir savunma mekanizması.

Zayıf yönler:
- **Breakout sadece RANGE rejimde aktif** (REGIME_STRATEGIES mapping). Oysa gerçekte breakout sinyalleri genellikle RANGE→TREND geçişlerinde oluşur. Breakout tetiklendiğinde rejim henüz RANGE olsa da, emir gönderildikten sonra rejim TREND'e dönecektir — bu gecikme kaçırılan fırsatlara yol açabilir.
- TP = %100 range genişliği, dar range'lerde çok küçük, geniş range'lerde çok büyük hedef verir. Dinamik bir TP daha uygun olurdu.

---

### 1.4 Rejim-Strateji Mapping — KRİTİK KISITLAMA

```
TREND    → [TREND_FOLLOW]          ← Tek silindir çalışıyor
RANGE    → [MEAN_REVERSION, BREAKOUT] ← İki silindir
VOLATILE → []                       ← Motor durdu!
OLAY     → []                       ← Motor durdu!
```

**Bu mapping'in en büyük sorunu:** VOLATILE ve OLAY rejimlerinde motor tamamen duruyor. Yani BABA'nın tespitine göre piyasa volatil veya olay modundaysa, OĞUL hiçbir sinyal üretmiyor. Bu doğru bir risk yönetimi kararı ama şu anlamı var:

**VİOP gibi haber odaklı piyasalarda, volatil günlerin büyük kısmında motor susacak.** Eğer BABA'nın VOLATILE/OLAY tespiti çok hassassa (düşük eşik), motor gün boyu çalışmayabilir. Bu, canlı performansı doğrudan etkiler.

---

## 2. STATE MACHINE — "Şanzıman"

**Durum akışı:** SIGNAL → PENDING → SENT (LIMIT) → FILLED / PARTIAL / TIMEOUT → MARKET_RETRY → CLOSED

**Değerlendirme: 9/10**

Bu, motorun en güçlü parçası. Ciddi bir mühendislik var:

- **LIMIT emir + ATR ofsetli giriş** (0.25×ATR geri) — market emri yerine limit emir, spread kaybını azaltır. VİOP gibi geniş spread'li piyasalarda bu kritik.
- **Kısmi dolum yönetimi** — %50+ dolum kabul, altı iptal. VİOP'ta kısmi dolumlar sık görülür, bu mantık sağlam.
- **Timeout → Market retry** — limit emir dolmazsa, TREND/RANGE rejimlerinde 1 kez market emir deniyor. VOLATILE/OLAY'da market retry yasak. Akıllı risk ayrımı.
- **Slippage kontrolü** — market retry sonrası 0.5×ATR üzeri slippage varsa pozisyon anında kapatılıyor.
- **Netting mod senkronizasyonu** — VİOP netting modda çalışır, sembol bazlı ticket eşleştirme doğru yapılmış.

Tek zayıflık: ORDER_TIMEOUT_SEC = 5 saniye çok kısa olabilir. VİOP'ta özellikle C sınıfı kontratlarda limit emir 5 saniyede dolmayabilir.

---

## 3. POZİSYON YÖNETİMİ — "Süspansiyon Sistemi"

**Evrensel yönetim sistemi:** Breakeven → TP1 (yarı kapanış) → Trailing Stop (EMA20) → Geri çekilme toleransı → Maliyetlendirme

**Değerlendirme: 9/10**

Bu kısım gerçekten iyi tasarlanmış:

### 3.1 Breakeven (Likidite Bazlı)
- A sınıfı: 1.0×ATR kâr → SL'yi entry'e çek
- B sınıfı: 1.3×ATR
- C sınıfı: 1.5×ATR

Düşük likidite kontratlarında daha geniş eşik, spread kayıplarını hesaba katıyor. Doğru.

### 3.2 TP1 (Yarı Kapanış)
- Kâr ≥ 1.5×ATR → pozisyonun yarısını kapat, kalan yarıya trailing + oylama yönetimi
- TP kaldırılıyor (kalan yarı serbest koşuyor)

Bu, kâr kilitleme + trend sürüşü dengesini sağlayan klasik bir yöntem. İyi uygulama.

### 3.3 Trailing Stop (EMA20 Bazlı)
- BUY: SL = EMA(20) − trail_mult × ATR
- SELL: SL = EMA(20) + trail_mult × ATR
- Öğle arası (12:30-14:00): trailing %30 genişletme

EMA tabanlı trailing, sabit ATR trailing'den üstün — trend yapısını takip eder. Öğle arası genişletme, VİOP'un düşük likidite saatlerinde erken çıkışı önlüyor. Profesyonel dokunuş.

### 3.4 Geri Çekilme Toleransı (Dinamik)
- Düşük volatilite (ATR/fiyat < %0.5): peak kârın %20'si
- Normal: %30
- Yüksek volatilite (> %1.2): %40

Volatiliteye göre dinamik tolerans, sabit eşikten çok daha akıllı.

### 3.5 Oylama Bazlı Çıkış
- 4 gösterge (RSI, EMA crossover, ATR genişleme, hacim): her biri 1 oy
- 3/4+ ters oy VEYA ≤1/4 lehte oy → pozisyonu kapat

Bu, tek bir göstergeye bağımlılığı ortadan kaldıran demokratik bir çıkış sistemi. Güçlü.

### 3.6 Maliyetlendirme (Cost Averaging)
- 5 koşul hepsi sağlanmalı: ilk kez + 3/4 aynı yönde oylama + 1×ATR geri çekilme + hacim düşmüyor + risk ≤ %120
- Çok muhafazakâr şartlar, bu iyi — riskli ekleme yapılmıyor.

---

## 4. RİSK KURALLARI — "Fren Sistemi"

**Değerlendirme: 8/10**

### 4.1 Günlük Zarar Limiti
- Equity'nin %3'ü → tüm pozisyonları kapat, gün sonuna kadar sinyal üretme

### 4.2 Sembol Bazlı Ardışık Zarar
- Aynı sembolde 2 ardışık zarar → o gün o sembol devre dışı

### 4.3 Spread Anormalliği
- Spread ≥ ortalama × 2 → kârdaysa kapat (zarar/nötrdeyse bekle)

### 4.4 Hacim Patlaması
- Hacim ≥ ortalama × 3 + pozisyon 0.3×ATR aleyhine → anında kapat

### 4.5 Bias-Lot Entegrasyonu
- Oylama ters yönde → lot = 0 (sinyal iptal)
- Oylama nötr → lot × 0.85 (güven düşürme)

### 4.6 Gün Sonu Kapatma
- 17:45 sonrası tüm FILLED pozisyonları ve bekleyen emirleri kapat
- Hibrit pozisyonları da kapat

### 4.7 Seans Zamanlama Filtresi
- Açılış volatilitesi (09:45-10:15) ve kapanış (17:15-17:45): sinyal gücü × 0.5

Fren sistemi sağlam. BABA korelasyon kontrolü, margin kontrolü, concurrent limit (max 5) ve kill-switch ile birleşince çok katmanlı bir güvenlik ağı oluşuyor.

---

## 5. TOP 5 KONTRAT SEÇİMİ — "Navigasyon Sistemi"

**Değerlendirme: 7/10**

5 kriterin ağırlıklı toplamı: Teknik (%35) + Hacim (%20) + Spread (%15) + Tarihsel (%20) + Volatilite (%10)

Güçlü yönler:
- Winsorize + min-max normalizasyon, outlier dirençli
- 30 dakikada bir güncelleme, hem adaptif hem kararlı
- Vade geçiş filtresi (son 3 iş günü yeni işlem yok)
- KAP/haber deaktif sistemi
- Bilanço takvimi entegrasyonu
- Minimum 3 kontrat garantisi

Zayıf yönler:
- **Tarihsel başarı skoru minimum 10 işlem istiyor** (FAZ 2.7). Yeni bir kontrat veya yeni başlayan sistem bu eşiğe ulaşana kadar 30 puan (düşük) alıyor. Bu, cold-start problemi yaratır.
- 15 kontrat havuzu arasından 5 seçmek, VİOP'un dar evreninde mantıklı ama havuz genişlemesi zor.

---

## 6. LOT HESAPLAMA — "Yakıt Enjeksiyon"

**Değerlendirme: 7/10**

- BABA'nın `calculate_position_size()` fonksiyonu kullanılıyor (ATR bazlı risk hesabı)
- Bias-lot entegrasyonu (ters oy → 0, nötr → ×0.85)
- ÜSTAT lot_scale (rejime göre ölçekleme)
- Evrensel yönetimde ENTRY_LOT_FRACTION = 0.5 (yarım lot giriş, maliyetlendirme için alan bırak)
- MAX_LOT_PER_CONTRACT = 1.0 (test süreci limiti)

Sorun: **MAX_LOT = 1.0 çok düşük.** Bu test süreci parametresi olarak belirtilmiş ama üretimde de bu değer kaldığında, büyük hesaplarda potansiyelin çok altında kalınır. Ayrıca yarım lot giriş + max 1 lot = max 2 işlemde pozisyon dolmuş olur. Maliyetlendirme kapasitesi çok sınırlı.

---

## 7. RESTORE & SENKRONİZASYON — "Yeniden Çalıştırma Sistemi"

**Değerlendirme: 9/10**

- Engine restart'ta MT5 pozisyonlarını DB ile eşleyerek active_trades'i yeniden oluşturuyor
- Manuel/Hibrit pozisyonlar ayrı tutuluyor (netting çakışma koruması)
- DB'deki strateji, rejim, TP1, breakeven, peak_profit bilgilerini geri yüklüyor
- Yetim pozisyon (DB'de eşleşmesi olmayan) tespit + uyarı sistemi
- Netting farklarını (lot/entry_price) otomatik senkronize ediyor

Bu, üretim ortamında kritik bir parça ve doğru uygulanmış.

---

## GENEL SONUÇ TABLOSU

| Bileşen | Puan | Yorum |
|---------|------|-------|
| Trend Follow stratejisi | 8/10 | Sağlam, H1 onay güçlü |
| Mean Reversion stratejisi | 7/10 | TP hedefi muhafazakâr, sinyal seyrek |
| Breakout stratejisi | 8/10 | Likidite bazlı parametreler mükemmel |
| State Machine | 9/10 | Profesyonel, LIMIT+retry+slippage |
| Pozisyon Yönetimi | 9/10 | Evrensel yönetim, çok katmanlı |
| Risk Kuralları | 8/10 | Çok katmanlı güvenlik ağı |
| Top 5 Seçimi | 7/10 | Cold-start problemi var |
| Lot Hesaplama | 7/10 | Test limitleri üretim için düşük |
| Restore/Sync | 9/10 | Netting-aware, sağlam |
| **GENEL ORTALAMA** | **8.0/10** | |

---

## TEŞHİS: Bu Motor Ferrari'yi Yürütür mü?

### Evet, Yürütür — Ama Bazı Vidalara Sıkma Lazım

**Motor kapasitesi: Porsche 911 GT3** seviyesinde. Mühendisliği sağlam, mimarisi profesyonel, risk yönetimi çok katmanlı. Ama birkaç kritik ayar yapılmazsa performans beklentilerin altında kalır:

### KRİTİK AYARLAR (Hemen Yapılmalı)

1. **VOLATILE/OLAY rejimlerinde tamamen susma** — Eğer BABA'nın volatilite eşikleri düşükse, motor gün boyu çalışmayabilir. BABA'nın rejim tespiti ile OĞUL'un aktivitesi arasındaki dengeyi canlıda izlemek şart.

2. **MAX_LOT_PER_CONTRACT = 1.0** — Test limiti olarak düşük kalsın, ama ileride bu parametreyi hesap büyüklüğüne oranla artırmak gerekecek.

3. **ORDER_TIMEOUT_SEC = 5** — VİOP C sınıfı kontratlar için 10-15 saniye daha uygun olabilir.

### ÖNEMLİ GÖZLEMLER

4. **Mean Reversion TP = BB orta bant** düşük Risk:Ödül oranı yaratıyor. BB orta bandın ötesine bir miktar (örneğin BB_mid + 0.3×ATR) TP vermek, risk:ödül dengesini iyileştirir.

5. **Breakout'un sadece RANGE rejimde aktif olması** sezgisel olarak doğru ama pratikte kırılımlar range→trend geçişinde oluşur. Bu mapping gözden geçirilmeli.

6. **Minimum 10 işlem tarihsel eşiği** cold-start döneminde hemen hemen tüm kontratlar 30 puan (düşük) alacak. İlk ay sistem "kör" çalışacak.

### GÜÇLÜ YÖNLER (Olduğu Gibi Kalsın)

- 4 göstergeli oylama sistemi (pozisyon yönetimi + lot filtresi)
- Likidite sınıfı bazlı tüm parametreler (breakeven, trailing, breakout filtreleri)
- H1 çoklu zaman dilimi onayı
- ADX hysteresis (22-28 geçiş bölgesi)
- Öğle arası trailing genişletme
- Seans açılış/kapanış volatilite filtresi
- ÜSTAT entegrasyonu (dinamik parametreler + kontrat profilleri)
- BB-KC Squeeze bonusu (breakout güvenilirlik artışı)
- Evrensel pozisyon yönetimi (tüm stratejiler için tek, tutarlı sistem)

---

## SONUÇ

**OĞUL motoru Ferrari'yi yürütecek kapasitede.** Kod 4000+ satır, ama bunun büyük çoğunluğu gerçek iş mantığı — boilerplate değil. Her strateji birden fazla onay katmanıyla korunuyor, pozisyon yönetimi 8 adımlı evrensel bir sistem, risk kuralları çok katmanlı, state machine profesyonel seviyede.

**Ancak Ferrari'nin gaz pedalına basabilmek için BABA'nın rejim tespitinin ne kadar muhafazakâr olduğunu izlemek kritik.** Eğer BABA çok sık VOLATILE/OLAY sinyali veriyorsa, motor kapasitesi ne kadar yüksek olursa olsun, araç hareket etmez.

**Motor notu: 8.0/10 — Üretim ortamı için hazır, ama ilk aylar yakın izleme + parametre fine-tuning gerektirir.**
