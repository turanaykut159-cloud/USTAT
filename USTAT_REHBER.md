# ÜSTAT v5.0 — Detayli Kullanim ve Calisma Rehberi

---

## 1. Sistem Nedir?

USTAT, VIOP (Vadeli Islem ve Opsiyon Piyasasi) pay vadeli kontratlarda **algoritmik islem yapan** bir masaustu uygulamasidir. GCM Capital uzerinden MetaTrader 5 terminaline baglanarak calisir.

**Temel felsefe:** *Once sermayeyi koru, sonra kazan.*

Sistem uc ana modulden olusur:

| Modul | Gorev | Benzetme |
|-------|-------|----------|
| **USTAT** | Hangi kontratlarla islem yapilacagini secer (Top 5) | Komutan — strateji belirler |
| **BABA** | Risk yonetimi + piyasa durumu tespiti (rejim) | Kalkan — zardan korur |
| **OGUL** | Sinyal uretimi + emir gonderimi | Silah — islemi yapar |

**Kural:** BABA her zaman OGUL'dan once calisir. Risk uygun degilse OGUL sinyal uretmez.

---

## 2. Izlenen 15 VIOP Kontrati

Kontratlar likidite siniflarina ayrilmistir (dusuk sinif = daha siki risk):

| Sinif | Kontratlar | Spread Toleransi |
|-------|-----------|-----------------|
| **A** (Yuksek likidite) | F_THYAO, F_AKBNK, F_ASELS, F_TCELL, F_HALKB | En dusuk |
| **B** (Orta likidite) | F_PGSUS, F_GUBRF, F_EKGYO, F_SOKM, F_TKFEN, F_OYAKC, F_BRSAN, F_AKSEN | Orta |
| **C** (Dusuk likidite) | F_ASTOR, F_KONTR | En yuksek |

---

## 3. Nasil Baslar?

### Baslatma Adimlari
1. USTAT ikonuna tiklanir — **Electron uygulamasi** hemen acilir (2-3 sn)
2. **Kilit ekrani** gosterilir — MT5 arka planda baslatilir
3. OTP (tek kullanimlik sifre) girisi istenir
4. MT5 baglantisi saglaninca — **Dashboard**'a gecilir
5. **Arka planda:**
   - API sunucusu (port 8000) baslatilir
   - Vite dev server (port 5173) baslatilir
   - Python Engine calismaya baslar

### Teknik Baslatma Zinciri (start_ustat.py)

```
Temizlik (eski process'ler) --> API baslat --> Vite baslat --> Electron baslat
```

### Kapanis Zinciri

```
Kullanici "Cikis" --> Electron before-quit --> api.pid oku --> API process oldur
--> Engine durur --> MT5'e hicbir sinyal gitmez
```

**Onemli:** USTAT kapandiginda MT5 acik kalabilir — onu bagimsiz kullanmaya devam edebilirsiniz. Ama USTAT kapaliyken MT5'e hicbir otomatik emir gitmez.

---

## 4. Ana Dongu — Her 10 Saniyede Neler Olur?

Engine her 10 saniyede bir "cycle" calistirir. Siralama sabittir, degistirilemez:

```
+-----------------------------------------------------+
|  CYCLE (her 10 saniye)                               |
|                                                      |
|  1. MT5 Heartbeat — baglanti saglikli mi?            |
|     |                                                |
|  2. Veri Guncelleme — 15 kontratin fiyat/hacim/      |
|     spread verileri cekilir (M1, M5, M15, H1)        |
|     |                                                |
|  3. BABA Cycle — rejim tespiti + erken uyarilar +    |
|     fake sinyal analizi + kill-switch                |
|     |                                                |
|  4. BABA Risk Kontrolu — gunluk/haftalik/aylik       |
|     zarar limitleri, korelasyon, floating loss       |
|     |                                                |
|  5. USTAT Top 5 — en iyi 5 kontrati sec             |
|     |                                                |
|  6. OGUL — sinyal uret + emir yonet + trailing stop  |
|     (risk kapaliysa yeni sinyal uretmez ama          |
|      mevcut emirleri yonetmeye devam eder)           |
|     |                                                |
|  7. Cycle Loglama — tum kararlar SQLite'a yazilir    |
+-----------------------------------------------------+
```

---

## 5. Piyasa Rejimleri (BABA)

BABA her cycle'da piyasanin hangi durumda oldugunu tespit eder:

### TREND Rejimi
- **Tespit:** ADX > 25 + EMA mesafesi artiyor + son 5 barin 4'u ayni yonde
- **Risk carpani:** 1.0 (tam kapasite)
- **Aktif strateji:** Trend Follow
- **Anlami:** Piyasa net bir yonde ilerliyor, trend takip stratejisi calisir

### RANGE Rejimi
- **Tespit:** ADX < 20 + Bollinger bandi genisligi ortalamanin %80'inden dar
- **Risk carpani:** 0.7 (lot %30 azaltilir)
- **Aktif stratejiler:** Mean Reversion + Breakout
- **Anlami:** Piyasa yatay, ortalamaya donus veya kirilim beklenir

### VOLATILE Rejimi
- **Tespit:** ATR > ortalamanin 2 kati VEYA spread > normalin 3 kati VEYA %2+ fiyat hareketi
- **Risk carpani:** 0.25 (lot cok dusuk)
- **Aktif strateji:** HICBIRI — tum sinyaller durur
- **Anlami:** Piyasa cok oynak, islem yapmak tehlikeli

### OLAY Rejimi
- **Tespit:** TCMB/FED karar gunu VEYA USD/TRY %2+ hareket VEYA vade son 2 gun
- **Risk carpani:** 0.0 (sifir — islem yok)
- **Aktif strateji:** SISTEM PAUSE
- **Anlami:** Dis etken var, hicbir islem yapilmaz

---

## 6. Top 5 Secimi (USTAT)

Her gun 09:15'te baslayip 30 dakikada bir guncellenen puanlama sistemi. 15 kontrat arasindan en iyi 5'i secilir:

### Puanlama Kriterleri

| Kriter | Agirlik | Aciklama |
|--------|---------|----------|
| Teknik sinyal gucu | %35 | EMA, ADX, RSI, MACD, Bollinger Band uyumu |
| Hacim kalitesi | %20 | Guncel hacim / 20 gunluk ortalama orani |
| Spread durumu | %15 | Dusuk spread = yuksek skor |
| Tarihsel basari | %20 | Son 30 gunde o kontrat + rejim kombinasyonunda basari |
| Volatilite uyumu | %10 | ATR/fiyat oraninin mevcut rejime uygunlugu |

### Normalizasyon
Winsorization (1. ve 99. percentile) + Min-Max 0-100 olcekleme.

### Filtreler (Top 5'e giremez)
- **Ortalama filtresi:** Genel ortalamanin altinda kalanlar elenir
- **Vade gecisi:** Son 3 gun yeni islem yok, son 1 gun mevcut pozisyon kapatilir, yeni vadede 2 gun gozlem
- **Haber/bilanco:** TCMB/FED --> OLAY, bilanco +-1 gun --> engel, KAP --> durdur, manuel --> gun boyu deaktif

---

## 7. Sinyal Stratejileri (OGUL)

### Strateji 1: TREND FOLLOW
- **Ne zaman:** TREND rejiminde
- **Giris:** EMA(20) x EMA(50) kesisimi + ADX > 25 + MACD histogrami 2 bar ayni isaret
- **Onay:** M15 giris + H1 zaman diliminde onay
- **Stop Loss:** 1.5 x ATR
- **Take Profit:** 2 x ATR
- **Trailing Stop:** 1.5 x ATR (fiyat lehine gittikce SL yukari cekilir)

### Strateji 2: MEAN REVERSION (Ortalamaya Donus)
- **Ne zaman:** RANGE rejiminde
- **Giris:** RSI(14) asiri bolge (< 30 veya > 70) + Bollinger Band'a temas + ADX < 20
- **Stop Loss:** BB bandi +- 1 ATR
- **Take Profit:** BB orta bandi

### Strateji 3: BREAKOUT (Kirilim)
- **Ne zaman:** RANGE rejiminde (kirilim beklentisi)
- **Giris:** 20-bar en yuksek/dusuk kirilimi + hacim > ortalamanin 1.5 kati + ATR genisleme
- **Stop Loss:** Range orta noktasi
- **Take Profit:** %100 range genisligi

### Rejim - Strateji Eslemesi

```
TREND    --> Trend Follow [AKTIF]     Mean Reversion [KAPALI]   Breakout [KAPALI]
RANGE    --> Trend Follow [KAPALI]    Mean Reversion [AKTIF]    Breakout [AKTIF]
VOLATILE --> HEPSI KAPALI
OLAY     --> SISTEM PAUSE
```

---

## 8. Emir State Machine

Bir sinyal uretildiginde su asamalardan gecer:

```
SIGNAL --> PENDING --> SENT --> FILLED --> ... --> CLOSED
  |          |         |        |                   |
  |          |         |        |                   +-- Pozisyon kapandi
  |          |         |        +-- Emir doldu, pozisyon acildi
  |          |         +-- MT5'e gonderildi
  |          +-- Risk onayi bekleniyor
  +-- Sinyal uretildi
```

- **Timeout:** Limit emir 5 saniye dolmazsa iptal edilir
- **Max Slippage:** 0.5 x ATR (asilirsa emir reddedilir)
- **Max Lot:** Kontrat basina 1.0 lot (test sureci)
- **Max Esanli Pozisyon:** 5 (test sureci)

---

## 9. Risk Yonetimi Katmanlari (BABA)

### A. Zarar Limitleri

| Limit | Esik | Aksiyon | Sifirlama |
|-------|------|---------|-----------|
| Gunluk zarar | %2 | Tum islemler durur | Ertesi gun 09:30 |
| Haftalik zarar | %4 | Lot %50 azaltilir | Pazartesi 09:30 |
| Aylik zarar | %7 | Sistem durur | Manuel onay gerekli |
| Max Drawdown | %10 | Tam kapanis | Manuel onay |
| Hard Drawdown | %15 | Tam kapanis + acil | Manuel onay |

### B. Diger Risk Kurallari
- **3 ust uste kayip:** 4 saat soguma suresi (cool-down)
- **Floating loss %1.5:** Yeni islem engeli (mevcut kayip cok yuksek)
- **Gunluk max islem:** 5 (fazlasi engellenir)
- **Tek islem riski:** Max %2 sermaye
- **Risk per trade:** %1 sermaye (varsayilan)
- **Teminat ayirma:** %20 (margin reserve)

### C. Korelasyon Korumasi
- Max 3 pozisyon ayni yonde
- Max 2 pozisyon ayni sektorde ayni yonde
- Endeks agirlik skoru < 0.25

### D. Erken Uyari Sistemi

| Tetikleyici | A Sinifi | B Sinifi | C Sinifi |
|-------------|----------|----------|----------|
| Spread patlamasi | 3x | 4x | 5x |
| Ani fiyat hareketi | %1.5 | %2.0 | %3.0 |
| Hacim patlamasi | 5x | 5x | 5x |
| USD/TRY soku (5dk) | %0.5 | %0.5 | %0.5 |

### E. Kill-Switch Seviyeleri

| Seviye | Tetikleyici | Aksiyon |
|--------|------------|--------|
| **L1** | Kontrat anomalisi (spread, fiyat, hacim) | O kontrat durdurulur |
| **L2** | Risk limiti / 3 kayip / OLAY rejimi | Tum sistem pause |
| **L3** | Manuel + onay / DD %10+ / flash crash | Tum pozisyonlar kapatilir + sistem durur |

### F. Fake Sinyal Analizi
Acik pozisyonlar surekli kontrol edilir:
- Hacim / 20-bar ortalama < 0.7 --> +1 puan (dusuk hacim)
- Diger katmanlar da skoru artirabilir
- Toplam skor >= 3 --> pozisyon kapatilir (sahte hareket tespit edildi)

---

## 10. Islem Saatleri

| Saat | Olay |
|------|------|
| 09:15 | Top 5 secimi baslar (30 dakikada bir guncellenir) |
| 09:45 | Islem penceresi acilir (sinyal uretimi baslar) |
| 17:45 | Islem penceresi kapanir (tum pozisyonlar kapatilir — EOD) |

**Not:** Hafta sonu ve resmi tatil gunlerinde sistem islem yapmaz.

---

## 11. Veri Pipeline

Her cycle'da MT5'ten cekilen veriler:

| Veri | Frekans | Aciklama |
|------|---------|----------|
| OHLCV barlari | M1, M5, M15, H1 | Tum 15 kontrat icin |
| Tick / spread | Her 10 saniye | Canli fiyat + alis-satis farki |
| Risk snapshot | Her 10 saniye | Equity, bakiye, margin durumu |

**Temizleme kurallari:**
- Gap: Bar arasi zaman bosluklari tespit ve loglanir
- Outlier: z-score > 5 olan barlar reddedilir
- Eksik veri: 3+ ardisik eksik bar --> o kontrat deaktif edilir

### Teknik Indikatorler
- **EMA:** 9 (hizli) ve 21 (yavas) — rejim + sinyal icin
- **RSI:** 14 periyot — asiri alim/satim tespiti
- **MACD:** 12/26/9 — momentum onay
- **ADX:** 14 periyot — trend gucu
- **Bollinger Bands:** 20 periyot, 2 standart sapma
- **ATR:** 14 periyot — volatilite olcumu

---

## 12. Uygulama Arayuzu (UI Sayfalari)

### Kilit Ekrani (LockScreen)
- MT5 OTP girisi
- MT5 baglanti durumu (canli gosterge)
- Baglanti saglaninca otomatik Dashboard'a gecis

### Dashboard (Ana Ekran)
- **Ust kisim:** 4 ozet kart — Toplam Islem, Basari Orani, Net K/Z, Profit Factor
- **Orta sol:** Equity egrisi (alan grafik)
- **Orta sag:** Gunluk K/Z cubuk grafigi
- **Alt sol:** Son 5 islem tablosu
- **Alt sag:** Aktif rejim + Top 5 kontrat listesi
- **Canli guncelleme:** WebSocket ile equity ve durum anlik guncellenir

### Islem Gecmisi (TradeHistory)
- Tamamlanan tum islemler (MT5'ten senkronize edilir)
- Sembol, yon, giris/cikis fiyat-zaman, lot, K/Z, komisyon, swap
- Donem filtresi: Son Ay, Son 3 Ay, Son 6 Ay, Tumu
- Ozet istatistikler: Toplam islem, basari orani, net K/Z, profit factor

### Acik Pozisyonlar (OpenPositions)
- Anlik acik pozisyonlar
- Floating K/Z durumu
- Lot, giris fiyati, anlik fiyat, SL/TP seviyeleri

### Risk Yonetimi (RiskManagement)
- Gunluk/haftalik/aylik zarar durumu (progress bar ile)
- Kill-switch seviyesi
- Mevcut rejim bilgisi
- Korelasyon durumu

### Performans (Performance)
- Detayli performans metrikleri
- Donemsel grafik ve istatistikler
- Strateji bazinda basari orani

### Ayarlar (Settings)
- Sistem konfigurasyonu
- Risk parametreleri

---

## 13. MT5 Islem Gecmisi Senkronizasyonu

Engine basladiginda otomatik olarak MT5'teki son 90 gunluk islem gecmisini veritabanina aktarir:

1. MT5'ten tum deal'ler cekilir
2. Deal'ler position_id ile gruplanir
3. IN (giris) ve OUT (cikis) deal'ler eslestirilir
4. Agirlikli ortalama giris/cikis fiyatlari hesaplanir
5. PnL, komisyon, swap toplanir
6. Daha once aktarilmis pozisyonlar tekrar eklenmez (mt5_position_id ile dedup)
7. Izlenen 15 kontrat disindaki semboller de dahil edilir

**Not:** Bu senkronizasyon her engine baslatildiginda otomatik calisir. Yeni islemler bir sonraki baslatmada aktarilir.

---

## 14. Guvenlik Mekanizmalari

| Durum | Sistem Tepkisi |
|-------|---------------|
| MT5 baglantisi koptu | 5 deneme reconnect, basarisiz --> sistem durur |
| Ekonomik takvim erisilemez | Otomatik OLAY rejimi (guvenli taraf) |
| Disk/DB hatasi | 3 ardisik hata --> sistem durur |
| Veri anomalisi | O kontrat deaktif edilir |
| USTAT kapatildi | API + Engine oldurulur, MT5'e sinyal gitmez |
| MT5 kapali (heartbeat) | Engine MT5'i yeniden ACMAZ, sadece bekleme |
| VOLATILE rejim | Tum sinyaller durur, sadece mevcut pozisyon yonetilir |
| OLAY rejimi | Sistem tamamen pause |

### Fail-Safe Prensipleri
- Suphe durumunda islem YAPMA (guvenli taraf)
- Her karar loglanir (SQLite + dosya loglari)
- Manuel onay gerektiren durumlar otomatik gecilmez
- Sermaye koruma her zaman onceliklidir

---

## 15. Konfigürasyon Varsayilanlari

```
Engine:
  Cycle araligi         : 10 saniye
  Veri lookback          : 500 bar

Risk:
  Gunluk max zarar       : %2
  Max drawdown           : %10
  Risk per trade         : %1
  Max acik pozisyon      : 5
  Max korelasyon         : 3

MT5:
  Terminal yolu          : C:\Program Files\GCM MT5 Terminal\terminal64.exe
  API port               : 8000

Indikatorler:
  EMA hizli/yavas        : 9 / 21
  RSI periyot            : 14
  MACD                   : 12 / 26 / 9
  ADX periyot            : 14
  BB periyot / std       : 20 / 2.0
  ATR periyot            : 14
```

---

## 16. Tipik Islem Akisi (Ornek Senaryo)

```
09:15  USTAT Top 5 secimi: F_THYAO, F_AKBNK, F_ASELS, F_PGSUS, F_TCELL
       (15 kontrattan 5 kritere gore en yuksek puanli 5'i secildi)

09:45  Islem penceresi acildi
       Engine her 10 saniyede cycle calismaya baslar

09:50  Cycle #30:
       - BABA: F_THYAO icin TREND rejimi tespit etti (ADX=28, EMA artiyor)
       - Risk kontrolu: Gunluk zarar %0.3 — UYGUN
       - OGUL: F_THYAO TREND_FOLLOW sinyali uretti --> BUY
         (EMA(20) > EMA(50) + MACD pozitif + ADX > 25)

09:50  Emir akisi:
       SIGNAL --> PENDING (risk onayi bekleniyor)
       PENDING --> SENT (MT5'e limit emir gonderildi)
       SENT --> FILLED (1 lot @ 185.50 TL doldu)
       SL: 183.70 TL (1.5 x ATR)
       TP: 189.10 TL (2 x ATR)

10:30  Trailing stop guncellendi:
       Fiyat 187.00 TL'ye yukseldi --> SL 185.20 TL'ye cekildi

12:00  TP'ye ulasildi:
       FILLED --> CLOSED @ 189.10 TL
       K/Z: +360 TL (komisyon ve swap sonrasi)

15:30  BABA: F_AKBNK icin VOLATILE rejim tespit etti
       (ATR normalin 2.5 kati, spread 4x patlamis)
       --> F_AKBNK icin tum sinyaller durduruldu
       --> Mevcut pozisyon varsa sadece yonetim devam ediyor

17:45  EOD (End of Day):
       Kalan acik pozisyonlar piyasa emri ile kapatildi
       Gunluk rapor: 3 islem, 2 kar, 1 zarar, net +520 TL
```

---

## 17. Hizli Basvuru

### Baslatma / Kapatma

| Islem | Yontem |
|-------|--------|
| Uygulamayi baslat | USTAT ikonuna tikla |
| Konsoldan baslat | `python start_ustat.py` |
| Gizli baslat (konsol yok) | `wscript start_ustat.vbs` |
| Uygulamayi kapat | Sistem tepsisi --> sag tik --> "Cikis" |

### Onemli Dosyalar

| Dosya | Aciklama |
|-------|----------|
| C:\USTAT\startup.log | Baslatma adimlarinin logu |
| C:\USTAT\api.log | API sunucu loglari |
| C:\USTAT\vite.log | Vite dev server loglari |
| C:\USTAT\api.pid | Calisan API'nin process ID'si |
| C:\USTAT\database\trades.db | SQLite veritabani |
| C:\USTAT\config\default.json | Varsayilan konfigürasyon |

### Durum Cubugu (Alt Bar)

Uygulamanin alt barinda her zaman gorunen bilgiler:
- **Sistem durumu:** CALISIYOR / DURDURULDU
- **Faz:** Mevcut cycle fazi
- **MT5 baglanti:** Yesil (bagli) / Kirmizi (bagli degil)
- **Bakiye / Equity / Floating:** Anlik hesap bilgileri
- **Gunluk K/Z:** O gunun toplam kar/zarar durumu

---

## 18. Sik Sorulan Sorular

**S: USTAT kapatinca MT5 de kapaniyor mu?**
H: Hayir. MT5 bagimsiz calisir. USTAT kapaninca sadece otomatik islem durur.

**S: Ayni trade iki kez senkronize edilir mi?**
H: Hayir. Her trade'in mt5_position_id'si kontrol edilir, zaten varsa atlanir.

**S: VOLATILE rejimde acik pozisyon ne olur?**
H: Mevcut pozisyonlar yonetilmeye devam eder (SL/TP/trailing). Yeni sinyal uretilmez.

**S: Gunluk zarar limiti asilinca ne olur?**
H: Tum yeni islemler durur. Ertesi gun 09:30'da otomatik sifirlanir.

**S: Kill-switch L3 tetiklenince ne yapmam lazim?**
H: Tum pozisyonlar otomatik kapatilir. Sistemi tekrar baslatmak icin manuel onay gerekir.

**S: Internet koparsa ne olur?**
H: MT5 heartbeat basarisiz olur, 5 deneme yapilir, basarisizsa sistem durur. Acik pozisyonlar MT5'te SL/TP ile korunur.

---

*Bu rehber USTAT v5.0 kod tabanindan dogrudan dogrulanarak olusturulmustur.*
*Her parametre, esik ve davranis gercek kaynak kodundaki degerleri yansitmaktadir.*
*Tarih: 2026-02-22*
