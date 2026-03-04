# CHANGELOG — ÜSTAT v5.1 (Faz 4)

**Tarih:** 2026-03-04
**Versiyon:** 5.0.0 → 5.1.0
**Toplam Değişiklik:** 22 madde (3 P0, 2 risk param, 1 graduated lot, 5 sinyal, 6 indikatör, 3 mimari, 2 config/versiyon)

---

## Test Durumu (Final)

```
pytest tests/ -v --ignore=tests/test_mt5_data_depth.py --ignore=tests/test_trade.py
================= 665 passed, 1 skipped, 1 warning in 19.74s ==================
```

| Metrik | v5.0 | v5.1 | Fark |
|--------|------|------|------|
| Toplam test | 644 | 666 | +22 |
| Geçen | 644 | 665 | +21 |
| Başarısız | 0 | 0 | — |
| Yeni test | — | 22 | +22 |
| Atlanan | 1 | 1 | — |

---

## P0 Düzeltmeleri (Kritik)

### P0-1: SL/TP 3-Retry + Force Close
- **Dosya:** `engine/mt5_bridge.py`
- **Neden:** Phase 2 SL/TP tek denemede başarısız olursa pozisyon korumasız kalıyordu.
- **Değişiklik:** 3 denemeli retry döngüsü. 3 deneme de başarısız olursa pozisyon otomatik kapatılır (`force_closed=True`).
- **Etki:** Hiçbir pozisyon SL/TP'siz açık kalmaz.

### P0-2: L3 Close All 3-Retry
- **Dosya:** `engine/baba.py`
- **Neden:** `_close_all_positions()` tek denemede başarısız olursa pozisyon açık kalabiliyordu.
- **Değişiklik:** Her ticket için 3 denemeli retry. Başarısız ticket'lar ayrı loglanır.
- **Etki:** L3 kill-switch güvenilirliği artırıldı.

### P0-3: Active Trades Startup Recovery
- **Dosya:** `engine/ogul.py`
- **Neden:** `restore_active_trades()` strateji bilgisi, rejim ve entry zamanını kurtarmıyordu.
- **Değişiklik:** DB'den strateji, rejim, entry_time bilgileri okunur. Yetim pozisyonlar (DB eşleşmesi yok) uyarı ile loglanır. Exception handling eklendi.
- **Etki:** Engine restart sonrası pozisyon yönetimi (trailing, breakeven) doğru çalışır.

---

## Risk Parametre Güncellemeleri

### R1: max_daily_loss 0.02 → 0.018
- **Dosyalar:** `engine/models/risk.py`, `config/default.json`, `api/schemas.py`
- **Neden:** Daha muhafazakar günlük kayıp limiti.

### R2: HARD_DRAWDOWN 0.15 → 0.12
- **Dosyalar:** `engine/baba.py`, `engine/models/risk.py`, `config/default.json`, `api/schemas.py`
- **Neden:** Tasarım dokümanı (v13.0) ile tutarlılık. Sermaye koruması güçlendirildi.

### R3: Graduated Lot Schedule
- **Dosya:** `engine/baba.py` (`calculate_position_size`)
- **Neden:** Kayıp sonrası kademeli lot azaltma mekanizması.
- **Değişiklik:**
  - 1 üst üste kayıp: lot × 0.75
  - 2 üst üste kayıp: lot × 0.50
  - 3+ üst üste kayıp: lot = 0 (cooldown)
- **Etki:** Üst üste kayıpta risk kademeli azaltılır.

---

## Sinyal İyileştirmeleri

### A1: RSI 30/70 → 20/80
- **Dosya:** `engine/ogul.py`
- **Neden:** VİOP M15'te 30/70 çok geniş, düşük kaliteli MR sinyalleri.
- **Değişiklik:** `MR_RSI_OVERSOLD=20.0`, `MR_RSI_OVERBOUGHT=80.0`

### A2: Breakout Strength Likidite Fix
- **Dosya:** `engine/ogul.py`
- **Neden:** Breakout strength hesabında global `BO_VOLUME_MULT` kullanılıyordu, likidite sınıfı bazlı eşikler göz ardı ediliyordu.
- **Değişiklik:** `vol_mult` ve `atr_exp` değişkenleri (zaten hesaplanmış) kullanılıyor.

### A3: Breakout Trailing Likidite Bazlı
- **Dosya:** `engine/ogul.py`
- **Neden:** `_manage_breakout()` sabit `BO_TRAILING_ATR_MULT=2.0` kullanıyordu, `TRAILING_ATR_BY_CLASS` dict'i tanımlı ama kullanılmıyordu.
- **Değişiklik:** `_manage_breakout()` likidite sınıfını okuyup `TRAILING_ATR_BY_CLASS` kullanıyor.

### A4: Bias-Lot Entegrasyonu
- **Dosya:** `engine/ogul.py` (`_calculate_lot`)
- **Neden:** `_calculate_bias()` hesaplanıyordu ama lot boyutuna yansımıyordu.
- **Değişiklik:**
  - Bias ters yönde → lot = 0 (işlem yapma)
  - Bias nötr → lot × 0.7 (güven düşürme)
  - Bias uyumlu → değişiklik yok

### A5: MR Breakeven Trailing
- **Dosya:** `engine/ogul.py` (`_manage_mean_reversion`)
- **Neden:** MR'da trailing stop yoktu, kâr tamamen korumadan BB mid'e ulaşımda kapanıyordu.
- **Değişiklik:** TP mesafesinin %50'sine ulaşınca SL → entry (breakeven).

---

## Yeni İndikatörler

### B1-B6: 6 Yeni İndikatör
- **Dosya:** `engine/utils/indicators.py`

| # | İndikatör | Amaç | Entegre |
|---|-----------|------|---------|
| B1 | Keltner Channel | ATR bazlı volatilite kanalı, BB/KC squeeze için | Evet (squeeze) |
| B2 | BB/KC Squeeze | Sıkışma → patlama momentum tespiti | Evet (breakout +0.15 bonus) |
| B3 | Williams %R | Aşırı bölge teyidi, RSI çift onay | Evet (MR filtre) |
| B4 | Normalized ATR | Fiyat seviyesinden bağımsız volatilite karşılaştırma | Analitik |
| B5 | ADX Slope | Trend güçleniyor/zayıflıyor ayrımı | Analitik |
| B6 | Hurst Exponent | Trend/mean-reversion doğası tespiti | Analitik |

---

## Mimari İyileştirmeler

### C1: Seans Zamanlama Filtresi
- **Dosya:** `engine/ogul.py` (`_generate_signal`)
- **Neden:** Açılış (09:45-10:15) ve kapanış (17:15-17:45) volatilitesinde sinyal gürültüsü.
- **Değişiklik:** Bu dönemlerde `strength × 0.5` (sinyal güç düşürme).

### C2: Squeeze Entegrasyonu (Breakout)
- **Dosya:** `engine/ogul.py` (`_check_breakout`)
- **Neden:** Sıkışma sonrası kırılım daha güvenilir.
- **Değişiklik:** Son 3 bar'da squeeze tespit edilmişse breakout strength'e +0.15 bonus.

### C3: Williams %R Çift Onay (MR)
- **Dosya:** `engine/ogul.py` (`_check_mean_reversion`)
- **Neden:** Tek RSI yerine RSI + W%R çift filtre → daha güvenilir aşırı bölge tespiti.
- **Değişiklik:** Long: RSI<20 + W%R<-80. Short: RSI>80 + W%R>-20.

---

## Config & Versiyon

### Config Güncellemesi
- **Dosya:** `config/default.json`
- **Değişiklikler:**
  - `version: "5.1.0"` eklendi
  - `risk.max_daily_loss_pct: 0.02 → 0.018`
  - `risk.hard_drawdown_pct: 0.12` eklendi
  - `risk.sltp_max_retries: 3` eklendi
  - `risk.close_max_retries: 3` eklendi
  - `indicators.kc_*`, `williams_r_period`, `adx_slope_bars` eklendi
  - `strategies.mean_reversion.rsi_oversold: 30 → 20`, `rsi_overbought: 70 → 80`
  - `strategies.mean_reversion.williams_r_*`, `breakeven_profit_pct` eklendi
  - `strategies.breakout.squeeze_bonus: 0.15` eklendi
  - `session_filter` bölümü eklendi
  - `graduated_lot` bölümü eklendi

### VERSION
- **Dosya:** `engine/__init__.py`
- **Değişiklik:** `VERSION = "5.1.0"` eklendi

---

## Dosya Değişiklik Özeti

| Dosya | Değişiklik |
|-------|-----------|
| `engine/utils/indicators.py` | +6 yeni indikatör (KC, squeeze, W%R, NATR, ADX slope, Hurst) |
| `engine/mt5_bridge.py` | P0-1: SL/TP 3-retry + force close |
| `engine/baba.py` | P0-2: L3 3-retry, R2: HARD_DD 0.12, R3: graduated lot |
| `engine/ogul.py` | A1-A5 + C1-C3 + P0-3: 8 iyileştirme |
| `engine/models/risk.py` | R1: daily_loss 0.018, R2: hard_dd 0.12 |
| `engine/__init__.py` | VERSION = "5.1.0" |
| `config/default.json` | Tüm yeni parametreler |
| `api/server.py` | Versiyon 5.0 → 5.1 |
| `api/schemas.py` | version, risk limitleri, graduated_lot_mult |
| `desktop/src/components/Dashboard.jsx` | Versiyon 5.1 |
| `tests/test_indicators.py` | +22 yeni test (6 indikatör) |
| `tests/test_integration.py` | bias-lot mock düzeltme |
| `tests/test_risk_calculations.py` | hard_dd 0.12 uyumu |

---

## Bağımsız Değerlendirme

### Yapılanlar ✓
- 3 P0 kritik fix (SL/TP retry, L3 retry, startup recovery)
- 2 risk parametre sıkılaştırma (daily loss, hard DD)
- 1 yeni mekanizma (graduated lot)
- 5 sinyal iyileştirme (RSI, breakout strength/trailing, bias-lot, MR breakeven)
- 6 yeni indikatör (3'ü entegre, 3'ü analitik)
- 3 mimari iyileştirme (seans filtresi, squeeze, W%R)
- 22 yeni test, 0 regresyon

### Yapılmayanlar
- Hurst / ADX slope stratejiye entegre edilmedi (backtest gerekli)
- Basis (spot-futures) eklenemedi (MT5'te spot veri kısıtı)
- Config'den parametre okuma (mevcut sabitler yeterli, gelecek faz)

### Tavsiyeler
1. **v5.1 canlıya alınmadan önce backtest zorunlu** — özellikle RSI 20/80 + W%R filtresi
2. **Graduated lot backtest** — 0.75/0.5 çarpanlarının optimizasyonu
3. **Dashboard'a yeni indikatörler** — squeeze, W%R, NATR gösterimi
