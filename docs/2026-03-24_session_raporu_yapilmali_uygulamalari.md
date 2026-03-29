# Oturum Raporu — YAPILMALI Uygulamaları

**Tarih:** 2026-03-24
**Konu:** #57 audit raporundaki 3 "YAPILMALI" maddenin uygulanması
**Commit:** `34e89f0`

---

## Yapılan İşler

### 1. Ağırlıklı Oylama Tiebreaker (🔴 YÜKSEK → ✅ Tamamlandı)

- **Dosya:** `engine/ogul.py` → `_get_voting_detail()`
- **Problem:** buy_votes == sell_votes durumunda w_buy/w_sell hesaplanıyor ama kullanılmıyordu → NOTR
- **Çözüm:** Tiebreaker bloku eklendi — eşitlikte ağırlıklı skor farkı ≥ 1.0 ise yön belirlenir
- **Minimum eşik:** 1.0 puan fark (zayıf tiebreak'ler önlendi)
- **Satır:** ~925-935 arası

### 2. RSS Haber Provider (🟡 ORTA → ✅ Tamamlandı)

- **Dosya:** `engine/news_bridge.py` → `RSSProvider(NewsProvider)`
- **Mimari:** `requests` + `xml.etree.ElementTree` — ek bağımlılık yok
- **Varsayılan feed'ler:** Bloomberg HT piyasa, borsa, doviz RSS
- **Config:** `config/default.json` → `news.rss_feeds[]`
- **Aktivasyon:** `"provider": "rss"` veya `"provider": "all"`
- **Güvenlik özellikleri:**
  - seen_guids deduplikasyon (aynı haber tekrar gelmez)
  - max_seen = 5000 (bellek sınırı, aşılırsa temizlenir)
  - timeout = 8s per feed
  - RFC 2822 tarih parse (email.utils)

### 3. Birim Test Altyapısı (🟡 ORTA → ✅ Tamamlandı)

- **Dosya:** `tests/test_unit_core.py`
- **Framework:** pytest
- **Sonuç:** 57/57 PASSED (0.36s)
- **Test sınıfları:**
  - `TestNormalizeTurkish` (8 test) — İ→i, combining dot, boş string
  - `TestDetectCategory` (13 test) — Jeopolitik/Ekonomik/Sektörel/Şirket/Genel
  - `TestMatchSymbols` (7 test) — THY, Akbank, çoklu sembol, büyük/küçük harf
  - `TestRSSProvider` (12 test) — is_available, parse_date, dedup, mock fetch
  - `TestVotingTiebreaker` (10 test) — Tüm karar yolları, eşik sınırları
  - `TestConstants` (7 test) — Keyword listeleri tutarlılık doğrulaması

## Değişen Dosyalar

| Dosya | Değişiklik | Satır |
|-------|-----------|-------|
| `engine/ogul.py` | Tiebreaker mantığı | +11 |
| `engine/news_bridge.py` | RSSProvider sınıfı + docstring | +121 |
| `config/default.json` | rss_feeds listesi | +5 |
| `tests/test_unit_core.py` | Yeni dosya — birim testler | +494 |
| `docs/USTAT_v5_gelisim_tarihcesi.md` | #58 girişi | +33 |

## Versiyon Durumu

- **Mevcut:** v5.7.0
- **Değişiklik oranı:** ~125 satır / ~68.886 toplam = %0.18
- **Karar:** Eşik altı (%10) — versiyon artırılmadı

## Build Durumu

Syntax check: ✅ OK (ogul.py, news_bridge.py)
Test: ✅ 57/57 PASSED

## Commit

```
34e89f0 feat: audit YAPILMALI uygulamaları — tiebreaker, RSS provider, birim testler (#58)
```
