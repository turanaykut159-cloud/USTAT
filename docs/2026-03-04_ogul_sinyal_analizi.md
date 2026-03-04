# OĞUL Sinyal Motoru — Gerçek Piyasa Analizi ve Güçlendirme Yol Haritası

**Tarih:** 2026-03-04
**Kapsam:** `engine/ogul.py` (2267 satır), `engine/utils/indicators.py` (431 satır), `config/default.json`
**Piyasa:** VİOP Pay Vadeli İşlem Sözleşmeleri (15 kontrat, M15 zaman dilimi)

---

## 1. Mevcut Sistem Özeti

### 1.1 İndikatör Seti

| İndikatör | Parametre | Kullanıldığı Yer | Kod Konumu |
|-----------|-----------|-------------------|------------|
| EMA | 20, 50 | Trend Follow giriş + çıkış | `ogul.py:52-53` |
| EMA | 9, 21 | Rejim tespiti (Baba), bias | `indicators.py:411-412` |
| ADX | 14, eşik=25 | Trend koşulu, RANGE filtresi | `ogul.py:54` |
| RSI | 14, 30/70 | Mean Reversion giriş | `ogul.py:61-63` |
| Bollinger Bands | 20, 2σ | MR giriş + SL/TP | `ogul.py:65-66` |
| MACD | 12/26/9 | Trend onay (2-bar histogram) | `ogul.py:55` |
| ATR | 14 | SL/TP, lot hesaplama, trailing | `ogul.py:79` |

### 1.2 Üç Strateji Giriş Koşulları

**Trend Follow** (`ogul.py:391-484`):
- EMA(20) > EMA(50) [BUY] veya EMA(20) < EMA(50) [SELL]
- ADX(14) > 25
- MACD histogram son 2 bar aynı işaret
- H1 EMA(20)/EMA(50) yön onayı (zorunlu)
- SL: Swing low/high(10) ± 1×ATR, fallback entry ± 1.5×ATR
- TP: 2×ATR

**Mean Reversion** (`ogul.py:488-576`):
- ADX(14) < 20
- RSI(14) < 30 + fiyat ≤ BB alt [BUY] veya RSI(14) > 70 + fiyat ≥ BB üst [SELL]
- SL: BB bant ± 1×ATR
- TP: BB orta bant

**Breakout** (`ogul.py:580-687`):
- Son kapanış > 20-bar en yüksek [BUY] veya < 20-bar en düşük [SELL]
- Hacim > ortalama × çarpan (A:1.5, B:2.0, C:3.0)
- ATR > ortalama × çarpan (A:1.2, B:1.3, C:1.5)
- SL: Entry ± 1.5×ATR
- TP: Entry ± range genişliği (high20 - low20)

### 1.3 Sinyal Güç Hesabı

Her strateji 3 bileşenli bir güç skoru üretir (max 1.0):

| Strateji | Bileşen 1 (0-0.5) | Bileşen 2 (0-0.3) | Bileşen 3 (0-0.2) |
|----------|--------------------|--------------------|---------------------|
| Trend Follow | ADX gücü | MACD büyüklüğü | EMA mesafesi |
| Mean Reversion | RSI aşırılığı | BB penetrasyonu | ADX zayıflığı |
| Breakout | Hacim patlaması | ATR genişleme | Kırılım büyüklüğü |

Birden fazla strateji sinyal üretirse en yüksek güçlü seçilir.

---

## 2. VİOP Perspektifinden Parametre Değerlendirmesi

### 2.1 EMA(20)/EMA(50) — Trend Follow

**Güvenilirlik: ORTA-DÜŞÜK (M15'te)**

M15'te EMA(20) = 5 saatlik veri, EMA(50) = 12.5 saatlik veri anlamına gelir. VİOP pay vadeli seans süresi ~8 saat 50 dakika olduğundan, EMA(50) neredeyse 1.5 seansı kapsar.

| Sorun | Açıklama | Etki |
|-------|----------|------|
| **Gecikme (lag)** | Crossover, trendin başlangıcından 1-3 saat sonra tetiklenir | İlk hareketin büyük kısmı kaçar |
| **Whipsaw** | Range piyasada sık yanlış sinyal | Win rate %35-45 aralığına düşer |
| **VİOP'a özgü** | Günde ~35 M15 bar — EMA(50) istatistiksel anlamlılık sınırında | Yeterli veri noktası zayıf |

**Mevcut Durum:** H1 onayı whipsaw'ı azaltır — bu iyi bir tasarım kararı. Ancak H1 onayı gecikmeyi daha da artırır.

**Değerlendirme:** EMA(20)/EMA(50) daily veya H4 zaman dilimlerinde güvenilir, M15'te ise **fazla yavaş**. Uygulayıcı konsensüsü M15 için EMA(9)/EMA(21) veya EMA(12)/EMA(26) önerir.

### 2.2 ADX(14) — Rejim Tespiti ve Trend Filtresi

**Güvenilirlik: ORTA (eşik=25 için)**

| Sorun | Açıklama | Etki |
|-------|----------|------|
| **Çift yumuşatma gecikmesi** | ADX = DI'ların Wilder smooth'u. Yönsel hareket zaten smooth edilmiş, ADX bunu tekrar smooth eder | Rejim değişimini 30-60 dk geç algılar |
| **Sabit eşik sorunu** | ADX > 25 bazı kontratlarda (F_KONTR, F_BRSAN) M15'te nadiren aşılır | Düşük likidite kontratlarında trend hiç tespit edilmez |
| **ADX < 20 güvenilirliği** | RANGE rejimi filtresi olarak kullanılıyor | ADX 20-25 arası "belirsiz bölge" geniş, çok sinyal kaçar |

**Değerlendirme:** ADX(14) M15'te **geç kalır**. Daha kısa periyot (7-9) veya ADX slope analizi (yükselen ADX = güçlenen trend, mutlak seviyeden bağımsız) düşünülmeli.

### 2.3 RSI(14) — Mean Reversion

**Güvenilirlik: ORTA-YÜKSEK (30/70 eşikleri için)**

| Sorun | Açıklama | Etki |
|-------|----------|------|
| **Trendde kalıcı aşırı bölge** | RSI, güçlü trendde uzun süre >70 veya <30 kalabilir | Trende karşı işlem riski |
| **M15'te 30/70 genişliği** | Uygulayıcı testleri M15'te 20/80'in daha kaliteli sinyal ürettiğini gösterir | Daha az ama daha güvenilir sinyal |
| **Gecikme** | 14-periyot Wilder smoothing M15'te 3.5 saat veri | Hızlı reversal'ları kaçırır |

**Mevcut Durum:** ADX < 20 filtresi RSI'ın trendde tetiklenmesini büyük ölçüde önler — bu **iyi bir tasarım**. BB teması ile birlikte kullanım sinyal kalitesini artırır.

**Değerlendirme:** RSI(14) + BB teması + ADX < 20 kombinasyonu sağlam. Eşiklerin 20/80'e sıkılaştırılması daha az ama daha kaliteli sinyal üretir.

### 2.4 Bollinger Bands (20, 2σ) — Mean Reversion

**Güvenilirlik: ORTA-YÜKSEK**

| Sorun | Açıklama | Etki |
|-------|----------|------|
| **"Band riding"** | Güçlü trendde fiyat sürekli banda yapışır, reversal gelmez | Yanlış giriş (ADX filtresi bunu hafifletir) |
| **Outlier duyarlılığı** | Tek büyük M15 bar std sapma hesabını çarpıtır | Bantlar ani genişler, sinyal bozulur |
| **TP olarak BB orta** | Mean reversion hedefi olarak uygun | SMA(20) = 5 saat — makul |

**Değerlendirme:** BB tek başına yeterli değil ama ADX ve RSI ile birlikte kullanım güçlü. Keltner Channel eklenmesi BB/KC squeeze stratejisi açar.

### 2.5 MACD (12/26/9) — Trend Onay

**Güvenilirlik: ORTA**

| Sorun | Açıklama | Etki |
|-------|----------|------|
| **Çift EMA gecikmesi** | MACD = EMA(12) - EMA(26), sinyal = EMA(9)(MACD) — toplam gecikme önemli | Trend onayı çok geç gelir |
| **Histogram 2-bar onayı** | 2 bar aynı işaret = 30 dk bekleme | Hızlı trendlerde giriş kaçar |

**Değerlendirme:** MACD onay filtresi olarak kabul edilebilir. Ancak ROC (Rate of Change) veya histogram slope analizi daha hızlı alternatifler.

### 2.6 Hacim Filtresi — Breakout

**Güvenilirlik: KRİTİK OLARAK DEĞİŞKEN**

| Sınıf | Hacim Güvenilirliği | Açıklama |
|-------|---------------------|----------|
| A (F_THYAO, F_AKBNK, F_ASELS) | Yüksek | Yeterli işlem hacmi, RVOL anlamlı |
| B (F_HALKB, F_GUBRF, F_EKGYO) | Orta | Gün içi hacim dengesiz, erken/geç seans farkı büyük |
| C (F_OYAKC, F_BRSAN, F_KONTR) | Düşük | Tek büyük emir ortalamayı çarpıtır, hacim filtresi güvenilmez |

**Mevcut Durum:** Likidite sınıfı bazlı çarpanlar (A:1.5, B:2.0, C:3.0) doğru yaklaşım. Ancak C sınıfı kontratlarda **hacim filtresinin hiçbir eşikte güvenilir olmadığı** kabul edilmeli.

**Değerlendirme:** C sınıfı için hacim filtresi yerine spread-bazlı filtre veya minimum işlem sayısı filtresi daha güvenilir olabilir.

### 2.7 ATR(14) — SL/TP/Trailing

**Güvenilirlik: YÜKSEK**

ATR, VİOP M15'te en güvenilir indikatör. True Range gap'leri de hesaba katar (VİOP'ta overnight gap yaygın). 14-periyot Wilder smoothing M15'te 3.5 saatlik volatilite ölçer — intraday SL/TP için makul.

**Tek uyarı:** ATR bazlı SL'ler sabit çarpan kullanır (1.5×). Piyasanın mevcut volatilitesine göre dinamik çarpan (ör: volatilite yüksekken daha geniş stop) daha iyi sonuç verebilir.

---

## 3. Alternatif ve Tamamlayıcı Yaklaşımlar

### 3.1 Momentum / Hız Göstergeleri

| Gösterge | Avantaj | Dezavantaj | VİOP Uygunluğu |
|----------|---------|------------|-----------------|
| **Williams %R(14)** | RSI'dan hızlı, smoothing yok. S&P 500'de %81 win rate raporlanmış | Daha gürültülü | YÜKSEK — M15'te RSI alternatifi olarak test edilmeli |
| **Stochastic(14,3,3)** | %K/%D crossover ek sinyal katmanı | RSI ile büyük ölçüde örtüşür | ORTA — RSI varken ek bilgi sınırlı |
| **Rate of Change (ROC)** | Sınırsız momentum ölçümü, kırılım büyüklüğü tespiti | Aşırı alım/satım eşiği yok | ORTA — breakout strength ölçümünde kullanılabilir |

**Öneri:** Williams %R, mean reversion stratejisinde RSI'ın yerine veya tamamlayıcısı olarak test edilmeli. Daha hızlı tepki süresi M15'te avantaj.

### 3.2 Volatilite Göstergeleri

| Gösterge | Avantaj | Dezavantaj | VİOP Uygunluğu |
|----------|---------|------------|-----------------|
| **Keltner Channel (EMA20 ± 1.5×ATR)** | ATR bazlı, outlier'a daha dayanıklı | BB'den daha az reaktif | YÜKSEK — BB ile birlikte squeeze stratejisi |
| **Donchian Channel (20)** | En basit breakout sistemi, VİOP'ta ~5 saat lookback | Düşük win rate (~45%), güçlü R:R ile telafi | ORTA — mevcut breakout alternatifi olarak test edilebilir |
| **Normalized ATR (ATR/Close×100)** | Farklı fiyat seviyeli kontratları karşılaştırır | Ek bir sinyal üretmez | YÜKSEK — likidite sınıfları arasında volatilite karşılaştırması |

**Öneri:** Keltner Channel eklenmesi en yüksek değer. BB/KC squeeze (BB bantları KC içine girdiğinde → düşük volatilite → yakında kırılım beklenir) hem breakout hem mean reversion stratejilerine bilgi sağlar.

### 3.3 Piyasa Yapısı / Order Flow

| Gösterge | Avantaj | Dezavantaj | VİOP Uygunluğu |
|----------|---------|------------|-----------------|
| **VWAP** | Kurumsal referans seviyesi, intraday destek/direnç | Düşük hacimli kontratlarda anlamsız | SINIRLI — sadece A sınıfı |
| **CVD (Cumulative Volume Delta)** | Agresif alıcı/satıcı ayrımı | MT5'te bid/ask atıf güvenilirliği belirsiz | DÜŞÜK — veri kalitesi doğrulanmalı |
| **OBV (On Balance Volume)** | Kümülatif yapı gürültüyü azaltır, trend onayı | Yavaş | ORTA — trend onay filtresi olarak kullanılabilir |

**Öneri:** VWAP yalnızca A sınıfı kontratlar için implementasyon değerli. CVD, VİOP'ta veri altyapısı doğrulanmadan kullanılmamalı. OBV trend onayı olarak makul.

### 3.4 Rejim Tespiti Alternatifleri

| Yöntem | Avantaj | Dezavantaj | VİOP Uygunluğu |
|--------|---------|------------|-----------------|
| **Hurst Exponent** | İstatistiksel temelli: H<0.45=MR, H>0.55=trend | Yön bilgisi vermez, hesaplama ağır | YÜKSEK — ADX yerine/yanına |
| **Choppiness Index** | Trend/range ayrımı, ADX'e benzer ama farklı formül | ADX kadar gecikmeli | ORTA |
| **Volatilite rejimi (ATR genişleme/daralma)** | Basit, hızlı | İkili sınıflandırma (yalnızca volatile/sessiz) | YÜKSEK — mevcut ATR_VOLATILE_MULT ile zaten kısmen var |

**Öneri:** Hurst Exponent, ADX'in en güçlü alternatifi. Rolling pencere (ör: 100 M15 bar) üzerinde hesaplanarak piyasanın mean-reverting mi trending mi olduğunu istatistiksel olarak belirler. NumPy ile ~10 satırda implement edilebilir.

### 3.5 Tick/Order Bazlı Yaklaşımlar

VİOP pay vadeli kontratları için tick bazlı analiz **sınırlı uygulanabilirliğe** sahiptir:
- A sınıfı kontratlar günde birkaç bin işlem görür — tick analizi mümkün ama sığ
- B/C sınıfı kontratlar çok az işlem görür — tick analizi anlamsız
- MT5 `copy_ticks_from` fonksiyonu tick verisi sağlar ama VİOP'ta bid/ask atıf güvenilirliği belirsiz
- **Sonuç:** Tick bazlı yaklaşımlar VİOP pay vadeli için uygun değil (endeks vadeli F_XU030 için düşünülebilir)

### 3.6 VİOP'a Özgü Sinyaller

| Sinyal | Açıklama | Uygunluk |
|--------|----------|----------|
| **Baz (Spot-Futures Farkı)** | Kontango/backwardation durumu, vade yaklaştıkça sıfıra yakınsar | YÜKSEK — unique bilgi, başka indikatörde yok |
| **Açık Pozisyon Değişimi (OI)** | Yükselen fiyat + yükselen OI = güçlü trend; düşen OI = zayıflayan trend | ORTA — günlük bazda filtre olarak kullanılabilir |
| **Yabancı İşlemleri** | BIST'te yabancı payı piyasa yönü için referans | DÜŞÜK — VİOP'a özgü yabancı verisi sınırlı |

**Öneri:** Baz (basis) analizi implementasyona en uygun VİOP-özgü sinyal. Spot fiyat MT5'ten çekilebilir (ör: THYAO spot vs F_THYAO vadeli). Extreme baz değerleri (z-score bazlı) ek bir filtre olarak kullanılabilir.

---

## 4. Tespit Edilen Kod Zayıflıkları

### 4.1 Breakout Strength Hesabında Likidite Sınıfı Kullanılmıyor
- **Konum:** `ogul.py:664`
- **Sorun:** Giriş filtresi likidite bazlı çarpan kullanır (A:1.5, B:2.0, C:3.0) ama strength hesabı global `BO_VOLUME_MULT=1.5` ve `BO_ATR_EXPANSION=1.2` sabitlerini kullanır
- **Etki:** C sınıfı kontratta 3× hacimle geçen breakout ile A sınıfında 1.5× hacimle geçen breakout aynı güç skorunu alır. C sınıfı sinyalinin aslında çok daha güçlü olması gerekir.
- **Öneri:** Strength hesabında da likidite bazlı sabitleri kullanmak

### 4.2 Breakout Trailing Stop Likidite Sınıfı Kullanmıyor
- **Konum:** `ogul.py:2070-2102`
- **Sorun:** Trend Follow trailing stop likidite bazlı (A:1.5, B:1.8, C:2.5 ATR) ama Breakout sabit `BO_TRAILING_ATR_MULT=2.0` kullanır
- **Etki:** A sınıfı kontratta breakout trailing stop gereksiz geniş, C sınıfında potansiyel olarak dar
- **Öneri:** `TRAILING_ATR_BY_CLASS` dict'ini breakout'ta da kullanmak

### 4.3 Mean Reversion'da Trailing Stop Yok
- **Konum:** `ogul.py:1963-2008`
- **Sorun:** Mean reversion pozisyonları yalnızca BB orta bant hedefine ve MT5 SL/TP'ye dayanır. Fiyat lehte hareket ettiğinde trailing stop güncellenmez.
- **Etki:** Kar koruması zayıf — fiyat BB orta banta yaklaşıp geri dönerse kazanç buharlaşır
- **Öneri:** BB orta banta mesafe %50 kapandığında SL'yi entry fiyatına çekmek (breakeven trailing)

### 4.4 Bias-Sinyal Çakışması Kullanılmıyor
- **Konum:** `ogul.py:266-315`
- **Sorun:** Bias her cycle hesaplanır ama sinyal üretim veya lot hesaplamasında kullanılmaz
- **Etki:** Zayıf yönde tam lot açılabilir
- **Öneri:** v13.0 dokümanına uygun olarak bias-sinyal çelişkisinde lot %50 küçültme

### 4.5 Seans İçi Zamanlama Filtresi Yok
- **Konum:** `ogul.py:98-99`
- **Sorun:** 09:45-17:45 dışında sinyal üretilmez ama seans içinde zamanlama ayrımı yapılmaz
- **Etki:** Düşük likidite dönemlerinde (11:00-14:00) aynı kalitede sinyal üretilir
- **Öneri:** Seans açılış (ilk 30 dk) ve öğle (11:00-14:00) dönemlerinde lot küçültme veya sinyal kalitesi eşiğini yükseltme

---

## 5. Güçlendirme Yol Haritası

### Faz A — Düşük Risk Optimizasyonlar (Mevcut yapıya minimal müdahale)

| # | Değişiklik | Dosya | Beklenen Etki | Karmaşıklık |
|---|-----------|-------|---------------|-------------|
| A1 | RSI eşiklerini 20/80'e sıkılaştır | `ogul.py:62-63` | Daha az ama daha kaliteli MR sinyali | Düşük — 2 satır |
| A2 | Breakout strength'e likidite sınıfı ekle | `ogul.py:~664` | C sınıfı sinyalleri doğru değerlenir | Düşük — 5 satır |
| A3 | Breakout trailing stop'a likidite sınıfı ekle | `ogul.py:~2070` | Stop mesafesi piyasa gerçekliğine uyar | Düşük — 3 satır |
| A4 | Bias-sinyal çakışmasında lot %50 küçült | `ogul.py:_execute_signal()` | Zayıf yönde risk azaltma | Orta — 15 satır |
| A5 | Mean Reversion'a breakeven trailing ekle | `ogul.py:_manage_mean_reversion()` | Kar koruması iyileşir | Orta — 20 satır |

### Faz B — Tamamlayıcı İndikatörler (Yeni bilgi katmanı)

| # | Değişiklik | Dosya | Beklenen Etki | Karmaşıklık |
|---|-----------|-------|---------------|-------------|
| B1 | Keltner Channel implementasyonu | `indicators.py` | BB/KC squeeze stratejisi, breakout kalitesi | Orta — ~40 satır |
| B2 | Williams %R implementasyonu | `indicators.py` | MR stratejisinde daha hızlı sinyal | Düşük — ~20 satır |
| B3 | Normalized ATR (ATR/Close%) | `indicators.py` | Kontratlar arası volatilite karşılaştırması | Düşük — ~10 satır |
| B4 | Baz (spot-futures) hesaplama | `ogul.py` veya `baba.py` | VİOP'a özgü filtre | Orta — ~30 satır |
| B5 | BB/KC Squeeze tespiti | `ogul.py` | Yüksek olasılıklı breakout sinyali | Orta — ~40 satır |

### Faz C — Mimari İyileştirmeler (Daha derin değişiklikler)

| # | Değişiklik | Dosya | Beklenen Etki | Karmaşıklık |
|---|-----------|-------|---------------|-------------|
| C1 | Hurst Exponent bazlı rejim tespiti | `baba.py` | ADX'ten daha güvenilir RANGE/TREND ayrımı | Yüksek — ~100 satır + test |
| C2 | Adaptif EMA (KAMA veya HMA) | `indicators.py`, `ogul.py` | Lag azaltma, whipsaw azaltma | Yüksek — ~80 satır + test |
| C3 | Seans içi zamanlama filtresi | `ogul.py` | Düşük likidite döneminde lot/kalite ayarı | Orta — ~30 satır |
| C4 | VWAP (sadece A sınıfı) | `indicators.py`, `ogul.py` | Kurumsal seviye referansı | Yüksek — ~60 satır + test |
| C5 | OBV trend onay filtresi | `indicators.py`, `ogul.py` | Hacim-fiyat uyumsuzluğu tespiti | Orta — ~40 satır |

### Önerilen Uygulama Sırası

```
Faz A (1-2 gün)  → Mevcut sistemde düşük riskli iyileştirmeler
    A1 → A2 → A3 → A4 → A5

Faz B (3-5 gün)  → Yeni indikatörler + test
    B1 → B5 → B2 → B3 → B4

Faz C (1-2 hafta) → Mimari değişiklikler + kapsamlı backtest
    C1 → C3 → C2 → C5 → C4
```

### Her Faz Sonrası Doğrulama

1. Mevcut 644 test'in tamamı geçmeli
2. Backtest: Son 3 ay VİOP verisi üzerinde A/B karşılaştırma
3. Metrikler: Win rate, profit factor, max drawdown, Sharpe ratio
4. Sinyal sayısı karşılaştırması (çok az sinyal = aşırı filtreleme)

---

## 6. Risk ve Uyarılar

### Yapılmaması Gerekenler

1. **Aşırı optimizasyon (overfitting):** Backtest'te mükemmel görünen parametreler canlıda çalışmaz. Her parametre değişikliği out-of-sample test gerektirir.
2. **İndikatör enflasyonu:** Daha fazla indikatör = daha iyi değil. Birbirine benzer indikatörler (RSI + Stochastic + Williams %R hepsi birden) redundansi yaratır, ek bilgi katmaz.
3. **C sınıfı kontratlarda karmaşık sinyal:** Düşük likidite kontratlarında basit kurallar karmaşık sistemlerden daha güvenilirdir.
4. **VİOP spread + komisyon maliyetini ihmal etme:** %55-60 edge olsa bile spread + komisyon + slippage maliyeti karı yiyebilir. Her strateji değişikliğinde net kârlılık (brüt değil) ölçülmelidir.

### VİOP'a Özgü Riskler

- **Overnight gap:** Pay vadeli kontratlar akşam seansı olmadan kapanır. Ertesi gün açılışta gap riski.
- **Vade geçişi:** Vade ayı sonlarında likidite düşer, spread genişler. Mevcut `EXPIRY_NO_NEW_TRADE_DAYS=3` doğru ama yetersiz olabilir.
- **Market maker etkisi:** VİOP'ta market maker kimlikleri görülmez. Market maker'ın pozisyon boşaltması normal hacim artışı olarak algılanabilir.

---

## 7. Sonuç

Mevcut OĞUL sinyal motoru **sağlam bir temel** üzerine kuruludur. Üç strateji, rejim bazlı aktivasyon, likidite sınıfı ayrımı ve çok katmanlı filtreleme profesyonel bir yaklaşımı yansıtır.

**En kritik zayıflık:** EMA(20)/EMA(50) crossover'ın M15 zaman diliminde aşırı gecikme problemi. Bu, trend follow stratejisinin VİOP'ta beklenen performansın altında kalmasına neden olabilir.

**En yüksek değerli ekleme:** Keltner Channel + BB/KC squeeze. Mevcut breakout stratejisine güçlü bir tamamlayıcı ve yeni sinyal kaynağı sağlar.

**En düşük maliyetli iyileştirme:** RSI eşiklerini 20/80'e sıkılaştırma + breakout strength/trailing'e likidite sınıfı ekleme. Minimum kod değişikliği, ölçülebilir kalite artışı.

---

*Rapor Sonu — Hazırlayan: Claude Code / ÜSTAT v5.0 Sinyal Analizi*
