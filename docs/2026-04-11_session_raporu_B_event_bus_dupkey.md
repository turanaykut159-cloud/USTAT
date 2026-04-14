# B-finding — event_bus.emit Dup-Key Bug Giderildi

**Tarih:** 2026-04-11 (Cumartesi, Barış Zamanı)
**Commit:** `2e2db23`
**Kaynak:** A3 session raporu "Dokunulmayanlar" bölümünde tespit edilen B bulgusu
**Değişiklik sınıfı:** C1 — Yeşil Bölge (`engine/event_bus.py`)
**Changelog girişi:** #169

---

## 1. Özet

A3 fix'i (notification prefs) sırasında tespit edilen `event_bus.emit` dup-key
bug'ı giderildi. `emit()` artık iç `data` sözlüğünde `type` anahtarı varsa
dış event type'ı korur, iç değeri `notif_type` alanına taşır. Sonuç:
Dashboard'daki `msg.type === 'notification'` WS branch'i artık gerçekten
tetikleniyor — h_engine bildirim emit'leri (hybrid_eod, hybrid_direction_flip,
hybrid_daily_reset) canlı olarak drawer'a düşüyor, HTTP polling'e gerek
kalmıyor.

## 2. Kök Neden

### 2.1 Eski kod

```python
def emit(event: str, data: dict[str, Any] | None = None) -> None:
    payload = {"type": event, **(data or {})}
    # ... listener + pending append
```

Dict literal + spread deseni: outer `"type": event` önce yazılır, sonra iç
`data` spread ile üstüne eklenir. Python dict spread kuralları: sonraki key
önceki key'i ezer. İç `data`'da `"type"` varsa, outer event type sessizce
kaybolur.

### 2.2 Canlı etkisi

`engine/h_engine.py`'de 3 emit call-site:

| Satır | Çağrı | Inner type |
|-------|-------|-----------|
| 701 | `_check_end_of_day` | `hybrid_eod` |
| 793 | `_check_direction_flip` | `hybrid_direction_flip` |
| 2593 | `_check_daily_reset` | `hybrid_daily_reset` |

Hepsi `_emit("notification", {"type": "hybrid_...", ...})` formatında.
`emit` bunları şu payload'lara dönüştürüyordu:

```python
{"type": "hybrid_eod", "title": "...", "message": "...", "severity": "warning", ...}
```

Dashboard WS handler (satır 379):

```jsx
if (msg.type === 'notification') {
  // notification branch
}
```

Bu koşul hiçbir zaman eşleşmiyordu — `msg.type` artık `"hybrid_eod"`,
`"notification"` değil. Tüm `hybrid_*` bildirimleri WS üzerinden Dashboard'a
ulaşmıyordu, yalnızca `getNotifications({limit:50})` HTTP polling path'i
(20sn interval) ile gecikmeli olarak geliyordu. Direction flip veya daily
reset gibi anlık uyarılar pratik olarak canlı drawer'a yansımıyordu.

### 2.3 Neden A3'te çözülmedi?

A3 fix'i **display-layer filtering** kararı aldı (`shouldShowNotification`),
toggle davranışını HTTP fetch path'ine + WS branch'ine uygular biçimde yazdı.
WS branch'in dup-key nedeniyle ölü kod olduğu tespit edildi ama bu fix
event_bus'a dokunmayı gerektirdiği için A3 kapsamından çıkarılıp ayrı bir
B bulgusu olarak işaretlendi. Bugün ele alındı.

## 3. Atomik Değişiklik

### 3.1 `engine/event_bus.py::emit` (satır 27-55)

```python
def emit(event: str, data: dict[str, Any] | None = None) -> None:
    """Event yayınla — ...

    Dup-key koruması (Widget Denetimi B-finding): Eski versiyon outer
    event'i önce yazıp inner data'yı spread ediyordu — iç ``data`` sözlüğünde
    ``type`` anahtarı varsa ..., dict spread iç ``type``'ı dış ``event``'in
    üstüne yazıyordu. ...
    """
    payload: dict[str, Any] = dict(data or {})
    if "type" in payload:
        inner_type = payload.pop("type")
        payload.setdefault("notif_type", inner_type)
    payload["type"] = event
    # ... (listener + pending append aynı)
```

**Anahtar kararlar:**

1. **setdefault kullanımı** — caller zaten `notif_type` set ettiyse explicit
   değeri korumak için. `payload["notif_type"] = inner_type` yerine
   `payload.setdefault(...)` override'i önler.
2. **Dış event her zaman `type`** — `payload["type"] = event` son satırda
   yapıldığı için inner type'a rağmen outer garantili.
3. **Listener ve pending logic değişmedi** — sadece payload oluşturma
   düzeltildi.

### 3.2 `tests/critical_flows/test_static_contracts.py` — Flow 4f

Yeni test `test_event_bus_emit_preserves_outer_type` 3 aşamalı kontrol yapar:

**Aşama 1 — Runtime drain:**

```python
event_bus._pending.clear()
event_bus.emit("notification", {
    "type": "hybrid_eod", "title": "Test", "message": "test msg", "severity": "warning",
})
events = event_bus.drain()
assert events[0]["type"] == "notification"       # outer korundu
assert events[0]["notif_type"] == "hybrid_eod"   # inner taşındı
assert events[0]["message"] == "test msg"        # diğer alanlar korundu
```

**Aşama 2 — notif_type override koruma:**

```python
event_bus.emit("notification", {
    "type": "inner_should_be_ignored",
    "notif_type": "explicit_value",
})
assert events[0]["notif_type"] == "explicit_value"  # caller'ın değeri korundu
```

**Aşama 3 — Statik kaynak kontrolu:**

```python
src = inspect.getsource(event_bus.emit)
assert '{"type": event, **' not in src  # eski dup-key literal yasak
assert "notif_type" in src              # yeni koruma var
```

### 3.3 False Positive Düzeltmesi

İlk test çalıştırmasında Aşama 3 başarısız oldu: event_bus.py docstring'i
eski buggy pattern'i literal olarak gösteriyordu (`{"type": event, **(data or {})}`).
Static grep bunu yakaladı ve test patlıyordu. Docstring genel açıklamaya
dönüştürüldü, literal pattern kaldırıldı. İkinci denemede **39 passed**.

## 4. Dokunulmayanlar (Bilinçli)

- **h_engine.py emit call-site'ları (3 yer)** — fix merkezde (event_bus)
  yapıldığı için call-site'lar aynı `{"type": "hybrid_eod", ...}` formatını
  kullanmaya devam edebilir. event_bus bunları güvenle işliyor.
- **Dashboard.jsx WS branch** — zaten `msg.type === 'notification'` check'i
  yerinde, `shouldShowNotification` filtresi A3'ten kaldı. Artık gerçekten
  tetikleniyor, ek değişiklik gereksiz.
- **HTTP `getNotifications` polling path'i** — A3'te uygulandı, fallback
  olarak kalıyor. Sistem artık hem canlı (WS) hem polling (HTTP) yollarıyla
  bildirim gösterebiliyor.
- **`api/routes/live.py::_event_drain_loop`** — drain → broadcast zinciri
  değişmedi, sadece daha önceki ölü kod yolunu canlı kılacak payload'lar
  üretiliyor.

## 5. Doğrulama

| Kontrol | Sonuç |
|---------|-------|
| critical_flows | **39 passed, 3 warnings in 2.56s** (38 baseline + 1 yeni Flow 4f) |
| Runtime drain test | outer type korundu, notif_type taşındı, override korundu |
| Build | Gereksiz (backend-only, React/JSX dokunulmadı) |
| Pre-commit hook | Geçti |
| Git commit | `2e2db23`, 3 files changed, +83/-2 |

## 6. Etki Analizi

- **Dosya sayısı:** 1 engine + 1 test + 1 changelog = 3 dosya
- **Zone dokunuşu:** Yeşil Bölge yalnız (event_bus.py listelerde yok)
- **Siyah Kapı:** YOK
- **Geriye dönük uyumluluk:** %100 — eski call-site'lar değişmedi, yeni
  `notif_type` alanı opsiyonel ve Dashboard zaten okuyor
- **Tüketici zinciri:** `emit()` → `drain()` → WS broadcast → Dashboard
  notification branch → `shouldShowNotification` filtre → drawer. Hepsi
  artık canlı.
- **Backend listener:** `event_bus._listeners` boş — hiçbir Python kodu
  `subscribe()` çağırmıyor, fix listener path'ini etkilemiyor.
- **Backpressure & cleanup logic:** Dokunulmadı. `_MAX_PENDING=500` ve
  `_pending_lock` davranışı aynı.

## 7. Deploy Durumu

- Piyasa kapalı (Cumartesi, Barış Zamanı) — deploy güvenli.
- Build gereksiz, `restart_app` yeterli (API modül reload).
- A1 + A2 + A3 + A4 + B dörtlü + B-fix beşlisi aynı anda canlıya alınabilir.
  A1 restart sırasında 1 açık pozisyonu L3 ile kapatacak (beklenen davranış).

## 8. Follow-Up

- **Yeni notification türleri** — kill_switch, drawdown, regime için backend
  `_emit("notification", {"type": "kill_switch_escalated", ...})` çağrıları
  eklenebilir. Toggle'lar (`killSwitchAlert`, `drawdownAlert`, `regimeAlert`)
  zaten persistency'ye bağlı, Dashboard `shouldShowNotification` filtresi
  ek type kategorileri için genişletilebilir. Ayrı bir A-maddesi.
- **Minimal Web Audio beep altyapısı** — `soundEnabled` toggle'ı şu an
  persistent ama davranışa bağlı değil. HTML5 Audio API veya Web Audio API
  ile basit beep/chime implementasyonu yapılabilir. Opsiyonel.
- **Monitor errorCounts substring parse kırılganlığı** — A4'te bilinçli
  dokunulmadı, ayrı madde.

## 9. Referanslar

- **A3 session raporu:** `docs/2026-04-11_session_raporu_A3_notification_prefs.md`
  — "Dokunulmayanlar (bilinçli)" bölümünde B-finding tespiti
- **h_engine emit call-site'ları:** `engine/h_engine.py` satır 701, 793, 2593
- **Dashboard WS handler:** `desktop/src/components/Dashboard.jsx` satır 379-395
- **Commit:** `2e2db23` — fix(event-bus): emit dup-key koruma (Widget Denetimi B-finding)
- **Changelog:** #169 (`docs/USTAT_GELISIM_TARIHCESI.md`)
