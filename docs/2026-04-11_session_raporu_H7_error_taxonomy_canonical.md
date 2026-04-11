# Oturum Raporu — 2026-04-11 — Widget Denetimi H7: Hata Takip Taxonomy Canonical Kaynak

**Oturum Türü:** Widget Denetimi Backlog — H7 (Düşük kritiklik)
**Sınıf:** C1 (Yeşil Bölge frontend utility + UI refactor — tek atomik değişiklik)
**Piyasa Durumu:** Kapalı (Pazar, Barış Zamanı)
**Commit:** (aşağıda)
**Oturum Süresi:** ~50 dakika

---

## 1. Bulgu Bağlamı

Widget Denetimi v6.0 (`docs/2026-04-11_widget_denetimi.md`) Bölüm 16.3 Bulgu H7 (Düşük kritiklik):

> **H7 — Hata Takip kategori/severity sabitleri drift.** `ErrorTracker.jsx` içinde `CATEGORY_COLORS`, `SEVERITY_COLORS`, kategori filtre seçenekleri frontend sabit dizisi olarak hardcode ediliyor — backend `engine/error_tracker.py` ERROR_CATEGORIES değişirse frontend sessizce kopar.

Backend tek doğru kaynak iken frontend hardcode dict'leri sessizce kopabilirdi. Bu görev drift yüzeyini **tek canonical modüle** taşıdı ve **statik sözleşme testi** ile backend ile sync'i CI'da garanti etti.

---

## 2. Kök Neden Analizi

### 2.1 Drift Yüzeyi Envanteri

`ErrorTracker.jsx` içinde 5 ayrı drift sahası bulundu:

| # | Konum | Tip | Hücre Sayısı | İçerik |
|---|-------|-----|--------------|--------|
| 1 | Satır 37-46 | `const CATEGORY_COLORS = { ... }` | 8 key | Backend kategori → hex renk |
| 2 | Satır 48-53 | `const SEVERITY_COLORS = { ... }` | 4 key | Backend severity → hex renk |
| 3 | Satır 55-59 | `const SEVERITY_LABELS = { ... }` | 3 key | Severity → UPPERCASE Türkçe badge |
| 4 | Satır 406-414 | Kategori filtre `options=[]` literal | 7 öğe | `{ value, label }` Title Case |
| 5 | Satır 420-424 | Severity filtre `options=[]` literal | 3 öğe | `{ value, label }` Title Case |

5 ayrı yer, 4 ayrı bilgi türü, sıfır canonical sözleşme.

### 2.2 Backend Canonical Kaynağı

`engine/error_tracker.py` iki canonical yapı:

**`ERROR_CATEGORIES` (satır 32-63)** — error_type → kategori dict:
```
MT5_DISCONNECT/MT5_RECONNECT/MT5_TIMEOUT → "bağlantı"
ORDER_REJECT/ORDER_TIMEOUT/ORDER_FILL_PARTIAL/SLTP_MODIFY_FAIL/
TRADE_ERROR/MANUAL_TRADE_ERROR                           → "emir"
KILL_SWITCH/DRAWDOWN_LIMIT/RISK_LIMIT/FLOATING_LIMIT/
COOLDOWN/EARLY_WARNING                                    → "risk"
FAKE_SIGNAL/SIGNAL_REJECTED                               → "sinyal"
NETTING_MISMATCH/VOLUME_MISMATCH/EXTERNAL_CLOSE          → "netting"
DATA_ANOMALY/DATA_STALE                                   → "veri"
DB_ERROR/CYCLE_OVERRUN/IPC_ERROR                         → "sistem"
UNKNOWN                                                   → "diğer"
```

Unique values seti: **8 kategori** = `{bağlantı, emir, risk, sinyal, netting, veri, sistem, diğer}`

**`SEVERITY_PRIORITY` (satır 66-72)**:
```
CRITICAL=4, ERROR=3, WARNING=2, INFO=1, DEBUG=0
```

Unique keys seti: **5 seviye**.

### 2.3 Drift Riski Senaryosu

Backend takımı yeni bir kategori eklediğinde (örnek: `LIQUIDITY_HALT` → `"likidite"`):
- `error_tracker.py::ERROR_CATEGORIES` güncellenir
- `g.category = "likidite"` döner
- Frontend `CATEGORY_COLORS["likidite"]` → `undefined`
- Render: `background: undefined + '22'` → CSS NaN, badge bozulur
- Filtre dropdown: kullanıcı `"likidite"` filtreleyemez
- Sessiz başarısızlık. Hiçbir test, hiçbir uyarı.

Bu görev bu senaryoyu tamamen elimine etmek için yapıldı.

### 2.4 UX İstisnaları (Drift Değil, Bilinçli Tercih)

İki UX kararı drift olarak yorumlanmamalı:

1. **`"diğer"` filtre dropdown'unda gösterilmez** — `UNKNOWN` fallback'i filtrelemenin anlamı yok. Ama `CATEGORY_COLORS`'ta kalır çünkü bilinmeyen tip rozet için renk gerekir.
2. **`INFO` ve `DEBUG` filtre dropdown'unda gösterilmez** — `error_tracker.py::_load_existing_groups` (satır 192-194) zaten yalnız `WARNING/ERROR/CRITICAL` yükler. Frontend de aynı set üzerinde filtre uygular.

Canonical modülde bu iki UX kararı `CATEGORY_FILTER_EXCLUDE = new Set(['diğer'])` ve `INFO/DEBUG hariç` yorumlarıyla **explicit olarak belgelenmiştir**.

---

## 3. Çözüm Uygulaması

### 3.1 `desktop/src/utils/errorTaxonomy.js` (canonical kaynak — 100 satır)

Modül başında 50+ satırlık JSDoc açıklaması:
- Backend sözleşmesi (`ERROR_CATEGORIES.values()` ve `SEVERITY_PRIORITY` keys ile sync zorunluluğu)
- Drift koruma testi atfı (Flow 4z)
- 3 UX istisnası (`diğer` exclude, `INFO/DEBUG` exclude, badge UPPERCASE vs filter Title Case)
- Hangi backend dosyasının/hangi satırın referans alındığı

Export'lar:
1. `CATEGORY_COLORS` — 8 key, sırası backend ile birebir
2. `CATEGORY_LABELS` — Turkish Title Case görünen adlar
3. `CATEGORY_FILTER_OPTIONS` — `Object.keys(CATEGORY_COLORS).filter(c => !CATEGORY_FILTER_EXCLUDE.has(c)).map(...)` — derived array
4. `SEVERITY_COLORS` — 4 key (CRITICAL/ERROR/WARNING/INFO)
5. `SEVERITY_LABELS` — 3 UPPERCASE badge etiketi (mevcut davranış)
6. `SEVERITY_FILTER_OPTIONS` — 3 Title Case dropdown öğesi (`SEVERITY_FILTER_LABELS` mapping'inden derived)

### 3.2 `desktop/src/components/ErrorTracker.jsx` Refactor

Silinen (23 satır):
- `const CATEGORY_COLORS = { ... }` (8 key bloğu)
- `const SEVERITY_COLORS = { ... }` (4 key bloğu)
- `const SEVERITY_LABELS = { ... }` (3 key bloğu)

Eklenen:
```javascript
// Widget Denetimi H7: Kategori/severity renkleri, etiketleri ve filtre
// seçenekleri frontend canonical modülüne (errorTaxonomy.js) taşındı.
// (...)
import {
  CATEGORY_COLORS,
  SEVERITY_COLORS,
  SEVERITY_LABELS,
  CATEGORY_FILTER_OPTIONS,
  SEVERITY_FILTER_OPTIONS,
} from '../utils/errorTaxonomy';
```

Filtre options literal'leri:
```javascript
// Önceki:
options={[
  { value: 'bağlantı', label: 'Bağlantı' },
  { value: 'emir', label: 'Emir' },
  // ... 7 öğe
]}

// Sonrası:
options={CATEGORY_FILTER_OPTIONS}
```

Aynı pattern severity filter için. Net etki: 23 satır silindi, 16 satır (import + yorumlar + 2 options değişimi) eklendi. Bundle boyutu fark: +0.01 kB net.

### 3.3 Statik Sözleşme Testi — Flow 4z

`tests/critical_flows/test_static_contracts.py`'a **Flow 4z** (`test_error_taxonomy_backend_sync`) eklendi. **6 aşamalı koruma:**

**(a)** Canonical modül + 5 export var:
```python
for export_name in ("CATEGORY_COLORS", "SEVERITY_COLORS", "SEVERITY_LABELS",
                    "CATEGORY_FILTER_OPTIONS", "SEVERITY_FILTER_OPTIONS"):
    assert re.search(rf"export\s+const\s+{export_name}\b", tax_src)
```

**(b)** Backend `ERROR_CATEGORIES` parse → unique values seti → frontend `CATEGORY_COLORS` keys seti ile **EXACT match**:
```python
err_cat_match = re.search(r"ERROR_CATEGORIES\s*=\s*\{(.*?)\}", backend_src, re.DOTALL)
backend_cats = set(re.findall(r":\s*\"([^\"]+)\"", err_cat_match.group(1)))

cat_colors_match = re.search(r"export\s+const\s+CATEGORY_COLORS\s*=\s*\{(.*?)\};", tax_src, re.DOTALL)
frontend_cats = set(re.findall(r"'([^']+)'\s*:", cat_colors_match.group(1)))

missing_in_frontend = backend_cats - frontend_cats
extra_in_frontend = frontend_cats - backend_cats
assert not missing_in_frontend
assert not extra_in_frontend
```

İki yönlü set fark testi — backend yeni eklerse VE frontend stale kalırsa veya frontend'de hayalet kategori varsa CI FAIL eder.

**(c)** Backend `SEVERITY_PRIORITY` keys → frontend `SEVERITY_COLORS` keys alt küme kontrolü (frontend INFO/DEBUG göstermese bile drift olmamalı).

**(d)** `ErrorTracker.jsx` içinde yerel `const CATEGORY_COLORS|SEVERITY_COLORS|SEVERITY_LABELS =` tanımı YASAK (multiline regex). Biri yanlışlıkla geri eklerse test FAIL eder.

**(e)** `ErrorTracker.jsx` `from '../utils/errorTaxonomy'` import'unu yapıyor olmalı.

**(f)** `Widget Denetimi H7` marker yorumu `errorTaxonomy.js`'te mevcut — canonical kaynak rolu/atif kaybolmasın.

**Test çift yönlülüğü:** (b) kritik — backend ekler frontend güncellemezse FAIL, frontend ekler backend güncellemezse de FAIL. Tek yönlü senkronizasyon yetersizdi (örneğin frontend'de hayalet kategori bırakmak da bug yüzeyi).

---

## 4. Test ve Build Sonuçları

### 4.1 `tests/critical_flows` — 59 passed (ilk koşuda yeşil)

```
59 passed, 3 warnings in 3.37s
```

Baseline 58 (H13 sonrası) + Flow 4z = 59. Yorum self-poisoning yok — Flow 4z testinde literal `CATEGORY_COLORS` / `SEVERITY_COLORS` / `SEVERITY_LABELS` string'leri var ama (d) assertion regex pattern'ı `^\s*const\s+(?:CATEGORY_COLORS|...)` kullanıyor — yani SADECE satır başında `const NAME =` formatını arar, herhangi bir yorum veya import veya diğer kullanım tetiklemez. ErrorTracker.jsx'de bu pattern yok (silindi); test geçer.

### 4.2 Windows Production Build — Başarılı

```
ustat-desktop@6.0.0 build
vite v6.4.1 building for production...
729 modules transformed.
dist/index.html                  1.07 kB │ gzip:   0.60 kB
dist/assets/index-CiUWDTb0.css  90.52 kB │ gzip:  15.07 kB
dist/assets/index-v6FJD-qa.js  889.87 kB │ gzip: 255.19 kB
✓ built in 2.64s
```

Modül sayısı: 728 → **729** (+1: yeni `errorTaxonomy.js`).
Bundle boyutu: 889.86 kB → **889.87 kB** (+0.01 kB net — yeni modül + 5 export'lu import 23 satır silinen yerel `const`'larla dengelendi).

---

## 5. Anayasa Uyumu

| Kural | Uyum |
|-------|------|
| Çağrı sırası | Backend dokunulmadı — motor sırası etkilenmedi |
| Kırmızı Bölge | Dokunulmadı — `engine/error_tracker.py` SADECE OKUNDU (test parse'i için), değiştirilmedi |
| Sarı Bölge | Dokunulmadı |
| Siyah Kapı (31 fonksiyon) | Dokunulmadı |
| Sözleşme tek yönlü | Backend canonical, frontend ayna — test backend → frontend yönünü zorlar |
| Geri alma planı | `git revert HEAD` — 5 dosya tek commit, geri dönüş 1 komut |
| Test disiplini | Flow 4z statik sözleşme; CI'da drift mümkün değil |
| Piyasa zamanlaması | Pazar → Barış Zamanı |

**Davranışsal eşdeğerlik:** Bit-level identical. Kullanıcı UI'da farklı renk, farklı etiket, farklı dropdown sırası görmez.

---

## 6. Dosya Listesi

| Dosya | Değişiklik | Kategori |
|-------|-----------|----------|
| `desktop/src/utils/errorTaxonomy.js` | +100/-0 (yeni canonical modül) | Frontend utility |
| `desktop/src/components/ErrorTracker.jsx` | +16/-23 (import + 2 options değişimi - yerel 3 const) | Frontend UI |
| `tests/critical_flows/test_static_contracts.py` | +130/-0 (Flow 4z) | Test |
| `docs/USTAT_GELISIM_TARIHCESI.md` | +1 (#189) | Changelog |
| `docs/2026-04-11_session_raporu_H7_error_taxonomy_canonical.md` | +N (bu dosya) | Oturum raporu |

**Toplam:** 5 dosya, 0 Siyah Kapı dokunusu, 0 Kırmızı/Sarı Bölge dokunusu, 0 config değişikliği, 0 backend değişikliği, 0 CSS değişikliği, 0 API değişikliği.

---

## 7. Risk ve Geri Alma

**Risk profili:** Sıfır (frontend UI refactor, davranışsal eşdeğer, backend yalnız okundu).

**Geri alma:** `git revert HEAD --no-edit` → `python .agent/claude_bridge.py build` → `python .agent/claude_bridge.py restart_app`. Tek commit olduğu için geri dönüş tek komuttur.

---

## 8. Sonraki Audit Maddesi

Widget Denetimi backlog'da kalan **Düşük** kritiklik tek madde:

- **H16 — Hibrit Devir operator identity hardcode:** `HybridTrade.jsx` `approveTrade(id, 'operator', '')` çağrısında kullanıcı kimliği sabit string. Bu daha geniş kapsam — Settings'te operatör adı state'i + LocalStorage persistance + approveTrade çağrı sitelerinin parametre değişimi gerektirir. Audit notu A27 ile birlikte değerlendirilmeli.

H7 tamamen kapandı. Audit tarafında **Düşük** kritiklik bölümü neredeyse temizlendi (H16 hariç hepsi yapıldı: H8, H9, H11, H12, H13, H18). Bir sonraki "Devam edelim" turunda H16 değerlendirilecek.
