# USTAT v5.3 — Kurumsal Değerlendirme Raporu Doğrulama Analizi

**Rapor türü:** Teknik doğrulama raporu  
**Tarih:** 2026-03-10  
**Konu:** "STAT v5.3 — Doküman ve Ekranlar Birlikte Kurumsal Düzeyde Derin Değerlendirme" metnindeki tespitlerin kod ve dokümanla karşılaştırılarak doğrulanması.  
**Kapsam:** Uygulama yapısı (engine, API, frontend, DB, MT5, BABA, OĞUL, H-Engine, handover) incelendi; kurumsal değerlendirme maddeleri tek tek kontrol edildi. **Hiçbir kod veya uygulama değişikliği yapılmamıştır.**

---

## Yönetici Özeti

- **İncelenen metin:** STAT v5.3 Kurumsal Düzeyde Derin Değerlendirme (yönetici değerlendirmesi, 13 bölüm, puanlama, aksiyon planı).
- **Yöntem:** Kod tabanı (engine, api, desktop, USTAT_HANDOVER) ve ilgili dokümanlar taranarak her iddia için kanıt eşleştirildi.
- **Sonuç:** Kurumsal değerlendirme raporu **büyük ölçüde doğru ve kodla uyumlu**. Tespitlerin tamamına yakını kod, handover ve API/UI ile teyit edildi. Yanlış veya abartılı iddia tespit edilmedi.
- **Öne çıkan doğrulamalar:** BABA→OĞUL sırası, tek engine thread, risk limitleri ve kill-switch, **lot çarpanı çelişkisi** (iki farklı alanın aynı isimle gösterilmesi), correlation id yokluğu, OTP/admin (SendMessageW), MT5/DB halt davranışı, EOD’un hem OĞUL hem hibrit için geçerli olması.
- **Tek netleştirme:** EOD sadece OĞUL’a özel değil; kodda hibrit pozisyonlar da 17:45’te kapatılıyor. Raporun "politika metninin açık yazılması" önerisi yerinde.

---

## Özet Sonuç

Rapor büyük ölçüde **doğru ve kodla uyumlu**. Tespitlerin çoğu kod tabanı, handover dokümanı ve API/UI akışıyla teyit edildi. Birkaç nokta kısmen doğru veya ifade farkı taşıyor; yanlış veya abartılı bulunan iddia yok.

---

## 1. Kanıt Bütünlüğü (Doküman–Ekran Uyumu)

| Rapor iddiası | Doğrulama | Kanıt |
|---------------|-----------|--------|
| Handover soyut tasarım değil, as-built | ✅ Doğru | USTAT_HANDOVER (README_FIRST, SYSTEM_OVERVIEW_AS_BUILT, CODEMAP, MAIN_LOOP, BABA_OVERVIEW, vb.) modül modül "as-built" ve sıra değiştirilemez notlarıyla yazılmış. |
| L2, Top 5, hibrit, manuel, risk limitleri ekranda karşılık buluyor | ✅ Doğru | Risk Yönetimi (kill_switch_level, can_trade, regime), AutoTrading (Top 5, lot çarpanı), HybridTrade (0/3, 500 TL, olay geçmişi), Dashboard (Hibrite Devret) kodda ve API ile bağlı. |
| Modüller arası iş akışı uygulanmış | ✅ Doğru | Manuel → Hibrite Devret (Dashboard), H-Engine limitleri ve olay geçmişi API + HybridTrade.jsx ile sunuluyor. |

**Sonuç:** Bu bölüm iddiaları **geçerli**.

---

## 2. Mimari Olgunluk

| Rapor iddiası | Doğrulama | Kanıt |
|---------------|-----------|--------|
| VBS → Python → FastAPI → Engine → MT5Bridge/DataPipeline/BABA/OĞUL/H-Engine/ÜSTAT → Electron/React | ✅ Doğru | PROCESS_MODEL.md, STARTUP_SEQUENCE.md, main.py (Engine, _main_loop, _run_single_cycle sırası). |
| BABA her zaman OĞUL’dan önce çalışır | ✅ Doğru | engine/main.py satır 14–15 (docstring), 382–421: _run_baba_cycle() → check_risk_limits() → ogul.select_top5() → ogul.process_signals() → h_engine.run_cycle() → ustat.run_cycle(). MAIN_LOOP.md ile aynı. |
| Emir/karar tek ana engine thread’de | ✅ Doğru | Engine tek thread; _main_loop içinde _run_single_cycle, overlap yok (sleep ile 10 sn). |
| MT5 erişimi UI’dan izole; API/WS çoğunlukla DataPipeline cache | ✅ Doğru | API deps (get_mt5, get_engine), live/performance route’ları pipeline/engine’den veri alıyor; UI doğrudan MT5’e gitmiyor. |
| Risk motoru BABA, sinyal OĞUL; hibrit/manuel ayrı sahiplik | ✅ Doğru | BABA → risk_verdict; OĞUL process_signals; HEngine, ManuelMotor ayrı modüller, restore_positions/restore_active_trades ayrı. |
| Restart sonrası MT5’ten state restore | ✅ Doğru | main.py _restore_state(): baba.restore_risk_state(), ogul.restore_active_trades(), h_engine.restore_positions(), manuel_motor.restore_active_trades(). |
| DB tek bağlantı ve lock ile seri | ✅ Doğru | database.py: Lock, _execute ile seri yazım. |
| Windows/tek makine/tek kullanıcı/SQLite/admin/Vite dev | ✅ Doğru | PROCESS_MODEL (VBS runas, uvicorn, Vite, Electron), MACHINE_REQUIREMENTS (admin, OTP), SQLite (DB_PATH), known issues. |

**Sonuç:** Mimari anlatım **kod ve dokümanla uyumlu**.

---

## 3. Operasyon Modeli ve UI

| Rapor iddiası | Doğrulama | Kanıt |
|---------------|-----------|--------|
| Sol menü: Dashboard, Manuel, Hibrit, Otomatik, İşlem Geçmişi, Üstat & Performans, Risk, Sistem Monitor, Ayarlar | ✅ Doğru | SideNav / sayfa yapısı ve PAGE_MAP.md ile uyumlu. |
| Her ekranda alt bölümde Güvenli Kapat ve Kill-Switch | ✅ Doğru | Bileşenlerde sabit aksiyon alanı kullanımı mevcut. |
| System Monitor modül kutuları, ping, döngü süresi, uptime | ✅ Doğru | Monitor bileşeni, health/cycle timing API ile besleniyor. |

**Sonuç:** Operasyonel cockpit ve ekran yapısı **doğru tarif edilmiş**.

---

## 4. Risk Yönetimi ve Lot Çarpanı Çelişkisi

| Rapor iddiası | Doğrulama | Kanıt |
|---------------|-----------|--------|
| BABA önce çalışır; L1/L2/L3, günlük/haftalık/aylık limitler, hard drawdown, cooldown | ✅ Doğru | baba.py, check_risk_limits; api/routes/risk.py limitleri ve kill_switch_level dolduruyor. |
| Risk ekranında bir yerde Lot Çarpanı x0.00, başka yerde x1.00 | ✅ Doğru | RiskManagement.jsx: (1) Rejim kartında "Lot Çarpanı: x{risk.risk_multiplier}" (rejimden, örn. 1.0), (2) Ayrı kart "Lot Çarpanı: x{risk.lot_multiplier}" (verdict’ten; can_trade=False iken 0.0). api/routes/risk.py: risk_multiplier = baba.current_regime.risk_multiplier; lot_multiplier = verdict.lot_multiplier. İki farklı kaynak, aynı isimle iki yerde gösteriliyor → kullanıcıda "hangisi geçerli?" belirsizliği. |
| İşlem izni KAPALI + rejim uygun olsa bile yeni işlem açılmıyor | ✅ Doğru | risk_verdict.can_trade False ise ogul.process_signals(top5, …) boş liste ile çağrılabiliyor; sinyal açılımı engelleniyor. |

**Sonuç:** Risk mimarisi doğru; **lot çarpanı çelişkisi tespiti geçerli ve kodla kanıtlanıyor**.

---

## 5. Manuel ve Hibrit İş Akışı

| Rapor iddiası | Doğrulama | Kanıt |
|---------------|-----------|--------|
| Manuel izleme, hibrite devir, 0/3, günlük 500 TL, olay geçmişi | ✅ Doğru | h_engine (max 3, _config_daily_limit), hybrid_trade API, get_hybrid_events, HybridTrade.jsx. |
| Hibrit olay geçmişinde detaylar ham JSON gibi görünüyor | ⚠️ Kısmen doğru | HybridTrade.jsx: details için JSON.parse ile new_sl, reason, pnl özel formatlanıyor; bunlar yoksa `evt.details` (ham string) gösteriliyor. Yani bazı olaylarda ham JSON görünür; tamamen ham değil ama raporun "daha semantik format gerekir" önerisi yerinde. |

**Sonuç:** Hibrit/manuel akış doğru; olay detayı **kısmen ham**, rapor önerisi mantıklı.

---

## 6. Veri Bütünlüğü, Gözlemlenebilirlik, ÜSTAT Analiz

| Rapor iddiası | Doğrulama | Kanıt |
|---------------|-----------|--------|
| Correlation id yokluğu | ✅ Doğru | Kodda trade/emir izi için correlation_id yok. Sadece check_correlation_limits (pozisyon korelasyonu) var. KNOWN_ISSUES.md ve LOGGING_STRATEGY.md’de "correlation key yok" açık yazıyor. |
| ÜSTAT Analiz sekmesinde Analiz edilen işlem 0, En iyi rejim -, vb. | ✅ Doğru | Performance.jsx brainSummary: totalTrades = trade_categories.by_result toplamı; bestRegime/bestContract = regime_performance ve contract_profiles. API /api/ustat/brain: trades + ustat.get_next_day_analyses() vb. Ertesi gün analizi 09:30+, hafta içi, dün kapanan işlem varsa çalışıyor. Veri yoksa veya henüz çalışmadıysa 0 ve "—" görünmesi normal; raporun "ürün vaat ettiği analiz katmanını henüz olgunlaştırmamış" yorumu veri/akış açısından tutarlı. |
| "Veri eski" uyarısı, MT5 Senkronize Et | ✅ Doğru | Dashboard ve İşlem Geçmişi’nde bu kontroller mevcut. |

**Sonuç:** Correlation eksikliği ve ÜSTAT analiz verisi/ekran davranışı **rapordaki gibi**.

---

## 7. Ticari Gerçeklik (Performans Metrikleri)

| Rapor iddiası | Doğrulama | Kanıt |
|---------------|-----------|--------|
| Performans sayıları (işlem sayısı, net K/Z, Sharpe, profit factor, drawdown) ekrandan okunuyor | ✅ Doğru | Performance API ve trades/equity verisi; frontend’te gösteriliyor. |
| "Strateji ekonomisi zayıf, platform yapısı strateji çıktısından daha olgun" | — Değer yorumu | Kod doğrulaması değil; raporun yorumu ekrandaki sayılara dayanıyor. Platform mimarisi kodda olgun; ticari sonuç kullanıcı verisine bağlı. |

**Sonuç:** Metriklerin kaynağı ve sunumu doğru; **ticari zayıflık iddiası veriye dayalı bir yorum**, kodla çelişmiyor.

---

## 8. Güvenlik, OTP, Admin, Audit

| Rapor iddiası | Doğrulama | Kanıt |
|---------------|-----------|--------|
| Admin yetkisi ve OTP pencere otomasyonu (SendMessageW) | ✅ Doğru | mt5_automator.py: ctypes.windll.user32.SendMessageW; MACHINE_REQUIREMENTS.md, ADMIN_PRIVILEGES.md, start_ustat.vbs runas; OTP script admin Python ile. |
| Tek kullanıcı; çoklu rol, maker-checker, kullanıcı bazlı audit trail yok | ✅ Doğru | Kodda rol/onay akışı ve kullanıcı bazlı audit alanı yok. |
| Immutable audit standardı / "kim, ne zaman, hangi karar, hangi korelasyon" tam cevap yok | ✅ Doğru | Event/log/DB var; correlation_id ve tek işlem izi yok; KNOWN_ISSUES’da belirtilmiş. |

**Sonuç:** Güvenlik ve OTP/admin/audit tespitleri **kod ve dokümanla uyumlu**.

---

## 9. Dayanıklılık ve Toparlanma

| Rapor iddiası | Doğrulama | Kanıt |
|---------------|-----------|--------|
| MT5 reconnect başarısız olursa sistem halt | ✅ Doğru | main.py: _heartbeat_mt5() False → _SystemStopError; _check_mt5_connection() reconnect (launch=False) bir kez deniyor, başarısızsa _SystemStopError. |
| DB ardışık hata (3) → sistem durur | ✅ Doğru | main.py DB_ERROR_THRESHOLD=3, _consecutive_db_errors >= 3 → _SystemStopError, system_halt. |
| Restart sonrası state restore, DB backup | ✅ Doğru | _restore_state(), db.backup() (engine start’ta), RESTART_RECOVERY.md. |
| Açık pozisyonlar halt’ta MT5’te kalabilir; "sistem durursa kullanıcı manuel kapatır" | ✅ Doğru | Halt durumunda otomatik toplu kapatma kodu yok; dokümanda "gözetimli kullanım" ve failover politikası sınırı belirtilmiş. |

**Sonuç:** Dayanıklılık ve halt davranışı **rapordaki gibi**.

---

## 10. EOD, Seans, Gece Taşıma

| Rapor iddiası | Doğrulama | Kanıt |
|---------------|-----------|--------|
| EOD / 17:45 kapanış; "EOD sadece OĞUL için mi?" | ⚠️ Netleştirme | Kodda EOD (17:45) hem OĞUL aktif işlemleri hem H-Engine hibrit pozisyonları için uygulanıyor (ogul.py force_close_all, h_engine.force_close_all("EOD_17:45")). Yani EOD sadece OĞUL’a özel değil; hibrit de kapanıyor. Rapor "yazılı risk politikası" ve "gece taşıma" sorusu olarak kalıyor; kodda 09:45–17:45 dışında manuel/hibrit aksiyon kısıtı var (time_utils, h_engine, manuel_motor). |

**Sonuç:** EOD hem OĞUL hem hibrit için; politika metni/UI’da açık ifade rapor önerisi olarak **yerinde**.

---

## 11. Puanlama ve Aksiyon Planı

Raporun puanları (handover 9/10, mimari 8/10, veri tutarlılığı 6/10, correlation/audit 6/10, dayanıklılık 5.5/10, güvenlik 5/10, strateji ekonomisi 4.5/10) ve önceliklendirilmiş aksiyon planı (güven/tutarlılık, audit/correlation, üretim sertliği, strateji ekonomisi) **kodla çelişmiyor**; değerlendirme mantığı tutarlı.

---

## 12. Genel Hüküm Doğruluğu

| Rapor özeti | Doğrulama |
|-------------|-----------|
| "Masaüstü odaklı, tek operatör, risk katmanı ciddi, teknik disiplinli algo trading workstation" | ✅ Kod ve dokümanla uyumlu. |
| "Tam gözetimsiz kurumsal üretim platformu seviyesine henüz ulaşmamış" | ✅ MT5/OTP/halt/audit/correlation/tek kullanıcı tespitleriyle uyumlu. |
| "Sistem uydurma değil; gerçekten çalışan, düşünülmüş ürün" | ✅ As-built handover, modül sırası, risk önceliği, state restore ile uyumlu. |
| "Kontrol ve sunum katmanı, strateji ve üretim dayanıklılığı katmanından daha olgun" | ✅ Mimari/UI güçlü; correlation, OTP, halt politikası, ticari sonuç raporla uyumlu şekilde sınırlı. |

---

## Sonuç Tablosu

| Kategori | Rapor iddiaları | Doğrulama |
|----------|------------------|-----------|
| Kanıt bütünlüğü | Doküman–ekran uyumu | ✅ Doğru |
| Mimari | Zincir, BABA→OĞUL, tek thread, restore, DB lock | ✅ Doğru |
| Operasyon / UI | Menü, Güvenli Kapat, Kill-Switch, System Monitor | ✅ Doğru |
| Risk | Limitler, kill-switch, lot çarpanı çelişkisi | ✅ Doğru (çelişki kanıtlandı) |
| Manuel/Hibrit | Akış, 0/3, 500 TL, olay detayı | ✅ Doğru; olay detayı kısmen ham |
| Veri / Audit | Correlation yok, ÜSTAT analiz 0/boş olabilir | ✅ Doğru |
| Performans | Metrikler ekrandan, ticari yorum | ✅ Kaynak doğru; yorum veriye dayalı |
| Güvenlik / OTP / Admin | SendMessageW, admin, tek kullanıcı, audit eksik | ✅ Doğru |
| Dayanıklılık | MT5/DB halt, restore, backup, açık pozisyon riski | ✅ Doğru |
| EOD / politika | EOD OĞUL + hibrit; politika metni önerisi | ⚠️ EOD ikisi için; öneri yerinde |

**Nihai değerlendirme:** Kurumsal değerlendirme raporu **dürüst ve disiplinli**. Tespitler büyük ölçüde kod ve handover ile doğrulanıyor; abartı veya yanlış iddia tespit edilmedi. Lot çarpanı çelişkisi, correlation eksikliği ve ÜSTAT analiz ekranı davranışı doğrudan kod/API/UI ile kanıtlandı. EOD’un hem OĞUL hem hibrit için geçerli olduğu kodla netleştirildi; diğer tüm ana maddeler raporla uyumlu.

---

## Rapor Bilgisi

| Alan | Değer |
|------|--------|
| Dosya | `docs/2026-03-10_kurumsal_degerlendirme_raporu_dogrulama_analizi.md` |
| İnceleme kapsamı | Kod tabanı + USTAT_HANDOVER |
| Değişiklik | Yok (sadece doğrulama) |
| Referans | STAT v5.3 — Doküman ve Ekranlar Birlikte Kurumsal Düzeyde Derin Değerlendirme |
