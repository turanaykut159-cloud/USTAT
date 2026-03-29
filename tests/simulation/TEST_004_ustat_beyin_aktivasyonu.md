# TEST_004 — ÜSTAT Beyin Modülleri Aktivasyonu

| Alan | Değer |
|------|-------|
| **Tarih** | 2026-03-21 ~21:10 |
| **Modül** | `engine/simulation.py` |
| **Cycle** | 300 |
| **Hız** | 0 (hızlı mod) |
| **Amaç** | ÜSTAT beyin modüllerinin (hata ataması, ertesi gün analizi, regülasyon önerisi) simülasyonda aktif olmasının doğrulanması |

## Ne İçin Yapıldı

TEST_003'te tüm ÜSTAT beyin modülleri 0 çıkıyordu:
- Hata ataması: 0
- Ertesi gün analizi: 0
- Regülasyon önerisi: 0

Araştırma sonucu 3 kök neden tespit edildi:

1. **Hata ataması** → DB'de kaybeden işlem (pnl < 0) yok. MockMT5Bridge SL/TP kapanışlarını DB'ye kaydetmiyordu.
2. **Ertesi gün analizi** → "Önceki iş günü"nden kapanmış işlem yok. Simülasyon tek gün içinde çalışıyordu (hep aynı tarih).
3. **Regülasyon önerisi** → İlk iki modülden veri gelmediği için tetiklenmiyordu.

## Düzeltmeler (TEST_003 → TEST_004)

### 1. MockMT5Bridge'e DB Referansı
- `__init__` parametresine `db=None` eklendi
- `_time_fn` parametresi: simüle edilmiş zaman fonksiyonu
- SL/TP kapanışında `_record_closed_trade()` çağrılıyor

### 2. `_record_closed_trade()` Metodu (Yeni)
```
Kapanan pozisyon → DB'ye insert_trade() ile yazılıyor:
  - entry_time: pozisyon açılış zamanı (simüle edilmiş)
  - exit_time: kapanış zamanı (simüle edilmiş)
  - exit_reason: "SL_HIT" veya "TP_HIT" (ÜSTAT uyumlu)
  - pnl: gerçekleşen kar/zarar
```

### 3. Çok Günlü Simülasyon
- `_SimDatetime` artık cycle'a göre gün ilerletiyor
- Her `CYCLES_PER_DAY` cycle = 1 iş günü (hafta sonları atlanıyor)
- ÜSTAT modülüne de datetime monkey-patch uygulandı
- Gün değişikliği konsolda gösteriliyor

### 4. Sentetik Geçmiş İşlemler
- `_seed_historical_trades()` metodu eklendi
- Simülasyon başlamadan önce 5 iş günü geriye 20-30 işlem ekleniyor
- %60 kaybeden / %40 kazanan dağılımı
- Risk olayları da ekleniyor (DRAWDOWN_WARNING)

### 5. Exit Reason Uyumluluğu
- Eski: `"STOP_LOSS"`, `"TAKE_PROFIT"` → ÜSTAT tanımıyor
- Yeni: `"SL_HIT"`, `"TP_HIT"` → `_determine_fault()` tarafından tanınıyor

## Test Çalıştırma Komutu

```bash
python -m engine.simulation --cycles 300 --speed 0
```

## Sonuç

| Metrik | Değer |
|--------|-------|
| Başarılı cycle | 300/300 ✅ |
| Simüle edilen gün | 6 iş günü (60 cycle/gün) |
| Tarih aralığı | 2026-03-16 → 2026-03-21 |
| Sentetik geçmiş | 24 işlem DB'ye eklendi |
| Sinyal üretimi | 1 |
| SL kapanış | 1 ✅ (F_SOKM BUY, SL_HIT, -46.82 TL) |
| TP kapanış | 0 |
| **Hata ataması** | **1** ✅ (önceki: 0) |
| **Ertesi gün analizi** | **1** ✅ (ilk gün 13, önceki: 0) |
| **Kontrat profili** | **12** ✅ (önceki: 0) |
| Regülasyon önerisi | 0 (≥2 BABA hatası gerekli) |
| Son bakiye | 9,953.18 TL (-0.47%) |
| Durum | ✅ BAŞARILI — 3 beyin modülünden 2'si aktif |

## Gün Bazında Akış

```
📅 2026-03-16 (cycle 1-59):
   - Engine başlatıldı
   - F_SOKM BUY 1.00 lot @ 32.26 açıldı
   - F_SOKM SL_HIT @ 31.79 → -46.82 TL
   - Trade DB'ye kaydedildi

📅 2026-03-17 (cycle 60-119):
   - Ertesi gün analizi: 1 işlem analiz edildi ✅
   - Hata ataması: F_SOKM SL_HIT → OĞUL hatası ✅

📅 2026-03-18 → 2026-03-21:
   - Ek sinyal üretilmedi (OĞUL kalite filtreleri)
   - Kontrat profilleri güncellendi
```

## Kalan Sorunlar

1. **Regülasyon önerisi = 0**: 2+ BABA hatası veya 3+ OĞUL hatası gerekiyor. Tek bir SL kapanışı yeterli değil.
2. **Sinyal frekansı düşük**: 300 cycle'da 1 sinyal. OĞUL'un kalite filtreleri (PA confluence, MTF, H1 confirmation) sentetik fiyat verileriyle düşük puan üretiyor.
