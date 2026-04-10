# OĞUL Kapsamlı Fix Planı — 14 Bulgu Uygulaması

**Tarih:** 10 Nisan 2026 (Cuma, piyasa açık ama motor kapalı — 0 pozisyon)
**Kaynak:** `docs/2026-04-10_ogul_kapsamli_analiz.md`
**Onay:** Kullanıcı açık yazılı talebi ("tamam bulguların hepsini planla etki analizi yap ve uygula")
**Mod:** Motor durmuş, MT5 bağlantısız, 0 pozisyon → fiili BARIŞ ZAMANI

---

## 1. Uygulama Stratejisi

**Kırmızı Bölge kuralı (§4.1):** Tek seferde tek değişiklik. 14 fix atomik commit'lere bölünmüştür. Mantıksal olarak birbirine bağlı küçük fix'ler tek commit'te gruplanmıştır.

**Sıralama:** P0 (kritik) → P1 (yüksek) → P2 (orta) → P3 (temizlik)

**Her commit öncesi:** Read → Edit → AST syntax doğrulama → git commit
**Son adım:** Build → restart → session report → changelog #150 → version bump

---

## 2. Commit Planı (14 Adım)

### Commit 1 — C-1: Lot Hesaplama Geri Yükleme (Siyah Kapı C4)

**Dosya:** `engine/ogul.py`
**Fonksiyon:** `_execute_signal` (satır 1619)
**Değişiklik:** `lot = 1.0` → BABA.calculate_position_size(...) çağrısı + guard

**Etki analizi:**
- BABA.calculate_position_size zaten mevcut (baba.py:1054) — test edilmiş
- ATR değeri M15 verisinden `calc_atr` ile alınır
- Rejim çarpanı BABA içinde uygulanır → `_risk_multiplier` field gereksizleşir
- Guard: ATR None → CANCELLED, lot <= 0 → CANCELLED (graduated lot 0 da dahil)
- `docs/ogul_calculate_lot_backup.md` mevcut ama "bilinen sorunlar" listeli — backup'ın temiz versiyonu uygulanır (sadece BABA çağrısı + guard, conviction/bias kompleks katmanlar dahil edilmez)
- Çağrı zinciri: `_execute_signal → baba.calculate_position_size → mt5.get_symbol_info` (mevcut)
- Sihirli sayı yok — tüm eşikler config'den

**Geri alma:** `git revert <hash>` — tek commit, tek fonksiyon bloğu

### Commit 2 — C-2 + O-6: Yön Konsensüsü Sıkılaştırma

**Dosya:** `engine/ogul.py`
**Fonksiyon:** `_determine_direction`
**Değişiklikler:**
- `buy_v >= 1` → `buy_v >= 2` (3 kaynaktan 2 çoğunluk)
- H1 slope eşiği `0.001` → `0.005` (%0.1 → %0.5)

**Etki analizi:**
- Sinyal sayısı azalacak (tahmin: ~%40–50 düşüş)
- False positive oranı düşecek
- Miss rate artar — ancak refactor amacı güvenlik
- Çağıran: `process_signals:628`

**Geri alma:** `git revert <hash>`

### Commit 3 — C-4: SL Fail Branch Return Path

**Dosya:** `engine/ogul.py`
**Fonksiyon:** `_execute_signal` (satır 1762–1792)
**Değişiklik:** close_result None branch'ına:
- `trade.state = TradeState.SIGNAL` → yeni sentinel gerekmez, event CRITICAL, `return`
- DB'ye FILLED yazılmasını engelle
- active_trades.pop + BABA'ya raporlama KORUNUR

**Etki analizi:**
- Korumasız pozisyon MT5'te gerçekten açık kalırsa → trade state korumalı (DB'de FILLED değil)
- BABA.report_unprotected_position çağrısı korunur
- `baba.increment_daily_trade_count` ve DB.insert_trade bypass edilir
- Anayasa Kural 4 uyumu sağlanır

**Geri alma:** `git revert <hash>`

### Commit 4 — C-6: PnL Commission Sıralama

**Dosya:** `engine/ogul.py`
**Fonksiyon:** `_handle_closed_trade` (satır 2982–3024)
**Değişiklik:** Fallback PnL sadece log'a, DB update `deal_summary` başarılıysa yapılır. Başarısızsa kısmi update (commission=0 yazmadan).

**Etki analizi:**
- Deal summary retry 3×0.8s bloklaması korunur (C-5 ile birleşik değil — ayrı fix)
- Commission ve swap değerleri doğru olur
- Muhasebe sadakati artar

**Geri alma:** `git revert <hash>`

### Commit 5 — C-5: EOD Blocking Retry Azaltma

**Dosya:** `engine/ogul.py`
**Fonksiyon:** `_verify_eod_closure` (satır 2088)
**Değişiklik:** 5 deneme × 1s → 3 deneme × 0.5s (worst case 5s × N → 1.5s × N)

**Etki analizi:**
- Main loop bloklaması azalır
- EOD başarı oranı küçük miktarda düşebilir (1 ticket için 3s vs 5s retry)
- Piyasa kapalı olduğu için heartbeat riski minimal

**Geri alma:** `git revert <hash>`

### Commit 6 — Y-1: baba.get_kill_switch_level() Public API

**Dosyalar:** `engine/baba.py`, `engine/ogul.py`
**Değişiklikler:**
- baba.py'a `def get_kill_switch_level(self) -> int` ekle
- ogul.py `process_signals:566` `baba._kill_switch_level` → `baba.get_kill_switch_level()`

**Etki analizi:**
- Encapsulation düzeltmesi
- BABA iç field değişirse OĞUL etkilenmez
- Yeni public metod — backward compatible

**Geri alma:** `git revert <hash>`

### Commit 7 — Y-2: _risk_multiplier Sızıntı Temizliği

**Dosyalar:** `engine/main.py`, `engine/ogul.py`
**Değişiklikler:**
- main.py:876 `self.ogul._risk_multiplier = risk_verdict.risk_multiplier` kaldır
- ogul.py `_risk_multiplier` field tanımı kaldır
- main.py:870-884 yorum bloğu güncelle — "BABA zaten çarpanı uyguluyor"

**Etki analizi:**
- C-1 ile birlikte anlamlı — BABA.calculate_position_size kendi `current_regime.risk_multiplier`'ını kullanıyor
- Aynı mantığın iki kere uygulanması engellenir
- Kod netliği artar

**Geri alma:** `git revert <hash>`

### Commit 8 — O-4/O-5: ATR Oylama Yön Filtresi

**Dosya:** `engine/ogul.py`
**Fonksiyon:** `_calculate_voting`
**Değişiklik:** ATR genişleme + fiyat son 3 mum pozitif → BUY, negatif → SELL, karışık → oy yok

**Etki analizi:**
- Matematiksel olarak doğru: ATR yön bilgisi vermez, birleşik filtre gerekir
- Oy sayısı bazen 4 yerine 3'e düşer (ATR belirsizse) → konsensüs zorlaşır (C-2 ile birleşik etki)

**Geri alma:** `git revert <hash>`

### Commit 9 — Y-5: MR TP = BB_mid

**Dosya:** `engine/ogul.py`
**Fonksiyon:** `_check_mean_reversion`
**Değişiklik:** `tp = bb_mid + 0.3 * atr_val` → `tp = bb_mid`

**Etki analizi:**
- Mean reversion TP ortaya ayarlanır (gerçek hedef)
- Expectancy yükselir — kaçırma riski düşer
- Trailing TP aşıldığında çalışmaya devam eder (zaten var)

**Geri alma:** `git revert <hash>`

### Commit 10 — O-10: Breakeven Eşiği BE_ATR_BY_CLASS

**Dosya:** `engine/ogul.py`
**Fonksiyon:** `_determine_trade_mode` (satır 2420)
**Değişiklik:** `profit_pts >= atr_val` → `profit_pts >= BE_ATR_BY_CLASS.get(liq_class, 0.75) * atr_val`

**Etki analizi:**
- Likidite sınıfı A (yüksek) daha geç breakeven, C (düşük) daha erken
- `liq_class` `_determine_trade_mode` içine parametre olarak geçirilmeli veya `self._get_liq_class(trade.symbol)` çağrısı içine konmalı
- Sabit zaten tanımlı

**Geri alma:** `git revert <hash>`

### Commit 11 — O-14: Volume Spike Eşiği

**Dosya:** `engine/ogul.py`
**Fonksiyon:** `_check_volume_spike` (satır 2658)
**Değişiklik:** `profit < -0.3 * atr_val` → `profit < -0.8 * atr_val`

**Etki analizi:**
- Erken çıkış azalır
- Trailing SL ile birlikte çalışır — SL zaten 1-1.5×ATR'de
- Hacim spike + aleyhe = gerçek panik, 0.8×ATR daha mantıklı eşik

**Geri alma:** `git revert <hash>`

### Commit 12 — O-9: BO SL Yapısal

**Dosya:** `engine/ogul.py`
**Fonksiyon:** `_check_breakout` SL hesabı
**Değişiklik:** `last_close - 1.5 * atr_val` → konsolidasyon low/high - 0.2*ATR buffer

**Etki analizi:**
- False breakout'ta daha hızlı çıkış
- SL mesafesi azalır → risk-per-trade hesabı değişir (BABA lot daha yüksek verebilir)
- TP de yakınlaşabilir → R:R değişmez çünkü SL yapısal

**Geri alma:** `git revert <hash>`

### Commit 13 — O-1/D-7: Ölü State Temizliği

**Dosyalar:** `engine/ogul.py`, `api/routes/health.py`
**Değişiklikler:**
- `_daily_loss_stop`, `_daily_loss_stop_date`, `_monthly_start_equity`, `_monthly_start_date`, `_monthly_dd_stop`, `_monthly_dd_warn` field'ları sil
- `process_signals` günlük reset bloğu sil
- health.py:133 `ogul._daily_loss_stop` → `baba._daily_loss_stop` veya BABA public API

**Etki analizi:**
- API contract değişir — health endpoint
- Frontend değişikliği gerekmez (değer aynı biçimde döner)
- Dead code temizliği

**Geri alma:** `git revert <hash>`

### Commit 14 — Y-9: Orphan CRITICAL Log + Event Bus

**Dosya:** `engine/ogul.py`
**Fonksiyon:** `restore_active_trades` (satır 3300)
**Değişiklik:** `logger.warning` → `logger.critical`, `event_bus.emit("orphan_detected", ...)` ekle

**Etki analizi:**
- Log seviyesi artar — operatör dikkati
- Frontend'de uyarı çıkabilir (event_bus → WebSocket)
- Fonksiyonel davranış değişmez

**Geri alma:** `git revert <hash>`

---

## 3. Etki Özeti

| Dosya | Fonksiyon Sayısı | Satır Değişimi (tahmini) | Bölge |
|-------|------------------|--------------------------|-------|
| engine/ogul.py | 11 | ~120 | **KIRMIZI** |
| engine/baba.py | 1 (yeni metod) | ~10 | **KIRMIZI** |
| engine/main.py | 1 (_run_single_cycle yorum + satır) | ~15 | **KIRMIZI** |
| api/routes/health.py | 1 | ~5 | Yeşil |

**Toplam:** ~150 satır değişim, ~14000 satırlık kod tabanında ~%1.07 → versiyon bump eşiği (%10) altında kalır. **Patch versiyon bump yeterli:** v5.9.0 → v5.9.1 (opsiyonel). Kullanıcı onayı sonrası karar verilir.

## 4. Risk ve Azaltma

| Risk | Olasılık | Azaltma |
|------|----------|---------|
| C-1 ATR calc hatası | Orta | `_get_current_atr` yardımcı fonksiyon kullanılıyorsa güvenli; yoksa inline calc_atr |
| C-4 state değişimi frontend'i etkiler | Düşük | Yeni state eklenmez, mevcut akışta return yapılır |
| O-10 liq_class scope | Düşük | `_determine_trade_mode` içine geçirilir |
| C-5 EOD 3 deneme yetmez | Çok düşük | Piyasa kapalı, manuel müdahale mümkün |

## 5. Yürütme Kontrol Listesi

- [x] Plan belgelendi
- [ ] C-1 (Commit 1)
- [ ] C-2 + O-6 (Commit 2)
- [ ] C-4 (Commit 3)
- [ ] C-6 (Commit 4)
- [ ] C-5 (Commit 5)
- [ ] Y-1 (Commit 6)
- [ ] Y-2 (Commit 7)
- [ ] O-4/O-5 (Commit 8)
- [ ] Y-5 (Commit 9)
- [ ] O-10 (Commit 10)
- [ ] O-14 (Commit 11)
- [ ] O-9 (Commit 12)
- [ ] O-1/D-7 (Commit 13)
- [ ] Y-9 (Commit 14)
- [ ] AST syntax doğrulama (py_compile tüm modüller)
- [ ] Frontend build (npm run build)
- [ ] Restart + smoke test
- [ ] Changelog #150
- [ ] Session report
- [ ] Version bump kararı

**Başlangıç:** 10 Nisan 2026, 12:10
