# Oturum Raporu — Widget Denetimi H8 + H9: NABIZ Eşik Değerleri Canonical Kaynağa Bağlandı

**Tarih:** 2026-04-11 (Pazar, Barış Zamanı)
**Değişiklik Sınıfı:** C1 — Yeşil Bölge (3 kod dosyası + 1 test)
**Kaynak:** `docs/2026-04-11_widget_denetimi.md` Bölüm 13.1 + 13.2 + 16.3 H8 (Orta) + H9 (Düşük)
**Versiyon:** v6.0.0 (bump yok — değişiklik oranı eşik altı)
**Commit:** #184
**Piyasa:** Kapalı (Pazar, Barış Zamanı — refactor serbest)

---

## 1. Kapsam

NABIZ Sistem Monitörü sayfasında üç farklı noktada dağılmış hardcode eşik/limit değerleri tek bir canonical kaynağa (backend modülü `api/routes/nabiz.py`) bağlandı. Frontend `Nabiz.jsx` artık eşikleri `/api/nabiz.thresholds` alanından okuyor, backend erişilemezse `DEFAULT_*` fallback ile sayfanın boş görünmesi engelleniyor.

H8 ve H9 aynı commit'te birleştirildi çünkü ikisi de `Nabiz.jsx` aynı dosyasına dokunuyor ve audit tarafından "aynı mimari sorun — hardcode UI politikaları" olarak etiketlenmiş.

## 2. Kök Neden

`Nabiz.jsx` üç ayrı noktada hardcode değerler barındırıyordu:

1. **TABLE_THRESHOLDS dict** (~15 tablo): `bars: {warn: 50000, danger: 150000}`, `trades: {warn: 5000, danger: 20000}`, ... şeklinde 15 VİOP tablosu için warn/danger eşikleri frontend'de bir const olarak tutuluyordu. `getRowColor(name, count)` bu dict'i okuyup tablo satırlarına sarı/kırmızı renk veriyordu.

2. **SummaryCard inline magic patterns**: "Veritabanı", "Loglar" ve "Disk" kartlarının render'ında 6 ayrı sihirli sayı iç içe ternary'lerle karışmış durumdaydı:
   - `db.file_size_mb > 1000 ? red : db.file_size_mb > 500 ? yellow : cyan`
   - `logs.total_size_mb > 2000 ? red : ... > 500 ? yellow : cyan`
   - `disk.usage_pct > 90 ? red : ... > 80 ? yellow : cyan`

3. **LogFilesPanel**: `files.slice(0, 15)` — log dosyası listesi sabit 15'e kırpılıyordu.

Audit Bölüm 13.1 + 16.3 H8 (Orta): "🧱 TABLE_THRESHOLDS frontend hardcode — backend canonical kaynak olmalı". Audit Bölüm 13.2 + H9 (Düşük): "🧱 `files.slice(0,15)` — config'den okunmalı".

## 3. Canonical Kaynak Kararı

Audit ipucu "config'den okunmalı" diyordu ama `config/default.json` **Kırmızı Bölge** (Anayasa Bölüm 4.1 #8). Orada değişiklik yapmak çift doğrulama + kullanıcı açık onayı gerektirir. Bu eşikler ise **UI-only soft threshold** — motor/risk/kill-switch davranışına etkisi SIFIR, yalnızca NABIZ sayfasında renk/alarm görsel politikası.

Pattern A-H3 (`engine/mt5_bridge.py::WATCHED_SYMBOLS`) ile aynı mantık uygulandı: canonical kaynak olarak **Yeşil Bölge backend modülü** `api/routes/nabiz.py` seçildi. Config yerine kod kaynaklı olmasının üç nedeni:

1. **Tek kaynak netliği**: Config + kod paralel çalışsaydı "hangi doğru?" belirsizliği oluşurdu.
2. **Yetki ayrımı**: UI politikası UI ekibinin kontrolünde olmalı; config risk/motor ekibinin.
3. **Geleceğe uyum**: Kullanıcı özelleştirmesi istenirse `config.nabiz.*` anahtarları eklenip helper'da merge edilebilir (kod + config → merged dict).

## 4. Yapılan Değişiklikler

### 4.1 `api/routes/nabiz.py` (Yeşil Bölge, +~50 satır)

Modül seviyesinde üç canonical sabit eklendi:

```python
NABIZ_TABLE_ROW_THRESHOLDS: dict[str, dict[str, int]] = {
    "bars":                 {"warn": 50000, "danger": 150000},
    "trades":               {"warn": 5000,  "danger": 20000},
    "risk_snapshots":       {"warn": 20000, "danger": 100000},
    "events":               {"warn": 10000, "danger": 50000},
    "top5_history":         {"warn": 5000,  "danger": 20000},
    "notifications":        {"warn": 2000,  "danger": 10000},
    "daily_risk_summary":   {"warn": 500,   "danger": 2000},
    "weekly_top5_summary":  {"warn": 500,   "danger": 2000},
    "config_history":       {"warn": 500,   "danger": 2000},
    "manual_interventions": {"warn": 200,   "danger": 1000},
    "hybrid_positions":     {"warn": 500,   "danger": 2000},
    "hybrid_events":        {"warn": 2000,  "danger": 10000},
    "strategies":           {"warn": 100,   "danger": 500},
    "liquidity_classes":    {"warn": 1000,  "danger": 5000},
    "app_state":            {"warn": 50,    "danger": 200},
}

NABIZ_SUMMARY_THRESHOLDS: dict[str, float] = {
    "database_mb_warn": 500.0,
    "database_mb_err":  1000.0,
    "log_mb_warn":      500.0,
    "log_mb_err":       2000.0,
    "disk_pct_warn":    80.0,
    "disk_pct_err":     90.0,
}

NABIZ_LOG_FILES_DISPLAY_LIMIT: int = 15
```

Üç sabitin üstünde 20+ satırlık yorum bloğu: H8/H9 audit arka planı, canonical kaynak kararının nedeni, gelecek kullanıcı özelleştirme yolu, regresyon koruma test referansı (Flow 4u).

Yeni helper fonksiyonu `_build_thresholds_info()` üç sabiti tek bir dict'e paketler:

```python
def _build_thresholds_info() -> dict:
    return {
        "table_row_thresholds": dict(NABIZ_TABLE_ROW_THRESHOLDS),
        "summary": dict(NABIZ_SUMMARY_THRESHOLDS),
        "log_files_display_limit": NABIZ_LOG_FILES_DISPLAY_LIMIT,
        "source": "api.routes.nabiz",
    }
```

`get_nabiz()` response dict'ine yeni alan eklendi:

```python
result = {
    "timestamp": ...,
    "database": _build_database_info(db),
    "logs": _build_log_info(),
    "disk": _build_disk_info(),
    "retention": _build_retention_info(engine),
    "cleanup_conflict": _build_cleanup_conflict_info(engine),
    "thresholds": _build_thresholds_info(),   # ← yeni
}
```

Mevcut helper fonksiyonlar (`_build_database_info`, `_build_log_info`, vs.) **DOKUNULMADI** — davranış aynı.

### 4.2 `desktop/src/components/Nabiz.jsx` (Yeşil Bölge, ~120 satır net değişim)

Eski hardcode `const TABLE_THRESHOLDS = {...}` tamamen kaldırıldı. Yerine üç fallback sabiti geldi:

```jsx
const DEFAULT_TABLE_THRESHOLDS = { /* 15 tablonun kopyası */ };
const DEFAULT_SUMMARY_THRESHOLDS = {
  database_mb_warn: 500, database_mb_err: 1000,
  log_mb_warn: 500, log_mb_err: 2000,
  disk_pct_warn: 80, disk_pct_err: 90,
};
const DEFAULT_LOG_FILES_DISPLAY_LIMIT = 15;
```

`DEFAULT_*` prefix'i kod okurken "bu hardcode değil, backend çalışmazsa güvenli default" kastını net ediyor.

`getRowColor(table, count, tableThresholds)` imzası üçüncü parametre aldı (opsiyonel, default `DEFAULT_TABLE_THRESHOLDS`).

Yeni saf fonksiyon `pickSummaryStatus(value, warn, err)`:

```jsx
function pickSummaryStatus(value, warn, err) {
  if (value > err) return 'err';
  if (value > warn) return 'warn';
  return 'ok';
}
```

Ana bileşende threshold ekstraksiyonu:

```jsx
const thresholds = data?.thresholds || {};
const tableRowThresholds = thresholds.table_row_thresholds || DEFAULT_TABLE_THRESHOLDS;
const summaryThresholds = thresholds.summary || DEFAULT_SUMMARY_THRESHOLDS;
const logFilesDisplayLimit = Number.isFinite(thresholds.log_files_display_limit)
  ? thresholds.log_files_display_limit
  : DEFAULT_LOG_FILES_DISPLAY_LIMIT;

const dbStatus = pickSummaryStatus(dbSizeMb, summaryThresholds.database_mb_warn, summaryThresholds.database_mb_err);
const logStatus = pickSummaryStatus(logSizeMb, summaryThresholds.log_mb_warn, summaryThresholds.log_mb_err);
const diskStatus = pickSummaryStatus(diskPct, summaryThresholds.disk_pct_warn, summaryThresholds.disk_pct_err);
const diskColor = diskStatus === 'err' ? COLORS.red : diskStatus === 'warn' ? COLORS.yellow : COLORS.cyan;
```

Üç SummaryCard artık bu durum değişkenlerini kullanıyor — inline `> 1000`, `> 500`, `> 2000`, `> 80`, `> 90` magic pattern'leri tamamen kaldırıldı.

`TableSizesPanel({ tables, tableRowThresholds })` ve `LogFilesPanel({ logs, displayLimit = DEFAULT_LOG_FILES_DISPLAY_LIMIT })` imzaları genişletildi. `files.slice(0, 15)` → `files.slice(0, displayLimit)`.

### 4.3 `tests/critical_flows/test_static_contracts.py` (Yeşil Bölge, +~85 satır)

Yeni test `test_nabiz_thresholds_are_backend_driven` (Flow 4u) Flow 5'ten önce eklendi. 6 aşamalı zincir kontrolü:

- **(a) Backend canonical**: `NABIZ_TABLE_ROW_THRESHOLDS`, `NABIZ_SUMMARY_THRESHOLDS`, `NABIZ_LOG_FILES_DISPLAY_LIMIT`, `def _build_thresholds_info`, `"thresholds": _build_thresholds_info()` ibareleri mevcut olmalı.
- **(b) Dict anahtar sayısı**: Regex ile `NABIZ_TABLE_ROW_THRESHOLDS` gövdesi parse edilir, key sayısı ≥10 olmalı (mevcut 15 tabloyu korur).
- **(c) Nabiz.jsx eski hardcode YASAK**: `const TABLE_THRESHOLDS = {` pattern'i dosyada olmamalı; `DEFAULT_TABLE_THRESHOLDS` fallback sabiti olmalı.
- **(d) Tüketim**: `data?.thresholds` okuma, `tableRowThresholds` state, `getRowColor(name, count, tableRowThresholds)` çağrısı.
- **(e) Inline magic YASAK**: `file_size_mb\s*>\s*1000`, `total_size_mb\s*>\s*2000`, `usage_pct\s*>\s*90` pattern'leri YASAK; `pickSummaryStatus` + `summaryThresholds` kullanımı mevcut.
- **(f) slice limit dinamik**: `files.slice(0, 15)` hardcode YASAK; `files.slice(0, displayLimit)` kullanımı mevcut.

## 5. Neden Populate Değil, Backend Canonical

Audit "config'den okunmalı" diyordu. Ama:

1. **Kırmızı Bölge koruması**: `config/default.json` dokunusu C3 gerektirir, risk parametresi olmayan UI-only eşikleri oraya taşımak Anayasa politikasıyla çelişir.
2. **Tek kaynak**: Pattern A-H3 ile aynı mantık. Backend modülü canonical, config kullanıcı override alanı (gelecekte).
3. **UI-motor ayrımı**: Bu eşikler kill-switch/drawdown/lot-size gibi motor kararlarını etkilemez — yalnızca NABIZ sayfası render politikası.
4. **Fallback garantisi**: Frontend `DEFAULT_*` fallback tutar, backend erişilemezse sayfa boş görünmez.

## 6. Anayasa Uyumu

- **Siyah Kapı**: Dokunulmadı. `get_nabiz` sadece SELECT/stat işler.
- **Kırmızı Bölge**: `config/default.json` **DOKUNULMADI**. `engine/database.py` **DOKUNULMADI**.
- **Sarı Bölge**: Dokunulmadı.
- **Yeşil Bölge**: 3 dosya (`api/routes/nabiz.py`, `desktop/src/components/Nabiz.jsx`, `tests/critical_flows/test_static_contracts.py`).
- **Çağrı sırası**: Değişmedi (BABA → OĞUL → H-Engine → ÜSTAT sabit).
- **Motor davranışı**: Aynı. Bu değişiklik yalnızca UI render politikası canonical kaynağını yeniden yerleştirdi.

## 7. Test + Build

**critical_flows**: 54/54 yeşil (53 baseline + yeni Flow 4u), 3.30s, 0 hata.

```
......................................................                   [100%]
54 passed, 3 warnings in 3.30s
```

**Windows `npm run build`**:

```
ustat-desktop@6.0.0 build
> vite build
vite v6.4.1 building for production...
✓ 728 modules transformed.
dist/index.html                   1.07 kB │ gzip:   0.60 kB
dist/assets/index-CiUWDTb0.css   90.52 kB │ gzip:  15.07 kB
dist/assets/index-BkQmj5O5.js   889.84 kB │ gzip: 255.04 kB
✓ built in 2.67s
```

Bundle boyutu: 889.84 kB (önceki commit 889.46 kB, +0.38 kB — `DEFAULT_*` fallback sabitler + `pickSummaryStatus` helper + threshold ekstraksiyon).

## 8. Versiyon

Değişiklik oranı eşik altı (3 dosya, ~250 satır ekleme, toplam proje ≥90k satır → oran %0.3, eşik %10). **Versiyon bump yapılmadı**. Mevcut: v6.0.0.

## 9. Değişen Dosyalar

| Dosya | Tür | Satır |
|-------|-----|-------|
| `api/routes/nabiz.py` | Backend | +~50 |
| `desktop/src/components/Nabiz.jsx` | Frontend | ~120 net |
| `tests/critical_flows/test_static_contracts.py` | Test | +~85 |
| `docs/USTAT_GELISIM_TARIHCESI.md` | Doküman | +1 girişi (#184) |
| `docs/2026-04-11_session_raporu_H8_nabiz_thresholds_backend_canonical.md` | Doküman | yeni |

## 10. Bilinçli Dokunulmayanlar

- `config/default.json` — Kırmızı Bölge + canonical yeri değil.
- `engine/database.py::get_table_sizes` — Kırmızı Bölge, zaten kaynak veriyi sağlıyor.
- `api/routes/nabiz.py::_build_database_info`, `_build_log_info`, `_build_disk_info`, `_build_retention_info`, `_build_cleanup_conflict_info` — davranış aynı, yalnız `_build_thresholds_info` helper'ı eklendi.
- `Nabiz.jsx::RetentionCard`, `CleanupConflictPanel` render bileşenleri — dokunulmadı.

## 11. Deploy Notu

Piyasa kapalı (Pazar, Barış Zamanı). Deploy için `python .agent/claude_bridge.py restart_app` yeterli — hem backend route hem Electron bundle yenilenir. Production'da canlı risk/kill-switch davranışı etkilenmez.

## 12. Sonuç

Widget Denetimi H8 (Orta) + H9 (Düşük) birleşik fix'i tamamlandı. NABIZ sayfası eşik değerleri artık tek canonical kaynak olan `api/routes/nabiz.py` modül sabitlerinden akıyor; frontend `DEFAULT_*` fallback ile backend erişilemezlik durumunda da güvenli davranıyor. Flow 4u statik sözleşme testi regresyon koruması sağlıyor — gelecek refactor sırasında hardcode eşikler geri eklenirse pre-commit hook commit'i bloklar.

**Siyah Kapı dokunusu: 0. Kırmızı Bölge dokunusu: 0. Motor davranışı: aynı. Risk: sıfır.**
