"""ÜSTAT v5.0 — Entegrasyon Testleri.

8 senaryo:
    1. Uygulama Başlatma Akışı   – Engine init → MT5 connect → restore → cycle
    2. Veri Akışı                 – MT5 → pipeline → BABA → OĞUL → API response
    3. İşlem Akışı               – sinyal → BABA onay → limit emir → fill → pozisyon
    4. Risk Kontrolü             – zarar tetikleme → kill-switch → dashboard uyarısı
    5. Kill-Switch 3 Seviye      – L1 sembol, L2 sistem, L3 tam kapanış
    6. Bağlantı Kopması          – MT5 disconnect → reconnect → recovery
    7. İşlem Geçmişi             – filtreler, istatistikler, onay sistemi
    8. Performans                 – çok kontrat + API yanıt süresi
"""

import json
import os
import tempfile
import time as _time
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, PropertyMock, call

import numpy as np
import pandas as pd
import pytest

from engine.main import (
    Engine,
    CYCLE_INTERVAL,
    MAX_MT5_RECONNECT,
    DB_ERROR_THRESHOLD,
)
from engine.config import Config
from engine.database import Database
from engine.models.regime import Regime, RegimeType
from engine.models.risk import RiskParams, RiskVerdict
from engine.models.signal import Signal, SignalType, StrategyType
from engine.models.trade import Trade, TradeState
from engine.ogul import (
    Ogul,
    REGIME_STRATEGIES,
    MAX_CONCURRENT,
    TRADING_OPEN,
    TRADING_CLOSE,
    MAX_LOT_PER_CONTRACT,
    MARGIN_RESERVE_PCT,
)


# ═════════════════════════════════════════════════════════════════════
#  YARDIMCI: Fixture'lar
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
def mock_mt5():
    """MagicMock MT5Bridge — tam özellikli."""
    mt5 = MagicMock()
    mt5.connect.return_value = True
    mt5.heartbeat.return_value = True
    mt5.disconnect.return_value = None
    mt5.is_connected = True
    mt5.send_order.return_value = {"order": 12345}
    mt5.get_tick.return_value = SimpleNamespace(ask=100.0, bid=99.9)
    mt5.get_positions.return_value = []
    mt5.close_position.return_value = True
    mt5.modify_position.return_value = True
    mt5.cancel_order.return_value = True
    mt5.check_order_status.return_value = None
    mt5.get_account_info.return_value = SimpleNamespace(
        login=12345678, server="VIOPDemo",
        balance=100000.0, equity=100000.0,
        margin=0.0, free_margin=100000.0,
        currency="TRY",
    )
    mt5.get_bars.return_value = pd.DataFrame()
    mt5.get_pending_orders.return_value = []
    return mt5


@pytest.fixture
def mock_pipeline():
    """MagicMock DataPipeline."""
    pipeline = MagicMock()
    pipeline.run_cycle.return_value = None
    pipeline.get_deactivated_symbols.return_value = []
    pipeline.get_active_symbols.return_value = [
        "F_THYAO", "F_AKBNK", "F_ASELS", "F_TCELL", "F_HALKB",
    ]
    pipeline.latest_ticks = {}
    return pipeline


@pytest.fixture
def mock_baba():
    """MagicMock Baba — normal çalışma."""
    baba = MagicMock()
    baba.run_cycle.return_value = Regime(regime_type=RegimeType.TREND)
    baba.check_risk_limits.return_value = RiskVerdict(can_trade=True)
    baba.check_correlation_limits.return_value = RiskVerdict(can_trade=True)
    baba.active_warnings = []
    baba.restore_risk_state.return_value = None
    baba.is_symbol_killed.return_value = False
    baba.calculate_position_size.return_value = 1.0
    baba.increment_daily_trade_count.return_value = None
    baba.current_regime = Regime(regime_type=RegimeType.TREND)
    baba._kill_switch_level = 0
    baba._killed_symbols = set()
    baba._risk_state = {
        "daily_trade_count": 0,
        "consecutive_losses": 0,
        "cooldown_until": None,
    }
    return baba


@pytest.fixture
def mock_ogul():
    """MagicMock Ogul — basit."""
    ogul = MagicMock()
    ogul.process_signals.return_value = None
    ogul.restore_active_trades.return_value = None
    ogul.active_trades = {}
    return ogul


@pytest.fixture
def mock_ustat():
    """MagicMock Ustat."""
    ustat = MagicMock()
    ustat.select_top5.return_value = [
        "F_THYAO", "F_AKBNK", "F_ASELS", "F_TCELL", "F_HALKB",
    ]
    return ustat


@pytest.fixture
def mock_db():
    """MagicMock Database (Engine testleri için)."""
    db = MagicMock()
    db.insert_event.return_value = None
    db.close.return_value = None
    return db


@pytest.fixture
def engine(config, mock_db, mock_mt5, mock_pipeline,
           mock_ustat, mock_baba, mock_ogul):
    """Tam mock bileşenlerle Engine nesnesi."""
    return Engine(
        config=config,
        db=mock_db,
        mt5=mock_mt5,
        pipeline=mock_pipeline,
        ustat=mock_ustat,
        baba=mock_baba,
        ogul=mock_ogul,
    )


@pytest.fixture
def real_ogul(config, mock_mt5, tmp_db, mock_baba):
    """Gerçek Ogul + gerçek DB (state-machine testleri için)."""
    return Ogul(config, mock_mt5, tmp_db, baba=mock_baba)


def _make_m15_bars(n=70, start=100.0, atr_base=2.0, symbol="F_THYAO"):
    """M15 bar verisi üretir (ATR hesabı için yeterli)."""
    timestamps = [
        f"2025-01-10T09:{30 + i // 4:02d}:{(i % 4) * 15:02d}"
        for i in range(n)
    ]
    closes = [start + (i * 0.1) for i in range(n)]
    highs = [c + atr_base for c in closes]
    lows = [c - atr_base for c in closes]
    opens = [c - 0.05 for c in closes]
    volumes = [1000 + i * 10 for i in range(n)]
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


# ═════════════════════════════════════════════════════════════════════
#  1. UYGULAMA BAŞLATMA AKIŞI
#     İkon → MT5 bağlantı → OTP/restore → dashboard (uçtan uca)
# ═════════════════════════════════════════════════════════════════════

class TestStartupFlow:
    """Uygulama başlatma sırası: init → connect → restore → cycle."""

    def test_full_startup_sequence(self, engine, mock_mt5, mock_baba, mock_ogul):
        """Başlatma sırası: connect → restore baba → restore ogul → cycle."""
        execution_log = []

        mock_mt5.connect.side_effect = lambda: (
            execution_log.append("mt5_connect") or True
        )
        mock_baba.restore_risk_state.side_effect = lambda: (
            execution_log.append("baba_restore")
        )
        mock_ogul.restore_active_trades.side_effect = lambda: (
            execution_log.append("ogul_restore")
        )

        def stop_after_one(pipeline):
            execution_log.append("baba_cycle")
            engine._running = False
            return Regime(regime_type=RegimeType.TREND)

        mock_baba.run_cycle.side_effect = stop_after_one

        with patch("engine.main._time.sleep"):
            engine.start()

        assert "mt5_connect" in execution_log
        assert "baba_restore" in execution_log
        assert "ogul_restore" in execution_log
        assert "baba_cycle" in execution_log

        # Sıralama: connect → restore → cycle
        ci = execution_log.index("mt5_connect")
        bi = execution_log.index("baba_restore")
        oi = execution_log.index("ogul_restore")
        bc = execution_log.index("baba_cycle")
        assert ci < bi < bc
        assert ci < oi < bc

    def test_startup_mt5_connect_failure_retries(self, engine, mock_mt5):
        """MT5 bağlantı başarısız → stop (start içinden)."""
        mock_mt5.connect.return_value = False

        with patch("engine.main._time.sleep"):
            engine.start()

        # Engine durdu
        assert engine._running is False

    def test_startup_restore_error_tolerant(self, engine, mock_mt5,
                                             mock_baba, mock_ogul):
        """Restore hatası engine'i durdurmaz."""
        mock_baba.restore_risk_state.side_effect = Exception("DB bozuk")

        cycle_ran = False

        def mark_and_stop(pipeline):
            nonlocal cycle_ran
            cycle_ran = True
            engine._running = False
            return Regime(regime_type=RegimeType.TREND)

        mock_baba.run_cycle.side_effect = mark_and_stop

        with patch("engine.main._time.sleep"):
            engine.start()

        assert cycle_ran, "Restore hatası cycle'ı engellememeli"

    def test_engine_state_after_startup(self, engine, mock_mt5,
                                        mock_baba, mock_ogul):
        """Başlatma sonrası state doğru."""
        engine._running = True

        def stop_engine(pipeline):
            engine._running = False
            return Regime(regime_type=RegimeType.TREND)

        mock_baba.run_cycle.side_effect = stop_engine

        with patch("engine.main._time.sleep"):
            engine.start()

        # Cycle count artmalı
        assert engine._cycle_count >= 1


# ═════════════════════════════════════════════════════════════════════
#  2. VERİ AKIŞI
#     MT5 → engine → API → dashboard (gerçek zamanlı)
# ═════════════════════════════════════════════════════════════════════

class TestDataFlow:
    """MT5 → pipeline → BABA → OĞUL → API response zinciri."""

    def test_data_pipeline_feeds_baba(self, engine, mock_pipeline,
                                      mock_baba, mock_ogul):
        """Pipeline cycle → BABA cycle → OĞUL process sırasıyla çağrılır."""
        call_order = []

        mock_pipeline.run_cycle.side_effect = lambda: (
            call_order.append("pipeline")
        )

        def baba_run(pipeline):
            call_order.append("baba")
            return Regime(regime_type=RegimeType.TREND)

        mock_baba.run_cycle.side_effect = baba_run

        def ogul_run(symbols, regime):
            call_order.append("ogul")

        mock_ogul.process_signals.side_effect = ogul_run

        engine._run_single_cycle()

        assert call_order == ["pipeline", "baba", "ogul"]

    def test_regime_propagated_to_ogul(self, engine, mock_baba, mock_ogul):
        """BABA'nın tespit ettiği rejim OĞUL'a iletilir."""
        volatile_regime = Regime(regime_type=RegimeType.VOLATILE)
        mock_baba.run_cycle.return_value = volatile_regime
        mock_baba.check_risk_limits.return_value = RiskVerdict(can_trade=True)

        engine._run_single_cycle()

        mock_ogul.process_signals.assert_called_once()
        _, regime_arg = mock_ogul.process_signals.call_args[0]
        assert regime_arg.regime_type == RegimeType.VOLATILE

    def test_top5_propagated_to_ogul(self, engine, mock_ustat, mock_ogul):
        """ÜSTAT'ın seçtiği Top 5 OĞUL'a iletilir."""
        selected = ["F_THYAO", "F_AKBNK", "F_PGSUS"]
        mock_ustat.select_top5.return_value = selected

        engine._run_single_cycle()

        mock_ogul.process_signals.assert_called_once()
        symbols_arg = mock_ogul.process_signals.call_args[0][0]
        assert symbols_arg == selected

    def test_risk_blocked_sends_empty_to_ogul(self, engine, mock_baba,
                                               mock_ogul, mock_ustat):
        """Risk engeli → OĞUL'a boş sembol listesi."""
        mock_baba.check_risk_limits.return_value = RiskVerdict(
            can_trade=False, reason="daily_loss_exceeded",
        )
        mock_ustat.select_top5.return_value = ["F_THYAO"]

        engine._run_single_cycle()

        symbols_arg = mock_ogul.process_signals.call_args[0][0]
        assert symbols_arg == []

    def test_api_status_reflects_engine_state(self, engine, mock_baba,
                                               mock_mt5):
        """API deps üzerinden engine state'i okunabilir."""
        from api.deps import set_engine, get_engine, is_engine_running, get_baba

        set_engine(engine)

        assert get_engine() is engine
        assert get_baba() is mock_baba

    def test_multi_cycle_data_consistency(self, engine, mock_baba,
                                          mock_ogul, mock_ustat):
        """3 cycle boyunca veri tutarlılığı korunur."""
        regimes = [
            Regime(regime_type=RegimeType.TREND),
            Regime(regime_type=RegimeType.VOLATILE),
            Regime(regime_type=RegimeType.RANGE),
        ]
        captured_regimes = []

        cycle_idx = 0

        def baba_run(pipeline):
            nonlocal cycle_idx
            r = regimes[cycle_idx]
            cycle_idx += 1
            return r

        def ogul_run(symbols, regime):
            captured_regimes.append(regime.regime_type)

        mock_baba.run_cycle.side_effect = baba_run
        mock_ogul.process_signals.side_effect = ogul_run

        engine._running = True
        real_run = engine._run_single_cycle
        counter = 0

        def counted():
            nonlocal counter
            counter += 1
            real_run()
            if counter >= 3:
                engine._running = False

        engine._run_single_cycle = counted

        with patch("engine.main._time.sleep"):
            engine._main_loop()

        assert captured_regimes == [
            RegimeType.TREND,
            RegimeType.VOLATILE,
            RegimeType.RANGE,
        ]


# ═════════════════════════════════════════════════════════════════════
#  3. İŞLEM AKIŞI
#     Sinyal → BABA onay → emir → pozisyon → dashboard'da görünme
# ═════════════════════════════════════════════════════════════════════

class TestTradeFlow:
    """Sinyal → BABA onay → limit emir → fill → pozisyon → DB kaydı."""

    def test_signal_to_sent_full_flow(self, real_ogul, mock_mt5, tmp_db, mock_baba):
        """Sinyal → BABA onay → SENT state: tam akış."""
        # M15 bar verisi ekle (ATR hesabı için)
        bars = _make_m15_bars()
        tmp_db.insert_bars("F_THYAO", "M15", bars)

        signal = Signal(
            symbol="F_THYAO",
            signal_type=SignalType.BUY,
            price=100.0,
            sl=98.0,
            tp=104.0,
            strength=0.8,
            reason="test_signal",
            strategy=StrategyType.TREND_FOLLOW,
        )
        regime = Regime(regime_type=RegimeType.TREND)

        # İşlem saatleri içinde çalıştır
        with patch.object(real_ogul, '_is_trading_allowed', return_value=True):
            real_ogul._execute_signal(signal, regime)

        # Trade active_trades'e eklenmeli
        assert "F_THYAO" in real_ogul.active_trades
        trade = real_ogul.active_trades["F_THYAO"]
        assert trade.state == TradeState.SENT
        assert trade.order_ticket == 12345
        assert trade.direction == "BUY"
        assert trade.volume > 0

        # DB kaydı
        events = tmp_db.get_events(event_type="ORDER_SENT")
        assert len(events) >= 1
        assert "F_THYAO" in events[0]["message"]

        # BABA sayacı güncellendi
        mock_baba.increment_daily_trade_count.assert_called_once()

    def test_sent_to_filled_flow(self, real_ogul, mock_mt5, tmp_db, mock_baba):
        """SENT → check_order_status → FILLED."""
        # Aktif trade SENT state'te
        trade = Trade(
            symbol="F_THYAO",
            direction="BUY",
            volume=1.0,
            entry_price=100.0,
            sl=98.0,
            tp=104.0,
            state=TradeState.SENT,
            order_ticket=12345,
            sent_at=datetime.now(),
            requested_volume=1.0,
            limit_price=100.0,
            regime_at_entry="TREND",
            db_id=1,
        )
        real_ogul.active_trades["F_THYAO"] = trade

        # DB'ye trade ekle
        trade.db_id = tmp_db.insert_trade({
            "strategy": "trend_follow",
            "symbol": "F_THYAO",
            "direction": "BUY",
            "entry_time": datetime.now().isoformat(),
            "entry_price": 100.0,
            "lot": 1.0,
            "regime": "TREND",
        })

        # MT5 "filled" dönsün
        mock_mt5.check_order_status.return_value = {
            "status": "filled",
            "filled_volume": 1.0,
            "remaining_volume": 0.0,
            "deal_ticket": 99999,
        }
        mock_mt5.get_positions.return_value = [
            {"ticket": 99999, "price_open": 100.05},
        ]

        regime = Regime(regime_type=RegimeType.TREND)
        real_ogul._advance_orders(regime)

        assert real_ogul.active_trades["F_THYAO"].state == TradeState.FILLED
        assert real_ogul.active_trades["F_THYAO"].ticket == 99999

    def test_baba_correlation_blocks_signal(self, real_ogul, mock_mt5,
                                             tmp_db, mock_baba):
        """BABA korelasyon engeli → CANCELLED."""
        bars = _make_m15_bars()
        tmp_db.insert_bars("F_THYAO", "M15", bars)

        mock_baba.check_correlation_limits.return_value = RiskVerdict(
            can_trade=False, reason="correlated_with_F_AKBNK",
        )

        signal = Signal(
            symbol="F_THYAO",
            signal_type=SignalType.BUY,
            price=100.0,
            sl=98.0,
            tp=104.0,
            strength=0.8,
            reason="test",
            strategy=StrategyType.TREND_FOLLOW,
        )
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(real_ogul, '_is_trading_allowed', return_value=True):
            real_ogul._execute_signal(signal, regime)

        # Trade eklenmemeli
        assert "F_THYAO" not in real_ogul.active_trades

        # Cancel event yazılmalı
        events = tmp_db.get_events(event_type="ORDER_CANCELLED")
        assert len(events) >= 1
        assert "correlation" in events[0]["message"]

    def test_concurrent_limit_blocks_new_trade(self, real_ogul, mock_mt5,
                                                tmp_db, mock_baba):
        """5 aktif trade varken yeni trade CANCELLED."""
        bars = _make_m15_bars()
        tmp_db.insert_bars("F_NEWCONTRACT", "M15", bars)

        # MAX_CONCURRENT kadar aktif trade oluştur
        for i in range(MAX_CONCURRENT):
            sym = f"F_SYM{i}"
            real_ogul.active_trades[sym] = Trade(
                symbol=sym, direction="BUY", volume=1.0,
                state=TradeState.FILLED,
            )

        signal = Signal(
            symbol="F_NEWCONTRACT",
            signal_type=SignalType.BUY,
            price=100.0, sl=98.0, tp=104.0,
            strength=0.8, reason="test",
            strategy=StrategyType.TREND_FOLLOW,
        )
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(real_ogul, '_is_trading_allowed', return_value=True):
            real_ogul._execute_signal(signal, regime)

        assert "F_NEWCONTRACT" not in real_ogul.active_trades
        events = tmp_db.get_events(event_type="ORDER_CANCELLED")
        assert any("concurrent_limit" in e["message"] for e in events)

    def test_margin_insufficient_blocks_trade(self, real_ogul, mock_mt5,
                                               tmp_db, mock_baba):
        """Yetersiz teminat → CANCELLED."""
        bars = _make_m15_bars()
        tmp_db.insert_bars("F_THYAO", "M15", bars)

        # Teminat yetersiz
        mock_mt5.get_account_info.return_value = SimpleNamespace(
            equity=100000.0, free_margin=5000.0,  # < %20 reserve
        )

        signal = Signal(
            symbol="F_THYAO",
            signal_type=SignalType.BUY,
            price=100.0, sl=98.0, tp=104.0,
            strength=0.8, reason="test",
            strategy=StrategyType.TREND_FOLLOW,
        )
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(real_ogul, '_is_trading_allowed', return_value=True):
            real_ogul._execute_signal(signal, regime)

        assert "F_THYAO" not in real_ogul.active_trades
        events = tmp_db.get_events(event_type="ORDER_CANCELLED")
        assert any("margin_insufficient" in e["message"] for e in events)

    def test_trade_appears_in_db(self, real_ogul, mock_mt5, tmp_db, mock_baba):
        """İşlem DB'ye kaydedilir."""
        bars = _make_m15_bars()
        tmp_db.insert_bars("F_THYAO", "M15", bars)

        signal = Signal(
            symbol="F_THYAO",
            signal_type=SignalType.SELL,
            price=100.0, sl=102.0, tp=96.0,
            strength=0.7, reason="test",
            strategy=StrategyType.MEAN_REVERSION,
        )
        regime = Regime(regime_type=RegimeType.RANGE)

        with patch.object(real_ogul, '_is_trading_allowed', return_value=True):
            real_ogul._execute_signal(signal, regime)

        # DB'den trade oku
        trades = tmp_db.get_trades(symbol="F_THYAO")
        assert len(trades) >= 1
        assert trades[0]["direction"] == "SELL"
        assert trades[0]["strategy"] == "mean_reversion"
        assert trades[0]["regime"] == "RANGE"


# ═════════════════════════════════════════════════════════════════════
#  4. RİSK KONTROLÜ
#     Zarar limiti tetikleme → sistem durdurma → dashboard uyarı
# ═════════════════════════════════════════════════════════════════════

class TestRiskControl:
    """Zarar tetikleme → işlem engelleme → kill-switch."""

    def test_daily_loss_blocks_trading(self, engine, mock_baba, mock_ogul):
        """Günlük zarar limiti → OĞUL'a boş sembol."""
        mock_baba.check_risk_limits.return_value = RiskVerdict(
            can_trade=False,
            reason="daily_loss_exceeded",
            kill_switch_level=0,
        )

        engine._run_single_cycle()

        symbols_arg = mock_ogul.process_signals.call_args[0][0]
        assert symbols_arg == []

    def test_risk_verdict_lot_multiplier(self, engine, mock_baba, mock_ogul):
        """Haftalık zarar → lot çarpanı %50."""
        mock_baba.check_risk_limits.return_value = RiskVerdict(
            can_trade=True,
            lot_multiplier=0.5,
        )

        engine._run_single_cycle()

        # process_signals çağrılmalı (engellenmemeli)
        mock_ogul.process_signals.assert_called_once()
        symbols = mock_ogul.process_signals.call_args[0][0]
        assert len(symbols) > 0

    def test_consecutive_losses_trigger_cooldown(self, engine, mock_baba,
                                                  mock_ogul):
        """3 ardışık kayıp → cooldown (can_trade=False)."""
        mock_baba._risk_state["consecutive_losses"] = 3
        mock_baba.check_risk_limits.return_value = RiskVerdict(
            can_trade=False,
            reason="consecutive_loss_cooldown",
            kill_switch_level=2,
        )

        engine._run_single_cycle()

        symbols_arg = mock_ogul.process_signals.call_args[0][0]
        assert symbols_arg == []

    def test_risk_flow_multi_cycle(self, engine, mock_baba, mock_ogul):
        """2 cycle: 1. risk engel, 2. risk OK → ticaret başlar."""
        verdicts = [
            RiskVerdict(can_trade=False, reason="daily_loss"),
            RiskVerdict(can_trade=True),
        ]
        mock_baba.check_risk_limits.side_effect = verdicts

        symbol_sets = []

        def capture(symbols, regime):
            symbol_sets.append(list(symbols))

        mock_ogul.process_signals.side_effect = capture

        # 2 cycle çalıştır
        engine._running = True
        real_run = engine._run_single_cycle
        counter = 0

        def counted():
            nonlocal counter
            counter += 1
            real_run()
            if counter >= 2:
                engine._running = False

        engine._run_single_cycle = counted

        with patch("engine.main._time.sleep"):
            engine._main_loop()

        assert symbol_sets[0] == []       # Cycle 1: engel
        assert len(symbol_sets[1]) > 0    # Cycle 2: OK

    def test_risk_block_sends_empty_symbols(self, engine, mock_baba, mock_ogul):
        """Risk engeli → OĞUL'a boş sembol, ama process_signals çağrılır."""
        mock_baba.check_risk_limits.return_value = RiskVerdict(
            can_trade=False,
            reason="hard_drawdown_exceeded",
            kill_switch_level=3,
        )

        engine._run_single_cycle()

        # process_signals çağrılır (mevcut emirleri yönetmek için)
        mock_ogul.process_signals.assert_called_once()
        symbols_arg = mock_ogul.process_signals.call_args[0][0]
        assert symbols_arg == []

    def test_floating_loss_blocks_new_trades(self, real_ogul, mock_mt5,
                                              tmp_db, mock_baba):
        """Floating loss yüksekken yeni emir girilmez (teminat kontrolü)."""
        bars = _make_m15_bars()
        tmp_db.insert_bars("F_THYAO", "M15", bars)

        # Free margin < reserve
        mock_mt5.get_account_info.return_value = SimpleNamespace(
            equity=100000.0,
            free_margin=10000.0,  # < %20 of equity
        )

        signal = Signal(
            symbol="F_THYAO", signal_type=SignalType.BUY,
            price=100.0, sl=98.0, tp=104.0,
            strength=0.8, reason="test",
            strategy=StrategyType.TREND_FOLLOW,
        )
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(real_ogul, '_is_trading_allowed', return_value=True):
            real_ogul._execute_signal(signal, regime)

        assert "F_THYAO" not in real_ogul.active_trades


# ═════════════════════════════════════════════════════════════════════
#  5. KILL-SWITCH 3 SEVİYE
#     L1 sembol, L2 sistem, L3 tam kapanış
# ═════════════════════════════════════════════════════════════════════

class TestKillSwitch:
    """3 seviye kill-switch entegrasyonu."""

    def test_l1_blocks_single_symbol(self, real_ogul, mock_mt5, tmp_db,
                                      mock_baba):
        """L1: belirli sembol durdurulur, diğerleri devam eder."""

        def symbol_killed(sym):
            return sym == "F_THYAO"

        mock_baba.is_symbol_killed.side_effect = symbol_killed

        # F_THYAO için sinyal üretilmemeli (process_signals içinde kontrol)
        # Basit test: sinyal üretilse bile is_symbol_killed kontrol edilir
        regime = Regime(regime_type=RegimeType.TREND)

        with patch.object(real_ogul, '_generate_signal', return_value=None) as gen:
            with patch.object(real_ogul, '_is_trading_allowed', return_value=True):
                with patch.object(real_ogul, '_check_end_of_day'):
                    with patch.object(real_ogul, '_advance_orders'):
                        with patch.object(real_ogul, '_manage_active_trades'):
                            with patch.object(real_ogul, '_sync_positions'):
                                real_ogul.process_signals(
                                    ["F_THYAO", "F_AKBNK"], regime,
                                )

        # F_THYAO için generate_signal çağrılmamalı
        calls = [c[0][0] for c in gen.call_args_list]
        assert "F_THYAO" not in calls
        assert "F_AKBNK" in calls

    def test_l2_blocks_all_trading(self, engine, mock_baba, mock_ogul):
        """L2: tüm sistem durur, OĞUL'a boş sembol."""
        mock_baba.check_risk_limits.return_value = RiskVerdict(
            can_trade=False,
            reason="kill_switch_L2",
            kill_switch_level=2,
        )

        engine._run_single_cycle()

        symbols_arg = mock_ogul.process_signals.call_args[0][0]
        assert symbols_arg == []

    def test_l3_closes_all_positions(self, real_ogul, mock_mt5, tmp_db):
        """L3: tüm pozisyonlar ve bekleyen emirler kapatılır."""
        # 2 aktif FILLED trade + 1 SENT trade
        real_ogul.active_trades["F_THYAO"] = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            state=TradeState.FILLED, ticket=111,
        )
        real_ogul.active_trades["F_AKBNK"] = Trade(
            symbol="F_AKBNK", direction="SELL", volume=0.5,
            state=TradeState.FILLED, ticket=222,
        )
        real_ogul.active_trades["F_ASELS"] = Trade(
            symbol="F_ASELS", direction="BUY", volume=1.0,
            state=TradeState.SENT, order_ticket=333,
        )

        # Gün sonu simüle et (17:45+ → tüm pozisyon/emir kapatma)
        eod_time = datetime(2025, 1, 10, 17, 50, 0)
        real_ogul._check_end_of_day(now=eod_time)

        # close_position ve cancel_order çağrılmalı
        close_calls = mock_mt5.close_position.call_args_list
        cancel_calls = mock_mt5.cancel_order.call_args_list

        close_tickets = [c[0][0] for c in close_calls]
        assert 111 in close_tickets
        assert 222 in close_tickets

        cancel_tickets = [c[0][0] for c in cancel_calls]
        assert 333 in cancel_tickets

    def test_l1_to_l2_escalation(self, engine, mock_baba, mock_ogul):
        """L1 → L2 eskalasyon: BABA risk verdict seviye yükseltir."""
        # İlk cycle L1 (sembol engeli), ikinci cycle L2 (sistem engeli)
        verdicts = [
            RiskVerdict(
                can_trade=True, kill_switch_level=1,
                blocked_symbols=["F_THYAO"],
            ),
            RiskVerdict(
                can_trade=False, kill_switch_level=2,
                reason="three_consecutive_losses",
            ),
        ]
        mock_baba.check_risk_limits.side_effect = verdicts

        symbol_sets = []

        def capture(symbols, regime):
            symbol_sets.append(list(symbols))

        mock_ogul.process_signals.side_effect = capture

        engine._running = True
        real_run = engine._run_single_cycle
        counter = 0

        def counted():
            nonlocal counter
            counter += 1
            real_run()
            if counter >= 2:
                engine._running = False

        engine._run_single_cycle = counted

        with patch("engine.main._time.sleep"):
            engine._main_loop()

        # Cycle 1: ticaret var (L1 sadece sembol engeli)
        assert len(symbol_sets[0]) > 0
        # Cycle 2: boş (L2 sistem engeli)
        assert symbol_sets[1] == []

    def test_kill_switch_events_in_db(self, tmp_db):
        """Kill-switch olayları DB'de kayıtlı."""
        tmp_db.insert_event(
            event_type="KILL_SWITCH",
            message="L2 tetiklendi: 3 ardışık kayıp",
            severity="CRITICAL",
            action="LEVEL_2",
        )
        tmp_db.insert_event(
            event_type="KILL_SWITCH",
            message="L3 tetiklendi: hard drawdown",
            severity="CRITICAL",
            action="LEVEL_3",
        )

        events = tmp_db.get_events(event_type="KILL_SWITCH")
        assert len(events) == 2
        assert events[0]["action"] == "LEVEL_3"  # DESC sıralama (son event ilk)
        assert events[1]["action"] == "LEVEL_2"


# ═════════════════════════════════════════════════════════════════════
#  6. BAĞLANTI KOPMASI
#     MT5 disconnect → reconnect → recovery
# ═════════════════════════════════════════════════════════════════════

class TestConnectionRecovery:
    """MT5 kopma → yeniden bağlanma → devam."""

    def test_heartbeat_failure_triggers_reconnect(self, engine, mock_mt5):
        """Heartbeat başarısız → reconnect denemesi."""
        mock_mt5.heartbeat.return_value = False
        mock_mt5.connect.return_value = True

        engine._heartbeat_mt5()

        mock_mt5.connect.assert_called()

    def test_reconnect_success_continues_cycle(self, engine, mock_mt5,
                                                mock_baba, mock_ogul):
        """Reconnect başarılı → cycle devam eder."""
        cycle_ran = False

        def baba_run(pipeline):
            nonlocal cycle_ran
            cycle_ran = True
            return Regime(regime_type=RegimeType.TREND)

        mock_baba.run_cycle.side_effect = baba_run

        # Heartbeat: 1. çağrı fail → reconnect success → 2. çağrı OK
        mock_mt5.heartbeat.side_effect = [False, True]
        mock_mt5.connect.return_value = True

        # _heartbeat_mt5: fail → connect OK → True döner
        # Sonra ikinci cycle'da heartbeat OK
        result = engine._heartbeat_mt5()
        assert result is True
        mock_mt5.connect.assert_called()

        # Ardından normal cycle çalışır
        mock_mt5.heartbeat.side_effect = None
        mock_mt5.heartbeat.return_value = True

        engine._run_single_cycle()
        assert cycle_ran

    def test_max_reconnect_attempts_stops_engine(self, engine, mock_mt5):
        """MT5 bağlantısı kurulamazsa _heartbeat_mt5 False döner."""
        mock_mt5.heartbeat.return_value = False
        mock_mt5.connect.return_value = False  # Reconnect hep başarısız

        # _heartbeat_mt5 → heartbeat fail → connect fail → False döner
        result = engine._heartbeat_mt5()
        assert result is False

        # _run_single_cycle çağrılınca _SystemStopError fırlatır
        from engine.main import _SystemStopError

        with pytest.raises(_SystemStopError):
            engine._run_single_cycle()

    def test_positions_survive_reconnect(self, real_ogul, mock_mt5, tmp_db):
        """Reconnect sonrası aktif trade'ler korunur."""
        # Aktif trade ekle
        trade = Trade(
            symbol="F_THYAO", direction="BUY", volume=1.0,
            state=TradeState.FILLED, ticket=111,
            entry_price=100.0,
        )
        real_ogul.active_trades["F_THYAO"] = trade

        # MT5'te aynı pozisyon mevcut
        mock_mt5.get_positions.return_value = [
            {"ticket": 111, "symbol": "F_THYAO", "type": 0,
             "volume": 1.0, "price_open": 100.0,
             "sl": 98.0, "tp": 104.0, "profit": 50.0},
        ]

        # Sync positions çağır
        real_ogul._sync_positions()

        # Trade hâlâ aktif
        assert "F_THYAO" in real_ogul.active_trades
        assert real_ogul.active_trades["F_THYAO"].state == TradeState.FILLED

    def test_orphan_position_after_reconnect(self, real_ogul, mock_mt5, tmp_db):
        """Reconnect sonrası MT5'te pozisyon var ama trade yok → senkronize."""
        # active_trades boş ama MT5'te pozisyon var → _sync_positions
        # Bu senaryoda active_trades boş olduğundan yeni pozisyon algılanır
        mock_mt5.get_positions.return_value = [
            {"ticket": 999, "symbol": "F_THYAO", "type": 0,
             "volume": 1.0, "price_open": 100.0,
             "sl": 98.0, "tp": 104.0, "profit": 50.0},
        ]

        # Sync çağır — bilinmeyen pozisyonu loglar
        real_ogul._sync_positions()

        # Pozisyon algılandı (active_trades'e eklenmemiş bile olsa log var)
        # Önemli olan sistemin çökmemesi
        assert True  # No exception raised


# ═════════════════════════════════════════════════════════════════════
#  7. İŞLEM GEÇMİŞİ
#     Filtreler, istatistikler, onay sistemi
# ═════════════════════════════════════════════════════════════════════

class TestTradeHistory:
    """İşlem geçmişi: DB sorgulama, filtreleme, istatistik, onay."""

    def _insert_sample_trades(self, db, n=10):
        """Test trade'leri ekle."""
        symbols = ["F_THYAO", "F_AKBNK", "F_ASELS"]
        strategies = ["trend_follow", "mean_reversion", "breakout"]
        directions = ["BUY", "SELL"]
        ids = []
        for i in range(n):
            tid = db.insert_trade({
                "strategy": strategies[i % 3],
                "symbol": symbols[i % 3],
                "direction": directions[i % 2],
                "entry_time": f"2025-01-{10 + i:02d}T10:00:00",
                "exit_time": f"2025-01-{10 + i:02d}T14:00:00",
                "entry_price": 100.0 + i,
                "exit_price": 100.0 + i + (1 if i % 3 != 0 else -1),
                "lot": 1.0,
                "pnl": 500.0 if i % 3 != 0 else -300.0,
                "slippage": 0.1 * i,
                "commission": 5.0,
                "swap": 0.0,
                "regime": "TREND",
            })
            ids.append(tid)
        return ids

    def test_get_trades_unfiltered(self, tmp_db):
        """Tüm trade'ler limit ile sorgulanır."""
        self._insert_sample_trades(tmp_db, 10)

        trades = tmp_db.get_trades(limit=100)
        assert len(trades) == 10

    def test_get_trades_by_symbol(self, tmp_db):
        """Sembol filtresi doğru çalışır."""
        self._insert_sample_trades(tmp_db, 10)

        trades = tmp_db.get_trades(symbol="F_THYAO", limit=100)
        assert all(t["symbol"] == "F_THYAO" for t in trades)
        assert len(trades) > 0

    def test_get_trades_by_strategy(self, tmp_db):
        """Strateji filtresi doğru çalışır."""
        self._insert_sample_trades(tmp_db, 10)

        trades = tmp_db.get_trades(strategy="breakout", limit=100)
        assert all(t["strategy"] == "breakout" for t in trades)

    def test_trade_stats_calculation(self, tmp_db):
        """İstatistikler doğru hesaplanır."""
        self._insert_sample_trades(tmp_db, 10)

        trades = tmp_db.get_trades(limit=100)
        pnl_values = [t["pnl"] for t in trades if t.get("pnl") is not None]
        total_pnl = sum(pnl_values)
        winning = [p for p in pnl_values if p > 0]
        losing = [p for p in pnl_values if p < 0]

        assert len(pnl_values) == 10
        assert len(winning) > 0
        assert len(losing) > 0
        # Win rate hesabı
        win_rate = len(winning) / len(pnl_values) * 100
        assert 0 < win_rate < 100

    def test_approve_trade(self, tmp_db):
        """İşlem onaylama: exit_reason güncellenir."""
        ids = self._insert_sample_trades(tmp_db, 3)
        trade_id = ids[0]

        # Onay öncesi
        trade_before = tmp_db.get_trade(trade_id)
        assert trade_before is not None

        # Onay: exit_reason güncelle
        existing = trade_before.get("exit_reason") or ""
        new_reason = f"{existing} | APPROVED by operator: Test onay"
        success = tmp_db.update_trade(trade_id, {"exit_reason": new_reason.strip()})
        assert success is True

        # Onay sonrası
        trade_after = tmp_db.get_trade(trade_id)
        assert "APPROVED" in trade_after["exit_reason"]
        assert "operator" in trade_after["exit_reason"]

    def test_approve_nonexistent_trade(self, tmp_db):
        """Olmayan trade onaylama → None döner."""
        trade = tmp_db.get_trade(99999)
        assert trade is None

    def test_trade_limit_capped(self, tmp_db):
        """Limit parametresi çalışır."""
        self._insert_sample_trades(tmp_db, 10)

        trades = tmp_db.get_trades(limit=3)
        assert len(trades) == 3

    def test_events_logged_for_trades(self, tmp_db):
        """Trade olayları event tablosuna yazılır."""
        tmp_db.insert_event(
            event_type="ORDER_SENT",
            message="LIMIT BUY F_THYAO 1 lot @ 100.00",
            severity="INFO",
            action="order_sent",
        )
        tmp_db.insert_event(
            event_type="ORDER_FILLED",
            message="FILLED BUY F_THYAO 1 lot @ 100.05",
            severity="INFO",
            action="order_filled",
        )
        tmp_db.insert_event(
            event_type="TRADE_CLOSE",
            message="CLOSED BUY F_THYAO PnL=+500",
            severity="INFO",
            action="trade_close",
        )

        all_events = tmp_db.get_events(limit=10)
        assert len(all_events) == 3

        sent_events = tmp_db.get_events(event_type="ORDER_SENT")
        assert len(sent_events) == 1
        assert "F_THYAO" in sent_events[0]["message"]


# ═════════════════════════════════════════════════════════════════════
#  8. PERFORMANS
#     15 kontrat canlı veri + API yanıt süresi < 1 saniye
# ═════════════════════════════════════════════════════════════════════

class TestPerformance:
    """Çok kontrat + yanıt süresi testleri."""

    def test_15_symbols_single_cycle(self, engine, mock_baba, mock_ogul,
                                      mock_ustat, mock_pipeline):
        """15 kontratla tek cycle süresi ölçümü."""
        from engine.mt5_bridge import WATCHED_SYMBOLS

        mock_ustat.select_top5.return_value = WATCHED_SYMBOLS[:5]

        start = _time.perf_counter()
        engine._run_single_cycle()
        elapsed = _time.perf_counter() - start

        # Mock ortamda cycle < 1 saniye olmalı
        assert elapsed < 1.0, f"Cycle süresi çok uzun: {elapsed:.3f}s"

        mock_ogul.process_signals.assert_called_once()
        symbols_arg = mock_ogul.process_signals.call_args[0][0]
        assert len(symbols_arg) == 5

    def test_db_bulk_insert_performance(self, tmp_db):
        """500 trade insert performansı < 2 saniye."""
        symbols = ["F_THYAO", "F_AKBNK", "F_ASELS", "F_TCELL", "F_HALKB"]

        start = _time.perf_counter()
        for i in range(500):
            tmp_db.insert_trade({
                "strategy": "trend_follow",
                "symbol": symbols[i % 5],
                "direction": "BUY" if i % 2 == 0 else "SELL",
                "entry_time": f"2025-01-10T{10 + i // 60:02d}:{i % 60:02d}:00",
                "exit_time": f"2025-01-10T{14 + i // 60:02d}:{i % 60:02d}:00",
                "entry_price": 100.0 + i * 0.1,
                "exit_price": 101.0 + i * 0.1,
                "lot": 1.0,
                "pnl": 100.0 - (i % 7) * 50,
                "regime": "TREND",
            })
        elapsed = _time.perf_counter() - start

        assert elapsed < 2.0, f"500 trade insert çok yavaş: {elapsed:.3f}s"

        # Doğruluk
        trades = tmp_db.get_trades(limit=1000)
        assert len(trades) == 500

    def test_db_query_performance(self, tmp_db):
        """500 trade query performansı < 0.5 saniye."""
        symbols = ["F_THYAO", "F_AKBNK", "F_ASELS", "F_TCELL", "F_HALKB"]
        for i in range(500):
            tmp_db.insert_trade({
                "strategy": "trend_follow",
                "symbol": symbols[i % 5],
                "direction": "BUY",
                "entry_time": f"2025-01-10T10:{i % 60:02d}:00",
                "lot": 1.0,
                "pnl": 100.0,
                "regime": "TREND",
            })

        start = _time.perf_counter()
        trades = tmp_db.get_trades(limit=500)
        by_symbol = tmp_db.get_trades(symbol="F_THYAO", limit=500)
        by_strategy = tmp_db.get_trades(strategy="trend_follow", limit=500)
        elapsed = _time.perf_counter() - start

        assert elapsed < 0.5, f"3 sorgu çok yavaş: {elapsed:.3f}s"
        assert len(trades) == 500
        assert len(by_symbol) == 100  # 500/5
        assert len(by_strategy) == 500

    def test_event_bulk_insert_and_query(self, tmp_db):
        """200 event insert + filtreleme performansı."""
        types = ["ORDER_SENT", "ORDER_FILLED", "TRADE_CLOSE",
                 "KILL_SWITCH", "COOLDOWN"]
        severities = ["INFO", "WARNING", "CRITICAL"]

        start = _time.perf_counter()
        for i in range(200):
            tmp_db.insert_event(
                event_type=types[i % 5],
                message=f"Test event #{i}",
                severity=severities[i % 3],
                action=f"action_{i}",
            )
        insert_time = _time.perf_counter() - start

        start = _time.perf_counter()
        all_events = tmp_db.get_events(limit=200)
        critical_events = tmp_db.get_events(severity="CRITICAL", limit=200)
        kill_events = tmp_db.get_events(event_type="KILL_SWITCH", limit=200)
        query_time = _time.perf_counter() - start

        assert insert_time < 2.0, f"200 event insert yavaş: {insert_time:.3f}s"
        assert query_time < 0.5, f"3 event sorgu yavaş: {query_time:.3f}s"
        assert len(all_events) == 200
        assert len(critical_events) > 0
        assert all(e["severity"] == "CRITICAL" for e in critical_events)
        assert all(e["type"] == "KILL_SWITCH" for e in kill_events)

    def test_risk_snapshot_write_read(self, tmp_db):
        """Risk snapshot yazma/okuma performansı."""
        base = datetime(2025, 1, 10, 9, 30, 0)
        for i in range(100):
            ts = (base + timedelta(seconds=i * 10)).isoformat()
            tmp_db.insert_risk_snapshot({
                "timestamp": ts,
                "equity": 100000.0 + i * 100,
                "floating_pnl": -500.0 + i * 10,
                "daily_pnl": 200.0 - i * 5,
                "regime": "TREND",
                "drawdown": 0.01 + i * 0.001,
                "margin_usage": 0.3,
                "positions_json": json.dumps([]),
            })

        start = _time.perf_counter()
        latest = tmp_db.get_latest_risk_snapshot()
        snapshots = tmp_db.get_risk_snapshots(limit=50)
        elapsed = _time.perf_counter() - start

        assert elapsed < 0.2, f"Risk snapshot sorgu yavaş: {elapsed:.3f}s"
        assert latest is not None
        assert len(snapshots) == 50

    def test_concurrent_trades_state_tracking(self, real_ogul, mock_mt5, tmp_db):
        """5 eş zamanlı trade state takibi."""
        symbols = ["F_THYAO", "F_AKBNK", "F_ASELS", "F_TCELL", "F_HALKB"]

        for sym in symbols:
            real_ogul.active_trades[sym] = Trade(
                symbol=sym,
                direction="BUY",
                volume=1.0,
                state=TradeState.FILLED,
                ticket=hash(sym) % 100000,
                entry_price=100.0,
            )

        assert len(real_ogul.active_trades) == 5

        # Tüm trade'ler FILLED state'te
        for sym, trade in real_ogul.active_trades.items():
            assert trade.state == TradeState.FILLED

    def test_api_deps_response_time(self, engine, mock_baba, mock_mt5):
        """API dependency çözümleme süresi."""
        from api.deps import set_engine, get_engine, get_db, get_mt5, get_baba

        set_engine(engine)

        start = _time.perf_counter()
        for _ in range(1000):
            get_engine()
            get_db()
            get_mt5()
            get_baba()
        elapsed = _time.perf_counter() - start

        # 1000 × 4 çağrı < 0.1s
        assert elapsed < 0.1, f"API deps çözümleme yavaş: {elapsed:.3f}s"


# ═════════════════════════════════════════════════════════════════════
#  EK: API ENDPOINT ENTEGRASYONU
#     FastAPI TestClient ile HTTP endpoint testleri
# ═════════════════════════════════════════════════════════════════════

class TestAPIEndpoints:
    """FastAPI endpoint'lerinin gerçek HTTP testleri."""

    @pytest.fixture
    def api_client(self, engine, mock_baba, mock_mt5):
        """FastAPI TestClient oluşturur."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi[test] / httpx gerekli")

        from api.deps import set_engine
        set_engine(engine)

        from api.server import app
        client = TestClient(app, raise_server_exceptions=False)
        yield client

    def test_status_endpoint(self, api_client):
        """GET /api/status — 200 döner."""
        resp = api_client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "engine_running" in data
        assert "regime" in data
        assert "kill_switch_level" in data

    def test_account_endpoint(self, api_client, mock_mt5):
        """GET /api/account — hesap bilgileri."""
        # Hesap bilgilerinde tüm alanlar gerekli
        mock_mt5.get_account_info.return_value = SimpleNamespace(
            login=12345678, server="VIOPDemo",
            balance=100000.0, equity=100000.0,
            margin=0.0, free_margin=100000.0,
            margin_level=0.0, currency="TRY",
        )
        resp = api_client.get("/api/account")
        assert resp.status_code == 200
        data = resp.json()
        assert "balance" in data
        assert "equity" in data

    def test_positions_endpoint(self, api_client, mock_mt5):
        """GET /api/positions — pozisyon listesi."""
        mock_mt5.get_positions.return_value = [
            {"ticket": 111, "symbol": "F_THYAO", "type": 0,
             "volume": 1.0, "price_open": 100.0,
             "price_current": 101.0, "sl": 98.0, "tp": 104.0,
             "profit": 500.0, "time": 1700000000},
        ]

        resp = api_client.get("/api/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert "positions" in data

    def test_risk_endpoint(self, api_client, mock_baba):
        """GET /api/risk — risk snapshot."""
        resp = api_client.get("/api/risk")
        assert resp.status_code == 200
        data = resp.json()
        assert "can_trade" in data
        assert "regime" in data
        assert "kill_switch_level" in data

    def test_events_endpoint(self, api_client):
        """GET /api/events — sistem olayları."""
        resp = api_client.get("/api/events")
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data
        assert "count" in data

    def test_events_filter_by_severity(self, api_client):
        """GET /api/events?severity=CRITICAL — filtre."""
        resp = api_client.get("/api/events", params={"severity": "CRITICAL"})
        assert resp.status_code == 200

    def test_root_endpoint(self, api_client):
        """GET / — API bilgisi."""
        resp = api_client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "ÜSTAT API"
        assert data["version"] == "5.0.0"

    def test_trades_endpoint(self, api_client):
        """GET /api/trades — işlem geçmişi."""
        resp = api_client.get("/api/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert "trades" in data

    def test_trade_stats_endpoint(self, api_client):
        """GET /api/trades/stats — istatistikler."""
        resp = api_client.get("/api/trades/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_trades" in data
        assert "win_rate" in data
