# Session Raporu — 2026-03-07

## Kapsam
Bu session'da 3 ana iş tamamlandı:

1. **OĞUL 7 İşlem Engeli Düzeltmesi** (engine/baba.py, engine/ogul.py)
2. **USDTRY Dinamik Sembol Çözümleme** (engine/mt5_bridge.py)
3. **OĞUL Aktivite Kartı** (API + Desktop UI)

---

## 1. OĞUL 7 İşlem Engeli Düzeltmesi

OĞUL'un hiç işlem açamamasının 7 kök nedeni tespit edildi ve düzeltildi:

| # | Sorun | Çözüm | Dosya |
|---|-------|-------|-------|
| 1 | Kill-Switch L2 kısır döngü (851 cycle risk_ok=False) | `daily_reset_equity` ile PnL bazı sıfırlanır | baba.py |
| 2 | Lot floor(0) — kümülatif çarpanlar lot'u 0'a düşürüyor | `vol_min` minimum garanti | baba.py + ogul.py |
| 3 | ADX 20-25 ölü bölge — MR ve TF ikisi de bloklanıyor | `MR_ADX_THRESHOLD` 20→25 | ogul.py |
| 4 | `ENTRY_LOT_FRACTION=0.5` lot=1'i 0'a düşürüyor | lot≤2 ise fraction=1.0 | ogul.py |
| 5 | Top5'te sadece 2 kontrat (5 yerine) | Minimum 3 kontrat garantisi | ogul.py |
| 6 | Bias nötr çarpanı ×0.7 çok agresif | ×0.85'e yumuşatma | ogul.py |
| 7 | RANGE rejimi + ADX=30.4 çelişkisi | ADX>25 → TREND override | baba.py |

### Doğrulama
- Her iki dosya `py_compile` geçti
- 22:42'de engine yeniden başlatıldığında loglardan doğrulandı:
  - Fix #1: `"reset equity=12433.57"` ✅
  - Fix #5: `"Top5 minimum garanti: 3 kontrat"` ✅
  - Fix #7: `"RANGE→TREND (avg_adx=30.4>25.0)"` ✅

---

## 2. USDTRY Dinamik Sembol Çözümleme

| Alan | Detay |
|------|-------|
| **Sorun** | Her cycle `"Tick alınamadı [USDTRY]: (-4, Not found)"` hatası |
| **Kök neden** | GCM'de sembol adı `USDTRY_YAKINVADE`, kodda hardcoded `"USDTRY"` |
| **Çözüm** | `_resolve_symbols()` içinde `"USDTRY" in s.name.upper()` ile dinamik arama |
| **Dosya** | `engine/mt5_bridge.py` |
| **Etki** | BABA'nın USD/TRY şok kontrolü çalışır hale gelecek |

---

## 3. OĞUL Aktivite Kartı

Otomatik İşlem Paneline yeni kart eklendi:

| Bileşen | Dosya | İçerik |
|---------|-------|--------|
| API Endpoint | `api/routes/ogul_activity.py` (YENİ) | `GET /api/ogul/activity` |
| Schema | `api/schemas.py` | `OgulActivityResponse`, `OgulSignalItem`, `OgulUnopenedItem` |
| Router | `api/server.py` | `ogul_activity` router kaydı |
| UI Kart | `desktop/src/components/AutoTrading.jsx` | Sayaçlar + oylama tablosu + açılamayan işlemler |
| API Service | `desktop/src/services/api.js` | `getOgulActivity()` |
| CSS | `desktop/src/styles/theme.css` | `.ogul-*` sınıfları |

### Kart İçeriği
- **Sayaçlar:** Tarama / Sinyal / Reddedilen
- **Strateji Parametreleri:** Son M15, aktif strateji, ADX değeri
- **Oylama Tablosu:** RSI, EMA, ATR, Hacim göstergeleri + oy skoru
- **Açılamayan İşlemler:** Bugünün UNOPENED_TRADE eventleri

---

## Commit
```
7284f4b feat: OĞUL aktivite kartı, 7 işlem engeli düzeltmesi, USDTRY dinamik çözümleme
11 files changed, 1115 insertions(+), 42 deletions(-)
```

## Versiyon
%2.9 değişiklik — versiyon yükseltme gerekmiyor (eşik: %10).

## Bekleyen
- Pazartesi (2026-03-09) seansında OĞUL'un ilk işlemini yapması bekleniyor
- Toplam drawdown %13.39 — equity artışıyla doğal olarak düzelecek
- GCM sunucu build uyarısı (4755 < 5200) — broker tarafı
