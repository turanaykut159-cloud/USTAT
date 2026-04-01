# Oturum Raporu — Otonom Vade Geçiş Sistemi

**Tarih:** 1 Nisan 2026
**Konu:** #105 — 4 Katmanlı Otonom Vade Geçiş Sistemi
**Commit:** 34ded93
**Versiyon:** v5.9.0 (artış gerekmedi — %0.44 değişiklik oranı)

---

## 1. Sorun Tanımı

31 Mart 2026 VİOP vadesi sona erdi. 1 Nisan sabahı sistem eski vade kontratlarına (0326) eşlendi. GCM bu kontratları CLOSE_ONLY moduna almıştı — `symbol_select()` başarılı dönüyor ama emir gönderildiğinde MT5 retcode=10044 ("Only position closing is allowed") ile reddediyordu. F_BRSAN ve F_AKBNK'ta toplam 4 emir reddedildi.

## 2. Kök Sebep Zinciri

| # | Sorun | Detay |
|---|-------|-------|
| 1 | trade_mode kontrolü yok | `_resolve_symbols()` sadece `symbol_select()` başarısına bakıyor, kontratın CLOSE_ONLY olup olmadığını kontrol etmiyor |
| 2 | Vade günü mantığı | `_next_expiry_suffix()` sadece tam vade gününde çalışıyor — 1 Nisan'da None dönüyor |
| 3 | Alfabetik sıralama | YÖNTEM 2'de adaylar isimle sıralanıyor: F_AKBNK0326 < F_AKBNK0426 → eski vade önce seçiliyor |
| 4 | EXPIRY_DAYS=0 | BABA'da vade koruma tamamen kapalı — OLAY rejimi vade günlerinde tetiklenmiyor |
| 5 | Günde 1 kez resolve | `_resolve_symbols()` günde 1 kez çalışıyor — gün içi kontrat değişimlerini yakalamıyor |

## 3. Yapılan Değişiklikler

### Faz 1: trade_mode Kontrolü (mt5_bridge.py)
- `_resolve_symbols()` YÖNTEM 1 (vade günü): Hedef kontratın `trade_mode >= 4` (FULL) olup olmadığı kontrol ediliyor
- `_resolve_symbols()` YÖNTEM 2 (normal gün): Her aday için `trade_mode < 4` ise atlanıyor, FULL olan ilk kontrat seçiliyor
- Hiçbir aday FULL değilse → fallback + ERROR log

### Faz 2: Retcode 10044 Reaktif Handler (mt5_bridge.py)
- `send_order()` içinde retcode 10044 (CLOSE_ONLY) ve 10017 (TRADE_DISABLED) yakalanıyor
- Anında `_resolve_symbols()` tetikleniyor
- Event bus'a `VADE_UYARI` event'i emit ediliyor

### Faz 3: Periyodik trade_mode Tarama (mt5_bridge.py + main.py)
- Yeni `check_trade_modes()` metodu: Mevcut symbol_map'teki tüm kontratları sorgulayıp CLOSEONLY/DISABLED olanları tespit ediyor
- `_run_single_cycle()` içinde 1 saatlik aralıkla çağrılıyor
- Tespit edilirse otomatik re-resolve başlatılıyor

### Faz 4: Takvim Düzeltmesi (baba.py + time_utils.py)
- `VIOP_EXPIRY_DATES` Mayıs 2026: `date(2026, 5, 29)` → `date(2026, 5, 25)` düzeltildi
  - Neden: 26 Mayıs Kurban Bayramı arefesi (yarım gün). VİOP kuralı: yarım gün = önceki iş günü
- `time_utils.py`: `ALL_HALF_DAYS` seti (2025-2027 arefe günleri) eklendi
- `is_half_day()`, `get_close_time()` fonksiyonları eklendi
- `is_market_open()` arefe günü 12:40 kapanış desteği eklendi
- `validate_expiry_dates()` yarım gün kontrolü eklendi
- `HOLIDAYS_2026` düzeltildi: Ramazan 19 Mart arefe olarak ayrıldı, Kurban 27-30 Mayıs olarak güncellendi

### Faz 5: Eski Vade Pozisyon Koruması (mt5_bridge.py)
- Yeni `_check_stale_positions()` metodu: MT5'teki açık pozisyonların aktif symbol_map ile eşleşip eşleşmediğini kontrol ediyor
- Eski vadede kalan pozisyonlar tespit edilirse ERROR log + `STALE_POSITION` event emit ediliyor

## 4. Mimari: 4 Katmanlı Koruma

```
K1 (Proaktif)  : _resolve_symbols() → trade_mode>=4 kontrolü
K2 (Dedektif)  : check_trade_modes() → saatlik tarama
K3 (Reaktif)   : send_order() → retcode 10044 handler
K4 (Informatif): VIOP_EXPIRY_DATES + yarım gün takvimi
```

## 5. Değişiklik Listesi

| Dosya | Bölge | Değişiklik |
|-------|-------|------------|
| `engine/mt5_bridge.py` | Kırmızı | trade_mode kontrolü, 10044 handler, check_trade_modes(), _check_stale_positions() |
| `engine/main.py` | Kırmızı | Saatlik trade_mode tarama çağrısı |
| `engine/baba.py` | Kırmızı | Mayıs 2026 tarih düzeltme, validate_expiry_dates() yarım gün |
| `engine/utils/time_utils.py` | Sarı | HALF_DAYS setleri, is_half_day(), get_close_time(), is_market_open() güncelleme |
| `tests/test_1000_combinations.py` | Yeşil | Ramazan testi yarım gün beklentisine güncellendi |

## 6. Test Sonuçları

- **401 test PASSED** (test_unit_core + test_ogul_200 + test_1000_combinations)
- 6 hybrid test failure: pre-existing (PRIMNET faz geçiş mantığıyla ilgili, bu değişiklikle ilgisiz)
- Build: 0 hata (chunk size uyarısı mevcut)

## 7. Geri Alma

```bash
git revert 34ded93 --no-edit
```

## 8. Araştırma Bulguları

### GCM VİOP Rollover
- GCM otomatik pozisyon rollover YAPMIYOR (Forex/CFD'den farklı)
- Eski kontrat CLOSE_ONLY'ye geçer, yeni kontrat MT5'te otomatik listelenir
- Zamanlaması broker'a bağlı (genellikle vade günü veya 1-2 gün önce)

### MT5 API
- `symbol_info().trade_mode`: 0=DISABLED, 3=CLOSEONLY, 4=FULL — broker gerçek zamanlı günceller
- `symbol_info().expiration_time`: Unix timestamp (GCM dolduruyor mu test edilmeli)
- Retcode 10044 = TRADE_RETCODE_CLOSE_ONLY

### 2026 Kritik Tarihler
- **Mayıs 2026**: Kurban Bayramı 27-30 Mayıs, arefe 26 Mayıs → VİOP son işlem **25 Mayıs Pazartesi** (7 gün boşluk!)
- Ramazan Bayramı arefesi: 19 Mart 2026 (yarım gün)
- Cumhuriyet Bayramı arefesi: 28 Ekim 2026 (yarım gün)
