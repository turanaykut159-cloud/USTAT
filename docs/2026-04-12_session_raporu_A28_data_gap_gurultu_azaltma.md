# Oturum Raporu — A28 (K6): DATA_GAP Gürültü Azaltma

**Tarih:** 12 Nisan 2026
**Kategori:** Widget Denetimi — Priority 3 (K6 sessiz alan)
**Sınıf:** C2 (Sarı Bölge `engine/data_pipeline.py`)
**Kapsam:** 1 engine + 1 test + 1 changelog + 1 rapor
**Durum:** Tamamlandı — atomik commit hazır

---

## 1. Sorun Tanımı

Widget Denetimi raporundaki **K6 / A28** maddesi: Ayarlar sayfasındaki
Sistem Log bölümünde ilk 5 kayıt istikrarlı olarak `DATA_GAP WARNING`
mesajları ile doluyordu. `engine/data_pipeline.py::_detect_gaps()`
fonksiyonu VİOP piyasa saati içinde tespit edilen bar arası boşlukları
WARNING seviyesinde DB event olarak yazıyordu ve 15 kontrat × 4 timeframe
(60 kombinasyon) üzerinden 5 dakikada bir yeni WARNING üretiyordu.

Sonuç: Gerçek uyarılar (örn. bayat veri, outlier, MT5 kopması)
DATA_GAP WARNING selinde gözden kaçıyor; kullanıcı Sistem Log panelinde
sürekli "WARNING" görerek paniğe kapılıyordu.

---

## 2. Kök Sebep

`_detect_gaps()` içinde iki tasarım hatası bulundu:

1. **Yanlış severity sınıflandırması:** Rutin market-saati gap'leri
   zaten throttle ve `_is_market_hours_gap()` filtresiyle süzülüyor. Geriye
   kalan "gerçek gap'ler" çoğunlukla saniye/dakika düzeyinde recoverable
   boşluklar — bir sonraki tick'te normale dönüyor. Bunları `WARNING`
   olarak işaretlemek yanıltıcı. Gerçek bayatlık zaten
   `check_data_freshness()` içinde ayrı `logger.warning` + STALE dönüş
   ile raporlanıyor.

2. **Yetersiz throttle aralığı:** Per-symbol/timeframe cooldown 300
   saniye (5 dk). 15 kontrat × 4 TF = 60 kombinasyon × 12 event/saat =
   teorik 720 DB event/saat üst sınırı. Bu sınır DATA_GAP'in Sistem Log
   tablosunu domine etmesi için yeterli.

---

## 3. Çözüm

### 3a) `engine/data_pipeline.py`

Üç nokta değişikliği:

**Nokta 1 — instance değişken yorumu (satır ~127-131):**

```python
# DATA_GAP spam throttle: sembol başına son event zamanı
# A28 (K6): Aynı sembol/timeframe için 15 dakikada en fazla 1 DB event
# yazılır. Severity INFO — rutin market-saati gap'leri gürültüdür,
# gerçek bayatlık check_data_freshness() içinde ayrı WARNING loglar.
self._last_gap_event: dict[str, datetime] = {}
_GAP_EVENT_COOLDOWN_SEC: float = 900.0  # 15 dakika
```

**Nokta 2 — `_detect_gaps()` DB event bloku (satır ~573-590):**

```python
# DB event throttle: aynı sembol/tf için 15 dakikada 1 kez
# A28 (K6): Severity INFO — rutin gap'ler recoverable/piyasa saati içi
# beklenen gürültü. Gerçek bayat veri check_data_freshness() içinde
# ayrı WARNING olarak loglanır. Cooldown 300s→900s genişletildi.
if real_gaps:
    throttle_key = f"{symbol}/{timeframe}"
    now = datetime.now()
    last = self._last_gap_event.get(throttle_key)
    if last is None or (now - last).total_seconds() > 900.0:
        self._last_gap_event[throttle_key] = now
        self._db.insert_event(
            event_type="DATA_GAP",
            message=(
                f"{symbol}/{timeframe}: {len(real_gaps)} gap "
                f"tespit edildi (piyasa saati içi, rutin)"
            ),
            severity="INFO",
            dedup_seconds=900,
        )
```

Değişiklikler:
- `severity="WARNING"` → `severity="INFO"`
- `> 300.0` → `> 900.0` (cooldown 5dk → 15dk)
- `dedup_seconds=300` → `dedup_seconds=900`
- Mesaj sonuna "rutin" ibaresi eklendi (insan okunabilirlik)

**Değişmeyen koruma noktaları:**
- `_is_market_hours_gap()` filtresi korundu (hafta sonu/gece gap'leri hâlâ atlanıyor)
- `logger.debug(...)` rutin gap detayı DEBUG seviyesinde kaldı (değişiklik yok)
- `check_data_freshness()` STALE durumunda `logger.warning` loglamaya devam ediyor
- OHLCV validasyon mantığı (`validate_ohlcv`, `_filter_outliers`) dokunulmadı

### 3b) `tests/critical_flows/test_static_contracts.py`

**Flow 4zg** eklendi: `test_data_gap_noise_reduction`. 4 sözleşme noktası:

1. `_detect_gaps()` içinde `DATA_GAP` insert_event severity `INFO` olmalı (WARNING değil)
2. Per-symbol cooldown `> 900.0` olmalı (eski 300 değeri geri dönerse regresyon)
3. `insert_event(dedup_seconds=900)` olmalı (insert_event dedup penceresi)
4. `check_data_freshness` içinde `logger.warning` korunmuş olmalı (gerçek bayatlık
   WARNING loglamaya devam etmeli — rutin gap INFO'ya inerken bayatlık WARNING kalır)
5. `data_pipeline.py` içinde `A28` audit marker'ı bulunmalı

### 3c) `docs/USTAT_GELISIM_TARIHCESI.md`

**#196** girişi #195 üzerine eklendi.

---

## 4. Test Sonuçları

```
python -m pytest tests/critical_flows -q --tb=short
========================
66 passed in 3.20s
========================
```

Baseline 65 → 66 (Flow 4zg eklendi).

---

## 5. Build Sonuçları

Bu oturum backend-only olduğu için `npm run build` gerekmiyor.
Frontend bundle değişmedi.

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
| Sarı Bölge dokunuşu | `data_pipeline.py` — yalnız DB event politikası (severity + cooldown) |
| `_detect_gaps` gap tespit mantığı | Değişmedi (threshold, `_is_market_hours_gap`, real_gaps filtresi aynı) |
| `check_data_freshness` | Dokunulmadı — gerçek bayatlık tespiti ve WARNING loglama korundu |
| Validasyon katmanı (`validate_ohlcv`, `_filter_outliers`) | Dokunulmadı |
| Sihirli sayı | 900.0 değeri hemen üstteki yorumda dokümante edildi (15 dk); hem cooldown hem dedup aynı değeri kullanıyor — çifte kilit simetrisi için |

**Değişiklik sınıfı:** C2 — Sarı Bölge dosyasına dokunuş ama sadece DB
event politikası. Veri akışı, validasyon, gap tespit eşikleri, fetch
döngüsü tamamen dokunulmadan kaldı.

---

## 7. Etki Analizi

**Doğrudan etkilenen tüketiciler:**
- Ayarlar sayfası Sistem Log tablosu — DATA_GAP kayıtları INFO
  seviyesine düştüğü için WARNING filtresi seçildiğinde görünmeyecek
- `database.db_events` tablosu — yeni DATA_GAP satırları severity="INFO"
- `api/routes/events.py` / notification sistemi — WARNING seviye filtresi
  kullanan herhangi bir dashboard DATA_GAP'i saymayacak

**Dolaylı etki yok:**
- Engine çalışma mantığı (cycle süresi, veri çekme, sinyal üretimi) etkilenmedi
- BABA risk kararları etkilenmedi (DATA_GAP zaten BABA tarafından tüketilmiyor)
- OĞUL emir üretimi etkilenmedi
- Gerçek veri kaybı tespiti hâlâ `check_data_freshness()` içinde WARNING loglar

---

## 8. Geri Alma Planı

```bash
git revert <commit_hash> --no-edit
```

Revert sonrası:
- DATA_GAP yeniden WARNING seviyesine döner
- Cooldown 5 dakikaya iner
- Sistem Log panelinde yine DATA_GAP spam gözükür
- Test Flow 4zg'yi test_static_contracts.py'dan kaldırmak gerekir

---

## 9. Kalan İşler

- Atomik commit (4 dosya: data_pipeline.py, test_static_contracts.py, USTAT_GELISIM_TARIHCESI.md, bu rapor)
- Sonraki backlog maddesi: A7 (B21) — Baseline tekilleştirme
