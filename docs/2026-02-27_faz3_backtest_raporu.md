# USTAT v5.0 - Faz 3 Backtest Sonuc Degerlendirmesi

**Tarih:** 2026-02-27
**Veri:** 24,295 M15 bar (2025-12-01 -> 2026-02-27, ~3 ay, 0226 vadesi)
**Sermaye:** 100,000 TRY (backtest baslangic)

---

## 1. PER-SEMBOL KIRILIM

### A Sinifi (Yuksek Likidite)

| Sembol   | Islem | WR%   | PnL        | PF   | Sharpe | MaxDD |
|----------|-------|-------|------------|------|--------|-------|
| F_THYAO  | 124   | 46.8% | +1,517     | 1.15 | 0.06   | 1.8%  |
| F_AKBNK  | 104   | 43.3% | +3         | 1.00 | 0.00   | 0.8%  |
| F_ASELS  | 124   | 50.8% | +5,267     | 1.36 | 0.13   | 2.5%  |
| F_TCELL  | 86    | 40.7% | +206       | 1.06 | 0.02   | 1.2%  |
| F_PGSUS  | 111   | 45.0% | +2,071     | 1.35 | 0.12   | 1.6%  |
| **TOPLAM** | **549** | **45.3%** | **+9,064** | **1.18** | **0.07** | **2.5%** |

### B Sinifi (Orta Likidite)

| Sembol   | Islem | WR%   | PnL        | PF   | Sharpe | MaxDD |
|----------|-------|-------|------------|------|--------|-------|
| F_HALKB  | 122   | 35.2% | -1,450     | 0.60 | -0.18  | 1.6%  |
| F_GUBRF  | 87    | 41.4% | +405       | 1.02 | 0.01   | 6.5%  |
| F_EKGYO  | 94    | 34.0% | -616       | 0.58 | -0.22  | 0.7%  |
| F_SOKM   | 92    | 43.5% | -15        | 0.99 | -0.00  | 0.4%  |
| F_TKFEN  | 74    | 40.5% | +126       | 1.04 | 0.02   | 0.8%  |
| **TOPLAM** | **469** | **38.9%** | **-1,549** | **0.85** | **-0.07** | **6.5%** |

### C Sinifi (Dusuk Likidite)

| Sembol   | Islem | WR%   | PnL        | PF   | Sharpe | MaxDD  |
|----------|-------|-------|------------|------|--------|--------|
| F_OYAKC  | 87    | 32.2% | -615       | 0.53 | -0.25  | 0.6%   |
| F_BRSAN  | 84    | 33.3% | -9,385     | 0.74 | -0.13  | 13.2%  |
| F_AKSEN  | 86    | 38.4% | -877       | 0.75 | -0.11  | 1.3%   |
| F_ASTOR  | 109   | 47.7% | +1,742     | 1.19 | 0.07   | 1.4%   |
| F_KONTR  | 8     | 50.0% | +43        | 1.84 | 0.26   | 0.0%   |
| **TOPLAM** | **374** | **40.3%** | **-9,092** | **0.84** | **-0.03** | **13.2%** |

---

## 2. SENARYO KARSILASTIRMASI

| Senaryo                    | Islem | WR%   | PnL      | PF   | Sharpe | MaxDD |
|----------------------------|-------|-------|----------|------|--------|-------|
| Trend Follow (A sinifi)    | 549   | 45.3% | +9,064   | 1.18 | 0.07   | 2.5%  |
| Mean Reversion (tumu)      | 1392  | 41.5% | -1,577   | 1.01 | -0.01  | 13.2% |
| Breakout (A+B)             | 1018  | 42.1% | +7,515   | 1.02 | -0.01  | 6.5%  |
| Kombinasyon (tumu)         | 1392  | 41.5% | -1,577   | 1.01 | -0.01  | 13.2% |

**ONEMLI NOT:** BacktestRunner tum stratejileri birlikte calistirir (rejime gore otomatik gecis).
Senaryolar arasi fark sembol listesinden kaynaklanir, strateji izolasyonundan degil.

---

## 3. SEMBOL SINIFLANDIRMASI

### YESIL — Acik ust (PF >= 1.10, pozitif Sharpe)
- **F_ASELS**: PF=1.36, Sharpe=0.13 — en iyi performans
- **F_PGSUS**: PF=1.35, Sharpe=0.12 — cok guclu
- **F_ASTOR**: PF=1.19, Sharpe=0.07 — C sinifi ama basarili
- **F_THYAO**: PF=1.15, Sharpe=0.06 — istikrarli

### SARI — Marjinal (PF 0.95-1.10, Sharpe ~0)
- **F_TCELL**: PF=1.06, Sharpe=0.02 — hafif ustunluk
- **F_TKFEN**: PF=1.04, Sharpe=0.02 — hafif ustunluk
- **F_GUBRF**: PF=1.02, Sharpe=0.01 — neredeyse nötr
- **F_AKBNK**: PF=1.00, Sharpe=0.00 — sifir ustunluk
- **F_SOKM**: PF=0.99, Sharpe=-0.00 — sifir ustunluk

### KIRMIZI — Acik kayipli (PF < 0.80, negatif Sharpe)
- **F_HALKB**: PF=0.60, Sharpe=-0.18 — surekli kayip
- **F_EKGYO**: PF=0.58, Sharpe=-0.22 — en kotu PF
- **F_OYAKC**: PF=0.53, Sharpe=-0.25 — en kotu Sharpe
- **F_BRSAN**: PF=0.74, Sharpe=-0.13, MaxDD=13.2% — felaket drawdown
- **F_AKSEN**: PF=0.75, Sharpe=-0.11 — belirgin kayip

### GRI — Yetersiz veri
- **F_KONTR**: 8 islem — istatistiksel olarak anlamsiz

---

## 4. KOK NEDEN ANALIZI

### Neden B/C sinifi kayip veriyor?
1. **Dusuk likidite**: Spread maliyeti toplam PnL'in buyuk kismini yer
2. **Az bar verisi**: Bazi semboller (F_KONTR: 325, F_TKFEN: 1471) yeterli veri uretemiyor
3. **F_BRSAN ozel durum**: 84 islemde -9,385 TRY kayip + %13.2 MaxDD.
   Diger sembollerden farkli olarak catissal buyuklukte kayip.
   Muhtemel neden: contract_size farki veya asiri volatilite

### Neden runner strateji izole edemiyor?
- BacktestRunner rejime gore strateji atiyor (TREND -> trend_follow, RANGE -> mean_reversion, BREAKOUT -> breakout)
- Tum stratejiler ayni runner'da aktif — belirli bir stratejiyi kapatmak icin runner degisikligi gerekli
- Bu nedenle Senaryo 2 (Mean Rev) = Senaryo 4 (Kombinasyon) = ayni sonuc

---

## 5. WALK-FORWARD DURUMU

**DURUM: YAPILAMADI**

| Gereksinim | Mevcut | Sonuc |
|------------|--------|-------|
| IS penceresi | 4 ay | - |
| OOS penceresi | 2 ay | - |
| Minimum pencere | 3 adet | - |
| Minimum veri | 10 ay | 3 ay |
| **Karar** | - | **VERI YETERSIZ** |

Walk-forward optimizasyon icin en az 10 ay (ideal 12+) M15 verisi gerekli.
Mevcut 3 aylik veri (0226 vadesi) bunu karsılamiyor.

**Oneri:** Yeni vade doneminde (0526) 6+ ay veri birikiminden sonra walk-forward calistirilabilir.

---

## 6. KARARLAR VE ONERILER

### A. Sembol Havuzu Guncelleme

| Karar | Semboller | Aksiyon |
|-------|-----------|---------|
| **KALSIN** | F_THYAO, F_ASELS, F_PGSUS, F_ASTOR | Top 5 aday havuzunda kalir |
| **IZLE** | F_TCELL, F_AKBNK, F_GUBRF, F_TKFEN, F_SOKM | Kalir ama 0526 vadesi sonunda tekrar degerlendirilir |
| **CIKAR** | F_HALKB, F_EKGYO, F_OYAKC | Top 5 havuzundan cikarilmali (PF < 0.60) |
| **CIKAR** | F_BRSAN, F_AKSEN | Cikarilmali (F_BRSAN: %13.2 DD felaket) |
| **VERI BEKLE** | F_KONTR | 8 islem yeterli degil, veri biriksin |

### B. Strateji Parametreleri

| Parametre | Mevcut | Oneri | Gerekce |
|-----------|--------|-------|---------|
| EMA_FAST | 20 | Ayni kalsin | A sinifi iyi calisiyor |
| EMA_SLOW | 50 | Ayni kalsin | Degistirmek icin yeterli veri yok |
| BO_VOLUME_MULT | 1.5-3.0 (likiditeye gore) | Ayni kalsin | Faz 2.2 iyilestirmesi yeni |
| BO_TRAILING_ATR_MULT | 2.0 | Ayni kalsin | Faz 2.1 degisikligi yeni |
| risk_per_trade | %1 | Ayni kalsin | MaxDD kontrol altinda |

### C. Sistem Limitleri

| Limit | Oneri | Gerekce |
|-------|-------|---------|
| max_concurrent | 5 | Ayni kalsin |
| max_lot_per_contract | 5 | Ayni kalsin |
| margin_reserve_pct | %30 | Ayni kalsin |

### D. Sonraki Adimlar

1. **0526 vadesi baslangicinda** sembol havuzunu guncelle (KIRMIZI sembolleri cikar)
2. **3 ay sonra** (Mayis 2026): Tekrar backtest calistir, walk-forward dene
3. **6 ay sonra** (Agustos 2026): Tam walk-forward optimizasyon
4. **BacktestRunner iyilestirmesi**: Strateji izolasyonu ekle (runner'a strategy_filter parametresi)

---

## 7. RISK UYARISI

- Bu backtest **3 aylik tek vade** verisine dayanir — istatistiksel guvenilirlik DUSUK
- Walk-forward dogrulamasi yapilamamistir — overfitting riski YUKSEK
- Canli islem sonuclari backtest'ten FARKLI olacaktir (slippage, likidite, timing)
- **Oneri:** Faz 1/2 kod iyilestirmeleri canli sisteme alinsin, parametre degisiklikleri icin daha fazla veri beklenmeli
