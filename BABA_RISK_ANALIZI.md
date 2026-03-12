# BABA Risk Motoru Analizi — Garantici mi, Gerçekçi mi?

**Tarih:** 13 Mart 2026
**Dosya:** engine/baba.py (2325 satır, v13.0)
**Soru:** BABA sistemi gerçekten riski yönetebilecek kapasitede mi? Yoksa çok katı mı?

---

## KISA CEVAP

**BABA çok katı ve çok garantici.** Mevcut parametrelerle sistem, VİOP'un normal işlem koşullarında bile sürekli kendi kendini kısıtlıyor. Bir risk yöneticisi sermayeyi korumalı — ama bu kadar sıkı tutarsa motor hiç çalışmaz. Şu anki haliyle BABA, Ferrari'nin el frenini çekili bırakmış bir güvenlik görevlisi gibi.

---

## 1. REJİM TESPİTİ — BABA'nın Beyni

### 1.1 Rejim Algılama Mimarisi

BABA 15 sembolü tek tek sınıflandırıp **ağırlıklı oylama** ile genel rejim belirliyor:

```
Öncelik sırası: OLAY > VOLATILE > TREND > RANGE
Likidite ağırlığı: A=3 oy, B=2 oy, C=1 oy
```

**VOLATILE eşiği: %30 oy yeterli.** Yani 15 sembolün likidite ağırlıklı oylarının %30'u VOLATILE derse, tüm piyasa VOLATILE ilan ediliyor ve motor duruyor.

### 1.2 KRİTİK SORUN: VOLATILE Çok Kolay Tetikleniyor

VOLATILE koşulları (herhangi biri yeterli):
- ATR > ortalama × 2.0
- Spread > ortalama × 3.0
- Son bar hareketi > %2

**VİOP gerçekliği:** Borsa İstanbul/VİOP'ta ATR'nin ortalamanın 2 katına çıkması sık görülür — özellikle gün içi haber akışlarında. Tek bir C sınıfı kontratta (F_KONTR, F_ASTOR) spread'in 3× patlaması yeterli — bu düşük likidite kontratlarında öğle arasında bile olabilir.

**Sonuç:** Likidite ağırlıklı oylama sayesinde C sınıfı kontratlar az oy taşır (1 oy), ama 5 A sınıfı kontrattan 2 tanesi bile VOLATILE oy verirse (2×3=6 oy), toplam 28 oy içinde %21 eder. Buna birkaç B+C eklenince kolayca %30 aşılır.

**VOLATILE = motor durması** demek. OĞUL'da VOLATILE rejimde sinyal yok + açık pozisyonlar kapatılıyor.

### 1.3 OLAY Rejimi — Takvim Bazlı Tam Duruş

OLAY tetikleyicileri:
- TCMB/FED toplantı günü (takvimden)
- VİOP vade bitiş: son 2 gün
- USD/TRY şoku: %2+ hareket

**Problem:** TCMB/FED toplantı günü, **tüm gün boyunca** OLAY rejimi. Bu mantıklı mı? Toplantı kararı genellikle 14:00'te açıklanır (TCMB) veya gece (FED). Saat 09:45-13:00 arası piyasa normal işliyor olabilir ama BABA tüm günü kapatıyor.

Yılda yaklaşık 20 TCMB+FED günü var. Artı 12 vade bitiş × 2 gün = 24 gün. **Toplam ~44 gün (yılın yaklaşık %18'i)** otomatik olarak OLAY rejiminde, yani motor tamamen duruyor.

### 1.4 Rejim Tespiti Puanı: 6/10

Mekanizma sağlam ama eşikler VİOP gerçekliği için ayarlanmamış. Tüm gün bazlı OLAY durumu ve düşük VOLATILE eşiği, motoru gereksiz yere susturuyor.

---

## 2. RİSK KATMANLARI — Ne Kadar Katı?

BABA'nın risk kontrol sırası (her biri durdurucu):

| # | Kontrol | Eşik | Aksiyon | Katılık |
|---|---------|------|---------|---------|
| 1 | Kill-switch L3 | Manuel/DD | Tam kapanış | Gerekli |
| 2 | Kill-switch L2 | Günlük kayıp/3 kayıp | Sistem pause | **Çok katı** |
| 3 | Aylık kayıp | %7 | Sistem dur + manuel onay | Makul |
| 4 | Günlük kayıp | **%1.8** | Sistem dur + L2 | **ÇOK KATI** |
| 5 | Hard drawdown | %15 | Tam kapanış + L3 | Makul |
| 6 | Max drawdown | %10 | Tam kapanış + L3 | Makul |
| 7 | Haftalık kayıp | %4 | Lot %50 azalt | Makul |
| 8 | Floating loss | **%1.5** | Yeni işlem engeli | **Çok katı** |
| 9 | Günlük işlem | **5** | Yeni işlem engeli | **Çok katı** |
| 10 | 3 üst üste kayıp | 3 kayıp | **4 saat cooldown + L2** | **AŞIRI KATI** |
| 11 | Korelasyon | 3 aynı yön | Yeni işlem engeli | Makul |

### 2.1 GÜNLÜK KAYIP LİMİTİ: %1.8 — Çok Dar

**Problem:** %1.8 günlük kayıp limiti, risk_per_trade=%1 ve max 5 pozisyon ile pratikte 2 ardışık kayıp sonrası tüm günü kapatır.

Hesap: 100.000 TL hesap, %1 risk/işlem = 1.000 TL risk. İki kötü işlem (-1.000 + -800 TL) = -1.800 TL = %1.8. Gün bitti.

**Sektör standardı:** Günlük kayıp limiti genellikle %2-3 civarında. %1.8, çoğu gün sadece 1-2 kayıp sonrası sistemi durduracak.

### 2.2 FLOATING LOSS: %1.5 — Erken Engel

Açık pozisyonlar %1.5 kayıpta olduğunda yeni işlem engeli. 5 pozisyon açıksa ve her biri ortalama -0.3% floating loss'ta, toplam %1.5'e ulaşır. Bu, normal piyasa geri çekilmelerinde bile tetiklenir.

### 2.3 GÜNLÜK MAX İŞLEM: 5 — Çok Az

5 işlem = sabah 2 sinyal + öğlen 1 sinyal + öğleden sonra 2 sinyal. Ancak BABA'nın kendi cooldown'ları + OĞUL'un yarım lot girişi + maliyetlendirme hesaba katıldığında:

- Yarım lot giriş → dolum sayılır (daily_trade_count++)
- Maliyetlendirme → bu da sayılır (+1)
- TP1 yarı kapanış → OĞUL'da increment yok ama lot azalır

Pratikte 5 işlem limiti, 2-3 tam döngüden sonra dolabilir.

### 2.4 3 ÜST ÜSTE KAYIP → 4 SAAT COOLDOWN + L2 — EN KATI KURAL

Bu kural tek başına sistemin en büyük darboğazı:

1. 3 kayıp → 4 saat cooldown başlar
2. Kill-switch L2 aktif → sistem pause
3. 8 saatlik VİOP seansında 4 saat = seansın yarısı kapalı
4. Ertesi gün günlük sıfırlamayla resetleniyor — ama o gün bitmiş

**Graduated lot schedule** (1 kayıp → %75 lot, 2 kayıp → %50 lot, 3 kayıp → lot=0) kademeli azaltmayı zaten sağlıyor. Üstüne 4 saat cooldown FAZLA.

---

## 3. POZİSYON BOYUTLAMA — Motor Gücü Ne Kadar?

```python
lot = (equity × risk_per_trade × regime_mult) / (ATR × kontrat_çarpanı)
```

**Rejim çarpanları:**
- TREND: 1.0 (tam güç)
- RANGE: 0.7 (%70 güç)
- VOLATILE: 0.25 (%25 güç — ama nasılsa sinyal yok)
- OLAY: 0.0 (sıfır — sinyal yok)

**Katmanlar üst üste biniyor:**
1. Rejim çarpanı: × 0.7 (RANGE'de)
2. Graduated lot: × 0.75 (1 kayıp sonrası)
3. Bias nötr: × 0.85 (OĞUL'dan)
4. Haftalık yarılama: × 0.5 (haftalık kayıpsa)
5. ÜSTAT lot_scale: × ? (dinamik)
6. ENTRY_LOT_FRACTION: × 0.5 (evrensel yönetim yarım lot giriş)

**En kötü normal senaryo (RANGE rejim, 1 kayıp, bias nötr, yarım lot):**
```
lot = base × 0.7 × 0.75 × 0.85 × 0.5 = base × 0.223
```

Yani hesaplanan lot'un sadece %22'si ile giriyor! 100.000 TL hesapta base lot 3 olsa, gerçek giriş = 0.67 lot. Minimum 1 lot'un altında kaldığı için vol_min = 1 uygulanıyor. Ama bu durumda da risk hesabı bozuluyor çünkü lot_min ile girilen risk, hesaplananın çok üstünde olabilir.

---

## 4. KORELASYON YÖNETİMİ — Mantıklı Ama Sıkı

- Max 3 aynı yön: Makul. VİOP'ta 15 kontrat arasında 3 BUY/3 SELL dengesi mantıklı.
- Max 2 aynı sektör aynı yön: **Çok sıkı.** VİOP'ta sektör sayısı az, "banka" sektöründe F_AKBNK + F_HALKB var ve ikisi de sık Top 5'e girer. 2 banka BUY → 3. banka BUY engellenmiş.
- Endeks ağırlık skoru < 0.25: İlginç ve sofistike bir kontrol. F_THYAO (%12 endeks ağırlığı) + F_AKBNK (%8) aynı yönde → skor 0.20. Bir tane daha eklenince 0.25'i aşar. Pratikte 2-3 büyük kontrat aynı yönde olunca engel.

---

## 5. FAKE SİNYAL ANALİZİ — İyi Fikir, Tartışmalı Uygulama

4 katmanlı fake sinyal sistemi (her 30 sn kontrol):

| Katman | Ağırlık | Tetikleyici |
|--------|---------|-------------|
| Hacim | 1 | volume/ort < 0.7 |
| Spread | 2 | spread > 2.5-5× (likidite bazlı) |
| Multi-TF | 1 | M5+M15+H1 yön uyumu < 2/3 |
| Momentum | 2 | RSI aşırı + MACD diverjans |

**Toplam skor ≥ 5 → pozisyon kapatılır** (max 6 puan).

**Problem:** Bu sistem OĞUL'un açtığı pozisyonları BABA'nın kapatması demek. Yani OĞUL sinyal üretip emir gönderdi, pozisyon açıldı, 30 saniye sonra BABA "bu fake" deyip kapatıyor. Bu, iki motor arasında çatışma yaratır.

**Daha büyük problem:** Fake skor eşiği 5 iken, sadece spread(2) + momentum(2) + hacim(1) = 5 ile tetiklenir. Spread genişleme VİOP'ta öğle arasında normal, momentum RSI aşırı bölge trend piyasada sık oluşur (trend güçlüyken RSI > 80 olabilir). Bu durumda BABA, trend'in en güçlü anında pozisyonu kapatabilir.

---

## 6. KILL-SWITCH SİSTEMİ — Güçlü Ama Agresif

**L1 (Kontrat durdur):** Erken uyarı CRITICAL → tek kontrat durur. Mantıklı.

**L2 (Sistem pause):** Günlük kayıp, 3 üst üste kayıp, OLAY rejimi → tüm sistem durur. **Çok agresif.** Günlük kayıp %1.8'de L2 aktif olması, neredeyse her kötü günde sistemi durdurur.

**L3 (Tam kapanış):** Max drawdown %10, hard drawdown %15, manuel buton. Akıllı kapatma mantığı: önce zarardakileri kapatıyor, hâlâ eşik üstündeyse kârdakileri de kapatıyor. Bu iyi.

**Önemli detay:** L2 → ertesi günü sıfırlamayla otomatik kalkar. Ama L3 ve aylık paused = **manuel onay gerekli**. Bu doğru.

---

## 7. BABA OĞUL'U NE KADAR KISITLIYOR?

BABA'nın OĞUL'u kısıtladığı tüm noktalar:

| Nokta | Mekanizma | Etki |
|-------|-----------|------|
| Rejim → strateji | VOLATILE/OLAY → sinyal yok | Motor durur |
| Rejim → lot çarpan | RANGE → ×0.7 | Lot azalır |
| Korelasyon | 3 aynı yön | Yeni işlem engeli |
| Günlük kayıp | %1.8 → L2 | Motor durur |
| 3 üst üste kayıp | → 4 saat cooldown | Motor durur |
| Floating loss | %1.5 | Yeni işlem engeli |
| Günlük max işlem | 5 | Yeni işlem engeli |
| Graduated lot | 1-2 kayıp → lot azalt | Lot düşer |
| Fake sinyal | Skor ≥ 5 → kapatma | Pozisyon kapatılır |
| L1 erken uyarı | CRITICAL → kontrat dur | Tek sembol engelli |

**Toplam etki:** Normal bir işlem gününde BABA, ortalama olarak OĞUL'un potansiyel kapasitesinin **%30-50'sini kısıtlıyor**. Kötü bir günde bu oran **%80-100'e** çıkıyor.

---

## 8. BABA NASIL OLMALI? — YAPISAL ÖNERİLER

### 8.1 Rejim Tespiti İyileştirmeleri

**OLAY rejimi saatlik olmalı, günlük değil:**
```
TCMB PPK günü:
  09:45 - 12:00 → RANGE (normal işlem, dikkatli)
  12:00 - 15:00 → OLAY (karar açıklanıyor, motor dur)
  15:00 - 17:45 → Karar sonrası: eğer hareketli → VOLATILE, değilse → TREND/RANGE
```

**VOLATILE eşiği artırılmalı:**
- ATR_VOLATILE_MULT: 2.0 → 2.5 (VİOP normali daha volatil)
- SPREAD_VOLATILE_MULT: 3.0 → 4.0 (düşük likidite spread'ini hesaba kat)
- VOLATILE oy eşiği: %30 → %40 (daha fazla sembolün onayı gereksin)

### 8.2 Risk Limitleri Gevşetilmeli

| Parametre | Mevcut | Önerilen | Gerekçe |
|-----------|--------|----------|---------|
| max_daily_loss | %1.8 | **%2.5** | 2-3 kayıp sonrası değil, 3-4 kayıp sonrası dursun |
| max_floating_loss | %1.5 | **%2.0** | Normal geri çekilmelerde tetiklenmesin |
| max_daily_trades | 5 | **8** | Yarım lot giriş + maliyetlendirme sayılıyor |
| consecutive_loss_limit | 3 | 3 (değişmesin) | Ama cooldown 4→**2 saat** olsun |
| cooldown_hours | 4 | **2** | 8 saatlik seansta 4 saat = yarım gün |

### 8.3 Graduated Lot + Cooldown Çakışması Çözülmeli

Şu an hem graduated lot (1 kayıp → %75, 2 kayıp → %50) hem cooldown (3 kayıp → 4 saat dur) var. İkisi birden aşırı:

**Önerilen:** Graduated lot'u KOR, cooldown'u KALDIR. Bunun yerine:
- 3 üst üste kayıp → lot %25'e düşür (graduated devam etsin: 3 kayıp → %25)
- 4 üst üste kayıp → o gün dur (cooldown yerine günlük kapanış)
- 4 saat cooldown tamamen kaldırılsın

### 8.4 Fake Sinyal Sistemi Revize Edilmeli

Mevcut: Skor ≥ 5 → pozisyon kapatılır.
Problem: BABA kendi başına OĞUL'un pozisyonlarını kapatıyor.

**Önerilen:**
- Fake skor ≥ 5 → OĞUL'a "sinyal zayıfladı" bildirimi gönder (pozisyon kapatma kararını OĞUL versin)
- Fake skor ≥ 6 (tüm katmanlar) → doğrudan kapatma (gerçekten tehlikeli durum)
- RSI > 80 tek başına fake tetikleyicisi OLMAMALI — güçlü trendlerde RSI uzun süre 80+ kalabilir

### 8.5 VOLATILE Rejimde Kısmi İşlem

Mevcut: VOLATILE → sinyal yok + açık pozisyonlar kapatılıyor.

**Önerilen:**
- VOLATILE → yeni sinyal yok (bu kalabilir)
- VOLATILE → mevcut kârdaki pozisyonları KORU (trailing ile)
- VOLATILE → sadece zarardaki pozisyonları kapat
- VOLATILE rejim çarpanı: 0.25 → 0.0 (zaten sinyal yok ama formül için)

Bu sayede volatilite artışında kârdaki pozisyonlar korunur (çoğu zaman volatilite trend yönünde artar).

### 8.6 Endeks Ağırlık Skoru Güncellenmeli

XU030_WEIGHTS statik hardcoded. Bu ağırlıklar her çeyrekte değişir.

**Önerilen:** Config veya DB'den okunacak şekilde dinamik yapılmalı. Veya ÜSTAT'ın görevleri arasına eklenebilir.

---

## GENEL SONUÇ TABLOSU

| Bileşen | Puan | Yorum |
|---------|------|-------|
| Rejim algılama mekanizması | 7/10 | Oylama sistemi iyi, eşikler ayarlanmalı |
| Rejim eşikleri (VİOP uyumu) | 4/10 | VOLATILE/OLAY çok kolay tetikleniyor |
| Pozisyon boyutlama formülü | 8/10 | Fixed-fractional + rejim çarpanı profesyonel |
| Lot kısıtlama katmanları | 4/10 | Çok fazla çarpan üst üste biniyor |
| Günlük/haftalık/aylık limitler | 6/10 | Yapı doğru, eşikler dar |
| Korelasyon yönetimi | 7/10 | Sektör + endeks ağırlık, VİOP'a uygun |
| Kill-switch sistemi | 8/10 | L1/L2/L3 mimarisi profesyonel |
| Fake sinyal analizi | 5/10 | İyi fikir ama OĞUL ile çatışıyor |
| Erken uyarı sistemi | 8/10 | Likidite bazlı eşikler çok iyi |
| Period sıfırlama | 8/10 | Gün/hafta/ay + cooldown end tracking |
| **GENEL ORTALAMA** | **6.5/10** | |

---

## SONUÇ: GÜVENLİK GÖREVLİSİ Mİ, HAPİSHANE GARDİYANI MI?

**BABA şu anda hapishane gardiyanı.** Mimarisi doğru, mekanizmaları profesyonel, ama eşikleri VİOP'un gerçek koşulları için çok sıkı. Sonuç:

1. **Yılın ~%18'i OLAY rejiminde** (TCMB/FED + vade günleri) → motor tamamen kapalı
2. **Normal günlerde bile %1.8 günlük kayıp** → 2 kötü işlemde gün biter
3. **3 üst üste kayıp → 4 saat cooldown** → seansın yarısı kapanır
4. **Lot çarpanları üst üste binince** → gerçek lot, hesaplananın %20-30'u
5. **Fake sinyal sistemi** → BABA, OĞUL'un kararlarını geçersiz kılıyor

**BABA'nın yapıya uygun hali:**
Bir güvenlik görevlisi gibi olmalı — kapıda durup şüpheli durumları engellemeli, ama içerideki insanların (OĞUL) işini yapmasına izin vermeli. Şu an kapıyı kilitleyip anahtarı cebine koymuş.

**Önerilen yaklaşım:** Eşikleri %30-40 gevşet, OLAY rejimini saatlik yap, cooldown'u kaldırıp graduated lot'u genişlet, fake sinyal kapatma yetkisini OĞUL'a devret. Bu değişikliklerle BABA 6.5/10'dan 8.5/10'a çıkar.
