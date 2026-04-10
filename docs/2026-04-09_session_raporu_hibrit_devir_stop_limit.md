# Oturum Raporu — 2026-04-09

## Konu: Hibrit Devir "Invalid order" Hatası Düzeltmesi (#140)

## Özet

Hibrit motora işlem devri sırasında "Devir hatası: Stop trailing emri gönderilemedi — devir iptal" hatası alınıyordu. Kök neden: GCM VİOP düz STOP (ORDER_TYPE_BUY_STOP / ORDER_TYPE_SELL_STOP) emirlerini desteklemiyor, sadece STOP LIMIT (ORDER_TYPE_BUY_STOP_LIMIT / ORDER_TYPE_SELL_STOP_LIMIT) emirleri kabul ediyor.

## Teşhis Süreci

1. İlk hata mesajı `retcode=10027` (AutoTrading disabled by client) idi — bu MT5'te Algo Trading kapalıyken görülüyordu
2. Kullanıcı Algo Trading'i açtıktan sonra hata devam etti
3. MT5 günlüğü incelendi: `failed buy stop 1 F_ASELS0426 at 378.26 [Invalid order]` — 7 kez tekrarlanmış
4. Bu, hatanın AutoTrading ile değil emir tipi ile ilgili olduğunu kanıtladı
5. Kod incelemesi: `h_engine.py` `_use_stop_limit=True` olmasına rağmen `send_stop()` (düz STOP) çağırıyordu, `send_stop_limit()` (STOP LIMIT) değil

## Kök Neden

`engine/h_engine.py`'de 3 noktada `self.mt5.send_stop()` çağrılıyordu:
- Satır 433: `transfer_to_hybrid()` — ilk devir
- Satır 1185: `_trailing_via_stop_limit()` — trailing güncelleme
- Satır 1905: `_daily_primnet_refresh()` — günlük yenileme

GCM VİOP netting modda düz STOP emirleri (type=4, type=5) kabul etmiyor. Sadece STOP LIMIT emirleri (type=6, type=7) destekleniyor.

## Uygulanan Düzeltme

Her 3 noktada `send_stop()` → `send_stop_limit()` dönüşümü yapıldı:
- `stop_price`: Mevcut SL fiyatı (değişmedi)
- `limit_price`: `_stop_limit_gap_prim` (config: 0.3 prim) kullanılarak hesaplandı
  - BUY STOP LIMIT: `limit_price = stop_price - gap` (limit < stop)
  - SELL STOP LIMIT: `limit_price = stop_price + gap` (limit > stop)

## Değişiklik Sınıfı

C2 (Sarı Bölge — h_engine.py)

## Etki Analizi

- Kırmızı Bölge dokunusu: YOK
- Siyah Kapı dokunusu: YOK
- Fonksiyonel değişiklik: Emir tipi STOP → STOP LIMIT (davranış aynı, GCM VİOP uyumlu)
- Config parametresi: `hybrid.primnet.stop_limit_gap_prim` (0.3) — zaten mevcuttu

## Değişen Dosyalar

| Dosya | Değişiklik |
|-------|-----------|
| `engine/h_engine.py` | 3 noktada send_stop → send_stop_limit + limit fiyat hesaplaması |
| `docs/USTAT_GELISIM_TARIHCESI.md` | #140 maddesi eklendi |

## Versiyon

v5.9.0 (değişiklik oranı %10 altında, versiyon artışı gerekmez)

## Commit

`1047414` — fix: #140 — hibrit devir send_stop → send_stop_limit (GCM VİOP uyumluluğu)

## Build

Frontend değişikliği yok (sadece Python engine). Uygulamanın yeniden başlatılması yeterli.

## Geri Alma

```bash
git revert 1047414
```
