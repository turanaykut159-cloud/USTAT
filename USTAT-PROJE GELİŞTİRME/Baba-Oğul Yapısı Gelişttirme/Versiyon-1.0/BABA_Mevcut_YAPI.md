# BABA_YAPI.md — BABA (Risk Yoneticisi + Rejim Algilama)

Kaynak: `engine/baba.py` (1981 satir)

---

## 1. SINIF YAPISI

### Class: `Baba`

- Inheritance: Yok (plain class)

### `__init__` Parametreleri

```python
def __init__(
    self,
    config: Config,
    db: Database,
    mt5: MT5Bridge | None = None,
) -> None
```

### Instance Degiskenleri

| Degisken | Tip | Baslangic Degeri |
|---|---|---|
| `self._config` | `Config` | `config` parametresi |
| `self._db` | `Database` | `db` parametresi |
| `self._mt5` | `MT5Bridge \| None` | `mt5` parametresi |
| `self.current_regime` | `Regime` | `Regime(regime_type=RegimeType.TREND)` |
| `self.active_warnings` | `list[EarlyWarning]` | `[]` |
| `self._spread_history` | `dict[str, list]` | `{s: [] for s in WATCHED_SYMBOLS}` (sembol basina 30 elemanlik ring buffer) |
| `self._SPREAD_HISTORY_LEN` | `int` | `30` |
| `self._usdtry_history` | `list` | `[]` |
| `self._kill_switch_level` | `int` | `KILL_SWITCH_NONE` (0) |
| `self._kill_switch_details` | `dict` | `{}` |
| `self._killed_symbols` | `set` | `set()` |
| `self._risk_state` | `dict` | Asagidaki dict |

### `_risk_state` Baslangic Degerleri

```python
{
    "daily_reset_date": None,
    "daily_trade_count": 0,
    "weekly_reset_week": None,
    "weekly_loss_halved": False,
    "monthly_reset_month": None,
    "monthly_paused": False,
    "consecutive_losses": 0,
    "last_trade_count": 0,
    "cooldown_until": None,
}
```

---

## 2. PUBLIC METODLAR

| Metod | Parametreler | Donus | Ozet |
|---|---|---|---|
| `run_cycle` | `self, pipeline=None` | `Regime` | Ana 10sn cycle: buffer guncelle, rejim algila, uyarilari kontrol et, fake analiz, periyod sifirla, kill-switch tetikleyicilerini degerlendir |
| `detect_regime` | `self` | `Regime` | Piyasa rejimini algila (oncelik: OLAY > VOLATILE > TREND > RANGE) |
| `check_early_warnings` | `self` | `list[EarlyWarning]` | Tum erken uyari tetikleyicilerini kontrol et (15 sembol + USDTRY) |
| `calculate_position_size` | `self, symbol: str, risk_params: RiskParams, atr_value: float, account_equity: float` | `float` | Sabit-kesirli pozisyon boyutlama, rejim carpaniyla; lot sayisi doner (0.0 = islem yok) |
| `check_drawdown_limits` | `self, risk_params: RiskParams` | `bool` | Gunluk ve toplam drawdown limitleri; True = devam, False = dur |
| `check_risk_limits` | `self, risk_params: RiskParams` | `RiskVerdict` | Ana risk kontrolu: kill-switch, aylik, gunluk, haftalik, hard DD, floating, gunluk sayac, ust uste kayip |
| `check_correlation_limits` | `self, symbol: str, direction: str, risk_params: RiskParams` | `RiskVerdict` | Korelasyon kontrolu: ayni yon max 3, ayni sektor max 2, endeks agirlik skoru < 0.25 |
| `increment_daily_trade_count` | `self` | `None` | Gunluk islem sayacini artir (Ogul islem actiginda cagrilir) |
| `acknowledge_kill_switch` | `self, user: str = "operator"` | `bool` | Manuel kill-switch onayi; L3/monthly_paused sifirlar; True ise onay basarili |
| `activate_kill_switch_l1` | `self, symbol: str, reason: str` | `None` | L1: tek kontrat durdur (anomali tespitinde disardan cagrilir) |
| `activate_kill_switch_l3_manual` | `self, user: str = "operator"` | `None` | L3: manuel tam kapanma (Desktop 2sn basili tut + onayla) |
| `is_symbol_killed` | `self, symbol: str` | `bool` | Sembol L1 ile durdurulmus mu |
| `restore_risk_state` | `self` | `None` | Engine restart sonrasi kill-switch ve cooldown durumunu DB'den geri yukle |
| `analyze_fake_signals` | `self` | `list[FakeAnalysis]` | Tum acik pozisyonlar icin fake sinyal analizi; skor >= esik ise otomatik kapat |

### Kimler Cagiriyor

- `run_cycle` → `main.py` her 10sn cycle'da
- `detect_regime` → `run_cycle` icinden
- `check_early_warnings` → `run_cycle` icinden
- `calculate_position_size` → `ogul.py` `_calculate_lot` icinden
- `check_drawdown_limits` → `check_risk_limits` icinden
- `check_risk_limits` → `main.py` her cycle'da
- `check_correlation_limits` → `ogul.py` `_execute_signal` icinden
- `increment_daily_trade_count` → `ogul.py` islem acildiginda
- `acknowledge_kill_switch` → API route (Desktop UI'dan)
- `activate_kill_switch_l1` → `_evaluate_kill_switch_triggers` icinden veya disardan
- `activate_kill_switch_l3_manual` → API route (Desktop UI'dan)
- `is_symbol_killed` → `ogul.py` `process_signals` icinden
- `restore_risk_state` → `main.py` engine baslangicinda
- `analyze_fake_signals` → `run_cycle` icinden

---

## 3. PRIVATE METODLAR

| Metod | Parametreler | Donus | Ozet |
|---|---|---|---|
| `_classify_symbol` | `self, symbol: str` | `dict[str, Any] \| None` | Tek sembol icin M5 barlariyla VOLATILE/TREND/RANGE siniflandirmasi |
| `_check_trend` (static) | `adx_val: float, ema_fast: ndarray, ema_slow: ndarray, close: ndarray` | `bool` | TREND kosuluplarinini dogrula: ADX>25, EMA mesafesi artiyor, 4/5 bar ayni yon |
| `_check_olay` | `self` | `dict[str, Any] \| None` | OLAY kosullari: merkez bankasi tarihleri, VIOP vade, USD/TRY soku |
| `_check_spread_spike` | `self, symbol: str, liq_class: str` | `EarlyWarning \| None` | Spread spike erken uyarisi: A 3x, B 4x, C 5x |
| `_check_price_shock` | `self, symbol: str, liq_class: str` | `EarlyWarning \| None` | Fiyat soku erken uyarisi: A %1.5, B %2, C %3 |
| `_check_volume_spike` | `self, symbol: str` | `EarlyWarning \| None` | Volume spike: 5dk volume > ortalama x 5 |
| `_check_usdtry_shock` | `self` | `EarlyWarning \| None` | USD/TRY 5dk soku: >= %0.5 |
| `_check_period_resets` | `self` | `None` | Gunluk/haftalik/aylik periyod sifirlamalarini kontrol et |
| `_reset_daily` | `self, today: date` | `None` | Gunluk islem sayacini sifirla, daily_loss L2 temizle |
| `_reset_weekly` | `self, week_tuple: tuple` | `None` | weekly_loss_halved flag'ini sifirla |
| `_reset_monthly` | `self, month_tuple: tuple` | `None` | Aylik periyod isaretcisini sifirla (monthly_paused sifirlanmaz — manuel onay gerekir) |
| `_check_weekly_loss` | `self, risk_params: RiskParams` | `str \| None` | Haftalik kayip kontrolu; >= %4 ise "halved" doner |
| `_check_monthly_loss` | `self, risk_params: RiskParams` | `bool` | Aylik kayip >= %7 kontrolu; True ise limit asildi |
| `_check_hard_drawdown` | `self, risk_params: RiskParams` | `str \| None` | DD >= %15 ise "hard", DD >= %10 ise "soft" doner |
| `_check_floating_loss` | `self, risk_params: RiskParams` | `bool` | Floating kayip >= equity %1.5 ise True |
| `_update_consecutive_losses` | `self` | `None` | DB islemlerinden ust uste kayip sayacini guncelle (RISK_BASELINE_DATE sonrasi) |
| `_start_cooldown` | `self, risk_params: RiskParams` | `None` | 4 saatlik cooldown zamanlayicisi baslatir |
| `_is_in_cooldown` | `self` | `bool` | Cooldown aktif mi; suresi dolduysa otomatik temizler |
| `_activate_kill_switch` | `self, level: int, reason: str, message: str, symbols: list[str] \| None = None` | `None` | Kill-switch aktive et (sadece yukari eskalasyon: L1->L2 tamam, L2->L1 engelli) |
| `_clear_kill_switch` | `self, reason: str` | `None` | Kill-switch'i L0'a temizle, killed_symbols bosalt |
| `_close_all_positions` | `self, reason: str` | `None` | Tum acik MT5 pozisyonlarini kapat (L3 icin) |
| `_evaluate_kill_switch_triggers` | `self` | `None` | CRITICAL erken uyarilari L1'e, OLAY rejimi L2'ye degerlendir; olay_regime L2 otomatik temizle |
| `_calculate_index_weight_score` | `self, positions: list[dict], new_symbol: str, new_direction: str, new_lot: float = 1.0` | `float` | XU030 endeks agirlik skoru: abs(sum(lot * weight * sign)) |
| `_get_liquidity_class` | `self, symbol: str` | `str` | Sembolun likidite sinifini DB'den al (varsayilan "C") |
| `_current_spread_multiple` | `self, symbol: str` | `float` | Guncel spread / ortalama spread |
| `_update_spread_history` | `self, pipeline` | `None` | Pipeline tick'lerinden spread ring buffer guncelle |
| `_update_usdtry_history` | `self` | `None` | MT5'ten USD/TRY fiyat gecmisini guncelle |
| `_usdtry_5m_move_pct` | `self` | `float` | USD/TRY buffer penceresi uzerindeki yuzde hareketi doner |
| `_analyze_fake_signal` | `self, symbol: str, direction: str, ticket: int` | `FakeAnalysis` | Tek pozisyon icin 4 katmanli fake sinyal analizi |
| `_fake_check_volume` | `self, symbol: str` | `FakeLayerResult` | Fake katman 1: volume orani < 0.7 = FAKE (agirlik 1) |
| `_fake_check_spread` | `self, symbol: str` | `FakeLayerResult` | Fake katman 2: spread carpani > esik = FAKE (agirlik 2) |
| `_fake_check_multi_tf` | `self, symbol: str, direction: str` | `FakeLayerResult` | Fake katman 3: M5/M15/H1 EMA-9 yon uyumu < 2/3 = FAKE (agirlik 1) |
| `_fake_check_momentum` | `self, symbol: str, direction: str` | `FakeLayerResult` | Fake katman 4: RSI asiri + MACD histogram uyumsuzlugu = FAKE (agirlik 2) |

### Modul Seviyesi Yardimci Fonksiyonlar

| Fonksiyon | Parametreler | Donus | Ozet |
|---|---|---|---|
| `_last_valid` | `arr: np.ndarray` | `float \| None` | Dizideki son NaN olmayan deger |
| `_nanmean` | `arr: np.ndarray` | `float` | NaN olmayan degerlerin ortalamasi (tumu NaN ise 0.0) |
| `_volatile_reason` | `atr_ratio: float, spread_mult: float, move_pct: float` | `str` | Okunabilir VOLATILE neden metni olusturur |

---

## 4. REJIM ALGILAMA

### Oncelik Sirasi: OLAY > VOLATILE > TREND > RANGE

### `detect_regime()` Akisi

1. `_check_olay()` cagir — None degilse hemen `RegimeType.OLAY` (confidence=1.0) don
2. 15 WATCHED_SYMBOLS icin `_classify_symbol()` cagir, her biri VOLATILE/TREND/RANGE oyu verir
3. VOLATILE oylari >= toplam %30 -> sistem VOLATILE
4. Aksi halde en cok oy alan rejim kazanir
5. Confidence = kazanan oylar / toplam oylar
6. Gecerli veri ureten sembol yoksa (toplam=0), varsayilan RANGE confidence=0.0

### OLAY Rejimi

**3 tetikleyici (sirayla kontrol edilir):**

1. Bugun `CENTRAL_BANK_DATES` icinde mi → `{"reason": "TCMB/FED toplanti gunu", "trigger": "calendar"}`
2. Herhangi bir `VIOP_EXPIRY_DATES` tarihi 0-2 gun icinde mi → `{"reason": "Vade bitis: {tarih} ({gun} gun kaldi)", "trigger": "expiry"}`
3. `_usdtry_5m_move_pct()` >= `USDTRY_SHOCK_PCT` (2.0) → `{"reason": "USD/TRY soku: %{deger} (5dk)", "trigger": "usdtry"}`

Herhangi biri True ise OLAY aktif. None donerse OLAY degil.

### VOLATILE Rejimi (sembol bazli)

Asagidakilerden herhangi biri:
- `atr_ratio > 2.0` (ATR_VOLATILE_MULT) — guncel ATR / ortalama ATR (M5)
- `spread_mult > 3.0` (SPREAD_VOLATILE_MULT) — guncel spread / ortalama spread
- `last_move_pct > 2.0` (PRICE_MOVE_PCT) — son M5 bar mutlak yuzde hareketi

Sistem geneli: Sembollerin >= %30'u VOLATILE oylarsa -> tum piyasa VOLATILE

### TREND Rejimi (sembol bazli, UC KOSUL BIRDEN)

1. ADX > 25.0 (ADX_TREND_THRESHOLD), M5 barlari, periyot 14
2. |EMA_fast(9) - EMA_slow(21)| mesafesi ARTIYOR (son 6 degerin ilki < sonu)
3. Son 5 bar: en az 4/5 ayni yone hareket (up >= 4 veya down >= 4)

### RANGE Rejimi (sembol bazli)

- ADX < 20.0 (ADX_RANGE_THRESHOLD) VE BB genislik orani < 0.8 (BB_WIDTH_RATIO)
- BB genislik orani = guncel BB genisligi / ortalama BB genisligi
- ADX 20-25 belirsiz bolgede varsayilan

### `_classify_symbol` Mantigi

- M5 barlari alir (limit=100)
- En az max(14*3, 20+10) = 42 bar gerekli
- Hesaplar: ADX(14), ATR(14), EMA(9), EMA(21), BB(20, 2.0)
- Oncelik: VOLATILE > TREND > RANGE
- Varsayilan RANGE

---

## 5. KILL-SWITCH SISTEMI

### Seviyeler ve Sabitleri

| Sabit | Deger | Ad |
|---|---|---|
| `KILL_SWITCH_NONE` | 0 | Kill-switch yok |
| `KILL_SWITCH_L1` | 1 | Kontrat durdurma |
| `KILL_SWITCH_L2` | 2 | Sistem duraklatma |
| `KILL_SWITCH_L3` | 3 | Tam kapanma |

### Tetikleme Kosullari

**L1 (kontrat durdurma):**
- Belirli sembol icin CRITICAL erken uyari (`_evaluate_kill_switch_triggers`)
- Disardan `activate_kill_switch_l1(symbol, reason)` ile
- Mevcut seviye > L1 ise seviyeyi yukseltmez (sadece sembolu killed set'e ekler)

**L2 (sistem duraklatma):**
- OLAY rejimi algilandi (neden: `"olay_regime"`)
- Gunluk kayip limiti asildi (neden: `"daily_loss"`)
- Aylik kayip limiti asildi (neden: `"monthly_loss"`)
- Ust uste kayip limiti (neden: `"consecutive_loss"`)

**L3 (tam kapanma):**
- Hard drawdown >= %15 (neden: `"hard_drawdown"`)
- Max drawdown >= %10 (neden: `"max_drawdown"`)
- Manuel aktivasyon `activate_kill_switch_l3_manual()` (neden: `"manual"`)

### Her Seviyede Ne Oluyor

- **L1:** Sembol `_killed_symbols` set'ine eklenir. `is_symbol_killed()` True doner. Sistem geneli etki yok.
- **L2:** `check_risk_limits` `can_trade=False, lot_multiplier=0.0` doner. Tum yeni islemler engellenir.
- **L3:** L2 ile ayni + `_close_all_positions()` cagrilir — tum acik MT5 pozisyonlari hemen kapatilir.

### Eskalasyon Kurali

Kill-switch sadece yukari eskalasyon yapar: `if level <= self._kill_switch_level: return` (L1->L2 tamam, L2->L1 engelli)

### Sifirlama Kosullari

| Neden | Sifirlama Yontemi |
|---|---|
| L2 `daily_loss` | Sonraki islem gunu 09:30'da otomatik (`_reset_daily`) |
| L2 `olay_regime` | OLAY rejimi sona erdiginde otomatik (`_evaluate_kill_switch_triggers`) |
| L2 `consecutive_loss` | Cooldown suresi dolunca (`_is_in_cooldown`) |
| L2 `monthly_loss` | Manuel `acknowledge_kill_switch()` gerekli |
| L3 herhangi neden | Manuel `acknowledge_kill_switch()` gerekli |
| L1 | `_clear_kill_switch()` cagrildiginda (acknowledge ile) |

### `acknowledge_kill_switch` Mantigi

1. Seviye NONE ise False don
2. DB'ye intervention kaydi ekle
3. `monthly_paused = False` sifirla
4. `_clear_kill_switch()` cagir → seviye 0, detaylar ve killed_symbols temizle
5. True don

### Persist/Restore Mantigi (`restore_risk_state`)

- DB'den son `KILL_SWITCH` event'ini oku
- Action `LEVEL_X` ve X != 0 ise, o seviyeyi `"restored_from_db"` nedeniyle geri yukle
- Son `COOLDOWN` event'ini oku; `cooldown_start` varsa ve bitis zamani hala gelecekteyse, cooldown_until geri yukle

---

## 6. POZISYON BOYUTLAMA

### `calculate_position_size` Tam Mantigi

**Formul:**
```
lot = (equity * effective_risk * regime_multiplier) / (ATR * contract_size)
```

**Adimlar:**

1. `atr_value <= 0` veya `account_equity <= 0` ise: 0.0 don
2. Rejim risk carpanini al (`self.current_regime.risk_multiplier`)
3. Carpan == 0 ise: 0.0 don (OLAY rejimi tum islemleri engeller)
4. `effective_risk = min(risk_params.risk_per_trade, risk_params.max_risk_per_trade_hard)` — hard cap %2
5. `risk_amount = equity * effective_risk * mult`
6. MT5 sembol bilgisinden `contract_size` (varsayilan 100.0), `vol_min` (varsayilan 1.0), `vol_step` (varsayilan 1.0) al
7. `lot = risk_amount / (atr_value * contract_size)`
8. `vol_step`'e asagi yuvarla: `lot = floor(lot / vol_step) * vol_step`
9. `lot >= 0.0` garanti et
10. `risk_params.max_position_size` ile sinirla
11. **Haftalik yarilama:** `weekly_loss_halved` True ise, lot * 0.5 ve floor vol_step'e
12. `round(lot, 2)` don

### Rejim Bazli Carplanlar

```python
RISK_MULTIPLIERS = {
    RegimeType.TREND:    1.0,
    RegimeType.RANGE:    0.7,
    RegimeType.VOLATILE: 0.25,
    RegimeType.OLAY:     0.0,
}
```

---

## 7. ZARAR LIMITLERI

### Esikler (Sabitler)

| Sabit | Deger | Aciklama |
|---|---|---|
| `MAX_WEEKLY_LOSS_PCT` | 0.04 (%4) | Haftalik kayip → lot yarilama |
| `MAX_MONTHLY_LOSS_PCT` | 0.07 (%7) | Aylik kayip → sistem durdurma |
| `HARD_DRAWDOWN_PCT` | 0.15 (%15) | Hard drawdown → tam kapanma |
| `MAX_FLOATING_LOSS_PCT` | 0.015 (%1.5) | Floating kayip → yeni islem engeli |
| `CONSECUTIVE_LOSS_LIMIT` | 3 | Ust uste kayip → 4 saat cooldown |
| `COOLDOWN_HOURS` | 4 | Cooldown suresi |
| `MAX_DAILY_TRADES` | 5 | Gunluk max islem sayisi |
| `MAX_RISK_PER_TRADE_HARD` | 0.02 (%2) | Islem basina risk hard cap |

### `check_risk_limits` Kontrol Sirasi

1. **Kill-switch L3 aktif:** can_trade=False, lot_multiplier=0.0
2. **Kill-switch L2 aktif:** can_trade=False
3. **monthly_paused:** can_trade=False (manuel onay bekleniyor)
4. **Gunluk kayip** (`check_drawdown_limits`): daily_pnl/equity >= max_daily_loss → L2 aktive, can_trade=False
5. **Hard drawdown** (`_check_hard_drawdown`): drawdown >= 0.15 → L3 "hard"; drawdown >= max_total_drawdown (0.10) → L3 "soft"
6. **Aylik kayip** (`_check_monthly_loss`): (ay_baslangic_equity - guncel) / ay_baslangic >= 0.07 → monthly_paused=True, L2
7. **Haftalik kayip** (`_check_weekly_loss`): (hafta_baslangic_equity - guncel) / hafta_baslangic >= 0.04 → lot_multiplier=0.5 (engellemez)
8. **Floating kayip** (`_check_floating_loss`): abs(floating_pnl)/equity >= 0.015 → can_trade=False
9. **Gunluk islem sayaci:** >= max_daily_trades (5) → can_trade=False
10. **Cooldown aktif:** can_trade=False
11. **Ust uste kayip:** >= 3 → cooldown baslatilir, L2, can_trade=False

### `check_drawdown_limits` (ayri metod)

- DB'den son risk snapshot'ini alir
- `daily_pnl < 0` ve `abs(daily_pnl / equity) >= max_daily_loss` → False (dur)
- `drawdown >= max_total_drawdown` → False (dur)
- Aksi halde True (devam)

### Baseline Tarihi

`RISK_BASELINE_DATE = "2026-02-23"` — Bu tarihten onceki islemler ve snapshot'lar haftalik/aylik kayip ve ust uste kayip hesaplamalarindan haric tutulur.

---

## 8. ERKEN UYARI SISTEMI

### `check_early_warnings` Akisi

15 WATCHED_SYMBOLS icin 3 kosul kontrol edilir. Sonra USDTRY ayri kontrol edilir.

### Spread Spike (`_check_spread_spike`)

- spread_history'de >= 5 kayit gerekli
- `mult = guncel_spread / ort(gecmis[:-1])`
- Esikler: A >= 3.0x, B >= 4.0x, C >= 5.0x (`SPREAD_SPIKE_MULT`)
- Siddet: `mult >= esik * 1.5` ise CRITICAL, aksi halde WARNING

### Price Shock (`_check_price_shock`)

- M1 barlari alir (limit=2)
- `move_pct = abs(close[-1] - close[-2]) / close[-2] * 100`
- Esikler: A >= %1.5, B >= %2.0, C >= %3.0 (`PRICE_SHOCK_PCT`)
- Siddet: `move_pct >= esik * 1.5` ise CRITICAL, aksi halde WARNING

### Volume Spike (`_check_volume_spike`)

- M5 barlari alir (limit=50), en az 10 gerekli
- `mult = guncel_vol / ort(vol[:-1])`
- Esik: >= 5.0x (`VOLUME_SPIKE_MULT`) tum siniflar icin
- Siddet: `mult >= 10.0` (VOLUME_SPIKE_MULT * 2) ise CRITICAL, aksi halde WARNING

### USD/TRY Soku (`_check_usdtry_shock`)

- `move = _usdtry_5m_move_pct()`
- Esik: >= %0.5 (`USDTRY_5M_SHOCK_PCT`)
- Siddet: `move >= 1.0` ise CRITICAL, aksi halde WARNING
- Sembol: "USDTRY", likidite sinifi: "ALL"

Tum tetiklenen uyarilar DB'ye `EARLY_WARNING` event olarak yazilir.

---

## 9. KORELASYON YONETIMI

### `check_correlation_limits` Mantigi (3 kontrol)

**1. Ayni yon limiti:**
- Ayni `type` (BUY/SELL) ile pozisyon sayisi sayilir
- Sayi >= `risk_params.max_same_direction` (varsayilan 3) ise engellenir

**2. Ayni sektor ayni yon limiti:**
- Ayni sektor + ayni yon pozisyon sayisi sayilir
- Sektor esleme: `SYMBOL_TO_SECTOR` dict
- Sayi >= `risk_params.max_same_sector_direction` (varsayilan 2) ise engellenir

**3. Endeks agirlik skoru:**
- `_calculate_index_weight_score()`: `abs(sum(lot_i * xu030_weight_i * sign_i))` tum mevcut pozisyonlar + onerilen yeni pozisyon icin
- BUY = +1, SELL = -1
- Skor > `risk_params.max_index_weight_score` (varsayilan 0.25) ise engellenir

### Korelasyon Sabitleri

```python
MAX_SAME_DIRECTION = 3
MAX_SAME_SECTOR_DIRECTION = 2
MAX_INDEX_WEIGHT_SCORE = 0.25
```

---

## 10. OLAY KONTROLU

### `_check_olay` Tam Mantigi

```python
def _check_olay(self) -> dict[str, Any] | None:
    today = date.today()

    # 1. Merkez bankasi toplanti gunu
    if today in CENTRAL_BANK_DATES:
        return {"reason": "TCMB/FED toplanti gunu", "trigger": "calendar"}

    # 2. VIOP vade bitisi 2 gun icinde
    for expiry in VIOP_EXPIRY_DATES:
        days = (expiry - today).days
        if 0 <= days <= EXPIRY_DAYS:
            return {"reason": f"Vade bitis: {expiry} ({days} gun kaldi)", "trigger": "expiry"}

    # 3. USD/TRY soku >= %2
    usdtry_move = self._usdtry_5m_move_pct()
    if usdtry_move >= USDTRY_SHOCK_PCT:
        return {"reason": f"USD/TRY soku: %{usdtry_move:.2f} (5dk)", "trigger": "usdtry", "value": usdtry_move}

    return None
```

### CENTRAL_BANK_DATES (Tum Tarihler)

```
# 2025 TCMB PPK (12 tarih)
2025-01-23, 2025-02-20, 2025-03-20, 2025-04-17, 2025-05-22, 2025-06-19,
2025-07-24, 2025-08-21, 2025-09-18, 2025-10-23, 2025-11-20, 2025-12-25

# 2025 FED FOMC (8 tarih)
2025-01-29, 2025-03-19, 2025-05-07, 2025-06-18, 2025-07-30, 2025-09-17,
2025-10-29, 2025-12-10

# 2026 TCMB (tahmini, 6 tarih)
2026-01-22, 2026-02-19, 2026-03-19, 2026-04-16, 2026-05-21, 2026-06-18
```

### VIOP_EXPIRY_DATES (Tum Tarihler)

```
# 2025 (12 tarih)
2025-01-31, 2025-02-28, 2025-03-31, 2025-04-30, 2025-05-30, 2025-06-30,
2025-07-31, 2025-08-29, 2025-09-30, 2025-10-31, 2025-11-28, 2025-12-31

# 2026 (3 tarih)
2026-01-30, 2026-02-27, 2026-03-31
```

### Esikler

```python
USDTRY_SHOCK_PCT = 2.0    # OLAY tetikleyicisi
EXPIRY_DAYS = 2            # Vade bitisine kalan gun esigi
```

---

## 11. SABITLER VE ESIKLER

### Rejim Esikleri

| Sabit | Tip | Deger | Aciklama |
|---|---|---|---|
| `ADX_TREND_THRESHOLD` | `float` | `25.0` | TREND icin minimum ADX |
| `ADX_RANGE_THRESHOLD` | `float` | `20.0` | RANGE icin maksimum ADX |
| `EMA_DIRECTION_BARS` | `int` | `5` | Son N bar yon kontrolu |
| `EMA_DIRECTION_MIN` | `int` | `4` | N bardan en az kaci ayni yonde olmali |
| `BB_WIDTH_RATIO` | `float` | `0.8` | BB genislik orani esigi |
| `ATR_VOLATILE_MULT` | `float` | `2.0` | VOLATILE icin ATR carpani |
| `SPREAD_VOLATILE_MULT` | `float` | `3.0` | VOLATILE icin spread carpani |
| `PRICE_MOVE_PCT` | `float` | `2.0` | VOLATILE icin fiyat hareketi % |

### OLAY Esikleri

| Sabit | Tip | Deger | Aciklama |
|---|---|---|---|
| `USDTRY_SHOCK_PCT` | `float` | `2.0` | OLAY tetikleme esigi |
| `EXPIRY_DAYS` | `int` | `2` | Vade bitisine kalan gun |

### Erken Uyari Esikleri

| Sabit | Tip | Deger | Aciklama |
|---|---|---|---|
| `SPREAD_SPIKE_MULT` | `dict` | `{"A": 3.0, "B": 4.0, "C": 5.0}` | Sinif bazli spread spike |
| `PRICE_SHOCK_PCT` | `dict` | `{"A": 1.5, "B": 2.0, "C": 3.0}` | Sinif bazli fiyat soku % |
| `VOLUME_SPIKE_MULT` | `float` | `5.0` | Volume spike carpani |
| `USDTRY_5M_SHOCK_PCT` | `float` | `0.5` | USDTRY erken uyari esigi |

### Hesaplama Sabitleri

| Sabit | Tip | Deger | Aciklama |
|---|---|---|---|
| `EMA_FAST` | `int` | `9` | Hizli EMA periyodu (rejim siniflandirma) |
| `EMA_SLOW` | `int` | `21` | Yavas EMA periyodu (rejim siniflandirma) |
| `ADX_PERIOD` | `int` | `14` | ADX hesaplama periyodu |
| `ATR_PERIOD` | `int` | `14` | ATR hesaplama periyodu |
| `BB_PERIOD` | `int` | `20` | Bollinger Band periyodu |
| `BB_STD` | `float` | `2.0` | Bollinger Band std sapma |
| `ATR_LOOKBACK` | `int` | `100` | ATR lookback penceresi |

### Cok Katmanli Zarar Limitleri

| Sabit | Tip | Deger | Aciklama |
|---|---|---|---|
| `MAX_WEEKLY_LOSS_PCT` | `float` | `0.04` | Haftalik kayip %4 → lot yarilama |
| `MAX_MONTHLY_LOSS_PCT` | `float` | `0.07` | Aylik kayip %7 → sistem durdurma |
| `HARD_DRAWDOWN_PCT` | `float` | `0.15` | Hard DD %15 → tam kapanma |
| `CONSECUTIVE_LOSS_LIMIT` | `int` | `3` | Ust uste kayip → cooldown |
| `COOLDOWN_HOURS` | `int` | `4` | Cooldown suresi (saat) |
| `MAX_FLOATING_LOSS_PCT` | `float` | `0.015` | Floating kayip %1.5 → yeni islem engeli |
| `MAX_DAILY_TRADES` | `int` | `5` | Gunluk max islem |
| `MAX_RISK_PER_TRADE_HARD` | `float` | `0.02` | Islem basina risk %2 hard cap |

### Korelasyon Sabitleri

| Sabit | Tip | Deger | Aciklama |
|---|---|---|---|
| `MAX_SAME_DIRECTION` | `int` | `3` | Ayni yon max pozisyon |
| `MAX_SAME_SECTOR_DIRECTION` | `int` | `2` | Ayni sektor ayni yon max |
| `MAX_INDEX_WEIGHT_SCORE` | `float` | `0.25` | Endeks agirlik skor limiti |

### Fake Sinyal Sabitleri

| Sabit | Tip | Deger | Aciklama |
|---|---|---|---|
| `FAKE_SCORE_THRESHOLD` | `int` | `3` | Otomatik kapanis esigi |
| `FAKE_VOLUME_RATIO_MIN` | `float` | `0.7` | Volume oran alt siniri |
| `FAKE_VOLUME_LOOKBACK` | `int` | `20` | Volume lookback bar sayisi |
| `FAKE_SPREAD_MULT` | `dict` | `{"A": 2.5, "B": 3.5, "C": 5.0}` | Sinif bazli spread esigi |
| `FAKE_MTF_EMA_PERIOD` | `int` | `9` | MTF EMA periyodu |
| `FAKE_MTF_AGREEMENT_MIN` | `int` | `2` | Minimum TF uyum sayisi |
| `FAKE_RSI_OVERBOUGHT` | `float` | `80.0` | RSI asiri alim (fake) |
| `FAKE_RSI_OVERSOLD` | `float` | `20.0` | RSI asiri satim (fake) |
| `FAKE_RSI_PERIOD` | `int` | `14` | RSI periyodu (fake) |
| `FAKE_WEIGHT_VOLUME` | `int` | `1` | Volume katman agirligi |
| `FAKE_WEIGHT_SPREAD` | `int` | `2` | Spread katman agirligi |
| `FAKE_WEIGHT_MULTI_TF` | `int` | `1` | MTF katman agirligi |
| `FAKE_WEIGHT_MOMENTUM` | `int` | `2` | Momentum katman agirligi |

### Kill-Switch Sabitleri

| Sabit | Tip | Deger |
|---|---|---|
| `KILL_SWITCH_NONE` | `int` | `0` |
| `KILL_SWITCH_L1` | `int` | `1` |
| `KILL_SWITCH_L2` | `int` | `2` |
| `KILL_SWITCH_L3` | `int` | `3` |

### Risk Baseline

| Sabit | Tip | Deger |
|---|---|---|
| `RISK_BASELINE_DATE` | `str` | `"2026-02-23"` |

### Sektor Eslemesi

```python
SYMBOL_TO_SECTOR = {
    "F_THYAO": "havacilik", "F_AKBNK": "banka", "F_ASELS": "teknoloji",
    "F_TCELL": "teknoloji", "F_HALKB": "banka", "F_PGSUS": "havacilik",
    "F_GUBRF": "kimya", "F_EKGYO": "gayrimenkul", "F_SOKM": "perakende",
    "F_TKFEN": "holding", "F_OYAKC": "sanayi", "F_BRSAN": "sanayi",
    "F_AKSEN": "enerji", "F_ASTOR": "enerji", "F_KONTR": "diger",
}
```

### XU030 Endeks Agirliklari

```python
XU030_WEIGHTS = {
    "F_THYAO": 0.12, "F_AKBNK": 0.08, "F_ASELS": 0.07, "F_TCELL": 0.05,
    "F_HALKB": 0.03, "F_PGSUS": 0.04, "F_GUBRF": 0.02, "F_EKGYO": 0.03,
    "F_SOKM": 0.02, "F_TKFEN": 0.03, "F_OYAKC": 0.01, "F_BRSAN": 0.01,
    "F_AKSEN": 0.02, "F_ASTOR": 0.01, "F_KONTR": 0.00,
}
```

---

## 12. BAGIMLILIKLAR

### Import'lar

**Standart kutuphane:**
```python
from __future__ import annotations
import math  # floor
from datetime import date, datetime, timedelta
from typing import Any
import numpy as np
```

**Dahili moduller:**
```python
from engine.config import Config
from engine.database import Database
from engine.logger import get_logger
from engine.models.regime import EarlyWarning, Regime, RegimeType, RISK_MULTIPLIERS
from engine.models.risk import RiskParams, RiskVerdict, FakeAnalysis, FakeLayerResult
from engine.mt5_bridge import MT5Bridge, WATCHED_SYMBOLS
from engine.utils.indicators import (
    adx as calc_adx,
    atr as calc_atr,
    ema,
    bollinger_bands,
    rsi as calc_rsi,
    macd as calc_macd,
)
```

### MT5Bridge'den Ne Aliyor

| Cagri | Donus | Kullanim |
|---|---|---|
| `mt5.get_positions()` | `list[dict]` (symbol, type, ticket, volume) | Acik pozisyon listesi |
| `mt5.get_symbol_info(symbol)` | trade_contract_size, volume_min, volume_step | Pozisyon boyutlama |
| `mt5.get_tick("USDTRY")` | tick.bid | USDTRY fiyat gecmisi |
| `mt5.close_position(ticket)` | `bool` | L3 tam kapanma ve fake sinyal kapatma |
| `WATCHED_SYMBOLS` | `list[str]` | 15 sembol listesi |

### Database'den Ne Aliyor

| Cagri | Donus | Kullanim |
|---|---|---|
| `db.get_bars(symbol, timeframe, limit)` | `DataFrame` | Rejim siniflandirma ve fake analiz |
| `db.get_latest_risk_snapshot()` | `dict` (daily_pnl, equity, drawdown, floating_pnl) | Risk limitleri |
| `db.get_risk_snapshots(since, limit)` | `list[dict]` | Haftalik/aylik kayip hesaplama |
| `db.get_trades(symbol, limit)` | `list[dict]` | Ust uste kayip ve fake analiz |
| `db.get_events(event_type, limit)` | `list[dict]` | Kill-switch restore |
| `db.get_liquidity(target_date, symbol)` | `list` | Likidite sinifi |
| `db.insert_event(...)` | — | Event kaydi |
| `db.insert_intervention(...)` | — | Kill-switch onay kaydi |
| `db.update_trade(...)` | — | Fake skor guncelleme |

### Diger Modullere Ne Veriyor

| Alan/Metod | Tuketici | Aciklama |
|---|---|---|
| `current_regime: Regime` | `main.py`, `ogul.py` | Guncel rejim (tip, carpan, guven, detaylar) |
| `active_warnings: list[EarlyWarning]` | `main.py`, API | Aktif erken uyarilar |
| `check_risk_limits(risk_params)` | `main.py` | RiskVerdict (can_trade, lot_multiplier, reason, kill_switch_level) |
| `check_correlation_limits(symbol, direction, risk_params)` | `ogul.py` | Korelasyon onayi |
| `calculate_position_size(symbol, risk_params, atr_value, equity)` | `ogul.py` | Lot hesaplama |
| `is_symbol_killed(symbol)` | `ogul.py` | L1 sembol kontrolu |
| `increment_daily_trade_count()` | `ogul.py` | Gunluk sayac |
| `activate_kill_switch_l1(symbol, reason)` | `ogul.py`, API | L1 aktivasyon |
| `activate_kill_switch_l3_manual(user)` | API | L3 manuel aktivasyon |
| `acknowledge_kill_switch(user)` | API | Kill-switch onaylama |
| `analyze_fake_signals()` | `main.py` | Fake sinyal analiz sonuclari |
| `restore_risk_state()` | `main.py` | Restart sonrasi durum geri yukleme |
