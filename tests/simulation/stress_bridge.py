"""StressTestBridge — MockBridge3 üzerine hata enjeksiyon altyapısı.

FAZ-1.1: Stres testi için genişletilmiş mock MT5 bridge.
10 hata modu destekler:
    1. Bağlantı kopuşu (disconnect)
    2. Yüksek gecikme (latency injection)
    3. API timeout (>5sn)
    4. Kısmi dolum (partial fill)
    5. Emir reddi (order reject)
    6. Netting hatası (position mismatch)
    7. Rate limiting (API limit)
    8. Veri boşluğu (data gap / stale)
    9. Bozuk yanıt (corrupt response)
    10. Gateway yükü (slow response)

Kullanım:
    bridge = StressTestBridge(pgen, balance, db=db, fault_profile="normal")
    bridge.inject_fault("disconnect", duration=5.0)
    bridge.inject_fault("latency", min_ms=100, max_ms=500)
    bridge.inject_fault("timeout", probability=0.1)
"""

from __future__ import annotations

import random
import time
import threading
from datetime import datetime, timedelta
from collections import defaultdict, deque
from typing import Any
from dataclasses import dataclass, field

import numpy as np


# ══════════════════════════════════════════════════════════════════════
#  HATA PROFİLLERİ
# ══════════════════════════════════════════════════════════════════════

FAULT_PROFILES = {
    "normal": {},
    "light_stress": {
        "latency": {"enabled": True, "min_ms": 10, "max_ms": 100, "probability": 0.05},
        "timeout": {"enabled": True, "probability": 0.01},
        "reject": {"enabled": True, "probability": 0.02},
    },
    "medium_stress": {
        "latency": {"enabled": True, "min_ms": 50, "max_ms": 300, "probability": 0.10},
        "timeout": {"enabled": True, "probability": 0.03},
        "reject": {"enabled": True, "probability": 0.05},
        "partial_fill": {"enabled": True, "probability": 0.05, "fill_pct_range": (0.3, 0.8)},
        "disconnect": {"enabled": True, "probability": 0.005, "duration_s": 3.0},
    },
    "heavy_stress": {
        "latency": {"enabled": True, "min_ms": 100, "max_ms": 500, "probability": 0.20},
        "timeout": {"enabled": True, "probability": 0.08},
        "reject": {"enabled": True, "probability": 0.10},
        "partial_fill": {"enabled": True, "probability": 0.10, "fill_pct_range": (0.2, 0.7)},
        "disconnect": {"enabled": True, "probability": 0.01, "duration_s": 5.0},
        "data_gap": {"enabled": True, "probability": 0.05},
        "corrupt": {"enabled": True, "probability": 0.02},
        "rate_limit": {"enabled": True, "max_per_second": 5},
    },
    "chaos": {
        "latency": {"enabled": True, "min_ms": 200, "max_ms": 1000, "probability": 0.30},
        "timeout": {"enabled": True, "probability": 0.15},
        "reject": {"enabled": True, "probability": 0.15},
        "partial_fill": {"enabled": True, "probability": 0.15, "fill_pct_range": (0.1, 0.6)},
        "disconnect": {"enabled": True, "probability": 0.03, "duration_s": 10.0},
        "data_gap": {"enabled": True, "probability": 0.10},
        "corrupt": {"enabled": True, "probability": 0.05},
        "rate_limit": {"enabled": True, "max_per_second": 3},
        "gateway_slow": {"enabled": True, "probability": 0.10, "delay_s_range": (2.0, 5.0)},
        "netting_error": {"enabled": True, "probability": 0.02},
    },
}


# ══════════════════════════════════════════════════════════════════════
#  STRES METRİK TOPLAYICI
# ══════════════════════════════════════════════════════════════════════

@dataclass
class StressMetrics:
    """Stres testi boyunca toplanan tüm metrikler."""

    # ── Emir metrikleri ──
    total_orders_sent: int = 0
    total_orders_filled: int = 0
    total_orders_rejected: int = 0
    total_orders_timed_out: int = 0
    total_partial_fills: int = 0

    # ── Bağlantı metrikleri ──
    total_disconnects: int = 0
    total_reconnects: int = 0
    max_disconnect_duration_s: float = 0.0
    total_disconnect_time_s: float = 0.0

    # ── Gecikme metrikleri ──
    latency_samples: list = field(default_factory=list)
    order_latencies_ms: list = field(default_factory=list)

    # ── Hata metrikleri ──
    total_timeouts: int = 0
    total_data_gaps: int = 0
    total_corrupt_responses: int = 0
    total_rate_limited: int = 0
    total_netting_errors: int = 0
    total_gateway_slow: int = 0

    # ── Kaynak metrikleri ──
    peak_memory_mb: float = 0.0
    peak_positions: int = 0
    peak_pending_events: int = 0

    # ── Kurtarma metrikleri ──
    circuit_breaker_trips: int = 0
    auto_recoveries: int = 0
    failed_recoveries: int = 0

    # ── Zamanlama ──
    cycle_durations_ms: list = field(default_factory=list)

    def summary(self) -> dict:
        """Özet metrikleri döndür."""
        lat = self.latency_samples if self.latency_samples else [0]
        ord_lat = self.order_latencies_ms if self.order_latencies_ms else [0]
        cyc = self.cycle_durations_ms if self.cycle_durations_ms else [0]
        return {
            "orders": {
                "sent": self.total_orders_sent,
                "filled": self.total_orders_filled,
                "rejected": self.total_orders_rejected,
                "timed_out": self.total_orders_timed_out,
                "partial": self.total_partial_fills,
                "fill_rate": (self.total_orders_filled / max(self.total_orders_sent, 1)) * 100,
            },
            "connection": {
                "disconnects": self.total_disconnects,
                "reconnects": self.total_reconnects,
                "max_disconnect_s": round(self.max_disconnect_duration_s, 2),
                "total_downtime_s": round(self.total_disconnect_time_s, 2),
            },
            "latency_ms": {
                "p50": round(float(np.percentile(lat, 50)), 2) if lat else 0,
                "p95": round(float(np.percentile(lat, 95)), 2) if lat else 0,
                "p99": round(float(np.percentile(lat, 99)), 2) if lat else 0,
                "max": round(max(lat), 2) if lat else 0,
            },
            "order_latency_ms": {
                "p50": round(float(np.percentile(ord_lat, 50)), 2) if ord_lat else 0,
                "p95": round(float(np.percentile(ord_lat, 95)), 2) if ord_lat else 0,
                "p99": round(float(np.percentile(ord_lat, 99)), 2) if ord_lat else 0,
            },
            "cycle_duration_ms": {
                "p50": round(float(np.percentile(cyc, 50)), 2) if cyc else 0,
                "p95": round(float(np.percentile(cyc, 95)), 2) if cyc else 0,
                "p99": round(float(np.percentile(cyc, 99)), 2) if cyc else 0,
                "max": round(max(cyc), 2) if cyc else 0,
            },
            "errors": {
                "timeouts": self.total_timeouts,
                "data_gaps": self.total_data_gaps,
                "corrupt": self.total_corrupt_responses,
                "rate_limited": self.total_rate_limited,
                "netting_errors": self.total_netting_errors,
                "gateway_slow": self.total_gateway_slow,
            },
            "recovery": {
                "circuit_breaker_trips": self.circuit_breaker_trips,
                "auto_recoveries": self.auto_recoveries,
                "failed_recoveries": self.failed_recoveries,
            },
            "resources": {
                "peak_memory_mb": round(self.peak_memory_mb, 1),
                "peak_positions": self.peak_positions,
                "peak_pending_events": self.peak_pending_events,
            },
        }


# ══════════════════════════════════════════════════════════════════════
#  STRES TEST BRIDGE
# ══════════════════════════════════════════════════════════════════════

class StressTestBridge:
    """MockBridge3 üzerine hata enjeksiyonu ekleyen stres testi bridge'i.

    Normal MockBridge3 gibi çalışır ama her API çağrısında olasılıksal
    hata enjeksiyonu yapabilir.
    """

    TF_MAP = {1: "M1", 5: "M5", 15: "M15", 16385: "H1"}
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_H1 = 16385

    def __init__(self, pgen, balance: float, db=None, time_fn=None,
                 fault_profile: str = "normal", symbols=None, contract_sizes=None):
        self._gen = pgen
        self._connected = True
        self._balance = balance
        self._equity = balance
        self._health = None
        self._db = db
        self._time_fn = time_fn or datetime.now
        self._symbols = symbols or ["F_THYAO", "F_AKBNK", "F_XU030"]
        self._contract_sizes = contract_sizes or {"F_THYAO": 100, "F_AKBNK": 100, "F_XU030": 1}
        self._symbol_map = {s: s for s in self._symbols}
        self._reverse_map = {s: s for s in self._symbols}
        self._map_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._positions: list[dict] = []
        self._next_ticket = 300000
        self._trade_log: list[dict] = []

        # ── İstatistikler ──
        self._sl_close_count = 0
        self._tp_close_count = 0
        self._total_realized_pnl = 0.0

        # ── Hata enjeksiyon ayarları ──
        self._fault_config = dict(FAULT_PROFILES.get(fault_profile, {}))
        self._active_faults: dict[str, dict] = {}
        self._metrics = StressMetrics()

        # ── Circuit breaker state ──
        self._consecutive_failures = 0
        self._cb_tripped = False
        self._cb_trip_time = 0.0
        self._cb_cooldown_s = 30.0

        # ── Rate limiter state ──
        self._call_timestamps: deque = deque(maxlen=100)

        # ── Disconnect state ──
        self._disconnect_start = 0.0
        self._disconnect_duration = 0.0

    # ──────────────────────────────────────────────────────────────
    #  HATA ENJEKSİYON API
    # ──────────────────────────────────────────────────────────────

    def inject_fault(self, fault_type: str, **kwargs):
        """Hata modu enjekte et veya güncelle."""
        kwargs["enabled"] = True
        self._fault_config[fault_type] = kwargs

    def clear_fault(self, fault_type: str):
        """Hata modunu kaldır."""
        self._fault_config.pop(fault_type, None)

    def clear_all_faults(self):
        """Tüm hata modlarını temizle."""
        self._fault_config.clear()

    def set_profile(self, profile: str):
        """Hazır hata profili uygula."""
        self._fault_config = dict(FAULT_PROFILES.get(profile, {}))

    @property
    def metrics(self) -> StressMetrics:
        return self._metrics

    # ──────────────────────────────────────────────────────────────
    #  DAHİLİ HATA KONTROL
    # ──────────────────────────────────────────────────────────────

    def _should_inject(self, fault_type: str) -> bool:
        """Belirli bir hata tipinin tetiklenmesi gerekiyor mu?"""
        cfg = self._fault_config.get(fault_type, {})
        if not cfg.get("enabled", False):
            return False
        prob = cfg.get("probability", 0.0)
        return random.random() < prob

    def _apply_latency(self):
        """Gecikme enjekte et (simüle)."""
        cfg = self._fault_config.get("latency", {})
        if not cfg.get("enabled", False):
            return 0.0
        if random.random() < cfg.get("probability", 0.0):
            ms = random.uniform(cfg.get("min_ms", 10), cfg.get("max_ms", 100))
            self._metrics.latency_samples.append(ms)
            return ms
        return 0.0

    def _check_disconnect(self) -> bool:
        """Bağlantı kopukluk durumunu kontrol et."""
        # Aktif kopukluk varsa süresini kontrol et
        if not self._connected:
            elapsed = time.monotonic() - self._disconnect_start
            if elapsed >= self._disconnect_duration:
                self._connected = True
                self._metrics.total_reconnects += 1
                self._metrics.auto_recoveries += 1
                dur = elapsed
                self._metrics.total_disconnect_time_s += dur
                if dur > self._metrics.max_disconnect_duration_s:
                    self._metrics.max_disconnect_duration_s = dur
                return False  # Artık bağlı
            return True  # Hâlâ kopuk

        # Yeni kopukluk tetikle
        if self._should_inject("disconnect"):
            cfg = self._fault_config["disconnect"]
            self._connected = False
            self._disconnect_start = time.monotonic()
            self._disconnect_duration = cfg.get("duration_s", 3.0)
            self._metrics.total_disconnects += 1
            return True

        return False

    def _check_rate_limit(self) -> bool:
        """Rate limit kontrolü."""
        cfg = self._fault_config.get("rate_limit", {})
        if not cfg.get("enabled", False):
            return False
        max_per_sec = cfg.get("max_per_second", 10)
        now = time.monotonic()
        self._call_timestamps.append(now)
        # Son 1 saniyedeki çağrı sayısı
        recent = sum(1 for t in self._call_timestamps if now - t < 1.0)
        if recent > max_per_sec:
            self._metrics.total_rate_limited += 1
            return True
        return False

    def _check_circuit_breaker(self) -> bool:
        """Circuit breaker aktif mi?"""
        if self._cb_tripped:
            if time.monotonic() - self._cb_trip_time >= self._cb_cooldown_s:
                self._cb_tripped = False
                self._consecutive_failures = 0
                return False
            return True
        return False

    def _record_failure(self):
        """Ardışık hata say, gerekirse circuit breaker tetikle."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= 5:
            self._cb_tripped = True
            self._cb_trip_time = time.monotonic()
            self._metrics.circuit_breaker_trips += 1
            self._consecutive_failures = 0

    def _record_success(self):
        """Başarılı çağrıda ardışık hata sayacını sıfırla."""
        self._consecutive_failures = 0

    # ──────────────────────────────────────────────────────────────
    #  BRIDGE API (MockBridge3 uyumlu)
    # ──────────────────────────────────────────────────────────────

    def is_connected(self):
        return self._connected and not self._cb_tripped

    def connect(self, launch=True):
        self._connected = True
        return True

    def disconnect(self):
        self._connected = False

    def heartbeat(self):
        if self._check_disconnect():
            return False
        return True

    def _to_mt5(self, s): return s
    def _to_base(self, s): return s
    def _is_watched(self, s): return s in self._symbols

    def get_account_info(self):
        if self._check_disconnect():
            return None
        from engine.mt5_bridge import AccountInfo
        fl = sum(p.get("profit", 0) for p in self._positions)
        self._equity = self._balance + fl
        return AccountInfo(
            login=99999, server="STRESS-TEST", balance=self._balance,
            equity=self._equity, margin=len(self._positions) * 500.0,
            free_margin=self._equity - len(self._positions) * 500.0,
            margin_level=9999.0 if not self._positions else
                (self._equity / (len(self._positions) * 500.0)) * 100,
            currency="TRY",
        )

    def get_symbol_info(self, symbol):
        if self._check_disconnect():
            return None
        from engine.mt5_bridge import SymbolInfo
        price = self._gen._prices.get(symbol, 100.0)
        cs = self._contract_sizes.get(symbol, 100)
        return SymbolInfo(
            name=symbol, point=0.01, trade_contract_size=cs,
            trade_tick_value=cs * 0.01, volume_min=1.0, volume_max=50.0,
            volume_step=1.0, bid=round(price - 0.01, 2),
            ask=round(price + 0.01, 2), spread=2,
        )

    def get_bars(self, symbol, timeframe=5, count=500):
        import pandas as pd
        if self._check_disconnect():
            return pd.DataFrame(columns=["time", "open", "high", "low", "close",
                                         "tick_volume", "spread", "real_volume"])

        # Veri boşluğu enjeksiyonu
        if self._should_inject("data_gap"):
            self._metrics.total_data_gaps += 1
            return pd.DataFrame(columns=["time", "open", "high", "low", "close",
                                         "tick_volume", "spread", "real_volume"])

        # Bozuk veri enjeksiyonu
        if self._should_inject("corrupt"):
            self._metrics.total_corrupt_responses += 1
            df = self._gen.generate_bars(symbol,
                                          self.TF_MAP.get(timeframe, "M5"), count)
            if len(df) > 0:
                # NaN enjekte
                corrupt_idx = random.sample(range(len(df)), min(5, len(df)))
                for idx in corrupt_idx:
                    df.iloc[idx, df.columns.get_loc("close")] = float("nan")
            return df

        if symbol not in self._symbols:
            return pd.DataFrame(columns=["time", "open", "high", "low", "close",
                                         "tick_volume", "spread", "real_volume"])
        tf_str = self.TF_MAP.get(timeframe, "M5")
        self._apply_latency()
        return self._gen.generate_bars(symbol, tf_str, count)

    def get_tick(self, symbol):
        if self._check_disconnect():
            return None
        from engine.mt5_bridge import Tick
        t = self._gen.generate_tick(symbol)
        self._apply_latency()
        return Tick(symbol=t["symbol"], bid=t["bid"], ask=t["ask"],
                    spread=t["spread"], time=t["time"])

    def positions_get(self):
        return self._positions

    def get_history_for_sync(self, days=90):
        return []

    def get_positions(self):
        self.update_floating_pnl()
        result = []
        for p in self._positions:
            tick = self._gen.generate_tick(p["symbol"])
            result.append({
                "ticket": p["ticket"], "symbol": p["symbol"],
                "type": "BUY" if p["type"] == 0 else "SELL",
                "volume": p["volume"], "price_open": p["price_open"],
                "sl": p.get("sl", 0.0), "tp": p.get("tp", 0.0),
                "price_current": tick["bid"] if p["type"] == 0 else tick["ask"],
                "profit": p["profit"], "swap": 0.0,
                "time": datetime.fromtimestamp(
                    p.get("time", datetime.now().timestamp())
                ).isoformat(),
            })
        self._metrics.peak_positions = max(self._metrics.peak_positions, len(result))
        return result

    def send_order(self, symbol, direction, lot, price,
                   sl=0.0, tp=0.0, order_type="market"):
        """Emir gönder — hata enjeksiyonu dahil."""
        t0 = time.monotonic()
        self._metrics.total_orders_sent += 1

        # ── Bağlantı kontrol ──
        if self._check_disconnect():
            self._record_failure()
            self._metrics.total_orders_timed_out += 1
            return None

        # ── Circuit breaker ──
        if self._check_circuit_breaker():
            self._metrics.total_orders_rejected += 1
            return None

        # ── Rate limit ──
        if self._check_rate_limit():
            return None

        # ── Timeout enjeksiyonu ──
        if self._should_inject("timeout"):
            self._record_failure()
            self._metrics.total_timeouts += 1
            self._metrics.total_orders_timed_out += 1
            return None

        # ── Emir reddi enjeksiyonu ──
        if self._should_inject("reject"):
            self._record_failure()
            self._metrics.total_orders_rejected += 1
            return {"retcode": 10016, "comment": "STRESS_REJECT"}

        # ── Gateway yavaşlık ──
        if self._should_inject("gateway_slow"):
            self._metrics.total_gateway_slow += 1
            # Simüle — gerçek bekleme yapmıyoruz, sadece metrik

        # ── Gecikme ──
        latency = self._apply_latency()

        # ── Kısmi dolum ──
        actual_lot = lot
        if self._should_inject("partial_fill"):
            cfg = self._fault_config["partial_fill"]
            fill_range = cfg.get("fill_pct_range", (0.3, 0.8))
            fill_pct = random.uniform(*fill_range)
            actual_lot = max(1.0, round(lot * fill_pct))
            self._metrics.total_partial_fills += 1

        # ── Netting hatası ──
        if self._should_inject("netting_error"):
            self._metrics.total_netting_errors += 1
            # Netting hatasında emir gider ama yanlış fiyatla
            tick = self._gen.generate_tick(symbol)
            entry = tick["ask"] if direction == "BUY" else tick["bid"]
            # %1 slippage enjekte
            entry *= (1.01 if direction == "BUY" else 0.99)

            self._next_ticket += 1
            pos = {
                "ticket": self._next_ticket, "symbol": symbol,
                "type": 0 if direction == "BUY" else 1,
                "volume": actual_lot, "price_open": round(entry, 2),
                "sl": sl or 0.0, "tp": tp or 0.0, "profit": 0.0,
                "comment": f"STRESS_NETTING_ERR", "magic": 0,
                "time": int(self._time_fn().timestamp()),
            }
            self._positions.append(pos)
            self._metrics.total_orders_filled += 1
            self._record_success()
            elapsed = (time.monotonic() - t0) * 1000
            self._metrics.order_latencies_ms.append(elapsed + latency)
            return {"retcode": 10009, "order": self._next_ticket,
                    "deal": self._next_ticket, "volume": actual_lot,
                    "price": round(entry, 2), "comment": "STRESS_NETTING_ERR"}

        # ── Normal emir ──
        tick = self._gen.generate_tick(symbol)
        entry = tick["ask"] if direction == "BUY" else tick["bid"]
        self._next_ticket += 1
        pos = {
            "ticket": self._next_ticket, "symbol": symbol,
            "type": 0 if direction == "BUY" else 1,
            "volume": actual_lot, "price_open": entry,
            "sl": sl or 0.0, "tp": tp or 0.0, "profit": 0.0,
            "comment": f"STRESS_{order_type}", "magic": 0,
            "time": int(self._time_fn().timestamp()),
        }
        self._positions.append(pos)
        self._metrics.total_orders_filled += 1
        self._record_success()

        elapsed = (time.monotonic() - t0) * 1000
        self._metrics.order_latencies_ms.append(elapsed + latency)

        self._trade_log.append({
            "event": "OPEN", "ticket": self._next_ticket, "symbol": symbol,
            "direction": direction, "lot": actual_lot, "entry": entry,
            "sl": sl, "tp": tp, "time": self._time_fn().isoformat(),
            "latency_ms": round(elapsed + latency, 2),
        })
        return {"retcode": 10009, "order": self._next_ticket,
                "deal": self._next_ticket, "volume": actual_lot,
                "price": entry, "comment": f"STRESS_{order_type}"}

    def close_position(self, ticket):
        if self._check_disconnect():
            return None
        if self._should_inject("timeout"):
            self._metrics.total_timeouts += 1
            return None
        for i, p in enumerate(self._positions):
            if p["ticket"] == ticket:
                tick = self._gen.generate_tick(p["symbol"])
                exit_p = tick["bid"] if p["type"] == 0 else tick["ask"]
                cs = self._contract_sizes.get(p["symbol"], 100)
                pnl = (exit_p - p["price_open"]) * p["volume"] * cs
                if p["type"] == 1:
                    pnl = -pnl
                self._balance += pnl
                self._total_realized_pnl += pnl
                self._positions.pop(i)
                return {"retcode": 10009, "order": ticket, "profit": pnl}
        return None

    def check_order_status(self, order_ticket):
        return {"status": "filled", "filled_volume": 1.0,
                "remaining_volume": 0.0, "deal_ticket": order_ticket}

    def get_pending_orders(self):
        return []

    def cancel_order(self, order_ticket):
        return {"retcode": 10009}

    def send_market_order(self, symbol, direction, lot, sl=0.0, tp=0.0, comment=""):
        return self.send_order(symbol, direction, lot, 0.0,
                               sl=sl, tp=tp, order_type="market")

    def close_position_partial(self, ticket, volume):
        if self._check_disconnect():
            return None
        for p in self._positions:
            if p["ticket"] == ticket:
                if volume >= p["volume"]:
                    return self.close_position(ticket)
                p["volume"] -= volume
                tick = self._gen.generate_tick(p["symbol"])
                cs = self._contract_sizes.get(p["symbol"], 100)
                exit_p = tick["bid"] if p["type"] == 0 else tick["ask"]
                if p["type"] == 0:
                    pnl = (exit_p - p["price_open"]) * volume * cs
                else:
                    pnl = (p["price_open"] - exit_p) * volume * cs
                self._balance += pnl
                self._total_realized_pnl += pnl
                self._tp_close_count += 1
                return {"retcode": 10009, "order": ticket, "profit": pnl}
        return None

    def get_deal_summary(self, ticket):
        return None

    def modify_position(self, ticket, sl=None, tp=None):
        if self._check_disconnect():
            return None
        if self._should_inject("timeout"):
            self._metrics.total_timeouts += 1
            return None
        for p in self._positions:
            if p["ticket"] == ticket:
                if sl is not None:
                    p["sl"] = sl
                if tp is not None:
                    p["tp"] = tp
                return {"retcode": 10009}
        return None

    def update_floating_pnl(self):
        """Kayan K/Z güncelle + SL/TP tetikle."""
        closed = []
        for p in self._positions:
            tick = self._gen.generate_tick(p["symbol"])
            cs = self._contract_sizes.get(p["symbol"], 100)
            if p["type"] == 0:  # BUY
                cur = tick["bid"]
                p["profit"] = (cur - p["price_open"]) * p["volume"] * cs
                if p["sl"] > 0 and cur <= p["sl"]:
                    pnl = (p["sl"] - p["price_open"]) * p["volume"] * cs
                    self._balance += pnl
                    self._total_realized_pnl += pnl
                    self._sl_close_count += 1
                    p["_pnl"] = pnl
                    p["_reason"] = "SL_HIT"
                    closed.append(p["ticket"])
                    continue
                if p["tp"] > 0 and cur >= p["tp"]:
                    pnl = (p["tp"] - p["price_open"]) * p["volume"] * cs
                    self._balance += pnl
                    self._total_realized_pnl += pnl
                    self._tp_close_count += 1
                    p["_pnl"] = pnl
                    p["_reason"] = "TP_HIT"
                    closed.append(p["ticket"])
                    continue
            else:  # SELL
                cur = tick["ask"]
                p["profit"] = (p["price_open"] - cur) * p["volume"] * cs
                if p["sl"] > 0 and cur >= p["sl"]:
                    pnl = (p["price_open"] - p["sl"]) * p["volume"] * cs
                    self._balance += pnl
                    self._total_realized_pnl += pnl
                    self._sl_close_count += 1
                    p["_pnl"] = pnl
                    p["_reason"] = "SL_HIT"
                    closed.append(p["ticket"])
                    continue
                if p["tp"] > 0 and cur <= p["tp"]:
                    pnl = (p["price_open"] - p["tp"]) * p["volume"] * cs
                    self._balance += pnl
                    self._total_realized_pnl += pnl
                    self._tp_close_count += 1
                    p["_pnl"] = pnl
                    p["_reason"] = "TP_HIT"
                    closed.append(p["ticket"])
                    continue

        if closed:
            for p in self._positions:
                if p["ticket"] in closed:
                    self._record_close(p)
            self._positions = [p for p in self._positions if p["ticket"] not in closed]

    def _record_close(self, pos):
        if not self._db:
            return
        try:
            sim_now = self._time_fn()
            direction = "BUY" if pos["type"] == 0 else "SELL"
            pnl = pos.get("_pnl", pos.get("profit", 0))
            reason = pos.get("_reason", "UNKNOWN")
            entry_t = datetime.fromtimestamp(pos.get("time", sim_now.timestamp()))
            self._db.insert_trade({
                "strategy": "STRESS_SIM", "symbol": pos["symbol"],
                "direction": direction,
                "entry_time": entry_t.strftime("%Y-%m-%d %H:%M:%S"),
                "exit_time": sim_now.strftime("%Y-%m-%d %H:%M:%S"),
                "entry_price": pos["price_open"],
                "exit_price": pos.get("sl", 0) if reason == "SL_HIT" else pos.get("tp", 0),
                "lot": pos["volume"], "pnl": round(pnl, 2),
                "slippage": 0, "commission": 0, "swap": 0,
                "regime": "STRESS", "exit_reason": reason,
            })
            self._trade_log.append({
                "event": "CLOSE", "ticket": pos["ticket"], "symbol": pos["symbol"],
                "direction": direction, "pnl": round(pnl, 2), "reason": reason,
                "time": sim_now.isoformat(),
            })
        except Exception:
            pass
