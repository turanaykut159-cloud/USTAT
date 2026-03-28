# H-Engine Eski Trailing Modları — Arşiv

**Tarih:** 2026-03-28
**Neden:** PRİMNET tek pozisyon yönetim sistemi olarak belirlendi.
ATR ve Profit trailing modları kaldırıldı.

## Silinen Fonksiyonlar
1. `_calc_atr_trailing_sl()` — ATR bazlı trailing SL hesaplama
2. `_calc_profit_trailing_sl()` — Kâr bazlı trailing SL hesaplama (kademeli oran dahil)
3. `_check_breakeven()` ATR breakeven mantığı (satır 882-972)
4. `_check_trailing()` içindeki ATR/profit dallanmaları ve min/max clamp bloğu

## Silinen Config Parametreleri (config/default.json → hybrid)
- `trailing_mode` — "atr" | "profit" | "primnet" seçimi (artık hep primnet)
- `trailing_profit_gap` — Profit mod sabit gap (100 TRY)
- `trailing_graduated` — Kademeli oran bayrağı
- `trailing_graduated_tiers` — 4 kademeli oran listesi
- `trailing_trigger_atr_mult` — ATR trailing tetik çarpanı
- `trailing_distance_atr_mult` — ATR trailing mesafe çarpanı
- `breakeven_atr_mult` — ATR breakeven eşik çarpanı
- `trailing_min_pct` — Min trailing mesafe yüzdesi
- `trailing_max_pct` — Max trailing mesafe yüzdesi

## Geri Alma
```bash
git revert <bu_commit_hash> --no-edit
```
