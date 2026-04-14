# Oturum Raporu — PRİMNET Daily Reset Rollback + Self-Heal

**Tarih:** 13 Nisan 2026  
**Konu:** PRİMNET günlük yenileme rollback koruması, restore self-heal, previous_date düzeltmesi  
**Versiyon:** 6.0.0 (artış yok — değişiklik oranı <%10)  
**Commit:** `da25662`  
**Sınıf:** C2 (Sarı Bölge — h_engine.py)  

---

## Özet

PRİMNET (Prim-based Net Order Tracking) sistemi canlıda ilk kez çalıştırıldıktan sonra derin inceleme yapıldı. Üç hata tespit ve düzeltildi:

1. **#218 — Daily Reset Rollback Koruması (HIGH):** `_primnet_daily_reset` fonksiyonunda trailing Stop Limit başarılı fakat hedef Stop Limit başarısız olduğunda, trailing emir yetim kalıyordu. Netting sync rollback kalıbı (`_sync_netting_volume` satır 1115-1122) örnek alınarak atomik tutarlılık sağlandı.

2. **#217 — Restore Self-Heal (HIGH):** Uygulama yeniden başlatıldığında `_restore_stop_limit_tickets` sadece metadata eşleşmesi yapıyor; eğer restart sırasında MT5'teki emirler expire olmuşsa `ticket=0` kalıyordu ve sonraki döngülerde `_verify_trailing_sync` erken dönüş yaparak pozisyon korumasız kalıyordu. `_refresh_daily_pnl` içine self-heal mekanizması eklendi: ACTIVE pozisyonlarda `ticket=0` tespit edildiğinde `_primnet_daily_reset` otomatik tetikleniyor.

3. **#216 — previous_date "?" Sorunu (MEDIUM):** `_refresh_daily_pnl` fonksiyonunda `self._daily_pnl_date` gün değişiminde `today` ile üzerine yazıldıktan SONRA `previous` değişkenine atanıyordu. Bu nedenle `_primnet_daily_reset(previous)` her zaman `today` değerini alıyordu. Fix: `previous` ataması gün değişimi kontrolünden ÖNCE yapıldı.

---

## Değişen Dosyalar

| Dosya | Değişiklik | Bölge |
|-------|-----------|-------|
| `engine/h_engine.py` | 3 fix (rollback, self-heal, previous_date) | Sarı Bölge #1 |
| `docs/USTAT_GELISIM_TARIHCESI.md` | Changelog #216-#218 | C0 |

## Etki Analizi

- **Doğrudan etki:** `_primnet_daily_reset`, `_refresh_daily_pnl` fonksiyonları
- **Dolaylı etki:** `_cancel_stop_limit_orders`, `_place_target_stop_limit`, `mt5.cancel_pending_order`
- **Kırmızı Bölge dokunuşu:** Yok
- **Siyah Kapı dokunuşu:** Yok
- **Frontend değişikliği:** Yok (build gerekmedi)

## Doğrulama

- AST syntax kontrolü: PASSED
- Git commit: `da25662` (2 dosya, +80/-8 satır)
- Windows testleri: Sandbox'ta çalıştırılamadı (MetaTrader5, loguru bağımlılığı). Windows'ta `python -m pytest tests/critical_flows -q --tb=short` çalıştırılması önerilir.

## Geri Alma Planı

```bash
git revert da25662 --no-edit
```

## Öneriler

1. `tests/test_hybrid_100.py` config'ine `use_stop_limit: true` eklenerek Stop Limit yolu test kapsamına alınmalı
2. Windows ortamında `tests/critical_flows` çalıştırılarak mevcut testlerin geçtiği doğrulanmalı
3. Bir sonraki piyasa gününde (14 Nisan) PRİMNET logları izlenerek self-heal ve rollback mekanizmalarının tetiklenip tetiklenmediği kontrol edilmeli
