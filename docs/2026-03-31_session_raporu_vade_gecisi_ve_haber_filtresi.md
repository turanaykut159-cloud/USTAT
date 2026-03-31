# Oturum Raporu — 31 Mart 2026

**Konu:** Vade geçişi otomasyonu, L1 kill-switch düzeltmeleri, haber filtresi, pozisyon görünürlük
**Versiyon:** v5.9.0 (versiyon artışı gerekmedi — %0.24 değişim)
**Commit:** 647d178

---

## Yapılan İşler

### 1. Başlatıcı Düzeltmeleri (start_ustat.py — Sarı Bölge)
- **shutdown.signal koşulsuz temizleme:** Masaüstü kısayolundan başlatıldığında shutdown.signal'in engellemesi kaldırıldı. Kısayol 2 dakika içinde yeniden başlatılamıyordu.
- **API timeout 30→15sn:** Gereksiz uzun bekleme kısaltıldı.

### 2. OLAY Rejimi Vade Kontrolü (baba.py — Kırmızı Bölge)
- **Sorun:** `_check_olay()` satır 834'te `if 0 <= days <= EXPIRY_DAYS:` ile EXPIRY_DAYS=0 olmasına rağmen vade günü OLAY rejimi tetikleniyordu.
- **Çözüm:** `<=` → `<` operatörüne değiştirildi. EXPIRY_DAYS=0 artık hiçbir vade kontrolü tetiklemiyor.
- **Kanıt:** top5_selection.py'de aynı düzeltme daha önce yapılmıştı (#83), baba.py karşılığı eksikti.

### 3. L1 Kill-Switch Günlük Sıfırlama (baba.py — Kırmızı Bölge)
- **Sorun:** Haber kaynaklı L1 kontrat engeli 2+ gün aktif kalıyordu. `_reset_daily()` sadece L2'yi temizliyordu.
- **Çözüm:** `_reset_daily()` fonksiyonuna L1 temizleme eklendi — yeni günde önceki günün L1 engelleri kaldırılır.
- **Anayasa Kural #3 uyumu:** Kill-switch seviyesi monoton yukarı gider kuralı korunuyor — bu günlük sıfırlama, yeni günün başında yapılır.

### 4. Haber Filtresi İyileştirmesi (news_bridge.py — Yeşil Bölge)
- **Sorun 1:** `get_news_warnings()` fonksiyonunda VİOP ilgisizlik filtresi (`_is_viop_relevant_for_olay()`) eksikti. EUR/JPY/GBP haberleri VİOP kontratlarında L1 tetikliyordu.
- **Çözüm:** Currency filtresi eklendi — sadece TRY/USD haberleri VİOP'ta L1 tetikler.
- **Sorun 2:** SYMBOL_KEYWORDS'de "perakende", "savunma", "çelik" gibi genel sektör kelimeleri vardı. Almanya perakende satış haberi → "perakende" → F_BIMAS L1 tetikliyordu.
- **Çözüm:** Genel sektör kelimeleri kaldırıldı, sadece şirket isim/kısaltmaları bırakıldı.

### 5. Vade Geçişi Otomasyonu (mt5_bridge.py — Kırmızı Bölge)
- **Sorun:** `_resolve_symbols()` visible kontratı seçiyor ama vade son günü eski kontrat (0326) hâlâ visible olabiliyor. 12/15 sembol activate edilemiyordu. Sistem expired kontratlarla çalışıyordu.
- **Çözüm:** `_resolve_symbols()` tamamen yeniden yazıldı:
  - Kontratlar en yeni vadeden eskiye sıralanır
  - Her biri `symbol_select()` ile activate edilmeye çalışılır
  - İlk başarılı olan seçilir
  - Activate ve map oluşturma tek döngüde — `connect()` içindeki ayrı activate döngüsü kaldırıldı
- **Sonuç:** Restart sonrası TÜM kontratlar 0526'ya (Mayıs 2026) eşlendi ve activate edildi. 16/16 başarılı.

### 6. Pozisyon Görünürlük (mt5_bridge.py — Kırmızı Bölge)
- **Sorun 1:** `_resolve_symbols()` çoklu visible'da `min()` kullanıyordu → eski vadeyi seçiyordu.
- **Çözüm:** `min()` → `max()` (bu artık yeni resolve mantığına entegre).
- **Sorun 2:** `_to_base()` sadece reverse_map'te arıyordu. Pozisyon farklı vadedeyse (ör. map 0326, pozisyon 0426) bulunamıyordu.
- **Çözüm:** Prefix fallback eklendi — WATCHED_SYMBOLS üzerinde `startswith` kontrolü.

---

## Doğrulama

### Restart Sonrası Log Kanıtları
```
11:23:52 | Sembol eşleme: F_THYAO → F_THYAO0526 (visible=True, activated=True)
11:23:52 | Sembol eşleme: F_AKBNK → F_AKBNK0526 (visible=True, activated=True)
... (15/15 kontrat 0526'ya eşlendi)
11:23:52 | Sembol çözümleme tamamlandı: 16/16 eşlendi
```

### API Durumu
- Kill-switch: L0 (temiz)
- Rejim: TREND
- MT5: Bağlı
- Engine: Çalışıyor
- 15/15 OHLCV veri çekimi başarılı

---

## Değişen Dosyalar

| Dosya | Bölge | Değişiklik |
|-------|-------|------------|
| `engine/mt5_bridge.py` | Kırmızı | _resolve_symbols() yeniden yazım + _to_base() fallback |
| `engine/baba.py` | Kırmızı | _check_olay() operatör + _reset_daily() L1 temizleme |
| `engine/news_bridge.py` | Yeşil | Currency filtresi + SYMBOL_KEYWORDS temizlik |
| `start_ustat.py` | Sarı | shutdown.signal + API timeout |
| `docs/USTAT_GELISIM_TARIHCESI.md` | C0 | #91-#96 maddeleri |

---

## Geri Alma

```bash
git revert 647d178 --no-edit
```
