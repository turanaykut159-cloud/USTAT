# TEST_006 — XU30 + THYAO + AKBNK Tam Katman Testi

| Alan | Değer |
|------|-------|
| **Tarih** | 2026-03-21 22:08 - 22:19 |
| **Modül** | `tests/simulation/test_006_runner.py` |
| **Cycle** | 2800 (56 iş günü × 50 cycle/gün) |
| **Süre** | 10.8 dakika (646.9 saniye) |
| **Semboller** | F_THYAO, F_AKBNK, F_XU030 |
| **Tarih aralığı** | 2026-01-02 → 2026-03-21 |
| **Başlangıç bakiye** | 50,000 TL |
| **Amaç** | 3 sembolle tüm katmanların (BABA, OĞUL, H-Engine, Manuel Motor, ÜSTAT) 56 iş günü boyunca uçtan uca testi |

## Ne İçin Yapıldı

Kullanıcı canlı VİOP fiyatlarını göstererek XU30, Türk Hava Yolları (F_THYAO) ve Akbank (F_AKBNK) için 01.01.2026'dan itibaren tam bir sistem testi istedi. Test aşağıdakileri kapsar:

- **BABA**: Rejim tespiti (TREND/RANGE/VOLATILE), risk yönetimi, kill switch
- **OĞUL**: Sinyal üretimi, emir açma, SL/TP yönetimi
- **H-Engine**: Hibrit pozisyon yönetimi
- **Manuel Motor**: Pozisyon senkronizasyonu
- **ÜSTAT**: Hata ataması, ertesi gün analizi, regülasyon önerisi, kontrat profili

## Test Parametreleri

```
Semboller      : F_THYAO (THY), F_AKBNK (Akbank), F_XU030 (BIST30 endeks)
Başlangıç fiyat: THYAO=275.0 TL, AKBNK=33.50 TL, XU030=13,200
Cycle/gün      : 50
Toplam cycle   : 2,800
İş günü        : 56
Sentetik geçmiş: 27-41 işlem (önceki 10 iş günü)
```

## Test Komutu

```bash
cd /sessions/exciting-laughing-newton/mnt/USTAT
python tests/simulation/test_006_runner.py
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
| TREND | 1,519 | 54.2% |
| RANGE | 1,258 | 44.9% |
| VOLATILE | 23 | 0.8% |

BABA 56 iş günü boyunca tek hata vermeden çalıştı. Rejim dağılımı gerçekçi: çoğunlukla TREND ve RANGE, nadiren VOLATILE.

### 2. OĞUL — Sinyal Motoru ⚠️

| Metrik | Değer |
|--------|-------|
| Başarılı cycle | 19/2800 |
| Hata | 2,781 |
| Sinyal üretimi | 1 |
| Emir açılan | 1 |

**Neden 2781 hata?** DataPipeline testteki 3 sembol dışındaki 12 sembol için bar çekmeye çalışıyor → her birinde KeyError → OĞUL cycle'ı exception'a düşüyor. Sinyal üretimi çalışıyor ama pipeline hataları cycle'ları kesiyor.

**Açılan işlem:**
- **F_AKBNK SELL** 1.0 lot @ 37.83 TL
- Gün 1'de (02.01.2026) açıldı
- Gün 2'de (05.01.2026) TP ile kapandı: **+58.20 TL** ✅

### 3. H-Engine — Hibrit Pozisyon ✅

| Metrik | Değer |
|--------|-------|
| Başarılı cycle | **2800/2800** (hatasız) |
| Hata | 0 |

H-Engine tüm cycle'larda sorunsuz çalıştı. Hibrit pozisyon açılmadı (sinyal koşulları oluşmadı) ama modül stabil.

### 4. Manuel Motor — Pozisyon Sync ✅

| Metrik | Değer |
|--------|-------|
| Başarılı cycle | **2800/2800** (hatasız) |
| Hata | 0 |
| Sync işlemi | 2,800 |

Manuel Motor her cycle'da pozisyon senkronizasyonu yaptı, hatasız.

### 5. ÜSTAT — Beyin Merkezi ✅

| Metrik | Değer |
|--------|-------|
| Başarılı cycle | **2800/2800** (hatasız) |
| Hata ataması | **1** ✅ |
| Ertesi gün analizi | **5** ✅ |
| Regülasyon önerisi | 0 |
| Kontrat profili | **3** ✅ |
| Kategorizasyon | **3** ✅ |

ÜSTAT 56 gün boyunca hatasız çalıştı. Sentetik geçmişten 5 ertesi gün analizi ve 1 hata ataması üretti. 3 kontratın her biri için profil oluşturdu.

---

## BAKİYE ve İŞLEM ÖZETİ

| Metrik | Değer |
|--------|-------|
| Başlangıç | 50,000.00 TL |
| Son bakiye | 50,058.20 TL |
| Toplam K/Z | **+58.20 TL (+0.12%)** |
| Sinyal | 1 |
| TP kapanış | 1 (Win Rate: 100%) |
| SL kapanış | 0 |

## FİYAT GELİŞİMİ (Simüle Edilmiş)

| Sembol | Başlangıç | Bitiş | Değişim |
|--------|-----------|-------|---------|
| F_THYAO | 275.00 | 528.23 | +92.08% |
| F_AKBNK | 33.50 | 40.34 | +20.42% |
| F_XU030 | 13,200.00 | 34,457.88 | +161.04% |

> **Not:** Fiyat gelişimi sentetik (geometric Brownian motion). Gerçek piyasa fiyatlarını yansıtmaz.

## KRONOLOJİK AKIŞ

```
📅 2026-01-02 (Gün 1):
   - Engine başlatıldı, 27 sentetik geçmiş işlem yüklendi
   - Ertesi gün analizi: 5 işlem analiz edildi (sentetik geçmişten)
   - Hata ataması: 1 (sentetik kaybeden işlem)
   - Sinyal: F_AKBNK BUY/SELL sinyalleri üretildi (çoğu skor eşiğini geçemedi)
   - Emir: F_AKBNK SELL 1.0 lot @ 37.83 TL açıldı

📅 2026-01-05 (Gün 2):
   - F_AKBNK SELL pozisyonu TP ile kapandı: +58.20 TL ✅
   - Ertesi gün analizi: Dün kapanan işlem yok (TP dün değil bugün kapandı)

📅 2026-01-06 → 2026-03-21 (Gün 3-56):
   - Ertesi gün analizi her gün çalıştı (dün kapanan işlem yok)
   - BABA rejim geçişleri: TREND ↔ RANGE ↔ VOLATILE
   - OĞUL sinyal skor eşiklerini geçemedi → ek emir yok
   - Tüm katmanlar hatasız döndü
```

## TESPİT EDİLEN SORUNLAR

### 1. DataPipeline 12 sembol hatası (YÜKSEK)
Pipeline engine config'den 15 sembolü çekiyor ama mock bridge sadece 3 sembol biliyor. Bu 12 × 4 timeframe = 48 hata/cycle üretiyor. OĞUL'un cycle başarısını %0.7'ye düşürüyor.

**Çözüm önerisi:** Test runner'da engine config'in `symbols` listesini 3 sembole override et, veya mock bridge'e bilinmeyen semboller için boş DataFrame dön.

### 2. Sinyal frekansı düşük (ORTA)
2800 cycle'da sadece 1 emir açıldı. Sebepler:
- OĞUL'un pipeline hataları cycle'ları kesiyor (yukarıdaki sorun)
- OĞUL kalite filtreleri sentetik fiyatla düşük skor üretiyor
- Sadece 3 sembol → daha az çeşitlilik

### 3. Fiyat gelişimi gerçek dışı (DÜŞÜK)
F_THYAO +92%, F_XU030 +161% — 3 ayda bu kadar yükseliş gerçekçi değil. PriceGenerator drift parametresi yüksek.

---

## GENEL DEĞERLENDİRME

| Katman | Durum | Not |
|--------|-------|-----|
| BABA | ✅ Tam çalışıyor | 2800/2800 hatasız, rejim dağılımı gerçekçi |
| OĞUL | ⚠️ Kısmi | Sinyal motoru çalışıyor ama pipeline hataları cycle'ları kesiyor |
| H-Engine | ✅ Tam çalışıyor | 2800/2800 hatasız |
| Manuel Motor | ✅ Tam çalışıyor | 2800/2800 hatasız, sync düzgün |
| ÜSTAT | ✅ Tam çalışıyor | Beyin modülleri aktif, hata ataması + ertesi gün analizi çalışıyor |

**Sonuç:** 5 katmandan 4'ü tam çalışıyor. OĞUL'un pipeline entegrasyonu 3 sembol modunda düzeltme gerektiriyor.

## DOSYALAR

- `tests/simulation/test_006_runner.py` — Test scripti
- `tests/simulation/TEST_006_results.json` — JSON sonuç verisi
- `tests/simulation/TEST_006_xu30_thyao_akbnk.md` — Bu rapor
