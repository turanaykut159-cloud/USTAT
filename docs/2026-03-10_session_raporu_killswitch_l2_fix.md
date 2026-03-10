# Session Raporu — 2026-03-10

## Konu
Kill-Switch L2 döngü bugu düzeltmesi + öğle arası sinyal engeli kaldırma

## Sorun
Otomatik işlem sistemi tüm gün boyunca işlem açmıyordu:
- OĞUL AKTİVİTE: 0 tarama, 0 sinyal, "Strateji yok"
- BUY sinyalleri üretilmesine rağmen tüm işlemler "Kill-switch L2 aktif" nedeniyle reddediliyordu
- Kill-Switch L2, 00:48'de "Günlük kayıp limiti" nedeniyle aktifleşti ve 13:08'e kadar (~12 saat) devam etti

## Kök Neden Analizi

### 1. Kill-Switch L2 Sonsuz Döngüsü
- `_reset_daily()` sadece `reason=="daily_loss"` olan L2'yi temizliyordu
- Ama `_update_consecutive_losses()` engine restart sonrası `last_cooldown_end` kaybediyordu
- Eski kayıplar tekrar sayılıp `consecutive_loss` nedeniyle L2 yeniden aktifleşiyordu
- `_reset_daily()` bu nedeni tanımadığı için temizleyemiyordu → sonsuz döngü

### 2. Öğle Arası Engeli
- Kill-Switch kalktıktan sonra (13:08) öğle arası engeli (12:30-14:00) devreye girdi
- Saat 14:00'a kadar yeni sinyal üretimi bloklandı

### 3. UNOPENED_TRADE Log Kirliliği
- `_check_unopened_trades()` öğle arası ve işlem saatleri dışında da çalışıp gereksiz log yazıyordu
- `_find_block_reason()` fallback mesajı belirsizdi ("Parametre/sinyal eşiği karşılanmadı")

## Yapılan Değişiklikler

| Dosya | Değişiklik |
|-------|-----------|
| `engine/baba.py` | `_reset_daily()`: L2 temizleme koşuluna `"consecutive_loss"` eklendi. `consecutive_losses=0`, `cooldown_until=None`, `last_cooldown_end=now` sıfırlaması |
| `engine/ogul.py` | `process_signals()`: Öğle arası sinyal engeli (12:30-14:00 LUNCH bloğu) kaldırıldı |
| `engine/ustat.py` | `_check_unopened_trades()`: İşlem saatleri dışı guard. `_find_block_reason()`: Detaylı neden raporlaması |
| `docs/USTAT_v5_gelisim_tarihcesi.md` | #41 kaydı eklendi |

## Etki Analizi
- **baba.py `_reset_daily()`**: Sadece yeni gün başlangıcında çalışır, mevcut gün içi risk kontrollerini ETKİLEMEZ
- **ogul.py lunch bloğu**: Kaldırılan blok yalnızca sinyal üretimini engelliyordu; trailing stop genişletme (LUNCH_TRAIL_WIDEN) korundu
- **ustat.py**: Sadece diagnostik raporlama — işlem açma/kapama mantığını ETKİLEMEZ

## Versiyon Durumu
- Mevcut: v5.3
- Kümülatif değişiklik: %6.6 (< %10 eşiği) → versiyon yükseltme gerekmedi

## Commit
- Hash: `9439361`
- Mesaj: `fix: Kill-Switch L2 döngü bugu + öğle arası sinyal engeli kaldırıldı`

## Build
- Masaüstü uygulamasında kullanıcı-görünür değişiklik yok (engine-only fix) → build gerekmedi
