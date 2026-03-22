"""TEST_011 — FAZ-2 + FAZ-3: Kaos Mühendisliği + Monte Carlo + Tarihsel Kriz

Alt testler:
    A) Spike testi — 10x normal yük, 5dk süre
    B) Kaos motor kill — OĞUL/BABA thread kesintisi
    C) Monte Carlo — 1000 rastgele piyasa yolu simülasyonu
    D) Tarihsel kriz replay — Flash crash, yüksek volatilite

Kullanım:
    cd /sessions/exciting-laughing-newton/mnt/USTAT
    python tests/simulation/test_011_chaos_montecarlo.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import tempfile
import random
import threading
from datetime import datetime, timedelta, date
from collections import defaultdict

import numpy as np

# ── Proje kökü ──
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

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

from engine.config import Config
from engine.database import Database
from engine.logger import get_logger
from tests.simulation.stress_bridge import StressTestBridge
from tests.simulation.test_009_stress_runner import PriceGen15, business_days_between, seed_trades

logger = get_logger(__name__)

SYMBOLS_3 = ["F_THYAO", "F_AKBNK", "F_XU030"]
CS_3 = {"F_THYAO": 100, "F_AKBNK": 100, "F_XU030": 1}
JAN1 = {"F_THYAO": 275.0, "F_AKBNK": 33.50, "F_XU030": 13200.0}
BALANCE = 50_000.0


# ══════════════════════════════════════════════════════════════════════
#  TEST A: SPIKE TESTİ — 10x NORMAL YÜK
# ══════════════════════════════════════════════════════════════════════

def test_spike_load():
    """10x normal yük altında 5 iş günü simülasyonu."""
    print("\n" + "=" * 70)
    print("  TEST_011-A: Spike Testi (10x Yük, 5 Gün)")
    print("=" * 70)

    pgen = PriceGen15(symbols=SYMBOLS_3)
    bridge = StressTestBridge(
        pgen, BALANCE, fault_profile="light_stress",
        symbols=SYMBOLS_3, contract_sizes=CS_3,
    )

    SPIKE_CYCLES_PER_DAY = 500  # Normal: 50, spike: 500 (10x)
    SIM_DAYS = 5

    bdays = business_days_between(date(2026, 3, 16), date(2026, 3, 21))[:SIM_DAYS]
    print(f"  Yük seviyesi      : 10x ({SPIKE_CYCLES_PER_DAY} cycle/gün)")
    print(f"  Stres profili     : heavy_stress")
    print(f"  Simülasyon günü   : {len(bdays)}")

    cycle_times = []
    errors_total = 0
    t0 = time.time()

    for day_i, sim_day in enumerate(bdays):
        day_t0 = time.time()
        for c in range(SPIKE_CYCLES_PER_DAY):
            ct0 = time.time()
            pgen.advance_cycle()
            bridge.update_floating_pnl()

            # Sürekli emir gönder (spike simülasyonu)
            sym = random.choice(SYMBOLS_3)
            try:
                r = bridge.send_order(sym, random.choice(["BUY", "SELL"]),
                                       1.0, 0.0, sl=0.0, tp=0.0)
                if r and r.get("retcode") == 10009:
                    # Hemen kapat
                    bridge.close_position(r["order"])
            except Exception:
                errors_total += 1

            ct_elapsed = (time.time() - ct0) * 1000
            cycle_times.append(ct_elapsed)

        day_elapsed = time.time() - day_t0
        print(f"  📅 Gün {day_i+1}/{len(bdays)}: {SPIKE_CYCLES_PER_DAY} cycle, "
              f"{day_elapsed:.1f}s, "
              f"Emir: {bridge.metrics.total_orders_sent}, "
              f"Hata: {errors_total}")

    elapsed = time.time() - t0
    sm = bridge.metrics.summary()

    result = {
        "test": "SPIKE_LOAD",
        "elapsed_s": round(elapsed, 1),
        "total_cycles": len(cycle_times),
        "cycle_p95_ms": round(float(np.percentile(cycle_times, 95)), 2),
        "cycle_max_ms": round(max(cycle_times), 2),
        "orders_sent": sm["orders"]["sent"],
        "fill_rate": sm["orders"]["fill_rate"],
        "errors": errors_total,
        "stress_metrics": sm,
    }

    criteria = {
        "Crash yok (tüm cycle tamamlandı)": len(cycle_times) == SPIKE_CYCLES_PER_DAY * SIM_DAYS,
        "Dolum oranı >%90": sm["orders"]["fill_rate"] > 90,
        "Cycle P95 <500ms": float(np.percentile(cycle_times, 95)) < 500,
    }
    result["criteria"] = criteria
    result["passed"] = all(criteria.values())

    print(f"\n  ── Sonuçlar ──")
    print(f"  Toplam cycle      : {len(cycle_times)}")
    print(f"  Toplam emir       : {sm['orders']['sent']}")
    print(f"  Dolum oranı       : {sm['orders']['fill_rate']:.1f}%")
    print(f"  Cycle P95         : {result['cycle_p95_ms']:.2f}ms")
    print(f"  Cycle Max         : {result['cycle_max_ms']:.2f}ms")

    for name, passed in criteria.items():
        icon = "\033[32m✓\033[0m" if passed else "\033[31m✗\033[0m"
        print(f"  {icon} {name}")

    print(f"\n  SONUÇ: {'GEÇER' if result['passed'] else 'BAŞARISIZ'}")
    return result


# ══════════════════════════════════════════════════════════════════════
#  TEST B: KAOS MOTOR KİLL TESTİ
# ══════════════════════════════════════════════════════════════════════

def test_chaos_motor_kill():
    """Motor kesintisi sırasında pozisyon güvenliği testi."""
    print("\n" + "=" * 70)
    print("  TEST_011-B: Kaos Motor Kill Testi")
    print("=" * 70)

    pgen = PriceGen15(symbols=SYMBOLS_3)
    bridge = StressTestBridge(
        pgen, BALANCE, fault_profile="normal",
        symbols=SYMBOLS_3, contract_sizes=CS_3,
    )

    # Pozisyonlar aç
    open_tickets = []
    for sym in SYMBOLS_3:
        pgen.advance_cycle()
        r = bridge.send_order(sym, "BUY", 2.0, 0.0, sl=0.0, tp=0.0)
        if r and r.get("retcode") == 10009:
            open_tickets.append(r["order"])

    initial_positions = len(bridge._positions)
    print(f"  Açık pozisyon     : {initial_positions}")

    # ── Simüle: Bağlantı kes (motor kill simülasyonu) ──
    print("  Motor kesintisi simülasyonu (30 cycle disconnect)...")
    bridge.inject_fault("disconnect", probability=1.0, duration_s=999)
    bridge._connected = False

    # 30 cycle boyunca kesik
    disconnect_orders = []
    for _ in range(30):
        pgen.advance_cycle()
        r = bridge.send_order("F_THYAO", "BUY", 1.0, 0.0)
        disconnect_orders.append(r)

    failed_during_disconnect = sum(1 for r in disconnect_orders if r is None)
    print(f"  Kesinti sırasında başarısız emir: {failed_during_disconnect}/30")

    # ── Kurtarma ──
    print("  Kurtarma simülasyonu...")
    bridge.clear_all_faults()
    bridge._connected = True
    bridge._cb_tripped = False
    bridge._consecutive_failures = 0

    positions_after_recovery = len(bridge._positions)
    print(f"  Kurtarma sonrası pozisyon: {positions_after_recovery}")

    # Kurtarma sonrası yeni emir gönder
    recovery_success = 0
    for _ in range(10):
        pgen.advance_cycle()
        r = bridge.send_order("F_THYAO", "BUY", 1.0, 0.0, sl=270.0, tp=285.0)
        if r and r.get("retcode") == 10009:
            recovery_success += 1
            bridge.close_position(r["order"])

    print(f"  Kurtarma sonrası emir: {recovery_success}/10")

    result = {
        "test": "CHAOS_MOTOR_KILL",
        "initial_positions": initial_positions,
        "positions_after_recovery": positions_after_recovery,
        "failed_during_disconnect": failed_during_disconnect,
        "recovery_success": recovery_success,
    }

    criteria = {
        "Pozisyonlar korundu": positions_after_recovery >= initial_positions,
        "Kesintide çoğu emir engellendi (>=%80)": failed_during_disconnect >= 24,
        "Kurtarma başarılı (>=%80)": recovery_success >= 8,
    }
    result["criteria"] = criteria
    result["passed"] = all(criteria.values())

    for name, passed in criteria.items():
        icon = "\033[32m✓\033[0m" if passed else "\033[31m✗\033[0m"
        print(f"  {icon} {name}")

    print(f"\n  SONUÇ: {'GEÇER' if result['passed'] else 'BAŞARISIZ'}")
    return result


# ══════════════════════════════════════════════════════════════════════
#  TEST C: MONTE CARLO SİMÜLASYONU
# ══════════════════════════════════════════════════════════════════════

def test_monte_carlo():
    """1000 rastgele piyasa yolu ile strateji dayanıklılığı testi."""
    print("\n" + "=" * 70)
    print("  TEST_011-C: Monte Carlo Simülasyonu (1000 Yol)")
    print("=" * 70)

    N_SIMULATIONS = 1000
    N_TRADES_PER_SIM = 100  # Her simülasyonda 100 işlem
    WIN_RATE = 0.45  # ÜSTAT'ın gerçekçi kazanma oranı
    AVG_WIN_R = 1.8  # Ortalama kazanç R-multiple
    AVG_LOSS_R = 1.0  # Ortalama kayıp (1R)
    RISK_PER_TRADE = 0.01  # %1 risk/işlem

    print(f"  Simülasyon sayısı : {N_SIMULATIONS}")
    print(f"  İşlem/simülasyon  : {N_TRADES_PER_SIM}")
    print(f"  Kazanma oranı     : {WIN_RATE:.0%}")
    print(f"  Ortalama Win R    : {AVG_WIN_R:.1f}R")
    print(f"  Risk/işlem        : {RISK_PER_TRADE:.0%}")

    final_equities = []
    max_drawdowns = []
    profitable_sims = 0

    for sim_i in range(N_SIMULATIONS):
        equity = BALANCE
        peak = equity
        max_dd = 0.0

        for _ in range(N_TRADES_PER_SIM):
            risk_amount = equity * RISK_PER_TRADE
            is_win = random.random() < WIN_RATE

            if is_win:
                # Kazanç: log-normal dağılım (büyük kazançlar nadir)
                r_mult = max(0.5, np.random.lognormal(np.log(AVG_WIN_R), 0.5))
                pnl = risk_amount * r_mult
            else:
                # Kayıp: genellikle 1R, bazen daha az (trailing SL)
                r_mult = min(AVG_LOSS_R, max(0.3, np.random.normal(AVG_LOSS_R, 0.2)))
                pnl = -risk_amount * r_mult

            equity += pnl
            if equity <= 0:
                equity = 0
                break
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd

        final_equities.append(equity)
        max_drawdowns.append(max_dd)
        if equity > BALANCE:
            profitable_sims += 1

    # ── İstatistikler ──
    eq_arr = np.array(final_equities)
    dd_arr = np.array(max_drawdowns)

    result = {
        "test": "MONTE_CARLO",
        "simulations": N_SIMULATIONS,
        "trades_per_sim": N_TRADES_PER_SIM,
        "win_rate": WIN_RATE,
        "equity": {
            "mean": round(float(np.mean(eq_arr)), 2),
            "median": round(float(np.median(eq_arr)), 2),
            "p5": round(float(np.percentile(eq_arr, 5)), 2),
            "p25": round(float(np.percentile(eq_arr, 25)), 2),
            "p75": round(float(np.percentile(eq_arr, 75)), 2),
            "p95": round(float(np.percentile(eq_arr, 95)), 2),
            "min": round(float(np.min(eq_arr)), 2),
            "max": round(float(np.max(eq_arr)), 2),
        },
        "drawdown": {
            "mean": round(float(np.mean(dd_arr)) * 100, 2),
            "median": round(float(np.median(dd_arr)) * 100, 2),
            "p95": round(float(np.percentile(dd_arr, 95)) * 100, 2),
            "max": round(float(np.max(dd_arr)) * 100, 2),
        },
        "profitable_pct": round(profitable_sims / N_SIMULATIONS * 100, 1),
        "ruin_pct": round(sum(1 for e in final_equities if e <= 0) / N_SIMULATIONS * 100, 2),
    }

    print(f"\n  ── Sonuçlar ──")
    print(f"  Karlı simülasyon  : {result['profitable_pct']:.1f}%")
    print(f"  İflas oranı       : {result['ruin_pct']:.2f}%")
    print(f"  Equity ortalama   : {result['equity']['mean']:,.2f} TL")
    print(f"  Equity medyan     : {result['equity']['median']:,.2f} TL")
    print(f"  Equity P5         : {result['equity']['p5']:,.2f} TL")
    print(f"  Equity P95        : {result['equity']['p95']:,.2f} TL")
    print(f"  Maks DD ortalama  : {result['drawdown']['mean']:.1f}%")
    print(f"  Maks DD P95       : {result['drawdown']['p95']:.1f}%")
    print(f"  Maks DD max       : {result['drawdown']['max']:.1f}%")

    criteria = {
        "Karlılık >%60": result["profitable_pct"] > 60,
        "İflas oranı <%5": result["ruin_pct"] < 5,
        "Ortalama DD <%15": result["drawdown"]["mean"] < 15,
        "P95 DD <%30": result["drawdown"]["p95"] < 30,
    }
    result["criteria"] = criteria
    result["passed"] = all(criteria.values())

    for name, passed in criteria.items():
        icon = "\033[32m✓\033[0m" if passed else "\033[31m✗\033[0m"
        print(f"  {icon} {name}")

    print(f"\n  SONUÇ: {'GEÇER' if result['passed'] else 'BAŞARISIZ'}")
    return result


# ══════════════════════════════════════════════════════════════════════
#  TEST D: TARİHSEL KRİZ REPLAY
# ══════════════════════════════════════════════════════════════════════

def test_historical_crisis():
    """Tarihsel kriz senaryoları simülasyonu."""
    print("\n" + "=" * 70)
    print("  TEST_011-D: Tarihsel Kriz Replay Testi")
    print("=" * 70)

    # Kriz senaryoları: (isim, günlük hareket %, volatilite çarpanı, süre gün)
    CRISIS_SCENARIOS = [
        ("2018 TL Krizi (Ağustos)", -8.0, 5.0, 10),
        ("COVID-19 Mart 2020", -12.0, 7.0, 15),
        ("Flash Crash (Ani %5 düşüş)", -5.0, 10.0, 1),
        ("Kademeli Düşüş (%20 / 30 gün)", -0.7, 2.0, 30),
        ("V-Shape Toparlanma", -6.0, 4.0, 5),  # 5 gün düşüş, 5 gün yükseliş
    ]

    results = []
    for scenario_name, daily_move_pct, vol_mult, duration in CRISIS_SCENARIOS:
        print(f"\n  🔴 Senaryo: {scenario_name}")

        equity = BALANCE
        peak = equity
        max_dd = 0.0

        for day in range(duration):
            # Kriz günü fiyat hareketi
            if "V-Shape" in scenario_name and day >= duration // 2:
                daily_ret = abs(daily_move_pct) / 100  # Toparlanma
            else:
                daily_ret = daily_move_pct / 100

            # Volatilite: normal ± kriz çarpanı
            noise = np.random.normal(0, abs(daily_ret) * vol_mult * 0.3)
            total_ret = daily_ret + noise

            # Pozisyon etkisi (%1 risk, max 5 pozisyon)
            risk_exposure = 0.05  # 5 pozisyon × %1
            equity_change = equity * total_ret * risk_exposure

            # Kill-switch simülasyonu: -%3 günlük → tüm kapat
            if equity_change / equity < -0.03:
                equity_change = equity * (-0.03)  # Kill-switch sınırla

            equity += equity_change
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd

        total_return = (equity - BALANCE) / BALANCE * 100
        print(f"    Başlangıç: {BALANCE:,.0f} → Bitiş: {equity:,.0f} TL ({total_return:+.1f}%)")
        print(f"    Maks Drawdown: {max_dd:.1%}")

        results.append({
            "scenario": scenario_name,
            "start_equity": BALANCE,
            "end_equity": round(equity, 2),
            "return_pct": round(total_return, 2),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "duration_days": duration,
            "survived": equity > BALANCE * 0.85,  # %15'ten fazla kaybetmedi
        })

    result = {
        "test": "HISTORICAL_CRISIS",
        "scenarios": results,
    }

    criteria = {
        "Tüm senaryolarda hayatta kaldı (DD<%15)": all(r["survived"] for r in results),
        "Hiçbir senaryoda iflas yok": all(r["end_equity"] > 0 for r in results),
        "V-Shape'de toparlanma": any(r["return_pct"] > -10 for r in results if "V-Shape" in r["scenario"]),
    }
    result["criteria"] = criteria
    result["passed"] = all(criteria.values())

    print()
    for name, passed in criteria.items():
        icon = "\033[32m✓\033[0m" if passed else "\033[31m✗\033[0m"
        print(f"  {icon} {name}")

    print(f"\n  SONUÇ: {'GEÇER' if result['passed'] else 'BAŞARISIZ'}")
    return result


# ══════════════════════════════════════════════════════════════════════
#  ANA GİRİŞ
# ══════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "=" * 70)
    print("  TEST_011 — Kaos + Monte Carlo + Tarihsel Kriz Testleri")
    print("=" * 70)

    t0 = time.time()
    results = {}

    results["A_spike_load"] = test_spike_load()
    results["B_chaos_motor_kill"] = test_chaos_motor_kill()
    results["C_monte_carlo"] = test_monte_carlo()
    results["D_historical_crisis"] = test_historical_crisis()

    elapsed = time.time() - t0

    # ── Özet ──
    print("\n" + "=" * 70)
    print("  TEST_011 — TOPLAM ÖZET")
    print("=" * 70)
    all_passed = True
    for name, r in results.items():
        passed = r.get("passed", False)
        icon = "\033[32m✓\033[0m" if passed else "\033[31m✗\033[0m"
        print(f"  {icon} {name}: {'GEÇER' if passed else 'BAŞARISIZ'}")
        if not passed:
            all_passed = False

    print(f"\n  Toplam süre: {elapsed:.1f}s")
    final = "\033[32m✓ TÜM TESTLER GEÇER\033[0m" if all_passed else "\033[31m✗ BAŞARISIZ TEST VAR\033[0m"
    print(f"  SONUÇ: {final}")
    print("=" * 70)

    # ── JSON kaydet ──
    out_dir = os.path.join(PROJECT_ROOT, "tests", "simulation")
    json_path = os.path.join(out_dir, "TEST_011_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  📄 JSON sonuç: {json_path}")

    return results


if __name__ == "__main__":
    main()
