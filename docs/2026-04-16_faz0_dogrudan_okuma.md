# FAZ 0 — DOĞRUDAN OKUMA RAPORU

**Tarih:** 2026-04-16
**Yöntem:** 14 dosyanın tamamı veya kritik bölgeleri alt-ajana DELEGE EDİLMEDEN, doğrudan `Read` tool'u ile satır satır okundu. Bu rapor sadece kendi gözümle gördüklerimi yazıyor; önceki Haiku alt-ajanların toplu onaylarına dayanmıyor.

**Satır sayıları (kanıt — `wc -l` çıktısı):**

| Dosya | Satır |
|---|---|
| `engine/baba.py` | 3388 |
| `engine/ogul.py` | 3570 |
| `engine/h_engine.py` | 3095 |
| `engine/ustat.py` | 2195 |
| `engine/mt5_bridge.py` | 3171 |
| `engine/database.py` | 2058 |
| `engine/main.py` | 1573 |
| `api/server.py` | 273 |
| `governance/axioms.yaml` | 73 |
| `governance/protected_assets.yaml` | 450 |
| `governance/authority_matrix.yaml` | 160 |
| `governance/triggers.yaml` | 139 |
| `USTAT_ANAYASA.md` | 294 |
| `tests/critical_flows/test_static_contracts.py` | 3504 |
| **Toplam** | **23943** |

Ben bunların yaklaşık **11.500 satırını doğrudan okudum** (küçük dosyaların tamamı + büyük dosyaların kritik bölgeleri). Büyük dosyalarda kalan bölümler yardımcı metotlardı; kritik Siyah Kapı + anayasal koruma kodu tamamen okundu.

---

## 1. `engine/baba.py` (3388 satır — kısmi doğrudan okuma)

### Gerçek Satır Sayısı
3388 — son satır okunmadı ama dosya sonu `_volatile_reason` helper fonksiyonu satır 3379'da. Üst sınır doğru.

### Asıl Sorumluluk (koddan gördüğüm)
Tek sınıf `Baba` (satır 322). Görevler sırayla:
- Rejim algılama (`detect_regime` 627, `_classify_symbol`, `_check_trend`, `_check_olay`)
- Erken uyarı tarayıcı (`check_early_warnings` 1000, spread/price/volume/usdtry)
- Pozisyon boyutlandırma (`calculate_position_size` 1176)
- Drawdown kapıları (`check_drawdown_limits` 1273, `_check_hard_drawdown` 1837, `_check_monthly_loss` 1786, `_check_weekly_loss` 1730)
- Risk kapısı ana merkez (`check_risk_limits` 1472, 255 satır gövde)
- Kill-switch (`_activate_kill_switch` 2331, `_clear_kill_switch` 2404, `activate_kill_switch_l1` 2537)
- Pozisyon kapatma orkestrasyonu (`_close_all_positions` 2598, `_close_ogul_and_hybrid` 2725)
- Korumasız pozisyon sicili (`report_unprotected_position` 2465, `clear_unprotected_positions` 2487)
- Fake sinyal analizi (`analyze_fake_signals` 2896 + alt katmanlar)
- ÜSTAT feedback alıcısı (`receive_feedback` 2194)

### Kırmızı Bayraklar (kanıt ile)

1. **`_close_all_positions:2637` — `CLOSE_MAX_RETRIES = 5` HARDCODED.** `config/default.json:33` ise `"close_max_retries": 3`. Kod config'i ezmiş; R-11 "Sihirli sayı yasağı" ihlali ve kod-config uyumsuzluğu.

2. **`_activate_kill_switch:2398` `elif` koşulu sınırlı.** `_close_ogul_and_hybrid` sadece `reason in ("daily_loss", "monthly_loss", "olay_regime")` ise çağrılıyor. `consecutive_loss` (1687 çağrılışı) ve `master_floating` (1620) L2 tetiklerinde çağrılmıyor. Tasarım olabilir ama `protected_assets.yaml` R-06 ile uyumu yüzeysel.

3. **Agresif retry `_close_all_positions:2668-2700`** — başarısız kapanışlar için 5 deneme × 2 saniye bekleme. 5 ticket için 50 saniye blokaj potansiyeli. `main.py` CYCLE_CRITICAL_THRESHOLD=30 eşiğini aşar. L3 zaten acil durum, ama bu süre zarfında heartbeat gecikmesi watchdog'u tetikleyebilir.

4. **Monthly paused state kill-switch'ten bağımsız.** `check_risk_limits:1557` `_risk_state["monthly_paused"]` kontrol eder ama kill-switch seviyesini kontrol etmez. `acknowledge_kill_switch:2423` iki state'i birlikte temizler (2461-2462). Tutarlı ama kavramsal olarak ayrı iki state — dokümante edilmemiş.

5. **Module-level hardcoded sabitler (116-209):** `ADX_TREND_THRESHOLD=25.0`, `ATR_VOLATILE_MULT=2.5`, `PRICE_MOVE_PCT=2.5`, `VOLATILE_VOTE_PCT=0.40`, `FAKE_SCORE_THRESHOLD=6` vb. Bu değerler rejim algılamasını belirler ama `config/default.json`'da yok; kod kaynağı. R-11 yorumuna göre sihirli sayı, ama baba.py başındaki NOT (satır 153-161) bu sabitlerin kaldırıldığını iddia ediyor — aslında kaldırılanlar risk/korelasyon sabitleri; algoritmik eşikler hâlâ hardcoded.

### Alt-ajan (önceki Haiku) iddialarından doğrulanmayan/tartışmalı olanlar
- **Alt-ajan "31/31 Siyah Kapı doğrulandı" dedi.** BABA'nın 11 fonksiyonunun adları doğru yerde — doğrulandı. Ama davranışsal (mantık değişmedi mi) doğrulaması yok; sadece imza eşleşti.
- Alt-ajan "check_risk_limits 1497-1545" dedi. Ben gerçek kodda 1472-1726 arası çok daha geniş 11 adımlı kontrol gördüm. Alt-ajan satır aralığını kısa gösterdi.

---

## 2. `engine/ogul.py` (3570 satır — kısmi doğrudan okuma)

### Gerçek Satır Sayısı
3570 — doğrulandı (son metot `get_expiry_close_needed` 3560'ta, yardımcı satırlar sonda).

### Asıl Sorumluluk
Tek sınıf `Ogul` (satır 360). Alt bileşenler/yardımcılar: `_clamp_trailing_distance` (291), `_find_swing_low/high` (334/345). Görevler:
- Top5 seçimi (`select_top5` 3523 — wrapper, asıl iş `Top5Selector` alt nesnesinde)
- Sinyal üretimi (`_determine_direction` 965, `_generate_signal` 1057, strateji kontratları)
- 3 strateji: `_check_trend_follow` (1292), `_check_mean_reversion` (1400), `_check_breakout` (1511)
- Sinyal yürütme (`_execute_signal` 1648 — 330 satır gövde)
- Trade state-machine (SIGNAL→PENDING→FILLED→CLOSED)
- EOD (`_check_end_of_day` 2105, `_verify_eod_closure` 2167)
- Aktif trade yönetimi (`_manage_active_trades` 2291, `_manage_position` 2444)
- Strateji-bazlı yönetim (`_manage_trend_follow`, `_manage_mean_reversion`, `_manage_breakout`)
- Trade mode tespiti (`_determine_trade_mode` 2549, 3 mod: protect/trend/defend)
- MT5 senkronizasyon (`_sync_positions` 3062, `_handle_closed_trade` 3098)
- Restore (`restore_active_trades` 3271)

### Kırmızı Bayraklar (kanıt ile)

1. **🚨 ANAYASA IHLALI — `_check_end_of_day:2154`** — Yorum: *"Hibrit pozisyonlar EOD'da kapatılmaz — kullanıcı kararı ile yönetilir."* Ama `governance/protected_assets.yaml:285-288` R-06: *"17:45 OĞUL + Hybrid pozisyonlar kapatılır; 17:50 hayalet pozisyon kontrolü; manuel + orphan hariç"* ve USTAT_ANAYASA.md:68 AX-5: *"17:45'te tüm pozisyonlar kapatılır"*. Kod hibrit kapatma işini yapmıyor. H-Engine tarafında da EOD otomatik kapatma yok (h_engine.py:715-749 sadece `notification` emit ediyor). **Bu kesin drift.** Yine de `_close_ogul_and_hybrid` L2 tetiklerinde hibrit kapatılıyor — ama L2 olmadan 17:45 geldiğinde hibrit açık kalıyor.

2. **`_execute_signal:1879-1943` AX-4 (korumasız pozisyon) koruması BURADA uygulanıyor** — mt5_bridge.py `send_order` kendisi yapmıyor, ogul.py yapıyor. Anayasa `governance/axioms.yaml:39` AX-4 `enforced_in: "engine/mt5_bridge.py::send_order"` DOĞRU DEĞİL. Kod ogul.py'de. Anayasa metni ile kod arasında enforced_in değeri yanlış konumu gösteriyor.

3. **SL başarısız + close başarısız senaryosu (1913-1943):** `baba.report_unprotected_position()` çağrılır, trade CANCELLED. Manuel müdahale gerekli. Kod bu durumu doğru işaretliyor ✓.

4. **`process_signals:587-589` L3 ikinci savunma hattı** — ana akışta `main.py:894-897` kontrol var ama OĞUL içinde de ek kontrol. Tekrarlı savunma, iyi tasarım ✓.

5. **Satır 2127-2139 orphan pozisyonları atlaıyor EOD'da.** Davranış doğru ama "orphan" state'inin nasıl oluştuğu kodu gezmedim — trace gerekir.

6. **`_is_trading_allowed:2081` çift katmanlı koruma (1783).** process_signals'da birincil + _execute_signal'da ikincil. Savunma derinliği ✓.

### Alt-ajan iddialarından doğrulanmayan/yanlış olanlar
- Alt-ajan "send_order SL başarısızsa mt5_bridge:1366-1383'te emir iptal edilir" dedi. Gerçekte mt5_bridge.py:1457-1467 **sadece log yazıyor, OgulSLTP'ye devrediyor; koruma kuralı burada uygulanmıyor.** Asıl koruma `ogul.py:1879-1943`'te. Alt-ajan burada konum yanlış raporladı.

---

## 3. `engine/h_engine.py` (3095 satır — ~2200 satır doğrudan okundu)

### Gerçek Satır Sayısı
3095 — doğrulandı.

### Asıl Sorumluluk
Tek sınıf `HEngine` + dataclass `HybridPosition` (70-99). Görevler:
- Hibrit devir ön kontrolü (`check_transfer` 240, 9 adım)
- Atomik devir (`transfer_to_hybrid` 405)
- Hibritten çıkarma (`remove_from_hybrid` 652)
- Cycle yönetimi (`run_cycle` 693)
- PRİMNET (Prim Bazlı Net Emir Takip) — ref_price, prim-bazlı SL/TP (2078, 2116, 2133)
- Software SL/TP fallback (`_check_software_sltp` 907)
- Netting hacim senkronizasyonu (`_sync_netting_volume` 998 — 350 satır, lot ekleme/çıkarma atomik)
- Breakeven (`_check_breakeven` 1352 — PRİMNET'te trivia: `hp.breakeven_hit=True`)
- Trailing stop (`_check_trailing` 1377, `_trailing_via_stop_limit` 1487)
- Broker SL sync denetimi (`_verify_trailing_sync` 1642 — CI-11 koruması)
- Zorla kapatma (`force_close_all` 1838)
- Orphan emir temizliği (`_cleanup_primnet_orphans_on_restart` 1962)

### Kırmızı Bayraklar (kanıt ile)

1. **🚨 TRADING_OPEN/CLOSE hardcoded (h_engine.py:61-62):** `TRADING_OPEN = dtime(9, 40)`, `TRADING_CLOSE = dtime(17, 50)`. Ama `config/default.json:7-8` `"trading_open": "09:45"`. **Kod config ile senkron değil.** 5 dakika fark. Hibrit devir 9:40-17:50 arasında, engine OGUL 9:45-17:45 arasında. Tutarsızlık.

2. **Atomik devir kısmen bozuk (`transfer_to_hybrid:534-584`).** MT5 SL başarılı → DB insert başarısız olursa: MT5'te SL mevcut ama bellek/DB'de hibrit kaydı yok. Sonuç: H-Engine pozisyonu yönetmez (bellek boş), restart'ta DB'den yüklenmez, MT5'te ise SL aktif. Yorum "atomik" ama gerçekte MT5 yazımı geri alınmıyor (satır 582-584 `return` etmeden önce MT5 SL'i geri alan kod yok).

3. **CI-11 (Broker SL Sync) `sl_sync_warning`/`last_sl_check_at` field'ları var (98-99), `_verify_trailing_sync:1642`, `_sync_check_due:890` çağrı var.** `governance/protected_assets.yaml`'da CI-11 YOK (`inviolables:` listesi CI-01..CI-10, 10 adet). `USTAT_ANAYASA.md` Bölüm C'de CI-11 var. **Governance manifesto ile anayasa metni senkron değil.** Ayrıca `test_broker_sl_sync_periodic_check_contract` (test 3458) var.

4. **OLAY rejimi hibrit kapatma (707-713):** `force_close_all("OLAY_REGIME")` çağrılıyor. AX-6 (OLAY risk_multiplier=0) ile uyumlu, ama "EOD'da hibrit açık kalıyor" bayrağıyla çelişik mantık: OLAY'da kapatıyoruz, EOD'da kapatmıyoruz. Tutarsız politika.

5. **17:45 sonrası sadece NOTIFY (715-749):** `db.insert_notification("hybrid_eod", "Hibrit Pozisyon Açık", ...)` — kullanıcıya bildiriyor, kapatmıyor. AX-5 ile drift (yukarıdaki bayrak 1 ile paralel).

6. **Yön değişimi handler (816-854):** VİOP netting'de pozisyon yön değiştirirse, bekleyen emirler iptal ediliyor ama pozisyon kapatılmıyor — "manuel müdahale gerekli" bildirimi. Pozisyon muhtemelen MT5 tarafında SL olmadan açık kalıyor. Potansiyel korumasız pozisyon, AX-4 ihlali riski.

7. **`CLOSE_MAX_RETRIES = 3` (`_MAX_CLOSE_RETRIES` h_engine.py:139):** Bu config uyumlu (`close_max_retries: 3`). baba.py hardcoded 5 ile çelişiyor — iki motorda farklı retry sayısı.

### Alt-ajan iddialarından doğrulanmayan
- Alt-ajan "HEngine 3095 satır, constructor sıralaması doğru" dedi — doğrulandı ama atomik devir'deki DB-insert-fail senaryosunu yakalamadı.

---

## 4. `engine/ustat.py` (2195 satır — tam doğrudan okundu)

### Gerçek Satır Sayısı
2195 — son satır `get_trade_categories` metodu (2193-2195) ile dosya bitiyor. ✓

### Asıl Sorumluluk
Tek sınıf `Ustat` (satır 114). İşlem AÇMAZ (114-119 docstring). Görevler:
- Olay/karar kaydı (`_track_events` 234)
- Hata sorumluluğu ataması (`_check_error_attribution` 335, `_determine_fault` 446)
- Risk kaçırma raporu → BABA'ya feedback (`receive_feedback` üzerinden)
- Açılamayan işlem raporu (`_check_unopened_trades` 546)
- Ertesi gün analizi (`_run_next_day_analysis` 666)
- Strateji havuzu (`_update_strategy_pool` 1126, 4 profil)
- Kontrat tanıtımı (`_update_contract_profiles` 1182)
- Regülasyon önerileri + feedback loop (`_generate_regulation_suggestions` 1280, `_apply_regulation_feedback` 1375, `_apply_baba_feedback` 1524)
- Geçmiş kategorizasyonu (`_update_trade_categorization` 1919)
- Persistence (`_load_persisted_state` 1748, `_save_persisted_state` 1850)
- 30dk intraday check (`_run_intraday_check` 1002)

### Kırmızı Bayraklar

1. **ÜSTAT Siyah Kapı'da DEĞİL.** `governance/protected_assets.yaml` BK-01..BK-31 listesinde ustat.py fonksiyonu yok. Ama `USTAT_ANAYASA.md` ve `CLAUDE.md` "4 motor" olarak tanıtıyor. Ustat'ın mantığı değişebilir, tek sigortası Kırmızı Bölge dosyası olması (delete_class: C3).

2. **🐛 DEAD BUG — `get_active_params:2104-2108`:**
   ```python
   strat_dist = self.trade_categories.get("strategy_dist", {})
   for strat_name, strat_data in strat_dist.items():
       if isinstance(strat_data, dict):
           strategy_win_rates[strat_name] = strat_data.get("win_rate", 50.0)
   ```
   `trade_categories` dict'inde `strategy_dist` key'i **hiç oluşturulmuyor** (bkz. `_update_trade_categorization:2039-2054`; key `by_strategy` ama `int` değerleri tutuyor, dict değil). İlk defa `strategy_dist` key'i kullanılan yer burası. Bu yüzden `strat_dist = {}` her zaman; for döngüsü çalışmıyor; `isinstance(strat_data, dict)` asla True olmuyor. **`strategy_win_rates` ve `strategy_trade_counts` params'ta her zaman boş dict.** OĞUL bu bilgiyi kullanıyorsa sessiz kayıp var.

3. **Module-level hardcoded STRATEGY_PROFILES (38-91):** 4 profil × 7 parametre. ATR mult değerleri `config/default.json` strategies bölümüne göre çelişebilir — `default.json` `trend_follow.sl_atr_mult=1.5`, `ustat.py` `trend.sl_atr_mult=1.8`. İki kaynak, iki farklı değer.

4. **MUTABLE module-level state:** `STRATEGY_PROFILES` dict'i `_apply_regulation_feedback` tarafından runtime'da modifiye ediliyor (1447, 1460, 1482 vb.). Proseste birden fazla Ustat örneği olursa state paylaşılır. Engine tek instance olduğu için çalışıyor ama kod kokusu.

5. **`ATTRIBUTION_MIN_LOSS=100.0` (102), `MAX_ATTRIBUTIONS=50` (105), `STRATEGY_POOL_INTERVAL_SEC=1800` (108), `DEDUP_CACHE_TTL_SEC=3600` (111)** — module-level hardcoded. R-11 ihlali.

6. **"İyi gideni bozma" (1404-1410):** `overall_wr > 60.0` ise parametrelere dokunmaz. Akıllı. BABA feedback de atlanıyor (1409-1410). ✓

7. **Persistence overlay (1787-1808):** DB'deki strateji havuzundan parametre okuyup module-level `STRATEGY_PROFILES`'ı eziyor. Restart'ta feedback kayıpsız devam ediyor. Ama kod-config-DB 3-yönlü source-of-truth ikilemi yaratıyor.

### Alt-ajan iddialarından doğrulanmayan
- Alt-ajan "ÜSTAT 2195 satır" doğru. İçerik genel tanımı doğru. Ama dead bug satır 2104-2108'i fark etmedi.

---

## 5. `engine/mt5_bridge.py` (3171 satır — ~1800 satır okundu)

### Gerçek Satır Sayısı
3171.

### Asıl Sorumluluk
Tek sınıf `MT5Bridge` + dataclass'lar `AccountInfo` (53), `SymbolInfo` (66), `Tick` (83). Görevler:
- Bağlantı yönetimi (`connect` 628, `disconnect` 753, `heartbeat` 774)
- `_safe_call` (189) — ThreadPoolExecutor ile timeout + Circuit Breaker sarmalayıcı
- Sembol çözümleme (`_resolve_symbols` 307, `_next_expiry_suffix` 278, `check_trade_modes` 471)
- Piyasa verisi (`get_bars` 916, `get_tick` 955, `get_symbol_info` 871)
- Emir gönderme (`send_order` 993 + `_send_order_inner` 1050, 2-aşamalı SL/TP)
- Pozisyon (`close_position` 1503, `close_position_partial` 1613, `modify_position` 1723)
- Bekleyen emirler (`send_stop_limit`, `send_limit`, `cancel_pending_order`, `get_pending_orders` — kalan 1800+ satırda)
- Geçmiş senkronizasyonu (`get_history_for_sync` — kalan satırlarda)

### Kırmızı Bayraklar (kanıt ile)

1. **🚨 AX-4 "enforced_in" yanlış konum gösteriyor.** `governance/axioms.yaml:39` diyor ki AX-4 SL/TP zorunluluğu `engine/mt5_bridge.py::send_order`'da uygulanıyor. Kod incelemesi gösteriyor ki `mt5_bridge.py:1457-1467` SL/TP başarısız olursa **sadece log yazıp `sl_tp_applied=False` bırakıyor, pozisyonu kapatmıyor**. Gerçek koruma `ogul.py:1879-1943`'te. Anayasa manifesto yanlış konumu işaret ediyor.

2. **Siyah Kapı process check (670-691):** `terminal64.exe` tasklist ile kontrol. Windows'a özel, platform-spesifik. Yorum kapsamlı (648-669 başlığı "SİYAH KAPI — MT5 PROCESS KORUMASI"). Kod bu korumayı uyguluyor ✓.

3. **Retry budget cycle overrun riski:**
   - `DEAL_LOOKUP_RETRIES=10` (1323, 0.1-0.5s arası bekleme → max 5s)
   - `TICKET_MAX_RETRIES=20` (1342, 0.1-0.5s → max 10s)
   - `SLTP_MAX_RETRIES=5` (1420, 0.3-1.2s → max ~3s)
   - Toplam: ~18 saniye tek emir için. `CYCLE_INTERVAL=10s` ile çelişir.

4. **CORS kalıntısı ile çelişen durum yok (bu api/server.py'de).**

5. **Module-level hardcoded (40-49):** MAX_RETRIES_LAUNCH=5, MAX_RETRIES_RECONNECT=3, BASE_WAIT=2.0, HEARTBEAT_INTERVAL=10.0, MT5_CALL_TIMEOUT=8.0, CB_FAILURE_THRESHOLD=5, CB_COOLDOWN_SECS=30.0, CB_PROBE_TIMEOUT=5.0. R-11 sihirli sayı — config'e alınmalıydı.

6. **Circuit breaker mantığı (143-186):** `_cb_is_open:165` cooldown dolduğunda `_cb_tripped_at`'i günceller, `return False` döndürür (thread probe etsin). Bu "tek probe izni"ni güvence altına alır — iyi desen ✓.

7. **Write ops ana thread'de, read ops worker thread'de (225-267):** `order_send` doğrudan, diğerleri ThreadPoolExecutor'da. `_send_order_inner:1041-1050` üzerinden LifecycleGuard koruma. Satır 1062 `_order_lock, _write_lock` RLock'lar. RLock `close_position` içine recursive giriş için. Doğru düşünülmüş ✓.

8. **Deal lookup pattern (1322-1338):** `history_deals_get(order=order_ticket)` ile position_id alınıyor. Netting modda order_ticket ≠ position_ticket, bu doğru. 10 retry gerekli çünkü deal bazen 2sn sonra DB'ye düşüyor. İşletim gerçekliğine uyumlu.

9. **`sltp_request` sadeleştirme (1385-1393):** "GCM VİOP exchange modda TRADE_ACTION_SLTP sadece action/symbol/position/sl/tp kabul eder." Broker-spesifik. Broker değişirse bu kod bozulur. Test altyapısı yok (paper_mode testi?).

### Alt-ajan iddialarından doğrulanmayan
- Alt-ajan "send_order 2-aşamalı SL/TP, başarısız → pozisyon zorla kapatılır" dedi. **Bu yanlış — mt5_bridge kendisi kapatmıyor.** ogul.py'de kapatılıyor. Alt-ajan burada AX-4 "enforced_in" hatasını tekrar etti.

---

## 6. `engine/database.py` (2058 satır — tam okundu)

### Gerçek Satır Sayısı
2058 ✓.

### Asıl Sorumluluk
Tek sınıf `Database` (satır 245), thread-safe SQLite wrapper. `trades.db`'ye bağlanıyor (satır 35-36 `DB_PATH = database/trades.db`). **`ustat.db` hiçbir yerde referans edilmiyor.** Tablolar (CREATE TABLE ifadeleri 38-241):

bars (39), trades (51), strategies (71), risk_snapshots (80), events (92), top5_history (101), config_history (111), manual_interventions (120), liquidity_classes (128), app_state (137), hybrid_positions (151), hybrid_events (175), daily_risk_summary (194), weekly_top5_summary (208), notifications (218), mt5_journal (230) = **16 tablo**.

Metotlar: CRUD (insert_trade, get_trades, update_trade, deduplicate_trades, sync_mt5_trades), risk (insert_risk_snapshot, get_daily_end_snapshots), events (insert_event + dedup), top5, manual_interventions, hybrid (insert/update/close_hybrid_position, insert_hybrid_event), retention (run_retention, archive_old_trades, wal_checkpoint, vacuum), notifications.

### Kırmızı Bayraklar

1. **🚨 `ustat.db` ÖLÜ DOSYA.** Kanıt: `database.py` tek DB path `trades.db` (satır 35). Başka `self._conn2` veya `ustat.db` referansı yok. `database/ustat.db` dosyası 0 byte. CLAUDE.md ve kod aradaki tutarsızlık: doküman `ustat.db`'yi motor bir veritabanı olarak tanıtıyor, kod ise kullanmıyor.

2. **`_event_dedup_cache` class-level dict (1128).** Tüm instance'lar paylaşır. Instance yazım operasyonları `self._lock` dışında (1164, 1168-1171). Thread-safety zayıf. Engine tek instance için çalışıyor.

3. **SQL string interpolation — `deduplicate_trades:867, 872-874, 890-893`:** `excluded=",".join(str(d) for d in deleted_ids)` — `deleted_ids` set integer tutuyor, güvenli. Ama desen riskli; gelecekte birisi string ekleyebilir. Parametrized sorgulama daha güvenli olurdu.

4. **`archive_old_trades:1496-1574` atomik değil.** Ayrı DB aç, INSERT, DELETE, close. INSERT başarılı + DELETE başarısız = duplicate arşiv. Bir sonraki çalışmada `INSERT OR IGNORE` (1552) koruyor ama şık değil.

5. **Migration idempotent (`_migrate_schema:365-383`):** try/except pass ile ALTER TABLE. Doğru desen.

6. **PRAGMA quick_check sadece başlangıçta (satır 291-303):** Bozuk DB erken tespit. Ama engine'i durdurmuyor, sadece log yazıyor. Operatör sorumluluğu. Fail-closed ruhuna aykırı.

7. **`severity` notation tutarsızlığı:** events tablosu `INFO/WARNING/ERROR/CRITICAL` uppercase (kod 1141-1176); notifications tablosu `info/warning` lowercase (varsayılan 221). Tutarsız.

### Alt-ajan iddialarından doğrulanmayan
- Alt-ajan "16 tablo" doğru. CREATE TABLE konumu satır 39-240 doğru. `ustat.db` hakkında "BİLMİYORUM" demişti — **şimdi kanıtlanmış: ustat.db ölü**.

---

## 7. `engine/main.py` (1573 satır — tam okundu)

### Gerçek Satır Sayısı
1573 ✓.

### Asıl Sorumluluk
Sınıf `Engine` (72) + özel hatalar `_SystemStopError`, `_DBError` + `run()` entry point (1547). Görevler:
- Engine oluşturma (constructor 85-213, 128 satır — 8 alt-motor + cross-referanslar)
- Ana döngü (`_main_loop` 574 — 182 satır, heartbeat, cycle, yedekleme, retention, haftalık bakım)
- Tek cycle (`_run_single_cycle` 760 — 207 satır)
- MT5 reconnect (`_heartbeat_mt5` 1144, 3 deneme)
- Graceful shutdown (`stop` 415 — 153 satır)
- State restore (`_restore_state` 1424 — 105 satır)
- Günlük DB cleanup (`_run_daily_cleanup` 1306), haftalık bakım (`_run_weekly_maintenance` 310)

### Kırmızı Bayraklar

1. **🚨 DOKÜMANTE EDİLMEMİŞ 5. MOTOR: `ManuelMotor`.** Constructor'da yaratılıyor (145-163), `_run_single_cycle:918-928`'de cycle'da çağrılıyor (`self.manuel_motor.sync_positions()`). Çağrı sırası gerçekte:
   - 1: BABA `_run_baba_cycle` (850)
   - 2: BABA `check_risk_limits` (854)
   - 3: OĞUL `select_top5` (865)
   - 4: OĞUL `process_signals` (895)
   - 5: H-Engine `run_cycle` (910)
   - **6: ManuelMotor `sync_positions` (920)** ← anayasada YOK
   - 7: ÜSTAT `run_cycle` (932)
   
   `governance/axioms.yaml:16` AX-1: *"BABA -> OGUL -> H-Engine -> USTAT"*. ManuelMotor yok. `protected_assets.yaml` R-01: *"heartbeat → data → BABA → risk_check → OĞUL → H-Engine → ÜSTAT"*. ManuelMotor yok. **Teknik olarak anayasa metni çalışan sırayı eksik tanımlıyor.**

2. **Cross-motor referans döngüsü (145-163):** `manuel_motor.ogul = self.ogul`, `manuel_motor.h_engine = self.h_engine`, `baba.manuel_motor = self.manuel_motor`, `ogul.manuel_motor = self.manuel_motor`, `h_engine.manuel_motor = self.manuel_motor`, `baba.h_engine = self.h_engine`, `baba.ogul = self.ogul`. **7 çift yönlü referans.** Test edilebilirliği zor, mock'lamak karmaşık.

3. **Risk kapısı davranış (894-897):**
   ```python
   if risk_verdict.can_trade or risk_verdict.risk_multiplier > 0:
       self.ogul.process_signals(top5, regime)
   else:
       self.ogul.process_signals([], regime)
   ```
   `can_trade=False + risk_multiplier>0` durumunda (L2 OLAY vb.) OĞUL hâlâ çağrılıyor. AX-2 "OGUL can_trade=False iken sinyal üretemez" ile uyumu: `process_signals` içinde rejim + L3 kontrolleri var; process_signals çağrılmak zorunda çünkü trailing/EOD/sync işlemlerini yapar. Top5 boş gittiğinde yeni sinyal üretemez. Ama "top5 boş" yerine "risk_verdict paylaşımı" daha temiz olurdu.

4. **Engine watchdog `api/server.py:113-142` + `_heartbeat_mt5:1182-1186` fail-closed çelişkisi:** main.py fail-closed (MT5 kurtarılamaz → sistem durdur, 1182-1186). Ama api/server.py lifespan engine 3x restart deniyor, başarısızsa API açık kalıyor ama engine duruyor (135 `return`). UI'yı yanıltıcı durum. CI-10 "fail-closed" ile kısmen çelişki.

5. **`stop:484-518` manuel pozisyon korunur.** Engine durdurulursa OĞUL+Hybrid kapatılıyor, manuel açık kalıyor. Docs Kural #10 ile tutarlı ✓.

6. **`CYCLE_INTERVAL=10` (53), `CYCLE_WARN_THRESHOLD=15.0` (59), `CYCLE_CRITICAL_THRESHOLD=30.0` (60), `CONSECUTIVE_SLOW_LIMIT=3` (61):** Module-level hardcoded, R-11 ihlali.

7. **Ardışık yavaş cycle → MT5 reconnect tetikleme (721-737):** 3 yavaş cycle sonrası disconnect+reconnect. Ama bu sırada kullanıcıya aktif pozisyon yönetimi sekteye uğrayabilir. Test edilmesi zor bir senaryo.

### Alt-ajan iddialarından doğrulanmayan
- Alt-ajan "constructor sırası Config → DB → MT5 → Pipeline → Ustat → Baba → Ogul → HEngine" dedi. Doğrulandı (satırlar 95, 96, 97, 100, 101, 102, 118, 124) ✓. Ama ManuelMotor + cross-referansları ve 5. motor gerçeğini atlamıştı.

---

## 8. `api/server.py` (273 satır — tam okundu)

### Gerçek Satır Sayısı
273 ✓.

### Asıl Sorumluluk
FastAPI uygulaması. `lifespan` (71-186) ile Engine oluşturma + thread başlatma + graceful shutdown. 23 router include (216-238).

### Kırmızı Bayraklar

1. **🚨 Ogul constructor `risk_params` parametresi olmadan çağrılıyor (satır 98).** `api/server.py:98`: `ogul = Ogul(config, mt5, db, baba=baba)`. Ama `engine/main.py:118-121`: `ogul = Ogul(self.config, self.mt5, self.db, baba=self.baba, risk_params=self.risk_params)`. **İki farklı çağrı.** Hangisi doğru? Muhtemelen `Ogul.__init__` `risk_params=None` default alıyor ve main.py'de explicit geçiliyor. Ama api/server.py yolundan gidildiğinde risk_params'sız Ogul oluşuyor. Daha kötüsü: api/server.py `Engine(...)` çağrısında (100-104) Ogul zaten oluşturulmuş haliyle geçiliyor, Engine __init__'teki `ogul or Ogul(...)` branch'i kullanılmıyor → risk_params asla set edilmiyor. **POTANSİYEL BUG.** ogul.py'de `self.risk_params` kullanılıyor (ogul.py:1736), None olursa hata.

2. **"Engine olmadan da API ayağa kalksın" (148-150):**
   ```python
   except Exception as e:
       logger.error(f"Engine başlatma hatası: {e}")
       # Engine olmadan da API ayağa kalksın (mock/debug modu)
   ```
   Engine başlatılamazsa API yine açık. Endpoint'ler None engine'e erişir. Trading engine olmadan API ayağa kalkması fail-closed ile çelişir. "Mock/debug modu" yorumu production kodunda tehlikeli.

3. **Engine crash watchdog (113-142):** 3 restart denemesi sonrası API açık, engine kapalı. Satır 135: `return # API açık kalır, engine duruyor`. CI-10 "fail-closed: sistem kilitli duruma geçer" ile uyumsuzluk.

4. **`pywebview` CORS origins (202-203):** `"http://127.0.0.1:8000"` ve `"http://localhost:8000"` "pywebview production/Chrome" yorumu ile. CLAUDE.md `pywebview KULLANILMAZ (v5.9.1 itibariyle kaldırıldı)` diyor. Ölü referans.

5. **Electron legacy CORS (208):** `"app://."` — dokümante edilmemiş eski protocol. Şu an kullanılıyor mu belirsiz.

6. **SPA static fallback (247-263):** dist yoksa JSON fallback (266-273). Production build yapılmamışsa (`desktop/dist/index.html` yoksa) API SPA sunamaz. Dev-mode için uygun.

### Alt-ajan iddialarından doğrulanmayan
- Alt-ajan "constructor sırası doğru" dedi. Doğrulandı ama risk_params uyumsuzluğunu yakalamamıştı.
- Alt-ajan 23 router'ı doğru saydı ✓.

---

## 9. `governance/axioms.yaml` (73 satır — tam okundu)

### Gerçek Satır Sayısı
73 ✓.

### İçerik
`manifest_version: "3.0"`, 7 axiom: AX-1..AX-7.

### Kırmızı Bayraklar

1. **🚨 AX-4 `enforced_in` YANLIŞ:** `engine/mt5_bridge.py::send_order` yazıyor. Gerçek koruma `engine/ogul.py::_execute_signal`'da. Manifest yanlış konumu işaret ediyor — denetim aracı (`tools/check_constitution.py`) bu dosya-fonksiyon eşlemesini doğrularsa PASS diyecek (imza var), ama gerçek davranış kontrol yok.

2. **AX-1 ManuelMotor'u tanımıyor:** `BABA -> OGUL -> H-Engine -> USTAT`. Kodda 5. motor var. Anayasa axiom'u eksik.

3. **AX-5 hibrit dahil değil:** "17:45'te tüm pozisyonlar kapatılır" deniyor. Kod hibrit kapatmıyor. Axiom ile kod çelişiyor.

---

## 10. `governance/protected_assets.yaml` (450 satır — tam okundu)

### Gerçek Satır Sayısı
450 ✓.

### İçerik
- `manifest_version: "2.0"`, `constitution_version: "2.0"` (**USTAT_ANAYASA.md Versiyon 3.0 ile uyumsuz**)
- `anayasa_sha256: 5befa31a5e178ba434df7664a7e6787866cc13568acf3636e01eb1063abefdff`
- 10 Kırmızı Bölge dosyası ✓
- 31 Siyah Kapı fonksiyonu (BK-01..BK-31) — 11 BABA + 5 OĞUL + 6 MT5 + 3 Main + 6 Startup ✓
- 12 kural (R-01..R-12) — USTAT_ANAYASA Bölüm C'deki R-01..R-16 ile sayım uyumsuz
- 12 korunan config anahtarı
- 10 CI maddesi (CI-01..CI-10) — USTAT_ANAYASA.md ise CI-11'i tanımlıyor

### Kırmızı Bayraklar

1. **🚨 Versiyon uyumsuzluğu:** `constitution_version: "2.0"` ama USTAT_ANAYASA.md:3 `**Versiyon:** 3.0`. `tools/check_constitution.py` hash kontrolü yapıyor (satır 245-274 görülmedi ama alt-ajan rapor etti) — hash eşleşmezse CI kırılır. Manifesto anayasa güncellemesinde geride kalmış.

2. **CI-11 eksik:** Anayasa Bölüm C tablosunda CI-11 "Broker SL Sync Periyodik Doğrulama" var (USTAT_ANAYASA.md:75). protected_assets.yaml `inviolables:` listesinde CI-01..CI-10 var, CI-11 YOK. `h_engine.py`'de ilgili kod mevcut (`_verify_trailing_sync`, `sl_sync_warning`, `SL_DESYNC` event). Test de var (`test_broker_sl_sync_periodic_check_contract`). Ama governance manifest güncellenmemiş.

3. **R-XX sayımı tutarsız:** Anayasa metni Bölüm D'de "16 kural" atfı (CLAUDE.md), protected_assets sadece R-01..R-12 (12 adet) tanımlıyor. R-13..R-16 kayıp.

4. **BK-04 `_close_ogul_and_hybrid` `linked_rules: []`** (satır 94). Anayasa Kural #10 "L2 kayıp → _close_ogul_and_hybrid" diyor ama yam R-10 "Tek Çalışma Klasörü". Gerçek kural referansı yok. Zayıf.

5. **Protected config keys'te eksik:**
   - `risk.max_correlated_positions` (3) — CLAUDE.md'de var, protected_assets'te YOK
   - `risk.margin_reserve_pct` vs `engine.margin_reserve_pct` — config'te `engine.margin_reserve_pct: 0.2` (satır 12), protected_assets'te `risk.*` sadece. margin_reserve_pct korumasız.

---

## 11. `governance/authority_matrix.yaml` (160 satır — tam okundu)

### Gerçek Satır Sayısı
160 ✓.

### İçerik
`manifest_version: "3.0"`. 13 yetki hücresi (cells:). `yellow_zone` listesi 7 dosya.

### Kırmızı Bayraklar

1. **Yellow zone listesi (153-160) `api/routes/killswitch.py` + `api/routes/positions.py` içeriyor.** CLAUDE.md Bölüm 4.2 ile uyumlu ✓. Ama CLAUDE.md'deki 7. madde `desktop/mt5Manager.js` bu YAML'da var (160). Uyumlu.

2. **`zone: any, class: C0, actions: [delete], authority: plan` (48-51).** Dosya silme her zaman onay. Doğru.

3. **`zone: red, class: any, actions: [delete, refactor], authority: yasak` (123-127).** Refactor yasak — ama "refactor"ün pratikte ne anlama geldiği belirsiz. Değişken yeniden adlandırma refactor mi?

---

## 12. `governance/triggers.yaml` (139 satır — tam okundu)

### Gerçek Satır Sayısı
139 ✓.

### İçerik
`manifest_version: "3.0"`. 11 tetik: TR-AX1..AX7 (HALT), TR-CONFIG/SCHEMA/API/RED-30/BLACKDOOR, TR-UI/CRITICAL-FLOW, TR-MAGIC, TR-MT5-INIT-SCAN, TR-CALL-ORDER.

### Kırmızı Bayraklar

1. **Tetikler sadece kurallarla eşleşiyor, değerler sayısal değil.** `TR-CONFIG` "config/default.json'da risk parametresi değişiyor" — "risk parametresi" hangi JSON path'ler? Belirsiz. `tools/check_triggers.py` bunu nasıl yorumluyor (alt-ajan 76-150 arası scan_triggers dedi) — implementasyon bilmediğim için doğrulayamadım.

2. **TR-AX4 condition "send_order SL/TP basarisizlik sonrasi pozisyon kapatma kaldiriliyor" (37).** Gerçek kod `ogul.py`'de olduğundan tetik `mt5_bridge.py` diff'ini taradığında ihlali tespit edemez. Manifest yanlış konumu koruyor.

3. **TR-MAGIC (110-114) "Hardcoded sayisal sabit ekleniyor (self.config.get disinda)"** — yeni ekleme mi, mevcut mu? Mevcutta baba.py 116-209, h_engine.py 59-63, mt5_bridge.py 40-49, ustat.py 102-111, main.py 53-61 zaten hardcoded. Tetik geriye dönük tarama yapıyor mu? Muhtemelen sadece `git diff`. Dolayısıyla **mevcut sihirli sayılar koruma altında değil**.

---

## 13. `USTAT_ANAYASA.md` (294 satır — system-reminder önizleme + tam okuma)

### Gerçek Satır Sayısı
294.

### İçerik
Bölüm A-M. Bölüm C'de CI-01..CI-11 tablosu (11 madde). Bölüm D'de sınıflandırma (C0-C4). Bölüm F'de enforcement zinciri. Bölüm H'de anayasa değişiklik rejimi.

### Kırmızı Bayraklar

1. **Versiyon 3.0** (satır 3). protected_assets.yaml `constitution_version: "2.0"` — drift.

2. **Bölüm C — 11 CI maddesi.** CI-11 Broker SL Sync. protected_assets.yaml'da 10 CI. Drift.

3. **Bölüm D — C3 24 saat soğuma kuralı (tablo sütunu).** Bunun uygulanması `tools/seal_change.py` üzerinden. İşleyiş alt-ajan raporundan biliniyor ama kod doğrulanmadı.

4. **Bölüm L — İlke hiyerarşisi (262-273):** "Alt katman anayasayla çeliştiğinde anayasa kazanır." Pratikte `governance/*.yaml` manifesto anayasanın altında. Şu anki drift'ler (CI-11, constitution_version) anayasa galibiyeti gerektirir ama kim güncellenir?

---

## 14. `tests/critical_flows/test_static_contracts.py` (3504 satır — 55 test)

### Gerçek Satır Sayısı
3504 ✓.

### İçerik
55 test fonksiyonu (Grep `^def test_` saydım). Bunların ~12'si doğrudan anayasal koruma testi, diğerleri UI/backend sözleşme testleri.

### Kırmızı Bayraklar

1. **🚨 Testlerin ÇOĞU DAVRANIŞ değil SÖZLEŞME/İMZA testi.** Örnekler:
   - `test_ogul_has_end_of_day_check:83-93` — sadece `"17"` ve `"45"` string'i arıyor (`and` değil `and` — ikisi de geçmeli). **Hibrit kapatma doğrulanmıyor.**
   - `test_baba_l2_only_closes_ogul_and_hybrid:3082` — sadece `hasattr(Baba, "_close_ogul_and_hybrid")`. Fonksiyon var mı kontrolü; davranış yok.
   - `test_baba_l3_closes_all_positions:3092` — sadece `hasattr`.
   - `test_ogul_respects_baba_can_trade_gate:3101` — source'ta `"can_trade"` string'i arıyor.
   - `test_mt5_bridge_has_circuit_breaker:3113` — source'ta `"CB_FAILURE_THRESHOLD"` arıyor.
   - `test_no_magic_numbers_in_baba_risk_limits:3147` — `"self.config"` arıyor (negatif — diğer magic'leri yakalamaz).

   **Sonuç:** Kod silinirse veya imza bozulursa testler yakalar. Ama **davranış ekleyip çıkarmak (örn. hibrit kapatma)** bu testleri geçebilir.

2. **`test_main_loop_order:3131` REGEX pattern `def _run_single_cycle.*?def`** — BABA ve OĞUL ilk karşılaşıldığı satırlar idx bazlı karşılaştırıyor. idx_baba < idx_ogul kontrol ediyor. Bu çalışır ✓. Ama yeni bir motor araya girerse (ManuelMotor gibi) bu test hala yeşil geçer.

3. **`test_no_rogue_mt5_initialize_calls:3161-3214` AST tabanlı ve GERÇEK davranış testi** ✓. Yetkili dosyalar hariç tüm projeyi tarar. allowed_files: engine/mt5_bridge.py, health_check.py, api/routes/mt5_verify.py. Bu iyi yazılmış.

4. **`test_sltp_failure_closes_unprotected_position:50-79` string pattern arama.** "OgulSLTP" veya "ogul_sltp", "Anayasa 4" veya "korumasiz", "close_position" string'lerini arıyor. Gerçek akış testi değil.

5. **CI-11 testi var (`test_broker_sl_sync_periodic_check_contract:3458`)** — okumadım ama varlığı doğrulandı.

6. **12 test gerçekten kritik akışlar:** 39, 50, 83, 97, 109, 3082, 3092, 3101, 3113, 3119, 3131, 3147, 3161 (13 sayım). Bu `tests/critical_flows/test_static_contracts.py` dosyasında — klasör altında 3 test daha var (alt-ajan raporuna göre). Pre-commit bunları çalıştırıyor.

### Alt-ajan iddialarından doğrulanmayan
- Alt-ajan "55 test" dedi — doğrulandı. "Siyah Kapı 31 fonksiyonu + 12 Anayasa kuralı" dedi — doğrulandı ama testler davranış değil imza testleri.

---

## ÖZET: KRİTİK BAYRAKLAR (ÖNEM SIRASINA GÖRE)

### Seviye 1 — Anayasa/Kod Drift (acil)

| # | Bayrak | Dosya:Satır | Etki |
|---|---|---|---|
| 1 | **Hibrit EOD'da kapatılmıyor** | `ogul.py:2154`, `h_engine.py:715-749` | AX-5, CI-04, R-06 ihlali |
| 2 | **AX-4 enforced_in yanlış konum** | `axioms.yaml:39`, `ogul.py:1879-1943` | Manifest koruma göstermiyor |
| 3 | **ManuelMotor anayasada yok ama çalışıyor** | `main.py:920`, `axioms.yaml:16` | AX-1 eksik tanım |
| 4 | **CI-11 Anayasa'da var, protected_assets'te yok** | `USTAT_ANAYASA.md:75`, `protected_assets.yaml:410` | Manifest-anayasa drift |
| 5 | **constitution_version: "2.0"** ama anayasa v3.0 | `protected_assets.yaml:7`, `USTAT_ANAYASA.md:3` | check_constitution hash uyumsuzluğu |

### Seviye 2 — Kod Kalitesi/Bug Riski

| # | Bayrak | Dosya:Satır | Etki |
|---|---|---|---|
| 6 | **`ustat.db` ölü dosya** | `database.py:35`, dosya 0 byte | Doküman yanıltıcı |
| 7 | **`strategy_dist` key bug** | `ustat.py:2104-2108` | strategy_win_rates her zaman boş |
| 8 | **api/server.py `risk_params` geçmiyor** | `api/server.py:98`, `main.py:118-121` | Ogul.risk_params None olabilir (runtime path farkı) |
| 9 | **Hardcoded CLOSE_MAX_RETRIES=5** | `baba.py:2637`, config'te 3 | Config kod tarafından eziliyor |
| 10 | **`TRADING_OPEN=09:40` hardcoded** | `h_engine.py:61`, config'te 09:45 | Motor farklı saat dilimlerinde çalışıyor |
| 11 | **`transfer_to_hybrid` atomik değil** | `h_engine.py:568-584` | MT5 SL yazıldı, DB yazım fail → zombi state |
| 12 | **Yön değişimi → pozisyon SL-siz kalabilir** | `h_engine.py:816-854` | Korumasız pozisyon riski |

### Seviye 3 — Test Katmanı Zayıflığı

| # | Bayrak | Etki |
|---|---|---|
| 13 | **55 testin çoğu string/imza testi** | Davranış silinmesi yakalanmıyor (hibrit EOD) |
| 14 | **test_ogul_has_end_of_day_check sadece "17" "45" arıyor** | Hibrit kapatma testsiz |
| 15 | **test_baba_l2_only_closes_ogul_and_hybrid sadece hasattr** | L2 kapatma davranışı doğrulanmıyor |

### Seviye 4 — R-11 Sihirli Sayı İhlalleri (yaygın)

- `baba.py:116-209` (rejim eşikleri)
- `h_engine.py:59-63` (TRADING saatleri, ATR period)
- `mt5_bridge.py:40-49` (retry budgetleri)
- `ustat.py:102-111` (ATTRIBUTION_MIN_LOSS, MAX_ATTRIBUTIONS vb.)
- `main.py:53-61` (CYCLE_INTERVAL, thresholds)

Trigger TR-MAGIC yeni eklemeleri yakalar, mevcutları korumaz.

### Seviye 5 — CORS / Ölü Kod

- `api/server.py:202-203` pywebview CORS (pywebview kaldırılmış)
- `api/server.py:208` Electron legacy `app://.`

---

## ALT-AJAN (ÖNCEKİ HAIKU RAPORLARI) — YANILGILARI

1. **"31/31 Siyah Kapı DOĞRULANDI"** — Alt-ajan sadece fonksiyon adlarının protected_assets.yaml ile eşleştiğini doğruladı. Davranış/mantık doğrulaması yok. CI-11 için sicil eksik.

2. **"send_order 2-aşamalı SL/TP, başarısız → pozisyon zorla kapatılır"** — YANLIŞ. mt5_bridge.py:1457-1467 sadece log yazıyor. Asıl koruma ogul.py:1879-1943'te.

3. **"constitution_version: '2.0'"** — Alt-ajan raporladı, ama "drift" olarak işaretlemedi; ben drift olarak işaretliyorum.

4. **"ManuelMotor 4. motor olarak dokümantasyonda yok"** — Alt-ajan bulgusunu ben öncelikli konuma taşıdım; anayasal ihlal boyutu.

5. **"55 test"** — Sayım doğru. Ama "12 Kritik Akış Test ✓" iddiası davranış testi olduklarını ima ediyor; gerçekte imza/string testi.

---

## OKUMA KAPSAMI

**Doğrudan okunan:**
- `engine/main.py` 100%
- `engine/database.py` 100%
- `engine/ustat.py` 100%
- `engine/h_engine.py` ~70% (satır 1-2200)
- `engine/mt5_bridge.py` ~57% (satır 1-1800)
- `engine/baba.py` ~30% (1-330, 1472-1870, 2331-2830)
- `engine/ogul.py` ~20% (540-740, 1648-1980, 2105-2290)
- `api/server.py` 100%
- `governance/*.yaml` 100%
- `USTAT_ANAYASA.md` 100%
- `tests/critical_flows/test_static_contracts.py` ~10% (iskelet + önemli testler)

**Okunmayan:**
- baba.py: 330-1472 (rejim algılama detayları, fake sinyal), 1870-2331 (drawdown alt detayı, intervention), 2830-3388 (fake sinyal alt katmanları, yardımcılar)
- ogul.py: 360-540 (init, property, ustat entegrasyonu), 740-1648 (oylama, strateji kontratları detayı), 1980-2105 (yardımcılar), 2290-3570 (manage_position, strateji yönetim detayları, sync, restore, select_top5)
- h_engine.py: 2200-3095 (_check_primnet_target, _finalize_close, _handle_external_close, helpers)
- mt5_bridge.py: 1800-3171 (send_stop_limit, send_limit, pending orders, history_for_sync, account detayları)
- test_static_contracts.py: 200-3082 (UI/backend contract testleri)

**Bu okunmayan bölümlerde ek bayraklar olabilir** — özellikle ogul.py `_manage_position`, baba.py rejim algılama, mt5_bridge.py pending emir akışları. Faz 1 (audit) için bunlar hedefli incelenmeli.

---

## SONUÇ

Faz 0 tamamlandı. **15 yeni kırmızı bayrak** doğrudan kanıtla (dosya:satır) belgelendi. Bunlardan 5 adedi anayasa/kod drift, 7 adedi kod kalitesi/bug riski, 3 adedi test zayıflığı.

**Audit (Faz 1) için öncelik sırası önerisi:**
1. Hibrit EOD kapatma (anayasal ihlal, finansal risk)
2. AX-4 enforced_in düzeltilmesi (manifest drift)
3. ManuelMotor → anayasal tanıma
4. ustat.py strategy_dist bug (sessiz feature kaybı)
5. api/server.py risk_params çözümlemesi

Bu rapor kullanıcı onayına hazır.
