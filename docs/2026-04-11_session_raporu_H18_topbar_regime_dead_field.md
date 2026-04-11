# Oturum Raporu — Widget Denetimi H18: TopBar `regime` Dead Field Removal

**Tarih:** 2026-04-11 (Pazar, Barış Zamanı — piyasa kapalı)
**Konu:** `desktop/src/components/TopBar.jsx` `useState` initial state'inden `regime: 'TREND'` alanının kaldırılması (dead field removal)
**Kapsam:** Widget Denetimi Bulgu H18 (Düşük kritiklik)
**Versiyon:** 6.0.0 (değişiklik yok)
**Commit:** (aşağıda)

---

## 1. Kapsam

`docs/2026-04-11_widget_denetimi.md` Bölüm 15.1 + 16.3 H18 (Düşük kritiklik):

> TopBar.jsx initial state'te `regime: 'TREND'` taşıyor — backend response gelene kadar yanıltıcı; loading state için `'—'` olmalı.

Bu oturumda tek hedef: TopBar başlangıç state'inde tutulan ölü `regime` alanını kaldırmak, dosyaya bir Widget Denetimi H18 marker yorumu eklemek ve regression koruma testi (Flow 4w) yazmak.

## 2. Kök Neden

`desktop/src/components/TopBar.jsx` dosyasında:

```jsx
const [status, setStatus] = useState({
  engine_running: false,
  mt5_connected: false,
  phase: 'stopped',
  kill_switch_level: 0,
  regime: 'TREND',          // ← H18 sorunu
});
```

Backend `getStatus()` polling'i (2 sn) `setStatus(s)` ile tüm alanları override ediyor, fakat:

1. **`status.regime` TopBar render'ında HİÇBİR yerde okunmuyor.** TopBar yalnızca `phase`, `kill_switch_level`, `mt5_connected`, `version` alanlarını JSX'te tüketir. `regime` alanı tamamen ölü.
2. **İlk render'da `'TREND'` default değeri** kullanıcıya hiçbir şekilde gösterilmediği için pratikte yanıltıcı bir sinyal değil — fakat ileride biri TopBar'da rejimi göstermek isterse, bu kayıtlı default ona "her zaman TREND'le başla" mesajı verirdi. Audit bu nedenle "loading state için `'—'` placeholder" önermişti.
3. **Ölü kod = teknik borç.** Widget Denetimi disiplini ölü alanların temizlenmesini şart koşar.

### Scope analizi (silmek başka bileşeni bozar mı?)

`grep -rn "status.regime" desktop/src/`:

- `Dashboard.jsx`: kendi bağımsız `getStatus()` polling'i + kendi `status` state'i.
- `AutoTrading.jsx`: kendi bağımsız `getStatus()` polling'i + kendi `status` state'i.
- React'ta TopBar'daki state Dashboard veya AutoTrading'e prop drill OLMAZ — `status` prop hiçbir yerde geçmiyor.

Sonuç: TopBar'dan `regime` alanını kaldırmak başka hiçbir bileşeni etkilemez.

## 3. Çözüm Kararı

**Default değiştirme yerine alanı tamamen silme:**

Audit `'—'` em-dash placeholder öneriyordu. Fakat alan TopBar'da hiç okunmadığı için en dürüst çözüm tüm alanı silmektir:

- `'—'` yapmak yine ölü kod tutmak demek olur (loading placeholder ama hiç gösterilmiyor).
- Silmek + bir yorum bloğuyla nedeni belgelemek "bu alan kasıtlı olarak yok" mesajı verir.
- Gelecekte TopBar'da gerçekten piyasa rejimi gösterilmek istenirse: ayrı bir state eklenir, loading için em-dash placeholder o zaman düşünülür, bu yorum bloğu o gün rehberlik eder.

## 4. Yapılan Değişiklikler

### 4.1 `desktop/src/components/TopBar.jsx`

**Eski (satır 22-30):**

```jsx
// ── State ──────────────────────────────────────────────────────
const [status, setStatus] = useState({
  engine_running: false,
  mt5_connected: false,
  phase: 'stopped',
  kill_switch_level: 0,
  regime: 'TREND',
});
```

**Yeni (satır 22-38):**

```jsx
// ── State ──────────────────────────────────────────────────────
//
// Widget Denetimi H18: Eski initial state'te piyasa rejimi alanı
// yanıltıcı bir default değer ile taşınıyordu ama TopBar render'ında
// bu alan HİÇBİR yerde okunmuyordu — backend status response'u
// setStatus ile geldiğinde dahi UI'de görünmüyordu. Dashboard.jsx ve
// AutoTrading.jsx kendi bağımsız status state'lerini tutuyor (React'ta
// TopBar'daki state onlara prop drill olmuyor), bu yüzden alanı
// kaldırmak başka bir bileşeni bozmaz. Dead field removal: gelecekte
// piyasa rejimi TopBar'da gerçekten gösterilmek istenirse ayrı bir
// state eklenir ve loading state'i için em-dash placeholder kullanılır.
const [status, setStatus] = useState({
  engine_running: false,
  mt5_connected: false,
  phase: 'stopped',
  kill_switch_level: 0,
});
```

### 4.2 `tests/critical_flows/test_static_contracts.py`

Yeni Flow 4w testi (Flow 5'ten önce eklendi):

```python
# ── Flow 4w: TopBar regime dead field removal (Widget Denetimi H18) ─
def test_topbar_no_dead_regime_initial_state():
    """TopBar.jsx useState initial state'inde olu `regime` alani olmamali.

    H18: Eski TopBar initial state'te `regime: 'TREND'` aliani vardi
    ama JSX render'inda hicbir yerde okunmuyordu (dead field). Audit
    'em-dash placeholder' onerdi, biz daha dogal cozumu sectik: alani
    tamamen silmek. Regression koruma:
        (a) `regime: 'TREND'` literal'i YASAK
        (b) useState initial state bloğunda `regime:` alan tanimi YASAK
        (c) `status.regime` consumption YASAK (alanin hic okunmadigini
            sözlesmeleyen ek koruma)
        (d) `Widget Denetimi H18` marker yorumu mevcut
    """
    topbar_jsx = ROOT / "desktop" / "src" / "components" / "TopBar.jsx"
    assert topbar_jsx.exists(), "desktop/src/components/TopBar.jsx yok."
    src = topbar_jsx.read_text(encoding="utf-8")

    # (a) Eski literal YASAK
    assert "regime: 'TREND'" not in src, ...
    # (b) useState initial state'inde regime alani YASAK
    usestate_block = re.search(r"useState\s*\(\s*\{([^}]*)\}", src, re.DOTALL)
    assert usestate_block, ...
    initial_state = usestate_block.group(1)
    assert not re.search(r"\bregime\s*:", initial_state), ...
    # (c) status.regime consumption YASAK
    assert "status.regime" not in src, ...
    # (d) H18 marker
    assert "Widget Denetimi H18" in src, ...
```

**İlk çalıştırmada test FAİL etti** çünkü ilk yorum bloğu taslağında `status.regime` ve `regime: 'TREND'` literal'leri açıklama metni içinde geçiyordu. Yorum bloğu literal'leri içermeyecek şekilde yeniden yazıldı ("piyasa rejimi alanı", "yanıltıcı bir default değer", "em-dash placeholder") ve test 56/56 yeşile döndü.

## 5. Dokunulmayanlar (Bilinçli)

- `desktop/src/components/Dashboard.jsx` — kendi bağımsız `status` state'i ve `getStatus()` polling'i var.
- `desktop/src/components/AutoTrading.jsx` — kendi bağımsız `status` state'i ve `getStatus()` polling'i var.
- `engine/baba.py` `detect_regime()` — backend rejim algılama mantığı değişmedi.
- `api/routes/status.py` — backend `getStatus()` response'u değişmedi (`regime` alanını döndürmeye devam ediyor; Dashboard/AutoTrading kullanıyor).
- `config/default.json` — Kırmızı Bölge, scope dışı.

## 6. Anayasa Uyumu

- **Siyah Kapı**: yok — `TopBar.jsx` Yeşil Bölge, frontend-only.
- **Kırmızı Bölge**: DOKUNULMADI (config/default.json, engine/baba.py, ogul.py, mt5_bridge.py, database.py, data_pipeline.py, main.py, ustat.py, start_ustat.py, api/server.py).
- **Sarı Bölge**: DOKUNULMADI (h_engine.py, config.py, logger.py, killswitch.py, positions.py, desktop/main.js, desktop/mt5Manager.js).
- **Çağrı sırası**: BABA → OĞUL → H-Engine → ÜSTAT — etkilenmedi.
- **Motor davranışı**: değişmedi; yalnızca TopBar başlangıç state'inden ölü alan temizlendi.

## 7. Test ve Build

**critical_flows testleri:**

```
python -m pytest tests/critical_flows -q --tb=short
56 passed, 3 warnings in 2.91s
```

(55 baseline H12 sonrası + Flow 4w yeni test = 56)

**Windows production build:**

```
ustat-desktop@6.0.0 build
vite v6.4.1 building for production...
✓ 728 modules transformed.
dist/index.html                 1.07 kB │ gzip:   0.60 kB
dist/assets/index-CiUWDTb0.css  90.52 kB │ gzip:  15.07 kB
dist/assets/index-0yf54m4J.js   889.91 kB │ gzip: 255.12 kB
✓ built in 2.74s
```

Bundle boyutu değişimi: -0.02 kB (ölü alan kaldırma 2 byte tasarruf; ekli yorum gzip'ten sonra daha küçük).

## 8. Versiyon

Versiyon arttırılmadı. Değişiklik oranı eşiğin altında (yalnız 2 dosya, ~10 satır net delta). Versiyon `6.0.0` kalır.

## 9. Değişen Dosyalar

1. `desktop/src/components/TopBar.jsx` — `useState(status)` initial state'inden `regime: 'TREND'` kaldırıldı + 9 satırlık H18 açıklama yorumu eklendi.
2. `tests/critical_flows/test_static_contracts.py` — Flow 4w testi eklendi (`test_topbar_no_dead_regime_initial_state`).
3. `docs/USTAT_GELISIM_TARIHCESI.md` — #186 girişi (#185'in önüne).
4. `docs/2026-04-11_session_raporu_H18_topbar_regime_dead_field.md` — bu rapor.

## 10. Deploy Notu

Piyasa kapalı (Pazar, Barış Zamanı). `restart_app` yeterli. Kullanıcıya görünen davranışta sıfır değişim — TopBar render'ı zaten `regime` alanını okumuyordu.

## 11. Sonuç

H18 kapatıldı: TopBar başlangıç state'inden ölü `regime` alanı temizlendi, neden açıklama yorumuyla belgelendi, regression koruma testi (Flow 4w) pre-commit hook tarafından bloklanacak. Audit'in önerdiği `'—'` placeholder yerine daha dürüst çözüm seçildi: alanı tamamen silmek (gelecekte rejim TopBar'da gerçekten gösterilmek istenirse ayrı bir state eklenir). critical_flows 56/56 yeşil, build temiz. Widget Denetimi backlog'unda sıradaki Düşük maddeye (H7, H11, H13, H16) geçilebilir.
