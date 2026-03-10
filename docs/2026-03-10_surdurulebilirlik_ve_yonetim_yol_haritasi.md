# Algoritmik İşlem Platformu — Sürdürülebilirlik ve Yönetim Yol Haritası

**Rapor türü:** Stratejik yol haritası  
**Tarih:** 2026-03-10  
**Kapsam:** ~40.000 satırlık USTAT kod tabanının kurumsal seviyede yönetilebilir, izlenebilir ve sürdürülebilir hale getirilmesi.  
**Hedef:** Bakımı kolay, hataları hızlı tespit edilebilen, performansı korunabilen ve gelecekteki gelişmelere uyum sağlayabilen profesyonel yazılım yönetim sistemi.

---

## Yönetici Özeti

Bu rapor, platformun **kod yönetimi**, **hata tespiti**, **kaynak analizi**, **performans izleme** ve **sürdürülebilir geliştirme** ihtiyaçlarını karşılayacak bir yol haritası sunar. Öneriler mevcut USTAT mimarisi (engine, API, BABA, OĞUL, H-Engine, MT5, SQLite, Electron) ve USTAT_HANDOVER dokümanlarındaki as-built gerçeklerle uyumludur. Yol haritası dört fazda kurgulanmıştır: **Gözlemlenebilirlik**, **Hata yönetimi ve runbook’lar**, **Test ve değişiklik disiplini**, **Performans ve uyum**.

---

## 1. Temel Sorulara Yanıtlar

### 1.1 Bu büyüklükteki bir kod tabanı nasıl yönetilebilir ve kontrol altında tutulabilir?

| Araç / Mekanizma | Açıklama |
|------------------|----------|
| **Tek doğruluk kaynağı dokümanı** | USTAT_HANDOVER (CODEMAP, KEY_FILES_LIST, MAIN_LOOP, modül özetleri) zaten “nerede ne var” sorusunu yanıtlıyor. Tüm yeni geliştirmelerde bu dokümanlar güncel tutulmalı; değişiklik yapılan modülün ilgili .md dosyası aynı commit’te güncellenmeli. |
| **Modül sınırları ve sahiplik** | STATE_OWNERSHIP.md ve CODEMAP’teki bağımlılık grafiği net: Engine → BABA → OĞUL → H-Engine → ÜSTAT. Değişiklik yaparken “bu modülün sahibi hangi dosya/akış?” sorusu cevaplanmalı; cross-modül değişiklikler tasarım notu ile dokümante edilmeli. |
| **Değişiklik kontrolü** | Feature/bugfix branch + PR; PR açıklamasında “etkilenen modüller” (engine, api, desktop, config) ve “handover güncellemesi gerekli mi?” alanları zorunlu. Kritik yol (BABA, OĞUL, MT5Bridge, database) için en az bir inceleme (code review) kuralı konulmalı. |
| **Sürüm ve ortam** | VERSION_AND_ENV.md tek yerde sürüm ve bağımlılıkları topluyor. Her release’te bu dosya ve ilgili package.json/requirements.txt güncellenmeli; “hangi commit’te ne vardı?” sorusu COMMIT_HASH veya tag ile yanıtlanabilir. |

**Sonuç:** Kod tabanı, **dokümantasyonu güncel tutma**, **modül sınırlarına saygı** ve **değişiklik kontrolü (branch + PR + handover güncellemesi)** ile kontrol altında tutulabilir. Tüm kodu tek tek okumak yerine CODEMAP ve KEY_FILES_LIST ile “nereden başlanır” netleştirilir.

---

### 1.2 Sistem içinde oluşabilecek hatalar en hızlı şekilde nasıl tespit edilip çözülebilir?

| Katman | Tespit mekanizması | Çözüm yönü |
|--------|--------------------|------------|
| **MT5** | Heartbeat (terminal_info); 3x reconnect sonrası engine halt. | FAILURE_MATRIX: Reconnect başarısız → yeniden başlatma + _restore_state. Log: ENGINE_STOP, MT5_RECONNECT. |
| **Veritabanı** | 3 ardışık _DBError → engine stop. | Restart; gerekirse yedekten geri (BACKUP_RESTORE). Log: SYSTEM_STOP. |
| **Cycle** | _run_single_cycle exception → cycle_error event; döngü devam. | Log CYCLE_ERROR; hangi aşamada (DataPipeline, BABA, OĞUL vb.) exception olduğu health.record_cycle ve stack trace ile tespit. |
| **Uzun cycle** | elapsed > CYCLE_INTERVAL → uyarı log. | Hangi fazın uzun sürdüğü CycleTimings (heartbeat_ms, baba_cycle_ms, ogul_signals_ms vb.) ile analiz; darboğaz modüle odaklan. |
| **API/Frontend** | /api/health, WebSocket /ws/live; UI donması veya veri güncel değil. | Health endpoint’te engine_alive, mt5_connected, last_cycle_ts; WS kopması → istemci yeniden bağlanır. |

**Hızlandırıcı:** Tüm hata senaryoları için **runbook** (aşağıda) yazılmalı; “şu log/ekran görünüyorsa → şu adımlar” tek yerde toplanmalı. Böylece hatanın türü tanındığı anda çözüm adımları uygulanabilir.

---

### 1.3 Sorunun kaynağını hızla bulabilecek mekanizmalar nasıl kurulabilir?

| Mekanizma | Durum / Öneri |
|-----------|----------------|
| **Correlation ID** | Şu an **yok** (KNOWN_ISSUES, ROADMAP_GAPS). Bir emir/trade’i log’da baştan sona takip etmek için request/trade bazında benzersiz ID (örn. `correlation_id`) eklenmeli: MT5Bridge emir gönderirken, OĞUL sinyal üretirken, event_bus emit ederken aynı ID loglanmalı. Böylece “bu işlem nerede takıldı?” sorusu log aramasıyla yanıtlanır. |
| **Yapısal log alanları** | Loguru ile seviye ve format var; ek olarak `phase`, `module`, `ticket`, `symbol` gibi alanlar yapısal (JSON veya key=value) yazılırsa filtreleme ve arama kolaylaşır. |
| **Health / CycleTimings** | health.record_cycle ile cycle süreleri zaten toplanıyor. Bu veriler /api/health veya ayrı bir metrik endpoint’ten okunabilir; “yavaşlık hangi aşamada?” sorusu cycle fazlarına göre cevaplanır. |
| **Hata matrisi ve log eşlemesi** | FAILURE_MATRIX.md senaryo → tespit → toparlanma → log anahtar kelimelerini veriyor. Her senaryo için “aranacak log satırları” (örn. ENGINE_STOP, CYCLE_ERROR, MT5_RECONNECT) bir “Teşhis Rehberi” dokümanında toplanabilir; operatör log’da bu anahtar kelimeleri arayarak senaryoyu ve kaynağı bulur. |

**Özet:** Correlation ID + yapısal log + CycleTimings + “Teşhis Rehberi” (senaryo → log anahtarları → runbook) ile sorun kaynağı tek tek kod okumadan daraltılabilir.

---

### 1.4 Sistem çöktüğünde veya hatalı davranış gösterdiğinde analiz nereden ve nasıl yapılacak?

| Kaynak | Kullanım |
|--------|----------|
| **Log dosyaları** | engine/logger.py (Loguru) rotasyon ve retention ile; ustat_YYYY-MM-DD.log. Hata anında tarih/saat ile ilgili log dosyası açılır; ENGINE_STOP, CYCLE_ERROR, exception stack aranır. |
| **api.pid / startup.log** | Başlatma sırası ve port temizliği; API açılmazsa start_ustat.py ve startup.log incelenir. |
| **RUNTIME_GENERATED_FILES.md** | Hangi dosyanın nerede olduğu ve ne anlama geldiği burada; analiz öncesi “nerede ne var” referansı. |
| **FAILURE_MATRIX + Teşhis Rehberi** | Görünen semptom (ekran, log satırı) → senaryo → toparlanma adımları. Örnek: “MT5 veri güncel değil” → MT5 kapanması/reconnect başarısız → runbook “MT5 yeniden başlatma ve uygulama restart”. |
| **DB (trades.db)** | Açık pozisyonlar, risk_snapshots, app_state, hybrid_positions; “restart öncesi sistem ne durumdaydı?” sorusu için. Gerekirse BACKUP_RESTORE ve WRITE_PATHS ile yedek ve şema kontrolü. |

**Sıra önerisi:** (1) Semptomu tespit et (UI/API/WS), (2) FAILURE_MATRIX ve Teşhis Rehberi’nde eşleştir, (3) İlgili log dosyasında önerilen anahtar kelimeleri ara, (4) Runbook’taki adımları uygula, (5) Gerekirse DB/state dosyalarını incele.

---

### 1.5 Performans korunarak yeni özellikler ve geliştirmeler nasıl entegre edilecek?

| İlke | Uygulama |
|------|----------|
| **Baseline ölçüm** | BASELINE_PERFORMANCE.md’de otomatik ölçüm raporu şu an yok. En azından “boşta” ve “15 kontrat cycle” için CPU/RAM ve cycle toplam/parça süreleri (health.record_cycle) periyodik kaydedilmeli; yeni özellik öncesi/sonrası karşılaştırma yapılabilir. |
| **Cycle süresi hedefi** | 10 sn cycle; tek cycle’ın CYCLE_INTERVAL’ı aşmaması hedeflenir. Yeni kod (özellikle DataPipeline, BABA, OĞUL) merge öncesi “cycle süresini belirgin artırıyor mu?” sorusu test veya canlı ölçümle yanıtlanmalı. |
| **Özellik bayrakları** | Kritik davranış değişiklikleri config veya feature flag ile açılıp kapatılabilir olursa, sorun çıktığında hızlı geri alınabilir. |
| **Modül izolasyonu** | Yeni özellik mümkün olduğunca tek modül/servis sınırında; MAIN_LOOP sırası ve BABA→OĞUL bağımlılığı değiştirilmeden eklenmeli. |

---

### 1.6 Teknoloji ve altyapı değişimlerine uyum nasıl sürdürülebilir?

| Alan | Öneri |
|------|--------|
| **Bağımlılık matrisi** | DEPENDENCY_MATRIX.md (Python/Node/Electron/MT5 sürümleri) periyodik güncellenmeli; yükseltme planı (örn. Python 3.12, yeni MT5 build) ayrı bir “Upgrade Checklist” ile yapılmalı. |
| **MT5 / Broker** | MT5 API değişikliği veya broker arayüz (OTP) değişikliği bilinen risk (KNOWN_ISSUES). Değişiklik duyulduğunda MT5_BRIDGE_OVERVIEW ve MT5_LOGIN_OTP_FLOW gözden geçirilmeli; gerekirse mock ile test. |
| **SQLite sınırları** | ROADMAP_GAPS: Tek yazıcı, tek dosya; ileride yük artarsa migration (PostgreSQL vb.) veya read-replica planı dokümante edilmeli; şimdilik WAL ve backup stratejisi (BACKUP_RESTORE, RETENTION_AND_CLEANUP) uygulanarak sürdürülebilirlik artırılır. |
| **Tek süreç varsayımı** | Dağıtık/çoklu worker yok; bu bilinçli kısıt. Altyapı değişimi (örn. çoklu makine) büyük mimari karar olarak ROADMAP_GAPS’te kalmalı; karar verilene kadar tek makine dokümanları güncel tutulmalı. |

---

## 2. Yol Haritası — Dört Faz

### Faz 1: Gözlemlenebilirlik (Öncelik: Yüksek)

| # | Aksiyon | Çıktı | Süre (tahmini) |
|---|---------|--------|-----------------|
| 1.1 | Correlation ID tasarımı ve uygulaması (emir/trade akışında tek ID) | Kod değişikliği + LOGGING_STRATEGY güncellemesi | 2–3 gün |
| 1.2 | Yapısal log alanları (phase, module, ticket, symbol) eklenmesi | Log formatı ve örnek log dokümanı | 1–2 gün |
| 1.3 | “Teşhis Rehberi” dokümanı: Senaryo → log anahtar kelimeleri → runbook referansı | docs veya USTAT_HANDOVER altında TEŞHIS_REHBERI.md | 1 gün |
| 1.4 | /api/health (veya mevcut health) üzerinden cycle faz sürelerinin istikrarlı sunulması | API ve frontend’de “en yavaş faz” görünürlüğü | 0,5–1 gün |

**Hedef:** Sorun anında “nerede?” sorusu correlation ID ve log anahtar kelimeleriyle hızlı yanıtlanır; cycle yavaşlığı faz bazında görülür.

---

### Faz 2: Hata yönetimi ve runbook’lar (Öncelik: Yüksek)

| # | Aksiyon | Çıktı | Süre (tahmini) |
|---|---------|--------|-----------------|
| 2.1 | FAILURE_MATRIX’teki her senaryo için tek sayfalık runbook | RUNBOOK_MT5_KOPMA, RUNBOOK_DB_HATA, RUNBOOK_CYCLE_ERROR, RUNBOOK_UZUN_CYCLE, RUNBOOK_API_ACILMAZ vb. | 2–3 gün |
| 2.2 | Runbook’larda “aranacak log satırları” ve “beklenen çıktı” örnekleri | Operatörün kopyala-yapıştır yapabileceği komutlar/log örnekleri | 1 gün |
| 2.3 | Başlatma/kapanış sorunları için STARTUP_SEQUENCE ve SHUTDOWN_SEQUENCE ile eşleşen runbook’lar | RUNBOOK_STARTUP, RUNBOOK_SAFE_QUIT | 0,5 gün |

**Hedef:** Çökme veya hatalı davranışta operatör runbook’a giderek adım adım toparlanma yapar; “kim ne yapacak?” belirsizliği kalkar.

---

### Faz 3: Test ve değişiklik disiplini (Öncelik: Orta–Yüksek)

| # | Aksiyon | Çıktı | Süre (tahmini) |
|---|---------|--------|-----------------|
| 3.1 | Unit test iskeleti: engine/utils, model sınıfları, kritik yardımcı fonksiyonlar (TEST_STRATEGY ile uyumlu) | tests/ veya engine/tests/; pytest ile çalışan en az 5–10 test | 2–4 gün |
| 3.2 | API smoke testleri: /api/health, /api/status, /api/risk (MT5 mock veya MT5’siz mod) | integration test script veya pytest | 1–2 gün |
| 3.3 | Değişiklik kontrolü: PR şablonu (etkilenen modüller, handover güncellemesi, test edilen senaryolar) | .github veya repo kökünde PULL_REQUEST_TEMPLATE.md | 0,5 gün |
| 3.4 | Kritik yol için “Merge öncesi kontrol listesi” (BABA, OĞUL, MT5Bridge, database değişikliklerinde) | CONTRIBUTING.md veya docs/MERGE_CHECKLIST.md | 0,5 gün |

**Hedef:** Yeni kod regresyonu azalır; değişiklikler modül ve doküman güncellemesi ile takip edilir.

---

### Faz 4: Performans ve uyum (Öncelik: Orta)

| # | Aksiyon | Çıktı | Süre (tahmini) |
|---|---------|--------|-----------------|
| 4.1 | Baseline ölçüm protokolü: boşta ve 15 kontrat cycle’da CPU/RAM + cycle toplam/parça süreleri | BASELINE_PERFORMANCE.md güncellemesi + ölçüm scripti veya notlar | 1–2 gün |
| 4.2 | Büyük değişiklik öncesi/sonrası karşılaştırma kuralı (dokümante) | PERFORMANCE_CHECKLIST.md veya BASELINE_PERFORMANCE’a ek bölüm | 0,5 gün |
| 4.3 | DEPENDENCY_MATRIX ve VERSION_AND_ENV periyodik güncelleme (örn. çeyreklik) | Takvim maddesi + gerekirse Upgrade Checklist | Sürekli |
| 4.4 | ROADMAP_GAPS’teki SQLite/dağıtık/OTP alternatifi maddelerinin “karar tarihi” veya “ertelenmiş” notu | Doküman güncellemesi | 0,5 gün |

**Hedef:** Performans bilinçli şekilde izlenir; teknoloji ve altyapı değişimleri planlı ilerler.

---

## 3. Özet Tablo: Soru → Mekanizma

| Soru | Kurulacak / Güçlendirilecek Mekanizma |
|------|----------------------------------------|
| Kod tabanı nasıl yönetilir? | CODEMAP/KEY_FILES + modül sınırları + PR + handover güncellemesi |
| Hatalar nasıl hızlı tespit/çözülür? | FAILURE_MATRIX + runbook’lar + health/cycle metrikleri |
| Sorun kaynağı nasıl hızlı bulunur? | Correlation ID + yapısal log + Teşhis Rehberi + CycleTimings |
| Çökme/hatada analiz nereden? | Log dosyaları + FAILURE_MATRIX + Teşhis Rehberi + runbook + DB/state |
| Performans nasıl korunur? | Baseline ölçüm + cycle süresi hedefi + merge öncesi performans kontrolü |
| Teknoloji uyumu nasıl sürdürülür? | DEPENDENCY_MATRIX güncellemesi + Upgrade Checklist + ROADMAP_GAPS takibi |

---

## 4. Sonuç

Bu yol haritası, 40.000 satırlık algoritmik işlem platformunu **kontrollü ve disiplinli** yönetmek için gerekli yapı taşlarını tanımlar:

1. **Gözlemlenebilirlik:** Correlation ID, yapısal log, Teşhis Rehberi ve cycle metrikleri ile “nerede ne oldu?” sorusu kod satırı satırı okunmadan yanıtlanır.
2. **Hata yönetimi:** Runbook’lar ve FAILURE_MATRIX ile her senaryoda tespit ve toparlanma adımları netleşir; analiz tek bir doküman setine (log + Teşhis Rehberi + runbook) dayanır.
3. **Sürdürülebilir geliştirme:** PR + handover güncellemesi + test iskeleti + merge kontrol listesi ile yeni özellikler modül sınırları ve performans hedefleriyle entegre edilir.
4. **Uyum:** Bağımlılık ve sürüm dokümanları periyodik güncellenir; teknoloji ve altyapı değişimleri ROADMAP_GAPS ve Upgrade Checklist ile takip edilir.

Uygulama sırası önerisi: **Faz 1 (Gözlemlenebilirlik)** ve **Faz 2 (Runbook’lar)** önce tamamlanmalı; böylece mevcut sistemde bile hata tespiti ve toparlanma süresi kısalır. Ardından **Faz 3 (Test ve değişiklik disiplini)** ve **Faz 4 (Performans ve uyum)** ile sürdürülebilirlik kalıcı hale getirilir.
