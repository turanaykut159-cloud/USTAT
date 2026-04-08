# Oturum Raporu — Haber Entegrasyonu

**Tarih:** 2026-03-23
**Konu:** MT5 Economic Calendar → NewsBridge → BABA/OĞUL Pipeline
**Commit:** a7a3c82
**Versiyon:** v5.7 (değişmedi — %5.35 < %10)
**Build:** Başarılı (0 hata)

---

## Yapılan İş Özeti

MT5 Economic Calendar verilerini otomatik olarak BABA (risk yönetimi) ve OĞUL (sinyal üretimi) motorlarına aktaran uçtan uca haber pipeline'ı kuruldu. Sistem tamamen otonom çalışır, manuel müdahale gerektirmez.

Pipeline akışı: MT5 Calendar API → MQL5 Service Script → JSON dosya → MT5FileProvider → NewsBridge → SentimentAnalyzer → NewsCache → BABA/OĞUL API → Dashboard UI

---

## Değişiklik Listesi (Dosya Bazında)

### Yeni Dosyalar (2287 satır)
| Dosya | Satır | Açıklama |
|-------|-------|----------|
| mql5/Services/UstatNewsService.mq5 | 276 | MT5 Calendar JSON export service |
| mql5/KURULUM.md | 97 | MQL5 kurulum rehberi |
| engine/news_bridge.py | 1330 | NewsBridge, MT5FileProvider, SentimentAnalyzer, NewsCache, PreMarketBriefing |
| api/routes/news.py | 175 | REST endpoint'leri: /status, /active, /briefing |
| desktop/src/components/NewsPanel.jsx | 157 | Haber Akışı UI bileşeni |
| desktop/src/components/NewsPanel.css | 252 | NewsPanel stilleri |
| restart_all.bat | — | API + Engine yeniden başlatma |
| start_agent.vbs | — | Claude Bridge Agent başlatma |
| ustat_agent.py | — | Windows-side agent |

### Değiştirilen Dosyalar (755 ekleme, 355 silme)
| Dosya | Değişiklik |
|-------|-----------|
| engine/main.py | NewsBridge/PreMarketBriefing init + motor döngüsü entegrasyonu |
| engine/baba.py | should_trigger_olay(), get_lot_multiplier(), get_news_warnings() |
| engine/utils/signal_engine.py | SE2 10. kaynak: haber sinyali |
| api/server.py | News router mount |
| api/schemas.py | NewsEvent, NewsBriefing, NewsStatus şemaları |
| api/deps.py | news_bridge DI |
| api/routes/live.py | TickSnapshot fix + WS haber push |
| api/routes/trades.py | İşlem geçmişi endpoint iyileştirmeleri |
| api/routes/health.py | Haber sistemi sağlık kontrolleri |
| config/default.json | news_bridge konfigürasyonu (max_age: 3600s) |
| Dashboard.jsx | NewsPanel entegrasyonu, REST polling (10sn), kart sıralaması |
| api.js | getNewsStatus(), getNewsActive() |
| TopBar.jsx | Haber durumu göstergesi |
| health_check.py | Haber sistemi kontrolleri (refactor) |

---

## Teknik Detaylar ve Kanıtlar

### MQL5 Service Script
- `#property service` tipi — MT5 arka planda çalıştırır
- `CalendarValueHistory()` API ile TRY/USD/EUR ekonomik takvim verisi
- Her 10 saniyede Common\Files\ustat_news.json dosyasına yazar
- FILE_ANSI encoding (Windows-1254 locale)

### NewsBridge Mimarisi
- **MT5FileProvider**: JSON dosyayı okur, Windows-1254 fallback encoding
- **SentimentAnalyzer**: Başlık bazlı NLP sentiment skoru (-1.0 ↔ +1.0)
- **NewsCache**: TTL bazlı cache (max_age: 3600s), importance bazlı confidence boost
- **PreMarketBriefing**: 09:30-09:50 arası otomatik gece analizi, risk skoru (0-100)

### BABA Entegrasyonu
- `should_trigger_olay()`: sentiment < -0.7 → OLAY rejimi
- `get_lot_multiplier()`: Olumsuz haberlerde lot azaltma
- `get_news_warnings()`: Erken uyarı listesi

### OĞUL Entegrasyonu
- SE2 10. kaynak: sentiment > +0.5 ve confidence > %70 → BUY sinyali

### Çözülen 6 Hata
1. MQL5 sector_name derleme hatası
2. Windows-1254 encoding hatası
3. Cooldown batch engeli (MT5 muafiyeti)
4. TTL erken expire (300s → 3600s)
5. Chrome WebSocket code 1006 (REST polling fallback)
6. TickSnapshot attribute error (tüm WS push'u kırıyordu)

---

## Versiyon Durumu

- Toplam değişiklik: 3397 satır
- Toplam kod tabanı: 63478 satır
- Oran: %5.35 (< %10 eşiği)
- **Versiyon artmadı** — v5.7 olarak devam ediyor

---

## Commit

```
a7a3c82 feat: haber entegrasyonu — MT5 Calendar → NewsBridge → BABA/OĞUL pipeline
26 files changed, 3772 insertions(+), 355 deletions(-)
```

## Build Sonucu

```
✓ 721 modules transformed
✓ built in 8.01s — 0 HATA
```
