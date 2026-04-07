"""OĞUL Stop SL/TP Yönetim Katmanı.

GCM VİOP netting modunda TRADE_ACTION_SLTP (modify_position) çalışmıyor
(retcode=10035 Invalid order). Bu modül, OĞUL pozisyonlarının SL/TP
korumasını plain STOP bekleyen emirlerle sağlar.

Mimari:
    - BUY pozisyon → Sell Stop = SL koruma (bid ≤ price → market sell)
    - SELL pozisyon → Buy Stop = SL koruma (ask ≥ price → market buy)
    - Güncelleme: modify_pending_order → 3x başarısızsa cancel + yeniden gönder

Plain STOP tetiklendiğinde MARKET emri olarak çalışır — dolum garantili.
Stop Limit'ten farklı olarak limit fiyatı yoktur, slippage koruması yoktur
ama tetiklendiğinde EMİR DOLAR.

v5.9.2: #118 Motor izolasyonu sonrası eklendi.
v5.9.2: #120 Stop Limit → plain STOP migrasyonu.
"""

from __future__ import annotations

from typing import Any

from engine.logger import get_logger

logger = get_logger(__name__)

# ── Varsayılan sabitler ─────────────────────────────────────────────
_MAX_MODIFY_RETRIES = 3    # modify başarısız → cancel + yeniden gönder


class OgulSLTP:
    """OĞUL pozisyonları için plain STOP SL yöneticisi.

    Her OĞUL pozisyonu için bir trailing Stop emri yönetir.
    mt5_bridge'in send_stop / modify_pending_order / cancel_pending_order
    fonksiyonlarını kullanır.

    Args:
        mt5: MT5Bridge instance.
        config: Config instance.
    """

    def __init__(self, mt5: Any, config: Any) -> None:
        self._mt5 = mt5
        self._config = config
        # Sembol bazlı modify başarısızlık sayacı
        self._modify_fail_counts: dict[str, int] = {}
        logger.info("OgulSLTP başlatıldı (plain STOP modu)")

    # ═════════════════════════════════════════════════════════════════
    #  İLK SL YERLEŞTİRME
    # ═════════════════════════════════════════════════════════════════

    def set_initial_sl(self, trade: Any, sl: float) -> bool:
        """Pozisyon açıldıktan sonra ilk SL Stop emrini yerleştir.

        Args:
            trade: Trade nesnesi (ticket, symbol, direction, volume gerekli).
            sl: Stop-loss fiyatı.

        Returns:
            True → emir başarıyla yerleştirildi, False → başarısız.
        """
        if sl <= 0:
            return False

        symbol = trade.symbol
        order_direction = "SELL" if trade.direction == "BUY" else "BUY"

        result = self._mt5.send_stop(
            symbol, order_direction, trade.volume,
            sl,
            comment=f"OGUL_SL_{trade.ticket}",
        )

        if result is not None:
            trade.sl_order_ticket = result.get("order_ticket", 0)
            logger.info(
                f"OĞUL SL Stop yerleştirildi [{symbol}]: "
                f"order={trade.sl_order_ticket} {order_direction} "
                f"price={sl:.4f}"
            )
            return True

        logger.error(
            f"OĞUL SL Stop gönderilemedi [{symbol}]: "
            f"{order_direction} price={sl:.4f}"
        )
        return False

    # ═════════════════════════════════════════════════════════════════
    #  TRAİLİNG SL GÜNCELLEME
    # ═════════════════════════════════════════════════════════════════

    def update_trailing_sl(self, trade: Any, new_sl: float) -> bool:
        """Trailing SL Stop emrini güncelle.

        Sıra:
            1. Mevcut emir varsa → modify_pending_order dene
            2. Modify 3x başarısız → cancel + yeniden gönder
            3. Emir yoksa (ilk kez veya tetiklenmiş) → yeni emir gönder

        Args:
            trade: Trade nesnesi.
            new_sl: Yeni trailing SL fiyatı.

        Returns:
            True → güncelleme başarılı, False → başarısız.
        """
        symbol = trade.symbol
        sl_ticket = getattr(trade, "sl_order_ticket", 0)
        order_direction = "SELL" if trade.direction == "BUY" else "BUY"

        # ── Mevcut emir var mı? ──────────────────────────────────────
        if sl_ticket > 0:
            # Emrin hâlâ bekliyor olduğunu doğrula
            pending = self._mt5.get_pending_orders(symbol)
            order_exists = any(
                o.get("ticket") == sl_ticket for o in (pending or [])
            )

            if order_exists:
                # Modify dene (tek fiyat — plain STOP)
                result = self._mt5.modify_pending_order(
                    sl_ticket, new_sl,
                )
                if result is not None:
                    self._modify_fail_counts.pop(symbol, None)
                    trade.trailing_sl = new_sl
                    trade.sl = new_sl
                    return True

                # Modify başarısız
                fail_count = self._modify_fail_counts.get(symbol, 0) + 1
                self._modify_fail_counts[symbol] = fail_count
                if fail_count < _MAX_MODIFY_RETRIES:
                    logger.warning(
                        f"OĞUL SL modify başarısız [{symbol}]: "
                        f"ticket={sl_ticket} (deneme {fail_count}/{_MAX_MODIFY_RETRIES})"
                    )
                    return False

                # 3x başarısız → cancel + yeniden gönder
                logger.warning(
                    f"OĞUL SL modify {_MAX_MODIFY_RETRIES}x başarısız [{symbol}] "
                    f"— iptal edip yeniden gönderiliyor"
                )
                self._mt5.cancel_pending_order(sl_ticket)
                trade.sl_order_ticket = 0
                self._modify_fail_counts.pop(symbol, None)
            else:
                # Emir tetiklenmiş veya iptal edilmiş
                logger.info(
                    f"OĞUL SL emri kayboldu [{symbol}]: ticket={sl_ticket} "
                    f"— yenisi gönderiliyor"
                )
                trade.sl_order_ticket = 0

        # ── Yeni emir gönder ──────────────────────────────────────────
        result = self._mt5.send_stop(
            symbol, order_direction, trade.volume,
            new_sl,
            comment=f"OGUL_SL_{trade.ticket}",
        )

        if result is not None:
            trade.sl_order_ticket = result.get("order_ticket", 0)
            trade.trailing_sl = new_sl
            trade.sl = new_sl
            logger.info(
                f"OĞUL SL Stop yerleştirildi [{symbol}]: "
                f"order={trade.sl_order_ticket} price={new_sl:.4f}"
            )
            self._modify_fail_counts.pop(symbol, None)
            return True

        logger.error(
            f"OĞUL SL Stop gönderilemedi [{symbol}]: price={new_sl:.4f}"
        )
        return False

    # ═════════════════════════════════════════════════════════════════
    #  BEKLEMEDEKİ EMİRLERİ TEMİZLE
    # ═════════════════════════════════════════════════════════════════

    def cancel_orders(self, trade: Any) -> None:
        """Pozisyon kapanışında veya EOD'da bekleyen Stop emirlerini iptal et.

        Args:
            trade: Kapanan Trade nesnesi.
        """
        sl_ticket = getattr(trade, "sl_order_ticket", 0)
        symbol = trade.symbol

        if sl_ticket > 0:
            try:
                self._mt5.cancel_pending_order(sl_ticket)
                logger.info(
                    f"OĞUL SL emri iptal edildi [{symbol}]: ticket={sl_ticket}"
                )
            except Exception as exc:
                logger.error(
                    f"OĞUL SL emri iptal hatası [{symbol}]: "
                    f"ticket={sl_ticket} — {exc}"
                )
            trade.sl_order_ticket = 0

        self._modify_fail_counts.pop(symbol, None)

    # ═════════════════════════════════════════════════════════════════
    #  EMİR DURUMU KONTROL
    # ═════════════════════════════════════════════════════════════════

    def check_sl_triggered(self, trade: Any) -> bool:
        """SL Stop emrinin tetiklenip tetiklenmediğini kontrol et.

        Tetiklenmişse (bekleyen emirler arasında yoksa) → True döner.
        Bu durumda OĞUL pozisyonu kapatılmış demektir.

        Args:
            trade: Trade nesnesi.

        Returns:
            True → emir tetiklendi (pozisyon kapandı), False → hâlâ bekliyor.
        """
        sl_ticket = getattr(trade, "sl_order_ticket", 0)
        if sl_ticket <= 0:
            return False  # Emir yok, tetiklenme kontrolü anlamsız

        pending = self._mt5.get_pending_orders(trade.symbol)
        order_exists = any(
            o.get("ticket") == sl_ticket for o in (pending or [])
        )

        if not order_exists:
            # Emir kayboldu — büyük olasılıkla tetiklendi
            trade.sl_order_ticket = 0
            return True

        return False

    # ═════════════════════════════════════════════════════════════════
    #  RESTART KURTARMA
    # ═════════════════════════════════════════════════════════════════

    def restore_sl_order(self, trade: Any) -> None:
        """Restart sonrası mevcut Stop emrini bul ve eşleştir.

        OGUL_SL_{ticket} comment pattern'iyle eşleştirme yapar.
        Bulamazsa yeni SL emri yerleştirir.

        Args:
            trade: Restore edilen Trade nesnesi.
        """
        symbol = trade.symbol
        pending = self._mt5.get_pending_orders(symbol)

        if pending:
            comment_pattern = f"OGUL_SL_{trade.ticket}"
            for order in pending:
                if comment_pattern in (order.get("comment", "") or ""):
                    trade.sl_order_ticket = order.get("ticket", 0)
                    logger.info(
                        f"OĞUL SL emri restore edildi [{symbol}]: "
                        f"ticket={trade.sl_order_ticket}"
                    )
                    return

        # Mevcut emir bulunamadı — yenisini yerleştir
        if trade.sl > 0 and trade.trailing_sl > 0:
            sl_price = trade.trailing_sl
        elif trade.sl > 0:
            sl_price = trade.sl
        else:
            logger.warning(
                f"OĞUL SL restore: SL bilgisi yok [{symbol}] — emir yerleştirilemiyor"
            )
            return

        self.set_initial_sl(trade, sl_price)
