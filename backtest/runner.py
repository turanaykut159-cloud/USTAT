"""Backtest motoru — tarihsel veri üzerinde strateji simülasyonu.

Bar-bar simülasyon akışı (her bar için):
    1. Seans boşluk kontrolü (gece/öğle)
    2. Boşluk SL tetiklenmesi kontrolü
    3. Açık pozisyonlar için SL/TP kontrolü (bar H/L'ye karşı)
    4. Trailing stop güncelleme (trend follow)
    5. Son barlardan rejim tespiti
    6. Rejime göre sinyal üretimi
    7. Spread + slippage ile sinyal yürütme
    8. Mark-to-market equity kaydı

engine/ogul.py strateji sabitleri ve engine/utils/indicators.py
fonksiyonları yeniden kullanılır.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from engine.logger import get_logger
from engine.models.regime import RegimeType, RISK_MULTIPLIERS
from engine.models.signal import StrategyType
from engine.utils.indicators import (
    ema,
    rsi as calc_rsi,
    macd as calc_macd,
    atr as calc_atr,
    adx as calc_adx,
    bollinger_bands,
)

# Strateji sabitleri — engine/ogul.py'den import
from engine.ogul import (
    TF_EMA_FAST,
    TF_EMA_SLOW,
    TF_ADX_THRESHOLD,
    TF_MACD_CONFIRM_BARS,
    TF_SL_ATR_MULT,
    TF_TP_ATR_MULT,
    TF_TRAILING_ATR_MULT,
    MR_RSI_PERIOD,
    MR_RSI_OVERSOLD,
    MR_RSI_OVERBOUGHT,
    MR_ADX_THRESHOLD,
    MR_BB_PERIOD,
    MR_BB_STD,
    MR_SL_ATR_MULT,
    BO_LOOKBACK,
    BO_VOLUME_MULT,
    BO_ATR_EXPANSION,
    ATR_PERIOD,
    CONTRACT_SIZE,
    MAX_CONCURRENT,
    REGIME_STRATEGIES,
)

from backtest.spread_model import SpreadModel
from backtest.slippage_model import SlippageModel
from backtest.session_model import SessionModel
from backtest.report import BacktestReport

logger = get_logger(__name__)


# ═════════════════════════════════════════════════════════════════════
#  VERİ MODELLERİ
# ═════════════════════════════════════════════════════════════════════


@dataclass
class BacktestPosition:
    """Backtest simülasyonu sırasında aktif pozisyon."""

    symbol: str
    direction: str              # "BUY" veya "SELL"
    entry_price: float
    entry_time: datetime
    sl: float
    tp: float
    trailing_sl: float
    volume: float               # lot
    strategy: str               # "trend_follow", "mean_reversion", "breakout"
    regime_at_entry: str


# ═════════════════════════════════════════════════════════════════════
#  VARSAYILAN KONFİGÜRASYON
# ═════════════════════════════════════════════════════════════════════

DEFAULT_CONFIG: dict = {
    "initial_capital": 100_000,         # TRY
    "tick_size": 0.01,
    "contract_size": CONTRACT_SIZE,     # 100.0
    "risk_per_trade": 0.01,             # %1
    "max_concurrent": MAX_CONCURRENT,   # 5
    "commission_per_lot": 0.50,         # TRY / lot / yön
    "seed": 42,
    "symbol": "F_THYAO",
}


# ═════════════════════════════════════════════════════════════════════
#  ANA BACKTEST MOTORU
# ═════════════════════════════════════════════════════════════════════


class BacktestRunner:
    """Backtest motoru — tarihsel veri üzerinde strateji testi.

    Args:
        data: OHLCV DataFrame (timestamp/time, open, high, low, close,
              volume sütunları).
        config: Konfigürasyon sözlüğü (``DEFAULT_CONFIG`` üzerine yazılır).
    """

    def __init__(self, data: pd.DataFrame, config: dict | None = None):
        cfg = {**DEFAULT_CONFIG, **(config or {})}
        self.data = data.copy().reset_index(drop=True)
        self.config = cfg

        seed = cfg.get("seed", 42)
        self.spread_model = SpreadModel(seed=seed)
        self.slippage_model = SlippageModel(seed=seed)
        self.session_model = SessionModel()

        self.trades: list[dict] = []
        self.equity_curve: list[float] = []
        self.positions: list[BacktestPosition] = []

        # İndikatörleri tüm veri seti üzerinde bir kez hesapla
        self._precompute_indicators()

    # ── İndikatör ön-hesaplama ──────────────────────────────────────

    def _precompute_indicators(self) -> None:
        """Tüm teknik indikatörleri tam veri seti üzerinde hesapla."""
        c = self.data["close"].values.astype(np.float64)
        h = self.data["high"].values.astype(np.float64)
        l_ = self.data["low"].values.astype(np.float64)
        v = self.data["volume"].values.astype(np.float64)

        self._close = c
        self._high = h
        self._low = l_
        self._volume = v

        # Trend Follow indikatörleri
        self._ema_fast = ema(c, TF_EMA_FAST)
        self._ema_slow = ema(c, TF_EMA_SLOW)
        self._adx = calc_adx(h, l_, c, ATR_PERIOD)
        self._atr = calc_atr(h, l_, c, ATR_PERIOD)
        _, _, self._macd_hist = calc_macd(c)

        # Mean Reversion indikatörleri
        self._rsi = calc_rsi(c, MR_RSI_PERIOD)
        self._bb_upper, self._bb_middle, self._bb_lower = bollinger_bands(
            c, MR_BB_PERIOD, MR_BB_STD,
        )

    # ── Rejim tespiti ───────────────────────────────────────────────

    def _detect_regime(self, i: int) -> RegimeType:
        """Bar *i*'deki indikatör değerlerinden basit rejim tespiti.

        baba.py ile aynı eşikler:
            VOLATILE: ATR > ort(ATR) × 2.0
            TREND:    ADX > 25
            RANGE:    ADX < 20
        """
        if i < ATR_PERIOD * 3:
            return RegimeType.RANGE  # Yeterli veri yok

        adx_val = self._adx[i]
        atr_val = self._atr[i]

        if np.isnan(adx_val) or np.isnan(atr_val):
            return RegimeType.RANGE

        # ATR oranı: mevcut / son N barın ortalaması
        lookback = min(100, i)
        atr_slice = self._atr[max(0, i - lookback) : i + 1]
        atr_valid = atr_slice[~np.isnan(atr_slice)]
        atr_mean = float(np.mean(atr_valid)) if len(atr_valid) > 0 else atr_val

        if atr_mean > 0 and atr_val / atr_mean > 2.0:
            return RegimeType.VOLATILE

        if adx_val > 25.0:
            return RegimeType.TREND
        elif adx_val < 20.0:
            return RegimeType.RANGE

        return RegimeType.RANGE  # 20-25 belirsiz bölge

    # ── Sinyal kontrolleri ──────────────────────────────────────────

    def _check_trend_follow(self, i: int) -> dict | None:
        """Bar *i*'de trend follow sinyali kontrol et.

        ogul.py ``_check_trend_follow`` mantığının aynısı, ön-hesaplanmış
        diziler kullanılarak.
        """
        if i < TF_EMA_SLOW + TF_MACD_CONFIRM_BARS:
            return None

        ema_f = self._ema_fast[i]
        ema_s = self._ema_slow[i]
        adx_val = self._adx[i]
        atr_val = self._atr[i]

        if any(np.isnan(v) for v in [ema_f, ema_s, adx_val, atr_val]):
            return None
        if atr_val <= 0 or adx_val <= TF_ADX_THRESHOLD:
            return None

        # MACD histogram son N bar
        hist_vals: list[float] = []
        for j in range(i, max(i - TF_MACD_CONFIRM_BARS, -1), -1):
            if not np.isnan(self._macd_hist[j]):
                hist_vals.insert(0, self._macd_hist[j])
        if len(hist_vals) < TF_MACD_CONFIRM_BARS:
            return None
        hist_vals = hist_vals[-TF_MACD_CONFIRM_BARS:]

        direction: str | None = None
        if ema_f > ema_s and all(h > 0 for h in hist_vals):
            direction = "BUY"
        elif ema_f < ema_s and all(h < 0 for h in hist_vals):
            direction = "SELL"

        if direction is None:
            return None

        price = float(self._close[i])
        if direction == "BUY":
            sl = price - TF_SL_ATR_MULT * atr_val
            tp = price + TF_TP_ATR_MULT * atr_val
        else:
            sl = price + TF_SL_ATR_MULT * atr_val
            tp = price - TF_TP_ATR_MULT * atr_val

        return {
            "direction": direction,
            "price": price,
            "sl": sl,
            "tp": tp,
            "strategy": "trend_follow",
            "atr": float(atr_val),
        }

    def _check_mean_reversion(self, i: int) -> dict | None:
        """Bar *i*'de mean reversion sinyali kontrol et."""
        if i < MR_BB_PERIOD + MR_RSI_PERIOD:
            return None

        rsi_val = self._rsi[i]
        bb_up = self._bb_upper[i]
        bb_mid = self._bb_middle[i]
        bb_low = self._bb_lower[i]
        adx_val = self._adx[i]
        atr_val = self._atr[i]

        if any(
            np.isnan(v)
            for v in [rsi_val, bb_up, bb_mid, bb_low, adx_val, atr_val]
        ):
            return None
        if atr_val <= 0 or adx_val >= MR_ADX_THRESHOLD:
            return None

        close = float(self._close[i])
        direction: str | None = None

        if rsi_val < MR_RSI_OVERSOLD and close <= bb_low:
            direction = "BUY"
        elif rsi_val > MR_RSI_OVERBOUGHT and close >= bb_up:
            direction = "SELL"

        if direction is None:
            return None

        if direction == "BUY":
            sl = bb_low - MR_SL_ATR_MULT * atr_val
            tp = bb_mid
        else:
            sl = bb_up + MR_SL_ATR_MULT * atr_val
            tp = bb_mid

        return {
            "direction": direction,
            "price": close,
            "sl": float(sl),
            "tp": float(tp),
            "strategy": "mean_reversion",
            "atr": float(atr_val),
        }

    def _check_breakout(self, i: int) -> dict | None:
        """Bar *i*'de breakout sinyali kontrol et."""
        if i < BO_LOOKBACK + 2:
            return None

        atr_val = self._atr[i]
        if np.isnan(atr_val) or atr_val <= 0:
            return None

        # 20-bar yüksek/düşük (mevcut bar hariç)
        h_slice = self._high[i - BO_LOOKBACK : i]
        l_slice = self._low[i - BO_LOOKBACK : i]
        v_slice = self._volume[i - BO_LOOKBACK : i]

        high_20 = float(np.nanmax(h_slice))
        low_20 = float(np.nanmin(l_slice))

        # Hacim filtresi
        vol_avg = float(np.nanmean(v_slice))
        curr_vol = self._volume[i]
        if vol_avg <= 0 or curr_vol <= vol_avg * BO_VOLUME_MULT:
            return None

        # ATR genişleme
        atr_slice = self._atr[max(0, i - BO_LOOKBACK) : i]
        atr_valid = atr_slice[~np.isnan(atr_slice)]
        atr_mean = float(np.mean(atr_valid)) if len(atr_valid) > 0 else atr_val
        if atr_mean <= 0 or atr_val <= atr_mean * BO_ATR_EXPANSION:
            return None

        close = float(self._close[i])
        direction: str | None = None
        if close > high_20:
            direction = "BUY"
        elif close < low_20:
            direction = "SELL"

        if direction is None:
            return None

        range_width = high_20 - low_20
        range_mid = (high_20 + low_20) / 2.0
        sl = range_mid
        tp = close + range_width if direction == "BUY" else close - range_width

        return {
            "direction": direction,
            "price": close,
            "sl": sl,
            "tp": tp,
            "strategy": "breakout",
            "atr": float(atr_val),
        }

    def _generate_signals(self, i: int, regime: RegimeType) -> list[dict]:
        """Bar *i*'de verilen rejim için tüm geçerli sinyalleri üret."""
        strategies = REGIME_STRATEGIES.get(regime, [])
        if not strategies:
            return []

        signals: list[dict] = []
        for strat in strategies:
            sig = None
            if strat == StrategyType.TREND_FOLLOW:
                sig = self._check_trend_follow(i)
            elif strat == StrategyType.MEAN_REVERSION:
                sig = self._check_mean_reversion(i)
            elif strat == StrategyType.BREAKOUT:
                sig = self._check_breakout(i)
            if sig:
                signals.append(sig)
        return signals

    # ── Pozisyon boyutlandırma ──────────────────────────────────────

    def _calculate_lot(
        self,
        atr_val: float,
        equity: float,
        regime: RegimeType,
    ) -> float:
        """Sabit-kesirli pozisyon boyutlandırma + rejim çarpanı."""
        risk_pct = self.config.get("risk_per_trade", 0.01)
        mult = RISK_MULTIPLIERS.get(regime, 1.0)
        if mult == 0 or atr_val <= 0 or equity <= 0:
            return 0.0

        contract_size = self.config.get("contract_size", CONTRACT_SIZE)
        lot = (equity * risk_pct * mult) / (atr_val * contract_size)
        return max(0.0, min(lot, 1.0))  # MAX_LOT_PER_CONTRACT = 1.0

    # ── Spread & slippage uygulama ──────────────────────────────────

    def _apply_spread_and_slippage(
        self,
        price: float,
        direction: str,
        regime: RegimeType,
        is_entry: bool = True,
    ) -> float:
        """Dolum fiyatını hesaplamak için spread ve slippage uygula.

        Giriş BUY:  price + yarı_spread + slippage (daha kötü = yüksek)
        Giriş SELL: price - yarı_spread - slippage (daha kötü = düşük)
        Çıkış BUY:  price - yarı_spread - slippage
        Çıkış SELL: price + yarı_spread + slippage
        """
        is_volatile = regime in (RegimeType.VOLATILE, RegimeType.OLAY)
        tick_size = self.config.get("tick_size", 0.01)

        spread = self.spread_model.get_spread(price, is_volatile=is_volatile)
        half_spread = spread * tick_size / 2.0

        slippage = self.slippage_model.get_slippage(
            is_volatile=is_volatile,
            is_market_order=not is_entry,  # çıkışlar market emri
        )
        slip_amount = slippage * tick_size

        # Olumsuzluk yönünü belirle
        if (direction == "BUY" and is_entry) or (
            direction == "SELL" and not is_entry
        ):
            return price + half_spread + slip_amount
        else:
            return price - half_spread - slip_amount

    # ── SL/TP kontrolü ──────────────────────────────────────────────

    def _check_sl_tp(
        self,
        pos: BacktestPosition,
        bar_high: float,
        bar_low: float,
    ) -> str | None:
        """Bu bar içinde SL veya TP'nin tetiklenip tetiklenmediğini kontrol et.

        Konservatif varsayım: SL önce kontrol edilir.

        Returns:
            ``"sl"``, ``"tp"``, veya ``None``.
        """
        if pos.direction == "BUY":
            if bar_low <= pos.trailing_sl:
                return "sl"
            if bar_high >= pos.tp:
                return "tp"
        else:
            if bar_high >= pos.trailing_sl:
                return "sl"
            if bar_low <= pos.tp:
                return "tp"
        return None

    # ── Trailing stop ───────────────────────────────────────────────

    def _update_trailing_stop(self, pos: BacktestPosition, i: int) -> None:
        """Trend follow pozisyonları için trailing stop güncelle."""
        if pos.strategy != "trend_follow":
            return

        atr_val = self._atr[i]
        if np.isnan(atr_val) or atr_val <= 0:
            return

        current_price = float(self._close[i])

        if pos.direction == "BUY":
            new_sl = current_price - TF_TRAILING_ATR_MULT * atr_val
            if new_sl > pos.trailing_sl:
                pos.trailing_sl = new_sl
        else:
            new_sl = current_price + TF_TRAILING_ATR_MULT * atr_val
            if new_sl < pos.trailing_sl:
                pos.trailing_sl = new_sl

    # ── Pozisyon kapatma ────────────────────────────────────────────

    def _close_position(
        self,
        pos: BacktestPosition,
        exit_price: float,
        exit_time: datetime,
        exit_reason: str,
    ) -> dict:
        """Pozisyonu kapat ve işlem kaydı oluştur."""
        contract_size = self.config.get("contract_size", CONTRACT_SIZE)
        commission = (
            self.config.get("commission_per_lot", 0.50) * pos.volume * 2
        )  # giriş + çıkış

        if pos.direction == "BUY":
            raw_pnl = (exit_price - pos.entry_price) * pos.volume * contract_size
        else:
            raw_pnl = (pos.entry_price - exit_price) * pos.volume * contract_size

        net_pnl = raw_pnl - commission

        trade = {
            "symbol": pos.symbol,
            "direction": pos.direction,
            "strategy": pos.strategy,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "entry_time": (
                pos.entry_time.isoformat()
                if isinstance(pos.entry_time, datetime)
                else str(pos.entry_time)
            ),
            "exit_time": (
                exit_time.isoformat()
                if isinstance(exit_time, datetime)
                else str(exit_time)
            ),
            "volume": pos.volume,
            "pnl": net_pnl,
            "raw_pnl": raw_pnl,
            "commission": commission,
            "exit_reason": exit_reason,
            "regime": pos.regime_at_entry,
            "sl": pos.sl,
            "tp": pos.tp,
        }
        return trade

    # ── ANA BACKTEST DÖNGÜSÜ ────────────────────────────────────────

    def run(self) -> BacktestReport:
        """Tam bar-bar backtest simülasyonunu çalıştır.

        Returns:
            ``BacktestReport`` — işlemler, equity curve, başlangıç sermayesi.
        """
        logger.info("Backtest baslatiliyor...")
        initial_capital = self.config.get("initial_capital", 100_000)
        equity = initial_capital
        max_concurrent = self.config.get("max_concurrent", MAX_CONCURRENT)
        tick_size = self.config.get("tick_size", 0.01)
        symbol = self.config.get("symbol", "F_THYAO")

        self.positions = []
        self.trades = []
        self.equity_curve = []

        # Zaman damgası sütun adı
        ts_col = "timestamp" if "timestamp" in self.data.columns else "time"

        for i in range(len(self.data)):
            bar = self.data.iloc[i]
            bar_time = pd.Timestamp(bar[ts_col])
            bar_open = float(bar["open"])
            bar_high = float(bar["high"])
            bar_low = float(bar["low"])
            bar_close = float(bar["close"])

            # ── 1. Seans boşluk kontrolü ────────────────────────────
            if i > 0:
                prev_bar = self.data.iloc[i - 1]
                prev_time = pd.Timestamp(prev_bar[ts_col])
                prev_close = float(prev_bar["close"])

                gap = self.session_model.detect_gap(
                    prev_close, bar_open, prev_time, bar_time,
                )

                if gap is not None:
                    # Her açık pozisyon için gap SL kontrol et
                    for pos in list(self.positions):
                        sl_result = self.session_model.check_gap_sl(
                            gap, pos.direction, pos.trailing_sl, tick_size,
                        )
                        if sl_result:
                            trade = self._close_position(
                                pos,
                                sl_result["fill_price"],
                                bar_time,
                                f"gap_sl_{gap.gap_type}",
                            )
                            self.trades.append(trade)
                            equity += trade["pnl"]
                            self.positions.remove(pos)

            # ── 2. SL/TP kontrolü ───────────────────────────────────
            regime = self._detect_regime(i)

            for pos in list(self.positions):
                hit = self._check_sl_tp(pos, bar_high, bar_low)
                if hit:
                    if hit == "sl":
                        exit_price = pos.trailing_sl
                    else:
                        exit_price = pos.tp

                    # Çıkış slippage uygula
                    exit_price_adj = self._apply_spread_and_slippage(
                        exit_price, pos.direction, regime, is_entry=False,
                    )

                    trade = self._close_position(
                        pos, exit_price_adj, bar_time, hit,
                    )
                    self.trades.append(trade)
                    equity += trade["pnl"]
                    self.positions.remove(pos)

            # ── 3. Trailing stop güncelle ───────────────────────────
            for pos in self.positions:
                self._update_trailing_stop(pos, i)

            # ── 4. Sinyal üret ve yürüt ─────────────────────────────
            if len(self.positions) < max_concurrent:
                signals = self._generate_signals(i, regime)

                for sig in signals:
                    if len(self.positions) >= max_concurrent:
                        break

                    # Aynı sembol tekrar yok
                    if any(p.symbol == symbol for p in self.positions):
                        continue

                    atr_val = sig.get("atr", float(self._atr[i]))
                    lot = self._calculate_lot(atr_val, equity, regime)
                    if lot <= 0:
                        continue

                    entry_price = self._apply_spread_and_slippage(
                        sig["price"], sig["direction"], regime, is_entry=True,
                    )

                    pos = BacktestPosition(
                        symbol=symbol,
                        direction=sig["direction"],
                        entry_price=entry_price,
                        entry_time=bar_time,
                        sl=sig["sl"],
                        tp=sig["tp"],
                        trailing_sl=sig["sl"],
                        volume=lot,
                        strategy=sig["strategy"],
                        regime_at_entry=regime.value,
                    )
                    self.positions.append(pos)

            # ── 5. Equity kaydet (mark-to-market) ───────────────────
            floating = 0.0
            contract_size = self.config.get("contract_size", CONTRACT_SIZE)
            for pos in self.positions:
                if pos.direction == "BUY":
                    floating += (
                        (bar_close - pos.entry_price)
                        * pos.volume
                        * contract_size
                    )
                else:
                    floating += (
                        (pos.entry_price - bar_close)
                        * pos.volume
                        * contract_size
                    )

            self.equity_curve.append(equity + floating)

        # ── Kalan açık pozisyonları son barda kapat ─────────────────
        if self.positions:
            last_bar = self.data.iloc[-1]
            last_time = pd.Timestamp(last_bar[ts_col])
            for pos in list(self.positions):
                trade = self._close_position(
                    pos,
                    float(last_bar["close"]),
                    last_time,
                    "backtest_end",
                )
                self.trades.append(trade)
                equity += trade["pnl"]
                self.positions.remove(pos)

        logger.info(f"Backtest tamamlandi. {len(self.trades)} islem.")
        return BacktestReport(
            trades=self.trades,
            equity_curve=self.equity_curve,
            initial_capital=initial_capital,
        )
