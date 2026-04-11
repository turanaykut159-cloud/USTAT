# Oturum Raporu — A5 / H1: Versiyon Tek Kaynak Tekilleştirme

**Tarih:** 11 Nisan 2026 (Cumartesi — Barış Zamanı)
**Oturum:** Widget Denetimi A5 fix
**Sınıf:** C1 — Yeşil Bölge (backend route + 3 frontend bileşen + api.js fallback + 1 test)
**Commit:** (bu raporla birlikte — ayrıca git log'da görülür)
**Audit Kaynağı:** `docs/2026-04-11_widget_denetimi.md` Bölüm 2.1 + 16.3 H1 + 17 A5

---

## 1. Amaç

Widget Denetimi audit'i Bölüm 2.1 ve 16.3 H1 tek bir hardcode anti-pattern'ini tespit etti: `TopBar.jsx`, `LockScreen.jsx`, `Settings.jsx` üç ayrı UI bileşeni kendi hardcode versiyon stringini (`V6.0` / `const VERSION = '6.0.0'`) içeriyordu. Tek kaynak principle ihlali: yeni major/minor release yapıldığında geliştirici üç dosyayı manuel güncellemek zorunda. Audit `engine/__init__.py::VERSION`'ı tek kaynak olarak işaretledi.

Hedef: Üç frontend bileşenin de versiyon etiketini `engine/__init__.py::VERSION` → `/api/status.version` zinciri üzerinden okuması. `V6.0` display formatı korunur (minimum görsel değişiklik).

## 2. Kök Neden Analizi

- `engine/__init__.py::VERSION = "6.0.0"` — canonical single source of truth (değişmedi).
- `api/schemas.py::StatusResponse.version` alanı satır 19'da `str = "6.0.0"` default ile zaten vardı — ama runtime'da `api/routes/status.py::get_status()` bu alanı doldurmuyordu, schema default'a düşüyordu.
- `desktop/src/components/TopBar.jsx` satır ~150: `<h1>ÜSTAT Plus <span className="version">V6.0</span></h1>` hardcode.
- `desktop/src/components/Settings.jsx` satır 11: `const VERSION = '6.0.0'` hardcode + iki FieldRow kullanımı.
- `desktop/src/components/LockScreen.jsx`: `<h1>ÜSTAT Plus <span className="version">V6.0</span></h1>` hardcode.

`api/routes/status.py` zaten 2 saniyede bir `TopBar` tarafından polling yapılıyor, `Settings.jsx` mount'ta status fetch ediyor, `Dashboard.jsx` da status fetch ediyor. Yani TopBar + Settings için yeni fetch gerekmiyor — mevcut status state'i yeterli. Sadece `LockScreen` pre-auth olduğu için kendi fetch'ini eklemek gerekti.

## 3. Değişiklikler (6 dosya)

### 3.1 Backend

- **`api/routes/status.py`** — `from engine import VERSION as ENGINE_VERSION` import eklendi; `get_status()` return bloğuna `version=ENGINE_VERSION` atama eklendi. Schema değişikliği yok (alan zaten mevcuttu).

### 3.2 Frontend

- **`desktop/src/services/api.js::getStatus`** — fallback objesine `version: '6.0.0'` eklendi. Backend erişilemezse dahi UI kırılmaz.
- **`desktop/src/components/TopBar.jsx`** — hardcode `V6.0` KALDIRILDI; yeni `const versionLabel = (status.version || '6.0.0').split('.').slice(0, 2).join('.')` hesaplaması; `<h1>ÜSTAT Plus <span className="version">V{versionLabel}</span></h1>`.
- **`desktop/src/components/Settings.jsx`** — `const VERSION = '6.0.0'` KALDIRILDI → `const VERSION_FALLBACK = '6.0.0'`; iki FieldRow `ÜSTAT Plus V{(status?.version || VERSION_FALLBACK).split('.').slice(0, 2).join('.')} Desktop` + `v{status?.version || VERSION_FALLBACK}` formatında.
- **`desktop/src/components/LockScreen.jsx`** — hardcode `V6.0` KALDIRILDI; `getStatus` import; `const VERSION_FALLBACK = '6.0.0'`; yeni `appVersion` state (`useState(VERSION_FALLBACK)`); yeni `useEffect` mount'ta `getStatus()` çağırıp `s.version` varsa state güncellenir (try/catch sessizce düşer); `<h1>ÜSTAT Plus <span className="version">V{appVersion.split('.').slice(0, 2).join('.')}</span></h1>`.

### 3.3 Test

- **`tests/critical_flows/test_static_contracts.py::test_version_single_source_of_truth`** — yeni Flow 4p. 6 aşamalı zincir:
  1. `engine/__init__.py::VERSION` semver (`X.Y.Z`) formatında.
  2. `api/routes/status.py` `from engine import VERSION` import + `version=ENGINE_VERSION` atama.
  3. `services/api.js::getStatus` fallback objesinde `version:` alanı.
  4. `TopBar.jsx` eski `<span className="version">V6.0</span>` hardcode YASAK + `status.version` ifadesi mevcut.
  5. `Settings.jsx` eski `const VERSION = '6.0.0'` hardcode YASAK + `status?.version` ifadesi mevcut.
  6. `LockScreen.jsx` eski `<span className="version">V6.0</span>` hardcode YASAK + `appVersion` state + `getStatus` import mevcut.

## 4. Anayasa Uyumu

- **Kırmızı Bölge:** Dokunulmadı.
- **Sarı Bölge:** Dokunulmadı.
- **Yeşil Bölge:** `api/routes/status.py` (route), 4 frontend bileşen, 1 test.
- **Siyah Kapı:** 31 korumalı fonksiyon dokunulmadı.
- **Sihirli Sayı:** `'6.0.0'` fallback yorumları (runtime fail-safe) Anayasa Kural 9 fail-safe katmanı — config değil, last-resort UI kırılmazlık garantisi.
- **MT5 Başlatma Sorumluluğu:** N/A.
- **Startup/Lifespan:** N/A — status endpoint zaten mevcut.

## 5. Test Sonuçları

```
tests/critical_flows: 49 passed, 3 warnings in 3.66s
```

48 baseline + 1 yeni Flow 4p = 49. Regression yok.

## 6. Production Build

```
vite v6.4.1 building for production...
transforming...
✓ 728 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                 1.07 kB │ gzip:   0.60 kB
dist/assets/index-CiUWDTb0.css  90.52 kB │ gzip:  15.07 kB
dist/assets/index-ClbTJZBi.js  887.41 kB │ gzip: 254.08 kB
✓ built in 2.70s
```

0 hata, dist/ üretildi.

## 7. Etki Analizi

Çağıran zinciri (tek yön):

```
engine/__init__.py::VERSION
  → api/routes/status.py::get_status()
    → StatusResponse(version=ENGINE_VERSION, ...)
      → /api/status
        → services/api.js::getStatus()
          ├→ TopBar.jsx (2sn polling, mevcut state)
          ├→ Settings.jsx (mount fetch, mevcut state)
          └→ LockScreen.jsx (mount fetch, yeni useEffect)
```

Tüketici zinciri: Dashboard.jsx status fetch ediyor ama versiyon kullanmıyor — etkilenmedi. Monitor.jsx, Performance.jsx vs. etkilenmedi.

Kullanıcı deneyimi: Davranış aynı (`V6.0` görünür). v6.1 release'inde sadece `engine/__init__.py::VERSION = "6.1.0"` değiştirilmesi yeterli; TopBar/Settings/LockScreen otomatik güncellenir.

## 8. CLAUDE.md Bölüm 7 ADIM 4 Değişikliği

**ÖNCE (manuel güncelleme gerektiren 12 nokta):**
- `engine/__init__.py`, `config/default.json`, `api/server.py`, `api/schemas.py`, `desktop/package.json`
- `desktop/main.js` (APP_TITLE + splash), `desktop/src/components/TopBar.jsx`, **`LockScreen.jsx`**, **`Settings.jsx`**
- `desktop/preload.js`, `mt5Manager.js` (JSDoc)
- `create_shortcut.ps1`, `update_shortcut.ps1`

**SONRA (A5 sonrası manuel güncelleme gerektiren 9 nokta):**
- `engine/__init__.py` ← **TEK SOURCE OF TRUTH**
- `config/default.json`, `api/server.py`, `api/schemas.py` (default fallback), `desktop/package.json`
- `desktop/main.js` (APP_TITLE + splash)
- `desktop/preload.js`, `mt5Manager.js` (JSDoc)
- `create_shortcut.ps1`, `update_shortcut.ps1`

**Kazanç:** Üç frontend bileşen listeden çıktı. v6.1 release'inde 3 dosya daha az manuel dokunuş.

## 9. Dokunulmayanlar (Bilinçli)

- `api/schemas.py::StatusResponse.version` default değeri `"6.0.0"` — bırakıldı. Runtime'da override ediliyor; default yalnız test/mock senaryosunda etkili. Audit bu defaultu hedeflemiyor.
- `desktop/package.json::version` — Electron build system için; app versiyonu göstermek değil, native title/installer için kullanılıyor. Ayrı bir kanal.
- `desktop/main.js::APP_TITLE` — Windows tray/taskbar tooltip için. Runtime frontend versiyon bilgisinden bağımsız.

## 10. Deployment

Piyasa kapalı (Cumartesi, Barış Zamanı). `restart_app` yeterli — hem backend route hem Electron bundle yenilenir.

## 11. Sonuç

A5 tek atomik değişiklikle tamamlandı. Versiyon sabiti artık `engine/__init__.py::VERSION` tek kaynağından akıyor; üç frontend bileşeninde hardcode yok. Flow 4p statik sözleşme testi geleceğe dönük regression korumasını sağlıyor.

Sıradaki audit maddesi için standing directive devam: H-ailesi kritik aksiyonlar (H5 tamamlandı A19'da, H1 tamamlandı A5'te, H2 tamamlandı A18'de) — kalan H3/H4/H6 veya B-ailesi için devam edilebilir.
