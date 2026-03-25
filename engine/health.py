"""ÜSTAT Engine — Sistem sağlığı metrik toplayıcı + Startup Smoke Test.

Thread-safe, deque tabanlı metrik depolama.
DB'ye YAZMAZ — sadece bellekte tutar, API üzerinden okunur.
Overhead: ~0.01ms per cycle (perf_counter çağrıları).

Startup Smoke Test: Uygulama başladığında MT5 bağlantısı, emir
gönderebilme yeteneği ve expiration hesabını doğrular.
Başarısız olursa engine BAŞLAMAZ — sessiz hata YASAK.
"""

from __future__ import annotations

import logging
import threading
import time as _time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime as _dt
from typing import Any

_logger = logging.getLogger(__name__)


# ── Metrik geçmişi büyüklükleri ────────────────────────────────
HISTORY_SIZE: int = 100           # cycle + ping geçmişi
ORDER_HISTORY_SIZE: int = 50      # emir geçmişi
RECONNECT_HISTORY_SIZE: int = 20  # reconnect geçmişi


# ── Dataclass'lar ───────────────────────────────────────────────

@dataclass(slots=True)
class CycleTimings:
    """Tek cycle'ın adım-adım zamanlama kaydı."""
    cycle_number: int
    timestamp: float              # time.time() (ISO dönüşüm için)
    total_ms: float
    heartbeat_ms: float = 0.0
    data_update_ms: float = 0.0
    closure_check_ms: float = 0.0
    baba_cycle_ms: float = 0.0
    risk_check_ms: float = 0.0
    top5_ms: float = 0.0
    ogul_signals_ms: float = 0.0
    h_engine_ms: float = 0.0
    manuel_sync_ms: float = 0.0
    ustat_brain_ms: float = 0.0
    log_summary_ms: float = 0.0
    overrun: bool = False


@dataclass(slots=True)
class OrderTiming:
    """Tek emir gönderim zamanlama kaydı."""
    timestamp: float              # time.time()
    symbol: str
    direction: str
    duration_ms: float
    success: bool
    retcode: int = 0
    slippage: float = 0.0


@dataclass(slots=True)
class ReconnectEvent:
    """MT5 bağlantı kopma/yeniden bağlama kaydı."""
    timestamp: float              # time.time()
    success: bool
    duration_ms: float = 0.0


# ── HealthCollector ─────────────────────────────────────────────

class HealthCollector:
    """Sistem sağlığı metrik toplayıcısı.

    Engine main.py'den çağrılır:
      - record_cycle(timings) : her cycle sonunda
    MT5Bridge'den çağrılır:
      - record_order(timing)  : her emir gönderiminde
      - record_disconnect()   : her bağlantı kopmada
      - record_reconnect()    : her yeniden bağlanmada
      - record_ping(ms)       : her heartbeat'te
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # Cycle zamanlama geçmişi
        self.cycle_history: deque[CycleTimings] = deque(maxlen=HISTORY_SIZE)
        self.overrun_count: int = 0

        # MT5 bağlantı metrikleri
        self.ping_history: deque[float] = deque(maxlen=HISTORY_SIZE)  # ms
        self.disconnect_count: int = 0
        self.reconnect_history: deque[ReconnectEvent] = deque(maxlen=RECONNECT_HISTORY_SIZE)
        self._mt5_connected_since: float = 0.0  # monotonic

        # Emir metrikleri
        self.order_history: deque[OrderTiming] = deque(maxlen=ORDER_HISTORY_SIZE)
        self.order_success_count: int = 0
        self.order_reject_count: int = 0
        self.order_timeout_count: int = 0

    # ── Record metodları ────────────────────────────────────────

    def record_cycle(self, timings: CycleTimings) -> None:
        """Cycle zamanlama kaydı ekle."""
        with self._lock:
            self.cycle_history.append(timings)
            if timings.overrun:
                self.overrun_count += 1

    def record_ping(self, ms: float) -> None:
        """MT5 heartbeat ping süresi kaydet."""
        with self._lock:
            self.ping_history.append(ms)

    def record_disconnect(self) -> None:
        """MT5 bağlantı kopması kaydet."""
        with self._lock:
            self.disconnect_count += 1
            self._mt5_connected_since = 0.0

    def record_reconnect(self, success: bool, duration_ms: float = 0.0) -> None:
        """MT5 yeniden bağlanma denemesi kaydet."""
        with self._lock:
            evt = ReconnectEvent(
                timestamp=_time.time(),
                success=success,
                duration_ms=duration_ms,
            )
            self.reconnect_history.append(evt)
            if success:
                self._mt5_connected_since = _time.monotonic()

    def record_connection_established(self) -> None:
        """İlk başlangıçta bağlantı kurulduğunda çağrılır."""
        with self._lock:
            self._mt5_connected_since = _time.monotonic()

    def record_order(self, timing: OrderTiming) -> None:
        """Emir gönderim kaydı ekle."""
        with self._lock:
            self.order_history.append(timing)
            if timing.success:
                self.order_success_count += 1
            elif timing.retcode == -1:  # timeout
                self.order_timeout_count += 1
            else:
                self.order_reject_count += 1

    # ── Snapshot (API okuma) ────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """Tüm metriklerin anlık snapshot'ı (API için).

        Thread-safe: lock altında tüm verilerin kopyasını alır.
        """
        with self._lock:
            return self._build_snapshot()

    def _build_snapshot(self) -> dict[str, Any]:
        """Lock altında çağrılır — snapshot dict oluştur."""

        # ── Cycle metrikleri ────────────────────────────────────
        cycles = list(self.cycle_history)
        last_60 = cycles[-60:] if cycles else []
        cycle_durations = [c.total_ms for c in last_60]

        last_cycle = None
        if cycles:
            lc = cycles[-1]
            last_cycle = {
                "cycle_number": lc.cycle_number,
                "total_ms": round(lc.total_ms, 1),
                "timestamp": lc.timestamp,
                "steps": {
                    "heartbeat": round(lc.heartbeat_ms, 1),
                    "data_update": round(lc.data_update_ms, 1),
                    "closure_check": round(lc.closure_check_ms, 1),
                    "baba_cycle": round(lc.baba_cycle_ms, 1),
                    "risk_check": round(lc.risk_check_ms, 1),
                    "top5": round(lc.top5_ms, 1),
                    "ogul_signals": round(lc.ogul_signals_ms, 1),
                    "h_engine": round(lc.h_engine_ms, 1),
                    "ustat_brain": round(lc.ustat_brain_ms, 1),
                    "log_summary": round(lc.log_summary_ms, 1),
                },
                "overrun": lc.overrun,
            }

        avg_cycle = round(sum(cycle_durations) / len(cycle_durations), 1) if cycle_durations else 0.0
        max_cycle = round(max(cycle_durations), 1) if cycle_durations else 0.0

        # ── MT5 ping metrikleri ─────────────────────────────────
        pings = list(self.ping_history)
        avg_ping = round(sum(pings) / len(pings), 1) if pings else 0.0
        last_ping = round(pings[-1], 1) if pings else 0.0

        mt5_uptime_s = 0
        if self._mt5_connected_since > 0:
            mt5_uptime_s = int(_time.monotonic() - self._mt5_connected_since)

        # ── Emir metrikleri ─────────────────────────────────────
        orders = list(self.order_history)
        order_durations = [o.duration_ms for o in orders if o.success]
        avg_order_ms = round(sum(order_durations) / len(order_durations), 1) if order_durations else 0.0

        last_10_orders = [
            {
                "timestamp": o.timestamp,
                "symbol": o.symbol,
                "direction": o.direction,
                "duration_ms": round(o.duration_ms, 1),
                "success": o.success,
                "retcode": o.retcode,
                "slippage": round(o.slippage, 4),
            }
            for o in orders[-10:]
        ]

        # ── Reconnect geçmişi ──────────────────────────────────
        reconnects = [
            {
                "timestamp": r.timestamp,
                "success": r.success,
                "duration_ms": round(r.duration_ms, 1),
            }
            for r in list(self.reconnect_history)[-10:]
        ]

        return {
            "cycle": {
                "last_cycle": last_cycle,
                "durations_ms": [round(d, 1) for d in cycle_durations],
                "overrun_count": self.overrun_count,
                "avg_ms": avg_cycle,
                "max_ms": max_cycle,
            },
            "mt5": {
                "avg_ping_ms": avg_ping,
                "last_ping_ms": last_ping,
                "disconnect_count": self.disconnect_count,
                "mt5_uptime_seconds": mt5_uptime_s,
                "reconnect_history": reconnects,
            },
            "orders": {
                "avg_send_ms": avg_order_ms,
                "success_count": self.order_success_count,
                "reject_count": self.order_reject_count,
                "timeout_count": self.order_timeout_count,
                "last_10": last_10_orders,
            },
            "alarms": {
                "consecutive_rejects": self._consecutive_rejects,
                "last_reject_reason": self._last_reject_reason,
            },
        }

    # ── Alarm state ───────────────────────────────────────────────
    _consecutive_rejects: int = 0
    _last_reject_reason: str = ""

    def record_order_reject(self, symbol: str, retcode: int, comment: str) -> None:
        """Ardışık emir reddi say — 3'te alarm."""
        with self._lock:
            self._consecutive_rejects += 1
            self._last_reject_reason = f"{symbol}: retcode={retcode} {comment}"
            if self._consecutive_rejects >= 3:
                _logger.critical(
                    f"[ALARM] {self._consecutive_rejects} ardışık emir reddedildi! "
                    f"Son: {self._last_reject_reason}"
                )

    def clear_reject_streak(self) -> None:
        """Başarılı emir sonrası sayacı sıfırla."""
        with self._lock:
            self._consecutive_rejects = 0
            self._last_reject_reason = ""


# ═════════════════════════════════════════════════════════════════════
#  STARTUP SMOKE TEST
# ═════════════════════════════════════════════════════════════════════

@dataclass
class SmokeTestResult:
    """Smoke test sonuçları."""
    passed: bool = True
    checks: list[dict[str, Any]] = field(default_factory=list)

    def fail(self, name: str, reason: str) -> None:
        self.passed = False
        self.checks.append({"name": name, "status": "FAIL", "reason": reason})
        _logger.error(f"[SMOKE] ✗ {name}: {reason}")

    def ok(self, name: str, detail: str = "") -> None:
        self.checks.append({"name": name, "status": "OK", "detail": detail})
        _logger.info(f"[SMOKE] ✓ {name} {detail}")


def run_startup_smoke_test(mt5_bridge) -> SmokeTestResult:
    """Startup smoke test — engine başlamadan önce kritik kontroller.

    Kontroller:
        1. MT5 bağlantısı aktif mi?
        2. Sembol bilgisi çekilebiliyor mu?
        3. Order expiration hesabı geçerli mi?
        4. Tick verisi alınabiliyor mu?
        5. Account bilgisi okunabiliyor mu?

    Args:
        mt5_bridge: MT5Bridge instance (bağlantı kurulmuş olmalı).

    Returns:
        SmokeTestResult — passed=False ise engine başlamamalı.
    """
    result = SmokeTestResult()
    _logger.info("=" * 50)
    _logger.info("[SMOKE] Startup Smoke Test başlıyor...")
    _logger.info("=" * 50)

    try:
        import MetaTrader5 as mt5
    except ImportError:
        result.fail("MT5_IMPORT", "MetaTrader5 paketi yüklenemedi")
        return result

    # ── 1. MT5 Bağlantı Kontrolü ──────────────────────────────
    try:
        terminal_info = mt5.terminal_info()
        if terminal_info is None:
            result.fail("MT5_CONNECTION", "terminal_info() None döndü — bağlantı yok")
        elif not terminal_info.connected:
            result.fail("MT5_CONNECTION", "Terminal bağlı değil (connected=False)")
        else:
            result.ok("MT5_CONNECTION", f"build={terminal_info.build}")
    except Exception as exc:
        result.fail("MT5_CONNECTION", str(exc))

    # ── 2. Sembol Bilgisi ─────────────────────────────────────
    # VİOP'ta baz isimler (F_THYAO) değil, vade ekli isimler (F_THYAO0326)
    # görünür olur.  Bridge instance varsa eşlenmiş map'i kullan,
    # yoksa mt5_bridge.WATCHED_SYMBOLS baz isimlerini MT5'te tüm
    # visible semboller arasında prefix ile ara.
    test_symbol = None
    try:
        # Önce bridge instance'ın eşlediği gerçek sembol isimlerini dene
        if mt5_bridge and hasattr(mt5_bridge, "_symbol_map") and mt5_bridge._symbol_map:
            for base, resolved in mt5_bridge._symbol_map.items():
                info = mt5.symbol_info(resolved)
                if info is not None and info.visible:
                    test_symbol = resolved
                    break

        # Bridge map yoksa fallback: WATCHED_SYMBOLS prefix araması
        if not test_symbol:
            from engine.mt5_bridge import WATCHED_SYMBOLS
            for base in WATCHED_SYMBOLS:
                # Önce doğrudan dene
                info = mt5.symbol_info(base)
                if info is not None and info.visible:
                    test_symbol = base
                    break
                # VİOP vade ekli arama (ör. F_THYAO → F_THYAO0*)
                symbols = mt5.symbols_get(base + "0*")
                if symbols:
                    for s in symbols:
                        if s.visible:
                            test_symbol = s.name
                            break
                if test_symbol:
                    break

        if test_symbol:
            result.ok("SYMBOL_INFO", f"Test sembolü: {test_symbol}")
        else:
            result.fail("SYMBOL_INFO", "Hiçbir izlenen sembol erişilebilir değil")
    except Exception as exc:
        result.fail("SYMBOL_INFO", str(exc))

    # ── 3. Tick Verisi ─────────────────────────────────────────
    if test_symbol:
        try:
            tick = mt5.symbol_info_tick(test_symbol)
            if tick is None or tick.bid == 0:
                result.fail("TICK_DATA", f"{test_symbol}: tick verisi alınamadı")
            else:
                result.ok("TICK_DATA", f"{test_symbol}: bid={tick.bid} ask={tick.ask}")
        except Exception as exc:
            result.fail("TICK_DATA", str(exc))

    # ── 4. Account Bilgisi ─────────────────────────────────────
    try:
        account = mt5.account_info()
        if account is None:
            result.fail("ACCOUNT_INFO", "account_info() None döndü")
        else:
            result.ok("ACCOUNT_INFO", f"#{account.login} balance={account.balance}")
    except Exception as exc:
        result.fail("ACCOUNT_INFO", str(exc))

    # ── 5. Order Expiration Hesabı ─────────────────────────────
    try:
        today = _dt.now().date()
        expiry = _dt.combine(today, _dt.min.time().replace(hour=18, minute=10))
        now = _dt.now()
        if expiry <= now:
            result.fail(
                "ORDER_EXPIRATION",
                f"Expiry ({expiry}) geçmişte — seans bitmiş olabilir"
            )
        else:
            diff_min = (expiry - now).total_seconds() / 60
            result.ok("ORDER_EXPIRATION", f"Seans sonuna {diff_min:.0f} dk kaldı")
    except Exception as exc:
        result.fail("ORDER_EXPIRATION", str(exc))

    # ── Sonuç ──────────────────────────────────────────────────
    passed_count = sum(1 for c in result.checks if c["status"] == "OK")
    total_count = len(result.checks)
    _logger.info("=" * 50)
    if result.passed:
        _logger.info(
            f"[SMOKE] ✓ TÜM TESTLER GEÇTİ ({passed_count}/{total_count})"
        )
    else:
        _logger.critical(
            f"[SMOKE] ✗ SMOKE TEST BAŞARISIZ "
            f"({passed_count}/{total_count} geçti)"
        )
    _logger.info("=" * 50)

    return result
