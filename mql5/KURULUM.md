# ÜSTAT v5.7.1 — MQL5 Haber Servisi Kurulum Kılavuzu

## Genel Bakış

Bu servis MT5'teki Economic Calendar verilerini `ustat_news.json` dosyasına yazar.
Python tarafındaki `MT5FileProvider` bu dosyayı her 10 saniyede okur ve haberleri
BABA/OĞUL motorlarına iletir.

```
MT5 Calendar → UstatNewsService.mq5 → ustat_news.json → MT5FileProvider → NewsBridge → BABA/OĞUL
```

## Dosyalar

| Dosya | Konum | Açıklama |
|-------|-------|----------|
| `UstatNewsService.mq5` | `mql5/Services/` | MQL5 servis kaynak kodu |
| `ustat_news.json` | `%APPDATA%\MetaQuotes\Terminal\Common\Files\` | Çıktı dosyası |

## Kurulum Adımları

### 1. MQL5 Dosyasını Kopyala

```
mql5/Services/UstatNewsService.mq5
    →
C:\Users\<kullanıcı>\AppData\Roaming\MetaQuotes\Terminal\<terminal_id>\MQL5\Services\UstatNewsService.mq5
```

Veya MetaEditor'da File → Open ile doğrudan aç.

### 2. Derle

MetaEditor'da `Ctrl+F7` ile derle. Hata olmamalı.

### 3. Başlat

MT5 Navigator panelinde:
- Services → UstatNewsService → Sağ tık → Start

### 4. Doğrula

- MT5 Experts sekmesinde `[UstatNews] Servis başlatıldı` logu görünmeli
- `%APPDATA%\MetaQuotes\Terminal\Common\Files\ustat_news.json` dosyası oluşmalı

### 5. ÜSTAT Tarafında Kontrol

```bash
# API üzerinden kontrol
curl http://localhost:8000/api/news/status
```

`provider_count: 1` ve `active_news_count > 0` görünmeli (önemli haber varsa).

## Ayarlar (Service Input Parameters)

| Parametre | Varsayılan | Açıklama |
|-----------|-----------|----------|
| `InpCheckIntervalSec` | 10 | Kontrol aralığı (saniye) |
| `InpLookbackHours` | 24 | Geriye bakış süresi |
| `InpLookaheadHours` | 12 | İleriye bakış (yaklaşan haberler) |
| `InpFileName` | `ustat_news.json` | Çıktı dosya adı |
| `InpCurrencyFilter` | `TRY,USD,EUR` | Takip edilecek para birimleri |
| `InpMinImportance` | 1 | Min önem (0=Yok, 1=Düşük, 2=Orta, 3=Yüksek) |

## Pre-Market Briefing Sistemi

Sabah 09:30-09:50 arasında otomatik çalışır. Gece boyunca biriken haberleri analiz eder:

- **Risk skoru** (0-100): Negatif haberlerin ağırlıklı toplamı
- **Fırsat skoru** (0-100): Pozitif haberlerin ağırlıklı toplamı
- **BABA önerisi**: NORMAL / DİKKAT / TEHLİKE giriş rejimi
- **OĞUL önerisi**: Fırsat sinyali veya bekleme

### API Endpoint'leri

```
GET  /api/news/briefing    → En son briefing sonucu
POST /api/news/briefing    → Manuel briefing tetikle (test için)
```

### Risk Seviyeleri

| Seviye | Risk Skoru | BABA Davranışı |
|--------|-----------|----------------|
| NORMAL | < 30 | Normal giriş |
| DİKKAT | 30-60 | Lot ×0.7, L1 uyarı aktif |
| TEHLİKE | > 60 | Lot ×0.3-0.5, ilk 5dk işlem yok, OLAY hazır |

## Sorun Giderme

| Sorun | Çözüm |
|-------|-------|
| `ustat_news.json` oluşmuyor | MT5'te "Allow DLL imports" ve "Allow algo trading" açık mı? |
| Servis başlamıyor | MetaEditor'da derleme hatası kontrol et |
| `active_news_count: 0` | Para birimi filtresi ve önem seviyesi kontrol et |
| Briefing çalışmıyor | Engine'de `premarket_briefing` attribute'u var mı? API'den manuel tetikle |
