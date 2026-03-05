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
