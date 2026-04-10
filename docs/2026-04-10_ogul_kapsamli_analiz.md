# OĞUL Kapsamlı Analiz Raporu

**Tarih:** 10 Nisan 2026
**Versiyon:** v5.9.0 (commit `d9177df` sonrası)
**Kapsam:** `engine/ogul.py` (3378 satır), BABA–OĞUL–H-Engine–Manuel Motor–MT5 Bridge etkileşimleri
**Tür:** READ-ONLY teknik denetim — kod değişikliği YOK
**Çalışma prensipleri:** CLAUDE.md §3 (kanıta dayalı, varsayım yok)

---

## 1. Yönetici Özeti

OĞUL, CLAUDE.md §1.1'de tanımlanan görev sınırlarına refactor sonrası (#149) büyük ölçüde uymaktadır: **sinyal üret → emir gönder → pozisyon yönet → kapat**. 1016 satırlık risk/zaman/dead kod silinmiş, günlük-kayıp sorumluluğu BABA'ya devredilmiştir.

Ancak **derin incelemede 6 kritik (C), 9 yüksek (Y), 12 orta (O) ve 7 düşük (D) seviye bulgu tespit edilmiştir.** Bunların en ağırı `_execute_signal` içindeki `lot = 1.0` hardcode satırıdır — BABA'nın fixed-fractional pozisyon boyutlama motoru, rejim çarpanı, graduated lot ve haftalık yarılama dahil tamamen devre dışıdır. Test modu olduğu beyan edilmekle birlikte, bu durum üretim güvenlik kapılarını fiili olarak tek bir float'a indirgemiştir.

**Genel kanaat:** OĞUL verilen görevleri **yapısal olarak yapabilecek kapasitededir.** Mimari (state machine, orphan guard, atomik concurrent limit, netting-lock, EOD double-verify) sağlamdır. Ancak mevcut test modu kısıtlaması kaldırılmadan, piyasa mantığı ile uyumlu bazı filtreler gevşetilmeden veya düzeltilmeden canlı risk alınmamalıdır. Öncelikli 6 C-bulgusu giderilmeden v5.9 gerçek para ile uçurulmamalıdır.

---

## 2. Yöntem

1. `engine/ogul.py` dosyası baştan sona okundu (satır 1–3378, 49 metod, 0 null byte, AST OK)
2. Bağımlı modüller hedefli okundu: `engine/ogul_sltp.py`, `engine/baba.py` (kilit fonksiyonlar), `engine/main.py` (`_run_single_cycle`)
3. Her bulgu için **kanıt satır numarası** gösterilmiştir
4. Bulgular 4 şiddet seviyesinde (C/Y/O/D) ve 3 kategoride (mantık, matematik, görev çakışması) sınıflandırılmıştır
5. Kod değişikliği yapılmamıştır (READ-ONLY görev)

---

## 3. OĞUL'un Beyan Edilen Görev Tanımı

CLAUDE.md §1.1'den:

> **OĞUL:** Top 5 kontrat seçimi, sinyal üretimi, emir yönetimi, pozisyon takibi

CLAUDE.md §4.4 (Siyah Kapı — OĞUL 5 fonksiyon):

| # | Fonksiyon | Görev |
|---|-----------|-------|
| 12 | `_execute_signal()` | Emir öncesi risk kontrolleri + sinyal yürütme |
| 13 | `_check_end_of_day()` | 17:45 zorunlu kapanış |
| 14 | `_verify_eod_closure()` | Gün sonu hayalet pozisyon temizliği |
| 15 | `_manage_active_trades()` | Pozisyon yönetimi |
| 16 | `process_signals()` | Sinyal işleme (SABİT çağrı sırası) |

OĞUL'un BABA'ya devredilen sorumluluklar: günlük/aylık kayıp stop, spread guard, yatay piyasa kapama, son-45dk kâr kapama.

---

## 4. OĞUL İç Mimari Analizi

### 4.1 Dosya İstatistikleri

| Metrik | Değer |
|--------|-------|
| Satır sayısı | 3378 |
| Modül boyutu | 151,102 bayt |
| `class Ogul` satır aralığı | 360–3377 |
| Metod sayısı | 49 |
| Modül-seviyesi sabit sayısı | ~70 |
| İçe aktarım kalemi | 17 modül |
| Feature flag: `USE_UNIVERSAL_MANAGEMENT` | True (eski strateji bazlı yönetim feature-flag ile korunur) |
| Test modu bayrağı | `lot = 1.0` hardcoded (#149 sonrası) |

### 4.2 Sınıf Yapısı

`Ogul` sınıfı 49 metod içerir. İşlevsel bloklar:

1. **Sabit tanım bloğu** (satır 1–360): Eşikler, likidite sınıfları, yardımcı fonksiyonlar (`_clamp_trailing_distance`, `_find_swing_low/high`)
2. **__init__** (360–519, ~160 satır): Config yükleme + state alanları + Top5Selector + OgulSLTP kurulumu
3. **process_signals** (519–635): 10-saniye ana döngü girişi
4. **Sinyal üretimi** (641–1575): `_is_new_m5_candle`, `_calculate_voting`, `_determine_direction`, `_generate_signal`, `_check_trend_follow/mean_reversion/breakout`
5. **Emir yürütme** (1581–1920): `_execute_signal`, `_log_cancelled_trade`, `_remove_trade`, `_update_fill_price`
6. **Gün sonu** (1930–2133): `_is_trading_allowed`, `_check_end_of_day`, `_verify_eod_closure`
7. **Pozisyon yönetimi — evrensel** (2139–2678): `_manage_active_trades`, `_manage_position`, `_determine_trade_mode`, 4 mod (`_mode_protect/_mode_trend/_mode_defend/+ÇIKIŞ`), `_is_structural_break`, `_check_momentum_strength`, `_check_volume_spike`
8. **Pozisyon yönetimi — legacy** (2684–2900): `_manage_trend_follow/_manage_mean_reversion/_manage_breakout` (feature flag=False için)
9. **Senkronizasyon** (2905–3097): `_sync_positions`, `_handle_closed_trade`
10. **Restore** (3103–3333): `restore_active_trades` — MT5+DB çapraz eşleme, yetim tespiti, manuel/hibrit exclusion
11. **Top5 delegasyonları** (3338–3378): `select_top5`, `current_top5`, `current_scores`, haber/bilanço delegasyonları

**Değerlendirme:** Yapısal ayrım nettir. Tek sınıf 3378 satır olsa da fonksiyonlar iyi modüle edilmiş, bölümler ASCII heading bloklarıyla ayrılmıştır. Kod kokusu yok.

### 4.3 State Alanları

`__init__` içinde tanımlı alanlar (satır 450–519):

**Canlı kullanılan:**
- `active_trades: dict[str, Trade]` — sembol → Trade eşleme (çekirdek state)
- `_trade_lock: threading.Lock` — atomik concurrent check
- `_risk_multiplier: float = 1.0` — main.py tarafından her cycle set edilir
- `_symbol_loss_count: dict[str, int]` — per-sembol ardışık kayıp
- `_symbol_loss_date: date` — rollover bayrağı
- `last_signals: dict[str, str]` — Dashboard için per-sembol bias
- `_pyramid_last_add: dict[str, datetime]` — piramit tekrar girişimi frenleme
- `_r_multiple_history: deque` — expectancy hesabı
- `_r_expectancy: float` — global expectancy
- `_top5: Top5Selector` — kompozisyon
- `_sltp: OgulSLTP` — kompozisyon (plain STOP SL yöneticisi)

**#149 sonrası fonksiyonel olarak ölü, API-contract için korunan:**
- `_daily_loss_stop: bool` (satır 542–544'te "sıfırlanıyor" ama kimse True set etmiyor — `api/routes/health.py:133` okuduğu için tutuluyor)
- `_daily_loss_stop_date: date`
- `_monthly_start_equity`, `_monthly_start_date`, `_monthly_dd_stop`, `_monthly_dd_warn`

**Bulgu O-1 (Ölü state):** `_daily_loss_stop` artık hiç set edilmiyor ama `process_signals`'ın ilk 6 satırı (540–544) hâlâ günlük reset yapıyor. Bu silent dead code — kaldırılması CLAUDE.md §4.4 Kural 10'u ihlal etmez çünkü sorumluluk zaten BABA'ya devredilmiş. API endpoint'in dönüş değeri kalıcı olarak `False` olacak; bu değer frontend tarafından yanıltıcı olabilir. **Öneri:** `health.py:133` okuma noktası BABA'nın eşdeğer durumuna yönlendirilip OĞUL'dan tamamen kaldırılmalıdır.

### 4.4 process_signals — Ana Döngü Girişi

Satır 519–635, 117 satır. Çağrı sırası:

```
1. Günlük reset (_daily_loss_stop, _symbol_loss_count)
2. HIZLI DÖNGÜ (her 10sn):
   2.1 _check_end_of_day()        # 17:45 EOD
   2.2 _manage_active_trades()    # trailing, 4 mod, volume spike
   2.3 _sync_positions()          # MT5 çapraz doğrulama
   2.4 Dashboard voting (her sembol)
3. L3 ikincil savunma çıkışı (baba._kill_switch_level >= 3)
4. SİNYAL DÖNGÜSÜ (M5 kapanışta):
   4.1 _is_new_m5_candle() gate
   4.2 strategies = regime.allowed_strategies
   4.3 _is_trading_allowed()
   4.4 Per-sembol loop:
       - active, netting_lock, hybrid, manual, is_symbol_killed, symbol_loss ≥ 2
       - _determine_direction → _generate_signal → _execute_signal
```

**Bulgu Y-1 (Savunma katmanı L3):** Satır 566–568 `baba._kill_switch_level >= 3` kontrolü bir iç özelliğe (`_kill_switch_level` — lider alt çizgi) sızıntı yapıyor. Encapsulation ihlali. BABA'da bu durumu döndüren public metod yok gibi. İleride BABA içinde isim değişirse silent break. **Öneri:** `baba.get_kill_switch_level() -> int` public metodu eklenmeli.

**Bulgu O-2 (Cycle sırası belgeyle tutarsız):** Docstring "Sıra: 1,2,3,4,5,6,7" diyor ama gerçek akış `2, 3, 7, ..., 6, 10` numaralandırmasıyla karışık. Yorum satırları #1, #2, #3, #7 (!), #6, #7 (!) diye atlıyor. Refactor artığı. Kod doğru çalışıyor ama okuma zorlaşıyor.

**Bulgu Y-2 (risk_multiplier sızıntısı):** `main.py:876` `self.ogul._risk_multiplier = risk_verdict.risk_multiplier` atıyor. OĞUL içinde bu alan **hiçbir yerde okunmuyor**. Grep doğrulaması gerekir ama `_execute_signal` `lot = 1.0` hardcode olduğu için pozisyon boyutlamaya etki etmiyor. Sonuç: main.py'daki "3 katmanlı pipeline" yorum bloğu (870–875) yanıltıcıdır; risk_multiplier aktarımı **tamamen fonksiyonsuzdur** şu anki test modunda. Bkz. C-1.

### 4.5 _is_new_m5_candle — Mum Kapanış Dedektörü

Satır 641–684, 44 satır.

**Mekanizma:** `self.current_top5[0]` örneklenir, `db.get_bars(sample, "M5", limit=1)` ile son mum timestamp'i alınır, son tetiklenen timestamp ile karşılaştırılır.

**Bulgu Y-3 (tek örnek sembol riski):** Sinyal döngüsü, sadece bir sembolün M5 verisinin güncelliğine bağlıdır. Eğer `current_top5[0]` veri boşluğu (WATCHED_SYMBOLS dahil tüm top5 sembollerde gap) yaşarsa tüm SİNYAL DÖNGÜSÜ iptal olur. Örnek sembol "kilitli" olursa diğer 4 sembol de kör kalır.

**Bulgu O-3 (state scoping):** `_last_m5_candle_ts` (okunan kısımdan çıkardığım field adı) per-Ogul instance tutulur, per-sembol değil. Farklı kontratların M5 kapanış zamanları küçük sapmalar gösterse bile (genelde göstermez — borsa dakik) ayrı takip edilmez. Teorik uç durum.

### 4.6 _calculate_voting — Oylama Mantığı

Satır 699–899, ~200 satır. 4 gösterge oylaması + yapı destek/direnç teyidi:

| Oy | Koşul | Ağırlık |
|----|-------|---------|
| RSI | RSI[-1] > 50 | 2.0 |
| EMA | EMA20 > EMA50 | 2.5 |
| TREND_PA | Price action trend structure | 2.5 |
| ATR | ATR genişliyor | 1.5 |
| VOLUME | Hacim > ortalama | 1.5 (LOW vol rejimde 0.80×) |

Volatilite rejimi (`_vol_regime`): percentile rank ile LOW/NORMAL/HIGH.

**Matematiksel notlar:**
- `RSI[-1] > 50` BUY oyu olarak sayılıyor — bu **neutral çizgi** geçişidir, momentum göstergesi değildir. 51 RSI ve 79 RSI aynı oyu verir. Bilgisi kaybedilir.
- ATR genişleme göstergesi tek başına yön **bilgisi vermez** (sadece volatilite); oylama sepetinde "buy" sayılması piyasa mantığıyla çelişir. Bulgu **O-4**.
- Ağırlıklar toplam 10.0 — bu bilinçli seçim ama belgelenmemiş. Tiebreaker "weighted diff ≥ 1.0" eşiği, bir göstergenin tüm ağırlığıyla değişmesini gerektirir — bu sağlam.

**Bulgu O-5 (ATR oyu yanlılığı):** ATR genişliyor → BUY oyu mantıksal olarak yanlış. ATR her iki yönde de patlayabilir. Doğru versiyon: "ATR genişliyor **ve** fiyat son N mumda artıyor" → BUY oyu. Mevcut haliyle, düşüş trendinde ATR genişleseydi BUY oyu verecek — gerçek ters yön.

### 4.7 _determine_direction — Yön Konsensüsü

Satır 905–990, 86 satır. 3 kaynak:

1. **Voting** (`_calculate_voting` → BUY/SELL/NOTR)
2. **H1 trend filtresi** — 70 H1 bar slope, `abs(slope_pct) > 0.001` (%0.1)
3. **SE3 Signal Engine** (`engine.utils.signal_engine.SignalEngine`)

Konsensüs kuralı: `if buy_v > sell_v and buy_v >= 1`

**Bulgu C-2 (KRİTİK — konsensüs gevşetilmiş):** 3 kaynaktan **en az 1** oy BUY ise ve majoryte BUY ise → BUY. Bu 1-of-3 eşiğidir. Önceki daha sıkı eşik kayda değer biçimde gevşetilmiş. Etki:

- 3 kaynak çoğunlukla "NOTR" derken 1 kaynak (örn. SE3) BUY derse → BUY
- Dengesiz çoğunluk (örn. Voting=NOTR, H1=NOTR, SE3=BUY) → BUY (1-0-2 → buy=1, sell=0, neutral=2, `1 > 0` ve `1 >= 1`)
- Gerçek 3-oy konsensüsü artık yok. Yalnızca tek olumlu sinyal + hiç ters sinyal olmama şartı

Piyasa mantığı açısından bu **tek gözetmenli karar** demektir — SE3 olası hatalı sinyal verirse diğer 2 filtre aktif blocker değil, pasif onaylayıcıdır. Çalışma prensipleri (§3.2 "birden fazla kaynak"a dayanan karar) ile çelişir.

**Öneri:** Eşik `buy_v >= 2` yapılmalı (2-of-3 gerçek çoğunluk). Bu değişiklik Kırmızı Bölge'de (C3 sınıfı) olup kullanıcı onayı gerekir.

**Bulgu O-6 (H1 slope eşiği çok küçük):** `abs(slope_pct) > 0.001` → %0.1 eğim "trend var" sayılıyor. 70 H1 bar ≈ 3 haftalık. 3 haftada %0.1 hareket noise seviyesindedir. Eşik %0.5 civarına çıkarılmalı.

### 4.8 _generate_signal — Sinyal İnşası

Satır 996–1227, 232 satır. Akış:

1. M5 veri (60 bar min), M15 veri (60 bar min)
2. **SE3 ana motor** (`SignalEngine`) — 9 kaynak, yapısal SL/TP
3. `direction` filtresi (yalnızca konsensüs yönünde olanlar geçer)
4. SE3 boşsa → Legacy strateji fallback (trend_follow/mean_reversion/breakout)
5. Strength'e göre sıralama
6. Confluence skoru → sürekli çarpan (score/100)
7. `CONFLUENCE_MIN_SCORE=20` taban filtresi
8. Rejim-strateji uyumluluk filtresi (SE3 bypass düzeltmesi)

**Bulgu Y-4 (SE3 + Legacy birlikte çalışıyor):** SE3 önce denenir, boşsa legacy. Ama her ikisinin de üretmesi durumunda hangisi kullanıldığını belirleyen kod açık değil (okunan bölüm). Bu belirsizlik strateji atfetme doğruluğunu etkileyebilir — bir trade "trend_follow" etiketiyle DB'ye yazılırken gerçekte SE3'ün sinyali olabilir.

**Bulgu O-7 (confluence çarpanı):** `strength * (conf_score/100)` → conf_score=20 iken strength %80 düşüyor (0.20 çarpanı). CONFLUENCE_MIN_SCORE=20 tabanında etki: eşiği geçen ama zayıf confluence'lı sinyaller neredeyse her zaman zayıf strength'le geçiyor. Eğer `_execute_signal` strength filtresi yoksa (hardcoded lot yüzünden etkisiz olsa da), canlı mod açıldığında bu düşük kaliteli işlem riski.

### 4.9 _check_trend_follow / _check_mean_reversion / _check_breakout

Satır 1231–1575, toplam ~345 satır.

**_check_trend_follow (1231–1335):**
- EMA20/50 cross + ADX histerezis (22–28 geçiş zonu, dışında sert onay)
- MACD 2-bar teyit
- SL: `swing_low - ATR` veya `price - 1.5*ATR` (fallback)
- TP: `price + 2.0*ATR`
- Strength: ADX(0–0.5) + MACD(0–0.3) + EMA_dist(0–0.2)

**Bulgu O-8 (trend_follow SL'si çok geniş olabilir):** Fallback `price - 1.5*ATR` derin swing_low yoksa devreye girer. 1.5×ATR SL, trend_follow için normaldir. TP=2.0×ATR → R:R = 1.33. **Matematiksel olarak uzun vadeli pozitif beklenti için ~%43 win rate gerektirir** — SE3 + filtreler bunu tutturuyor mu? Expectancy log'u `_r_multiple_history`'de tutuluyor (bulgu D-1: bu veri kullanıcıya raporlanmıyor).

**_check_mean_reversion (1339–1443):**
- RSI<20/>80 + BB touch + ADX range histerezis + Williams %R çift teyit
- SL: `BB_band ± 1.0*ATR`
- TP: `BB_mid + 0.3*ATR` (BUY için)

**Bulgu Y-5 (MR TP hesabı asimetrik):** BUY mean reversion'da TP=BB_mid + 0.3*ATR (orta bandın üstünde). SELL'de tersi. Sorun: **"mean reversion" mantığı ortaya dönüşü bekler.** Ortanın 0.3×ATR ötesine geçişe ajustman, yalnızca pozitif momentum varsa anlamlıdır. Mevcut kod bunu kontrol etmiyor — koşulsuz +0.3×ATR uzatıyor. Sonuç: fiyat tam BB_mid'e değip dönerse hedef kaçırılır, trailing yoksa pozisyon zarara geri dönebilir. **Öneri:** TP = BB_mid (kesin orta). Fazla kâr isteniyorsa trailing ile yakalansın.

**_check_breakout (1447–1575):**
- 20-bar high/low break
- Likidite sınıfına göre hacim çarpanı (A=1.5×, B=2.0×, C=3.0×)
- ATR expansion
- Range width: `range ≥ ATR*0.5` zorunlu
- SL: `last_close - 1.5*ATR`
- TP: `price + range_width`
- Squeeze sonrası breakout bonus +0.15 strength

**Bulgu O-9 (BO SL mesafesi):** `last_close - 1.5*ATR` yapısal değil. Doğrusu konsolidasyon low'u - 0.2×ATR buffer olmalıdır. Mevcut SL false breakout'ta çok geç kapatır.

### 4.10 _execute_signal — EMİR YÜRÜTME (KRİTİK)

Satır 1581–1826, 246 satır. En yoğun mantık burada.

**Akış:**
1. Paper mode kısa devre
2. **`lot = 1.0` HARDCODE** (satır 1619)
3. Trade oluştur (SIGNAL state)
4. BABA `check_correlation_limits` — korelasyon guard
5. PENDING state'e geç
6. `_is_trading_allowed(now)` ikinci katman
7. `_trade_lock` atomik concurrent check (`active_count < _max_concurrent`)
8. `account.free_margin < equity * 0.20` → cancel
9. `initial_risk = risk_pts * lot * contract_size` (R-Multiple için)
10. `mt5.send_order(... order_type="market")`
11. Başarı → FILLED state, ticket çıkar
12. `_update_fill_price` (MT5'ten gerçek dolum)
13. `_sltp.set_initial_sl(trade, signal.sl)` — plain STOP emri
14. SL başarısız → `mt5.close_position` + `baba.report_unprotected_position`
15. `baba.increment_daily_trade_count`
16. `db.insert_trade` + event

### BULGU C-1 (KRİTİK — LOT HARDCODE)

Satır 1618–1619:
```python
# Test süreci: sabit 1 lot (lot hesaplama docs/ogul_calculate_lot_backup.md'de)
lot = 1.0
```

**Etki:**
- BABA `calculate_position_size()` (baba.py:1054, 95 satır) **çağrılmıyor**. Bu fonksiyon:
  - Equity × risk_per_trade × regime_multiplier / (ATR × contract_size) formülünü uyguluyor
  - Graduated lot (1 zarar → ×0.75, 2 zarar → ×0.5, 3 zarar → 0)
  - Haftalık yarılama (`weekly_loss_halved`)
  - `max_position_size` cap
  - `vol_min` floor
- `_risk_multiplier` alanı set ediliyor ama **okunmuyor** (bulgu Y-2)
- `risk_per_trade_pct=0.01` (config) → %1 risk-per-trade kuralı **etkisiz**
- `max_lot_per_contract` config → **etkisiz**

**VİOP mantığı uyuşmazlığı:** 1 lot F_XU030 ≈ endeks değeri × 10 TL çarpan → endeks 10000 iken 100,000 TL notional. Ortalama 1.5×ATR SL'de ~1800 TL kayıp (single trade) → `max_daily_loss_pct: 1.8%` limiti **tek bir zarar ile tetiklenebilir** (100K equity'de). Beş eşzamanlı pozisyonda 5× risk.

**Matematiksel olarak:** Risk-per-trade hedef %1, BABA formülü 1 lot F_GARAN (düşük notional) ve 1 lot F_XU030 (yüksek notional) için **farklı** lot vermelidir. `lot=1.0` hardcode, yüksek volatiliteli/yüksek notional kontratlarda risk-per-trade'i %3–%5'e çıkarabilir.

**Piyasa mantığı uyuşmazlığı:** Trade başına sabit lot, portföy teorisinde **kaçınılması gereken** bir davranıştır. Kelly kriteri / fixed-fractional teorisinin tümü ihlal edilir.

**Mevcut yorum:** "Test süreci" — belgelenmiş bir geçici durum. Ancak canlı ortamda %15 drawdown'a yaklaşmak (log kanıtı: 18.78% drawdown zaten oluşmuş durumda — oturum raporu §3) bu hardcode'un fiili etkisini göstermektedir.

**Öneri:** `lot = self.baba.calculate_position_size(symbol, self.risk_params, atr_val, equity)` satırı geri eklenmeli. Test döneminin bittiği kullanıcı tarafından teyit edilmelidir. Rollback planı: `docs/ogul_calculate_lot_backup.md` mevcut.

### BULGU C-3 (Trading hours çift kontrolü faydalı ama timing farkı var)

Satır 1651 ikincil `_is_trading_allowed` kontrolü savunma derinliği olarak iyi. Ancak: birincil kontrol `process_signals:587` zamanında `now` hesaplanıyor, ikincil kontrol `_execute_signal:1651`'de **farklı** `now`. 10–200 ms arası fark. Eğer sinyal 17:44:59.950'de üretilirse birincil kontrol geçer, ikincil kontrol 17:45:00.100'de fail olur → trade CANCELLED. Bu istenen davranış. Sorun **yok**. Bulgu açıklama amaçlı.

### BULGU Y-6 (Margin check formülü)

Satır 1684:
```python
if equity <= 0 or free_margin < equity * self._margin_reserve_pct:
```

`margin_reserve_pct=0.20` → free_margin equity'nin %20'sinden az olmamalı. Doğru. Ama: **bu kontrol lot hesabından sonra değil, önce yapılıyor.** Lot=1.0 hardcode olduğu için şimdi anlamsız, ama canlı moda dönüldüğünde lot hesaplama `account.equity`'yi okuduktan sonra `calculate_position_size` çağrılmalı **ve sonra** margin yeterliliği kontrol edilmelidir. Mevcut sıra: margin_check → send_order. VİOP marjin gereksinimi kontrat fiyatıyla değişir; **send_order başarılı olup marjin yetersizliği sonradan görülebilir.** MT5 broker-side reddedecek ama gereksiz latency.

### BULGU C-4 (KRİTİK — SL Yerleştirilemediğinde Kapatılamama Senaryosu)

Satır 1762–1792:
```python
if sl_ok is False:
    close_result = self.mt5.close_position(position_ticket)
    if close_result is None:
        # Kapatma da başarısız — KRİTİK
        baba.report_unprotected_position(...)
```

**Sorun:** SL yerleştirilemedi **ve** close_position da None döndürdü → pozisyon açık + korumasız + BABA'ya raporlandı. Kod burada **return yapmıyor** — devamı satır 1794'ten devam ediyor, `baba.increment_daily_trade_count()` çağrılıyor, DB'ye FILLED olarak yazılıyor, event FILLED olarak logganıyor. Yani DB içinde korumasız pozisyon gayet FILLED görünüyor.

**Anayasa Kural 4** "Korumasız pozisyon YASAK" ile çelişir — kural var ama koruma eksik. `report_unprotected_position` muhtemelen sadece BABA'da bir uyarı event'i set ediyor, fiili kapatma yapmıyor.

**Öneri:** `else:` branch'in sonuna `return` veya raise-sentinel eklenmeli. Trade kaydı "CANCELLED + requires_manual" gibi bir state'te kaydedilmeli. Alternatif: retry loop (3 deneme) + panic mode.

### 4.11 _manage_active_trades + 4-Modlu Yönetim

Satır 2139–2286, 148 satır.

**Akış:**
1. Manuel ön-filtre (memory+marker+DB)
2. MT5 pozisyonları bir kere al, sembol bazlı indexle
3. **OLAY rejimi** → tüm FILLED kapat (orphan hariç)
4. **VOLATILE rejimi** → zarardakileri kapat, kârdakileri `_manage_position`'a gönder
5. Normal rejimlerde → her trade için `_manage_position` (universal) veya strateji bazlı (feature flag)

### BULGU Y-7 (VOLATILE rejim mantığı tartışmalı)

Satır 2199–2231. VOLATILE'da:
- **Zarardaki pozisyon** → hemen kapat (close_position)
- **Kârdaki pozisyon** → trailing ile yönet (korumak)

**Tartışma:** Bu "cut losses, let winners run" felsefesine uygundur. Ancak VOLATILE rejim tam da volatilite patladığında oluşur — bir pozisyonun "kârdaki" olup olmadığı yüksek frekansta değişir. 10 saniye içinde kâr→zarar→kâr dönebilir. Karar:
- **Artı:** Aleyhine volatilite patlarsa hemen çık
- **Eksi:** Volatilitenin geçici doğası ile çelişir; yanlış sinyalleme yüksek

Piyasa mantığı iki ucu da destekleyebilir. Matematiksel olarak **asimetrik kâr-zarar** üretir (zarardaki hemen gerçekleşir, kârdaki trailing'e bağlı). Expectancy negatife kayabilir.

**Alternatif:** VOLATILE'da tüm OĞUL pozisyonları trailing'i sıkılaştır (0.5×ATR), yeni pozisyon açmayı kapat, pozitif R-multiple bir eşiği geçenleri kapat (örn. R ≥ 1.0). Bu daha simetriktir.

Sınırdaki karar; mevcut kod hatalı değil ama kullanıcı hedefiyle örtüştüğü doğrulanmalı.

### BULGU Y-8 (OLAY rejiminde orphan'a dokunmuyor — DOĞRU)

Satır 2183–2184:
```python
if getattr(trade, "orphan", False):
    continue
```

Doğru kararlar: orphan = OĞUL'un değil. Manuel exclusion pre-filter ile yapılmış. Hibrit H-Engine'e ait, H-Engine kendi OLAY tepkisini verir. Bu kod doğrudur. Bulgu olumlu notasyon.

### 4.12 _manage_position — Evrensel 4-Mod

Satır 2292–2395, 104 satır.

**Modlar:** KORUMA → TREND → SAVUNMA → ÇIKIŞ

**Mod karar matrisi (`_determine_trade_mode`, 2397–2443):**
- Yapısal bozulma → ÇIKIŞ
- !breakeven_hit + profit ≥ ATR → breakeven çek, TREND
- !breakeven_hit → KORUMA
- breakeven_hit + momentum weakening → SAVUNMA
- breakeven_hit + momentum strong → TREND

### BULGU O-10 (Breakeven eşiği = 1×ATR — yüksek)

Satır 2420: `if profit_pts >= atr_val`. Bu "1×ATR kâr = breakeven çek" demektir. `BE_ATR_BY_CLASS` diye bir sabit tanımlanmış (satır 360 civarında), ama burada **kullanılmıyor** — tüm likidite sınıfları için sabit 1.0 ATR.

**Sorun:** Bulgu Y-5 (MR TP=BB_mid+0.3*ATR) ile birleşince, ATR'nin %100'ü kâr eşiği + BB_mid'in 0.3×ATR ötesi TP çok yakın. MR trade'de breakeven'a ulaşamadan TP'ye çarpabilir veya geri döndüğünde SL'ye çarpabilir. Trend_follow trade'de 1×ATR kâra ulaşmak mümkündür ama breakeven çekme gecikir.

**Öneri:** `BE_ATR_BY_CLASS.get(liq_class, 0.75)` gibi sınıfa bağlı eşik kullanılmalı (var ama bağlı değil).

### BULGU O-11 (Spread hesaplama yer tutucu)

Satır 2424–2427: Breakeven SL hesaplanırken spread alınıyor ama try/except fallback 0.0. VİOP'ta spread genelde 1-2 tick, ihmal edilebilir. Notasyon amaçlı.

### 4.13 _check_momentum_strength

Satır 2445–2498, 54 satır. 3 sinyal:

1. **RSI divergence** (price yeni high, RSI düşük high — 5 bar lookback)
2. **Volume azalma** (son 5 bar ort / önceki 5 bar ort < 0.7)
3. **Candle bodies küçülme** (son 3 bar avg body / 20 bar avg body < 0.5)

2+ uyarı → "weakening".

### BULGU O-12 (5-bar divergence çok kısa)

Standart RSI divergence analizi 14–28 bar swing'leri arar. 5-bar pencere gürültüye açıktır. M15 timeframe'de 5 bar = 75 dakika. Mikro dalgalanmalar "divergence" olarak yanlış raporlanabilir.

### 4.14 _is_structural_break

Satır 2500–2540, 41 satır.

Koşullar (breakeven_hit sonrası):
- BUY: swing_lows[-1] < swing_lows[-2] VEYA (close < EMA20 ve volume > avg)
- SELL: swing_highs[-1] > swing_highs[-2] VEYA (close > EMA20 ve volume > avg)

### BULGU O-13 (swing güvenilirliği)

`trend.swing_lows` `analyze_trend_structure` çıktısından. Swing tespiti `find_support_resistance` benzeri bir fonksiyonda. Swing tespit algoritması minimum 3 bar gerekir. Az bar'da false swing üretimi yapılabilir. Bu dolaylı olarak ÇIKIŞ tetiklemesi yapar — istenmeyen erken kapanış riski.

**Not:** `price_action.py` incelenmedi — bu bulgu katmanlı. İlerideki analiz için bırakıldı.

### 4.15 _check_volume_spike

Satır 2626–2678. Akış:
- `VOLUME_SPIKE_MULT` çarpanı üstü hacim patlaması
- Aleyhine + profit < -0.3×ATR → "close" döner
- Lehine + profit > 0 → log, çıkış trailing'e bırakılır

### BULGU O-14 (-0.3×ATR eşiği çok sıkı)

Satır 2658: `profit < -0.3 * atr_val`. ATR'nin %30'u kadar zarar eşiği çok dar. Normal mum açılış/kapanışı aralığındadır. Hacim patlamasıyla birleşince **erken çıkış** eğilimi yüksek. **Öneri:** `-0.8 × ATR` daha mantıklı (SL öncesi "panik çıkış").

### 4.16 _check_end_of_day + _verify_eod_closure

Satır 1954–2133.

`_check_end_of_day`:
- 17:45 sonrası tüm FILLED pozisyonları kapat
- Orphan hariç
- Stop Limit SL emirlerini önce iptal et
- Sonra pozisyon kapat
- Event "EOD_CLOSE" kaydet
- `_verify_eod_closure` ikincil doğrulama

`_verify_eod_closure`:
- MT5'te kalan pozisyonları al
- Hibrit, manuel, orphan ticket setlerinden hariç tut
- Kalanları 5 deneme × 1 saniye aralıkla kapatmaya çalış
- Başarısızları "KRITIK" log + "EOD_CLOSE_FAILED" event + event_bus emit

### BULGU C-5 (EOD retry cycle'ı bloke ediyor)

5 attempt × 1 saniye × N ticket = O(5N) saniye blocking call. Normal 2–3 pozisyonda 10–15 saniye. **Main loop'un normal cycle süresi 10 saniye.** EOD doğrulama sırasında cycle aşılır (heartbeat, BABA, H-Engine bekler).

**Sorun:** Cycle aşımı → `_heartbeat_mt5` gecikebilir → watchdog false alarm. Normalde EOD sonrası cycle'lar az kritik (piyasa kapalı) ama teknik olarak bloke edicidir.

**Öneri:** EOD'da cycle interval'ı geçici olarak artır veya async kapatma kullan.

### 4.17 _sync_positions

Satır 2905–2940. Her cycle MT5'i sorgular, active_trades ile karşılaştırır:
- SL triggered mi? (`_sltp.check_sl_triggered`)
- Symbol kalmadıysa → `_handle_closed_trade(external_close)`

### BULGU D-2 (Double-close riski)

`check_sl_triggered` pending emir kaybolduğunda True döner. Ardından `if symbol not in open_symbols` kontrolü — eğer SL tetikledi ve MT5 pozisyon kapandıysa, her iki koşul da True olur. `_handle_closed_trade` bir kere çağrılır (if/if-else mantığı değil). Sorun yok ama log çizgileri iki mesaj basabilir. Kozmetik.

### 4.18 _handle_closed_trade

Satır 2941–3097, 157 satır. Akış:
1. Trade state=CLOSED
2. `_sltp.cancel_orders`
3. `mt5.get_tick` ile exit_price
4. PnL fallback hesap (fiyat farkı × lot × contract_size)
5. `mt5.get_deal_summary` 3 kez retry × 0.8s (PnL override)
6. DB update_trade
7. insert_event "TRADE_CLOSE"
8. event_bus emit
9. Per-sembol ardışık zarar sayacı
10. R-Multiple hesap + expectancy
11. `_pyramid_last_add.pop`
12. active_trades.pop

### BULGU O-15 (get_deal_summary retry bloke eder)

Satır 2997–3002: 3 × 0.8s = 2.4 saniye worst case blocking. 5 pozisyon aynı anda kapanırsa 12 saniye main-loop bloklaması. Nadir ama gerçekçi (rejim değişimi OLAY).

**Öneri:** Deal summary async alınmalı veya ilk cycle skip edilip sonraki cycle'a ertelenmeli.

### BULGU C-6 (PnL sıralama — deal_summary sonrası güncelleme)

Satır 2982–3006:
1. Önce fallback PnL hesaplanıyor (`(exit - entry) * volume * contract_size`)
2. `trade.pnl` set ediliyor
3. `deal_summary` alınıyor, başarılıysa **override**
4. DB update satır 3013 `trade.pnl` yazıyor (override sonrası)

**Sorun:** Fallback PnL **commission ve swap'ı dahil etmez**. deal_summary başarısız olursa (3 retry sonrasında) DB'ye commission/swap=0 yazılır ama fiyat farkı tam PnL olarak yansır. Gerçek brüt PnL'den komisyon düşmemiş olur. Canlı ortamda küçük ama **kümülatif** muhasebe hatası.

**Öneri:** Fallback PnL sadece log olarak tutulmalı, DB yalnızca `deal_summary` başarılıysa PnL yazmalı. Deal summary gelmediyse trade "pending_reconciliation" state'e alınmalı ve cycle'larda yeniden denenmeli.

### 4.19 restore_active_trades

Satır 3103–3333, 231 satır. Engine restart'ta açık pozisyonları MT5+DB çapraz eşleyerek geri yükler.

**Pozitif bulgular (doğru davranış):**
- 3-katmanlı manuel guard (memory, marker, DB)
- 2-katmanlı hibrit guard (memory, DB)
- DB eşleşmesi yoksa `trade.orphan = True` işaretle, active_trades'te tut (duplicate emir engeli) — CLAUDE.md §4.4'teki orphan guard felsefesi ile tutarlı
- Post-restore DB çapraz doğrulama (race condition telafisi)
- `_sltp.restore_sl_order` — Stop emir yeniden oluşturma

### BULGU Y-9 (Restore orphan count artırmadan tutuyor ama loglama)

Satır 3295–3305: DB eşleşmesi yok → `orphan_count += 1`, `active_trades` içinde tutuluyor. Log "KRİTİK" seviyesinde değil "warning". Operasyonel gözlemcilik için CRITICAL olmalı — yetim pozisyon operatörün dikkatini çekmeli. **Öneri:** `logger.critical` + event_bus emit.

---

## 5. OĞUL ↔ BABA Etkileşimi

### 5.1 Köprü Noktaları

| Çağrı | Konum (OĞUL) | Görev |
|-------|--------------|-------|
| `baba.is_symbol_killed(symbol)` | process_signals:615 | Per-sembol L1 kill check |
| `baba._kill_switch_level >= 3` | process_signals:566 | L3 kontrolü (encapsulation sızıntısı — Y-1) |
| `baba.check_correlation_limits()` | _execute_signal:1637 | Korelasyon guard |
| `baba.increment_daily_trade_count()` | _execute_signal:1796 | Günlük sayaç |
| `baba.report_unprotected_position()` | _execute_signal:1789 | Kritik uyarı |
| `baba.calculate_position_size()` | **ÇAĞIRIMAYOR** — lot=1.0 hardcode | **Bulgu C-1** |

### 5.2 BABA → OĞUL Çağrılar

| BABA tarafı | OĞUL tarafı |
|-------------|-------------|
| `_close_ogul_and_hybrid` → `self.baba.ogul = self.ogul` wire ile `self.ogul.active_trades` okur | OĞUL active_trades dict |
| `_close_ogul_and_hybrid` → FILLED + !orphan + !manual süzgeç | direct dict iteration |

**Bulgu D-3:** `main.py:161` `self.baba.ogul = self.ogul` — circular reference. Her iki motor da birbirine erişebilir. Memory leak riski yok (weakref gerek yok — uygulama ömrü boyunca yaşar) ama unit test'te mock zorlaşır.

### 5.3 Sorumluluk Matrisi (Refactor Sonrası)

| Sorumluluk | Sahip | Kanıt |
|------------|-------|-------|
| Günlük kayıp durdurma | BABA (`_check_monthly_loss`, `check_drawdown_limits`, `_activate_kill_switch L2`) | CLAUDE.md Kural 10 |
| Aylık DD | BABA | baba.py `_check_monthly_loss` |
| Hard drawdown %15 L3 | BABA | CLAUDE.md Kural 6 |
| Rejim algılama | BABA | `baba.run_cycle` → `detect_regime` |
| Lot boyutlama | **BABA (fiili olarak UYGULANMIYOR)** | calculate_position_size var ama çağrılmıyor — C-1 |
| Korelasyon | BABA | check_correlation_limits |
| Sinyal üretimi | OĞUL | _generate_signal + SE3 |
| Emir gönderimi | OĞUL | _execute_signal |
| State machine | OĞUL | SIGNAL/PENDING/SENT/FILLED/CLOSED |
| SL koruması (plain STOP) | OĞUL (OgulSLTP) | _sltp.set_initial_sl |
| Trailing stop | OĞUL (4 mod) | _manage_position |
| EOD kapanış | OĞUL | _check_end_of_day |
| EOD hayalet temizliği | OĞUL | _verify_eod_closure |
| Orphan takibi | OĞUL | restore_active_trades |
| Per-sembol ardışık kayıp | OĞUL | _symbol_loss_count |

**Değerlendirme:** Refactor sonrası sorumluluk ayrımı **mimari olarak** temiz. Ancak "Lot boyutlama = BABA" satırı gerçekte uygulanmamakta (C-1).

---

## 6. OĞUL ↔ MT5 Bridge Etkileşimi (GCM VİOP Özgül)

### 6.1 Kullanılan Bridge Fonksiyonları

| Fonksiyon | Kullanım yeri | Not |
|-----------|---------------|-----|
| `get_bars(symbol, tf, limit)` | _is_new_m5_candle, _calculate_voting, _manage_position, vb. | DB'den (mt5 → cache → db) |
| `get_positions()` | _update_fill_price, _manage_active_trades, _verify_eod_closure, _sync_positions, restore_active_trades | Her cycle en az 2 kez |
| `get_tick(symbol)` | _determine_trade_mode (spread), _handle_closed_trade | Latency low |
| `get_symbol_info(symbol)` | contract_size, vol_min, vol_step | R-Multiple, PnL |
| `get_account_info()` | _execute_signal | equity, free_margin |
| `send_order(market)` | _execute_signal | 2-aşamalı (emir + SL/TP retry) |
| `close_position(ticket)` | 4+ yerde | Retry handled externally |
| `send_stop` (via OgulSLTP) | _sltp.set_initial_sl | Plain STOP emir |
| `modify_pending_order` (via OgulSLTP) | _sltp.update_trailing_sl | 3x retry then cancel+resend |
| `cancel_pending_order` (via OgulSLTP) | _sltp.cancel_orders, _check_end_of_day | Stop emir iptal |
| `get_pending_orders` | _sltp.update_trailing_sl | |
| `get_deal_summary(ticket)` | _handle_closed_trade | Retry 3×0.8s — C-6 |

### 6.2 GCM VİOP Uyum Noktaları (Doğru Davranışlar)

1. **Netting mode handling:** `_update_fill_price` sembol bazlı pozisyon arar (ticket merge sonrası yeni ticket alır). Doğru.
2. **`_sync_positions` ticket değişimi:** satır 2251–2253 `pos_ticket != trade.ticket` ise trade.ticket güncellenir. Netting merge doğru.
3. **`TRADE_ACTION_SLTP` bypass:** `OgulSLTP` tüm SL'yi plain STOP pending emir ile yerleştirir (GCM VİOP `retcode=10035` workaround). Doğru.
4. **`_manage_active_trades` volume senkronizasyonu:** `abs(pos_vol - trade.volume) > 1e-8` netting sonrası lot değişimini yakalar. Doğru.

### 6.3 GCM VİOP Uyum Sorunları

**Bulgu Y-10 (comment alanı):** Trade gönderiminde `comment=f"OGUL_SL_{trade.ticket}"` (OgulSLTP:74) — GCM VİOP comment alanı 31 karakterle sınırlı. `OGUL_SL_` (8) + ticket (9 basamak max) = 17 karakter → güvenli. Ama `OGUL_SL_2147483647` = 18 karakter → güvenli. Ama diğer yerlerde comment'lerde daha uzun string kullanılıyorsa risk var. _execute_signal'da comment parametresi set edilmiyor → default boşluk. OK.

**Bulgu O-16 (retcode=10027 AutoTrading disabled):** Oturum raporu §3'te kanıtlanan bu retcode, broker-taraflı ayar. OĞUL kod tarafında `close_position` başarısızlığı "external error" olarak işlenir, retry mantığı yok (tek deneme). **Öneri:** `close_position` return None ise 3× retry eklemek. Mevcut kod tek denemede vazgeçer.

**Bulgu D-4 (get_pending_orders symbol filter):** OgulSLTP `get_pending_orders(symbol)` bazı broker'larda filter'lanmadan tüm pending'leri döndürebilir. Bridge implementasyonu burada sessiz — okunamamış. Mevcut kod güvenli tarafı seçiyor (filter sonucu). Belirsizlik notasyon.

---

## 7. OĞUL ↔ H-Engine Etkileşimi

### 7.1 Sınırlar

- **Hibrit sembol dokunmazlığı:** `process_signals:605–607` OĞUL hibrit sembolleri skip eder
- **Hibrit ticket dokunmazlığı:** `_verify_eod_closure:2067` hibrit pozisyonları EOD hariç tutar
- **Restore:** `restore_active_trades:3151-3178` hybrid_tickets + hybrid_symbols + DB hybrid_positions üçlü check
- **Position manager:** `_manage_position:2322` `if trade.ticket in h_engine.hybrid_positions: return` — savunma ağı

### Bulgu Y-11 (Hibrit devir yok)

OĞUL'dan H-Engine'e pozisyon **devretme** mekanizması yok. Sadece exclusion-based ayrım. Kullanıcı pozisyonu hibrit'e almak istediğinde (frontend UI üzerinden) H-Engine pozisyonu kendisi üstlenir. Bu OĞUL'un görevi değil — **doğru ayrım**. Ama:

**Gerçek risk:** Devir sırasında race condition — OĞUL cycle N'de pozisyonu yönettiği sırada kullanıcı cycle N+1'de hibrit'e alır. OĞUL cycle N'de bu değişimi görmedi. Bir cycle boyunca iki motor da pozisyonu "yönetebilir". Net pratik etki: 10 saniye max. Tolerable.

---

## 8. OĞUL ↔ Manuel Motor Etkileşimi

### 8.1 Exclusion Zinciri (ÇOK KATMANLI)

1. **Pre-filter** (`_manage_active_trades:2154-2162`): memory+marker+DB üçlü
2. **Sinyal döngüsü skip** (`process_signals:610-612`)
3. **Pozisyon yönetimi pop** (`_manage_position:2314-2320`): memory+ticket çift kontrol
4. **EOD doğrulama exclusion** (`_verify_eod_closure:2046-2049`)
5. **Restore üçlü guard** (manuel tickets + manuel symbols + DB strategy="manual")
6. **Post-restore doğrulama** (`restore_active_trades:3310-3327`)

### Bulgu POZİTİF (iyi mühendislik)

6 katmanlı exclusion zinciri manuel/otomatik karışımını güvenle önler. Refactor #149 sonrası bu katmanlar korunmuş, risk yok.

---

## 9. OĞUL ↔ ÜSTAT Etkileşimi

### 9.1 Kullanım

- `_get_ustat_param(strategy, key, default)` (satır ~490'lar) — strateji parametrelerini ÜSTAT'tan al
- `_get_contract_profile(symbol)` — kontrat profilini al
- `_get_ustat_strategy_hint(symbol)` — öneri al
- `Top5Selector._ustat = self.ustat` — Top 5 seçimine strateji puanı girer

**Bulgu D-5:** `_get_ustat_param` `self.ustat` None ise default döner. Graceful. Ama bu bir **test durumu** değil, engine başlatma sırası gereği geçici olarak None olabilir (lifespan sırası). Constructor sırasında atanıyor → eğer `main.py:133 self.ogul.ustat = self.ustat` ile çakışırsa cycle sırasında fark eder. Düşük risk.

---

## 10. Piyasa Mantığı Çelişkileri — Özet Tablo

| # | Yer | Çelişki | Şiddet |
|---|-----|---------|--------|
| 1 | _execute_signal:1619 | lot=1.0 hardcode → risk-per-trade kuralı fiili devre dışı | **C-1** |
| 2 | _determine_direction:985 | 1-of-3 konsensüs (önceki 2/3'ten gevşetilmiş) | **C-2** |
| 3 | _calculate_voting (ATR oyu) | ATR genişlemesi her zaman BUY oyu — yön bilgisi yok | O-4/O-5 |
| 4 | _check_mean_reversion TP | BB_mid + 0.3×ATR (orta üstü) MR mantığıyla çelişir | Y-5 |
| 5 | _determine_trade_mode | Breakeven eşiği sabit 1×ATR — BE_ATR_BY_CLASS kullanılmıyor | O-10 |
| 6 | _check_volume_spike | -0.3×ATR aleyhe eşik çok sıkı — erken çıkış | O-14 |
| 7 | VOLATILE yönetim | Kârdaki koru zarardaki kes — volatilite geçiciliği ile çelişir | Y-7 |
| 8 | _check_breakout SL | last_close - 1.5×ATR yapısal değil | O-9 |
| 9 | _check_momentum_strength | 5-bar divergence — gürültü seviyesi | O-12 |
| 10 | H1 slope eşiği | %0.1 eğim noise düzeyinde | O-6 |
| 11 | trend_follow SL fallback | 1.5×ATR düz uzaklık (swing yoksa) | O-8 |

---

## 11. Matematiksel Hatalar — Özet Tablo

| # | Yer | Hata | Şiddet |
|---|-----|------|--------|
| 1 | _handle_closed_trade PnL sıralama | Fallback PnL + commission=0 DB'ye yazılabiliyor | **C-6** |
| 2 | _execute_signal SL fail kapatılamadı | Return yok, FILLED state DB'ye yazılıyor | **C-4** |
| 3 | _execute_signal margin check sıra | Lot=1.0 olduğu için etkisiz ama canlı modda broker-side reddedebilir | Y-6 |
| 4 | R-Multiple hesabı | `initial_risk = risk_pts * lot * contract_size` doğru ama `R = pnl / initial_risk` commission hariç | Y-12 (alt) |
| 5 | _verify_eod_closure retry | 5×1s×N ticket blocking main loop | **C-5** |
| 6 | _handle_closed_trade deal_summary | 3×0.8s blocking | O-15 |

---

## 12. Görev Çakışmaları — Özet Tablo

| # | Çakışma | Durum |
|---|---------|-------|
| 1 | Günlük kayıp: OĞUL vs BABA | ✅ Çözüldü (#149) |
| 2 | Aylık DD: OĞUL vs BABA | ✅ Çözüldü (#149) |
| 3 | Yatay piyasa kapama: OĞUL vs BABA | ✅ Çözüldü (#149) |
| 4 | Spread guard: OĞUL _check_advanced_risk_rules | ✅ Silindi ama BABA'da yedeği yok — **Y-13 (alt)** |
| 5 | Lot hesabı: OĞUL calculate_lot vs BABA calculate_position_size | ⚠️ Lot=1.0 hardcode — **C-1** |
| 6 | Rejim değişimi kapama: _manage_active_trades OLAY/VOLATILE | ✅ Ayrı alan, baba.detect_regime girdi |
| 7 | EOD kapama: manuel motor vs OĞUL | ✅ exclusion zinciri sağlam |
| 8 | Hibrit sembol: OĞUL vs H-Engine | ✅ exclusion zinciri sağlam |
| 9 | SL koruma: mt5_bridge TRADE_ACTION_SLTP vs OgulSLTP plain STOP | ✅ GCM workaround belgelenmiş |

---

## 13. Bulgu Özet Tablosu

### Kritik (C) — 6 adet

| ID | Açıklama | Etkilenen | Eylem önceliği |
|----|----------|-----------|----------------|
| **C-1** | `lot = 1.0` hardcode, BABA.calculate_position_size çağrılmıyor | _execute_signal:1619 | Acil — canlı modda ÖLÜMCÜL |
| **C-2** | Yön konsensüsü 1-of-3'e gevşetilmiş | _determine_direction:985 | Yüksek — yanlış sinyal riski |
| **C-3** | _is_trading_allowed ikincil kontrol (FALSE POSITIVE) | _execute_signal:1651 | **Yok** — kasıtlı savunma |
| **C-4** | SL fail + close fail → FILLED DB'ye yazılıyor | _execute_signal:1762-1792 | Yüksek — anayasa kural 4 ihlal |
| **C-5** | _verify_eod_closure blocking retry | _verify_eod_closure:2088 | Orta — EOD'a özel, piyasa kapalı |
| **C-6** | Fallback PnL commission hariç DB'ye yazılıyor | _handle_closed_trade:2982 | Orta — kümülatif muhasebe hatası |

### Yüksek (Y) — 9 adet

Y-1, Y-2, Y-3, Y-4, Y-5, Y-6, Y-7, Y-9, Y-10, Y-11 (tabloda belirtildi). Y-12, Y-13 alt bulgu.

### Orta (O) — 15 adet

Tabloda belirtildi.

### Düşük (D) — 7 adet

D-1: R-Multiple veri kullanıcıya raporlanmıyor (Dashboard eksik)
D-2: Double-close log kozmetik
D-3: Circular reference (baba.ogul, ogul.baba) — unit test zorluğu
D-4: get_pending_orders symbol filter belirsizliği
D-5: self.ustat None olabilirlik (lifespan sırası)
D-6: Top5Selector'ın `last_refresh` property'si (düşük kullanım)
D-7: Ölü state `_monthly_start_equity` vb. (O-1 ile bağlantılı)

---

## 14. Sonuç ve Öneriler

### 14.1 Genel Değerlendirme

OĞUL mimari olarak sağlam bir trading motorudur. Refactor #149 sorumluluk ayrımını büyük ölçüde tamamlamıştır. Manuel/hibrit exclusion katmanları, orphan guard, restore logic, atomik concurrent check, netting-lock ve plain-STOP SL yerleştirme gibi kritik emniyet mekanizmaları mevcut ve doğru çalışmaktadır.

Ancak **"verilen görevleri tam kapasitede yapabilecek mi?"** sorusuna cevap: **Mevcut haliyle HAYIR.** Gerekçe:

1. **C-1 (lot hardcode)** tek başına canlı modu yüksek riske sokar. BABA'nın tüm fixed-fractional mantığı ve graduated-lot telafisi bypass edilmektedir.
2. **C-2 (1-of-3 konsensüs)** yanlış sinyal oranını artırır.
3. **C-4 (SL fail + close fail)** Anayasa Kural 4 ihlaline açık kapı bırakır.
4. **C-6 (PnL commission sıralama)** muhasebe sadakatini bozar.

Bu 4 kritik bulgu giderilirse OĞUL görev sınırları içinde **güvenilir bir sinyal ve emir yürütme motoru** olabilir.

### 14.2 Önerilen Eylem Planı (Öncelik Sırası)

**P0 — Anında (Barış zamanı):**
1. **C-1 düzeltme:** `lot = 1.0` satırı `lot = self.baba.calculate_position_size(...)` ile değiştir. Backup: `docs/ogul_calculate_lot_backup.md`. Sınıf C4 (Siyah Kapı fonksiyon mantık değişikliği). Kullanıcı onayı + çift doğrulama zorunlu.
2. **C-4 düzeltme:** `close_result is None` branch'ına `return` ekle, trade state'i `CANCELLED_UNPROTECTED` gibi yeni bir sentinel'e set et, DB'ye FILLED yerine bu state yaz.
3. **C-6 düzeltme:** Fallback PnL yalnızca log'a yazılsın, DB update yalnızca `deal_summary is not None` blok'unda yapılsın. `pending_reconciliation` state'i eklenebilir.

**P1 — Yakın dönem:**
4. **C-2 düzeltme:** `buy_v >= 2` yap. Sınıf C3.
5. **Y-2 düzeltme:** `_risk_multiplier` ya kullan ya da main.py atamasını kaldır (tutarsızlık).
6. **O-4/O-5:** ATR oyu yön bilgisiyle birleştirilsin (ATR + son 3 mum pozitif → BUY oyu).

**P2 — Orta dönem:**
7. **Y-5:** MR TP hedefini BB_mid'e indir, trailing ile kâr büyüt.
8. **O-10:** Breakeven eşiği `BE_ATR_BY_CLASS` ile bağlansın.
9. **C-5:** EOD retry non-blocking yapılsın veya cycle interval geçici artırılsın.
10. **Y-1:** `baba.get_kill_switch_level()` public API eklensin.
11. **Y-4:** SE3 vs Legacy sinyal önceliği net belgelensin ve DB'ye doğru strateji yazılsın.

**P3 — Temizlik:**
12. **O-1:** Ölü `_daily_loss_stop` state kaldırılsın, `health.py:133` BABA'ya yönlendirilsin.
13. **Y-9:** Orphan log seviyesi CRITICAL + event_bus emit.
14. **Y-13 alt:** Spread guard BABA'da reimplement edilsin (OĞUL'dan silindi ama BABA'da yedek yok).

### 14.3 Kullanıcıya Özet

OĞUL'un omurgası güçlüdür. Mimari ayrım #149 ile doğru yere geldi. Ancak mevcut **test modu kilitleri** (özellikle `lot=1.0`) üretim ortamında tutmak güvensizdir. Önerim: P0 düzeltmelerinden sonra canlı ortama tekrar alın. P0'sız canlı çalıştırma, **CLAUDE.md §3.2 finansal risk uyarısıyla doğrudan çelişir** — "her hata kullanıcıya finansal zarar olarak yansır".

Bu rapor salt bir denetimdir. Tek satır kod değiştirilmemiştir. Her düzeltme için ayrı plan + kullanıcı onayı gerekmektedir (CLAUDE.md §3.3).

---

**Rapor Sonu**
**Satır sayısı (yaklaşık):** 700
**Denetlenen kod satırı:** ~3400 (ogul.py) + ~150 (ogul_sltp.py) + ~100 (baba.py kilit fonksiyonlar) + ~100 (main.py cycle)
**Kanıt türü:** Tüm bulgular satır numarasıyla referanslanmıştır
**Çalışma prensibi uyumu:** CLAUDE.md §3 (kanıta dayalı, varsayım yok) ✅
