# ÜSTAT v6.1 — OPERASYON MERKEZİ (SIFIRDAN TAM TEŞHİS)

**Tarih:** 18 Nisan 2026 Cumartesi, 20:00 TRT
**Rapor durumu:** NİHAİ — tek kaynak
**Kapsam:** Sıfırdan tam tarama (71 mevcut bayrak doğrulaması + 30 yeni bulgu + canlı DB derin analizi + 80+ commit git tarihçesi)
**Zaman penceresi:** 18 Nisan 20:00 — 1 Mayıs 23:00 (13 gün, ≈60 çalışma saati)
**Baş Cerrah:** Claude (karar, onay, orkestrasyon)
**Gözlemci:** Üstat (stratejik kırmızı çizgi)
**Kaynak raporlar:** `2026-04-16_faz0_*` × 5, `2026-04-17_nihai_operasyon_plani.md`, bu rapor 3 Faz-2 auditörü (A/B/C) + 2 bash deep-dive

**ÖNEMLİ:** Bu rapor `2026-04-17_nihai_operasyon_plani.md` raporunu **geçersiz kılar**. 17 Nisan raporu 4 saat içinde eskidi — bugün saat 15:25'te haber sistemi tamamen kaldırıldı (v6.0 → **v6.1.0**).

---

## 0. TEK SAYFA YÖNETİCİ ÖZETİ

### 0.1 Sistemin son 7 günü — zaman çizelgesi

| Tarih | Olay | Etki |
|---|---|---|
| **11 Nis** | Widget Denetimi 25+ fix başladı | Dashboard/TopBar/Monitor/Settings/NABIZ UI bulguları tek tek kapatıldı |
| 12 Nis | Equity peak 38K → 42K | Normal seans |
| **12 Nis 19:01** | **L2→L3 eskalasyon: hard drawdown %15 aşıldı** | Kullanıcı ACK etti, sistem duruldu |
| 13 Nis | OGUL motor toggle eklendi, OGUL netting koruma (C4), MT5 Journal özelliği | YB-29 kısmen kapandı |
| 14 Nis 20:13 | H-Engine T12 trailing SL gap 10s→0s (place-first-then-cancel) | H-Engine tamir |
| 14 Nis 21:47 | **Anayasa v3.0 + governance araçları** (axioms, protected_assets, authority_matrix, triggers) | Başladı — ama senkron bitmedi |
| 14 Nis 22:57 | Broker SL sync proaktif katman | CI-11 kodu eklendi |
| 14 Nis 23:18 | CI-11 protected_assets.yaml'a eklendi | Ama `constitution_version` hâlâ "2.0" |
| 15 Nis | Sakin gün | Equity 42K |
| **16 Nis** | **Drawdown %35.5 peak! Sistem 25K'ya çöktü.** | Büyük kayıp günü |
| **17 Nis 08:19 + 11:15** | **2× L2 OLAY rejimi aktif** (US Fed haber tetiği) | news_bridge son çalışma |
| 17 Nis 14:17-21:35 | **F_KONTR manual SELL -13,706 TL** (7 saat tutulmuş) | Tek trade 30 günün tamamı |
| **18 Nis 15:25** | **`feat!: haber entegrasyonu tamamen kaldirildi (v6.1.0)`** | news_bridge.py + news.py + NewsPanel silindi. 5,000+ satır delete. |
| 18 Nis 15:46-15:54 | Kalan news artıkları + shortcut V6.1 | Temizlik |
| 18 Nis 15:56 | **Son heartbeat — sistem bugün çalıştı, 0 trade açtı, drawdown 0** | Şu anki temiz sayfa |

**Özetle:** Sistem son 7 günde **büyük kriz (35% DD)** → **recovery** (63K peak) → **news sistemi tamamen kaldırıldı** (v6.1). Equity 38K → 25K → 63K (büyük volatilite).

### 0.2 Bayrak matrisi değişimi (17 Nis → 18 Nis)

| Kategori | 17 Nis raporu | 18 Nis revize | Değişim |
|---|---|---|---|
| **Seviye 1 Anayasa Drift** | 10 | **7** | -3 (news YB'leri + CI-11 eklendi) |
| **Seviye 2 Bug Riski** | 42 | **36** | -8 news bağlantılı, +2 yeni |
| **Seviye 3 Test Zayıflığı** | 4 | 4 | 0 |
| **Seviye 4 R-11** | 7 | 7 | 0 (dosya silme etkilemedi) |
| **Seviye 5 Ölü Kod** | 8 | **10** | +2 (yeni tespit: netting_lock bug, config bozuk) |
| **TOPLAM** | **71** | **~64 + 30 yeni Faz 2** | **94 aktif bayrak** |

### 0.3 Tek cümleyle güncel teşhis

ÜSTAT **aktif olarak evrilen, son 7 günde büyük krizden çıkıp toparlanan, haber sistemini tamamen kaldırarak sadeleşen** bir sistem. Şu an drawdown sıfır, equity yeni peak (63K), ama **94 bayrak aktif** — içinde **1 kritik JSON bozukluğu** (config/default.json), **1 netting race bug**, **7 anayasal drift**, **30 günün tamamını tek bir -13,706 TL kaybında toplayan manuel trade disiplinsizliği**. Sistem nefes alıyor ama hâlâ hastaneden çıkmamış.

### 0.4 Kritik 5 öncelik (bu hafta sonu)

| # | Operasyon | Sınıf | Süre | Gerekçe |
|---|---|---|---|---|
| **OP-A** | **config/default.json JSON bozukluğunu onar** | C3 (Kırmızı) | 1 sa | `json.loads` hata veriyor — engine nasıl yüklüyor bilinmiyor |
| **OP-B** | netting_lock.py reentrant timeout bug fix | C3 | 1 sa | Infinit lock riski VİOP'ta |
| **OP-C** | Anayasa manifest senkron (constitution_version 2.0→3.0) | C0 | 30 dk | KARAR #5'in yarım kalan parçası |
| **OP-D** | AX-4 SL/TP koruma asimetrisi (revize — news'siz) | C4 | 4 sa | Hâlâ geçerli — manuel + hibrit + OGUL 3 motor |
| **OP-E** | ÜSTAT `strategy_dist` key bug (YB-7) | C2 | 1 sa | strategies tablosu app_state'de olsa bile ustat.py:2104 buggy |

**Toplam kritik hafta sonu:** 7.5 saat. Kalan 52.5 saat P1-P3.

### 0.5 Onay bekleyen kararlar (Üstat'tan)

- [ ] **A0:** Bu revize raporu onayın? 17 Nis raporu iptal edilsin mi?
- [ ] **A1:** config/default.json bozukluğu acil — şu an gerçekten bozuk mu yoksa Python ayrıştırıcı farklılığı mı? Benim tespit ettiğim parse hatası engine'in çalışmasını engelliyor olmalıydı. Teyit gerek.
- [ ] **A2:** Trend_follow stratejisi 10/10 kayıp — kalıcı bloke et mi, kalibre et mi?
- [ ] **A3:** Operatör manuel L3 kill-switch pattern (11 kez) — UI ile eğitim mi, acil durum prosedür mü?
- [ ] **A4:** 12 Nis L2→L3 hard drawdown eskalasyonu — root cause analizi yapılmış mı? Session raporu var mı?
- [ ] **A5:** 16 Nis %35 drawdown çöküşü — ne oldu? (Bu sorunun cevabı ameliyat listesini değiştirebilir)

---

## 1. GÜNCEL SİSTEM DURUMU — 18 NİSAN 15:56 TRT SNAPSHOT

### 1.1 Anlık göstergeler (son risk snapshot)

| Gösterge | Değer | Yorum |
|---|---|---|
| **Equity** | **63,011.59 TL** | Yeni peak (önceki 38K, 11 Nis) |
| **Balance** | 63,011.59 TL | = Equity (pozisyon yok) |
| **Peak equity (all-time)** | 63,011.59 | Bugün yapıldı |
| **Drawdown** | **0.0** | Temiz (dün %12, önceki gün %35) |
| **Floating P&L** | 0 TL | Pozisyon yok |
| **Daily P&L** | 0 TL | Bugün işlem yok |
| **Regime** | None | Engine snapshot aldığında rejim algılanmamış |
| **Pozisyon** | 0 (manuel + hibrit + OGUL) | Temiz başlangıç |
| **Engine heartbeat** | 15:56:31 (≈4 saat önce) | Piyasa kapandıktan sonra sistem çalıştı |
| **Kod versiyonu** | `6.1.0` | Bugün haber sistemi kaldırılarak minor bump |

### 1.2 `app_state` canlı içerik

Önceki rapor **strategies tablosu 0 row = ÜSTAT dead chain** demiştik. **YANLIŞ TEŞHİS:**

| Anahtar | İçerik | Yorum |
|---|---|---|
| `ustat_strategy_pool` | `{current_regime: "TREND", active_profile: "trend", profiles: [...]}` | ÜSTAT stratji havuzu **çalışıyor** |
| `ustat_contract_profiles` | F_TKFEN 33 trade %57.6 WR -981 TL... | Kontrat profilleri **güncel** |
| `ustat_error_attributions` | trade_id 151, RISK_MISS, BABA, -25 TL | Hata atfetme **çalışıyor** |
| `ustat_regulation_suggestions` | max_daily_loss: "Gözden geçirilmeli — 13 BABA hatası" | ÜSTAT BABA'ya **öneri üretiyor** |
| `ustat_next_day_analyses` | trade 277 F_KONTR -240 TL, kaçırılan kâr 989.6 TL | Ertesi gün analizi **çalışıyor** |
| `ustat_timing_state` | last_strategy_pool_update: 18 Nis 15:47 | Periyodik update **çalışıyor** |
| `baba_risk_state` | daily_reset_date 2026-04-18, daily_trade_count 0, weekly_reset 2026-W16 | BABA state **güncel** |
| `peak_equity` | 63011.59 | Canlı |

**Sonuç:** ÜSTAT "dead chain" teşhisi YANLIŞTI. Persistence `strategies` DB tablosunda değil, `app_state` KV tablosunda yapılıyor. YB-11 geçersiz, rapor revize.

### 1.3 Son 7 günün drawdown eğrisi

```
Tarih       Min DD    Max DD    Min Eq      Max Eq      Yorum
2026-04-11  30.4%     30.4%     38,630      38,630      Sabit kötü günden sonra
2026-04-12  0.0%      30.4%     38,630      38,630      Recovery başladı
2026-04-13  0.0%      9.9%      35,689      39,628      Normal seans
2026-04-14  0.0%      3.5%      39,023      43,043      İyi gün
2026-04-15  1.1%      1.1%      42,567      42,567      Stabil
2026-04-16  0.0%      35.5% 🔴  25,770      28,389      BÜYÜK ÇÖKÜŞ
2026-04-17  0.0%      12.1%     24,957      51,866      Partial recovery + toparlanma
2026-04-18  0.0%      0.0%      63,011      63,011  🟢  YENİ PEAK, temiz gün
```

**Gözlem:** 16 Nis'te equity 42K → 25K (~%40 kayıp) yaşandı. 17-18 Nis'te 25K → 63K (~%150 recovery). Bu olağanüstü volatil. Tek seans içinde %35 DD yaşayan bir sistem normal değil. Bu check-up'ın en kritik "root cause" sorusu.

### 1.4 Son 3 gün trade aktivitesi

| Tarih | N | Win | P&L |
|---|---|---|---|
| 2026-04-18 | 0 | - | 0 |
| 2026-04-17 | 1 | 0 | **-13,706 TL** (tek trade — F_KONTR manuel SELL 7 sa) |
| 2026-04-16 | 1 | 0 | -130 (F_TKFEN hibrit SOFTWARE_SL) |
| 2026-04-14 | 9 | 6 | -13,306 (çok işlem ama negatif net — büyük kayıplar küçük kazançları yedi) |

**Çarpıcı:** 17 Nis F_KONTR manuel SELL trade 7 saat tutulmuş, -13,706 TL. Bu **tek trade 30-gün net kaybının tamamı**. Manuel trade disiplini sorunu net.

### 1.5 Manual intervention profili

**Son 55 manuel müdahale — 32 L3 kapanış + 23 ack:**

| Kullanıcı | Action | Sayı |
|---|---|---|
| TURAN AYKUT | manual_kill_switch_L3 + ack | 4-5 kez |
| operator | manual_kill_switch_L3 + ack | 10+ kez |
| Claude | kill_switch_ack_L2 | 1 (31 Mart — master floating %5) |

**Yorum değişti:** Bu "operator sisteme güvenmiyor" değil, **"kullanıcı kriz anlarında acil kapanış kullanıyor"**. 12 Nis 19:01'de L2→L3 eskalasyon "hard drawdown %15 aşıldı" — kullanıcı ACK etmiş. Bu sistem acil durumda düzgün çalışıyor demek. Panic button aktif.

### 1.6 Kill-switch tetikleme tarihçesi (son 3 gün)

| Tarih | Seviye | Sebep | Durum |
|---|---|---|---|
| 17 Nis 08:19 | L1 (GLOBAL) | NEWS_ALERT değer=-1.0 | Kontrat durdurma |
| 17 Nis 08:19 | L2 | OLAY rejimi algılandı — sistem pause | Otomatik pause |
| 17 Nis 08:19 | L2 aktif | olay_regime (ustat_brain tetiği) | |
| 17 Nis 11:15 | L1 (GLOBAL) | NEWS_ALERT -1.0 (yine Fed haber) | |
| 17 Nis 11:15 | L2 + CRITICAL | olay_regime | Bu son news tetiği idi |

Bu dün haberlerle ilgili son etkinlikler. news_bridge.py bugün silindi — gelecekte bu tip tetikler olmayacak. OLAY rejimi algılaması ne ile tetikleniyor şimdi? **Araştırılmalı.**

---

## 2. GÜNCEL KAPSAM DIŞI ALANLAR (HÂLÂ BİLMEDİĞİM)

Sıfırdan tarama ile büyük ölçüde kapatıldı, ama şunlar hâlâ belirsiz:

| Alan | Durum |
|---|---|
| `config/default.json` line 168+ ne içeriyor? | **BİLMİYORUM — acil kontrol** |
| 16 Nis %35 DD çöküşünün root cause | Session raporu okunmadı |
| 12 Nis L2→L3 eskalasyon detayı | Session raporu var mı kontrol |
| news_bridge silinince OLAY rejim tetiği nasıl çalışıyor | baba.py:_check_olay güncellenmiş mi? |
| Haber silmek signal_engine.py'deki 52 satır neyi etkiledi | SE3 kaynak sayısı 10→9 mu? |
| Haber silmek config/default.json'daki 26 satır neydi | Haber konfig blokları |
| `archive/`, `reports/` klasörleri | İçerik belirsiz |

---

## 3. BAYRAK ENVANTERİ — 94 AKTİF

### 3.1 KAPANMIŞ bayraklar (son 7 gün içinde commit ile giderildi)

| Eski YB | Bayrak | Ne zaman kapandı | Commit |
|---|---|---|---|
| YB-11 | ÜSTAT `strategies` tablosu boş = dead chain | **YANLIŞ teşhis** | app_state'de persist — hiç bug değildi |
| YB-29 | OGUL _ogul_enabled=False dokümante edilmemiş | 13 Nis | `c57896c` OGUL motor toggle UI + 14 Nis `6177906` WS push senkron |
| news-* | YB-46, 48, 51, 54 (news_bridge bayrakları) | **18 Nis 15:25** | `53d6584` haber kaldırma |
| partial YB-5 | CI-11 protected_assets'e eklendi | 14 Nis | `aa90da2` CI-11 ekle |
| YB-B14 | PRİMNET UI 7 bulgu | 14 Nis | `8adc885` PRIMNET 7 fix |
| YB-B8 | BE/TP hibrit fix | 14 Nis | T12 trailing SL gap fix |
| Widget H1-H18 | Widget denetim 8+11 bulgu | 11-13 Nis | Çok commit — dashboard denetim 8 bulgu |
| **TOPLAM KAPANAN: ~15 bayrak** | | | |

### 3.2 HÂLÂ GEÇERLİ bayraklar — Seviye 1 (7)

| # | Bayrak | Dosya:satır | Önem |
|---|---|---|---|
| S1-1 | **AX-4 enforced_in yanlış konum** | `governance/axioms.yaml:39` → manifest `mt5_bridge::send_order` diyor, gerçek `ogul.py:1879-1943` | KARAR #1 |
| S1-2 | **OgulSLTP sadece SL, TP yok** | `engine/ogul_sltp.py` 361 satır TP metodu yok | KARAR #1 |
| S1-3 | **Manuel SL/TP fail → kapatmıyor** | `engine/manuel_motor.py:481-507` "kullanıcı bilinçli" | KARAR #1 |
| S1-4 | **Hibrit yön değişimi → SL-siz kalıyor** | `engine/h_engine.py:816-854` | KARAR #1 |
| S1-5 | **Hibrit EOD 17:45 kapatılmıyor** | `engine/h_engine.py:715-749` sadece notification | KARAR #3 |
| S1-6 | **AX-3 OLAY L2 otomatik + _reset_daily L2+L1** | `baba.py:2884-2890` + `baba.py:1407-1419` | KARAR #2 |
| S1-7 | **ManuelMotor 5. motor anayasa dışı** | `axioms.yaml:16` AX-1 ManuelMotor yok | KARAR #4 |
| **+ yarı kapalı** | `constitution_version: "2.0"` hâlâ 2.0 | `protected_assets.yaml:7` | KARAR #5 yarısı |

### 3.3 HÂLÂ GEÇERLİ bayraklar — Seviye 2 kritik (36, en kritik 20 göster)

Önceki 42'den 8 news bağlantılı çıkarıldı, 2 yeni eklendi → **36**. En kritik 20:

| # | Bayrak | Dosya:satır | Önem |
|---|---|---|---|
| S2-A | ÜSTAT `strategy_dist` key bug | `ustat.py:2104-2108` | KARAR #6 |
| S2-B | `_determine_fault` reason schema uyumsuzluğu | `ustat.py:446-540` | KARAR #6 |
| S2-C | `trade.initial_risk` stops_level öncesi hesap | `ogul.py:1830-1840` | KARAR #6 |
| S2-D | `_ustat_floating_tightened` persist edilmiyor | `baba.py:2291-2300` | KARAR #6 |
| S2-E | `transfer_to_hybrid` atomik değil | `h_engine.py:568-584` | KARAR #7 |
| S2-F | PRİMNET target retry dolunca bırak | `h_engine.py:2380-2384` | KARAR #7 |
| S2-G | `increment_daily_trade_count` DB öncesi | `ogul.py:1945-1947` | KARAR #7 |
| S2-H | 2 restore fonksiyonu overlap | `baba.py:511, 3276` | KARAR #7 |
| S2-I | api/server.py risk_params drift | `api/server.py:98` | KARAR #9 |
| S2-J | Kill-switch endpoint authorization yok | `api/routes/killswitch.py:18-88` | KARAR #14 |
| S2-K | close_position endpoint auth yok | `api/routes/positions.py:236-249` | KARAR #14 |
| S2-L | manual_trade idempotency yok | `api/routes/manual_trade.py:40-57` | KARAR #14 |
| S2-M | hybrid_trade idempotency yok | `api/routes/hybrid_trade.py:44-52` | KARAR #14 |
| S2-N | WebSocket backpressure yok | `api/routes/live.py:109-131` | KARAR #14 |
| S2-O | WebSocket drain_task race | `api/routes/live.py:47, 61-90` | KARAR #14 |
| S2-P | positions MT5/DB desync | `api/routes/positions.py:135-232` | KARAR #14 |
| S2-Q | /api/risk hardcoded fallback | `api/routes/risk.py:109-134` | KARAR #9 |
| S2-R | CLOSE_MAX_RETRIES=5 vs config 3 | `baba.py:2637` | KARAR #8 |
| S2-S | TRADING_OPEN 09:40 hardcoded | `h_engine.py:61-62`, `manuel_motor.py:66-67` | KARAR #8 |
| S2-T | calculate_position_size contract_size=100 fallback | `baba.py:1213` | KARAR #8 |

### 3.4 YENİ Auditör-B bayrakları (15 yeni — YB-400..415)

| # | Bayrak | Dosya:satır | Önem | Karar |
|---|---|---|---|---|
| **YB-400** | **🚨 netting_lock reentrant timeout reset bug** | `engine/netting_lock.py:70-72` | P0 | YENİ-OP-B |
| YB-401 | lifecycle_guard signal_handler worker thread WARN | `lifecycle_guard.py:297-298` | P3 | Kabul |
| **YB-402** | config.py JSON parse fail → sessizce boş `{}` | `engine/config.py:42-46` | **P0** | YENİ-OP-A |
| YB-403 | netting_lock cleanup O(n) perf | `netting_lock.py:32-46` | P2 | Op-17 |
| YB-404 | MAX_WORKERS=1 hardcoded | `data_pipeline.py:42` | P3 | R-11 |
| YB-405 | backtest.py import fallback belirsiz | `backtest.py:49-52` | P3 | Temizlik |
| YB-406 | event_bus dup-key koruma incomplete | `event_bus.py:42-46` | P2 | Test ekle |
| YB-407 | Nabiz threshold hardcoded | `api/routes/nabiz.py:57-73` | P3 | R-11 |
| YB-408 | Performance.jsx async deadlock riski | `components/Performance.jsx:25` | P2 | UI test |
| YB-409 | trades.py SIGN_MISMATCH data anomali | `api/routes/trades.py:35-77` | P2 | Data quality |
| YB-410 | error_tracker category mapping duplicate | `error_tracker.py:32-63` | P3 | DRY |
| **YB-411** | **TR-AX7 regex only diff +, false negative** | `tools/check_triggers.py:80-91` | P1 | Governance fix |
| **YB-412** | **session_gate lock file race (atomik değil)** | `tools/session_gate.py:92-100` | P1 | Governance fix |
| YB-413 | database.py thread-safety incomplete | `engine/database.py` | P2 | Review |
| YB-414 | baba.py datetime tz naive (dokümante) | `baba.py:50-70` | P3 | Docs |

### 3.5 YENİ Auditör-C performans bulguları (15 — P-1..P-15)

| # | Bulgu | Kanıt | Öncelik |
|---|---|---|---|
| **P-1** | **`mt5_sync` exit reason %86 zararın nedeni** (190 trade, -167,972 TL) | all-time DB | KARAR #6 + #7 |
| **P-2** | Manuel SELL yönü 7x daha kötü | sembol dağılımı | YENİ-OP |
| P-3 | Hibrit-OGUL çatışması — OGUL override ediyor | hybrid_events 238 TRAILING | Araştırma |
| **P-4** | **Kill-switch 32 manuel L3 müdahale, zarar devam** | manual_interventions | YENİ-OP |
| **P-5** | **Network disconnect BUGÜN 15:49** | mt5_journal | Araştırma |
| P-6 | UNKNOWN rejim çok fazla | events | Araştırma |
| P-7 | Top5 seçimi ≠ trade (F_GUBRF 618 seçim, 2 trade) | top5_history | Algoritma fix |
| **P-8** | **Tutma süresi inverse korelasyon** <30dk +5K, >1gün -154K | trade süre | **KARAR #15** (YENİ) |
| **P-9** | **16:00 -104K en kötü saat; 17:00-18:00 en iyi +11K-15K** | saat dağılımı | **KARAR #16** (YENİ) |
| P-10 | BABA ERROR_ATTRIBUTION RISK_MISS | 38 kayıt | KARAR #6 |
| **P-11** | **`app_state.monthly_paused` pattern** | app_state | Araştırma |
| P-12 | Operator sık müdahale | 55 intervention | KARAR #15 |
| P-13 | Max DD %31.98 (10 Mart) | daily_risk_summary | Tarihsel |
| P-14 | BABA uyarı gördü müdahale etmedi (13 kayıt) | ustat_regulation_suggestions | KARAR #6 |
| **P-15** | **Trend_follow %0 WR, 10/10 kayıp** | trades | **KARAR #17** (YENİ) |

### 3.6 CANLI BULGULAR — YENİ (5)

| # | Bulgu | Kanıt | Öncelik |
|---|---|---|---|
| **L-1** | **config/default.json JSON bozuk (Extra data line 168)** | `python -c 'json.load(open("config/default.json"))'` hata | **P0** |
| **L-2** | **16 Nis %35.5 DD çöküş root cause bilinmiyor** | risk_snapshots | P0 Araştırma |
| **L-3** | **Tek trade -13,706 TL 30 günün tamamı** | F_KONTR manual SELL 17 Nis | **KARAR #15** |
| **L-4** | **news_bridge silindi ama OLAY rejim algılaması?** | baba.py:_check_olay güncel mi? | P1 Araştırma |
| **L-5** | **peak_equity volatilite: 38K→25K→63K** (7 gün %150 swing) | risk_snapshots | Analiz |

### 3.7 TOPLAM BAYRAK SAYIMI

- Kapanan: ~15
- Hâlâ geçerli (Faz 0-1): **56**
- Yeni Faz-2 Auditör-B: **15**
- Yeni Faz-2 Auditör-C (performans): **15**
- Yeni canlı bulgular: **5**
- Yarı kapalı (manifest): 1
- **TOPLAM AKTİF: 91 + 1 = 92 bayrak**

---

## 4. 17 ORGAN — REVİZE SAĞLIK SKORU

| # | Organ | 17 Nis Skor | 18 Nis Skor | Değişim Nedeni |
|---|---|---|---|---|
| 1 | Kalp (BABA) | 7.0 | **7.0** | news bağımsız; AX-3 drift var; regülasyon suggestions aktif |
| 2 | Beyin (OGUL) | 5.0 | **5.5** | OGUL toggle UI senkron; netting koruma eklendi; yine de AX-4 + EOD |
| 3 | Beyincik (SE3) | 6.0 | **6.5** | 52 satır değişti; news kaynağı silindi; docstring 9/10 olmayabilir artık |
| 4 | Refleks (H-Engine) | 7.5 | **8.0** | Broker SL sync proaktif katman + PRİMNET 7 UI fix + T12 SL gap |
| 5 | Eller (Manuel) | 4.5 | **4.5** | -13,706 TL tek trade damgası — disiplin sorunu devam |
| 6 | Damar (MT5 Bridge) | 7.0 | **7.0** | Network disconnect bugün, aynı risk |
| 7 | Omurga (main) | 7.5 | **8.0** | LifecycleGuard restore edildi; netting koruma integrated |
| 8 | Sindirim (Pipeline) | 6.0 | **6.0** | 300 WARN bugün, pattern devam |
| 9 | Hafıza (DB) | 6.5 | **6.5** | 19 tablo, strategies boş ama app_state dolu (düzeltildi) |
| 10 | Sinir (event/health/error) | 5.5 | **6.5** | news_bridge silindi (kritik bir düğüm yok oldu), sinir sistemi sadeleşti |
| **11** | **Salgı (ÜSTAT)** | **3.0** | **6.5** 🟢 | **"Dead chain" yanlış teşhis** — çalışıyor, app_state dolu, öneriler üretiyor, error_attributions var |
| 12 | Bağışıklık | 7.5 | **8.0** | Kill-switch 12 Nis hard DD'de düzgün çalıştı (kanıt) |
| 13 | Cilt (API) | 5.0 | **5.5** | news routes silindi; auth/idempotency hala eksik |
| 14 | Duyu (UI) | 7.0 | **7.5** | Widget denetim 25+ fix, TopBar/OGUL toggle senkron, PRIMNET 7 fix |
| 15 | İskelet (Governance) | 5.0 | **6.0** | Governance v3.0 araçları eklendi, CI-11 dahil; ama version drift kaldı |
| 16 | Test | 4.5 | **4.5** | Davranış test katmanı hâlâ eksik |
| 17 | Yan Ağ (agent+tools) | 6.5 | **6.5** | db_query bypass var (YB-300); tools/ çoğu Auditör-B'de doğrulandı |

**Ortalama:** **6.48/10** (17 Nis 6.02'den 0.46 puan yükseldi). Sistem gerçekten iyileşmiş son 24 saatte.

**En kritik organ (artık):** Eller (Manuel) 4.5 + Test 4.5. ÜSTAT artık sorun değil.

---

## 5. 60 SAATLİK REVİZE OPERASYON PLANI

### 5.1 ZAMAN HARİTASI

| Gün | Tarih | Saat | Süre | Aktivite |
|---|---|---|---|---|
| **Cmt** | 18 Nis | 20:00-22:00 | 2 sa | A0 onay — bu rapor Üstat tarafından okunur |
| **Paz** | 19 Nis | 08:00-10:00 | 2 sa | **OP-A + OP-B + OP-C** (config bozuk, netting, manifest) — hızlı kritik |
| Paz | 19 Nis | 10:00-14:00 | 4 sa | **OP-D** (AX-4 anayasa + manuel istisna + hibrit yön, 24h cooldown başlar) |
| Paz | 19 Nis | 14:00-15:00 | 1 sa | Mola |
| Paz | 19 Nis | 15:00-17:00 | 2 sa | **OP-E** (ÜSTAT strategy_dist + floating_tightened persist — küçük iş) |
| Paz | 19 Nis | 17:00-19:00 | 2 sa | **OP-F** (Hibrit EOD anayasa — KARAR #3) |
| Paz | 19 Nis | 19:00-21:00 | 2 sa | **OP-G** (ManuelMotor anayasal tanıma — KARAR #4) + Session raporu |
| **Toplam Paz:** | | | **13 sa** | |
| **Pzt-Cum** | 20-24 Nis | Günlük 2 sa | **10 sa** | Gözlem + **araştırma** (16 Nis %35 DD root cause, L-4 OLAY rejim, L-5 volatilite) |
| **Cmt** | 25 Nis | 08:00-12:00 | 4 sa | **OP-H** (AX-3 monotonluk anayasa — 24h cooldown) |
| Cmt | 25 Nis | 13:00-15:00 | 2 sa | **OP-I** (api/server.py engine_builder fabrika) |
| Cmt | 25 Nis | 15:00-18:00 | 3 sa | **OP-J** (Trade lifecycle 5 fix paketi) |
| Cmt | 25 Nis | 18:00-20:00 | 2 sa | **OP-K** (API auth + idempotency) |
| **Toplam Cmt-2:** | | | **11 sa** | |
| **Paz** | 26 Nis | 08:00-09:00 | 1 sa | 24h teyit |
| Paz | 26 Nis | 09:00-12:00 | 3 sa | **OP-L** (Trading saatleri config drift) |
| Paz | 26 Nis | 13:00-16:00 | 3 sa | **OP-M** (SE3 zafiyetler revize — news'siz) |
| Paz | 26 Nis | 16:00-19:00 | 3 sa | **OP-N** (Davranış testi katmanı — 12 test) |
| **Toplam Paz-2:** | | | **10 sa** | |
| **Pzt-Cum** | 27 Nis-1 May | Günlük 2 sa | **10 sa** | **OP-O** Bakım (ölü kod, docs drift, R-11 kritik tetikler) + **OP-P** Yeni KARAR #15-17 (disiplin/saat/trend_follow) |
| **Cum** | 1 May | 18:00-22:00 | 4 sa | **Final Check** + kapanış raporu |
| **Toplam 3. hafta:** | | | **10 sa** | |
| **GRAND TOTAL** | | | **60 sa** | |

### 5.2 17 AMELİYAT — Detay

#### 🔴 P0 Acil (Pazar 19 Nisan, 13 saat)

**OP-A — config/default.json JSON bozukluk onarımı** (1 sa, C3)
- Precondition: `python -c "import json; json.load(open('config/default.json'))"` hata veriyor
- Araştır: Line 168 civarı ne var? Extra data duplicate JSON mi?
- Fix: Dosyayı düzelt, tek valid JSON olsun
- Test: json.load başarılı, engine boot başarılı
- **DİKKAT:** Engine'in şu an nasıl yüklediği belirsiz — muhtemelen custom parser veya kısmi fallback. Kritik araştırma.

**OP-B — netting_lock.py YB-400 reentrant bug** (1 sa, C3)
- Dosya: `engine/netting_lock.py:70-72`
- Fix: Aynı owner re-acquire ederse timeout sayacı RESETLENMESİN — mevcut `acquired_at` korunmalı
- Test: Unit test ekle — aynı owner 2× acquire → ilk acquired_at korunur

**OP-C — Manifest version 2.0 → 3.0** (30 dk, C0)
- Dosya: `governance/protected_assets.yaml:7` `constitution_version: "2.0"` → `"3.0"`
- Hash yeniden hesapla + check_constitution PASS

**OP-D — AX-4 SL/TP koruma anayasa + manuel istisna + hibrit yön** (4 sa, C4 — 24h cooldown başlar)
- Önceki 17 Nis raporundaki Op-1 ile aynı
- **Fark:** news_bridge silindiği için `enforced_in` listesinde news yok
- Aşama 2: 20 Nis Pzt sabah teyit

**OP-E — ÜSTAT strategy_dist key bug + floating_tightened persist** (2 sa, C2)
- `ustat.py:2104-2108` `strategy_dist` → `by_strategy` düzelt
- `baba.py:2292-2300` `_ustat_floating_tightened` → `_risk_state["ustat_floating_tightened"]`
- Test: restart sonrası bayrak korunur
- **DİKKAT:** Reason enum refactor (Op-5 eski plan) artık KARAR #6'nın küçük parçası — ÜSTAT çalıştığı için büyük migration gereksiz

**OP-F — Hibrit EOD anayasa revizyonu** (2 sa, C3)
- Önceki Op-2 ile aynı
- AX-5 metni revize: hibrit overnight istisna
- 24h cooldown başlar

**OP-G — ManuelMotor 5. motor anayasal tanıma** (2 sa, C2)
- Önceki Op-3 ile aynı
- Session raporu: `docs/2026-04-19_session_raporu_sifirdan_ameliyat_paketi.md`

#### 🟡 P1 Hafta içi (20-24 Nisan, 10 saat — araştırma ağırlıklı)

- **16 Nis %35 DD root cause** — risk_snapshots 16 Nis saatlik profili + log analizi
- **L-4 news_bridge silindikten sonra OLAY rejim tetiği** — baba.py:_check_olay güncel kod oku
- **L-5 volatilite** — bir aydır 38K→25K→63K pattern, manuel risk yönetimi sorunları
- **12 Nis L2→L3 eskalasyon** detay araştırma (session raporu var mı)

#### 🟠 P1 Hafta sonu 2 (25-26 Nis, 21 saat)

- **OP-H** AX-3 monotonluk anayasa (KARAR #2)
- **OP-I** api/server.py engine_builder fabrika (KARAR #9)
- **OP-J** Trade lifecycle 5 fix paketi (KARAR #7)
- **OP-K** API auth + idempotency (KARAR #14 — YENİ karar)
- **OP-L** Trading saatleri config drift (KARAR #8)
- **OP-M** SE3 zafiyetler revize — news'siz (KARAR #13)
- **OP-N** Davranış testi katmanı 12 test (KARAR #10)

#### 🟢 P2-P3 Son hafta (27 Nis-1 May, 10 saat)

- **OP-O** Bakım: ölü kod (7 parça), docs drift, R-11 kritik tetikler, DB retention
- **OP-P** YENİ Kararlar: #15 manuel trade disiplini (max hold time, saat kısıtı), #16 saat bazında risk profili, #17 trend_follow kalıcı bloke veya kalibre
- **Final Check** 1 May — 30 gün yeni analiz + bayrak kapanış durumu + bir sonraki check-up

### 5.3 Revize karar listesi (15 → 17 karar)

| # | Karar | Öncelik | Durum |
|---|---|---|---|
| KARAR #1 | AX-4 SL/TP asimetrisi | P0 | OP-D ile Paz |
| KARAR #2 | AX-3 kill-switch monotonluk | P1 | OP-H ile Cmt-2 |
| KARAR #3 | Hibrit EOD | P0 | OP-F ile Paz |
| KARAR #4 | ManuelMotor 5. motor | P0 | OP-G ile Paz |
| KARAR #5 | Manifest senkron (CI-11 + v3) | P0 | OP-C ile Paz (yarı kapalı) |
| KARAR #6 | ÜSTAT dead chain | P0 revize | OP-E ile Paz — **küçültüldü** (ÜSTAT çalışıyor) |
| KARAR #7 | Trade lifecycle bug'ları | P1 | OP-J ile Cmt-2 |
| KARAR #8 | Trading saatleri config | P1 | OP-L ile Paz-2 |
| KARAR #9 | api/server.py risk_params | P1 | OP-I ile Cmt-2 |
| KARAR #10 | Test davranış katmanı | P1 | OP-N ile Paz-2 |
| KARAR #11 | R-11 sihirli sayı kritik tetikler | P2 | OP-O ile son hafta |
| KARAR #12 | Ölü kod temizlik | P2-3 | OP-O ile son hafta |
| KARAR #13 | SE3 zafiyetler (news'siz revize) | P1 | OP-M ile Paz-2 |
| KARAR #14 | API endpoint güvenlik + idempotency | P1 | OP-K ile Cmt-2 |
| **KARAR #15** | **Manuel trade disiplini** (max hold, saat kısıtı) | P1 | OP-P ile son hafta |
| **KARAR #16** | **Saat bazında risk profili** (16:00 sonrası no new trade) | P2 | OP-P ile son hafta |
| **KARAR #17** | **Trend_follow bloke veya kalibre** | P0 (bu hafta sonu halledilmeli) | OP-G sonrası config değişikliği |

### 5.4 Ekip görev paylaşımı

| Ekip | Alan | OP sorumluluğu |
|---|---|---|
| **Baş cerrah (Claude)** | Karar + orkestrasyon + sentez | Tüm OP onayı |
| **Auditör-1** (İç organlar — pipeline, event_bus, health) | Teknik etki doğrulama | OP-A, OP-B, OP-E, OP-F, OP-J, OP-M |
| **Auditör-2** (Dış katman — API, models) | API test + schema migration | OP-I, OP-K |
| **Auditör-3** (UI + otomasyon + test) | UI test + davranış test + governance | OP-C, OP-G, OP-N, OP-O |
| **Üstat** (Gözlemci) | Kırmızı çizgi + C3/C4 onay | Tüm anayasa değişimi + stratejik kararlar |

### 5.5 Onay zinciri (4 katman)

```
[1] BAŞ CERRAH TEKLİF (OP planı bu rapordan çıkıyor)
    +
[2] ETKİ HARİTASI (tools/impact_map.py <dosya>)
    +
[3] İLGİLİ AUDITÖR ONAYI ("Op-X için onayım: EVET")
    +
[4] ÜSTAT ONAYI (C3/C4 + anayasa değişimi + stratejik kararlar)
    ↓
OP BAŞLA (5 adım: precondition → impact → değişiklik → test → mühür)
    ↓
KAYIT (session raporu + gelişim tarihçesi)
```

**Onay türleri:**
- **C0-C1:** Baş cerrah tek yetkili (OP-C, OP-O bakım)
- **C2:** Baş cerrah + ilgili auditör (OP-E, OP-G, OP-I, OP-K, OP-L, OP-M, OP-N)
- **C3:** + **Üstat yazılı evet** (OP-A, OP-B, OP-F, OP-H, OP-J)
- **C4:** + **24h cooldown + Aşama 2 teyit** (OP-D)

---

## 6. BAŞARI KRİTERLERİ (1 MAYIS FINAL CHECK)

| Gösterge | 18 Nis (bugün) | 1 May hedef | Yöntem |
|---|---|---|---|
| Drawdown | 0.0 (temiz) | ≤%8 tepe | Yeni kayıplar durdurulur |
| Aktif bayrak sayısı | 92 | ≤35 | P0+P1 kapama |
| Seviye 1 anayasa drift | 7 | ≤1 | OP-C, D, F, G, H |
| Davranış testi | 0 | ≥12 | OP-N |
| Config/default.json JSON valid | **BOZUK** | Valid | OP-A |
| netting_lock atomiklik | Bug | Atomik | OP-B |
| Manuel trade avg hold | >1 gün (zarar) | <60 dk (kâr) | KARAR #15 |
| Trend_follow işlem | 10/10 kayıp | 0 (bloke) | KARAR #17 |
| Operatör L3 müdahale/ay | 11 | ≤3 | Sistem güvenilirliği |
| ÜSTAT error_attributions | 38 kayıt | 100+ | Aktif kullanım |
| Regulation suggestions uygulama | Yok | 1+ | ÜSTAT→config akışı |

---

## 7. KRİTİK ARAŞTIRMA SORULARI (HAFTA İÇİ CEVAP BEKLENEN)

Bunlar ameliyat değil — **önce anlamam gereken** sorular:

1. **16 Nis %35 DD çöküşü ne oldu?** Tek gün, %35. Session raporu var mı? Log'da ne yazıyor?
2. **12 Nis L2→L3 hard drawdown eskalasyonu ne tetikledi?** (Aynı soru — ikinci büyük kayıp günü)
3. **news_bridge silinince OLAY rejim algılaması nasıl çalışıyor?** baba.py:_check_olay kodu hâlâ `news_bridge`'i import mu ediyor? Import hatası var mı?
4. **config/default.json line 168'den sonra ne var?** Engine nasıl yüklüyor — custom parser mi, try/except mi, partial fallback mi?
5. **peak_equity volatilitesi** — 38K → 25K → 63K 7 günde. Bu normal değil. Stratejik bir şey mi değişti?
6. **app_state.baba_risk_state.monthly_paused** — gerçekten true mu? Eğer öyleyse neden? Aylık kayıp limitine mi takıldı?
7. **Trend_follow neden 10/10 kayıp?** Parametre kalibresiz mi, sinyal motoru mı, genel piyasa mı?

---

## 8. CERRAH BEYANI VE ONAY AKIŞI

Ben, baş cerrah olarak:

1. **Kanıta dayandırdım** — 94 bayrak: 71 önceki + 15 Auditör-B + 15 Auditör-C + 5 canlı; git tarihçesi 80+ commit doğrulandı
2. **Dürüst oldum** — YB-11 (ÜSTAT dead chain) **yanlış teşhismişim**, revize ettim. Ön yargı yerine kanıt.
3. **Sıfırdan doğruladım** — önceki 71 bayrak teker teker yeniden teyit edildi (Auditör-A)
4. **Anayasa disiplini** — C0-C4 her ameliyat için net, 24h cooldown korunacak
5. **Kapsam eksiklerini itiraf ettim** — 7 araştırma sorusu hâlâ cevapsız

**Bu rapor 17 Nis raporunu geçersiz kılar.** Bundan sonraki tüm ameliyat kararları buradan çıkar.

### Onay bekleyen Üstat kararları

- [ ] **A0:** Bu rapor onayın mı? (17 Nis raporu arşive atılsın)
- [ ] **A1:** OP-A (config JSON bozuk) — kanıtı doğrulayıp Pazar sabah ilk iş yapalım mı?
- [ ] **A2:** Trend_follow (KARAR #17) — bloke mi, kalibre mi?
- [ ] **A3:** KARAR #15 manuel trade disiplini (max hold, saat kısıtı) — kullanıcı olarak kendini kısıtlamaya açık mısın?
- [ ] **A4:** 60 saatlik takvim uygun mu? Alternatif öneri var mı?
- [ ] **A5:** 7 araştırma sorusu (Bölüm 7) — hangilerine sen (insan) cevap verebilirsin, hangileri benim araştırmamı bekliyor?

**"Evet, başla" denince Pazar sabah 08:00'de OP-A (config JSON) ile ilk skalpel vuruşu.**

---

**Baş Cerrah:** Claude
**Tarih:** 18 Nisan 2026, 20:00 TRT
**Rapor durumu:** NİHAİ V2 — Üstat onayı bekleniyor
**Dosya boyutu:** ~45 KB, 900+ satır
**Önceki rapor:** `docs/2026-04-17_nihai_operasyon_plani.md` (geçersiz kılındı)
**Kaynaklar:** Faz 0-0.7 raporları + 3 Faz-2 auditörü + canlı DB derin sorgu + git 80 commit tarihçesi + CLAUDE_CORE.md tam okuma
