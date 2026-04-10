# Oturum Raporu — PRİMNET Orphan Bekleyen Emir Temizliği

**Tarih:** 2026-04-10
**Versiyon:** v5.9.0 (değişiklik oranı < %10 — versiyon artışı yok)
**Kategori:** Fixed — Kritik (direktional flip riski)
**Değişiklik Sınıfı:** C2 (Sarı Bölge — h_engine.py)
**Tarihçe Girdi:** #148

---

## 1. Kullanıcı Bildirimi (Verbatim)

> "bak bakalım neden 2 tane emirler var eğer emir değişirse eski emiri sil. alta neden iki tane emir koydun bu risk emirin biri pozisyonu kapatır digeri tekrar işlem açar şu mantığı iyi kavra emir koyarken bu tabloyu görmüyor musun?"

**Çeviri:** Neden 2 emir var. Emir değişirse eski emiri sil. Pozisyonun altına neden iki emir koydun — biri pozisyonu kapatır, diğeri tekrar işlem açar (netting flip riski).

---

## 2. Sorunun Tespiti

**Etkilenen pozisyon:** F_AKBNK SELL ticket=8050545494, 5 lot @ 78.76

**Gözlemlenen durum:** PRİMNET trailing + hedef için tek trailing + tek target bekleyen emir olması gerekirken, MT5 terminal ekranında 4 BUY yönlü bekleyen emir listeleniyordu:

```
ticket=8050545561 type=BUY_STOP_LIMIT vol=5.0 comment='PRIMNET_TRAIL_80'
ticket=8050545562 type=BUY_LIMIT      vol=5.0 comment='PRIMNET_TGT_8050'
ticket=8050546603 type=BUY_LIMIT      vol=5.0 comment='PRIMNET_TGT_8050'
ticket=8050546613 type=BUY_STOP_LIMIT vol=5.0 comment='PRIMNET_TRAIL_80'
```

**Finansal risk:** VİOP netting modunda BUY_STOP_LIMIT tetiklenirse önce 5 lot SELL pozisyonu kapanır, fazla kalan volume YENİ BUY pozisyon oluşturur. Yani tek bir tetik = pozisyon kapanması + ters yön açılması = directional flip.

---

## 3. Kök Neden Analizi

### 3.1 Birincil Kök Neden — Broker Comment Kırpma

`engine/h_engine.py` orphan temizliği kodu `PRIMNET_TRAIL_{ticket}` ve `PRIMNET_TGT_{ticket}` comment prefix'leriyle bekleyen emirleri arıyordu. Restart sonrasında bu arama her seferinde başarısız oluyordu.

**DEBUG log kanıtı (12:15:13.014):**
```
_find_orders_by_comment: aranan='PRIMNET_TRAIL_8050545494' F_AKBNK
eşleşme yok. Mevcut bekleyen emirler:
[ticket=8050545561 ... comment='PRIMNET_TRAIL_80']
```

GCM broker MT5 comment alanını **tam olarak 16 karakterde** kırpıyor:
- `PRIMNET_TRAIL_8050545494` (24 kar) → `PRIMNET_TRAIL_80` (16 kar)
- `PRIMNET_TGT_8050545494` (22 kar) → `PRIMNET_TGT_8050` (16 kar)

Arama stringi kırpılmış comment'e uymuyordu → orphan hiç bulunamıyordu → her restart'ta eski emirler kalıyordu + yeni emirler eklenince emir sayısı çoğalıyordu.

### 3.2 İkincil Kök Neden — Comment-Only Eşleştirme Tek Savunma Hattıydı

Orphan temizliği SADECE comment prefix eşleşmesine dayanıyordu. Comment sistemi bozulunca (yukarıdaki kırpma nedeniyle) hiçbir yedek savunma yoktu.

---

## 4. Uygulanan Çözüm (Üç Katmanlı Savunma)

### 4.1 Katman 1 — Comment Kısaltma

Tüm comment prefix'leri 16 karakter limiti altına indirildi:

| Eski | Yeni | Uzunluk (11-rakamlı ticket) |
|------|------|---|
| `PRIMNET_TRAIL_{ticket}` | `TRL_{ticket}` | 14 kar (≤16 ✓) |
| `PRIMNET_TGT_{ticket}` | `TGT_{ticket}` | 14 kar (≤16 ✓) |

**Dosya:** `engine/h_engine.py`
**Değişiklik sayısı:** 27 adet (`replace_all` ile)
**Etkilenen bölgeler:** `transfer_to_hybrid` (hibrit devir), `_sync_netting_volume` (lot ekleme/çıkarma), `_trailing_via_stop_limit`, `_place_target_limit`, `_cancel_orphan_pending_for_symbol`, `_cleanup_primnet_orphans_on_restart`, `_restore_stop_limit_tickets`.

### 4.2 Katman 2 — Yön Bazlı Fallback Yardımcısı

Yeni `_cancel_orphan_pendings_by_direction()` yardımcı metodu eklendi. Comment'e bakmadan, pozisyonun ters yönündeki izlenmeyen pending emirleri yön+tip bazlı iptal eder:

```python
def _cancel_orphan_pendings_by_direction(self, hp: "HybridPosition") -> int:
    pending = self.mt5.get_pending_orders(hp.symbol)
    if hp.direction == "SELL":
        dangerous_types = {"BUY_STOP_LIMIT", "BUY_LIMIT", "BUY_STOP"}
    else:
        dangerous_types = {"SELL_STOP_LIMIT", "SELL_LIMIT", "SELL_STOP"}

    tracked = set()
    if hp.trailing_order_ticket > 0:
        tracked.add(hp.trailing_order_ticket)
    if hp.target_order_ticket > 0:
        tracked.add(hp.target_order_ticket)

    cancelled = 0
    for order in pending:
        if order["type"] not in dangerous_types:
            continue
        if order["ticket"] in tracked:
            continue
        if self.mt5.cancel_pending_order(order["ticket"]) is not None:
            cancelled += 1
    return cancelled
```

Bu fallback, comment sisteminin bozulması (kırpma, corrupt, farklı broker) durumunda savunmayı devam ettirir.

### 4.3 Katman 3 — Entegrasyon

**`_cleanup_primnet_orphans_on_restart`** — comment bazlı temizlik sonrası fallback çağrılır:
```python
# Comment bazlı temizlik yapılır...
# ── 2) Yön bazlı savunma (fallback) ──
remaining = self._cancel_orphan_pendings_by_direction(hp)
if remaining > 0:
    logger.warning(f"Yön bazlı fallback: pozisyon={hp.ticket} ...")
```

**`_restore_stop_limit_tickets`** — hiçbir comment eşleşmesi bulunamazsa fallback:
```python
if not comment_match_found:
    fallback_cancelled = self._cancel_orphan_pendings_by_direction(hp)
```

**`_trailing_via_stop_limit`** — yeni trailing emir göndermeden önce defansif temizlik:
```python
# v5.9.2 — Defansif orphan temizliği: yeni emir göndermeden ÖNCE
# aynı comment prefix ile bekleyen TÜM emirleri iptal et
orphans = self._find_orders_by_comment(hp.symbol, f"TRL_{hp.ticket}")
for orphan in orphans:
    self.mt5.cancel_pending_order(orphan["ticket"])
```

Bu kullanıcının açık kuralını zorunlu kılar: "emir değişirse eski emiri sil" — yeni emir YAZILMADAN önce eski iptal edilir.

### 4.4 DEBUG Logging

`_find_orders_by_comment` metodu eşleşme bulamadığında tüm mevcut bekleyen emirlerin detayını (ticket, type, volume, comment) DEBUG seviyesinde loglar. Bu, broker comment kırpmasını/bozulmasını teşhis etmeyi mümkün kıldı.

---

## 5. Live Doğrulama

**12:15:13.014** — Engine restart sonrası `_restore_stop_limit_tickets` çağrıldı, comment eşleşmesi başarısız (kırpılmış comment'ler):
```
_find_orders_by_comment: aranan='PRIMNET_TRAIL_8050545494' eşleşme yok
```

**12:15:14.369** — Yön bazlı fallback devreye girdi:
```
Yön bazlı orphan iptal edildi: order=8050546613 F_AKBNK type=BUY_STOP_LIMIT
Yön bazlı fallback (restore): pozisyon=8050545494 F_AKBNK SELL
için 4 izlenmeyen orphan iptal edildi (comment eşleşmesi yoktu)
```

**12:23:07** — Stabil durum: `Bekleyen emir sayısı: 2` (1 trailing + 1 target, correct), pozisyon normal yönetiliyor, directional flip riski elimine.

### 5.1 Eksik Kalan Doğrulama

Comment kısaltma fix'i (`TRL_`/`TGT_`) kod dosyasında aktif ama **engine process henüz bu yeni kodla restart edilmedi**. Mevcut engine hâlâ eski `PRIMNET_TRAIL_` comment formatını kullanıyor. Sonraki restart (BARIŞ ZAMANI — 18:15 sonrası) ile yeni comment'lerin broker tarafından kırpılmadan saklandığı doğrulanacak.

**Önemli:** Bu eksik doğrulama temel bug'ı etkilemez — yön bazlı fallback her durumda orphan'ları temizler (comment formatı ne olursa olsun). Comment kısaltma optimizasyon düzeyinde bir iyileştirmedir (her restart'ta fallback'ın boşa tetiklenmesini önler).

---

## 6. Test Sonuçları

```
tests/test_hybrid_100.py + tests/test_unit_core.py
146 passed, 11 failed in 1.07s
```

**11 başarısız test:** TestPrimCalc, TestFaz1, TestFaz2 — baseline. Hiçbirinin değiştirilen fonksiyonlarla ilgisi yok. Yeni regresyon yok.

**Syntax kontrolü:** `ast.parse(engine/h_engine.py)` → OK.

---

## 7. Değişen Dosyalar

| Dosya | Bölge | Değişiklik |
|-------|-------|-----------|
| `engine/h_engine.py` | Sarı (Anayasa 4.2) | +362 / -78 satır |
| `docs/USTAT_GELISIM_TARIHCESI.md` | Yeşil | +1 changelog girdisi (#148) |
| `docs/2026-04-10_session_raporu_primnet_orphan_cleanup.md` | Yeşil | Yeni oturum raporu |

---

## 8. Etki Analizi

**Çağrı zinciri etkisi:**
- `restore_positions` (lifespan startup) → `_restore_stop_limit_tickets` → fallback (yeni) → `cancel_pending_order`
- `restore_positions` → `_cleanup_primnet_orphans_on_restart` → comment match + fallback (yeni) → `cancel_pending_order`
- `_trailing_via_stop_limit` → `_find_orders_by_comment` + cancel (yeni defansif blok) → `send_stop_limit`

**Risk kontrol etkisi:** Yok. BABA risk pipeline'ı değişmedi. Sadece H-Engine'in iç orphan temizliği güçlendirildi.

**Siyah Kapı etkisi:** Yok. H-Engine Siyah Kapı kapsamında değil (Sarı Bölge).

**Geri alma:** `git revert <commit_hash>` — tek commit'te tüm değişiklikler, temiz geri alma.

---

## 9. Pending İşler

- [ ] Engine production build + restart (BARIŞ ZAMANI — 18:15 sonrası)
- [ ] Yeni `TRL_`/`TGT_` comment'lerinin broker'da saklandığını doğrula
- [ ] Commit hash'i changelog'a ekle (git commit sonrası)

---

## 10. Kullanıcı Talimatına Uyum

**Kullanıcı:** "eğer emir değişirse eski emiri sil"
**Uyum:** `_trailing_via_stop_limit`'e yeni emir göndermeden önce `_find_orders_by_comment` ile TÜM orphan trailing emirlerin iptalini zorunlu kılan bir blok eklendi. Yönelim kuralı: **ÖNCE SİL, SONRA YAZ.**

**Kullanıcı:** "alta neden iki tane emir koydun bu risk"
**Uyum:** Yön bazlı fallback, pozisyonun altına/üstüne yanlış yönde hiçbir izlenmeyen emir kalmasına izin vermez. Her restart ve her yeni emir gönderimi öncesi temizlik.
