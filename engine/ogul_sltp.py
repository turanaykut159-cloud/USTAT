"""OĞUL Stop Limit SL/TP Yönetim Katmanı.

GCM VİOP netting modunda TRADE_ACTION_SLTP (modify_position) çalışmıyor
(retcode=10035 Invalid order). Ayrıca GCM VİOP plain STOP emirlerini de
reddeder (ORDER_TYPE_BUY_STOP/SELL_STOP → retcode=10035).

Bu modül, OĞUL pozisyonlarının SL korumasını STOP LIMIT bekleyen emirlerle
sağlar. H-Engine PRİMNET ile aynı emir tipi kullanılır.

Mimari:
    - BUY pozisyon → Sell Stop Limit = SL koruma
      (ask ≤ stop_price → Sell Limit @ limit_price yerleşir)
    - SELL pozisyon → Buy Stop Limit = SL koruma
      (bid ≥ stop_price → Buy Limit @ limit_price yerleşir)
    - Limit fiyatı: stop ± gap (config: ogul.stop_limit_gap_prim)
    - Güncelleme: modify_pending_order → 3x başarısızsa cancel + yeniden gönder

v5.9.2: #118 Motor izolasyonu sonrası eklendi.
v5.9.2: #120 Stop Limit → plain STOP migrasyonu.
v6.0.0: #121 plain STOP → STOP LIMIT migrasyonu (GCM VİOP uyumluluğu).
"""

from __future__ import annotations

from typing import Any

from engine.logger import get_logger

logger = get_logger(__name__)

# ── Varsayılan sabitler ─────────────────────────────────────────────
_MAX_MODIFY_RETRIES = 3    # modify başarısız → cancel + yeniden gönder


class OgulSLTP:
    """OĞUL pozisyonları için STOP LIMIT SL yöneticisi.

    Her OĞUL pozisyonu için bir trailing Stop Limit emri yönetir.
    mt5_bridge'in send_stop_limit / modify_pending_order / cancel_pending_order
    fonksiyonlarını kullanır.

    GCM VİOP plain STOP desteklemez — STOP LIMIT kullanılır.
    Limit fiyatı, stop fiyatından gap kadar uzakta ayarlanır:
        - SELL STOP LIMIT: limit = stop + gap (limit > stop)
        - BUY STOP LIMIT:  limit = stop - gap (limit < stop)

    Args:
        mt5: MT5Bridge instance.
        config: Config instance.
    """

    def __init__(self, mt5: Any, config: Any) -> None:
        self._mt5 = mt5
        self._config = config
        # Stop ile Limit arasındaki mesafe (prim cinsinden, varsayılan 0.3)
        self._stop_limit_gap_prim: float = config.get(
            "ogul.stop_limit_gap_prim", 0.3,
        )
        # Sembol bazlı modify başarısızlık sayacı
        self._modify_fail_counts: dict[str, int] = {}
        logger.info(
            f"OgulSLTP başlatıldı (STOP LIMIT modu, "
            f"gap_prim={self._stop_limit_gap_prim})"
        )

    # ═════════════════════════════════════════════════════════════════
    #  YARDIMCI METOTLAR
    # ═════════════════════════════════════════════════════════════════

    @staticmethod
    def _viop_tick_size(price: float) -> float:
        """VİOP pay vadeli kontrat fiyat adımını döndür.

        MT5 API trade_tick_size alanı VİOP'ta fiyat aralığına göre
        değişen adımları doğru raporlamıyor (hep 0.01 dönüyor).
        Bu tablo Borsa İstanbul VİOP kurallarını uygular.

        Kaynak: H-Engine._viop_tick_size ile aynı tablo.
        """
        abs_price = abs(price)
        if abs_price < 25.0:
            return 0.01
        if abs_price < 50.0:
            return 0.02
        if abs_price < 100.0:
            return 0.05
        if abs_price < 500.0:
            return 0.05
        if abs_price < 1000.0:
            return 0.10
        if abs_price < 2500.0:
            return 0.25
        return 0.50

    def _calc_limit_price(
        self, stop_price: float, order_direction: str,
    ) -> float:
        """Stop fiyatından limit fiyatını hesapla.

        SELL STOP LIMIT (BUY poz SL): limit = stop + gap  (limit > stop)
        BUY STOP LIMIT  (SELL poz SL): limit = stop - gap  (limit < stop)

        Gap = stop_price × stop_limit_gap_prim × 0.01
        Sonuç VİOP tick adımına yuvarlanır.

        Args:
            stop_price: Stop (tetikleme) fiyatı.
            order_direction: "SELL" veya "BUY" (SL emir yönü).

        Returns:
            Limit fiyatı (VİOP tick adımına yuvarlanmış).
        """
        gap = stop_price * self._stop_limit_gap_prim * 0.01
        tick = self._viop_tick_size(stop_price)

        if order_direction.upper() == "SELL":
            # SELL STOP LIMIT: limit > stop
            raw_limit = stop_price + gap
        else:
            # BUY STOP LIMIT: limit < stop
            raw_limit = stop_price - gap

        # VİOP tick adımına yuvarla + floating point temizliği
        return round(round(raw_limit / tick) * tick, 2)

    # ═════════════════════════════════════════════════════════════════
    #  İLK SL YERLEŞTİRME
    # ═════════════════════════════════════════════════════════════════

    def set_initial_sl(self, trade: Any, sl: float) -> bool:
        """Pozisyon açıldıktan sonra ilk SL Stop Limit emrini yerleştir.

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
        limit_price = self._calc_limit_price(sl, order_direction)

        result = self._mt5.send_stop_limit(
            symbol, order_direction, trade.volume,
            sl, limit_price,
            comment=f"OGUL_SL_{trade.ticket}",
        )

        if result is not None:
            trade.sl_order_ticket = result.get("order_ticket", 0)
            logger.info(
                f"OĞUL SL Stop Limit yerleştirildi [{symbol}]: "
                f"order={trade.sl_order_ticket} {order_direction} "
                f"stop={sl:.4f} limit={limit_price:.4f}"
            )
            return True

        logger.error(
            f"OĞUL SL Stop Limit gönderilemedi [{symbol}]: "
            f"{order_direction} stop={sl:.4f} limit={limit_price:.4f}"
        )
        return False

    # ═════════════════════════════════════════════════════════════════
    #  İLK TP YERLEŞTİRME (#247 OP-D S1-2)
    # ═════════════════════════════════════════════════════════════════

    def set_initial_tp(self, trade: Any, tp: float) -> bool:
        """Pozisyon açıldıktan sonra ilk TP Limit emrini yerleştir.

        OGUL sinyali `signal.tp` sağlarsa çağrılır. Buy pozisyonu için Sell Limit,
        Sell pozisyonu için Buy Limit emri gönderilir (VİOP netting'de ters yönlü
        Limit pozisyonu azaltır/kapatır).

        AX-4 enforced_in: engine/ogul_sltp.py::set_initial_sl + set_initial_tp.
        TP trailing mekanizması SEPARATEDİR (ogul.update_profit_protection
        async) — bu metot sadece ilk statik TP'yi yerleştirir. Reject halinde
        trailing fallback'a bırakılır.

        Args:
            trade: Trade nesnesi (ticket, symbol, direction, volume gerekli).
            tp: Take-profit fiyatı.

        Returns:
            True → emir başarıyla yerleştirildi, False → başarısız (trailing
            mekanizması devreye girer).
        """
        if tp <= 0:
            return False

        symbol = trade.symbol
        # Pozisyon BUY ise TP'ye SELL LIMIT (üstte), pozisyon SELL ise BUY LIMIT (altta)
        order_direction = "SELL" if trade.direction == "BUY" else "BUY"

        result = self._mt5.send_limit(
            symbol, order_direction, trade.volume, tp,
            comment=f"OGUL_TP_{trade.ticket}",
        )

        if result is not None:
            trade.tp_order_ticket = result.get("order_ticket", 0)
            logger.info(
                f"OĞUL TP Limit yerleştirildi [{symbol}]: "
                f"order={trade.tp_order_ticket} {order_direction} "
                f"price={tp:.4f}"
            )
            return True

        logger.warning(
            f"OĞUL TP Limit gönderilemedi [{symbol}]: "
            f"{order_direction} price={tp:.4f} — trailing mekanizması fallback"
        )
        return False

    # ═════════════════════════════════════════════════════════════════
    #  TRAİLİNG SL GÜNCELLEME
    # ═════════════════════════════════════════════════════════════════

    def update_trailing_sl(self, trade: Any, new_sl: float) -> bool:
        """Trailing SL Stop Limit emrini güncelle.

        Sıra:
            1. Mevcut emir varsa → modify_pending_order dene (stop + limit)
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
        new_limit = self._calc_limit_price(new_sl, order_direction)

        # ── Mevcut emir var mı? ──────────────────────────────────────
        if sl_ticket > 0:
            # Emrin hâlâ bekliyor olduğunu doğrula
            pending = self._mt5.get_pending_orders(symbol)
            order_exists = any(
                o.get("ticket") == sl_ticket for o in (pending or [])
            )

            if order_exists:
                # Modify dene (stop + stoplimit — STOP LIMIT emri)
                result = self._mt5.modify_pending_order(
                    sl_ticket, new_sl,
                    new_stoplimit=new_limit,
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
        result = self._mt5.send_stop_limit(
            symbol, order_direction, trade.volume,
            new_sl, new_limit,
            comment=f"OGUL_SL_{trade.ticket}",
        )

        if result is not None:
            trade.sl_order_ticket = result.get("order_ticket", 0)
            trade.trailing_sl = new_sl
            trade.sl = new_sl
            logger.info(
                f"OĞUL SL Stop Limit yerleştirildi [{symbol}]: "
                f"order={trade.sl_order_ticket} stop={new_sl:.4f} "
                f"limit={new_limit:.4f}"
            )
            self._modify_fail_counts.pop(symbol, None)
            return True

        logger.error(
            f"OĞUL SL Stop Limit gönderilemedi [{symbol}]: "
            f"stop={new_sl:.4f} limit={new_limit:.4f}"
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
