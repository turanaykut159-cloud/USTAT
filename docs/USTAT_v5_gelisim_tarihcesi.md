# ÜSTAT v5.1 — Gelişim Tarihçesi

---

## #1 — Yazılımsal SL/TP Modu (2026-03-05)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-05 |
| **Neden** | Hibrit devir sırasında `TRADE_ACTION_SLTP` → retcode=10035 hatası. MT5 build 4755 < sunucu min 5200. Native SLTP GCM VİOP'ta çalışmıyor. |
| **Kök Neden** | MT5/broker tarafı. `TRADE_ACTION_SLTP` hiçbir koşulda başarılı olmuyor. `TRADE_ACTION_DEAL` sorunsuz çalışıyor. |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `config/default.json` | `hybrid.native_sltp: false` config flag eklendi |
| `engine/h_engine.py` | `_check_software_sltp()` metodu — her 10sn fiyat kontrolü, SL/TP ihlalinde `close_position` (DEAL) ile kapatma |
| `engine/h_engine.py` | `transfer_to_hybrid` — `native_sltp=false` ise MT5 modify atlanır, SL/TP yalnızca bellek+DB |
| `engine/h_engine.py` | `_check_breakeven` — native kapalıyken sadece internal SL güncelleme |
| `engine/h_engine.py` | `_check_trailing` — native kapalıyken sadece internal SL güncelleme |
| `api/schemas.py` | `HybridStatusResponse.native_sltp` alanı |
| `api/routes/hybrid_trade.py` | `native_sltp` bilgisi response'a eklendi |
| `desktop/src/components/HybridTrade.jsx` | "Yazılımsal SL/TP" badge göstergesi |
| `desktop/src/styles/theme.css` | Badge stilleri + SOFTWARE_SL/TP event renkleri |
| `docs/HIBRIT_10035_KOK_NEDEN_ANALIZI.md` | Tam kök neden analiz dokümanı |

### Eklenen
- `_check_software_sltp()` metodu (h_engine.py)
- `hybrid.native_sltp` config parametresi
- UI'da SL/TP modu göstergesi

### Geçiş Planı
- MT5 build 5200+ kurulunca → `native_sltp: true` → engine restart

---

## #2 — Açık Pozisyonlar "İşlemi Kapat" Butonu Düzeltmesi (2026-03-05)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-05 |
| **Neden** | MT5'ten doğrudan açılan pozisyonlarda "İşlemi Kapat" butonu görünmüyordu |
| **Kök Neden** | `_strategy_for_position()` OĞUL active_trades'te bulamadığı pozisyonlara `"bilinmiyor"` döndürüyor → UI bunu "Otomatik" olarak gösteriyor → "İşlemi Kapat" butonu sadece `strategy=manual` için gösteriliyordu |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `desktop/src/components/OpenPositions.jsx` | "İşlemi Kapat" butonu tüm non-hybrid pozisyonlarda gösteriliyor |
| `desktop/src/components/OpenPositions.jsx` | `"bilinmiyor"` → "Harici" etiketi (MT5'ten açılan pozisyonlar) |
| `desktop/src/styles/theme.css` | `.op-tur--external` badge stili |

### Eklenen
- "Harici" pozisyon türü etiketi ve stili

### Çıkartılan
- `isManual` koşulu buton gösteriminden kaldırıldı (artık tüm pozisyonlarda buton var)

---

## #3 — Önceki Düzeltmeler (mt5_bridge.py) (2026-03-05)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-05 |
| **Neden** | 10035 hatası araştırılırken yapılan iyileştirmeler |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `engine/mt5_bridge.py` | `modify_position`: `position` alanı her zaman gönderiliyor (netting koşulu kaldırıldı) |
| `engine/mt5_bridge.py` | `modify_position`: `order_check` kaldırıldı (eski build false-negative) |
| `engine/mt5_bridge.py` | `modify_position`: 3 retry + 0.5s bekleme eklendi |
| `engine/mt5_bridge.py` | `modify_position`: `type_filling=RETURN` ve `type_time=GTC` eklendi |
| `engine/mt5_bridge.py` | `send_order` Phase 2: retry arası 0.5s bekleme eklendi |
| `engine/mt5_bridge.py` | `send_order` Phase 2: `type_filling` ve `type_time` eklendi |

### Not
Bu düzeltmeler native SLTP çalışmadığı için sorunu çözmedi ama kod kalitesini artırdı. MT5 build güncellenince bu iyileştirmeler faydalı olacak.

---

## #4 — Açık Pozisyonlar "Tür" Sütunu (Backend Tek Kaynak) (2026-03-05)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-05 |
| **Neden** | Tür sütununda "Otomatik/Manuel/Hibrit" tutarlı görünsün; yanlış "Otomatik" etiketleri düzelsin |
| **Kök Neden** | Tür yalnızca frontend'de stratejiye göre hesaplanıyordu; hibrit listesi ve strateji tek kaynak değildi |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `api/schemas.py` | `PositionItem.tur` alanı eklendi ("Otomatik" \| "Manuel" \| "Hibrit") |
| `api/routes/positions.py` | `get_h_engine`, `_tur_for_position()` — hibrit ticket seti + sadece trend_follow/mean_reversion/breakout → Otomatik |
| `api/routes/positions.py` | GET /positions: her pozisyon için `tur` hesaplanıp response'a yazılıyor |
| `desktop/src/components/OpenPositions.jsx` | Önce API'den gelen `pos.tur` kullanılıyor; yoksa fallback (strateji/hibrit) |

### Eklenen
- Backend'de tek kaynak: `tur` API'den geliyor; masaüstü uygulaması bu değeri gösteriyor

---

## #5 — İşlem Geçmişi MT5 Anlık Sync (2026-03-05)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-05 |
| **Neden** | MT5'te değişiklik olduğunda tüm işlem geçmişi ekranları anlık güncel veri göstermeli |
| **Kök Neden** | Geçmiş sadece engine açılışında bir kez sync ediliyordu; ekranlar sadece DB'den okuyordu |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `engine/main.py` | `sync_mt5_history_recent(days)` eklendi; periyodik her 60 sn son 7 gün sync |
| `engine/main.py` | Startup'tan sonra `_last_history_sync_time` ile periyodik sync tetikleniyor |
| `api/routes/trades.py` | GET /trades, GET /trades/stats: önce `sync_mt5_history_recent(3)` (try/except ile) |
| `api/routes/performance.py` | GET /performance: önce son 3 gün sync (try/except) |
| `api/routes/ustat_brain.py` | GET /ustat/brain: önce son 7 gün sync (try/except) |
| `api/routes/positions.py` | POST /positions/close başarılı olunca `sync_mt5_history_recent(1)` |

### Eklenen
- Geçmiş verisi isteyen her ekran açılışında MT5'ten son günler sync, sonra DB'den okuma
- Pozisyon kapatıldığında kapanan işlem hemen geçmişte görünüyor

---

## #6 — İşlem Geçmişi Yüklenme ve Hata Mesajları (2026-03-05)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-05 |
| **Neden** | "İşlem geçmişi gelmedi" — API hata verince veya veri boş gelince kullanıcı bilgilendirilmeli |
| **Kök Neden** | Sync hatası tüm isteği düşürüyordu; frontend boş/hatada aynı mesajı gösteriyordu |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `api/routes/trades.py` | GET /trades, GET /trades/stats: sync `try/except` — hata olsa bile DB cevabı dönüyor |
| `api/routes/performance.py` | sync try/except |
| `api/routes/ustat_brain.py` | sync try/except |
| `desktop/src/services/api.js` | getTrades hata durumunda `{ count: 0, trades: [], error: true }` dönüyor |
| `desktop/src/components/TradeHistory.jsx` | `fetchError` state; hata mesajı + "Yenile" butonu; boş/veri yok ayrı mesajlar |
| `desktop/src/styles/theme.css` | `.th-error-msg`, `.th-error-hint`, `.th-retry-btn` stilleri |

### Eklenen
- Masaüstü İşlem Geçmişi: "İşlem geçmişi yüklenemedi" + Yenile butonu; "Henüz işlem kaydı yok veya veri gelmedi" metni

---

## #7 — Kapanma-Tetiklemeli MT5 Sync (Event-Driven) (2026-03-05)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-05 |
| **Neden** | MT5'te kapanan islemler USTAT'ta gorunmuyordu. Periyodik polling (60sn) calismiyordu veya engine restart edilmemisti |
| **Kok Neden** | Step 8 periyodik sync (HISTORY_SYNC_INTERVAL=60) ya engine restart gerektiriyordu ya da _connected guard engelliyordu. TradeHistory.jsx'te auto-refresh yoktu |

### Yaklasim — Ticket Set Diff (Periyodik Polling Yerine)
1. Her cycle'da `pipeline.latest_positions`'dan guncel ticket set alinir
2. Onceki cycle'in ticket set'i ile karsilastirilir: `onceki - simdiki = kapanan ticket'lar`
3. Kapanma tespit edilirse `get_history_for_sync(days=1)` tetiklenir → DB'ye sync
4. Ilk cycle'da (prev bos) sadece set baslatilir, sync tetiklenmez

### Degisiklikler

| Dosya | Ne Degisti |
|-------|-----------|
| `engine/main.py` | Step 8 periyodik sync (HISTORY_SYNC_INTERVAL + _last_history_sync_time) KALDIRILDI |
| `engine/main.py` | `_prev_mt5_tickets: set[int]` state EKLENDI (__init__) |
| `engine/main.py` | `_check_position_closures()` metodu EKLENDI (cycle adim 2.5, _update_data sonrasi) |
| `engine/main.py` | `_sync_closed_positions(closed_tickets)` metodu EKLENDI |
| `engine/main.py` | `sync_mt5_history_recent()` KORUNDU (API endpoint'leri kullaniyor) |
| `desktop/src/components/TradeHistory.jsx` | 30sn auto-refresh `setInterval` EKLENDI |

### Kaldirilan
- `HISTORY_SYNC_INTERVAL` class attribute (60sn periyodik)
- `_last_history_sync_time` state
- Step 8 periyodik sync cagrisi (`sync_mt5_history_recent(7)`)

### Eklenen
- `_check_position_closures()` — ticket set diff ile pozisyon kapanma tespiti
- `_sync_closed_positions()` — kapanma tetiklemeli history sync (1 gunluk lookback)
- TradeHistory 30sn auto-refresh (DB polling, MT5 polling degil)

### Davranis Degisikligi
- Onceki: Her 60sn MT5 history pollingi (calisma garantisi yok)
- Yeni: Sadece pozisyon kapandiginda sync tetiklenir + TradeHistory 30sn DB polling
- Kapanan pozisyon max ~10sn icinde (cycle suresi) DB'de gorunur

---

## #8 — VİOP Uzlasma Gecikmesi Retry Mekanizmasi (2026-03-05)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-05 |
| **Neden** | #7'deki ticket set diff ile kapanma tespiti calisiyor ama kapanan pozisyonlarin trade kayitlari DB'ye dusmuyordu. F_SOKM ve F_AKSEN kapanmis ama USTAT'ta gorunmuyor. |
| **Kok Neden** | VİOP gunluk uzlasma (settlement) 21:35'te yapiliyor. Pozisyon gun icinde kapandiginda `positions_get()`'ten duser ama OUT deal'leri (entry=1) 21:35'e kadar MT5 history'ye yazilmiyor. `get_history_for_sync()` `if not entries or not exits: continue` ile bu pozisyonlari atliyor. |

### Yaklasim — Pending Retry Mekanizmasi
1. Ticket set diff ile kapanma tespit edildiginde ticket `_pending_closure_tickets`'a eklenir
2. Hemen `get_history_for_sync(days=3)` ile sync denenir
3. Sync sonucunda donen trade'lerin `mt5_position_id`'leri ile pending ticket'lar karsilastirilir
4. Eslesen ticket'lar (hem IN hem OUT deal'i olan) pending'den cikar
5. Eslesmeyen ticket'lar (OUT deal henuz yazilmamis) pending'de kalir
6. Her 6 cycle'da (60sn) pending ticket'lar tekrar denenir
7. 21:35 uzlasma sonrasi OUT deal'ler yazildiginda bir sonraki retry'da cozulur

### Degisiklikler

| Dosya | Ne Degisti |
|-------|-----------|
| `engine/main.py` | `CLOSURE_SYNC_LOOKBACK_DAYS = 3` ve `CLOSURE_RETRY_INTERVAL = 6` sabitleri EKLENDI |
| `engine/main.py` | `_pending_closure_tickets: set[int]` state EKLENDI (__init__) |
| `engine/main.py` | `_check_position_closures()` — pending retry mantigi EKLENDI (yeni kapanma → hemen sync, pending varsa 60sn aralikli retry) |
| `engine/main.py` | `_sync_closed_positions()` — parametresiz hale getirildi, mt5_position_id eslesme ile resolved ticket tracking EKLENDI |

### Davranis Degisikligi
- Onceki (#7): Kapanma tespit edilip sync yapildiginda OUT deal yoksa islem kaybi
- Yeni (#8): OUT deal yoksa ticket pending'de kalir, 60sn aralikli retry ile 21:35 sonrasi otomatik cozulur
- Trade gorulme suresi: Kapanma ani → max 10sn tespit + OUT deal bekleme (21:35'e kadar) + max 60sn retry = uzlasma sonrasi ~70sn

---

## #9 — v13.0: Top 5 Kontrat Seçimi ÜSTAT → OĞUL Taşınması (2026-03-05)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-05 |
| **Commit** | `39b53d8` |
| **Neden** | v13.0 spesifikasyonunda ÜSTAT read-only brain olarak tanımlandı. Top 5 seçimi işlem kararı gerektirdiğinden OĞUL sorumluluğuna alındı |
| **Kök Neden** | Katman sorumluluğu düzeltmesi — ÜSTAT işlem kararı vermemeli, yalnızca gözlem ve raporlama yapmalı |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `engine/ogul.py` | Top 5 seçim mantığı ÜSTAT'tan taşındı: `select_top5()`, `_refresh_scores()`, 5 boyutlu puanlama (teknik/hacim/spread/tarihsel/volatilite) |
| `engine/ogul.py` | Vade geçişi yönetimi: `_get_expiry_status()`, `get_expiry_close_needed()` |
| `engine/ogul.py` | Haber/bilanço filtresi: `set_earnings_dates()`, `set_kap_event()`, `clear_kap_event()`, `set_manual_news_flag()` |
| `engine/ustat.py` | Top 5 kodu kaldırıldı (99 satıra düştü) |
| `engine/main.py` | Cycle adım 5: `self.ogul.select_top5(regime)` çağrısı |

### Taşınan
- 5 boyutlu kontrat puanlama sistemi (teknik, hacim, spread, tarihsel, volatilite)
- Vade geçişi yönetimi (3 gün öncesi yeni işlem yasak, 1 gün öncesi pozisyon kapat)
- Haber/bilanço filtresi (KAP özel durum, bilanço tarihleri)

---

## #10 — v13.0: ÜSTAT Brain Tam İmplementasyon (2026-03-05)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-05 |
| **Commit** | `faf5182` |
| **Neden** | v13.0 spesifikasyonunda ÜSTAT'a 8 brain görevi verildi ama implementasyon yoktu (sadece 99 satır boş sınıf) |
| **Kök Neden** | v13.0 spec yazıldı ama engine kodu güncellenmemişti |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `engine/ustat.py` | 99 → 1213 satır: 8 brain görevi tam implementasyon |
| `api/schemas.py` | `NextDayAnalysis`: `profit_score`, `risk_score`, `total_score` eklendi |
| `api/schemas.py` | `StrategyPool`: `active_profile` eklendi |
| `api/routes/ustat_brain.py` | Placeholder yerine gerçek engine verisi: `get_error_attributions()`, `get_next_day_analyses()`, `get_strategy_pool()`, `get_regulation_suggestions()` |

### Eklenen (ÜSTAT Brain 8 Görev)
1. **Olay takibi** — rejim değişikliği, kill-switch, işlem açma/kapama, uyarı değişimleri
2. **Hata ataması** — BABA hatası (RISK_MISS) vs OĞUL hatası (PROFIT_MISS) ayrımı
3. **Açılmayan işlem analizi** — bloke edilen sinyallerin neden analizi
4. **Ertesi gün analizi** — 4 boyutlu puanlama (sinyal arama, işlem yönetimi, kâr yakalama, risk uyumu)
5. **Strateji havuzu** — rejim bazlı profil eşleme (TREND→trend, RANGE→durağan, VOLATILE→volatil, OLAY→patlama)
6. **Kontrat profilleri** — 90 günlük sembol bazlı performans
7. **Günlük rapor** — otomatik iş günü sonu raporlama
8. **Regülasyon önerileri** — hata/skor bazlı parametre değişiklik önerileri

---

## #11 — v13.0: BABA Risk Aksiyonu Olay Kaydı (2026-03-05)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-05 |
| **Commit** | `6f61f98` |
| **Neden** | v13.0 spesifikasyonunda BABA'nın "izin verdi" aksiyonunu da loglaması istendi. Sadece "kapattı" ve "kapatamadı" loglanıyordu |
| **Kök Neden** | Risk kontrolü sonucu pozitif olduğunda (ticarete izin verildiğinde) olay kaydı düşmüyordu |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `engine/baba.py` | `check_risk_limits()` sonunda `RISK_ALLOWED` event kaydı eklendi (5 dakika dedup ile) |
| `engine/baba.py` | `_last_risk_allowed_log` timestamp eklendi (`__init__`) |
| `engine/baba.py` | Docstring v12.0 → v13.0 güncellendi |
| `engine/ustat.py` | `_check_error_attribution()` içinde `risk_event_types` tuple'ına `"RISK_ALLOWED"` eklendi |

### Eklenen
- `RISK_ALLOWED` event tipi — uyarı aktifken ticarete izin verildiğinde loglanır
- 5 dakika dedup — her 10 sn'de değil, 5 dk'da bir log düşer

---

## #12 — Sistem Sağlık İyileştirmeleri (2026-03-05)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-05 |
| **Commit** | `4bf6cbb` |
| **Neden** | Sistem sağlık analizi sonucu tespit edilen 2 mimari sorun düzeltildi |

### Sorun 1: OĞUL Exception → H-Engine ve ÜSTAT Atlanması

| Alan | Detay |
|------|-------|
| **Kök Neden** | `main.py` process_signals() çağrısı try/except içinde değildi. OĞUL exception atarsa H-Engine (hibrit pozisyon yönetimi) ve ÜSTAT (raporlama) adımları çalışmıyordu |
| **Çözüm** | process_signals() çağrısı try/except ile sarıldı, `OGUL_ERROR` event kaydı eklendi |

### Sorun 2: OĞUL/H-Engine BABA Private Alan Erişimi

| Alan | Detay |
|------|-------|
| **Kök Neden** | OĞUL ve H-Engine, BABA'nın `_kill_switch_level` ve `_risk_state` private alanlarına doğrudan erişiyordu. BABA iç yapısı değiştiğinde sessiz kırılma riski |
| **Çözüm** | BABA'ya 3 public property eklendi: `kill_switch_level`, `daily_trade_count`, `consecutive_losses`. OĞUL ve H-Engine bu property'leri kullanacak şekilde güncellendi |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `engine/main.py` | `process_signals()` çağrısı try/except ile sarıldı |
| `engine/baba.py` | `kill_switch_level`, `daily_trade_count`, `consecutive_losses` public property'leri eklendi |
| `engine/ogul.py` | `baba._kill_switch_level` → `baba.kill_switch_level`, `baba._risk_state` erişimleri property'lere dönüştürüldü |
| `engine/h_engine.py` | `baba._kill_switch_level` → `baba.kill_switch_level` |

### Analiz Sonucu İptal Edilen Öneriler
- `_volatile_reason()` dead code DEĞİL — `baba.py:469`'da kullanılıyor
- RiskVerdict çift çağrı sorun DEĞİL — API ve cycle farklı bağlam, her biri güncel veri almak zorunda

---

## #13 — OĞUL Evrensel Pozisyon Yönetim Sistemi (2026-03-06)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-06 |
| **Neden** | Strateji bazlı pozisyon yönetimi (trend_follow, mean_reversion, breakout — her biri farklı çıkış mantığı) dağınık ve tutarsızdı. 10sn döngüde sinyal üretimi fake sinyal riski taşıyordu. 3 gösterge (RSI, EMA, MACD) hepsi fiyat bazlıydı. |
| **Çözüm** | Strateji bazlı yönetim yerine evrensel (universal) pozisyon yönetimi. İki döngü mimarisi. 4 göstergeli oylama sistemi. Feature flag ile anında geri dönüş imkanı. |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `engine/models/trade.py` | 8 yeni alan: peak_profit, tp1_hit, tp1_price, cost_averaged, initial_volume, breakeven_hit, voting_score, flat_candle_count |
| `engine/database.py` | `_migrate_schema()` metodu: 5 ALTER TABLE (tp1_hit, cost_averaged, initial_volume, peak_profit, breakeven_hit) |
| `engine/mt5_bridge.py` | `close_position_partial(ticket, volume)` metodu: TP1 yarı kapanış için kısmi pozisyon kapatma |
| `engine/ogul.py` | ~50 yeni sabit (BE_ATR_BY_CLASS, TP1_ATR_MULT, TRAIL_ATR_BY_CLASS, PULLBACK, FLAT, LUNCH, RISK vb.) |
| `engine/ogul.py` | `_is_new_m15_candle()`: M15 kapanış kontrolü (iki döngü mimarisi) |
| `engine/ogul.py` | `_calculate_voting()` + `_get_voting_detail()`: RSI + EMA + ATR genişleme + Hacim (4 gösterge, 3/4 çoğunluk) |
| `engine/ogul.py` | `process_signals()` yeniden yazıldı: hızlı döngü (10sn, yönetim) + sinyal döngüsü (M15 kapanış) |
| `engine/ogul.py` | `_manage_position()`: evrensel yönetim (peak_profit, oylama çıkışı, hacim patlaması, breakeven, TP1 yarı kapanış, trailing stop, pullback toleransı, maliyetlendirme) |
| `engine/ogul.py` | `_check_volume_spike()`: 3x ort. hacim algılama ve yön bazlı aksiyon |
| `engine/ogul.py` | `_check_cost_average()`: 5 koşullu maliyetlendirme (max 1 kez, sinyal 3/4+, 1xATR geri çekilme) |
| `engine/ogul.py` | `_check_time_rules()`: yatay piyasa (8 mum < 0.5xATR), son 45dk kâr kapanışı |
| `engine/ogul.py` | `_check_advanced_risk_rules()`: günlük %3 zarar stop, spread anomalisi |
| `engine/ogul.py` | `_manage_active_trades()` router: USE_UNIVERSAL_MANAGEMENT feature flag |
| `engine/ogul.py` | `_execute_signal()`: yarım lot giriş (0.5x), limit fiyat ofseti (0.25xATR) |
| `engine/ogul.py` | `_handle_closed_trade()`: ardışık zarar sayacı (sembol bazlı, günlük sıfırlama) |
| `engine/ogul.py` | `restore_active_trades()`: evrensel alanlar DB'den kurtarılıyor (tp1_hit, breakeven_hit, cost_averaged, peak_profit, initial_volume) |
| `api/schemas.py` | PositionItem: tp1_hit, breakeven_hit, cost_averaged, peak_profit, voting_score |
| `api/routes/positions.py` | `_universal_fields()` helper: OĞUL active_trades'den evrensel alanları oku |
| `api/routes/live.py` | WebSocket position mesajlarına evrensel yönetim alanları eklendi |
| `desktop/src/components/OpenPositions.jsx` | "Yönetim" sütunu: TP1/BE/MA badge'leri + oylama skoru göstergesi |
| `desktop/src/styles/theme.css` | Yönetim badge CSS stilleri (op-mgmt-badge, tp1, be, avg, vote-strong, vote-weak) |

### Eklenen
- 8 yeni metot (ogul.py): _is_new_m15_candle, _calculate_voting, _get_voting_detail, _manage_position, _check_volume_spike, _check_cost_average, _check_time_rules, _check_advanced_risk_rules
- 1 yeni metot (mt5_bridge.py): close_position_partial
- 1 yeni metot (database.py): _migrate_schema
- 1 yeni helper (positions.py): _universal_fields
- ~50 yeni sabit (ogul.py)
- 8 yeni Trade alanı (trade.py)
- 5 yeni DB kolonu
- Desktop "Yönetim" sütunu + badge'ler

### Çıkartılan (Devre dışı, silinmedi)
- `_manage_trend_follow()`, `_manage_mean_reversion()`, `_manage_breakout()` — USE_UNIVERSAL_MANAGEMENT=False ile geri dönülebilir

### Geri Alma Planı
- `USE_UNIVERSAL_MANAGEMENT = False` → eski strateji bazlı yönetim anında aktif
- Eski metotlar silinmedi, yorum satırına alınmadı — feature flag ile bypass ediliyor
- 5 işlem günü stabil çalışma sonrası eski metotlar silinebilir

---

## #14 — Sistem Sağlığı Paneli (2026-03-06)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-06 |
| **Neden** | Canlı trading sırasında döngü performansı, MT5 bağlantı kalitesi, emir süreleri, katman durumları ve hataları tek ekranda izleme ihtiyacı. Bilgi sadece loglarda dağınıktı, operatör için görünürlük yoktu. |
| **Prensip** | Memory-only metrik toplama. DB'ye yazma yok. `time.perf_counter()` overhead ~0.01ms — 10sn döngüde görünmez. |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `engine/health.py` | **YENİ** — HealthCollector sınıfı: thread-safe deque tabanlı metrik toplama. CycleTimings (11 adım zamanlama), OrderTiming (emir süresi), ReconnectEvent dataclass'ları. `snapshot()` ile anlık kopya. |
| `engine/main.py` | HealthCollector import + `__init__`'e `self.health` + `self.mt5._health` eklendi. `_run_single_cycle` her adıma `perf_counter` timer. `record_connection_established()` çağrısı. |
| `engine/mt5_bridge.py` | `_health` attr + heartbeat'te ping kaydı (`record_ping`) + disconnect kaydı (`record_disconnect`) + `send_order`'da emir süresi kaydı (`record_order`) |
| `engine/ustat.py` | `_last_run_time` 1 satır (run_cycle başında ISO format) |
| `api/schemas.py` | `HealthResponse` Pydantic modeli (cycle, mt5, orders, layers, recent_events, system) |
| `api/routes/health.py` | **YENİ** — `GET /api/health` endpoint. Veri kaynakları: health.snapshot(), katman öznitelikleri, db.get_events(), os.path.getsize, get_uptime(), WS istemci sayısı, cache durumu |
| `api/server.py` | `health` import + `include_router(health.router)` kayıt |
| `desktop/src/services/api.js` | `getHealth()` fonksiyonu |
| `desktop/src/components/SystemHealth.jsx` | **YENİ** — 6 bölümlü React sayfası: Döngü performansı (adım barlar + trend grafik), MT5 bağlantı (ping, kopma, reconnect), Emir performansı (son 10, başarı/ret/timeout), Katman durumu (BABA/OĞUL/H-Engine/ÜSTAT kartları), Hata tablosu (severity filtre), Sistem bilgisi (uptime, DB boyut, WS, cache) |
| `desktop/src/components/SideNav.jsx` | NAV_ITEMS'a "Sistem Sağlığı" (🩺) eklendi |
| `desktop/src/App.jsx` | SystemHealth import + `/health` Route |
| `desktop/src/styles/theme.css` | `.sh-*` prefix ile ~300 satır CSS: kartlar, barlar, trend grafik, tablolar, badge'ler, filtre butonları, katman grid |

### Eklenen
- `engine/health.py` dosyası (HealthCollector, CycleTimings, OrderTiming, ReconnectEvent)
- `api/routes/health.py` dosyası (GET /api/health endpoint)
- `desktop/src/components/SystemHealth.jsx` dosyası (6 bölümlü sayfa)
- `getHealth()` API fonksiyonu
- `.sh-*` CSS stilleri (~300 satır)
- SideNav menü öğesi + App Route

### Çıkartılan
- Yok (tamamen additive değişiklik)

### Geri Alma Planı
- Tüm değişiklikler additive — mevcut işlevselliğe dokunmuyor
- `health.py` silinemese bile `HealthCollector` sadece `record_*` çağrılmazsa boş deque tutar
- `_health = None` default olduğu için MT5Bridge standalone kullanımda sorun çıkmaz
- Desktop sayfası kaldırmak için SideNav + App Route + SystemHealth.jsx silinmesi yeterli

---

## #15 — REGIME_STRATEGIES Risk Otoritesi Taşınması (2026-03-07)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-07 |
| **Neden** | `REGIME_STRATEGIES` (hangi rejimde hangi stratejiler çalışır) bir risk kararıdır ama OĞUL'da (`ogul.py`) tanımlıydı. OĞUL kendi risk kararını veriyordu — BABA otoritesini zayıflatıyordu. Ayrıca `BABA.risk_multiplier=0.25` ile OĞUL'un `strategies=[]` kararı çelişiyordu. |
| **Kök Neden** | Mimari: risk kararları iki farklı yerde veriliyordu (BABA + OĞUL). Tek otorite prensibi ihlali. |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `engine/models/regime.py` | `StrategyType` import eklendi. `REGIME_STRATEGIES` dict burada tanımlandı (`RISK_MULTIPLIERS` yanına). `Regime` dataclass'ına `allowed_strategies: list[StrategyType]` alanı eklendi. `__post_init__` rejim tipine göre otomatik dolduruyor. |
| `engine/ogul.py` | Lokal `REGIME_STRATEGIES` dict silindi. `process_signals()` artık `regime.allowed_strategies` okuyor. |

### Eklenen
- `allowed_strategies` alanı (`Regime` dataclass — `regime.py`)
- `REGIME_STRATEGIES` dict (`regime.py` — `RISK_MULTIPLIERS` pattern'i ile)

### Çıkartılan
- `REGIME_STRATEGIES` lokal tanımı (`ogul.py` satır 90-95)

### Geri Alma Planı
- `regime.py`'den `REGIME_STRATEGIES` dict + `allowed_strategies` field + `__post_init__` satırları silinir
- `ogul.py`'ye eski `REGIME_STRATEGIES` dict geri eklenir
- `process_signals()`'da `regime.allowed_strategies` → `REGIME_STRATEGIES.get(regime.regime_type, [])` geri değiştirilir

---

## #16 — Dashboard Düzenleme + Otomatik İşlem Paneli (2026-03-07)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-07 |
| **Neden** | Dashboard'daki "Aktif Rejim + Top 5" bölümü Performans sayfasıyla örtüşüyordu. 3 işlem modu (Manuel, Hibrit, Otomatik) varken otomatik modun ayrı paneli yoktu. Dashboard operasyonel duruma odaklanmalı. |
| **Kök Neden** | Mimari: Dashboard overview + analiz karışmıştı. Otomatik işlem izleme arayüzü eksikti. |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `desktop/src/components/Dashboard.jsx` | "Aktif Rejim + Top 5" sağ card kaldırıldı. "Son İşlemler" tam genişliğe yayıldı. `getTop5()` fetch, `top5` state, `REGIME_META` kaldırıldı. |
| `desktop/src/components/AutoTrading.jsx` | YENİ — Otomatik İşlem Paneli sayfası. 4 stat kart (Durum, Aktif Rejim, Lot Çarpanı, Oto İşlem) + Top 5 Kontrat + Otomatik Pozisyonlar + Son Otomatik İşlemler. |
| `desktop/src/components/SideNav.jsx` | NAV_ITEMS'a `/auto` (Otomatik İşlem Paneli) eklendi — Hibrit'in altına. |
| `desktop/src/App.jsx` | `AutoTrading` import + `/auto` route eklendi. |
| `desktop/src/styles/theme.css` | `.dash-bottom-row` → tek kolon. `.auto-page`, `.auto-stats-row`, `.auto-main-row`, `.auto-card`, `.auto-table` stilleri eklendi. |

### Eklenen
- `AutoTrading.jsx` — Otomatik İşlem Paneli (yeni sayfa)
- `/auto` route ve navigasyon menü öğesi
- `.auto-*` CSS sınıfları

### Çıkartılan
- Dashboard'dan: Aktif Rejim badge, Top 5 kontrat listesi, `REGIME_META` sabit, `getTop5()` API çağrısı

### Geri Alma Planı
- `AutoTrading.jsx` silinir
- `App.jsx` ve `SideNav.jsx`'den `/auto` route/nav öğesi kaldırılır
- `Dashboard.jsx`'e Aktif Rejim + Top 5 JSX geri eklenir (git history'den)
- `.dash-bottom-row` → `grid-template-columns: 1fr 1fr` geri çevrilir

---

## #17 — Risk Baseline Tarih Güncelleme (2026-03-07)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-07 |
| **Neden** | Eski baseline (2026-02-23) test/geliştirme döneminden kalma verileri içeriyordu. Aylık kayıp %13.39 göstererek L2 kill-switch tetiklenmişti. Temiz risk takibi için baseline sıfırlandı. |
| **Kök Neden** | RISK_BASELINE_DATE eski test dönemine ayarlıydı, üretim dönemi risk verileri eskilerle karışıyordu. |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `engine/baba.py` | `RISK_BASELINE_DATE` → `"2026-02-23"` → `"2026-03-07"` |

### Eklenen
- (yok)

### Çıkartılan
- (yok)

### Geri Alma Planı
- `engine/baba.py` satır 126: `RISK_BASELINE_DATE` → `"2026-02-23"` geri çevrilir
