# ÜSTAT — Profesyonel Çalışma Rehberi

**Bu rehber, algoritmik trading uygulamalarının geliştirilmesi, bakımı ve yönetimi için
sektör standartlarını ÜSTAT'a uyarlar. FIA (Futures Industry Association), FINRA,
Google SRE ve profesyonel quant firmalarının pratiklerinden derlenmiştir.**

**Kaynak:** keepachangelog.com, FIA Automated Trading Risk Controls, Google SRE Workbook,
Knight Capital postmortem, NautilusTrader, Build Alpha, LuxAlgo.

---

## 1. GÜNLÜK ÇALIŞMA DİSİPLİNİ

### 1.1 Piyasa Öncesi Kontrol Listesi (Her Gün 09:00-09:30)

```
[ ] Geceden gelen haber ve ekonomik takvimi incele
    - TCMB, FED, ECB kararları, VİOP vade tarihleri
    - Bilanço açıklayan şirketler (KAP bildirimleri)

[ ] Sistem sağlık kontrolü
    - API çalışıyor mu? → curl http://localhost:8000/api/health
    - MT5 bağlı mı? → Ping < 5ms
    - Engine heartbeat taze mi? → < 45sn
    - Kill-switch seviyesi → L0 olmalı
    - Disk alanı → %10 üzeri boş

[ ] Dünün kapanış raporu
    - Tüm pozisyonlar kapandı mı? (EOD 17:45)
    - Günlük K/Z normal aralıkta mı?
    - Hata loglarında anomali var mı?

[ ] Bakiye ve risk durumu
    - Bakiye dünle tutarlı mı?
    - Drawdown seviyeleri kabul edilebilir mi?
    - Floating pozisyon yok olmalı (gece açık kalmış mı?)
```

### 1.2 Piyasa Saatlerinde (09:30-18:15) — SAVAŞ ZAMANI

```
YAPILACAKLAR:
  ✓ Monitör sayfasını açık tut — rejim, pozisyon, kill-switch izle
  ✓ Hata Takip sayfasını periyodik kontrol et
  ✓ Anormal davranış gördüğünde hemen log'a bak
  ✓ Acil durumda Kill-Switch butonunu kullan (2sn basılı tut)

YASAKLAR:
  ✗ Kod değişikliği YAPMA (acil bug fix hariç — yazılı onay gerekir)
  ✗ Config parametresi DEĞİŞTİRME
  ✗ Yeniden başlatma YAPMA (watchdog otomatik yapar)
  ✗ Yeni özellik EKLEME
  ✗ Refactoring YAPMA
```

### 1.3 Piyasa Sonrası Kontrol Listesi (Her Gün 18:15-18:30)

```
[ ] Günlük işlem sayısı ve sonuçları
[ ] Win rate ve ortalama K/Z
[ ] SL/TP tetiklenme oranları
[ ] Hangi semboller işlem gördü, hangileri görmedi
[ ] Anormal slippage var mı?
[ ] Veritabanı yedeği alındı mı? (otomatik kontrol)
[ ] Log dosyası boyutu kontrol (şişme var mı?)
```

### 1.4 Haftalık Kontrol (Her Cuma Kapanış Sonrası)

```
[ ] Haftalık performans özeti
    - Toplam K/Z, win rate, profit factor
    - En iyi / en kötü işlem analizi
    - Strateji bazlı performans kırılımı

[ ] Korelasyon kontrolü
    - Hangi semboller birlikte hareket etti?
    - Korelasyon limitleri doğru çalıştı mı?

[ ] Sistem kaynakları
    - DB boyutu (trades.db) — şişme var mı?
    - Log dosyaları rotasyonu yapıldı mı?
    - CPU/RAM kullanımı normal mi?

[ ] Rejim analizi
    - Bu hafta hangi rejimler baskındı?
    - OLAY rejimi kaç kez tetiklendi?
    - Stratejiler rejime uygun mu çalıştı?
```

### 1.5 Aylık Kontrol (Her Ayın İlk Pazartesi)

```
[ ] Aylık performans raporu
    - Hedef vs gerçekleşen K/Z
    - Drawdown grafiği analizi
    - Sharpe ratio hesaplama

[ ] Strateji sağlığı
    - Backtest vs canlı sonuç karşılaştırma
    - Walk-forward analiz (son 3 ay)
    - Parametre drift kontrolü (ATR, ADX eşikleri hâlâ geçerli mi?)

[ ] Altyapı bakımı
    - Python paket güncellemeleri (güvenlik yamaları)
    - Electron/Node güncellemeleri
    - MT5 terminal güncellemesi
    - Windows güncellemeleri (piyasa kapalıyken)

[ ] Stres testi
    - 10.000 kombinasyonlu stres testi çalıştır
    - Simülasyon (500+ cycle) çalıştır
    - Sonuçları önceki ayla karşılaştır

[ ] Vade takvimi kontrolü
    - Sonraki 3 ayın vade tarihleri VIOP_EXPIRY_DATES'te var mı?
    - Tatil takvimi (ALL_HOLIDAYS) güncel mi?
```

---

## 2. KOD DEĞİŞİKLİĞİ YAPMA KURALLARI

### 2.1 Değişiklik Öncesi (ZORUNLU)

```
1. SORUN TESPİTİ
   - Log'dan gerçek hatayı bul (tahmin YASAK)
   - Hatanın hangi modülde olduğunu belirle
   - Kök nedeni kanıtla (ekran görüntüsü, log çıktısı)

2. ETKİ ANALİZİ
   - Değişeceğin fonksiyonu kim çağırıyor? (CLAUDE.md Bölüm 6)
   - Bu değişiklik başka neyi bozabilir?
   - Kırmızı Bölge / Siyah Kapı dokunuyor mu?

3. PLAN YAZ
   - Ne değişecek (eski → yeni, yan yana)
   - Neden değişecek (kök neden referansı)
   - Geri alma planı (git revert komutu hazır)

4. ONAY AL
   - C3/C4 değişiklikler: kullanıcıdan açık "evet" al
   - Config değişikliği: eski ve yeni değeri göster
```

### 2.2 Değişiklik Sırasında

```
- TEK ATOMİK DEĞİŞİKLİK: Bir seferde bir şeyi düzelt
- Fonksiyon silme YASAK (özellikle Siyah Kapı)
- Çağrı sırasını değiştirme YASAK
- Magic number kullanma YASAK (config'den oku)
- Test et, sonra commit et (BOZUK kod commit'lenMEZ)
- git add dosya1 dosya2 (git add . YASAK)
```

### 2.3 Değişiklik Sonrası (İŞLEMİ BİTİR)

```
1. Build al → npm run build (0 hata)
2. Gelişim tarihçesine yaz → docs/USTAT_GELISIM_TARIHCESI.md
3. Versiyon kontrolü hesapla → değişiklik oranı ≥%10 ise artır
4. Git commit → açıklayıcı mesaj (feat: / fix: / refactor:)
5. Oturum raporu yaz → docs/YYYY-MM-DD_session_raporu_*.md
6. Uygulamayı yeniden başlat (piyasa kapalıyken)
7. Doğrulama → API health check + log kontrolü
```

---

## 3. TEST DİSİPLİNİ

### 3.1 Test Piramidi

```
                    ┌──────────┐
                    │ Simülasyon│  ← 500+ cycle, gerçek piyasa koşulları
                   ┌┤  (Manuel) ├┐
                  ┌┤│          │├┐
                 ┌┤││          ││├┐
                │  │└──────────┘│  │
                │  │  Entegrasyon│  │  ← API endpoint testi, motor etkileşimi
               ┌┤  └──────────┘  ├┐
              ┌┤│                  │├┐
             │  │   Stres Testi    │  │  ← 10.000 kombinasyon, her modül
            ┌┤  └──────────────────┘  ├┐
           │  │      Birim Testi       │  │  ← Fonksiyon bazlı, hızlı
           └──┴────────────────────────┴──┘
```

### 3.2 Ne Zaman Hangi Test?

| Durum | Test |
|-------|------|
| Her değişiklikten sonra | Birim testi (`pytest tests/test_unit_core.py`) |
| Her commit'ten sonra | Stres testi (`pytest tests/test_stress_10000.py`) |
| Her hafta sonu | Simülasyon (500 cycle, `python -m engine.simulation`) |
| Yeni strateji ekleme | Backtest + forward test + simülasyon |
| Config değişikliği | Stres testi + simülasyon |

### 3.3 Test Kriterleri (Go/No-Go)

| Metrik | Hedef | Kırmızı Çizgi |
|--------|-------|---------------|
| Birim test başarı | %100 | < %100 → deploy YASAK |
| Stres test başarı | %100 | < %99 → inceleme gerekli |
| Simülasyon K/Z | Pozitif | 3 ardışık negatif → strateji durdur |
| Max drawdown | < %20 | > %30 → strateji devre dışı |
| Win rate (trend) | %30-50 | < %20 → strateji sorgulanmalı |
| Profit factor | > 1.5 | < 1.0 → strateji zarar ediyor |

---

## 4. CANLI SİSTEM İZLEME

### 4.1 Anlık İzlenecek Metrikler

| Kategori | Metrik | Alarm Eşiği |
|----------|--------|-------------|
| **Execution** | Emir dolum oranı | < %90 |
| **Execution** | Slippage | > 0.5×ATR |
| **Execution** | Emir→Dolum süresi | > 2 saniye |
| **Risk** | Günlük K/Z | -%1.8 limite yaklaşma |
| **Risk** | Drawdown | > maks izin verilenin %50'si |
| **Risk** | Açık pozisyon | Limite yaklaşma (5) |
| **Risk** | Floating kayıp | > %1.5 |
| **Sistem** | MT5 ping | > 5ms |
| **Sistem** | Heartbeat yaşı | > 45sn |
| **Sistem** | Cycle süresi | > 10sn (overrun) |
| **Sistem** | Disk alanı | < %10 boş |
| **Strateji** | Win rate (haftalık) | 2 SD sapma |
| **Strateji** | İşlem sıklığı | Beklenmedik artış/azalış |

### 4.2 Alarm Seviyeleri

```
SEVİYE 1 — BİLGİLENDİRME (Sarı)
  → Logla, izle, müdahale gerekmiyor
  Örnek: Spread yükselmesi, düşük hacim, minor data gap

SEVİYE 2 — UYARI (Turuncu)
  → Logla, pozisyon boyutu küçült, yakından izle
  Örnek: Kill-switch L1, korelasyon uyarısı, floating kayıp artışı

SEVİYE 3 — KRİTİK (Kırmızı)
  → Yeni işlem durdur, mevcut pozisyonları koru
  Örnek: Kill-switch L2, günlük kayıp limiti, aylık drawdown

SEVİYE 4 — ACİL (Siyah)
  → TÜM pozisyonları kapat, sistemi durdur
  Örnek: Kill-switch L3, hard drawdown ≥%15, MT5 kopukluk > 5dk
```

---

## 5. ACİL DURUM YÖNETİMİ

### 5.1 Olay Müdahale Akışı

```
ALGILAMA (< 10 saniye)
    ↓ Otomatik alarm veya kullanıcı fark etti
SINIFLANDIRMA (< 30 saniye)
    ↓ P1: Para kaybı aktif / P2: Sistem bozuk / P3: Kritik değil
KONTROL ALTINA ALMA (< 1 dakika)
    ↓ P1 → Kill-Switch / P2 → Lot küçültme / P3 → İzle
ÇÖZÜM
    ↓ Minimal düzeltme ile güvenli duruma getir
DOĞRULAMA
    ↓ Log kontrol, API health, pozisyon durumu
RAPOR
    ↓ Oturum raporu: ne oldu, neden oldu, ne yapıldı
```

### 5.2 Bilinen Senaryo Aksiyon Tablosu

| Senaryo | Anında Yapılacak | Sonra Yapılacak |
|---------|-----------------|-----------------|
| MT5 kopukluk | Reconnect 3 deneme, sonra kill-switch | Bağlantı nedenini araştır |
| Veri akışı durdu | Yeni işlem durdur, mevcut pozisyonları koru | Data pipeline loglarını incele |
| Kontrolsüz algoritma | Kill-switch HEMEN | Tam sistem audit |
| SL/TP eksik pozisyon | Force-close HEMEN | Kök neden analizi |
| Drawdown limiti aşıldı | Otomatik: tüm pozisyonları kapat | Strateji performans inceleme |
| DB bozulması | Yedekten geri yükle, trading durdur | Bütünlük kontrolü |
| Çift pozisyon (netting) | Manuel kontrol, fazlayı kapat | Netting lock inceleme |

### 5.3 Postmortem (Olay Sonrası Analiz)

Her P1/P2 olaydan sonra ZORUNLU:

```
1. ZAMAN ÇİZELGESİ
   - Olay ne zaman başladı?
   - Ne zaman fark edildi?
   - Ne zaman müdahale edildi?
   - Ne zaman çözüldü?

2. KÖK NEDEN
   - Sorunun asıl kaynağı ne? (semptom değil)
   - Savunma mekanizmaları neden yakalayamadı?

3. ETKİ
   - Finansal kayıp tutarı
   - Kaçırılan işlem fırsatları
   - Sistem kesintisi süresi

4. AKSİYON MADDELERİ
   - Bu sorunun tekrar yaşanmaması için ne yapılacak?
   - Hangi monitoring/kontrol eklenecek?
   - Tahmini tamamlanma tarihi

5. DERS ÇIKARILDI
   - Knight Capital dersi: Ölü kod KALMAZ, silinir
   - Otomatik kill-switch insan tepkisinden HER ZAMAN hızlıdır
```

---

## 6. PROFESYONEL DEPLOYMENT (YAYIN) SÜRECİ

### 6.1 Güvenli Yayın Adımları

```
1. GELİŞTİRME (Piyasa kapalıyken)
   └─ Kod yaz → birim test → stres test → commit

2. DOĞRULAMA
   └─ Build al (0 hata) → simülasyon çalıştır → sonuçları değerlendir

3. YAYIN
   └─ Uygulamayı kapat → yeni kodu yükle → başlat → health check

4. İZLEME (İlk 24-48 saat)
   └─ Yoğun monitöring → ilk işlemleri yakından takip

5. KARARLAMA (1 hafta sonra)
   └─ Performans normal mi? → Evet: başarılı / Hayır: rollback
```

### 6.2 Rollback (Geri Alma) Kuralları

```
- Her değişiklik AYRI commit → tek adımda geri alınabilir
- Rollback komutu ÖNCEDEN yazılır: git revert <hash>
- Rollback sonrası: build al + uygulamayı yeniden başlat
- Rollback nedenini oturum raporuna yaz
```

---

## 7. VERİ YÖNETİMİ

### 7.1 Veritabanı Bakımı

```
- Günlük yedek: otomatik (engine başlatmada)
- Haftalık: yedek dosyası boyut kontrolü
- Aylık: eski log kayıtlarını arşivle (90 günden eski)
- Yıllık: tam veritabanı dışa aktarma
```

### 7.2 Log Yönetimi

```
- Engine logu: logs/ustat_YYYY-MM-DD.log (günlük rotasyon)
- API logu: api.log
- Electron logu: electron.log
- Max log boyutu: 50MB/dosya (aşarsa sıkıştır ve arşivle)
- Saklama süresi: 90 gün (sonra sil)
```

---

## 8. PERFORMANS DEĞERLENDİRME METRİKLERİ

### 8.1 Strateji Sağlık Göstergeleri

| Metrik | Formül | Hedef | Alarm |
|--------|--------|-------|-------|
| **Sharpe Ratio** | (Ort. Getiri - Risksiz) / Std | > 1.0 | < 0.5 |
| **Profit Factor** | Brüt Kâr / Brüt Zarar | > 1.5 | < 1.0 |
| **Max Drawdown** | En yüksekten en düşüğe % | < %15 | > %20 |
| **Win Rate** | Kârlı İşlem / Toplam | %30-50 (trend) | < %20 |
| **Expectancy** | (WR × Ort.Kâr) - ((1-WR) × Ort.Zarar) | > 0 | < 0 |
| **Recovery Factor** | Net Kâr / Max Drawdown | > 3.0 | < 1.0 |

### 8.2 Overfitting (Aşırı Uyum) Kontrolleri

```
DİKKAT: Bu sinyaller overfitting göstergesidir:
  ⚠ Backtest mükemmel ama canlıda kötü → aşırı optimizasyon
  ⚠ Profit Factor > 3.0 → gerçekçi değil
  ⚠ Win Rate > %80 (trend stratejisi) → muhtemelen curve fitting
  ⚠ Parametre değişikliğine aşırı duyarlılık → fragile strateji
  ⚠ Sadece belirli dönemde çalışan strateji → dönem bağımlılığı

ÖNLEME:
  ✓ Walk-forward analiz (kayar pencere optimizasyon)
  ✓ Out-of-sample test (%20 ayrılmış veri)
  ✓ Monte Carlo simülasyonu (işlem sırasını karıştır)
  ✓ Noise testi (veriye rastgele gürültü ekle)
  ✓ Çoklu enstrüman testi (2+ farklı kontrat)
```

---

## 9. ÜSTAT'A ÖZEL KURALLAR

### 9.1 4 Motor Hiyerarşisi (DEĞİŞTİRİLEMEZ)

```
BABA → OĞUL → H-Engine → ÜSTAT

BABA karar vermeden OĞUL çalışmaz.
BABA "hayır" derse OĞUL işlem açamaz.
Bu sıra ASLA değiştirilemez.
```

### 9.2 Korumasız Pozisyon YASAK

```
send_order() → SL/TP ekleme başarısız → pozisyon ZORLA kapatılır
Hiçbir koşulda SL/TP'siz açık pozisyon bırakılamaz.
Bu kural istisnası YOKTUR.
```

### 9.3 Kill-Switch Monotonluk

```
L0 → L1 → L2 → L3  (sadece yukarı gider)
Otomatik düşürme YASAK.
Sadece kullanıcı manuel düşürebilir (acknowledge).
```

### 9.4 EOD Zorunlu Kapanış

```
17:45 — TÜM pozisyonlar kapatılır
17:50 — Hayalet pozisyon kontrolü
İstisna YOKTUR.
```

### 9.5 Vade Geçişi

```
Vade günü - 1: Eski vade ile son işlem
Vade günü:     GCM yeni vadeye geçer, yeni vade ile işlem
Otomatik — müdahale gerekmez.
```

---

## 10. KNIGHT CAPITAL DERSİ (ASLA UNUTMA)

2012'de Knight Capital, 45 dakikada 460 milyon dolar kaybetti.

**Neden?**
- Eski, kullanılmayan kod (dormant code) production'da bırakılmıştı
- Yeni deployment sırasında eski kod kazara aktif oldu
- Kill-switch'i tetiklemek 30 dakika sürdü (insan tepki süresi)

**ÜSTAT için dersler:**
1. **Ölü kod KALMAZ** — kullanılmayan fonksiyon/değişken silinir
2. **Otomatik kill-switch** — insan tepkisini BEKLEMEden devreye girer
3. **Her deployment test edilir** — "çalışır herhalde" KABUL EDİLEMEZ
4. **Feature flag bırakma** — geçici devre dışı bırakma YASAK
5. **Tek atomik değişiklik** — birden fazla şeyi aynı anda değiştirme

---

> **Bu rehber yaşayan bir belgedir.**
> Yeni dersler öğrenildikçe, yeni kurallar eklendikçe güncellenir.
> Son güncelleme: 2026-03-29
