# ÜSTAT — Gelişim Tarihçesi (Changelog)

<!--
╔══════════════════════════════════════════════════════════════════════╗
║                   GELİŞİM TARİHÇESİ NASIL TUTULUR?                ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  Bu dosya projenin TÜM değişikliklerinin kronolojik kaydıdır.       ║
║  "Keep a Changelog" (keepachangelog.com) standardını takip eder.    ║
║                                                                      ║
║  KURALLAR:                                                           ║
║                                                                      ║
║  1. YAPI: Her versiyon bir başlık, altında kategoriler.             ║
║     Kategoriler: Added, Changed, Fixed, Removed, Security           ║
║     - Added    → Yeni eklenen özellik                               ║
║     - Changed  → Mevcut davranışta değişiklik                       ║
║     - Fixed    → Hata düzeltmesi                                    ║
║     - Removed  → Kaldırılan özellik/kod                             ║
║     - Security → Güvenlik düzeltmesi                                ║
║                                                                      ║
║  2. SIRALAMA: En yeni versiyon en üstte (ters kronolojik).         ║
║     Aynı versiyon içinde: en önemli değişiklik ilk sırada.         ║
║                                                                      ║
║  3. UZUNLUK: Her madde 1-2 satır. Detay gerekiyorsa oturum         ║
║     raporuna (docs/YYYY-MM-DD_session_raporu_*.md) referans ver.    ║
║     Changelog = "NE yapıldı", Oturum Raporu = "NASIL yapıldı".     ║
║                                                                      ║
║  4. NUMARA: Her madde #N formatında benzersiz sıra numarası alır.  ║
║     Numara HİÇBİR ZAMAN tekrar kullanılmaz veya atlanmaz.          ║
║                                                                      ║
║  5. REFERANS: Commit hash'i parantez içinde verilir.                ║
║     Örnek: #83 — Vade geçişi düzeltmesi (1d93ffd)                  ║
║                                                                      ║
║  6. DİL: Türkçe. Teknik terimler İngilizce kalabilir.              ║
║                                                                      ║
║  7. VERSİYON: Semantic Versioning (semver.org).                     ║
║     MAJOR.MINOR.PATCH — minor 9'dan sonra major artar.              ║
║     v5.8 → v5.9 → v6.0 → v6.1 ...                                  ║
║                                                                      ║
║  ÖRNEK MADDE:                                                        ║
║  - #83 — Vade günü Top 5 engeli: `<=` → `<` operatörü (1d93ffd)   ║
║                                                                      ║
║  YAPMA:                                                              ║
║  ✗ 50 satırlık detaylı analiz yazma (oturum raporuna koy)          ║
║  ✗ Aynı numarayı iki kez kullanma                                   ║
║  ✗ Numara atlama (#57'den #69'a geçme)                              ║
║  ✗ Kronolojik sırayı bozma                                          ║
║  ✗ "Sorun Analizi / Çözüm / Etkilenen Dosyalar" bölümleri ekleme  ║
║                                                                      ║
║  ESKİ DETAYLI VERSİYON:                                              ║
║  docs/USTAT_GELISIM_TARIHCESI_YEDEK.md (arşiv, referans için)   ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
-->

---

## [5.9.0] — 2026-03-28 / 2026-04-10

### Fixed
- #147 — PRİMNET netting SYNC atomik refactor: lot ekleme/çıkarma senkronizasyonunda state desync (retcode 10019 NO MONEY sonrası hp.volume eski pending emirlerle uyumsuz kalıyordu) giderildi. Margin ön kontrolü (free_margin ≥ 2000, margin_level ≥ 150%), atomik commit (hp.volume/entry_price SADECE emir başarısı sonrası güncellenir), trailing→hedef rollback mekanizması, lot çıkarmada entry_price/SL/TP koruması (netting mode MT5 davranışıyla birebir uyum). Config: `primnet.netting_sync_min_free_margin`, `primnet.netting_sync_min_margin_level` (h_engine.py, tests/test_hybrid_100.py)

### Added
- #139 — Kill-Switch bilgi modalı: Risk Yönetimi sayfasında Kill-Switch kartına tıklanınca seviye, neden, tetiklenme zamanı ve engelli kontratları gösteren modal pencere açılıyor (RiskManagement.jsx, api/routes/risk.py, api/schemas.py)
- #132 — Dashboard sürükle-bırak kart sıralaması: @dnd-kit ile tüm Dashboard bölümleri (8 kart) bağımsız olarak sürüklenip yeniden sıralanabiliyor. 4 stat kartı ayrı ayrı, büyük bölümler tam genişlik grid düzeninde. localStorage ile kalıcı sıralama
- #131 — SortableCard bileşenine className prop desteği eklendi — Dashboard grid düzeni için gerekli CSS class geçişi

### Fixed
- #146 — Kill-Switch L3 h_engine koordinasyonu: BABA L3 tetiklendiğinde `h_engine.force_close_all()` çağrılıyor — STOP LIMIT/LIMIT bekleyen emirler artık yetim kalmıyor (baba.py, main.py)
- #145 — Yön değişimi algılama: VİOP netting ile pozisyon yönü değişirse (ör. SELL→BUY) h_engine tüm PRIMNET emirlerini iptal edip hibrit takibi sonlandırıyor, UI'a critical bildirim gönderiyor (h_engine.py)
- #144 — Lot çıkarma sonrası bekleyen emir güncelleme: `_sync_netting_volume` lot azaltma branch'inde PRIMNET trailing+target emirleri yeni volume ile iptal+yeniden oluşturuluyor (h_engine.py)
- #143 — Trailing LOCK sonrası MT5-bellek desync tespiti: `modify_pending_order` başarısız olduğunda bellek/DB güncelleniyor ama MT5 emri eski fiyatta kalıyordu → LOCK bloğu desync'i gizliyordu. `_verify_trailing_sync()` eklendi: LOCK tetiklendiğinde MT5 bekleyen emri kontrol eder, fark varsa cancel+replace yapar. Restart sonrası yetim emir sahiplenmesi (comment-based) de destekleniyor (h_engine.py)
- #142 — Trailing Stop modify STOP LIMIT emirlerde "Invalid price" hatası: `modify_pending_order` sadece `price` gönderiyordu, `stoplimit` eksikti → SELL STOP LIMIT'te stoplimit < price kuralı ihlali (retcode 10015). Fonksiyona opsiyonel `new_stoplimit` parametresi eklendi, `_trailing_via_stop_limit` limit fiyatını da geçiyor (mt5_bridge.py, h_engine.py)
- #141 — Netting lot ekleme sonrası MT5 bekleyen emirler güncellenmiyor: `_sync_netting_volume` hp.current_sl'yi yeniden hesaplıyor ama MT5 stop limit emri eski fiyat+volume ile kalıyordu → iptal+yeni emir mekanizması eklendi (trailing + hedef, h_engine.py)
- #140 — Hibrit devir "Invalid order" hatası: GCM VİOP düz STOP emirleri desteklemiyor — `send_stop()` → `send_stop_limit()` dönüşümü yapıldı. 3 nokta düzeltildi: `transfer_to_hybrid()`, `_trailing_via_stop_limit()`, `_daily_primnet_refresh()` (h_engine.py)
- #134 — Veri yönetim sistemi çakışma düzeltmesi: `_run_daily_cleanup()` events ve risk_snapshots'ı aggregation yapmadan siliyordu → `daily_risk_summary` veri kaybına yol açıyordu. Cleanup artık sadece bars temizliyor, events/snapshots tamamen `run_retention()` tarafından yönetiliyor (main.py)
- #135 — Temizlik/retention/bakım tarihleri restart sonrası kayboluyordu (`None`'a dönüyordu → aynı gün tekrar çalışma riski). Tarihler artık `app_state` tablosuna persist ediliyor ve `_restore_state()` ile geri yükleniyor (main.py)
- #136 — Retention hiç çalışmıyordu (saat ≥18 koşulu + piyasa 18:15'te kapanma → pencere çok dar). Koşul 17:00'ye alındı (main.py)
- #137 — NABIZ çakışma algılama kodu (`nabiz.py`) yanlış sabit değerler kullanıyordu (events=60, snapshots=90) — gerçek cleanup config'den okuyor. Çakışma algılama mantığı güncellendi, retention kapalıysa uyarı veriyor
- #130 — OĞUL SE3 rejim-strateji filtresi: SE3 sinyal motoru regime.allowed_strategies kontrolünü atlatıyordu — RANGE rejiminde trend_follow sinyalleri üretilip zarar eden işlemler açılıyordu. Confluence döngüsüne rejim kapısı eklendi (ogul.py)

### Changed
- #138 — NABIZ retention tarihleri artık DB fallback ile okunuyor — engine bellekte yoksa `app_state` tablosundan okunuyor (nabiz.py)

### Fixed
- #139 — NABIZ üst kartlarında status ternary sırası hatalıydı: `>500 ? warn : >1000 ? err` → `err` koşuluna hiçbir zaman ulaşılamıyordu. Sıra düzeltildi: `>1000 ? err : >500 ? warn` (Nabiz.jsx, VERİTABANI + LOG DOSYALARI kartları)
- #133 — CLAUDE.md Bölüm 7 ADIM 1 güncellendi: Electron production build zorunluluğu detaylı açıklandı — kaynak dosya düzenlemek yetmez, `npm run build` + shortcut güncelleme + restart gerekir

### Security
- #129 — MT5 auto-launch koruma genişletme: `api/routes/mt5_verify.py _verify()` ve `health_check.py`'ye de terminal64.exe process kontrolü eklendi — mt5.initialize() çağrılmadan önce MT5 çalışıyor mu diye bakılıyor. `start_ustat.py` ölü pywebview koduna uyarı eklendi
- #128 — MT5 auto-launch koruma: Engine connect(launch=False) artık mt5.initialize() çağırmadan ÖNCE terminal64.exe process kontrolü yapıyor — process yoksa bağlantı atlanır, MT5 asla otomatik açılmaz. Siyah Kapı #31 + Anayasa Kural 4.15 eklendi. 10/10 açma-kapama testi geçti
- #127 — Electron single-instance kilidi HER ZAMAN aktif: `requestSingleInstanceLock()` artık API modda da çalışıyor — birden fazla pencere açılması engellendi (desktop/main.js)
- #126 — Ajan singleton koruması: PID dosyası + psutil kontrolü ile çoklu ajan instance engellendi. Atomik komut kilitleme (.processing rename) ile aynı komutun birden fazla kez işlenmesi önlendi (ustat_agent.py v3.2.0)
- #125 — handle_start_app Electron process kontrolü: Uygulama başlatılmadan önce hem API portu hem Electron process'i kontrol ediliyor — çift başlatma engellendi

### Fixed
- #124 — API başlatma hatası kök neden: pythonw.exe stdout/stderr=None yapıyor → uvicorn sessizce çöküyordu. python.exe + CREATE_NO_WINDOW ile değiştirildi, start_ustat.py'ya stdout/stderr fallback koruması eklendi
- #123 — Named Mutex namespace: `Local\` → `Global\` değiştirildi — admin/normal kullanıcı oturumları arası tek instance koruması sağlandı. TIME_WAIT socket süresi 120sn→30sn (TcpTimedWaitDelay registry)

### Fixed
- #122 — OĞUL anında kapanış sorunu: `_send_order_inner` TRADE_ACTION_SLTP başarısız olduğunda pozisyonu hemen kapatıyordu (GCM VİOP exchange modda SLTP desteklenmiyor). Artık OgulSLTP mekanizmasına (plain STOP pending emir) bırakıyor, pozisyon korumalı yaşıyor. OgulSLTP de başarısız olursa Anayasa 4.4 kuralı `_execute_signal`'da uygulanıyor

### Added
- #112 — ProcessGuard hayalet koruma modülü: PID registry, tree-kill, orphan Electron/MT5 tespiti, port/socket temizliği — kapanışta kalan zombie process/port/socket sorununu çözer
- #113 — api.pid dosya yazımı: start_ustat.py API başladığında PID yazar, Electron killApiProcess() artık API process'i bulabilir
- #114 — WebSocket graceful shutdown: shutdown_all_connections() fonksiyonu — kapanışta tüm WS bağlantıları kapatılır, TIME_WAIT socket birikimi önlenir
- #107 — pywebview migrasyonu: Electron+Vite → pywebview+pystray tek process mimarisi, SPA static serving FastAPI'den (65dc9ff)

### Fixed
- #115 — Shutdown zinciri düzeltmesi: _shutdown_api() timeout 20sn→45sn (engine.stop() 30sn sürebilir), çift çağrı koruması, Electron tree-kill subprocess durumundan bağımsız hale getirildi
- #116 — Kapanış sırası düzeltmesi: server.py lifespan shutdown — WebSocket kapat → Engine durdur → api.pid temizle (eskiden WebSocket cleanup yoktu)
- #108 — CORS/origin düzeltmesi: api.js absolute URL→relative (`/api`), server.py CORS listesine `127.0.0.1:8000` eklendi — pywebview origin uyumsuzluğu giderildi
- #109 — logger.py UTF-8 stderr sarmalayıcı: pythonw.exe charmap codec hatası düzeltildi — MT5 bağlantı başarısızlığının kök nedeni
- #110 — Tek instance kilidi: start_ustat.py port+PID kontrolü, stale lock temizleme, mevcut pencereyi öne getirme (EnumWindows)
- #111 — pywebview shim API referansı: `window.pywebviewApi`→`window.pywebview.api` — pencere kontrolleri, güvenli kapat, pin butonu çalışmıyordu (26b4945)
- #111 — Pencere maximized başlatma: `maximized=True` eklendi — uygulama tam ekran açılıyor (26b4945)
- #106 — 8 güvenlik açığı düzeltmesi: 1 Nisan olay raporu (230ee5f)

### Changed
- #105 — Otonom vade geçiş sistemi: 4 katmanlı koruma — trade_mode tabanlı kontrat seçimi, saatlik periyodik tarama, retcode 10044 reaktif handler, eski vade pozisyon tespiti + VADE_UYARI/STALE_POSITION event'leri (34ded93)
- #105 — Yarım gün (arefe) desteği: HALF_DAYS setleri (2025-2027), is_half_day(), get_close_time(), is_market_open() arefe günü 12:40 kapanış (34ded93)
- #104 — Veri Yönetim Sistemi iyileştirme: OHLCV validasyon katmanı (Katman 1), veri bayatlık tespiti (freshness monitor — FRESH/STALE/SOURCE_FAILURE ayrımı), SQLite PRAGMA optimizasyonu (synchronous=NORMAL, cache_size=64MB, mmap_size=256MB)
- #104 — Retention düzeltme: M1/M5 bar temizliği eklendi, hard-coded retention→config'den okuma, trade_archive_days config desteği
- #104 — 7 sessiz hata düzeltmesi: OĞUL SE3 `except: pass`→loglama, M5 yetersiz veri DEBUG→WARNING, H1/Voting atlama logları, insert_top5 boş liste koruması, insert_risk_snapshot güvenli .get() erişimi, insert_bars dönüş değeri kontrolü
- #90 — Log Yönetim Sistemi v3.0: FUSE cache bypass — 5 yeni ajan komutu (fresh_engine_log, search_all_logs, log_digest, log_stats, log_export), Claude Bridge v4.0, log_reader.py yardımcı scripti
- #55 — ÜSTAT Beyin Merkezi sayfası: trade kategorileri, kontrat profilleri, rejim analizi, hata atfetme (3d75fe3)
- #56 — Haber entegrasyonu: MT5 Calendar → NewsBridge → BABA/OĞUL erken uyarı sistemi (2026-03-23)
- #69 — Kademeli trailing stop + breakeven floor: ATR bazlı 3 fazlı sistem (2026-03-25)
- #70 — OĞUL manuel pozisyon koruma kalkanı: cross-motor netting koruması (2026-03-25)
- #73 — MT5-Direct pozisyon sahiplenme: ManuelMotor adopt mekanizması (2026-03-26)
- #79 — PRİMNET: Prim bazlı net emir takip sistemi — H-Engine yeni pozisyon yönetim modu (2026-03-27)
- #80 — PRİMNET v2: Bildirim sistemi, PrimnetDetail modalı, hibrit performans istatistikleri, notifications API (6a38f64)
- #82 — Frameless titlebar: SVG pencere kontrolleri, IPC bridge (da730b1)
- #82 — Ajan Windows Service desteği: pywin32, crash restart, auto-install, shutdown.signal (b56ef71)
- #82 — Watchdog OTP bekleme: WATCHDOG_INITIAL_DELAY=30sn, eski heartbeat temizleme (da730b1)
- #83 — 10.003 kombinasyonlu stres testi: BABA/OĞUL/H-Engine/MT5/Manuel/Top5/DB/Entegrasyon (a36f3d0)

### Added
- #120 — mt5_bridge.py'ye 4 yeni fonksiyon: send_stop (BUY/SELL STOP), send_limit (BUY/SELL LIMIT), modify_pending_order, cancel_pending_order — plain STOP/LIMIT emir desteği
- #119 — OĞUL Stop Limit SL/TP sistemi: ogul_sltp.py modülü — GCM VİOP netting modunda TRADE_ACTION_SLTP yerine bekleyen emirlerle SL koruması
- #119 — Trade modeline sl_order_ticket alanı eklendi (bekleyen emir takibi)

### Fixed
- #121 — PRİMNET trailing stop KİLİT mekanizması: send_stop() başarısız olduğunda hp.current_sl güncellenmiyordu → trailing geri gidiyordu. Artık her durumda bellek+DB güncelleniyor, software SL güvenlik ağı olarak çalışıyor (734999e)
- #121 — PRİMNET çift emir temizliği: _cancel_stop_limit_orders artık ticket + comment deseni ile arama yapıyor → restart sonrası kalan orphan emirler de temizleniyor (734999e)
- #121 — PRİMNET 0.50 prim adım filtresi: trailing stop artık giriş priminden başlayan 0.50'lik ızgaraya yuvarlanıyor (config step_prim=0.5). Floating point hatası round(,10) ile giderildi
- #120 — Stop Limit → plain STOP/LIMIT migrasyonu: Stop Limit emirleri tetiklendiğinde limit fiyatı yüzünden dolmuyordu (SL) veya [Invalid price] hatası veriyordu (TP). Plain STOP (SL için — market dolum garantili) ve plain LIMIT (TP için — doğru fiyat yönü) ile değiştirildi

### Changed
- #120 — H-Engine trailing: _trailing_via_stop_limit() artık send_stop + modify_pending_order kullanıyor (Stop Limit + gap yerine tek fiyatlı plain STOP)
- #120 — H-Engine hedef: _place_target_stop_limit() artık send_limit kullanıyor (TP için plain LIMIT — [Invalid price] hatası düzeldi)
- #120 — H-Engine devir + yenileme: send_stop_limit çağrıları send_stop/send_limit ile değiştirildi, _cancel_stop_limit_orders cancel_pending_order kullanıyor
- #120 — ogul_sltp.py: Stop Limit → plain STOP migrasyonu, gap/limit_price hesabı kaldırıldı, modify_stop_limit → modify_pending_order
- #119 — OĞUL'da tüm modify_position çağrıları OgulSLTP.update_trailing_sl() ile değiştirildi — breakeven, KORUMA, TREND, SAVUNMA, fallback trailing, MR breakeven, breakout trailing
- #119 — Lifecycle entegrasyonu: _handle_closed_trade → SL iptal, EOD → SL iptal, _sync_positions → SL tetiklenme kontrolü, restore_active_trades → SL kurtarma
- #119 — config/default.json'a ogul.stop_limit_gap_prim=0.3 eklendi
- #118 — Motor izolasyonu: OĞUL ardışık kayıp sayacı motor bazlı ayrıştırma — H-Engine/ManuelMotor kayıpları OĞUL cooldown'ını tetiklemez, OĞUL trade kaydına `source: "auto"` eklendi (baba.py, ogul.py)
- #117 — PRİMNET Stop Limit emir sistemi: TRADE_ACTION_SLTP (modify_position) yerine Buy/Sell Stop Limit bekleyen emirler ile trailing stop ve hedef yönetimi — GCM VİOP netting modunda "Invalid order" (retcode 10035) sorununu çözer
- #117 — mt5_bridge.py'ye 3 yeni fonksiyon: send_stop_limit, modify_stop_limit, cancel_stop_limit + get_pending_orders STOP_LIMIT tip tanıma
- #117 — H-Engine tam yaşam döngüsü: devir→trailing→hedef→kapanış→gece geçişi→restart kurtarma Stop Limit emirlerle
- #97 — PRİMNET sabit trailing: Faz 1/Faz 2 ayrımı kaldırıldı, her zaman 1.5 prim sabit trailing, stop > giriş olduğunda kilitli kâr otomatik (9020e43)

### Fixed
- #105 — VIOP_EXPIRY_DATES Mayıs 2026 düzeltmesi: date(2026,5,29)→date(2026,5,25) — Kurban Bayramı arefesi yarım gün kuralı nedeniyle vade 25 Mayıs Pazartesi (34ded93)
- #103 — OĞUL 3 katmanlı pipeline: SE3 binary→sürekli strength, confluence ≥50 kapı→çarpan (min 20), yön 2/3→1/3, R:R sert blok→penalty, risk_multiplier lot çarpanı (116cc5e, c755cf2, 04dc627, b0baa87)
- #99 — 16 kritik sessiz mayın temizliği: haber filtresi VİOP ilgililik kontrolü, H1 iloc/label index, vade CRITICAL log, risk fail-safe, api.js client fix, 5 silent pass→logger (536ccb7, 57989f2)
- #100 — Engine başlatma resilience: MT5 retry 15sn×20 döngü, smoke test toleransı (kısıtlı mod), API os._exit kaldırıldı→yeniden başlatma (59d81cd)
- #101 — Açılış hızı optimizasyonu: wait_for_port 1s→0.2s polling, cleanup sleep'ler kısaltıldı, watchdog 30→10sn, splash 10→4sn, Vite poll 500→150ms (6f62507)
- #102 — Nabız hardcoded kartlar dinamik kontrole çevrildi: çakışma uyarısı config karşılaştırması, missing_retention DB'den hesaplama (4c6364e)
- #98 — PRİMNET devir hatası: h_engine.py'de 6 yerde eski _primnet_faz1_stop/_primnet_faz2_trailing referansları _primnet_trailing olarak düzeltildi — transfer_to_hybrid, netting sync, referans fiyat güncelleme fonksiyonları
- #75 — Vade geçişi GCM paraleli: EXPIRY_NO_NEW_TRADE_DAYS/EXPIRY_CLOSE_DAYS=1→0, gözlem süresi kaldırıldı (2026-03-26)
- #80 — H-Engine: ATR/profit trailing kaldırıldı, PRİMNET tek pozisyon yönetim modu (6a38f64)
- #80 — OĞUL EOD hibrit kapatma kaldırıldı — her motor kendi işini yapacak (6a38f64)
- #80 — Eski trailing mantığı arşive taşındı: engine/archive/h_engine_trailing_legacy/ (6a38f64)
- #81 — OĞUL v5.9 yeniden yapılandırma: 44 bulgu, 5 aşamalı revizyon (e57b008)
- #81 — Sinyal mimarisi: yön konsensüsü (3 kaynak, 2/3 çoğunluk) + tek confluence gate (e57b008)
- #81 — Pozisyon yönetimi: 4 modlu adaptif sistem (KORUMA→TREND→SAVUNMA→ÇIKIŞ) (e57b008)
- #81 — Emir mekanizması: limit→market, lot=1 sabit (test süreci) (e57b008)
- #81 — TRADING_CLOSE, MAX_LOT, MAX_CONCURRENT config'den okunuyor (e57b008)
- #81 — 700+ satır ölü kod kaldırıldı, SE2→SE3 isimlendirme (e57b008)
- #82 — BABA EXPIRY_DAYS=2→0: vade kısıtlaması kaldırıldı (da730b1)

### Changed
- #85 — Hibrit İşlem Paneli sürükle-bırak: react-grid-layout → @dnd-kit — 5 kart sürüklenebilir sıralama, localStorage kalıcılık, sıfırla butonu

### Fixed
- #91 — Vade geçişi otomasyonu: `_resolve_symbols()` en yeni vadeden activate eder — vade son günü otomatik yeni kontrata geçiş (mt5_bridge.py)
- #92 — Haber kaynaklı L1 kontrat engeli günlük sıfırlama: `_reset_daily()` önceki günün L1'ini kaldırır (baba.py)
- #93 — VİOP ilgisizlik filtresi: `get_news_warnings()` currency kontrolü + SYMBOL_KEYWORDS genel sektör kelimeleri temizlendi (news_bridge.py)
- #94 — OLAY rejimi vade kontrolü: `_check_olay()` EXPIRY_DAYS=0 ile `<=` → `<` operatörü (baba.py)
- #95 — Pozisyon görünürlük: `_to_base()` prefix fallback + `_resolve_symbols()` çoklu visible'da max seçimi (mt5_bridge.py)
- #96 — Başlatıcı: shutdown.signal koşulsuz temizleme + API timeout 30→15sn (start_ustat.py)
- #88 — Confluence strateji-bazlı skorlama: trend_follow/breakout sinyallerinde RSI>70 ve direnç yakınlığı cezaları kaldırıldı — 184 sinyal/0 işlem sorununu çözer
- #89 — PrimnetDetail.jsx Faz 2 açıklama satırları düzeltmesi + theme.css PRİMNET modal stilleri iyileştirmesi
- #76 — VİOP ilgisizlik filtresi: USD haberlerinin Türk hisselerinde yanlış OLAY rejimi tetiklemesi (2026-03-27)
- #77 — Exchange netting position ticket: VİOP netting modunda ticket çözümleme hatası (2026-03-27)
- #78 — Native SL/TP config geri alma: yanlış config override düzeltmesi (2026-03-27)
- #81 — _check_advanced_risk_rules() + _check_time_rules() çağrılmıyordu — 5 risk kontrolü devre dışıydı (e57b008)
- #81 — SE3'e symbol gönderilmiyordu — haber kaynağı sessizce devre dışıydı (e57b008)
- #83 — Vade günü Top 5 engeli: `<=` → `<` operatörü — 31 Mart tüm semboller engelleniyordu (1d93ffd)
- #83 — Ajan ChangeServiceConfig parametre çakışması + main() eksik (ebab753)
- #83 — ManualTrade MT5 pozisyon filtresi: `'Manuel'` → `'Manuel' || 'MT5'` (ebab753)
- #83 — Settings.jsx VERSION=5.8→5.9, BUILD_DATE=03-26→03-29 (7bba799)
- #83 — Python 3.10 __pycache__ kalıntıları temizlendi, build yenilendi
- #84 — Event deduplication: aynı uyarı 5dk içinde tekrar DB'ye yazılmaz — EARLY_WARNING 3600+ spam düzeltildi (ddcb053)
- #84 — Gelişim tarihçesi Keep a Changelog formatına dönüştürüldü (0927520)
- #84 — Dosya organizasyonu: raporlar RAPORLAR/, oturum raporları docs/ (2b64dc7)
- #86 — Ajan start_app Session 0 sorunu: subprocess.Popen → schtasks /IT ile kullanıcı oturumunda başlatma
- #87 — Pozisyon tür ayrımı: _source_for_position() fallback düzeltmesi — DB'de source boş olan pozisyonlar MT5 olarak etiketleniyor

---

## [5.8.0] — 2026-03-20 / 2026-03-26

### Added
- #46 — Otomatik İşlem Paneli WebSocket entegrasyonu: canlı pozisyon + durum güncellemesi (2026-03-20)
- #48 — OĞUL v2 Revizyon: 6 aşamalı pipeline yenileme, aktif işlem kapasitesi (2026-03-21)
- #49 — M5 sinyal tetikleme: M15→M5 timeframe geçişi (2026-03-21)
- #50 — OĞUL tam mimari dokümantasyonu (2026-03-21)
- #51 — ANAYASA v2.0: CEO genişletmesi, Siyah Kapı tanımları (2026-03-21)
- #52 — CEO FAZ-1: Kritik güvenlik yamaları (2026-03-21)
- #53 — CEO FAZ-2: Altyapı güçlendirme (2026-03-21)
- #54 — CEO FAZ-3: Governance — modüler refactoring (2026-03-21)
- #57 — Gelişim tarihçesi audit: yapılmadı/atlandı/yarım kaldı analizi (2026-03-23)
- #58 — OĞUL v13.0 işlem yönetimi iyileştirmeleri (2026-03-22)
- #59 — Stres test altyapısı: FAZ-1/2/3 (2026-03-22)
- #60 — Hibrit Motor breakeven/trailing parametre optimizasyonu (2026-03-24)
- #63 — Kâr bazlı trailing stop (Profit Trailing) (2026-03-24)
- #65 — Zombie process koruması: CIM fallback (2026-03-25)
- #67 — Trailing mesafe sınırları: VİOP rapor uyumu (2026-03-25)
- #71 — Güvenli çıkış: shutdown.signal + watchdog singleton düzeltmesi (2026-03-26)
- #72 — Tam sistem audit: 25 dosya, 8 kategori düzeltme + ÜSTAT beyin geliştirme (2026-03-26)

### Changed
- #62 — Motor bazlı floating ayrıştırma: CEO Option C (2026-03-24)
- #74 — WebSocket TÜR sütunu tutarsızlığı düzeltmesi (2026-03-26)

### Fixed
- #45 — Kırmızı Bölge kapsamlı bug tarama: 29 sorun tespiti ve düzeltmesi (2026-03-20)
- #47 — v5.6 Kırmızı Bölge: 9 bug düzeltmesi (3 kritik, 3 yüksek, 3 orta) (2026-03-20)
- #61 — VİOP limit emir invalid expiration düzeltmesi (2026-03-24)
- #66 — SSE tür tutarsızlığı: Manuel/Hibrit flipping sorunu (2026-03-25)

### Security
- #52 — SL/TP zorunluluk kontrolü güçlendirildi (2026-03-21)
- #54 — Circuit breaker cooldown doğrulaması eklendi (2026-03-21)

---

## [5.7.0] — 2026-03-13 / 2026-03-17

### Added
- #40 — v14 Production-Ready: Risk & sinyal motoru tam revizyon (2026-03-13)
- #41 — Tam sistem audit: WebSocket güvenliği, süre etiketi, PnL düzeltmesi (2026-03-16)

### Fixed
- #44 — Risk hesaplama: Günlük/haftalık/aylık PnL doğru sıralama (2026-03-17)

---

## [5.6.0] — 2026-03-10

### Added
- #38 — Kurumsal değerlendirme eleştiri düzeltmeleri (2026-03-10)
- #39 — Sürdürülebilirlik ve çökme direnci iyileştirmeleri (2026-03-10)

### Fixed
- #41 — Kill-Switch L2 döngü bugu düzeltmesi (2026-03-10)
- #42 — Manuel işlem force-close bugu + aktif pozisyon kartları (2026-03-10)
- #43 — OĞUL manuel/hibrit pozisyon sahiplenme bugu (2026-03-10)

---

## [5.4.0] — 2026-03-09 → [5.5.0]

### Added
- #35 — System Monitor: Sistem sağlığı + günlük birleştirme (2026-03-09)
- #36 — Monitor: Çift yönlü oklar + metin okunabilirliği (2026-03-09)

### Changed
- Versiyon geçişi: v5.3 → v5.4 (2026-03-09)

### Fixed
- #37 — Manuel/Hibrit bug fix + risk baseline ayarı (2026-03-09)

### Removed
- #14 — Ölü kod temizliği + performans optimizasyonu (2026-03-09)

---

## [5.3.0] — 2026-03-08

### Added
- #29 — Kod merkezileştirme + ekran inceleme düzeltmeleri (2026-03-08)
- #31 — Bağımsız Manuel İşlem Motoru (ManuelMotor) (2026-03-07)
- #32 — 50 kişilik uzman ekip raporu uygulaması (2026-03-08)
- #33 — İşlem geçmişi: filtre ve sıralama iyileştirmesi (2026-03-08)

### Changed
- #30 — Versiyon yükseltme: v5.1 → v5.2 (2026-03-08)

### Fixed
- #34 — Engine başlatma hatası: RISK_BASELINE_DATE (2026-03-08)

---

## [5.2.0] — 2026-03-07

### Added
- #13 — OĞUL Evrensel Pozisyon Yönetim Sistemi (2026-03-06)
- #14 — Sistem Sağlığı Paneli (2026-03-06)
- #16 — Dashboard düzenleme + Otomatik İşlem Paneli (2026-03-07)
- #18 — Açık Pozisyonlar Dashboard'a birleştirilmesi (2026-03-07)
- #22 — Event-Driven işlem geçmişi + tarih filtresi (2026-03-07)
- #28 — OĞUL Aktivite Kartı + USDTRY sembol düzeltmesi (2026-03-07)

### Changed
- #15 — REGIME_STRATEGIES risk otoritesi taşınması (2026-03-07)
- #21 — Hibrit işlem türü sınıflandırma (2026-03-07)
- #23 — Dashboard istatistikleri 01.02.2026 tarih filtresi (2026-03-07)

### Fixed
- #17 — Risk baseline tarih güncelleme (2026-03-07)
- #19 — Peak equity doğrulama eşiği düzeltmesi (2026-03-07)
- #20 — İşlem geçmişi baseline filtresini kaldır (2026-03-07)
- #24 — Profit Factor baseline tutarsızlığı düzeltmesi (2026-03-07)
- #25 — Stres testi bulguları: 6 düzeltme (2026-03-07)
- #26 — Sistem sağlığı: 8 sorun düzeltme (2026-03-07)
- #27 — OĞUL işlem yapmama: 7 engel düzeltmesi (2026-03-07)

---

## [5.1.0] — 2026-03-05 / 2026-03-06

### Added
- #1 — Yazılımsal SL/TP modu: software bazlı stop-loss/take-profit (2026-03-05)
- #4 — Açık Pozisyonlar "Tür" sütunu: backend tek kaynak (2026-03-05)
- #5 — İşlem geçmişi MT5 anlık sync (2026-03-05)
- #7 — Kapanma-tetiklemeli MT5 sync: event-driven mimari (2026-03-05)
- #8 — VİOP uzlaşma gecikmesi retry mekanizması (2026-03-05)
- #9 — v13.0: Top 5 kontrat seçimi ÜSTAT → OĞUL taşınması (2026-03-05)
- #10 — v13.0: ÜSTAT Brain tam implementasyon (2026-03-05)
- #11 — v13.0: BABA risk aksiyonu olay kaydı (2026-03-05)
- #12 — Sistem sağlık iyileştirmeleri (2026-03-05)

### Fixed
- #2 — Açık Pozisyonlar "İşlemi Kapat" butonu düzeltmesi (2026-03-05)
- #3 — mt5_bridge.py önceki düzeltmeler (2026-03-05)
- #6 — İşlem geçmişi yüklenme ve hata mesajları (2026-03-05)

---

> **Not:** Detaylı sorun analizleri, çözüm açıklamaları ve etkilenen dosya listeleri
> oturum raporlarında bulunur: `docs/YYYY-MM-DD_session_raporu_*.md`
>
> Eski detaylı tarihçe arşivi: `docs/USTAT_GELISIM_TARIHCESI_YEDEK.md`
