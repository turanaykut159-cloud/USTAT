# RiskParams Drift Ölçüm Raporu

**Tarih:** 2026-04-16
**Amaç:** Faz 1 KARAR #9 aciliyet seviyesini belirlemek için RiskParams (dataclass default) ve config/default.json (operasyonel değerler) arasındaki drift'i alan bazında ölçmek.
**Yöntem:** Sadece okunan değerler. Yorum/tahmin yok.

---

## BÖLÜM A — RiskParams tam tanımı

**Dosya:** `engine/models/risk.py`
**Sınıf:** `RiskParams` (satır 15-46, dataclass)
**Satır sayısı:** 125 (tüm dosya)

| # | Alan | Tip | Default değer | Yorum (koddan) |
|---|---|---|---|---|
| 1 | `max_position_size` | `float` | `1.0` | — |
| 2 | `max_daily_loss` | `float` | `0.025` | v14: %1.8→%2.5 günlük max kayıp |
| 3 | `max_total_drawdown` | `float` | `0.10` | %10 toplam max drawdown |
| 4 | `risk_per_trade` | `float` | `0.01` | %1 işlem başına risk |
| 5 | `max_open_positions` | `int` | `5` | — |
| 6 | `max_correlated_positions` | `int` | `3` | — |
| 7 | `max_weekly_loss` | `float` | `0.04` | %4 haftalık → lot %50 azalt |
| 8 | `max_monthly_loss` | `float` | `0.07` | %7 aylık → sistem dur |
| 9 | `hard_drawdown` | `float` | `0.15` | %15 hard drawdown → tam kapanış |
| 10 | `max_floating_loss` | `float` | `0.020` | v14: %1.5→%2.0 floating loss → yeni işlem engeli |
| 11 | `max_daily_trades` | `int` | `8` | v14: 5→8 günlük max işlem sayısı (sadece otomatik) |
| 12 | `max_daily_manual_trades` | `int` | `10` | v5.9.3 BULGU #3: manuel için ayrı günlük sayaç |
| 13 | `max_risk_per_trade_hard` | `float` | `0.02` | tek işlem max %2 (hard cap) |
| 14 | `consecutive_loss_limit` | `int` | `3` | üst üste kayıp → cooldown |
| 15 | `cooldown_hours` | `int` | `2` | v14: 4→2 saat cool-down süresi |
| 16 | `max_same_direction` | `int` | `3` | aynı yönde max pozisyon |
| 17 | `max_same_sector_direction` | `int` | `2` | aynı sektörde aynı yönde max |
| 18 | `max_index_weight_score` | `float` | `0.25` | endeks ağırlık skoru limiti |
| 19 | `ustat_notifications` | `list[str]` | `[]` (field factory) | ÜSTAT→BABA bildirim kuyruğu (dinamik) |

**Toplam alan sayısı:** 19 (18 statik + 1 dinamik list)

---

## BÖLÜM B — config/default.json risk bölümü

**Dosya:** `config/default.json`
**Bölüm:** `"risk"` (satır 15-35)

| # | Anahtar | Değer | Tip |
|---|---|---|---|
| 1 | `max_daily_loss_pct` | `0.018` | float |
| 2 | `max_total_drawdown_pct` | `0.1` | float |
| 3 | `hard_drawdown_pct` | `0.15` | float |
| 4 | `risk_per_trade_pct` | `0.01` | float |
| 5 | `max_open_positions` | `5` | int |
| 6 | `max_correlated_positions` | `3` | int |
| 7 | `max_weekly_loss_pct` | `0.04` | float |
| 8 | `max_monthly_loss_pct` | `0.07` | float |
| 9 | `max_floating_loss_pct` | `0.015` | float |
| 10 | `max_daily_trades` | `5` | int |
| 11 | `max_daily_manual_trades` | `10` | int |
| 12 | `consecutive_loss_limit` | `3` | int |
| 13 | `cooldown_hours` | `4` | int |
| 14 | `fake_signal_threshold` | `5` | int |
| 15 | `baseline_date` | `"2026-04-16 09:50"` | str |
| 16 | `stats_baseline_date` | `"2026-02-01"` | str |
| 17 | `master_floating_loss_pct` | `0.05` | float |
| 18 | `sltp_max_retries` | `3` | int |
| 19 | `close_max_retries` | `3` | int |

**Toplam alan sayısı:** 19

**Not:** Config anahtarları `_pct` suffix'i kullanıyor (ör. `max_daily_loss_pct`), RiskParams dataclass field'ları suffix'siz (ör. `max_daily_loss`). **Mapping** `engine/main.py:103-117`'de manuel yapılıyor.

---

## BÖLÜM C — YAN YANA KARŞILAŞTIRMA TABLOSU

### C.1 — Eşleşen alanlar (13 alan)

| RiskParams alan | RiskParams default | Config anahtarı | Config değeri | Drift? | Drift yönü | % fark |
|---|---|---|---|---|---|---|
| `max_daily_loss` | 0.025 | `max_daily_loss_pct` | 0.018 | **EVET** | Config daha SIKI | config %28 daha sıkı |
| `max_total_drawdown` | 0.10 | `max_total_drawdown_pct` | 0.1 | HAYIR | — | 0% |
| `risk_per_trade` | 0.01 | `risk_per_trade_pct` | 0.01 | HAYIR | — | 0% |
| `max_open_positions` | 5 | `max_open_positions` | 5 | HAYIR | — | 0% |
| `max_correlated_positions` | 3 | `max_correlated_positions` | 3 | HAYIR | — | 0% |
| `max_weekly_loss` | 0.04 | `max_weekly_loss_pct` | 0.04 | HAYIR | — | 0% |
| `max_monthly_loss` | 0.07 | `max_monthly_loss_pct` | 0.07 | HAYIR | — | 0% |
| `hard_drawdown` | 0.15 | `hard_drawdown_pct` | 0.15 | HAYIR | — | 0% |
| `max_floating_loss` | 0.020 | `max_floating_loss_pct` | 0.015 | **EVET** | Config daha SIKI | config %25 daha sıkı |
| `max_daily_trades` | 8 | `max_daily_trades` | 5 | **EVET** | Config daha SIKI | config %37.5 daha sıkı |
| `max_daily_manual_trades` | 10 | `max_daily_manual_trades` | 10 | HAYIR | — | 0% |
| `consecutive_loss_limit` | 3 | `consecutive_loss_limit` | 3 | HAYIR | — | 0% |
| `cooldown_hours` | 2 | `cooldown_hours` | 4 | **EVET** | Config daha SIKI (cooldown uzun) | config %100 daha sıkı |

**Eşleşen alan sayısı:** 13
**Drift olan:** 4
**Drift olmayan:** 9

### C.2 — RiskParams'ta var, config'te yok (5 alan)

Bu alanlar `main.py:103-117` mapping'inde de yer almıyor. Her iki kod yolunda (main.py ve api/server.py) dataclass default kullanılıyor.

| RiskParams alan | Default |
|---|---|
| `max_position_size` | `1.0` |
| `max_risk_per_trade_hard` | `0.02` |
| `max_same_direction` | `3` |
| `max_same_sector_direction` | `2` |
| `max_index_weight_score` | `0.25` |

### C.3 — Config'te var, RiskParams'ta yok (6 alan)

Bu anahtarlar RiskParams dataclass'ında tanımlı değil. Farklı yerlerden okunuyor (baba.py module-level veya doğrudan `self.config.get()`).

| Config anahtarı | Değer | Nereden okunur |
|---|---|---|
| `fake_signal_threshold` | 5 | baba.py module-level `FAKE_SCORE_THRESHOLD=6` (hardcoded, config'ten okumuyor — YB-33) |
| `baseline_date` | "2026-04-16 09:50" | `baba.py:341` `self._risk_baseline_date = self._config.get("risk.baseline_date", ...)` |
| `stats_baseline_date` | "2026-02-01" | `api/constants.py` (Faz 0 alt-ajan raporu, doğrulanmadı) |
| `master_floating_loss_pct` | 0.05 | `baba.py:1921` `_MASTER_FLOATING_LIMIT = self._config.get("risk.master_floating_loss_pct", 0.05)` |
| `sltp_max_retries` | 3 | `baba.py` — kullanım doğrulanmadı (BİLMİYORUM) |
| `close_max_retries` | 3 | Config'te 3, ama `baba.py:2637` `CLOSE_MAX_RETRIES = 5` hardcoded — **KARAR #8 kapsamı** |

---

## BÖLÜM D — DRIFT ANALİZİ

### D.1 — Kaç alan farklı?

**4 alan farklı (drift):**
1. `max_daily_loss`: default 0.025 vs config 0.018 (**%28 daha sıkı config**)
2. `max_floating_loss`: default 0.020 vs config 0.015 (**%25 daha sıkı config**)
3. `max_daily_trades`: default 8 vs config 5 (**%37.5 daha sıkı config**)
4. `cooldown_hours`: default 2 vs config 4 (**%100 daha sıkı config** — cooldown 2x uzun)

### D.2 — Drift yönü

**Tüm drift alanlarında config daha sıkı davranış öngörüyor.** Yani config operatör tarafından "daha muhafazakâr" ayarlanmış; dataclass default'u ise "daha gevşek".

Bu şu anlama geliyor: Eğer bir kod yolu config'i okumazsa ve dataclass default kullanırsa, **sistem daha RİSKLİ davranır** — config'e göre izin verilenden daha fazla kayba/işleme açılır.

### D.3 — api/server.py vs main.py — hangi kod yolu hangi RiskParams'ı kullanıyor?

**main.py yolu (`engine/main.py:103-121`):**
```python
self.risk_params = RiskParams(
    max_daily_loss=self.config.get("risk.max_daily_loss_pct", 0.018),
    # ... 13 alan config'ten yüklenir
)
self.ogul = ogul or Ogul(..., risk_params=self.risk_params)
```
→ Engine.risk_params **config-loaded**. ogul parametresiz verildiyse Ogul da config-loaded risk_params alır.

**api/server.py yolu (`api/server.py:92-104`):**
```python
ogul = Ogul(config, mt5, db, baba=baba)   # risk_params argümanı YOK
engine = Engine(..., ogul=ogul)           # Engine'e zaten yaratılmış ogul verilir
```
→ Ogul.risk_params `RiskParams()` **default değerleri** alır.
→ Engine.__init__ yine çalışır ve `self.risk_params = RiskParams(config'ten...)` yapar, ama bu Engine-level risk_params Ogul'a set edilmez (ogul zaten var, `self.ogul = ogul or Ogul(...)` sağ taraf KULLANILMIYOR).

### D.4 — Gerçek runtime etki — drift alanları nerede kullanılıyor?

Drift olan 4 alan kodda nerede okunuyor:

| Drift alan | Kullanım noktası | risk_params kaynağı |
|---|---|---|
| `max_daily_loss` | `baba.py:check_drawdown_limits:1336` | **Engine.risk_params** (main.py:854'te geçilir) — config ✓ |
| `max_floating_loss` | `baba.py:_check_floating_loss:1899` | **Engine.risk_params** — config ✓ |
| `max_daily_trades` | `baba.py:check_risk_limits:1629` | **Engine.risk_params** — config ✓ |
| `cooldown_hours` | `baba.py:_start_cooldown:1977`, `_is_in_cooldown` | **Engine.risk_params** — config ✓ |

**Kritik bulgu:** BABA risk kontrolleri `main.py:_run_single_cycle:854`'teki `risk_verdict = self.baba.check_risk_limits(self.risk_params)` çağrısında **Engine.risk_params**'ı alıyor. Engine.__init__ her zaman config-loaded risk_params yaratıyor.

**Yani:** api/server.py yolunda Ogul'un kendi `self.risk_params`'ı default değerlerde olsa bile, BABA check_risk_limits **Engine.risk_params (config)** ile karar veriyor. Kritik risk kararları config değerlerine göre alınıyor.

### D.5 — OGUL'un kendi risk_params'ı nerede kullanılıyor?

**ogul.py:380** `self.risk_params = risk_params or RiskParams()` — init.

Kullanım noktaları:
| Satır | Fonksiyon | Hangi risk_params alanları? |
|---|---|---|
| 1735-1737 | `_execute_signal:calculate_position_size` | `risk_per_trade` (drift yok), `max_risk_per_trade_hard` (config'te yok), `max_position_size` (config'te yok), `consecutive_loss_limit` (drift yok) |
| 1769-1771 | `_execute_signal:check_correlation_limits` | `max_same_direction`, `max_same_sector_direction`, `max_index_weight_score` (hepsi config'te yok) |

**Kritik bulgu #2:** OGUL'un kendi `self.risk_params`'ı sadece:
- **Drift OLMAYAN** alanları (`risk_per_trade`, `consecutive_loss_limit`)
- **Config'te OLMAYAN** alanları (`max_risk_per_trade_hard`, `max_position_size`, `max_same_*`, `max_index_weight_score`)

... için kullanılıyor. **Drift olan 4 alan OGUL'un risk_params'ında kullanılmıyor.**

### D.6 — Finansal etki tahmini

**Şu anki durum (kod incelemesi):**

| Senaryo | Sonuç |
|---|---|
| api/server.py yolunda çalışan sistem BABA risk kontrolleri | **Config değerleri kullanılıyor** (Engine.risk_params). Drift etkisiz. |
| api/server.py yolunda OGUL lot hesabı | `risk_per_trade=0.01` (drift yok). Config değişikliği OGUL lot hesabına yansıyor dolaylı olarak (BABA.calculate_position_size OGUL.risk_params alıyor ama bu alanda drift yok) |
| api/server.py yolunda OGUL korelasyon kontrolü | `max_same_*` config'te yok, default kullanılıyor zaten — her iki yolda aynı davranış |
| Operatör config'te `max_daily_loss`'ı değiştirse (örn. 0.018 → 0.025) | BABA bunu **anında** okur (Engine.risk_params), OGUL'un self.risk_params'ı ilgisiz |

**Sonuç: Şu anki kod yollarında finansal etki minimal — sessiz drift var ama kritik karar noktalarında kullanılmıyor.**

### D.7 — Potansiyel gelecek risk

Kod bakımı sırasında biri **OGUL.process_signals** veya **OGUL._execute_signal** içine drift olan alanlardan birini kullanan bir kontrol eklerse, drift anında patlar. Örnek gelecek senaryo:

```python
# Hayali ilerideki bir değişiklik
def process_signals(self, symbols, regime):
    if self._risk_state.get("daily_auto_trade_count", 0) >= self.risk_params.max_daily_trades:
        # ↑ api/server.py yolunda max_daily_trades=8 (default, drift!)
        # main.py yolunda max_daily_trades=5 (config)
        return
```

Bu tür bir ekleme gelecek bir refactor'da yapılırsa → api/server.py yolunda günde 8 işlem, main.py yolunda 5 işlem → **tutarsız finansal davranış**.

### D.8 — İç tutarsızlık şu an var mı?

Var ama **kritik yerde değil:**

`engine/main.py:103-117` Engine.__init__ 13 config alanını RiskParams'a manuel map'liyor. Ama mapping'te 5 RiskParams alanı yok:
- `max_position_size` (config'te yok → default 1.0)
- `max_risk_per_trade_hard` (config'te yok → default 0.02)
- `max_same_direction` (config'te yok → default 3)
- `max_same_sector_direction` (config'te yok → default 2)
- `max_index_weight_score` (config'te yok → default 0.25)

Bu 5 alan **her iki kod yolunda aynı davranıyor** (default kullanılıyor). Tutarsızlık yok.

**Tek tutarsızlık:** Ogul.risk_params vs Engine.risk_params. Engine hep config-loaded, Ogul api/server.py yolunda default-loaded. Ama OGUL'un self.risk_params'ı drift alanlarında kullanılmıyor.

---

## BÖLÜM E — SONUÇ

### E.1 — KARAR #9 aciliyet seviyesi

**Önerilen sınıflandırma: ORTA (KISA VADEDE) / DÜŞÜK (CANLI PARA RİSKİ)**

**Gerekçe:**
1. **Şu an canlı para riski yok:** BABA kritik risk kontrollerini Engine.risk_params (config-loaded) ile yapıyor.
2. **Operasyonel tutarsızlık var:** api/server.py yolunda Ogul.risk_params ≠ Engine.risk_params. Kod kalitesi sorunu.
3. **Gelecek patlama riski var:** Kod bakımı sırasında drift alanlarını OGUL içinde kullanan bir kontrol eklenirse anında tutarsızlık ortaya çıkar. Savunma derinliği eksik.
4. **5 alan config'te hiç yok** (max_position_size, max_risk_per_trade_hard, max_same_direction, max_same_sector_direction, max_index_weight_score). Operatör bunları config'ten değiştiremiyor; kod değişikliği gerekli. Ayrı bir eksik — **KARAR #11 (R-11 sihirli sayı) kapsamında**.

### E.2 — En riskli drift alanı

**`cooldown_hours`:** default 2, config 4. Fark **%100 (2x)**.

Kritik çünkü:
- Default cooldown 2 saat — 3 ardışık kayıptan sonra sadece 2 saat bekleme
- Config cooldown 4 saat — operatör "4 saat beklenmeli" diyor
- Eğer OGUL gelecekte cooldown_hours'u okuyup kendi state'ine yazarsa (şu an BABA yapıyor), api/server.py yolunda sistem 2 saat sonra yeniden işlem açabilir

**`max_daily_trades`:** default 8, config 5. Fark **%37.5 (+3 işlem/gün)**.

Kritik çünkü:
- Default 8 işlem — operatörün istediğinden 3 fazla işlem/gün
- Eğer OGUL gelecekte bu alanı kullanırsa, günde 60% daha fazla işlem → daha fazla maliyet/risk

### E.3 — Önerilen eylem

**KARAR #9 Seçenek A (fabrika fonksiyonu) önerisi GEÇERLİ ama düşük aciliyetle.** Şu anki production'da canlı para riski yok, ama:

- Kod temiz yapılmalı (teknik borç)
- Gelecek bakım sırasında drift anında patlamasın diye savunma katmanı eklensin
- Ayrıca 5 RiskParams-only alanı (max_position_size, max_risk_per_trade_hard, max_same_direction, max_same_sector_direction, max_index_weight_score) config'e taşınsın — bu KARAR #11 genişletme olarak ele alınabilir

**Öncelik sırası revizyonu:**
- Faz 1 Critical Path'te KARAR #9 "Aşama 3: Finansal risk kapama" içinde listelenmişti.
- Ölçüm sonrası: KARAR #9 **"Aşama 4: Tutarlılık"**a indirgenmeli (KARAR #8 ile aynı aşama).
- Gerçek finansal risk yok; kod tutarlılığı ve gelecek koruma için çözülmeli.

### E.4 — Özet

**KARAR #9 gerçek aciliyet:**
- **Canlı para riski:** DÜŞÜK (mevcut kod yollarında drift alanları kullanılmıyor)
- **Kod kalitesi / teknik borç:** ORTA (iç tutarsızlık var, operatör config'i operasyonel ama ikinci yaratım yolu bunu ihmal ediyor)
- **Gelecek bakım riski:** YÜKSEK (drift alanları gelecekte OGUL'da kullanılırsa patlar)

**Faz 1 raporundaki "DOĞRUDAN finansal risk" sınıflandırması revize edilmeli:** KARAR #9 "DOLAYLI/GELECEK finansal risk" kategorisine taşınmalı.
