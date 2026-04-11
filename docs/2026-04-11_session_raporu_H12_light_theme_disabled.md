# Oturum Raporu — Widget Denetimi H12: Açık Tema Disabled

**Tarih:** 2026-04-11 (Pazar, Barış Zamanı — piyasa kapalı)
**Konu:** Settings sayfasında "Açık Tema" kartının `disabled` state'ine alınması
**Kapsam:** Widget Denetimi Bulgu H12 (Düşük kritiklik)
**Versiyon:** 6.0.0 (değişiklik yok)
**Commit:** (aşağıda)

---

## 1. Kapsam

`docs/2026-04-11_widget_denetimi.md` Bölüm 12.3 + 16.3 H12 (Düşük kritiklik):

> Settings → Tema: Açık tema CSS'te hazır ama tüm bileşenlerde doğrulanmamış — kullanıcı seçerse UI karmaşıklaşır, "Koyu Tema aktif" yazısı yanıltıcı.

Bu oturumda tek hedef: Açık tema kartını gerçekten seçilemez hale getirmek, `applyTheme` fonksiyonunu `'dark'` whitelist'iyle korumak, dosya başlığındaki yanıltıcı yorumu düzeltmek ve regression koruma testi eklemek.

## 2. Kök Neden

`desktop/src/components/Settings.jsx` dosyasında:

1. **`useState` initializer**: `localStorage.getItem('ustat_theme') || 'dark'` — legacy `'light'` değeri olduğu gibi kabul ediliyor, render sırasında Açık Tema kartı `active` class'ı alıyor.
2. **`applyTheme(newTheme)` fonksiyonu**: Hiçbir whitelist yok; `setTheme(newTheme) + localStorage.setItem('ustat_theme', newTheme) + documentElement.setAttribute('data-theme', newTheme)` zinciri her değer için çalışıyordu.
3. **JSX Açık Tema kartı**: `onClick={() => applyTheme('light')}` açıkça `'light'` geçiyor, kart `active` class'ı alıp tıklanabilir görünüyor.
4. **`App.jsx` mount effect** (satır 41-46): `localStorage === 'light'` olursa `documentElement.setAttribute('data-theme', 'light')` — bir sonraki açılışta `theme.css :root[data-theme="light"]` değişkenleri aktifleşiyor.
5. **Dosya başlığı yorumu** (satır 7): `3. Tema Ayarı (şimdilik sadece koyu tema)` — kodun gerçek durumunu yansıtmıyor (açık tema aslında persist ediliyor).

Sonuç: Kullanıcı Açık Tema'yı seçerse Dashboard, Monitor, Risk Yönetimi, Nabiz, TradeHistory gibi tüm bileşenler koyu tema için tasarlandığından kontrast kırılıyor, risk renk kodları karmaşıklaşıyor, gerçek para ile işlem yapan kullanıcı yanıltıcı bir görsel deneyim yaşıyor.

## 3. Çözüm Kararı

**Disable yaklaşımı seçildi (remove değil):**

1. `.st-theme-card.disabled` class'ı `theme.css`'te zaten mevcut (opacity 0.4, cursor not-allowed) — CSS dokunulmadı.
2. Açık tema CSS değişkenleri (`:root[data-theme="light"]`) korundu — gelecekte re-enablement kolay.
3. Kartı tamamen kaldırmak "bu özellik hiç yoktu" sinyali verir; `(yakında)` etiketi "özellik geliyor, hazır değil" mesajı verir — daha dürüst UX.
4. Scope'u dar tutmak için `App.jsx` mount effect dokunulmadı; legacy `'light'` kullanıcıları `Settings.jsx::useState` initializer ile bir sonraki mount'ta sessizce koyu temaya alınıyor.

## 4. Yapılan Değişiklikler

### 4.1 `desktop/src/components/Settings.jsx`

**(a) Dosya başlığı yorumu (satır 7):**

Eski:
```
*   3. Tema Ayarı (şimdilik sadece koyu tema)
```

Yeni:
```
*   3. Tema Ayarı (koyu tema aktif; açık tema CSS'te hazır ama tüm bileşenlerde
*      doğrulanmadığı için disabled — Widget Denetimi H12)
```

**(b) Theme state + `applyTheme` (satır 101-128 civarı):**

```jsx
// ── Tema (localStorage + DOM) — Widget Denetimi H12 ──
//
// Açık tema CSS değişkenleri (theme.css `:root[data-theme="light"]`) hazır,
// ancak tüm bileşenlerde doğrulanmadığı için UI'den seçilemez (disabled
// kart + tooltip). applyTheme sadece 'dark' argümanını kabul eder; 'light'
// çağrısı güvenlik amaçlı sessizce reddedilir. Açık tema hazır olduğunda
// kart disabled state'inden çıkarılır ve bu guard kaldırılır.
const [theme, setTheme] = useState(() => {
  const saved = localStorage.getItem('ustat_theme');
  // Legacy kullanıcı 'light' kaydetmiş olsa bile UI 'dark' gösterir;
  // gerçek applyTheme çağrısı olana kadar DOM data-theme attribute'u
  // App.jsx mount effect'inde zaten yönetilir.
  return saved === 'light' ? 'dark' : (saved || 'dark');
});

const applyTheme = useCallback((newTheme) => {
  // H12 guard: açık tema henüz tam doğrulanmadı, yalnız 'dark' kabul edilir.
  if (newTheme !== 'dark') {
    return;
  }
  setTheme('dark');
  localStorage.setItem('ustat_theme', 'dark');
  document.documentElement.removeAttribute('data-theme');
}, []);
```

**(c) Açık Tema kartı JSX:**

Eski:
```jsx
<div
  className={`st-theme-card ${theme === 'light' ? 'active' : ''}`}
  onClick={() => applyTheme('light')}
>
  <div className="st-theme-preview light" />
  <span>Açık Tema</span>
</div>
```

Yeni:
```jsx
<div
  className="st-theme-card disabled"
  title="Açık tema henüz tüm bileşenlerde doğrulanmadı — yalnız koyu tema aktif (Widget Denetimi H12)"
  aria-disabled="true"
>
  <div className="st-theme-preview light" />
  <span>Açık Tema (yakında)</span>
</div>
```

### 4.2 `tests/critical_flows/test_static_contracts.py`

Yeni Flow 4v testi (Flow 5'ten önce eklendi):

```python
# ── Flow 4v: Settings acik tema disabled (Widget Denetimi H12) ───
def test_settings_light_theme_disabled():
    """Settings.jsx icinde acik tema UI'den secilemez olmali.

    H12: acik tema CSS degiskenleri hazir ama tum bilesenlerde
    dogrulanmadigi icin Settings sayfasinda 'Koyu Tema aktif' yazip
    acik temayi sessizce uyguluyordu. Regression koruma:
        (a) 'simdilik sadece koyu tema' yaniltici yorumu kaldirilmis
        (b) 'Widget Denetimi H12' marker mevcut
        (c) applyTheme guard: 'dark' disinda cagrilar reddedilir
        (d) Acik tema karti disabled class + title tooltip + aria-disabled
        (e) Regresyon: onClick={() => applyTheme('light')} YOK
    """
    settings_jsx = ROOT / "desktop" / "src" / "components" / "Settings.jsx"
    assert settings_jsx.exists(), "desktop/src/components/Settings.jsx yok."
    src = settings_jsx.read_text(encoding="utf-8")

    # (a) Yaniltici yorum kaldirilmis olmali
    assert "şimdilik sadece koyu tema" not in src, ...
    # (b) H12 marker mevcut
    assert "Widget Denetimi H12" in src, ...
    # (c) applyTheme guard mevcut
    assert "if (newTheme !== 'dark')" in src, ...
    # (d) Acik tema karti disabled + title + aria-disabled
    assert 'className="st-theme-card disabled"' in src, ...
    assert 'aria-disabled="true"' in src, ...
    title_match = re.search(r'title="[^"]*Widget Denetimi H12[^"]*"', src)
    assert title_match, ...
    # (e) Regresyon: onClick applyTheme('light') cagrisi OLMAMALI
    assert "applyTheme('light')" not in src, ...
```

## 5. Dokunulmayanlar (Bilinçli)

- `desktop/src/styles/theme.css` — `:root[data-theme="light"]` CSS değişkenleri + `.st-theme-card.disabled` class'ı korundu (re-enablement için).
- `desktop/src/App.jsx` (satır 41-46) — mount effect `localStorage === 'light'` branch'i korundu; `Settings.jsx::useState` initializer legacy kullanıcıyı hemen `'dark'` yaptığı için pratikte tetiklenmez.
- `config/default.json` — Kırmızı Bölge + tema geliştirme state'i config konusu değil.
- BABA, OĞUL, H-Engine, risk modülleri — scope dışı.
- Backend route'lar — hiçbir backend değişikliği yok.

## 6. Anayasa Uyumu

- **Siyah Kapı**: yok — `Settings.jsx` Yeşil Bölge, frontend-only.
- **Kırmızı Bölge**: DOKUNULMADI (config/default.json, engine/baba.py, ogul.py, mt5_bridge.py, database.py, data_pipeline.py, main.py, ustat.py, start_ustat.py, api/server.py).
- **Sarı Bölge**: DOKUNULMADI (h_engine.py, config.py, logger.py, killswitch.py, positions.py, desktop/main.js, desktop/mt5Manager.js).
- **Çağrı sırası**: BABA → OĞUL → H-Engine → ÜSTAT — etkilenmedi.
- **Motor davranışı**: değişmedi; yalnızca UI tema seçimi netleştirildi.

## 7. Test ve Build

**critical_flows testleri:**
```
python -m pytest tests/critical_flows -q --tb=short
55 passed, 3 warnings in 3.35s
```

**Windows production build:**
```
ustat-desktop@6.0.0 build
vite v6.4.1 building for production...
✓ 728 modules transformed.
dist/index.html                 1.07 kB │ gzip:   0.60 kB
dist/assets/index-CiUWDTb0.css  90.52 kB │ gzip:  15.07 kB
dist/assets/index-3RJ0D3O3.js   889.93 kB │ gzip: 255.12 kB
✓ built in 2.64s
```

Bundle boyutu değişimi: +0.09 kB (yorum bloğu + guard + label + tooltip).

## 8. Versiyon

Versiyon arttırılmadı. Değişiklik oranı eşiğin altında (yalnız 2 dosya, ~25 satır net ekleme). Versiyon `6.0.0` kalır.

## 9. Değişen Dosyalar

1. `desktop/src/components/Settings.jsx` — dosya başlığı yorumu + theme useState initializer + applyTheme guard + Açık Tema kartı JSX.
2. `tests/critical_flows/test_static_contracts.py` — Flow 4v testi eklendi.
3. `docs/USTAT_GELISIM_TARIHCESI.md` — #185 girişi.
4. `docs/2026-04-11_session_raporu_H12_light_theme_disabled.md` — bu rapor.

## 10. Deploy Notu

Piyasa kapalı (Pazar, Barış Zamanı). `restart_app` yeterli. Legacy `'light'` kayıtlı kullanıcılar bir sonraki mount'ta sessizce koyu temaya döner.

## 11. Sonuç

H12 kapatıldı: Açık Tema kartı artık gerçekten seçilemez, tooltip kullanıcıya nedeni açıklıyor, `applyTheme` whitelist guard'ı ile korundu, dosya başlığı dürüstleşti, regression koruma testi (Flow 4v) pre-commit hook tarafından bloklanacak. critical_flows 55/55 yeşil, build temiz. Widget Denetimi backlog'unda sıradaki maddeye geçilebilir.
