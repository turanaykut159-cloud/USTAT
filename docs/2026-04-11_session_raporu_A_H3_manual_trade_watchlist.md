# Oturum Raporu — A-H3: ManualTrade Watchlist Tek Kaynak

**Tarih:** 11 Nisan 2026 (Cumartesi — Barış Zamanı)
**Konu:** Widget Denetimi A-H3 — ManualTrade sembol listesinin tek kaynaktan gelmesi
**Değişiklik Sınıfı:** C1 (Yeşil Bölge — Kırmızı/Sarı Bölge dokunulmadı)
**İşlem Tipi:** Tek atomik değişiklik zinciri (6 dosya)

---

## 1. Kapsam

Widget Denetimi `docs/2026-04-11_widget_denetimi.md` içinde A-H3 maddesi:
> **ManualTrade.jsx hardcoded SYMBOLS** — Manuel İşlem ekranında 15 VİOP kontratı JSX içinde bir dizi olarak yazılmış. `engine/mt5_bridge.py::WATCHED_SYMBOLS` ile drift riski var. Tek kaynak haline getir.

Bu madde çözüldü. ManualTrade bileşeni artık `/api/settings/watchlist` endpoint'inden dinamik liste okur; endpoint ise runtime'da `engine.mt5_bridge.WATCHED_SYMBOLS` değişkenini tüketir. Drift kesildi.

---

## 2. Kök Neden

Önceki durum:
- `engine/mt5_bridge.py` → `WATCHED_SYMBOLS = ["F_THYAO", ..., "F_KONTR"]` (15 element) — sistemin gerçek kaynak listesi. `data_pipeline.py`, `baba.py`, `ogul.py`, `backtest.py` bunu kullanır.
- `desktop/src/components/ManualTrade.jsx` → `const SYMBOLS = [...]` (15 element kopyası). JSX dropdown bu kopyayı kullanır.

İki liste ayrı dosyada. Birinde değişiklik yapılırsa diğeri senkron kalmaz. Kullanıcı Manuel İşlem dropdown'ında olmayan bir sembol için bridge'te polling olur veya tersi. Aynı veri tekrarı = drift riski.

---

## 3. Yapılan Değişiklikler

### 3.1 Backend — `api/schemas.py`
Yeni yanıt modeli:

```python
class WatchlistResponse(BaseModel):
    """GET /api/settings/watchlist — İzlenen 15 VİOP kontratı (Widget Denetimi A-H3)."""
    symbols: list[str] = []
    source: str = "bridge"   # bridge | default | error
```

### 3.2 Backend — `api/routes/settings.py`
Üç ek:
- `DEFAULT_WATCHLIST_SYMBOLS` sabiti (bridge erişilemezse fallback)
- `_read_watchlist_symbols()` helper — runtime'da `engine.mt5_bridge.WATCHED_SYMBOLS` import eder. Import ya da liste bozulursa default'a düşer, `source` alanı `error`/`default` olarak işaretlenir.
- `GET /settings/watchlist` route (response_model=WatchlistResponse)

Runtime import neden? Test ortamında MetaTrader5 modülü bulunmayabilir, top-level import `api.routes.settings` açılışını kilitler. Fonksiyon içinde import güvenlidir.

### 3.3 Frontend — `desktop/src/services/api.js`
`getWatchlistSymbols()` export edildi. Hata durumunda 15 elementlik hardcode fallback döner; `source: 'error'` işaretlenir. UI kullanıcıya asla boş dropdown göstermez.

### 3.4 Frontend — `desktop/src/components/ManualTrade.jsx`
- `const SYMBOLS = [...]` adı `DEFAULT_SYMBOLS` yapıldı (fallback görevli).
- `useState(DEFAULT_SYMBOLS)` ile `watchlist` state eklendi.
- Yeni `useEffect`: mount'ta `getWatchlistSymbols()` çağrısı. Dönen sembol dizisi boş değilse state güncellenir; mevcut seçili `symbol` artık listede yoksa `symbols[0]`'a düşer (dropdown tutarlılığı).
- Cleanup: `cancelled` flag → unmount sonrası setState uyarısı engellendi.
- JSX: `{SYMBOLS.map(...)}` → `{watchlist.map(...)}`.

### 3.5 Test — `tests/critical_flows/test_static_contracts.py`
Flow 4q eklendi (`test_manual_trade_watchlist_single_source`). 6 aşamalı statik sözleşme:
1. `engine/mt5_bridge.py::WATCHED_SYMBOLS` tanımı + ≥10 sembol.
2. `api/schemas.py::WatchlistResponse` sınıfı + `symbols` alanı.
3. `api/routes/settings.py` → `_read_watchlist_symbols` + WATCHED_SYMBOLS import + `/settings/watchlist` route + `WatchlistResponse` kullanımı.
4. `services/api.js` → `getWatchlistSymbols` export + `/settings/watchlist` çağrısı + fallback sembolleri.
5. `ManualTrade.jsx` → `const SYMBOLS = [` kalıntısı YOK + `getWatchlistSymbols` import + `watchlist` state.
6. JSX'te `watchlist.map` kullanılıyor, eski `SYMBOLS.map` kalıntısı YOK.

### 3.6 Changelog — `docs/USTAT_GELISIM_TARIHCESI.md`
#180 girişi eklendi (#179'dan önce): 5 dosya kod + 1 test kontratı zinciri özeti, Anayasa uyumu notları, test+build sonuçları.

---

## 4. Etki Analizi (Call Chain)

```
ManualTrade mount
  → useEffect → getWatchlistSymbols()
    → axios GET /api/settings/watchlist
      → @router.get("/settings/watchlist") → get_watchlist()
        → _read_watchlist_symbols()
          → runtime import: engine.mt5_bridge.WATCHED_SYMBOLS
          → clean + validate
        → WatchlistResponse(symbols=..., source="bridge")
  ← response
  → setWatchlist(symbols)
  → JSX {watchlist.map(s => <option>)}
```

Her halka tek sorumluluğa sahip. Fallback zinciri 3 kat (bridge → default → error), UI her koşulda çalışır.

---

## 5. Anayasa Uyumu

- **Kırmızı Bölge dokunuşu:** YOK. `engine/mt5_bridge.py::WATCHED_SYMBOLS` sadece OKUNDU, değiştirilmedi.
- **Sarı Bölge dokunuşu:** YOK.
- **Yeşil Bölge dosyaları:** `api/schemas.py`, `api/routes/settings.py`, `desktop/src/services/api.js`, `desktop/src/components/ManualTrade.jsx`, `tests/critical_flows/test_static_contracts.py`, `docs/USTAT_GELISIM_TARIHCESI.md`.
- **Siyah Kapı fonksiyonu:** Dokunulmadı.
- **Sihirli sayı:** Yok. Sembol listesi runtime'da bridge'ten çekiliyor, fallback sabit listede korunuyor.
- **Çağrı sırası:** Dokunulmadı (BABA → OĞUL → H-Engine → ÜSTAT).
- **Config değişikliği:** YOK. `config/default.json` hiç açılmadı — zira bridge listesi zaten canonical kaynak, ikinci kaynak eklemek drift riskini geri getirirdi.

---

## 6. Test ve Build Sonuçları

### 6.1 Kritik akış testleri
```
python -m pytest tests/critical_flows -q --tb=short
```
Sonuç: **50 passed in 3.20s**. Flow 4q yeni eklendi, diğer 49 flow hiç bozulmadı.

### 6.2 Windows production build
```
python .agent/claude_bridge.py build
```
Sonuç: **başarılı**, `ustat-desktop@6.0.0`, 728 modül transform edildi, 2.65 s, `index.js` 888.05 kB gzip.

---

## 7. Versiyon Durumu

Bu değişiklik zinciri tek atomik C1 düzeltmesi. Toplam oran (git diff --stat) %10'un altında kalıyor, major/minor artışı gerekmiyor. Versiyon `v6.0.0` aynen korunuyor.

---

## 8. Dosya Listesi

1. `api/schemas.py` (+12 satır)
2. `api/routes/settings.py` (+40 satır)
3. `desktop/src/services/api.js` (+18 satır)
4. `desktop/src/components/ManualTrade.jsx` (+24 / -15 satır)
5. `tests/critical_flows/test_static_contracts.py` (+76 satır — Flow 4q)
6. `docs/USTAT_GELISIM_TARIHCESI.md` (+28 satır — #180)
7. `docs/2026-04-11_session_raporu_A_H3_manual_trade_watchlist.md` (yeni — bu dosya)

---

## 9. Sonuç

Widget Denetimi A-H3 maddesi tamamen kapatıldı. ManualTrade watchlist'i artık `engine/mt5_bridge.py::WATCHED_SYMBOLS` tek kaynağından besleniyor; drift kapısı kapandı. Statik sözleşme (Flow 4q) bu zinciri commit öncesi her seferinde doğrular.

Sonraki aday: H4 (Manuel İşlem lot input min/max sınırları) veya H14 (Monitor performance threshold). Sıradaki pick aynı disiplinle devam edecek.
