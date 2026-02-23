"""OĞUL — Sinyal üretimi ve emir state-machine (v12.0).

3 sinyal stratejisi:
    TREND_FOLLOW   — EMA(20)×EMA(50) crossover + ADX>25 + MACD 2-bar
                     M15 giriş + H1 onay, trailing stop 1.5×ATR
    MEAN_REVERSION — RSI(14) aşırı bölge + BB bant teması + ADX<20
                     SL: BB bant ± 1 ATR, TP: BB orta bant
    BREAKOUT       — 20-bar high/low kırılımı + hacim>1.5× + ATR genişleme
                     SL: range orta noktası, TP: %100 range genişliği

Rejim → Aktif sinyaller:
    TREND    → trend follow aktif, mean reversion deaktif
    RANGE    → mean reversion aktif, breakout bekle
    VOLATILE → TÜM sinyaller durur
    OLAY     → SİSTEM PAUSE
"""

from __future__ import annotations

import math
from datetime import datetime, time
from typing import Any

import numpy as np

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

logger = get_logger(__name__)


# ═════════════════════════════════════════════════════════════════════
#  SABİTLER
# ═════════════════════════════════════════════════════════════════════

# ── Trend Follow ──────────────────────────────────────────────────
TF_EMA_FAST:          int   = 20
TF_EMA_SLOW:          int   = 50
TF_ADX_THRESHOLD:     float = 25.0
TF_MACD_CONFIRM_BARS: int   = 2     # histogram 2 bar aynı işaret
TF_SL_ATR_MULT:       float = 1.5   # entry ± 1.5×ATR (fallback)
TF_TP_ATR_MULT:       float = 2.0   # 2×ATR
TF_TRAILING_ATR_MULT: float = 1.5   # trailing stop 1.5×ATR

# ── Mean Reversion ────────────────────────────────────────────────
MR_RSI_PERIOD:    int   = 14
MR_RSI_OVERSOLD:  float = 30.0
MR_RSI_OVERBOUGHT: float = 70.0
MR_ADX_THRESHOLD: float = 20.0      # ADX < 20 gerekli
MR_BB_PERIOD:     int   = 20
MR_BB_STD:        float = 2.0
MR_SL_ATR_MULT:   float = 1.0       # BB bant ± 1 ATR

# ── Breakout ──────────────────────────────────────────────────────
BO_LOOKBACK:       int   = 20       # 20-bar high/low
BO_VOLUME_MULT:    float = 1.5      # hacim > ort × 1.5
BO_ATR_EXPANSION:  float = 1.2      # ATR genişleme oranı

# ── Genel ─────────────────────────────────────────────────────────
SWING_LOOKBACK:  int = 10           # swing high/low arama barı
ATR_PERIOD:      int = 14
MIN_BARS_M15:    int = 60           # M15 için min bar
MIN_BARS_H1:     int = 30           # H1 onay için min bar
CONTRACT_SIZE:   float = 100.0      # VİOP çarpanı (varsayılan)

# ── Rejim → aktif strateji eşleme ─────────────────────────────────
REGIME_STRATEGIES: dict[RegimeType, list[StrategyType]] = {
    RegimeType.TREND:    [StrategyType.TREND_FOLLOW],
    RegimeType.RANGE:    [StrategyType.MEAN_REVERSION, StrategyType.BREAKOUT],
    RegimeType.VOLATILE: [],    # tüm sinyaller durur
    RegimeType.OLAY:     [],    # sistem pause
}

# ── State Machine ────────────────────────────────────────────────
ORDER_TIMEOUT_SEC: int       = 5       # limit emir timeout (saniye)
MAX_SLIPPAGE_ATR_MULT: float = 0.5     # max slippage = 0.5 × ATR
MAX_LOT_PER_CONTRACT: float  = 1.0     # test süreci: kontrat başına max 1 lot
MARGIN_RESERVE_PCT: float    = 0.20    # test süreci: %20 teminat ayırma
MAX_CONCURRENT: int          = 5       # test süreci: eş zamanlı maks 5 pozisyon
TRADING_OPEN: time           = time(9, 45)   # işlem başlangıç
TRADING_CLOSE: time          = time(17, 45)  # işlem bitiş + tüm pozisyonlar kapatılır


# ═════════════════════════════════════════════════════════════════════
#  YARDIMCI FONKSİYONLAR
# ═════════════════════════════════════════════════════════════════════

def _last_valid(arr: np.ndarray) -> float | None:
    """Dizinin son NaN-olmayan değeri."""
    for i in range(len(arr) - 1, -1, -1):
        if not np.isnan(arr[i]):
            return float(arr[i])
    return None


def _last_n_valid(arr: np.ndarray, n: int) -> list[float]:
    """Son *n* adet NaN-olmayan değer (eskiden yeniye)."""
    result: list[float] = []
    for i in range(len(arr) - 1, -1, -1):
        if not np.isnan(arr[i]):
            result.append(float(arr[i]))
            if len(result) >= n:
                break
    result.reverse()
    return result


def _find_swing_low(low: np.ndarray, lookback: int) -> float | None:
    """Son *lookback* bar içindeki en düşük fiyat."""
    if len(low) < lookback:
        return None
    segment = low[-lookback:]
    valid = segment[~np.isnan(segment)]
    if len(valid) == 0:
        return None
    return float(np.min(valid))


def _find_swing_high(high: np.ndarray, lookback: int) -> float | None:
    """Son *lookback* bar içindeki en yüksek fiyat."""
    if len(high) < lookback:
        return None
    segment = high[-lookback:]
    valid = segment[~np.isnan(segment)]
    if len(valid) == 0:
        return None
    return float(np.max(valid))


# ═════════════════════════════════════════════════════════════════════
#  OĞUL
# ═════════════════════════════════════════════════════════════════════

class Ogul:
    """Sinyal üretici ve emir yöneticisi.

    Her 10 saniyede ``process_signals()`` çağrılır.
    3 strateji: trend follow, mean reversion, breakout.
    """

    def __init__(
        self,
        config: Config,
        mt5: MT5Bridge,
        db: Database,
        baba: Any | None = None,
    ) -> None:
        self.config = config
        self.mt5 = mt5
        self.db = db
        self.baba = baba
        self.active_trades: dict[str, Trade] = {}
        self.last_signals: dict[str, str] = {}  # symbol → "BUY"|"SELL"|"BEKLE"

    # ═════════════════════════════════════════════════════════════════
    #  ANA GİRİŞ
    # ═════════════════════════════════════════════════════════════════

    def process_signals(self, symbols: list[str], regime: Regime) -> None:
        """Seçilen kontratlar için sinyal üret ve emirleri yönet.

        Her 10 sn'de ``main_loop`` tarafından çağrılır.

        Çağrı sırası:
            1. _check_end_of_day()         — 17:45 kapatma (EN ÖNCE)
            2. _advance_orders(regime)      — SENT/PARTIAL/TIMEOUT ilerletme
            3. _manage_active_trades(regime) — trailing stop, çıkış
            4. _sync_positions()            — MT5 senkronizasyon
            5. Rejim kontrolü               — aktif stratejiler
            6. _is_trading_allowed()        — 09:45-17:45 kontrolü
            7. Sinyal üretimi               — per-symbol

        Args:
            symbols: Top-5 kontrat sembolleri.
            regime: Mevcut piyasa rejimi.
        """
        # 1. Gün sonu kontrolü — 17:45 tüm pozisyon/emir kapatma
        self._check_end_of_day()

        # 2. Bekleyen emir state-machine ilerletme
        self._advance_orders(regime)

        # 3. Mevcut işlemleri yönet (trailing, çıkış kontrolleri)
        self._manage_active_trades(regime)

        # 4. MT5 ile pozisyon senkronizasyonu
        self._sync_positions()

        # 5. Rejim kontrolü — aktif stratejiler
        strategies = REGIME_STRATEGIES.get(regime.regime_type, [])
        if not strategies:
            logger.debug(
                f"Rejim {regime.regime_type.value}: tüm sinyaller deaktif"
            )
            return

        # 6. İşlem saatleri kontrolü
        if not self._is_trading_allowed():
            return

        # 7. Her sembol için sinyal üretimi
        for symbol in symbols:
            # Sembol başına 1 aktif işlem kuralı
            if symbol in self.active_trades:
                continue

            # Kill-switch kontrolü
            if self.baba and self.baba.is_symbol_killed(symbol):
                logger.debug(f"Sembol durdurulmuş (L1): {symbol}")
                continue

            signal = self._generate_signal(symbol, regime, strategies)
            # Sinyal sonucunu kaydet (Dashboard Top 5 için)
            if signal:
                self.last_signals[symbol] = signal.signal_type.value
                self._execute_signal(signal, regime)
            else:
                self.last_signals[symbol] = "BEKLE"

    # ═════════════════════════════════════════════════════════════════
    #  SİNYAL ÜRETİMİ
    # ═════════════════════════════════════════════════════════════════

    def _generate_signal(
        self,
        symbol: str,
        regime: Regime,
        strategies: list[StrategyType],
    ) -> Signal | None:
        """Bir kontrat için en güçlü sinyali üret.

        Args:
            symbol: Kontrat sembolü.
            regime: Mevcut rejim.
            strategies: Aktif strateji listesi.

        Returns:
            En yüksek strength'e sahip Signal veya None.
        """
        # M15 bar verisi
        df = self.db.get_bars(symbol, "M15", limit=MIN_BARS_M15)
        if df.empty or len(df) < MIN_BARS_M15:
            return None

        close = df["close"].values.astype(np.float64)
        high = df["high"].values.astype(np.float64)
        low = df["low"].values.astype(np.float64)
        volume = df["volume"].values.astype(np.float64)

        candidates: list[Signal] = []

        for strategy in strategies:
            signal: Signal | None = None

            if strategy == StrategyType.TREND_FOLLOW:
                signal = self._check_trend_follow(
                    symbol, close, high, low, volume,
                )
            elif strategy == StrategyType.MEAN_REVERSION:
                signal = self._check_mean_reversion(
                    symbol, close, high, low, volume,
                )
            elif strategy == StrategyType.BREAKOUT:
                signal = self._check_breakout(
                    symbol, close, high, low, volume,
                )

            if signal:
                candidates.append(signal)

        if not candidates:
            return None

        # En güçlü sinyali seç
        best = max(candidates, key=lambda s: s.strength)

        # Trend follow ise H1 onayı gerekli
        if best.strategy == StrategyType.TREND_FOLLOW:
            if not self._confirm_h1(symbol, best):
                logger.debug(
                    f"H1 onayı başarısız [{symbol}]: {best.signal_type.value}"
                )
                return None

        logger.info(
            f"Sinyal üretildi [{symbol}]: {best.signal_type.value} "
            f"strateji={best.strategy.value} güç={best.strength:.2f} "
            f"SL={best.sl:.4f} TP={best.tp:.4f}"
        )
        return best

    # ── Trend Follow ──────────────────────────────────────────────

    def _check_trend_follow(
        self,
        symbol: str,
        close: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        volume: np.ndarray,
    ) -> Signal | None:
        """Trend follow sinyali kontrolü.

        Long: EMA(20) > EMA(50) + ADX > 25 + MACD histogram 2 bar pozitif
        Short: EMA(20) < EMA(50) + ADX > 25 + MACD histogram 2 bar negatif
        """
        # İndikatörler
        ema_fast = ema(close, TF_EMA_FAST)
        ema_slow = ema(close, TF_EMA_SLOW)
        adx_arr = calc_adx(high, low, close, ATR_PERIOD)
        atr_arr = calc_atr(high, low, close, ATR_PERIOD)
        _, _, histogram = calc_macd(close)

        # Son geçerli değerler
        ema_f = _last_valid(ema_fast)
        ema_s = _last_valid(ema_slow)
        adx_val = _last_valid(adx_arr)
        atr_val = _last_valid(atr_arr)

        if any(v is None for v in (ema_f, ema_s, adx_val, atr_val)):
            return None
        if atr_val <= 0:
            return None

        # MACD histogram son 2 bar
        hist_vals = _last_n_valid(histogram, TF_MACD_CONFIRM_BARS)
        if len(hist_vals) < TF_MACD_CONFIRM_BARS:
            return None

        # ADX eşik
        if adx_val <= TF_ADX_THRESHOLD:
            return None

        # Yön belirleme
        direction: SignalType | None = None

        if ema_f > ema_s and all(h > 0 for h in hist_vals):
            direction = SignalType.BUY
        elif ema_f < ema_s and all(h < 0 for h in hist_vals):
            direction = SignalType.SELL

        if direction is None:
            return None

        # Giriş fiyatı
        tick = self.mt5.get_tick(symbol)
        if tick is None:
            return None
        price = tick.ask if direction == SignalType.BUY else tick.bid

        # SL hesaplama: swing low/high - 1 ATR veya fallback
        if direction == SignalType.BUY:
            swing = _find_swing_low(low, SWING_LOOKBACK)
            if swing is not None and swing < price:
                sl = swing - atr_val
            else:
                sl = price - TF_SL_ATR_MULT * atr_val
            tp = price + TF_TP_ATR_MULT * atr_val
        else:
            swing = _find_swing_high(high, SWING_LOOKBACK)
            if swing is not None and swing > price:
                sl = swing + atr_val
            else:
                sl = price + TF_SL_ATR_MULT * atr_val
            tp = price - TF_TP_ATR_MULT * atr_val

        # Sinyal gücü: ADX (0-0.5) + MACD (0-0.3) + EMA mesafesi (0-0.2)
        adx_str = min((adx_val - TF_ADX_THRESHOLD) / 25.0, 0.5)
        hist_avg = abs(sum(hist_vals) / len(hist_vals))
        macd_str = min(hist_avg / (atr_val * 0.5) if atr_val > 0 else 0.0, 0.3)
        ema_dist = abs(ema_f - ema_s) / (price * 0.01) if price > 0 else 0.0
        ema_str = min(ema_dist * 0.1, 0.2)
        strength = adx_str + macd_str + ema_str

        return Signal(
            symbol=symbol,
            signal_type=direction,
            price=price,
            sl=sl,
            tp=tp,
            strength=min(strength, 1.0),
            reason=(
                f"TREND_FOLLOW: EMA({TF_EMA_FAST}){'>' if direction == SignalType.BUY else '<'}"
                f"EMA({TF_EMA_SLOW}) ADX={adx_val:.1f}"
            ),
            strategy=StrategyType.TREND_FOLLOW,
        )

    # ── Mean Reversion ────────────────────────────────────────────

    def _check_mean_reversion(
        self,
        symbol: str,
        close: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        volume: np.ndarray,
    ) -> Signal | None:
        """Mean reversion sinyali kontrolü.

        Long: RSI(14) < 30 + BB alt bant teması + ADX < 20
        Short: RSI(14) > 70 + BB üst bant teması + ADX < 20
        """
        # İndikatörler
        rsi_arr = calc_rsi(close, MR_RSI_PERIOD)
        bb_upper, bb_middle, bb_lower = bollinger_bands(
            close, MR_BB_PERIOD, MR_BB_STD,
        )
        adx_arr = calc_adx(high, low, close, ATR_PERIOD)
        atr_arr = calc_atr(high, low, close, ATR_PERIOD)

        # Son geçerli değerler
        rsi_val = _last_valid(rsi_arr)
        bb_up = _last_valid(bb_upper)
        bb_mid = _last_valid(bb_middle)
        bb_low = _last_valid(bb_lower)
        adx_val = _last_valid(adx_arr)
        atr_val = _last_valid(atr_arr)

        if any(v is None for v in (rsi_val, bb_up, bb_mid, bb_low, adx_val, atr_val)):
            return None
        if atr_val <= 0:
            return None

        # ADX eşik — range piyasası gerekli
        if adx_val >= MR_ADX_THRESHOLD:
            return None

        last_close = float(close[-1])
        direction: SignalType | None = None

        # Long: RSI < 30 + BB alt bant teması
        if rsi_val < MR_RSI_OVERSOLD and last_close <= bb_low:
            direction = SignalType.BUY
        # Short: RSI > 70 + BB üst bant teması
        elif rsi_val > MR_RSI_OVERBOUGHT and last_close >= bb_up:
            direction = SignalType.SELL

        if direction is None:
            return None

        # Giriş fiyatı
        tick = self.mt5.get_tick(symbol)
        if tick is None:
            return None
        price = tick.ask if direction == SignalType.BUY else tick.bid

        # SL / TP
        if direction == SignalType.BUY:
            sl = bb_low - MR_SL_ATR_MULT * atr_val
            tp = bb_mid
        else:
            sl = bb_up + MR_SL_ATR_MULT * atr_val
            tp = bb_mid

        # Sinyal gücü: RSI aşırılık (0-0.5) + BB temas (0-0.3) + ADX zayıflık (0-0.2)
        if direction == SignalType.BUY:
            rsi_str = min((MR_RSI_OVERSOLD - rsi_val) / 30.0, 0.5)
            bb_touch = min((bb_low - last_close) / atr_val if atr_val > 0 else 0.0, 0.3)
        else:
            rsi_str = min((rsi_val - MR_RSI_OVERBOUGHT) / 30.0, 0.5)
            bb_touch = min((last_close - bb_up) / atr_val if atr_val > 0 else 0.0, 0.3)

        adx_str = min((MR_ADX_THRESHOLD - adx_val) / 20.0, 0.2)
        strength = max(rsi_str, 0.0) + max(bb_touch, 0.0) + max(adx_str, 0.0)

        return Signal(
            symbol=symbol,
            signal_type=direction,
            price=price,
            sl=sl,
            tp=tp,
            strength=min(strength, 1.0),
            reason=(
                f"MEAN_REVERSION: RSI={rsi_val:.1f} "
                f"ADX={adx_val:.1f} BB_touch"
            ),
            strategy=StrategyType.MEAN_REVERSION,
        )

    # ── Breakout ──────────────────────────────────────────────────

    def _check_breakout(
        self,
        symbol: str,
        close: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        volume: np.ndarray,
    ) -> Signal | None:
        """Breakout sinyali kontrolü.

        Long: 20-bar high kırılımı + hacim > ort×1.5 + ATR genişleme
        Short: 20-bar low kırılımı + hacim > ort×1.5 + ATR genişleme
        Hacim filtresi ZORUNLU.
        """
        if len(close) < BO_LOOKBACK + 2:
            return None

        atr_arr = calc_atr(high, low, close, ATR_PERIOD)
        atr_val = _last_valid(atr_arr)
        if atr_val is None or atr_val <= 0:
            return None

        # 20-bar high/low (son bar hariç)
        lookback_high = high[-(BO_LOOKBACK + 1):-1]
        lookback_low = low[-(BO_LOOKBACK + 1):-1]
        valid_high = lookback_high[~np.isnan(lookback_high)]
        valid_low = lookback_low[~np.isnan(lookback_low)]

        if len(valid_high) == 0 or len(valid_low) == 0:
            return None

        high_20 = float(np.max(valid_high))
        low_20 = float(np.min(valid_low))

        # Hacim kontrolü (ZORUNLU)
        lookback_vol = volume[-(BO_LOOKBACK + 1):-1]
        valid_vol = lookback_vol[~np.isnan(lookback_vol)]
        if len(valid_vol) == 0:
            return None
        vol_avg = float(np.mean(valid_vol))
        current_vol = float(volume[-1])

        if vol_avg <= 0 or current_vol <= vol_avg * BO_VOLUME_MULT:
            return None

        # ATR genişleme kontrolü
        atr_valid = atr_arr[~np.isnan(atr_arr)]
        if len(atr_valid) < 5:
            return None
        atr_mean = float(np.mean(atr_valid[:-1])) if len(atr_valid) > 1 else atr_val
        if atr_mean <= 0 or atr_val <= atr_mean * BO_ATR_EXPANSION:
            return None

        last_close = float(close[-1])
        direction: SignalType | None = None

        if last_close > high_20:
            direction = SignalType.BUY
        elif last_close < low_20:
            direction = SignalType.SELL

        if direction is None:
            return None

        # Giriş fiyatı
        tick = self.mt5.get_tick(symbol)
        if tick is None:
            return None
        price = tick.ask if direction == SignalType.BUY else tick.bid

        # SL / TP
        range_width = high_20 - low_20
        range_mid = (high_20 + low_20) / 2.0
        sl = range_mid

        if direction == SignalType.BUY:
            tp = price + range_width
        else:
            tp = price - range_width

        # Sinyal gücü: hacim patlaması (0-0.5) + ATR genişleme (0-0.3) + kırılım büyüklüğü (0-0.2)
        vol_str = min((current_vol / vol_avg - BO_VOLUME_MULT) / 2.0, 0.5)
        atr_str = min((atr_val / atr_mean - BO_ATR_EXPANSION) / 1.0, 0.3)
        if direction == SignalType.BUY:
            break_size = (last_close - high_20) / atr_val if atr_val > 0 else 0.0
        else:
            break_size = (low_20 - last_close) / atr_val if atr_val > 0 else 0.0
        break_str = min(break_size * 0.2, 0.2)

        strength = max(vol_str, 0.0) + max(atr_str, 0.0) + max(break_str, 0.0)

        return Signal(
            symbol=symbol,
            signal_type=direction,
            price=price,
            sl=sl,
            tp=tp,
            strength=min(strength, 1.0),
            reason=(
                f"BREAKOUT: {'high' if direction == SignalType.BUY else 'low'} "
                f"kırılım vol={current_vol/vol_avg:.1f}× "
                f"ATR_exp={atr_val/atr_mean:.2f}"
            ),
            strategy=StrategyType.BREAKOUT,
        )

    # ── H1 Onay ──────────────────────────────────────────────────

    def _confirm_h1(self, symbol: str, signal: Signal) -> bool:
        """H1 zaman diliminde trend onayı (sadece trend follow).

        BUY → H1 EMA(20) > EMA(50)
        SELL → H1 EMA(20) < EMA(50)

        Args:
            symbol: Kontrat sembolü.
            signal: Onaylanacak sinyal.

        Returns:
            True ise H1 onaylı.
        """
        df = self.db.get_bars(symbol, "H1", limit=MIN_BARS_H1)
        if df.empty or len(df) < TF_EMA_SLOW + 1:
            return False

        close_h1 = df["close"].values.astype(np.float64)
        ema_fast_h1 = ema(close_h1, TF_EMA_FAST)
        ema_slow_h1 = ema(close_h1, TF_EMA_SLOW)

        ef = _last_valid(ema_fast_h1)
        es = _last_valid(ema_slow_h1)

        if ef is None or es is None:
            return False

        if signal.signal_type == SignalType.BUY:
            return ef > es
        elif signal.signal_type == SignalType.SELL:
            return ef < es

        return False

    # ═════════════════════════════════════════════════════════════════
    #  EMİR YÜRÜTME
    # ═════════════════════════════════════════════════════════════════

    def _execute_signal(self, signal: Signal, regime: Regime) -> None:
        """Sinyali state-machine ile emir akışına sok.

        SIGNAL → PENDING → SENT (LIMIT emir).

        Args:
            signal: Çalıştırılacak sinyal.
            regime: Mevcut rejim.
        """
        symbol = signal.symbol
        direction = "BUY" if signal.signal_type == SignalType.BUY else "SELL"
        now = datetime.now()

        # ── FAZ 1: SIGNAL ────────────────────────────────────────────
        trade = Trade(
            symbol=symbol,
            direction=direction,
            volume=0.0,  # lot henüz hesaplanmadı
            entry_price=signal.price,
            sl=signal.sl,
            tp=signal.tp,
            state=TradeState.SIGNAL,
            opened_at=now,
            strategy=signal.strategy.value,
            trailing_sl=signal.sl,
            regime_at_entry=regime.regime_type.value,
        )

        # BABA onay — korelasyon kontrolü
        risk_params = RiskParams()
        if self.baba:
            corr_verdict = self.baba.check_correlation_limits(
                symbol, direction, risk_params,
            )
            if not corr_verdict.can_trade:
                trade.state = TradeState.CANCELLED
                trade.cancel_reason = f"correlation: {corr_verdict.reason}"
                self._log_cancelled_trade(trade)
                return

        # ── FAZ 2: PENDING (pre-flight) ──────────────────────────────
        trade.state = TradeState.PENDING

        # İşlem saatleri kontrolü
        if not self._is_trading_allowed(now):
            trade.state = TradeState.CANCELLED
            trade.cancel_reason = "outside_trading_hours"
            self._log_cancelled_trade(trade)
            return

        # Eş zamanlı pozisyon limiti
        active_states = (
            TradeState.FILLED, TradeState.SENT,
            TradeState.PARTIAL, TradeState.MARKET_RETRY,
        )
        active_count = sum(
            1 for t in self.active_trades.values()
            if t.state in active_states
        )
        if active_count >= MAX_CONCURRENT:
            trade.state = TradeState.CANCELLED
            trade.cancel_reason = (
                f"concurrent_limit ({active_count}/{MAX_CONCURRENT})"
            )
            self._log_cancelled_trade(trade)
            return

        # Teminat kontrolü
        account = self.mt5.get_account_info()
        if account is None:
            trade.state = TradeState.CANCELLED
            trade.cancel_reason = "account_info_unavailable"
            self._log_cancelled_trade(trade)
            return

        equity = account.equity
        free_margin = account.free_margin
        if equity <= 0 or free_margin < equity * MARGIN_RESERVE_PCT:
            trade.state = TradeState.CANCELLED
            trade.cancel_reason = (
                f"margin_insufficient (free={free_margin:.0f}, "
                f"reserve={equity * MARGIN_RESERVE_PCT:.0f})"
            )
            self._log_cancelled_trade(trade)
            return

        # Lot hesaplama
        lot = self._calculate_lot(signal, regime, equity, risk_params)
        if lot <= 0:
            trade.state = TradeState.CANCELLED
            trade.cancel_reason = "lot_zero"
            self._log_cancelled_trade(trade)
            return

        trade.volume = lot
        trade.requested_volume = lot

        # Max slippage hesapla
        atr_val = self._get_current_atr(symbol)
        trade.max_slippage = (
            atr_val * MAX_SLIPPAGE_ATR_MULT if atr_val else 0.0
        )

        # ── FAZ 3: SENT (LIMIT emir gönder) ─────────────────────────
        trade.limit_price = signal.price
        result = self.mt5.send_order(
            symbol=symbol,
            direction=direction,
            lot=lot,
            price=signal.price,
            sl=signal.sl,
            tp=signal.tp,
            order_type="limit",
        )

        if result is None:
            trade.state = TradeState.CANCELLED
            trade.cancel_reason = "send_order_failed"
            self._log_cancelled_trade(trade)
            self.db.insert_event(
                event_type="TRADE_ERROR",
                message=f"Emir başarısız: {symbol} {direction} {lot} lot",
                severity="ERROR",
                action="order_failed",
            )
            return

        # Başarılı → SENT
        trade.state = TradeState.SENT
        trade.order_ticket = result.get("order", 0)
        trade.sent_at = now

        # DB kayıt
        db_id = self.db.insert_trade({
            "strategy": signal.strategy.value,
            "symbol": symbol,
            "direction": direction,
            "entry_time": now.isoformat(),
            "entry_price": signal.price,
            "lot": lot,
            "regime": regime.regime_type.value,
        })
        trade.db_id = db_id

        # Aktif işlemlere ekle
        self.active_trades[symbol] = trade

        # Risk sayacı güncelle
        if self.baba:
            self.baba.increment_daily_trade_count()

        # Event kaydet
        self.db.insert_event(
            event_type="ORDER_SENT",
            message=(
                f"LIMIT emir gönderildi: {direction} {lot} lot {symbol} "
                f"@ {signal.price:.4f} SL={signal.sl:.4f} TP={signal.tp:.4f} "
                f"strateji={signal.strategy.value} "
                f"order_ticket={trade.order_ticket}"
            ),
            severity="INFO",
            action="order_sent",
        )

        logger.info(
            f"LIMIT emir gönderildi [{symbol}]: {direction} {lot} lot "
            f"@ {signal.price:.4f} order_ticket={trade.order_ticket}"
        )

    # ── Yardımcı metodlar ─────────────────────────────────────────

    def _calculate_lot(
        self,
        signal: Signal,
        regime: Regime,
        equity: float,
        risk_params: RiskParams,
    ) -> float:
        """Pozisyon boyutu hesapla.

        BABA varsa ``calculate_position_size`` kullanır,
        yoksa basit fallback (1 lot). Her durumda
        ``MAX_LOT_PER_CONTRACT`` ile sınırlar.

        Returns:
            Hesaplanan lot miktarı.
        """
        if self.baba:
            atr_val = self._get_current_atr(signal.symbol)
            if atr_val is None or atr_val <= 0:
                return 0.0
            lot = self.baba.calculate_position_size(
                signal.symbol, risk_params, atr_val, equity,
            )
        else:
            lot = 1.0

        return min(lot, MAX_LOT_PER_CONTRACT)

    def _get_current_atr(self, symbol: str) -> float | None:
        """Sembol için güncel ATR(14) değeri.

        Returns:
            ATR değeri veya veri yoksa None.
        """
        df = self.db.get_bars(symbol, "M15", limit=MIN_BARS_M15)
        if df.empty or len(df) < ATR_PERIOD + 1:
            return None

        close = df["close"].values.astype(np.float64)
        high_arr = df["high"].values.astype(np.float64)
        low_arr = df["low"].values.astype(np.float64)
        atr_arr = calc_atr(high_arr, low_arr, close, ATR_PERIOD)
        return _last_valid(atr_arr)

    def _log_cancelled_trade(self, trade: Trade) -> None:
        """İptal edilen trade'i logla ve event yaz.

        Args:
            trade: İptal edilen Trade nesnesi.
        """
        self.db.insert_event(
            event_type="ORDER_CANCELLED",
            message=(
                f"Emir iptal: {trade.direction} {trade.symbol} "
                f"neden={trade.cancel_reason}"
            ),
            severity="WARNING",
            action="order_cancelled",
        )
        logger.info(
            f"Emir iptal [{trade.symbol}]: {trade.cancel_reason}"
        )

    def _remove_trade(
        self,
        symbol: str,
        trade: Trade,
        reason: str,
    ) -> None:
        """Trade'i active_trades'den sil ve DB güncelle.

        Args:
            symbol: Kontrat sembolü.
            trade: Silinecek Trade nesnesi.
            reason: Silme nedeni.
        """
        trade.state = TradeState.CANCELLED
        trade.cancel_reason = reason

        if trade.db_id > 0:
            self.db.update_trade(trade.db_id, {
                "exit_time": datetime.now().isoformat(),
                "exit_reason": reason,
            })

        self.db.insert_event(
            event_type="ORDER_CANCELLED",
            message=(
                f"Emir kaldırıldı: {trade.direction} {trade.symbol} "
                f"neden={reason}"
            ),
            severity="WARNING",
            action="order_removed",
        )

        self.active_trades.pop(symbol, None)
        logger.info(f"Trade kaldırıldı [{symbol}]: {reason}")

    # ═════════════════════════════════════════════════════════════════
    #  STATE MACHINE — EMİR İLERLETME
    # ═════════════════════════════════════════════════════════════════

    def _advance_orders(self, regime: Regime) -> None:
        """Bekleyen emirlerin state-machine'ini ilerlet.

        SENT → FILLED / PARTIAL / TIMEOUT
        PARTIAL → FILLED / CANCELLED
        TIMEOUT → MARKET_RETRY / CANCELLED
        MARKET_RETRY → FILLED / REJECTED

        Her cycle'da ``process_signals()`` başında çağrılır.

        Args:
            regime: Mevcut piyasa rejimi.
        """
        for symbol in list(self.active_trades):
            trade = self.active_trades[symbol]

            if trade.state == TradeState.SENT:
                self._advance_sent(symbol, trade, regime)
            elif trade.state == TradeState.PARTIAL:
                self._advance_partial(symbol, trade, regime)
            elif trade.state == TradeState.TIMEOUT:
                self._advance_timeout(symbol, trade, regime)
            elif trade.state == TradeState.MARKET_RETRY:
                self._advance_market_retry(symbol, trade, regime)

    def _advance_sent(
        self,
        symbol: str,
        trade: Trade,
        regime: Regime,
    ) -> None:
        """SENT state ilerletme — emir dolum kontrolü.

        Args:
            symbol: Kontrat sembolü.
            trade: SENT state'teki Trade.
            regime: Mevcut rejim.
        """
        status = self.mt5.check_order_status(trade.order_ticket)

        if status is None:
            # MT5 yanıt yok — timeout kontrolü
            if trade.sent_at and (
                datetime.now() - trade.sent_at
            ).total_seconds() > ORDER_TIMEOUT_SEC:
                trade.state = TradeState.TIMEOUT
                logger.warning(
                    f"Emir timeout (yanıt yok) [{symbol}]: "
                    f"order_ticket={trade.order_ticket}"
                )
            return

        order_status = status["status"]

        if order_status == "filled":
            trade.state = TradeState.FILLED
            # Netting modda position_ticket kullan (close_position bunu bekler)
            trade.ticket = status.get(
                "position_ticket",
                status.get("deal_ticket", trade.order_ticket),
            )
            trade.filled_volume = status.get(
                "filled_volume", trade.volume,
            )
            trade.volume = trade.filled_volume
            self._update_fill_price(symbol, trade)
            logger.info(
                f"LIMIT emir doldu [{symbol}]: position_ticket={trade.ticket}"
            )
            self.db.insert_event(
                event_type="ORDER_FILLED",
                message=(
                    f"Emir doldu: {trade.direction} {trade.volume} lot "
                    f"{symbol} ticket={trade.ticket}"
                ),
                severity="INFO",
                action="order_filled",
            )

        elif order_status == "partial":
            trade.state = TradeState.PARTIAL
            trade.filled_volume = status.get("filled_volume", 0.0)
            logger.info(
                f"Kısmi dolum [{symbol}]: "
                f"{trade.filled_volume}/{trade.requested_volume} lot"
            )

        elif order_status == "pending":
            # Hâlâ bekliyor — timeout kontrolü
            if trade.sent_at and (
                datetime.now() - trade.sent_at
            ).total_seconds() > ORDER_TIMEOUT_SEC:
                trade.state = TradeState.TIMEOUT
                logger.info(
                    f"LIMIT emir timeout [{symbol}]: "
                    f"order_ticket={trade.order_ticket}"
                )

        elif order_status == "cancelled":
            # Borsa tarafından iptal edilmiş
            trade.state = TradeState.TIMEOUT
            logger.warning(
                f"Emir borsa tarafından iptal edildi [{symbol}]: "
                f"order_ticket={trade.order_ticket}"
            )

    def _advance_partial(
        self,
        symbol: str,
        trade: Trade,
        regime: Regime,
    ) -> None:
        """PARTIAL state ilerletme — kısmi dolum değerlendirme.

        ≥%50 dolum → kabul (FILLED).
        <%50 dolum → kısmi pozisyonu kapat (CANCELLED).

        Args:
            symbol: Kontrat sembolü.
            trade: PARTIAL state'teki Trade.
            regime: Mevcut rejim.
        """
        # Kalan bekleyen emri iptal et
        self.mt5.cancel_order(trade.order_ticket)

        threshold = trade.requested_volume * 0.5

        if trade.filled_volume >= threshold:
            # Kabul — kısmi dolum yeterli
            trade.state = TradeState.FILLED
            trade.volume = trade.filled_volume
            self._update_fill_price(symbol, trade)
            logger.info(
                f"Kısmi dolum kabul [{symbol}]: "
                f"{trade.filled_volume}/{trade.requested_volume} lot"
            )
            self.db.insert_event(
                event_type="ORDER_FILLED",
                message=(
                    f"Kısmi dolum kabul: {trade.filled_volume} lot "
                    f"{symbol} (istek: {trade.requested_volume})"
                ),
                severity="INFO",
                action="partial_accepted",
            )
        else:
            # Yetersiz — kısmi pozisyonu kapat
            if trade.ticket:
                self.mt5.close_position(trade.ticket)
            self._remove_trade(
                symbol, trade,
                f"partial_insufficient "
                f"({trade.filled_volume}/{trade.requested_volume})",
            )

    def _advance_timeout(
        self,
        symbol: str,
        trade: Trade,
        regime: Regime,
    ) -> None:
        """TIMEOUT state ilerletme — market retry veya iptal.

        VOLATILE/OLAY → market emir YASAK → CANCELLED.
        TREND/RANGE → market retry (max 1 kez).

        Args:
            symbol: Kontrat sembolü.
            trade: TIMEOUT state'teki Trade.
            regime: Mevcut rejim.
        """
        # Bekleyen emri iptal et
        self.mt5.cancel_order(trade.order_ticket)

        # VOLATILE/OLAY rejimde market emir yasak
        if trade.regime_at_entry in ("VOLATILE", "OLAY"):
            self._remove_trade(
                symbol, trade,
                f"timeout_no_market_retry "
                f"(regime={trade.regime_at_entry})",
            )
            return

        # Max retry kontrolü
        if trade.retry_count >= 1:
            self._remove_trade(
                symbol, trade, "timeout_max_retry_reached",
            )
            return

        # Market emir gönder
        result = self.mt5.send_order(
            symbol=symbol,
            direction=trade.direction,
            lot=trade.volume,
            price=trade.limit_price,
            sl=trade.sl,
            tp=trade.tp,
            order_type="market",
        )

        if result is None:
            trade.state = TradeState.REJECTED
            trade.cancel_reason = "market_retry_failed"
            self._remove_trade(symbol, trade, "market_retry_send_failed")
            return

        # Market retry başarılı — order ticket'ı kaydet
        trade.state = TradeState.MARKET_RETRY
        trade.order_ticket = result.get("order", 0)
        trade.retry_count += 1

        logger.info(
            f"Market retry [{symbol}]: order_ticket={trade.order_ticket}"
        )
        self.db.insert_event(
            event_type="MARKET_RETRY",
            message=(
                f"Market retry: {trade.direction} {trade.volume} lot "
                f"{symbol} ticket={trade.ticket}"
            ),
            severity="INFO",
            action="market_retry",
        )

    def _advance_market_retry(
        self,
        symbol: str,
        trade: Trade,
        regime: Regime,
    ) -> None:
        """MARKET_RETRY state ilerletme — dolum ve slippage kontrolü.

        Dolum var → slippage kontrol → kabul veya red.
        Dolum yok → REJECTED.

        Args:
            symbol: Kontrat sembolü.
            trade: MARKET_RETRY state'teki Trade.
            regime: Mevcut rejim.
        """
        # MT5'te pozisyon var mı? (Netting: sembol bazlı eşleştir)
        positions = self.mt5.get_positions()
        pos = next(
            (p for p in positions if p.get("symbol") == symbol),
            None,
        )

        if pos is None:
            # Pozisyon oluşmadı
            self._remove_trade(
                symbol, trade, "market_retry_no_position",
            )
            return

        # Pozisyon ticket'ını kaydet (close_position için gerekli)
        trade.ticket = pos.get("ticket", 0)

        # Dolum fiyatı ve slippage kontrolü
        fill_price = pos.get("price_open", 0.0)
        slippage = abs(fill_price - trade.limit_price)

        if trade.max_slippage > 0 and slippage > trade.max_slippage:
            # Slippage aşımı — pozisyonu kapat
            logger.warning(
                f"Slippage aşımı [{symbol}]: "
                f"fill={fill_price:.4f} limit={trade.limit_price:.4f} "
                f"slippage={slippage:.4f} max={trade.max_slippage:.4f}"
            )
            self.mt5.close_position(trade.ticket)
            self._remove_trade(
                symbol, trade,
                f"slippage_exceeded "
                f"({slippage:.4f}>{trade.max_slippage:.4f})",
            )
            return

        # Kabul — dolum başarılı
        trade.state = TradeState.FILLED
        trade.entry_price = fill_price
        trade.filled_volume = trade.volume

        if trade.db_id > 0:
            self.db.update_trade(trade.db_id, {
                "entry_price": fill_price,
            })

        logger.info(
            f"Market retry dolum [{symbol}]: "
            f"fill_price={fill_price:.4f} slippage={slippage:.4f}"
        )
        self.db.insert_event(
            event_type="ORDER_FILLED",
            message=(
                f"Market retry dolum: {trade.direction} {trade.volume} lot "
                f"{symbol} @ {fill_price:.4f}"
            ),
            severity="INFO",
            action="market_retry_filled",
        )

    def _update_fill_price(self, symbol: str, trade: Trade) -> None:
        """MT5 pozisyondan gerçek dolum fiyatını al ve DB güncelle.

        Args:
            symbol: Kontrat sembolü.
            trade: Güncellenecek Trade.
        """
        positions = self.mt5.get_positions()
        pos = next(
            (p for p in positions if p.get("ticket") == trade.ticket),
            None,
        )

        if pos:
            trade.entry_price = pos.get(
                "price_open", trade.entry_price,
            )

        if trade.db_id > 0:
            self.db.update_trade(trade.db_id, {
                "entry_price": trade.entry_price,
            })

    # ═════════════════════════════════════════════════════════════════
    #  İŞLEM SAATLERİ VE GÜN SONU
    # ═════════════════════════════════════════════════════════════════

    def _is_trading_allowed(
        self,
        now: datetime | None = None,
    ) -> bool:
        """İşlem saatleri içinde olup olmadığını kontrol et.

        09:45-17:45 arası + piyasa açık (hafta içi, tatil değil).

        Args:
            now: Kontrol zamanı (varsayılan: şu an).

        Returns:
            İşlem yapılabilir ise True.
        """
        if now is None:
            now = datetime.now()

        from engine.utils.time_utils import is_market_open
        if not is_market_open(now):
            return False

        current_time = now.time()
        return TRADING_OPEN <= current_time <= TRADING_CLOSE

    def _check_end_of_day(
        self,
        now: datetime | None = None,
    ) -> None:
        """Gün sonu kontrolü — 17:45 sonrası tüm pozisyon/emir kapatma.

        FILLED pozisyonlar → close_position.
        SENT/PARTIAL emirler → cancel_order + remove.

        Args:
            now: Kontrol zamanı (varsayılan: şu an).
        """
        if now is None:
            now = datetime.now()

        if now.time() < TRADING_CLOSE:
            return

        if not self.active_trades:
            return

        logger.warning(
            "Gün sonu: tüm pozisyon ve emirler kapatılıyor"
        )

        for symbol in list(self.active_trades):
            trade = self.active_trades[symbol]

            if trade.state == TradeState.FILLED:
                # Pozisyonu kapat
                self.mt5.close_position(trade.ticket)
                self._handle_closed_trade(symbol, trade, "end_of_day")

            elif trade.state in (
                TradeState.SENT, TradeState.PARTIAL,
                TradeState.TIMEOUT, TradeState.MARKET_RETRY,
            ):
                # Bekleyen emri iptal et
                if trade.order_ticket:
                    self.mt5.cancel_order(trade.order_ticket)
                # Kısmi dolum varsa pozisyonu da kapat
                if trade.ticket and trade.filled_volume > 0:
                    self.mt5.close_position(trade.ticket)
                self._remove_trade(symbol, trade, "end_of_day")

        self.db.insert_event(
            event_type="EOD_CLOSE",
            message="Gün sonu: tüm pozisyon ve emirler kapatıldı",
            severity="INFO",
            action="eod_close",
        )

    # ═════════════════════════════════════════════════════════════════
    #  AKTİF İŞLEM YÖNETİMİ
    # ═════════════════════════════════════════════════════════════════

    def _manage_active_trades(self, regime: Regime) -> None:
        """Mevcut açık işlemleri yönet — trailing stop, çıkış kontrolleri.

        Her cycle'da ``process_signals()`` başında çağrılır.

        Args:
            regime: Mevcut piyasa rejimi.
        """
        if not self.active_trades:
            return

        # VOLATILE / OLAY → FILLED pozisyonları kapat
        if regime.regime_type in (RegimeType.VOLATILE, RegimeType.OLAY):
            for symbol in list(self.active_trades):
                trade = self.active_trades[symbol]
                if trade.state != TradeState.FILLED:
                    continue
                close_result = self.mt5.close_position(trade.ticket)
                reason = f"regime_{regime.regime_type.value.lower()}"
                if close_result:
                    logger.warning(
                        f"Rejim değişimi kapanış [{symbol}]: {reason}"
                    )
                self._handle_closed_trade(symbol, trade, reason)
            return

        # Her aktif işlem için strateji bazlı kontrol (sadece FILLED)
        for symbol in list(self.active_trades):
            trade = self.active_trades[symbol]

            # Sadece dolu pozisyonları yönet
            if trade.state != TradeState.FILLED:
                continue

            # Pozisyon hâlâ MT5'te var mı? (Netting: sembol bazlı eşleştir)
            positions = self.mt5.get_positions()
            pos = next(
                (p for p in positions if p.get("symbol") == symbol),
                None,
            )
            if pos is None:
                # Pozisyon harici kapanmış (SL/TP hit)
                self._handle_closed_trade(symbol, trade, "sl_tp")
                continue

            # Pozisyon ticket'ını güncelle (senkronizasyon)
            pos_ticket = pos.get("ticket", 0)
            if pos_ticket and pos_ticket != trade.ticket:
                trade.ticket = pos_ticket

            # Strateji bazlı çıkış kontrolleri
            if trade.strategy == "trend_follow":
                self._manage_trend_follow(symbol, trade, pos)
            elif trade.strategy == "mean_reversion":
                self._manage_mean_reversion(symbol, trade, pos)
            # breakout: sabit SL/TP, ek kontrol yok

    def _manage_trend_follow(
        self,
        symbol: str,
        trade: Trade,
        pos: dict[str, Any],
    ) -> None:
        """Trend follow işlem yönetimi — EMA ihlali + trailing stop.

        Args:
            symbol: Kontrat sembolü.
            trade: Aktif Trade nesnesi.
            pos: MT5 pozisyon bilgisi.
        """
        df = self.db.get_bars(symbol, "M15", limit=MIN_BARS_M15)
        if df.empty or len(df) < TF_EMA_FAST + 1:
            return

        close = df["close"].values.astype(np.float64)
        high_arr = df["high"].values.astype(np.float64)
        low_arr = df["low"].values.astype(np.float64)

        ema_20 = ema(close, TF_EMA_FAST)
        atr_arr = calc_atr(high_arr, low_arr, close, ATR_PERIOD)

        ema_val = _last_valid(ema_20)
        atr_val = _last_valid(atr_arr)
        current_price = float(pos.get("price_current", close[-1]))

        if ema_val is None or atr_val is None or atr_val <= 0:
            return

        # EMA(20) ihlali kontrolü
        ema_violated = False
        if trade.direction == "BUY" and current_price < ema_val:
            ema_violated = True
        elif trade.direction == "SELL" and current_price > ema_val:
            ema_violated = True

        if ema_violated:
            logger.info(
                f"EMA ihlali kapatma [{symbol}]: "
                f"fiyat={current_price:.4f} EMA(20)={ema_val:.4f}"
            )
            self.mt5.close_position(trade.ticket)
            self._handle_closed_trade(symbol, trade, "ema_violation")
            return

        # Trailing stop güncelleme
        if trade.direction == "BUY":
            new_sl = current_price - TF_TRAILING_ATR_MULT * atr_val
            if new_sl > trade.trailing_sl:
                mod_result = self.mt5.modify_position(
                    trade.ticket, sl=new_sl,
                )
                if mod_result:
                    trade.trailing_sl = new_sl
                    trade.sl = new_sl
                    logger.debug(
                        f"Trailing SL güncellendi [{symbol}]: {new_sl:.4f}"
                    )
        else:  # SELL
            new_sl = current_price + TF_TRAILING_ATR_MULT * atr_val
            if new_sl < trade.trailing_sl:
                mod_result = self.mt5.modify_position(
                    trade.ticket, sl=new_sl,
                )
                if mod_result:
                    trade.trailing_sl = new_sl
                    trade.sl = new_sl
                    logger.debug(
                        f"Trailing SL güncellendi [{symbol}]: {new_sl:.4f}"
                    )

    def _manage_mean_reversion(
        self,
        symbol: str,
        trade: Trade,
        pos: dict[str, Any],
    ) -> None:
        """Mean reversion işlem yönetimi — BB orta bant kontrolü.

        Normalde TP MT5 tarafından yönetilir, ama programatik kontrol de
        ekleyelim — fiyat BB orta bandına ulaştıysa kapat.

        Args:
            symbol: Kontrat sembolü.
            trade: Aktif Trade nesnesi.
            pos: MT5 pozisyon bilgisi.
        """
        df = self.db.get_bars(symbol, "M15", limit=MIN_BARS_M15)
        if df.empty or len(df) < MR_BB_PERIOD + 1:
            return

        close = df["close"].values.astype(np.float64)
        _, bb_middle, _ = bollinger_bands(close, MR_BB_PERIOD, MR_BB_STD)
        bb_mid = _last_valid(bb_middle)

        if bb_mid is None:
            return

        current_price = float(pos.get("price_current", close[-1]))

        # BB orta banda ulaşım kontrolü
        reached_target = False
        if trade.direction == "BUY" and current_price >= bb_mid:
            reached_target = True
        elif trade.direction == "SELL" and current_price <= bb_mid:
            reached_target = True

        if reached_target:
            logger.info(
                f"BB orta bant ulaşımı [{symbol}]: "
                f"fiyat={current_price:.4f} BB_mid={bb_mid:.4f}"
            )
            self.mt5.close_position(trade.ticket)
            self._handle_closed_trade(symbol, trade, "bb_middle_reached")

    # ═════════════════════════════════════════════════════════════════
    #  POZİSYON SENKRONİZASYONU
    # ═════════════════════════════════════════════════════════════════

    def _sync_positions(self) -> None:
        """MT5 pozisyonları ile active_trades senkronize et.

        Netting modda sembol bazlı kontrol: MT5'te o sembolde
        açık pozisyon yoksa → harici kapanmış → DB güncelle.
        """
        if not self.active_trades:
            return

        positions = self.mt5.get_positions()
        open_symbols = {p.get("symbol") for p in positions}

        for symbol in list(self.active_trades):
            trade = self.active_trades[symbol]
            # Sadece dolu pozisyonları senkronize et
            if trade.state != TradeState.FILLED:
                continue
            if symbol not in open_symbols:
                logger.info(
                    f"Pozisyon harici kapanmış [{symbol}]: ticket={trade.ticket}"
                )
                self._handle_closed_trade(symbol, trade, "external_close")

    def _handle_closed_trade(
        self,
        symbol: str,
        trade: Trade,
        exit_reason: str,
    ) -> None:
        """Kapanmış işlemi işle — state güncelle, DB yaz, active_trades'den sil.

        Args:
            symbol: Kontrat sembolü.
            trade: Kapanan Trade nesnesi.
            exit_reason: Kapanış nedeni.
        """
        now = datetime.now()
        trade.state = TradeState.CLOSED
        trade.closed_at = now

        # Son fiyatı al
        tick = self.mt5.get_tick(symbol)
        if tick:
            if trade.direction == "BUY":
                trade.exit_price = tick.bid
            else:
                trade.exit_price = tick.ask
        elif trade.exit_price == 0:
            # Fallback: en son bar kapanışı
            df = self.db.get_bars(symbol, "M15", limit=1)
            if not df.empty:
                trade.exit_price = float(df["close"].values[-1])

        # PnL hesapla
        if trade.entry_price > 0 and trade.exit_price > 0:
            if trade.direction == "BUY":
                trade.pnl = (trade.exit_price - trade.entry_price) * trade.volume * CONTRACT_SIZE
            else:
                trade.pnl = (trade.entry_price - trade.exit_price) * trade.volume * CONTRACT_SIZE

        # DB güncelle
        if trade.db_id > 0:
            self.db.update_trade(trade.db_id, {
                "exit_time": now.isoformat(),
                "exit_price": trade.exit_price,
                "pnl": trade.pnl,
                "exit_reason": exit_reason,
            })

        # Event kaydet
        self.db.insert_event(
            event_type="TRADE_CLOSE",
            message=(
                f"İşlem kapandı: {trade.direction} {trade.volume} lot {symbol} "
                f"@ {trade.exit_price:.4f} PnL={trade.pnl:.2f} "
                f"neden={exit_reason}"
            ),
            severity="INFO",
            action="trade_closed",
        )

        logger.info(
            f"İşlem kapandı [{symbol}]: {exit_reason} "
            f"PnL={trade.pnl:.2f}"
        )

        # Aktif işlemlerden sil
        self.active_trades.pop(symbol, None)

    # ═════════════════════════════════════════════════════════════════
    #  DURUM GERİ YÜKLEME
    # ═════════════════════════════════════════════════════════════════

    def restore_active_trades(self) -> None:
        """Engine restart'ta açık işlemleri geri yükle.

        MT5 pozisyonları ile DB trade kayıtlarını eşleyerek
        ``active_trades`` dict'ini yeniden oluşturur.
        """
        positions = self.mt5.get_positions()
        if not positions:
            logger.info("Geri yükleme: açık pozisyon yok")
            return

        for pos in positions:
            symbol = pos.get("symbol", "")
            ticket = pos.get("ticket", 0)
            direction = pos.get("type", "")

            if not symbol or not ticket:
                continue

            # DB'de eşleşen aktif trade ara
            trades = self.db.get_trades(symbol=symbol, limit=10)
            db_trade = next(
                (
                    t for t in trades
                    if t.get("exit_time") is None
                    and t.get("direction") == direction
                ),
                None,
            )

            trade = Trade(
                symbol=symbol,
                direction=direction,
                volume=pos.get("volume", 0.0),
                entry_price=pos.get("price_open", 0.0),
                sl=pos.get("sl", 0.0),
                tp=pos.get("tp", 0.0),
                state=TradeState.FILLED,
                ticket=ticket,
                strategy=db_trade.get("strategy", "") if db_trade else "",
                trailing_sl=pos.get("sl", 0.0),
                db_id=db_trade.get("id", 0) if db_trade else 0,
            )

            self.active_trades[symbol] = trade
            logger.info(
                f"Geri yüklendi [{symbol}]: ticket={ticket} "
                f"{direction} {trade.volume} lot"
            )

        logger.info(
            f"Geri yükleme tamamlandı: {len(self.active_trades)} aktif işlem"
        )
