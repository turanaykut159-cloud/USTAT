# Oturum Raporu — A17 BIST Seans Saatleri Config Zinciri

**Tarih:** 2026-04-11 (Cumartesi, Barış Zamanı)
**Kapsam:** Widget Denetimi Bulgu A17 (H6+H10) — ErrorTracker EOD geri sayım + Performance saat-bazlı heatmap
**Sınıf:** C3 (Kırmızı Bölge additive, risk/strateji/eşik parametresi dokunulmadı)
**Etki:** 6 dosya + 1 test
**Siyah Kapı / Kırmızı Bölge fonksiyon dokunusu:** YOK

---

## 1. Kök Neden

İki frontend bileşeni BIST VİOP seans saatlerini **hardcoded literal** olarak tutuyordu:

### ErrorTracker.jsx (satır 61-67)
```jsx
const EOD_CLOSE_HOUR = 17;
const EOD_CLOSE_MIN = 45;
const VIOP_OPEN_HOUR = 9;
const VIOP_OPEN_MIN = 30;
const VIOP_CLOSE_HOUR = 18;
const VIOP_CLOSE_MIN = 15;
```
`getEodInfo()` bu sabitleri doğrudan okuyarak "EOD'ye kalan süre" label'ını üretiyordu.

### Performance.jsx (satır 232)
```jsx
for (let h = 9; h <= 18; h++) {
  hours[h] = { hour: h, count: 0, pnl: 0, wins: 0 };
}
```
Saat-bazlı heatmap 9-18 aralığını literal üretiyordu.

**Sonuç:** Backend `config/default.json::engine.trading_close = "17:45"` (Anayasa Kural #5, EOD zorunlu kapanış) değişse bile frontend sessizce senkronsuz kalırdı. BIST VİOP sabitleri stabil ama "tek doğru kaynak" backend tarafındadır; frontend `config/default.json::engine.trading_close` ile tutarsız kalırsa kullanıcı Monitor/ErrorTracker/Performance panellerine güvenerek yanlış kararlar alabilir.

## 2. Atomik Değişiklikler

### Backend (3 dosya)

**config/default.json** — yeni `session` bloğu eklendi:
```json
"session": {
  "market_open": "09:30",
  "market_close": "18:15",
  "eod_close": "17:45"
}
```
Kırmızı Bölge #8 additive — risk/strateji/eşik/baseline/drawdown parametresi **DEĞİŞMEDİ**. `engine.trading_open` (09:45) / `engine.trading_close` (17:45) dokunulmadı — engine buffered trading window'u ayrı namespace'inde kalır, session namespace'i salt-UI referans.

**api/schemas.py** — yeni `SessionHoursResponse` Pydantic modeli:
```python
class SessionHoursResponse(BaseModel):
    market_open: str = "09:30"
    market_close: str = "18:15"
    eod_close: str = "17:45"
    source: str = "config"  # config | default
```

**api/routes/settings.py** — `DEFAULT_SESSION_HOURS` fallback + `_read_session_hours_from_config()` helper + `GET /settings/session` endpoint'i. Helper engine.config'den okur, eksik anahtarları default ile merge eder, `^\d{2}:\d{2}$` regex doğrulaması yapar (geçersiz değer sessizce default'a düşer). `(merged, source)` tuple döner.

### Frontend (3 dosya)

**desktop/src/services/api.js** — yeni `getSession()`:
```js
export async function getSession() {
  try {
    const { data } = await client.get('/settings/session');
    return data;
  } catch (err) {
    console.error('[ÜSTAT API] getSession:', err?.message ?? err);
    return {
      market_open: '09:30',
      market_close: '18:15',
      eod_close: '17:45',
      source: 'error',
    };
  }
}
```

**desktop/src/components/ErrorTracker.jsx:**
- 6 hardcoded `EOD_CLOSE_*`/`VIOP_*` literal sabit KALDIRILDI
- `DEFAULT_SESSION_HOURS` fallback + `parseHHMM(str)` helper eklendi
- `getEodInfo(sessionCfg = DEFAULT_SESSION_HOURS)` parametre kabul eder, parse hatalarında fallback'e düşer
- `useState(DEFAULT_SESSION_HOURS)` ile `sessionHours` state'i
- `useEffect` mount'ta `getSession()` çağırıp state'i günceller ve `setEod(getEodInfo(next))` ilk değeri de yeniler (cancelled flag cleanup'lı)
- Dakikalık `setInterval` artık `getEodInfo(sessionHours)` kullanır ve `[sessionHours]` dependency ile yeniden kurulur

**desktop/src/components/Performance.jsx:**
- Yeni `DEFAULT_HEATMAP_HOURS` sabiti + `parseHour(str)` helper
- `useState(DEFAULT_HEATMAP_HOURS)` ile `heatmapHours` state'i
- `useEffect` mount'ta `getSession()` çağırır
- `hourData` useMemo bloğu eski `for (let h = 9; h <= 18; h++)` literal'i kaldırıldı, `openHour`/`closeHour` state'ten parse edilir
- useMemo dependency array'ine `heatmapHours` eklendi

### Test (1 yeni akış)

**tests/critical_flows/test_static_contracts.py::test_session_hours_from_config_to_frontend** (Flow 4i) — 6 aşamalı statik sözleşme kontrolü:
1. `config/default.json::session` bloğu var ve 3 anahtar string tipte
2. `api/schemas.py::SessionHoursResponse` sınıfı + 3 field var
3. `api/routes/settings.py::get_session_hours` fonksiyonu var, `/settings/session` route kaydı var, `config.get("session"` çağırır
4. `services/api.js::getSession` export var ve `/settings/session` endpoint'i çağırır
5. `ErrorTracker.jsx` getSession import eder + DEFAULT_SESSION_HOURS fallback var + 6 eski hardcoded literal YASAK
6. `Performance.jsx` getSession import eder + heatmapHours state'i var + eski `for (let h = 9; h <= 18; h++)` literal YASAK

## 3. Dokunulmayanlar (Bilinçli)

- **engine/baba.py::run_cycle** (Siyah Kapı #10) — EOD kontrolü zaten `self.config.get("engine.trading_close")` kullanıyor, backend davranışı değişmez
- **engine/ogul.py::_check_end_of_day** (Siyah Kapı #13) — aynı sebep
- **engine.trading_open / engine.trading_close** namespace'i — buffered trading window (09:45) session.market_open (09:30)'dan 30dk buffer'lıdır; iki semantik ayrı tutuldu
- **api/routes/settings.py::_risk_baseline, _notification_prefs helper'ları** — ayrı alanlar
- **Dashboard.jsx** ve diğer bileşenler — hardcoded saat referansı taraması yapıldı, başka kullanım bulunmadı

## 4. Doğrulama

| Kontrol | Sonuç |
|---------|-------|
| `pytest tests/critical_flows -q` | **42 passed** (41 baseline + 1 yeni Flow 4i), 2.77s |
| Flow 4i bağımsız | PASSED, 0.33s |
| `npm run build` (Windows, ilk deneme) | HATA — `getEodInfo(hours = ...)` parametre ismi ErrorTracker içindeki lokal `const hours = Math.floor(remaining / 60)` ile collision |
| `npm run build` (Windows, ikinci deneme) | **Başarılı** — `sessionCfg` rename sonrası 728 modül, 2.64s, 0 hata |
| Siyah Kapı ihlali | **YOK** |
| Kırmızı Bölge ihlali | **YOK** (risk/strateji/eşik parametresi değişmedi) |

## 5. Etki Analizi

- **Dosya sayısı:** 6 (1 config + 2 backend + 3 frontend) + 1 test
- **Net satır:** ~140 (backend helper ~30 + schema ~15 + api.js ~15 + ErrorTracker ~40 + Performance ~25 + config ~5 + test ~135)
- **Çağıran zinciri:** `getSession()` → `ErrorTracker.sessionHours` state → `getEodInfo(sessionHours)` → EOD geri sayım label; `getSession()` → `Performance.heatmapHours` state → `hourData` useMemo → BarChart
- **Tüketici zinciri:** Geriye dönük uyumlu — mevcut API konsümerleri yeni endpoint'i görmüyor, yeni state'ler ilgili bileşen içinde kalır
- **Geriye dönük uyumluluk:** Tam — backend davranışı değişmedi, frontend fallback'ler ağ hatasında dahi UI'ı ayakta tutar

## 6. İlk Build Hatası ve Çözüm

İlk `npm run build` denemesi:
```
ERROR: The symbol "hours" has already been declared
137|    const remaining = eodMins - nowMins;
138|    const hours = Math.floor(remaining / 60);
139|           ^
```

`getEodInfo(hours = DEFAULT_SESSION_HOURS)` parametre ismi, fonksiyonun alt kısmındaki `const hours = Math.floor(remaining / 60)` lokal değişken ile çakışıyordu. Parametre `sessionCfg` olarak yeniden adlandırıldı, parse blokları da buna göre güncellendi. İkinci build temiz geçti.

## 7. Deploy Kararı

Piyasa kapalı (Cumartesi, Barış Zamanı). Deploy için `restart_app` yeterli — API yeni route'u serve eder, Electron yeni `dist/` bundle'ını yükler. Kullanıcı zamanlamayı seçer; halen bekleyen A1+A2+A3+A4+B+B25+A9+A17 paketiyle birlikte veya ayrı deploy edilebilir.

## 8. Sonraki Adımlar

- Widget Denetimi kalan A maddeleri: A7 (Baseline tekilleştirme), A6 (Performans equity/deposits), A diğerleri
- B17 (TRADE_ERROR kategori haritalama), B8 (Dashboard Otomatik Pozisyon Özeti 45 vs 31), B11 (Monitor MT5 hardcode)
- A1+A2+A3+A4+B+B25+A9+A17 paket deploy zamanlaması (kullanıcı kararı)

## 9. Kaynak

- `docs/2026-04-11_widget_denetimi.md` Bölüm 11.4 + Bölüm 17 A17 (H6+H10)
- Audit bulgu özeti: "ErrorTracker.jsx içindeki hardcoded saat sabitleri config/default.json.session altından okunsun; aynı şey Performans · Heatmap'teki 9-18 için"
- Backend `config/default.json::engine.trading_close = "17:45"` (Anayasa Kural #5)
