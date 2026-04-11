# Oturum Raporu — Widget Denetimi H11: Settings Dummy Şifre FieldRow Removal

**Tarih:** 2026-04-11 (Pazar, Barış Zamanı — piyasa kapalı)
**Konu:** `desktop/src/components/Settings.jsx` "Bağlantı Bilgileri" bölümünden dummy "Şifre" FieldRow satırının kaldırılması
**Kapsam:** Widget Denetimi Bulgu H11 (Düşük kritiklik)
**Versiyon:** 6.0.0 (değişiklik yok)
**Commit:** (aşağıda)

---

## 1. Kapsam

`docs/2026-04-11_widget_denetimi.md` Bölüm 14.3 + 16.3 H11 (Düşük kritiklik):

> Ayarlar / MT5 Bağlantı Bilgileri: "Şifre" alanı dummy sabit bullet dizisi — anlamsız, kaldırılabilir veya gerçekleştirilebilir.

Bu oturumda tek hedef: Settings sayfasında sabit bullet dizisiyle render edilen dummy şifre satırının tamamen kaldırılması, dosya başlığı yorumunun güncellenmesi ve regresyon koruma testi (Flow 4x) yazılması.

## 2. Kök Neden

`desktop/src/components/Settings.jsx` satır 276:

```jsx
<FieldRow label="Sunucu" value={account?.server || '—'} />
<FieldRow label="Hesap No" value={showLogin ? ... : maskLogin(account?.login)} ... />
<FieldRow label="Şifre" value="(sabit 8 bullet)" />   // ← H11 sorunu
<FieldRow label="Para Birimi" value={account?.currency || 'TRY'} />
```

**Sorunun niteliği:**

1. `value="(sabit 8 bullet)"` — tamamen literal, hiçbir backend verisine bağlı değil. Her render'da aynı sabit dizi.
2. `/api/account` endpoint'i (`api/routes/account.py`) şifre alanı DÖNDÜRMEZ. Kontrol ettim: `grep password api/routes/account.py` → 0 eşleşme.
3. MT5 şifresi `api/routes/mt5_verify.py:66` → `keyring.get_password("ustat-mt5", "credentials")` ile **Windows credential store**'da saklanır; yalnız `passwordMask: "******"` olarak kurulum doğrulamasında döner ve bu da renderer tarafına gitmez.
4. Kullanıcıya yanıltıcı bir "uygulama şifreyi biliyor ve maskeliyor" mesajı veriyor. Gerçekte uygulama bu değeri bilmiyor bile.
5. LockScreen'deki gerçek şifre akışı (`LockScreen.jsx` 341/446/478) login formu — Settings ile alakasız. Her açılışta kullanıcı kendi girer.

Audit değerlendirmesi dürüsttü: "anlamsız, kaldırılabilir veya gerçekleştirilebilir".

## 3. Çözüm Kararı

**"Gerçekleştirme" seçeneği reddedildi:**

MT5 şifresini renderer'a döndürmek Windows credential store'un amacını ihlal eder:
- Plaintext memory exposure (Electron DevTools, memory dump, crash logs)
- Şifre rotasyonunda desync riski
- Güvenlik denetimlerinde red bayrak

**Tek dürüst seçim:** Satırı tamamen kaldır + neden belgelenen yorum bloğu ekle.

## 4. Yapılan Değişiklikler

### 4.1 `desktop/src/components/Settings.jsx` — dummy FieldRow silindi

**Eski (satır 276):**

```jsx
<FieldRow label="Hesap No" value={...} action={...} />
<FieldRow label="Şifre" value="(sabit 8 bullet)" />
<FieldRow label="Para Birimi" value={account?.currency || 'TRY'} />
```

**Yeni:**

```jsx
<FieldRow label="Hesap No" value={...} action={...} />
{/* Widget Denetimi H11: Eski dummy "Şifre" satırı kaldırıldı.
    /api/account MT5 şifresini hiç döndürmez (güvenlik), bu
    FieldRow sabit bir bullet dizisi gösteriyordu ve hiçbir
    backend verisine bağlı değildi. Kullanıcıya "uygulama
    şifreyi bilip maskeliyor" yanlış mesajını veriyordu.
    "Farklı Hesap ile Giriş" butonu aşağıda zaten kimlik
    değişimini sağlıyor. */}
<FieldRow label="Para Birimi" value={account?.currency || 'TRY'} />
```

### 4.2 `desktop/src/components/Settings.jsx` — dosya başlığı yorumu güncellendi

**Eski (satır 5):**

```
 *   1. MT5 Bağlantı Bilgileri (sunucu, hesap, şifre maskeli)
```

**Yeni:**

```
 *   1. MT5 Bağlantı Bilgileri (sunucu, hesap no maskeli, para birimi —
 *      şifre UI'de GÖSTERİLMEZ; Widget Denetimi H11: eski dummy sabit
 *      bullet FieldRow tamamen kaldırıldı, çünkü /api/account endpoint'i
 *      şifreyi hiç döndürmez — MT5 şifresi Windows credential store'da
 *      tutulur ve renderer'a güvenlik gereği aktarılmaz. Placeholder
 *      bile değildi, tamamen dekoratif ölü UI idi)
```

### 4.3 `tests/critical_flows/test_static_contracts.py` — Flow 4x eklendi

Yeni test `test_settings_no_dummy_password_fieldrow` Flow 4w'den sonra, Flow 5'ten önce eklendi. 3 aşamalı koruma:

**(a)** 8 karakterlik sabit bullet literal (`"\u2022" * 8`) Settings.jsx'in HİÇBİR yerinde (JSX + yorumlar dahil) bulunamaz — dummy satırın herhangi bir biçimde geri gelmesini engeller.

**(b)** Hem `label="Şifre" value=` hem `label="Sifre" value=` (Türkçe `ş` ve ASCII `s` varyantları) regex pattern'i YASAK — ileride biri aynı kalıbı farklı placeholder ile yeniden eklerse test yakalar.

**(c)** `Widget Denetimi H11` marker yorumu Settings.jsx'te mevcut olmalı — canonical atıf koruması.

## 5. Test Koşusu — İlk FAIL / Düzeltme / Yeşil

**İlk koşu:** `test_settings_no_dummy_password_fieldrow` FAIL etti. Neden: Hem dosya başlığı yorum bloğunda hem FieldRow yerine eklediğim JSX yorum bloğunda metin olarak 8 bullet literal'i geçiyordu (assertion (a) tetiklendi). H18'de de aynı döngü yaşanmıştı — test metni test'in kendisini bozuyor.

**Düzeltme:**
- Dosya başlığında: `"sabit 8 bullet"` yerine `"sabit bullet"` — sayı kelime olarak yazılmadı.
- JSX yorumunda: `FieldRow sabit "••••••••" gösteriyordu` → `FieldRow sabit bir bullet dizisi gösteriyordu`.
- `grep -c '••••••••' Settings.jsx` → 0.

**İkinci koşu:** 57 passed, 3 warnings in 2.90s.

## 6. Dokunulmayanlar (Bilinçli)

- `api/routes/account.py` — gerçek backend endpoint'i; şifre zaten döndürmüyor.
- `api/routes/mt5_verify.py` — kurulum doğrulama akışı; `passwordMask` alanı renderer dışına gitmiyor.
- `desktop/src/components/LockScreen.jsx` — gerçek login formu; Settings ile ilgisi yok.
- `desktop/src/components/Settings.jsx` `showLogin` state'i ve `maskLogin()` helper'ı — Hesap No için hâlâ kullanılıyor, H11 kapsamı dışında.
- `engine/*` — motor davranışı değişmedi.

## 7. Anayasa Uyumu

- **Siyah Kapı**: yok — `Settings.jsx` Yeşil Bölge, frontend-only.
- **Kırmızı Bölge**: DOKUNULMADI (config/default.json, engine/baba.py, ogul.py, mt5_bridge.py, database.py, data_pipeline.py, main.py, ustat.py, start_ustat.py, api/server.py).
- **Sarı Bölge**: DOKUNULMADI (h_engine.py, config.py, logger.py, killswitch.py, positions.py, desktop/main.js, desktop/mt5Manager.js).
- **API yüzeyi**: değişmedi — `/api/account` response şeması aynı.
- **Motor davranışı**: değişmedi.
- **Çağrı sırası**: BABA → OĞUL → H-Engine → ÜSTAT — etkilenmedi.

## 8. Test ve Build

**critical_flows testleri:**

```
python -m pytest tests/critical_flows -q --tb=short
57 passed, 3 warnings in 2.90s
```

(56 baseline = H12 sonrası 55 + H18 sonrası 56 + Flow 4x = 57)

**Windows production build:**

```
ustat-desktop@6.0.0 build
vite v6.4.1 building for production...
✓ 728 modules transformed.
dist/index.html                 1.07 kB │ gzip:   0.60 kB
dist/assets/index-CiUWDTb0.css  90.52 kB │ gzip:  15.07 kB
dist/assets/index-CZtP-blr.js   889.85 kB │ gzip: 255.10 kB
✓ built in 2.66s
```

Bundle boyutu değişimi: -0.06 kB (dummy FieldRow silme + açıklama yorumu net tasarruf).

## 9. Versiyon

Versiyon arttırılmadı. Değişiklik oranı eşiğin altında (2 dosya, ~10 satır net delta + test). Versiyon `6.0.0` kalır.

## 10. Değişen Dosyalar

1. `desktop/src/components/Settings.jsx` — dummy "Şifre" FieldRow silindi + 6 satırlık JSX açıklama yorumu eklendi + dosya başlığı bölüm açıklaması güncellendi.
2. `tests/critical_flows/test_static_contracts.py` — Flow 4x eklendi (`test_settings_no_dummy_password_fieldrow`).
3. `docs/USTAT_GELISIM_TARIHCESI.md` — #187 girişi (#186'nın önüne).
4. `docs/2026-04-11_session_raporu_H11_settings_dummy_password.md` — bu rapor.

## 11. Deploy Notu

Piyasa kapalı (Pazar, Barış Zamanı). `restart_app` yeterli. Kullanıcıya görünen davranış farkı: Settings → Bağlantı Bilgileri bölümünde artık 4 satır yerine 3 satır (Sunucu, Hesap No, Para Birimi). Yanıltıcı "Şifre: ••••••••" satırı yok. Güvenlik iletişimi netleşti.

## 12. Sonuç

H11 kapatıldı: Dekoratif ölü şifre satırı temizlendi, güvenlik gerekçesiyle nedeni iki yerde (dosya başlığı + inline JSX yorumu) belgelendi, Flow 4x regression koruma testi pre-commit hook tarafından bloklanacak. Audit'in "kaldırılabilir veya gerçekleştirilebilir" seçeneklerinden kaldırma tercih edildi çünkü gerçekleştirme Windows credential store güvenlik modelini bozar. critical_flows 57/57 yeşil, build temiz. Widget Denetimi backlog'unda kalan Düşük maddeler: H7, H13, H16.
