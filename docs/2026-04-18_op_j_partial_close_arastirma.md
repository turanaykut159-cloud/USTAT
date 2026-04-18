# OP-J Ön Araştırma: Manuel Partial Close Handling (Trade #279)

**Tarih:** 18 Nisan 2026 Cmt gece
**Durum:** Research-only, fix hafta içi
**Sınıf tahmini:** C3 (Kırmızı Bölge: manuel_motor.py + ogul.py mt5_sync akışı)
**Aciliyet:** Orta — orphan pozisyon tekil olay, ama pattern tekrarlarsa sistemik hale gelir

---

## 1. Olay Zinciri (Forensic)

| Zaman | Olay | Kaynak |
|---|---|---|
| 17 Nis 14:17:46 TRT | Üstat manuel MT5'te 316 lot F_KONTR SELL açtı | DB trade #279 entry_time |
| 17 Nis 14:17-21:35 | 7 saat pozisyon açık, fiyat 12.7063 → 13.14 | price_open vs exit_price |
| 17 Nis 21:35:00 | Üstat manuel olarak 158 lot close etti (yarısı) | Risk snapshot positions_json volume: 158 |
| 17 Nis ~21:35+ | Engine `mt5_sync` cycle'ında lot düşüşünü algıladı | DB trade #279 exit_reason="mt5_sync \| APPROVED" |
| 17 Nis ~21:35+ | Engine **yanlış yorum**: "pozisyon tamamen kapandı" → DB 316 lot -13706 full-close kaydı | trade #279 lot=316, pnl=-13706 |
| 18 Nis 15:55:59 | Engine restart: DB'de açık kayıt bulamadı, MT5'te 158 lot gördü → orphan | ustat_2026-04-18.log:15776 |
| 18 Nis 16:00+ | Engine orphan'ı `active_trades`'e "duplicate engeli" ile ekledi, operator uyarısı | ogul.py:restore_active_trades:3470 |

## 2. Kanıt Matrisi

```
Trade #279 alanlar (DB):
  id: 279
  strategy: manual
  symbol: F_KONTR
  direction: SELL
  entry_time: 2026-04-17T14:17:46
  exit_time: 2026-04-17T21:35:00
  entry_price: 12.7063
  exit_price: 13.14
  lot: 316.0            ← orijinal TAM lot (DB'ye bu yazıldı)
  initial_volume: None  ← BU ALAN BOŞ (bug: partial close için gerekli)
  pnl: -13706.0         ← 316 lot * (13.14-12.7063) * 10 ≈ -13,706
  exit_reason: mt5_sync | APPROVED by TURAN AYKUT
  mt5_position_id: 8050624913

Risk snapshot 15:56:31 positions_json:
  {ticket: 8050624913, symbol: F_KONTR, type: SELL,
   volume: 158.0,  ← MT5'te hâlâ açık lot
   price_open: 13.14,  ← Engine'in 17 Nis partial close'tan sonra yeni entry saydığı
   sl: 0.0, tp: 0.0,  ← KORUMASIZ
   profit: 0.0, time: '2026-04-17T11:17:46' ← orijinal açılış}

MT5_journal:
  0 referans (ticket 8050624913 hiç yok) — engine terminal log'u ile tetiklenmedi
Events (type=TRADE):
  18 Nis 15:56:01 "TRADE_OPENED: F_KONTR SELL" ← engine restart'ta orphan'ı "açılış" olarak algıladı
  18 Nis 15:56:01 "ERROR_ATTRIBUTION: trade#279 OGUL: Zararli islem (mt5_sync)"
  18 Nis 15:56:16/17 "İşlem #278/#279 onaylandı: TURAN AYKUT"
```

## 3. Teşhis (Kök Neden)

**"Partial close DB desync bug" değil.** Gerçek bug: Engine `mt5_sync` akışı **manuel partial close'u full-close olarak yorumluyor**.

Mekanizma:
1. Manuel trade açılır (lot=X) → DB'ye açık kayıt yazılır VEYA hiç yazılmaz (bu olayda yazılmadı, ilk sync'te yazıldı)
2. Manuel partial close (lot=X → X/2) → Engine lot düşüşünü pozisyon kapanması olarak yorumlar
3. DB'de "full close" kaydı oluşur (pnl orijinal lot üzerinden hesaplanır — ama PnL gerçekte partial close'un realized kısmı)
4. MT5'te kalan lot kayıtsız orphan

**Hangi kod bloğu?** `engine/ogul.py::restore_active_trades` veya `engine/manuel_motor.py::mt5_sync_handler`. Kesin lokasyon hafta içi `grep "mt5_sync" engine/` ile bulunur.

## 4. Önerilen Fix Yönü (Hafta İçi OP-J)

### 4.1 Kısa vade (hafta içi ~3 saat C3)

A. **Volume Delta Handler**: `mt5_sync` pozisyon senkronize ederken:
   ```python
   if existing_db_trade and existing_db_trade.exit_time is None:
       # Açık kayıt var; volume delta hesapla
       delta = existing_db_trade.lot - current_mt5_volume
       if delta > 0 and current_mt5_volume > 0:
           # PARTIAL CLOSE tespit edildi
           # Yeni bir partial close kaydı oluştur: lot=delta, pnl=realized
           # existing_db_trade.lot -= delta (kalan açık)
           # initial_volume: eski lot'u sakla (bu da ayrı fix)
   ```

B. **`initial_volume` backfill**: Trade açılışında her zaman `initial_volume = lot` set edilsin. Bu alan şu an manuel trade'lerde None — fix ile manuel_motor.py'da da doldurulmalı.

C. **Orphan auto-close policy**: Engine boot'ta DB'de eşleşmeyen pozisyon tespit edilirse (158 lot F_KONTR gibi) ya:
   - Otomatik yeni bir açık kayıt oluştur (temiz sayfa),
   - Ya da kullanıcı onayı iste (mevcut davranış: sadece log + duplicate engeli).

### 4.2 Uzun vade (hafta sonu)

- Event sourcing: Her lot değişimi ayrı event (OPEN, PARTIAL_CLOSE, FULL_CLOSE, INCREASE). Mevcut model "open + exit" ikili olduğu için partial'a uygun değil.
- MT5 deal history entegrasyonu: `mt5.history_deals_get()` ile deal bazında sync — volume delta'nın gerçek nedenini (close mu, ekleme mi) broker'dan öğrenebilmek.

## 5. Test Stratejisi

Yeni `tests/critical_flows/test_manuel_partial_close.py`:
- Test 1: Manuel 200 lot aç → partial 100 close → DB'de 2 kayıt (close=100, open=100), initial_volume=200 her ikisinde
- Test 2: Manuel 100 lot aç → full close → 1 kayıt, exit_time set
- Test 3: Manuel 100 lot aç → engine restart → DB kayıt korunur, orphan yok
- Test 4: Manuel 100 lot aç → +50 artır (increase) → DB 150 lot aynı kayıt veya yeni kayıt (policy kararı)

## 6. Risk Matrisi

| Fonksiyon | Bölge | Class | Risk |
|---|---|---|---|
| `ogul.py::restore_active_trades` | Kırmızı | C3 (Siyah Kapı #14 `_verify_eod_closure` ile bağlantılı) | Yüksek |
| `ogul.py::_manage_active_trades` | Kırmızı | C3 (Siyah Kapı #15) | Yüksek |
| `manuel_motor.py::mt5_sync` (varsa) | Sarı | C2-C3 | Orta |
| `database.py::insert_trade` | Kırmızı | C3 (schema change: initial_volume NOT NULL default?) | Orta |

## 7. Aciliyet Değerlendirmesi

- **Şu an riski düşük:** Tekil olay, 158 lot F_KONTR Üstat'ın manuel kontrolünde. Pzt 09:00 öncesi el ile kapatılacak.
- **Pattern riski:** Her manuel partial close aynı pattern'i tetikleyecek. Üstat manuel trading yaptığında her defasında potansiyel orphan.
- **Karar:** OP-J hafta içi (20-24 Nis), OP-D/F/G'den sonra.

## 8. Açık Sorular (Pzt sonrası araştırılacak)

1. `mt5_sync` handler'ı hangi dosyada? (`grep -rn "mt5_sync" engine/`)
2. `initial_volume` alanı hangi commit'te eklendi? Migrator var mı? Eski trade'ler backfill edildi mi?
3. MT5 `history_deals_get()` ÜSTAT'ta kullanılıyor mu? (evet ise çözüm daha kolay)
4. Önceki "mt5_sync" exit_reason'lı trade'ler (kaç tane, ne kadar PnL?) — P-1 bulgusu "mt5_sync %86 zararın nedeni, 190 trade, -167,972 TL" — bu partial close pattern'ın sistemik olduğunu gösterebilir.

---

**Not:** Bu dosya OP-J için pre-reading. Fix yapılmadı. Pazar OP-D bitince veya hafta içi OP-J slot'unda kullanılacak.
