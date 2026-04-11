# Oturum Raporu — A15 (B18): Hata Resolve `message_prefix` DB Yazımı

**Tarih:** 11 Nisan 2026 (Pazar, Barış Zamanı)
**Bulgu:** Widget Denetimi A15 (B18) — Hata Takip Paneli "Çözümle" butonu spesifik mesaj seçimini DB'ye yazmıyor
**Sınıf:** C1 (Yeşil Bölge — `engine/error_tracker.py` + `api/routes/error_dashboard.py`)
**Zaman dilimi:** Pazar — piyasa kapalı, Barış Zamanı
**Anayasa uyumu:** Siyah Kapı yok ✓, Kırmızı Bölge yok ✓, Sarı Bölge yok ✓

---

## 1. Kök Neden

Hata Takip panelinde kullanıcı bir hata grubu için "Çözümle" butonuna tıkladığında frontend `POST /api/errors/resolve` isteği `{ error_type, message_prefix, resolved_by }` payload'u ile gidiyordu. Ancak iki katmanda da `message_prefix` GÖZARDI EDİLİYORDU:

1. **Backend route** (`api/routes/error_dashboard.py`): INSERT statement sadece `(error_type, resolved_at, resolved_by)` 3 kolonu yazıyordu, `message_prefix` payload alanı kullanılmıyordu.
2. **ErrorTracker** (`engine/error_tracker.py`): `_resolved_types: set[str]` yalnız `error_type` bazlı suppression yapıyordu — `record_error` çağrılarında "tip çözümlenmiş ise → bastır" mantığı bu set'i okuyordu.

Sonuç: Kullanıcı tek bir mesajı çözümlediğini sanıyordu (örn. "TRADE_ERROR: SL ekleme başarısız: ticket=123"), oysa aynı tipin (TRADE_ERROR) tüm mesajlarını sessizce gizliyordu. Audit B18 kritik/orta sınıf: kullanıcı yanılgısı + finansal görünürlük kaybı potansiyeli.

`error_resolutions` tablosunun şeması da `error_type TEXT PRIMARY KEY` idi — composite key destekli değildi, dolayısıyla "aynı tip + farklı prefix" kayıtları yan yana tutmak imkansızdı.

## 2. Çözüm (3 dosya + 1 test)

### 2.1 Şema Migration — `engine/error_tracker.py::_ensure_resolution_table`

Yeni şema:

```sql
CREATE TABLE error_resolutions (
    error_type      TEXT NOT NULL,
    message_prefix  TEXT NOT NULL DEFAULT '',
    resolved_at     TEXT NOT NULL,
    resolved_by     TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (error_type, message_prefix)
)
```

Migration mantığı:

1. `sqlite_master` ile tablo varlığını kontrol et.
2. Tablo yok → yeni şema ile oluştur (normal path).
3. Tablo var ama `PRAGMA table_info` çıktısında `message_prefix` kolonu yok →
   - `ALTER TABLE error_resolutions RENAME TO error_resolutions_old`
   - Yeni şema `CREATE TABLE`
   - `INSERT ... SELECT error_type, '', resolved_at, resolved_by FROM ..._old` (eski satırlar wildcard olarak taşınır → geriye dönük uyumlu)
   - `DROP TABLE error_resolutions_old`
4. Tablo var ve kolon mevcut → no-op.

Bu migration ErrorTracker `__init__` sırasında `_load_resolved_types` ÖNCESİ çalışır.

### 2.2 İki Seviyeli Suppression — `_resolved_types` + `_resolved_keys`

```python
self._resolved_types: set[str] = set()                  # wildcard
self._resolved_keys: set[tuple[str, str]] = set()       # spesifik
```

`_load_resolved_types`:

```python
for (etype, prefix), _res in resolutions.items():
    if prefix:
        self._resolved_keys.add((etype, prefix))
    else:
        self._resolved_types.add(etype)
```

`_load_resolutions` artık `dict[tuple[str, str], dict]` döndürür:

```python
rows = self._db._fetch_all(
    "SELECT error_type, message_prefix, resolved_at, resolved_by "
    "FROM error_resolutions"
)
return {(r["error_type"], r.get("message_prefix", "") or ""): r for r in rows}
```

`_apply_resolutions` iki seviyeli eşleştirme yapar:

```python
wildcards = {etype: res for (etype, p), res in resolutions.items() if not p}
specifics = {(etype, p): res for (etype, p), res in resolutions.items() if p}
for key, group in self._groups.items():
    g_prefix = key.split("::", 1)[1] if "::" in key else ""
    res = specifics.get((group.error_type, g_prefix))
    if res is None:
        res = wildcards.get(group.error_type)
    if res and group.last_seen.isoformat() <= res["resolved_at"]:
        group.resolved = True
        ...
```

### 2.3 `resolve_group` Yeniden Yazımı

```python
def resolve_group(self, error_type, message_prefix="", by="operator"):
    prefix_key = message_prefix[:80].strip() if message_prefix else ""

    with self._lock:
        for key, group in list(self._groups.items()):
            if group.error_type == error_type:
                g_prefix = key.split("::", 1)[1] if "::" in key else ""
                matches = (
                    not prefix_key                          # wildcard
                    or prefix_key == g_prefix               # tam eşleşme
                    or prefix_key in (group.message or "")[:80].strip()
                )
                if matches:
                    group.resolve(by)
                    keys_to_remove.append(key)
                    resolved_any = True
        ...
        if resolved_any:
            if prefix_key:
                self._resolved_keys.add((error_type, prefix_key))
            else:
                self._resolved_types.add(error_type)

    if resolved_any and self._db:
        self._db._execute(
            """INSERT OR REPLACE INTO error_resolutions
               (error_type, message_prefix, resolved_at, resolved_by)
               VALUES (?, ?, ?, ?)""",
            (error_type, prefix_key, now_str, by),
        )
        if prefix_key:
            self._db._execute(
                "DELETE FROM events WHERE type = ? "
                "AND substr(trim(message), 1, 80) = ? AND timestamp <= ?",
                (error_type, prefix_key, now_str),
            )
        else:
            self._db._execute(
                "DELETE FROM events WHERE type = ? AND timestamp <= ?",
                (error_type, now_str),
            )
```

Davranış matrisi:

| `message_prefix` | DB satırı | Suppression set | Etki |
|---|---|---|---|
| `""` | `(TYPE, '')` | `_resolved_types.add(TYPE)` | Tipin tüm mesajları bastırılır (eski davranış, bilinçli) |
| `"send_order failed: ticket=123"` | `(TYPE, 'send_order...')` | `_resolved_keys.add((TYPE, 'send_order...'))` | SADECE bu mesaj prefix'ine sahip event'ler bastırılır; aynı tipin diğer mesajları görünmeye devam eder |

### 2.4 `record_error` İki Seviyeli Suppression Kontrolü

```python
prefix_for_check = message[:80].strip() if message else ""
is_suppressed = (
    (
        error_type in self._resolved_types
        or (error_type, prefix_for_check) in self._resolved_keys
    )
    and severity not in ("CRITICAL", "ERROR")
)
```

`_load_from_db` aynı iki seviyeli kontrolü yapar (DB'den geçmiş event'leri belleğe yüklerken).

### 2.5 `resolve_all` 4 Kolonlu INSERT

```python
self._db._execute(
    """INSERT OR REPLACE INTO error_resolutions
       (error_type, message_prefix, resolved_at, resolved_by)
       VALUES (?, '', ?, ?)""",
    (etype, now_str, by),
)
```

Wildcard satır olarak yazılır (`message_prefix=''`).

### 2.6 Route Düzeltmeleri — `api/routes/error_dashboard.py`

`resolve_error_group`:

```python
prefix_key = (req.message_prefix or "")[:80].strip()
db._execute(
    """INSERT OR REPLACE INTO error_resolutions
       (error_type, message_prefix, resolved_at, resolved_by)
       VALUES (?, ?, ?, ?)""",
    (req.error_type, prefix_key, now_str, req.resolved_by),
)
```

`resolve_all_errors`:

```python
db._execute(
    """INSERT OR REPLACE INTO error_resolutions
       (error_type, message_prefix, resolved_at, resolved_by)
       VALUES (?, '', ?, ?)""",
    (etype, now_str, by),
)
```

`_get_resolution_map` artık SADECE wildcard satırları okur:

```python
rows = db._fetch_all(
    "SELECT error_type, resolved_at, resolved_by FROM error_resolutions "
    "WHERE message_prefix = ''"
)
return {r["error_type"]: r for r in rows}
```

Try/except fallback eski şemaya da düşer (test kontekstinde migration koşmadıysa). Route `/groups` endpoint'i tip bazında grupladığı için spesifik çözümlemelerin "tip çözülmüş" gibi sızmasını engeller — yoksa tek bir mesaj çözümlemesi tüm tipi gizlerdi (audit B18 tekrarı).

### 2.7 Flow 4zc — Statik Sözleşme Testi

`tests/critical_flows/test_static_contracts.py::test_error_resolve_message_prefix_persistence` (5 aşama):

1. **`_resolved_keys` field + composite PK + ALTER migration** — `engine/error_tracker.py` içinde `_resolved_keys`, `message_prefix`, `ALTER TABLE error_resolutions RENAME`, `PRIMARY KEY (error_type, message_prefix)` regex eşleşmeleri.
2. **`prefix_key` dallanması + 4 kolonlu INSERT + DELETE substr** — `prefix_key` değişkeni, `INSERT OR REPLACE INTO error_resolutions (error_type, message_prefix, resolved_at, resolved_by)` regex, `substr(trim(message), 1, 80)` string'i.
3. **`record_error` iki seviyeli suppression** — `_resolved_keys` ve `in self._resolved_keys` kontrolü.
4. **Route düzeltmeleri** — `error_dashboard.py` 4 kolonlu INSERT regex, `WHERE message_prefix = ''` filtresi, `prefix_key` ekstraksiyonu.
5. **Audit markerları** — `A15` + `B18` her iki dosyada.

## 3. Anayasa Uyumu

| Kontrol | Sonuç |
|---|---|
| Siyah Kapı dokunuşu | Yok — `_ensure_resolution_table`, `resolve_group`, `record_error` korunan fonksiyon listesinde değil |
| Kırmızı Bölge | Yok — `engine/database.py` DOKUNULMADI; migration ErrorTracker kendi `_db._execute` kanalı üzerinden yapar |
| Sarı Bölge | Yok |
| Çağrı sırası | Değişmedi |
| Config | Değişmedi |
| Backend motor davranışı | BABA/OĞUL/H-Engine/main loop dokunulmadı |
| Schema geriye uyum | Eski tek-kolon şema ALTER ile migration; eski satırlar wildcard olarak taşınır → eski davranış korunur |
| API geriye uyum | `/api/errors/resolve` request schema (`ResolveRequest`) zaten `message_prefix: str = ""` alanını içeriyordu — frontend payload değişmedi, sadece backend artık dürüstçe yazıyor |
| Piyasa zamanı | Barış Zamanı (Pazar) ✓ |

## 4. Test ve Build

**Kritik akış testleri:**
```
python -m pytest tests/critical_flows -q --tb=short
62 passed, 3 warnings in 3.45s
```

Baseline 61 → 62 (Flow 4zc eklendi). İlk koşuda yeşil.

**Production build:**
```
python .agent/claude_bridge.py build
ustat-desktop@6.0.0
vite v6.4.1 building for production...
✓ 730 modules transformed
dist/assets/index-BHiPf3Rm.js   892.07 kB │ gzip: 255.77 kB
✓ built in 2.69s
```

Modül sayısı (730) ve bundle boyutu değişmedi (frontend dokunulmadı).

## 5. Değişiklik Özeti

| Dosya | Tür | Satır |
|---|---|---|
| `engine/error_tracker.py` | DEĞİŞTİ | +135 / -25 |
| `api/routes/error_dashboard.py` | DEĞİŞTİ | +47 / -10 |
| `tests/critical_flows/test_static_contracts.py` | DEĞİŞTİ | +95 / 0 |
| `docs/USTAT_GELISIM_TARIHCESI.md` | DEĞİŞTİ | +1 / 0 |
| `docs/2026-04-11_session_raporu_A15_error_resolve_message_prefix.md` | YENİ | +~220 |

**Toplam:** 3 değişiklik dosyası + 1 yeni test + 1 changelog girişi + 1 oturum raporu.

## 6. Geriye Dönük Uyumluluk Notları

- **Mevcut DB rows:** Eski şemadaki satırlar (`error_type` PK, `message_prefix` yok) migration sırasında `message_prefix=''` ile taşınır → wildcard olarak yorumlanır → eski "tüm tipi bastır" davranışı korunur.
- **Frontend:** `ResolveRequest` schema değişmedi (`message_prefix: str = ""` zaten vardı), frontend kod değişikliği gerekmez. Yeni davranış otomatik aktif.
- **`/api/errors/resolve-all`:** Wildcard yazımı korundu — "Hepsini Çözümle" butonu eski davranışın aynısını yapar (tüm açık tipleri tipik olarak bastırır).
- **`/api/errors/groups`:** Route grouping tip bazında olduğu için sadece wildcard çözümlemeleri "tip çözüldü" diye gösterir; spesifik çözümleme aynı tipin diğer mesajlarını "açık" olarak gösterir → audit B18 dürüst davranış.

## 7. Sonraki Maddeler

A15 kapatıldı. Backlog'da sırada:

- **A6** — Performans equity vs deposit ayrımı (B14, Yüksek)
- **B8** — Otomatik Pozisyon Özeti duplicate + sayısal tutarsızlık (Yüksek)

Mandate: otonom olarak devam et.
