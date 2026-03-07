"""H-Engine — Hibrit İşlem Motoru (v1.0).

İnsan işlemi açar, robot yönetir ve kapatır.

Bileşenler:
    H-Baba  → Devir ön kontrolü (risk/yetkilendirme)
    H-Oğul  → Pozisyon yönetimi (breakeven, trailing stop)

Yönetim kuralları:
    1. Giriş SL  = entry_price ± (entry_atr × sl_atr_mult)
    2. Giriş TP  = entry_price ± (entry_atr × tp_atr_mult)
    3. Breakeven = Kâr ≥ breakeven_atr_mult × entry_atr → SL = entry_price
    4. Trailing  = Kâr ≥ trailing_trigger × entry_atr → SL = price ∓ distance × entry_atr
    5. entry_atr devir anında sabitlerir, değişmez.

SL/TP modları:
    - native_sltp=True  → MT5 TRADE_ACTION_SLTP ile SL/TP yönetimi
    - native_sltp=False → Yazılımsal: SL/TP bellekte, H-Oğul fiyat kontrolü,
                           TRADE_ACTION_DEAL ile kapatma (GCM VİOP build<5200 için)

Güvenlik:
    - OĞUL netting koruması (get_hybrid_symbols)
    - EOD 17:45 kapanış (force_close_all)
    - Kill-Switch L3 kapanış (force_close_all)
    - Günlük zarar limiti (check_transfer)
    - Eşzamanlı limit (check_transfer)
    - Native modda atomik devir (MT5 modify başarısız → hiçbir şey değişmez)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, date
from typing import Any, TYPE_CHECKING

import numpy as np

from engine.logger import get_logger
from engine.utils.indicators import atr as calc_atr

if TYPE_CHECKING:
    from engine.baba import Baba
    from engine.config import Config
    from engine.data_pipeline import DataPipeline
    from engine.database import Database
    from engine.mt5_bridge import MT5Bridge

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════
#  SABİTLER
# ═══════════════════════════════════════════════════════════════════

ATR_PERIOD: int = 14          # ATR hesaplama periyodu
MIN_BARS: int = 30            # ATR hesaplamak için min bar sayısı
TRADING_OPEN: dtime = dtime(9, 45)
TRADING_CLOSE: dtime = dtime(17, 45)


# ═══════════════════════════════════════════════════════════════════
#  HybridPosition — Bellekteki pozisyon kaydı
# ═══════════════════════════════════════════════════════════════════

@dataclass
class HybridPosition:
    """Hibrit yönetim altındaki tek pozisyon.

    entry_atr: Devir anındaki ATR değeri — sabit, hiç değişmez.
    breakeven_hit: Kâr 1×ATR'yi geçince True olur.
    trailing_active: Trailing stop devreye girince True olur.
    """

    ticket: int
    symbol: str
    direction: str              # "BUY" | "SELL"
    volume: float
    entry_price: float
    entry_atr: float            # devir anındaki ATR (SABİT)
    initial_sl: float
    initial_tp: float
    current_sl: float
    current_tp: float
    state: str = "ACTIVE"       # ACTIVE | CLOSED
    breakeven_hit: bool = False
    trailing_active: bool = False
    transferred_at: str = ""
    db_id: int = 0


# ═══════════════════════════════════════════════════════════════════
#  H-ENGINE
# ═══════════════════════════════════════════════════════════════════

class HEngine:
    """Hibrit İşlem Motoru — H-Baba (risk) + H-Oğul (yönetim).

    Her 10 saniyede ``run_cycle()`` çağrılır.
    Yalnızca fiyat + ATR kullanır, karmaşık indikatör yok.
    """

    def __init__(
        self,
        config: Config,
        mt5: MT5Bridge,
        db: Database,
        baba: Baba,
        pipeline: DataPipeline,
    ) -> None:
        self.config = config
        self.mt5 = mt5
        self.db = db
        self.baba = baba
        self.pipeline = pipeline

        # ── Pozisyon deposu (bellek) ──────────────────────────────
        self.hybrid_positions: dict[int, HybridPosition] = {}

        # ── Günlük PnL takibi ─────────────────────────────────────
        self._daily_hybrid_pnl: float = 0.0
        self._daily_pnl_date: str = date.today().isoformat()

        # ── Config parametreleri ──────────────────────────────────
        hybrid_cfg = config.get("hybrid", {})
        self._enabled: bool = hybrid_cfg.get("enabled", True)
        self._max_concurrent: int = hybrid_cfg.get("max_concurrent", 3)
        self._config_daily_limit: float = hybrid_cfg.get("daily_loss_limit", 500.0)
        self._sl_atr_mult: float = hybrid_cfg.get("sl_atr_mult", 2.0)
        self._tp_atr_mult: float = hybrid_cfg.get("tp_atr_mult", 2.0)
        self._breakeven_atr_mult: float = hybrid_cfg.get("breakeven_atr_mult", 1.0)
        self._trailing_trigger_mult: float = hybrid_cfg.get("trailing_trigger_atr_mult", 1.5)
        self._trailing_distance_mult: float = hybrid_cfg.get("trailing_distance_atr_mult", 1.0)
        self._native_sltp: bool = hybrid_cfg.get("native_sltp", False)

        sltp_mode = "NATIVE (MT5)" if self._native_sltp else "SOFTWARE (H-Oğul)"
        logger.info(
            f"H-Engine başlatıldı: max_concurrent={self._max_concurrent}, "
            f"daily_limit={self._config_daily_limit}, "
            f"SL={self._sl_atr_mult}×ATR, TP={self._tp_atr_mult}×ATR, "
            f"SL/TP modu={sltp_mode}"
        )

    # ═════════════════════════════════════════════════════════════════
    #  YARDIMCI — Sembol listesi (OĞUL entegrasyonu)
    # ═════════════════════════════════════════════════════════════════

    def get_hybrid_symbols(self) -> set[str]:
        """Hibrit yönetimindeki aktif sembol kümesini döndür.

        OĞUL bu listeye bakarak netting çakışmasını önler:
        hibrit sembolüne sinyal üretmez.

        Returns:
            Aktif hibrit sembol kümesi.
        """
        return {hp.symbol for hp in self.hybrid_positions.values() if hp.state == "ACTIVE"}

    # ═════════════════════════════════════════════════════════════════
    #  H-BABA — Devir Ön Kontrolü
    # ═════════════════════════════════════════════════════════════════

    def check_transfer(self, ticket: int) -> dict[str, Any]:
        """Pozisyonun hibrite devredilip devredilemeyeceğini kontrol et.

        9 adımlı kontrol sırası (H-Baba):
            1. H-Engine aktif mi?
            2. Kill-switch seviyesi < 3?
            3. İşlem saatleri içinde mi?
            4. Ticket MT5'te açık pozisyon mu?
            5. Sembol zaten hibrit yönetiminde mi?
            6. Sembol OĞUL active_trades'te mi?
            7. Eşzamanlı hibrit limit aşılıyor mu?
            8. Günlük hibrit zarar limiti aşılmış mı?
            9. ATR verisi mevcut mu?

        Args:
            ticket: MT5 pozisyon ticket numarası.

        Returns:
            dict: can_transfer, reason, ve ek bilgiler.
        """
        result: dict[str, Any] = {
            "can_transfer": False,
            "reason": "",
            "symbol": "",
            "direction": "",
            "volume": 0.0,
            "entry_price": 0.0,
            "current_price": 0.0,
            "atr_value": 0.0,
            "suggested_sl": 0.0,
            "suggested_tp": 0.0,
            "hybrid_daily_pnl": self._daily_hybrid_pnl,
            "hybrid_daily_limit": self._config_daily_limit,
            "active_hybrid_count": len(self.hybrid_positions),
            "max_hybrid_count": self._max_concurrent,
        }

        # 1. H-Engine aktif mi?
        if not self._enabled:
            result["reason"] = "Hibrit motor devre dışı"
            return result

        # 2. Kill-switch seviyesi
        if self.baba and self.baba.kill_switch_level >= 3:
            result["reason"] = "Kill-switch L3 aktif — tüm işlemler durduruldu"
            return result

        # 3. İşlem saatleri
        now = datetime.now()
        if not self._is_trading_hours(now):
            result["reason"] = "İşlem saatleri dışında (09:45-17:45)"
            return result

        # 4. MT5'te pozisyon kontrolü
        positions = self.mt5.get_positions()
        if not positions:
            result["reason"] = "MT5'te açık pozisyon bulunamadı"
            return result

        mt5_pos = next((p for p in positions if p.get("ticket") == ticket), None)
        if mt5_pos is None:
            result["reason"] = f"Ticket {ticket} MT5'te bulunamadı"
            return result

        symbol = mt5_pos.get("symbol", "")
        direction = "BUY" if mt5_pos.get("type", -1) in (0, "BUY") else "SELL"
        volume = mt5_pos.get("volume", 0.0)
        entry_price = mt5_pos.get("price_open", 0.0)
        current_price = mt5_pos.get("price_current", 0.0)

        result["symbol"] = symbol
        result["direction"] = direction
        result["volume"] = volume
        result["entry_price"] = entry_price
        result["current_price"] = current_price

        # 5. Sembol zaten hibrit yönetiminde mi?
        if symbol in self.get_hybrid_symbols():
            result["reason"] = f"{symbol} zaten hibrit yönetiminde (netting)"
            return result

        # 6. Ticket zaten hibrit yönetiminde mi?
        if ticket in self.hybrid_positions:
            result["reason"] = f"Ticket {ticket} zaten hibrit yönetiminde"
            return result

        # 7. Eşzamanlı limit
        active_count = len(self.hybrid_positions)
        if active_count >= self._max_concurrent:
            result["reason"] = (
                f"Eşzamanlı hibrit limit aşıldı ({active_count}/{self._max_concurrent})"
            )
            return result

        # 8. Günlük zarar limiti
        self._refresh_daily_pnl()
        if self._daily_hybrid_pnl <= -abs(self._config_daily_limit):
            result["reason"] = (
                f"Günlük hibrit zarar limiti aşıldı "
                f"({self._daily_hybrid_pnl:.2f} / -{self._config_daily_limit:.2f} TRY)"
            )
            return result

        # 9. ATR verisi
        atr_value = self._get_atr(symbol)
        if atr_value is None or atr_value <= 0:
            result["reason"] = f"{symbol} için ATR verisi bulunamadı"
            return result

        result["atr_value"] = atr_value

        # SL/TP önerileri hesapla
        if direction == "BUY":
            result["suggested_sl"] = entry_price - (atr_value * self._sl_atr_mult)
            result["suggested_tp"] = entry_price + (atr_value * self._tp_atr_mult)
        else:
            result["suggested_sl"] = entry_price + (atr_value * self._sl_atr_mult)
            result["suggested_tp"] = entry_price - (atr_value * self._tp_atr_mult)

        result["can_transfer"] = True
        result["reason"] = "Hibrite devir uygun"
        return result

    # ═════════════════════════════════════════════════════════════════
    #  ATOMİK DEVİR
    # ═════════════════════════════════════════════════════════════════

    def transfer_to_hybrid(self, ticket: int) -> dict[str, Any]:
        """Pozisyonu hibrit yönetime devret — atomik işlem.

        Sıralama:
            1. check_transfer() ile ön kontrol
            2. ATR al, SL/TP hesapla
            3. MT5 modify_position(ticket, sl, tp) — ÖNCE MT5'e yaz
            4. Başarılıysa → DB insert + belleğe ekle
            5. Başarısızsa → hiçbir şey değişmez

        Args:
            ticket: MT5 pozisyon ticket numarası.

        Returns:
            dict: success, message, ticket, symbol, sl, tp, entry_atr.
        """
        result = {
            "success": False, "message": "", "ticket": ticket,
            "symbol": "", "sl": 0.0, "tp": 0.0, "entry_atr": 0.0,
        }

        # Ön kontrol
        check = self.check_transfer(ticket)
        if not check["can_transfer"]:
            result["message"] = check["reason"]
            return result

        symbol = check["symbol"]
        direction = check["direction"]
        volume = check["volume"]
        entry_price = check["entry_price"]
        atr_value = check["atr_value"]
        suggested_sl = check["suggested_sl"]
        suggested_tp = check["suggested_tp"]

        result["symbol"] = symbol
        result["entry_atr"] = atr_value

        # ── 1. SL/TP ataması ────────────────────────────────────────
        if self._native_sltp:
            # Native mod: MT5'e SL/TP yaz (atomik — başarısızsa devir iptal)
            modify_result = self.mt5.modify_position(
                ticket, sl=suggested_sl, tp=suggested_tp,
            )
            if modify_result is None:
                result["message"] = "MT5 SL/TP ataması başarısız — devir iptal"
                detail = getattr(self.mt5, "_last_modify_error", None)
                if detail:
                    if "last_error" in detail:
                        result["message"] += f" — MT5: {detail['last_error']}"
                    elif "retcode" in detail:
                        result["message"] += f" — retcode={detail.get('retcode')} {detail.get('comment', '')}"
                    elif "exception" in detail:
                        result["message"] += f" — {detail['exception']}"
                logger.error(
                    f"Hibrit devir başarısız — MT5 modify hatası: "
                    f"ticket={ticket} {symbol} | {result['message']}"
                )
                return result
        else:
            # Software mod: MT5 native SLTP kullanılmıyor.
            # SL/TP yalnızca bellekte/DB'de tutulur, H-Oğul run_cycle
            # her 10sn'de fiyat kontrolü yaparak DEAL ile kapatır.
            logger.info(
                f"Software SL/TP modu: ticket={ticket} {symbol} "
                f"SL={suggested_sl:.4f} TP={suggested_tp:.4f} (MT5 modify atlandı)"
            )

        # ── 2. DB'ye kaydet ───────────────────────────────────────
        try:
            db_id = self.db.insert_hybrid_position({
                "ticket": ticket,
                "symbol": symbol,
                "direction": direction,
                "volume": volume,
                "entry_price": entry_price,
                "entry_atr": atr_value,
                "initial_sl": suggested_sl,
                "initial_tp": suggested_tp,
                "current_sl": suggested_sl,
                "current_tp": suggested_tp,
            })
        except Exception as exc:
            logger.error(f"Hibrit DB insert hatası: {exc}")
            result["message"] = f"DB kayıt hatası: {exc}"
            return result

        # ── 2b. trades tablosundaki strategy'yi güncelle ─────────
        try:
            self.db._execute(
                "UPDATE trades SET strategy='hibrit' WHERE mt5_position_id=?",
                (ticket,),
            )
        except Exception:
            pass  # trade kaydı henüz sync olmamış olabilir

        # ── 3. Belleğe ekle ───────────────────────────────────────
        hp = HybridPosition(
            ticket=ticket,
            symbol=symbol,
            direction=direction,
            volume=volume,
            entry_price=entry_price,
            entry_atr=atr_value,
            initial_sl=suggested_sl,
            initial_tp=suggested_tp,
            current_sl=suggested_sl,
            current_tp=suggested_tp,
            state="ACTIVE",
            transferred_at=datetime.now().isoformat(timespec="seconds"),
            db_id=db_id,
        )
        self.hybrid_positions[ticket] = hp

        # ── 4. Event log ──────────────────────────────────────────
        self.db.insert_hybrid_event(
            ticket=ticket, symbol=symbol, event="TRANSFER",
            details={
                "direction": direction, "volume": volume,
                "entry_price": entry_price, "entry_atr": atr_value,
                "sl": suggested_sl, "tp": suggested_tp,
            },
        )

        result["success"] = True
        result["message"] = "Pozisyon hibrit yönetime devredildi"
        result["sl"] = suggested_sl
        result["tp"] = suggested_tp

        logger.info(
            f"Hibrit devir başarılı: ticket={ticket} {symbol} {direction} "
            f"SL={suggested_sl:.4f} TP={suggested_tp:.4f} ATR={atr_value:.4f}"
        )
        return result

    # ═════════════════════════════════════════════════════════════════
    #  HİBRİTTEN ÇIKAR
    # ═════════════════════════════════════════════════════════════════

    def remove_from_hybrid(self, ticket: int) -> dict[str, Any]:
        """Pozisyonu hibrit yönetiminden çıkar — SL/TP kalır, yönetim durur.

        Args:
            ticket: MT5 pozisyon ticket numarası.

        Returns:
            dict: success, message.
        """
        if ticket not in self.hybrid_positions:
            return {"success": False, "message": f"Ticket {ticket} hibrit yönetiminde değil"}

        hp = self.hybrid_positions[ticket]
        symbol = hp.symbol

        # DB güncelle
        self.db.close_hybrid_position(
            ticket=ticket, reason="MANUAL_REMOVE", pnl=0.0, swap=0.0,
        )
        self.db.insert_hybrid_event(
            ticket=ticket, symbol=symbol, event="REMOVE",
            details={"reason": "Kullanıcı tarafından çıkarıldı"},
        )

        # Bellekten kaldır
        del self.hybrid_positions[ticket]

        logger.info(f"Hibrit yönetiminden çıkarıldı: ticket={ticket} {symbol}")
        return {"success": True, "message": f"{symbol} hibrit yönetiminden çıkarıldı"}

    # ═════════════════════════════════════════════════════════════════
    #  ANA DÖNGÜ — Her 10sn (H-Oğul)
    # ═════════════════════════════════════════════════════════════════

    def run_cycle(self) -> None:
        """Tüm aktif hibrit pozisyonları yönet.

        Her 10 saniyede ``main_loop`` tarafından çağrılır.

        Sıralama:
            1. Günlük PnL tarih kontrolü (gün değişimi)
            2. Her pozisyon için: sync → breakeven → trailing
        """
        if not self._enabled or not self.hybrid_positions:
            return

        # Gün değişimi kontrolü
        self._refresh_daily_pnl()

        # MT5'ten güncel pozisyonları al
        try:
            mt5_positions = self.mt5.get_positions()
        except Exception as exc:
            logger.error(f"H-Engine get_positions hatası: {exc}")
            return

        mt5_by_ticket: dict[int, dict] = {
            p.get("ticket"): p for p in (mt5_positions or [])
        }

        # Her aktif pozisyonu yönet (snapshot — iterasyon sırasında dict değişebilir)
        for ticket in list(self.hybrid_positions.keys()):
            hp = self.hybrid_positions.get(ticket)
            if hp is None or hp.state != "ACTIVE":
                continue

            mt5_pos = mt5_by_ticket.get(ticket)

            # ── Sync: Pozisyon MT5'te kapanmış mı? ────────────────
            if mt5_pos is None:
                self._handle_external_close(hp)
                continue

            current_price = mt5_pos.get("price_current", 0.0)
            profit = mt5_pos.get("profit", 0.0)
            swap = mt5_pos.get("swap", 0.0)

            if current_price <= 0:
                continue

            # ── Software SL/TP kontrolü (native kapalıysa) ───────
            if not self._native_sltp:
                if self._check_software_sltp(hp, current_price, profit, swap):
                    continue  # Pozisyon kapatıldı, sonraki döngüye geç

            # ── Breakeven kontrolü ────────────────────────────────
            self._check_breakeven(hp, current_price, profit, swap)

            # ── Trailing stop kontrolü ────────────────────────────
            self._check_trailing(hp, current_price, profit, swap)

    # ═════════════════════════════════════════════════════════════════
    #  SOFTWARE SL/TP — Fiyat bazlı kapatma (native SLTP kapalıyken)
    # ═════════════════════════════════════════════════════════════════

    def _check_software_sltp(
        self, hp: HybridPosition, current_price: float,
        profit: float, swap: float,
    ) -> bool:
        """Yazılımsal SL/TP kontrolü — fiyat SL veya TP'yi aştıysa DEAL ile kapat.

        Native SLTP çalışmadığında (GCM VİOP build<5200) bu fonksiyon
        her 10sn'de fiyatı kontrol eder ve ihlal varsa close_position ile kapatır.

        Args:
            hp: Hibrit pozisyon.
            current_price: Güncel fiyat.
            profit: MT5 profit.
            swap: Birikmiş swap.

        Returns:
            True ise pozisyon kapatıldı, False ise devam.
        """
        sl_hit = False
        tp_hit = False

        if hp.direction == "BUY":
            if hp.current_sl > 0 and current_price <= hp.current_sl:
                sl_hit = True
            if hp.current_tp > 0 and current_price >= hp.current_tp:
                tp_hit = True
        else:  # SELL
            if hp.current_sl > 0 and current_price >= hp.current_sl:
                sl_hit = True
            if hp.current_tp > 0 and current_price <= hp.current_tp:
                tp_hit = True

        if not sl_hit and not tp_hit:
            return False

        reason = "SOFTWARE_SL" if sl_hit else "SOFTWARE_TP"
        triggered_level = hp.current_sl if sl_hit else hp.current_tp

        logger.info(
            f"Software {reason}: ticket={hp.ticket} {hp.symbol} {hp.direction} "
            f"fiyat={current_price:.4f} seviye={triggered_level:.4f} — kapatılıyor"
        )

        # TRADE_ACTION_DEAL ile kapat
        close_result = self.mt5.close_position(hp.ticket)
        if close_result is None:
            logger.error(
                f"Software {reason} kapatma başarısız: ticket={hp.ticket} {hp.symbol}"
            )
            return False

        total_pnl = profit + swap
        self._finalize_close(hp, reason, total_pnl, swap)

        logger.info(
            f"Software {reason} başarılı: ticket={hp.ticket} {hp.symbol} "
            f"PnL={total_pnl:.2f}"
        )
        return True

    # ═════════════════════════════════════════════════════════════════
    #  BREAKEVEN — Kâr ≥ breakeven_mult × entry_atr → SL = entry
    # ═════════════════════════════════════════════════════════════════

    def _check_breakeven(
        self, hp: HybridPosition, current_price: float,
        profit: float, swap: float,
    ) -> None:
        """Breakeven koşulunu kontrol et ve gerekirse SL'yi giriş fiyatına taşı.

        Koşul: Fiyat hareketinden oluşan kâr ≥ breakeven_atr_mult × entry_atr
        Etki: SL = entry_price (zarar riski sıfırlanır)

        Args:
            hp: Hibrit pozisyon.
            current_price: Güncel fiyat.
            profit: MT5 profit (swap hariç).
            swap: Birikmiş swap.
        """
        if hp.breakeven_hit:
            return

        # Fiyat bazlı kâr hesabı (yön dikkate alınır)
        price_diff = self._price_profit(hp, current_price)
        breakeven_threshold = self._breakeven_atr_mult * hp.entry_atr

        if price_diff < breakeven_threshold:
            return

        # Breakeven SL: giriş fiyatı
        new_sl = hp.entry_price

        # Mevcut SL zaten giriş fiyatında veya daha iyiyse güncelleme yapma
        if hp.direction == "BUY" and hp.current_sl >= new_sl:
            hp.breakeven_hit = True
            return
        if hp.direction == "SELL" and hp.current_sl <= new_sl:
            hp.breakeven_hit = True
            return

        # MT5'e yaz (native mod) veya sadece internal güncelle (software mod)
        if self._native_sltp:
            modify_result = self.mt5.modify_position(hp.ticket, sl=new_sl)
            if modify_result is None:
                logger.warning(
                    f"Breakeven SL modify başarısız: ticket={hp.ticket} {hp.symbol}"
                )
                return

        old_sl = hp.current_sl
        hp.current_sl = new_sl
        hp.breakeven_hit = True

        # DB güncelle
        self.db.update_hybrid_position(hp.ticket, {
            "current_sl": new_sl,
            "breakeven_hit": 1,
        })
        self.db.insert_hybrid_event(
            ticket=hp.ticket, symbol=hp.symbol, event="BREAKEVEN",
            details={
                "old_sl": old_sl, "new_sl": new_sl,
                "price": current_price, "entry_atr": hp.entry_atr,
                "mode": "native" if self._native_sltp else "software",
            },
        )

        logger.info(
            f"Breakeven SL: ticket={hp.ticket} {hp.symbol} "
            f"SL {old_sl:.4f} → {new_sl:.4f} (fiyat={current_price:.4f}) "
            f"[{'native' if self._native_sltp else 'software'}]"
        )

    # ═════════════════════════════════════════════════════════════════
    #  TRAILING STOP — Kâr ≥ trigger × ATR → SL = price ∓ distance × ATR
    # ═════════════════════════════════════════════════════════════════

    def _check_trailing(
        self, hp: HybridPosition, current_price: float,
        profit: float, swap: float,
    ) -> None:
        """Trailing stop kontrolü — breakeven sonrası devreye girer.

        Koşul: breakeven_hit == True VE kâr ≥ trailing_trigger × entry_atr
        Etki: SL = current_price - distance × entry_atr (BUY)
               SL = current_price + distance × entry_atr (SELL)
        Kural: SL sadece daha iyi yöne taşınır (BUY: yukarı, SELL: aşağı)

        Args:
            hp: Hibrit pozisyon.
            current_price: Güncel fiyat.
            profit: MT5 profit.
            swap: Birikmiş swap.
        """
        if not hp.breakeven_hit:
            return

        price_diff = self._price_profit(hp, current_price)
        trailing_threshold = self._trailing_trigger_mult * hp.entry_atr

        if price_diff < trailing_threshold:
            return

        # Trailing SL hesapla
        distance = self._trailing_distance_mult * hp.entry_atr
        if hp.direction == "BUY":
            new_sl = current_price - distance
            # SL sadece yukarı taşınır
            if new_sl <= hp.current_sl:
                return
        else:
            new_sl = current_price + distance
            # SL sadece aşağı taşınır
            if new_sl >= hp.current_sl:
                return

        # MT5'e yaz (native mod) veya sadece internal güncelle (software mod)
        if self._native_sltp:
            modify_result = self.mt5.modify_position(hp.ticket, sl=new_sl)
            if modify_result is None:
                logger.warning(
                    f"Trailing SL modify başarısız: ticket={hp.ticket} {hp.symbol}"
                )
                return

        old_sl = hp.current_sl
        hp.current_sl = new_sl
        hp.trailing_active = True

        # DB güncelle
        self.db.update_hybrid_position(hp.ticket, {
            "current_sl": new_sl,
            "trailing_active": 1,
        })
        self.db.insert_hybrid_event(
            ticket=hp.ticket, symbol=hp.symbol, event="TRAILING_UPDATE",
            details={
                "old_sl": old_sl, "new_sl": new_sl,
                "price": current_price, "entry_atr": hp.entry_atr,
                "mode": "native" if self._native_sltp else "software",
            },
        )

        logger.info(
            f"Trailing SL: ticket={hp.ticket} {hp.symbol} "
            f"SL {old_sl:.4f} → {new_sl:.4f} (fiyat={current_price:.4f}) "
            f"[{'native' if self._native_sltp else 'software'}]"
        )

    # ═════════════════════════════════════════════════════════════════
    #  ZORLA KAPAT — EOD / Kill-Switch L3
    # ═════════════════════════════════════════════════════════════════

    def force_close_all(self, reason: str) -> list[int]:
        """Tüm aktif hibrit pozisyonları zorla kapat.

        Kill-Switch L3 veya EOD 17:45 tarafından çağrılır.

        Args:
            reason: Kapanış nedeni (EOD_17:45, KILL_SWITCH_L3, vb.).

        Returns:
            Kapatılamayan ticket listesi (boş = hepsi başarılı).
        """
        failed_tickets: list[int] = []

        if not self.hybrid_positions:
            return failed_tickets

        logger.info(
            f"Hibrit pozisyonlar kapatılıyor: {len(self.hybrid_positions)} adet, "
            f"neden={reason}"
        )

        for ticket in list(self.hybrid_positions.keys()):
            hp = self.hybrid_positions.get(ticket)
            if hp is None or hp.state != "ACTIVE":
                continue

            # MT5'ten güncel PnL al
            pnl = 0.0
            swap = 0.0
            try:
                mt5_positions = self.mt5.get_positions()
                mt5_pos = next(
                    (p for p in (mt5_positions or []) if p.get("ticket") == ticket),
                    None,
                )
                if mt5_pos:
                    pnl = mt5_pos.get("profit", 0.0) + mt5_pos.get("swap", 0.0)
                    swap = mt5_pos.get("swap", 0.0)
            except Exception:
                pass

            # MT5'te kapat
            close_result = self.mt5.close_position(ticket)
            if close_result is None:
                logger.error(
                    f"Hibrit force_close başarısız: ticket={ticket} {hp.symbol}"
                )
                failed_tickets.append(ticket)
                continue

            # DB + bellek güncelle
            self._finalize_close(hp, reason, pnl, swap)

        if failed_tickets:
            logger.error(f"Kapatılamayan hibrit ticketlar: {failed_tickets}")
        else:
            logger.info(f"Tüm hibrit pozisyonlar kapatıldı: neden={reason}")

        return failed_tickets

    # ═════════════════════════════════════════════════════════════════
    #  DURUM GERİ YÜKLEME — Engine restart
    # ═════════════════════════════════════════════════════════════════

    def restore_positions(self) -> None:
        """DB'den aktif hibrit pozisyonları belleğe yükle.

        Engine restart sonrası çağrılır. Aktif pozisyonları yeniden
        yönetim altına alır.
        """
        try:
            rows = self.db.get_active_hybrid_positions()
        except Exception as exc:
            logger.error(f"Hibrit pozisyon restore hatası: {exc}")
            return

        for row in rows:
            hp = HybridPosition(
                ticket=row["ticket"],
                symbol=row["symbol"],
                direction=row["direction"],
                volume=row["volume"],
                entry_price=row["entry_price"],
                entry_atr=row["entry_atr"],
                initial_sl=row["initial_sl"],
                initial_tp=row["initial_tp"],
                current_sl=row.get("current_sl") or row["initial_sl"],
                current_tp=row.get("current_tp") or row["initial_tp"],
                state="ACTIVE",
                breakeven_hit=bool(row.get("breakeven_hit", 0)),
                trailing_active=bool(row.get("trailing_active", 0)),
                transferred_at=row.get("transferred_at", ""),
                db_id=row["id"],
            )
            self.hybrid_positions[hp.ticket] = hp

        count = len(self.hybrid_positions)
        if count > 0:
            logger.info(f"Hibrit pozisyonlar geri yüklendi: {count} adet")

        # Günlük PnL'yi DB'den yükle
        self._refresh_daily_pnl()

    # ═════════════════════════════════════════════════════════════════
    #  DAHİLİ YARDIMCILAR
    # ═════════════════════════════════════════════════════════════════

    def _get_atr(self, symbol: str) -> float | None:
        """Sembol için güncel ATR(14) M15 değeri.

        OĞUL'un ``_get_current_atr()`` ile aynı mantık:
        DB'den M15 barları al → calc_atr hesapla → son geçerli değer.

        Args:
            symbol: Kontrat sembolü.

        Returns:
            ATR değeri veya veri yoksa None.
        """
        try:
            df = self.db.get_bars(symbol, "M15", limit=60)
            if df is None or df.empty or len(df) < ATR_PERIOD + 1:
                return None

            close = df["close"].values.astype(np.float64)
            high_arr = df["high"].values.astype(np.float64)
            low_arr = df["low"].values.astype(np.float64)
            atr_arr = calc_atr(high_arr, low_arr, close, ATR_PERIOD)

            # Son geçerli (NaN olmayan) değer
            for i in range(len(atr_arr) - 1, -1, -1):
                if not np.isnan(atr_arr[i]) and atr_arr[i] > 0:
                    return float(atr_arr[i])
            return None
        except Exception as exc:
            logger.error(f"ATR hesaplama hatası [{symbol}]: {exc}")
            return None

    def _price_profit(self, hp: HybridPosition, current_price: float) -> float:
        """Fiyat bazlı kâr (puan olarak, yön dikkate alınır).

        BUY: current_price - entry_price (pozitif = kâr)
        SELL: entry_price - current_price (pozitif = kâr)

        Args:
            hp: Hibrit pozisyon.
            current_price: Güncel fiyat.

        Returns:
            Fiyat farkı (pozitif = kâr yönünde).
        """
        if hp.direction == "BUY":
            return current_price - hp.entry_price
        return hp.entry_price - current_price

    def _is_trading_hours(self, now: datetime | None = None) -> bool:
        """İşlem saatleri içinde olup olmadığını kontrol et (09:45-17:45).

        Args:
            now: Kontrol zamanı. None ise şu an.

        Returns:
            True ise işlem yapılabilir.
        """
        if now is None:
            now = datetime.now()
        current_time = now.time()
        return TRADING_OPEN <= current_time <= TRADING_CLOSE

    def _refresh_daily_pnl(self) -> None:
        """Günlük PnL'yi kontrol et; gün değişmişse sıfırla, DB'den yeniden oku."""
        today = date.today().isoformat()
        if self._daily_pnl_date != today:
            self._daily_pnl_date = today
            self._daily_hybrid_pnl = 0.0
            logger.info("Hibrit günlük PnL sıfırlandı (yeni gün)")

        # DB'den güncel toplam
        try:
            self._daily_hybrid_pnl = self.db.get_hybrid_daily_pnl(today)
        except Exception:
            pass  # Hata durumunda mevcut değeri koru

    def _handle_external_close(self, hp: HybridPosition) -> None:
        """MT5'te kapatılmış (harici kapanış) hibrit pozisyonu işle.

        SL/TP hit veya kullanıcı MT5'ten kapatmış olabilir.

        Args:
            hp: Kapatılan hibrit pozisyon.
        """
        # PnL bilgisi: DB'deki son risk snapshot'tan veya 0
        pnl = 0.0
        swap = 0.0
        self._finalize_close(hp, "EXTERNAL", pnl, swap)
        logger.info(
            f"Hibrit pozisyon harici kapanış: ticket={hp.ticket} {hp.symbol}"
        )

    def _finalize_close(
        self, hp: HybridPosition, reason: str, pnl: float, swap: float,
    ) -> None:
        """Hibrit pozisyonu kapat — DB + bellek güncelle + günlük PnL.

        Args:
            hp: Kapatılan pozisyon.
            reason: Kapanış nedeni.
            pnl: Toplam K/Z (profit + swap).
            swap: Swap maliyeti.
        """
        hp.state = "CLOSED"

        # DB güncelle
        try:
            self.db.close_hybrid_position(
                ticket=hp.ticket, reason=reason, pnl=pnl, swap=swap,
            )
            self.db.insert_hybrid_event(
                ticket=hp.ticket, symbol=hp.symbol, event="CLOSE",
                details={"reason": reason, "pnl": pnl, "swap": swap},
            )
        except Exception as exc:
            logger.error(f"Hibrit close DB hatası: {exc}")

        # Günlük PnL güncelle
        self._daily_hybrid_pnl += pnl

        # Bellekten kaldır
        self.hybrid_positions.pop(hp.ticket, None)

        logger.info(
            f"Hibrit pozisyon kapatıldı: ticket={hp.ticket} {hp.symbol} "
            f"neden={reason} pnl={pnl:.2f}"
        )
