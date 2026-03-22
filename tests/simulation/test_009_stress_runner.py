"""TEST_009 — FAZ-1 Stres Testi: Yük Testi Runner

15 sembol, yüksek döngü hızı, 4 stres profili, kaynak izleme.
StressTestBridge ile hata enjeksiyonu altında tam katman testi.

Testler:
    A) Normal profil — baseline ölçüm (15 sembol, 100 döngü/gün)
    B) Hafif stres — %5 gecikme, %1 timeout, %2 reject
    C) Orta stres — %10 gecikme, %3 timeout, %5 reject, %5 partial, %0.5 disconnect
    D) Ağır stres — %20 gecikme, %8 timeout, %10 reject, %10 partial, %1 disconnect

Kullanım:
    cd /sessions/exciting-laughing-newton/mnt/USTAT
    python tests/simulation/test_009_stress_runner.py
    python tests/simulation/test_009_stress_runner.py --profile heavy_stress
    python tests/simulation/test_009_stress_runner.py --all
"""

from __future__ import annotations

import json
import os
import sys
import time as _time
import tempfile
import random
import argparse
import tracemalloc
from datetime import datetime, timedelta, date
from collections import defaultdict
from typing import Any

import numpy as np

# ── Proje kökünü path'e ekle ──
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

# ── MetaTrader5 mock (Linux) ──
import types as _types
_mock_mt5 = _types.ModuleType("MetaTrader5")
for attr, val in [
    ("TIMEFRAME_M1", 1), ("TIMEFRAME_M5", 5), ("TIMEFRAME_M15", 15),
    ("TIMEFRAME_H1", 16385), ("TRADE_ACTION_DEAL", 1),
    ("ORDER_TYPE_BUY", 0), ("ORDER_TYPE_SELL", 1),
    ("ORDER_FILLING_IOC", 2), ("TRADE_RETCODE_DONE", 10009),
]:
    setattr(_mock_mt5, attr, val)
for fn in ("initialize", "shutdown", "login", "symbol_info", "symbol_info_tick",
           "copy_rates_from_pos", "order_send", "positions_get", "account_info",
           "terminal_info", "symbols_get"):
    setattr(_mock_mt5, fn, lambda *a, **kw: None)
sys.modules["MetaTrader5"] = _mock_mt5

# ── Engine imports ──
from engine.config import Config
from engine.database import Database
from engine.logger import get_logger
from tests.simulation.stress_bridge import StressTestBridge, StressMetrics

logger = get_logger(__name__)


# ══════════════════════════════════════════════════════════════════════
#  TEST PARAMETRELERİ
# ══════════════════════════════════════════════════════════════════════

ALL_SYMBOLS = [
    "F_THYAO", "F_AKBNK", "F_XU030", "F_GARAN", "F_SAHOL",
    "F_ISCTR", "F_KCHOL", "F_TUPRS", "F_SISE", "F_ASELS",
    "F_EREGL", "F_BIMAS", "F_KOZAL", "F_PETKM", "F_TCELL",
]

# Gerçekçi VİOP fiyatları (Ocak 2026 tahmini)
JAN1_PRICES = {
    "F_THYAO": 275.0, "F_AKBNK": 33.50, "F_XU030": 13200.0,
    "F_GARAN": 125.0, "F_SAHOL": 72.0, "F_ISCTR": 17.50,
    "F_KCHOL": 210.0, "F_TUPRS": 185.0, "F_SISE": 62.0,
    "F_ASELS": 95.0, "F_EREGL": 48.0, "F_BIMAS": 420.0,
    "F_KOZAL": 78.0, "F_PETKM": 24.50, "F_TCELL": 85.0,
}

CONTRACT_SIZES = {s: (1 if s == "F_XU030" else 100) for s in ALL_SYMBOLS}

SIM_START_DATE = date(2026, 1, 2)
SIM_END_DATE = date(2026, 3, 21)
CYCLES_PER_DAY = 100  # Yük testi: normal (50) yerine 100
INITIAL_BALANCE = 100_000.0  # Daha büyük bakiye (15 sembol)


# ══════════════════════════════════════════════════════════════════════
#  FİYAT ÜRETECİ — 15 sembol
# ══════════════════════════════════════════════════════════════════════

class PriceGen15:
    """15 sembol için persistent fiyat üreteci."""

    TIMEFRAMES = ["M1", "M5", "M15", "H1"]
    TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60}

    def __init__(self, symbols=None):
        self._symbols = symbols or ALL_SYMBOLS
        self._prices = {s: JAN1_PRICES.get(s, 100.0) for s in self._symbols}
        self._cycle_count = 0
        self._trend_dir = {}
        for s in self._symbols:
            self._trend_dir[s] = random.uniform(0.000010, 0.000040)
        self._bar_history: dict[tuple[str, str], list[dict]] = {}
        self._init_history()

    def _init_history(self):
        for s in self._symbols:
            for tf in self.TIMEFRAMES:
                self._bar_history[(s, tf)] = self._gen_bars(s, tf, 600)

    def _gen_bars(self, symbol, tf, count):
        price = self._prices[symbol]
        bars = []
        now = datetime(2026, 1, 2, 10, 30, 0)
        interval = timedelta(minutes=self.TF_MINUTES.get(tf, 5))
        vol = 0.003 * {"M1": 0.4, "M5": 1.0, "M15": 1.7, "H1": 3.5}.get(tf, 1.0)
        drift = self._trend_dir[symbol]
        for i in range(count):
            t = now - interval * (count - i)
            ret = drift + vol * np.random.randn()
            op = price
            cl = price * (1 + ret)
            hi = max(op, cl) * (1 + abs(np.random.randn()) * vol * 0.15)
            lo = min(op, cl) * (1 - abs(np.random.randn()) * vol * 0.15)
            bars.append({
                "time": t, "open": round(op, 2), "high": round(hi, 2),
                "low": round(lo, 2), "close": round(cl, 2),
                "tick_volume": random.randint(80, 400),
                "spread": random.randint(1, 4),
                "real_volume": random.randint(800, 4000),
            })
            price = cl
        self._prices[symbol] = round(price, 2)
        return bars

    def advance_cycle(self):
        self._cycle_count += 1
        regime = self.get_regime()
        vol_map = {"TREND": 0.003, "RANGE": 0.002, "OLAY": 0.006, "VOLATILE": 0.005}
        base_vol = vol_map.get(regime, 0.003)

        for s in self._symbols:
            drift = self._trend_dir[s]
            if regime == "OLAY":
                drift += random.choice([-1, 1]) * 0.002
            elif regime == "RANGE":
                drift *= 0.3
            elif regime == "VOLATILE":
                drift += random.choice([-1, 1]) * 0.001

            for tf in self.TIMEFRAMES:
                tf_mult = {"M1": 0.4, "M5": 1.0, "M15": 1.7, "H1": 3.5}.get(tf, 1.0)
                vol = base_vol * tf_mult
                ret = drift + vol * np.random.randn()
                hist = self._bar_history[(s, tf)]
                last_close = hist[-1]["close"]
                new_close = last_close * (1 + ret)
                op = last_close
                hi = max(op, new_close) * (1 + abs(np.random.randn()) * vol * 0.15)
                lo = min(op, new_close) * (1 - abs(np.random.randn()) * vol * 0.15)
                bar = {
                    "time": hist[-1]["time"] + timedelta(minutes=self.TF_MINUTES[tf]),
                    "open": round(op, 2), "high": round(hi, 2),
                    "low": round(lo, 2), "close": round(new_close, 2),
                    "tick_volume": random.randint(80, 400),
                    "spread": random.randint(1, 4),
                    "real_volume": random.randint(800, 4000),
                }
                hist.append(bar)
                if len(hist) > 800:
                    self._bar_history[(s, tf)] = hist[-700:]
            self._prices[s] = round(self._bar_history[(s, "M5")][-1]["close"], 2)

    def get_regime(self):
        phase = (self._cycle_count // 80) % 5
        return ["TREND", "RANGE", "VOLATILE", "OLAY", "TREND"][phase]

    def generate_bars(self, symbol, tf="M5", count=500):
        import pandas as pd
        key = (symbol, tf)
        hist = self._bar_history.get(key, [])
        if not hist:
            hist = self._gen_bars(symbol, tf, 600)
            self._bar_history[key] = hist
        return pd.DataFrame(hist[-count:])

    def generate_tick(self, symbol):
        price = self._prices.get(symbol, 100.0)
        sp = random.randint(1, 3)
        h = sp * 0.01 / 2
        return {
            "symbol": symbol, "bid": round(price - h, 2),
            "ask": round(price + h, 2), "spread": sp, "time": datetime.now(),
        }


# ══════════════════════════════════════════════════════════════════════
#  YARDIMCI FONKSİYONLAR
# ══════════════════════════════════════════════════════════════════════

def business_days_between(d1: date, d2: date) -> list[date]:
    days = []
    d = d1
    while d <= d2:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def seed_trades(db, symbols, start_date: date):
    strategies = ["trend_follow", "mean_reversion", "breakout"]
    d = start_date
    trades_added = 0
    for _ in range(10):
        d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        for _ in range(random.randint(3, 8)):
            sym = random.choice(symbols)
            direction = random.choice(["BUY", "SELL"])
            price = JAN1_PRICES.get(sym, 100.0)
            lot = random.choice([1.0, 2.0, 3.0])
            is_loss = random.random() < 0.55
            pnl = -random.uniform(30, 500) if is_loss else random.uniform(20, 400)
            entry_h = random.randint(10, 15)
            exit_h = min(entry_h + random.randint(1, 3), 17)
            cs = CONTRACT_SIZES.get(sym, 100)
            ep = price * (1 + random.uniform(-0.02, 0.02))
            xp = ep + (pnl / (lot * cs)) * (1 if direction == "BUY" else -1)
            db.insert_trade({
                "strategy": random.choice(strategies), "symbol": sym,
                "direction": direction,
                "entry_time": f"{d.isoformat()} {entry_h:02d}:{random.randint(0,59):02d}:00",
                "exit_time": f"{d.isoformat()} {exit_h:02d}:{random.randint(0,59):02d}:00",
                "entry_price": round(ep, 2), "exit_price": round(xp, 2),
                "lot": lot, "pnl": round(pnl, 2), "slippage": 0,
                "commission": 0, "swap": 0, "regime": "SIM",
                "exit_reason": "SL_HIT" if is_loss else "TP_HIT",
            })
            trades_added += 1
    return trades_added


def get_memory_mb():
    """Mevcut tracemalloc bellek kullanımı (MB)."""
    current, peak = tracemalloc.get_traced_memory()
    return current / (1024 * 1024), peak / (1024 * 1024)


# ══════════════════════════════════════════════════════════════════════
#  ANA TEST RUNNER
# ══════════════════════════════════════════════════════════════════════

def run_stress_test(profile: str = "normal", symbols=None, cycles_per_day=None,
                    sim_days=None) -> dict:
    """Tek bir stres profili ile tam test çalıştır."""

    test_symbols = symbols or ALL_SYMBOLS
    cpd = cycles_per_day or CYCLES_PER_DAY

    # Bellek izleme başlat
    tracemalloc.start()

    print("\n" + "=" * 80)
    print(f"  TEST_009 — STRES TESTİ: {profile.upper()}")
    print("=" * 80)
    print(f"  Profil          : {profile}")
    print(f"  Sembol sayısı   : {len(test_symbols)}")
    print(f"  Semboller       : {', '.join(test_symbols[:5])}{'...' if len(test_symbols) > 5 else ''}")
    print(f"  Tarih aralığı   : {SIM_START_DATE} → {SIM_END_DATE}")
    bdays = business_days_between(SIM_START_DATE, SIM_END_DATE)
    if sim_days:
        bdays = bdays[:sim_days]
    total_cycles = len(bdays) * cpd
    print(f"  İş günü         : {len(bdays)}")
    print(f"  Cycle/gün       : {cpd}")
    print(f"  Toplam cycle    : {total_cycles}")
    print(f"  Başlangıç bakiye: {INITIAL_BALANCE:,.0f} TL")
    print("=" * 80 + "\n")

    # ── Config + DB ──
    config = Config()
    config._data.setdefault("engine", {})["paper_mode"] = False
    sim_dir = tempfile.mkdtemp(prefix="ustat_t009_")
    config._data.setdefault("database", {})["path"] = os.path.join(sim_dir, "t009.db")
    db = Database(config)

    # ── Price Generator + Stress Bridge ──
    pgen = PriceGen15(symbols=test_symbols)
    bridge = StressTestBridge(
        pgen, INITIAL_BALANCE, db=db,
        fault_profile=profile,
        symbols=test_symbols,
        contract_sizes=CONTRACT_SIZES,
    )

    # ── Sentetik geçmiş ──
    n_seed = seed_trades(db, test_symbols, SIM_START_DATE)
    print(f"  📦 Sentetik geçmiş: {n_seed} işlem DB'ye eklendi\n")

    # ── Datetime monkey-patch ──
    _real_dt = datetime
    _current_sim_date = [SIM_START_DATE]

    class _SimDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return _real_dt(
                _current_sim_date[0].year, _current_sim_date[0].month,
                _current_sim_date[0].day, 11, 0, 0,
            )

    bridge._time_fn = _SimDT.now

    import engine.ogul as _ogul_mod
    import engine.h_engine as _hengine_mod
    import engine.baba as _baba_mod
    import engine.data_pipeline as _dp_mod
    import engine.ustat as _ustat_mod
    import engine.utils.time_utils as _tu_mod
    _ogul_mod.datetime = _SimDT
    _hengine_mod.datetime = _SimDT
    _baba_mod.datetime = _SimDT
    _dp_mod.datetime = _SimDT
    _ustat_mod.datetime = _SimDT
    _tu_mod.is_market_open = lambda *a, **kw: True

    import engine.mt5_bridge as _bridge_mod
    import engine.top5_selection as _top5_mod
    _bridge_mod.WATCHED_SYMBOLS = list(test_symbols)
    _dp_mod.WATCHED_SYMBOLS = list(test_symbols)
    _top5_mod.WATCHED_SYMBOLS = list(test_symbols)

    # ── Engine oluştur ──
    from engine.main import Engine
    engine = Engine(config=config, db=db, mt5=bridge)
    engine.ogul._is_new_m5_candle = lambda: True
    engine.ogul._is_new_m15_candle = lambda: True
    engine.ogul._is_trading_allowed = lambda *a, **kw: True
    engine.ogul._check_end_of_day = lambda: None

    # ── Katman metrikleri ──
    metrics = {
        "baba": {"cycles": 0, "errors": 0, "regimes": defaultdict(int), "risk_blocks": 0},
        "ogul": {"cycles": 0, "errors": 0, "signals": 0, "orders": 0},
        "h_engine": {"cycles": 0, "errors": 0},
        "manuel": {"cycles": 0, "errors": 0},
        "ustat": {"cycles": 0, "errors": 0},
    }

    day_results = []
    memory_samples = []

    # ══════════════════════════════════════════════════════════════════
    #  ANA DÖNGÜ
    # ══════════════════════════════════════════════════════════════════
    cycle_idx = 0
    t_start = _time.time()
    prev_date = None

    for day_i, sim_day in enumerate(bdays):
        _current_sim_date[0] = sim_day

        if prev_date is None or sim_day != prev_date:
            if prev_date is not None:
                print()
            print(f"  📅 {sim_day.isoformat()} (Gün {day_i + 1}/{len(bdays)})", end="", flush=True)
            prev_date = sim_day

        day_open_bal = bridge._balance
        day_signals = 0
        day_errors = 0
        day_cycle_times = []

        for c in range(cpd):
            cycle_idx += 1
            cycle_t0 = _time.time()
            pgen.advance_cycle()
            bridge.update_floating_pnl()

            # ── 1. Pipeline ──
            try:
                engine.pipeline.run_cycle()
            except Exception:
                day_errors += 1

            # ── 2. BABA ──
            regime = None
            try:
                regime = engine.baba.run_cycle(engine.pipeline)
                metrics["baba"]["cycles"] += 1
                rname = getattr(regime, "regime_type", None)
                if rname:
                    metrics["baba"]["regimes"][rname.value] += 1
            except Exception:
                metrics["baba"]["errors"] += 1
                day_errors += 1

            # ── 3. BABA risk ──
            risk_verdict = None
            try:
                risk_verdict = engine.baba.check_risk_limits(engine.risk_params)
                if risk_verdict and not getattr(risk_verdict, "can_trade", True):
                    metrics["baba"]["risk_blocks"] += 1
            except Exception:
                pass

            # ── 4. Top5 + OĞUL ──
            top5 = []
            try:
                top5 = engine.ogul.select_top5(regime)
            except Exception:
                pass

            pre_pos = len(bridge._positions)
            try:
                if risk_verdict and getattr(risk_verdict, "can_trade", False):
                    engine.ogul.process_signals(top5, regime)
                else:
                    engine.ogul.process_signals([], regime)
                metrics["ogul"]["cycles"] += 1
            except Exception:
                metrics["ogul"]["errors"] += 1
                day_errors += 1

            post_pos = len(bridge._positions)
            if post_pos > pre_pos:
                new_count = post_pos - pre_pos
                metrics["ogul"]["signals"] += new_count
                metrics["ogul"]["orders"] += new_count
                day_signals += new_count

            # ── 5. H-Engine ──
            try:
                engine.h_engine.run_cycle()
                metrics["h_engine"]["cycles"] += 1
            except Exception:
                metrics["h_engine"]["errors"] += 1

            # ── 6. Manuel Motor ──
            try:
                engine.manuel_motor.sync_positions()
                metrics["manuel"]["cycles"] += 1
            except Exception:
                metrics["manuel"]["errors"] += 1

            # ── 7. ÜSTAT ──
            try:
                engine.ustat.run_cycle(engine.baba, engine.ogul)
                metrics["ustat"]["cycles"] += 1
            except Exception:
                metrics["ustat"]["errors"] += 1

            cycle_elapsed = (_time.time() - cycle_t0) * 1000
            day_cycle_times.append(cycle_elapsed)
            bridge.metrics.cycle_durations_ms.append(cycle_elapsed)

        # ── Gün sonu metrikleri ──
        day_close_bal = bridge._balance
        day_pnl = day_close_bal - day_open_bal
        floating = sum(p.get("profit", 0) for p in bridge._positions)
        cur_mem, peak_mem = get_memory_mb()
        bridge.metrics.peak_memory_mb = max(bridge.metrics.peak_memory_mb, peak_mem)

        memory_samples.append({"day": day_i + 1, "current_mb": round(cur_mem, 1),
                               "peak_mb": round(peak_mem, 1)})

        day_rec = {
            "date": sim_day.isoformat(), "day_num": day_i + 1,
            "open_bal": round(day_open_bal, 2), "close_bal": round(day_close_bal, 2),
            "pnl": round(day_pnl, 2), "floating": round(floating, 2),
            "positions": len(bridge._positions), "signals": day_signals,
            "errors": day_errors, "regime": pgen.get_regime(),
            "avg_cycle_ms": round(np.mean(day_cycle_times), 2) if day_cycle_times else 0,
            "max_cycle_ms": round(max(day_cycle_times), 2) if day_cycle_times else 0,
            "memory_mb": round(cur_mem, 1),
        }
        day_results.append(day_rec)

        pnl_color = "\033[32m" if day_pnl >= 0 else "\033[31m"
        err_color = "\033[31m" if day_errors > 0 else "\033[90m"
        print(f"  | {pnl_color}{day_pnl:>+8.2f}\033[0m TL "
              f"| Poz:{len(bridge._positions)} "
              f"| Sin:{day_signals} "
              f"| {err_color}Err:{day_errors}\033[0m "
              f"| Mem:{cur_mem:.0f}MB "
              f"| {pgen.get_regime()}", flush=True)

    elapsed = _time.time() - t_start
    tracemalloc.stop()

    # ══════════════════════════════════════════════════════════════════
    #  SONUÇ RAPORU
    # ══════════════════════════════════════════════════════════════════
    stress_summary = bridge.metrics.summary()
    total_errors = sum(m.get("errors", 0) for m in metrics.values())

    print("\n\n" + "=" * 80)
    print(f"  TEST_009 STRES TESTİ SONUÇ RAPORU — {profile.upper()}")
    print("=" * 80)

    print(f"\n  ── Genel ──")
    print(f"  Profil            : {profile}")
    print(f"  Süre              : {elapsed:.1f}s ({elapsed/60:.1f} dk)")
    print(f"  Toplam cycle      : {cycle_idx}")
    print(f"  Sembol sayısı     : {len(test_symbols)}")

    print(f"\n  ── Bakiye ──")
    final_eq = bridge._equity
    total_pnl = final_eq - INITIAL_BALANCE
    color = "\033[32m" if total_pnl >= 0 else "\033[31m"
    print(f"  Başlangıç         : {INITIAL_BALANCE:>12,.2f} TL")
    print(f"  Son bakiye        : {bridge._balance:>12,.2f} TL")
    print(f"  Equity            : {final_eq:>12,.2f} TL")
    print(f"  Toplam K/Z        : {color}{total_pnl:>+12,.2f} TL\033[0m")

    print(f"\n  ── Emir Metrikleri ──")
    print(f"  Gönderilen        : {stress_summary['orders']['sent']}")
    print(f"  Doldurulan        : {stress_summary['orders']['filled']}")
    print(f"  Reddedilen        : {stress_summary['orders']['rejected']}")
    print(f"  Timeout           : {stress_summary['orders']['timed_out']}")
    print(f"  Kısmi dolum       : {stress_summary['orders']['partial']}")
    print(f"  Dolum oranı       : {stress_summary['orders']['fill_rate']:.1f}%")

    print(f"\n  ── Gecikme (ms) ──")
    print(f"  Emir P50          : {stress_summary['order_latency_ms']['p50']:.2f}")
    print(f"  Emir P95          : {stress_summary['order_latency_ms']['p95']:.2f}")
    print(f"  Emir P99          : {stress_summary['order_latency_ms']['p99']:.2f}")

    print(f"\n  ── Döngü Süresi (ms) ──")
    print(f"  P50               : {stress_summary['cycle_duration_ms']['p50']:.2f}")
    print(f"  P95               : {stress_summary['cycle_duration_ms']['p95']:.2f}")
    print(f"  P99               : {stress_summary['cycle_duration_ms']['p99']:.2f}")
    print(f"  Max               : {stress_summary['cycle_duration_ms']['max']:.2f}")

    print(f"\n  ── Bağlantı ──")
    print(f"  Disconnect sayısı : {stress_summary['connection']['disconnects']}")
    print(f"  Reconnect sayısı  : {stress_summary['connection']['reconnects']}")
    print(f"  Max kesinti       : {stress_summary['connection']['max_disconnect_s']:.2f}s")
    print(f"  Toplam kesinti    : {stress_summary['connection']['total_downtime_s']:.2f}s")

    print(f"\n  ── Hata Enjeksiyonu ──")
    for k, v in stress_summary["errors"].items():
        print(f"  {k:20s}: {v}")

    print(f"\n  ── Kurtarma ──")
    print(f"  CB tetikleme      : {stress_summary['recovery']['circuit_breaker_trips']}")
    print(f"  Otomatik kurtarma : {stress_summary['recovery']['auto_recoveries']}")

    print(f"\n  ── Kaynak ──")
    print(f"  Pik bellek        : {stress_summary['resources']['peak_memory_mb']:.1f} MB")
    print(f"  Pik pozisyon      : {stress_summary['resources']['peak_positions']}")

    print(f"\n  ── Motor Hataları ──")
    for layer, m in metrics.items():
        err = m.get("errors", 0)
        cyc = m.get("cycles", 0)
        color = "\033[31m" if err > 0 else "\033[32m"
        print(f"  {layer:12s}: {color}{err}\033[0m hata / {cyc} cycle")

    # ── GEÇME KRİTERLERİ ──
    print(f"\n  ── GEÇME KRİTERLERİ ──")
    pass_criteria = {
        "Dolum oranı >%95": stress_summary["orders"]["fill_rate"] > 95,
        "Döngü P95 <5000ms": stress_summary["cycle_duration_ms"]["p95"] < 5000,
        "Motor hata <cycle %5": total_errors < cycle_idx * 0.05,
        "Bellek sızıntısı <100MB": stress_summary["resources"]["peak_memory_mb"] < 100,
        "Pik pozisyon <50": stress_summary["resources"]["peak_positions"] < 50,
    }

    all_passed = True
    for criterion, passed in pass_criteria.items():
        icon = "\033[32m✓\033[0m" if passed else "\033[31m✗\033[0m"
        print(f"  {icon} {criterion}")
        if not passed:
            all_passed = False

    final_verdict = "\033[32m✓ GEÇER\033[0m" if all_passed else "\033[31m✗ BAŞARISIZ\033[0m"
    print(f"\n  SONUÇ: {final_verdict}")
    print("=" * 80)

    # ── JSON çıktı ──
    output = {
        "test_id": "TEST_009",
        "profile": profile,
        "date": datetime.now().isoformat(),
        "params": {
            "symbols": test_symbols, "symbol_count": len(test_symbols),
            "start": SIM_START_DATE.isoformat(), "end": SIM_END_DATE.isoformat(),
            "cycles_per_day": cpd, "total_cycles": cycle_idx,
            "business_days": len(bdays), "initial_balance": INITIAL_BALANCE,
        },
        "balance": {
            "initial": INITIAL_BALANCE, "final": round(bridge._balance, 2),
            "equity": round(final_eq, 2), "total_pnl": round(total_pnl, 2),
        },
        "stress_metrics": stress_summary,
        "layer_metrics": {k: dict(v) for k, v in metrics.items()},
        "pass_criteria": pass_criteria,
        "all_passed": all_passed,
        "daily": day_results,
        "memory_samples": memory_samples,
        "elapsed_seconds": round(elapsed, 1),
    }

    out_dir = os.path.join(PROJECT_ROOT, "tests", "simulation")
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, f"TEST_009_{profile}_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  📄 JSON sonuç: {json_path}")
    print("=" * 80 + "\n")

    return output


# ══════════════════════════════════════════════════════════════════════
#  KOMUT SATIRI
# ══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="TEST_009 — Stres Testi Runner")
    parser.add_argument("--profile", default="normal",
                        choices=["normal", "light_stress", "medium_stress",
                                 "heavy_stress", "chaos"],
                        help="Stres profili")
    parser.add_argument("--all", action="store_true",
                        help="Tüm profilleri sırayla çalıştır")
    parser.add_argument("--symbols", type=int, default=15,
                        help="Sembol sayısı (3-15)")
    parser.add_argument("--cycles", type=int, default=100,
                        help="Döngü/gün")
    parser.add_argument("--days", type=int, default=None,
                        help="Simüle edilecek iş günü (varsayılan: tümü)")

    args = parser.parse_args()
    symbols = ALL_SYMBOLS[:max(3, min(15, args.symbols))]

    if args.all:
        profiles = ["normal", "light_stress", "medium_stress", "heavy_stress"]
        results = {}
        for p in profiles:
            results[p] = run_stress_test(
                profile=p, symbols=symbols,
                cycles_per_day=args.cycles, sim_days=args.days,
            )

        # ── Karşılaştırma özeti ──
        print("\n" + "=" * 80)
        print("  KARŞILAŞTIRMA ÖZETİ")
        print("=" * 80)
        print(f"  {'Profil':20s} {'Dolum%':>8s} {'P95ms':>8s} {'Hata':>8s} {'Bellek':>8s} {'Sonuç':>8s}")
        print("-" * 80)
        for p, r in results.items():
            sm = r["stress_metrics"]
            verdict = "GEÇER" if r["all_passed"] else "BAŞARISIZ"
            v_color = "\033[32m" if r["all_passed"] else "\033[31m"
            print(f"  {p:20s} {sm['orders']['fill_rate']:>7.1f}% "
                  f"{sm['cycle_duration_ms']['p95']:>7.1f} "
                  f"{sum(m.get('errors',0) for m in r['layer_metrics'].values()):>8d} "
                  f"{sm['resources']['peak_memory_mb']:>6.1f}MB "
                  f"{v_color}{verdict:>8s}\033[0m")
        print("=" * 80 + "\n")
    else:
        run_stress_test(
            profile=args.profile, symbols=symbols,
            cycles_per_day=args.cycles, sim_days=args.days,
        )


if __name__ == "__main__":
    main()
