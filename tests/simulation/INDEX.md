# ÜSTAT Simülasyon Test İndeksi

> Son güncelleme: 2026-03-22

## Klasör Yapısı

```
tests/simulation/
├── INDEX.md                              ← Bu dosya
├── TEST_001_ilk_calistirma.md            ← İlk çalıştırma ve import hataları
├── TEST_002_temel_dongu.md               ← Temel döngü doğrulama
├── TEST_003_sinyal_uretimi.md            ← Sinyal üretimi ve TP kapanış
├── TEST_004_ustat_beyin_aktivasyonu.md   ← ÜSTAT beyin modülleri
├── TEST_005_tam_dogrulama_500.md         ← 500 cycle tam doğrulama
├── TEST_006_xu30_thyao_akbnk.md          ← 3 sembol tam katman testi
├── test_006_runner.py                    ← TEST_006 scripti
├── TEST_006_results.json                 ← TEST_006 JSON verisi
├── TEST_007_ogul_pipeline_fix.md         ← OĞUL pipeline düzeltme testi
├── test_007_runner.py                    ← TEST_007 scripti
├── TEST_007_results.json                 ← TEST_007 JSON verisi
├── TEST_008_results.json                 ← TEST_008 JSON verisi
└── test_008_runner.py                    ← TEST_008 scripti (v13.0 doğrulama)
```

## Test Özet Tablosu

| # | Test | Tarih | Cycle | Sonuç | Önemli Bulgular |
|---|------|-------|-------|-------|-----------------|
| 001 | İlk Çalıştırma | 2026-03-21 ~19:30 | 50 | ❌ BAŞARISIZ | MT5 import, DB lock, method signature hataları |
| 002 | Temel Döngü | 2026-03-21 ~20:00 | 50 | ⚠️ KISMI | Döngü çalışıyor ama VOLATILE rejim → 0 sinyal |
| 003 | Sinyal Üretimi | 2026-03-21 ~20:30 | 200 | ✅ BAŞARILI | 2 sinyal, 1 TP kapanış (+267 TL), SL/TP çalışıyor |
| 004 | ÜSTAT Beyin | 2026-03-21 ~21:10 | 300 | ✅ BAŞARILI | Hata ataması=1, Ertesi gün=1, Kontrat profili=12 |
| 005 | Tam Doğrulama | 2026-03-21 21:38 | 500 | ✅ BAŞARILI | 2 TP, ertesi gün=2, 6 iş günü, 8 rejim değişikliği |
| 006 | XU30+THYAO+AKBNK | 2026-03-21 22:08 | 2800 | ⚠️ KISMI | 4/5 katman ✅, OĞUL %0.7 (pipeline 12 sembol hatası) |
| 007 | OĞUL Pipeline Fix | 2026-03-21 23:01 | 2800 | ✅ BAŞARILI | **5/5 katman ✅**, OĞUL %99.9, regülasyon önerisi ilk kez aktif |
| 008 | v13.0 İyileştirmeler | 2026-03-22 00:23 | 2800 | ✅ BAŞARILI | **5/5 katman ✅ 0 hata**, R-Multiple + DD + Pyramid + Chandelier + MaxHold |

## Düzeltme Zinciri

```
TEST_001 → MT5 mock enjeksiyonu, ayrı DB, method imzaları
    ↓
TEST_002 → PriceGenerator persistent history, paper_mode=False, monkey-patches
    ↓
TEST_003 → send_order imza düzeltme, SL/TP execution, datetime override
    ↓
TEST_004 → DB kayıt, çok günlü tarih, sentetik geçmiş, exit_reason uyumu
    ↓
TEST_005 → Bütünleşik doğrulama (tüm modüller birlikte)
    ↓
TEST_006 → 3 sembol, 56 iş günü, standalone runner, OĞUL pipeline sorunu tespit
    ↓
TEST_007 → WATCHED_SYMBOLS override, eksik metot ekleme, fiyat drift kalibrasyonu
    ↓
TEST_008 → v13.0: R-Multiple, Aylık DD, Piramitleme, Chandelier Exit, Max Hold Süresi
```

## Metrik Gelişim Grafiği

```
                TEST_001  TEST_002  TEST_003  TEST_004  TEST_005  TEST_006  TEST_007  TEST_008
Başarılı cycle    0/50     50/50    200/200   300/300   500/500   ---*     2800/2800 2800/2800
OĞUL cycle          -        -        -         -         -     19/2800  2797/2800 2800/2800
Sinyal sayısı       0        0        2         1         1        1         3         0**
TP kapanış          -        -        1         0         2        1         0         0
SL kapanış          -        -        0         1         0        0         1         0
Hata ataması        -        -        0         1         0        1         3         2
Ertesi gün          -        -        0         1         2        5         1         4
Regülasyon          -        -        0         0         0        0         1 ✅      2
Kontrat profili     -        -        0        12        13        3         3         3
v13.0 Modüller      -        -        -         -         -        -         -      5/5 ✅

* TEST_006: BABA/H-Engine/Manuel/ÜSTAT 2800/2800, OĞUL 19/2800
** TEST_008: Sentetik veri PA confluence eşiği — tüm v13.0 modülleri hatasız entegre
```

## Kalan Test İhtiyaçları

1. ~~**Uzun simülasyon (2700+ cycle)**: Tam backtest senaryosu~~ ✅ TEST_006/007 (2800 cycle)
2. **Yüksek volatilite testi**: `--volatile` flag ile OLAY rejimi dominasyonu
3. ~~**Regülasyon önerisi testi**: 2+ BABA hatası oluşana kadar çalıştırma~~ ✅ TEST_007 (1 öneri)
4. **Çoklu paralel koşu**: Başlangıç koşullarına duyarlılık analizi
5. **Performans testi**: Cycle/saniye metriği, bellek kullanımı
6. **Fiyat drift kalibrasyonu**: F_AKBNK +55%, F_XU030 +79% hâlâ gerçek dışı
7. **Sinyal frekansı iyileştirmesi**: 2800 cycle'da 3 sinyal — OĞUL filtreleri çok sıkı
