# OP-D Ön Hazırlık Raporu: AX-4 SL/TP Zorunluluğu
**Tarih:** 19 Nisan 2026, Pazar 08:00-12:00
**Sınıf:** C4 (Siyah Kapı + anayasa metni)
**Süre:** 4 saat
**Karar:** KARAR #1

---

## A. DÖRT MOTOR ÖZGÜL FIX (PROBLEM + ÇÖZÜM + KODLAR)

### Fix S1-1: axioms.yaml enforced_in Manifest Yanlış Konum
**Mevcut bug:** Satır 39, `enforced_in: "engine/mt5_bridge.py::send_order"` yazılı ama gerçek SL/TP koruma `ogul.py:_execute_signal` (satır 1648-1943)'de.
- mt5_bridge.send_order (satır 1280-1490): SADECE LOG atiyor, kapatmıyor.
- Anayasa manifest yanlış yöne işaret ediyor = test coverage boşluğu.

**Doğru davranış:**
- OGUL sinyal SL/TP eklemede başarısızsa → close_position çağrı → report_unprotected_position
- Fallback SL olarak STOP LIMIT emrleri (OgulSLTP) kullanılır

**Kod değişiklikleri:**
1. `governance/axioms.yaml:39` — enforced_in listesi çoklu noktaya:
   ```yaml
   enforced_in:
     - "engine/ogul.py::_execute_signal"
     - "engine/ogul_sltp.py::set_initial_sl"
     - "engine/manuel_motor.py::open_manual_trade"
     - "engine/h_engine.py::_handle_direction_change"
   ```
2. Manifest doğrulama testi: `tests/critical_flows/test_ax4_manifest.py` — enforced_in her nokta fonksiyonda mevcutsa pass

**Edge case'ler:**
- Netting modda position_ticket bulunması 20 retry (mt5_bridge:1364) — başarısızsa ERR log + force close
- STOP LIMIT emrinin kendisi reject olursa (GCM VİOP modunda) → log warning, pozisyon korumasız kalabilir
- Cascade: SL fail → report → BABA kayıt → sistem uyarı (UI)

---

### Fix S1-2: OgulSLTP Sadece SL, TP Yok
**Mevcut bug:** Satır 1-361, set_initial_sl (satır 130-166) ve update_trailing_sl (satır 172-261) VAR, **TP seti metodu YOK**.
- OgulSLTP STOP LIMIT (SL koruma) yapıyor, TP trailing değil
- AX-4 metni "SL/TP eklemede başarısız olursa" → TP fallback'te başka yerde

**Doğru davranış:**
- OGUL stratejiler M15 mum kapatışında signal.tp sağlarsa, STOP LIMIT değil LIMIT emri gönderil
- TP trailing: OGUL update_profit_protection (ayrı flow)

**Kod değişiklikleri:**
1. `ogul_sltp.py` docstring (satır 1-21) düzelt: "TP mekanizması ayrı; ogul.py trailing ile yönetilir"
2. Yeni metot set_initial_tp (satır 165 sonrası): LIMIT emri gönderme (Python kod struktur sağlanır)
3. ogul.py:_execute_signal (satır 1800-1820) — TP fail davranış dökümante: "TP optional, trailing timeout'a kadar bekle"

**Edge case'ler:**
- TP fiyatı bid/ask spread'i içindeyse LIMIT reddedilir → timeout sonrası trailing takılır
- Volume match: SL ile TP aynı lot mu? OgulSLTP volume match (satır 148)

---

### Fix S1-3: Manuel SL/TP Fail → Kapatmıyor
**Mevcut bug:** Satır 481-507, if not sl_tp_applied: bloğu LOG warning atiyor ama KAPATMIYOR. Yorumda "kullanıcı bilinçli" (satır 506).
- Position açık, korumasız → reporte veri gelmesi + manual intervention risk
- Anayasa "korumasız pozisyon yasak" diyor = CONTRADICTION

**Doğru davranış:**
- SL/TP MT5 modify fail → force close yerine BABA'ya rapor
- Manuel trade = operatör sorumluluğu artık yüksek, ancak sistem kaydını tutar
- KARAR #1: Manuel istisna metin olur (baba.report_unprotected_position çağrılır)

**Kod değişiklikleri:**
1. manuel_motor.py:481-507 — Replace satır 501-507 warning (report_unprotected_position ekle)
2. USTAT_ANAYASA.md (CI-03) — "manuel istisna paragrafi" 
3. Test: test_manual_sltp_fail_reports_unprotected

**Edge case'ler:**
- Position zaten kapatılmışsa (partial close) → ticket=0 → report skip
- BABA başarısız → log ama devam (fail-silent rule, UI bildirim yeterli)

---

### Fix S1-4: Hibrit Yön Dönüşü → SL-siz Kalıyor
**Mevcut bug:** Satır 816-854, VİOP netting yön değişim algılanıyor (satır 817: if mt5_direction != hp.direction), ama:
- Bekleyen SL emirleri iptal (satır 823: _cancel_stop_limit_orders)
- Pozisyon KAPATILMIYOR → yeni yöndeki pozisyon SL-siz devam ediyor
- Sadece h_engine takibini bitiyor (satır 828: _finalize_close)

**Doğru davranış:**
- Yön dönüşü = kontrol kaybı (netting modda karşı yöne açılan emir)
- Pozisyon force_close → kapatılmalı

**Kod değişiklikleri:**
1. h_engine.py:816-854, satır 823 sonrası ekle: mt5.close_position force_close
2. USTAT_ANAYASA.md — "yön dönüşümün güvenli kapanış tetikler"
3. Test: test_hybrid_direction_change_force_closes

**Edge case'ler:**
- Force close başarısız (ör. market kapalı) → alert user, pozisyon tuzak
- Volume desync: MT5'de 16 lot, h_engine'de 10 lot → close_position volume param ile tam close
- Cascading: direction_flip event → kill-switch L1 tetiklemeyecek mi? (ayrı araştırma)

---

## B. DEPENDENCY SIRALAMA (S1-1 → S1-4 Doğrulama)

| Sıra | Fix | Gerekçe | Bağlantı |
|------|-----|---------|---------|
| 1 | S1-1 (axioms manifest) | Test coverage setup — enforced_in doğru işaret etmeliydi | Başlangıç |
| 2 | S1-2 (ogul_sltp TP metodu) | S1-1 testleri TP fallback araştırınca bulunur | S1-1 test yazımında tespit |
| 3 | S1-3 (manuel SL/TP fail report) | S1-1 enforced_in manuel_motor'u ekler → report() fonksiyon gerekli | S1-1 enforced_in listesi |
| 4 | S1-4 (hibrit yön dönüşü force_close) | S1-3 manuel fallback = force_close pattern örnek | Pattern tutarlılık |

**ONAY:** Sıra **doğru**. Önerilen S1-1 → S1-2 → S1-3 → S1-4 uygun.

---

## C. HER FIX İÇİN COMMIT MESAJI (Conventional Commits)

```
1. Fix S1-1 (axioms manifest):
   fix(ax4): enforced_in manifest 4 motora doğru işaret
   
   AX-4 SL/TP koruma gerçek konumu: mt5_bridge::send_order LOG-only, 
   gerçek: ogul::_execute_signal + fallback ogul_sltp::set_initial_sl + 
   manuel_motor::open_manual_trade + h_engine yön dönüşü.
   
   enforced_in liste 1 noktadan 4 noktaya güncellendi. Test coverage 
   boşluğu kapatılmış (axioms manifest doğrulaması).
   
   Fixes: S1-1

2. Fix S1-2 (ogul_sltp TP metodu):
   feat(ogul_sltp): TP Limit emri desteği ve docstring revizyonu
   
   OgulSLTP STOP LIMIT (SL) gönderiyordu, TP trailing separate flow 
   (ogul.update_profit_protection). TP Limit fallback opsiyonu eklenmesi 
   (set_initial_tp metodu) AX-4 TP coverage'ı tamamlar.
   
   - Yeni set_initial_tp(trade, tp) metodu
   - Docstring: "TP ayrı trailing mekanizması"
   - Edge case: LIMIT reject → timeout trailing

   Fixes: S1-2

3. Fix S1-3 (manuel SL/TP fail report):
   fix(manuel_motor): SL/TP başarısız → BABA report
   
   Manuel trade SL/TP fail'de force close yerine 
   BABA.report_unprotected_position çağrısı. Anayasa manuel istisna: 
   operatör bilinci, sistem kaydı.
   
   - Satır 505: report_unprotected_position ekle
   - Log info + error handling
   - AX-4 metin revizyonu: manuel istisna paragrafi

   Fixes: S1-3

4. Fix S1-4 (hibrit yön dönüşü force_close):
   fix(h_engine): yön dönüşü → force_close (SL-siz kalanma önle)
   
   Netting modda yön dönüşü (ör. SELL 16 → BUY 4) h_engine takibini 
   bitiriyor ama MT5 pozisyonu SL-siz kalıyordu. Force close eklenmiş.
   
   - Satır 823 sonrası: mt5.close_position(force)
   - Log info/error
   - AX-4 metin: "yön dönüşü force_close_all"

   Fixes: S1-4
```

---

## D. RISK MATRİSİ (C4 SIYAH KAPI + ÇIFT DOĞRULAMA)

| Motor | Fonksiyon | C4? | Çift Doğrulama? | Kanıt |
|-------|-----------|-----|-----------------|-------|
| OGUL | _execute_signal (satır 1648) | ✓ | **GEREKLI** (SL/TP fail → close) | Raporun §5.4 Auditör-1 |
| OgulSLTP | set_initial_sl + NEW set_initial_tp | ✓ | **GEREKLI** (fallback koruma) | CI-11 test + impact_map |
| Manuel | open_manual_trade (satır 465) | ✓ | **GEREKLI** (report fail) | Auditör-1 onayı |
| H-Engine | yön dönüşü block (satır 816) | ✓ | **GEREKLI** (force_close safety) | Auditör-1 + health check |
| MT5 Bridge | close_position generic | ✓ | **GEREKLI** (trade iptali risk) | MT5 API kontrol |

**Raporun §4 Siyah Kapı tablosu (satır 300-340) referans:**
- #1: check_risk_limits — bu fix'de referans değil
- #12: _execute_signal — **BU FIX'DE VURDU** (satır 1648)
- #17: send_order — mt5_bridge, Log-only (fix değil, dökümante)

**Çift doğrulama kural:** C4 fix commit edilmeden:
1. Auditör-1 (motor logic) kontrol ✓
2. Impact_map.py etki doğrulama ✓
3. Test yeşil + davranış testi yeni ✓
4. Üstat insan onayı ✓

---

## E. TEST GAP ANALIZI

### Mevcut testler (tests/critical_flows/test_static_contracts.py)
- ✓ satır 39-49: test_send_order_has_two_phase_sltp — SL/TP ekleme logic
- ✓ satır 51-80: test_sltp_failed_triggers_close — OgulSLTP fallback check
- ✓ satır 2182-2254: Widget SL/TP gösterim (UI)
- ✓ satır 3457-3500: Broker SL sync periodic (CI-11)

### Eksik testler (OP-D kapsamında yeni yazılacak)
1. **test_ax4_enforced_in_manifest**
   - governance/axioms.yaml AX-4.enforced_in 4 nokta var mı?
   - Her nokta Python importlib ile bulunuyor mu?
   - Test dosya: tests/governance/test_ax4_manifest.py

2. **test_manual_sltp_fail_reports_to_baba**
   - manuel_motor.open_manual_trade() mock → SL/TP fail sağla
   - baba.report_unprotected_position çağrıldı mı?
   - Parametreler: source="manual", reason="sltp_failure" ✓

3. **test_ogul_sltp_tp_fallback**
   - set_initial_tp(trade, tp) emri gönder
   - Limit emri MI yerleştirildi?
   - trade.tp_order_ticket atandı mı?

4. **test_hybrid_direction_change_force_closes**
   - Yön dönüşü mock (mt5_pos.type != hp.direction)
   - SL emirleri iptal edildi mi?
   - MT5 close_position çağrıldı mı?

5. **test_ax4_asimmetry_edge_cases**
   - Netting ticket lookup fail (20 retry → err) → force close ✓
   - STOP LIMIT reject (GCM VİOP) → warning log ✓
   - Cascade: SL fail → report → BABA alert ✓

---

## F. ANAYASA METIN REVİZYON

### USTAT_ANAYASA.md AX-4 bölümü

**Mevcut metin:**
> CI-03: AX-4 "Korumasız pozisyon yasak: send_order SL/TP başarısız → pozisyon ZORLA kapatılır"

**Revize metin:**
> CI-03: AX-4 "SL/TP Zorunluluğu (motor-spesifik)"
> - Otomatik sinyal (OGUL): SL eklemede başarısız → close_position + baba.report
> - TP: Trailing mekanizması async (optional initial Limit); timeout sonrası update_profit_protection
> - Manuel trade: SL/TP fail → baba.report_unprotected_position (operatör bilinci, sistem kaydı)
> - Hibrit yön dönüşü: MT5 force_close (SL koruma kaybı)
> Koruma: ogul::_execute_signal + ogul_sltp::set_initial_sl + manuel_motor::open_manual_trade + h_engine

### governance/axioms.yaml AX-4 enforced_in revizyonu
```yaml
- id: AX-4
  name: "SL/TP Zorunluluğu"
  statement: |
    Otomatik sinyal ile açılan pozisyonlarda SL eklenmesi zorunlu.
    SL başarısız → korumasız olarak mark edilir + baba.report.
    TP optional; trailing opsiyoneldir.
    Manuel trade: operatör bilinci (sistem kaydı tutulur).
    Hibrit yön dönüşü: force_close tetikler.
  enforced_in:
    - "engine/ogul.py::_execute_signal"
    - "engine/ogul_sltp.py::set_initial_sl"
    - "engine/manuel_motor.py::open_manual_trade"
    - "engine/h_engine.py::_handle_direction_change"
  violation_response: "LOG + baba.report_unprotected_position + UI alert"
```

---

## G. SÜRE VE AŞAMA ÖNERİSİ

**4 fix saat tahminleri:**
1. S1-1 (axioms manifest + test setup): **45 dk** (dosya edit + test skelet simple)
2. S1-2 (ogul_sltp TP metodu + docstring): **75 dk** (yeni metot yazma + unit test)
3. S1-3 (manuel report): **45 dk** (satır 505 ekle, try-catch, log, test mock)
4. S1-4 (hibrit force_close): **45 dk** (close_position entegrasyonu, edge case, test)

**Toplam: 210 dakika = 3.5 saat ✓ (4 saatlık slot'a sığıyor, 30 dk buffer)**

### Aşama önerisi: **TEK OTURUM UYGUN**

Neden:
- 4 fix bağımsız (farklı dosyalar, motor benzeri kontekst)
- Test'ler sequential çalışabilir (pytest batching)
- Seal_change.py seremoni 1× (tüm commit'ler toplanabilir)
- 24h cooldown teknik gerekçe değil

### Tavsiye zaman çizelgesi (Pazar 08:00-12:00)
- **08:00-08:45:** S1-1 precondition + impact map + axioms.yaml edit
- **08:45-10:00:** S1-2 ogul_sltp.py set_initial_tp yazma + docstring
- **10:00-11:00:** S1-3 manuel_motor report ekle + test mock
- **11:00-12:00:** S1-4 h_engine force_close + test + seal_change seremoni

---

## İMPLEMENTASYON KONTROL LİSTESİ

- [ ] Precondition: motor durmuş, git status temiz
- [ ] Impact_map koştur (4 dosya)
- [ ] S1-1: axioms.yaml enforced_in = 4 nokta
- [ ] S1-1: test_ax4_manifest.py yazıldı
- [ ] S1-2: ogul_sltp.py set_initial_tp metodu
- [ ] S1-2: docstring "TP ayrı trailing"
- [ ] S1-3: manuel_motor.py report_unprotected_position
- [ ] S1-3: test_manuel_sltp_fail_reports
- [ ] S1-4: h_engine close_position force ekle
- [ ] S1-4: test_hybrid_direction_force_closes
- [ ] USTAT_ANAYASA.md CI-03 revize
- [ ] pytest tests/critical_flows -q ✓
- [ ] Seal_change seremoni + git log kontrol
- [ ] Session raporu: docs/2026-04-19_op_d_session.md
