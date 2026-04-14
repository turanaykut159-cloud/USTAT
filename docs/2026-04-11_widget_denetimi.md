# ÜSTAT v5.9 — Kapsamlı Widget & Sayfa Denetimi

**Tarih:** 11 Nisan 2026
**Denetçi:** Claude (Cowork)
**Amaç:** Bütün sayfa / kart / modül / widget'ların kod ile gerçek bağlantısını, veri kaynağını ve görevlerini yerinde doğrulamak.

## 0. Denetim Yöntemi

Her widget için 4 adım kontrol edilir:

1. **UI → API:** React bileşeni hangi `api.js` fonksiyonunu çağırıyor?
2. **API → Route:** `api.js` → FastAPI route dosyası var mı, endpoint çalışıyor mu?
3. **Route → Kaynak:** Route gerçek veri kaynağı (DB, Engine, MT5) döndürüyor mu, yoksa hardcode/stub mu?
4. **Karar:** ✅ Canlı · ⚠️ Kısmi · 🔴 Sessiz (veri yok) · 🐛 Yanlış görev · 🧱 Hardcode/stub

**Drill-down kuralı:** Kartlara tıklayınca açılan alt kartlar / modallar / detay panelleri ayrıca denetlenir.

## 1. Sayfa ve Route Haritası

Kaynak: `desktop/src/App.jsx` (HashRouter) ve `desktop/src/components/SideNav.jsx`

| # | Yol | Bileşen | SideNav Başlığı |
|---|-----|---------|-----------------|
| 1 | `/` | `Dashboard.jsx` | Gösterge Paneli |
| 2 | `/manual` | `ManualTrade.jsx` | Manuel İşlem |
| 3 | `/hybrid` | `HybridTrade.jsx` | Hibrit İşlem |
| 4 | `/auto` | `AutoTrading.jsx` | Otomatik İşlem |
| 5 | `/trades` | `TradeHistory.jsx` | İşlem Geçmişi |
| 6 | `/performance` | `Performance.jsx` | Performans |
| 7 | `/ustat` | `UstatBrain.jsx` | ÜSTAT Beyin |
| 8 | `/risk` | `RiskManagement.jsx` | Risk Yönetimi |
| 9 | `/monitor` | `Monitor.jsx` | Sistem Monitörü |
| 10 | `/errors` | `ErrorTracker.jsx` | Hata Takip |
| 11 | `/nabiz` | `Nabiz.jsx` | NABIZ |
| 12 | `/settings` | `Settings.jsx` | Ayarlar |

## 2. Backend Route Envanteri (api/routes/)

22 modül: `account`, `error_dashboard`, `events`, `health`, `hybrid_trade`, `killswitch`, `live`, `manual_trade`, `mt5_verify`, `nabiz`, `news`, `notifications`, `ogul_activity`, `performance`, `positions`, `risk`, `settings`, `status`, `top5`, `trades`, `ustat_brain`.

---

## 3. Dashboard (`/`)

**Dosya:** `desktop/src/components/Dashboard.jsx` (872 satır)
**Sürükle-bırak:** `@dnd-kit/core` + `SortableCard` + `DraggableGrid`. 8 kart ID'si `localStorage['ustat_dashboard_card_order']` anahtarında saklanır. "↺ Sıfırla" butonu varsayılan sıraya döndürür.
**Veri kaynağı:** REST polling (10 sn) + WebSocket `/ws/live` (2 sn) karışımı. WebSocket koparsa `equityStale` bayrağı devreye girer ve üst panelde `⚠ Veri eski` banner'ı gösterilir. Bağlantı özeti `wsState` ile takip edilir.

### 3.1 Üst Bar — 4 Stat Kartı

| Kart | Değer Kaynağı | UI → API | API → Kaynak | Karar |
|------|---------------|----------|--------------|-------|
| Günlük İşlem | `status.daily_trade_count` / `stats.total_trades` | `getStatus()` + `getTradeStats()` | `/api/status` → `baba._risk_state["daily_trade_count"]` (canlı) · `/api/trades/stats` → DB `get_trades(since=STATS_BASELINE)` | ✅ Canlı |
| Başarı Oranı | `stats.win_rate` + `winning_trades`/`losing_trades` | `getTradeStats()` | `/api/trades/stats` → DB istatistikleri | ✅ Canlı |
| Net K/Z | `stats.total_pnl` | `getTradeStats()` | Aynı DB hesabı | ✅ Canlı |
| Profit Factor | `perf.profit_factor` | `getPerformance(30)` | `/api/performance` → DB (gross_profit / gross_loss) | ✅ Canlı |

**Canlı gözlem:** 0 / 164 · %53.0 (87W/77L) · −14.414,28 TRY · 0.54 → hesaplar baseline 2026-02-01 tarihinden itibaren doğru çalışıyor.

### 3.2 Hesap Durumu Kartı (6 alt kalem)

| Alan | UI → API | API → Kaynak | Karar |
|------|----------|--------------|-------|
| Bakiye | `getAccount()` → `account.balance`, WS `equity` mesajındaki `balance` | `/api/account` → `mt5.get_account_info()` (canlı MT5) | ✅ Canlı |
| Varlık (Equity) | WS `equity` stream, REST fallback `account.equity` | `ws/live` `_push_loop` → MT5 account | ✅ Canlı |
| Teminat | WS `msg.margin` (2 sn), REST `/account` fallback (30 sn) | MT5 account | ✅ Canlı |
| Serbest Teminat | WS `msg.free_margin`, REST fallback | MT5 account | ✅ Canlı |
| Floating K/Z | WS `liveEquity.floating_pnl`, REST fallback (`equity − balance`) | MT5 account + türetme | ✅ Canlı |
| Günlük K/Z (TRY) | WS `liveEquity.daily_pnl`, REST `account.daily_pnl` | `/api/account` → `db.get_latest_risk_snapshot()["daily_pnl"]` | ✅ Canlı — *NB: TopBar'daki "Günlük K/Z (MT5)" başka kaynağa bakıyor, Bölüm 15'te değerlendirilecek.* |

**Stale banner:** `equityStale || status.circuit_breaker_active || status.data_fresh === false` durumlarında çalışıyor. Bu gerçek anayasal koruma katmanı — ✅ canlı.

### 3.3 Açık Pozisyonlar Tablosu (14 kolon)

**UI → API:** `getPositions()` (REST 10 sn) + WS `position` mesajı (event-driven). `getHybridStatus()` ile Hibrit ticket seti ayrıca çekilir.
**API → Kaynak:** `/api/positions` → `mt5.get_positions()` zenginleştirme (ogul/manuel_motor active_trades + db source cache + h_engine hybrid_positions seti).

| Kolon | Kaynak | Karar |
|-------|--------|-------|
| Sembol, Yön, Lot, Giriş/Anlık Fiyat | MT5 raw | ✅ Canlı |
| SL, TP | `p["sl"]`, `p["tp"]` — MT5 native seviyeler | ⚠️ **Kısmi** — Hibrit pozisyonlarda MT5 native SL/TP kullanılmıyor (`h_engine._native_sltp = false`). Ekranda "—" gösteriliyor. Gerçek koruma h_engine.current_sl/current_tp içinde. Dashboard tablosu Hibrit satırlar için bu değerleri göstermiyor → **karar verirken kullanıcı yanılabilir**. |
| Swap, K/Z | MT5 raw | ✅ Canlı |
| Tür (Manuel / MT5 / Otomatik / Hibrit) | Backend `_tur_for_position` (OĞUL stratejileri, source cache, hybrid set kesişiminden hesaplanır) | ✅ Canlı |
| Yönetim (TP1/BE/MA/Vote) | `ogul.active_trades[sym]` bayrakları | ⚠️ **Kısmi** — sadece OĞUL yönetimi altındaki pozisyonlarda dolu. Manuel/Hibrit için boş kalıyor (adopt edilmiş pozisyonlarda `strategy="bilinmiyor"`). Tasarım böyle olsa da kullanıcıya görsel olarak "hiç yönetilmiyor" hissi veriyor — ileride tooltip ekleme adayı. |
| Süre | `open_time` → `elapsed()` yardımcısı; 30 sn `setTick` ile yeniden render | ✅ Canlı |
| Rejim | `status.regime` (BABA) | ✅ Canlı |
| İşlem → `İşlemi Kapat` butonu | `closePosition(ticket)` → `POST /positions/close` → `mt5.close_position()` | ✅ Canlı |
| İşlem → `Hibrite Devret` / `PRİMNET` butonu | `checkHybridTransfer` + `transferToHybrid` → `POST /hybrid/check` + `POST /hybrid/transfer` → `h_engine.check_transfer()` / `h_engine.transfer_to_hybrid()` | ✅ Canlı |

**Üst sağ rozetler:**
- `1 / 5` pozisyon sayacı — `max_open_positions` config'e **bağlı değil**, sabit "/5" kullanılıyor. 🧱 **Hardcode** — config'den `max_open_positions` okunmalı (Bölüm 17 aksiyon adayı).
- `Teminat: %99.3` — `marginUsagePct(margin, equity)` canlı hesaplar, >%80 kırmızı. ✅ Canlı. **Operasyonel not:** Denetim anında %99.3 görünüyor — margin tamponu yok, yeni pozisyon kabul edilemez.

**Altlık (footer):** TOPLAM satırı — lot, swap, K/Z toplamı `reduce` ile hesaplanır. ✅ Canlı.

**Drill-down #1 — PRİMNET modalı (`PrimnetDetail.jsx`):**
Hibrit satırındaki `PRİMNET` butonu → `setSelectedHybridPos(hp)` → `PrimnetDetail` açılır. Modal içeriği:
- **Hesaplar:** `priceToPrim`/`primToPrice` (1 prim = %1) istemci tarafında hesaplanır. Sabit 1.5 prim trailing, +9.5 prim hedef (`primnet.trailing_prim`, `primnet.target_prim` — `/hybrid/status` → `h_engine._primnet_trailing/_target` canlı değerler).
- **Tablo:** −10 ile +10 arası tüm prim kademeleri, açıklama kolonu (buildExplanation), statusClass rozetleri (unreachable/locked/breakeven/trailing/target).
- **Kaynak:** `selectedHybridPos` objesi REST `/hybrid/status` çıktısının birebir kopyası.
- **Karar:** ✅ Canlı — h_engine gerçek trailing durumunu yansıtıyor.
- **Bulgu:** Ekrandaki F_ASELS pozisyonunda `current_sl=405.7`, `current_tp=365.45`, `breakeven_hit=true`, `trailing_active=false` görünüyor. Ancak pozisyon listesinde SL/TP "—" gösterildiği için iki panel arasında uyumsuzluk var → kullanıcının **hangi değerin geçerli olduğunu anlayamaması riski**.

### 3.4 Son İşlemler Kartı

| Öğe | Kaynak | Karar |
|------|--------|-------|
| Tablo (5 satır) | `getTrades({limit:5})` → `/api/trades` → DB `get_trades()` | ✅ Canlı |
| "N onaysız" rozeti | `recentTrades.filter(t => !(t.exit_reason ?? '').includes('APPROVED'))` | ⚠️ **Mantık zayıf** — exit_reason string üzerinden substring kontrolü yapılıyor. "APPROVED" anahtarının ne zaman set edildiği `/trades/approve` endpoint'ine bağlı. Otomatik işlemlerde bu alan boş kalırsa tüm kapanmış işlemler "onaysız" görünür. **Tasarım doğrulaması gerekiyor**. |
| Zaman kolonu | `shortTime(t.exit_time ?? t.entry_time)` | ✅ Canlı |

### 3.5 Haber Akışı Kartı (`NewsPanel`)

| Öğe | Kaynak | Karar |
|------|--------|-------|
| `newsData` başlangıç | REST `getNewsActive()` → `/api/news/active` → `engine.news_bridge.get_active_events()` | ✅ Canlı |
| Canlı güncelleme | WS `type: 'news'` mesajı | ✅ Canlı |
| Sayaçlar (aktif/en iyi/en kötü sentiment) | `NewsActiveResponse.count`, `best_sentiment`, `worst_sentiment` | ✅ Canlı |
| KRİTİK badge | `newsData.worst_severity === 'critical'` (NewsPanel içinde) | Denetim yapılacak — NewsPanel ayrıca denetlenmeli; göründüğü kadarıyla ✅. |

**Canlı gözlem:** 45 aktif haber, KRİTİK etiketi aktif, GENEL kaynaklı TÜFE/HICP olayları 18 dk önce injected. Haber motoru sağlıklı.

### 3.6 Bildirim Butonu ve Paneli

| Öğe | Kaynak | Karar |
|------|--------|-------|
| Başlangıç `notifications` | `getNotifications({limit:50})` → `/api/notifications` → `db.get_notifications()` | ✅ Canlı |
| Yeni bildirim push | WS `type: 'notification'` | ✅ Canlı |
| "Tümünü okundu yap" | `markAllNotificationsRead()` → `/api/notifications/read-all` | ✅ Canlı |
| Tekli okundu | `markNotificationRead(dbId)` → `/api/notifications/read` | ✅ Canlı |

**Canlı gözlem:** TopBar'da "Bildirimler (12)" — DB'de 12 okunmamış kayıt var, Dashboard bunu doğru yansıtıyor.

### 3.7 Dashboard — Toplam Değerlendirme

- **9 kart + 3 drill-down** (PRİMNET modal, ConfirmModal hata modalı, Bildirim paneli) denetlendi.
- ✅ Canlı: 6 kart (4 stat + hesap + haber)
- ⚠️ Kısmi: 2 kart (Açık Pozisyonlar — Hibrit SL/TP görünürlük sorunu; Son İşlemler — onaysız mantığı)
- 🧱 Hardcode: 1 yer (pozisyon `/5` sayacı)
- 🔴 Sessiz kart: **yok**
- 🐛 Yanlış görev: **yok**

## 4. Manuel İşlem (`/manual`)

**Dosya:** `desktop/src/components/ManualTrade.jsx` (533 satır)
**Backend:** `api/routes/manual_trade.py` → `ManuelMotor` (engine/manuel_motor.py)
**Faz makinesi:** `'select' → 'checked' → 'done'` — "Kontrol Et" adımı `/manual-trade/check` (read-only), "Onayla" `/manual-trade/execute` (MARKET emir).

### 4.1 Sol Panel — Emir Formu

| Öğe | Kaynak | Karar |
|------|--------|-------|
| Sembol dropdown (15 kontrat) | `SYMBOLS` sabiti (dosya satır 21-25) | 🧱 **Hardcode** — `config/default.json.watchlist.symbols` ile senkron kalma garantisi yok. Backend watchlist değişirse UI kilitli kalır. |
| Yön (BUY/SELL) | Local state | ✅ |
| Lot input | `min={1} max={10} step={1}` sabit (satır 214-216) | 🧱 **Hardcode** — config'deki `max_open_positions` veya `max_lot_per_trade` okunmalı. |
| SL/TP input | `checkResult` öneri + kullanıcı düzenleme | ✅ Backend ATR tabanlı öneri döner, düzenlenebilir. |
| "Kontrol Et" butonu | `checkManualTrade(symbol, direction)` → `POST /manual-trade/check` → `mm.check_manual_trade()` | ✅ Canlı (BABA risk kapısı, rejim, kill-switch, lot çarpanı hepsi gerçek). |
| "Onayla" butonu | `executeManualTrade(symbol, direction, lot, sl, tp)` → `POST /manual-trade/execute` → `mm.open_manual_trade()` | ⚠️ **Kod bulgu:** `handleExecute` useCallback dependency array'i `[symbol, direction, lot, fetchRecentTrades]` — `sl` ve `tp` eksik. Kullanıcı SL/TP'yi düzenledikten sonra closure eski değerleri yakalayabilir (stale closure). React lint bunu yakalar. 🐛 **Potansiyel hata** — düzeltilmesi gereken gerçek sorun. |

### 4.2 Sağ Panel — Risk Özeti

| Satır | Kaynak (`risk_summary`) | Karar |
|-------|------------------------|-------|
| Rejim × risk_multiplier | BABA current_regime | ✅ Canlı |
| Günlük İşlem (n/5) | BABA risk_state | ✅ Canlı — "/5" de hardcode, config'den alınmıyor 🧱 |
| Üst Üste Kayıp | BABA consecutive_losses | ✅ Canlı |
| Equity / Serbest Teminat / Floating K/Z | MT5 account | ✅ Canlı |
| Kill-Switch FAZ | BABA `_kill_switch_level` | ✅ Canlı |
| Lot Çarpanı | BABA `_lot_multiplier` | ✅ Canlı |
| "İşlem açılabilir" / red sebebi | `checkResult.can_trade` + `checkResult.reason` | ✅ Canlı |

### 4.3 Aktif Manuel Pozisyonlar Tablosu

**Filtre:** `getPositions()` sonucundan `pos.tur === 'Manuel' || pos.tur === 'MT5'` kayıtları.

| Öğe | Karar |
|------|-------|
| Sembol, Yön, Lot, Giriş, Anlık, K/Z, Süre kolonları | ✅ Canlı (MT5 raw) |
| "Kapat" butonu | `closePosition(ticket)` → `/positions/close` → `mt5.close_position` | ✅ Canlı |
| TOPLAM satırı (2+ pozisyonda) | Client reduce | ✅ |

**Canlı gözlem:** Tablo boş — Dashboard'daki F_ASELS pozisyonu "Hibrit" türünde olduğu için filtre dışında kaldı. Tutarlı.

### 4.4 Açık Manuel Pozisyonlar — Risk Göstergesi (ikincil tablo)

| Öğe | Kaynak | Karar |
|------|--------|-------|
| Satırlar | `getManualRiskScores()` → `/manual-trade/risk-scores` → `mm.get_all_risk_scores()` | ✅ Canlı |
| Renkli badge'ler (DUSUK/ORTA/YUKSEK) | 5 boyut: sl_risk, regime_risk, pnl_risk, system_risk, overall | ✅ Canlı |
| Skor sütunu | `rs.score` | ✅ Canlı |

**Not:** Denetim anında `riskScores` boş → tablo gizli. Kod koşullu render kullanıyor.

### 4.5 Son Manuel İşlemler Tablosu

`getTrades({strategy:'manual', limit:10})` → DB filtreli → ✅ Canlı. Canlı gözlem: 1 adet "F_ASELS SELL 5 lot 394.63 → 397.65 −1.510" kaydı görünüyor.

### 4.6 Manuel — Toplam Değerlendirme

- Faz makinesi mimari olarak sağlam (2 aşamalı — check → execute).
- ✅ Canlı: 4 alan (form akışı, risk özeti, aktif poz tablosu, geçmiş tablosu).
- 🧱 Hardcode: 3 yer (SYMBOLS listesi, lot min/max, max_daily_trades/5).
- 🐛 `handleExecute` useCallback stale closure riski (sl/tp dependency eksik).
- 🔴 Sessiz kart: **yok**.
- Drill-down: yok (modal yok, form ile inline akış).

## 5. Hibrit İşlem (`/hybrid`)

**Bileşen:** `HybridTrade.jsx` (729 satır) — `DndContext` + `SortableContext` ile 5 sürüklenebilir kart (`summary`, `perf`, `form`, `positions`, `events`). Sıra `localStorage: ustat_hybrid_card_order`.

**api.js fonksiyonları (doğrulandı):** `getPositions`, `checkHybridTransfer → POST /hybrid/check`, `transferToHybrid → POST /hybrid/transfer`, `removeFromHybrid → POST /hybrid/remove`, `getHybridStatus → GET /hybrid/status`, `getHybridEvents → GET /hybrid/events`, `getHybridPerformance → GET /hybrid/performance`, `connectLiveWS`.

**Başlık rozeti:** `native_sltp` durumuna göre `MT5 SL/TP` vs **`Yazılımsal SL/TP`** gösterir. Canlı sistemde `native_sltp: false` doğrulandı → rozet doğru çalışıyor ✅.

### 5.1 Özet Kartı (`summary`)

4 stat kartı: **Aktif Hibrit** (`active_count / max_count`), **Anlık Floating** (`totalHybridPnl`), **Günlük Hibrit K/Z** (`daily_pnl`), **Günlük Limit** (`%limitUsedPct / daily_limit` + ilerleme çubuğu).

| Kalem | Kaynak | Durum |
|---|---|---|
| `active_count` / `max_count` | `/hybrid/status` → `h_engine._max_concurrent` | ✅ Canlı |
| `totalHybridPnl` | WS `hybrid` mesajı + REST pozisyon `profit + swap` | ✅ Canlı |
| `daily_pnl` | `h_engine._daily_hybrid_pnl` | ✅ Canlı |
| `daily_limit` | `h_engine._config_daily_limit` | ✅ Canlı (config bağlı) |

Canlı doğrulama: `{active:1, max:3, daily_pnl:0, daily_limit:500, limit_used:0%}` — değerler `hybrid_trade.py` `/hybrid/status` çıktısıyla birebir.

### 5.2 Performans Kartı (`perf`)

`getHybridPerformance() → db.get_hybrid_performance()` çıktısını 8 hücreli grid'de gösterir: toplam, kazanan, kaybeden, başarı %, toplam K/Z, ortalama, en iyi, en kötü + kapanış nedeni etiketleri.

Canlı doğrulama:
```
total=45, winners=15, losers=16 (!), win_rate=33.3%, total_pnl=351.9, best=535, worst=-758.99
close_reasons: {EXTERNAL:23, KILL_SWITCH_L3:1, MANUAL_REMOVE:4, SOFTWARE_SL:16, SOFTWARE_TP:1}
```

**Tespitler:**
- ✅ Tüm kalemler DB'den (`db.get_hybrid_performance()`).
- 🐛 **Tutarsızlık:** `total=45` ama `winners+losers = 15+16 = 31`. Aradaki 14 işlem `scratch/even` olmalı ancak UI'de sadece `winners + losers` gösteriliyor → kullanıcı toplam ile alt dökümler arasında tutarsızlık görüyor.
- ⚠️ `perfStats.total > 0` koşulu yoksa "Henüz performans verisi yok" gösterir — doğru fallback.
- 🧱 Close reasons etiketleri raw string (`EXTERNAL`, `KILL_SWITCH_L3` gibi teknik kodlar) — kullanıcı dostu çeviri yok.

### 5.3 Devir & Risk Kartı (`form`)

**Sol panel — form akışı:** Açık pozisyon dropdown'ı (`hybridTickets` hariç filtrelenmiş) → `handleCheck()` → `/hybrid/check` → sonuç ekranı (symbol, direction, entry, current, ATR(14), suggested SL, suggested TP 2×ATR metni) → `handleTransfer()` → `/hybrid/transfer` → sonuç mesajı (başarı/hata). 2 sn sonra form resetlenir.

**Sağ panel — risk özeti:** `Aktif Hibrit`, `Günlük K/Z`, `Günlük Limit`, `Anlık Floating`, (kontrol sonrası) `ATR Değeri`. `active_count >= max_count` ise "Eşzamanlı limit dolu" uyarısı.

**Tespitler:**
- ✅ Backend `/hybrid/check` → `h_engine.check_transfer(ticket)` gerçek H-Engine hesabı. `/hybrid/transfer` → `h_engine.transfer_to_hybrid(ticket)` atomik.
- 🐛 **Hatasız `handleCheck`/`handleTransfer`** — hiçbirinde `try/catch` yok (satır 142-172). `fetch` hatası UI'yi sessiz bozar; `checkResult=null` kalır, kullanıcı butonun takıldığını sanır.
- ⚠️ `2×ATR` metni UI'de hardcode (satır 449-452: `'-2×ATR'`, `'+2×ATR'`). Backend'de ATR çarpanı değiştirilirse UI açıklaması yanlış kalır — config'den gelmeli.
- ⚠️ "Eşzamanlı limit dolu" uyarısı sadece eşitlik kontrolünde gösteriliyor; gerçek backend reddi (`can_transfer=false`) sadece `reason` string olarak geliyor.
- ⚠️ `parseInt(selectedTicket, 10)` — ticket 32-bit JS int sınırını aşarsa bozulur; `/positions` F_ASELS canlı ticket `8050554788` güvenli (< 2^53).

### 5.4 Aktif Hibrit Pozisyonlar Tablosu (`positions`)

11 kolon: Sembol, Yön, Lot, Giriş Fiy., Anlık Fiy., SL, TP, K/Z, Durum, Süre, İşlem.

- `stateLabel(hp)`: `trailing_active → 'Trailing'`, `breakeven_hit → 'Breakeven'`, else `'Aktif'`.
- `İşlem` kolonu: `Hibritten Çıkar` butonu → `removeFromHybrid(ticket)` → `/hybrid/remove` → `h_engine.remove_from_hybrid`.

**Canlı veri** (F_ASELS, tek pozisyon):
```
ticket=8050554788, symbol=F_ASELS, direction=SELL, volume=4, entry=400.05
current_price=403.80, current_sl=405.70, current_tp=365.45
initial_sl=405.70, initial_tp=341.95, pnl=0, breakeven_hit=true, trailing_active=false
state=ACTIVE, reference_price=403.80, transferred_at=2026-04-10T17:45:14
```

**Tespitler:**
- 🐛 **Volume tutarsızlığı** — Hibrit backend `volume: 4`, Dashboard MT5 pozisyonu `5 lot`. Aynı ticket için iki panelde iki farklı lot gözüküyor. H-Engine `hp.volume` başka bir alandan besleniyor (`hybrid_positions` kaydı devir anındaki lot mu? pozisyon MT5'ten bağımsız mı?). Bu, kullanıcı görünürlük açısından CİDDİ.
- 🐛 **`pnl=0`** — F_ASELS SELL @400.05, current 403.80 → 3.75 TL zarar olmalı. Backend `mt5_pos.get("profit", 0.0) + mt5_pos.get("swap", 0.0)` formülü `profit=0, swap=0` dönüyor (Dashboard ile aynı bulgu). Broker netting / MT5 `profit` alanının sıfır gelmesi. H-Engine sanal PnL hesabı yok.
- 🐛 **TP regresyon** — SELL için `initial_tp=341.95` (hedef), `current_tp=365.45` (entry'ye daha yakın, kazancı azaltıyor). Bu PRİMNET trailing hedef "güvenceye alma" mantığı olabilir ama UI bu hareketi açıklamıyor → kullanıcı TP'nin neden geriletildiğini anlamaz.
- ⚠️ `volume.toFixed(2) → "4.00"` VİOP'ta kullanıcıyı rahatsız eder (tam sayı lot).
- ✅ `transferred_at` + `elapsed()` süre göstergesi canlı.
- ✅ `removeFromHybrid` → catch bloğu var (`errorModal`), doğru uyarı akışı.

### 5.5 Olay Geçmişi (`events`)

`getHybridEvents({limit:20}) → /hybrid/events → db.get_hybrid_events(limit)`. 4 kolon: Zaman, Sembol, Olay (renkli rozet), Detay (JSON parse ile bağlam).

Desteklenen olay tipleri: `TRANSFER`, `BREAKEVEN`, `TRAILING_UPDATE`, `CLOSE`, `REMOVE` + fallback. Her biri için farklı cümle formatı.

Canlı örnek:
```
id=426 ticket=8050554788 event=PRIMNET_DAILY_RESET details={old_ref:0.0, new_ref:403.79, old_sl:405.7, new_sl:405.7, ...}
```

**Tespitler:**
- 🐛 **Bilinmeyen olay tipi** — Canlı veride `PRIMNET_DAILY_RESET` olayı var ama UI `switch` 5 tip biliyor (`TRANSFER/BREAKEVEN/TRAILING_UPDATE/CLOSE/REMOVE`). Bu olay fallback dalına düşer → `d.new_sl → SL: 405.7 → 405.7` gibi anlamsız metin üretir. PRİMNET günlük reset olayı için özel format eksik.
- ⚠️ `maxWidth: 300px, overflow:hidden` ile uzun JSON detayları kırpılıyor — kullanıcı tam bilgiyi göremez. Tooltip yok.
- ✅ Zaman formatı TR locale doğru.
- ✅ Backend `/hybrid/events` → `db.get_hybrid_events` gerçek SQLite okuma.

### 5.6 Hibrit — Toplam Değerlendirme

- **🔴 Sessiz kart:** Yok — tüm kartlar gerçek veri çekiyor.
- **🧱 Hardcode:** `2×ATR` açıklama metni (UI'de sabit); close reason etiketleri teknik kod.
- **🐛 Yanlış görev (KRİTİK):**
  1. Pozisyon tablosunda `volume=4`, Dashboard'da `5 lot` — aynı pozisyon için veri çatışması.
  2. `pnl=0` canlı SELL pozisyonda (PnL hesabı eksik/yanlış).
  3. TP regresyonu (341.95 → 365.45) UI'de açıklanmıyor.
  4. `PRIMNET_DAILY_RESET` olayı UI `switch`'te yok → fallback bozuk metin üretir.
  5. Performans `total=45` vs `winners+losers=31` tutarsızlığı.
  6. `handleCheck`/`handleTransfer` try/catch yok → sessiz kilitlenme riski.
- **⚠️ Kısmi/iyileştirme:** ATR çarpanı metni config'den gelmeli; olay detay sütunu tooltip gerekli; `parseInt` ticket güvenliği not edilmeli.
- **Drill-down:** Modal yok; tüm ayrıntılar kart içinde inline akışta. PRİMNET detay modali YOK (Dashboard'daki `PrimnetDetail` bu sayfadan tetiklenmiyor).
- **PRİMNET config bağlantısı:** `/hybrid/status.primnet = {trailing_prim:1.5, target_prim:9.5}` canlı dönüyor ama UI'de bu değerleri gösteren bir kart/gösterge YOK — kullanıcı trailing/target prim eşiklerini göremiyor. 🔴 **Görünürlük boşluğu.**

## 6. Otomatik İşlem (`/auto`)

**Bileşen:** `AutoTrading.jsx` (572 satır) — sabit layout (drag-drop yok). 4 stat kartı üstte, Top 5 + Otomatik Pozisyon yan yana, altında tablo, en altta Son İşlemler + Oğul Aktivite kartı.

**api.js fonksiyonları:** `getStatus → /status`, `getTop5 → /top5`, `getPositions → /positions`, `getTrades → /trades`, `reactivateSymbols → /ogul/reactivate-symbols`, `getOgulActivity → /ogul/activity`, `getHealth → /health`, `connectLiveWS`.

**Poll:** REST 30 sn (WS zaten 2 sn push). WS dinlediği tipler: `status` + `position`. `AUTO_STRATEGIES = {trend_follow, mean_reversion, breakout}` — otomatik işlem filtresi.

### 6.1 Emir Red Alarmı (banner)

Koşul: `alarms.consecutive_rejects >= 2`. Kaynak: `getHealth()` → backend `/health` → `health.py` `alarms` sözlüğü. Canlı doğrulama: `{consecutive_rejects:0, last_reject_reason:""}` → banner gizli, doğru ✅.

### 6.2 Üst Bar — 4 Stat Kartı

| Kart | Kaynak | Durum |
|---|---|---|
| **DURUM** (`AKTİF/KISITLI/DURDURULDU/KAPALI`) | `status.engine_running` + `kill_switch_level` | ✅ Canlı. L2 durumunda `DURDURULDU` doğru gösteriliyor. |
| **AKTİF REJİM** (TREND/RANGE/VOLATILE/OLAY + %conf) | `status.regime` + `regime_confidence` | ✅ Canlı. Alt metin `REGIME_META.strategies` UI hardcode — "Trend Follow / MR + Breakout / Sinyal yok / Sistem pause". |
| **LOT ÇARPANI** | `status.risk_multiplier` | ✅ Canlı. Renk: 0=loss, ≤0.25=warning, <1=accent, else profit. |
| **OTO. İŞLEM** | `autoTradeCount` (son 50 trade'de filtre) | ⚠️ "Son 50" pencereli sayım — günlük/toplam değil, kullanıcı buna "günlük" zanneder. Etiket muğlak. |

**Tespit:** 🧱 `REGIME_META` içindeki `strategies` metni UI hardcode. Backend `active_strategies` (OĞUL aktivite) zaten bu bilgiyi dinamik veriyor — UI eski statik metne bağımlı.

### 6.3 Top 5 Kontrat Listesi

`getTop5()` → backend `ogul.current_scores` + `last_signals` (indikatör tabanlı). 5 satır: rank, symbol, direction (`BUY/SELL/NOTR`), score, bar (max'a göre normalize).

**Status bar:** `{activeCount}/15 aktif` — `deactivated_symbols` listesi üzerinden. `deactCount > 0` ise `Aktif Et` butonu → `reactivateSymbols()` → `/ogul/reactivate-symbols`. `last_refresh` tarih etiketi.

Canlı doğrulama: `contracts=5, first={rank:1, symbol:F_EKGYO, score:83.6, signal_direction:BUY, regime:TREND}, last_refresh:2026-04-11T16:10:50` → ✅ Gerçek.

**Tespit:**
- 🧱 `15` (toplam kontrat sayısı) UI hardcode (satır 272: `const activeCount = 15 - deactCount`). `config.symbols.length` yerine magic number. Sembol listesi değiştirilirse sayı bozulur.
- ✅ `reactivateSymbols` backend'e gerçek yazma işlemi, try/catch yok ama `res.success` kontrolüyle sessiz hata önleniyor.
- ⚠️ `score / top5.contracts[0].score` normalizasyon — ilk kontrat 83.6 ise diğerleri göreceli; mutlak skor görünmüyor (sadece ilk satırda açık yazılı).

### 6.4 Otomatik Pozisyon Özeti (sağ kart)

İçerik: `Açık poz: N | Toplam K/Z: X` — tek satırlık özet. Kart gövdesi boş.

**Tespit:**
- 🔴 **Sessiz kart adayı.** Kart yer kaplıyor ama tek satırlık bir bilgi veriyor. Altındaki tam tablo zaten aynı bilgiyi detaylı sunuyor → bu kart gereksiz (veya geliştirilmeli).

### 6.5 Aktif Otomatik Pozisyonlar Tablosu

11 kolon: Sembol, Yön, Strateji, Lot, Giriş, Anlık, SL, TP, K/Z, Oy, Süre. Filtre: `p.tur === 'Otomatik'`.

- `voting_score`: `/positions` backend'inde `pos.voting_score` → DB'deki `trades.voting_score` alanı (OĞUL karar oyu).
- `sl > 0 ? formatPrice : '—'` — sıfırsa çizgi.

**Tespitler:**
- ✅ Filtreleme doğru: `positions.py` `_tur_for_position` → trade kaydına `strategy in _OTOMATIK_STRATEJILER` ise `Otomatik` dönüyor.
- ✅ SL/TP görünürlüğü otomatikte doğru (native_sltp=true, MT5 emir düzeyinde).
- ⚠️ **Boş durum** — L2 aktif + tüm pozisyonlar hibrit/manuel olduğu için bu tablo canlı sistemde boş. Canlı örnek veri üretilemedi.
- ⚠️ Strateji kolonu backend'den gelen string (`trend_follow`, `mean_reversion`, `breakout`) — kullanıcı dostu çeviri yok.

### 6.6 Son Otomatik İşlemler Tablosu

`getTrades({limit:50})` sonra frontend'de `AUTO_STRATEGIES` ile filtre, `slice(0,10)`. 7 kolon: Sembol, Yön, Strateji, Lot, K/Z, Rejim, Zaman.

**Tespitler:**
- 🐛 **Çift zahmet:** Backend'den 50 trade çekilip client tarafında filtreleniyor — `/trades?strategy=auto` gibi sunucu filtresi yok. Büyük hacimde çoğu satır atılır.
- ✅ Veri kaynağı DB (`db.get_trades`).
- ⚠️ Strateji etiket çevirisi yok (yukarıdakiyle aynı).

### 6.7 Oğul Aktivite Kartı

`getOgulActivity()` → `/ogul/activity`. 4 alt parça:
1. **Header metadata:** `last_m15_close`, `active_strategies`, `adx_value`.
2. **3 sayaç:** Tarama, Sinyal, Reddedilen (`scan_symbols`, `signal_count`, `unopened_count`).
3. **Oylama tablosu:** `signals[]` — Sembol, Yön, RSI vote, EMA vote, ATR expanding, Volume > avg, Oy skoru (`favorable/total`).
4. **Açılamayan işlemler:** `unopened[]` liste + zaman + mesaj.

Canlı: `scan_symbols=3, signal_count=3, unopened_count=0, strategies=[trend_follow, breakout], adx=0, signals[3]`.

**Tespitler:**
- ✅ Tüm sayaç ve tablolar gerçek `ogul.scan_results` verisinden geliyor.
- 🐛 **`adx_value=0`** canlı sistemde. `ADX: 0` etiketi gösteriliyor → `ogulActivity.adx_value > 0` koşulu yanlış: 0 → etiket gizlenir. Şu an gizli. Ama canlı veride de 0 — backend ADX hesabı sonuç üretmiyor olabilir (TREND rejimi varken ADX > 25 beklenirdi).
- 🐛 **`last_m15_close=""` canlı** → "Son M15" etiketi gizli. UI fallback çalışıyor ama değerin boş olması backend tarafında OĞUL `last_m15_close` alanının yazılmadığını gösteriyor.
- ⚠️ `scan_symbols=3` ama Top 5 listesinde 5 kontrat var. "Tarama" sayacı farklı bir metriği gösteriyor (muhtemelen o döngüde aktif taranan) — etiket muğlak.
- ⚠️ Oylama tablosundaki `favorable / (totalVotes || 4)` — totalVotes=0 ise `0/4` gösterir, doğru fallback.

### 6.8 Otomatik — Toplam Değerlendirme

- **🔴 Sessiz kart:** Otomatik Pozisyon Özeti kartı (6.4) — fonksiyonel ama anlamsız ikilik.
- **🧱 Hardcode:** `activeCount = 15 - deactCount` (sembol sayısı), `REGIME_META.strategies` metin.
- **🐛 Yanlış görev:**
  1. `adx_value=0` canlı — backend hesaplama eksikliği veya `getOgulActivity` serializer eksikliği (TREND rejimindeyiz ama ADX=0).
  2. `last_m15_close=""` canlı — OĞUL metadatası eksik.
  3. Son İşlemler 50 çekip client filtresi (performans izi).
  4. "OTO. İŞLEM" sayacı "son 50" penceresinden → kullanıcıya muğlak (günlük mü?).
- **⚠️ Kısmi/iyileştirme:** Strateji etiketleri kullanıcı dostu çevirilere gerekli; `scan_symbols` etiketi "aktif tarama" olarak netleşmeli.
- **Drill-down:** Modal yok; "Aktif Et" butonu inline action.

## 7. İşlem Geçmişi (`/trades`)

> **NOT:** Route rapor başlığında `/history` olarak yazılmış — gerçek route `/trades`. (SideNav label "İşlem Geçmişi" ama path `/trades`.)

**Bileşen:** `TradeHistory.jsx` (669 satır). Layout: zaman butonları → filtre çubuğu → 4 özet kart → tablo (sayfalama 50) → performans+risk panelleri → alt özet.

**api.js fonksiyonları:** `getTrades`, `getTradeStats`, `getPerformance`, `approveTrade → POST /trades/approve`, `syncTrades → POST /trades/sync`, `connectLiveWS`, sabit `STATS_BASELINE`.

**WS tetiklemesi:** `trade_closed` ve `position_closed` mesajlarında `fetchData()` tekrar çağrılır — event-driven yenileme.

### 7.1 Zaman Filtre Butonları

`Varsayılan | Bugün | Bu Hafta | Bu Ay | 3 Ay | 6 Ay | 1 Yıl` — 7 buton.

- `Varsayılan`: `period='all' + symbol='all' + dir='all' + result='all' + sortMode=null` → tüm filtreler sıfırlanır.
- `periodStartDate(period)` client-side tarih hesaplaması → `filter` ile uygulanır.

**Tespit:**
- ⚠️ `period` client-side; backend `since` parametresi sadece `STATS_BASELINE` (`2026-02-01`) sabit değeri ile çağrılıyor. Yani her dönem seçiminde ilk 1000 kayıt tekrar çekilmiyor — **ilk çekimdeki STATS_BASELINE sonrası veriler filtreleniyor.** Kullanıcı `1y` seçse bile baseline'dan önce veri yok.
- ✅ Buton state toggle mantığı sağlam.

### 7.2 Filtre + Sıralama Çubuğu

Dropdowns: `Sembol` (dinamik `allTrades`'ten unique + sort), `Yön` (Tümü/Buy/Sell), `Sonuç` (Tümü/Kârlı/Zararlı). Sıralama butonları: En Kârlı/En Zararlı/En Uzun/En Kısa (toggle). `Yenile ↻` + `⟳ MT5 Senkronize Et` butonları.

**Tespit:**
- ✅ Tüm filtre mantığı client-side — `filteredTrades` memo.
- ✅ `syncTrades(90)` → `/trades/sync` → `engine.mt5.get_history_for_sync(days=90)` → `db.sync_mt5_trades` → dedup. Gerçek MT5 çağrısı.
- ⚠️ `handleSync`'te `try/finally` var ama error mesajı UI'ye düşmez (sadece `syncResult` null kalır).
- ⚠️ Yenile butonu fetchData ile aynı — MT5 sync değil, sadece DB refresh.

### 7.3 4 Özet Kart

| Kart | Kaynak | Durum |
|---|---|---|
| Toplam İşlem | `filteredStats.count` (client) | ✅ Canlı |
| Başarı Oranı | `filteredStats.winRate` | ✅ Canlı |
| Net K/Z | `filteredStats.totalPnl` | ✅ Canlı |
| Profit Factor | `filteredStats.profitFactor` | ✅ Canlı |

Canlı veri (baseline sonrası, 164 trade): `win_rate=53%`, `total_pnl=-14414.28`, `pf=0.54`, `best=+2705 (F_TOASO)`, `worst=-7925 (F_KONTR)`.

**Tespit:**
- ✅ Backend `/trades/stats` de çağrılıyor ama özet kartlar client-side hesaplıyor → filtre değişiminde backend trip gerekmiyor, iyi tasarım.
- 🐛 **Kritik veri şüphesi** — Canlı `best_trade`: `F_TOASO BUY 8 lot, entry=259.87, exit=257.80, pnl=+2705`. BUY için `exit<entry` zarar olmalı, pnl `+2705` olması veri tutarsızlığı. İki olasılık: (a) direction yanlış loglandı, (b) MT5 sync'te BUY/SELL ayarı bozuk. Bu 4. özet karta doğrudan etki ediyor.

### 7.4 İşlem Tablosu (13 kolon)

Kolonlar: Sembol, Yön, **Tür**, Lot, Giriş, Çıkış, Giriş Tarihi, Çıkış Tarihi, Süre, Swap, Komisyon, K/Z, Onay Butonu.

**Tür sınıflandırma mantığı (satır 508-513):**
```js
const isHybrid = exitReason.includes('SOFTWARE') || stratLower === 'hybrid' || stratLower === 'hibrit';
const isAuto = !isHybrid && stratLower !== '' && stratLower !== 'manual' && stratLower !== 'bilinmiyor';
const turLabel = isHybrid ? 'Hibrit' : isAuto ? 'Otomatik' : 'Manuel';
```

**Tespitler:**
- 🐛 **Sınıflandırma zayıf:** `isAuto` negatif koşullarla belirleniyor — `strategy` boş, `manual` veya `bilinmiyor` dışındaysa otomatik. Yeni strateji adı eklendiğinde otomatik sayılır ama `isHybrid` kontrolü de aynı listeye bağlı → yanıltıcı. Backend `_OTOMATIK_STRATEJILER` frozenset'i ile senkron değil.
- 🐛 `exitReason.includes('SOFTWARE')` — `SOFTWARE_SL`/`SOFTWARE_TP` kapanışlar hibrit sayılıyor. Ancak bir hibrit pozisyon `EXTERNAL` ile de kapanabilir (broker tarafı) → yanlış olarak **Manuel** veya **Otomatik** etiketlenir. Canlı veride `exit_reason: "mt5_sync"` olan hibrit tradeler bu koşula uymaz; yine de `strategy='hibrit'` ile yakalanıyor — ikili fallback iyi ama `exit_reason.includes('SOFTWARE')` gereksiz karmaşıklık.
- 🧱 **Onay mekanizması:** `approveTrade(id, 'operator', '')` — operator kim olduğu UI'den seçilemez, hep string `'operator'`. Kullanıcı kimliği yok.
- ✅ `approved` satırlar `th-row-new` class'ı almıyor → görsel ayrım var.
- 🐛 Optimistic update (satır 339-345): onay sonrası client-side state güncelleniyor ama `exit_reason` formatı backend'in yazdığı formatla ayrı (`' | APPROVED by operator'` - leading space). Bir sonraki `fetchData` sonrası format farkı göz ardı ediliyor.
- ⚠️ Tür kolonunda `regime` etiketi YOK — kullanıcı hangi rejimde açılmış bir işlem olduğunu göremez. Canlı örnekte zaten `regime=""` boş (backfill yapılmamış).
- ⚠️ `formatDuration` sadece exit_time varsa çalışır, açık pozisyon tabloda zaten yok.

### 7.5 Sayfalama

`PAGE_SIZE=50`, `totalPages = Math.ceil(sortedTrades.length / 50)`. `«« « N/M » »»` kontrolleri.

**Tespit:** ✅ Client-side, sağlam.

### 7.6 Performans + Risk Panelleri

**Performans paneli (Sol):** Toplam Kâr, Toplam Zarar, Kazanan, Kaybeden, Ort. Kazanç, Ort. Kayıp, Toplam Swap, Toplam Komisyon — hepsi `filteredStats` client hesabı.

**Risk paneli (Sağ):**
- `En İyi/En Kötü İşlem` → `stats?.best_trade`/`worst_trade` (backend `/trades/stats`).
- `Maks. Ardışık Kayıp` → client hesabı `maxConsecLosses`.
- `Sharpe Oranı` → `perf?.sharpe_ratio` (backend `/performance`).
- `Maks. Drawdown` → `perf?.max_drawdown_pct`.
- `Ort. İşlem Süresi` → `stats?.avg_duration_minutes`.
- `Toplam Lot / Ort. Lot` → client.

Canlı doğrulama: `sharpe=-2.09, maxdd=29.05%, pf=0.54, avg_duration=306dk` → `/performance` ve `/trades/stats` gerçek.

**Tespit:**
- 🐛 **Karışık kaynak:** Sol panel filtreli client hesap, sağ panel backend'in **sabit STATS_BASELINE**'dan hesapladığı global istatistikler. Kullanıcı dönem filtresi değiştiriyor ama `best_trade`, `sharpe`, `maxdd` hiç güncellenmiyor. Aralarında tutarsızlık oluşturuyor.
- 🐛 **`Maks. Drawdown %29.05`** canlı sistemde — Anayasa `hard_drawdown_pct=%15` sınırının çok üstünde. Ya hesap geçmiş veriden, ya backfill'li verinin doğru yansıması. Hiçbir yerde uyarı yok, sadece sayı gösteriliyor.
- ✅ `maxConsecLosses` client-hesap doğru.

### 7.7 Alt Özet Satırı

`Kâr | Swap | Komisyon | Toplam Lot | İşlem Sayısı` — hepsi `filteredStats` client.

**Tespit:** ✅ Tablo üst özetle birebir, tekrar bilgi.

### 7.8 İşlem Geçmişi — Toplam Değerlendirme

- **🔴 Sessiz kart:** Yok.
- **🧱 Hardcode:** STATS_BASELINE sabit, onay kullanıcı adı `'operator'` sabit, PAGE_SIZE=50 UI'de magic number.
- **🐛 Yanlış görev (KRİTİK):**
  1. Sağ risk paneli (best/worst/sharpe/maxdd/avg_duration) filtreye bağlı değil — sol panel filtreli, sağ global → kullanıcıyı yanıltır.
  2. `best_trade F_TOASO BUY 259.87→257.80 pnl +2705` veri tutarsızlığı — pnl işareti direction ile çelişiyor.
  3. Tür sınıflandırma mantığı (`isHybrid/isAuto`) backend `_OTOMATIK_STRATEJILER` ile senkron değil; `exit_reason.includes('SOFTWARE')` fragile.
  4. Rejim kolonu UI'de yok; `regime=""` backfill eksikliği gizli kalıyor.
- **⚠️ Kısmi:** Sync butonu hata raporlamıyor; onay optimistic update format uyumsuz.
- **Drill-down:** Yok — tüm detay tabloda inline.

## 8. Performans (`/performance`)

**Bileşen:** `Performance.jsx` (560 satır). 9 bölüm: 5 özet kart, equity eğrisi, drawdown, strateji+sembol (yan yana BarChart), Long vs Short + Win Rate trend (yan yana), saat heatmap, aylık K/Z breakdown.

**api.js:** `getPerformance(days) → /performance?days=N`, `getTradeStats(1000)`, `getTrades({since:STATS_BASELINE, limit:1000})`. Recharts (`AreaChart`, `BarChart`, `LineChart`).

**Period butonları:** 30/90/180/365 gün — `days` state'ine bağlı. Değişince `fetchPerfData` tetiklenir.

### 8.1 5 Özet Kart

| Kart | Kaynak | Durum |
|---|---|---|
| Net Kâr/Zarar | `perf.total_pnl` | ✅ Canlı |
| Win Rate | `perf.win_rate` | ✅ Canlı |
| Sharpe | `perf.sharpe_ratio` | ✅ Canlı (daily_snapshots'tan) |
| Profit Factor | `perf.profit_factor` | ✅ Canlı |
| Max Drawdown | `perf.max_drawdown_pct` | ✅ Canlı |

Canlı veri (days=90): `total_pnl=-14414, wr=53.05%, sharpe=-2.09, pf=0.54, maxdd=29.05%, total_trades=164, equity_points=31`.

**🐛 KRİTİK BUG — `days` parametresi backend'de KULLANILMIYOR:**
`api/routes/performance.py` satır 26 `days: int = Query(30)` accept ediyor ama fonksiyon içinde `db.get_trades(since=STATS_BASELINE, limit=5000)` çağrılıyor — `days` parametresi hiçbir yerde kullanılmıyor. Backend her zaman `STATS_BASELINE` (2026-02-01) sonrası TÜM işlemleri dönüyor.

**Sonuç:** Performans ekranındaki `1 Ay / 3 Ay / 6 Ay / 1 Yıl` butonları **hiçbir şey değiştirmiyor.** Kullanıcı `1 Ay` seçse bile tam baseline period verisini görüyor. UI butonları sessizce aldatıcı.

### 8.2 Equity Eğrisi (AreaChart)

`eq = perf.equity_curve` (backend'den `daily_snapshots` ile hesaplanmış). İki alan: `equity` (mavi, solid) + `balance` (yeşil, dashed).

Canlı: 31 nokta, başlangıç `balance=9949.59 @2026-03-11`, son `balance=38630.87 @2026-04-11`. Grafik bakiyenin 10k→38k büyüdüğünü gösteriyor (mevduat eklendi, total_pnl negatif olmasına rağmen).

**Tespit:**
- ✅ Gerçek günlük snapshot verisinden.
- 🐛 **Yanıltıcı görsel:** Bakiye artışı yatırım kaynaklı, fakat UI bu büyümeyi "kazanç trendi" olarak gösteriyor. Kullanıcı grafiği görünce kâr ediyor sanır — oysa `total_pnl=-14414` zarar. **Net sermaye vs mevduat ayrımı yok.**
- ⚠️ `balance=equity` her snapshot'ta (gün sonu floating yok) → dashed çizgi solid'in üzerine çöküyor, farklı görünmüyor.

### 8.3 Drawdown Grafiği

`drawdownData` client hesabı: `peak` takibi + `dd = (peak-eq)/peak*100`. AreaChart (kırmızı).

**Tespit:**
- ✅ Client hesabı doğru, equity_curve'den üretiliyor.
- 🐛 Backend `max_drawdown_pct=29.05` ile client chart tepe değeri eşleşmeli — uyum beklenen ama doğrulama için en yüksek DD noktası işaretlenmeli (şu an sadece trend). Referans çizgi yok.

### 8.4 Strateji Bazlı K/Z (BarChart)

`stats.by_strategy` → `strategyData`. Yatay bar, sıralı.

Canlı: 5 strateji (`hibrit`, `hybrid`, `manual`, `bilinmiyor`, `breakout`/trend_follow vs.) — backend bunları ayrı grupluyor.

**Tespit:**
- 🐛 **Tekrarlayan etiketler:** `by_strategy` hem `hibrit` hem `hybrid` anahtarını içeriyor (aynı şey iki isimle DB'de). UI iki ayrı bar gösterir — kullanıcı kafası karışır.
- 🧱 `name === 'unknown' ? 'Bilinmeyen' : name.replace(/_/g, ' ')` — sadece `unknown` çevriliyor, diğer teknik isimler (`trend_follow`, `mean_reversion`) olduğu gibi kalıyor.

### 8.5 Sembol Bazlı K/Z Top 10

`stats.by_symbol` → `symbolData.slice(0,10)`. Yatay bar.

**Tespit:**
- ✅ Gerçek agregasyon.
- ⚠️ Sıralama `pnl desc` — en kazandıran ve en kaybettiren semboller karışık görünüyor. "Top 10 kazandıran" ve "Top 10 kaybettiren" ayrımı daha bilgilendirici olurdu.

### 8.6 Long vs Short Paneli

`trades.filter(direction==='BUY' / 'SELL')` → client hesap: count, winRate, pnl, avgPnl, pf.

**Tespit:**
- ✅ Doğrudan trade verisinden.
- 🐛 **Veri tutarsızlığı riski:** İşlem Geçmişi bölümünde tespit edilen `F_TOASO BUY exit<entry pnl+2705` gibi veri bozuklukları bu panele de yansır (BUY için zarar hanesinde eksi olmalıyken artıyı seçer).

### 8.7 Win Rate Trend (20-İşlem MA)

`trades` ters sıralanıp 20'lik hareketli pencere → LineChart. `ReferenceLine y={50}`.

**Tespit:**
- ✅ Client hesap doğru.
- ⚠️ `sorted = [...trades].reverse()` — zaten DB `entry_time DESC` dönüyorsa ters çevirince `ASC` oluyor; order garantisi yok. Backend `db.get_trades` sıralaması doğrulanmalı.
- ⚠️ 20-işlem minimum; 20'den az varsa grafik boş ("Yeterli işlem yok").

### 8.8 Saat Bazlı Heatmap

Sabit 09-18 aralığı, dakika bazlı saat bucket'ı. Her hücre: saat, pnl, işlem sayısı, WR%.

**Tespit:**
- 🧱 **Saat aralığı hardcoded (9-18):** BIST/VİOP seans saatleri sabit kodlanmış. `config/default.json` → `session_start/end` kullanılmalı.
- 🐛 **Timezone sorunu:** `new Date(ts).getHours()` tarayıcı local saatine göre — kullanıcı farklı TZ'de olursa (örn. VPN) yanlış bucket'a düşer. Server time UTC+3 varsayımı yok.
- ✅ `entry_time` üzerinden (exit yerine) — işlem başlangıç saati metriği olarak doğru.

### 8.9 Aylık K/Z Breakdown (BarChart)

`ts.slice(0,7)` key ile gruplama → aylık pnl + count → Türkçe ay etiketi.

**Tespit:**
- ✅ Sağlam.
- ⚠️ `monthLabel` sadece ay adı döndürüyor, yıl göstermiyor → `Şub 2026` / `Mar 2026` ayrımı yok; 12 aydan fazla veri olursa çakışır.

### 8.10 Performans — Toplam Değerlendirme

- **🔴 Sessiz kart:** Yok — tüm bölümler veri üretiyor.
- **🧱 Hardcode:** Saat aralığı 9-18, strateji isim çevirisi yok, `CategoryChart` alt bileşeni render'da kullanılmıyor (dead code — satır 532-560).
- **🐛 Yanlış görev (KRİTİK):**
  1. **`days` butonları hiçbir şey yapmıyor** — backend parametreyi ignore ediyor. UI boşuna değişiyor.
  2. Equity grafiği net sermaye vs mevduat ayırmıyor → kazanç yanılsaması.
  3. `by_strategy` içinde `hibrit` ve `hybrid` duplicate anahtarları.
  4. Long vs Short, İşlem Geçmişi'ndeki yanlış pnl işareti olan tradelerden etkilenir.
  5. Drawdown chart'ta peak noktası işaretsiz.
  6. Timezone hardcoded assumption saat heatmap'te.
- **⚠️ Kısmi:** Aylık chart yıl etiketi yok; sembol Top10 ayrımı; `CategoryChart` dead component.
- **Drill-down:** Yok — tüm bölümler inline chart/panel.

## 9. ÜSTAT Beyin (`/ustat`)

**Dosya:** `desktop/src/components/UstatBrain.jsx` (488 satır)
**Sürükle-bırak:** Yok — sabit düzen.
**Veri kaynağı:** `getUstatBrain(days)` → `GET /api/ustat/brain?days=N`, `getPerformance(days)`, `getStatus()` — `fetchData` üçünü paralel yükler, periyot değişince (30/90/180/365 gün) yeniden çalışır. **Poll yok, WS yok** — sadece periyot butonuna basınca fetch yapılır.

**Backend:** `api/routes/ustat_brain.py`.
- `/ustat/brain` endpoint `days` parametresini ALIR VE KULLANIR (`since = now - days` ile `db.get_trades`). 🟢 Performans endpoint'inin aksine burada period butonu gerçekten çalışır.
- DB + Engine karışık: kategoriler/profiller `db.get_trades`'den üretilir, hata ataması / ertesi gün / strateji havuzu / regülasyon `ustat` engine modülünden (`get_error_attributions`, `get_next_day_analyses`, `get_strategy_pool`, `get_regulation_suggestions`).
- Engine MT5 bağlıysa önce `engine.sync_mt5_history_recent(min(7, days))` çağrılır — bu her periyot değişiminde MT5 geçmiş senkronizasyonunu tetikler (yan etki).

**Canlı test (fetch `/api/ustat/brain?days=90`):** 27 kontrat profili, 30 hata ataması, 50 olay, 5 rejim kovası, 7 ertesi gün analizi, 3 regülasyon önerisi, strateji havuzunda aktif profil `trend`. 🟢 Tüm bölümler canlı veri dönüyor.

### 9.1 Hero Banner (4 metrik + periyot butonları)

- **Analiz Edilen İşlem:** `summary.totalTrades = brain.trade_categories.by_result.reduce((s,c)=>s+c.count)` — 90 gün kapanan işlem sayısı. ✅ Canlı (164).
- **En İyi Rejim:** `regime_performance` win_rate'e göre sıralanıp en iyisi seçiliyor. Canlı testte "Bilinmeyen (%60)" döndü — 60 işlemin `regime` kolonu NULL. 🐛 Backfill eksiği: `/trades/backfill-regime` endpoint'i var ama çalıştırılmadığı için hero metric anlamsız etiket gösteriyor.
- **En Verimli Kontrat:** `contract_profiles[0]` — backend `total_pnl` desc sıralar. Canlı: `F_ASTOR` (+6850 TL, %87.5 WR, 8 işlem). ✅ Canlı.
- **Toplam Karar:** `recent_decisions.length` — events tablosundan son 50, sabit görünüyor. ⚠️ "Toplam Karar" yanıltıcı isim: aslında son 50 olay. Gerçek toplam değil.
- **Periyot butonları 30/90/180/365:** 🟢 `days` parametresi hem frontend'ten hem backend'ten aktif kullanılıyor — her periyot butonu farklı veri döndürür.

**🧱 Ölü API çağrısı:** `fetchData` içinde `getPerformance(days)` çağrılıyor ve `setPerf` ile state'e yazılıyor, **ama component içinde `perf` HİÇBİR YERDE OKUNMUYOR** (rgrep doğrulandı). Her periyot değişiminde backend'e gereksiz bir `/api/performance` isteği gidiyor. Kaldırılabilir.

**🧱 Yarı ölü state:** `motors` içinde `status?.phase` değeri alınıp değişkene atanıyor ama hiçbir yerde karşılaştırılmıyor — sadece `engine_running` ve `mt5_connected` kullanılıyor. `phase` dead assignment.

### 9.2 Üç Motor Panorama (BABA / OĞUL / ÜSTAT)

- Her kart yalnızca `status?.engine_running` ve `status?.mt5_connected` değerlerinden üretilir.
- BABA/ÜSTAT için kriter sadece `engine_running` → ikisi aynı anda ya yeşil ya kırmızı olur. Gerçek BABA kill-switch seviyesi, gerçek ÜSTAT cycle aktivitesi **gösterilmiyor**. 🐛 Yanlış görev: "BABA AKTİF" etiketi L2 kill-switch açıkken bile yeşil görünür (çünkü motor koşuyor).
- OĞUL için ek kriter `mt5_connected`. 🟡 Kısmi.
- `role/desc` alanları React içinde hardcode (`Kalkan / Silah / Beyin`). 🧱 Bilgi amaçlı label.

### 9.3 İşlem Kategorileri (4 mini bar chart)

- `MiniBarChart` 4 alt kategori: Sonuca / Yöne / Süreye / Rejime göre — her biri `brain.trade_categories.by_*` listesinden çiziliyor, tooltip `CategoryTip`.
- Bar rengi: `total_pnl >= 0 ? green : red`. ✅ Canlı (90 gün: by_result 2 grup, by_direction 2, by_duration 3, by_regime 5).
- **Ölü alan:** Backend `by_exit_reason` grubunu da döndürüyor (`_categorize_trades` çıktısı) ama UI'da kullanılmıyor.

### 9.4 Kontrat Profilleri

- `brain.contract_profiles.map` — her sembol için 4 kutu (İşlem / Win Rate / K/Z / Ort. Süre).
- ✅ Canlı (27 kontrat).
- 🐛 Tercih edilen yön hesaplaması **yanıltıcı**: Backend `buy_pnl >= sell_pnl` kriteriyle BUY/SELL seçiyor. Eşitlik veya hiç işlem yoksa otomatik `BUY` — yani veri yokken bile "BUY" badge'i basılabilir.
- 🐛 `preferred_direction` sıfır BUY işlemi olan bir sembolde (sadece SELL trade'leri varsa) yine `SELL` doğru çıkar ama UI "preferred" olarak sunduğu için kullanıcı bunu "gelecekte de bu yönde işlem yapılacak" gibi okur — yalnızca tarihsel istatistik.
- 🧱 Drill-down yok: Kart tıklanınca detay açmıyor; sadece özet kalıyor.

### 9.5 Karar Akışı (Timeline, son 20)

- `brain.recent_decisions.slice(0, 20)` — backend son 50 event dönderiyor, UI ilk 20'sini gösteriyor.
- ✅ Canlı (örn: "F_KONTR/M15: 2 gap tespit edildi" `severity=WARNING`, tarih bugünkü 16:46).
- `action` alanı schema'da var ama UI'da render edilmiyor. Ölü alan.
- 🐛 Timeline başlık "Karar Akışı" ama gelen veriler aslında **risk/data/system olayları** (DATA_GAP, RISK_ALERT...) — gerçek "karar" (pozisyon aç/kapat) olayı burada yok. Yanıltıcı başlık.

### 9.6 Rejim Bazlı Performans (Bar Chart)

- `brain.regime_performance` — aslında `by_regime` kategorisinin aynısı.
- ✅ Canlı ama 🐛: En büyük kova `label="Bilinmeyen"` (60 trade, -9805.99 TL). Bu, eski trade'lerde `regime` kolonu NULL olduğu için. `/trades/backfill-regime` endpoint'i backend'te var; çalıştırılmamış. Grafiğin en büyük çubuğu "Bilinmeyen" olarak kalıyor → kullanıcı hangi rejimde kaybettiğini göremiyor.
- Sağ üstte `Aktif: ${brain.strategy_pool.current_regime}` badge. Canlıda `TREND`. ✅

### 9.7 Hata Atama Paneli (Tam Genişlik)

- `ErrorAttributionPanel` — backend'in `ustat.get_error_attributions()` döndüğü listeyi ilk 15 kayıtla gösterir.
- İstatistik: toplam, BABA sayısı, OGUL sayısı, toplam zarar.
- 🟡 Fallback zorlaması: `symbol`/`pnl` yoksa `description` metninden regex ile ("F_OYAKC: ... Zarar: -25.00 TL") parse ediliyor (frontend useMemo). Bu, BACKEND RESTART ÖNCESİ eski attribution formatını kurtarmaya yarıyor — bugün restart sonrası schema zaten `symbol`, `pnl`, `exit_reason`, `risk_events` alanlarını içeriyor. Kod borcu, kaldırılabilir.
- ✅ Canlı (30 attribution). Örnek kayıt: trade_id=151, `F_OYAKC`, -25 TL, `RISK_MISS`, `responsible=BABA`, `exit_reason="| APPROVED by operator"`.
- 🐛 `exit_reason` pipe ile başlıyor ("| APPROVED by operator") — `/trades/approve` endpoint'i `exit_reason + " | APPROVED by ..."` concat yapıyor ama orijinal reason boş olduğu için pipe ile başlayan string kalıyor. Cosmetic issue.
- 🐛 "Hata Atama" 30 hatayı BABA/OĞUL sınıflandırmasıyla gösteriyor ama seçim için **manual filtre yok** — sadece ilk 15 kayıt (`raw.slice(0, 15)`). Daha eski zararlı işlem nasıl görülecek? Drill-down yok.

### 9.8 Beyin Panelleri (2 sütun)

**9.8.1 Ertesi Gün Analizi**
- `brain.next_day_analyses.slice(0, 10)` — her satırda symbol + actual_pnl + 4 alt skor (Sinyal/Yönetim/Kar/Risk) + total/100.
- ✅ Canlı (7 kayıt).
- 🧱 Placeholder metni: "Her sabah 09:30'da puanlanır" — backend'te bu cron/scheduler doğrulanmadı (sadece `ustat.run_cycle` tetikleyebilir). Zamanlama bilgisi UI'da hardcode, gerçekte doğrulanmalı.

**9.8.2 Regülasyon Önerileri**
- `brain.regulation_suggestions.slice(0, 10)` — priority + parameter + current→suggested + reason.
- ✅ Canlı (3 kayıt).
- 🧱 UI "Her akşam 18:00'da üretilir" diyor ama yine tetikleyici bilgisi doğrulanmadı.
- 🧱 Uygula/Onayla butonu yok — yalnızca gösterim. "Öneri" ama aksiyon atma yolu yok. 🐛 Pasif panel.

### 9.9 Drill-down Kontrolü

- Hiçbir kartın kendisinin tıklanabilir alt kart/modal açılımı YOK — ÜSTAT Beyin sayfası salt okunur.
- Hero metric'lere, kontrat kartına, timeline öğesine tıklama efekti bulunmuyor.

### 9.10 Bu Sayfanın Bulguları

- **🔴 Sessiz kart yok** — tüm bölümler canlı veri dönüyor.
- **🐛 Yanıltıcı görev:**
  1. "Üç Motor" kartı BABA/ÜSTAT farklılığını yansıtmıyor; kill-switch L2 iken bile "AKTIF" yeşil gösteriyor.
  2. "Karar Akışı" başlığı altında gelen veri aslında sistem/risk olayları — gerçek karar kayıtları değil.
  3. "Rejim Bazlı Performans" en büyük çubuk "Bilinmeyen" (backfill eksik).
  4. "Tercih Edilen Yön" BUY/SELL kıyasında eşitliği BUY lehine çözüp kullanıcıya "öneri" gibi sunuyor.
- **🧱 Hardcode/ölü kod:**
  1. `getPerformance(days)` fetch ediliyor, state yazılıyor, ama `perf` hiçbir yerde okunmuyor. Kaldırılmalı.
  2. `motors` içinde `status?.phase` değeri alınıp kullanılmıyor (dead assignment).
  3. `by_exit_reason` backend tarafından hazırlanıyor ama UI'da render yok.
  4. Beyin panellerinde "09:30'da / 18:00'da" zamanlama metinleri hardcode, gerçek cron doğrulaması yok.
  5. Regülasyon önerileri için "Uygula/Reddet" butonu yok — salt pasif panel.
  6. Hata atama frontend fallback (description regex parse) geri dönüşü kaldırılabilir kod borcu.
- **Drill-down:** Yok — sayfa tamamen salt okunur.

## 10. Risk Yönetimi (`/risk`)

**Dosya:** `desktop/src/components/RiskManagement.jsx` (394 satır)
**Sürükle-bırak:** Yok — sabit düzen.
**Veri kaynağı:** `getRisk()` → `GET /api/risk`, 10 sn REST polling. WS yok.
**Backend:** `api/routes/risk.py` — iki kaynak karışımı:
- `db.get_latest_risk_snapshot` — `balance`, `equity`, `daily_pnl`, `floating_pnl`, `total_drawdown_pct`
- `db.get_risk_snapshots` — hafta/ay başlangıç equity'si ile `weekly_drawdown_pct`/`monthly_drawdown_pct` anlık hesap
- `baba` canlı: kill-switch level/details, blocked_symbols, daily_trade_count, consecutive_losses, cooldown_until, rejim, risk_multiplier, `check_risk_limits()` verdict (can_trade, lot_multiplier, risk_reason)
- `engine.risk_params` — max_daily_loss, max_weekly_loss, max_monthly_loss, hard_drawdown, max_floating_loss, max_daily_trades, consecutive_loss_limit, max_open_positions
- `mt5.get_positions()` — open_positions sayısı

**Canlı test (fetch `/api/risk`):**
```
can_trade=false, kill_switch_level=2, regime=TREND, risk_multiplier=1, lot_multiplier=0
balance=38630.87, equity=38630.87, daily_pnl=0, floating_pnl=0
daily_drawdown_pct=0, weekly_drawdown_pct=0, monthly_drawdown_pct=0
total_drawdown_pct=0.304293  ← %30.43
hard_drawdown=0.15, max_daily_loss=0.018, max_monthly_loss=0.07
open_positions=1, daily_trade_count=0, consecutive_losses=0
kill_switch_details={reason:"daily_loss", triggered_at:"2026-04-11T16:10:49", message:"Günlük kayıp limiti aşıldı"}
risk_reason="KILL_SWITCH L2 aktif — sistem durduruldu"
graduated_lot_mult=1
```

### 10.1 Durum Banner (4 kart)

**10.1.1 İşlem İzni**
- ✅ Canlı. Şu an "KAPALI", `risk_reason="KILL_SWITCH L2 aktif — sistem durduruldu"` altında.
- `can_trade` BABA `check_risk_limits(risk_params)` verdict'inden gelir — gerçek risk kapısı.

**10.1.2 Kill-Switch (tıklanabilir → modal)**
- ✅ Canlı. Şu an "L2 — Sistem Pause".
- 🟢 **Drill-down mevcut:** `KillSwitchInfoModal` — Seviye, Neden (`formatKsReason` TR çeviri), Tetiklenme Zamanı (locale format), Engelli Kontratlar (liste), L0 için bilgi kutusu.
- Neden çevirisi için `KS_REASON_MAP` hardcode (12 anahtar). Backend yeni bir `reason` kodu döndürürse çeviri olmadan ham kod yazılır.
- 🐛 Modal `details.symbols` VE `blockedSymbols` prop'unun her ikisini de kontrol ediyor (double-source). API yanıtında ikisi de `[]`, L1 tetiklense biri dolu olur. Kod borç.
- 🧱 Modal salt okunur — "Sıfırla/Geri Al" butonu YOK. KS'yi bu sayfadan temizlemek mümkün değil; yalnızca TopBar'daki acknowledge mekanizması var. Bölüm sonunda çözüm ipucu eksikliği kullanıcıyı yanıltıcı olabilir.

**10.1.3 Rejim**
- ✅ Canlı (TREND). Rejim çarpanı `x${risk.risk_multiplier}` → x1.00 gösterilir.
- `REGIME_LABELS` map sadece TREND/RANGE/VOLATILE/OLAY içerir. Backend başka bir değer döndürürse default `regime-trend` class uygulanır.

**10.1.4 Lot Çarpanı**
- ⚠️ **Yanıltıcı:** UI `risk.lot_multiplier` (BABA verdict) gösterir → kill-switch aktifken bu değer **0.00** olur. Kullanıcı "Lot çarpanı 0" ifadesini "çarpan sıfırlandı" olarak yorumlayabilir, oysa anlamı "işlem yasak".
- 🧱 **Ölü alan:** Schema `graduated_lot_mult=1` döndürüyor (haftalık kayıp sonrası lot yarılama çarpanı) ama UI **hiçbir yerde göstermiyor**. Önemli risk metriği kaybı.

### 10.2 Zarar Limitleri (5 Progress Bar)

Hepsi `RiskBar` component: `current`/`limit` (fraction), renk (okay/warning/critical), doldurma `Math.min(|current|/limit, 1) * 100`.

- **Günlük Kayıp:** `daily_drawdown_pct=0` / `max_daily_loss=0.018` → %0.00 / %1.80. ✅ Canlı.
- **Haftalık Kayıp:** `weekly_drawdown_pct=0` / `max_weekly_loss=0.04` → %0.00 / %4.00. ✅ Canlı.
- **Aylık Kayıp:** `monthly_drawdown_pct ?? total_drawdown_pct` / `max_monthly_loss=0.07`.
  - 🐛 **Fallback yanıltıcı:** Backend `monthly_drawdown_pct=0` (ay başı equity'den düşüş yok), UI yine de `?? total_drawdown_pct` kullanıyor ama `0 ?? x` → 0 gelir (nullish coalescing). Şu an doğru çalışıyor AMA backend `monthly_drawdown_pct=null` döndürürse `total_drawdown_pct` devreye girer, aylık bar "toplam drawdown"u gösterir. Karmaşa riski.
- **Hard Drawdown:** `total_drawdown_pct=0.304293` / `hard_drawdown=0.15` → %30.43 / %15.00. ⚠️ **KRİTİK:**
  - 🐛 **Anayasa Kural #6 ihlali gibi görünüyor:** Hard drawdown ≥%15 → L3 otomatik. Canlı değer %30.43 ama `kill_switch_level=2` (L3 değil). İki açıklama olabilir:
    1. `total_drawdown_pct` DB `drawdown` alanı (all-time high water mark) — BABA'nın `_check_hard_drawdown` daha dar hesap yapıyor (ör. günlük equity tepesi). UI bu farkı göstermiyor.
    2. BABA'nın `_check_hard_drawdown` fonksiyonu bozulmuş veya eşik farklı.
  - Her iki durumda da **UI progress bar %100 (cap) kırmızı gösteriyor** ama sistem L3'e geçmemiş. **Kullanıcı için paradoks görseli**.
  - `Math.min(0.304/0.15, 1)` = 1 → bar %100'de sabit. Kullanıcı aşım miktarını (×2) göremiyor.
- **Floating Kayıp:** `equity>0 && floating_pnl<0 ? abs(floating_pnl)/equity : 0` / `max_floating_loss=0.015`.
  - Canlı `floating_pnl=0` → %0. Ama F_ASELS hibrit açık ve Monitor raporunda pozisyon zarar ediyor.
  - 🐛 **Stale data:** Floating P&L DB snapshot'ından geliyor — anlık MT5 equity değişimini yansıtmıyor. Dashboard'da 2sn WS ile güncelleniyor ama Risk sayfası 10sn DB polling'e takılı. Canlı değer ile snapshot'un son kayıt arası gecikme olur.

### 10.3 Sayaçlar (4 kart)

- **Günlük İşlem:** 0/5 — `daily_trade_count / max_daily_trades`. ✅ Canlı.
- **Üst Üste Kayıp:** 0/3 — `consecutive_losses / consecutive_loss_limit`. ≥ limit olunca kırmızı class. ✅ Canlı.
- **Açık Pozisyon:** 1/5 — MT5 canlı (F_ASELS hibrit). ✅ Canlı.
- **Cooldown:** `risk.cooldown_until || 'Yok'` — şu an "Yok".
  - 🧱 Backend ISO string döndürür (örn. `"2026-04-11T17:30:00"`). UI hiç parse etmiyor → kullanıcı çıplak ISO görür. Locale format uygulanmalı.

### 10.4 Anlık Durum (4 kart)

- **Günlük K/Z:** `daily_pnl=0` → "0 TRY". ✅
- **Floating K/Z:** `floating_pnl=0` → "0 TRY". 🐛 Yukarıdaki floating bar ile aynı stale sorunu — F_ASELS kaçak gösterim.
- **Bakiye:** `balance=38630.87` → "38.630,87 TRY". ✅ Canlı (formatMoney).
- **Toplam Drawdown:** `pct(total_drawdown_pct)` → "%30.43". ✅ Canlı.
  - `pct` helper fraction → `%XX.XX` çevirir, doğru.

### 10.5 Bu Sayfanın Bulguları

- **🔴 Sessiz kart yok** — tüm değerler backend'ten geliyor.
- **🐛 Kritik mantık sorunu:** Hard drawdown %30.43 gösterirken kill-switch L2'de sabit. Ya schema alan adı yanlış (`total_drawdown_pct` != hard drawdown), ya da BABA hard drawdown kuralı ihlal ediliyor. **Bu bulgu kendi başına acil soruşturma gerektirir** (Anayasa Madde 4.5 #6).
- **🐛 Floating P&L stale:** 10 sn DB snapshot polling ile anlık kayıp gösterilmiyor. Risk sayfasının WS'e bağlanması veya `/api/risk` endpoint'inin canlı MT5 equity kullanması gerekir.
- **🐛 Lot Çarpanı anlam karmaşası:** Kill-switch aktif → `lot_multiplier=0`. "Çarpan 0" kullanıcıya "lot yarılanmış" gibi okunur, aslında "işlem kapalı" anlamına gelir. Ayrıca `graduated_lot_mult` (haftalık lot yarılama) tamamen gösterilmiyor.
- **🐛 Aylık Kayıp fallback riski:** `monthly_drawdown_pct ?? total_drawdown_pct` ile 0/null ayrımı net değil; backend null gönderirse bar anlamsız yüksek olur.
- **🧱 Hardcode/ölü alanlar:**
  1. `KS_REASON_MAP` sadece 12 kod — yeni reason girildiğinde çeviri yok.
  2. `REGIME_LABELS` sadece 4 değer.
  3. Cooldown ISO string parse edilmiyor.
  4. Kill-Switch modal'da "Sıfırla" butonu yok — salt bilgi.
  5. `graduated_lot_mult` UI'da yok.
- **🟢 Drill-down:** SADECE Kill-Switch kartı tıklanınca `KillSwitchInfoModal` açılıyor. Diğer 7 kart (rejim, lot, 5 bar, 4 sayaç, 4 PNL) tıklanamaz.

## 11. Sistem Monitörü (`/monitor`)

**Dosya:** `desktop/src/components/Monitor.jsx` (825 satır)
**Sürükle-bırak:** Yok — sabit inline-CSS düzeni (kendi `<style>` blok'u var).
**Veri kaynağı:** 6 paralel çağrı her 10 saniyede (`POLL_MS=10000`) — `getHealth`, `getStatus`, `getRisk`, `getAccount`, `getPositions`, `getEvents({limit:20})`. Ek olarak 1 sn'lik yerel saat + VİOP seans timer.

🐛 **Yorum/gerçeklik farkı:** Kod yorumu "3 sn API poll" diyor ama `POLL_MS = 10000`. Dokümantasyon güncel değil.

**Backend:** `api/routes/health.py` — tek endpoint `engine.health.snapshot()` + katman öznitelikleri + DB son olayları + MT5 `is_trade_allowed()` döndürür. `/events` `/risk` `/account` `/positions` `/status` ayrı endpoint'ler.

**Canlı test (fetch `/api/health`):**
```
cycle: avg_ms=2871.8, max_ms=4878.1, overrun=0,
  steps: baba=122.4, data_update=2596.8, ogul=10.2, ustat=3.2, h_engine=4.4
mt5: last_ping_ms=1.6, trade_allowed=false, disconnect_count=0, uptime=2559s
orders: success=0, reject=0, timeout=0, last_10=[]
layers.baba: kill_switch_level=2, regime=TREND, risk_multiplier=1, confidence=0.6
layers.ogul: active_trade_count=0, daily_loss_stop=true, universal_management=true
layers.h_engine: active_hybrid_count=1, daily_limit=500, daily_pnl=0, native_sltp=false
layers.ustat: last_run_time="2026-04-11T16:53:19"
system: cache_stale=false, cycle_count=256, db=67.71MB, uptime=2573s, ws_clients=1
alarms: consecutive_rejects=0, last_reject_reason=""
```

### 11.1 Header [A] + Kill-Switch Banner

- Başlık: "ÜSTAT · System Monitor"
- Sağ tarafta: VİOP AÇIK/KAPALI (yerel hesap, 09:30-18:15 hardcode), SİSTEM AKTİF/PASİF, KILL-SWITCH Lx (killLevel>0 ise), yerel saat.
- 🧱 VİOP seans hesabı hardcode `mins >= 570 && mins < 1095`. Tatil/DST/session break algılamaz.
- ✅ `killLevel = max(status.ks_level, risk.ks_level)` — iki kaynaktan en yükseği. Şu an L2 banner gösterilir.

### 11.2 Emir Red Alarmı

- `alarms.consecutive_rejects >= 2` olduğunda pulse banner.
- ✅ Canlı (şu an 0 → gizli). Backend `engine.health.snapshot().alarms` üretir.

### 11.3 Stats Bar [B] — 6 Kart

Her kart `StatCard` component'i:
- **GÜNLÜK P&L:** `account.daily_pnl` → formatMoney. ✅ Canlı.
- **AKTİF POZİSYON:** `positions.count` + ilk 3 sembol (`F_` ve son 4 hane vade kodu strip edilerek). ✅ Canlı. (Şu an 1, "ASELS")
- **DRAWDOWN:** `daily_drawdown_pct*100` / `max_daily_loss*100`. Renk `> limit*0.5 ? warn : green`. ✅ Canlı.
- **MT5 PİNG:** `mt5.last_ping_ms`ms. ✅ Canlı (1.6ms).
- **DÖNGÜ SÜRESİ:** `cycle.avg_ms`ms. **Renk: `cycleAvg > 50 ? red : teal`.**
  - 🐛 **KRİTİK Eşik sorunu:** Canlı avg_ms = 2871.8 (data_update ağırlıkta). Eşik 50ms gerçekçi değil → kart sürekli kırmızı. Kullanıcı "döngü bozuk" algılar ama `overrun_count=0` (backend sorun görmüyor). Eşik 10000ms (CYCLE_INTERVAL) veya data_update hariç hesaplanmalı.
- **UPTIME:** `system.engine_uptime_seconds ?? status.uptime_seconds` + `cycle_count`. ✅ Canlı (2573s = 42dk / 256 döngü).

### 11.4 Flow Diagram [C] — Mimari Paneli

Kompleks SVG + flex layout: MT5 üstte, altında 4 modül kolonu (BABA/OĞUL/H-ENGINE/MANUEL) birbirine oklarla bağlı, en altta geniş ÜSTAT kartı BABA ↔ OĞUL arası dikey çift yön bağlantılarla.

**11.4.1 MT5 Üst Kutusu**
- 4 metrik: BAĞLANTI (✓ CANLI / ✗ KOPUK), PİNG, KOPMA (`mt5.disconnect_count`), UPTIME. ✅ Canlı.

**11.4.2 BABA Kolonu**
- Metric: `L${killLevel}` (L2 şu an), Label: KİLL-SWİTCH.
- Details: BLOKE sembol sayısı, DD LİMİT, REJİM (`layers.baba.regime`), HATA (bugün event mesajından parse).
- 🐛 `modStatus.baba` `killLevel >= 3 ? err : killLevel > 0 ? warn : ok`. L2 = warn. Doğru.
- 🐛 **errorCounts parse yöntemi kırılgan:** `recent_events.forEach → msg.toLowerCase().includes('baba')` substring araması. İlgisiz mesaj "baba" geçiyorsa yanlış pozitif. Daha önce "ogul|oğul" arama var — büyük/küçük harf garanti değil (toLowerCase sonrası 'oğul' geçer mi Unicode'da?).

**11.4.3 OĞUL Kolonu**
- Metric: `layers.ogul.active_trade_count` (0), AKTİF İŞLEM.
- Details: sembol sayısı, KAYIP STOP (`daily_loss_stop` → AKTİF/KAPALI, şu an AKTİF kırmızı), EMİR OK, RED/TMOUT, HATA.
- 🐛 `daily_loss_stop` OĞUL'da canlıda `true`. Anayasa Madde 4.5 #10'a göre günlük/aylık kayıp BABA'ya devredildi; `daily_loss_stop` OĞUL'da hâlâ okunuyor. Ya legacy bayrak, ya da OĞUL side-effect. Monitor bunu gösteriyor ama gerçek etki bilinmiyor.

**11.4.4 H-ENGINE Kolonu**
- Metric: `layers.h_engine.active_hybrid_count` (1), HİBRİT POZ.
- Details: GÜNLÜK P&L (canlı: 0 TL), LİMİT (500 TL), HATA.
- `fill` bar: `|daily_pnl| / daily_limit * 100`. Şu an 0.
- 🐛 `native_sltp=false` değeri backend'de var ama Monitor'da gösterilmiyor — kullanıcı Hibrit sayfasındaki "Yazılımsal SL/TP" bilgisini burada tekrar göremiyor.

**11.4.5 MANUEL Kolonu**
- Metric: `risk.daily_trade_count`, GÜNLÜK EMİR.
- Details: MAKSİMUM, ARD. KAYIP, HATA.
- 🐛 **`modStatus.manuel = 'ok'` SABİT HARDCODE** — manuel motor hatası hiç warn/err göstermez. 🧱

**11.4.6 ÜSTAT Geniş Alt Kart**
- Metric: `cache_stale ? '⚠' : '✓'`, CACHE DURUMU.
- Details: SON ÇALIŞMA, DB BOYUT, **`['MT5', 'BAĞLANTI YOK', '#556680']` SABİT HARDCODE**, HATA.
- 🧱 **Ağır bug:** Her durumda "MT5 BAĞLANTI YOK" yazıyor — `mt5Connected` state var ama ÜSTAT kart detail'ında kullanılmıyor. Yanıltıcı bilgi (MT5 aslında bağlı).
- 🐛 `last_run_time` ISO string → `fmtTime` new Date() ile parse. ISO "2026-04-11T16:53:19" (TZ yok) → local time olarak parse edilir, doğru.

### 11.5 Emir Akış Tablosu [D]

- `orders.last_10` → Zaman, Kontrat, Yön, Durum (FILLED/TIMEOUT/RED), Süresi, Kayma.
- Canlı: `last_10=[]` → "Henüz emir yok" boş durum. ✅ Doğru davranış (L2 aktifken yeni emir yok).
- `fmtTimestamp(unixTs)` unix timestamp saniye → HH:MM:SS. ✅

### 11.6 Log Akışı [E1]

- `events` state `getEvents({limit:20})` — 20 satır, severity'ye göre renk (ok/info/warn/error).
- Her satırda timestamp (HH:MM:SS) + mesaj (tek satır, overflow ellipsis).
- ✅ Canlı. 20 event geldi.
- 🧱 **Drill-down yok:** Event satırına tıklanınca detay açılmıyor, filtre/arama yok. Uzun mesaj `whiteSpace:nowrap` ile kesiliyor — tam metni görmek için `/errors` sayfasına gitmek gerek.

### 11.7 Performans [E2]

`ResponseBar` bar'lar — her adımın `steps.*` süresini `max` değeriyle karşılaştırır:

| Bar | max (ms) | Canlı | Sorun |
|-----|---------|-------|-------|
| BABA DÖNGÜ | 50 | 122.4 | 🐛 %100+ cap kırmızı |
| OĞUL SİNYAL | 100 | 10.2 | ✅ %10 |
| ÜSTAT BEYİN | 50 | 3.2 | ✅ |
| H-ENGINE | 50 | 4.4 | ✅ |
| VERİ GÜNCELLEME | 100 | 2596.8 | 🐛 **%2596!** |
| TOPLAM DÖNGÜ | 300 | 2739.3 | 🐛 %913 |

- 🐛 **KRİTİK eşik sorunu:** `max` değerleri gerçek sistemle uyumsuz. Veri güncelleme adımı 2.6 sn sürüyor (data_update ağırlıklı) ama bar max=100 olduğu için bar hep %100'de sabit. Kullanıcı darboğazı fark edemez — değer yazıyor ama bar visual bilgi vermiyor.
- 🐛 BABA DÖNGÜ adımı (122.4ms) max=50 için %244 → cap, kırmızı. Normal bir sürede çalışıyor ama "alarm" görünüyor.
- DÖNGÜ İSTATİSTİK alt grid: ORT/MAX/AŞIM. ✅ Canlı.
  - `cycle.max_ms > 100 ? warn : ok` — canlı 4878ms → warn. Yine gerçekçi olmayan eşik.
  - `overrun_count > 0 ? red : green` — şu an 0, yeşil. Bu eşik backend tanımlı.

### 11.8 Risk & Kill-Switch [E3]

**11.8.1 L1/L2/L3 Kutuları**
- 3 kutu: L1 UYARI, L2 DURDUR, L3 KRİTİK. `killLevel >= lvlNum` olunca kırmızı.
- Yüzde etiketi: `(limDaily * 0.5/0.75/1).toFixed(1)` → yaklaşık eşikler.
- 🐛 **Hardcode yaklaşık eşik:** Gerçek BABA L1/L2/L3 eşikleri farklı. `config/default.json` risk parametreleri kontrol edilmeli; UI "yaklaşık" olduğunu yazmıyor, kullanıcı gerçek eşik sanar.

**11.8.2 Drawdown Barları**
- GÜNLÜK DD / HAFTALIK DD / FLOATING P&L. ✅ Canlı ama 🐛 aylık drawdown burada YOK (Risk sayfasında var).

**11.8.3 Hata Sayacı · Bugün**
- 5 modül (BABA/USTAT/OGUL/HENGINE/MANUEL) grid. `errorCounts` substring match sonucu.
- 🐛 Kırılgan parse yöntemi + `manuel` ve `ustat`/`üstat` Türkçe karakter uyumu riski.

### 11.9 Drill-Down Kontrolü

- Modül kartları hover'da yukarı kayıyor (`transform: translateY(-3px)`), **tıklanma etkisi YOK**. Kullanıcı kart detayını göremez.
- Log akışı öğeleri tıklanamaz.
- L1/L2/L3 kutuları tıklanamaz — Risk sayfası aksine modal açmıyor.
- **Monitor tamamen salt okunur — tıklanabilir hiçbir aksiyon yok.**

### 11.10 Bu Sayfanın Bulguları

- **🔴 Sessiz kart yok** — tüm değerler backend'ten geliyor, ÜSTAT kart ve `modStatus.manuel` hariç.
- **🐛 Yanıltıcı eşikler (6 yer):**
  1. DÖNGÜ SÜRESİ stat card kırmızı eşiği 50ms → gerçek 2871ms, sürekli kırmızı.
  2. Performans bar'larında BABA/DATA/TOTAL max değerleri gerçekte aşılıyor, bar'lar visual bilgi vermiyor.
  3. DÖNGÜ İSTATİSTİK MAX alarmı 100ms → canlı 4878ms → sürekli warn.
  4. L1/L2/L3 kutularının "% eşiği" yaklaşık hesap, gerçek BABA eşikleri farklı olabilir.
  5. BABA DÖNGÜ max=50ms ama adım 122ms — her zaman kırmızı.
  6. "Döngü aşımı yok" (overrun=0) diyor ama UI "ortalama 2871ms → kırmızı" diyor. İki kaynak çelişiyor.
- **🐛 ÜSTAT kartında MT5 bilgisi hardcode "BAĞLANTI YOK"** — MT5 gerçekten bağlı olsa bile yanlış gösterir.
- **🐛 `modStatus.manuel = 'ok'` sabit** — manuel modülde hata hiç yansımaz.
- **🐛 `errorCounts` substring parse kırılgan** — false positive/negative riski yüksek.
- **🐛 `POLL_MS=10000` ile yorum "3sn" çelişiyor** — dokümantasyon.
- **🐛 OĞUL `daily_loss_stop=true`** Anayasa 4.5 #10 ile yeniden yapılandırma sonrası legacy bayrak olarak görünüyor; merkezileştirme tamamlanmamış.
- **🧱 Hardcode:**
  1. VİOP seans 09:30-18:15 (tatil/DST yok).
  2. ÜSTAT kart `MT5 BAĞLANTI YOK` sabit.
  3. `modStatus.manuel = 'ok'` sabit.
  4. `ksLevels.pct` hesabı yaklaşık.
  5. ResponseBar max değerleri.
  6. DÖNGÜ SÜRESİ kırmızı eşiği 50ms.
- **Drill-down:** Hiçbir kart/log satırı tıklanamaz. Monitor salt okunur.

## 12. Hata Takip (`/errors`)

**Dosya:** `desktop/src/components/ErrorTracker.jsx` (643 satır)
**Route:** `api/routes/error_dashboard.py` (661 satır)
**Veri kaynağı:** `database/trades.db::events` tablosu (son 7 gün, WARNING+) + `database/trades.db::error_resolutions` tablosu (manuel çözümleme kayıtları) + in-memory `engine.error_tracker` (ikincil).
**Poll:** 15sn (`POLL_INTERVAL`). Filtre değişikliği anında yeniden çeker.
**Üç endpoint paralel:** `/api/errors/summary`, `/api/errors/groups`, `/api/errors/trends`.

### 12.1 Başlık + EOD Geri Sayım

| Öğe | Kaynak | Görev | Karar |
|-----|--------|-------|-------|
| "Hata Takip Paneli" | Sabit başlık | — | ✅ |
| `EodBadge` | `getEodInfo()` — tamamen frontend (Date + hardcode saat sabitleri) | VİOP 09:30–18:15 arası, 17:45 EOD'ye kalan süreyi gösterir; hafta sonu "PİYASA KAPALI". | ⚠️ Hardcode — backend zamanlaması değil yerel saat. `VIOP_OPEN/CLOSE/EOD` sabitleri dosya başında. Tatil/yarım gün tanınmaz. |
| `Tümünü Çözümle` butonu | `resolveAllErrors()` → `POST /api/errors/resolve-all` | Tüm açık `error_type`'ları `error_resolutions` tablosuna yazar. | ✅ Canlı — toplu çözümleme DB'ye kalıcı yazılır. |

### 12.2 Özet Kartları (4 adet — `StatCard`)

| Kart | Alan | Kaynak | Karar |
|------|------|--------|-------|
| Bugün Hata | `summary.today_errors` / `total_errors` | `events WHERE severity IN (ERROR, CRITICAL) AND timestamp >= bugün` (son 7 gün içinden) | ✅ Canlı |
| Bugün Uyarı | `summary.today_warnings` / `total_warnings` | `events WHERE severity = WARNING` | ✅ Canlı |
| Açık Gruplar | `summary.open_groups` / `resolved_groups` | `error_type` başına `last_seen` vs `error_resolutions.resolved_at` karşılaştırması (24 saat tolerans) | ✅ Canlı |
| Bu Saat | `summary.this_hour_count` / alt satır `total_critical > 0 ? "N kritik" : "stabil"` | Son 1 saat içindeki tüm WARNING+ eventler | ✅ Canlı |

**Canlı gözlem (`/api/errors/summary`):** `today_errors=6`, `today_warnings=129`, `this_hour_count=106`, `total_critical=27`, `total_errors=48`, `total_warnings=4952`, `open_groups=9`, `resolved_groups=11`. Latest error: `KILL_SWITCH` — "Kill-switch L2 aktif: daily_loss" (16:10:50).

**🧱 Mimari not:** `_fetch_events_from_db(limit=5000)` — 7 günlük WARNING+ olay sayısı 5000'i aşarsa eski kayıtlar düşer, özet eksik çıkar. Bu denetimde `by_severity.WARNING=4952` → eşiğe çok yakın. Yüksek frekanslı WARNING akışında (her saat 124 tepe) limit mutlaka aşılır ve özet kayar.

### 12.3 Kategori Dağılımı

**Bileşen:** `CategoryBadge` × N — `summary.by_category` üzerinden dinamik.
**Kaynak:** `EVENT_TYPE_CATEGORY` sözlüğü (66 giriş) `event_dashboard.py` içinde. Bilinmeyen tipler "sistem" kategorisine düşer.

**Canlı gözlem:** `{"bağlantı":2, "risk":52, "sistem":4946}` — **4946 olay "sistem" kategorisine düşmüş.** Bu yanıltıcı: gerçekte `TRADE_ERROR`, `SYSTEM_STOP`, başka tipler de "sistem" altında toplanıyor çünkü `EVENT_TYPE_CATEGORY` sözlüğünde `TRADE_ERROR` anahtarı YOK. Örnek: canlı grup listesinde `TRADE_ERROR` (9 tekrar) "sistem" kategorisinde görünüyor ama semantik olarak "emir" olmalıydı.

| Bulgu | Sonuç |
|-------|-------|
| 🐛 `TRADE_ERROR` kategori eşlemesi eksik | "emir" yerine "sistem"'e düşüyor |
| 🐛 `SYSTEM_STOP` kategori eşlemesi eksik | "sistem" — bu tesadüfen doğru |
| 🧱 "emir", "sinyal", "netting", "veri" kategorileri canlı dağılımda **hiç görünmüyor** | Filtrede seçildiğinde tablo boş kalıyor |

### 12.4 Hata Trendi Grafiği

**Bileşen:** 24 bar × `div` (saatlik) veya N bar (günlük). `trendPeriod` state ile `hourly` / `daily` toggle.
**Renk eşiği:** `val > 5 → kırmızı`, `> 2 → turuncu`, aksi → yeşil (hardcode).
**UI → API:** `getErrorTrends({period})` → `/api/errors/trends?period=hourly&hours=24`

**Canlı gözlem (`period=hourly, hours=24`):** 24 saatlik barın sadece 4'ü dolu; tepe `124 olay/saat`. Renk eşiği `>5 kırmızı` → neredeyse her dolu saat kırmızı görünüyor; eşik, mevcut WARNING yoğunluğu için anlamsız.

**Karar:** ⚠️ Canlı veri akıyor ama **hardcode renk eşiği** (5/2) sistemin gerçek gürültü seviyesinde değersiz. Config'den okunmuyor.

### 12.5 Filtreler

| Filtre | Değer | Arka uç | Karar |
|--------|-------|---------|-------|
| Kategori | `''` + 7 sabit seçenek (bağlantı/emir/risk/sinyal/netting/veri/sistem) | `/api/errors/groups?category=...` | ✅ Server-side filtre çalışıyor |
| Severity | `''` + 3 seçenek (CRITICAL/ERROR/WARNING) | `/api/errors/groups?severity=...` | ✅ Server-side filtre çalışıyor |
| Çözümlenenleri göster (checkbox) | `filterResolved` | `resolved=undefined` (göster) veya `resolved=false` (gizle) | ✅ Çalışıyor |

**Not:** `FilterSelect` seçenek listesi hardcode. Backend dinamik kategori sağlıyor (`summary.by_category`) ama frontend sabit listeyle çalışıyor. `"diğer"` ve `"bağlantı"` (summary'de canlı 2 adet var) listede olduğu halde veri dağılımıyla çelişebilir.

### 12.6 Hata Grupları Tablosu

**Kolonlar:** SEVİYE · KATEGORİ · TİP · MESAJ · TEKRAR · SON · İŞLEM

**Canlı gözlem (`/api/errors/groups?limit=5`):**

| Tip | Kategori | Sev | Tekrar | Çözümlü | Mesaj |
|-----|----------|-----|--------|---------|-------|
| KILL_SWITCH | risk | CRITICAL | 25 | Hayır | Kill-switch L2 aktif: daily_loss |
| DRAWDOWN_LIMIT | risk | CRITICAL | 12 | Hayır | Toplam drawdown: %30.43 |
| SYSTEM_STOP | sistem | CRITICAL | 1 | Evet | MT5 bağlantısı kurtarılamadı — sistem durduruluyor |
| DAILY_LOSS_STOP | risk | CRITICAL | 1 | Evet | equity=45160 balance=46575 pnl=-3.04% |
| TRADE_ERROR | sistem | ERROR | 9 | Evet | Emir başarısız: F_EKGYO BUY 1.0 lot |

**Karar:** ✅ Canlı — gruplama, sıralama (severity → count desc), mesaj tooltip, `Çözümle` butonu hepsi çalışıyor. `resolveError(type, msg.slice(0,80))` → `/api/errors/resolve` → `error_resolutions` tablosuna yazıyor.

**🐛 Ufak tutarsızlık:** `_is_resolved` 24 saat toleransı kuralı — çözümlenmiş bir tip son 24 saat içinde tekrar event atarsa "hâlâ çözümlü" sayılıyor. UI'da `res: true` görünüyor ama `count` sonradan gelen eventleri de sayıyor → kullanıcı yanılabilir (`9 TRADE_ERROR / çözümlü` ama aslında 24 saat içinde yeni hatalar geliyor).

**🐛 Hidden/ghost mesaj uyuşmazlığı:** `groups_map` aynı `error_type` için son eventin `message`'ını tutuyor (en güncel). Eğer aynı tipte farklı mesajlar varsa kullanıcı sadece sonuncuyu görüyor; eski farklı mesaj kaybolur.

### 12.7 En Son Hata Kartı

**Gösterge:** Sadece `summary.latest_error` varsa görünür, kırmızı çerçeveli kart.
**Kaynak:** Summary endpoint — `sev in (ERROR, CRITICAL)` olan ilk event.
**Karar:** ✅ Canlı.

### 12.8 Drill-down Kontrolü

**Bulgu:** **Hiçbir kart tıklanamıyor.** `StatCard`'ların `onClick` yok, `CategoryBadge`'ler pasif, tablo satırı tıklanmıyor (tek etkileşim "Çözümle" butonu). Tooltip (hover → tam mesaj) mevcut. Sayfa içinden başka bir panele zıplama yok.

**Kullanıcının istediği anlamda drill-down YOK:** "karta tıklayınca yeni kartlar çıkıyor mu?" → hayır, Hata Takip sayfası tek seviyeli.

### 12.9 Sayfa Bulguları

- **🧱 5000 event limiti:** `_fetch_events_from_db(limit=5000)` — mevcut WARNING akışı (saat tepesi 124, gün toplamı ≥129) 7 gün × 5000 sınırını delebilir. Panele girmeyen eski eventler kayboluyor.
- **🐛 Kategori eşleme eksik:** `EVENT_TYPE_CATEGORY` sözlüğünde `TRADE_ERROR` anahtarı yok. Canlı sistemde 9 adet `TRADE_ERROR` "sistem" kategorisine düşmüş, oysa semantik "emir". Sonuç: Emir filtresinde TRADE_ERROR görünmez.
- **🧱 Trend renk eşiği hardcode:** `val > 5 kırmızı, > 2 turuncu` — tüm dolu saatler kırmızı oluyor. Config'den gelmeli ya da yüzdelik olmalı.
- **🧱 EOD sabitleri hardcode:** `EOD_CLOSE_HOUR=17`, `EOD_CLOSE_MIN=45` vb. — backend'ten gelmiyor, hatta `config/default.json` değerleriyle de eşleşme garantisi yok. Tatil günleri tanınmaz.
- **🧱 Filtre seçenekleri sabit:** 7 kategori + 3 severity hardcode dropdown. Backend zaten `by_category` gönderiyor ama kullanılmıyor.
- **🐛 24 saat tolerans tutarsızlığı:** Çözümlenmiş bir `error_type` için yeni event gelse bile 24 saat boyunca "çözümlü" görünüyor. Count artıyor ama kullanıcı yeni hatadan haberdar olamaz.
- **🐛 Gruplandırma mesaj kaybı:** Aynı `error_type` altındaki farklı mesajlar "son gelen" ile override edilir — eski hatalar silinir.
- **🔴 Drill-down yok:** Tablonun üstündeki kartlar ve kategori rozetleri tıklanamaz, modal açmaz. Sayfa tek katman.
- **🧱 Resolve butonu `message_prefix = msg.slice(0,80)`:** Backend bu parametreyi sadece `tracker.resolve_group`'a gönderiyor ama `error_resolutions` tablosuna yazılırken mesaj tamamen yok sayılıyor — `error_type` bazlı çözümleme. Yani farklı mesajlı aynı tipteki tüm hatalar aynı anda "çözümlü" oluyor. Kullanıcı tek bir satırı çözümlediğini sanıyor, oysa tüm tipi çözümlüyor.
- **✅ Gerçek veri akıyor:** Kill-switch, Drawdown, Daily loss, System stop — hepsi gerçek engine eventleri. Çözümleme kalıcı (`error_resolutions`).


## 13. NABIZ (`/nabiz`)

**Dosya:** `desktop/src/components/Nabiz.jsx` (564 satır)
**Route:** `api/routes/nabiz.py` (270 satır) — `GET /api/nabiz`
**Poll:** 10sn
**Veri kaynağı:** `db.get_table_sizes()` + `shutil.disk_usage()` + `os.stat()` (log dizini) + `engine.config.retention.*`
**Prensip:** Sadece OKUMA, hiçbir şeyi değiştirmez.

### 13.1 Üst Özet Kartları (4 adet — `SummaryCard`)

| Kart | Alan | Durum Eşiği | Canlı Değer | Karar |
|------|------|-------------|-------------|-------|
| VERİTABANI | `db.file_size_mb` + WAL + total_rows | >1000 err, >500 warn | 65.13 MB + WAL 65.38 MB + 353.807 satır | ✅ Canlı — yeşil |
| LOG DOSYALARI | `logs.total_size_mb` + dosya sayısı | >2000 err, >500 warn | **6111 MB (6.1 GB)** — 40 dosya | ⚠️ **Canlı + KIRMIZI uyarı:** Threshold 2000 MB aşıldı 3 kat. |
| DİSK ALANI | `disk.free_gb` + `usage_pct` + total | >90% err, >80% warn | 657.1 GB boş / 953 GB · %31.1 | ✅ Canlı |
| RETENTION | `retention.enabled` + `last_retention_date` | `enabled ? ok : err` | AKTİF · Son: 2026-04-11 | ✅ Canlı |

**🧱 Hardcode threshold:** SummaryCard eşikleri bileşen içinde sabit (500/1000 MB, 80/90 %). Config'den okunmuyor.

### 13.2 Çakışma Uyarısı (`ConflictWarning`)

**Bileşen:** Sadece `cleanup_conflict.has_conflict === true` ise görünür (tıklayınca genişler).
**Kaynak:** `_build_cleanup_conflict_info(engine)` — retention kapalıysa "cakisma" oluşur.
**Canlı durum:** `has_conflict=false` → bileşen görünmüyor.
**Karar:** ✅ Canlı — retention açık olduğundan uyarı gizli.

**Drill-down:** Kullanıcı başlığa tıklarsa açılır/kapanır (expand/collapse). İçerik: `affected_tables` tablosu (cleanup_days, retention_days, risk).

### 13.3 Veritabanı Tabloları Paneli (`TableSizesPanel`)

**Kaynak:** `database.file_size_mb` + `db.table_sizes` objesi. Frontend tablo boyutlarını `TABLE_THRESHOLDS` sözlüğüyle karşılaştırıp renk atar.

**Canlı tablolar (sıralı):**

| Tablo | Satır | Threshold (warn/danger) | Renk | Retention? |
|-------|-------|-------------------------|------|------------|
| bars | 183.078 | 50.000 / 150.000 | **🔴 Kırmızı** | ❌ YOK |
| risk_snapshots | 106.426 | 20.000 / 100.000 | **🔴 Kırmızı** | ✅ var |
| events | 60.285 | 10.000 / 50.000 | **🔴 Kırmızı** | ✅ var |
| top5_history | 3.142 | 5.000 / 20.000 | ✅ Yeşil | ✅ var |
| hybrid_events | 426 | 2.000 / 10.000 | ✅ Yeşil | ❌ YOK |
| trades | 215 | 5.000 / 20.000 | ✅ Yeşil | ✅ (trade_archive) |
| notifications | 117 | 2.000 / 10.000 | ✅ Yeşil | ❌ YOK |
| manual_interventions | 50 | 200 / 1.000 | ✅ Yeşil | ❌ YOK |

**Karar:** ✅ Canlı — sıralama ve renk hesabı gerçek veri üzerinden. 3 tablo kırmızı eşiğin üzerinde.

**🧱 Hardcode eşikler:** `TABLE_THRESHOLDS` bileşen içinde sabit. Backend bu eşikleri göndermiyor, frontend kendi karar veriyor. Config'den gelmiyor.
**🐛 `bars` tablosu retention kapsamında değil ama `_build_cleanup_conflict_info` retention açık olduğundan `has_conflict=false` raporluyor — `bars` kırmızı alarm olmasına rağmen `ConflictWarning` paneli görünmüyor. Anlamsal çelişki.**

### 13.4 Log Dosyaları Paneli (`LogFilesPanel`)

**İçerik:** İlk 15 dosya (sıralama backend'te `sorted(reverse=True)`) — tablo formatında.
**Alanlar:** Dosya adı · Boyut · Güncelleme tarihi
**Canlı gözlem:**
- Toplam 40 dosya, 6111 MB
- En yeni: `ustat_2026-04-11.log` — 20.14 MB (aktif gün)
- 2026-04-10: 67.45 MB · 2026-04-09: 86.22 MB · 2026-04-08: 86.77 MB · 2026-04-07: **137.25 MB**

**Karar:** ✅ Canlı — veri doğru görünüyor.

**🧱 Gizli bulgular:**
- Günlük log 50-137 MB arası. Logger log rotasyonu etkin değil/çok gevşek görünüyor.
- Backend log listesi sıralı ama "ilk 15" ile kesiliyor → 40 dosyadan 25'i UI'da görünmüyor (log birikimi gizlenir).
- `/api/nabiz` log boyutu hesabı `total += size (bytes)` sonra `/1024**2` — toplama doğru ama frontend `formatBytes(6111)` çağrısı → 5.97 GB olarak gösterir; eşik "> 2 GB" → kırmızı alarm tetiklenir.

### 13.5 Retention Ayarları Paneli (`RetentionConfigPanel`)

**İçerik:** 9 retention anahtarı (risk_snapshots_days, top5_history_days, events_info/warning/error_days, config_history_days, liquidity_days, hybrid_closed_days, trade_archive_days) + `last_retention_date` + `last_cleanup_date`.
**Canlı:** `enabled=true`, son cleanup ve retention = 2026-04-11 (bugün).
**Karar:** ✅ Canlı — config değerleri ve son çalışma tarihleri gerçek.

### 13.6 Eksik Retention Paneli (`MissingRetentionPanel`)

**Gösterge:** Sadece `cleanup_conflict.missing_retention.length > 0` ise görünür. Grid format, sarı tema.
**Canlı gözlem (5 tablo):**

| Tablo | Satır | Büyüme |
|-------|-------|--------|
| bars | 183.078 | buyuyor |
| hybrid_events | 426 | buyuyor |
| notifications | 117 | buyuyor |
| manual_interventions | 50 | düşük |
| daily_risk_summary | 10 | düşük |

**Karar:** ✅ Canlı — panel görünür ve doğru listeliyor.

**🔴 Kritik mimari bulgu:** `bars` tablosu 183.078 satırla kırmızı eşiğin üzerinde VE retention kapsamında değil. Bu tablo büyümeye devam edecek ama cleanup kapsamında (kod yorumu: "v5.9.3: Cleanup artik sadece bars temizliyor") → anlamsal çelişki: yorum bars'ı cleanup'ın temizlediğini söylüyor, ama `retention_covered` setinde bars yok ve uyarı paneli bars için `retention YOK` diyor. Kullanıcı kafa karışıyor: bars gerçekten temizleniyor mu, temizlenmiyor mu?

### 13.7 Drill-down Kontrolü

- `SummaryCard` → tıklanamaz (onClick yok).
- `ConflictWarning` → tıklayınca genişler/daralır (`expanded` state) ✅
- `TableSizesPanel` satırları → tıklanamaz.
- `LogFilesPanel` satırları → tıklanamaz.
- `RetentionConfigPanel` alanları → tıklanamaz.
- `MissingRetentionPanel` grid → tıklanamaz.

Sadece ConflictWarning accordion çalışır; **o da canlı gizli** (has_conflict=false). Pratikte sayfa tamamen statik bir dashboard.

### 13.8 Sayfa Bulguları

- **🔴 LOG RESİM BOMBASI:** 6.1 GB log birikimi, en büyük dosya 137 MB. Log rotasyonu etkin değil. Kart alarmı çalışıyor ama kullanıcıya "ne yapmalı" denmiyor (çözümleme butonu yok).
- **🧱 Frontend-only eşikler:** `TABLE_THRESHOLDS` ve `SummaryCard status` eşikleri bileşen içinde sabit, backend'ten gelmiyor.
- **🐛 `bars` tablosu için çelişkili bilgi:** Kod yorumu "cleanup bars temizliyor" diyor, ama panel "retention YOK" uyarısı veriyor. `has_conflict=false` olduğundan ConflictWarning gizli. Gerçek durumun ne olduğu UI'dan anlaşılmıyor.
- **🐛 Log listesi "ilk 15" kırpması:** 40 dosyadan 25'i kullanıcıya gösterilmiyor — büyük günlerdeki problemler UI'da gizlenir. Backend zaten listeyi döndürüyor, kırpma tamamen frontend'te (`files.slice(0, 15)`).
- **🔴 `cleanup_conflict.has_conflict` yalnızca retention tamamen kapalıysa true dönüyor.** Retention açık ama `bars` gibi kritik tablolar retention kapsamında değilken `has_conflict=false` raporlanıyor — erken uyarı sistemi kör.
- **✅ Veri akışı sağlıklı:** DB boyutu, tablo satırları, log boyutu, disk alanı, retention tarihleri hepsi canlı ve doğru.
- **✅ RETENTION AKTIF:** Son retention ve cleanup çalışması bugün (2026-04-11) tetiklenmiş.
- **✅ Tek sayfa, tek endpoint:** `/api/nabiz` çağrısı atomik ve ucuz. Sayfanın kendisi sağlam.
- **Drill-down:** Tek tıklanabilir öğe `ConflictWarning` accordion. Canlı durumda gizli → sayfa fiilen salt okunur.

## 14. Ayarlar (`/settings`)

**Dosya:** `desktop/src/components/Settings.jsx` (559 satır)
**Route:** `api/routes/settings.py` (162 satır) + `api/routes/account.py` + `api/routes/status.py` + `api/routes/events.py`
**Veri kaynağı:**
- `getAccount()` → `/api/account` (MT5 bağlantı bilgisi)
- `getStatus()` → `/api/status` (engine faz, uptime, mt5_connected)
- `getRiskBaseline()` → `/api/settings/risk-baseline` (config'ten)
- `getEvents({severity, limit})` → `/api/events` (DB events tablosu)
- `updateRiskBaseline(combined)` → `POST /api/settings/risk-baseline`
- `updateNotificationPrefs(prefs)` → `POST /api/settings/notification-prefs`

**Poll:** Sayfa ilk açılışta + `logLimit` / `logFilter` değişiminde yeniden çekim. Ayrı interval yok.

### 14.1 MT5 Bağlantı Bölümü (Sol Kolon)

| Alan | Kaynak | Karar |
|------|--------|-------|
| Bağlantı badge ("Bağlı" / "Bağlantı Yok") | `status.mt5_connected` | ✅ Canlı — bugün "Bağlı" |
| Sunucu | `account.server` — canlı "GCM-Real01" | ✅ Canlı |
| Hesap No | `account.login` — canlı 7023084 (mask + göz butonu) | ✅ Canlı — `maskLogin` ile ortadaki kısım gizli |
| Şifre | `"••••••••"` sabit | 🧱 Dummy — gerçek bir şey göstermiyor, zaten göstermemeli |
| Para Birimi | `account.currency` — "TRY" | ✅ Canlı |
| **Farklı Hesap ile Giriş** butonu | `window.electronAPI.restartMT5()` IPC → `desktop/main.js` → `mt5Manager.js` | ✅ Electron IPC üzerinden çalışıyor. Web bağlamında `electronAPI` yoksa `alert` gösteriyor (fallback güvenli). |

**Drill-down:** Göz butonu (`◉ / ○`) mask'i aç/kapa; dışa başka tıklanabilir öğe yok.

### 14.2 Risk Hesaplama Başlangıcı (Risk Baseline Date+Time)

**Akış:** `idle → confirm → saving → idle` iki aşamalı onay.
**Girdi:** `date` input + `time` input → `"YYYY-MM-DD HH:MM"` formatına birleştirilir.
**Doğrulama:** Regex + `Date()` parse + gelecek tarih kontrolü.
**Backend yan etkileri:** Config'e yaz + dosyaya kaydet + `baba._risk_baseline_date` güncelle + `baba_module.RISK_BASELINE_DATE` sabiti güncelle + **peak_equity sıfırla**.

**Canlı gözlem (`/api/settings/risk-baseline`):** `baseline_date="2026-04-01 00:01"`, `source="config"` → config'ten okuyor.

**Karar:** ✅ Canlı — iki aşamalı onay, backend validation, peak equity sıfırlama hepsi çalışıyor.

**🐛 Çelişki:** Dashboard bölümünde `STATS_BASELINE='2026-02-01'` (trade istatistikleri için) sabit, bu sayfada risk baseline `2026-04-01 00:01`. İki farklı başlangıç tarihi kullanılıyor ve UI'da ayrımı açıkça anlatılmıyor. Kullanıcı baseline'ı 2026-04-01'e çekmiş ama Dashboard istatistikleri hâlâ 2026-02-01'den hesaplıyor.

### 14.3 Versiyon Bilgisi Bölümü

**🧱 Kritik hardcode bulgu:**
```jsx
const VERSION = '6.0.0';
const BUILD_DATE = '2026-03-29';
```

Bu değerler bileşen başında sabit string. Uygulama gerçekte v5.9.x çalışıyor (`engine/__init__.py::VERSION`, `config/default.json::version`, `desktop/package.json::version` hepsi `5.9.0` civarı), fakat bu ekranda kullanıcıya **"ÜSTAT Plus V6.0 Desktop"** + **`v6.0.0`** + **`Build: 2026-03-29`** gösteriliyor. Backend'ten versiyon çekilmiyor (örn. `/api/status` dönüşünde versiyon alanı olsa da kullanılmıyor).

| Alan | Kaynak | Canlı Değer | Karar |
|------|--------|-------------|-------|
| Uygulama | Sabit | "ÜSTAT Plus V6.0 Desktop" | 🧱 **Hardcode yanlış versiyon** |
| Versiyon | Sabit `VERSION` | "v6.0.0" | 🧱 **Hardcode — gerçek v5.9.x** |
| Build Tarihi | Sabit `BUILD_DATE` | "2026-03-29" | 🧱 **Hardcode** |
| Engine | `status.engine_running` | "Çalışıyor" | ✅ Canlı |
| Uptime | `status.uptime_seconds` (formatUptime) | Canlı 3148sn → "52dk 28sn" | ✅ Canlı |
| Faz | `status.phase` | "running" | ✅ Canlı |
| Geliştirici | Sabit | "TURAN AYKUT" | 🧱 Sabit (meşru) |
| Copyright | Sabit | "© 2026 TURAN AYKUT" | 🧱 Sabit (meşru) |

### 14.4 Tema Ayarı (Sağ Kolon)

**Seçenekler:** Koyu (aktif) + Açık Tema (seçilebilir).
**Kaynak:** `localStorage['ustat_theme']` + `document.documentElement.setAttribute('data-theme', 'light')`.
**Backend yan etkisi yok** — tamamen frontend-side tema.

**Karar:** ⚠️ Kısmi — "Açık Tema" kartı tıklanabilir ama CSS'te `[data-theme="light"]` kuralı tam tanımlı değil. Dosya yorumu "şimdilik sadece koyu tema" diyor ama kart aktif → kullanıcı açık temayı seçerse eksik bir tema elde edebilir. UI ile yorum çelişiyor.

### 14.5 Bildirim Tercihleri

**5 toggle:** soundEnabled, killSwitchAlert, tradeAlert, drawdownAlert, regimeAlert.
**Kaydetme akışı:** Toggle → `localStorage['ustat_notification_prefs']` yazar → `updateNotificationPrefs(prefs)` → `POST /api/settings/notification-prefs`.

**🧱 Backend kalıcılığı YOK:** `api/routes/settings.py` içinde `_notification_prefs` **process belleğinde** bir dict. Engine restart → bellek sıfırlanır, sadece `DEFAULT_PREFS` kalır.
```python
_notification_prefs: dict = {
    "soundEnabled": True, ...
}
```
Config dosyasına veya DB'ye yazılmıyor. **localStorage** UI tarafında saklandığı için kullanıcı kendi tarayıcısında prefs'ini görür ama farklı makineden açınca veya cache silince kaybolur. Backend tarafında prefs gerçekten değişiklik üretmiyor — hiçbir bildirim kodu bu dict'i okumuyor (grep sonucu yok).

**Karar:** 🔴 **Sessiz kart:** 5 toggle var, her biri `localStorage` + API çağrısı yapıyor, ama hiçbir şey gerçek bildirim davranışını değiştirmiyor. Kullanıcı "Kill-Switch uyarısı kapatıldı" sanıyor ama sistem aynı sesleri çıkarıyor. UI simulasyon.

### 14.6 Sistem Log (Tam Genişlik)

**Filtreler:** `all / CRITICAL / WARNING / INFO` + limit seçenekleri 25/50/100/200 + Yenile butonu.
**UI → API:** `getEvents({severity, limit})` → `/api/events?severity=...&limit=...`
**Kolonlar:** Zaman · Önem · Tip · Mesaj · Aksiyon

**Canlı gözlem (`/api/events?limit=5`):**

| Tip | Sev | Mesaj |
|-----|-----|-------|
| DATA_GAP | WARNING | F_KONTR/M15: 2 gap tespit edildi |
| DATA_GAP | WARNING | F_KONTR/M5: 10 gap tespit edildi |
| DATA_GAP | WARNING | F_KONTR/M1: 85 gap tespit edildi |
| DATA_GAP | WARNING | F_AKSEN/M1: 16 gap tespit edildi |
| DATA_GAP | WARNING | F_BRSAN/M1: 32 gap tespit edildi |

**Karar:** ✅ Canlı — backend filtre parametreleri çalışıyor, tablo anlamlı veriyle doluyor.

**🔴 Gürültü problemi:** Event listesi DATA_GAP WARNING ile dolup taşmış. Piyasa saati içinde 85 gap tek bir kontratın M1 zamanında yakalanmış — data pipeline'da kaynak sorunu var ama bu Settings sayfası açısından sadece kullanıcıya gösterilen veri. Hata Takip sayfasındaki 4952 WARNING sayısının ana kaynağı bu.

**Aksiyon sütunu:** Her satır için `ev.action || '—'` — ham DB field. Aksiyon doldurulmuş event yok, her satır `—` gösteriyor. Backend bu alanı tutarlı doldurmuyor.

### 14.7 Drill-down Kontrolü

- MT5 göz butonu: ✅ hesap no mask/unmask (tek toggle)
- Farklı Hesap butonu: ✅ Electron IPC → MT5 launcher akışı
- Risk baseline: ✅ iki aşamalı onay akışı (idle → confirm → saving)
- Tema kartları: ✅ dark/light switch (ama açık tema eksik)
- Toggle switches: ✅ state değişir ama backend davranış ➜ yok
- Log filtre butonları + limit select: ✅ filtreleme çalışır
- Log tablosu satırları: ❌ tıklanamaz, modal açmaz
- Versiyon kartı: ❌ sabit bilgi

### 14.8 Sayfa Bulguları

- **🧱 Versiyon 3 satır hardcode:** `VERSION = '6.0.0'`, `BUILD_DATE = '2026-03-29'`, başlık "V6.0 Desktop". Gerçek uygulama v5.9.x. Backend'te versiyon endpoint'i eksik olduğu için UI sabit string kullanıyor.
- **🔴 Bildirim tercihleri sessiz:** 5 toggle + localStorage + API POST, ama backend `_notification_prefs` dict'ini hiçbir kod okumuyor. Toggle'lar kullanıcı algısı yaratıyor, gerçek davranış yok.
- **🧱 Backend prefs kalıcılığı yok:** `api/routes/settings.py::_notification_prefs` process belleği. Restart → default değerler.
- **🐛 Baseline tarih çelişkisi:** `risk.baseline_date=2026-04-01 00:01` (Settings), `STATS_BASELINE='2026-02-01'` (Dashboard). İki farklı kavram ama UI ayrımı anlatmıyor.
- **⚠️ Açık Tema eksik implementasyon:** `st-theme-card` tıklanabilir ama CSS'te açık tema tam tanımlı değil, yorum "şimdilik sadece koyu tema" diyor. Tutarsızlık.
- **🧱 Şifre alanı dummy:** Sabit `"••••••••"` — anlamsız, kaldırılabilir.
- **✅ Risk baseline güncelleme:** İki aşamalı onay, backend validation, peak_equity sıfırlama — sağlam akış.
- **✅ MT5 IPC akışı:** `Farklı Hesap ile Giriş` → Electron preload → mt5Manager → gerçek launcher. Fallback `alert` mevcut.
- **✅ Sistem log tablosu:** Filtre + limit + yenile, backend severity filtresi çalışıyor.
- **🔴 DATA_GAP event seli:** Log ilk 5 kaydı hepsi DATA_GAP WARNING — data pipeline'dan aşırı gürültü. Bu Settings ekranı değil, data katmanı bulgusudur.
- **Drill-down:** Baseline confirm akışı + Theme switch + MT5 göz butonu dışında tıklanabilir drill-down yok.

## 15. Ortak Öğeler — TopBar, SideNav, ConfirmModal

Bu üç bileşen her sayfada render edilir; bulguları ayrı bir bölümde topluyorum çünkü drill-down zincirleri (kill-switch, güvenli kapanış, pin, native pencere kontrolleri) buradan başlıyor.

### 15.1 TopBar (`desktop/src/components/TopBar.jsx`, 279 satır)

**Veri akışı:**
- `getStatus()` + `getAccount()` → 2 saniyede bir paralel polling (`Promise.allSettled`).
- `getAgentStatus()` → 10 saniyede bir (`setInterval`).
- `getHealth()` → 10 saniyede bir, `health.mt5.trade_allowed` bayrağını okur.
- İlk state varsayılanı: `regime: 'TREND'` — **🧱 hardcode default.** Engine cevap vermeden önce UI "TREND" gösteriyor; kısa süreli yanılma. Daha güvenli varsayılan `"—"` veya `"BAĞLANIYOR"` olurdu.

**Sol blok — Uygulama başlığı:**
```jsx
<h1>ÜSTAT Plus <span className="version">V6.0</span></h1>
```
🧱 **Sabit "V6.0"** — gerçek uygulama `v5.9.x` (Settings'teki `VERSION='6.0.0'` hardcode ile aynı problem). İki ayrı noktada aynı yanlış versiyon. Tek değişken haline getirilmeli.

**Orta blok — Rozetler:**

| Rozet | Kaynak | Karar |
|------|--------|-------|
| PHASE_LABELS (`running`, `stopped`, `killed`, `error`, `idle`) | `status.phase` → sözlük çevirisi | ✅ Canlı — sözlük hardcode, eksik bir state gelirse `— idle` gösterilir |
| Rejim rozeti (TREND/RANGE/VOLATILE/OLAY) | `status.regime` | ✅ Canlı |
| Kill-Switch seviye rozeti (L0/L1/L2/L3) | `status.kill_switch_level` | ✅ Canlı |
| `Kill-Switch Sıfırla` butonu | `phase === 'killed'` koşulu → `acknowledgeKillSwitch()` → `/api/killswitch/acknowledge` | ✅ Canlı. Buton SADECE killed fazında beliriyor; L1/L2'de görünmüyor. Anayasa Kural #3 (monotonluk) gereği düşürme endpoint'i `acknowledge` olarak korunmuş. |
| `Algo KAPALI` banner'ı | `healthBlockReason` state, `health.mt5.trade_allowed === false` olduğunda | ✅ Canlı — bu özellikle anayasal kritik, MT5 tarafında algo ticareti kapandığında kullanıcı uyarılıyor |
| `⚠ Veri eski` banner'ı | `status.data_fresh === false` veya WS bağlantısı koptu | ✅ Canlı |
| Pin butonu (📌 Her Zaman Üstte) | `window.electronAPI.toggleAlwaysOnTop()` → Electron IPC | ✅ Canlı (Electron dışı ortamda sessizce çalışmaz) |

**Sağ blok — Hesap metrikleri (4 alan):**

| Alan | Kaynak | Karar |
|------|--------|-------|
| Bakiye | `account.balance` | ✅ Canlı |
| Equity | `account.equity` | ✅ Canlı |
| Floating | `account.equity - account.balance` türetmesi | ⚠️ **Hafif tutarsızlık** — Dashboard'da aynı değer WS `liveEquity.floating_pnl` üzerinden gelir; TopBar'da REST türetmesi kullanılıyor. Aynı ekranda 2 sn'lik gecikme farkı olabilir, kritik değil |
| Günlük K/Z (MT5) | `account.daily_pnl` — `/api/account` cevabı | ⚠️ **Kısmi** — Bölüm 3.2 notunda belirttiğim "başka kaynak" aynı endpoint'in `daily_pnl` alanı. Dashboard'daki Günlük K/Z ise WS `liveEquity.daily_pnl`. İkisi de aynı `db.get_latest_risk_snapshot()` snapshot'ına bağlı; ancak WS stream 2 sn, REST 2 sn (TopBar) — yine de "MT5" etiketi **yanıltıcı**, veri MT5'ten değil risk_snapshots tablosundan geliyor. 🐛 **Yanlış etiket.** |

**Sağ uç — 140px spacer:**
`titleBarOverlay` kullanıldığı için Windows native pencere butonları (min/max/close) için boşluk bırakılmış. Electron dışında fallback butonlar render ediliyor (`window.electronAPI.minimize/maximize/close`).

**Drill-down:** Pin butonu + Kill-Switch Sıfırla dışında tıklanabilir derinlik yok. Rozetlere tıklayınca bir şey olmuyor — ✅ sessiz kart DEĞİL, ama rejim/phase için detay modalı açılabilir (Aksiyon Adayı).

### 15.2 SideNav (`desktop/src/components/SideNav.jsx`, 212 satır)

**Üst blok — 12 Navigation Item:**
`NAV_ITEMS` sabit dizisi; her kayıt `{ path, label, icon }` içerir. React Router `NavLink` + `activeClass` ile aktif sayfa vurgulanır. Route path'leri Bölüm 1'deki tabloyla birebir uyumlu (düzeltme sonrası).

**Alt blok — Kritik aksiyonlar (2 buton):**

| Buton | Davranış | Kaynak | Karar |
|-------|---------|--------|-------|
| `Güvenli Kapat` | 2 aşamalı ConfirmModal akışı: Step 1 "Tüm pozisyonlar kapatılacak, devam?" → Step 2 "Emin misin?" → `window.electronAPI.safeQuit()` → Electron main process `safeQuit` IPC → `close_all_positions` + `stop` + `app.quit()` | ✅ Canlı — 2-step onay Anayasa Kural #13 (kapanış sırası) korumasına uyumlu |
| `Kill-Switch` (basılı tut) | 2 saniye basılı tutma + 60fps progress animation (`setInterval 16ms`) → `activateKillSwitch('operator')` → `/api/killswitch/activate` | ✅ Canlı — animasyon süresi `KILL_HOLD_DURATION = 2000ms` sabiti |

**Hardcode sabitleri:**
- `KILL_HOLD_DURATION = 2000` — 2 saniye basılı tutma. 🧱 Config'den okunmuyor.
- `setInterval(..., 16)` — 60fps tick. Kritik değil, sabit kalabilir.
- İcon emojileri hardcoded (`📊 📈 🔀 🤖 📜 📑 🧠 ⚠️ 🖥️ 🐛 💓 ⚙️`). Render sürücüsü.

**Drill-down:** `ConfirmModal` dışında başka modal açılmıyor.

### 15.3 ConfirmModal (`desktop/src/components/ConfirmModal.jsx`)

Yeniden kullanılabilir onay diyaloğu. Üç yerden çağrılıyor: SideNav (safe quit 2-step), SideNav (genel uyarı), Settings (risk baseline confirm).

**Props:**
- `open` (boolean)
- `title`, `message` (string)
- `confirmLabel`, `cancelLabel`
- `variant` (`default` / `danger`) — buton renk tonu
- `onConfirm`, `onCancel` callbacks

**Davranış:**
- ESC tuşu → `onCancel || onConfirm` (varsayılan iptal)
- Overlay tıklama → `onCancel`
- Confirm butonu → `onConfirm`, modal kapanmaz (parent kontrol ediyor)
- Odak yönetimi var (`autoFocus` cancel butonunda)

**Karar:** ✅ Sağlam — reusable, erişilebilirlik temel düzeyde tamam, 3 farklı çağıran da tutarlı davranıyor.

### 15.4 Ortak Bulgular

- **🧱 V6.0 hardcode 2 noktada:** TopBar `<h1>` ve Settings `VERSION` sabiti. Tek değişkene indirilmeli.
- **🧱 `regime: 'TREND'` varsayılanı:** İlk frame yanıltıcı. `"—"` olmalı.
- **🐛 TopBar "Günlük K/Z (MT5)" etiketi yanıltıcı:** Veri risk_snapshots tablosundan, MT5'ten değil.
- **🧱 KILL_HOLD_DURATION hardcode:** Kritik bir koruma parametresi config'de olmalı.
- **⚠️ Floating K/Z tutarsızlığı:** Dashboard WS stream, TopBar REST türetme — aynı ekranda iki farklı yol. Kritik değil ama gözlemci kafa karıştırabilir.
- **✅ Güvenli Kapat 2-step:** Anayasa Kural #13'e uyumlu sağlam akış.
- **✅ Kill-Switch Sıfırla:** Yalnızca `killed` fazında görünür, acknowledge endpoint'i kullanır.
- **Drill-down:** Sadece ConfirmModal açan 2 aksiyon (Güvenli Kapat, Baseline Confirm). Rozet/metrik tıklamalarında derinlik yok.

---

## 16. Bulgu Özeti

Bölüm 3–15 boyunca tespit edilen bulgular kategorize edilmiştir. Numaralandırma Aksiyon Adayları (Bölüm 17) ile eşleşir.

### 16.1 🔴 Sessiz Kartlar (UI var ama işlevi yok)

| # | Konum | Bulgu | Kritiklik |
|---|-------|-------|-----------|
| S1 | Ayarlar · Bildirim Tercihleri (14.5) | 5 toggle `localStorage` + backend memory dict'e yazıyor, hiçbir gerçek bildirim davranışını değiştirmiyor (sistem sesleri, banner, popup hep aynı) | **KRİTİK** — kullanıcı "sessize aldım" sanıp uyarıları kaçırabilir |
| S2 | Otomatik İşlem · Otomatik Pozisyon Özeti (6.4) | Fonksiyonel ama altındaki tablo ile aynı bilgiyi gösteriyor, ikilik | Orta |
| S3 | İşlem Geçmişi · 4 Özet Kart üstü karşılaştırma satırı (7.3) | Tek satırlık bilgi, altındaki tam tablo daha zengin | Düşük |
| S4 | Hibrit İşlem · PRİMNET eşikleri (5.6) | Backend `trailing_prim=1.5, target_prim=9.5` dönüyor ama UI'de bu eşikleri gösteren kart/gösterge yok — sadece `PrimnetDetail` modalı içinde | Orta (görünürlük boşluğu) |

### 16.2 🐛 Yanlış Görev / Yanıltıcı Veri

| # | Konum | Bulgu | Kritiklik |
|---|-------|-------|-----------|
| B1 | Risk Yönetimi (10) — Anayasa Kural #6 ihlali şüphesi | Canlı `hard_drawdown_pct ≥ %15` (ölçüm sırasında %30.43) ama `kill_switch_level=2` (L3 değil). İki olasılık: (a) otomatik L3 tetik mekanizması `_check_hard_drawdown` çalışmıyor, (b) baseline farklı hesaplanıyor ve gerçek drawdown daha düşük | **KRİTİK — ANAYASA** |
| B2 | Performans · En İyi İşlem (8.1) + İşlem Geçmişi (7.4) | `F_TOASO BUY 8 lot entry=259.87 exit=257.80 pnl=+2705` — BUY için exit<entry zarar olmalıyken +2705. Direction veya pnl kaydı bozuk | **KRİTİK** — veri güvenilirliği |
| B3 | Hibrit İşlem · Aktif Pozisyonlar (5.4) | Aynı ticket için Dashboard 5 lot, Hibrit paneli `volume=4`. H-Engine `hp.volume` başka alandan besleniyor | **KRİTİK** — tutarsız sermaye gösterimi |
| B4 | Hibrit İşlem · `pnl=0` (5.4) | F_ASELS SELL @400.05, current 403.80 → 3.75 TL zarar olmalı. Backend `mt5_pos.get("profit",0)` sıfır dönüyor. Broker netting veya MT5 profit field'ı zero | **KRİTİK** |
| B5 | Hibrit · `TP regresyon` (5.4) | SELL için `initial_tp=341.95` → `current_tp=365.45` (entry'ye yaklaşma). PRİMNET trailing güvenceye alma olabilir ama UI açıklamıyor | Orta |
| B6 | Hibrit · Olay Geçmişi (5.5) | `PRIMNET_DAILY_RESET` olayı UI `switch`'inde yok, fallback "SL: 405.7 → 405.7" anlamsız metin üretiyor | Orta |
| B7 | Otomatik · Oğul Aktivite (6.7) | Canlı `adx_value=0` TREND rejiminde imkansız, backend ADX hesabı sonuç üretmiyor; `last_m15_close=""` → OĞUL son M15 close yazılmıyor | Yüksek |
| B8 | Otomatik · Dashboard (6.8) | Sağ üst "Otomatik Pozisyon Özeti" → 🔴 çift gösterim (S2) + 🐛 sayısal tutarsızlık (`total=45`, `winners+losers=31`, scratch 14 işlem gizli) | Yüksek |
| B9 | Monitor · Motor Durumu (11.4) | `modStatus.manuel = 'ok'` **sabit hardcode** (manuel motor hatası hiç görünmez); BABA/ÜSTAT rozetleri sadece `engine_running`'e bağlı → L2 kill-switch aktifken bile "BABA AKTİF" yeşil | **KRİTİK** |
| B10 | Monitor · Performans (11.7) | VERİ GÜNCELLEME adımı `avg=2596.8ms`, eşik `max=100` → bar her zaman %100 dolu, darboğaz görünmez; kullanıcı "döngü bozuk" algılar ama `overrun_count=0` | Yüksek |
| B11 | Monitor · Flow Diagram MT5 panosu (11.4) | Her durumda "MT5 BAĞLANTI YOK" yazıyor (mt5Connected state var ama detail'da kullanılmıyor) — MT5 aslında bağlı | Yüksek |
| B12 | Performans · Saat Heatmap (8.8) | `new Date(ts).getHours()` tarayıcı local TZ → VPN/farklı TZ'de yanlış bucket | Düşük |
| B13 | Performans · Strateji Bazlı K/Z (8.4) | `by_strategy` hem `hibrit` hem `hybrid` anahtarı → iki ayrı bar, kullanıcı kafası karışır | Düşük |
| B14 | Performans · Equity Eğrisi (8.2) | Bakiye büyümesi yatırım kaynaklı, UI bunu "kazanç trendi" gösteriyor. Net sermaye vs mevduat ayrımı yok → kullanıcı kâr ediyor sanır | Yüksek |
| B15 | Dashboard · Son İşlemler (3.4) | "N onaysız" rozeti `exit_reason` substring `APPROVED` kontrolü ile — otomatik işlemler onaysız görünür | Orta |
| B16 | TopBar (15.1) | "Günlük K/Z (MT5)" etiketi yanıltıcı — veri `risk_snapshots` tablosundan, MT5'ten değil | Orta |
| B17 | Hata Takip (12) | `TRADE_ERROR` anahtarı `EVENT_TYPE_CATEGORY` sözlüğünde yok → "sistem" kategorisine düşüyor, canlı 9x miskategorize | Yüksek |
| B18 | Hata Takip (12) | `error_resolutions` `/resolve` endpoint'i `message_prefix` parametresini DB'ye YAZMIYOR (sadece error_type) — frontend `slice(0,80)` gönderiyor ama kayboluyor | Orta |
| B19 | Risk Yönetimi (10.2) | `monthly_drawdown_pct ?? total_drawdown_pct` fallback — backend 0 dönerse UI 0 (doğru), ama null dönerse toplam drawdown gösterir (karmaşa riski) | Düşük |
| B20 | Risk Yönetimi (10.4) | Floating P&L `risk_snapshots` DB 10sn polling — anlık MT5 değişimini yansıtmıyor, Dashboard WS'inin 2sn'lik canlı değerinden farklı | Orta |
| B21 | Performans · Profit Factor kartı (8.1) + Risk Yönetimi alt paneli (7.6) | `STATS_BASELINE=2026-02-01` vs `risk.baseline_date=2026-04-01 00:01` — iki ayrı baseline farkı UI'da gizli; kullanıcı "aynı dönem" sanır | Yüksek |
| B22 | Otomatik · Aktif Pozisyonlar (6.5) | Yönetim kolonu Manuel/Hibrit pozisyonlarda boş (`strategy=bilinmiyor`) → kullanıcı "hiç yönetilmiyor" hissi yaşar | Orta |
| B23 | İşlem Geçmişi sınıflandırma (7.4) | `isAuto` negatif koşullarla (`strategy=boş/manual/bilinmiyor değil`) belirleniyor; backend `_OTOMATIK_STRATEJILER` frozenset ile senkron değil | Orta |
| B24 | İşlem Geçmişi · Alt Panel (7.6) | Sol panel dönem filtreli client hesap, sağ panel sabit `STATS_BASELINE` backend — filtre değişse bile `best_trade/sharpe/maxdd` güncellenmiyor | Yüksek |
| B25 | Monitor · errorCounts (11.4) | `msg.toLowerCase().includes('baba')` substring — ilgisiz mesaj "baba" geçerse yanlış pozitif; Unicode `oğul` toLowerCase sorunlu | Düşük |

### 16.3 🧱 Hardcode / Config'e Bağlı Olmayan Sabitler

| # | Konum | Bulgu | Kritiklik |
|---|-------|-------|-----------|
| H1 | **TopBar (15.1) + Settings (14.3)** | `V6.0` / `VERSION='6.0.0'` / `BUILD_DATE='2026-03-29'` — gerçek uygulama `v5.9.x`; iki ayrı noktada YANLIŞ hardcode versiyon | **KRİTİK** — kullanıcıya yanlış sürüm söylüyor |
| H2 | Dashboard (3.3) | `1 / 5` pozisyon sayacı — `max_open_positions` config'den değil, sabit "/5" | Orta |
| H3 | Manuel İşlem (4.1) | `SYMBOLS` sabit dizisi (15 kontrat) `config/default.json.watchlist.symbols` ile senkron değil | Yüksek |
| H4 | Manuel İşlem (4.1) | Lot input `min=1 max=10 step=1` sabit, config'deki `max_lot_per_trade` okunmuyor | Yüksek |
| H5 | SideNav (15.2) | `KILL_HOLD_DURATION=2000ms` sabit — kritik koruma parametresi config'de olmalı | Orta |
| H6 | Hata Takip (12) | EOD saat sabitleri (`EOD_CLOSE_HOUR=17, _MIN=45, VIOP_OPEN_HOUR=9, _MIN=30, VIOP_CLOSE_HOUR=18, _MIN=15`) tümü hardcode; `config/default.json.session` kullanılmalı | Yüksek |
| H7 | Hata Takip (12) | `CATEGORY_COLORS`, `SEVERITY_COLORS`, kategori filtre seçenekleri frontend sabit dizisi — backend değişirse senkron kopar | Düşük |
| H8 | NABIZ (13) | `TABLE_THRESHOLDS` (15 tablo), `SummaryCard` eşikleri (DB 500/1000 MB, log 2000 MB, disk 80/90%) frontend hardcode | Orta |
| H9 | NABIZ (13) | `files.slice(0,15)` — log listesi 15'e kırpılıyor, kullanıcı daha fazlasını göremez | Düşük |
| H10 | Performans (8.8) | Seans saat aralığı `9-18` hardcode; `config/default.json.session_start/end` kullanılmalı | Orta |
| H11 | Ayarlar (14.3) | "Şifre" alanı dummy `"••••••••"` — anlamsız, kaldırılabilir veya gerçekleştirilebilir | Düşük |
| H12 | Ayarlar (14.4) | Açık tema tıklanabilir ama CSS'te tam implementasyon yok, yorum "şimdilik sadece koyu tema" | Orta |
| H13 | ÜSTAT Beyin (9.4) | Kontrat profil eşikleri UI seviyesinde yorumlanıyor (config'den değil) — tekrar kontrol gerekli | Düşük |
| H14 | Monitor (11.7) | Performans max eşiği 100 ms — data_update adımı 2596 ms, bar her zaman %100 (B10 ile birlikte) | Yüksek |
| H15 | Monitor (11.8) | BABA L1/L2/L3 eşikleri UI'de "yaklaşık" olarak hardcode ama "yaklaşık" notu yok — kullanıcı gerçek eşik sanar | Orta |
| H16 | Hibrit Devir (5.3) | `approveTrade(id, 'operator', '')` — operatör kimliği sabit string `'operator'`, kullanıcı ayırt edilemiyor | Düşük |
| H17 | Risk Yönetimi (10.2) | `graduated_lot_mult=1` backend'den geliyor ama UI hiçbir yerde göstermiyor (ölü alan) | Orta |
| H18 | TopBar (15.1) | İlk state varsayılanı `regime: 'TREND'` — engine yanıtlamadan önce yanlış rejim gösteriyor; `"—"` olmalı | Düşük |

### 16.4 ⚠️ Kod Kalitesi / Dayanıklılık Sorunları

| # | Konum | Bulgu |
|---|-------|-------|
| K1 | Manuel İşlem (4.1) | `handleExecute` `useCallback` dependency array'i `[symbol, direction, lot, fetchRecentTrades]` — **`sl` ve `tp` eksik**, stale closure riski (React lint yakalar) |
| K2 | Hibrit (5.3) | `handleCheck`/`handleTransfer` fonksiyonlarında `try/catch` yok (satır 142-172); fetch hatası UI'yi sessizce bozar |
| K3 | Hata Takip (12) | `by_severity.WARNING=4952` — 5000 limit sınırına çok yakın; `_fetch_events_from_db(limit=5000)` 7 günlük pencerede taşma riski var |
| K4 | NABIZ (13) | `retention_covered` set `bars`'ı hariç tutuyor ama kod yorumu "v5.9.3 cleanup artık sadece bars temizliyor" diyor — çelişki; `has_conflict` sensörü kör |
| K5 | NABIZ canlı | `bars=183078`, `risk_snapshots=106426`, `events=60285` (kırmızı eşik üstü); log 6111 MB (40 dosya, max 137.25 MB) — retention son 2026-04-11 çalışmış ama tablo şişkinliği devam |
| K6 | Ayarlar (14.6) | Sistem log ilk 5 kaydı hepsi `DATA_GAP WARNING` — data pipeline gürültü katmanı |
| K7 | Hibrit Devir (5.3) | Onay mekanizması kullanıcı kimlikli değil; audit trail yok |
| K8 | Risk (10.2) | Hard drawdown %30.43 üstüne rağmen UI'de hiçbir uyarı banner'ı yok, sadece sayı gösteriliyor |
| K9 | Monitor (11.3) | `POLL_MS=10000` ama kod yorumu "3 sn API poll" diyor — dokümantasyon güncel değil |
| K10 | Dashboard (3.3) | Hibrit pozisyonlarda MT5 native SL/TP "—" gösteriliyor; gerçek koruma `h_engine.current_sl/current_tp`'de — kullanıcı "korumasız" sanabilir |
| K11 | Dashboard (3.3) | Yönetim kolonu (TP1/BE/MA/Vote) manuel/hibrit adopt edilmiş pozisyonlarda boş — tooltip yok, kafa karıştırıcı |

### 16.5 Sayısal Özet

| Kategori | Sayı |
|----------|------|
| 🔴 Sessiz kart | **4** (S1 KRİTİK + 3 orta/düşük) |
| 🐛 Yanlış görev / yanıltıcı veri | **25** (5 KRİTİK, 7 yüksek, 10 orta, 3 düşük) |
| 🧱 Hardcode / config bağı yok | **18** (1 KRİTİK, 5 yüksek, 8 orta, 4 düşük) |
| ⚠️ Kod kalitesi / dayanıklılık | **11** |
| **TOPLAM** | **58 ayrı bulgu** |

### 16.6 Anayasa İhlali Şüpheleri (Özel Kategori)

| Ref | İhlal Adayı | Şiddet |
|-----|-------------|--------|
| B1 | Kural #6 — Hard Drawdown ≥%15 → L3 otomatik. Canlı %30.43 ama L2. Mekanizma çalışıyor mu? | **DOĞRULAMA ZORUNLU** |
| B2 | Veri güvenilirliği — `F_TOASO BUY pnl=+2705` (exit<entry) — trade kaydı bozuk | **DOĞRULAMA ZORUNLU** |
| B3 | Hibrit lot tutarsızlığı — aynı ticket 4 vs 5 lot | **DOĞRULAMA ZORUNLU** |
| B9 | Monitor "BABA AKTİF" rozeti L2 kill-switch açıkken bile yeşil | Orta |
| S1 | Bildirim sessizliği — kullanıcı uyarıları kaçırabilir | Orta |

---

## 17. Aksiyon Adayları

Bulgular öncelik sırasına göre eylem planına dönüştürülmüştür. Her adayın yanında Bölüm 16'daki bulgu numarası referansı vardır.

### 17.1 ÖNCELİK 1 — Anayasa/Güvenlik (Piyasa kapalıyken HEMEN)

**A1. Hard Drawdown L3 otomatik tetikleme doğrulaması** (B1, Anayasa Kural #6)
- `baba.py::_check_hard_drawdown` fonksiyonunu log'dan doğrula
- Canlı `hard_drawdown_pct` hesaplama yöntemi kontrol et (`risk_snapshots` vs in-memory `peak_equity`)
- Eğer mekanizma çalışıyorsa: Risk sayfasında "HARD DD AŞILDI — L3 bekleniyor" banner'ı ekle
- Eğer çalışmıyorsa: Acil kök neden fix + unit test

**A2. Trade veri güvenilirliği** (B2, B3, B4)
- `F_TOASO BUY exit<entry pnl+2705` kaydını DB'den çek, direction/pnl alanlarını ham MT5 deal history ile karşılaştır
- Hibrit lot tutarsızlığı (ticket 4 vs 5 lot) — `h_engine.hybrid_positions` kaydının kaynağı araştır
- `mt5_pos.get("profit", 0)` sıfır dönüyor — broker netting mi, MT5 API bug mı? Alternatif hesap (`(current - entry) × volume × tick_value`)

**A3. Bildirim Tercihleri gerçek davranış bağlaması** (S1)
- Backend `_notification_prefs` dict'i DB'ye kalıcılaştır
- Ses tetikleme noktalarında (kill-switch, trade, drawdown, regime) `killSwitchAlert/tradeAlert/drawdownAlert/regimeAlert` bayraklarını oku
- Toggle'lar kapalıyken gerçekten susacak

**A4. Monitor motor durumu doğru sinyalleme** (B9)
- `modStatus.manuel = 'ok'` sabit değerini gerçek manuel_motor health check ile bağla
- BABA/ÜSTAT rozetlerini `kill_switch_level` ve `regime` ile zenginleştir (L2 açıkken BABA yeşil göstermesin)

### 17.2 ÖNCELİK 2 — Yanıltıcı Gösterim (Kullanıcı kararlarını bozuyor)

**A5. Versiyon sabiti tekilleştirme** (H1)
- TopBar `<h1>V6.0</h1>` ve Settings `VERSION='6.0.0'` tek kaynaktan okunacak
- Kaynak: `engine/__init__.py::VERSION` veya `config/default.json::version`
- Tek build-time veya runtime fetch (`/api/status.version` zaten mevcut)

**A6. Performans ekranı equity vs mevduat ayrımı** (B14)
- Yatırım transferleri "kazanç" olarak gösterilmesin
- `deposits/withdrawals` kolonu `trades.db` veya MT5 deal history'den al
- Equity eğrisine "Net Sermaye" (= equity − cumulative_deposits) serisi ekle

**A7. Baseline tekilleştirme** (B21)
- `STATS_BASELINE='2026-02-01'` hardcode ile `risk.baseline_date='2026-04-01 00:01'` aynı kaynaktan okunmalı
- `/trades/stats` endpoint'ine `baseline_date` parametre olarak verilmeli
- UI'de hangi baseline aktif olduğu küçük bir label olarak gösterilmeli

**A8. Hibrit MT5 SL/TP görünürlüğü** (K10)
- Dashboard tablosunda Hibrit satırları için `h_engine.current_sl/current_tp` değerlerini MT5 "—" yerine göster
- Tooltip: "Bu değer MT5 native değil, H-Engine sanal korumadır"

**A9. Monitor performans eşikleri gerçekçi değer** (B10, H14)
- `max=100ms` eşiği data_update için gerçekçi değil — data_update hariç hesap veya 10000 ms (CYCLE_INTERVAL)
- Bar hesabı `avg/threshold` oranına göre renklenmeli

**A10. TopBar "Günlük K/Z (MT5)" etiketi düzelt** (B16)
- Etiket → "Günlük K/Z (Snapshot)" veya WS `liveEquity.daily_pnl` kaynağına bağla

### 17.3 ÖNCELİK 3 — Sessiz Alanlar / Ölü Veri

**A11. PRİMNET eşikleri görünür kart** (S4)
- Hibrit sayfasında `trailing_prim=1.5, target_prim=9.5` değerlerini gösteren küçük bir kart veya rozet
- `primnet_daily_reset` olayı için UI formatı ekle (B6)

**A12. Otomatik Pozisyon Özeti kartı elden geçir** (S2)
- Kart ya kaldırılmalı ya da ek metriklerle zenginleştirilmeli (ör. bu ay açılan sinyal sayısı, strateji dağılımı)

**A13. Graduated lot mult gösterimi** (H17)
- Risk sayfasında `graduated_lot_mult=1.0` değerinin "Normal lot" / "Yarım lot" rozet olarak göster
- Haftalık kayıp sonrası devreye girdiğini banner ile göster

**A14. Hata Takip kategori fix** (B17)
- `EVENT_TYPE_CATEGORY` sözlüğüne `TRADE_ERROR: "emir"` ekle
- "Sistem" kategorisindeki 9 `TRADE_ERROR` kaydını migration ile yeniden sınıflandır (veya geriye dönük hesap)

**A15. Error resolve message_prefix DB yazımı** (B18)
- `error_resolutions` tablosuna `message_prefix` kolonu ekle (veya zaten varsa INSERT'te doldur)
- `_is_resolved` kontrolü de bu prefix'i kullansın

### 17.4 ÖNCELİK 4 — Config'e Bağı Olmayan Sabitler

**A16. Manuel İşlem watchlist senkronu** (H3, H4)
- `SYMBOLS` sabitini kaldır, `/api/status.watchlist_symbols` veya yeni endpoint `/api/config/watchlist` üzerinden oku
- Lot min/max config'deki `max_lot_per_trade` ve `min_lot`'tan okunsun

**A17. EOD saat sabitleri config'e taşı** (H6)
- `ErrorTracker.jsx` içindeki hardcoded saat sabitleri `config/default.json.session` altından okunsun
- Aynı şey Performans · Heatmap'teki `9-18` için (H10)

**A18. Pozisyon `/5` sayacı config'e bağla** (H2)
- `max_open_positions` config'den okunup Dashboard rozetinde gösterilsin

**A19. KILL_HOLD_DURATION config'e taşı** (H5)
- `config/default.json.ui.kill_hold_ms = 2000` olarak tanımla, SideNav bundan oku

**A20. NABIZ table threshold / log limit config'e taşı** (H8, H9)
- `TABLE_THRESHOLDS`, summary eşikleri ve `files.slice(0,15)` backend'den dönsün

**A21. Açık tema implementasyonu** (H12)
- Ya tam implementasyon yap (tüm bileşenlerde CSS variables + `data-theme="light"` desteği)
- Ya da Settings'teki light seçeneğini gizle ("Yakında" rozeti)

**A22. TopBar initial state `regime: '—'`** (H18)
- İlk render'da yanlış rejim göstermesin

### 17.5 ÖNCELİK 5 — Kod Kalitesi

**A23. Manuel İşlem stale closure fix** (K1)
- `handleExecute` dependency array'ine `sl, tp` eklenecek

**A24. Hibrit Devir error handling** (K2)
- `handleCheck`/`handleTransfer` try/catch sarılacak, UI'ye hata mesajı basılacak

**A25. Event query 5000 limit alarmı** (K3)
- `_fetch_events_from_db` limit aşımı için logger warning + UI banner
- Düşük öncelikli event'ler için retention sıklaştırılmalı

**A26. NABIZ retention_covered bars çelişkisi** (K4)
- Kod yorumu ve `retention_covered` set'i arasındaki çelişki resolve edilsin
- `has_conflict` sensörü `bars` dahil tüm büyük tabloların retention durumunu taramalı

**A27. Operatör kimliği approve flow'una ekle** (H16, K7)
- `approveTrade(id, operator_name, note)` — operator kimliği kullanıcıdan alınsın (Settings'te ad alanı, localStorage)

**A28. Data pipeline DATA_GAP gürültü azaltma** (K6)
- `DATA_GAP WARNING` frekansı düşür (örn. aynı sembol için 60 sn cooldown)

### 17.6 Kısa Vadeli Sonraki Adım

Kullanıcı onayı sonrası önerilen eylem zinciri:

1. **A1 + A2 (Anayasa doğrulama)** — Piyasa kapalı saatte (Savaş Zamanı dışı) 30 dk
2. **A3 (Bildirim)** — Backend + UI birlikte, 1 saat
3. **A5 (Version tekil kaynak)** — 30 dk (Sarı/Yeşil Bölge)
4. **A14 + A15 (Hata Takip fix)** — 1 saat
5. Critical flows testleri çalıştır (`tests/critical_flows`) — 5 dk
6. Build + restart — 2 dk
7. Canlı doğrulama — 15 dk

Toplam tahmini süre: **~3 saat** (Priority 1 ve kritik Priority 2 işleri için).

---

**Denetim tamamlandı.** Toplam 15 bölüm, 58 bulgu, 28 aksiyon adayı. Rapor `docs/2026-04-11_widget_denetimi.md` altında kalıcıdır.
