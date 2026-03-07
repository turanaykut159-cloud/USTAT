# Hibrit Panel 10035 Hatası — Kök Neden Analizi

## Özet

**Sorun:** Hibrit devir sırasında "MT5 SL/TP ataması başarısız — retcode=10035 Invalid order" hatası.

**Sonuç:** MT5/broker tarafı sorunu. `TRADE_ACTION_SLTP` GCM VİOP build 4755'te çalışmıyor.

**Çözüm:** Yazılımsal SL/TP modu eklendi (2026-03-05).

---

## Kök Neden (2026-03-05 kesin teşhis)

### Nihai Teşhis

`TRADE_ACTION_SLTP` GCM VİOP sunucusunda (GCM-Real01, build 4755 < gerekli 5200) **hiçbir koşulda çalışmıyor**. Denenen tüm request yapıları (position var/yok, type_filling var/yok, type_time var/yok) aynı sonucu veriyor: **retcode=10035 Invalid order**.

`TRADE_ACTION_DEAL` (alım/satım emirleri) ise sorunsuz çalışıyor.

### Deneme Geçmişi

| # | Denenen | Sonuç |
|---|---------|-------|
| 1 | `position` alanı her zaman gönder | 10035 devam |
| 2 | `order_check` kaldır, retry ekle | 10035 devam |
| 3 | `type_filling=RETURN`, `type_time=GTC` ekle | 10035 devam |
| 4 | Farklı request yapıları | Hepsi 10035 |

**Kanıt:** Tüm log geçmişinde `TRADE_ACTION_SLTP` ile tek bir başarılı işlem yok. `TRADE_ACTION_DEAL` ile onlarca başarılı işlem var.

---

## Uygulanan Çözüm: Yazılımsal SL/TP (2026-03-05)

### Mimari

```
native_sltp=false (varsayılan):
  transfer_to_hybrid → MT5 SLTP çağrısı ATLANIR
                      → SL/TP yalnızca bellek + DB'de tutulur

  run_cycle (10sn) → _check_software_sltp()
                    → Fiyat SL'yi aştı mı? → close_position (DEAL)
                    → Fiyat TP'yi aştı mı? → close_position (DEAL)

  breakeven/trailing → Sadece internal SL günceller (bellek + DB)
                     → MT5'e modify_position ÇAĞRILMAZ

native_sltp=true (MT5 güncellenince):
  Eski davranış: modify_position ile MT5'e SL/TP yazar
```

### Değiştirilen Dosyalar

| Dosya | Değişiklik |
|-------|------------|
| `config/default.json` | `hybrid.native_sltp: false` eklendi |
| `engine/h_engine.py` | `_check_software_sltp()` metodu eklendi |
| `engine/h_engine.py` | `transfer_to_hybrid` — native kapalıyken MT5 modify atlanır |
| `engine/h_engine.py` | `run_cycle` — software SL/TP kontrolü eklendi |
| `engine/h_engine.py` | `_check_breakeven` — native kapalıyken sadece internal günceller |
| `engine/h_engine.py` | `_check_trailing` — native kapalıyken sadece internal günceller |
| `api/schemas.py` | `HybridStatusResponse.native_sltp` alanı eklendi |
| `api/routes/hybrid_trade.py` | `native_sltp` bilgisi response'a eklendi |
| `desktop/src/components/HybridTrade.jsx` | SL/TP modu badge'i eklendi |
| `desktop/src/styles/theme.css` | Badge ve event stilleri eklendi |

### `_check_software_sltp` Mantığı

```python
BUY pozisyon:
  SL tetikleme: current_price <= current_sl
  TP tetikleme: current_price >= current_tp

SELL pozisyon:
  SL tetikleme: current_price >= current_sl
  TP tetikleme: current_price <= current_tp

Tetiklenirse → close_position(ticket) [TRADE_ACTION_DEAL]
             → _finalize_close(hp, "SOFTWARE_SL"/"SOFTWARE_TP", pnl, swap)
```

### Önceki Düzeltmeler (hâlâ aktif)

- `modify_position`: `position` alanı her zaman gönderiliyor
- `modify_position`: `order_check` kaldırıldı, 3 retry + 0.5s bekleme
- `send_order` Phase 2: retry arası 0.5s bekleme

---

## Kalan Aksiyon

| Aksiyon | Kim | Öncelik |
|---------|-----|---------|
| MT5'i build **5200+** yap | Kullanıcı (GCM/MetaQuotes) | Yüksek |
| Build güncellenince `native_sltp: true` yap | Geliştirici | Orta |

### Geçiş Planı

MT5 build 5200+ kurulduğunda:
1. `config/default.json` → `"native_sltp": true`
2. Engine restart
3. Log'da "SL/TP modu=NATIVE (MT5)" görülmeli
4. Hibrit devir sırasında `modify_position` başarılı olmalı (retcode=10009)

### Dikkat

Yazılımsal SL/TP **10 saniye aralıklı** fiyat kontrolü yapar. Bu sürede fiyat SL/TP seviyesini aşıp geri dönebilir (slippage riski). Native SLTP'de bu risk yoktur çünkü SL/TP sunucu tarafında anlık tetiklenir.
