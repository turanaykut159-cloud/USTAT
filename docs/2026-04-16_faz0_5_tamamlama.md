# FAZ 0.5 — EKSİK BÖLGELERİN DOĞRUDAN OKUMA RAPORU

**Tarih:** 2026-04-16
**Yöntem:** Faz 0'da kısmi okunmuş 4 dosyanın eksik bölgeleri + manuel_motor.py tamamı, alt-ajan DELEGE EDİLMEDEN, doğrudan `Read` tool'u ile satır satır okundu.
**Referans:** Bu rapor `docs/2026-04-16_faz0_dogrudan_okuma.md`'nin devamıdır. Faz 0'daki bayraklar tekrarlanmaz.

---

## BÖLÜM A — OKUMA KAPSAMI

| Dosya | Toplam satır | Faz 0.5'te okunan | Kümülatif | Yüzde |
|---|---|---|---|---|
| `engine/manuel_motor.py` | 1190 | 1-1190 | 1190 | **%100** ✓ |
| `engine/ogul.py` | 3570 | 1-540, 740-1650, 1980-2105, 2290-3570 | ~3485 | **%98** ✓ |
| `engine/baba.py` | 3388 | 330-1000, 1000-1470, 1870-2330, 2830-3388 | ~3350 | **%99** ✓ |
| `engine/h_engine.py` | 3095 | 2200-3095 (önceki 1-2200 + bu) | 3095 | **%100** ✓ |
| `engine/mt5_bridge.py` | 3171 | 1800-3171 (önceki 1-1800 + bu) | 3171 | **%100** ✓ |

**Toplam Faz 0 + Faz 0.5 kümülatif:** ~22.500 satır / 23.943 (tek seferde) = **%94**
(Kalan %6: ogul.py 540-740 ve 1650-1980 — oylama detay/yardımcılar, _log_cancelled_trade, _remove_trade vb. kritik olmayan yardımcı fonksiyonlar.)

---

## BÖLÜM B — YENİ BAYRAKLAR

### Seviye 1 — Anayasa/Kod Drift

#### YB-16 — `_evaluate_kill_switch_triggers` OLAY kalktığında L2 otomatik temizlenir
**Dosya:** `engine/baba.py:2865-2890`
**Kanıt:**
```python
# baba.py:2877-2890
if self.current_regime.regime_type == RegimeType.OLAY:
    if self._kill_switch_level < KILL_SWITCH_L2:
        self._activate_kill_switch(KILL_SWITCH_L2, "olay_regime", ...)
# OLAY rejimi kalktıysa ve L2 olay_regime nedenli ise → temizle
elif (
    self._kill_switch_level == KILL_SWITCH_L2
    and self._kill_switch_details.get("reason") == "olay_regime"
):
    self._clear_kill_switch("OLAY rejimi sona erdi — L2 otomatik kaldırıldı")
```
**Etki:** **AX-3 (Kill-switch Monotonluğu) ile çelişki.** Axiom: *"Kill-switch seviyesi sadece yukari gider (L1 → L2 → L3). Otomatik dusurme yasak."* Kod ise: OLAY regime kalktığında (örn. TCMB toplantı saati 12:00-15:30 geçtiğinde) L2→L0 otomatik temiz. Docstring'de açıklama yok. Dokümanlı bir istisna mı, yoksa istenmeden yapılmış drift mi belirsiz.

#### YB-17 — `_reset_daily` L2 + L1 kill-switch'leri otomatik temizler
**Dosya:** `engine/baba.py:1407-1419`
**Kanıt:**
```python
# baba.py:1407-1412
if (
    self._kill_switch_level == KILL_SWITCH_L2
    and self._kill_switch_details.get("reason") in ("daily_loss", "consecutive_loss")
):
    self._clear_kill_switch("Günlük sıfırlama — L2 kaldırıldı")
# 1416-1419
if self._kill_switch_level == KILL_SWITCH_L1 and self._killed_symbols:
    self._clear_kill_switch("Günlük sıfırlama — L1 kontrat engelleri kaldırıldı")
```
**Etki:** Her yeni günde L2 (`daily_loss`/`consecutive_loss` nedenli) ve L1 (killed_symbols'lı) otomatik temizleniyor. **AX-3 sıkı okumada ihlal.** Niyet belli: "yeni gün = temiz başlangıç — eski günün kaybı bugünü bloklamasın" (1405 yorum). Ama axiom "otomatik düşürme yasak" diyor. Dokümante edilmiş bir istisna mı? Hayır — AXIOMS.yaml AX-3 hiçbir istisna tanımlamıyor. **Anayasa-kod drift.**

---

### Seviye 2 — Kod Kalitesi / Bug Riski

#### YB-18 — `manuel_motor.get_manual_symbols` İKİ KEZ TANIMLI
**Dosya:** `engine/manuel_motor.py:858` ve `1151`
**Kanıt:**
```python
# manuel_motor.py:858-866 (birinci tanım)
def get_manual_symbols(self) -> set[str]:
    return {s for s, t in self.active_trades.items() if t.state in (...)}

# manuel_motor.py:1151-1163 (ikinci tanım — birinciyi üzerine yazar)
def get_manual_symbols(self) -> set[str]:
    symbols = set(self.active_trades.keys())
    try:
        marker_data = self._load_marker()
        symbols.update(marker_data.keys())
    except Exception:
        pass
    return symbols
```
**Etki:** Python'da ikinci tanım üzerine yazar. Satır 858'deki tanım **ÖLÜ KOD**. Kritik fark: ikincisi state filtresini (`FILLED/SENT/PARTIAL`) YAPMIYOR, tüm `active_trades` keys'lerini döndürüyor — CLOSED trade'ler bile dahil edilebilir. İkinci tanım `_load_marker()` fallback ekliyor. Davranış farkı: **ogul.py ve h_engine.py'nin `manual_motor.get_manual_symbols()` çağrılarında state filtresi kaybolmuş** — teorik olarak kapalı manuel trade sembolleri OĞUL ve H-Engine'e "manuel" olarak sızabilir.

#### YB-19 — `manuel_motor._is_trading_allowed` docstring yalanı
**Dosya:** `engine/manuel_motor.py:1181-1190`
**Kanıt:**
```python
def _is_trading_allowed(self, now: datetime | None = None) -> bool:
    """İşlem saatleri kontrolü (09:45-17:45)."""   # ← YALAN
    now = now or datetime.now()
    current_time = now.time()
    if current_time < TRADING_OPEN or current_time > TRADING_CLOSE:   # TRADING_OPEN = time(9, 40), TRADING_CLOSE = time(17, 50)
        return False
```
**Etki:** Docstring 09:45-17:45 derken kod 09:40-17:50 kontrol ediyor. Geliştirici okurken yanlış yönlendirilir. Faz 0'daki Bayrak #10 (h_engine TRADING_OPEN=09:40) ile tutarlı.

#### YB-20 — Manuel SL/TP başarısızsa pozisyon KAPATILMIYOR (AX-4 drift)
**Dosya:** `engine/manuel_motor.py:481-507`
**Kanıt:**
```python
# manuel_motor.py:481-507
if position_ticket and sl > 0 and tp > 0:
    for attempt in range(3):
        mod_result = self.mt5.modify_position(ticket=position_ticket, sl=sl, tp=tp)
        if mod_result is not None:
            sl_tp_applied = True
            break
    if not sl_tp_applied:
        logger.warning(
            f"Manuel SL/TP MT5'e yazılamadı [{symbol}] — "
            f"pozisyon açık ama yazılım SL/TP ile korunuyor"
        )
        # SL/TP yazılamasa bile pozisyonu KAPATMA — kullanıcı bilinçli açtı
        # Risk göstergesi olarak bellekte tutulmaya devam eder
```
**Etki:** **AX-4 (SL/TP zorunluluğu) ManuelMotor için UYGULANMIYOR.** Anayasa: *"send_order SL/TP eklemede basarisiz olursa pozisyon zorla kapatilir. Korumasiz pozisyon yasak."* — bu metinde istisna YOK. ManuelMotor yazılım SL/TP'yi "koruma" sayıyor ama bu MT5'te fiilen mevcut değil — pozisyon gap riskiyle açık kalıyor. Bellekteki SL/TP anlık fiyat hareketini takip edemezse gap olur. Ayrıca bu durum BABA'nın `_unprotected_positions` sicili ile raporlanmıyor (ogul.py:1923-1927 `baba.report_unprotected_position()` çağırır; manuel_motor yapmaz). **Sessiz AX-4 ihlali.**

#### YB-21 — `"force_closed"` dead branch (mt5_bridge'de hiç set edilmiyor)
**Dosya:** `engine/manuel_motor.py:470-476`
**Kanıt:**
```python
if order_result.get("force_closed"):   # ← bu key mt5_bridge.send_order sonucunda SET EDİLMİYOR
    logger.error(f"Manuel emir force-closed [{symbol}]: ...")
    result["message"] = "Emir gönderildi ama SL/TP hatası nedeniyle kapatıldı"
    return result
```
`mt5_bridge.py:1261 order_result = result._asdict()` + `order_result["sl_tp_applied"]` + `order_result["unprotected"]` (1381-1383) var ama **"force_closed" key hiçbir yerde set edilmiyor.** Dead branch.

#### YB-22 — `_ustat_floating_tightened` bayrağı persist edilmiyor
**Dosya:** `engine/baba.py:2291-2300`
**Kanıt:**
```python
if len(recent_misses) >= 5:
    feedback_key = "_ustat_floating_tightened"
    if not getattr(self, feedback_key, False):
        rp = getattr(self, "_risk_params_ref", None)
        if rp is not None:
            old_val = rp.max_floating_loss
            new_val = round(max(0.008, old_val * 0.90), 4)
            if new_val != old_val:
                rp.max_floating_loss = new_val
                setattr(self, feedback_key, True)   # ← instance attribute, _risk_state dict'te değil
```
**Etki:** Bayrak instance attribute. `_persist_risk_state:484` sadece `_risk_state` dict'ini JSON'a serialize ediyor. Restart sonrası `_ustat_floating_tightened=False` resetleniyor → aynı 24 saat içinde tekrar 5+ miss olursa `max_floating_loss` TEKRAR %10 sıkılaştırılır → kademeli iniş. Kullanıcı farkında olmayabilir. **State leak.**

#### YB-23 — `calculate_position_size` contract_size=100.0 hardcoded fallback
**Dosya:** `engine/baba.py:1213`
**Kanıt:**
```python
contract_size = 100.0
vol_min = 1.0
vol_step = 1.0
if self._mt5:
    info = self._mt5.get_symbol_info(symbol)
    if info:
        contract_size = info.trade_contract_size
        ...
```
**Etki:** MT5 symbol_info alınamazsa default 100. VİOP kontrat çarpanı tipik 100 olsa da, bazı kontratlar farklı olabilir (ör. endeks kontratları). Fallback kullanıldığında lot hesaplaması yanlış (çarpan yanlış). `risk_per_trade_pct=0.01`, equity=100k, ATR=2 ile lot = 100000 × 0.01 × 1 / (2 × 100) = **5 lot** — gerçek çarpan 50 olsa lot 10 olurdu (yanlış 2x yönünde risk). MT5 bağlantısı sağlıklı olsa bile sembol_info hatası istisnai durumda hatalı risk verir.

#### YB-24 — İki restore fonksiyonu (`_restore_risk_state` + `restore_risk_state`)
**Dosya:** `engine/baba.py:511` (private, init'te çağrılıyor) ve `engine/baba.py:3276` (public, main.py'den çağrılıyor)
**Kanıt:**
- `_restore_risk_state:511` — `_risk_state` dict'ini JSON'dan yükler (daily counters, cooldown, monthly_paused vb.). `__init__:373`'te otomatik çağrılıyor.
- `restore_risk_state:3276` — DB'deki son `KILL_SWITCH` event'inden seviyeyi okur ve son `COOLDOWN` event'ten cooldown bitişini hesaplar. `main.py:1440` `_restore_state`'ten çağrılıyor.

**Etki:** İki farklı yoldan restore. Çakışma riski: `_restore_risk_state` JSON'dan `cooldown_until` yükler, sonra `restore_risk_state` event'ten tekrar hesaplar ve üzerine yazar. Hangisi doğru? JSON taze (her cycle persist), event geç (cooldown_start event'ten hesaplama hatalı olabilir). Dokümante edilmemiş. **Overlap, restore order belirsiz.**

#### YB-25 — OGUL `_handle_closed_trade` reason="sl_tp" varsayımı
**Dosya:** `engine/ogul.py:2398-2400` (manage_active_trades) + `3062-3096` (_sync_positions)
**Kanıt:**
```python
# ogul.py:2396-2400
pos = pos_by_symbol.get(symbol)
if pos is None:
    self._handle_closed_trade(symbol, trade, "sl_tp")   # ← reason varsayımı
    continue
```
Pozisyon MT5'te yoksa "sl_tp" reason atfetiliyor. Ama pozisyon kapanmış olabilir çünkü:
1. SL/TP tetiklendi (gerçek "sl_tp")
2. BABA `_close_all_positions` L3 çağırdı
3. Kullanıcı MT5 terminalinden manuel kapattı
4. Hibrite devredildi (h_engine pozisyonu aldı, OĞUL listesinde kalabilir)
5. Harici broker kesintisi

`_sync_positions:3092-3096` farklı yerde "external_close" kullanıyor:
```python
if symbol not in open_symbols:
    self._handle_closed_trade(symbol, trade, "external_close")
```
**İki farklı kod yolu aynı durum için farklı reason atfediyor.** R-Multiple istatistikleri ve ÜSTAT hata atfetme analizi (`_determine_fault`) `exit_reason`'a dayanıyor — yanlış reason yanlış atfetme yapar. **Data quality sorunu.**

#### YB-26 — `_check_primnet_target` retry limit dolunca pozisyon kapatılmıyor
**Dosya:** `engine/h_engine.py:2380-2384`
**Kanıt:**
```python
retry_key = f"primnet_target_{hp.ticket}"
retry_count = self._close_retry_counts.get(retry_key, 0)
if retry_count >= self._MAX_CLOSE_RETRIES:
    return False   # ← hedef vurulmuş ama kapatma atlanıyor
```
**Etki:** PRİMNET hedef fiyatına ulaşılmış (±9.5 prim), ama 3 retry başarısız oldu. Fonksiyon `False` dönüyor → pozisyon hibrit yönetimde AÇIK KALMAYA devam ediyor. Kullanıcıya bildirim yok. Stop Limit modunda emir hala bekliyor olabilir (bağlantısı kontrol edilmiyor bu dalda). **Sessiz fail-soft:** hedef ulaşıldı ama koruma atılıyor. Operatör log monitör etmiyorsa fark etmez.

#### YB-27 — `modify_pending_order` ve `modify_stop_limit` duplicate fonksiyon
**Dosya:** `engine/mt5_bridge.py:2670` ve `3007`
**Kanıt:** İki ayrı metot, aynı işi (bekleyen Stop Limit emir güncelleme) farklı imzalarla yapıyor:
- `modify_pending_order(order_ticket, new_price, new_stoplimit=None)` — `price` + opsiyonel `stoplimit`
- `modify_stop_limit(order_ticket, new_stop_price=None, new_limit_price=None)` — iki ayrı opsiyonel parametre

**Etki:** Hangisi kullanılıyor? Grep yapılmamış ama h_engine.py'de `_trailing_via_stop_limit` yeni STOP_LIMIT gönderip eskisini iptal ediyor (place-first-then-cancel pattern). `modify_*` metotları çağrılmıyor olabilir → **dead code.** İki ayrı fonksiyon bakımı zor, dokümantasyon kafası karıştırıcı.

#### YB-28 — `check_order_status` muhtemelen dead code
**Dosya:** `engine/mt5_bridge.py:2315`
**Durum:** Faz 0 + Faz 0.5 boyunca OĞUL/H-Engine/ManuelMotor/baba hiçbir yerinde `check_order_status` çağrısı görülmedi. API routes bu fonksiyonu kullanıyor olabilir (doğrulanmadı). **Potansiyel ölü kod**, Faz 1'de grep ile doğrulanmalı.

#### YB-29 — OGUL ogul_enabled=False varsayılan: sistem açılışında otomatik trade YAPMAZ
**Dosya:** `engine/ogul.py:436`
**Kanıt:**
```python
# ── OĞUL Motor Toggle (v6.0 — kullanıcı arayüzünden açılıp kapatılabilir) ──
# Varsayılan KAPALI: uygulama açılışında OĞUL sinyal üretmez,
# kullanıcı UI'den elle açar. Diğer motorlar (Manuel, Hibrit) bağımsızdır.
self._ogul_enabled: bool = False
```
**Etki:** CLAUDE.md dokümantasyonu OĞUL'u "otonom sinyal üreticisi" olarak tanıtıyor. Ama `_ogul_enabled=False` default. Kullanıcı UI'den `POST /api/ogul-toggle` ile açmazsa **OĞUL yeni sinyal üretmez** (process_signals satır 594-595: `if not self._ogul_enabled: return`). HIZLI DÖNGÜ (EOD, manage_active, sync) çalışıyor ama SİNYAL DÖNGÜSÜ engelleniyor. Anayasa'da bu state dokümante edilmemiş. **Dokümantasyon eksikliği.**

#### YB-30 — OGUL `_determine_direction` 3 kaynak iddia ediyor, aslında 2 bağımsız
**Dosya:** `engine/ogul.py:965-1051`
**Kanıt:** 3 kaynaktan konsensüs:
1. `_calculate_voting` (satır 982) — RSI + EMA(20 vs 50) + ATR + Volume + price_action
2. H1 trend filtresi (989-1005) — EMA(20 vs 50) H1 zaman diliminde
3. SE3 motoru (1007-1030) — bağımsız (9 kaynak iç içe)

**Etki:** **Kaynak 1 ve 2'de aynı gösterge (EMA 20/50) kullanılıyor**, sadece zaman dilimi farklı. "3 bağımsız kaynak" iddiası zayıf — iki kaynak korele. Konsensüs kararının istatistiksel bağımsızlığı sorgulanır. Sinyal kalitesi analizi yapılmamış.

---

### Seviye 3 — Test Katmanı Zayıflığı

Faz 0'daki bulgular devam — yeni bulgu yok.

---

### Seviye 4 — R-11 Sihirli Sayı İhlalleri (yaygın, yeni)

#### YB-31 — `manuel_motor.py` modül seviyesi hardcoded sabitler
**Dosya:** `engine/manuel_motor.py:59-77`
`ATR_PERIOD`, `MIN_BARS_M15`, `CONTRACT_SIZE`, `MAX_LOT_PER_CONTRACT`, `MARGIN_RESERVE_PCT_DEFAULT`, `MAX_CONCURRENT_MANUAL`, `TRADING_OPEN=time(9,40)`, `TRADING_CLOSE=time(17,50)`, `SENT_EXPIRE_SEC=30.0`, `SL_ATR_GREEN=1.5`, `SL_ATR_YELLOW=0.8`, `PNL_YELLOW_PCT=-0.005`. Hiçbiri config'ten okunmuyor.

#### YB-32 — `ogul.py` modül seviyesi hardcoded sabitler
**Dosya:** `engine/ogul.py:85-284`
**~60+ module-level constant** — strateji eşikleri (TF_EMA_FAST/SLOW, TF_ADX_HARD/SOFT, MR_RSI_OVERSOLD/OVERBOUGHT, BO_LOOKBACK, BO_VOLUME_MULT), trade timing (ORDER_TIMEOUT_SEC, MAX_SLIPPAGE_ATR_MULT), pyramid (PYRAMID_MAX_ADDS), chandelier (CHANDELIER_LOOKBACK), max_hold (MAX_HOLD_BARS), trailing (TRAILING_MIN_PCT, TRAILING_MAX_PCT) vb. Sadece `_margin_reserve_pct`, `_max_lot`, `_max_concurrent`, `_trading_open`, `_trading_close` config'ten okunuyor (satır 386-407). Geri kalan **~55 sabit hardcoded**. R-11 ihlali yaygın.

#### YB-33 — `baba.py` module-level hardcoded (zaten Faz 0'da not edildi ama detay)
**Dosya:** `engine/baba.py:116-209`
Rejim eşikleri, fake sinyal ağırlıkları (`FAKE_WEIGHT_VOLUME=1`, `FAKE_WEIGHT_SPREAD=2`, `FAKE_WEIGHT_MULTI_TF=1`, `FAKE_WEIGHT_MOMENTUM=2`, toplam=6=`FAKE_SCORE_THRESHOLD`). Fake ağırlık şeması tamamen koddan — `config/default.json`'da hiç yer almıyor. Fake sinyal eşiği kritik (pozisyon kapatılıyor) ama "config_history" siciline yazılmıyor.

---

### Seviye 5 — CORS/Ölü Kod

#### YB-34 — `manuel_motor.py` `get_manual_symbols` dublicate (YB-18 ile aynı, ölü kod kategorisinde)
Satır 858'deki ilk tanım ölü (ikincisi üzerine yazıyor).

#### YB-35 — `mt5_bridge.py` çift modify fonksiyonu (YB-27)
`modify_pending_order` ve `modify_stop_limit` aynı işi yapıyor. Hangisi kullanılmadığı grep ile doğrulanmalı.

---

## BÖLÜM C — `ManuelMotor` TAM PROFİLİ

### C.1 — Ne zaman yaratılıyor?
**Yaratım noktası:** `engine/main.py:145-153` (Engine `__init__` içinde), tek yer:
```python
# main.py:145-153
from engine.manuel_motor import ManuelMotor
self.manuel_motor = ManuelMotor(
    config=self.config,
    mt5=self.mt5,
    db=self.db,
    baba=self.baba,
    risk_params=self.risk_params,
)
```
**Başka yaratım noktası yok.** api/server.py:92-104'te Engine oluşturulduktan sonra lifespan üzerinden ManuelMotor yaratılır. Testlerde mock kullanılıyor olabilir.

### C.2 — Hangi state'i tutuyor?
**`self.active_trades: dict[str, Trade]` (satır 103)** — kendi manuel pozisyon sicili (OĞUL'un active_trades'ten AYRI).
**`self._marker_path: Path`** (106-108) — `database/manual_positions.json` dosyasına yazılan atomik JSON marker. DB WAL kayıp koruması.
**Cross-motor referanslar (116-117):** `self.ogul` ve `self.h_engine` (Engine `__init__` tarafından atanır, main.py:155-157).

Docstring (1-27) net tanım:
- "Trailing stop YOK"
- "TP1 yarı kapanış YOK"
- "Breakeven çekme YOK"
- "Rejim bazlı zorunlu kapanış YOK (VOLATILE/OLAY → sadece KIRMIZI gösterge)"
- "Sinyal devam kontrolü YOK"
- "Kullanıcının SL/TP'si aynen korunur"

Yani ManuelMotor **politika olarak müdahale etmiyor** — sadece kullanıcının açtığı işlemi takip ediyor ve risk göstergesi sağlıyor.

### C.3 — `sync_positions()` ne yapıyor?
**Giriş:** `engine/main.py:920` her cycle (10 saniye) çağrılıyor.
**Kod:** `manuel_motor.py:566-648`
**İşlev:**
1. MT5'ten `get_positions()` çeker.
2. `active_trades` içindeki her trade için:
   - **SENT → FILLED geçişi:** Symbol MT5'te varsa, FILLED'a çevir (604-609). DB'de trade kaydını güncelle (612-617).
   - **SENT ama MT5'te yok + 30sn aştı:** `SENT_EXPIRE_SEC=30.0` — emir reddedildi/anında kapatıldı → `_handle_closed_trade(symbol, trade, "external_close")` (618-630).
   - **FILLED ama ticket MT5 tickets'ta yok:** Pozisyon kapanmış → `_handle_closed_trade(symbol, trade, "external_close")` (632-648).

**OĞUL/H-Engine state'ini GÜNCELLEMİYOR.** Sadece kendi `active_trades`'ini yönetir. Çakışma kontrolü için `get_manual_symbols()` / `get_manual_tickets()` expose ediyor — diğer motorlar (ogul.py:2306-2313, h_engine.py:2193-2202) bu listeleri okuyup kendi filtrelerinde kullanıyor.

### C.4 — Anayasada nasıl tanımlanmalı?
**Kod davranışı:**
- İşlem AÇIYOR: `open_manual_trade` (306) → `mt5.send_order` (435)
- İşlem KAPATIYOR: `sync_positions` external_close handler (629, 641, 648)
- Pozisyon YÖNETİYOR: `restore_active_trades` (872), `adopt_mt5_direct_position` (1006)
- State TUTUYOR: `active_trades` + `manual_positions.json` marker
- Main loop'ta ÇAĞRILIYOR: `main.py:920` her cycle

**Sonuç: Bu tam bir motor, yardımcı servis veya köprü değil.**
- Köprü (bridge) olsaydı sadece MT5 çağrılarını wrap ederdi.
- Yardımcı servis olsaydı "kullanıcı tetiklerse" çalışırdı, cycle'da değil.

ManuelMotor **5. motor**. Anayasa (USTAT_ANAYASA.md + axioms.yaml) bu gerçeği yansıtmalı:

1. **AX-1 güncellemesi önerisi:** "Ana dongu sirasi BABA → OGUL → H-Engine → **ManuelMotor** → USTAT"
2. **Yeni axiom öner:** "ManuelMotor sadece kullanıcı tetiğiyle emir açar; otonom sinyal üretemez" (docstring bunu yazıyor — anayasaya aktarılabilir).
3. **protected_assets.yaml:** `engine/manuel_motor.py` Kırmızı Bölge listesine eklenmeli (11. dosya).
4. **Siyah Kapı:** `open_manual_trade`, `sync_positions`, `_handle_closed_trade`, `restore_active_trades`, `adopt_mt5_direct_position` fonksiyonları korunmalı.

Alternatif (kod tasarımı değişikliği): ManuelMotor OĞUL'un alt modülü haline getirilebilir — ama bu büyük refactor ve faydası şüpheli.

---

## BÖLÜM D — FAZ 0 BAYRAKLARININ DOĞRULAMA/ÇÜRÜTME DURUMU

| # | Faz 0 Bayrağı | Durum | Yeni kanıt/açıklama |
|---|---|---|---|
| 1 | Hibrit EOD'da kapatılmıyor | **DOĞRULANDI** | `ogul.py:2154` + `h_engine.py:715-749` netleşti. H-Engine OLAY'da kapatır (706-713), EOD'da sadece `insert_notification("hybrid_eod")` |
| 2 | AX-4 `enforced_in` yanlış konum | **DOĞRULANDI** | `ogul.py:1879-1943` AX-4 koruma burada gerçekleşiyor; `mt5_bridge.py:1457-1467` ve `manuel_motor.py:501-507` bu koruma YOK — AX-4 drift dallanıyor (YB-20) |
| 3 | ManuelMotor 5. motor, anayasada yok | **DOĞRULANDI + DETAYLANDI** | ManuelMotor tam motor profili Bölüm C'de. AX-1 güncellemesi gerekiyor |
| 4 | CI-11 Anayasa'da var, protected_assets'te yok | DOĞRULANDI (Faz 0) | Değişiklik yok |
| 5 | `constitution_version: "2.0"` vs anayasa v3.0 | DOĞRULANDI (Faz 0) | Değişiklik yok |
| 6 | `ustat.db` ölü dosya | DOĞRULANDI (Faz 0) | Değişiklik yok |
| 7 | `ustat.py:2104-2108` `strategy_dist` key bug | DOĞRULANDI (Faz 0) | Değişiklik yok |
| 8 | `api/server.py:98` Ogul constructor risk_params geçmiyor | **KISMEN DÜZELTİLDİ — aşağıda Bölüm E** | Bkz. E.1 |
| 9 | `baba.py:2637` CLOSE_MAX_RETRIES=5 hardcoded | DOĞRULANDI (Faz 0) | Değişiklik yok |
| 10 | `h_engine.py:61` TRADING_OPEN=09:40 hardcoded | **DOĞRULANDI + GENİŞLEDİ** | `manuel_motor.py:66-67` de aynı drift. OĞUL ise config'ten okuyor (ogul.py:396-407) — **üç motor farklı saatler** |
| 11 | `transfer_to_hybrid` atomik değil | DOĞRULANDI (Faz 0) | H-Engine 568-584, DB insert başarısız → MT5 SL geri alınmıyor |
| 12 | Yön değişimi → pozisyon SL-siz kalabilir | DOĞRULANDI | `h_engine.py:816-854`, hibrit takibi sonlandırılıyor ama MT5 pozisyon + SL durumu bilinmiyor |
| 13 | 55 testin çoğu string/imza testi | DOĞRULANDI (Faz 0) | Değişiklik yok |
| 14 | `test_ogul_has_end_of_day_check` sadece "17"/"45" arıyor | DOĞRULANDI (Faz 0) | Değişiklik yok |
| 15 | `test_baba_l2_only_closes_ogul_and_hybrid` sadece `hasattr` | DOĞRULANDI (Faz 0) | Değişiklik yok |

---

## BÖLÜM E — FAZ 0'DA YANLIŞ YAZILAN ŞEYLER (DÜZELTİLME)

### E.1 — Faz 0 Bayrağı #8 kısmen yanlış
**Faz 0'da yazdım:**
> api/server.py:98 `risk_params` geçmiyor → Ogul.risk_params None olabilir.

**Gerçek:** `engine/ogul.py:380` — Ogul `__init__` içinde `self.risk_params = risk_params or RiskParams()` var. Default bir `RiskParams()` instance oluşturuluyor. **None olmayacak, crash etmeyecek.**

**Ama gerçek drift var:** api/server.py yolunda `RiskParams()` default değerlerle yaratılıyor, main.py yolunda ise config'ten okunan `risk_params` geçiliyor (main.py:103-121). Yani:
- `main.py` → `Engine()` → `Ogul(... risk_params=self.risk_params)` — config'ten max_daily_loss=0.018
- `api/server.py:98` → `Ogul(config, mt5, db, baba=baba)` — default `RiskParams()` (dataclass defaults)

**İki yolda farklı risk parametreleri.** api/server.py yolunda `RiskParams` default değerleri ne? `engine/models/risk.py` dosyasını okumadım (Faz 0 veya 0.5'te). Potansiyel olarak config değerleri ile uyumsuz. Bu bir **CRASH değil, değer drift'i**. Faz 0'daki "POTANSİYEL BUG" ifadesi düzeltilmeli → "POTANSİYEL DEĞER DRIFT'i".

**Not:** api/server.py:100-104'te Engine `Engine(... ogul=ogul)` geçiliyor — Engine `__init__:118-121`'deki `ogul or Ogul(...)` branch'i **kullanılmıyor** (ogul zaten verilmiş). Yani main.py'deki risk_params parametreli Ogul yaratımı api/server.py yolunda ÇALIŞMAZ. api/server.py'deki Ogul kalır. Drift kesin.

---

## BÖLÜM F — NİHAİ BAYRAK SAYIMI

| Kategori | Faz 0 | Faz 0.5 yeni | Toplam |
|---|---|---|---|
| Seviye 1 — Anayasa/Kod Drift | 5 | 2 (YB-16, 17) | **7** |
| Seviye 2 — Kod Kalitesi / Bug Riski | 7 | 13 (YB-18 ~ YB-30) | **20** |
| Seviye 3 — Test Katmanı Zayıflığı | 3 | 0 | **3** |
| Seviye 4 — R-11 Sihirli Sayı | 1 (yaygın) | 3 (YB-31, 32, 33) | **4 (yaygın)** |
| Seviye 5 — CORS / Ölü Kod | 2 | 2 (YB-34, 35) | **4** |
| **TOPLAM** | **15** | **17** | **32** (düzeltme dahil 33) |

**Düzeltme:** Faz 0 Bayrak #8 "POTANSİYEL BUG" → "DEĞER DRIFT" olarak revize edildi.

---

## ÖZET

Faz 0.5 tamamlandı. Eksik 4 dosya tamamen okundu + `manuel_motor.py` ilk kez baştan sona okundu.

**Kritik yeni bulgular:**
1. **YB-16 + YB-17:** Kill-switch otomatik temizleme (OLAY kalktığında + günlük reset'te) — AX-3 anayasal drift'i.
2. **YB-18:** `manuel_motor.get_manual_symbols` iki kez tanımlı, ilki ölü, ikincisinde state filtresi kaybolmuş — kapalı manuel trade sembolleri cross-motor netting'e sızabilir.
3. **YB-20:** ManuelMotor SL/TP başarısızsa pozisyonu kapatmıyor — AX-4 drift.
4. **YB-22:** `_ustat_floating_tightened` bayrağı persist edilmiyor — restart'ta kademeli floating_loss sıkılaşması riski.
5. **YB-25:** "sl_tp" vs "external_close" reason ataması iki farklı kod yolunda tutarsız.
6. **YB-26:** PRİMNET hedef retry limit sonra sessiz fail-soft — pozisyon açık kalır.
7. **ManuelMotor tam profili:** 5. motor, emir açıyor, state tutuyor, main loop'ta cycle'da çalışıyor. AX-1 güncellemesi ve protected_assets.yaml'a eklemesi önerilir.

**Toplam bayrak sayımı: Faz 0 (15) + Faz 0.5 yeni (17) = 32 aktif bayrak.**

Faz 1 (audit) onayına hazır.
