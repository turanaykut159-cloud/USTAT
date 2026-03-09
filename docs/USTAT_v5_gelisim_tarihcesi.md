# ÜSTAT v5.2 — Gelişim Tarihçesi

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

---

## #18 — Açık Pozisyonlar Dashboard'a Birleştirilmesi (2026-03-07)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-07 |
| **Neden** | Dashboard zaten "Açık Pozisyonlar" kartı içeriyordu. Ayrı bir "Açık Pozisyonlar" sayfası gereksiz tekrara neden oluyordu. Kullanıcı tek ekrandan tüm pozisyon yönetimini istedi. |
| **Kök Neden** | Mimari: Aynı veri iki farklı sayfada gösteriliyordu. OpenPositions sayfasında ekstra özellikler (Swap, Yönetim, Süre, Rejim, Hibrit Devir) Dashboard'da eksikti. |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `desktop/src/components/Dashboard.jsx` | Tam özellikli pozisyon tablosu: Swap, Yönetim (TP1/BE/MA/Oylama), Süre, Rejim kolonları eklendi. Hibrit devir butonu eklendi. Tür sınıflandırması API `tur` alanı öncelikli. Hesap şeridi 6 kolona genişletildi (Teminat, Serbest Teminat eklendi). Teminat kullanım badge'i eklendi. `getHybridStatus`, `checkHybridTransfer`, `transferToHybrid` API çağrıları, `useNavigate`, `hybridTickets` state, `elapsed()`, `marginUsagePct()` eklendi. |
| `desktop/src/components/SideNav.jsx` | `/positions` (Açık Pozisyonlar) nav öğesi kaldırıldı. |
| `desktop/src/App.jsx` | `OpenPositions` import ve `/positions` route kaldırıldı. |
| `desktop/src/styles/theme.css` | `.dash-account-strip` → 6 kolon. `.dash-card-header-right`, `.dash-margin-badge` stilleri eklendi. |

### Eklenen
- Dashboard'a: Swap, Yönetim, Süre, Rejim kolonları
- Dashboard'a: "Hibrite Devret" / "Hibritte" butonları
- Dashboard'a: Teminat kullanım yüzdesi badge
- Hesap şeridine: Teminat, Serbest Teminat alanları
- `elapsed()`, `marginUsagePct()` yardımcı fonksiyonlar
- `.dash-card-header-right`, `.dash-margin-badge` CSS sınıfları

### Çıkartılan
- Sidebar'dan: "Açık Pozisyonlar" menü öğesi
- App.jsx'ten: `/positions` route
- `OpenPositions.jsx` dosyası artık kullanılmıyor (referans amaçlı korundu)

### Geri Alma Planı
- `SideNav.jsx`'e `/positions` nav öğesi geri eklenir
- `App.jsx`'e `OpenPositions` import + route geri eklenir
- `Dashboard.jsx` git history'den eski versiyona dönülür

---

## #19 — Peak Equity Doğrulama Eşiği Düzeltmesi (2026-03-07)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-07 |
| **Neden** | RISK_BASELINE_DATE güncellendikten sonra eski peak_equity DB'de kaldı. Doğrulama eşiği (1.5x) çok gevşekti — eski peak sıfırlanmadı, drawdown %13.39 olarak kalmaya devam etti. |
| **Kök Neden** | `_validate_peak_equity()` koşulu `stored_peak > max_eq * 1.5` — peak baseline sonrası max'ın 1.5 katından büyük olmalıydı. Gerçek fark (~%13) bu eşiğin altında kalıyordu. |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `engine/data_pipeline.py` | `_validate_peak_equity()`: koşul `stored_peak > max_eq * 1.5` → `stored_peak > max_eq` olarak güncellendi |

### Eklenen
- (yok)

### Çıkartılan
- (yok)

### Geri Alma Planı
- `engine/data_pipeline.py` satır 632: koşul `stored_peak > max_eq` → `stored_peak > max_eq * 1.5` geri çevrilir

---

## #20 — İşlem Geçmişi Baseline Filtresini Kaldır (2026-03-07)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-07 |
| **Neden** | `RISK_BASELINE_DATE` trades API'sinde de filtre olarak kullanılıyordu. Baseline güncellenince işlem geçmişi boş görünüyordu. Baseline sadece risk hesaplamalarını etkilemeli. |
| **Kök Neden** | `trades.py` endpoint'leri `since=RISK_BASELINE_DATE` parametresiyle veritabanı sorgusu yapıyordu — işlem gösterimi risk tarihine bağlanmıştı. |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `api/routes/trades.py` | `get_trades()` ve `get_trade_stats()` sorgularından `since=RISK_BASELINE_DATE` kaldırıldı. `RISK_BASELINE_DATE` import'u kaldırıldı. |

### Eklenen
- (yok)

### Çıkartılan
- `trades.py`'den `RISK_BASELINE_DATE` import ve filtresi

### Geri Alma Planı
- `trades.py`'ye `from engine.baba import RISK_BASELINE_DATE` import'u geri eklenir
- `get_trades` ve `get_trade_stats` sorgularına `since=RISK_BASELINE_DATE` parametresi geri eklenir

---

## #21 — Hibrit İşlem Türü Sınıflandırma (2026-03-07)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-07 |
| **Neden** | Hibrit motora devredilen ve kapanan pozisyonlar İşlem Geçmişi'nde "Manuel" olarak görünüyordu. H-Engine `trades` tablosundaki `strategy` alanını hiç güncellemiyordu. MT5 sync tüm işlemleri "manual" olarak etiketliyordu. |
| **Kök Neden** | 3 ayrı eksiklik: (1) `transfer_to_hybrid()` trades.strategy güncellemiyordu (2) Sync mevcut kaydı güncellerken hibrit kontrolü yoktu (3) Sync yeni kayıt eklerken hibrit kontrolü yoktu (4) UI'da `"hibrit"` strategy tanınmıyordu |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `engine/h_engine.py` | `transfer_to_hybrid()`: DB insert sonrası `trades.strategy='hibrit'` güncelleme eklendi |
| `engine/database.py` | `sync_mt5_trades()` path 1 (mevcut kayıt): `hybrid_positions` kontrolü, eşleşirse `strategy='hibrit'` |
| `engine/database.py` | `sync_mt5_trades()` path 3 (yeni kayıt): `hybrid_positions` kontrolü, eşleşirse `strategy='hibrit'` |
| `desktop/src/components/TradeHistory.jsx` | `isHybrid` kontrolüne `stratLower === 'hibrit'` eklendi |

### Eklenen
- Hibrit pozisyon tespiti (3 noktada: devir, sync mevcut, sync yeni)
- UI'da `"hibrit"` strategy tanıma

### Çıkartılan
- (yok)

### Geri Alma Planı
- `h_engine.py`: `transfer_to_hybrid()`'deki strategy UPDATE bloğu kaldırılır
- `database.py`: `sync_mt5_trades()`'deki hibrit kontrol blokları kaldırılır, eski UPDATE/INSERT'e dönülür
- `TradeHistory.jsx`: `isHybrid` koşulundan `stratLower === 'hibrit'` kaldırılır

---

## #22 — Event-Driven İşlem Geçmişi + Tarih Filtresi (2026-03-07)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-07 |
| **Neden** | İşlem Geçmişi sayfası 30sn'de bir 3 API çağrısı yapıyordu (trades + stats + performance). Kapanmış işlemler değişmediğinden gereksiz yüktü. Ayrıca işlem geçmişi 01.02.2026'dan başlamalıydı. Dashboard da 10sn'de bir 7 API çağrısı yapıyordu. |
| **Kök Neden** | Polling-tabanlı mimari: veri değişip değişmediğine bakılmadan sabit aralıklarla API çağrılıyordu. WebSocket altyapısı mevcuttu ama sadece equity/position/status için kullanılıyordu. |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `engine/event_bus.py` | **YENİ** — Thread-safe event bus: `on()`, `off()`, `emit()`, `drain()` fonksiyonları. Engine thread'den emit, async WS thread'den drain. |
| `engine/ogul.py` | `_handle_closed_trade()` sonuna `event_bus.emit("trade_closed", {...})` eklendi |
| `engine/h_engine.py` | `_finalize_close()` sonuna `event_bus.emit("trade_closed", {..., source: "hybrid"})` eklendi |
| `engine/main.py` | `_sync_closed_positions()`: resolved ticket'lar için `event_bus.emit("position_closed", {...})` eklendi |
| `api/routes/live.py` | Global `_event_drain_loop` task: 1sn'de bir event bus drain → tüm WS bağlantılarına broadcast. `broadcast()` artık `[msg]` formatında gönderir (client uyumu). |
| `api/routes/trades.py` | `get_trades()` endpoint'ine `since` query parametresi eklendi (YYYY-MM-DD) |
| `desktop/src/components/TradeHistory.jsx` | 30sn polling kaldırıldı → WS `trade_closed`/`position_closed` event-driven. `since=2026-02-01` varsayılan filtre. `connectLiveWS` ile WS dinleme. |
| `desktop/src/components/Dashboard.jsx` | REST polling 10sn → 30sn'ye düşürüldü. WS handler'a `trade_closed`/`position_closed` dinleme eklendi → trades/stats anında yenilenir. |

### Eklenen
- `engine/event_bus.py` — Hafif event bus modülü
- 3 emit noktası: ogul.py, h_engine.py, main.py
- WS event drain loop (live.py)
- Trades API `since` parametresi
- TradeHistory WS event-driven yenileme
- Dashboard WS trade event dinleme

### Çıkartılan
- TradeHistory 30sn `setInterval` polling
- Dashboard 10sn polling (30sn'ye uzatıldı)

### Geri Alma Planı
- `event_bus.py` silinir
- `ogul.py`, `h_engine.py`, `main.py`'deki emit satırları kaldırılır
- `live.py`'deki `_event_drain_loop` ve global task yönetimi kaldırılır, eski `_push_loop` geri konulur
- `trades.py`'den `since` parametresi kaldırılır
- `TradeHistory.jsx`'e `setInterval(fetchData, 30_000)` geri eklenir, WS import/handler kaldırılır
- `Dashboard.jsx`'de polling 10sn'ye döndürülür, WS'den `trade_closed` handler kaldırılır

---

## #23 — Dashboard İstatistikleri 01.02.2026 Tarih Filtresi (2026-03-07)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-07 |
| **Neden** | Dashboard NET KÂR/ZARAR ve diğer istatistikler tüm kapanmış işlemleri hesaba katıyordu; kullanıcı 01.02.2026 itibariyle hesaplama istiyor |
| **Kök Neden** | `/api/trades/stats` endpoint'i `db.get_trades()` çağrısında `since` parametresi kullanmıyordu; tüm geçmiş dahil ediliyordu |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `api/routes/trades.py` | `get_trade_stats()` endpoint'ine `since` query parametresi eklendi (varsayılan: `"2026-02-01"`) |
| `api/routes/trades.py` | `db.get_trades(limit=limit)` → `db.get_trades(since=since, limit=limit)` |

### Eklenen
- `/trades/stats` endpoint'inde `since` parametresi — Dashboard istatistikleri artık 01.02.2026 sonrasını hesaplıyor

### Davranış Değişikliği
- Önceki: Tüm kapanmış işlemlerin PnL toplamı (eski -482K zararlı işlemler dahil)
- Yeni: 01.02.2026 ve sonrasındaki işlemler dahil; eski işlemler istatistik dışı

---

## #24 — Profit Factor Baseline Tutarsızlığı Düzeltmesi (2026-03-07)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-07 |
| **Neden** | Dashboard'da Profit Factor "—" (çizgi) gösteriyordu |
| **Kök Neden** | `performance.py` endpoint'i `RISK_BASELINE_DATE = "2026-03-07"` (bugün) kullanıyordu; bugün kapanmış işlem yok → gross_loss=0 → profit_factor=0 → "—" gösterimi. `/trades/stats` ise `"2026-02-01"` kullanıyordu — tutarsızlık. |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `api/routes/performance.py` | `RISK_BASELINE_DATE` import'u kaldırıldı → `_STATS_BASELINE = "2026-02-01"` sabit tanımlandı |
| `api/routes/performance.py` | `db.get_trades(since=RISK_BASELINE_DATE)` → `db.get_trades(since=_STATS_BASELINE)` |
| `api/routes/performance.py` | `get_daily_end_snapshots(since=RISK_BASELINE_DATE)` → `since=_STATS_BASELINE` |

### Eklenen
- `_STATS_BASELINE` sabiti — `/trades/stats` ve `/performance` endpoint'leri artık aynı baseline kullanıyor

### Davranış Değişikliği
- Önceki: Profit Factor bugünün tarihinden hesaplanıyor → veri yok → "—"
- Yeni: 01.02.2026 sonrası tüm işlemlerden hesaplanıyor → 0.77 (doğru değer)

---

## #25 — Stres Testi Bulguları: 6 Düzeltme (2026-03-07)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-07 |
| **Neden** | Kapsamlı stres testi ve sağlık analizinde tespit edilen 6 gerçek sorunun düzeltilmesi |
| **Kök Neden** | WebSocket reconnect eksikliği, sessiz hata yutma, equity staleness kontrolü yokluğu, dead code, onay mekanizması görünürlüğü, engine stop davranışı |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `desktop/src/services/api.js` | `connectLiveWS()` exponential backoff ile otomatik reconnect (1s→30s), `onStateChange` callback, `getState()` API |
| `api/routes/trades.py` | Logger eklendi; 3 bare `except: pass` → `logger.warning(...)` |
| `api/routes/performance.py` | Logger eklendi; 1 bare `except: pass` → `logger.warning(...)` |
| `api/routes/health.py` | Logger eklendi; 2 bare `except: pass` → `logger.debug/warning(...)` |
| `api/routes/risk.py` | Logger eklendi; 1 bare `except: pass` → `logger.exception(...)` (en kritik — risk limitleri) |
| `api/routes/live.py` | Equity WS mesajına `"ts": time.time()` timestamp eklendi |
| `desktop/src/components/Dashboard.jsx` | Equity staleness kontrolü (10sn eşik), stale banner ("⚠ Veri eski" / "⚠ Bağlantı koptu"), stale durumda REST fallback, onaylanmamış trade badge ("N onaysız") |
| `desktop/src/components/TradeHistory.jsx` | `syncTrades` import + "⟳ MT5 Senkronize Et" butonu, sync sonuç mesajı |
| `desktop/src/styles/theme.css` | `.dash-stale-banner`, `.dash-unapproved-badge`, `.th-sync-btn`, `.th-sync-result` stilleri |
| `engine/main.py` | `stop(close_positions=False)` opsiyonel parametre; True ise BABA `_close_all_positions()` ile kapatma |

### Eklenen
- WebSocket auto-reconnect (exponential backoff: 1s → 2s → 4s → 8s → 16s → 30s max)
- Equity staleness kontrolü + banner (10sn eşik, REST fallback)
- WS bağlantı durumu göstergesi (connected / reconnecting / disconnected)
- 7 API route'ta proper exception logging
- TradeHistory'de "MT5 Senkronize Et" butonu (syncTrades artık kullanılıyor)
- Dashboard'da onaylanmamış trade sayısı badge'i
- Engine stop'ta opsiyonel pozisyon kapatma mekanizması

### Çıkartılan
- 7 bare `except: pass` bloğu (sessiz hata yutma kaldırıldı)

---

## #26 — Sistem Sağlığı: 8 Sorun Düzeltme (2026-03-07)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-07 |
| **Neden** | Sistem sağlığı analizi sonrası tespit edilen 8 sorunun düzeltilmesi: kritik event kaybı, UI bloklanma, bağlantı yönetimi, event loop bloklama, eksik veriler. |
| **Kök Neden** | ENGINE_STOP event'i DB kapandıktan sonra yazılıyor (sessiz kayıp), window.alert UI'yı kilitliyor, WS broadcast çift silme riski, engine crash sessiz, shutdown thread beklemiyor, sync DB sorgusu async loop'u blokluyor, margin WS'te yok, push loop sonsuz retry. |

| # | Dosya | Değişiklik |
|---|-------|-----------|
| 1 | `engine/main.py` | `_log_event_safe("ENGINE_STOP")` çağrısı `db.close()` öncesine taşındı |
| 2 | `desktop/src/components/Dashboard.jsx` | 5 `window.alert()` → inline banner + ConfirmModal ile değiştirildi |
| 3 | `api/routes/live.py` | `broadcast()` çift silme guard'ı eklendi |
| 4 | `api/server.py` | Engine watchdog task eklendi (crash loglanır) |
| 5 | `api/server.py` | Shutdown'da engine thread timeout ile bekleniyor (30sn) |
| 6 | `api/routes/live.py` | Risk snapshot cache (5sn TTL) + `asyncio.to_thread()` |
| 7 | `api/routes/live.py` + `Dashboard.jsx` | Margin/free_margin WS equity mesajına eklendi |
| 8 | `api/routes/live.py` | Push loop circuit breaker (log throttle + artan backoff) |
| 9 | `desktop/src/styles/theme.css` | `.dash-api-error-banner` stili eklendi |
| 10 | `api/server.py` | `get_event_loop()` → `get_running_loop()` (deprecation) |

### Eklenen
- API hata banner'ı (kırmızı, otomatik temizlenir)
- ConfirmModal ile hata gösterimi (window.alert yerine)
- Engine crash watchdog task (pasif gözlemci)
- Shutdown'da engine thread await mekanizması
- Risk snapshot 5sn cache (event loop bloklama çözümü)
- WS equity mesajında margin/free_margin alanları
- Push loop log throttle (ilk 5 + her 60.)
- Push loop artan backoff (5s → 10s → ... → max 30s)

### Çıkartılan
- 5 `window.alert()` çağrısı (blocking UI)
- Sync DB sorgusu doğrudan event loop üzerinde (her 2sn)

---

## #27 — OĞUL İşlem Yapmama: 7 Engel Düzeltmesi (2026-03-07)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-07 |
| **Neden** | OĞUL hiç işlem yapamıyor. Derinlemesine log analizi: Kill-Switch L2 kısır döngüsü (851 cycle risk_ok=False), ADX ölü bölge (20-25), lot floor(0), yetersiz Top5, rejim-strateji uyumsuzluğu |
| **Kök Neden** | 6 farklı engel zinciri: (1) daily_pnl eski günden kalma → L2 sürekli tekrar aktif, (2) vol_min floor yok → rounding lot=0, (3) MR_ADX<20 ama rejim RANGE+ADX=30, (4) ENTRY_LOT_FRACTION=0.5 küçük lotları sıfıra düşürüyor, (5) Top5 ortalama filtresi 2 kontraya düşüyor, (6) bias nötr ×0.7 çok agresif |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `engine/baba.py` | Fix 1: `daily_reset_equity` ile günlük PnL bazı reset anına taşındı → L2 kısır döngü kırıldı |
| `engine/baba.py` | Fix 2: `calculate_position_size()` sonunda `vol_min` floor eklendi → lot=0 koruması |
| `engine/baba.py` | Fix 7: `detect_regime()` ADX çapraz kontrol → RANGE+yüksek ADX ise TREND override |
| `engine/ogul.py` | Fix 2: `_execute_signal()` ENTRY_LOT_FRACTION sonrası `vol_min` floor |
| `engine/ogul.py` | Fix 3: `MR_ADX_THRESHOLD` 20→25 — ADX ölü bölge kapatıldı |
| `engine/ogul.py` | Fix 4: `ENTRY_LOT_FRACTION` lot≤2 ise 1.0 (yarılama atla) |
| `engine/ogul.py` | Fix 5: Top5 minimum 3 kontrat garantisi |
| `engine/ogul.py` | Fix 6: Bias nötr çarpanı 0.7→0.85 |

### Eklenen
- `daily_reset_equity` risk state alanı (baba.py)
- `vol_min` lot floor koruması (baba.py + ogul.py)
- Rejim ADX çapraz kontrol (baba.py)
- Top5 minimum kontrat garantisi (ogul.py)
- Dinamik ENTRY_LOT_FRACTION mantığı (ogul.py)

### Çıkartılan
- ADX 20-25 ölü bölge (MR_ADX 20→25 ile kapatıldı)
- L2 kısır döngü (daily_reset_equity ile çözüldü)
- Bias nötr %30 cezası (%15'e düşürüldü)

---

## #28 — OĞUL Aktivite Kartı + USDTRY Sembol Düzeltmesi (2026-03-07)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-07 |
| **Neden** | OĞUL neden işlem açmıyor/açamıyor sorusu UI'dan izlenemiyor. USDTRY tick hatası her cycle loglanıyor. |
| **Kapsam** | Yeni API endpoint + desktop kart + USDTRY dinamik sembol çözümleme |

### Değişiklikler

| Dosya | Değişiklik |
|-------|-----------|
| `api/routes/ogul_activity.py` | **YENİ** — `GET /api/ogul/activity` endpoint: oylama detayı, strateji parametreleri, açılamayan işlem sayaçları |
| `api/schemas.py` | `OgulActivityResponse`, `OgulSignalItem`, `OgulUnopenedItem` schema'ları |
| `api/server.py` | `ogul_activity` router kaydı |
| `desktop/src/components/AutoTrading.jsx` | OĞUL Aktivite kartı: sayaçlar, 4-gösterge oylama tablosu, açılamayan işlemler listesi |
| `desktop/src/services/api.js` | `getOgulActivity()` fonksiyonu |
| `desktop/src/styles/theme.css` | `.ogul-*` CSS sınıfları (kart, sayaçlar, oylama chip'leri, skor renkleri) |
| `engine/mt5_bridge.py` | USDTRY dinamik sembol çözümleme (`_resolve_symbols` → `USDTRY_YAKINVADE` eşlemesi) |

### Eklenen
- `/api/ogul/activity` endpoint (ogul_activity.py)
- Oğul Aktivite kartı: Tarama/Sinyal/Reddedilen sayaçları + 4-gösterge oylama tablosu (RSI, EMA, ATR, Hacim)
- USDTRY dinamik sembol çözümleme (GCM'deki `USDTRY_YAKINVADE` otomatik bulunuyor)
- `getOgulActivity()` API fonksiyonu (api.js)

### Çıkartılan
- Hardcoded `"USDTRY"` sembol adı (dinamik çözümleme ile değiştirildi)

---

## #29 — Kod Merkezileştirme + Ekran İnceleme Düzeltmeleri (2026-03-08)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-08 |
| **Neden** | Ekran-ekran canlı inceleme sırasında tespit edilen sorunlar: mükerrer formatMoney/formatPrice/pnlClass/elapsed fonksiyonları (8 bileşende tekrar), mükerrer Risk Parametreleri bölümü, stale VERSION/BUILD_DATE, hardcoded baseline tarihleri, eksik `since` parametresi |
| **Kapsam** | Frontend yardımcı merkezileştirme, backend sabit merkezileştirme, 13 dosya değişikliği (43 ekleme, 283 silme) |

### Değişiklikler

| Dosya | Değişiklik |
|-------|-----------|
| `desktop/src/utils/formatters.js` | **YENİ** — `formatMoney`, `formatPrice`, `pnlClass`, `elapsed` merkezi yardımcılar |
| `desktop/src/components/Dashboard.jsx` | Yerel formatMoney/formatPrice/pnlClass/elapsed kaldırıldı → import |
| `desktop/src/components/AutoTrading.jsx` | Yerel formatMoney/formatPrice/pnlClass kaldırıldı → import |
| `desktop/src/components/TopBar.jsx` | Yerel formatMoney kaldırıldı → import |
| `desktop/src/components/HybridTrade.jsx` | Yerel formatMoney/formatPrice/pnlClass/elapsed kaldırıldı → import |
| `desktop/src/components/ManualTrade.jsx` | Yerel formatMoney/formatPrice kaldırıldı → import (`formatPrice(val, 4, 4)` VİOP hassasiyeti korundu) |
| `desktop/src/components/OpenPositions.jsx` | Yerel formatMoney/formatPrice/pnlClass/elapsed kaldırıldı → import |
| `desktop/src/components/RiskManagement.jsx` | Yerel formatMoney kaldırıldı → import; `.toFixed(0)` → `.toFixed(1)` düzeltmesi |
| `desktop/src/components/TradeHistory.jsx` | Yerel formatMoney/formatPrice/pnlClass kaldırıldı → import |
| `desktop/src/components/Settings.jsx` | Risk Parametreleri bölümü kaldırıldı (mükerrer); VERSION `5.1.0`→`5.1`; BUILD_DATE güncellendi; SEVERITY_ORDER dead code kaldırıldı |
| `desktop/src/components/Performance.jsx` | `getTrades` çağrısına `since: STATS_BASELINE` eklendi |
| `desktop/src/services/api.js` | `STATS_BASELINE = '2026-02-01'` sabiti; `getTradeStats` fonksiyonuna `since` parametresi |
| `api/constants.py` | **YENİ** — `STATS_BASELINE = "2026-02-01"` backend sabiti |
| `api/routes/performance.py` | Yerel `_STATS_BASELINE` → `api.constants.STATS_BASELINE` import |
| `api/routes/trades.py` | Hardcoded `"2026-02-01"` → `STATS_BASELINE` import |

### Eklenen
- `desktop/src/utils/formatters.js` — 4 merkezi yardımcı fonksiyon
- `api/constants.py` — Backend sabit dosyası
- `STATS_BASELINE` sabiti (frontend + backend)
- `getTradeStats` fonksiyonuna explicit `since` parametresi

### Çıkartılan
- 8 bileşendeki ~120 satır tekrarlanan yardımcı fonksiyon
- Settings.jsx Risk Parametreleri bölümü (Risk Yönetimi sayfasıyla mükerrerdi)
- Settings.jsx SEVERITY_ORDER dead code
- 4 adet hardcoded `"2026-02-01"` string (frontend + backend)

---

## #30 — Versiyon Yükseltme: v5.1 → v5.2 (2026-03-08)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-08 |
| **Neden** | v5.1 commit'inden (52299aa, 2026-03-05) bu yana kümülatif değişiklik %41,2 (14.817 satır / 36.000 baz). %10 eşiği aşıldı — versiyon yükseltme zorunlu. |
| **Kapsam** | 30 dosyada versiyon referansı güncelleme (sabitler, UI, JSDoc, başlatıcılar, paket meta) |

### Değişiklikler

| Kategori | Dosya Sayısı | Açıklama |
|----------|-------------|----------|
| Aktif sabitler | 5 | `package.json`, `Settings.jsx`, `api/server.py`, `engine/__init__.py` — VERSION/API_VERSION |
| Kullanıcı-görünür UI | 5 | `main.js` (APP_TITLE + Splash), `index.html`, `LockScreen.jsx`, `TopBar.jsx` |
| Başlatıcılar | 3 | `start_ustat.py`, `.bat`, `.vbs` |
| JSDoc/Docstring | 17 | Tüm React bileşenleri + services + utils + theme.css |
| Gelişim tarihçesi | 1 | Başlık v5.1 → v5.2 |

### Eklenen
- v5.2 versiyon numarası (tüm referans noktaları)

### Çıkartılan
- v5.1 versiyon numarası (tarihsel referanslar docs/ içinde korundu)

---

## #31 — Bağımsız Manuel İşlem Motoru (ManuelMotor) (2026-03-07)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-07 |
| **Neden** | Manuel işlemler OĞUL'un `active_trades`'ine girip otomatik yönetim alıyordu (trailing stop, TP1, breakeven, rejim kapanışı). Kullanıcı pozisyon üzerinde kontrol kaybediyordu. |
| **Kök Neden** | Manuel ve otomatik işlemler aynı `active_trades` dict'inde yönetiliyordu. `_manage_active_trades()` strateji ayrımı yapmıyordu. |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `engine/manuel_motor.py` | **YENİ** — Bağımsız ManuelMotor sınıfı (~530 satır): check, open, sync, risk score |
| `engine/main.py` | ManuelMotor oluşturma, cross-motor referanslar, cycle'a sync ekleme, restore ekleme |
| `engine/ogul.py` | `check_manual_trade()` + `open_manual_trade()` silindi (~350 satır), ManuelMotor netting check |
| `engine/health.py` | `CycleTimings.manuel_sync_ms` alanı eklendi |
| `api/deps.py` | `get_manuel_motor()` eklendi |
| `api/schemas.py` | `ManualRiskScoresResponse`, `PositionItem.risk_score` alanları eklendi |
| `api/routes/manual_trade.py` | `get_ogul()` → `get_manuel_motor()`, yeni `GET /manual-trade/risk-scores` endpoint |
| `api/routes/positions.py` | Strategy lookup ManuelMotor + OĞUL, risk_score zenginleştirmesi |
| `desktop/src/services/api.js` | `getManualRiskScores()` fonksiyonu eklendi |
| `desktop/src/components/OpenPositions.jsx` | "Risk" sütunu (yeşil/sarı/kırmızı badge + skor) |
| `desktop/src/components/ManualTrade.jsx` | Açık pozisyon risk göstergesi paneli (4 boyut + overall) |

### Eklenen
- `engine/manuel_motor.py` — ManuelMotor sınıfı (bağımsız active_trades, risk score hesaplama)
- `GET /api/manual-trade/risk-scores` endpoint
- Risk göstergesi: SL/ATR, rejim, K/Z, sistem riski → yeşil/sarı/kırmızı + 0-100 skor
- Cross-motor netting: OĞUL ↔ ManuelMotor ↔ H-Engine çift yönlü kontrol

### Çıkartılan
- `Ogul.check_manual_trade()` (~145 satır) → ManuelMotor'a taşındı
- `Ogul.open_manual_trade()` (~200 satır) → ManuelMotor'a taşındı

---

## #32 — 50 Kişilik Uzman Ekip Raporu Uygulaması (2026-03-08)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-08 |
| **Neden** | 50 kişilik uzman ekip USTAT v5.2'yi 8 departmanda analiz etti. 28 tespitten 23 tam doğru, 3 kısmen doğru, 2 yanlış. Doğrulanmış 25 tespit 2 fazda uygulandı. |
| **Kapsam** | FAZ 1: 6 kritik düzeltme. FAZ 2: 11 güçlendirme. Toplam 17 iş kalemi. |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `config/default.json` | `hard_drawdown_pct` 0.12→0.15, eksik risk parametreleri eklendi (7 yeni alan) |
| `engine/main.py` | `RiskParams` config'den yüklenir (boş init yerine), DB backup çağrısı, günlük DB temizlik zamanlayıcısı |
| `engine/baba.py` | Floating loss formülü düzeltildi (`|pnl|/equity`), fake sinyal eşiği 3→5, L3 akıllı kapatma (zarardakiler önce), baseline date config'den okunuyor, ring buffer dinamik boyut, günlük reset senkron snapshot, rejim oylamasında likidite ağırlığı |
| `engine/ogul.py` | ADX hysteresis geçiş bölgesi (22-28), Top 5 tarihsel skor minimum eşik 3→10 |
| `engine/database.py` | `backup()` metodu (otomatik yedekleme, son 5 tut) |
| `desktop/src/components/OpenPositions.jsx` | 4× `window.alert()` → ConfirmModal |
| `desktop/src/components/HybridTrade.jsx` | 1× `window.alert()` → ConfirmModal |
| `desktop/src/components/ErrorBoundary.jsx` | Yeni: React Error Boundary bileşeni |
| `desktop/src/App.jsx` | ErrorBoundary ile Routes sarmalandı |
| `desktop/src/components/TradeHistory.jsx` | Client-side sayfalama (50/sayfa) |
| `desktop/src/styles/theme.css` | Sayfalama stilleri |
| `start_ustat.py` | `--prod` flag desteği, production build fonksiyonu |

### Eklenen
- `ErrorBoundary.jsx` — React hata sınırı bileşeni
- `database.py:backup()` — otomatik DB yedekleme
- `main.py:_run_daily_cleanup()` — günlük eski veri temizliği
- `baba.py:_try_close_position()` — tek pozisyon kapatma yardımcısı
- `baba.py:_still_above_hard_drawdown()` — drawdown kontrol yardımcısı
- ADX hysteresis sabitleri: `TF_ADX_HARD/SOFT`, `MR_ADX_HARD/SOFT`
- TradeHistory sayfalama UI + CSS
- `start_ustat.py:build_frontend()` — Vite production build

### Çıkartılan
- `RISK_BASELINE_DATE` sabit → `_risk_baseline_date` instance değişkeni (config'den)
- `SPREAD_HISTORY_LEN` sabit → `_spread_history_len` dinamik (cycle_interval'a göre)
- 5× `window.alert()` çağrısı → ConfirmModal

---

## #33 — İşlem Geçmişi: Filtre ve Sıralama İyileştirmesi (2026-03-08)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-08 |
| **Neden** | Sıralama butonları (En Kârlı/Zararlı/Uzun/Kısa) tabloyu sıralamıyor, sadece tek satıra scroll yapıyordu. Zaman filtresi dropdown olarak gizliydi, hızlı erişim buton olmalıydı. |
| **Kök Neden** | Butonlar `scrollToTrade()` çağırıyordu (stats API'den gelen tek işleme scroll). Gerçek sıralama mantığı yoktu. |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `desktop/src/components/TradeHistory.jsx` | Zaman filtresi dropdown → buton satırı (Varsayılan / Bugün / Bu Hafta / Bu Ay / 3 Ay / 6 Ay / 1 Yıl); sıralama butonları gerçek sıralama yapacak şekilde yeniden yazıldı (sortMode state + sortedTrades useMemo); Varsayılan butonu tüm filtreleri sıfırlar; zaman butonuna tıklayınca diğer filtreler sıfırlanır |
| `desktop/src/styles/theme.css` | `.th-period-btns`, `.th-period-btn`, `.th-period-btn--active`, `.th-sort-btns`, `.th-sort-btn`, `.th-sort-btn--active` stilleri eklendi; eski `.th-quick-btns`, `.th-quick-btn` stilleri kaldırıldı |

### Eklenen
- `sortMode` state: `null | pnl_desc | pnl_asc | duration_desc | duration_asc`
- `sortedTrades` useMemo: filtrelenmiş verileri seçilen moda göre sıralar
- `tradeDurationMs()` yardımcı fonksiyonu: işlem süresini ms cinsinden hesaplar
- `resetFilters()`: tüm filtreleri varsayılana döndürür
- `handlePeriodClick()`: zaman butonuna tıklanınca periyod ayarlar + diğer filtreleri sıfırlar
- Zaman buton satırı: Varsayılan | Bugün | Bu Hafta | Bu Ay | 3 Ay | 6 Ay | 1 Yıl
- Sıralama toggle: aynı butona tekrar tıklanınca sıralama kapanır

### Çıkartılan
- `scrollToTrade()` fonksiyonu ve `highlight` state (tek satıra scroll mantığı)
- `PERIOD_OPTIONS` dropdown sabiti → `PERIOD_BUTTONS` buton sabiti ile değiştirildi
- Dönem dropdown (`<select>`) kaldırıldı

---

## #34 — Engine Başlatma Hatası Düzeltmesi: RISK_BASELINE_DATE (2026-03-08)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-08 |
| **Neden** | Uygulama yeniden başlatıldığında "Bağlantı Yok!" hatası — engine ayağa kalkamıyordu. |
| **Kök Neden** | Remote commit `6c909f1` (#32 — Uzman Ekip Raporu) `baba.py`'daki `RISK_BASELINE_DATE` sabitini `_DEFAULT_RISK_BASELINE_DATE` olarak yeniden adlandırmış ama `data_pipeline.py:611`'deki import güncellenmemiş. `ImportError` → engine oluşturulamıyor → `mt5_connected: false` → "Bağlantı Yok!". |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `engine/baba.py` | `RISK_BASELINE_DATE = _DEFAULT_RISK_BASELINE_DATE` alias eklendi (satır 125) — `data_pipeline.py` geriye uyumluluğu sağlandı |

### Eklenen
- `RISK_BASELINE_DATE` public alias (1 satır) — `data_pipeline._validate_peak_equity()` import uyumu

### Çıkartılan
- Yok

---

## #35 — System Monitor: Sistem Sağlığı + Günlük Birleştirme (2026-03-09)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-09 |
| **Neden** | Sistem Sağlığı ve Sistem Günlüğü iki ayrı sayfada dağınıktı; kullanıcı tüm izleme verilerini tek terminale benzer bir panelde görmek istedi. Referans tasarım (SİSTEM SAĞLIĞI.txt) temel alındı, simülasyon verisi gerçek API'ye dönüştürüldü. |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `desktop/src/components/Monitor.jsx` | **YENİ** (520 satır) — Tek sayfa sistem izleme paneli: Header, 6 stat kart, modül mimarisi diyagramı (BABA→OĞUL→ÜSTAT→H-ENGINE→MANUEL→HİBRİT), emir akış tablosu, log akışı, performans barları, risk & kill-switch paneli. 6 API endpoint'ten Promise.all ile 3sn poll. |
| `desktop/src/components/SystemHealth.jsx` | **SİLİNDİ** (545 satır) — tüm verisi Monitor'e taşındı |
| `desktop/src/components/SystemLog.jsx` | **SİLİNDİ** (270 satır) — tüm verisi Monitor'e taşındı |
| `desktop/src/App.jsx` | `/health` + `/logs` route'ları kaldırıldı → `/monitor` eklendi, import'lar güncellendi |
| `desktop/src/components/SideNav.jsx` | 2 menü öğesi (Sistem Sağlığı, Sistem Günlüğü) → 1 menü öğesi (📡 System Monitor) |
| `desktop/src/styles/theme.css` | 679 satır `.sh-*` + `.sl-*` CSS kaldırıldı → 13 satır `.mn-page` CSS eklendi |

### Eklenen
- `Monitor.jsx` — Terminal tarzı koyu arka plan, modül bazlı renk kodları, animasyonlu akış okları
- `.mn-page` CSS sınıfı
- Modül hata sayacı (event'lerden türetme)
- Kill-switch seviye göstergesi (L1/L2/L3 aktif vurgu)
- VİOP piyasa durumu (09:30–18:15 seans saati kontrolü)

### Çıkartılan
- `SystemHealth.jsx` (545 satır)
- `SystemLog.jsx` (270 satır)
- `.sh-*` CSS kuralları (448 satır)
- `.sl-*` CSS kuralları (231 satır)
- `/health` ve `/logs` route'ları

---

## #36 — Monitor: Çift Yönlü Oklar + Metin Okunabilirliği (2026-03-09)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-09 |
| **Neden** | Flow diyagramında MT5 ↔ OĞUL/MANUEL/HİBRİT bağlantıları tek yönlü (sadece aşağı) gösteriliyordu; gerçek mimaride modüller MT5'e emir de gönderiyor. Ayrıca tüm sayfa metinleri koyu arka planda çok silik/okunaksız kalıyordu. |

### Değişiklikler

| Dosya | Ne Değişti |
|-------|-----------|
| `desktop/src/components/Monitor.jsx` | MT5 okları tek yönlü → çift yönlü (yukarı EMİR ↑ + aşağı VERİ ↓), `mnFlowVUp` animasyonu eklendi. 6 silik renk tonu parlatıldı: `#2a3a55→#5a7a9a`, `#253550→#4a6a8a`, `#3a5070→#6a8aa8`, `#1e3050→#4a6a8a`, `#3a5880→#7a9ab8`, `#4a6080→#7a9ab0` |

### Eklenen
- Çift yönlü ok bileşeni (EMİR ↑ / VERİ ↓ etiketli)
- `@keyframes mnFlowVUp` animasyonu (yukarı akış)

### Çıkartılan
- Tek yönlü aşağı oklar (MT5 → modül)

---

## #37 — Manuel/Hibrit Bug Fix + Risk Baseline Ayari (2026-03-09)

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-09 |
| **Neden** | Manuel islem hibrite devredildikten sonra iki sorun yasaniyordu: (1) ManuelMotor ghost entry — active_trades temizlenmedigi icin ayni sembolde yeni islem acilamiyordu, (2) Fiyat zaten SL seviyesini ihlal etmisken devir yapilabiliyordu ve 10sn sonra pozisyon aninda kapaniyordu. Ayrica kullanici istegiyle BABA risk hesaplama baslangic tarihini arayuzden degistirme ozelligi eklendi. |

### Degisiklikler

| Dosya | Ne Degisti |
|-------|-----------|
| engine/h_engine.py | transfer_to_hybrid(): ManuelMotor.active_trades temizleme. check_transfer(): fiyat SL ihlali kontrolu. __init__: manuel_motor cross-motor referansi. |
| engine/manuel_motor.py | sync_positions(): FILLED pozisyon kontrolu symbol-based yerine ticket-based. |
| engine/main.py | Engine.__init__: h_engine.manuel_motor cross-referans eklendi. |
| engine/config.py | set() ve save() metotlari eklendi (config JSON guncelleme destegi). |
| api/routes/settings.py | **YENI** — GET/POST /settings/risk-baseline endpoint'leri. |
| api/schemas.py | RiskBaselineGetResponse, RiskBaselineUpdateRequest, RiskBaselineUpdateResponse semalari eklendi. |
| api/server.py | Settings router import ve include eklendi. |
| desktop/src/services/api.js | getRiskBaseline() ve updateRiskBaseline() API fonksiyonlari eklendi. |
| desktop/src/components/Settings.jsx | Risk Hesaplama Baslangici karti — tarih input, iki asamali dogrulama. |
| desktop/src/styles/theme.css | .st-baseline-*, .st-btn-primary, .st-btn-danger, .st-section-desc CSS kurallari eklendi. |

### Eklenen
- ManuelMotor ghost entry temizleme (hibrite devir sonrasi)
- Fiyat vs SL ihlal kontrolu (devir oncesi guvenlik)
- Ticket-based sync (symbol-based yerine)
- Config set/save API destegi
- /api/settings/risk-baseline endpoint (GET + POST)
- Settings: Risk Baseline Date karti (iki asamali dogrulama)

### Cikartilan
- (yok — mevcut davranisa ekleme yapildi)
