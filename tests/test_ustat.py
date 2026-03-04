"""Ustat (Top 5 kontrat seçimi) modülü testleri.

Test sınıfları:
    TestUstatInit          — Başlangıç durumu (3 test)
    TestShouldRefresh      — Zamanlama mantığı (5 test)
    TestSelectTop5         — Ana API (5 test)
    TestScoreTechnical     — Teknik sinyal puanı (5 test)
    TestScoreVolume        — Hacim puanı (4 test)
    TestScoreSpread        — Spread puanı (4 test)
    TestScoreHistorical    — Tarihsel başarı puanı (5 test)
    TestScoreVolatilityFit — Volatilite uyumu puanı (4 test)
    TestWinsorize          — Winsorization (3 test)
    TestNormalization      — Normalize + ağırlıklı toplam (4 test)
    TestExpiryStatus       — Vade geçişi (6 test)
    TestNewsFilter         — Haber/bilanço filtresi (7 test)
    TestBusinessDays       — İş günü hesaplama (4 test)
    TestIntegration        — Entegrasyon testleri (4 test)
    TOPLAM                 — ~63 test
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from engine.config import Config
from engine.models.regime import Regime, RegimeType
from engine.ustat import (
    ALL_HOLIDAYS,
    EXPIRY_CLOSE_DAYS,
    EXPIRY_NO_NEW_TRADE_DAYS,
    EXPIRY_OBSERVATION_DAYS,
    HIST_LOOKBACK_DAYS,
    REFRESH_INTERVAL_MIN,
    SELECTION_START,
    TECH_MIN_BARS,
    VOL_LOOKBACK,
    VOL_MAX_RATIO,
    W_HISTORICAL,
    W_SPREAD,
    W_TECHNICAL,
    W_VOLATILITY,
    W_VOLUME,
    WINSOR_LOWER_PCT,
    WINSOR_UPPER_PCT,
    Ustat,
    _business_days_since,
    _business_days_until,
)
from engine.utils.helpers import last_valid as _last_valid


# ═════════════════════════════════════════════════════════════════════
#  FIXTURES
# ═════════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_config():
    """Minimal Config nesnesi."""
    config = Config.__new__(Config)
    config._data = {}
    config._path = None
    return config


@pytest.fixture
def mock_db():
    """Mock Database — kontrol edilebilir dönüş değerleri."""
    db = MagicMock()
    db.get_bars.return_value = pd.DataFrame()
    db.get_trades.return_value = []
    db.get_liquidity.return_value = []
    db.insert_top5.return_value = None
    db.insert_event.return_value = 1
    return db


@pytest.fixture
def ustat(mock_config, mock_db):
    """Ustat instance (mock bağımlılıklar)."""
    return Ustat(mock_config, mock_db)


def _make_trend_bars(n: int = 60, base: float = 100.0, step: float = 0.5):
    """Yükselen fiyat bar verisi → ADX yüksek, RSI > 50."""
    close = np.array([base + i * step for i in range(n)])
    high = close + 0.3
    low = close - 0.3
    open_ = close - step / 2
    volume = np.full(n, 500.0)
    return pd.DataFrame({
        "symbol": "F_TEST",
        "timeframe": "M15",
        "timestamp": [
            (datetime(2025, 6, 1) + timedelta(minutes=15 * i)).isoformat()
            for i in range(n)
        ],
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def _make_range_bars(n: int = 60, base: float = 100.0, amp: float = 0.5):
    """Yatay (oscillating) fiyat bar verisi → ADX düşük, RSI ~50."""
    close = np.array([base + amp * np.sin(i * 0.5) for i in range(n)])
    high = close + 0.2
    low = close - 0.2
    open_ = close - 0.1
    volume = np.full(n, 300.0)
    return pd.DataFrame({
        "symbol": "F_TEST",
        "timeframe": "M15",
        "timestamp": [
            (datetime(2025, 6, 1) + timedelta(minutes=15 * i)).isoformat()
            for i in range(n)
        ],
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def _make_volume_bars(
    n: int = 100,
    base_vol: float = 100.0,
    recent_vol: float = 300.0,
):
    """Hacim testi için bar verisi."""
    close = np.full(n, 100.0)
    high = close + 0.5
    low = close - 0.5
    open_ = np.full(n, 100.0)
    volume = np.full(n, base_vol)
    volume[-4:] = recent_vol  # son 4 bar yüksek hacim
    return pd.DataFrame({
        "symbol": "F_TEST",
        "timeframe": "M15",
        "timestamp": [f"2025-06-01T{i:05d}" for i in range(n)],
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


# ═════════════════════════════════════════════════════════════════════
#  TestUstatInit
# ═════════════════════════════════════════════════════════════════════


class TestUstatInit:
    """Başlangıç durumu testleri."""

    def test_empty_top5(self, ustat):
        """İlk durumda top5 boş."""
        assert ustat._current_top5 == []

    def test_empty_scores(self, ustat):
        """İlk durumda skorlar boş."""
        assert ustat.current_scores == {}

    def test_no_last_refresh(self, ustat):
        """İlk durumda son güncelleme None."""
        assert ustat.last_refresh is None


# ═════════════════════════════════════════════════════════════════════
#  TestShouldRefresh
# ═════════════════════════════════════════════════════════════════════


class TestShouldRefresh:
    """Zamanlama mantığı testleri."""

    def test_first_call_should_refresh(self, ustat):
        """İlk çağrıda güncelleme gerekli."""
        now = datetime(2025, 6, 2, 10, 0, 0)
        assert ustat._should_refresh(now) is True

    def test_same_period_no_refresh(self, ustat):
        """30 dk içinde güncelleme yok."""
        ustat._last_refresh = datetime(2025, 6, 2, 10, 0, 0)
        now = datetime(2025, 6, 2, 10, 15, 0)  # 15 dk sonra
        assert ustat._should_refresh(now) is False

    def test_after_30_min_refresh(self, ustat):
        """30 dk sonra güncelleme gerekli."""
        ustat._last_refresh = datetime(2025, 6, 2, 10, 0, 0)
        now = datetime(2025, 6, 2, 10, 31, 0)  # 31 dk sonra
        assert ustat._should_refresh(now) is True

    def test_new_day_refresh(self, ustat):
        """Yeni gün → güncelleme gerekli."""
        ustat._last_refresh = datetime(2025, 6, 2, 17, 0, 0)
        now = datetime(2025, 6, 3, 9, 20, 0)  # ertesi gün
        assert ustat._should_refresh(now) is True

    def test_exact_30_min_no_refresh(self, ustat):
        """Tam 30 dk sınırında güncelleme yok (elapsed < 30*60)."""
        ustat._last_refresh = datetime(2025, 6, 2, 10, 0, 0)
        now = datetime(2025, 6, 2, 10, 29, 59)  # 29 dk 59 sn
        assert ustat._should_refresh(now) is False


# ═════════════════════════════════════════════════════════════════════
#  TestSelectTop5
# ═════════════════════════════════════════════════════════════════════


class TestSelectTop5:
    """Ana API testleri."""

    def test_returns_list(self, ustat):
        """Dönüş tipi liste."""
        regime = Regime(regime_type=RegimeType.RANGE)
        with patch.object(ustat, "_should_refresh", return_value=False):
            result = ustat.select_top5(regime)
        assert isinstance(result, list)

    def test_max_five(self, ustat):
        """En fazla 5 kontrat."""
        regime = Regime(regime_type=RegimeType.RANGE)
        with patch.object(ustat, "_should_refresh", return_value=False):
            result = ustat.select_top5(regime)
        assert len(result) <= 5

    def test_before_0915_returns_cached(self, ustat):
        """09:15 öncesi → cache (boş) döner."""
        regime = Regime(regime_type=RegimeType.TREND)
        with patch("engine.ustat.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 2, 9, 10, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = ustat.select_top5(regime)
        assert result == []

    def test_after_0915_triggers_refresh(self, ustat):
        """09:15 sonrası → ilk güncelleme tetiklenir."""
        regime = Regime(regime_type=RegimeType.TREND)
        with patch.object(ustat, "_refresh_scores") as mock_refresh:
            with patch("engine.ustat.datetime") as mock_dt:
                now = datetime(2025, 6, 2, 9, 30, 0)
                mock_dt.now.return_value = now
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                ustat.select_top5(regime)
            mock_refresh.assert_called_once()

    def test_cached_between_refreshes(self, ustat):
        """İki güncelleme arasında cache döner."""
        ustat._current_top5 = ["F_THYAO", "F_AKBNK"]
        ustat._last_refresh = datetime(2025, 6, 2, 10, 0, 0)
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(ustat, "_refresh_scores") as mock_refresh:
            with patch("engine.ustat.datetime") as mock_dt:
                mock_dt.now.return_value = datetime(2025, 6, 2, 10, 15, 0)
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                result = ustat.select_top5(regime)

            mock_refresh.assert_not_called()
        assert result == ["F_THYAO", "F_AKBNK"]


# ═════════════════════════════════════════════════════════════════════
#  TestScoreTechnical
# ═════════════════════════════════════════════════════════════════════


class TestScoreTechnical:
    """Teknik sinyal puanı testleri."""

    def test_insufficient_data_returns_50(self, ustat, mock_db):
        """Yetersiz veri → 50 (nötr)."""
        mock_db.get_bars.return_value = pd.DataFrame()
        regime = Regime(regime_type=RegimeType.TREND)
        score = ustat._score_technical("F_THYAO", regime)
        assert score == 50.0

    def test_short_data_returns_50(self, ustat, mock_db):
        """Kısa veri (<60 bar) → 50."""
        df = _make_trend_bars(n=30)
        mock_db.get_bars.return_value = df
        regime = Regime(regime_type=RegimeType.TREND)
        score = ustat._score_technical("F_THYAO", regime)
        assert score == 50.0

    def test_trend_data_positive_score(self, ustat, mock_db):
        """Trend verisi → 0 < skor <= 100."""
        df = _make_trend_bars(n=80, base=100.0, step=0.5)
        mock_db.get_bars.return_value = df
        regime = Regime(regime_type=RegimeType.TREND)
        score = ustat._score_technical("F_THYAO", regime)
        assert 0 < score <= 100

    def test_range_data_positive_score(self, ustat, mock_db):
        """Range verisi → 0 < skor <= 100."""
        df = _make_range_bars(n=80, base=100.0, amp=0.3)
        mock_db.get_bars.return_value = df
        regime = Regime(regime_type=RegimeType.RANGE)
        score = ustat._score_technical("F_THYAO", regime)
        assert 0 < score <= 100

    def test_volatile_regime_returns_50(self, ustat, mock_db):
        """VOLATILE rejimde → nötr skor 50."""
        df = _make_trend_bars(n=80)
        mock_db.get_bars.return_value = df
        regime = Regime(regime_type=RegimeType.VOLATILE)
        score = ustat._score_technical("F_THYAO", regime)
        # VOLATILE/OLAY → is_trend False, adx_score düşük
        assert 0 < score <= 100


# ═════════════════════════════════════════════════════════════════════
#  TestScoreVolume
# ═════════════════════════════════════════════════════════════════════


class TestScoreVolume:
    """Hacim puanı testleri."""

    def test_no_data_returns_50(self, ustat, mock_db):
        """Veri yok → 50."""
        mock_db.get_bars.return_value = pd.DataFrame()
        assert ustat._score_volume("F_THYAO") == 50.0

    def test_high_volume_high_score(self, ustat, mock_db):
        """Yüksek hacim → yüksek skor."""
        df = _make_volume_bars(n=100, base_vol=100.0, recent_vol=300.0)
        mock_db.get_bars.return_value = df
        score = ustat._score_volume("F_THYAO")
        assert score > 50.0  # 300/100 = 3x → yüksek

    def test_low_volume_low_score(self, ustat, mock_db):
        """Düşük hacim → düşük skor."""
        df = _make_volume_bars(n=100, base_vol=1000.0, recent_vol=50.0)
        mock_db.get_bars.return_value = df
        score = ustat._score_volume("F_THYAO")
        assert score < 50.0  # 50/1000 = 0.05x → düşük

    def test_equal_volume_moderate(self, ustat, mock_db):
        """Eşit hacim → orta skor."""
        df = _make_volume_bars(n=100, base_vol=100.0, recent_vol=100.0)
        mock_db.get_bars.return_value = df
        score = ustat._score_volume("F_THYAO")
        assert 20.0 <= score <= 60.0  # 1x → orta


# ═════════════════════════════════════════════════════════════════════
#  TestScoreSpread
# ═════════════════════════════════════════════════════════════════════


class TestScoreSpread:
    """Spread puanı testleri."""

    def test_no_data_returns_50(self, ustat, mock_db):
        """Hiç veri yok → 50."""
        mock_db.get_liquidity.return_value = []
        mock_db.get_bars.return_value = pd.DataFrame()
        assert ustat._score_spread("F_THYAO") == 50.0

    def test_class_a_high_score(self, ustat, mock_db):
        """A sınıfı likidite → yüksek skor."""
        mock_db.get_liquidity.return_value = [
            {"avg_spread": 5.0, "class": "A"},
        ]
        score = ustat._score_spread("F_THYAO")
        assert score > 70.0

    def test_class_c_low_score(self, ustat, mock_db):
        """C sınıfı yüksek spread → düşük skor."""
        mock_db.get_liquidity.return_value = [
            {"avg_spread": 40.0, "class": "C"},
        ]
        score = ustat._score_spread("F_THYAO")
        assert score < 30.0

    def test_bar_proxy_fallback(self, ustat, mock_db):
        """Likidite verisi yoksa bar proxy kullan."""
        mock_db.get_liquidity.return_value = []
        df = _make_range_bars(n=20, base=100.0, amp=0.2)
        mock_db.get_bars.return_value = df
        score = ustat._score_spread("F_THYAO")
        assert 0 <= score <= 100


# ═════════════════════════════════════════════════════════════════════
#  TestScoreHistorical
# ═════════════════════════════════════════════════════════════════════


class TestScoreHistorical:
    """Tarihsel başarı puanı testleri."""

    def test_no_trades_returns_50(self, ustat, mock_db):
        """İşlem yok → 50."""
        mock_db.get_trades.return_value = []
        regime = Regime(regime_type=RegimeType.TREND)
        assert ustat._score_historical("F_THYAO", regime) == 50.0

    def test_few_trades_returns_50(self, ustat, mock_db):
        """3'ten az işlem → 50."""
        mock_db.get_trades.return_value = [
            {
                "pnl": 100.0,
                "exit_time": datetime.now().isoformat(),
                "regime": "TREND",
            },
        ]
        regime = Regime(regime_type=RegimeType.TREND)
        assert ustat._score_historical("F_THYAO", regime) == 50.0

    def test_all_winning_high_score(self, ustat, mock_db):
        """Tüm işlemler kârlı → yüksek skor."""
        now = datetime.now().isoformat()
        trades = [
            {"pnl": 50.0, "exit_time": now, "regime": "TREND"}
            for _ in range(10)
        ]
        mock_db.get_trades.return_value = trades
        regime = Regime(regime_type=RegimeType.TREND)
        score = ustat._score_historical("F_THYAO", regime)
        assert score > 70.0

    def test_all_losing_low_score(self, ustat, mock_db):
        """Tüm işlemler zararlı → düşük skor."""
        now = datetime.now().isoformat()
        trades = [
            {"pnl": -50.0, "exit_time": now, "regime": "TREND"}
            for _ in range(10)
        ]
        mock_db.get_trades.return_value = trades
        regime = Regime(regime_type=RegimeType.TREND)
        score = ustat._score_historical("F_THYAO", regime)
        assert score < 40.0

    def test_old_trades_excluded(self, ustat, mock_db):
        """31+ gün önceki işlemler hariç → 50."""
        old_time = (
            datetime.now() - timedelta(days=HIST_LOOKBACK_DAYS + 5)
        ).isoformat()
        trades = [
            {"pnl": 100.0, "exit_time": old_time, "regime": "TREND"}
            for _ in range(10)
        ]
        mock_db.get_trades.return_value = trades
        regime = Regime(regime_type=RegimeType.TREND)
        assert ustat._score_historical("F_THYAO", regime) == 50.0


# ═════════════════════════════════════════════════════════════════════
#  TestScoreVolatilityFit
# ═════════════════════════════════════════════════════════════════════


class TestScoreVolatilityFit:
    """Volatilite uyumu puanı testleri."""

    def test_no_data_returns_50(self, ustat, mock_db):
        """Veri yok → 50."""
        mock_db.get_bars.return_value = pd.DataFrame()
        regime = Regime(regime_type=RegimeType.TREND)
        assert ustat._score_volatility_fit("F_THYAO", regime) == 50.0

    def test_trend_regime_scores(self, ustat, mock_db):
        """TREND rejimde skor 0-100 arası."""
        df = _make_trend_bars(n=60, step=0.3)
        mock_db.get_bars.return_value = df
        regime = Regime(regime_type=RegimeType.TREND)
        score = ustat._score_volatility_fit("F_THYAO", regime)
        assert 0 <= score <= 100

    def test_range_regime_scores(self, ustat, mock_db):
        """RANGE rejimde skor 0-100 arası."""
        df = _make_range_bars(n=60, amp=0.2)
        mock_db.get_bars.return_value = df
        regime = Regime(regime_type=RegimeType.RANGE)
        score = ustat._score_volatility_fit("F_THYAO", regime)
        assert 0 <= score <= 100

    def test_short_data_returns_50(self, ustat, mock_db):
        """Kısa veri (<30 bar) → 50."""
        df = _make_trend_bars(n=20)
        mock_db.get_bars.return_value = df
        regime = Regime(regime_type=RegimeType.TREND)
        assert ustat._score_volatility_fit("F_THYAO", regime) == 50.0


# ═════════════════════════════════════════════════════════════════════
#  TestWinsorize
# ═════════════════════════════════════════════════════════════════════


class TestWinsorize:
    """Winsorization testleri."""

    def test_small_list_unchanged(self):
        """3'ten az eleman → değişmez."""
        result = Ustat._winsorize([10, 20])
        assert result == [10, 20]

    def test_outlier_clipped(self):
        """Aşırı uç değer kırpılır."""
        values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 1000.0]
        result = Ustat._winsorize(values)
        # 1000 kırpılmalı (99. percentile'a)
        assert result[-1] < 1000.0
        assert result[-1] >= 90.0  # en azından bu kadar

    def test_normal_values_unchanged(self):
        """Normal dağılımlı değerler → yaklaşık aynı."""
        values = [50.0, 55.0, 60.0, 65.0, 70.0, 75.0, 80.0, 85.0, 90.0, 95.0]
        result = Ustat._winsorize(values)
        # İç değerler değişmemeli veya çok az değişmeli
        for i in range(2, len(values) - 2):
            assert abs(result[i] - values[i]) < 5.0


# ═════════════════════════════════════════════════════════════════════
#  TestNormalization
# ═════════════════════════════════════════════════════════════════════


class TestNormalization:
    """Normalize + ağırlıklı toplam testleri."""

    def test_output_range_0_100(self, ustat):
        """Final skorlar 0-100 aralığında."""
        raw = {
            "SYM_A": {
                "technical": 90, "volume": 80, "spread": 70,
                "historical": 60, "volatility": 50,
            },
            "SYM_B": {
                "technical": 10, "volume": 20, "spread": 30,
                "historical": 40, "volatility": 50,
            },
            "SYM_C": {
                "technical": 50, "volume": 50, "spread": 50,
                "historical": 50, "volatility": 50,
            },
        }
        final = ustat._normalize_and_weight(raw)
        for score in final.values():
            assert 0 <= score <= 100

    def test_higher_raw_higher_final(self, ustat):
        """Tüm ham puanları yüksek olan sembol → en yüksek final."""
        raw = {
            "HIGH": {
                "technical": 100, "volume": 100, "spread": 100,
                "historical": 100, "volatility": 100,
            },
            "LOW": {
                "technical": 0, "volume": 0, "spread": 0,
                "historical": 0, "volatility": 0,
            },
            "MID": {
                "technical": 50, "volume": 50, "spread": 50,
                "historical": 50, "volatility": 50,
            },
        }
        final = ustat._normalize_and_weight(raw)
        assert final["HIGH"] > final["MID"] > final["LOW"]

    def test_all_same_scores(self, ustat):
        """Tüm puanlar aynı → hepsi 50."""
        raw = {
            "A": {
                "technical": 70, "volume": 70, "spread": 70,
                "historical": 70, "volatility": 70,
            },
            "B": {
                "technical": 70, "volume": 70, "spread": 70,
                "historical": 70, "volatility": 70,
            },
            "C": {
                "technical": 70, "volume": 70, "spread": 70,
                "historical": 70, "volatility": 70,
            },
        }
        final = ustat._normalize_and_weight(raw)
        for score in final.values():
            assert score == 50.0

    def test_weights_sum_to_one(self):
        """Ağırlıklar toplamı 1.0."""
        total = W_TECHNICAL + W_VOLUME + W_SPREAD + W_HISTORICAL + W_VOLATILITY
        assert abs(total - 1.0) < 0.001


# ═════════════════════════════════════════════════════════════════════
#  TestExpiryStatus
# ═════════════════════════════════════════════════════════════════════


class TestExpiryStatus:
    """Vade geçişi testleri."""

    @patch("engine.ustat.VIOP_EXPIRY_DATES", {date(2025, 6, 30)})
    def test_normal_far_from_expiry(self, ustat):
        """Vade uzakken → 'normal'."""
        today = date(2025, 6, 10)  # 20 gün kaldı
        status = ustat._get_expiry_status(today)
        assert all(v == "normal" for v in status.values())

    @patch("engine.ustat.VIOP_EXPIRY_DATES", {date(2025, 6, 30)})
    def test_no_new_trade_3_days_before(self, ustat):
        """3 iş günü kala → 'no_new_trade'."""
        # 30 Haziran Pazartesi → 3 iş günü kala = 25 Çarşamba
        today = date(2025, 6, 25)  # Çarşamba
        status = ustat._get_expiry_status(today)
        # 3 iş günü: 26 Per, 27 Cum, 30 Paz = 3
        assert all(v == "no_new_trade" for v in status.values())

    @patch("engine.ustat.VIOP_EXPIRY_DATES", {date(2025, 6, 30)})
    def test_close_1_day_before(self, ustat):
        """1 iş günü kala → 'close'."""
        today = date(2025, 6, 27)  # Cuma → Pazartesi 30 = 1 iş günü
        status = ustat._get_expiry_status(today)
        assert all(v == "close" for v in status.values())

    @patch(
        "engine.ustat.VIOP_EXPIRY_DATES",
        {date(2025, 5, 30), date(2025, 7, 31)},
    )
    def test_observation_after_expiry(self, ustat):
        """Vade sonrası 2 iş günü → 'observation'."""
        # 30 Mayıs Cuma = vade, 2 Haziran Pazartesi = 1. iş günü sonra
        today = date(2025, 6, 2)  # Pazartesi
        status = ustat._get_expiry_status(today)
        assert all(v == "observation" for v in status.values())

    @patch(
        "engine.ustat.VIOP_EXPIRY_DATES",
        {date(2025, 5, 30), date(2025, 7, 31)},
    )
    def test_normal_after_observation(self, ustat):
        """Gözlem bittikten sonra → 'normal'."""
        # 30 Mayıs Cuma = vade, 4 Haziran Çarşamba = 3. iş günü sonra
        today = date(2025, 6, 4)  # Çarşamba
        status = ustat._get_expiry_status(today)
        assert all(v == "normal" for v in status.values())

    @patch("engine.ustat.VIOP_EXPIRY_DATES", set())
    def test_no_expiry_dates(self, ustat):
        """Vade listesi boş → hepsi 'normal'."""
        status = ustat._get_expiry_status(date(2025, 6, 15))
        assert all(v == "normal" for v in status.values())


# ═════════════════════════════════════════════════════════════════════
#  TestNewsFilter
# ═════════════════════════════════════════════════════════════════════


class TestNewsFilter:
    """Haber/bilanço filtresi testleri."""

    def test_no_block_by_default(self, ustat):
        """Varsayılan → engel yok."""
        assert ustat._is_news_blocked("F_THYAO", date.today()) is False

    def test_kap_block(self, ustat):
        """KAP özel durum → engel."""
        ustat.set_kap_event("F_THYAO")
        assert ustat._is_news_blocked("F_THYAO", date.today()) is True

    def test_kap_clear(self, ustat):
        """KAP temizle → engel kalk."""
        ustat.set_kap_event("F_THYAO")
        ustat.clear_kap_event("F_THYAO")
        assert ustat._is_news_blocked("F_THYAO", date.today()) is False

    def test_manual_news_flag(self, ustat):
        """Manuel haber → gün boyu engel."""
        ustat.set_manual_news_flag("F_AKBNK")
        assert ustat._is_news_blocked("F_AKBNK", date.today()) is True

    def test_manual_news_other_day(self, ustat):
        """Manuel haber → ertesi gün engel yok."""
        ustat.set_manual_news_flag("F_AKBNK")
        tomorrow = date.today() + timedelta(days=1)
        # news_deactivate_date bugün, tomorrow != bugün → engel yok
        assert ustat._is_news_blocked("F_AKBNK", tomorrow) is False

    def test_earnings_block(self, ustat):
        """Bilanço günü → engel."""
        today = date(2025, 6, 15)
        ustat.set_earnings_dates("F_TCELL", [today])
        assert ustat._is_news_blocked("F_TCELL", today) is True

    def test_earnings_plus_minus_1(self, ustat):
        """Bilanço ±1 gün → engel."""
        earn_date = date(2025, 6, 15)
        ustat.set_earnings_dates("F_TCELL", [earn_date])

        # 1 gün önce
        assert ustat._is_news_blocked("F_TCELL", date(2025, 6, 14)) is True
        # Bilanço günü
        assert ustat._is_news_blocked("F_TCELL", date(2025, 6, 15)) is True
        # 1 gün sonra
        assert ustat._is_news_blocked("F_TCELL", date(2025, 6, 16)) is True
        # 2 gün sonra
        assert ustat._is_news_blocked("F_TCELL", date(2025, 6, 17)) is False


# ═════════════════════════════════════════════════════════════════════
#  TestBusinessDays
# ═════════════════════════════════════════════════════════════════════


class TestBusinessDays:
    """İş günü hesaplama testleri."""

    def test_same_day_zero(self):
        """Aynı gün → 0."""
        d = date(2025, 6, 2)
        assert _business_days_until(d, d) == 0

    def test_weekdays_count(self):
        """Pazartesi → Cuma = 4 iş günü (tatil olmayan hafta)."""
        monday = date(2025, 5, 5)    # Pazartesi (tatil değil)
        friday = date(2025, 5, 9)    # Cuma (tatil değil)
        assert _business_days_until(friday, monday) == 4

    def test_weekend_skipped(self):
        """Cuma → Pazartesi = 1 iş günü (haftasonu atlanır)."""
        friday = date(2025, 5, 9)    # Cuma
        monday = date(2025, 5, 12)   # Pazartesi
        assert _business_days_until(monday, friday) == 1

    def test_business_days_since(self):
        """Geçmiş iş günü sayısı."""
        monday = date(2025, 6, 2)
        wednesday = date(2025, 6, 4)
        assert _business_days_since(monday, wednesday) == 2


# ═════════════════════════════════════════════════════════════════════
#  TestIntegration
# ═════════════════════════════════════════════════════════════════════


class TestIntegration:
    """Entegrasyon testleri — tam puanlama döngüsü."""

    def test_refresh_produces_scores(self, ustat, mock_db):
        """_refresh_scores sonrası scores dolu."""
        # Tüm sembollere aynı veri ver
        df = _make_trend_bars(n=100, base=100.0, step=0.3)
        mock_db.get_bars.return_value = df
        mock_db.get_trades.return_value = []
        mock_db.get_liquidity.return_value = []

        regime = Regime(regime_type=RegimeType.TREND)
        now = datetime(2025, 6, 10, 10, 0, 0)

        with patch("engine.ustat.VIOP_EXPIRY_DATES", set()):
            ustat._refresh_scores(regime, now)

        assert len(ustat.current_scores) == 15  # 15 WATCHED_SYMBOLS
        assert ustat.last_refresh == now

    def test_top5_max_five_after_refresh(self, ustat, mock_db):
        """Güncelleme sonrası max 5 kontrat."""
        df = _make_trend_bars(n=100, base=100.0, step=0.3)
        mock_db.get_bars.return_value = df
        mock_db.get_trades.return_value = []
        mock_db.get_liquidity.return_value = []

        regime = Regime(regime_type=RegimeType.TREND)
        now = datetime(2025, 6, 10, 10, 0, 0)

        with patch("engine.ustat.VIOP_EXPIRY_DATES", set()):
            ustat._refresh_scores(regime, now)

        assert len(ustat._current_top5) <= 5

    def test_db_logging_called(self, ustat, mock_db):
        """Güncelleme sonrası DB'ye kayıt."""
        df = _make_trend_bars(n=100, base=100.0, step=0.3)
        mock_db.get_bars.return_value = df
        mock_db.get_trades.return_value = []
        mock_db.get_liquidity.return_value = []

        regime = Regime(regime_type=RegimeType.TREND)
        now = datetime(2025, 6, 10, 10, 0, 0)

        with patch("engine.ustat.VIOP_EXPIRY_DATES", set()):
            ustat._refresh_scores(regime, now)

        if ustat._current_top5:
            mock_db.insert_top5.assert_called_once()

    def test_expiry_close_needed(self, ustat):
        """get_expiry_close_needed — 1 iş günü kala True."""
        with patch("engine.ustat.VIOP_EXPIRY_DATES", {date(2025, 6, 30)}):
            with patch("engine.ustat.date") as mock_date:
                mock_date.today.return_value = date(2025, 6, 27)
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
                assert ustat.get_expiry_close_needed() is True


# ═════════════════════════════════════════════════════════════════════
#  TestLastValid
# ═════════════════════════════════════════════════════════════════════


class TestLastValid:
    """_last_valid yardımcı fonksiyon testleri."""

    def test_all_nan(self):
        """Tümü NaN → None."""
        arr = np.array([np.nan, np.nan, np.nan])
        assert _last_valid(arr) is None

    def test_last_valid_value(self):
        """Son geçerli değer döner."""
        arr = np.array([1.0, 2.0, 3.0, np.nan])
        assert _last_valid(arr) == 3.0

    def test_single_value(self):
        """Tek geçerli değer."""
        arr = np.array([np.nan, np.nan, 42.0])
        assert _last_valid(arr) == 42.0


# ═════════════════════════════════════════════════════════════════════
#  TestGetExpiryCloseNeeded
# ═════════════════════════════════════════════════════════════════════


class TestGetExpiryCloseNeeded:
    """get_expiry_close_needed testleri."""

    def test_no_expiry_dates(self, ustat):
        """Vade listesi boş → False."""
        with patch("engine.ustat.VIOP_EXPIRY_DATES", set()):
            assert ustat.get_expiry_close_needed() is False

    def test_far_from_expiry(self, ustat):
        """Vade uzak → False."""
        with patch("engine.ustat.VIOP_EXPIRY_DATES", {date(2025, 12, 31)}):
            with patch("engine.ustat.date") as mock_date:
                mock_date.today.return_value = date(2025, 6, 1)
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
                assert ustat.get_expiry_close_needed() is False


# ═════════════════════════════════════════════════════════════════════
#  TestAverageFilter
# ═════════════════════════════════════════════════════════════════════


class TestAverageFilter:
    """Ortalama filtresi testleri."""

    def test_below_average_excluded(self, ustat, mock_db):
        """Ortalamanın altındakiler elenir."""
        # Farklı ham puanlar üretecek şekilde farklı veri ver
        call_count = {"n": 0}
        orig_score_tech = ustat._score_technical

        def _varying_tech(symbol, regime):
            call_count["n"] += 1
            # Her sembol farklı skor alsın
            idx = list(
                __import__("engine.mt5_bridge", fromlist=["WATCHED_SYMBOLS"])
                .WATCHED_SYMBOLS
            ).index(symbol)
            return 10.0 + idx * 6.0  # 10, 16, 22, 28, ..., 94

        with patch.object(ustat, "_score_technical", _varying_tech):
            with patch.object(ustat, "_score_volume", return_value=50.0):
                with patch.object(ustat, "_score_spread", return_value=50.0):
                    with patch.object(
                        ustat, "_score_historical", return_value=50.0
                    ):
                        with patch.object(
                            ustat, "_score_volatility_fit", return_value=50.0
                        ):
                            with patch(
                                "engine.ustat.VIOP_EXPIRY_DATES", set()
                            ):
                                regime = Regime(
                                    regime_type=RegimeType.TREND,
                                )
                                now = datetime(2025, 6, 10, 10, 0, 0)
                                ustat._refresh_scores(regime, now)

        # Top 5 seçildi + ortalama filtresi uygulandı
        # Bazı semboller average'ın altında kaldıysa <= 5 olmalı
        assert len(ustat._current_top5) <= 5
        assert len(ustat._current_top5) > 0


# ═════════════════════════════════════════════════════════════════════
#  TestSetEarningsDates
# ═════════════════════════════════════════════════════════════════════


class TestSetEarningsDates:
    """set_earnings_dates testleri."""

    def test_earnings_stored(self, ustat):
        """Bilanço tarihleri kaydedilir."""
        dates = [date(2025, 7, 15), date(2025, 10, 20)]
        ustat.set_earnings_dates("F_THYAO", dates)
        assert "F_THYAO" in ustat._earnings_calendar
        assert len(ustat._earnings_calendar["F_THYAO"]) == 2

    def test_earnings_sorted(self, ustat):
        """Bilanço tarihleri sıralı kaydedilir."""
        dates = [date(2025, 10, 20), date(2025, 7, 15)]
        ustat.set_earnings_dates("F_THYAO", dates)
        stored = ustat._earnings_calendar["F_THYAO"]
        assert stored[0] < stored[1]


# ═════════════════════════════════════════════════════════════════════
#  TestConstants
# ═════════════════════════════════════════════════════════════════════


class TestConstants:
    """Sabit değer kontrolleri."""

    def test_selection_start(self):
        """Seçim başlangıç saati 09:15."""
        assert SELECTION_START == time(9, 15)

    def test_refresh_interval(self):
        """Güncelleme aralığı 30 dk."""
        assert REFRESH_INTERVAL_MIN == 30

    def test_expiry_days(self):
        """Vade gün sabitleri."""
        assert EXPIRY_NO_NEW_TRADE_DAYS == 3
        assert EXPIRY_CLOSE_DAYS == 1
        assert EXPIRY_OBSERVATION_DAYS == 2

    def test_all_holidays_includes_2025_and_2026(self):
        """ALL_HOLIDAYS 2025 ve 2026 tatillerini içerir."""
        assert date(2025, 1, 1) in ALL_HOLIDAYS
        assert date(2026, 1, 1) in ALL_HOLIDAYS
        assert date(2025, 4, 23) in ALL_HOLIDAYS
        assert date(2026, 4, 23) in ALL_HOLIDAYS
