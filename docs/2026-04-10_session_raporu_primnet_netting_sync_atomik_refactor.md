# Oturum Raporu — 2026-04-10

## Konu
PRİMNET Netting SYNC Atomik Refactor — `_sync_netting_volume` güvenli ve MT5 tabanlı hale getirildi

## Kullanıcı Talebi
Canlı ortamda F_AKBNK SELL pozisyonunda 18 lot vardı ama bekleyen PRIMNET stop limit emirleri hâlâ 16 lot gösteriyordu — 2 lot sahipsiz kaldı. Kullanıcı PrimNet'in yönetmiş olduğu pozisyonu her döngüde kontrol edip lot eklemesini/çıkarmasını otomatik olarak MT5 ile uyumlu hale getirmesini istedi. Açık talimat:

> "tamam hesaplamalarını mt5 ile sağlamasını yap hesap mantıkları aynı olsun. çelişki olmasın. şimdi yapacağımız işi planlayalım. etki analizini yapalım ve uygulayalım."

Ek netleştirme: "pozisyondan lot azaltıldığında maliyette bir değişim olmaz."

## Kök Neden Analizi

`logs/ustat_2026-04-09.log` satır 631407-631411 kanıtı:

```
2026-04-09 17:00:40 | INFO | Netting SYNC (lot ekleme): ticket=8050533471 F_AKBNK lot 16.0→18.0, entry 76.3413→76.3911
2026-04-09 17:00:40 | ERROR | Stop Limit reddedildi [F_AKBNK]: retcode=10019, comment=No money
2026-04-09 17:00:40 | ERROR | Netting SYNC: trailing emri gönderilemedi F_AKBNK
```

MT5 hesabı: `free_margin=9078 TRY`, `margin_level=119.88%` — kritik seviyede.

Üç kusur birleşerek probleme yol açtı:

1. **State desync bug (h_engine.py:955-956):** `hp.volume = mt5_volume` ve `hp.entry_price = mt5_entry` satırları emir gönderme denemesinden ÖNCE çalıştırılıyordu. `retcode=10019` rejection sonrası `hp.volume=18` olurken MT5'teki pending emirler hâlâ 16 lotluktaydı. Sonraki döngüde `mt5_volume == hp.volume` → sync koşulu tetiklenmedi → retry mekanizması yok.

2. **Margin ön kontrolü yok:** Cancel+replace mekanizması yetersiz marj varlığından haberdar değildi. Cancel başarılı oluyor, replace başarısız oluyor, pending emirler siliniyor ve pozisyon korumasız kalıyordu.

3. **Entry price koruması eksik:** Mevcut kod, lot çıkarma senaryosunda `hp.entry_price = mt5_entry` atıyor. Netting modda MT5 kısmi kapanışta `price_open`'ı zaten korur (yani değerler eşitti) ama semantik olarak "lot çıkarma maliyeti değiştirir" hatalı bir kanı oluşturuyordu.

## Tasarım Kararları

### Senaryo A — Lot Ekleme

1. **Margin ön kontrolü:** `free_margin < 2000` VEYA `margin_level < 150%` ise sync ertelenir. `hp` dokunulmaz, return. Bir sonraki döngüde marj iyileşirse otomatik retry.
2. **MT5 weighted avg = gerçek kaynak:** `mt5_entry` (MT5'in zaten hesapladığı weighted average) doğrudan kullanılır. Motor ayrı hesaplama yapmaz.
3. **PRİMNET SL/TP yeniden hesaplanır:** yeni entry üzerinden `trailing_prim=1.5`, `target_prim=9.5` ile.
4. **Atomik commit:** hp.volume, entry_price, SL/TP, ticket'lar SADECE her iki pending emir (trailing + hedef) başarılı olduktan sonra güncellenir. Başarısızlıkta hp eski değerinde kalır → bir sonraki döngü otomatik retry.
5. **Rollback:** Trailing başarılı, hedef başarısız senaryosunda yeni yerleştirilen trailing iptal edilir (state tutarlılığı).

### Senaryo B — Lot Çıkarma

Kullanıcı direktifi: **maliyet değişmez.**

- `hp.entry_price`, `hp.current_sl`, `hp.current_tp` DOKUNULMAZ.
- Sadece `hp.volume` güncellenir.
- Pending emirler AYNI fiyatlarda, küçülmüş volume ile yeniden yerleştirilir.
- Emir başarısızlığında software SL/TP devreye alınır (volume commit edilir çünkü MT5 gerçeği öyle).

## Etki Analizi

| Alan | Durum |
|------|-------|
| **Dosya** | `engine/h_engine.py` (Sarı Bölge — Anayasa 4.2 #1) |
| **Sınıflandırma** | C2 (Sarı Bölge kod değişikliği) |
| **Fonksiyon** | `_sync_netting_volume` (sadece bir çağıran: `run_cycle` satır 817) |
| **Kırmızı Bölge dokunusu** | YOK |
| **Siyah Kapı fonksiyon değişikliği** | YOK |
| **İmza değişikliği** | YOK — parametreler aynı |
| **Yeni config anahtarları** | `primnet.netting_sync_min_free_margin` (varsayılan 2000.0), `primnet.netting_sync_min_margin_level` (varsayılan 150.0) — `.get()` fallback ile eski kurulumlar etkilenmez |
| **DB şeması** | Değişmedi |
| **Yeni event tipi** | `NETTING_SYNC_ADD_FAILED` (başarısız lot ekleme teşhisi için) |

## Uygulama

**Değişen dosyalar:**

1. `engine/h_engine.py`
   - `__init__`: iki yeni config anahtarı eklendi (satır 162-168)
   - `_sync_netting_volume`: tamamen yeniden yazıldı (satır 939-1287, eski 932-1173)
   - Eski: 242 satır, yeni: 349 satır (atomik commit + rollback + margin pre-check mantığı)

2. `tests/test_hybrid_100.py`
   - `MockMT5` sınıfına eklendi: `get_account_info()` (None döner → margin check skip), `get_pending_orders()` (boş liste), `cancel_pending_order()` (no-op)

## Doğrulama

### Syntax kontrolü
```bash
python -m py_compile engine/h_engine.py
# OK: syntax temiz
```

### Birim testleri (tests/test_hybrid_100.py)
- **Baseline (refactor öncesi):** 89 pass / 11 fail
- **Refactor sonrası:** 89 pass / 11 fail
- **TestNettingSync altı test:** 6/6 geçti
- Kalan 11 hata (TestPrimCalc:1, TestFaz1:5, TestFaz2:5) önceden beri mevcut PRİMNET v2 refactoru (commit 6a38f64) kalıntıları — bu işin kapsamı dışında.

## Savaş/Barış Değerlendirmesi

Piyasa saatleri: Cuma 10:30 civarı. Değişiklik savaş zamanında uygulandı çünkü: (a) log kanıtıyla doğrulanmış aktif bug, (b) kullanıcı açık yazılı talimat verdi, (c) atomik commit + margin pre-check koruma katmanıdır — mevcut davranışı daha güvenli hale getirir, riski artırmaz.

## Sonraki Adımlar

1. **Windows build:** `python .agent/claude_bridge.py build`
2. **Restart:** `python .agent/claude_bridge.py restart_app`
3. **Canlı doğrulama:** F_AKBNK pozisyonunda netting SYNC logları gözle — yeni COMMIT/ERTELENDİ/BAŞARISIZ mesaj formatları görünmeli
4. **Git commit:** `engine/h_engine.py`, `tests/test_hybrid_100.py`, `docs/USTAT_GELISIM_TARIHCESI.md`, bu oturum raporu

## Geri Alma Planı

```bash
git revert <commit_hash> --no-edit
```

Eski kod tek dosya değişikliği olduğundan revert güvenlidir.
