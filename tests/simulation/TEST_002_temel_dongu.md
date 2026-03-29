# TEST_002 — Temel Döngü Doğrulama

| Alan | Değer |
|------|-------|
| **Tarih** | 2026-03-21 ~20:00 |
| **Modül** | `engine/simulation.py` |
| **Cycle** | 50 |
| **Hız** | 0 (hızlı mod) |
| **Amaç** | TEST_001 hatalarının düzeltilmesinden sonra temel cycle döngüsünün uçtan uca çalışması |

## Ne İçin Yapıldı

TEST_001'de bulunan 4 kritik hata düzeltildikten sonra simülasyonun en azından cycle'ları hatasız tamamlamasını doğrulamak.

## Düzeltmeler (TEST_001 → TEST_002)

- MetaTrader5 sahte modül enjeksiyonu (tüm sabitler + stub fonksiyonlar)
- Ayrı simülasyon DB'si (`tempfile.mkdtemp`)
- `get_positions()`, `get_history_for_sync()` eklendi
- Cycle çağrı imzaları düzeltildi: `baba.run_cycle(pipeline)`, `baba.check_risk_limits(risk_params)`

## Karşılaşılan Sorunlar

1. **PriceGenerator her çağrıda yeni rastgele yürüyüş oluşturuyordu**
   - ATR oranları aşırı yüksek → BABA her cycle VOLATILE tespit ediyor → ticaret durduruluyor
   - Çözüm: PriceGenerator'ı persistent history ile tamamen yeniden yazıldı

2. **`_is_new_m5_candle()` sürekli False dönüyordu**
   - Pipeline outlier tespiti en yeni barları siliyor, DB'deki son timestamp hiç değişmiyor
   - Çözüm: `engine.ogul._is_new_m5_candle = lambda: True` monkey-patch

3. **Paper mode emir gönderimi engelliyor**
   - `config.paper_mode = True` → `_execute_signal()` log yazıp return ediyor
   - Çözüm: `config._data["engine"]["paper_mode"] = False`

## Sonuç

| Metrik | Değer |
|--------|-------|
| Başarılı cycle | 50/50 ✅ |
| Sinyal üretimi | 0 (rejim VOLATILE → ticaret engeli) |
| Rejim | VOLATILE (tüm cycle'lar) |
| Durum | ⚠️ KISMI BAŞARI — döngü çalışıyor ama sinyal üretilmiyor |
| Sonraki adım | PriceGenerator yeniden yazılması (TEST_003) |
