# Oturum Raporu — Gelişim Tarihçesi Audit

**Tarih:** 2026-03-23
**Konu:** Gelişim tarihçesi (#1-#59) üzerinden yapılmadı/atlandı/yarım kaldı analizi
**Commit:** `fe71e55`

---

## Yapılan İş Özeti

Gelişim tarihçesinin 1979 satırlık tamamı (59 giriş) okundu ve kod tabanıyla karşılaştırmalı inceleme yapıldı. Planlanan/önerilen ama uygulanmayan işlemler tespit edildi, her birinin neden o durumda kaldığı araştırıldı.

## Bulgular

### Toplam İncelenen: 16 madde
- ✅ **7 tamamlanmış** (paper_mode, bare except temizliği, window.alert, RISK_BASELINE merkezileştirme, event-driven mimari, ManuelMotor ayrımı, BenzingaProvider kodu)
- ⚠️ **4 yarım kalmış** (BenzingaProvider aktif değil, eski strateji metotları, native_sltp false, MQL5 ANSI)
- ❌ **5 yapılmamış** (ağırlıklı oylama bug, RSS provider, birim test, versiyon geçiş kayıtları, hafta sonu risk)

### Derinlemesine Araştırma Sonuçları (9 madde)

| # | Konu | Önem | Neden Yapılmadı | Karar |
|---|------|------|-----------------|-------|
| 1 | **Ağırlıklı oylama kullanılmıyor** | 🔴 YÜKSEK | Bug — fark edilmemiş. w_buy/w_sell hesaplanıyor ama karar basit oy sayısıyla veriliyor | **YAPILMALI** |
| 2 | **RSS haber provider** | 🟡 ORTA | Öncelik — haber entegrasyonu dün eklendi, önce MT5 pipeline çalıştırıldı | **YAPILMALI** |
| 3 | **Birim test (pytest)** | 🟡 ORTA | Zaman — 18 günde 59 giriş hızında birim test fırsatı bulunamadı | **YAPILMALI (acil değil)** |
| 4 | **native_sltp** | 🟡 ORTA | Broker limiti — GCM MT5 build 4755 < min 5200. Dış bağımlılık | **BEKLET** |
| 5 | **BenzingaProvider** | 🟡 DÜŞÜK-ORTA | Ücretli servis ($99-199/ay) — API key alınmamış | **BEKLET** |
| 6 | **Eski strateji metotları** | 🟢 DÜŞÜK | Bilerek bırakılmış — geri alma sigortası, fonksiyonel risk yok | **BEKLET** |
| 7 | **MQL5 ANSI→UTF-16** | 🟢 DÜŞÜK | Workaround çalışıyor — _normalize_turkish() 100/100 geçti | **VAZGEÇ** |
| 8 | **Hafta sonu risk** | 🟢 DÜŞÜK | Gerek yok — VİOP EOD 17:45 tüm pozisyonları kapatıyor | **GEREK YOK** |
| 9 | **Versiyon geçiş kayıtları** | 🟢 DÜŞÜK | Farklı oturumlarda unutulmuş — kozmetik | **KOZMETİK** |

## Teknik Detay: Ağırlıklı Oylama Bug'ı

**Dosya:** `engine/ogul.py`
**Fonksiyon:** `_get_voting_detail()`
- Satır 876-914: `w_buy`, `w_sell` ağırlıklı skorlar hesaplanıyor (RSI:2.0, EMA:2.5, ATR:1.5, Hacim:1.5, PriceAction:2.5)
- Satır 926: Karar `if buy_votes > sell_votes` — basit oy sayısı kullanılıyor
- Ağırlıklı skorlar `result["weighted_buy"]` ve `result["weighted_sell"]` olarak dict'e yazılıp **karar mekanizmasında kullanılmıyor**
- ATR ve Hacim oyları bağımsız oy değil — sadece mevcut çoğunluğu güçlendiriyor (1-1 durumunda hiç oy vermiyorlar)
- **Sonuç:** RSI-EMA beraberliğinde, Price Action güçlü trend gösterse bile NOTR dönüyor → sinyal kaybı

## Değişiklik Listesi

| Dosya | Değişiklik |
|-------|-----------|
| `docs/USTAT_v5_gelisim_tarihcesi.md` | #57 girişi eklendi (audit sonuçları, 9 madde karar tablosu, ağırlıklı oylama bug detayı) |

## Versiyon Durumu

- **Mevcut:** v5.7.0
- **Değişiklik oranı:** 39 satır / 68.886 toplam = %0.06
- **Karar:** Eşik altı (%10) — versiyon artırılmadı

## Build Durumu

UI değişikliği yok — mevcut build geçerli.

## Commit

```
fe71e55 docs: gelişim tarihçesi audit — yapılmadı/atlandı/yarım kaldı analizi (#57)
```
