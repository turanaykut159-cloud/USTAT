# TEST_001 — İlk Simülasyon Çalıştırma

| Alan | Değer |
|------|-------|
| **Tarih** | 2026-03-21 ~19:30 |
| **Modül** | `engine/simulation.py` |
| **Cycle** | 50 (varsayılan) |
| **Hız** | 1.0 s/cycle |
| **Amaç** | Simülasyon modülünün ilk kez çalıştırılması, import zinciri ve Engine entegrasyonunun doğrulanması |

## Ne İçin Yapıldı

`engine/simulation.py` dosyası yazıldıktan sonra ilk kez `python -m engine.simulation` ile çalıştırıldı.
Hedef: MockMT5Bridge → Engine → BABA/OĞUL/ÜSTAT pipeline'ının uçtan uca hatasız dönmesi.

## Karşılaşılan Hatalar

1. **`ModuleNotFoundError: No module named 'MetaTrader5'`**
   - Sebep: Linux ortamında MT5 modülü yok
   - Çözüm: `sys.modules["MetaTrader5"]` içine sahte modül enjekte edildi

2. **`sqlite3.OperationalError: disk I/O error`**
   - Sebep: Canlı engine DB'si kilitli (başka process kullanıyor)
   - Çözüm: `tempfile.mkdtemp(prefix="ustat_sim_")` ile ayrı DB oluşturuldu

3. **`AttributeError: 'MockMT5Bridge' object has no attribute 'get_positions'`**
   - Sebep: DataPipeline `get_positions()` çağırıyor, mock'ta yoktu
   - Çözüm: `get_positions() -> list[dict]` metodu eklendi

4. **BABA/OĞUL cycle çağrı imza uyumsuzlukları**
   - Sebep: Runner yanlış parametre sayısıyla çağırıyordu
   - Çözüm: `Engine._run_single_cycle()` okunup gerçek imzalar kopyalandı

## Sonuç

| Metrik | Değer |
|--------|-------|
| Başarılı cycle | 0/50 (ilk denemede) |
| Durum | ❌ BAŞARISIZ — import ve DB hataları düzeltilmesi gerekti |
| Sonraki adım | TEST_002'de düzeltmeler uygulanıp tekrar çalıştırıldı |
