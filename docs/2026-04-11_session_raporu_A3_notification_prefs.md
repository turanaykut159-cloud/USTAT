# A3 — Bildirim Tercihleri Gerçek Davranış Bağlaması (Widget Denetimi S1)

**Tarih:** 2026-04-11 (Cumartesi, Barış Zamanı)
**Commit:** `c2512fc`
**Sınıf:** C3 (config/default.json Kırmızı Bölge #8 dokunusu — yalnız yeni UI alanı)
**Kaynak bulgu:** `docs/2026-04-11_widget_denetimi.md` Bölüm 14.5 + Bölüm 17 A3 (S1)
**Anayasa uyum:** ✅ (risk/strateji/eşik parametresi dokunulmadı; Siyah Kapı fonksiyonu dokunulmadı; kapsam dürüstçe iletildi)

---

## 1. Özet

Settings ekranındaki 5 bildirim toggle'ı (`soundEnabled`, `killSwitchAlert`, `tradeAlert`, `drawdownAlert`, `regimeAlert`) iki katmanda kırık durumdaydı:

1. **Backend persistence yok** — `_notification_prefs` process belleğindeydi, restart sonrası sıfırlanıyordu
2. **Gerçek davranış yok** — hiçbir backend/frontend kodu bu prefs'i okumuyordu; ayrıca frontend'de ses çalma altyapısı da yoktu (`new Audio`/`playSound`/`beep` grep'leri boş)

Bu fix iki katmanı da ele aldı: (a) backend persistence `config/default.json` → `ui.notification_prefs` → `config.save()` zinciri ile sağlandı, (b) Dashboard bildirim çekmecesi (zil ikonu) `hybrid_*` notification tiplerini `tradeAlert` bayrağı ile kapılıyor, (c) Settings sayfasına dürüst kapsam bilgi kutusu eklenerek kullanıcıya hangi toggle'ın gerçekten çalıştığı açıkça iletildi.

**Çıktı:** Kullanıcı "İşlem & Hibrit Uyarıları" toggle'ını kapattığında hibrit pozisyon EOD/yön değişimi/PRİMNET reset bildirimleri bell drawer'a gelmeyecek. Diğer 4 toggle kapsamlı info kutusu ile "henüz aktif değil" olarak işaretlendi — UI tiyatrosu kaldırıldı.

---

## 2. Kök Neden Analizi

### 2.1 Backend — `_notification_prefs` orphan dict

`api/routes/settings.py` içinde modül seviyesinde:

```python
_notification_prefs: dict = {
    "soundEnabled": True,
    "killSwitchAlert": True,
    ...
}
```

- `GET /settings/notification-prefs` → `dict(_notification_prefs)` döner
- `POST /settings/notification-prefs` → `_notification_prefs.update(...)` yapar
- **Hiçbir modül bu dict'i okumuyor** — grep `_notification_prefs` tüm kod tabanında sadece bu dosyada 4 satır
- Engine restart → Python process yeniden başlar → dict initial değerlerine döner

### 2.2 Frontend — Ses altyapısı hiç yok

```bash
grep -r "new Audio\|playSound\|AudioContext\|\.mp3\|\.wav\|beep" desktop/src/
```

- `Dashboard.jsx` — 0 eşleşme
- `Settings.jsx` — 0 eşleşme  
- Diğer bileşenler — 0 eşleşme

Audit raporu "kullanıcı sessize aldım sanıyor ama sistem ses çıkarıyor" dedi — gerçek daha net: hiç ses zaten yok, 5 toggle tamamen UI tiyatrosu.

### 2.3 Bonus: event_bus dup-key bug (A3 kapsamı dışı, not edildi)

`engine/event_bus.py::emit` payload'ı şöyle üretiyor:
```python
payload = {"type": event, **(data or {})}
```

`engine/h_engine.py` emit çağrısı:
```python
_emit("notification", {"type": "hybrid_eod", ...})
```

Sonuç: `payload = {"type": "notification", "type": "hybrid_eod", ...}` — dup-key spread iç `type`'ı dış `type`'a üstüne yazıyor → son payload `{"type": "hybrid_eod", ...}`. Dashboard'daki `msg.type === 'notification'` WS branch'i hiç tetiklenmiyor; hybrid notification'lar yalnız HTTP fetch (`getNotifications`) yoluyla gelebiliyor. **A3 kapsamı dışı**, ayrı bir B-bulgu olarak izlenecek.

---

## 3. Atomik Değişiklikler

### 3.1 `config/default.json` (Kırmızı Bölge #8 — sadece yeni UI alanı)

Yeni `ui` namespace altında `notification_prefs`:

```json
"ui": {
  "notification_prefs": {
    "soundEnabled": true,
    "killSwitchAlert": true,
    "tradeAlert": true,
    "drawdownAlert": true,
    "regimeAlert": false
  }
}
```

**Eski/yeni karşılaştırma (Kırmızı Bölge kuralı):**
- Eski: `ui` anahtarı yoktu
- Yeni: yalnız `ui.notification_prefs` eklendi, başka hiçbir alan değişmedi
- **Risk/strateji/eşik parametreleri DOKUNULMADI** (`risk.*`, `strategies.*`, `indicators.*`, `engine.*`, `mt5.*`, `api.*`)

### 3.2 `api/routes/settings.py`

**Kaldırıldı:**
```python
_notification_prefs: dict = {...}
```

**Eklendi:**
- `DEFAULT_NOTIFICATION_PREFS` fallback sabiti (dict, 5 anahtar, frontend ile senkron)
- `_read_notification_prefs_from_config()` helper — engine.config'den okur, eksik key'leri default ile merge eder, tip kontrolü boolean
- `GET /settings/notification-prefs` → helper'dan okur
- `POST /settings/notification-prefs` → `config.set("ui.notification_prefs", current)` + `config.save()` zinciri (`update_risk_baseline` ile aynı persistence deseni). Engine yoksa warning log + `success=False`

### 3.3 `desktop/src/components/Dashboard.jsx`

Eklendi:
- `NOTIF_PREFS_KEY = 'ustat_notification_prefs'` sabiti (Settings ile aynı)
- `NOTIF_PREFS_DEFAULT` fallback objesi
- `readNotifPrefs()` helper — `localStorage` + default merge
- `notifPrefsRef = useRef(readNotifPrefs())` — mutable ref (re-render tetiklemez)
- `useEffect` — `storage` event listener (Settings'te toggle değişince Dashboard prefs'i yeniden okur)
- `shouldShowNotification(msg)` filtresi — `msg.notif_type || msg.type` okur, `hybrid_*` için `prefs.tradeAlert` bayrağını kontrol eder
- HTTP fetch path: `getNotifications({limit:50}).then(...)` içinde `.filter(n => shouldShowNotification(...))`
- WS branch: `if (msg.type === 'notification') { if (!shouldShowNotification(msg)) return; ... }`

### 3.4 `desktop/src/components/Settings.jsx`

Eklendi (toggle bölümünün ÜSTÜNE):
- Dürüst kapsam bilgi kutusu (sarı border, sarı arka plan): "Kapsam: Şu an yalnızca **İşlem & Hibrit Uyarıları** toggle'ı Dashboard bildirim çekmecesinde (zil ikonu) gerçek davranışa bağlıdır. Diğer toggle'lar tercihleriniz sunucuda kalıcı olarak saklanır, ancak henüz bağlı oldukları bir tetikleme mekanizması yoktur."

Label/desc güncellemeleri:
- `tradeAlert` label: "İşlem bildirimi" → **"İşlem & Hibrit Uyarıları"**
- `tradeAlert` desc: "Yeni işlem açıldığında / kapandığında" → **"Hibrit pozisyon, EOD ve yön değişimi bildirimleri"**
- `soundEnabled` desc: "İşlem ve uyarı sesleri" → "İşlem ve uyarı sesleri (henüz aktif değil)"
- `killSwitchAlert` desc: "L1/L2/L3 tetiklendiğinde bildirim" → "L1/L2/L3 tetiklendiğinde bildirim (henüz aktif değil)"
- `drawdownAlert` desc: "Risk limitlerine yaklaşıldığında" → "Risk limitlerine yaklaşıldığında (henüz aktif değil)"
- `regimeAlert` desc: "Piyasa rejimi değiştiğinde" → "Piyasa rejimi değiştiğinde (henüz aktif değil)"

### 3.5 `tests/critical_flows/test_static_contracts.py` — Flow 4d

Yeni test: `test_notification_prefs_persists_via_config`

İnspect/statik doğrulamalar:
1. `_notification_prefs: dict` tanımı KALDIRILMIŞ olmalı
2. `_notification_prefs.update(` çağrısı kaldırılmış olmalı
3. `DEFAULT_NOTIFICATION_PREFS` sabiti var ve 5 anahtarı içeriyor
4. `_read_notification_prefs_from_config` helper var ve `ui.notification_prefs` kullanıyor
5. `update_notification_prefs` POST'u `config.set("ui.notification_prefs"` + `config.save()` çağırıyor

Gelecekte bellek tabanlı dict geri eklenirse pre-commit hook commit'i bloklar.

---

## 4. Dokunulmayanlar (Bilinçli)

| Dosya / Alan | Neden dokunulmadı |
|---|---|
| `engine/h_engine.py` notification emit noktaları | Sarı Bölge, dup-key bug'ı ayrı bir B-bulgu, gereksiz risk |
| `engine/event_bus.py::emit` dup-key | Ayrı bir bulgu, A3 kapsamı dışı — not edildi |
| Yeni notification türleri (`kill_switch_*`, `drawdown_*`, `regime_*` emit) | Büyük iş, ayrı A-maddesi; backend emit + frontend filter + sound altyapısı |
| `baba.py`, `ogul.py`, `mt5_bridge.py` | Kırmızı Bölge, A3 ile ilgisiz |
| `config/default.json` risk/strateji/eşik sabitleri | Anayasa Kural #8, DOKUNULMAZ |
| Frontend ses altyapısı eklenmesi | A3 dürüst kapsam: "ses yok" gerçeği info kutusu ile kullanıcıya iletildi; ses eklemek ayrı iş |

---

## 5. Doğrulama

### 5.1 Syntax & Compile
```
python -m py_compile api/routes/settings.py api/schemas.py api/routes/trades.py
→ ALL_SYNTAX_OK
```

### 5.2 Config kontrol
```python
>>> d.get('ui',{}).get('notification_prefs')
{'soundEnabled': True, 'killSwitchAlert': True, 'tradeAlert': True,
 'drawdownAlert': True, 'regimeAlert': False}
>>> d['risk']['hard_drawdown_pct']
0.15  # DEĞİŞMEDİ
>>> d['version']
'6.0.0'  # DEĞİŞMEDİ
```

### 5.3 Critical flows
```
python -m pytest tests/critical_flows -q --tb=short
→ 37 passed, 3 warnings in 2.91s
```
36 baseline + 1 yeni `test_notification_prefs_persists_via_config` — **37/37 yeşil**

### 5.4 Production build
```
python .agent/claude_bridge.py build
→ ustat-desktop@6.0.0 build
→ vite v6.4.1 building for production...
→ ✓ 728 modules transformed.
→ dist/index.html 1.06 kB, index.css 90.52 kB, index.js 881.71 kB
→ ✓ built in 2.67s
→ Build başarılı. (0 hata)
```
Vite Dashboard.jsx + Settings.jsx JSX compile — syntax temiz.

### 5.5 Git status
```
[main c2512fc] fix(notification-prefs): backend persistence + gercek davranis kapilamasi (Widget Denetimi S1)
 6 files changed, 194 insertions(+), 15 deletions(-)
```

---

## 6. Etki Analizi

| Dosya | Bölge | Değişiklik | Risk |
|---|---|---|---|
| `config/default.json` | 🔴 Kırmızı #8 | Yalnız `ui.notification_prefs` ekleme | Düşük — risk/strateji/eşik yok |
| `api/routes/settings.py` | 🟡 Sarı (dolaylı) | `_notification_prefs` dict → config persistence | Düşük — `update_risk_baseline` deseni kanıtlı |
| `desktop/src/components/Dashboard.jsx` | 🟢 Yeşil | Filter + storage listener eklendi | Düşük — geriye dönük uyumlu |
| `desktop/src/components/Settings.jsx` | 🟢 Yeşil | Info kutusu + label | Sıfır — pure UI metni |
| `tests/critical_flows/test_static_contracts.py` | 🟢 Yeşil | Yeni Flow 4d | Sıfır — yalnız ekleme |

**Tüketici zinciri:** Settings → `localStorage['ustat_notification_prefs']` → Dashboard `storage` event → `notifPrefsRef` → `shouldShowNotification` → notifications drawer.
**Çağrı zinciri:** POST endpoint → `config.set` + `config.save()` → `config/default.json` disk yazımı → `GET` endpoint sonraki istekte disk'ten okur.

**Geriye dönük uyumluluk:** Yeni `ui.notification_prefs` key'i eski config'te yoksa fallback `DEFAULT_NOTIFICATION_PREFS` devreye girer. Eski `_notification_prefs` dict'ini import eden başka modül yoktu (grep teyit edildi), dış kırılma yok.

---

## 7. Deploy Durumu

**Deploy yapılmadı** (kullanıcı kontrolünde). Deploy için:
1. `python .agent/claude_bridge.py restart_app` — backend modül reload, frontend dist zaten build edildi
2. Doğrulama adımları:
   - Settings sayfasını aç → info kutusu görünmeli
   - "İşlem & Hibrit Uyarıları" kapat → `POST /api/settings/notification-prefs` → API restart → `GET` → değer kalıcı olmalı
   - Dashboard → localStorage kontrol et → `ustat_notification_prefs` key'i `tradeAlert: false` olmalı
   - Yeni `hybrid_daily_reset` event'inde (sonraki gün sabah H-Engine tetikler) bell drawer'a gelmediğini doğrula

**Zamanlama:** Barış Zamanı (Cumartesi) — her zaman deploy edilebilir. A1 (bekleyen L3 eskalasyon) ile aynı restart'ta gitmesi mantıklı.

---

## 8. Takip (Ayrı A-maddeleri gerekli)

| # | İş | Boyut |
|---|---|---|
| B-bulgu | `engine/event_bus.py::emit` dup-key fix — `type` parametresi ile `data` içindeki `type` çakışması | Küçük |
| A-madde | Yeni notification emit noktaları (kill_switch/drawdown/regime) + backend → frontend filter + (isteğe bağlı) minimal Web Audio beep | Orta |
| A-madde | `engine/mt5_bridge.py::get_history_for_sync` multi-leg netting split (A2'den carry) | Büyük, C3 Kırmızı Bölge |

---

## 9. Referanslar

- Audit: `docs/2026-04-11_widget_denetimi.md` Bölüm 14.5 + Bölüm 17 A3 (S1)
- A1 raporu: `docs/2026-04-11_session_raporu_A1_hard_drawdown_l2_l3.md`
- A2 raporu: `docs/2026-04-11_session_raporu_A2_trade_sign_mismatch.md`
- Changelog: `docs/USTAT_GELISIM_TARIHCESI.md` #167
- Commit: `c2512fc`
- Anayasa referansları: Kural #8 (config yönetimi), Bölüm 4.1 (Kırmızı Bölge #8)
