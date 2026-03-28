"""Silinen fonksiyon: _calc_profit_trailing_sl
Kaynak: engine/h_engine.py satır 1000-1073
Silme tarihi: 2026-03-28
Neden: PRİMNET tek trailing modu olarak belirlendi
"""


def _calc_profit_trailing_sl(
    self, hp, current_price: float,
    profit: float, swap: float,
) -> float | None:
    """Kar bazli trailing SL hesapla (v5.8 - Kademeli Oran Sistemi).

    Iki mod:
    1) Kademeli (trailing_graduated=true):
       Kar seviyesine gore artan oranda kilitleme.
       Faz 1 (breakeven) : kar>0     -> SL=entry (zarar yok)
       Faz 2 (erken)     : kar>=100  -> karin %30'u kilitli
       Faz 3 (normal)    : kar>=250  -> karin %50'si kilitli
       Faz 4 (agresif)   : kar>=500  -> karin %70'i kilitli

    2) Eski mod (trailing_graduated=false):
       Sabit gap: lock = kar - gap

    Returns:
        Yeni SL degeri, kosul saglanmiyorsa None.
    """
    total_pnl = profit + swap

    # -- Kademeli Oran Sistemi
    if self._trailing_graduated:
        if total_pnl <= 0:
            return None

        lock_ratio = 0.0
        tier_label = "breakeven"
        for tier in self._trailing_tiers:
            if total_pnl >= tier["min_profit"]:
                lock_ratio = tier["lock_ratio"]
                tier_label = tier.get("label", "?")
                break

        lock_trl = total_pnl * lock_ratio

        logger.debug(
            f"Kademeli trailing [{hp.symbol}] t={hp.ticket}: "
            f"kar={total_pnl:.0f} TRY, faz={tier_label}, "
            f"oran=%{lock_ratio*100:.0f}, kilit={lock_trl:.0f} TRY"
        )
    else:
        # -- Eski sabit gap modu
        gap = self._trailing_profit_gap
        if total_pnl <= gap:
            return None
        lock_trl = total_pnl - gap

    # TRY -> fiyat mesafesi donusumu (symbol_info'dan kontrat carpani)
    sym = self.mt5.get_symbol_info(hp.symbol)
    if sym is None or sym.trade_contract_size <= 0:
        logger.warning(
            f"Profit trailing: symbol_info alinamadi [{hp.symbol}] "
            f"- ATR moduna fallback"
        )
        return self._calc_atr_trailing_sl(hp, current_price)

    # profit = price_diff x volume x contract_size (VIOP basit formul)
    trl_per_point = hp.volume * sym.trade_contract_size
    if trl_per_point <= 0:
        return None

    lock_points = lock_trl / trl_per_point

    # SL = giris fiyatindan lock_points kadar kar yonunde
    if hp.direction == "BUY":
        new_sl = hp.entry_price + lock_points
    else:
        new_sl = hp.entry_price - lock_points

    return new_sl
