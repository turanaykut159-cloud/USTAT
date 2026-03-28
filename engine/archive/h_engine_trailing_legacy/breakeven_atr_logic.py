"""Silinen kod: _check_breakeven ATR breakeven mantigi
Kaynak: engine/h_engine.py satir 882-972
Silme tarihi: 2026-03-28
Neden: PRiMNET modunda breakeven atlanir, Faz 1 trailing baslan calisir.
       ATR breakeven artik kullanilmiyor.
"""

# --- _check_breakeven icindeki ATR breakeven blogu (satir 882-972) ---

# Fiyat bazli kar hesabi (yon dikkate alinir)
price_diff = self._price_profit(hp, current_price)
breakeven_threshold = self._breakeven_atr_mult * hp.entry_atr

if price_diff < breakeven_threshold:
    return

# Breakeven SL: giris fiyati
new_sl = hp.entry_price

# Mevcut SL zaten giris fiyatinda veya daha iyiyse guncelleme yapma
if hp.direction == "BUY" and hp.current_sl >= new_sl:
    hp.breakeven_hit = True
    return
if hp.direction == "SELL" and hp.current_sl <= new_sl:
    hp.breakeven_hit = True
    return

# MT5'e yaz (native mod) veya sadece internal guncelle (software mod)
if self._native_sltp:
    modify_result = self.mt5.modify_position(hp.ticket, sl=new_sl)
    if modify_result is None:
        retry_key = f"be_modify_{hp.ticket}"
        fail_count = self._close_retry_counts.get(retry_key, 0) + 1
        self._close_retry_counts[retry_key] = fail_count
        logger.warning(
            f"Breakeven SL modify basarisiz: ticket={hp.ticket} {hp.symbol} "
            f"(deneme {fail_count}/3)"
        )
        if fail_count >= 3:
            logger.critical(
                f"Breakeven SL 3x modify basarisiz: ticket={hp.ticket} {hp.symbol} "
                f"-- software SL moduna geciliyor"
            )
            self._close_retry_counts.pop(retry_key, None)
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
                    "message": "Native modify 3x basarisiz, software SL aktif",
                },
            )
            logger.warning(
                f"Breakeven SL (software fallback): ticket={hp.ticket} {hp.symbol} "
                f"SL {old_sl:.4f} -> {new_sl:.4f}"
            )
        return
    else:
        self._close_retry_counts.pop(f"be_modify_{hp.ticket}", None)
        verified_sl = self._verify_mt5_sl(hp.ticket)
        if verified_sl is not None and abs(verified_sl - new_sl) > 0.01:
            logger.error(
                f"Breakeven SL DESYNC: ticket={hp.ticket} {hp.symbol} "
                f"istenen={new_sl:.4f} MT5={verified_sl:.4f} -- MT5 degeri kullaniliyor"
            )
            new_sl = verified_sl

old_sl = hp.current_sl
hp.current_sl = new_sl
hp.breakeven_hit = True

# DB guncelle
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
    f"SL {old_sl:.4f} -> {new_sl:.4f} (fiyat={current_price:.4f}) "
    f"[{'native' if self._native_sltp else 'software'}]"
)
