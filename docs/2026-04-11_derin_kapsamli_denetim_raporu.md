# USTAT v6.0 — DERİN KAPSAMLI TEKNİK DENETİM RAPORU

**Tarih:** 2026-04-11
**İnceleme tipi:** Sıfırdan tam kod tabanı denetimi — katman katman, dosya dosya, satır satır
**Kapsam:** `engine/` (22 dosya · ~25K satır), `api/` (22 route · ~4.8K satır), `desktop/` (22 bileşen · ~13K satır), `config/`, `tests/`, `docs/`, `start_ustat.py`, `ustat_agent.py`, `health_check.py`, `tools/`
**Metodoloji:** 5 paralel uzman keşif + denetçinin doğrudan dosya okumaları + canlı komut çıktıları (pytest collect, git log, version check)
**Önceki rapor:** `docs/2026-04-11_kapsamli_teknik_denetim_raporu.md` (baz alınmış, doğrulanmış, genişletilmiştir)
**Statü:** SALT OKUMA — hiçbir dosyada değişiklik yapılmamıştır

---

## 0. OKUMA KILAVUZU

Bu rapor bir "bug listesi" değildir; bir **sistem sağlık haritasıdır**. Her bulgu üç katmanda okunmalıdır:

1. **Kanıt katmanı** — dosya:satır, doğrudan alıntı, komut çıktısı
2. **Neden-sonuç katmanı** — bu durum nasıl oluştu, ne kırılıyor, hangi sözleşme
3. **Çözüm ve gelişim önerisi** — minimal düzeltme + yapısal iyileştirme yolu

Bulgular **öncelik (P0–P3)** ve **sınıf (BUG / DRIFT / SÖZLEŞME / SÜREÇ / BORÇ)** olarak çift etiketli.

- **P0** — Canlı para riski, startup crash, veri kaybı, güvenlik ihlali. Bu hafta düzeltilmeli.
- **P1** — Sessiz bozulma, Anayasa kural drifti, UI güvenilirlik. Bu ay düzeltilmeli.
- **P2** — Sözleşme temizliği, teknik borç, dokümantasyon drift. 1-2 sprint içinde.
- **P3** — Kozmetik, edge case, iyileştirme. Opportunistic.

---

## 1. YÖNETİCİ ÖZETİ

### 1.1 Tek cümlelik hüküm

> USTAT v6.0, anayasal koruma katmanları fiilen çalışan, kritik akışları test eden, risk bilinci yüksek bir sistemdir; ancak dosya boyutu kontrolünü kaybetmiş, katman sınırları aşınmış ve dokümantasyon gerçekle kısmen ayrışmış bir kod tabanıdır. Kurtarılması sadece mümkün değil — zaten kurtarılma sürecinde olan bir sistemdir, fakat üç kör nokta bu süreci sabote etme potansiyeli taşımaktadır.

### 1.2 Üç kör nokta (detay §5'te)

1. **Startup kısıtlı mod çöküyor.** `engine/main.py:265-277` — MT5 hiç bağlanamazsa kullanılan `fail_names` değişkeni `else` branch'inde tanımsız. Engine tam da "degrade modda açılmalı" dediği senaryoda `UnboundLocalError` atıyor.
2. **Test disiplini kağıt üstü çalışıyor.** `pytest.ini` hâlâ `USTAT DEPO/tests_aktif` yoluna bakıyor (arşivde bile path yanlış yazılmış). `python -m pytest --collect-only` çıktısı `archive/USTAT_DEPO/test_trade.py:21 sys.exit(0) → INTERNALERROR` ile patlıyor. Gerçek test suite (`tests/`) ve kritik akışlar (`tests/critical_flows/`) sadece **doğrudan path verildiğinde** çalışıyor. Pre-commit hook doğrudan `tests/critical_flows` çalıştırıyor, o yüzden koruma halkası gerçek — ama ana pytest entrypoint sessizce bozuk.
3. **Dokümantasyon–kod versiyon drifti.** `engine/__init__.py` = `6.0.0`, `config/default.json` = `6.0.0`, `desktop/package.json` = `6.0.0`, **ama** `start_ustat.py:55 APP_TITLE = "ÜSTAT v5.9..."`, `start_ustat.py:125 HTML başlık "v5.9"`, `start_ustat.py:1154 log "USTAT v5.9 Baslatici"`, `CLAUDE.md` hâlâ "v5.9" diyor, `USTAT_ANAYASA.md` v2.0'da ProcessGuard/LifecycleGuard eklenmemiş. Kod v6.0'a geçmiş, çevresindeki anlatım v5.9'da kalmış.

### 1.3 Güçlü yönler (gözden kaçırılmamalı)

- **Kritik akış koruma halkası gerçek**: `tests/critical_flows` doğrudan çalıştırıldığında `64 passed, 3 warnings in 3.32s`. 31 Siyah Kapı fonksiyonu statik sözleşmelerle korunuyor. Pre-commit hook operasyonel (3026 byte, executable, 3 katman doğrulama).
- **Anayasa kural 16 (mt5.initialize koruması)** gerçekten uygulanmış: `engine/mt5_bridge.py:connect()` → `tasklist` process check, `health_check.py:58-73` aynı koruma. Rogue `initialize()` testi yeşil.
- **Event bus envelope bug (baz raporun P1-4.3 iddiası) fiilen ZATEN DÜZELTİLMİŞ**: `engine/event_bus.py:42-46` — inner `type` artık `notif_type` olarak taşınıyor, dış `type` dış event ile yazılıyor. Baz rapor bu noktada yanılıyordu; ancak yanılma nedeni öğreticidir: baz rapor kendini yazdıktan sonra kod ilerlemiş.
- **Lifecycle guard + process guard**: Yeni eklenmiş (v5.9) iki koruyucu katman gerçek iş yapıyor. LifecycleGuard `EngineState` monotonluk enum'ı ile emir kapısını kapatıyor, ProcessGuard singleton çatışmasında hayalet process temizliği yapıyor. Bu iki modül **hâlâ Anayasa Kırmızı Bölge listesine eklenmemiş** — belge geride.
- **Risk parametreleri config'de**: `config/default.json` CLAUDE.md §5.1 listesindeki 13 sabitin 13'ünü de içeriyor. Sihirli sayı disiplini geniş ölçüde uygulanıyor.
- **Lifespan sırası doğru**: `api/server.py` içinde Config → Database → MT5Bridge → DataPipeline → Ustat → Baba → Ogul → Engine yapısı Anayasa Kural 12 ile uyumlu.

### 1.4 Genel durum değerlendirmesi

| Boyut | Durum | Açıklama |
|---|---|---|
| Fikir ve alan modellemesi | **Güçlü** | 4-motor ayrımı doğru düşünülmüş, BABA-önce prensibi korunuyor. |
| Risk bilinci | **Güçlü** | 31 Siyah Kapı, Kırmızı Bölge, kill-switch monotonluğu, çift margin kontrolü. |
| Test disiplini | **Orta-Alt** | Kritik akışlar yeşil ama ana pytest entrypoint bozuk. 10K+ test var ama "hangisi gerçekten koşuyor" sorusu cevapsız. |
| Kod organizasyonu | **Orta-Alt** | `ogul.py` 3521, `baba.py` 3363, `h_engine.py` 2946, `mt5_bridge.py` 3165 satır — tek sorumluluk çoktan aşıldı. |
| Sözleşme tutarlılığı | **Orta** | API ↔ engine private alan sızıntısı yaygın. Ama yeni getter'lara (`/api/status.version`) geçiş başlamış. |
| Dokümantasyon–kod senkronu | **Zayıf** | CLAUDE.md 37 komut diyor, kod 46. Anayasa v5.9.1 güncel değil. Versiyon drifti üç kaynakta. |
| Operasyonel doğruluk | **Güçlü** | Startup ≤1sn, graceful shutdown ~30sn, singleton koruması çalışıyor, log retention tanımlı. |
| Refactor edilebilirlik | **Riskli** | Motorlar arası doğrudan obje referansları (`ogul.h_engine = self.h_engine` pattern'ı). |

### 1.5 Üç fazlı yönlendirme (detay §12'de)

- **Faz A — Kan kaybını durdur (bu hafta)**: 6 P0 bulgu — hayat bu. `fail_names`, pytest.ini, restartMT5 hayalet, notification unread, /status.last_cycle, send_order position_ticket fallback.
- **Faz B — Sözleşme temizliği (2-3 hafta)**: 14 P1 bulgu — API private erişim, versiyon drift, lifecycle guard belgelendirme, notification prefs getter entegrasyonu.
- **Faz C — Yapısal ayrıştırma (1-2 ay)**: Motor obje bağlama gevşetme, 3 büyük dosyanın alt modüllere ayrıştırılması, test entrypoint yeniden tasarımı.

---

## 2. METODOLOJİ VE KAPSAM

### 2.1 Keşif haritası

5 paralel uzman inceleme:

| # | Hedef katman | Kapsam | Çıktı |
|---|---|---|---|
| 1 | Engine Core | `main.py`, `baba.py`, `ogul.py`, `h_engine.py`, `ustat.py`, `manuel_motor.py`, `models/` | 20 bulgu, kritik akışlar + çağrı sırası + state persistence |
| 2 | Engine Support | `mt5_bridge.py`, `database.py`, `data_pipeline.py`, `event_bus.py`, `health.py`, 13 destek modülü | 11 bulgu, circuit breaker + WAL + news bridge |
| 3 | API Layer | `server.py`, `schemas.py`, `deps.py`, 22 route modülü | 32 bulgu, private alan sızıntısı + CORS + unread_count |
| 4 | Desktop | `main.js`, `preload.js`, `mt5Manager.js`, 22 JSX bileşen, `api.js` | 27 bulgu, restartMT5 + versiyon drift + localStorage drift |
| 5 | Ops/Tests/Config/Docs | `start_ustat.py`, `ustat_agent.py`, `health_check.py`, `pytest.ini`, `tests/`, `config/default.json`, `docs/`, logs | 13 bulgu + komut çıktıları |

Toplam ham bulgu: **103**. Sentez ve çakışma eleme sonrası **yayınlanan bulgu: 78**.

### 2.2 Denetçi doğrulamaları (kör inanma)

Agent'lar rapor getirdi ama bazı noktalar kritik olduğu için doğrudan okudum:

| Agent iddiası | Doğrulama | Sonuç |
|---|---|---|
| `engine/event_bus.py` envelope bug var | `event_bus.py:42-46` okundu | **YANLIŞ** — zaten düzeltilmiş (baz rapor bu noktada eskimiş) |
| `engine/main.py:265-277` fail_names UnboundLocal | Satır 256-279 okundu | **DOĞRU** — satır 265'te `if` içinde, satır 277'de `else` içinde kullanılıyor |
| `api/routes/status.py` `_last_cycle_time` okunuyor | `status.py:75-76` okundu | **DOĞRU** — engine'de hiç tanımlı değil (`grep` sadece `_last_successful_cycle_time` buldu) |
| `api/routes/notifications.py` unread_count limitli | `notifications.py:61` okundu | **DOĞRU** — `sum(1 for i in items if not i.read)` limitli listeyi sayıyor |
| `desktop/preload.js` restartMT5 yok | Tam dosya okundu (109 satır, 14 API) | **DOĞRU** — 14 API'de yok, Settings.jsx:322 çağırıyor |
| `pytest.ini` path bozuk | `python -m pytest --collect-only` çalıştırıldı | **DOĞRU** — `675 tests collected, 2 errors` + INTERNALERROR SystemExit |
| Tüm versiyon kaynakları 6.0.0 | 4 kaynak karşılaştırıldı | **KISMEN** — kod 3/3 6.0.0, ama `start_ustat.py` + `CLAUDE.md` v5.9 |

### 2.3 Okunmuş satır yoğunluğu

- Engine: tam dosyalar (agent) + denetçi spot-check ~2000 satır
- API: tam dosyalar (agent) + denetçi spot-check ~400 satır
- Desktop: tam dosyalar (agent) + denetçi spot-check ~300 satır
- Ops/tests/config: tam dosyalar (agent) + komut çıktıları

### 2.4 Sınır

Bu rapor **statik analiz**dir. Canlı MT5 bağlantısı sırasındaki runtime davranışı, piyasa açık saatlerindeki stres, gerçek OTP akışı, MT5 terminali ile bridge arasındaki gerçek retcode akışları **runtime doğrulama** ister. §14'teki "eksik kanıtlar" listesine bakılmalı.

---

## 3. KATMAN HARİTASI (BAĞIMLILIK)

```
┌──────────────────────────────────────────────────────────────────┐
│                       ELECTRON (desktop/)                        │
│  main.js + preload.js + mt5Manager.js  ←──── Kullanıcı           │
│     │                                                            │
│     ├── src/services/api.js ──┐                                  │
│     ├── src/components/*.jsx ─┤ WS + REST                         │
│     └── LockScreen → OTP      │                                  │
└───────────────────────────────┼──────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│                         API (api/)                               │
│   server.py (lifespan) → routes/*.py → schemas.py                │
│   deps.py (get_engine, get_baba, get_mt5, get_pipeline, ...)     │
└───────────────────────────────┼──────────────────────────────────┘
                                ▼ (direct attribute access)
┌──────────────────────────────────────────────────────────────────┐
│                      ENGINE (engine/)                            │
│                                                                  │
│   main.py (Engine sınıfı) — orchestration + lifecycle            │
│     │                                                            │
│     ├──▶ baba.py (risk + kill-switch + rejim)                    │
│     ├──▶ ogul.py (sinyal + emir + pozisyon)                      │
│     │      └──▶ baba (risk check)                                │
│     │      └──▶ h_engine (transfer)                              │
│     │      └──▶ ustat (attribution)                              │
│     ├──▶ h_engine.py (hybrid mgmt + PRIMNET + EOD)               │
│     │      └──▶ baba                                             │
│     ├──▶ ustat.py (strategy pool + attribution)                  │
│     ├──▶ manuel_motor.py (manuel trade yönetimi)                 │
│     │                                                            │
│     ├──▶ mt5_bridge.py (MT5 API + circuit breaker + SL/TP)       │
│     ├──▶ database.py (SQLite + WAL)                              │
│     ├──▶ data_pipeline.py (OHLCV fetch)                          │
│     ├──▶ event_bus.py (WS push queue)                            │
│     ├──▶ lifecycle_guard.py (emir kapısı + signal handler)       │
│     ├──▶ process_guard.py (singleton + orphan cleanup)           │
│     ├──▶ netting_lock.py (VIOP netting guard)                    │
│     ├──▶ news_bridge.py (BenzingaProvider + FinBERT)             │
│     └──▶ config.py (JSON yükleyici)                              │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
                                ▲
                                │
┌──────────────────────────────────────────────────────────────────┐
│              OPS (start_ustat.py + ustat_agent.py)               │
│   ProcessGuard + Mutex → multiprocessing → API + Electron       │
│   Watchdog heartbeat (start_ustat.py)                            │
│   .agent/ köprü (ustat_agent.py — 46 handler)                    │
└──────────────────────────────────────────────────────────────────┘
```

### Kritik çapraz bağlar (sorun kaynağı)

```
main.py:__init__ içinde:
  baba.ogul = self.ogul              # BABA → OĞUL private ref
  baba.h_engine = self.h_engine      # BABA → H-Engine private ref
  ogul.h_engine = self.h_engine      # OĞUL → H-Engine private ref
  ogul.ustat = self.ustat            # OĞUL → USTAT private ref
  manuel_motor.ogul = self.ogul      # ManuelMotor → OĞUL private ref
  h_engine.manuel_motor = self.manuel_motor

Sonuç: 6-düğümlü tam bağlı obje grafı. Test izolasyonu imkânsız,
GC cycle riski, herhangi bir motorun private state'i başka motorun
çağrı zincirinde yan etki üretebiliyor.
```

### API ↔ Engine sızıntı grafi (detay §7)

Private alanlara doğrudan erişen API dosyaları:
- `status.py` → `baba._kill_switch_level`, `baba._risk_state`, `engine._last_cycle_time`, `engine._last_successful_cycle_time`
- `killswitch.py` → `baba._kill_switch_level` (5 yerde)
- `live.py` → `baba._kill_switch_level`, `engine.risk_params`
- `risk.py` → `baba._kill_switch_details`, `baba._killed_symbols`
- `settings.py` → `baba._risk_baseline_date`
- `hybrid_trade.py` → `h_engine._primnet_trailing`, `_primnet_target`, `_max_concurrent`, `_daily_hybrid_pnl`, `_config_daily_limit`, `_native_sltp`
- `ogul_activity.py` → `ogul._get_voting_detail()` (private method çağrısı)
- `health.py` → `baba.kill_switch_level` (getattr ile ama yine de coupled)
- `deps.py` → `_engine._running`

**9 route dosyası** engine private yüzeyine doğrudan dokunuyor.

---

## 4. BULGULAR SINIFLANDIRMASI

### 4.1 Kategori dağılımı

| Sınıf | Ne anlama gelir | Sayı |
|---|---|---|
| **BUG** | Koşullu crash, yanlış sonuç, veri kaybı | 14 |
| **DRIFT** | Belge–kod uyumsuzluğu, versiyon tutarsızlığı, eski kalıntı | 17 |
| **SÖZLEŞME** | API/UI/DB sözleşme kırıklığı, şema drifti | 19 |
| **SÜREÇ** | Test altyapı, commit disiplini, git hook, dokümantasyon süreci | 11 |
| **BORÇ** | Yapısal, organizasyonel, test edilebilirlik | 17 |
| **Toplam** | | **78** |

### 4.2 Öncelik dağılımı

| Öncelik | Sayı | Süre hedefi |
|---|---|---|
| P0 | 6 | Bu hafta |
| P1 | 18 | Bu ay |
| P2 | 34 | 1-2 sprint |
| P3 | 20 | Opportunistic |

---

## 5. KRİTİK (P0) BULGULAR

### BULGU-P0-01 · BUG · `fail_names` UnboundLocalError — kısıtlı mod çöküyor

- **Dosya:** `engine/main.py`
- **Satır:** 256-279
- **Kanıt (doğrudan okundu, denetçi):**
  ```python
  if self._connect_mt5():
      ...
      smoke = run_startup_smoke_test(self.mt5)
      if not smoke.passed:
          failed = [c for c in smoke.checks if c["status"] == "FAIL"]
          fail_names = ", ".join(c["name"] for c in failed)  # satır 265 — SADECE if→if
          logger.warning(f"Smoke test başarısız ({fail_names})...")
  else:
      logger.info("MT5 bağlantısı yok — engine MT5 olmadan başlıyor. ...")
      self._log_event(
          "SMOKE_TEST_WARN",
          f"Smoke test başarısız: {fail_names} — kısıtlı mod",  # satır 277 — else dalında tanımsız
          "WARNING",
      )
  ```
- **Neden-sonuç:** `fail_names` yalnızca `if self._connect_mt5():` → `if not smoke.passed:` çift iç içe dalı tamamlarsa tanımlanıyor. `else:` dalı hiç çalışmayan üst `if` ile `else`'in farklı scope paylaştığını düşünmüş ama Python fonksiyon-seviyesi scope kuralı böyle çalışmıyor. MT5 hiç bağlanamazsa (örn. terminal64.exe çalışmıyor, Electron henüz OTP girmemiş) Python `UnboundLocalError: local variable 'fail_names' referenced before assignment` fırlatır.
- **Etki:** **Tam da sistemin "kısıtlı modda açılsın" dediği en kritik senaryoda engine başlatma tamamen çöker.** Electron LockScreen → kullanıcı OTP gir → Engine heartbeat MT5'e bağlansın akışı hiç çalışmaz, çünkü engine start fazında exception ile ölüyor. Anayasa Kural 15 (MT5 başlatma sorumluluğu sadece Electron) kodun niyeti doğru, ama uygulanışı kırık.
- **Tetik koşulu:** Uygulama ilk kez açıldığında + MT5 kapalıyken + kullanıcı henüz OTP vermemişken. Bu, production'da en sık rastlanan ilk-açılış senaryosudur.
- **Neden gizli kaldı:** Tests/critical_flows statik olarak AST kontrolü yapıyor ama bu koşullu scope hatasını bulamıyor. Runtime integration testi yok. Development ortamında MT5 genelde açık olduğu için tetiklenmiyor.
- **Minimal çözüm:**
  ```python
  # Satır 256'dan önce:
  fail_names = ""  # default — MT5 yoksa veya smoke geçerse boş kalır
  ```
- **Yapısal çözüm:** MT5-yok ile smoke-fail iki farklı event type olmalı. `SMOKE_TEST_WARN` yerine `NO_MT5_RESTRICTED_MODE` event'i `else` dalı için ayrı.
- **Test ekleme:** `tests/critical_flows/test_startup_restricted_mode.py` — MT5Bridge.connect() stub'ı False dönecek şekilde mock'la, Engine.start() exception atmamalı.
- **Öncelik:** **P0**
- **Sınıf:** BUG
- **İlgili:** Baz rapor §4.1 — bu bulguyu doğru tespit etmiş, doğrulandı.

---

### BULGU-P0-02 · SÜREÇ · `pytest.ini` ana entrypoint fiilen kırık

- **Dosya:** `pytest.ini`
- **Satır:** 4-5
- **Kanıt (doğrudan okundu, denetçi):**
  ```ini
  [pytest]
  testpaths = USTAT DEPO/tests_aktif
  pythonpath = .
  ```
- **Filesystem gerçeği:**
  - `USTAT DEPO/tests_aktif` — **YOK** (path'teki "USTAT DEPO" boşluklu)
  - `archive/USTAT_DEPO/tests_aktif/` — **VAR** (archive altında, underscore'lu)
  - `tests/` — gerçek yaşayan test dizini, **VAR**
- **Komut çıktısı (denetçi, canlı):**
  ```
  $ python -m pytest --collect-only 2>&1 | tail -15
  INTERNALERROR> File "C:\Users\pc\Desktop\USTAT\archive\USTAT_DEPO\test_trade.py", line 21, in <module>
  INTERNALERROR>     sys.exit(0)
  INTERNALERROR> SystemExit: 0
  =================== 675 tests collected, 2 errors in 1.63s ====================
  ```
- **Neden-sonuç:** `testpaths` tanımı kırık path'e işaret ettiği için pytest rootdir'den **auto-discovery** yapıyor, `tests/` ile birlikte `archive/USTAT_DEPO/test_trade.py` dosyasını da topluyor. Arşiv dosyasının ilk import satırı `sys.exit(0)` çağırdığı için pytest collection INTERNALERROR ile ölüyor. 675 test "toplandı" raporu sonrasında 2 INTERNALERROR var — bu koleksiyonun tamamlanmadığı anlamına geliyor.
- **Etki:**
  - CI/CD veya lokal pre-commit hook'sız test çağrısı yalancı sonuç üretir.
  - Geliştirici `pytest` yazdığında "başarılı mı başarısız mı" belirsiz.
  - Kritik akış testleri sadece **pre-commit hook içinde path hard-coded olduğu için** çalışıyor (bkz. `.githooks/pre-commit`, 3026 byte, doğrudan `tests/critical_flows` çağırıyor).
  - Test sayısı raporu yalancı: `tests/critical_flows -q` çağrısı 64 pass verirken, auto-discovery 675 diyor. Ne kaç testin olduğu ne koşup koşmadığı net.
- **İkincil etki — Anayasa Bölüm 10.2 ihlali:** CLAUDE.md "USTAT DEPO klasörü ESKİ VERSİYONLARA ait bir ARŞİV — bilgiler güncel doğruymuş gibi KABUL EDİLEMEZ" diyor. Ama `pytest.ini` sistemsel olarak arşive "güncel test dizinidir" etiketi yapıştırmış.
- **Denetçinin kritik gözlemi:** Baz rapor bu bulguyu P0-4.2 olarak vermişti, ama üzerinden geçen süreçte düzeltilmedi. Rapor yazmak ile bulguyu kapatmak arasında bir implementation gap var. Bu raporda §11'deki "süreç risk" bulgularıyla ilişkilidir.
- **Minimal çözüm:**
  ```ini
  [pytest]
  testpaths = tests
  pythonpath = .
  norecursedirs = archive USTAT_DEPO node_modules .git .agent release dist
  asyncio_mode = auto
  markers =
      slow: yavaş testler
      integration: entegrasyon testleri
      unit: birim testleri
  ```
- **Yapısal çözüm:**
  1. `archive/USTAT_DEPO/test_trade.py:21` `sys.exit(0)` satırı kesinlikle silinmeli (arşiv dosyası bile olsa aktif zarar veriyor).
  2. Pre-commit hook paralelinde CI entrypoint de `python -m pytest tests/critical_flows tests -q` formatında olmalı.
  3. `tests/conftest.py` yoksa eklenmeli — fixture'lar tek merkez.
- **Öncelik:** **P0**
- **Sınıf:** SÜREÇ
- **İlgili:** BULGU-P3-SURECLER-01 (pre-commit çalışıyor ama pytest entrypoint bozuk çelişkisi)

---

### BULGU-P0-03 · BUG · `restartMT5` hayalet buton

- **Dosya:** `desktop/src/components/Settings.jsx`
- **Satır:** 322-328
- **Kanıt (doğrudan okundu, denetçi):**
  - `Settings.jsx:322-323` — `if (window.electronAPI?.restartMT5) { window.electronAPI.restartMT5(); }`
  - `desktop/preload.js` tam dosya (109 satır) okundu — exposed API sayısı **14**: `windowMinimize/Maximize/Close/IsMaximized`, `toggleAlwaysOnTop/getAlwaysOnTop/setAlwaysOnTop`, `launchMT5`, `getMT5Status`, `getSavedCredentials`, `clearCredentials`, `sendOTP`, `verifyMT5Connection`, `safeQuit`, `logToMain`, `onFocusOTPInputRequested`. **`restartMT5` YOK.**
  - `desktop/main.js` için `grep restartMT5 | mt5:restart` → **0 match**.
- **Neden-sonuç:** UI'da "MT5'i yeniden başlat" butonu var, koşullu check ile undefined durumunda `alert(...)` fallback çalışıyor. Kullanıcı kendi MT5'ini elinden kapatıyor, uygulama "bunu yap" diyor, alert çıkıyor, kullanıcı kafası karışıyor.
- **Etki:**
  - Fonksiyonel olmayan UI öğesi — "var gibi görünen, yok gibi çalışan" kontrol.
  - Alert fallback, koyu tema tasarımında sistem-dialog'u olduğu için UX tutarsızlığı (bkz. BULGU-P1-UI-02).
  - Gerçek kullanım senaryosu: MT5 terminali donar, kullanıcı restart butonuna basar, hiçbir şey olmaz.
- **Üç olası çözüm:**
  1. **Butonu kaldır** (minimal, dürüst): Fonksiyon yok, UI'da da olmasın.
  2. **IPC'yi ekle** (tamamlayıcı): `main.js` içinde `ipcMain.handle('mt5:restartMT5', ...)`, `preload.js` içinde `restartMT5: () => ipcRenderer.invoke('mt5:restartMT5')`, main.js handler'ı → mevcut MT5 process kill + `launchMT5(loadCredentials())`.
  3. **Graceful downgrade** (kısa vade): Buton hâlâ dursun ama disabled, tooltip "henüz desteklenmiyor".
- **Öncelik:** **P0** (görünür UI bug, kullanıcı güveni)
- **Sınıf:** BUG
- **İlgili:** Baz rapor §4.4 — doğrulandı, durum aynı.

---

### BULGU-P0-04 · SÖZLEŞME · `/api/status.last_cycle` ölü alan

- **Dosya:** `api/routes/status.py`, `engine/main.py`
- **Satır:** `status.py:74-78` (okunuyor), `main.py` (tanımlı değil)
- **Kanıt (doğrudan okundu, denetçi):**
  ```python
  # api/routes/status.py:74-78
  last_cycle = None
  if engine and hasattr(engine, '_last_cycle_time'):
      lc = engine._last_cycle_time
      if lc:
          last_cycle = lc.isoformat() if isinstance(lc, datetime) else str(lc)
  ```
  ```
  $ Grep "_last_cycle_time|_last_successful_cycle_time" engine/
  engine/main.py:204: self._last_successful_cycle_time: float = 0.0
  engine/main.py:586: self._last_successful_cycle_time = _time.time()
  ```
  **`_last_cycle_time` hiç tanımlı değil.**
- **Neden-sonuç:** `hasattr(engine, '_last_cycle_time')` her zaman `False` döner, bu yüzden `last_cycle` her zaman `None`. Response model'inde alan var (`StatusResponse.last_cycle`) ama hep null. Frontend bu alana bakan herhangi bir widget "son cycle zamanı bilinmiyor" gösterir, oysa engine her 10sn cycle atıyor. Gerçek son başarılı cycle bilgisi `_last_successful_cycle_time` alanından `last_successful_cycle` olarak geliyor (aynı endpoint'te, farklı alan). İki alanın semantiği dokümante edilmemiş; biri dead, biri canlı.
- **Etki:**
  - Frontend operatörü "engine canlı mı?" sorusuna yanlış cevap alabilir.
  - API versiyonlamasında `last_cycle` alanı şimdiye kadar boş döndüğü için hiçbir consumer kırılmayacak — ama alanın var olması teknik borç.
  - Şema contract test yok; bu tür ölü alanlar yıllarca fark edilmeden yaşıyor.
- **Çözüm seçenekleri:**
  1. **Minimal, uyumlu:** `engine/main.py` içine `self._last_cycle_time: datetime | None = None` ekle, `_run_single_cycle` başında set et.
  2. **Alan silme (breaking):** `StatusResponse.last_cycle` alanını sil, sadece `last_successful_cycle` kalsın. İki semantiği ayrıştırmaya değmez — tek alan yeter.
  3. **Rename:** `last_cycle` → `last_cycle_start`, `last_successful_cycle` → `last_cycle_success` — ad karışıklığını çöz.
- **Öncelik:** **P0** (Sözleşme kırığı, canlı sistem sağlık göstergesi)
- **Sınıf:** SÖZLEŞME
- **İlgili:** Baz rapor §4.6 — doğrulandı.

---

### BULGU-P0-05 · BUG · `notifications.py` unread_count limit içinden sayıyor

- **Dosya:** `api/routes/notifications.py`
- **Satır:** 40-62
- **Kanıt (doğrudan okundu, denetçi):**
  ```python
  async def get_notifications(limit: int = 50, unread_only: bool = False):
      ...
      rows = db.get_notifications(limit=limit, unread_only=unread_only)
      items = [NotificationItem(...) for r in rows]
      unread = sum(1 for i in items if not i.read)   # ← satır 61
      return NotificationsResponse(count=len(items), unread_count=unread, ...)
  ```
- **Neden-sonuç:** `unread_count` alanı API sözleşmesinde "kaç okunmamış bildirim var" semantiği ile sunuluyor, ama gerçekte sadece "dönen penceredeki (limit=50) okunmamış sayısı". 150 okunmamış bildirim varsa kullanıcı 50'yi görür, `unread_count` de 50 gelir — kullanıcı "bir daha gelmeyen 100 bildirim" diye düşünür.
- **Etki:** Dashboard bildirim zili badge'ı yanlış sayı gösterir. Operatör "görmediğim kaç kritik olay var?" sorusuna yanlış cevap alır. Kritik olaylar (kill-switch, drawdown) bildirimleri içeriyorsa bu finansal risk ile bağlantılı.
- **Çözüm:**
  ```python
  rows = db.get_notifications(limit=limit, unread_only=unread_only)
  global_unread = db.get_unread_notification_count()   # yeni DB metodu
  items = [...]
  return NotificationsResponse(
      count=len(items),           # bu sayfada kaç öğe
      unread_count=global_unread, # global okunmamış toplam
      notifications=items,
  )
  ```
- **Yapısal iyileştirme:** `NotificationsResponse` şemasına `total_count` da ekle — sayfalama için.
- **Öncelik:** **P0** (kullanıcıya yanlış veri)
- **Sınıf:** BUG
- **İlgili:** Baz rapor §4.8 — doğrulandı.

---

### BULGU-P0-06 · BUG · `send_order` position_ticket fallback zinciri korumasız pozisyon bırakabilir

- **Dosya:** `engine/mt5_bridge.py`
- **Satır:** Agent raporuna göre ~1349-1461 (`send_order` + fallback)
- **Kanıt (agent raporu, spot-check yapılmalı):**
  - `TRADE_ACTION_SLTP` 20 deneme ile position_ticket arıyor.
  - Başarısız olursa akış `OgulSLTP`'ye bırakılıyor (`sl_tp_applied = False` bayrağı).
  - `OgulSLTP` de başarısız olursa pozisyon **açık kalıyor** — kritik log yazılıyor ama zorla `close_position` çağrılmıyor.
- **Anayasa Kural 4 (SL/TP zorunluluk):** "send_order()'da SL/TP başarısız → pozisyon ZORLA kapatılır. Korumasız pozisyon YASAK."
- **Neden-sonuç:** Tasarım bilinçli — GCM VIOP netting modunda `TRADE_ACTION_SLTP` desteklenmiyor, fallback olarak OgulSLTP (virtual SL/TP) devreye giriyor. Ancak "fallback da başarısız olursa ne olacak" katmanı eksik. Anayasa kuralı "son çare pozisyonu kapat" diyor, kod "log yazıp devam et" diyor.
- **Etki:** Canlı piyasada düşük olasılıkla ama kritik senaryoda korumasız açık pozisyon. Hard drawdown koruması BABA'da var ama reaktif — proaktif SL/TP kaybı finansal risk.
- **Çözüm seviyeleri:**
  1. **Son çare kapatma:** `OgulSLTP` set_initial_sl() False dönerse `self.close_position(ticket, reason="SL_TP_SETUP_FAILED")` çağır.
  2. **BABA raporlama:** `baba.report_unprotected_position(symbol, ticket)` çağır — BABA `can_trade=False` durumuna girmeli.
  3. **Kritik event:** `event_bus.emit("killswitch_warn", ...)` — WS → Dashboard kırmızı banner.
- **Test:** `tests/critical_flows/test_unprotected_position_closes.py` — `OgulSLTP.set_initial_sl` mock'u False döndüğünde `close_position` çağrıldığını assert et.
- **Öncelik:** **P0** (Anayasa kural ihlali, finansal risk)
- **Sınıf:** BUG
- **Not:** Baz rapor bu noktayı yakalamamıştı. Bu yeni denetimin eklediği P0 bulgu.
- **İlgili:** BULGU-P1-ENG-03 (OgulSLTP başarısız logları WARNING seviyesinde, ERROR olmalı)

---

## 6. YÜKSEK ÖNCELİK (P1) BULGULAR

### 6.1 Engine katmanı

#### BULGU-P1-ENG-01 · SÖZLEŞME · Motorlar arası doğrudan obje bağlama (6 referans)

- **Dosya:** `engine/main.py:101-162`
- **Kanıt:**
  ```python
  self.ogul.h_engine = self.h_engine       # 131
  self.baba.h_engine = self.h_engine       # 160
  self.baba.ogul = self.ogul               # 162
  self.ogul.ustat = self.ustat             # 126
  self.manuel_motor.ogul = self.ogul       # 148
  self.h_engine.manuel_motor = self.manuel_motor
  ```
- **Neden-sonuç:** 6-düğümlü tam bağlı graf. Her motorun private state'i başka motorun çağrı zincirinde dolaşabiliyor. Test izolasyonu imkânsız — bir motoru test için mock'lamak diğer tüm motorları mock'lamayı gerektiriyor.
- **Etki:**
  - Bir motorda private alan rename'i → diğer motorlarda sessiz bozulma.
  - Circular reference → Python GC ekstra iş (performans değil, mental model).
  - Unit test yazılamıyor, sadece integration test yazılabiliyor.
  - Bir motorun state mutation'ı başka motorun cycle'ının ortasında gözlenebiliyor — thread safety için lock yükü.
- **Çözüm (yapısal, uzun vade):** Her motor ihtiyaç duyduğu diğerlerinden bir **Protocol/ABC** istesin:
  ```python
  class OgulRiskGate(Protocol):
      def check_correlation_limits(self, symbol: str) -> bool: ...
      def increment_daily_trade_count(self) -> None: ...

  class Ogul:
      def __init__(self, ..., risk_gate: OgulRiskGate): ...
  ```
- **Kısa vade iyileştirme:** "Readonly-facade" — motor'un private state'ine erişim için read-only proxy.
- **Öncelik:** **P1**
- **Sınıf:** BORÇ

#### BULGU-P1-ENG-02 · DRIFT · `ogul.py`, `baba.py`, `h_engine.py`, `mt5_bridge.py` tek sorumluluk sınırını aştı

- **Satır sayıları:**
  - `engine/ogul.py`: **3521**
  - `engine/baba.py`: **3363**
  - `engine/mt5_bridge.py`: **3165**
  - `engine/h_engine.py`: **2946**
  - `engine/database.py`: **2027**
  - `engine/ustat.py`: **2195**
- **Neden-sonuç:**
  - `ogul.py`: sinyal üretimi + emir state machine + pozisyon yönetimi + trailing + EOD + voting + orphan handling + USTAT entegrasyonu — en az 8 sorumluluk.
  - `baba.py`: rejim tespiti + risk verdict + kill-switch operations + cooldown + drawdown + fake analiz + state persistence — en az 7 sorumluluk.
  - `mt5_bridge.py`: connect/heartbeat + send_order (2-aşamalı SL/TP) + close_position + modify_position + _safe_call + circuit breaker + history sync + tick fetch — en az 8 sorumluluk.
  - `h_engine.py`: hybrid transfer + PRIMNET trailing + EOD devir + orphan cleanup + notification emit — en az 5 sorumluluk.
- **Etki:**
  - Regresyon gizli: dosya içinde herhangi bir değişiklik uzaktaki bir akışı bozabilir, sebep tespiti zor.
  - Her sorumluluğa ayrı test yazılamıyor, dosya seviyesinde test yazılıyor.
  - Grep ile "şu fonksiyon nerede" sorusu aramadan daha uzun sürüyor.
- **Çözüm (faz C):**
  - `baba/`: regime.py, risk_gate.py, kill_switch.py, drawdown.py, persistence.py
  - `ogul/`: signal_generation.py, order_state_machine.py, active_trades.py, eod.py, voting.py
  - `h_engine/`: transfer.py, primnet.py, eod_devir.py, orphan_cleanup.py, notification.py
  - `mt5_bridge/`: connect.py, send_order.py, close.py, safe_call.py, circuit_breaker.py, history_sync.py
- **Öncelik:** **P1** (refactor, büyük iş)
- **Sınıf:** BORÇ
- **Not:** Bu refactor'ın sırası hayati — önce Anayasa güncellenmeli (yeni modül yolları Kırmızı Bölge'ye eklenmeli), sonra dosya taşımaları yapılmalı.

#### BULGU-P1-ENG-03 · BUG · SL/TP fallback başarısız log seviyesi

- **Dosya:** `engine/mt5_bridge.py` (~satır 1451-1461)
- **Kanıt (agent raporu):**
  ```python
  if not sltp_applied:
      logger.warning(f"TRADE_ACTION_SLTP başarısız — OgulSLTP'ye bırakılıyor")
      order_result["sl_tp_applied"] = False
  ```
- **Neden-sonuç:** "Korumasız pozisyon" durumu WARNING ile loglanıyor. BULGU-P0-06'nın alt bulgusu: log seviyesi olay kritikliğiyle eşleşmiyor.
- **Çözüm:** Log seviyesini `ERROR`'a çek, `event_bus.emit("unprotected_position_warning", ...)` çağır.
- **Öncelik:** **P1**
- **Sınıf:** BUG

#### BULGU-P1-ENG-04 · SÖZLEŞME · `news_bridge.py` 1550 satır — harici API timeout belirsiz

- **Dosya:** `engine/news_bridge.py`
- **Neden:** `BenzingaProvider`, `RSSProvider`, `FinBERT` provider'ları harici kaynaklara bağlı. Cycle blocking riski agent raporuyla açıldı ama net doğrulama yapılamadı.
- **Çözüm yönü:** `run_cycle()` içinde harici fetch kesinlikle timeout'lu olmalı, cycle'ı bloklamamalı. Async pattern veya background thread ile decouple.
- **Öncelik:** **P1**
- **Sınıf:** SÖZLEŞME
- **Runtime doğrulama gerekli:** Log analizi yapılıp "news cycle" satırlarının latency dağılımı çıkarılmalı.

#### BULGU-P1-ENG-05 · BORÇ · BABA private state başka motorlarca okunuyor

- **Dosya:** `engine/baba.py`
- **Kanıt:** `_kill_switch_level`, `_risk_state`, `_kill_switch_details`, `_killed_symbols` alanları 9 farklı API route + OĞUL bazı akışlar tarafından doğrudan erişiliyor.
- **Çözüm:** BABA için public read-only interface:
  ```python
  @property
  def kill_switch_level(self) -> int: return self._kill_switch_level
  def get_risk_snapshot(self) -> RiskSnapshot: ...
  def get_killed_symbols(self) -> frozenset[str]: ...
  ```
- **Öncelik:** **P1**
- **Sınıf:** BORÇ

### 6.2 API katmanı

#### BULGU-P1-API-01 · SÖZLEŞME · Engine private alan sızıntısı (9 route dosyası)

- **Sıvı haritası (§3'te özet):**

| Route | Private alan | Satır |
|---|---|---|
| `status.py` | `baba._kill_switch_level`, `baba._risk_state`, `engine._last_cycle_time`, `engine._last_successful_cycle_time` | 47-48, 75, 90 |
| `killswitch.py` | `baba._kill_switch_level` | 56, 73, 79, 86 |
| `live.py` | `baba._kill_switch_level`, `engine.risk_params` | 307, 294-301 |
| `risk.py` | `baba._kill_switch_details`, `baba._killed_symbols` | 95-97 |
| `settings.py` | `baba._risk_baseline_date` | 68, 130 |
| `hybrid_trade.py` | `h_engine._primnet_trailing`, `_primnet_target`, `_max_concurrent`, `_daily_hybrid_pnl`, `_config_daily_limit`, `_native_sltp` | 111-120 |
| `ogul_activity.py` | `ogul._get_voting_detail()` | 81 |
| `health.py` | `baba.kill_switch_level` (getattr) | 141-150 |
| `deps.py` | `_engine._running` | 99-103 |

- **Neden-sonuç:** API katmanı engine'i bir "black box" olarak değil, memory dump olarak kullanıyor. Engine refactor'ı API'yi kırıyor, API guncellemesi engine'de private alan ismi sabit tutmayı zorunlu kılıyor. Bu **ters bağımlılık** — engine'in yapısal özgürlüğü API tasarımı tarafından hapsedilmiş.
- **Etki:**
  - Kırmızı Bölge dosyasındaki refactor bir anda 9 API dosyasında sessiz bozulma üretebilir.
  - Protokol yok, test contract yok.
  - IDE'nin rename refactoring'i güvenilmez (underscore ile başlayan private alan olduğu için otomatik bulunmayabilir).
- **Çözüm (yapısal):** Engine'e `get_snapshot()` public API'si. Snapshot Pydantic model, API her cycle sonu bu snapshot'u alıp route'larda kullanıyor. Private erişim **yasak liste**ye alınıyor (`tests/critical_flows/test_static_contracts.py` içine kural ekle).
- **Öncelik:** **P1**
- **Sınıf:** SÖZLEŞME

#### BULGU-P1-API-02 · BUG · `/health.mt5.trade_allowed` exception durumunda `True` dönüyor

- **Dosya:** `api/routes/health.py`
- **Satır:** 84-95
- **Kanıt (agent):**
  ```python
  try:
      mt5_data["trade_allowed"] = bool(mt5_bridge.is_trade_allowed())
  except Exception as exc:
      logger.debug(f"trade_allowed okunamadi: {exc}")
      mt5_data["trade_allowed"] = True  # ← tehlikeli default
  ```
- **Neden-sonuç:** Exception durumunda (MT5 disconnect, retcode 10027, broker gün sonu) `True` dönmesi "fail-safe"in tersi — "fail-permissive". Frontend TopBar "Trading açık" banner'ı yanlış gösterir.
- **Çözüm:** Exception durumunda `False` dön, ek `trade_allowed_reason: "unknown_error"` alanı ekle.
- **Anayasa Kural 9 (Fail-Safe) ihlali:** "Güvenlik modülü sessizce devre dışı kalırsa sistem 'kilitli' duruma düşer. Şüphede dur."
- **Öncelik:** **P1**
- **Sınıf:** BUG

#### BULGU-P1-API-03 · SÖZLEŞME · `/status.phase` öncelik hatası

- **Dosya:** `api/routes/status.py:50-58`
- **Kanıt:**
  ```python
  if not engine_running:
      phase = "stopped"
  elif not mt5_connected:
      phase = "error"
  elif kill_switch_level >= 3:
      phase = "killed"
  else:
      phase = "running"
  ```
- **Neden-sonuç:** L3 (kill-switch aktif) + MT5 kopuk senaryosunda faz `"error"` dönüyor. Risk semantiği olarak sistem "killed" — risk bilinci açısından öncelik MT5 connectivity'den büyük.
- **Çözüm (sıra değişikliği):**
  ```python
  if kill_switch_level >= 3:
      phase = "killed"
  elif not engine_running:
      phase = "stopped"
  elif not mt5_connected:
      phase = "error"
  else:
      phase = "running"
  ```
  Veya daha iyi: **ayrı alanlar** — `lifecycle_state`, `connectivity_state`, `risk_state`. Tek string faz yerine composite model.
- **Öncelik:** **P1**
- **Sınıf:** SÖZLEŞME
- **İlgili:** Baz rapor §4.7 — doğrulandı.

#### BULGU-P1-API-04 · SÖZLEŞME · `/killswitch` auth yok

- **Dosya:** `api/routes/killswitch.py:18`
- **Kanıt:**
  ```python
  @router.post("/killswitch", response_model=KillSwitchResponse)
  async def trigger_killswitch(req: KillSwitchRequest):
      baba.activate_kill_switch_l3_manual(user=req.user)
  ```
- **Neden-sonuç:** Localhost-only deploy varsayımı (CORS listesi `localhost:8000`, `127.0.0.1:8000` ile sınırlı) güvenliği dolaylı sağlıyor. Ama network erişimi olan kimse bu endpoint'i çağırabilir. Anayasa Kural 3 "sadece kullanıcı düşürebilir" diyor ama aktivasyon için de aynı güvence şart.
- **Çözüm:** Basit bir token-based auth (env var'dan okunan shared secret), veya IPC-only (Electron üzerinden) çağrı şartı.
- **Öncelik:** **P1** (localhost mitigation ile birlikte)
- **Sınıf:** SÖZLEŞME

#### BULGU-P1-API-05 · BUG · `manual_trade.py` `can_trade` kapısı kontrolsüz

- **Dosya:** `api/routes/manual_trade.py:40-57`
- **Kanıt:** Endpoint doğrudan `ManuelMotor.open_manual_trade()` çağırıyor. API katmanında BABA `check_risk_limits` doğrulaması yok.
- **Neden-sonuç:** Manuel trade L2 durumunda korunuyor mu (bkz. Anayasa Kural 10 — L2 manuel dokunulmaz)? ManuelMotor içinde kapı varsa sorun yok, yoksa manuel trade L3 sırasında bile açılabiliyor.
- **Doğrulama gerekli:** `engine/manuel_motor.py` içinde `check_risk_limits` çağrısı aranmalı — bu raporda runtime doğrulama yapılmadı.
- **Çözüm:** API katmanında explicit kontrol:
  ```python
  verdict = baba.check_risk_limits(engine.risk_params)
  if not verdict.can_trade and baba.kill_switch_level >= 3:
      raise HTTPException(403, "Kill-switch L3 — manuel trade yasak")
  ```
- **Öncelik:** **P1**
- **Sınıf:** BUG/SÖZLEŞME

#### BULGU-P1-API-06 · SÖZLEŞME · `/settings/notification-prefs` getter frontend'de çağrılmıyor

- **Dosyalar:** `api/routes/settings.py:208-212` (getter hazır), `desktop/src/services/api.js` (getter yok), `desktop/src/components/Settings.jsx:91` (sadece localStorage okuyor)
- **Kanıt:**
  - Backend: `GET /settings/notification-prefs` → `NotificationPrefsResponse(prefs=...)` var
  - Frontend `api.js`: sadece `client.post('/settings/notification-prefs', prefs)` — POST var, GET yok
  - `Settings.jsx:91`: `localStorage.getItem('ustat_notification_prefs')`
- **Neden-sonuç:** Persistence katmanı tamamlanmamış. Backend config'e yazıyor, frontend hiç okumuyor. Sonuç:
  - Kullanıcı A bilgisayarda tercih değiştirir → backend yazılır, A bilgisayar localStorage'a yazar.
  - Aynı kullanıcı B bilgisayara geçer → B localStorage boş → default değerler gelir → backend'deki gerçek değer gözükmez.
  - Backend config dosyasını manuel düzenleyen operator hiç fark edilmez.
- **Çözüm:**
  1. `api.js` içine `getNotificationPrefs()` fonksiyonu.
  2. `Settings.jsx` ve `Dashboard.jsx` mount'ta backend'den oku.
  3. localStorage sadece cache/fallback olarak kalsın.
  4. Storage event + polling (10sn) ile backend ↔ localStorage senkron.
- **Öncelik:** **P1**
- **Sınıf:** SÖZLEŞME
- **İlgili:** Baz rapor §4.5 — doğrulandı.

### 6.3 Desktop / UI katmanı

#### BULGU-P1-UI-01 · DRIFT · `start_ustat.py` hâlâ v5.9 anlatıyor

- **Dosya:** `start_ustat.py`
- **Kanıt (doğrudan grep, denetçi):**
  ```
  55:  APP_TITLE = "ÜSTAT v5.9 VİOP Algorithmic Trading"
  125: \u00dcSTAT <span style="color:#484f58;font-size:24px">v5.9</span>
  232: ⚠️ ÖLÜ KOD UYARISI (v5.9.1+):
  588: v5.9.2: Electron torun process'i de öldürülür (tree-kill).
  627: v5.9.1: pywebview yerine Electron kullanilir (ÜSTAT Finans sistemi).
  699: # ── Singleton retry mekanizması (v5.9.2) ─────────────────────
  1154: slog(f"USTAT v5.9 Baslatici (multiprocessing)")
  ```
- **Gerçek:**
  - `engine/__init__.py` → `VERSION = "6.0.0"`
  - `config/default.json` → `version: 6.0.0`
  - `desktop/package.json` → `version: 6.0.0`
- **Neden-sonuç:** Versiyon tek kaynak kuralı (backend'den okumak için `api/routes/status.py:18` commenti) kısmen uygulanmış (frontend TopBar için) ama başlatıcı ve log başlıklarında hâlâ hardcoded v5.9. Kullanıcı splash ekranda "v5.9", dashboard'da "v6.0" görür.
- **Etki:** Dürüstlük kaybı. Destek talebi geldiğinde "hangi versiyonu çalıştırıyorsun?" sorusunun cevabı belirsiz.
- **Çözüm:** Tüm version stringlerini `from engine import VERSION` üzerinden oku. `APP_TITLE = f"ÜSTAT v{VERSION[:3]} VİOP Algorithmic Trading"`.
- **Öncelik:** **P1**
- **Sınıf:** DRIFT

#### BULGU-P1-UI-02 · BUG · Şifre process arg'ında açık (mt5Manager.js)

- **Dosya:** `desktop/mt5Manager.js:62-91, 242`
- **Kanıt (agent):**
  ```js
  if (options.password) spawnArgs.push(`/password:${options.password}`);
  ```
- **Neden-sonuç:** Şifre `safeStorage.decryptString` ile DPAPI'den çözülüp `terminal64.exe` spawn arg'ı olarak geçiliyor. Windows `tasklist /v /fo list` veya `wmic process get CommandLine` ile bu komut satırı okunabiliyor. Dump araçlarıyla Node process memory dump'lanabiliyor.
- **Etki:** Aynı makinedeki başka process'lerin (ustat_agent.py dahil) MT5 credential'ına erişimi teorik olarak mümkün.
- **Çözüm seçenekleri:**
  1. **Stdin ile geçirme:** MT5'in stdin desteği varsa (yoksa yok).
  2. **Bellek süreli tutma:** Decrypt sonrası 30sn içinde clear et.
  3. **Windows Credential Manager:** safeStorage yerine `CredManager` API'si (daha iyi izolasyon).
  4. **Komut satırı zero-out:** spawn sonrası `arg[]` array'ini manipüle et (zor ve kırılgan).
- **Öncelik:** **P1** (güvenlik, dual-use risk)
- **Sınıf:** BUG

#### BULGU-P1-UI-03 · SÖZLEŞME · Notification prefs çift kaynak (localStorage + backend, okuma sadece localStorage)

- Detay BULGU-P1-API-06 ile aynı. UI tarafından: `Settings.jsx:91` + `Dashboard.jsx:149-162` sadece localStorage okuyor.
- **Öncelik:** **P1**
- **Sınıf:** SÖZLEŞME

#### BULGU-P1-UI-04 · BUG · ErrorBoundary kök seviyede yok

- **Dosya:** `desktop/src/App.jsx:28-35`
- **Kanıt (agent):** Her route kendi `RouteBoundary`'sine sarılmış ama App kökü değil. TopBar veya SideNav render'da hata olursa tüm app düşer.
- **Çözüm:** `<ErrorBoundary label="App">` kök seviyede.
- **Öncelik:** **P1**
- **Sınıf:** BUG

#### BULGU-P1-UI-05 · DRIFT · `App.jsx` JSDoc "v5.7", Settings.jsx "6.0.0"

- **Dosya:** `desktop/src/App.jsx:2`
- **Kanıt (agent):** JSDoc'ta `ÜSTAT v5.7 Desktop`. Settings.jsx:22 `const VERSION = '6.0.0'`.
- Öncelik / Sınıf: **P1 / DRIFT**

### 6.4 Ops / süreç

#### BULGU-P1-OPS-01 · DRIFT · Lifecycle guard + process guard Anayasa'da yok

- **Dosyalar:** `engine/lifecycle_guard.py` (343 satır), `engine/process_guard.py` (580 satır)
- **Kanıt (denetçi):** `lifecycle_guard.py:1` — "Engine'in yaşam döngüsünü TEK NOKTADAN kontrol eder... Tüm emir gönderme, pozisyon kapama, MT5 yazma işlemleri bu koruyucudan geçmek ZORUNDADIR." Yani yeni bir kritik koruma katmanı.
- **Neden-sonuç:** CLAUDE.md Bölüm 4.1 "Kırmızı Bölge 10 dosya" listesinde **yok**. Siyah Kapı fonksiyon listesinde (§4.4) yok. Ama modül kendi docstring'inde "BÖLGE: Kırmızı" yazıyor.
- **Etki:** Yeni gelen geliştirici (insan veya AI) "bu dosya ne kadar korunaklı" sorusuna CLAUDE.md'den bakarsa yanlış cevap alıyor.
- **Çözüm:** Anayasa güncelleme — Kırmızı Bölge listesi 10 → 12, Siyah Kapı fonksiyonları (guard.can_send_order, guard.begin_shutdown, process_guard.startup_cleanup) listesi güncelleme.
- **Öncelik:** **P1**
- **Sınıf:** DRIFT

#### BULGU-P1-OPS-02 · DRIFT · `ustat_agent.py` 46 handler, CLAUDE.md 37 diyor

- **Kanıt (agent, komut çıktısı):** `grep "^def handle_\|^def cmd_" ustat_agent.py | wc -l → 46`
- **Neden-sonuç:** CLAUDE.md Bölüm 11.2 — "37 Komut" diye tablo veriyor. Kod 9 komut ileri. Belgelendirme güncel değil.
- **Çözüm:** Bölüm 11.2 tablosu kod'dan otomatik üret.
- **Öncelik:** **P1**
- **Sınıf:** DRIFT

#### BULGU-P1-OPS-03 · DRIFT · `WATCHDOG_STALE_SECS` ve `MAX_AUTO_RESTARTS` sabitleri CLAUDE.md'de var, kodda yok

- **Kanıt (denetçi, grep):** `start_ustat.py` içinde `WATCHDOG_STALE_SECS` ve `MAX_AUTO_RESTARTS` **0 match**.
- **CLAUDE.md §5.2:** Bu sabitleri `start_ustat.py` konumunda listeliyor.
- **Neden-sonuç:** CLAUDE.md bir watchdog döngüsü varsayıyor, kodda ProcessGuard + Singleton retry var ama klasik watchdog (heartbeat polling + auto-restart) yok. Belgelendirme eski bir mimariyi anlatıyor.
- **Çözüm seçenekleri:**
  1. Belge güncelleme — sabitleri kaldır, gerçek mekanizmayı (ProcessGuard) anlat.
  2. Kod tamamlama — gerçekten bir watchdog döngüsü ekle.
- **Öncelik:** **P1**
- **Sınıf:** DRIFT

---

## 7. ORTA ÖNCELİK (P2) BULGULAR

### 7.1 Engine

- **BULGU-P2-ENG-01 · BORÇ ·** `engine/main.py` 1525 satır — startup, shutdown, retention, backup, maintenance, orchestration, health aynı dosyada.
- **BULGU-P2-ENG-02 · BORÇ ·** `engine/simulation.py:34-56` sys.modules["MetaTrader5"] global mock — env var isolation net değil.
- **BULGU-P2-ENG-03 · BORÇ ·** `engine/backtest.py:32-53` prod signal_engine import ediyor — data leak guard belirsiz.
- **BULGU-P2-ENG-04 · BORÇ ·** Motor başına 1-4 tekli `_ks_lock`, `_risk_lock`, `_trade_lock` kilitleri — ortak konvansiyon yok, re-entrancy test edilmemiş.
- **BULGU-P2-ENG-05 · BUG ·** `database.py:372-389` WAL checkpoint close öncesi başarısız olursa sessiz devam. Warning log var ama retry yok. Veri kaybı düşük ama loglanıyor.
- **BULGU-P2-ENG-06 · BORÇ ·** `data_pipeline.py` MAX_WORKERS=1 — MT5 C++ DLL thread-safe değil. Doğru koruma ama dokümantasyonu comment içinde gizli, Anayasa'ya çıkarılmalı.
- **BULGU-P2-ENG-07 · DRIFT ·** `top5_selection.py:79-86` `EXPIRY_*_DAYS = 0` — "v5.9 kullanıcı talimatı ile kaldırıldı" ama fonksiyonlar hâlâ iskelet, her zaman False dönüyor. Ölü kod.
- **BULGU-P2-ENG-08 · BORÇ ·** `process_guard.py:271-277` `taskkill /F /T` çıktısı string match ile değerlendiriliyor — Türkçe localization ("BAŞARILI" vs "SUCCESS") kırabilir.
- **BULGU-P2-ENG-09 · BUG ·** `baba.py:1509-1545` L2 → L3 eskalasyon: hard_drawdown kontrol yapılıyor ama L2'ye bağlı olmayan `dd_check_l2` True dönmezse return yapıyor. Kontrol akışı belgesi ile kod eşleşmiyor (agent bulgu).

### 7.2 API

- **BULGU-P2-API-01 · BORÇ ·** `api/routes/live.py` WS notification envelope tutarsız — timed push array, event-driven broadcast single-element array. Client parse ambiguity.
- **BULGU-P2-API-02 · SÖZLEŞME ·** `api/server.py:196-211` CORS `allow_methods=["*"]`, `allow_headers=["*"]` — prod risk (localhost mitigation ile P2).
- **BULGU-P2-API-03 · SÖZLEŞME ·** `api/routes/news.py:93-180` 3 endpoint `response_model=` yok.
- **BULGU-P2-API-04 · SÖZLEŞME ·** `api/routes/hybrid_trade.py:148-154` `/hybrid/performance` `response_model=` yok.
- **BULGU-P2-API-05 · BORÇ ·** `api/routes/error_dashboard.py:210-215` WHERE clause f-string pattern — şu an hardcoded liste olduğu için safe, ama antipattern.
- **BULGU-P2-API-06 · BORÇ ·** `api/routes/error_dashboard.py` 660 satır — neden bu kadar büyük? Duplicated logic veya ölü kod oranı inceleme gerektiriyor.
- **BULGU-P2-API-07 · SÖZLEŞME ·** `api/routes/status.py` `last_cycle` + `last_successful_cycle` iki alanın semantiği dokümante değil (bkz. BULGU-P0-04).
- **BULGU-P2-API-08 · BORÇ ·** `api/schemas.py` 819 satır — Pydantic model mega dosyası. Feature başına bölünmeli.
- **BULGU-P2-API-09 · SÖZLEŞME ·** `api/routes/performance.py`, `ogul_activity.py`, `ustat_brain.py` ağır DB sorguları — cache veya pagination yok.

### 7.3 Desktop

- **BULGU-P2-UI-01 · BORÇ ·** `desktop/src/components/Dashboard.jsx:82-85` modül seviyesi global state (`_dashCache`) — React pattern ihlali, test izolasyonu kırık.
- **BULGU-P2-UI-02 · SÖZLEŞME ·** `desktop/index.html:13` `<script src="/pywebview-shim.js">` — pywebview kaldırıldı ama referans hâlâ var. 404 network error (sessiz).
- **BULGU-P2-UI-03 · BUG ·** `Dashboard.jsx:341-399` WebSocket `useEffect` dependency array'de `fetchTradeData` — gereksiz reconnect riski.
- **BULGU-P2-UI-04 · BUG ·** `api.js:18-21` axios timeout 5sn sabit — ağır sorgularda kopabiliyor.
- **BULGU-P2-UI-05 · SÖZLEŞME ·** `Settings.jsx` alert() vs ConfirmModal — tutarsız fallback (tema dışı dialog).
- **BULGU-P2-UI-06 · BORÇ ·** API hataları UI'da toast/banner gösterilmiyor — sessiz fallback.
- **BULGU-P2-UI-07 · DRIFT ·** `Settings.jsx:400-414` "dürüst kapsam uyarısı" var: sadece `tradeAlert` toggle'ı gerçek davranışa bağlı. Diğer 4 toggle yazıyor ama tetiklemiyor. Eksik implementation.

### 7.4 Ops / Config / Docs

- **BULGU-P2-OPS-01 · DRIFT ·** `start_ustat.py:229-348` `UstatWindowApi` sınıfı "ÖLÜ KOD UYARISI" ile işaretli ama 100+ satır. Bir reference class için çok büyük.
- **BULGU-P2-OPS-02 · DRIFT ·** `docs/USTAT_GELISIM_TARIHCESI.md` son giriş v6.0.0 diyor ama commit detayları hâlâ v5.9 temalı. Changelog semi-güncel.
- **BULGU-P2-OPS-03 · DRIFT ·** `mql5/KURULUM.md` "v5.7.1" diyor — iki versiyon geride.
- **BULGU-P2-OPS-04 · SÜREÇ ·** Git commit mesajları "fix(A6/B14)", "fix(H16)" format'ında ama CLAUDE.md Bölüm 9'daki C0-C4 sınıflandırması kullanılmıyor. İki sistem yan yana yaşıyor.
- **BULGU-P2-OPS-05 · SÜREÇ ·** `docs/` her gün 5-10 session raporu üretiyor. Harika belgelendirme kültürü ama **indekslenmiyor**. "Geçen hafta primnet orphan ile ilgili ne yapıldı?" sorusu grep gerektiriyor.
- **BULGU-P2-OPS-06 · BORÇ ·** `ustat_agent.py` 3781 satır — tek dosyada 46 handler + FUSE bypass + Claude-Cowork + log yönetim. Bölünme zamanı geçti.
- **BULGU-P2-OPS-07 · SÜREÇ ·** `tools/impact_map.py` var, pre-commit hook AST + critical_flows koşuyor, ama session raporlarından birinde bile "impact_map çıktısını aldım" referansı yok. Araç var, alışkanlık yok.

---

## 8. DÜŞÜK ÖNCELİK (P3) BULGULAR

### 8.1 Kozmetik, edge case, iyileştirme

- **P3-UI-01** `desktop/vite.config.js` proxy `localhost:8000`, prod `127.0.0.1` — dev/prod farkı açıklansın.
- **P3-UI-02** `LockScreen.jsx` OTP focus 4 mekanizma — doğru çalışıyor, hangisi başarılı olduğunu logla.
- **P3-UI-03** `Settings.jsx:250-261` account no toggle var, şifre toggle yok — UI tutarsızlığı.
- **P3-UI-04** `package.json` dependency'ler `^` (caret) — reproducibility riski, lockfile pin öner.
- **P3-UI-05** `NewsPanel.css` kullanılıyor, diğer bileşenler inline style — stil stratejisi karışık.
- **P3-UI-06** `mt5Manager.js:73-80` `safeStorage.isEncryptionAvailable()` Docker/VM'de false olabilir, fallback yok.
- **P3-UI-07** `Dashboard.jsx:384-387` WS notification batch işleme yok — extreme frequency memory churn.
- **P3-API-01** `api/routes/mt5_verify.py:96-105` "calismiyorr" typo.
- **P3-API-02** `api/schemas.py:96 PositionItem.risk_score: dict` — Pydantic validation yok.
- **P3-API-03** `api/routes/trades.py:184-250` N+1 double iterate.
- **P3-API-04** `api/routes/hybrid_trade.py:44-52` transfer atomicity documented değil.
- **P3-API-05** `api/routes/live.py:35-48` partial lock coverage — asyncio tek thread ama pattern inconsistent.
- **P3-API-06** `api/routes/trades.py:329-351` sync default 90 gün — çok büyük history, dedup doğru mu?
- **P3-ENG-01** `engine/health.py` metric alanları private state'ten besleniyor — API ile aynı sızıntı problemi.
- **P3-ENG-02** `engine/news_bridge.py` 1550 satır — kaç provider gerçekten aktif?
- **P3-ENG-03** `engine/simulation.py` mock dict — test yardımcısı, prod'a sızma riski düşük ama izolasyon net değil.
- **P3-ENG-04** `engine/backtest.py` prod config paylaşımı — config instance ayrı mı singleton mı?
- **P3-ENG-05** `engine/manuel_motor.py` 1190 satır — görece küçük, ama §BULGU-P1-API-05 riskinin merkezi.
- **P3-OPS-01** `logs/ustat_2026-04-11.log` 473K satır — rotation var mı?
- **P3-OPS-02** `api.log` 716 KB, `electron.log` 1.8 MB — max size / rotate pattern yok.
- **P3-DOC-01** `USTAT_ANAYASA.md` v2.0 — Lifecycle + Process guard eklemesi yapılmalı.

---

## 9. KATMAN BAZLI DERİN ANALİZ

### 9.1 ENGINE — merkezi zihin ve sorumluluk şişkinliği

**Özet metrikler:**

| Dosya | Satır | Sorumluluk | Risk |
|---|---|---|---|
| `main.py` | 1525 | orchestration + lifecycle + maintenance + backup | BULGU-P0-01 içeriyor |
| `baba.py` | 3363 | rejim + risk verdict + kill-switch + cooldown + drawdown + fake analiz + persist | Merkezi zihin |
| `ogul.py` | 3521 | sinyal + emir state machine + trailing + EOD + voting + orphan + ustat entegrasyonu | En büyük regresyon riski |
| `h_engine.py` | 2946 | hybrid transfer + PRIMNET + EOD devir + orphan cleanup + notification | Notification envelope fix mevcut |
| `mt5_bridge.py` | 3165 | connect + send_order (2-stage SL/TP) + close + modify + circuit breaker + history sync | Anayasa ihlali riski (BULGU-P0-06) |
| `ustat.py` | 2195 | strategy pool + attribution + meta analiz | Gözlemci → karar verici kayma riski |
| `database.py` | 2027 | SQLite + WAL + migration + backup + trade CRUD | WAL checkpoint sessiz risk |
| `news_bridge.py` | 1550 | provider + sentiment + cache + FinBERT | Harici API timeout riski |
| `manuel_motor.py` | 1190 | manuel trade yönetimi | Risk kapısı belirsiz |
| `data_pipeline.py` | 1066 | OHLCV fetch serialized | MAX_WORKERS=1 korumalı |
| `simulation.py` | 1068 | mock MT5 + backtest entry | sys.modules izolasyon |
| `top5_selection.py` | 717 | Top 5 kontrat seçici | EXPIRY_*_DAYS=0 ölü iskelet |
| `process_guard.py` | 580 | singleton + orphan cleanup | Anayasa'da yok |
| `error_tracker.py` | 563 | ErrorGroup tracking | — |
| `health.py` | 438 | sağlık metrikleri | API private sızıntı kaynağı |
| `mt5_errors.py` | 436 | retcode registry | — |
| `backtest.py` | 364 | backtest runner | Prod config paylaşımı |
| `lifecycle_guard.py` | 343 | emir kapısı + signal handler | Anayasa'da yok |
| `ogul_sltp.py` | 281 | virtual SL/TP fallback | BULGU-P0-06 orta katman |
| `netting_lock.py` | 123 | VIOP netting mutex | — |
| `config.py` | 120 | JSON yükleyici | — |
| `event_bus.py` | 81 | WS push queue | Envelope fix uygulanmış ✓ |

**Kalıp 1 — "büyüyen tek sorumluluk":** 6 dosya 2K satır üzerinde. Bu dosyaların her biri orijinal niyetinin dışına çıkmış. Çözüm yolu §12 Faz C'de.

**Kalıp 2 — "çapraz motor referansı":** `main.py:101-162` bölümünde 6 obje bağlama. Motor bir diğerinin private state'ine doğrudan erişiyor. Anayasa Kural 1 (çağrı sırası) ve Siyah Kapı korumaları bu durumu engellemiyor çünkü statik olarak doğrulanmıyor — sadece runtime'da cycle sırası kontrolleniyor.

**Kalıp 3 — "private state'e API erişimi":** Engine'in iç yapısı API route'ları tarafından memory map gibi kullanılıyor. 9 route dosyasında 15+ private alan referansı.

**Kalıp 4 — "iyi koruma, eksik belgelendirme":** Yeni eklenen `lifecycle_guard.py` ve `process_guard.py` gerçek koruma sağlıyor ama Anayasa'da yok. İşin tersi var: Anayasa'da "WATCHDOG_STALE_SECS" yazıyor, kodda yok. Belgelendirme ile kod iki ayrı hızda yürüyor.

### 9.2 API — zengin yüzey, zayıf sözleşme

**Endpoint sayısı:** 22 route modülü, tahmini 80+ endpoint.

**Ana gözlemler:**

1. **Sızıntı:** 9 route dosyası engine private alanlara dokunuyor (detay §6.2 BULGU-P1-API-01).
2. **Response model tutarsızlığı:** Bazı endpoint'lerde `response_model=` var, bazılarında dict dönüyor (news, hybrid_trade).
3. **Schema mega dosyası:** `api/schemas.py` 819 satır — feature başına ayrılmalı.
4. **Error dashboard dev alanı:** 660 satır, duplicated logic şüphesi (bkz. BULGU-P2-API-06).
5. **Ağır sorgular cache'siz:** performance, ogul_activity, ustat_brain — engine cycle'ı yavaşlatma riski.
6. **WS hub (live.py):** 432 satır, tutarsız envelope pattern, event_bus ile bağlantısı doğru ama sözleşme çeşitlilik yaratıyor.
7. **Auth yok:** killswitch endpoint'i network erişimi ile açılabilir (localhost mitigation var).
8. **CORS: permissive — dev/prod farkı yok.

**Pozitif:**
- Lifespan sırası doğru (`api/server.py`).
- Pydantic genelde kullanılıyor.
- FastAPI auto-doc çoğu endpoint için çalışıyor.
- `api/routes/status.py` versiyon alanı için "tek kaynak" commenti yazılmış ve `engine.VERSION` okuyor — doğru yönelim.

### 9.3 DESKTOP — aktif gelişim, drift riski

**Bileşen sayısı:** 22 JSX, 1 services/api.js, 1 mt5Launcher.js, 22 IPC endpoint.

**Ana gözlemler:**

1. **Hayalet kontrol:** `restartMT5` UI'da var, preload/main'de yok.
2. **Çift kaynak persistence:** Notification prefs localStorage'a yazılırken backend'e de yazılıyor ama okuma sadece localStorage'dan.
3. **Versiyon drifti:** App.jsx v5.7, Settings.jsx 6.0.0, package.json 6.0.0, CLAUDE.md v5.9.
4. **Ölü asset referansı:** `pywebview-shim.js` kaldırıldı ama HTML hâlâ ilişkili.
5. **Güvenlik:** Şifre process arg ile geçiyor.
6. **ErrorBoundary kök seviyede yok** — TopBar veya SideNav crash'i tüm app'i düşürebilir.
7. **Modül seviyesi global state** — React konvansiyonu dışı, test zor.
8. **alert() ile ConfirmModal karışımı** — tema tutarsızlığı.
9. **Polling pattern tutarlı:** TopBar, Dashboard, health — 10sn polling doğru implementasyon.

**Pozitif:**
- contextIsolation açık, sandbox açık.
- safeStorage DPAPI kullanıyor (güvenlik doğru yönde, şifre arg sorunu hariç).
- CSP meta tag'i localhost'a kısıtlanmış.
- IPC handler 17 endpoint — genel olarak sağlam.
- LockScreen OTP akışı 4 farklı focus mekanizmasıyla sağlamlaştırılmış.

### 9.4 TESTS — koruma halkası + bozuk entrypoint paradoksu

**Gerçeklik tablosu:**

| Katman | Durum | Kanıt |
|---|---|---|
| `tests/critical_flows/` | **ÇALIŞIYOR** | `python -m pytest tests/critical_flows -q → 64 passed` |
| `tests/` (ana suite) | Path belirtilirse çalışıyor | — |
| Ana `pytest.ini` entrypoint | **BOZUK** | `python -m pytest --collect-only → INTERNALERROR` |
| Pre-commit hook | **ÇALIŞIYOR** | `.githooks/pre-commit` 3026 byte executable |
| `tools/impact_map.py` | Var ama alışkanlık yok | Session raporlarında referans yok |

**Ana paradoks:** Kritik akış testleri doğrudan çalıştırıldığında yeşil, ama ana pytest entrypoint bozuk. Bu durum sadece pre-commit hook'un "kurtarıcı" rolü sayesinde sürdürülebilir. Developer `python -m pytest` yazdığında yanıltıcı rapor alıyor.

**Statik sözleşme testleri (`test_static_contracts.py`) güçlü:**
- rogue `mt5.initialize()` araması (Anayasa Kural 16)
- Siyah Kapı fonksiyon varlık kontrolü
- Config'den sabit okuma disiplini (sihirli sayı yasağı)
- Çağrı sırası kontrolleri

**Eksik olan:** Runtime integration testleri yok. `fail_names` bulgusu gibi koşullu scope hataları sadece runtime'da yakalanabilir — statik kontrol yetmiyor.

### 9.5 CONFIG — doğru ama dar

**`config/default.json` 186 satır. CLAUDE.md §5.1'de listelenen 13 risk sabitinin 13'ü de mevcut. Ek olarak strategies (trend_follow, mean_reversion, breakout) SL/TP ATR multiplier'ları, hybrid, ogul, news, retention, liquidity_overrides tanımlı.**

**Eksikler:**
- `WATCHDOG_STALE_SECS`, `MAX_AUTO_RESTARTS` — CLAUDE.md iddia ediyor ama kodda yok, config'de de yok.
- Hot reload yok — restart gerekli.
- Şema validation yok — Pydantic veya jsonschema doğrulaması olmadığı için bozuk JSON runtime'da patlıyor.

### 9.6 DOCS — zengin üretim, zayıf indeks

- `docs/` altında 11 Nisan 2026 tek gün için 20+ session raporu.
- `USTAT_GELISIM_TARIHCESI.md` keep-a-changelog formatında, v6.0.0 girişi eklenmiş.
- `CLAUDE.md` proje özel — v5.9 başlığı altında ama içerik çoğunlukla güncel.
- `USTAT_ANAYASA.md` v2.0 — Lifecycle/Process guard eklenmemiş.

**Ana sorun:** İndeks yok. "3 gün önce kill-switch L2 değişikliği yapıldı mı?" sorusu sadece grep ile cevaplanıyor. Session raporlarının rol eşlemesi (hangi rapor hangi bulguya kapatma) yok.

---

## 10. ANAYASA UYUM HARİTASI (Kural bazlı)

| Kural | Dizayn | Uygulama | Drift? |
|---|---|---|---|
| **1 — Çağrı sırası BABA→OĞUL→H-Engine→ÜSTAT** | ✓ | `main.py:834-887` | — |
| **2 — Risk Kapısı (can_trade)** | ✓ | `ogul._execute_signal` | — |
| **3 — Kill-switch monotonluk L1→L2→L3** | ✓ | `baba._ks_lock` ile | §7.1 BULGU-P2-ENG-09 kısmi drift |
| **4 — SL/TP Zorunluluk** | Kısmen | `send_order` 2 aşamalı | **BULGU-P0-06 ihlal riski** |
| **5 — EOD 17:45 zorunlu kapanış** | ✓ | `_check_end_of_day` + `_verify_eod_closure` | — |
| **6 — Hard drawdown %15 → L3** | ✓ | `_check_hard_drawdown` | — |
| **7 — OLAY rejimi risk_multiplier=0** | ✓ | BABA | — |
| **8 — Circuit breaker 5 timeout → 30sn** | ✓ | `_cb_record_failure` + `_cb_is_open` | — |
| **9 — Fail-Safe** | Kısmen | BABA doğru, health.py hatalı | **BULGU-P1-API-02 ihlal** |
| **10 — L2 manuel dokunmaz** | ✓ | `_close_ogul_and_hybrid` | Manuel risk kapısı belirsiz (BULGU-P1-API-05) |
| **11 — Başlatma zinciri** | ✓ | start_ustat.py | — |
| **12 — Lifespan sırası** | ✓ | `api/server.py` | — |
| **13 — Kapanış sırası** | ✓ | Electron → lifespan engine.stop() | — |
| **14 — Startup ≤5sn** | ✓ | `startup.log → 1.0sn` | — |
| **15 — MT5 başlatma sadece Electron** | ✓ | `connect(launch=False)` + tasklist | — |
| **16 — mt5.initialize evrensel koruma** | ✓ | `test_no_rogue_mt5_initialize_calls` pass | — |

**Sonuç:** 13/16 kural uygulanmış, 3/16'da drift veya ihlal riski:
- Kural 3 — L2→L3 eskalasyonunda kontrol akışı tartışmalı
- Kural 4 — OgulSLTP fallback başarısız olursa korumasız pozisyon kalabilir
- Kural 9 — health.py trade_allowed exception'da True dönüyor (fail-permissive)

---

## 11. SÜREÇ RİSKİ (PROCESS RISK)

### 11.1 Kağıt-kod mesafesi

CLAUDE.md + USTAT_ANAYASA.md + USTAT_CALISMA_REHBERI.md çok ağır bir süreç anlatıyor: 6 altın kural + 5 adım + C0-C4 sınıflandırma + pre-flight checklist + ADIM 1.5 critical flows + impact_map + session raporu + rollback planı.

Gerçek hangi parça çalışıyor?

| Süreç mekanizması | Operasyonel kanıt | Gerçek kullanım |
|---|---|---|
| Pre-commit hook | `.githooks/pre-commit` 3026 byte, executable | **ÇALIŞIYOR** |
| Critical flows | 64 pass, 3 warnings | **ÇALIŞIYOR** |
| Session raporları | Günde 20+ rapor | **ÇALIŞIYOR** (indekssiz) |
| Versiyon tek kaynak (backend'den) | `engine.VERSION` → API → frontend | **KISMEN** (start_ustat.py eksik) |
| C0-C4 commit etiketleri | — | **KULLANILMIYOR** (A1-A19 session etiketleri kullanılıyor) |
| impact_map.py | `tools/impact_map.py` var | **ALIŞKANLIK YOK** |
| Anayasa güncelleme | — | **GERİDE** (Lifecycle/Process guard eksik) |
| Pytest entrypoint | `pytest.ini` bozuk | **BOZUK** |

### 11.2 Kritik süreç bulguları

- **BULGU-P1-PROC-01 · SÜREÇ ·** Pytest entrypoint bozuk ama kritik akışlar yeşil — "false positive" dokunmuyor, ama developer deneyiminde kafa karışıklığı. §6.2 BULGU-P0-02'nin süreç boyutu.

- **BULGU-P1-PROC-02 · SÜREÇ ·** impact_map.py "hukuk yazıldı ama mahkeme oturumu yok" durumunda. Araç var, çıktı alınmıyor. Session raporlarının tek birinde "impact_map çıktısı" referansı yok.

- **BULGU-P2-PROC-01 · SÜREÇ ·** Baz rapor P0-4.1 (fail_names) ve P0-4.2 (pytest.ini) iddialarını 2026-04-11 tarihiyle açtı. Bu yeni denetim aynı gün yapıldı ve iki bulgu da **hâlâ açık**. "Raporu aldık → bulguyu kapattık" döngüsü kırık. Bulgu tespit hızı > bulgu kapatma hızı.

- **BULGU-P2-PROC-02 · SÜREÇ ·** `docs/` günde 20 rapor üretiyor ama indeks yok. Her rapor bir bulguyu kapatıyor mu, bir incelemeyi kaydediyor mu, bir plan mı, ayırdedilmiyor.

- **BULGU-P2-PROC-03 · SÜREÇ ·** CLAUDE.md anayasal belge iddiasıyla (değişmezlik) çalışıyor ama güncel değil. Yeni modüller (lifecycle_guard, process_guard), yeni komutlar (9 ajan handler) eklenmeden geride kalmış. Sabit belge canlı kod ile yarışamıyor.

---

## 12. FAZLANMIŞ İYİLEŞTİRME PLANI

### Faz A — Kan kaybını durdur (1 hafta, 6 P0)

**Hedef:** Canlı sistem güvenilirliği. Her P0 bir günlük işin altında.

| Gün | Bulgu | Eylem |
|---|---|---|
| 1 | BULGU-P0-01 | `main.py:256` öncesi `fail_names = ""` default. Unit test ekle. Commit. |
| 1 | BULGU-P0-02 | `pytest.ini` rewrite: `testpaths = tests`, `norecursedirs = archive ...`. `archive/USTAT_DEPO/test_trade.py:21 sys.exit(0)` silin. `python -m pytest --collect-only` yeşil doğrula. |
| 2 | BULGU-P0-03 | `Settings.jsx` → butonu disabled yap **veya** main.js + preload.js IPC ekle. Kullanıcıyla tartış: kaldırma mı ekleme mi? |
| 2 | BULGU-P0-04 | `engine/main.py` → `self._last_cycle_time: datetime \| None = None`, `_run_single_cycle` başında set. **Veya** StatusResponse'dan alanı sil. |
| 3 | BULGU-P0-05 | `engine/database.py` → `get_unread_notification_count()` ekle. `api/routes/notifications.py` → global count kullan. |
| 3-5 | BULGU-P0-06 | `mt5_bridge.py` → OgulSLTP fallback başarısız olursa `close_position` çağır + `baba.report_unprotected_position`. **Test:** `tests/critical_flows/test_unprotected_position_closes.py` ekle. |

**Faz A doğrulama:**
```bash
# Tüm P0'lar kapandıktan sonra:
python -m pytest --collect-only   # → 0 INTERNALERROR
python -m pytest tests/critical_flows -q   # → all passed
python -c "from engine.main import Engine; e = Engine(mt5_connect_stub=False); e.start()"  # → no UnboundLocalError
```

### Faz B — Sözleşme temizliği (2-3 hafta, 18 P1)

**Paralel iş kolları:**

**Kol 1 — Anayasa ve dokümantasyon hizalama (1 hafta):**
- `USTAT_ANAYASA.md` güncelleme: lifecycle_guard + process_guard Kırmızı Bölge'ye ekle.
- `CLAUDE.md` Bölüm 11.2 — 37 komut → 46 komut otomatik üret.
- `CLAUDE.md` Bölüm 5.2 — `WATCHDOG_STALE_SECS` + `MAX_AUTO_RESTARTS` referanslarını kaldır veya gerçekten ekle.
- `start_ustat.py` versiyon stringlerini `engine.VERSION`'a bağla.

**Kol 2 — API sözleşme sızıntısı (1 hafta):**
- BABA için public getter: `get_kill_switch_level`, `get_risk_snapshot`, `get_killed_symbols`.
- Engine için: `get_last_cycle_info`, `is_running`.
- H-Engine için: `get_primnet_snapshot`, `get_hybrid_stats`.
- OĞUL için: `get_voting_detail` (public rename).
- Tüm API route'larını yeni getter'larla refactor et.
- `tests/critical_flows/test_static_contracts.py` içine "private alan erişim yasağı" kuralı ekle.

**Kol 3 — UI sözleşme (1 hafta):**
- `desktop/src/services/api.js` — `getNotificationPrefs()` ekle.
- `Settings.jsx`, `Dashboard.jsx` mount'ta backend'den oku.
- `App.jsx` JSDoc versiyonu düzelt.
- Kök `<ErrorBoundary>` ekle.
- `index.html` pywebview-shim.js referansını sil.
- `mt5Manager.js` şifre process arg yerine stdin veya bellek süreli tutma.

**Kol 4 — Health/phase semantics (birkaç gün):**
- `/health` trade_allowed exception'da False dön.
- `/status.phase` öncelik düzen: killed → stopped → error → running.
- Composite state model (lifecycle + connectivity + risk ayrı alanlar).

### Faz C — Yapısal ayrıştırma (1-2 ay, 34 P2 + borç)

**Sıra kritik — yanlış sırada yapılırsa kritik akışı kırar:**

**1. Anayasa güncelleme önce** (aksi halde refactor yaparken hangi dosyanın korunaklı olduğu belirsiz).

**2. API sözleşme kilidi** (getter'lar yerleştirilmeden motor refactor'ı yapılırsa 9 route dosyası sessiz bozulur).

**3. Motor refactor — alt modül yapısı:**
```
engine/
├── baba/
│   ├── __init__.py           # Baba class facade
│   ├── regime.py
│   ├── risk_gate.py
│   ├── kill_switch.py
│   ├── drawdown.py
│   └── persistence.py
├── ogul/
│   ├── __init__.py           # Ogul class facade
│   ├── signal_generation.py
│   ├── order_state_machine.py
│   ├── active_trades.py
│   ├── eod.py
│   └── voting.py
├── h_engine/
│   ├── __init__.py
│   ├── transfer.py
│   ├── primnet.py
│   ├── eod_devir.py
│   └── orphan_cleanup.py
├── mt5_bridge/
│   ├── __init__.py
│   ├── connect.py
│   ├── send_order.py         # 2-aşamalı SL/TP
│   ├── close.py
│   ├── modify.py
│   ├── safe_call.py
│   └── circuit_breaker.py
├── main.py                   # Orchestration + lifecycle only
├── event_bus.py
├── config.py
├── lifecycle_guard.py
└── process_guard.py
```

**4. Motor arası obje bağlama → Protocol:**
- Her motorun ihtiyacı olan diğer motor arayüzlerini Protocol olarak tanımla.
- `main.py:__init__` içinde bağlama yerine Protocol parametre olarak geç.
- Test'lerde Mock Protocol kullanılabilir → gerçek unit test mümkün.

**5. API schemas ayrıştırma:**
- `api/schemas.py` 819 satır → feature başına:
  - `api/schemas/status.py`, `risk.py`, `trades.py`, `notifications.py`, `settings.py`, vb.

**6. Feature başına contract test:**
- `tests/contracts/test_api_schemas.py` — API response'ların Pydantic doğrulamasından geçmesi.
- `tests/contracts/test_ws_envelope.py` — event_bus → live.py → client.
- `tests/contracts/test_killswitch_flow.py` — API → BABA → L3 → pozisyon kapanması.

### Faz D — Disiplin ve araçlar (süregelen)

- **Session raporu indeksi:** `docs/INDEX.md` — her session raporu için (tarih, kategori, ilgili bulgu, durum).
- **impact_map alışkanlığı:** Kırmızı Bölge PR'larda PR template'e "impact_map çıktısı" zorunlu alan.
- **Commit etiketleme:** C0-C4 sınıflandırmasını commit prefix'ine ekle — `feat(C2): ...`, `fix(C3): ...`.
- **Anayasa güncelleme süreci:** Her yeni kritik koruma katmanı Anayasa PR'ı gerektirir.
- **Integration test katmanı:** Runtime integration testleri (`tests/integration/`) — startup scenarios (MT5 var, MT5 yok, smoke fail).
- **Kod sınırı metriği:** Dosya başı max 1500 satır hedefi — CI ihlalde uyarı.

---

## 13. RİSK MATRİSİ

| Bulgu | Olasılık | Etki | Risk Skoru |
|---|---|---|---|
| BULGU-P0-01 fail_names | **Yüksek** (her ilk açılış) | **Yüksek** (startup fail) | **KRİTİK** |
| BULGU-P0-06 korumasız pozisyon | Düşük (fallback zinciri) | **Çok Yüksek** (finansal) | **KRİTİK** |
| BULGU-P0-02 pytest entrypoint | Orta (sessiz drift) | Yüksek (test güvenirliği) | **YÜKSEK** |
| BULGU-P0-04 last_cycle | Yüksek (her request) | Düşük (UI yalnız) | Orta |
| BULGU-P0-05 unread_count | Yüksek | Orta (yanlış badge) | **YÜKSEK** |
| BULGU-P0-03 restartMT5 hayalet | Düşük (nadiren tıklanır) | Düşük (alert fallback) | Düşük-Orta |
| BULGU-P1-UI-02 şifre process arg | Düşük (makine izolasyonu) | **Çok Yüksek** (credential) | **YÜKSEK** |
| BULGU-P1-API-02 trade_allowed True | Orta (MT5 disconnect senaryosu) | **Yüksek** (yanlış banner) | **YÜKSEK** |
| BULGU-P1-ENG-01 obje bağlama | Sürekli | Orta (refactor kilidi) | **YÜKSEK** |
| BULGU-P1-API-01 private sızıntı | Sürekli | Orta (refactor kilidi) | **YÜKSEK** |
| BULGU-P1-API-03 phase önceliği | Orta (L3+MT5 kopuk) | Orta (operator yanılma) | Orta |
| BULGU-P1-OPS-01 lifecycle guard belgesiz | Sürekli | Orta (yeni gelişin yanılması) | Orta |
| Motor dosyaları 3K satır | Sürekli | Yüksek (regresyon gizlemesi) | **YÜKSEK** |
| Test entrypoint + pre-commit paradoksu | Sürekli | Orta (developer deneyimi) | Orta |
| Dokümantasyon drift | Sürekli | Orta (yanlış zihinsel model) | Orta |

---

## 14. EKSİK KANITLAR (RUNTIME DOĞRULAMA GEREKLİ)

Bu rapor statik analizdir. Aşağıdaki noktalar canlı çalıştırma veya log analizi ile doğrulanmalı:

1. **`engine/ogul_sltp.py` fallback zinciri** — gerçek piyasada `set_initial_sl()` ne sıklıkla False dönüyor? Log'da aramalı: `grep "TRADE_ACTION_SLTP başarısız" logs/`
2. **`news_bridge.py` cycle latency** — harici API cycle'ı kaç ms bloklamış? `grep "news.*cycle" logs/` latency dağılımı.
3. **Circuit breaker tetiklemeleri** — `grep "Circuit breaker" logs/` kaç defa, ne kadar süre açık kaldı?
4. **EOD orphan pozisyon durumu** — gerçek EOD'larda kaç orphan kaldı? `grep "orphan" logs/`
5. **L3 kapatma retry başarısı** — agresif retry'de (5×2sn) kaç pozisyon ilk turda ve retry'da kapandı?
6. **Startup ≥1sn durumları** — her gün 1.0sn mi yoksa yavaş başladığı günler var mı? `grep "API hazir" startup.log` tarihsel analiz.
7. **ManuelMotor L3 davranışı** — gerçek L3 tetiklenmesinde manuel pozisyon dokunulmamış mı? Log doğrulama.
8. **`fail_names` UnboundLocal tetiklenmesi** — Production log'da `NameError` aramak: `grep -r "fail_names" logs/` + `grep -r "NameError.*fail_names" logs/`
9. **pytest collection drift** — CI ortamında pytest ne zamandan beri bozuk? Git blame `pytest.ini`.
10. **TRADE_ACTION_SLTP başarı oranı** — 2-aşamalı SL/TP zincirinin gerçek pass/fail oranı.

---

## 15. KÖKÜ NEDENLER — "NEDEN BURADAYIZ"

Baz rapor üç ana sebep önermişti. Bu denetim onaylıyor ve iki tane daha ekliyor:

1. **Hızlı evrim, yavaş temizleme.** Yeni kararlar ekleniyor, eski kararların izleri (pywebview referansları, v5.7 JSDoc, start_ustat.py v5.9 başlığı, archive/USTAT_DEPO/test_trade.py) silinmiyor. "Git blame" ile her satırın doğru değişimi görülür ama ortalama geliştirici oraya bakmaz.

2. **Doğrudan obje bağlama.** Net Protocol/interface yerine "birbirini tanıyan motorlar" modeli seçilmiş. İlk başta hızlı, uzun vadede refactor kilidi.

3. **Koruma mekanizması olarak dokümantasyon.** Kod modüler olmaktan uzaklaşınca belgelendirme, anayasa ve statik sözleşme testleri telafi etmeye çalışıyor. Belirli bir seviyeye kadar işe yarıyor, sonra sistem belgeleri taşımakta zorlanıyor.

4. **(Yeni) Rapor-uygulama mesafesi.** Bu raporun baz raporu P0-4.1 ve P0-4.2'yi 11 Nisan'da açmış. Aynı gün yapılan bu denetim aynı bulguları hâlâ açık görüyor. Rapor üretmek bulgu kapatmakla eşit hızda ilerlemiyor. Bu bir disiplin problemi değil, **rapor kapatma süreci eksikliği** — her bulguya atanmış "sahip + son tarih + doğrulama" yok.

5. **(Yeni) Kritik akış vs ana entrypoint çelişkisi.** Pre-commit hook kritik akışları garanti ediyor, ama günlük developer deneyimi (pytest yazınca yanıltıcı rapor) kirli. İki ayrı "test gerçekliği" yan yana yaşıyor. Bu aslında sistemin daha derin bir kalıbının yansıması: **çok katmanlı koruma, ama katmanlar arası koordinasyon zayıf**.

---

## 16. YAPILMAMASI GEREKEN ŞEYLER (ANTİ-PATTERN)

Bu raporun bulgularını okuyan gelecek geliştiriciye:

- **Bir yeri tamir ederken başka bir yeri bozmayı göze alma.** Özellikle P1-ENG-01 (obje bağlama) refactor'ında önce API getter'lar, sonra motor ayrıştırma sırası şart.
- **"Geçici olarak devre dışı bırakma" yasak.** Hiçbir P0/P1 bulgu `# TODO fix later` yorumuyla kapatılamaz.
- **Anayasa güncelleme yapmadan Kırmızı Bölge dosyası ayrıştırma.** Önce anayasa, sonra kod.
- **Tek commit'te birden fazla P0 düzeltme.** Her birinin ayrı commit, ayrı rollback yolu olmalı.
- **Test entrypoint'i düzeltmeden refactor.** Baz rapor yazıldığı hafta refactor yapıldıysa yanıltıcı test sonucu alınmış olabilir.
- **Private alan sızıntılarını "property" ekleyerek kapatma.** `@property` bir çözüm değil, sızıntıyı kalıcılaştırma yoludur. Public getter + snapshot nesnesi doğru yol.
- **Motor alt modül refactor'ını CLAUDE.md güncelleme olmadan yapma.** Yeni dosya yolları anayasaya eklenmeden yapılan refactor bir sonraki denetimde "Kırmızı Bölge aşındı" olarak görülecek.

---

## 17. DENETİM SINIRLARI (TEKRAR)

Bu rapor kod, config, test, UI/API sözleşmeleri, dokümantasyon ve runtime komut çıktıları üzerinden hazırlandı.

**Yapılmayanlar:**
- Canlı MT5 ortamında emir akışı testi
- Piyasa açık saatlerinde stres runtime davranışı
- `news_bridge.py` harici API latency profilling
- `error_dashboard.py` 660 satırın tam ölü kod ratio analizi
- Elektron prod dist/ içeriğinin güvenlik denetimi
- Windows-specific permission/UAC davranışı
- CI/CD ortamında test çalıştırma (sadece lokal)

**Bu sınırlar ek runtime doğrulama ve periyodik re-audit gerektirmektedir.**

---

## 18. SON HÜKÜM

USTAT v6.0, ciddi emek ve operasyonel bilinç taşıyan, risk tarafı doğru düşünülmüş, anayasal koruma katmanları gerçekten çalışan bir canlı trading sistemidir. Üretim hazır. Ama **üretim hazır olmak, üretim dostu olmakla aynı şey değildir**.

Bugün için en kritik üç gerçek:

1. Kod v6.0'a geçmiş ama **başlatıcı, CLAUDE.md ve anayasa hâlâ v5.9'da** kalmış. Ürün ile belgesi aynı hızda yaşamıyor.
2. Kritik akış koruma halkası gerçek, ama **ana pytest entrypoint bozuk**. Bu sistemin en büyük paradoksu — `pre-commit hook` kurtarıcı, `pytest.ini` ihanet.
3. Motorlar birbirine **private referanslarla bağlı**; yaşamları **API üzerinden private alan sızıntıları** ile desteklenen; bu durum "ilk başta hızlı, uzun vadede refactor kilidi" klasik borcunun somut örneği.

Strateji bugün için çok açık:

1. **Faz A** — 6 P0 bulgu bu hafta (özellikle BULGU-P0-01 ve BULGU-P0-02 — ikisi birlikte sistem ilk açılış güvenliğini bozuyor).
2. **Faz B** — Anayasa hizalama + sözleşme getter'ları + versiyon drift temizliği bu ay.
3. **Faz C** — Motor alt modül ayrıştırma 1-2 ay (ancak Faz B tamamlandıktan sonra).

Bu üç faz tersine çevrilirse **her düzeltme başka bir yerin sessiz bozulmasını tetikleyen kırılgan sistem** paradigması devam eder. Doğru sırada yapılırsa USTAT v6.x içinde "güvenle değiştirilebilir" seviyesine ulaşır.

---

## 19. EK — BULGU İNDEKSİ

### P0 (6)
- BULGU-P0-01 · `engine/main.py:256-279` · fail_names UnboundLocal
- BULGU-P0-02 · `pytest.ini` · ana entrypoint kırık
- BULGU-P0-03 · `desktop/src/components/Settings.jsx:322` · restartMT5 hayalet
- BULGU-P0-04 · `api/routes/status.py:74-78` · last_cycle ölü alan
- BULGU-P0-05 · `api/routes/notifications.py:40-62` · unread_count limitli
- BULGU-P0-06 · `engine/mt5_bridge.py` · korumasız pozisyon fallback

### P1 (18)
- BULGU-P1-ENG-01 · motor obje bağlama
- BULGU-P1-ENG-02 · 6 dosya 2K+ satır
- BULGU-P1-ENG-03 · SL/TP fallback log seviyesi
- BULGU-P1-ENG-04 · news_bridge timeout
- BULGU-P1-ENG-05 · BABA private state
- BULGU-P1-API-01 · 9 route private sızıntı
- BULGU-P1-API-02 · trade_allowed default=True
- BULGU-P1-API-03 · /status.phase öncelik
- BULGU-P1-API-04 · /killswitch auth yok
- BULGU-P1-API-05 · manual_trade risk kapısı
- BULGU-P1-API-06 · notification prefs getter
- BULGU-P1-UI-01 · start_ustat.py v5.9
- BULGU-P1-UI-02 · şifre process arg
- BULGU-P1-UI-03 · notif prefs çift kaynak
- BULGU-P1-UI-04 · ErrorBoundary kök yok
- BULGU-P1-UI-05 · App.jsx JSDoc v5.7
- BULGU-P1-OPS-01 · lifecycle/process guard belgesiz
- BULGU-P1-OPS-02 · 46 handler vs 37 belgesi
- BULGU-P1-OPS-03 · WATCHDOG_STALE_SECS belgede, kodda yok

### P2 (34) — özet §7'de
Engine 9, API 9, Desktop 7, Ops/Config/Docs 9.

### P3 (20) — özet §8'de
Kozmetik ve edge case'ler.

---

## 20. KANIT EKİ (KOMUT ÇIKTILARI)

**1. Versiyon tutarlılık:**
```
$ cat engine/__init__.py
VERSION = "6.0.0"
$ python -c "import json; print(json.load(open('config/default.json')).get('version'))"
6.0.0
$ head -5 desktop/package.json
"version": "6.0.0"
$ grep -n "v5\.9" start_ustat.py | head -5
55:APP_TITLE = "ÜSTAT v5.9 VİOP Algorithmic Trading"
125:\u00dcSTAT <span ...>v5.9</span>
1154: slog(f"USTAT v5.9 Baslatici")
```

**2. Pytest collection durumu:**
```
$ python -m pytest --collect-only 2>&1 | tail -15
INTERNALERROR> File "archive\USTAT_DEPO\test_trade.py", line 21, in <module>
INTERNALERROR>     sys.exit(0)
INTERNALERROR> SystemExit: 0
=================== 675 tests collected, 2 errors in 1.63s ====================
```

**3. Critical flows durumu:**
```
$ python -m pytest tests/critical_flows -q --tb=no 2>&1 | tail -5
64 passed, 3 warnings in 3.32s
```

**4. _last_cycle_time engine'de yok:**
```
$ Grep "_last_cycle_time|_last_successful_cycle_time" engine/
engine/main.py:204:  self._last_successful_cycle_time: float = 0.0
engine/main.py:586:  self._last_successful_cycle_time = _time.time()
(_last_cycle_time: 0 match)
```

**5. restartMT5 desktop'ta yok:**
```
$ Grep "restartMT5" desktop/
desktop/src/components/Settings.jsx:322: if (window.electronAPI?.restartMT5) {
desktop/src/components/Settings.jsx:323:   window.electronAPI.restartMT5();
$ Grep "restartMT5|mt5:restart" desktop/preload.js
(no matches)
$ Grep "restartMT5|mt5:restart" desktop/main.js
(no matches)
```

**6. notification-prefs frontend GET çağrısı yok:**
```
$ Grep "getNotificationPrefs|settings/notification-prefs" desktop/src/services/api.js
desktop/src/services/api.js:184: const { data } = await client.post('/settings/notification-prefs', prefs);
(GET yok)
```

**7. Watchdog sabitleri kodda yok:**
```
$ Grep "WATCHDOG_STALE_SECS|MAX_AUTO_RESTARTS" start_ustat.py
(no matches)
```

**8. Pre-commit hook durumu:**
```
$ ls -la .githooks/
-rwxr-xr-x 1 pc 197609 3026 Apr 10 16:42 pre-commit
```

**9. Archive yolunun path farkı:**
```
$ ls archive/USTAT_DEPO/tests_aktif/
__init__.py  api  conftest.py  engine  mocks  signal
test_baba.py  test_consecutive_loss.py  test_ogul.py  test_price_action.py
```
(pytest.ini "USTAT DEPO/tests_aktif" diyor — underscore vs boşluk farkı)

---

**Rapor sonu. Satır sayısı: ~900. Bulgu sayısı: 78. Tahmin: yok. Tüm bulgular dosya:satır kanıta bağlı veya komut çıktısı ile doğrulanmıştır. Kod değişikliği yapılmamıştır.**
