# Oturum Raporu — 2026-04-08 — Veri Yönetim Sistemi Düzeltmesi

**Tarih:** 8 Nisan 2026
**Versiyon:** v5.9.0 (versiyon artışı gerekmedi — %0.2 değişiklik oranı)
**Commit:** fabdb5c
**Sınıf:** C3 (Kırmızı Bölge — engine/main.py)

---

## Yapılan İş Özeti

NABIZ (Sistem Monitörü) sayfasında tespit edilen "Çift Temizlik Çakışması" uyarısı üzerine veri yönetim sisteminin derinlemesine incelenmesi ve 6 sorunun düzeltilmesi.

## Tespit Edilen Sorunlar

### SORUN 1 — İki Temizlik Sistemi Çakışıyor (KRİTİK)
`_run_daily_cleanup()` (FAZ 2.8) ve `run_retention()` (FAZ-A) aynı tabloları farklı mantıkla temizliyordu. Cleanup, risk_snapshots'ı aggregation yapmadan sildiği için `daily_risk_summary` tablosuna özet veriler yazılamıyordu. 30 günlük veriden sadece 7 gün özetlenmişti.

### SORUN 2 — Retention Hiç Çalışmamış (KRİTİK)
Retention `current_hour >= 18` koşuluna bağlıydı ama uygulama genellikle 18:15'te kapanıyor — pencere çok dardı. Ayrıca `_last_retention_date` bellekte tutuluyordu, her restart'ta None'a dönüyordu.

### SORUN 3 — NABIZ Yanlış Alarm (ORTA)
`nabiz.py`'deki çakışma algılama kodu sabit değerler (events=60, snapshots=90) kullanıyordu — gerçek cleanup config'den farklı değerler okuyordu.

### SORUN 4 — Tarihler Persist Edilmiyor (ORTA)
`_last_cleanup_date`, `_last_retention_date`, `_last_weekly_maintenance` hiçbir yere kaydedilmiyordu. Her restart sonrası aynı gün tekrar çalışma riski vardı.

## Uygulanan Düzeltmeler

| # | Değişiklik | Dosya | Satır |
|---|-----------|-------|-------|
| 1 | Cleanup'tan events/snapshots silme kaldırıldı | engine/main.py | 1272-1296 |
| 2 | Temizlik tarihleri app_state'e persist | engine/main.py | _restore_state, _run_daily_cleanup |
| 3 | Retention tarihi persist | engine/main.py | retention trigger |
| 4 | Haftalık bakım tarihi persist | engine/main.py | _run_weekly_maintenance |
| 5 | Retention saat koşulu 18→17 | engine/main.py | satır 597 |
| 6 | Çakışma algılama mantığı güncellendi | api/routes/nabiz.py | 190-237 |
| 7 | Retention tarihleri DB fallback | api/routes/nabiz.py | 181-200 |

## Etki Analizi

- `_run_daily_cleanup()`: Sadece bars temizliği + trade arşivleme + WAL bakımı yapıyor (Siyah Kapı fonksiyonu DEĞİL)
- events ve risk_snapshots: Tamamen `run_retention()` tarafından yönetiliyor (aggregation korunuyor)
- NABIZ çakışma uyarısı: Retention kapalıysa uyarı veriyor, açıksa çakışma yok
- `app_state` tablosu: 3 yeni key eklendi (last_cleanup_date, last_retention_date, last_weekly_maintenance)
- Kırmızı/Siyah Kapı fonksiyonlara DOKUNULMADI: `_run_single_cycle()`, `_main_loop()`, `check_risk_limits()` vb. değişmedi

## Doğrulama

- [x] Python syntax kontrolü: main.py GEÇER
- [x] Python syntax kontrolü: nabiz.py GEÇER
- [x] Production build: 0 hata (2.54s)
- [x] Uygulama restart: API AKTIF, Engine ÇALIŞIYOR, MT5 BAĞLI
- [x] NABIZ sayfası: "Çift Temizlik Çakışması" uyarısı kaldırıldı

## Geri Alma

```bash
git revert fabdb5c --no-edit
cd desktop && npm run build
```
