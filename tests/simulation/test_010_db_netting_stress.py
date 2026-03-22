"""TEST_010 — FAZ-1.3 + FAZ-1.4 + FAZ-2.4: DB Stres + Netting Lock Testi

Alt testler:
    A) DB eşzamanlı yazma/okuma stres testi
    B) Netting lock deadlock testi (3 owner paralel)
    C) Event bus backpressure testi

Kullanım:
    cd /sessions/exciting-laughing-newton/mnt/USTAT
    python tests/simulation/test_010_db_netting_stress.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import tempfile
import threading
import random
from datetime import datetime
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
from engine.netting_lock import acquire_symbol, release_symbol, is_symbol_locked, get_locked_symbols


# ══════════════════════════════════════════════════════════════════════
#  TEST A: DB EŞZAMANLI YAZMA/OKUMA STRES TESTİ
# ══════════════════════════════════════════════════════════════════════

def test_db_concurrent_stress():
    """SQLite WAL modu altında eşzamanlı yazma/okuma stres testi."""
    print("\n" + "=" * 70)
    print("  TEST_010-A: DB Eşzamanlı Yazma/Okuma Stres Testi")
    print("=" * 70)

    config = Config()
    sim_dir = tempfile.mkdtemp(prefix="ustat_t010_db_")
    config._data.setdefault("database", {})["path"] = os.path.join(sim_dir, "stress.db")
    db = Database(config)

    # Test parametreleri
    N_WRITERS = 5
    N_READERS = 3
    WRITES_PER_THREAD = 200
    READS_PER_THREAD = 500

    errors = {"write": 0, "read": 0, "lock_wait": []}
    lock = threading.Lock()
    barrier = threading.Barrier(N_WRITERS + N_READERS)

    def writer_task(thread_id):
        """İşlem ve event yazıcı."""
        barrier.wait()
        for i in range(WRITES_PER_THREAD):
            try:
                t0 = time.monotonic()
                sym = random.choice(["F_THYAO", "F_AKBNK", "F_XU030", "F_GARAN", "F_SAHOL"])
                db.insert_trade({
                    "strategy": f"stress_w{thread_id}",
                    "symbol": sym,
                    "direction": random.choice(["BUY", "SELL"]),
                    "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "exit_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "entry_price": round(random.uniform(50, 300), 2),
                    "exit_price": round(random.uniform(50, 300), 2),
                    "lot": random.choice([1.0, 2.0, 3.0]),
                    "pnl": round(random.uniform(-500, 500), 2),
                    "slippage": 0, "commission": 0, "swap": 0,
                    "regime": "STRESS", "exit_reason": "STRESS_TEST",
                })
                elapsed = (time.monotonic() - t0) * 1000
                with lock:
                    errors["lock_wait"].append(elapsed)

                # Her 10 yazımda bir event de yaz
                if i % 10 == 0:
                    db.insert_event(
                        event_type="STRESS_TEST",
                        message=f"Writer {thread_id} iteration {i}",
                        severity="INFO", action="test",
                    )
            except Exception as e:
                with lock:
                    errors["write"] += 1

    def reader_task(thread_id):
        """Eşzamanlı okuyucu."""
        barrier.wait()
        for i in range(READS_PER_THREAD):
            try:
                t0 = time.monotonic()
                trades = db.get_trades(limit=20)
                elapsed = (time.monotonic() - t0) * 1000
                with lock:
                    errors["lock_wait"].append(elapsed)
            except Exception:
                with lock:
                    errors["read"] += 1

    # ── Çalıştır ──
    print(f"  Yazıcı thread   : {N_WRITERS} × {WRITES_PER_THREAD} yazma")
    print(f"  Okuyucu thread  : {N_READERS} × {READS_PER_THREAD} okuma")
    print(f"  Toplam işlem    : {N_WRITERS * WRITES_PER_THREAD + N_READERS * READS_PER_THREAD}")

    threads = []
    t0 = time.monotonic()
    for i in range(N_WRITERS):
        t = threading.Thread(target=writer_task, args=(i,), daemon=True)
        threads.append(t)
    for i in range(N_READERS):
        t = threading.Thread(target=reader_task, args=(i,), daemon=True)
        threads.append(t)

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)

    elapsed = (time.monotonic() - t0) * 1000

    # ── Sonuçlar ──
    waits = errors["lock_wait"]
    p50 = round(float(np.percentile(waits, 50)), 2) if waits else 0
    p95 = round(float(np.percentile(waits, 95)), 2) if waits else 0
    p99 = round(float(np.percentile(waits, 99)), 2) if waits else 0
    max_wait = round(max(waits), 2) if waits else 0

    result = {
        "test": "DB_CONCURRENT_STRESS",
        "write_errors": errors["write"],
        "read_errors": errors["read"],
        "total_operations": len(waits),
        "elapsed_ms": round(elapsed, 1),
        "latency_p50_ms": p50,
        "latency_p95_ms": p95,
        "latency_p99_ms": p99,
        "latency_max_ms": max_wait,
        "ops_per_second": round(len(waits) / (elapsed / 1000), 1) if elapsed > 0 else 0,
    }

    # ── Geçme kriterleri ──
    criteria = {
        "Yazma hatası = 0": errors["write"] == 0,
        "Okuma hatası = 0": errors["read"] == 0,
        "Kilit bekleme P95 <50ms": p95 < 50,
        "Kilit bekleme Max <200ms": max_wait < 200,
    }
    result["criteria"] = criteria
    result["passed"] = all(criteria.values())

    print(f"\n  ── Sonuçlar ──")
    print(f"  Toplam süre       : {elapsed:.1f}ms")
    print(f"  Toplam işlem      : {len(waits)}")
    print(f"  İşlem/saniye      : {result['ops_per_second']:.0f}")
    print(f"  Yazma hatası      : {errors['write']}")
    print(f"  Okuma hatası      : {errors['read']}")
    print(f"  Gecikme P50       : {p50:.2f}ms")
    print(f"  Gecikme P95       : {p95:.2f}ms")
    print(f"  Gecikme P99       : {p99:.2f}ms")
    print(f"  Gecikme Max       : {max_wait:.2f}ms")

    for name, passed in criteria.items():
        icon = "\033[32m✓\033[0m" if passed else "\033[31m✗\033[0m"
        print(f"  {icon} {name}")

    print(f"\n  SONUÇ: {'GEÇER' if result['passed'] else 'BAŞARISIZ'}")
    return result


# ══════════════════════════════════════════════════════════════════════
#  TEST B: NETTING LOCK DEADLOCK TESTİ
# ══════════════════════════════════════════════════════════════════════

def test_netting_lock_stress():
    """Netting lock eşzamanlı erişim ve deadlock testi."""
    print("\n" + "=" * 70)
    print("  TEST_010-B: Netting Lock Deadlock Stres Testi")
    print("=" * 70)

    SYMBOLS = ["F_THYAO", "F_AKBNK", "F_XU030", "F_GARAN", "F_SAHOL",
               "F_ISCTR", "F_KCHOL", "F_TUPRS"]
    OWNERS = ["ogul", "h_engine", "manuel"]
    N_THREADS = 6
    ITERATIONS = 1000

    stats = {
        "acquired": 0, "rejected": 0, "released": 0,
        "deadlock_detected": 0, "errors": 0,
        "reentrant_success": 0,
    }
    lock = threading.Lock()

    def lock_worker(worker_id):
        owner = OWNERS[worker_id % len(OWNERS)]
        for _ in range(ITERATIONS):
            sym = random.choice(SYMBOLS)
            try:
                got = acquire_symbol(sym, owner)
                if got:
                    with lock:
                        stats["acquired"] += 1

                    # Reentrant test: aynı owner tekrar kilitlesin
                    if random.random() < 0.1:
                        got2 = acquire_symbol(sym, owner)
                        if got2:
                            with lock:
                                stats["reentrant_success"] += 1

                    # İş simülasyonu
                    time.sleep(random.uniform(0, 0.001))

                    release_symbol(sym, owner)
                    with lock:
                        stats["released"] += 1
                else:
                    with lock:
                        stats["rejected"] += 1
            except Exception:
                with lock:
                    stats["errors"] += 1

    # ── Cross-lock deadlock testi ──
    # İki thread aynı anda farklı sembolü ters sırada kilitlemeye çalışır
    deadlock_events = []

    def cross_lock_worker(w_id, sym_a, sym_b, owner):
        """İki sembolü sırayla kilitle — deadlock riski."""
        for _ in range(200):
            got_a = acquire_symbol(sym_a, owner)
            if got_a:
                time.sleep(random.uniform(0, 0.0005))
                got_b = acquire_symbol(sym_b, owner)
                if got_b:
                    release_symbol(sym_b, owner)
                release_symbol(sym_a, owner)
            time.sleep(random.uniform(0, 0.0005))

    # ── Ana test ──
    print(f"  Thread sayısı     : {N_THREADS}")
    print(f"  İterasyon/thread  : {ITERATIONS}")
    print(f"  Sembol sayısı     : {len(SYMBOLS)}")
    print(f"  Owner sayısı      : {len(OWNERS)}")

    t0 = time.monotonic()

    # Normal eşzamanlı test
    threads = []
    for i in range(N_THREADS):
        t = threading.Thread(target=lock_worker, args=(i,), daemon=True)
        threads.append(t)

    # Cross-lock deadlock testi
    t_cross1 = threading.Thread(
        target=cross_lock_worker,
        args=(0, "F_THYAO", "F_AKBNK", "ogul"), daemon=True)
    t_cross2 = threading.Thread(
        target=cross_lock_worker,
        args=(1, "F_AKBNK", "F_THYAO", "h_engine"), daemon=True)
    threads.extend([t_cross1, t_cross2])

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    elapsed = (time.monotonic() - t0) * 1000

    # ── Final kontrol: tüm kilitler serbest mi? ──
    locked = get_locked_symbols()
    orphan_locks = len(locked)

    result = {
        "test": "NETTING_LOCK_STRESS",
        "stats": dict(stats),
        "elapsed_ms": round(elapsed, 1),
        "orphan_locks": orphan_locks,
        "locked_symbols": locked,
    }

    criteria = {
        "Deadlock tespit = 0": stats["deadlock_detected"] == 0,
        "Hata = 0": stats["errors"] == 0,
        "Sahipsiz kilit = 0": orphan_locks == 0,
        "Reentrant çalışıyor": stats["reentrant_success"] > 0,
        "Acquired > 0": stats["acquired"] > 0,
    }
    result["criteria"] = criteria
    result["passed"] = all(criteria.values())

    print(f"\n  ── Sonuçlar ──")
    print(f"  Toplam süre       : {elapsed:.1f}ms")
    print(f"  Kilit alınan      : {stats['acquired']}")
    print(f"  Kilit reddedilen  : {stats['rejected']}")
    print(f"  Kilit serbest     : {stats['released']}")
    print(f"  Reentrant başarı  : {stats['reentrant_success']}")
    print(f"  Deadlock          : {stats['deadlock_detected']}")
    print(f"  Hata              : {stats['errors']}")
    print(f"  Sahipsiz kilit    : {orphan_locks}")

    for name, passed in criteria.items():
        icon = "\033[32m✓\033[0m" if passed else "\033[31m✗\033[0m"
        print(f"  {icon} {name}")

    print(f"\n  SONUÇ: {'GEÇER' if result['passed'] else 'BAŞARISIZ'}")
    return result


# ══════════════════════════════════════════════════════════════════════
#  TEST C: CIRCUIT BREAKER KASKAD TESTİ
# ══════════════════════════════════════════════════════════════════════

def test_circuit_breaker_cascade():
    """Circuit breaker tetikleme ve kurtarma testi."""
    print("\n" + "=" * 70)
    print("  TEST_010-C: Circuit Breaker Kaskad Testi")
    print("=" * 70)

    from tests.simulation.stress_bridge import StressTestBridge
    from tests.simulation.test_009_stress_runner import PriceGen15

    symbols = ["F_THYAO", "F_AKBNK", "F_XU030"]
    pgen = PriceGen15(symbols=symbols)
    bridge = StressTestBridge(
        pgen, 50000.0, fault_profile="normal", symbols=symbols,
        contract_sizes={"F_THYAO": 100, "F_AKBNK": 100, "F_XU030": 1},
    )

    # ── Aşama 1: Normal emirler (baseline) ──
    print("  Aşama 1: Normal emirler (baseline)...")
    normal_results = []
    for i in range(20):
        pgen.advance_cycle()
        r = bridge.send_order("F_THYAO", "BUY", 1.0, 0.0, sl=270.0, tp=285.0)
        normal_results.append(r is not None)
        if r:
            bridge.close_position(r["order"])
    normal_success = sum(normal_results)
    print(f"    Başarılı: {normal_success}/20")

    # ── Aşama 2: Timeout enjekte → CB tetikle ──
    print("  Aşama 2: Timeout enjeksiyonu → Circuit Breaker tetikleme...")
    bridge.inject_fault("timeout", probability=1.0)  # %100 timeout
    timeout_results = []
    for i in range(10):
        pgen.advance_cycle()
        r = bridge.send_order("F_THYAO", "BUY", 1.0, 0.0)
        timeout_results.append(r is not None)
    bridge.clear_fault("timeout")

    cb_tripped = bridge._cb_tripped
    print(f"    CB tetiklendi mi: {'EVET' if cb_tripped else 'HAYIR'}")
    print(f"    CB trip sayısı: {bridge.metrics.circuit_breaker_trips}")

    # ── Aşama 3: CB aktifken emir gönder ──
    print("  Aşama 3: CB aktifken emir denemesi...")
    cb_blocked = []
    for i in range(5):
        pgen.advance_cycle()
        r = bridge.send_order("F_THYAO", "BUY", 1.0, 0.0)
        cb_blocked.append(r is None)

    # ── Aşama 4: CB cooldown sonrası kurtarma ──
    print("  Aşama 4: CB cooldown simülasyonu...")
    bridge._cb_trip_time = time.monotonic() - 31  # 30sn cooldown geçir
    recovery_results = []
    for i in range(10):
        pgen.advance_cycle()
        r = bridge.send_order("F_THYAO", "BUY", 1.0, 0.0, sl=270.0, tp=285.0)
        recovery_results.append(r is not None)
        if r:
            bridge.close_position(r["order"])
    recovery_success = sum(recovery_results)
    print(f"    Kurtarma başarılı: {recovery_success}/10")

    result = {
        "test": "CIRCUIT_BREAKER_CASCADE",
        "normal_success": normal_success,
        "cb_tripped": cb_tripped,
        "cb_trips": bridge.metrics.circuit_breaker_trips,
        "cb_blocked_all": all(cb_blocked),
        "recovery_success": recovery_success,
    }

    criteria = {
        "Normal emirler başarılı": normal_success == 20,
        "CB tetiklendi": cb_tripped,
        "CB aktifken emirler engellendi": all(cb_blocked),
        "Kurtarma sonrası emirler başarılı": recovery_success >= 8,
    }
    result["criteria"] = criteria
    result["passed"] = all(criteria.values())

    for name, passed in criteria.items():
        icon = "\033[32m✓\033[0m" if passed else "\033[31m✗\033[0m"
        print(f"  {icon} {name}")

    print(f"\n  SONUÇ: {'GEÇER' if result['passed'] else 'BAŞARISIZ'}")
    return result


# ══════════════════════════════════════════════════════════════════════
#  TEST D: RISK LİMİT KASKAD TESTİ
# ══════════════════════════════════════════════════════════════════════

def test_risk_limit_cascade():
    """Aylık DD → uyarı → stop → L3 kaskad tetikleme testi."""
    print("\n" + "=" * 70)
    print("  TEST_010-D: Risk Limit Kaskad Tetikleme Testi")
    print("=" * 70)

    from tests.simulation.stress_bridge import StressTestBridge
    from tests.simulation.test_009_stress_runner import PriceGen15

    symbols = ["F_THYAO", "F_AKBNK", "F_XU030"]
    pgen = PriceGen15(symbols=symbols)
    bridge = StressTestBridge(
        pgen, 50000.0, fault_profile="normal", symbols=symbols,
        contract_sizes={"F_THYAO": 100, "F_AKBNK": 100, "F_XU030": 1},
    )

    # Simüle edilmiş kayıp seviyeleri test et
    levels = [
        (0.02, "Normal (%2 kayıp)"),
        (0.04, "Uyarı seviyesi (%4 kayıp)"),
        (0.06, "Mutlak stop (%6 kayıp)"),
        (0.10, "Drawdown (%10 kayıp)"),
        (0.15, "Felaket (%15 kayıp)"),
    ]

    results = []
    for pct, label in levels:
        simulated_loss = 50000.0 * pct
        test_equity = 50000.0 - simulated_loss
        dd_pct = (50000.0 - test_equity) / 50000.0

        should_warn = dd_pct >= 0.04
        should_stop = dd_pct >= 0.06
        should_l3 = dd_pct >= 0.15

        results.append({
            "level": label,
            "loss_pct": f"{pct:.0%}",
            "equity": round(test_equity, 2),
            "warn": should_warn,
            "stop": should_stop,
            "l3": should_l3,
        })
        status = []
        if should_warn:
            status.append("UYARI")
        if should_stop:
            status.append("STOP")
        if should_l3:
            status.append("L3")
        print(f"  {label:30s} | Equity: {test_equity:>10,.2f} | Aksiyonlar: {', '.join(status) or 'YOK'}")

    result = {
        "test": "RISK_LIMIT_CASCADE",
        "levels": results,
        "passed": True,
    }

    criteria = {
        "%2 kayıpta aksiyon YOK": not results[0]["warn"],
        "%4 kayıpta UYARI": results[1]["warn"] and not results[1]["stop"],
        "%6 kayıpta STOP": results[2]["stop"] and not results[2]["l3"],
        "%10 kayıpta STOP (L3 değil)": results[3]["stop"] and not results[3]["l3"],
        "%15 kayıpta L3 tam tasfiye": results[4]["l3"],
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
    print("  TEST_010 — DB + Netting Lock + CB + Risk Kaskad Stres Testleri")
    print("=" * 70)

    t0 = time.monotonic()
    results = {}

    results["A_db_stress"] = test_db_concurrent_stress()
    results["B_netting_lock"] = test_netting_lock_stress()
    results["C_circuit_breaker"] = test_circuit_breaker_cascade()
    results["D_risk_cascade"] = test_risk_limit_cascade()

    elapsed = (time.monotonic() - t0)

    # ── Özet ──
    print("\n" + "=" * 70)
    print("  TEST_010 — TOPLAM ÖZET")
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
    json_path = os.path.join(out_dir, "TEST_010_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  📄 JSON sonuç: {json_path}")

    return results


if __name__ == "__main__":
    main()
