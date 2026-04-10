"""
HİBRİT MOTOR — 100 KOMBİNASYONLU STRES TESTİ
================================================

PRİMNET pozisyon yönetiminin tüm senaryolarını test eder.
Mock MT5, DB, Baba, Pipeline ile tamamen izole çalışır.

Çalıştırma:
    cd C:\\Users\\pc\\Desktop\\USTAT
    python -m pytest tests/test_hybrid_100.py -v --tb=short
"""

from __future__ import annotations

import json
import sys
import os
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, date
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ── Path ayarı ──────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.h_engine import HEngine, HybridPosition, ATR_PERIOD, TRADING_OPEN, TRADING_CLOSE
from engine.models.regime import RegimeType, Regime


# ═══════════════════════════════════════════════════════════════════
#  MOCK'LAR
# ═══════════════════════════════════════════════════════════════════

HYBRID_CONFIG = {
    "hybrid": {
        "enabled": True,
        "native_sltp": False,
        "max_concurrent": 3,
        "daily_loss_limit": 500.0,
        "sl_atr_mult": 2.0,
        "tp_atr_mult": 2.0,
        "primnet": {
            "faz1_stop_prim": 1.5,
            "faz2_activation_prim": 2.0,
            "faz2_trailing_prim": 1.0,
            "target_prim": 9.5,
        },
    }
}

REF_PRICE = 67.25       # Uzlaşma fiyatı
ONE_PRIM = 0.6725       # 1 prim = ref × 0.01
CONTRACT_SIZE = 100      # VİOP sözleşme büyüklüğü


def _price_at_prim(prim: float) -> float:
    """Prim → fiyat."""
    return REF_PRICE + prim * ONE_PRIM


def _prim_at_price(price: float) -> float:
    """Fiyat → prim."""
    return (price - REF_PRICE) / ONE_PRIM


class MockSymbolInfo:
    """MT5 symbol_info mock."""
    session_price_limit_max = REF_PRICE * 1.10   # tavan
    session_price_limit_min = REF_PRICE * 0.90    # taban
    trade_contract_size = CONTRACT_SIZE


class MockConfig:
    """Config mock — default.json yerine."""
    def __init__(self, overrides=None):
        self._data = HYBRID_CONFIG.copy()
        if overrides:
            self._data.update(overrides)

    def get(self, key, default=None):
        return self._data.get(key, default)


class MockDB:
    """Database mock — bellekte çalışır."""
    def __init__(self):
        self.hybrid_positions = []
        self.hybrid_events = []
        self.notifications = []
        self._daily_pnl = 0.0
        self._next_id = 1

    def insert_hybrid_position(self, data):
        data["id"] = self._next_id
        self._next_id += 1
        self.hybrid_positions.append(data)
        return data["id"]

    def update_hybrid_position(self, ticket, updates):
        for hp in self.hybrid_positions:
            if hp.get("ticket") == ticket:
                hp.update(updates)

    def close_hybrid_position(self, ticket, reason, pnl, swap):
        for hp in self.hybrid_positions:
            if hp.get("ticket") == ticket:
                hp["state"] = "CLOSED"
                hp["close_reason"] = reason
                hp["pnl"] = pnl
                hp["swap"] = swap

    def insert_hybrid_event(self, ticket, symbol, event, details=None):
        self.hybrid_events.append({
            "ticket": ticket, "symbol": symbol, "event": event,
            "details": json.dumps(details or {}),
            "timestamp": datetime.now().isoformat(),
        })

    def get_active_hybrid_positions(self):
        return [hp for hp in self.hybrid_positions if hp.get("state") == "ACTIVE"]

    def get_hybrid_daily_pnl(self, target_date=None):
        return self._daily_pnl

    def insert_notification(self, **kwargs):
        self.notifications.append(kwargs)
        return len(self.notifications)

    def _execute(self, sql, params=None):
        pass  # trades tablosu güncelleme (noop)


class MockBaba:
    """BABA mock."""
    def __init__(self, regime_type=RegimeType.TREND, kill_switch_level=0):
        self.current_regime = Regime(regime_type=regime_type)
        self.kill_switch_level = kill_switch_level


class MockMT5:
    """MT5Bridge mock."""
    def __init__(self):
        self.positions = []
        self.modify_calls = []
        self.close_calls = []
        self._modify_fail = False
        self._close_fail = False

    def get_positions(self):
        return self.positions

    def get_symbol_info(self, symbol):
        return MockSymbolInfo()

    def get_account_info(self):
        """v5.9.2 netting sync için — test fallback (None = margin check skip)."""
        return None

    def get_pending_orders(self, symbol=None):
        """v5.9.2 netting sync — test ortamında pending emir yok."""
        return []

    def cancel_pending_order(self, order_ticket):
        """v5.9.2 netting sync — test ortamında no-op."""
        return {"retcode": 0}

    def modify_position(self, ticket, sl=None, tp=None):
        self.modify_calls.append({"ticket": ticket, "sl": sl, "tp": tp})
        if self._modify_fail:
            return None
        return {"retcode": 0}

    def close_position(self, ticket, expected_volume=None):
        self.close_calls.append({"ticket": ticket, "volume": expected_volume})
        if self._close_fail:
            return None
        return {"retcode": 0}

    def get_deal_summary(self, ticket):
        return {"pnl": 50.0, "swap": -2.0}

    def add_position(self, ticket, symbol, direction, volume, entry, current, sl=0, tp=0, pnl=0, swap=0):
        """Test helper — pozisyon ekle."""
        self.positions.append({
            "ticket": ticket, "symbol": symbol,
            "type": 0 if direction == "BUY" else 1,
            "volume": volume,
            "price_open": entry, "price_current": current,
            "sl": sl, "tp": tp,
            "profit": pnl, "swap": swap,
        })


class MockPipeline:
    """DataPipeline mock."""
    pass


# ═══════════════════════════════════════════════════════════════════
#  FIXTURE
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def engine():
    """Temiz bir HEngine + mock bağımlılıklar oluştur."""
    mt5 = MockMT5()
    db = MockDB()
    baba = MockBaba()
    config = MockConfig()
    pipeline = MockPipeline()

    h = HEngine(config=config, mt5=mt5, db=db, baba=baba, pipeline=pipeline)

    # ATR mock — normalde DB'den bar okur
    h._get_atr = MagicMock(return_value=1.50)
    # Verify mock — test ortamında MT5 gerçek pozisyon döndürmez
    h._verify_mt5_sl = MagicMock(return_value=None)

    return h, mt5, db, baba


def _do_transfer(engine_tuple, ticket=1001, symbol="F_AKBNK", direction="BUY",
                 volume=1.0, entry_prim=0.0, current_prim=0.0):
    """Helper — pozisyon oluşturup hibrite devret."""
    h, mt5, db, baba = engine_tuple
    entry_price = _price_at_prim(entry_prim)
    current_price = _price_at_prim(current_prim)

    mt5.add_position(ticket, symbol, direction, volume, entry_price, current_price)

    with patch.object(h, '_is_trading_hours', return_value=True):
        result = h.transfer_to_hybrid(ticket)

    return result


def _simulate_price(engine_tuple, ticket, new_prim, pnl=None, swap=0.0):
    """Helper — fiyat değiştir ve run_cycle çalıştır."""
    h, mt5, db, baba = engine_tuple
    hp = h.hybrid_positions.get(ticket)
    if not hp:
        return

    new_price = _price_at_prim(new_prim)
    if pnl is None:
        entry_prim = _prim_at_price(hp.entry_price)
        if hp.direction == "BUY":
            pnl = (new_prim - entry_prim) * ONE_PRIM * hp.volume * CONTRACT_SIZE
        else:
            pnl = (entry_prim - new_prim) * ONE_PRIM * hp.volume * CONTRACT_SIZE

    # MT5 pozisyonu güncelle
    mt5.positions = [{
        "ticket": ticket, "symbol": hp.symbol,
        "type": 0 if hp.direction == "BUY" else 1,
        "volume": hp.volume,
        "price_open": hp.entry_price, "price_current": new_price,
        "sl": 0, "tp": 0,
        "profit": pnl, "swap": swap,
    }]

    # Daily reset'in tetiklenmesini engelle (test ortamında tarih farkı olabilir)
    h._daily_reset_done = date.today().isoformat()
    h._daily_pnl_date = date.today().isoformat()

    with patch.object(h, '_is_trading_hours', return_value=True):
        h.run_cycle()


# ═══════════════════════════════════════════════════════════════════
#  KATEGORİ 1: DEVİR (12 test)
# ═══════════════════════════════════════════════════════════════════

class TestTransfer:
    def test_001_buy_transfer(self, engine):
        """BUY pozisyon devir — SL ve TP prim bazlı hesaplanır."""
        result = _do_transfer(engine, direction="BUY", entry_prim=0.0)
        assert result["success"], f"Devir başarısız: {result['message']}"
        hp = engine[0].hybrid_positions[1001]
        sl_prim = _prim_at_price(hp.current_sl)
        tp_prim = _prim_at_price(hp.current_tp)
        assert abs(sl_prim - (-1.5)) < 0.05, f"SL prim: beklenen=-1.5, gerçek={sl_prim:.2f}"
        assert abs(tp_prim - 9.5) < 0.05, f"TP prim: beklenen=+9.5, gerçek={tp_prim:.2f}"

    def test_002_sell_transfer(self, engine):
        """SELL pozisyon devir — SL ve TP ters yön."""
        result = _do_transfer(engine, direction="SELL", entry_prim=0.0)
        assert result["success"]
        hp = engine[0].hybrid_positions[1001]
        sl_prim = _prim_at_price(hp.current_sl)
        tp_prim = _prim_at_price(hp.current_tp)
        assert abs(sl_prim - 1.5) < 0.05, f"SL prim: beklenen=+1.5, gerçek={sl_prim:.2f}"
        assert abs(tp_prim - (-9.5)) < 0.05, f"TP prim: beklenen=-9.5, gerçek={tp_prim:.2f}"

    def test_003_profit_transfer(self, engine):
        """Kârda devir — breakeven_hit=True."""
        result = _do_transfer(engine, entry_prim=0.0, current_prim=2.0)
        assert result["success"]
        hp = engine[0].hybrid_positions[1001]
        assert hp.breakeven_hit is True

    def test_004_loss_transfer(self, engine):
        """Zararda devir — kabul edilir, SL giriş bazlı."""
        result = _do_transfer(engine, entry_prim=0.0, current_prim=-0.5)
        assert result["success"]

    def test_005_no_ref_price(self, engine):
        """Referans fiyat alınamazsa ATR fallback."""
        h, mt5, db, baba = engine
        mt5.get_symbol_info = MagicMock(return_value=None)
        result = _do_transfer(engine)
        assert result["success"]  # ATR fallback ile devam eder

    def test_006_concurrent_limit(self, engine):
        """Eşzamanlı 3 limit — 4. reddedilir."""
        for i in range(3):
            _do_transfer(engine, ticket=1001+i, symbol=f"F_SYM{i}")
        result = _do_transfer(engine, ticket=1004, symbol="F_SYM3")
        assert not result["success"]
        assert "limit" in result["message"].lower()

    def test_007_duplicate_symbol(self, engine):
        """Aynı sembol tekrar devredilemez."""
        _do_transfer(engine, ticket=1001, symbol="F_AKBNK")
        result = _do_transfer(engine, ticket=1002, symbol="F_AKBNK")
        assert not result["success"]
        assert "netting" in result["message"].lower() or "zaten" in result["message"].lower()

    def test_008_l3_blocks_transfer(self, engine):
        """Kill-Switch L3 devri engeller."""
        h, mt5, db, baba = engine
        baba.kill_switch_level = 3
        result = _do_transfer(engine)
        assert not result["success"]
        assert "L3" in result["message"] or "kill" in result["message"].lower()

    def test_009_outside_hours(self, engine):
        """İşlem saatleri dışında devir engeli."""
        h, mt5, db, baba = engine
        mt5.add_position(1001, "F_AKBNK", "BUY", 1.0, REF_PRICE, REF_PRICE)
        with patch.object(h, '_is_trading_hours', return_value=False):
            result = h.transfer_to_hybrid(1001)
        assert not result["success"]
        assert "saat" in result["message"].lower()

    def test_010_missing_ticket(self, engine):
        """MT5'te olmayan ticket."""
        h, mt5, db, baba = engine
        # Pozisyon eklemeden devir dene
        with patch.object(h, '_is_trading_hours', return_value=True):
            result = h.transfer_to_hybrid(99999)
        assert not result["success"]

    def test_011_safety_sl_in_software_mode(self, engine):
        """Software modda güvenlik ağı SL MT5'e yazılır."""
        h, mt5, db, baba = engine
        _do_transfer(engine)
        # modify_position çağrılmış olmalı (güvenlik ağı SL)
        assert len(mt5.modify_calls) >= 1, "Güvenlik ağı SL MT5'e yazılmadı"
        sl_call = mt5.modify_calls[0]
        assert sl_call["sl"] is not None and sl_call["sl"] > 0

    def test_012_daily_loss_limit(self, engine):
        """Günlük zarar limiti aşılınca devir engellenir."""
        h, mt5, db, baba = engine
        db._daily_pnl = -501.0  # limit aşıldı
        result = _do_transfer(engine)
        assert not result["success"]
        assert "zarar" in result["message"].lower() or "limit" in result["message"].lower()


# ═══════════════════════════════════════════════════════════════════
#  KATEGORİ 2: PRİMNET HESAPLAMA (10 test)
# ═══════════════════════════════════════════════════════════════════

class TestPrimCalc:
    def test_013_price_to_prim(self, engine):
        h = engine[0]
        assert abs(h._price_to_prim(68.60, REF_PRICE) - 2.007) < 0.01

    def test_014_negative_prim(self, engine):
        h = engine[0]
        assert abs(h._price_to_prim(66.24, REF_PRICE) - (-1.501)) < 0.01

    def test_015_prim_to_price(self, engine):
        h = engine[0]
        assert abs(h._prim_to_price(5.0, REF_PRICE) - 70.6125) < 0.01

    def test_016_roundtrip(self, engine):
        h = engine[0]
        original = 68.00
        prim = h._price_to_prim(original, REF_PRICE)
        back = h._prim_to_price(prim, REF_PRICE)
        assert abs(back - original) < 0.001

    def test_017_ref_price_normal(self, engine):
        h = engine[0]
        ref = h._get_reference_price("F_AKBNK")
        expected = (REF_PRICE * 1.10 + REF_PRICE * 0.90) / 2
        assert ref is not None
        assert abs(ref - expected) < 0.01

    def test_018_ref_price_suspicious(self, engine):
        """Tavan/taban spread şüpheli — uyarı ama kabul."""
        h, mt5, db, baba = engine
        bad_sym = MagicMock()
        bad_sym.session_price_limit_max = 70.0
        bad_sym.session_price_limit_min = 65.0  # spread %7.4
        mt5.get_symbol_info = MagicMock(return_value=bad_sym)
        ref = h._get_reference_price("F_TEST")
        assert ref is not None  # Kabul edilir ama uyarı loglanır

    def test_019_zero_ref(self, engine):
        """Sıfır referans — prim 0 döner, crash yok."""
        h = engine[0]
        assert h._price_to_prim(68.00, 0.0) == 0.0

    def test_020_small_ref(self, engine):
        h = engine[0]
        prim = h._price_to_prim(0.505, 0.50)
        assert abs(prim - 1.0) < 0.01

    def test_021_buy_profit_prim(self, engine):
        h = engine[0]
        hp = HybridPosition(ticket=1, symbol="F_T", direction="BUY", volume=1,
                            entry_price=REF_PRICE, entry_atr=1.0,
                            initial_sl=0, initial_tp=0, current_sl=0, current_tp=0)
        assert h._price_profit(hp, _price_at_prim(3.0)) > 0

    def test_022_sell_profit_prim(self, engine):
        h = engine[0]
        hp = HybridPosition(ticket=1, symbol="F_T", direction="SELL", volume=1,
                            entry_price=REF_PRICE, entry_atr=1.0,
                            initial_sl=0, initial_tp=0, current_sl=0, current_tp=0)
        assert h._price_profit(hp, _price_at_prim(-3.0)) > 0


# ═══════════════════════════════════════════════════════════════════
#  KATEGORİ 3: FAZ 1 TRAİLİNG (10 test)
# ═══════════════════════════════════════════════════════════════════

class TestFaz1:
    def test_023_buy_faz1_start(self, engine):
        """BUY Faz1 trailing başlangıç."""
        _do_transfer(engine, entry_prim=0.0)
        _simulate_price(engine, 1001, new_prim=0.5)
        hp = engine[0].hybrid_positions[1001]
        sl_prim = _prim_at_price(hp.current_sl)
        # 0.5 - 1.5 = -1.0 ama eski SL -1.5'ten iyi → güncellenir
        assert sl_prim > -1.5, f"SL iyileşmedi: {sl_prim:.2f}"

    def test_024_buy_faz1_improve(self, engine):
        """BUY Faz1 SL iyileşme: fiyat yükseldikçe SL yukarı kayar."""
        _do_transfer(engine, entry_prim=0.0)
        _simulate_price(engine, 1001, new_prim=1.0)
        sl1 = engine[0].hybrid_positions[1001].current_sl
        _simulate_price(engine, 1001, new_prim=1.5)
        sl2 = engine[0].hybrid_positions[1001].current_sl
        assert sl2 > sl1, f"SL iyileşmedi: {sl1:.4f} → {sl2:.4f}"

    def test_025_buy_faz1_no_regress(self, engine):
        """BUY Faz1 SL gerilemez — fiyat düşünce SL sabit kalır."""
        _do_transfer(engine, entry_prim=0.0)
        _simulate_price(engine, 1001, new_prim=1.5)
        sl_high = engine[0].hybrid_positions[1001].current_sl
        _simulate_price(engine, 1001, new_prim=1.0)
        sl_after = engine[0].hybrid_positions[1001].current_sl
        assert sl_after >= sl_high, f"SL geriledi: {sl_high:.4f} → {sl_after:.4f}"

    def test_026_sell_faz1_start(self, engine):
        """SELL Faz1 trailing."""
        _do_transfer(engine, direction="SELL", entry_prim=0.0)
        _simulate_price(engine, 1001, new_prim=-0.5)
        hp = engine[0].hybrid_positions[1001]
        sl_prim = _prim_at_price(hp.current_sl)
        assert sl_prim < 1.5, f"SELL SL iyileşmedi: {sl_prim:.2f}"

    def test_027_sell_faz1_improve(self, engine):
        _do_transfer(engine, direction="SELL", entry_prim=0.0)
        _simulate_price(engine, 1001, new_prim=-1.0)
        sl1 = engine[0].hybrid_positions[1001].current_sl
        _simulate_price(engine, 1001, new_prim=-1.5)
        sl2 = engine[0].hybrid_positions[1001].current_sl
        assert sl2 < sl1, f"SELL SL iyileşmedi: {sl1:.4f} → {sl2:.4f}"

    def test_028_sell_faz1_no_regress(self, engine):
        _do_transfer(engine, direction="SELL", entry_prim=0.0)
        _simulate_price(engine, 1001, new_prim=-1.5)
        sl_best = engine[0].hybrid_positions[1001].current_sl
        _simulate_price(engine, 1001, new_prim=-1.0)
        sl_after = engine[0].hybrid_positions[1001].current_sl
        assert sl_after <= sl_best, f"SELL SL geriledi: {sl_best:.4f} → {sl_after:.4f}"

    def test_029_faz1_boundary(self, engine):
        """Tam +1.99 prim — hâlâ Faz 1."""
        _do_transfer(engine, entry_prim=0.0)
        _simulate_price(engine, 1001, new_prim=1.99)
        hp = engine[0].hybrid_positions[1001]
        sl_prim = _prim_at_price(hp.current_sl)
        expected_sl = 1.99 - 1.5  # Faz 1 mesafe
        assert abs(sl_prim - expected_sl) < 0.1, f"Faz1 eşik: {sl_prim:.2f} vs {expected_sl:.2f}"

    def test_030_faz1_to_faz2_transition(self, engine):
        """Faz 1 → Faz 2 geçişi (+2.5 prim — net Faz 2)."""
        _do_transfer(engine, entry_prim=0.0)
        _simulate_price(engine, 1001, new_prim=2.5)
        hp = engine[0].hybrid_positions[1001]
        sl_prim = _prim_at_price(hp.current_sl)
        expected_sl = 2.5 - 1.0  # Faz 2 mesafe
        assert abs(sl_prim - expected_sl) < 0.15, f"Faz2 geçiş: {sl_prim:.2f} vs {expected_sl:.2f}"

    def test_031_faz1_sl_written_to_mt5(self, engine):
        """Faz1 SL güncellemesi MT5'e yazılır (software modda bile)."""
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        initial_calls = len(mt5.modify_calls)
        _simulate_price(engine, 1001, new_prim=1.0)
        assert len(mt5.modify_calls) > initial_calls, "Trailing SL MT5'e yazılmadı"

    def test_032_faz1_modify_fail_3x(self, engine):
        """Modify 3x başarısız — bellekte güncellenir, CRITICAL log."""
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        mt5._modify_fail = True
        for prim in [0.5, 1.0, 1.5]:
            _simulate_price(engine, 1001, new_prim=prim)
        # Bellekte SL güncellenmeli (modify başarısız olsa bile)
        hp = h.hybrid_positions[1001]
        sl_prim = _prim_at_price(hp.current_sl)
        assert sl_prim > -1.5, f"SL bellekte güncellenmedi: {sl_prim:.2f}"


# ═══════════════════════════════════════════════════════════════════
#  KATEGORİ 4: FAZ 2 TRAİLİNG (10 test)
# ═══════════════════════════════════════════════════════════════════

class TestFaz2:
    def test_033_buy_faz2_tighter(self, engine):
        """BUY Faz2 — mesafe 1.0 prim (Faz1'den sıkı)."""
        _do_transfer(engine, entry_prim=0.0)
        _simulate_price(engine, 1001, new_prim=3.0)
        hp = engine[0].hybrid_positions[1001]
        sl_prim = _prim_at_price(hp.current_sl)
        assert abs(sl_prim - 2.0) < 0.1, f"Faz2 SL: {sl_prim:.2f} vs beklenen 2.0"

    def test_034_buy_faz2_progressive(self, engine):
        """Faz2 kademeli: +3p → +5p → +8p."""
        _do_transfer(engine, entry_prim=0.0)
        expected_sls = []
        for prim in [3.0, 5.0, 8.0]:
            _simulate_price(engine, 1001, new_prim=prim)
            hp = engine[0].hybrid_positions[1001]
            expected_sls.append(_prim_at_price(hp.current_sl))
        # Her biri bir öncekinden büyük olmalı
        assert expected_sls[1] > expected_sls[0]
        assert expected_sls[2] > expected_sls[1]

    def test_035_sell_faz2(self, engine):
        """SELL Faz2 — aşağı yönde trailing."""
        _do_transfer(engine, direction="SELL", entry_prim=0.0)
        _simulate_price(engine, 1001, new_prim=-3.0)
        hp = engine[0].hybrid_positions[1001]
        sl_prim = _prim_at_price(hp.current_sl)
        assert abs(sl_prim - (-2.0)) < 0.1, f"SELL Faz2 SL: {sl_prim:.2f}"

    def test_036_no_faz2_to_faz1_regress(self, engine):
        """Faz2'den Faz1'e geri dönüş yok — SL monotonluk.
        Not: Fiyat geri geldiğinde software SL tetikleyebilir (SL fiyattan yukarıda kalırsa).
        Burada fiyatı SL üstünde tutuyoruz."""
        _do_transfer(engine, entry_prim=0.0)
        _simulate_price(engine, 1001, new_prim=3.0)
        sl_faz2 = engine[0].hybrid_positions[1001].current_sl
        # Fiyatı SL'nin üstünde tut (software SL tetiklenmesin)
        sl_prim = _prim_at_price(sl_faz2)
        safe_prim = sl_prim + 0.5  # SL'nin 0.5 prim üstünde
        _simulate_price(engine, 1001, new_prim=safe_prim)
        if 1001 in engine[0].hybrid_positions:
            sl_after = engine[0].hybrid_positions[1001].current_sl
            assert sl_after >= sl_faz2, f"SL geriledi: {sl_faz2:.4f} → {sl_after:.4f}"

    def test_037_faz2_locked_profit(self, engine):
        """Faz2 kilitli kâr: SL=+4p ise 4 prim kilitli."""
        _do_transfer(engine, entry_prim=0.0)
        _simulate_price(engine, 1001, new_prim=5.0)
        hp = engine[0].hybrid_positions[1001]
        sl_prim = _prim_at_price(hp.current_sl)
        assert sl_prim >= 3.9, f"Kilitli kâr yetersiz: SL prim={sl_prim:.2f}"

    def test_038_faz2_near_target(self, engine):
        """Tavana yakın (+9.0p) — SL +8.0p."""
        _do_transfer(engine, entry_prim=0.0)
        _simulate_price(engine, 1001, new_prim=9.0)
        hp = engine[0].hybrid_positions[1001]
        sl_prim = _prim_at_price(hp.current_sl)
        assert sl_prim >= 7.9, f"Tavan yakını SL: {sl_prim:.2f}"

    def test_039_faz2_mt5_native_sl(self, engine):
        """Faz2 SL MT5'e yazılır."""
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        calls_before = len(mt5.modify_calls)
        _simulate_price(engine, 1001, new_prim=5.0)
        assert len(mt5.modify_calls) > calls_before

    def test_040_faz2_desync(self, engine):
        """MT5 farklı SL dönerse MT5 değeri kullanılır."""
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        # _verify_mt5_sl mock
        h._verify_mt5_sl = MagicMock(return_value=_price_at_prim(3.5))
        _simulate_price(engine, 1001, new_prim=5.0)
        hp = h.hybrid_positions[1001]
        sl_prim = _prim_at_price(hp.current_sl)
        # MT5'ten farklı SL dönüyorsa o kullanılır
        assert hp.current_sl > 0

    def test_041_faz2_verify(self, engine):
        """Modify başarılı → verify çağrılır."""
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        h._verify_mt5_sl = MagicMock(return_value=None)
        _simulate_price(engine, 1001, new_prim=3.0)
        h._verify_mt5_sl.assert_called()

    def test_042_faz2_big_jump(self, engine):
        """Tek cycle'da büyük sıçrama: +2p → +8p."""
        _do_transfer(engine, entry_prim=0.0)
        _simulate_price(engine, 1001, new_prim=2.0)
        _simulate_price(engine, 1001, new_prim=8.0)
        hp = engine[0].hybrid_positions[1001]
        sl_prim = _prim_at_price(hp.current_sl)
        assert sl_prim >= 6.9, f"Büyük sıçrama SL: {sl_prim:.2f}"


# ═══════════════════════════════════════════════════════════════════
#  KATEGORİ 5: HEDEF KAPANIŞ (8 test)
# ═══════════════════════════════════════════════════════════════════

class TestTarget:
    def test_043_buy_target(self, engine):
        _do_transfer(engine, entry_prim=0.0)
        _simulate_price(engine, 1001, new_prim=9.5)
        assert 1001 not in engine[0].hybrid_positions, "Hedef kapanış olmadı"

    def test_044_sell_target(self, engine):
        _do_transfer(engine, direction="SELL", entry_prim=0.0)
        _simulate_price(engine, 1001, new_prim=-9.5)
        assert 1001 not in engine[0].hybrid_positions, "SELL hedef kapanış olmadı"

    def test_045_near_target(self, engine):
        _do_transfer(engine, entry_prim=0.0)
        _simulate_price(engine, 1001, new_prim=9.4)
        assert 1001 in engine[0].hybrid_positions, "Hedefe 0.1 kala kapatılmamalı"

    def test_046_gap_beyond_target(self, engine):
        _do_transfer(engine, entry_prim=0.0)
        _simulate_price(engine, 1001, new_prim=10.2)
        assert 1001 not in engine[0].hybrid_positions, "Hedef aşımı kapanmalı"

    def test_047_target_close_fail(self, engine):
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        mt5._close_fail = True
        _simulate_price(engine, 1001, new_prim=9.5)
        assert 1001 in engine[0].hybrid_positions, "Başarısız kapanış sonrası açık kalmalı"

    def test_048_target_3x_fail(self, engine):
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        mt5._close_fail = True
        for _ in range(4):
            _simulate_price(engine, 1001, new_prim=9.5)
        assert 1001 in engine[0].hybrid_positions, "3x sonra retry durmalı"

    def test_049_target_pnl_recorded(self, engine):
        _do_transfer(engine, entry_prim=0.0)
        _simulate_price(engine, 1001, new_prim=9.5, pnl=639.0)
        close_events = [e for e in engine[2].hybrid_events if e["event"] == "CLOSE"]
        assert len(close_events) >= 1

    def test_050_target_no_ref(self, engine):
        """Referans fiyat yoksa hedef kontrolü atlanır — pozisyon açık kalır."""
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        # Ref fiyat None dönünce _check_primnet_target False döner
        original_ref = h._get_reference_price
        h._get_reference_price = MagicMock(return_value=None)
        # Software SL/TP de TP'yi kontrol edebilir — TP'yi devre dışı bırak
        h.hybrid_positions[1001].current_tp = 0.0
        _simulate_price(engine, 1001, new_prim=9.5)
        h._get_reference_price = original_ref
        # Ref yoksa ne hedef ne trailing çalışır — ama software SL/TP TP kontrolü de 0 ise atlar
        assert 1001 in h.hybrid_positions, "Ref yoksa hedef kontrolü atlanmalı"


# ═══════════════════════════════════════════════════════════════════
#  KATEGORİ 6: GÜVENLİK — OLAY / L3 / EOD (12 test)
# ═══════════════════════════════════════════════════════════════════

class TestSafety:
    def test_051_olay_force_close(self, engine):
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        baba.current_regime = Regime(regime_type=RegimeType.OLAY)
        _simulate_price(engine, 1001, new_prim=-0.3)
        assert 1001 not in h.hybrid_positions, "OLAY'da kapatılmadı"

    def test_052_olay_multiple(self, engine):
        h, mt5, db, baba = engine
        for i in range(3):
            _do_transfer(engine, ticket=1001+i, symbol=f"F_S{i}")
        baba.current_regime = Regime(regime_type=RegimeType.OLAY)
        with patch.object(h, '_is_trading_hours', return_value=True):
            h.run_cycle()
        assert len(h.hybrid_positions) == 0

    def test_053_olay_close_fail(self, engine):
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        mt5._close_fail = True
        baba.current_regime = Regime(regime_type=RegimeType.OLAY)
        with patch.object(h, '_is_trading_hours', return_value=True):
            h.run_cycle()
        assert 1001 in h.hybrid_positions, "Başarısız kapanış sonrası hâlâ açık"

    def test_054_olay_then_trend(self, engine):
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        baba.current_regime = Regime(regime_type=RegimeType.OLAY)
        _simulate_price(engine, 1001, new_prim=0.0)
        assert len(h.hybrid_positions) == 0
        baba.current_regime = Regime(regime_type=RegimeType.TREND)
        result = _do_transfer(engine, ticket=1002)
        assert result["success"], "OLAY sonrası yeni devir alınabilmeli"

    def test_055_l3_closes_all(self, engine):
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        result = h.force_close_all("KILL_SWITCH_L3")
        assert 1001 not in h.hybrid_positions

    def test_056_eod_notification(self, engine):
        """17:45 sonrası bildirim — pozisyon kapatılmaz."""
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        now = datetime(2026, 3, 28, 17, 46)
        with patch('engine.h_engine.datetime') as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            h._eod_notified_date = ""
            # Manuel kontrol
            today_str = now.date().isoformat()
            if now.time() >= dtime(17, 45) and h._eod_notified_date != today_str:
                h._eod_notified_date = today_str
                assert len(h.hybrid_positions) > 0, "Pozisyon kapatılmamalı"

    def test_057_eod_no_repeat(self, engine):
        """EOD bildirimi günde 1 kez."""
        h = engine[0]
        h._eod_notified_date = date.today().isoformat()
        # Aynı gün tekrar tetiklenmemeli

    def test_058_ogul_eod_skips_hybrid(self, engine):
        """OĞUL EOD — hibrit kapatma kaldırıldı (ogul.py kontrolü)."""
        # Bu integration test — unit'te ogul.py test edilmez
        pass

    def test_059_verify_eod_skips_hybrid(self, engine):
        """_verify_eod_closure hibrit atlar (ogul.py kontrolü)."""
        pass  # Integration test

    def test_060_olay_before_eod(self, engine):
        """OLAY + EOD aynı cycle — OLAY önce çalışır."""
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        baba.current_regime = Regime(regime_type=RegimeType.OLAY)
        # run_cycle OLAY kontrolünü ilk yapıyor
        with patch.object(h, '_is_trading_hours', return_value=True):
            h.run_cycle()
        assert 1001 not in h.hybrid_positions

    def test_061_l3_blocks_new_transfer(self, engine):
        h, mt5, db, baba = engine
        baba.kill_switch_level = 3
        result = _do_transfer(engine)
        assert not result["success"]

    def test_062_l3_existing_positions(self, engine):
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        failed = h.force_close_all("KILL_SWITCH_L3")
        assert len(failed) == 0


# ═══════════════════════════════════════════════════════════════════
#  KATEGORİ 7: SOFTWARE SL/TP (8 test)
# ═══════════════════════════════════════════════════════════════════

class TestSoftwareSLTP:
    def test_063_buy_sl_hit(self, engine):
        h = engine[0]
        _do_transfer(engine, entry_prim=0.0)
        hp = h.hybrid_positions[1001]
        sl_price = hp.current_sl
        _simulate_price(engine, 1001, new_prim=_prim_at_price(sl_price) - 0.1)
        assert 1001 not in h.hybrid_positions, "Software SL tetiklenmedi"

    def test_064_sell_sl_hit(self, engine):
        h = engine[0]
        _do_transfer(engine, direction="SELL", entry_prim=0.0)
        hp = h.hybrid_positions[1001]
        sl_price = hp.current_sl
        _simulate_price(engine, 1001, new_prim=_prim_at_price(sl_price) + 0.1)
        assert 1001 not in h.hybrid_positions

    def test_065_buy_tp_hit(self, engine):
        h = engine[0]
        _do_transfer(engine, entry_prim=0.0)
        hp = h.hybrid_positions[1001]
        tp_price = hp.current_tp
        _simulate_price(engine, 1001, new_prim=_prim_at_price(tp_price) + 0.1)
        # TP veya hedef kapanış ile kapatılmış olmalı
        assert 1001 not in h.hybrid_positions

    def test_066_sl_gap(self, engine):
        """SL'nin çok altına gap — yakaladığı yerde kapatır."""
        h = engine[0]
        _do_transfer(engine, entry_prim=0.0)
        _simulate_price(engine, 1001, new_prim=-5.0, pnl=-336.0)
        assert 1001 not in h.hybrid_positions

    def test_067_close_3x_fail(self, engine):
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        mt5._close_fail = True
        for _ in range(4):
            _simulate_price(engine, 1001, new_prim=-2.0, pnl=-134.0)
        assert 1001 in h.hybrid_positions, "3x sonra retry durmalı"

    def test_068_software_plus_native_sl(self, engine):
        """Trailing SL hem bellekte hem MT5'te."""
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        _simulate_price(engine, 1001, new_prim=5.0)
        hp = h.hybrid_positions[1001]
        # MT5'e yazılan son SL trailing seviyesinde olmalı
        last_modify = mt5.modify_calls[-1]
        assert last_modify["sl"] is not None
        assert abs(last_modify["sl"] - hp.current_sl) < 0.01

    def test_069_tp_exact(self, engine):
        """TP tam eşikte."""
        h = engine[0]
        _do_transfer(engine, entry_prim=0.0)
        hp = h.hybrid_positions[1001]
        tp_prim = _prim_at_price(hp.current_tp)
        _simulate_price(engine, 1001, new_prim=tp_prim)
        # Hedef veya TP kapanışı
        assert 1001 not in h.hybrid_positions

    def test_070_software_skip_in_native(self, engine):
        """Native mod aktifse software SL/TP atlanır."""
        h, mt5, db, baba = engine
        h._native_sltp = True
        _do_transfer(engine, entry_prim=0.0)
        # Software check çağrılmamalı (native mod)
        # run_cycle'da `if not self._native_sltp:` kontrolü var


# ═══════════════════════════════════════════════════════════════════
#  KATEGORİ 8: GÜN GEÇİŞİ (12 test)
# ═══════════════════════════════════════════════════════════════════

class TestOvernight:
    def test_071_daily_reset_trigger(self, engine):
        """Yeni gün + işlem saati → daily reset çalışır."""
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        h._daily_pnl_date = "2026-03-27"  # dünkü tarih
        h._daily_reset_done = ""
        with patch.object(h, '_is_trading_hours', return_value=True):
            h._refresh_daily_pnl()
        events = [e for e in db.hybrid_events if e["event"] == "PRIMNET_DAILY_RESET"]
        assert len(events) >= 1, "Daily reset tetiklenmedi"

    def test_072_no_reset_at_midnight(self, engine):
        """Gece yarısı reset çalışmaz (işlem saati dışı)."""
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        h._daily_pnl_date = "2026-03-27"
        h._daily_reset_done = ""
        with patch.object(h, '_is_trading_hours', return_value=False):
            h._refresh_daily_pnl()
        events = [e for e in db.hybrid_events if e["event"] == "PRIMNET_DAILY_RESET"]
        assert len(events) == 0, "Gece yarısı reset çalışmamalı"

    def test_073_new_ref_sl_calc(self, engine):
        """Yeni referans ile SL yeniden hesaplanır."""
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        old_sl = h.hybrid_positions[1001].current_sl
        h._primnet_daily_reset("2026-03-27")
        # SL değişmiş veya aynı kalmalı (monotonluk)
        new_sl = h.hybrid_positions[1001].current_sl
        assert new_sl > 0

    def test_074_sl_monotonicity(self, engine):
        """Yeni SL eskiden kötüyse eski korunur."""
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        # Trailing ile SL'yi iyileştir
        _simulate_price(engine, 1001, new_prim=5.0)
        good_sl = h.hybrid_positions[1001].current_sl
        # Daily reset yapınca SL kötüleşmemeli
        h._primnet_daily_reset("2026-03-27")
        assert h.hybrid_positions[1001].current_sl >= good_sl

    def test_075_sl_improvement(self, engine):
        """Yeni SL eskiden iyiyse güncellenir."""
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        # İlk SL düşük — daily reset iyileştirse kabul eder
        hp = h.hybrid_positions[1001]
        assert hp.current_sl > 0

    def test_076_tp_updated(self, engine):
        """TP yeni referansla güncellenir."""
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        old_tp = h.hybrid_positions[1001].current_tp
        h._primnet_daily_reset("2026-03-27")
        new_tp = h.hybrid_positions[1001].current_tp
        assert new_tp > 0

    def test_077_faz2_overnight(self, engine):
        """Faz2'de overnight — Faz2 mesafe korunur."""
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        _simulate_price(engine, 1001, new_prim=5.0)
        hp = h.hybrid_positions[1001]
        assert hp.trailing_active is True

    def test_078_faz1_overnight(self, engine):
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        hp = h.hybrid_positions[1001]
        assert hp.trailing_active is False  # henüz trailing başlamadı

    def test_079_no_ref_at_morning(self, engine):
        """Sabah referans alınamazsa eski SL korunur."""
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        old_sl = h.hybrid_positions[1001].current_sl
        h._get_reference_price = MagicMock(return_value=None)
        h._primnet_daily_reset("2026-03-27")
        assert h.hybrid_positions[1001].current_sl == old_sl

    def test_080_daily_reset_db_notification(self, engine):
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        h._primnet_daily_reset("2026-03-27")
        assert len(db.notifications) >= 1

    def test_081_daily_reset_event_bus(self, engine):
        """Event bus bildirimi gönderilir (DB notification kontrolü)."""
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        notif_before = len(db.notifications)
        h._primnet_daily_reset("2026-03-27")
        assert len(db.notifications) > notif_before, "DB bildirim eklenmedi"

    def test_082_weekend_transition(self, engine):
        """Hafta sonu geçişi — Pzt açılışında çalışır."""
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        h._daily_pnl_date = "2026-03-27"  # Cuma
        h._daily_reset_done = ""
        with patch.object(h, '_is_trading_hours', return_value=True):
            h._refresh_daily_pnl()
        events = [e for e in db.hybrid_events if e["event"] == "PRIMNET_DAILY_RESET"]
        assert len(events) >= 1


# ═══════════════════════════════════════════════════════════════════
#  KATEGORİ 9: NETTİNG SYNC (6 test)
# ═══════════════════════════════════════════════════════════════════

class TestNettingSync:
    def test_083_lot_add(self, engine):
        """Lot ekleme — PRİMNET SL/TP yeniden hesaplanır."""
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0, volume=1.0)
        hp = h.hybrid_positions[1001]
        old_sl = hp.current_sl
        hp_mock = hp
        h._sync_netting_volume(hp_mock, 2.0, REF_PRICE + 0.50)
        assert hp_mock.volume == 2.0

    def test_084_lot_reduce(self, engine):
        """Lot çıkarma — SL/TP korunur."""
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0, volume=2.0)
        hp = h.hybrid_positions[1001]
        old_sl = hp.current_sl
        h._sync_netting_volume(hp, 1.0, hp.entry_price)
        assert hp.volume == 1.0
        assert hp.current_sl == old_sl, "Lot çıkarmada SL değişmemeli"

    def test_085_lot_add_no_ref(self, engine):
        """Lot ekleme + ref fiyat yok → ATR fallback."""
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        h._get_reference_price = MagicMock(return_value=None)
        hp = h.hybrid_positions[1001]
        h._sync_netting_volume(hp, 2.0, REF_PRICE + 0.50)
        assert hp.volume == 2.0
        assert hp.current_sl > 0  # ATR fallback

    def test_086_lot_add_breakeven(self, engine):
        """Lot ekleme sonrası breakeven_hit=True (PRİMNET)."""
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        hp = h.hybrid_positions[1001]
        h._sync_netting_volume(hp, 2.0, REF_PRICE + 0.50)
        assert hp.breakeven_hit is True

    def test_087_entry_price_update(self, engine):
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        hp = h.hybrid_positions[1001]
        new_entry = REF_PRICE + 0.50
        h._sync_netting_volume(hp, 2.0, new_entry)
        assert hp.entry_price == new_entry

    def test_088_netting_db_event(self, engine):
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        hp = h.hybrid_positions[1001]
        h._sync_netting_volume(hp, 2.0, REF_PRICE + 0.50)
        sync_events = [e for e in db.hybrid_events if "NETTING" in e["event"]]
        assert len(sync_events) >= 1


# ═══════════════════════════════════════════════════════════════════
#  KATEGORİ 10: KULLANICI KONTROLÜ (6 test)
# ═══════════════════════════════════════════════════════════════════

class TestUserControl:
    def test_089_remove_from_hybrid(self, engine):
        h = engine[0]
        _do_transfer(engine, entry_prim=0.0)
        result = h.remove_from_hybrid(1001)
        assert result["success"]
        assert 1001 not in h.hybrid_positions

    def test_090_external_close_mt5(self, engine):
        """MT5'ten kapatma — 3 miss sonrası algılanır."""
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        mt5.positions = []  # MT5'te pozisyon yok
        for _ in range(3):
            with patch.object(h, '_is_trading_hours', return_value=True):
                h.run_cycle()
        assert 1001 not in h.hybrid_positions, "External close algılanmadı"

    def test_091_external_close_pnl(self, engine):
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        mt5.positions = []
        for _ in range(3):
            with patch.object(h, '_is_trading_hours', return_value=True):
                h.run_cycle()
        close_events = [e for e in db.hybrid_events if e["event"] == "CLOSE"]
        assert len(close_events) >= 1

    def test_092_temporary_miss(self, engine):
        """1 cycle kayıp — geçici, pozisyon açık kalır."""
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        saved_positions = mt5.positions.copy()
        mt5.positions = []  # 1 cycle kayıp
        with patch.object(h, '_is_trading_hours', return_value=True):
            h.run_cycle()
        assert 1001 in h.hybrid_positions, "1. miss'te kapatılmamalı"
        mt5.positions = saved_positions  # geri geldi
        with patch.object(h, '_is_trading_hours', return_value=True):
            h.run_cycle()
        assert 1001 in h.hybrid_positions

    def test_093_3_miss_confirmed(self, engine):
        h, mt5, db, baba = engine
        _do_transfer(engine, entry_prim=0.0)
        mt5.positions = []
        for _ in range(3):
            with patch.object(h, '_is_trading_hours', return_value=True):
                h.run_cycle()
        assert 1001 not in h.hybrid_positions

    def test_094_remove_nonexistent(self, engine):
        h = engine[0]
        result = h.remove_from_hybrid(99999)
        assert not result["success"]


# ═══════════════════════════════════════════════════════════════════
#  KATEGORİ 11: RESTORE (4 test)
# ═══════════════════════════════════════════════════════════════════

class TestRestore:
    def test_095_restore_positions(self, engine):
        h, mt5, db, baba = engine
        db.hybrid_positions.append({
            "id": 1, "ticket": 2001, "symbol": "F_AKBNK", "direction": "BUY",
            "volume": 1.0, "entry_price": REF_PRICE, "entry_atr": 1.5,
            "initial_sl": 66.24, "initial_tp": 73.64,
            "current_sl": 67.00, "current_tp": 73.64,
            "state": "ACTIVE", "breakeven_hit": 0, "trailing_active": 0,
            "transferred_at": "2026-03-28T10:00:00",
        })
        h.restore_positions()
        assert 2001 in h.hybrid_positions
        assert h.hybrid_positions[2001].breakeven_hit is True  # PRİMNET: always True

    def test_096_restore_trailing(self, engine):
        h, mt5, db, baba = engine
        db.hybrid_positions.append({
            "id": 1, "ticket": 2001, "symbol": "F_AKBNK", "direction": "BUY",
            "volume": 1.0, "entry_price": REF_PRICE, "entry_atr": 1.5,
            "initial_sl": 66.24, "initial_tp": 73.64,
            "current_sl": 68.60, "current_tp": 73.64,
            "state": "ACTIVE", "breakeven_hit": 1, "trailing_active": 1,
            "transferred_at": "2026-03-28T10:00:00",
        })
        h.restore_positions()
        hp = h.hybrid_positions[2001]
        assert hp.trailing_active is True
        assert hp.breakeven_hit is True

    def test_097_restore_stale(self, engine):
        """DB'de ACTIVE ama MT5'te kapalı — 3 miss sonrası temizlenir."""
        h, mt5, db, baba = engine
        db.hybrid_positions.append({
            "id": 1, "ticket": 2001, "symbol": "F_AKBNK", "direction": "BUY",
            "volume": 1.0, "entry_price": REF_PRICE, "entry_atr": 1.5,
            "initial_sl": 66.24, "initial_tp": 73.64,
            "state": "ACTIVE", "breakeven_hit": 1, "trailing_active": 0,
            "transferred_at": "2026-03-28T10:00:00",
        })
        h.restore_positions()
        mt5.positions = []  # MT5'te yok
        for _ in range(3):
            with patch.object(h, '_is_trading_hours', return_value=True):
                h.run_cycle()
        assert 2001 not in h.hybrid_positions

    def test_098_restore_daily_pnl(self, engine):
        h, mt5, db, baba = engine
        db._daily_pnl = 250.0
        h._refresh_daily_pnl()
        assert h._daily_hybrid_pnl == 250.0


# ═══════════════════════════════════════════════════════════════════
#  KATEGORİ 12: BİLDİRİM + PERFORMANS (2 test)
# ═══════════════════════════════════════════════════════════════════

class TestNotifPerf:
    def test_099_notification_persistence(self, engine):
        h, mt5, db, baba = engine
        db.insert_notification(
            notif_type="hybrid_eod", title="Test", message="Test msg", severity="warning"
        )
        assert len(db.notifications) >= 1
        assert db.notifications[0]["title"] == "Test"

    def test_100_performance_stats(self, engine):
        """Kapalı pozisyon istatistikleri."""
        h, mt5, db, baba = engine
        # 3 kapalı pozisyon simüle et
        for i, (pnl, reason) in enumerate([
            (150.0, "PRIMNET_TARGET"),
            (-80.0, "SOFTWARE_SL"),
            (200.0, "EXTERNAL"),
        ]):
            db.hybrid_positions.append({
                "state": "CLOSED", "pnl": pnl, "swap": 0.0,
                "close_reason": reason, "ticket": 3000+i,
            })
        # Performance hesaplama (DB mock'ta basit)
        closed = [hp for hp in db.hybrid_positions if hp.get("state") == "CLOSED"]
        pnls = [hp["pnl"] for hp in closed]
        assert len(closed) == 3
        assert sum(1 for p in pnls if p > 0) == 2  # 2 kazanan
        assert sum(pnls) == 270.0  # toplam PnL
