# Oturum Raporu — A2: Trade Veri Güvenilirliği (SIGN_MISMATCH Filtresi)

**Tarih:** 2026-04-11 Cumartesi (Barış Zamanı — piyasa kapalı)
**Commit:** `6a56648`
**Sınıf:** C1 (Yeşil Bölge — `api/routes/trades.py`, `api/schemas.py`)
**Bölge:** Yeşil Bölge (Red Zone dokunusu YOK)
**Kaynak bulgu:** `docs/2026-04-11_widget_denetimi.md` Bölüm 16.2 B2
**Aksiyon:** Widget Denetimi Aksiyon A2

---

## 1. Özet

Performans sayfasında "En Kârlı İşlem" kartında `F_TOASO BUY 8 lot entry=259.87 exit=257.80 pnl=+2705` görünüyordu — BUY için exit<entry zarar olması gerekirken pnl pozitif. Kök neden MT5 netting sync'te parçalı pozisyonların weighted-average ile özetlenmesi; matematik tutarsızlığı rapor katmanına yansıyordu. Fix: `best_trade`/`worst_trade` seçiminde işaret çelişkili (`SIGN_MISMATCH`) trade'leri hariç tut, ham pnl değerlerine dokunma, kullanıcıya anomaly sayısını bildir.

## 2. Kök Neden Analizi (Kanıt)

### 2.1 Canlı veri incelemesi
`trades` tablosunda `mt5_sync` kaynaklı son 30 trade sorgulandı. İşaret tutarlılığı için hesaplandı:
`calc_buy = (exit - entry) × lot × 100`, `calc_sell = -(exit - entry) × lot × 100`

| id | Sembol | Dir | Entry | Exit | Lot | pnl | Durum |
|----|--------|-----|-------|------|-----|-----|-------|
| 233 | F_TOASO | BUY | 259.87 | 257.80 | 8 | **+2705** | SIGN_MISMATCH (BUY+exit<entry+pnl>0) |
| 214 | F_TKFEN | SELL | 104.26 | 104.40 | 5 | **+485** | SIGN_MISMATCH (SELL+exit>entry+pnl>0) |
| 245 | F_KONTR | SELL | 8.90 | 8.91 | 150 | -7925 | İşaret tutarlı (magnitude farkı ayrı konu) |
| 239 | F_YKBNK | SELL | 38.27 | 38.51 | 102 | -145.98 | İşaret tutarlı |
| 222 | F_HALKB | BUY | 37.58 | 37.66 | 2 | +6 | İşaret tutarlı |

**Not:** SIGN_MISMATCH yalnız 2/30 trade'de. Multiplier/magnitude uyumsuzluğu (F_KONTR, F_YKBNK) ayrı bir kategori — işaret doğru olduğu için bu fix kapsamına alınmadı.

### 2.2 Kod akışı
`engine/mt5_bridge.py::get_history_for_sync` (satır 2030-2135):
```python
# Direction: ilk IN deal'in tipi
direction = "BUY" if entries[0].type == 0 else "SELL"
# Entry: TÜM IN deal'lerin ağırlıklı ortalaması
entry_price = sum(d.price*d.volume for d in entries) / total_entry_vol
# Exit: TÜM OUT deal'lerin ağırlıklı ortalaması
exit_price  = sum(d.price*d.volume for d in exits) / total_exit_vol
# pnl: TÜM deal'lerin MT5 raw profit toplamı (ground truth)
total_pnl = sum(d.profit for d in group)
```

Netting mod'da aynı `position_id` altında scale-in/out veya kısa ters dönüşler tek pozisyon olarak toplanıyor. Ağırlıklı ortalamalar matematiğe sadık ama pnl hesaplaması leg-bazlı olduğu için `(avg_exit - avg_entry) × lot × multiplier ≠ sum(deal.profit)` olabiliyor.

### 2.3 UI etkisi
`api/routes/trades.py::get_trade_stats` (satır 144-145):
```python
best_trade = max(items, key=lambda t: t.pnl or 0.0) if items else None
worst_trade = min(items, key=lambda t: t.pnl or 0.0) if items else None
```
`pnl` tabanlı seçim MT5 doğru olduğu için "en büyük kar" olan trade'i bulur, ama parçalı pozisyon ise kullanıcıya entry/exit ile uyumsuz görünür → veri güvenilirliği algısı bozulur.

## 3. Atomik Değişiklik

### 3.1 `api/schemas.py`
```python
class TradeItem(BaseModel):
    ...
    data_warning: str | None = None  # "SIGN_MISMATCH" or None

class TradeStatsResponse(BaseModel):
    ...
    anomaly_count: int = 0
```

### 3.2 `api/routes/trades.py`
Yeni helper:
```python
def _check_trade_consistency(direction, entry, exit, pnl) -> str | None:
    if pnl is None or entry is None or exit is None: return None
    if direction not in ("BUY", "SELL"): return None
    if pnl == 0: return None
    price_diff = exit - entry
    if price_diff == 0: return None
    expected_sign = 1 if direction == "BUY" else -1
    if (pnl > 0) != ((expected_sign * price_diff) > 0):
        return "SIGN_MISMATCH"
    return None
```

`_to_trade_item` bu kontrolü her trade için çağırıp `data_warning` doldurur.

`get_trade_stats`:
```python
clean_items = [t for t in items if t.data_warning is None]
anomaly_count = sum(1 for t in items if t.data_warning is not None)
best_trade = max(clean_items, key=lambda t: t.pnl or 0.0) if clean_items else None
worst_trade = min(clean_items, key=lambda t: t.pnl or 0.0) if clean_items else None
```

**Değişmeyen metrikler (kritik koruma):**
- `total_pnl` — ham pnl toplamı (MT5 ground truth)
- `win_rate` — ham pnl işaretlerine göre
- `avg_pnl` — ham toplam / sayı
- `winning_trades` / `losing_trades`
- `by_strategy` / `by_symbol` — ham pnl toplamları

Yalnız `best_trade`, `worst_trade`, `anomaly_count` anomaly filtresinden etkilenir.

### 3.3 Etki sınırlaması
| Alan | Durum |
|------|-------|
| Dosya sayısı | 3 (`api/schemas.py`, `api/routes/trades.py`, `tests/critical_flows/test_static_contracts.py`) |
| Net satır | +148 / -7 |
| Kırmızı Bölge dokunusu | Yok |
| Sarı Bölge dokunusu | Yok |
| Siyah Kapı dokunusu | Yok |
| Frontend zorunluluğu | Yok (field'lar opsiyonel) |
| DB schema değişikliği | Yok |
| Re-sync gerekliliği | Yok |

## 4. Statik Sözleşme Testi

**Yeni test:** `tests/critical_flows/test_static_contracts.py::test_trade_stats_excludes_sign_mismatch_from_best_worst`

Kapsam:
1. `_check_trade_consistency` yardımcı fonksiyon varlığı
2. `TradeItem.data_warning` Pydantic model_fields varlığı
3. `TradeStatsResponse.anomaly_count` Pydantic model_fields varlığı
4. `get_trade_stats` source'unda `data_warning` filtresi ve `clean_items` (veya `data_warning is None`) kullanımı
5. Helper'ın 5 kanonik durumda doğru sonuç üretmesi:
   - BUY + exit<entry + pnl>0 → SIGN_MISMATCH
   - SELL + exit>entry + pnl>0 → SIGN_MISMATCH
   - BUY + exit>entry + pnl>0 → None
   - SELL + exit<entry + pnl>0 → None
   - pnl=None → None

Pre-commit hook bu testi çalıştırır; gelecekte filtre silinirse commit bloklanır.

## 5. Mimari Karar: Neden `engine/mt5_bridge.py` DOKUNULMADI?

`get_history_for_sync` fonksiyonu `engine/mt5_bridge.py` (Kırmızı Bölge #3) içinde. Sync mantığını değiştirmek:
1. **DB migration:** Her trade için `deal_count` veya `is_scaled` kolonu → schema update
2. **Re-sync:** Mevcut 254 trade'in ham MT5 deal'leri yeniden toplanması gerekir
3. **Savaş Zamanı riski:** MT5 bridge değişikliği canlı sistemde restart gerektirir ve emir gönderim path'ini (Siyah Kapı #17 `send_order`) etkileyebilir
4. **Alt katman belirsizliği:** Netting mod'da "bir pozisyon ne zaman biter?" tanımı belirsiz — reversal yapılan pozisyon 1 trade mi, 2 trade mi?

Bu fix **display katmanında** anomaly'i tanıyor, ham veriyi DB'de koruyor. Gelecekte `mt5_bridge` iyileştirmesi ayrı C3 değişikliği olarak ele alınabilir — o zaman `data_warning` filtresi de devre dışı bırakılabilir.

## 6. Doğrulama

### 6.1 Critical flows
```
tests/critical_flows — 36 passed, 3 warnings in 3.64s
```
35 baseline + 1 yeni. Regresyon yok.

### 6.2 Syntax
`api/schemas.py` ve `api/routes/trades.py` py_compile temiz.

### 6.3 Davranış beklentisi (deploy sonrası)
- `/api/trades/stats` çağrısında `best_trade` artık F_TOASO BUY dışında bir trade döndürmeli (#233 hariç)
- `anomaly_count ≥ 2` (en az F_TOASO #233 ve F_TKFEN #214)
- `total_pnl`, `win_rate`, `avg_pnl` değişmemeli
- Frontend mevcut haliyle çalışır (yeni field'lar ignore edilir), kullanıcı düzelmiş "En Kârlı İşlem"i görür

## 7. Deploy Durumu

- **Commit:** `6a56648` `main` branch'inde
- **Build:** Gerekli değil (backend değişikliği)
- **Restart:** Gerekir (Python modül yeniden yüklenmesi). Piyasa açık; deploy zamanlaması kullanıcı kontrolünde
- **Deploy sonrası etki:** Sadece `/api/trades/stats` yanıtı değişir; işlem akışı, risk kontrolü, emir gönderimi etkilenmez

## 8. Follow-up (Bu fix kapsamında DEĞİL)

- **Frontend rozet:** `TradeItem.data_warning` değerini Performans → En Kârlı İşlem kartında ve İşlem Geçmişi tablosunda rozet olarak göstermek (ayrı patch)
- **Anomaly banner:** `anomaly_count > 0` ise "N işlem veri anomalisi nedeniyle hariç" banner'ı (ayrı patch)
- **MT5 sync robustness:** `get_history_for_sync` netting position detection + multi-leg split (C3 Kırmızı Bölge, büyük iş, ayrı oturum)
- **Magnitude uyumsuzluğu:** F_KONTR/F_YKBNK gibi multiplier farklı kontratlarda `pnl` ≠ `calc × 100` (A2 dışı, muhtemelen contract spec config'i gerektirir)

## 9. Referanslar
- Denetim raporu: `docs/2026-04-11_widget_denetimi.md` (Bölüm 16.2 B2, Bölüm 17 A2)
- Changelog: `docs/USTAT_GELISIM_TARIHCESI.md` entry #166
- İlgili Kırmızı Bölge fonksiyonu (DOKUNULMADI): `engine/mt5_bridge.py::get_history_for_sync` (satır 2030-2135)
- Etkilenen Pydantic schemas: `api/schemas.py::TradeItem`, `api/schemas.py::TradeStatsResponse`
