"""H-Engine — Hibrit İşlem Motoru (v1.0).

İnsan işlemi açar, robot yönetir ve kapatır.

Bileşenler:
    H-Baba  → Devir ön kontrolü (risk/yetkilendirme)
    H-Oğul  → Pozisyon yönetimi (breakeven, trailing stop)

Yönetim kuralları:
    1. Giriş SL  = entry_price ± (entry_atr × sl_atr_mult)
    2. Giriş TP  = entry_price ± (entry_atr × tp_atr_mult)
    3. Breakeven = Kâr ≥ breakeven_atr_mult × entry_atr → SL = entry_price
    4a. Trailing (ATR mod)    = Kâr ≥ trigger × ATR → SL = price ∓ distance × ATR
    4b. Trailing (profit mod) = Kâr > gap TRY → SL = entry ∓ (kâr-gap)/çarpan
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

from dataclasses import dataclass
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
TRADING_OPEN: dtime = dtime(9, 40)
TRADING_CLOSE: dtime = dtime(17, 50)


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
        self._trailing_mode: str = hybrid_cfg.get("trailing_mode", "atr")  # "atr" | "profit"
        self._trailing_profit_gap: float = hybrid_cfg.get("trailing_profit_gap", 100.0)  # TRY
        self._native_sltp: bool = hybrid_cfg.get("native_sltp", False)

        sltp_mode = "NATIVE (MT5)" if self._native_sltp else "SOFTWARE (H-Oğul)"
        trailing_desc = (
            f"PROFIT (gap={self._trailing_profit_gap} TRY)"
            if self._trailing_mode == "profit"
            else f"ATR (trigger={self._trailing_trigger_mult}×, dist={self._trailing_distance_mult}×)"
        )
        logger.info(
            f"H-Engine başlatıldı: max_concurrent={self._max_concurrent}, "
            f"daily_limit={self._config_daily_limit}, "
            f"SL={self._sl_atr_mult}×ATR, TP={self._tp_atr_mult}×ATR, "
            f"SL/TP modu={sltp_mode}, trailing={trailing_desc}"
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

            # ── Netting hacim kontrolü ──────────────────────────────
            mt5_volume = mt5_pos.get("volume", hp.volume)
            if mt5_volume != hp.volume:
                vol_key = f"vol_warn_{ticket}"
                if vol_key not in self._close_retry_counts:
                    logger.warning(
                        f"Netting hacim uyuşmazlığı: ticket={ticket} "
                        f"{hp.symbol} — engine={hp.volume} lot, "
                        f"MT5={mt5_volume} lot (dışarıdan lot eklenmiş olabilir)"
                    )
                    self._close_retry_counts[vol_key] = 1

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
                # v5.4.1: Modify başarısız — retry sayacı + alarm
                retry_key = f"be_modify_{hp.ticket}"
                fail_count = self._close_retry_counts.get(retry_key, 0) + 1
                self._close_retry_counts[retry_key] = fail_count
                logger.warning(
                    f"Breakeven SL modify başarısız: ticket={hp.ticket} {hp.symbol} "
                    f"(deneme {fail_count}/3)"
                )
                if fail_count >= 3:
                    logger.critical(
                        f"Breakeven SL 3x modify başarısız: ticket={hp.ticket} {hp.symbol} "
                        f"— software SL moduna geçiliyor"
                    )
                    # Native başarısız, software SL ile korumaya devam et
                    self._close_retry_counts.pop(retry_key, None)
                    # Belleği güncelle ama DB'ye native=False olarak kaydet
                    old_sl = hp.current_sl
                    hp.current_sl = new_sl
                    hp.breakeven_hit = True
                    self.db.update_hybrid_position(hp.ticket, {
                        "current_sl": new_sl, "breakeven_hit": 1,
                    })
                    self.db.insert_hybrid_event(
                        ticket=hp.ticket, symbol=hp.symbol, event="BREAKEVEN_FALLBACK",
                        details={
                            "old_sl": old_sl, "new_sl": new_sl,
                            "price": current_price,
                            "message": "Native modify 3x başarısız, software SL aktif",
                        },
                    )
                    logger.warning(
                        f"Breakeven SL (software fallback): ticket={hp.ticket} {hp.symbol} "
                        f"SL {old_sl:.4f} → {new_sl:.4f}"
                    )
                return
            else:
                # v5.4.1: Modify başarılı — MT5 doğrulama
                self._close_retry_counts.pop(f"be_modify_{hp.ticket}", None)
                verified_sl = self._verify_mt5_sl(hp.ticket)
                if verified_sl is not None and abs(verified_sl - new_sl) > 0.01:
                    logger.error(
                        f"Breakeven SL DESYNC: ticket={hp.ticket} {hp.symbol} "
                        f"istenen={new_sl:.4f} MT5={verified_sl:.4f} — MT5 değeri kullanılıyor"
                    )
                    new_sl = verified_sl

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
    #  TRAILING SL HESAPLAMA — ATR ve Profit modları
    # ═════════════════════════════════════════════════════════════════

    def _calc_atr_trailing_sl(
        self, hp: HybridPosition, current_price: float,
    ) -> float | None:
        """ATR bazlı trailing SL hesapla (klasik mod).

        Koşul: kâr ≥ trailing_trigger × entry_atr
        Hesap: SL = current_price ∓ distance × entry_atr

        Returns:
            Yeni SL değeri, koşul sağlanmıyorsa None.
        """
        price_diff = self._price_profit(hp, current_price)
        trailing_threshold = self._trailing_trigger_mult * hp.entry_atr

        if price_diff < trailing_threshold:
            return None

        distance = self._trailing_distance_mult * hp.entry_atr
        if hp.direction == "BUY":
            return current_price - distance
        return current_price + distance

    def _calc_profit_trailing_sl(
        self, hp: HybridPosition, current_price: float,
        profit: float, swap: float,
    ) -> float | None:
        """Kâr bazlı trailing SL hesapla (v5.7.1 — CEO onaylı).

        Mantık: (mevcut_kâr - nefes_payı) TRY'yi fiyat mesafesine çevirip
        giriş fiyatından o kadar uzağa SL koyar.

        Örnek (SELL, gap=100 TRY):
            Kâr=300 TRY → kilitle=200 TRY → SL = entry - 200/çarpan
            Kâr=500 TRY → kilitle=400 TRY → SL = entry - 400/çarpan

        Returns:
            Yeni SL değeri, koşul sağlanmıyorsa None.
        """
        total_pnl = profit + swap
        gap = self._trailing_profit_gap

        # Kâr nefes payını aşmadıysa trailing başlamaz
        if total_pnl <= gap:
            return None

        lock_trl = total_pnl - gap  # kilitlenecek TRY

        # TRY → fiyat mesafesi dönüşümü (symbol_info'dan kontrat çarpanı)
        sym = self.mt5.get_symbol_info(hp.symbol)
        if sym is None or sym.trade_contract_size <= 0:
            logger.warning(
                f"Profit trailing: symbol_info alınamadı [{hp.symbol}] "
                f"— ATR moduna fallback"
            )
            return self._calc_atr_trailing_sl(hp, current_price)

        # profit = price_diff × volume × contract_size (VİOP basit formül)
        trl_per_point = hp.volume * sym.trade_contract_size
        if trl_per_point <= 0:
            return None

        lock_points = lock_trl / trl_per_point

        # SL = giriş fiyatından lock_points kadar kâr yönünde
        if hp.direction == "BUY":
            new_sl = hp.entry_price + lock_points
        else:
            new_sl = hp.entry_price - lock_points

        return new_sl

    # ═════════════════════════════════════════════════════════════════
    #  TRAILING STOP — Ana kontrol
    # ═════════════════════════════════════════════════════════════════

    def _check_trailing(
        self, hp: HybridPosition, current_price: float,
        profit: float, swap: float,
    ) -> None:
        """Trailing stop kontrolü — breakeven sonrası devreye girer.

        İki mod destekler (config trailing_mode):
            "atr"    → Klasik ATR mesafe bazlı trailing (eski davranış)
            "profit" → Kâr bazlı trailing: (kâr - gap) TRY'yi fiyata çevirip
                        SL olarak kilitler. Daha sezgisel, para odaklı.

        Kural: SL sadece daha iyi yöne taşınır (BUY: yukarı, SELL: aşağı)

        Args:
            hp: Hibrit pozisyon.
            current_price: Güncel fiyat.
            profit: MT5 profit (swap hariç).
            swap: Birikmiş swap.
        """
        if not hp.breakeven_hit:
            return

        if self._trailing_mode == "profit":
            new_sl = self._calc_profit_trailing_sl(hp, current_price, profit, swap)
        else:
            new_sl = self._calc_atr_trailing_sl(hp, current_price)

        if new_sl is None:
            return

        # SL sadece daha iyi yöne taşınır
        if hp.direction == "BUY":
            if new_sl <= hp.current_sl:
                return
        else:
            if new_sl >= hp.current_sl:
                return

        # MT5'e yaz (native mod) veya sadece internal güncelle (software mod)
        if self._native_sltp:
            modify_result = self.mt5.modify_position(hp.ticket, sl=new_sl)
            if modify_result is None:
                # v5.4.1: Modify başarısız — retry sayacı + alarm
                retry_key = f"tr_modify_{hp.ticket}"
                fail_count = self._close_retry_counts.get(retry_key, 0) + 1
                self._close_retry_counts[retry_key] = fail_count
                logger.warning(
                    f"Trailing SL modify başarısız: ticket={hp.ticket} {hp.symbol} "
                    f"(deneme {fail_count}/3)"
                )
                if fail_count >= 3:
                    logger.critical(
                        f"Trailing SL 3x modify başarısız: ticket={hp.ticket} {hp.symbol} "
                        f"— software SL moduna geçiliyor"
                    )
                    self._close_retry_counts.pop(retry_key, None)
                    old_sl = hp.current_sl
                    hp.current_sl = new_sl
                    hp.trailing_active = True
                    self.db.update_hybrid_position(hp.ticket, {
                        "current_sl": new_sl, "trailing_active": 1,
                    })
                    self.db.insert_hybrid_event(
                        ticket=hp.ticket, symbol=hp.symbol, event="TRAILING_FALLBACK",
                        details={
                            "old_sl": old_sl, "new_sl": new_sl,
                            "price": current_price,
                            "message": "Native modify 3x başarısız, software SL aktif",
                        },
                    )
                    logger.warning(
                        f"Trailing SL (software fallback): ticket={hp.ticket} {hp.symbol} "
                        f"SL {old_sl:.4f} → {new_sl:.4f}"
                    )
                return
            else:
                # v5.4.1: Modify başarılı — MT5 doğrulama
                self._close_retry_counts.pop(f"tr_modify_{hp.ticket}", None)
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
                "trailing_mode": self._trailing_mode,
                "pnl": round(total_pnl, 2),
            },
        )

        logger.info(
            f"Trailing SL: ticket={hp.ticket} {hp.symbol} "
            f"SL {old_sl:.4f} → {new_sl:.4f} (fiyat={current_price:.4f}, "
            f"kâr={total_pnl:.0f} TRY) [{self._trailing_mode}]"
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
        Gerçek PnL'i MT5 deal geçmişinden almaya çalışır.

        Args:
            hp: Kapatılan hibrit pozisyon.
        """
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
