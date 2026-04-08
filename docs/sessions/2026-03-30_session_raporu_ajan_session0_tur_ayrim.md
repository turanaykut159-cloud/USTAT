# Oturum Raporu — 2026-03-30

## Konu
Ajan Session 0 başlatma sorunu + Pozisyon tür ayrımı düzeltmesi

## Yapılan İşler

### #86 — Ajan start_app Session 0 Sorunu
- **Sorun:** Ajan `NT AUTHORITY\SYSTEM` (Session 0) olarak çalışıyor. `subprocess.Popen` ile başlatılan Electron process'leri Session 0'da kalıyor, kullanıcı masaüstünde görünmüyor.
- **Kök neden:** Windows güvenlik izolasyonu — Session 0'dan kullanıcı masaüstüne (Session 2) pencere gönderilemez. `DETACHED_PROCESS` flag'i bu durumu çözmez.
- **Çözüm:** `handle_start_app()` fonksiyonunda `subprocess.Popen` yerine `schtasks /create /RU "pc" /IT` kullanıldı. `/IT` (Interactive Token) flag'i process'i kullanıcının aktif masaüstü oturumunda başlatır.
- **Dosya:** `ustat_agent.py` → `handle_start_app()` (satır 880-948)
- **Doğrulama:** Electron process'leri `Console Session 2 / DESKTOP-MB09L59\pc` altında başarıyla çalışıyor.

### #87 — Pozisyon Tür Ayrımı (MT5 vs Manuel)
- **Sorun:** Dashboard'da tüm pozisyonlar "Manuel" olarak etiketleniyor, MT5'ten direkt açılanlar ayrışmıyor.
- **Kök neden (2 katman):**
  1. `_source_for_position()` DB sorgusunda `exit_time IS NULL` filtresi — kapanıp tekrar açılmış pozisyonlarda source bulunamıyordu.
  2. DB'de `source=""` olan eski kayıtlar fallback'e düşmüyordu (`"" is not None` → boş string dönüyordu).
- **Çözüm:**
  1. DB sorgusu: `exit_time IS NULL` kaldırıldı → `ORDER BY rowid DESC LIMIT 1` (en son kayıt)
  2. Boş source kontrolü: `db_result is not None` → `db_result is not None and db_result != ""`
  3. Fallback: DB'de ve ManuelMotor'da bulunamayan pozisyonlar → `"mt5_direct"` olarak etiketleniyor
- **Dosya:** `api/routes/positions.py` → `_source_for_position()` (satır 80-120)
- **Doğrulama:** F_EKGYO pozisyonu API'den `tur: "MT5"` olarak dönüyor.

### CLAUDE.md Güncellemesi
- v5.8 → v5.9 referansları düzeltildi (3 yer)
- api/routes sayısı: 18 → 20 (`notifications.py` eklendi)
- React bileşen sayısı: 16 → 20 (DraggableGrid, PrimnetDetail, SortableCard eklendi)
- Test dosyaları: 2 → 6 (4 yeni test eklendi)
- Ajan komut tablosu: Handler fonksiyon adları ve detaylı açıklamalar eklendi

## Değişiklik Listesi
| Dosya | Değişiklik |
|-------|-----------|
| `ustat_agent.py` | handle_start_app(): subprocess.Popen → schtasks /IT |
| `api/routes/positions.py` | _source_for_position(): fallback + DB sorgusu düzeltmesi |
| `CLAUDE.md` | v5.9 referansları, dosya sayıları, ajan komut tablosu |
| `docs/USTAT_GELISIM_TARIHCESI.md` | #86, #87 maddeleri eklendi |

## Versiyon
- Mevcut: v5.9.0 (değişiklik yok)
- Commit: 4e9ff79
- Build: Gerekmedi (backend-only değişiklik)
