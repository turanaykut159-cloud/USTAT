"""ÜSTAT v5.7 — Tam Sistem Simülasyonu.

MT5 bağlantısı olmadan sahte fiyat akışıyla tüm sistemi uçtan uca çalıştırır.
MockMT5Bridge gerçekçi VİOP fiyat verisi üretir, BABA → OĞUL → ÜSTAT cycle'ı
normal akışta döner, sonuçlar DB ve API üzerinden UI'a yansır.

Kullanım:
    python -m engine.simulation                  # 50 cycle, 15 kontrat
    python -m engine.simulation --cycles 200     # 200 cycle
    python -m engine.simulation --speed 0.5      # yarım saniye aralıkla
    python -m engine.simulation --regime TREND   # sabit rejim zorla
    python -m engine.simulation --volatile       # yüksek volatilite senaryosu

Çıktı:
    - Tüm cycle'lar DB'ye kaydedilir
    - API üzerinden ÜSTAT Beyin Merkezi sayfasında görüntülenebilir
    - Sonuç özeti terminale yazdırılır
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

# ── MetaTrader5 mock (Linux'ta gerçek modül yok) ──────────────────
# Engine import chain mt5_bridge.py → `import MetaTrader5 as mt5` gerektirir.
# Simülasyon modunda gerçek MT5 kullanılmadığı için sahte modül enjekte ediyoruz.
import types as _types

_mock_mt5_module = _types.ModuleType("MetaTrader5")
_mock_mt5_module.TIMEFRAME_M1 = 1
_mock_mt5_module.TIMEFRAME_M5 = 5
_mock_mt5_module.TIMEFRAME_M15 = 15
_mock_mt5_module.TIMEFRAME_H1 = 16385
_mock_mt5_module.TRADE_ACTION_DEAL = 1
_mock_mt5_module.ORDER_TYPE_BUY = 0
_mock_mt5_module.ORDER_TYPE_SELL = 1
_mock_mt5_module.ORDER_FILLING_IOC = 2
_mock_mt5_module.TRADE_RETCODE_DONE = 10009

# Boş fonksiyonlar — çağrılırsa hata vermesin
for _fn in ("initialize", "shutdown", "login", "symbol_info", "symbol_info_tick",
            "copy_rates_from_pos", "order_send", "positions_get", "account_info",
            "terminal_info", "symbols_get"):
    setattr(_mock_mt5_module, _fn, lambda *a, **kw: None)

sys.modules["MetaTrader5"] = _mock_mt5_module
# ──────────────────────────────────────────────────────────────────

from engine.config import Config
from engine.database import Database
from engine.logger import get_logger

logger = get_logger(__name__)

# ── İzlenen 15 VİOP kontrat ──────────────────────────────────────
SYMBOLS: list[str] = [
    "F_THYAO", "F_AKBNK", "F_ASELS", "F_TCELL", "F_HALKB",
    "F_PGSUS", "F_GUBRF", "F_EKGYO", "F_SOKM",  "F_TKFEN",
    "F_OYAKC", "F_BRSAN", "F_AKSEN", "F_ASTOR", "F_KONTR",
]

# Gerçekçi VİOP başlangıç fiyatları (TL)
BASE_PRICES: dict[str, float] = {
    "F_THYAO": 305.0, "F_AKBNK": 68.0,  "F_ASELS": 95.0,
    "F_TCELL": 120.0, "F_HALKB": 22.0,  "F_PGSUS": 1650.0,
    "F_GUBRF": 195.0, "F_EKGYO": 14.5,  "F_SOKM": 43.0,
    "F_TKFEN": 240.0, "F_OYAKC": 78.0,  "F_BRSAN": 330.0,
    "F_AKSEN": 58.0,  "F_ASTOR": 520.0, "F_KONTR": 42.0,
}

# Kontrat çarpanları
CONTRACT_SIZES: dict[str, float] = {
    "F_THYAO": 100, "F_AKBNK": 100, "F_ASELS": 100,
    "F_TCELL": 100, "F_HALKB": 100, "F_PGSUS": 10,
    "F_GUBRF": 100, "F_EKGYO": 100, "F_SOKM": 100,
    "F_TKFEN": 100, "F_OYAKC": 100, "F_BRSAN": 10,
    "F_AKSEN": 100, "F_ASTOR": 10,  "F_KONTR": 100,
}


# ═══════════════════════════════════════════════════════════════════
#  SAHTE FİYAT ÜRETECİ
# ═══════════════════════════════════════════════════════════════════

class PriceGenerator:
    """Gerçekçi VİOP fiyat serisi üretir (geometric Brownian motion + rejim).

    Her kontrat ve timeframe için persistent bar geçmişi tutar.
    advance_cycle() çağrıldıkça mevcut geçmişe yeni bar eklenir,
    böylece göstergeler (EMA, ADX, ATR) tutarlı hesaplanır.
    """

    TIMEFRAMES = ["M1", "M5", "M15", "H1"]
    TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60}

    def __init__(self, regime: str = "auto", volatile: bool = False):
        self.regime = regime
        self.volatile = volatile
        self._prices: dict[str, float] = dict(BASE_PRICES)
        self._cycle_count = 0

        # Her kontrat için rastgele trend yönü (küçük, gerçekçi)
        self._trend_dir: dict[str, float] = {}
        for s in SYMBOLS:
            self._trend_dir[s] = random.choice([-1, 1]) * random.uniform(0.00005, 0.0003)

        # Persistent bar geçmişi: {(symbol, timeframe): [bar_dict, ...]}
        self._bar_history: dict[tuple[str, str], list[dict]] = {}
        self._init_history()

    def _init_history(self) -> None:
        """Başlangıçta her sembol/timeframe için 600 barlık geçmiş oluştur."""
        for s in SYMBOLS:
            for tf in self.TIMEFRAMES:
                self._bar_history[(s, tf)] = self._generate_initial_bars(s, tf, 600)

    def _generate_initial_bars(self, symbol: str, timeframe: str, count: int) -> list[dict]:
        """Başlangıç bar geçmişi üret — düşük volatilite ile gerçekçi seri."""
        price = self._prices[symbol]
        bars = []
        now = datetime.now().replace(hour=10, minute=30, second=0, microsecond=0)
        interval = timedelta(minutes=self.TF_MINUTES.get(timeframe, 5))

        # Başlangıç volatilitesi düşük (normal piyasa)
        base_vol = 0.003
        tf_mult = {"M1": 0.4, "M5": 1.0, "M15": 1.7, "H1": 3.5}
        vol = base_vol * tf_mult.get(timeframe, 1.0)
        drift = self._trend_dir[symbol]

        for i in range(count):
            t = now - interval * (count - i)
            ret = drift + vol * np.random.randn()
            open_p = price
            close_p = price * (1 + ret)

            # OHLC tutarlılık: high/low open-close aralığını hafifçe aşar
            hi = max(open_p, close_p) * (1 + abs(np.random.randn()) * vol * 0.15)
            lo = min(open_p, close_p) * (1 - abs(np.random.randn()) * vol * 0.15)

            bars.append({
                "time": t,
                "open": round(open_p, 2),
                "high": round(hi, 2),
                "low": round(lo, 2),
                "close": round(close_p, 2),
                "tick_volume": random.randint(80, 400),
                "spread": random.randint(1, 4),
                "real_volume": random.randint(800, 4000),
            })
            price = close_p

        self._prices[symbol] = round(price, 2)
        return bars

    def get_current_regime(self) -> str:
        """Simülasyon rejimini döndür."""
        if self.regime != "auto":
            return self.regime
        cycle_phase = (self._cycle_count // 50) % 4
        regimes = ["TREND", "RANGE", "OLAY", "TREND"]
        return regimes[cycle_phase]

    def generate_bars(self, symbol: str, timeframe: str = "M5", count: int = 500) -> pd.DataFrame:
        """Mevcut persistent geçmişten son `count` barı döndür."""
        key = (symbol, timeframe)
        history = self._bar_history.get(key, [])
        if not history:
            # Fallback: yeni geçmiş oluştur
            history = self._generate_initial_bars(symbol, timeframe, 600)
            self._bar_history[key] = history

        # Son count barı al
        bars = history[-count:] if len(history) >= count else history
        return pd.DataFrame(bars)

    def generate_tick(self, symbol: str):
        """Anlık bid/ask/spread üret."""
        price = self._prices.get(symbol, 100.0)
        spread_pips = random.randint(1, 3)
        half_spread = spread_pips * 0.01 / 2
        return {
            "symbol": symbol,
            "bid": round(price - half_spread, 2),
            "ask": round(price + half_spread, 2),
            "spread": spread_pips,
            "time": datetime.now(),
        }

    def advance_cycle(self):
        """Bir cycle ilerlet — her sembol/TF'ye yeni bar ekle."""
        self._cycle_count += 1
        regime = self.get_current_regime()

        # Rejim bazlı volatilite (küçük, gerçekçi)
        vol_map = {"TREND": 0.003, "RANGE": 0.002, "OLAY": 0.006, "UNKNOWN": 0.003}
        base_vol = vol_map.get(regime, 0.003)
        if self.volatile:
            base_vol *= 1.8

        # Her 80 cycle'da bazı kontratların trend yönü değişsin
        if self._cycle_count % 80 == 0:
            for s in random.sample(SYMBOLS, k=random.randint(2, 5)):
                self._trend_dir[s] = random.choice([-1, 1]) * random.uniform(0.00005, 0.0003)

        tf_mult = {"M1": 0.4, "M5": 1.0, "M15": 1.7, "H1": 3.5}

        for s in SYMBOLS:
            price = self._prices[s]
            drift = self._trend_dir[s]
            if regime == "TREND":
                drift *= 2.0
            elif regime == "RANGE":
                drift *= 0.3

            for tf in self.TIMEFRAMES:
                vol = base_vol * tf_mult.get(tf, 1.0)
                ret = drift + vol * np.random.randn()
                open_p = price
                close_p = price * (1 + ret)
                hi = max(open_p, close_p) * (1 + abs(np.random.randn()) * vol * 0.15)
                lo = min(open_p, close_p) * (1 - abs(np.random.randn()) * vol * 0.15)

                history = self._bar_history.get((s, tf), [])
                last_time = history[-1]["time"] if history else datetime.now()
                new_time = last_time + timedelta(minutes=self.TF_MINUTES[tf])

                bar = {
                    "time": new_time,
                    "open": round(open_p, 2),
                    "high": round(hi, 2),
                    "low": round(lo, 2),
                    "close": round(close_p, 2),
                    "tick_volume": random.randint(80, 400),
                    "spread": random.randint(1, 3),
                    "real_volume": random.randint(800, 4000),
                }
                history.append(bar)

                # Bellek kontrolü: max 800 bar tut
                if len(history) > 800:
                    history[:] = history[-700:]

                self._bar_history[(s, tf)] = history

            # Fiyatı M5'in son close'una eşitle (tutarlılık)
            m5_history = self._bar_history.get((s, "M5"), [])
            if m5_history:
                self._prices[s] = m5_history[-1]["close"]


# ═══════════════════════════════════════════════════════════════════
#  MOCK MT5 BRIDGE
# ═══════════════════════════════════════════════════════════════════

class MockMT5Bridge:
    """MT5Bridge arayüzünü taklit eden sahte bridge.

    Engine sınıfına enjekte edilir, gerçek MT5 bağlantısı yerine
    PriceGenerator'dan veri döndürür.
    """

    # MT5 timeframe sabitleri
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_H1 = 16385

    TF_MAP = {1: "M1", 5: "M5", 15: "M15", 16385: "H1"}

    def __init__(self, price_gen: PriceGenerator, balance: float = 10000.0,
                 db=None, time_fn=None):
        self._gen = price_gen
        self._connected = True
        self._balance = balance
        self._equity = balance
        self._health: Any = None
        self._db = db  # DB referansı — SL/TP kapanışlarını kaydetmek için
        self._time_fn = time_fn or datetime.now  # Simüle edilmiş zaman fonksiyonu

        # Symbol map (base → base, gerçek MT5'te suffix eklenir)
        self._symbol_map: dict[str, str] = {s: s for s in SYMBOLS}
        self._reverse_map: dict[str, str] = {s: s for s in SYMBOLS}
        self._map_lock = __import__("threading").Lock()
        self._write_lock = __import__("threading").Lock()

        # Pozisyon simülasyonu
        self._positions: list[dict] = []
        self._next_ticket: int = 100000

        # SL/TP kapanış sayaçları
        self._sl_close_count: int = 0
        self._tp_close_count: int = 0
        self._total_realized_pnl: float = 0.0

        logger.info(f"[SIM] MockMT5Bridge başlatıldı — {len(SYMBOLS)} kontrat")

    def is_connected(self) -> bool:
        return self._connected

    def connect(self, launch: bool = True) -> bool:
        self._connected = True
        logger.info("[SIM] Mock MT5 bağlantısı kuruldu")
        return True

    def disconnect(self) -> None:
        self._connected = False

    def heartbeat(self) -> bool:
        return True

    def _to_mt5(self, symbol: str) -> str:
        return symbol

    def _to_base(self, mt5_name: str) -> str:
        return mt5_name

    def _is_watched(self, symbol: str) -> bool:
        return symbol in SYMBOLS

    # ── Hesap bilgisi ──────────────────────────────────────────────
    def get_account_info(self):
        from engine.mt5_bridge import AccountInfo
        floating = sum(p.get("profit", 0) for p in self._positions)
        self._equity = self._balance + floating
        return AccountInfo(
            login=12345678,
            server="SIM-Demo",
            balance=self._balance,
            equity=self._equity,
            margin=len(self._positions) * 500.0,
            free_margin=self._equity - len(self._positions) * 500.0,
            margin_level=9999.0 if not self._positions else (self._equity / (len(self._positions) * 500.0)) * 100,
            currency="TRY",
        )

    # ── Sembol bilgisi ──────────────────────────────────────────────
    def get_symbol_info(self, symbol: str):
        from engine.mt5_bridge import SymbolInfo
        price = self._gen._prices.get(symbol, 100.0)
        cs = CONTRACT_SIZES.get(symbol, 100)
        return SymbolInfo(
            name=symbol,
            point=0.01,
            trade_contract_size=cs,
            trade_tick_value=cs * 0.01,
            volume_min=1.0,
            volume_max=50.0,
            volume_step=1.0,
            bid=round(price - 0.01, 2),
            ask=round(price + 0.01, 2),
            spread=2,
        )

    # ── Bar verisi ──────────────────────────────────────────────────
    def get_bars(self, symbol: str, timeframe: int = 5, count: int = 500) -> pd.DataFrame:
        tf_str = self.TF_MAP.get(timeframe, "M5")
        return self._gen.generate_bars(symbol, tf_str, count)

    # ── Tick verisi ─────────────────────────────────────────────────
    def get_tick(self, symbol: str):
        from engine.mt5_bridge import Tick
        t = self._gen.generate_tick(symbol)
        return Tick(symbol=t["symbol"], bid=t["bid"], ask=t["ask"],
                    spread=t["spread"], time=t["time"])

    # ── Pozisyon yönetimi (simüle) ──────────────────────────────────
    def positions_get(self) -> list:
        return self._positions

    def send_order(self, symbol: str, direction: str, lot: float,
                   price: float, sl: float = 0.0, tp: float = 0.0,
                   order_type: str = "market") -> dict | None:
        """Sahte emir gönder — pozisyon oluştur (MT5Bridge imza uyumlu)."""
        tick = self._gen.generate_tick(symbol)
        entry_price = tick["ask"] if direction == "BUY" else tick["bid"]

        self._next_ticket += 1
        pos = {
            "ticket": self._next_ticket,
            "symbol": symbol,
            "type": 0 if direction == "BUY" else 1,
            "volume": lot,
            "price_open": entry_price,
            "sl": sl or 0.0,
            "tp": tp or 0.0,
            "profit": 0.0,
            "comment": f"SIM_{order_type}",
            "magic": 0,
            "time": int(self._time_fn().timestamp()),
        }
        self._positions.append(pos)
        logger.info(f"[SIM] Emir açıldı: {symbol} {direction} {lot:.2f} lot @ {entry_price:.2f} ({order_type})")
        return {
            "retcode": 10009,
            "order": self._next_ticket,
            "deal": self._next_ticket,
            "volume": lot,
            "price": entry_price,
            "comment": f"SIM_{order_type}",
        }

    def close_position(self, ticket: int) -> dict | None:
        """Sahte pozisyon kapat."""
        for i, p in enumerate(self._positions):
            if p["ticket"] == ticket:
                tick = self._gen.generate_tick(p["symbol"])
                exit_price = tick["bid"] if p["type"] == 0 else tick["ask"]
                pnl = (exit_price - p["price_open"]) * p["volume"] * CONTRACT_SIZES.get(p["symbol"], 100)
                if p["type"] == 1:
                    pnl = -pnl
                self._balance += pnl
                self._positions.pop(i)
                logger.info(f"[SIM] Pozisyon kapatıldı: #{ticket} {p['symbol']} K/Z={pnl:.2f} TL")
                return {"retcode": 10009, "order": ticket, "profit": pnl}
        return None

    def modify_position(self, ticket, sl=None, tp=None) -> dict | None:
        for p in self._positions:
            if p["ticket"] == ticket:
                if sl is not None:
                    p["sl"] = sl
                if tp is not None:
                    p["tp"] = tp
                return {"retcode": 10009}
        return None

    def get_positions(self) -> list[dict]:
        """MT5Bridge.get_positions() uyumlu — dict listesi döndürür."""
        self.update_floating_pnl()
        result = []
        for p in self._positions:
            tick = self._gen.generate_tick(p["symbol"])
            result.append({
                "ticket": p["ticket"],
                "symbol": p["symbol"],
                "type": "BUY" if p["type"] == 0 else "SELL",
                "volume": p["volume"],
                "price_open": p["price_open"],
                "sl": p.get("sl", 0.0),
                "tp": p.get("tp", 0.0),
                "price_current": tick["bid"] if p["type"] == 0 else tick["ask"],
                "profit": p["profit"],
                "swap": 0.0,
                "time": datetime.fromtimestamp(p.get("time", datetime.now().timestamp())).isoformat(),
            })
        return result

    def get_history_for_sync(self, days: int = 90) -> list[dict]:
        """Mock geçmiş — boş liste döndür."""
        return []

    def update_floating_pnl(self):
        """Açık pozisyonların floating PnL'ini güncelle VE SL/TP execute et.

        Gerçek borsada SL/TP emirleri exchange tarafından otomatik tetiklenir.
        Simülasyonda bu davranışı her tick güncellemesinde kontrol ederiz:
          - BUY: bid <= SL → stop-loss, bid >= TP → take-profit
          - SELL: ask >= SL → stop-loss, ask <= TP → take-profit
        """
        closed_tickets: list[int] = []

        for p in self._positions:
            tick = self._gen.generate_tick(p["symbol"])
            cs = CONTRACT_SIZES.get(p["symbol"], 100)

            if p["type"] == 0:  # BUY
                current_price = tick["bid"]
                p["profit"] = (current_price - p["price_open"]) * p["volume"] * cs

                # SL check: fiyat stop-loss'un altına düştü
                if p["sl"] > 0 and current_price <= p["sl"]:
                    pnl = (p["sl"] - p["price_open"]) * p["volume"] * cs
                    self._balance += pnl
                    self._total_realized_pnl += pnl
                    self._sl_close_count += 1
                    p["_close_pnl"] = pnl
                    p["_exit_reason"] = "SL_HIT"
                    closed_tickets.append(p["ticket"])
                    logger.info(
                        f"[SIM] STOP-LOSS tetiklendi: #{p['ticket']} {p['symbol']} "
                        f"BUY @ {p['price_open']:.2f} -> SL={p['sl']:.2f} "
                        f"K/Z={pnl:+.2f} TL"
                    )
                    continue

                # TP check: fiyat take-profit'e ulaştı
                if p["tp"] > 0 and current_price >= p["tp"]:
                    pnl = (p["tp"] - p["price_open"]) * p["volume"] * cs
                    self._balance += pnl
                    self._total_realized_pnl += pnl
                    self._tp_close_count += 1
                    p["_close_pnl"] = pnl
                    p["_exit_reason"] = "TP_HIT"
                    closed_tickets.append(p["ticket"])
                    logger.info(
                        f"[SIM] TAKE-PROFIT tetiklendi: #{p['ticket']} {p['symbol']} "
                        f"BUY @ {p['price_open']:.2f} -> TP={p['tp']:.2f} "
                        f"K/Z={pnl:+.2f} TL"
                    )
                    continue

            else:  # SELL
                current_price = tick["ask"]
                p["profit"] = (p["price_open"] - current_price) * p["volume"] * cs

                # SL check: fiyat stop-loss'un üstüne çıktı
                if p["sl"] > 0 and current_price >= p["sl"]:
                    pnl = (p["price_open"] - p["sl"]) * p["volume"] * cs
                    self._balance += pnl
                    self._total_realized_pnl += pnl
                    self._sl_close_count += 1
                    p["_close_pnl"] = pnl
                    p["_exit_reason"] = "SL_HIT"
                    closed_tickets.append(p["ticket"])
                    logger.info(
                        f"[SIM] STOP-LOSS tetiklendi: #{p['ticket']} {p['symbol']} "
                        f"SELL @ {p['price_open']:.2f} -> SL={p['sl']:.2f} "
                        f"K/Z={pnl:+.2f} TL"
                    )
                    continue

                # TP check: fiyat take-profit'e ulaştı
                if p["tp"] > 0 and current_price <= p["tp"]:
                    pnl = (p["price_open"] - p["tp"]) * p["volume"] * cs
                    self._balance += pnl
                    self._total_realized_pnl += pnl
                    self._tp_close_count += 1
                    p["_close_pnl"] = pnl
                    p["_exit_reason"] = "TP_HIT"
                    closed_tickets.append(p["ticket"])
                    logger.info(
                        f"[SIM] TAKE-PROFIT tetiklendi: #{p['ticket']} {p['symbol']} "
                        f"SELL @ {p['price_open']:.2f} -> TP={p['tp']:.2f} "
                        f"K/Z={pnl:+.2f} TL"
                    )
                    continue

        # Kapatılan pozisyonları DB'ye kaydet ve listeden çıkar
        if closed_tickets:
            for p in self._positions:
                if p["ticket"] in closed_tickets:
                    self._record_closed_trade(p)
            self._positions = [
                p for p in self._positions
                if p["ticket"] not in closed_tickets
            ]

    def _record_closed_trade(self, pos: dict) -> None:
        """Kapanan pozisyonu DB'ye yaz — ÜSTAT beyin modülleri için gerekli."""
        if not self._db:
            return
        try:
            tick = self._gen.generate_tick(pos["symbol"])
            cs = CONTRACT_SIZES.get(pos["symbol"], 100)
            direction = "BUY" if pos["type"] == 0 else "SELL"

            if pos["type"] == 0:
                exit_price = tick["bid"]
            else:
                exit_price = tick["ask"]

            # SL/TP'den kapandıysa kesin fiyatı hesapla
            pnl = pos.get("_close_pnl", pos.get("profit", 0.0))
            exit_reason = pos.get("_exit_reason", "SL_TP")

            sim_now = self._time_fn()
            entry_time = datetime.fromtimestamp(
                pos.get("time", sim_now.timestamp())
            ).strftime("%Y-%m-%d %H:%M:%S")
            exit_time = sim_now.strftime("%Y-%m-%d %H:%M:%S")

            self._db.insert_trade({
                "strategy": "OGUL_SIM",
                "symbol": pos["symbol"],
                "direction": direction,
                "entry_time": entry_time,
                "exit_time": exit_time,
                "entry_price": pos["price_open"],
                "exit_price": exit_price,
                "lot": pos["volume"],
                "pnl": pnl,
                "slippage": 0.0,
                "commission": 0.0,
                "swap": 0.0,
                "regime": "SIM",
                "exit_reason": exit_reason,
            })
            logger.info(
                f"[SIM] Trade DB'ye kaydedildi: {pos['symbol']} {direction} "
                f"K/Z={pnl:+.2f} TL ({exit_reason})"
            )
        except Exception as exc:
            logger.warning(f"[SIM] Trade DB kayıt hatası: {exc}")


# ═══════════════════════════════════════════════════════════════════
#  SİMÜLASYON RUNNER
# ═══════════════════════════════════════════════════════════════════

class SimulationRunner:
    """Tam sistem simülasyonu çalıştırıcı.

    MockMT5Bridge'i Engine'e enjekte eder, belirtilen sayıda cycle döndürür.
    Her cycle'da BABA → OĞUL → ÜSTAT sırası korunur.
    """

    def __init__(
        self,
        cycles: int = 50,
        speed: float = 1.0,
        regime: str = "auto",
        volatile: bool = False,
        balance: float = 10000.0,
    ):
        self.cycles = cycles
        self.speed = speed
        self.regime = regime
        self.volatile = volatile
        self.balance = balance

        # Bileşenler
        self.price_gen = PriceGenerator(regime=regime, volatile=volatile)
        self.config = Config()

        # Paper mode KAPALI — simülasyonda mock MT5 ile gerçek emir akışı test edilir
        self.config._data.setdefault("engine", {})["paper_mode"] = False

        # Simülasyon için ayrı DB (canlı engine DB'sine dokunma)
        import tempfile, os
        self._sim_db_dir = tempfile.mkdtemp(prefix="ustat_sim_")
        sim_db_path = os.path.join(self._sim_db_dir, "sim_trades.db")
        self.config._data.setdefault("database", {})["path"] = sim_db_path
        self.db = Database(self.config)

        # Çok günlü simülasyon: her CYCLES_PER_DAY cycle = 1 iş günü
        self.CYCLES_PER_DAY = max(cycles // 5, 50)  # En az 5 gün simüle et

        # MockMT5Bridge — DB referansıyla (kapanan işlemleri kaydeder)
        # time_fn run() içinde _SimDatetime tanımlandıktan sonra ayarlanır
        self.mock_mt5 = MockMT5Bridge(self.price_gen, balance=balance, db=self.db)

        # Sonuç istatistikleri
        self.stats = {
            "total_cycles": 0,
            "signals_generated": 0,
            "trades_opened": 0,
            "trades_closed_sl": 0,
            "trades_closed_tp": 0,
            "trades_closed_manual": 0,
            "max_open_positions": 0,
            "regime_changes": 0,
            "errors_attributed": 0,
            "decisions_logged": 0,
            "final_balance": balance,
            "final_pnl": 0.0,
            "regimes_seen": set(),
        }

    def _seed_historical_trades(self, start_date: date) -> None:
        """Simülasyon başlamadan önce DB'ye sentetik geçmiş işlemleri ekle.

        Bu işlemler ÜSTAT'ın beyin modüllerini tetikler:
        - Kaybeden işlemler → hata ataması
        - Dünkü kapanışlar → ertesi gün analizi
        - Yeterli veri → regülasyon önerisi

        Args:
            start_date: Simülasyonun başladığı tarih.
        """
        import random
        symbols = SYMBOLS  # SYMBOLS zaten list[str]
        strategies = ["trend_follow", "mean_reversion", "breakout"]

        # Son 5 iş günü için sentetik işlemler oluştur
        trade_date = start_date
        for day_offset in range(5):
            # Geriye doğru iş günleri bul
            d = start_date - timedelta(days=day_offset + 1)
            while d.weekday() >= 5:
                d -= timedelta(days=1)

            n_trades = random.randint(3, 6)
            for _ in range(n_trades):
                sym = random.choice(symbols)
                direction = random.choice(["BUY", "SELL"])
                strategy = random.choice(strategies)
                price = BASE_PRICES.get(sym, 100.0)
                lot = random.choice([1.0, 2.0, 3.0])

                # %60 kaybeden, %40 kazanan (hata ataması testi için)
                is_loss = random.random() < 0.60
                if is_loss:
                    pnl = -random.uniform(50, 500)
                    exit_reason = random.choice(["SL_HIT", "TIMEOUT"])
                else:
                    pnl = random.uniform(30, 400)
                    exit_reason = "TP_HIT"

                entry_hour = random.randint(10, 15)
                exit_hour = min(entry_hour + random.randint(1, 4), 17)

                entry_time = f"{d.isoformat()} {entry_hour:02d}:{random.randint(0, 59):02d}:00"
                exit_time = f"{d.isoformat()} {exit_hour:02d}:{random.randint(0, 59):02d}:00"

                cs = CONTRACT_SIZES.get(sym, 100)
                entry_price = price * (1 + random.uniform(-0.02, 0.02))
                if direction == "BUY":
                    exit_price = entry_price + (pnl / (lot * cs))
                else:
                    exit_price = entry_price - (pnl / (lot * cs))

                self.db.insert_trade({
                    "strategy": strategy,
                    "symbol": sym,
                    "direction": direction,
                    "entry_time": entry_time,
                    "exit_time": exit_time,
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(exit_price, 2),
                    "lot": lot,
                    "pnl": round(pnl, 2),
                    "slippage": 0.0,
                    "commission": 0.0,
                    "swap": 0.0,
                    "regime": "SIM",
                    "exit_reason": exit_reason,
                })

            # Ayrıca risk olayları ekle (BABA hata ataması için)
            if random.random() < 0.4:
                self.db.insert_event(
                    event_type="DRAWDOWN_WARNING",
                    message=f"Drawdown uyarısı: %{random.uniform(3, 8):.1f}",
                    severity="WARNING",
                    action="risk_check",
                )

        count = len(self.db.get_trades(limit=100, closed_only=True))
        logger.info(f"[SIM] Sentetik geçmiş: {count} işlem DB'ye eklendi")

    def run(self) -> dict:
        """Simülasyonu çalıştır.

        Returns:
            Simülasyon sonuç istatistikleri.
        """
        print("\n" + "=" * 70)
        print("  ÜSTAT v5.7 — TAM SİSTEM SİMÜLASYONU")
        print("=" * 70)
        print(f"  Cycle sayısı  : {self.cycles}")
        print(f"  Hız           : {self.speed}s/cycle")
        print(f"  Rejim         : {self.regime}")
        print(f"  Volatilite    : {'YÜKSEK' if self.volatile else 'NORMAL'}")
        print(f"  Başlangıç     : {self.balance:,.2f} TL")
        print(f"  Kontrat sayısı: {len(SYMBOLS)}")
        print("=" * 70 + "\n")

        # ── Çok günlü saat ayarı ──────────────────────────────────────
        # datetime.now() monkey-patch: cycle ilerledikçe gün de ilerler
        # Her CYCLES_PER_DAY cycle = 1 iş günü.  Saat her zaman 11:00.
        import engine.utils.time_utils as _tu_mod

        _real_datetime = datetime
        _runner_ref = self  # closure için

        class _SimDatetime(datetime):
            """datetime.now() override — cycle'a göre gün ilerletir, saat=11:00."""
            _current_cycle: int = 0

            @classmethod
            def now(cls, tz=None):
                real = _real_datetime.now(tz)
                # Kaç iş günü geçti?
                days_offset = cls._current_cycle // _runner_ref.CYCLES_PER_DAY
                # Geriye doğru günleri ayarla: simülasyon "bugün"den N gün önce başlar
                # Böylece ilk günlerin işlemleri "dün" olarak görülür
                total_sim_days = _runner_ref.cycles // _runner_ref.CYCLES_PER_DAY + 1
                start_offset = total_sim_days - 1  # kaç gün geriden başla
                actual_day_offset = days_offset - start_offset
                # İş günleri hesapla (hafta sonlarını atla)
                sim_date = real.date()
                remaining = actual_day_offset
                if remaining <= 0:
                    step = -1
                    remaining = abs(remaining)
                else:
                    step = 1
                    remaining = remaining
                for _ in range(remaining):
                    sim_date += timedelta(days=step)
                    while sim_date.weekday() >= 5:  # Cumartesi/Pazar atla
                        sim_date += timedelta(days=step)

                return _real_datetime(
                    sim_date.year, sim_date.month, sim_date.day,
                    11, 0, 0, 0,
                )

        self._sim_datetime_cls = _SimDatetime

        # Engine modüllerindeki datetime referansını değiştir
        import engine.ogul as _ogul_mod
        import engine.h_engine as _hengine_mod
        import engine.baba as _baba_mod
        import engine.data_pipeline as _dp_mod
        import engine.ustat as _ustat_mod
        _ogul_mod.datetime = _SimDatetime
        _hengine_mod.datetime = _SimDatetime
        _baba_mod.datetime = _SimDatetime
        _dp_mod.datetime = _SimDatetime
        _ustat_mod.datetime = _SimDatetime

        # MockMT5Bridge'e simüle edilmiş zaman fonksiyonunu ver
        self.mock_mt5._time_fn = _SimDatetime.now

        # is_market_open her zaman True dönsün
        _tu_mod.is_market_open = lambda *a, **kw: True

        # Sentetik geçmiş işlemler ekle (ÜSTAT beyin modülleri için)
        sim_start_date = _SimDatetime.now().date()
        self._seed_historical_trades(sim_start_date)

        # Engine'i oluştur (MockMT5Bridge enjekte)
        try:
            from engine.main import Engine
            engine = Engine(
                config=self.config,
                db=self.db,
                mt5=self.mock_mt5,
            )

            # Simülasyon override'ları:
            # 1. _is_new_m5_candle her zaman True (her cycle sinyal üret)
            engine.ogul._is_new_m5_candle = lambda: True
            engine.ogul._is_new_m15_candle = lambda: True
            # 2. _is_trading_allowed her zaman True (seans saati yok)
            engine.ogul._is_trading_allowed = lambda *a, **kw: True
            # 3. EOD check bypass (gün sonu kapatma yok)
            engine.ogul._check_end_of_day = lambda: None

        except Exception as e:
            print(f"[HATA] Engine oluşturulamadı: {e}")
            import traceback
            traceback.print_exc()
            return self.stats

        prev_regime = ""

        for i in range(1, self.cycles + 1):
            cycle_start = _time.time()

            # Simülasyon gününü ilerlet
            self._sim_datetime_cls._current_cycle = i

            # Fiyat güncelle
            self.price_gen.advance_cycle()
            self.mock_mt5.update_floating_pnl()

            # Gün değişikliği bildirimi
            sim_now = self._sim_datetime_cls.now()
            sim_date_str = sim_now.strftime("%Y-%m-%d")
            if not hasattr(self, '_prev_sim_date') or self._prev_sim_date != sim_date_str:
                if hasattr(self, '_prev_sim_date'):
                    print(f"\n  📅 Yeni gün: {sim_date_str} (cycle {i})")
                else:
                    print(f"  📅 Başlangıç günü: {sim_date_str}")
                self._prev_sim_date = sim_date_str

            # Rejim bilgisi
            current_regime = self.price_gen.get_current_regime()
            if current_regime != prev_regime:
                if prev_regime:
                    self.stats["regime_changes"] += 1
                    print(f"\n  ⚡ Rejim değişti: {prev_regime} → {current_regime}")
                prev_regime = current_regime
            self.stats["regimes_seen"].add(current_regime)

            # ── Gerçek Engine cycle akışı (main.py _run_single_cycle sırası) ──

            # 1. Veri güncelleme (DataPipeline mock MT5'ten çeker)
            try:
                engine.pipeline.run_cycle()
            except Exception as e:
                logger.debug(f"[SIM] Pipeline cycle hatası (beklenen): {e}")

            # 2. BABA cycle — rejim tespiti (tek argüman: pipeline)
            regime = None
            try:
                regime = engine.baba.run_cycle(engine.pipeline)
            except Exception as e:
                logger.debug(f"[SIM] BABA cycle hatası: {e}")

            # 3. BABA risk kontrolü (tek argüman: risk_params)
            risk_verdict = None
            try:
                risk_verdict = engine.baba.check_risk_limits(engine.risk_params)
            except Exception as e:
                logger.debug(f"[SIM] Risk kontrol hatası: {e}")

            # 4. Top 5 kontrat seçimi
            top5 = []
            try:
                top5 = engine.ogul.select_top5(regime)
            except Exception as e:
                logger.debug(f"[SIM] Top5 seçim hatası: {e}")

            # 5. OĞUL — sinyal üretimi + emir yönetimi
            try:
                if risk_verdict and getattr(risk_verdict, "can_trade", False):
                    engine.ogul.process_signals(top5, regime)
                    self.stats["signals_generated"] += 1
                else:
                    engine.ogul.process_signals([], regime)
            except Exception as e:
                logger.debug(f"[SIM] OĞUL cycle hatası: {e}")

            # 6. H-Engine cycle
            try:
                engine.h_engine.run_cycle()
            except Exception as e:
                logger.debug(f"[SIM] H-Engine cycle hatası: {e}")

            # 7. ÜSTAT brain
            try:
                engine.ustat.run_cycle(engine.baba, engine.ogul)
                self.stats["decisions_logged"] += len(getattr(engine.ustat, "_dedup_cache", {}))
            except Exception as e:
                logger.debug(f"[SIM] ÜSTAT cycle hatası: {e}")

            # İstatistik güncelle
            self.stats["total_cycles"] = i
            pos_count = len(self.mock_mt5._positions)
            self.stats["trades_opened"] = pos_count
            self.stats["max_open_positions"] = max(
                self.stats["max_open_positions"], pos_count
            )
            self.stats["errors_attributed"] = len(getattr(engine.ustat, "error_attributions", []))

            # SL/TP kapanış sayacı: mock_mt5 kapatma loglarından say
            # (her cycle'da closed_tickets güncellenir)
            sl_count = getattr(self.mock_mt5, "_sl_close_count", 0)
            tp_count = getattr(self.mock_mt5, "_tp_close_count", 0)
            self.stats["trades_closed_sl"] = sl_count
            self.stats["trades_closed_tp"] = tp_count

            account = self.mock_mt5.get_account_info()
            self.stats["final_balance"] = account.equity
            self.stats["final_pnl"] = account.equity - self.balance

            # İlerleme çubuğu
            elapsed = _time.time() - cycle_start
            bar_len = 30
            filled = int(bar_len * i / self.cycles)
            bar = "█" * filled + "░" * (bar_len - filled)
            pnl_str = f"{self.stats['final_pnl']:+,.2f}"
            pnl_color = "\033[32m" if self.stats["final_pnl"] >= 0 else "\033[31m"
            sl_tp_str = f"SL:{sl_count} TP:{tp_count}"
            print(
                f"\r  [{bar}] {i}/{self.cycles} | "
                f"Rejim: {current_regime:7s} | "
                f"Poz: {pos_count} | "
                f"{sl_tp_str} | "
                f"K/Z: {pnl_color}{pnl_str}\033[0m TL | "
                f"{elapsed:.2f}s",
                end="", flush=True,
            )

            # Hız kontrolü
            if self.speed > 0:
                sleep_time = max(0, self.speed - elapsed)
                if sleep_time > 0:
                    _time.sleep(sleep_time)

        # ── Sonuç raporu ─────────────────────────────────────────
        self.stats["regimes_seen"] = list(self.stats["regimes_seen"])
        self._print_summary(engine)
        return self.stats

    def _print_summary(self, engine) -> None:
        """Simülasyon sonuç özetini yazdır."""
        s = self.stats
        mt5 = self.mock_mt5
        print("\n\n" + "=" * 70)
        print("  SİMÜLASYON SONUÇ RAPORU")
        print("=" * 70)
        print(f"  Toplam cycle          : {s['total_cycles']}")
        sim_days = s['total_cycles'] // self.CYCLES_PER_DAY + 1
        print(f"  Simüle edilen gün     : {sim_days} iş günü ({self.CYCLES_PER_DAY} cycle/gün)")
        print(f"  Görülen rejimler      : {', '.join(s['regimes_seen'])}")
        print(f"  Rejim değişikliği     : {s['regime_changes']}")

        print(f"\n  ── İşlem İstatistikleri ──")
        print(f"  Sinyal üretildi       : {s['signals_generated']}")
        total_closed = mt5._sl_close_count + mt5._tp_close_count
        print(f"  Toplam kapanan        : {total_closed}")
        print(f"    Stop-Loss kapanış   : {mt5._sl_close_count}")
        print(f"    Take-Profit kapanış : {mt5._tp_close_count}")
        if total_closed > 0:
            win_rate = (mt5._tp_close_count / total_closed) * 100
            print(f"    Win Rate            : {win_rate:.1f}%")
        print(f"  Hâlâ açık pozisyon    : {len(mt5._positions)}")
        print(f"  Max eş zamanlı poz.   : {s['max_open_positions']}")
        print(f"  Gerçekleşen K/Z       : {mt5._total_realized_pnl:>+12,.2f} TL")

        print(f"\n  ── Bakiye ──")
        print(f"  Başlangıç             : {self.balance:>12,.2f} TL")
        print(f"  Son bakiye            : {s['final_balance']:>12,.2f} TL")
        pnl = s["final_pnl"]
        pnl_pct = (pnl / self.balance) * 100
        color = "\033[32m" if pnl >= 0 else "\033[31m"
        print(f"  Toplam K/Z            : {color}{pnl:>+12,.2f} TL ({pnl_pct:+.2f}%)\033[0m")

        # ÜSTAT beyin raporu
        ustat = engine.ustat
        print(f"\n  ── ÜSTAT Beyin Durumu ──")
        print(f"  Hata ataması          : {len(getattr(ustat, 'error_attributions', []))}")
        print(f"  Ertesi gün analizi    : {len(getattr(ustat, 'next_day_analyses', []))}")
        print(f"  Regülasyon önerisi    : {len(getattr(ustat, 'regulation_suggestions', []))}")
        sp = getattr(ustat, "strategy_pool", {})
        print(f"  Strateji havuzu       : rejim={sp.get('current_regime', '?')}, profil={sp.get('active_profile', '?')}")
        print(f"  Kontrat profili       : {len(getattr(ustat, 'contract_profiles', {}))}")
        print(f"  Kategorizasyon        : {len(getattr(ustat, 'trade_categories', {}))}")
        print("=" * 70 + "\n")


# ═══════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="ÜSTAT v5.7 — Tam Sistem Simülasyonu",
    )
    parser.add_argument("--cycles", type=int, default=50, help="Cycle sayısı (varsayılan: 50)")
    parser.add_argument("--speed", type=float, default=1.0, help="Cycle aralığı saniye (varsayılan: 1.0, 0=hızlı)")
    parser.add_argument("--regime", type=str, default="auto", help="Sabit rejim (TREND/RANGE/OLAY/auto)")
    parser.add_argument("--volatile", action="store_true", help="Yüksek volatilite senaryosu")
    parser.add_argument("--balance", type=float, default=10000.0, help="Başlangıç bakiyesi TL (varsayılan: 10000)")

    args = parser.parse_args()

    runner = SimulationRunner(
        cycles=args.cycles,
        speed=args.speed,
        regime=args.regime,
        volatile=args.volatile,
        balance=args.balance,
    )

    try:
        results = runner.run()
    except KeyboardInterrupt:
        print("\n\n  [!] Simülasyon kullanıcı tarafından durduruldu.\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
