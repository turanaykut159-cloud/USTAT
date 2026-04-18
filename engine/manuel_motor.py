"""ManuelMotor — Bağımsız Manuel İşlem Motoru (v14.0).

Kullanıcı açar, kullanıcı kontrol eder.  Sistem sadece risk göstergesi sağlar.

Kurallar
--------
- Trailing stop YOK
- TP1 yarı kapanış YOK
- Breakeven çekme YOK
- Rejim bazlı zorunlu kapanış YOK (VOLATILE/OLAY → sadece KIRMIZI gösterge)
- Sinyal devam kontrolü YOK
- Kullanıcının SL/TP'si aynen korunur

Risk göstergesi (read-only, müdahale yok)
-----------------------------------------
sl_risk     : SL mesafesi / ATR → yeşil / sarı / kırmızı
regime_risk : rejim → yeşil / sarı / kırmızı
pnl_risk    : floating K/Z → yeşil / sarı / kırmızı
system_risk : kill-switch seviyesi → yeşil / sarı / kırmızı
overall     : en kötü renk
score       : 0-100 (0 = maks risk, 100 = güvenli)

BABA L3 mekanizması
-------------------
L3 ``_close_all_positions()`` tüm MT5 pozisyonlarını direkt kapatır.
ManuelMotor kapanmayı ``sync_positions()`` ile tespit eder.
"""

from __future__ import annotations

import json
import time as _time
from datetime import datetime, time
from pathlib import Path
from typing import Any, TYPE_CHECKING

import numpy as np

from engine.logger import get_logger
from engine.models.trade import Trade, TradeState
from engine.utils.helpers import last_valid
from engine.utils.indicators import atr as calc_atr

if TYPE_CHECKING:
    from engine.baba import Baba
    from engine.config import Config
    from engine.database import Database
    from engine.models.regime import RegimeType
    from engine.models.risk import RiskParams
    from engine.mt5_bridge import MT5Bridge

logger = get_logger(__name__)


# ═════════════════════════════════════════════════════════════════════
#  SABİTLER
# ═════════════════════════════════════════════════════════════════════

ATR_PERIOD: int = 14
MIN_BARS_M15: int = 60
CONTRACT_SIZE: float = 100.0
MAX_LOT_PER_CONTRACT: float = 1.0
# v5.8/CEO-FAZ2: Varsayılan — config'den override edilir (ManuelMotor.__init__)
MARGIN_RESERVE_PCT_DEFAULT: float = 0.20
MAX_CONCURRENT_MANUAL: int = 3
TRADING_OPEN: time = time(9, 40)
TRADING_CLOSE: time = time(17, 50)
SENT_EXPIRE_SEC: float = 30.0    # SENT → MT5'te yoksa 30 sn sonra temizle

# ── Risk Skor Eşikleri ──────────────────────────────────────────────
SL_ATR_GREEN: float = 1.5      # SL mesafesi / ATR > 1.5 → yeşil
SL_ATR_YELLOW: float = 0.8     # 0.8–1.5 → sarı, < 0.8 → kırmızı
PNL_YELLOW_PCT: float = -0.005  # -%0.5 equity → kırmızı eşiği

_COLOR_RANK = {"green": 0, "yellow": 1, "red": 2}
_RANK_COLOR = {0: "green", 1: "yellow", 2: "red"}
_COLOR_POINTS = {"green": 25, "yellow": 15, "red": 0}


class ManuelMotor:
    """Bağımsız Manuel İşlem Motoru."""

    # ─────────────────────────────────────────────────────────────────
    #  BAŞLATMA
    # ─────────────────────────────────────────────────────────────────

    def __init__(
        self,
        config: Config,
        mt5: MT5Bridge,
        db: Database,
        baba: Baba | None = None,
        risk_params: RiskParams | None = None,
    ) -> None:
        self.config = config
        self.mt5 = mt5
        self.db = db
        self.baba = baba
        from engine.models.risk import RiskParams as _RP
        self.risk_params = risk_params or _RP()

        # Kendi aktif işlem sözlüğü (OĞUL'dan AYRI)
        self.active_trades: dict[str, Trade] = {}

        # v5.8.1: DB-bağımsız dosya marker (WAL kaybına karşı koruma)
        self._marker_path = Path(config.get(
            "engine.db_path", "database/trades.db"
        )).parent / "manual_positions.json"

        # v5.8/CEO-FAZ2: margin_reserve_pct config'den okunuyor
        self._margin_reserve_pct: float = float(
            config.get("engine.margin_reserve_pct", MARGIN_RESERVE_PCT_DEFAULT)
        )

        # Cross-motor referansları (Engine.__init__ tarafından atanır)
        self.ogul: Any | None = None
        self.h_engine: Any | None = None

    # ─────────────────────────────────────────────────────────────────
    #  RİSK ÖN KONTROLÜ (READ-ONLY, EMİR GÖNDERMİYOR)
    # ─────────────────────────────────────────────────────────────────

    def check_manual_trade(self, symbol: str, direction: str) -> dict:
        """Manuel işlem için risk ön kontrolü.

        BABA risk limitlerini, korelasyon kurallarını, teminat,
        eş zamanlı pozisyon limitini ve cross-motor netting'i kontrol eder.

        Returns:
            dict: can_trade, reason, suggested_lot, current_price,
                  atr_value, suggested_sl, suggested_tp, max_lot,
                  risk_summary.
        """
        result: dict[str, Any] = {
            "can_trade": False,
            "reason": "",
            "suggested_lot": 0.0,
            "current_price": 0.0,
            "atr_value": 0.0,
            "risk_summary": {},
        }

        # 1. İşlem saatleri
        if not self._is_trading_allowed():
            result["reason"] = "İşlem saatleri dışında (09:40-17:50)"
            return result

        # 2. Kendi active_trades'de netting çakışma
        if symbol in self.active_trades:
            existing = self.active_trades[symbol]
            result["reason"] = (
                f"Bu sembolde zaten manuel pozisyon var "
                f"({existing.direction} {existing.volume} lot)"
            )
            return result

        # 3. Cross-motor netting: OĞUL
        if self.ogul and hasattr(self.ogul, "active_trades"):
            if symbol in self.ogul.active_trades:
                ogul_trade = self.ogul.active_trades[symbol]
                result["reason"] = (
                    f"Bu sembolde OĞUL pozisyonu var "
                    f"({ogul_trade.direction} {ogul_trade.volume} lot)"
                )
                return result

        # 4. Cross-motor netting: H-Engine
        if self.h_engine and hasattr(self.h_engine, "get_hybrid_symbols"):
            if symbol in self.h_engine.get_hybrid_symbols():
                result["reason"] = (
                    f"Bu sembol hibrit yönetiminde — "
                    f"manuel işlem açılamaz"
                )
                return result

        # 5. BABA risk kontrolü
        if not self.baba:
            result["reason"] = "BABA başlatılmamış"
            return result

        verdict = self.baba.check_risk_limits(self.risk_params)
        result["risk_summary"] = {
            "regime": (
                self.baba.current_regime.regime_type.value
                if self.baba.current_regime else "UNKNOWN"
            ),
            "risk_multiplier": (
                self.baba.current_regime.risk_multiplier
                if self.baba.current_regime else 0
            ),
            "kill_switch_level": self.baba.kill_switch_level,
            "daily_trade_count": self.baba.daily_trade_count,
            "max_daily_trades": self.risk_params.max_daily_trades,
            "daily_manual_trade_count": self.baba._risk_state.get(
                "daily_manual_trade_count", 0,
            ),
            "max_daily_manual_trades": self.risk_params.max_daily_manual_trades,
            "consecutive_losses": self.baba.consecutive_losses,
            "lot_multiplier": verdict.lot_multiplier,
            "can_trade": verdict.can_trade,
        }
        if not verdict.can_trade:
            result["reason"] = verdict.reason
            return result

        # 6. Korelasyon kontrolü
        corr = self.baba.check_correlation_limits(
            symbol, direction, self.risk_params,
        )
        if not corr.can_trade:
            result["reason"] = corr.reason
            return result

        # 6.5. Günlük manuel işlem limiti (v5.9.3 — BULGU #3)
        # Manuel işlemler için ayrı günlük sayac. Otomatik işlem bütçesi
        # (max_daily_trades) eritilmez, manuel işlemler kendi bütçesinden
        # düşer (max_daily_manual_trades, varsayılan 10).
        max_manual = self.risk_params.max_daily_manual_trades
        manual_count = self.baba._risk_state.get("daily_manual_trade_count", 0)
        if manual_count >= max_manual:
            result["reason"] = (
                f"Günlük manuel işlem limiti doldu "
                f"({manual_count}/{max_manual})"
            )
            return result

        # 7. Eş zamanlı manuel pozisyon limiti
        active_states = (
            TradeState.FILLED, TradeState.SENT,
            TradeState.PARTIAL, TradeState.MARKET_RETRY,
        )
        active_count = sum(
            1 for t in self.active_trades.values()
            if t.state in active_states
        )
        if active_count >= MAX_CONCURRENT_MANUAL:
            result["reason"] = (
                f"Eş zamanlı manuel pozisyon limiti doldu "
                f"({active_count}/{MAX_CONCURRENT_MANUAL})"
            )
            return result

        # 8. Teminat kontrolü
        account = self.mt5.get_account_info()
        if account is None:
            result["reason"] = "Hesap bilgisi alınamadı"
            return result
        # v5.8/CEO-FAZ2: config'den okunan margin_reserve_pct
        if account.free_margin < account.equity * self._margin_reserve_pct:
            result["reason"] = (
                f"Yetersiz teminat (serbest={account.free_margin:.0f})"
            )
            return result

        # 9. ATR & lot hesaplama
        atr_val = self._get_current_atr(symbol)
        if atr_val is None or atr_val <= 0:
            result["reason"] = f"ATR hesaplanamadı ({symbol})"
            return result

        lot = self.baba.calculate_position_size(
            symbol, self.risk_params, atr_val, account.equity,
        )
        lot = min(lot, MAX_LOT_PER_CONTRACT)

        # 10. Fiyat
        tick = self.mt5.get_tick(symbol)
        current_price = 0.0
        if tick:
            current_price = tick.ask if direction == "BUY" else tick.bid

        # 11. Önerilen SL/TP (ATR bazlı)
        if current_price > 0 and atr_val > 0:
            if direction == "BUY":
                suggested_sl = current_price - (atr_val * 1.5)
                suggested_tp = current_price + (atr_val * 2.0)
            else:
                suggested_sl = current_price + (atr_val * 1.5)
                suggested_tp = current_price - (atr_val * 2.0)
        else:
            suggested_sl = 0.0
            suggested_tp = 0.0

        # 12. Sembol bazlı max lot
        sym_info = self.mt5.get_symbol_info(symbol)
        max_lot = sym_info.volume_max if sym_info else 10.0

        result["can_trade"] = True
        result["suggested_lot"] = lot
        result["current_price"] = current_price
        result["atr_value"] = atr_val
        result["suggested_sl"] = round(suggested_sl, 2)
        result["suggested_tp"] = round(suggested_tp, 2)
        result["max_lot"] = max_lot
        result["risk_summary"]["floating_pnl"] = (
            account.profit if hasattr(account, "profit") else 0.0
        )
        result["risk_summary"]["equity"] = account.equity
        result["risk_summary"]["free_margin"] = account.free_margin
        return result

    # ─────────────────────────────────────────────────────────────────
    #  EMİR GÖNDER
    # ─────────────────────────────────────────────────────────────────

    def open_manual_trade(
        self,
        symbol: str,
        direction: str,
        lot: float,
        sl: float | None = None,
        tp: float | None = None,
    ) -> dict:
        """Manuel MARKET emri gönder ve active_trades'e kaydet.

        Returns:
            dict: success, message, ticket, entry_price, sl, tp, lot.
        """
        result: dict[str, Any] = {
            "success": False,
            "message": "",
            "ticket": 0,
            "entry_price": 0.0,
            "sl": 0.0,
            "tp": 0.0,
            "lot": 0.0,
        }

        # 0. Netting kilit kontrolü (v5.5.1: cross-motor race condition önlemi)
        from engine.netting_lock import acquire_symbol, release_symbol
        if not acquire_symbol(symbol, owner="manuel"):
            result["message"] = f"{symbol} başka motor tarafından işleniyor (netting lock)"
            return result

        try:
            return self._open_manual_trade_locked(
                symbol, direction, lot, sl, tp, result
            )
        finally:
            release_symbol(symbol, owner="manuel")

    def _open_manual_trade_locked(
        self,
        symbol: str,
        direction: str,
        lot: float,
        sl: float | None,
        tp: float | None,
        result: dict,
    ) -> dict:
        """Netting lock alındıktan sonra çağrılır (iç metod)."""
        # 1. Tekrar risk kontrolü (race condition önlemi)
        check = self.check_manual_trade(symbol, direction)
        if not check["can_trade"]:
            result["message"] = check["reason"]
            return result

        # 2. ATR → SL/TP hesapla
        atr_val = self._get_current_atr(symbol)
        if atr_val is None or atr_val <= 0:
            result["message"] = "ATR hesaplanamadı"
            return result

        tick_data = self.mt5.get_tick(symbol)
        if tick_data is None:
            result["message"] = "Fiyat alınamadı"
            return result

        price = tick_data.ask if direction == "BUY" else tick_data.bid

        # Kullanıcı SL/TP verdiyse kullan, vermediyse ATR bazlı otomatik
        if sl is None or sl <= 0:
            if direction == "BUY":
                sl = price - (atr_val * 1.5)
            else:
                sl = price + (atr_val * 1.5)
            logger.info(f"Manuel SL otomatik: {sl:.2f} (ATR×1.5={atr_val * 1.5:.2f})")

        if tp is None or tp <= 0:
            if direction == "BUY":
                tp = price + (atr_val * 2.0)
            else:
                tp = price - (atr_val * 2.0)
            logger.info(f"Manuel TP otomatik: {tp:.2f} (ATR×2.0={atr_val * 2.0:.2f})")

        # 3. Lot sınırlama — sembol bazlı
        sym_info = self.mt5.get_symbol_info(symbol)
        if sym_info:
            vol_min = sym_info.volume_min
            vol_max = sym_info.volume_max
            vol_step = sym_info.volume_step if sym_info.volume_step > 0 else vol_min

            if lot < vol_min:
                result["message"] = f"Lot çok düşük: {lot} (min={vol_min})"
                return result
            if lot > vol_max:
                result["message"] = f"Lot çok yüksek: {lot} (max={vol_max})"
                return result

            # volume_step'e yuvarlama
            if vol_step > 0:
                lot = round(lot / vol_step) * vol_step
                lot = round(lot, 8)
        else:
            lot = min(lot, MAX_LOT_PER_CONTRACT)

        if lot <= 0:
            result["message"] = "Geçersiz lot miktarı"
            return result

        # 4. Trade nesnesi oluştur
        now = datetime.now()
        regime = self.baba.current_regime if self.baba else None
        regime_str = regime.regime_type.value if regime else "UNKNOWN"

        trade = Trade(
            symbol=symbol,
            direction=direction,
            volume=lot,
            entry_price=price,
            sl=sl,
            tp=tp,
            state=TradeState.SIGNAL,
            opened_at=now,
            strategy="manual",
            source="app",
            trailing_sl=sl,
            regime_at_entry=regime_str,
            requested_volume=lot,
        )

        # 5. MARKET emir gönder
        # v5.8: Manuel emirlerde SL/TP, emir sonrası modify_position ile MT5'e yazılır.
        # OĞUL ile aynı 2-aşamalı yaklaşım: önce emir, sonra SL/TP ekle.
        order_result = self.mt5.send_order(
            symbol=symbol,
            direction=direction,
            lot=lot,
            price=price,
            sl=0,
            tp=0,
            order_type="market",
        )

        if order_result is None:
            err = self.mt5._last_order_error
            if err.get("retcode"):
                error_detail = (
                    f"MT5 retcode={err['retcode']}: "
                    f"{err.get('comment', 'bilinmeyen hata')}"
                )
            elif err.get("reason"):
                error_detail = err["reason"]
            else:
                error_detail = "Bilinmeyen MT5 hatası"

            result["message"] = f"Emir gönderilemedi — {error_detail}"
            self.db.insert_event(
                event_type="MANUAL_TRADE_ERROR",
                message=(
                    f"Manuel emir başarısız: "
                    f"{direction} {lot} lot {symbol} — {error_detail}"
                ),
                severity="ERROR",
                action="manual_order_failed",
            )
            return result

        # 6. Force-close kontrolü (savunma katmanı)
        if order_result.get("force_closed"):
            logger.error(
                f"Manuel emir force-closed [{symbol}]: "
                f"MT5 SL/TP ekleyemedi, pozisyon kapatıldı"
            )
            result["message"] = "Emir gönderildi ama SL/TP hatası nedeniyle kapatıldı"
            return result

        # 6b. SL/TP MT5'e yaz (modify_position — OĞUL ile aynı 2-aşamalı yaklaşım)
        position_ticket = order_result.get("order", 0)
        sl_tp_applied = False
        if position_ticket and sl > 0 and tp > 0:
            for attempt in range(3):
                try:
                    mod_result = self.mt5.modify_position(
                        ticket=position_ticket, sl=sl, tp=tp,
                    )
                    if mod_result is not None:
                        sl_tp_applied = True
                        logger.info(
                            f"Manuel SL/TP MT5'e yazıldı [{symbol}]: "
                            f"ticket={position_ticket} SL={sl:.4f} TP={tp:.4f}"
                        )
                        break
                    else:
                        logger.warning(
                            f"Manuel SL/TP yazma denemesi {attempt+1}/3 başarısız [{symbol}]"
                        )
                except Exception as exc:
                    logger.error(f"Manuel SL/TP modify hatası [{symbol}]: {exc}")

            if not sl_tp_applied:
                # #247 OP-D S1-3: Manuel istisna + BABA raporu.
                # AX-4 "korumasız pozisyon yasak" genel kuralı; manuel trade'de
                # operatör kullanıcı bilinçli SL/TP açmış → pozisyonu KAPATMIYORUZ.
                # Ancak sistem kaydı şart: baba.report_unprotected_position çağrılır
                # → BABA ERROR_ATTRIBUTION + UI uyarı + RISK_MISS zinciri tetiklenir.
                logger.critical(
                    f"[AX-4 MANUEL İSTİSNA] Manuel SL/TP MT5'e yazılamadı [{symbol}] "
                    f"ticket={position_ticket} — pozisyon AÇIK (manuel bilinç), "
                    f"BABA'ya korumasız olarak raporlanıyor"
                )
                baba = getattr(self, "baba", None)
                if baba and hasattr(baba, "report_unprotected_position"):
                    try:
                        baba.report_unprotected_position(symbol, position_ticket)
                    except Exception as bexc:
                        logger.error(
                            f"baba.report_unprotected_position hatası [{symbol}]: {bexc}"
                        )
                else:
                    logger.warning(
                        "baba referansı yok veya report_unprotected_position eksik — "
                        "manuel korumasız pozisyon raporlanamadı"
                    )
                # Yazılım SL/TP bellekte korur; kullanıcı bilinç + sistem kaydı

        # 7. Başarılı → state güncelle
        trade.state = TradeState.SENT
        trade.order_ticket = position_ticket
        trade.sent_at = now

        # 7. DB kayıt
        db_id = self.db.insert_trade({
            "strategy": "manual",
            "symbol": symbol,
            "direction": direction,
            "entry_time": now.isoformat(),
            "entry_price": price,
            "lot": lot,
            "regime": regime_str,
            "source": "app",
        })
        trade.db_id = db_id

        # 8. ManuelMotor active_trades'e ekle (OĞUL'a GİRMİYOR)
        self.active_trades[symbol] = trade

        # 8.1. Dosya marker güncelle (v5.8.1: DB-bağımsız koruma)
        self._save_marker()

        # 9. BABA sayaç güncelle (v5.9.3 — BULGU #3: manuel olarak işaretle)
        if self.baba:
            self.baba.increment_daily_trade_count(trade_type="manual")

        # 10. Event kaydet
        self.db.insert_event(
            event_type="MANUAL_ORDER_SENT",
            message=(
                f"Manuel MARKET emir: {direction} {lot} lot {symbol} "
                f"@ {price:.4f} SL={sl:.4f} TP={tp:.4f}"
            ),
            severity="INFO",
            action="manual_order_sent",
        )

        logger.info(
            f"Manuel emir gönderildi [{symbol}]: "
            f"{direction} {lot} lot @ {price:.4f}"
        )

        result["success"] = True
        result["message"] = "Emir başarıyla gönderildi"
        result["ticket"] = trade.order_ticket
        result["entry_price"] = price
        result["sl"] = round(sl, 4)
        result["tp"] = round(tp, 4)
        result["lot"] = lot
        return result

    # ─────────────────────────────────────────────────────────────────
    #  POZİSYON SENKRONİZASYONU
    # ─────────────────────────────────────────────────────────────────

    def sync_positions(self) -> None:
        """MT5 pozisyonları ile active_trades senkronize et.

        SL/TP hit, L3 kapanma veya harici kapanmayı tespit eder.
        Ayrıca SENT → FILLED geçişini kontrol eder.

        NOT: FILLED pozisyonlar ticket bazlı kontrol edilir (sembol değil).
        Böylece aynı sembolde hibrit/oğul pozisyonu varken manuel ghost
        entry oluşması engellenir.
        """
        if not self.active_trades:
            return

        try:
            positions = self.mt5.get_positions()
        except Exception as exc:
            logger.error(f"get_positions hatası (ManuelMotor sync): {exc}")
            return

        # Symbol-based lookup (SENT → FILLED geçişi için)
        pos_by_symbol: dict[str, dict] = {
            p.get("symbol"): p for p in positions
        }
        open_symbols = set(pos_by_symbol.keys())

        # Ticket-based lookup (FILLED kapanma tespiti için)
        open_tickets: set[int] = {
            p.get("ticket") for p in positions if p.get("ticket")
        }

        for symbol in list(self.active_trades):
            trade = self.active_trades[symbol]

            # SENT → FILLED geçişi kontrol (sembol bazlı — ticket henüz yok)
            if trade.state == TradeState.SENT:
                if symbol in open_symbols:
                    pos = pos_by_symbol[symbol]
                    trade.state = TradeState.FILLED
                    trade.ticket = pos.get("ticket", trade.order_ticket)
                    trade.entry_price = pos.get("price_open", trade.entry_price)
                    trade.volume = pos.get("volume", trade.volume)
                    logger.info(
                        f"Manuel pozisyon FILLED [{symbol}]: "
                        f"ticket={trade.ticket}"
                    )
                    # DB güncelle
                    if trade.db_id > 0:
                        self.db.update_trade(trade.db_id, {
                            "mt5_position_id": trade.ticket,
                            "entry_price": trade.entry_price,
                            "lot": trade.volume,
                        })
                elif trade.sent_at and (
                    (datetime.now() - trade.sent_at).total_seconds()
                    > SENT_EXPIRE_SEC
                ):
                    # SENT ama MT5'te yok ve süre doldu →
                    # pozisyon açılıp harici kapatılmış veya emir reddedilmiş
                    logger.warning(
                        f"Manuel pozisyon SENT ama MT5'te yok [{symbol}]: "
                        f"order_ticket={trade.order_ticket} "
                        f"— {SENT_EXPIRE_SEC}s aşıldı, external_close"
                    )
                    self._handle_closed_trade(symbol, trade, "external_close")
                continue

            # FILLED pozisyon: ticket bazlı kontrol (sembol değil!)
            # Hibrite devredilen pozisyon aynı sembolle MT5'te kalır,
            # ama ticket farklıysa veya yoksa manuel işlem kapanmıştır.
            if trade.state == TradeState.FILLED:
                if trade.ticket and trade.ticket not in open_tickets:
                    logger.info(
                        f"Manuel pozisyon kapanmış [{symbol}]: "
                        f"ticket={trade.ticket}"
                    )
                    self._handle_closed_trade(symbol, trade, "external_close")
                elif not trade.ticket and symbol not in open_symbols:
                    # Ticket atanmamış eski kayıt — sembol bazlı fallback
                    logger.info(
                        f"Manuel pozisyon kapanmış [{symbol}]: "
                        f"ticket yok, sembol bazlı tespit"
                    )
                    self._handle_closed_trade(symbol, trade, "external_close")

    def _handle_closed_trade(
        self,
        symbol: str,
        trade: Trade,
        exit_reason: str,
    ) -> None:
        """Kapanmış manuel işlemi işle — state güncelle, DB yaz, active_trades'den sil."""
        now = datetime.now()
        trade.state = TradeState.CLOSED
        trade.closed_at = now

        # Son fiyatı al
        try:
            tick = self.mt5.get_tick(symbol)
        except Exception as exc:
            logger.error(f"get_tick hatası [{symbol}]: {exc}")
            tick = None

        if tick:
            if trade.direction == "BUY":
                trade.exit_price = tick.bid
            else:
                trade.exit_price = tick.ask
        elif trade.exit_price == 0:
            df = self.db.get_bars(symbol, "M15", limit=1)
            if not df.empty:
                trade.exit_price = float(df["close"].values[-1])

        # PnL hesapla (fiyat farkından fallback)
        if trade.entry_price > 0 and trade.exit_price > 0:
            contract_size = CONTRACT_SIZE
            sym_info = self.mt5.get_symbol_info(symbol)
            if sym_info and hasattr(sym_info, "trade_contract_size"):
                contract_size = sym_info.trade_contract_size

            if trade.direction == "BUY":
                trade.pnl = (trade.exit_price - trade.entry_price) * trade.volume * contract_size
            else:
                trade.pnl = (trade.entry_price - trade.exit_price) * trade.volume * contract_size

        # MT5 deal verisinden gerçek PnL/komisyon/swap
        commission = 0.0
        swap = 0.0
        deal_summary = None
        for attempt in range(3):
            deal_summary = self.mt5.get_deal_summary(trade.ticket)
            if deal_summary is not None:
                break
            if attempt < 2:
                _time.sleep(0.8)
        if deal_summary is not None:
            trade.pnl = deal_summary["pnl"]
            commission = deal_summary["commission"]
            swap = deal_summary["swap"]

        # DB güncelle
        if trade.db_id > 0:
            self.db.update_trade(trade.db_id, {
                "exit_time": now.isoformat(),
                "exit_price": trade.exit_price,
                "entry_price": trade.entry_price,
                "lot": trade.volume,
                "pnl": trade.pnl,
                "exit_reason": exit_reason,
                "mt5_position_id": trade.ticket,
                "commission": commission,
                "swap": swap,
            })

        # Event kaydet
        self.db.insert_event(
            event_type="MANUAL_TRADE_CLOSE",
            message=(
                f"Manuel işlem kapandı: {trade.direction} {trade.volume} lot "
                f"{symbol} @ {trade.exit_price:.4f} PnL={trade.pnl:.2f} "
                f"neden={exit_reason}"
            ),
            severity="INFO",
            action="manual_trade_closed",
        )

        logger.info(
            f"Manuel işlem kapandı [{symbol}]: {exit_reason} "
            f"PnL={trade.pnl:.2f}"
        )

        # Aktif işlemlerden sil
        self.active_trades.pop(symbol, None)

        # Dosya marker güncelle (v5.8.1)
        self._save_marker()

    # ─────────────────────────────────────────────────────────────────
    #  RİSK GÖSTERGESİ (READ-ONLY)
    # ─────────────────────────────────────────────────────────────────

    def calculate_risk_score(self, symbol: str, trade: Trade) -> dict:
        """Tek pozisyon için risk göstergesi hesapla.

        Returns:
            dict: sl_risk, regime_risk, pnl_risk, system_risk,
                  overall ("green"|"yellow"|"red"), score (0-100).
        """
        # --- SL Risk: SL mesafesi / ATR ---
        sl_risk = "green"
        atr_val = self._get_current_atr(symbol)
        if atr_val and atr_val > 0 and trade.sl > 0:
            tick = self.mt5.get_tick(symbol)
            if tick:
                current_price = tick.bid if trade.direction == "BUY" else tick.ask
                sl_distance = abs(current_price - trade.sl)
                sl_atr_ratio = sl_distance / atr_val
                if sl_atr_ratio >= SL_ATR_GREEN:
                    sl_risk = "green"
                elif sl_atr_ratio >= SL_ATR_YELLOW:
                    sl_risk = "yellow"
                else:
                    sl_risk = "red"
            else:
                sl_risk = "yellow"
        else:
            sl_risk = "yellow"

        # --- Regime Risk ---
        regime_risk = "green"
        if self.baba and self.baba.current_regime:
            from engine.models.regime import RegimeType
            rt = self.baba.current_regime.regime_type
            if rt == RegimeType.TREND:
                regime_risk = "green"
            elif rt == RegimeType.RANGE:
                regime_risk = "yellow"
            else:  # VOLATILE, OLAY
                regime_risk = "red"

        # --- PnL Risk: floating K/Z / equity ---
        pnl_risk = "green"
        account = self.mt5.get_account_info()
        if account and account.equity > 0:
            tick = self.mt5.get_tick(symbol)
            if tick:
                current_price = tick.bid if trade.direction == "BUY" else tick.ask
                contract_size = CONTRACT_SIZE
                sym_info = self.mt5.get_symbol_info(symbol)
                if sym_info and hasattr(sym_info, "trade_contract_size"):
                    contract_size = sym_info.trade_contract_size

                if trade.direction == "BUY":
                    floating = (current_price - trade.entry_price) * trade.volume * contract_size
                else:
                    floating = (trade.entry_price - current_price) * trade.volume * contract_size

                pnl_pct = floating / account.equity
                if pnl_pct >= 0:
                    pnl_risk = "green"
                elif pnl_pct >= PNL_YELLOW_PCT:
                    pnl_risk = "yellow"
                else:
                    pnl_risk = "red"

        # --- System Risk: kill-switch level ---
        system_risk = "green"
        if self.baba:
            ks = self.baba.kill_switch_level
            if ks == 0:
                system_risk = "green"
            elif ks == 1:
                system_risk = "yellow"
            else:  # L2, L3
                system_risk = "red"

        # --- Overall: en kötü renk ---
        colors = [sl_risk, regime_risk, pnl_risk, system_risk]
        worst_rank = max(_COLOR_RANK.get(c, 0) for c in colors)
        overall = _RANK_COLOR[worst_rank]

        # --- Score: toplam (0-100) ---
        score = sum(_COLOR_POINTS.get(c, 0) for c in colors)

        return {
            "sl_risk": sl_risk,
            "regime_risk": regime_risk,
            "pnl_risk": pnl_risk,
            "system_risk": system_risk,
            "overall": overall,
            "score": score,
        }

    def get_all_risk_scores(self) -> dict[str, dict]:
        """Tüm aktif manuel pozisyonların risk skorlarını döndür."""
        scores: dict[str, dict] = {}
        for symbol, trade in self.active_trades.items():
            if trade.state == TradeState.FILLED:
                try:
                    scores[symbol] = self.calculate_risk_score(symbol, trade)
                except Exception as exc:
                    logger.error(f"Risk skor hesaplama hatası [{symbol}]: {exc}")
                    scores[symbol] = {
                        "sl_risk": "yellow", "regime_risk": "yellow",
                        "pnl_risk": "yellow", "system_risk": "yellow",
                        "overall": "yellow", "score": 60,
                    }
        return scores

    # ─────────────────────────────────────────────────────────────────
    #  CROSS-MOTOR KOORDİNASYON
    # ─────────────────────────────────────────────────────────────────

    def get_manual_symbols(self) -> set[str]:
        """Manuel yönetimdeki aktif sembol kümesi.

        OĞUL ve H-Engine netting koruması için kullanılır.
        """
        return {
            s for s, t in self.active_trades.items()
            if t.state in (TradeState.FILLED, TradeState.SENT, TradeState.PARTIAL)
        }

    # ─────────────────────────────────────────────────────────────────
    #  DURUM GERİ YÜKLEME
    # ─────────────────────────────────────────────────────────────────

    def restore_active_trades(self) -> None:
        """Engine restart'ta manuel işlemleri MT5 + DB + marker eşleyerek geri yükle.

        v5.8.1: Marker dosya fallback eklendi. DB WAL kaybı durumunda
        bile manuel pozisyonlar korunur.

        Kaynak önceliği: DB > marker dosya.
        """
        try:
            positions = self.mt5.get_positions()
        except Exception as exc:
            logger.error(f"get_positions hatası (ManuelMotor restore): {exc}")
            return

        if not positions:
            logger.info("ManuelMotor restore: açık pozisyon yok")
            # Marker temizle (MT5'te pozisyon kalmamış)
            self._save_marker()
            return

        # v5.8.1: Marker dosyasını fallback olarak oku
        marker_data = self._load_marker()

        restored_count = 0
        for pos in positions:
            symbol = pos.get("symbol", "")
            ticket = pos.get("ticket", 0)
            direction = pos.get("type", "")

            if not symbol or not ticket:
                continue

            # Kaynak 1: DB'de eşleşen aktif trade ara
            trades = self.db.get_trades(symbol=symbol, limit=10)
            db_trade = next(
                (
                    t for t in trades
                    if t.get("exit_time") is None
                    and t.get("direction") == direction
                    and t.get("strategy") == "manual"  # SADECE manuel işlemler
                ),
                None,
            )

            # Kaynak 2: Marker dosyasında var mı? (DB kaybına karşı fallback)
            marker_info = marker_data.get(symbol)
            marker_match = (
                marker_info is not None
                and int(marker_info.get("ticket", 0)) == ticket
            )

            if db_trade is None and not marker_match:
                continue  # Ne DB'de ne marker'da → Manuel değil → OĞUL'a ait

            # Manuel pozisyon tespit edildi
            if db_trade is None and marker_match:
                logger.warning(
                    f"ManuelMotor restore: {symbol} ticket={ticket} "
                    f"DB'de YOK ama marker dosyasında var — marker'dan geri yükleniyor! "
                    f"(WAL kaybı muhtemel)"
                )

            strategy = "manual"
            regime_at_entry = db_trade.get("regime", "") if db_trade else ""
            entry_time_str = db_trade.get("entry_time", "") if db_trade else ""

            # Marker'dan entry_time fallback
            if not entry_time_str and marker_info:
                entry_time_str = marker_info.get("opened_at", "") or ""

            opened_at = None
            if entry_time_str:
                try:
                    opened_at = datetime.fromisoformat(entry_time_str)
                except (ValueError, TypeError):
                    pass

            # source bilgisini DB'den veya marker'dan al
            restore_source = ""
            if db_trade:
                restore_source = db_trade.get("source", "app") or "app"
            elif marker_match and marker_info:
                restore_source = marker_info.get("source", "mt5_direct") or "mt5_direct"

            trade = Trade(
                symbol=symbol,
                direction=direction,
                volume=pos.get("volume", 0.0),
                entry_price=pos.get("price_open", 0.0),
                sl=pos.get("sl", 0.0),
                tp=pos.get("tp", 0.0),
                state=TradeState.FILLED,
                ticket=ticket,
                strategy=strategy,
                source=restore_source,
                trailing_sl=pos.get("sl", 0.0),
                db_id=db_trade.get("id", 0) if db_trade else 0,
                regime_at_entry=regime_at_entry,
            )
            if opened_at:
                trade.opened_at = opened_at

            self.active_trades[symbol] = trade
            restored_count += 1

            # DB'yi MT5 pozisyonuyla senkronize et
            if db_trade:
                sync_fields: dict[str, Any] = {}
                db_lot = db_trade.get("lot", 0.0)
                db_entry = db_trade.get("entry_price", 0.0)
                if abs(trade.volume - db_lot) > 1e-8:
                    sync_fields["lot"] = trade.volume
                if abs(trade.entry_price - db_entry) > 1e-4:
                    sync_fields["entry_price"] = trade.entry_price
                if trade.ticket and not db_trade.get("mt5_position_id"):
                    sync_fields["mt5_position_id"] = trade.ticket
                if sync_fields and trade.db_id > 0:
                    self.db.update_trade(trade.db_id, sync_fields)

            logger.info(
                f"ManuelMotor geri yüklendi [{symbol}]: ticket={ticket} "
                f"{direction} {trade.volume} lot"
                f" kaynak={'DB' if db_trade else 'MARKER'}"
            )

        # Marker'ı güncel active_trades ile senkronize et
        self._save_marker()

        logger.info(f"ManuelMotor restore tamamlandı: {restored_count} pozisyon")

    # ─────────────────────────────────────────────────────────────────
    #  MT5-DIRECT POZİSYON SAHİPLENME (v5.8.2)
    # ─────────────────────────────────────────────────────────────────

    def adopt_mt5_direct_position(self, pos: dict) -> bool:
        """MT5 terminalinden doğrudan açılmış pozisyonu ManuelMotor'a devret.

        OĞUL restore_active_trades() tarafından çağrılır. Hiçbir motorun
        sahiplenmediği (yetim) pozisyonlar, kullanıcının MT5'ten açtığı
        işlemler olarak ManuelMotor'a aktarılır.

        Yapılan işlemler:
            1. DB'ye strategy='manual', source='mt5_direct' kaydı oluştur
            2. active_trades dict'e ekle
            3. Marker dosyasını güncelle

        Args:
            pos: MT5 pozisyon verisi (symbol, ticket, type, volume, price_open, sl, tp).

        Returns:
            True: başarılı sahiplenme, False: hata oluştu.
        """
        try:
            symbol = pos.get("symbol", "")
            ticket = pos.get("ticket", 0)
            direction = pos.get("type", "")
            volume = pos.get("volume", 0.0)
            entry_price = pos.get("price_open", 0.0)
            sl = pos.get("sl", 0.0)
            tp = pos.get("tp", 0.0)

            if not symbol or not ticket:
                logger.error(f"MT5-direct adopt: symbol veya ticket eksik — {pos}")
                return False

            # Netting kontrolü — aynı sembolde zaten pozisyon varsa alma
            if symbol in self.active_trades:
                logger.warning(
                    f"MT5-direct adopt: {symbol} zaten active_trades'de — atlanıyor"
                )
                return False

            # DB'ye kayıt oluştur
            from datetime import datetime as _dt
            now = _dt.now()
            db_id = self.db.insert_trade({
                "strategy": "manual",
                "symbol": symbol,
                "direction": direction,
                "entry_time": now.isoformat(),
                "entry_price": entry_price,
                "lot": volume,
                "regime": "",
                "mt5_position_id": ticket,
                "source": "mt5_direct",
            })

            # Trade nesnesi oluştur ve active_trades'e ekle
            trade = Trade(
                symbol=symbol,
                direction=direction,
                volume=volume,
                entry_price=entry_price,
                sl=sl,
                tp=tp,
                state=TradeState.FILLED,
                ticket=ticket,
                strategy="manual",
                source="mt5_direct",
                trailing_sl=sl,
                db_id=db_id,
                regime_at_entry="",
                opened_at=now,
            )

            self.active_trades[symbol] = trade
            self._save_marker()

            logger.info(
                f"MT5-direct sahiplenildi [{symbol}]: ticket={ticket} "
                f"{direction} {volume} lot @ {entry_price} — DB id={db_id}"
            )
            return True

        except Exception as exc:
            logger.error(
                f"MT5-direct sahiplenme hatası [{pos.get('symbol', '?')}]: {exc}"
            )
            return False

    # ─────────────────────────────────────────────────────────────────
    #  YARDIMCI METOTLAR
    # ─────────────────────────────────────────────────────────────────

    def _get_current_atr(self, symbol: str) -> float | None:
        """Sembol için güncel ATR(14) değeri."""
        df = self.db.get_bars(symbol, "M15", limit=MIN_BARS_M15)
        if df.empty or len(df) < ATR_PERIOD + 1:
            return None
        close = df["close"].values.astype(np.float64)
        high_arr = df["high"].values.astype(np.float64)
        low_arr = df["low"].values.astype(np.float64)
        atr_arr = calc_atr(high_arr, low_arr, close, ATR_PERIOD)
        return last_valid(atr_arr)

    # ─────────────────────────────────────────────────────────────────
    #  DOSYA MARKER (v5.8.1 — DB-bağımsız koruma)
    # ─────────────────────────────────────────────────────────────────

    def _save_marker(self) -> None:
        """Aktif manuel pozisyonları JSON dosyaya yaz.

        DB WAL kaybına karşı yedek koruma. Her pozisyon açma/kapama
        işleminde çağrılır. Dosya küçük ve atomik yazılır.
        """
        try:
            data = {}
            for sym, trade in self.active_trades.items():
                data[sym] = {
                    "ticket": trade.ticket,
                    "direction": trade.direction,
                    "volume": trade.volume,
                    "entry_price": trade.entry_price,
                    "opened_at": trade.opened_at.isoformat() if trade.opened_at else None,
                    "source": getattr(trade, "source", ""),
                }
            # Atomik yaz: önce temp dosyaya, sonra rename
            tmp = self._marker_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self._marker_path)
            logger.debug(f"Manuel marker kaydedildi: {len(data)} pozisyon")
        except Exception as exc:
            logger.error(f"Manuel marker kaydetme hatası: {exc}")

    def _load_marker(self) -> dict[str, dict]:
        """JSON marker dosyasından manuel pozisyon listesini oku.

        Returns:
            {symbol: {ticket, direction, volume, ...}} veya boş dict.
        """
        try:
            if self._marker_path.exists():
                data = json.loads(self._marker_path.read_text(encoding="utf-8"))
                logger.info(f"Manuel marker okundu: {len(data)} pozisyon")
                return data
        except Exception as exc:
            logger.error(f"Manuel marker okuma hatası: {exc}")
        return {}

    def get_manual_symbols(self) -> set[str]:
        """Tüm kaynaklardan (memory + marker dosya) manuel sembol setini döndür.

        OĞUL bu metodu kullanarak DB'den bağımsız koruma sağlar.
        """
        symbols = set(self.active_trades.keys())
        # Marker dosyasından da oku (memory boş olsa bile)
        try:
            marker_data = self._load_marker()
            symbols.update(marker_data.keys())
        except Exception:
            pass
        return symbols

    def get_manual_tickets(self) -> set[int]:
        """Tüm kaynaklardan (memory + marker dosya) manuel ticket setini döndür."""
        tickets: set[int] = set()
        for t in self.active_trades.values():
            if t.ticket:
                tickets.add(t.ticket)
        try:
            marker_data = self._load_marker()
            for info in marker_data.values():
                tk = info.get("ticket")
                if tk:
                    tickets.add(int(tk))
        except Exception:
            pass
        return tickets

    def _is_trading_allowed(self, now: datetime | None = None) -> bool:
        """İşlem saatleri kontrolü (09:45-17:45)."""
        now = now or datetime.now()
        current_time = now.time()
        if current_time < TRADING_OPEN or current_time > TRADING_CLOSE:
            return False
        # Hafta sonu kontrolü (Cumartesi=5, Pazar=6)
        if now.weekday() >= 5:
            return False
        return True
