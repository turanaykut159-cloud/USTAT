# USTAT v5.0 — GELISIM TARIHCESI

**Olusturulma Tarihi:** 2026-02-23
**Son Guncelleme:** 2026-02-23
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
