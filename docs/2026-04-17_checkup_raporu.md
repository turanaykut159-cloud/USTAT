# ÜSTAT v6.0 — KAPSAMLI CHECK-UP RAPORU

**Tarih:** 2026-04-17 (Cuma, 09:18 TRT — piyasa açılışına 12 dk)
**Tür:** Tam sistem sağlık muayenesi (A'dan Z'ye tarama)
**Yöntem:** 17 anatomik organa ayırma + organ-organ muayene + sistemik etkileşim matrisi
**Kaynak:** 7 Faz 0-1 raporu (187 KB, 42 bayrak, 13 karar noktası) + canlı log/DB/heartbeat okuması
**Zaman sınıfı:** Savaş Zamanı teşhis (piyasa açıkken sadece okuma) — ameliyatlar Barış Zamanına (hafta sonu) planlanacak
**Eşlik eden dosya:** `2026-04-17_ameliyat_plani.md` (öncelik sıralı tamir listesi)

---

## 0. YÖNETİCİ ÖZETİ (TEK SAYFA)

### 0.1 Genel sağlık skoru

| Kategori | Skor | Durum |
|---|---|---|
| **Kritik fonksiyonlar (trading, risk, emir)** | **7.5/10** | Çalışıyor, yerel drift var |
| **Güvenlik katmanları (kill-switch, SL/TP)** | **6.5/10** | Asimetrik — kısmi koruma, 4 motor farklı yorum |
| **Veri bütünlüğü (DB, pipeline, persistence)** | **7.0/10** | Sağlam ama `ustat.db` ölü, reason schema uyumsuz |
| **Anayasal uyum (axioms, manifest, doc)** | **5.5/10** | v3.0 anayasa vs v2.0 manifest drift, 5. motor tanımsız |
| **Test kapsamı (critical_flows davranış)** | **4.5/10** | 55 test ama çoğu string/imza — davranış testi eksik |
| **Operasyonel olgunluk** | **8.0/10** | Logging güçlü, governance otomasyon kurulmuş |
| **GENEL TOPLAM** | **6.5/10** | Üretim düzeyinde çalışıyor; kritik bakım gerekli |

### 0.2 Bir cümleyle teşhis

Sistem **canlı para ile çalışan sağlıklı bir organizma** — kalp atıyor, damarlar açık, beyin karar veriyor — ama **birkaç önemli damarda tıkanıklık başlamış** (AX-4 SL/TP asimetrisi, ÜSTAT öğrenme motoru sessiz, 5. motor anayasa dışı). Bu tıkanıklıklar bugün semptom vermiyor ama önümüzdeki haftalarda **sessiz felç veya mini kriz** tetikleyebilir.

### 0.3 Acil bakım sinyalleri (bugün bilinmeli)

1. **AX-4 SL/TP koruma asimetrisi** — OgulSLTP sadece SL koyuyor, TP yok; ManuelMotor SL/TP başarısızsa pozisyonu kapatmıyor; H-Engine yön dönüşünde korumayı bırakıyor. **Canlı para riski: ORTA-YÜKSEK (nadiren tetiklenen ama felaket potansiyelli).**
2. **ÜSTAT'ın dead chain'i** — hata atfetme motoru reason string uyumsuzluğu yüzünden hiçbir şey atfetmiyor, R-Multiple yanlış hesaplanıyor, strateji önerileri boş veri ile üretiliyor. **"Öğrenen sistem" şu an öğrenmiyor.**
3. **Hibrit EOD kapanış yok** — 17:45'te hibrit pozisyonlar overnight kalıyor; PRİMNET daily settlement koruma sağlıyor ama gap senaryosu açık. Anayasa AX-5 ile kesin çelişki.
4. **Kill-switch monotonluk ihlali** — OLAY kalkınca L2→L0 otomatik temizleniyor (baba.py:2884); günlük reset L2+L1 temizliyor (baba.py:1407). AX-3 "sadece yukarı gider" metniyle çelişki.
5. **ManuelMotor 5. motor ama anayasada yok** — Kırmızı Bölge dışında, yetki matrisi tanımsız, silinirse test yakalamaz.

### 0.4 Canlı sistem durumu (17 Nisan 09:18 TRT)

- **Motor:** Kapalı (graceful shutdown 08:41 TRT, shutdown.signal aktif)
- **Piyasa:** 12 dk sonra açılacak
- **Açık pozisyon:** Manuel 0, Hibrit 0 (son kapanış 16 Nisan TKFEN SOFTWARE_SL -125 TL)
- **Son 5 hibrit P&L:** -125, -1039, +620, -250, +710 = **net -84 TL**
- **Son hesap bakiye/equity** (dün 08:41): 24,980.66 TL / 24,980.66 TL (margin 26,040 anlık bir snapshot anomalisi — sistem kapatılmış, pozisyon yok)
- **Log hacmi bugün:** 6.4 MB (premarket veri toplama), 875 WARN/ERROR/CRITICAL
- **Governance v3.0 araçları** kurulmuş ama manifest senkronu bozuk

### 0.5 Öncelik özeti (ameliyat plan detayı ayrı dosyada)

| Öncelik | Kategori | Adet | Efor | Ne zaman |
|---|---|---|---|---|
| **P0 — Kritik damar** | Finansal risk veya anayasa ihlali | 3 | M-L | **Bu hafta sonu** (18-19 Nisan) |
| **P1 — Tıkalı damar** | Gelecek patlayacak bug'lar | 5 | M | **Nisan son haftası** |
| **P2 — Bakım** | Dokümantasyon, test, temizlik | 7 | S | **Mayıs boyunca yayılmış** |
| **P3 — İyileştirme** | Refactor, modernizasyon | 3 | L-XL | **Önümüzdeki çeyrek** |

---

## 1. CANLI SİSTEM DURUMU (17 Nisan 2026, 09:18 TRT)

### 1.1 Anlık süreç durumu

| Bileşen | Durum | Kanıt |
|---|---|---|
| Engine heartbeat | **Kapalı** | `engine.heartbeat` son yazım 08:41:42 UTC (37 dk önce) |
| API (uvicorn :8000) | **Kapalı** | `api.pid` yok |
| Watchdog | **Kapalı** | `watchdog.pid` yok |
| Shutdown signal | **Aktif** | `shutdown.signal` = 1776404511381 (graceful shutdown bayrağı) |
| Electron UI | Muhtemelen kapalı | Win hostunda doğrulanmadı |
| MT5 terminal | Muhtemelen kapalı | Engine-side kontrol yapılamaz (process Windows) |

**Gözlem:** Piyasa açılışına 12 dakika var. Kullanıcı normalde bu noktada sistemi başlatır (LockScreen → MT5 OTP → Dashboard). Premarket veri toplama bugün 08:41'e kadar sürmüş, sonra sistem kapanmış.

### 1.2 Açık pozisyon sayımı (DB)

- **Manuel pozisyon** (`database/manual_positions.json`): `{}` → **0 pozisyon**
- **Hibrit pozisyon** (`hybrid_positions WHERE closed_at IS NULL`): **0 pozisyon**
- **OGUL açık pozisyon** (trades tablosunda `state` kolonu yok; açık state bellek) → engine kapalı olduğu için belirsiz, ama manuel+hibrit sıfır olduğundan büyük ihtimalle **0**

**Sonuç:** Hesap açık pozisyondan bağımsız. Sabah yeniden başlarken temiz sayfa.

### 1.3 Son 5 hibrit pozisyon — tarihsel göstergeler

| # | Tarih | Sembol | Yön | Lot | Giriş | Sonuç | P&L | Kapanış sebebi |
|---|---|---|---|---|---|---|---|---|
| 65 | 16 Nisan 10:47 | F_TKFEN | BUY | 1.0 | 122.9 | — | **-125** | **SOFTWARE_SL** |
| 64 | 14 Nisan 20:40 | F_AKBNK | BUY | 5.0 | 81.6 | — | **-1039** | EXTERNAL |
| 63 | 14 Nisan 12:57 | F_ASELS | SELL | 1.0 | 425.6 | — | **+620** | EXTERNAL |
| 62 | 14 Nisan 12:03 | F_KONTR | SELL | 25.0 | 9.96 | — | **-250** | **SOFTWARE_SL** |
| 61 | 14 Nisan 11:08 | F_ASELS | SELL | 1.0 | 427.8 | — | **+710** | EXTERNAL |

**Net 5-işlem P&L: -84 TL**, WR 2/5 = %40.

**Kritik sinyal:** `SOFTWARE_SL` iki kez (TKFEN, KONTR). Bu reason, H-Engine yazılımının SL'i MT5 broker tarafında yerleşik olmadığında kendi iç SL hesaplamasıyla pozisyonu kapattığını gösterir. Yani CI-11 (Broker SL Sync) koruması gerçekten tetiklenmiş — iyi haber koruma çalışıyor, kötü haber broker SL sync bozuluyor. Anayasal katman ve kod drift'i var:
- CI-11 `USTAT_ANAYASA.md:75`'te tanımlı ama `protected_assets.yaml`'da YOK
- Test (`test_broker_sl_sync_periodic_check_contract`) var ama davranış testi değil, imza kontrolü

### 1.4 Bugünkü log profili

- **Dosya:** `logs/ustat_2026-04-17.log` — 6.4 MB, 05:41 UTC'de kapatıldı
- **WARN+ERROR+CRITICAL sayımı:** 875
- **Profil:** Çoğunluğu `data_pipeline Gap` uyarıları (bar eksikliği) — dün (16 Nisan) gün içi pek çok 180-360 saniyelik bar eksikliği var. Operasyonel değil, yapısal.
- **Dünkü log:** 33.7 MB — normal yoğunlukta bir seans logu
- **14 Nisan log:** 145 MB — **anormal derecede büyük**, derin debug seansı işareti

### 1.5 Veri büyümesi ve yedekleme

- **trades.db**: 71 MB aktif, WAL 4.1 MB, SHM 32 KB → sağlıklı
- **Yedekler**: 3 aynı günde alınmış 71 MB'lık yedek (16 Nisan 06:48, 06:52, 07:52) → günde 1 yedek yeter, **3 fazla** (disk yükü)
- **`ustat.db`**: 0 byte → **ÖLÜ DOSYA** (Faz 0 bulgusu doğrulandı; `database.py` sadece `trades.db`'ye bağlanıyor)
- **`t009.db`**: 4.5 MB, 13 Nisan → bilinmeyen, muhtemelen deneysel backtest DB

### 1.6 Tablo büyüklükleri (canlı)

| Tablo | Kaynak raporlar | Gerçek canlı durum |
|---|---|---|
| Toplam tablo sayısı | Docs 16, faz0 16 | **19 tablo** (doküman drift: `backtest_bars`, `error_resolutions`, `sqlite_sequence`) |
| `trades` | — | Büyük (gerçek boyut doğrulanmadı, trades.db 71 MB'nin büyük payı) |
| `bars` | — | Ana hacim tüketicisi |
| `events` | — | Olay zinciri |
| `notifications` | — | Düşük hacim |
| `hybrid_positions` | — | 65 satır (total, sadece ilk 5 canlı sorgulandı) |

---

## 2. ORGAN HARİTASI — 17 ANATOMİK BÖLGE

Sistemi doğal bölünmesine göre 17 organa ayırdım. Sayı mistik değil, kodun gerçekliğine göre çıktı (kullanıcı "15 kesin değil, esnek olsun" dedi — doğal bölünmeye izin verdim, 17 oldu).

### 2.1 Anatomi haritası

| # | Organ | Biyolojik karşılığı | Kod dosya(lar)ı | Satır | Rol (tek cümle) |
|---|---|---|---|---|---|
| **1** | **KALP** | Pompa — ritim + risk kapısı | `engine/baba.py` | 3388 | Risk kontrolü, kill-switch, rejim algılama, drawdown kapıları |
| **2** | **BEYİN (KORTEKS)** | Karar merkezi | `engine/ogul.py` | 3570 | Sinyal yürütme, emir state-machine, Top5, EOD |
| **3** | **BEYİNCİK** | Koordinasyon | `engine/utils/signal_engine.py` (SE3) | 1512 | 10-kaynak sinyal üretimi, konsensüs, yapısal SL/TP |
| **4** | **REFLEKS SİSTEMİ** | Otomatik tepki | `engine/h_engine.py` | 3095 | Hibrit pozisyon: breakeven, trailing, PRİMNET, broker SL sync |
| **5** | **ELLER (KULLANICI DOKUNUSU)** | Motor beceri | `engine/manuel_motor.py` | 1190 | Kullanıcı tetikli manuel emirler, MT5 direct position benimseme |
| **6** | **ATARDAMAR + KILCAL** | Kan dolaşımı | `engine/mt5_bridge.py` | 3171 | Broker I/O: emir, pozisyon, tick, bar, heartbeat, CB |
| **7** | **OMURİLİK** | Ana iletim | `engine/main.py` + `api/server.py` (lifespan) | 1573 + 273 | Cycle orkestrasyonu, lifespan, fail-closed, crash watchdog |
| **8** | **SİNDİRİM** | Besin işleme | `engine/data_pipeline.py` + `engine/top5_selection.py` | — | Piyasa verisi besleme (15 kontrat × 4 TF), Top5 seçim |
| **9** | **HAFIZA (HİPPOKAMPUS)** | Kalıcı kayıt | `engine/database.py` + `trades.db` | 2058 | SQLite wrapper, 19 tablo, retention, WAL yönetimi |
| **10** | **SİNİR SİSTEMİ (İÇ)** | İleti + uyarı | `engine/event_bus.py`, `error_tracker.py`, `health.py`, `news_bridge.py` | — | Event emission, error attribution trigger, health metrics, news feed |
| **11** | **SALGI BEZLERİ (ÖĞRENME)** | Endokrin — geri besleme | `engine/ustat.py` | 2195 | Strateji havuzu, hata atfetme, BABA feedback, kontrat profilleri |
| **12** | **BAĞIŞIKLIK SİSTEMİ** | Tehdide yanıt | BABA içindeki kill-switch + mt5_bridge Circuit Breaker + main fail-closed | (dağınık) | L1/L2/L3, 5 ardışık timeout → 30sn block, MT5 kurtarılamaz → sistem dur |
| **13** | **CİLT (DIŞ KABUK)** | Sınır + iletişim | `api/server.py` + `api/routes/*` (23 dosya) | 273 + ~1500 | FastAPI endpoints, WebSocket, CORS, SPA fallback |
| **14** | **DUYU ORGANLARI** | Dış dünya arayüzü | `desktop/main.js` + `desktop/src/` (21 JSX) + `desktop/mt5Manager.js` | ~5000 | Electron, LockScreen, Dashboard, MT5 OTP otomasyon |
| **15** | **İSKELET** | Destek + şekil | `config/default.json` + `governance/*.yaml` + `USTAT_ANAYASA.md` + `CLAUDE.md` | 189 + 822 + 294 + … | Sabitler, axiomlar, korunan varlıklar, yetki matrisi, tetikler |
| **16** | **BAĞIŞIKLIK HAFIZASI (TESTLER)** | Anti-regresyon | `tests/critical_flows/test_static_contracts.py` + `tests/*` | 3504 + … | 55 sözleşme testi, pre-commit, CI koruması |
| **17** | **YAN SİNİR AGI** | Periferik destek | `ustat_agent.py` + `.agent/claude_bridge.py` + `tools/*.py` | 3781 + … | Claude ↔ Windows köprüsü (53 komut), governance otomasyonu |

### 2.2 Organ büyüklük dağılımı (satır bazında)

```
BEYİN (OĞUL)     3570 ████████████████████████
KALP (BABA)      3388 ██████████████████████▊
ATARDAMAR        3171 █████████████████████▍
REFLEKS          3095 ████████████████████▊
OMURILIK (main)  1573 ██████████
BEYİNCİK (SE3)   1512 ██████████
ELLERI (manuel)  1190 ████████
SALGI (ÜSTAT)    2195 ██████████████▊
HAFIZA           2058 █████████████▉
TESTLER          3504 ███████████████████████▋
YAN AĞ (agent)   3781 █████████████████████████▍
```

Toplam çekirdek engine kod: **~20,000 satır** (models/ + utils/ hariç).

### 2.3 Organ sınıflandırması — Anayasa bölgeleri

| Bölge | Organ | Dokunma kuralı |
|---|---|---|
| **Kırmızı** (10) | #1, #2, #4, #6, #7, #9, #15 (kısmi — config), omurilik main.py+api/server.py | Çift doğrulama, tek değişiklik, fonksiyon silme YASAK |
| **Sarı** (7) | #4 kısmi h_engine, #13 killswitch+positions routes, #15 engine/config.py/logger.py, #14 main.js+mt5Manager.js | Standart adımlar yeterli |
| **Yeşil** | Diğerleri (ustat.py, manuel_motor.py, api routes çoğu, desktop components, utils) | Standart dikkat |
| **Tanımsız / Drift** | #5 manuel_motor.py (anayasada yok ama davranışı Kırmızı), #10 news_bridge.py (kritik ama Yeşil) | Bakım: KARAR #4 kapsamında |

---

## 3. ORGAN MUAYENELERİ

Her organ için rol + kanıt + sağlık göstergeleri + bulgular + diğer organlara etki + skor. Bulgular 7 Faz raporundaki 42 bayrağa bağlı — kanıt satırları o raporlarda.

---

### ORGAN 1 — KALP (BABA risk motoru) — `engine/baba.py` 3388 satır

**Rol:** Sistemin hayat-ölüm kapısı. Her 10 saniyede bir ritim atar (`run_cycle`). `check_risk_limits` merkezi kararı verir: "bugün işlem açılabilir mi?" Kalbin sağlığı → tüm sistemin sağlığı.

**Sorumluluk dağılımı (kanıt: `baba.py:322` `Baba` sınıfı):**
- Rejim algılama (TREND/RANGE/VOLATILE/OLAY) — `detect_regime:627`
- Pozisyon boyutlandırma — `calculate_position_size:1176`
- Drawdown kapıları (günlük/haftalık/aylık/hard %15) — `check_drawdown_limits:1273`, `_check_hard_drawdown:1837`
- Kill-switch orkestrasyonu (L1/L2/L3) — `_activate_kill_switch:2331`, `_clear_kill_switch:2404`
- L2 kısmi kapatma (OGUL+Hybrid, manuel dokunmaz) — `_close_ogul_and_hybrid:2725`
- L3 tam kapatma (manuel dahil) — `_close_all_positions:2598`
- Fake sinyal analizi — `analyze_fake_signals:2896`
- ÜSTAT geri besleme alımı — `receive_feedback:2194`

**Sağlık göstergeleri ✓:**
- `run_cycle` her 10 sn'de çalışıyor (log'da DEBUG cycle ritmi düzenli)
- 11/11 Siyah Kapı fonksiyonu sicilde mevcut
- Fail-closed davranışı tanımlı (MT5 kurtarılamaz → sistem durdur)
- `_persist_risk_state` JSON persistansı her cycle'da çalışıyor

**Bulgular (P0-P2):**

| Bulgu | Kanıt | Sınıf | Etki |
|---|---|---|---|
| **AX-3 monotonluk ihlali: OLAY kalkınca L2→L0 otomatik** | `baba.py:2884-2890` | P1 | Haber sonrası volatilite dalgasında anında işlem açabilir |
| **AX-3 ihlali: günlük reset L2 (`daily_loss`/`consecutive_loss`) + L1 otomatik temizliyor** | `baba.py:1407-1419` | P1 | Dün kaybettirten sistem bugün temiz başlıyor; operasyonel doğru ama anayasal drift |
| **`CLOSE_MAX_RETRIES = 5` hardcoded, config `close_max_retries: 3`** | `baba.py:2637` vs `config/default.json:34` | P1 | L3'te 5 pozisyon × 5 deneme × 2 sn = 50 sn blok — CYCLE_CRITICAL_THRESHOLD=30 sn'yi aşar |
| **Fake sinyal ağırlıkları module-level hardcoded** (FAKE_WEIGHT_VOLUME=1, SPREAD=2, MULTI_TF=1, MOMENTUM=2, THRESHOLD=6) | `baba.py:116-209` | P2 | R-11 ihlali; kalibrasyon commit gerektirir, config_history silinmez |
| **`calculate_position_size` contract_size=100 fallback** | `baba.py:1213` | P2 | MT5 symbol_info başarısızsa yanlış lot; endeks kontratlarında 2x risk riski |
| **İki restore fonksiyonu overlap** (`_restore_risk_state:511` ve `restore_risk_state:3276`) | baba.py | P1 | JSON + event-based restore çakışabilir; cooldown_until hangi kaynaktan? Belirsiz |
| **`_ustat_floating_tightened` instance attr, persist edilmiyor** | `baba.py:2291-2300` | P2 | Restart sonrası aynı gün tekrar sıkılaştırma — kademeli iniş riski |

**Diğer organlara etki (damar haritası):**
- → **OGUL (Beyin):** `can_trade` kararını gönderir; `can_trade=False` ise OGUL sinyal üretemez (AX-2). BABA kalbi durursa → beyin karar veremez → sistem felç.
- → **H-Engine (Refleks):** `calculate_position_size` sonucu H-Engine'e de yansır (transfer_to_hybrid lot).
- → **MT5 Bridge (Damar):** Doğrudan çağırmıyor; OGUL/Manuel/H-Engine üzerinden dolaylı.
- → **ÜSTAT (Salgı):** `receive_feedback` geri bildirim kanalı; KARAR #6 ile bağlantılı dead chain.

**Tıkalı damar riski:** BABA'nın `_close_all_positions` fonksiyonunda retry blokajı (50 sn) heartbeat'i aşarsa watchdog'u tetikler → sistem döngüden düşer. Bu ince bir "kalp damarı sıkışması" senaryosu. L3 zaten acil durum ama ek agresif retry kalbi durdurabilir.

**Sağlık skoru: 8.0/10**
- Temel işlevler sağlam, 11 Siyah Kapı fonksiyonu yerinde
- Anayasa v3.0 ile kısmi drift (AX-3 otomatik temizleme, hardcoded sabitler)
- L3 retry blokajı potansiyel tıkanıklık

---

### ORGAN 2 — BEYİN / KORTEKS (OĞUL sinyal+emir motoru) — `engine/ogul.py` 3570 satır + `engine/ogul_sltp.py` 361 satır

**Rol:** Top5 kontratta sinyal üret, emir gönder, state machine yönet (SIGNAL→PENDING→SENT→FILLED→CLOSED), 17:45 EOD kapat, aktif pozisyonları trailing/yapısal kopma/hacim spike ile yönet, MT5 ile senkron tut.

**Sorumluluk dağılımı:**
- Top5 seçim delegasyonu (`select_top5:3523` → `Top5Selector`)
- Yön kararı (`_determine_direction:965` — 3 kaynak konsensüs)
- Strateji kontratları (`_check_trend_follow:1292`, `_check_mean_reversion:1400`, `_check_breakout:1511`)
- Sinyal yürütme (`_execute_signal:1648` — 330 satır, 9 altın kural kapısı)
- AX-4 SL koruması (`_execute_signal:1879-1943` — mt5_bridge'de değil burada)
- Trade state machine (process_signals, _manage_active_trades)
- EOD kapanış (`_check_end_of_day:2105` + `_verify_eod_closure:2167`)
- Strateji-bazlı yönetim (`_manage_trend_follow`, `_manage_mean_reversion`, `_manage_breakout`)
- MT5 senkronizasyon (`_sync_positions:3062`, `_handle_closed_trade:3098`)
- Trade mode tespiti (protect/trend/defend — `_determine_trade_mode:2549`)

**Sağlık göstergeleri ✓:**
- 5/5 Siyah Kapı fonksiyonu yerinde
- Çift katmanlı trading_hours koruması (process_signals + _execute_signal)
- Atomik concurrent slot reservation `_trade_lock` ile (1790-1803)
- AX-4 koruma zinciri tam: SLTP → OgulSLTP → close_position → report_unprotected_position

**Bulgular:**

| Bulgu | Kanıt | Sınıf | Etki |
|---|---|---|---|
| **OGUL varsayılan KAPALI (`_ogul_enabled=False`), CLAUDE.md dokümante etmiyor** | `ogul.py:436` | P2 | Kullanıcı ilk açışta "sinyal üretmiyor" paniği; UI'den `POST /api/ogul-toggle` ile açılmalı |
| **OgulSLTP (ogul_sltp.py tamamı) sadece SL koyuyor, TP YOK** | `ogul_sltp.py` 361 satır | **P0** | AX-4 "SL/TP fail → kapat" kısmi uygulanıyor; GCM VİOP TRADE_ACTION_SLTP başarısız olunca pozisyon TP'siz açılıyor |
| **Hibrit EOD kapatılmıyor** | `ogul.py:2154` yorumu: *"Hibrit EOD'da kapatılmaz, kullanıcı kararı"* | **P0** | AX-5 "17:45 tüm pozisyonlar kapatılır" ihlali |
| **Cancel/exit reason string schema merkezi değil (12+ farklı)** | `ogul.py` 1774, 1785, 1798..., 2342, 2375, 2399, 2525, 3096, 2152 | P1 | ÜSTAT `_determine_fault` `"SL_HIT"` arıyor, OGUL `"sl_tp"` üretiyor → eşleşmiyor |
| **`trade.initial_risk` stops_level ayarı öncesi hesaplanıyor** | `ogul.py:1830-1840` | P1 | R-Multiple istatistikleri yanlış → expectancy drift |
| **`increment_daily_trade_count` DB insert öncesi çağrılıyor** | `ogul.py:1945-1947` | P1 | DB fail olursa sayaç şişer, yanlış limit tetiklenir |
| **`_is_new_m5_candle` tek sample (top5[0])** | `ogul.py:686-729` | P1 | Tek sembol veri gecikmesi → 5 sembolün hepsi sinyal alamıyor |
| **`_determine_direction` 3 kaynak zayıf bağımsız** (voting + H1 aynı EMA 20/50 kullanıyor) | `ogul.py:965-1051` | P2 | "3 kaynak konsensüs" istatistiksel olarak 2-kaynak |
| **`_remove_trade` dead code** (Grep ile doğrulandı, hiç çağrılmıyor) | `ogul.py:2004-2037` | P3 | Bakım yükü |
| **~55+ module-level hardcoded sabit** (VOTE_W_*, CONFLUENCE_MIN_SCORE=20, CONVICTION_HIGH=75...) | `ogul.py:85-284` | P3 | R-11 sistematik ihlal |

**Diğer organlara etki:**
- ← **BABA (Kalp):** `self.baba.can_trade`, `self.baba.check_correlation_limits`, `self.baba.increment_daily_trade_count`
- → **MT5 Bridge (Damar):** `_execute_signal` → `mt5.send_order`; `_manage_active_trades` → `mt5.close_position`, `mt5.modify_position`
- → **H-Engine (Refleks):** `check_transfer` çağırdığında pozisyon H-Engine'e devir; ManuelMotor.get_manual_symbols'ten filtre alır
- → **ÜSTAT (Salgı):** Trade kapanınca `_handle_closed_trade` → events, ÜSTAT _check_error_attribution ile ilgileniyor
- → **Database (Hafıza):** insert_trade, update_trade, insert_event

**Tıkalı damar riski:** **En kritik tıkanıklık burada.** OgulSLTP'nin TP eksikliği + hibrit EOD drift + reason schema uyumsuzluğu üç ayrı damar sıkışması. Her biri kendi başına "yarın kalp krizi yapmaz" ama birleştiğinde: (1) gap senaryosunda pozisyon kontrolsüz açık, (2) ÜSTAT yanlış veri topluyor, (3) stratejiler zamanla yanlış kalibre oluyor. Kademeli bir "bilişsel bozulma".

**Sağlık skoru: 6.5/10**
- Çekirdek trading mantığı sağlam ama AX-4/AX-5 ile drift
- OgulSLTP TP eksikliği Seviye 1 anayasa drift
- Reason schema uyumsuzluğu sessiz data quality kaybı

---

### ORGAN 3 — BEYİNCİK (SE3 sinyal motoru) — `engine/utils/signal_engine.py` 1512 satır

**Rol:** Ana yön kararı için 10 bağımsız (iddia) kaynakta sinyal tarama → konsensüs → strength + total_score + yapısal SL/TP önerme. OGUL `_determine_direction` ve `_generate_signal`'dan çağrılır.

**Kaynaklar (10 adet, A-J):**
A) Structure Break · B) Momentum Ignition · C) Volume Intelligence · D) Compression Release · E) Extreme Reversion · F) VWAP Institutional · G) Smart Divergence · H) Ichimoku Cloud · I) Adaptive Momentum (KAMA) · J) News Event

**Sağlık göstergeleri ✓:**
- 6 kaynak tam bağımsız (A, D, F, H, I, J)
- Rejim-duyarlı eşikler (TREND=2, RANGE=2, VOLATILE=3, OLAY=5 agreeing)
- SOURCE_WEIGHTS ile kaynak bazlı ağırlıklandırma (VWAP 1.3, News 1.3 en yüksek)

**Bulgular:**

| Bulgu | Kanıt | Sınıf | Etki |
|---|---|---|---|
| **Docstring 9 kaynak, kod 10 (J=News)** | `signal_engine.py:12-22` vs `:1269, 1376` | P3 | Belgeleme drift |
| **4 kaynak gösterge çakışması** (StochRSI B↔E, RSI E↔G, OBV C↔G, Volume C↔D↔F) | signal_engine internal | P2 | "10 bağımsız" iddiası efektif ~6-7 bağımsız |
| **`MIN_RISK_REWARD=1.5` sert kapı değil, strength penalty** | `signal_engine.py:1473-1481` | P1 | R:R=0.1 bile geçer (strength × 0.067); "minimum" garantisi yok |
| **`strategy_type` eşleme 2/10 kaynak eksik** (`volume_intelligence`, `news_event` → varsayılan `trend_follow`) | `signal_engine.py:1487-1501` | P2 | Haber-driven sinyal trend yönetimiyle işleniyor, yanlış atfetme |
| **Azınlık fallback: 2/10 ile yön geçebiliyor** | `signal_engine.py:1378-1397` | P2 | Minimum "3/9" docstring iddiasını ihlal ediyor; zayıf konsensüs de geçer |
| **~50 module-level hardcoded sabit** (REGIME_SE2_PARAMS 12, SOURCE_WEIGHTS 10, ROC_STRONG/WEAK, COMPRESSION_*, EXTREME_RSI_*, …) | `signal_engine.py:107-208` | P3 | "Trading beyninin parametreleri" config'te yok |

**Diğer organlara etki:**
- ← **Data Pipeline (Sindirim):** 5 array (open/high/low/close/volume) tüketir
- ← **NewsBridge (Sinir):** `news_bridge` parametresi — opsiyonel, yoksa J kaynak sıfır
- → **OGUL (Beyin):** `_determine_direction` ve `_generate_signal` çağrıları

**Tıkalı damar riski:** Düşük R:R sinyallerin sert filtrede elenmemesi + yanlış strategy_type atfetme, OGUL'un _manage_* stratejilerini yanlış trade'e uygulamasına yol açıyor. Bu doğrudan finansal değil (strength penalty yumuşak filtre sağlıyor) ama **sinyal kalitesi zamanla bozuluyor** — ÜSTAT'ın ölü chain'i (sonraki organ) bunu da fark edemiyor.

**Sağlık skoru: 6.0/10**
- Çok-kaynaklı sistem zengin, rejim-duyarlı eşikler iyi
- MIN_RR bypass doğrudan risk zayıflatıcı
- Docstring + strategy_type eşleme gerçeklikle uyumsuz

---

### ORGAN 4 — REFLEKS SİSTEMİ (H-Engine hibrit motor) — `engine/h_engine.py` 3095 satır

**Rol:** OGUL'dan "devir uygun" sinyali gelince pozisyonu bellekte devralır; breakeven/trailing/PRİMNET yönetir, broker SL ile yazılım SL arasındaki senkronu periyodik doğrular (CI-11). Kullanıcı "hibrit modumu aç" dediğinde operatif.

**Sorumluluk dağılımı:**
- Devir ön kontrolü — `check_transfer:240` (9 adım)
- Atomik devir — `transfer_to_hybrid:405`
- Hibritten çıkarma — `remove_from_hybrid:652`
- Cycle — `run_cycle:693`
- PRİMNET (prim-bazlı uzlaşma fiyatı takip) — 2078, 2116, 2133
- Software SL/TP fallback — `_check_software_sltp:907`
- Trailing via Stop Limit — `_trailing_via_stop_limit:1487`
- Broker SL sync denetimi (CI-11) — `_verify_trailing_sync:1642`
- Zorla kapatma — `force_close_all:1838`
- Orphan temizliği — `_cleanup_primnet_orphans_on_restart:1962`

**Sağlık göstergeleri ✓:**
- OLAY rejiminde `force_close_all("OLAY_REGIME")` uyguluyor (707-713) — AX-6 uyumlu
- `_MAX_CLOSE_RETRIES=3` config ile uyumlu
- Broker SL sync periyodik (`_sync_check_due:890`), canlı verilerde 2 kez SOFTWARE_SL tetiklendiğini gördük — **çalışıyor**
- Orphan temizlik restart'ta aktif
- `_trailing_via_stop_limit` place-first-then-cancel atomiklik desenini kullanıyor

**Bulgular:**

| Bulgu | Kanıt | Sınıf | Etki |
|---|---|---|---|
| **🚨 Hibrit EOD 17:45'te kapatılmıyor (sadece notification)** | `h_engine.py:715-749` | **P0** | AX-5/CI-04 ihlali; overnight gap riski |
| **🚨 `TRADING_OPEN=09:40`, `TRADING_CLOSE=17:50` hardcoded** (config `engine.trading_open=09:45`) | `h_engine.py:61-62` vs `config/default.json:7` | P1 | OGUL 09:45-17:45, H-Engine 09:40-17:50 → 5 dk fark, motorlar farklı zaman penceresinde |
| **`transfer_to_hybrid` atomik değil — DB insert fail → MT5 SL kalır, bellek boş** | `h_engine.py:568-584` | P1 | Zombie state; restart'ta DB'den yükleme olmuyor, MT5 SL gerçek hayatta durur (kontrolsüz pozisyon) |
| **Yön değişimi → pozisyon kapatılmıyor, sadece takibi bırakılıyor** | `h_engine.py:816-854` | **P0** | Korumasız pozisyon potansiyeli (VİOP netting'de nadir ama gerçek) |
| **`_check_primnet_target` retry dolarsa pozisyon açık kalıyor (sessiz fail-soft)** | `h_engine.py:2380-2384` | P1 | Kâr hedefi vurulmuş ama kapatılmamış → gerileme fırsatı kaybı |
| **`modify_pending_order` vs `modify_stop_limit` duplicate** | `mt5_bridge.py:2670 vs 3007` | P3 | Hangisi kullanılıyor belirsiz |
| **CI-11 governance manifest'te yok** (anayasa metninde var, `protected_assets.yaml`'da yok) | `USTAT_ANAYASA.md:75` vs `protected_assets.yaml` | P1 | Koruma koddan uyguluyor ama sicilde tanımsız |

**Diğer organlara etki:**
- ← **OGUL (Beyin):** `check_transfer` çağrısıyla pozisyon devri
- ← **MT5 Bridge (Damar):** `modify_position`, `send_stop_limit`, `cancel_pending_order`
- → **Database (Hafıza):** `insert_hybrid_position`, `update_hybrid_position`, `insert_hybrid_event`

**Tıkalı damar riski:** EOD drift + yön değişimi drift birleşimi en tehlikeli senaryo. Günün sonunda hibrit pozisyon → gece boyunca açık → ertesi gün VİOP gap → SL broker'da sendmiştir umudu varsa (CI-11 periyodik sync bir damarla bunu destekliyor) tamam, yoksa sabahleyin sürpriz. Olasılık düşük ama tetiklendiğinde büyük kayıp.

**Sağlık skoru: 7.0/10**
- PRİMNET sistemi zengin ve çalışıyor, CI-11 broker sync aktif (canlı veride kanıt)
- EOD eksikliği ve yön dönüşü bırakma Seviye 1 drift
- Atomik devir koruması yarım

---

### ORGAN 5 — ELLER / KULLANICI DOKUNUSU (ManuelMotor) — `engine/manuel_motor.py` 1190 satır

**Rol:** Kullanıcının UI'den "al/sat" butonu tetiklediği anda emir açan motor. OGUL'dan bağımsız, kendi `active_trades` sözlüğü var, main loop'ta her cycle `sync_positions` ile MT5'le senkronize oluyor. Kullanıcının SL/TP'sine dokunmuyor, trailing yapmıyor, rejim kapatmıyor — tamamen "kullanıcı bilinçli açtı" felsefesiyle çalışıyor.

**Sorumluluk dağılımı:**
- Manuel emir açma — `open_manual_trade:306` → `mt5.send_order:435`
- MT5 direct position benimseme — `adopt_mt5_direct_position:1006`
- Cycle senkronu — `sync_positions:566-648`
- Restore — `restore_active_trades:872`
- Marker (DB WAL kayıp koruması) — `manual_positions.json` JSON marker

**Sağlık göstergeleri ✓:**
- main.py:920 her cycle çalışıyor
- SENT_EXPIRE_SEC=30 emir timeout koruması var
- State FILLED → EXTERNAL_CLOSE geçişleri yerinde
- Marker JSON yedek koruma (DB WAL kaybolsa bile recover)

**Bulgular:**

| Bulgu | Kanıt | Sınıf | Etki |
|---|---|---|---|
| **🚨 ANAYASADA TANIMSIZ — 5. motor** | `axioms.yaml:16` AX-1: *"BABA → OGUL → H-Engine → USTAT"* — ManuelMotor yok; `protected_assets.yaml` Kırmızı Bölge listesinde 11. olarak YOK | **P0** (yönetimsel) | Authority matrix tanımsız; silinirse test yakalamaz; audit "4 motor" tarar, 5.'yi atlar |
| **🚨 Manuel SL/TP başarısızsa pozisyon kapatılmıyor** | `manuel_motor.py:481-507`: *"SL/TP yazılamasa bile pozisyonu KAPATMA — kullanıcı bilinçli açtı"* | **P0** | AX-4 "korumasız pozisyon yasak" ihlali; BABA `report_unprotected_position` çağrılmıyor bile, sessiz AX-4 ihlali |
| **`get_manual_symbols` iki kez tanımlı, ilki ölü** | `manuel_motor.py:858` ve `1151` | P3 | İkincisi üstüne yazıyor ve state filtresi kaybolmuş → kapalı trade sembolleri cross-motor netting'e sızabilir |
| **`_is_trading_allowed` docstring yalan** (09:45-17:45 diyor, kod 09:40-17:50) | `manuel_motor.py:1181-1190` | P3 | Belgeleme uyumsuzluğu |
| **`TRADING_OPEN=time(9,40), TRADING_CLOSE=time(17,50)` hardcoded** | `manuel_motor.py:66-67` | P2 | H-Engine ile aynı drift; üç motor üç farklı saat penceresi |
| **`"force_closed"` dead branch** — `order_result.get("force_closed")` hiç set edilmiyor mt5_bridge'de | `manuel_motor.py:470-476` | P3 | Ölü kod |
| **~10 module-level hardcoded sabit** (ATR_PERIOD, MIN_BARS_M15, CONTRACT_SIZE, MAX_LOT_PER_CONTRACT, MARGIN_RESERVE_PCT_DEFAULT, MAX_CONCURRENT_MANUAL, SENT_EXPIRE_SEC, SL_ATR_GREEN/YELLOW, PNL_YELLOW_PCT) | `manuel_motor.py:59-77` | P3 | R-11 |

**Diğer organlara etki:**
- ↔ **OGUL + H-Engine + BABA:** Cross-motor referans (Engine `__init__`'te set edilir); `get_manual_symbols`/`get_manual_tickets` netting filtrelerinde kullanılıyor
- → **MT5 Bridge:** `send_order`, `modify_position`, `close_position`
- → **Database + marker:** `insert_trade`, `update_trade`, `manual_positions.json`

**Tıkalı damar riski:** Manuel SL/TP fail durumu nadir ama gerçekleştiğinde — TRADE_ACTION_SLTP broker rejeksiyonu + yazılım SL/TP kullanıcıya "korumalı" diye gösteriyor — **kullanıcı yanıltıcı bir güvenlik duygusu** yaşıyor. Kod yorumu "kullanıcı bilinçli açtı" diyor ama gerçekte kullanıcı "SL koydum, korundum" sanıyor. Bir gece gap'te bu damar kör bir nokta olabilir.

**Sağlık skoru: 6.0/10**
- Çalışıyor, restore çalışıyor, marker koruması var
- Anayasal tanımsızlık + AX-4 özel istisna resmi değil
- "Kullanıcı bilinçli" felsefesi anayasayla çelişiyor

---

### ORGAN 6 — ATARDAMAR VE KILCALLAR (MT5 Bridge) — `engine/mt5_bridge.py` 3171 satır

**Rol:** ÜSTAT'ın kan dolaşımı. Broker ile her iletişim burada. Engine'in MT5'e açılan tek kapısı. Hayati sabah-akşam broker bağlantısı, emir gönderimi, pozisyon kapatma/düzenleme, tick/bar okuma. Circuit breaker ile kendini koruyor.

**Sorumluluk dağılımı:**
- Bağlantı (`connect:628`, `disconnect:753`, `heartbeat:774`) — terminal64.exe process kontrolü
- `_safe_call:189` — ThreadPoolExecutor ile timeout + Circuit Breaker sarmalayıcı (8 sn timeout, 5 ardışık fail → 30 sn CB)
- Sembol çözümleme (`_resolve_symbols:307`, vade son ek hesabı)
- Piyasa verisi (`get_bars:916`, `get_tick:955`)
- Emir gönderme (`send_order:993` + `_send_order_inner:1050` — 2 aşamalı SL/TP)
- Pozisyon (`close_position:1503`, `modify_position:1723`)
- Bekleyen emirler (`send_stop_limit`, `send_limit`, `cancel_pending_order`)
- Tarih senkronu (history için)

**Sağlık göstergeleri ✓:**
- Circuit Breaker çalışıyor (`_cb_is_open:165` probe izni mantığı)
- terminal64.exe process korumalı kapı (AX-15/AX-16)
- Write ops ana thread'de (order_send), read ops worker thread'de (225-267) — doğru mimarı
- RLock kullanımı close_position içi recursive koruma
- Deal lookup retry (10 deneme × 0.5 sn) netting gecikmelerini yakalıyor
- GCM VİOP-özel sltp_request sadeleştirme (1385-1393)

**Bulgular:**

| Bulgu | Kanıt | Sınıf | Etki |
|---|---|---|---|
| **🚨 AX-4 `enforced_in: "engine/mt5_bridge.py::send_order"` — yanlış konum** | `axioms.yaml:39`; gerçek koruma `ogul.py:1879-1943`'te | P1 | Manifest tool'u imzayı PASS veriyor ama davranışı doğrulayamıyor |
| **`send_order` SL/TP fail → sadece log yazıyor, pozisyonu kapatmıyor** | `mt5_bridge.py:1457-1467` | **P0 (yapısal)** | AX-4 davranışı buraya taşınmalı veya axiom düzeltilmeli — KARAR #1 |
| **Retry budgeti toplam ~18 sn** (DEAL_LOOKUP_RETRIES=10, TICKET_MAX_RETRIES=20, SLTP_MAX_RETRIES=5) | `mt5_bridge.py:1323, 1342, 1420` | P1 | CYCLE_INTERVAL=10 sn ile çelişki; tek emir normal seyirde 3-5 sn, patolojik durumda cycle overrun |
| **~10 module-level hardcoded sabit** (MAX_RETRIES_LAUNCH, RECONNECT, BASE_WAIT, HEARTBEAT_INTERVAL, MT5_CALL_TIMEOUT, CB_FAILURE_THRESHOLD, CB_COOLDOWN_SECS, CB_PROBE_TIMEOUT) | `mt5_bridge.py:40-49` | P3 | R-11 |
| **GCM VİOP-özel broker kodu, alternatif broker için test yok** | `mt5_bridge.py:1385-1393` | P2 | Broker değişirse TRADE_ACTION_SLTP sadeleştirme tutmaz |
| **`check_order_status` muhtemelen dead code** | `mt5_bridge.py:2315` — kullanımı Grep ile doğrulanmadı | P3 | — |

**Diğer organlara etki:**
- ← Her şey (BABA, OGUL, H-Engine, Manuel, Data Pipeline) — hemen her motor kan istiyor
- → MT5 terminal (dış dünya)

**Tıkalı damar riski:** **Asıl damar bu.** Damar sağlam — CB var, process koruması var, retry var, RLock var. Ama üç potansiyel tıkanıklık: (1) AX-4 imzası yanlış konumu gösterdiği için audit'te korumasız pozisyon taraması eksik kalıyor; (2) 18 sn retry budgeti cycle threshold'unu aşabiliyor; (3) broker-spesifik kod test edilmemiş. Kalp krizi olmaz ama mini felçler olabilir.

**Sağlık skoru: 8.0/10**
- Mimari çok iyi — CB, RLock, thread ayrımı, process korumalı
- AX-4 manifest-kod uyumsuzluğu en büyük zayıflık (koruma ogul.py'de)
- Retry budget cycle threshold çakışması nadir ama ciddi

---

### ORGAN 7 — OMURİLİK (main.py + api/server.py lifespan) — 1573 + 273 satır

**Rol:** Tüm motor sırasını koordine eder. 10 saniyelik ritim atar (`_main_loop`). Engine oluşturma sırası (`Config → DB → MT5 → Pipeline → ÜSTAT → BABA → OGUL → H-Engine`) omurga. Lifespan — API ayağa kalkışı + graceful shutdown.

**Sorumluluk dağılımı:**
- Engine constructor (`main.py:85-213`, 128 satır) — 8 alt-motor + cross-reference
- Ana döngü (`_main_loop:574`) — heartbeat, cycle, yedekleme, retention
- Tek cycle (`_run_single_cycle:760`) — SABİT SIRA 6 adım
- MT5 reconnect (`_heartbeat_mt5:1144`) — 3 deneme → fail-closed
- Graceful shutdown (`stop:415` — 153 satır)
- State restore (`_restore_state:1424`)
- API lifespan (`api/server.py:71-186`) — Engine yaratımı + engine watchdog (3 restart)

**Sağlık göstergeleri ✓:**
- Call order test var (`test_main_loop_order:3131`)
- Lifespan sırası korunuyor (AX-12)
- Fail-closed `_heartbeat_mt5:1182-1186` — 3 deneme sonrası sistem durdur
- Graceful shutdown zinciri API → engine → MT5 → DB ters sırada (AX-13)

**Bulgular:**

| Bulgu | Kanıt | Sınıf | Etki |
|---|---|---|---|
| **🚨 5. motor (ManuelMotor) anayasada yok ama cycle'da çalışıyor** | `main.py:920` `self.manuel_motor.sync_positions()`; AX-1 tanımıyor | **P0** (yönetimsel) | KARAR #4 |
| **`api/server.py:98` Ogul `risk_params` olmadan yaratılıyor** | api/server.py vs main.py:118-121 | P1 | Ogul.risk_params default RiskParams() (drift ölçümü: canlı riski DÜŞÜK ama gelecek patlama YÜKSEK) |
| **"Engine olmadan da API ayağa kalksın" — mock/debug modu** | `api/server.py:148-150` | P2 | CI-10 fail-closed ile çelişki; engine çökerse UI yanıltıcı "çalışıyor" gösterir |
| **Engine crash watchdog 3 restart → API açık engine kapalı** | `api/server.py:113-142, 135` | P2 | Aynı fail-closed çelişkisi; operatör fark etmeyebilir |
| **Risk kapısı `can_trade=False + risk_multiplier>0` → process_signals hâlâ çağrılıyor** (top5 boş) | `main.py:894-897` | P2 | Temiz tasarım değil; risk_verdict paylaşımı daha iyi olurdu |
| **Cross-motor referans döngüsü (7 çift yönlü bağ)** | main.py:145-163 | P2 | Test ve mock zorlaşıyor |
| **CORS pywebview legacy + Electron `app://.`** | `api/server.py:202-203, 208` | P3 | Ölü CORS origins |
| **~6 module-level hardcoded** (CYCLE_INTERVAL=10, CYCLE_WARN_THRESHOLD=15, CYCLE_CRITICAL_THRESHOLD=30, CONSECUTIVE_SLOW_LIMIT=3) | main.py:53-61 | P3 | R-11 |

**Diğer organlara etki:**
- Tüm motor cycle sırasını belirliyor — bozulursa her organ etkilenir
- Lifespan Engine oluşturma sırası bozulursa constructor dependencies crash (AX-12)
- Fail-closed API watchdog → engine crash sonrası UI yanıltıcı görüntü

**Tıkalı damar riski:** Omurga sağlam — call order test + fail-closed korumaları var. Ama **omurga çatlağı**: ManuelMotor anayasada olmayan bir motor cycle'a girmiş, api/server.py risk_params drift'i, engine crash watchdog'un UI tutarsızlığı — birleştiğinde "işleyen ama tanımsız davranışlı" bir omurga oluyor. Audit araçları bunu tam göremiyor.

**Sağlık skoru: 7.5/10**
- Call order + lifespan + fail-closed ana iskelet sağlam
- ManuelMotor uyumsuzluğu Seviye 1 drift
- Engine crash watchdog'un API'yi açık bırakması koruma ruhuna ters

---

### ORGAN 8 — SİNDİRİM SİSTEMİ (Data Pipeline + Top5 Selection) — `engine/data_pipeline.py` + `engine/top5_selection.py`

**Rol:** Piyasa verisini işle, bar/tick MT5'ten çek, DB'ye upsert et, tazelik tespit et, gap tarama yap. Her 10 sn: 15 kontrat × 4 TF (M1/M5/M15/H1) bar güncellemesi. Top5 her 30 dk'da ham skor → normalize → ortalama → Top5 listesi üretir.

**Sağlık göstergeleri ✓:**
- Gap detection aktif (`_detect_gaps:569`) — canlı log'da dün 30+ gap tespiti
- Bar upsert çalışıyor (`insert_bars:555`)
- Tazelik sınıflandırması (FRESH/STALE/DEAD)
- Engine tarafından Kırmızı Bölge (#7) koruma

**Bulgular (Faz 0-1 doğrudan okunmadı, ama indirekt):**

| Bulgu | Kanıt | Sınıf | Etki |
|---|---|---|---|
| **Dün (16 Nisan) çok sayıda M1 gap (180-360 sn)** — TCELL, HALKB, PGSUS, GUBRF vb. | Bugünkü log 08:41 detect_gaps çıktısı | P2 (operasyonel) | Broker tarafı likidite düşüklüğü veya MT5 bağlantı kesintisi olabilir. Sinyal kalitesi etkiler |
| **OGUL `_is_new_m5_candle` tek sample SPOF** — top5[0] gecikirse 5 sembol kapanıyor | Organ 2 bulgusu | P1 | Pipeline arızası → sinyal akışı durmasına dönüşüyor |
| **Data Pipeline Kırmızı Bölge ama Faz 0-1 okumasında hedefli inceleme yok** | protected_assets.yaml | — | Faz 2'de auditor incelemesi gerekli |

**Diğer organlara etki:**
- → Tüm motorlar: OGUL, H-Engine, Top5, BABA veri kaynağı
- ← MT5 Bridge: `get_bars`, `get_tick`, `get_positions`
- → Database: `insert_bars`, `insert_tick_history`

**Tıkalı damar riski:** Dün gün içi gap sayısı "normal" mi yoksa istisna mı bilmiyoruz. Sistematik bar gap'i hem SE3 hem BABA rejim algılamasını bozabilir. **Audit gerekli damar.**

**Sağlık skoru: 6.5/10** (Kanıt eksik; Faz 2'de hedefli incelemeye alınmalı)

---

### ORGAN 9 — HAFIZA (Database) — `engine/database.py` 2058 satır + `trades.db` 71 MB

**Rol:** Her kararın sicili. 19 tablo (docs 16 diyor — drift). Trade geçmişi, risk snapshot, event log, hibrit pozisyonlar, top5 history, notifications, MT5 journal. WAL + SHM thread-safe yazım. Günlük yedek, retention, vacuum.

**Sağlık göstergeleri ✓:**
- `trades.db` 71 MB sağlıklı büyüme (1 haftada 71 MB → günlük ~10 MB)
- WAL 4.1 MB (normal), SHM 32 KB
- Günlük yedek sistemi çalışıyor (16 Nisan 3 yedek)
- `PRAGMA quick_check` başlangıçta
- Migration idempotent (`_migrate_schema:365-383` try/except ALTER TABLE)
- Retention (`run_retention`, `archive_old_trades`, `wal_checkpoint`, `vacuum`)

**Bulgular:**

| Bulgu | Kanıt | Sınıf | Etki |
|---|---|---|---|
| **`ustat.db` 0 byte ÖLÜ DOSYA** | `database.py:35` sadece trades.db bağlanıyor | P3 | CLAUDE.md drift — `ustat.db` motor DB diye yazıyor |
| **19 tablo (docs 16)** — `backtest_bars`, `error_resolutions`, `sqlite_sequence` eklenmiş | Canlı `sqlite_master` sorgusu | P3 | Dokümantasyon güncelleme |
| **3 yedek aynı günde** (16 Nisan 06:48, 06:52, 07:52) × 71 MB = 213 MB disk fazladan | `database/` listele | P3 | Yedek retention politikası: günde 1 yeterli |
| **`archive_old_trades` atomik değil** — INSERT+DELETE ayrı, ama `INSERT OR IGNORE` koruyor | `database.py:1496-1574` | P3 | Edge case tolerans yeterli |
| **`severity` notation tutarsızlığı** — events UPPERCASE, notifications lowercase | database.py CREATE TABLE | P3 | Dashboard filtre karışıklığı |
| **`_event_dedup_cache` class-level dict, thread-safety zayıf** (engine tek instance olduğu için çalışıyor) | `database.py:1128` | P3 | Gelecekte multi-worker API regresyon |
| **PRAGMA quick_check engine durdurmuyor, sadece log** | database.py:291-303 | P2 | Fail-closed ruhu ile çelişki |
| **SQL string interpolation `deduplicate_trades`** (integer set güvenli ama desen riskli) | database.py:867, 872-874, 890-893 | P3 | Parametrized sorgulama daha güvenli |

**Diğer organlara etki:**
- ← Tüm motorlar yazıyor
- → ÜSTAT persistence overlay (strategy pool), BABA restore_risk_state

**Tıkalı damar riski:** Hafıza sağlam, akut risk yok. Yedek retention politikası disk yükünü ciddi şekilde artırıyor. `ustat.db` ölü dosya dokümantasyon yanıltıcılığı. **Sessiz damar** — iyi işliyor ama temizlik gerekiyor.

**Sağlık skoru: 8.0/10**
- Sağlam şema, retention, WAL yönetimi
- Dokümantasyon drift (19 vs 16 tablo, ustat.db)
- Yedek retention temizliği gerekli

---

### ORGAN 10 — SİNİR SİSTEMİ (İÇ) — event_bus, error_tracker, health, news_bridge

**Rol:** Motorlar arası iletişim + dış dünyadan uyarı alımı + kendi içindeki semptom izleme. event_bus (olay yayını), error_tracker (hata izleme), health (sağlık metrikleri), news_bridge (bloomberght RSS + MT5 journal haber feed).

**Sağlık göstergeleri ✓:**
- Event emission sürekli — bugünkü log'da event tipleri: KILL_SWITCH, TRADE_OPEN/CLOSE, RISK_DECISION, SIGNAL_GENERATED, CYCLE_TIME
- health.py sağlık skoru üretiyor (API `/api/health`)
- news_bridge 1550 satır, OLAY rejim tetiğinde kritik
- Config'te haber kaynakları tanımlı (`config/default.json:148-169`)

**Bulgular (Faz 0-1 doğrudan okunmadı, dolaylı):**

| Bulgu | Kanıt | Sınıf | Etki |
|---|---|---|---|
| **NewsBridge SE3'ün J kaynağı için kritik, ama içi incelenmemiş** | signal_engine.py:1208-1251 J kaynak | P2 | Faz 2 auditor gerekli |
| **news_bridge 1550 satır — boyut/karmaşıklık işareti** | — | P2 | Auditör incelemesi gerekli |
| **Error tracker ile ÜSTAT `_check_error_attribution` iletişimi belirsiz** | — | P2 | Faz 2 |
| **Bugünkü 875 WARN/ERROR/CRITICAL sayımı profil çıkarılmamış** | logs/ustat_2026-04-17.log | P2 | Log digest yapılmalı |

**Diğer organlara etki:**
- → BABA: news_bridge OLAY tetiği (regime=OLAY, risk_multiplier=0.0)
- → SE3: NewsBridge sentiment → news_event kaynak puan
- → ÜSTAT: error_tracker hata atfetme veri kaynağı (KARAR #6 bağlantılı)
- → Dashboard: events & notifications → WebSocket /ws/live

**Tıkalı damar riski:** News haber feed bozuksa BABA yanlış rejim algılayabilir — **bu çok önemli ama şu ana kadar incelenmedi**. OLAY rejimine girmemesi = volatil haber saatinde normal lot ile işlem = potansiyel büyük kayıp. NewsBridge bu check-up'ın en boşluklu organı.

**Sağlık skoru: 6.0/10** (Kanıt eksik; öncelikli Faz 2 inceleme hedefi)

---

### ORGAN 11 — SALGI BEZLERİ / ÖĞRENME (ÜSTAT) — `engine/ustat.py` 2195 satır

**Rol:** Sistemin "deneyim öğrenen" organı. Açılan işlemlerin sebeplerini geriye dönük inceleyip BABA'ya geri bildirim gönderir: "Şu strateji çok kaybettirdi, parametre sıkılaştır." Strateji havuzunu runtime'da günceller. Hata atfetmesi yapar (hangi motor hata etti?).

**Sorumluluk dağılımı:**
- Olay kaydı — `_track_events:234`
- Hata atfetme — `_check_error_attribution:335`, `_determine_fault:446`
- Risk kaçırma → BABA feedback — `receive_feedback`
- Açılamayan işlem raporu — `_check_unopened_trades:546`
- Ertesi gün analizi — `_run_next_day_analysis:666`
- Strateji havuzu — `_update_strategy_pool:1126` (4 profil)
- Kontrat profilleri — `_update_contract_profiles:1182`
- Regülasyon önerileri + feedback — `_generate_regulation_suggestions:1280`, `_apply_regulation_feedback:1375`, `_apply_baba_feedback:1524`
- Persistence — `_load_persisted_state:1748`, `_save_persisted_state:1850`
- 30dk intraday — `_run_intraday_check:1002`

**Sağlık göstergeleri ✓:**
- "İyi gideni bozma" kuralı (`overall_wr>60` → parametre dokunma) 1404-1410
- Persistence overlay (DB'den strateji havuzu parametrelerini module-level'a yükler) 1787-1808
- Cycle'da her 1800 sn'de bir pool güncellemesi

**Bulgular:**

| Bulgu | Kanıt | Sınıf | Etki |
|---|---|---|---|
| **🚨 DEAD BUG: `strategy_dist` key hiç oluşmuyor** | `ustat.py:2104-2108`, gerçek key `by_strategy`; for döngüsü hep boş | **P0** (veri bütünlüğü) | `strategy_win_rates` ve `strategy_trade_counts` her zaman boş → OGUL strateji tercih bonusu uygulamıyor |
| **🚨 Reason schema uyumsuzluğu — `_determine_fault` UPPERCASE arıyor, OGUL lowercase üretiyor** | `ustat.py:446-540`; "SL_HIT" vs OGUL "sl_tp" | **P0** (veri bütünlüğü) | Hata atfetme HİÇ eşleşmiyor → dashboard'da motor hatası gösterilemez |
| **ÜSTAT Siyah Kapı'da DEĞİL** — ustat.py fonksiyonları BK listesinde yok | `protected_assets.yaml` | P2 | Mantık değişebilir; tek sigorta Kırmızı Bölge dosya koruması |
| **Module-level MUTABLE `STRATEGY_PROFILES` dict** (`_apply_regulation_feedback` runtime'da modifiye ediyor) | ustat.py:38-91, 1447, 1460, 1482 | P2 | Tek instance sağlıklı ama kod kokusu |
| **Module-level hardcoded** (`ATTRIBUTION_MIN_LOSS=100, MAX_ATTRIBUTIONS=50, STRATEGY_POOL_INTERVAL_SEC=1800, DEDUP_CACHE_TTL_SEC=3600`) | ustat.py:102-111 | P3 | R-11 |
| **Kod-config-DB 3 kaynak drift** (`config/default.json strategies` vs `ustat.py STRATEGY_PROFILES` vs DB persist) | ustat.py:38-91 vs config/default.json | P2 | trend_follow.sl_atr_mult config=1.5 vs code=1.8 |

**Diğer organlara etki:**
- ← OGUL: trade kapanınca sebep ve veri
- → BABA: `receive_feedback` risk parametre sıkılaştırma
- → Strateji profilleri: OGUL stratejileri hangi parametreyle çalıştıracak
- → Database: strateji pool persistence

**Tıkalı damar riski:** **En kritik "tıkalı damar" bu organda.** ÜSTAT'ın varlık amacı = öğrenmek. Ama dead bug + reason uyumsuzluğu yüzünden **fiilen öğrenmiyor**. Dashboard operatöre "şu stratejide hata var" demiyor, R-Multiple yanlış, strategy_win_rates boş. Sistem zamanla **algoritmik başı boşluğa** sürüklenir. Bu ani ölüm değil, **kademeli bilişsel bozulma** — 2-3 ay sonra kötü strateji kalibrasyonu kayıpların artmasına yol açabilir.

**Sağlık skoru: 4.0/10** — Çalışıyor ama **dead chain**. KARAR #6 en öncelikli.

---

### ORGAN 12 — BAĞIŞIKLIK SİSTEMİ (kill-switch + circuit breaker + fail-closed)

**Rol:** Tehdit algılayıp savunma başlatan sistem. L1 (sembol bazlı), L2 (günlük/aylık/consecutive kayıp), L3 (hard drawdown %15 — felaket). MT5 Bridge Circuit Breaker (5 ardışık timeout → 30 sn). main.py fail-closed (MT5 kurtarılamaz → sistem durdur).

**Bulgular (KARAR #2 AX-3 monotonluk):**

| Bulgu | Kanıt | Sınıf |
|---|---|---|
| **🚨 AX-3 "otomatik düşürme yasak" — 2 yerde ihlal** | baba.py:2884-2890 (OLAY kalkınca L2→L0) + baba.py:1407-1419 (_reset_daily L2+L1 temizlik) | P1 |
| **CB probe izni mantığı doğru** | mt5_bridge.py:165 | ✓ |
| **Fail-closed _heartbeat_mt5 3 deneme sonrası sistem durdur** | main.py:1182-1186 | ✓ |
| **api/server.py engine crash → API açık kalıyor (fail-closed çelişki)** | api/server.py:148-150, 135 | P2 |
| **CI-10 (fail-closed) korunması var ama operasyonel katmanda sızıntı** | api/server.py watchdog | P2 |

**Diğer organlara etki:**
- → Tüm motorlar (kill-switch level)
- ← BABA (L1/L2/L3 orkestrasyonu)
- ← mt5_bridge (CB durumu)
- ← main.py (fail-closed)

**Tıkalı damar riski:** Bağışıklık "sıkı okumada" zayıf — otomatik temizleme AX-3'e ters. Ama operasyonel bakımdan günlük reset mantıklı. Asıl risk: api/server.py'nin engine crash'te "ayağa kalkmış gibi" görünmesi — kullanıcı MT5'i açıp "çalışıyor" sanabilir. Bu bir **sessiz immün yetmezlik**.

**Sağlık skoru: 7.5/10** — Çoğunluk sağlam, 2 drift + 1 çelişki

---

### ORGAN 13 — CİLT (API katmanı) — `api/server.py` 273 + `api/routes/*` 23 dosya

**Rol:** Dış iletişim katmanı. FastAPI REST + WebSocket `/ws/live`. 23 router modülü (canlı verilere göre — docs 20 diyor, drift). CORS policy. SPA static fallback.

**Bulgular:**

| Bulgu | Kanıt | Sınıf |
|---|---|---|
| **23 router, docs 20** | api/routes/ listesi | P3 (drift) |
| **CORS kalıntıları: pywebview + Electron `app://.`** | api/server.py:202-208 | P3 |
| **SPA fallback dist yoksa JSON** | api/server.py:247-273 | ✓ (dev-mode uygun) |
| **Router dosyaları Faz 0-1'de derin okunmadı** | — | P2 (Faz 2 gerekli) |

**Sağlık skoru: 7.0/10** (Faz 2 auditor gerekli — router davranışları test edilmedi)

---

### ORGAN 14 — DUYU ORGANLARI (Electron + React UI) — `desktop/` + 21 JSX bileşeni

**Rol:** Kullanıcının sistemi gördüğü pencere. LockScreen (MT5 kimlik + OTP), Dashboard, Monitor, RiskManagement, AutoTrading, HybridTrade, ManualTrade, ErrorTracker, NewsPanel, PrimnetDetail vb. Windows native pencere yönetimi (titleBarStyle:'hidden' + titleBarOverlay).

**Bulgular:**

| Bulgu | Kanıt | Sınıf |
|---|---|---|
| **21 JSX, docs 20 — Nabiz.jsx (660 satır) drift** | desktop/src/components/ listesi | P3 |
| **Production build zorunluluğu — `desktop/dist/` olmadan Electron eski bundle yükler** | CLAUDE.md Bölüm 7 ADIM 1 | ✓ (kullanıcı bilgilendirilmiş) |
| **mt5Manager.js 535 satır — OTP otomasyonu Sarı Bölge** | desktop/mt5Manager.js | ✓ |
| **Component içerikleri Faz 0-1'de okunmadı** | — | P2 (Faz 2 auditor) |
| **OGUL _ogul_enabled=False default UI'da nasıl gösteriliyor belirsiz** | AutoTrading.jsx? — doğrulanmadı | P2 |

**Sağlık skoru: 7.0/10** (UI Faz 2 auditor'a devredilecek alanlar)

---

### ORGAN 15 — İSKELET (Governance + Config + Anayasa)

**Rol:** Sistemin "değiştirilemez" katmanı. `config/default.json` 189 satır (risk parametreleri, saatler, MT5 yolu, haber feeds, strateji ayarları). `governance/` 4 YAML (axioms, protected_assets, authority_matrix, triggers). `USTAT_ANAYASA.md` 294 satır. `CLAUDE.md` (ana rehber). `CLAUDE_CORE.md` (L1 yükleme).

**Sağlık göstergeleri ✓:**
- manifest_version 3.0 axioms + authority + triggers
- Hash-based anayasa koruma (anayasa_sha256)
- check_constitution.py + check_triggers.py + seal_change.py + session_gate.py araçları
- Pre-commit hook zinciri

**Bulgular:**

| Bulgu | Kanıt | Sınıf |
|---|---|---|
| **🚨 `constitution_version: "2.0"` vs anayasa v3.0** | protected_assets.yaml:7 vs USTAT_ANAYASA.md:3 | P1 |
| **🚨 CI-11 anayasada var, protected_assets'te yok** | USTAT_ANAYASA.md:75 vs protected_assets.yaml | P1 |
| **AX-4 `enforced_in` yanlış konum** | axioms.yaml:39 | P1 (KARAR #1) |
| **AX-1 5. motor tanımsız** | axioms.yaml:16 | P1 (KARAR #4) |
| **R-XX sayım tutarsızlığı** — anayasa "16 kural" atfı, protected_assets 12 R-XX | USTAT_ANAYASA.md:D vs protected_assets.yaml | P2 |
| **Protected config keys eksik** — `risk.max_correlated_positions`, `engine.margin_reserve_pct` vs sicilde yok | protected_assets.yaml | P2 |
| **TR-MAGIC sadece yeni eklemeleri yakalıyor, mevcut ~200 hardcoded sabit korumasız** | triggers.yaml:110-114 | P2 |
| **CLAUDE.md ve CLAUDE_CORE.md başlıkları "v5.9"** (kod v6.0, desktop productName "v5.7") | docs | P3 (KARAR #4 ile ilgili) |

**Diğer organlara etki:**
- Tüm organlar config okuyor
- governance tool'ları pre-commit zincirinde davranıyor
- anayasa_sha256 mismatch → check_constitution.py CI kırılır

**Tıkalı damar riski:** İskelet "kırık" — üç belge (anayasa metni, manifest, CLAUDE.md) üç farklı versiyon söylüyor. Araçlar çalışıyor ama yanlış bir doğruyu kontrol ediyor. **Teşhis zorlaşıyor** — yeni geliştirici "neyin doğru olduğunu" anlamakta zorlanır.

**Sağlık skoru: 5.5/10** — Yapı var, senkronu bozuk

---

### ORGAN 16 — BAĞIŞIKLIK HAFIZASI (Test Katmanı) — `tests/critical_flows/test_static_contracts.py` 3504 satır, 55 test + diğer test dosyaları

**Rol:** Kod değişikliklerinin anayasal garantileri bozmamasını pre-commit + CI'da otomatik test eder. Davranış testi değil, çoğu **string presence** veya **hasattr** sözleşme testi.

**Bulgular:**

| Bulgu | Kanıt | Sınıf |
|---|---|---|
| **55 testin çoğu string/imza testi, davranış testi eksik** | tests/critical_flows/test_static_contracts.py | P1 (KARAR #10) |
| **`test_ogul_has_end_of_day_check` sadece "17" ve "45" string arıyor** — hibrit kapatma davranışı test edilmiyor | satır 83-93 | P1 |
| **`test_baba_l2_only_closes_ogul_and_hybrid` sadece `hasattr`** | satır 3082 | P1 |
| **`test_baba_l3_closes_all_positions` sadece `hasattr`** | satır 3092 | P1 |
| **`test_ogul_respects_baba_can_trade_gate` source'ta "can_trade" string arıyor** | satır 3101 | P1 |
| **`test_main_loop_order` regex BABA idx < OGUL idx** — yeni motor araya girerse geçer | satır 3131 | P1 |
| **`test_no_rogue_mt5_initialize_calls` AST tabanlı GERÇEK davranış testi ✓** | satır 3161-3214 | ✓ |
| **`test_sltp_failure_closes_unprotected_position` string pattern arama** | satır 50-79 | P1 |
| **CI-11 testi (`test_broker_sl_sync_periodic_check_contract`) var ama içeriği okunmadı** | satır 3458 | P2 |

**Diğer organlara etki:**
- Pre-commit engine değişikliklerini test ediyor
- KARAR #1, #2, #3 sonrasında davranış testleri yazılmalı

**Tıkalı damar riski:** Bağışıklık hafızası yüzeyde iyi görünüyor ama **gerçek tehdidi tanımıyor**. KARAR #3 (hibrit EOD) bunun kanıtı: kodda hibrit kapatılmıyor, ama string testi "17" ve "45" görüyor → test yeşil. Bu en sinsi tıkanıklık. Geliştirici refactor yaparken tested feeling ile yanlış değişiklik yapabilir.

**Sağlık skoru: 4.5/10** — Kapsama var, davranış doğrulaması zayıf

---

### ORGAN 17 — YAN SİNİR AĞI (ustat_agent.py + Claude Bridge) — 3781 satır + tools/

**Rol:** Claude/Cowork ↔ Windows köprüsü. 53 komut handler'ı (docs 37 diyor — drift): uygulama yönetimi, sistem durumu, DB query, log oku, shell, screenshot, FUSE bypass, Cowork window/clipboard/system_info. Singleton koruması PID + psutil. Atomik komut kilitleme `.processing` rename. Claude Agent SDK'nın otomasyonu için omurga.

**Sağlık göstergeleri ✓:**
- Singleton koruması çalışıyor
- 53 komut hepsi tanımlı
- db_query SADECE SELECT — koruma var
- file_write SADECE `.agent/` — koruma var
- Shell timeout 120 sn

**Bulgular:**

| Bulgu | Kanıt | Sınıf |
|---|---|---|
| **CLAUDE.md "37 komut, 3686 satır", gerçek "53 komut, 3781 satır"** | docs drift | P3 |
| **tools/ klasörü (check_constitution, impact_map, rollback/*.sh vb.) Faz 0-1'de doğrudan okunmadı** | — | P2 (Faz 2 gerekli) |
| **.githooks/pre-commit içeriği doğrulanmadı** | — | P2 |

**Sağlık skoru: 7.5/10** (Yan ağ sağlam, dokümantasyon drift, tools/ derin incelemesi gerekli)

---

## 4. ORGAN ETKİLEŞİM MATRİSİ (DAMAR HARİTASI)

Her organ diğerine hangi kanallarla bağlı ve biri tıkanınca hangisi hangi etkiyi alıyor. Matrix kısaltma: **H** (doğrudan data/çağrı), **S** (state paylaşımı), **F** (feedback), **T** (tetik/olay).

### 4.1 Matris tablo (kaynak → hedef)

| Kaynak \ Hedef | 1 Kalp | 2 Beyin | 3 Beyincik | 4 Refleks | 5 Eller | 6 Damar | 7 Omur | 8 Sindirim | 9 Hafıza | 10 Sinir | 11 Salgı | 12 Bağış | 13 Cilt | 14 Duyu | 15 İskelet | 16 Test | 17 Yan |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **1 Kalp** (BABA) | — | **H**(can_trade, correlation, increment) | — | T (L2→force_close) | T (L2→close_hybrid) | — | F(risk_verdict) | — | S(risk_snapshot insert) | T(kill_switch event) | F(receive_feedback) | **H**(L1/L2/L3 karar) | — | — | — | — | — |
| **2 Beyin** (OGUL) | F(increment_daily, correlation check) | — | **H**(SE3 çağrı) | T(check_transfer) | S(get_manual_symbols filter) | **H**(send_order, close, modify) | F(process_signals) | H(get_bars) | S(insert_trade) | T(TRADE_OPEN/CLOSE event) | T(trade closed → fault) | ← can_trade gate | — | — | ← config | ← test_static | — |
| **3 Beyincik** (SE3) | — | H(signal verdict return) | — | — | — | — | — | H(bars input) | — | H(news_bridge) | — | — | — | — | ← config (ama ~50 hardcoded, çoğu yok) | — | — |
| **4 Refleks** (H-Engine) | ← correlation / OLAY | ← check_transfer | — | — | S(get_hybrid_tickets filter) | **H**(modify, send_stop_limit, cancel) | ← run_cycle | — | S(insert_hybrid, update_hybrid) | T(hybrid_events, notifications) | — | ← kill_switch | — | — | ← config (ama 09:40 hardcoded) | ← test | — |
| **5 Eller** (Manuel) | ← risk_params | S(get_manual_symbols) | — | S(get_manual_tickets) | — | **H**(send_order, modify, close) | ← sync_positions | — | S(insert_trade, marker JSON) | T(TRADE_OPEN event) | — | ← kill_switch (L3 only) | — | — | ← config (kısmi) | ← test (yok) | — |
| **6 Damar** (MT5) | — | H(order result) | — | H(pos info) | H(pos info) | — | F(health) | H(bars, tick, positions) | — | — | — | T(CB trip/clear) | — | — | ← config.terminal_path | ← test | — |
| **7 Omurga** (main+lifespan) | **H**(run_cycle) | **H**(process_signals) | — | **H**(run_cycle) | **H**(sync_positions) | **H**(heartbeat) | — | **H**(run_cycle) | — | — | **H**(run_cycle) | — | ← uvicorn | — | ← config | ← test | ← agent |
| **8 Sindirim** (Pipeline) | H(regime input) | H(bars input) | H(bars input) | H(bars input) | — | ← get_bars | — | — | S(insert_bars) | T(gap events) | — | — | — | — | ← config (top5 params) | — | — |
| **9 Hafıza** (DB) | H(restore_risk) | H(restore_active_trades) | — | H(restore hybrid) | H(restore manuel) | — | — | H(bars retention) | — | H(event_bus persist) | **H**(strategy pool load) | — | H(API reads) | — | — | — | H(ustat_agent db_query) |
| **10 Sinir** (event/error/health/news) | T(news→OLAY) | T(news→spread spike) | T(news→news_event) | T(notifications) | — | — | — | T(gap) | ← event log | — | T(error_attribution trigger) | T(alarm) | WebSocket /ws/live | UI render | — | — | — |
| **11 Salgı** (ÜSTAT) | F(risk param tightening) | F(strategy profile update) | — | — | — | — | ← run_cycle | — | S(persist strategy pool) | — | — | — | H(API brain endpoint) | UI brain panel | — | — | — |
| **12 Bağışıklık** (kill-switch+CB) | ← level state | T(can_trade=False) | — | T(force_close_all OLAY) | T(L3 only) | ← CB trip (5 fail→30s) | T(fail-closed shutdown) | — | S(event kill_switch) | T(alarm) | — | — | — | — | — | — | — |
| **13 Cilt** (API+routes) | H(/api/risk) | H(/api/top5, ogul-toggle) | — | H(/api/hybrid_trade) | H(/api/manual_trade) | — | ← lifespan | — | H(reads) | H(WebSocket) | H(/api/ustat-brain) | H(/api/killswitch) | — | H(HTTP/WS) | — | — | — |
| **14 Duyu** (Electron+React) | — | — | — | — | UI trigger | H(mt5Manager OTP) | ← lifespan | — | — | WebSocket consumer | — | UI alarm | — | — | — | — | — |
| **15 İskelet** (config+governance) | **H**(load) | **H**(load) | kısmen(load) | **H**(load) | **H**(load) | H(terminal_path) | H(load) | H(load) | — | H(news sources) | H(persist overlay) | — | — | — | — | H(test assertions) | H(tools config) |
| **16 Test** (critical_flows) | T(pre-commit check) | T(pre-commit check) | — | T(pre-commit check) | T(pre-commit check) | T(pre-commit check) | T(call order) | — | — | — | — | — | — | — | ← manifest hash check | — | — |
| **17 Yan** (agent+tools) | H(read state) | H(read state) | — | H(read hybrid) | H(read manuel) | ← terminal check | H(start/stop/restart) | H(tail_log) | H(db_query SELECT) | H(search_all_logs) | — | — | H(via API endpoints) | — | H(check_constitution) | H(pytest trigger) | — |

### 4.2 Güçlü bağlantılar (H — doğrudan çağrı)

Kritik damarların her biri **bir motor çökerse birden fazla organ etkilenir**:

1. **Damar (MT5 Bridge)** — 7 organ doğrudan çağırıyor. Çökerse: BABA+OGUL+H-Engine+Manuel+Pipeline+API+Test hepsi durur. **Ama CB + fail-closed koruması var** → kontrollü çöküş.
2. **Omurga (main.py)** — Tüm motorları çağırıyor. Çökerse: sistem durur. **Ama call order test + lifespan sırası koruması var** → düzenli shutdown.
3. **İskelet (config + governance)** — 15+ organ config okuyor. Bozulursa → yanlış kalibrasyon. **Doğrudan koruma: `check_constitution.py` + pre-commit**.
4. **Hafıza (DB)** — 10+ organ yazıyor/okuyor. Bozulursa → state kaybolur, restart başarısız. **PRAGMA quick_check + WAL + yedek + vacuum koruması var**.

### 4.3 Tıkalı damar senaryoları (kritik bağlantılar)

Bu senaryolar **yarın semptom vermeyebilir ama önümüzdeki haftalarda tetiklenebilir**:

#### **Senaryo A — Hibrit EOD → Overnight Gap → Kontrolsüz Kayıp**
Zincir: Beyin (OGUL 17:45 hibrite dokunmuyor) → Refleks (H-Engine sadece notification, kapatmıyor) → sabah piyasa açılırken gap → PRİMNET daily settlement ile uzlaşma fiyatı değişti ama SL broker'da takip etmedi → (H-Engine'de CI-11 broker sync sonra kontrol edecek ama sabah 09:30 anında gap olmuş) → kontrolsüz kayıp.
**Koruyucu katmanlar:** (1) daily settlement 21:35; (2) CI-11 periyodik sync. **Ama 09:25-09:30 gap olursa 2 katman da aktif değil.**
**Olasılık:** AYLIK 1-2 kez. **Etki:** Pozisyon büyüklüğüne göre 500-5000 TL.

#### **Senaryo B — AX-4 Üç Motor Farklı Uygulama → Korumasız Pozisyon**
Zincir: Broker TRADE_ACTION_SLTP rejekte → OgulSLTP fallback (SL koyuyor, TP koymuyor) → pozisyon TP'siz açık → kâr hedefe ulaşıp geri dönebiliyor → OR → Manuel SL/TP fail → kullanıcı "SL var" sanıyor ama MT5'te yok → gece gap.
**Koruyucu katmanlar:** OgulSLTP SL var, trailing eventual TP kuruyor. **Ama Manuel için hiç koruma yok.**
**Olasılık:** Manuel koruma fail — nadir ama kullanıcı haber verilmiyor. **Etki:** Büyük.

#### **Senaryo C — ÜSTAT Dead Chain → Kademeli Strateji Kalibrasyon Kaybı**
Zincir: `strategy_dist` key bug + reason schema uyumsuzluğu → ÜSTAT her cycle'da trade kapatmalarını inceliyor ama hiç eşleşme bulamıyor → `strategy_win_rates` boş kalıyor → BABA'ya feedback verilmiyor → OGUL `get_active_params()` strateji tercih bonusu uygulayamıyor → kötü stratejiler zamanla kalıcılaşıyor.
**Koruyucu katmanlar:** Module-level `STRATEGY_PROFILES` statik default var — OGUL en azından default parametreleri kullanıyor. **Ama adaptasyon sıfır.**
**Olasılık:** HER GÜN. **Etki:** 3-6 ayda %5-10 net performans farkı.

#### **Senaryo D — ManuelMotor Anayasada Yok → Audit Kör Nokta**
Zincir: Yeni geliştirici (veya AI ajan) "anayasa 4 motor" görüyor → manuel_motor.py'yi refactor ediyor → Siyah Kapı korumasız olduğundan test yakalayamıyor → kullanıcı manuel emir açtığında beklenmedik davranış.
**Koruyucu katmanlar:** manuel_motor.py Kırmızı Bölge dosya listesinde YOK → silme koruması yok.
**Olasılık:** Nadir (bakım senaryosu). **Etki:** Sistem seviyesi kırılma.

#### **Senaryo E — Kill-Switch Otomatik Temizleme → Tetik Etkisi**
Zincir: Haberden (OLAY) sistem L2'ye girdi → 30 dk sonra haber rejimi kalktı → L2 otomatik temizlendi → haber sonrası volatilite dalgası devam ediyordu (gerçekte 45-60 dk daha sürer) → OGUL işlem açtı → zarar.
**Koruyucu katmanlar:** Rejim algılaması volatilite tespit edebilir (ATR spike → VOLATILE). **Ama TREND gelirse normal.**
**Olasılık:** AYLIK 1 kez. **Etki:** Orta.

#### **Senaryo F — Data Pipeline Gap → SE3 Sinyal Kalitesi Kaybı**
Zincir: Dün 16 Nisan gün içi 30+ bar gap (180-360 sn) → SE3 KAMA slope hesabı eksik veriye dayanıyor → yanlış sinyal gücü → OGUL _is_new_m5_candle top5[0] gecikirse 5 sembol sinyal yok → fırsat kaybı + yanlış sinyal.
**Koruyucu katmanlar:** Veri tazelik sınıflandırması var (FRESH/STALE/DEAD). Ama OGUL STALE'i hâlâ kullanıyor.
**Olasılık:** Broker tarafı bağlantı arızası günlerinde. **Etki:** Orta.

#### **Senaryo G — api/server.py Risk Params Drift → Gelecekte Patlama**
Zincir: Kod bakımı sırasında biri OGUL'da `self.risk_params.max_daily_trades` kontrolü ekler (şu an kullanılmıyor) → api/server.py yolunda default 8 vs main.py yolunda config 5 → ikisinin farklı değerde olduğu fark edilmiyor → production'da günde 8, test'te 5 → tutarsız davranış, debug zorluğu.
**Koruyucu katmanlar:** Şu anda bu alan OGUL kodunda kullanılmıyor. **Gelecek refactor anında patlar.**
**Olasılık:** Düşük (planlı bir refactor olmazsa). **Etki:** Bulunması zor, büyük.

---

## 5. ORGAN-ORGAN SAĞLIK SKORU ÖZETİ

### 5.1 Skor listesi (yüksek→düşük)

| Organ | Skor | Durum | Ana sebep |
|---|---|---|---|
| 1. Kalp (BABA) | **8.0/10** | İYİ | AX-3 drift + L3 retry blokaj |
| 6. Damar (MT5 Bridge) | **8.0/10** | İYİ | AX-4 manifest-kod uyumsuzluğu |
| 9. Hafıza (DB) | **8.0/10** | İYİ | docs drift (19 vs 16 tablo), ustat.db ölü |
| 12. Bağışıklık | **7.5/10** | İYİ | AX-3 monotonluk ihlali + api fail-closed çelişki |
| 7. Omurga (main) | **7.5/10** | İYİ | 5. motor anayasa dışı + API engine crash drift |
| 17. Yan Ağ (agent) | **7.5/10** | İYİ | docs drift (53 vs 37 komut) |
| 4. Refleks (H-Engine) | **7.0/10** | ORTA | EOD + yön dönüş drift |
| 13. Cilt (API) | **7.0/10** | ORTA | CORS kalıntı + Faz 2 eksik |
| 14. Duyu (UI) | **7.0/10** | ORTA | Faz 2 auditor eksik |
| 8. Sindirim (Pipeline) | **6.5/10** | ORTA | Gap sorgu + Faz 2 eksik |
| **2. Beyin (OGUL)** | **6.5/10** | **ORTA** | AX-4 TP yok + EOD + reason schema |
| **5. Eller (Manuel)** | **6.0/10** | **ORTA** | Anayasasız + AX-4 istisna |
| 3. Beyincik (SE3) | **6.0/10** | ORTA | MIN_RR bypass + strategy_type eksik |
| 10. Sinir (News+health) | **6.0/10** | ORTA | Faz 2 eksik, NewsBridge kritik ama incelenmedi |
| 15. İskelet (Governance) | **5.5/10** | **ZAYIF** | 3 belge 3 versiyon, CI-11 senkronsuz |
| 16. Test | **4.5/10** | **ZAYIF** | Davranış testi eksik |
| **11. Salgı (ÜSTAT)** | **4.0/10** | **ZAYIF** | **DEAD CHAIN — öğrenmiyor** |

### 5.2 Genel sistem skoru

- **Ortalama:** 6.76/10
- **Medyan:** 7.0/10
- **Standart sapma:** 1.2 (yüksek — sağlam organlar var, çürük organlar var)

**Tıbbi benzetme:** 40 yaşında orta yaş erişkin — temel fonksiyonlar iyi, ama **öğrenme/hafıza sistemi zayıflamış** (ÜSTAT dead chain), **iskelet çatlakları** var (governance drift), **bağışıklık hafızası** güvenilmez (davranış testi yok).

---

## 6. KRİTİK BULGULARIN ÖNCELİK PİRAMİDİ

### P0 — Acil (Bu hafta sonu / Barış Zamanı ilk operasyon)

| # | Bulgu | Organ | Sınıf | Çalışma süresi |
|---|---|---|---|---|
| 1 | **AX-4 SL/TP 3 motorda farklı uygulama** | 2 Beyin + 5 Eller + 4 Refleks | C3 (Kırmızı Bölge) | Kararla birlikte ~1 gün |
| 2 | **ÜSTAT dead chain (strategy_dist key + reason schema)** | 11 Salgı + 2 Beyin | C2 (Sarı) | ~2 gün (enum refactor) |
| 3 | **Hibrit EOD 17:45 kapatılmıyor** | 4 Refleks | C3 | ~0.5 gün |
| 4 | **ManuelMotor anayasa tanımsız** | 5 Eller + 15 İskelet | C1 + anayasa C3 | ~0.5 gün |

### P1 — Yakın vade (Nisan sonu)

| # | Bulgu | Organ | Sınıf |
|---|---|---|---|
| 5 | AX-3 kill-switch otomatik temizleme | 1 Kalp + 12 Bağış | C3 veya anayasa C3 |
| 6 | Trade lifecycle bug'ları (transfer_to_hybrid atomik, PRİMNET retry, sayaç sıra) | 4 Refleks + 2 Beyin | C3 kombinasyonu |
| 7 | Trading saatleri drift (3 motor 3 saat) | 4 Refleks + 5 Eller + 1 Kalp | C2 |
| 8 | api/server.py risk_params drift (fabrika fonksiyonu) | 7 Omurga | C2 |
| 9 | Governance manifest senkron (CI-11 ekle, version 3.0) | 15 İskelet | C0 (sadece yaml) |

### P2 — Orta vade (Nisan sonu — Mayıs)

| # | Bulgu | Organ | Sınıf |
|---|---|---|---|
| 10 | Test katmanı davranış testleri (KARAR #10) | 16 Test | L efor, C1-C2 |
| 11 | SE3 zafiyetler (R:R sert kapı, strategy_type, SPOF) | 3 Beyincik | C2 |
| 12 | R-11 kritik tetikler config'e taşıma (~15 sabit) | 15 İskelet + motorlar | C2 yaygın |
| 13 | Faz 2 auditor: data_pipeline, news_bridge, api/routes, desktop components | 8, 10, 13, 14 | okuma + C2 gerekirse |

### P3 — Bakım (Mayıs+)

| # | Bulgu | Organ | Sınıf |
|---|---|---|---|
| 14 | Ölü kod temizliği (7 parça) | 2 Beyin + 5 Eller + 13 Cilt | C0-C1 |
| 15 | Docs drift (CLAUDE.md versiyon + endpoint sayısı + bileşen sayısı + komut sayısı) | 15 İskelet | C0 |
| 16 | Yedek retention policy (günde 1) | 9 Hafıza | C1 |
| 17 | `ustat.db` dosyasını sil veya kullanıma al | 9 Hafıza + 11 Salgı | C1 |

---

## 7. SONRAKI ADIMLAR

### 7.1 Bu rapordan sonra

Bu check-up raporu **teşhis** aşaması. **Tedavi (ameliyat) planı ayrı dosyada:**

- `docs/2026-04-17_ameliyat_plani.md` — P0 operasyonlarının **detaylı adım-adım planı**: hangi dosya, hangi satır, hangi değişiklik, hangi test, geri alma prosedürü.

### 7.2 Barış Zamanı ameliyat takvimi

| Tarih | Operasyon | P seviyesi | Tahmini süre |
|---|---|---|---|
| **18 Nisan Cumartesi** | KARAR #1 (AX-4) + KARAR #4 (ManuelMotor) + KARAR #5 (manifest senkron) | P0 | 4-6 saat |
| **19 Nisan Pazar** | KARAR #3 (Hibrit EOD) + KARAR #6 (ÜSTAT dead chain) + davranış testleri | P0 | 4-6 saat |
| **Hafta içi 20-24 Nisan** | **DOKUNMA** — Savaş Zamanı, sadece izle + kanıt topla |
| **25-26 Nisan hafta sonu** | KARAR #2 (AX-3) + KARAR #7 (trade lifecycle) + KARAR #9 (risk_params fabrika) | P1 | 6-8 saat |
| **Mayıs 1. hafta** | KARAR #8 (config drift) + KARAR #13 (SE3) + P2 davranış testleri | P1-P2 | 8-10 saat yayılmış |
| **Mayıs boyunca** | KARAR #10 tamamlama + KARAR #11 R-11 migration kısmi + KARAR #12 temizlik | P2-P3 | Sürekli |

### 7.3 Operasyon onayı

Bu rapor **tanı aşaması**. Her ameliyat için ayrı onay gerekiyor (Anayasa Bölüm H C3 24 saat soğuma + Aşama 2 teyit). Kullanıcı raporu okuyup:

1. **Teşhise katılıp katılmadığı** — herhangi bir bulguda "hayır, bu böyle çalışıyor / kabul ediyorum" diyebilir
2. **P0 operasyonları için karar** — Faz 1 raporundaki (docs/2026-04-16_faz1_audit_karar_noktalari.md) "Üstat kararı: ____" satırlarına karar yazımı (A/B/C seçenek)
3. **Ameliyat sırası önerisi** — yukarıdaki takvim onayı veya revizyon

### 7.4 Faz 2 auditor eksikleri

Bu check-up 14 kritik dosyayı %100 + organ-organ değerlendirme yaptı. Ama aşağıdaki dosyalar **doğrudan okunmadı** — bulgular sınırlı:
- `engine/data_pipeline.py` (Kırmızı Bölge #7 ama derin okuma yok)
- `engine/top5_selection.py` (Top5 algoritması)
- `engine/news_bridge.py` (1550 satır — OLAY rejim tetiği)
- `engine/models/risk.py` (RiskParams dataclass default değerleri)
- `engine/event_bus.py`, `health.py`, `error_tracker.py` (yardımcı sinir sistemi)
- `api/routes/*.py` (23 dosya — endpoint davranışları)
- `desktop/src/components/*.jsx` (21 bileşen)
- `tools/*.py` (governance otomasyon)
- `tests/critical_flows/*` (test_static_contracts.py dışı)

**Öneri:** Faz 2'de bu dosyalar paralel ajanlarla hedefli denetlenebilir — her dosya için "başka hangi bayrağı saklıyor?" sorusuyla.

---

## 8. SON SÖZ

Sistem **hasta değil** — canlı parayla çalışan, kar/zarar üreten, öğrenmeye çalışan aktif bir organizma. Ama **rutin kontrol gerektiren** bir organizma. 42 bayrak teşhis edildi, 13 karar noktasına indirildi. Bunların 3-5 tanesi **ertelenirse** sessiz "kalp krizi" potansiyeli taşıyor (özellikle AX-4 asimetrisi + hibrit EOD + ÜSTAT dead chain).

**Bu rapor bir fotoğraf çekimi — teşhis. Tedavi ayrı belge. Her ameliyat ayrı onay.** Hafta sonu P0 operasyonları ile başlamak sistemin bir sonraki hafta savaş zamanına sağlıklı girmesi için en iyi yatırım.

---

**Kaynaklar:**
- 2026-04-16_proje_anlama_raporu.md (genel çerçeve)
- 2026-04-16_faz0_dogrudan_okuma.md (Faz 0, 15 bayrak)
- 2026-04-16_faz0_5_tamamlama.md (Faz 0.5, +17 bayrak)
- 2026-04-16_faz0_6_ogul_tam_kapsam.md (Faz 0.6, +6 bayrak)
- 2026-04-16_faz0_7_son_iki_modul.md (Faz 0.7, +4 bayrak, toplam 42)
- 2026-04-16_faz1_audit_karar_noktalari.md (13 karar noktası)
- 2026-04-16_risk_params_drift_olcumu.md (KARAR #9 ölçüm)
- Canlı sistem: `engine.heartbeat`, `shutdown.signal`, `logs/ustat_2026-04-17.log`, `database/trades.db` (read-only SELECT sorguları)
- Governance: `USTAT_ANAYASA.md`, `governance/*.yaml`, `CLAUDE.md`, `config/default.json`

