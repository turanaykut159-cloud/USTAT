# OĞUL İşlem Yapmama Analizi — 2026-03-07

## Özet
OĞUL'un işlem yapmamasının **birden fazla iç içe geçmiş nedeni** var. Bunlar tek başına değil, birlikte bir "engel zinciri" oluşturuyor.

---

## 1. BİRİNCİL NEDEN: Kill-Switch L2 — Günlük Kayıp Limiti (%1.8)

### Kanıt (Loglar)
```
01:17:44 → risk_ok=False başlıyor (engine başlangıcı, restore_risk_state)
...851 cycle boyunca risk_ok=False...
17:17:24 → son risk_ok=False (cycle #53)
17:18:46 → risk_ok=True başlıyor (yeni engine başlatması)
```

### Mekanizma
1. **6 Mart'ta** günlük kayıp %1.8 limitini aşıyor → BABA Kill-Switch L2 aktive ediyor
2. Engine yeniden başladığında `restore_risk_state()` DB'deki son KILL_SWITCH event'ini okuyor
3. Son event `LEVEL_2` → L2 geri yükleniyor
4. 7 Mart 09:30'da `_reset_daily()` çağrılıyor → L2 temizleniyor (reason=="daily_loss" kontrolü)
5. **AMA** hemen ardından `check_risk_limits()` → `check_drawdown_limits()` çağrılıyor
6. daily_pnl hâlâ negatif (eski pozisyonlardan) → L2 tekrar aktive ediliyor!
7. Bu döngü tüm gün boyunca tekrarlanıyor (851 cycle!)

### Kısır Döngü
```
_reset_daily() → L2 temizle → check_risk_limits() → daily_loss hâlâ ≥%1.8 → L2 tekrar aktif
```

Bu döngü nedeniyle risk_ok 17:18'e kadar False kaldı. 17:18'de yeni engine başlatılmış, bu başlatmada RISK_BASELINE_DATE="2026-03-07" olduğu için eski veriler hesaba katılmamış.

### Sonuç
**Gün içinde (09:45-17:45) risk_ok=False — hiçbir sinyal üretilemedi.**

---

## 2. İKİNCİL NEDEN: Rejim-Strateji Uyumsuzluğu

### Kanıt
```
Rejim: RANGE (conf=0.933, ADX=30.4, votes={'TREND': 1, 'RANGE': 14, 'VOLATILE': 0})
```

### Sorun: ADX=30.4 olmasına rağmen rejim RANGE
- Oylama sistemi sembol bazlı çalışıyor: 15 sembolden 14'ü RANGE oyu vermiş
- Ama ortalama ADX=30.4 — bu TREND bölgesi (>25)
- Bu çelişki: bireysel semboller RANGE ama genel piyasa ADX yüksek

### RANGE Rejiminde Aktif Stratejiler
```python
REGIME_STRATEGIES = {
    RegimeType.RANGE: [StrategyType.MEAN_REVERSION, StrategyType.BREAKOUT],
}
```

### Mean Reversion — BLOKLANDI
- **Koşul:** ADX < 20 (MR_ADX_THRESHOLD)
- **Gerçek:** ADX = 30.4
- **Sonuç:** `if adx_val >= MR_ADX_THRESHOLD: return None` — sinyal üretilemez
- Mean Reversion'ın çalışması için ADX < 20 olmalı ama RANGE rejimi zaten ADX < 20 + BB dar gerektirir. ADX=30.4 ile RANGE rejiminde olmak çelişkili.

### Breakout — ZOR
- **Koşul 1:** 20-bar high/low kırılımı
- **Koşul 2:** Hacim > ort × 1.5-3× (likidite sınıfına göre)
- **Koşul 3:** ATR genişleme > 1.2-1.5×
- RANGE piyasasında kırılım zaten nadir. Üstelik hacim ve ATR genişleme koşulları da sıkı.

---

## 3. ÜÇÜNCÜL NEDEN: Top 5'te Sadece 2 Kontrat

### Kanıt
```
top5=['F_AKSEN', 'F_HALKB']  (5 yerine 2)
```

### Etki
- Sinyal üretimi sadece 2 sembolle sınırlı
- F_AKSEN = C sınıfı (düşük likidite) → hacim eşiği çok yüksek (3×)
- F_HALKB = B sınıfı (orta likidite) → hacim eşiği 2×
- 5 yerine 2 sembolle sinyal bulma olasılığı %60 düşüyor

---

## 4. LOT HESAPLAMASI SIFIRA DÜŞME RİSKİ

### Formül Zinciri
```
lot = (equity × risk% × regime_mult) / (ATR × contract_size)
    × graduated_loss_mult      (1 kayıp: ×0.75, 2: ×0.5, 3+: ×0)
    × weekly_halved             (haftalık kayıp: ×0.5)
    × bias_mult                 (nötr: ×0.7, ters: ×0)
    × ENTRY_LOT_FRACTION        (×0.5 — evrensel yönetim)
    → math.floor(lot / vol_step) × vol_step
```

### Örnek Hesaplama (Gerçekçi)
- equity = 50,000 TL
- risk% = 0.01 (%1)
- regime_mult = 0.7 (RANGE)
- ATR = 2.50
- contract_size = 100

```
lot = (50,000 × 0.01 × 0.7) / (2.50 × 100)
    = 350 / 250
    = 1.4
    → floor(1.4) = 1 lot
    × 0.7 (bias nötr) = 0.7
    → floor(0.7) = 0 lot ← SIFIR!
    × ENTRY_LOT_FRACTION (0.5) → zaten 0
```

**Vol_step=1.0 ile her floor() işlemi lot'u yuvarlama ile 0'a düşürebilir.**

### En Kötü Senaryo (Tüm Çarpanlar Kümülatif)
```
1.4 (ham lot)
× 0.75 (1 kayıp graduated) = 1.05
× 0.7 (bias nötr) = 0.735
→ floor(0.735) = 0 ← SIFIR
```

---

## 5. İŞLEM SAATLERİ KISITMASI

### risk_ok=True Olduğunda
```
risk_ok=True başlangıç: 17:18:46
İşlem kapanış: 17:45
Kullanılabilir pencere: ~27 dakika
```

- Bu 27 dakikada M15 mum kapanışı beklenmeli (sinyal sadece M15 kapanışta)
- 17:00-17:45 arası `LAST_45_MIN` seans filtresi → strength × 0.5
- Son 45 dakikada kalan tek şans: 17:30 M15 kapanışı

---

## 6. M15 MUM VERİSİ SORUNU

### Kanıt
```
Yeni M15 mum kapanışı tespit edildi: 2026-03-06 18:00:00
```

- Tespit edilen mum **6 Mart 18:00** — dünün son mumu
- 7 Mart'ta piyasa açıldığında yeni M15 verisi DataPipeline tarafından gelmiyor olabilir
- risk_ok=True olduğu 17:18'den sonra da mum hâlâ dünden → sinyal üretimi tetiklenmiyor

---

## TAM ENGELLEYİCİ ZİNCİRİ (Akış Şeması)

```
Engine Başlat (01:17)
    ↓
restore_risk_state() → L2 geri yükle (6 Mart'tan)
    ↓
09:30 _reset_daily() → L2 temizle
    ↓
10 sn sonra check_risk_limits() → daily_loss hâlâ ≥%1.8 → L2 tekrar aktif!
    ↓
[851 cycle boyunca risk_ok=False → sinyal üretilemez]
    ↓
17:18 Yeni engine başlatma (RISK_BASELINE_DATE güncel)
    ↓
risk_ok=True AMA:
    ├── İşlem saati: sadece 27 dk kaldı
    ├── M15 mum: dünün mumu, yeni mum gelmiyor
    ├── Rejim: RANGE (ADX=30.4 ile çelişkili)
    ├── Mean Reversion: ADX≥20 → BLOK
    ├── Breakout: hacim+ATR koşulları karşılanmıyor
    ├── Top5: sadece 2 kontrat
    └── Lot: kümülatif çarpanlar → floor(0) riski
    ↓
SONUÇ: Sıfır işlem
```

---

## DEĞERLENDİRME

### Hata mı, Tasarım mı?
| Durum | Tipi | Açıklama |
|-------|------|----------|
| Kill-Switch L2 kısır döngüsü | **HATA** | Günlük sıfırlama → hemen tekrar tetikleme döngüsü |
| ADX=30.4 + RANGE rejimi | **Tasarım** | Oylama sistemi bireysel sembollere bakıyor, ADX ortalamayla çelişebilir |
| Mean Reversion ADX<20 koşulu | **Tasarım** | RANGE'de ADX>20 olunca MR bloklanıyor — boşluk |
| Sadece 2/5 Top5 | **Tasarım** | Puan eşikleri sıkı olabilir |
| Lot floor(0) | **HATA** | Kümülatif çarpanlar sonrası vol_step yuvarlaması |
| ENTRY_LOT_FRACTION=0.5 | **Tasarım** | Ama düşük lot'ta sıfıra düşürüyor |
| M15 mum verisi eski | **Olası HATA** | Pipeline 17:18 sonrası yeni veri çekemiyor olabilir |

---

## ÇÖZÜM ÖNERİLERİ

### P0 — Kritik (Hemen)
1. **Kill-Switch L2 Kısır Döngü:** RISK_BASELINE_DATE'i otomatik güncelle veya _reset_daily sonrası bir "grace period" ekle
2. **Lot floor(0) Koruması:** vol_step yuvarlaması sonrası lot=0 ise vol_min'e yükselt (en az 1 lot garantisi)

### P1 — Önemli (Kısa Vadede)
3. **ADX Boşluğu:** RANGE rejiminde Mean Reversion için ADX eşiğini yumuşat (20→25) veya RANGE rejiminde de Trend Follow izin ver
4. **ENTRY_LOT_FRACTION Dinamik:** Equity yüksekse 0.5, düşükse 1.0 (her zaman en az 1 lot)
5. **Top 5 Minimum:** En az 3 kontrat garanti et

### P2 — İyileştirme
6. **Bias-lot nötr çarpanı:** 0.7 → 0.85 (daha az lot kaybı)
7. **Rejim oylama + ADX uyumu:** Ortalama ADX ile rejim kararını çapraz kontrol et
