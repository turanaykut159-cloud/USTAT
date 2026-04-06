# Oturum Raporu — 6 Nisan 2026

## PRİMNET Stop Limit Emir Sistemi (#117)

### Sorun

H-Engine PRİMNET trailing stop mekanizması `TRADE_ACTION_SLTP` (`modify_position`) kullanarak
VİOP netting modunda SL/TP güncellemeye çalışıyordu. GCM MT5 bu işlemi sürekli
**retcode 10035 "Invalid order"** ile reddediyordu. Sonuç: trailing stop hiçbir zaman
güncellenemiyordu, pozisyonlar korumasız kalıyordu.

### Çözüm

Tüm PRİMNET trailing stop ve hedef yönetimi **Buy Stop Limit / Sell Stop Limit** bekleyen
emirlere (`TRADE_ACTION_PENDING`) çevrildi. GCM MT5 VİOP'ta bu emir tipleri destekleniyor
(canlı `order_check` ile doğrulandı, `ORDER_TIME_DAY` + `ORDER_FILLING_RETURN` gerekli).

### Değişiklik Detayları

**engine/mt5_bridge.py** (Kırmızı Bölge — sadece ekleme, mevcut kod değişmedi)

| Fonksiyon | Açıklama |
|-----------|----------|
| `send_stop_limit()` | Buy/Sell Stop Limit emir gönderme (TRADE_ACTION_PENDING) |
| `modify_stop_limit()` | Bekleyen emri güncelleme (TRADE_ACTION_MODIFY, 3 deneme) |
| `cancel_stop_limit()` | Bekleyen emri iptal (TRADE_ACTION_REMOVE) |
| `get_pending_orders()` | BUY_STOP_LIMIT/SELL_STOP_LIMIT tip tanıma + comment + stoplimit fiyatı |

**engine/h_engine.py** (Sarı Bölge)

| Fonksiyon | Değişiklik |
|-----------|------------|
| `HybridPosition` | `trailing_order_ticket`, `target_order_ticket` alanları eklendi |
| `__init__` | `_use_stop_limit`, `_stop_limit_gap_prim` config okuma |
| `_check_trailing()` | Stop Limit dallanması (`_trailing_via_stop_limit` çağrısı) |
| `_trailing_via_stop_limit()` | YENİ: Trailing SL'yi Stop Limit emirle yönet |
| `transfer_to_hybrid()` | Devirde trailing + hedef Stop Limit emir yerleştirme |
| `_check_primnet_target()` | Hedef emri kaybolmuşsa yeniden yerleştirme |
| `_place_target_stop_limit()` | YENİ: Hedef Stop Limit emir yerleştirme yardımcısı |
| `_cancel_stop_limit_orders()` | YENİ: Ortak emir iptal yardımcısı |
| `_restore_stop_limit_tickets()` | YENİ: Restart sonrası comment eşleştirme |
| `force_close_all()` | Kapatmadan önce Stop Limit emirleri iptal |
| `_finalize_close()` | Kapanışta Stop Limit temizliği |
| `_handle_external_close()` | Harici kapanışta Stop Limit temizliği |
| `remove_from_hybrid()` | Hibritten çıkışta Stop Limit temizliği |
| `_primnet_daily_reset()` | Gece geçişinde eski emirleri iptal, yenilerini koy |
| `restore_positions()` | Restart sonrası ticket kurtarma |

**config/default.json** (Kırmızı Bölge)

| Parametre | Değer | Açıklama |
|-----------|-------|----------|
| `use_stop_limit` | `true` | Stop Limit mod aktif |
| `stop_limit_gap_prim` | `0.3` | Stop ile limit arası mesafe (prim) |

### Geriye Uyumluluk

`use_stop_limit: false` yapılırsa eski `TRADE_ACTION_SLTP` mantığı aynen çalışır.
Hiçbir mevcut fonksiyon silinmedi veya mantığı değiştirilmedi.

### Teknik Doğrulama

- Sözdizimi: `ast.parse()` — h_engine.py ✓, mt5_bridge.py ✓
- JSON: `json.load()` — default.json ✓
- Build: `npm run build` — 0 hata ✓

### Versiyon

- Mevcut: v5.9.0 (değişiklik oranı %1.56 < %10 — artış yok)
- Commit: `ae189bd`
- Sınıf: C3 (Kırmızı Bölge: mt5_bridge.py, config/default.json) + C2 (Sarı Bölge: h_engine.py)

### Geri Alma

```bash
git revert ae189bd --no-edit
```

### Test Planı

1. Piyasa açıkken bir pozisyon hibrite devret → trailing + hedef Stop Limit emirlerin MT5 bekleyen emirlerde görünmesini doğrula
2. Fiyat hareket ettikçe trailing emrin `modify_stop_limit` ile güncellenmesini logdan doğrula
3. Pozisyon kapatıldığında bekleyen emirlerin iptal edilmesini doğrula
4. Engine restart sonrası `_restore_stop_limit_tickets` ile emir eşleşmesini doğrula
