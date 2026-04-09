# Oturum Raporu — 9 Nisan 2026

**Konu:** PRİMNET Edge Case Korumaları (#144, #145, #146)
**Süre:** ~3 saat (önceki oturumdan devam)
**Commit:** `3d797bd`
**Versiyon:** 5.9.0 (değişiklik oranı <%10, versiyon artışı gereksiz)

---

## Özet

F_AKBNK SELL 16 lot hibrit pozisyonunun PRİMNET analizi sırasında tespit edilen 3 kritik edge case kapatıldı. Tüm fix'ler Sarı Bölge (h_engine.py) ve Kırmızı Bölge (baba.py, database.py, main.py) dosyalarına uygulandı.

## Kök Neden Analizi

Kullanıcı 10 lot SELL pozisyon açtıktan sonra manuel olarak 6 lot daha ekledi (toplam 16 lot). Bu senaryoda:

1. **DB şema eksikliği:** `hybrid_positions` tablosunda `trailing_order_ticket` ve `target_order_ticket` sütunları yoktu → `_sync_netting_volume` UPDATE çağrısı tamamen başarısız oluyor, volume/entry_price de güncellenemiyordu.
2. **Duplikat emir:** Engine restart sonrası bellek `trailing_order_ticket=0` ile başladığı için `_trailing_via_stop_limit` yeni emir oluşturuyor, eski emir MT5'te kalıyordu.
3. **Lot çıkarma branch eksik:** `_sync_netting_volume` lot ekleme durumunda emirleri güncelliyordu ama lot çıkarma branch'inde bekleyen emirler eski volume ile kalıyordu.

Kapsamlı edge case analizi sonucu 3 ek açık tespit edildi:

| # | Açık | Risk |
|---|------|------|
| A6 | Yön değişimi algılanmıyor | H-engine ters yöndeki pozisyonu yönetemez |
| D2 | Kill-Switch L3 bekleyen emirleri iptal etmiyor | STOP LIMIT emirler yetim kalır |
| A4 | Lot çıkarma bekleyen emirleri güncellemiyor | Eski volume ile emir kalır |

## Yapılan Değişiklikler

### Fix #144 — Lot Çıkarma Emir Güncelleme (h_engine.py)

**Dosya:** `engine/h_engine.py` — `_sync_netting_volume` lot çıkarma branch'i
**Sınıf:** C2 (Sarı Bölge)

Lot azaltma tespit edildiğinde:
1. Tüm PRIMNET trailing + target emirleri iptal edilir
2. Yeni volume ile trailing stop limit + target limit emirleri oluşturulur
3. SL/TP mevcut değerlerden korunur (yeni giriş fiyatından yeniden hesaplanmaz)

### Fix #145 — Yön Değişimi Algılama (h_engine.py)

**Dosya:** `engine/h_engine.py` — `run_cycle` ana döngüsü
**Sınıf:** C2 (Sarı Bölge)

Her 10sn döngüde MT5 pozisyon yönü (`type: BUY/SELL`) ile `hp.direction` karşılaştırılır:
- Yön farklıysa → tüm PRIMNET emirleri iptal
- Hibrit takip `DIRECTION_FLIP` sebebiyle sonlandırılır
- MT5 pozisyonu KAPATILMAZ (kullanıcı kararı)
- UI'a critical bildirim + DB notification kaydı

**Senaryo:** SELL 16 lot pozisyona karşı 20 lot BUY girerse → VİOP netting → BUY 4 lot. H-engine SELL parametreleri ile BUY pozisyonu yönetemez → güvenli sonlandırma.

### Fix #146 — Kill-Switch L3 Koordinasyonu (baba.py, main.py)

**Dosya:** `engine/baba.py` — `_activate_kill_switch`, `engine/main.py` — Engine constructor
**Sınıf:** C3 (Kırmızı Bölge — baba.py) + C3 (Kırmızı Bölge — main.py)

1. `main.py`: `self.baba.h_engine = self.h_engine` referansı eklendi
2. `baba.py`: L3 tetiklendiğinde `_close_all_positions`'dan ÖNCE `h_engine.force_close_all("KILL_SWITCH_L3")` çağrılır
3. `force_close_all` zaten tüm PRIMNET emirlerini iptal ediyor (`_cancel_stop_limit_orders`)
4. `getattr(self, "h_engine", None)` ile güvenli erişim — h_engine yoksa atlanır

**Önceki önceki fix'lerden bu oturumda da uygulanan (önceki oturumdan):**
- DB şema: `ALTER TABLE hybrid_positions ADD COLUMN trailing_order_ticket/target_order_ticket`
- `database.py`: CREATE TABLE + INSERT OR REPLACE sorgularına yeni sütunlar
- `_sync_netting_volume` lot ekleme: tüm PRIMNET emirleri iptal + yeni oluşturma
- `_verify_trailing_sync`: duplikat trailing emir temizliği
- `restore_positions`: DB'den trailing/target ticket yükleme

## Etkilenen Dosyalar

| Dosya | Bölge | Değişiklik |
|-------|-------|-----------|
| `engine/h_engine.py` | Sarı | Fix #144, #145 + önceki oturumdan lot ekleme/duplikat fix |
| `engine/baba.py` | Kırmızı | Fix #146 — L3 h_engine koordinasyonu |
| `engine/main.py` | Kırmızı | Fix #146 — h_engine referansı |
| `engine/database.py` | Kırmızı | Şema: 2 yeni sütun (önceki oturumdan) |
| `docs/USTAT_GELISIM_TARIHCESI.md` | C0 | #144, #145, #146 kayıtları |

## Doğrulama

- Syntax kontrolü: 4/4 dosya OK
- Engine restart: Başarılı (8.1sn)
- Log kontrolü: Hata yok, hibrit pozisyon doğru restore edildi
- Netting SYNC tetiklenmedi (DB=MT5=16 lot)
- DIRECTION_FLIP tetiklenmedi (yön aynı: SELL)
- Bekleyen emir sayısı: 2 (trailing + target, doğru)
- PRİMNET trailing hesaplaması çalışıyor (SL=78.30)

## Geri Alma

```bash
git revert 3d797bd --no-edit
# Not: DB şema değişikliği (ALTER TABLE) geri alınamaz ama
# yeni sütunlar DEFAULT 0 olduğu için zarar vermez
```
