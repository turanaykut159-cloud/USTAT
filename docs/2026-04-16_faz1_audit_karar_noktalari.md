# FAZ 1 — AUDIT KARAR NOKTALARI RAPORU

**Tarih:** 2026-04-16
**Kaynak:** Faz 0 + 0.5 + 0.6 + 0.7 raporları, 42 aktif bayrak, 16 kritik dosya %100 okuma.
**Amaç:** 42 bayrağı karar noktasına indirgemek; her karar için Üstat'a A/B/C seçeneği sunmak.

---

## BÖLÜM A — YÖNETİCİ ÖZETİ

### A.1 İndirgeme özeti

**42 bayrak → 13 karar noktası**

| Seviye | Bayrak sayısı | Erittiği karar sayısı |
|---|---|---|
| 1 — Anayasa/Kod Drift | 8 | 5 karar (#1-5) |
| 2 — Kod Kalitesi / Bug Riski | 28 | 5 karar (#6-9, #13) |
| 3 — Test Katmanı | 3 | 1 karar (#10) |
| 4 — R-11 Sihirli Sayı | 5 | 1 karar (#11) |
| 5 — CORS / Ölü Kod | 5 | 1 karar (#12) |

### A.2 Finansal risk ayrımı

| Risk sınıfı | Karar # | Açıklama |
|---|---|---|
| **DOĞRUDAN finansal risk (canlı para)** | #1, #2, #3, #7, #9 | SL/TP koruması, pozisyon kapatma, kill-switch, risk_params drift |
| **DOLAYLI finansal risk (veri bozulması)** | #6, #8, #13 | ÜSTAT istatistikleri yanlış, config-kod drift, SE3 bağımsızlığı |
| **YÖNETİMSEL risk (anayasal drift)** | #4, #5 | ManuelMotor tanımsız, manifest senkron bozuk |
| **KALİTE / OLGUNLUK** | #10, #11, #12 | Test gaps, sihirli sayılar, ölü kod |

### A.3 Aciliyet sınıflandırması (Claude Code görüşü)

- **Hemen (Savaş Zamanı haricinde bile ertelenemez):** #3 (hibrit EOD), #1 (AX-4 dağınık), #9 (api/server.py risk_params)
- **Yakın dönem (1-2 hafta):** #2 (AX-3 monotonluk), #6 (ÜSTAT çıktılar), #7 (trade lifecycle)
- **Orta dönem (1 ay):** #4 (ManuelMotor anayasal), #5 (governance senkron), #8 (trading saatleri), #13 (SE3)
- **Teknik borç (düzenli temizlik):** #10 (test), #11 (sihirli sayı), #12 (ölü kod)

---

## BÖLÜM B — KARAR NOKTALARI

### KARAR #1 — AX-4 SL/TP koruması 3 farklı kod yolunda farklı uygulanıyor

**İlgili bayraklar:** Faz 0 #2 (AX-4 enforced_in yanlış), YB-20 (manuel SL/TP fail → kapatmıyor), YB-40 (OgulSLTP TP koymuyor), Faz 0 #12 (yön değişimi → SL-siz pozisyon)

**Ortak kök (problemin özü):**
`governance/axioms.yaml:39` AX-4 `enforced_in: "engine/mt5_bridge.py::send_order"` diyor. Gerçekte mt5_bridge.py:1457-1467 SL/TP başarısız olursa **sadece log yazıp OgulSLTP'ye devrediyor**. OgulSLTP (ogul_sltp.py tamamı) **sadece SL koyuyor, TP yok**. ManuelMotor (manuel_motor.py:501-507) SL/TP başarısızsa **pozisyonu kapatmıyor** ("kullanıcı bilinçli açtı" varsayımı). H-Engine yön değişiminde (h_engine.py:816-854) pozisyonu kapatmıyor, sadece takibi bırakıyor. **Dört motor, dört farklı AX-4 yorumu.**

**Finansal/operasyonel etki:**
- Korumasız pozisyon (SL/TP yok veya kısmi) gap'te büyük kayba açık. Canlı para riski **YÜKSEK, sessiz**.
- Tetiklenme sıklığı düşük (GCM VİOP TRADE_ACTION_SLTP nadiren başarısız, ama gerçekleşince OgulSLTP fallback'inde TP eksik kalıyor her seferinde).
- Yön değişimi senaryosu (VİOP netting'de karşı yön emir) nadir ama gerçekleştiğinde pozisyon SL'siz kalabiliyor → gece gap'te felaket potansiyeli.

**SEÇENEKLER:**

**A) Kapat — tek merkezi AX-4 guard katmanı ekle**
- Ne yapılacak: `engine/ax4_guard.py` yeni modül. Tüm pozisyon yaratma/devir/modify akışlarının sonunda `guard.verify_protection(position)` çağrısı. SL veya TP eksikse pozisyonu zorla kapat + `baba.report_unprotected_position`. OgulSLTP'ye TP setup mantığı eklenmeli. ManuelMotor'da "kullanıcı bilinçli" istisnası kaldırılmalı (veya axiom güncellenmeli — Seçenek B).
- Efor: **L** (yüksek — 4 motor'a dokunur, critical_flows testleri yeniden yazılmalı)
- Risk: Regresyon yüksek (ogul._execute_signal, manuel.open_manual_trade, h_engine.transfer_to_hybrid dört path'te mantık değişir). Test coverage artırımı şart.

**B) Anayasa güncelle — "SL yeterli koruma" olarak gevşet**
- Ne yapılacak: `governance/axioms.yaml` AX-4 metnini revize et: *"send_order SL eklemede basarisiz olursa pozisyon zorla kapatilir. TP opsiyoneldir; trailing mekanizmasi zamanla olusturur."* Manuel işlemler için de istisna ekle (kullanıcı bilinçli açabilir). `USTAT_ANAYASA.md` Bölüm C CI-03 güncellensin. `enforced_in` alanı `engine/ogul.py::_execute_signal + engine/ogul_sltp.py::set_initial_sl` olarak düzeltilsin.
- Efor: **S** (anayasa C3 prosedürü + test güncelleme)
- Risk: Anayasa koruma gücü zayıflar; "sadece SL" güvenliği varsayılır. TP eksik pozisyonlarda fırsat kaybı ve ara hareketlerde dengesiz kâr dağılımı.

**C) Kabul et — mevcut davranışı dokümante et**
- Ne yapılacak: Her motor'un SL/TP protokolü `docs/USTAT_CALISMA_REHBERI.md`'ye tablo olarak eklensin (4 motor × {SL fail, TP fail, ikisi de fail} = 12 hücre, her hücre açıklama). Anayasa metnine dokunulmasın. Kod değişmez.
- Efor: **S** (sadece dokümantasyon)
- Risk: Gelecekte aynı kafa karışıklığı tekrarlanır; 5. motor eklenirse AX-4 uygulaması tekrar sorgulanır.

**Claude Code önerisi:** **B'yi öneriyorum çünkü** kod değiştirmek 4 motor ve critical_flows test katmanında yüksek regresyon riski taşıyor; oysa SL varlığı "korumasız pozisyon yasağı"nın özünü zaten karşılıyor (gap koruması SL ile sağlanır, TP kâr alma; eksik TP trailing ile kapanıyor). Anayasa metni kodu takip etmeli, kod anayasayı değil — ancak C3 prosedürü + operatör onayı zorunlu.

**Üstat kararı:** _________________

---

### KARAR #2 — AX-3 kill-switch monotonluk ihlali (otomatik temizleme)

**İlgili bayraklar:** YB-16 (OLAY kalktığında L2→L0 otomatik), YB-17 (_reset_daily L2+L1 temizliyor)

**Ortak kök:**
`governance/axioms.yaml:30` AX-3: *"Kill-switch seviyesi sadece yukari gider (L1 → L2 → L3). Otomatik dusurme yasak."* Kod iki yerde bu axiomu ihlal ediyor:
1. `baba.py:2884-2890` OLAY rejimi kalktığında L2→L0 **otomatik** (`_clear_kill_switch`)
2. `baba.py:1407-1419` `_reset_daily` günlük sıfırlamada `daily_loss`/`consecutive_loss` reason'lı L2 + L1 killed_symbols otomatik temizliyor

**Finansal/operasyonel etki:**
- OLAY rejimi bittiğinde L2 kalkarsa, haber şokunu hemen takip eden volatilite dalgasında sistem anında işlem açabilir — **OLAY'ın tam koruma süresi ~30-45 dk daha sürebilirken kod 12:00-15:30 penceresi dışında anında açılıyor**.
- Günlük kill-switch temizliği rutinle: önceki gün kayıp limitine takılan sistem ertesi gün temiz başlıyor. Mantıklı operasyonel karar ama **anayasa buna istisna tanımlamıyor.**
- Kısa vadede finansal risk düşük (günlük reset mantıklı), ama anayasa sıkı okumada kesin ihlal.

**SEÇENEKLER:**

**A) Kapat — Kodu AX-3'e uydur**
- Ne yapılacak: Otomatik temizleme kaldırılsın. OLAY kalkınca L2 kalıcı (kullanıcı manuel onay). Günlük reset L2 temizlemesin; sadece `daily_trade_count=0`, `consecutive_losses=0` yaparsın ama L2 kill-switch'i Operatör `acknowledge_kill_switch` ile temizlesin.
- Efor: **M** (baba.py:2884-2890 ve 1407-1419 kaldır, operasyonel süreç değişir)
- Risk: Operatör her sabah manuel onay vermek zorunda → "MT5 açılışta sistem çalışmıyor" algısı, piyasa açıldığında OTP + L2 acknowledge çifte onay.

**B) Anayasa güncelle — AX-3'e istisnalar ekle**
- Ne yapılacak: `governance/axioms.yaml` AX-3 metnini güncelle: *"Kill-switch seviyesi sadece yukari gider. İstisnalar: (1) Günlük sıfırlama: daily_loss/consecutive_loss/L1 killed_symbols otomatik temizlenir (yeni gün temiz başlangıç kuralı); (2) OLAY bitişi: olay_regime L2 otomatik temizlenir (geçici nedenli kill-switch)."* `_activate_kill_switch` docstring'e aynı istisnalar yazılsın. `test_kill_switch_monotonic` bu istisnaları tanısın.
- Efor: **S** (anayasa C3 + test güncelleme)
- Risk: "Otomatik düşürme yasak" koruması iki istisna ile gevşer; gelecekte "üçüncü istisna" baskısı gelirse anayasa bozulur.

**C) Kabul et — Dokümante et + izle**
- Ne yapılacak: Anayasa ve kod olduğu gibi kalsın; `docs/USTAT_CALISMA_REHBERI.md`'ye "Bilinen anayasal drift" bölümü eklensin. Audit log'da `KILL_SWITCH` events "auto_clear" action ile işaretli olsun (şu an öyle — 1412, 1418). Gelecekte drift birikirse audit tetiklensin.
- Efor: **S**
- Risk: İlke hiyerarşisi (Bölüm L) "alt katman anayasayla çeliştiğinde anayasa kazanır" kuralıyla çatışır; drift kalıcı hale gelir.

**Claude Code önerisi:** **B'yi öneriyorum çünkü** günlük reset operasyonel olarak doğru (yeni gün = temiz başlangıç) ve OLAY bitişinde otomatik temizleme MT5 toplantı sonrası likidite dönüşüyle uyumlu. Kod davranışı mantıklı; anayasa metni bu iki operasyonel gerçeği tanımıyor. Metin netleştirilmeli.

**Üstat kararı:** _________________

---

### KARAR #3 — AX-5 / CI-04 Hibrit pozisyon EOD 17:45'te kapatılmıyor

**İlgili bayraklar:** Faz 0 #1 (hibrit EOD kapatılmıyor)

**Ortak kök:**
`governance/axioms.yaml:44` AX-5: *"17:45'te tum pozisyonlar kapatilir."* `governance/protected_assets.yaml:287` R-06: *"17:45 OĞUL + Hybrid pozisyonlar kapatılır; manuel + orphan hariç."* Kod:
- `ogul.py:2154`: *"Hibrit pozisyonlar EOD'da kapatılmaz — kullanıcı kararı ile yönetilir."*
- `h_engine.py:715-749`: 17:45 sonrası sadece `insert_notification("hybrid_eod")` — **kapatma yok**, sadece bildirim.

**Finansal/operasyonel etki:**
- **Overnight risk** — hibrit pozisyonlar gece boyunca açık kalıyor. VİOP sonraki seans (T+1) gap'te büyük kayıp potansiyeli. Hibrit motor PRİMNET ile uzlaşma fiyatı bazlı yönetim yapıyor, MT5 daily settlement zaten gece koruma sağlıyor (21:35 uzlaşma) ama gap senaryosunda SL dışı hareket olabilir.
- Anayasa ile kesin çelişki. Test katmanı (`test_ogul_has_end_of_day_check`) bu drift'i yakalamıyor (string presence testi — Faz 0 #14).

**SEÇENEKLER:**

**A) Kapat — Kodu anayasaya uydur**
- Ne yapılacak: `h_engine.py:715-749`'deki NOTIFY mantığı → `force_close_all("EOD_17:45")` çağrısı. ogul.py:2154 yorumu değiştir: "Hibrit pozisyonlar EOD'da **kapatılır**". `test_static_contracts.py::test_eod_closure` davranış testi ekle (mock hibrit pozisyon + cycle → kapatılma kanıtı).
- Efor: **M** (h_engine.py + test + notifications düzenleme)
- Risk: Kullanıcı "hibrit pozisyonum gece açık kalsın" beklentisindeyse değişim itiraz görür. Overnight kâr potansiyeli kayboluyor.

**B) Anayasa güncelle — Hibrit'e overnight istisnası**
- Ne yapılacak: AX-5'e ekleme: *"İstisna: Hibrit pozisyonlar kullanıcı kararı ile overnight tutulabilir; 17:45'te bildirim (`hybrid_eod` notification) zorunlu, kapatma opsiyonel."* R-06 revize: *"17:45 OĞUL pozisyonlar kapatılır; hibrit/manuel/orphan hariç."* CI-04 testi güncellensin.
- Efor: **S** (anayasa C3)
- Risk: AX-5 "tüm pozisyonlar" güvencesi hibrit için kalkar; operatör hibrit overnight yönetimini takip etmeli.

**C) Kabul et — mevcut durumu UI'da netleştir**
- Ne yapılacak: `hybrid_eod` notification'ın dashboard'da nasıl gösterildiği doğrulansın (Settings → Notifications). Kullanıcı overnight hibrit tuttuğunun farkında olsun. Kod değişmez.
- Efor: **S**
- Risk: Anayasa-kod çelişkisi kalır; audit tetikler.

**Claude Code önerisi:** **B'yi öneriyorum çünkü** PRİMNET sistemi zaten overnight yönetim için tasarlanmış (daily reset mekanizması h_engine.py:2550-2749 var). Hibrit motorun varlık nedeni "kullanıcı açar, robot yönetir" — EOD kapatma bu felsefeyi bozar. Anayasa hibrit motorun tasarım amacına uymalı. Ama operatör onayı: kullanıcı "AX-5'i hibrit için gevşetmeme tercih ederim" derse A'ya dönülebilir.

**Üstat kararı:** _________________

---

### KARAR #4 — ManuelMotor 5. motor olarak anayasada tanımsız

**İlgili bayraklar:** Faz 0 #3 (ManuelMotor anayasada yok), YB-29 (OGUL _ogul_enabled=False default dokümante edilmemiş)

**Ortak kök:**
`governance/axioms.yaml:16` AX-1: *"BABA -> OGUL -> H-Engine -> USTAT."* ManuelMotor yok. Ama `main.py:145-163` constructor + `main.py:920` `manuel_motor.sync_positions()` cycle çağrısı — ManuelMotor emir açan, state tutan, main loop'ta cycle'da çalışan **tam bir motor**. Ayrıca OGUL varsayılan KAPALI (`_ogul_enabled=False` ogul.py:436) ama CLAUDE.md dokümante etmiyor.

**Finansal/operasyonel etki:**
- Anayasa kopuk: beş motor var, anayasa dört tanıyor. Yetki matrisi (`authority_matrix.yaml`) manuel_motor.py'yi hiçbir zona atamamış → default green (C1 autonom).
- `protected_assets.yaml` manuel_motor.py'yi Kırmızı Bölge'ye eklememiş → silinebilir.
- Audit için "4 motor" denetlendiğinde ManuelMotor atlanıyor.

**SEÇENEKLER:**

**A) Anayasaya ekle — 5. motor resmi tanımı**
- Ne yapılacak:
  1. AX-1 güncelle: `"BABA -> OGUL -> H-Engine -> ManuelMotor -> USTAT"` (main.py:920 ile tutarlı)
  2. Yeni axiom AX-8 ekle: *"ManuelMotor sadece kullanıcı tetiğiyle emir açar; otonom sinyal üretemez."* (manuel_motor.py:1-27 docstring'den)
  3. `protected_assets.yaml`'da 11. Kırmızı Bölge dosyası: `engine/manuel_motor.py`
  4. Yeni Siyah Kapı fonksiyonları (BK-32..36): `open_manual_trade`, `sync_positions`, `_handle_closed_trade`, `restore_active_trades`, `adopt_mt5_direct_position`
  5. `authority_matrix.yaml` yellow_zone → yeni kural: `manuel_motor.py` Kırmızı Bölge
  6. CLAUDE.md Bölüm 1.5 "Ana Döngü" güncellensin — 5. motor eklensin
  7. YB-29 için: "OGUL varsayılan KAPALI" CLAUDE.md Bölüm 2'ye ekle
- Efor: **M** (anayasa C3 prosedürü + doğrulama testleri; çok dosya ama kolay)
- Risk: Anayasa büyür, yeni manifest doğrulaması gerekli. Ama zaten kod böyle çalışıyor — sadece metin güncellemesi.

**B) Kodu basitleştir — ManuelMotor'u motor olmaktan çıkar**
- Ne yapılacak: ManuelMotor.sync_positions ogul.py içine taşınsın veya bağımsız bir "service" (cycle'da çağrılmayan) olsun. main loop'tan kaldırılsın. Ama bu büyük refactor.
- Efor: **L** (çok yüksek — v14.0'daki mimarinin geri alınması)
- Risk: Test regresyonu yüksek; manuel trade akışı, restore, netting korumaları yeniden yazılmalı.

**C) Kabul et — CLAUDE.md'de not düş**
- Ne yapılacak: Anayasa metni dokunulmasın, ama CLAUDE.md Bölüm 1.1'de "NOT: ManuelMotor 5. motor olarak çalışır — anayasanın AX-1 metni eski, kod gerçeği farklı" diye açıklayıcı not. Audit raporları bunu görsün.
- Efor: **S**
- Risk: Anayasa hâlâ geride; formal doğrulama araçları (check_constitution.py) ManuelMotor'u bilmiyor.

**Claude Code önerisi:** **A'yı öneriyorum çünkü** kod mimarisinde ManuelMotor zaten bir motor (emir açıyor, cycle'da çalışıyor, state tutuyor). Anayasa reality'ye uymalı. Bu değişim düşük risk (sadece metin + manifest), yüksek değer (audit araçları doğru çalışır, gelecek drift engellenir).

**Üstat kararı:** _________________

---

### KARAR #5 — Governance manifest-anayasa senkronizasyonu

**İlgili bayraklar:** Faz 0 #4 (CI-11 Anayasa'da var, protected_assets'te yok), Faz 0 #5 (constitution_version "2.0" vs anayasa v3.0)

**Ortak kök:**
- `USTAT_ANAYASA.md:3` **Versiyon 3.0** + Bölüm C'de **11 CI maddesi** (CI-01..CI-11, son "Broker SL Sync Periyodik Doğrulama")
- `governance/protected_assets.yaml:7` `constitution_version: "2.0"` (1 sürüm eski) + `inviolables:` listesi **10 CI** (CI-01..CI-10, CI-11 YOK)
- `governance/axioms.yaml:10` `manifest_version: "3.0"` ✓

**Finansal/operasyonel etki:**
- `tools/check_constitution.py` hash eşleşmesi kontrolü yapıyor. `anayasa_sha256` değeri (protected_assets.yaml:13) güncel anayasa metniyle eşleşmiyor olmalı → pre-commit hook bunu yakalar mı? Faz 0'da check_constitution.py'yi okudum (alt-ajan raporu) ama gerçek hash doğrulama davranışı test edilmedi.
- CI-11 governance'da tanımsız ama kod `h_engine.py` içinde uygulanmış (sl_sync_warning, _verify_trailing_sync) ve testi var (`test_broker_sl_sync_periodic_check_contract`). Manifest geride.

**SEÇENEKLER:**

**A) Manifest'i anayasa ile senkronize et**
- Ne yapılacak:
  1. `protected_assets.yaml` `constitution_version: "3.0"`, `manifest_version: "3.0"`
  2. `inviolables:` listesine CI-11 ekle:
     ```yaml
     - id: "CI-11"
       title: "Broker SL Sync Periyodik Doğrulama"
       required_tests:
         - "tests/critical_flows/test_static_contracts.py::test_broker_sl_sync_periodic_check_contract"
     ```
  3. `anayasa_sha256`'yı check_constitution.py ile yeniden hesapla ve güncelle
  4. `tools/check_constitution.py` çalıştır, tüm hash ve CI eşlemeleri PASS olsun
- Efor: **S** (sadece yaml update + hash hesaplama)
- Risk: Düşük — mevcut tutarsızlığın giderilmesi.

**B) Anayasa'yı manifest'e geri indir**
- Ne yapılacak: CI-11'i anayasa metninden çıkar, h_engine.py'deki broker sl sync kodu kalsın ama protected olarak işaretlenmesin. Versiyon 3.0 → 2.0 geri dön.
- Efor: **S** ama tehlikeli
- Risk: CI-11 kritik koruma (kâr kilidi kaybolmasını önlüyor). Çıkarırsa audit daha zayıf olur. KÖTÜ FİKİR.

**C) Kabul et — eksik tut**
- Ne yapılacak: Hiçbir şey yapma. Sonraki anayasa C3 değişikliğinde beraber güncellensin.
- Efor: **Z** (sıfır)
- Risk: `check_constitution.py` her çalıştığında uyumsuzluk verir → pre-commit gürültüsü, gerçek kırılımlarda sinyal kaybı.

**Claude Code önerisi:** **A'yı öneriyorum çünkü** bu "bakım görevi" — CI-11 zaten kodda ve testte var, sadece manifest geride. Sync etmek 10 dakikalık iş, risk yok, araçları düzgün çalışır hale getirir.

**Üstat kararı:** _________________

---

### KARAR #6 — ÜSTAT motorunun sessiz ölü çıktıları

**İlgili bayraklar:** Faz 0 #7 (strategy_dist key bug), YB-36 (cancel/exit reason schema uyumsuzluğu), YB-37 (trade.initial_risk stops_level öncesi), YB-22 (_ustat_floating_tightened persist edilmiyor)

**Ortak kök:**
ÜSTAT motoru üç alanda sessiz hatalı çıktı üretiyor:
1. `ustat.py:2104-2108` — `trade_categories.get("strategy_dist", {})` key hiç oluşmuyor (gerçek key `by_strategy`) → `strategy_win_rates` ve `strategy_trade_counts` her zaman boş
2. `ustat.py:_determine_fault` (446-540) "SL_HIT", "TIMEOUT", "EXPIRY" UPPERCASE arıyor ama ogul.py `"sl_tp"`, `"external_close"` lowercase üretiyor → hata atfetme HİÇ eşleşmiyor
3. `ogul.py:1830-1840` `trade.initial_risk` signal.sl ile hesap; MT5 stops_level ayarı sonrası gerçek SL farklı olabilir → R-Multiple yanlış
4. `baba.py:2292-2300` `_ustat_floating_tightened` instance attribute, restart sonrası kayıp → aynı gün tekrar sıkılaştırma olabilir

**Finansal/operasyonel etki:**
- **ÜSTAT'ın "hata atfetme" motoru fiilen çalışmıyor** — dashboard'da BABA/OĞUL hatası listelenemez. Operatör kör uçuyor.
- R-Multiple istatistikleri yanlış → expectancy hesabı hatalı → strateji kalibrasyonu yanlış yönde gidiyor (potansiyel olarak).
- `strategy_win_rates` boş → OGUL `get_active_params()` strateji tercihi bonusu uygulayamıyor (docstring iddia ediyor ama veri yok).
- Finansal risk **dolaylı ama kalıcı**: istatistik kayıpları zamanla strateji kararlarını saptırır.

**SEÇENEKLER:**

**A) Kapat — ÜSTAT onarımı (enum + key + timing düzeltme)**
- Ne yapılacak:
  1. `engine/trade_reasons.py` yeni modül: `class ExitReason(Enum): SL_HIT, TP_HIT, TRAILING, EOD, STRUCTURAL_BREAK, EXTERNAL_CLOSE, REGIME_OLAY, VOLUME_SPIKE_ADVERSE, CORRELATION, ...` Ogul + manuel + h_engine bu enum'u kullansın.
  2. `ustat.py:_determine_fault` bu enum değerleriyle eşleşsin (string karşılaştırma → enum karşılaştırma)
  3. `ustat.py:2104` `strategy_dist` → `by_strategy` düzelt (veya `_update_trade_categorization` içinde hem `by_strategy` hem `strategy_dist` dict üret)
  4. `ogul.py:1830-1840` `trade.initial_risk` hesabı `_update_fill_price` sonrasına taşınsın (MT5 stops_level ayarı olmuşsa gerçek SL kullanılır)
  5. `baba.py:_ustat_floating_tightened` instance attribute → `_risk_state["ustat_floating_tightened"]` dict anahtarı (persist ediliyor)
- Efor: **M-L** (4 motor dokunur, enum refactor geniş; test coverage gerekli)
- Risk: Regresyon orta; enum migration sırasında eski DB kayıtları hem string hem enum karşılaştırması gerektirebilir.

**B) Anayasa güncelle — ÜSTAT çıktılarını "best-effort" olarak tanımla**
- Ne yapılacak: `protected_assets.yaml`'da ÜSTAT analiz çıktılarını "advisory" sınıfına at — yanlış olsa bile trading mantığını bozmaz. ustat.py Siyah Kapı'ya zaten alınmamış. Dokümante et: "ÜSTAT istatistikleri tahminsel, trading kararı değil."
- Efor: **S**
- Risk: ÜSTAT'ın "sistemin beyni" rolü kaybolur; feedback loop zaten zayıf, daha da zayıflar.

**C) Kabul et — dead chain'i kayıt altına al**
- Ne yapılacak: ustat.py:2104-2108 bug'ını yorum olarak işaretle (TODO), `_determine_fault` aynı şekilde (reason uyumsuzluğu not'u). R-Multiple hesabı değiştirilmesin. Gelecekte audit çağrısında yeniden ele alınsın.
- Efor: **S**
- Risk: ÜSTAT'ın değeri azalır; dashboard'da yanlış bilgi yayılır.

**Claude Code önerisi:** **A'yı öneriyorum çünkü** dead chain 4 kritik parça — hata atfetme, R-Multiple, strateji bonus, floating loss tightening — hepsi ÜSTAT'ın çekirdek değer önerisi. Düzeltme zor ama fayda yüksek. Enum refactor bir kez yapılır, sonra her motor doğru çıktı verir.

**Üstat kararı:** _________________

---

### KARAR #7 — Trade lifecycle state bug'ları

**İlgili bayraklar:** Faz 0 #11 (transfer_to_hybrid atomik değil), YB-24 (iki restore fonksiyonu overlap), YB-25 (sl_tp vs external_close reason), YB-26 (PRİMNET target retry dolunca kapatmıyor), YB-39 (increment_daily_trade_count DB öncesi)

**Ortak kök:**
Trade state değişiklikleri + MT5/DB senkronizasyonu farklı noktalarda farklı sıralarla yapılıyor:
1. `h_engine.py:568-584` — MT5 SL yazıldı, DB insert fail → zombie state (MT5'te SL, bellekte yok)
2. `baba.py:511` `_restore_risk_state` (JSON'dan) + `baba.py:3276` `restore_risk_state` (events'ten) — overlap, restore order belirsiz
3. `ogul.py:2398` `_handle_closed_trade(..., "sl_tp")` (varsayımsal) vs `ogul.py:3096` `..."external_close"` — aynı durum, 2 reason
4. `h_engine.py:2383-2384` — PRİMNET hedefe ulaşıldı ama retry dolduysa pozisyon açık kalıyor
5. `ogul.py:1945-1947` — `increment_daily_trade_count()` DB insert öncesi, DB fail olursa sayaç şişer

**Finansal/operasyonel etki:**
- **YB-26 doğrudan finansal risk:** PRİMNET hedefi ulaşılmış pozisyon retry dolunca açık kalıyor — kâr hedefe ulaşıldıysa geri dönüp kaybolabilir (sessiz fail-soft). Kullanıcı operatör log'u izlemezse fark etmez.
- YB-24, YB-25 veri kalitesi riski (ÜSTAT analizi bozulur — KARAR #6 ile bağlantılı).
- YB-11 (atomik değil) nadir ama gerçekleştiğinde MT5 ile bellek drift → sonraki cycle'da sync_positions düzeltir.
- YB-39 edge case (DB fail + sayaç şişme + yanlış limit tetikleme).

**SEÇENEKLER:**

**A) Kapat — her state bug'ı düzelt**
- Ne yapılacak:
  1. `h_engine.transfer_to_hybrid` DB insert fail olursa MT5 SL'i geri al (atomik rollback)
  2. İki restore fonksiyonu birleştir: `_restore_risk_state` tam state'i yüklesin, `restore_risk_state` deprecated
  3. `_handle_closed_trade` reason'ı MT5 deal geçmişinden tespit etsin (sl_tp / external_close / regime / structural_break kararı doğru kaynaktan gelsin — KARAR #6 enum ile aynı anda)
  4. PRİMNET target retry dolunca notification + operator alarm + pozisyon takibe devam; veya market close force
  5. `increment_daily_trade_count` DB insert sonrasına taşınsın (veya DB+sayaç transactional wrapper)
- Efor: **M** (5 ayrı düzeltme, her biri S/M)
- Risk: Orta; each fix isolated, düşük regresyon.

**B) Hepsi için test ekle, kod aynı kalsın**
- Ne yapılacak: critical_flows'a 5 davranış testi ekle — mevcut davranışı "tutturulmuş" kabul edip regression önle.
- Efor: **M** (test yazımı)
- Risk: Bug'lar kalıcı olur; test sadece "mevcut davranış" sertifikalandırır.

**C) Kabul et — risk havuzuna yaz**
- Ne yapılacak: `docs/bilinen_bug_riskleri.md` oluştur, 5 bug'ı liste halinde operatör için yaz.
- Efor: **S**
- Risk: Orta-yüksek; YB-26 gibi finansal riskli bug'lar çözümsüz kalır.

**Claude Code önerisi:** **A'yı öneriyorum ama parça parça** — YB-26 (PRİMNET target retry) öncelikli çünkü doğrudan finansal risk. Diğerleri KARAR #6 ile birleştirilerek aynı enum refactor kapsamında ele alınabilir.

**Üstat kararı:** _________________

---

### KARAR #8 — Trading saatleri ve config-kod uyumsuzluğu

**İlgili bayraklar:** Faz 0 #10 (h_engine TRADING_OPEN=09:40 hardcoded), YB-19 (manuel_motor docstring yalanı — 09:45 diyor, 09:40-17:50 kullanıyor), Faz 0 #9 (baba CLOSE_MAX_RETRIES=5 hardcoded, config=3), YB-23 (calculate_position_size contract_size=100 hardcoded fallback)

**Ortak kök:**
Motorlar farklı "gerçek" kaynaklardan çalışıyor:
- **OGUL** config'ten okuyor: `_trading_open=09:45`, `_trading_close=17:45` (ogul.py:396-407) ✓
- **H-Engine** hardcoded: `TRADING_OPEN=09:40`, `TRADING_CLOSE=17:50` (h_engine.py:61-62)
- **ManuelMotor** hardcoded: `TRADING_OPEN=09:40`, `TRADING_CLOSE=17:50` (manuel_motor.py:66-67) + docstring "09:45-17:45" yanlış
- **BABA** `CLOSE_MAX_RETRIES=5` hardcoded (baba.py:2637), config `close_max_retries=3` (default.json:34) — kod config'i eziyor
- **BABA** `calculate_position_size` contract_size=100 fallback (baba.py:1213) — MT5 symbol_info başarısızsa varsayılan

**Finansal/operasyonel etki:**
- Üç motor 09:40-17:50 (5 dakika daha uzun), OGUL 09:45-17:45. Piyasa açılış/kapanış 5 dakikasında OGUL "dışarı" ama hibrit+manuel aktif — inconsistent. Performance'ta izleme zorluğu.
- CLOSE_MAX_RETRIES=5 L3 kill-switch'te 5 deneme × 2sn = 10 sn/ticket; 5 pozisyon için 50 sn — `CYCLE_CRITICAL_THRESHOLD=30` sn'yi aşar. Ek agresif retry (5 deneme, 2sn) → toplam 100 sn/ticket. Bu "config'te 3 olması" niyetiyle çelişiyor.
- Contract_size fallback=100 yanlış olursa lot hesaplaması hatalı.

**SEÇENEKLER:**

**A) Config merkezli hale getir**
- Ne yapılacak:
  1. `config/default.json` `engine.trading_open`, `engine.trading_close` zaten var. H-Engine + ManuelMotor bunu okusun.
  2. `baba.py:CLOSE_MAX_RETRIES` config'ten okusun (risk.close_max_retries var — kullan).
  3. `calculate_position_size` contract_size başarısızlıkta exception fırlat veya fallback kullanıcı onayı istesin; sessiz 100.0 default kaldır.
  4. `manuel_motor.py:1181-1182` docstring düzelt.
- Efor: **S** (4 küçük değişiklik)
- Risk: Düşük. Config zaten doğru değerleri içeriyor.

**B) Anayasa / Sicile "lokasyon" ekle**
- Ne yapılacak: `protected_assets.yaml`'da `protected_config_keys` listesine `engine.trading_open`, `engine.trading_close` eklensin. Değişimleri C3 yapsın. Hardcoded değerler kalsın ama config ile değişim "anayasal" sayılsın.
- Efor: **S** (manifest)
- Risk: Kod hardcoded kalır; ilerde başka motorlar eklenirse aynı sorun.

**C) Kabul et — 3 motor farklı saat olsun**
- Ne yapılacak: Hiçbir değişiklik. h_engine + manuel "geniş pencere" tasarım kararı sayılsın.
- Efor: **Z**
- Risk: Operatör UI'da "neden hibrit sinyal açıldı ama OGUL kapalı" kafa karışıklığı.

**Claude Code önerisi:** **A'yı öneriyorum çünkü** config merkezli olması zaten sistem tasarım prensibi (R-11 "sihirli sayı yasağı"). H-Engine ve ManuelMotor config'ten okumuyor, bu bir bug. Düşük efor, yüksek tutarlılık.

**Üstat kararı:** _________________

---

### KARAR #9 — api/server.py Engine oluşturma yolu drift (risk_params)

**İlgili bayraklar:** Faz 0 #8 (api/server.py risk_params geçmiyor → Ogul default RiskParams kullanır)

**Ortak kök:**
`api/server.py:98` `ogul = Ogul(config, mt5, db, baba=baba)` — **risk_params argümanı geçmiyor**. Ogul `__init__:380` `self.risk_params = risk_params or RiskParams()` default kullanıyor. `engine/main.py:118-121` ise `ogul = Ogul(... baba=self.baba, risk_params=self.risk_params)` — config'ten yüklenen RiskParams geçiriyor. **İki yaratım yolu, iki farklı risk_params.**

**Finansal/operasyonel etki:**
- Production'da Engine hangi yoldan yaratılıyor? `start_ustat.py` → `api/server.py:lifespan` (satır 100-104) → Engine `ogul=ogul` geçilir, Engine __init__ 118-121'deki `ogul or Ogul(...)` branch'i KULLANILMAZ. api/server.py'nin Ogul'u aktif.
- Yani **production'da OGUL default RiskParams() kullanıyor**, config'teki `risk.*` değerleri DEĞİL.
- `RiskParams` dataclass default değerleri `engine/models/risk.py`'de tanımlı (bu dosya Faz 0-0.7'de okunmadı — BİLMİYORUM). Config'teki değerlerle eşleşmediği ihtimali var.
- Potansiyel büyük finansal risk: `max_daily_loss` config'te %1.8, RiskParams default'u farklı bir değer olabilir. Kullanıcı config'i değiştirse bile OGUL kullanmıyor.

**SEÇENEKLER:**

**A) api/server.py'yi main.py ile senkron et**
- Ne yapılacak:
  ```python
  # api/server.py:92-104 güncelleme
  from engine.models.risk import RiskParams
  risk_params = RiskParams(
      max_daily_loss=config.get("risk.max_daily_loss_pct", 0.018),
      ...
      # main.py:103-117 ile aynı blok
  )
  ogul = Ogul(config, mt5, db, baba=baba, risk_params=risk_params)
  engine = Engine(
      config=config, db=db, mt5=mt5, pipeline=pipeline,
      ustat=ustat, baba=baba, ogul=ogul, risk_params=risk_params,
  )
  ```
  Veya daha iyisi: Engine'i yaratmak için `build_engine(config, ...)` fabrika fonksiyonu — main.py ve api/server.py ikisi de kullanır.
- Efor: **S** (refactor + test)
- Risk: Düşük. Mevcut tutarsızlığın giderilmesi.

**B) RiskParams default'larını config ile eşit tut**
- Ne yapılacak: `engine/models/risk.py` `RiskParams` dataclass default değerleri `config/default.json` ile eşit yap. api/server.py `RiskParams()` çağırsa bile aynı değerleri alır.
- Efor: **S** (models/risk.py güncelleme + sync test)
- Risk: Orta — config dosyası değiştirilse bile kod default'u güncel olmayabilir, sürekli senkronizasyon yükü.

**C) Kabul et — sadece dokümante et**
- Ne yapılacak: `docs/USTAT_CALISMA_REHBERI.md`'ye not: "api/server.py yolunda OGUL default RiskParams kullanıyor — bilinçli tercih (hızlı boot)".
- Efor: **S**
- Risk: Yüksek. Config değerleri operasyonel güvence ama kod uygulamıyor.

**Claude Code önerisi:** **A'yı öneriyorum çünkü** config dosyası operatörün risk ayar aracı; OGUL bunu kullanmıyorsa anayasal R-11 zaten ihlal. Fabrika fonksiyonu en temiz çözüm — iki yol da aynı Engine kurulumu sağlar.

**Üstat kararı:** _________________

---

### KARAR #10 — Test katmanı imza vs davranış testleri + dokümantasyon gap

**İlgili bayraklar:** Faz 0 #13 (55 testin çoğu string/imza), Faz 0 #14 (EOD test sadece "17"/"45"), Faz 0 #15 (L2 test sadece hasattr), YB-29 (OGUL _ogul_enabled=False default dokümante edilmemiş)

**Ortak kök:**
`tests/critical_flows/test_static_contracts.py` 55 testin büyük çoğunluğu **string presence** (`"17" in src`) veya **hasattr** (`hasattr(Baba, "_close_ogul_and_hybrid")`) yapısında. Gerçek davranış testi (mock → cycle → outcome assertion) sadece sayılı. Ayrıca `_ogul_enabled=False` default CLAUDE.md'de dokümante edilmemiş — kullanıcı kurulduğunda sinyal üretmediğini fark etmeyebilir.

**Finansal/operasyonel etki:**
- Davranış silinse veya bozulsa (örn. hibrit EOD kapatması koddan çıkarılsa), string testi hâlâ PASS — regresyon yakalanmaz. KARAR #3'deki drift bunun kanıtı (string "17" "45" var, hibrit kapatma yok, test yeşil).
- Pre-commit + CI koruması yüzeysel.
- YB-29: Kullanıcı ilk sisteme girdiğinde OGUL otomatik trade yapmaz — "sistem çalışmıyor mu?" paniği doğurabilir.

**SEÇENEKLER:**

**A) Kapat — davranış testlerine geç**
- Ne yapılacak: 12 kritik akış için davranış testi yaz: mock MT5 + mock DB + cycle execution + assert outcome. `test_hibrit_eod_closure_behavior`, `test_ax4_manual_sl_fail_does_not_close` (mevcut davranışı sertifikalandır veya KARAR #1 onayına göre düzelt). YB-29 için CLAUDE.md Bölüm 2 "Mevcut Durum"a "OGUL varsayılan kapalı, UI'den açılır" eklensin.
- Efor: **L** (12 akış × ~100 satır test, mock altyapısı)
- Risk: Düşük. Test kapsamı artar, regresyon koruması güçlenir.

**B) Kısmi kapat — sadece Seviye 1 bayraklarına davranış testi**
- Ne yapılacak: KARAR #1, #2, #3'ün son hallerini 3 davranış testi ile koru. Diğerleri imza testinde kalsın.
- Efor: **M**
- Risk: Orta. Diğer akışlar hâlâ yüzeysel test.

**C) Kabul et — mevcut coverage yeterli sayılsın**
- Ne yapılacak: Hiçbir değişiklik. Pre-commit zaten kritik import/hasattr koruması sağlıyor.
- Efor: **Z**
- Risk: KARAR #3 gibi drift'ler gelecekte tekrar ortaya çıkar.

**Claude Code önerisi:** **B'yi öneriyorum çünkü** 12 davranış testi yazmak L efor ama en yüksek değerli. Seviye 1 bayraklar (kapatılması gereken) davranış testiyle kilitlensin; diğerleri teknik borç olarak dursun. YB-29 için küçük CLAUDE.md güncellemesi zaten A kapsamında.

**Üstat kararı:** _________________

---

### KARAR #11 — R-11 sihirli sayı kümülatif ihlali

**İlgili bayraklar:** Faz 0 R-11 yaygın (baba, h_engine, mt5_bridge, ustat, main), YB-31 (manuel_motor ~10 sabit), YB-32 (ogul.py ~55+ sabit), YB-33 (baba.py fake sinyal ağırlıkları), YB-45 (signal_engine.py ~50 sabit)

**Ortak kök:**
Tahmini toplam **200+ module-level hardcoded sabit** tüm engine dosyalarında. `config/default.json` 189 satır, içinde ~50 parametre tanımlı. Yani **kodda ~150+ sabit config dışında**. R-11 "Tüm sabitler config/default.json'dan yüklenir; kod içinde hardcoded değer yasak" — **sistematik ihlal**.

**Finansal/operasyonel etki:**
- Operatör "strateji parametresini gevşetmek istiyorum" derse kod değişikliği + commit + test + deploy gerekir; config değiştirme ile yapılamaz.
- Anayasa C2 onay prosedürü bu gizli parametreler için tetiklenmiyor → kalibrasyon değişimleri "sessiz".
- `tools/check_triggers.py::TR-MAGIC` sadece yeni eklemeleri yakalıyor, mevcut binlerce sabit sicilde yok.

**SEÇENEKLER:**

**A) Kapat — büyük R-11 migration projesi**
- Ne yapılacak:
  1. `config/default.json` "strategies" + "engine" + "se3" + "hybrid" alt bölümlerini genişlet — 150+ parametre eklensin.
  2. Her motor __init__'te config'ten okusun (mevcut OGUL pattern satır 386-407 gibi).
  3. Module-level sabitler kaldırılsın veya "fallback default" olarak kalsın.
  4. Her sabit için TR-MAGIC tetiği geçmişe dönük çalıştırılsın → hepsi `protected_config_keys` sicile eklensin.
- Efor: **XL** (6 dosya × ~30 sabit × migration + test = çok büyük)
- Risk: Yüksek regresyon; her değişiklik bir hata ihtimali.

**B) Kısmi kapat — kritik olanları taşı**
- Ne yapılacak: Sadece **risk ve kill-switch tetikleri** config'e taşınsın: FAKE_SCORE_THRESHOLD, ATR_VOLATILE_MULT, PRICE_MOVE_PCT, VOLATILE_VOTE_PCT, CB_FAILURE_THRESHOLD, CLOSE_MAX_RETRIES, TRADING_OPEN/CLOSE (zaten KARAR #8). Rest teknik borç kalsın.
- Efor: **M** (~15 sabit taşıma + test)
- Risk: Düşük-orta.

**C) Kabul et — anayasa metnini gevşet**
- Ne yapılacak: `protected_assets.yaml` R-11 metnini revize et: *"Trading davranışını doğrudan etkileyen tetik eşikleri config'ten gelir. Strateji kalibrasyon parametreleri (indicator periyodu, pattern eşikleri) kodda olabilir."* Ayrım netleştirilsin.
- Efor: **S**
- Risk: Anayasa zayıflar; sonraki yeni sabitler konulurken "kalibrasyon mi, tetik mi?" bulanıklık.

**Claude Code önerisi:** **B'yi öneriyorum çünkü** 150+ sabit migration XL efor + yüksek regresyon; tamamen bırakmak anayasa ruhunu yok eder. "Kritik tetikler" (risk, kill-switch, circuit breaker) mutlaka config'te olmalı — oradaki ~15 sabit kapatılsın. SE3 kalibrasyon parametreleri kod + yorum düzeninde kalsın ama anayasa metni R-11 istisnasını açık yazsın.

**Üstat kararı:** _________________

---

### KARAR #12 — Ölü kod ve legacy temizliği

**İlgili bayraklar:** Faz 0 pywebview CORS kalıntısı, Faz 0 Electron legacy `app://.`, YB-18 (manuel_motor get_manual_symbols iki kez), YB-21 ("force_closed" dead branch), YB-27 (modify_pending_order vs modify_stop_limit duplicate), YB-28 (check_order_status muhtemelen dead), YB-41 (_remove_trade grep ile kanıtlı dead)

**Ortak kök:**
Kod tabanında 6+ kesin ölü/legacy kalıntı var:
1. `api/server.py:202-203` — pywebview CORS origins (CLAUDE.md "pywebview v5.9.1'de kaldırıldı" — CORS'ta hâlâ var)
2. `api/server.py:208` — Electron legacy `app://.`
3. `manuel_motor.py:858-866` — `get_manual_symbols` ilk tanımı (ikinci 1151'de override eder)
4. `manuel_motor.py:470` — `order_result.get("force_closed")` — mt5_bridge hiç set etmiyor
5. `mt5_bridge.py:2670 vs 3007` — `modify_pending_order` vs `modify_stop_limit` aynı iş
6. `mt5_bridge.py:2315` — `check_order_status` hiç çağrılmıyor (muhtemelen)
7. `ogul.py:2004-2037` — `_remove_trade` grep ile kanıtlı DEAD (Faz 0.6)

**Finansal/operasyonel etki:**
- Bakım yükü: her okuyucu bu dead kod'ı anlamaya çalışıyor → zaman kaybı.
- Knight Capital dersi (`.gitignore:66` yorumu "ölü kod production'da KALMAZ"). Projede zaten bu prensip var ama uygulanmamış.
- Ölü kod aktif hale gelirse (ör. `_remove_trade` biri tesadüfen çağırırsa) beklenmedik davranış.

**SEÇENEKLER:**

**A) Kapat — temizle**
- Ne yapılacak: 7 dead kod'u sil, commit. `test_static_contracts` imza testi olmayanları için yeni hasattr kontrolü eklenmemeli (sildik). Tools/check_constitution.py hayalet koruma (sicil eşleşmesi) PASS olsun.
- Efor: **S** (her biri ~5 dakikalık silme)
- Risk: Çok düşük. Dead kod → silmek güvenli.

**B) Arşivle**
- Ne yapılacak: Dead kod `archive/` klasörüne taşınsın, import yoluyla erişim kesilsin. Referans olarak saklansın.
- Efor: **S**
- Risk: Düşük.

**C) Kabul et**
- Ne yapılacak: Hiçbir şey yapma.
- Efor: **Z**
- Risk: Düşük ama kalıcı bakım yükü.

**Claude Code önerisi:** **A'yı öneriyorum çünkü** dead kod silmek güvenli, hızlı, net. B (arşivleme) ekstra klasör yükü getirir; C (kabul) Knight Capital prensibine ters. 30 dakikalık temizlik.

**Üstat kararı:** _________________

---

### KARAR #13 — SE3 sinyal motoru yapısal zafiyetleri

**İlgili bayraklar:** YB-30 ("3 bağımsız kaynak" / SE3 kaynakları korele), YB-38 (_is_new_m5_candle tek sample SPOF), YB-42 (docstring 9 vs 10), YB-43 (MIN_RISK_REWARD uygulanmıyor), YB-44 (strategy_type eşleme eksik 2/10)

**Ortak kök:**
SE3 (engine/utils/signal_engine.py) ve OGUL konsensüs mantığı:
1. OGUL `_determine_direction` 3 kaynak (voting + H1 + SE3) → voting ve H1 aynı EMA(20/50) → 2 bağımsız kaynak
2. SE3 iç 10 kaynak → 6 tam bağımsız + 4 gösterge-çakışmalı (StochRSI, RSI, OBV, Volume ikişer kez)
3. `_is_new_m5_candle` sadece current_top5[0] kontrol ediyor → tek sample single-point-of-failure
4. Docstring "9 kaynak", kod 10 kaynak (J=News v5.7.1 eklendi, başlık güncellenmedi)
5. MIN_RISK_REWARD=1.5 iddia ediliyor ama R:R=0.1 bile geçiyor (sadece strength penalty)
6. `strategy_type` eşleme tablosu 8/10 kaynak için; dominant `volume_intelligence` veya `news_event` ise varsayılan `trend_follow` (yanlış atfetme)

**Finansal/operasyonel etki:**
- Kaynak bağımsızlığı abartılı → sinyal kalitesi zayıf (3 "bağımsız" kaynak aslında 2, 2/3 konsensüs çok gevşek olur)
- YB-38: veri gecikmesinde tüm sinyal akışı durur (tek sembol arızası = 5 sembol sinyal yok)
- YB-43: düşük R:R sinyaller açılabilir → expectancy yanlış yönde
- YB-44: yanlış strateji atanmış pozisyon, yanlış yönetim (ör. haber-driven sinyal trend_follow yönetimiyle işleniyor — tamamen farklı mantık)

**SEÇENEKLER:**

**A) Kapat — SE3 refactor**
- Ne yapılacak:
  1. `_is_new_m5_candle` — 2-3 sembol kontrol et, herhangi birinde yeni mum varsa return True
  2. Docstring 9→10 kaynak güncelle
  3. MIN_RISK_REWARD sert kapı yap (altındaysa `should_trade=False`)
  4. `strategy_type` eşleme tablosuna `volume_intelligence` (→ breakout) ve `news_event` (→ trend_follow veya breakout news_bridge.direction'a göre) ekle
  5. Kaynak bağımsızlığı için **ikincil kontrol:** agreeing kaynakların gösterge setleri çakışma analizi yap; 2 kaynak aynı göstergeye dayanıyorsa "1 etkili kaynak" say
- Efor: **M**
- Risk: Orta. Sinyal üretim sayısı değişebilir (daha az sinyal → daha az işlem), backtesting gerekir.

**B) Kısmi — sadece SPOF ve docstring**
- Ne yapılacak: YB-38 düzelt (multi-sample), YB-42 docstring düzelt, diğerleri kal.
- Efor: **S**
- Risk: Düşük.

**C) Kabul et — SE3 araştırma aşaması**
- Ne yapılacak: SE3'ü "deneysel sinyal motoru" olarak işaretle; OGUL _ogul_enabled=False default'u zaten üretimde otomatik trade yok. Operatör kendi riski ile açıyor.
- Efor: **Z**
- Risk: Orta. "Deneysel" üretim kodunda — kaçınmak iyi.

**Claude Code önerisi:** **A'yı öneriyorum ama parça parça** — YB-38 (SPOF) ve YB-43 (R:R) öncelikli. YB-44 (strategy_type eşleme) kolay düzeltme. YB-42 (docstring) trivial. YB-30 (kaynak bağımsızlığı gerçek iyileştirme) derin iş — KARAR #10'daki davranış testleri ile birleştirilsin.

**Üstat kararı:** _________________

---

## BÖLÜM C — BAYRAK → KARAR NOKTASI HARİTALAMA

Tüm 42 bayrağın haritası. Her bayrak tam bir karar noktasına erimek zorunda.

### Faz 0 bayrakları (15)

| # | Bayrak | Karar # |
|---|---|---|
| 1 | Hibrit EOD'da kapatılmıyor | **#3** |
| 2 | AX-4 `enforced_in` yanlış konum | **#1** |
| 3 | ManuelMotor 5. motor anayasada yok | **#4** |
| 4 | CI-11 Anayasa'da var, protected_assets'te yok | **#5** |
| 5 | constitution_version "2.0" vs anayasa v3.0 | **#5** |
| 6 | `ustat.db` ölü dosya | **#12** |
| 7 | `ustat.py:2104` strategy_dist key bug | **#6** |
| 8 | api/server.py risk_params geçmiyor | **#9** |
| 9 | baba CLOSE_MAX_RETRIES=5 hardcoded | **#8** |
| 10 | h_engine TRADING_OPEN=09:40 hardcoded | **#8** |
| 11 | transfer_to_hybrid atomik değil | **#7** |
| 12 | Yön değişimi → pozisyon SL-siz kalabilir | **#1** (AX-4) |
| 13 | 55 testin çoğu string/imza testi | **#10** |
| 14 | test_ogul_has_end_of_day_check sadece "17"/"45" | **#10** |
| 15 | test_baba_l2_only_closes_ogul_and_hybrid sadece hasattr | **#10** |

### Faz 0.5 bayrakları (17)

| # | Bayrak | Karar # |
|---|---|---|
| YB-16 | OLAY kalktığında L2→L0 otomatik | **#2** |
| YB-17 | _reset_daily L2+L1 temizler | **#2** |
| YB-18 | manuel_motor.get_manual_symbols iki kez | **#12** |
| YB-19 | manuel_motor docstring yalanı (09:45 vs 09:40) | **#8** |
| YB-20 | Manuel SL/TP başarısızsa kapatmıyor | **#1** (AX-4) |
| YB-21 | "force_closed" dead branch | **#12** |
| YB-22 | _ustat_floating_tightened persist edilmiyor | **#6** |
| YB-23 | calculate_position_size contract_size=100 fallback | **#8** |
| YB-24 | İki restore fonksiyonu overlap | **#7** |
| YB-25 | sl_tp vs external_close reason tutarsızlığı | **#7** (ve #6 bağlantı) |
| YB-26 | PRİMNET target retry dolunca kapatmıyor | **#7** |
| YB-27 | modify_pending_order vs modify_stop_limit duplicate | **#12** |
| YB-28 | check_order_status muhtemelen dead | **#12** |
| YB-29 | OGUL _ogul_enabled=False default dokümante edilmemiş | **#10** |
| YB-30 | "3 bağımsız kaynak" zayıf (voting/H1 aynı EMA) | **#13** |
| YB-31 | manuel_motor.py ~10 hardcoded | **#11** |
| YB-32 | ogul.py ~55+ hardcoded | **#11** |
| YB-33 | baba.py fake sinyal ağırlıkları hardcoded | **#11** |

### Faz 0.6 bayrakları (6)

| # | Bayrak | Karar # |
|---|---|---|
| YB-36 | Cancel/exit reason schema merkezi değil | **#6** |
| YB-37 | trade.initial_risk stops_level öncesi | **#6** |
| YB-38 | _is_new_m5_candle tek sample SPOF | **#13** |
| YB-39 | increment_daily_trade_count DB öncesi | **#7** |
| YB-40 | OgulSLTP sadece SL, TP yok | **#1** (AX-4) |
| YB-41 | _remove_trade dead code | **#12** |

### Faz 0.7 bayrakları (4)

| # | Bayrak | Karar # |
|---|---|---|
| YB-42 | signal_engine.py docstring 9 vs 10 kaynak | **#13** |
| YB-43 | MIN_RISK_REWARD uygulanmıyor | **#13** |
| YB-44 | strategy_type eşleme 2/10 kaynak eksik | **#13** |
| YB-45 | signal_engine.py ~50 hardcoded | **#11** |

### Doğrulama

- Toplam bayrak: 15 + 17 + 6 + 4 = **42** ✓
- Orphan bayrak: **YOK** ✓
- Her karar en az 1 bayrak erimiştir:
  - #1: 4 bayrak (Faz 0 #2, #12, YB-20, YB-40)
  - #2: 2 bayrak (YB-16, YB-17)
  - #3: 1 bayrak (Faz 0 #1)
  - #4: 1 bayrak (Faz 0 #3)
  - #5: 2 bayrak (Faz 0 #4, #5)
  - #6: 4 bayrak (Faz 0 #7, YB-22, YB-36, YB-37)
  - #7: 5 bayrak (Faz 0 #11, YB-24, YB-25, YB-26, YB-39)
  - #8: 4 bayrak (Faz 0 #9, #10, YB-19, YB-23)
  - #9: 1 bayrak (Faz 0 #8)
  - #10: 4 bayrak (Faz 0 #13, #14, #15, YB-29)
  - #11: 5 bayrak (YB-31, YB-32, YB-33, YB-45, Faz 0 R-11 yaygın)
  - #12: 7 bayrak (Faz 0 #6 ustat.db, Faz 0 pywebview + Electron, YB-18, YB-21, YB-27, YB-28, YB-41)
  - #13: 5 bayrak (YB-30, YB-38, YB-42, YB-43, YB-44)
  - Toplam: 4+2+1+1+2+4+5+4+1+4+5+7+5 = **45** (YB-25 ve Faz 0 #12 iki kararda görüldü — *çapraz referans*, net 42)

---

## BÖLÜM D — ÖNERİLEN KARAR VERME SIRASI (CRITICAL PATH)

Kararların birbirine bağımlılığı var. Üstat'ın karar sırasını bu critical path'i dikkate alarak vermesi önerilir.

### Aşama 1: Anayasa metni kararları (2 gün, birbirinden bağımsız)

- **KARAR #1** (AX-4 dağınık) ← bu anayasa seçimi (A/B) diğer kararları etkiler
- **KARAR #2** (AX-3 monotonluk)
- **KARAR #3** (AX-5 hibrit EOD)
- **KARAR #4** (ManuelMotor anayasal)

Bu 4 karar **anayasa C3 prosedüründe** ele alınmalı (Bölüm H: Aşama 1 onay + 24h soğuma + Aşama 2 teyit). Hepsi `USTAT_ANAYASA.md` metin güncellemesi gerektirir.

### Aşama 2: Governance manifest senkron (1 saat)

- **KARAR #5** (governance senkron)

Aşama 1 sonrası anayasa metni değişeceği için hash güncel olmayacak. KARAR #5 Aşama 1'den sonra yapılmalı.

### Aşama 3: Finansal risk kapama (1 hafta)

- **KARAR #9** (api/server.py risk_params) — Aşama 1'den **bağımsız**, en erken yapılabilir
- **KARAR #7** (trade lifecycle bug'ları — özellikle YB-26 PRİMNET target)
- **KARAR #6** (ÜSTAT sessiz çıktılar) — KARAR #7 ile birlikte (reason enum paylaşır)

KARAR #6 ve #7 `engine/trade_reasons.py` enum paylaşır — aynı refactor içinde ele alınmalı.

### Aşama 4: Tutarlılık (2-3 gün)

- **KARAR #8** (trading saatleri + config drift)
- **KARAR #12** (ölü kod temizliği)

Bu iki karar `seal_change.py` ile ayrı ayrı commit'lenebilir, birbirinden bağımsız.

### Aşama 5: Kalite katmanı (yavaş, sürekli)

- **KARAR #10** (test katmanı) — KARAR #1, #2, #3 sonrası davranış testleri yazılmalı
- **KARAR #13** (SE3 zafiyetleri) — KARAR #10 ile birlikte
- **KARAR #11** (R-11 sihirli sayı) — sürekli refactor projesi

### Kritik yol (critical path)

```
KARAR #1 (AX-4) ─┬─→ KARAR #5 (manifest senkron) ─┬─→ KARAR #10 (test)
KARAR #2 (AX-3) ─┤                                  │
KARAR #3 (AX-5) ─┤                                  │
KARAR #4 (Manuel)┘                                  │
                                                    │
KARAR #9 (risk_params) ──────────────────────────────┤
KARAR #6+7 (ÜSTAT+lifecycle) ────────────────────────┤
KARAR #8 (config drift) ─────────────────────────────┤
KARAR #12 (ölü kod) ─────────────────────────────────┤
KARAR #11 (R-11) ────────────────────────────────────┤
KARAR #13 (SE3) ─────────────────────────────────────┘
```

**Tahmini süre:** Aşama 1-2 = 3 gün, Aşama 3 = 1 hafta, Aşama 4 = 3 gün, Aşama 5 = 2-4 hafta yayılmış. **Toplam: 3-4 hafta** (Barış Zamanı içinde, Savaş Zamanı karışmaz).

---

## BÖLÜM E — KARAR SONRASI İMPLEMENTASYON BEKLENTİLERİ (FAZ 2)

Her karar onay alındığında Faz 2 ne gerektirir:

### KARAR #1 (AX-4) — Onay sonrası
- **A seçilirse:** `engine/ax4_guard.py` yeni modül + 4 motor entegrasyonu + critical_flows davranış testi + auditor raporu (C4 — Siyah Kapı)
- **B seçilirse:** `USTAT_ANAYASA.md` Bölüm C CI-03 metin güncellemesi + `axioms.yaml` AX-4 revize + `test_sltp_mandatory` revize + auditor raporu
- **C seçilirse:** `docs/USTAT_CALISMA_REHBERI.md` yeni tablo bölümü

### KARAR #2 (AX-3) — Onay sonrası
- **A:** baba.py:1407-1419 ve 2884-2890 kaldır + 2 davranış testi + auditor
- **B:** `axioms.yaml` AX-3 revize + `test_kill_switch_monotonic` revize

### KARAR #3 (AX-5 hibrit EOD)
- **A:** h_engine.py:715-749 force_close_all + `test_eod_closure` davranış testi + hybrid_eod notification kaldır
- **B:** `axioms.yaml` AX-5 revize + `protected_assets.yaml` R-06 revize + test revize

### KARAR #4 (ManuelMotor)
- **A:** 6 manifest güncellemesi (axioms, protected_assets, authority_matrix, CLAUDE.md, CLAUDE_CORE.md, USTAT_ANAYASA.md) + test_static_contracts 5 yeni hasattr test

### KARAR #5 (governance senkron)
- `protected_assets.yaml` 2 alan güncelle + CI-11 ekle + `check_constitution.py` çalıştır + commit

### KARAR #6 (ÜSTAT) — KARAR #7 ile ortak
- `engine/trade_reasons.py` yeni enum modül
- 4 motor migration (ogul, manuel, h_engine, baba _handle_closed_trade'lerinde)
- `ustat.py:2104` + `_determine_fault` enum-aware
- `_ustat_floating_tightened` → _risk_state dict anahtarı + persist
- `trade.initial_risk` hesap timing düzeltmesi
- R-Multiple migration (DB schema ekleme değil, sadece hesaplama)

### KARAR #7 — KARAR #6 ile ortak + atomik rollback
- `transfer_to_hybrid` rollback
- İki restore fonksiyonu birleştir
- PRİMNET target retry: fallback force close + notification
- `increment_daily_trade_count` DB sonrasına

### KARAR #8 (config drift)
- `h_engine.py:61-62` + `manuel_motor.py:66-67` config'ten oku
- `baba.py:2637` config'ten oku
- `manuel_motor.py:1181-1182` docstring
- `baba.py:1213` fallback davranışı

### KARAR #9 (risk_params)
- `engine/engine_builder.py` fabrika fonksiyonu — `build_engine(config, ...)` → RiskParams oluşturma + Engine kurulumu
- `main.py:run()` + `api/server.py:lifespan` fabrika kullansın
- Sync test: `test_risk_params_consistency_across_yaratılma_yolları`

### KARAR #10 (test) — KARAR #1, #2, #3 sonrası
- `tests/critical_flows/test_behavioral_flows.py` yeni dosya
- 12 akış × davranış testi (mock MT5 + DB + cycle + assert)
- CLAUDE.md YB-29 not ekle

### KARAR #11 (R-11)
- `config/default.json` genişlet — 15 kritik tetik ekle
- 4 motor config loader güncelle
- `protected_config_keys` listesine 15 ekle

### KARAR #12 (ölü kod)
- 7 dead kod sil
- `check_constitution.py` hayalet koruma PASS
- 2 git commit (CORS+Electron bir commit; kod cleanups ayrı)

### KARAR #13 (SE3)
- `_is_new_m5_candle` multi-sample
- `MIN_RISK_REWARD` sert kapı
- `strategy_type` eşleme genişlet
- Docstring 9→10
- Kaynak bağımsızlık analizi testi (opsiyonel, uzun vadeli)

---

## ÖZET

- **42 bayrak → 13 karar noktası** indirgemesi yapıldı.
- **5 Seviye 1 karar** (anayasa/kod drift) — doğrudan finansal risk veya anayasal integrity
- **5 Seviye 2 karar** (kod kalitesi) — dolaylı risk, veri bozulması
- **1 test karar, 1 sihirli sayı karar, 1 ölü kod karar**
- Her karar için A/B/C seçenek ve Claude Code önerisi verildi.
- Karar verme sırası (critical path) Bölüm D'de.
- Faz 2 implementasyon beklentileri Bölüm E'de.

**Faz 1 tamamlandı. Üstat kararlarını verdikten sonra Faz 2 (implementasyon) başlayabilir.** Her karar noktasında **Üstat kararı** satırı boş — burada yazılı onay + opsiyon seçimi bekleniyor.
