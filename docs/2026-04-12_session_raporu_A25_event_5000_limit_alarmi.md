# Oturum Raporu — A25 (K3): Event 5000 Limit Truncation Alarmı

**Tarih:** 12 Nisan 2026
**Kategori:** Widget Denetimi — Priority 3 (K3 kritik)
**Sınıf:** C1 (Yeşil Bölge route + frontend)
**Kapsam:** 1 backend route + 1 frontend + 1 test + 1 changelog + 1 rapor
**Durum:** Tamamlandı — atomik commit hazır

---

## 1. Sorun Tanımı

Widget Denetimi K3 / A25 bulgusu: `api/routes/error_dashboard.py`
içindeki `_fetch_events_from_db()` helper'ı `/api/errors/summary`,
`/api/errors/groups` ve `/api/errors/resolve-all` endpoint'lerinde 7
günlük event sorguları için `limit=5000` ile çağrılıyor:

```python
week_start = (now - timedelta(days=7)).isoformat()
events = _fetch_events_from_db(since=week_start, limit=5000)
```

SQL gövde:

```sql
SELECT * FROM events
WHERE severity IN ('WARNING', 'ERROR', 'CRITICAL')
  AND timestamp >= ?
ORDER BY id DESC
LIMIT 5000
```

**Etki:** Audit denetimi anında `by_severity.WARNING = 4952` — 5000
sınırına 48 kayıt mesafede. Mevcut WARNING akışı (saat tepesi 124,
gün toplamı ≥129) 7 gün × 5000 sınırını her an delebilir. Limit
aşıldığında SQL `ORDER BY id DESC LIMIT 5000` kuralıyla EN ESKİ
WARNING'leri sessizce düşürür, frontend özet kayıkları kayar
(`total_warnings`, `today_warnings`, `by_category`, `by_severity`
hepsi eksik), kullanıcı buna dair hiçbir uyarı görmez.

Bu, "veri var ama ben görmüyorum" sınıfında **veri görünürlük**
hatasıdır — risk yönetimi için kritik.

---

## 2. Kök Sebep

İki katman birden:

1. **Helper sessizliği:** `_fetch_events_from_db` truncation tespit
   etmiyor — `len(rows) == limit` durumunda log dahi yok.
2. **Magic number:** `5000` literal'i hem helper'da hem üç ayrı
   endpoint'te tekrarlanıyor; tek noktada değiştirme imkansız.
3. **UI sessizlik:** Schema'da truncation alanı yok, frontend banner
   yok.

---

## 3. Çözüm

### 3a) `api/routes/error_dashboard.py`

**(i) ErrorSummaryResponse schema'ya yeni alan:**

```python
class ErrorSummaryResponse(BaseModel):
    """Dashboard özet verisi.

    Widget Denetimi A25 (K3): `truncation_warning` alanı 7 günlük event
    sorgusu 5000 limitine değdiğinde doldurulur — bu durumda eski kayıtlar
    sessizce düşer ve özet eksiktir. Frontend banner ile kullanıcıya
    bildirir, retention politikası gözden geçirilir.
    """
    today_errors: int = 0
    ...
    truncation_warning: str | None = None
```

**(ii) `_fetch_events_from_db` truncation log:**

```python
rows = db._fetch_all(
    f"SELECT * FROM events {where} ORDER BY id DESC LIMIT ?",
    tuple(params),
)

# A25 (K3): truncation alarm — kayıt sayısı limite değdi
if len(rows) >= limit:
    logger.warning(
        "events query truncation: returned=%d limit=%d since=%s "
        "severity_filter=%s — eski kayıtlar düşmüş olabilir, "
        "retention politikasını gözden geçirin",
        len(rows), limit, since, severity_filter,
    )

return rows
```

**(iii) `get_error_summary` truncation hesaplama:**

```python
week_start = (now - timedelta(days=7)).isoformat()
SUMMARY_EVENT_LIMIT = 5000
events = _fetch_events_from_db(since=week_start, limit=SUMMARY_EVENT_LIMIT)

# A25 (K3): truncation alarm hesapla — kayıt sayısı limite değdi mi?
truncation_warning: str | None = None
if len(events) >= SUMMARY_EVENT_LIMIT:
    truncation_warning = (
        f"Son 7 gün içinde {SUMMARY_EVENT_LIMIT}+ event mevcut — "
        "özet kayıtları eksik olabilir. Düşük öncelikli event "
        "retention politikası gözden geçirilmeli."
    )
...
return ErrorSummaryResponse(
    ...
    truncation_warning=truncation_warning,
)
```

Magic number `5000` lokal sabit `SUMMARY_EVENT_LIMIT`'e çekildi (test
de bu sabit ismini kontrol eder — değişirse hem helper hem schema hem
test aynı anda görür).

### 3b) `desktop/src/components/ErrorTracker.jsx`

Mevcut hata banner'ının hemen altına eklendi:

```jsx
{/* Widget Denetimi A25 (K3): Truncation banner — backend
    /api/errors/summary 7 günlük event sorgusunda 5000 limitine
    değdiğinde bu uyarı görünür. Eski kayıtlar düşmüş demektir,
    özet eksiktir. Operatör retention politikasını gözden geçirmeli. */}
{s.truncation_warning && (
  <div
    className="error-truncation-banner"
    style={{
      background: '#78350f22', border: '1px solid #d97706', borderRadius: 6,
      padding: '8px 14px', marginBottom: 14, fontSize: 12, color: '#fbbf24',
      display: 'flex', alignItems: 'center', gap: 8,
    }}
    title="Backend events tablosu 7 gün × 5000 limit aşımı tespit etti"
  >
    <span style={{ fontSize: 14 }}>⚠</span>
    <span><b>Eksik özet:</b> {s.truncation_warning}</span>
  </div>
)}
```

`error-truncation-banner` className test için drift anchor; banner
mevcut hata mesajı banner'ından farklı renkte (sarı, `#d97706` border)
— operatör hatadan ayırt edebilir.

### 3c) `tests/critical_flows/test_static_contracts.py`

**Flow 4zj** eklendi: `test_error_dashboard_event_truncation_alarm`.
5 sözleşme noktası:

1. `ErrorSummaryResponse` içinde `truncation_warning: str | None = None`
2. `_fetch_events_from_db` body'sinde `len(rows) >= limit` + `logger.warning` + `truncation` keyword
3. `get_error_summary` body'sinde `SUMMARY_EVENT_LIMIT` sabiti + `len(events) >= SUMMARY_EVENT_LIMIT` + `truncation_warning=truncation_warning` keyword arg
4. Frontend `s.truncation_warning` koşulu + `error-truncation-banner` className
5. A25 audit marker hem `error_dashboard.py` hem `ErrorTracker.jsx`'te

### 3d) `docs/USTAT_GELISIM_TARIHCESI.md`

**#199** girişi #198 üzerine eklendi.

---

## 4. Test Sonuçları

```
python -m pytest tests/critical_flows -q
========================
69 passed, 3 warnings in 3.16s
========================
```

Baseline 68 → 69 (Flow 4zj eklendi).

---

## 5. Build Sonuçları

```
npm run build (vite v6.4.1)
✓ 730 modules transformed
dist/index.js   895.70 kB │ gzip: 256.68 kB
✓ built in 2.55s
```

Bundle boyutu: 895.70 kB (A24 sonrası 895.23 → +0.47 kB; truncation
banner JSX + style).

---

## 6. Anayasa Uyumu Doğrulama

| Kontrol | Durum |
|---------|-------|
| Çağrı sırası (BABA → OĞUL → H-Engine → ÜSTAT) | Etkilenmedi |
| Risk kapısı (`can_trade`) | Etkilenmedi |
| Kill-switch monotonluğu | Etkilenmedi |
| SL/TP zorunluluğu | Etkilenmedi |
| EOD kapanış 17:45 | Etkilenmedi |
| Felaket drawdown %15 | Etkilenmedi |
| OLAY rejimi `risk_multiplier=0` | Etkilenmedi |
| Circuit breaker | Etkilenmedi |
| Siyah Kapı fonksiyonları (31) | Hiçbiri değişmedi |
| Kırmızı Bölge dokunuşu | Yok |
| Sarı Bölge dokunuşu | Yok |
| Backend motor değişikliği | Yok (sadece read-only route + helper) |
| Sihirli sayı | Yok (5000 → SUMMARY_EVENT_LIMIT) |
| Events tablosu şeması | Değişmedi |
| Retention politikası | Değişmedi (audit önerisi A26 kapsamına havale) |

**Değişiklik sınıfı:** C1 — Yeşil Bölge route + frontend defansif
sertleştirme. Veri görünürlük katmanı.

---

## 7. Kalan İşler

- Atomik commit (4 dosya: error_dashboard.py, ErrorTracker.jsx,
  test_static_contracts.py, USTAT_GELISIM_TARIHCESI.md, bu rapor)
- Sonraki madde: A26 (K4) — NABIZ retention_covered bars çelişkisi
