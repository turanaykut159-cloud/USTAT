# TEST_003 — Sinyal Üretimi ve İlk İşlem

| Alan | Değer |
|------|-------|
| **Tarih** | 2026-03-21 ~20:30 |
| **Modül** | `engine/simulation.py` |
| **Cycle** | 200 |
| **Hız** | 0 (hızlı mod) |
| **Amaç** | Yeniden yazılan PriceGenerator ile sinyal üretimi, emir açılması ve TP kapanışının doğrulanması |

## Ne İçin Yapıldı

TEST_002'de PriceGenerator'ın her çağrıda yeni rastgele yürüyüş oluşturması VOLATILE rejim tespitine yol açıyordu. PriceGenerator tamamen yeniden yazıldı (persistent history). Bu testin amacı:

1. Rejim tespitinin stabil çalışması (RANGE/TREND, VOLATILE değil)
2. OĞUL'un sinyal üretmesi
3. MockMT5Bridge'in emir açması
4. SL/TP execution mekanizmasının çalışması

## Düzeltmeler (TEST_002 → TEST_003)

### PriceGenerator Yeniden Yazımı
- Persistent bar history: her (symbol, timeframe) için 600 başlangıç bar
- `advance_cycle()`: her çağrıda 1 yeni bar ekler (yeni rastgele yürüyüş değil)
- Düşük volatilite: TREND=0.003, RANGE=0.002, OLAY=0.006
- TF çarpanları: M1=0.4, M5=1.0, M15=1.7, H1=3.5
- Max 800 bar (700'e trim)

### MockMT5Bridge.send_order İmza Düzeltmesi
- Eski: `(symbol, order_type, volume, ...)`
- Yeni: `(symbol, direction, lot, price, sl, tp, order_type="market")`
- Gerçek MT5Bridge imzasıyla birebir uyumlu

### SL/TP Execution Eklendi
- `update_floating_pnl()` içinde her tick'te SL/TP kontrolü
- BUY: bid ≤ SL → stop-loss, bid ≥ TP → take-profit
- SELL: ask ≥ SL → stop-loss, ask ≤ TP → take-profit
- `_sl_close_count`, `_tp_close_count`, `_total_realized_pnl` sayaçları

### Datetime Monkey-Patching
- `_SimDatetime.now()` → her zaman 11:00 döndürür
- OĞUL, H-Engine, BABA, DataPipeline modüllerine uygulandı
- `is_market_open` her zaman True
- Seans filtresi %50 cezası kaldırıldı

## Sonuç

| Metrik | Değer |
|--------|-------|
| Başarılı cycle | 200/200 ✅ |
| Sinyal üretimi | 2 |
| Emir açılan | 1 (F_ASELS SELL) |
| TP kapanış | 1 ✅ (+267.05 TL) |
| SL kapanış | 0 |
| Rejim geçişleri | 3 (RANGE → TREND → OLAY) |
| Son bakiye | 10,267.05 TL (+2.67%) |
| Durum | ✅ BAŞARILI — SL/TP mekanizması çalışıyor, TP tetiklendi |
| ÜSTAT beyin | Hata:0, Ertesi gün:0, Regülasyon:0 (henüz inaktif) |
| Sonraki adım | ÜSTAT beyin modüllerinin aktivasyonu (TEST_004) |
