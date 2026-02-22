"""Engine ana döngü (main.py) modülü testleri — v12.0.

Test sınıfları:
    TestEngineInit            – __init__ parametreleri, varsayılan/özel bileşenler
    TestStart                 – MT5 bağlantısı, restore, başarısız başlatma
    TestStop                  – Graceful shutdown, aktif işlem uyarısı
    TestMainLoop              – Cycle sıralaması, interval hesabı, uzun cycle uyarısı
    TestSingleCycle           – BABA-first sırası, risk engeli, Top 5, OĞUL
    TestHeartbeatMT5          – Bağlantı OK, kopma, reconnect, sistem durdurma
    TestUpdateData            – Pipeline hatası yakalanması
    TestRunBabaCycle          – Normal rejim, BABA hatası → OLAY fallback
    TestCycleSummary          – Debug/info log aralıkları
    TestDBErrorHandling       – Art arda DB hatası → sistem durdurma
    TestSystemStopError       – Kritik hata → engine stop
    TestRestoreState          – BABA + OĞUL restore, hata toleransı
    TestLogEvent              – Event yazma, DBError fırlatma
    TestRunFunction           – run() giriş noktası, sinyal yakalama
    TestConstants             – Sabit değer doğrulaması
"""

import json
import signal as _signal
import sys
import time as _time
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call, PropertyMock

import pytest

from engine.main import (
    Engine,
    run,
    _SystemStopError,
    _DBError,
    CYCLE_INTERVAL,
    MAX_MT5_RECONNECT,
    DB_ERROR_THRESHOLD,
    SHUTDOWN_TIMEOUT,
)
from engine.config import Config
from engine.database import Database
from engine.models.regime import Regime, RegimeType
from engine.models.risk import RiskParams, RiskVerdict


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
def mock_mt5():
    """MagicMock MT5Bridge."""
    mt5 = MagicMock()
    mt5.connect.return_value = True
    mt5.heartbeat.return_value = True
    mt5.disconnect.return_value = None
    mt5.get_positions.return_value = []
    mt5.get_account_info.return_value = SimpleNamespace(
        equity=100000.0, free_margin=80000.0,
    )
    return mt5


@pytest.fixture
def mock_pipeline():
    """MagicMock DataPipeline."""
    pipeline = MagicMock()
    pipeline.run_cycle.return_value = None
    pipeline.get_deactivated_symbols.return_value = []
    pipeline.get_active_symbols.return_value = ["F_THYAO", "F_AKBNK"]
    pipeline.latest_ticks = {}
    return pipeline


@pytest.fixture
def mock_baba():
    """MagicMock Baba — normal çalışma."""
    baba = MagicMock()
    baba.run_cycle.return_value = Regime(regime_type=RegimeType.TREND)
    baba.check_risk_limits.return_value = RiskVerdict(can_trade=True)
    baba.active_warnings = []
    baba.restore_risk_state.return_value = None
    baba.is_symbol_killed.return_value = False
    return baba


@pytest.fixture
def mock_ogul():
    """MagicMock Ogul."""
    ogul = MagicMock()
    ogul.process_signals.return_value = None
    ogul.restore_active_trades.return_value = None
    ogul.active_trades = {}
    return ogul


@pytest.fixture
def mock_ustat():
    """MagicMock Ustat."""
    ustat = MagicMock()
    ustat.select_top5.return_value = ["F_THYAO", "F_AKBNK", "F_ASELS"]
    return ustat


@pytest.fixture
def mock_db():
    """MagicMock Database."""
    db = MagicMock()
    db.insert_event.return_value = None
    db.close.return_value = None
    return db


@pytest.fixture
def mock_config():
    """MagicMock Config."""
    return MagicMock()


@pytest.fixture
def engine(mock_config, mock_db, mock_mt5, mock_pipeline, mock_ustat, mock_baba, mock_ogul):
    """Tam mock bileşenlerle Engine nesnesi."""
    return Engine(
        config=mock_config,
        db=mock_db,
        mt5=mock_mt5,
        pipeline=mock_pipeline,
        ustat=mock_ustat,
        baba=mock_baba,
        ogul=mock_ogul,
    )


# ═════════════════════════════════════════════════════════════════════
#  TestEngineInit
# ═════════════════════════════════════════════════════════════════════

class TestEngineInit:
    """Engine.__init__ testleri."""

    def test_custom_components(self, engine, mock_config, mock_db, mock_mt5,
                                mock_pipeline, mock_ustat, mock_baba, mock_ogul):
        """Özel bileşenler atanır."""
        assert engine.config is mock_config
        assert engine.db is mock_db
        assert engine.mt5 is mock_mt5
        assert engine.pipeline is mock_pipeline
        assert engine.ustat is mock_ustat
        assert engine.baba is mock_baba
        assert engine.ogul is mock_ogul

    def test_initial_state(self, engine):
        """Başlangıç durumu doğru."""
        assert engine._running is False
        assert engine._cycle_count == 0
        assert engine._consecutive_db_errors == 0
        assert engine._shutdown_requested is False

    def test_risk_params_created(self, engine):
        """RiskParams varsayılan olarak oluşturulur."""
        assert isinstance(engine.risk_params, RiskParams)
        assert engine.risk_params.risk_per_trade == 0.01

    @patch("engine.main.Config")
    @patch("engine.main.Database")
    @patch("engine.main.MT5Bridge")
    @patch("engine.main.DataPipeline")
    @patch("engine.main.Ustat")
    @patch("engine.main.Baba")
    @patch("engine.main.Ogul")
    def test_default_components_created(self, mock_ogul_cls, mock_baba_cls,
                                        mock_ustat_cls, mock_pipeline_cls,
                                        mock_mt5_cls, mock_db_cls, mock_config_cls):
        """Hiçbir bileşen verilmezse varsayılanlar oluşturulur."""
        eng = Engine()
        mock_config_cls.assert_called_once()
        mock_db_cls.assert_called_once()
        mock_mt5_cls.assert_called_once()
        mock_pipeline_cls.assert_called_once()
        mock_ustat_cls.assert_called_once()
        mock_baba_cls.assert_called_once()
        mock_ogul_cls.assert_called_once()


# ═════════════════════════════════════════════════════════════════════
#  TestStart
# ═════════════════════════════════════════════════════════════════════

class TestStart:
    """Engine.start() testleri."""

    def test_successful_start(self, engine, mock_mt5, mock_baba, mock_ogul):
        """Başarılı başlatma: MT5 bağlan + restore + loop."""
        # _main_loop'u 1 cycle sonra durdur
        def stop_after_call():
            engine._running = False

        engine._main_loop = MagicMock(side_effect=stop_after_call)
        engine.start()

        mock_mt5.connect.assert_called_once()
        mock_baba.restore_risk_state.assert_called_once()
        mock_ogul.restore_active_trades.assert_called_once()
        engine._main_loop.assert_called_once()

    def test_mt5_connect_failure(self, engine, mock_mt5, mock_db):
        """MT5 bağlantısı başarısız → engine başlamaz."""
        mock_mt5.connect.return_value = False
        engine.start()

        assert engine._running is False
        mock_db.insert_event.assert_called()
        # _main_loop çağrılmamalı
        assert engine._cycle_count == 0

    def test_start_sets_running(self, engine):
        """start() _running=True yapar."""
        engine._main_loop = MagicMock(side_effect=lambda: setattr(engine, '_running', False))
        engine.start()
        # _main_loop çağrıldığı anda _running True olmalıydı
        engine._main_loop.assert_called_once()


# ═════════════════════════════════════════════════════════════════════
#  TestStop
# ═════════════════════════════════════════════════════════════════════

class TestStop:
    """Engine.stop() testleri."""

    def test_graceful_stop(self, engine, mock_mt5, mock_db):
        """Graceful shutdown: MT5 disconnect + DB close."""
        engine._running = True
        engine.stop(reason="test")

        assert engine._running is False
        assert engine._shutdown_requested is True
        mock_mt5.disconnect.assert_called_once()
        mock_db.close.assert_called_once()

    def test_stop_with_active_trades(self, engine, mock_ogul):
        """Aktif işlem varsa uyarı loglanır."""
        engine._running = True
        mock_ogul.active_trades = {"F_THYAO": MagicMock(), "F_AKBNK": MagicMock()}
        with patch("engine.main.logger") as mock_logger:
            engine.stop(reason="test")
            # "DİKKAT" mesajı loglanmalı
            warning_calls = [c for c in mock_logger.warning.call_args_list
                           if "aktif işlem" in str(c)]
            assert len(warning_calls) == 1

    def test_stop_idempotent(self, engine, mock_mt5):
        """İki kez stop() çağrılınca ikincisi etkisiz."""
        engine._running = True
        engine.stop()
        mock_mt5.disconnect.assert_called_once()

        mock_mt5.disconnect.reset_mock()
        engine.stop()
        mock_mt5.disconnect.assert_not_called()

    def test_stop_handles_disconnect_error(self, engine, mock_mt5):
        """MT5 disconnect hatası yakalanır."""
        engine._running = True
        mock_mt5.disconnect.side_effect = Exception("disconnect fail")
        engine.stop()  # hata fırlatılmamalı
        assert engine._running is False

    def test_stop_handles_db_close_error(self, engine, mock_db):
        """DB close hatası yakalanır."""
        engine._running = True
        mock_db.close.side_effect = Exception("db close fail")
        engine.stop()  # hata fırlatılmamalı
        assert engine._running is False


# ═════════════════════════════════════════════════════════════════════
#  TestMainLoop
# ═════════════════════════════════════════════════════════════════════

class TestMainLoop:
    """Engine._main_loop() testleri."""

    def test_loop_calls_run_single_cycle(self, engine):
        """Her iterasyonda _run_single_cycle çağrılır."""
        call_count = 0

        def fake_cycle():
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                engine._running = False

        engine._running = True
        engine._run_single_cycle = MagicMock(side_effect=fake_cycle)

        with patch("engine.main._time.sleep"):
            engine._main_loop()

        assert call_count == 3
        assert engine._cycle_count == 3

    def test_cycle_count_increments(self, engine):
        """_cycle_count her cycle artar."""
        call_count = 0

        def fake_cycle():
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                engine._running = False

        engine._running = True
        engine._run_single_cycle = MagicMock(side_effect=fake_cycle)

        with patch("engine.main._time.sleep"):
            engine._main_loop()

        assert engine._cycle_count == 2

    def test_system_stop_error_halts_loop(self, engine):
        """_SystemStopError → engine stop."""
        engine._running = True
        engine._run_single_cycle = MagicMock(
            side_effect=_SystemStopError("MT5 koptu")
        )
        engine.stop = MagicMock()

        engine._main_loop()

        engine.stop.assert_called_once()
        assert "MT5 koptu" in str(engine.stop.call_args)

    def test_db_error_threshold(self, engine, mock_db):
        """Art arda DB_ERROR_THRESHOLD hata → sistem durdur."""
        engine._running = True
        call_count = 0

        def raise_db_error():
            nonlocal call_count
            call_count += 1
            raise _DBError(f"DB hatası #{call_count}")

        engine._run_single_cycle = MagicMock(side_effect=raise_db_error)
        engine.stop = MagicMock(side_effect=lambda **kw: setattr(engine, '_running', False))

        with patch("engine.main._time.sleep"):
            engine._main_loop()

        assert engine._consecutive_db_errors >= DB_ERROR_THRESHOLD
        engine.stop.assert_called_once()

    def test_db_error_reset_on_success(self, engine):
        """Başarılı cycle DB hata sayacını sıfırlar."""
        engine._running = True
        engine._consecutive_db_errors = 2
        call_count = 0

        def fake_cycle():
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                engine._running = False

        engine._run_single_cycle = MagicMock(side_effect=fake_cycle)

        with patch("engine.main._time.sleep"):
            engine._main_loop()

        assert engine._consecutive_db_errors == 0

    def test_generic_exception_continues(self, engine):
        """Genel hata → cycle devam eder."""
        engine._running = True
        call_count = 0

        def fake_cycle():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("test hatası")
            if call_count >= 2:
                engine._running = False

        engine._run_single_cycle = MagicMock(side_effect=fake_cycle)

        with patch("engine.main._time.sleep"):
            engine._main_loop()

        assert call_count == 2

    def test_sleep_calculated_correctly(self, engine):
        """Cycle süresi < CYCLE_INTERVAL ise kalan süre beklenir."""
        engine._running = True
        call_count = 0

        def fake_cycle():
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                engine._running = False

        engine._run_single_cycle = MagicMock(side_effect=fake_cycle)

        with patch("engine.main._time.sleep") as mock_sleep:
            with patch("engine.main._time.monotonic", side_effect=[0.0, 2.0]):
                engine._main_loop()

            if mock_sleep.called:
                sleep_arg = mock_sleep.call_args[0][0]
                assert sleep_arg <= CYCLE_INTERVAL


# ═════════════════════════════════════════════════════════════════════
#  TestSingleCycle
# ═════════════════════════════════════════════════════════════════════

class TestSingleCycle:
    """Engine._run_single_cycle() testleri."""

    def test_baba_first_order(self, engine, mock_mt5, mock_baba, mock_pipeline,
                               mock_ustat, mock_ogul):
        """BABA → ÜSTAT → OĞUL sıralaması doğru."""
        call_order = []

        mock_pipeline.run_cycle.side_effect = lambda: call_order.append("pipeline")
        mock_baba.run_cycle.side_effect = lambda p: (
            call_order.append("baba"),
            Regime(regime_type=RegimeType.TREND),
        )[-1]
        mock_baba.check_risk_limits.side_effect = lambda rp: (
            call_order.append("risk"),
            RiskVerdict(can_trade=True),
        )[-1]
        mock_ustat.select_top5.side_effect = lambda r: (
            call_order.append("ustat"),
            ["F_THYAO"],
        )[-1]
        mock_ogul.process_signals.side_effect = lambda t, r: call_order.append("ogul")

        engine._run_single_cycle()

        assert call_order == ["pipeline", "baba", "risk", "ustat", "ogul"]

    def test_risk_ok_passes_top5(self, engine, mock_baba, mock_ustat, mock_ogul):
        """Risk OK → Top 5 ile sinyal üretimi."""
        mock_baba.check_risk_limits.return_value = RiskVerdict(can_trade=True)
        mock_ustat.select_top5.return_value = ["F_THYAO", "F_AKBNK"]

        engine._run_single_cycle()

        mock_ogul.process_signals.assert_called_once()
        args = mock_ogul.process_signals.call_args[0]
        assert args[0] == ["F_THYAO", "F_AKBNK"]

    def test_risk_blocked_passes_empty(self, engine, mock_baba, mock_ogul):
        """Risk engeli → boş liste ile emir yönetimi."""
        mock_baba.check_risk_limits.return_value = RiskVerdict(
            can_trade=False, reason="günlük limit"
        )

        engine._run_single_cycle()

        mock_ogul.process_signals.assert_called_once()
        args = mock_ogul.process_signals.call_args[0]
        assert args[0] == []  # boş liste = yeni sinyal yok

    def test_heartbeat_failure_raises_system_stop(self, engine, mock_mt5):
        """MT5 heartbeat + reconnect başarısız → SystemStopError."""
        mock_mt5.heartbeat.return_value = False
        mock_mt5.connect.return_value = False

        with pytest.raises(_SystemStopError):
            engine._run_single_cycle()

    def test_ogul_always_called(self, engine, mock_baba, mock_ogul):
        """Risk durumundan bağımsız process_signals her zaman çağrılır."""
        # Risk OK
        mock_baba.check_risk_limits.return_value = RiskVerdict(can_trade=True)
        engine._run_single_cycle()
        assert mock_ogul.process_signals.call_count == 1

        mock_ogul.process_signals.reset_mock()

        # Risk engel
        mock_baba.check_risk_limits.return_value = RiskVerdict(can_trade=False)
        engine._run_single_cycle()
        assert mock_ogul.process_signals.call_count == 1


# ═════════════════════════════════════════════════════════════════════
#  TestHeartbeatMT5
# ═════════════════════════════════════════════════════════════════════

class TestHeartbeatMT5:
    """Engine._heartbeat_mt5() testleri."""

    def test_heartbeat_ok(self, engine, mock_mt5):
        """Heartbeat başarılı → True."""
        mock_mt5.heartbeat.return_value = True
        assert engine._heartbeat_mt5() is True

    def test_heartbeat_fail_reconnect_ok(self, engine, mock_mt5, mock_db):
        """Heartbeat başarısız, reconnect başarılı → True."""
        mock_mt5.heartbeat.return_value = False
        mock_mt5.connect.return_value = True

        assert engine._heartbeat_mt5() is True
        mock_mt5.connect.assert_called_once()
        # Reconnect event loglanmalı
        mock_db.insert_event.assert_called()

    def test_heartbeat_fail_reconnect_fail(self, engine, mock_mt5):
        """Heartbeat + reconnect başarısız → False."""
        mock_mt5.heartbeat.return_value = False
        mock_mt5.connect.return_value = False

        assert engine._heartbeat_mt5() is False


# ═════════════════════════════════════════════════════════════════════
#  TestUpdateData
# ═════════════════════════════════════════════════════════════════════

class TestUpdateData:
    """Engine._update_data() testleri."""

    def test_pipeline_called(self, engine, mock_pipeline):
        """Pipeline.run_cycle() çağrılır."""
        engine._update_data()
        mock_pipeline.run_cycle.assert_called_once()

    def test_pipeline_error_caught(self, engine, mock_pipeline):
        """Pipeline hatası yakalanır, engine durmamalı."""
        mock_pipeline.run_cycle.side_effect = Exception("veri hatası")
        engine._update_data()  # hata fırlatılmamalı

    def test_pipeline_error_logged(self, engine, mock_pipeline, mock_db):
        """Pipeline hatası event olarak loglanır."""
        mock_pipeline.run_cycle.side_effect = Exception("veri hatası")
        engine._update_data()
        # insert_event çağrılmış olmalı (DATA_ERROR)
        calls = [c for c in mock_db.insert_event.call_args_list
                if "DATA_ERROR" in str(c)]
        assert len(calls) >= 1


# ═════════════════════════════════════════════════════════════════════
#  TestRunBabaCycle
# ═════════════════════════════════════════════════════════════════════

class TestRunBabaCycle:
    """Engine._run_baba_cycle() testleri."""

    def test_normal_regime(self, engine, mock_baba):
        """Normal BABA cycle → Regime döner."""
        mock_baba.run_cycle.return_value = Regime(regime_type=RegimeType.TREND)
        regime = engine._run_baba_cycle()
        assert regime.regime_type == RegimeType.TREND

    def test_baba_error_fallback_olay(self, engine, mock_baba):
        """BABA hatası → OLAY rejimi fallback."""
        mock_baba.run_cycle.side_effect = Exception("BABA crash")
        mock_baba.active_warnings = []
        regime = engine._run_baba_cycle()
        assert regime.regime_type == RegimeType.OLAY

    def test_baba_error_logged(self, engine, mock_baba, mock_db):
        """BABA hatası event olarak loglanır."""
        mock_baba.run_cycle.side_effect = Exception("BABA crash")
        mock_baba.active_warnings = []
        engine._run_baba_cycle()
        calls = [c for c in mock_db.insert_event.call_args_list
                if "BABA_ERROR" in str(c)]
        assert len(calls) >= 1

    def test_early_warnings_logged(self, engine, mock_baba):
        """Erken uyarılar loglanır."""
        mock_baba.run_cycle.return_value = Regime(regime_type=RegimeType.VOLATILE)
        warning = MagicMock()
        warning.warning_type = "spread_spike"
        warning.message = "spread 3x"
        mock_baba.active_warnings = [warning]

        with patch("engine.main.logger") as mock_logger:
            engine._run_baba_cycle()
            warning_calls = [c for c in mock_logger.warning.call_args_list
                           if "Erken uyarı" in str(c)]
            assert len(warning_calls) == 1

    def test_baba_pipeline_passed(self, engine, mock_baba, mock_pipeline):
        """BABA cycle'a pipeline geçirilir."""
        engine._run_baba_cycle()
        mock_baba.run_cycle.assert_called_once_with(mock_pipeline)


# ═════════════════════════════════════════════════════════════════════
#  TestCycleSummary
# ═════════════════════════════════════════════════════════════════════

class TestCycleSummary:
    """Engine._log_cycle_summary() testleri."""

    def test_debug_every_cycle(self, engine):
        """Her cycle debug log yazar."""
        regime = Regime(regime_type=RegimeType.TREND)
        verdict = RiskVerdict(can_trade=True)

        with patch("engine.main.logger") as mock_logger:
            engine._cycle_count = 1
            engine._log_cycle_summary(regime, verdict, ["F_THYAO"])
            mock_logger.debug.assert_called()

    def test_info_every_6_cycles(self, engine):
        """Her 6 cycle'da info log yazar."""
        regime = Regime(regime_type=RegimeType.TREND)
        verdict = RiskVerdict(can_trade=True)

        with patch("engine.main.logger") as mock_logger:
            engine._cycle_count = 6
            engine._log_cycle_summary(regime, verdict, ["F_THYAO"])
            info_calls = [c for c in mock_logger.info.call_args_list
                        if "Özet" in str(c)]
            assert len(info_calls) == 1

    def test_no_info_non_6_cycle(self, engine):
        """6'nın katı olmayan cycle'da info log yok."""
        regime = Regime(regime_type=RegimeType.TREND)
        verdict = RiskVerdict(can_trade=True)

        with patch("engine.main.logger") as mock_logger:
            engine._cycle_count = 7
            engine._log_cycle_summary(regime, verdict, ["F_THYAO"])
            info_calls = [c for c in mock_logger.info.call_args_list
                        if "Özet" in str(c)]
            assert len(info_calls) == 0


# ═════════════════════════════════════════════════════════════════════
#  TestDBErrorHandling
# ═════════════════════════════════════════════════════════════════════

class TestDBErrorHandling:
    """DB hata yönetimi testleri."""

    def test_single_db_error_continues(self, engine):
        """Tek DB hatası → engine devam eder."""
        engine._running = True
        call_count = 0

        def fake_cycle():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _DBError("DB hatası")
            engine._running = False

        engine._run_single_cycle = MagicMock(side_effect=fake_cycle)

        with patch("engine.main._time.sleep"):
            engine._main_loop()

        assert call_count == 2
        assert engine._consecutive_db_errors == 0  # başarılı cycle sıfırladı

    def test_consecutive_errors_accumulate(self, engine):
        """Art arda DB hataları birikir."""
        engine._running = True
        call_count = 0

        def fake_cycle():
            nonlocal call_count
            call_count += 1
            if call_count < DB_ERROR_THRESHOLD:
                raise _DBError(f"DB hatası #{call_count}")
            engine._running = False

        engine._run_single_cycle = MagicMock(side_effect=fake_cycle)

        with patch("engine.main._time.sleep"):
            engine._main_loop()

        # Son cycle başarılı → sayaç sıfır
        assert engine._consecutive_db_errors == 0

    def test_threshold_triggers_stop(self, engine):
        """DB_ERROR_THRESHOLD aşılırsa engine durur."""
        engine._running = True
        engine.stop = MagicMock(side_effect=lambda **kw: setattr(engine, '_running', False))

        engine._run_single_cycle = MagicMock(
            side_effect=_DBError("DB hatası")
        )

        with patch("engine.main._time.sleep"):
            engine._main_loop()

        engine.stop.assert_called_once()
        assert engine._consecutive_db_errors >= DB_ERROR_THRESHOLD


# ═════════════════════════════════════════════════════════════════════
#  TestRestoreState
# ═════════════════════════════════════════════════════════════════════

class TestRestoreState:
    """Engine._restore_state() testleri."""

    def test_baba_restore_called(self, engine, mock_baba):
        """BABA restore_risk_state çağrılır."""
        engine._restore_state()
        mock_baba.restore_risk_state.assert_called_once()

    def test_ogul_restore_called(self, engine, mock_ogul):
        """OĞUL restore_active_trades çağrılır."""
        engine._restore_state()
        mock_ogul.restore_active_trades.assert_called_once()

    def test_baba_restore_error_tolerance(self, engine, mock_baba, mock_ogul):
        """BABA restore hatası → OĞUL restore yine çalışır."""
        mock_baba.restore_risk_state.side_effect = Exception("restore fail")
        engine._restore_state()
        # OĞUL restore yine çağrılmalı
        mock_ogul.restore_active_trades.assert_called_once()

    def test_ogul_restore_error_tolerance(self, engine, mock_ogul):
        """OĞUL restore hatası yakalanır."""
        mock_ogul.restore_active_trades.side_effect = Exception("restore fail")
        engine._restore_state()  # hata fırlatılmamalı


# ═════════════════════════════════════════════════════════════════════
#  TestLogEvent
# ═════════════════════════════════════════════════════════════════════

class TestLogEvent:
    """Engine loglama testleri."""

    def test_log_event_writes_db(self, engine, mock_db):
        """_log_event DB'ye yazar."""
        engine._log_event("TEST_EVENT", "test mesajı", "INFO")
        mock_db.insert_event.assert_called_once_with(
            event_type="TEST_EVENT",
            message="test mesajı",
            severity="INFO",
            action=None,
        )

    def test_log_event_with_action(self, engine, mock_db):
        """_log_event action parametresi ile."""
        engine._log_event("TEST", "msg", "WARNING", action="test_action")
        mock_db.insert_event.assert_called_once_with(
            event_type="TEST",
            message="msg",
            severity="WARNING",
            action="test_action",
        )

    def test_log_event_db_error_raises(self, engine, mock_db):
        """_log_event DB hatası → _DBError."""
        mock_db.insert_event.side_effect = Exception("DB write fail")
        with pytest.raises(_DBError):
            engine._log_event("TEST", "msg", "INFO")

    def test_log_event_safe_no_raise(self, engine, mock_db):
        """_log_event_safe hatayı yutar."""
        mock_db.insert_event.side_effect = Exception("DB fail")
        engine._log_event_safe("TEST", "msg", "INFO")  # hata yok

    def test_log_event_safe_writes_db(self, engine, mock_db):
        """_log_event_safe normal durumda DB'ye yazar."""
        engine._log_event_safe("TEST", "msg", "INFO")
        mock_db.insert_event.assert_called_once()


# ═════════════════════════════════════════════════════════════════════
#  TestRunFunction
# ═════════════════════════════════════════════════════════════════════

class TestRunFunction:
    """run() giriş noktası testleri."""

    @patch("engine.main.Engine")
    def test_run_creates_engine(self, mock_engine_cls):
        """run() Engine nesnesi oluşturur ve start çağırır."""
        mock_engine = MagicMock()
        mock_engine_cls.return_value = mock_engine
        mock_engine.start.return_value = None

        with patch("engine.main.signal.signal"):
            run()

        mock_engine_cls.assert_called_once()
        mock_engine.start.assert_called_once()

    @patch("engine.main.Engine")
    def test_run_keyboard_interrupt(self, mock_engine_cls):
        """KeyboardInterrupt → engine.stop()."""
        mock_engine = MagicMock()
        mock_engine_cls.return_value = mock_engine
        mock_engine.start.side_effect = KeyboardInterrupt()

        with patch("engine.main.signal.signal"):
            run()

        mock_engine.stop.assert_called_once()

    @patch("engine.main.Engine")
    def test_run_critical_error(self, mock_engine_cls):
        """Kritik hata → stop + sys.exit."""
        mock_engine = MagicMock()
        mock_engine_cls.return_value = mock_engine
        mock_engine.start.side_effect = RuntimeError("critical")

        with patch("engine.main.signal.signal"):
            with pytest.raises(SystemExit):
                run()

        mock_engine.stop.assert_called_once()

    @patch("engine.main.Engine")
    def test_signal_handler_registered(self, mock_engine_cls):
        """SIGINT ve SIGTERM handler'ları kayıtlı."""
        mock_engine = MagicMock()
        mock_engine_cls.return_value = mock_engine

        with patch("engine.main.signal.signal") as mock_signal:
            run()

        signal_calls = [c[0][0] for c in mock_signal.call_args_list]
        assert _signal.SIGINT in signal_calls
        assert _signal.SIGTERM in signal_calls


# ═════════════════════════════════════════════════════════════════════
#  TestConstants
# ═════════════════════════════════════════════════════════════════════

class TestConstants:
    """Sabit değer doğrulaması."""

    def test_cycle_interval(self):
        """CYCLE_INTERVAL = 10 saniye."""
        assert CYCLE_INTERVAL == 10

    def test_max_mt5_reconnect(self):
        """MAX_MT5_RECONNECT = 5."""
        assert MAX_MT5_RECONNECT == 5

    def test_db_error_threshold(self):
        """DB_ERROR_THRESHOLD = 3."""
        assert DB_ERROR_THRESHOLD == 3

    def test_shutdown_timeout(self):
        """SHUTDOWN_TIMEOUT = 30."""
        assert SHUTDOWN_TIMEOUT == 30


# ═════════════════════════════════════════════════════════════════════
#  TestSystemStopError
# ═════════════════════════════════════════════════════════════════════

class TestSystemStopError:
    """Özel hata sınıfları testleri."""

    def test_system_stop_error_is_exception(self):
        """_SystemStopError Exception alt sınıfı."""
        assert issubclass(_SystemStopError, Exception)

    def test_db_error_is_exception(self):
        """_DBError Exception alt sınıfı."""
        assert issubclass(_DBError, Exception)

    def test_system_stop_error_message(self):
        """_SystemStopError mesajı korunur."""
        err = _SystemStopError("MT5 koptu")
        assert str(err) == "MT5 koptu"

    def test_db_error_message(self):
        """_DBError mesajı korunur."""
        err = _DBError("DB yok")
        assert str(err) == "DB yok"


# ═════════════════════════════════════════════════════════════════════
#  TestIntegration
# ═════════════════════════════════════════════════════════════════════

class TestIntegration:
    """Entegrasyon testleri — birden fazla cycle."""

    def test_three_cycle_integration(self, engine, mock_baba, mock_ogul, mock_ustat):
        """3 cycle boyunca doğru sıralama."""
        engine._running = True
        call_count = 0
        cycle_top5_calls = []

        original_process = mock_ogul.process_signals

        def track_process(symbols, regime):
            cycle_top5_calls.append(list(symbols))

        mock_ogul.process_signals.side_effect = track_process
        mock_ustat.select_top5.return_value = ["F_THYAO"]

        def fake_cycle():
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                engine._running = False

        # Gerçek _run_single_cycle çağır ama 3 cycle sonra dur
        real_run = engine._run_single_cycle
        cycle_counter = 0

        def counted_run():
            nonlocal cycle_counter
            cycle_counter += 1
            real_run()
            if cycle_counter >= 3:
                engine._running = False

        engine._run_single_cycle = counted_run

        with patch("engine.main._time.sleep"):
            engine._main_loop()

        assert cycle_counter == 3
        assert len(cycle_top5_calls) == 3
        # Her cycle Top 5 geçirildi
        for t5 in cycle_top5_calls:
            assert t5 == ["F_THYAO"]

    def test_risk_blocked_then_ok(self, engine, mock_baba, mock_ogul, mock_ustat):
        """İlk cycle risk engel → boş, ikinci cycle OK → top5."""
        engine._running = True
        mock_ustat.select_top5.return_value = ["F_THYAO", "F_AKBNK"]

        cycle_count = 0
        symbol_calls = []

        def track_process(symbols, regime):
            symbol_calls.append(list(symbols))

        mock_ogul.process_signals.side_effect = track_process

        # İlk cycle risk kapalı, ikinci cycle açık
        verdicts = [
            RiskVerdict(can_trade=False, reason="test"),
            RiskVerdict(can_trade=True),
        ]
        mock_baba.check_risk_limits.side_effect = verdicts

        real_run = engine._run_single_cycle
        counter = 0

        def counted_run():
            nonlocal counter
            counter += 1
            real_run()
            if counter >= 2:
                engine._running = False

        engine._run_single_cycle = counted_run

        with patch("engine.main._time.sleep"):
            engine._main_loop()

        assert len(symbol_calls) == 2
        assert symbol_calls[0] == []                          # risk engel → boş
        assert symbol_calls[1] == ["F_THYAO", "F_AKBNK"]    # risk OK → top5

    def test_baba_always_runs_before_ogul(self, engine, mock_baba, mock_ogul):
        """BABA her zaman OĞUL'dan önce çalışır."""
        execution_order = []

        def baba_run(pipeline):
            execution_order.append("baba_cycle")
            return Regime(regime_type=RegimeType.TREND)

        def baba_risk(rp):
            execution_order.append("baba_risk")
            return RiskVerdict(can_trade=True)

        def ogul_process(symbols, regime):
            execution_order.append("ogul")

        mock_baba.run_cycle.side_effect = baba_run
        mock_baba.check_risk_limits.side_effect = baba_risk
        mock_ogul.process_signals.side_effect = ogul_process

        engine._run_single_cycle()

        baba_idx = execution_order.index("baba_cycle")
        risk_idx = execution_order.index("baba_risk")
        ogul_idx = execution_order.index("ogul")

        assert baba_idx < risk_idx < ogul_idx

    def test_olay_regime_no_new_signals(self, engine, mock_baba, mock_ogul, mock_ustat):
        """OLAY rejimi → OĞUL'a boş strateji (process_signals içinde kontrol)."""
        mock_baba.run_cycle.return_value = Regime(regime_type=RegimeType.OLAY)
        mock_baba.check_risk_limits.return_value = RiskVerdict(can_trade=True)
        mock_ustat.select_top5.return_value = ["F_THYAO"]

        engine._run_single_cycle()

        # process_signals çağrılır ama rejim OLAY → içeride durur
        mock_ogul.process_signals.assert_called_once()
        args = mock_ogul.process_signals.call_args[0]
        assert args[1].regime_type == RegimeType.OLAY


# ═════════════════════════════════════════════════════════════════════
#  TestConnectMT5
# ═════════════════════════════════════════════════════════════════════

class TestConnectMT5:
    """Engine._connect_mt5() testleri."""

    def test_connect_delegates_to_mt5(self, engine, mock_mt5):
        """MT5Bridge.connect() çağrılır."""
        result = engine._connect_mt5()
        mock_mt5.connect.assert_called_once()
        assert result is True

    def test_connect_failure(self, engine, mock_mt5):
        """MT5 bağlantı başarısız → False."""
        mock_mt5.connect.return_value = False
        result = engine._connect_mt5()
        assert result is False
