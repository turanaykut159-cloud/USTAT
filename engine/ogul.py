"""OĞUL — Sinyal üretimi ve emir state-machine (v12.0).

3 sinyal stratejisi:
    TREND_FOLLOW   — EMA(20)×EMA(50) crossover + ADX>25 + MACD 2-bar
                     M15 giriş + H1 onay, trailing stop 1.5×ATR
    MEAN_REVERSION — RSI(14) aşırı bölge + BB bant teması + ADX<20
                     SL: BB bant ± 1 ATR, TP: BB orta bant
    BREAKOUT       — 20-bar high/low kırılımı + hacim>1.5× + ATR genişleme
                     SL: entry ± 1.5×ATR, TP: %100 range genişliği

Rejim → Aktif sinyaller:
    TREND    → trend follow aktif, mean reversion deaktif
    RANGE    → mean reversion aktif, breakout bekle
    VOLATILE → TÜM sinyaller durur
    OLAY     → SİSTEM PAUSE
"""

from __future__ import annotations

import math
import time as _time
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
from engine.utils.helpers import last_valid, last_n_valid
from engine.utils.indicators import (
    adx as calc_adx,
    atr as calc_atr,
    ema,
    bollinger_bands,
    rsi as calc_rsi,
    macd as calc_macd,
    bb_kc_squeeze,
    williams_r as calc_williams_r,
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
MR_RSI_OVERSOLD:  float = 20.0
MR_RSI_OVERBOUGHT: float = 80.0
MR_ADX_THRESHOLD: float = 20.0      # ADX < 20 gerekli
MR_BB_PERIOD:     int   = 20
MR_BB_STD:        float = 2.0
MR_SL_ATR_MULT:   float = 1.0       # BB bant ± 1 ATR

# ── Breakout ──────────────────────────────────────────────────────
BO_LOOKBACK:       int   = 20       # 20-bar high/low
BO_VOLUME_MULT:    float = 1.5      # hacim > ort × 1.5
BO_ATR_EXPANSION:  float = 1.2      # ATR genişleme oranı
BO_SL_ATR_MULT:    float = 1.5      # Breakout SL = entry ± 1.5 × ATR
BO_TRAILING_ATR_MULT: float = 2.0   # trailing stop: fiyat ± 2×ATR (trend follow'dan geniş)
BO_REENTRY_BARS: int = 3            # son 3 bar range içine dönmüşse = false breakout

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

# ── Likidite Sınıfı Bazlı Parametreler ───────────────────────
# A sınıfı: yüksek likidite (F_THYAO, F_AKBNK, F_ASELS, F_TCELL, F_PGSUS)
# B sınıfı: orta likidite (F_HALKB, F_GUBRF, F_EKGYO, F_SOKM, F_TKFEN)
# C sınıfı: düşük likidite (F_OYAKC, F_BRSAN, F_AKSEN, F_ASTOR, F_KONTR)

LIQUIDITY_CLASSES: dict[str, str] = {
    "F_THYAO": "A", "F_AKBNK": "A", "F_ASELS": "A",
    "F_TCELL": "A", "F_PGSUS": "A",
    "F_HALKB": "B", "F_GUBRF": "B", "F_EKGYO": "B",
    "F_SOKM": "B", "F_TKFEN": "B",
    "F_OYAKC": "C", "F_BRSAN": "C", "F_AKSEN": "C",
    "F_ASTOR": "C", "F_KONTR": "C",
}

# Breakout: volume çarpanı (likidite bazlı)
BO_VOLUME_MULT_BY_CLASS: dict[str, float] = {
    "A": 1.5,    # A sınıfında 1.5x yeterli (zaten likit)
    "B": 2.0,    # B sınıfında daha yüksek eşik (gürültü filtrele)
    "C": 3.0,    # C sınıfında çok yüksek eşik (gerçek kırılım filtresi)
}

# ATR genişleme çarpanı (likidite bazlı)
BO_ATR_EXPANSION_BY_CLASS: dict[str, float] = {
    "A": 1.2,    # standart
    "B": 1.3,    # biraz daha sıkı
    "C": 1.5,    # C sınıfında ATR zaten geniş, daha sıkı filtre
}

# Trailing stop ATR çarpanı (likidite bazlı) — tüm stratejiler
TRAILING_ATR_BY_CLASS: dict[str, float] = {
    "A": 1.5,    # dar stop (likit, hızlı çıkış mümkün)
    "B": 1.8,    # biraz geniş
    "C": 2.5,    # geniş stop (düşük likidite, spread geniş, fakeout riski)
}


# ═════════════════════════════════════════════════════════════════════
#  YARDIMCI FONKSİYONLAR
# ═════════════════════════════════════════════════════════════════════


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
        risk_params: RiskParams | None = None,
    ) -> None:
        self.config = config
        self.mt5 = mt5
        self.db = db
        self.baba = baba
        self.risk_params = risk_params or RiskParams()
        self.active_trades: dict[str, Trade] = {}
        self.last_signals: dict[str, str] = {}  # symbol → "BUY"|"SELL"|"BEKLE"
        self.h_engine: Any | None = None  # HEngine referansı (main.py tarafından atanır)

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

        # 5. Her sembol için yön eğilimi (bias) hesapla — her zaman, koşulsuz
        for symbol in symbols:
            self.last_signals[symbol] = self._calculate_bias(symbol)

        # 6. Rejim kontrolü — aktif stratejiler
        strategies = REGIME_STRATEGIES.get(regime.regime_type, [])
        if not strategies:
            logger.debug(
                f"Rejim {regime.regime_type.value}: tüm sinyaller deaktif"
            )
            return

        # 7. İşlem saatleri kontrolü
        if not self._is_trading_allowed():
            return

        # 8. Her sembol için sinyal üretimi
        for symbol in symbols:
            # Sembol başına 1 aktif işlem kuralı
            if symbol in self.active_trades:
                continue

            # Hibrit yönetimindeki sembol atla (netting koruması)
            if self.h_engine and symbol in self.h_engine.get_hybrid_symbols():
                logger.debug(f"Hibrit yönetiminde: {symbol} — sinyal atlanıyor")
                continue

            # Kill-switch kontrolü
            if self.baba and self.baba.is_symbol_killed(symbol):
                logger.debug(f"Sembol durdurulmuş (L1): {symbol}")
                continue

            signal = self._generate_signal(symbol, regime, strategies)
            if signal:
                self.last_signals[symbol] = signal.signal_type.value
                self._execute_signal(signal, regime)

    # ═════════════════════════════════════════════════════════════════
    #  YÖN EĞİLİMİ (BIAS)
    # ═════════════════════════════════════════════════════════════════

    @staticmethod
    def _get_liq_class(symbol: str) -> str:
        """Sembolün likidite sınıfını döndür (A/B/C)."""
        return LIQUIDITY_CLASSES.get(symbol, "C")  # bilinmeyen = C (en muhafazakâr)

    def _calculate_bias(self, symbol: str) -> str:
        """İndikatör bazlı yön eğilimi (sinyal eşiği olmadan).

        3 temel indikatörün çoğunluk oyu:
        RSI(14), EMA(20/50) crossover, MACD histogram.

        Returns:
            ``"BUY"``, ``"SELL"`` veya ``"NOTR"``.
        """
        df = self.db.get_bars(symbol, "M15", limit=MIN_BARS_M15)
        if df is None or df.empty or len(df) < MIN_BARS_M15:
            return "NOTR"

        close = df["close"].values.astype(np.float64)
        votes = 0  # pozitif=BUY, negatif=SELL

        # 1. RSI — 50 üstü bullish, 50 altı bearish
        rsi_arr = calc_rsi(close, period=MR_RSI_PERIOD)
        rsi_val = last_valid(rsi_arr)
        if rsi_val is not None:
            if rsi_val > 50:
                votes += 1
            elif rsi_val < 50:
                votes -= 1

        # 2. EMA crossover — fast > slow bullish
        ema_f = ema(close, period=TF_EMA_FAST)
        ema_s = ema(close, period=TF_EMA_SLOW)
        ef = last_valid(ema_f)
        es = last_valid(ema_s)
        if ef is not None and es is not None:
            if ef > es:
                votes += 1
            elif ef < es:
                votes -= 1

        # 3. MACD histogram — pozitif bullish
        _, _, hist = calc_macd(close)
        h = last_valid(hist)
        if h is not None:
            if h > 0:
                votes += 1
            elif h < 0:
                votes -= 1

        if votes > 0:
            return "BUY"
        elif votes < 0:
            return "SELL"
        return "NOTR"

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

        # C1: Seans zamanlama filtresi — açılış/kapanış volatilitesinde
        # strength düşürme (09:45-10:15 ve 17:15-17:45)
        now_time = datetime.now().time()
        SESSION_OPEN_END = time(10, 15)
        SESSION_CLOSE_START = time(17, 15)
        if now_time < SESSION_OPEN_END or now_time >= SESSION_CLOSE_START:
            original_str = best.strength
            best.strength = best.strength * 0.5
            logger.debug(
                f"Seans filtresi [{symbol}]: strength {original_str:.2f} "
                f"→ {best.strength:.2f} (saat={now_time})"
            )

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
        ema_f = last_valid(ema_fast)
        ema_s = last_valid(ema_slow)
        adx_val = last_valid(adx_arr)
        atr_val = last_valid(atr_arr)

        if any(v is None for v in (ema_f, ema_s, adx_val, atr_val)):
            return None
        if atr_val <= 0:
            return None

        # MACD histogram son 2 bar
        hist_vals = last_n_valid(histogram, TF_MACD_CONFIRM_BARS)
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

        Long: RSI(14) < 20 + BB alt bant teması + ADX < 20 + W%R < -80
        Short: RSI(14) > 80 + BB üst bant teması + ADX < 20 + W%R > -20
        C3: Williams %R çift onay eklendi.
        """
        # İndikatörler
        rsi_arr = calc_rsi(close, MR_RSI_PERIOD)
        bb_upper, bb_middle, bb_lower = bollinger_bands(
            close, MR_BB_PERIOD, MR_BB_STD,
        )
        adx_arr = calc_adx(high, low, close, ATR_PERIOD)
        atr_arr = calc_atr(high, low, close, ATR_PERIOD)
        wr_arr = calc_williams_r(high, low, close, MR_RSI_PERIOD)

        # Son geçerli değerler
        rsi_val = last_valid(rsi_arr)
        bb_up = last_valid(bb_upper)
        bb_mid = last_valid(bb_middle)
        bb_low = last_valid(bb_lower)
        adx_val = last_valid(adx_arr)
        atr_val = last_valid(atr_arr)
        wr_val = last_valid(wr_arr)

        if any(v is None for v in (rsi_val, bb_up, bb_mid, bb_low, adx_val, atr_val)):
            return None
        if atr_val <= 0:
            return None

        # ADX eşik — range piyasası gerekli
        if adx_val >= MR_ADX_THRESHOLD:
            return None

        last_close = float(close[-1])
        direction: SignalType | None = None

        # Long: RSI < 20 + BB alt bant teması + W%R < -80 (C3)
        if rsi_val < MR_RSI_OVERSOLD and last_close <= bb_low:
            if wr_val is not None and wr_val < -80.0:
                direction = SignalType.BUY
        # Short: RSI > 80 + BB üst bant teması + W%R > -20 (C3)
        elif rsi_val > MR_RSI_OVERBOUGHT and last_close >= bb_up:
            if wr_val is not None and wr_val > -20.0:
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
        atr_val = last_valid(atr_arr)
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

        liq_class = self._get_liq_class(symbol)
        vol_mult = BO_VOLUME_MULT_BY_CLASS.get(liq_class, BO_VOLUME_MULT)
        if vol_avg <= 0 or current_vol <= vol_avg * vol_mult:
            return None

        # ATR genişleme kontrolü
        atr_valid = atr_arr[~np.isnan(atr_arr)]
        if len(atr_valid) < 5:
            return None
        atr_mean = float(np.mean(atr_valid[:-1])) if len(atr_valid) > 1 else atr_val
        atr_exp = BO_ATR_EXPANSION_BY_CLASS.get(liq_class, BO_ATR_EXPANSION)
        if atr_mean <= 0 or atr_val <= atr_mean * atr_exp:
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

        if direction == SignalType.BUY:
            sl = last_close - BO_SL_ATR_MULT * atr_val
            tp = price + range_width
        else:
            sl = last_close + BO_SL_ATR_MULT * atr_val
            tp = price - range_width

        # Sinyal gücü: hacim patlaması (0-0.5) + ATR genişleme (0-0.3) + kırılım büyüklüğü (0-0.2)
        # A2 fix: likidite sınıfı bazlı eşikler kullanılıyor (global sabit yerine)
        vol_str = min((current_vol / vol_avg - vol_mult) / 2.0, 0.5)
        atr_str = min((atr_val / atr_mean - atr_exp) / 1.0, 0.3)
        if direction == SignalType.BUY:
            break_size = (last_close - high_20) / atr_val if atr_val > 0 else 0.0
        else:
            break_size = (low_20 - last_close) / atr_val if atr_val > 0 else 0.0
        break_str = min(break_size * 0.2, 0.2)

        strength = max(vol_str, 0.0) + max(atr_str, 0.0) + max(break_str, 0.0)

        # C2: Squeeze çıkışında bonus — sıkışma sonrası kırılım daha güvenilir
        squeeze_arr = bb_kc_squeeze(high, low, close)
        squeeze_bonus = 0.0
        if len(squeeze_arr) >= 3:
            # Son 3 bar'dan en az 1'i squeeze ise → yakın zamanda sıkışma vardı
            recent_squeeze = squeeze_arr[-3:]
            valid_sq = recent_squeeze[~np.isnan(recent_squeeze)]
            if len(valid_sq) > 0 and np.any(valid_sq == 1.0):
                squeeze_bonus = 0.15
                strength += squeeze_bonus

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

        ef = last_valid(ema_fast_h1)
        es = last_valid(ema_slow_h1)

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

        # BABA onay — korelasyon kontrolü (Madde 2.1: merkezi risk_params)
        if self.baba:
            corr_verdict = self.baba.check_correlation_limits(
                symbol, direction, self.risk_params,
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
        lot = self._calculate_lot(signal, regime, equity, self.risk_params)
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

    # ═════════════════════════════════════════════════════════════════
    #  MANUEL İŞLEM (İŞLEM PANELİ)
    # ═════════════════════════════════════════════════════════════════

    def check_manual_trade(self, symbol: str, direction: str) -> dict:
        """Manuel işlem için risk ön kontrolü (emir göndermez).

        BABA risk limitlerini, korelasyon kurallarını, teminat ve
        eş zamanlı pozisyon limitini kontrol eder.  Read-only.

        Args:
            symbol: Base sembol (ör. ``"F_THYAO"``).
            direction: ``"BUY"`` veya ``"SELL"``.

        Returns:
            dict anahtarları:
                can_trade, reason, suggested_lot, current_price,
                atr_value, risk_summary.
        """
        result: dict[str, Any] = {
            "can_trade": False,
            "reason": "",
            "suggested_lot": 0.0,
            "current_price": 0.0,
            "atr_value": 0.0,
            "risk_summary": {},
        }

        # 1. İşlem saatleri
        if not self._is_trading_allowed():
            result["reason"] = "İşlem saatleri dışında (09:45-17:45)"
            return result

        # 2. Sembol active_trades'de mi? (netting çakışma)
        if symbol in self.active_trades:
            existing = self.active_trades[symbol]
            result["reason"] = (
                f"Bu sembolde zaten aktif pozisyon var "
                f"({existing.direction} {existing.volume} lot)"
            )
            return result

        # 3. BABA risk kontrolü (Madde 2.1: merkezi risk_params)
        if not self.baba:
            result["reason"] = "BABA başlatılmamış"
            return result

        verdict = self.baba.check_risk_limits(self.risk_params)
        result["risk_summary"] = {
            "regime": (
                self.baba.current_regime.regime_type.value
                if self.baba.current_regime else "UNKNOWN"
            ),
            "risk_multiplier": (
                self.baba.current_regime.risk_multiplier
                if self.baba.current_regime else 0
            ),
            "kill_switch_level": self.baba._kill_switch_level,
            "daily_trade_count": self.baba._risk_state.get(
                "daily_trade_count", 0,
            ),
            "max_daily_trades": self.risk_params.max_daily_trades,
            "consecutive_losses": self.baba._risk_state.get(
                "consecutive_losses", 0,
            ),
            "lot_multiplier": verdict.lot_multiplier,
            "can_trade": verdict.can_trade,
        }
        if not verdict.can_trade:
            result["reason"] = verdict.reason
            return result

        # 4. Korelasyon kontrolü
        corr = self.baba.check_correlation_limits(
            symbol, direction, self.risk_params,
        )
        if not corr.can_trade:
            result["reason"] = corr.reason
            return result

        # 5. Eş zamanlı pozisyon limiti
        active_states = (
            TradeState.FILLED, TradeState.SENT,
            TradeState.PARTIAL, TradeState.MARKET_RETRY,
        )
        active_count = sum(
            1 for t in self.active_trades.values()
            if t.state in active_states
        )
        if active_count >= MAX_CONCURRENT:
            result["reason"] = (
                f"Eş zamanlı pozisyon limiti doldu "
                f"({active_count}/{MAX_CONCURRENT})"
            )
            return result

        # 6. Teminat kontrolü
        account = self.mt5.get_account_info()
        if account is None:
            result["reason"] = "Hesap bilgisi alınamadı"
            return result
        if account.free_margin < account.equity * MARGIN_RESERVE_PCT:
            result["reason"] = (
                f"Yetersiz teminat (serbest={account.free_margin:.0f})"
            )
            return result

        # 7. ATR & lot hesaplama
        atr_val = self._get_current_atr(symbol)
        if atr_val is None or atr_val <= 0:
            result["reason"] = f"ATR hesaplanamadı ({symbol})"
            return result

        lot = self.baba.calculate_position_size(
            symbol, self.risk_params, atr_val, account.equity,
        )
        lot = min(lot, MAX_LOT_PER_CONTRACT)

        # 8. Fiyat
        tick = self.mt5.get_tick(symbol)
        current_price = 0.0
        if tick:
            current_price = tick.ask if direction == "BUY" else tick.bid

        # 9. Suggested SL/TP (Madde 1.5)
        if current_price > 0 and atr_val > 0:
            if direction == "BUY":
                suggested_sl = current_price - (atr_val * 1.5)
                suggested_tp = current_price + (atr_val * 2.0)
            else:
                suggested_sl = current_price + (atr_val * 1.5)
                suggested_tp = current_price - (atr_val * 2.0)
        else:
            suggested_sl = 0.0
            suggested_tp = 0.0

        # 10. Sembol bazlı max lot (Madde 2.5)
        sym_info = self.mt5.get_symbol_info(symbol)
        max_lot = sym_info.volume_max if sym_info else 10.0

        result["can_trade"] = True
        result["suggested_lot"] = lot
        result["current_price"] = current_price
        result["atr_value"] = atr_val
        result["suggested_sl"] = round(suggested_sl, 2)
        result["suggested_tp"] = round(suggested_tp, 2)
        result["max_lot"] = max_lot
        result["risk_summary"]["floating_pnl"] = (
            account.profit if hasattr(account, "profit") else 0.0
        )
        result["risk_summary"]["equity"] = account.equity
        result["risk_summary"]["free_margin"] = account.free_margin
        return result

    def open_manual_trade(
        self,
        symbol: str,
        direction: str,
        lot: float,
        sl: float | None = None,
        tp: float | None = None,
    ) -> dict:
        """Manuel market emri gönder ve active_trades'e kaydet.

        ``_execute_signal()`` akışının basitleştirilmiş versiyonu.
        MARKET emir gönderir, LIMIT değil.
        SL verilmezse ATR×1.5 otomatik hesaplanır (Madde 1.5).
        TP verilmezse ATR×2.0 otomatik hesaplanır.

        Args:
            symbol: Base sembol (``"F_THYAO"``).
            direction: ``"BUY"`` veya ``"SELL"``.
            lot: Lot miktarı.

        Returns:
            dict anahtarları:
                success, message, ticket, entry_price, sl, tp, lot.
        """
        result: dict[str, Any] = {
            "success": False,
            "message": "",
            "ticket": 0,
            "entry_price": 0.0,
            "sl": 0.0,
            "tp": 0.0,
            "lot": 0.0,
        }

        # 1. Tekrar risk kontrolü (race condition önlemi)
        check = self.check_manual_trade(symbol, direction)
        if not check["can_trade"]:
            result["message"] = check["reason"]
            return result

        # 2. ATR → SL/TP hesapla
        atr_val = self._get_current_atr(symbol)
        if atr_val is None or atr_val <= 0:
            result["message"] = "ATR hesaplanamadı"
            return result

        tick_data = self.mt5.get_tick(symbol)
        if tick_data is None:
            result["message"] = "Fiyat alınamadı"
            return result

        price = tick_data.ask if direction == "BUY" else tick_data.bid

        # Madde 1.5: Kullanıcı SL/TP verdiyse kullan, vermediyse ATR bazlı otomatik
        if sl is None or sl <= 0:
            if direction == "BUY":
                sl = price - (atr_val * 1.5)
            else:
                sl = price + (atr_val * 1.5)
            logger.info(f"Manuel SL otomatik: {sl:.2f} (ATR×1.5={atr_val*1.5:.2f})")

        if tp is None or tp <= 0:
            if direction == "BUY":
                tp = price + (atr_val * 2.0)
            else:
                tp = price - (atr_val * 2.0)
            logger.info(f"Manuel TP otomatik: {tp:.2f} (ATR×2.0={atr_val*2.0:.2f})")

        # 3. Lot sınırlama — sembol bazlı (Madde 2.5)
        sym_info = self.mt5.get_symbol_info(symbol)
        if sym_info:
            vol_min = sym_info.volume_min
            vol_max = sym_info.volume_max
            vol_step = sym_info.volume_step if sym_info.volume_step > 0 else vol_min

            if lot < vol_min:
                result["message"] = (
                    f"Lot çok düşük: {lot} (min={vol_min})"
                )
                return result
            if lot > vol_max:
                result["message"] = (
                    f"Lot çok yüksek: {lot} (max={vol_max})"
                )
                return result

            # volume_step'e yuvarlama
            if vol_step > 0:
                lot = round(lot / vol_step) * vol_step
                lot = round(lot, 8)  # float hassasiyet düzeltme
        else:
            lot = min(lot, MAX_LOT_PER_CONTRACT)

        if lot <= 0:
            result["message"] = "Geçersiz lot miktarı"
            return result

        # 4. Trade nesnesi oluştur
        now = datetime.now()
        regime = self.baba.current_regime if self.baba else None
        regime_str = regime.regime_type.value if regime else "UNKNOWN"

        trade = Trade(
            symbol=symbol,
            direction=direction,
            volume=lot,
            entry_price=price,
            sl=sl,
            tp=tp,
            state=TradeState.SIGNAL,
            opened_at=now,
            strategy="manual",
            trailing_sl=sl,
            regime_at_entry=regime_str,
            requested_volume=lot,
        )

        # 5. MARKET emir gönder
        order_result = self.mt5.send_order(
            symbol=symbol,
            direction=direction,
            lot=lot,
            price=price,
            sl=sl,
            tp=tp,
            order_type="market",
        )

        if order_result is None:
            # ── KRİTİK: Spesifik MT5 hata mesajı ──────────────────
            err = self.mt5._last_order_error
            if err.get("retcode"):
                error_detail = (
                    f"MT5 retcode={err['retcode']}: "
                    f"{err.get('comment', 'bilinmeyen hata')}"
                )
            elif err.get("reason"):
                error_detail = err["reason"]
            else:
                error_detail = "Bilinmeyen MT5 hatası"

            result["message"] = f"Emir gönderilemedi — {error_detail}"
            self.db.insert_event(
                event_type="MANUAL_TRADE_ERROR",
                message=(
                    f"Manuel emir başarısız: "
                    f"{direction} {lot} lot {symbol} — {error_detail}"
                ),
                severity="ERROR",
                action="manual_order_failed",
            )
            return result

        # 6. Başarılı → state güncelle
        trade.state = TradeState.SENT
        trade.order_ticket = order_result.get("order", 0)
        trade.sent_at = now

        # 7. DB kayıt
        db_id = self.db.insert_trade({
            "strategy": "manual",
            "symbol": symbol,
            "direction": direction,
            "entry_time": now.isoformat(),
            "entry_price": price,
            "lot": lot,
            "regime": regime_str,
        })
        trade.db_id = db_id

        # 8. active_trades'e ekle — OĞUL yönetimi devralır
        self.active_trades[symbol] = trade

        # 9. BABA sayaç güncelle
        if self.baba:
            self.baba.increment_daily_trade_count()

        # 10. Event kaydet
        self.db.insert_event(
            event_type="MANUAL_ORDER_SENT",
            message=(
                f"Manuel MARKET emir: {direction} {lot} lot {symbol} "
                f"@ {price:.4f} SL={sl:.4f} TP={tp:.4f}"
            ),
            severity="INFO",
            action="manual_order_sent",
        )

        logger.info(
            f"Manuel emir gönderildi [{symbol}]: "
            f"{direction} {lot} lot @ {price:.4f}"
        )

        result["success"] = True
        result["message"] = "Emir başarıyla gönderildi"
        result["ticket"] = trade.order_ticket
        result["entry_price"] = price
        result["sl"] = round(sl, 4)
        result["tp"] = round(tp, 4)
        result["lot"] = lot
        return result

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

        A4: Bias-lot entegrasyonu — bias ters yöndeyse lot=0,
        bias nötr ise lot*0.7 (güven düşürme).

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

        # A4: Bias-lot entegrasyonu
        bias = self._calculate_bias(signal.symbol)
        direction = "BUY" if signal.signal_type == SignalType.BUY else "SELL"
        if bias != "NOTR" and bias != direction:
            # Bias ters yönde → işlem yapma
            logger.info(
                f"Bias-lot engeli [{signal.symbol}]: "
                f"sinyal={direction}, bias={bias} → lot=0"
            )
            return 0.0
        elif bias == "NOTR":
            # Bias nötr → güven düşürme
            lot = lot * 0.7
            logger.debug(
                f"Bias-lot nötr [{signal.symbol}]: lot*0.7={lot:.2f}"
            )

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
        return last_valid(atr_arr)

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
            # Günlük işlem sayacı — sadece gerçek dolumda artır
            if self.baba:
                self.baba.increment_daily_trade_count()

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
        try:
            self.mt5.cancel_order(trade.order_ticket)
        except Exception as exc:
            logger.error(f"cancel_order hatası [{symbol}] ticket={trade.order_ticket}: {exc}")

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
            # Günlük işlem sayacı — kısmi dolum kabul edildi
            if self.baba:
                self.baba.increment_daily_trade_count()
        else:
            # Yetersiz — kısmi pozisyonu kapat
            if trade.ticket:
                try:
                    self.mt5.close_position(trade.ticket)
                except Exception as exc:
                    logger.error(f"close_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
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
        try:
            self.mt5.cancel_order(trade.order_ticket)
        except Exception as exc:
            logger.error(f"cancel_order hatası [{symbol}] ticket={trade.order_ticket}: {exc}")

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
        try:
            positions = self.mt5.get_positions()
        except Exception as exc:
            logger.error(f"get_positions hatası [{symbol}]: {exc}")
            positions = []
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
            try:
                self.mt5.close_position(trade.ticket)
            except Exception as exc:
                logger.error(f"close_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
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
        # Günlük işlem sayacı — market retry dolum
        if self.baba:
            self.baba.increment_daily_trade_count()

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

        Netting mode: sembol bazlı eşleştirme (ticket değişebilir).

        Args:
            symbol: Kontrat sembolü.
            trade: Güncellenecek Trade.
        """
        try:
            positions = self.mt5.get_positions()
        except Exception as exc:
            logger.error(f"get_positions hatası [{symbol}] (fill_price): {exc}")
            return
        # Netting mode: sembol bazlı eşleştir
        pos = next(
            (p for p in positions if p.get("symbol") == symbol),
            None,
        )

        if pos:
            trade.entry_price = pos.get(
                "price_open", trade.entry_price,
            )
            # Ticket güncellemesi — netting merge sonrası farklı olabilir
            new_ticket = pos.get("ticket", 0)
            if new_ticket and new_ticket != trade.ticket:
                logger.debug(
                    f"Ticket güncellendi [{symbol}]: "
                    f"{trade.ticket} → {new_ticket}"
                )
                trade.ticket = new_ticket

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
                try:
                    self.mt5.close_position(trade.ticket)
                except Exception as exc:
                    logger.error(f"EOD close_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
                self._handle_closed_trade(symbol, trade, "end_of_day")

            elif trade.state in (
                TradeState.SENT, TradeState.PARTIAL,
                TradeState.TIMEOUT, TradeState.MARKET_RETRY,
            ):
                # Bekleyen emri iptal et
                if trade.order_ticket:
                    try:
                        self.mt5.cancel_order(trade.order_ticket)
                    except Exception as exc:
                        logger.error(f"EOD cancel_order hatası [{symbol}] ticket={trade.order_ticket}: {exc}")
                # Kısmi dolum varsa pozisyonu da kapat
                if trade.ticket and trade.filled_volume > 0:
                    try:
                        self.mt5.close_position(trade.ticket)
                    except Exception as exc:
                        logger.error(f"EOD close_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
                self._remove_trade(symbol, trade, "end_of_day")

        # Hibrit pozisyonları da kapat (EOD)
        if self.h_engine:
            failed = self.h_engine.force_close_all(reason="EOD_17:45")
            if failed:
                logger.error(f"EOD hibrit kapatma başarısız: {failed}")

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
        MT5 pozisyonları tek seferde alınır (performans).

        Args:
            regime: Mevcut piyasa rejimi.
        """
        if not self.active_trades:
            return

        # MT5 pozisyonlarını BİR KERE al, sembol bazlı indexle
        try:
            positions = self.mt5.get_positions()
        except Exception as exc:
            logger.error(f"get_positions hatası (manage_filled): {exc}")
            return
        pos_by_symbol: dict[str, dict] = {
            p.get("symbol"): p for p in positions
        }

        # VOLATILE / OLAY → FILLED pozisyonları kapat
        if regime.regime_type in (RegimeType.VOLATILE, RegimeType.OLAY):
            for symbol in list(self.active_trades):
                trade = self.active_trades[symbol]
                if trade.state != TradeState.FILLED:
                    continue
                try:
                    close_result = self.mt5.close_position(trade.ticket)
                except Exception as exc:
                    logger.error(f"close_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
                    close_result = None
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

            if trade.state != TradeState.FILLED:
                continue

            # Pozisyon hâlâ MT5'te var mı?
            pos = pos_by_symbol.get(symbol)
            if pos is None:
                self._handle_closed_trade(symbol, trade, "sl_tp")
                continue

            # Pozisyon senkronizasyonu (netting: lot/fiyat değişebilir)
            pos_ticket = pos.get("ticket", 0)
            if pos_ticket and pos_ticket != trade.ticket:
                trade.ticket = pos_ticket
            pos_vol = pos.get("volume", trade.volume)
            pos_entry = pos.get("price_open", trade.entry_price)
            sync_needed = False
            if abs(pos_vol - trade.volume) > 1e-8:
                trade.volume = pos_vol
                sync_needed = True
            if abs(pos_entry - trade.entry_price) > 1e-4:
                trade.entry_price = pos_entry
                sync_needed = True
            if sync_needed and trade.db_id > 0:
                self.db.update_trade(trade.db_id, {
                    "lot": trade.volume,
                    "entry_price": trade.entry_price,
                    "mt5_position_id": trade.ticket,
                })

            # Strateji bazlı çıkış kontrolleri
            if trade.strategy == "trend_follow":
                self._manage_trend_follow(symbol, trade, pos)
            elif trade.strategy == "mean_reversion":
                self._manage_mean_reversion(symbol, trade, pos)
            elif trade.strategy == "breakout":
                self._manage_breakout(symbol, trade, pos)

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

        ema_val = last_valid(ema_20)
        atr_val = last_valid(atr_arr)
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
            try:
                self.mt5.close_position(trade.ticket)
            except Exception as exc:
                logger.error(f"close_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
            self._handle_closed_trade(symbol, trade, "ema_violation")
            return

        # Trailing stop güncelleme — likidite bazlı çarpan
        liq_class = self._get_liq_class(symbol)
        trail_mult = TRAILING_ATR_BY_CLASS.get(liq_class, TF_TRAILING_ATR_MULT)
        if trade.direction == "BUY":
            new_sl = current_price - trail_mult * atr_val
            if new_sl > trade.trailing_sl:
                try:
                    mod_result = self.mt5.modify_position(
                        trade.ticket, sl=new_sl,
                    )
                except Exception as exc:
                    logger.error(f"modify_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
                    mod_result = None
                if mod_result:
                    trade.trailing_sl = new_sl
                    trade.sl = new_sl
                    logger.debug(
                        f"Trailing SL güncellendi [{symbol}]: {new_sl:.4f}"
                    )
        else:  # SELL
            new_sl = current_price + trail_mult * atr_val
            if new_sl < trade.trailing_sl:
                try:
                    mod_result = self.mt5.modify_position(
                        trade.ticket, sl=new_sl,
                    )
                except Exception as exc:
                    logger.error(f"modify_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
                    mod_result = None
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
        """Mean reversion işlem yönetimi — breakeven + BB orta bant kontrolü.

        A5: Kâr %50+ olduğunda SL'yi entry fiyatına çek (breakeven).
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
        bb_mid = last_valid(bb_middle)

        if bb_mid is None:
            return

        current_price = float(pos.get("price_current", close[-1]))

        # A5: Breakeven trailing — kâr %50+ ise SL'yi entry'e çek
        entry = trade.entry_price
        if entry > 0 and trade.sl != entry:
            if trade.direction == "BUY":
                tp_distance = trade.tp - entry if trade.tp > 0 else 0
                current_profit = current_price - entry
            else:
                tp_distance = entry - trade.tp if trade.tp > 0 else 0
                current_profit = entry - current_price

            # TP mesafesinin %50'sine ulaştıysa breakeven
            if tp_distance > 0 and current_profit >= tp_distance * 0.5:
                try:
                    mod_result = self.mt5.modify_position(
                        trade.ticket, sl=entry,
                    )
                except Exception as exc:
                    logger.error(
                        f"MR breakeven hatası [{symbol}] "
                        f"ticket={trade.ticket}: {exc}"
                    )
                    mod_result = None
                if mod_result:
                    trade.sl = entry
                    trade.trailing_sl = entry
                    logger.info(
                        f"MR breakeven [{symbol}]: SL→entry={entry:.4f} "
                        f"(kâr={current_profit:.4f}, "
                        f"TP mesafe={tp_distance:.4f})"
                    )

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
            try:
                self.mt5.close_position(trade.ticket)
            except Exception as exc:
                logger.error(f"close_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
            self._handle_closed_trade(symbol, trade, "bb_middle_reached")

    def _manage_breakout(
        self,
        symbol: str,
        trade: Trade,
        pos: dict[str, Any],
    ) -> None:
        """Breakout işlem yönetimi — false breakout tespiti + trailing stop.

        İki savunma katmanı:
        1. False breakout tespiti: fiyat kırılım range'inin içine geri döndüyse kapat
        2. Trailing stop: 2×ATR (trend follow'dan geniş, breakout'a alan tanı)

        Args:
            symbol: Kontrat sembolü.
            trade: Aktif Trade nesnesi.
            pos: MT5 pozisyon bilgisi.
        """
        df = self.db.get_bars(symbol, "M15", limit=MIN_BARS_M15)
        if df.empty or len(df) < BO_LOOKBACK + 2:
            return

        close = df["close"].values.astype(np.float64)
        high_arr = df["high"].values.astype(np.float64)
        low_arr = df["low"].values.astype(np.float64)

        atr_arr = calc_atr(high_arr, low_arr, close, ATR_PERIOD)
        atr_val = last_valid(atr_arr)
        if atr_val is None or atr_val <= 0:
            return

        current_price = float(pos.get("price_current", close[-1]))

        # ── False breakout tespiti ────────────────────────────────
        # Son BO_REENTRY_BARS bar'ın tamamı kırılım seviyesinin
        # gerisine dönmüşse = false breakout
        recent_closes = close[-BO_REENTRY_BARS:]

        # Kırılım seviyesi: trade açılırken kaydedilen entry_price
        # BUY breakout: fiyat entry altına düştüyse false
        # SELL breakout: fiyat entry üstüne çıktıysa false
        false_breakout = False
        if trade.direction == "BUY":
            if all(c < trade.entry_price for c in recent_closes):
                false_breakout = True
        else:
            if all(c > trade.entry_price for c in recent_closes):
                false_breakout = True

        if false_breakout:
            logger.info(
                f"False breakout tespit [{symbol}]: fiyat={current_price:.4f} "
                f"entry={trade.entry_price:.4f} — pozisyon kapatılıyor"
            )
            try:
                self.mt5.close_position(trade.ticket)
            except Exception as exc:
                logger.error(f"close_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
            self._handle_closed_trade(symbol, trade, "false_breakout")
            return

        # ── Trailing stop (A3: likidite sınıfı bazlı) ─────────────
        liq_class = self._get_liq_class(symbol)
        trail_mult = TRAILING_ATR_BY_CLASS.get(liq_class, BO_TRAILING_ATR_MULT)

        if trade.direction == "BUY":
            new_sl = current_price - trail_mult * atr_val
            if new_sl > trade.trailing_sl:
                try:
                    mod_result = self.mt5.modify_position(
                        trade.ticket, sl=new_sl,
                    )
                except Exception as exc:
                    logger.error(f"modify_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
                    mod_result = None
                if mod_result:
                    trade.trailing_sl = new_sl
                    trade.sl = new_sl
                    logger.debug(
                        f"Breakout trailing SL [{symbol}] "
                        f"(liq={liq_class}, mult={trail_mult}): {new_sl:.4f}"
                    )
        else:
            new_sl = current_price + trail_mult * atr_val
            if new_sl < trade.trailing_sl:
                try:
                    mod_result = self.mt5.modify_position(
                        trade.ticket, sl=new_sl,
                    )
                except Exception as exc:
                    logger.error(f"modify_position hatası [{symbol}] ticket={trade.ticket}: {exc}")
                    mod_result = None
                if mod_result:
                    trade.trailing_sl = new_sl
                    trade.sl = new_sl
                    logger.debug(
                        f"Breakout trailing SL [{symbol}] "
                        f"(liq={liq_class}, mult={trail_mult}): {new_sl:.4f}"
                    )

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

        try:
            positions = self.mt5.get_positions()
        except Exception as exc:
            logger.error(f"get_positions hatası (sync): {exc}")
            return
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
        try:
            tick = self.mt5.get_tick(symbol)
        except Exception as exc:
            logger.error(f"get_tick hatası [{symbol}]: {exc}")
            tick = None
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

        # PnL hesapla — önce fiyat farkından (fallback)
        if trade.entry_price > 0 and trade.exit_price > 0:
            contract_size = CONTRACT_SIZE  # varsayılan fallback
            sym_info = self.mt5.get_symbol_info(symbol)
            if sym_info and hasattr(sym_info, "trade_contract_size"):
                contract_size = sym_info.trade_contract_size

            if trade.direction == "BUY":
                trade.pnl = (trade.exit_price - trade.entry_price) * trade.volume * contract_size
            else:
                trade.pnl = (trade.entry_price - trade.exit_price) * trade.volume * contract_size

        # MT5 deal verisinden gerçek PnL/komisyon/swap al (geçmişe yazılma gecikmesi için retry)
        commission = 0.0
        swap = 0.0
        deal_summary = None
        for attempt in range(3):
            deal_summary = self.mt5.get_deal_summary(trade.ticket)
            if deal_summary is not None:
                break
            if attempt < 2:
                _time.sleep(0.8)
        if deal_summary is not None:
            trade.pnl = deal_summary["pnl"]
            commission = deal_summary["commission"]
            swap = deal_summary["swap"]
            logger.debug(
                f"MT5 deal verisi kullanıldı [{symbol}]: "
                f"pnl={trade.pnl:.2f} comm={commission:.2f} swap={swap:.2f}"
            )

        # DB güncelle — entry_price/lot da dahil (netting değişikliği yansısın)
        if trade.db_id > 0:
            self.db.update_trade(trade.db_id, {
                "exit_time": now.isoformat(),
                "exit_price": trade.exit_price,
                "entry_price": trade.entry_price,
                "lot": trade.volume,
                "pnl": trade.pnl,
                "exit_reason": exit_reason,
                "mt5_position_id": trade.ticket,
                "commission": commission,
                "swap": swap,
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
        """Engine restart'ta açık işlemleri geri yükle (P0-3 iyileştirme).

        MT5 pozisyonları ile DB trade kayıtlarını eşleyerek
        ``active_trades`` dict'ini yeniden oluşturur.

        P0-3: Strateji bilgisi, rejim bilgisi ve entry zamanı da
        DB'den kurtarılır. trailing_sl için mevcut SL kullanılır.
        """
        try:
            positions = self.mt5.get_positions()
        except Exception as exc:
            logger.error(f"get_positions hatası (restore): {exc}")
            return

        if not positions:
            logger.info("Geri yükleme: açık pozisyon yok")
            return

        restored_count = 0
        orphan_count = 0

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

            # P0-3: Strateji ve rejim bilgisini DB'den al
            strategy = db_trade.get("strategy", "") if db_trade else ""
            regime_at_entry = db_trade.get("regime", "") if db_trade else ""
            entry_time_str = db_trade.get("entry_time", "") if db_trade else ""

            opened_at = None
            if entry_time_str:
                try:
                    opened_at = datetime.fromisoformat(entry_time_str)
                except (ValueError, TypeError):
                    pass

            trade = Trade(
                symbol=symbol,
                direction=direction,
                volume=pos.get("volume", 0.0),
                entry_price=pos.get("price_open", 0.0),
                sl=pos.get("sl", 0.0),
                tp=pos.get("tp", 0.0),
                state=TradeState.FILLED,
                ticket=ticket,
                strategy=strategy,
                trailing_sl=pos.get("sl", 0.0),
                db_id=db_trade.get("id", 0) if db_trade else 0,
                regime_at_entry=regime_at_entry,
            )
            if opened_at:
                trade.opened_at = opened_at

            self.active_trades[symbol] = trade
            restored_count += 1

            if db_trade:
                # DB'yi MT5 pozisyonuyla senkronize et (netting farkı düzeltme)
                sync_fields: dict[str, Any] = {}
                db_lot = db_trade.get("lot", 0.0)
                db_entry = db_trade.get("entry_price", 0.0)
                if abs(trade.volume - db_lot) > 1e-8:
                    sync_fields["lot"] = trade.volume
                if abs(trade.entry_price - db_entry) > 1e-4:
                    sync_fields["entry_price"] = trade.entry_price
                if trade.ticket and not db_trade.get("mt5_position_id"):
                    sync_fields["mt5_position_id"] = trade.ticket
                if sync_fields and trade.db_id > 0:
                    self.db.update_trade(trade.db_id, sync_fields)
                    logger.info(
                        f"DB senkronize [{symbol}]: {sync_fields}"
                    )

                logger.info(
                    f"Geri yüklendi [{symbol}]: ticket={ticket} "
                    f"{direction} {trade.volume} lot "
                    f"strateji={strategy} rejim={regime_at_entry}"
                )
            else:
                orphan_count += 1
                logger.warning(
                    f"Yetim pozisyon geri yüklendi [{symbol}]: ticket={ticket} "
                    f"{direction} {trade.volume} lot (DB eşleşmesi yok)"
                )

        logger.info(
            f"Geri yükleme tamamlandı: {restored_count} aktif işlem "
            f"({orphan_count} yetim)"
        )
