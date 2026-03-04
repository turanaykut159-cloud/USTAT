# ÜSTAT v5.1 — Geliştirme Planı

**Tarih:** 2026-03-04
**Aşama:** 1 — Analiz ve Planlama

---

## 1.1 MEVCUT DURUM TESPİTİ

### OĞUL (ogul.py — 2267 satır)

**Gerçek işlev:** Sinyal üretimi (3 strateji) + state-machine emir yönetimi + pozisyon yönetimi

**Açık bulgular (karşılaştırma raporu):**
- P0-1: SL/TP retry yok (mt5_bridge.py:686-701) — pozisyon korumasız kalıyor
- Breakout strength hesabında global BO_VOLUME_MULT kullanılıyor (satır 664), likidite sınıfı değerleri değil
- Breakout trailing sabit BO_TRAILING_ATR_MULT=2.0 kullanıyor (satır 2072/2088), TRAILING_ATR_BY_CLASS değil
- Mean reversion'da trailing stop yok (satır 1963-2008), sadece BB orta bant hedefi
- Bias hesaplanıyor (satır 266-315) ama lot boyutlandırmada kullanılmıyor

**Sinyal analiz raporu zayıflıkları:**
- RSI 30/70 VİOP M15 için çok geniş → 20/80 olmalı
- Keltner Channel eksik → BB/KC squeeze momentum tespiti yapılamıyor
- Williams %R eksik → aşırı bölge teyidi yok
- ADX slope hesaplanmıyor → trend güçleniyor/zayıflıyor ayrımı yok
- Seans zamanlama filtresi yok → açılış/kapanış volatilitesinde sinyal gürültüsü

### BABA (baba.py — 2085 satır)

**Gerçek işlev:** Risk yönetimi + rejim algılama + fake sinyal analizi + kill-switch

**Açık bulgular:**
- P0-2: _close_all_positions retry yok (satır 1541-1590) — L3'te pozisyon açık kalabilir
- P0-3: restore_active_trades yetersiz — startup'ta active_trades kurtarılıyor ama strateji bilgisi eksik olabilir
- HARD_DRAWDOWN_PCT=0.15 (satır 110) → tasarım dokümanı 0.12 diyor
- max_daily_loss=0.02 → 0.018 olmalı (daha muhafazakar)
- Graduated lot schedule yok — kayıp sonrası kademeli lot azaltma mekanizması eksik

### MT5 Bridge (mt5_bridge.py — 1255 satır)

**Kritik sorun:**
- send_order Phase 2 SL/TP (satır 659-701): Tek deneme, başarısızlıkta sadece log → pozisyon korumasız
- close_position (satır 713-793): Tek deneme, retry yok

### İndikatörler (indicators.py — 431 satır)

**Mevcut:** SMA, EMA, RSI, MACD, ADX, BB, ATR
**Eksik:** Keltner Channel, Williams %R, Normalized ATR, BB/KC Squeeze, ADX slope, Hurst Exponent

### Config (default.json)

- Versiyon bilgisi yok
- Ogul/Baba spesifik bölümler yok
- Yeni indikatör parametreleri eksik

---

## 1.2 GELİŞTİRME PLANI

### FAZ A — Düşük Riskli Parametre İyileştirmeleri

| # | Ne | Neden | Nasıl | Dosya:Satır | Risk | Test |
|---|-----|-------|-------|-------------|------|------|
| A1 | RSI 30/70 → 20/80 | VİOP M15'te 30/70 çok geniş, sinyal kalitesi düşük | MR_RSI_OVERSOLD=20.0, MR_RSI_OVERBOUGHT=80.0 | ogul.py:62-63 | Düşük — parametre değişimi | test_ogul.py MR testleri |
| A2 | Breakout strength likidite sınıfı | strength hesabında global BO_VOLUME_MULT var, sınıf bazlı olmalı | vol_mult değişkenini kullan | ogul.py:664 | Düşük — doğru değer zaten orada | test_ogul.py breakout testleri |
| A3 | Breakout trailing likidite bazlı | Sabit 2.0 kullanılıyor, TRAILING_ATR_BY_CLASS tanımlı ama kullanılmıyor | _manage_breakout'ta liq_class oku, TRAILING_ATR_BY_CLASS kullan | ogul.py:2072,2088 | Düşük — dict zaten var | test_ogul.py trailing testleri |
| A4 | Bias-lot entegrasyonu | Bias hesaplanıyor ama lot'a yansımıyor | _calculate_lot'ta bias=="NOTR" ise lot*0.7, ters bias ise lot=0 | ogul.py:1251-1277 | Orta — lot boyutunu etkiler | test_ogul.py lot testleri |
| A5 | MR breakeven trailing | MR'da trailing stop yok, BB mid'e ulaşımda aniden kapanıyor | %50+ kâr → SL'yi entry'e çek (breakeven) | ogul.py:1963-2008 | Düşük — ek koruma | test_ogul.py MR trailing testleri |

### FAZ B — Yeni İndikatörler

| # | Ne | Nereye | Neden | Bağımlılıklar |
|---|-----|--------|-------|---------------|
| B1 | Keltner Channel | indicators.py | BB/KC squeeze tespiti, volatilite bazlı kanal | EMA + ATR fonksiyonları (mevcut) |
| B2 | BB/KC Squeeze | indicators.py | Sıkışma → patlama momentum sinyali | BB + KC fonksiyonları |
| B3 | Williams %R | indicators.py | RSI alternatifi, aşırı bölge teyidi | Yok |
| B4 | Normalized ATR | indicators.py | Farklı fiyat seviyelerinde karşılaştırılabilir volatilite | ATR (mevcut) |
| B5 | ADX Slope | indicators.py | Trend güçleniyor mu zayıflıyor mu | ADX (mevcut) |
| B6 | Hurst Exponent | indicators.py | Trend/mean-reversion ayrımı | Yok |

### FAZ C — Mimari İyileştirmeler

| # | Ne | Neden | Nasıl | Risk |
|---|-----|-------|-------|------|
| C1 | Seans zamanlama filtresi | Açılış (09:45-10:15) ve kapanış (17:15-17:45) volatilitesinde sinyal gürültüsü | _generate_signal başına zaman kontrolü ekle, bu dönemlerde strength*0.5 | Düşük |
| C2 | Squeeze entegrasyonu | Sıkışma sonrası breakout kalitesi daha yüksek | _check_breakout'a squeeze durumu ekle, squeeze varsa strength bonus | Orta — yeni indikatör bağımlılığı |
| C3 | Williams %R teyidi | RSI + W%R çift onay = daha güvenilir sinyal | _check_mean_reversion'a W%R kontrolü ekle | Düşük — ek filtre |

### BABA GELİŞTİRMELERİ

| # | Ne | Neden | Nasıl | Dosya:Satır | Risk |
|---|-----|-------|-------|-------------|------|
| P0-1 | SL/TP 3-retry + force close | Pozisyon SL/TP'siz açık kalıyor | mt5_bridge.py'de 3 deneme + başarısızlıkta pozisyon kapat | mt5_bridge.py:659-701 | Yüksek — emir mantığı |
| P0-2 | L3 close_all 3-retry | L3'te pozisyon açık kalabilir | _close_all_positions'a per-ticket 3 retry | baba.py:1541-1590 | Yüksek — kapanış mantığı |
| P0-3 | active_trades startup recovery | Restart'ta strateji bilgisi eksik, trailing_sl kaybolur | restore_active_trades'i zenginleştir, DB'den strateji+regime oku | ogul.py:2214-2267 | Orta |
| R1 | max_daily_loss 0.02→0.018 | Daha muhafazakar risk | Sabit değiştir | baba.py:sabitler, risk.py:21 | Düşük |
| R2 | HARD_DRAWDOWN 0.15→0.12 | Tasarım dokümanı tutarlılığı | Sabit değiştir | baba.py:110, risk.py:30 | Düşük |
| R3 | Graduated lot schedule | Kayıp sonrası kademeli azaltma | 1 kayıp: lot*0.75, 2 kayıp: lot*0.5, 3 kayıp: cooldown | baba.py calculate_position_size | Orta |

---

## 1.3 UYGULAMA SIRASI

1. **indicators.py** — Yeni indikatörler (bağımlılık yok, diğer tüm değişikliklerden bağımsız)
2. **mt5_bridge.py** — P0-1 SL/TP retry (kritik güvenlik)
3. **baba.py** — P0-2, R1, R2, R3 (risk parametreleri)
4. **models/risk.py** — RiskParams güncelleme
5. **ogul.py** — Faz A + Faz C (sinyal iyileştirmeleri)
6. **config/default.json** — Tüm yeni parametreler
7. **engine/__init__.py** — VERSION
8. **api/schemas.py + routes** — API güncellemeleri
9. **tests/** — Yeni testler + mevcut düzeltmeler
10. **docs/** — Changelog + rapor

---

## 1.4 RISK DEĞERLENDİRMESİ

| Değişiklik | Etki Alanı | Geri Alma |
|-----------|------------|-----------|
| RSI 20/80 | Sadece MR sinyal üretimi | Sabiti geri al |
| SL/TP retry | Emir akışı tamamı | retry kodu sil |
| L3 retry | Kill-switch akışı | retry kodu sil |
| Graduated lot | Tüm lot hesaplamaları | schedule kodu sil |
| Yeni indikatörler | Bağımsız modül, entegre edilene kadar etkisiz | Dosya geri al |
| Seans filtresi | Sinyal üretimi | guard kodu sil |

Her değişiklik bağımsız geri alınabilir.
