# Oturum Raporu — v13.0 İşlem Yönetimi İyileştirmeleri

**Tarih:** 2026-03-22
**Commit:** e6fed7e
**Versiyon:** v5.7 (değişmedi, oran %2.2 < %10)

---

## Yapılan İş Özeti

Dünya standartlarında kanıtlanmış 3 trade management sistemiyle (Turtle Trading, Van Tharp R-Multiple, Alexander Elder Triple Screen) yapılan derin araştırma ve karşılaştırma analizinden doğan 5 eksikliğin OĞUL motoruna entegrasyonu.

## Değişiklik Listesi

| Dosya | Değişiklik |
|-------|-----------|
| `engine/models/trade.py` | 7 yeni alan: initial_risk, r_multiple, r_multiple_at_close, pyramid_count, pyramid_prices, max_hold_warned |
| `engine/ogul.py` | +35 sabit, +12 instance değişken, 5 yeni modül entegrasyonu (~250 satır yeni kod) |
| `engine/ogul.py` — `_manage_position` | 1b. R-Multiple, 1c. Max Hold, 6. Chandelier hibrit, 9. Piramitleme |
| `engine/ogul.py` — `_check_pyramid_add` (YENİ) | Turtle-style piramitleme metodu |
| `engine/ogul.py` — `_check_advanced_risk_rules` | Aylık drawdown kontrolü (%4/%6) |
| `engine/ogul.py` — `_execute_signal` | 1R hesaplama + aylık DD engeli |
| `engine/ogul.py` — `_handle_closed_trade` | R-Multiple kapanış + expectancy |
| `tests/simulation/test_008_runner.py` (YENİ) | v13.0 doğrulama testi |
| `tests/simulation/INDEX.md` | TEST_008 kaydı |
| `docs/USTAT_v5_gelisim_tarihcesi.md` | #58 girişi |
| `RAPORLAR/` (YENİ klasör) | 2 DOCX rapor |

## 5 İyileştirme Detayları

### 1. R-Multiple Takip Sistemi (YÜKSEK)
- Kaynak: Van Tharp R-Multiple Sistemi
- 1R = |giriş - SL| × lot × kontrat
- -2R felaket koruma (anında kapat), -1.5R uyarı (trailing sıkılaştır)
- Expectancy: (WR × Avg Win R) - (LR × 1R)

### 2. Aylık Drawdown Limiti (YÜKSEK)
- Kaynak: Turtle Trading drawdown kuralı
- %4 uyarı → yeni işlem engeli
- %6 mutlak stop → tüm pozisyonlar kapatılır
- Ay değişiminde otomatik sıfırlama

### 3. Piramitleme (ORTA)
- Kaynak: Turtle Trading piramitleme kuralı
- 0.5×ATR adım, max 3 ekleme (toplam 4 katman)
- Oylama 3/4+ aynı yönde gerekli
- Her eklemede SL yeni entry - 2N'ye taşınır

### 4. Chandelier Exit (ORTA)
- Kaynak: Chuck LeBeau / Alexander Elder
- 22-bar HH - 3×ATR (long), LL + 3×ATR (short)
- %30 Chandelier + %70 mevcut trailing hibrit karışım
- R-Multiple uyarısında trailing %30 sıkılaştırma

### 5. Maksimum Pozisyon Süresi (DÜŞÜK)
- 96 M15 bar = 24 saat (1.5 işlem günü)
- Kârdaysa kapat, zarardaysa SL breakeven'e çek

## TEST_008 Sonuçları

- 2800 cycle, 56 iş günü, 3 sembol
- BABA: 2800/2800 (0 hata)
- OĞUL: 2800/2800 (0 hata)
- H-Engine: 2800/2800 (0 hata)
- Manuel: 2800/2800 (0 hata)
- ÜSTAT: 2800/2800 (0 hata)
- Süre: 662.7s (11 dk)

## Skor Gelişimi

- Önceki: 69/90 (ÜSTAT v12)
- Güncel: **82/90** (ÜSTAT v13.0)
- Artış: **+13 puan**

## Versiyon Durumu

- Değişiklik oranı: (905 + 357) / 57113 = %2.2
- %10'un altında → versiyon artışı gerekmedi
- Mevcut versiyon: v5.7

## Build Sonucu

- Masaüstü build gerekmedi (engine-only değişiklik)
- Python syntax doğrulama: ✅ OK (ogul.py, trade.py)
- TEST_008 entegrasyon: ✅ 0 hata
