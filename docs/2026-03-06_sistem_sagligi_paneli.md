# Sistem Sagligi Paneli — Session Raporu

**Tarih:** 2026-03-06
**Session:** Tasarim + Uygulama + Dogrulama

---

## Yapilan Is

USTAT v5.1 masaustu uygulamasina "Sistem Sagligi" sekmesi eklendi. Dongu performansi, MT5 baglanti durumu, emir sureleri, katman durumlari ve hatalar tek ekranda izlenebilir hale getirildi.

**Temel prensip:** Bellekte metrik topla, DB'ye yazma, sistemi yavaslatma. `time.perf_counter()` overhead ~0.01ms.

---

## Mimari

### 1. HealthCollector (engine/health.py)
- Thread-safe, `threading.Lock` + `collections.deque(maxlen=N)` ile bellek-icinde metrik toplama
- `CycleTimings`: 11 adim zamanlama + overrun flag
- `OrderTiming`: sembol, yon, sure, basari, retcode, slippage
- `ReconnectEvent`: zaman, basari, sure
- `snapshot()`: lock altinda tum verilerin kopyasini dondurur

### 2. Timer Enstrumantasyonu
- `engine/main.py`: Her 10 adima `perf_counter` timer. Cycle sonunda `record_cycle()`.
- `engine/mt5_bridge.py`: Heartbeat'te `record_ping()`, hatalarda `record_disconnect()`, emirlerde `record_order()`.
- `engine/ustat.py`: `_last_run_time` ISO format.

### 3. API Endpoint (GET /api/health)
Tek endpoint 6 bolum veri dondurur:
1. **cycle**: Son dongu adimlari, trend (son 60 dongu), ort/max, asim sayisi
2. **mt5**: Son/ort ping, kopma sayisi, uptime, reconnect gecmisi
3. **orders**: Ort emir suresi, basari/ret/timeout sayilari, son 10 emir
4. **layers**: BABA (rejim, guven, kill-switch), OGUL (aktif islem, gunluk zarar stop), H-Engine (hibrit, K/Z, native_sltp), USTAT (son calisma)
5. **recent_events**: Son 30 DB olayi (severity ile)
6. **system**: Engine uptime, dongu sayisi, DB boyutu, WS istemci, cache durumu

### 4. Desktop Sayfasi (SystemHealth.jsx)
- 6 bolumlu React bilesenI, 5sn polling
- Adim breakdown barlari (renk kodlu, yuzde gosterimi)
- Mini trend grafik (CSS-only, son 60 dongu)
- Katman durumu 4'lu grid
- Severity filtre butonlari (ALL / ERROR / WARNING / INFO)
- Reconnect ve emir tablolari

---

## Degisen Dosyalar (12 dosya)

| Dosya | Degisiklik Turu |
|---|---|
| engine/health.py | YENI — HealthCollector sinifi |
| engine/main.py | timer ekleme (3 nokta) |
| engine/mt5_bridge.py | _health attr + ping/disconnect/order kaydi |
| engine/ustat.py | 1 satir (_last_run_time) |
| api/schemas.py | HealthResponse model |
| api/routes/health.py | YENI — GET /api/health |
| api/server.py | health import + include_router |
| desktop/src/services/api.js | getHealth() fonksiyonu |
| desktop/src/components/SystemHealth.jsx | YENI — 6 bolumlu sayfa |
| desktop/src/components/SideNav.jsx | 1 satir (menu ogesi) |
| desktop/src/App.jsx | 1 import + 1 Route |
| desktop/src/styles/theme.css | ~300 satir .sh-* CSS |

---

## Dogrulama

- 7/7 Python dosyasi syntax hatasiz (py_compile)
- HealthCollector olusturma + snapshot OK
- HealthResponse model olusturma + serialization OK
- Tum degisiklikler additive — mevcut islevsellige dokunmuyor

---

## Siradaki Adimlar

1. **Engine calistirken test:** `curl http://localhost:8000/api/health` — JSON response tum bolumleri dolu dondurmeli
2. **Desktop test:** "Sistem Sagligi" sekmesine tikla, 6 bolumun gorundugunu dogrula
3. **Performans kontrolu:** Cycle suresi ekleme oncesi/sonrasi karsilastirma — overhead <0.05ms olmali
