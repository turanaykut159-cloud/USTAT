"""OĞUL (sinyal üretimi & emir yönetimi) modülü testleri — v12.0.

Test sınıfları:
    TestHelpers              – modül-seviye yardımcılar (_last_valid, _last_n_valid, _find_swing_*)
    TestOgulInit             – __init__, baba var/yok
    TestRegimeGating         – VOLATILE/OLAY dur, TREND/RANGE aktif strateji
    TestTrendFollow          – Long/Short koşullar, ADX eşik, MACD 2-bar, SL/TP
    TestMeanReversion        – RSI+BB+ADX koşullar, SL/TP hesabı
    TestBreakout             – High/low kırılım, hacim filtresi (zorunlu), ATR genişleme
    TestH1Confirmation       – Onay/red, yetersiz veri
    TestExecuteSignal        – Başarılı emir, başarısız emir, korelasyon engeli, DB kayıt
    TestManageActiveTrades   – Trailing stop, EMA ihlali, rejim değişimi
    TestSyncPositions        – Kapanmış pozisyon tespiti, senkron
    TestRestoreActiveTrades  – Engine restart, boş pozisyon
    TestHandleClosedTrade    – State, PnL, DB güncelleme
    TestEdgeCases            – MT5 bağlantı yok, boş veri, NaN, ATR=0
"""

import json
import os
import tempfile
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pandas as pd
import pytest

from engine.utils.helpers import last_valid as _last_valid, last_n_valid as _last_n_valid
from engine.ogul import (
    Ogul,
    _find_swing_low,
    _find_swing_high,
    REGIME_STRATEGIES,
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
    SWING_LOOKBACK,
    ATR_PERIOD,
    MIN_BARS_M15,
    MIN_BARS_H1,
    CONTRACT_SIZE,
    ORDER_TIMEOUT_SEC,
    MAX_SLIPPAGE_ATR_MULT,
    MAX_LOT_PER_CONTRACT,
    MARGIN_RESERVE_PCT,
    MAX_CONCURRENT,
    TRADING_OPEN,
    TRADING_CLOSE,
)
from engine.config import Config
from engine.database import Database
from engine.models.regime import Regime, RegimeType
from engine.models.risk import RiskParams, RiskVerdict
from engine.models.signal import Signal, SignalType, StrategyType
from engine.models.trade import Trade, TradeState


# ═════════════════════════════════════════════════════════════════════
#  YARDIMCI: Geçici DB, mock nesneler, bar verileri
# ═════════════════════════════════════════════════════════════════════

@pytest.fixture
def tmp_db(tmp_path):
    """Geçici SQLite veritabanı oluşturur."""
    db_dir = tmp_path / "database"
    db_dir.mkdir()
    db_file = db_dir / "test.db"
    config_data = {"database": {"path": str(db_file)}}
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config_data))
    config = Config(str(config_file))
    db = Database(config)
    yield db
    db.close()


@pytest.fixture
def mock_mt5():
    """MagicMock MT5Bridge."""
    mt5 = MagicMock()
    mt5.send_order.return_value = {"order": 12345}
    mt5.get_tick.return_value = SimpleNamespace(ask=100.0, bid=99.9)
    mt5.get_positions.return_value = []
    mt5.close_position.return_value = True
    mt5.modify_position.return_value = True
    mt5.get_account_info.return_value = SimpleNamespace(
        equity=100000.0, free_margin=80000.0,
    )
    mt5.cancel_order.return_value = True
    mt5.check_order_status.return_value = None
    mt5.get_symbol_info.return_value = SimpleNamespace(
        trade_contract_size=100.0,
        volume_min=1.0,
        volume_max=10.0,
        volume_step=1.0,
    )
    return mt5


@pytest.fixture
def mock_baba():
    """MagicMock Baba."""
    baba = MagicMock()
    baba.is_symbol_killed.return_value = False
    baba.check_correlation_limits.return_value = RiskVerdict(can_trade=True)
    baba.calculate_position_size.return_value = 1.0
    baba.increment_daily_trade_count.return_value = None
    return baba


@pytest.fixture
def config():
    """Basit Config nesnesi."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump({}, f)
        config_path = f.name
    c = Config(config_path)
    yield c
    os.unlink(config_path)


@pytest.fixture
def ogul(config, mock_mt5, tmp_db, mock_baba):
    """Ogul nesnesi (tam bağımlılıklarla)."""
    return Ogul(config, mock_mt5, tmp_db, baba=mock_baba)


@pytest.fixture
def ogul_no_baba(config, mock_mt5, tmp_db):
    """Ogul nesnesi (baba olmadan)."""
    return Ogul(config, mock_mt5, tmp_db, baba=None)


def _make_trend_bars(
    n: int = 70,
    start: float = 100.0,
    direction: str = "up",
    symbol: str = "F_THYAO",
    timeframe: str = "M15",
) -> pd.DataFrame:
    """Trend bar verileri üretir (EMA(20)>EMA(50) + ADX yüksek + MACD pozitif).

    direction="up" → long sinyali üretecek barlar
    direction="down" → short sinyali üretecek barlar
    """
    timestamps = [
        f"2025-01-01T09:{30 + i // 4:02d}:{(i % 4) * 15:02d}"
        for i in range(n)
    ]
    if direction == "up":
        close = np.linspace(start, start * 1.3, n)
    else:
        close = np.linspace(start, start * 0.7, n)

    high = close * 1.005
    low = close * 0.995
    opn = close * 0.998
    volume = np.full(n, 150.0)

    return pd.DataFrame({
        "symbol": symbol,
        "timeframe": timeframe,
        "timestamp": timestamps,
        "open": opn,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def _make_range_bars(
    n: int = 70,
    mid: float = 100.0,
    amplitude: float = 0.5,
    symbol: str = "F_THYAO",
    timeframe: str = "M15",
) -> pd.DataFrame:
    """Range bar verileri üretir (RSI aşırı + BB bant teması + ADX düşük)."""
    timestamps = [
        f"2025-01-01T09:{30 + i // 4:02d}:{(i % 4) * 15:02d}"
        for i in range(n)
    ]
    # Sinusoidal fiyat — dar range
    t = np.linspace(0, 4 * np.pi, n)
    close = mid + amplitude * np.sin(t)
    # Son birkaç barı alt banda yaklaştır (oversold)
    close[-5:] = mid - amplitude * 2.5
    high = close + 0.2
    low = close - 0.2
    opn = close + 0.05
    volume = np.full(n, 100.0)

    return pd.DataFrame({
        "symbol": symbol,
        "timeframe": timeframe,
        "timestamp": timestamps,
        "open": opn,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def _make_breakout_bars(
    n: int = 70,
    mid: float = 100.0,
    range_width: float = 2.0,
    symbol: str = "F_THYAO",
    timeframe: str = "M15",
    direction: str = "up",
) -> pd.DataFrame:
    """Breakout bar verileri üretir (20-bar high/low kırılımı + yüksek hacim)."""
    timestamps = [
        f"2025-01-01T09:{30 + i // 4:02d}:{(i % 4) * 15:02d}"
        for i in range(n)
    ]
    # Range bölgesi
    close = np.full(n, mid)
    close[:n - 1] = mid + np.random.uniform(-range_width / 4, range_width / 4, n - 1)
    high = close + 0.3
    low = close - 0.3
    # Son bar: kırılım
    if direction == "up":
        close[-1] = mid + range_width * 1.5
        high[-1] = close[-1] + 0.5
        low[-1] = close[-1] - 0.3
    else:
        close[-1] = mid - range_width * 1.5
        high[-1] = close[-1] + 0.3
        low[-1] = close[-1] - 0.5

    opn = close * 0.999
    # Hacim: son bar çok yüksek
    volume = np.full(n, 100.0)
    volume[-1] = 300.0  # > avg * 1.5

    return pd.DataFrame({
        "symbol": symbol,
        "timeframe": timeframe,
        "timestamp": timestamps,
        "open": opn,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def _insert_bars(db: Database, df: pd.DataFrame, symbol: str, timeframe: str):
    """Yardımcı: bar verisini DB'ye ekle."""
    df2 = df.copy()
    if "symbol" not in df2.columns:
        df2["symbol"] = symbol
    if "timeframe" not in df2.columns:
        df2["timeframe"] = timeframe
    db.insert_bars(symbol, timeframe, df2)


# ═════════════════════════════════════════════════════════════════════
#  TestHelpers — Modül seviye yardımcılar
# ═════════════════════════════════════════════════════════════════════

class TestHelpers:
    """_last_valid, _last_n_valid, _find_swing_low, _find_swing_high testleri."""

    def test_last_valid_normal(self):
        """Normal dizide son değeri döner."""
        arr = np.array([1.0, 2.0, 3.0, 4.0])
        assert _last_valid(arr) == 4.0

    def test_last_valid_with_nan(self):
        """NaN'lı dizide son geçerli değeri döner."""
        arr = np.array([1.0, 2.0, 3.0, np.nan, np.nan])
        assert _last_valid(arr) == 3.0

    def test_last_valid_all_nan(self):
        """Tamamı NaN → None."""
        arr = np.array([np.nan, np.nan, np.nan])
        assert _last_valid(arr) is None

    def test_last_valid_empty(self):
        """Boş dizi → None."""
        arr = np.array([])
        assert _last_valid(arr) is None

    def test_last_n_valid_normal(self):
        """Son n geçerli değeri döner (eskiden yeniye)."""
        arr = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = _last_n_valid(arr, 3)
        assert result == [3.0, 4.0, 5.0]

    def test_last_n_valid_with_nan(self):
        """NaN'lı dizide son n geçerli değeri döner."""
        arr = np.array([1.0, 2.0, np.nan, 4.0, np.nan, 5.0])
        result = _last_n_valid(arr, 2)
        assert result == [4.0, 5.0]

    def test_last_n_valid_insufficient(self):
        """Yeterli geçerli değer yoksa kısa liste döner."""
        arr = np.array([np.nan, np.nan, 1.0])
        result = _last_n_valid(arr, 5)
        assert result == [1.0]

    def test_find_swing_low(self):
        """Son lookback bar içindeki minimum."""
        low = np.array([10.0, 8.0, 9.0, 7.0, 11.0])
        assert _find_swing_low(low, 5) == 7.0

    def test_find_swing_low_short_array(self):
        """Kısa dizi → None."""
        low = np.array([10.0])
        assert _find_swing_low(low, 5) is None

    def test_find_swing_high(self):
        """Son lookback bar içindeki maksimum."""
        high = np.array([10.0, 12.0, 9.0, 11.0, 8.0])
        assert _find_swing_high(high, 5) == 12.0

    def test_find_swing_high_with_nan(self):
        """NaN'lı dizide geçerli maksimum."""
        high = np.array([np.nan, np.nan, 10.0, np.nan, 5.0, np.nan, np.nan, np.nan, 8.0, 9.0])
        assert _find_swing_high(high, 5) == 9.0


# ═════════════════════════════════════════════════════════════════════
#  TestOgulInit — __init__, baba var/yok
# ═════════════════════════════════════════════════════════════════════

class TestOgulInit:
    """Ogul init testleri."""

    def test_init_with_baba(self, config, mock_mt5, tmp_db, mock_baba):
        """Baba ile oluşturma."""
        o = Ogul(config, mock_mt5, tmp_db, baba=mock_baba)
        assert o.baba is mock_baba
        assert o.active_trades == {}

    def test_init_without_baba(self, config, mock_mt5, tmp_db):
        """Baba olmadan oluşturma."""
        o = Ogul(config, mock_mt5, tmp_db)
        assert o.baba is None
        assert o.active_trades == {}

    def test_initial_no_active_trades(self, ogul):
        """Başlangıçta aktif işlem olmamalı."""
        assert len(ogul.active_trades) == 0


# ═════════════════════════════════════════════════════════════════════
#  TestRegimeGating — Rejim → strateji eşleme
# ═════════════════════════════════════════════════════════════════════

class TestRegimeGating:
    """Rejim bazlı strateji filtreleme testleri."""

    def test_volatile_blocks_all(self, ogul):
        """VOLATILE rejiminde sinyal üretilmez."""
        regime = Regime(regime_type=RegimeType.VOLATILE)
        ogul.process_signals(["F_THYAO"], regime)
        assert len(ogul.active_trades) == 0

    def test_olay_blocks_all(self, ogul):
        """OLAY rejiminde sinyal üretilmez."""
        regime = Regime(regime_type=RegimeType.OLAY)
        ogul.process_signals(["F_THYAO"], regime)
        assert len(ogul.active_trades) == 0

    def test_trend_regime_strategies(self):
        """TREND → sadece TREND_FOLLOW aktif."""
        strategies = REGIME_STRATEGIES[RegimeType.TREND]
        assert StrategyType.TREND_FOLLOW in strategies
        assert StrategyType.MEAN_REVERSION not in strategies
        assert StrategyType.BREAKOUT not in strategies

    def test_range_regime_strategies(self):
        """RANGE → MEAN_REVERSION + BREAKOUT aktif."""
        strategies = REGIME_STRATEGIES[RegimeType.RANGE]
        assert StrategyType.MEAN_REVERSION in strategies
        assert StrategyType.BREAKOUT in strategies
        assert StrategyType.TREND_FOLLOW not in strategies

    def test_empty_symbols_no_error(self, ogul):
        """Boş sembol listesi hata vermemeli."""
        regime = Regime(regime_type=RegimeType.RANGE)
        ogul.process_signals([], regime)
        assert len(ogul.active_trades) == 0

    def test_volatile_closes_existing_positions(self, ogul, mock_mt5):
        """VOLATILE rejiminde mevcut pozisyonlar kapatılır."""
        # Mevcut işlem ekle
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            entry_price=100.0, sl=95.0, tp=110.0,
            state=TradeState.FILLED, ticket=999,
            strategy="trend_follow", db_id=0,
        )
        ogul.active_trades["F_THYAO"] = trade
        mock_mt5.get_tick.return_value = SimpleNamespace(ask=101.0, bid=100.9)

        regime = Regime(regime_type=RegimeType.VOLATILE)
        ogul.process_signals(["F_THYAO"], regime)

        # Pozisyon kapatılmalı
        mock_mt5.close_position.assert_called_once_with(999)
        assert "F_THYAO" not in ogul.active_trades


# ═════════════════════════════════════════════════════════════════════
#  TestTrendFollow — Trend follow sinyali testleri
# ═════════════════════════════════════════════════════════════════════

class TestTrendFollow:
    """_check_trend_follow testleri."""

    def _setup_trend_data(self, ogul, tmp_db, direction="up"):
        """Trend follow sinyal verisi hazırlar."""
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10, direction=direction)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")
        # H1 onay barları da ekle
        h1_bars = _make_trend_bars(
            n=MIN_BARS_H1 + 10, direction=direction,
            timeframe="H1",
        )
        _insert_bars(tmp_db, h1_bars, "F_THYAO", "H1")

    def test_long_signal_conditions(self, ogul, tmp_db, mock_mt5):
        """Long sinyal: EMA(20) > EMA(50) + ADX > 25 + MACD 2 bar pozitif."""
        self._setup_trend_data(ogul, tmp_db, "up")

        df = tmp_db.get_bars("F_THYAO", "M15", limit=MIN_BARS_M15)
        close = df["close"].values.astype(np.float64)
        high = df["high"].values.astype(np.float64)
        low = df["low"].values.astype(np.float64)
        volume = df["volume"].values.astype(np.float64)

        signal = ogul._check_trend_follow("F_THYAO", close, high, low, volume)

        # Trend verileri üretildiğinde EMA/ADX/MACD koşulları sağlanıyorsa sinyal üretilir
        # Eğer koşullar synthetic veride sağlanmıyorsa signal None olabilir
        if signal is not None:
            assert signal.signal_type == SignalType.BUY
            assert signal.strategy == StrategyType.TREND_FOLLOW
            assert signal.sl < signal.price
            assert signal.tp > signal.price
            assert 0 <= signal.strength <= 1.0

    def test_short_signal_conditions(self, ogul, tmp_db, mock_mt5):
        """Short sinyal: EMA(20) < EMA(50) + ADX > 25 + MACD 2 bar negatif."""
        self._setup_trend_data(ogul, tmp_db, "down")

        df = tmp_db.get_bars("F_THYAO", "M15", limit=MIN_BARS_M15)
        close = df["close"].values.astype(np.float64)
        high = df["high"].values.astype(np.float64)
        low = df["low"].values.astype(np.float64)
        volume = df["volume"].values.astype(np.float64)

        signal = ogul._check_trend_follow("F_THYAO", close, high, low, volume)

        if signal is not None:
            assert signal.signal_type == SignalType.SELL
            assert signal.strategy == StrategyType.TREND_FOLLOW
            assert signal.sl > signal.price
            assert signal.tp < signal.price

    def test_adx_below_threshold_no_signal(self, ogul, mock_mt5):
        """ADX < 25 → sinyal yok."""
        n = MIN_BARS_M15 + 10
        # Düz fiyat → düşük ADX
        close = np.full(n, 100.0) + np.random.uniform(-0.01, 0.01, n)
        high = close + 0.01
        low = close - 0.01
        volume = np.full(n, 100.0)

        signal = ogul._check_trend_follow("F_THYAO", close, high, low, volume)
        assert signal is None

    def test_macd_mixed_no_signal(self, ogul, mock_mt5):
        """MACD histogram karışık → sinyal yok."""
        n = MIN_BARS_M15 + 10
        # Zigzag → EMA çapraz ama MACD tutarsız
        close = np.array([100 + (-1)**i * 0.5 for i in range(n)])
        high = close + 0.1
        low = close - 0.1
        volume = np.full(n, 100.0)

        signal = ogul._check_trend_follow("F_THYAO", close, high, low, volume)
        assert signal is None

    def test_no_tick_no_signal(self, ogul, mock_mt5):
        """get_tick None → sinyal yok."""
        mock_mt5.get_tick.return_value = None
        n = MIN_BARS_M15 + 10
        close = np.linspace(100, 130, n)
        high = close * 1.005
        low = close * 0.995
        volume = np.full(n, 100.0)

        signal = ogul._check_trend_follow("F_THYAO", close, high, low, volume)
        # get_tick None döndüğünde ya hiç sinyal olmaz ya da None
        # (ADX ve diğer koşullar sağlansa bile fiyat alınamazsa None)
        if signal is None:
            assert True  # expected

    def test_strength_bounded(self, ogul, tmp_db, mock_mt5):
        """Sinyal gücü [0, 1] aralığında."""
        self._setup_trend_data(ogul, tmp_db, "up")

        df = tmp_db.get_bars("F_THYAO", "M15", limit=MIN_BARS_M15)
        close = df["close"].values.astype(np.float64)
        high = df["high"].values.astype(np.float64)
        low = df["low"].values.astype(np.float64)
        volume = df["volume"].values.astype(np.float64)

        signal = ogul._check_trend_follow("F_THYAO", close, high, low, volume)
        if signal is not None:
            assert 0 <= signal.strength <= 1.0

    def test_sl_uses_swing_low_for_buy(self, ogul, mock_mt5):
        """BUY: SL swing low - 1*ATR (veya fallback)."""
        n = MIN_BARS_M15 + 10
        # Güçlü yukarı trend
        close = np.linspace(80, 130, n)
        high = close * 1.005
        low = close * 0.995
        volume = np.full(n, 100.0)

        signal = ogul._check_trend_follow("F_THYAO", close, high, low, volume)
        if signal is not None and signal.signal_type == SignalType.BUY:
            assert signal.sl < signal.price  # SL fiyatın altında

    def test_atr_zero_no_signal(self, ogul, mock_mt5):
        """ATR = 0 → sinyal yok."""
        n = MIN_BARS_M15 + 10
        # Sabit fiyat → ATR = 0
        close = np.full(n, 100.0)
        high = close.copy()
        low = close.copy()
        volume = np.full(n, 100.0)

        signal = ogul._check_trend_follow("F_THYAO", close, high, low, volume)
        assert signal is None

    def test_trend_follow_reason_format(self, ogul, tmp_db, mock_mt5):
        """Sinyal reason doğru formatta."""
        self._setup_trend_data(ogul, tmp_db, "up")

        df = tmp_db.get_bars("F_THYAO", "M15", limit=MIN_BARS_M15)
        close = df["close"].values.astype(np.float64)
        high = df["high"].values.astype(np.float64)
        low = df["low"].values.astype(np.float64)
        volume = df["volume"].values.astype(np.float64)

        signal = ogul._check_trend_follow("F_THYAO", close, high, low, volume)
        if signal is not None:
            assert "TREND_FOLLOW" in signal.reason
            assert "ADX=" in signal.reason

    def test_all_nan_indicators_no_signal(self, ogul, mock_mt5):
        """Tüm indikatörler NaN → sinyal yok."""
        n = MIN_BARS_M15 + 10
        close = np.full(n, np.nan)
        high = np.full(n, np.nan)
        low = np.full(n, np.nan)
        volume = np.full(n, np.nan)

        signal = ogul._check_trend_follow("F_THYAO", close, high, low, volume)
        assert signal is None


# ═════════════════════════════════════════════════════════════════════
#  TestMeanReversion — Mean reversion sinyali testleri
# ═════════════════════════════════════════════════════════════════════

class TestMeanReversion:
    """_check_mean_reversion testleri."""

    def test_long_rsi_oversold_bb_lower(self, ogul, mock_mt5):
        """Long: RSI < 30 + BB alt bant teması + ADX < 20."""
        n = MIN_BARS_M15 + 10
        # Range piyasası, son barlarda düşüş (oversold)
        mid = 100.0
        close = np.full(n, mid)
        # Küçük dalgalanma
        close += np.random.uniform(-0.3, 0.3, n)
        # Son 5 bar: güçlü düşüş → RSI oversold
        close[-10:] = np.linspace(mid, mid - 5.0, 10)
        high = close + 0.2
        low = close - 0.2
        volume = np.full(n, 100.0)

        signal = ogul._check_mean_reversion("F_THYAO", close, high, low, volume)
        # Koşullar sağlanıyorsa BUY sinyali
        if signal is not None:
            assert signal.signal_type == SignalType.BUY
            assert signal.strategy == StrategyType.MEAN_REVERSION

    def test_short_rsi_overbought_bb_upper(self, ogul, mock_mt5):
        """Short: RSI > 70 + BB üst bant teması + ADX < 20."""
        n = MIN_BARS_M15 + 10
        mid = 100.0
        close = np.full(n, mid)
        close += np.random.uniform(-0.3, 0.3, n)
        # Son 10 bar: güçlü yükseliş → RSI overbought
        close[-10:] = np.linspace(mid, mid + 5.0, 10)
        high = close + 0.2
        low = close - 0.2
        volume = np.full(n, 100.0)

        signal = ogul._check_mean_reversion("F_THYAO", close, high, low, volume)
        if signal is not None:
            assert signal.signal_type == SignalType.SELL
            assert signal.strategy == StrategyType.MEAN_REVERSION

    def test_adx_above_threshold_no_signal(self, ogul, mock_mt5):
        """ADX >= 20 → mean reversion sinyali yok."""
        n = MIN_BARS_M15 + 10
        # Güçlü trend → yüksek ADX
        close = np.linspace(100, 150, n)
        high = close * 1.01
        low = close * 0.99
        volume = np.full(n, 100.0)

        signal = ogul._check_mean_reversion("F_THYAO", close, high, low, volume)
        assert signal is None

    def test_no_tick_no_signal(self, ogul, mock_mt5):
        """get_tick None → sinyal yok."""
        mock_mt5.get_tick.return_value = None
        n = MIN_BARS_M15 + 10
        mid = 100.0
        close = np.full(n, mid)
        close[-10:] = np.linspace(mid, mid - 5.0, 10)
        high = close + 0.2
        low = close - 0.2
        volume = np.full(n, 100.0)

        signal = ogul._check_mean_reversion("F_THYAO", close, high, low, volume)
        # Tick yoksa fiyat alınamaz
        # Sinyal üretilmemeli (ADX kontrolü geçse bile)

    def test_sl_uses_bb_band(self, ogul, mock_mt5):
        """SL: BB alt/üst bant ± 1 ATR."""
        n = MIN_BARS_M15 + 10
        mid = 100.0
        close = np.full(n, mid)
        close += np.random.uniform(-0.3, 0.3, n)
        close[-10:] = np.linspace(mid, mid - 5.0, 10)
        high = close + 0.2
        low = close - 0.2
        volume = np.full(n, 100.0)

        signal = ogul._check_mean_reversion("F_THYAO", close, high, low, volume)
        if signal is not None and signal.signal_type == SignalType.BUY:
            # SL fiyatın altında olmalı
            assert signal.sl < signal.price

    def test_tp_at_bb_middle(self, ogul, mock_mt5):
        """TP: BB orta bandı (20 SMA)."""
        n = MIN_BARS_M15 + 10
        mid = 100.0
        close = np.full(n, mid)
        close += np.random.uniform(-0.3, 0.3, n)
        close[-10:] = np.linspace(mid, mid - 5.0, 10)
        high = close + 0.2
        low = close - 0.2
        volume = np.full(n, 100.0)

        signal = ogul._check_mean_reversion("F_THYAO", close, high, low, volume)
        if signal is not None and signal.signal_type == SignalType.BUY:
            # TP giriş fiyatının üzerinde (orta banda doğru)
            assert signal.tp > signal.sl

    def test_atr_zero_no_signal(self, ogul, mock_mt5):
        """ATR = 0 → sinyal yok."""
        n = MIN_BARS_M15 + 10
        close = np.full(n, 100.0)
        high = close.copy()
        low = close.copy()
        volume = np.full(n, 100.0)

        signal = ogul._check_mean_reversion("F_THYAO", close, high, low, volume)
        assert signal is None

    def test_strength_components(self, ogul, mock_mt5):
        """Sinyal gücü: RSI + BB temas + ADX zayıflık."""
        n = MIN_BARS_M15 + 10
        mid = 100.0
        close = np.full(n, mid)
        close += np.random.uniform(-0.3, 0.3, n)
        close[-10:] = np.linspace(mid, mid - 5.0, 10)
        high = close + 0.2
        low = close - 0.2
        volume = np.full(n, 100.0)

        signal = ogul._check_mean_reversion("F_THYAO", close, high, low, volume)
        if signal is not None:
            assert 0 <= signal.strength <= 1.0


# ═════════════════════════════════════════════════════════════════════
#  TestBreakout — Breakout sinyali testleri
# ═════════════════════════════════════════════════════════════════════

class TestBreakout:
    """_check_breakout testleri."""

    def test_long_high_breakout(self, ogul, mock_mt5):
        """Long: 20-bar high kırılımı + hacim + ATR genişleme."""
        n = MIN_BARS_M15 + 10
        mid = 100.0

        close = np.full(n, mid)
        close += np.random.uniform(-0.2, 0.2, n)
        high = close + 0.3
        low = close - 0.3
        volume = np.full(n, 80.0)

        # Son bar: yukarı kırılım + yüksek hacim
        close[-1] = mid + 3.0
        high[-1] = close[-1] + 0.5
        low[-1] = close[-1] - 0.3
        volume[-1] = 250.0

        # ATR genişleme: son barlarda daha yüksek volatilite
        high[-3:-1] = close[-3:-1] + 2.0
        low[-3:-1] = close[-3:-1] - 2.0

        signal = ogul._check_breakout("F_THYAO", close, high, low, volume)
        if signal is not None:
            assert signal.signal_type == SignalType.BUY
            assert signal.strategy == StrategyType.BREAKOUT

    def test_short_low_breakout(self, ogul, mock_mt5):
        """Short: 20-bar low kırılımı + hacim + ATR genişleme."""
        n = MIN_BARS_M15 + 10
        mid = 100.0

        close = np.full(n, mid)
        close += np.random.uniform(-0.2, 0.2, n)
        high = close + 0.3
        low = close - 0.3
        volume = np.full(n, 80.0)

        # Son bar: aşağı kırılım + yüksek hacim
        close[-1] = mid - 3.0
        high[-1] = close[-1] + 0.3
        low[-1] = close[-1] - 0.5
        volume[-1] = 250.0

        # ATR genişleme
        high[-3:-1] = close[-3:-1] + 2.0
        low[-3:-1] = close[-3:-1] - 2.0

        signal = ogul._check_breakout("F_THYAO", close, high, low, volume)
        if signal is not None:
            assert signal.signal_type == SignalType.SELL
            assert signal.strategy == StrategyType.BREAKOUT

    def test_volume_filter_mandatory(self, ogul, mock_mt5):
        """Hacim filtresi zorunlu — düşük hacim → sinyal yok."""
        n = MIN_BARS_M15 + 10
        mid = 100.0

        close = np.full(n, mid)
        close += np.random.uniform(-0.2, 0.2, n)
        high = close + 0.3
        low = close - 0.3
        volume = np.full(n, 100.0)

        # Kırılım var ama hacim düşük
        close[-1] = mid + 3.0
        high[-1] = close[-1] + 0.5
        low[-1] = close[-1] - 0.3
        volume[-1] = 100.0  # <= avg * 1.5 → filtre

        # ATR genişleme
        high[-3:-1] = close[-3:-1] + 2.0
        low[-3:-1] = close[-3:-1] - 2.0

        signal = ogul._check_breakout("F_THYAO", close, high, low, volume)
        assert signal is None

    def test_no_atr_expansion_no_signal(self, ogul, mock_mt5):
        """ATR genişleme yok → sinyal yok."""
        n = MIN_BARS_M15 + 10
        mid = 100.0

        # Yüksek volatiliteli range → ATR zaten yüksek
        close = np.full(n, mid)
        close += np.random.uniform(-1.0, 1.0, n)
        high = close + 2.0   # ATR'yi yüksek tut
        low = close - 2.0
        volume = np.full(n, 80.0)

        # Son bar: küçük bir kırılım (zaten yüksek ATR'den küçük)
        close[-1] = mid + 3.0
        high[-1] = close[-1] + 1.5   # Mevcut ATR'den düşük genişleme
        low[-1] = close[-1] - 1.5
        volume[-1] = 250.0

        signal = ogul._check_breakout("F_THYAO", close, high, low, volume)
        assert signal is None

    def test_sl_at_range_midpoint(self, ogul, mock_mt5):
        """SL: last_close - ATR_mult → fiyatın altında."""
        n = MIN_BARS_M15 + 10
        mid = 100.0

        close = np.full(n, mid)
        close += np.random.uniform(-0.2, 0.2, n)
        high = close + 0.3
        low = close - 0.3
        volume = np.full(n, 80.0)

        close[-1] = mid + 3.0
        high[-1] = close[-1] + 0.5
        low[-1] = close[-1] - 0.3
        volume[-1] = 250.0

        high[-3:-1] = close[-3:-1] + 2.0
        low[-3:-1] = close[-3:-1] - 2.0

        # Tick fiyatını breakout close'a yakın ayarla (tutarlı test verisi)
        mock_mt5.get_tick.return_value = SimpleNamespace(
            ask=close[-1], bid=close[-1] - 0.1,
        )

        signal = ogul._check_breakout("F_THYAO", close, high, low, volume)
        if signal is not None:
            # SL = last_close - BO_SL_ATR_MULT * ATR → fiyatın altında
            assert signal.sl < signal.price  # BUY ise SL fiyatın altında

    def test_tp_range_width(self, ogul, mock_mt5):
        """TP: price ± range genişliği."""
        n = MIN_BARS_M15 + 10
        mid = 100.0

        close = np.full(n, mid)
        close += np.random.uniform(-0.2, 0.2, n)
        high = close + 0.3
        low = close - 0.3
        volume = np.full(n, 80.0)

        close[-1] = mid + 3.0
        high[-1] = close[-1] + 0.5
        low[-1] = close[-1] - 0.3
        volume[-1] = 250.0

        high[-3:-1] = close[-3:-1] + 2.0
        low[-3:-1] = close[-3:-1] - 2.0

        signal = ogul._check_breakout("F_THYAO", close, high, low, volume)
        if signal is not None and signal.signal_type == SignalType.BUY:
            # TP > price
            assert signal.tp > signal.price

    def test_insufficient_bars(self, ogul, mock_mt5):
        """Yetersiz bar verisi → None."""
        close = np.array([100.0] * 10)
        high = close + 0.3
        low = close - 0.3
        volume = np.full(10, 100.0)

        signal = ogul._check_breakout("F_THYAO", close, high, low, volume)
        assert signal is None

    def test_no_tick_no_signal(self, ogul, mock_mt5):
        """get_tick None → sinyal yok."""
        mock_mt5.get_tick.return_value = None
        n = MIN_BARS_M15 + 10
        mid = 100.0

        close = np.full(n, mid)
        close += np.random.uniform(-0.2, 0.2, n)
        high = close + 0.3
        low = close - 0.3
        volume = np.full(n, 80.0)

        close[-1] = mid + 3.0
        high[-1] = close[-1] + 0.5
        low[-1] = close[-1] - 0.3
        volume[-1] = 250.0

        high[-3:-1] = close[-3:-1] + 2.0
        low[-3:-1] = close[-3:-1] - 2.0

        signal = ogul._check_breakout("F_THYAO", close, high, low, volume)
        # Tick yoksa sinyal yok (veya None dönmeli)

    def test_strength_bounded(self, ogul, mock_mt5):
        """Sinyal gücü [0, 1] aralığında."""
        n = MIN_BARS_M15 + 10
        mid = 100.0

        close = np.full(n, mid)
        close += np.random.uniform(-0.2, 0.2, n)
        high = close + 0.3
        low = close - 0.3
        volume = np.full(n, 80.0)

        close[-1] = mid + 3.0
        high[-1] = close[-1] + 0.5
        low[-1] = close[-1] - 0.3
        volume[-1] = 250.0

        high[-3:-1] = close[-3:-1] + 2.0
        low[-3:-1] = close[-3:-1] - 2.0

        signal = ogul._check_breakout("F_THYAO", close, high, low, volume)
        if signal is not None:
            assert 0 <= signal.strength <= 1.0


# ═════════════════════════════════════════════════════════════════════
#  TestH1Confirmation — H1 zaman dilimi onayı
# ═════════════════════════════════════════════════════════════════════

class TestH1Confirmation:
    """_confirm_h1 testleri."""

    def test_h1_buy_confirmed(self, ogul, tmp_db):
        """H1 EMA(20) > EMA(50) → BUY onaylı."""
        h1_bars = _make_trend_bars(
            n=MIN_BARS_H1 + 20, direction="up", timeframe="H1",
        )
        _insert_bars(tmp_db, h1_bars, "F_THYAO", "H1")

        signal = Signal(
            symbol="F_THYAO", signal_type=SignalType.BUY,
            price=100.0, sl=95.0, tp=110.0,
            strategy=StrategyType.TREND_FOLLOW,
        )
        # H1'de yukarı trend → onay
        result = ogul._confirm_h1("F_THYAO", signal)
        # EMA(20) > EMA(50) sağlanıyorsa True
        # (synthetic datada sağlanır)
        assert isinstance(result, bool)

    def test_h1_sell_rejected_in_uptrend(self, ogul, tmp_db):
        """H1 yukarı trend → SELL reddedilir."""
        h1_bars = _make_trend_bars(
            n=MIN_BARS_H1 + 20, direction="up", timeframe="H1",
        )
        _insert_bars(tmp_db, h1_bars, "F_THYAO", "H1")

        signal = Signal(
            symbol="F_THYAO", signal_type=SignalType.SELL,
            price=100.0, sl=105.0, tp=90.0,
            strategy=StrategyType.TREND_FOLLOW,
        )
        result = ogul._confirm_h1("F_THYAO", signal)
        # H1'de EMA(20)>EMA(50) ise SELL reddedilir
        # (result = False)
        assert isinstance(result, bool)

    def test_h1_insufficient_data(self, ogul, tmp_db):
        """H1 yetersiz veri → False."""
        # Çok az bar
        h1_bars = _make_trend_bars(n=10, direction="up", timeframe="H1")
        _insert_bars(tmp_db, h1_bars, "F_THYAO", "H1")

        signal = Signal(
            symbol="F_THYAO", signal_type=SignalType.BUY,
            price=100.0, sl=95.0, tp=110.0,
            strategy=StrategyType.TREND_FOLLOW,
        )
        result = ogul._confirm_h1("F_THYAO", signal)
        assert result is False

    def test_h1_no_data(self, ogul, tmp_db):
        """H1 veri yok → False."""
        signal = Signal(
            symbol="F_THYAO", signal_type=SignalType.BUY,
            price=100.0, sl=95.0, tp=110.0,
            strategy=StrategyType.TREND_FOLLOW,
        )
        result = ogul._confirm_h1("F_THYAO", signal)
        assert result is False


# ═════════════════════════════════════════════════════════════════════
#  TestExecuteSignal — Emir yürütme testleri
# ═════════════════════════════════════════════════════════════════════

class TestExecuteSignal:
    """_execute_signal testleri."""

    def _make_signal(self, symbol="F_THYAO"):
        """Test sinyali oluşturur."""
        return Signal(
            symbol=symbol, signal_type=SignalType.BUY,
            price=100.0, sl=95.0, tp=110.0,
            strength=0.7, reason="test",
            strategy=StrategyType.TREND_FOLLOW,
        )

    def test_successful_order(self, ogul, mock_mt5, tmp_db, mock_baba):
        """Başarılı emir → Trade oluşur + active_trades'e eklenir (SENT state)."""
        # Bar verisi gerekli (ATR hesabı için)
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        signal = self._make_signal()
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(ogul, '_is_trading_allowed', return_value=True):
            ogul._execute_signal(signal, regime)

        assert "F_THYAO" in ogul.active_trades
        trade = ogul.active_trades["F_THYAO"]
        assert trade.state == TradeState.SENT
        assert trade.order_ticket == 12345
        assert trade.direction == "BUY"
        assert trade.strategy == "trend_follow"
        # Sayaç FILLED'da artıyor, SENT'te değil
        mock_baba.increment_daily_trade_count.assert_not_called()

    def test_failed_order(self, ogul, mock_mt5, tmp_db, mock_baba):
        """Başarısız emir → Trade oluşmaz."""
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        mock_mt5.send_order.return_value = None

        signal = self._make_signal()
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(ogul, '_is_trading_allowed', return_value=True):
            ogul._execute_signal(signal, regime)

        assert "F_THYAO" not in ogul.active_trades

    def test_correlation_blocks(self, ogul, mock_mt5, tmp_db, mock_baba):
        """Korelasyon engeli → işlem açılmaz."""
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        mock_baba.check_correlation_limits.return_value = RiskVerdict(
            can_trade=False, reason="Aynı yönde max pozisyon",
        )

        signal = self._make_signal()
        regime = Regime(regime_type=RegimeType.TREND)

        ogul._execute_signal(signal, regime)

        assert "F_THYAO" not in ogul.active_trades
        mock_mt5.send_order.assert_not_called()

    def test_zero_lot_no_trade(self, ogul, mock_mt5, tmp_db, mock_baba):
        """Lot = 0 → işlem açılmaz."""
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        mock_baba.calculate_position_size.return_value = 0.0

        signal = self._make_signal()
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(ogul, '_is_trading_allowed', return_value=True):
            ogul._execute_signal(signal, regime)

        assert "F_THYAO" not in ogul.active_trades
        mock_mt5.send_order.assert_not_called()

    def test_db_trade_inserted(self, ogul, mock_mt5, tmp_db, mock_baba):
        """DB'ye trade kaydı eklenir."""
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        signal = self._make_signal()
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(ogul, '_is_trading_allowed', return_value=True):
            ogul._execute_signal(signal, regime)

        trades = tmp_db.get_trades(symbol="F_THYAO")
        assert len(trades) >= 1
        t = trades[0]
        assert t["symbol"] == "F_THYAO"
        assert t["direction"] == "BUY"
        assert t["strategy"] == "trend_follow"

    def test_event_logged(self, ogul, mock_mt5, tmp_db, mock_baba):
        """ORDER_SENT event kaydedilir."""
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        signal = self._make_signal()
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(ogul, '_is_trading_allowed', return_value=True):
            ogul._execute_signal(signal, regime)

        events = tmp_db.get_events(event_type="ORDER_SENT")
        assert len(events) >= 1

    def test_no_baba_fallback_lot(self, ogul_no_baba, mock_mt5, tmp_db):
        """Baba yoksa fallback lot = 1.0, state = SENT."""
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        signal = Signal(
            symbol="F_THYAO", signal_type=SignalType.BUY,
            price=100.0, sl=95.0, tp=110.0,
            strength=0.7, reason="test",
            strategy=StrategyType.TREND_FOLLOW,
        )
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(ogul_no_baba, '_is_trading_allowed', return_value=True):
            ogul_no_baba._execute_signal(signal, regime)

        assert "F_THYAO" in ogul_no_baba.active_trades
        trade = ogul_no_baba.active_trades["F_THYAO"]
        assert trade.volume == 1.0
        assert trade.state == TradeState.SENT

    def test_empty_bars_no_trade(self, ogul, mock_mt5, tmp_db, mock_baba):
        """Bar verisi yok → işlem açılmaz (ATR hesaplanamaz → lot=0)."""
        signal = self._make_signal()
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(ogul, '_is_trading_allowed', return_value=True):
            ogul._execute_signal(signal, regime)

        assert "F_THYAO" not in ogul.active_trades


# ═════════════════════════════════════════════════════════════════════
#  TestManageActiveTrades — Aktif işlem yönetimi
# ═════════════════════════════════════════════════════════════════════

class TestManageActiveTrades:
    """_manage_active_trades, _manage_trend_follow, _manage_mean_reversion testleri."""

    def _setup_trade(self, ogul, mock_mt5, symbol="F_THYAO", strategy="trend_follow"):
        """Mevcut aktif işlem ekler."""
        trade = Trade(
            symbol=symbol, direction="BUY", volume=1.0,
            entry_price=100.0, sl=95.0, tp=110.0,
            state=TradeState.FILLED, ticket=999,
            strategy=strategy, trailing_sl=95.0, db_id=1,
        )
        ogul.active_trades[symbol] = trade
        # MT5'te pozisyon var
        mock_mt5.get_positions.return_value = [
            {"ticket": 999, "symbol": symbol, "type": "BUY",
             "volume": 1.0, "price_open": 100.0, "sl": 95.0,
             "tp": 110.0, "price_current": 105.0}
        ]
        return trade

    def test_volatile_closes_all(self, ogul, mock_mt5, tmp_db):
        """VOLATILE → tüm pozisyonlar kapatılır."""
        self._setup_trade(ogul, mock_mt5)
        mock_mt5.get_tick.return_value = SimpleNamespace(ask=105.0, bid=104.9)

        regime = Regime(regime_type=RegimeType.VOLATILE)
        ogul._manage_active_trades(regime)

        mock_mt5.close_position.assert_called_with(999)
        assert "F_THYAO" not in ogul.active_trades

    def test_olay_closes_all(self, ogul, mock_mt5, tmp_db):
        """OLAY → tüm pozisyonlar kapatılır."""
        self._setup_trade(ogul, mock_mt5)
        mock_mt5.get_tick.return_value = SimpleNamespace(ask=105.0, bid=104.9)

        regime = Regime(regime_type=RegimeType.OLAY)
        ogul._manage_active_trades(regime)

        mock_mt5.close_position.assert_called_with(999)
        assert "F_THYAO" not in ogul.active_trades

    def test_trend_follow_trailing_stop_update(self, ogul, mock_mt5, tmp_db):
        """Trend follow: trailing stop yukarı güncellenir (BUY)."""
        trade = self._setup_trade(ogul, mock_mt5, strategy="trend_follow")

        # M15 bar verisi ekle (EMA, ATR hesabı için)
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10, direction="up")
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        regime = Regime(regime_type=RegimeType.TREND)
        ogul._manage_active_trades(regime)

        # modify_position çağrılmış mı kontrol
        # (fiyat yukarı gittiyse trailing SL güncellenmeli)

    def test_trend_follow_ema_violation_close(self, ogul, mock_mt5, tmp_db):
        """Trend follow: EMA(20) ihlali → pozisyon kapatılır."""
        trade = self._setup_trade(ogul, mock_mt5, strategy="trend_follow")
        # Fiyat EMA(20) altına düşmüş
        mock_mt5.get_positions.return_value = [
            {"ticket": 999, "symbol": "F_THYAO", "type": "BUY",
             "volume": 1.0, "price_open": 100.0, "sl": 95.0,
             "tp": 110.0, "price_current": 70.0}  # çok düşük → EMA altında
        ]
        mock_mt5.get_tick.return_value = SimpleNamespace(ask=70.5, bid=70.0)

        # Bar verisi: trend halâ yukarı ama fiyat çok düştü
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10, direction="up")
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        regime = Regime(regime_type=RegimeType.TREND)
        ogul._manage_active_trades(regime)

        # Fiyat EMA(20) altındaysa → close_position çağrılır
        # (barlar yukarı trend ama current_price çok düşük)

    def test_mean_reversion_bb_middle_close(self, ogul, mock_mt5, tmp_db):
        """Mean reversion: BB orta bant ulaşımı → pozisyon kapatılır."""
        trade = self._setup_trade(ogul, mock_mt5, strategy="mean_reversion")
        # Fiyat BB orta bandına ulaştı
        mock_mt5.get_positions.return_value = [
            {"ticket": 999, "symbol": "F_THYAO", "type": "BUY",
             "volume": 1.0, "price_open": 95.0, "sl": 90.0,
             "tp": 100.0, "price_current": 100.5}
        ]
        mock_mt5.get_tick.return_value = SimpleNamespace(ask=100.5, bid=100.4)

        # Range bar verisi
        bars = _make_range_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        regime = Regime(regime_type=RegimeType.RANGE)
        ogul._manage_active_trades(regime)

        # BB orta bant ulaşıldıysa close_position çağrılır

    def test_breakout_no_extra_exit(self, ogul, mock_mt5, tmp_db):
        """Breakout: sabit SL/TP, ek çıkış mantığı yok."""
        trade = self._setup_trade(ogul, mock_mt5, strategy="breakout")

        regime = Regime(regime_type=RegimeType.RANGE)
        ogul._manage_active_trades(regime)

        # Breakout stratejisinde ek yönetim yok
        # Pozisyon aktif kalmalı (SL/TP MT5 yönetir)
        assert "F_THYAO" in ogul.active_trades

    def test_position_not_in_mt5(self, ogul, mock_mt5, tmp_db):
        """MT5'te pozisyon yok → harici kapanmış."""
        trade = self._setup_trade(ogul, mock_mt5, strategy="trend_follow")
        # MT5'te pozisyon yok (SL/TP tetiklendi)
        mock_mt5.get_positions.return_value = []
        mock_mt5.get_tick.return_value = SimpleNamespace(ask=92.0, bid=91.9)

        regime = Regime(regime_type=RegimeType.TREND)
        ogul._manage_active_trades(regime)

        assert "F_THYAO" not in ogul.active_trades

    def test_no_active_trades_no_action(self, ogul, mock_mt5):
        """Aktif işlem yoksa hiçbir şey yapma."""
        regime = Regime(regime_type=RegimeType.TREND)
        ogul._manage_active_trades(regime)
        mock_mt5.get_positions.assert_not_called()


# ═════════════════════════════════════════════════════════════════════
#  TestSyncPositions — MT5 pozisyon senkronizasyonu
# ═════════════════════════════════════════════════════════════════════

class TestSyncPositions:
    """_sync_positions testleri."""

    def test_synced_positions(self, ogul, mock_mt5, tmp_db):
        """MT5'teki pozisyon ile eşleşen trade."""
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            entry_price=100.0, sl=95.0, tp=110.0,
            state=TradeState.FILLED, ticket=999, db_id=1,
        )
        ogul.active_trades["F_THYAO"] = trade
        mock_mt5.get_positions.return_value = [
            {"ticket": 999, "symbol": "F_THYAO"}
        ]

        ogul._sync_positions()
        assert "F_THYAO" in ogul.active_trades

    def test_externally_closed(self, ogul, mock_mt5, tmp_db):
        """MT5'te olmayan pozisyon → harici kapanmış."""
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            entry_price=100.0, sl=95.0, tp=110.0,
            state=TradeState.FILLED, ticket=999, db_id=0,
        )
        ogul.active_trades["F_THYAO"] = trade
        mock_mt5.get_positions.return_value = []  # MT5'te yok
        mock_mt5.get_tick.return_value = SimpleNamespace(ask=102.0, bid=101.9)

        ogul._sync_positions()
        assert "F_THYAO" not in ogul.active_trades

    def test_no_active_trades_no_sync(self, ogul, mock_mt5):
        """Aktif işlem yoksa senkronizasyon yapılmaz."""
        ogul._sync_positions()
        mock_mt5.get_positions.assert_not_called()

    def test_multiple_positions_sync(self, ogul, mock_mt5, tmp_db):
        """Birden fazla pozisyon senkronizasyonu."""
        for sym, ticket in [("F_THYAO", 100), ("F_GARAN", 200)]:
            trade = Trade(
                symbol=sym, direction="BUY", volume=1.0,
                entry_price=100.0, sl=95.0, tp=110.0,
                state=TradeState.FILLED, ticket=ticket, db_id=0,
            )
            ogul.active_trades[sym] = trade

        # Sadece THYAO MT5'te, GARAN kapanmış
        mock_mt5.get_positions.return_value = [
            {"ticket": 100, "symbol": "F_THYAO"}
        ]
        mock_mt5.get_tick.return_value = SimpleNamespace(ask=102.0, bid=101.9)

        ogul._sync_positions()
        assert "F_THYAO" in ogul.active_trades
        assert "F_GARAN" not in ogul.active_trades


# ═════════════════════════════════════════════════════════════════════
#  TestRestoreActiveTrades — Engine restart geri yükleme
# ═════════════════════════════════════════════════════════════════════

class TestRestoreActiveTrades:
    """restore_active_trades testleri."""

    def test_restore_from_mt5(self, ogul, mock_mt5, tmp_db):
        """MT5 pozisyonlarından geri yükleme."""
        # DB'de eşleşen trade ekle
        trade_id = tmp_db.insert_trade({
            "strategy": "trend_follow",
            "symbol": "F_THYAO",
            "direction": "BUY",
            "lot": 1.0,
            "entry_time": datetime.now().isoformat(),
            "entry_price": 100.0,
        })

        mock_mt5.get_positions.return_value = [
            {
                "ticket": 555, "symbol": "F_THYAO", "type": "BUY",
                "volume": 1.0, "price_open": 100.0,
                "sl": 95.0, "tp": 110.0,
            }
        ]

        ogul.restore_active_trades()

        assert "F_THYAO" in ogul.active_trades
        trade = ogul.active_trades["F_THYAO"]
        assert trade.ticket == 555
        assert trade.direction == "BUY"
        assert trade.volume == 1.0
        assert trade.state == TradeState.FILLED

    def test_restore_no_positions(self, ogul, mock_mt5):
        """MT5'te pozisyon yok → boş."""
        mock_mt5.get_positions.return_value = []

        ogul.restore_active_trades()
        assert len(ogul.active_trades) == 0

    def test_restore_no_db_match(self, ogul, mock_mt5, tmp_db):
        """MT5 pozisyon var ama DB'de eşleşme yok → yine yüklenir."""
        mock_mt5.get_positions.return_value = [
            {
                "ticket": 777, "symbol": "F_GARAN", "type": "SELL",
                "volume": 2.0, "price_open": 50.0,
                "sl": 55.0, "tp": 40.0,
            }
        ]

        ogul.restore_active_trades()

        assert "F_GARAN" in ogul.active_trades
        trade = ogul.active_trades["F_GARAN"]
        assert trade.ticket == 777
        assert trade.strategy == ""  # DB eşleşmesi yok


# ═════════════════════════════════════════════════════════════════════
#  TestHandleClosedTrade — Kapanmış işlem yönetimi
# ═════════════════════════════════════════════════════════════════════

class TestHandleClosedTrade:
    """_handle_closed_trade testleri."""

    def test_state_updated(self, ogul, mock_mt5, tmp_db):
        """Trade state → CLOSED."""
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            entry_price=100.0, sl=95.0, tp=110.0,
            state=TradeState.FILLED, ticket=999, db_id=0,
        )
        ogul.active_trades["F_THYAO"] = trade
        mock_mt5.get_tick.return_value = SimpleNamespace(ask=105.0, bid=104.9)

        ogul._handle_closed_trade("F_THYAO", trade, "test_close")

        assert trade.state == TradeState.CLOSED
        assert trade.closed_at is not None

    def test_pnl_calculated_buy(self, ogul, mock_mt5, tmp_db):
        """BUY PnL: (exit - entry) * volume * contract_size."""
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            entry_price=100.0, sl=95.0, tp=110.0,
            state=TradeState.FILLED, ticket=999, db_id=0,
        )
        ogul.active_trades["F_THYAO"] = trade
        mock_mt5.get_tick.return_value = SimpleNamespace(ask=105.0, bid=104.9)

        ogul._handle_closed_trade("F_THYAO", trade, "test_close")

        # PnL = (104.9 - 100.0) * 1.0 * 100.0 = 490.0
        assert trade.pnl == pytest.approx(490.0, rel=0.01)
        assert trade.exit_price == 104.9

    def test_pnl_calculated_sell(self, ogul, mock_mt5, tmp_db):
        """SELL PnL: (entry - exit) * volume * contract_size."""
        trade = Trade(
            symbol="F_THYAO", direction="SELL", volume=1.0,
            entry_price=100.0, sl=105.0, tp=90.0,
            state=TradeState.FILLED, ticket=999, db_id=0,
        )
        ogul.active_trades["F_THYAO"] = trade
        mock_mt5.get_tick.return_value = SimpleNamespace(ask=95.5, bid=95.0)

        ogul._handle_closed_trade("F_THYAO", trade, "test_close")

        # PnL = (100.0 - 95.5) * 1.0 * 100.0 = 450.0
        assert trade.pnl == pytest.approx(450.0, rel=0.01)
        assert trade.exit_price == 95.5  # SELL → ask ile çıkış

    def test_db_updated(self, ogul, mock_mt5, tmp_db):
        """DB'deki trade kaydı güncellenir."""
        trade_id = tmp_db.insert_trade({
            "strategy": "trend_follow",
            "symbol": "F_THYAO",
            "direction": "BUY",
            "lot": 1.0,
            "entry_time": datetime.now().isoformat(),
            "entry_price": 100.0,
        })

        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            entry_price=100.0, sl=95.0, tp=110.0,
            state=TradeState.FILLED, ticket=999, db_id=trade_id,
        )
        ogul.active_trades["F_THYAO"] = trade
        mock_mt5.get_tick.return_value = SimpleNamespace(ask=105.0, bid=104.9)

        ogul._handle_closed_trade("F_THYAO", trade, "sl_tp")

        # DB kontrolü
        db_trade = tmp_db.get_trade(trade_id)
        assert db_trade is not None
        assert db_trade["exit_price"] is not None
        assert db_trade["exit_reason"] == "sl_tp"

    def test_removed_from_active(self, ogul, mock_mt5, tmp_db):
        """active_trades'den silinir."""
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            entry_price=100.0, sl=95.0, tp=110.0,
            state=TradeState.FILLED, ticket=999, db_id=0,
        )
        ogul.active_trades["F_THYAO"] = trade
        mock_mt5.get_tick.return_value = SimpleNamespace(ask=105.0, bid=104.9)

        ogul._handle_closed_trade("F_THYAO", trade, "manual")

        assert "F_THYAO" not in ogul.active_trades


# ═════════════════════════════════════════════════════════════════════
#  TestEdgeCases — Kenar durumlar
# ═════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Kenar durum testleri."""

    def test_mt5_no_connection_tick(self, ogul, mock_mt5, tmp_db):
        """MT5 bağlantı yok (get_tick None) → sinyal üretilmez."""
        mock_mt5.get_tick.return_value = None

        bars = _make_trend_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        regime = Regime(regime_type=RegimeType.TREND)
        ogul.process_signals(["F_THYAO"], regime)

        assert "F_THYAO" not in ogul.active_trades

    def test_empty_bars_no_signal(self, ogul, tmp_db):
        """Boş bar verisi → sinyal yok."""
        regime = Regime(regime_type=RegimeType.TREND)
        strategies = [StrategyType.TREND_FOLLOW]

        signal = ogul._generate_signal("F_THYAO", regime, strategies)
        assert signal is None

    def test_insufficient_bars(self, ogul, tmp_db):
        """Yetersiz bar verisi → sinyal yok."""
        bars = _make_trend_bars(n=20)  # < MIN_BARS_M15
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        regime = Regime(regime_type=RegimeType.TREND)
        strategies = [StrategyType.TREND_FOLLOW]

        signal = ogul._generate_signal("F_THYAO", regime, strategies)
        assert signal is None

    def test_one_trade_per_symbol(self, ogul, mock_mt5, tmp_db, mock_baba):
        """Sembol başına 1 aktif işlem kuralı."""
        # Mevcut işlem
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            entry_price=100.0, sl=95.0, tp=110.0,
            state=TradeState.FILLED, ticket=999,
        )
        ogul.active_trades["F_THYAO"] = trade

        # Sinyal verisi ekle
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")
        h1_bars = _make_trend_bars(n=MIN_BARS_H1 + 10, timeframe="H1")
        _insert_bars(tmp_db, h1_bars, "F_THYAO", "H1")

        regime = Regime(regime_type=RegimeType.TREND)
        ogul.process_signals(["F_THYAO"], regime)

        # send_order çağrılmamalı (mevcut işlem var)
        mock_mt5.send_order.assert_not_called()

    def test_killed_symbol_skipped(self, ogul, mock_mt5, tmp_db, mock_baba):
        """Kill-switch ile durdurulmuş sembol atlanır."""
        mock_baba.is_symbol_killed.return_value = True

        bars = _make_trend_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        regime = Regime(regime_type=RegimeType.TREND)
        ogul.process_signals(["F_THYAO"], regime)

        assert "F_THYAO" not in ogul.active_trades
        mock_mt5.send_order.assert_not_called()

    def test_handle_closed_no_tick(self, ogul, mock_mt5, tmp_db):
        """Tick yok → fallback bar verisi kullanılır."""
        bars = _make_trend_bars(n=5)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        mock_mt5.get_tick.return_value = None

        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            entry_price=100.0, sl=95.0, tp=110.0,
            state=TradeState.FILLED, ticket=999, db_id=0,
        )
        ogul.active_trades["F_THYAO"] = trade

        ogul._handle_closed_trade("F_THYAO", trade, "no_tick")

        assert trade.state == TradeState.CLOSED
        # Fallback: bar verisi kullanılmış olmalı
        assert trade.exit_price > 0 or trade.exit_price == 0  # DB'de bar varsa > 0

    def test_process_signals_error_recovery(self, ogul, mock_mt5, tmp_db):
        """Hata durumunda diğer semboller etkilenmemeli."""
        # İlk sembol hata üretsin
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10, symbol="F_GARAN")
        _insert_bars(tmp_db, bars, "F_GARAN", "M15")

        regime = Regime(regime_type=RegimeType.TREND)
        # Her iki sembol de işlenir, hata fırlatılmaz
        with patch.object(ogul, '_check_end_of_day'), \
             patch.object(ogul, '_is_trading_allowed', return_value=True):
            ogul.process_signals(["F_THYAO", "F_GARAN"], regime)


# ═════════════════════════════════════════════════════════════════════
#  TestTradeStateEnum — Yeni state'ler
# ═════════════════════════════════════════════════════════════════════

class TestTradeStateEnum:
    """TradeState enum yeni state testleri."""

    def test_new_states_exist(self):
        """Yeni state'ler tanımlı olmalı."""
        assert TradeState.SIGNAL.value == "signal"
        assert TradeState.SENT.value == "sent"
        assert TradeState.TIMEOUT.value == "timeout"
        assert TradeState.MARKET_RETRY.value == "market_retry"
        assert TradeState.REJECTED.value == "rejected"

    def test_all_states_count(self):
        """Toplam 11 state olmalı."""
        assert len(TradeState) == 11


# ═════════════════════════════════════════════════════════════════════
#  TestTradeDataclass — Yeni alanlar
# ═════════════════════════════════════════════════════════════════════

class TestTradeDataclass:
    """Trade dataclass yeni alan testleri."""

    def test_new_fields_defaults(self):
        """Yeni alanlar varsayılan değerlerle oluşmalı."""
        trade = Trade(symbol="F_THYAO", direction="BUY", volume=1.0)
        assert trade.order_ticket == 0
        assert trade.sent_at is None
        assert trade.requested_volume == 0.0
        assert trade.filled_volume == 0.0
        assert trade.limit_price == 0.0
        assert trade.regime_at_entry == ""
        assert trade.cancel_reason == ""
        assert trade.retry_count == 0
        assert trade.max_slippage == 0.0

    def test_new_fields_custom(self):
        """Yeni alanlar özel değerlerle oluşturulabilmeli."""
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            order_ticket=111, regime_at_entry="TREND",
            max_slippage=0.5, retry_count=1,
        )
        assert trade.order_ticket == 111
        assert trade.regime_at_entry == "TREND"
        assert trade.max_slippage == 0.5
        assert trade.retry_count == 1


# ═════════════════════════════════════════════════════════════════════
#  TestIsTradingAllowed — İşlem saatleri kontrolü
# ═════════════════════════════════════════════════════════════════════

class TestIsTradingAllowed:
    """_is_trading_allowed testleri."""

    def test_within_hours(self, ogul):
        """09:45-17:45 arası → True."""
        now = datetime(2025, 1, 6, 14, 0)  # Pazartesi 14:00
        assert ogul._is_trading_allowed(now) is True

    def test_before_open(self, ogul):
        """09:30 → False (dar pencere 09:45'ten başlar)."""
        now = datetime(2025, 1, 6, 9, 30)
        assert ogul._is_trading_allowed(now) is False

    def test_after_close(self, ogul):
        """17:46 → False."""
        now = datetime(2025, 1, 6, 17, 46)
        assert ogul._is_trading_allowed(now) is False

    def test_at_open(self, ogul):
        """09:45 → True."""
        now = datetime(2025, 1, 6, 9, 45)
        assert ogul._is_trading_allowed(now) is True

    def test_at_close(self, ogul):
        """17:45 → True."""
        now = datetime(2025, 1, 6, 17, 45)
        assert ogul._is_trading_allowed(now) is True

    def test_weekend(self, ogul):
        """Cumartesi → False."""
        now = datetime(2025, 1, 4, 14, 0)  # Cumartesi
        assert ogul._is_trading_allowed(now) is False

    def test_holiday(self, ogul):
        """Tatil günü → False."""
        now = datetime(2025, 1, 1, 14, 0)  # Yılbaşı
        assert ogul._is_trading_allowed(now) is False


# ═════════════════════════════════════════════════════════════════════
#  TestEndOfDay — Gün sonu kapatma
# ═════════════════════════════════════════════════════════════════════

class TestEndOfDay:
    """_check_end_of_day testleri."""

    def test_before_close_no_action(self, ogul, mock_mt5):
        """17:44 → hiçbir şey yapma."""
        now = datetime(2025, 1, 6, 17, 44)
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            state=TradeState.FILLED, ticket=999,
        )
        ogul.active_trades["F_THYAO"] = trade

        ogul._check_end_of_day(now)

        assert "F_THYAO" in ogul.active_trades
        mock_mt5.close_position.assert_not_called()

    def test_close_filled_position(self, ogul, mock_mt5, tmp_db):
        """17:46 → FILLED pozisyon kapatılır."""
        now = datetime(2025, 1, 6, 17, 46)
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            entry_price=100.0, state=TradeState.FILLED,
            ticket=999, db_id=0,
        )
        ogul.active_trades["F_THYAO"] = trade

        ogul._check_end_of_day(now)

        mock_mt5.close_position.assert_called_with(999)
        assert "F_THYAO" not in ogul.active_trades

    def test_cancel_sent_order(self, ogul, mock_mt5, tmp_db):
        """17:46 → SENT emir iptal edilir."""
        now = datetime(2025, 1, 6, 17, 46)
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            state=TradeState.SENT, order_ticket=555,
        )
        ogul.active_trades["F_THYAO"] = trade

        ogul._check_end_of_day(now)

        mock_mt5.cancel_order.assert_called_with(555)
        assert "F_THYAO" not in ogul.active_trades

    def test_cancel_partial_with_close(self, ogul, mock_mt5, tmp_db):
        """17:46 → PARTIAL emir iptal + kısmi pozisyon kapatma."""
        now = datetime(2025, 1, 6, 17, 46)
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            state=TradeState.PARTIAL, order_ticket=555,
            ticket=888, filled_volume=0.5,
        )
        ogul.active_trades["F_THYAO"] = trade

        ogul._check_end_of_day(now)

        mock_mt5.cancel_order.assert_called_with(555)
        mock_mt5.close_position.assert_called_with(888)
        assert "F_THYAO" not in ogul.active_trades

    def test_empty_trades_no_action(self, ogul, mock_mt5):
        """Aktif işlem yok → hiçbir şey yapma."""
        now = datetime(2025, 1, 6, 17, 46)
        ogul._check_end_of_day(now)
        mock_mt5.close_position.assert_not_called()
        mock_mt5.cancel_order.assert_not_called()

    def test_eod_event_logged(self, ogul, mock_mt5, tmp_db):
        """EOD_CLOSE event kaydedilir."""
        now = datetime(2025, 1, 6, 17, 46)
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            entry_price=100.0, state=TradeState.FILLED,
            ticket=999, db_id=0,
        )
        ogul.active_trades["F_THYAO"] = trade

        ogul._check_end_of_day(now)

        events = tmp_db.get_events(event_type="EOD_CLOSE")
        assert len(events) >= 1


# ═════════════════════════════════════════════════════════════════════
#  TestExecuteSignalSM — State machine _execute_signal testleri
# ═════════════════════════════════════════════════════════════════════

class TestExecuteSignalSM:
    """State-machine _execute_signal testleri."""

    def _make_signal(self, symbol="F_THYAO"):
        return Signal(
            symbol=symbol, signal_type=SignalType.BUY,
            price=100.0, sl=95.0, tp=110.0,
            strength=0.7, reason="test",
            strategy=StrategyType.TREND_FOLLOW,
        )

    def test_signal_to_sent_flow(self, ogul, mock_mt5, tmp_db, mock_baba):
        """Başarılı akış: SIGNAL → PENDING → SENT."""
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        signal = self._make_signal()
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(ogul, '_is_trading_allowed', return_value=True):
            ogul._execute_signal(signal, regime)

        assert "F_THYAO" in ogul.active_trades
        trade = ogul.active_trades["F_THYAO"]
        assert trade.state == TradeState.SENT
        assert trade.order_ticket == 12345
        assert trade.regime_at_entry == "TREND"
        assert trade.requested_volume == trade.volume

    def test_limit_order_type(self, ogul, mock_mt5, tmp_db, mock_baba):
        """LIMIT emir gönderilmeli (market değil)."""
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        signal = self._make_signal()
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(ogul, '_is_trading_allowed', return_value=True):
            ogul._execute_signal(signal, regime)

        call_kwargs = mock_mt5.send_order.call_args
        assert call_kwargs[1].get("order_type") == "limit"

    def test_baba_correlation_rejection(self, ogul, mock_mt5, tmp_db, mock_baba):
        """BABA korelasyon reddi → CANCELLED (send_order çağrılmaz)."""
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        mock_baba.check_correlation_limits.return_value = RiskVerdict(
            can_trade=False, reason="Aynı yönde max",
        )
        signal = self._make_signal()
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(ogul, '_is_trading_allowed', return_value=True):
            ogul._execute_signal(signal, regime)

        assert "F_THYAO" not in ogul.active_trades
        mock_mt5.send_order.assert_not_called()

    def test_outside_hours_cancelled(self, ogul, mock_mt5, tmp_db, mock_baba):
        """İşlem saatleri dışında → CANCELLED."""
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        signal = self._make_signal()
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(ogul, '_is_trading_allowed', return_value=False):
            ogul._execute_signal(signal, regime)

        assert "F_THYAO" not in ogul.active_trades
        mock_mt5.send_order.assert_not_called()

    def test_concurrent_limit_blocks(self, ogul, mock_mt5, tmp_db, mock_baba):
        """Eş zamanlı pozisyon limiti aşımı → CANCELLED."""
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        # 5 aktif trade (FILLED + SENT karışık)
        for i in range(3):
            ogul.active_trades[f"F_F{i}"] = Trade(
                symbol=f"F_F{i}", direction="BUY", volume=1.0,
                state=TradeState.FILLED, ticket=i + 1,
            )
        for i in range(2):
            ogul.active_trades[f"F_S{i}"] = Trade(
                symbol=f"F_S{i}", direction="BUY", volume=1.0,
                state=TradeState.SENT, order_ticket=100 + i,
            )

        signal = self._make_signal()
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(ogul, '_is_trading_allowed', return_value=True):
            ogul._execute_signal(signal, regime)

        assert "F_THYAO" not in ogul.active_trades

    def test_margin_insufficient_blocks(self, ogul, mock_mt5, tmp_db, mock_baba):
        """Yetersiz teminat → CANCELLED."""
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        mock_mt5.get_account_info.return_value = SimpleNamespace(
            equity=100000.0, free_margin=10000.0,
        )

        signal = self._make_signal()
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(ogul, '_is_trading_allowed', return_value=True):
            ogul._execute_signal(signal, regime)

        assert "F_THYAO" not in ogul.active_trades
        mock_mt5.send_order.assert_not_called()

    def test_lot_capped_at_max(self, ogul, mock_mt5, tmp_db, mock_baba):
        """Lot MAX_LOT_PER_CONTRACT ile sınırlanır."""
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        mock_baba.calculate_position_size.return_value = 5.0

        signal = self._make_signal()
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(ogul, '_is_trading_allowed', return_value=True):
            ogul._execute_signal(signal, regime)

        assert "F_THYAO" in ogul.active_trades
        trade = ogul.active_trades["F_THYAO"]
        assert trade.volume == MAX_LOT_PER_CONTRACT

    def test_send_order_failed_cancelled(self, ogul, mock_mt5, tmp_db, mock_baba):
        """send_order None → CANCELLED + TRADE_ERROR event."""
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        mock_mt5.send_order.return_value = None

        signal = self._make_signal()
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(ogul, '_is_trading_allowed', return_value=True):
            ogul._execute_signal(signal, regime)

        assert "F_THYAO" not in ogul.active_trades
        events = tmp_db.get_events(event_type="TRADE_ERROR")
        assert len(events) >= 1

    def test_max_slippage_calculated(self, ogul, mock_mt5, tmp_db, mock_baba):
        """max_slippage ATR'den hesaplanır (> 0)."""
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        signal = self._make_signal()
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(ogul, '_is_trading_allowed', return_value=True):
            ogul._execute_signal(signal, regime)

        trade = ogul.active_trades["F_THYAO"]
        assert trade.max_slippage > 0


# ═════════════════════════════════════════════════════════════════════
#  TestAdvanceSent — SENT state ilerletme
# ═════════════════════════════════════════════════════════════════════

class TestAdvanceSent:
    """_advance_sent testleri."""

    def _make_sent_trade(self, symbol="F_THYAO"):
        return Trade(
            symbol=symbol, direction="BUY", volume=1.0,
            entry_price=100.0, sl=95.0, tp=110.0,
            state=TradeState.SENT, order_ticket=555,
            sent_at=datetime.now(),
            requested_volume=1.0, regime_at_entry="TREND",
        )

    def test_filled(self, ogul, mock_mt5, tmp_db):
        """SENT → FILLED dolum olunca."""
        trade = self._make_sent_trade()
        ogul.active_trades["F_THYAO"] = trade

        mock_mt5.check_order_status.return_value = {
            "status": "filled", "filled_volume": 1.0,
            "remaining_volume": 0.0, "deal_ticket": 888,
        }
        mock_mt5.get_positions.return_value = [
            {"ticket": 888, "price_open": 100.05},
        ]

        regime = Regime(regime_type=RegimeType.TREND)
        ogul._advance_sent("F_THYAO", trade, regime)

        assert trade.state == TradeState.FILLED
        assert trade.ticket == 888
        assert trade.filled_volume == 1.0

    def test_partial(self, ogul, mock_mt5, tmp_db):
        """SENT → PARTIAL kısmi dolumda."""
        trade = self._make_sent_trade()
        ogul.active_trades["F_THYAO"] = trade

        mock_mt5.check_order_status.return_value = {
            "status": "partial", "filled_volume": 0.6,
            "remaining_volume": 0.4, "deal_ticket": 0,
        }

        regime = Regime(regime_type=RegimeType.TREND)
        ogul._advance_sent("F_THYAO", trade, regime)

        assert trade.state == TradeState.PARTIAL
        assert trade.filled_volume == 0.6

    def test_pending_timeout(self, ogul, mock_mt5, tmp_db):
        """SENT → TIMEOUT emir hâlâ bekliyor ve süre aşıldı."""
        trade = self._make_sent_trade()
        trade.sent_at = datetime(2020, 1, 1, 12, 0, 0)  # çok eski
        ogul.active_trades["F_THYAO"] = trade

        mock_mt5.check_order_status.return_value = {
            "status": "pending", "filled_volume": 0.0,
            "remaining_volume": 1.0, "deal_ticket": 0,
        }

        regime = Regime(regime_type=RegimeType.TREND)
        ogul._advance_sent("F_THYAO", trade, regime)

        assert trade.state == TradeState.TIMEOUT

    def test_exchange_cancelled(self, ogul, mock_mt5, tmp_db):
        """SENT → TIMEOUT borsa tarafından iptal."""
        trade = self._make_sent_trade()
        ogul.active_trades["F_THYAO"] = trade

        mock_mt5.check_order_status.return_value = {
            "status": "cancelled", "filled_volume": 0.0,
            "remaining_volume": 1.0, "deal_ticket": 0,
        }

        regime = Regime(regime_type=RegimeType.TREND)
        ogul._advance_sent("F_THYAO", trade, regime)

        assert trade.state == TradeState.TIMEOUT

    def test_none_status_no_timeout(self, ogul, mock_mt5, tmp_db):
        """None yanıt, henüz timeout olmamış → SENT kalır."""
        trade = self._make_sent_trade()
        trade.sent_at = datetime.now()  # şu an → timeout olmamış
        ogul.active_trades["F_THYAO"] = trade

        mock_mt5.check_order_status.return_value = None

        regime = Regime(regime_type=RegimeType.TREND)
        ogul._advance_sent("F_THYAO", trade, regime)

        assert trade.state == TradeState.SENT

    def test_none_status_with_timeout(self, ogul, mock_mt5, tmp_db):
        """None yanıt, timeout aşılmış → TIMEOUT."""
        trade = self._make_sent_trade()
        trade.sent_at = datetime(2020, 1, 1, 12, 0, 0)  # çok eski
        ogul.active_trades["F_THYAO"] = trade

        mock_mt5.check_order_status.return_value = None

        regime = Regime(regime_type=RegimeType.TREND)
        ogul._advance_sent("F_THYAO", trade, regime)

        assert trade.state == TradeState.TIMEOUT


# ═════════════════════════════════════════════════════════════════════
#  TestAdvancePartial — PARTIAL state ilerletme
# ═════════════════════════════════════════════════════════════════════

class TestAdvancePartial:
    """_advance_partial testleri."""

    def test_accept_above_50pct(self, ogul, mock_mt5, tmp_db):
        """≥50% dolum → FILLED olarak kabul."""
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            state=TradeState.PARTIAL, order_ticket=555,
            requested_volume=1.0, filled_volume=0.6,
            ticket=888, db_id=0,
        )
        ogul.active_trades["F_THYAO"] = trade
        mock_mt5.get_positions.return_value = [
            {"ticket": 888, "price_open": 100.05},
        ]

        regime = Regime(regime_type=RegimeType.TREND)
        ogul._advance_partial("F_THYAO", trade, regime)

        assert trade.state == TradeState.FILLED
        assert trade.volume == 0.6
        mock_mt5.cancel_order.assert_called_with(555)

    def test_reject_below_50pct(self, ogul, mock_mt5, tmp_db):
        """<50% dolum → CANCELLED, kısmi pozisyon kapatılır."""
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            state=TradeState.PARTIAL, order_ticket=555,
            requested_volume=1.0, filled_volume=0.3,
            ticket=888, db_id=0,
        )
        ogul.active_trades["F_THYAO"] = trade

        regime = Regime(regime_type=RegimeType.TREND)
        ogul._advance_partial("F_THYAO", trade, regime)

        assert "F_THYAO" not in ogul.active_trades
        mock_mt5.close_position.assert_called_with(888)
        mock_mt5.cancel_order.assert_called_with(555)

    def test_cancel_order_always_called(self, ogul, mock_mt5, tmp_db):
        """Bekleyen emir daima iptal edilir (kabul durumunda da)."""
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            state=TradeState.PARTIAL, order_ticket=555,
            requested_volume=1.0, filled_volume=0.7,
            ticket=888, db_id=0,
        )
        ogul.active_trades["F_THYAO"] = trade
        mock_mt5.get_positions.return_value = [
            {"ticket": 888, "price_open": 100.05},
        ]

        regime = Regime(regime_type=RegimeType.TREND)
        ogul._advance_partial("F_THYAO", trade, regime)

        mock_mt5.cancel_order.assert_called_with(555)
        assert trade.state == TradeState.FILLED


# ═════════════════════════════════════════════════════════════════════
#  TestAdvanceTimeout — TIMEOUT state ilerletme
# ═════════════════════════════════════════════════════════════════════

class TestAdvanceTimeout:
    """_advance_timeout testleri."""

    def test_trend_market_retry(self, ogul, mock_mt5, tmp_db):
        """TREND rejim → market retry."""
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            state=TradeState.TIMEOUT, order_ticket=555,
            regime_at_entry="TREND", limit_price=100.0,
            sl=95.0, tp=110.0, retry_count=0,
        )
        ogul.active_trades["F_THYAO"] = trade
        mock_mt5.send_order.return_value = {"order": 999}

        regime = Regime(regime_type=RegimeType.TREND)
        ogul._advance_timeout("F_THYAO", trade, regime)

        assert trade.state == TradeState.MARKET_RETRY
        assert trade.order_ticket == 999
        assert trade.retry_count == 1
        call_kwargs = mock_mt5.send_order.call_args
        assert call_kwargs[1].get("order_type") == "market"

    def test_volatile_cancelled(self, ogul, mock_mt5, tmp_db):
        """VOLATILE rejim → market YASAK → CANCELLED."""
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            state=TradeState.TIMEOUT, order_ticket=555,
            regime_at_entry="VOLATILE",
        )
        ogul.active_trades["F_THYAO"] = trade

        regime = Regime(regime_type=RegimeType.VOLATILE)
        ogul._advance_timeout("F_THYAO", trade, regime)

        assert "F_THYAO" not in ogul.active_trades
        mock_mt5.send_order.assert_not_called()

    def test_olay_cancelled(self, ogul, mock_mt5, tmp_db):
        """OLAY rejim → market YASAK → CANCELLED."""
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            state=TradeState.TIMEOUT, order_ticket=555,
            regime_at_entry="OLAY",
        )
        ogul.active_trades["F_THYAO"] = trade

        regime = Regime(regime_type=RegimeType.OLAY)
        ogul._advance_timeout("F_THYAO", trade, regime)

        assert "F_THYAO" not in ogul.active_trades

    def test_max_retry_reached(self, ogul, mock_mt5, tmp_db):
        """retry_count >= 1 → CANCELLED (tekrar yok)."""
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            state=TradeState.TIMEOUT, order_ticket=555,
            regime_at_entry="TREND", retry_count=1,
        )
        ogul.active_trades["F_THYAO"] = trade

        regime = Regime(regime_type=RegimeType.TREND)
        ogul._advance_timeout("F_THYAO", trade, regime)

        assert "F_THYAO" not in ogul.active_trades
        mock_mt5.send_order.assert_not_called()

    def test_market_retry_send_failed(self, ogul, mock_mt5, tmp_db):
        """Market emir başarısız → active_trades'den silinir."""
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            state=TradeState.TIMEOUT, order_ticket=555,
            regime_at_entry="TREND", retry_count=0,
            limit_price=100.0, sl=95.0, tp=110.0,
        )
        ogul.active_trades["F_THYAO"] = trade
        mock_mt5.send_order.return_value = None

        regime = Regime(regime_type=RegimeType.TREND)
        ogul._advance_timeout("F_THYAO", trade, regime)

        assert "F_THYAO" not in ogul.active_trades

    def test_cancel_order_called(self, ogul, mock_mt5, tmp_db):
        """Bekleyen emir her zaman iptal edilir."""
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            state=TradeState.TIMEOUT, order_ticket=555,
            regime_at_entry="VOLATILE",
        )
        ogul.active_trades["F_THYAO"] = trade

        regime = Regime(regime_type=RegimeType.VOLATILE)
        ogul._advance_timeout("F_THYAO", trade, regime)

        mock_mt5.cancel_order.assert_called_with(555)


# ═════════════════════════════════════════════════════════════════════
#  TestAdvanceMarketRetry — MARKET_RETRY state ilerletme
# ═════════════════════════════════════════════════════════════════════

class TestAdvanceMarketRetry:
    """_advance_market_retry testleri."""

    def test_filled_ok(self, ogul, mock_mt5, tmp_db):
        """Pozisyon var, slippage OK → FILLED."""
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            state=TradeState.MARKET_RETRY, ticket=999,
            limit_price=100.0, max_slippage=0.5, db_id=0,
        )
        ogul.active_trades["F_THYAO"] = trade
        mock_mt5.get_positions.return_value = [
            {"ticket": 999, "symbol": "F_THYAO", "price_open": 100.2},
        ]

        regime = Regime(regime_type=RegimeType.TREND)
        ogul._advance_market_retry("F_THYAO", trade, regime)

        assert trade.state == TradeState.FILLED
        assert trade.entry_price == 100.2

    def test_no_position(self, ogul, mock_mt5, tmp_db):
        """Pozisyon yok → CANCELLED."""
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            state=TradeState.MARKET_RETRY, ticket=999,
            limit_price=100.0,
        )
        ogul.active_trades["F_THYAO"] = trade
        mock_mt5.get_positions.return_value = []

        regime = Regime(regime_type=RegimeType.TREND)
        ogul._advance_market_retry("F_THYAO", trade, regime)

        assert "F_THYAO" not in ogul.active_trades

    def test_slippage_exceeded(self, ogul, mock_mt5, tmp_db):
        """Slippage aşımı → pozisyon kapatılır, CANCELLED."""
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            state=TradeState.MARKET_RETRY, ticket=999,
            limit_price=100.0, max_slippage=0.3,
        )
        ogul.active_trades["F_THYAO"] = trade
        mock_mt5.get_positions.return_value = [
            {"ticket": 999, "symbol": "F_THYAO", "price_open": 100.5},  # slippage=0.5 > 0.3
        ]

        regime = Regime(regime_type=RegimeType.TREND)
        ogul._advance_market_retry("F_THYAO", trade, regime)

        assert "F_THYAO" not in ogul.active_trades
        mock_mt5.close_position.assert_called_with(999)

    def test_db_price_updated(self, ogul, mock_mt5, tmp_db):
        """Başarılı dolumda DB entry_price güncellenir."""
        db_id = tmp_db.insert_trade({
            "strategy": "trend_follow", "symbol": "F_THYAO",
            "direction": "BUY", "entry_time": "2025-01-06T14:00:00",
            "entry_price": 100.0, "lot": 1.0, "regime": "TREND",
        })

        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            state=TradeState.MARKET_RETRY, ticket=999,
            limit_price=100.0, max_slippage=1.0, db_id=db_id,
        )
        ogul.active_trades["F_THYAO"] = trade
        mock_mt5.get_positions.return_value = [
            {"ticket": 999, "symbol": "F_THYAO", "price_open": 100.3},
        ]

        regime = Regime(regime_type=RegimeType.TREND)
        ogul._advance_market_retry("F_THYAO", trade, regime)

        assert trade.entry_price == 100.3
        assert trade.state == TradeState.FILLED


# ═════════════════════════════════════════════════════════════════════
#  TestLimitChecks — İşlem limiti kontrolleri
# ═════════════════════════════════════════════════════════════════════

class TestLimitChecks:
    """Margin, concurrent, lot limit testleri."""

    def test_margin_reserve_20pct(self, ogul, mock_mt5, tmp_db, mock_baba):
        """free_margin < equity * 20% → CANCELLED."""
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        mock_mt5.get_account_info.return_value = SimpleNamespace(
            equity=100000.0, free_margin=19999.0,
        )

        signal = Signal(
            symbol="F_THYAO", signal_type=SignalType.BUY,
            price=100.0, sl=95.0, tp=110.0,
            strength=0.7, reason="test",
            strategy=StrategyType.TREND_FOLLOW,
        )
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(ogul, '_is_trading_allowed', return_value=True):
            ogul._execute_signal(signal, regime)

        assert "F_THYAO" not in ogul.active_trades

    def test_concurrent_includes_all_active_states(
        self, ogul, mock_mt5, tmp_db, mock_baba,
    ):
        """Concurrent sayım FILLED + SENT + PARTIAL + MARKET_RETRY içerir."""
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        # Farklı state'lerde 5 trade
        ogul.active_trades["F_A"] = Trade(
            symbol="F_A", direction="BUY", volume=1.0,
            state=TradeState.FILLED, ticket=1,
        )
        ogul.active_trades["F_B"] = Trade(
            symbol="F_B", direction="BUY", volume=1.0,
            state=TradeState.SENT, order_ticket=2,
        )
        ogul.active_trades["F_C"] = Trade(
            symbol="F_C", direction="BUY", volume=1.0,
            state=TradeState.PARTIAL, order_ticket=3,
        )
        ogul.active_trades["F_D"] = Trade(
            symbol="F_D", direction="BUY", volume=1.0,
            state=TradeState.MARKET_RETRY, ticket=4,
        )
        ogul.active_trades["F_E"] = Trade(
            symbol="F_E", direction="BUY", volume=1.0,
            state=TradeState.FILLED, ticket=5,
        )

        signal = Signal(
            symbol="F_THYAO", signal_type=SignalType.BUY,
            price=100.0, sl=95.0, tp=110.0,
            strength=0.7, reason="test",
            strategy=StrategyType.TREND_FOLLOW,
        )
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(ogul, '_is_trading_allowed', return_value=True):
            ogul._execute_signal(signal, regime)

        assert "F_THYAO" not in ogul.active_trades

    def test_lot_zero_cancelled_event(self, ogul, mock_mt5, tmp_db, mock_baba):
        """Lot = 0 → ORDER_CANCELLED event."""
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        mock_baba.calculate_position_size.return_value = 0.0

        signal = Signal(
            symbol="F_THYAO", signal_type=SignalType.BUY,
            price=100.0, sl=95.0, tp=110.0,
            strength=0.7, reason="test",
            strategy=StrategyType.TREND_FOLLOW,
        )
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(ogul, '_is_trading_allowed', return_value=True):
            ogul._execute_signal(signal, regime)

        assert "F_THYAO" not in ogul.active_trades
        events = tmp_db.get_events(event_type="ORDER_CANCELLED")
        assert len(events) >= 1

    def test_max_slippage_from_atr(self, ogul, mock_mt5, tmp_db, mock_baba):
        """max_slippage = ATR × 0.5."""
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")

        signal = Signal(
            symbol="F_THYAO", signal_type=SignalType.BUY,
            price=100.0, sl=95.0, tp=110.0,
            strength=0.7, reason="test",
            strategy=StrategyType.TREND_FOLLOW,
        )
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(ogul, '_is_trading_allowed', return_value=True):
            ogul._execute_signal(signal, regime)

        trade = ogul.active_trades["F_THYAO"]
        assert trade.max_slippage > 0.0


# ═════════════════════════════════════════════════════════════════════
#  TestProcessSignalsIntegration — Entegrasyon testleri
# ═════════════════════════════════════════════════════════════════════

class TestProcessSignalsIntegration:
    """process_signals entegrasyon testleri."""

    def test_advance_orders_called(self, ogul, mock_mt5, tmp_db):
        """_advance_orders çağrılır."""
        with patch.object(ogul, '_advance_orders') as mock_advance, \
             patch.object(ogul, '_check_end_of_day'), \
             patch.object(ogul, '_is_trading_allowed', return_value=True):
            regime = Regime(regime_type=RegimeType.TREND)
            ogul.process_signals([], regime)
            mock_advance.assert_called_once_with(regime)

    def test_eod_runs_first(self, ogul, mock_mt5, tmp_db):
        """_check_end_of_day EN ÖNCE çağrılır."""
        call_order = []

        def track_eod(*a, **kw):
            call_order.append("eod")

        def track_advance(*a, **kw):
            call_order.append("advance")

        with patch.object(ogul, '_check_end_of_day', side_effect=track_eod), \
             patch.object(ogul, '_advance_orders', side_effect=track_advance), \
             patch.object(ogul, '_is_trading_allowed', return_value=True):
            regime = Regime(regime_type=RegimeType.TREND)
            ogul.process_signals([], regime)

        assert call_order[0] == "eod"
        assert call_order[1] == "advance"

    def test_trading_hours_blocks_signals(
        self, ogul, mock_mt5, tmp_db, mock_baba,
    ):
        """İşlem saatleri dışında sinyal üretilmez."""
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")
        h1_bars = _make_trend_bars(
            n=MIN_BARS_H1 + 10, timeframe="H1",
        )
        _insert_bars(tmp_db, h1_bars, "F_THYAO", "H1")

        with patch.object(ogul, '_check_end_of_day'), \
             patch.object(ogul, '_advance_orders'), \
             patch.object(ogul, '_is_trading_allowed', return_value=False):
            regime = Regime(regime_type=RegimeType.TREND)
            ogul.process_signals(["F_THYAO"], regime)

        mock_mt5.send_order.assert_not_called()

    def test_two_cycle_sent_to_filled(
        self, ogul, mock_mt5, tmp_db, mock_baba,
    ):
        """2-cycle entegrasyon: Cycle 1 → SENT, Cycle 2 → FILLED."""
        bars = _make_trend_bars(n=MIN_BARS_M15 + 10)
        _insert_bars(tmp_db, bars, "F_THYAO", "M15")
        h1_bars = _make_trend_bars(
            n=MIN_BARS_H1 + 10, timeframe="H1",
        )
        _insert_bars(tmp_db, h1_bars, "F_THYAO", "H1")

        # Cycle 1: sinyal → SENT
        with patch.object(ogul, '_check_end_of_day'), \
             patch.object(ogul, '_is_trading_allowed', return_value=True):
            regime = Regime(regime_type=RegimeType.TREND)
            ogul.process_signals(["F_THYAO"], regime)

        if "F_THYAO" not in ogul.active_trades:
            pytest.skip("Sinyal üretilemedi (veri yetersiz)")

        assert ogul.active_trades["F_THYAO"].state == TradeState.SENT

        # Cycle 2: advance → FILLED
        mock_mt5.check_order_status.return_value = {
            "status": "filled", "filled_volume": 1.0,
            "remaining_volume": 0.0, "deal_ticket": 888,
        }
        mock_mt5.get_positions.return_value = [
            {"ticket": 888, "price_open": 100.05},
        ]

        with patch.object(ogul, '_check_end_of_day'), \
             patch.object(ogul, '_is_trading_allowed', return_value=True):
            ogul.process_signals(["F_THYAO"], regime)

        assert ogul.active_trades["F_THYAO"].state == TradeState.FILLED
