# USTAT DEPO — Taşıma Özeti

**Tarih:** 2026-03-05

## Yapılan işlem

- **USTAT DEPO** klasörü oluşturuldu; uygulamanın **kullanmadığı** dosya ve klasörler buraya taşındı.
- **Uygulama ayağa kalkarken kullandığı** hiçbir öğe taşınmadı (engine, api, config, database, desktop, logs, start_ustat.*, requirements.txt).

## Kökte bilerek bırakılanlar (uygulama bunları kullanıyor)

- `engine/`, `api/`, `config/`, `database/`, `desktop/`, `logs/`
- `start_ustat.py`, `start_ustat.bat`, `start_ustat.vbs`
- `requirements.txt`, `.gitignore`, `.git`

## Taşınamayan (işlem kilitli)

Aşağıdakiler taşıma sırasında **başka işlem tarafından kullanıldığı** için kökte kaldı. Uygulama ve ilgili süreçler **kapalıyken** isterseniz bunları da **USTAT DEPO** içine elle taşıyabilirsiniz:

- `collector.log` (collector.py veya başka süreç yazıyorsa)
- `vite.log` (Vite/Electron açıksa)
- `viop_collected_data.db`, `viop_collected_data.db-shm`, `viop_collected_data.db-wal` (collector veya SQLite kullanıyorsa)
- `nul` (Windows özel dosyası; gerekmezse silebilir veya olduğu gibi bırakabilirsiniz)

Bu dosyalar **ana USTAT uygulaması** (start_ustat → API → Engine) tarafından kullanılmıyor; sadece collector veya geliştirme süreçleri kullanıyor olabilir.

## Taşınanlar

Detaylı liste: **USTAT DEPO** klasörü içindeki `USTAT_DEPO_TAŞIMA_LISTESI.md` dosyasına bakın.
