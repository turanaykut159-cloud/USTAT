# Oturum Raporu — A26 (K4): NABIZ retention_covered bars çelişkisi

**Tarih:** 12 Nisan 2026
**Kategori:** Widget Denetimi — Priority 4 (K4 kritik)
**Sınıf:** C1 (Yeşil Bölge route + frontend)
**Kapsam:** 1 backend route + 1 frontend + 1 test + 1 changelog + 1 rapor
**Durum:** Tamamlandı — atomik commit hazır

---

## 1. Sorun Tanımı

Widget Denetimi K4 / A26 bulgusu: `api/routes/nabiz.py` içindeki
`_build_cleanup_conflict_info(engine)` sensörü iki kritik hata içeriyordu.

### Hata 1 — Kod yorumu vs. `retention_covered` set çelişkisi

Fonksiyonun docstring'i açıkça söylüyordu:

> v5.9.3: Cleanup artik sadece bars temizliyor.

Ama `retention_covered` set'i `bars`'ı **içermiyordu**:

```python
retention_covered = {
    "risk_snapshots", "top5_history", "events",
    "config_history", "liquidity_classes", "hybrid_positions",
    "trades",
}
```

Aşağıdaki `growing_tables` taraması şöyleydi:

```python
for table, count in sizes.items():
    if table in ("app_state", "strategies"):
        continue
    if table not in retention_covered and count > 0:
        growing_tables[table] = count
```

Sonuç: `bars` tablosu (audit anında 183,078 satır) bu tarama tarafından
"retention YOK" olarak listeleniyor ve frontend `MissingRetentionPanel`
üzerinden kullanıcıya `bars → retention YOK (183,078 satir)` şeklinde
raporlanıyordu. **Yanlış sinyal:** Bars aslında `run_cleanup()` tarafından
yönetiliyor; kullanıcı "bu tablo unutulmuş" sanıyordu.

### Hata 2 — `has_conflict` sensörü kör

`has_conflict` sadece retention tamamen kapalıyken True dönüyordu:

```python
has_conflict = len(affected) > 0
# affected sadece retention_enabled=False iken doluyor
```

Bars 183,078 satırla `NABIZ_TABLE_ROW_THRESHOLDS["bars"]["danger"] = 150,000`
eşiğini aşmış olmasına rağmen conflict accordion'u (`ConflictWarning`)
gizli kalıyordu. **Erken uyarı körü:** Operatör NABIZ sayfasına girmeden
eşik aşımını fark edemiyordu.

---

## 2. Kök Sebep

Üç katman birden:

1. **Semantik ayrım eksikliği:** `retention_covered` set'i retention VE
   cleanup kapsamını birlikte temsil etmeye çalışıyordu. `run_cleanup()`
   sadece bars'ı temizliyor (v5.9.3) — bu ayrı kümede tutulmalıydı.
2. **Sensör dar kapsamlı:** `has_conflict` sadece bir (1) tetikleyiciyi
   izliyordu (retention-off). Gerçek bir "eşik aşımı" sensörü yoktu.
3. **Frontend pasif:** UI sadece `missing_retention` listesini gösteriyordu;
   eşik aşımı için ayrı bir paneli yoktu.

---

## 3. Çözüm

### 3a) `api/routes/nabiz.py::_build_cleanup_conflict_info`

**(i) Yönetim kapsamı iki kümeye ayrıldı:**

```python
# A26 (K4): Yonetim kapsami iki ayri kumeden olusur:
#   retention_covered → run_retention() ile yonetilir
#   cleanup_covered   → run_cleanup() ile yonetilir (v5.9.3 sonrasi sadece bars)
retention_covered = {
    "risk_snapshots", "top5_history", "events",
    "config_history", "liquidity_classes", "hybrid_positions",
    "trades",  # trade_archive_days ile kapsaniyor
}
cleanup_covered = {"bars"}
managed_tables = retention_covered | cleanup_covered
```

`growing_tables` taraması artık `managed_tables` birleşimini kullanıyor:

```python
if table not in managed_tables and count > 0:
    growing_tables[table] = count
```

Bars artık `missing` listesinden çıktı — kullanıcıya yanlış sinyal yok.

**(ii) `critical_over_threshold` taraması — yeni sensör:**

```python
# A26 (K4): Kirmizi esik taramasi — NABIZ_TABLE_ROW_THRESHOLDS'daki HER tablo
# icin danger esigini kontrol et. Tablo yonetim altinda OLSA BILE danger'i
# asmissa cakisma sayilir.
critical_over_threshold = []
for table, thresholds in NABIZ_TABLE_ROW_THRESHOLDS.items():
    count = sizes.get(table, 0)
    danger = thresholds.get("danger", 0)
    if danger > 0 and count >= danger:
        if table in cleanup_covered:
            managed_by = "cleanup"
        elif table in retention_covered:
            managed_by = "retention"
        else:
            managed_by = "UNMANAGED"
        critical_over_threshold.append({
            "table": table,
            "count": count,
            "danger_threshold": danger,
            "managed_by": managed_by,
            "risk": (
                f"{table} danger esigini asti ({count:,} >= {danger:,}) — "
                f"yonetim={managed_by}, retention/cleanup siklastirilmali"
            ),
        })
```

**(iii) `has_conflict` üç katmanlı:**

```python
has_conflict = (
    len(affected) > 0
    or len(missing) > 0
    or len(critical_over_threshold) > 0
)
```

Bars 150k eşiğini aşarsa `has_conflict=True` olur ve `ConflictWarning`
accordion'u otomatik görünür.

**(iv) Description dinamik:**

```python
if has_conflict:
    parts = []
    if affected:
        parts.append(f"{len(affected)} retention-off uyarisi")
    if missing:
        parts.append(f"{len(missing)} yonetimsiz tablo")
    if critical_over_threshold:
        parts.append(f"{len(critical_over_threshold)} tablo kirmizi esikte")
    description = "Cakisma tespit: " + ", ".join(parts) + "."
else:
    description = (
        "Cakisma yok — cleanup ve retention uyumlu, "
        "tum izlenen tablolar esik altinda."
    )
```

**(v) Return payload'a `critical_over_threshold` alanı eklendi** (additive).

### 3b) `desktop/src/components/Nabiz.jsx`

Yeni `CriticalOverThresholdPanel` bileşeni eklendi:

```jsx
function CriticalOverThresholdPanel({ items }) {
  if (!items || items.length === 0) return null;

  return (
    <div style={styles.criticalPanel}>
      <div style={styles.panelHeader}>
        <h3 style={{ ...styles.panelTitle, color: COLORS.red }}>
          ⚠ Kritik Esik Asimi
        </h3>
        <span style={{ fontSize: 11, color: COLORS.dim }}>{items.length} tablo</span>
      </div>
      <div style={styles.missingGrid}>
        {items.map((item, i) => (
          <div key={i} style={styles.criticalItem}>
            <div style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 600 }}>
              {item.table}
            </div>
            <div style={{ fontSize: 11, color: COLORS.red, marginTop: 4 }}>
              {formatNumber(item.count)} / {formatNumber(item.danger_threshold)}
            </div>
            <div style={{ fontSize: 10, color: COLORS.dim, marginTop: 2 }}>
              yonetim: {item.managed_by}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

Render ağacına `MissingRetentionPanel` altına eklendi:

```jsx
{/* Widget Denetimi A26 (K4): Kritik esik asimi paneli */}
<CriticalOverThresholdPanel items={conflict.critical_over_threshold || []} />
```

Stil sınıfları `styles.criticalPanel` ve `styles.criticalItem` eklendi
(kırmızı ton, `rgba(248,81,73,0.05)` background, `rgba(248,81,73,0.3)`
border). Missing paneli sarı tonda kalır; kritik panel kırmızı — operatör
ikisini ayırt edebilir.

### 3c) `tests/critical_flows/test_static_contracts.py`

**Flow 4zk** eklendi: `test_nabiz_cleanup_conflict_bars_coverage_and_critical_scan`.
7 sözleşme noktası:

1. `cleanup_covered = {"bars"}` tanımı
2. `managed_tables = retention_covered | cleanup_covered` birleşimi +
   `table not in managed_tables` kontrolü
3. `NABIZ_TABLE_ROW_THRESHOLDS` iterasyonu + `count >= danger` eşik kontrolü
4. `critical_over_threshold` listesi tanımı
5. `has_conflict` üç katmanlı ifadesi (affected + missing + critical_over_threshold)
6. Return payload'da `"critical_over_threshold": critical_over_threshold` alanı
7. Frontend `CriticalOverThresholdPanel` fonksiyonu + `<CriticalOverThresholdPanel items={conflict.critical_over_threshold...` render çağrısı
8. A26 audit markerları (`api/routes/nabiz.py` + `Nabiz.jsx`)

### 3d) `docs/USTAT_GELISIM_TARIHCESI.md`

**#200** girişi #199 üzerine eklendi.

---

## 4. Test Sonuçları

```
python -m pytest tests/critical_flows -q
========================
70 passed, 3 warnings in 3.28s
========================
```

Baseline 69 → 70 (Flow 4zk eklendi).

---

## 5. Build Sonuçları

(Windows agent ile build adımı commit'ten önce çalıştırılacak.)

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
| Retention politikası | Değişmedi |
| Cleanup politikası | Değişmedi |
| Events/bars tablo şemaları | Değişmedi |
| Sihirli sayı | Yok (NABIZ_TABLE_ROW_THRESHOLDS tek kaynak) |

**Değişiklik sınıfı:** C1 — Yeşil Bölge route + frontend defansif
sertleştirme. Sensör doğruluk katmanı.

---

## 7. Kalan İşler

- Build doğrulama (Windows agent)
- Atomik commit (5 dosya: nabiz.py, Nabiz.jsx, test_static_contracts.py,
  USTAT_GELISIM_TARIHCESI.md, bu rapor)
- Sonraki madde: Backlog'daki bir sonraki açık bulgu
