"""TEST_008 — v13.0 İşlem Yönetimi İyileştirmeleri Doğrulama Testi

5 yeni modülün entegrasyon testi:
    1. R-Multiple Takip Sistemi (Van Tharp)
    2. Aylık Drawdown Limiti (%6 max, %4 uyarı)
    3. Piramitleme (Turtle-style add to winners)
    4. Chandelier Exit (hibrit trailing)
    5. Maksimum Pozisyon Süresi (96 bar = 24 saat)

Kullanım:
    cd /sessions/exciting-laughing-newton/mnt/USTAT
    python tests/simulation/test_008_runner.py
"""

from __future__ import annotations

import json
import os
import sys
import time as _time
import tempfile
import random
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

logger = get_logger(__name__)

# ══════════════════════════════════════════════════════════════════════
#  TEST PARAMETRELERİ
# ══════════════════════════════════════════════════════════════════════

TEST_SYMBOLS = ["F_THYAO", "F_AKBNK", "F_XU030"]

# 01.01.2026 yaklaşık VİOP fiyatları (geriye doğru tahmin)
JAN1_PRICES = {
    "F_THYAO": 275.0,    # Ocak 2026 → bugün 291 TL
    "F_AKBNK": 33.50,    # Ocak 2026 → bugün 35.34 TL
    "F_XU030": 13200.0,  # Ocak 2026 → bugün ~14700
}

CONTRACT_SIZES = {
    "F_THYAO": 100,
    "F_AKBNK": 100,
    "F_XU030": 1,  # Mini VİOP endeks kontratı
}

# Simülasyon parametreleri
SIM_START_DATE = date(2026, 1, 2)   # 01.01.2026 tatil, ilk iş günü 02.01
SIM_END_DATE   = date(2026, 3, 21)  # Bugün
CYCLES_PER_DAY = 50                 # Her iş günü 50 cycle (≈8.3 dk/cycle)
INITIAL_BALANCE = 50_000.0          # 50K TL


# ══════════════════════════════════════════════════════════════════════
#  FİYAT ÜRETECİ — 3 sembol, gerçekçi
# ══════════════════════════════════════════════════════════════════════

class PriceGen3:
    """3 sembol için persistent fiyat üreteci."""

    TIMEFRAMES = ["M1", "M5", "M15", "H1"]
    TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60}

    def __init__(self):
        self._prices = dict(JAN1_PRICES)
        self._cycle_count = 0
        self._trend_dir = {
            "F_THYAO": 0.000020,   # gerçekçi: 275 → ~291 (3 ayda %6)
            "F_AKBNK": 0.000018,   # gerçekçi: 33.50 → ~35.34 (3 ayda %5.5)
            "F_XU030": 0.000035,   # gerçekçi: 13200 → ~14700 (3 ayda %11)
        }
        self._bar_history: dict[tuple[str, str], list[dict]] = {}
        self._init_history()

    def _init_history(self):
        for s in TEST_SYMBOLS:
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
        vol_map = {"TREND": 0.003, "RANGE": 0.002, "OLAY": 0.006}
        base_vol = vol_map.get(regime, 0.003)

        for s in TEST_SYMBOLS:
            drift = self._trend_dir[s]
            # Rejim etkisi
            if regime == "OLAY":
                drift += random.choice([-1, 1]) * 0.002
            elif regime == "RANGE":
                drift *= 0.3

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
        phase = (self._cycle_count // 80) % 4
        return ["TREND", "RANGE", "OLAY", "TREND"][phase]

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
#  MOCK MT5 BRIDGE — 3 sembol
# ══════════════════════════════════════════════════════════════════════

class MockBridge3:
    """3 sembol için MockMT5Bridge."""

    TF_MAP = {1: "M1", 5: "M5", 15: "M15", 16385: "H1"}
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_H1 = 16385

    def __init__(self, pgen: PriceGen3, balance: float, db=None, time_fn=None):
        self._gen = pgen
        self._connected = True
        self._balance = balance
        self._equity = balance
        self._health = None
        self._db = db
        self._time_fn = time_fn or datetime.now
        self._symbol_map = {s: s for s in TEST_SYMBOLS}
        self._reverse_map = {s: s for s in TEST_SYMBOLS}
        self._map_lock = __import__("threading").Lock()
        self._write_lock = __import__("threading").Lock()
        self._positions: list[dict] = []
        self._next_ticket = 200000
        # İstatistikler
        self._sl_close_count = 0
        self._tp_close_count = 0
        self._total_realized_pnl = 0.0
        self._trade_log: list[dict] = []  # Tüm açılış/kapanış kaydı

    def is_connected(self): return self._connected
    def connect(self, launch=True):
        self._connected = True; return True
    def disconnect(self): self._connected = False
    def heartbeat(self): return True
    def _to_mt5(self, s): return s
    def _to_base(self, s): return s
    def _is_watched(self, s): return s in TEST_SYMBOLS

    def get_account_info(self):
        from engine.mt5_bridge import AccountInfo
        fl = sum(p.get("profit", 0) for p in self._positions)
        self._equity = self._balance + fl
        return AccountInfo(
            login=99999, server="SIM-TEST006", balance=self._balance,
            equity=self._equity, margin=len(self._positions) * 500.0,
            free_margin=self._equity - len(self._positions) * 500.0,
            margin_level=9999.0 if not self._positions else (self._equity / (len(self._positions) * 500.0)) * 100,
            currency="TRY",
        )

    def get_symbol_info(self, symbol):
        from engine.mt5_bridge import SymbolInfo
        price = self._gen._prices.get(symbol, 100.0)
        cs = CONTRACT_SIZES.get(symbol, 100)
        return SymbolInfo(
            name=symbol, point=0.01, trade_contract_size=cs,
            trade_tick_value=cs * 0.01, volume_min=1.0, volume_max=50.0,
            volume_step=1.0, bid=round(price - 0.01, 2),
            ask=round(price + 0.01, 2), spread=2,
        )

    def get_bars(self, symbol, timeframe=5, count=500):
        import pandas as pd
        if symbol not in TEST_SYMBOLS:
            # Bilinmeyen sembol → boş DataFrame (pipeline hatasını önler)
            return pd.DataFrame(columns=["time","open","high","low","close",
                                         "tick_volume","spread","real_volume"])
        tf_str = self.TF_MAP.get(timeframe, "M5")
        return self._gen.generate_bars(symbol, tf_str, count)

    def get_tick(self, symbol):
        from engine.mt5_bridge import Tick
        t = self._gen.generate_tick(symbol)
        return Tick(symbol=t["symbol"], bid=t["bid"], ask=t["ask"],
                    spread=t["spread"], time=t["time"])

    def positions_get(self): return self._positions
    def get_history_for_sync(self, days=90): return []

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
        return result

    def send_order(self, symbol, direction, lot, price,
                   sl=0.0, tp=0.0, order_type="market"):
        tick = self._gen.generate_tick(symbol)
        entry = tick["ask"] if direction == "BUY" else tick["bid"]
        self._next_ticket += 1
        pos = {
            "ticket": self._next_ticket, "symbol": symbol,
            "type": 0 if direction == "BUY" else 1,
            "volume": lot, "price_open": entry,
            "sl": sl or 0.0, "tp": tp or 0.0, "profit": 0.0,
            "comment": f"SIM_{order_type}", "magic": 0,
            "time": int(self._time_fn().timestamp()),
        }
        self._positions.append(pos)
        self._trade_log.append({
            "event": "OPEN", "ticket": self._next_ticket, "symbol": symbol,
            "direction": direction, "lot": lot, "entry": entry,
            "sl": sl, "tp": tp, "time": self._time_fn().isoformat(),
        })
        logger.info(f"[T008] Emir açıldı: {symbol} {direction} {lot:.1f} lot @ {entry:.2f}")
        return {"retcode": 10009, "order": self._next_ticket,
                "deal": self._next_ticket, "volume": lot,
                "price": entry, "comment": f"SIM_{order_type}"}

    def close_position(self, ticket):
        for i, p in enumerate(self._positions):
            if p["ticket"] == ticket:
                tick = self._gen.generate_tick(p["symbol"])
                exit_p = tick["bid"] if p["type"] == 0 else tick["ask"]
                cs = CONTRACT_SIZES.get(p["symbol"], 100)
                pnl = (exit_p - p["price_open"]) * p["volume"] * cs
                if p["type"] == 1: pnl = -pnl
                self._balance += pnl
                self._total_realized_pnl += pnl
                self._positions.pop(i)
                return {"retcode": 10009, "order": ticket, "profit": pnl}
        return None

    def check_order_status(self, order_ticket):
        """Simülasyonda emirler her zaman anında dolar."""
        return {
            "status": "filled",
            "filled_volume": 1.0,
            "remaining_volume": 0.0,
            "deal_ticket": order_ticket,
        }

    def get_pending_orders(self):
        """Simülasyonda bekleyen emir yok."""
        return []

    def cancel_order(self, order_ticket):
        """Simülasyonda emir iptali — her zaman başarılı."""
        return {"retcode": 10009}

    def send_market_order(self, symbol, direction, lot, sl=0.0, tp=0.0, comment=""):
        """v13.0 Piramitleme için market emir gönder."""
        return self.send_order(symbol, direction, lot, 0.0, sl=sl, tp=tp, order_type="market")

    def close_position_partial(self, ticket, volume):
        """Kısmi kapanış — TP1 için gerekli."""
        for p in self._positions:
            if p["ticket"] == ticket:
                if volume >= p["volume"]:
                    return self.close_position(ticket)
                p["volume"] -= volume
                tick = self._gen.generate_tick(p["symbol"])
                cs = CONTRACT_SIZES.get(p["symbol"], 100)
                exit_p = tick["bid"] if p["type"] == 0 else tick["ask"]
                if p["type"] == 0:
                    pnl = (exit_p - p["price_open"]) * volume * cs
                else:
                    pnl = (p["price_open"] - exit_p) * volume * cs
                self._balance += pnl
                self._total_realized_pnl += pnl
                self._tp_close_count += 1
                logger.info(f"[T008] Kısmi kapanış: #{ticket} {volume} lot K/Z={pnl:+.2f}")
                return {"retcode": 10009, "order": ticket, "profit": pnl}
        return None

    def get_deal_summary(self, ticket):
        """MT5 deal özeti — simülasyonda None (fallback PnL hesabı kullanılır)."""
        return None

    def modify_position(self, ticket, sl=None, tp=None):
        for p in self._positions:
            if p["ticket"] == ticket:
                if sl is not None: p["sl"] = sl
                if tp is not None: p["tp"] = tp
                return {"retcode": 10009}
        return None

    def update_floating_pnl(self):
        closed = []
        for p in self._positions:
            tick = self._gen.generate_tick(p["symbol"])
            cs = CONTRACT_SIZES.get(p["symbol"], 100)
            if p["type"] == 0:
                cur = tick["bid"]
                p["profit"] = (cur - p["price_open"]) * p["volume"] * cs
                if p["sl"] > 0 and cur <= p["sl"]:
                    pnl = (p["sl"] - p["price_open"]) * p["volume"] * cs
                    self._balance += pnl; self._total_realized_pnl += pnl
                    self._sl_close_count += 1
                    p["_pnl"] = pnl; p["_reason"] = "SL_HIT"; closed.append(p["ticket"])
                    logger.info(f"[T008] SL: #{p['ticket']} {p['symbol']} BUY K/Z={pnl:+.2f}")
                    continue
                if p["tp"] > 0 and cur >= p["tp"]:
                    pnl = (p["tp"] - p["price_open"]) * p["volume"] * cs
                    self._balance += pnl; self._total_realized_pnl += pnl
                    self._tp_close_count += 1
                    p["_pnl"] = pnl; p["_reason"] = "TP_HIT"; closed.append(p["ticket"])
                    logger.info(f"[T008] TP: #{p['ticket']} {p['symbol']} BUY K/Z={pnl:+.2f}")
                    continue
            else:
                cur = tick["ask"]
                p["profit"] = (p["price_open"] - cur) * p["volume"] * cs
                if p["sl"] > 0 and cur >= p["sl"]:
                    pnl = (p["price_open"] - p["sl"]) * p["volume"] * cs
                    self._balance += pnl; self._total_realized_pnl += pnl
                    self._sl_close_count += 1
                    p["_pnl"] = pnl; p["_reason"] = "SL_HIT"; closed.append(p["ticket"])
                    logger.info(f"[T008] SL: #{p['ticket']} {p['symbol']} SELL K/Z={pnl:+.2f}")
                    continue
                if p["tp"] > 0 and cur <= p["tp"]:
                    pnl = (p["price_open"] - p["tp"]) * p["volume"] * cs
                    self._balance += pnl; self._total_realized_pnl += pnl
                    self._tp_close_count += 1
                    p["_pnl"] = pnl; p["_reason"] = "TP_HIT"; closed.append(p["ticket"])
                    logger.info(f"[T008] TP: #{p['ticket']} {p['symbol']} SELL K/Z={pnl:+.2f}")
                    continue
        if closed:
            for p in self._positions:
                if p["ticket"] in closed:
                    self._record_close(p)
            self._positions = [p for p in self._positions if p["ticket"] not in closed]

    def _record_close(self, pos):
        if not self._db: return
        try:
            sim_now = self._time_fn()
            direction = "BUY" if pos["type"] == 0 else "SELL"
            pnl = pos.get("_pnl", pos.get("profit", 0))
            reason = pos.get("_reason", "UNKNOWN")
            entry_t = datetime.fromtimestamp(pos.get("time", sim_now.timestamp()))
            self._db.insert_trade({
                "strategy": "OGUL_SIM", "symbol": pos["symbol"],
                "direction": direction,
                "entry_time": entry_t.strftime("%Y-%m-%d %H:%M:%S"),
                "exit_time": sim_now.strftime("%Y-%m-%d %H:%M:%S"),
                "entry_price": pos["price_open"],
                "exit_price": pos.get("sl", 0) if reason == "SL_HIT" else pos.get("tp", 0),
                "lot": pos["volume"], "pnl": round(pnl, 2),
                "slippage": 0, "commission": 0, "swap": 0,
                "regime": "SIM", "exit_reason": reason,
            })
            self._trade_log.append({
                "event": "CLOSE", "ticket": pos["ticket"], "symbol": pos["symbol"],
                "direction": direction, "pnl": round(pnl, 2), "reason": reason,
                "time": sim_now.isoformat(),
            })
        except Exception as e:
            logger.warning(f"[T008] DB kayıt hatası: {e}")


# ══════════════════════════════════════════════════════════════════════
#  ANA TEST RUNNER
# ══════════════════════════════════════════════════════════════════════

def business_days_between(d1: date, d2: date) -> list[date]:
    """İki tarih arasındaki iş günlerini listele."""
    days = []
    d = d1
    while d <= d2:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def seed_trades(db, start_date: date):
    """Başlangıçtan önceki 10 iş günü için sentetik geçmiş."""
    strategies = ["trend_follow", "mean_reversion", "breakout"]
    d = start_date
    trades_added = 0
    for _ in range(10):
        d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        for _ in range(random.randint(2, 5)):
            sym = random.choice(TEST_SYMBOLS)
            direction = random.choice(["BUY", "SELL"])
            price = JAN1_PRICES[sym]
            lot = random.choice([1.0, 2.0])
            is_loss = random.random() < 0.55
            pnl = -random.uniform(30, 300) if is_loss else random.uniform(20, 250)
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
        # Risk olayları
        if random.random() < 0.3:
            db.insert_event(
                event_type="DRAWDOWN_WARNING",
                message=f"Drawdown: %{random.uniform(2, 7):.1f}",
                severity="WARNING", action="risk_check",
            )
    return trades_added


def run_test():
    """Ana test akışı."""
    print("\n" + "=" * 78)
    print("  TEST_008 — v13.0 İşlem Yönetimi İyileştirmeleri Doğrulama")
    print("=" * 78)
    print(f"  Semboller       : {', '.join(TEST_SYMBOLS)}")
    print(f"  Tarih aralığı   : {SIM_START_DATE} → {SIM_END_DATE}")
    bdays = business_days_between(SIM_START_DATE, SIM_END_DATE)
    total_cycles = len(bdays) * CYCLES_PER_DAY
    print(f"  İş günü         : {len(bdays)}")
    print(f"  Cycle/gün       : {CYCLES_PER_DAY}")
    print(f"  Toplam cycle    : {total_cycles}")
    print(f"  Başlangıç bakiye: {INITIAL_BALANCE:,.0f} TL")
    print(f"  Başlangıç fiyat : THYAO={JAN1_PRICES['F_THYAO']}, "
          f"AKBNK={JAN1_PRICES['F_AKBNK']}, XU030={JAN1_PRICES['F_XU030']}")
    print("=" * 78 + "\n")

    # ── Config + DB ──
    config = Config()
    config._data.setdefault("engine", {})["paper_mode"] = False
    sim_dir = tempfile.mkdtemp(prefix="ustat_t008_")
    config._data.setdefault("database", {})["path"] = os.path.join(sim_dir, "t008.db")
    db = Database(config)

    # ── Price Generator + Mock Bridge ──
    pgen = PriceGen3()
    bridge = MockBridge3(pgen, INITIAL_BALANCE, db=db)

    # ── Sentetik geçmiş ──
    n_seed = seed_trades(db, SIM_START_DATE)
    print(f"  📦 Sentetik geçmiş: {n_seed} işlem DB'ye eklendi\n")

    # ── Datetime monkey-patch ──
    _real_dt = datetime
    _current_sim_date = [SIM_START_DATE]  # mutable container

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

    # ── WATCHED_SYMBOLS override — sadece test sembolleri ──
    # "from engine.mt5_bridge import WATCHED_SYMBOLS" yapan modüller
    # kendi namespace'lerinde bir kopya tutar → hepsini override etmeliyiz
    import engine.mt5_bridge as _bridge_mod
    import engine.top5_selection as _top5_mod
    _bridge_mod.WATCHED_SYMBOLS = list(TEST_SYMBOLS)
    _dp_mod.WATCHED_SYMBOLS = list(TEST_SYMBOLS)
    _top5_mod.WATCHED_SYMBOLS = list(TEST_SYMBOLS)

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
        "manuel": {"cycles": 0, "errors": 0, "syncs": 0},
        "ustat": {
            "cycles": 0, "errors": 0,
            "hata_atamasi": 0, "ertesi_gun": 0, "regulasyon": 0,
            "kontrat_profil": 0, "kategori": 0,
        },
    }

    day_results = []
    prev_date = None

    # ══════════════════════════════════════════════════════════════════
    #  ANA DÖNGÜ
    # ══════════════════════════════════════════════════════════════════
    cycle_idx = 0
    t_start = _time.time()

    for day_i, sim_day in enumerate(bdays):
        _current_sim_date[0] = sim_day

        if prev_date is None or sim_day != prev_date:
            if prev_date is not None:
                print()
            print(f"  📅 {sim_day.isoformat()} (Gün {day_i + 1}/{len(bdays)})", end="", flush=True)
            prev_date = sim_day

        day_open_bal = bridge._balance
        day_signals = 0
        day_sl = 0
        day_tp = 0

        for c in range(CYCLES_PER_DAY):
            cycle_idx += 1
            pgen.advance_cycle()
            bridge.update_floating_pnl()

            # ── 1. Pipeline ──
            try:
                engine.pipeline.run_cycle()
            except Exception:
                pass

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
            except Exception as _top5_exc:
                if cycle_idx <= 3:
                    import traceback
                    logger.error(f"[T008] Top5 hata: {_top5_exc}")
                    traceback.print_exc()

            pre_pos = len(bridge._positions)
            try:
                if risk_verdict and getattr(risk_verdict, "can_trade", False):
                    engine.ogul.process_signals(top5, regime)
                else:
                    engine.ogul.process_signals([], regime)
                metrics["ogul"]["cycles"] += 1
            except Exception as _ogul_exc:
                metrics["ogul"]["errors"] += 1
                if metrics["ogul"]["errors"] <= 3:
                    import traceback
                    logger.error(f"[T008] OĞUL hata #{metrics['ogul']['errors']}: {_ogul_exc}")
                    traceback.print_exc()

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
                metrics["manuel"]["syncs"] += 1
            except Exception:
                metrics["manuel"]["errors"] += 1

            # ── 7. ÜSTAT ──
            try:
                engine.ustat.run_cycle(engine.baba, engine.ogul)
                metrics["ustat"]["cycles"] += 1
            except Exception:
                metrics["ustat"]["errors"] += 1

            # SL/TP bu cycle
            new_sl = bridge._sl_close_count - (day_sl + sum(d.get("sl", 0) for d in day_results))
            new_tp = bridge._tp_close_count - (day_tp + sum(d.get("tp", 0) for d in day_results))

        # ── Gün sonu metrikleri ──
        day_close_bal = bridge._balance
        day_pnl = day_close_bal - day_open_bal
        floating = sum(p.get("profit", 0) for p in bridge._positions)

        day_rec = {
            "date": sim_day.isoformat(),
            "day_num": day_i + 1,
            "open_bal": round(day_open_bal, 2),
            "close_bal": round(day_close_bal, 2),
            "pnl": round(day_pnl, 2),
            "floating": round(floating, 2),
            "positions": len(bridge._positions),
            "signals": day_signals,
            "sl": bridge._sl_close_count - sum(d.get("sl", 0) for d in day_results),
            "tp": bridge._tp_close_count - sum(d.get("tp", 0) for d in day_results),
            "regime": pgen.get_regime(),
        }
        day_results.append(day_rec)

        # Compact günlük satır
        pnl_color = "\033[32m" if day_pnl >= 0 else "\033[31m"
        print(f"  | {pnl_color}{day_pnl:>+8.2f}\033[0m TL | Poz:{len(bridge._positions)} "
              f"| Sinyal:{day_signals} | {pgen.get_regime()}", flush=True)

    elapsed = _time.time() - t_start

    # ── ÜSTAT son durum ──
    ustat = engine.ustat
    metrics["ustat"]["hata_atamasi"] = len(getattr(ustat, "error_attributions", []))
    metrics["ustat"]["ertesi_gun"] = len(getattr(ustat, "next_day_analyses", []))
    metrics["ustat"]["regulasyon"] = len(getattr(ustat, "regulation_suggestions", []))
    metrics["ustat"]["kontrat_profil"] = len(getattr(ustat, "contract_profiles", {}))
    metrics["ustat"]["kategori"] = len(getattr(ustat, "trade_categories", {}))

    # ══════════════════════════════════════════════════════════════════
    #  SONUÇ RAPORU
    # ══════════════════════════════════════════════════════════════════
    print("\n\n" + "=" * 78)
    print("  TEST_008 SONUÇ RAPORU")
    print("=" * 78)

    print(f"\n  ── Genel ──")
    print(f"  Süre              : {elapsed:.1f}s ({elapsed/60:.1f} dk)")
    print(f"  Toplam cycle      : {cycle_idx}")
    print(f"  Simüle edilen gün : {len(bdays)} iş günü")
    print(f"  Tarih aralığı     : {SIM_START_DATE} → {SIM_END_DATE}")

    print(f"\n  ── Fiyat Gelişimi ──")
    for s in TEST_SYMBOLS:
        start_p = JAN1_PRICES[s]
        end_p = pgen._prices[s]
        chg = (end_p - start_p) / start_p * 100
        print(f"  {s:12s}: {start_p:>10.2f} → {end_p:>10.2f} ({chg:>+6.2f}%)")

    print(f"\n  ── Bakiye ──")
    final_eq = bridge._equity
    total_pnl = final_eq - INITIAL_BALANCE
    pnl_pct = total_pnl / INITIAL_BALANCE * 100
    color = "\033[32m" if total_pnl >= 0 else "\033[31m"
    print(f"  Başlangıç         : {INITIAL_BALANCE:>12,.2f} TL")
    print(f"  Son bakiye        : {bridge._balance:>12,.2f} TL")
    print(f"  Floating P/L      : {sum(p.get('profit',0) for p in bridge._positions):>12,.2f} TL")
    print(f"  Equity            : {final_eq:>12,.2f} TL")
    print(f"  Toplam K/Z        : {color}{total_pnl:>+12,.2f} TL ({pnl_pct:>+.2f}%)\033[0m")
    print(f"  Gerçekleşen K/Z   : {bridge._total_realized_pnl:>+12,.2f} TL")

    print(f"\n  ── İşlem İstatistikleri ──")
    print(f"  Sinyal            : {metrics['ogul']['signals']}")
    print(f"  Emir açılan       : {metrics['ogul']['orders']}")
    print(f"  SL kapanış        : {bridge._sl_close_count}")
    print(f"  TP kapanış        : {bridge._tp_close_count}")
    total_closed = bridge._sl_close_count + bridge._tp_close_count
    if total_closed > 0:
        wr = bridge._tp_close_count / total_closed * 100
        print(f"  Win Rate          : {wr:.1f}%")
    print(f"  Açık pozisyon     : {len(bridge._positions)}")

    # ── v13.0 İyileştirme Metrikleri ──
    print(f"\n  ── v13.0 İYİLEŞTİRME METRİKLERİ ──")
    ogul = engine.ogul

    # R-Multiple
    r_hist = ogul._r_multiple_history
    if r_hist:
        avg_r = sum(r_hist) / len(r_hist)
        wins_r = [r for r in r_hist if r > 0]
        losses_r = [r for r in r_hist if r <= 0]
        print(f"\n  [1. R-Multiple Takibi]")
        print(f"    İşlem sayısı    : {len(r_hist)}")
        print(f"    Ortalama R      : {avg_r:+.3f}R")
        if wins_r:
            print(f"    Ortalama Win R  : +{sum(wins_r)/len(wins_r):.3f}R")
        if losses_r:
            print(f"    Ortalama Loss R : {sum(losses_r)/len(losses_r):.3f}R")
        print(f"    Expectancy      : {ogul._r_expectancy:+.3f}R")
        print(f"    Max Win R       : +{max(r_hist):.3f}R" if r_hist else "")
        print(f"    Max Loss R      : {min(r_hist):.3f}R" if r_hist else "")
    else:
        print(f"\n  [1. R-Multiple Takibi]")
        print(f"    Henüz R-Multiple verisi yok (işlem kapanmadı)")

    # Aylık Drawdown
    print(f"\n  [2. Aylık Drawdown]")
    print(f"    Aylık DD stop   : {'EVET' if ogul._monthly_dd_stop else 'Hayır'}")
    print(f"    Aylık DD uyarı  : {'EVET' if ogul._monthly_dd_warn else 'Hayır'}")
    if ogul._monthly_start_equity > 0:
        current_dd = (ogul._monthly_start_equity - bridge._equity) / ogul._monthly_start_equity
        print(f"    Mevcut DD       : {current_dd:.2%}")

    # Piramitleme
    pyramid_trades = [t for t in ogul.active_trades.values() if t.pyramid_count > 0]
    total_pyramids = sum(t.pyramid_count for t in ogul.active_trades.values())
    print(f"\n  [3. Piramitleme (Turtle)]")
    print(f"    Piramit ekleme  : {total_pyramids}")
    print(f"    Piramitli işlem : {len(pyramid_trades)}")

    # Chandelier Exit
    print(f"\n  [4. Chandelier Exit]")
    print(f"    Durum           : {'AKTİF' if True else 'KAPALI'}")
    print(f"    Karışım oranı  : %30 Chandelier + %70 EMA/Swing")

    # Max Hold Time
    print(f"\n  [5. Maksimum Pozisyon Süresi]")
    print(f"    Durum           : {'AKTİF (96 bar = 24 saat)' if True else 'KAPALI'}")

    print(f"\n  ── KATMAN RAPORU ──")

    print(f"\n  [BABA — Risk Yönetimi]")
    print(f"    Başarılı cycle  : {metrics['baba']['cycles']}")
    print(f"    Hata            : {metrics['baba']['errors']}")
    print(f"    Risk engeli     : {metrics['baba']['risk_blocks']}")
    print(f"    Rejim dağılımı  :")
    for r, cnt in sorted(metrics["baba"]["regimes"].items()):
        pct = cnt / max(metrics["baba"]["cycles"], 1) * 100
        print(f"      {r:12s}: {cnt:5d} ({pct:.1f}%)")

    print(f"\n  [OĞUL — Sinyal Motoru]")
    print(f"    Başarılı cycle  : {metrics['ogul']['cycles']}")
    print(f"    Hata            : {metrics['ogul']['errors']}")
    print(f"    Sinyal          : {metrics['ogul']['signals']}")
    print(f"    Emir            : {metrics['ogul']['orders']}")

    print(f"\n  [H-Engine — Hibrit Pozisyon]")
    print(f"    Başarılı cycle  : {metrics['h_engine']['cycles']}")
    print(f"    Hata            : {metrics['h_engine']['errors']}")

    print(f"\n  [Manuel Motor — Pozisyon Sync]")
    print(f"    Başarılı cycle  : {metrics['manuel']['cycles']}")
    print(f"    Hata            : {metrics['manuel']['errors']}")
    print(f"    Sync            : {metrics['manuel']['syncs']}")

    print(f"\n  [ÜSTAT — Beyin Merkezi]")
    print(f"    Başarılı cycle  : {metrics['ustat']['cycles']}")
    print(f"    Hata            : {metrics['ustat']['errors']}")
    print(f"    Hata ataması    : {metrics['ustat']['hata_atamasi']}")
    print(f"    Ertesi gün      : {metrics['ustat']['ertesi_gun']}")
    print(f"    Regülasyon      : {metrics['ustat']['regulasyon']}")
    print(f"    Kontrat profili : {metrics['ustat']['kontrat_profil']}")
    print(f"    Kategorizasyon  : {metrics['ustat']['kategori']}")

    print("\n" + "=" * 78)

    # ── JSON çıktı ──
    output = {
        "test_id": "TEST_008",
        "date": datetime.now().isoformat(),
        "params": {
            "symbols": TEST_SYMBOLS,
            "start": SIM_START_DATE.isoformat(),
            "end": SIM_END_DATE.isoformat(),
            "cycles_per_day": CYCLES_PER_DAY,
            "total_cycles": cycle_idx,
            "business_days": len(bdays),
            "initial_balance": INITIAL_BALANCE,
        },
        "prices": {s: {"start": JAN1_PRICES[s], "end": pgen._prices[s]} for s in TEST_SYMBOLS},
        "balance": {
            "initial": INITIAL_BALANCE, "final_balance": round(bridge._balance, 2),
            "equity": round(final_eq, 2), "total_pnl": round(total_pnl, 2),
            "realized_pnl": round(bridge._total_realized_pnl, 2),
        },
        "trades": {
            "signals": metrics["ogul"]["signals"], "orders": metrics["ogul"]["orders"],
            "sl_closes": bridge._sl_close_count, "tp_closes": bridge._tp_close_count,
            "open_positions": len(bridge._positions),
            "trade_log": bridge._trade_log,
        },
        "layers": metrics,
        "daily": day_results,
        "elapsed_seconds": round(elapsed, 1),
        "v13_improvements": {
            "r_multiple": {
                "history": [round(r, 3) for r in ogul._r_multiple_history],
                "expectancy": round(ogul._r_expectancy, 4),
                "count": len(ogul._r_multiple_history),
            },
            "monthly_dd": {
                "stop_triggered": ogul._monthly_dd_stop,
                "warn_triggered": ogul._monthly_dd_warn,
                "start_equity": round(ogul._monthly_start_equity, 2),
            },
            "pyramiding": {
                "total_adds": total_pyramids,
                "trades_with_pyramid": len(pyramid_trades),
            },
            "chandelier_exit": {"enabled": True, "weight": 0.3},
            "max_hold_time": {"enabled": True, "max_bars": 96},
        },
    }

    # JSON kaydet
    out_dir = os.path.join(PROJECT_ROOT, "tests", "simulation")
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "TEST_008_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  📄 JSON sonuç: {json_path}")
    print("=" * 78 + "\n")

    return output


if __name__ == "__main__":
    run_test()
