"""Silinen kod: _check_trailing icindeki ATR/profit dallanmalari ve min/max clamp blogu
Kaynak: engine/h_engine.py satir 1101-1139
Silme tarihi: 2026-03-28
Neden: PRiMNET tek trailing modu olarak belirlendi. ATR/profit dallari ve
       min/max clamp blogu (sadece ATR/profit icin gecerliydi) kaldirildi.
"""

# --- _check_trailing icindeki mod dallanmasi (satir 1101-1106) ---

if self._trailing_mode == "primnet":
    new_sl = self._calc_primnet_trailing_sl(hp, current_price)
elif self._trailing_mode == "profit":
    new_sl = self._calc_profit_trailing_sl(hp, current_price, profit, swap)
else:
    new_sl = self._calc_atr_trailing_sl(hp, current_price)

# --- min/max clamp blogu (satir 1113-1139) ---
# PRiMNET modunda atlaniyordu, sadece ATR/profit icin gecerliydi

if self._trailing_mode != "primnet":
    # Min/Max trailing mesafe siniri (VIOP Rapor uyumu)
    if current_price > 0:
        min_dist = current_price * self._trailing_min_pct
        max_dist = current_price * self._trailing_max_pct
        if hp.direction == "BUY":
            distance = current_price - new_sl
            clamped = max(min_dist, min(distance, max_dist))
            new_sl = current_price - clamped
        else:
            distance = new_sl - current_price
            clamped = max(min_dist, min(distance, max_dist))
            new_sl = current_price + clamped

    # -- Breakeven Floor (v5.8)
    if hp.direction == "SELL" and new_sl > hp.entry_price:
        new_sl = hp.entry_price
        logger.debug(
            f"Breakeven floor uygulandi [{hp.symbol}] t={hp.ticket}: "
            f"SL entry'ye cekildi ({hp.entry_price:.2f})"
        )
    elif hp.direction == "BUY" and new_sl < hp.entry_price:
        new_sl = hp.entry_price
        logger.debug(
            f"Breakeven floor uygulandi [{hp.symbol}] t={hp.ticket}: "
            f"SL entry'ye cekildi ({hp.entry_price:.2f})"
        )
