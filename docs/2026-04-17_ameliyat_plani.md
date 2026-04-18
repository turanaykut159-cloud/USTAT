# ÜSTAT v6.0 — HAFTA SONU AMELİYAT PLANI

**Tarih:** 2026-04-17
**Teşhis kaynağı:** `docs/2026-04-17_checkup_raporu.md`
**Zaman sınıfı:** Barış Zamanı (Cumartesi-Pazar 18-19 Nisan, hafta içi 20-24 dokunma YASAK)
**Planlama disiplini:** Anayasa Bölüm H C3 prosedürü — her anayasa değişikliği 24 saat soğuma + Aşama 2 teyit

---

## 0. AMELİYAT FELSEFESİ

### 0.1 Üç kural

1. **Tek seferde tek bıçak vuruşu.** Her ameliyat AYRI commit (`git revert` geri alabilsin). Birleştirmek = risk birleştirmek.
2. **Kanıt önce, değişiklik sonra.** Her ameliyatın "neden" cevabı kod:satır referansıyla belgelenmiş. Varsayım yasak.
3. **Savaş zamanında dikiş açılmaz.** Pazartesi 09:30-18:15 arası Kırmızı Bölge'ye dokunmak için "kanıtlı acil" yazılı onay gerekir.

### 0.2 Her ameliyatın standart 5 adımı

| Adım | İçerik |
|---|---|
| **A) Precondition** | Mevcut kod:satır okundu, branch temiz (`git status`), test yeşil, motor durdurulmuş veya Barış Zamanı |
| **B) Pre-flight** | `python tools/impact_map.py <dosya>` etki haritası çıkar, operatör onayı al |
| **C) Kesinti** | Tek atomik değişiklik — dosya/fonksiyon/satır belirli |
| **D) Doğrulama** | `python -m pytest tests/critical_flows -q` yeşil; davranış testi yazıldıysa o da yeşil |
| **E) Mühür** | `python tools/seal_change.py` 6-adımlı commit seremonisi; `USTAT_GELISIM_TARIHCESI.md` güncelle |

### 0.3 Geri alma standart protokolü

```bash
# Her ameliyat ayrı commit. Fail olursa:
git revert <commit_hash> --no-edit
python tools/seal_change.py  # Seremoniyi yine yürüt
# Sonra sorunu sormak için session raporu aç
```

---

## 1. P0 AMELİYATLARI — 18-19 NİSAN HAFTA SONU

**4 büyük ameliyat, tahmini 8-12 saat toplam süre, 2 güne yayılmış.**

---

### AMELİYAT #1 — AX-4 SL/TP Koruması Anayasasını Düzenle (KARAR #1)

**Tarih hedefi:** Cumartesi 18 Nisan sabah (Aşama 1)
**Anayasa Bölüm H C3 prosedürü — 24 saat soğuma gerekli**

#### 1.1 Sınıflandırma

- **Sınıf:** C4 (Siyah Kapı kodu + anayasa metni) — ÜÇLÜ ONAY (kanıt + plan + sonuç)
- **Bölge:** Kırmızı + Anayasa
- **Efor:** Dosya + Anayasa + Test — 4-6 saat

#### 1.2 Teşhis özeti

Faz 1 Karar #1'deki bulgu: 4 motor AX-4'ü 4 farklı şekilde uyguluyor:
- `mt5_bridge.send_order` (AX-4 manifest'te burada olduğu yazılmış) — SADECE LOG
- `ogul._execute_signal` (gerçek AX-4 koruma) — SL fail → close_position → report_unprotected
- `ogul_sltp.set_initial_sl` (OGUL fallback) — **SADECE SL, TP yok**
- `manuel_motor.open_manual_trade` — SL/TP fail → **pozisyon açık bırak** ("kullanıcı bilinçli")
- `h_engine` yön dönüşü → takibi bırak, pozisyon SL-siz kalabilir

#### 1.3 Seçilen opsiyon (Claude Code önerisi — Üstat onayı gerekli)

**OPSIYON B — Anayasa'yı kod gerçeğine uyumla (metni gevşet + enforced_in düzelt).**

Nedenler:
- A seçeneği (`engine/ax4_guard.py` merkezi guard) 4 motora dokunur — yüksek regresyon
- B seçeneği anayasa metnini kodla senkronlar — teknik borçlu daha az
- C seçeneği dokümantasyonla bırakmak — gelecek drift riski devam eder

#### 1.4 Detaylı adım listesi

**AŞAMA 1 (Cumartesi sabah) — Anayasa değişikliği teklifi**

1. **Precondition:**
   - Motor durmuş (`engine.heartbeat` 15 dk+ eski)
   - `git status` temiz, HEAD `master`'da
   - `python -m pytest tests/critical_flows -q` yeşil

2. **Pre-flight (impact):**
   ```bash
   python tools/impact_map.py engine/ogul_sltp.py
   python tools/impact_map.py engine/manuel_motor.py::open_manual_trade
   python tools/impact_map.py governance/axioms.yaml
   ```

3. **Dosya değişiklikleri:**

   **3a) `governance/axioms.yaml:36-40` AX-4 metin revizyonu:**
   ```yaml
   # ESKİ (AX-4):
   #   text: "send_order SL/TP eklemede basarisiz olursa pozisyon zorla kapatilir. Korumasiz pozisyon yasak."
   #   enforced_in: "engine/mt5_bridge.py::send_order"
   
   # YENİ (AX-4):
   id: "AX-4"
   text: |
     Otomatik sinyal ile acilan pozisyonlarda SL eklemede basarisiz olunursa pozisyon zorla kapatilir.
     TP opsiyoneldir; trailing mekanizmasi zamanla TP yerlestirir.
     Manuel pozisyonlarda kullanici bilincli oldugundan SL/TP fail pozisyon kapatma tetigi degildir
     — ancak `baba.report_unprotected_position` ile sicile kaydedilir.
     Hibrit devir yon degisimi durumunda pozisyon force_close_all ile kapatilir.
   enforced_in:
     - "engine/ogul.py::_execute_signal"
     - "engine/ogul_sltp.py::set_initial_sl"
     - "engine/manuel_motor.py::open_manual_trade"
     - "engine/h_engine.py::_handle_direction_change"
   ```

   **3b) `USTAT_ANAYASA.md` Bölüm C CI-03 güncellemesi** — aynı içerik narratif formda.

   **3c) `protected_assets.yaml:7` `constitution_version: "3.0"`** (KARAR #5 ile birlikte)

   **3d) `manuel_motor.py:481-507`** — Ekleme: SL/TP fail olduğunda BABA'ya bildirim
   ```python
   # YENİ — satır 495 civarı, uyarı bloğundan sonra:
   if not sl_tp_applied:
       try:
           self.baba.report_unprotected_position(
               symbol=symbol,
               ticket=position_ticket,
               source="manuel",
               reason="manual_sltp_fail_user_aware",
           )
       except Exception:
           logger.exception("BABA report_unprotected_position başarısız")
   ```

   **3e) `h_engine.py:816-854` yön dönüşü — force_close ekle:**
   ```python
   # ESKİ — sadece takibi bırakıyor
   # YENİ — eklenecek satır 850 civarı (remove_from_hybrid'den önce):
   self.force_close_one(hp.ticket, reason="DIRECTION_CHANGE_UNSAFE")
   ```
   (Bu force_close_one metodu var mı — ön kontrol: `Grep "def force_close" engine/h_engine.py`. Yoksa `force_close_all` listeyi filtrele.)

4. **Test:**
   ```bash
   python -m pytest tests/critical_flows -q --tb=short
   # 55 test yeşil kalmalı. Hiçbir test kırılmasın.
   ```
   
   **Yeni davranış testi yazımı (Aşama 2'de yapılacak):**
   - `test_manual_sltp_fail_reports_to_baba` — manuel.open_manual_trade mock'la SL/TP fail sağla, `baba.report_unprotected_position` çağrıldı mı kontrol
   - `test_hybrid_direction_change_force_closes` — yön dönüşü senaryosu mock'la, force_close çağrıldı mı

5. **Mühür:**
   ```bash
   git add governance/axioms.yaml USTAT_ANAYASA.md governance/protected_assets.yaml engine/manuel_motor.py engine/h_engine.py
   python tools/seal_change.py --class C4 --zone red --rationale "KARAR #1: AX-4 metni kod gerçeğine uyumlandırıldı (OpsB)"
   ```

6. **Kayıt:**
   - `docs/USTAT_GELISIM_TARIHCESI.md` — Changed: AX-4 anayasa metni güncellendi (manuel istisna + hibrit yön dönüşü force_close)
   - Session raporu: `docs/2026-04-18_session_raporu_ax4_normalize.md`

**AŞAMA 2 (24 saat sonra — Pazar 19 Nisan sabah) — Anayasa teyidi + davranış testleri**

Anayasa değişikliği Bölüm H gereği 24 saat soğumadan sonra tekrar doğrulanır:
- Cumartesi sabah değişiklik commit'lendi
- Pazar sabah ikincil kontrol: "Hala aynı kararda mısın?"
- Evet ise: davranış testleri commit edilir
- Hayır ise: `git revert` ile geri alınır

#### 1.5 Risk ve geri alma

**Risk seviyesi:** ORTA — anayasa metni değişimi büyük sonuç doğurabilir
**Geri alma:** `git revert <aşama1_commit>` → anayasa eski haline döner
**Savaş Zamanı tehdidi:** Bu değişiklik Pazartesi piyasa açılışından önce (18:15 Pazar - 09:30 Pazartesi pencerede) mühürlenmiş olmalı

---

### AMELİYAT #2 — Hibrit EOD Anayasa Düzenlemesi (KARAR #3)

**Tarih hedefi:** Cumartesi 18 Nisan öğleden sonra
**Süre:** 2-3 saat

#### 2.1 Sınıflandırma
- **Sınıf:** C3 (Kırmızı Bölge + anayasa metni)
- **Bölge:** `engine/h_engine.py` + `governance/axioms.yaml` AX-5 + `protected_assets.yaml` R-06

#### 2.2 Teşhis

`ogul.py:2154` yorumu ve `h_engine.py:715-749` kodu hibrit pozisyonları 17:45'te kapatmıyor — sadece `insert_notification("hybrid_eod")`. AX-5 metni "tüm pozisyonlar kapatılır" diyor. Kesin drift.

#### 2.3 Seçilen opsiyon

**OPSIYON B — Anayasa'ya hibrit istisnası ekle** (KARAR #3 öneri)

Nedenler:
- Hibrit motorun varlık nedeni = "kullanıcı açar, robot yönetir, overnight kalabilir"
- PRİMNET zaten overnight yönetim için tasarlanmış (daily settlement)
- A opsiyonu (kapatma uygula) hibrit motorun ruhunu bozar

#### 2.4 Adımlar

1. **Precondition + impact map** (Ameliyat #1 şablonu)

2. **`governance/axioms.yaml:42-46` AX-5 metin revizyonu:**
   ```yaml
   id: "AX-5"
   text: |
     17:45'te OGUL ve Manuel pozisyonlar kapatilir. Hibrit pozisyonlar istisnadir:
     kullanici karari ile overnight tutulur. 17:45'te `hybrid_eod` notification zorunlu.
     Daily settlement (21:35) PRIMNET ile uzlasma fiyati guncellenir;
     sonraki sabah gap senaryosunda CI-11 (Broker SL Sync) tetigi koruma saglar.
   enforced_in:
     - "engine/ogul.py::_check_end_of_day"
     - "engine/h_engine.py::run_cycle:715-749"
   ```

3. **`protected_assets.yaml` R-06 güncelle:**
   ```yaml
   # ESKİ: "17:45 OGUL + Hybrid kapatılır, manuel + orphan hariç"
   # YENİ: "17:45 OGUL kapatılır; hibrit kullanıcı opsiyonu (notification zorunlu); manuel + orphan hariç"
   ```

4. **`USTAT_ANAYASA.md` Bölüm C CI-04 güncelleme** — narratif format.

5. **Davranış testi (Aşama 2):**
   ```python
   # tests/critical_flows/test_behavioral_flows.py — yeni dosya
   def test_hybrid_eod_notification_without_close():
       """17:45'te hibrit pozisyon açık, notification emit ediliyor ama kapatılmıyor."""
       # mock: H-Engine + hibrit pozisyon + saat 17:45
       # assert: notification inserted
       # assert: position still open (force_close_all called=False)
   ```

6. **Mühür + kayıt** — Ameliyat #1 şablonu.

#### 2.5 Risk
- **Düşük** — Metin değişimi; kod zaten mevcut davranışta
- **Geri alma:** `git revert` ile anayasa eski haline

---

### AMELİYAT #3 — ManuelMotor Anayasal Tanıma (KARAR #4)

**Tarih hedefi:** Cumartesi 18 Nisan öğleden sonra (Ameliyat #2 ile aynı gün)
**Süre:** 2-3 saat

#### 3.1 Sınıflandırma
- **Sınıf:** C2 (anayasa yaml'ları + manifest)
- **Bölge:** governance/*.yaml + CLAUDE.md

#### 3.2 Teşhis

5. motor (ManuelMotor) kod içinde cycle'da çalışıyor, emir açıyor, state tutuyor — ama:
- `axioms.yaml:16` AX-1: sadece "BABA → OGUL → H-Engine → USTAT"
- `protected_assets.yaml` Kırmızı Bölge listesinde yok (11. dosya eklenmeli)
- Siyah Kapı BK listesinde yok (yeni BK-32..36)
- `authority_matrix.yaml` yellow_zone'a girmemiş
- OGUL `_ogul_enabled=False` default CLAUDE.md'de dokümante edilmemiş (YB-29)

#### 3.3 Seçilen opsiyon

**OPSIYON A — Anayasa'ya 5. motor resmi tanımı ekle**

#### 3.4 Adımlar

1. **Precondition + impact map**

2. **`governance/axioms.yaml:16` AX-1 güncelle:**
   ```yaml
   id: "AX-1"
   text: "Ana dongu sirasi SABIT: BABA -> OGUL -> H-Engine -> ManuelMotor -> USTAT"
   enforced_in: "engine/main.py::_run_single_cycle"
   ```

3. **Yeni axiom AX-8:**
   ```yaml
   id: "AX-8"
   text: |
     ManuelMotor sadece kullanici tetigi (UI butonu, /api/manual_trade) ile emir acar.
     Otonom sinyal uretemez. Main loop'ta her cycle sync_positions ile MT5 senkronu tutulur.
   enforced_in: "engine/manuel_motor.py::open_manual_trade, sync_positions"
   ```

4. **`protected_assets.yaml`:**
   - Kırmızı Bölge listesine 11. dosya ekle: `engine/manuel_motor.py`
   - Siyah Kapı BK-32..36 ekle:
     ```yaml
     - id: "BK-32"
       file: "engine/manuel_motor.py"
       function: "open_manual_trade"
     - id: "BK-33"
       function: "sync_positions"
     - id: "BK-34"
       function: "_handle_closed_trade"
     - id: "BK-35"
       function: "restore_active_trades"
     - id: "BK-36"
       function: "adopt_mt5_direct_position"
     ```

5. **`authority_matrix.yaml` yellow_zone** — `engine/manuel_motor.py` Kırmızı Bölge tanımı, refactor yasak hücresi

6. **`CLAUDE.md` güncelle:**
   - Bölüm 1.1 tablosu: 4 motor → 5 motor
   - Bölüm 1.5 ana döngü: ManuelMotor adımı eklensin
   - Bölüm 2.1 veya yeni bölüm: "OGUL varsayılan KAPALI — UI'den açılır" not

7. **`CLAUDE_CORE.md` + `USTAT_ANAYASA.md` senkronize**

8. **`tests/critical_flows/test_static_contracts.py` yeni 5 hasattr testi (C1):**
   ```python
   def test_manuel_motor_has_open_manual_trade(): ...
   def test_manuel_motor_has_sync_positions(): ...
   # vb.
   ```

9. **Mühür + kayıt**

#### 3.5 Risk
- **Düşük** — Sadece manifest ve doküman değişimi, kod değişmiyor
- **Geri alma:** `git revert`

---

### AMELİYAT #4 — Governance Manifest Senkron (KARAR #5)

**Tarih hedefi:** Cumartesi 18 Nisan akşam (Ameliyat #3 ile aynı gün, hızlı)
**Süre:** 1 saat

#### 4.1 Sınıflandırma
- **Sınıf:** C0 (sadece YAML sync + hash)
- **Bölge:** `governance/protected_assets.yaml`

#### 4.2 Adımlar

1. **Değişiklikler:**
   - `constitution_version: "2.0"` → `"3.0"`
   - `manifest_version: "3.0"` (zaten)
   - `inviolables:` listesine CI-11 ekle:
     ```yaml
     - id: "CI-11"
       title: "Broker SL Sync Periyodik Dogrulama"
       required_tests:
         - "tests/critical_flows/test_static_contracts.py::test_broker_sl_sync_periodic_check_contract"
     ```
   - `anayasa_sha256` yeniden hesapla:
     ```bash
     python -c "import hashlib; print(hashlib.sha256(open('USTAT_ANAYASA.md','rb').read()).hexdigest())"
     ```

2. **Doğrulama:**
   ```bash
   python tools/check_constitution.py
   # PASS olsun
   python -m pytest tests/critical_flows -q
   # 55 yeşil kalmalı
   ```

3. **Mühür + kayıt**

#### 4.3 Risk
- **Çok düşük** — Hash + version + test referansı
- **Geri alma:** `git revert`

---

### AMELİYAT #5 — ÜSTAT Dead Chain Tamiri (KARAR #6)

**Tarih hedefi:** Pazar 19 Nisan sabah-öğle
**Süre:** 4-6 saat (en uzun P0 operasyonu)

#### 5.1 Sınıflandırma
- **Sınıf:** C2 (Yeşil/Sarı — ustat.py yeşil, enum yeni dosya, ogul.py reason eki Kırmızı)
- **Bölge:** Birden fazla

#### 5.2 Teşhis

ÜSTAT öğrenme motoru 4 ayrı soğuk damar var (Organ 11 muayenesi):
- `ustat.py:2104-2108` `strategy_dist` key yok (gerçek key `by_strategy`)
- `ustat.py:_determine_fault` UPPERCASE reason arıyor (SL_HIT), ogul.py lowercase üretiyor (sl_tp)
- `ogul.py:1830-1840` `trade.initial_risk` stops_level öncesi hesap
- `baba.py:_ustat_floating_tightened` persist edilmiyor

#### 5.3 Seçilen opsiyon

**OPSIYON A — Enum refactor ile tüm damarları bir seferde aç** (KARAR #6 öneri)

#### 5.4 Adımlar

1. **Precondition + impact map** (özellikle ogul.py reason çağrıları geniş)

2. **Yeni dosya `engine/trade_reasons.py`:**
   ```python
   from enum import Enum
   
   class ExitReason(Enum):
       SL_HIT = "sl_hit"
       TP_HIT = "tp_hit"
       TRAILING = "trailing"
       END_OF_DAY = "end_of_day"
       STRUCTURAL_BREAK = "structural_break"
       EXTERNAL_CLOSE = "external_close"
       REGIME_OLAY = "regime_olay"
       REGIME_VOLATILE_LOSS = "regime_volatile_loss"
       VOLUME_SPIKE_ADVERSE = "volume_spike_adverse"
       KILL_SWITCH_L2 = "kill_switch_l2"
       KILL_SWITCH_L3 = "kill_switch_l3"
       MANUAL_USER_CLOSE = "manual_user_close"
       DIRECTION_CHANGE_UNSAFE = "direction_change_unsafe"
   
   class CancelReason(Enum):
       CORRELATION = "correlation"
       OUTSIDE_TRADING_HOURS = "outside_trading_hours"
       CONCURRENT_LIMIT = "concurrent_limit"
       MARGIN_INSUFFICIENT = "margin_insufficient"
       SEND_ORDER_FAILED = "send_order_failed"
       SL_PLACEMENT_FAILED = "sl_placement_failed"
       SL_AND_CLOSE_FAILED = "sl_placement_failed_and_close_failed"
   ```

3. **`ustat.py:_determine_fault` enum karşılaştırma:**
   ```python
   # ESKİ: if reason in ("SL_HIT", "TIMEOUT", "EXPIRY"): ...
   # YENİ:
   from engine.trade_reasons import ExitReason
   reason_enum = ExitReason(reason) if isinstance(reason, str) else reason
   if reason_enum in (ExitReason.SL_HIT, ...):
       ...
   ```

4. **`ustat.py:2104` `strategy_dist` → `by_strategy` düzelt:**
   ```python
   # ESKİ: strat_dist = self.trade_categories.get("strategy_dist", {})
   # YENİ:
   strat_dist = self.trade_categories.get("by_strategy", {})
   ```
   (Ama `by_strategy` değerleri dict mi int mi kontrol et — eğer int ise veri şemasını da düzelt.)

5. **`ogul.py` reason atamalarını enum ile değiştir:**
   - Satır 2342: `"regime_olay"` → `ExitReason.REGIME_OLAY.value`
   - Satır 2399: `"sl_tp"` → `ExitReason.SL_HIT.value` (bu satır zaten değişiyor çünkü doğru olan "sl_hit")
   - Satır 3096: `"external_close"` → `ExitReason.EXTERNAL_CLOSE.value`
   - 2152: `"end_of_day"` → `ExitReason.END_OF_DAY.value`
   - Diğerleri...

6. **`ogul.py:1830-1840` `trade.initial_risk` timing düzeltmesi:**
   ```python
   # MT5 stops_level ayarı send_order içinde olur
   # initial_risk hesabı send_order sonrası, actual SL ile yapılmalı
   # YENİ:
   if R_MULT_TRACK_ENABLED and trade.sl > 0 and trade.entry_price > 0:  # trade.sl = actual SL
       risk_pts = abs(trade.entry_price - trade.sl)
       trade.initial_risk = risk_pts * lot * contract_size
   ```

7. **`baba.py:2292-2300` `_ustat_floating_tightened` persist:**
   ```python
   # ESKİ: setattr(self, feedback_key, True)
   # YENİ:
   self._risk_state["ustat_floating_tightened"] = True
   # _persist_risk_state zaten _risk_state'i yazıyor
   ```

8. **Test:**
   ```bash
   python -m pytest tests/critical_flows -q
   # 55 yeşil
   # Manuel test: mock trade ile _determine_fault doğru atfetme yapıyor mu?
   ```

9. **Mühür + kayıt**

#### 5.5 Risk

- **ORTA-YÜKSEK** — 4 motor reason üretiyor, enum migration geniş
- **Strategy_dist fix:** by_strategy değerleri dict mi int mi kontrol gerekli
- **DB'de geçmiş trades reason=lowercase string** — migration sadece gelecek için, eski veri `_determine_fault` yeni kodla uyumlu değil → opsiyonel migration query
- **Geri alma:** `git revert` ile commit geri alınır; enum dosyası silinir

#### 5.6 Kabul kriterleri

- Pazartesi sabah ilk trade kapandığında `_determine_fault` doğru motor bulduğunu event log'da göreceğiz
- `_ustat_floating_tightened` state restart sonrası korunuyor mu — test ile
- `ustat.get_active_params()` `strategy_win_rates` dolu dict dönüyor mu

---

## 2. P0 AMELİYAT ÖZETİ

| # | Ameliyat | Sınıf | Efor | Risk | Tarih |
|---|---|---|---|---|---|
| 1 | AX-4 metni + manuel istisna + hibrit yön force_close | C4 | 4-6 sa | Orta | Cmt sabah (Aşama 1) + Paz sabah (Aşama 2) |
| 2 | Hibrit EOD anayasa revizyon | C3 | 2-3 sa | Düşük | Cmt öğleden sonra |
| 3 | ManuelMotor 5. motor tanımı | C2 | 2-3 sa | Düşük | Cmt öğleden sonra |
| 4 | Governance manifest senkron (CI-11, v3.0) | C0 | 1 sa | Çok düşük | Cmt akşam |
| 5 | ÜSTAT dead chain tamiri (enum refactor + 4 bug) | C2-C3 | 4-6 sa | Orta-yüksek | Paz sabah-öğle |

**Toplam tahmini süre:** 13-19 saat (iki güne bölünmüş — cmt 8-11 sa, paz 4-6 sa)

**Toplam commit sayısı:** 5-7 (her ameliyat 1-2 commit)

---

## 3. P1 AMELİYATLARI — 25-26 NİSAN 2. HAFTA SONU

### AMELİYAT #6 — AX-3 Kill-Switch Monotonluk (KARAR #2)
- OPSIYON B: Anayasa'ya istisnalar ekle (günlük reset + OLAY bitişi)
- `axioms.yaml` AX-3 metni güncelle + test ekle
- Efor: S

### AMELİYAT #7 — Trade Lifecycle Bug'ları (KARAR #7)
- `transfer_to_hybrid` rollback ekle (MT5 SL geri al)
- `_handle_closed_trade` reason MT5 deal history'den tespit etsin
- PRİMNET target retry dolunca force_close + notification
- `increment_daily_trade_count` DB insert sonrasına
- 2 restore fonksiyonu birleştir (`_restore_risk_state` kalır, `restore_risk_state` deprecated)
- Efor: M

### AMELİYAT #8 — api/server.py Engine Builder (KARAR #9)
- Yeni dosya: `engine/engine_builder.py` `build_engine(config, ...)` fabrika
- main.py ve api/server.py ikisi de kullansın
- Test: `test_risk_params_consistency_across_build_paths`
- Efor: S

### AMELİYAT #9 — Trading Saatleri Config Drift (KARAR #8)
- `h_engine.py:61-62`, `manuel_motor.py:66-67` config'ten okusun
- `baba.py:2637 CLOSE_MAX_RETRIES` config'ten
- `baba.py:1213` contract_size fallback exception
- `manuel_motor.py:1181-1182` docstring düzelt
- Efor: S

---

## 4. P2 AMELİYATLARI — MAYIS BOYUNCA

### AMELİYAT #10 — Davranış Testleri Yazımı (KARAR #10)

**Öncelik sırası:**
- P0 ameliyatlarının her biri için davranış testi (Aşama 2'de yazılır)
- `test_hybrid_eod_notification_without_close`
- `test_manual_sltp_fail_reports_to_baba`
- `test_hybrid_direction_change_force_closes`
- `test_ogul_reason_matches_ustat_fault_enum`
- vb.

Efor: L (2-4 hafta yayılmış, her davranış 1-2 saat)

### AMELİYAT #11 — SE3 Zafiyetler (KARAR #13)
- `_is_new_m5_candle` multi-sample (en az 3 sembol kontrol)
- `MIN_RISK_REWARD` sert kapı (`should_trade=False` R:R<1.5 ise)
- `strategy_type` eşleme genişlet (volume_intelligence → breakout, news_event → news-driven veya breakout)
- Docstring 9→10 kaynak
- Efor: M

### AMELİYAT #12 — R-11 Kritik Tetikler Config'e Taşı (KARAR #11 OPSIYON B)

`config/default.json` genişlet (~15 kritik tetik):
- `baba.fake_signal_weights` (SPREAD/VOLUME/MULTI_TF/MOMENTUM + THRESHOLD)
- `baba.regime_thresholds` (ADX, ATR mult, price move pct)
- `mt5_bridge.circuit_breaker` (failure_threshold, cooldown, probe_timeout)
- `mt5_bridge.retry_budgets` (deal_lookup, ticket, sltp)
- `main.cycle` (interval, warn, critical thresholds)

Efor: M

---

## 5. P3 AMELİYATLARI — BAKIM

### AMELİYAT #13 — Ölü Kod Temizliği (KARAR #12)

7 parça sil, 2 commit:
- `git commit -m "chore: remove dead CORS legacy (pywebview, electron app://)"`
- `git commit -m "chore: remove unused functions (get_manual_symbols v1, force_closed branch, modify_pending_order, check_order_status, _remove_trade)"`

Efor: S

### AMELİYAT #14 — Docs Drift Tamiri

- `CLAUDE.md` + `CLAUDE_CORE.md` başlık v6.0'a güncelle
- Endpoint sayısı 20 → 23
- Bileşen sayısı 20 → 21
- Komut sayısı 37 → 53, satır 3686 → 3781
- `ustat.db` ölü dosya notu ya sil ya dokümante
- 19 tablo listesi güncelle (backtest_bars, error_resolutions ekle)
- Desktop productName "v5.7" → "v6.0"

Efor: S

### AMELİYAT #15 — DB Yedek Retention Politikası

- Sadece günde 1 yedek tutulsun (`database.py` retention güncelle)
- Eski 3 günlük yedekler ile çalış, 7+ gün silinsin
- Disk alan: ~200 MB tasarruf

Efor: S

---

## 6. HAFTA İÇİ DİSİPLİNİ (20-24 NİSAN)

**Savaş Zamanı — Pazartesi-Cuma 09:30-18:15:**

1. **Kırmızı Bölge DOKUNMA.** İstisna: P0 ameliyatı yarım kaldıysa ve hatası tespit edildiyse → yazılı onay + tek değişiklik.
2. **İzleme görevleri:**
   - Her sabah `engine.heartbeat` + `api.pid` kontrol
   - Sabah premarket `logs/premarket_briefing_*.json` oku
   - 18:15 sonrası `logs/ustat_YYYY-MM-DD.log` digest (ERROR + CRITICAL)
   - Gün sonu `trades.db` son kapanışlar + ÜSTAT feedback kontrol
3. **P0 ameliyat etki ölçümü:**
   - AX-4 drift kapandıktan sonra `baba.report_unprotected_position` çağrılarını izle
   - Hibrit EOD notification işliyor mu?
   - ÜSTAT `_determine_fault` event'lerde motor atfetmesi yapıyor mu?
4. **Kanıt topla:** Herhangi P1 ameliyatı için ek kanıt bulursan not et (docs/2026-04-17_checkup_raporu.md teşhislerini güçlendir)
5. **Hiçbir yeni feature eklenmez.** Sadece bug fix (kanıtlı) + log + monitoring.

---

## 7. BAŞARI KRİTERLERİ

### Pazartesi 20 Nisan piyasa açılışı kontrolü:

| Gösterge | Beklenen | Kanıt |
|---|---|---|
| AX-4 manuel SL/TP fail senaryosu | `report_unprotected_position` çağrısı event log'da | `events WHERE event_type='UNPROTECTED_POSITION'` |
| ÜSTAT `_determine_fault` işliyor | Dashboard "motor_fault" sütunu dolu | `events WHERE event_type='ERROR_ATTRIBUTION'` |
| Hibrit EOD notification | 17:45'te `hybrid_eod` type notification | `notifications WHERE type='hybrid_eod'` |
| `strategy_win_rates` dolu | OGUL `get_active_params()` çıktısı boş dict değil | API `/api/ustat-brain` yanıtı |
| `check_constitution.py` PASS | Pre-commit yeşil | `pre-commit` çıktısı |

### Nisan sonu (P1 sonrası):
- `engine_builder.py` hem main hem api/server kullanıyor
- `transfer_to_hybrid` rollback test edilmiş
- AX-3 anayasa metni istisna tanımlı

### Mayıs sonu (P2 sonrası):
- 12 davranış testi yazılmış, pre-commit'te
- SE3 R:R sert kapı aktif
- 15 kritik tetik config'te

---

## 8. ÖZET

Bu hafta sonu **5 büyük ameliyat, 13-19 saat, 5-7 commit**. Üçü anayasa metni değişimi (C3 prosedürü, 24 saat soğuma zorunlu). Biri manifest senkron (trivial). Biri kod refactor (enum migration — en uzun).

Pazartesi piyasa açılışına kadar sistem **5 önemli tıkanıklığı açılmış** şekilde girer. Bu doğrudan finansal risk azaltır (AX-4 asimetrisi + ÜSTAT dead chain + hibrit EOD) ve anayasal integrity sağlar (ManuelMotor resmiyeti + manifest senkron).

**Hafta içi sadece izleme — Barış Zamanını 25-26 Nisan'a sakla.**

---

**Referanslar:**
- Teşhis: `docs/2026-04-17_checkup_raporu.md`
- Karar noktaları: `docs/2026-04-16_faz1_audit_karar_noktalari.md` (13 karar, Üstat kararları boş)
- Kanıt dosyaları: Faz 0, 0.5, 0.6, 0.7 raporları (42 bayrak detayı)
- Anayasa prosedür: `USTAT_ANAYASA.md` Bölüm H
- Etki haritası aracı: `python tools/impact_map.py <dosya>`
- Commit seremonisi: `python tools/seal_change.py`
- Rollback: `tools/rollback/commit.sh`
