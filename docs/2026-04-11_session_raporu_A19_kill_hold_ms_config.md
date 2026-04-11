# Oturum Raporu — A19 KILL_HOLD_DURATION Config Binding (H5)

**Tarih:** 11 Nisan 2026 (Cumartesi — Barış Zamanı)
**Audit kaynağı:** `docs/2026-04-11_widget_denetimi.md` Bölüm 15.1, 15.4, 16.3 H5, 17 A19
**Bulgu kodu:** A19 / H5 (Orta kritiklik — Kritik koruma parametresi hardcode)
**Değişiklik sınıfı:** C3 (Kırmızı Bölge dokunusu — `config/default.json` yeni UI namespace alanı)
**Versiyon artışı:** YOK (toplam diff oranı < %10)
**Commit hedefi:** Tek atomik commit — 5 kod dosyası + 1 test + 1 changelog + 1 rapor

---

## 1. Bulgu Özeti

`desktop/src/components/SideNav.jsx` satır 29'da `const KILL_HOLD_DURATION = 2000` şeklinde hardcode edilmiş bir sabit bulunuyordu. Bu sabit kill-switch butonunun basılı tutulması gereken süreyi (ms) tanımlıyor ve iki farklı yerde kullanılıyordu:

1. **Progress animasyonu** (`setInterval`): `elapsed / KILL_HOLD_DURATION` — ilerleme çubuğu yüzdesi
2. **Tetikleme süresi** (`setTimeout`): gerçek kill-switch tetiklenme gecikmesi

Kritik koruma parametresi — kullanıcı yanlışlıkla kill-switch'e basması durumunda iki aşamalı koruma (basılı tutma süresi + görsel progress) tetiklenme öncesi son engeli oluşturuyor. Config'de olmadığı için:

- Admin değeri değiştirmek istese kod düzenleyip rebuild gerekiyordu
- Stres testi veya şüphe durumunda (yanlış tetiklenme şüphesi → 3000 ms, stres → 500 ms) dinamik ayar imkansızdı
- Audit raporunda **"🧱 KILL_HOLD_DURATION hardcode: Kritik bir koruma parametresi config'de olmalı"** ve **H5: SideNav `KILL_HOLD_DURATION=2000ms` sabit — kritik koruma parametresi config'de olmalı** olarak işaretlendi

---

## 2. Anayasa Değerlendirmesi

| Kontrol | Durum |
|---|---|
| **Siyah Kapı dokunusu** | YOK — kill-switch aktivasyon mantığı (`activateKillSwitch`) hiç değiştirilmedi |
| **Kırmızı Bölge** | VAR — `config/default.json` (#8). Ancak yalnızca `ui.kill_hold_ms` yeni anahtarı eklendi; risk/strateji/eşik/baseline/drawdown parametresi DOKUNULMADI |
| **Sarı Bölge** | YOK |
| **Çağrı sırası** | DEĞİŞMEDİ — main.py döngüsü etkilenmez (sadece frontend UI-layer) |
| **Fonksiyon silme** | YOK |
| **Savaş zamanı ihlali** | YOK — Cumartesi (Barış Zamanı) |

**Sınıf:** C3 (Kırmızı Bölge — sadece yeni UI namespace alanı). Kullanıcı onayı önceki turda alındı (standing directive: "Bir sonraki audit maddesini sen seç ve İŞLEMİ BİTİR disipliniyle tamamla").

---

## 3. Atomik Değişiklikler

### 3.1 Backend Zinciri

**(a) `config/default.json`** — mevcut `ui` bloğuna yeni alan:
```json
"ui": {
  "notification_prefs": { ... },
  "kill_hold_ms": 2000
}
```

**(b) `api/schemas.py`** — yeni Pydantic modeli `UiPrefsResponse`:
```python
class UiPrefsResponse(BaseModel):
    """GET /api/settings/ui-prefs — UI davranış sabitleri (Widget Denetimi A19 / H5)."""
    kill_hold_ms: int = 2000
    source: str = "config"
```

Gelecek UI-layer sabitleri (animation speed, auto-refresh interval, tooltip delay) da aynı endpoint altında toplanabilecek şekilde tasarlandı.

**(c) `api/routes/settings.py`** — üç yeni sabit/helper/endpoint:
1. `DEFAULT_UI_PREFS = {"kill_hold_ms": 2000}` fallback sabiti
2. `_read_ui_prefs_from_config()` helper — tip+aralık doğrulaması: `isinstance(raw, int) and not isinstance(raw, bool) and 500 <= raw <= 10000`. Geçersiz değer sessizce fallback'e düşer — UI kırılmaz. Exception yakalama `try/except` ile `source="error"` döner
3. `GET /settings/ui-prefs` endpoint — helper'dan okur, `(merged, source)` tuple'ını `UiPrefsResponse`'a çevirir

### 3.2 Frontend Zinciri

**(d) `desktop/src/services/api.js`** — yeni async export:
```javascript
export async function getUiPrefs() {
  try {
    const { data } = await client.get('/settings/ui-prefs');
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getUiPrefs:', err?.message ?? err);
    return { kill_hold_ms: 2000, source: 'error' };
  }
}
```

Hata durumunda `kill_hold_ms: 2000` döner — kill-switch koruması ASLA kırılmaz, admin config'i kurtulana kadar fallback garantili.

**(e) `desktop/src/components/SideNav.jsx`** — beş değişiklik:
1. `useEffect` + `getUiPrefs` import edildi
2. Eski `const KILL_HOLD_DURATION = 2000` **KALDIRILDI**
3. Yeni `const DEFAULT_KILL_HOLD_MS = 2000` fallback sabiti + Anayasa kritik koruma yorumu
4. Yeni `killHoldMs` state'i (`useState(DEFAULT_KILL_HOLD_MS)`)
5. Mount `useEffect`: `getUiPrefs()` çağırır + `Number.isFinite(val) && val >= 500 && val <= 10000` güvenlik kontrolü + `cancelled` flag cleanup
6. `setInterval` ve `setTimeout` artık `killHoldMs` state'i kullanıyor
7. `handleKillDown` useCallback dependency'si: `[killFired, killHoldMs]`

### 3.3 Statik Sözleşme Testi

**`tests/critical_flows/test_static_contracts.py::test_sidenav_kill_hold_ms_from_config`** (Flow 4n) — 6 aşamalı zincir doğrulaması:

1. `config/default.json::ui.kill_hold_ms` var + `isinstance(int) and 500 <= val <= 10000`
2. `api/schemas.py::UiPrefsResponse` Pydantic sınıfı + `kill_hold_ms` + `source` alanları mevcut
3. `api/routes/settings.py::_read_ui_prefs_from_config` helper + `/settings/ui-prefs` route kaydı + `config.get("ui.kill_hold_ms"` çağrısı
4. `desktop/src/services/api.js::getUiPrefs` export + `/settings/ui-prefs` endpoint çağrısı
5. `desktop/src/components/SideNav.jsx` eski `const KILL_HOLD_DURATION = 2000` hardcode **YASAK** (regression koruma) + `getUiPrefs` import/kullanımı
6. `killHoldMs` state + `setKillHoldMs` setter + `elapsed / killHoldMs` ifadesi mevcut (setInterval hâlâ dinamik değere bağlı)

Gelecekte refactor sırasında hardcode geri eklenirse pre-commit hook commit'i bloklayacak.

---

## 4. Dokunulmayanlar (Bilinçli)

- `ui.notification_prefs` endpoint'i (`/settings/notification-prefs`) — S1 fix'inde tamamlandı, ayrı yazma API'si var
- `setInterval(..., 16)` 60fps tick — audit "Kritik değil, sabit kalabilir" kararı
- `activateKillSwitch('operator')` operatör kimliği sabit string — H16 ayrı bulgu, A19 kapsamı dışı
- `api/routes/killswitch.py` — fiziksel kill-switch aktivasyonu aynı, yalnız frontend tetikleme gecikmesi config'e bağlandı

---

## 5. Etki Analizi

| Kriter | Değer |
|---|---|
| Dosya sayısı | 5 kod + 1 test + 1 changelog + 1 rapor = 8 |
| Net satır | ~80 ekleme |
| Siyah Kapı dokunusu | 0 |
| Çağıran zinciri | `SideNav mount → getUiPrefs() → /settings/ui-prefs → _read_ui_prefs_from_config() → config.get("ui.kill_hold_ms") → state → setInterval/setTimeout` |
| Tüketici zinciri | Geriye dönük uyumlu — yeni endpoint, mevcut konsümerler etkilenmez |
| Kullanıcı deneyimi | Davranış aynı (2 saniye basılı tutma); admin artık config değiştirip restart yaparak süreyi ayarlayabiliyor |

---

## 6. Doğrulama

| Test | Sonuç |
|---|---|
| `tests/critical_flows` | **47/47 yeşil** (46 baseline + 1 yeni Flow 4n), 3.16s |
| Windows `npm run build` | `ustat-desktop@6.0.0`, 728 modül transformed, 2.74s, **0 hata** |
| dist/ çıktıları | `index.js 886.82 kB`, `index.css 90.52 kB` |
| Piyasa durumu | Cumartesi — Barış Zamanı |
| Deploy hazırlığı | `restart_app` yeterli (hem backend route hem Electron bundle yenilenir) |

---

## 7. Versiyon Durumu

Bu değişiklik tek başına versiyon artışı gerektirecek büyüklükte değil. Diff oranı toplam kod satırının %1'inin altında. Versiyon sabiti korundu — v6.0.0.

---

## 8. Geri Alma Planı

```bash
git revert <commit_hash> --no-edit
```

Commit tamamen atomic: 8 dosya birlikte geri alınır, hiçbir yarım state kalmaz. Fallback sabiti `DEFAULT_KILL_HOLD_MS = 2000` SideNav'da kalır, `getUiPrefs` `{kill_hold_ms: 2000, source: 'error'}` döner — kill-switch davranışı geri almadan sonra da 2 sn kalır.

---

## 9. Kaynak Belgeler

- `docs/2026-04-11_widget_denetimi.md` Bölüm 15.1, 15.4, 16.3 (H5), 17 (A19)
- `docs/USTAT_GELISIM_TARIHCESI.md` entry #177
- `CLAUDE.md` Bölüm 4.1 (Kırmızı Bölge), 4.5 (Değişmez kural 16 — mt5.initialize koruma ile ilgisiz), Bölüm 9 (C3 sınıfı)
- `USTAT_ANAYASA.md` v2.0
