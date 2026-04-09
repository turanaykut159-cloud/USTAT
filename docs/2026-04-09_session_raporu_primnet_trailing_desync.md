# Oturum Raporu — PRİMNET Trailing Desync Fix

**Tarih:** 9 Nisan 2026
**Oturum:** 14:00 – 14:35 (Savaş Zamanı — acil bug fix)
**Versiyon:** v5.9.0 (değişiklik yok)
**Commit:** dc11e69, ea9f3e1

---

## Özet

STOP LIMIT trailing emirlerde iki kritik hata tespit ve düzeltildi:

1. **#142** — `modify_pending_order` STOP LIMIT emirlerde `stoplimit` parametresini göndermiyordu → MT5 retcode 10015 "Invalid price"
2. **#143** — Modify başarısız olduğunda bellek/DB güncellenip MT5'te eski fiyat kalıyordu. LOCK mekanizması desync'i gizliyordu → `_verify_trailing_sync()` eklendi

---

## Sorun #142 — modify_pending_order stoplimit eksikliği

**Kök Neden:** `mt5_bridge.py modify_pending_order()` fonksiyonu sadece `price` alanını gönderiyordu. STOP LIMIT emirlerde `stoplimit` alanı da zorunlu. SELL STOP LIMIT'te `stoplimit >= price` kuralı var. Trailing stop 106.45 → 106.95'e taşındığında eski stoplimit=106.75 < yeni price=106.95 → retcode 10015.

**Düzeltme:**
- `modify_pending_order`'a opsiyonel `new_stoplimit: float | None = None` parametresi eklendi
- `_trailing_via_stop_limit` artık `new_stoplimit=limit_price` geçiyor
- Dosyalar: `engine/mt5_bridge.py`, `engine/h_engine.py`

**Sınıf:** C3 (Kırmızı Bölge — mt5_bridge.py)

---

## Sorun #143 — Trailing LOCK desync tespiti

**Kök Neden:** `_trailing_via_stop_limit` satır 1310'da `hp.current_sl = new_sl` ile belleği güncelliyor — MT5 modify başarısız olsa bile. Sonraki döngülerde trailing hesabı aynı SL'yi verince LOCK tetikleniyor (`new_sl <= current_sl` BUY / `new_sl >= current_sl` SELL) ve fonksiyon sessizce dönüyor. Desync kalıcı hale geliyor.

**Düzeltme:**
- `_verify_trailing_sync()` metodu eklendi (93 satır)
- LOCK tetiklendiğinde çağrılır
- MT5 bekleyen emri ile bellekteki SL'yi karşılaştırır
- Tick tolerance (1.5×tick) dışında fark varsa → cancel + replace
- Restart sonrası yetim emir tespiti (comment-based `PRIMNET_TRAIL_{ticket}`)
- Dosya: `engine/h_engine.py`

**Sınıf:** C2 (Sarı Bölge — h_engine.py)

---

## Operasyonel Notlar

### Motor Restart Sorunu
Önceki oturumda `restart_app` komutu başarılı raporlandı ancak PID değişmedi (5896 → 5896). Eski motor yeni kodu yüklemedi. Çözüm: `taskkill /F /PID` ile manuel process öldürme + `start_app`.

### F_TKFEN Pozisyonu
- BUY ticket=8050532174, entry=107.95
- 13:43'te hibrite devredildi, SL=106.45
- Trailing 106.45→106.95 denendi ama modify başarısız (fix #142 öncesi)
- 14:22'de EXTERNAL kapanma (PnL: +40 TRY)
- Desync düzeltme moot — pozisyon zaten kapalı

### F_AKBNK Pozisyonu
- SELL ticket=8050533471, current_sl=77.30
- PRİMNET trailing hesaplıyor: SL=77.65 (mevcut 77.30'dan kötü)
- LOCK doğru çalışıyor — SL yukarı taşınmıyor
- Fiyat yeterince düşmediği için trailing henüz tetiklenmedi

---

## Değişiklik Listesi

| Dosya | Satır | Değişiklik |
|-------|-------|-----------|
| `engine/mt5_bridge.py` | ~2617 | `new_stoplimit` parametresi + request["stoplimit"] |
| `engine/h_engine.py` | 1118,1122 | LOCK bloğuna `_verify_trailing_sync()` çağrısı |
| `engine/h_engine.py` | 1341-1427 | Yeni `_verify_trailing_sync()` metodu (93 satır) |
| `engine/h_engine.py` | 1247-1250 | `modify_pending_order` çağrısına `new_stoplimit=limit_price` |

---

## Test ve Doğrulama

- Motor init logu `trailing modu=STOP LIMIT EMİR` gösteriyor → yeni kod aktif
- PRİMNET hesaplamalar 10 saniyede bir çalışıyor (F_AKBNK)
- `_verify_trailing_sync` çağrılıyor (get_pending_orders logu PRİMNET calc sonrası görünüyor)
- F_AKBNK için trailing order yok → fonksiyon sessizce dönüyor (doğru davranış)
- Desync durumu test edilemedi (F_TKFEN zaten kapalı, F_AKBNK'da trailing order yok)
