# USTAT v5.1 — GELISIM TARIHCESI

**Olusturulma Tarihi:** 2026-02-23
**Son Guncelleme:** 2026-03-04
**Amac:** Projenin kurulumundan itibaren tum degisikliklerin, eklemelerin ve cikartmalarin kaydi

> Bu dosya her gelistirme sonrasi guncellenecek canli bir gelistirme gunlugudur.

---

## KAYIT FORMATI

Her kayit su bilgileri icerir:
- **Tarih/Saat** — Degisikligin yapildigi zaman
- **Commit** — Git commit hash (kisa)
- **Baslik** — Ne yapildi (ozet)
- **Neden** — Neden yapildi
- **Degisiklikler** — Hangi dosyalarda ne degisti
- **Eklenen/Cikartilan** — Yeni eklenen veya kaldirilan ozellikler

---

## #01 — FABRIKA AYARLARI (Proje Olusturma)

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-02-22 23:16:26 +03:00 |
| **Commit** | `cb2e2e91` |
| **Baslik** | USTAT v5.0 Factory — fabrika ayarlari yedegi |

**Neden:** USTAT v5.0 projesinin ilk kurulumu. Tum moduller, testler ve masaustu uygulamasi sifirdan olusturuldu.

**Eklenenler (91 dosya, 39.930 satir):**
- **Engine (Python trading motoru):**
  - `engine/baba.py` (1.951 satir) — Risk yonetimi + rejim algilama
  - `engine/ogul.py` (1.629 satir) — Sinyal uretimi + emir state-machine
  - `engine/ustat.py` (934 satir) — Strateji yonetimi, Top 5 secim
  - `engine/mt5_bridge.py` (1.125 satir) — MT5 baglanti katmani
  - `engine/database.py` (1.082 satir) — SQLite yonetimi
  - `engine/data_pipeline.py` (606 satir) — Veri cekme/temizleme
  - `engine/main.py` (562 satir) — Ana dongu, 10sn cycle
  - `engine/config.py`, `engine/logger.py` — Konfigurasyon ve loglama
  - `engine/models/` — Veri modelleri (trade, signal, risk, regime)
  - `engine/utils/` — Teknik indikatorler (430 satir), sabitler, zaman yardimcilari
- **API (FastAPI sunucu):**
  - `api/server.py` (151 satir) — Ana FastAPI app
  - `api/schemas.py` (362 satir) — Pydantic semalari
  - `api/deps.py` (74 satir) — Dependency injection
  - `api/routes/` — 11 route dosyasi (status, trades, positions, risk, killswitch, live, top5, account, events, performance)
- **Desktop (Electron + React):**
  - `desktop/main.js` (440 satir) — Electron ana surec
  - `desktop/mt5Manager.js` (550 satir) — MT5 surec yonetimi
  - `desktop/preload.js` (77 satir) — Electron preload
  - `desktop/src/App.jsx` — React ana bilesen
  - `desktop/src/components/` — 10 bilesen (Dashboard, LockScreen, OpenPositions, Performance, RiskManagement, Settings, SideNav, TopBar, TradeHistory)
  - `desktop/src/services/` — api.js, mt5Launcher.js, storage.js
  - `desktop/src/styles/theme.css` (2.628 satir) — Tema dosyasi
  - `desktop/scripts/mt5_automator.py` (433 satir) — MT5 OTP otomasyon
  - `desktop/scripts/otp_teshis.py` (437 satir) — OTP teshis araci
- **Backtest:**
  - 9 dosya (runner, report, monte_carlo, sensitivity, session_model, slippage_model, spread_model, stress_test, walk_forward)
- **Testler:**
  - 8 test dosyasi (test_baba 2.909 satir, test_ogul 2.511 satir, test_ustat 958 satir, test_main 1.047 satir, test_integration 1.420 satir, test_indicators 527 satir, test_data_pipeline, test_mt5_bridge)
- **Kok dosyalar:**
  - `.gitignore`, `CLAUDE.md`, `README.md`, `USTAT_REHBER.md`
  - `requirements.txt`, `package.json`
  - `start_ustat.py`, `start_ustat.bat`, `start_ustat.vbs`
  - `config/default.json`

**Cikartilan:** Yok (ilk commit)

---

## #02 — FACTORY RESET SCRIPTI

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-02-22 23:17:25 +03:00 |
| **Commit** | `fa968fdb` |
| **Baslik** | Factory reset scripti eklendi |

**Neden:** Sistem sorun yasadiginda fabrika ayarlarina donebilmek icin tek tusla sifirlama scripti gerekiyordu.

**Eklenenler:**
- `factory_reset.bat` (173 satir) — Windows bat dosyasi, projeyi fabrika ayarlarina dondurur

**Cikartilan:** Yok

---

## #03 — KILL-SWITCH SIFIRLAMA + RISK BASELINE

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-02-23 12:09:45 +03:00 |
| **Commit** | `d22fed8b` |
| **Baslik** | Kill-switch sifirlama + risk baseline tarihi + UI reset butonu |

**Neden:** Kill-switch aktif kaldiktan sonra sifirlanamiyordu. Risk baseline tarihi yanlisti. UI'dan sifirlama butonu eksikti.

**Degisiklikler (3 dosya, +72 -5 satir):**
- `engine/baba.py` — Kill-switch sifirlama ve risk baseline tarih duzeltmesi (+29 -4)
- `desktop/src/components/TopBar.jsx` — UI'a kill-switch reset butonu eklendi (+26 -1)
- `desktop/src/styles/theme.css` — Reset butonu stilleri (+22)

**Eklenenler:**
- Kill-switch sifirlama fonksiyonu (BABA)
- Risk baseline tarih duzeltmesi
- TopBar'da kill-switch reset butonu

**Cikartilan:** Hatali baseline hesaplama mantigi

---

## #04 — PROJE GELISTIRME DOKUMANLARI

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-02-23 12:12:24 +03:00 |
| **Commit** | `d89d581c` |
| **Baslik** | Proje gelistirme dokumanlari eklendi |

**Neden:** Projenin gecmis surumleri (v10.2, v11, v11.1, v12), elestiri dokumanlari, master plan ve entegrasyon analizi arsivlenmek icin eklendi.

**Eklenenler (15 dosya, +997 satir):**
- `USTAT-PROJE GELISTIRME/` klasoru alti:
  - `BABA-OGUL-USTAT_10.2.docx` — v10.2 dokumani
  - `BABA_OGUL_USTAT_v11.docx` — v11 dokumani
  - `BABA_OGUL_USTAT_v11_1.docx` — v11.1 dokumani
  - `BABA_OGUL_USTAT_v12.docx` — v12 dokumani
  - `V11.0 ELESTIRI/` — 4 elestiri dokumani (GR, GE, DS, CG)
  - `V11.1 ELESTIRI/` — 4 elestiri dokumani (GR, GE, DS, CG)
  - `USTAT_v5_Master_Plan.md` (740 satir)
  - `Ustat_v5_Entegrasyon_Analiz.md` (257 satir)
  - GCM META 5 iletisim gelistirme dokumani

**Cikartilan:** Yok

---

## #05 — DASHBOARD DUZELTMELERI

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-02-23 12:47:44 +03:00 |
| **Commit** | `00a46e5d` |
| **Baslik** | Dashboard duzeltmeleri: baseline filtreleme, risk sayfasi, kontrat deaktivasyonu |

**Neden:** Dashboard'da baseline filtreleme hatali calisiyordu. Risk sayfasi bos geliyordu. Kontrat deaktivasyonu duzgun calismiyordu.

**Degisiklikler (12 dosya, +569 -16 satir):**
- `engine/data_pipeline.py` — Baseline filtreleme duzeltmesi (+37 -1)
- `engine/database.py` — Veritabani sorgu duzeltmesi (+5)
- `api/deps.py` — Yeni dependency eklendi (+6)
- `api/routes/status.py` — Durum API genisletildi (+36 -5)
- `api/routes/performance.py` — Performans API duzeltmesi (+9 -1)
- `api/routes/positions.py` — Pozisyon API duzeltmesi (+3 -1)
- `api/routes/trades.py` — Trade API duzeltmesi (+3 -1)
- `api/schemas.py` — Yeni sema alani (+1)
- `desktop/src/components/Dashboard.jsx` — UI duzeltmeleri (+28 -4)
- `desktop/src/components/RiskManagement.jsx` — Risk sayfasi tamamen yeniden yazildi (+240 -1)
- `desktop/src/services/api.js` — Yeni API cagrilari (+11)
- `desktop/src/styles/theme.css` — Risk sayfasi stilleri (+206)

**Eklenenler:**
- RiskManagement sayfasi tamamen yeniden olusturuldu (240 satir)
- Risk API entegrasyonu
- Baseline filtreleme duzeltmesi

**Cikartilan:** Eski bos RiskManagement sablonu (16 satir)

---

## #06 — TOP 5 FALLBACK DUZELTMESI

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-02-23 12:52:25 +03:00 |
| **Commit** | `c001060a` |
| **Baslik** | Top 5 fallback: duplike sembol ve 5+ satir sorunu duzeltildi |

**Neden:** Top 5 listesinde ayni sembol birden fazla cikiyordu. 5'ten fazla kontrat listeleniyordu.

**Degisiklikler (1 dosya, +10 -3 satir):**
- `api/routes/top5.py` — Duplike sembol filtreleme ve 5 satir limiti eklendi

**Eklenenler:**
- Duplike sembol kontrolu
- Maksimum 5 satir sinirlamasi

**Cikartilan:** Hatali fallback mantigi

---

## #07 — SON ISLEMLER BASELINE FILTRESI + EQUITY FALLBACK

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-02-23 13:12:33 +03:00 |
| **Commit** | `cb2e48e2` |
| **Baslik** | Son Islemler baseline filtresi + Equity karti account fallback |

**Neden:** Son islemler listesinde baseline oncesi kayitlar gorunuyordu. Equity karti account bilgisi alinamadiginda bos geliyordu.

**Degisiklikler (2 dosya, +14 -5 satir):**
- `api/routes/trades.py` — Baseline tarih filtresi eklendi (+5 -1)
- `desktop/src/components/Dashboard.jsx` — Equity karti icin account fallback (+14 -4)

**Eklenenler:**
- Trade listesine baseline tarih filtresi
- Account bilgisi icin fallback mekanizmasi

**Cikartilan:** Filtresiz trade sorgusu

---

## #08 — NETTING MODE UYUMLULUGU

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-02-23 13:56:00 +03:00 |
| **Commit** | `24d1d17a` |
| **Baslik** | Netting mode uyumlulugu: LIMIT retcode + sembol bazli pozisyon eslestirme |

**Neden:** GCM MT5 netting modunda calisiyor. LIMIT emirlerde farkli retcode donuyordu. Pozisyon eslestirme ticket bazli yapiliyordu ama netting'de sembol bazli olmasi gerekiyor.

**Degisiklikler (2 dosya, +36 -15 satir):**
- `engine/mt5_bridge.py` — LIMIT retcode destegi eklendi, hata yonetimi gelistirildi (+14 -3)
- `engine/ogul.py` — Sembol bazli pozisyon eslestirme + netting mode uyumu (+37 -12)

**Eklenenler:**
- LIMIT emir retcode (TRADE_RETCODE_PLACED) destegi
- Sembol bazli pozisyon eslestirme (netting mode)

**Cikartilan:** Ticket bazli pozisyon eslestirme (hedging mode kalintisi)

---

## #09 — TOP 5 SINYAL YONU EKLENDI

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-02-23 14:11:14 +03:00 |
| **Commit** | `f93a5eb5` |
| **Baslik** | Top 5 kontrat listesine sinyal yonu (BUY/SELL/BEKLE) eklendi |

**Neden:** Dashboard'daki Top 5 listesinde kontrat yonu (BUY/SELL/BEKLE) gosterilmiyordu. Kullanici hangi yonde sinyal oldugunu goremiyordu.

**Degisiklikler (5 dosya, +50 -17 satir):**
- `api/deps.py` — OGUL dependency eklendi (+6)
- `api/routes/top5.py` — Sinyal yonu bilgisi eklendi (+10 -1)
- `api/schemas.py` — Yeni sema alani (signal_direction) (+1)
- `desktop/src/components/Dashboard.jsx` — Sinyal yonu gosterimi eklendi (+37 -15)
- `desktop/src/styles/theme.css` — Sinyal yonu renkleri (BUY=yesil, SELL=kirmizi) (+13 -1)

**Eklenenler:**
- Top 5 listesinde BUY/SELL/BEKLE gosterimi
- Renk kodlamasi (BUY=yesil, SELL=kirmizi, BEKLE=gri)

**Cikartilan:** Yok

---

## #10 — DEAKTIVASYON M15/H1 SINIRLAMASI

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-02-23 15:05:50 +03:00 |
| **Commit** | `1b27915e` |
| **Baslik** | Deaktivasyon kontrolunu M15/H1 ile sinirla (M1/M5 sahte tetikleme duzeltmesi) |

**Neden:** Kontrat deaktivasyon kontrolu M1 ve M5 timeframe'lerde sahte tetikleme yapiyordu. Kisa vadeli gurultu yuzunden kontratlar yanlislikla deaktif ediliyordu.

**Degisiklikler (1 dosya, +12 -3 satir):**
- `engine/data_pipeline.py` — Deaktivasyon kontrolu sadece M15 ve H1 timeframe'lerde yapilacak sekilde sinirlandirildi

**Eklenenler:**
- M15/H1 timeframe filtresi (deaktivasyon icin)

**Cikartilan:** M1/M5 timeframe'lerde deaktivasyon kontrolu (sahte tetikleme kaynagi)

---

## #11 — SINYAL YONU GERCEK INDIKATOR ANALIZINDEN OKUMA

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-02-23 15:33:18 +03:00 |
| **Commit** | `e9c588ef` |
| **Baslik** | Top 5 sinyal yonunu pozisyon yerine gercek indikator analizinden oku |

**Neden:** Sinyal yonu mevcut pozisyondan okunuyordu. Ancak pozisyon yoksa yon bilgisi gelmiyor, pozisyon varsa da gercek sinyal degil pozisyon yonunu gosteriyordu.

**Degisiklikler (2 dosya, +9 -5 satir):**
- `api/routes/top5.py` — Sinyal yonunu OGUL indikator analizinden oku (+9 -5)
- `engine/ogul.py` — Indikator analiz fonksiyonu eklendi (+5)

**Eklenenler:**
- Gercek indikator bazli sinyal yonu okuma
- OGUL'da yeni analiz fonksiyonu

**Cikartilan:** Pozisyon bazli sinyal yonu okuma (yanlis bilgi kaynagi)

---

## #12 — TOP 5 YON EGILIMI (BIAS) GOSTERIMI

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-02-23 15:52:04 +03:00 |
| **Commit** | `34b8eb03` |
| **Baslik** | Top 5 yon egilimi (bias) gosterimi + kontrat durumu her zaman gorunur |

**Neden:** Top 5 listesinde sadece anlık sinyal gosteriliyordu ama genel yon egilimi (bias) gorulmuyordu. Ayrica kontrat durumu (aktif/deaktif) her zaman gorunur olmasi gerekiyordu.

**Degisiklikler (4 dosya, +98 -28 satir):**
- `engine/ogul.py` — Bias hesaplama fonksiyonu + coklu timeframe analizi (+68 -4)
- `api/routes/top5.py` — Bias bilgisi API'ye eklendi (+2 -1)
- `desktop/src/components/Dashboard.jsx` — Bias gosterimi + kontrat durumu her zaman gorunur (+40 -9)
- `desktop/src/styles/theme.css` — Bias gosterim stilleri (+16 -3)

**Eklenenler:**
- Coklu timeframe bias hesaplama (OGUL)
- Dashboard'da yon egilimi gosterimi
- Kontrat durumu her zaman gorunur

**Cikartilan:** Sadece anlik sinyal gosterimi (yetersiz bilgi)

---

## #13 — TEST_TRADE PASIF YAPMA + MT5 UYARI ANALIZI (Commit disisi)

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-02-23 ~20:50 +03:00 |
| **Commit** | Henuz commit edilmedi |
| **Baslik** | test_trade.py pasif yapildi + MT5 uyari analizi |

**Neden:** MT5 terminalinde 20:47'de market kapali iken F_KONTR0226N1 satis emri goruldu. Analiz sonucu test_trade.py'nin saat kontrolu olmadan emir gonderebildigi tespit edildi. Test basarili oldugu icin script devre disi birakildi.

**Degisiklikler:**
- `test_trade.py` — Dosyanin basina `sys.exit(0)` eklendi, docstring'e PASIF notu yazildi

**Eklenenler:**
- `docs/2026-02-23_mt5_uyari_analizi.md` — MT5 uyari analiz raporu
- `docs/2026-02-23_talimatlar.md` — Oturum talimatlari
- `docs/USTAT_v5_kod_dokumu_2026-02-23.md` — Tam kod dokumu (100 dosya, 36.175 satir)
- `docs/USTAT_v5_gelisim_tarihcesi.md` — Bu dosya
- `docs/generate_dump.py` — Kod dokumu olusturucu script

**Cikartilan:** test_trade.py calistirilabilirlik ozelligi (sys.exit ile devre disi)

---

## ISTATISTIKLER

| Metrik | Deger |
|--------|-------|
| **Ilk commit** | 2026-02-22 23:16 |
| **Son commit** | 2026-02-23 15:52 |
| **Toplam commit** | 12 |
| **Toplam kaynak dosya** | ~100 |
| **Toplam satir (tahmini)** | ~36.000+ |
| **Proje suresi** | 1 gun (yogun gelistirme) |

---

## BUNDAN SONRAKI KAYITLAR ASAGIYA EKLENECEK

## #14 — FAZ 1: BUG DUZELTMELERI

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-02-27 10:25:00 +03:00 |
| **Commit** | `fb94471` |
| **Baslik** | Faz 1 — Bug duzeltmeleri (netting, sayac, contract_size, bias) |

**Neden:** Canli sistemdeki guvenilirlik sorunlarini gidermek. Netting mode ticket tutarsizligi, gunluk islem sayacinin yanlis zamanda artmasi, sabit CONTRACT_SIZE ile yanlis PnL, risk kapaliyken eski bias gosterimi.

**Degisiklikler (2 dosya, +45 -19 satir):**
- `engine/ogul.py` — _update_fill_price sembol bazli eslestirme, _manage_active_trades tek MT5 cagrisi, increment_daily_trade_count FILLED'a tasindi (3 metoda eklendi), _handle_closed_trade kontrat bazli PnL
- `engine/main.py` — Risk kapaliyken bias guncelleme (Dashboard icin)

**Eklenenler:**
- Sembol bazli pozisyon eslestirme (_update_fill_price)
- pos_by_symbol dict ile MT5 cagri optimizasyonu
- FILLED'da sayac artirma (_advance_sent, _advance_partial, _advance_market_retry)
- get_symbol_info ile kontrat bazli PnL hesaplama
- Risk kapaliyken _calculate_bias cagrisi

**Cikartilan:**
- _execute_signal icindeki increment_daily_trade_count (SENT'te artirma)
- Dongu ici get_positions cagrisi

---

## #15 — FAZ 2: STRATEJI IYILESTIRMELERI

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-02-27 10:30:00 +03:00 |
| **Commit** | `0d32bcc` |
| **Baslik** | Faz 2 — Strateji iyilestirmeleri (breakout, likidite, config) |

**Neden:** Breakout pozisyonlarinda false breakout korumasinin olmamasi, tum kontratlarin ayni parametrelerle degerlendirilmesi, config altyapisinin kullanilmamasi.

**Degisiklikler (3 dosya, +166 -24 satir):**
- `engine/ogul.py` — _manage_breakout false breakout tespiti, BO_TRAILING_ATR_MULT 1.5→2.0, BO_REENTRY_BARS=3, LIQUIDITY_CLASSES, _get_liq_class, _check_breakout likidite bazli, _manage_trend_follow likidite bazli
- `config/default.json` — strategies + liquidity_overrides bolumleri eklendi
- `engine/config.py` — Parse hatasi korumasi, config summary loglama

**Eklenenler:**
- False breakout tespiti (son 3 bar entry gerisine donmusse kapat)
- Likidite sinifi sistemi (A/B/C): 15 kontrat siniflandirildi
- BO_VOLUME_MULT_BY_CLASS, BO_ATR_EXPANSION_BY_CLASS, TRAILING_ATR_BY_CLASS
- Config'de strategies ve liquidity_overrides bolumleri
- Config parse hatasi korumasi (bozuk JSON engine cokertmez)

---

## #16 — FAZ 3: BACKTEST + VADE GECISI

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-02-27 11:30:00 +03:00 |
| **Commit** | (bu commit) |
| **Baslik** | Faz 3 — Backtest senaryolari, vade gecisi, takvim guncellemesi |

**Neden:** Faz 1/2 iyilestirmelerinin performans etkisini olcmek, 0226 vadesi sonunda 0526 vadesi icin sistemi hazirlamak.

**Degisiklikler (5 dosya):**
- `backtest/run_faz3.py` — YENI: 4 senaryo backtest calistiricisi (per-sembol ve senaryo bazli raporlama)
- `engine/baba.py` — VIOP_EXPIRY_DATES 2026 Nisan-Aralik eklendi (9 tarih)
- `engine/utils/time_utils.py` — HOLIDAYS_2026 eklendi, ALL_HOLIDAYS merkezi set, is_market_open guncellendi
- `engine/ustat.py` — Yerel ALL_HOLIDAYS kaldirildi, merkezi import kullanildi
- `docs/2026-02-27_faz3_backtest_raporu.md` — YENI: Detayli backtest analiz raporu

**Eklenenler:**
- Faz 3.1 backtest scripti (4 senaryo, 14 sembol, 3 ay M15 verisi)
- VIOP_EXPIRY_DATES: 2026 Nisan-Aralik (Kurban Bayrami cakismasi dikkate alindi)
- HOLIDAYS_2026 (resmi + dini bayramlar tahmini)
- Merkezi ALL_HOLIDAYS seti (time_utils.py tek kaynak)
- Backtest analiz raporu: sembol siniflandirmasi (YESIL/SARI/KIRMIZI), kararlar

**Sonuclar:**
- Trend Follow (A sinifi): +9,064 TRY, PF=1.18 — EN IYI
- Mean Reversion (tumu): -1,577 TRY, PF=1.01 — NÖTR
- Sorunlu semboller: F_HALKB (PF=0.60), F_EKGYO (PF=0.58), F_OYAKC (PF=0.53), F_BRSAN (DD=13.2%)
- Walk-forward: YAPILAMADI (3 ay vs 10 ay minimum gereksinim)

---

## #11 — Madde 2.2: Sharpe Ratio Yuzde Getiri Duzeltmesi

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-03-03 |
| **Baslik** | Sharpe Ratio TRY → yuzde getiri bazli duzeltme |

**Neden:** Sharpe ratio hesabi TRY cinsinden mutlak gunluk PnL kullaniyordu. Farkli equity buyuklukleri icin ayni TRY PnL farkli yuzde getiri demek. Ornegin 100K TRY hesapta 100 TRY = %0.1, 10K TRY hesapta 100 TRY = %1 — ama eski kod ikisini ayni degerlendiriyordu.

**Degisiklikler (2 dosya):**
- `engine/database.py` — Yeni `get_daily_end_snapshots()` metodu: SQL GROUP BY ile gun bazli son snapshot'i dondurur (verimli, binlerce snapshot yerine gun basina 1 row)
- `api/routes/performance.py` — Sharpe hesabi: snapshot'tan day_start_equity = equity - daily_pnl, yuzde getiri = daily_pnl / day_start_equity, Sharpe bu yuzde getiriler uzerinden hesaplanir

**Eklenenler:**
- `Database.get_daily_end_snapshots()` — gun bazli aggregate risk snapshot metodu
- Yuzde getiri bazli Sharpe ratio hesabi (Madde 1.2 day_start_equity formuluyle tutarli)

**Cikartilan:**
- TRY bazli Sharpe hesabi (mutlak PnL / std, olcege duyarli yanlis hesap)

---

## #12 — Madde 2.3: Equity Egrisi Timestamp Duzeltmesi

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-03-03 |
| **Baslik** | Equity egrisi: limit=500 → gunluk snapshot + saat gosterimi |

**Neden:** Equity egrisi icin `get_risk_snapshots(limit=500)` kullaniliyordu. 10sn'de 1 snapshot × 500 = sadece ~83 dakika veri. Tum noktalar ayni gunde → XAxis'te hep "03.03" tekrarliyordu. Ayrica saat bilgisi gosterilmiyordu.

**Degisiklikler (2 dosya):**
- `api/routes/performance.py` — Equity curve + max drawdown icin ayri `get_risk_snapshots(limit=500)` kaldirildi, yerine Sharpe icin zaten cekilen `daily_snapshots` (get_daily_end_snapshots) kullanildi. Bir DB call eliminate edildi. Kullanilmayan `datetime` import kaldirildi.
- `desktop/src/components/Performance.jsx` — `shortDate()`: "DD.MM" → "DD.MM HH:mm" formatina guncellendi

**Eklenenler:**
- Equity egrisi 30+ gun kapsam (onceki: ~83 dakika)
- XAxis'te anlamli tarih-saat gosterimi

**Cikartilan:**
- `get_risk_snapshots(limit=500)` cagirisi (gereksiz DB sorgusu)
- `from datetime import datetime` (kullanilmiyordu)

---

## #13 — Madde 2.4: WebSocket MT5 Cache Mekanizmasi

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-03-03 |
| **Baslik** | WebSocket: dogrudan MT5 erisimi → DataPipeline cache |

**Neden:** WebSocket her 2 saniyede dogrudan MT5'e 3 senkron cagri yapiyordu (get_account_info, get_positions, get_tick × 5). Engine cycle'i da ayni cagrilari yapiyordu. MT5 Python kutuphanesi thread-safe degil → cakisma riski.

**Degisiklikler (2 dosya):**
- `engine/data_pipeline.py` — `latest_account`, `latest_positions`, `_cache_time` cache alanlari eklendi. `is_cache_stale(max_age_seconds=15)` metodu eklendi. `update_risk_snapshot()` icinde MT5'ten alinan account+positions cache'e yaziliyor.
- `api/routes/live.py` — `_send_all_updates()`: MT5'e dogrudan erisim kaldirildi, `pipeline.latest_account`, `pipeline.latest_positions`, `pipeline.latest_ticks` cache'inden okunuyor. `get_mt5` import kaldirildi, `get_pipeline` eklendi. 15sn stale kontrolu eklendi.

**Eklenenler:**
- DataPipeline cache (account, positions, cache_time)
- `is_cache_stale()` metodu (15sn esik)
- Thread-safe MT5 erisim mimari (tek erisim noktasi: DataPipeline)

**Cikartilan:**
- WebSocket'ten dogrudan MT5 erisimi (get_account_info, get_positions, get_tick)
- `get_mt5` import (live.py'de artik gerekli degil)

---

## #14 — Madde 2.5: Manuel Islem Lot Validasyonu

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-03-03 |
| **Baslik** | Manuel islem: sabit 10 lot → sembol bazli volume_max |

**Neden:** API'de sabit `req.lot > 10` kontrolu vardi. VIOP'ta her sembolun `volume_max` degeri farkli. Sabit limit gercek MT5 limitleriyle uyusmayabilir.

**Degisiklikler (3 dosya):**
- `api/schemas.py` — `ManualTradeCheckResponse`'a `max_lot: float = 0.0` alani eklendi
- `engine/ogul.py` — `check_manual_trade()`: MT5 `get_symbol_info()` ile `volume_max` alinip response'a yaziliyor. `open_manual_trade()`: Sabit `MAX_LOT_PER_CONTRACT` yerine sembol bazli `volume_min/volume_max/volume_step` kontrolu ve yuvarlama eklendi
- `api/routes/manual_trade.py` — Sabit `req.lot > 10` kontrolu kaldirildi, lot validasyonu ogul.py'ye devredildi

**Eklenenler:**
- Sembol bazli lot limiti (MT5 SymbolInfo.volume_max)
- Volume_step yuvarlama (lot miktari adim buyuklugune uygun hale getirilir)
- `max_lot` alani check response'ta (frontend'e gonder)

**Cikartilan:**
- Sabit `req.lot > 10` kontrolu (API katmani)

---

## #15 — Madde 2.6: Config Yoksa Uyari Mekanizmasi

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-03-03 |
| **Baslik** | Config dosyasi yoksa CRITICAL log + event |

**Neden:** Config dosyasi yoksa sessizce bos dict ile devam ediyordu. Kullanici durumdan haberdar olmuyordu.

**Degisiklikler (2 dosya):**
- `engine/config.py` — `_is_loaded` flag eklendi, `is_loaded` property eklendi. Config yoksa WARNING → CRITICAL seviyesine yukseltildi.
- `engine/main.py` — Engine baslarken `config.is_loaded` kontrol, yoksa CONFIG_MISSING event'i loglanir.

**Eklenenler:**
- `Config._is_loaded` flag + `Config.is_loaded` property
- CRITICAL log seviyesi (config bulunamadiginda)
- CONFIG_MISSING event (engine baslatma sirasinda)

**Cikartilan:**
- WARNING log seviyesi (config yoksa)

---

## #16 — Madde 2.7: VIOP Vade Tarihleri Dogrulama

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-03-03 |
| **Baslik** | Engine baslarken VIOP vade tarihlerini is gunu olarak dogrula |

**Neden:** VIOP_EXPIRY_DATES listesindeki tarihler hafta sonuna veya resmi tatile denk gelebilir. Bu durumda vade gecisi/rollover mantigi bozulabilir. Engine baslarken erken uyari verilmeli.

**Degisiklikler (2 dosya):**
- `engine/baba.py` — `validate_expiry_dates()` fonksiyonu eklendi. VIOP_EXPIRY_DATES'teki tarihleri hafta sonu ve ALL_HOLIDAYS'e karsi kontrol eder.
- `engine/main.py` — `start()` metodunda config kontrolundan sonra, MT5 baglantisindan once `validate_expiry_dates()` cagrisi eklendi. Sorun varsa WARNING event loglanir.

**Eklenenler:**
- `validate_expiry_dates()` fonksiyonu (engine/baba.py)
- EXPIRY_DATE_WARNING event tipi (engine baslatma sirasinda)
- Basarili dogrulama icin INFO log mesaji

**Cikartilan:**
- Yok

**Test:** 381 passed, 28 failed (pre-existing). Regresyon yok.
**Tespit:** 2025-03-31 tatil gunune denk geliyor (Ramazan Bayrami).

---

## #17 — Madde 3.1: Tekrarlanan Fonksiyonlari Birlestirme

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-03-03 |
| **Baslik** | _last_valid, _last_n_valid, _nanmean fonksiyonlarini tek noktada birlestirme |

**Neden:** `_last_valid()` 3 dosyada (baba, ogul, ustat) birebir ayni tanimliydi. `_nanmean()` baba'da, `_last_n_valid()` ogul'da. Tekrar = bakim zorluklari.

**Degisiklikler (7 dosya):**
- `engine/utils/helpers.py` — YENI: `last_valid`, `last_n_valid`, `nanmean` fonksiyonlari
- `engine/baba.py` — Import eklendi, yerel `_last_valid` + `_nanmean` tanimlari silindi
- `engine/ogul.py` — Import eklendi, yerel `_last_valid` + `_last_n_valid` tanimlari silindi
- `engine/ustat.py` — Import eklendi, yerel `_last_valid` tanimi silindi
- `tests/test_baba.py` — Import kaynagi `engine.utils.helpers` olarak guncellendi
- `tests/test_ogul.py` — Import kaynagi `engine.utils.helpers` olarak guncellendi
- `tests/test_ustat.py` — Import kaynagi `engine.utils.helpers` olarak guncellendi

**Eklenenler:**
- `engine/utils/helpers.py` (yeni dosya, 3 fonksiyon)

**Cikartilan:**
- 3 dosyadan toplam 5 yerel fonksiyon tanimi (baba: 2, ogul: 2, ustat: 1)

**Test:** 454 passed, 30 failed (28 + 2 pre-existing test_ustat). Regresyon yok.

---

## #18 — Madde 3.2+3.3: Fake Analiz Optimizasyonu + Spread Sabiti

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-03-03 |
| **Baslik** | Fake sinyal analizi frekans azaltma + SPREAD_HISTORY_LEN modul sabiti |

**Neden:** Fake sinyal analizi her 10 sn calisiyordu (gereksiz yuk). _SPREAD_HISTORY_LEN instance degiskeni olmamali, modul sabiti olmali.

**Degisiklikler (1 dosya):**
- `engine/baba.py` — `_cycle_count` eklendi, fake analiz her 3 cycle'da bir (30 sn). `_SPREAD_HISTORY_LEN` instance degiskeni kaldirildi, `SPREAD_HISTORY_LEN` modul sabiti eklendi.

**Test:** 381 passed, 28 failed (pre-existing). Regresyon yok.

---

## #19 — Madde 3.4: Error Handling Standardizasyonu

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-03-03 |
| **Baslik** | MT5 cagrilarinda try/except sarmalama |

**Neden:** ogul.py ve baba.py'de toplam ~21 korumasiz MT5 cagrisi vardi. Herhangi bir MT5 hatasi tum engine'i dusuruyordu.

**Degisiklikler (2 dosya):**
- `engine/ogul.py` — 14+ MT5 cagrisi try/except ile sarildi: cancel_order, close_position, modify_position, get_positions, get_tick. Hatalar loglanir, islem akisi korunur.
- `engine/baba.py` — 7 MT5 cagrisi try/except ile sarildi: get_positions (fake+close_all), close_position (fake+L3), get_tick (USDTRY).

**Eklenenler:**
- Tum korumasiz MT5 cagrilarina try/except + logger.error

**Cikartilan:**
- Yok (mevcut davranis korundu)

**Test:** 381 passed, 28 failed (pre-existing). Regresyon yok.

---

## #20 — Madde 3.5: Database Snapshot Balance Alani

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-03-03 |
| **Baslik** | risk_snapshots tablosuna balance kolonu eklenmesi |

**Neden:** Floating loss hesabinda balance lazim ancak tabloda balance alani yoktu. equity - floating_pnl ile hesap yapiliyordu.

**Degisiklikler (2 dosya):**
- `engine/database.py` — ALTER TABLE ile balance kolonu eklendi (DEFAULT 0). insert_risk_snapshot'a balance parametresi eklendi. Uc okuma metoduna geriye uyumluluk fallback eklendi.
- `engine/data_pipeline.py` — update_risk_snapshot snapshot'ina `account.balance` eklendi.

**Test:** 381 passed, 28 failed (pre-existing). Regresyon yok.

---

## #21 — Madde 3.6: Kapsamli Test Suite

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-03-03 |
| **Baslik** | Risk hesaplama, consecutive loss, cooldown, manuel islem ve peak equity testleri |

**Neden:** Mevcut test suite'i risk fonksiyonlarinin sinir degerlerini, cooldown mekanizmasini, manuel islem kontrol akisini ve peak equity kaliciliğini yeterince test etmiyordu.

**Degisiklikler (4 yeni dosya, +243 satir):**
- `tests/test_risk_calculations.py` (YENI) — _check_hard_drawdown (soft/hard esik, sifir drawdown, DB'den okuma), _check_floating_loss (pozitif/sifir/esik/balance-sifir), _check_weekly_loss (halved flag).
- `tests/test_consecutive_loss.py` (YENI) — _update_consecutive_losses (sifir trade, 3 ust uste kayip, kazanc kirma), cooldown (baslat, sure ici, sure dolma, sifir sayac), cooldown sonrasi sayac (Madde 1.6 dogrulamasi).
- `tests/test_manual_trade.py` (YENI) — check_manual_trade (donus tipi, gecersiz sembol, netting), SL/TP formul dogrulama (BUY/SELL icin 1.5xATR ve 2.0xATR), lot validasyonu (min/max/sifir).
- `tests/test_peak_equity.py` (YENI) — peak equity ilk ayar, yukari guncelleme, asagi koruma, drawdown hesabi, DB'de kalicilik, sifir equity, negatif olmama, hassasiyet.

**Eklenenler:**
- 38 yeni test (12 risk hesaplama + 8 consecutive/cooldown + 10 manuel islem + 8 peak equity)
- Toplam test sayisi: 613 passed (onceki: ~575)

**Cikartilan:**
- Yok

**Test:** 613 passed, 31 failed (pre-existing), 8 errors (MT5 baglanti). 38/38 yeni test PASSED. Regresyon yok.

---

## #22 — Masaustu Uygulamasi Balance Entegrasyonu

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-03-03 |
| **Baslik** | Engine balance verisinin API ve frontend'e yansitilmasi |

**Neden:** Engine tarafinda risk_snapshots'a eklenen balance kolonu API ve frontend'e ulasmiyordu. Kullanici bakiye, equity ve floating K/Z verilerini canli goremiyordu.

**Degisiklikler (7 dosya):**
- `api/schemas.py` — EquityPoint ve RiskResponse modellerine `balance: float = 0.0` eklendi.
- `api/routes/performance.py` — Equity curve dongusunde balance okunuyor ve EquityPoint'e aktariliyor.
- `api/routes/risk.py` — Risk snapshot'tan balance degeri RiskResponse'a eklendi.
- `desktop/src/components/Dashboard.jsx` — Stat kartlari ile pozisyon tablosu arasina "Hesap Durumu" seridi eklendi (Bakiye, Varlik, Floating K/Z, Gunluk K/Z). WebSocket canli veri + REST fallback.
- `desktop/src/components/RiskManagement.jsx` — "Anlik Durum" bolumune Bakiye karti eklendi (4. kart).
- `desktop/src/components/Performance.jsx` — Equity grafikine yesil kesikli balance cizgisi + gradient + legend + tooltip guncellendi.
- `desktop/src/styles/theme.css` — .dash-account-strip ve .pf-chart-legend stilleri eklendi.

**Eklenenler:**
- Dashboard canli hesap durumu seridi (4 metrik, WebSocket 2sn guncelleme)
- Risk sayfasinda Bakiye karti
- Performans equity grafikinde balance cizgisi (yesil, kesikli)
- Chart legend (Equity=mavi, Bakiye=yesil)

**Cikartilan:**
- Yok (mevcut davranis korundu)

**Test:** Backend: 252 passed, 1 failed (pre-existing). Frontend: Vite build basarili (0 hata). Regresyon yok.

---

## #23 — Peak Equity Baseline Validasyonu (Drawdown Fix)

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-03-03 |
| **Baslik** | _calculate_drawdown RISK_BASELINE_DATE filtresi eksikligi duzeltmesi |

**Neden:** peak_equity DB'de 200.000 TRY olarak kayitliydi ancak hicbir gercek snapshot'ta bu deger yoktu (test/gelistirme doneminden kalma). Gercek equity ~14.000 TRY oldugu icin drawdown %93 olarak hesaplaniyor ve Kill-Switch L2 tetikleniyordu. _calculate_drawdown, RISK_BASELINE_DATE filtresi kullanmayan TEK fonksiyondu.

**Kok neden:** Tum risk fonksiyonlari (weekly loss, monthly loss, consecutive losses, trades, performance) RISK_BASELINE_DATE filtresini kullaniyor ancak _calculate_drawdown() kullaNMIyordu. Peak equity DB state tablosunda kalici saklandigi icin eski degerler hic temizlenmiyordu.

**Degisiklikler (1 dosya + DB temizlik):**
- `engine/data_pipeline.py` — `_validate_peak_equity()` metodu eklendi. DataPipeline.__init__ icinde cagrilir. RISK_BASELINE_DATE sonrasi max equity ile stored peak'i karsilastirir, 1.5x asimda sifirlar.
- DB temizlik: 2 anomali snapshot silindi (balance=0, equity=100K/90K — test verisi). peak_equity 200.000 → 14.127,53 olarak duzeltildi.

**Eklenenler:**
- `_validate_peak_equity()` — Engine baslatmada peak equity tutarliligi kontrolu

**Cikartilan:**
- DB'den 2 test snapshot (balance=0, equity 100K ve 90K)

**Etki:** Drawdown %93 → %0.8. Kill-Switch L2 engine yeniden baslatildiginda kalkar. Islem izni acilir.

**Test:** 234 passed, 1 failed (pre-existing). Regresyon yok.

---

## #19 — Dokuman-Kod Karsilastirma Raporu (v13.0)

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-03-04 |
| **Baslik** | BABA_OGUL_Trading_Sistemi_v13.0.docx ile mevcut kod karsilastirmasi |

**Neden:** Canli teste gecis oncesi dokuman ile kod arasindaki uyumsuzluklarin tespiti. Dogrulanmis parametrelerin kayit altina alinmasi.

**Degisiklikler (1 dosya):**
- `USTAT-PROJE GELISTIRME/PROJE GELISTIRME/KARSILASTIRMA_RAPORU.md` — 22 farklilik tespiti (7 kritik, 6 yuksek, 5 orta, 4 dusuk)

**Temel Bulgular:**
- Kontrat havuzu uyumsuz: Dokuman 8, kod 15
- Kill-switch yapisi uyumsuz: Dokuman 5 katman (K0-K4), kod 3 seviye (L1-L3) + OLAY rejimi
- Risk parametreleri farkli: Gunluk kayip %1.8 vs %2, hard drawdown %12 vs %15, cooldown 2h vs 4h
- P0 aciklarin 4/5'i kodda tam kapatilmamis (SL/TP retry yok, hedge yok, startup recover yok, takvim hardcoded)
- Kod fazlaliklari (fake sinyal, korelasyon, manuel islem) guvenligi artirir — silinmemeli, belgelenmeli

**Eklenenler:**
- `KARSILASTIRMA_RAPORU.md` — 10 bolumlu profesyonel analiz raporu

**Cikartilan:**
- Yok

---

## #20 — Ogul Sinyal Motoru Gercek Piyasa Analizi

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-03-04 |
| **Baslik** | Ogul sinyal motorunun VIOP perspektifinden parametrik analizi + guclendirme yol haritasi |

**Neden:** Canli teste gecis oncesi sinyal motorunun gercek piyasa kosullarinda performansini degerlendirmek. Her indikator ve parametre VIOP pay vadeli seans yapisina gore sorgulanmistir.

**Degisiklikler (1 dosya):**
- `docs/2026-03-04_ogul_sinyal_analizi.md` — 7 bolumlu analiz raporu

**Temel Bulgular:**
- EMA(20)/EMA(50) M15'te fazla yavas — EMA(9)/EMA(21) veya adaptif MA onerilir
- ADX(14) cift yumusatma gecikmesi — Hurst Exponent alternatifi onerilir
- RSI 30/70 esikleri 20/80'e sikilastirilmali
- Keltner Channel eklenmesi en yuksek degerli tamamlayici
- 5 kod zayifligi tespit edildi (breakout strength likidite, trailing stop, MR trailing, bias-lot, seans zamanlama)
- 3 fazli guclendirme yol haritasi ciziildi (A: optimizasyon, B: yeni indikatorler, C: mimari)

**Eklenenler:**
- `docs/2026-03-04_ogul_sinyal_analizi.md`

**Cikartilan:**
- Yok

---

## #21 — USTAT v5.1: Sinyal Motoru + Risk Guclendirilmesi (Faz 4)

| Bilgi | Deger |
|-------|-------|
| **Tarih** | 2026-03-04 12:00:00 +03:00 |
| **Commit** | (beklemede) |
| **Baslik** | USTAT v5.0 → v5.1: 22 iyilestirme (3 P0 + 6 indikator + 8 sinyal/mimari + 3 risk + 2 config) |

**Neden:** Karsilastirma raporu (v13.0) ve sinyal analiz raporundaki eksiklikler dogrultusunda:
- P0-1 SL/TP retry yok (pozisyon korumasiz)
- P0-2 L3 close retry yok
- P0-3 startup recovery yetersiz
- RSI 30/70 VİOP M15 icin cok genis
- Breakout strength/trailing likidite sinifini kullanmiyor
- Bias hesaplaniyor ama lot'a yansimyor
- MR'da trailing stop yok
- Yeni indikatorler eksik (KC, squeeze, W%R, NATR, ADX slope, Hurst)
- Risk parametreleri tasarim dokümanından sapma

**Degisiklikler (13 dosya):**
- `engine/utils/indicators.py` — +6 yeni indikator (KC, squeeze, W%R, NATR, ADX slope, Hurst)
- `engine/mt5_bridge.py` — P0-1: SL/TP 3-retry + force close
- `engine/baba.py` — P0-2: L3 3-retry, HARD_DD 0.15→0.12, graduated lot
- `engine/ogul.py` — RSI 20/80, breakout fix, bias-lot, MR breakeven, seans filtresi, squeeze, W%R, P0-3
- `engine/models/risk.py` — daily_loss 0.018, hard_dd 0.12
- `engine/__init__.py` — VERSION = "5.1.0"
- `config/default.json` — v5.1 yapi (yeni bolumler + parametreler)
- `api/server.py` — versiyon 5.1
- `api/schemas.py` — version alani, risk limitleri, graduated_lot_mult
- `desktop/src/components/Dashboard.jsx` — versiyon 5.1
- `tests/test_indicators.py` — +22 yeni test
- `tests/test_integration.py` — bias-lot mock duzeltme
- `tests/test_risk_calculations.py` — hard_dd 0.12 uyumu

**Eklenenler:**
- 6 yeni indikator fonksiyonu
- SL/TP retry mekanizmasi (3 deneme + force close)
- L3 close retry mekanizmasi (3 deneme)
- Graduated lot schedule (1 kayip: x0.75, 2 kayip: x0.50, 3+: cooldown)
- Bias-lot entegrasyonu
- MR breakeven trailing
- Seans zamanlama filtresi
- BB/KC squeeze breakout bonusu
- Williams %R cift onay (MR)
- 22 yeni test
- `engine/__init__.py` VERSION
- `docs/CHANGELOG_FAZ4.md`
- `docs/2026-03-04_v5_1_gelistirme_plani.md`

**Cikartilan:**
- Yok (tum degisiklikler ekleme/guncelleme)

**Test Sonucu:** 665 passed, 0 failed, 1 skipped, 1 warning

---

<!-- Yeni kayit sablonu:

## #XX — BASLIK

| Bilgi | Deger |
|-------|-------|
| **Tarih** | YYYY-MM-DD HH:MM:SS +03:00 |
| **Commit** | `xxxxxxxx` |
| **Baslik** | Ne yapildi |

**Neden:** Neden yapildi

**Degisiklikler (X dosya, +Y -Z satir):**
- `dosya/yolu` — Aciklama

**Eklenenler:**
- Yeni eklenen ozellikler

**Cikartilan:**
- Kaldirilan ozellikler

-->
