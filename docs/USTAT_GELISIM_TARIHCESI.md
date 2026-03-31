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

## [5.9.0] — 2026-03-28 / 2026-03-31

### Added
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

### Changed
- #97 — PRİMNET sabit trailing: Faz 1/Faz 2 ayrımı kaldırıldı, her zaman 1.5 prim sabit trailing, stop > giriş olduğunda kilitli kâr otomatik (9020e43)
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
