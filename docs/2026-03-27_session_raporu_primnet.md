# Oturum Raporu — 27 Mart 2026
## PRİMNET: Prim Bazlı Net Emir Takip Sistemi

### Yapılan İş Özeti

VİOP'un günlük ±%10 fiyat limiti (tavan/taban) üzerine kurulu, prim oranlarına dayalı yeni bir pozisyon yönetim sistemi olan **PRİMNET** tasarlandı, Excel ile simüle edildi ve H-Engine'e implemente edildi.

### PRİMNET Kuralları

- **Faz 1:** Girişten itibaren trailing stop aktif, 1.5 prim mesafe
- **Faz 2:** Kâr ≥ 2.0 prim olduğunda trailing 1.0 prime daralır
- **Hedef Kapanış:** ±9.5 prim (tavan/tabana 0.5 prim kala)
- **EOD:** 17:45 zorunlu kapanış
- **Monotonluk:** Stop sadece ileri gider, geri dönmez

### Değişiklik Listesi

| # | Dosya | Bölge | Değişiklik |
|---|-------|-------|-----------|
| 1 | `engine/h_engine.py` | Sarı | 5 yeni fonksiyon + 5 mevcut fonksiyon düzenleme (~180 satır) |
| 2 | `config/default.json` | Kırmızı | `trailing_mode: "primnet"` + yeni `primnet` config bloğu |
| 3 | `engine/mt5_bridge.py` | Kırmızı | Pozisyon ticket düzeltmesi (entry #77) |
| 4 | `docs/USTAT_v5_gelisim_tarihcesi.md` | C0 | Entry #79 eklendi |

### Teknik Detaylar

**Yeni Fonksiyonlar (h_engine.py):**
- `_get_reference_price(symbol)` — MT5 tavan/taban'dan uzlaşma fiyatı hesaplama
- `_price_to_prim(price, ref)` — Fiyat → prim dönüşümü
- `_prim_to_price(prim, ref)` — Prim → fiyat dönüşümü
- `_calc_primnet_trailing_sl(hp, price)` — Faz 1/2 trailing stop hesaplama
- `_check_primnet_target(hp, price, profit, swap)` — ±9.5 prim hedef kapanışı

**Mimari Kararlar:**
- Mevcut `trailing_mode` sistemi korundu: "atr", "profit", "primnet" seçenekleri
- Geriye uyumlu: trailing_mode değiştirildiğinde eski modlar çalışmaya devam eder
- PRİMNET modunda breakeven fazı atlanır (breakeven_hit=True ile transfer)
- Min/max trailing pct clamp PRİMNET'te uygulanmaz (prim oranları kendi kendini sınırlar)

**Config Eklentisi:**
```json
"primnet": {
  "faz1_stop_prim": 1.5,
  "faz2_activation_prim": 2.0,
  "faz2_trailing_prim": 1.0,
  "target_prim": 9.5
}
```

### Test Sonuçları

7 unit test yazıldı ve geçti:
1. Fiyat↔prim dönüşümü doğruluğu
2. Faz 1 trailing (1.5 prim mesafe)
3. Faz 2 trailing (1.0 prime daralma)
4. SELL yönü hesaplamaları
5. ±9.5 prim hedef kapanışı
6. Stop monotonluk koruması
7. Faz regresyon koruması (Faz 2'den 1'e dönüşte stop geri gitmez)

### Versiyon Durumu

- **Mevcut:** v5.8.0
- **Değişim oranı:** %5.87 (< %10 eşiği)
- **Karar:** Versiyon artırılmadı

### Commit

```
5f892ad feat: PRİMNET prim-bazlı pozisyon yönetim sistemi (#79)
```

### Bekleyen İşler

- `npm run build` Windows'ta çalıştırılmalı (bu oturumda UI değişikliği yok, acil değil)
- PRIMNET_Sistem.xlsx dosyası untracked (referans doküman, commit opsiyonel)
- Canlı piyasada PRİMNET ilk test: Pazartesi 31 Mart 2026
