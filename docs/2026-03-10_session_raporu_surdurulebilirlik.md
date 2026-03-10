# Session Raporu — Sürdürülebilirlik ve Çökme Direnci

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-10 |
| **Konu** | 5 Kritik Sürdürülebilirlik Sorununun Düzeltilmesi |
| **Commit** | `4ec3fb0` |
| **Versiyon** | v5.3.0 (değişiklik %6.3 — yükseltme gerekmedi) |
| **Build** | ✅ Başarılı (0 hata) |

---

## Yapılan İş

### Ön Analiz
- ÜSTAT v5.3 Performans ve Sürdürülebilirlik Raporu (.docx) incelendi
- 5 katmanda (Engine, Database, API/Frontend, Startup) 80+ bulgu tespit edildi
- Kapsamlı rapor oluşturuldu: `docs/2026-03-10_surdurulebilirlik_ve_performans_koruma_raporu.md`

### 5 Kritik Düzeltme

| # | Sorun | Dosya | Çözüm |
|---|-------|-------|-------|
| 1 | MT5 bağlantı kopması → Engine durur | `engine/main.py` | `_heartbeat_mt5()`: 1 → 3 deneme, 2sn arayla. Toplam ~42sn reconnect penceresi |
| 2 | Restart sonrası state tutarsızlığı | `engine/main.py` | `_restore_state()`: BABA restore başarısızsa tüm restore iptal (partial restore önlemi) |
| 3 | DB integrity check yok | `engine/database.py` | `_check_integrity()`: `PRAGMA quick_check` + `sqlite3.backup()` API |
| 4 | Error Boundary yetersiz | `ErrorBoundary.jsx` + `App.jsx` | Per-route `RouteBoundary` wrapper, `resetKey` ile route değişiminde otomatik reset |
| 5 | Engine crash → API hayatta | `api/server.py` | Watchdog: Engine thread ölürse `os._exit(1)` ile API de kapanır |

### 2 Bonus Düzeltme

| Dosya | Çözüm |
|-------|-------|
| `engine/event_bus.py` | Sessiz `except: pass` → hata loglama + backpressure (max 500 pending event) |
| `engine/h_engine.py` | Yazılımsal SL/TP kapatmada sonsuz retry → max 3 deneme + `close_failed` event |

---

## Değişiklik Özeti

| Dosya | Satır (+/-) |
|-------|-------------|
| `engine/main.py` | +149 / −(refactored) |
| `engine/database.py` | +349 / −(simplified) |
| `engine/h_engine.py` | +34 / − |
| `engine/event_bus.py` | +33 / − |
| `api/server.py` | +22 / − |
| `desktop/src/App.jsx` | +36 / − |
| `desktop/src/components/ErrorBoundary.jsx` | +20 / − |
| `docs/USTAT_v5_gelisim_tarihcesi.md` | +131 (kayıt #39) |
| `docs/..._surdurulebilirlik_raporu.md` | +475 (yeni) |
| **Toplam** | **+881 / −368** |

---

## Teknik Detaylar

### MT5 Heartbeat (Kritik #1)
- Önceki: Tek `connect(launch=False)` denemesi → başarısız → engine tamamen durur
- Yeni: 3 deneme × 2sn bekleme = max 6sn reconnect penceresi
- Eğer 3 deneme de başarısızsa engine güvenli şekilde kapanır

### State Restore Atomicity (Kritik #2)
- Önceki: BABA restore başarısız olsa bile OĞUL/Pipeline restore deneniyor → risk limiti bypass riski
- Yeni: BABA restore başarısızsa tüm restore aborted, temiz başlangıç yapılır
- Sonuç özeti dict ile tüm bileşen durumları loglanır

### DB Integrity (Kritik #3)
- `PRAGMA quick_check`: Başlangıçta WAL/journal hatalarını tespit eder
- `sqlite3.backup()`: WAL-safe yedekleme (shutil.copy2 fallback korundu)

### Error Boundary (Kritik #4)
- `resetKey={pathname}`: Route değişikliğinde error state otomatik temizlenir
- `label` prop: Hangi sayfada hata olduğu kullanıcıya bildirilir
- Bir sayfa çökse bile diğer sayfalar etkilenmez

### Engine Watchdog (Kritik #5)
- `asyncio.create_task(_engine_watchdog())`: Engine thread'ini izler
- Thread sonlanırsa `os._exit(1)` — Electron/start_ustat.py süreci yeniden başlatabilir
- API'nin ölü veri sunmasını önler

---

## Versiyon Durumu

- Mevcut: **v5.3.0**
- Kümülatif değişiklik: 2301 satır / 36,242 toplam = **%6.3**
- Eşik: %10 → **Versiyon yükseltme GEREKMEDİ**

---

## Sonraki Adımlar (Opsiyonel — Rapordaki Faz 2-4)

- [ ] Faz 2: Unit test altyapısı (pytest) + Engine cycle testi
- [ ] Faz 2: Correlation ID ile request izleme
- [ ] Faz 3: API retry wrapper (frontend)
- [ ] Faz 3: Otomatik restart mekanizması (start_ustat.py)
- [ ] Faz 4: Prometheus metrikleri + Alerting
