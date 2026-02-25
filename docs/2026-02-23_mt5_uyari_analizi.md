# MT5 Terminal Uyari Analiz Raporu
**Tarih:** 2026-02-23
**Oturum:** USTAT v5.0 MT5 log incelemesi

---

## 1. "Outdated server build" Uyarisi (BROKER TARAFLI)

```
outdated server build - must be at least 5200, contact your broker please
```

- GCM sunucu build'i: **4755**, MT5 terminali minimum **5200** bekliyor
- **USTAT ile ilgisi YOK** — Tamamen GCM Capital sunucu tarafi sorunu
- GCM'in sunucularini guncellemesi gerekiyor
- Emir isleme, hata kodlari ve baglanti stabilitesini etkileyebilir
- **Oneri:** GCM musteri hizmetlerine bu uyariyi bildirin

---

## 2. "Market closed" Emir Reddi (KRITIK)

```
failed exchange sell 1 F_KONTR0226N1 at market [Market closed] — 20:47:26
```

Saat **20:47**'de F_KONTR0226N1 pozisyonu kapatma emri gonderilmis ve **"Market closed"** ile reddedilmis. VIOP 18:15'te kapanir, yani bu emir pazardan **2.5 saat sonra** gonderilmis.

### USTAT ile ilgisi var mi?

| Kaynak | Saat kontrolu | Bu emri gondermis olabilir mi? |
|--------|--------------|-------------------------------|
| **OGUL otomatik sinyaller** | 09:45-17:45 arasi kilitli | HAYIR — 17:45'ten sonra sinyal uretmez |
| **Manuel Trade paneli** | `check_manual_trade()` kontrol eder | OLASI — ama once "Islem saatleri disinda" uyarisi vermeli |
| **test_trade.py** | Saat kontrolu YOK | EN OLASI — dogrudan MT5'e emir gonderir |
| **MT5 Bridge (send_order)** | Kendi saat kontrolu YOK | Son savunma hatti MT5 sunucusu |

**Sonuc:** Emri buyuk ihtimalle `test_trade.py` scripti gonderdi. MT5 sunucusu dogru sekilde reddetti.

---

## 3. Baglanti Kopmasi

```
connection to GCM-Real01 lost — 20:47:37
```

- Emir reddinden **11 saniye sonra** baglanti kopmus
- Hemen ardindan NL2 sunucusuna yeniden baglanmis (57ms ping)
- "Outdated build" sorunu baglanti stabilitesini etkileyebilir
- **USTAT ile dogrudan ilgisi YOK** — ag/sunucu kaynakli

---

## 4. Pozitif Bulgular (Sorun olmayan)

- **Yetkilendirme:** Basarili (7023084 hesabi, GCM-Real01)
- **Senkronizasyon:** 1 pozisyon, 0 emir, 202 spread — normal
- **Trading modu:** Netting mode etkin — dogru
- **Mevcut pozisyon:** 1 adet acik pozisyon var (muhtemelen F_KONTR buy)

---

## 5. USTAT Kod Tarafi Tespit Edilen Aciklar

| Acik | Risk | Detay |
|------|------|-------|
| `mt5_bridge.py send_order()` saat kontrolu yok | ORTA | Son savunma hatti MT5 sunucusu, ama client-side kontrol eksik |
| `test_trade.py` saat kontrolu yok | DUSUK | Test scripti, ama yanlislikla calistirilabilir |
| Engine 17:45 kapanir ama VIOP 18:15'te kapanir | DUSUK | 30 dakikalik kayip var ama guvenli tarafta kaliyor |

---

## 6. Ozet

| Uyari | USTAT ilgisi | Aksiyon |
|-------|-------------|---------|
| Outdated server build | YOK | GCM'e bildirin |
| F_KONTR market closed | OLASI (test_trade.py) | test_trade.py pasif yapildi |
| Connection lost | YOK | Broker/ag kaynakli |
