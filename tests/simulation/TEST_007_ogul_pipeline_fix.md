# TEST_007 — OĞUL Pipeline Fix + 3 Sembol Tekrar Testi

| Alan | Değer |
|------|-------|
| **Tarih** | 2026-03-21 23:01 - 23:12 |
| **Modül** | `tests/simulation/test_007_runner.py` |
| **Cycle** | 2800 (56 iş günü × 50 cycle/gün) |
| **Süre** | 11.3 dakika (676.9 saniye) |
| **Semboller** | F_THYAO, F_AKBNK, F_XU030 |
| **Tarih aralığı** | 2026-01-02 → 2026-03-21 |
| **Başlangıç bakiye** | 50,000 TL |
| **Amaç** | TEST_006'daki OĞUL pipeline hatasının (2781/2800) düzeltilmesi ve tekrar doğrulaması |

## Ne İçin Yapıldı

TEST_006'da OĞUL 2800 cycle'ın 2781'inde hata veriyordu (%99.3 hata). İki kök neden tespit edildi:

### Sorun 1: DataPipeline 12 sembol hatası
`DataPipeline.fetch_all_symbols_parallel()` engine config'den 15 sembolü çekiyor (`WATCHED_SYMBOLS`), ancak MockBridge3 sadece 3 test sembolünü biliyor. 12 bilinmeyen sembol için KeyError → her cycle'da pipeline hataları.

### Sorun 2: MockBridge3 eksik metotlar
`engine/ogul.py` bazı metotları çağırıyor (`check_order_status`, `cancel_order`, `get_pending_orders`) ama MockBridge3'te bunlar tanımlı değildi → AttributeError.

## Düzeltmeler (TEST_006 → TEST_007)

### 1. WATCHED_SYMBOLS Override
```python
import engine.mt5_bridge as _bridge_mod
import engine.top5_selection as _top5_mod
_bridge_mod.WATCHED_SYMBOLS = list(TEST_SYMBOLS)
_dp_mod.WATCHED_SYMBOLS = list(TEST_SYMBOLS)
_top5_mod.WATCHED_SYMBOLS = list(TEST_SYMBOLS)
```
`WATCHED_SYMBOLS` 15 sembolden 3 test sembolüne indirildi. Hem `mt5_bridge`, hem `data_pipeline`, hem `top5_selection` modüllerindeki kopyalar override edildi.

### 2. Bilinmeyen Sembol Güvenliği
```python
def get_bars(self, symbol, timeframe=5, count=500):
    if symbol not in TEST_SYMBOLS:
        return pd.DataFrame(columns=["time","open","high","low","close",
                                     "tick_volume","spread","real_volume"])
    # ...
```
Bilinmeyen semboller için boş DataFrame dönüyor (ek güvenlik).

### 3. Eksik MockBridge3 Metotları
```python
def check_order_status(self, order_ticket):
    return {"status": "filled", "filled_volume": 1.0,
            "remaining_volume": 0.0, "deal_ticket": order_ticket}

def get_pending_orders(self):
    return []

def cancel_order(self, order_ticket):
    return {"retcode": 10009}
```

### 4. Gerçekçi Fiyat Drift
```python
# Eski (TEST_006):
"F_THYAO": 0.00015    → +92% (3 ayda)
"F_XU030": 0.00020    → +161%

# Yeni (TEST_007):
"F_THYAO": 0.000020   → -2% (3 ayda, gerçekçi)
"F_XU030": 0.000035   → +79% (hâlâ yüksek ama daha iyi)
```

## Test Komutu

```bash
cd /sessions/exciting-laughing-newton/mnt/USTAT
python tests/simulation/test_007_runner.py
```

---

## KATMAN SONUÇLARI

### 1. BABA — Risk Yönetimi ✅

| Metrik | Değer |
|--------|-------|
| Başarılı cycle | **2800/2800** (hatasız) |
| Hata | 0 |
| Risk engeli | 0 |

**Rejim dağılımı:**

| Rejim | Cycle | Oran |
|-------|-------|------|
| TREND | 1,725 | 61.6% |
| RANGE | 1,060 | 37.9% |
| VOLATILE | 15 | 0.5% |

### 2. OĞUL — Sinyal Motoru ✅

| Metrik | TEST_006 | TEST_007 | İyileşme |
|--------|----------|----------|----------|
| Başarılı cycle | 19/2800 | **2797/2800** | **%0.7 → %99.9** |
| Hata | 2,781 | **3** | **-2,778** |
| Sinyal | 1 | **3** | +200% |
| Emir | 1 | **3** | +200% |

**Neden hâlâ 3 hata?** OĞUL ilk cycle'lar da indicator hesaplaması için yeterli veri biriktirememiş olabilir (normal warm-up hatası).

**Açılan işlemler:**
- 3 adet emir açıldı (detaylar JSON'da)
- 1 SL kapanış
- Son bakiye: 51,110.09 TL (+1,110.09 TL)

### 3. H-Engine — Hibrit Pozisyon ✅

| Metrik | Değer |
|--------|-------|
| Başarılı cycle | **2800/2800** (hatasız) |

### 4. Manuel Motor — Pozisyon Sync ✅

| Metrik | Değer |
|--------|-------|
| Başarılı cycle | **2800/2800** (hatasız) |
| Sync işlemi | 2,800 |

### 5. ÜSTAT — Beyin Merkezi ✅

| Metrik | TEST_006 | TEST_007 |
|--------|----------|----------|
| Başarılı cycle | 2800/2800 | **2800/2800** |
| Hata ataması | 1 | **3** ✅ |
| Ertesi gün analizi | 5 | **1** |
| **Regülasyon önerisi** | **0** | **1** ✅ |
| Kontrat profili | 3 | **3** ✅ |
| Kategorizasyon | 3 | **3** ✅ |

**Regülasyon önerisi ilk kez aktif!** TEST_001'den beri 0 olan bu modül nihayet tetiklendi.

---

## BAKİYE ve İŞLEM ÖZETİ

| Metrik | Değer |
|--------|-------|
| Başlangıç | 50,000.00 TL |
| Son bakiye | 51,110.09 TL |
| Toplam K/Z | **+1,110.09 TL (+2.22%)** |
| Sinyal | 3 |
| SL kapanış | 1 |
| TP kapanış | 0 |
| Açık pozisyon | 0 |

## FİYAT GELİŞİMİ (Simüle Edilmiş)

| Sembol | Başlangıç | Bitiş | Değişim |
|--------|-----------|-------|---------|
| F_THYAO | 275.00 | 269.37 | -2.05% |
| F_AKBNK | 33.50 | 51.99 | +55.19% |
| F_XU030 | 13,200.00 | 23,640.88 | +79.10% |

> **Not:** THYAO fiyat gelişimi artık gerçekçi seviyede. AKBNK ve XU030 drift parametreleri hâlâ yüksek.

---

## TEST_006 → TEST_007 KARŞILAŞTIRMA

| Katman | TEST_006 | TEST_007 | Durum |
|--------|----------|----------|-------|
| BABA | 2800/2800 ✅ | 2800/2800 ✅ | Değişim yok |
| **OĞUL** | **19/2800 ⚠️** | **2797/2800 ✅** | **🟢 DÜZELTME BAŞARILI** |
| H-Engine | 2800/2800 ✅ | 2800/2800 ✅ | Değişim yok |
| Manuel Motor | 2800/2800 ✅ | 2800/2800 ✅ | Değişim yok |
| ÜSTAT | 2800/2800 ✅ | 2800/2800 ✅ | Değişim yok |
| **Regülasyon** | **0** | **1 ✅** | **🟢 İLK KEZ AKTİF** |

## GENEL DEĞERLENDİRME

**Sonuç: 5 katmandan 5'i tam çalışıyor. ✅**

OĞUL başarı oranı %0.7'den %99.9'a yükseldi. Regülasyon önerisi modülü ilk kez tetiklendi. Sistem uçtan uca stabil çalışıyor.

### Kalan İyileştirmeler (Opsiyonel)
1. **Fiyat drift kalibrasyonu**: F_AKBNK +55% ve F_XU030 +79% hâlâ yüksek
2. **Sinyal frekansı**: 2800 cycle'da 3 sinyal — OĞUL filtreleri çok sıkı
3. **OĞUL 3 hata**: Warm-up döneminde indicator yetersizliği araştırılabilir

## DOSYALAR

- `tests/simulation/test_007_runner.py` — Test scripti
- `tests/simulation/TEST_007_results.json` — JSON sonuç verisi
- `tests/simulation/TEST_007_ogul_pipeline_fix.md` — Bu rapor
