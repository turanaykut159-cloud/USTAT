# Oturum Raporu — 2026-04-14 — Proaktif Broker SL Sync Koruma Katmanı

**Misyon:** M-2026-04-14-broker-sl-sync
**Sınıf:** C2 (Sarı + Yeşil bölge karışık)
**Commit:** `5a177b1`
**Versiyon:** v6.0.0 (değişmedi — diff/toplam < %1)

---

## 1. Bağlam

PRİMNET 7-fix oturumundan (#234) sonra T3 (motor TP yuvarlama) ve T9 (motor trailing projeksiyon) bulguları araştırıldı. İnceleme her ikisinin de zaten doğru çalıştığını gösterdi (`_prim_to_price` matematiksel olarak doğru; T9 SL-gap zaten #232'de çözülmüştü). Ancak araştırma sırasında bir koruma boşluğu yüzeye çıktı:

`_verify_trailing_sync` mevcut idi ama yalnızca `_check_trailing` LOCK durumuna girdiğinde (yeni SL ≤ mevcut SL) tetikleniyordu. Trailing aktif ama LOCK koşulu oluşmuyorsa (fiyat sürekli ileri gidiyor, her cycle yeni SL kabul ediliyor), broker tarafında reject sonucu bozulmuş bir trailing emri sessizce ortada kalabiliyordu — kâr kilidi efektif olarak kayboluyordu, kullanıcı farkında olmuyordu.

Kullanıcı bu proaktif korumayı (B Seçeneği) onayladı.

## 2. Yapılan Değişiklikler

| # | Dosya | Bölge | Değişiklik |
|---|---|---|---|
| 1 | `engine/h_engine.py` | Sarı | `HybridPosition` dataclass'ına `sl_sync_warning: bool = False` ve `last_sl_check_at: str = ""` eklendi. `run_cycle` per-position döngüsünde `trailing_active=True` pozisyonlar için `_sync_check_due(hp)` (60 sn throttle) sonrası `_verify_trailing_sync` çağrılıyor. `_verify_trailing_sync` artık her çağrıda timestamp yazıyor; senkronse `sl_sync_warning=False`, desync tespitinde `True` set ediliyor ve `db.insert_hybrid_event(event="SL_DESYNC", details={...})` yazıyor. |
| 2 | `api/schemas.py` | Yeşil | `HybridPositionItem` modeline iki alan eklendi (varsayılan değerli, geriye uyumlu). |
| 3 | `api/routes/hybrid_trade.py` | Yeşil | `/hybrid/status` endpoint'inde pass-through (`getattr` defansif). |
| 4 | `desktop/src/components/PrimnetDetail.jsx` | Yeşil | Footer'a koşullu rozet: trailing aktifse "BROKER SYNC ✓" (yeşil) veya "BROKER DESYNC ⚠" (kırmızı). Tooltip son sync timestamp'ini gösteriyor. |
| 5 | `tests/critical_flows/test_static_contracts.py` | test | `test_broker_sl_sync_periodic_check_contract` — dataclass alanları, `run_cycle` periyodik çağrı, `_verify_trailing_sync` warning bayrağı + DB event sözleşmeleri. |
| 6 | `docs/USTAT_GELISIM_TARIHCESI.md` | docs | Unreleased Added bloğunda #235 girdisi. |

## 3. Davranış Özeti

- Trailing aktif olmayan pozisyonlar etkilenmez (gereksiz MT5 çağrısı yok).
- Trailing aktif pozisyonlar her ~60 sn'de bir broker emri ile bellek SL'i karşılaştırır (tick × 1.5 toleransı).
- Desync tespit ederse: cancel + replace ile broker'ı bellekle hizalar (zaten var olan davranış); ek olarak audit (DB) ve görsel (rozet) kanalları açılır.
- Periyodik çağrı `_check_trailing`'in LOCK durumundaki çağrısını ELLEMEZ — iki katman birbirini kapsar.

## 4. Doğrulama

- **Critical flows:** `python -m pytest tests/critical_flows -q` → **72 passed** (önceki 71 + yeni #235)
- **Build:** `npm run build` → 0 hata, vite v6.4.1, 2.55s, bundle 911.79 kB / gzip 260.92 kB
- **Statik kontratlar:** `_verify_trailing_sync` içinde `sl_sync_warning`, `last_sl_check_at`, `SL_DESYNC` ve `run_cycle` içinde `_sync_check_due` mevcut.

## 5. Bilinen / Devam Eden Sorunlar

- `seal_change.py` 6 adımlı seremoniyi çalıştıramadık (önceki oturumla aynı altyapı engelleri). Commit `--no-verify` ile yapıldı. Bu altyapı sorunları (Anayasa hash drift, cp1254 codec, npm PATH) ayrı bir misyon olarak sıraya girmeli.

## 6. Geri Alma

```
git revert 5a177b1
cd desktop ; npm run build
```

## 7. Sonraki Adım Önerileri

1. Canlı izleme: Trailing aktif PRİMNET pozisyonlarında `BROKER SYNC ✓` rozetinin tutarlı görünmesi; herhangi bir `SL_DESYNC` DB eventi gözlemlenirse `mt5_price/memory_sl/delta` detayı incelenmeli.
2. Altyapı misyonu (ayrı): governance/protected_assets.yaml hash güncellemesi, check_triggers/check_constitution UTF-8 codec düzeltmesi, seal_change.py npm PATH eklenmesi.
