# Session Raporu — Crash Recovery & Sustainability Hafta 1-2

**Tarih:** 2026-03-14
**Konu:** Crash Recovery & Sürdürülebilirlik Eylem Planı — Hafta 1-2 Uygulama
**Versiyon:** 5.4.1 → 5.5.0
**Commit:** `559ca01` — feat: crash recovery & sustainability — Week 1-2 implementation + v5.5.0
**Build:** ✅ `npm run build` başarılı (0 hata)

---

## Yapılan İş

Bu session'da Crash Recovery & Sürdürülebilirlik Eylem Planı'nın Hafta 1 (Madde 1-5) ve Hafta 2 (Madde 6-10) tamamen uygulandı.

### Hafta 1 — Temel Koruma Katmanları

1. **MT5 `_safe_call()` Timeout Wrapper** (`engine/mt5_bridge.py`)
   - Tüm MT5 C++ DLL çağrıları `ThreadPoolExecutor` ile sarıldı
   - Varsayılan timeout: 8s, `order_send`: 15s, `initialize`: 30s, `shutdown`: 5s
   - 14 farklı MT5 API fonksiyonu korulandı

2. **Circuit Breaker Pattern** (`engine/mt5_bridge.py`)
   - 5 ardışık başarısız çağrı → 30 saniye cooldown
   - Cooldown sonrası otomatik probe (5s timeout ile)
   - Thread-safe implementasyon (`threading.Lock`)

3. **Heartbeat / Watchdog Sistemi** (`start_ustat.py`)
   - Engine her cycle sonunda `engine.heartbeat` dosyasını günceller
   - Watchdog: 15 saniye aralıkla kontrol, 45 saniye stale eşiği
   - Maksimum 5 ardışık restart, `--no-watchdog` devre dışı bırakma

4. **Netting Lock** (`engine/netting_lock.py` — YENİ DOSYA)
   - Symbol seviyesinde thread-safe mutex
   - H_Engine entry'de acquire, tüm çıkış noktalarında release
   - Oğul motor sinyal üretmeden önce lock kontrolü

5. **L3 Kill-Switch Close Retry Güçlendirme** (`engine/baba.py`)
   - `CLOSE_MAX_RETRIES`: 3 → 5
   - İlk tur başarısız → agresif ikinci tur retry
   - CRITICAL seviye loglama, `l3_close_failed` event kaydı

### Hafta 2 — İzleme ve API Entegrasyonu

6. **Cycle Timeout Tespiti** (`engine/main.py`)
   - Kademeli uyarı: >15s WARNING, ≥30s CRITICAL
   - 3 ardışık yavaş cycle → otomatik MT5 reconnect
   - `_last_successful_cycle_time` tracking

7. **API `data_fresh` Alanı** (`api/routes/status.py`, `api/schemas.py`)
   - `data_fresh`: Son başarılı cycle 60s'den eski mi kontrolü
   - `last_successful_cycle`: ISO timestamp
   - `circuit_breaker_active`: Circuit breaker durumu

8. **Dashboard Stale Banner** (`desktop/src/components/Dashboard.jsx`)
   - Circuit breaker aktif → "🔴 MT5 bağlantı krizi" banner
   - Data stale → "⚠ Engine verisi eski" banner
   - Mevcut equity stale ve WS reconnecting banner'larına entegre

9. **Watchdog Graceful Shutdown** (`api/server.py`)
   - Engine thread ölürse `engine.stop(reason="engine_thread_terminated")` çağrısı
   - Ardından `os._exit(1)` ile temiz çıkış

10. **Versiyon Yükseltme 5.4 → 5.5** (40+ dosya)
    - Değişiklik oranı: %106.7 (≥ %10 eşik)
    - Tüm fonksiyonel sabitler, UI elemanları, JSDoc başlıkları, metadata güncellendi

---

## Değişiklik Özeti

| Kategori | Dosya Sayısı | Açıklama |
|----------|-------------|----------|
| Engine core | 7 | mt5_bridge, main, baba, ogul, h_engine, __init__, netting_lock (yeni) |
| API | 3 | server, status route, schemas |
| Desktop | 20+ | Dashboard + tüm JSDoc/versiyon güncellemeleri |
| Config/Startup | 4 | default.json, start_ustat.py/bat/vbs |
| Doküman | 2 | Uygulama Takvimi, Eylem Planı Değerlendirme Raporu |
| **Toplam** | **71** | **22,854 eklenen / 20,079 silinen satır** |

---

## Teknik Detaylar

- **`_safe_call()` Mekanizması:** Her MT5 çağrısı tek seferlik `ThreadPoolExecutor` ile çalıştırılır, `future.result(timeout=X)` ile beklenir. Timeout → `TimeoutError`, bağlantı kesildi olarak işaretlenir.
- **Circuit Breaker State:** `_cb_failures` sayacı, `_cb_tripped` flag, `_cb_tripped_at` timestamp. `_cb_is_open()` cooldown kontrolü yapar, cooldown bitince probe dener.
- **Netting Lock:** `dict[str, str]` (symbol → owner) mapping, `threading.Lock` korumalı. `acquire_symbol()`, `release_symbol()`, `is_symbol_locked()`, `get_locked_symbols()` fonksiyonları.
- **Stale Detection:** `_last_successful_cycle_time` epoch timestamp, API'de 60s eşik ile `data_fresh` hesaplanır.

---

## Gelişim Tarihçesi

Kayıt #34 olarak `USTAT DEPO/docs/USTAT_v5_gelisim_tarihcesi/USTAT_v5_gelisim_tarihcesi.md` dosyasına eklendi.

---

## Sonraki Adımlar (Gelecek Session'lar)

- **Hafta 3 (16-20 Mar):** Madde 11 (Transaction Isolation), 12 (Thread Lock Timeout), 13 (Memory Monitoring)
- **Hafta 4 (23-27 Mar):** Madde 14 (HealthCollector Alarm), 15 (Config Schema)
- **Ay 2 (30 Mar-19 Nis):** Madde 16-20 (Advanced monitoring, auto-recovery, stress test)
