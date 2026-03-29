# Oturum Raporu — 27 Mart 2026

## Konu: Native SL/TP Config Geri Alma + Exchange Netting Position Ticket Düzeltmesi

---

## Yapılan İş Özeti

### Sorun
Hibrit İşlem Paneli'nden "Hibrite Devret" butonuna tıklandığında pozisyon hibrit yönetime aktarılamıyordu:
```
Devir hatası: MT5 SL/TP ataması başarısız — devir iptal — retcode=10035 Invalid order
```

### Araştırma Süreci
1. **İlk teşhis:** `retcode=10035` hatası `TRADE_ACTION_SLTP` komutunda order ticket vs position ticket karışıklığı olarak değerlendirildi
2. **mt5_bridge.py düzeltmesi:** `send_order()` ve `modify_position()` fonksiyonlarına `history_deals_get(order=ticket) → deal.position_id` çözümleme eklendi (#77)
3. **Gerçek kök neden keşfi:** Uygulama yeniden başlatılıp test edildiğinde hata devam etti. Gelişim tarihçesi #1 incelenince asıl sorun belirlendi: `config/default.json`'daki `hybrid.native_sltp` parametresi 26 Mart geliştirmesinde yanlışlıkla `false`'dan `true`'ya dönmüştü
4. **Kök neden:** GCM VİOP'ta `TRADE_ACTION_SLTP` çalışmıyor (MT5 build 4755 < sunucu minimum 5200). Bu bilinen bir kısıtlama (#1, 5 Mart 2026)

### Çözüm
`config/default.json` → `hybrid.native_sltp: true` → `false`

Bu sayede h_engine yazılımsal SL/TP moduna döndü (`_check_software_sltp()` — her 10sn fiyat kontrolü ile SL/TP ihlalinde pozisyon kapatma).

### Doğrulama
- Config düzeltmesi sonrası uygulama yeniden başlatıldı
- F_AKSEN SELL 1.00 lot pozisyon başarıyla hibrit yönetime devredildi ✅
- Dashboard'da YÖNETİM sütunu "Manuel" → "Hibrit" olarak güncellendi ✅

---

## Değişiklik Listesi

| # | Dosya | Değişiklik | Sınıf |
|---|-------|-----------|-------|
| 1 | `config/default.json` | `hybrid.native_sltp: true` → `false` | C3 |
| 2 | `docs/USTAT_v5_gelisim_tarihcesi.md` | #78 girişi eklendi | C0 |

**Not:** #77'deki `engine/mt5_bridge.py` değişiklikleri (position ticket çözümleme) henüz commit edilmedi — gelecekte `native_sltp: true` açıldığında gerekli olacak.

---

## Teknik Detaylar

### Etkilenen Akış
```
Dashboard "Hibrite Devret" butonu
  → API: POST /api/hybrid/transfer
    → h_engine.transfer_to_hybrid(ticket, symbol)
      → native_sltp=True ise: mt5_bridge.modify_position(ticket, sl, tp)
        → TRADE_ACTION_SLTP → retcode=10035 ❌
      → native_sltp=False ise: SL/TP bellek+DB'de tutulur ✅
        → _check_software_sltp() her 10sn fiyat kontrolü yapar
```

### Neden native_sltp Çalışmıyor
- GCM Capital MT5 terminal build: **4755**
- `TRADE_ACTION_SLTP` minimum build: **5200** (sunucu tarafı gereksinimi)
- Geçiş planı: MT5 build 5200+ güncellemesi gelince `native_sltp: true` yapılabilir

---

## Versiyon Durumu

| Alan | Değer |
|------|-------|
| Mevcut versiyon | v5.8.0 |
| Versiyon arttırma | Hayır (%5.2 < %10 eşik) |
| Commit hash | `daa4b94` |
| Build | VM'de FUSE izin kısıtlaması — Windows'ta `npm run build` gerekli |

---

## Gelişim Tarihçesi Referansları
- **#78** — Native SL/TP Config Geri Alma (bu oturum)
- **#77** — Exchange Netting Position Ticket Düzeltmesi (bu oturum, henüz commit edilmedi)
- **#1** — Yazılımsal SL/TP Modu (5 Mart 2026, orijinal çözüm)
