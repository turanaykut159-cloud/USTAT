# Oturum Raporu — H4: ManualTrade Lot Input Sınırları Tek Kaynak

**Tarih:** 11 Nisan 2026 (Cumartesi — Barış Zamanı)
**Konu:** Widget Denetimi H4 — ManualTrade lot input'u `engine.max_lot_per_contract` canonical kaynağına bağlama
**Değişiklik Sınıfı:** C1 (Yeşil Bölge)
**İşlem Tipi:** Tek atomik değişiklik zinciri (5 dosya kod + 1 test)

---

## 1. Kapsam

Widget Denetimi `docs/2026-04-11_widget_denetimi.md` Bölüm 16.3 H4:
> **Manuel İşlem (4.1)** — Lot input `min=1 max=10 step=1` sabit, config'deki
> `max_lot_per_trade` okunmuyor. (Yüksek kritiklik)

Bu madde çözüldü. `ManualTrade.jsx` lot input'u artık `/api/settings/trading-limits`
endpoint'i üzerinden `config.engine.max_lot_per_contract` canonical kaynağından
min/max/step değerlerini dinamik olarak okur. Sessiz truncation kapısı kapandı.

---

## 2. Kök Neden

Önceki durum:

- **Motor tarafı (canonical):** `config/default.json` → `engine.max_lot_per_contract: 1.0`.
  `engine/manuel_motor.py` satır 62'de `MAX_LOT_PER_CONTRACT: float = 1.0` module
  sabiti + satır 264 & 405: `lot = min(lot, MAX_LOT_PER_CONTRACT)` — manuel
  emirler her koşulda 1.0 lota kırpılır. `engine/ogul.py` de satır 389-391'de
  `self._max_lot = float(config.get("engine.max_lot_per_contract", ...))` ile
  aynı config değerini kullanır.
- **UI tarafı (drift):** `desktop/src/components/ManualTrade.jsx` satır 245-247
  lot input'u `min={1} max={10} step={1}` olarak hardcoded. Kullanıcı dropdown'a
  `5` veya `10` girebilir, "Onayla" düğmesiyle emri gönderebilir, motor
  `min(lot, 1.0)` ile sessizce `1.0`'a düşer. Kullanıcı 10 lot gönderdiğini
  sanır; sistem 1 lot açar. **Yanıltıcı UX + potansiyel finansal yanlış
  anlama riski.**

Audit: "Lot input `min=1 max=10 step=1` sabit, config'deki `max_lot_per_trade`
okunmuyor" — Yüksek kritiklik.

---

## 3. Yapılan Değişiklikler

### 3.1 Backend — `api/schemas.py`
Yeni yanıt modeli eklendi:

```python
class TradingLimitsResponse(BaseModel):
    """GET /api/settings/trading-limits — Lot giriş sınırları (Widget Denetimi H4)."""
    lot_min: float = 1.0
    lot_max: float = 1.0
    lot_step: float = 1.0
    source: str = "config"  # config | default | error
```

### 3.2 Backend — `api/routes/settings.py`
Üç ek:
- `DEFAULT_LOT_MIN / DEFAULT_LOT_MAX / DEFAULT_LOT_STEP` sabitleri (1.0/1.0/1.0)
  — import başarısız veya anahtar yok durumunda fallback.
- `_read_trading_limits()` helper — runtime'da `from engine.config import Config`
  import eder, `cfg.get("engine.max_lot_per_contract")` okur, tip + pozitif
  kontrolü yapar. Hata durumunda `"error"`, anahtar yoksa `"default"`,
  başarılı ise `"config"` source'u döndürür.
- `GET /settings/trading-limits` route (response_model=TradingLimitsResponse).

Runtime import neden? Test ortamında `engine.config` MetaTrader5 bağımlılıklarını
beraberinde getirebileceği için top-level import edilmez — böylece endpoint
route kayıt aşamasında import hatası oluşmaz.

VİOP kontratları integer lot ile işlem gördüğünden `lot_min` ve `lot_step`
canonical olarak 1.0 hard-defaulted. İleride symbol-özel `volume_min` /
`volume_step` gerekirse helper bu noktada genişletilebilir (MT5 `symbol_info`
tüketimi).

### 3.3 Frontend — `desktop/src/services/api.js`
`getTradingLimits()` async export eklendi. Hata durumunda `{lot_min: 1.0,
lot_max: 1.0, lot_step: 1.0, source: 'error'}` fallback objesi döner — UI
hiçbir koşulda sınırsız input kalmaz.

### 3.4 Frontend — `desktop/src/components/ManualTrade.jsx`
- `getTradingLimits` import eklendi.
- Yeni `const [lotLimits, setLotLimits] = useState({lot_min: 1, lot_max: 1, lot_step: 1})`.
- Yeni `useEffect` (mount-only, `[]` dependency): `getTradingLimits()` çağırır,
  gelen değer pozitifse `setLotLimits` ile state güncellenir. Mevcut `lot`
  state'i yeni sınırların dışındaysa içeri çekilir (`setLot(prev => ...)`).
  `cancelled` flag cleanup ile unmount sonrası setState uyarısı engellendi.
- Lot input JSX: `min={1} max={10} step={1}` → `min={lotLimits.lot_min}
  max={lotLimits.lot_max} step={lotLimits.lot_step}`.

Sonuç: `config/default.json` içinde `max_lot_per_contract: 1.0` olduğu sürece,
UI lot input'u `min=1 max=1 step=1` olarak render edilir. Kullanıcı 10 girişi
yapamaz; native HTML5 number input tarayıcı/Electron tarafında reddeder.

### 3.5 Test — `tests/critical_flows/test_static_contracts.py`
Flow 4r eklendi (`test_manual_trade_lot_limits_from_config`). 6 aşamalı
statik sözleşme:

1. `config/default.json.engine.max_lot_per_contract` mevcut + pozitif sayı.
2. `api/schemas.py::TradingLimitsResponse` sınıfı + `lot_min` / `lot_max` /
   `lot_step` alanları.
3. `api/routes/settings.py` → `_read_trading_limits` helper +
   `engine.max_lot_per_contract` okuma string'i + `/settings/trading-limits`
   route + `TradingLimitsResponse` kullanımı.
4. `services/api.js` → `getTradingLimits` export + `/settings/trading-limits`
   çağrısı + fallback objesinde `lot_min/lot_max/lot_step`.
5. `ManualTrade.jsx` → eski `min={1}` ve `max={10}` regex literalleri YOK +
   `getTradingLimits` import + `lotLimits` state + lot input 3 attribute
   `lotLimits.*` ile bağlı.
6. `setLotLimits` setter çağrısı mevcut (useEffect içinde).

### 3.6 Changelog — `docs/USTAT_GELISIM_TARIHCESI.md`
#181 girişi eklendi (#180'den önce): 5 dosya kod + 1 test, test/build
sonuçları, Anayasa uyumu notları.

---

## 4. Etki Analizi (Call Chain)

```
ManualTrade mount
  → useEffect → getTradingLimits()
    → axios GET /api/settings/trading-limits
      → @router.get("/settings/trading-limits") → get_trading_limits()
        → _read_trading_limits()
          → runtime import: engine.config.Config
          → cfg.get("engine.max_lot_per_contract") → 1.0
          → tip + pozitif kontrolü
        → TradingLimitsResponse(lot_min=1.0, lot_max=1.0, lot_step=1.0, source="config")
  ← response
  → setLotLimits({...})
  → setLot(prev => clamp(prev, min, max))
  → JSX <input min={lotLimits.lot_min} max={lotLimits.lot_max} step={lotLimits.lot_step}/>
```

Tüketiciler:
- `ManualTrade.jsx` — sadece bu bileşen.
- `HybridTrade.jsx`, `AutoTrading.jsx` — dokunulmadı (kendi akışları var).

Motor etkisi: YOK. `manuel_motor.py`, `ogul.py`, `baba.py` hiçbir şekilde
değişmedi. Yalnızca UI tarafında görünen kısıt motor tarafındaki kısıt ile
hizalandı.

---

## 5. Anayasa Uyumu

- **Kırmızı Bölge dokunuşu:** YOK. `engine/ogul.py`, `engine/baba.py`,
  `engine/mt5_bridge.py`, `engine/manuel_motor.py`, `config/default.json`
  — hiçbirine dokunulmadı.
- **Sarı Bölge dokunuşu:** YOK.
- **Yeşil Bölge dosyaları:** `api/schemas.py`, `api/routes/settings.py`,
  `desktop/src/services/api.js`, `desktop/src/components/ManualTrade.jsx`,
  `tests/critical_flows/test_static_contracts.py`,
  `docs/USTAT_GELISIM_TARIHCESI.md`.
- **Siyah Kapı fonksiyonu:** Dokunulmadı.
- **Sihirli sayı:** UI tarafında kaldırıldı. Backend fallback sabitleri
  `DEFAULT_LOT_MIN/MAX/STEP = 1.0` VİOP'un native integer kontrat özelliğini
  yansıtıyor, canonical değil fallback.
- **Çağrı sırası:** Dokunulmadı (BABA → OĞUL → H-Engine → ÜSTAT).
- **Config değişikliği:** YOK.

---

## 6. Test ve Build Sonuçları

### 6.1 Kritik akış testleri
```
python -m pytest tests/critical_flows -q --tb=short
```
Sonuç: **51 passed, 3 warnings in 3.25s**. Flow 4r yeni eklendi, diğer 50
flow dokunulmadan geçti.

### 6.2 Windows production build
```
python .agent/claude_bridge.py build
```
Sonuç: **başarılı**, `ustat-desktop@6.0.0`, 728 modül transform edildi, 2.65 s,
`index.js` 888.72 kB (gzip 254.47 kB), `index.css` 90.52 kB.

---

## 7. Versiyon Durumu

Tek atomik C1 düzeltme. Toplam değişiklik oranı düşük (~100 satır). Versiyon
`v6.0.0` korunuyor.

---

## 8. Dosya Listesi

1. `api/schemas.py` (+20 satır — TradingLimitsResponse)
2. `api/routes/settings.py` (+60 satır — DEFAULT_LOT_*, _read_trading_limits, route)
3. `desktop/src/services/api.js` (+21 satır — getTradingLimits)
4. `desktop/src/components/ManualTrade.jsx` (+30 / -3 satır)
5. `tests/critical_flows/test_static_contracts.py` (+125 satır — Flow 4r)
6. `docs/USTAT_GELISIM_TARIHCESI.md` (+1 satır — #181)
7. `docs/2026-04-11_session_raporu_H4_manual_trade_lot_limits.md` (yeni — bu dosya)

---

## 9. Dokunulmayanlar (Bilinçli)

- **`engine/manuel_motor.py::MAX_LOT_PER_CONTRACT = 1.0`** — Module sabiti
  hâlâ hardcode, config'den override edilmiyor. Bu ayrı bir audit maddesi
  olabilir (ikincil canonical kaynak). Bu oturum yalnızca UI tarafını ele aldı;
  motor tarafının config'e bağlanması ayrı atomik değişiklik gerektirir ve
  Siyah Kapı'ya yakın (`_execute_signal` çağrı zinciri). H4 skopu dışı.
- **`config.engine.max_lot_per_contract` değeri** değiştirilmedi. 1.0 olarak
  bırakıldı — mevcut üretim davranışı korundu.
- **`manual_trade.py` API route'u** dokunulmadı. Emir kontrolü ve yürütme
  mantığı aynı; UI sadece kullanıcının sınır-aşırı değer girmesini engelliyor.

---

## 10. Sonuç

Widget Denetimi H4 maddesi tamamen kapatıldı. ManualTrade lot input'u artık
`config.engine.max_lot_per_contract` canonical kaynağından besleniyor;
kullanıcı motor sınırının üzerinde değer giremez. Silent truncation kaynaklı
yanıltıcı UX tamamen kalktı. Statik sözleşme (Flow 4r) bu zinciri commit
öncesi her seferinde doğrular.

Sonraki aday: H6 (Hata Takip EOD saat sabitleri), H14 (Monitor Performans
max eşiği), H10 (Performans seans saat aralığı 9-18). Sıradaki pick aynı
disiplinle devam edecek.
