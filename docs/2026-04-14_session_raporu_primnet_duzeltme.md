# 2026-04-14 — PRİMNET Düzeltme Oturumu

**Versiyon:** 6.0.0 (bump yok — diff oranı %9.7, eşik %10)
**Commit'ler:** d1ed241, b660f84, 5e32cbd
**Zone/Class:** Sarı (h_engine) + Yeşil (PrimnetDetail/schemas/hybrid_trade) — C2
**Test:** 71/71 critical_flows PASS (her commit sonrası), Vite build 3.22s (730 modül)

## Özet

Üç bağımsız PRİMNET/H-Engine sorunu atomik commit disiplini ile çözüldü:

1. **UI motor uyumsuzluğu** (T1–T10 bulguları) — PrimnetDetail modalı motor `_calc_primnet_trailing_sl` mantığından sapmıştı. Grid snap, yön-bilinçli açıklama, monotonic kilitli kâr, TRAILING STOP etiketi eklendi.
2. **T12 SL-gap** — `_trailing_via_stop_limit` GCM VİOP pending-modify reddi (retcode 10006) nedeniyle 3× retry + fallback cancel+place pattern'i ile yaklaşık 10 saniye SL'siz pozisyon bırakıyordu. Place-first-then-cancel pattern'ine çevrildi.
3. **Orphan log spam** — `_find_orders_by_comment` tanı logu her döngüde aynı (symbol, prefix) için basılıyordu. (symbol, prefix) anahtarlı 60s throttle eklendi.

## 1) PRİMNET UI (d1ed241)

**Sorun kanıtı:** `docs/2026-04-14_primnet_canli_gozlem_notlari.md` — motor grid = 0.5 prim, UI grid = dinamik interpolasyon. Motor floor/ceil yön-bilinçli, UI düz hesap. Row `stopPrim` motor snap'lenmiş değeri yansıtmıyordu.

**Değişenler:**
- `api/schemas.py` — `PrimnetConfig.step_prim: float = 0.5`
- `api/routes/hybrid_trade.py` — payload'da `step_prim=h_engine.primnet_step`
- `engine/h_engine.py` — `primnet_step` property
- `desktop/src/components/PrimnetDetail.jsx` — 6 sıralı edit (504 satır toplam):
  - `fmtPrim` 1 → 2 ondalık
  - `snapStopPrim(rawStopPrim, entryPrim, step, direction)` helper (motor JS portu: BUY floor, SELL ceil)
  - `buildLadder` — gridStep = `cfg.step_prim`, entryRounded 2-decimal
  - `buildExplanation` — cmpProfit/cmpLoss yön-bilinçli
  - Row computation — `stopPrimSnapped` alanı, T8 monotonic via `slPrim`, T4 boş `stopLevel`
  - Rules row — "Adım: {cfg.step_prim} prim (grid)"
  - Footer — "SL" → "TRAILING STOP" (aktif/beklemede alt etiketi)

## 2) T12 SL-Gap (b660f84)

**Kök neden:** GCM VİOP `mt5.order_send(TRADE_ACTION_MODIFY)` pending-stop için kalıcı retcode 10006 dönüyor. Eski akış: 3× retry (~8s) → başarısız → cancel + place (~2s). Toplam ~10s SL'siz.

**Yeni akış (place-first-then-cancel):**

```
1. Yeni stop emri önce konur (send_stop_limit)
2. Başarılıysa:
   - hp.trailing_order_ticket = new_ticket
   - eski ticket varsa cancel_pending_order(old_ticket)
   - İki stop ~300ms eşzamanlı (fail-safe)
3. Başarısızsa:
   - Eski stop yerinde kalır
   - Pozisyon asla SL'siz kalmaz
```

**Eksiltme:** 59 ekleme / 72 silme — retry loop ve modify branch kaldırıldı.

## 3) Orphan Log Throttle (5e32cbd)

`_find_orders_by_comment` içindeki "orphan comment tanı" debug logu aynı (symbol, prefix) için her 10s döngüde basılıyordu. `_orphan_log_throttle` dict'i ile (symbol, prefix) anahtarlı 60s throttle. Log hacmi ~6x → 1x azaldı, davranış değişmedi.

## Doğrulama

- `python -m pytest tests/critical_flows -q` → 71 passed (her commit sonrası)
- `npm run build` → 730 modül / 3.22s / 0 hata
- Agent bridge: `build`, `restart_app` (opsiyonel — kullanıcı teyidi bekleniyor)

## Versiyon Değerlendirmesi

- Son bump: `32ebeda` → 6.0.0
- 32ebeda..HEAD: 104 dosya, 16883+/986- = 17869 satır
- Toplam kod: 183745 satır
- Oran: **%9.7** — %10 eşiğinin altında, bump yok.

## Takip Eden İşler

- Canlı piyasa seansında T12 davranışının tekrar gözlem notuyla teyidi
- UI'da PRİMNET modal açılışında step_prim alanının payload'dan düzgün geldiğinin göz testi
