"""ÜSTAT Engine — Sistem sağlığı metrik toplayıcı (memory-only).

Thread-safe, deque tabanlı metrik depolama.
DB'ye YAZMAZ — sadece bellekte tutar, API üzerinden okunur.
Overhead: ~0.01ms per cycle (perf_counter çağrıları).
"""

from __future__ import annotations

import threading
import time as _time
from collections import deque
from dataclasses import dataclass
from typing import Any


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
        }
