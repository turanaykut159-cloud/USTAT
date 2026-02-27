# OGUL_YAPI.md — OGUL (Sinyal Uretici + Emir State Machine)

Kaynak: `engine/ogul.py` (2161 satir)

---

## 1. SINIF YAPISI

### Class: `Ogul`

- Inheritance: Yok (plain class)
- Docstring: "Sinyal uretici ve emir yoneticisi. Her 10 saniyede `process_signals()` cagrilir. 3 strateji: trend follow, mean reversion, breakout."

### `__init__` Parametreleri

```python
def __init__(
    self,
    config: Config,
    mt5: MT5Bridge,
    db: Database,
    baba: Any | None = None,
) -> None
```

### Instance Degiskenleri

| Degisken | Tip | Baslangic Degeri |
|---|---|---|
| `self.config` | `Config` | `config` parametresi |
| `self.mt5` | `MT5Bridge` | `mt5` parametresi |
| `self.db` | `Database` | `db` parametresi |
| `self.baba` | `Any \| None` | `baba` parametresi (default `None`) |
| `self.active_trades` | `dict[str, Trade]` | `{}` |
| `self.last_signals` | `dict[str, str]` | `{}` — symbol -> "BUY"/"SELL"/"BEKLE" |

---

## 2. PUBLIC METODLAR

| Metod | Parametreler | Donus | Ozet |
|---|---|---|---|
| `process_signals` | `symbols: list[str], regime: Regime` | `None` | Ana giris noktasi (10sn cycle): gun sonu kontrol, emir ilerleme, aktif islem yonetimi, pozisyon senkron, bias hesaplama, sinyal uretim ve calistirma |
| `restore_active_trades` | (yok) | `None` | Engine restart sonrasi `active_trades` dict'ini MT5 acik pozisyonlar + DB kayitlarindan yeniden olusturur |

### Kimler Cagiriyor

- `process_signals` → `main.py` her 10sn cycle'da
- `restore_active_trades` → `main.py` engine baslangicinda

---

## 3. PRIVATE METODLAR

| Metod | Parametreler | Donus | Ozet |
|---|---|---|---|
| `_calculate_bias` | `symbol: str` | `str` | RSI(14) + EMA(20/50) crossover + MACD histogram ile cogunluk oyu; "BUY"/"SELL"/"NOTR" doner |
| `_generate_signal` | `symbol: str, regime: Regime, strategies: list[StrategyType]` | `Signal \| None` | Aktif stratejileri calistirir, en guclu sinyali secer; trend follow ise H1 onay gerektirir |
| `_check_trend_follow` | `symbol: str, close: ndarray, high: ndarray, low: ndarray, volume: ndarray` | `Signal \| None` | EMA(20)xEMA(50) crossover + ADX>25 + MACD histogram 2-bar onayi |
| `_check_mean_reversion` | `symbol: str, close: ndarray, high: ndarray, low: ndarray, volume: ndarray` | `Signal \| None` | RSI(14) asiri bolgeler + Bollinger Band dokunusu + ADX<20 |
| `_check_breakout` | `symbol: str, close: ndarray, high: ndarray, low: ndarray, volume: ndarray` | `Signal \| None` | 20-bar high/low kirimi + volume>1.5x ort + ATR genislemesi>1.2x |
| `_confirm_h1` | `symbol: str, signal: Signal` | `bool` | H1 timeframe trend onayi: BUY icin H1 EMA(20)>EMA(50), SELL icin H1 EMA(20)<EMA(50) |
| `_execute_signal` | `signal: Signal, regime: Regime` | `None` | Sinyal-emir pipeline: Trade(SIGNAL) olustur, BABA korelasyon kontrol, on-ucus kontrolleri, LIMIT emir gonder |
| `_calculate_lot` | `signal: Signal, regime: Regime, equity: float, risk_params: RiskParams` | `float` | Pozisyon boyutlama: BABA'nin `calculate_position_size` kullanir, yoksa fallback 1 lot; `MAX_LOT_PER_CONTRACT` ile sinirli |
| `_get_current_atr` | `symbol: str` | `float \| None` | M15 barlarindan guncel ATR(14) degerini alir |
| `_log_cancelled_trade` | `trade: Trade` | `None` | Iptal edilen islemi DB event ve logger'a yazar |
| `_remove_trade` | `symbol: str, trade: Trade, reason: str` | `None` | `active_trades`'den cikarir, CANCELLED yapar, DB'ye exit_time/exit_reason yazar |
| `_advance_orders` | `regime: Regime` | `None` | State machine dispatcher: SENT/PARTIAL/TIMEOUT/MARKET_RETRY trade'leri ilgili handler'a yonlendirir |
| `_advance_sent` | `symbol: str, trade: Trade, regime: Regime` | `None` | SENT emirler icin MT5 emir durumu kontrol; FILLED/PARTIAL/TIMEOUT gecisleri |
| `_advance_partial` | `symbol: str, trade: Trade, regime: Regime` | `None` | Kismi dolum degerlendirme: >=50% kabul -> FILLED; <50% -> kapat ve iptal |
| `_advance_timeout` | `symbol: str, trade: Trade, regime: Regime` | `None` | LIMIT timeout: VOLATILE/OLAY -> iptal; TREND/RANGE ve retry_count<1 -> MARKET retry |
| `_advance_market_retry` | `symbol: str, trade: Trade, regime: Regime` | `None` | Market retry sonucu: MT5'te pozisyon varsa slippage kontrol; asimissa kapat, yoksa FILLED |
| `_update_fill_price` | `symbol: str, trade: Trade` | `None` | MT5 pozisyonundan gercek dolum fiyatini alir, DB gunceller. **Sembol bazli eslestirme** (netting mode): ticket degil symbol ile pozisyon bulur, ticket degismisse gunceller |
| `_is_trading_allowed` | `now: datetime \| None = None` | `bool` | 09:45-17:45 arasi ve piyasa acik mi kontrol |
| `_check_end_of_day` | `now: datetime \| None = None` | `None` | 17:45 sonrasi: tum FILLED pozisyonlari kapat, bekleyen emirleri iptal et |
| `_manage_active_trades` | `regime: Regime` | `None` | FILLED pozisyon yonetimi: dongu oncesi **tek `get_positions()` cagrisi** -> `pos_by_symbol` dict. VOLATILE/OLAY -> tumu kapat; digerleri strateji bazli cikis (trend_follow, mean_reversion, breakout) |
| `_manage_trend_follow` | `symbol: str, trade: Trade, pos: dict[str, Any]` | `None` | Trend follow cikis: fiyat EMA(20) ihlali veya **likidite bazli trailing stop** (A=1.5, B=1.8, C=2.5 ATR) |
| `_manage_mean_reversion` | `symbol: str, trade: Trade, pos: dict[str, Any]` | `None` | Mean reversion cikis: fiyat BB orta bandina ulasti mi (programatik TP yedegi) |
| `_manage_breakout` | `symbol: str, trade: Trade, pos: dict[str, Any]` | `None` | Breakout cikis: **false breakout tespiti** (son BO_REENTRY_BARS=3 bar entry gerisine donmusse kapat) + trailing stop (BO_TRAILING_ATR_MULT=2.0 ATR) |
| `_get_liq_class` (static) | `symbol: str` | `str` | Sembolun likidite sinifini doner: "A"/"B"/"C" (LIQUIDITY_CLASSES dict'inden) |
| `_sync_positions` | (yok) | `None` | `active_trades` FILLED kayitlarini MT5 acik pozisyonlarla karsilastirir; harici kapanis tespit |
| `_handle_closed_trade` | `symbol: str, trade: Trade, exit_reason: str` | `None` | Kapanan islemi isle: PnL hesapla, DB guncelle, event yaz, `active_trades`'den cikar |

### Modul Seviyesi Yardimci Fonksiyonlar

| Fonksiyon | Parametreler | Donus | Ozet |
|---|---|---|---|
| `_last_valid` | `arr: np.ndarray` | `float \| None` | Dizideki son NaN olmayan degeri doner |
| `_last_n_valid` | `arr: np.ndarray, n: int` | `list[float]` | Son `n` NaN olmayan degeri doner (eski->yeni) |
| `_find_swing_low` | `low: np.ndarray, lookback: int` | `float \| None` | Son `lookback` bardaki minimum fiyat |
| `_find_swing_high` | `high: np.ndarray, lookback: int` | `float \| None` | Son `lookback` bardaki maksimum fiyat |

---

## 4. STATE MACHINE

### Tum State'ler (TradeState enum — `engine/models/trade.py`)

| State | Deger | Aciklama |
|---|---|---|
| `IDLE` | `"idle"` | Baslangic (eski, ogul.py'de kullanilmiyor) |
| `SIGNAL` | `"signal"` | Sinyal uretildi, BABA onayi bekleniyor |
| `PENDING` | `"pending"` | BABA onayladi, on-ucus kontrolleri calisiyor |
| `SENT` | `"sent"` | LIMIT emir MT5'e gonderildi |
| `FILLED` | `"filled"` | Emir tamamen doldu, pozisyon aktif |
| `PARTIAL` | `"partial"` | Kismi dolum tespit edildi |
| `TIMEOUT` | `"timeout"` | LIMIT emir zaman asimina ugradi |
| `MARKET_RETRY` | `"market_retry"` | MARKET emir denemesi devam ediyor |
| `REJECTED` | `"rejected"` | Emir reddedildi (MT5 veya slippage) |
| `CLOSED` | `"closed"` | Pozisyon kapatildi |
| `CANCELLED` | `"cancelled"` | Emir iptal edildi |

### State Gecis Kurallari

```
SIGNAL -> PENDING          BABA korelasyon kontrolu gecti
SIGNAL -> CANCELLED        BABA korelasyon kontrolu basarisiz

PENDING -> SENT            Tum on-ucus kontrolleri gecti + LIMIT emir basariyla gonderildi
PENDING -> CANCELLED       On-ucus basarisiz: saat, esanli limit, margin, lot=0

SENT -> FILLED             MT5 order_status == "filled"
SENT -> PARTIAL            MT5 order_status == "partial"
SENT -> TIMEOUT            order_status == "pending" ve sure > 5sn
                           VEYA status None ve sure > 5sn
                           VEYA order_status == "cancelled"

PARTIAL -> FILLED          filled_volume >= %50 talep edilen
PARTIAL -> CANCELLED       filled_volume < %50 (kismi pozisyon da kapatilir)

TIMEOUT -> MARKET_RETRY    regime_at_entry VOLATILE/OLAY DEGIL VE retry_count < 1
TIMEOUT -> CANCELLED       regime_at_entry VOLATILE/OLAY VEYA retry_count >= 1

MARKET_RETRY -> FILLED     MT5 pozisyon bulundu VE slippage <= max_slippage
MARKET_RETRY -> CANCELLED  MT5 pozisyon bulunamadi veya slippage asimi
MARKET_RETRY -> REJECTED   send_order None dondu (hemen cikarilir)

FILLED -> CLOSED           gun_sonu, rejim_degisimi (VOLATILE/OLAY),
                           ema_ihlali, bb_orta_bandi, false_breakout, sl_tp_harici, harici_kapanis
```

### Her State'de Ne Yapiliyor

- **SIGNAL:** Trade nesnesi olusturulur, BABA `check_correlation_limits()` cagrilir
- **PENDING:** On-ucus kontrolleri: islem saati, esanli pozisyon limiti (max 5), margin kontrolu (free_margin >= %20 equity), lot hesaplama. Hepsi gecerse LIMIT emir gonderilir
- **SENT:** `_advance_sent` MT5 `check_order_status()` sorgular. Doldu -> FILLED + **`increment_daily_trade_count()`** cagrilir (Faz 1.3). Kismi -> PARTIAL. Beklemede ve >5sn -> TIMEOUT
- **FILLED:** Pozisyon aktif. `_manage_active_trades` strateji bazli cikis mantigi calistirir (`_manage_trend_follow`, `_manage_mean_reversion`, `_manage_breakout`). `_sync_positions` MT5'te pozisyonun hala var mi kontrol eder
- **PARTIAL:** `_advance_partial` kalan emri iptal eder. >=50% dolmus -> FILLED + **`increment_daily_trade_count()`** (Faz 1.3). <50% -> kismi pozisyonu kapat, CANCELLED
- **TIMEOUT:** `_advance_timeout` bekleyen emri iptal eder. VOLATILE/OLAY rejim -> CANCELLED. TREND/RANGE ve retry_count<1 -> MARKET emri gonder -> MARKET_RETRY
- **MARKET_RETRY:** `_advance_market_retry` MT5'te sembol icin pozisyon var mi kontrol eder. Varsa slippage dogrulama (fill_price vs limit_price). Kabul edilebilir -> FILLED + **`increment_daily_trade_count()`** (Faz 1.3). Asim -> pozisyonu kapat, CANCELLED
- **REJECTED:** Trade hemen cikarilir (market retry basarisizliginda)
- **CLOSED:** Islem sonlandirilir. PnL hesaplanir, DB guncellenir, `active_trades`'den cikarilir
- **CANCELLED:** Trade loglanir, event yazilir, `active_trades`'den cikarilir

---

## 5. SINYAL STRATEJILERI

### Rejim-Strateji Eslemesi

```python
REGIME_STRATEGIES: dict[RegimeType, list[StrategyType]] = {
    RegimeType.TREND:    [StrategyType.TREND_FOLLOW],
    RegimeType.RANGE:    [StrategyType.MEAN_REVERSION, StrategyType.BREAKOUT],
    RegimeType.VOLATILE: [],    # tum sinyaller durur
    RegimeType.OLAY:     [],    # sistem pause
}
```

### Trend Follow (`_check_trend_follow`)

**Giris Kosullari:**
- BUY: EMA(20) > EMA(50) VE ADX > 25 VE MACD histogram son 2 bar pozitif
- SELL: EMA(20) < EMA(50) VE ADX > 25 VE MACD histogram son 2 bar negatif
- Ek: H1 onayi zorunlu (`_confirm_h1`): BUY icin H1 EMA(20) > H1 EMA(50); SELL icin H1 EMA(20) < H1 EMA(50)

**Cikis Kosullari:**
- EMA(20) ihlali: BUY kapanir fiyat < EMA(20); SELL kapanir fiyat > EMA(20)
- **Likidite bazli trailing stop:** her cycle `current_price +/- TRAILING_ATR_BY_CLASS[liq] * ATR` ile guncellenir (A=1.5, B=1.8, C=2.5)
- Gun sonu (17:45)
- Rejim degisimi (VOLATILE/OLAY)

**Kullanilan Indikatorler:** EMA(20), EMA(50), ADX(14), ATR(14), MACD(default), H1 EMA(20), H1 EMA(50)

**SL Hesaplama:**
- BUY: swing_low(10 bar) - 1*ATR; fallback: price - 1.5*ATR
- SELL: swing_high(10 bar) + 1*ATR; fallback: price + 1.5*ATR

**TP Hesaplama:**
- BUY: price + 2*ATR
- SELL: price - 2*ATR

**Guc Formulu:**
```
strength = min(adx_str + macd_str + ema_str, 1.0)
  adx_str  = min((adx_val - 25) / 25.0, 0.5)
  macd_str = min(avg_abs_histogram / (atr_val * 0.5), 0.3)
  ema_str  = min(abs(ema_f - ema_s) / (price * 0.01) * 0.1, 0.2)
```

### Mean Reversion (`_check_mean_reversion`)

**Giris Kosullari:**
- BUY: RSI(14) < 30 VE close <= BB alt bandi VE ADX < 20
- SELL: RSI(14) > 70 VE close >= BB ust bandi VE ADX < 20

**Cikis Kosullari:**
- Fiyat BB orta bandina ulastiginda (`_manage_mean_reversion` ile programatik kontrol)
- TP: BB orta bandi (MT5 emir seviyesinde de ayarli)
- Gun sonu (17:45)
- Rejim degisimi (VOLATILE/OLAY)

**Kullanilan Indikatorler:** RSI(14), Bollinger Bands(20, 2.0 std), ADX(14), ATR(14)

**SL Hesaplama:**
- BUY: BB_lower - 1.0 * ATR
- SELL: BB_upper + 1.0 * ATR

**TP Hesaplama:**
- BUY: BB_middle
- SELL: BB_middle

**Guc Formulu:**
```
strength = min(rsi_str + bb_touch + adx_str, 1.0)
  BUY:  rsi_str  = min((30 - rsi_val) / 30.0, 0.5)
        bb_touch = min((bb_low - last_close) / atr_val, 0.3)
  SELL: rsi_str  = min((rsi_val - 70) / 30.0, 0.5)
        bb_touch = min((last_close - bb_up) / atr_val, 0.3)
  adx_str = min((20 - adx_val) / 20.0, 0.2)
```

### Breakout (`_check_breakout`)

**Giris Kosullari (likidite bazli esikler):**
- BUY: close > 20-bar high (son bar haric) VE volume > ort_volume * **BO_VOLUME_MULT_BY_CLASS[liq]** VE ATR > ort_ATR * **BO_ATR_EXPANSION_BY_CLASS[liq]**
- SELL: close < 20-bar low (son bar haric) VE volume > ort_volume * **BO_VOLUME_MULT_BY_CLASS[liq]** VE ATR > ort_ATR * **BO_ATR_EXPANSION_BY_CLASS[liq]**
- Likidite sinifi `_get_liq_class(symbol)` ile belirlenir

**Cikis Kosullari (`_manage_breakout`):**
- **False breakout tespiti:** Son `BO_REENTRY_BARS`(3) bar entry fiyatinin gerisine donmusse pozisyon kapatilir
- **Trailing stop:** `BO_TRAILING_ATR_MULT`(2.0) * ATR ile guncellenir
- Gun sonu (17:45)
- Rejim degisimi (VOLATILE/OLAY)

**Kullanilan Indikatorler:** ATR(14), 20-bar high/low, volume ortalamasi

**SL Hesaplama:**
- Her iki yon: `SL = (high_20 + low_20) / 2.0` (range orta noktasi)

**TP Hesaplama:**
- BUY: `price + range_width` (range_width = high_20 - low_20)
- SELL: `price - range_width`

**Guc Formulu:**
```
strength = min(vol_str + atr_str + break_str, 1.0)
  vol_str   = min((current_vol / vol_avg - 1.5) / 2.0, 0.5)
  atr_str   = min((atr_val / atr_mean - 1.2) / 1.0, 0.3)
  BUY:  break_str = min((last_close - high_20) / atr_val * 0.2, 0.2)
  SELL: break_str = min((low_20 - last_close) / atr_val * 0.2, 0.2)
```

---

## 6. EMIR YONETIMI

### Emir Tipleri

- **LIMIT:** Tum yeni sinyaller icin varsayilan (`_execute_signal` -> `order_type="limit"`)
- **MARKET:** Sadece LIMIT timeout sonrasi retry olarak (`_advance_timeout` -> `order_type="market"`); VOLATILE/OLAY rejimlerinde YASAK

### SL/TP Hesaplama Mantigi

Strateji bazli — yukari Bolum 5'e bak.

### Pozisyon Kapatma Mantigi

`mt5.close_position(trade.ticket)` su durumlarda cagrilir:
- Gun sonu kapanisi (17:45)
- VOLATILE/OLAY rejim degisimi
- EMA ihlali (trend follow)
- BB orta bandi ulasimi (mean reversion)
- False breakout tespiti (breakout — son 3 bar entry gerisine donmus)
- Slippage asimi (market retry)
- Yetersiz kismi dolum (<50%)

`mt5.cancel_order(trade.order_ticket)` su durumlarda cagrilir:
- Kismi dolumda bekleyen emir iptali
- Timeout isleme
- Gun sonu bekleyen emir temizligi

### Netting Mode Uyumu

- Pozisyon ticket MT5'ten `trade.ticket` olarak saklanir (`trade.order_ticket`'ten farkli)
- SENT->FILLED gecisinde: MT5 durumundan `position_ticket` kullanilir (emir ticket'i degil) — netting icin kritik
- `_update_fill_price` pozisyonlari **sembol** ile eslestirir (Faz 1.1: ticket bazli -> sembol bazli). Ticket degismisse otomatik gunceller ve loglar
- `_advance_market_retry` pozisyonlari **sembol** ile eslestirir (netting: sembol basina tek pozisyon)
- `_sync_positions` pozisyonlari **sembol** ile eslestirir
- `_manage_active_trades` dongu oncesi tek `get_positions()` cagrisi + `pos_by_symbol` dict (Faz 1.2 optimizasyonu)
- MT5 farkli ticket bildirirse pozisyon ticket guncellenir

### PnL Hesaplama

```python
# Dinamik contract_size: MT5 sembol bilgisinden alinir, fallback CONTRACT_SIZE=100
contract_size = CONTRACT_SIZE  # varsayilan fallback
sym_info = self.mt5.get_symbol_info(symbol)
if sym_info and hasattr(sym_info, "trade_contract_size"):
    contract_size = sym_info.trade_contract_size

# BUY:
pnl = (exit_price - entry_price) * volume * contract_size

# SELL:
pnl = (entry_price - exit_price) * volume * contract_size
```

---

## 7. BIAS HESAPLAMA

### `_calculate_bias(symbol: str) -> str`

**Timeframe:** Sadece M15 (minimum 60 bar gerekli)

Hafif bir yon egilimi hesabi — sinyal uretiminden farkli.
Her cycle'da **tum semboller** icin **rejimden bagimsiz** calisir.

### Oylama Mantigi

```python
votes = 0  # pozitif = BUY, negatif = SELL

# 1. RSI(14): > 50 -> +1, < 50 -> -1
# 2. EMA crossover: EMA(20) > EMA(50) -> +1, < -> -1
# 3. MACD histogram: > 0 -> +1, < 0 -> -1

if votes > 0:   return "BUY"
elif votes < 0:  return "SELL"
else:            return "NOTR"
```

Her indikator tam olarak +1 veya -1 katki yapar (sinirda 0). 3 oylayici ile mumkun toplamlar: -3, -2, -1, 0, +1, +2, +3.

### Sonuc Saklama

- `self.last_signals[symbol]` icinde saklanir (her cycle uzerine yazilir)
- Sonradan sinyal uretilip calistirilirsa, `last_signals[symbol]` sinyal yonune guncellenir

---

## 8. SABITLER VE ESIKLER

### Trend Follow Sabitleri

| Sabit | Tip | Deger | Aciklama |
|---|---|---|---|
| `TF_EMA_FAST` | `int` | `20` | Hizli EMA periyodu |
| `TF_EMA_SLOW` | `int` | `50` | Yavas EMA periyodu |
| `TF_ADX_THRESHOLD` | `float` | `25.0` | Trend icin minimum ADX |
| `TF_MACD_CONFIRM_BARS` | `int` | `2` | Histogram ayni isaret 2 bar olmali |
| `TF_SL_ATR_MULT` | `float` | `1.5` | Fallback SL = giris +/- 1.5*ATR |
| `TF_TP_ATR_MULT` | `float` | `2.0` | TP = giris +/- 2*ATR |
| `TF_TRAILING_ATR_MULT` | `float` | `1.5` | Trailing stop varsayilan (likidite bazli override: TRAILING_ATR_BY_CLASS) |

### Mean Reversion Sabitleri

| Sabit | Tip | Deger | Aciklama |
|---|---|---|---|
| `MR_RSI_PERIOD` | `int` | `14` | RSI periyodu |
| `MR_RSI_OVERSOLD` | `float` | `30.0` | RSI asiri satim esigi |
| `MR_RSI_OVERBOUGHT` | `float` | `70.0` | RSI asiri alim esigi |
| `MR_ADX_THRESHOLD` | `float` | `20.0` | Range icin max ADX (< 20 olmali) |
| `MR_BB_PERIOD` | `int` | `20` | Bollinger Band periyodu |
| `MR_BB_STD` | `float` | `2.0` | Bollinger Band std sapma carpani |
| `MR_SL_ATR_MULT` | `float` | `1.0` | SL = BB bandi +/- 1*ATR |

### Breakout Sabitleri

| Sabit | Tip | Deger | Aciklama |
|---|---|---|---|
| `BO_LOOKBACK` | `int` | `20` | High/low geriye bakis periyodu |
| `BO_VOLUME_MULT` | `float` | `1.5` | Volume ort carpani (varsayilan fallback) |
| `BO_ATR_EXPANSION` | `float` | `1.2` | ATR ort carpani (varsayilan fallback) |
| `BO_TRAILING_ATR_MULT` | `float` | `2.0` | Breakout trailing stop ATR carpani |
| `BO_REENTRY_BARS` | `int` | `3` | False breakout kontrolu icin bar sayisi |

### Likidite Sinifi Sabitleri (Faz 2.2)

| Sabit | Tip | Deger | Aciklama |
|---|---|---|---|
| `LIQUIDITY_CLASSES` | `dict[str, str]` | 15 kontrat -> "A"/"B"/"C" | Sembol bazli likidite sinifi |
| `BO_VOLUME_MULT_BY_CLASS` | `dict[str, float]` | `{"A": 1.5, "B": 2.0, "C": 3.0}` | Breakout volume esigi (likidite bazli) |
| `BO_ATR_EXPANSION_BY_CLASS` | `dict[str, float]` | `{"A": 1.2, "B": 1.3, "C": 1.5}` | Breakout ATR genisleme esigi (likidite bazli) |
| `TRAILING_ATR_BY_CLASS` | `dict[str, float]` | `{"A": 1.5, "B": 1.8, "C": 2.5}` | Trend follow trailing stop (likidite bazli) |

### LIQUIDITY_CLASSES Esleme

```python
LIQUIDITY_CLASSES = {
    # A sinifi (yuksek likidite)
    "F_THYAO": "A", "F_AKBNK": "A", "F_ASELS": "A", "F_TCELL": "A", "F_PGSUS": "A",
    # B sinifi (orta likidite)
    "F_HALKB": "B", "F_GUBRF": "B", "F_EKGYO": "B", "F_SOKM": "B", "F_TKFEN": "B",
    # C sinifi (dusuk likidite)
    "F_OYAKC": "C", "F_BRSAN": "C", "F_AKSEN": "C", "F_ASTOR": "C", "F_KONTR": "C",
}
```

### Genel Sabitler

| Sabit | Tip | Deger | Aciklama |
|---|---|---|---|
| `SWING_LOOKBACK` | `int` | `10` | Swing high/low arama penceresi |
| `ATR_PERIOD` | `int` | `14` | ATR hesaplama periyodu |
| `MIN_BARS_M15` | `int` | `60` | Gereken minimum M15 bar sayisi |
| `MIN_BARS_H1` | `int` | `30` | H1 onayi icin minimum bar sayisi |
| `CONTRACT_SIZE` | `float` | `100.0` | VIOP kontrat carpani |
| `ORDER_TIMEOUT_SEC` | `int` | `5` | LIMIT emir zaman asimi (saniye) |
| `MAX_SLIPPAGE_ATR_MULT` | `float` | `0.5` | Max slippage = 0.5 * ATR |
| `MAX_LOT_PER_CONTRACT` | `float` | `1.0` | Kontrat basina max 1 lot (test donemi) |
| `MARGIN_RESERVE_PCT` | `float` | `0.20` | %20 margin rezervi |
| `MAX_CONCURRENT` | `int` | `5` | Max 5 esanli pozisyon |
| `TRADING_OPEN` | `time` | `time(9, 45)` | Islem baslangic saati |
| `TRADING_CLOSE` | `time` | `time(17, 45)` | Islem bitis saati |

---

## 9. BAGIMLILIKLAR

### Icerideki Import'lar

```python
from engine.config import Config
from engine.database import Database
from engine.logger import get_logger
from engine.models.regime import Regime, RegimeType
from engine.models.risk import RiskParams
from engine.models.signal import Signal, SignalType, StrategyType
from engine.models.trade import Trade, TradeState
from engine.mt5_bridge import MT5Bridge
from engine.utils.indicators import (
    adx as calc_adx,
    atr as calc_atr,
    ema,
    bollinger_bands,
    rsi as calc_rsi,
    macd as calc_macd,
)
```

Lazy import (`_is_trading_allowed` icinde):
```python
from engine.utils.time_utils import is_market_open
```

Standart kutuphane:
```python
from __future__ import annotations
import math
from datetime import datetime, time
from typing import Any
import numpy as np
```

### BABA'dan Ne Aliyor

| Cagri | Donus | Kullanim |
|---|---|---|
| `baba.check_correlation_limits(symbol, direction, risk_params)` | `.can_trade: bool, .reason: str` | Sinyal calistirilmadan once korelasyon kontrolu |
| `baba.calculate_position_size(symbol, risk_params, atr_val, equity)` | `float` (lot) | Pozisyon boyutlama |
| `baba.increment_daily_trade_count()` | `None` | Islem **FILLED** oldugunda gunluk sayac artirma (`_advance_sent`, `_advance_partial`, `_advance_market_retry` icinden cagrilir) |
| `baba.is_symbol_killed(symbol)` | `bool` | Sembol bazli L1 kill-switch kontrolu |

### MT5Bridge'den Ne Aliyor

| Cagri | Donus | Kullanim |
|---|---|---|
| `mt5.get_tick(symbol)` | `.ask, .bid` | Guncel fiyat |
| `mt5.get_account_info()` | `.equity, .free_margin` | Hesap bilgisi |
| `mt5.send_order(symbol, direction, lot, price, sl, tp, order_type)` | `dict \| None` | Emir gonderme |
| `mt5.check_order_status(order_ticket)` | `dict \| None` | Emir durumu sorgulama |
| `mt5.cancel_order(order_ticket)` | — | Emir iptal |
| `mt5.close_position(ticket)` | `bool` | Pozisyon kapatma |
| `mt5.modify_position(ticket, sl=new_sl)` | `bool` | Trailing stop guncelleme |
| `mt5.get_positions()` | `list[dict]` | Acik pozisyon listesi |

### Database'den Ne Aliyor

| Cagri | Donus | Kullanim |
|---|---|---|
| `db.get_bars(symbol, timeframe, limit)` | `DataFrame` | Fiyat verileri (close, high, low, volume) |
| `db.insert_trade(dict)` | `int` (db_id) | Islem kaydi olusturma |
| `db.update_trade(db_id, dict)` | — | Islem guncelleme |
| `db.insert_event(event_type, message, severity, action)` | — | Event kaydi |
| `db.get_trades(symbol, limit)` | `list[dict]` | Islem gecmisi sorgulama |

### Config'den Ne Aliyor

- `config/default.json` uzerinden: `strategies.trend_follow`, `strategies.mean_reversion`, `strategies.breakout`, `liquidity_overrides` bolumleri (Faz 2.3)
- Ogul sabitleri hala hardcoded — config override mekanizmasi henuz aktif degil (gelecek gelistirme)
