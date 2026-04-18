# FAZ 0.7 — SON İKİ KRİTİK MODÜL RAPORU

**Tarih:** 2026-04-16
**Amaç:** Faz 0.6'da kalan iki "BİLMİYORUM" bölgesini kapatmak:
- `engine/ogul_sltp.py` → YB-40 (AX-4 TP eksik) kesin cevap
- `engine/utils/signal_engine.py` → YB-30 (SE3 "9 bağımsız kaynak") doğrulama
**Yöntem:** Doğrudan `Read`, alt-ajan delegasyonu YOK.

---

## BÖLÜM A — OKUMA KAPSAMI

| Dosya | Satır sayısı | Okundu | Kapsam |
|---|---|---|---|
| `engine/ogul_sltp.py` | 361 | 1-361 | **%100** ✓ |
| `engine/utils/signal_engine.py` | 1512 | 1-1511 | **%100** ✓ |

---

## BÖLÜM B — YENİ BAYRAKLAR (YB-42 ~ YB-45)

### Seviye 2 — Kod Kalitesi / Bug Riski

#### YB-42 — signal_engine.py docstring kaynak sayısı güncel değil
**Dosya:** `engine/utils/signal_engine.py:12-22` (başlık) vs `1269` (generate_signal)
**Kanıt:**
```python
# Dosya başlığı (12-22):
"""
9 Bağımsız Sinyal Kaynağı:
    A) Yapı Kırılımı ...
    ...
    I) Adaptif Momentum ...
"""

# generate_signal docstring (1269):
"""Ana sinyal üretim motoru — 10 bağımsız kaynaktan karar (SE3 + News)."""

# total_sources yorumu (1376):
total_sources = len(sources)  # 10
```
**Etki:** Dosya başlığı A..I (9 kaynak) diyor ama J (News Event) eklenmiş (1208-1251 v5.7.1 güncellemesi). Generate_signal 10 sayıyor. **Dokümantasyon-kod drift.** Yeni okuyucu "9" sayısına güvenir, gerçekte 10 kaynak çalışıyor. Anayasada `_source_news_event` referansı yok.

#### YB-43 — R:R minimum eşiği (1.5) uygulanmıyor, sadece strength penalty
**Dosya:** `engine/utils/signal_engine.py:1473-1481`
**Kanıt:**
```python
if verdict.risk_reward < min_rr:
    if verdict.risk_reward <= 0:
        verdict.should_trade = False      # ← sadece 0 veya negatif bloke
        return verdict
    # Kademeli penalty: R:R = min_rr/2 ise strength × 0.5
    rr_penalty = min(verdict.risk_reward / min_rr, 1.0)
    verdict.strength *= rr_penalty
```
**Etki:** MIN_RISK_REWARD=1.5 (satır 120) "minimum" iddia ediyor. Ama R:R=0.1 bile kabul ediliyor (strength × 0.067). `should_trade=True` kalır, ogul.py bunu yürütür. **Sert kapı yerine yumuşak penalty** — finansal risk açısından "minimum" garantisi yok. Zayıf R:R sinyaller sadece strength düşük olduğundan dolaylı filtrelenir (confluence skoru vb. üzerinden). Sinyal gerçekten kötü olsa bile potansiyel olarak geçer.

#### YB-44 — `strategy_type` eşleme 8/10 kaynak için tanımlı, 2 kaynak varsayılan `trend_follow` alır
**Dosya:** `engine/utils/signal_engine.py:1487-1501`
**Kanıt:**
```python
MR_SOURCES = {"extreme_reversion", "smart_divergence"}           # 2
BO_SOURCES = {"compression_release", "structure_break"}           # 2
TF_SOURCES = {"momentum_ignition", "ichimoku_cloud",
              "adaptive_momentum", "vwap_institutional"}          # 4
# Toplam: 8 kaynak tanımlı

if dominant.name in MR_SOURCES: ...
elif dominant.name in BO_SOURCES: ...
elif dominant.name in TF_SOURCES: ...
else:
    verdict.strategy_type = "trend_follow"   # ← volume_intelligence ve news_event buraya düşer
```
**Etki:** 10 kaynaktan 2 tanesi (`volume_intelligence`, `news_event`) hiçbir strateji setine atanmamış → dominant olduklarında varsayılan `"trend_follow"` atanıyor. Hacim klimaksı aslında breakout veya mean reversion olabilir — haber sinyali genelde "news-driven" bir şey. İkisi de körleme trend_follow sayılıyor. ogul.py'de strateji bazlı yönetim (`_manage_trend_follow` vb.) yanlış stratejiyle çalıştırılır. **Yanlış atfetme → yanlış yönetim.** Kullanım sıklığı sık değil ama kanıtlı mantık hatası.

### Seviye 4 — R-11 Sihirli Sayı

#### YB-45 — signal_engine.py ~30+ module-level hardcoded sabit
**Dosya:** `engine/utils/signal_engine.py:107-208`
**Sayım:**
- Konsensüs eşikleri: MIN_AGREEING_SOURCES, MIN_AGREEING_SOURCES_LOW_VOL, MIN_TOTAL_SCORE, MIN_TOTAL_SCORE_LOW_VOL, MIN_RISK_REWARD — **5**
- REGIME_SE2_PARAMS (4 rejim × 3 parametre) — **12**
- Volatilite: LOW_VOL_PERCENTILE, HIGH_VOL_PERCENTILE — **2**
- SOURCE_WEIGHTS (10 kaynak) — **10**
- VWAP: VWAP_BOUNCE_ATR, VWAP_BREAK_ATR — **2**
- Ichimoku: ICHI_STRONG_SCORE, ICHI_WEAK_SCORE — **2**
- KAMA: KAMA_TREND_SLOPE, KAMA_FLAT_SLOPE — **2**
- Divergence: DIV_MIN_STRENGTH, DIV_MAX_AGE_BARS — **2**
- S/R: SR_PROXIMITY_ATR, SR_BREAK_ATR — **2**
- Momentum: ROC_STRONG, ROC_WEAK, STOCH_RSI_OB, STOCH_RSI_OS, STOCH_RSI_CROSS_ZONE — **5**
- Compression: COMPRESSION_TIGHT, COMPRESSION_EXPANDING — **2**
- Extreme: EXTREME_RSI_OB, EXTREME_RSI_OS, EXTREME_WR_OB, EXTREME_WR_OS — **4**

**Toplam ~50 sabit, config'te hiçbiri yok.** R-11 ihlali. Yorumlarda "[VİOP kalibrasyon: X→Y]" arşiv değerler duruyor — kirli.

---

## BÖLÜM C — OgulSLTP TAM PROFİLİ (YB-40 KESİN CEVAP)

### C.1 — Sınıf imzası ve metotları

**Dosya:** `engine/ogul_sltp.py` (361 satır)

**Sınıf:** `OgulSLTP` (satır 35)
**Docstring (satır 1-21, 36-50):** *"OĞUL pozisyonları için **STOP LIMIT SL yöneticisi**."* — açıkça "SL yöneticisi" iddia ediyor, TP sözcüğü hiçbir yerde geçmiyor.

**Public metotlar:**
| # | Metot | Satır | Amaç |
|---|---|---|---|
| 1 | `__init__(mt5, config)` | 52-64 | Stop_limit_gap_prim config'ten al, modify fail sayacı init |
| 2 | `_viop_tick_size(price)` (static) | 70-93 | VİOP fiyat adımı hesapla |
| 3 | `_calc_limit_price(stop_price, order_direction)` | 95-124 | Stop'tan limit fiyatı türet |
| 4 | `set_initial_sl(trade, sl)` | 130-166 | İlk SL Stop Limit emri yerleştir |
| 5 | `update_trailing_sl(trade, new_sl)` | 172-261 | SL'yi modify → cancel+replace |
| 6 | `cancel_orders(trade)` | 267-289 | Pozisyon kapanışta SL emri iptal |
| 7 | `check_sl_triggered(trade)` | 295-321 | SL emri kayboldu mu kontrol |
| 8 | `restore_sl_order(trade)` | 327-361 | Restart sonrası SL emri eşle veya yeniden yerleştir |

### C.2 — YB-40 kesin cevap: **DOĞRULANDI**

**İddia:** "OgulSLTP sadece SL koyuyor, TP koymuyor."

**Kanıt (kesin):**
1. **Hiçbir metot TP içermiyor:** `set_initial_tp`, `set_initial_sltp`, `update_tp` yok.
2. **`trade.sl_order_ticket` tek alan** (satır 154, 246, 287, 343) — TP ticket alanı yok.
3. **Comment pattern `OGUL_SL_{trade.ticket}`** (satır 150, 242, 340) — SL'ye özel, TP comment'i yok.
4. **`send_stop_limit` çağrısı** (satır 147-151, 239-243) sadece SL direction (BUY poz → SELL stop limit, SELL poz → BUY stop limit) — kâr al emri yerleştirme mekanizması yok.
5. **`_calc_limit_price` sadece SL gap hesaplar** (99-103) — TP için ayrı hesap yok.

**Davranış zinciri:**
1. ogul.py `_execute_signal` → `mt5.send_order(sl, tp)` çağırır.
2. mt5_bridge `TRADE_ACTION_SLTP` dener (atomik, SL+TP birlikte).
3. GCM VİOP netting'de `TRADE_ACTION_SLTP` → `retcode=10035 Invalid order` → `sl_tp_applied=False`.
4. ogul.py fallback: `self._sltp.set_initial_sl(trade, signal.sl)` — **sadece SL.**
5. Pozisyon açık, SL Stop Limit emriyle korumalı, **TP YOK.**

### C.3 — AX-4 ile ilişki

**AX-4 metni (`governance/axioms.yaml:36-38`):**
> *"send_order SL/TP eklemede basarisiz olursa pozisyon zorla kapatilir. Korumasiz pozisyon yasak."*

**Yorumlama:**
- **Sıkı okuma:** "SL/TP" ifadesi "SL VE TP" anlamına gelir. Kısmi başarı (sadece SL) AX-4 kapsamında olmalı → pozisyon kapatılmalı.
- **Liberal okuma:** "Korumasiz pozisyon yasak" kısmına bakıp SL varsa "koruma sağlandı" sayılır → pozisyon açık kalabilir.

**Kod davranışı liberal okumayı uyguluyor.** Dokümantasyon metni "TP eksik" senaryosu için spesifikasyon içermiyor — **tanımsız bölge.**

### C.4 — YB-40'ın Seviye 1'e yükseltilmesi

Faz 0.6'da YB-40 Seviye 2 (dokümantasyon boşluğu + davranış belirsizliği) olarak sınıflandırılmıştı.
Faz 0.7 kesin kanıtıyla: kod AX-4'ü kısmi olarak uygulamıyor. **Seviye 1'e yükseltilir** çünkü:
1. Anayasa axiom'u koruma garantisi veriyor ama kod sadece yarı veriyor
2. TP eksik pozisyon = hedefsiz açık pozisyon = risk/reward belirsiz

Ama bu yükseltme tartışmalı çünkü anayasa metni yoruma açık. **Sınıflandırma: Seviye 1.5 (Anayasa metni boşluğu + kod kısmi uygulama).** Rapor için Seviye 1 sayılacak, `governance/axioms.yaml` AX-4 metninin netleştirilmesi önerilir.

### C.5 — Diğer bulgular

- **`_MAX_MODIFY_RETRIES = 3`** (satır 32) hardcoded — R-11 küçük ihlal (YB-32 kümülatif).
- **Config anahtarı:** `ogul.stop_limit_gap_prim` (56) — config/default.json:188'de mevcut, default 0.3 ✓.
- **Thread-safety:** `_modify_fail_counts` dict açık yazma (satır 207, 214, 229, 254, 289). Ama OGUL tek thread'te çalışıyor (main loop), risk yok.
- **`check_sl_triggered` false-positive riski:** SL emri MT5 tarafında iptal edilmiş olabilir (broker tarafı). Kod "tetiklendi" varsayıyor, pozisyon kapanmış varsayılıp _handle_closed_trade çağrılıyor (`ogul.py:3086-3090`). Gerçekte pozisyon hâlâ açık olabilir. **Küçük yan etki** — sonraki cycle sync_positions düzeltir.

---

## BÖLÜM D — SE3 (signal_engine.py) TAM PROFİLİ (YB-30 KESİN CEVAP)

### D.1 — Fonksiyon imzası

**Ana entry:** `generate_signal` (satır 1258-1511)
```python
def generate_signal(
    open_: np.ndarray, high, low, close, volume,
    current_price: float = 0.0,
    regime_type: str = "",
    symbol: str = "",
    news_bridge=None,
) -> SignalVerdict
```

**Dönüş:** `SignalVerdict` dataclass (87-102) — `should_trade`, `direction`, `strength` (0-1), `total_score` (0-100), `agreeing_sources`, `entry_price`, `structural_sl/tp`, `risk_reward`, `strategy_type`.

### D.2 — 10 Kaynak Listesi (docstring 9 diyordu — YB-42)

| Kod | İsim | Gösterge(ler) | Veri | Puan |
|---|---|---|---|---|
| A | structure_break | S/R levels + bar patterns + trend structure | M15 PA | 0-20 |
| B | momentum_ignition | ROC(12,5) + StochRSI | M15 | 0-20 |
| C | volume_intelligence | OBV divergence + Volume momentum + Volume climax | M15 + vol | 0-20 |
| D | compression_release | Compression ratio + Volume destek | M15 | 0-20 |
| E | extreme_reversion | RSI(14) + Williams%R(14) + StochRSI | M15 | 0-20 |
| F | vwap_institutional | VWAP + Bands + Cross | M15 + vol | 0-20 |
| G | smart_divergence | RSI div + MACD hist div + OBV div | M15 | 0-20 |
| H | ichimoku_cloud | 5-bileşen Ichimoku | M15 | 0-20 |
| I | adaptive_momentum | KAMA slope + price-KAMA + Efficiency Ratio | M15 | 0-20 |
| J | news_event | NewsBridge sentiment | ext | 0-20 |

### D.3 — GÖSTERGE BAĞIMSIZLIK ANALİZİ (YB-30 derinleştirme)

**Çakışmalar (aynı gösterge, farklı yorum):**

| Gösterge | Kaynak 1 | Kaynak 2 | Kaynak 3 |
|---|---|---|---|
| **StochRSI** | B (momentum flip) | E (aşırı bölge) | — |
| **RSI(14)** | E (aşırı bölge) | G (divergence) | — |
| **OBV** | C (divergence + momentum) | G (divergence) | — |
| **Volume (raw)** | C (climax) | D (compression destek) | F (VWAP ağırlığı) |

**Kısmi korelasyon:**
- **VWAP (F) ve KAMA (I):** İkisi de "fiyat-ortalama pozisyonu" kavramsal benzer; matematiksel farklı. Düşük korelasyon.
- **Price action (A) ve trend structure:** A içinde `analyze_trend_structure` kullanılıyor; I KAMA slope da trend ölçümü. Farklı metotlar, düşük korelasyon.

**Tamamen bağımsız (gösterge paylaşımı yok):**
- A — Structure Break (price action saf)
- D — Compression Release (saf fiyat range)
- F — VWAP Institutional (hacim-ağırlıklı ortalama)
- H — Ichimoku Cloud (5-bileşen Japon sistemi, RSI/MACD kullanmıyor)
- I — Adaptive Momentum (KAMA, RSI/MACD kullanmıyor)
- J — News Event (dış veri kaynağı)

**Çakışmalı (gösterge paylaşan):**
- B (StochRSI) ↔ E (StochRSI, RSI)
- E (RSI, StochRSI, WR) ↔ G (RSI)
- C (OBV) ↔ G (OBV)

**Bağımsız kaynak sayımı:**
- **Tam bağımsız:** 6 kaynak (A, D, F, H, I, J)
- **Kısmen korele:** 4 kaynak (B, C, E, G — gösterge çakışmaları var)
- **Efektif bağımsızlık derecesi: ~6-7 / 10 (ortalama ~%65)**

**Önceki YB-30 iddiası (Faz 0.5 + 0.6):** "Kaynak 1 ve 2 aynı EMA kullanıyor" — bu iddia `_determine_direction` (ogul.py:965) içindeki 3 kaynak hakkındaydı (voting + H1 trend + SE3). Burada SE3'ün iç kaynakları analiz edildi; kısmen korelasyon var ama "9'un 4'ü" kadar sert değil.

**Yeniden sınıflandırma:**
- **ogul.py `_determine_direction` 3 kaynak:** Voting ve H1 trend **aynı gösterge (EMA 20/50)** kullanıyor — kesin korele. YB-30 doğru.
- **SE3 iç 10 kaynak:** Çakışma var ama 6 tam bağımsız kaynak arkasında. İddia "9 bağımsız" abartılı ama "4'ü gerçek" kadar sert değil. **Efektif bağımsızlık ~6-7**.

### D.4 — Konsensüs mantığı

**Yön belirleme (satır 1378-1397):**
```python
buy_sources = [s for s in sources if s.direction == "BUY" and s.score > 2.0]
# 3 yol:
if len(buy_sources) >= min_agree:  # normal
    verdict.direction = "BUY"
elif len(sell_sources) >= min_agree:
    verdict.direction = "SELL"
elif len(buy_sources) > len(sell_sources) and len(buy_sources) >= 2:  # azınlık fallback
    verdict.direction = "BUY"   # ← 2/10 ile de geçer
elif len(sell_sources) > len(buy_sources) and len(sell_sources) >= 2:
    verdict.direction = "SELL"
```

**min_agree rejime göre:** TREND=2, RANGE=2, VOLATILE=3, OLAY=5, fallback NORMAL=3, LOW_VOL=2.

**Gerçek eşik:** Minimum 2/10 kaynak yeterli. Azınlık fallback (3. ve 4. yollar) 2/10 ile geçebiliyor — docstring'in "minimum 3/9" iddiasını çürütüyor (satır 24). **Kod-doküman drift.**

### D.5 — Skor toplama ve strength hesabı

```python
total = sum(s.score for s in agreeing)      # toplam 0-100
# Strength = ağırlıklı ortalama
weighted_sum = sum(s.confidence * SOURCE_WEIGHTS[s.name] for s in agreeing)
weight_total = sum(SOURCE_WEIGHTS[s.name] for s in agreeing)
verdict.strength = weighted_sum / weight_total
```

- **Vote-mechanism değil, score-aggregation.** Her kaynak 0-20 puan üretir, agreeing kaynakların toplamı total_score, ağırlıklı confidence ortalaması strength.
- SOURCE_WEIGHTS en yüksek: VWAP (1.3), News (1.3), Momentum (1.2). En düşük: Extreme Reversion (0.8), Ichimoku (0.8).

### D.6 — Yapısal SL/TP

SE3 kendi yapısal SL/TP hesabı yapar (1432-1464):
- **BUY SL:** son swing_low - 0.3×ATR, veya fallback current - 1.5×ATR
- **BUY TP:** İlk direnç - 0.1×ATR, veya 2×risk fallback
- **SELL tersi**

Bu SL/TP signal_engine'in kendi önerisi. ogul.py `_generate_signal` bu önerileri candidate sinyale atar, sonra confluence filter çalıştırır.

### D.7 — SE3 hardcoded sabitler (YB-45)

~50 sabit module-level (Bölüm B YB-45'te listelendi). Config'te hiçbiri yok. **Trading kalbinin parametreleri tamamen koddan geliyor** — operasyon ekibi değiştirmek istese kod commit gerekir.

---

## BÖLÜM E — FAZ 0/0.5/0.6 BAYRAKLARI DOĞRULAMA/ÇÜRÜTME/DEĞİŞEN

| # | Bayrak | Durum | Not |
|---|---|---|---|
| 30 | "3 bağımsız kaynak" zayıf | **KISMEN GENİŞLEDİ** | ogul.py _determine_direction için kanıt güçlü (voting + H1 aynı EMA). SE3 iç 10 kaynak için bağımsızlık ~6-7/10. İddia "9 bağımsız" abartılı ama "3 bağımsız iddia hatalı" ogul seviyesinde. |
| 40 | OgulSLTP sadece SL, TP yok | **KESİN DOĞRULANDI + SEVİYE 1'E YÜKSELTME** | 361 satırın tamamı TP-free. AX-4 metni "kısmi başarı" tanımlamadığından tartışmalı anayasa drift'i. Seviye 1 olarak sınıflandırıldı. |
| 32 | ogul.py hardcoded sabitler | **GENİŞLEDİ** | signal_engine.py ~50 sabit eklendi (YB-45). Kümülatif "trading beyninin parametreleri config'te yok" sorunu. |

**Çürütülen:** Yok.

**Revize edilen sınıflandırma:**
- **YB-40** Faz 0.6'da Seviye 2 → Faz 0.7'de Seviye 1 (kesin kanıt ile)

---

## BÖLÜM F — NİHAİ BAYRAK SAYIMI

| Kategori | Faz 0 | Faz 0.5 | Faz 0.6 | Faz 0.7 | Toplam |
|---|---|---|---|---|---|
| Seviye 1 — Anayasa/Kod Drift | 5 | 2 | 0 | 1 (YB-40 yükseltme) | **8** |
| Seviye 2 — Kod Kalitesi / Bug | 7 | 13 | 5 (YB-40 çıkar) | 3 (YB-42, 43, 44) | **28** |
| Seviye 3 — Test Katmanı | 3 | 0 | 0 | 0 | **3** |
| Seviye 4 — R-11 Sihirli Sayı | 1 (yaygın) | 3 | 0 | 1 (YB-45) | **5** |
| Seviye 5 — CORS / Ölü Kod | 2 | 2 | 1 (YB-41) | 0 | **5** |
| **YENİ EKLEME** | **15** | **17** | **6** | **4** | **42** |

**Net aktif bayrak sayısı: 42**

---

## BÖLÜM G — "BİLMİYORUM" KALAN VAR MI?

### G.1 — Faz 0.7 ile kapatılanlar ✓

| Soru | Durum |
|---|---|
| YB-40: OgulSLTP TP koyuyor mu? | **KESİN CEVAP: HAYIR.** Seviye 1 anayasa drift. |
| YB-30: SE3 9 bağımsız kaynak mı? | **KESİN CEVAP: KISMEN.** 6 bağımsız + 4 gösterge-çakışmalı = efektif ~6-7/10. |

### G.2 — Kalan BİLMİYORUM (Faz 1 audit'e devreden)

Bu 14 dosya kritik değil ama tamamen okunmadı. Audit sırasında hedefli incelenmesi gerekebilir:

| Dosya | Önem | Not |
|---|---|---|
| `engine/data_pipeline.py` | **Yüksek** (Kırmızı Bölge #7) | `update_risk_snapshot` drawdown hesaplar — BABA bunu kullanıyor |
| `engine/top5_selection.py` | **Orta** (ogul.py delege ediyor) | Anayasa R-03 "Top 5 Seçim Algoritması" burada |
| `engine/models/risk.py` | **Orta** | RiskParams dataclass — api/server.py default değerler kullanıyor (YB düzelme bağlam) |
| `engine/models/regime.py, signal.py, trade.py` | Düşük | Dataclass tanımları |
| `engine/config.py` | Düşük (Sarı Bölge) | JSON yükleyici |
| `engine/logger.py` | Düşük (Sarı Bölge) | Loguru wrapper |
| `engine/news_bridge.py` | Düşük | NewsBridge — SE3 J kaynak |
| `engine/utils/indicators.py` | Düşük | TA hesaplamalar |
| `engine/utils/price_action.py` | Düşük | S/R, pattern, trend structure |
| `engine/utils/multi_tf.py` | Düşük | Multi-timeframe |
| `engine/event_bus.py, health.py, error_tracker.py` vb. | Düşük | Yardımcı modüller |
| `api/routes/*.py` (23 dosya) | **Orta** | Frontend API |
| `desktop/src/**/*.jsx` (21 bileşen) | **Orta** | React UI |
| `tests/` (kritik_flows hariç) | Düşük | Stress/unit testleri |
| `tools/*.py` | **Orta** | Governance otomasyon |

**Proje olgunluğu açısından:** Ana iş mantığı (10 core engine dosyası + 4 governance yaml + anayasa + kritik testler) %100 okundu. Peripheri modüller audit'te hedefli olarak okunur.

### G.3 — Değerlendirme

**Faz 0-0.7 kümülatif kapsam (kritik dosyalar):**
- Anayasa katmanı (governance + USTAT_ANAYASA.md): **%100**
- Engine çekirdek (baba, ogul, h_engine, ustat, mt5_bridge, database, main, manuel_motor, ogul_sltp, signal_engine): **%100**
- api/server.py: **%100**
- tests/critical_flows/test_static_contracts.py: **%100**

**Yeni BİLMİYORUM üretildi mi?** Hayır. Faz 0.7 iki açık soruyu kesin cevapla kapattı. Yeni bir "bilmediğim" ortaya çıkmadı.

**Proje olgunluğu revize mi?** Hayır. Faz 0'daki "Production, aktif çalışıyor" değerlendirmesi geçerli. 42 bayrak **kalite meselesi**, sistemi çalışmaz hale getirmiyor. 8 Seviye 1 bayrağı anayasal drift — **bunlar audit'in ana gündemi**.

---

## ÖZET

Faz 0.7 tamamlandı. **ogul_sltp.py (%100) + signal_engine.py (%100) okundu.**

**İki "BİLMİYORUM" kesin cevaplandı:**
1. **YB-40 DOĞRULANDI + Seviye 1'e yükseltildi:** OgulSLTP tamamen SL-odaklı, TP mekanizması yok. AX-4 "TP eksik" durumu anayasada tanımsız → anayasa metni netleştirilmeli.
2. **YB-30 KISMEN DOĞRULANDI:** ogul.py `_determine_direction` 3 kaynak iddiası hâlâ zayıf (Kaynak 1 ve 2 aynı EMA). SE3 iç 10 kaynak için çakışma var (StochRSI, RSI, OBV ikişer kez kullanılıyor) ama 6 tam bağımsız kaynak mevcut. Efektif bağımsızlık %60-70.

**4 yeni bayrak (YB-42 ~ YB-45):**
- YB-42 docstring güncel değil (9 vs 10 kaynak)
- YB-43 MIN_RISK_REWARD uygulanmıyor, strength penalty ile yumuşak geçiyor
- YB-44 `strategy_type` eşleme 2 kaynak için eksik (volume_intelligence, news_event → varsayılan trend_follow)
- YB-45 signal_engine.py ~50 hardcoded sabit

**Toplam bayrak: Faz 0 (15) + Faz 0.5 (17) + Faz 0.6 (6) + Faz 0.7 (4) = 42 aktif bayrak.**
**Seviye 1 anayasa drift'i: 8 bayrak — audit'in ana gündemi.**

**Faz 1 (audit) için tam hazır.** Okunmayan modüller (data_pipeline, top5_selection, models/risk.py) audit sırasında hedefli incelemeye alınabilir; kritik drift ve bug riski ana motorlarda incelenmiş durumda.

Audit onayına hazır.
