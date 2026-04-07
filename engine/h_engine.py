"""H-Engine — Hibrit İşlem Motoru (v2.0 — PRİMNET).

İnsan işlemi açar, robot PRİMNET ile yönetir ve kapatır.

Bileşenler:
    H-Baba  → Devir ön kontrolü (risk/yetkilendirme)
    H-Oğul  → PRİMNET pozisyon yönetimi (prim bazlı trailing stop)

Pozisyon yönetimi — PRİMNET (Prim Bazlı Net Emir Takip):
    1. Giriş SL  = entry_prim - faz1_stop_prim (BUY) / + faz1_stop_prim (SELL)
    2. Giriş TP  = target_prim (tavan/tabana 0.5 prim kala)
    3. Faz 1     = Trailing mesafe: faz1_stop_prim (1.5 prim)
    4. Faz 2     = Kâr ≥ faz2_activation_prim → mesafe daralır: faz2_trailing_prim (1.0 prim)
    5. Hedef     = Prim ≥ target_prim → pozisyon kapatılır
    6. Referans fiyat = (tavan + taban) / 2 — devir anında sabitlenil, değişmez.
    7. Referans fiyat alınamazsa → ATR bazlı SL/TP fallback (sadece giriş için)

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

from dataclasses import dataclass
from datetime import datetime, time as dtime, date
from typing import Any, TYPE_CHECKING

import numpy as np

from engine.logger import get_logger
from engine.models.regime import RegimeType
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
TRADING_OPEN: dtime = dtime(9, 40)
TRADING_CLOSE: dtime = dtime(17, 50)
EOD_NOTIFY: dtime = dtime(17, 45)  # Hibrit EOD bildirim saati


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
    reference_price: float = 0.0  # PRİMNET: Uzlaşma fiyatı (devir günü)
    trailing_order_ticket: int = 0  # PRİMNET Stop Limit: trailing bekleyen emir ticket'ı
    target_order_ticket: int = 0    # PRİMNET Stop Limit: hedef bekleyen emir ticket'ı


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

        # Cross-motor referansı (Engine.__init__ tarafından atanır)
        self.manuel_motor: Any | None = None

        # ── Pozisyon deposu (bellek) ──────────────────────────────
        self.hybrid_positions: dict[int, HybridPosition] = {}

        # ── Günlük PnL takibi ─────────────────────────────────────
        self._daily_hybrid_pnl: float = 0.0
        self._daily_pnl_date: str = date.today().isoformat()

        # ── Software SL/TP kapatma retry sayaçları ─────────────
        self._close_retry_counts: dict[int, int] = {}  # ticket → retry sayısı
        self._MAX_CLOSE_RETRIES: int = 3  # max kapatma denemesi

        # ── EOD bildirim bayrağı (günde 1 kez) ───────────────
        self._eod_notified_date: str = ""

        # ── Günlük PRİMNET yenileme bayrağı ──────────────────
        self._daily_reset_done: str = ""  # hangi gün yapıldı

        # ── Config parametreleri ──────────────────────────────────
        hybrid_cfg = config.get("hybrid", {})
        self._enabled: bool = hybrid_cfg.get("enabled", True)
        self._max_concurrent: int = hybrid_cfg.get("max_concurrent", 3)
        self._config_daily_limit: float = hybrid_cfg.get("daily_loss_limit", 500.0)
        self._sl_atr_mult: float = hybrid_cfg.get("sl_atr_mult", 2.0)
        self._tp_atr_mult: float = hybrid_cfg.get("tp_atr_mult", 2.0)
        self._native_sltp: bool = hybrid_cfg.get("native_sltp", False)

        # ── PRİMNET — Prim Bazlı Net Emir Takip Sistemi ─────────
        # Tek pozisyon yönetim modu: prim cinsinden SL/TP, trailing, hedef
        # Trailing mesafe HER ZAMAN SABİT (faz ayrımı yok)
        primnet_cfg = hybrid_cfg.get("primnet", {})
        self._primnet_trailing: float = primnet_cfg.get("trailing_prim", 1.5)
        self._primnet_target: float = primnet_cfg.get("target_prim", 9.5)
        self._use_stop_limit: bool = primnet_cfg.get("use_stop_limit", False)
        # Stop Limit emirde stop ile limit arasındaki mesafe (prim cinsinden)
        self._stop_limit_gap_prim: float = primnet_cfg.get("stop_limit_gap_prim", 0.3)

        sltp_mode = "NATIVE (MT5)" if self._native_sltp else "SOFTWARE (H-Oğul)"
        stop_limit_mode = "STOP LIMIT EMİR" if self._use_stop_limit else "TRADE_ACTION_SLTP"
        logger.info(
            f"H-Engine başlatıldı: max_concurrent={self._max_concurrent}, "
            f"daily_limit={self._config_daily_limit}, "
            f"SL/TP fallback={self._sl_atr_mult}×ATR/{self._tp_atr_mult}×ATR, "
            f"SL/TP modu={sltp_mode}, trailing modu={stop_limit_mode}, "
            f"PRİMNET (trailing={self._primnet_trailing}, "
            f"hedef=±{self._primnet_target})"
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
            result["reason"] = "İşlem saatleri dışında (09:40-17:50)"
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

        # v5.4.1: Atomik netting kilidi al (race condition önleme)
        from engine.netting_lock import acquire_symbol, release_symbol
        if not acquire_symbol(symbol, owner="h_engine"):
            result["reason"] = f"{symbol} başka motor tarafından kilitli (netting lock)"
            return result

        # 5. Sembol zaten hibrit yönetiminde mi?
        if symbol in self.get_hybrid_symbols():
            release_symbol(symbol, owner="h_engine")
            result["reason"] = f"{symbol} zaten hibrit yönetiminde (netting)"
            return result

        # 6. Ticket zaten hibrit yönetiminde mi? (bellek + DB)
        if ticket in self.hybrid_positions:
            release_symbol(symbol, owner="h_engine")
            result["reason"] = f"Ticket {ticket} zaten hibrit yönetiminde"
            return result
        # v14: DB'de eski ACTIVE kayıt varsa bellekle senkronize et
        try:
            db_active = self.db.get_active_hybrid_positions()
            db_ticket_exists = any(r.get("ticket") == ticket for r in db_active)
            if db_ticket_exists:
                logger.warning(
                    f"Ticket {ticket} DB'de ACTIVE ama bellekte yok — "
                    f"eski kayıt INSERT OR REPLACE ile güncellenecek"
                )
        except Exception:
            pass  # DB hatası devir engellemez

        # 7. Eşzamanlı limit
        active_count = len(self.hybrid_positions)
        if active_count >= self._max_concurrent:
            release_symbol(symbol, owner="h_engine")
            result["reason"] = (
                f"Eşzamanlı hibrit limit aşıldı ({active_count}/{self._max_concurrent})"
            )
            return result

        # 8. Günlük zarar limiti
        self._refresh_daily_pnl()
        if self._daily_hybrid_pnl <= -abs(self._config_daily_limit):
            release_symbol(symbol, owner="h_engine")
            result["reason"] = (
                f"Günlük hibrit zarar limiti aşıldı "
                f"({self._daily_hybrid_pnl:.2f} / -{self._config_daily_limit:.2f} TRY)"
            )
            return result

        # 9. ATR verisi
        atr_value = self._get_atr(symbol)
        if atr_value is None or atr_value <= 0:
            release_symbol(symbol, owner="h_engine")
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

        # 10. Güncel fiyat SL'yi zaten ihlal ediyor mu?
        suggested_sl = result["suggested_sl"]
        if direction == "BUY" and current_price <= suggested_sl:
            release_symbol(symbol, owner="h_engine")
            result["reason"] = (
                f"Güncel fiyat ({current_price:.4f}) zaten SL seviyesinin "
                f"({suggested_sl:.4f}) altında — devir güvenli değil"
            )
            return result
        if direction == "SELL" and current_price >= suggested_sl:
            result["reason"] = (
                f"Güncel fiyat ({current_price:.4f}) zaten SL seviyesinin "
                f"({suggested_sl:.4f}) üstünde — devir güvenli değil"
            )
            return result

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

        # ── PRİMNET: Prim bazlı SL/TP hesapla ──────────────────
        ref_price = self._get_reference_price(symbol) or 0.0
        if ref_price > 0:
            entry_prim = self._price_to_prim(entry_price, ref_price)
            if direction == "BUY":
                stop_prim = entry_prim - self._primnet_trailing
                target_prim = self._primnet_target
            else:
                stop_prim = entry_prim + self._primnet_trailing
                target_prim = -self._primnet_target
            suggested_sl = self._prim_to_price(stop_prim, ref_price)
            suggested_tp = self._prim_to_price(target_prim, ref_price)
            logger.info(
                f"PRİMNET devir: {symbol} {direction} giriş_prim={entry_prim:.2f} "
                f"stop_prim={stop_prim:.2f} hedef_prim={target_prim:.2f} "
                f"SL={suggested_sl:.4f} TP={suggested_tp:.4f} ref={ref_price:.4f}"
            )
        else:
            logger.warning(
                f"PRİMNET: Referans fiyat alınamadı [{symbol}] — ATR SL/TP kullanılıyor"
            )

        # ── 1. SL/TP ataması ────────────────────────────────────────
        trailing_order_ticket = 0
        target_order_ticket = 0

        if self._use_stop_limit and ref_price > 0:
            # ─ Bekleyen emirlerle SL/TP yönetimi ─
            # SL: plain STOP (tetiklenince market — dolum garantili)
            # TP: plain LIMIT (fiyat hedefe ulaşınca tetiklenir)

            # Trailing Stop emri (SL)
            if direction == "BUY":
                trail_dir = "SELL"
            else:
                trail_dir = "BUY"

            trail_result = self.mt5.send_stop(
                symbol, trail_dir, volume,
                suggested_sl,
                comment=f"PRIMNET_TRAIL_{ticket}",
            )
            if trail_result is None:
                result["message"] = "Stop trailing emri gönderilemedi — devir iptal"
                logger.error(
                    f"Hibrit devir başarısız — trailing Stop hatası: "
                    f"ticket={ticket} {symbol}"
                )
                return result
            trailing_order_ticket = trail_result["order_ticket"]

            # Hedef Limit emri (TP — target_prim seviyesinde)
            if direction == "BUY":
                tgt_dir = "SELL"
            else:
                tgt_dir = "BUY"

            tgt_result = self.mt5.send_limit(
                symbol, tgt_dir, volume,
                suggested_tp,
                comment=f"PRIMNET_TGT_{ticket}",
            )
            if tgt_result is not None:
                target_order_ticket = tgt_result["order_ticket"]
                logger.info(
                    f"Hedef Limit yerleştirildi: order={target_order_ticket} "
                    f"{symbol} {tgt_dir} price={suggested_tp:.4f}"
                )
            else:
                # Hedef emri kritik değil — trailing yeterli, log yaz devam et
                logger.warning(
                    f"Hedef Limit gönderilemedi: {symbol} {tgt_dir} "
                    f"price={suggested_tp:.4f} — sadece trailing aktif"
                )

            logger.info(
                f"Bekleyen emir devir: ticket={ticket} {symbol} {direction} "
                f"trail_order={trailing_order_ticket} tgt_order={target_order_ticket}"
            )

        elif self._native_sltp:
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
            # Software mod: SL/TP bellekte tutulur, H-Oğul fiyat kontrolü ile kapatır.
            # Güvenlik ağı: MT5'e geniş bir native SL koy (gap koruması).
            # Normal yönetim yazılımsal, ama piyasa gap atarsa MT5 native SL devreye girer.
            safety_sl = suggested_sl  # PRİMNET stop = geniş yeterli
            try:
                self.mt5.modify_position(ticket, sl=safety_sl)
                logger.info(
                    f"Software SL/TP modu + güvenlik ağı SL: ticket={ticket} {symbol} "
                    f"native_SL={safety_sl:.4f} (gap koruması)"
                )
            except Exception as exc:
                logger.warning(
                    f"Güvenlik ağı SL atanamadı: ticket={ticket} {symbol} — {exc}"
                )
            logger.info(
                f"Software SL/TP modu: ticket={ticket} {symbol} "
                f"SL={suggested_sl:.4f} TP={suggested_tp:.4f} (software yönetim aktif)"
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
            reference_price=ref_price,
            trailing_order_ticket=trailing_order_ticket,
            target_order_ticket=target_order_ticket,
        )
        # PRİMNET: breakeven_hit baştan True — Faz 1 trailing hemen başlar
        hp.breakeven_hit = True
        self.hybrid_positions[ticket] = hp

        # ── 3b. ManuelMotor aktif işlemlerden çıkar ──────────────────
        if self.manuel_motor and hasattr(self.manuel_motor, 'active_trades'):
            removed = self.manuel_motor.active_trades.pop(symbol, None)
            if removed:
                logger.info(
                    f"ManuelMotor aktif işlemden çıkarıldı (hibrite devir): "
                    f"ticket={ticket} {symbol}"
                )

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

        # Stop Limit emirlerini iptal et
        self._cancel_stop_limit_orders(hp)

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

        # v5.4.1: Netting kilidi serbest bırak
        from engine.netting_lock import release_symbol
        release_symbol(symbol, owner="h_engine")

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

        # ── OLAY rejimi → tüm hibrit pozisyonları anında kapat ─────
        if (self.baba
                and hasattr(self.baba, "current_regime")
                and self.baba.current_regime.regime_type == RegimeType.OLAY):
            logger.warning(
                "OLAY rejimi algılandı — tüm hibrit pozisyonlar kapatılıyor"
            )
            self.force_close_all("OLAY_REGIME")
            return

        # ── 17:45 sonrası açık pozisyon bildirimi (günde 1 kez) ──
        now = datetime.now()
        today_str = now.date().isoformat()
        if (now.time() >= EOD_NOTIFY
                and self._eod_notified_date != today_str):
            self._eod_notified_date = today_str
            active = [
                hp for hp in self.hybrid_positions.values()
                if hp.state == "ACTIVE"
            ]
            if active:
                symbols = ", ".join(f"{hp.symbol} {hp.direction}" for hp in active)
                msg = (
                    f"{len(active)} hibrit pozisyon gün sonunda açık: {symbols}. "
                    f"Kapatmak veya yarına bırakmak senin kararın."
                )
                # DB'ye kaydet (restart sonrası kaybolmaz)
                self.db.insert_notification(
                    notif_type="hybrid_eod",
                    title="Hibrit Pozisyon Açık",
                    message=msg,
                    severity="warning",
                )
                # WS ile dashboard'a gönder
                from engine.event_bus import emit as _emit
                _emit("notification", {
                    "type": "hybrid_eod",
                    "title": "Hibrit Pozisyon Açık",
                    "message": msg,
                    "severity": "warning",
                    "timestamp": now.isoformat(timespec="seconds"),
                })
                logger.info(
                    f"EOD bildirim gönderildi: {len(active)} hibrit pozisyon açık"
                )

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
                # SE3 düzeltme: Tek snapshot'a güvenme — 2. doğrulama yap
                # MT5 bazen geçici snapshot tutarsızlığı yaşıyor
                miss_key = f"miss_{ticket}"
                miss_count = self._close_retry_counts.get(miss_key, 0) + 1
                self._close_retry_counts[miss_key] = miss_count

                if miss_count < 3:
                    # İlk 2 kayıpta bekle — geçici olabilir
                    logger.warning(
                        f"Hibrit pozisyon MT5'te bulunamadı: ticket={ticket} "
                        f"{hp.symbol} — doğrulama bekleniyor ({miss_count}/3)"
                    )
                    continue

                # 3. ardışık kayıp — gerçekten kapanmış, doğrulandı
                self._close_retry_counts.pop(miss_key, None)
                logger.info(
                    f"Hibrit pozisyon kapanışı doğrulandı (3/3 miss): "
                    f"ticket={ticket} {hp.symbol}"
                )
                self._handle_external_close(hp)
                continue
            else:
                # Pozisyon bulundu — miss sayacını sıfırla
                miss_key = f"miss_{ticket}"
                if miss_key in self._close_retry_counts:
                    logger.info(
                        f"Hibrit pozisyon tekrar bulundu: ticket={ticket} "
                        f"{hp.symbol} — geçici kayıp düzeldi"
                    )
                    self._close_retry_counts.pop(miss_key, None)

            current_price = mt5_pos.get("price_current", 0.0)
            profit = mt5_pos.get("profit", 0.0)
            swap = mt5_pos.get("swap", 0.0)

            # ── Netting hacim senkronizasyonu ─────────────────────
            mt5_volume = mt5_pos.get("volume", hp.volume)
            if mt5_volume != hp.volume:
                mt5_entry = mt5_pos.get("price_open", hp.entry_price)
                self._sync_netting_volume(hp, mt5_volume, mt5_entry)

            if current_price <= 0:
                continue

            # ── Software SL/TP kontrolü (native kapalıysa) ───────
            if not self._native_sltp:
                if self._check_software_sltp(hp, current_price, profit, swap):
                    continue  # Pozisyon kapatıldı, sonraki döngüye geç

            # ── PRİMNET hedef kontrolü (tavan/tabana 0.5 kala) ───
            if self._check_primnet_target(hp, current_price, profit, swap):
                continue  # Hedef kapanış, sonraki döngüye geç

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

        # Retry limiti kontrolü — sonsuz döngüyü önle
        retry_count = self._close_retry_counts.get(hp.ticket, 0)
        if retry_count >= self._MAX_CLOSE_RETRIES:
            if retry_count == self._MAX_CLOSE_RETRIES:
                logger.critical(
                    f"Software {reason} kapatma {self._MAX_CLOSE_RETRIES}x başarısız: "
                    f"ticket={hp.ticket} {hp.symbol} — MANUEL KAPATMA GEREKLİ! "
                    f"Daha fazla deneme yapılmayacak."
                )
                from engine.event_bus import emit as _emit
                _emit("close_failed", {
                    "ticket": hp.ticket,
                    "symbol": hp.symbol,
                    "reason": reason,
                    "message": f"Pozisyon {self._MAX_CLOSE_RETRIES}x kapatılamadı — manuel müdahale gerekli",
                })
                self._close_retry_counts[hp.ticket] = retry_count + 1
            return False

        logger.info(
            f"Software {reason}: ticket={hp.ticket} {hp.symbol} {hp.direction} "
            f"fiyat={current_price:.4f} seviye={triggered_level:.4f} — kapatılıyor"
            f" (deneme {retry_count + 1}/{self._MAX_CLOSE_RETRIES})"
        )

        # TRADE_ACTION_DEAL ile kapat — netting koruma: sadece engine lotu
        close_result = self.mt5.close_position(
            hp.ticket, expected_volume=hp.volume,
        )
        if close_result is None:
            self._close_retry_counts[hp.ticket] = retry_count + 1
            logger.error(
                f"Software {reason} kapatma başarısız: ticket={hp.ticket} {hp.symbol} "
                f"(deneme {retry_count + 1}/{self._MAX_CLOSE_RETRIES})"
            )
            return False

        # Başarılı kapatma — retry sayacını temizle
        self._close_retry_counts.pop(hp.ticket, None)

        total_pnl = profit + swap
        self._finalize_close(hp, reason, total_pnl, swap)

        logger.info(
            f"Software {reason} başarılı: ticket={hp.ticket} {hp.symbol} "
            f"PnL={total_pnl:.2f}"
        )
        return True

    # ═════════════════════════════════════════════════════════════════
    #  NETTING SYNC — MT5 hacim/giriş fiyatı değişikliğini otomatik benimse
    # ═════════════════════════════════════════════════════════════════

    def _sync_netting_volume(
        self, hp: HybridPosition, mt5_volume: float, mt5_entry: float,
    ) -> None:
        """VİOP netting'de dışarıdan yapılan lot ekleme/çıkarma değişikliğini
        otomatik olarak hibrit pozisyona senkronize eder.

        Lot ekleme (volume artış):
            - volume, entry_price güncellenir
            - SL/TP yeni entry'den ATR ile yeniden hesaplanır
            - breakeven_hit sıfırlanır (yeni giriş seviyesinden yeniden değerlendirilir)

        Lot çıkarma (volume azalış — kısmi kâr alma):
            - volume güncellenir
            - entry_price güncellenir (MT5'ten)
            - SL/TP mevcut kalır (koruma devam eder)
            - breakeven_hit mevcut kalır
        """
        old_volume = hp.volume
        old_entry = hp.entry_price
        old_sl = hp.current_sl
        old_tp = hp.current_tp
        old_be = hp.breakeven_hit

        hp.volume = mt5_volume
        hp.entry_price = mt5_entry

        # Lot ekleme — SL/TP yeni giriş fiyatından PRİMNET ile yeniden hesapla
        if mt5_volume > old_volume:
            ref_price = self._get_reference_price(hp.symbol)
            if ref_price and ref_price > 0:
                entry_prim = self._price_to_prim(mt5_entry, ref_price)
                if hp.direction == "BUY":
                    stop_prim = entry_prim - self._primnet_trailing
                    target_prim = self._primnet_target
                else:
                    stop_prim = entry_prim + self._primnet_trailing
                    target_prim = -self._primnet_target
                hp.current_sl = self._prim_to_price(stop_prim, ref_price)
                hp.current_tp = self._prim_to_price(target_prim, ref_price)
                hp.reference_price = ref_price
            else:
                # Referans fiyat alınamazsa ATR fallback (sadece giriş SL/TP)
                logger.warning(
                    f"Netting SYNC: PRİMNET referans fiyat alınamadı [{hp.symbol}] "
                    f"— ATR SL/TP fallback"
                )
                if hp.direction == "BUY":
                    hp.current_sl = mt5_entry - (self._sl_atr_mult * hp.entry_atr)
                    hp.current_tp = mt5_entry + (self._tp_atr_mult * hp.entry_atr)
                else:
                    hp.current_sl = mt5_entry + (self._sl_atr_mult * hp.entry_atr)
                    hp.current_tp = mt5_entry - (self._tp_atr_mult * hp.entry_atr)
            hp.breakeven_hit = True  # PRİMNET: trailing hemen aktif

            logger.info(
                f"Netting SYNC (lot ekleme): ticket={hp.ticket} {hp.symbol} "
                f"lot {old_volume}→{mt5_volume}, entry {old_entry:.4f}→{mt5_entry:.4f}, "
                f"SL {old_sl:.4f}→{hp.current_sl:.4f}, "
                f"TP {old_tp:.4f}→{hp.current_tp:.4f} "
                f"(PRİMNET yeniden hesaplandı)"
            )
        else:
            # Lot çıkarma — SL/TP koru, sadece hacim güncelle
            logger.info(
                f"Netting SYNC (lot çıkarma): ticket={hp.ticket} {hp.symbol} "
                f"lot {old_volume}→{mt5_volume}, entry {old_entry:.4f}→{mt5_entry:.4f} "
                f"(SL/TP korundu)"
            )

        # DB güncelle
        self.db.update_hybrid_position(hp.ticket, {
            "volume": hp.volume,
            "entry_price": hp.entry_price,
            "current_sl": hp.current_sl,
            "current_tp": hp.current_tp,
            "breakeven_hit": int(hp.breakeven_hit),
        })

        # Olay geçmişine kaydet
        event_type = "NETTING_SYNC_ADD" if mt5_volume > old_volume else "NETTING_SYNC_REDUCE"
        self.db.insert_hybrid_event(
            ticket=hp.ticket, symbol=hp.symbol, event=event_type,
            details={
                "old_volume": old_volume, "new_volume": mt5_volume,
                "old_entry": old_entry, "new_entry": mt5_entry,
                "old_sl": old_sl, "new_sl": hp.current_sl,
                "old_tp": old_tp, "new_tp": hp.current_tp,
                "breakeven_reset": old_be and not hp.breakeven_hit,
            },
        )

    # ═════════════════════════════════════════════════════════════════
    #  BREAKEVEN — PRİMNET: Faz 1 trailing hemen başlar
    # ═════════════════════════════════════════════════════════════════

    def _check_breakeven(
        self, hp: HybridPosition, current_price: float,
        profit: float, swap: float,
    ) -> None:
        """PRİMNET breakeven — Faz 1 trailing hemen başlar, ayrı breakeven yok.

        PRİMNET'te breakeven ayrı bir adım değildir. Devir anında SL zaten
        prim bazlı hesaplanmıştır (faz1_stop). Bu fonksiyon sadece
        breakeven_hit bayrağını True yaparak trailing'in çalışmasını sağlar.

        Args:
            hp: Hibrit pozisyon.
            current_price: Güncel fiyat.
            profit: MT5 profit (swap hariç).
            swap: Birikmiş swap.
        """
        if hp.breakeven_hit:
            return

        hp.breakeven_hit = True  # trailing'in çalışması için

    # ═════════════════════════════════════════════════════════════════
    #  TRAILING STOP — PRİMNET Ana kontrol
    # ═════════════════════════════════════════════════════════════════

    def _check_trailing(
        self, hp: HybridPosition, current_price: float,
        profit: float, swap: float,
    ) -> None:
        """PRİMNET trailing stop kontrolü — breakeven sonrası devreye girer.

        Prim bazlı mesafe hesabı ile SL günceller.
        Kural: SL sadece daha iyi yöne taşınır (BUY: yukarı, SELL: aşağı)

        use_stop_limit=True ise:
            Stop Limit bekleyen emir ile trailing — modify_position yerine
            Buy Stop Limit (SELL pozisyon) / Sell Stop Limit (BUY pozisyon)

        use_stop_limit=False ise:
            Eski davranış: TRADE_ACTION_SLTP ile pozisyon SL güncelleme

        Args:
            hp: Hibrit pozisyon.
            current_price: Güncel fiyat.
            profit: MT5 profit (swap hariç).
            swap: Birikmiş swap.
        """
        if not hp.breakeven_hit:
            return

        new_sl = self._calc_primnet_trailing_sl(hp, current_price)

        if new_sl is None:
            return

        # SL sadece daha iyi yöne taşınır
        if hp.direction == "BUY":
            if new_sl <= hp.current_sl:
                return
        else:
            if new_sl >= hp.current_sl:
                return

        # ── Stop Limit modu: bekleyen emir ile trailing ─────────────
        if self._use_stop_limit:
            self._trailing_via_stop_limit(hp, new_sl, current_price, profit, swap)
            return

        # ── Eski mod: TRADE_ACTION_SLTP ile SL güncelleme ───────────
        modify_result = self.mt5.modify_position(hp.ticket, sl=new_sl)
        if modify_result is None:
            retry_key = f"tr_modify_{hp.ticket}"
            fail_count = self._close_retry_counts.get(retry_key, 0) + 1
            self._close_retry_counts[retry_key] = fail_count
            if fail_count <= 3:
                logger.warning(
                    f"Trailing SL modify başarısız: ticket={hp.ticket} {hp.symbol} "
                    f"(deneme {fail_count}/3) — bellekte güncelleniyor"
                )
            if fail_count >= 3 and fail_count == 3:
                logger.critical(
                    f"Trailing SL 3x modify başarısız: ticket={hp.ticket} {hp.symbol} "
                    f"— sadece software SL ile devam ediliyor (gap riski!)"
                )
                self.db.insert_hybrid_event(
                    ticket=hp.ticket, symbol=hp.symbol, event="TRAILING_FALLBACK",
                    details={
                        "old_sl": hp.current_sl, "new_sl": new_sl,
                        "price": current_price,
                        "message": "Native modify 3x başarısız, software-only SL",
                    },
                )
            # Modify başarısız olsa bile bellekte güncelle (software SL devam eder)
        else:
            self._close_retry_counts.pop(f"tr_modify_{hp.ticket}", None)
            # MT5 doğrulama
            verified_sl = self._verify_mt5_sl(hp.ticket)
            if verified_sl is not None and abs(verified_sl - new_sl) > 0.01:
                logger.error(
                    f"Trailing SL DESYNC: ticket={hp.ticket} {hp.symbol} "
                    f"istenen={new_sl:.4f} MT5={verified_sl:.4f} — MT5 değeri kullanılıyor"
                )
                new_sl = verified_sl

        old_sl = hp.current_sl
        hp.current_sl = new_sl
        hp.trailing_active = True

        # DB güncelle
        self.db.update_hybrid_position(hp.ticket, {
            "current_sl": new_sl,
            "trailing_active": 1,
        })
        total_pnl = profit + swap
        self.db.insert_hybrid_event(
            ticket=hp.ticket, symbol=hp.symbol, event="TRAILING_UPDATE",
            details={
                "old_sl": old_sl, "new_sl": new_sl,
                "price": current_price, "entry_atr": hp.entry_atr,
                "mode": "native" if self._native_sltp else "software",
                "trailing_mode": "primnet",
                "pnl": round(total_pnl, 2),
            },
        )

        logger.info(
            f"Trailing SL: ticket={hp.ticket} {hp.symbol} "
            f"SL {old_sl:.4f} → {new_sl:.4f} (fiyat={current_price:.4f}, "
            f"kâr={total_pnl:.0f} TRY) [primnet]"
        )

    # ── TRAILING VIA STOP LIMIT ─────────────────────────────────────

    def _trailing_via_stop_limit(
        self, hp: HybridPosition, new_sl: float,
        current_price: float, profit: float, swap: float,
    ) -> None:
        """Plain STOP bekleyen emir ile trailing stop güncelleme.

        SELL pozisyon → BUY STOP (ask ≥ price → market buy → pozisyonu kapat)
        BUY pozisyon  → SELL STOP (bid ≤ price → market sell → pozisyonu kapat)

        Plain STOP emri tetiklendiğinde MARKET olarak çalışır — dolum garantili.
        Stop Limit'ten farklı olarak limit fiyatı yoktur.

        Args:
            hp: Hibrit pozisyon.
            new_sl: Hesaplanan yeni trailing SL fiyatı.
            current_price: Güncel fiyat.
            profit: MT5 profit.
            swap: Birikmiş swap.
        """
        # Stop fiyatı hesapla (limit yok — plain STOP)
        stop_price = new_sl
        if hp.direction == "BUY":
            # BUY pozisyon → SELL STOP (fiyat düşerse kapat)
            order_direction = "SELL"
        else:
            # SELL pozisyon → BUY STOP (fiyat yükselirse kapat)
            order_direction = "BUY"

        old_sl = hp.current_sl

        # Mevcut trailing emir var mı? → MODIFY, yoksa → yeni emir gönder
        if hp.trailing_order_ticket > 0:
            # Önce emrin hâlâ bekliyor olduğunu kontrol et
            pending = self.mt5.get_pending_orders(hp.symbol)
            order_exists = any(
                o.get("ticket") == hp.trailing_order_ticket for o in (pending or [])
            )

            if order_exists:
                # TRADE_ACTION_MODIFY — atomik güncelleme (tek fiyat)
                result = self.mt5.modify_pending_order(
                    hp.trailing_order_ticket, stop_price,
                )
                if result is not None:
                    self._close_retry_counts.pop(f"tr_sl_{hp.ticket}", None)
                    logger.info(
                        f"Trailing Stop güncellendi: ticket={hp.trailing_order_ticket} "
                        f"{hp.symbol} price={stop_price:.4f}"
                    )
                else:
                    retry_key = f"tr_sl_{hp.ticket}"
                    fail_count = self._close_retry_counts.get(retry_key, 0) + 1
                    self._close_retry_counts[retry_key] = fail_count
                    if fail_count <= 3:
                        logger.warning(
                            f"Trailing Stop modify başarısız: "
                            f"ticket={hp.trailing_order_ticket} {hp.symbol} "
                            f"(deneme {fail_count}/3)"
                        )
                    if fail_count == 3:
                        # Modify 3x başarısız — emri iptal edip yeniden gönder
                        logger.warning(
                            f"Trailing Stop 3x modify başarısız — "
                            f"iptal edip yeniden gönderiliyor: {hp.symbol}"
                        )
                        self.mt5.cancel_pending_order(hp.trailing_order_ticket)
                        hp.trailing_order_ticket = 0
                        self._close_retry_counts.pop(retry_key, None)
            else:
                # Emir tetiklenmiş veya iptal edilmiş — yenisini gönder
                logger.info(
                    f"Trailing Stop emri kayboldu: "
                    f"ticket={hp.trailing_order_ticket} {hp.symbol} — yenisi gönderiliyor"
                )
                hp.trailing_order_ticket = 0

        # Yeni emir gönder (ilk kez veya eski iptal edilmiş)
        if hp.trailing_order_ticket == 0:
            result = self.mt5.send_stop(
                hp.symbol, order_direction, hp.volume,
                stop_price,
                comment=f"PRIMNET_TRAIL_{hp.ticket}",
            )
            if result is not None:
                hp.trailing_order_ticket = result["order_ticket"]
                logger.info(
                    f"Trailing Stop yerleştirildi: "
                    f"order={hp.trailing_order_ticket} {hp.symbol} "
                    f"{order_direction} price={stop_price:.4f}"
                )
            else:
                logger.error(
                    f"Trailing Stop gönderilemedi: {hp.symbol} {order_direction} "
                    f"price={stop_price:.4f}"
                )
                return

        # Bellek + DB güncelle
        hp.current_sl = new_sl
        hp.trailing_active = True

        self.db.update_hybrid_position(hp.ticket, {
            "current_sl": new_sl,
            "trailing_active": 1,
        })
        total_pnl = profit + swap
        self.db.insert_hybrid_event(
            ticket=hp.ticket, symbol=hp.symbol, event="TRAILING_UPDATE",
            details={
                "old_sl": old_sl, "new_sl": new_sl,
                "stop_price": stop_price, "limit_price": limit_price,
                "trailing_order_ticket": hp.trailing_order_ticket,
                "price": current_price, "entry_atr": hp.entry_atr,
                "mode": "stop_limit",
                "trailing_mode": "primnet",
                "pnl": round(total_pnl, 2),
            },
        )

        logger.info(
            f"Trailing SL: ticket={hp.ticket} {hp.symbol} "
            f"SL {old_sl:.4f} → {new_sl:.4f} (fiyat={current_price:.4f}, "
            f"kâr={total_pnl:.0f} TRY) [stop_limit]"
        )

    # ═════════════════════════════════════════════════════════════════
    #  MT5 SL DOĞRULAMA — v5.4.1
    # ═════════════════════════════════════════════════════════════════

    def _verify_mt5_sl(self, ticket: int) -> float | None:
        """MT5'ten pozisyonun gerçek SL değerini oku ve doğrula.

        v5.4.1 ekleme: Modify sonrası bellek-MT5 tutarlılık kontrolü.

        Args:
            ticket: MT5 pozisyon ticket numarası.

        Returns:
            MT5'teki gerçek SL değeri, okunamazsa None.
        """
        try:
            positions = self.mt5.get_positions()
            if not positions:
                return None
            mt5_pos = next(
                (p for p in positions if p.get("ticket") == ticket), None,
            )
            if mt5_pos is None:
                return None
            return mt5_pos.get("sl", 0.0)
        except Exception as exc:
            logger.debug(f"MT5 SL doğrulama okunamadı: ticket={ticket}: {exc}")
            return None

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

            # Stop Limit emirlerini iptal et (pozisyon kapatılmadan ÖNCE)
            self._cancel_stop_limit_orders(hp)

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

            # MT5'te kapat — netting koruma: sadece engine lotu
            close_result = self.mt5.close_position(
                ticket, expected_volume=hp.volume,
            )
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
            # PRİMNET: trailing her zaman aktif — restart sonrası da
            hp.breakeven_hit = True
            self.hybrid_positions[hp.ticket] = hp

        count = len(self.hybrid_positions)
        if count > 0:
            logger.info(f"Hibrit pozisyonlar geri yüklendi: {count} adet")

            # Stop Limit mod: bekleyen emirleri eşleştir
            if self._use_stop_limit:
                self._restore_stop_limit_tickets()

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

    # ═════════════════════════════════════════════════════════════════
    #  PRİMNET — Prim Bazlı Net Emir Takip Sistemi
    # ═════════════════════════════════════════════════════════════════

    def _get_reference_price(self, symbol: str) -> float | None:
        """Sembolün günlük uzlaşma (referans) fiyatını hesapla.

        VİOP'ta: tavan = uzlaşma × 1.10, taban = uzlaşma × 0.90
        Dolayısıyla: uzlaşma = (tavan + taban) / 2

        Args:
            symbol: Kontrat sembolü.

        Returns:
            Uzlaşma fiyatı veya hesaplanamazsa None.
        """
        try:
            sym = self.mt5.get_symbol_info(symbol)
            if sym is None:
                return None
            tavan = getattr(sym, "session_price_limit_max", 0.0)
            taban = getattr(sym, "session_price_limit_min", 0.0)
            if tavan <= 0 or taban <= 0:
                return None

            ref = (tavan + taban) / 2.0

            # Doğrulama: tavan/taban farkı %20 olmalı (VİOP ±%10 limit)
            # Tolerans: %15-%25 arası kabul (bazı kontratlar farklı)
            spread_pct = (tavan - taban) / ref if ref > 0 else 0
            if spread_pct < 0.10 or spread_pct > 0.30:
                logger.warning(
                    f"PRİMNET referans fiyat şüpheli [{symbol}]: "
                    f"tavan={tavan:.4f} taban={taban:.4f} ref={ref:.4f} "
                    f"spread=%{spread_pct*100:.1f} (beklenen ~%20) — kullanılıyor ama dikkat"
                )

            return ref
        except Exception as exc:
            logger.error(f"PRİMNET referans fiyat hatası [{symbol}]: {exc}")
            return None

    def _price_to_prim(self, price: float, ref_price: float) -> float:
        """Fiyatı prim seviyesine çevir.

        Prim = (fiyat - referans) / (referans × 0.01)

        Args:
            price: Güncel veya giriş fiyatı.
            ref_price: Uzlaşma (referans) fiyatı.

        Returns:
            Prim seviyesi (ör: +5.3, -2.1).
        """
        one_prim = ref_price * 0.01
        if one_prim <= 0:
            return 0.0
        return (price - ref_price) / one_prim

    def _prim_to_price(self, prim: float, ref_price: float) -> float:
        """Prim seviyesini fiyata çevir.

        Fiyat = referans + prim × (referans × 0.01)

        Args:
            prim: Prim seviyesi (ör: +9.5, -1.5).
            ref_price: Uzlaşma (referans) fiyatı.

        Returns:
            Fiyat değeri.
        """
        return ref_price + prim * (ref_price * 0.01)

    def _calc_primnet_trailing_sl(
        self, hp: HybridPosition, current_price: float,
    ) -> float | None:
        """PRİMNET prim bazlı trailing SL hesapla.

        Trailing mesafe HER ZAMAN SABİT (1.5 prim).
        Stop sadece kâr yönünde hareket eder, asla geri gelmez.

        Args:
            hp: Hibrit pozisyon.
            current_price: Güncel fiyat.

        Returns:
            Yeni SL fiyatı, hesaplanamazsa None.
        """
        ref_price = self._get_reference_price(hp.symbol)
        if ref_price is None:
            logger.warning(
                f"PRİMNET: Referans fiyat alınamadı [{hp.symbol}] "
                f"— bu cycle atlanıyor, sonraki denemede tekrar denenecek"
            )
            return None

        # Referans fiyat başarıyla alındı — hp'yi güncelle (frontend + overnight için)
        if hp.reference_price != ref_price:
            old_ref = hp.reference_price
            hp.reference_price = ref_price
            if old_ref == 0.0:
                logger.info(
                    f"PRİMNET: Referans fiyat ilk kez alındı [{hp.symbol}] "
                    f"ref={ref_price:.4f}"
                )

        entry_prim = self._price_to_prim(hp.entry_price, ref_price)
        current_prim = self._price_to_prim(current_price, ref_price)

        # Kâr primi hesapla (yöne göre)
        if hp.direction == "BUY":
            profit_prim = current_prim - entry_prim
        else:
            profit_prim = entry_prim - current_prim

        # Trailing mesafe SABİT (faz ayrımı yok)
        trailing_dist = self._primnet_trailing

        # Stop prim hesapla
        if hp.direction == "BUY":
            stop_prim = current_prim - trailing_dist
        else:
            stop_prim = current_prim + trailing_dist

        new_sl = self._prim_to_price(stop_prim, ref_price)

        logger.debug(
            f"PRİMNET [{hp.symbol}] t={hp.ticket}: "
            f"giriş_prim={entry_prim:.2f} güncel_prim={current_prim:.2f} "
            f"kâr_prim={profit_prim:.2f} trailing={trailing_dist} "
            f"stop_prim={stop_prim:.2f} → SL={new_sl:.4f}"
        )

        return new_sl

    def _check_primnet_target(
        self, hp: HybridPosition, current_price: float,
        profit: float, swap: float,
    ) -> bool:
        """PRİMNET hedef kapanış kontrolü — tavan/tabana 0.5 prim kala kapat.

        BUY: güncel_prim ≥ +target_prim (varsayılan +9.5) → KAPAT
        SELL: güncel_prim ≤ -target_prim (varsayılan -9.5) → KAPAT

        Stop Limit modda: hedef emir MT5'te bekliyor. Emir tetiklenmiş olabilir
        (pozisyon kapanmış), ya da fiyat hedefe ulaşmış ama emir henüz tetiklenmemişse
        market ile kapatır.

        Args:
            hp: Hibrit pozisyon.
            current_price: Güncel fiyat.
            profit: MT5 profit.
            swap: Birikmiş swap.

        Returns:
            True ise pozisyon kapatıldı, False ise devam.
        """
        ref_price = self._get_reference_price(hp.symbol)
        if ref_price is None:
            return False

        current_prim = self._price_to_prim(current_price, ref_price)
        target = self._primnet_target

        hit = False
        if hp.direction == "BUY" and current_prim >= target:
            hit = True
        elif hp.direction == "SELL" and current_prim <= -target:
            hit = True

        if not hit:
            # Hedef vurulmadı — Stop Limit modda hedef emri hâlâ orada mı kontrol et
            if self._use_stop_limit and hp.target_order_ticket > 0:
                pending = self.mt5.get_pending_orders(hp.symbol)
                tgt_exists = any(
                    o.get("ticket") == hp.target_order_ticket
                    for o in (pending or [])
                )
                if not tgt_exists:
                    # Hedef emir kayboldu (iptal edilmiş veya kısmi tetik?)
                    # Pozisyon hâlâ MT5'te açıksa yeniden yerleştir
                    logger.warning(
                        f"PRİMNET hedef emri kayboldu: order={hp.target_order_ticket} "
                        f"{hp.symbol} — yeniden yerleştirilecek"
                    )
                    hp.target_order_ticket = 0
                    self._place_target_stop_limit(hp)
            return False

        # Retry limiti kontrolü
        retry_key = f"primnet_target_{hp.ticket}"
        retry_count = self._close_retry_counts.get(retry_key, 0)
        if retry_count >= self._MAX_CLOSE_RETRIES:
            return False

        logger.info(
            f"PRİMNET HEDEF: ticket={hp.ticket} {hp.symbol} {hp.direction} "
            f"prim={current_prim:.2f} hedef=±{target} — kapatılıyor"
        )

        # Stop Limit modda: hedef emir tetiklenmiş olabilir, pozisyon zaten kapanmış
        # olabilir — _manage_positions zaten external close algılar.
        # Ama fiyat hedefe ulaşmış ve emir tetiklenmemişse market ile kapat.
        close_result = self.mt5.close_position(
            hp.ticket, expected_volume=hp.volume,
        )
        if close_result is None:
            self._close_retry_counts[retry_key] = retry_count + 1
            logger.error(
                f"PRİMNET hedef kapanış başarısız: ticket={hp.ticket} {hp.symbol} "
                f"(deneme {retry_count + 1}/{self._MAX_CLOSE_RETRIES})"
            )
            return False

        self._close_retry_counts.pop(retry_key, None)
        total_pnl = profit + swap
        self._finalize_close(hp, "PRIMNET_TARGET", total_pnl, swap)

        logger.info(
            f"PRİMNET hedef kapanış başarılı: ticket={hp.ticket} {hp.symbol} "
            f"prim={current_prim:.2f} PnL={total_pnl:.2f}"
        )
        return True

    def _place_target_stop_limit(self, hp: HybridPosition) -> None:
        """Hedef Limit emrini (yeniden) yerleştir.

        Plain LIMIT kullanır — fiyat hedefe ulaştığında tetiklenir.
        BUY pozisyon → SELL LIMIT (bid ≥ price → pozisyonu kapat)
        SELL pozisyon → BUY LIMIT (ask ≤ price → pozisyonu kapat)

        Args:
            hp: Hibrit pozisyon.
        """
        ref_price = hp.reference_price or self._get_reference_price(hp.symbol)
        if not ref_price or ref_price <= 0:
            return

        target = self._primnet_target

        if hp.direction == "BUY":
            target_prim = target
            tgt_dir = "SELL"
            tgt_price = self._prim_to_price(target_prim, ref_price)
        else:
            target_prim = -target
            tgt_dir = "BUY"
            tgt_price = self._prim_to_price(target_prim, ref_price)

        result = self.mt5.send_limit(
            hp.symbol, tgt_dir, hp.volume,
            tgt_price,
            comment=f"PRIMNET_TGT_{hp.ticket}",
        )
        if result is not None:
            hp.target_order_ticket = result["order_ticket"]
            logger.info(
                f"Hedef Limit yerleştirildi: "
                f"order={hp.target_order_ticket} {hp.symbol} {tgt_dir} "
                f"price={tgt_price:.4f}"
            )
        else:
            logger.error(
                f"Hedef Limit gönderilemedi: {hp.symbol} {tgt_dir} "
                f"price={tgt_price:.4f}"
            )

    def _is_trading_hours(self, now: datetime | None = None) -> bool:
        """İşlem saatleri içinde olup olmadığını kontrol et (09:40-17:50).

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
        """Günlük PnL'yi kontrol et; gün değişmişse sıfırla, DB'den yeniden oku.

        PRİMNET yenilemesi piyasa açılışında (09:40+) çalışır, gece yarısında değil.
        MT5'in yeni uzlaşma fiyatlarını yüklemesi için piyasa açık olmalı.
        """
        today = date.today().isoformat()
        if self._daily_pnl_date != today:
            self._daily_pnl_date = today
            self._daily_hybrid_pnl = 0.0
            logger.info("Hibrit günlük PnL sıfırlandı (yeni gün)")

        # PRİMNET yenileme — piyasa açılışında (uzlaşma fiyatları hazır)
        now = datetime.now()
        if (self._daily_reset_done != today
                and self.hybrid_positions
                and self._is_trading_hours(now)):
            self._daily_reset_done = today
            yesterday = self._daily_pnl_date if self._daily_pnl_date != today else "?"
            self._primnet_daily_reset(yesterday)

        # DB'den güncel toplam
        try:
            self._daily_hybrid_pnl = self.db.get_hybrid_daily_pnl(today)
        except Exception:
            pass  # Hata durumunda mevcut değeri koru

    def _primnet_daily_reset(self, previous_date: str) -> None:
        """Yeni gün başında overnight pozisyonların PRİMNET SL/TP'sini yenile.

        MT5'in günlük uzlaşma yenilemesi gibi: yeni referans fiyat al,
        prim hesabını sıfırdan yap, SL/TP'yi yeni güne göre ayarla.

        Args:
            previous_date: Önceki gün tarihi (log için).
        """
        logger.info(
            f"PRİMNET günlük yenileme başlatıldı: "
            f"{len(self.hybrid_positions)} overnight pozisyon ({previous_date} → bugün)"
        )

        for ticket in list(self.hybrid_positions.keys()):
            hp = self.hybrid_positions.get(ticket)
            if hp is None or hp.state != "ACTIVE":
                continue

            old_ref = hp.reference_price
            old_sl = hp.current_sl
            old_tp = hp.current_tp

            # Yeni referans fiyat al
            new_ref = self._get_reference_price(hp.symbol)
            if new_ref is None or new_ref <= 0:
                logger.warning(
                    f"PRİMNET yenileme: {hp.symbol} t={ticket} "
                    f"referans fiyat alınamadı — eski SL/TP korunuyor, "
                    f"sonraki cycle'da tekrar denenecek"
                )
                continue

            # Yeni primler hesapla
            entry_prim = self._price_to_prim(hp.entry_price, new_ref)

            # Trailing mesafe SABİT (faz ayrımı yok)
            trailing_dist = self._primnet_trailing

            # Yeni SL hesapla
            if hp.direction == "BUY":
                stop_prim = entry_prim - trailing_dist
                target_prim = self._primnet_target
            else:
                stop_prim = entry_prim + trailing_dist
                target_prim = -self._primnet_target

            new_sl = self._prim_to_price(stop_prim, new_ref)
            new_tp = self._prim_to_price(target_prim, new_ref)

            # SL monotonluk: yeni SL eski SL'den kötüyse eski SL'yi koru
            sl_worse = False
            if hp.direction == "BUY" and new_sl < old_sl:
                sl_worse = True
            elif hp.direction == "SELL" and new_sl > old_sl:
                sl_worse = True

            if sl_worse:
                new_sl = old_sl
                logger.info(
                    f"PRİMNET yenileme [{hp.symbol}] t={ticket}: "
                    f"yeni SL ({new_sl:.4f}) eskiden kötü — eski SL korundu"
                )

            # Güncelle
            hp.reference_price = new_ref
            hp.current_sl = new_sl
            hp.current_tp = new_tp
            hp.breakeven_hit = True  # PRİMNET: trailing her zaman aktif

            # MT5'e yaz
            if self._use_stop_limit and new_ref > 0:
                # Eski emirleri iptal et, yenilerini koy
                self._cancel_stop_limit_orders(hp)

                # Trailing Stop emri (SL)
                if hp.direction == "BUY":
                    trail_dir = "SELL"
                else:
                    trail_dir = "BUY"

                trail_res = self.mt5.send_stop(
                    hp.symbol, trail_dir, hp.volume,
                    new_sl,
                    comment=f"PRIMNET_TRAIL_{ticket}",
                )
                if trail_res is not None:
                    hp.trailing_order_ticket = trail_res["order_ticket"]
                else:
                    logger.error(
                        f"PRİMNET yenileme trailing Stop başarısız: "
                        f"ticket={ticket} {hp.symbol}"
                    )

                # Hedef Stop Limit
                self._place_target_stop_limit(hp)

            elif self._native_sltp:
                modify_result = self.mt5.modify_position(ticket, sl=new_sl, tp=new_tp)
                if modify_result is None:
                    logger.error(
                        f"PRİMNET yenileme MT5 modify başarısız: "
                        f"ticket={ticket} {hp.symbol} — software SL aktif"
                    )

            # DB güncelle
            self.db.update_hybrid_position(ticket, {
                "current_sl": new_sl,
                "current_tp": new_tp,
                "breakeven_hit": 1,
            })

            # Olay kaydı
            self.db.insert_hybrid_event(
                ticket=ticket, symbol=hp.symbol, event="PRIMNET_DAILY_RESET",
                details={
                    "old_ref": old_ref, "new_ref": new_ref,
                    "old_sl": old_sl, "new_sl": new_sl,
                    "old_tp": old_tp, "new_tp": new_tp,
                    "entry_prim": round(entry_prim, 2),
                    "trailing_dist": trailing_dist,
                    "previous_date": previous_date,
                },
            )

            # DB + event bus — dashboard bildirimi
            reset_msg = (
                f"{hp.symbol} {hp.direction} overnight — "
                f"ref {old_ref:.2f}→{new_ref:.2f}, "
                f"SL {old_sl:.4f}→{new_sl:.4f}"
            )
            self.db.insert_notification(
                notif_type="hybrid_daily_reset",
                title="PRİMNET Günlük Yenileme",
                message=reset_msg,
                severity="info",
            )
            from engine.event_bus import emit as _emit
            _emit("notification", {
                "type": "hybrid_daily_reset",
                "title": "PRİMNET Günlük Yenileme",
                "message": reset_msg,
                "severity": "info",
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            })

            logger.info(
                f"PRİMNET yenileme: ticket={ticket} {hp.symbol} {hp.direction} "
                f"ref={old_ref:.4f}→{new_ref:.4f} "
                f"SL={old_sl:.4f}→{new_sl:.4f} "
                f"TP={old_tp:.4f}→{new_tp:.4f} "
                f"giriş_prim={entry_prim:.2f} trailing={trailing_dist}"
            )

        logger.info("PRİMNET günlük yenileme tamamlandı")

    def _cancel_stop_limit_orders(self, hp: HybridPosition) -> None:
        """Pozisyona ait bekleyen emirleri (STOP/LIMIT) iptal et.

        Trailing ve hedef emirleri kontrol eder, hâlâ bekleyenleri iptal eder.
        Ticket'ları sıfırlar.

        Args:
            hp: Hibrit pozisyon.
        """
        if not self._use_stop_limit:
            return

        for attr_name, label in [
            ("trailing_order_ticket", "trailing"),
            ("target_order_ticket", "hedef"),
        ]:
            order_ticket = getattr(hp, attr_name, 0)
            if order_ticket > 0:
                result = self.mt5.cancel_pending_order(order_ticket)
                if result is not None:
                    logger.info(
                        f"Bekleyen {label} emri iptal edildi: "
                        f"order={order_ticket} {hp.symbol}"
                    )
                else:
                    logger.warning(
                        f"Bekleyen {label} emri iptal edilemedi: "
                        f"order={order_ticket} {hp.symbol}"
                    )
                setattr(hp, attr_name, 0)

    def _restore_stop_limit_tickets(self) -> None:
        """Restart sonrası bekleyen Stop Limit emirlerini hibrit pozisyonlarla eşleştir.

        MT5'teki bekleyen emirlerin comment alanından PRIMNET_TRAIL_<ticket> ve
        PRIMNET_TGT_<ticket> bilgisi çıkarılır, ilgili pozisyonla eşlenir.
        Eşleşmeyen emirler loglanır.
        """
        for hp in self.hybrid_positions.values():
            if hp.state != "ACTIVE":
                continue
            pending = self.mt5.get_pending_orders(hp.symbol)
            if not pending:
                continue

            for order in pending:
                comment = order.get("comment", "")
                order_ticket = order.get("ticket", 0)
                if not order_ticket:
                    continue

                if comment == f"PRIMNET_TRAIL_{hp.ticket}":
                    hp.trailing_order_ticket = order_ticket
                    logger.info(
                        f"Trailing Stop Limit eşleştirildi: order={order_ticket} "
                        f"← pozisyon={hp.ticket} {hp.symbol}"
                    )
                elif comment == f"PRIMNET_TGT_{hp.ticket}":
                    hp.target_order_ticket = order_ticket
                    logger.info(
                        f"Hedef Stop Limit eşleştirildi: order={order_ticket} "
                        f"← pozisyon={hp.ticket} {hp.symbol}"
                    )

            # Emir bulunamadıysa: yeniden yerleştir
            if hp.trailing_order_ticket == 0:
                logger.warning(
                    f"Trailing Stop Limit bulunamadı: pozisyon={hp.ticket} "
                    f"{hp.symbol} — sonraki cycle'da yeniden yerleştirilecek"
                )
            if hp.target_order_ticket == 0:
                logger.warning(
                    f"Hedef Stop Limit bulunamadı: pozisyon={hp.ticket} "
                    f"{hp.symbol} — sonraki cycle'da yeniden yerleştirilecek"
                )

    def _handle_external_close(self, hp: HybridPosition) -> None:
        """MT5'te kapatılmış (harici kapanış) hibrit pozisyonu işle.

        SL/TP hit veya kullanıcı MT5'ten kapatmış olabilir.
        Stop Limit emir tetiklenmiş de olabilir.
        Gerçek PnL'i MT5 deal geçmişinden almaya çalışır.

        Args:
            hp: Kapatılan hibrit pozisyon.
        """
        # Stop Limit emirlerini temizle (tetiklenmemiş kalanları iptal et)
        self._cancel_stop_limit_orders(hp)

        # Gerçek PnL bilgisi: Deal geçmişinden almayı dene
        pnl = 0.0
        swap = 0.0
        try:
            deal_pnl = self.mt5.get_deal_summary(hp.ticket)
            if deal_pnl is not None:
                pnl = deal_pnl.get("pnl", 0.0)
                swap = deal_pnl.get("swap", 0.0)
                logger.info(
                    f"Hibrit harici kapanış deal PnL: ticket={hp.ticket} "
                    f"pnl={pnl:.2f} swap={swap:.2f}"
                )
        except Exception as exc:
            logger.debug(f"Deal PnL alınamadı: {exc}")

        self._finalize_close(hp, "EXTERNAL", pnl, swap)
        logger.info(
            f"Hibrit pozisyon harici kapanış: ticket={hp.ticket} {hp.symbol} "
            f"pnl={pnl:.2f}"
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
        # Stop Limit bekleyen emirleri temizle
        self._cancel_stop_limit_orders(hp)

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

        # v5.4.1: Netting kilidi serbest bırak
        from engine.netting_lock import release_symbol
        release_symbol(hp.symbol, owner="h_engine")

        logger.info(
            f"Hibrit pozisyon kapatıldı: ticket={hp.ticket} {hp.symbol} "
            f"neden={reason} pnl={pnl:.2f}"
        )

        # ── Event bus — trade_closed bildirimi ────────────────────
        from engine.event_bus import emit as _emit_event
        _emit_event("trade_closed", {
            "ticket": hp.ticket, "symbol": hp.symbol,
            "direction": hp.direction, "pnl": pnl,
            "exit_reason": reason, "source": "hybrid",
        })
