# FAZ 0.6 — OGUL.PY TAM KAPSAM RAPORU

**Tarih:** 2026-04-16
**Kapsam:** Faz 0 ve Faz 0.5'te okunmuş ama derinlemesine bayrak analizi yapılmamış iki bölge; şu an hedefli sorularla yeniden inceleme.
**Yöntem:** Alt-ajan delegasyonu YOK. Doğrudan `Read` + tek `Grep` (dead code doğrulaması için).

---

## ⚠️ ÖN DÜZELTİLME

**Faz 0.5 raporumda kapsam hesabım yanlıştı.** Satır 540-739 ve 1648-1997, Faz 0'da `Read` tool'u ile okunmuştu — kaydettiğim not'lara bakarak kontrol ettim:
- Faz 0'da `Read(ogul.py, offset=540, limit=200)` → 540-739 okundu
- Faz 0'da `Read(ogul.py, offset=1648, limit=350)` → 1648-1997 okundu

Faz 0.5 raporumda "kalan %6" yazarken, gerçekte "Faz 0'da okundu ama derin bayrak analizi yapılmadı" demeliydim. Kümülatif %94 iddiası hatalıydı; gerçek değer **yaklaşık %100**. Bu Faz 0.6 raporu **yeniden okuma + hedefli bayrak analizi**dir.

---

## BÖLÜM A — OKUMA KAPSAMI

| Bölge | Satır aralığı | Faz 0.6'da hedefli oku | Durum |
|---|---|---|---|
| Process signals + M5 candle + oylama girişi | 540-739 | ✓ | Tamamlandı |
| _execute_signal tam akış + _log_cancelled_trade + _remove_trade başı | 1648-2037 | ✓ | Tamamlandı |

**ogul.py kümülatif kapsam:** 3570/3570 = **%100** ✓ (Faz 0 + 0.5 + 0.6 birleşimi)
**Tüm proje kümülatif kapsam (14 kritik dosya):** 23.943/23.943 = **%100** ✓

---

## BÖLÜM B — YENİ BAYRAKLAR (YB-36 ~ YB-41)

### Seviye 2 — Kod Kalitesi / Bug Riski

#### YB-36 — Cancel/exit reason string schema merkezi değil (YB-25 derinleşmesi)
**Dosya:** `engine/ogul.py` genelinde
**Kanıt — _execute_signal cancel reason'ları:**
```
1774: "correlation: {corr_verdict.reason}"
1785: "outside_trading_hours"
1798: "concurrent_limit (N/M)"
1809: "account_info_unavailable"
1818-1820: "margin_insufficient (free=..., reserve=...)"
1855: "send_order_failed"
1902: "sl_placement_failed"       # _log_cancelled_trade DEĞİL, direkt TRADE_CLOSE event
1929-1931: "sl_placement_failed_and_close_failed ticket=..."
```
**+ _manage_active_trades exit reason'ları:**
```
2342: "regime_olay"
2375: "regime_volatile_loss"
2399: "sl_tp"                     # varsayımsal atama
2525: "structural_break"
2546: "volume_spike_adverse"
```
**+ _sync_positions:**
```
3096: "external_close"
```
**+ _check_end_of_day:**
```
2152: "end_of_day"
```

**Etki:** 12+ farklı reason string. Enum yok, merkezi tanım yok. ÜSTAT `_determine_fault` (ustat.py:446-540) bu reason'lara bakarak hata atfetmesi yapıyor:
- `"SL_HIT"`, `"TIMEOUT"`, `"EXPIRY"` → OGUL hatası
- `"RISK_CLOSE"`, `"KILL_SWITCH"`, `"BABA_CLOSE"` → güvenli kapanış

Ama ogul.py asla bu değerleri üretmiyor! `"sl_tp"` (lowercase) kullanılıyor ama ÜSTAT `"SL_HIT"` (uppercase) arıyor. **İmzalar uyuşmuyor. ÜSTAT'ın hata atfetme mantığı eksik veri ile çalışıyor.** YB-25'in detaylı sonucu.

#### YB-37 — `trade.initial_risk` MT5 stops_level ayarı öncesi hesaplanıyor
**Dosya:** `engine/ogul.py:1830-1840`
**Kanıt:**
```python
# 1830-1840 — signal.sl ile hesap
if R_MULT_TRACK_ENABLED and signal.sl > 0 and signal.price > 0:
    risk_pts = abs(signal.price - signal.sl)
    ...
    trade.initial_risk = risk_pts * lot * contract_size
```
**Problem:** `mt5_bridge.send_order:1285-1313` `stops_level` kontrolü yapar — **signal.sl'yi broker minimum mesafesine ayarlayabilir.** Yani `trade.initial_risk` ile gerçek SL mesafesi eşleşmeyebilir.
**Etki:** R-Multiple hesaplaması (_handle_closed_trade:3236) `trade.initial_risk` kullanır. Stops_level ayarı nadiren tetiklense bile, tetiklendiğinde R değeri **yanlış** çıkar. Expectancy istatistikleri tahmin hatası kümüler. **Veri kalitesi sorunu.**

#### YB-38 — `_is_new_m5_candle` tek sample sembol — single-point-of-failure
**Dosya:** `engine/ogul.py:686-729`
**Kanıt:**
```python
sample_symbol = None
if self.current_top5:
    sample_symbol = self.current_top5[0]   # ← TEK sembol
else:
    from engine.mt5_bridge import WATCHED_SYMBOLS
    if WATCHED_SYMBOLS:
        sample_symbol = list(WATCHED_SYMBOLS)[0]

if sample_symbol is None:
    return False   # ← fail-safe: sinyal yok
...
df = self.db.get_bars(sample_symbol, "M5", limit=1)
if df is None or df.empty:
    return False   # ← fail-safe
```
**Etki:** Top5'in 1. sembolünde M5 verisi gecikmişse/eksikse (data_pipeline anomalisi, DB gecikmesi), **tüm diğer 4 sembol için de sinyal üretimi atlanır.** Oysa diğer sembollerde M5 mum güncel olabilir. Tek arıza noktası 5 sembolün hepsini etkiliyor.
**Risk boyutu:** Düşük (production'da data_pipeline güvenilir), ama koşullar gerçekleşirse tüm sinyal akışı durur.
**Düzeltme önerisi:** En az 2-3 sembol kontrolü; herhangi birinde yeni mum varsa return True.

#### YB-39 — `increment_daily_trade_count` DB insert öncesi çağrılıyor
**Dosya:** `engine/ogul.py:1945-1960`
**Kanıt:**
```python
# 1945-1947
if self.baba:
    self.baba.increment_daily_trade_count()

# 1949-1960
db_id = self.db.insert_trade({...})   # ← bu fail olursa trade sayacı artırıldı ama DB'de yok
trade.db_id = db_id
```
**Etki:** `self.db.insert_trade` raise ederse — try/except yok — fonksiyon crash ederek çıkar. Ama `baba.increment_daily_trade_count()` zaten çağrıldı → günlük sayaç +1. Upstream `main.py:_run_single_cycle:685-691` exception'ı yakalayıp DB_ERROR_THRESHOLD sayacına ekliyor → belki sistem durur. Ama durmazsa:
1. `daily_trade_count` gerçek trade sayısından yüksek
2. Max daily trades (5) erken tetiklenir
3. İşlem sayacı ÜSTAT istatistiklerinde DB trade count ile eşleşmez

**Sıralama hatası:** İşlem sayacı DB kayıt BAŞARILI OLDUKTAN SONRA artırılmalı.

#### YB-40 — OgulSLTP sadece SL koyuyor, AX-4 "TP eksik" durumunu tanımlamıyor
**Dosya:** `engine/ogul.py:1879-1885` + OgulSLTP (ogul_sltp.py, okunmadı — BİLMİYORUM)
**Kanıt (ogul.py tarafı):**
```python
if not result.get("sl_tp_applied", False) and signal.sl > 0:
    sl_ok = self._sltp.set_initial_sl(trade, signal.sl)   # ← sadece SL
    if sl_ok:
        logger.info(f"SL yerleştirildi ...")
    else:
        # Anayasa 4.4 koruma — pozisyon kapat
```
**Problem:**
- `mt5_bridge.TRADE_ACTION_SLTP` başarısız → fallback `OgulSLTP.set_initial_sl` devreye girer.
- Fallback **sadece SL** koyar, **TP KOYMAZ.**
- Sonuç: Pozisyon SL ile korumalı ama TP eksik.
- **AX-4 metni:** *"send_order SL/TP eklemede basarisiz olursa pozisyon zorla kapatilir."*
- AX-4 "SL VE TP" mi, "SL VEYA TP" mi? Metin belirsiz. Kod "SL yeterli" sayıyor.
- **TP olmadan pozisyon:** Trailing TP _manage_active_trades'te zamanla oluşur ama anında TP korumasız. Hızlı fiyat hareketi olursa pozisyon TP hedefine ulaşıp geri dönebilir — fırsat kaybı ama güvenlik zafiyeti değil.

**Etki:** Finansal risk değil, **anayasa-kod drift'i**. AX-4 spesifikasyonu "TP eksik" case'ini kapsamıyor. Dokümantasyon boşluğu + OgulSLTP kodunu okumadım, TP ekleme/güncelleme mantığı için **BİLMİYORUM**.

#### YB-41 — `_remove_trade` fonksiyonu DEAD CODE
**Dosya:** `engine/ogul.py:2004-2037`
**Kanıt:** `Grep` ile `engine/` altında "_remove_trade" araması:
```
engine/ogul.py:2004: def _remove_trade(
(Yalnızca tanım. Başka çağrı YOK.)
```
**Etki:** 33 satır fonksiyon, hiçbir yerden çağrılmıyor. `_log_cancelled_trade` + `active_trades.pop()` + `db.insert_event()` kombinasyonu `_execute_signal` içinde inline yapılıyor. `_remove_trade` bu kombinasyonun "daha temiz" implementasyonu ama kullanılmamış. **Ölü kod**, bakım yükü. Faz 0.5'te tahmin edilmişti, Grep ile **kesin kanıtlandı**.

---

## BÖLÜM C — OYLAMA MANTIĞININ TAM PROFİLİ (YB-30 derinleştirmesi)

### C.1 — `_calculate_voting` ve `get_voting_detail` (ogul.py:744-959)

**4 bağımsız oy + ağırlıklı oylama:**

| # | Oy | Kaynak | Göstergeler | Module-level sabit |
|---|---|---|---|---|
| 1 | Momentum | RSI(14) | >50 BUY, <50 SELL | MR_RSI_PERIOD=14 |
| 2 | Trend | EMA(20) vs EMA(50) | crossover | TF_EMA_FAST=20, TF_EMA_SLOW=50 |
| 3 | Volatilite | ATR genişleme + son 3 bar yön | recent > prev + 2/3 bar konsensüsü | VOTING_ATR_LOOKBACK=5 |
| 4 | Likidite | Hacim / 20-bar ortalama | adaptif eşik (LOW vol=0.80, NORMAL/HIGH=1.0) | VOL_LOOKBACK=20 |

**Ağırlıklı oylama skoru (satır 889-917):**

| Oy kaynağı | Ağırlık |
|---|---|
| VOTE_W_RSI | 2.0 |
| VOTE_W_EMA | 2.5 |
| VOTE_W_TREND_PA (price action trend yapısı) | 2.5 |
| VOTE_W_ATR | 1.5 |
| VOTE_W_VOLUME | 1.5 |
| **Toplam** | **10** |

**Karar mantığı (satır 938-958):**
1. Basit oy çokluğu (buy_votes vs sell_votes) ilk önce
2. Beraberlikte ağırlıklı tiebreaker — fark ≥ 1.0 ise yön belirlenir
3. Aksi halde NOTR

### C.2 — `_determine_direction` 3 kaynak konsensüsü (ogul.py:965-1051)

| Kaynak | Yer | Bağımsız mı? |
|---|---|---|
| 1. `_calculate_voting` | M15 data | RSI + EMA(20/50) + ATR + Volume + PA trend |
| 2. H1 trend filtresi | H1 data | EMA(20) vs EMA(50) + gap_pct>%0.5 |
| 3. SE3 motoru | M5 data | `engine/utils/signal_engine.py::se3_generate_signal` — 9 bağımsız kaynak (yapı-öncelikli) |

**Konsensüs kuralı:** Her kaynak BUY/SELL veya yok (0) oyluyor; max(buy, sell) ≥ 2 ise yön belirleniyor. **2/3 çoğunluk.**

**BAĞIMSIZLIK ANALİZİ:**
- Kaynak 1 (voting) EMA(20 vs 50) M15 kullanıyor
- Kaynak 2 (H1 filter) **AYNI EMA(20 vs 50)** H1 kullanıyor
- Kaynak 3 (SE3) bağımsız
- **Yani 2 kaynak korele**: Eğer trend güçlüyse hem M15 hem H1 EMA yönü genellikle aynı → Kaynak 1 ve 2 aynı oyu verir. İstatistiksel "bağımsızlık" sağlanmıyor.
- **YB-30 (Faz 0.5) DOĞRULANDI** — "3 bağımsız kaynak" iddiası zayıf.

### C.3 — Oylama eşiği hardcoded mı?
**Cevap: EVET, tamamen hardcoded.**
- `VOTE_W_*` ağırlıkları (229-233) module-level
- `WEIGHTED_VOTE_EXIT_THRESHOLD=3.0` (236) hardcoded
- `CONFLUENCE_MIN_SCORE=20.0` (_generate_signal:1256) fonksiyon-içi local
- `CONFLUENCE_PASS_SCORE=50.0` (1186) fonksiyon-içi local
- `CONVICTION_HIGH_THRESHOLD=75.0`, `CONVICTION_MED_THRESHOLD=60.0`, `CONVICTION_HIGH_MULT=1.0`, `CONVICTION_MED_MULT=0.7`, `CONVICTION_LOW_MULT=0.5` (239-243)

`config/default.json`'da hiçbiri yok. **R-11 "Sihirli sayı yasağı" ihlali.** YB-32 (Faz 0.5) kapsamında.

### C.4 — SE3 motoru entegrasyonu
- Import: `engine/utils/signal_engine.py::generate_signal as se3_generate_signal` (ogul.py:71-74)
- Çağrı 1: `_determine_direction:1019-1024` — yön konsensüsü için
- Çağrı 2: `_generate_signal:1111-1116` — sinyal aday üretimi için
- SE3 "9 bağımsız kaynak" iddiası — `signal_engine.py` kodu **okunmadı** (BİLMİYORUM). SE3'ün iç mantığı doğrulanmamış.

---

## BÖLÜM D — TRADE LIFECYCLE ÇIKIŞ YOLLARI HARİTASI

```
┌─────────────────────┐
│  Signal üretildi    │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  _execute_signal    │
│  (1648-1977)        │
└──────────┬──────────┘
           │
           ├── ATR yok           ──► log → return
           ├── Account bilgi yok ──► log → return
           ├── BABA yok          ──► log → return
           ├── lot=0             ──► log → return
           ├── correlation fail  ──► _log_cancelled_trade("correlation: ...")
           ├── trading_hours     ──► _log_cancelled_trade("outside_trading_hours")
           ├── concurrent_limit  ──► _log_cancelled_trade("concurrent_limit ...")
           ├── account_info fail ──► _log_cancelled_trade("account_info_unavailable")
           ├── margin fail       ──► _log_cancelled_trade("margin_insufficient ...")
           ├── send_order fail   ──► _log_cancelled_trade("send_order_failed")
           │
           ├── SL setup fail + close success ──► state=CLOSED,
           │                                     "sl_placement_failed",
           │                                     direkt db.insert_event
           │                                     (NOT: _log_cancelled_trade YOK!)
           │
           ├── SL setup fail + close fail    ──► state=CANCELLED,
           │                                     "sl_placement_failed_and_close_failed ...",
           │                                     baba.report_unprotected_position(),
           │                                     direkt db.insert_event
           │                                     (NOT: _log_cancelled_trade YOK!)
           │
           └── Başarılı → state=FILLED, DB insert, sayaç ++
                    │
                    ▼
           ┌─────────────────────┐
           │  _manage_active_    │
           │  trades (cycle)     │
           └──────────┬──────────┘
                      │
                      ├── OLAY rejimi    ──► _handle_closed_trade("regime_olay")
                      ├── VOLATILE+zarar ──► _handle_closed_trade("regime_volatile_loss")
                      ├── MT5'te yok     ──► _handle_closed_trade("sl_tp")   ⚠️ varsayım
                      ├── yapısal kopma  ──► _handle_closed_trade("structural_break")
                      └── volume spike   ──► _handle_closed_trade("volume_spike_adverse")

           ┌─────────────────────┐
           │  _sync_positions    │
           │  (cycle)            │
           └──────────┬──────────┘
                      │
                      ├── SL triggered  ──► _handle_closed_trade("sl_tp"?)  (satır 3086-3090 belirsiz)
                      └── external close ──► _handle_closed_trade("external_close")

           ┌─────────────────────┐
           │  _check_end_of_day  │
           │  (cycle)            │
           └──────────┬──────────┘
                      │
                      └── 17:45+ FILLED  ──► _handle_closed_trade("end_of_day")
```

### Tutarsızlıklar:

1. **`_log_cancelled_trade` vs direkt `db.insert_event`:** _execute_signal içinde 6 cancel durumu `_log_cancelled_trade` çağırıyor. Ama 2 durum (SL fail variants) `_log_cancelled_trade` atlayıp doğrudan `db.insert_event` çağırıyor (1904-1911, 1934-1942). **Event type farklı**: `_log_cancelled_trade` → `"ORDER_CANCELLED"`, direkt → `"TRADE_CLOSE"` / `"TRADE_ERROR"`. Dashboard filtresi bu iki event'i farklı yerlerde gösterebilir.

2. **`_remove_trade` (2004-2037) DEAD CODE (YB-41):** Grep ile doğrulandı. Benzer işlevi yapan hiçbir çağrı noktası yok. `_log_cancelled_trade` + `active_trades.pop()` kombinasyonu her yerde inline yapılıyor.

3. **`_handle_closed_trade` reason uyumsuzlukları:**
   - _manage_active_trades MT5'te yoksa varsayımsal "sl_tp" (ogul.py:2399)
   - _sync_positions MT5'te yoksa "external_close" (ogul.py:3096)
   - **Aynı durum → 2 farklı kod yolu → 2 farklı reason.** YB-25 (Faz 0) merkezinde.

### Race Condition / Dangling Reference Riski:

- `_execute_signal` satır 1790-1803 `_trade_lock` ile atomik slot ayırma. Lock bırakıldıktan sonra (1803) MT5 çağrıları geliyor — account_info, send_order. Lock bu çağrılar sırasında alınmıyor. Başka thread aynı anda active_trades üzerinde `pop()` yapabilir, ama ana thread tek (main loop) → düşük risk.
- `active_trades[symbol] = trade` (1803), sonra exception olursa `active_trades.pop(symbol, None)` yapılıyor (1810, 1822, 1856, vb.). Ama `send_order` ve SL setup sırasında exception olursa? Cleanup yok. 1853-1864 try olmadan direct `return` — trade `active_trades`'te asılı kalır. Sonraki cycle'da MT5 pozisyon yoksa sync_positions `_handle_closed_trade("external_close")` ile temizler. Self-healing ama kısa süreli dangling reference penceresi var.

---

## BÖLÜM E — FAZ 0/0.5 BAYRAKLARI DOĞRULAMA/ÇÜRÜTME/GENİŞLEME

| # | Bayrak | Durum | Faz 0.6'da not |
|---|---|---|---|
| 2 | AX-4 enforced_in yanlış konum | **GENİŞLEDİ** | ogul.py:1879-1943 AX-4 koruma uygulanıyor ✓; ama OgulSLTP fallback **TP KOYMUYOR** (YB-40) — "TP eksik" durumu AX-4 metninde tanımsız |
| 20 | Manuel SL/TP başarısızsa kapatmıyor | DOĞRULANDI | ogul.py AX-4'ü uyguluyor (1879-1943), manuel_motor değil. Aralarındaki drift pekişti |
| 25 | Cancel/exit reason tutarsızlığı | **DERİNLEŞTİ** | YB-36: 12+ farklı reason string, merkezi enum yok, ÜSTAT `_determine_fault` ile **imza uyumsuzluğu** var |
| 30 | "3 bağımsız kaynak" iddiası zayıf | DOĞRULANDI | Bölüm C.2'de kanıtlandı — kaynak 1 ve 2 aynı EMA(20/50) kullanıyor, korele |
| 32 | ogul.py hardcoded sabitler | DOĞRULANDI | Bölüm C.3'te ek liste (CONFLUENCE_MIN_SCORE=20, CONFLUENCE_PASS_SCORE=50, CONVICTION_* 5 sabit, VOTE_W_* 5 sabit). Toplam ~55+ sabit config'ten değil |

**Yeni doğrulanan:**
- _execute_signal'daki 6 altın kural niyeti (ATR, account, BABA, lot, correlation, trading_hours, concurrent, margin, send_order) sırayla enforce ediliyor ✓
- Çift katmanlı trading_hours koruması (1783 vs 614) fail-safe depth ✓
- Atomik concurrent slot reservation `_trade_lock` ile (1790-1803) ✓
- AX-4 "korumasız pozisyon yasak" fallback zinciri (SLTP→OgulSLTP→close_position→report_unprotected_position) tam uygulanmış ✓

**Çürütülen:** Yok.

---

## BÖLÜM F — NİHAİ BAYRAK SAYIMI

| Kategori | Faz 0 | Faz 0.5 | Faz 0.6 | Toplam |
|---|---|---|---|---|
| Seviye 1 — Anayasa/Kod Drift | 5 | 2 | 0 (YB-40 Seviye 2'ye düştü) | **7** |
| Seviye 2 — Kod Kalitesi / Bug Riski | 7 | 13 | 6 (YB-36..41) | **26** |
| Seviye 3 — Test Katmanı Zayıflığı | 3 | 0 | 0 | **3** |
| Seviye 4 — R-11 Sihirli Sayı | 1 | 3 | 0 (YB-32 genişledi, yeni sayılmadı) | **4** |
| Seviye 5 — CORS / Ölü Kod | 2 | 2 | 1 (YB-41 ölü kod) | **5** |
| **TOPLAM** | **15** | **17** | **6** | **38** |

**Not:** YB-40 (AX-4 TP eksik) ilk bakışta Seviye 1 anayasa drift sayılabilir ama anayasa metni "TP eksik" durumunu tanımlamadığından, kod "uyumsuzluk" değil "tanımsız bölge" içinde. Seviye 2 "dokümantasyon boşluğu + davranış belirsizliği" olarak sınıflandırıldı.

---

## ÖZET

Faz 0.6 tamamlandı. **ogul.py %100 kapsam sağlandı.** 6 yeni bayrak:
1. **YB-36** — Cancel/exit reason schema merkezi değil, ÜSTAT imza uyumsuzluğu
2. **YB-37** — `trade.initial_risk` MT5 stops_level modification öncesi hesaplanıyor, R-Multiple drift
3. **YB-38** — `_is_new_m5_candle` tek sample, single-point-of-failure
4. **YB-39** — `increment_daily_trade_count` DB insert öncesi, sayaç drift riski
5. **YB-40** — OgulSLTP sadece SL koyuyor, AX-4 "TP eksik" durumu tanımsız
6. **YB-41** — `_remove_trade` dead code (Grep ile kanıtlandı)

**Kritik derinleşme:** YB-30 (3 bağımsız kaynak zayıf) kanıt ile doğrulandı — Kaynak 1 (voting) ve Kaynak 2 (H1 trend) AYNI EMA(20/50) göstergesini kullanıyor, istatistiksel bağımsızlık yok.

**Bilmediğim (BİLMİYORUM):**
- `engine/ogul_sltp.py` (OgulSLTP) kodu — TP koyma mantığı var mı? YB-40 tam cevap için bu dosya gerekli.
- `engine/utils/signal_engine.py` (SE3) kodu — "9 bağımsız kaynak" iddiasının doğrulaması.

**Toplam bayrak sayımı: Faz 0 (15) + Faz 0.5 (17) + Faz 0.6 (6) = 38 aktif bayrak.**

Faz 1 (audit) onayına hazır.
