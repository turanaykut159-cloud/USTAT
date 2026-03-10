# USTAT v5.3 — Sürdürülebilirlik ve Performans Koruma Nihai Raporu

**Rapor türü:** Birleşik strateji ve uygulama yol haritası  
**Tarih:** 2026-03-10  
**Kapsam:** MT5 ile entegre USTAT algoritmik işlem platformunun kurumsal seviyede güvenilir, izlenebilir, bakım yapılabilir ve kontrollü geliştirilebilir hale getirilmesi.  
**Referanslar:** USTAT_HANDOVER (as-built), FAILURE_MATRIX, CYCLE_PHASES_TABLE, KNOWN_ISSUES, ROADMAP_GAPS, CODEMAP, STATE_OWNERSHIP.

---

## 1. Amaç

Bu raporun amacı, **sistemi sıfırdan yeniden yazmak yerine**, mevcut çalışan çekirdeği **kurumsal seviye yönetim, izleme, test ve değişiklik kontrolü** ile güçlendirmektir.

Hedefler:

- Uzun vadede **güvenilir** ve **hızlı** çalışma  
- **Bakım yapılabilir** ve **kontrollü** geliştirme  
- Hata kaynağının **dakikalar içinde** bulunması  
- Performansın **sayısal hedeflerle** korunması  
- Yeni özelliklerin **replay ve senaryo testinden geçerek** canlıya alınması  

Bu belge hem stratejik öncelikleri hem de operasyonel araçları (teşhis rehberi, runbook, mevcut doküman referansları) tek yerde toplar.

---

## 2. Mevcut durumdan çıkan ana gerçekler

As-built yapıya göre sistem çalışıyor; ancak sürdürülebilirlik açısından şu kırılgan noktalar vardır:

| Gerçek | Açıklama |
|--------|----------|
| **Engine tek çekirdek, 10 sn cycle** | Deterministik çalışma iyi bir temel; cycle fazları CYCLE_PHASES_TABLE ile dokümante (USTAT_HANDOVER/06_engine_core). |
| **MT5 / DB halt** | MT5 reconnect 3x başarısız veya art arda 3 DB hatası → engine durur. Açık pozisyonlar MT5’te kalır; toparlanma _restore_state ve yeniden başlatma (FAILURE_MATRIX). |
| **Event bus sınırsız** | _pending listesi sınırsız büyüyebilir; bellek artışı ve sessiz kayıp riski (KNOWN_ISSUES, ROADMAP_GAPS). |
| **Correlation id yok** | Bir trade’i log’da baştan sona takip eden resmi ID yok; kök neden analizi uzun sürer. |
| **OTP akışı** | UI otomasyonu (SendMessageW); admin yetkisi ve pencere odağına bağımlı; broker arayüz değişince kırılabilir. |
| **Vite dev riski** | Üretimde yanlışlıkla Vite dev kullanımı 5173 bağımlılığı ve kararsızlık riski. |
| **SQLite** | Tek dosya, tek yazıcı; WAL ile iyileşir ama yüksek eşzamanlılık sınırlı (ROADMAP_GAPS). |
| **Tek doğruluk kaynağı** | Açık pozisyonların tek doğruluk kaynağı MT5; uygulama içi state ile broker state’inin sürekli doğrulanması gerekir. |

Bu nedenle öncelik **yeni özellik eklemek değil**, sistemi **ölçülebilir ve izlenebilir** hale getirmektir.

---

## 3. Öncelikli risk alanları

| Alan | Mevcut durum | Etki | Öncelik | Referans (mevcut doküman) |
|------|--------------|------|---------|---------------------------|
| İz sürülebilirlik | Correlation id yok | Hata kaynağı geç bulunur | Kritik | KNOWN_ISSUES, 18_logging_observability |
| Olay kuyruğu | Event bus sınırsız _pending | Bellek artışı, sessiz kayıp riski | Kritik | event_bus.py, ROADMAP_GAPS |
| MT5 bağımlılığı | Reconnect başarısızsa engine halt | Canlı işlem yönetimi kesilir | Kritik | FAILURE_MATRIX, MT5_RECONNECT_LOGIC |
| OTP akışı | UI odağına ve admin haklarına bağılı | Giriş kırılabilir | Yüksek | MT5_LOGIN_OTP_FLOW, KNOWN_ISSUES |
| Veri tabanı | SQLite tek yazıcı, 3 hata sonrası stop | Performans ve dayanıklılık riski | Yüksek | database.py, BACKUP_RESTORE, WRITE_PATHS |
| Yayın disiplini | Dev/prod ayrımı sert değil | Üretim kararlılığı düşer | Yüksek | start_ustat.py, Vite, RUNTIME_GENERATED_FILES |
| Test tekrar üretimi | Replay ve senaryo laboratuvarı yok | Hatalar güvenle düzeltilemez | Yüksek | TEST_STRATEGY, ROADMAP_GAPS |
| Konfigürasyon yönetimi | Kod sabitleri ve config dağınık | Davranış kontrolü zorlaşır | Orta | config/default.json, engine/config.py |

---

## 4. Temel sorulara pratik yanıtlar (operasyonel referans)

Bu bölüm, günlük operasyon ve teşhis sırasında “nereye bakılır?” sorusunu yanıtlar.

### 4.1 Kod tabanı nasıl yönetilir?

- **Tek doğruluk kaynağı:** USTAT_HANDOVER — CODEMAP, KEY_FILES_LIST, MAIN_LOOP, modül özetleri. Değişiklik yapılan modülün ilgili .md dosyası aynı commit’te güncellenmeli.
- **Modül sınırları:** STATE_OWNERSHIP.md, CODEMAP bağımlılık grafiği (Engine → BABA → OĞUL → H-Engine → ÜSTAT). Cross-modül değişiklikler tasarım notu ile dokümante edilmeli.
- **Değişiklik kontrolü:** Feature/bugfix branch + PR; PR’da “etkilenen modüller” ve “handover güncellemesi gerekli mi?” zorunlu. Kritik yol (BABA, OĞUL, MT5Bridge, database) için code review.
- **Sürüm:** VERSION_AND_ENV.md, COMMIT_HASH; her release’te güncellenmeli.

### 4.2 Hatalar nasıl hızlı tespit ve çözülür?

- **MT5:** Heartbeat (terminal_info); 3x reconnect sonrası halt. Toparlanma: yeniden başlatma + _restore_state. Log: ENGINE_STOP, MT5_RECONNECT.
- **DB:** 3 ardışık _DBError → engine stop. Toparlanma: restart; gerekirse yedekten geri (BACKUP_RESTORE). Log: SYSTEM_STOP.
- **Cycle:** Exception → cycle_error event; hangi aşama health.record_cycle ve stack trace ile. Uzun cycle → elapsed > CYCLE_INTERVAL uyarı; darboğaz CycleTimings ile (CYCLE_PHASES_TABLE).
- **Hızlandırıcı:** Her senaryo için **runbook**; “şu log/ekran görünüyorsa → şu adımlar”. Ref: FAILURE_MATRIX.

### 4.3 Sorun kaynağı nasıl hızlı bulunur?

- **Correlation ID (hedef):** run_id, cycle_id, signal_id, order_intent_id, incident_id zinciri + cycle_journal, signal_journal, order_journal (Bölüm 5’te detay).
- **Şu an:** Yapısal log (phase, module, ticket, symbol) + **Teşhis Rehberi** (senaryo → log anahtar kelimeleri → runbook referansı) + CycleTimings (/api/health veya health.record_cycle).

### 4.4 Çökme/hatada analiz nereden yapılır?

1. **Semptomu tespit et** (UI, API, WS).  
2. **FAILURE_MATRIX** ve **Teşhis Rehberi**’nde senaryoyu eşleştir.  
3. **Log:** engine/logger.py (Loguru), ustat_YYYY-MM-DD.log; ENGINE_STOP, CYCLE_ERROR, MT5_RECONNECT, exception stack ara.  
4. **Başlatma:** api.pid, startup.log; RUNTIME_GENERATED_FILES.md.  
5. **Runbook** adımlarını uygula.  
6. Gerekirse **DB** (trades.db): açık pozisyonlar, risk_snapshots, app_state; BACKUP_RESTORE, WRITE_PATHS.

### 4.5 Performans nasıl korunur?

- **Bütçe (hedef):** Ortalama cycle <3 sn, p95 <7 sn; 10 sn aşımı alarm (Bölüm 5.3).  
- **Faz ölçümü:** CYCLE_PHASES_TABLE’daki aşamalar (heartbeat, veri güncelleme, BABA, risk, Top5, OĞUL, hibrit, manuel sync, raporlama, DB). Bu süreler log ve metriğe yazılmalı.  
- **Baseline:** BASELINE_PERFORMANCE.md; boşta ve 15 kontrat cycle için CPU/RAM ve cycle süreleri; büyük değişiklik öncesi/sonrası karşılaştırma.

### 4.6 Teknoloji uyumu nasıl sürdürülür?

- DEPENDENCY_MATRIX, VERSION_AND_ENV periyodik (örn. çeyreklik) güncelleme; Upgrade Checklist.  
- MT5/Broker değişikliği: MT5_BRIDGE_OVERVIEW, MT5_LOGIN_OTP_FLOW gözden geçirme; gerekirse mock test.  
- SQLite: WAL, backup, retention (RETENTION_AND_CLEANUP); ileride PostgreSQL kararı için metrik toplama (Bölüm 5.5).

---

## 5. Yapılması gereken ana işler (detaylı)

### 5.1 İzlenebilirlik omurgası kurulmalı

**Amaç:** Log artırmak değil, **karar zinciri** oluşturmak.

- **Kimlikler:** Her uygulama açılışına `run_id`, her cycle’a `cycle_id`, her sinyale `signal_id`, her emir niyetine `order_intent_id`, her olaya `incident_id`. Bu kimlikler log, DB kaydı, WebSocket olayı ve trade kaydında birlikte taşınmalı.
- **Zincir:** Hangi cycle → hangi rejim → risk kararı → neden emir → MT5 retcode → ticket → kapanış. Tek yerde izlenebilir olmalı.
- **Üç yeni günlük tablosu:**
  - **cycle_journal:** Her cycle’ın karar özeti.
  - **signal_journal:** Sinyalin neden üretildiği veya üretilmediği.
  - **order_journal:** Broker’a gönderilen niyet, sonuç ve süre.
- **Operasyonel tamamlayıcı (ilk 30 gün):** **Teşhis Rehberi** dokümanı: Senaryo → aranacak log anahtar kelimeleri (FAILURE_MATRIX’teki Log sütunu) → ilgili runbook referansı. Böylece correlation tam devreye girmeden bile “nerede?” sorusu hızla yanıtlanır.

**Referans:** LOGGING_STRATEGY, 18_logging_observability.

---

### 5.2 Hata tespiti alarm sistemine bağlanmalı

Log’a düşmesi yetmez; **kritik durumlarda alarm** üretilmeli.

**Otomatik kritik alarm üretilecek durumlar:**

- Son başarılı cycle üzerinden 20 saniyeden fazla geçmiş olması  
- MT5 reconnect denemelerinin başarısız olması  
- DB hata sayacının artması  
- Cycle süresinin 10 saniyeyi aşması  
- Event bus kuyruğunun eşik değeri geçmesi  
- MT5 açık pozisyonları ile engine active state’inin uyuşmaması  
- Risk snapshot güncellenmemesi  
- EOD kapanışının eksik kalması  
- L3 kapanış denemelerinde açık ticket kalması  

**Incident paketi:** Alarm çıktığında sadece mesaj değil, otomatik “incident paketi” üretilmeli: son cycle’lar, son kritik loglar, MT5 durumu, config özeti, açık pozisyonlar, commit hash.

**Operasyonel tamamlayıcı:** FAILURE_MATRIX’teki her senaryo için **tek sayfalık runbook** (RUNBOOK_MT5_KOPMA, RUNBOOK_DB_HATA, RUNBOOK_CYCLE_ERROR, RUNBOOK_UZUN_CYCLE, RUNBOOK_API_ACILMAZ, RUNBOOK_STARTUP, RUNBOOK_SAFE_QUIT); “aranacak log satırları” ve “beklenen çıktı” örnekleri. STARTUP_SEQUENCE ve SHUTDOWN_SEQUENCE ile eşleşmeli.

---

### 5.3 Performans bütçesi tanımlanmalı

Soyut değil, **sayısal hedefler** konmalı.

- Toplam cycle süresi **ortalamada 3 saniyenin altında**.  
- **95. yüzdelik** cycle süresi **7 saniyenin altında**.  
- **10 saniyeyi aşan her cycle** alarm sebebi.  
- MT5 heartbeat ve hesap okuma süresi izlenebilir.  
- DB yazma gecikmeleri ayrı ölçülür.  
- WebSocket yayın süresi ve bağlantı sayısı izlenir.  

**Faz bazlı ölçüm:** CYCLE_PHASES_TABLE ile uyumlu: heartbeat, veri güncelleme, BABA, risk kontrolü, Top5, OĞUL, hibrit, manuel sync, raporlama, DB yazımı. Bu süreler hem log’a hem metriğe (örn. /api/health veya ayrı metrik endpoint) yazılmalı.

**Mevcut altyapı:** health.record_cycle(CycleTimings(...)); BASELINE_PERFORMANCE.md güncellenmeli.

---

### 5.4 DataPipeline verimli hale getirilmeli

Her 10 saniyede tüm semboller ve çoklu timeframe için tam veri çekimi maliyetlidir.

- **İlk açılış:** Tam yükleme.  
- **Sonraki cycle’lar:** Sadece **artımlı** veri (her timeframe için son 2–3 bar, son tick aralığı).  
- **İndikatörler:** Tüm geçmiş yerine **kayan pencere** ile güncelleme.  
- **Seans dışı / deaktivasyon:** Bu sembollere daha seyrek sorgu.  

Bu tek başına cycle süresini ve DB yazım yükünü ciddi şekilde düşürür.

**Referans:** engine/data_pipeline.py, 07_data_pipeline.

---

### 5.5 Veri tabanı sertleştirilmeli

SQLite hemen değiştirilmek zorunda değildir; **kurumsal kullanım için sertleştirme** yapılmalı.

- Yazım yolu **tek bir kontrollü writer katmanında** toplanmalı.  
- Yüksek frekanslı event yazımları **batch** mantığına alınmalı.  
- Düzenli **integrity_check** çalıştırılmalı.  
- **WAL checkpoint** politikası tanımlanmalı.  
- **Otomatik yedek doğrulaması** eklenmeli.  
- Retention ve cleanup sadece zaman bazlı değil **boyut bazlı** da izlenmeli.  

**Orta vadede toplanacak metrikler:** lock bekleme süresi, yazım gecikmesi, DB boyut büyüme hızı, günlük kayıt sayısı, kurtarma sıklığı. Bu metrikler yüksek çıkarsa PostgreSQL geçişi planlanmalı; **ölçüm olmadan geçiş yapılmamalı**.

**Referans:** database.py, BACKUP_RESTORE, RETENTION_AND_CLEANUP, WRITE_PATHS, SQLITE_SETTINGS.

---

### 5.6 Event bus güvenli hale getirilmeli

_pending listesinin sınırsız olması üretimde kabul edilmemelidir.

- **Bounded queue:** Kuyruk için üst sınır.  
- **Politika:** En eskiyi at veya en yeniyi reddet; **drop sayacı** tutulmalı.  
- **Alarm:** Eşik aşımı veya drop sayacı artışında alarm.  
- **Ölçüm:** Event üretim hızı ile drain hızı ayrı ayrı ölçülmeli.  

**Referans:** engine/event_bus.py, 15_websocket_eventbus.

---

### 5.7 Üretim çalışma modeli düzeltilmeli

- **Mevcut risk:** Canlı işlem yapan backend ile masaüstü arayüz aynı yaşam döngüsüne bağlı; Electron kapanınca API taskkill operasyonel risk oluşturur.  
- **Hedef model:** Trading backend **ayrı yönetilen bir servis**; UI sadece bağlanan istemci. Pencere kapatıldığında işlem motoru durmamalı; “motoru durdur” ayrı ve bilinçli işlem olmalı.  
- **Vite:** Üretim ortamında **Vite dev server kullanımı tamamen yasaklanmalı**; canlıda yalnızca **build edilmiş** frontend çalışmalı.

**Referans:** start_ustat.py, desktop/main.js, PROCESS_MODEL, RUNTIME_GENERATED_FILES.

---

### 5.8 MT5 hata yönetimi güçlendirilmeli

- **Retcode grupları:** Geçici bağlantı, fiyat kayması, sembol erişim, emir reddi, yetki, timeout. Her grup için ayrı tepki tanımlanmalı.  
- **order_journal:** Her broker hatası standart formatta order_journal’a yazılmalı.  
- **Safe mode:** Engine “tam durma” yerine “safe mode”: yeni emirler durdurulur, süreç yaşamaya devam eder; tekrar bağlanma ve incident üretme sürer.  

**Referans:** engine/mt5_bridge.py, MT5_RECONNECT_LOGIC, MT5_ORDER_MAPPING, 05_mt5_integration.

---

### 5.9 Test ve tekrar üretim laboratuvarı kurulmalı

- **Replay altyapısı:** Tick, bar, MT5 yanıtı ve açık pozisyon state’i kayıt ve yeniden oynatma.  
- **Otomatik senaryo testleri:** MT5 kopması, reject emir, EOD kapanışı, L3 forced close, restart sonrası açık pozisyon restore, hibrit transfer ve trailing, manual position tespiti, DB lock/geçici hata, WebSocket reconnect, closure retry ve history sync.  
- **Shadow mode:** Yeni özellikler önce shadow’da çalışmalı; canlı veriyle karar üretmeli ama emir göndermemeli. Eski davranışla fark ölçülmeden canlıya alınmamalı.  
- **Kısa vadede:** Unit test iskeleti (engine/utils, model sınıfları), API smoke testleri (/api/health, /api/status, /api/risk); TEST_STRATEGY ile uyumlu.

**Referans:** TEST_STRATEGY, 20_tests, ROADMAP_GAPS.

---

### 5.10 Kod yönetimi kurumsallaştırılmalı

- **Modül sahipliği:** BABA, OĞUL, MT5Bridge, DataPipeline, H-Engine, API, Electron için sorumlu alanlar net olmalı (STATE_OWNERSHIP, CODEMAP ile uyumlu).  
- **Karar kaydı:** Her davranış değişikliği için karar kaydı tutulmalı.  
- **Disiplin:** Kod standartları, branch stratejisi, yayın notu, geriye dönüş planı, config değişiklik onayı zorunlu.  
- **Sert kurallar:** Config değişikliği **versiyonsuz** yapılamaz; canlı strateji mantığı **replay ve senaryo testinden geçmeden** yayınlanamaz.  
- **PR:** Etkilenen modüller, handover güncellemesi, test edilen senaryolar; kritik yol için merge öncesi kontrol listesi (CONTRIBUTING.md veya MERGE_CHECKLIST.md).

**Referans:** CODEMAP, KEY_FILES_LIST, VERSION_AND_ENV, DELIVERY_INDEX.

---

### 5.11 Teknik borç temizliği planlı yapılmalı

- start_ustat.vbs ve start_ustat.py içindeki **hardcoded path’ler** kaldırılmalı.  
- **Admin yetkisi:** Tüm uygulamaya değil, yalnızca gerekli helper sürece verilmeli.  
- **OTP:** Manuel fallback zorunlu olmalı.  
- **Sabitler:** Kod içinde dağınık sabitler tek konfigürasyon kaynağında birleştirilmeli.  
- **Bağımlılık:** Çapraz referans azaltılmalı; hedef mikroservis değil, **sınırları net modüler monolit**.  

Bu çalışma tek seferde değil, **modül modül** yapılmalı.

**Referans:** KNOWN_ISSUES, TECH_DEBT, 17_security.

---

## 6. Operasyonel araçlar (hemen kullanılabilir)

Aşağıdakiler ilk 30 gün içinde oluşturulup kullanıma alınmalı; böylece izlenebilirlik omurgası tam devreye girmeden bile teşhis ve toparlanma hızlanır.

| Araç | İçerik | Konum / referans |
|------|--------|-------------------|
| **Teşhis Rehberi** | Senaryo → aranacak log anahtar kelimeleri (ENGINE_STOP, CYCLE_ERROR, MT5_RECONNECT, SYSTEM_STOP vb.) → ilgili runbook | docs/ veya USTAT_HANDOVER/19_failure_recovery/ TEŞHIS_REHBERI.md |
| **Runbook’lar** | FAILURE_MATRIX senaryolarına tek sayfa: semptom, log örnekleri, adımlar, beklenen çıktı | Aynı klasör RUNBOOK_*.md |
| **Analiz sırası** | (1) Semptom (2) FAILURE_MATRIX + Teşhis Rehberi (3) Log arama (4) Runbook (5) DB/state gerekirse | Bu rapor Bölüm 4.4 |
| **Mevcut dokümanlar** | CODEMAP, KEY_FILES_LIST, FAILURE_MATRIX, CYCLE_PHASES_TABLE, RUNTIME_GENERATED_FILES, BACKUP_RESTORE, STARTUP_SEQUENCE, SHUTDOWN_SEQUENCE | USTAT_HANDOVER |

---

## 7. Uygulama planı

| Dönem | Yapılacak ana iş | Çıktı |
|-------|------------------|--------|
| **İlk 30 gün** | Correlation zinciri (run_id, cycle_id, signal_id, order_intent_id, incident_id), cycle/signal/order journal tasarımı ve uygulaması; JSON/yapısal log; Teşhis Rehberi ve runbook’lar; kritik alarm (en az: cycle >10 sn, MT5 reconnect fail, DB hata sayacı); prod build zorunluluğu dokümante | Hızlı görünürlük, operatör runbook ile toparlanma |
| **30–60 gün** | Event bus sınırı (bounded queue, drop sayacı, alarm); incident paketi; health dashboard / cycle faz süreleri; MT5 hata sınıfları ve order_journal broker hata kaydı | Hızlı hata analizi |
| **60–90 gün** | Replay laboratuvarı iskeleti, senaryo testleri (en az 5 senaryo), shadow mode altyapısı; config versiyonlama; unit + API smoke testleri | Güvenli değişiklik |
| **90–180 gün** | Backend servisleşmesi (UI’dan bağımsız trading süreci); DB sertleştirme (writer katmanı, batch, integrity_check, WAL politikası, yedek doğrulama); DataPipeline artımlı veri; performans bütçesi ölçümü ve alarm entegrasyonu | Ölçeklenebilir operasyon |
| **180 gün sonrası** | PostgreSQL kararı (metriklere göre); broker adapter soyutlama; ileri otomasyon | Stratejik evrim |

---

## 8. Başarı kriterleri

Bu dönüşümün tamamlandığı aşağıdaki sonuçlarla anlaşılır:

1. Her trade **tam correlation zinciri** (run_id → cycle_id → signal_id → order_intent_id) ile izlenebilir.  
2. Bir incident için **ilk teşhis 5 dakika** içinde yapılabiliyor (Teşhis Rehberi + runbook).  
3. **Kök neden analizi** 30 dakika içinde veriyle (log + journal) desteklenebiliyor.  
4. Cycle performansı tanımlı eşiklerin dışına çıktığında **otomatik alarm** oluşuyor.  
5. Yeni sürüm canlıya çıkmadan önce **replay ve senaryo testlerinden** geçiyor.  
6. **UI kapanması** trading backend’i durdurmuyor (backend servis modeli).  
7. **Üretimde dev akış** (Vite dev) kullanılmıyor.  
8. Sessiz **event kaybı** veya kuyruk büyümesi **sayaçsız/alarmsız** bırakılmıyor (bounded queue + alarm).  
9. **Config değişikliği** versiyonsuz yapılamıyor; canlı strateji **replay/senaryo testinden geçmeden** yayınlanmıyor.

---

## 9. Özet tablo: Soru → Mekanizma

| Soru | Kurulacak / güçlendirilecek mekanizma |
|------|----------------------------------------|
| Kod tabanı nasıl yönetilir? | CODEMAP/KEY_FILES + modül sahipliği + PR + handover güncellemesi + karar kaydı |
| Hatalar nasıl hızlı tespit/çözülür? | FAILURE_MATRIX + runbook’lar + alarm + incident paketi + health/cycle metrikleri |
| Sorun kaynağı nasıl hızlı bulunur? | run_id/cycle_id/signal_id/order_intent_id + journal tabloları + Teşhis Rehberi + yapısal log |
| Çökme/hatada analiz nereden? | Log + FAILURE_MATRIX + Teşhis Rehberi + runbook + DB/state + RUNTIME_GENERATED_FILES |
| Performans nasıl korunur? | Performans bütçesi (avg <3 sn, p95 <7 sn) + faz ölçümü + alarm + baseline karşılaştırma |
| Teknoloji uyumu nasıl sürdürülür? | DEPENDENCY_MATRIX + VERSION_AND_ENV + Upgrade Checklist + ROADMAP_GAPS + DB metrikleri |

---

## 10. Sonuç

Bu platformun sürdürülebilirliğini korumanın yolu **daha fazla karmaşık kod eklemek değil**, sistemi **yönetilebilir** hale getirmektir.

**Öncelik sırası:** (1) Görünürlük (correlation zinciri + journal + Teşhis Rehberi + runbook + alarm), (2) Hata analizi (incident paketi, MT5 hata sınıfları, event bus sınırı), (3) Performans bütçesi ve faz ölçümü, (4) Güvenli değişiklik altyapısı (replay, senaryo testi, shadow mode, config versiyonlama).

**İlk kritik adım:** run_id / cycle_id / order_intent_id zinciri ve cycle_journal, signal_journal, order_journal ile karar günlüğünü devreye almak; paralelde Teşhis Rehberi ve runbook’ları yazmak. Bu adım atılmadan sürdürülebilirlik de performans yönetimi de eksik kalır.

Bu nihai rapor, stratejik hedefler ile operasyonel araçları (mevcut USTAT_HANDOVER referansları, FAILURE_MATRIX, runbook, Teşhis Rehberi, analiz sırası) tek belgede birleştirir; hem yönetim hem ekip için tek referans doküman olarak kullanılabilir.
