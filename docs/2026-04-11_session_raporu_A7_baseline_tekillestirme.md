# Oturum Raporu — Widget Denetimi A7 (B21): Baseline Tekilleştirme

**Tarih:** 11 Nisan 2026 (Cumartesi — Barış Zamanı)
**Konu:** `STATS_BASELINE` ile `risk.baseline_date` tek kaynaktan okunur hale getirildi
**Değişiklik Sınıfı:** C3 (config Kırmızı Bölge — sadece yeni anahtar eklendi, mevcut risk/strateji sabitleri dokunulmadı) + C1 (Yeşil Bölge helper/api/frontend)
**Versiyon:** v6.0.0 (değişmedi — audit fix kapsamında küçük ekleme)
**Changelog:** #173
**Commit:** (commit sonrası eklenecek)

---

## 1. Kök Neden (Widget Denetimi Bulgu A7 — B21)

Audit belgesi `docs/2026-04-11_widget_denetimi.md`'de kayıt altına alınmış Bulgu B21'in özü:

- **Dashboard / Performance / TradeHistory** istatistik kartları (win_rate, profit_factor, best_trade, vs.) `api/constants.py::STATS_BASELINE` üzerinden çalışıyordu. Bu sabit hardcoded `"2026-02-01"` değeriydi ve config'ten okunmuyordu.
- **BABA** peak_equity / drawdown / aylık-haftalık kayıp hesaplamaları ise `config.risk.baseline_date` (`"2026-04-01 00:01"`) üzerinden ayrı bir kaynaktan okuyordu. Settings sayfasından kullanıcı sadece bu risk baseline'ını değiştirebiliyordu.
- İki kavram ayrıydı ama UI'de ayrıştırılmadığı için kullanıcı "hangi tarihten beri istatistik sayılıyor?" ile "hangi tarihten beri drawdown sayılıyor?" sorularını ayırt edemiyordu. Audit'in teknik maddesi şöyleydi:

> "UI'de hangi baseline aktif olduğu küçük bir label olarak gösterilmeli. İstatistik baseline'ı da config'e alınmalı; aksi halde kullanıcı iki farklı başlangıç tarihi arasında kaybolur."

Bu bulgu B21 numarasıyla audit'te yer alıyordu, tekilleştirme aksiyonu A7 önceliğiyle işaretlenmişti.

## 2. Çözüm Özeti

Tek satırla: **istatistik baseline'ı config'e taşındı, her iki baseline tek endpoint'ten döndürülüyor, UI küçük bir etikette ikisini ayrı ayrı gösteriyor.**

Fonksiyonel hedefler:

1. `api/constants.py::STATS_BASELINE` değerini değiştirmek değil — **nereden okunduğunu değiştirmek**. Eski sabit geri uyum için fallback olarak korundu.
2. Yeni bir config anahtarı (`risk.stats_baseline_date`) üzerinden istatistik baseline'ı kullanıcı kontrolüne açılabilir hale geldi (şimdilik config dosyasında, ileride Settings POST endpoint'i eklenebilir — bu oturum kapsam dışı).
3. `/api/settings/stats-baseline` endpoint'i hem stats hem risk baseline'ı tek payload'da, her biri için `source` metadata'sı ile döndürüyor. Frontend bu endpoint'ten çekiyor ve kullanıcıya iki tarihi ayrı ayrı gösteriyor.
4. Backend'deki tüm istatistik okuyan route'lar (`performance.py`, `trades.py`) artık `STATS_BASELINE` sabiti yerine `get_stats_baseline()` helper'ı çağırıyor. Bu sayede ileride config değişikliği otomatik olarak tüm istatistik zincirine yansıyor.
5. Siyah Kapı fonksiyonları (BABA peak_equity/drawdown mantığı, `_check_hard_drawdown`, `_activate_kill_switch`, vs.) **hiç dokunulmadı**. Mevcut `/settings/risk-baseline` POST endpoint'i de **hiç dokunulmadı** — sadece okuma zinciri birleştirildi.

## 3. Atomik Değişiklik Listesi (9 dosya)

### 3.1 Config (C3 — Kırmızı Bölge, additive)

**`config/default.json`** — `risk` bloğu içine yeni anahtar eklendi:

```json
"risk": {
  "baseline_date": "2026-04-01 00:01",
  "stats_baseline_date": "2026-02-01",
  ...
}
```

Mevcut `baseline_date` ve diğer risk parametreleri (drawdown limitleri, pozisyon sayıları, vs.) **hiç değiştirilmedi**. Sadece yeni anahtar eklendi → Anayasa 5.1 ihlali yok.

### 3.2 Backend Helper (C1 — Yeşil Bölge rewrite)

**`api/constants.py`** — baştan yazıldı. Eski davranış korundu, üstüne helper fonksiyon eklendi:

```python
STATS_BASELINE = "2026-02-01"  # Fallback (geriye dönük uyum)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?$")

def get_stats_baseline() -> str:
    """Config'den risk.stats_baseline_date oku, yoksa STATS_BASELINE default."""
    # Engine yok → default
    # config.get hata → default
    # Format geçersiz → default
    # Aksi halde config değeri
```

Fallback zinciri: engine missing → config missing → invalid format → default `STATS_BASELINE`. Hiçbir durumda exception propagate olmuyor.

### 3.3 Backend Route Güncellemeleri (C1)

**`api/routes/performance.py`** — 2 nokta güncellendi:

- Import satırına `get_stats_baseline` eklendi.
- Trade fetch öncesi `baseline = get_stats_baseline()` çağrılıyor ve `db.get_trades(since=baseline, limit=5000)` olarak kullanılıyor.
- Risk snapshot zaman filtresinde `_snap_since = baseline[:10] if baseline else STATS_BASELINE` üzerinden `f"{_snap_since}T00:00:00"` kullanılıyor.

**`api/routes/trades.py`** — `/trades/stats` endpoint:

- Import satırına `get_stats_baseline` eklendi.
- Query parametresi `since` default'u `STATS_BASELINE` yerine `None` oldu.
- Kullanıcı explicit `since` vermezse `effective_since = since if since else get_stats_baseline()` ile helper'dan okunuyor.
- `rows = db.get_trades(since=effective_since, limit=limit)`.

Bu iki dosya Yeşil Bölge; Anayasa 4.4 Siyah Kapı listesinde değil.

### 3.4 Backend Schema (C1)

**`api/schemas.py`** — `SessionHoursResponse` sınıfından sonra `StatsBaselineResponse` eklendi:

```python
class StatsBaselineResponse(BaseModel):
    stats_baseline: str = "2026-02-01"
    risk_baseline: str = ""
    stats_source: str = "default"
    risk_source: str = "default"
```

### 3.5 Backend Endpoint (C1)

**`api/routes/settings.py`** — `GET /api/settings/stats-baseline` endpoint eklendi:

- `get_stats_baseline()` helper'ından stats değeri ve source (`config` veya `default`) hesaplanıyor.
- `risk.baseline_date` önce `engine.config` üzerinden okunuyor. Boşsa baba'nın `_risk_baseline_date` runtime alanından fallback olarak okunuyor.
- Her iki baseline ve her iki source tek payload'da döndürülüyor.
- Mevcut `/settings/risk-baseline` POST endpoint'i **dokunulmadı** — kullanıcının Settings'te mevcut davranışı bozulmadı.

### 3.6 Frontend API Client (C1)

**`desktop/src/services/api.js`** — 2 nokta:

- Eski `STATS_BASELINE = '2026-02-01'` sabiti **korundu** (fallback). JSDoc'ta A7 açıklaması eklendi.
- Yeni `getStatsBaseline()` fonksiyonu: `/settings/stats-baseline` çağırıyor, hata durumunda `STATS_BASELINE` fallback değerlerini döndürüyor (crash yok).

### 3.7 Frontend Bileşenleri (C1)

**`desktop/src/components/Performance.jsx`** — 3 nokta:

- Import satırına `getStatsBaseline` eklendi.
- Yeni `baselineInfo` state: `{stats_baseline: STATS_BASELINE, risk_baseline: '', stats_source: 'default', risk_source: 'unavailable'}`.
- Mount useEffect — `getStatsBaseline()` çağırıyor, `cancelled` flag ile cleanup yapıyor. Component unmount edilse bile state update yazılmıyor (React warning yok).
- `fetchPerfData` — `getTradeStats(1000, baselineInfo.stats_baseline)` ve `getTrades({since: baselineInfo.stats_baseline, limit: 1000})` kullanıyor. Dependency list `[days, baselineInfo.stats_baseline]`.
- Periyot butonlarının altına yeni küçük label:

```jsx
<div className="pf-baseline-label" title="İstatistik tabanı: ...">
  <span>İstatistik tabanı: <b>{(baselineInfo.stats_baseline || STATS_BASELINE).slice(0, 10)}</b></span>
  {baselineInfo.risk_baseline && (
    <span style={{ marginLeft: 12 }}>· Risk tabanı: <b>{baselineInfo.risk_baseline.slice(0, 10)}</b></span>
  )}
</div>
```

**`desktop/src/components/TradeHistory.jsx`** — aynı pattern:

- Import satırına `getStatsBaseline` eklendi.
- `baselineInfo` state + mount useEffect + cancelled flag.
- `fetchData` callback'i baseline'ı `effective_since` olarak kullanıyor. Dependency `[baselineInfo.stats_baseline]`.
- Render'ın üst tarafında (periyot butonlarından önce) `th-baseline-label` eklendi — aynı içerik.

### 3.8 Test (C1 — Yeşil Bölge ekleme)

**`tests/critical_flows/test_static_contracts.py`** — `test_stats_baseline_single_source_chain` (Flow 4j) eklendi. 9 aşamalı statik sözleşme:

1. `config/default.json` → `risk.stats_baseline_date` anahtarı mevcut.
2. `api/constants.py` → `STATS_BASELINE` sabiti hâlâ var (fallback).
3. `api/constants.py` → `get_stats_baseline` helper mevcut.
4. `api/schemas.py` → `StatsBaselineResponse` sınıfı mevcut.
5. `api/routes/settings.py` → `/settings/stats-baseline` endpoint tanımı mevcut.
6. `api/routes/performance.py` ve `api/routes/trades.py` → `get_stats_baseline` import ediyor.
7. `desktop/src/services/api.js` → `STATS_BASELINE` sabiti korunmuş + `getStatsBaseline` export ediyor.
8. `Performance.jsx` → `baselineInfo` state + `pf-baseline-label` label mevcut.
9. `TradeHistory.jsx` → `baselineInfo` state + `th-baseline-label` label mevcut.

Bu test, ileride biri bu zincirdeki herhangi bir halkayı sessizce silmeye kalkarsa pre-commit hook'un durdurmasını sağlıyor.

## 4. Anayasa Etki Analizi

| Katman | Durum |
|--------|-------|
| Kırmızı Bölge | `config/default.json` — sadece yeni anahtar (additive). Mevcut risk parametreleri 0 değişiklik. |
| Sarı Bölge | Dokunulmadı. |
| Yeşil Bölge | `api/constants.py`, `api/routes/performance.py`, `api/routes/trades.py`, `api/routes/settings.py`, `api/schemas.py`, `desktop/src/services/api.js`, `desktop/src/components/Performance.jsx`, `desktop/src/components/TradeHistory.jsx`, `tests/critical_flows/test_static_contracts.py` |
| Siyah Kapı | **Hiç dokunulmadı.** BABA peak_equity/drawdown, `_check_hard_drawdown`, `check_risk_limits`, `_activate_kill_switch`, `_close_all_positions`, `_close_ogul_and_hybrid` — hepsi aynı. |
| Değişmez Kurallar | Çağrı sırası değişmedi. Risk kapısı dokunulmadı. Kill-switch monotonluğu etkilenmedi. SL/TP zorunluluğu etkilenmedi. EOD zorunlu kapanışa temas yok. Hard drawdown eşiği (%15) değişmedi. |

Audit maddesi "istatistik baseline'ı Settings'ten değiştirilebilir olmalı" kısmı şu an için **config dosyası üzerinden** karşılandı (`risk.stats_baseline_date`). Settings POST endpoint'i ileride ayrı bir commit ile eklenebilir — bu oturumun kapsamı dışı, audit önceliği A7'nin ilk aşaması olarak kapandı.

## 5. Doğrulama

### 5.1 Kritik Akış Testleri

```
python -m pytest tests/critical_flows -q --tb=short
```

Sonuç: **43 passed in 3.92s** (önceki 42 baseline + yeni Flow 4j).

### 5.2 Windows Production Build

`python .agent/claude_bridge.py build` üzerinden `npm run build`:

- 728 modül dönüştürüldü
- 2.65 saniye
- 0 hata
- `index.js` 886.38 kB (gzip: 261 kB)
- `index.css` 150.93 kB (gzip: 22 kB)

Önceki A17 build'inde tespit edilen parametre çakışması (`hours` ↔ `sessionCfg`) regression kontrolünde tekrar görülmedi.

### 5.3 Dashboard.jsx Taraması

`STATS_BASELINE` kullanıcısı olup olmadığı grep ile doğrulandı: Dashboard.jsx bu sabiti kullanmıyor, kendi cycle'ında `/performance/summary` endpoint'inden alınan `stats_summary` bloğunu gösteriyor. Backend zinciri zaten helper üzerinden okuduğu için Dashboard otomatik olarak tek kaynaktan beslenmiş oluyor. Ekstra frontend dokunuşu gerekmedi.

## 6. Değişen Dosyalar (Commit Listesi)

1. `config/default.json`
2. `api/constants.py`
3. `api/schemas.py`
4. `api/routes/settings.py`
5. `api/routes/performance.py`
6. `api/routes/trades.py`
7. `desktop/src/services/api.js`
8. `desktop/src/components/Performance.jsx`
9. `desktop/src/components/TradeHistory.jsx`
10. `tests/critical_flows/test_static_contracts.py`
11. `docs/USTAT_GELISIM_TARIHCESI.md`
12. `docs/2026-04-11_session_raporu_A7_baseline_tekillestirme.md`

## 7. Versiyon Durumu

`git diff --stat` ile hesaplanan etki, toplam kod satırlarına oranla %10'un altında kaldığı için versiyon v6.0.0'da sabit. Changelog #173 girişi v6.0.0 "ÜSTAT Plus V6.0" bloğu içine eklendi.

## 8. Sonraki Adım (Sıradaki Audit Maddesi)

A7 kapandıktan sonra öncelik sırası:

- **A6** — Performance equity trendi `account_info.equity` yerine `deposits` bazlı hesaplanmalı (audit'te orta öncelik).
- **B17** — TRADE_ERROR kategori eşlemesi Monitor modül hata sayacı ile tam hizalanmalı (B25'in devamı).
- **B8** — Dashboard açık pozisyon satırları 45 satır hardcoded, backend max 31 dönüyor. Layout düzeltmesi.
- **B11** — Monitor MT5 ping/round-trip hardcoded 45ms eşik config'e taşınmalı.

Bu maddelerin her biri ayrı commit olarak, aynı İŞLEMİ BİTİR disiplini ile kapatılacak.
