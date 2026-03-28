"""Silinen fonksiyon: _calc_atr_trailing_sl
Kaynak: engine/h_engine.py satır 978-998
Silme tarihi: 2026-03-28
Neden: PRİMNET tek trailing modu olarak belirlendi
"""


def _calc_atr_trailing_sl(
    self, hp, current_price: float,
) -> float | None:
    """ATR bazlı trailing SL hesapla (klasik mod).

    Koşul: kâr >= trailing_trigger x entry_atr
    Hesap: SL = current_price -/+ distance x entry_atr

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
